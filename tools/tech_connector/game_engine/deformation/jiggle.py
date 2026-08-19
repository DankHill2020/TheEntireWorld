"""Stable, collision-aware secondary motion for skin and deformer stacks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap, Vec3, blend_deformation


@dataclass(frozen=True)
class JiggleDeformerSettings:
    stiffness: float = 85.0
    damping: float = 14.0
    mass: float = 1.0
    gravity: Vec3 = (0.0, 0.0, 0.0)
    max_offset: float = 0.25
    substeps: int = 2
    space: str = "object"
    follow: float = 0.72
    axis_weights: Vec3 = (1.0, 1.0, 1.0)
    max_velocity: float = 8.0
    settle_speed: float = 0.002
    collision_radius: float = 0.005
    friction: float = 0.25
    restitution: float = 0.08
    quality: str = "realtime"

    def validated(self) -> "JiggleDeformerSettings":
        if self.mass <= 0.0:
            raise ValueError("Jiggle mass must be greater than zero.")
        values = (self.stiffness, self.damping, self.max_offset, self.max_velocity,
                  self.settle_speed, self.collision_radius, self.friction, self.restitution)
        if min(values) < 0.0:
            raise ValueError("Jiggle stiffness, damping, limits, and collision values cannot be negative.")
        if not 0.0 <= self.follow <= 1.0:
            raise ValueError("Jiggle follow must be between zero and one.")
        if any(not 0.0 <= float(value) <= 1.0 for value in self.axis_weights):
            raise ValueError("Jiggle axis weights must be between zero and one.")
        if self.space not in {"object", "world"}:
            raise ValueError("Jiggle space must be object or world.")
        if self.quality not in {"preview", "realtime", "cinematic"}:
            raise ValueError("Jiggle quality must be preview, realtime, or cinematic.")
        return self


@dataclass
class JiggleRuntimeState:
    positions: list[Vec3] = field(default_factory=list)
    velocities: list[Vec3] = field(default_factory=list)
    previous_targets: list[Vec3] = field(default_factory=list)
    initialized: bool = False
    collision_count: int = 0
    settled_vertex_count: int = 0
    _positions_np: Any = field(default=None, repr=False)
    _velocities_np: Any = field(default=None, repr=False)
    _previous_targets_np: Any = field(default=None, repr=False)

    def reset(self, target_positions: Sequence[Sequence[float]]) -> None:
        self.positions = [_vec3(value) for value in target_positions]
        self.velocities = [(0.0, 0.0, 0.0) for _ in self.positions]
        self.previous_targets = list(self.positions)
        self.initialized = True
        self.collision_count = 0
        self.settled_vertex_count = len(self.positions)
        self._positions_np = self._velocities_np = self._previous_targets_np = None


def evaluate_jiggle(target_positions: Sequence[Sequence[float]], influence_map: DeformationWeightMap,
                    state: JiggleRuntimeState, settings: JiggleDeformerSettings, dt: float, *,
                    colliders: Sequence[Mapping[str, Any]] = ()) -> list[Vec3]:
    """Follow upstream animation with inertial lag, stable limits, and collision response."""
    settings.validated()
    if len(target_positions) != len(influence_map.values):
        raise ValueError("Jiggle targets and influence map must have matching vertex counts.")
    if not state.initialized or len(state.positions) != len(target_positions):
        state.reset(target_positions)
        return list(state.positions)
    frame_dt = max(0.0, float(dt))
    if frame_dt <= 0.0:
        return blend_deformation(target_positions, state.positions, influence_map)
    if np is not None and len(target_positions) >= 256 and not colliders:
        return _evaluate_numpy(target_positions, influence_map, state, settings, frame_dt)
    targets = [_vec3(value) for value in target_positions]
    state._positions_np = state._velocities_np = state._previous_targets_np = None
    target_velocities = [_scale(_subtract(target, state.previous_targets[i]), settings.follow / frame_dt)
                         for i, target in enumerate(targets)]
    state.collision_count = 0
    state.settled_vertex_count = 0
    substeps = max(1, int(settings.substeps))
    step_dt = frame_dt / substeps
    axes = _vec3(settings.axis_weights)
    for _ in range(substeps):
        for index, target in enumerate(targets):
            position = state.positions[index]
            velocity = state.velocities[index]
            spring = _multiply(_scale(_subtract(target, position), settings.stiffness), axes)
            drag = _multiply(_scale(_subtract(velocity, target_velocities[index]), -settings.damping), axes)
            acceleration = _add(_scale(_add(spring, drag), 1.0 / settings.mass), _multiply(settings.gravity, axes))
            velocity = _add(velocity, _scale(acceleration, step_dt))
            velocity = _add(target_velocities[index], _limit(
                _subtract(velocity, target_velocities[index]), settings.max_velocity
            ))
            position = _add(position, _scale(velocity, step_dt))
            position = _add(target, _multiply(_subtract(position, target), axes))
            velocity = _add(target_velocities[index], _multiply(
                _subtract(velocity, target_velocities[index]), axes
            ))
            offset = _multiply(_subtract(position, target), axes)
            distance = _length(offset)
            if settings.max_offset and distance > settings.max_offset:
                position = _add(target, _scale(offset, settings.max_offset / distance))
                velocity = _add(target_velocities[index], _scale(
                    _subtract(velocity, target_velocities[index]), 0.45
                ))
            position, velocity, contacts = _solve_colliders(position, velocity, settings, colliders)
            state.collision_count += contacts
            state.positions[index], state.velocities[index] = position, velocity
    for index, target in enumerate(targets):
        relative_speed = _length(_subtract(state.velocities[index], target_velocities[index]))
        if relative_speed <= settings.settle_speed and _length(_subtract(state.positions[index], target)) <= settings.settle_speed:
            state.positions[index], state.velocities[index] = target, target_velocities[index]
            state.settled_vertex_count += 1
    state.previous_targets = list(targets)
    return blend_deformation(targets, state.positions, influence_map)


def attach_jiggle_deformer(rig_graph: Any, source_id: str, mesh_id: str,
                           influence_map: DeformationWeightMap, *,
                           settings: JiggleDeformerSettings | None = None,
                           deformer_id: str | None = None) -> str:
    """Insert portable secondary motion after a skin cluster or graph deformer."""
    source = str(source_id)
    skins = getattr(rig_graph, "skins", {}) or {}
    deformers = getattr(rig_graph, "deformers", {}) or {}
    source_kind = "skin_cluster" if source in skins else "deformer" if source in deformers else ""
    if not source_kind:
        raise KeyError(f"Jiggle source is not a skin cluster or deformer: {source}")
    values = (settings or JiggleDeformerSettings()).validated()
    identifier = rig_graph.add_deformer(mesh_id, "jiggle", deformer_id=deformer_id, settings={
        "source_id": source, "source_kind": source_kind, "jiggle": asdict(values),
        "influence_map": influence_map.to_dict(), "collider_bindings": [],
        "map_semantics": "0 = upstream mesh, 1 = collision-aware secondary motion",
        "export_policy": secondary_motion_export_contract("portable"),
    })
    if source_kind == "skin_cluster":
        skins[source].setdefault("secondary_motion", []).append({
            "deformer_id": identifier, "type": "jiggle", "schema": "tech_connector.secondary_motion.v1",
            "canonical_skin_preserved": True,
        })
    return identifier


def secondary_motion_export_contract(destination: str) -> dict[str, Any]:
    key = str(destination or "portable").strip().lower()
    transfer = {
        "maya": "nHair/dynamics reconstruction or Alembic cache",
        "blender": "Geometry Nodes/soft-body reconstruction or Alembic cache",
        "houdini": "Vellum reconstruction or USD/Alembic cache",
        "unreal": "Anim Dynamics/Control Rig reconstruction or Geometry Cache",
        "unity": "runtime spring-bone reconstruction or baked vertex cache",
        "usd": "time-sampled points or blend shapes", "fbx": "baked joints/blend shapes or point cache",
        "gltf": "baked joint animation or morph targets",
        "portable": "TC secondary-motion extension plus optional baked cache",
    }.get(key, "native reconstruction or baked geometry cache")
    return {"schema": "tech_connector.secondary_motion_export.v1", "destination": key,
            "canonical_skin": "canonical joints and normalized weights",
            "secondary_motion_transfer": transfer, "canonical_skin_preserved": True,
            "fallback_required": key != "portable",
            "fallback_priority": ["native_reconstruction", "joint_or_morph_bake", "point_cache"]}


def _evaluate_numpy(targets, influence_map, state, settings, frame_dt):
    target = np.asarray(targets, dtype=np.float64)
    if state._positions_np is None or state._positions_np.shape != target.shape:
        state._positions_np = np.asarray(state.positions, dtype=np.float64)
        state._velocities_np = np.asarray(state.velocities, dtype=np.float64)
        state._previous_targets_np = np.asarray(state.previous_targets, dtype=np.float64)
    position, velocity = state._positions_np, state._velocities_np
    previous, axes = state._previous_targets_np, np.asarray(settings.axis_weights, dtype=np.float64)
    target_velocity = (target - previous) * (settings.follow / frame_dt)
    substeps, step_dt = max(1, int(settings.substeps)), frame_dt / max(1, int(settings.substeps))
    for _ in range(substeps):
        acceleration = (((target - position) * settings.stiffness - (velocity - target_velocity) * settings.damping) * axes) / settings.mass
        acceleration += np.asarray(settings.gravity, dtype=np.float64) * axes
        velocity += acceleration * step_dt
        relative_velocity = velocity - target_velocity
        speed = np.linalg.norm(relative_velocity, axis=1)
        if settings.max_velocity:
            mask = speed > settings.max_velocity
            relative_velocity[mask] *= (settings.max_velocity / speed[mask])[:, None]
        velocity = target_velocity + relative_velocity
        position += velocity * step_dt
        position = target + (position - target) * axes
        velocity = target_velocity + (velocity - target_velocity) * axes
        offset, distance = (position - target) * axes, np.linalg.norm((position - target) * axes, axis=1)
        if settings.max_offset:
            mask = distance > settings.max_offset
            position[mask] = target[mask] + offset[mask] * (settings.max_offset / distance[mask])[:, None]
            velocity[mask] = target_velocity[mask] + (velocity[mask] - target_velocity[mask]) * 0.45
    settled = ((np.linalg.norm(velocity - target_velocity, axis=1) <= settings.settle_speed) &
               (np.linalg.norm(position - target, axis=1) <= settings.settle_speed))
    position[settled], velocity[settled] = target[settled], target_velocity[settled]
    state.positions, state.velocities = [tuple(row) for row in position.tolist()], [tuple(row) for row in velocity.tolist()]
    state.previous_targets, state.collision_count, state.settled_vertex_count = [tuple(row) for row in target.tolist()], 0, int(np.count_nonzero(settled))
    state._previous_targets_np = target.copy()
    influence = np.asarray(influence_map.values, dtype=np.float64)
    if bool(np.all(influence == 1.0)):
        return list(state.positions)
    if bool(np.all(influence == 0.0)):
        return [tuple(row) for row in target.tolist()]
    blended = target + (position - target) * influence[:, None]
    return [tuple(row) for row in blended.tolist()]


def _solve_colliders(position, velocity, settings, colliders):
    contacts = 0
    for collider in colliders:
        kind = str(collider.get("type") or "sphere").lower()
        friction = max(0.0, float(collider.get("friction", settings.friction)))
        restitution = max(0.0, float(collider.get("restitution", settings.restitution)))
        if kind == "plane":
            normal = _normalize(_vec3(collider.get("normal", (0, 1, 0))), (0, 1, 0))
            distance = _dot(position, normal) - float(collider.get("offset", 0.0))
            if distance < settings.collision_radius:
                position, velocity, contacts = _add(position, _scale(normal, settings.collision_radius - distance)), _collision_velocity(velocity, normal, friction, restitution), contacts + 1
        elif kind == "sphere":
            center = _vec3(collider.get("center", (0, 0, 0)))
            radius, delta = max(0.0, float(collider.get("radius", 1.0))) + settings.collision_radius, _subtract(position, center)
            distance = _length(delta)
            if distance < radius:
                normal = _normalize(delta, (0, 1, 0))
                position, velocity, contacts = _add(center, _scale(normal, radius)), _collision_velocity(velocity, normal, friction, restitution), contacts + 1
    return position, velocity, contacts


def _collision_velocity(velocity, normal, friction, restitution):
    speed = _dot(velocity, normal)
    normal_velocity = _scale(normal, speed)
    return _add(_scale(normal_velocity, -restitution if speed < 0 else 1),
                _scale(_subtract(velocity, normal_velocity), max(0.0, 1.0 - friction)))


def _vec3(value):
    values = tuple(float(item) for item in value)
    return (values + (0.0, 0.0, 0.0))[:3]


def _add(a, b): return tuple(a[i] + b[i] for i in range(3))
def _subtract(a, b): return tuple(a[i] - b[i] for i in range(3))
def _scale(value, amount): return tuple(item * amount for item in value)
def _multiply(a, b): return tuple(a[i] * b[i] for i in range(3))
def _dot(a, b): return sum(a[i] * b[i] for i in range(3))
def _length(value): return math.sqrt(_dot(value, value))
def _normalize(value, fallback):
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-12 else fallback
def _limit(value, maximum):
    length = _length(value)
    return _scale(value, maximum / length) if maximum and length > maximum else value


__all__ = ["JiggleDeformerSettings", "JiggleRuntimeState", "attach_jiggle_deformer",
           "evaluate_jiggle", "secondary_motion_export_contract"]
