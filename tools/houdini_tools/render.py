"""Houdini render submission operations."""

from __future__ import annotations

from typing import Any


def submit(rop_path: str, start_frame: int = 1, end_frame: int = 100, step: int = 1) -> dict[str, Any]:
    import hou

    rop = hou.node(rop_path)
    if rop is None:
        raise ValueError(f"ROP does not exist: {rop_path}")
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    rop.render(frame_range=(start, end, max(1, int(step))))
    return {"ok": True, "rop_path": rop.path(), "frame_range": [start, end], "step": max(1, int(step))}


__all__ = ["submit"]
