"""Concrete Blender animation bake operations."""

from __future__ import annotations

from typing import Any


def set_keyframe(
    object_name: str,
    data_path: str,
    frame: int,
    value: Any,
    index: int = -1,
) -> dict[str, Any]:
    import bpy

    obj = bpy.data.objects.get(str(object_name))
    if obj is None:
        raise ValueError(f"Blender object does not exist: {object_name}")
    tokens = str(data_path).split(".")
    target = obj
    for token in tokens[:-1]:
        target = getattr(target, token)
    attribute = tokens[-1]
    if index >= 0:
        sequence = getattr(target, attribute)
        sequence[int(index)] = value
    else:
        setattr(target, attribute, value)
    inserted = obj.keyframe_insert(
        data_path=str(data_path),
        index=int(index),
        frame=int(frame),
    )
    if not inserted:
        raise RuntimeError(f"Blender did not insert keyframe: {object_name}.{data_path}")
    return {
        "ok": True,
        "object_name": obj.name,
        "data_path": str(data_path),
        "index": int(index),
        "frame": int(frame),
        "value": value,
    }


def bake_keyframes(start_frame: int, end_frame: int, only_selected: bool = True) -> dict[str, Any]:
    import bpy

    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    bpy.ops.nla.bake(
        frame_start=start,
        frame_end=end,
        only_selected=bool(only_selected),
        visual_keying=True,
        clear_constraints=False,
        clear_parents=False,
        use_current_action=True,
        bake_types={"POSE", "OBJECT"},
    )
    return {"ok": True, "start_frame": start, "end_frame": end, "only_selected": bool(only_selected)}


__all__ = ["bake_keyframes", "set_keyframe"]
