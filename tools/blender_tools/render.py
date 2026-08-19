"""Concrete Blender render operations."""

from __future__ import annotations

from typing import Any


def render_scene(output_path: str = "", animation: bool = False, write_still: bool = True) -> dict[str, Any]:
    import bpy

    if output_path:
        bpy.context.scene.render.filepath = str(output_path)
    bpy.ops.render.render(animation=bool(animation), write_still=bool(write_still and not animation))
    return {
        "ok": True,
        "output_path": str(bpy.context.scene.render.filepath or ""),
        "animation": bool(animation),
        "engine": str(bpy.context.scene.render.engine),
    }


__all__ = ["render_scene"]
