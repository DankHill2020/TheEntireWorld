"""Collision-responsive soft-tissue deformation layered after canonical skinning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Mapping, Sequence

try:
    import numpy as np
except Exception:  # pragma: no cover - minimal DCC Python environments use the scalar path.
    np = None

from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap, Vec3, blend_deformation
from tech_connector.game_engine.deformation.collision_projection import project_character_point


@dataclass(frozen=True)
class FleshDeformerSettings:
    stiffness: float = 115.0
    damping: float = 18.0
    mass: float = 1.0
    shape_stiffness: float = 22.0
    volume_preservation: float = 0.65
    collision_radius: float = 0.01
    friction: float = 0.35
    restitution: float = 0.05
    max_offset: float = 0.18
    substeps: int = 4
    gravity: Vec3 = (0.0, 0.0, 0.0)
    space: str = "world"
    quality: str = "realtime"

    def validated(self) -> "FleshDeformerSettings":
        if self.mass <= 0.0:
            raise ValueError("Flesh mass must be greater than zero.")
        if min(self.stiffness, self.damping, self.shape_stiffness, self.collision_radius, self.max_offset) < 0.0:
            raise ValueError("Flesh stiffness, damping, collision radius, and maximum offset cannot be negative.")
        if not 0.0 <= self.volume_preservation <= 1.0:
            raise ValueError("Flesh volume preservation must be between zero and one.")
        if self.space not in {"object", "world"}:
            raise ValueError("Flesh simulation space must be object or world.")
        return self


@dataclass
class FleshRuntimeState:
    positions: list[Vec3] = field(default_factory=list)
    velocities: list[Vec3] = field(default_factory=list)
    initialized: bool = False
    collision_count: int = 0

    def reset(self, target_positions: Sequence[Sequence[float]]) -> None:
        self.positions = [_vec3(value) for value in target_positions]
        self.velocities = [(0.0, 0.0, 0.0) for _ in self.positions]
        self.initialized = True
        self.collision_count = 0


def evaluate_flesh(
    target_positions: Sequence[Sequence[float]],
    influence_map: DeformationWeightMap,
    state: FleshRuntimeState,
    settings: FleshDeformerSettings,
    dt: float,
    *,
    edges: Sequence[Sequence[int]] = (),
    normals: Sequence[Sequence[float]] = (),
    colliders: Sequence[Mapping[str, Any]] = (),
) -> list[Vec3]:
    """Simulate skinned vertices as damped soft tissue with projected collision response."""
    settings.validated()
    targets = [_vec3(value) for value in target_positions]
    if len(targets) != len(influence_map.values):
        raise ValueError("Flesh targets and influence map must have matching vertex counts.")
    if normals and len(normals) != len(targets):
        raise ValueError("Flesh normals and target positions must have matching vertex counts.")
    if not state.initialized or len(state.positions) != len(targets):
        state.reset(targets)
        return list(targets)
    if np is not None and len(targets) >= 256 and not edges:
        return _evaluate_flesh_numpy(targets, influence_map, state, settings, dt, normals, colliders)
    adjacency = _adjacency(len(targets), edges)
    vertex_normals = [_normalize(_vec3(value), (0.0, 1.0, 0.0)) for value in normals] if normals else []
    substeps = max(1, int(settings.substeps))
    step_dt = max(0.0, float(dt)) / substeps
    state.collision_count = 0
    for _substep in range(substeps):
        old_positions = list(state.positions)
        for index, target in enumerate(targets):
            position = state.positions[index]
            previous_position = position
            velocity = state.velocities[index]
            spring = _scale(_subtract(target, position), settings.stiffness)
            drag = _scale(velocity, -settings.damping)
            shape_force = (0.0, 0.0, 0.0)
            neighbors = adjacency[index]
            if neighbors:
                own_offset = _subtract(position, target)
                for neighbor in neighbors:
                    neighbor_offset = _subtract(old_positions[neighbor], targets[neighbor])
                    shape_force = _add(shape_force, _subtract(neighbor_offset, own_offset))
                shape_force = _scale(shape_force, settings.shape_stiffness / len(neighbors))
            acceleration = _add(_scale(_add(_add(spring, drag), shape_force), 1.0 / settings.mass), settings.gravity)
            velocity = _add(velocity, _scale(acceleration, step_dt))
            position = _add(position, _scale(velocity, step_dt))
            offset = _subtract(position, target)
            distance = _length(offset)
            if settings.max_offset and distance > settings.max_offset:
                position = _add(target, _scale(offset, settings.max_offset / distance))
                velocity = _scale(velocity, 0.45)
            # Collision separation wins over the artistic offset limit; otherwise a
            # deeply intersecting animated target would clamp tissue back inside.
            position, velocity, contacts = _solve_colliders(
                position, velocity, settings, colliders, previous_position=previous_position,
            )
            state.collision_count += contacts
            state.positions[index] = position
            state.velocities[index] = velocity
        if vertex_normals and settings.volume_preservation > 0.0:
            signed = [
                _dot(_subtract(state.positions[index], targets[index]), vertex_normals[index])
                for index in range(len(targets))
            ]
            mean_signed = sum(signed) / max(1, len(signed))
            correction = settings.volume_preservation * mean_signed
            for index, normal in enumerate(vertex_normals):
                state.positions[index] = _subtract(state.positions[index], _scale(normal, correction))
            for index in range(len(targets)):
                state.positions[index], state.velocities[index], contacts = _solve_colliders(
                    state.positions[index], state.velocities[index], settings, colliders
                )
                state.collision_count += contacts
    return blend_deformation(targets, state.positions, influence_map)


def attach_flesh_deformer(
    rig_graph: Any,
    skin_id: str,
    mesh_id: str,
    influence_map: DeformationWeightMap,
    *,
    settings: FleshDeformerSettings | None = None,
    deformer_id: str | None = None,
) -> str:
    """Enable fleshy behavior after a skin while leaving canonical weights untouched."""
    skin = (getattr(rig_graph, "skins", {}) or {}).get(str(skin_id))
    if skin is None:
        raise KeyError(f"Flesh source must be a skin cluster: {skin_id}")
    values = (settings or FleshDeformerSettings()).validated()
    identifier = rig_graph.add_deformer(
        mesh_id,
        "flesh",
        deformer_id=deformer_id,
        settings={
            "source_id": str(skin_id),
            "source_kind": "skin_cluster",
            "flesh": asdict(values),
            "influence_map": influence_map.to_dict(),
            "collider_bindings": [],
            "map_semantics": "0 = canonical skinned mesh, 1 = collision-responsive flesh",
            "export_policy": flesh_export_contract("portable"),
        },
    )
    skin["fleshy"] = {
        "enabled": True,
        "deformer_id": identifier,
        "schema": "tech_connector.flesh.v1",
        "canonical_skin_preserved": True,
        "export_policy": flesh_export_contract("portable"),
    }
    return identifier


def _evaluate_flesh_numpy(
    targets: list[Vec3],
    influence_map: DeformationWeightMap,
    state: FleshRuntimeState,
    settings: FleshDeformerSettings,
    dt: float,
    normals: Sequence[Sequence[float]],
    colliders: Sequence[Mapping[str, Any]],
) -> list[Vec3]:
    target = np.asarray(targets, dtype=np.float64)
    position = np.asarray(state.positions, dtype=np.float64)
    velocity = np.asarray(state.velocities, dtype=np.float64)
    gravity = np.asarray(settings.gravity, dtype=np.float64)
    normal_array = np.asarray(normals, dtype=np.float64) if normals else None
    if normal_array is not None:
        lengths = np.linalg.norm(normal_array, axis=1)
        valid = lengths > 1.0e-12
        normal_array[valid] /= lengths[valid, None]
        normal_array[~valid] = (0.0, 1.0, 0.0)
    state.collision_count = 0
    substeps = max(1, int(settings.substeps))
    step_dt = max(0.0, float(dt)) / substeps
    for _substep in range(substeps):
        acceleration = (
            (target - position) * settings.stiffness - velocity * settings.damping
        ) / settings.mass + gravity
        velocity += acceleration * step_dt
        position += velocity * step_dt
        offset = position - target
        distance = np.linalg.norm(offset, axis=1)
        if settings.max_offset:
            mask = distance > settings.max_offset
            position[mask] = target[mask] + offset[mask] * (settings.max_offset / distance[mask])[:, None]
            velocity[mask] *= 0.45
        if normal_array is not None and settings.volume_preservation > 0.0:
            signed = np.sum((position - target) * normal_array, axis=1)
            position -= normal_array * (settings.volume_preservation * float(np.mean(signed)))
        for collider in colliders:
            kind = str(collider.get("type") or "sphere").lower()
            friction = max(0.0, float(collider.get("friction", settings.friction)))
            restitution = max(0.0, float(collider.get("restitution", settings.restitution)))
            if kind == "plane":
                normal = np.asarray(_normalize(_vec3(collider.get("normal", (0.0, 1.0, 0.0))), (0.0, 1.0, 0.0)))
                signed = position @ normal - float(collider.get("offset", 0.0))
                mask = signed < settings.collision_radius
                if np.any(mask):
                    position[mask] += (settings.collision_radius - signed[mask])[:, None] * normal
                    velocity[mask] = _numpy_collision_velocity(velocity[mask], normal, friction, restitution)
                    state.collision_count += int(np.count_nonzero(mask))
            elif kind == "sphere":
                center = np.asarray(_vec3(collider.get("center", (0.0, 0.0, 0.0))))
                minimum = max(0.0, float(collider.get("radius", 1.0))) + settings.collision_radius
                delta = position - center
                distance = np.linalg.norm(delta, axis=1)
                mask = distance < minimum
                if np.any(mask):
                    normals_at_contact = np.zeros_like(delta[mask])
                    valid = distance[mask] > 1.0e-12
                    normals_at_contact[valid] = delta[mask][valid] / distance[mask][valid, None]
                    normals_at_contact[~valid] = (0.0, 1.0, 0.0)
                    position[mask] = center + normals_at_contact * minimum
                    velocity[mask] = _numpy_collision_velocity(
                        velocity[mask], normals_at_contact, friction, restitution
                    )
                    state.collision_count += int(np.count_nonzero(mask))
            elif kind == "capsule":
                start = np.asarray(_vec3(collider.get("start", collider.get("a", (0.0, -0.5, 0.0)))))
                end = np.asarray(_vec3(collider.get("end", collider.get("b", (0.0, 0.5, 0.0)))))
                segment = end - start
                denominator = float(np.dot(segment, segment))
                amount = np.clip(((position - start) @ segment) / denominator, 0.0, 1.0) if denominator > 1.0e-18 else np.zeros(len(position))
                closest = start + amount[:, None] * segment
                delta = position - closest
                distance = np.linalg.norm(delta, axis=1)
                minimum = max(0.0, float(collider.get("radius", 0.5))) + settings.collision_radius
                mask = distance < minimum
                if np.any(mask):
                    normals_at_contact = np.zeros_like(delta[mask])
                    valid = distance[mask] > 1.0e-12
                    normals_at_contact[valid] = delta[mask][valid] / distance[mask][valid, None]
                    normals_at_contact[~valid] = (0.0, 0.0, 1.0)
                    position[mask] = closest[mask] + normals_at_contact * minimum
                    velocity[mask] = _numpy_collision_velocity(velocity[mask], normals_at_contact, friction, restitution)
                    state.collision_count += int(np.count_nonzero(mask))
            elif kind in {"box", "aabb"}:
                center = np.asarray(_vec3(collider.get("center", (0.0, 0.0, 0.0))))
                half = np.maximum(0.0, np.asarray(_vec3(collider.get("half_extents", collider.get("extents", (0.5, 0.5, 0.5))))))
                expanded = half + settings.collision_radius
                local = position - center
                mask = np.all(np.abs(local) < expanded, axis=1)
                if np.any(mask):
                    selected = np.flatnonzero(mask)
                    axes = np.argmin(expanded - np.abs(local[mask]), axis=1)
                    signs = np.where(local[selected, axes] < 0.0, -1.0, 1.0)
                    normals_at_contact = np.zeros((len(selected), 3), dtype=np.float64)
                    normals_at_contact[np.arange(len(selected)), axes] = signs
                    position[selected, axes] = center[axes] + signs * expanded[axes]
                    velocity[selected] = _numpy_collision_velocity(velocity[selected], normals_at_contact, friction, restitution)
                    state.collision_count += len(selected)
    state.positions = [tuple(row) for row in position.tolist()]
    state.velocities = [tuple(row) for row in velocity.tolist()]
    influence = np.asarray(influence_map.values, dtype=np.float64)[:, None]
    blended = target + (position - target) * influence
    return [tuple(row) for row in blended.tolist()]


def _numpy_collision_velocity(velocity, normal, friction: float, restitution: float):
    if normal.ndim == 1:
        normal_speed = velocity @ normal
        normal_velocity = normal_speed[:, None] * normal
    else:
        normal_speed = np.sum(velocity * normal, axis=1)
        normal_velocity = normal_speed[:, None] * normal
    tangent = velocity - normal_velocity
    reflected_scale = np.where(normal_speed < 0.0, -restitution, 1.0)
    return normal_velocity * reflected_scale[:, None] + tangent * max(0.0, 1.0 - friction)


def flesh_export_contract(destination: str) -> dict[str, Any]:
    key = str(destination or "portable").strip().lower()
    target = {
        "maya": ("skinCluster", "Alembic point cache or blendShape bake"),
        "blender": ("Armature vertex groups", "Mesh Cache/Alembic or shape-key bake"),
        "houdini": ("boneCapture weights", "Vellum reconstruction or USD/Alembic point cache"),
        "unreal": ("SkeletalMesh skin weights", "ML Deformer/morph targets or Geometry Cache"),
        "unity": ("SkinnedMeshRenderer weights", "blend shapes or baked vertex cache"),
        "usd": ("UsdSkel weights", "time-sampled points or blend shapes"),
        "fbx": ("FBX skeleton and skin weights", "baked blend shapes; point-cache sidecar recommended"),
        "gltf": ("glTF joints and weights", "morph-target bake"),
        "portable": ("canonical joints and normalized weights", "TC flesh extension plus optional baked cache"),
    }.get(key, ("canonical joints and normalized weights", "TC flesh extension plus baked geometry cache"))
    return {
        "schema": "tech_connector.flesh_export.v1",
        "destination": key,
        "canonical_skin": target[0],
        "flesh_transfer": target[1],
        "canonical_skin_preserved": True,
        "fallback_required": key not in {"portable"},
        "fallback_priority": ["native_reconstruction", "morph_or_blendshape_bake", "point_cache"],
    }


def _solve_colliders(
    position: Vec3,
    velocity: Vec3,
    settings: FleshDeformerSettings,
    colliders: Sequence[Mapping[str, Any]],
    *,
    previous_position: Sequence[float] | None = None,
) -> tuple[Vec3, Vec3, int]:
    return project_character_point(
        position, velocity, radius=settings.collision_radius,
        friction=settings.friction, restitution=settings.restitution,
        colliders=colliders, previous_position=previous_position,
    )


def _adjacency(vertex_count: int, edges: Sequence[Sequence[int]]) -> list[list[int]]:
    result = [[] for _ in range(vertex_count)]
    for edge in edges:
        if len(edge) < 2:
            continue
        first, second = int(edge[0]), int(edge[1])
        if 0 <= first < vertex_count and 0 <= second < vertex_count and first != second:
            result[first].append(second)
            result[second].append(first)
    return result


def _vec3(value: Sequence[float]) -> Vec3:
    values = tuple(float(item) for item in value)
    return (values + (0.0, 0.0, 0.0))[:3]


def _add(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] + second[index] for index in range(3))


def _subtract(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] - second[index] for index in range(3))


def _scale(value: Vec3, amount: float) -> Vec3:
    return tuple(component * amount for component in value)


def _dot(first: Vec3, second: Vec3) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _length(value: Vec3) -> float:
    return math.sqrt(_dot(value, value))


def _normalize(value: Vec3, fallback: Vec3) -> Vec3:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-12 else fallback


__all__ = [
    "FleshDeformerSettings", "FleshRuntimeState", "attach_flesh_deformer",
    "evaluate_flesh", "flesh_export_contract",
]
