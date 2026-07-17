from __future__ import annotations

"""Canonical action vocabulary and planner/executor compatibility checks.

This module owns action-name compatibility only. It does not plan or execute work.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


CANONICAL_DCC_ACTION = "execute_dcc"

# Compatibility aliases are normalized at the ActionGraph boundary. Keep the
# Unreal capability action separate because it has a different payload contract.
ACTION_TYPE_ALIASES: dict[str, str] = {
    "run_dcc_operation": CANONICAL_DCC_ACTION,
    "dcc_execute": CANONICAL_DCC_ACTION,
    "execute_dcc_operation": CANONICAL_DCC_ACTION,
}

# Action types currently emitted by deterministic planners/providers in the
# request path covered by Version 1.0 Recovery. This set is deliberately narrow:
# it protects active contracts without claiming every advertised graph type has
# an executor yet.
CRITICAL_PLANNER_ACTION_TYPES: set[str] = {
    "query_dcc",
    "execute_dcc",
    "validate_dcc_call",
    "execute_dcc_capability",
    "execute_unreal_python",
    "resolve_dcc_capability",
    "generate_python",
    "search_project",
    "github_search",
    "github_ingest",
    "index_repository",
    "validate_graph",
    "validate_workflow",
}


def canonical_action_type(action_type: str) -> str:
    value = str(action_type or "").strip()
    return ACTION_TYPE_ALIASES.get(value, value)


@dataclass
class ActionContractReport:
    ok: bool
    emitted_action_types: list[str] = field(default_factory=list)
    registered_action_types: list[str] = field(default_factory=list)
    missing_handlers: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_planner_executor_contract(
    registered_action_types: Iterable[str],
    emitted_action_types: Iterable[str] | None = None,
) -> ActionContractReport:
    registered = {canonical_action_type(item) for item in registered_action_types if item}
    emitted = {
        canonical_action_type(item)
        for item in (emitted_action_types or CRITICAL_PLANNER_ACTION_TYPES)
        if item
    }
    missing = sorted(emitted - registered)
    return ActionContractReport(
        ok=not missing,
        emitted_action_types=sorted(emitted),
        registered_action_types=sorted(registered),
        missing_handlers=missing,
        aliases=dict(ACTION_TYPE_ALIASES),
        notes=[
            "execute_dcc is the canonical generic DCC ActionGraph operation.",
            "execute_dcc_capability remains a separate Unreal/capability-graph contract.",
        ],
    )
