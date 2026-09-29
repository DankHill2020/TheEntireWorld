"""Activation- and pose-driven muscle tissue layered after canonical skinning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np

from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap, Vec3


@dataclass(frozen=True)
class MuscleDeformerSettings:
    stiffness: float = 180.0
    activation_stiffness: float = 1.4
    damping: float = 24.0
    mass: float = 1.0
    contraction: float = 0.08
    bulge: float = 0.035
    max_offset: float = 0.12
    fiber_direction: Vec3 = (0.0, 1.0, 0.0)
    inertial_follow: float = 0.85
    teleport_distance: float = 0.75
    substeps: int = 4
    quality: str = "realtime"

    def validated(self) -> "MuscleDeformerSettings":
        if self.mass <= 0.0:
            raise ValueError("Muscle mass must be greater than zero.")
        if min(self.stiffness, self.activation_stiffness, self.damping, self.contraction,
               self.bulge, self.max_offset, self.teleport_distance) < 0.0:
            raise ValueError("Muscle stiffness, damping, contraction, bulge, and limits cannot be negative.")
        if not 0.0 <= self.inertial_follow <= 1.0:
            raise ValueError("Muscle inertial follow must be between zero and one.")
        if self.quality not in {"preview", "realtime", "cinematic"}:
            raise ValueError("Muscle quality must be preview, realtime, or cinematic.")
        if _length(self.fiber_direction) <= 1.0e-12:
            raise ValueError("Muscle fiber direction cannot be zero.")
        return self


@dataclass(frozen=True)
class PoseSpaceTissueDriver:
    driver_id: str
    center: float = 1.0
    width: float = 0.25
    gain: float = 1.0
    bulge_scale: float = 1.0
    stiffness_scale: float = 1.0

    def validated(self) -> "PoseSpaceTissueDriver":
        if not self.driver_id:
            raise ValueError("A pose-space tissue driver requires an identifier.")
        if self.width <= 0.0 or self.gain < 0.0 or self.bulge_scale < 0.0 or self.stiffness_scale < 0.0:
            raise ValueError("Pose driver width must be positive and its scales cannot be negative.")
        return self


@dataclass
class MuscleRuntimeState:
    positions: Any = None
    velocities: Any = None
    previous_targets: Any = None
    initialized: bool = False
    teleport_count: int = 0
    activation_mean: float = 0.0
    activation_max: float = 0.0
    activated_vertices: int = 0
    kinetic_energy: float = 0.0

    def reset(self, targets: np.ndarray) -> None:
        self.positions = targets.copy()
        self.velocities = np.zeros_like(targets)
        self.previous_targets = targets.copy()
        self.initialized = True


def evaluate_muscle(
    target_positions: Sequence[Sequence[float]],
    activation_map: DeformationWeightMap,
    state: MuscleRuntimeState,
    settings: MuscleDeformerSettings,
    dt: float,
    *,
    activation: float | Sequence[float] = 1.0,
    normals: Sequence[Sequence[float]] = (),
    pose_drivers: Sequence[PoseSpaceTissueDriver | Mapping[str, Any]] = (),
    pose_values: Mapping[str, float] | None = None,
    pose_maps: Mapping[str, DeformationWeightMap | Mapping[str, Any]] | None = None,
) -> list[Vec3]:
    """Evaluate fiber contraction and volume-like bulging with stable inertia."""
    values = settings.validated()
    target = np.asarray(target_positions, dtype=np.float64).reshape((-1, 3))
    if len(target) != len(activation_map.values):
        raise ValueError("Muscle targets and activation map must have matching vertex counts.")
    normal = _normals(target, normals)
    effective, bulge_scale, stiffness_scale = _activation(
        len(target), activation_map, activation, pose_drivers, pose_values or {}, pose_maps or {},
    )
    fiber = np.asarray(_normalize(values.fiber_direction), dtype=np.float64)
    # Use the canonical region center, not an activation-weighted center. Painted
    # falloffs must control how much each point moves without shifting the muscle's
    # attachment frame as activation changes.
    centroid = np.mean(target, axis=0) if len(target) else np.zeros(3, dtype=np.float64)
    along = (target - centroid) @ fiber
    driven = target - fiber * (along * effective * float(values.contraction))[:, None]
    driven += normal * (effective * float(values.bulge) * bulge_scale)[:, None]

    if not state.initialized or state.positions is None or state.positions.shape != target.shape:
        state.reset(driven)
        state.previous_targets = target.copy()
        _telemetry(state, effective)
        return [tuple(row) for row in driven.tolist()]
    frame_dt = max(0.0, float(dt))
    maximum_driver_motion = float(np.max(np.linalg.norm(target - state.previous_targets, axis=1), initial=0.0))
    if values.teleport_distance > 0.0 and maximum_driver_motion > values.teleport_distance:
        state.reset(driven)
        state.previous_targets = target.copy()
        state.teleport_count += 1
        _telemetry(state, effective)
        return [tuple(row) for row in driven.tolist()]
    if frame_dt > 0.0:
        target_velocity = (target - state.previous_targets) * (float(values.inertial_follow) / frame_dt)
        substeps = max(1, int(values.substeps))
        step_dt = frame_dt / substeps
        stiffness = float(values.stiffness) * (1.0 + effective * float(values.activation_stiffness) * stiffness_scale)
        for _ in range(substeps):
            acceleration = (
                (driven - state.positions) * stiffness[:, None]
                - (state.velocities - target_velocity) * float(values.damping)
            ) / float(values.mass)
            state.velocities += acceleration * step_dt
            state.positions += state.velocities * step_dt
            offset = state.positions - target
            distance = np.linalg.norm(offset, axis=1)
            if values.max_offset > 0.0:
                over = distance > values.max_offset
                state.positions[over] = target[over] + offset[over] * (values.max_offset / distance[over])[:, None]
                state.velocities[over] = target_velocity[over] + (state.velocities[over] - target_velocity[over]) * 0.45
    state.previous_targets = target.copy()
    _telemetry(state, effective)
    return [tuple(row) for row in state.positions.tolist()]


def attach_muscle_deformer(
    rig_graph: Any,
    skin_id: str,
    mesh_id: str,
    activation_map: DeformationWeightMap,
    *,
    settings: MuscleDeformerSettings | None = None,
    pose_drivers: Sequence[PoseSpaceTissueDriver] = (),
    pose_maps: Mapping[str, DeformationWeightMap] | None = None,
    deformer_id: str | None = None,
) -> str:
    skin = (getattr(rig_graph, "skins", {}) or {}).get(str(skin_id))
    if skin is None:
        raise KeyError(f"Muscle source must be a skin cluster: {skin_id}")
    values = (settings or MuscleDeformerSettings()).validated()
    drivers = [item.validated() for item in pose_drivers]
    pose_maps = pose_maps or {}
    for item in drivers:
        if item.driver_id in pose_maps and len(pose_maps[item.driver_id].values) != len(activation_map.values):
            raise ValueError(f"Pose map {item.driver_id} must match the muscle activation map.")
    identifier = rig_graph.add_deformer(mesh_id, "muscle", deformer_id=deformer_id, settings={
        "source_id": str(skin_id), "source_kind": "skin_cluster",
        "muscle": asdict(values), "influence_map": activation_map.to_dict(),
        "activation_map": activation_map.to_dict(), "activation": 1.0,
        "pose_drivers": [asdict(item) for item in drivers],
        "pose_maps": {key: value.to_dict() for key, value in pose_maps.items()},
        "pose_values": {}, "collider_bindings": [],
        "map_semantics": "0 = canonical skin, 1 = activated muscle tissue",
        "export_policy": muscle_export_contract("portable"),
    })
    skin.setdefault("muscles", []).append({
        "deformer_id": identifier, "schema": "tech_connector.muscle.v1",
        "canonical_skin_preserved": True, "activation_editable": True,
    })
    return identifier


def set_muscle_activation(rig_graph: Any, deformer_id: str, activation: float, *,
                          pose_values: Mapping[str, float] | None = None) -> dict[str, Any]:
    deformer = (getattr(rig_graph, "deformers", {}) or {}).get(str(deformer_id))
    if deformer is None or str(deformer.get("type") or "") != "muscle":
        raise KeyError(f"Muscle deformer does not exist: {deformer_id}")
    settings = deformer.setdefault("settings", {})
    settings["activation"] = max(0.0, min(1.0, float(activation)))
    if pose_values is not None:
        settings["pose_values"] = {str(key): float(value) for key, value in pose_values.items()}
    return {"deformer_id": str(deformer_id), "activation": settings["activation"],
            "pose_values": dict(settings.get("pose_values") or {})}


def muscle_export_contract(destination: str = "portable") -> dict[str, Any]:
    key = str(destination or "portable").strip().lower()
    transfer = {
        "maya": "cMuscle or poseInterpolator reconstruction; Alembic/blendShape fallback",
        "houdini": "Muscles & Tissue activation and fiber attributes; USD/Alembic fallback",
        "blender": "Geometry Nodes corrective/muscle rig; shape-key or Alembic fallback",
        "unreal": "Deformer Graph/ML Deformer or morph targets plus canonical SkeletalMesh",
        "unity": "custom compute deformer or blend-shape/vertex-cache fallback",
        "usd": "UsdSkel canonical binding plus blend shapes or time-sampled points",
        "fbx": "canonical skeleton/weights plus baked corrective blend shapes",
        "gltf": "canonical skin plus morph-target animation",
        "portable": "TC muscle activation, pose drivers, fiber settings, and optional cache",
    }.get(key, "native tissue reconstruction or deterministic point cache")
    return {"schema": "tech_connector.muscle_export.v1", "destination": key,
            "canonical_skin_preserved": True, "muscle_transfer": transfer,
            "fallback_priority": ["native_muscle", "pose_correctives", "morph_bake", "point_cache"]}


def _activation(count, activation_map, activation, pose_drivers, pose_values, pose_maps):
    base = np.asarray(activation_map.values, dtype=np.float64)
    scalar = np.asarray(activation, dtype=np.float64)
    if scalar.ndim == 0:
        effective = base * float(np.clip(scalar, 0.0, 1.0))
    else:
        if len(scalar) != count:
            raise ValueError("Per-vertex muscle activation must match the vertex count.")
        effective = base * np.clip(scalar, 0.0, 1.0)
    bulge_scale = np.ones(count, dtype=np.float64)
    stiffness_scale = np.ones(count, dtype=np.float64)
    for raw in pose_drivers:
        driver = raw if isinstance(raw, PoseSpaceTissueDriver) else PoseSpaceTissueDriver(**dict(raw))
        driver.validated()
        value = float(pose_values.get(driver.driver_id, 0.0))
        response = math.exp(-0.5 * ((value - driver.center) / driver.width) ** 2) * driver.gain
        raw_map = pose_maps.get(driver.driver_id)
        if isinstance(raw_map, Mapping):
            raw_map = DeformationWeightMap.from_dict(dict(raw_map))
        driver_map = np.asarray(raw_map.values, dtype=np.float64) if isinstance(raw_map, DeformationWeightMap) else np.ones(count)
        if len(driver_map) != count:
            raise ValueError(f"Pose map {driver.driver_id} must match the vertex count.")
        weighted = response * driver_map
        effective += weighted
        bulge_scale += weighted * (driver.bulge_scale - 1.0)
        stiffness_scale += weighted * (driver.stiffness_scale - 1.0)
    return np.clip(effective, 0.0, 1.0), np.maximum(0.0, bulge_scale), np.maximum(0.0, stiffness_scale)


def _normals(target, normals):
    if normals:
        result = np.asarray(normals, dtype=np.float64).reshape((-1, 3))
        if len(result) != len(target):
            raise ValueError("Muscle normals must match the vertex count.")
    else:
        result = target - np.mean(target, axis=0)
    lengths = np.linalg.norm(result, axis=1)
    valid = lengths > 1.0e-12
    result[valid] /= lengths[valid, None]
    result[~valid] = (1.0, 0.0, 0.0)
    return result


def _telemetry(state, activation):
    state.activation_mean = float(np.mean(activation)) if len(activation) else 0.0
    state.activation_max = float(np.max(activation, initial=0.0))
    state.activated_vertices = int(np.count_nonzero(activation > 1.0e-4))
    state.kinetic_energy = float(0.5 * np.sum(state.velocities * state.velocities))


def _length(value): return math.sqrt(sum(float(item) * float(item) for item in value))
def _normalize(value):
    length = _length(value)
    return tuple(float(item) / length for item in value)


__all__ = [
    "MuscleDeformerSettings", "MuscleRuntimeState", "PoseSpaceTissueDriver",
    "attach_muscle_deformer", "evaluate_muscle", "muscle_export_contract", "set_muscle_activation",
]
