"""Weakly bind chat-callable commands to the active Scene Viewer session."""

from __future__ import annotations

import weakref
from typing import Any


_active_viewer: weakref.ReferenceType | None = None
_active_viewers: list[weakref.ReferenceType] = []


def _cleanup_stale_viewer_refs() -> None:
    global _active_viewer
    alive: list[weakref.ReferenceType] = [viewer_ref for viewer_ref in _active_viewers if viewer_ref() is not None]
    _active_viewers[:] = alive
    _active_viewer = alive[-1] if alive else None


def _release_viewer_ref(dead_ref: weakref.ReferenceType) -> None:
    global _active_viewers, _active_viewer
    _active_viewers = [viewer_ref for viewer_ref in _active_viewers if viewer_ref is not dead_ref]
    _cleanup_stale_viewer_refs()


def register_active_viewer(viewer: Any) -> None:
    global _active_viewer
    _cleanup_stale_viewer_refs()
    _active_viewers[:] = [viewer_ref for viewer_ref in _active_viewers if viewer_ref() is not viewer]
    tracked = weakref.ref(viewer, _release_viewer_ref)
    _active_viewers.append(tracked)
    if len(_active_viewers) > 16:
        del _active_viewers[:-16]
    _active_viewer = tracked


def unregister_active_viewer(viewer: Any) -> None:
    global _active_viewers, _active_viewer
    _active_viewers = [viewer_ref for viewer_ref in _active_viewers if viewer_ref() is not viewer]
    _cleanup_stale_viewer_refs()
    if _active_viewer is not None and _active_viewer() is viewer:
        _active_viewer = None


def active_viewer() -> Any | None:
    _cleanup_stale_viewer_refs()
    return _active_viewer() if _active_viewer is not None else None


def execute_active_viewer_command(command: str, **payload: Any) -> dict[str, Any]:
    viewer = active_viewer()
    if viewer is None:
        return {
            "executed": False,
            "command": str(command),
            "payload": dict(payload),
            "message": "Open The Entire Scene Viewer before executing a live scene command.",
            "status": "unavailable",
        }
    executor = getattr(viewer, "execute_adaptive_scene_command", None)
    if not callable(executor):
        return {
            "executed": False,
            "command": str(command),
            "payload": dict(payload),
            "message": "The active Scene Viewer does not expose adaptive command execution.",
            "status": "unsupported",
        }
    try:
        return dict(executor(str(command), dict(payload)) or {})
    except Exception as exc:
        return {
            "executed": False,
            "command": str(command),
            "payload": dict(payload),
            "message": str(exc) or "Scene Viewer command execution failed.",
            "status": "error",
        }
