"""Lightweight code structure extraction for the built-in editor."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StructureItem:
    name: str
    kind: str
    line: int
    depth: int = 0
    signature: str = ""

    def label(self) -> str:
        name = self.name
        if self.kind in {"function", "async function"} and self.signature:
            name = self.signature
        suffix = f"  :{self.line}" if self.line else ""
        return f"{name}{suffix}"


def _annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    params: list[str] = []
    args = list(getattr(node.args, "posonlyargs", [])) + list(node.args.args)
    for arg in args:
        text = arg.arg
        annotation = _annotation_text(arg.annotation)
        if annotation:
            text += f": {annotation}"
        params.append(text)
    if node.args.vararg:
        params.append("*" + node.args.vararg.arg)
    for arg in node.args.kwonlyargs:
        text = arg.arg
        annotation = _annotation_text(arg.annotation)
        if annotation:
            text += f": {annotation}"
        params.append(text)
    if node.args.kwarg:
        params.append("**" + node.args.kwarg.arg)
    returns = _annotation_text(node.returns)
    suffix = f" -> {returns}" if returns else ""
    return f"{node.name}({', '.join(params)}){suffix}"


def python_structure_from_text(text: str, file_path: str = "", *, sort_alpha: bool = True) -> list[StructureItem]:
    if file_path and Path(file_path).suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(text or "", filename=file_path or "<editor>")
    except SyntaxError:
        return []

    items: list[StructureItem] = []

    def sortable_name(node: ast.stmt) -> str:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name.lower()
        return "~"

    def ordered_body(body: list[ast.stmt]) -> list[ast.stmt]:
        if not sort_alpha:
            return body
        return sorted(body, key=lambda node: (sortable_name(node), getattr(node, "lineno", 0)))

    def visit_body(body: list[ast.stmt], depth: int) -> None:
        for node in ordered_body(body):
            if isinstance(node, ast.ClassDef):
                items.append(StructureItem(node.name, "class", node.lineno, depth, f"class {node.name}"))
                visit_body(node.body, depth + 1)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                items.append(StructureItem(node.name, kind, node.lineno, depth, _function_signature(node)))

    visit_body(tree.body, 0)
    return items
