"""Canonical ActionExecutionEngine for Tech Connector action graphs."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import copy
import re
import uuid
from typing import Any, Callable

from tech_connector.services.action_contract_service import canonical_action_type, validate_planner_executor_contract
from tech_connector.services.action_graph_service import (
    ACTION_TYPES,
    MUTABILITY_READ_ONLY,
    normalize_action,
    normalize_action_graph,
    validate_action_graph,
)


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


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
    compensate_fn: Callable[[dict[str, Any], ExecutionContext], dict[str, Any]] | None = None

    def validate(self, action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if self.validate_fn:
            return self.validate_fn(action, context)
        return {"valid": True, "errors": [], "warnings": []}

    def execute(self, action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
        if not self.execute_fn:
            return {"ok": False, "error": "Handler has no execution function."}
        return self.execute_fn(action, context)


class ActionHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ActionHandler] = {}

    def register(self, handler: ActionHandler) -> None:
        if handler.action_type in self._handlers:
            raise ValueError(f"Duplicate action handler registered: {handler.action_type}")
        if handler.action_type not in ACTION_TYPES:
            raise ValueError(f"Cannot register unknown action type: {handler.action_type}")
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


def _result_path(value: Any, path: str) -> Any:
    current = value
    if not path:
        return current
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


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
        errors = list(validation.get("errors") or [])
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
            failed_deps = [dep for dep in action.get("depends_on") or [] if statuses.get(dep, {}).get("status") not in {"completed"}]
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
            statuses[action_id] = {"status": "completed" if result.get("ok") else "failed", "result": result}
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
        try:
            validation = handler.validate(action, execution_context)
            if not validation.get("valid", True):
                result = {"ok": False, "error": "action validation failed", "validation": validation}
            else:
                result = handler.execute(action, execution_context)
                if result is None:
                    result = {"ok": True}
                result.setdefault("ok", True)
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "exception_type": type(exc).__name__}
        if execution_id and plan_id:
            event_type = "action_completed" if result.get("ok") else "action_failed"
            status = "completed" if result.get("ok") else "failed"
            self._emit(execution_context, ActionEvent(event_type, execution_id, plan_id, action["id"], action["type"], status, f"{action['type']} {status}", result))
        return result

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
        if any(v.get("status") == "failed" for v in statuses.values()):
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
    registry.register(ActionHandler("query_dcc", "tech_connector.services.dcc.dcc_execution_service", execute_fn=lambda a, c: _handle_execute_dcc(a, c, force_query=True)))
    registry.register(ActionHandler("execute_dcc", "tech_connector.services.dcc.dcc_execution_service", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_dcc(a, c)))
    registry.register(ActionHandler("execute_dcc_capability", "tech_connector.services.project_intelligence_service/unreal capability services", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_dcc_capability(a, c)))
    registry.register(ActionHandler("execute_unreal_python", "tech_connector.bridges.unreal.unreal_bridge.execute_python", mutability="dcc_mutation", execute_fn=lambda a, c: _handle_execute_unreal_python(a, c)))
    registry.register(ActionHandler("execute_workflow", "generated workflow callable", mutability="dcc_mutation", execute_fn=lambda a, c: {"ok": False, "error": "execute_workflow requires a registered workflow runner adapter"}))
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
    if context.dry_run:
        return {"ok": True, "dry_run": True, "query": args.get("query")}
    search_service = context.service("github_search")
    if search_service and hasattr(search_service, "search"):
        return {"ok": True, "results": search_service.search(args.get("query"))}
    return {"ok": False, "error": "GitHub search has no non-UI service adapter yet.", "query": args.get("query")}


def _handle_github_ingest(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.github_ingest_service import download_and_extract_repo, parse_github_repo_reference
    args = _action_args(action)
    repo_url = args.get("url") or args.get("repo")
    if not repo_url:
        return {"ok": False, "error": "github_ingest requires repo or url."}
    if context.dry_run:
        return {"ok": True, "dry_run": True, "repo": repo_url}
    ref = parse_github_repo_reference(str(repo_url))
    target_parent = Path(args.get("target_parent") or context.policy.get("external_tools_dir") or (Path(context.project_root or ".") / "external_tools"))
    path = download_and_extract_repo(ref.repo, ref.clean_url, target_parent)
    return {"ok": True, "repository_root": str(path), "repo": ref.full_name}


def _handle_index_repository(action: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    from tech_connector.services.tool_discovery_service import list_ingested_tools
    args = _action_args(action)
    repo_root = args.get("repository_root") or args.get("path") or args.get("source")
    if isinstance(repo_root, dict):
        repo_root = repo_root.get("repository_root") or repo_root.get("path")
    if not repo_root:
        return {"ok": False, "error": "index_repository requires repository_root/path."}
    symbols = list_ingested_tools(Path(repo_root))
    return {"ok": True, "repository_root": str(repo_root), "symbol_count": len(symbols), "symbols": symbols[:50]}


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
    from tech_connector.engine.request_context import RequestContext
    from tech_connector.services.dcc.dcc_execution_service import build_dcc_execution_request, default_dcc_execution_adapters

    args = _action_args(action)
    operation_contract = dict(args.get("operation_contract") or {})
    execution_context = dict(args.get("execution_context") or operation_contract.get("execution_context") or {})
    host = str(args.get("host") or execution_context.get("host") or operation_contract.get("execution_host") or context.current_dcc_host or "").strip()
    operation = str(args.get("operation") or args.get("target_identifier") or operation_contract.get("capability") or "").strip()
    callable_name = str(args.get("callable") or args.get("callable_name") or "").strip()
    params = dict(args.get("params") or args.get("payload") or {})
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
        from tech_connector.services.dcc.dcc_operation_service import build_dcc_capability_gap_plan

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
