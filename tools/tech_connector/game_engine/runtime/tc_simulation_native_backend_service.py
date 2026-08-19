"""Persistent NumPy structure-of-arrays executor for production particle/effect ticks."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np


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
        arrays = (self.positions, self.velocities, self.radii, self.inverse_mass,
                  self.dynamic, self.alive, self.damping, self.adhesion)
        return sum(int(value.nbytes) for value in arrays)


def native_backend_support(world: Any) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if any((world.constraints, world.area_constraints, world.volume_constraints, world.attachments)):
        reasons.append("constraint kernels are not installed")
    if world.self_collision:
        reasons.append("particle self-collision kernel is not installed")
    if world.mesh_colliders:
        reasons.append("triangle-mesh collision kernel is not installed")
    if world.curve_fields:
        reasons.append("curve-field kernel is not installed")
    if world.volumes:
        reasons.append("sparse-volume kernel is not installed")
    if world.deformable_surfaces:
        reasons.append("deformable-surface coupling kernel is not installed")
    if world.reformable_settings:
        reasons.append("reformable bond kernel is not installed")
    used_materials = {
        particle.material: world.materials.get(particle.material)
        for particle in world.particles
        if particle.alive
    }
    interacting_materials = sorted(
        name for name, material in used_materials.items()
        if material is not None and (material.viscosity > 0.0 or material.cohesion > 0.0)
    )
    if interacting_materials:
        reasons.append("material-neighbor kernels are not installed: " + ", ".join(interacting_materials))
    supported_fields = {"gravity", "wind", "uniform", "gravity_source", "point_gravity", "radial", "vortex"}
    unsupported_fields = sorted({str(item.field_type).lower() for item in world.fields} - supported_fields)
    if unsupported_fields:
        reasons.append("unsupported fields: " + ", ".join(unsupported_fields))
    return not reasons, reasons


def execute_native_cpu(compiled: Any, world: Any, dt: float) -> dict[str, Any]:
    """Run supported worlds with persistent vector buffers; explicitly fall back otherwise."""
    supported, reasons = native_backend_support(world)
    if not supported:
        synchronize_native_particles(world)
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
    timings["prepare_emit"] = (time.perf_counter() - started) * 1000.0

    buffers = getattr(world, "_native_particle_buffers", None)
    if not isinstance(buffers, NativeParticleBuffers):
        buffers = NativeParticleBuffers()
        world._native_particle_buffers = buffers
    uploaded = time.perf_counter()
    resident_output = bool(compiled.metadata.get("native_resident_output", False) and world.effect_system is None)
    reused_resident_state = bool(
        resident_output and getattr(world, "_native_buffers_authoritative", False)
        and buffers.count == len(world.particles)
    )
    if not reused_resident_state:
        buffers.upload(world)
    timings["buffer_upload"] = (time.perf_counter() - uploaded) * 1000.0

    solved = time.perf_counter()
    substeps = max(1, int(compiled.metadata.get("compiled_substeps", world.substeps)))
    sub_dt = max(0.0, float(dt)) / substeps
    for _ in range(substeps):
        _step_buffers(buffers, world, sub_dt)
    timings["integrate_collide"] = (time.perf_counter() - solved) * 1000.0

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
            "memory_bytes": buffers.memory_bytes, "dispatches": substeps,
            "compute_provider": "numpy_cpu",
            "synchronization_points": 0 if reused_resident_state else (1 if resident_output else 2),
            "resident_output": resident_output, "reused_resident_state": reused_resident_state,
            "buffer_residency": "persistent_host_soa", "buffer_capacity": buffers.capacity,
            "buffer_count": buffers.count, "buffer_reallocations": buffers.reallocations}


def _step_buffers(buffers: NativeParticleBuffers, world: Any, dt: float) -> None:
    count = buffers.count
    if count == 0 or dt <= 0.0:
        return
    view = slice(0, count)
    position = buffers.positions[view]
    velocity = buffers.velocities[view]
    dynamic = buffers.dynamic[view]
    previous = position.copy()
    acceleration = _field_acceleration(world, position)
    velocity[dynamic] += acceleration[dynamic] * dt
    position[dynamic] += velocity[dynamic] * dt
    collision_normal = np.zeros_like(position)
    collision_friction = np.zeros(count, dtype=np.float64)
    collision_restitution = np.zeros(count, dtype=np.float64)
    collided = np.zeros(count, dtype=np.bool_)
    radii = buffers.radii[view]
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
    velocity[dynamic] = (position[dynamic] - previous[dynamic]) / max(1.0e-12, dt)
    velocity[dynamic] *= np.maximum(0.0, 1.0 - buffers.damping[view][dynamic] * dt)[:, None]
    if np.any(collided):
        selected_velocity = velocity[collided]
        normals = collision_normal[collided]
        normal_speed = np.sum(selected_velocity * normals, axis=1)
        normal_velocity = normals * normal_speed[:, None]
        tangent = selected_velocity - normal_velocity
        scale = np.where(normal_speed < 0.0, -collision_restitution[collided], 1.0)
        velocity[collided] = normal_velocity * scale[:, None] + tangent * np.maximum(
            0.0, 1.0 - collision_friction[collided]
        )[:, None]
        velocity[collided] *= np.exp(-buffers.adhesion[view][collided] * dt)[:, None]
    velocity[~dynamic] = 0.0


def _field_acceleration(world: Any, position) -> Any:
    acceleration = np.zeros_like(position)
    for force in world.fields:
        kind = str(force.field_type or "gravity").lower()
        vector = np.asarray(force.vector, dtype=np.float64)
        center = np.asarray(force.center, dtype=np.float64)
        delta = position - center
        distance = np.linalg.norm(delta, axis=1)
        falloff = np.ones(len(position)) if force.radius <= 0.0 else np.maximum(0.0, 1.0 - distance / force.radius)
        if kind in {"gravity", "wind", "uniform"}:
            acceleration += vector * (float(force.strength) * falloff)[:, None]
        elif kind in {"gravity_source", "point_gravity"}:
            normal = _normalized_rows(delta, (0.0, -1.0, 0.0))
            softening = max(1.0e-4, float(vector[0]))
            strength = float(force.strength) / np.maximum(softening * softening, distance * distance + softening * softening)
            acceleration -= normal * (strength * falloff)[:, None]
        elif kind == "radial":
            acceleration += _normalized_rows(delta, (0.0, 1.0, 0.0)) * (float(force.strength) * falloff)[:, None]
        elif kind == "vortex":
            axis = _normalized(vector, np.asarray((0.0, 1.0, 0.0)))
            tangent = _normalized_rows(np.cross(np.broadcast_to(axis, delta.shape), delta), (1.0, 0.0, 0.0))
            acceleration += tangent * (float(force.strength) * falloff)[:, None]
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
        "radii": buffers.radii[view], "alive": buffers.alive[view],
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
        ("cloth", "softbody", "fluid", "particle", "volume", "rigid", "effect", "surface"),
        True, True, True, 2_000_000,
        "Persistent NumPy SoA particles/effects with capability-gated reference fallback.",
    ))
    register_simulation_executor("native_cpu", execute_native_cpu)


__all__ = [
    "NativeParticleBuffers", "execute_native_cpu", "install_native_cpu_backend", "native_backend_support",
    "native_particle_view", "synchronize_native_particles",
]
