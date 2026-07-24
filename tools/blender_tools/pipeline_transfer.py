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
    for obj in meshes:
        if clean_names:
            old_name = obj.name
            clean_name = re.sub(r"[^A-Za-z0-9_]+", "_", old_name).strip("_") or "Mesh"
            obj.name = clean_name
            obj.data.name = f"{clean_name}_Mesh"
            if old_name != clean_name:
                renamed[old_name] = clean_name
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        if apply_transforms:
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            transformed.append(obj.name)
        if ensure_material_slots and not obj.data.materials:
            material = bpy.data.materials.new(name=f"M_{obj.name}")
            obj.data.materials.append(material)
            materials.append(material.name)
        obj.select_set(False)

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

    return {
        "blender_scene": True,
        "meshes": [obj.name for obj in meshes],
        "renamed": renamed,
        "transformed": transformed,
        "materials": materials,
        "collision": collisions,
        "lods": lods,
    }
