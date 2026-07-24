"""Canonical action graph intermediate representation for Tech Connector.

The action graph is the common shape between a prompt and execution. It is not
generated code and it does not imply that every action should run immediately.
Validation and approval can inspect this structure before any mutation happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any
import uuid

from tech_connector.services.action_contract_service import canonical_action_type


ACTION_TYPES = {
    "resolve_symbol",
    "resolve_function",
    "resolve_class",
    "resolve_asset",
    "resolve_workflow",
    "resolve_pipeline",
    "resolve_file",
    "open_file",
    "open_symbol",
    "request_input",
    "inspect_function",
    "inspect_workflow",
    "create_node",
    "create_pipeline_node",
    "delete_node",
    "delete_pipeline_node",
    "move_node",
    "rename_node",
    "connect_data",
    "disconnect_data",
    "connect_flow",
    "disconnect_flow",
    "bind_literal",
    "bind_variable",
    "generate_python",
    "execute_python",
    "execute_workflow",
    "query_dcc",
    "execute_dcc",
    "validate_workflow",
    "validate_dcc_call",
    "validate",
    "validate_graph",
    "generate_workflow_code",
    "save_document",
    "save_workflow",
    "show_diff",
    "apply_code_patch",
    "create_file",
    "update_file",
    "git_diff",
    "git_commit",
    "github_search",
    "github_ingest",
    "index_project",
    "index_repository",
    "index_ingested_repository",
    "rebuild_index",
    "rebuild_project_index",
    "refresh_project_index",
    "refresh_unreal",
    "refresh_maya",
    "refresh_blender",
    "search_docs",
    "search_project",
    "search_assets",
    "resolve_dcc_capability",
    "execute_dcc_capability",
    "execute_unreal_python",
}


MUTATING_ACTION_TYPES = {
    "create_node",
    "create_pipeline_node",
    "delete_node",
    "delete_pipeline_node",
    "move_node",
    "rename_node",
    "connect_data",
    "disconnect_data",
    "connect_flow",
    "disconnect_flow",
    "bind_literal",
    "bind_variable",
    "generate_python",
    "execute_python",
    "execute_workflow",
    "execute_dcc",
    "execute_dcc_capability",
    "execute_unreal_python",
    "save_document",
    "save_workflow",
    "apply_code_patch",
    "create_file",
    "update_file",
    "git_commit",
    "github_ingest",
    "index_project",
    "index_repository",
    "index_ingested_repository",
    "rebuild_index",
    "rebuild_project_index",
    "refresh_project_index",
    "refresh_unreal",
    "refresh_maya",
    "refresh_blender",
}


MUTABILITY_READ_ONLY = "read_only"
MUTABILITY_LOCAL_REVERSIBLE = "local_reversible_mutation"
MUTABILITY_PERSISTENT_LOCAL = "persistent_local_mutation"
MUTABILITY_EXTERNAL = "external_mutation"
MUTABILITY_DCC = "dcc_mutation"


ACTION_MUTABILITY = {
    "search_project": MUTABILITY_READ_ONLY,
    "search_docs": MUTABILITY_READ_ONLY,
    "search_assets": MUTABILITY_READ_ONLY,
    "resolve_symbol": MUTABILITY_READ_ONLY,
    "resolve_function": MUTABILITY_READ_ONLY,
    "resolve_class": MUTABILITY_READ_ONLY,
    "resolve_asset": MUTABILITY_READ_ONLY,
    "resolve_workflow": MUTABILITY_READ_ONLY,
    "resolve_pipeline": MUTABILITY_READ_ONLY,
    "resolve_file": MUTABILITY_READ_ONLY,
    "open_symbol": MUTABILITY_LOCAL_REVERSIBLE,
    "open_file": MUTABILITY_LOCAL_REVERSIBLE,
    "request_input": MUTABILITY_READ_ONLY,
    "inspect_function": MUTABILITY_READ_ONLY,
    "inspect_workflow": MUTABILITY_READ_ONLY,
    "validate": MUTABILITY_READ_ONLY,
    "validate_graph": MUTABILITY_READ_ONLY,
    "validate_workflow": MUTABILITY_READ_ONLY,
    "validate_dcc_call": MUTABILITY_READ_ONLY,
    "generate_python": MUTABILITY_READ_ONLY,
    "generate_workflow_code": MUTABILITY_READ_ONLY,
    "show_diff": MUTABILITY_READ_ONLY,
    "git_diff": MUTABILITY_READ_ONLY,
    "github_search": MUTABILITY_READ_ONLY,
    "resolve_dcc_capability": MUTABILITY_READ_ONLY,
    "create_node": MUTABILITY_LOCAL_REVERSIBLE,
    "create_pipeline_node": MUTABILITY_LOCAL_REVERSIBLE,
    "delete_node": MUTABILITY_LOCAL_REVERSIBLE,
    "delete_pipeline_node": MUTABILITY_LOCAL_REVERSIBLE,
    "move_node": MUTABILITY_LOCAL_REVERSIBLE,
    "rename_node": MUTABILITY_LOCAL_REVERSIBLE,
    "connect_data": MUTABILITY_LOCAL_REVERSIBLE,
    "disconnect_data": MUTABILITY_LOCAL_REVERSIBLE,
    "connect_flow": MUTABILITY_LOCAL_REVERSIBLE,
    "disconnect_flow": MUTABILITY_LOCAL_REVERSIBLE,
    "bind_literal": MUTABILITY_LOCAL_REVERSIBLE,
    "bind_variable": MUTABILITY_LOCAL_REVERSIBLE,
    "save_document": MUTABILITY_PERSISTENT_LOCAL,
    "save_workflow": MUTABILITY_PERSISTENT_LOCAL,
    "apply_code_patch": MUTABILITY_PERSISTENT_LOCAL,
    "create_file": MUTABILITY_PERSISTENT_LOCAL,
    "update_file": MUTABILITY_PERSISTENT_LOCAL,
    "index_project": MUTABILITY_PERSISTENT_LOCAL,
    "rebuild_index": MUTABILITY_PERSISTENT_LOCAL,
    "rebuild_project_index": MUTABILITY_PERSISTENT_LOCAL,
    "refresh_project_index": MUTABILITY_PERSISTENT_LOCAL,
    "index_repository": MUTABILITY_PERSISTENT_LOCAL,
    "index_ingested_repository": MUTABILITY_PERSISTENT_LOCAL,
    "github_ingest": MUTABILITY_EXTERNAL,
    "git_commit": MUTABILITY_EXTERNAL,
    "refresh_unreal": MUTABILITY_DCC,
    "refresh_maya": MUTABILITY_DCC,
    "refresh_blender": MUTABILITY_DCC,
    "execute_python": MUTABILITY_DCC,
    "execute_workflow": MUTABILITY_DCC,
    "execute_dcc": MUTABILITY_DCC,
    "execute_dcc_capability": MUTABILITY_DCC,
    "execute_unreal_python": MUTABILITY_DCC,
}


@dataclass
class Action:
    type: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"action_{uuid.uuid4().hex[:10]}")
    version: int = 1
    title: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    target_refs: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    mutability: str = ""
    requires_approval: bool | None = None
    source: str = "deterministic"
    status: str = "planned"
    validation_status: str = "not_validated"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    timestamps: dict[str, str] = field(default_factory=dict)
    compensation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action_id"] = data["id"]
        data["action_type"] = data["type"]
        data["input"] = data["args"]
        if not data["title"]:
            data["title"] = data["type"].replace("_", " ").title()
        if not data["mutability"]:
            data["mutability"] = ACTION_MUTABILITY.get(self.type, MUTABILITY_READ_ONLY)
        if data["requires_approval"] is None or data["mutability"] != MUTABILITY_READ_ONLY:
            data["requires_approval"] = data["mutability"] != MUTABILITY_READ_ONLY
        return data


@dataclass
class ActionGraph:
    goal: str
    intent: str
    actions: list[Action] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:10]}")
    version: int = 1
    planner: str = "deterministic"
    confidence: float = 0.0
    diagnostics: list[str] = field(default_factory=list)

    def add(self, action_type: str, args: dict[str, Any] | None = None, **kwargs) -> Action:
        action = Action(action_type, args or {}, **kwargs)
        self.actions.append(action)
        return action

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "intent": self.intent,
            "plan_id": self.plan_id,
            "version": self.version,
            "planner": self.planner,
            "confidence": self.confidence,
            "diagnostics": self.diagnostics,
            "actions": [action.to_dict() for action in self.actions],
        }


def normalize_action(action: Action | dict[str, Any]) -> dict[str, Any]:
    data = action.to_dict() if isinstance(action, Action) else dict(action or {})
    action_type = canonical_action_type(data.get("action_type") or data.get("type"))
    action_id = data.get("action_id") or data.get("id") or f"action_{uuid.uuid4().hex[:10]}"
    payload = data.get("input")
    if payload is None:
        payload = data.get("payload")
    if payload is None:
        payload = data.get("arguments")
    if payload is None:
        payload = data.get("args") or {}
    data["id"] = action_id
    data["action_id"] = action_id
    data["type"] = action_type
    data["action_type"] = action_type
    data["args"] = payload or {}
    data["input"] = payload or {}
    data.setdefault("version", 1)
    data.setdefault("title", str(action_type or "Action").replace("_", " ").title())
    data.setdefault("description", "")
    data.setdefault("depends_on", list(data.get("dependency_action_ids") or []))
    data.setdefault("dependency_action_ids", list(data.get("depends_on") or []))
    data.setdefault("target_refs", [])
    data.setdefault("source_refs", [])
    data.setdefault("mutability", ACTION_MUTABILITY.get(str(action_type), MUTABILITY_READ_ONLY))
    if data["mutability"] != MUTABILITY_READ_ONLY:
        data["requires_approval"] = True
    else:
        data.setdefault("requires_approval", False)
    data.setdefault("status", "planned")
    data.setdefault("validation_status", "not_validated")
    data.setdefault("result", None)
    data.setdefault("error", None)
    data.setdefault("warnings", [])
    data.setdefault("diagnostics", [])
    data.setdefault("timestamps", {})
    data.setdefault("compensation", None)
    return data


def normalize_action_graph(graph: ActionGraph | dict[str, Any]) -> dict[str, Any]:
    data = graph.to_dict() if isinstance(graph, ActionGraph) else dict(graph or {})
    data.setdefault("plan_id", f"plan_{uuid.uuid4().hex[:10]}")
    data.setdefault("version", 1)
    data.setdefault("goal", "")
    data.setdefault("intent", "unknown")
    data.setdefault("planner", "unknown")
    data.setdefault("confidence", 0.0)
    data.setdefault("diagnostics", [])
    data["actions"] = [normalize_action(action) for action in data.get("actions") or []]
    return data


def validate_action_graph(graph: ActionGraph | dict[str, Any]) -> dict[str, Any]:
    data = normalize_action_graph(graph)
    actions = data.get("actions") or []
    ids = set()
    errors: list[str] = []
    warnings: list[str] = []

    for index, action in enumerate(actions, start=1):
        action_type = action.get("type")
        action_id = action.get("id") or f"action_{index}"
        if action_type not in ACTION_TYPES:
            errors.append(f"{action_id}: unknown action type {action_type!r}")
        if action_id in ids:
            errors.append(f"{action_id}: duplicate action id")
        ids.add(action_id)

    for action in actions:
        action_id = action.get("id") or ""
        for dep in action.get("depends_on") or []:
            if dep not in ids:
                errors.append(f"{action_id}: missing dependency {dep!r}")

        action_type = action.get("type")
        args = action.get("args") or {}
        if action_type in {"open_file", "resolve_file"} and not (args.get("path") or args.get("query")):
            errors.append(f"{action_id}: file action requires path or query")
        if action_type in {"resolve_function", "resolve_symbol", "resolve_class", "open_symbol"} and not (args.get("query") or args.get("symbol")):
            errors.append(f"{action_id}: symbol action requires query or symbol")
        if action_type == "request_input" and not (args.get("argument") or args.get("question")):
            errors.append(f"{action_id}: request_input requires argument or question")
        if action_type == "connect_data":
            if not (args.get("from") and args.get("to")):
                errors.append(f"{action_id}: connect_data requires from and to endpoints")
        if action_type == "connect_flow":
            if not (args.get("from") and args.get("to")):
                errors.append(f"{action_id}: connect_flow requires from and to nodes")
        if action_type == "bind_literal":
            if not (args.get("node") and args.get("parameter")):
                errors.append(f"{action_id}: bind_literal requires node and parameter")
        if action_type == "execute_dcc":
            contract = args.get("operation_contract") or {}
            operation = args.get("operation") or args.get("target_identifier") or contract.get("capability")
            callable_name = args.get("callable") or args.get("callable_name") or contract.get("callable")
            if not (operation or callable_name):
                errors.append(f"{action_id}: execute_dcc action requires an operation or callable")
        if action_type == "github_ingest" and not (args.get("repo") or args.get("url")):
            warnings.append(f"{action_id}: github_ingest will need a selected repo/url before execution")

    approval_required = any(bool(action.get("requires_approval")) for action in actions)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "approval_required": approval_required,
        "action_count": len(actions),
    }


def format_action_graph(graph: ActionGraph | dict[str, Any]) -> str:
    data = graph.to_dict() if isinstance(graph, ActionGraph) else graph
    validation = validate_action_graph(data)
    lines = [
        "Execution Plan:",
        f"Intent: {data.get('intent')}",
        f"Planner: {data.get('planner')}",
        f"Confidence: {data.get('confidence')}",
        f"Approval required: {'yes' if validation['approval_required'] else 'no'}",
        "",
        "Actions:",
    ]
    for index, action in enumerate(data.get("actions") or [], start=1):
        args = action.get("args") or {}
        lines.append(f"{index}. {action.get('type')}  id={action.get('id')}")
        for key, value in args.items():
            if key == "symbol" and isinstance(value, dict):
                lines.append(f"   {key}: {value.get('name')} [{value.get('file_path')}]")
            else:
                lines.append(f"   {key}: {value}")
    if validation["errors"]:
        lines.extend(["", "Validation errors:", *[f"- {item}" for item in validation["errors"]]])
    if validation["warnings"]:
        lines.extend(["", "Validation warnings:", *[f"- {item}" for item in validation["warnings"]]])
    return "\n".join(lines)
