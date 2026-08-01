"""Resource-aware Ollama request options.

Local model calls should leave room for the OS, Qt, Maya, Unreal, and menus.
These helpers keep that policy centralized so callers do not each invent their
own defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any


@dataclass(frozen=True)
class OllamaGenerationBudget:
    """Concrete local-model budget for one synthesis stage."""

    tier: str
    model_tier: str
    num_ctx: int
    num_predict: int
    timeout_seconds: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "model_tier": self.model_tier,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "timeout_seconds": self.timeout_seconds,
            "reason": self.reason,
        }


def build_ollama_options(
    *,
    num_ctx: int,
    num_predict: int,
    settings: dict[str, Any] | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    settings = dict(settings or {})
    resolved_temperature = (
        float(temperature)
        if temperature is not None
        else float(settings.get("ollama_temperature", 0.2))
    )
    options: dict[str, Any] = {
        "temperature": resolved_temperature,
        "num_ctx": int(num_ctx),
        "num_predict": int(num_predict),
    }
    if resolved_temperature == 0.0:
        options["top_k"] = 1
        options["top_p"] = 0.1

    num_thread = _positive_int(settings.get("ollama_num_thread"))
    if num_thread is None:
        cpu_count = os.cpu_count() or 4
        num_thread = max(1, min(8, cpu_count - 2))
    options["num_thread"] = num_thread

    num_gpu = _optional_int(settings.get("ollama_num_gpu"))
    if num_gpu is not None:
        options["num_gpu"] = num_gpu

    return options



def choose_semantic_understanding_budget(
    *,
    settings: dict[str, Any] | None = None,
) -> OllamaGenerationBudget:
    """Return the fixed micro budget for the first semantic hypothesis."""
    settings = dict(settings or {})
    max_ctx = _positive_int(settings.get("ollama_semantic_max_num_ctx")) or 2048
    max_predict = _positive_int(settings.get("ollama_semantic_max_num_predict")) or 384
    max_timeout = _positive_int(settings.get("ollama_semantic_timeout_seconds")) or 30
    return OllamaGenerationBudget(
        tier="micro",
        model_tier="semantic",
        num_ctx=min(max_ctx, 2048),
        num_predict=min(max_predict, 384),
        timeout_seconds=min(max_timeout, 30),
        reason="cheap semantic hypothesis before context-aware planning",
    )


def build_semantic_understanding_options(
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic options for the small semantic model."""
    budget = choose_semantic_understanding_budget(settings=settings)
    options = build_ollama_options(
        num_ctx=budget.num_ctx,
        num_predict=budget.num_predict,
        settings=settings,
        temperature=0.0,
    )
    # Encourage repeatable JSON classification where supported by Ollama.
    options["top_k"] = 1
    options["top_p"] = 0.1
    options["repeat_penalty"] = 1.0
    return options


def choose_ollama_generation_budget(
    *,
    prompt: str = "",
    evidence_text: str = "",
    route: str = "",
    llm_mode: str = "",
    confidence: float | None = None,
    settings: dict[str, Any] | None = None,
) -> OllamaGenerationBudget:
    """Choose a synthesis budget that scales primarily with uncertainty.

    Deterministic lookup should remain quick. When a prompt is planning-heavy or
    the system is unsure about the route/target, give the model more context and
    time. Large retrieved knowledge is a secondary signal: it helps only when the
    answer is not already certain enough.
    """

    settings = dict(settings or {})
    text = prompt or ""
    evidence = evidence_text or ""
    lower = text.lower()
    evidence_chars = len(evidence)
    word_count = len(text.split())
    complexity = 0
    uncertainty = 0
    complexity += 1 if word_count >= 80 else 0
    complexity += 1 if word_count >= 180 else 0
    complexity += 1 if evidence_chars >= 4000 else 0
    complexity += 1 if evidence_chars >= 10000 else 0
    complexity += 1 if route in {"target_discovery", "unreal_capability", "action_graph"} else 0
    complexity += 1 if (llm_mode or "").lower() in {"required", "synthesis", "force", "must"} else 0
    if confidence is not None:
        try:
            parsed_confidence = float(confidence)
        except Exception:
            parsed_confidence = 1.0
        if parsed_confidence < 0.55:
            uncertainty = 3
            complexity += 3
        elif parsed_confidence < 0.75:
            uncertainty = 2
            complexity += 2
        elif parsed_confidence < 0.9:
            uncertainty = 1
            complexity += 1
    if any(term in lower for term in ("plan", "architecture", "implement", "edit", "debug", "troubleshoot", "rollback", "validate")):
        complexity += 1

    max_ctx = _positive_int(settings.get("ollama_max_num_ctx")) or 8192
    max_predict = _positive_int(settings.get("ollama_max_num_predict")) or 1200
    max_timeout = _positive_int(settings.get("ollama_max_timeout_seconds")) or 240
    prompt_lower = (prompt or "").lower()
    is_code_generation = any(
        f" {verb} " in f" {prompt_lower} "
        for verb in ("add", "build", "create", "generate", "implement", "provide", "return", "write")
    ) and any(
        artifact in prompt_lower
        for artifact in (" class", " code", " dialog", " function", " method", " script", " ui", " widget")
    )

    if is_code_generation:
        return OllamaGenerationBudget(
            tier="code",
            model_tier="standard",
            num_ctx=min(max_ctx, 6144),
            num_predict=min(max_predict, 1000),
            timeout_seconds=min(max_timeout, 180),
            reason="complete code generation with enough output capacity for requested declarations and behavior",
        )

    if complexity >= 5:
        return OllamaGenerationBudget(
            tier="deep",
            model_tier="strong" if uncertainty >= 2 else "standard",
            num_ctx=min(max_ctx, 8192),
            num_predict=min(max_predict, 1100),
            timeout_seconds=min(max_timeout, 240),
            reason="uncertain synthesis" if uncertainty >= 2 else "large knowledge-heavy synthesis",
        )
    if complexity >= 3:
        return OllamaGenerationBudget(
            tier="standard",
            model_tier="standard",
            num_ctx=min(max_ctx, 6144),
            num_predict=min(max_predict, 256),
            timeout_seconds=min(max_timeout, 180),
            reason="moderate synthesis with retrieved evidence",
        )
    return OllamaGenerationBudget(
        tier="small",
        model_tier="small",
        num_ctx=min(max_ctx, 4096),
        num_predict=min(max_predict, 512),
        timeout_seconds=min(max_timeout, 120),
        reason="short synthesis or presentation pass",
    )


def choose_project_edit_coder_profile(
    *,
    prompt: str,
    target_count: int = 1,
    repair_attempt: int = 0,
) -> str:
    """Choose the smallest coder tier appropriate for one edit stage."""

    lower = str(prompt or "").lower()
    if repair_attempt >= 4:
        if re.search(
            r"\b(entire tool|whole tool|new tool|fresh tool|from scratch|large restructure|"
            r"major refactor|architecture rewrite|new application|new app|multi[- ]file|cross[- ]module)\b",
            lower,
        ):
            return "quality"
        return "standard"
    if repair_attempt in {2, 3}:
        return "standard"
    if repair_attempt == 1:
        return "small"
    if re.search(
        r"\b(entire tool|whole tool|new tool|fresh tool|from scratch|large restructure|"
        r"major refactor|architecture rewrite|new application|new app)\b",
        lower,
    ):
        return "quality"
    if target_count >= 3 or re.search(
        r"\b(multi[- ]file|across .* files|integration|restructure|architecture|"
        r"cross[- ]module|pipeline from scratch)\b",
        lower,
    ):
        return "standard"
    if re.search(
        r"\b(docstring|documentation|rename|typo|type hint|small guard|single condition)\b",
        lower,
    ):
        return "micro"
    return "micro"


def ollama_keep_alive(settings: dict[str, Any] | None = None) -> str | int:
    settings = dict(settings or {})
    value = settings.get("ollama_keep_alive", "10m")
    if value in (None, ""):
        return "10m"
    return value


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None
