"""MotionBuilder-inspired native animation takes, layers, and keyframe curves."""

from __future__ import annotations

from typing import Any
import uuid


def create_take(
    graph: Any,
    name: str,
    *,
    start_frame: int = 1,
    end_frame: int = 120,
    frame_rate: float = 24.0,
    timecode_start: str = "00:00:00:00",
) -> str:
    if int(end_frame) < int(start_frame):
        raise ValueError("A take's end frame cannot precede its start frame.")
    take_id = f"take_{uuid.uuid4().hex[:12]}"
    graph.animation[take_id] = {
        "id": take_id,
        "type": "animation_take",
        "name": str(name or "Take"),
        "start_frame": int(start_frame),
        "end_frame": int(end_frame),
        "frame_rate": float(frame_rate),
        "timecode_start": str(timecode_start or "00:00:00:00"),
        "active_layer": "BaseAnimation",
        "layers": {
            "BaseAnimation": {
                "name": "BaseAnimation",
                "weight": 1.0,
                "muted": False,
                "solo": False,
                "additive": False,
                "curves": {},
            }
        },
    }
    return take_id


def add_animation_layer(
    graph: Any,
    take_id: str,
    name: str,
    *,
    weight: float = 1.0,
    additive: bool = True,
) -> str:
    take = _take(graph, take_id)
    layer_name = str(name or "Layer").strip()
    if not layer_name:
        raise ValueError("Animation layer name cannot be empty.")
    layers = take.setdefault("layers", {})
    if layer_name in layers:
        raise ValueError(f"Animation layer already exists: {layer_name}")
    layers[layer_name] = {
        "name": layer_name,
        "weight": max(0.0, min(1.0, float(weight))),
        "muted": False,
        "solo": False,
        "additive": bool(additive),
        "curves": {},
    }
    take["active_layer"] = layer_name
    return layer_name


def set_keyframe(
    graph: Any,
    take_id: str,
    node_id: str,
    attribute: str,
    frame: int,
    value: float,
    *,
    layer: str = "",
    interpolation: str = "auto",
) -> dict[str, Any]:
    take = _take(graph, take_id)
    if str(node_id) not in graph.nodes:
        raise KeyError(f"Unknown animation node: {node_id}")
    layer_name = str(layer or take.get("active_layer") or "BaseAnimation")
    layer_data = (take.get("layers") or {}).get(layer_name)
    if layer_data is None:
        raise KeyError(f"Unknown animation layer: {layer_name}")
    curve_id = f"{node_id}.{attribute}"
    curve = layer_data.setdefault("curves", {}).setdefault(
        curve_id,
        {"node_id": str(node_id), "attribute": str(attribute), "keys": []},
    )
    key = {
        "frame": int(frame),
        "value": float(value),
        "interpolation": str(interpolation or "auto"),
    }
    keys = curve.setdefault("keys", [])
    frame_number = int(frame)
    index = _key_index(keys, frame_number)
    if index < len(keys) and int(keys[index].get("frame", 0)) == frame_number:
        keys[index] = key
    else:
        keys.insert(index, key)
    return key


def evaluate_curve(graph: Any, take_id: str, node_id: str, attribute: str, frame: float) -> float | None:
    take = _take(graph, take_id)
    value: float | None = None
    layers = take.get("layers") or {}
    soloed = {name for name, layer in layers.items() if bool(layer.get("solo"))}
    for layer_name, layer in layers.items():
        if bool(layer.get("muted")) or (soloed and layer_name not in soloed):
            continue
        curve = (layer.get("curves") or {}).get(f"{node_id}.{attribute}")
        sample = _sample_keys((curve or {}).get("keys") or [], float(frame))
        if sample is None:
            continue
        weight = max(0.0, min(1.0, float(layer.get("weight", 1.0) or 0.0)))
        if value is None:
            value = sample
        elif bool(layer.get("additive", True)):
            value += sample * weight
        else:
            value = value * (1.0 - weight) + sample * weight
    return value


def _sample_keys(keys: list[dict[str, Any]], frame: float) -> float | None:
    if not keys:
        return None
    sample_frame = float(frame)
    index = _key_index(keys, sample_frame)
    if index <= 0:
        return float(keys[0]["value"])
    if index >= len(keys):
        return float(keys[-1]["value"])
    second_frame = float(keys[index].get("frame", 0.0))
    if second_frame == sample_frame:
        return float(keys[index]["value"])
    first, second = keys[index - 1], keys[index]
    first_frame = float(first.get("frame", 0.0))
    if str(first.get("interpolation") or "auto").lower() in {"constant", "stepped"}:
        return float(first["value"])
    alpha = (sample_frame - first_frame) / max(1.0e-12, second_frame - first_frame)
    return float(first["value"]) * (1.0 - alpha) + float(second["value"]) * alpha


def _key_index(keys: list[dict[str, Any]], frame: float) -> int:
    """Return the first key index at or after ``frame`` without allocating a frame list."""
    low, high = 0, len(keys)
    while low < high:
        middle = (low + high) // 2
        if float(keys[middle].get("frame", 0.0)) < frame:
            low = middle + 1
        else:
            high = middle
    return low


def _take(graph: Any, take_id: str) -> dict[str, Any]:
    take = graph.animation.get(str(take_id))
    if not isinstance(take, dict) or str(take.get("type") or "") != "animation_take":
        raise KeyError(f"Unknown animation take: {take_id}")
    return take
