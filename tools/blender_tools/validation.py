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
    action = getattr(getattr(obj, "animation_data", None), "action", None) if obj is not None else None
    key_times = sorted({
        float(point.co[0])
        for curve in getattr(action, "fcurves", ()) or ()
        for point in getattr(curve, "keyframe_points", ()) or ()
    })
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    animation_ok = bool(key_times and key_times[0] <= start and key_times[-1] >= end)
    return {
        "ok": True,
        "object_name": str(object_name),
        "material_name": str(material_name),
        "polygon_count": polygons,
        "uv_layer_count": uv_layers,
        "key_times": key_times,
        "parity_checks": {
            "topology": topology_ok,
            "UV and materials": material_ok,
            "animation range": animation_ok,
        },
    }


__all__ = ["inspect_generalist_asset"]
