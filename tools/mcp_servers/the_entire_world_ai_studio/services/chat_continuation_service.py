"""Chat-facing continuation helpers for structured clarifications.

The UI owns presentation and event capture. This service keeps continuation
state, view models, common replacement detection, and staleness checks out of
Qt widgets so routing authority stays in services.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
import uuid
from typing import Any

from engine.request_context import RequestContext


@dataclass
class PendingChatContinuation:
    continuation_id: str
    pending_clarification: dict[str, Any]
    clarification: dict[str, Any] = field(default_factory=dict)
    route_decision: dict[str, Any] = field(default_factory=dict)
    dispatch_request: dict[str, Any] = field(default_factory=dict)
    ui_controls: list[dict[str, Any]] = field(default_factory=list)
    origin_message_id: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "awaiting_input"
    context_signature: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClarificationViewModel:
    continuation_id: str
    message: str
    controls: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "info"
    can_cancel: bool = True
    text_fallback: str = ""
    clarification_type: str = "slot"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_pending_continuation(result_metadata: dict[str, Any], context: RequestContext, *, message: str = "") -> PendingChatContinuation | None:
    pending = dict(result_metadata.get("pending_clarification") or {})
    if not pending:
        return None
    clarification = dict(result_metadata.get("clarification") or {})
    pending.setdefault("route_decision", result_metadata.get("route_decision") or clarification.get("route_decision") or {})
    pending.setdefault("execution_request", result_metadata.get("dcc_request") or clarification.get("execution_request") or {})
    return PendingChatContinuation(
        continuation_id=str(uuid.uuid4()),
        pending_clarification=pending,
        clarification=clarification,
        route_decision=dict(pending.get("route_decision") or {}),
        dispatch_request=dict(pending.get("execution_request") or {}),
        ui_controls=list(result_metadata.get("ui_controls") or clarification.get("ui_controls") or []),
        context_signature=context_signature(context),
    )


def continuation_view_model(continuation: PendingChatContinuation, *, message: str = "") -> ClarificationViewModel:
    clarification = continuation.clarification or {}
    controls = list(continuation.ui_controls or [])
    kind = str(clarification.get("kind") or continuation.pending_clarification.get("kind") or "slot")
    severity = "warning" if kind == "confirmation" else "info"
    return ClarificationViewModel(
        continuation_id=continuation.continuation_id,
        message=message,
        controls=controls,
        severity=severity,
        can_cancel=True,
        text_fallback=message,
        clarification_type=kind,
    )


def context_signature(context: RequestContext) -> dict[str, Any]:
    extras = context.extras or {}
    return {
        "project_roots": list(context.project_roots or []),
        "current_file_path": context.current_file_path or "",
        "index_state": context.index_state or "",
        "dcc_host": extras.get("dcc_host") or extras.get("active_dcc_host") or "",
        "selection_fingerprint": _fingerprint(extras.get("selected_objects") or extras.get("selected_actors") or []),
    }


def validate_continuation_context(continuation: PendingChatContinuation, context: RequestContext) -> dict[str, Any]:
    before = continuation.context_signature or {}
    now = context_signature(context)
    if not before:
        return {"status": "safe_to_continue", "reason": ""}
    if before.get("project_roots") != now.get("project_roots"):
        return {"status": "must_cancel_and_reroute", "reason": "The active project changed."}
    target_file = str((continuation.dispatch_request or {}).get("file") or "")
    if target_file and before.get("current_file_path") and before.get("current_file_path") != now.get("current_file_path"):
        return {"status": "requires_confirmation", "reason": "The active file changed since the clarification was generated."}
    if before.get("selection_fingerprint") and before.get("selection_fingerprint") != now.get("selection_fingerprint"):
        return {"status": "requires_refreshed_choices", "reason": "The active DCC selection changed."}
    return {"status": "safe_to_continue", "reason": ""}


def classify_continuation_reply(text: str) -> dict[str, Any]:
    lower = str(text or "").strip().lower()
    if lower in {"cancel", "stop", "never mind", "nevermind", "go back"}:
        return {"kind": "cancel"}
    if any(term in lower for term in ("explain instead", "open instead", "search instead", "don't run", "do not run")):
        return {"kind": "replace", "reason": "User requested a different intent."}
    if "preview" in lower and any(term in lower for term in ("only", "instead", "just preview", "show me", "first")):
        return {"kind": "modify", "operation_mode": "preview"}
    if any(term in lower for term in ("actually", "instead")) and len(lower.split()) > 3:
        return {"kind": "replace", "reason": "User appears to be replacing the pending request."}
    return {"kind": "answer"}


def apply_continuation_modifier(pending_state: dict[str, Any], modifier: dict[str, Any]) -> dict[str, Any]:
    updated = dict(pending_state or {})
    route_decision = dict(updated.get("route_decision") or {})
    execution_request = dict(updated.get("execution_request") or {})
    if modifier.get("operation_mode"):
        route_decision["operation_mode"] = modifier["operation_mode"]
        execution_request["operation_mode"] = modifier["operation_mode"]
    updated["route_decision"] = route_decision
    updated["execution_request"] = execution_request
    return updated


def _fingerprint(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "|".join(str(item) for item in value)
    return str(value)
