from __future__ import annotations

import ast
import re
from typing import Any

GITHUB_INGEST_FUNCTION_SUFFIX = "_git_ingest"

def workflow_function_name(name: str, uses_github_ingest: bool = False) -> str:
    """Return a safe Python function name for saved/generated pipelines."""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(name or "workflow")).strip("_").lower()
    text = re.sub(r"_+", "_", text) or "workflow"
    if text[0].isdigit():
        text = f"workflow_{text}"
    text = text[:64]
    if uses_github_ingest and not text.endswith(GITHUB_INGEST_FUNCTION_SUFFIX):
        text = f"{text}{GITHUB_INGEST_FUNCTION_SUFFIX}"
    return text


try:
    from ui.pipeline_node_types import normalized_outputs as _typed_normalized_outputs
    from ui.pipeline_utility_nodes import utility_codegen as _utility_codegen
except Exception:
    _typed_normalized_outputs = None
    _utility_codegen = None


def _module_and_attr(symbol: dict[str, Any]) -> tuple[str, str]:
    name = symbol.get("name") or ""
    function_path = symbol.get("function_path") or symbol.get("module") or ""
    if function_path and "." in function_path:
        parts = function_path.split(".")
        return ".".join(parts[:-1]), parts[-1]
    file_path = (symbol.get("file_path") or "").replace("\\", "/")
    if file_path.endswith(".py"):
        parts = file_path.split("/")
        if "the_entire_world_ai_studio" in parts:
            parts = parts[parts.index("the_entire_world_ai_studio") + 1 :]
        module = ".".join(parts)[:-3].replace("/", ".")
        return module, name.split(".")[-1]
    if "." in name:
        parts = name.split(".")
        return ".".join(parts[:-1]), parts[-1]
    return "", name


def _literal_repr(value: Any) -> str:
    raw = "" if value is None else str(value)
    if raw == "":
        return "None"
    try:
        parsed = ast.literal_eval(raw)
        return repr(parsed)
    except Exception:
        return repr(raw)


def _param_names(symbol: dict[str, Any]) -> list[str]:
    return [p.get("name", "") for p in symbol.get("params", []) or [] if p.get("name") and not p.get("name", "").startswith("*")]


def _clean_type(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text.replace("typing.", "")


_NONE_RETURN_TYPES = {"None", "NoneType", "void", "NoReturn"}
_UNKNOWN_RETURN_TYPES = {"", "Any", "Unknown", "object"}


def _annotation_from_ast(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        return _clean_type(ast.unparse(annotation))
    except Exception:
        return ""


def _function_ast(symbol: dict[str, Any]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    source = symbol.get("source") or ""
    if not source:
        return None
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    target_name = symbol.get("name") or ""
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for node in functions:
        if node.name == target_name:
            return node
    return functions[0] if len(functions) == 1 else None


def _infer_expr_type(expr: ast.AST | None, assignments: dict[str, str] | None = None) -> str:
    assignments = assignments or {}
    if expr is None:
        return "None"
    if isinstance(expr, ast.Constant):
        if expr.value is None:
            return "None"
        return type(expr.value).__name__
    if isinstance(expr, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(expr, (ast.Tuple, ast.GeneratorExp)):
        return "tuple"
    if isinstance(expr, (ast.Dict, ast.DictComp)):
        return "dict"
    if isinstance(expr, (ast.Set, ast.SetComp)):
        return "set"
    if isinstance(expr, ast.Name):
        return assignments.get(expr.id, "Unknown")
    if isinstance(expr, ast.Call):
        func = expr.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        if func_name in {"list", "sorted", "range"} or func_name.startswith("list") or func_name.endswith("s"):
            return "list"
        if func_name == "dict":
            return "dict"
        if func_name == "set":
            return "set"
        if func_name == "tuple":
            return "tuple"
    return "Unknown"


def _infer_symbol_return_type(symbol: dict[str, Any]) -> str:
    if symbol.get("utility_kind"):
        return _clean_type(symbol.get("return_annotation") or "Unknown") or "Unknown"
    for key in ("return_annotation", "returns"):
        ret = _clean_type(symbol.get(key) or "")
        if ret:
            return ret
    fn = _function_ast(symbol)
    if fn is None:
        return "Unknown"
    annotated = _annotation_from_ast(getattr(fn, "returns", None))
    if annotated:
        return annotated
    assignments: dict[str, str] = {}
    returns: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            inferred = _infer_expr_type(node.value, assignments)
            if inferred and inferred not in _UNKNOWN_RETURN_TYPES:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = inferred
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ann = _annotation_from_ast(node.annotation)
            if ann:
                assignments[node.target.id] = ann
            else:
                inferred = _infer_expr_type(node.value, assignments)
                if inferred and inferred not in _UNKNOWN_RETURN_TYPES:
                    assignments[node.target.id] = inferred
        elif isinstance(node, ast.Return):
            returns.append(_infer_expr_type(node.value, assignments))
    if not returns:
        return "None"
    non_none = [r for r in returns if r not in _NONE_RETURN_TYPES]
    if not non_none:
        return "None"
    known = [r for r in non_none if r not in _UNKNOWN_RETURN_TYPES]
    return known[0] if known else "Unknown"


def _has_data_return(symbol: dict[str, Any]) -> bool:
    if symbol.get("utility_kind"):
        return True
    inferred = _infer_symbol_return_type(symbol)
    if inferred in _NONE_RETURN_TYPES:
        return False
    outputs = symbol.get("outputs") or []
    if outputs:
        for out in outputs:
            anno = _clean_type((out or {}).get("annotation") or (out or {}).get("type") or "")
            name = _clean_type((out or {}).get("name") or "").lower()
            if name not in {"none", "void"} and anno not in _NONE_RETURN_TYPES:
                return True
        return False
    return True


def _output_names(symbol: dict[str, Any]) -> list[str]:
    if _typed_normalized_outputs is not None:
        try:
            return [o.get("name", "") for o in _typed_normalized_outputs(symbol, symbol.get("outputs") or []) if o.get("name")]
        except Exception:
            pass
    if not _has_data_return(symbol):
        return []
    outputs = symbol.get("outputs") or []
    names = [o.get("name", "") for o in outputs if isinstance(o, dict) and o.get("name")]
    return names or ["result"]


def _graph_order(view, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if view and hasattr(view, "ordered_step_data"):
        try:
            ordered = view.ordered_step_data()
            if ordered:
                return ordered
        except Exception:
            pass
    return steps


def _graph_data_links(view) -> list[dict[str, str]]:
    if view and hasattr(view, "manifest_data_links"):
        try:
            return view.manifest_data_links()
        except Exception:
            return []
    if view and hasattr(view, "manifest_links"):
        try:
            return view.manifest_links()
        except Exception:
            return []
    return []


def _graph_flow_links(view) -> list[dict[str, str]]:
    if view and hasattr(view, "manifest_flow_links"):
        try:
            return view.manifest_flow_links()
        except Exception:
            return []
    return []


def _link_map_for_order(links: list[dict[str, str]]) -> dict[tuple[int, str], tuple[int, str]]:
    result = {}
    pattern = re.compile(r"step(\d+)\.([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])*)")
    for link in links or []:
        sm = pattern.match(link.get("from", ""))
        dm = pattern.match(link.get("to", ""))
        if sm and dm:
            result[(int(dm.group(1)), dm.group(2))] = (int(sm.group(1)), sm.group(2))
    return result


def _safe_identifier(name: str, fallback: str) -> str:
    name = re.sub(r"\W+", "_", name or "").strip("_")
    if not name or not name.isidentifier():
        return fallback
    return name


def _output_expr(source_step: int, source_output: str) -> str:
    # Supports Get Dict Key / nested selector references like result['foo'] later.
    if "[" in source_output:
        base, selector = source_output.split("[", 1)
        return f"outputs['step{source_step}'].get({base!r}, results.get('step{source_step}'))[{selector}"
    return f"outputs['step{source_step}'][{source_output!r}]"


def _utility_call_lines(idx: int, symbol: dict[str, Any], call_args_by_name: dict[str, str], param_names: list[str] | None = None) -> list[str]:
    kind = symbol.get("utility_kind")
    param_names = param_names or _param_names(symbol)
    if _utility_codegen is not None:
        try:
            return _utility_codegen(kind, idx, call_args_by_name, param_names)
        except Exception:
            pass
    if kind == "dict_key":
        source = call_args_by_name.get("source", "None")
        key = call_args_by_name.get("key", "None")
        default = call_args_by_name.get("default", "None")
        return [
            f"        _source = {source}",
            f"        _key = {key}",
            f"        _default = {default}",
            f"        step{idx}_result = _source.get(_key, _default) if hasattr(_source, 'get') else _source[_key]",
            f"        step{idx}_outputs = {{'value': step{idx}_result}}",
        ]
    if kind == "list_item":
        source = call_args_by_name.get("source", "None")
        index = call_args_by_name.get("index", "0")
        return [
            f"        _source = {source}",
            f"        _index = {index}",
            f"        step{idx}_result = _source[int(_index)]",
            f"        step{idx}_outputs = {{'item': step{idx}_result}}",
        ]
    if kind == "make_dict":
        lines = [f"        step{idx}_result = {{}}"]
        for key_name in sorted([p for p in param_names if p.startswith('key_')], key=lambda n: int(n.split('_', 1)[1]) if n.split('_', 1)[1].isdigit() else 9999):
            suffix = key_name.split('_', 1)[1]
            lines.append(f"        step{idx}_result[{call_args_by_name.get(key_name, 'None')}] = {call_args_by_name.get('value_' + suffix, 'None')}")
        lines.append(f"        step{idx}_outputs = {{'dict': step{idx}_result}}")
        return lines
    raise RuntimeError(f"Unknown utility node kind: {kind}")


def generate_pipeline_code_from_graph(name: str, goal: str, steps: list[dict[str, Any]], view=None) -> str:
    ordered_steps = _graph_order(view, steps)
    data_links = _graph_data_links(view)
    flow_links = _graph_flow_links(view)
    link_map = _link_map_for_order(data_links)
    uses_github = any(
        "github" in str((s.get("symbol") or {}).get("name", "")).lower()
        or "github" in str((s.get("symbol") or {}).get("file_path", "")).lower()
        for s in ordered_steps
    )
    fn_name = workflow_function_name(name, uses_github_ingest=uses_github)

    function_params = []
    step_param_names = {}
    for idx, step in enumerate(ordered_steps, start=1):
        symbol = step.get("symbol") or {}
        linked_inputs = {target_input for (target_step, target_input), _src in link_map.items() if target_step == idx}
        literal_values = step.get("literal_values") or {}
        for param_name in _param_names(symbol):
            if param_name in linked_inputs:
                continue
            if param_name in literal_values and str(literal_values.get(param_name, "")) != "":
                continue
            arg_name = f"step{idx}_{param_name}"
            step_param_names[(idx, param_name)] = arg_name
            function_params.append(f"{arg_name}=None")

    lines = [
        '"""Generated pipeline.',
        f"Goal: {goal}",
        "",
        "Flow edges control execution order only.",
        "Data edges bind return/output values into downstream function arguments.",
        '"""',
        "",
        "import importlib",
        "import traceback",
        "",
        f"def {fn_name}({', '.join(function_params)}):",
        "    results = {}",
        "    outputs = {}",
    ]
    if flow_links:
        lines.append(f"    flow_links = {flow_links!r}")
    if not ordered_steps:
        lines.append("    return results")
        return "\n".join(lines)

    for idx, step in enumerate(ordered_steps, start=1):
        symbol = step.get("symbol") or {}
        params = _param_names(symbol)
        output_names = _output_names(symbol)
        literal_values = step.get("literal_values") or {}
        utility_kind = symbol.get("utility_kind")

        lines += ["", f"    # Step {idx}: {symbol.get('name', 'unknown')} ({symbol.get('kind', 'function')})", "    try:"]
        call_args = []
        call_args_by_name = {}
        for param_name in params:
            linked = link_map.get((idx, param_name))
            if linked:
                source_step, source_output = linked
                expr = _output_expr(source_step, source_output)
            elif param_name in literal_values and str(literal_values.get(param_name, "")) != "":
                expr = _literal_repr(literal_values.get(param_name))
            else:
                expr = step_param_names.get((idx, param_name), f"step{idx}_{param_name}")
            call_args_by_name[param_name] = expr
            call_args.append(f"{param_name}={expr}")

        if utility_kind:
            lines.extend(_utility_call_lines(idx, symbol, call_args_by_name, params))
        else:
            file_path = (symbol.get("file_path") or "").replace("\\", "/")
            module, attr = _module_and_attr(symbol)
            is_absolute = False
            if file_path:
                import os
                is_absolute = os.path.isabs(file_path)
            
            if is_absolute:
                lines += [
                    "        import importlib.util",
                    f"        spec = importlib.util.spec_from_file_location('step{idx}_mod', {file_path!r})",
                    "        module = importlib.util.module_from_spec(spec)",
                    "        spec.loader.exec_module(module)",
                    f"        target = getattr(module, {attr!r})",
                ]
            elif module:
                lines += [
                    f"        module = importlib.import_module({module!r})",
                    "        importlib.reload(module)",
                    f"        target = getattr(module, {attr!r})",
                ]
            else:
                lines += [
                    f"        target = globals().get({attr!r})",
                    "        if target is None:",
                    f"            raise RuntimeError('Could not resolve local callable: {attr}')",
                ]
            lines.append(f"        step{idx}_result = target({', '.join(call_args)})")
            if not output_names:
                lines.append(f"        step{idx}_outputs = {{}}")
            elif len(output_names) == 1:
                lines.append(f"        step{idx}_outputs = {{{output_names[0]!r}: step{idx}_result}}")
            else:
                lines.append(f"        step{idx}_outputs = {{}}")
                lines.append(f"        if not isinstance(step{idx}_result, (tuple, list)):")
                lines.append(f"            raise RuntimeError('Step {idx} expected multiple outputs but returned a single value')")
                for out_index, out_name in enumerate(output_names):
                    safe_name = _safe_identifier(out_name, f"output_{out_index + 1}")
                    lines.append(f"        {safe_name} = step{idx}_result[{out_index}]")
                    lines.append(f"        step{idx}_outputs[{out_name!r}] = {safe_name}")
        lines += [
            f"        outputs['step{idx}'] = step{idx}_outputs",
            f"        results['step{idx}'] = step{idx}_result",
            "    except Exception as e:",
            f"        print(f'Step {idx} failed: {{e}}')",
            "        traceback.print_exc()",
            "        raise",
        ]
    lines += ["", f"    return results.get('step{len(ordered_steps)}')"]
    return "\n".join(lines)
