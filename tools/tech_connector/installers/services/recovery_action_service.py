"""Executable recovery actions for routed operations and clarification controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RecoveryActionResult:
    status: str
    action_id: str
    message: str
    resumes_operation: bool = False
    refresh_required: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def execute_recovery_option(option: dict[str, Any], context: dict[str, Any] | None = None) -> RecoveryActionResult:
    context = context or {}
    action_id = str(option.get("action_id") or option.get("action") or "").strip()
    window = context.get("window")
    if action_id in {"reconnect_unreal", "reconnect"}:
        return _execute_first_callable(
            action_id,
            window,
            [
                "refresh_unreal_connection",
                "start_unreal_daemon_on_startup",
                "install_unreal_bridge",
                "start_mcphost",
                "connect_current_host",
            ],
            success_message="Started a reconnect attempt.",
            refresh_required=True,
        )
    if action_id == "retry":
        return RecoveryActionResult("resume_requested", action_id, "Retry requested.", resumes_operation=True)
    if action_id == "refresh_choices":
        return RecoveryActionResult("refresh_requested", action_id, "Choice refresh requested.", refresh_required=True)
    if action_id in {"choose_host", "enter_manually", "clarify"}:
        return RecoveryActionResult("clarification_requested", action_id, "Additional input is required.", resumes_operation=True)
    if action_id in {"diagnose", "show_diagnostics"}:
        return RecoveryActionResult("diagnostic_requested", action_id, "Diagnostics requested.", diagnostics=dict(context.get("diagnostics") or {}))
    if action_id == "rebuild_index":
        return _execute_first_callable(
            action_id,
            window,
            ["quick_index_project", "update_project_index", "build_project_index"],
            success_message="Started a project index rebuild.",
            refresh_required=True,
        )
    return RecoveryActionResult("unsupported", action_id or "unknown", f"No recovery executor is registered for {action_id or 'unknown'}.")


def _execute_first_callable(
    action_id: str,
    target: Any,
    method_names: list[str],
    *,
    success_message: str,
    refresh_required: bool = False,
) -> RecoveryActionResult:
    if target is None:
        return RecoveryActionResult("unavailable", action_id, "No application context was available for this recovery action.")
    for name in method_names:
        fn = getattr(target, name, None)
        if not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:
            return RecoveryActionResult(
                "failed",
                action_id,
                f"Recovery action {name} failed: {exc}",
                refresh_required=refresh_required,
                diagnostics={"method": name, "error": str(exc)},
            )
        return RecoveryActionResult(
            "started",
            action_id,
            success_message,
            refresh_required=refresh_required,
            diagnostics={"method": name},
        )
    return RecoveryActionResult(
        "unavailable",
        action_id,
        "No compatible recovery method was available on the application window.",
        refresh_required=refresh_required,
        diagnostics={"methods_checked": method_names},
    )
