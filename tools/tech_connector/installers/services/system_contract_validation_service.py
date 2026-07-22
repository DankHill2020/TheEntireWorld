from __future__ import annotations

"""Startup-safe compatibility checks for routes, handlers, and action types.

The default mode reports failures without preventing UI startup. Set
TEW_STRICT_STARTUP_CONTRACTS=1 to raise SystemContractError on failure.
"""

from dataclasses import asdict, dataclass, field
import os
from typing import Any


class SystemContractError(RuntimeError):
    pass


@dataclass
class SystemContractReport:
    ok: bool
    action_contract: dict[str, Any] = field(default_factory=dict)
    route_contract: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_system_contracts(*, strict: bool | None = None) -> SystemContractReport:
    errors: list[str] = []
    warnings: list[str] = []

    from services.action_execution_engine import default_action_handler_registry
    from services.action_graph_service import ACTION_TYPES
    from services.prompt_dispatch_service import default_route_handlers

    action_registry = default_action_handler_registry()
    action_contract = action_registry.contract_report()
    if not action_contract.get("ok"):
        missing = list(action_contract.get("missing_handlers") or [])
        errors.append("Planner action types without handlers: " + ", ".join(missing))

    registered_actions = {row["action_type"] for row in action_registry.ownership_map()}
    advertised_without_handlers = sorted(set(ACTION_TYPES) - registered_actions)
    # The graph schema intentionally advertises planning/preview-only actions.
    # Report these as warnings, while critical emitted actions remain errors.
    if advertised_without_handlers:
        warnings.append(
            "ActionGraph schema contains planning-only or unimplemented actions: "
            + ", ".join(advertised_without_handlers)
        )

    route_handlers = default_route_handlers()
    known_execution_routes = set(route_handlers)
    required_execution_routes = {
        "engine.project_health",
        "engine.project_search",
        "engine.connection_status",
        "engine.target_discovery",
        "engine.action_graph",
        "dcc.execution_pipeline",
        "dcc.prototype_pipeline",
        "unreal.capability_pipeline",
        "ui.github_import",
        "llm.chat",
    }
    missing_route_handlers = sorted(required_execution_routes - known_execution_routes)
    if missing_route_handlers:
        errors.append("Execution routes without dispatch handlers: " + ", ".join(missing_route_handlers))

    duplicate_handler_ids: list[str] = []
    seen_handler_ids: set[str] = set()
    for handler in route_handlers.values():
        handler_id = str(getattr(handler, "handler_id", "") or "")
        if handler_id in seen_handler_ids:
            duplicate_handler_ids.append(handler_id)
        seen_handler_ids.add(handler_id)
    if duplicate_handler_ids:
        errors.append("Duplicate route handler IDs: " + ", ".join(sorted(set(duplicate_handler_ids))))

    route_contract = {
        "known_execution_routes": sorted(known_execution_routes),
        "required_execution_routes": sorted(required_execution_routes),
        "missing_route_handlers": missing_route_handlers,
        "handler_ids": sorted(seen_handler_ids),
    }
    report = SystemContractReport(
        ok=not errors,
        action_contract=action_contract,
        route_contract=route_contract,
        errors=errors,
        warnings=warnings,
    )
    if strict is None:
        strict = os.getenv("TEW_STRICT_STARTUP_CONTRACTS", "").strip().lower() in {"1", "true", "yes", "on"}
    if strict and not report.ok:
        raise SystemContractError("; ".join(report.errors))
    return report


def render_system_contract_report(report: SystemContractReport | dict[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, SystemContractReport) else dict(report or {})
    lines = [f"System contracts: {'PASS' if data.get('ok') else 'FAIL'}"]
    action = data.get("action_contract") or {}
    lines.append(
        f"Actions: {len(action.get('registered_action_types') or [])} registered; "
        f"{len(action.get('missing_handlers') or [])} critical missing"
    )
    route = data.get("route_contract") or {}
    lines.append(
        f"Routes: {len(route.get('known_execution_routes') or [])} registered; "
        f"{len(route.get('missing_route_handlers') or [])} missing"
    )
    lines.extend(f"Error: {item}" for item in data.get("errors") or [])
    lines.extend(f"Warning: {item}" for item in data.get("warnings") or [])
    return "\n".join(lines)
