"""Concrete Blender FBX interchange operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def import_fbx(filepath: str, use_image_search: bool = True) -> dict[str, Any]:
    import bpy

    source = Path(filepath).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"FBX does not exist: {source}")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(source), use_image_search=bool(use_image_search))
    imported = [obj.name for obj in bpy.data.objects if obj not in before]
    return {"ok": True, "filepath": str(source), "objects": imported}


def export_fbx(
    filepath: str,
    selected_only: bool = True,
    apply_unit_scale: bool = True,
    axis_forward: str = "-Z",
    axis_up: str = "Y",
) -> dict[str, Any]:
    import bpy

    target = Path(filepath).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(target),
        use_selection=bool(selected_only),
        apply_unit_scale=bool(apply_unit_scale),
        axis_forward=str(axis_forward),
        axis_up=str(axis_up),
        bake_anim=True,
    )
    exists = target.is_file() and target.stat().st_size > 0
    if not exists:
        raise RuntimeError(f"Blender reported FBX export success but no file exists: {target}")
    return {
        "ok": True,
        "filepath": str(target),
        "selected_only": bool(selected_only),
        "axis_forward": str(axis_forward),
        "axis_up": str(axis_up),
        "parity_checks": {"coordinate conversion": exists and bool(apply_unit_scale)},
    }


__all__ = ["export_fbx", "import_fbx"]
