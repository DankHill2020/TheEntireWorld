from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class UtilityNodeDefinition:
    kind: str
    name: str
    category: str
    params: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    return_annotation: str = "Any"
    description: str = ""
    dynamic: bool = False

    def create_step_data(self) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        symbol = {
            "name": self.name,
            "kind": "utility",
            "host": "utility",
            "package": "Utility",
            "source_kind": "utility",
            "utility_kind": self.kind,
            "params": [dict(p) for p in self.params],
            "outputs": [dict(o) for o in self.outputs],
            "return_annotation": self.return_annotation,
            "description": self.description,
            "dynamic": self.dynamic,
        }
        step_data = {
            "symbol": symbol,
            "literal_values": default_literals_for(symbol),
            "dynamic_ports": {},
        }
        return step_data, symbol["params"], symbol["outputs"]


def _p(name: str, annotation: str = "Any", default: Any = "", semantic_type: str = "") -> dict[str, Any]:
    return {"name": name, "annotation": annotation, "python_type": annotation, "default": default, "semantic_type": semantic_type}


def _o(name: str, annotation: str = "Any", semantic_type: str = "") -> dict[str, Any]:
    return {"name": name, "annotation": annotation, "python_type": annotation, "semantic_type": semantic_type}


UTILITY_NODE_REGISTRY: dict[str, UtilityNodeDefinition] = {
    "dict_key": UtilityNodeDefinition(
        kind="dict_key",
        name="Get Dict Key",
        category="Dictionaries",
        params=[_p("source", "dict"), _p("key", "str", ""), _p("default", "Any", None)],
        outputs=[_o("value", "Any")],
        return_annotation="Any",
        description="Read one key from a dictionary. Connected inputs override literal values.",
    ),
    "set_dict_key": UtilityNodeDefinition(
        kind="set_dict_key",
        name="Set Dict Key",
        category="Dictionaries",
        params=[_p("source", "dict"), _p("key", "str", ""), _p("value", "Any")],
        outputs=[_o("dict", "dict")],
        return_annotation="dict",
        description="Copy a dictionary and set one key/value pair.",
    ),
    "make_dict": UtilityNodeDefinition(
        kind="make_dict",
        name="Make Dict",
        category="Dictionaries",
        params=[_p("key_1", "str", ""), _p("value_1", "Any")],
        outputs=[_o("dict", "dict")],
        return_annotation="dict",
        description="Build a dictionary from dynamic key/value input pairs.",
        dynamic=True,
    ),
    "merge_dicts": UtilityNodeDefinition(
        kind="merge_dicts",
        name="Merge Dicts",
        category="Dictionaries",
        params=[_p("a", "dict"), _p("b", "dict")],
        outputs=[_o("dict", "dict")],
        return_annotation="dict",
        description="Merge two dictionaries. Values from b override a.",
    ),
    "list_item": UtilityNodeDefinition(
        kind="list_item",
        name="Get List Item",
        category="Lists",
        params=[_p("source", "list"), _p("index", "int", 0)],
        outputs=[_o("item", "Any")],
        return_annotation="Any",
        description="Read one item from a list. If index is not connected, use the literal index on the node.",
    ),

    "split_list_items": UtilityNodeDefinition(
        kind="split_list_items",
        name="Split List Items",
        category="Lists",
        params=[_p("source", "list")],
        outputs=[_o("item_0", "Any"), _o("item_1", "Any")],
        return_annotation="list",
        description="Split a connected list or tuple into separate output ports. Ports can auto-expand from connected tuple/list metadata or be added manually.",
        dynamic=True,
    ),
    "make_list": UtilityNodeDefinition(
        kind="make_list",
        name="Make List",
        category="Lists",
        params=[_p("item_1", "Any")],
        outputs=[_o("list", "list")],
        return_annotation="list",
        description="Build a list from dynamic item inputs.",
        dynamic=True,
    ),
    "append_to_list": UtilityNodeDefinition(
        kind="append_to_list",
        name="Append To List",
        category="Lists",
        params=[_p("source", "list"), _p("item", "Any")],
        outputs=[_o("list", "list")],
        return_annotation="list",
        description="Copy a list and append an item.",
    ),
    "string_format": UtilityNodeDefinition(
        kind="string_format",
        name="String Format",
        category="Strings",
        params=[_p("template", "str", "{value}"), _p("value", "Any")],
        outputs=[_o("text", "str")],
        return_annotation="str",
        description="Format a string template using a value.",
    ),
    "path_join": UtilityNodeDefinition(
        kind="path_join",
        name="Path Join",
        category="Filesystem",
        params=[_p("base", "Path", ""), _p("child", "str", "")],
        outputs=[_o("path", "Path", "filesystem.path")],
        return_annotation="Path",
        description="Join a base path and child path.",
    ),
    "constant": UtilityNodeDefinition(
        kind="constant",
        name="Constant Value",
        category="Values",
        params=[_p("value", "Any", "")],
        outputs=[_o("value", "Any")],
        return_annotation="Any",
        description="Create a literal value for the graph.",
    ),
}


def default_literals_for(symbol: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for p in symbol.get("params") or []:
        if "default" in p and p.get("default") not in {"", None}:
            values[p.get("name", "")] = p.get("default")
        elif p.get("name") == "index":
            values[p.get("name")] = 0
    return values


def utility_node_menu_items() -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for kind, definition in UTILITY_NODE_REGISTRY.items():
        grouped.setdefault(definition.category, []).append((kind, definition.name))
    return grouped


def create_utility_step_data(utility_kind: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    definition = UTILITY_NODE_REGISTRY.get(utility_kind)
    if not definition:
        raise ValueError(f"Unknown utility node kind: {utility_kind}")
    return definition.create_step_data()


def add_dynamic_port(step_data: dict[str, Any]) -> bool:
    symbol = step_data.get("symbol") or {}
    kind = symbol.get("utility_kind")
    params = symbol.setdefault("params", [])
    if kind == "make_dict":
        next_idx = 1
        while any(p.get("name") == f"key_{next_idx}" for p in params):
            next_idx += 1
        params.extend([_p(f"key_{next_idx}", "str", ""), _p(f"value_{next_idx}", "Any")])
        return True
    if kind == "make_list":
        next_idx = 1
        while any(p.get("name") == f"item_{next_idx}" for p in params):
            next_idx += 1
        params.append(_p(f"item_{next_idx}", "Any"))
        return True
    if kind == "split_list_items":
        outputs = symbol.setdefault("outputs", [])
        next_idx = 0
        while any(o.get("name") == f"item_{next_idx}" for o in outputs):
            next_idx += 1
        outputs.append(_o(f"item_{next_idx}", "Any"))
        return True
    return False


def remove_last_dynamic_port(step_data: dict[str, Any]) -> bool:
    symbol = step_data.get("symbol") or {}
    kind = symbol.get("utility_kind")
    params = symbol.setdefault("params", [])
    if kind == "make_dict":
        key_params = [p for p in params if str(p.get("name", "")).startswith("key_")]
        if len(key_params) <= 1:
            return False
        max_idx = max(int(p["name"].split("_", 1)[1]) for p in key_params if p.get("name", "").split("_", 1)[1].isdigit())
        params[:] = [p for p in params if p.get("name") not in {f"key_{max_idx}", f"value_{max_idx}"}]
        return True
    if kind == "make_list":
        item_params = [p for p in params if str(p.get("name", "")).startswith("item_")]
        if len(item_params) <= 1:
            return False
        max_idx = max(int(p["name"].split("_", 1)[1]) for p in item_params if p.get("name", "").split("_", 1)[1].isdigit())
        params[:] = [p for p in params if p.get("name") != f"item_{max_idx}"]
        return True
    if kind == "split_list_items":
        outputs = symbol.setdefault("outputs", [])
        item_outputs = [o for o in outputs if str(o.get("name", "")).startswith("item_")]
        if len(item_outputs) <= 1:
            return False
        max_idx = max(int(o["name"].split("_", 1)[1]) for o in item_outputs if o.get("name", "").split("_", 1)[1].isdigit())
        outputs[:] = [o for o in outputs if o.get("name") != f"item_{max_idx}"]
        return True
    return False


def utility_codegen(kind: str, idx: int, call_args_by_name: dict[str, str], param_names: list[str]) -> list[str]:
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
    if kind == "set_dict_key":
        return [
            f"        step{idx}_result = dict({call_args_by_name.get('source', '{}')} or {{}})",
            f"        step{idx}_result[{call_args_by_name.get('key', 'None')}] = {call_args_by_name.get('value', 'None')}",
            f"        step{idx}_outputs = {{'dict': step{idx}_result}}",
        ]
    if kind == "make_dict":
        lines = [f"        step{idx}_result = {{}}"]
        key_names = sorted([p for p in param_names if p.startswith("key_")], key=lambda n: int(n.split("_", 1)[1]) if n.split("_", 1)[1].isdigit() else 9999)
        for key_name in key_names:
            suffix = key_name.split("_", 1)[1]
            value_name = f"value_{suffix}"
            lines.append(f"        step{idx}_result[{call_args_by_name.get(key_name, 'None')}] = {call_args_by_name.get(value_name, 'None')}")
        lines.append(f"        step{idx}_outputs = {{'dict': step{idx}_result}}")
        return lines
    if kind == "merge_dicts":
        return [
            f"        step{idx}_result = dict({call_args_by_name.get('a', '{}')} or {{}})",
            f"        step{idx}_result.update({call_args_by_name.get('b', '{}')} or {{}})",
            f"        step{idx}_outputs = {{'dict': step{idx}_result}}",
        ]
    if kind == "list_item":
        return [
            f"        _source = {call_args_by_name.get('source', '[]')}",
            f"        _index = {call_args_by_name.get('index', '0')}",
            f"        step{idx}_result = _source[int(_index)]",
            f"        step{idx}_outputs = {{'item': step{idx}_result}}",
        ]
    if kind == "split_list_items":
        source = call_args_by_name.get("source", "[]")
        output_names = [name for name in param_names if name.startswith("item_")]
        # Older codegen passes param names only. For this output-dynamic node, fall back
        # to two outputs if the service has not supplied output names.
        if not output_names:
            output_names = ["item_0", "item_1"]
        lines = [
            f"        step{idx}_result = list({source} or [])",
            f"        step{idx}_outputs = {{}}",
        ]
        for name in output_names:
            try:
                item_index = int(name.split("_", 1)[1])
            except Exception:
                item_index = len(lines)
            lines.append(f"        step{idx}_outputs[{name!r}] = step{idx}_result[{item_index}] if len(step{idx}_result) > {item_index} else None")
        return lines
    if kind == "make_list":
        items = [call_args_by_name.get(name, "None") for name in param_names if name.startswith("item_")]
        return [
            f"        step{idx}_result = [{', '.join(items)}]",
            f"        step{idx}_outputs = {{'list': step{idx}_result}}",
        ]
    if kind == "append_to_list":
        return [
            f"        step{idx}_result = list({call_args_by_name.get('source', '[]')} or [])",
            f"        step{idx}_result.append({call_args_by_name.get('item', 'None')})",
            f"        step{idx}_outputs = {{'list': step{idx}_result}}",
        ]
    if kind == "string_format":
        return [
            f"        step{idx}_result = str({call_args_by_name.get('template', repr('{value}'))}).format(value={call_args_by_name.get('value', 'None')})",
            f"        step{idx}_outputs = {{'text': step{idx}_result}}",
        ]
    if kind == "path_join":
        return [
            "        from pathlib import Path",
            f"        step{idx}_result = Path({call_args_by_name.get('base', repr(''))}) / str({call_args_by_name.get('child', repr(''))})",
            f"        step{idx}_outputs = {{'path': step{idx}_result}}",
        ]
    if kind == "constant":
        return [
            f"        step{idx}_result = {call_args_by_name.get('value', 'None')}",
            f"        step{idx}_outputs = {{'value': step{idx}_result}}",
        ]
    raise RuntimeError(f"Unknown utility node kind: {kind}")
