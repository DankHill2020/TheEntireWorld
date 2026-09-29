"""Portable procedural shader graphs, presets, validation, and preview baking."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
from typing import Any

import numpy as np


PROCEDURAL_SHADER_SCHEMA = "tech_connector.procedural_shader_graph.v1"


@dataclass(frozen=True)
class ShaderNodeSpec:
    key: str
    category: str
    output_type: str
    inputs: tuple[str, ...]
    cost: int
    description: str
    portable: bool = True


NODE_SPECS = {
    item.key: item for item in (
        ShaderNodeSpec("uv", "Coordinates", "vector2", (), 0, "Mesh UV coordinates."),
        ShaderNodeSpec("position", "Coordinates", "vector3", (), 0, "Object or world position."),
        ShaderNodeSpec("time", "Animation", "float", (), 0, "Timeline time in seconds."),
        ShaderNodeSpec("constant", "Input", "dynamic", (), 0, "Scalar, vector, or color constant."),
        ShaderNodeSpec("transform2d", "Coordinates", "vector2", ("coordinate",), 4, "Scale, rotate, and offset 2D coordinates."),
        ShaderNodeSpec("panner", "Coordinates", "vector2", ("coordinate", "time"), 2, "Animate coordinates at a controlled speed."),
        ShaderNodeSpec("linear_gradient", "Gradient", "float", ("coordinate",), 2, "Linear U/V or arbitrary-axis gradient."),
        ShaderNodeSpec("radial_gradient", "Gradient", "float", ("coordinate",), 6, "Radial gradient with controllable center and falloff."),
        ShaderNodeSpec("angular_gradient", "Gradient", "float", ("coordinate",), 7, "Polar angle normalized to zero through one."),
        ShaderNodeSpec("ramp", "Gradient", "color4", ("value",), 8, "Artist-authored float or color ramp."),
        ShaderNodeSpec("checker", "Pattern", "float", ("coordinate",), 5, "Tileable checker pattern."),
        ShaderNodeSpec("brick", "Pattern", "float", ("coordinate",), 9, "Offset brick bond with controllable mortar."),
        ShaderNodeSpec("dots", "Pattern", "float", ("coordinate",), 7, "Repeating circular dot field."),
        ShaderNodeSpec("hexagons", "Pattern", "float", ("coordinate",), 11, "Repeating hexagonal cell field."),
        ShaderNodeSpec("wave", "Pattern", "float", ("coordinate", "time"), 6, "Sine, saw, triangle, or rings."),
        ShaderNodeSpec("value_noise", "Noise", "float", ("coordinate",), 24, "Deterministic tile-friendly value noise."),
        ShaderNodeSpec("gradient_noise", "Noise", "float", ("coordinate",), 38, "Smooth Perlin-style gradient noise."),
        ShaderNodeSpec("voronoi", "Noise", "float", ("coordinate",), 48, "Worley/Voronoi nearest-cell distance."),
        ShaderNodeSpec("fbm", "Fractal", "float", ("coordinate",), 35, "Fractional Brownian motion with bounded octaves."),
        ShaderNodeSpec("turbulence", "Fractal", "float", ("coordinate",), 38, "Absolute-value multi-octave turbulence."),
        ShaderNodeSpec("ridged", "Fractal", "float", ("coordinate",), 42, "Ridged multifractal noise."),
        ShaderNodeSpec("add", "Math", "dynamic", ("a", "b"), 1, "Add values."),
        ShaderNodeSpec("subtract", "Math", "dynamic", ("a", "b"), 1, "Subtract values."),
        ShaderNodeSpec("multiply", "Math", "dynamic", ("a", "b"), 1, "Multiply values."),
        ShaderNodeSpec("power", "Math", "dynamic", ("value", "exponent"), 3, "Raise a value to a power."),
        ShaderNodeSpec("clamp", "Math", "dynamic", ("value",), 2, "Clamp to an authored range."),
        ShaderNodeSpec("smoothstep", "Mask", "float", ("value",), 3, "Create an antialiased threshold mask."),
        ShaderNodeSpec("remap", "Math", "dynamic", ("value",), 4, "Remap one numeric range to another."),
        ShaderNodeSpec("invert", "Math", "dynamic", ("value",), 1, "One minus the input."),
        ShaderNodeSpec("mix", "Layer", "dynamic", ("a", "b", "factor"), 3, "Blend two values with a mask."),
        ShaderNodeSpec("overlay", "Layer", "color4", ("a", "b"), 6, "Overlay compositing blend mode."),
        ShaderNodeSpec("hsv_adjust", "Color", "color4", ("color",), 12, "Adjust hue, saturation, and value."),
        ShaderNodeSpec("fresnel", "Surface", "float", (), 5, "View-angle edge mask."),
        ShaderNodeSpec("normal_from_height", "Surface", "vector3", ("height",), 10, "Derive a tangent-space normal from height."),
        ShaderNodeSpec("triplanar", "Projection", "color4", ("position", "normal"), 30, "Blend three axis projections without authored UVs."),
    )
}


def shader_node_catalog() -> dict[str, dict[str, Any]]:
    return {
        key: {
            "key": spec.key, "category": spec.category, "output_type": spec.output_type,
            "inputs": list(spec.inputs), "cost": spec.cost, "description": spec.description,
            "portable": spec.portable,
        }
        for key, spec in NODE_SPECS.items()
    }


def normalize_procedural_shader_graph(payload: dict[str, Any]) -> dict[str, Any]:
    graph = dict(payload or {})
    nodes = []
    seen: set[str] = set()
    for index, raw in enumerate(graph.get("nodes") or []):
        node = dict(raw or {})
        node_id = str(node.get("id") or f"node_{index}")
        if node_id in seen:
            raise ValueError(f"Duplicate procedural shader node id: {node_id}")
        seen.add(node_id)
        node_type = str(node.get("type") or "constant")
        nodes.append({
            "id": node_id, "type": node_type,
            "inputs": dict(node.get("inputs") or {}),
            "parameters": dict(node.get("parameters") or {}),
            "label": str(node.get("label") or NODE_SPECS.get(node_type, ShaderNodeSpec(node_type, "Unknown", "dynamic", (), 0, "")).description),
        })
    return {
        "schema": PROCEDURAL_SHADER_SCHEMA,
        "name": str(graph.get("name") or "Procedural Material"),
        "nodes": nodes,
        "outputs": dict(graph.get("outputs") or {}),
        "parameters": dict(graph.get("parameters") or {}),
        "metadata": dict(graph.get("metadata") or {}),
    }


def validate_procedural_shader_graph(payload: dict[str, Any], *, maximum_cost: int = 512) -> dict[str, Any]:
    graph = normalize_procedural_shader_graph(payload)
    nodes = {node["id"]: node for node in graph["nodes"]}
    errors: list[str] = []
    warnings: list[str] = []
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    cost = 0
    for node in graph["nodes"]:
        spec = NODE_SPECS.get(node["type"])
        if spec is None:
            errors.append(f"Node '{node['id']}' has unknown type '{node['type']}'.")
            continue
        multiplier = 1
        if node["type"] in {"fbm", "turbulence", "ridged"}:
            octaves = max(1, min(12, int(node["parameters"].get("octaves", 5))))
            multiplier = octaves
            if octaves > 8:
                warnings.append(f"Node '{node['id']}' uses {octaves} octaves; consider baking for real-time use.")
        cost += spec.cost * multiplier
        for input_name, value in node["inputs"].items():
            reference = _reference_id(value)
            if reference:
                if reference not in nodes:
                    errors.append(f"Node '{node['id']}' input '{input_name}' references unknown node '{reference}'.")
                else:
                    dependencies[node["id"]].add(reference)
    for output_name, value in graph["outputs"].items():
        reference = _reference_id(value)
        if reference and reference not in nodes:
            errors.append(f"Output '{output_name}' references unknown node '{reference}'.")
    cycle = _find_cycle(dependencies)
    if cycle:
        errors.append("Procedural shader graph contains a cycle: " + " -> ".join(cycle))
    if cost > maximum_cost:
        warnings.append(f"Estimated shader cost {cost} exceeds interactive budget {maximum_cost}.")
    return {
        "schema": "tech_connector.procedural_shader_validation.v1",
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "estimated_cost": cost,
        "maximum_cost": maximum_cost,
        "within_budget": cost <= maximum_cost,
        "node_count": len(nodes),
        "graph": graph,
    }


def compile_procedural_shader_graph(payload: dict[str, Any], *, target: str = "glsl") -> dict[str, Any]:
    validation = validate_procedural_shader_graph(payload)
    if not validation["valid"]:
        return {"schema": "tech_connector.procedural_shader_compile.v1", "compiled": False,
                "target": target, "diagnostics": validation["errors"], "source": "", "validation": validation}
    graph = validation["graph"]
    target_key = str(target).lower()
    if target_key not in {"glsl", "hlsl", "materialx"}:
        raise ValueError(f"Unknown procedural shader target: {target}")
    if target_key == "materialx":
        source = _compile_materialx(graph)
    else:
        source = _compile_code(graph, target_key)
    return {
        "schema": "tech_connector.procedural_shader_compile.v1", "compiled": True,
        "runtime_executable": False,
        "requires_backend_lowering": True,
        "target": target_key,
        "diagnostics": validation["warnings"] + ["Portable source requires target-native node-library lowering before runtime execution."],
        "source": source,
        "fingerprint": hashlib.sha256(source.encode("utf-8")).hexdigest(), "validation": validation,
    }


_QT_NATIVE_NODE_TYPES = frozenset({
    "uv", "time", "constant", "transform2d", "panner", "linear_gradient", "radial_gradient",
    "angular_gradient", "ramp", "checker", "brick", "dots", "hexagons", "wave", "value_noise",
    "gradient_noise", "voronoi", "fbm", "turbulence", "ridged", "add", "subtract", "multiply",
    "power", "clamp", "smoothstep", "remap", "invert", "mix", "overlay",
})


def lower_qt_quick3d_shader(payload: dict[str, Any], *, cache_root: str | Path | None = None) -> dict[str, Any]:
    """Lower a supported graph into a live Qt Quick 3D CustomMaterial fragment shader."""
    validation = validate_procedural_shader_graph(payload)
    blockers = list(validation["errors"])
    graph = validation["graph"]
    unsupported = sorted({node["type"] for node in graph["nodes"] if node["type"] not in _QT_NATIVE_NODE_TYPES})
    if unsupported:
        blockers.append("qt_native_unsupported_nodes: " + ", ".join(unsupported))
    if blockers:
        return {
            "schema": "tech_connector.qt_procedural_shader.v1", "native_executable": False,
            "blockers": blockers, "unsupported_nodes": unsupported, "fallback": "cpu_baked_preview",
            "validation": validation,
        }
    source = _compile_qt_quick3d_fragment(graph)
    fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()
    destination = Path(cache_root) if cache_root is not None else Path(tempfile.gettempdir()) / "tech_connector" / "shader_cache"
    destination.mkdir(parents=True, exist_ok=True)
    shader_path = destination / f"tc_procedural_{fingerprint[:24]}.frag"
    cache_hit = shader_path.is_file() and shader_path.read_text(encoding="utf-8") == source
    if not cache_hit:
        temporary = destination / f".{shader_path.name}.tmp"
        temporary.write_text(source, encoding="utf-8")
        temporary.replace(shader_path)
    manifest_path = destination / f"tc_procedural_{fingerprint[:24]}.json"
    manifest = {
        "schema": "tech_connector.qt_procedural_shader_cache.v1", "fingerprint": fingerprint,
        "shader_path": str(shader_path), "graph_name": graph["name"],
        "estimated_cost": validation["estimated_cost"], "node_count": validation["node_count"],
        "backend_compilation": "qt_quick3d_rhi_deferred", "cache_hit": cache_hit,
    }
    if not manifest_path.is_file():
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "schema": "tech_connector.qt_procedural_shader.v1", "native_executable": True,
        "gpu_execution": True,
        "pipeline_qualification": "deferred_to_first_rhi_draw",
        "blockers": [], "unsupported_nodes": [], "fallback": "", "source": source,
        "fingerprint": fingerprint, "shader_path": str(shader_path), "manifest_path": str(manifest_path),
        "cache_hit": cache_hit, "backend_compilation": "qt_quick3d_rhi_deferred",
        "validation": validation,
    }


def render_procedural_preview(payload: dict[str, Any], *, width: int = 256, height: int = 256,
                              time_seconds: float = 0.0) -> tuple[np.ndarray, dict[str, Any]]:
    validation = validate_procedural_shader_graph(payload)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    graph = validation["graph"]
    width, height = max(1, min(2048, int(width))), max(1, min(2048, int(height)))
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    uv = np.stack(((xx + 0.5) / width, (yy + 0.5) / height), axis=-1)
    values: dict[str, np.ndarray] = {}
    nodes = {node["id"]: node for node in graph["nodes"]}

    def evaluate(node_id: str) -> np.ndarray:
        if node_id in values:
            return values[node_id]
        node = nodes[node_id]
        kind, params, inputs = node["type"], node["parameters"], node["inputs"]
        get = lambda name, default=0.0: _resolve_preview_value(inputs.get(name, default), evaluate, uv.shape[:2])
        if kind == "uv": result = uv
        elif kind == "time": result = _full(uv.shape[:2], time_seconds)
        elif kind == "constant": result = _full(uv.shape[:2], params.get("value", 0.0))
        elif kind in {"transform2d", "panner"}:
            coord = get("coordinate", {"node": _first_node_of_type(nodes, "uv")})
            scale = np.asarray(params.get("scale", [1.0, 1.0]), dtype=np.float32)
            offset = np.asarray(params.get("offset", [0.0, 0.0]), dtype=np.float32)
            result = coord * scale
            if kind == "transform2d" and float(params.get("rotation_degrees", 0.0)):
                angle = math.radians(float(params.get("rotation_degrees", 0.0))); cosine, sine = math.cos(angle), math.sin(angle); centered = result - 0.5
                result = np.stack((centered[..., 0] * cosine - centered[..., 1] * sine, centered[..., 0] * sine + centered[..., 1] * cosine), axis=-1) + 0.5
            result = result + offset
            if kind == "panner": result = result + np.asarray(params.get("speed", [0.1, 0.0])) * get("time", time_seconds)[..., None]
        elif kind in {"linear_gradient", "radial_gradient", "angular_gradient"}:
            coord = get("coordinate", {"node": _first_node_of_type(nodes, "uv")})
            centered = coord - np.asarray(params.get("center", [0.5, 0.5]))
            if kind == "linear_gradient":
                axis = np.asarray(params.get("axis", [1.0, 0.0]), dtype=np.float32); axis /= max(1e-6, float(np.linalg.norm(axis)))
                result = np.clip(np.sum(centered * axis, axis=-1) + 0.5, 0.0, 1.0)
            elif kind == "radial_gradient": result = np.clip(np.linalg.norm(centered, axis=-1) / max(1e-6, float(params.get("radius", 0.5))), 0.0, 1.0)
            else: result = (np.arctan2(centered[..., 1], centered[..., 0]) / (2.0 * math.pi) + 1.0) % 1.0
        elif kind == "ramp": result = _evaluate_ramp(get("value"), params.get("points"))
        elif kind in {"checker", "brick", "dots", "hexagons"}:
            coord = get("coordinate", {"node": _first_node_of_type(nodes, "uv")}) * float(params.get("scale", 8.0))
            if kind == "checker": result = ((np.floor(coord[..., 0]) + np.floor(coord[..., 1])) % 2.0).astype(np.float32)
            elif kind == "brick":
                row = np.floor(coord[..., 1]); shifted_x = coord[..., 0] + (row % 2.0) * float(params.get("offset", 0.5)); local_x = np.mod(shifted_x, 1.0); local_y = np.mod(coord[..., 1], 1.0); mortar = float(params.get("mortar", 0.06)); result = ((local_x > mortar) & (local_y > mortar)).astype(np.float32)
            elif kind == "dots":
                local = np.mod(coord, 1.0) - 0.5; result = (np.linalg.norm(local, axis=-1) <= float(params.get("radius", 0.28))).astype(np.float32)
            else:
                qx = np.abs(np.mod(coord[..., 0], 1.5) - 0.75); qy = np.abs(np.mod(coord[..., 1] + (np.floor(coord[..., 0] / 1.5) % 2.0) * 0.5, 1.0) - 0.5); result = np.clip(1.0 - np.maximum(qx / 0.75, qy + qx * 0.35) / 0.62, 0.0, 1.0)
        elif kind == "wave":
            coord = get("coordinate", {"node": _first_node_of_type(nodes, "uv")}); frequency = float(params.get("frequency", 8.0))
            phase = float(params.get("phase", 0.0)) + time_seconds * float(params.get("speed", 0.0))
            signal = (np.linalg.norm(coord - 0.5, axis=-1) if params.get("mode") == "rings" else coord[..., int(params.get("axis", 0))]) * frequency + phase
            result = np.sin(signal * 2.0 * math.pi) * 0.5 + 0.5
        elif kind in {"value_noise", "gradient_noise", "voronoi", "fbm", "turbulence", "ridged"}:
            coord = get("coordinate", {"node": _first_node_of_type(nodes, "uv")}) * float(params.get("scale", 5.0))
            if kind == "voronoi": result = _voronoi(coord, int(params.get("seed", 0)))
            elif kind in {"fbm", "turbulence", "ridged"}: result = _fractal(coord, params, kind)
            elif kind == "gradient_noise": result = _gradient_noise(coord, int(params.get("seed", 0)))
            else: result = _value_noise(coord, int(params.get("seed", 0)))
        elif kind in {"add", "subtract", "multiply", "power", "mix", "overlay"}:
            a, b = get("a"), get("b")
            if kind == "add": result = a + b
            elif kind == "subtract": result = a - b
            elif kind == "multiply": result = a * b
            elif kind == "power": result = np.power(np.maximum(0.0, get("value", a)), get("exponent", b))
            elif kind == "mix": result = _mix(a, b, get("factor", 0.5))
            else: result = np.where(a <= 0.5, 2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b))
        elif kind in {"clamp", "smoothstep", "remap", "invert"}:
            value = get("value")
            if kind == "invert": result = 1.0 - value
            elif kind == "clamp": result = np.clip(value, float(params.get("minimum", 0.0)), float(params.get("maximum", 1.0)))
            elif kind == "remap":
                low, high = float(params.get("input_min", 0.0)), float(params.get("input_max", 1.0))
                result = (value - low) / max(1e-6, high - low) * (float(params.get("output_max", 1.0)) - float(params.get("output_min", 0.0))) + float(params.get("output_min", 0.0))
            else:
                low, high = float(params.get("edge0", 0.25)), float(params.get("edge1", 0.75)); t = np.clip((value - low) / max(1e-6, high - low), 0.0, 1.0); result = t * t * (3.0 - 2.0 * t)
        else: result = _full(uv.shape[:2], [1.0, 0.0, 1.0, 1.0])
        values[node_id] = np.asarray(result, dtype=np.float32)
        return values[node_id]

    output_ref = _reference_id(graph["outputs"].get("base_color")) or next(reversed(nodes), "")
    result = evaluate(output_ref) if output_ref else _full(uv.shape[:2], [0.5, 0.5, 0.5, 1.0])
    rgba = _as_rgba(result)
    receipt = {
        "schema": "tech_connector.procedural_shader_preview.v1", "width": width, "height": height,
        "time_seconds": float(time_seconds), "estimated_cost": validation["estimated_cost"],
        "within_budget": validation["within_budget"], "fallback": "cpu_baked_preview",
    }
    return np.clip(rgba * 255.0, 0, 255).astype(np.uint8), receipt


def procedural_shader_presets() -> dict[str, dict[str, Any]]:
    def graph(name: str, nodes: list[dict[str, Any]], output: str) -> dict[str, Any]:
        return {"schema": PROCEDURAL_SHADER_SCHEMA, "name": name, "nodes": nodes, "outputs": {"base_color": {"node": output}}}
    uv = {"id": "uv", "type": "uv"}
    return {
        "sunset_ramp": graph("Sunset Ramp", [uv, {"id": "gradient", "type": "linear_gradient", "inputs": {"coordinate": {"node": "uv"}}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "gradient"}}, "parameters": {"points": [[0, [0.03, 0.01, 0.12, 1]], [0.45, [0.85, 0.08, 0.18, 1]], [1, [1, 0.72, 0.18, 1]]]}}], "color"),
        "fractal_marble": graph("Fractal Marble", [uv, {"id": "noise", "type": "fbm", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"scale": 5, "octaves": 6, "lacunarity": 2.1, "gain": 0.52}}, {"id": "veins", "type": "ramp", "inputs": {"value": {"node": "noise"}}, "parameters": {"points": [[0, [0.02, 0.025, 0.04, 1]], [0.48, [0.08, 0.12, 0.18, 1]], [0.55, [0.8, 0.88, 0.95, 1]], [1, [0.05, 0.07, 0.1, 1]]]}}], "veins"),
        "lava": graph("Animated Lava", [uv, {"id": "flow", "type": "panner", "inputs": {"coordinate": {"node": "uv"}, "time": {"node": "time"}}, "parameters": {"speed": [0.04, -0.08]}}, {"id": "time", "type": "time"}, {"id": "crust", "type": "ridged", "inputs": {"coordinate": {"node": "flow"}}, "parameters": {"scale": 4, "octaves": 5}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "crust"}}, "parameters": {"points": [[0, [0.01, 0, 0, 1]], [0.4, [0.25, 0.01, 0, 1]], [0.7, [1, 0.08, 0, 1]], [1, [1, 0.8, 0.05, 1]]]}}], "color"),
        "electric_voronoi": graph("Electric Cells", [uv, {"id": "cells", "type": "voronoi", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"scale": 10}}, {"id": "edge", "type": "smoothstep", "inputs": {"value": {"node": "cells"}}, "parameters": {"edge0": 0.02, "edge1": 0.18}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "edge"}}, "parameters": {"points": [[0, [0, 0.9, 1, 1]], [0.3, [0.1, 0.05, 0.5, 1]], [1, [0.005, 0.005, 0.02, 1]]]}}], "color"),
        "water_ripples": graph("Water Ripples", [uv, {"id": "rings", "type": "wave", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"mode": "rings", "frequency": 12}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "rings"}}, "parameters": {"points": [[0, [0.01, 0.08, 0.12, 1]], [0.5, [0.02, 0.35, 0.48, 1]], [1, [0.45, 0.9, 1, 1]]]}}], "color"),
        "clouds": graph("Layered Clouds", [uv, {"id": "cloud", "type": "turbulence", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"scale": 3, "octaves": 7, "gain": 0.58}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "cloud"}}, "parameters": {"points": [[0, [0.08, 0.16, 0.32, 1]], [0.52, [0.45, 0.62, 0.78, 1]], [0.72, [0.95, 0.97, 1, 1]], [1, [1, 1, 1, 1]]]}}], "color"),
        "brick_wall": graph("Procedural Brick", [uv, {"id": "brick", "type": "brick", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"scale": 7, "mortar": 0.075}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "brick"}}, "parameters": {"points": [[0, [0.12, 0.11, 0.1, 1]], [0.48, [0.18, 0.17, 0.16, 1]], [0.52, [0.42, 0.07, 0.025, 1]], [1, [0.75, 0.2, 0.06, 1]]]}}], "color"),
        "hologram_grid": graph("Hologram Grid", [uv, {"id": "grid", "type": "hexagons", "inputs": {"coordinate": {"node": "uv"}}, "parameters": {"scale": 14}}, {"id": "color", "type": "ramp", "inputs": {"value": {"node": "grid"}}, "parameters": {"points": [[0, [0.005, 0.01, 0.04, 0.25]], [0.72, [0.02, 0.18, 0.32, 0.7]], [1, [0.1, 0.95, 1, 1]]]}}], "color"),
    }


def _reference_id(value: Any) -> str:
    if isinstance(value, dict): return str(value.get("node") or value.get("node_id") or "")
    if isinstance(value, str) and value.startswith("@"): return value[1:]
    return ""


def _find_cycle(dependencies: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set(); active: list[str] = []
    def visit(node: str) -> list[str]:
        if node in active: return active[active.index(node):] + [node]
        if node in visited: return []
        active.append(node)
        for dependency in dependencies.get(node, ()): 
            cycle = visit(dependency)
            if cycle: return cycle
        active.pop(); visited.add(node); return []
    for node in dependencies:
        cycle = visit(node)
        if cycle: return cycle
    return []


def _first_node_of_type(nodes: dict[str, dict[str, Any]], kind: str) -> str:
    return next((node_id for node_id, node in nodes.items() if node["type"] == kind), "")


def _full(shape: tuple[int, int], value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    return np.broadcast_to(array, shape + array.shape).copy()


def _resolve_preview_value(value: Any, evaluate: Any, shape: tuple[int, int]) -> np.ndarray:
    reference = _reference_id(value)
    return evaluate(reference) if reference else _full(shape, value)


def _hash2(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    return np.mod(np.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453, 1.0).astype(np.float32)


def _value_noise(p: np.ndarray, seed: int = 0) -> np.ndarray:
    cell = np.floor(p); fraction = p - cell; smooth = fraction * fraction * (3.0 - 2.0 * fraction)
    x, y = cell[..., 0], cell[..., 1]
    a, b = _hash2(x, y, seed), _hash2(x + 1, y, seed)
    c, d = _hash2(x, y + 1, seed), _hash2(x + 1, y + 1, seed)
    return (a * (1 - smooth[..., 0]) + b * smooth[..., 0]) * (1 - smooth[..., 1]) + (c * (1 - smooth[..., 0]) + d * smooth[..., 0]) * smooth[..., 1]


def _gradient_noise(p: np.ndarray, seed: int = 0) -> np.ndarray:
    cell = np.floor(p); fraction = p - cell; smooth = fraction * fraction * fraction * (fraction * (fraction * 6.0 - 15.0) + 10.0)
    dots = []
    for oy, ox in ((0, 0), (0, 1), (1, 0), (1, 1)):
        angle = _hash2(cell[..., 0] + ox, cell[..., 1] + oy, seed) * (2.0 * math.pi)
        gradient = np.stack((np.cos(angle), np.sin(angle)), axis=-1)
        dots.append(np.sum(gradient * (fraction - np.asarray([ox, oy], dtype=np.float32)), axis=-1))
    x0 = dots[0] * (1.0 - smooth[..., 0]) + dots[1] * smooth[..., 0]
    x1 = dots[2] * (1.0 - smooth[..., 0]) + dots[3] * smooth[..., 0]
    return np.clip((x0 * (1.0 - smooth[..., 1]) + x1 * smooth[..., 1]) * 0.7 + 0.5, 0.0, 1.0)


def _fractal(p: np.ndarray, params: dict[str, Any], kind: str) -> np.ndarray:
    octaves = max(1, min(12, int(params.get("octaves", 5)))); lacunarity = float(params.get("lacunarity", 2.0)); gain = float(params.get("gain", 0.5)); seed = int(params.get("seed", 0))
    result = np.zeros(p.shape[:2], dtype=np.float32); amplitude = 0.5; normalization = 0.0; coordinate = p
    for octave in range(octaves):
        noise = _value_noise(coordinate, seed + octave)
        if kind == "turbulence": noise = np.abs(noise * 2.0 - 1.0)
        elif kind == "ridged": noise = np.square(1.0 - np.abs(noise * 2.0 - 1.0))
        result += noise * amplitude; normalization += amplitude; amplitude *= gain; coordinate = coordinate * lacunarity
    return result / max(1e-6, normalization)


def _voronoi(p: np.ndarray, seed: int = 0) -> np.ndarray:
    cell = np.floor(p); fraction = p - cell; distance = np.full(p.shape[:2], 10.0, dtype=np.float32)
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            cx, cy = cell[..., 0] + ox, cell[..., 1] + oy
            point = np.stack((ox + _hash2(cx, cy, seed), oy + _hash2(cx, cy, seed + 17)), axis=-1)
            distance = np.minimum(distance, np.linalg.norm(point - fraction, axis=-1))
    return np.clip(distance, 0.0, 1.0)


def _evaluate_ramp(value: np.ndarray, points: Any) -> np.ndarray:
    authored = sorted(points or [[0, [0, 0, 0, 1]], [1, [1, 1, 1, 1]]], key=lambda item: float(item[0]))
    colors = [np.asarray(item[1], dtype=np.float32) for item in authored]
    result = np.broadcast_to(colors[0], value.shape + colors[0].shape).copy()
    for index in range(len(authored) - 1):
        start, end = float(authored[index][0]), float(authored[index + 1][0]); t = np.clip((value - start) / max(1e-6, end - start), 0, 1)
        mixed = colors[index] * (1 - t[..., None]) + colors[index + 1] * t[..., None]
        mask = (value >= start) & (value <= end); result[mask] = mixed[mask]
    result[value >= float(authored[-1][0])] = colors[-1]
    return result


def _mix(a: np.ndarray, b: np.ndarray, factor: np.ndarray) -> np.ndarray:
    while factor.ndim < max(a.ndim, b.ndim): factor = factor[..., None]
    return a * (1.0 - factor) + b * factor


def _as_rgba(value: np.ndarray) -> np.ndarray:
    if value.ndim == 2: return np.stack((value, value, value, np.ones_like(value)), axis=-1)
    if value.shape[-1] == 2: return np.concatenate((value, np.zeros(value.shape[:2] + (1,), dtype=np.float32), np.ones(value.shape[:2] + (1,), dtype=np.float32)), axis=-1)
    if value.shape[-1] == 3: return np.concatenate((value, np.ones(value.shape[:2] + (1,), dtype=np.float32)), axis=-1)
    return value[..., :4]


def _compile_code(graph: dict[str, Any], target: str) -> str:
    # The portable source is intentionally explicit; native backends replace helper calls with optimized libraries.
    lines = [f"// {PROCEDURAL_SHADER_SCHEMA} target={target}", "// Generated portable procedural material", "float4 tc_procedural(float2 uv, float3 position, float3 normal, float time) {"]
    for node in graph["nodes"]:
        lines.append(f"    // {node['id']}: {node['type']} | parameters={node['parameters']}")
    output = _reference_id(graph["outputs"].get("base_color"))
    lines.append(f"    return tc_eval_{output}(uv, position, normal, time);" if output else "    return float4(0.5, 0.5, 0.5, 1.0);")
    lines.append("}")
    if target == "glsl": lines = [line.replace("float4", "vec4").replace("float3", "vec3").replace("float2", "vec2") for line in lines]
    return "\n".join(lines)


def _compile_materialx(graph: dict[str, Any]) -> str:
    nodes = "\n".join(f'  <node name="{node["id"]}" category="{node["type"]}" />' for node in graph["nodes"])
    return f'<materialx version="1.38">\n<nodedef name="{graph["name"]}">\n{nodes}\n</nodedef>\n</materialx>'


def _compile_qt_quick3d_fragment(graph: dict[str, Any]) -> str:
    nodes = {node["id"]: node for node in graph["nodes"]}
    dependencies = {
        node_id: {_reference_id(value) for value in node["inputs"].values() if _reference_id(value)}
        for node_id, node in nodes.items()
    }
    order: list[str] = []
    visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visited: return
        for dependency in dependencies.get(node_id, ()): visit(dependency)
        visited.add(node_id); order.append(node_id)
    for node_id in nodes: visit(node_id)
    ramp_helpers = [_qt_ramp_function(nodes[node_id]) for node_id in order if nodes[node_id]["type"] == "ramp"]
    statements: list[str] = []
    for node_id in order:
        statements.extend(_qt_node_statements(nodes[node_id]))
    outputs = graph["outputs"]
    base = _qt_input(outputs.get("base_color"), "vec4(0.5, 0.5, 0.5, 1.0)")
    roughness = _qt_input(outputs.get("roughness"), "vec4(0.5)")
    metalness = _qt_input(outputs.get("metalness"), "vec4(0.0)")
    emission = _qt_input(outputs.get("emission"), "vec4(0.0)")
    opacity = _qt_input(outputs.get("opacity"), "vec4(1.0)")
    helpers = r"""
float tc_hash(vec2 p, float seed) { return fract(sin(dot(p, vec2(127.1, 311.7)) + seed * 74.7) * 43758.5453); }
float tc_value_noise(vec2 p, float seed) {
    vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(tc_hash(i,seed),tc_hash(i+vec2(1,0),seed),f.x),mix(tc_hash(i+vec2(0,1),seed),tc_hash(i+vec2(1),seed),f.x),f.y);
}
float tc_gradient_noise(vec2 p, float seed) {
    vec2 i=floor(p), f=fract(p), u=f*f*f*(f*(f*6.0-15.0)+10.0);
    vec2 g00=vec2(cos(tc_hash(i,seed)*6.2831853),sin(tc_hash(i,seed)*6.2831853));
    vec2 g10=vec2(cos(tc_hash(i+vec2(1,0),seed)*6.2831853),sin(tc_hash(i+vec2(1,0),seed)*6.2831853));
    vec2 g01=vec2(cos(tc_hash(i+vec2(0,1),seed)*6.2831853),sin(tc_hash(i+vec2(0,1),seed)*6.2831853));
    vec2 g11=vec2(cos(tc_hash(i+vec2(1),seed)*6.2831853),sin(tc_hash(i+vec2(1),seed)*6.2831853));
    return clamp(mix(mix(dot(g00,f),dot(g10,f-vec2(1,0)),u.x),mix(dot(g01,f-vec2(0,1)),dot(g11,f-vec2(1)),u.x),u.y)*0.7+0.5,0.0,1.0);
}
float tc_voronoi(vec2 p, float seed) {
    vec2 i=floor(p), f=fract(p); float d=10.0;
    for(int y=-1;y<=1;++y) for(int x=-1;x<=1;++x) { vec2 o=vec2(x,y); vec2 q=o+vec2(tc_hash(i+o,seed),tc_hash(i+o,seed+17.0))-f; d=min(d,length(q)); }
    return clamp(d,0.0,1.0);
}
float tc_fractal(vec2 p, float seed, int octaves, float lacunarity, float gain, int mode) {
    float sum=0.0, amp=0.5, norm=0.0;
    for(int octave=0;octave<12;++octave) { if(octave>=octaves) break; float n=tc_value_noise(p,seed+float(octave)); if(mode==1)n=abs(n*2.0-1.0); else if(mode==2)n=pow(1.0-abs(n*2.0-1.0),2.0); sum+=n*amp; norm+=amp; amp*=gain; p*=lacunarity; }
    return sum/max(norm,0.00001);
}
"""
    body = "\n".join("    " + statement for statement in statements)
    ramps = "\n".join(ramp_helpers)
    return f"""// {PROCEDURAL_SHADER_SCHEMA}\n// Generated executable Qt Quick 3D procedural fragment\n{helpers}\n{ramps}\nvoid MAIN()\n{{\n{body}\n    vec4 tcBase = {base};\n    BASE_COLOR = vec4(tcBase.rgb, tcBase.a * ({opacity}).x);\n    ROUGHNESS = clamp(({roughness}).x, 0.0, 1.0);\n    METALNESS = clamp(({metalness}).x, 0.0, 1.0);\n    EMISSIVE_COLOR = ({emission}).rgb;\n}}\n"""


def _qt_var(node_id: str) -> str:
    return "tc_" + re.sub(r"[^A-Za-z0-9_]", "_", str(node_id))


def _qt_float(value: Any, default: float = 0.0) -> str:
    try: result = float(value)
    except (TypeError, ValueError): result = float(default)
    if not math.isfinite(result): result = float(default)
    return f"{result:.9g}" + (".0" if float(result).is_integer() else "")


def _qt_vec(value: Any, size: int = 4) -> str:
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    defaults = [0.0, 0.0, 0.0, 1.0]
    values.extend(defaults[len(values):size])
    return f"vec{size}(" + ", ".join(_qt_float(values[index], defaults[index]) for index in range(size)) + ")"


def _qt_input(value: Any, default: str = "vec4(0.0)") -> str:
    reference = _reference_id(value)
    if reference: return _qt_var(reference)
    if value is None: return default
    if isinstance(value, (list, tuple)): return _qt_vec(value, 4)
    if isinstance(value, bool): return "vec4(1.0)" if value else "vec4(0.0)"
    if isinstance(value, (int, float)): return f"vec4({_qt_float(value)})"
    return default


def _qt_node_statements(node: dict[str, Any]) -> list[str]:
    kind, params, inputs = node["type"], node["parameters"], node["inputs"]
    var = _qt_var(node["id"])
    get = lambda name, default=None: _qt_input(inputs.get(name), _qt_input(default))
    uv_default = "vec4(UV0, 0.0, 1.0)"
    if kind == "uv": return [f"vec4 {var} = {uv_default};"]
    if kind == "time": return [f"vec4 {var} = vec4(tcTime);"]
    if kind == "constant": return [f"vec4 {var} = {_qt_input(params.get('value', 0.0))};"]
    if kind in {"transform2d", "panner"}:
        coord = get("coordinate", [0.0, 0.0, 0.0, 1.0]); scale = _qt_vec(params.get("scale", [1, 1]), 2); offset = _qt_vec(params.get("offset", [0, 0]), 2)
        lines = [f"vec2 {var}_uv = ({coord}).xy * {scale};"]
        if kind == "transform2d":
            angle = _qt_float(math.radians(float(params.get("rotation_degrees", 0.0)))); lines.append(f"{var}_uv = mat2(cos({angle}), -sin({angle}), sin({angle}), cos({angle})) * ({var}_uv - 0.5) + 0.5;")
        else:
            time_value = get("time", 0.0); speed = _qt_vec(params.get("speed", [0.1, 0]), 2); lines.append(f"{var}_uv += {speed} * ({time_value}).x;")
        lines.extend([f"{var}_uv += {offset};", f"vec4 {var} = vec4({var}_uv, 0.0, 1.0);"]); return lines
    if kind in {"linear_gradient", "radial_gradient", "angular_gradient"}:
        coord = get("coordinate", None) if "coordinate" in inputs else uv_default; center = _qt_vec(params.get("center", [0.5, 0.5]), 2)
        if kind == "linear_gradient": scalar = f"clamp(dot(({coord}).xy - {center}, normalize({_qt_vec(params.get('axis',[1,0]),2)})) + 0.5, 0.0, 1.0)"
        elif kind == "radial_gradient": scalar = f"clamp(length(({coord}).xy - {center}) / max({_qt_float(params.get('radius',0.5))},0.00001), 0.0, 1.0)"
        else: scalar = f"fract(atan(({coord}).y-{center}.y, ({coord}).x-{center}.x) / 6.2831853 + 1.0)"
        return [f"vec4 {var} = vec4({scalar});"]
    if kind == "ramp": return [f"vec4 {var} = {_qt_var('ramp_' + node['id'])}(({get('value')}).x);"]
    if kind in {"checker", "brick", "dots", "hexagons"}:
        coord = get("coordinate", None) if "coordinate" in inputs else uv_default; scale = _qt_float(params.get("scale", 8.0)); local = f"({coord}).xy * {scale}"
        if kind == "checker": scalar = f"mod(floor(({local}).x)+floor(({local}).y),2.0)"
        elif kind == "brick": scalar = f"step({_qt_float(params.get('mortar',0.06))},fract(({local}).x+mod(floor(({local}).y),2.0)*{_qt_float(params.get('offset',0.5))})) * step({_qt_float(params.get('mortar',0.06))},fract(({local}).y))"
        elif kind == "dots": scalar = f"1.0-step({_qt_float(params.get('radius',0.28))},length(fract({local})-0.5))"
        else: scalar = f"clamp(1.0-length(fract({local})-0.5)*1.8,0.0,1.0)"
        return [f"vec4 {var} = vec4({scalar});"]
    if kind == "wave":
        coord = get("coordinate", None) if "coordinate" in inputs else uv_default; frequency = _qt_float(params.get("frequency", 8.0)); phase = _qt_float(params.get("phase", 0.0)); speed = _qt_float(params.get("speed", 0.0)); signal = f"length(({coord}).xy-0.5)" if params.get("mode") == "rings" else f"({coord})[{max(0,min(1,int(params.get('axis',0))))}]"; return [f"vec4 {var} = vec4(sin(({signal}*{frequency}+{phase}+tcTime*{speed})*6.2831853)*0.5+0.5);"]
    if kind in {"value_noise", "gradient_noise", "voronoi", "fbm", "turbulence", "ridged"}:
        coord = get("coordinate", None) if "coordinate" in inputs else uv_default; p = f"({coord}).xy*{_qt_float(params.get('scale',5.0))}"; seed = _qt_float(params.get("seed",0))
        if kind == "value_noise": scalar = f"tc_value_noise({p},{seed})"
        elif kind == "gradient_noise": scalar = f"tc_gradient_noise({p},{seed})"
        elif kind == "voronoi": scalar = f"tc_voronoi({p},{seed})"
        else: scalar = f"tc_fractal({p},{seed},{max(1,min(12,int(params.get('octaves',5))))},{_qt_float(params.get('lacunarity',2.0))},{_qt_float(params.get('gain',0.5))},{0 if kind=='fbm' else (1 if kind=='turbulence' else 2)})"
        return [f"vec4 {var} = vec4({scalar});"]
    if kind in {"add", "subtract", "multiply", "power", "mix", "overlay"}:
        a, b = get("a", 0.0), get("b", 0.0)
        if kind == "add": expression = f"{a}+{b}"
        elif kind == "subtract": expression = f"{a}-{b}"
        elif kind == "multiply": expression = f"{a}*{b}"
        elif kind == "power": expression = f"pow(max({get('value',0.0)},vec4(0.0)),{get('exponent',1.0)})"
        elif kind == "mix": expression = f"mix({a},{b},clamp({get('factor',0.5)},0.0,1.0))"
        else: expression = f"mix(2.0*{a}*{b},1.0-2.0*(1.0-{a})*(1.0-{b}),step(vec4(0.5),{a}))"
        return [f"vec4 {var} = {expression};"]
    value = get("value", 0.0)
    if kind == "invert": expression = f"1.0-{value}"
    elif kind == "clamp": expression = f"clamp({value},vec4({_qt_float(params.get('minimum',0))}),vec4({_qt_float(params.get('maximum',1))}))"
    elif kind == "smoothstep": expression = f"smoothstep(vec4({_qt_float(params.get('edge0',0.25))}),vec4({_qt_float(params.get('edge1',0.75))}),{value})"
    else:
        low, high = _qt_float(params.get("input_min",0)), _qt_float(params.get("input_max",1)); out_low, out_high = _qt_float(params.get("output_min",0)), _qt_float(params.get("output_max",1)); expression = f"(({value}-vec4({low}))/max(vec4({high}-{low}),vec4(0.00001)))*({out_high}-{out_low})+{out_low}"
    return [f"vec4 {var} = {expression};"]


def _qt_ramp_function(node: dict[str, Any]) -> str:
    points = sorted(node["parameters"].get("points") or [[0,[0,0,0,1]],[1,[1,1,1,1]]], key=lambda item: float(item[0]))[:16]
    name = _qt_var("ramp_" + node["id"]); lines = [f"vec4 {name}(float t) {{", f"    vec4 result = {_qt_vec(points[0][1],4)};"]
    for index in range(len(points)-1):
        start, end = _qt_float(points[index][0]), _qt_float(points[index+1][0]); a, b = _qt_vec(points[index][1],4), _qt_vec(points[index+1][1],4); lines.append(f"    result = mix(result, mix({a}, {b}, smoothstep({start}, {end}, t)), step({start}, t));")
    lines.extend(["    return result;", "}"]); return "\n".join(lines)


__all__ = ["NODE_SPECS", "PROCEDURAL_SHADER_SCHEMA", "ShaderNodeSpec", "compile_procedural_shader_graph", "lower_qt_quick3d_shader",
           "normalize_procedural_shader_graph", "procedural_shader_presets", "render_procedural_preview",
           "shader_node_catalog", "validate_procedural_shader_graph"]
