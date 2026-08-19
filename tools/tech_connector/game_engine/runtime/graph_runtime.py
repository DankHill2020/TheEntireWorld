from __future__ import annotations

"""Reference execution boundary for code generated from TC Graph Programs."""

from typing import Any, Callable, Mapping


GraphOperationHandler = Callable[..., Any]
_HANDLERS: dict[str, GraphOperationHandler] = {}


def register_graph_runtime_operation(operation: str, handler: GraphOperationHandler) -> None:
    if not operation or not callable(handler):
        raise ValueError("Runtime graph operations require an operation key and callable handler.")
    _HANDLERS[str(operation)] = handler


def unregister_graph_runtime_operation(operation: str) -> None:
    _HANDLERS.pop(str(operation), None)


def graph_call(operation: str, *, context: Any, **inputs: Any) -> Any:
    """Execute one graph operation through context overrides or the reference registry.

    The future C++ runtime consumes the matching native graph manifest. This
    Python dispatcher keeps generated code executable in editor previews and
    tests without making Python part of the shipping frame loop.
    """

    contextual: Mapping[str, GraphOperationHandler] = {}
    if isinstance(context, Mapping):
        contextual = context.get("graph_operations") or {}
    else:
        contextual = getattr(context, "graph_operations", {}) or {}
    handler = contextual.get(str(operation)) or _HANDLERS.get(str(operation))
    if handler is None:
        raise LookupError(
            f"Graph operation '{operation}' is unavailable in this preview context. "
            "Register its runtime handler or compile the program for the TC native runtime."
        )
    return handler(context=context, **inputs)


__all__ = ["graph_call", "register_graph_runtime_operation", "unregister_graph_runtime_operation"]
