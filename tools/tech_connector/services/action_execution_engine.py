"""Canonical ActionExecutionEngine for Tech Connector action graphs."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
import copy
import re
import traceback
import uuid
from typing import Any, Callable

from reasoning_runtime.action.action_contract_service import (
    canonical_action_type,
    validate_planner_executor_contract,
)
from reasoning_runtime.action.action_graph_service import (
    MUTABILITY_DCC,
    MUTABILITY_READ_ONLY,
    normalize_action,
    normalize_action_graph,
    validate_action_graph,
)
from tech_connector.models.constants import temp_output_path


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass
class ActionEvent:
    event_type: str
    execution_id: str
    plan_id: str
    action_id: str = ""
    action_type: str = ""
    status: str = ""
    summary: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CancellationToken:
    cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "Cancelled") -> None:
        self.cancelled = True
        self.reason = reason


@dataclass
class ExecutionContext:
    project_root: str = ""
    project_roots: list[str] = field(default_factory=list)
    active_file: str = ""
    current_dcc_host: str = ""
    app_service: Any = None
    window: Any = None
    workflow: Any = None
    services: dict[str, Any] = field(default_factory=dict)
    approved: bool = False
    dry_run: bool = False
    policy: dict[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    event_sink: Callable[[ActionEvent], None] | None = None

    def roots(self) -> list[str]:
        roots = list(self.project_roots or [])
        if not roots and self.app_service is not None and hasattr(self.app_service, "all_roots"):
            try:
                roots = list(self.app_service.all_roots())
            except Exception:
                roots = []
        if self.project_root and self.project_root not in roots:
            roots.insert(0, self.project_root)
        return roots

    def service(self, name: str, default: Any = None) -> Any:
        return self.services.get(name, default)


@dataclass
class ActionHandler:
    action_type: str
    owning_service: str
    mutability: str = MUTABILITY_READ_ONLY
    approval_policy: str = "auto"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    validate_fn: Callable[[dict[str, Any], ExecutionContext], dict[str, Any]] | None = None
    execute_fn: Callable[[dict[str, Any], ExecutionContext], dict[str, Any]] | None = None
    repair_fn: Callable[[dict[str, Any], SupervisedActionResult, ExecutionContext], dict[str, Any] | None] | None = None
    compensate_fn: Callable[[dict[str, Any], ExecutionContext], dict[str, Any]] | None = None

    def validate(self, action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if self.validate_fn:
            return self.validate_fn(action, context)
        return {"valid": True, "errors": [], "warnings": []}

    def execute(self, action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if not self.execute_fn:
            return {"ok": False, "error": "Handler has no execution function."}
        return self.execute_fn(action, context)

    def repair(self, action: dict[str, Any], result: SupervisedActionResult, context: ExecutionContext) -> dict[str, Any] | None:
        if self.repair_fn:
            return self.repair_fn(action, result, context)
        repair_service = context.service("execution_repair")
        if repair_service and hasattr(repair_service, "repair_action"):
            return repair_service.repair_action(action, result.to_dict(), context)
        return _default_repair_action(action, result, context)


class ActionHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, handler: ActionHandler) -> None:
        if handler.action_type in self._handlers:
            raise ValueError(f"Duplicate action handler registered: {handler.action_type}")
        self._handlers[handler.action_type] = handler

    def get(self, action_type: str) -> ActionHandler | None:
        return self._handlers.get(canonical_action_type(action_type))

    def require(self, action_type: str) -> ActionHandler:
        handler = self.get(action_type)
        if not handler:
            raise KeyError(f"Unsupported action type: {action_type}")
        return handler

    def ownership_map(self) -> list[dict[str, Any]]:
        rows = []
        for action_type in sorted(self._handlers):
            handler = self._handlers[action_type]
            rows.append(
                {
                    "action_type": action_type,
                    "owning_service": handler.owning_service,
                    "mutability": handler.mutability,
                    "approval_policy": handler.approval_policy,
                    "input_schema": handler.input_schema,
                    "output_schema": handler.output_schema,
                    "implemented": True,
                }
            )
        return rows

    def contract_report(self) -> dict[str, Any]:
        return validate_planner_executor_contract(self._handlers.keys()).to_dict()


def _result_path_state(value: Any, path: str) -> tuple[bool, Any]:
    """Resolve a result path while preserving missing-versus-falsey state.

    :param value: Root result value.
    :param path: Dot-separated dictionary keys and list indexes.
    :return: Presence flag and resolved value.
    """

    current = value
    if not path:
        return True, current
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _result_path(value: Any, path: str) -> Any:
    """Resolve a result path and return None when it is missing.

    :param value: Root result value.
    :param path: Dot-separated dictionary keys and list indexes.
    :return: Resolved value or None.
    """

    found, current = _result_path_state(value, path)
    return current if found else None


def resolve_output_references(value: Any, results: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if "from_action" in value and "result_path" in value:
            source = results.get(str(value.get("from_action"))) or {}
            result = source.get("result", source)
            return _result_path(result, str(value.get("result_path") or ""))
        return {key: resolve_output_references(item, results) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_output_references(item, results) for item in value]
    return value


FAILURE_EXECUTION = "execution_failure"
FAILURE_VALIDATION = "validation_failure"
FAILURE_OUTCOME = "outcome_failure"
FAILURE_ENVIRONMENT = "environment_failure"
FAILURE_DEPENDENCY = "dependency_failure"
FAILURE_PERMISSION = "permission_failure"
FAILURE_CONFIRMATION = "user_confirmation_required"
FAILURE_NON_RETRYABLE = "non_retryable_failure"

ACTION_STATUS_PENDING = "pending"
ACTION_STATUS_EXECUTING = "executing"
ACTION_STATUS_OBSERVING = "observing"
ACTION_STATUS_DIAGNOSING = "diagnosing"
ACTION_STATUS_REPAIRING = "repairing"
ACTION_STATUS_RETRYING = "retrying"
ACTION_STATUS_VALIDATING = "validating"
ACTION_STATUS_SUCCEEDED = "succeeded"
ACTION_STATUS_BLOCKED = "blocked"
ACTION_STATUS_FAILED = "failed"
ACTION_STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
ACTION_STATUS_ROLLED_BACK = "rolled_back"


@dataclass
class SupervisedActionResult:
    action_id: str
    action_type: str
    tool: str = ""
    success: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    warnings: list[str] = field(default_factory=list)
    exception_type: str = ""
    exception_message: str = ""
    traceback: str = ""
    changed_files: list[str] = field(default_factory=list)
    changed_assets: list[str] = field(default_factory=list)
    changed_nodes: list[str] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    expected_outcomes: list[Any] = field(default_factory=list)
    observed_outcomes: list[Any] = field(default_factory=list)
    retryable: bool = False
    failure_category: str = ""
    retry_count: int = 0
    repair_attempt_count: int = 0
    model_tier: str = ""
    model_attempt_count: int = 0
    escalation_history: list[dict[str, Any]] = field(default_factory=list)
    repair_plan: dict[str, Any] = field(default_factory=dict)
    rollback_information: dict[str, Any] = field(default_factory=dict)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    unresolved_blocker: str = ""
    execution_status: str = ACTION_STATUS_PENDING
    diagnosis: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = bool(self.success)
        data["status"] = self.execution_status
        if self.unresolved_blocker:
            data["error"] = self.unresolved_blocker
        elif self.exception_message:
            data["error"] = self.exception_message
        return data


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text_from(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _truthy_result(value: Any) -> bool:
    if isinstance(value, dict):
        if "ok" in value:
            return bool(value.get("ok"))
        if "valid" in value:
            return bool(value.get("valid"))
        if "passed" in value:
            return bool(value.get("passed"))
    return bool(value)


def _infer_action_success(raw: dict[str, Any]) -> bool:
    """Infer execution success when a handler omits the canonical ok flag.

    :param raw: Raw handler result.
    :return: True only when no explicit failure evidence is present.
    """

    if "ok" in raw:
        return bool(raw.get("ok"))
    if "success" in raw:
        return bool(raw.get("success"))
    status = str(raw.get("status") or "").strip().casefold()
    if status in {
        "blocked",
        "cancelled",
        "error",
        "failed",
        "failure",
        "partial_failure",
        "rejected",
        "timed_out",
        "timeout",
    }:
        return False
    exit_code = raw.get("exit_code")
    if exit_code is not None:
        try:
            if int(exit_code) != 0:
                return False
        except (TypeError, ValueError):
            return False
    if any(
        raw.get(key) not in (None, "", [], {})
        for key in (
            "error",
            "errors",
            "exception",
            "exception_message",
            "exception_type",
            "traceback",
        )
    ):
        return False
    return True


def _contains_failure_text(text: str) -> bool:
    return bool(re.search(r"\b(error|exception|traceback|failed|failure|permission denied|not found|missing|invalid)\b", text or "", re.IGNORECASE))


def _collect_error_text(value: Any, *, depth: int = 0) -> str:
    if depth > 5 or value is None:
        return ""
    if isinstance(value, str):
        return value if _contains_failure_text(value) else ""
    if isinstance(value, dict):
        parts: list[str] = []
        for key in (
            "stderr",
            "error",
            "errors",
            "traceback",
            "raw_result",
            "raw",
            "output",
            "result",
            "data",
            "python_runner",
            "python_stderr",
        ):
            if key in value:
                text = _collect_error_text(value.get(key), depth=depth + 1)
                if text:
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(value, (list, tuple)):
        return "\n".join(text for item in value if (text := _collect_error_text(item, depth=depth + 1)))
    return ""


def _host_from_action(action: dict[str, Any]) -> str:
    args = action.get("args") or action.get("input") or {}
    value = str(args.get("host") or args.get("execution_environment") or action.get("execution_environment") or "").lower()
    if value:
        return value
    action_type = str(action.get("type") or action.get("action_type") or "").lower()
    if "unreal" in action_type:
        return "unreal"
    if "maya" in action_type:
        return "maya"
    return ""


def _default_repair_plan(action: dict[str, Any], result: SupervisedActionResult, context: ExecutionContext) -> dict[str, Any]:
    text = " ".join(
        [
            result.stderr,
            result.exception_type,
            result.exception_message,
            result.traceback,
            result.diagnosis,
            result.unresolved_blocker,
        ]
    ).lower()
    host = _host_from_action(action) or str(result.tool or "").lower()
    action_type = str(action.get("type") or "")
    steps: list[str] = []
    can_auto_retry = False
    needs_model = False
    repair_kind = "inspect_failure_evidence"

    if result.failure_category == FAILURE_CONFIRMATION:
        repair_kind = "request_confirmation"
        steps = [
            "Preserve the current action and evidence.",
            "Ask the user to approve the specific destructive or mutating step.",
            "Retry only after confirmation with the same action id and validation criteria.",
        ]
    elif result.failure_category == FAILURE_PERMISSION:
        repair_kind = "resolve_permission_boundary"
        steps = [
            "Identify the exact denied file, host operation, credential scope, or protected resource.",
            "Preserve the failed action without widening permissions automatically.",
            "Request only the minimum required access or report the exact administrator/user action needed.",
            "Retry only after the permission boundary is explicitly resolved.",
        ]
    elif result.failure_category == FAILURE_NON_RETRYABLE:
        repair_kind = "report_non_retryable_gap"
        steps = [
            "Preserve the exact capability-gap or unsupported-operation evidence.",
            "Report the missing callable, slot, adapter, or contract without retrying the same action.",
            "Require a new grounded implementation or capability plan before execution resumes.",
        ]
    elif result.failure_category == FAILURE_ENVIRONMENT or "no " in text and "bridge" in text:
        repair_kind = "restore_host_connection"
        app = host.replace("_", " ").title() or "the target application"
        steps = [
            f"Confirm {app} is open and the Tech Connector bridge/plugin is running.",
            "Refresh bridge/session discovery and remove stale port files if the discovered port is closed.",
            "Retry the same operation only after a health/session query succeeds.",
        ]
    elif result.failure_category == FAILURE_DEPENDENCY or "modulenotfound" in text or "importerror" in text:
        repair_kind = "resolve_dependency_or_import"
        steps = [
            "Read the traceback and identify the missing module, package, or import path.",
            "Search the project for the intended existing module or symbol before proposing a new dependency.",
            "Patch the import/path or report the exact dependency install/setup blocker.",
            "Rerun compile/import validation before retrying the original action.",
        ]
        needs_model = True
    elif result.failure_category == FAILURE_OUTCOME:
        repair_kind = "repair_missing_outcome"
        steps = [
            "Compare each expected outcome against the observed state recorded in the result.",
            "Query the exact target state again using deterministic project or host APIs.",
            "Apply the smallest change that makes the missing outcome observable.",
            "Retry only the failed action and affected dependents, then rerun outcome validation.",
        ]
        needs_model = True
    elif "syntaxerror" in text or "indentationerror" in text:
        repair_kind = "repair_code_syntax"
        steps = [
            "Open the traceback file and line.",
            "Patch the smallest syntax/indentation issue without refactoring unrelated code.",
            "Run py_compile for the touched file.",
            "Retry the original action after compile passes.",
        ]
        can_auto_retry = action_type in {"execute_python", "apply_code_patch", "update_file", "create_file", "validate"}
    elif "nameerror" in text or "attributeerror" in text or "typeerror" in text:
        repair_kind = "repair_code_or_api_usage"
        steps = [
            "Inspect the traceback frame, callable signature, and nearby existing call sites.",
            "Resolve the correct symbol, attribute, argument name, or API variant from local source or host reflection.",
            "Patch only the failing call or generated snippet.",
            "Retry the action and run the declared validation/outcome checks.",
        ]
        needs_model = True
    elif "traceback" in text or result.failure_category == FAILURE_EXECUTION:
        repair_kind = "repair_host_or_code_exception"
        host_label = host.replace("_", " ").title()
        if host_label:
            steps.append(f"Inspect the {host_label} traceback and separate host-state errors from generated-code errors.")
        else:
            steps.append("Inspect the traceback and classify the failing frame.")
        steps.extend(
            [
                "Gather the missing context named by the error, such as selected nodes, asset names, duplicate short names, or API signatures.",
                "Apply the smallest grounded correction.",
                "Retry the same action once and rerun validation.",
            ]
        )
        needs_model = True
    elif result.failure_category == FAILURE_VALIDATION:
        repair_kind = "repair_validation_failure"
        steps = [
            "Read the failed validation check and its observed value.",
            "Inspect the changed artifact or host state that produced the failed check.",
            "Patch the smallest cause and rerun the validation command.",
        ]
        needs_model = True
    else:
        steps = [
            "Preserve the raw result and diagnostics.",
            "Gather more context from the target file, action arguments, and host/application state.",
            "Choose a targeted repair before retrying.",
        ]
        needs_model = True

    if host in {"maya", "blender", "houdini", "motionbuilder", "substance_painter", "unity", "photoshop"}:
        steps.append("For host actions, verify the result through a follow-up state query rather than trusting command execution.")
    if host == "maya":
        steps.append("For Maya, inspect Script Editor stderr/traceback and query exact node, attribute, connection, parenting, or selection state.")
    if host == "unreal":
        steps.append("For Unreal, inspect python_runner/compile/log errors and rescan exact graph, asset, variable, node, pin, or saved state.")

    return {
        "kind": repair_kind,
        "failure_category": result.failure_category,
        "can_auto_retry": bool(can_auto_retry and result.retryable),
        "requires_model_escalation": bool(needs_model),
        "model_tier": result.model_tier,
        "steps": steps,
        "evidence": {
            "stderr": result.stderr[:2000],
            "exception": result.exception_message,
            "failed_validations": [
                item for item in result.validation_results
                if not bool(item.get("passed", item.get("ok", item.get("valid", True))))
            ],
        },
    }


def _default_repair_action(action: dict[str, Any], result: SupervisedActionResult, context: ExecutionContext) -> dict[str, Any] | None:
    plan = _default_repair_plan(action, result, context)
    return {
        "ok": False,
        "summary": "A repair plan was produced, but automatic retry is not safe until a grounded patch or host-state repair is available.",
        "repair_plan": plan,
    }


class ActionExecutionEngine:
    def __init__(self, registry: ActionHandlerRegistry | None = None):
        self.registry = registry or default_action_handler_registry()
        self._executions: dict[str, dict[str, Any]] = {}

    def _emit(self, context: ExecutionContext, event: ActionEvent) -> None:
        record = self._executions.setdefault(event.execution_id, {"events": []})
        record.setdefault("events", []).append(event.to_dict())
        if context.event_sink:
            context.event_sink(event)

    def validate_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        graph = normalize_action_graph(plan)
        validation = validate_action_graph(graph)
        registered_types = {str(action.get("type") or "") for action in graph.get("actions") or [] if self.registry.get(str(action.get("type") or ""))}
        errors = [
            error
            for error in list(validation.get("errors") or [])
            if not any(error.endswith(f"unknown action type {action_type!r}") for action_type in registered_types)
        ]
        warnings = list(validation.get("warnings") or [])
        for action in graph.get("actions") or []:
            if not self.registry.get(action["type"]):
                errors.append(f"{action['id']}: unsupported action type {action['type']!r}")
        order = self._dependency_order(graph)
        if not order["valid"]:
            errors.extend(order["errors"])
        return {
            **validation,
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "order": order.get("order", []),
            "graph": graph,
        }

    def analyze_approval_requirements(self, plan: dict[str, Any]) -> dict[str, Any]:
        graph = normalize_action_graph(plan)
        actions = graph.get("actions") or []
        mutating = [a for a in actions if a.get("requires_approval")]
        return {
            "approval_required": bool(mutating),
            "read_only_actions": [a["id"] for a in actions if not a.get("requires_approval")],
            "mutating_actions": [
                {
                    "action_id": a["id"],
                    "action_type": a["type"],
                    "title": a.get("title"),
                    "mutability": a.get("mutability"),
                    "targets": a.get("target_refs") or [],
                    "warnings": a.get("warnings") or [],
                }
                for a in mutating
            ],
        }

    def preflight_plan(self, plan: dict[str, Any], context: ExecutionContext | None = None) -> dict[str, Any]:
        context = context or ExecutionContext(dry_run=True)
        context.dry_run = True
        validation = self.validate_plan(plan)
        approval = self.analyze_approval_requirements(validation["graph"])
        action_validations = []
        for action in validation["graph"].get("actions") or []:
            handler = self.registry.get(action["type"])
            if not handler:
                action_validations.append({"action_id": action["id"], "valid": False, "errors": ["unsupported action"]})
                continue
            action_validations.append({"action_id": action["id"], **handler.validate(action, context)})
        return {
            "valid": validation["valid"] and all(item.get("valid", True) for item in action_validations),
            "validation": validation,
            "approval": approval,
            "action_validations": action_validations,
            "dry_run": True,
        }

    def execute_plan(self, plan: dict[str, Any], execution_context: ExecutionContext | None = None) -> dict[str, Any]:
        context = execution_context or ExecutionContext()
        graph = normalize_action_graph(plan)
        execution_id = f"exec_{uuid.uuid4().hex[:10]}"
        plan_id = graph.get("plan_id") or f"plan_{uuid.uuid4().hex[:10]}"
        self._executions[execution_id] = {"execution_id": execution_id, "plan_id": plan_id, "events": []}
        self._emit(context, ActionEvent("plan_validating", execution_id, plan_id, summary="Validating action plan"))
        validation = self.validate_plan(graph)
        if not validation["valid"]:
            report = self._final_report(execution_id, plan_id, graph, "rejected", validation, {}, {})
            self._executions[execution_id]["report"] = report
            self._emit(context, ActionEvent("execution_completed", execution_id, plan_id, status="rejected", summary="Action plan rejected during validation", diagnostics=validation))
            return report

        self._emit(context, ActionEvent("plan_validated", execution_id, plan_id, status="ok", summary="Action plan validated"))
        approval = self.analyze_approval_requirements(graph)
        if approval["approval_required"] and not context.approved and not context.dry_run:
            self._emit(context, ActionEvent("approval_required", execution_id, plan_id, status="blocked", summary="Approval required before executing mutating actions", diagnostics=approval))
            report = self._final_report(execution_id, plan_id, graph, "approval_required", validation, approval, {})
            self._executions[execution_id]["report"] = report
            return report

        if context.dry_run:
            preflight = self.preflight_plan(graph, context)
            report = self._final_report(execution_id, plan_id, graph, "dry_run", validation, approval, {}, preflight=preflight)
            self._executions[execution_id]["report"] = report
            return report

        self._emit(context, ActionEvent("execution_started", execution_id, plan_id, status="running", summary="Executing action plan"))
        results: dict[str, Any] = {}
        statuses: dict[str, dict[str, Any]] = {}
        order = validation["order"]
        for action_id in order:
            action = next(a for a in graph["actions"] if a["id"] == action_id)
            failed_deps = [dep for dep in action.get("depends_on") or [] if statuses.get(dep, {}).get("status") not in {"completed", ACTION_STATUS_SUCCEEDED}]
            if failed_deps:
                statuses[action_id] = {"status": "skipped", "reason": "failed dependency", "failed_dependencies": failed_deps}
                self._emit(context, ActionEvent("action_skipped", execution_id, plan_id, action_id, action["type"], "skipped", "Skipped due to failed dependency", {"failed_dependencies": failed_deps}))
                continue
            if context.cancellation_token.cancelled:
                statuses[action_id] = {"status": "cancelled", "reason": context.cancellation_token.reason}
                self._emit(context, ActionEvent("execution_cancelled", execution_id, plan_id, action_id, action["type"], "cancelled", context.cancellation_token.reason))
                break
            result = self.execute_action(action, context, execution_id=execution_id, plan_id=plan_id, previous_results=results)
            results[action_id] = result
            status = "completed" if result.get("ok") else result.get("status") or "failed"
            statuses[action_id] = {"status": status, "execution_status": result.get("status"), "result": result}
        final_status = self._overall_status(statuses, graph["actions"], context)
        report = self._final_report(execution_id, plan_id, graph, final_status, validation, approval, results, statuses=statuses)
        self._executions[execution_id]["report"] = report
        self._emit(context, ActionEvent("execution_completed", execution_id, plan_id, status=final_status, summary=f"Execution {final_status}", diagnostics={"status_counts": report["status_counts"]}))
        return report

    def execute_action(
        self,
        action: dict[str, Any],
        execution_context: ExecutionContext,
        *,
        execution_id: str = "",
        plan_id: str = "",
        previous_results: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = normalize_action(action)
        previous_results = previous_results or {}
        handler = self.registry.require(action["type"])
        action = copy.deepcopy(action)
        action["args"] = resolve_output_references(action.get("args") or {}, previous_results)
        action["input"] = action["args"]
        if execution_id and plan_id:
            self._emit(execution_context, ActionEvent("action_started", execution_id, plan_id, action["id"], action["type"], "running", f"Running {action['type']}"))
        max_retries = self._max_retries(action, handler, execution_context)
        model_tiers = self._model_tiers(action, execution_context)
        repairs_per_tier = self._repairs_per_model_tier(action, execution_context)
        attempt = 0
        tier_index = 0
        tier_repair_attempts = 0
        escalation_history: list[dict[str, Any]] = []
        last_supervised: SupervisedActionResult | None = None
        while True:
            action.setdefault("execution_model_tier", model_tiers[min(tier_index, len(model_tiers) - 1)])
            if attempt and execution_id and plan_id:
                self._emit(
                    execution_context,
                    ActionEvent(
                        "action_retrying",
                        execution_id,
                        plan_id,
                        action["id"],
                        action["type"],
                        ACTION_STATUS_RETRYING,
                        f"Retrying {action['type']} after repair",
                        {"attempt": attempt + 1, "previous": last_supervised.to_dict() if last_supervised else {}},
                    ),
                )
            supervised = self._run_supervised_attempt(action, handler, execution_context, retry_count=attempt)
            supervised.model_tier = str(action.get("execution_model_tier") or "")
            supervised.model_attempt_count = tier_repair_attempts + 1
            supervised.repair_attempt_count = attempt
            supervised.escalation_history = list(escalation_history)
            last_supervised = supervised
            if supervised.success:
                result = supervised.to_dict()
                break
            if attempt >= max_retries or not supervised.retryable:
                if not supervised.success:
                    supervised.retryable = False
                    if supervised.execution_status not in {ACTION_STATUS_AWAITING_CONFIRMATION, ACTION_STATUS_ROLLED_BACK}:
                        supervised.execution_status = ACTION_STATUS_BLOCKED
                    if not supervised.unresolved_blocker:
                        supervised.unresolved_blocker = supervised.diagnosis or supervised.stderr or supervised.exception_message or "Retry limit exhausted."
                result = supervised.to_dict()
                break
            if (
                self._should_escalate_model_tier(supervised, tier_repair_attempts, repairs_per_tier)
                and tier_index < len(model_tiers) - 1
            ):
                tier_index += 1
                tier_repair_attempts = 0
                escalation = self._escalate_model_tier(action, supervised, model_tiers[tier_index], execution_context)
                escalation_history.append(escalation)
                action = self._apply_repair(action, escalation)
                if execution_id and plan_id:
                    self._emit(
                        execution_context,
                        ActionEvent(
                            "action_escalating_model",
                            execution_id,
                            plan_id,
                            action["id"],
                            action["type"],
                            ACTION_STATUS_DIAGNOSING,
                            str(escalation.get("summary") or f"Escalating repair reasoning to {model_tiers[tier_index]}"),
                            escalation,
                        ),
                    )
                attempt += 1
                continue
            if execution_id and plan_id:
                self._emit(
                    execution_context,
                    ActionEvent(
                        "action_diagnosing",
                        execution_id,
                        plan_id,
                        action["id"],
                        action["type"],
                        ACTION_STATUS_DIAGNOSING,
                        supervised.diagnosis or "Diagnosing action failure",
                        supervised.to_dict(),
                    ),
                )
            repair = handler.repair(action, supervised, execution_context)
            if not repair or repair.get("ok") is False:
                supervised.retryable = False
                supervised.execution_status = ACTION_STATUS_BLOCKED
                supervised.unresolved_blocker = str((repair or {}).get("error") or supervised.unresolved_blocker or "No grounded repair was available.")
                if isinstance((repair or {}).get("repair_plan"), dict):
                    supervised.repair_plan = dict(repair["repair_plan"])
                supervised.supporting_evidence.append({"kind": "repair", "summary": supervised.unresolved_blocker, "data": repair or {}})
                result = supervised.to_dict()
                break
            action = self._apply_repair(action, repair)
            supervised.supporting_evidence.append({"kind": "repair", "summary": str(repair.get("summary") or "Applied targeted repair."), "data": repair})
            if execution_id and plan_id:
                self._emit(
                    execution_context,
                    ActionEvent(
                        "action_repairing",
                        execution_id,
                        plan_id,
                        action["id"],
                        action["type"],
                        ACTION_STATUS_REPAIRING,
                        str(repair.get("summary") or "Applied targeted repair."),
                        repair,
                    ),
                )
            attempt += 1
            tier_repair_attempts += 1
        if execution_id and plan_id:
            event_type = "action_completed" if result.get("ok") else "action_failed"
            status = "completed" if result.get("ok") else "failed"
            self._emit(execution_context, ActionEvent(event_type, execution_id, plan_id, action["id"], action["type"], status, f"{action['type']} {status}", result))
        return result

    def _run_supervised_attempt(
        self,
        action: dict[str, Any],
        handler: ActionHandler,
        context: ExecutionContext,
        *,
        retry_count: int,
    ) -> SupervisedActionResult:
        try:
            preflight = handler.validate(action, context)
        except Exception as exc:
            raw = {
                "ok": False,
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
                "validation": {"valid": False, "errors": [str(exc)]},
            }
            return self._normalize_action_result(action, handler, raw, context=context, retry_count=retry_count)
        if not preflight.get("valid", True):
            raw = {"ok": False, "error": "action validation failed", "validation": preflight}
            return self._normalize_action_result(action, handler, raw, context=context, retry_count=retry_count)
        try:
            raw_result = handler.execute(action, context)
            if raw_result is None:
                raw_result = {"ok": True}
            elif not isinstance(raw_result, dict):
                raw_result = {"ok": True, "output": raw_result}
            else:
                raw_result = dict(raw_result)
                raw_result["ok"] = _infer_action_success(raw_result)
        except Exception as exc:
            raw_result = {
                "ok": False,
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
            }
        return self._normalize_action_result(action, handler, raw_result, context=context, retry_count=retry_count)

    def _normalize_action_result(
        self,
        action: dict[str, Any],
        handler: ActionHandler,
        raw: dict[str, Any],
        *,
        context: ExecutionContext,
        retry_count: int,
    ) -> SupervisedActionResult:
        nested_error_text = _collect_error_text(raw)
        result = SupervisedActionResult(
            action_id=str(action.get("id") or action.get("action_id") or ""),
            action_type=str(action.get("type") or action.get("action_type") or ""),
            tool=str(raw.get("tool") or raw.get("executor") or raw.get("execution_environment") or handler.owning_service),
            success=bool(raw.get("ok")),
            exit_code=raw.get("exit_code"),
            stdout=_text_from(raw.get("stdout") or raw.get("output") if raw.get("ok") else raw.get("stdout")),
            stderr=_text_from(raw.get("stderr") or (raw.get("output") if not raw.get("ok") else "") or nested_error_text),
            warnings=[str(item) for item in _as_list(raw.get("warnings")) if str(item)],
            exception_type=str(raw.get("exception_type") or ""),
            exception_message=str(raw.get("exception_message") or raw.get("error") or ""),
            traceback=str(raw.get("traceback") or ""),
            changed_files=[str(item) for item in _as_list(raw.get("changed_files")) if str(item)],
            changed_assets=[str(item) for item in _as_list(raw.get("changed_assets") or raw.get("affected_targets")) if str(item)],
            changed_nodes=[str(item) for item in _as_list(raw.get("changed_nodes")) if str(item)],
            expected_outcomes=_as_list(action.get("expected_outcomes") or (action.get("args") or {}).get("expected_outcomes") or raw.get("expected_outcomes")),
            observed_outcomes=_as_list(raw.get("observed_outcomes") or raw.get("observed_outcome") or raw.get("structured_data") or raw.get("result")),
            retry_count=retry_count,
            rollback_information=dict(raw.get("rollback_information") or raw.get("rollback") or action.get("compensation") or {}),
            supporting_evidence=[item for item in _as_list(raw.get("supporting_evidence") or raw.get("evidence")) if isinstance(item, dict)],
            raw_result=dict(raw),
        )
        result.validation_results = self._collect_validation_results(action, raw)
        if result.success:
            result.validation_results.extend(self._validate_expected_outcomes(action, raw, result))
        result.failure_category = self._classify_failure(raw, result)
        result.success = bool(result.success and not result.failure_category)
        result.retryable = self._is_retryable(action, raw, result)
        if result.success:
            result.execution_status = ACTION_STATUS_SUCCEEDED
        elif result.failure_category == FAILURE_CONFIRMATION:
            result.execution_status = ACTION_STATUS_AWAITING_CONFIRMATION
        elif result.failure_category in {FAILURE_VALIDATION, FAILURE_OUTCOME, FAILURE_EXECUTION} and result.retryable:
            result.execution_status = ACTION_STATUS_DIAGNOSING
        elif result.failure_category:
            result.execution_status = ACTION_STATUS_BLOCKED
        else:
            result.execution_status = ACTION_STATUS_FAILED
        result.diagnosis = self._diagnose_failure(raw, result)
        if not result.success and not result.unresolved_blocker:
            result.unresolved_blocker = result.diagnosis or result.exception_message or "Action did not satisfy its execution contract."
        if not result.success:
            result.repair_plan = _default_repair_plan(action, result, context=context)
        return result

    def _collect_validation_results(self, action: dict[str, Any], raw: dict[str, Any]) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for item in _as_list(raw.get("validation_results")):
            if isinstance(item, dict):
                collected.append(dict(item))
        validation = raw.get("validation")
        if isinstance(validation, dict):
            collected.append(
                {
                    "name": "technical_validation",
                    "passed": bool(validation.get("valid", validation.get("ok", True))),
                    "errors": list(validation.get("errors") or []),
                    "warnings": list(validation.get("warnings") or []),
                }
            )
        if action.get("validation"):
            collected.append(
                {
                    "name": "declared_action_validation",
                    "passed": _truthy_result(action.get("validation")),
                    "details": action.get("validation"),
                }
            )
        return collected

    def _validate_expected_outcomes(
        self,
        action: dict[str, Any],
        raw: dict[str, Any],
        supervised: SupervisedActionResult,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, expected in enumerate(supervised.expected_outcomes, start=1):
            name = f"expected_outcome_{index}"
            if isinstance(expected, dict):
                path = str(expected.get("path") or "")
                expected_value = expected.get("equals")
                contains = expected.get("contains")
                found, observed = _result_path_state(raw, path) if path else (True, raw)
                passed = True
                if "equals" in expected:
                    passed = found and observed == expected_value
                elif contains is not None:
                    passed = found and str(contains) in _text_from(observed)
                elif "exists" in expected:
                    passed = found is bool(expected.get("exists"))
                elif "truthy" in expected:
                    expected_truth = bool(expected.get("truthy"))
                    passed = found and bool(observed) is expected_truth
                else:
                    passed = _truthy_result(expected)
                results.append(
                    {
                        "name": str(expected.get("name") or name),
                        "type": "outcome",
                        "passed": bool(passed),
                        "expected": expected,
                        "observed": observed,
                    }
                )
            else:
                text = _text_from(expected)
                haystack = " ".join(_text_from(value) for value in [raw.get("stdout"), raw.get("output"), raw.get("result"), raw.get("structured_data")])
                results.append(
                    {
                        "name": name,
                        "type": "outcome",
                        "passed": text.casefold() in haystack.casefold() if text else True,
                        "expected": expected,
                        "observed": haystack,
                    }
                )
        return results

    def _classify_failure(self, raw: dict[str, Any], result: SupervisedActionResult) -> str:
        if raw.get("requires_confirmation") or raw.get("status") == "confirmation_required":
            return FAILURE_CONFIRMATION
        nested_error_text = _collect_error_text(raw)
        validation_failures = [item for item in result.validation_results if not bool(item.get("passed", item.get("ok", item.get("valid", True))))]
        if validation_failures:
            if any(item.get("type") == "outcome" for item in validation_failures):
                return FAILURE_OUTCOME
            return FAILURE_VALIDATION
        explicit_error = bool(
            result.exception_type
            or result.exception_message
            or result.traceback
            or raw.get("error")
            or raw.get("errors")
        )
        if (
            result.success
            and not explicit_error
            and not _contains_failure_text(result.stderr)
            and not nested_error_text
        ):
            return ""
        text = " ".join(
            [
                result.stderr,
                nested_error_text,
                result.exception_type,
                result.exception_message,
                result.traceback,
                _text_from(raw.get("error")),
                _text_from(raw.get("status")),
            ]
        ).lower()
        if any(term in text for term in ("no object matches name", "missing maya object", "missing maya object(s)", "object does not exist", "could not find object")):
            return FAILURE_EXECUTION
        if re.search(r"\b(permission(?:error)?|access denied|operation denied)\b", text):
            return FAILURE_PERMISSION
        if any(
            term in text
            for term in (
                "not connected",
                "connection refused",
                "connection reset",
                "bridge not",
                "bridge unavailable",
                "no dcc",
                "no unreal",
                "no maya",
                "no host session",
                "host unavailable",
                "host is unavailable",
                "execution environment unavailable",
                "environment is unavailable",
            )
        ):
            return FAILURE_ENVIRONMENT
        if any(
            term in text
            for term in (
                "dependency",
                "importerror",
                "modulenotfound",
                "module not found",
                "no module named",
                "package is not installed",
            )
        ):
            return FAILURE_DEPENDENCY
        if raw.get("retryable") is False or raw.get("status") in {"capability_gap", "missing_slots"}:
            return FAILURE_NON_RETRYABLE
        if not result.success or explicit_error:
            return FAILURE_EXECUTION
        if _contains_failure_text(result.stderr):
            return FAILURE_EXECUTION
        return ""

    def _is_retryable(self, action: dict[str, Any], raw: dict[str, Any], result: SupervisedActionResult) -> bool:
        if raw.get("retryable") is not None:
            return bool(raw.get("retryable"))
        if result.failure_category in {FAILURE_CONFIRMATION, FAILURE_PERMISSION, FAILURE_NON_RETRYABLE}:
            return False
        if bool(action.get("destructive") or action.get("requires_confirmation")) and result.retry_count > 0:
            return False
        return result.failure_category in {FAILURE_EXECUTION, FAILURE_VALIDATION, FAILURE_OUTCOME, FAILURE_ENVIRONMENT, FAILURE_DEPENDENCY}

    def _diagnose_failure(self, raw: dict[str, Any], result: SupervisedActionResult) -> str:
        detail = self._failure_detail(raw, result)
        if result.failure_category == FAILURE_CONFIRMATION:
            return "User confirmation is required before this action can continue."
        if result.failure_category == FAILURE_OUTCOME:
            failed = [
                item for item in result.validation_results
                if not bool(item.get("passed", True))
            ]
            names = ", ".join(
                str(item.get("name")) for item in failed if item.get("name")
            )
            observation = next(
                (
                    f" Expected {item.get('expected')!r}; observed {item.get('observed')!r}."
                    for item in failed
                    if item.get("type") == "outcome"
                ),
                "",
            )
            return (
                "The action ran, but the requested outcome was not observed"
                + (f": {names}." if names else ".")
                + observation
            )
        if result.failure_category == FAILURE_VALIDATION:
            failed = [
                item for item in result.validation_results
                if not bool(item.get("passed", item.get("ok", item.get("valid", True))))
            ]
            names = ", ".join(
                str(item.get("name") or "validation") for item in failed
            )
            errors = "; ".join(
                _text_from(error)
                for item in failed
                for error in _as_list(item.get("errors"))
                if _text_from(error)
            )
            suffix = f" Failed checks: {names}." if names else ""
            if errors:
                suffix += f" {errors[:500]}"
            return "The action executed but failed technical validation." + suffix
        if result.failure_category == FAILURE_ENVIRONMENT:
            return self._diagnosis_with_detail(
                "The target application or execution environment is unavailable or returned an environment error.",
                detail,
            )
        if result.failure_category == FAILURE_DEPENDENCY:
            return self._diagnosis_with_detail(
                "A required dependency or import appears to be missing.",
                detail,
            )
        if result.failure_category == FAILURE_PERMISSION:
            return self._diagnosis_with_detail(
                "The action was blocked by a permission or access error.",
                detail,
            )
        if result.exception_message:
            return result.exception_message
        if result.stderr:
            return result.stderr
        return str(raw.get("error") or raw.get("status") or "")

    @staticmethod
    def _failure_detail(raw: dict[str, Any], result: SupervisedActionResult) -> str:
        """Return concise concrete evidence for a failure diagnosis.

        :param raw: Raw action result.
        :param result: Supervised action result.
        :return: Bounded failure detail.
        """

        candidates = [
            result.exception_message,
            result.stderr,
            _collect_error_text(raw),
            _text_from(raw.get("error")),
        ]
        for candidate in candidates:
            lines = [line.strip() for line in str(candidate or "").splitlines() if line.strip()]
            if lines:
                return lines[-1][:500]
        return result.exception_type[:500]

    @staticmethod
    def _diagnosis_with_detail(summary: str, detail: str) -> str:
        """Append non-duplicate evidence to a diagnosis summary.

        :param summary: Human-readable category summary.
        :param detail: Concrete failure evidence.
        :return: Complete diagnosis.
        """

        clean = str(detail or "").strip()
        if not clean or clean.casefold() in summary.casefold():
            return summary
        return f"{summary} Detail: {clean}"

    def _max_retries(self, action: dict[str, Any], handler: ActionHandler, context: ExecutionContext) -> int:
        policy = dict(context.policy.get("retry_limits") or {})
        action_type = str(action.get("type") or "")
        if action.get("max_retries") is not None:
            return max(0, int(action.get("max_retries") or 0))
        if action_type in policy:
            return max(0, int(policy[action_type]))
        if handler.mutability == MUTABILITY_READ_ONLY:
            return int(policy.get("read_only", 1))
        if handler.mutability == MUTABILITY_DCC:
            return int(policy.get("dcc_mutation", 2))
        return int(policy.get("mutation", 1))

    def _model_tiers(self, action: dict[str, Any], context: ExecutionContext) -> list[str]:
        policy = dict(context.policy.get("model_escalation") or {})
        tiers = action.get("model_tiers") or policy.get("tiers") or ["deterministic", "standard", "strong"]
        values = [str(item) for item in _as_list(tiers) if str(item)]
        return values or ["deterministic"]

    def _repairs_per_model_tier(self, action: dict[str, Any], context: ExecutionContext) -> int:
        policy = dict(context.policy.get("model_escalation") or {})
        if action.get("repairs_per_model_tier") is not None:
            return max(0, int(action.get("repairs_per_model_tier") or 0))
        return max(0, int(policy.get("repairs_per_tier", 1)))

    def _should_escalate_model_tier(
        self,
        result: SupervisedActionResult,
        tier_repair_attempts: int,
        repairs_per_tier: int,
    ) -> bool:
        """Escalate immediately for broad/ambiguous failures, otherwise after minor repair budget."""
        major_categories = {FAILURE_OUTCOME, FAILURE_ENVIRONMENT, FAILURE_DEPENDENCY}
        if result.failure_category in major_categories:
            return True
        if result.failure_category in {FAILURE_EXECUTION, FAILURE_VALIDATION} and tier_repair_attempts <= 0:
            return False
        if result.traceback and result.retry_count > 0:
            return True
        failed_validations = [
            item for item in result.validation_results
            if not bool(item.get("passed", item.get("ok", item.get("valid", True))))
        ]
        if len(failed_validations) > 1:
            return True
        return tier_repair_attempts >= repairs_per_tier

    def _escalate_model_tier(
        self,
        action: dict[str, Any],
        result: SupervisedActionResult,
        next_tier: str,
        context: ExecutionContext,
    ) -> dict[str, Any]:
        escalation = {
            "ok": True,
            "summary": f"Escalated repair reasoning to {next_tier}.",
            "model_tier": next_tier,
            "args": {"execution_model_tier": next_tier},
            "failure_category": result.failure_category,
            "diagnosis": result.diagnosis,
        }
        model_escalation = context.service("model_escalation")
        if model_escalation and hasattr(model_escalation, "escalate_action"):
            custom = model_escalation.escalate_action(action, result.to_dict(), next_tier, context)
            if isinstance(custom, dict):
                escalation.update(custom)
        return escalation

    def _apply_repair(self, action: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
        patched = copy.deepcopy(action)
        if isinstance(repair.get("action"), dict):
            patched.update(repair["action"])
        if isinstance(repair.get("args"), dict):
            patched.setdefault("args", {})
            patched["args"].update(repair["args"])
            patched["input"] = patched["args"]
        if repair.get("model_tier"):
            patched["execution_model_tier"] = str(repair["model_tier"])
        return patched

    def cancel_execution(self, execution_id: str) -> bool:
        record = self._executions.get(execution_id)
        if not record:
            return False
        record["cancel_requested"] = True
        return True

    def get_execution_status(self, execution_id: str) -> dict[str, Any]:
        record = self._executions.get(execution_id) or {}
        report = record.get("report") or {}
        return {"execution_id": execution_id, "status": report.get("status", "unknown"), "events": record.get("events", [])}

    def get_execution_report(self, execution_id: str) -> dict[str, Any]:
        return (self._executions.get(execution_id) or {}).get("report") or {}

    def _dependency_order(self, graph: dict[str, Any]) -> dict[str, Any]:
        actions = graph.get("actions") or []
        ids = {a["id"] for a in actions}
        incoming = {a["id"]: set(a.get("depends_on") or []) for a in actions}
        outgoing = {a["id"]: [] for a in actions}
        errors = []
        for action_id, deps in incoming.items():
            for dep in list(deps):
                if dep not in ids:
                    errors.append(f"{action_id}: missing dependency {dep!r}")
                else:
                    outgoing[dep].append(action_id)
        if errors:
            return {"valid": False, "errors": errors, "order": []}
        queue = [a["id"] for a in actions if not incoming[a["id"]]]
        order = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for child in outgoing[current]:
                incoming[child].discard(current)
                if not incoming[child]:
                    queue.append(child)
        if len(order) != len(actions):
            return {"valid": False, "errors": ["Action dependency graph contains a cycle."], "order": order}
        return {"valid": True, "errors": [], "order": order}

    def _overall_status(self, statuses: dict[str, dict[str, Any]], actions: list[dict[str, Any]], context: ExecutionContext) -> str:
        if context.cancellation_token.cancelled:
            return "cancelled"
        if any(v.get("status") == "skipped" for v in statuses.values()):
            return "partial_failure"
        failed_statuses = {"failed", ACTION_STATUS_FAILED, ACTION_STATUS_BLOCKED, ACTION_STATUS_AWAITING_CONFIRMATION, ACTION_STATUS_ROLLED_BACK}
        if any(v.get("status") in failed_statuses for v in statuses.values()):
            return "partial_failure" if any(v.get("status") == "completed" for v in statuses.values()) else "failed"
        return "completed" if len(statuses) == len(actions) else "partial"

    def _final_report(
        self,
        execution_id: str,
        plan_id: str,
        graph: dict[str, Any],
        status: str,
        validation: dict[str, Any],
        approval: dict[str, Any],
        results: dict[str, Any],
        *,
        statuses: dict[str, Any] | None = None,
        preflight: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        statuses = statuses or {}
        counts: dict[str, int] = {}
        for item in statuses.values():
            key = item.get("status", "unknown")
            counts[key] = counts.get(key, 0) + 1
        return {
            "execution_id": execution_id,
            "plan_id": plan_id,
            "status": status,
            "validation": validation,
            "approval": approval,
            "results": results,
            "action_statuses": statuses,
            "status_counts": counts,
            "preflight": preflight,
            "events": self._executions.get(execution_id, {}).get("events", []),
        }


def _action_args(action: dict[str, Any]) -> dict[str, Any]:
    return action.get("args") or action.get("input") or {}


def _resolve_symbol(action: dict[str, Any], context: ExecutionContext, kind: str = "function") -> dict[str, Any]:
    from tech_connector.services.tool_discovery_service import list_internal_functions, list_ingested_tools
    from tech_connector.models.constants import TOOLS_ROOT

    args = _action_args(action)
    if isinstance(args.get("symbol"), dict):
        symbol = dict(args["symbol"])
        return {"ok": True, "symbol": symbol, "symbol_id": _symbol_id(symbol)}
    query = str(args.get("query") or args.get("name") or "").lower()
    file_hint = str(args.get("file_hint") or "").lower()
    roots = context.roots()
    symbols = list_internal_functions(roots)
    ext_tools = ""
    try:
        settings = getattr(context.app_service, "settings", {}) if context.app_service else {}
        ext_tools = settings.get("external_tools_dir", "") or str(TOOLS_ROOT / "external_tools")
    except Exception:
        ext_tools = ""
    if ext_tools and Path(ext_tools).exists():
        symbols.extend(list_ingested_tools(Path(ext_tools)))
    best = None
    best_score = -1
    for symbol in symbols:
        if kind == "function" and str(symbol.get("kind", "")).lower() != "function":
            continue
        if kind == "class" and str(symbol.get("kind", "")).lower() != "class":
            continue
        text = " ".join([str(symbol.get("name", "")), Path(symbol.get("file_path", "")).name, str(symbol.get("file_path", ""))]).lower()
        score = 0
        if query and query == str(symbol.get("name", "")).lower():
            score += 100
        if query and query in text:
            score += 25
        if file_hint and file_hint in text:
            score += 20
        if score > best_score:
            best_score = score
            best = symbol
    if not best or best_score <= 0:
        return {"ok": False, "error": f"No {kind} matched query {query!r}", "query": query}
    return {"ok": True, "symbol": best, "symbol_id": _symbol_id(best), "score": best_score}


def _symbol_id(symbol: dict[str, Any]) -> str:
    return f"{Path(symbol.get('file_path', '')).as_posix()}::{symbol.get('name')}:{symbol.get('lineno', 0)}"


class InMemoryWorkflowRuntime:
    """Small adapter used by tests and dry execution when no Qt node view exists."""

    def __init__(self, name: str = "action_graph_pipeline", goal: str = "") -> None:
        self.name = name
        self.goal = goal
        self.steps: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []

    def create_node(self, symbol: dict[str, Any], node_name: str = "") -> dict[str, Any]:
        node_id = f"node_{len(self.steps) + 1}"
        step = {
            "node_id": node_id,
            "graph_step_id": node_id,
            "symbol": symbol,
            "params": symbol.get("params") or [],
            "outputs": symbol.get("outputs") or [],
            "literal_values": {},
            "node_name": node_name or symbol.get("name") or node_id,
        }
        self.steps.append(step)
        return step

    def bind_literal(self, node: str, parameter: str, value: Any) -> dict[str, Any]:
        step = self.find_step(node)
        step.setdefault("literal_values", {})[parameter] = value
        return step

    def connect_data(self, source_node: str, source_port: str, target_node: str, target_port: str) -> dict[str, Any]:
        link = {"type": "data", "from": {"node": source_node, "port": source_port}, "to": {"node": target_node, "port": target_port}}
        self.links.append(link)
        return link

    def connect_flow(self, source_node: str, target_node: str) -> dict[str, Any]:
        link = {"type": "flow", "from": source_node, "to": target_node}
        self.links.append(link)
        return link

    def find_step(self, node: str) -> dict[str, Any]:
        for step in self.steps:
            if node in {step.get("node_id"), step.get("node_name"), (step.get("symbol") or {}).get("name")}:
                return step
        raise KeyError(f"Workflow node not found: {node}")

    def validate_graph(self) -> dict[str, Any]:
        node_names = {step.get("node_id") for step in self.steps} | {step.get("node_name") for step in self.steps} | {(step.get("symbol") or {}).get("name") for step in self.steps}
        errors = []
        for link in self.links:
            if link["type"] == "data":
                if link["from"]["node"] not in node_names or link["to"]["node"] not in node_names:
                    errors.append(f"Invalid data link: {link}")
            elif link["type"] == "flow":
                if link["from"] not in node_names or link["to"] not in node_names:
                    errors.append(f"Invalid flow link: {link}")
        return {"valid": not errors, "errors": errors, "node_count": len(self.steps), "link_count": len(self.links)}

    def manifest_data_links(self) -> list[dict[str, str]]:
        index = self._node_index()
        links = []
        for link in self.links:
            if link["type"] != "data":
                continue
            src = index.get(link["from"]["node"])
            dst = index.get(link["to"]["node"])
            if src and dst:
                links.append({"from": f"step{src}.{link['from']['port']}", "to": f"step{dst}.{link['to']['port']}", "type": "data"})
        return links

    def manifest_flow_links(self) -> list[dict[str, str]]:
        index = self._node_index()
        return [{"from": f"step{index[l['from']]}", "to": f"step{index[l['to']]}", "type": "flow"} for l in self.links if l["type"] == "flow" and l["from"] in index and l["to"] in index]

    def ordered_step_data(self) -> list[dict[str, Any]]:
        return self.steps

    def _node_index(self) -> dict[str, int]:
        out = {}
        for idx, step in enumerate(self.steps, 1):
            for key in (step.get("node_id"), step.get("node_name"), (step.get("symbol") or {}).get("name")):
                if key:
                    out[key] = idx
        return out


def _workflow(context: ExecutionContext) -> Any:
    if context.workflow is None:
        context.workflow = InMemoryWorkflowRuntime(goal=context.policy.get("goal", ""))
    return context.workflow


def default_action_handler_registry() -> ActionHandlerRegistry:
    registry = ActionHandlerRegistry()

    registry.register(ActionHandler("search_project", "tech_connector.services.project_search_service", execute_fn=lambda a, c: _handle_search_project(a, c)))
    registry.register(ActionHandler("resolve_symbol", "tech_connector.services.tool_discovery_service", execute_fn=lambda a, c: _resolve_symbol(a, c, "symbol")))
    registry.register(ActionHandler("resolve_function", "tech_connector.services.tool_discovery_service", execute_fn=lambda a, c: _resolve_symbol(a, c, "function")))
    registry.register(ActionHandler("resolve_class", "tech_connector.services.tool_discovery_service", execute_fn=lambda a, c: _resolve_symbol(a, c, "class")))
    registry.register(ActionHandler("open_file", "tech_connector.app.main_window_editor.open_code_file", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_open_file(a, c)))
    registry.register(ActionHandler("open_symbol", "tech_connector.app.main_window_editor.open_code_file", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_open_symbol(a, c)))
    registry.register(ActionHandler("create_node", "tech_connector.ui.pipeline_node_view.PipelineNodeView.add_pipeline_step", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_create_node(a, c)))
    registry.register(ActionHandler("create_pipeline_node", "tech_connector.ui.pipeline_node_view.PipelineNodeView.add_pipeline_step", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_create_node(a, c)))
    registry.register(ActionHandler("bind_literal", "tech_connector.ui.pipeline_node_view.PipelineNodeView.set_literal_value", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_bind_literal(a, c)))
    registry.register(ActionHandler("connect_data", "tech_connector.ui.pipeline_node_view.PipelineGraphLink", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_connect_data(a, c)))
    registry.register(ActionHandler("connect_flow", "tech_connector.ui.pipeline_node_view.PipelineGraphLink", mutability="local_reversible_mutation", execute_fn=lambda a, c: _handle_connect_flow(a, c)))
    registry.register(ActionHandler("validate_graph", "tech_connector.ui.pipeline_node_view manifest validation", execute_fn=lambda a, c: _workflow(c).validate_graph()))
    registry.register(ActionHandler("validate_workflow", "tech_connector.ui.pipeline_node_view manifest validation", execute_fn=lambda a, c: _workflow(c).validate_graph()))
    registry.register(ActionHandler("generate_python", "tech_connector.services.workflow_codegen_service.generate_pipeline_code_from_graph", execute_fn=lambda a, c: _handle_generate_python(a, c)))
    registry.register(ActionHandler("generate_workflow_code", "tech_connector.services.workflow_codegen_service.generate_pipeline_code_from_graph", execute_fn=lambda a, c: _handle_generate_python(a, c)))
    registry.register(ActionHandler("index_project", "tech_connector.services.application_service.ApplicationService.build_index", mutability="persistent_local_mutation", execute_fn=lambda a, c: _handle_index_project(a, c)))
    registry.register(ActionHandler("rebuild_index", "tech_connector.services.application_service.ApplicationService.build_index", mutability="persistent_local_mutation", execute_fn=lambda a, c: _handle_index_project(a, c)))
    registry.register(ActionHandler("rebuild_project_index", "tech_connector.services.application_service.ApplicationService.build_index", mutability="persistent_local_mutation", execute_fn=lambda a, c: _handle_index_project(a, c)))
    registry.register(ActionHandler("github_search", "tech_connector.ui.unreal_editor_dialogs.SearchWorker/GitHub API", execute_fn=lambda a, c: _handle_github_search(a, c)))
    registry.register(ActionHandler("github_ingest", "tech_connector.services.github_ingest_service.download_and_extract_repo", mutability="external_mutation", execute_fn=lambda a, c: _handle_github_ingest(a, c)))
    registry.register(ActionHandler("index_repository", "tech_connector.services.tool_discovery_service.list_ingested_tools", mutability="persistent_local_mutation", execute_fn=lambda a, c: _handle_index_repository(a, c)))
    registry.register(ActionHandler("index_ingested_repository", "tech_connector.services.tool_discovery_service.list_ingested_tools", mutability="persistent_local_mutation", execute_fn=lambda a, c: _handle_index_repository(a, c)))
    registry.register(ActionHandler("resolve_dcc_capability", "tech_connector.services.project_intelligence_service/unreal capability services", execute_fn=lambda a, c: _handle_resolve_dcc_capability(a, c)))
    registry.register(ActionHandler("validate_dcc_call", "tech_connector.services.project_intelligence_service/unreal capability services", execute_fn=lambda a, c: _handle_validate_dcc_call(a, c)))
    registry.register(ActionHandler("query_dcc", "tech_connector.game_engine.integration.dcc_execution_service", execute_fn=lambda a, c: _handle_execute_dcc(a, c, force_query=True)))
    registry.register(ActionHandler("execute_dcc", "tech_connector.game_engine.integration.dcc_execution_service", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_dcc(a, c)))
    registry.register(ActionHandler("execute_dcc_capability", "tech_connector.services.project_intelligence_service/unreal capability services", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_dcc_capability(a, c)))
    registry.register(ActionHandler("execute_unreal_python", "tech_connector.bridges.unreal.unreal_bridge.execute_python", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_unreal_python(a, c)))
    registry.register(ActionHandler("execute_workflow", "generated workflow callable", mutability="dcc_mutation", execute_fn=lambda a, c: {"ok": False, "error": "execute_workflow requires a registered workflow runner adapter"}))
    registry.register(ActionHandler("asset_source_search", "tech_connector.services.external_asset_acquisition_service", execute_fn=lambda a, c: _handle_asset_source_search(a, c)))
    registry.register(ActionHandler("download_or_ingest_asset", "tech_connector.services.external_asset_acquisition_service", mutability="external_mutation", execute_fn=lambda a, c: _handle_download_or_ingest_asset(a, c)))
    return registry


def _handle_search_project(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.project_search_service import gather_project_search_context, build_deterministic_project_search_answer
    args = _action_args(action)
    query = str(args.get("query") or "")
    evidence = gather_project_search_context(query, active_path=context.active_file, limit=int(args.get("limit") or 80))
    return {"ok": True, "query": query, "evidence": evidence, "answer": build_deterministic_project_search_answer(query, context.active_file, evidence)}


def _handle_open_file(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    path = args.get("path") or args.get("query")
    if context.dry_run:
        return {"ok": True, "dry_run": True, "path": path}
    if context.window and hasattr(context.window, "open_code_file"):
        context.window.open_code_file(str(path))
        return {"ok": True, "path": str(path)}
    return {"ok": False, "error": "No editor adapter/window is available to open files.", "path": path}


def _handle_open_symbol(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    symbol = args.get("symbol")
    if not symbol:
        resolved = _resolve_symbol(action, context, "symbol")
        if not resolved.get("ok"):
            return resolved
        symbol = resolved["symbol"]
    path = symbol.get("file_path")
    line = int(symbol.get("lineno") or symbol.get("start_line") or 1)
    if context.dry_run:
        return {"ok": True, "dry_run": True, "path": path, "line": line, "symbol": symbol}
    if context.window and hasattr(context.window, "_open_or_focus_file_at_line"):
        context.window._open_or_focus_file_at_line(path, line)
        return {"ok": True, "path": path, "line": line, "symbol": symbol}
    if context.window and hasattr(context.window, "open_code_file"):
        context.window.open_code_file(path)
        return {"ok": True, "path": path, "line": line, "symbol": symbol}
    return {"ok": False, "error": "No symbol navigation adapter/window is available.", "path": path, "line": line}


def _handle_create_node(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    symbol = args.get("symbol")
    if not symbol and args.get("symbol_id"):
        return {"ok": False, "error": "symbol_id lookup requires a symbol registry adapter"}
    if not symbol:
        resolved = _resolve_symbol({"args": {"query": args.get("node") or args.get("query")}}, context, "function")
        if not resolved.get("ok"):
            return resolved
        symbol = resolved["symbol"]
    step = _workflow(context).create_node(symbol, args.get("node") or symbol.get("name") or "")
    return {"ok": True, "node_id": step.get("node_id") or step.get("graph_step_id"), "node": step.get("node_name"), "step": step, "symbol": symbol}


def _handle_bind_literal(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    step = _workflow(context).bind_literal(args.get("node"), args.get("parameter"), args.get("value"))
    return {"ok": True, "node_id": step.get("node_id") or step.get("graph_step_id"), "parameter": args.get("parameter"), "value": args.get("value")}


def _handle_connect_data(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    src = args.get("from") or {}
    dst = args.get("to") or {}
    link = _workflow(context).connect_data(src.get("node"), src.get("port"), dst.get("node"), dst.get("port"))
    return {"ok": True, "link": link}


def _handle_connect_flow(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    link = _workflow(context).connect_flow(args.get("from"), args.get("to"))
    return {"ok": True, "link": link}


def _handle_generate_python(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph
    workflow = _workflow(context)
    args = _action_args(action)
    name = args.get("name") or getattr(workflow, "name", "action_graph_pipeline")
    goal = args.get("goal") or getattr(workflow, "goal", context.policy.get("goal", ""))
    code = generate_pipeline_code_from_graph(name, goal, workflow.steps, view=workflow)
    return {"ok": True, "code": code, "line_count": len(code.splitlines())}


def _handle_index_project(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    full = bool(args.get("full") or action.get("type") in {"rebuild_index", "rebuild_project_index"})
    if context.dry_run:
        return {"ok": True, "dry_run": True, "roots": context.roots(), "full": full}
    if context.app_service and hasattr(context.app_service, "build_index"):
        try:
            worker = context.app_service.build_index(full=full)
        except TypeError:
            worker = context.app_service.build_index()
        return {"ok": True, "worker": repr(worker), "roots": context.roots(), "full": full}
    return {"ok": False, "error": "No ApplicationService is available for project indexing."}


def _handle_github_search(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    query = args.get("query") or args.get("request") or ""
    review_limit = max(3, min(5, int(args.get("limit") or context.policy.get("github_review_limit") or 5)))
    automated = bool(args.get("auto_select") or context.policy.get("auto_select_github_candidate"))
    if args.get("fallback_only") and _internal_search_has_match(args.get("internal_search_result")):
        return {
            "ok": True,
            "status": "skipped_internal_match_found",
            "query": query,
            "requires_confirmation": False,
            "candidate_repos": [],
            "message": "Internal project search found candidate evidence, so GitHub review was not opened.",
        }
    if context.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "query": query,
            "requires_confirmation": not automated,
            "review_limit": review_limit,
        }
    if context.window is not None and hasattr(context.window, "trigger_web_import"):
        try:
            context.window.trigger_web_import(
                initial_query=str(query),
                workflow_goal=str(context.policy.get("original_prompt") or query),
                auto_search=True,
                auto_select_after_search=automated,
            )
            return {
                "ok": True,
                "status": "review_window_opened",
                "query": query,
                "requires_confirmation": not automated,
                "review_limit": review_limit,
                "ui": "WebImportDialog",
            }
        except Exception as exc:
            return {"ok": False, "error": f"Could not open GitHub review window: {exc}", "query": query}
    search_service = context.service("github_search")
    if search_service and hasattr(search_service, "search"):
        raw_results = list(search_service.search(query) or [])
        candidates = _github_review_candidates(raw_results, limit=review_limit)
        return {
            "ok": True,
            "query": query,
            "results": candidates,
            "candidate_repos": candidates,
            "requires_confirmation": not automated,
            "next_action": "open_github_candidate_review" if not automated else "auto_select_candidate_then_ingest",
            "selected_repo": candidates[0] if automated and candidates else None,
        }
    return {
        "ok": True,
        "query": query,
        "results": [],
        "candidate_repos": [],
        "requires_confirmation": True,
        "next_action": "open_web_github_import",
        "ui": "WebImportDialog",
        "message": "Open the Web / GitHub Import window to review the top 3-5 repository matches before ingestion.",
    }


def _internal_search_has_match(result: Any) -> bool:
    if not isinstance(result, dict) or not result.get("ok", True):
        return False
    evidence = result.get("evidence")
    if isinstance(evidence, dict):
        for value in evidence.values():
            if isinstance(value, (list, tuple, set)) and value:
                return True
            if isinstance(value, dict) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
        return False
    if isinstance(evidence, (list, tuple, set)):
        return bool(evidence)
    if isinstance(evidence, str):
        return bool(evidence.strip())
    answer = str(result.get("answer") or "").lower()
    if answer and not any(marker in answer for marker in ("could not find", "no match", "no indexed", "no functions")):
        return True
    return False


def _github_review_candidates(results: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    from tech_connector.services.external_tool_service import rank_github_candidate_repos

    candidates: list[dict[str, Any]] = []
    for raw in results:
        item = dict(raw or {})
        url = item.get("html_url") or item.get("url") or ""
        name = item.get("name") or item.get("full_name") or url
        if not name and not url:
            continue
        candidates.append(
            {
                "name": name,
                "description": item.get("description") or "",
                "stars": int(item.get("stars") or item.get("stargazers_count") or 0),
                "html_url": url,
                "language": item.get("language") or "",
                "license": item.get("license") or {},
                "size": int(item.get("size") or 0),
                "archived": bool(item.get("archived", False)),
                "updated_at": item.get("updated_at") or "",
            }
        )
    return rank_github_candidate_repos(candidates, limit=limit)


def _handle_github_ingest(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.github_ingest_service import download_and_extract_repo, parse_github_repo_reference
    from tech_connector.services.external_tool_service import analyze_installed_tool, verify_external_tool_for_pipeline
    from tech_connector.services.tool_discovery_service import list_ingested_tools
    args = _action_args(action)
    repo_url = args.get("url") or args.get("repo")
    if not repo_url:
        return {"ok": False, "error": "github_ingest requires repo or url."}
    if context.dry_run:
        return {"ok": True, "dry_run": True, "repo": repo_url}
    ref = parse_github_repo_reference(str(repo_url))
    target_parent = Path(args.get("target_parent") or context.policy.get("external_tools_dir") or (Path(context.project_root or ".") / "external_tools"))
    path = download_and_extract_repo(ref.repo, ref.clean_url, target_parent)
    symbols = list_ingested_tools(Path(path))
    manifest = analyze_installed_tool(Path(path), {"full_name": ref.full_name, "html_url": ref.clean_url})
    goal = str(
        args.get("goal")
        or args.get("query")
        or args.get("prompt")
        or context.policy.get("original_prompt")
        or context.policy.get("prompt")
        or repo_url
    )
    verification = verify_external_tool_for_pipeline(
        Path(path),
        goal,
        symbols=symbols,
        repo_info={"full_name": ref.full_name, "html_url": ref.clean_url},
        host=str(args.get("host") or context.current_dcc_host or context.policy.get("host") or ""),
    )
    registered = _register_ingested_repository(Path(path), context, repo_name=ref.repo, repo_url=ref.clean_url, symbols=symbols)
    return {
        "ok": True,
        "repository_root": str(path),
        "repo": ref.full_name,
        "external_tools_dir": str(target_parent),
        "symbol_count": len(symbols),
        "registered_capability_ids": registered,
        "tool_manifest": manifest,
        "pipeline_import_verification": verification,
        "pipeline_import_candidates": verification.get("candidates", []),
        "requires_user_selection": verification.get("requires_user_selection", True),
    }


def _handle_index_repository(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.external_tool_service import verify_external_tool_for_pipeline
    from tech_connector.services.tool_discovery_service import list_ingested_tools
    args = _action_args(action)
    repo_root = args.get("repository_root") or args.get("path") or args.get("source")
    if isinstance(repo_root, dict):
        repo_root = repo_root.get("repository_root") or repo_root.get("path")
    if not repo_root:
        return {"ok": False, "error": "index_repository requires repository_root/path."}
    symbols = list_ingested_tools(Path(repo_root))
    goal = str(
        args.get("goal")
        or args.get("query")
        or args.get("prompt")
        or context.policy.get("original_prompt")
        or context.policy.get("prompt")
        or Path(repo_root).name
    )
    verification = verify_external_tool_for_pipeline(
        Path(repo_root),
        goal,
        symbols=symbols,
        repo_info={"full_name": str(args.get("repo_name") or Path(repo_root).name), "html_url": str(args.get("repo_url") or args.get("url") or "")},
        host=str(args.get("host") or context.current_dcc_host or context.policy.get("host") or ""),
    )
    registered = _register_ingested_repository(
        Path(repo_root),
        context,
        repo_name=str(args.get("repo_name") or Path(repo_root).name),
        repo_url=str(args.get("repo_url") or args.get("url") or ""),
        symbols=symbols,
    )
    return {
        "ok": True,
        "repository_root": str(repo_root),
        "symbol_count": len(symbols),
        "symbols": symbols[:50],
        "registered_capability_ids": registered,
        "pipeline_import_verification": verification,
        "pipeline_import_candidates": verification.get("candidates", []),
        "requires_user_selection": verification.get("requires_user_selection", True),
    }


def _register_ingested_repository(
    repo_root: Path,
    context: ExecutionContext,
    *,
    repo_name: str = "",
    repo_url: str = "",
    symbols: list[dict[str, Any]] | None = None,
) -> list[str]:
    symbols = list(symbols or [])
    if not symbols:
        return []
    registry = context.service("capability_registry")
    if registry is None:
        registry_path = context.policy.get("capability_registry_path")
        if not registry_path and context.project_root:
            from tech_connector.models.constants import capability_registry_path

            registry_path = str(capability_registry_path(context.project_root))
        if registry_path:
            try:
                from tech_connector.services.capability_registry import CapabilityRegistry

                registry = CapabilityRegistry(Path(str(registry_path)))
            except Exception:
                registry = None
    if registry is None or not hasattr(registry, "register_ingested_tool"):
        return []
    try:
        entries = registry.register_ingested_tool(
            repo_name=repo_name or repo_root.name,
            repo_url=repo_url,
            local_dir=repo_root,
            symbols=symbols,
            notes="Registered from ActionGraph GitHub ingestion.",
        )
        if hasattr(registry, "save"):
            registry.save()
        return [str(entry.id) for entry in entries]
    except Exception:
        return []


def _handle_resolve_dcc_capability(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    request = args.get("request") or args.get("query") or ""
    service = context.service("project_intelligence")
    if service and hasattr(service, "resolve_unreal_capability"):
        result = service.resolve_unreal_capability(request)
        return {"ok": bool(result), "result": result}
    from tech_connector.services.unreal.capability_graph_service import resolve_unreal_capability
    return {"ok": True, "result": resolve_unreal_capability(str(request), context.project_root or ".")}


def _handle_validate_dcc_call(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    name = args.get("name") or args.get("request") or ""
    payload = args.get("payload") or {}
    service = context.service("project_intelligence")
    if service and hasattr(service, "validate_unreal_capability"):
        result = service.validate_unreal_capability(name, payload)
        return {"ok": bool(result), "result": result}
    from tech_connector.services.unreal.capability_graph_service import validate_unreal_graph_call
    result = validate_unreal_graph_call(str(name), payload, context.project_root or ".")
    return {"ok": bool(result.get("valid")), "result": result}


def _handle_execute_dcc(
    action: dict[str, Any],
    context: ExecutionContext,
    *,
    force_query: bool = False,
) -> dict[str, Any]:
    """Execute a generic ActionGraph DCC operation through the canonical DCC layer."""
    try:
        from reasoning_runtime.engine.request_context import RequestContext
    except Exception:
        @dataclass(frozen=True)
        class RequestContext:  # type: ignore[no-redef]
            text: str
            current_file_path: str = ""
            project_roots: tuple[str, ...] = ()
            extras: dict[str, Any] = field(default_factory=dict)

    from tech_connector.game_engine.integration.dcc_execution_service import build_dcc_execution_request, default_dcc_execution_adapters

    args = _action_args(action)
    operation_contract = dict(args.get("operation_contract") or {})
    execution_context = dict(args.get("execution_context") or operation_contract.get("execution_context") or {})
    host = str(args.get("host") or execution_context.get("host") or operation_contract.get("execution_host") or context.current_dcc_host or "").strip()
    operation = str(args.get("operation") or args.get("target_identifier") or operation_contract.get("capability") or "").strip()
    callable_name = str(args.get("callable") or args.get("callable_name") or "").strip()
    params = dict(args.get("params") or args.get("payload") or {})
    if args.get("code") is not None:
        params["code"] = args.get("code")
    if not operation and params.get("code") and host in {"maya", "blender", "houdini"}:
        operation = "script.run"
    query_only = force_query or str(args.get("operation_mode") or "").lower() == "query"

    route_decision = {
        "route": "dcc_query" if query_only else "dcc_execute",
        "execution_route": "dcc.execution_pipeline",
        "provider": "dcc",
        "intent_category": "dcc_query" if query_only else "dcc_execution",
        "host": host,
        "execution_environment": host,
        "operation_mode": "query" if query_only else "preview" if context.dry_run else "execute",
        "target_type": "dcc_callable",
        "target_identifier": operation,
        "callable_name": callable_name,
        "keyword_args": params,
        "mutation_scope": "read_only" if query_only else action.get("mutability") or "dcc_scene_mutation",
        "risk_level": "low" if query_only else "high",
        "requires_confirmation": False if query_only else bool(action.get("requires_approval")),
        "approved": True if query_only else bool(context.approved),
    }
    request_context = RequestContext(
        text=str(context.policy.get("original_prompt") or context.policy.get("goal") or action.get("description") or action.get("title") or operation),
        current_file_path=context.active_file,
        project_roots=tuple(context.roots()),
        extras={"window": context.window, **dict(context.services or {})},
    )
    request = build_dcc_execution_request(route_decision, request_context)
    original_prompt = str(request.original_prompt or request_context.text or "")
    generic_function = str(params.get("function") or "").strip()
    unresolved_generic_function = bool(
        operation in {"api.call", "tool.call"}
        and generic_function
        and generic_function.casefold() not in original_prompt.casefold()
    )
    if "callable" in request.missing_slots or unresolved_generic_function:
        from tech_connector.game_engine.integration.dcc_operation_service import build_dcc_capability_gap_plan

        unresolved_name = generic_function or request.callable_name or request.target_identifier or operation
        gap = build_dcc_capability_gap_plan(
            host,
            unresolved_name,
            original_request=original_prompt,
        )
        return {
            "ok": False,
            "status": "capability_gap",
            "error": gap["block_reason"],
            "capability_gap": gap,
            "request": request.to_dict(),
            "requires_replan": True,
        }
    adapter = default_dcc_execution_adapters().get(request.execution_environment)
    if not adapter:
        return {"ok": False, "error": f"No DCC execution adapter registered for host: {request.execution_environment or '<missing>'}", "request": request.to_dict()}
    capability_check = adapter.check_capabilities(request, request_context)
    if not capability_check.ok:
        return {"ok": False, "error": "DCC capability preflight failed.", "failures": capability_check.to_dict().get("failures", []), "request": request.to_dict()}
    if context.dry_run or request.preview_only or request.operation_mode == "preview":
        dispatch_result = adapter.preview(request, request_context)
    elif request.operation_mode == "query":
        dispatch_result = adapter.query(request, request_context)
    else:
        dispatch_result = adapter.execute(request, request_context)
    result_data = dispatch_result.to_dict()
    return {
        "ok": dispatch_result.status in {"success", "completed", "ok", "preview", "confirmation_required"},
        "status": dispatch_result.status,
        "request": request.to_dict(),
        "result": result_data,
        "requires_confirmation": dispatch_result.status == "confirmation_required",
    }


def _handle_execute_dcc_capability(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    request = args.get("request") or args.get("query") or ""
    payload = args.get("payload") or {}
    service = context.service("project_intelligence")
    if service and hasattr(service, "execute_unreal_capability"):
        result = service.execute_unreal_capability(request, payload, dry_run=context.dry_run)
        return {"ok": bool(result), "result": result}
    from tech_connector.services.unreal.capability_graph_service import execute_unreal_capability
    result = execute_unreal_capability(str(request), payload, context.project_root or ".", dry_run=context.dry_run)
    return {"ok": bool(result.get("success")), "result": result}


def _handle_execute_unreal_python(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    args = _action_args(action)
    code = args.get("code") or ""
    if context.dry_run:
        return {"ok": True, "dry_run": True, "code_preview": str(code)[:500]}
    bridge = context.service("unreal_bridge")
    if bridge and hasattr(bridge, "execute_python"):
        response = bridge.execute_python(str(code), timeout=float(args.get("timeout") or 30.0))
        if isinstance(response, dict):
            return {
                "ok": bool(response.get("ok")),
                "output": response.get("data") if response.get("ok") else response.get("error"),
                "response": response,
            }
        if isinstance(response, tuple) and len(response) >= 2:
            ok, output = response[0], response[1]
            return {"ok": bool(ok), "output": output}
        return {"ok": bool(response), "output": response}
    return {"ok": False, "error": "No Unreal bridge adapter is available."}


def _handle_asset_source_search(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.external_asset_acquisition_service import search_asset_candidates
    args = _action_args(action)
    candidates = search_asset_candidates(
        query=args.get("query", ""),
        asset_type=args.get("asset_type", ""),
        target_host=args.get("target_host", ""),
        providers=args.get("providers"),
        limit=args.get("limit", 8),
        settings=args.get("settings"),
        active_only=bool(args.get("active_only", True)),
    )
    return {"ok": True, "candidate_assets": candidates}


def _handle_download_or_ingest_asset(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.external_asset_acquisition_service import download_asset_candidate
    args = _action_args(action)
    candidates = args.get("candidate_assets") or []
    idx = args.get("selected_index", 0)
    if not candidates or idx >= len(candidates):
        return {"ok": False, "error": "No candidate selected or empty candidate list."}
    candidate = candidates[idx]
    cache_root = args.get("cache_root") or str(temp_output_path("assets", subdir="asset_cache"))
    approved = bool(args.get("approved") or context.approved)
    target_host = args.get("target_host") or ""
    destination = args.get("destination") or ""
    return download_asset_candidate(
        candidate,
        cache_root=cache_root,
        approved=approved,
        target_host=target_host,
        destination=destination,
    )

