"""Portable sparse blend shapes, in-betweens, masks, and corrective drivers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np

from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap, Vec3


SparseDeltas = dict[int, Vec3]


@dataclass(frozen=True)
class BlendShapeFrame:
    weight: float
    deltas: SparseDeltas

    def validated(self, vertex_count: int) -> "BlendShapeFrame":
        if not math.isfinite(float(self.weight)) or abs(float(self.weight)) <= 1.0e-12:
            raise ValueError("Blend-shape frame weight must be finite and nonzero.")
        normalized = _validated_deltas(self.deltas, vertex_count)
        return BlendShapeFrame(float(self.weight), normalized)


@dataclass(frozen=True)
class BlendShapeCorrectiveDriver:
    driver_id: str
    center: float = 1.0
    width: float = 0.2
    gain: float = 1.0
    mode: str = "add"

    def validated(self) -> "BlendShapeCorrectiveDriver":
        if not self.driver_id or self.width <= 0.0 or self.gain < 0.0:
            raise ValueError("Corrective drivers require an id, positive width, and nonnegative gain.")
        if self.mode not in {"add", "multiply", "replace"}:
            raise ValueError("Corrective driver mode must be add, multiply, or replace.")
        return self


@dataclass(frozen=True)
class BlendShapeTarget:
    target_id: str
    name: str
    frames: tuple[BlendShapeFrame, ...]
    weight: float = 0.0
    minimum: float = -1.0
    maximum: float = 1.0
    mask: DeformationWeightMap | None = None
    driver: BlendShapeCorrectiveDriver | None = None
    animation_keys: tuple[tuple[float, float], ...] = ()

    def validated(self, vertex_count: int) -> "BlendShapeTarget":
        if not self.target_id or not self.name or not self.frames:
            raise ValueError("A blend-shape target requires an id, name, and at least one frame.")
        if self.minimum > self.maximum:
            raise ValueError("Blend-shape minimum cannot exceed maximum.")
        frames = tuple(sorted((item.validated(vertex_count) for item in self.frames), key=lambda item: item.weight))
        if len({item.weight for item in frames}) != len(frames):
            raise ValueError(f"Blend-shape target {self.target_id} has duplicate in-between weights.")
        if self.mask is not None and len(self.mask.values) != vertex_count:
            raise ValueError(f"Blend-shape mask {self.target_id} must match the vertex count.")
        driver = self.driver.validated() if self.driver is not None else None
        keys = tuple(sorted((float(frame), float(value)) for frame, value in self.animation_keys))
        if any(not math.isfinite(value) for key in keys for value in key):
            raise ValueError("Blend-shape animation keys must be finite.")
        return BlendShapeTarget(
            self.target_id, self.name, frames, float(self.weight), float(self.minimum),
            float(self.maximum), self.mask, driver, keys,
        )


@dataclass
class BlendShapeTelemetry:
    active_targets: int = 0
    active_deltas: int = 0
    maximum_absolute_weight: float = 0.0
    resolved_weights: dict[str, float] = field(default_factory=dict)


def evaluate_blend_shape(
    upstream_positions: Sequence[Sequence[float]],
    targets: Sequence[BlendShapeTarget | Mapping[str, Any]],
    *,
    weights: Mapping[str, float] | None = None,
    driver_values: Mapping[str, float] | None = None,
    frame: float | None = None,
    telemetry: BlendShapeTelemetry | None = None,
) -> list[Vec3]:
    source = np.asarray(upstream_positions, dtype=np.float64).reshape((-1, 3))
    result = source.copy()
    stats = telemetry if telemetry is not None else BlendShapeTelemetry()
    stats.active_targets = stats.active_deltas = 0
    stats.maximum_absolute_weight = 0.0
    stats.resolved_weights.clear()
    for raw in targets:
        target = raw if isinstance(raw, BlendShapeTarget) else blend_shape_target_from_dict(raw)
        target = target.validated(len(source))
        value = resolve_blend_shape_weight(target, weights or {}, driver_values or {}, frame)
        stats.resolved_weights[target.target_id] = value
        stats.maximum_absolute_weight = max(stats.maximum_absolute_weight, abs(value))
        if abs(value) <= 1.0e-12:
            continue
        deltas = resolve_blend_shape_deltas(target, value)
        if not deltas:
            continue
        indices = np.fromiter(deltas, dtype=np.int64)
        offsets = np.asarray([deltas[index] for index in indices], dtype=np.float64)
        if target.mask is not None:
            offsets *= np.asarray([target.mask.values[index] for index in indices], dtype=np.float64)[:, None]
        result[indices] += offsets
        stats.active_targets += 1
        stats.active_deltas += len(indices)
    return [tuple(row) for row in result.tolist()]


def resolve_blend_shape_weight(target: BlendShapeTarget, weights: Mapping[str, float],
                               driver_values: Mapping[str, float], frame: float | None) -> float:
    value = float(weights.get(target.target_id, weights.get(target.name, target.weight)))
    if frame is not None and target.animation_keys:
        value = _sample_keys(target.animation_keys, float(frame))
    if target.driver is not None:
        driver = target.driver
        response = math.exp(-0.5 * ((float(driver_values.get(driver.driver_id, 0.0)) - driver.center) /
                                    driver.width) ** 2) * driver.gain
        value = response if driver.mode == "replace" else value * response if driver.mode == "multiply" else value + response
    return min(target.maximum, max(target.minimum, value))


def resolve_blend_shape_deltas(target: BlendShapeTarget, weight: float) -> SparseDeltas:
    """Resolve the already-weighted sparse delta field at an arbitrary in-between weight."""
    frames = list(target.frames)
    zero = BlendShapeFrame(0.0, {})
    points = sorted(frames + ([zero] if not any(abs(item.weight) <= 1.0e-12 for item in frames) else []),
                    key=lambda item: item.weight)
    if weight <= points[0].weight:
        reference = points[1] if points[0].weight == 0.0 and len(points) > 1 else points[0]
        return _scaled(reference.deltas, weight / reference.weight) if reference.weight else {}
    if weight >= points[-1].weight:
        reference = points[-2] if points[-1].weight == 0.0 and len(points) > 1 else points[-1]
        return _scaled(reference.deltas, weight / reference.weight) if reference.weight else {}
    for first, second in zip(points, points[1:]):
        if first.weight <= weight <= second.weight:
            amount = (weight - first.weight) / max(1.0e-12, second.weight - first.weight)
            return _lerp_sparse(first.deltas, second.deltas, amount)
    return {}


def attach_blend_shape_deformer(rig_graph: Any, mesh_id: str, vertex_count: int,
                                targets: Sequence[BlendShapeTarget], *,
                                deformer_id: str | None = None) -> str:
    validated = [item.validated(int(vertex_count)) for item in targets]
    if len({item.target_id for item in validated}) != len(validated):
        raise ValueError("Blend-shape target ids must be unique within a deformer.")
    return rig_graph.add_deformer(
        mesh_id, "blend_shape", deformer_id=deformer_id,
        settings={"schema": "tech_connector.blend_shape.v1", "vertex_count": int(vertex_count),
                  "targets": [blend_shape_target_to_dict(item) for item in validated],
                  "weights": {}, "driver_values": {}, "frame": None,
                  "export_policy": blend_shape_export_contract("portable")},
    )


def set_blend_shape_weights(rig_graph: Any, deformer_id: str, weights: Mapping[str, float], *,
                            driver_values: Mapping[str, float] | None = None,
                            frame: float | None = None) -> dict[str, Any]:
    deformer = (getattr(rig_graph, "deformers", {}) or {}).get(str(deformer_id))
    if deformer is None or str(deformer.get("type") or "") != "blend_shape":
        raise KeyError(f"Blend-shape deformer does not exist: {deformer_id}")
    settings = deformer.setdefault("settings", {})
    settings["weights"] = {str(key): float(value) for key, value in weights.items()}
    if driver_values is not None:
        settings["driver_values"] = {str(key): float(value) for key, value in driver_values.items()}
    if frame is not None:
        settings["frame"] = float(frame)
    return {"deformer_id": str(deformer_id), "weights": dict(settings["weights"]),
            "driver_values": dict(settings.get("driver_values") or {}), "frame": settings.get("frame")}


def blend_shape_target_to_dict(target: BlendShapeTarget) -> dict[str, Any]:
    value = target.validated(len(target.mask.values) if target.mask is not None else
                             1 + max((index for frame in target.frames for index in frame.deltas), default=-1))
    return {"target_id": value.target_id, "name": value.name, "weight": value.weight,
            "minimum": value.minimum, "maximum": value.maximum,
            "frames": [{"weight": item.weight, "deltas": {str(index): list(delta)
                        for index, delta in item.deltas.items()}} for item in value.frames],
            "mask": value.mask.to_dict() if value.mask is not None else None,
            "driver": asdict(value.driver) if value.driver is not None else None,
            "animation_keys": [list(item) for item in value.animation_keys]}


def blend_shape_target_from_dict(data: Mapping[str, Any]) -> BlendShapeTarget:
    raw = dict(data)
    return BlendShapeTarget(
        str(raw.get("target_id") or raw.get("name") or "target"), str(raw.get("name") or "Target"),
        tuple(BlendShapeFrame(float(item.get("weight", 1.0)),
              {int(index): tuple(float(axis) for axis in delta) for index, delta in
               dict(item.get("deltas") or {}).items()}) for item in raw.get("frames") or ()),
        float(raw.get("weight", 0.0)), float(raw.get("minimum", -1.0)), float(raw.get("maximum", 1.0)),
        DeformationWeightMap.from_dict(dict(raw["mask"])) if isinstance(raw.get("mask"), Mapping) else None,
        BlendShapeCorrectiveDriver(**dict(raw["driver"])) if isinstance(raw.get("driver"), Mapping) else None,
        tuple((float(item[0]), float(item[1])) for item in raw.get("animation_keys") or ()),
    )


def blend_shape_export_contract(destination: str = "portable") -> dict[str, Any]:
    target = str(destination or "portable").lower()
    mapping = {"maya": "blendShape targets, in-betweens, targetWeights, and driven keys",
               "blender": "shape keys, vertex groups, drivers, and FCurves",
               "houdini": "blendshapes SOP targets, masks, and CHOP/channel drivers",
               "unreal": "SkeletalMesh morph targets and animation curves",
               "unity": "SkinnedMeshRenderer blend shapes and AnimationClip curves",
               "usd": "UsdSkelBlendShape offsets, pointIndices, inbetweens, and animation weights",
               "fbx": "FBX blend-shape channels, target shapes, and weight animation",
               "gltf": "morph target POSITION deltas and animated weights",
               "portable": "TC sparse targets, masks, in-betweens, drivers, and animation keys"}
    return {"schema": "tech_connector.blend_shape_export.v1", "destination": target,
            "native_mapping": mapping.get(target, "morph targets or point cache"),
            "fallback_priority": ["native_blend_shape", "morph_bake", "point_cache"],
            "topology_must_match": True, "deformer_order_preserved": True}


_DESTINATION_CAPABILITIES = {
    "maya": {"sparse": True, "inbetweens": True, "masks": True, "drivers": True, "animation": True},
    "blender": {"sparse": False, "inbetweens": False, "masks": True, "drivers": True, "animation": True},
    "houdini": {"sparse": True, "inbetweens": True, "masks": False, "drivers": True, "animation": True},
    "unreal": {"sparse": True, "inbetweens": False, "masks": False, "drivers": False, "animation": True},
    "unity": {"sparse": False, "inbetweens": True, "masks": False, "drivers": False, "animation": True},
    "usd": {"sparse": True, "inbetweens": True, "masks": False, "drivers": False, "animation": True},
    "fbx": {"sparse": True, "inbetweens": True, "masks": False, "drivers": False, "animation": True},
    "gltf": {"sparse": True, "inbetweens": False, "masks": False, "drivers": False, "animation": True},
}


def build_blend_shape_destination_manifest(targets: Sequence[BlendShapeTarget], vertex_count: int,
                                           destination: str, *, deformer_id: str = "blend_shape") -> dict[str, Any]:
    """Build a deterministic host mapping plus a lossless TC sidecar for readback."""
    target = str(destination or "").lower()
    if target not in _DESTINATION_CAPABILITIES:
        raise ValueError(f"Unsupported blend-shape destination: {destination}")
    capabilities = dict(_DESTINATION_CAPABILITIES[target])
    validated = [item.validated(vertex_count) for item in targets]
    host_targets = []
    required_bakes = set()
    for item in validated:
        frames = []
        for shape in item.frames:
            deltas = dict(shape.deltas)
            if item.mask is not None and not capabilities["masks"]:
                deltas = {index: tuple(axis * item.mask.values[index] for axis in delta)
                          for index, delta in deltas.items()}
                required_bakes.add("preapply_target_mask")
            frames.append({"weight": shape.weight,
                           "channel": item.target_id if capabilities["inbetweens"] else
                                      f"{item.target_id}__w_{shape.weight:g}",
                           "indices": sorted(deltas),
                           "offsets": [list(deltas[index]) for index in sorted(deltas)]})
        if len(item.frames) > 1 and not capabilities["inbetweens"]:
            required_bakes.add("expand_inbetweens_to_channels")
        if item.driver is not None and not capabilities["drivers"]:
            required_bakes.add("bake_corrective_driver_curve")
        host_targets.append({"target_id": item.target_id, "name": item.name, "frames": frames,
                             "mask": item.mask.to_dict() if item.mask is not None and capabilities["masks"] else None,
                             "driver": asdict(item.driver) if item.driver is not None and capabilities["drivers"] else None,
                             "animation_keys": [list(key) for key in item.animation_keys],
                             "reconstruction": "native_inbetween" if capabilities["inbetweens"] else
                                               "piecewise_linear_channel_mix"})
    portable = blend_shape_payload(validated, vertex_count)
    result = {"schema": "tech_connector.blend_shape_destination.v1", "destination": target,
              "deformer_id": str(deformer_id), "vertex_count": int(vertex_count),
              "host_mapping": blend_shape_export_contract(target)["native_mapping"],
              "capabilities": capabilities, "host_targets": host_targets,
              "required_bakes": sorted(required_bakes), "portable_sidecar": portable,
              "qualification": {"status": "golden_contract_ready", "live_host_claimed": False,
                                "remaining_gates": ["live_import", "host_evaluation_readback", "animation_hash"]}}
    result["sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


def blend_shape_targets_from_destination_manifest(manifest: Mapping[str, Any], *,
                                                  expected_destination: str = "") -> tuple[BlendShapeTarget, ...]:
    data = dict(manifest)
    checksum = str(data.pop("sha256", ""))
    if str(data.get("schema") or "") != "tech_connector.blend_shape_destination.v1":
        raise ValueError("Unsupported blend-shape destination manifest.")
    if expected_destination and str(data.get("destination") or "") != str(expected_destination).lower():
        raise ValueError("Blend-shape destination manifest targets a different package.")
    if checksum:
        actual = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual != checksum:
            raise ValueError("Blend-shape destination manifest checksum does not match.")
    return blend_shape_targets_from_payload(
        dict(data.get("portable_sidecar") or {}), expected_vertex_count=int(data.get("vertex_count", 0))
    )


def blend_shape_payload(targets: Sequence[BlendShapeTarget], vertex_count: int) -> dict[str, Any]:
    data = {"schema": "tech_connector.blend_shape.v1", "vertex_count": int(vertex_count),
            "targets": [blend_shape_target_to_dict(item.validated(vertex_count)) for item in targets]}
    data["sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return data


def blend_shape_targets_from_payload(payload: Mapping[str, Any], *,
                                     expected_vertex_count: int | None = None) -> tuple[BlendShapeTarget, ...]:
    data = dict(payload)
    if str(data.get("schema") or "") != "tech_connector.blend_shape.v1":
        raise ValueError("Unsupported or missing blend-shape schema.")
    checksum = str(data.pop("sha256", ""))
    if checksum:
        actual = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual != checksum:
            raise ValueError("Blend-shape payload checksum does not match its receipt.")
    vertex_count = int(data.get("vertex_count", 0) or 0)
    if expected_vertex_count is not None and vertex_count != int(expected_vertex_count):
        raise ValueError(f"Blend shapes contain {vertex_count} vertices, but the target mesh has {expected_vertex_count}.")
    return tuple(blend_shape_target_from_dict(item).validated(vertex_count) for item in data.get("targets") or ())


def blend_shape_target_from_positions(target_id: str, name: str,
                                      base_positions: Sequence[Sequence[float]],
                                      target_positions: Sequence[Sequence[float]], *,
                                      weight: float = 1.0, epsilon: float = 1.0e-8,
                                      mask: DeformationWeightMap | None = None) -> BlendShapeTarget:
    if len(base_positions) != len(target_positions):
        raise ValueError("Blend-shape base and target topology must have matching vertex counts.")
    deltas: SparseDeltas = {}
    for index, (base, target) in enumerate(zip(base_positions, target_positions)):
        base_value = tuple(float(axis) for axis in base)
        target_value = tuple(float(axis) for axis in target)
        if len(base_value) != 3 or len(target_value) != 3:
            raise ValueError("Blend-shape positions must be three-dimensional.")
        delta = tuple(target_value[axis] - base_value[axis] for axis in range(3))
        if any(abs(axis) > float(epsilon) for axis in delta):
            deltas[index] = delta
    return BlendShapeTarget(str(target_id), str(name), (BlendShapeFrame(float(weight), deltas),), mask=mask).validated(
        len(base_positions)
    )


def _validated_deltas(deltas: Mapping[int, Sequence[float]], vertex_count: int) -> SparseDeltas:
    result = {}
    for raw_index, raw_delta in deltas.items():
        index = int(raw_index)
        value = tuple(float(axis) for axis in raw_delta)
        if not 0 <= index < vertex_count or len(value) != 3 or not all(math.isfinite(axis) for axis in value):
            raise ValueError(f"Invalid blend-shape delta at vertex {index}.")
        if any(abs(axis) > 1.0e-12 for axis in value):
            result[index] = value
    return result


def _scaled(deltas, scale): return {index: tuple(axis * scale for axis in value) for index, value in deltas.items()}
def _lerp_sparse(first, second, amount):
    return {index: tuple((first.get(index, (0.0, 0.0, 0.0))[axis] * (1.0 - amount) +
                          second.get(index, (0.0, 0.0, 0.0))[axis] * amount) for axis in range(3))
            for index in set(first) | set(second)}
def _sample_keys(keys, frame):
    if frame <= keys[0][0]: return keys[0][1]
    if frame >= keys[-1][0]: return keys[-1][1]
    for first, second in zip(keys, keys[1:]):
        if first[0] <= frame <= second[0]:
            amount = (frame - first[0]) / max(1.0e-12, second[0] - first[0])
            return first[1] * (1.0 - amount) + second[1] * amount
    return keys[-1][1]


__all__ = ["BlendShapeCorrectiveDriver", "BlendShapeFrame", "BlendShapeTarget", "BlendShapeTelemetry",
           "attach_blend_shape_deformer", "blend_shape_export_contract", "blend_shape_payload",
           "build_blend_shape_destination_manifest", "blend_shape_targets_from_destination_manifest",
           "blend_shape_target_from_dict", "blend_shape_target_from_positions", "blend_shape_target_to_dict",
           "blend_shape_targets_from_payload", "evaluate_blend_shape",
           "resolve_blend_shape_deltas", "resolve_blend_shape_weight", "set_blend_shape_weights"]
