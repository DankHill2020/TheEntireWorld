"""Persistent CuPy-compatible GPU particle executor with explicit native fallback."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np

from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import compute_provider
from tech_connector.game_engine.runtime.tc_simulation_gpu_constraints_service import (
    GpuConstraintBuffers,
    MAX_PAIRWISE_PARTICLES,
    solve_gpu_constraints,
    solve_gpu_pairwise_neighbors,
)
from tech_connector.game_engine.runtime.tc_simulation_gpu_volume_service import step_gpu_sparse_volumes
from tech_connector.game_engine.runtime.tc_simulation_gpu_pic_service import solve_gpu_pic_grids
from tech_connector.game_engine.runtime.tc_simulation_gpu_magnetic_service import solve_gpu_magnetic_grids


@dataclass
class GpuParticleBuffers:
    provider_id: str
    capacity: int = 0
    count: int = 0
    reallocations: int = 0

    def __post_init__(self) -> None:
        self.arrays: dict[str, Any] = {}

    def reserve(self, count: int) -> None:
        if count <= self.capacity:
            return
        provider = compute_provider(self.provider_id)
        capacity = max(int(count), max(256, self.capacity * 2))
        specs = {
            "positions": ((capacity, 3), "float32"), "velocities": ((capacity, 3), "float32"),
            "mass": ((capacity,), "float32"), "charge": ((capacity,), "float32"),
            "collision_group": ((capacity,), "int32"), "collision_mask": ((capacity,), "int32"),
            "collision_priority": ((capacity,), "float32"),
            "radii": ((capacity,), "float32"), "dynamic": ((capacity,), "bool"),
            "alive": ((capacity,), "bool"), "inverse_mass": ((capacity,), "float32"),
            "damping": ((capacity,), "float32"), "adhesion": ((capacity,), "float32"),
            "material_id": ((capacity,), "int32"), "viscosity": ((capacity,), "float32"),
            "cohesion": ((capacity,), "float32"), "surface_tension": ((capacity,), "float32"),
            "yield_strength": ((capacity,), "float32"), "stringiness": ((capacity,), "float32"),
        }
        self.arrays = {name: provider.allocate(shape, dtype) for name, (shape, dtype) in specs.items()}
        self.capacity = capacity
        self.reallocations += 1

    def upload(self, world: Any) -> None:
        provider = compute_provider(self.provider_id)
        xp = provider.array_module
        particles = list(world.particles)
        self.reserve(len(particles))
        self.count = len(particles)
        if not particles:
            return
        materials = world.materials
        material_names = {name: index for index, name in enumerate(sorted({item.material for item in particles}))}
        values = {
            "positions": np.asarray([item.position for item in particles], dtype=np.float32),
            "velocities": np.asarray([item.velocity for item in particles], dtype=np.float32),
            "mass": np.asarray([item.inertial_mass for item in particles], dtype=np.float32),
            "charge": np.asarray([item.charge for item in particles], dtype=np.float32),
            "collision_group": np.asarray([item.collision_group for item in particles], dtype=np.int32),
            "collision_mask": np.asarray([item.collision_mask for item in particles], dtype=np.int32),
            "collision_priority": np.asarray([item.collision_priority for item in particles], dtype=np.float32),
            "radii": np.asarray([item.radius for item in particles], dtype=np.float32),
            "dynamic": np.asarray([
                item.alive and not item.pinned and not item.frozen and item.inverse_mass > 0.0 for item in particles
            ], dtype=np.bool_),
            "alive": np.asarray([item.alive for item in particles], dtype=np.bool_),
            "inverse_mass": np.asarray([item.inverse_mass for item in particles], dtype=np.float32),
            "damping": np.asarray([
                getattr(materials.get(item.material), "damping", 0.01) for item in particles
            ], dtype=np.float32),
            "adhesion": np.asarray([
                getattr(materials.get(item.material), "adhesion", 0.0) for item in particles
            ], dtype=np.float32),
            "material_id": np.asarray([material_names[item.material] for item in particles], dtype=np.int32),
            "viscosity": np.asarray([getattr(materials.get(item.material), "viscosity", 0.0)
                                     for item in particles], dtype=np.float32),
            "cohesion": np.asarray([getattr(materials.get(item.material), "cohesion", 0.0)
                                    for item in particles], dtype=np.float32),
            "surface_tension": np.asarray([getattr(materials.get(item.material), "surface_tension", 0.0)
                                           for item in particles], dtype=np.float32),
            "yield_strength": np.asarray([getattr(materials.get(item.material), "yield_strength", 0.0)
                                          for item in particles], dtype=np.float32),
            "stringiness": np.asarray([getattr(materials.get(item.material), "stringiness", 0.0)
                                       for item in particles], dtype=np.float32),
        }
        for name, value in values.items():
            self.arrays[name].handle[:self.count] = xp.asarray(value)
            self.arrays[name].revision += 1

    def download(self, world: Any) -> None:
        if self.count == 0:
            return
        provider = compute_provider(self.provider_id)
        positions = _host(provider.array_module, self.arrays["positions"].handle[:self.count]).tolist()
        velocities = _host(provider.array_module, self.arrays["velocities"].handle[:self.count]).tolist()
        for particle, position, velocity in zip(world.particles, positions, velocities):
            particle.position = tuple(float(value) for value in position)
            particle.velocity = tuple(float(value) for value in velocity)

    @property
    def memory_bytes(self) -> int:
        return sum(item.nbytes for item in self.arrays.values())


def gpu_backend_support(world: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if getattr(getattr(world, "interactions", None), "enabled", False):
        reasons.append("GPU long/short-range particle interaction kernels are not installed")
    if world.volume_constraints:
        reasons.append("GPU ragged volume-constraint kernel is not installed")
    if any(item.plastic_yield > 0.0 or item.reformable for item in world.constraints):
        reasons.append("GPU plastic/reformable distance constraints are not installed")
    if any(item.break_threshold > 0.0 for item in world.attachments):
        reasons.append("GPU breakable attachments are not installed")
    mesh_triangles = sum(max(0, len(face) - 2) for collider in world.mesh_colliders for face in collider.faces)
    if mesh_triangles * max(1, len(world.particles)) > 2_000_000:
        reasons.append("GPU mesh collision workload exceeds the qualified 2M particle-triangle bound")
    if any((world.curve_fields, world.deformable_surfaces, world.reformable_settings)):
        reasons.append("GPU coupled-domain kernels are not installed")
    supported_fields = {
        "gravity", "wind", "uniform", "gravity_source", "point_gravity", "radial", "repulsor",
        "attractor", "vortex", "turbulence", "drag", "linear_drag", "quadratic_drag", "buoyancy",
        "electric", "electric_field", "magnetic", "magnetic_field", "radiation", "radiation_pressure",
        "coriolis", "rotating_frame",
    }
    unsupported = sorted({str(item.field_type).lower() for item in world.fields} - supported_fields)
    if unsupported:
        reasons.append("unsupported GPU fields: " + ", ".join(unsupported))
    used = {particle.material for particle in world.particles if particle.alive}
    has_material_neighbors = any(
        material is not None and (material.viscosity > 0.0 or material.cohesion > 0.0)
        for name in used for material in (world.materials.get(name),)
    )
    if (world.self_collision or has_material_neighbors) and len(world.particles) > MAX_PAIRWISE_PARTICLES:
        reasons.append(f"GPU pairwise broadphase is capped at {MAX_PAIRWISE_PARTICLES} particles")
    return not reasons, reasons


def execute_gpu_compute(compiled: Any, world: Any, dt: float, *, provider_id: str = "cupy_cuda") -> dict[str, Any]:
    provider = compute_provider(provider_id)
    supported, reasons = gpu_backend_support(world)
    if not provider.status.available or not supported:
        if not provider.status.available:
            reasons.insert(0, provider.status.reason or f"{provider_id} is unavailable")
        from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import execute_native_cpu
        receipt = dict(execute_native_cpu(compiled, world, dt))
        receipt.setdefault("fallback_reasons", []).extend(reasons)
        return receipt

    from tech_connector.game_engine.runtime.tc_effect_system_service import finish_effect_step, prepare_effect_step

    timings: dict[str, float] = {}
    started = time.perf_counter()
    world.debug_contacts.clear()
    if world.effect_system is not None:
        prepare_effect_step(world.effect_system, world, float(dt))
    world._emit_geometry(float(dt))
    timings["prepare_emit"] = (time.perf_counter() - started) * 1000.0
    buffers = getattr(world, "_gpu_particle_buffers", None)
    if not isinstance(buffers, GpuParticleBuffers) or buffers.provider_id != provider_id:
        buffers = GpuParticleBuffers(provider_id)
        world._gpu_particle_buffers = buffers
    constraint_buffers = getattr(world, "_gpu_constraint_buffers", None)
    if not isinstance(constraint_buffers, GpuConstraintBuffers) or constraint_buffers.provider_id != provider_id:
        constraint_buffers = GpuConstraintBuffers(provider_id)
        world._gpu_constraint_buffers = constraint_buffers
    resident_output = bool(compiled.metadata.get("gpu_resident_output", False) and world.effect_system is None)
    reused = bool(resident_output and getattr(world, "_gpu_buffers_authoritative", False)
                  and buffers.count == len(world.particles))
    uploaded = time.perf_counter()
    if not reused:
        buffers.upload(world)
    constraint_buffers.upload(world, force=not reused)
    timings["host_to_device"] = (time.perf_counter() - uploaded) * 1000.0
    solved = time.perf_counter()
    substeps = max(1, int(compiled.metadata.get("compiled_substeps", world.substeps)))
    constraint_iterations = next(
        (max(1, int(stage.iterations)) for stage in compiled.stages if stage.stage_id == "constraints"), 1
    )
    used_materials = {particle.material for particle in world.particles if particle.alive}
    material_neighbors = any(
        material is not None and (material.viscosity > 0.0 or material.cohesion > 0.0)
        for name in used_materials for material in (world.materials.get(name),)
    )
    sub_dt = max(0.0, float(dt)) / substeps
    pair_metrics = {"self_collision_pairs": 0, "material_neighbor_pairs": 0, "broadphase_candidates": 0}
    pic_acceleration, pic_receipt = solve_gpu_pic_grids(
        world, buffers, provider, readback=not resident_output,
    ) if world.pic_grids else (
        provider.array_module.zeros((buffers.count, 3), dtype=provider.array_module.float32),
        {"gpu_pic_ms": 0.0, "gpu_pic_cells": 0, "gpu_pic_memory_bytes": 0,
         "gpu_pic_grids": [], "gpu_pic_resident": False, "gpu_pic_reused_state": False},
    )
    timings["gpu_pic"] = float(pic_receipt["gpu_pic_ms"])
    magnetic_field_sample, magnetic_receipt = solve_gpu_magnetic_grids(
        world, buffers, provider, float(dt), readback=not resident_output,
    ) if world.magnetic_grids else (
        provider.array_module.zeros((buffers.count, 3), dtype=provider.array_module.float32),
        {"gpu_magnetic_ms": 0.0, "gpu_magnetic_cells": 0, "gpu_magnetic_memory_bytes": 0,
         "gpu_magnetic_grids": [], "gpu_magnetic_resident": False,
         "gpu_magnetic_reused_state": False},
    )
    timings["gpu_magnetic"] = float(magnetic_receipt["gpu_magnetic_ms"])
    solved = time.perf_counter()
    for substep_index in range(substeps):
        world._field_time_seconds = world.time_seconds + substep_index * sub_dt
        step_metrics = _gpu_particle_step(
            provider.array_module, buffers, constraint_buffers, world, sub_dt, constraint_iterations,
            material_neighbors=material_neighbors, pic_acceleration=pic_acceleration,
            magnetic_field_sample=magnetic_field_sample,
        )
        for key in pair_metrics:
            pair_metrics[key] += step_metrics[key]
    world.__dict__.pop("_field_time_seconds", None)
    volume_receipt = step_gpu_sparse_volumes(
        world, float(dt), provider_id,
        resident_output=bool(compiled.metadata.get("gpu_volume_resident_output", False)),
    ) if world.volumes else {
        "gpu_volume_ms": 0.0, "gpu_volume_cells": 0, "gpu_volume_memory_bytes": 0,
        "gpu_volume_buffer_reallocations": 0, "gpu_volume_resident": False,
        "gpu_volume_reused_resident_state": False, "gpu_volume_synchronization_points": 0,
    }
    timings["gpu_integrate_collide"] = (time.perf_counter() - solved) * 1000.0
    timings["gpu_sparse_volume"] = float(volume_receipt["gpu_volume_ms"])
    readback = time.perf_counter()
    if resident_output:
        world._gpu_buffers_authoritative = True
    else:
        provider.synchronize()
        buffers.download(world)
        constraint_buffers.download_mutable_state(world)
        world._gpu_buffers_authoritative = False
    timings["device_to_host"] = (time.perf_counter() - readback) * 1000.0
    world.time_seconds += float(dt)
    if world.effect_system is not None:
        finish_effect_step(world.effect_system, world, float(dt))
    return {
        "execution_backend": "gpu_compute", "stage_ms": timings,
        "memory_bytes": buffers.memory_bytes + constraint_buffers.memory_bytes
                        + int(volume_receipt["gpu_volume_memory_bytes"])
                        + int(pic_receipt["gpu_pic_memory_bytes"])
                        + int(magnetic_receipt["gpu_magnetic_memory_bytes"]),
        "dispatches": substeps, "compute_provider": provider_id, "buffer_residency": "persistent_device",
        "buffer_capacity": buffers.capacity, "buffer_count": buffers.count,
        "buffer_reallocations": buffers.reallocations, "resident_output": resident_output,
        "reused_resident_state": reused, "synchronization_points": 0 if reused else (1 if resident_output else 2),
        "debug_contact_readback_deferred": True, "constraint_iterations": constraint_iterations,
        "gpu_dihedral_constraints": len(getattr(world, "bending_constraints", ())),
        "gpu_strain_constraints": sum(
            float(getattr(item, "strain_limit", 0.0)) > 1.0 for item in world.constraints
        ),
        "gpu_collision_layers": list(getattr(world, "cloth_settings", {}).get("collision_layers", [])),
        "constraint_memory_bytes": constraint_buffers.memory_bytes, **pair_metrics, **volume_receipt,
        **pic_receipt, **magnetic_receipt,
        "supported_stages": (
            ["particle_integration"]
            + (["pic_charge_deposit", "pic_poisson", "pic_field_sample"] if world.pic_grids else [])
            + (["magnetic_velocity_deposit", "magnetic_induction", "magnetic_divergence_clean",
                "magnetic_lorentz_sample"] if world.magnetic_grids else [])
            + (["dihedral_bending"] if getattr(world, "bending_constraints", None) else [])
            + (["hard_strain_limit"] if any(
                float(getattr(item, "strain_limit", 0.0)) > 1.0 for item in world.constraints
            ) else [])
            + (["layered_cloth_collision"] if bool(
                getattr(world, "cloth_settings", {}).get("layered_collision", False)
                or getattr(world, "cloth_settings", {}).get("exclude_topological_neighbors", False)
            ) else [])
        ),
    }


def _gpu_particle_step(
    xp: Any,
    buffers: GpuParticleBuffers,
    constraints: GpuConstraintBuffers,
    world: Any,
    dt: float,
    constraint_iterations: int,
    *,
    material_neighbors: bool,
    pic_acceleration: Any,
    magnetic_field_sample: Any,
) -> dict[str, int]:
    count = buffers.count
    if count == 0 or dt <= 0.0:
        return {"self_collision_pairs": 0, "material_neighbor_pairs": 0, "broadphase_candidates": 0}
    position = buffers.arrays["positions"].handle[:count]
    velocity = buffers.arrays["velocities"].handle[:count]
    dynamic = buffers.arrays["dynamic"].handle[:count]
    previous = position.copy()
    velocity[dynamic] += (
        _gpu_field_acceleration(
            xp, world, position, velocity,
            buffers.arrays["mass"].handle[:count], buffers.arrays["charge"].handle[:count],
            buffers.arrays["radii"].handle[:count],
        ) + pic_acceleration + xp.cross(velocity, magnetic_field_sample) * (
            buffers.arrays["charge"].handle[:count]
            / xp.maximum(buffers.arrays["mass"].handle[:count], 1.0e-30)
        )[:, None]
    )[dynamic] * dt
    position[dynamic] += velocity[dynamic] * dt
    constraints.begin_substep()
    pair_metrics = {"self_collision_pairs": 0, "material_neighbor_pairs": 0, "broadphase_candidates": 0}
    bending_iterations = max(0, int(getattr(world, "cloth_settings", {}).get(
        "dihedral_iterations_per_substep", constraint_iterations,
    )))
    for iteration_index in range(max(1, int(constraint_iterations))):
        solve_gpu_constraints(
            xp, buffers, constraints, world, dt,
            solve_bending=iteration_index < bending_iterations,
        )
        metrics = solve_gpu_pairwise_neighbors(
            xp, buffers, world, dt, self_collision=bool(world.self_collision),
            material_neighbors=material_neighbors, constraints=constraints,
        )
        for key in pair_metrics:
            pair_metrics[key] += metrics[key]
    radii = buffers.arrays["radii"].handle[:count]
    normals = xp.zeros_like(position)
    surface_velocity = xp.zeros_like(position)
    friction = xp.zeros(count, dtype=xp.float32)
    restitution = xp.zeros(count, dtype=xp.float32)
    collided = xp.zeros(count, dtype=xp.bool_)
    for collider in world.plane_colliders:
        normal = xp.asarray(collider.normal, dtype=xp.float32)
        normal_length = xp.linalg.norm(normal)
        normal = xp.where(
            normal_length > 1.0e-12, normal / xp.maximum(normal_length, 1.0e-12),
            xp.asarray((0.0, 1.0, 0.0), dtype=xp.float32),
        )
        signed = position @ normal - float(collider.offset)
        mask = dynamic & (signed < radii)
        position[mask] += (radii[mask] - signed[mask])[:, None] * normal
        normals[mask] = normal
        friction[mask] = max(0.0, float(collider.friction))
        restitution[mask] = max(0.0, float(collider.restitution))
        collided |= mask
    for collider in world.sphere_colliders:
        center = xp.asarray(collider.center, dtype=xp.float32)
        delta = position - center
        distance = xp.linalg.norm(delta, axis=1)
        minimum = radii + max(0.0, float(collider.radius))
        mask = dynamic & (distance < minimum)
        sphere_normals = delta / xp.maximum(distance[:, None], 1.0e-12)
        sphere_normals = xp.where(
            (distance > 1.0e-12)[:, None], sphere_normals,
            xp.asarray((0.0, 1.0, 0.0), dtype=xp.float32),
        )
        position[mask] = center + sphere_normals[mask] * minimum[mask, None]
        normals[mask] = sphere_normals[mask]
        friction[mask] = max(0.0, float(collider.friction))
        restitution[mask] = max(0.0, float(collider.restitution))
        collided |= mask
    _gpu_mesh_collisions(
        xp, buffers, world, dynamic, normals, surface_velocity, friction, restitution, collided, dt
    )
    velocity[dynamic] = (position[dynamic] - previous[dynamic]) / max(1.0e-12, dt)
    damping = buffers.arrays["damping"].handle[:count]
    velocity[dynamic] *= xp.maximum(0.0, 1.0 - damping[dynamic] * dt)[:, None]
    relative_velocity = velocity - surface_velocity
    normal_speed = xp.sum(relative_velocity * normals, axis=1)
    normal_velocity = normals * normal_speed[:, None]
    response = normal_velocity * xp.where(normal_speed < 0.0, -restitution, 1.0)[:, None]
    response += (relative_velocity - normal_velocity) * xp.maximum(0.0, 1.0 - friction)[:, None]
    response += surface_velocity
    adhesion = buffers.arrays["adhesion"].handle[:count]
    velocity[collided] = response[collided] * xp.exp(-adhesion[collided] * dt)[:, None]
    velocity[~dynamic] = 0.0
    return pair_metrics


def _gpu_mesh_collisions(
    xp: Any,
    buffers: GpuParticleBuffers,
    world: Any,
    dynamic: Any,
    normals: Any,
    surface_velocity: Any,
    friction: Any,
    restitution: Any,
    collided: Any,
    dt: float,
) -> None:
    count = buffers.count
    if count == 0:
        return
    position = buffers.arrays["positions"].handle[:count]
    radii = buffers.arrays["radii"].handle[:count]
    for collider in world.mesh_colliders:
        vertices = np.asarray(collider.vertices, dtype=np.float32)
        best_distance = radii.copy()
        best_point = position.copy()
        best_normal = xp.zeros_like(position)
        for raw_face in collider.faces:
            face = tuple(int(index) for index in raw_face)
            for offset in range(1, len(face) - 1):
                a, b, c = (xp.asarray(vertices[index], dtype=xp.float32)
                           for index in (face[0], face[offset], face[offset + 1]))
                point = _gpu_closest_points_triangle(xp, position, a, b, c)
                delta = position - point
                distance = xp.linalg.norm(delta, axis=1)
                raw_normal = xp.cross(b - a, c - a)
                raw_normal /= xp.maximum(xp.linalg.norm(raw_normal), 1.0e-12)
                oriented = xp.where(
                    (xp.sum(delta * raw_normal, axis=1) < 0.0)[:, None], -raw_normal, raw_normal
                )
                closer = distance < best_distance
                best_distance = xp.where(closer, distance, best_distance)
                best_point = xp.where(closer[:, None], point, best_point)
                best_normal = xp.where(closer[:, None], oriented, best_normal)
        mask = dynamic & (best_distance < radii)
        collider_velocity = xp.asarray(collider.velocity, dtype=xp.float32)
        tangent = collider_velocity - best_normal * xp.sum(collider_velocity * best_normal, axis=1)[:, None]
        corrected = best_point + best_normal * radii[:, None]
        corrected += tangent * max(0.0, float(collider.friction)) * dt
        position[mask] = corrected[mask]
        normals[mask] = best_normal[mask]
        surface_velocity[mask] = collider_velocity
        friction[mask] = max(0.0, float(collider.friction))
        restitution[mask] = max(0.0, float(collider.restitution))
        collided |= mask


def _gpu_closest_points_triangle(xp: Any, points: Any, a: Any, b: Any, c: Any) -> Any:
    normal = xp.cross(b - a, c - a)
    normal /= xp.maximum(xp.linalg.norm(normal), 1.0e-12)
    projected = points - xp.sum((points - a) * normal, axis=1)[:, None] * normal
    v0, v1 = b - a, c - a
    v2 = projected - a
    d00, d01, d11 = xp.dot(v0, v0), xp.dot(v0, v1), xp.dot(v1, v1)
    denominator = xp.maximum(d00 * d11 - d01 * d01, 1.0e-12)
    u = (d11 * xp.sum(v2 * v0, axis=1) - d01 * xp.sum(v2 * v1, axis=1)) / denominator
    v = (d00 * xp.sum(v2 * v1, axis=1) - d01 * xp.sum(v2 * v0, axis=1)) / denominator
    inside = (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0)
    ab = _gpu_closest_points_segment(xp, points, a, b)
    bc = _gpu_closest_points_segment(xp, points, b, c)
    ca = _gpu_closest_points_segment(xp, points, c, a)
    candidates = xp.stack((ab, bc, ca), axis=1)
    distances = xp.linalg.norm(points[:, None, :] - candidates, axis=2)
    nearest = xp.argmin(distances, axis=1)
    edge_point = candidates[xp.arange(len(points)), nearest]
    return xp.where(inside[:, None], projected, edge_point)


def _gpu_closest_points_segment(xp: Any, points: Any, first: Any, second: Any) -> Any:
    segment = second - first
    amount = xp.sum((points - first) * segment, axis=1) / xp.maximum(xp.dot(segment, segment), 1.0e-12)
    return first + xp.clip(amount, 0.0, 1.0)[:, None] * segment


def _gpu_field_acceleration(
    xp: Any, world: Any, position: Any, velocity: Any, masses: Any, charges: Any, radii: Any,
) -> Any:
    acceleration = xp.zeros_like(position)
    indices = xp.arange(len(position), dtype=xp.float32)
    for force in world.fields:
        if not getattr(force, "enabled", True):
            continue
        kind = str(force.field_type or "gravity").lower()
        vector = xp.asarray(force.vector, dtype=xp.float32)
        delta = position - xp.asarray(force.center, dtype=xp.float32)
        distance = xp.linalg.norm(delta, axis=1)
        radius = max(0.0, float(force.radius))
        inner = min(radius, max(0.0, float(getattr(force, "inner_radius", 0.0))))
        falloff = xp.ones(len(position), dtype=xp.float32) if radius <= 0.0 else xp.maximum(
            0.0, 1.0 - xp.maximum(0.0, distance - inner) / max(1.0e-12, radius - inner)
        ) ** max(0.01, float(getattr(force, "falloff_power", 1.0)))
        contribution = xp.zeros_like(position)
        if kind in {"gravity", "wind", "uniform"}:
            gust = 1.0 + float(getattr(force, "gust_strength", 0.0)) * math.sin(
                float(getattr(force, "frequency", 1.0))
                * float(getattr(world, "_field_time_seconds", world.time_seconds)) * math.tau + float(force.seed)
            )
            contribution = vector * (float(force.strength) * gust * falloff)[:, None]
            if kind == "wind" and float(getattr(force, "drag", 0.0)) > 0.0:
                contribution = (vector * (float(force.strength) * gust) - velocity) * (
                    float(force.drag) * falloff
                )[:, None]
        elif kind in {"gravity_source", "point_gravity", "radial", "repulsor", "attractor"}:
            fallback = (0.0, -1.0, 0.0) if kind in {"gravity_source", "point_gravity"} else (0.0, 1.0, 0.0)
            normal = _gpu_normalized_rows(xp, delta, fallback)
            if kind in {"gravity_source", "point_gravity"}:
                softening = max(1.0e-4, float(force.vector[0]))
                strength = float(force.strength) / xp.maximum(
                    softening * softening, distance * distance + softening * softening
                )
                contribution = -normal * (strength * falloff)[:, None]
            else:
                sign = -1.0 if kind == "attractor" else 1.0
                contribution = normal * (sign * float(force.strength) * falloff)[:, None]
        elif kind == "vortex":
            axis_length = xp.linalg.norm(vector)
            axis = xp.where(
                axis_length > 1.0e-12, vector / xp.maximum(axis_length, 1.0e-12),
                xp.asarray((0.0, 1.0, 0.0), dtype=xp.float32),
            )
            tangent = xp.cross(xp.broadcast_to(axis, delta.shape), delta)
            tangent = _gpu_normalized_rows(xp, tangent, (1.0, 0.0, 0.0))
            contribution = tangent * (float(force.strength) * falloff)[:, None]
        elif kind == "turbulence":
            phase = float(force.seed) * 17.17 + indices * 0.754877666
            sample = position * max(1.0e-6, float(getattr(force, "noise_scale", 1.0)))
            time_phase = float(getattr(world, "_field_time_seconds", world.time_seconds)) * max(
                0.0, float(getattr(force, "frequency", 1.0))
            )
            contribution = xp.stack((
                xp.sin((sample[:, 1] + phase * 1.37) * 1.73 + (sample[:, 2] + phase * 2.11) * 0.63 + time_phase * 2.03),
                xp.sin((sample[:, 2] + phase * 2.11) * 1.31 + (sample[:, 0] + phase) * 0.79 + time_phase * 1.71),
                xp.sin((sample[:, 0] + phase) * 1.57 + (sample[:, 1] + phase * 1.37) * 0.91 + time_phase * 2.29),
            ), axis=1) * (float(force.strength) * falloff)[:, None]
        elif kind in {"drag", "linear_drag"}:
            contribution = (vector - velocity) * (float(force.strength) * falloff)[:, None]
        elif kind == "quadratic_drag":
            relative = velocity - vector
            contribution = -relative * (float(force.strength) * xp.linalg.norm(relative, axis=1) * falloff)[:, None]
        elif kind == "buoyancy":
            densities = xp.asarray([
                max(1.0e-6, float(world.materials.get(item.material).density))
                if world.materials.get(item.material) is not None else 1000.0
                for item in world.particles[:len(position)]
            ], dtype=xp.float32)
            direction_length = xp.linalg.norm(vector)
            direction = xp.where(
                direction_length > 1.0e-12, vector / xp.maximum(direction_length, 1.0e-12),
                xp.asarray((0.0, 1.0, 0.0), dtype=xp.float32),
            )
            density_ratio = max(0.0, float(getattr(force, "ambient_density", 1.225))) / densities
            contribution = direction * (float(force.strength) * density_ratio * falloff)[:, None]
        elif kind in {"electric", "electric_field"}:
            contribution = vector * (
                float(force.strength) * charges / xp.maximum(masses, 1.0e-30) * falloff
            )[:, None]
        elif kind in {"magnetic", "magnetic_field"}:
            contribution = xp.cross(velocity, vector) * (
                float(force.strength) * charges / xp.maximum(masses, 1.0e-30) * falloff
            )[:, None]
        elif kind in {"radiation", "radiation_pressure"}:
            direction = vector / xp.maximum(xp.linalg.norm(vector), 1.0e-12)
            contribution = direction * (
                float(force.strength) * math.pi * radii * radii / xp.maximum(masses, 1.0e-30) * falloff
            )[:, None]
        elif kind in {"coriolis", "rotating_frame"}:
            omega = vector * float(force.strength)
            relative = position - xp.asarray(force.center, dtype=xp.float32)
            contribution = (
                -2.0 * xp.cross(xp.broadcast_to(omega, velocity.shape), velocity)
                - xp.cross(xp.broadcast_to(omega, relative.shape), xp.cross(xp.broadcast_to(omega, relative.shape), relative))
            ) * falloff[:, None]
        maximum = max(0.0, float(getattr(force, "max_acceleration", 0.0)))
        if maximum > 0.0:
            lengths = xp.linalg.norm(contribution, axis=1)
            contribution *= xp.minimum(1.0, maximum / xp.maximum(lengths, 1.0e-12))[:, None]
        acceleration += contribution
    return acceleration


def _host(xp: Any, value: Any) -> np.ndarray:
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value)


def synchronize_gpu_particles(world: Any) -> bool:
    buffers = getattr(world, "_gpu_particle_buffers", None)
    if not isinstance(buffers, GpuParticleBuffers) or not getattr(world, "_gpu_buffers_authoritative", False):
        return False
    buffers.download(world)
    world._gpu_buffers_authoritative = False
    return True


def gpu_particle_view(world: Any) -> dict[str, Any] | None:
    """Expose resident provider buffers without triggering host synchronization."""
    buffers = getattr(world, "_gpu_particle_buffers", None)
    if not isinstance(buffers, GpuParticleBuffers):
        return None
    view = slice(0, buffers.count)
    return {
        name: item.handle[view]
        for name, item in buffers.arrays.items()
    } | {
        "count": buffers.count,
        "capacity": buffers.capacity,
        "residency": "persistent_device",
        "provider_id": buffers.provider_id,
        "authoritative": bool(getattr(world, "_gpu_buffers_authoritative", False)),
        "revisions": {name: int(item.revision) for name, item in buffers.arrays.items()},
    }


def _gpu_normalized_rows(xp: Any, values: Any, fallback: tuple[float, float, float]) -> Any:
    lengths = xp.linalg.norm(values, axis=1)
    normalized = values / xp.maximum(lengths[:, None], 1.0e-12)
    return xp.where(
        (lengths > 1.0e-12)[:, None], normalized,
        xp.asarray(fallback, dtype=xp.float32),
    )


def install_gpu_compute_backend(provider_id: str = "cupy_cuda") -> bool:
    from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
        SimulationBackendCapabilities, register_simulation_backend, register_simulation_executor,
    )
    provider = compute_provider(provider_id)
    available = bool(provider.status.available and provider.status.device_type == "gpu")
    if not available:
        try:
            from tech_connector.game_engine.runtime.tc_gpu_compute_service import install_native_gpu_backend
            install_native_gpu_backend()
            return True
        except (ImportError, OSError, RuntimeError):
            pass
    register_simulation_backend(SimulationBackendCapabilities(
        "gpu_compute", available, "gpu",
        ("cloth", "softbody", "fluid", "particle", "granular", "volume", "rigid", "effect", "surface"),
        True, True, True, 20_000_000,
        (f"Persistent {provider_id} GPU particle executor; unsupported domains fall back to native CPU."
         if available else provider.status.reason),
    ))
    if available:
        register_simulation_executor(
            "gpu_compute", lambda compiled, world, dt: execute_gpu_compute(
                compiled, world, dt, provider_id=provider_id
            )
        )
    return available


__all__ = [
    "GpuParticleBuffers", "execute_gpu_compute", "gpu_backend_support", "gpu_particle_view",
    "install_gpu_compute_backend", "synchronize_gpu_particles",
]
