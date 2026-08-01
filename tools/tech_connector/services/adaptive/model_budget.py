from __future__ import annotations

"""Translate adaptive execution state into concrete local-model options."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AdaptiveModelBudget:
    stage_type: str
    model_tier: str
    model_name: str
    num_ctx: int
    num_predict: int
    timeout_seconds: int
    keep_alive: str | int
    reasoning_mode: str
    max_concurrent: int = 1
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def choose_adaptive_model_budget(
    state: Any,
    *,
    stage_type: str,
    settings: dict[str, Any] | None = None,
    selected_model: str | None = None,
) -> AdaptiveModelBudget:
    settings = dict(settings or {})
    budget = state.budget
    prediction = state.prediction
    stage = (stage_type or "synthesis").lower()
    uncertainty = 1.0 - min(
        float(state.confidence.intent),
        float(state.confidence.target or 0.0),
        float(state.confidence.knowledge or 0.0),
    )

    if stage in {"visual", "visual_media", "image", "video", "camera"}:
        tier = "local_visual"
        model = (
            settings.get("router_visual_media")
            or settings.get("visual_media_model")
            or settings.get("fast_general_model")
            or settings.get("router_fast_llm_model")
        )
        predict = max(384, min(budget.reserved_output_tokens, 900))
        ctx = min(max(4096, budget.token_budget), int(settings.get("ollama_max_num_ctx") or 8192))
        reasoning = "standard"
    elif stage in {"intent", "routing", "presentation", "summary"}:
        tier = "local_fast"
        model = settings.get("router_fast_llm_model") or settings.get("router_local_plan") or settings.get("general_model")
        predict = min(384, budget.reserved_output_tokens)
        ctx = min(4096, budget.token_budget)
        reasoning = "minimal"
    elif stage in {"patch", "patch_generation", "code"}:
        tier = "local_code"
        model = settings.get("router_local_code") or settings.get("code_model")
        predict = max(512, min(budget.reserved_output_tokens, prediction.predicted_output_tokens or 1600))
        ctx = min(max(4096, budget.token_budget), int(settings.get("ollama_max_num_ctx") or 8192))
        reasoning = "standard" if prediction.complexity_score < 0.7 else "deep"
    elif uncertainty > 0.45 or prediction.complexity_score >= 0.72:
        tier = "local_deep"
        model = settings.get("router_local_deep") or settings.get("model")
        predict = max(700, min(budget.reserved_output_tokens, 1400))
        ctx = min(max(6144, budget.token_budget), int(settings.get("ollama_max_num_ctx") or 8192))
        reasoning = "deep"
    else:
        tier = "local_plan"
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
        predict = max(384, min(budget.reserved_output_tokens, 900))
        ctx = min(max(4096, budget.token_budget), int(settings.get("ollama_max_num_ctx") or 8192))
        reasoning = budget.reasoning_level

    timeout = min(
        max(60, int(budget.runtime_budget_ms / 1000)),
        int(settings.get("ollama_max_timeout_seconds") or 300),
    )
    keep_alive = settings.get("ollama_keep_alive", "10m")
    return AdaptiveModelBudget(
        stage_type=stage_type,
        model_tier=tier,
        model_name=str(model or selected_model or settings.get("model") or "ollama:qwen2.5-coder:7b"),
        num_ctx=max(512, int(ctx)),
        num_predict=max(32, int(predict)),
        timeout_seconds=max(30, timeout),
        keep_alive=keep_alive,
        reasoning_mode=reasoning,
        max_concurrent=1,
        reason=f"stage={stage}; complexity={prediction.complexity_score:.2f}; uncertainty={uncertainty:.2f}",
    )
