"""Shared desktop entitlement gating without starting application subsystems."""

from __future__ import annotations

from typing import Any


_ACTIVE_PROJECT = object()


def ensure_entitlement(
    service,
    *,
    project_root: str | None | object = _ACTIVE_PROJECT,
    commercial_use: bool | None = None,
    parent=None,
) -> tuple[bool, str, tuple[str, ...]]:
    """Validate or interactively acquire an entitlement for one project context."""
    if service.development_entitlement_bypass_allowed():
        return True, "Source-development entitlement bypass enabled.", ()

    evaluation_kwargs: dict[str, Any] = {}
    if project_root is not _ACTIVE_PROJECT:
        evaluation_kwargs["project_root"] = project_root
    if commercial_use is not None:
        evaluation_kwargs["commercial_use"] = bool(commercial_use)
    evaluation = service.evaluate_current_entitlement(**evaluation_kwargs)
    if evaluation.decision.allowed:
        service.record_license_acceptance(evaluation)
        service.authorize_host_bridges(evaluation)
        return True, evaluation.decision.reason, tuple(evaluation.decision.warnings)

    reason = evaluation.decision.reason or "A valid Tech Connector entitlement is required."
    from tech_connector.app.license_activation_dialog import ensure_license_activated

    activation_project = (
        str(service.settings.get("active_project") or "")
        if project_root is _ACTIVE_PROJECT
        else str(project_root or "")
    )
    try:
        activated = ensure_license_activated(
            service.licensing_activation_client(),
            reason,
            activation_project,
            parent,
        )
    except Exception as exc:
        return False, str(exc) or reason, ()
    if not activated:
        return False, reason, ()

    refreshed = service.evaluate_current_entitlement(**evaluation_kwargs)
    if not refreshed.decision.allowed:
        return (
            False,
            refreshed.decision.reason or "The activated entitlement does not authorize this use.",
            tuple(refreshed.decision.warnings),
        )
    service.record_license_acceptance(refreshed)
    service.authorize_host_bridges(refreshed)
    return True, refreshed.decision.reason, tuple(refreshed.decision.warnings)


def ensure_desktop_preflight(service, parent=None) -> tuple[bool, str, tuple[str, ...]]:
    """Require the local license notice and entitlement before constructing the UI."""
    from tech_connector.app.tos_dialog import ensure_tos_accepted

    if not ensure_tos_accepted(parent):
        return False, "The current Tech Connector license terms were not accepted.", ()
    return ensure_entitlement(service, parent=parent)
