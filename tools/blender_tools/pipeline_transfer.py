"""Reusable Blender preparation operations for cross-DCC transfers."""

from __future__ import annotations

from typing import Any


def process_meshes_for_transfer(
    objects: list[str] | tuple[str, ...] | None = None,
    *,
    clean_names: bool = True,
    apply_transforms: bool = True,
    lod_count: int = 0,
    ensure_material_slots: bool = False,
    create_collision: bool = False,
    bevel_width: float = 0.0,
    bevel_segments: int = 2,
) -> dict[str, Any]:
    """Prepare Blender meshes for export and report every mutation."""
    import re
    import bpy

    requested = [str(name) for name in (objects or []) if str(name)]
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and (not requested or obj.name in requested)
    ]
    if not meshes:
        raise RuntimeError("No Blender mesh objects matched the transfer preparation request")

    renamed = {}
    transformed = []
    materials = []
    collisions = []
    lods = []
    bevels = []
    armatures = []
    width = float(bevel_width)
    segments = int(bevel_segments)
    if width < 0:
        raise ValueError("bevel_width must be nonnegative")
    if segments < 1 or segments > 1000:
        raise ValueError("bevel_segments must be between 1 and 1000")
    previous_selection = tuple(bpy.context.selected_objects)
    previous_active = bpy.context.view_layer.objects.active
    try:
        # transform_apply is a selection-wide operator. A caller may have other
        # scene objects selected, so isolate each requested mesh before invoking it.
        for selected in previous_selection:
            selected.select_set(False)
        for obj in meshes:
            if clean_names:
                old_name = obj.name
                clean_name = re.sub(r"[^A-Za-z0-9_]+", "_", old_name).strip("_") or "Mesh"
                obj.name = clean_name
                obj.data.name = f"{clean_name}_Mesh"
                if old_name != clean_name:
                    renamed[old_name] = clean_name
            if apply_transforms:
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                try:
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                    transformed.append(obj.name)
                finally:
                    obj.select_set(False)
            if ensure_material_slots and not obj.data.materials:
                material = bpy.data.materials.new(name=f"M_{obj.name}")
                obj.data.materials.append(material)
                materials.append(material.name)
            if width:
                modifier = obj.modifiers.new(name="TC_TransferBevel", type="BEVEL")
                modifier.width = width
                modifier.segments = segments
                modifier.limit_method = "ANGLE"
                bevels.append({"object": obj.name, "width": width, "segments": segments})

            for lod_index in range(1, max(0, int(lod_count)) + 1):
                duplicate = obj.copy()
                duplicate.data = obj.data.copy()
                duplicate.name = f"{obj.name}_LOD{lod_index}"
                bpy.context.collection.objects.link(duplicate)
                modifier = duplicate.modifiers.new(name="AIStudio_LOD", type="DECIMATE")
                modifier.ratio = max(0.05, 1.0 / (lod_index + 1))
                lods.append(duplicate.name)
            if create_collision:
                collision = obj.copy()
                collision.data = obj.data.copy()
                collision.name = f"UCX_{obj.name}_00"
                bpy.context.collection.objects.link(collision)
                collisions.append(collision.name)

            armature = obj.find_armature()
            if armature is not None and armature.name not in armatures:
                armatures.append(armature.name)
    finally:
        for selected in previous_selection:
            selected.select_set(True)
        bpy.context.view_layer.objects.active = previous_active

    export_objects = list(dict.fromkeys(
        [obj.name for obj in meshes] + armatures + lods + collisions
    ))

    return {
        "blender_scene": True,
        "export_objects": export_objects,
        "meshes": [obj.name for obj in meshes],
        "armatures": armatures,
        "renamed": renamed,
        "transformed": transformed,
        "materials": materials,
        "collision": collisions,
        "lods": lods,
        "bevels": bevels,
    }
