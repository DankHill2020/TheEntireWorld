from __future__ import annotations

"""Explicit editor console for Python and adaptive TC engine commands."""

import ast
import contextlib
import io
import json
import time
import traceback
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class EngineConsoleReceipt:
    mode: str
    ok: bool
    output: str
    result_repr: str
    error: str
    elapsed_ms: float
    command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EngineConsoleSession:
    """Persistent explicit-execution namespace; no code runs on load or from chat."""

    def __init__(self) -> None:
        self.namespace: dict[str, Any] = {"__name__": "__tc_engine_console__"}
        self.history: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.namespace = {"__name__": "__tc_engine_console__"}

    def execute_python(self, source: str, context: dict[str, Any] | None = None) -> EngineConsoleReceipt:
        started = time.perf_counter()
        stdout = io.StringIO()
        stderr = io.StringIO()
        result: Any = None
        error = ""
        ok = False
        self.namespace.update(dict(context or {}))
        try:
            module = ast.parse(str(source), filename="<tc-engine-console>", mode="exec")
            body = list(module.body)
            expression = body.pop() if body and isinstance(body[-1], ast.Expr) else None
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                if body:
                    exec(compile(ast.Module(body=body, type_ignores=[]), "<tc-engine-console>", "exec"), self.namespace, self.namespace)
                if expression is not None:
                    result = eval(compile(ast.Expression(expression.value), "<tc-engine-console>", "eval"), self.namespace, self.namespace)
                    self.namespace["_"] = result
            ok = True
        except BaseException:
            error = traceback.format_exc()
        output = stdout.getvalue() + stderr.getvalue()
        receipt = EngineConsoleReceipt(
            "python",
            ok,
            output,
            repr(result) if result is not None else "",
            error,
            (time.perf_counter() - started) * 1000.0,
        )
        self.history.append(receipt.to_dict())
        return receipt

    def execute_tc_command(
        self,
        source: str,
        executor: Callable[..., dict[str, Any]],
    ) -> EngineConsoleReceipt:
        started = time.perf_counter()
        command = ""
        try:
            command, payload = parse_tc_command(source)
            result = executor(command, **payload)
            receipt = EngineConsoleReceipt(
                "tc_command",
                True,
                json.dumps(result, indent=2, default=str),
                "",
                "",
                (time.perf_counter() - started) * 1000.0,
                command,
            )
        except BaseException:
            receipt = EngineConsoleReceipt(
                "tc_command",
                False,
                "",
                "",
                traceback.format_exc(),
                (time.perf_counter() - started) * 1000.0,
                command,
            )
        self.history.append(receipt.to_dict())
        return receipt


def parse_tc_command(source: str) -> tuple[str, dict[str, Any]]:
    text = str(source or "").strip()
    if not text:
        raise ValueError("Enter a TC command.")
    if text.startswith("{"):
        data = json.loads(text)
        command = str(data.get("command") or "")
        payload = dict(data.get("payload") or {})
    else:
        first, separator, remainder = text.partition("\n")
        command = first.strip()
        payload = json.loads(remainder) if separator and remainder.strip() else {}
    if not command:
        raise ValueError("TC command JSON requires a non-empty 'command'.")
    return command, payload
