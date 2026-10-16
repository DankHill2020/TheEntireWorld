"""Resolve a pipeline node's callable or operation implementation source."""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Any


TOOLS_ROOT = Path(__file__).resolve().parents[2]


def _definition_line(path: Path, symbol_name: str) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return 1
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == symbol_name
    ]
    return int(candidates[0].lineno) if candidates else 1


def _callable_source(function_path: str, roots: list[Path]) -> dict[str, Any] | None:
    parts = [part for part in str(function_path or "").split(".") if part]
    if len(parts) < 2:
        return None
    module_parts = parts[:-1]
    symbol_name = parts[-1]
    for root in roots:
        for candidate in (
            root.joinpath(*module_parts).with_suffix(".py"),
            root.joinpath(*module_parts, "__init__.py"),
        ):
            if candidate.is_file():
                return {
                    "file_path": str(candidate.resolve()),
                    "start_line": _definition_line(candidate, symbol_name),
                    "source_kind": "callable_definition",
                }
    return None


def _operation_source(host: str, operation: str) -> dict[str, Any] | None:
    host = str(host or "").lower()
    operation = str(operation or "")
    candidates = []
    if host == "unreal":
        candidates.append(TOOLS_ROOT / "tech_connector" / "services" / "unreal" / "unreal_operation_service.py")
    candidates.append(
        TOOLS_ROOT / "tech_connector" / "game_engine" / "integration" / "dcc_operation_service.py"
    )
    patterns = (
        re.compile(rf"^\s*elif\s+operation\s*==\s*['\"]{re.escape(operation)}['\"]\s*:", re.MULTILINE),
        re.compile(rf"^\s*['\"]{re.escape(operation)}['\"]\s*:\s*DccOperation\(", re.MULTILINE),
        re.compile(rf"^\s*key\s*=\s*['\"]{re.escape(operation)}['\"]", re.MULTILINE),
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return {
                    "file_path": str(candidate.resolve()),
                    "start_line": text.count("\n", 0, match.start()) + 1,
                    "source_kind": "operation_implementation",
                }
    return None


def resolve_pipeline_source_location(
    function_path: str,
    *,
    operation: str = "",
    host: str = "",
    project_roots: list[str] | None = None,
) -> dict[str, Any]:
    roots = [Path(root).expanduser().resolve() for root in (project_roots or []) if str(root).strip()]
    if TOOLS_ROOT not in roots:
        roots.append(TOOLS_ROOT)
    source = _callable_source(function_path, roots)
    if source:
        return source
    source = _operation_source(host, operation)
    if source:
        return source
    return {"file_path": "", "start_line": 1, "source_kind": "unresolved"}

