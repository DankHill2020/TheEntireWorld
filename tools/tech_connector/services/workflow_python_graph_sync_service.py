from __future__ import annotations

"""Parse generated Pipeline Python back into graph-editable nodes and plugs."""

import ast
from dataclasses import asdict, dataclass, field
from typing import Any

from tech_connector.services.workflow_service import extract_python_code


@dataclass
class ParsedPipelineGraph:
    ok: bool
    function_name: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    data_links: list[dict[str, Any]] = field(default_factory=list)
    flow_links: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_pipeline_python_to_graph(code: str) -> ParsedPipelineGraph:
    """Parse the reversible subset emitted by workflow_codegen_service.

    Supported shape:
    - one pipeline function
    - stepN_result = callable(...)
    - spec_from_file_location(..., "path.py") before the call
    - outputs['stepN'] = stepN_outputs
    - stepN_outputs = {'result': stepN_result} or stepN_outputs['name'] = value
    - call kwargs bound from outputs['stepX']['plug'] become data links
    - flow_links literal list becomes graph flow links
    """

    cleaned = extract_python_code(code)
    try:
        tree = ast.parse(cleaned or "")
    except SyntaxError as exc:
        return ParsedPipelineGraph(ok=False, diagnostics=[f"syntax_error:{exc.lineno}:{exc.msg}"])

    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    function = next((node for node in functions if not node.name.startswith("_")), None)
    if function is None:
        function = next(iter(functions), None)
    if function is None:
        return ParsedPipelineGraph(ok=False, diagnostics=["no pipeline function found"])

    step_modules: dict[int, str] = {}
    step_callables: dict[int, str] = {}
    step_params: dict[int, list[dict[str, Any]]] = {}
    step_outputs: dict[int, list[dict[str, Any]]] = {}
    step_symbols: dict[int, dict[str, Any]] = {}
    literal_values: dict[int, dict[str, Any]] = {}
    data_links: list[dict[str, Any]] = []
    flow_links = _literal_flow_links(function)
    operation_param_assignments = _operation_param_dict_assignments(function)

    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            _capture_spec_path(node, step_modules)
            _capture_getattr_alias(node, step_callables)
            _capture_output_names(node, step_outputs)
            _capture_step_call(
                node,
                step_callables,
                step_params,
                step_symbols,
                literal_values,
                data_links,
                operation_param_assignments,
            )

    steps: list[dict[str, Any]] = []
    for index in sorted(set(step_callables) | set(step_modules) | set(step_params) | set(step_outputs)):
        name = step_callables.get(index) or f"step{index}"
        params = step_params.get(index) or []
        outputs = step_outputs.get(index) or [{"name": "result", "annotation": "Any", "python_type": "Any"}]
        symbol = {
            "name": name,
            "kind": "function",
            "file_path": step_modules.get(index, ""),
            "params": params,
            "outputs": outputs,
            "public_tool": True,
            **step_symbols.get(index, {}),
        }
        symbol["params"] = params
        symbol["outputs"] = outputs
        steps.append(
            {
                "step_index": index,
                "symbol": symbol,
                "params": params,
                "outputs": outputs,
                "literal_values": literal_values.get(index, {}),
            }
        )

    return ParsedPipelineGraph(
        ok=bool(steps),
        function_name=function.name,
        steps=steps,
        data_links=data_links,
        flow_links=flow_links,
        diagnostics=[] if steps else ["no step calls found"],
    )


def _literal_flow_links(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    for stmt in function.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "flow_links" for target in stmt.targets):
            continue
        try:
            value = ast.literal_eval(stmt.value)
        except Exception:
            return []
        if isinstance(value, list):
            links: list[dict[str, Any]] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                from_step = _step_index_from_step_text(str(item.get("from") or item.get("from_step") or ""))
                to_step = _step_index_from_step_text(str(item.get("to") or item.get("to_step") or ""))
                if from_step and to_step:
                    links.append({"from_step": from_step, "to_step": to_step, "type": "flow"})
            return links
    return []


def _capture_spec_path(node: ast.Assign, step_modules: dict[int, str]) -> None:
    if not isinstance(node.value, ast.Call):
        return
    if not _is_attr_call(node.value.func, "spec_from_file_location"):
        return
    if len(node.value.args) < 2:
        return
    step = _step_index_from_expr(node.value.args[0])
    path = _literal_string(node.value.args[1])
    if step and path:
        step_modules[step] = path


def _capture_getattr_alias(node: ast.Assign, step_callables: dict[int, str]) -> None:
    if not isinstance(node.value, ast.Call):
        return
    if not isinstance(node.value.func, ast.Name) or node.value.func.id != "getattr":
        return
    if len(node.value.args) < 2:
        return
    name = _literal_string(node.value.args[1])
    if not name:
        return
    for target in node.targets:
        if isinstance(target, ast.Name) and target.id == "target":
            # Infer the step from the nearest spec path later if possible.
            continue
        if isinstance(target, ast.Name):
            step = _step_index_from_name(target.id)
            if step:
                step_callables[step] = name


def _capture_step_call(
    node: ast.Assign,
    step_callables: dict[int, str],
    step_params: dict[int, list[dict[str, Any]]],
    step_symbols: dict[int, dict[str, Any]],
    literal_values: dict[int, dict[str, Any]],
    data_links: list[dict[str, Any]],
    operation_param_assignments: list[tuple[int, ast.Dict]],
) -> None:
    step = 0
    for target in node.targets:
        if isinstance(target, ast.Name):
            step = _step_index_from_name(target.id)
            break
    if not step or not isinstance(node.value, ast.Call):
        return
    if not any(isinstance(target, ast.Name) and target.id == f"step{step}_result" for target in node.targets):
        return

    callable_name = _call_name(node.value.func)
    if callable_name == "execute_pipeline_operation":
        host = _literal_string(node.value.args[0]) if len(node.value.args) > 0 else ""
        operation = _literal_string(node.value.args[1]) if len(node.value.args) > 1 else ""
        function_path = _literal_string(node.value.args[2]) if len(node.value.args) > 2 else ""
        display_name = operation or function_path.rsplit(".", 1)[-1] or callable_name
        step_callables[step] = display_name
        step_symbols[step] = {
            "name": display_name,
            "kind": "function",
            "function_path": function_path,
            "module": function_path.rpartition(".")[0],
            "provider_id": host,
            "host": host,
            "operation": operation,
            "pipeline_operation": "dcc_operation",
            "runtime_dispatcher": "execute_pipeline_operation",
        }
        params_node = _nearest_operation_params(
            operation_param_assignments,
            getattr(node, "lineno", 0),
        )
        params, values = _params_and_links_from_dict(
            params_node,
            step,
            data_links,
        )
        step_params[step] = params
        if values:
            literal_values[step] = values
        return
    if callable_name and callable_name not in {"target"}:
        step_callables[step] = callable_name
    params: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    for keyword in node.value.keywords:
        if not keyword.arg:
            continue
        params.append({"name": keyword.arg, "annotation": "Any", "python_type": "Any"})
        link = _output_ref(keyword.value)
        if link:
            source_step, source_output = link
            data_links.append(
                {
                    "from_step": source_step,
                    "from_output": source_output,
                    "to_step": step,
                    "to_input": keyword.arg,
                    "type": "data",
                }
            )
        else:
            literal = _literal_value_or_name(keyword.value, external_prefix=f"step{step}_")
            if literal is not _UNSET:
                values[keyword.arg] = literal
    step_params[step] = params
    if values:
        literal_values[step] = values


def _operation_param_dict_assignments(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[int, ast.Dict]]:
    rows = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if any(
            isinstance(target, ast.Name)
            and (
                target.id == "_operation_params"
                or target.id.endswith("_operation_params")
            )
            for target in node.targets
        ):
            rows.append((getattr(node, "lineno", 0), node.value))
    return sorted(rows, key=lambda item: item[0])


def _nearest_operation_params(
    assignments: list[tuple[int, ast.Dict]],
    call_line: int,
) -> ast.Dict | None:
    candidates = [
        value
        for line, value in assignments
        if line and line < call_line
    ]
    return candidates[-1] if candidates else None


def _params_and_links_from_dict(
    value: ast.Dict | None,
    step: int,
    data_links: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = []
    literals = {}
    if value is None:
        return params, literals
    for key_node, value_node in zip(value.keys, value.values):
        name = _literal_string(key_node)
        if not name:
            continue
        params.append({"name": name, "annotation": "Any", "python_type": "Any"})
        link = _output_ref(value_node)
        if link:
            source_step, source_output = link
            data_links.append(
                {
                    "from_step": source_step,
                    "from_output": source_output,
                    "to_step": step,
                    "to_input": name,
                    "type": "data",
                }
            )
            continue
        literal = _literal_value_or_name(
            value_node,
            external_prefix=f"step{step}_",
        )
        if literal is not _UNSET:
            literals[name] = literal
    return params, literals


def _capture_output_names(node: ast.Assign, step_outputs: dict[int, list[dict[str, Any]]]) -> None:
    for target in node.targets:
        if isinstance(target, ast.Name):
            step = _step_index_from_name(target.id)
            if step and target.id == f"step{step}_outputs" and isinstance(node.value, ast.Dict):
                names = [_literal_string(key) for key in node.value.keys]
                filtered = [name for name in names if name]
                if filtered:
                    step_outputs[step] = [{"name": name, "annotation": "Any", "python_type": "Any"} for name in filtered]
        elif isinstance(target, ast.Subscript):
            parsed = _step_output_assignment(target)
            if parsed:
                step, name = parsed
                rows = step_outputs.setdefault(step, [])
                if name and name not in {row.get("name") for row in rows}:
                    rows.append({"name": name, "annotation": "Any", "python_type": "Any"})


def _step_output_assignment(target: ast.Subscript) -> tuple[int, str] | None:
    if not isinstance(target.value, ast.Name):
        return None
    step = _step_index_from_name(target.value.id)
    if not step:
        return None
    name = _literal_string(target.slice)
    return (step, name) if name else None


def _output_ref(value: ast.AST) -> tuple[int, str] | None:
    # outputs['step1']['body_joint_map']
    if not isinstance(value, ast.Subscript):
        return None
    output_name = _literal_string(value.slice)
    inner = value.value
    if not output_name or not isinstance(inner, ast.Subscript):
        return None
    if not isinstance(inner.value, ast.Name) or inner.value.id != "outputs":
        return None
    step_text = _literal_string(inner.slice)
    step = _step_index_from_step_text(step_text)
    return (step, output_name) if step else None


def _step_index_from_expr(value: ast.AST) -> int:
    return _step_index_from_step_text(_literal_string(value))


def _step_index_from_step_text(value: str) -> int:
    match = __import__("re").search(r"step(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def _step_index_from_name(value: str) -> int:
    return _step_index_from_step_text(value)


def _literal_string(value: ast.AST) -> str:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return ""


_UNSET = object()


def _literal_value_or_name(value: ast.AST, external_prefix: str = "") -> Any:
    try:
        return ast.literal_eval(value)
    except Exception:
        if isinstance(value, ast.Name):
            if external_prefix and value.id.startswith(external_prefix):
                return _UNSET
            return value.id
        return _UNSET


def _call_name(value: ast.AST) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _is_attr_call(value: ast.AST, attr: str) -> bool:
    return isinstance(value, ast.Attribute) and value.attr == attr
