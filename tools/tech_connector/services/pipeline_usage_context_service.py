"""Infer conservative pipeline bindings from real Python call sites.

This module never connects values solely because two annotations happen to
match.  A link is returned only when project code passes a value produced by
one selected callable into an argument of a later selected callable.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import time
from typing import Any


_SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "build", "dist",
    "node_modules", "external_tools", "Intermediate", "Saved",
    "DerivedDataCache", "workflows",
}


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _step_aliases(step: dict[str, Any]) -> set[str]:
    symbol = step.get("symbol") or {}
    values = {
        symbol.get("name"),
        symbol.get("qualified_name"),
        symbol.get("function_path"),
        symbol.get("module"),
        symbol.get("operation"),
    }
    aliases: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        aliases.add(text.casefold())
        aliases.add(text.rsplit(".", 1)[-1].casefold())
    return aliases


def _resolve_step_for_call(
    call: ast.Call,
    aliases: list[set[str]],
    import_aliases: dict[str, str] | None = None,
) -> int | None:
    name = _call_name(call.func).casefold()
    first, dot, rest = name.partition(".")
    imported = (import_aliases or {}).get(first)
    if imported:
        name = f"{imported}.{rest}" if dot else imported
    short = name.rsplit(".", 1)[-1]
    exact_matches = [
        index
        for index, names in enumerate(aliases, start=1)
        if name in names
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    short_matches = [
        index for index, names in enumerate(aliases, start=1) if short in names
    ]
    return short_matches[0] if len(short_matches) == 1 else None


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = str(item.asname or item.name.split(".", 1)[0]).casefold()
                aliases[local] = str(item.name).casefold()
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "").casefold()
            for item in node.names:
                if item.name == "*":
                    continue
                local = str(item.asname or item.name).casefold()
                aliases[local] = f"{module}.{item.name}".strip(".").casefold()
    return aliases


def _subscript_key(node: ast.Subscript) -> str:
    value = node.slice
    if isinstance(value, ast.Constant) and isinstance(value.value, (str, int)):
        return str(value.value)
    return ""


def _best_output(step: dict[str, Any], requested: str) -> str:
    outputs = list(step.get("outputs") or (step.get("symbol") or {}).get("outputs") or [])
    requested_n = _normalize(requested)
    for output in outputs:
        name = str(output.get("name") or "")
        if _normalize(name) == requested_n:
            return name
    for output in outputs:
        name = str(output.get("name") or "")
        output_n = _normalize(name)
        if requested_n and output_n and (
            requested_n in output_n or output_n in requested_n
        ):
            return name
    if len(outputs) == 1:
        return str(outputs[0].get("name") or "result")
    return ""


def _argument_bindings(
    value: ast.AST,
    assignments: dict[str, tuple[int, str, int]],
    aliases: list[set[str]],
    steps: list[dict[str, Any]],
    import_aliases: dict[str, str],
) -> tuple[int, str, int] | None:
    if isinstance(value, ast.Name):
        return assignments.get(value.id)
    if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
        source = assignments.get(value.value.id)
        if not source:
            return None
        output = _best_output(steps[source[0] - 1], _subscript_key(value))
        return (source[0], output, source[2]) if output else None
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        source = assignments.get(value.value.id)
        if not source:
            return None
        output = _best_output(steps[source[0] - 1], value.attr)
        return (source[0], output, source[2]) if output else None
    if isinstance(value, ast.Call):
        source_step = _resolve_step_for_call(value, aliases, import_aliases)
        if source_step is None:
            return None
        output = _best_output(steps[source_step - 1], "result")
        return (source_step, output, getattr(value, "lineno", 0)) if output else None
    return None


def _links_from_tree(
    tree: ast.AST,
    steps: list[dict[str, Any]],
    aliases: list[set[str]],
    path: Path,
) -> list[dict[str, Any]]:
    class _OwnedVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.nodes: list[ast.AST] = []

        def visit_FunctionDef(self, node):  # noqa: N802 - ast visitor API
            return

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

        def generic_visit(self, node):
            self.nodes.append(node)
            super().generic_visit(node)

    scopes: list[list[ast.stmt]] = []
    if isinstance(tree, ast.Module):
        scopes.append(list(tree.body))
    scopes.extend(
        list(node.body)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    all_links: list[dict[str, Any]] = []
    import_aliases = _import_aliases(tree)
    for body in scopes:
        visitor = _OwnedVisitor()
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            visitor.visit(statement)
        owned_nodes = visitor.nodes
        assignments: dict[str, tuple[int, str, int]] = {}
        calls = sorted(
            (node for node in owned_nodes if isinstance(node, ast.Call)),
            key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)),
        )
        assignment_by_call: dict[int, list[str]] = {}
        for node in owned_nodes:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            if names:
                assignment_by_call[id(node.value)] = names

        for call in calls:
            step_index = _resolve_step_for_call(call, aliases, import_aliases)
            if step_index is None:
                continue
            line = int(getattr(call, "lineno", 0) or 0)
            output = _best_output(steps[step_index - 1], "result")
            if output:
                for name in assignment_by_call.get(id(call), []):
                    assignments[name] = (step_index, output, line)

            params = list(steps[step_index - 1].get("params") or [])
            arguments: list[tuple[str, ast.AST]] = []
            for position, value in enumerate(call.args):
                if position < len(params):
                    arguments.append((str(params[position].get("name") or ""), value))
            arguments.extend(
                (str(keyword.arg or ""), keyword.value)
                for keyword in call.keywords
                if keyword.arg
            )
            for input_name, value in arguments:
                source = _argument_bindings(
                    value, assignments, aliases, steps, import_aliases
                )
                if not source or source[0] >= step_index or not source[1] or not input_name:
                    continue
                all_links.append({
                    "from_step": source[0],
                    "from_output": source[1],
                    "to_step": step_index,
                    "to_input": input_name,
                    "reason": "Observed project call site passes this upstream result into the argument.",
                    "evidence": {
                        "kind": "project_call_site",
                        "file": str(path),
                        "line": line,
                        "producer_line": source[2],
                    },
                    "confidence": "high",
                })
    return all_links


def _literal_argument_value(node: ast.AST) -> tuple[bool, Any]:
    """Return only inert literals; never evaluate project expressions."""

    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None
    if isinstance(value, (str, int, float, bool, type(None))):
        return True, value
    if isinstance(value, (list, tuple, dict)):
        try:
            encoded = json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False, None
        if len(encoded) <= 4096:
            return True, list(value) if isinstance(value, tuple) else value
    return False, None


def _live_context_kind(node: ast.AST) -> str:
    """Recognize established host-context expressions at real call sites."""

    name = _call_name(node.func).casefold() if isinstance(node, ast.Call) else _call_name(node).casefold()
    if name in {"bpy.context.selected_objects", "bpy.context.selected_editable_objects"}:
        return "selection"
    if name in {"bpy.context.object", "bpy.context.active_object"}:
        return "active_object"
    if isinstance(node, ast.Call):
        if name.endswith("cmds.ls") or name == "maya.cmds.ls":
            for keyword in node.keywords:
                if keyword.arg in {"selection", "sl"}:
                    ok, value = _literal_argument_value(keyword.value)
                    if ok and value is True:
                        return "selection"
        short = name.rsplit(".", 1)[-1]
        if short in {
            "get_selection", "current_selection", "selected_objects",
            "get_selected_objects", "get_selected_nodes", "get_selected_assets",
            "get_selected_actors", "get_selected_components",
        }:
            return "selection"
    return ""


def _usage_values_from_tree(
    tree: ast.AST,
    steps: list[dict[str, Any]],
    aliases: list[set[str]],
    path: Path,
) -> list[dict[str, Any]]:
    import_aliases = _import_aliases(tree)
    observations: list[dict[str, Any]] = []
    scopes: list[list[ast.stmt]] = []
    if isinstance(tree, ast.Module):
        scopes.append(list(tree.body))
    scopes.extend(
        list(node.body)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for body in scopes:
        owned: list[ast.AST] = []

        class _ScopeVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):  # noqa: N802
                return

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef
            visit_Lambda = visit_FunctionDef

            def generic_visit(self, node):
                owned.append(node)
                super().generic_visit(node)

        visitor = _ScopeVisitor()
        for statement in body:
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visitor.visit(statement)
        assigned: dict[str, list[tuple[int, ast.AST]]] = {}
        for node in owned:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append((int(getattr(node, "lineno", 0) or 0), value))

        for call in (node for node in owned if isinstance(node, ast.Call)):
            step_index = _resolve_step_for_call(call, aliases, import_aliases)
            if step_index is None:
                continue
            params = list(steps[step_index - 1].get("params") or [])
            arguments: list[tuple[str, ast.AST]] = []
            for position, value in enumerate(call.args):
                if position < len(params):
                    arguments.append((str(params[position].get("name") or ""), value))
            arguments.extend(
                (str(keyword.arg or ""), keyword.value)
                for keyword in call.keywords
                if keyword.arg
            )
            params_by_name = {
                str(param.get("name") or ""): param
                for param in params
                if isinstance(param, dict) and param.get("name")
            }
            for input_name, original_node in arguments:
                if not input_name:
                    continue
                value_node = original_node
                if isinstance(original_node, ast.Name):
                    candidates = [
                        item for item in assigned.get(original_node.id, [])
                        if item[0] < int(getattr(call, "lineno", 0) or 0)
                    ]
                    if candidates:
                        value_node = max(candidates, key=lambda item: item[0])[1]
                context_kind = _live_context_kind(value_node)
                if context_kind:
                    param = params_by_name.get(input_name, {})
                    annotation = str(param.get("annotation") or "")
                    multiple = (
                        input_name.endswith("s")
                        or input_name in {"selection", "selected"}
                        or any(word in annotation.lower() for word in ("list", "tuple", "set", "sequence"))
                    )
                    host = str((steps[step_index - 1].get("symbol") or {}).get("host") or "").lower()
                    observations.append({
                        "to_step": step_index,
                        "to_input": input_name,
                        "value": {
                            "$pipeline_context": "dcc_input_context_v1",
                            "host": host,
                            "context_kind": context_kind,
                            "input": input_name,
                            "multiple": multiple,
                            "label": "Current selection" if context_kind == "selection" else "Active object",
                        },
                        "reason": "Observed project call site resolves this argument from live DCC context.",
                        "evidence": {"kind": "project_call_site_context", "file": str(path), "line": int(getattr(call, "lineno", 0) or 0)},
                        "confidence": "high",
                    })
                    continue
                ok, value = _literal_argument_value(value_node)
                if ok:
                    observations.append({
                        "to_step": step_index,
                        "to_input": input_name,
                        "value": value,
                        "reason": "Observed project call site supplies this argument value.",
                        "evidence": {"kind": "project_call_site_value", "file": str(path), "line": int(getattr(call, "lineno", 0) or 0)},
                        "confidence": "high",
                    })
    return observations


def _consensus_usage_values(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in observations:
        grouped.setdefault((int(row["to_step"]), str(row["to_input"])), []).append(row)
    resolved: list[dict[str, Any]] = []
    for rows in grouped.values():
        fingerprints: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = json.dumps(row.get("value"), sort_keys=True, default=str)
            fingerprints.setdefault(key, []).append(row)
        # Ambiguous project usage is evidence to show, not a value to guess.
        if len(fingerprints) != 1:
            continue
        selected = dict(rows[0])
        selected["evidence_count"] = len(rows)
        resolved.append(selected)
    return sorted(resolved, key=lambda row: (row["to_step"], row["to_input"]))


def infer_project_usage_context(
    steps: list[dict[str, Any]],
    project_roots: list[str] | tuple[str, ...],
    *,
    max_files: int = 1500,
    time_budget_seconds: float = 2.0,
) -> dict[str, Any]:
    """Infer proven links and unambiguous argument context from real usage."""

    if not steps:
        return {"links": [], "values": [], "scanned_files": 0}
    aliases = [_step_aliases(step) for step in steps]
    searchable = {name for values in aliases for name in values if "." not in name}
    started = time.monotonic()
    scanned = 0
    found_links: list[dict[str, Any]] = []
    found_values: list[dict[str, Any]] = []
    for root_text in project_roots:
        root = Path(root_text)
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if scanned >= max_files or time.monotonic() - started >= time_budget_seconds:
                break
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            scanned += 1
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            present = [name for name in searchable if re.search(rf"\b{re.escape(name)}\s*\(", source)]
            if not present:
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue
            if len(present) >= 2:
                found_links.extend(_links_from_tree(tree, steps, aliases, path))
            found_values.extend(_usage_values_from_tree(tree, steps, aliases, path))

    by_target: dict[tuple[int, str], dict[str, Any]] = {}
    for link in found_links:
        key = (int(link["to_step"]), str(link["to_input"]))
        current = by_target.get(key)
        if current is None or int(link["from_step"]) > int(current["from_step"]):
            link["evidence_count"] = 1
            by_target[key] = link
        elif int(link["from_step"]) == int(current["from_step"]) and link["from_output"] == current["from_output"]:
            current["evidence_count"] = int(current.get("evidence_count") or 1) + 1
    return {
        "links": sorted(by_target.values(), key=lambda row: (row["to_step"], row["to_input"])),
        "values": _consensus_usage_values(found_values),
        "scanned_files": scanned,
    }


def infer_project_usage_links(
    steps: list[dict[str, Any]],
    project_roots: list[str] | tuple[str, ...],
    *,
    max_files: int = 1500,
    time_budget_seconds: float = 2.0,
) -> list[dict[str, Any]]:
    """Return links proven by data flow at real call sites in project Python."""

    if len(steps) < 2:
        return []
    return list(infer_project_usage_context(
        steps,
        project_roots,
        max_files=max_files,
        time_budget_seconds=time_budget_seconds,
    )["links"])


__all__ = ["infer_project_usage_context", "infer_project_usage_links"]
