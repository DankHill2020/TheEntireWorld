from __future__ import annotations

"""Static quality checks for planner-visible Unreal Python callables."""

import ast
import re
from typing import Any


_PLACEHOLDER_TEXT_PATTERNS = (
    r"\bnot implemented\b",
    r"\bimplementation required\b",
    r"\bimplementation strategy\b",
    r"\bendpoint reached\b",
    r"\badd .{0,80} here\b",
    r"\bplaceholder\b",
    r"\bcpp body required\b",
    r"\brequires_[a-z0-9_]+(?:_strategy|_implementation)\b",
)


def inspect_python_function_quality(
    source: str,
    function_name: str,
) -> dict[str, Any]:
    """Return fail-closed implementation evidence for one top-level function."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "implemented": False,
            "state": "syntax_error",
            "reasons": [str(exc)],
        }

    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == function_name
        ),
        None,
    )
    if node is None:
        return {
            "implemented": False,
            "state": "function_def_missing",
            "reasons": ["top-level function definition was not found"],
        }

    reasons: list[str] = []
    executable_body = list(node.body)
    if (
        executable_body
        and isinstance(executable_body[0], ast.Expr)
        and isinstance(executable_body[0].value, ast.Constant)
        and isinstance(executable_body[0].value.value, str)
    ):
        executable_body = executable_body[1:]
    if not executable_body or all(
        isinstance(item, ast.Pass)
        or (
            isinstance(item, ast.Expr)
            and isinstance(item.value, ast.Constant)
            and item.value.value is Ellipsis
        )
        for item in executable_body
    ):
        reasons.append("empty_or_pass_only_body")

    if len(executable_body) == 1 and isinstance(executable_body[0], ast.Return):
        returned = executable_body[0].value
        if isinstance(returned, ast.Call):
            for keyword in returned.keywords:
                if (
                    keyword.arg == "ok"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is False
                ):
                    reasons.append("unconditional_failure_return")

    for item in ast.walk(node):
        if (
            isinstance(item, ast.Raise)
            and isinstance(item.exc, ast.Call)
            and isinstance(item.exc.func, ast.Name)
            and item.exc.func.id == "NotImplementedError"
        ):
            reasons.append("raises_not_implemented")

    body_text = ast.get_source_segment(source, node) or ""
    for pattern in _PLACEHOLDER_TEXT_PATTERNS:
        if re.search(pattern, body_text, flags=re.I | re.S):
            reasons.append(f"placeholder_text:{pattern}")

    reasons = list(dict.fromkeys(reasons))
    return {
        "implemented": not reasons,
        "state": "implemented" if not reasons else "placeholder",
        "reasons": reasons,
        "line": int(getattr(node, "lineno", 0) or 0),
    }
