"""Normalize user-facing code-agent modes into one execution contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


PROMPT_MODES = ("auto", "ask", "plan", "edit", "review")
PROMPT_SCOPES = ("auto", "selection", "file", "folder", "project", "dcc")
PROMPT_DEPTHS = ("fast", "balanced", "deep", "maximum")
PROMPT_PERMISSIONS = ("read_only", "preview", "apply_after_review", "automatic_safe")


@dataclass(frozen=True)
class CodePromptProfile:
    """Describe one visible code-agent request policy.

    :param mode: User-selected Ask, Plan, Edit, Review, or automatic mode.
    :param scope: User-selected context boundary.
    :param depth: Requested model quality/latency tier.
    :param permission: Maximum mutation authority for the request.
    """

    mode: str = "auto"
    scope: str = "auto"
    depth: str = "balanced"
    permission: str = "preview"

    def to_dict(self) -> dict[str, str]:
        """Return the serializable profile.

        :return: Profile fields as a dictionary.
        """

        return asdict(self)


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """Return a normalized allowed choice.

    :param value: Candidate setting value.
    :param allowed: Supported values.
    :param default: Value returned for an unsupported candidate.
    :return: Normalized choice.
    """

    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def normalize_code_prompt_profile(
    value: CodePromptProfile | dict[str, Any] | None = None,
    *,
    settings: dict[str, Any] | None = None,
) -> CodePromptProfile:
    """Build a safe profile from UI values or persisted settings.

    :param value: Optional explicit profile or profile mapping.
    :param settings: Optional application settings fallback.
    :return: Normalized code-prompt profile.
    """

    if isinstance(value, CodePromptProfile):
        source = value.to_dict()
    else:
        source = dict(value or {})
    persisted = dict(settings or {})
    mode = _choice(
        source.get("mode", persisted.get("code_prompt_mode")),
        PROMPT_MODES,
        "auto",
    )
    scope = _choice(
        source.get("scope", persisted.get("code_prompt_scope")),
        PROMPT_SCOPES,
        "auto",
    )
    depth = _choice(
        source.get("depth", persisted.get("code_prompt_depth")),
        PROMPT_DEPTHS,
        "balanced",
    )
    permission = _choice(
        source.get("permission", persisted.get("code_prompt_permission")),
        PROMPT_PERMISSIONS,
        "preview",
    )

    # Read-only product modes are authoritative even if an older saved setting
    # still contains a mutation-capable permission.
    if mode in {"ask", "plan", "review"}:
        permission = "read_only"
    return CodePromptProfile(mode, scope, depth, permission)


def openai_execution_options(profile: CodePromptProfile | dict[str, Any]) -> dict[str, Any]:
    """Map a visible depth preset onto current OpenAI Responses controls.

    :param profile: Normalized profile or compatible mapping.
    :return: Provider-neutral options consumed by the OpenAI adapter.
    """

    normalized = normalize_code_prompt_profile(profile)
    options_by_depth = {
        "fast": {
            "reasoning_effort": "low",
            "reasoning_context": "current_turn",
            "verbosity": "low",
        },
        "balanced": {
            "reasoning_effort": "medium",
            "reasoning_context": "all_turns",
            "verbosity": "medium",
        },
        "deep": {
            "reasoning_effort": "high",
            "reasoning_context": "all_turns",
            "verbosity": "medium",
        },
        "maximum": {
            "reasoning_effort": "max",
            "reasoning_context": "all_turns",
            "reasoning_mode": "pro",
            "verbosity": "high",
        },
    }
    return dict(options_by_depth[normalized.depth])


def preferred_openai_model(depth: str) -> str:
    """Return the GPT-5.6 family member for a workload depth.

    :param depth: Fast, balanced, deep, or maximum depth.
    :return: OpenAI model identifier.
    """

    normalized = _choice(depth, PROMPT_DEPTHS, "balanced")
    if normalized == "fast":
        return "gpt-5.6-luna"
    if normalized == "balanced":
        return "gpt-5.6-terra"
    return "gpt-5.6-sol"


def render_code_prompt_contract(profile: CodePromptProfile | dict[str, Any]) -> str:
    """Render one compact, non-repeating autonomy contract for a model.

    :param profile: Normalized profile or compatible mapping.
    :return: Compact prompt policy text.
    """

    normalized = normalize_code_prompt_profile(profile)
    authority = {
        "read_only": "Inspect and report only. Do not modify project or DCC state.",
        "preview": "Generate reviewable changes in a disposable preview. Do not write project files.",
        "apply_after_review": "Prepare reviewable changes and apply only after explicit user approval.",
        "automatic_safe": "Apply only reversible, in-scope local changes; stop before destructive or external actions.",
    }[normalized.permission]
    return (
        "CODE REQUEST CONTRACT\n"
        f"Mode: {normalized.mode}\n"
        f"Scope: {normalized.scope}\n"
        f"Depth: {normalized.depth}\n"
        f"Authority: {authority}\n"
        "Success: satisfy the requested outcome, cite concrete changed or inspected files, "
        "and report validation evidence and remaining blockers."
    )


def apply_code_prompt_profile_to_decision(
    decision: Any,
    profile: CodePromptProfile | dict[str, Any],
) -> Any:
    """Apply explicit UI intent after natural-language route inference.

    :param decision: Mutable prompt-route decision object.
    :param profile: Normalized profile or compatible mapping.
    :return: The same updated decision object.
    """

    normalized = normalize_code_prompt_profile(profile)
    if hasattr(decision, "user_prompt_preferences"):
        decision.user_prompt_preferences = normalized.to_dict()
    if normalized.mode == "auto":
        return decision

    if normalized.mode in {"ask", "plan", "review"}:
        inferred_mutation = (
            str(getattr(decision, "mutation_scope", "") or "") != "read_only"
            or bool(getattr(decision, "requires_execution", False))
            or bool(getattr(decision, "requires_generation", False))
        )
        decision.mutation_scope = "read_only"
        decision.requires_confirmation = False
        decision.can_execute_directly = False
        decision.requires_execution = False
        mutation_routes = {
            "target_discovery",
            "project_edit",
            "project_mutation",
            "code_generation",
            "dcc_execution",
            "dcc_execute",
            "dcc_prototype",
            "unreal_capability",
            "capability_acquisition",
            "action_graph",
            "pipeline_graph",
        }
        current_provider = str(getattr(decision, "provider", "") or "")
        current_route = str(getattr(decision, "route", "") or "")
        if (
            inferred_mutation
            or current_provider in mutation_routes
            or current_route in mutation_routes
            or normalized.scope in {"folder", "project"}
            and normalized.mode in {"plan", "review"}
        ):
            decision.route = "project_search"
            decision.provider = "project_search"
            decision.execution_route = "engine.project_search"
            decision.handler_id = "ProjectSearchHandler"
            decision.selected_route_reason = (
                f"The explicit {normalized.mode.title()} mode converted the inferred "
                "mutation route into read-only project inspection."
            )
        if normalized.mode == "plan":
            decision.requires_plan = True
            decision.goal_type = "plan"
        elif normalized.mode == "review":
            decision.goal_type = "review"
            decision.requires_validation = True
        else:
            decision.goal_type = decision.goal_type or "explain"
    elif normalized.mode == "edit":
        decision.requires_generation = True
        decision.requires_validation = True
        decision.mutation_scope = "project_code_mutation"
        decision.requires_confirmation = normalized.permission != "automatic_safe"
        if str(getattr(decision, "provider", "")) in {"project_search", "chat"}:
            decision.route = "target_discovery"
            decision.provider = "target_discovery"
            decision.execution_route = "engine.target_discovery"
            decision.handler_id = "TargetDiscoveryHandler"
            decision.selected_route_reason = (
                "The user explicitly selected Edit mode, so target discovery precedes generation."
            )

    if normalized.scope == "dcc":
        decision.required_context = list(
            dict.fromkeys([*list(decision.required_context or []), "dcc_connection"])
        )
    elif normalized.scope in {"selection", "file", "folder", "project"}:
        scope_context = {
            "selection": "editor_selection",
            "file": "active_file",
            "folder": "active_folder",
            "project": "project_index",
        }[normalized.scope]
        decision.required_context = list(
            dict.fromkeys([*list(decision.required_context or []), scope_context])
        )
    return decision
