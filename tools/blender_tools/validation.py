"""Read-only parity inspectors for Blender production workflows."""

from __future__ import annotations

from typing import Any


def inspect_generalist_asset(
    object_name: str,
    material_name: str,
    start_frame: int = 1,
    end_frame: int = 24,
) -> dict[str, Any]:
    import bpy

    obj = bpy.data.objects.get(str(object_name))
    material = bpy.data.materials.get(str(material_name))
    mesh = getattr(obj, "data", None) if obj is not None else None
    polygons = len(getattr(mesh, "polygons", ()) or ()) if mesh is not None else 0
    topology_ok = bool(obj and obj.type == "MESH" and polygons > 0)
    uv_layers = len(getattr(mesh, "uv_layers", ()) or ()) if mesh is not None else 0
    assigned = [slot.material for slot in getattr(obj, "material_slots", ()) or () if slot.material]
    material_ok = bool(material and uv_layers > 0 and material in assigned)
    # Skeletal FBX animation belongs to the armature, not the skinned mesh.
    # Validate the mesh plus its parent and armature-modifier targets.
    animation_sources = [obj] if obj is not None else []
    parent = getattr(obj, "parent", None) if obj is not None else None
    if parent is not None and parent not in animation_sources:
        animation_sources.append(parent)
    for modifier in getattr(obj, "modifiers", ()) or ():
        candidate = getattr(modifier, "object", None)
        if (
            getattr(modifier, "type", "") == "ARMATURE"
            and candidate is not None
            and candidate not in animation_sources
        ):
            animation_sources.append(candidate)
    key_times_set = set()
    animated_objects = []
    for source in animation_sources:
        action = getattr(getattr(source, "animation_data", None), "action", None)
        if action is None:
            continue
        source_times = {
            float(point.co[0])
            for curve in getattr(action, "fcurves", ()) or ()
            for point in getattr(curve, "keyframe_points", ()) or ()
        }
        if not source_times:
            frame_range = getattr(action, "frame_range", None)
            if frame_range is not None and len(frame_range) >= 2:
                source_times.update((float(frame_range[0]), float(frame_range[1])))
        if source_times:
            key_times_set.update(source_times)
            animated_objects.append(str(getattr(source, "name", "")))
    key_times = sorted(key_times_set)
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    animation_ok = bool(key_times and key_times[0] <= start and key_times[-1] >= end)
    return {
        "ok": True,
        "object_name": str(object_name),
        "material_name": str(material_name),
        "polygon_count": polygons,
        "uv_layer_count": uv_layers,
        "key_times": key_times,
        "animated_objects": animated_objects,
        "parity_checks": {
            "topology": topology_ok,
            "UV and materials": material_ok,
            "animation range": animation_ok,
        },
    }


__all__ = ["inspect_generalist_asset"]
