"""Provider-resident blend-shape and secondary-motion evaluation with adaptive budgets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import time
from typing import Any, Mapping, Sequence

import numpy as np

from tech_connector.game_engine.deformation.flesh import FleshDeformerSettings
from tech_connector.game_engine.deformation.jiggle import JiggleDeformerSettings
from tech_connector.game_engine.deformation.muscle import MuscleDeformerSettings, PoseSpaceTissueDriver
from tech_connector.game_engine.deformation.blend_shape import (
    blend_shape_target_from_dict,
    resolve_blend_shape_weight,
)
from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import compute_provider


@dataclass
class GpuSecondaryMotionState:
    provider_id: str
    kind: str
    vertex_count: int
    positions: Any
    velocities: Any
    previous_targets: Any
    initialized: bool = False
    edge_signature: tuple[tuple[int, int], ...] = ()
    edge_indices: Any = None
    teleport_count: int = 0

    @property
    def memory_bytes(self) -> int:
        total = self.positions.nbytes + self.velocities.nbytes + self.previous_targets.nbytes
        return int(total + (0 if self.edge_indices is None else self.edge_indices.nbytes))


@dataclass
class GpuBlendShapeState:
    provider_id: str
    kind: str
    vertex_count: int
    signature: str = ""
    frames: Any = None
    masks: Any = None

    @property
    def memory_bytes(self) -> int:
        total = 0
        for values in (self.frames or {}).values():
            for _weight, indices, deltas in values:
                total += int(indices.nbytes + deltas.nbytes)
        for value in (self.masks or {}).values():
            total += int(value.nbytes)
        return total


@dataclass
class DeformationLodController:
    target_ms: float = 4.0
    quality: float = 1.0
    minimum_quality: float = 0.25
    maximum_quality: float = 1.0
    last_ms: float = 0.0

    def resolved_substeps(self, authored: int) -> int:
        return max(1, int(round(max(1, int(authored)) * self.quality)))

    def update(self, elapsed_ms: float) -> None:
        self.last_ms = max(0.0, float(elapsed_ms))
        if self.target_ms <= 0.0:
            return
        if self.last_ms > self.target_ms * 1.08:
            self.quality = max(self.minimum_quality, self.quality * 0.82)
        elif self.last_ms < self.target_ms * 0.72:
            self.quality = min(self.maximum_quality, self.quality * 1.06)


def evaluate_gpu_deformation_stack(
    rig_graph: Any,
    mesh_id: str,
    upstream_positions: Sequence[Sequence[float]],
    dt: float,
    *,
    provider_id: str,
    states: dict[str, GpuSecondaryMotionState],
    lod: DeformationLodController,
    edges: Sequence[Sequence[int]] = (),
    normals: Sequence[Sequence[float]] = (),
    colliders: Sequence[Mapping[str, Any]] = (),
    resident_output: bool = False,
) -> tuple[Any, dict[str, Any]]:
    provider = compute_provider(provider_id)
    if not provider.status.available:
        raise RuntimeError(provider.status.reason or f"Compute provider {provider_id} is unavailable.")
    xp = provider.array_module
    started = time.perf_counter()
    result = xp.asarray(upstream_positions, dtype=xp.float32).reshape((-1, 3))
    deformers = sorted(
        (
            (str(identifier), item)
            for identifier, item in (getattr(rig_graph, "deformers", {}) or {}).items()
            if str(item.get("mesh_id") or "") == str(mesh_id) and bool(item.get("enabled", True))
        ),
        key=lambda pair: (int(pair[1].get("order", 0) or 0), pair[0]),
    )
    evaluated: list[str] = []
    skipped: list[str] = []
    deformer_ms: dict[str, float] = {}
    reused_states = 0
    collision_count = 0
    settled_count = 0
    muscle_activation: dict[str, dict[str, float | int]] = {}
    blend_shapes: dict[str, dict[str, Any]] = {}
    teleport_resets = 0
    for identifier, deformer in deformers:
        deformer_started = time.perf_counter()
        settings = dict(deformer.get("settings") or {})
        influence_data = settings.get("influence_map")
        kind = str(deformer.get("type") or "")
        if kind == "blend_shape":
            state, reused = _blend_state(states, identifier, provider_id, len(result))
            reused_states += int(reused)
            result, blend_metrics = _blend_shape(xp, result, state, settings)
            blend_shapes[identifier] = blend_metrics
            evaluated.append(identifier)
            deformer_ms[identifier] = (time.perf_counter() - deformer_started) * 1000.0
            continue
        if not isinstance(influence_data, dict) or kind not in {"muscle", "jiggle", "flesh"}:
            skipped.append(identifier)
            continue
        influence = DeformationWeightMap.from_dict(influence_data)
        if len(influence.values) != len(result):
            skipped.append(identifier)
            continue
        state, reused = _state(xp, states, identifier, provider_id, kind, len(result))
        reused_states += int(reused)
        weights = xp.asarray(influence.values, dtype=xp.float32)[:, None]
        if kind == "muscle":
            values = MuscleDeformerSettings(**dict(settings.get("muscle") or {})).validated()
            activation_data = settings.get("activation_map") or influence_data
            activation_map = DeformationWeightMap.from_dict(dict(activation_data))
            if len(activation_map.values) != len(result):
                skipped.append(identifier)
                continue
            result, activation_metrics, teleports = _muscle(
                xp, result, xp.asarray(activation_map.values, dtype=xp.float32), state,
                values, float(dt), normals, settings, lod.resolved_substeps(values.substeps),
                readback=not resident_output,
            )
            muscle_activation[identifier] = activation_metrics
            teleport_resets += teleports
        elif kind == "jiggle":
            values = JiggleDeformerSettings(**dict(settings.get("jiggle") or {})).validated()
            result, contacts, settled = _jiggle(
                xp, result, weights, state, values, float(dt), colliders,
                lod.resolved_substeps(values.substeps), readback=not resident_output,
            )
            collision_count += contacts
            settled_count += settled
        else:
            values = FleshDeformerSettings(**dict(settings.get("flesh") or {})).validated()
            result, contacts = _flesh(
                xp, result, weights, state, values, float(dt), edges, normals, colliders,
                lod.resolved_substeps(values.substeps), readback=not resident_output,
            )
            collision_count += contacts
        evaluated.append(identifier)
        deformer_ms[identifier] = (time.perf_counter() - deformer_started) * 1000.0
    if not resident_output:
        provider.synchronize()
        output = _host(xp, result).tolist()
    else:
        output = result
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    lod.update(elapsed_ms)
    return output, {
        "schema": "tech_connector.gpu_deformation_telemetry.v1",
        "mesh_id": str(mesh_id), "provider_id": provider_id,
        "execution": provider.status.device_type,
        "evaluated_deformers": evaluated, "skipped_deformers": skipped,
        "deformer_ms": deformer_ms, "evaluation_ms": elapsed_ms,
        "collision_contacts": collision_count if not resident_output else 0,
        "settled_vertices": settled_count if not resident_output else 0,
        "muscle_activation": muscle_activation,
        "blend_shapes": blend_shapes,
        "teleport_resets": teleport_resets if not resident_output else 0,
        "readback_deferred": resident_output, "resident_output": resident_output,
        "synchronization_points": 0 if resident_output else 1,
        "reused_states": reused_states, "state_count": len(states),
        "memory_bytes": sum(item.memory_bytes for item in states.values()),
        "lod_quality": lod.quality, "lod_target_ms": lod.target_ms,
        "budget_pressure": elapsed_ms / max(1.0e-6, lod.target_ms),
    }


def _state(xp, states, identifier, provider_id, kind, count):
    state = states.get(identifier)
    reused = isinstance(state, GpuSecondaryMotionState) and state.provider_id == provider_id and state.kind == kind and state.vertex_count == count
    if not reused:
        zeros = xp.zeros((count, 3), dtype=xp.float32)
        state = GpuSecondaryMotionState(provider_id, kind, count, zeros.copy(), zeros.copy(), zeros.copy())
        states[identifier] = state
    return state, reused


def _blend_state(states, identifier, provider_id, count):
    state = states.get(identifier)
    reused = (isinstance(state, GpuBlendShapeState) and state.provider_id == provider_id
              and state.vertex_count == count)
    if not reused:
        state = GpuBlendShapeState(provider_id, "blend_shape", count, frames={}, masks={})
        states[identifier] = state
    return state, reused


def _blend_shape(xp, source, state, settings):
    raw_targets = list(settings.get("targets") or ())
    signature = hashlib.sha256(json.dumps(raw_targets, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    targets = [blend_shape_target_from_dict(item).validated(len(source)) for item in raw_targets]
    if state.signature != signature:
        state.frames = {}
        state.masks = {}
        for target in targets:
            state.frames[target.target_id] = [
                (float(frame.weight),
                 xp.asarray(sorted(frame.deltas), dtype=xp.int64),
                 xp.asarray([frame.deltas[index] for index in sorted(frame.deltas)], dtype=xp.float32).reshape((-1, 3)))
                for frame in target.frames
            ]
            if target.mask is not None:
                state.masks[target.target_id] = xp.asarray(target.mask.values, dtype=xp.float32)
        state.signature = signature
    result = source.copy()
    resolved = {}
    active_targets = 0
    active_deltas = 0
    weights = dict(settings.get("weights") or {})
    drivers = dict(settings.get("driver_values") or {})
    frame_value = settings.get("frame")
    for target in targets:
        value = resolve_blend_shape_weight(target, weights, drivers, frame_value)
        resolved[target.target_id] = value
        if abs(value) <= 1.0e-12:
            continue
        contributions = _blend_contributions(state.frames[target.target_id], value)
        mask = state.masks.get(target.target_id)
        touched = set()
        for scale, indices, deltas in contributions:
            if len(indices) == 0 or abs(scale) <= 1.0e-12:
                continue
            offsets = deltas * float(scale)
            if mask is not None:
                offsets = offsets * mask[indices, None]
            xp.add.at(result, indices, offsets)
            if xp is np:
                touched.update(int(index) for index in indices.tolist())
            else:
                active_deltas += len(indices)
        active_targets += 1
        if xp is np:
            active_deltas += len(touched)
    return result, {"active_targets": active_targets, "active_deltas": active_deltas,
                    "maximum_absolute_weight": max((abs(value) for value in resolved.values()), default=0.0),
                    "resolved_weights": resolved, "provider_buffers_resident": True}


def _blend_contributions(frames, weight):
    points = sorted([(0.0, None, None)] + list(frames), key=lambda item: item[0])
    if weight <= points[0][0]:
        reference = points[1] if points[0][0] == 0.0 and len(points) > 1 else points[0]
        return [] if reference[0] == 0.0 else [(weight / reference[0], reference[1], reference[2])]
    if weight >= points[-1][0]:
        reference = points[-2] if points[-1][0] == 0.0 and len(points) > 1 else points[-1]
        return [] if reference[0] == 0.0 else [(weight / reference[0], reference[1], reference[2])]
    for first, second in zip(points, points[1:]):
        if first[0] <= weight <= second[0]:
            amount = (weight - first[0]) / max(1.0e-12, second[0] - first[0])
            output = []
            if first[1] is not None: output.append((1.0 - amount, first[1], first[2]))
            if second[1] is not None: output.append((amount, second[1], second[2]))
            return output
    return []


def _muscle(xp, target, activation_map, state, settings, dt, normals, authored, substeps, *, readback):
    count = len(target)
    raw_activation = authored.get("activation", 1.0)
    scalar = xp.asarray(raw_activation, dtype=xp.float32)
    if getattr(scalar, "ndim", 0) == 0:
        effective = activation_map * xp.clip(scalar, 0.0, 1.0)
    else:
        if len(scalar) != count:
            raise ValueError("Per-vertex muscle activation must match the vertex count.")
        effective = activation_map * xp.clip(scalar.reshape((-1,)), 0.0, 1.0)
    bulge_scale = xp.ones(count, dtype=xp.float32)
    stiffness_scale = xp.ones(count, dtype=xp.float32)
    pose_values = dict(authored.get("pose_values") or {})
    pose_maps = dict(authored.get("pose_maps") or {})
    for raw in authored.get("pose_drivers", ()):
        driver = PoseSpaceTissueDriver(**dict(raw)).validated()
        value = float(pose_values.get(driver.driver_id, 0.0))
        response = math.exp(-0.5 * ((value - driver.center) / driver.width) ** 2) * driver.gain
        raw_map = pose_maps.get(driver.driver_id)
        if isinstance(raw_map, Mapping):
            raw_map = DeformationWeightMap.from_dict(dict(raw_map))
        driver_map = (
            xp.asarray(raw_map.values, dtype=xp.float32)
            if isinstance(raw_map, DeformationWeightMap) else xp.ones(count, dtype=xp.float32)
        )
        if len(driver_map) != count:
            raise ValueError(f"Pose map {driver.driver_id} must match the vertex count.")
        weighted = float(response) * driver_map
        effective += weighted
        bulge_scale += weighted * (float(driver.bulge_scale) - 1.0)
        stiffness_scale += weighted * (float(driver.stiffness_scale) - 1.0)
    effective = xp.clip(effective, 0.0, 1.0)
    bulge_scale = xp.maximum(0.0, bulge_scale)
    stiffness_scale = xp.maximum(0.0, stiffness_scale)

    if normals:
        normal = xp.asarray(normals, dtype=xp.float32).reshape((-1, 3))
        if len(normal) != count:
            raise ValueError("Muscle normals must match the vertex count.")
    else:
        normal = target - xp.mean(target, axis=0)
    normal_length = xp.linalg.norm(normal, axis=1)
    normal = normal / xp.maximum(normal_length[:, None], 1.0e-12)
    normal = xp.where(
        (normal_length > 1.0e-12)[:, None], normal,
        xp.asarray((1.0, 0.0, 0.0), dtype=xp.float32),
    )
    fiber = xp.asarray(settings.fiber_direction, dtype=xp.float32)
    fiber /= xp.maximum(xp.linalg.norm(fiber), 1.0e-12)
    centroid = xp.mean(target, axis=0) if count else xp.zeros(3, dtype=xp.float32)
    along = (target - centroid) @ fiber
    driven = target - fiber * (along * effective * float(settings.contraction))[:, None]
    driven += normal * (effective * float(settings.bulge) * bulge_scale)[:, None]
    metrics = _muscle_metrics(xp, effective, state, readback)
    if not state.initialized:
        state.positions[...] = driven
        state.velocities.fill(0.0)
        state.previous_targets[...] = target
        state.initialized = True
        return driven.copy(), metrics, 0

    frame_dt = max(0.0, float(dt))
    driver_motion = xp.max(xp.linalg.norm(target - state.previous_targets, axis=1)) if count else xp.asarray(0.0)
    teleport = driver_motion > float(settings.teleport_distance) if settings.teleport_distance > 0.0 else xp.asarray(False)
    if frame_dt > 0.0:
        target_velocity = (target - state.previous_targets) * (float(settings.inertial_follow) / frame_dt)
        step_dt = frame_dt / max(1, substeps)
        stiffness = float(settings.stiffness) * (
            1.0 + effective * float(settings.activation_stiffness) * stiffness_scale
        )
        for _ in range(max(1, substeps)):
            acceleration = (
                (driven - state.positions) * stiffness[:, None]
                - (state.velocities - target_velocity) * float(settings.damping)
            ) / float(settings.mass)
            state.velocities += acceleration * step_dt
            state.positions += state.velocities * step_dt
            _limit_offsets(xp, state, target, float(settings.max_offset), target_velocity)
        state.positions = xp.where(teleport, driven, state.positions)
        state.velocities = xp.where(teleport, xp.zeros_like(state.velocities), state.velocities)
    state.previous_targets[...] = target
    teleport_count = _scalar(xp, teleport) if readback else 0
    state.teleport_count += teleport_count
    metrics = _muscle_metrics(xp, effective, state, readback)
    return state.positions.copy(), metrics, teleport_count


def _muscle_metrics(xp, activation, state, readback):
    if not readback:
        return {"mean": 0.0, "maximum": 0.0, "active_vertices": 0,
                "kinetic_energy": 0.0, "readback_deferred": True}
    return {
        "mean": float(_host(xp, xp.mean(activation))),
        "maximum": float(_host(xp, xp.max(activation))) if len(activation) else 0.0,
        "active_vertices": _scalar(xp, xp.count_nonzero(activation > 1.0e-4)),
        "kinetic_energy": float(_host(xp, 0.5 * xp.sum(state.velocities * state.velocities))),
        "readback_deferred": False,
    }


def _jiggle(xp, target, influence, state, settings, dt, colliders, substeps, *, readback):
    if not state.initialized:
        state.positions[...] = target
        state.velocities.fill(0.0)
        state.previous_targets[...] = target
        state.initialized = True
        return target.copy(), 0, len(target) if readback else 0
    if dt <= 0.0:
        return target + (state.positions - target) * influence, 0, 0
    axes = xp.asarray(settings.axis_weights, dtype=xp.float32)
    target_velocity = (target - state.previous_targets) * (float(settings.follow) / dt)
    step_dt = dt / max(1, substeps)
    contacts = 0
    for _ in range(max(1, substeps)):
        previous = state.positions.copy()
        acceleration = (
            (target - state.positions) * float(settings.stiffness)
            - (state.velocities - target_velocity) * float(settings.damping)
        ) * axes / float(settings.mass)
        acceleration += xp.asarray(settings.gravity, dtype=xp.float32) * axes
        state.velocities += acceleration * step_dt
        relative = state.velocities - target_velocity
        speed = xp.linalg.norm(relative, axis=1)
        scale = xp.minimum(1.0, float(settings.max_velocity) / xp.maximum(speed, 1.0e-12)) if settings.max_velocity else 1.0
        relative *= scale[:, None] if hasattr(scale, "ndim") else scale
        state.velocities = target_velocity + relative
        state.positions += state.velocities * step_dt
        state.positions = target + (state.positions - target) * axes
        state.velocities = target_velocity + (state.velocities - target_velocity) * axes
        _limit_offsets(xp, state, target, float(settings.max_offset), target_velocity, axes=axes)
        state.positions, state.velocities, count = _collide(
            xp, state.positions, state.velocities, previous, float(settings.collision_radius),
            float(settings.friction), float(settings.restitution), colliders, readback,
        )
        contacts += count
    settled = (
        (xp.linalg.norm(state.velocities - target_velocity, axis=1) <= float(settings.settle_speed))
        & (xp.linalg.norm(state.positions - target, axis=1) <= float(settings.settle_speed))
    )
    state.positions = xp.where(settled[:, None], target, state.positions)
    state.velocities = xp.where(settled[:, None], target_velocity, state.velocities)
    state.previous_targets[...] = target
    settled_count = _scalar(xp, xp.count_nonzero(settled)) if readback else 0
    return target + (state.positions - target) * influence, contacts, settled_count


def _flesh(xp, target, influence, state, settings, dt, edges, normals, colliders, substeps, *, readback):
    if not state.initialized:
        state.positions[...] = target
        state.velocities.fill(0.0)
        state.previous_targets[...] = target
        state.initialized = True
        return target.copy(), 0
    edge_signature = tuple(tuple(sorted((int(edge[0]), int(edge[1])))) for edge in edges if len(edge) >= 2)
    if edge_signature != state.edge_signature:
        state.edge_signature = edge_signature
        state.edge_indices = xp.asarray(edge_signature, dtype=xp.int64).reshape((-1, 2))
    normal_array = xp.asarray(normals, dtype=xp.float32).reshape((-1, 3)) if normals else None
    if normal_array is not None:
        normal_array /= xp.maximum(xp.linalg.norm(normal_array, axis=1)[:, None], 1.0e-12)
    step_dt = max(0.0, dt) / max(1, substeps)
    contacts = 0
    for _ in range(max(1, substeps)):
        previous = state.positions.copy()
        shape_force = xp.zeros_like(state.positions)
        if state.edge_indices is not None and len(state.edge_indices):
            first, second = state.edge_indices[:, 0], state.edge_indices[:, 1]
            offsets = state.positions - target
            delta = offsets[second] - offsets[first]
            counts = xp.zeros(len(target), dtype=xp.float32)
            xp.add.at(shape_force, first, delta)
            xp.add.at(shape_force, second, -delta)
            xp.add.at(counts, first, 1.0)
            xp.add.at(counts, second, 1.0)
            shape_force /= xp.maximum(counts[:, None], 1.0)
            shape_force *= float(settings.shape_stiffness)
        acceleration = (
            (target - state.positions) * float(settings.stiffness)
            - state.velocities * float(settings.damping) + shape_force
        ) / float(settings.mass)
        acceleration += xp.asarray(settings.gravity, dtype=xp.float32)
        state.velocities += acceleration * step_dt
        state.positions += state.velocities * step_dt
        _limit_offsets(xp, state, target, float(settings.max_offset), None)
        if normal_array is not None and float(settings.volume_preservation) > 0.0:
            signed = xp.sum((state.positions - target) * normal_array, axis=1)
            state.positions -= normal_array * (float(settings.volume_preservation) * xp.mean(signed))
        state.positions, state.velocities, count = _collide(
            xp, state.positions, state.velocities, previous, float(settings.collision_radius),
            float(settings.friction), float(settings.restitution), colliders, readback,
        )
        contacts += count
    state.previous_targets[...] = target
    return target + (state.positions - target) * influence, contacts


def _limit_offsets(xp, state, target, maximum, target_velocity, *, axes=None):
    if maximum <= 0.0:
        return
    offset = state.positions - target
    if axes is not None:
        offset = offset * axes
    distance = xp.linalg.norm(offset, axis=1)
    mask = distance > maximum
    state.positions = xp.where(mask[:, None], target + offset * (maximum / xp.maximum(distance, 1.0e-12))[:, None], state.positions)
    reference = xp.zeros_like(state.velocities) if target_velocity is None else target_velocity
    state.velocities = xp.where(mask[:, None], reference + (state.velocities - reference) * 0.45, state.velocities)


def _collide(xp, position, velocity, previous, radius, friction, restitution, colliders, readback):
    contacts = 0
    for collider in colliders:
        kind = str(collider.get("type") or "sphere").lower()
        contact_friction = max(0.0, float(collider.get("friction", friction)))
        contact_restitution = max(0.0, float(collider.get("restitution", restitution)))
        normal = xp.zeros_like(position)
        mask = xp.zeros(len(position), dtype=xp.bool_)
        if kind == "plane":
            direction = xp.asarray(collider.get("normal", (0.0, 1.0, 0.0)), dtype=xp.float32)
            direction /= xp.maximum(xp.linalg.norm(direction), 1.0e-12)
            signed = position @ direction - float(collider.get("offset", 0.0))
            mask = signed < radius
            position = xp.where(mask[:, None], position + (radius - signed)[:, None] * direction, position)
            normal[...] = direction
        elif kind == "sphere":
            center = xp.asarray(collider.get("center", (0.0, 0.0, 0.0)), dtype=xp.float32)
            minimum = max(0.0, float(collider.get("radius", 1.0))) + radius
            delta = position - center
            distance = xp.linalg.norm(delta, axis=1)
            normal = delta / xp.maximum(distance[:, None], 1.0e-12)
            normal = xp.where((distance > 1.0e-12)[:, None], normal, xp.asarray((0.0, 1.0, 0.0), dtype=xp.float32))
            mask = distance < minimum
            position = xp.where(mask[:, None], center + normal * minimum, position)
        elif kind == "capsule":
            start = xp.asarray(collider.get("start", collider.get("a", (0.0, -0.5, 0.0))), dtype=xp.float32)
            end = xp.asarray(collider.get("end", collider.get("b", (0.0, 0.5, 0.0))), dtype=xp.float32)
            segment = end - start
            amount = xp.clip(((position - start) @ segment) / xp.maximum(xp.sum(segment * segment), 1.0e-12), 0.0, 1.0)
            closest = start + amount[:, None] * segment
            delta = position - closest
            distance = xp.linalg.norm(delta, axis=1)
            minimum = max(0.0, float(collider.get("radius", 0.5))) + radius
            normal = delta / xp.maximum(distance[:, None], 1.0e-12)
            normal = xp.where((distance > 1.0e-12)[:, None], normal, xp.asarray((0.0, 0.0, 1.0), dtype=xp.float32))
            mask = distance < minimum
            position = xp.where(mask[:, None], closest + normal * minimum, position)
        elif kind in {"box", "aabb"}:
            center = xp.asarray(collider.get("center", (0.0, 0.0, 0.0)), dtype=xp.float32)
            half = xp.maximum(0.0, xp.asarray(collider.get("half_extents", collider.get("extents", (0.5, 0.5, 0.5))), dtype=xp.float32)) + radius
            local = position - center
            mask = xp.all(xp.abs(local) < half, axis=1)
            axis = xp.argmin(half - xp.abs(local), axis=1)
            sign = xp.where(local[xp.arange(len(position)), axis] < 0.0, -1.0, 1.0)
            normal[xp.arange(len(position)), axis] = sign
            corrected = position.copy()
            corrected[xp.arange(len(position)), axis] = center[axis] + sign * half[axis]
            position = xp.where(mask[:, None], corrected, position)
        if readback:
            contacts += _scalar(xp, xp.count_nonzero(mask))
        normal_speed = xp.sum(velocity * normal, axis=1)
        normal_velocity = normal * normal_speed[:, None]
        response = normal_velocity * xp.where(normal_speed < 0.0, -contact_restitution, 1.0)[:, None]
        response += (velocity - normal_velocity) * max(0.0, 1.0 - contact_friction)
        velocity = xp.where(mask[:, None], response, velocity)
    return position, velocity, contacts


def _host(xp, value):
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value).copy()


def _scalar(xp, value):
    return int(xp.asnumpy(value)) if hasattr(xp, "asnumpy") else int(value)


__all__ = [
    "DeformationLodController", "GpuBlendShapeState", "GpuSecondaryMotionState", "evaluate_gpu_deformation_stack",
]
