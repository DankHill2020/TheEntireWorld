"""Dynamic Python execution helpers importable by the Unreal HTTP bridge.

This copy lives with Tech Connector's Unreal bridge code so the bridge can reference
it via a stable local module path.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import traceback
from typing import Any

_GLOBALS: dict[str, Any] = {}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    try:
        return str(value)
    except Exception:
        return repr(value)


def _compile_with_last_expr_result(source: str):
    tree = ast.parse(source, mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = tree.body[-1]
        tree.body[-1] = ast.Assign(
            targets=[ast.Name(id="__ai_result__", ctx=ast.Store())],
            value=last.value,
        )
        ast.fix_missing_locations(tree)
    return compile(tree, "<ai_studio_unreal_dynamic>", "exec")


def run_python_payload(source: str, reset_globals: bool = False) -> dict[str, Any]:
    """Execute *source* inside Unreal's Python interpreter and return details.

    If the final statement is an expression, its value is returned as `result`.
    Scripts may also explicitly assign a variable named `result`.
    """
    global _GLOBALS
    if reset_globals:
        _GLOBALS = {}

    stdout = io.StringIO()
    stderr = io.StringIO()
    namespace = _GLOBALS
    namespace.setdefault("__name__", "ai_studio_unreal_dynamic")

    try:
        try:
            import unreal  # type: ignore

            namespace.setdefault("unreal", unreal)
        except Exception:
            pass

        namespace.pop("__ai_result__", None)
        compiled = _compile_with_last_expr_result(source or "")
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compiled, namespace, namespace)
        result = namespace.get("result", namespace.get("__ai_result__"))
        return {
            "ok": True,
            "result": _jsonable(result),
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": None,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


def run_python_json(source: str, reset_globals: bool = False) -> str:
    return json.dumps(
        run_python_payload(source, reset_globals=reset_globals), indent=2, default=str
    )



def run_python(source: str, reset_globals: bool = False):
    """Legacy bridge-compatible Python executor.

    The Unreal HTTP dispatcher used by this toolchain expects exposed functions
    to return ``(success, payload)``.  Returning a bare dict causes dispatcher
    unpack errors such as:

        not enough values to unpack (expected 2, got 1)

    Keep the rich execution details, but wrap them in the legacy two-value
    contract so both older unreal_tools functions and this dynamic executor
    behave the same way.
    """
    payload = run_python_payload(source, reset_globals=reset_globals)
    return bool(payload.get("ok")), payload


def run_python_tuple(source: str, reset_globals: bool = False):
    """Explicit alias for callers that want the legacy two-value contract."""
    return run_python(source, reset_globals=reset_globals)
