# ast_parser.py
"""Compatibility parser for the Project-Analysis pipeline.

Python symbol extraction is centralized in ``services.tool_discovery_service``
so GitHub ingestion, workflow composition, and project analysis all see the
same signatures, params, docstrings, returns, output slots, imports, and calls.

This module also performs a small AST metadata pass as a defensive fallback.
That guarantees DCC API references such as ``unreal.EditorAssetLibrary.load_asset``
are retained even when the shared extractor does not yet expose call metadata.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any, Dict, Iterable, List

from services.tool_discovery_service import extract_symbols_from_file


def _dotted_name(node: ast.AST) -> str:
    """Return a stable dotted name for a call/import expression when possible."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return ""


def _unique_strings(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _module_imports(tree: ast.AST) -> List[str]:
    imports: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}".strip("."))
    return _unique_strings(imports)


def _symbol_nodes(tree: ast.AST) -> Dict[tuple[str, int], ast.AST]:
    """Index function/class nodes by simple name and starting line."""
    indexed: Dict[tuple[str, int], ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            indexed[(node.name, int(getattr(node, "lineno", 0) or 0))] = node
    return indexed


def _best_symbol_node(
    nodes: Dict[tuple[str, int], ast.AST], name: str, lineno: int
) -> ast.AST | None:
    exact = nodes.get((name, lineno))
    if exact is not None:
        return exact
    candidates = [
        (abs(line - lineno), node)
        for (node_name, line), node in nodes.items()
        if node_name == name
    ]
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _calls_from_node(node: ast.AST | None) -> List[str]:
    if node is None:
        return []
    return _unique_strings(
        _dotted_name(child.func)
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
    )


def _unreal_refs(calls: Iterable[str]) -> List[str]:
    return _unique_strings(call for call in calls if call.lower().startswith("unreal."))


def parse_python_file(file_path: str) -> List[Dict[str, Any]]:
    """Parse a Python file and return project-analysis-compatible symbols."""
    path = pathlib.Path(file_path)
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        tree = ast.Module(body=[], type_ignores=[])

    module_imports = _module_imports(tree)
    nodes = _symbol_nodes(tree)
    symbols: List[Dict[str, Any]] = []

    for symbol in extract_symbols_from_file(path):
        name = str(symbol.get("name", ""))
        lineno = int(symbol.get("lineno", symbol.get("start_line", 0)) or 0)
        node = _best_symbol_node(nodes, name, lineno)

        extractor_calls = symbol.get("calls", []) or []
        if isinstance(extractor_calls, str):
            extractor_calls = [extractor_calls]
        calls = _unique_strings([*extractor_calls, *_calls_from_node(node)])

        extractor_imports = symbol.get("imports", []) or []
        if isinstance(extractor_imports, str):
            extractor_imports = [extractor_imports]
        imports = _unique_strings([*extractor_imports, *module_imports])

        extractor_unreal = symbol.get("unreal_refs", []) or []
        if isinstance(extractor_unreal, str):
            extractor_unreal = [extractor_unreal]
        unreal_refs = _unique_strings([*extractor_unreal, *_unreal_refs(calls)])

        symbols.append({
            "name": name,
            "type": symbol.get("kind", ""),
            "kind": symbol.get("kind", ""),
            "lineno": lineno,
            "start_line": int(symbol.get("start_line", lineno) or lineno),
            "end_line": int(symbol.get("end_line", 0) or 0),
            "file": symbol.get("file_path", file_path),
            "file_path": symbol.get("file_path", file_path),
            "signature": symbol.get("signature", ""),
            "docstring": symbol.get("docstring", ""),
            "params": symbol.get("params", []),
            "return_annotation": symbol.get("return_annotation", ""),
            "returns": symbol.get("returns", []),
            "outputs": symbol.get("outputs", []),
            "imports": imports,
            "calls": calls,
            "unreal_refs": unreal_refs,
            "operation_keys": symbol.get("operation_keys", []),
        })
    return symbols


def parse_file(file_path: str) -> List[Dict[str, Any]]:
    """Dispatch to the appropriate parser based on extension."""
    ext = pathlib.Path(file_path).suffix.lower()
    if ext == ".py":
        return parse_python_file(file_path)
    return []


if __name__ == "__main__":
    import sys

    for fp in sys.argv[1:]:
        for sym in parse_file(fp):
            print(sym)
