from __future__ import annotations

"""Canonical, reversible code and graph programs for TC game authoring."""

import ast
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import keyword
import math
import re
from threading import RLock
import tokenize
from io import StringIO
from typing import Any, Iterable


ENGINE_GRAPH_SCHEMA = "tech_connector.engine_graph_program.v1"


def _friendly_name(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value).replace("_", " ").replace(".", " ")).split()
    return " ".join(word.upper() if word.lower() in {"ai", "fps", "id", "ik", "ui", "uv"} else word.capitalize() for word in words)


def _identifier(value: str, fallback: str = "value") -> str:
    text = re.sub(r"\W+", "_", str(value)).strip("_").lower() or fallback
    if text[0].isdigit() or keyword.iskeyword(text):
        text = f"{fallback}_{text}"
    return text


@dataclass(frozen=True)
class GraphPropertyDefinition:
    key: str
    display_name: str
    description: str
    value_type: str = "Any"
    default: Any = None
    units: str = ""
    minimum: float | None = None
    maximum: float | None = None
    advanced: bool = False
    required: bool = False
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphOperationDefinition:
    operation: str
    display_name: str
    description: str
    category: str
    inputs: tuple[GraphPropertyDefinition, ...] = ()
    output_name: str = "result"
    output_type: str = "Any"
    execution: str = "immediate"
    graph_kinds: tuple[str, ...] = ()
    owner_types: tuple[str, ...] = ()
    selection_types: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphAuthoringContext:
    graph_kind: str = "gameplay"
    owner_type: str = ""
    selected_types: tuple[str, ...] = ()
    available_capabilities: tuple[str, ...] = ()
    dragged_output_type: str = ""
    requested_input_type: str = ""
    authority: str = "any"

    @classmethod
    def from_value(cls, value: "GraphAuthoringContext | dict[str, Any] | None") -> "GraphAuthoringContext":
        if isinstance(value, cls):
            return value
        data = dict(value or {})
        return cls(
            graph_kind=str(data.get("graph_kind") or "gameplay"),
            owner_type=str(data.get("owner_type") or ""),
            selected_types=tuple(str(item) for item in data.get("selected_types") or ()),
            available_capabilities=tuple(str(item) for item in data.get("available_capabilities") or ()),
            dragged_output_type=str(data.get("dragged_output_type") or ""),
            requested_input_type=str(data.get("requested_input_type") or ""),
            authority=str(data.get("authority") or "any"),
        )


@dataclass
class GraphInputBinding:
    mode: str = "literal"
    literal: Any = None
    source_node: str = ""
    source_output: str = "result"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphInputBinding":
        return cls(
            mode=str(value.get("mode") or "literal"),
            literal=deepcopy(value.get("literal")),
            source_node=str(value.get("source_node") or ""),
            source_output=str(value.get("source_output") or "result"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineGraphNode:
    node_id: str
    operation: str
    display_name: str = ""
    inputs: dict[str, GraphInputBinding] = field(default_factory=dict)
    output_name: str = "result"
    position: tuple[float, float] = (0.0, 0.0)
    comment: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EngineGraphNode":
        return cls(
            node_id=str(value.get("node_id") or ""),
            operation=str(value.get("operation") or ""),
            display_name=str(value.get("display_name") or ""),
            inputs={str(key): GraphInputBinding.from_dict(item) for key, item in dict(value.get("inputs") or {}).items()},
            output_name=str(value.get("output_name") or "result"),
            position=tuple(value.get("position") or (0.0, 0.0))[:2],
            comment=str(value.get("comment") or ""),
            enabled=bool(value.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "operation": self.operation,
            "display_name": self.display_name,
            "inputs": {key: value.to_dict() for key, value in sorted(self.inputs.items())},
            "output_name": self.output_name,
            "position": list(self.position),
            "comment": self.comment,
            "enabled": self.enabled,
        }


@dataclass
class EngineGraphProgram:
    program_id: str
    display_name: str
    entry_event: str = "On Begin Play"
    nodes: list[EngineGraphNode] = field(default_factory=list)
    flow: list[str] = field(default_factory=list)
    description: str = ""
    version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EngineGraphProgram":
        return cls(
            program_id=str(value.get("program_id") or "graph_program"),
            display_name=str(value.get("display_name") or "Graph Program"),
            entry_event=str(value.get("entry_event") or "On Begin Play"),
            nodes=[EngineGraphNode.from_dict(item) for item in value.get("nodes") or ()],
            flow=[str(item) for item in value.get("flow") or ()],
            description=str(value.get("description") or ""),
            version=max(1, int(value.get("version") or 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ENGINE_GRAPH_SCHEMA,
            "program_id": self.program_id,
            "display_name": self.display_name,
            "entry_event": self.entry_event,
            "nodes": [node.to_dict() for node in self.nodes],
            "flow": list(self.flow or [node.node_id for node in self.nodes]),
            "description": self.description,
            "version": self.version,
        }


@dataclass
class GraphCodeSyncResult:
    ok: bool
    program: EngineGraphProgram | None = None
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "program": self.program.to_dict() if self.program else None,
            "diagnostics": deepcopy(self.diagnostics),
        }


_OPERATIONS: dict[str, GraphOperationDefinition] = {}
_OPERATIONS_LOCK = RLock()


def register_graph_operation(
    definition: GraphOperationDefinition,
    *,
    replace: bool = False,
) -> None:
    if not definition.operation or not definition.display_name or not definition.description:
        raise ValueError("Graph operations require an operation key, display name, and description.")
    keys = [item.key for item in definition.inputs]
    if len(keys) != len(set(keys)):
        raise ValueError(f"Graph operation '{definition.operation}' has duplicate input keys.")
    with _OPERATIONS_LOCK:
        if definition.operation in _OPERATIONS and not replace:
            raise KeyError(
                f"Graph operation '{definition.operation}' is already registered."
            )
        _OPERATIONS[definition.operation] = definition


def graph_operation_definition(operation: str) -> GraphOperationDefinition | None:
    with _OPERATIONS_LOCK:
        return _OPERATIONS.get(str(operation))


def unregister_graph_operation(operation: str) -> None:
    with _OPERATIONS_LOCK:
        _OPERATIONS.pop(str(operation), None)


def available_graph_operations() -> list[dict[str, Any]]:
    with _OPERATIONS_LOCK:
        return [_OPERATIONS[key].to_dict() for key in sorted(_OPERATIONS)]


def find_graph_actions(
    query: str = "",
    *,
    context: GraphAuthoringContext | dict[str, Any] | None = None,
    context_sensitive: bool = True,
) -> list[dict[str, Any]]:
    """Return action-menu rows for either the current context or the global library."""

    authoring_context = GraphAuthoringContext.from_value(context)
    terms = [term.casefold() for term in str(query).split() if term]
    rows: list[dict[str, Any]] = []
    with _OPERATIONS_LOCK:
        definitions = tuple(_OPERATIONS.values())
    for definition in definitions:
        searchable = " ".join((
            definition.operation,
            definition.display_name,
            definition.description,
            definition.category,
            *definition.keywords,
            *(item.display_name for item in definition.inputs),
            *(alias for item in definition.inputs for alias in item.aliases),
        )).casefold()
        if terms and not all(term in searchable for term in terms):
            continue
        availability = graph_action_availability(definition, authoring_context)
        if context_sensitive and not availability["available"]:
            continue
        rows.append({
            **definition.to_dict(),
            **availability,
            "scope": "Context" if availability["available"] else "Global",
            "search_score": _action_search_score(definition, terms, availability["available"]),
        })
    return sorted(rows, key=lambda row: (-row["search_score"], row["category"], row["display_name"]))


def graph_action_availability(
    definition: GraphOperationDefinition,
    context: GraphAuthoringContext | dict[str, Any] | None,
) -> dict[str, Any]:
    authoring_context = GraphAuthoringContext.from_value(context)
    reasons: list[str] = []
    if definition.graph_kinds and authoring_context.graph_kind not in definition.graph_kinds:
        reasons.append(f"Designed for {_list_words(definition.graph_kinds)} graphs, not {_friendly_name(authoring_context.graph_kind)}.")
    owner = authoring_context.owner_type.casefold()
    allowed_owners = {item.casefold() for item in definition.owner_types}
    if owner and allowed_owners and owner not in allowed_owners:
        reasons.append(f"Requires an owner such as {_list_words(definition.owner_types)}; current owner is {authoring_context.owner_type}.")
    selected = {item.casefold() for item in authoring_context.selected_types}
    allowed_selection = {item.casefold() for item in definition.selection_types}
    if selected and allowed_selection and not selected.intersection(allowed_selection):
        reasons.append(f"Works with {_list_words(definition.selection_types)} selections, not {_list_words(authoring_context.selected_types)}.")
    missing = [
        item for item in definition.required_capabilities if item not in authoring_context.available_capabilities
    ] if authoring_context.available_capabilities else []
    if missing:
        reasons.append(f"Requires {_list_words(missing)} to be enabled for this project.")
    if definition.authorities and authoring_context.authority not in {"", "any"} and authoring_context.authority not in definition.authorities:
        reasons.append(f"Runs with {_list_words(definition.authorities)} authority, not {_friendly_name(authoring_context.authority)}.")
    if authoring_context.dragged_output_type and not any(
        _types_compatible(authoring_context.dragged_output_type, item.value_type) for item in definition.inputs
    ):
        reasons.append(f"Does not accept {_friendly_name(authoring_context.dragged_output_type)} from the dragged pin.")
    if authoring_context.requested_input_type and not _types_compatible(definition.output_type, authoring_context.requested_input_type):
        reasons.append(f"Produces {_friendly_name(definition.output_type)}, not {_friendly_name(authoring_context.requested_input_type)}.")
    return {
        "available": not reasons,
        "availability_label": "Available Here" if not reasons else "Not Available Here",
        "availability_explanation": "Matches the current graph and selection." if not reasons else " ".join(reasons),
    }


def graph_node_controls(node: EngineGraphNode) -> list[dict[str, Any]]:
    definition = graph_operation_definition(node.operation)
    specs = definition.inputs if definition else tuple(
        GraphPropertyDefinition(key, _friendly_name(key), f"Value supplied to {_friendly_name(node.operation)}.")
        for key in sorted(node.inputs)
    )
    rows: list[dict[str, Any]] = []
    for spec in specs:
        binding = node.inputs.get(spec.key, GraphInputBinding(literal=deepcopy(spec.default)))
        rows.append({
            **spec.to_dict(),
            "value": deepcopy(binding.literal) if binding.mode == "literal" else None,
            "connected": binding.mode == "link",
            "connection": f"{binding.source_node}.{binding.source_output}" if binding.mode == "link" else "",
        })
    return rows


def validate_engine_graph_program(program: EngineGraphProgram) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    ids = [node.node_id for node in program.nodes]
    known = set(ids)
    for node_id in sorted({node_id for node_id in ids if ids.count(node_id) > 1}):
        diagnostics.append(_diagnostic("error", "duplicate_node_id", f"More than one node uses '{node_id}'.", node_id=node_id))
    for node in program.nodes:
        if not node.node_id or not node.operation:
            diagnostics.append(_diagnostic("error", "incomplete_node", "Every node needs an ID and operation.", node_id=node.node_id))
        if graph_operation_definition(node.operation) is None:
            diagnostics.append(_diagnostic("warning", "unknown_operation", f"'{node.operation}' has no registered operation definition yet.", node_id=node.node_id))
        else:
            diagnostics.extend(_validate_node_inputs(node))
        for input_name, binding in node.inputs.items():
            if binding.mode == "link" and binding.source_node not in known:
                diagnostics.append(_diagnostic("error", "missing_source", f"{_friendly_name(input_name)} is connected to missing node '{binding.source_node}'.", node_id=node.node_id))
    if _has_data_cycle(program):
        diagnostics.append(_diagnostic("error", "data_cycle", "The graph contains a data cycle. Add a state or delay node to cross frames safely."))
    return diagnostics


def generate_engine_graph_python(program: EngineGraphProgram) -> str:
    errors = [item for item in validate_engine_graph_program(program) if item["severity"] == "error"]
    if errors:
        raise ValueError("; ".join(item["message"] for item in errors))
    ordered = _ordered_nodes(program)
    variable_by_node: dict[str, str] = {}
    lines = [
        f"# TC Graph Program: {program.display_name}",
        f"# tc-program: {program.program_id}",
        f"# tc-entry-event: {program.entry_event}",
        "from tech_connector.game_engine.runtime.graph_runtime import graph_call",
        "",
        "",
        f"def {_identifier(program.program_id, 'graph')}(context):",
    ]
    if program.description:
        lines.append(f"    {program.description!r}")
    for node in ordered:
        if node.comment:
            lines.append(f"    # {node.comment}")
        lines.append(f"    # tc-node: {node.node_id}")
        arguments = [repr(node.operation), "context=context"]
        for input_name, binding in sorted(node.inputs.items()):
            if binding.mode == "link":
                value = variable_by_node.get(binding.source_node)
                if value is None:
                    raise ValueError(f"Node '{node.node_id}' uses '{binding.source_node}' before it produces a value.")
            else:
                value = repr(binding.literal)
            arguments.append(f"{_identifier(input_name, 'input')}={value}")
        call = f"graph_call({', '.join(arguments)})"
        if node.output_name:
            variable = _unique_variable(node.node_id, set(variable_by_node.values()))
            variable_by_node[node.node_id] = variable
            lines.append(f"    {variable} = {call}")
        else:
            lines.append(f"    {call}")
    if not ordered:
        lines.append("    pass")
    lines.append("")
    return "\n".join(lines)


def parse_engine_graph_python(code: str, previous: EngineGraphProgram | None = None) -> GraphCodeSyncResult:
    try:
        tree = ast.parse(code or "")
    except SyntaxError as exc:
        return GraphCodeSyncResult(False, previous, [_diagnostic("error", "syntax_error", exc.msg, line=exc.lineno or 0, column=exc.offset or 0)])
    function = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if function is None:
        return GraphCodeSyncResult(False, previous, [_diagnostic("error", "missing_function", "Graph code needs one program function.")])
    comments = _comments_by_line(code)
    metadata = _program_metadata(comments)
    previous_layout = {node.node_id: node.position for node in (previous.nodes if previous else ())}
    variable_sources: dict[str, str] = {}
    nodes: list[EngineGraphNode] = []
    diagnostics: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for statement in function.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            continue
        call: ast.Call | None = None
        target_name = ""
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name) and isinstance(statement.value, ast.Call):
            target_name = statement.targets[0].id
            call = statement.value
        elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
        elif isinstance(statement, ast.Pass):
            continue
        else:
            diagnostics.append(_diagnostic("error", "unsupported_statement", "This statement cannot be shown in Graph View yet. Put it in a registered function node or use supported graph control flow.", line=getattr(statement, "lineno", 0)))
            continue
        if not _is_graph_call(call):
            diagnostics.append(_diagnostic("error", "unsupported_call", "Graph View currently represents engine operations through graph_call(...).", line=getattr(statement, "lineno", 0)))
            continue
        operation = _literal(call.args[0]) if call.args else None
        if not isinstance(operation, str) or not operation:
            diagnostics.append(_diagnostic("error", "dynamic_operation", "Operation names must be fixed text so the graph can identify the node.", line=statement.lineno))
            continue
        node_id = _node_id_for_line(comments, statement.lineno) or _identifier(target_name or operation.rsplit(".", 1)[-1], "node")
        base_id = node_id
        suffix = 2
        while node_id in used_ids:
            node_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(node_id)
        definition = graph_operation_definition(operation)
        inputs: dict[str, GraphInputBinding] = {}
        for argument in call.keywords:
            if not argument.arg or argument.arg == "context":
                continue
            input_name = _canonical_input_name(definition, argument.arg)
            if isinstance(argument.value, ast.Name) and argument.value.id in variable_sources:
                inputs[input_name] = GraphInputBinding(mode="link", source_node=variable_sources[argument.value.id])
                continue
            try:
                inputs[input_name] = GraphInputBinding(literal=ast.literal_eval(argument.value))
            except Exception:
                diagnostics.append(_diagnostic("error", "dynamic_input", f"{_friendly_name(input_name)} must be a literal or another node's output.", node_id=node_id, line=getattr(argument.value, "lineno", statement.lineno)))
        output_name = (definition.output_name if definition else "result") if target_name else ""
        node = EngineGraphNode(
            node_id=node_id,
            operation=operation,
            display_name=definition.display_name if definition else _friendly_name(operation),
            inputs=inputs,
            output_name=output_name,
            position=previous_layout.get(node_id, (float(len(nodes) * 240), 0.0)),
        )
        nodes.append(node)
        if target_name:
            variable_sources[target_name] = node_id
    program = EngineGraphProgram(
        program_id=metadata.get("program_id") or (previous.program_id if previous else function.name),
        display_name=(previous.display_name if previous else _friendly_name(function.name)),
        entry_event=metadata.get("entry_event") or (previous.entry_event if previous else "On Begin Play"),
        nodes=nodes,
        flow=[node.node_id for node in nodes],
        description=previous.description if previous else "",
        version=previous.version if previous else 1,
    )
    diagnostics.extend(validate_engine_graph_program(program))
    return GraphCodeSyncResult(not any(item["severity"] == "error" for item in diagnostics), program, diagnostics)


def compile_engine_graph_manifest(program: EngineGraphProgram) -> dict[str, Any]:
    diagnostics = validate_engine_graph_program(program)
    is_valid = not any(item["severity"] == "error" for item in diagnostics)
    ordered = _ordered_nodes(program) if is_valid else []
    return {
        "schema": "tech_connector.native_graph_manifest.v1",
        "program_id": program.program_id,
        "display_name": program.display_name,
        "entry_event": program.entry_event,
        "backend": "tc_native_runtime",
        "abi": "tc_graph_c_v1",
        "valid": is_valid,
        "execution_order": [node.node_id for node in ordered],
        "nodes": [node.to_dict() for node in ordered],
        "operation_contracts": {
            node.node_id: _native_operation_contract(node.operation) for node in ordered
        },
        "diagnostics": diagnostics,
    }


def attach_engine_graph_program(scene: Any, program: EngineGraphProgram, source_code: str = "") -> dict[str, Any]:
    """Store one canonical graph program and its synchronized code in a TC scene."""

    metadata = scene.setdefault("metadata", {}) if isinstance(scene, dict) else getattr(scene, "metadata", None)
    if not isinstance(metadata, dict):
        raise TypeError("Scene document must expose mutable metadata.")
    programs = metadata.setdefault("engine_graph_programs", {})
    entry = {
        "program": program.to_dict(),
        "source_code": source_code or generate_engine_graph_python(program),
        "native_manifest": compile_engine_graph_manifest(program),
    }
    programs[program.program_id] = entry
    return entry


def engine_graph_programs_from_scene(scene: Any) -> dict[str, EngineGraphProgram]:
    metadata = scene.get("metadata", {}) if isinstance(scene, dict) else getattr(scene, "metadata", {})
    entries = metadata.get("engine_graph_programs", {}) if isinstance(metadata, dict) else {}
    return {
        str(program_id): EngineGraphProgram.from_dict(dict(entry.get("program") or {}))
        for program_id, entry in dict(entries).items()
        if isinstance(entry, dict) and isinstance(entry.get("program"), dict)
    }


def _ordered_nodes(program: EngineGraphProgram) -> list[EngineGraphNode]:
    lookup = {node.node_id: node for node in program.nodes}
    preferred = [node_id for node_id in program.flow if node_id in lookup]
    preferred.extend(
        node.node_id for node in program.nodes if node.node_id not in preferred
    )
    preferred_index = {node_id: index for index, node_id in enumerate(preferred)}

    outgoing: dict[str, set[str]] = {node_id: set() for node_id in lookup}
    incoming_count = {node_id: 0 for node_id in lookup}
    for node in lookup.values():
        for binding in node.inputs.values():
            source = binding.source_node
            if binding.mode != "link" or source not in lookup:
                continue
            if source == node.node_id:
                continue
            outgoing.setdefault(source, set()).add(node.node_id)
            incoming_count[node.node_id] += 1

    queue: list[str] = [node_id for node_id, count in incoming_count.items() if count == 0]
    queue.sort(key=preferred_index.get)
    ordered_nodes: list[EngineGraphNode] = []
    emitted: set[str] = set()

    while queue:
        node_id = queue.pop(0)
        if node_id in emitted:
            continue
        emitted.add(node_id)
        node = lookup[node_id]
        ordered_nodes.append(node)
        for child in sorted(outgoing.get(node_id, set()), key=preferred_index.get):
            incoming_count[child] -= 1
            if incoming_count[child] == 0:
                queue.append(child)
        queue.sort(key=preferred_index.get)

    ordered_nodes.extend(lookup[node_id] for node_id in preferred if node_id not in emitted)
    return ordered_nodes


def _has_data_cycle(program: EngineGraphProgram) -> bool:
    lookup = {node.node_id: node for node in program.nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for binding in lookup[node_id].inputs.values():
            if binding.mode == "link" and binding.source_node in lookup and visit(binding.source_node):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in lookup if node_id not in visited)


def _comments_by_line(code: str) -> dict[int, str]:
    try:
        return {token.start[0]: token.string.lstrip("#").strip() for token in tokenize.generate_tokens(StringIO(code).readline) if token.type == tokenize.COMMENT}
    except (IndentationError, tokenize.TokenError):
        return {}


def _program_metadata(comments: dict[int, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for text in comments.values():
        if text.startswith("tc-program:"):
            result["program_id"] = text.partition(":")[2].strip()
        elif text.startswith("tc-entry-event:"):
            result["entry_event"] = text.partition(":")[2].strip()
    return result


def _node_id_for_line(comments: dict[int, str], line: int) -> str:
    for candidate in range(line - 1, max(0, line - 4), -1):
        text = comments.get(candidate, "")
        if text.startswith("tc-node:"):
            return text.partition(":")[2].strip()
        if text and not text.startswith("tc-"):
            continue
    return ""


def _is_graph_call(call: ast.Call | None) -> bool:
    if call is None:
        return False
    return isinstance(call.func, ast.Name) and call.func.id == "graph_call"


def _literal(value: ast.AST) -> Any:
    try:
        return ast.literal_eval(value)
    except Exception:
        return None


def _unique_variable(node_id: str, used: set[str]) -> str:
    base = f"{_identifier(node_id, 'node')}_result"
    value = base
    index = 2
    while value in used:
        value = f"{base}_{index}"
        index += 1
    return value


def _diagnostic(severity: str, code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **{key: value for key, value in location.items() if value}}


def _native_operation_contract(operation: str) -> dict[str, Any]:
    definition = graph_operation_definition(operation)
    if definition is None:
        return {"operation": operation, "execution": "unresolved", "authorities": []}
    return {
        "operation": definition.operation,
        "execution": definition.execution,
        "authorities": list(definition.authorities),
        "required_capabilities": list(definition.required_capabilities),
        "input_types": {item.key: item.value_type for item in definition.inputs},
        "output_type": definition.output_type,
    }


def _canonical_input_name(
    definition: GraphOperationDefinition | None,
    input_name: str,
) -> str:
    if definition is None:
        return str(input_name)
    candidate = str(input_name).casefold()
    for item in definition.inputs:
        aliases = {alias.casefold() for alias in item.aliases}
        if candidate == item.key.casefold() or candidate in aliases:
            return item.key
    return str(input_name)


def _validate_node_inputs(node: EngineGraphNode) -> list[dict[str, Any]]:
    definition = graph_operation_definition(node.operation)
    if definition is None:
        return []
    diagnostics: list[dict[str, Any]] = []
    specs = {item.key: item for item in definition.inputs}
    for input_name in sorted(set(node.inputs) - set(specs)):
        diagnostics.append(
            _diagnostic(
                "error",
                "unknown_input",
                f"{definition.display_name} has no property named '{input_name}'.",
                node_id=node.node_id,
            )
        )
    for spec in definition.inputs:
        binding = node.inputs.get(spec.key)
        if binding is None:
            if spec.required:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "required_input_missing",
                        f"{spec.display_name} needs a value or connection.",
                        node_id=node.node_id,
                    )
                )
            continue
        if binding.mode == "link":
            continue
        issue = _literal_property_issue(spec, binding.literal)
        if issue:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "invalid_property_value",
                    issue,
                    node_id=node.node_id,
                )
            )
    return diagnostics


def _literal_property_issue(
    spec: GraphPropertyDefinition,
    value: Any,
) -> str:
    value_type = spec.value_type.casefold()
    if value_type in {"float", "number", "int"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{spec.display_name} must be a number."
        numeric = float(value)
        if not math.isfinite(numeric):
            return f"{spec.display_name} must be finite."
        units = f" {spec.units}" if spec.units else ""
        if spec.minimum is not None and numeric < spec.minimum:
            return f"{spec.display_name} must be at least {spec.minimum:g}{units}."
        if spec.maximum is not None and numeric > spec.maximum:
            return f"{spec.display_name} must be no more than {spec.maximum:g}{units}."
    elif value_type in {"str", "string", "entity"} and not isinstance(value, str):
        return f"{spec.display_name} must be text."
    elif value_type == "dict" and not isinstance(value, dict):
        return f"{spec.display_name} must contain named values."
    elif value_type.startswith("vector"):
        try:
            size = int(value_type.removeprefix("vector"))
        except ValueError:
            size = 0
        if not isinstance(value, (list, tuple)) or len(value) != size:
            return f"{spec.display_name} must contain exactly {size} numeric values."
        invalid = any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in value
        )
        if invalid:
            return f"{spec.display_name} must contain only finite numbers."
    return ""


def _types_compatible(produced: str, accepted: str) -> bool:
    source = str(produced or "Any").casefold()
    target = str(accepted or "Any").casefold()
    if "any" in {source, target} or source == target:
        return True
    numeric = {"int", "float", "number"}
    return source in numeric and target in numeric


def _list_words(values: Iterable[str]) -> str:
    labels = [_friendly_name(value) for value in values]
    if len(labels) < 2:
        return labels[0] if labels else "the required capability"
    return ", ".join(labels[:-1]) + f" or {labels[-1]}"


def _action_search_score(definition: GraphOperationDefinition, terms: list[str], available: bool) -> int:
    score = 100 if available else 0
    name = definition.display_name.casefold()
    operation = definition.operation.casefold()
    for term in terms:
        if name.startswith(term):
            score += 40
        elif term in name:
            score += 24
        elif term in operation:
            score += 12
        else:
            score += 4
    return score


def _property(key: str, display_name: str, description: str, value_type: str = "Any", default: Any = None, **kwargs: Any) -> GraphPropertyDefinition:
    return GraphPropertyDefinition(key, display_name, description, value_type, default, **kwargs)


for _definition in (
    GraphOperationDefinition(
        "input.read_axis", "Read Movement Input", "Read a named movement input using the current input mapping.", "Input",
        (_property("axis", "Input Action", "The player-facing action name to read.", "str", "Move"),), "value", "Vector2",
        graph_kinds=("gameplay", "input"), owner_types=("Actor", "Character", "Pawn", "Player Controller"),
        required_capabilities=("input",), keywords=("controls", "player", "axis"),
    ),
    GraphOperationDefinition(
        "movement.calculate_velocity", "Calculate Movement", "Turn directional input into a world-space movement velocity.", "Movement",
        (
            _property("direction", "Direction", "Movement direction supplied by input, AI, or another graph node.", "Vector2", required=True),
            _property("speed", "Movement Speed", "Maximum movement speed under normal conditions.", "float", 6.0, units="m/s", minimum=0.0, aliases=("max_speed",)),
            _property("acceleration", "Acceleration", "How quickly the character reaches the requested speed.", "float", 24.0, units="m/s^2", minimum=0.0, aliases=("accel",)),
            _property("target", "Movement Actor", "The actor whose current velocity is used for acceleration.", "Entity", "Self", aliases=("actor", "owner")),
        ), "velocity", "Vector3",
        graph_kinds=("gameplay", "animation"), owner_types=("Actor", "Character", "Pawn"),
        required_capabilities=("movement",), keywords=("move", "locomotion", "speed"),
    ),
    GraphOperationDefinition(
        "actor.set_velocity", "Set Actor Movement", "Apply a velocity to an actor through the active movement system.", "Actor",
        (
            _property("target", "Actor", "The actor whose movement should change.", "Entity", "Self", aliases=("actor", "owner")),
            _property("velocity", "Velocity", "The new world-space movement velocity.", "Vector3", required=True),
        ), "", "None",
        graph_kinds=("gameplay", "animation"), owner_types=("Actor", "Character", "Pawn"),
        selection_types=("Actor", "Character", "Pawn"), required_capabilities=("movement",),
        authorities=("local", "owner", "server"), keywords=("move", "velocity", "actor"),
    ),
    GraphOperationDefinition(
        "event.emit", "Send Gameplay Event", "Send a named gameplay event with an optional payload.", "Events",
        (
            _property("event", "Event", "The readable gameplay event name to send.", "str", required=True, aliases=("event_name", "name")),
            _property("payload", "Event Details", "Optional structured information carried by the event.", "dict", {}),
        ), "", "None",
        graph_kinds=("gameplay", "world_ai", "ui", "effects", "animation"),
        required_capabilities=("events",), keywords=("dispatch", "broadcast", "message", "signal"),
    ),
    GraphOperationDefinition(
        "variable.set", "Set Variable", "Store a named runtime value for later graph operations.", "Variables",
        (_property("name", "Variable", "Readable variable name.", "str", required=True), _property("value", "Value", "Value to store.", "Any")),
        "value", "Any", graph_kinds=("gameplay", "ui", "world_ai"), required_capabilities=("variables",), keywords=("state", "property", "write"),
    ),
    GraphOperationDefinition(
        "variable.add", "Add To Variable", "Increase a named numeric runtime value.", "Variables",
        (_property("name", "Variable", "Numeric variable to change.", "str", required=True), _property("amount", "Amount", "Amount to add.", "float", 1.0)),
        "value", "float", graph_kinds=("gameplay", "ui", "world_ai"), required_capabilities=("variables",), keywords=("increment", "counter", "score"),
    ),
    GraphOperationDefinition(
        "branch.greater", "Branch If Greater", "Test a variable and emit the true event when it exceeds a threshold.", "Flow",
        (
            _property("name", "Variable", "Numeric variable to test.", "str", required=True),
            _property("threshold", "Threshold", "Value the variable must exceed.", "float", 0.0),
            _property("event", "True Event", "Optional event emitted when the test succeeds.", "str", ""),
        ), "result", "bool", graph_kinds=("gameplay", "ui", "world_ai"), keywords=("if", "condition", "compare"),
    ),
    GraphOperationDefinition(
        "entity.spawn", "Spawn Entity", "Create a runtime entity at a world position.", "World",
        (
            _property("name", "Entity Name", "Stable name for the new entity.", "str", required=True),
            _property("x", "X", "World X position.", "float", 0.0), _property("y", "Y", "World Y position.", "float", 0.0),
            _property("z", "Z", "World Z position.", "float", 0.0),
        ), "entity", "Entity", graph_kinds=("gameplay", "world_ai"), required_capabilities=("world",), keywords=("create", "actor", "instance"),
    ),
    GraphOperationDefinition(
        "component.get_position", "Get World Position", "Read an entity's Transform position.", "Components",
        (_property("target", "Entity", "Entity whose Transform is read.", "Entity", "Self"),),
        "position", "Vector3", graph_kinds=("gameplay", "animation", "world_ai"), keywords=("transform", "component", "location"),
    ),
    GraphOperationDefinition(
        "component.set_position", "Set World Position", "Set an entity's Transform position.", "Components",
        (
            _property("target", "Entity", "Entity whose Transform is changed.", "Entity", "Self"),
            _property("x", "X", "World X position.", "float", 0.0), _property("y", "Y", "World Y position.", "float", 0.0),
            _property("z", "Z", "World Z position.", "float", 0.0),
        ), "", "None", graph_kinds=("gameplay", "animation", "world_ai"), keywords=("transform", "component", "location", "teleport"),
    ),
    GraphOperationDefinition(
        "ui.set_text", "Set Runtime Text", "Change the player-facing runtime HUD text.", "User Interface",
        (_property("text", "Text", "Text shown to the player.", "str", required=True),),
        "text", "str", graph_kinds=("gameplay", "ui"), required_capabilities=("runtime_ui",), keywords=("hud", "label", "message"),
    ),
    GraphOperationDefinition(
        "audio.play", "Play Audio", "Play a runtime audio asset without blocking gameplay.", "Audio",
        (_property("asset", "Audio Asset", "WAV asset path or stable audio asset ID.", "str", required=True),),
        "", "None", graph_kinds=("gameplay", "ui", "world_ai"), required_capabilities=("audio",), keywords=("sound", "music", "sfx"),
    ),
    GraphOperationDefinition(
        "save.write", "Save Game", "Write runtime variables and entity transforms to the active save slot.", "Persistence",
        (), "", "None", graph_kinds=("gameplay", "ui"), required_capabilities=("save_game",), keywords=("checkpoint", "persist", "slot"),
    ),
):
    register_graph_operation(_definition)


__all__ = [
    "ENGINE_GRAPH_SCHEMA", "EngineGraphNode", "EngineGraphProgram", "GraphAuthoringContext", "GraphCodeSyncResult", "GraphInputBinding",
    "GraphOperationDefinition", "GraphPropertyDefinition", "attach_engine_graph_program", "available_graph_operations",
    "compile_engine_graph_manifest", "engine_graph_programs_from_scene",
    "find_graph_actions", "generate_engine_graph_python", "graph_action_availability", "graph_node_controls",
    "graph_operation_definition", "parse_engine_graph_python",
    "register_graph_operation", "unregister_graph_operation",
    "validate_engine_graph_program",
]
