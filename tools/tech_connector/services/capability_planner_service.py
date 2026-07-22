"""Capability Planner — orchestrates gap analysis and acquisition planning.

Entry point for the Capability Acquisition & Gap Analysis system.

Pipeline:
  1. analyze_prompt()        — check if all required capabilities already exist
  2. decompose_tasks()       — extract capability requirements from the prompt
  3. detect_gaps()           — compare against CapabilityRegistry
  4. AcquisitionEngine       — discover + rank strategies for missing capabilities

Fast path (< 5ms): keyword heuristics for simple/known prompts.
Fallback path: local Ollama model (qwen2.5-coder:14b) for complex decomposition.

This module runs as a pre-dispatch gate in main_window_chat_runtime.py.
If no gaps are detected it returns immediately with zero UI impact.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# CapabilityRequirement
# ---------------------------------------------------------------------------

@dataclass
class CapabilityRequirement:
    """A single capability required to fulfil a user prompt."""

    name: str
    category: str          # animation | plugin | tool | api | asset | docs | function
    description: str
    required_by: str       # which task decomposition step needs this
    is_blocking: bool      # can the prompt proceed without it?


# ---------------------------------------------------------------------------
# CapabilityPlanResult
# ---------------------------------------------------------------------------

@dataclass
class CapabilityPlanResult:
    """Full result of the capability gap analysis pipeline."""

    plan_id: str
    prompt: str
    task_steps: list           # decomposed capability requirement strings
    satisfied: list            # list of CapabilityRequirement (found in registry)
    missing: list              # list of CapabilityRequirement (not found)
    acquisition_strategies: list  # list of AcquisitionStrategy, ranked
    recommended_strategy_id: str
    estimated_setup_minutes: int
    can_proceed_without: bool  # True if all gaps are non-blocking

    @property
    def has_gaps(self) -> bool:
        return len(self.missing) > 0

    def format_for_chat(self) -> str:
        """Format the gap analysis result as markdown for display in the chat panel."""
        if not self.has_gaps:
            return ""

        lines = [
            "## 🔍 Capability Gap Analysis\n",
            f"**Request:** {self.prompt[:120]}{'...' if len(self.prompt) > 120 else ''}\n",
        ]

        if self.satisfied:
            lines.append("**✔ Already available:**")
            for req in self.satisfied:
                lines.append(f"  ✔ {req.name}")
            lines.append("")

        if self.missing:
            lines.append("**✖ Missing capabilities:**")
            for req in self.missing:
                blocking = " *(blocking)*" if req.is_blocking else ""
                lines.append(f"  ✖ {req.name}{blocking}")
            lines.append("")

        if self.acquisition_strategies:
            lines.append("**Recommended acquisition plan:**\n")
            from tech_connector.services.capability_acquisition_service import format_strategy_summary
            for i, strategy in enumerate(self.acquisition_strategies[:5], 1):
                lines.append(f"{i}. {format_strategy_summary(strategy)}\n")

        if self.estimated_setup_minutes:
            lines.append(f"**Estimated setup:** ~{self.estimated_setup_minutes} min")

        lines.append("\nType **yes** to proceed with acquisition, or **skip** to continue without.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Keyword-based task decomposition (fast path)
# ---------------------------------------------------------------------------

# Known capability domains and their trigger keywords
_CAPABILITY_DOMAINS: dict = {
    "animation": ["animation", "anim", "motion", "keyframe", "mocap", "capture", "retarget", "fbx", "bvh",
                  "pose", "skeleton", "rig", "rigging", "walk", "run", "jump", "climb", "idle"],
    "motion_matching": ["motion matching", "motion match", "pose search", "motion database"],
    "ik": ["ik", "inverse kinematics", "full body ik", "fbik", "ccd ik"],
    "physics": ["physics", "cloth", "rigid body", "collision", "ragdoll", "softbody", "fluid", "destruction"],
    "blueprint": ["blueprint", "bp", "event graph", "actor", "component", "gameplay"],
    "material": ["material", "shader", "texture", "uv", "pbr", "normal map", "roughness"],
    "plugin": ["plugin", "extension", "addon", "add-on", "module", "package"],
    "import": ["import", "fbx", "obj", "usd", "gltf", "alembic", "abc"],
    "export": ["export", "publish", "bake", "save as"],
    "procedural": ["procedural", "houdini", "vex", "vop", "sop", "dop"],
    "ai_service": ["video to animation", "text to animation", "motion generation", "ai retarget",
                   "pose estimation", "audio driven"],
    "asset": ["asset", "megascan", "quixel", "fab", "marketplace", "store"],
    "docs": ["documentation", "api reference", "how to", "tutorial", "guide"],
}

_MULTI_WORD_TERMS = [
    "motion matching", "motion database", "pose search", "full body ik",
    "inverse kinematics", "video to animation", "text to animation",
    "audio driven", "motion generation",
]

# Minimum token length for keyword matching
_MIN_TOKEN_LEN = 3

# Threshold: if keyword matching finds fewer than this many requirements, call the LLM
_LLM_FALLBACK_THRESHOLD = 2


def decompose_tasks_keywords(prompt: str) -> list:
    """Fast keyword-based task decomposition. Returns list of capability requirement strings."""
    lower = prompt.lower()
    found = set()

    # Check multi-word terms first
    for term in _MULTI_WORD_TERMS:
        if term in lower:
            found.add(term)

    # Single-word keyword scan
    tokens = set(re.findall(r"[a-z][a-z0-9_]{2,}", lower))
    for domain, keywords in _CAPABILITY_DOMAINS.items():
        for kw in keywords:
            if " " in kw:
                continue  # already handled above
            if kw in tokens or kw in lower:
                found.add(domain)
                break

    return sorted(found)


def decompose_tasks_llm(prompt: str) -> list:
    """Fallback: use qwen2.5-coder:14b via Ollama to decompose complex prompts."""
    try:
        import urllib.request
        import json
        from tech_connector.services.ollama_service import OLLAMA_BASE_URL, FAST_CODE_MODEL, model_for_role

        system = (
            "You are a capability analyzer for a game development AI assistant. "
            "Given a user prompt, list the distinct technical capabilities required to fulfill it. "
            "Output ONLY a JSON array of short capability names (snake_case, max 5 words each). "
            "Example: [\"motion_matching\", \"pose_search\", \"animation_database\", \"ik_retargeting\"]\n"
            "Do not explain. Output only the JSON array."
        )

        model_name = model_for_role("code", FAST_CODE_MODEL)
        from tech_connector.services.llm_router_service import generate_llm_response
        raw = generate_llm_response(
            model=model_name,
            prompt=f"User prompt: {prompt}\n\nRequired capabilities (JSON array):",
            system=system,
            response_format="json",
            options={"temperature": 0.1, "num_predict": 150},
            timeout=15
        ).strip()
        # Extract JSON array from response
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            items = json.loads(match.group())
            if isinstance(items, list):
                return [str(i).lower().replace(" ", "_") for i in items if isinstance(i, str)]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

def analyze_prompt(prompt: str, registry, project_roots: Optional[list] = None) -> CapabilityPlanResult:
    """Full capability gap analysis pipeline.

    Returns immediately (no gaps) or with a populated CapabilityPlanResult.
    Fast path: keyword heuristics < 5ms.
    Slow path: Ollama LLM decomposition (triggered only when < 2 requirements found).
    """
    plan_id = str(uuid.uuid4())[:8]

    # --- Seed registry if not yet done ---
    if project_roots and not getattr(registry, "_seeded", False):
        try:
            registry.scan_internals(project_roots)
            registry.save()
        except Exception:
            pass

    # --- Task decomposition (fast path first) ---
    task_steps = decompose_tasks_keywords(prompt)

    # Fallback to LLM if we found very few requirements and prompt looks complex
    if len(task_steps) < _LLM_FALLBACK_THRESHOLD and _prompt_is_complex(prompt):
        llm_steps = decompose_tasks_llm(prompt)
        if llm_steps:
            # Merge, preferring LLM results for complex prompts
            merged = set(task_steps) | set(llm_steps)
            task_steps = sorted(merged)

    if not task_steps:
        # Nothing to analyze — pass straight through
        return CapabilityPlanResult(
            plan_id=plan_id,
            prompt=prompt,
            task_steps=[],
            satisfied=[],
            missing=[],
            acquisition_strategies=[],
            recommended_strategy_id="",
            estimated_setup_minutes=0,
            can_proceed_without=True,
        )

    # --- Gap detection ---
    satisfied, missing = detect_gaps(task_steps, registry)

    if not missing:
        # All requirements satisfied — zero UI impact
        return CapabilityPlanResult(
            plan_id=plan_id,
            prompt=prompt,
            task_steps=task_steps,
            satisfied=satisfied,
            missing=[],
            acquisition_strategies=[],
            recommended_strategy_id="",
            estimated_setup_minutes=0,
            can_proceed_without=True,
        )

    # --- Acquisition strategy discovery ---
    from tech_connector.services.capability_acquisition_service import AcquisitionEngine
    try:
        root_path = Path(project_roots[0]) if project_roots else Path(".")
        engine = AcquisitionEngine(registry, root_path)
        missing_names = [r.name for r in missing]
        strategies = engine.discover_strategies(missing_names)
    except Exception:
        strategies = []

    recommended_id = strategies[0].id if strategies else ""
    total_minutes = sum(
        s.estimated_minutes for s in strategies[:3] if s.phase == 1
    )
    # Determine if prompt can partially proceed
    can_proceed = all(not r.is_blocking for r in missing)

    return CapabilityPlanResult(
        plan_id=plan_id,
        prompt=prompt,
        task_steps=task_steps,
        satisfied=satisfied,
        missing=missing,
        acquisition_strategies=strategies,
        recommended_strategy_id=recommended_id,
        estimated_setup_minutes=total_minutes,
        can_proceed_without=can_proceed,
    )


def detect_gaps(
    task_steps: list,
    registry,
) -> tuple:
    """Compare decomposed task requirements against the registry.

    Returns (satisfied: list[CapabilityRequirement], missing: list[CapabilityRequirement]).
    """
    satisfied = []
    missing = []

    for step in task_steps:
        req = CapabilityRequirement(
            name=step.replace("_", " ").title(),
            category=_infer_category(step),
            description=f"Capability required: {step}",
            required_by="prompt",
            is_blocking=_is_blocking_capability(step),
        )
        if registry.satisfies(step):
            satisfied.append(req)
        else:
            missing.append(req)

    return satisfied, missing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPLEX_PROMPT_PATTERNS = [
    r"\band\b.*\band\b",       # multiple conjunctions
    r"\bthen\b",               # sequential steps
    r"\bafter\b",
    r"\bfollowed by\b",
    r"\bpipeline\b",
    r"\bworkflow\b",
    r"\bsystem\b",
    r"\bintegrat\b",
]

_BLOCKING_CATEGORIES = {"import", "plugin", "bridge", "animation"}


def _prompt_is_complex(prompt: str) -> bool:
    lower = prompt.lower()
    word_count = len(prompt.split())
    if word_count > 12:
        return True
    for pattern in _COMPLEX_PROMPT_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def _infer_category(step: str) -> str:
    if any(kw in step for kw in ("import", "export", "fbx", "usd", "gltf")):
        return "import"
    if any(kw in step for kw in ("plugin", "extension", "addon")):
        return "plugin"
    if any(kw in step for kw in ("animation", "motion", "mocap", "pose")):
        return "animation"
    if any(kw in step for kw in ("docs", "documentation", "api")):
        return "docs"
    if any(kw in step for kw in ("asset", "mesh", "texture", "material")):
        return "asset"
    return "tool"


def _is_blocking_capability(step: str) -> bool:
    """Capabilities that are blocking — prompt cannot run at all without them."""
    for cat in _BLOCKING_CATEGORIES:
        if cat in step:
            return True
    return False
