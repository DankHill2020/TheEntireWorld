"""Nested, exception-safe Maya undo transactions for public rig operations."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from maya import cmds


_DEPTH = 0
_F = TypeVar("_F", bound=Callable[..., Any])


@contextmanager
def undo_chunk(name: str) -> Iterator[None]:
    """Group nested rig edits into one Maya undo step."""
    global _DEPTH
    outermost = _DEPTH == 0
    opened = False
    if outermost:
        cmds.undoInfo(openChunk=True, chunkName=str(name))
        opened = True
    _DEPTH += 1
    try:
        yield
    finally:
        _DEPTH = max(0, _DEPTH - 1)
        if opened:
            cmds.undoInfo(closeChunk=True)


def undoable(name: str) -> Callable[[_F], _F]:
    """Decorate a public Maya operation with a nested-safe undo chunk."""
    def decorate(function: _F) -> _F:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with undo_chunk(name):
                return function(*args, **kwargs)
        return wrapped  # type: ignore[return-value]
    return decorate


__all__ = ["undo_chunk", "undoable"]