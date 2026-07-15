"""Model router for Tech Connector.

Upgraded router with:
- Multi-tier model table  (embed → local-code → local-plan → local-deep → active)
- Complexity scorer       (keyword density + Unreal subsystem detection)
- Automatic Unreal escalation for hard tasks (Blueprint, Control Rig, Motion
  Matching, animation, gameplay) — uses the deepest available local model
  so you never need to rely on credit-based cloud services.
- Per-call override support and allow_local_only flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteDecision:
    """Resolved routing choice for a user prompt."""
    task_role: str
    session_role: str
    model: str
    tier: str
    reason: str
    complexity: int  # 0-10


@dataclass
class ModelTiers:
    """Available model tiers, ordered from cheapest to most capable.

    Any tier set to "" means it is unavailable and will be skipped.
    `active` is whatever model the user currently has selected in the UI.
    """
    embed: str      = "nomic-embed-text"
    local_code: str = "qwen2.5-coder:1.5b"
    local_plan: str = "llama3:latest"
    local_deep: str = "qwen3:14b"
    active: str     = ""             # set at runtime to the UI-selected model

    def __post_init__(self):
        try:
            from services.settings_service import load_settings
            settings = load_settings()
            self.embed = settings.get("router_embed", self.embed)
            self.local_code = settings.get("router_local_code", self.local_code)
            self.local_plan = settings.get("router_local_plan", self.local_plan)
            self.local_deep = settings.get("router_local_deep", self.local_deep)
        except Exception:
            pass

    def best_available(self, minimum_tier: str = "local_plan") -> tuple[str, str]:
        """Return (tier_name, model_name) for the best non-empty tier at or
        above *minimum_tier*.  Falls back toward `active` if lower tiers are
        empty.
        """
        order = ["local_code", "local_plan", "local_deep", "active"]
        start = order.index(minimum_tier) if minimum_tier in order else 0
        for tier in order[start:]:
            model = getattr(self, tier, "")
            if model:
                return tier, model
        # Last resort: whatever is active
        return "active", self.active or ""


# ---------------------------------------------------------------------------
# Complexity scorer
# ---------------------------------------------------------------------------

# Keywords that push complexity up by 1 each
_COMPLEXITY_KEYWORDS: List[tuple[int, tuple[str, ...]]] = [
    # +1  — basic Unreal context
    (1, ("unreal", "blueprint", "ue5", "ue4", "uproject")),
    # +2  — intermediate subsystems
    (2, ("control rig", "animation blueprint", "skeletal mesh",
         "asset import", "level", "gameplay")),
    # +3  — hard architecture / composition tasks
    (3, ("motion matching", "blueprint architecture", "blueprint graph",
         "tool composition", "workflow", "compose", "refactor architecture",
         "generate blueprint", "create blueprint", "wire nodes",
         "ik rig", "full body ik", "retargeter")),
]


def _contains_unreal_bp_reference(prompt: str) -> bool:
    """Detect Unreal Blueprint shorthand without confusing Blender's `bpy`."""
    return bool(re.search(r"\bbp(?:\b|[_\-\s])", prompt or "", re.IGNORECASE))


# Unreal/in-engine subsystems that may escalate to local_deep. Workflow and
# composition alone are intentionally not deep triggers; indexed action graphs
# should handle those cheaply before any LLM is involved.
UNREAL_DEEP_TRIGGERS = frozenset({
    "blueprint", "control rig", "motion matching", "animation blueprint",
    "ik rig", "full body ik", "retargeter", "gameplay framework",
    "blueprint architecture", "generate blueprint", "create blueprint",
    "wire blueprint", "anim graph", "state machine", "niagara stack",
})

COMPLEX_CODE_TRIGGERS = frozenset({
    "architecture", "large refactor", "refactor architecture", "cross-module",
    "multi-file", "migration", "threading", "async", "concurrency",
    "performance regression", "memory leak", "deadlock", "race condition",
})


class ComplexityScorer:
    """Score a prompt 0-10; higher → more capable model needed."""

    @staticmethod
    def score(prompt: str) -> int:
        text = (prompt or "").lower()
        total = 0
        for weight, keywords in _COMPLEXITY_KEYWORDS:
            hits = sum(1 for kw in keywords if kw in text)
            total += hits * weight
        if _contains_unreal_bp_reference(prompt):
            total += 3
        return min(10, total)

    @staticmethod
    def needs_deep_model(prompt: str) -> bool:
        text = (prompt or "").lower()
        return _contains_unreal_bp_reference(prompt) or any(trigger in text for trigger in UNREAL_DEEP_TRIGGERS)

    @staticmethod
    def needs_deep_code_model(prompt: str, threshold: int = 7) -> bool:
        text = (prompt or "").lower()
        if any(trigger in text for trigger in COMPLEX_CODE_TRIGGERS):
            return True
        return ComplexityScorer.score(prompt) >= int(threshold or 7)


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

class AIRouter:
    EXPLICIT_HOST_KEYWORDS = (
        ("maya",              ("maya", "cmds", "pymel")),
        ("unreal",            ("unreal", "ue", "uproject", "uasset")),
        ("blender",           ("blender", "bpy", "blend file")),
        ("substance_painter", ("substance painter", "substance", "painter")),
        ("motionbuilder",     ("motionbuilder", "motion builder", "mobu")),
        ("unity",             ("unity", "unityeditor")),
    )

    ROLE_KEYWORDS = (
        ("unreal",            ("unreal", "control rig", "blueprint", "skeletal mesh", "uproject", "uasset",
                               "motion matching", "animation blueprint", "ik rig")),
        ("maya",              ("maya", "cmds", "pymel", "rig", "joint", "skincluster", "hik", "humanik")),
        ("blender",           ("blender", "bpy", "blend file", "geometry nodes")),
        ("substance_painter", ("substance painter", "substance", "texture set", "texture sets", "sbsar")),
        ("motionbuilder",     ("motionbuilder", "motion builder", "mobu", "fbx take", "takes")),
        ("unity",             ("unity", "gameobject", "prefab", "scene object", "unityeditor")),
        ("debug",             ("fix", "bug", "traceback", "error", "exception", "debug", "crash", "failing")),
        ("code",              ("implement", "refactor", "edit", "replace", "function", "class", "python", "patch")),
        ("docs",              ("docs", "readme", "document", "summarize", "explain")),
    )

    SESSION_BY_TASK_ROLE = {
        "general":            "plan",
        "plan":               "plan",
        "docs":               "plan",
        "code":               "code",
        "debug":              "code",
        "maya":               "dcc",
        "unreal":             "dcc",
        "blender":            "dcc",
        "substance_painter":  "dcc",
        "motionbuilder":      "dcc",
        "unity":              "dcc",
    }

    # Generic keyword density no longer escalates to deep by itself in normal use.
    # Deep routing is reserved for in-engine triggers and explicitly allowed
    # complex-code work.
    DEEP_THRESHOLD = 99

    @staticmethod
    def choose_role(prompt: str, editor_active: bool = False) -> str:
        text = (prompt or "").lower()

        if editor_active:
            return "code"

        if _contains_unreal_bp_reference(prompt):
            return "unreal"

        for role, keywords in AIRouter.EXPLICIT_HOST_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return role

        for role, keywords in AIRouter.ROLE_KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return role

        return "plan"

    @staticmethod
    def session_role_for_task(task_role: str) -> str:
        return AIRouter.SESSION_BY_TASK_ROLE.get(task_role or "general", "plan")

    @staticmethod
    def route_prompt(
        prompt: str,
        editor_active: bool = False,
        tiers: Optional[ModelTiers] = None,
        allow_local_only: bool = False,
        deep_route_scope: str = "engine_complex_only",
        deep_code_complexity_threshold: int = 7,
        get_model_for_role: Optional[Callable[[str], str]] = None,
    ) -> RouteDecision:
        """Route *prompt* to the most appropriate model tier.

        Priority:
        1. If `allow_local_only=True`, cap at local_deep regardless of complexity.
        2. If the prompt contains a hard Unreal trigger, escalate to local_deep.
        3. Use complexity score to choose between local_code / local_plan / local_deep.
        4. Fall back to `active` (currently selected model) only if `allow_local_only=False`
           and a deeper local model is unavailable.
        """
        if tiers is None:
            tiers = ModelTiers()

        task_role   = AIRouter.choose_role(prompt, editor_active=editor_active)
        session_role = AIRouter.session_role_for_task(task_role)
        complexity  = ComplexityScorer.score(prompt)
        needs_engine_deep = ComplexityScorer.needs_deep_model(prompt)
        needs_code_deep = ComplexityScorer.needs_deep_code_model(prompt, deep_code_complexity_threshold)
        deep_scope = (deep_route_scope or "engine_complex_only").strip().lower()
        allow_deep_for_code = deep_scope in {"engine_and_complex_code", "all_complex", "always"}
        needs_deep = needs_engine_deep or (
            allow_deep_for_code and task_role in {"code", "debug"} and needs_code_deep
        )

        # ---- Select minimum tier ----------------------------------------
        if editor_active:
            min_tier = "local_code"
            reason   = "editor is active → code tier"
        elif needs_deep:
            min_tier = "local_deep"
            reason   = f"Deep-work trigger detected (complexity={complexity})"
        elif complexity >= AIRouter.DEEP_THRESHOLD:
            min_tier = "local_deep"
            reason   = f"high complexity score {complexity}/10 → deep tier"
        elif task_role in ("code", "debug"):
            min_tier = "local_code"
            reason   = f"{task_role} task → code tier"
        elif task_role == "unreal":
            min_tier = "local_plan"
            reason   = "Unreal context → plan tier (not a deep trigger)"
        else:
            min_tier = "local_plan"
            reason   = f"{task_role} context → plan tier"

        # ---- If local_only, cap at local_deep ---------------------------
        if allow_local_only and min_tier == "active":
            min_tier = "local_deep"
            reason  += " [local-only mode: capped at local_deep]"

        tier, model = tiers.best_available(min_tier)

        # ---- Legacy callback support ------------------------------------
        if not model and get_model_for_role:
            model = get_model_for_role(session_role)
            tier  = "legacy_callback"

        return RouteDecision(
            task_role=task_role,
            session_role=session_role,
            model=model,
            tier=tier,
            reason=reason,
            complexity=complexity,
        )
