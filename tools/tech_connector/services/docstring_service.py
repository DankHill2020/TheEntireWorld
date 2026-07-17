"""Deterministic Python docstring insertion utilities."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable


@dataclass
class AddedDocstring:
    """Record a generated docstring insertion."""

    name: str
    line: int
    params: list[str] = field(default_factory=list)
    has_return: bool = False
    updated_existing: bool = False


@dataclass
class DocstringResult:
    """Result of adding missing docstrings to Python source."""

    source: str
    changed: bool
    added: list[AddedDocstring] = field(default_factory=list)
    updated_existing: list[str] = field(default_factory=list)
    skipped_out_of_scope: list[str] = field(default_factory=list)
    error: str = ""


VERB_PREFIXES = {
    "add": "Adds",
    "apply": "Applies",
    "build": "Builds",
    "calculate": "Calculates",
    "check": "Checks",
    "clean": "Cleans",
    "collect": "Collects",
    "connect": "Connects",
    "convert": "Converts",
    "create": "Creates",
    "delete": "Deletes",
    "detect": "Detects",
    "execute": "Executes",
    "export": "Exports",
    "find": "Finds",
    "format": "Formats",
    "generate": "Generates",
    "get": "Gets",
    "handle": "Handles",
    "import": "Imports",
    "initialize": "Initializes",
    "load": "Loads",
    "make": "Makes",
    "normalize": "Normalizes",
    "open": "Opens",
    "parse": "Parses",
    "populate": "Populates",
    "prepare": "Prepares",
    "refresh": "Refreshes",
    "remove": "Removes",
    "render": "Renders",
    "resolve": "Resolves",
    "run": "Runs",
    "save": "Saves",
    "set": "Sets",
    "show": "Shows",
    "sync": "Syncs",
    "toggle": "Toggles",
    "update": "Updates",
    "validate": "Validates",
    "write": "Writes",
}


def looks_like_docstring_request(text: str) -> bool:
    """Return whether a chat prompt asks to add missing docstrings."""
    lower = (text or "").lower()
    return bool(
        re.search(r"\b(add|create|generate|insert|write)\b", lower)
        and re.search(r"\b(docstring|docstrings|function docs|function documentation)\b", lower)
    )


def add_missing_docstrings_to_file(
    path: str | Path,
    *,
    selection_start_line: int | None = None,
    selection_end_line: int | None = None,
) -> DocstringResult:
    """Read a Python file and return updated source with missing function docs."""
    source = Path(path).read_text(encoding="utf-8")
    return add_missing_docstrings(
        source,
        selection_start_line=selection_start_line,
        selection_end_line=selection_end_line,
    )


def add_missing_docstrings(
    source: str,
    *,
    selection_start_line: int | None = None,
    selection_end_line: int | None = None,
) -> DocstringResult:
    """Add missing docstrings and repair missing parameter docs."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return DocstringResult(source=source, changed=False, error=f"Python syntax error: {exc}")

    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines()
    edits: list[tuple[int, int, list[str], AddedDocstring]] = []
    result = DocstringResult(source=source, changed=False)

    for node in _iter_functions(tree):
        if not _in_selection(node, selection_start_line, selection_end_line):
            result.skipped_out_of_scope.append(node.name)
            continue
        if not node.body:
            continue
        body_line_index = max(0, node.body[0].lineno - 1)
        body_indent = _line_indent(lines[body_line_index]) if body_line_index < len(lines) else _node_indent(lines, node) + "    "
        params = _function_param_names(node)
        has_return = _has_return_value(node)
        existing_doc = _existing_docstring_node(node)
        if existing_doc is None:
            doc_lines = _build_docstring_lines(node.name, params, has_return, body_indent)
            record = AddedDocstring(
                name=node.name,
                line=node.lineno,
                params=params,
                has_return=has_return,
            )
            edits.append((body_line_index, body_line_index, doc_lines, record))
            continue

        replacement = _repair_existing_docstring_lines(lines, existing_doc, params, has_return)
        if replacement is None:
            continue
        record = AddedDocstring(
            name=node.name,
            line=node.lineno,
            params=params,
            has_return=has_return,
            updated_existing=True,
        )
        edits.append((existing_doc.lineno - 1, existing_doc.end_lineno or existing_doc.lineno, replacement, record))
        result.updated_existing.append(node.name)

    if not edits:
        return result

    for start, end, doc_lines, record in sorted(edits, key=lambda item: item[0], reverse=True):
        lines[start:end] = doc_lines
        result.added.append(record)

    result.added.sort(key=lambda item: item.line)
    result.source = newline.join(lines)
    if source.endswith(("\n", "\r\n")):
        result.source += newline
    result.changed = result.source != source
    return result


def _iter_functions(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _in_selection(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    selection_start_line: int | None,
    selection_end_line: int | None,
) -> bool:
    if not selection_start_line or not selection_end_line:
        return True
    start = min(selection_start_line, selection_end_line)
    end = max(selection_start_line, selection_end_line)
    node_end = getattr(node, "end_lineno", node.lineno)
    return node.lineno <= end and node_end >= start


def _line_indent(line: str) -> str:
    match = re.match(r"\s*", line or "")
    return match.group(0) if match else ""


def _node_indent(lines: list[str], node: ast.AST) -> str:
    index = max(0, getattr(node, "lineno", 1) - 1)
    if index < len(lines):
        return _line_indent(lines[index])
    return ""


def _function_param_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = node.args
    names: list[str] = []
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        if arg.arg not in {"self", "cls"}:
            names.append(arg.arg)
    if args.vararg and args.vararg.arg not in {"self", "cls"}:
        names.append(args.vararg.arg)
    if args.kwarg and args.kwarg.arg not in {"self", "cls"}:
        names.append(args.kwarg.arg)
    return names


def _has_return_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is node:
                self.generic_visit(child)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is node:
                self.generic_visit(child)

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

        def visit_Return(self, child: ast.Return) -> None:
            if child.value is not None:
                self.found = True

    visitor = ReturnVisitor()
    visitor.visit(node)
    return visitor.found


def _build_docstring_lines(name: str, params: list[str], has_return: bool, indent: str) -> list[str]:
    summary = _summary_for_function(name)
    lines = [
        f'{indent}"""',
        f"{indent}    {summary}",
    ]
    for param in params:
        lines.append(f"{indent}:param {param}: {_param_description(param)}")
    lines.append(f"{indent}:return: {'result' if has_return else ''}".rstrip())
    lines.append(f'{indent}"""')
    return lines


def _existing_docstring_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.Constant | None:
    if not node.body:
        return None
    first = node.body[0]
    if not isinstance(first, ast.Expr):
        return None
    value = first.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value
    return None


def _repair_existing_docstring_lines(
    lines: list[str],
    doc_node: ast.Constant,
    params: list[str],
    has_return: bool,
) -> list[str] | None:
    start = doc_node.lineno - 1
    end = doc_node.end_lineno or doc_node.lineno
    original = lines[start:end]
    if not original:
        return None

    existing_text = "\n".join(original)
    missing_params = [param for param in params if not re.search(rf":param\s+{re.escape(param)}\s*:", existing_text)]
    missing_return = has_return and ":return:" not in existing_text
    if not missing_params and not missing_return:
        return None

    indent = _line_indent(original[-1])
    if len(original) == 1 and _line_contains_docstring_close(original[0]):
        body_text = str(doc_node.value or "").strip()
        expanded = [
            f'{indent}"""',
        ]
        if body_text:
            for line in body_text.splitlines():
                expanded.append(f"{indent}    {line.strip()}")
        expanded.extend(f"{indent}:param {param}: {_param_description(param)}" for param in missing_params)
        if missing_return:
            expanded.append(f"{indent}:return: result")
        expanded.append(f'{indent}"""')
        return expanded

    insert_at = len(original) - 1 if _line_contains_docstring_close(original[-1]) else len(original)
    additions = [f"{indent}:param {param}: {_param_description(param)}" for param in missing_params]
    if missing_return:
        additions.append(f"{indent}:return: result")
    return original[:insert_at] + additions + original[insert_at:]


def _line_contains_docstring_close(line: str) -> bool:
    stripped = (line or "").strip()
    return stripped.endswith('"""') or stripped.endswith("'''")


def _summary_for_function(name: str) -> str:
    clean = name.strip("_")
    parts = [part for part in clean.split("_") if part]
    if not parts:
        return "Describe this function."
    first = parts[0].lower()
    remainder = " ".join(parts[1:]) if len(parts) > 1 else "the requested operation"
    verb = VERB_PREFIXES.get(first)
    if verb:
        return f"{verb} {remainder}."
    return f"{clean.replace('_', ' ').capitalize()}."


def _param_description(name: str) -> str:
    readable = name.strip("_").replace("_", " ")
    if readable.endswith("s") or readable.endswith("list"):
        return f"list of {readable}"
    if "map" in readable or "dict" in readable:
        return f"mapping for {readable}"
    if readable in {"name", "path", "size", "normal", "offset"}:
        labels = {
            "name": "name",
            "path": "path",
            "size": "local size mult",
            "normal": "relative direction",
            "offset": "offset value",
        }
        return labels[readable]
    return readable
