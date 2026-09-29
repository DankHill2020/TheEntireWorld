"""Persistent NumPy structure-of-arrays executor for production particle/effect ticks."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np

from tech_connector.game_engine.runtime.tc_simulation_native_constraints_service import (
    NativeConstraintBuffers,
    solve_native_constraints,
    solve_native_material_neighbors,
    solve_native_self_collision,
)
from tech_connector.game_engine.runtime.tc_simulation_native_volume_service import (
    step_native_sparse_volumes,
    synchronize_native_sparse_volumes,
)


@dataclass
class NativeParticleBuffers:
    capacity: int = 0
    count: int = 0
    reallocations: int = 0

    def __post_init__(self) -> None:
        self.positions = np.empty((0, 3), dtype=np.float64)
        self.velocities = np.empty((0, 3), dtype=np.float64)
        self.radii = np.empty(0, dtype=np.float64)
        self.inverse_mass = np.empty(0, dtype=np.float64)
        self.mass = np.empty(0, dtype=np.float64)
        self.charge = np.empty(0, dtype=np.float64)
        self.dynamic = np.empty(0, dtype=np.bool_)
        self.alive = np.empty(0, dtype=np.bool_)
        self.damping = np.empty(0, dtype=np.float64)
        self.adhesion = np.empty(0, dtype=np.float64)

    def reserve(self, count: int) -> None:
        if count <= self.capacity:
            return
        capacity = max(int(count), max(256, self.capacity * 2))
        self.positions = np.empty((capacity, 3), dtype=np.float64)
        self.velocities = np.empty((capacity, 3), dtype=np.float64)
        self.radii = np.empty(capacity, dtype=np.float64)
        self.inverse_mass = np.empty(capacity, dtype=np.float64)
        self.mass = np.empty(capacity, dtype=np.float64)
        self.charge = np.empty(capacity, dtype=np.float64)
        self.dynamic = np.empty(capacity, dtype=np.bool_)
        self.alive = np.empty(capacity, dtype=np.bool_)
        self.damping = np.empty(capacity, dtype=np.float64)
        self.adhesion = np.empty(capacity, dtype=np.float64)
        self.capacity = capacity
        self.reallocations += 1

    def upload(self, world: Any) -> None:
        particles = list(world.particles)
        self.reserve(len(particles))
        self.count = len(particles)
        if not particles:
            return
        view = slice(0, self.count)
        self.positions[view] = np.asarray([item.position for item in particles], dtype=np.float64)
        self.velocities[view] = np.asarray([item.velocity for item in particles], dtype=np.float64)
        self.radii[view] = [float(item.radius) for item in particles]
        self.inverse_mass[view] = [float(item.inverse_mass) for item in particles]
        self.mass[view] = [float(item.inertial_mass) for item in particles]
        self.charge[view] = [float(item.charge) for item in particles]
        self.alive[view] = [bool(item.alive) for item in particles]
        self.dynamic[view] = [
            bool(item.alive and not item.pinned and not item.frozen and item.inverse_mass > 0.0)
            for item in particles
        ]
        materials = world.materials
        self.damping[view] = [float(getattr(materials.get(item.material), "damping", 0.01)) for item in particles]
        self.adhesion[view] = [float(getattr(materials.get(item.material), "adhesion", 0.0)) for item in particles]

    def download(self, world: Any) -> None:
        # ndarray.tolist performs the scalar conversion in C and is materially faster
        # than iterating NumPy row views for the object-model compatibility boundary.
        positions = self.positions[:self.count].tolist()
        velocities = self.velocities[:self.count].tolist()
        for particle, position, velocity in zip(world.particles, positions, velocities):
            particle.position = tuple(position)
            particle.velocity = tuple(velocity)

    @property
    def memory_bytes(self) -> int:
        arrays = (self.positions, self.velocities, self.radii, self.inverse_mass, self.mass, self.charge,
                  self.dynamic, self.alive, self.damping, self.adhesion)
        return sum(int(value.nbytes) for value in arrays)


def native_backend_support(world: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if getattr(world, "bending_constraints", None):
        reasons.append("true dihedral cloth bending is currently reference-authoritative")
    if any(float(getattr(item, "strain_limit", 0.0)) > 1.0 for item in world.constraints):
        reasons.append("hard cloth strain limiting is currently reference-authoritative")
    if bool(getattr(world, "cloth_settings", {}).get("exclude_topological_neighbors", False)) or any(
        int(getattr(item, "collision_group", 1)) != 1
        or int(getattr(item, "collision_mask", -1)) != -1
        or float(getattr(item, "collision_priority", 0.0)) != 0.0
        for item in world.particles
    ):
        reasons.append("layered cloth collision filtering is currently reference-authoritative")
    if getattr(world, "pic_grids", None):
        reasons.append("electrostatic PIC grid coupling is currently reference-authoritative")
    if getattr(world, "magnetic_grids", None):
        reasons.append("magnetic induction grid coupling is currently reference-authoritative")
    if str(getattr(world.interactions, "collision_mode", "none")).lower() != "none":
        reasons.append("particle merge/collision topology is currently reference-authoritative")
    if world.curve_fields:
        reasons.append("curve-field kernel is not installed")
    unsupported_surfaces = [
        surface for surface in world.deformable_surfaces
        if not (
            type(surface).__name__ == "OceanSurface"
            and callable(getattr(surface, "step", None))
            and callable(getattr(surface, "mesh_patch", None))
        )
    ]
    if unsupported_surfaces:
        reasons.append("deformable-surface coupling kernel is not installed")
    for particle in world.particles:
        material = world.materials.get(particle.material)
        if material is None or not particle.alive:
            continue
        thermal_change = (
            (particle.temperature >= material.ignition_temperature and particle.fuel > 0.0 and material.burn_rate > 0.0)
            or (particle.temperature <= material.freeze_temperature and not particle.frozen)
            or (particle.temperature > material.freeze_temperature and particle.frozen)
            or (particle.material == "metal" and particle.temperature >= material.melt_temperature
                and particle.state != "molten")
        )
        if thermal_change:
            reasons.append("thermal state-transition kernel is not installed")
            break
    supported_fields = {
        "gravity", "wind", "uniform", "gravity_source", "point_gravity", "radial", "repulsor",
        "attractor", "vortex", "turbulence", "drag", "linear_drag", "quadratic_drag", "buoyancy",
        "electric", "electric_field", "magnetic", "magnetic_field", "radiation", "radiation_pressure",
        "coriolis", "rotating_frame",
    }
    unsupported_fields = sorted({str(item.field_type).lower() for item in world.fields} - supported_fields)
    if unsupported_fields:
        reasons.append("unsupported fields: " + ", ".join(unsupported_fields))
    return not reasons, reasons


def execute_native_cpu(compiled: Any, world: Any, dt: float) -> dict[str, Any]:
    """Run supported worlds with persistent vector buffers; explicitly fall back otherwise."""
    world.scale.validate()
    if getattr(world, "_gpu_buffers_authoritative", False):
        from tech_connector.game_engine.runtime.tc_gpu_compute_service import synchronize_gpu_world
        if not synchronize_gpu_world(world):
            from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import synchronize_gpu_particles
            synchronize_gpu_particles(world)
    if getattr(world, "_gpu_volumes_authoritative", False):
        from tech_connector.game_engine.runtime.tc_simulation_gpu_volume_service import synchronize_gpu_sparse_volumes
        synchronize_gpu_sparse_volumes(world)
    supported, reasons = native_backend_support(world)
    if not supported:
        synchronize_native_particles(world)
        synchronize_native_sparse_volumes(world)
        from tech_connector.game_engine.runtime.tc_simulation_ir_service import execute_compiled_reference
        started = time.perf_counter()
        execute_compiled_reference(compiled, world, dt)
        elapsed = (time.perf_counter() - started) * 1000.0
        return {"execution_backend": "reference_cpu", "fallback_reasons": reasons,
                "stage_ms": {"reference_fallback": elapsed}, "memory_bytes": 0,
                "dispatches": 1, "buffer_residency": "host_objects"}

    from tech_connector.game_engine.runtime.tc_effect_system_service import finish_effect_step, prepare_effect_step

    timings: dict[str, float] = {}
    started = time.perf_counter()
    world.debug_contacts.clear()
    if world.effect_system is not None:
        prepare_effect_step(world.effect_system, world, float(dt))
    world._emit_geometry(float(dt))
    if world.reformable_settings:
        synchronize_native_particles(world)
        world._update_reformable_bonds()
    timings["prepare_emit"] = (time.perf_counter() - started) * 1000.0

    buffers = getattr(world, "_native_particle_buffers", None)
    if not isinstance(buffers, NativeParticleBuffers):
        buffers = NativeParticleBuffers()
        world._native_particle_buffers = buffers
    constraint_buffers = getattr(world, "_native_constraint_buffers", None)
    if not isinstance(constraint_buffers, NativeConstraintBuffers):
        constraint_buffers = NativeConstraintBuffers()
        world._native_constraint_buffers = constraint_buffers
    uploaded = time.perf_counter()
    resident_output = bool(
        compiled.metadata.get("native_resident_output", False)
        and world.effect_system is None and not world.reformable_settings
    )
    reused_resident_state = bool(
        resident_output and getattr(world, "_native_buffers_authoritative", False)
        and buffers.count == len(world.particles)
    )
    if not reused_resident_state:
        buffers.upload(world)
    constraint_buffers.upload(world, force=not reused_resident_state)
    timings["buffer_upload"] = (time.perf_counter() - uploaded) * 1000.0

    solved = time.perf_counter()
    substeps = max(
        1, int(compiled.metadata.get("compiled_substeps", world.substeps)),
        int(world.resolved_substeps(float(dt))),
    )
    sub_dt = max(0.0, float(dt)) / substeps
    constraint_iterations = next(
        (max(1, int(stage.iterations)) for stage in compiled.stages if stage.stage_id == "constraints"),
        max(1, int(world.constraint_iterations)),
    )
    kernel_metrics = {"integration_ms": 0.0, "constraint_ms": 0.0, "collision_ms": 0.0,
                      "material_neighbor_ms": 0.0, "material_pairs": 0, "self_collision_pairs": 0,
                      "constraint_iterations_executed": 0}
    neighbor_particles = [
        particle for particle in world.particles
        if particle.alive and str(getattr(particle, "phase", "")).lower() not in {
            "cloth", "softbody", "rigid_cluster"
        }
    ]
    used_material_names = {particle.material for particle in neighbor_particles}
    material_neighbors_enabled = any(
        material is not None and (material.viscosity > 0.0 or material.cohesion > 0.0)
        for name in used_material_names for material in (world.materials.get(name),)
    )
    for substep_index in range(substeps):
        world._field_time_seconds = world.time_seconds + substep_index * sub_dt
        receipt = _step_buffers(
            buffers, constraint_buffers, world, sub_dt, constraint_iterations,
            material_neighbors_enabled=material_neighbors_enabled,
            execution_profile=str(compiled.profile.name),
        )
        for key in kernel_metrics:
            kernel_metrics[key] += receipt[key]
    world.__dict__.pop("_field_time_seconds", None)
    timings["integrate_collide"] = (time.perf_counter() - solved) * 1000.0
    timings.update({key: float(value) for key, value in kernel_metrics.items() if key.endswith("_ms")})
    constraint_buffers.download_mutable_state(world)
    volume_receipt = step_native_sparse_volumes(
        world, float(dt),
        resident_output=bool(compiled.metadata.get("native_volume_resident_output", False)),
    ) if world.volumes else {
        "volume_ms": 0.0, "volume_cells": 0, "volume_memory_bytes": 0,
        "volume_buffer_reallocations": 0, "volume_residency": "none",
        "volume_resident_output": False, "volume_reused_resident_state": False,
        "volume_synchronization_points": 0,
    }
    timings["sparse_volume"] = float(volume_receipt["volume_ms"])

    surface_started = time.perf_counter()
    surface_outputs: dict[str, Any] = {}
    for surface_index, surface in enumerate(world.deformable_surfaces):
        surface.step(float(dt))
        patch = surface.mesh_patch(rows=32, columns=32)
        surface_outputs[f"ocean_surface_{surface_index}"] = patch
    if surface_outputs:
        world._native_surface_outputs = surface_outputs
    else:
        world.__dict__.pop("_native_surface_outputs", None)
    timings["surface_generation"] = (time.perf_counter() - surface_started) * 1000.0

    downloaded = time.perf_counter()
    if resident_output:
        world._native_buffers_authoritative = True
    else:
        buffers.download(world)
        world._native_buffers_authoritative = False
    timings["buffer_download"] = (time.perf_counter() - downloaded) * 1000.0
    world.time_seconds += float(dt)
    if world.effect_system is not None:
        finish_effect_step(world.effect_system, world, float(dt))
    timings["finish_events"] = (time.perf_counter() - downloaded) * 1000.0 - timings["buffer_download"]
    return {"execution_backend": "native_cpu", "stage_ms": timings,
            "memory_bytes": buffers.memory_bytes + constraint_buffers.memory_bytes
                            + int(volume_receipt["volume_memory_bytes"])
                            + sum(
                                len(output.get("vertices", ())) * 28
                                + len(output.get("triangles", ())) * 12
                                for output in surface_outputs.values()
                            ),
            "dispatches": int(kernel_metrics["constraint_iterations_executed"]) + substeps,
            "compute_provider": "numpy_cpu",
            "synchronization_points": 0 if reused_resident_state else (1 if resident_output else 2),
            "resident_output": resident_output, "reused_resident_state": reused_resident_state,
            "constraint_iterations": constraint_iterations,
            "constraint_colors": len(constraint_buffers.distance_colors) + len(constraint_buffers.area_colors),
            "constraint_buffer_reallocations": constraint_buffers.reallocations,
            "material_neighbor_pairs": int(kernel_metrics["material_pairs"]),
            "self_collision_pairs": int(kernel_metrics["self_collision_pairs"]),
            **volume_receipt,
            "surface_output_count": len(surface_outputs),
            "buffer_residency": "persistent_host_soa", "buffer_capacity": buffers.capacity,
            "buffer_count": buffers.count, "buffer_reallocations": buffers.reallocations}


def _step_buffers(
    buffers: NativeParticleBuffers,
    constraint_buffers: NativeConstraintBuffers,
    world: Any,
    dt: float,
    constraint_iterations: int,
    *,
    material_neighbors_enabled: bool,
    execution_profile: str,
) -> dict[str, float | int]:
    count = buffers.count
    empty = {"integration_ms": 0.0, "constraint_ms": 0.0, "collision_ms": 0.0,
             "material_neighbor_ms": 0.0, "material_pairs": 0, "self_collision_pairs": 0,
             "constraint_iterations_executed": 0}
    if count == 0 or dt <= 0.0:
        return empty
    view = slice(0, count)
    position = buffers.positions[view]
    velocity = buffers.velocities[view]
    dynamic = buffers.dynamic[view]
    previous = position.copy()
    started = time.perf_counter()
    acceleration = _field_acceleration(
        world, position, velocity, buffers.mass[view], buffers.charge[view], buffers.radii[view]
    )
    acceleration += _particle_interaction_acceleration(
        world, position, buffers.mass[view], buffers.charge[view], buffers.alive[view]
    )
    velocity[dynamic] += acceleration[dynamic] * dt
    position[dynamic] += velocity[dynamic] * dt
    integration_ms = (time.perf_counter() - started) * 1000.0
    collision_normal = np.zeros_like(position)
    collision_friction = np.zeros(count, dtype=np.float64)
    collision_restitution = np.zeros(count, dtype=np.float64)
    collision_surface_velocity = np.zeros_like(position)
    collided = np.zeros(count, dtype=np.bool_)
    constraint_buffers.begin_substep(world)
    constraint_ms = collision_ms = neighbor_ms = 0.0
    material_pairs = 0
    self_collision_pairs = 0
    iterations_executed = 0
    adaptive_small_topology = bool(
        count <= 256
        and not material_neighbors_enabled
        and len(getattr(world, "constraints", ())) + len(getattr(world, "area_constraints", ())) <= 512
    )
    # Profile-specific positional tolerances avoid low-value tail iterations
    # while retaining a tighter offline solve. At the default metre scale the
    # realtime tolerance is 0.75 mm, below a rendered pixel for ordinary
    # gameplay cameras; cinematic remains at 0.01 mm.
    profile_tolerance = {
        "retro": 1.5e-3, "mobile": 1.0e-3, "toony": 7.5e-4,
        "stylized": 7.5e-4, "realtime": 7.5e-4,
        "photoreal": 2.5e-4, "cinematic": 1.0e-5,
    }.get(str(execution_profile).lower(), 2.5e-4)
    convergence_tolerance = max(
        1.0e-6, float(getattr(world.scale, "distance_unit_meters", 1.0)) * profile_tolerance
    )
    self_collision_active = bool(world.self_collision)
    for _ in range(max(1, int(constraint_iterations))):
        before_constraints = position.copy() if adaptive_small_topology else None
        started = time.perf_counter()
        solve_native_constraints(buffers, constraint_buffers, world, dt)
        if self_collision_active:
            solved_pairs = solve_native_self_collision(
                buffers, world,
                lambda points, normals, penetration, kind: _record_contacts(
                    world, points, normals, penetration, kind
                ),
            )
            self_collision_pairs += solved_pairs
            # A broadphase with no overlaps remains valid for the rest of this
            # structural iteration group; only constraint projection occurs
            # between passes and cannot create a new high-speed contact.
            if solved_pairs == 0:
                self_collision_active = False
        constraint_ms += (time.perf_counter() - started) * 1000.0
        iterations_executed += 1
        if material_neighbors_enabled:
            started = time.perf_counter()
            material_pairs += solve_native_material_neighbors(buffers, world, dt)
            neighbor_ms += (time.perf_counter() - started) * 1000.0
        if before_constraints is not None:
            displacement = position - before_constraints
            maximum_correction = float(np.sqrt(np.max(np.sum(displacement * displacement, axis=1), initial=0.0)))
            if maximum_correction <= convergence_tolerance:
                break
    # Contact projection follows the XPBD structural solve. Repeating a static
    # collider pass for every structural iteration only reapplies the same
    # projection and scales dispatch cost with an unrelated quality control.
    started = time.perf_counter()
    _solve_native_colliders(
        buffers, world, dynamic, collision_normal, collision_friction,
        collision_restitution, collision_surface_velocity, collided, dt,
    )
    collision_ms += (time.perf_counter() - started) * 1000.0
    velocity[dynamic] = (position[dynamic] - previous[dynamic]) / max(1.0e-12, dt)
    velocity[dynamic] *= np.maximum(0.0, 1.0 - buffers.damping[view][dynamic] * dt)[:, None]
    if np.any(collided):
        surface_velocity = collision_surface_velocity[collided]
        selected_velocity = velocity[collided] - surface_velocity
        normals = collision_normal[collided]
        normal_speed = np.sum(selected_velocity * normals, axis=1)
        normal_velocity = normals * normal_speed[:, None]
        tangent = selected_velocity - normal_velocity
        scale = np.where(normal_speed < 0.0, -collision_restitution[collided], 1.0)
        velocity[collided] = surface_velocity + normal_velocity * scale[:, None] + tangent * np.maximum(
            0.0, 1.0 - collision_friction[collided]
        )[:, None]
        velocity[collided] *= np.exp(-buffers.adhesion[view][collided] * dt)[:, None]
    velocity[~dynamic] = 0.0
    return {"integration_ms": integration_ms, "constraint_ms": constraint_ms,
            "collision_ms": collision_ms, "material_neighbor_ms": neighbor_ms,
            "material_pairs": material_pairs, "self_collision_pairs": self_collision_pairs,
            "constraint_iterations_executed": iterations_executed}


def _solve_native_colliders(
    buffers: NativeParticleBuffers,
    world: Any,
    dynamic: Any,
    collision_normal: Any,
    collision_friction: Any,
    collision_restitution: Any,
    collision_surface_velocity: Any,
    collided: Any,
    dt: float,
) -> None:
    position = buffers.positions[:buffers.count]
    radii = buffers.radii[:buffers.count]
    for collider in world.plane_colliders:
        normal = _normalized(np.asarray(collider.normal, dtype=np.float64), np.asarray((0.0, 1.0, 0.0)))
        signed = position @ normal - float(collider.offset)
        mask = dynamic & (signed < radii)
        if np.any(mask):
            penetration = radii[mask] - signed[mask]
            position[mask] += penetration[:, None] * normal
            collision_normal[mask] = normal
            collision_friction[mask] = max(0.0, float(collider.friction))
            collision_restitution[mask] = max(0.0, float(collider.restitution))
            collided[mask] = True
            _record_contacts(world, position[mask] - normal * radii[mask, None], normal, penetration, "plane")
    for collider in world.sphere_colliders:
        center = np.asarray(collider.center, dtype=np.float64)
        delta = position - center
        distance = np.linalg.norm(delta, axis=1)
        minimum = radii + max(0.0, float(collider.radius))
        mask = dynamic & (distance < minimum)
        if np.any(mask):
            normals = np.zeros((int(np.count_nonzero(mask)), 3), dtype=np.float64)
            selected_distance = distance[mask]
            valid = selected_distance > 1.0e-12
            normals[valid] = delta[mask][valid] / selected_distance[valid, None]
            normals[~valid] = (0.0, 1.0, 0.0)
            penetration = minimum[mask] - selected_distance
            position[mask] = center + normals * minimum[mask, None]
            collision_normal[mask] = normals
            collision_friction[mask] = max(0.0, float(collider.friction))
            collision_restitution[mask] = max(0.0, float(collider.restitution))
            collided[mask] = True
            _record_contacts(world, center + normals * float(collider.radius), normals, penetration, "sphere")
    for collider in world.mesh_colliders:
        acceleration = collider.acceleration()
        vertices = np.asarray(collider.vertices, dtype=np.float64)
        surface_velocity = np.asarray(collider.velocity, dtype=np.float64)
        for index in np.flatnonzero(dynamic).tolist():
            query = acceleration.query_sphere(position[index], float(radii[index]))
            collider.record_query(query)
            closest_point = None
            closest_distance = float(radii[index])
            closest_normal = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
            for triangle_index in query.triangle_indices:
                face = acceleration.triangles[triangle_index]
                triangle = vertices[np.asarray(face, dtype=np.int64)]
                point = _closest_point_triangle(position[index], triangle[0], triangle[1], triangle[2])
                distance = float(np.linalg.norm(position[index] - point))
                if distance >= closest_distance:
                    continue
                closest_distance = distance
                closest_point = point
                raw_normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
                closest_normal = _normalized(raw_normal, closest_normal)
                if float(np.dot(position[index] - point, closest_normal)) < 0.0:
                    closest_normal *= -1.0
            if closest_point is None:
                continue
            penetration = float(radii[index]) - closest_distance
            _record_contacts(world, closest_point, closest_normal, np.asarray((penetration,)), "mesh")
            position[index] = closest_point + closest_normal * radii[index]
            tangent_velocity = surface_velocity - closest_normal * float(np.dot(surface_velocity, closest_normal))
            position[index] += tangent_velocity * max(0.0, float(collider.friction)) * dt
            collision_normal[index] = closest_normal
            collision_friction[index] = max(0.0, float(collider.friction))
            collision_restitution[index] = max(0.0, float(collider.restitution))
            collision_surface_velocity[index] = surface_velocity
            collided[index] = True


def _closest_point_triangle(point: Any, first: Any, second: Any, third: Any) -> Any:
    """Ericson closest-point regions, expressed on NumPy vectors."""
    ab = second - first
    ac = third - first
    ap = point - first
    d1, d2 = float(np.dot(ab, ap)), float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        return first
    bp = point - second
    d3, d4 = float(np.dot(ab, bp)), float(np.dot(ac, bp))
    if d3 >= 0.0 and d4 <= d3:
        return second
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return first + ab * (d1 / max(1.0e-12, d1 - d3))
    cp = point - third
    d5, d6 = float(np.dot(ab, cp)), float(np.dot(ac, cp))
    if d6 >= 0.0 and d5 <= d6:
        return third
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return first + ac * (d2 / max(1.0e-12, d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        edge = third - second
        return second + edge * ((d4 - d3) / max(1.0e-12, (d4 - d3) + (d5 - d6)))
    denominator = max(1.0e-12, va + vb + vc)
    return first + ab * (vb / denominator) + ac * (vc / denominator)


def _field_acceleration(world: Any, position, velocity, masses, charges, radii) -> Any:
    acceleration = np.zeros_like(position)
    indices = np.arange(len(position), dtype=np.float64)
    for force in world.fields:
        if not getattr(force, "enabled", True):
            continue
        kind = str(force.field_type or "gravity").lower()
        vector = np.asarray(force.vector, dtype=np.float64)
        center = np.asarray(force.center, dtype=np.float64)
        delta = position - center
        distance = np.linalg.norm(delta, axis=1)
        radius = max(0.0, float(force.radius))
        inner = min(radius, max(0.0, float(getattr(force, "inner_radius", 0.0))))
        falloff = np.ones(len(position)) if radius <= 0.0 else np.maximum(
            0.0, 1.0 - np.maximum(0.0, distance - inner) / max(1.0e-12, radius - inner)
        ) ** max(0.01, float(getattr(force, "falloff_power", 1.0)))
        contribution = np.zeros_like(position)
        if kind in {"gravity", "wind", "uniform"}:
            gust = 1.0 + float(getattr(force, "gust_strength", 0.0)) * math.sin(
                float(getattr(force, "frequency", 1.0))
                * float(getattr(world, "_field_time_seconds", world.time_seconds)) * math.tau + float(force.seed)
            )
            contribution = vector * (float(force.strength) * gust * falloff)[:, None]
            if kind == "wind" and float(getattr(force, "drag", 0.0)) > 0.0:
                target = vector * (float(force.strength) * gust)
                contribution = (target - velocity) * (float(force.drag) * falloff)[:, None]
        elif kind in {"gravity_source", "point_gravity"}:
            normal = _normalized_rows(delta, (0.0, -1.0, 0.0))
            softening = max(1.0e-4, float(vector[0]))
            strength = float(force.strength) / np.maximum(softening * softening, distance * distance + softening * softening)
            contribution = -normal * (strength * falloff)[:, None]
        elif kind in {"radial", "repulsor", "attractor"}:
            sign = -1.0 if kind == "attractor" else 1.0
            contribution = _normalized_rows(delta, (0.0, 1.0, 0.0)) * (
                sign * float(force.strength) * falloff
            )[:, None]
        elif kind == "vortex":
            axis = _normalized(vector, np.asarray((0.0, 1.0, 0.0)))
            tangent = _normalized_rows(np.cross(np.broadcast_to(axis, delta.shape), delta), (1.0, 0.0, 0.0))
            contribution = tangent * (float(force.strength) * falloff)[:, None]
        elif kind == "turbulence":
            phase = float(force.seed) * 17.17 + indices * 0.754877666
            sample = position * max(1.0e-6, float(getattr(force, "noise_scale", 1.0)))
            time_phase = float(getattr(world, "_field_time_seconds", world.time_seconds)) * max(
                0.0, float(getattr(force, "frequency", 1.0))
            )
            noise = np.column_stack((
                np.sin((sample[:, 1] + phase * 1.37) * 1.73 + (sample[:, 2] + phase * 2.11) * 0.63 + time_phase * 2.03),
                np.sin((sample[:, 2] + phase * 2.11) * 1.31 + (sample[:, 0] + phase) * 0.79 + time_phase * 1.71),
                np.sin((sample[:, 0] + phase) * 1.57 + (sample[:, 1] + phase * 1.37) * 0.91 + time_phase * 2.29),
            ))
            contribution = noise * (float(force.strength) * falloff)[:, None]
        elif kind in {"drag", "linear_drag"}:
            contribution = (vector - velocity) * (float(force.strength) * falloff)[:, None]
        elif kind == "quadratic_drag":
            relative = velocity - vector
            speed = np.linalg.norm(relative, axis=1)
            contribution = -relative * (float(force.strength) * speed * falloff)[:, None]
        elif kind == "buoyancy":
            densities = np.asarray([
                max(1.0e-6, float(world.materials.get(item.material).density))
                if world.materials.get(item.material) is not None else 1000.0
                for item in world.particles[:len(position)]
            ], dtype=np.float64)
            density_ratio = max(0.0, float(getattr(force, "ambient_density", 1.225))) / densities
            direction = _normalized(vector, np.asarray((0.0, 1.0, 0.0)))
            contribution = direction * (float(force.strength) * density_ratio * falloff)[:, None]
        elif kind in {"electric", "electric_field"}:
            charge_to_mass = np.divide(charges, masses, out=np.zeros_like(charges), where=np.isfinite(masses) & (masses > 0.0))
            contribution = vector * (float(force.strength) * charge_to_mass * falloff)[:, None]
        elif kind in {"magnetic", "magnetic_field"}:
            charge_to_mass = np.divide(charges, masses, out=np.zeros_like(charges), where=np.isfinite(masses) & (masses > 0.0))
            contribution = np.cross(velocity, vector) * (float(force.strength) * charge_to_mass * falloff)[:, None]
        elif kind in {"radiation", "radiation_pressure"}:
            area_to_mass = np.divide(np.pi * radii * radii, masses, out=np.zeros_like(masses), where=np.isfinite(masses) & (masses > 0.0))
            contribution = _normalized(vector, np.asarray((0.0, 1.0, 0.0))) * (
                float(force.strength) * area_to_mass * falloff
            )[:, None]
        elif kind in {"coriolis", "rotating_frame"}:
            omega = vector * float(force.strength)
            relative = position - center
            contribution = (
                -2.0 * np.cross(np.broadcast_to(omega, velocity.shape), velocity)
                - np.cross(np.broadcast_to(omega, relative.shape), np.cross(np.broadcast_to(omega, relative.shape), relative))
            ) * falloff[:, None]
        maximum = max(0.0, float(getattr(force, "max_acceleration", 0.0)))
        if maximum > 0.0:
            lengths = np.linalg.norm(contribution, axis=1)
            mask = lengths > maximum
            contribution[mask] *= (maximum / lengths[mask])[:, None]
        acceleration += contribution
    return acceleration


def _particle_interaction_acceleration(world: Any, position, masses, charges, alive) -> Any:
    """Vectorized-per-source exact kernel; deterministic reference for future tree/grid GPU stages."""
    settings = world.interactions
    acceleration = np.zeros_like(position)
    if not settings.enabled or len(position) < 2:
        return acceleration
    softening_sq = max(1.0e-30, float(settings.softening) ** 2)
    cutoff = max(0.0, float(settings.cutoff))
    source_threshold = max(0.0, float(getattr(settings, "gravity_source_mass_threshold", 0.0)))
    long_range_only = bool(settings.gravity_constant or settings.coulomb_constant) and not any(
        (settings.lennard_jones_epsilon, settings.yukawa_strength)
    )
    if (
        source_threshold <= 0.0 and long_range_only
        and settings.resolved_long_range_method(len(position)) == "barnes_hut"
    ):
        from tech_connector.game_engine.runtime.tc_nbody_acceleration_service import barnes_hut_accelerations

        values, receipt = barnes_hut_accelerations(position, masses, charges, alive, settings)
        world._interaction_diagnostics = receipt
        return np.asarray(values, dtype=np.float64)
    short_range_only = bool(settings.lennard_jones_epsilon or settings.yukawa_strength) and not any(
        (settings.gravity_constant, settings.coulomb_constant)
    )
    if (
        short_range_only and settings.cutoff > 0.0
        and settings.resolved_short_range_method(len(position)) == "spatial_hash"
    ):
        from tech_connector.game_engine.runtime.tc_short_range_interaction_service import spatial_hash_accelerations

        values, receipt = spatial_hash_accelerations(position, masses, alive, settings)
        world._interaction_diagnostics = receipt
        return np.asarray(values, dtype=np.float64)
    if (
        settings.gravity_constant and source_threshold > 0.0
        and not any((settings.coulomb_constant, settings.lennard_jones_epsilon, settings.yukawa_strength))
    ):
        targets = np.flatnonzero(alive)
        sources = np.flatnonzero(alive & (masses >= source_threshold))
        interaction_count = 0
        for source in sources:
            selected = targets[targets != source]
            interaction_count += len(selected)
            delta = position[source] - position[selected]
            distance_sq = np.sum(delta * delta, axis=1) + softening_sq
            distance = np.sqrt(distance_sq)
            if cutoff > 0.0:
                inside = distance <= cutoff
                selected, delta, distance_sq, distance = selected[inside], delta[inside], distance_sq[inside], distance[inside]
            if len(selected):
                acceleration[selected] += delta / np.maximum(1.0e-30, distance)[:, None] * (
                    float(settings.gravity_constant) * masses[source] / distance_sq
                )[:, None]
        maximum = max(0.0, float(settings.maximum_acceleration))
        if maximum > 0.0:
            lengths = np.linalg.norm(acceleration, axis=1)
            over = lengths > maximum
            acceleration[over] *= (maximum / lengths[over])[:, None]
        world._interaction_diagnostics = {
            "method": "dominant_source", "particles": int(len(targets)),
            "sources": int(len(sources)), "direct_interactions": int(interaction_count),
        }
        return acceleration
    world._interaction_diagnostics = {
        "method": "exact", "particles": int(np.count_nonzero(alive)), "direct_interactions": 0,
    }
    for first in range(len(position) - 1):
        if not alive[first]:
            continue
        indices = np.arange(first + 1, len(position))
        valid_alive = alive[indices]
        if not np.any(valid_alive):
            continue
        indices = indices[valid_alive]
        world._interaction_diagnostics["direct_interactions"] += len(indices)
        delta = position[indices] - position[first]
        distance_sq = np.sum(delta * delta, axis=1) + softening_sq
        distance = np.sqrt(distance_sq)
        if cutoff > 0.0:
            inside = distance <= cutoff
            indices, delta, distance_sq, distance = indices[inside], delta[inside], distance_sq[inside], distance[inside]
            if not len(indices):
                continue
        direction = delta / np.maximum(1.0e-30, distance)[:, None]
        first_scalar = np.zeros(len(indices), dtype=np.float64)
        second_scalar = np.zeros(len(indices), dtype=np.float64)
        if settings.gravity_constant:
            first_scalar += np.where(
                masses[indices] >= source_threshold,
                float(settings.gravity_constant) * masses[indices] / distance_sq, 0.0,
            )
            if masses[first] >= source_threshold:
                second_scalar -= float(settings.gravity_constant) * masses[first] / distance_sq
        if settings.coulomb_constant:
            force = -float(settings.coulomb_constant) * charges[first] * charges[indices] / distance_sq
            first_scalar += force / max(1.0e-30, masses[first])
            second_scalar -= force / np.maximum(1.0e-30, masses[indices])
        if settings.lennard_jones_epsilon:
            ratio = np.minimum(10.0, float(settings.lennard_jones_sigma) / np.maximum(1.0e-30, distance))
            ratio6 = ratio ** 6
            force = 24.0 * float(settings.lennard_jones_epsilon) * (2.0 * ratio6 * ratio6 - ratio6) / np.maximum(1.0e-30, distance)
            first_scalar -= force / max(1.0e-30, masses[first])
            second_scalar += force / np.maximum(1.0e-30, masses[indices])
        if settings.yukawa_strength:
            screening = max(0.0, float(settings.yukawa_screening))
            force = float(settings.yukawa_strength) * np.exp(-screening * distance) * (
                1.0 / distance_sq + screening / np.maximum(1.0e-30, distance)
            )
            first_scalar -= force / max(1.0e-30, masses[first])
            second_scalar += force / np.maximum(1.0e-30, masses[indices])
        acceleration[first] += np.sum(direction * first_scalar[:, None], axis=0)
        acceleration[indices] += direction * second_scalar[:, None]
    maximum = max(0.0, float(settings.maximum_acceleration))
    if maximum > 0.0:
        lengths = np.linalg.norm(acceleration, axis=1)
        over = lengths > maximum
        acceleration[over] *= (maximum / lengths[over])[:, None]
    return acceleration


def _record_contacts(world: Any, points, normals, penetration, kind: str) -> None:
    room = max(0, 4096 - len(world.debug_contacts))
    if room <= 0:
        return
    points = np.atleast_2d(points)[:room]
    normals = np.broadcast_to(normals, points.shape)[:room]
    penetration = np.atleast_1d(penetration)[:room]
    world.debug_contacts.extend({"point": tuple(map(float, point)), "normal": tuple(map(float, normal)),
                                 "penetration": max(0.0, float(depth)), "kind": kind}
                                for point, normal, depth in zip(points, normals, penetration))


def _normalized(value, fallback):
    length = float(np.linalg.norm(value))
    return value / length if length > 1.0e-12 else fallback


def _normalized_rows(values, fallback):
    result = np.zeros_like(values)
    lengths = np.linalg.norm(values, axis=1)
    valid = lengths > 1.0e-12
    result[valid] = values[valid] / lengths[valid, None]
    result[~valid] = fallback
    return result


def native_particle_view(world: Any) -> dict[str, Any] | None:
    """Return zero-copy native arrays for renderer/compute consumers when allocated."""
    buffers = getattr(world, "_native_particle_buffers", None)
    if not isinstance(buffers, NativeParticleBuffers):
        return None
    view = slice(0, buffers.count)
    return {
        "positions": buffers.positions[view], "velocities": buffers.velocities[view],
        "radii": buffers.radii[view], "mass": buffers.mass[view], "charge": buffers.charge[view],
        "alive": buffers.alive[view],
        "count": buffers.count, "capacity": buffers.capacity,
        "residency": "persistent_host_soa", "provider_id": "numpy_cpu",
    }


def synchronize_native_particles(world: Any) -> bool:
    """Explicitly read authoritative native state back into compatibility particle objects."""
    buffers = getattr(world, "_native_particle_buffers", None)
    if not isinstance(buffers, NativeParticleBuffers) or not getattr(world, "_native_buffers_authoritative", False):
        return False
    buffers.download(world)
    world._native_buffers_authoritative = False
    return True


def install_native_cpu_backend() -> None:
    from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
        SimulationBackendCapabilities, register_simulation_backend, register_simulation_executor,
    )
    register_simulation_backend(SimulationBackendCapabilities(
        "native_cpu", True, "cpu",
        ("cloth", "softbody", "fluid", "particle", "granular", "volume", "rigid", "effect", "surface"),
        True, True, True, 2_000_000,
        "Persistent NumPy SoA particles/effects with capability-gated reference fallback.",
    ))
    register_simulation_executor("native_cpu", execute_native_cpu)


__all__ = [
    "NativeParticleBuffers", "execute_native_cpu", "install_native_cpu_backend", "native_backend_support",
    "native_particle_view", "synchronize_native_particles",
]
