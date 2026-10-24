"""Concrete Blender FBX interchange operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def import_fbx(
    filepath: str,
    use_image_search: bool = True,
    animation_offset: float = 0.0,
) -> dict[str, Any]:
    import bpy

    source = Path(filepath).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"FBX does not exist: {source}")
    before = set(bpy.data.objects)
    before_actions = set(getattr(bpy.data, "actions", ()))
    status = bpy.ops.import_scene.fbx(
        filepath=str(source),
        use_image_search=bool(use_image_search),
        # Blender defaults to 1.0, which silently moves Maya frame 1 to frame 2.
        anim_offset=float(animation_offset),
    )
    if status is not None and "FINISHED" not in status:
        raise RuntimeError(f"Blender did not complete FBX import: {source}")
    imported_objects = [obj for obj in bpy.data.objects if obj not in before]
    imported_actions = [
        action for action in getattr(bpy.data, "actions", ()) if action not in before_actions
    ]
    if not imported_objects and not imported_actions:
        raise RuntimeError(
            f"FBX import produced no scene objects or animation actions: {source}. "
            "Check the source export selection and file content."
        )
    imported = [obj.name for obj in imported_objects]
    return {
        "ok": True,
        "filepath": str(source),
        "objects": imported,
        "meshes": [obj.name for obj in imported_objects if getattr(obj, "type", "") == "MESH"],
        "armatures": [obj.name for obj in imported_objects if getattr(obj, "type", "") == "ARMATURE"],
        "animations": list(dict.fromkeys([
            *(str(action.name) for action in imported_actions),
            *(
                str(obj.animation_data.action.name)
                for obj in imported_objects
                if getattr(getattr(obj, "animation_data", None), "action", None) is not None
            ),
        ])),
        "animation_offset": float(animation_offset),
    }


def export_fbx(
    filepath: str,
    selected_only: bool = True,
    apply_unit_scale: bool = True,
    axis_forward: str = "-Z",
    axis_up: str = "Y",
    object_names: list[str] | tuple[str, ...] | None = None,
    bake_animation: bool = True,
) -> dict[str, Any]:
    import bpy

    target = Path(filepath).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    exported_objects = []
    if object_names is not None:
        bpy.ops.object.select_all(action="DESELECT")
        for name in dict.fromkeys(str(value) for value in object_names):
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise ValueError(f"Blender export object does not exist: {name}")
            obj.select_set(True)
            exported_objects.append(name)
        selected_only = True
    bpy.ops.export_scene.fbx(
        filepath=str(target),
        use_selection=bool(selected_only),
        apply_unit_scale=bool(apply_unit_scale),
        use_mesh_modifiers=True,
        axis_forward=str(axis_forward),
        axis_up=str(axis_up),
        bake_anim=bool(bake_animation),
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
        "bake_animation": bool(bake_animation),
        "objects": exported_objects,
        "parity_checks": {"coordinate conversion": exists and bool(apply_unit_scale)},
    }


__all__ = ["export_fbx", "import_fbx"]
