"""Unreal Editor-side exporter for Tech Connector's animation interchange importer.

Run this module inside Unreal's Python environment. It intentionally uses reflected
editor data instead of attempting to decode private ``.uasset`` bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def export_animation_assets(asset_paths: Iterable[str], destination: str = "") -> dict[str, Any]:
    import unreal  # Available only in the Unreal Editor Python process.

    document: dict[str, Any] = {
        "engine_version": str(unreal.SystemLibrary.get_engine_version()),
        "animation_sequences": [], "blend_spaces": [], "animation_blueprints": [],
    }
    exported_sequences: set[str] = set()
    for object_path in dict.fromkeys(str(value) for value in asset_paths):
        asset = unreal.EditorAssetLibrary.load_asset(object_path)
        if asset is None:
            raise ValueError(f"Unreal asset was not found: {object_path}")
        class_name = asset.get_class().get_name()
        if class_name in {"AnimSequence", "AnimSequenceBase"}:
            document["animation_sequences"].append(_animation_sequence(unreal, object_path, asset))
            exported_sequences.add(object_path)
        elif class_name in {"BlendSpace", "BlendSpace1D"}:
            blend_space = _blend_space(unreal, object_path, asset, class_name)
            document["blend_spaces"].append(blend_space)
            # A Blend Space export is dependency-closed: referenced clips travel with it.
            for sample in blend_space.get("samples") or []:
                animation_path = str(sample.get("animation") or "")
                if not animation_path or animation_path in exported_sequences:
                    continue
                animation = unreal.EditorAssetLibrary.load_asset(animation_path)
                if animation is not None and animation.get_class().get_name() in {"AnimSequence", "AnimSequenceBase"}:
                    document["animation_sequences"].append(_animation_sequence(unreal, animation_path, animation))
                    exported_sequences.add(animation_path)
        elif class_name in {"AnimBlueprint", "AnimationBlueprint"}:
            document["animation_blueprints"].append(_animation_blueprint(unreal, object_path, asset))
        else:
            raise ValueError(f"Unsupported Unreal animation asset class: {class_name} ({object_path})")
    if destination:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def export_selected_animation_assets(destination: str = "") -> dict[str, Any]:
    import unreal

    selected = [str(value) for value in unreal.EditorUtilityLibrary.get_selected_asset_data()]
    paths = []
    for value in selected:
        # AssetData string formatting varies by engine minor; the package-name API is stable.
        try:
            data = unreal.EditorUtilityLibrary.get_selected_asset_data()[len(paths)]
            paths.append(str(data.get_soft_object_path()))
        except Exception:
            paths.append(value)
    return export_animation_assets(paths, destination)


def _animation_sequence(unreal: Any, object_path: str, asset: Any) -> dict[str, Any]:
    duration = _call_or_property(asset, "get_play_length", "sequence_length", 1.0)
    frames = int(_property(asset, "number_of_sampled_keys", _property(asset, "number_of_sampled_frames", 0)) or 0)
    sample_rate = float(frames / duration) if frames and duration else 30.0
    return {
        "name": asset.get_name(), "object_path": object_path,
        "skeleton": _object_path(_property(asset, "skeleton", None)),
        "duration": float(duration or 1.0), "sample_rate": sample_rate,
        "loop": bool(_property(asset, "loop", True)),
        "enable_root_motion": bool(_property(asset, "enable_root_motion", False)),
        "curves": _curve_names(unreal, asset), "events": _notify_events(asset),
    }


def _blend_space(unreal: Any, object_path: str, asset: Any, class_name: str) -> dict[str, Any]:
    dimensions = 1 if class_name == "BlendSpace1D" else 2
    axes = []
    for index in range(dimensions):
        parameter = _property(asset, f"blend_parameter_{'x' if index == 0 else 'y'}", None)
        axes.append({
            "name": str(_property(parameter, "display_name", f"Axis {index + 1}")),
            "parameter": str(_property(parameter, "display_name", f"axis_{index + 1}")),
            "minimum": float(_property(parameter, "min", 0.0)), "maximum": float(_property(parameter, "max", 1.0)),
            "grid_divisions": int(_property(parameter, "grid_num", 4)),
            "wrap": bool(_property(parameter, "wrap_input", False)),
        })
    samples = []
    for index, sample in enumerate(_property(asset, "sample_data", []) or []):
        animation = _property(sample, "animation", None); point = _property(sample, "sample_value", None)
        samples.append({
            "id": f"sample_{index}", "animation": _object_path(animation),
            "position": [float(_property(point, "x", 0.0)), float(_property(point, "y", 0.0))][:dimensions],
            "rate_scale": float(_property(sample, "rate_scale", 1.0)),
        })
    return {"name": asset.get_name(), "object_path": object_path, "type": class_name, "dimensions": dimensions, "skeleton": _object_path(_property(asset, "skeleton", None)), "axes": axes, "samples": samples}


def _animation_blueprint(unreal: Any, object_path: str, asset: Any) -> dict[str, Any]:
    nodes = []
    try:
        graphs = unreal.BlueprintEditorLibrary.get_all_graphs(asset)
    except Exception:
        graphs = []
    for graph in graphs or []:
        for node in _property(graph, "nodes", []) or []:
            nodes.append({
                "id": str(_property(node, "node_guid", "")), "name": str(_call_or_property(node, "get_node_title", "node_comment", node.get_name())),
                "type": node.get_class().get_name(), "graph": graph.get_name(),
            })
    variables = {}
    try:
        for name in unreal.BlueprintEditorLibrary.get_blueprint_variable_list(asset) or []:
            variables[str(name)] = {"type": "float", "default": 0.0, "source_type_requires_review": True}
    except Exception:
        pass
    return {
        "name": asset.get_name(), "object_path": object_path,
        "skeleton": _object_path(_property(asset, "target_skeleton", None)),
        "variables": variables, "state_machines": [], "nodes": nodes,
        "export_note": "State transition rules that are not exposed by this Unreal version remain preserved as graph node metadata.",
    }


def _curve_names(unreal: Any, asset: Any) -> list[dict[str, str]]:
    try:
        names = unreal.AnimationLibrary.get_animation_curve_names(asset, unreal.RawCurveTrackTypes.RCT_FLOAT)
        return [{"name": str(value), "type": "float"} for value in names or []]
    except Exception:
        return []


def _notify_events(asset: Any) -> list[dict[str, Any]]:
    result = []
    for index, notify in enumerate(_property(asset, "notifies", []) or []):
        result.append({"name": str(_property(notify, "notify_name", f"Notify {index}")), "time": float(_call_or_property(notify, "get_time", "time", 0.0))})
    return result


def _property(value: Any, name: str, default: Any) -> Any:
    if value is None:
        return default
    try:
        return value.get_editor_property(name)
    except Exception:
        return getattr(value, name, default)


def _call_or_property(value: Any, method: str, prop: str, default: Any) -> Any:
    callback = getattr(value, method, None)
    if callable(callback):
        try:
            return callback()
        except Exception:
            pass
    return _property(value, prop, default)


def _object_path(value: Any) -> str:
    if value is None:
        return ""
    callback = getattr(value, "get_path_name", None)
    return str(callback() if callable(callback) else value)


__all__ = ["export_animation_assets", "export_selected_animation_assets"]
