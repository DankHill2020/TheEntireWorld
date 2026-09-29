"""Provider-neutral float32 GPU XPBD and bounded pairwise neighbor kernels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import compute_provider
from tech_connector.game_engine.runtime.tc_simulation_native_constraints_service import NativeConstraintBuffers


MAX_PAIRWISE_PARTICLES = 2_000_000
MAX_BROADPHASE_CANDIDATES = 8_000_000


@dataclass
class GpuConstraintBuffers:
    provider_id: str

    def __post_init__(self) -> None:
        self.host = NativeConstraintBuffers()
        self.arrays: dict[str, Any] = {}
        self.distance_colors: list[Any] = []
        self.area_colors: list[Any] = []
        self.bending_colors: list[Any] = []
        self.bending_signature: tuple[Any, ...] = ()

    def upload(self, world: Any, *, force: bool = True) -> None:
        provider = compute_provider(self.provider_id)
        xp = provider.array_module
        previous_topology = self.host.topology_signature
        self.host.upload(world, force=force)
        names = (
            "distance_first", "distance_second", "distance_rest", "distance_compliance",
            "distance_break_threshold", "distance_break_distance", "distance_enabled", "distance_lambda",
            "area_indices", "area_rest", "area_compliance", "area_break_threshold", "area_enabled", "area_lambda",
        )
        self.arrays = {name: xp.asarray(getattr(self.host, name)) for name in names}
        self.arrays["distance_strain_limit"] = xp.asarray(
            [float(getattr(item, "strain_limit", 0.0)) for item in world.constraints], dtype=xp.float32,
        )
        bending = list(getattr(world, "bending_constraints", ()) or ())
        bending_signature = tuple(
            (item.edge_first, item.edge_second, item.opposite_first, item.opposite_second)
            for item in bending
        )
        self.arrays.update({
            "bending_indices": xp.asarray(bending_signature, dtype=xp.int64).reshape((-1, 4)),
            "bending_rest": xp.asarray([item.rest_angle for item in bending], dtype=xp.float32),
            "bending_compliance": xp.asarray([item.compliance for item in bending], dtype=xp.float32),
            "bending_break_threshold": xp.asarray([item.break_threshold for item in bending], dtype=xp.float32),
            "bending_enabled": xp.asarray([item.enabled for item in bending], dtype=xp.bool_),
            "bending_lambda": xp.zeros(len(bending), dtype=xp.float32),
        })
        if previous_topology != self.host.topology_signature or not self.distance_colors:
            self.distance_colors = [xp.asarray(color, dtype=xp.int64) for color in self.host.distance_colors]
            self.area_colors = [xp.asarray(color, dtype=xp.int64) for color in self.host.area_colors]
        if bending_signature != self.bending_signature:
            self.bending_colors = [xp.asarray(color, dtype=xp.int64) for color in _graph_colors(bending_signature)]
            self.bending_signature = bending_signature

    def begin_substep(self) -> None:
        self.arrays["distance_lambda"][...] = 0.0
        self.arrays["area_lambda"][...] = 0.0
        self.arrays["bending_lambda"][...] = 0.0

    def download_mutable_state(self, world: Any) -> None:
        provider = compute_provider(self.provider_id)
        xp = provider.array_module
        distance_enabled = _host(xp, self.arrays["distance_enabled"])
        distance_lambda = _host(xp, self.arrays["distance_lambda"])
        area_enabled = _host(xp, self.arrays["area_enabled"])
        area_lambda = _host(xp, self.arrays["area_lambda"])
        bending_enabled = _host(xp, self.arrays["bending_enabled"])
        bending_lambda = _host(xp, self.arrays["bending_lambda"])
        for index, item in enumerate(world.constraints):
            item.enabled = bool(distance_enabled[index])
            item.lagrange = float(distance_lambda[index])
        for index, item in enumerate(world.area_constraints):
            item.enabled = bool(area_enabled[index])
            item.lagrange = float(area_lambda[index])
        for index, item in enumerate(getattr(world, "bending_constraints", ())):
            item.enabled = bool(bending_enabled[index])
            item.lagrange = float(bending_lambda[index])

    @property
    def memory_bytes(self) -> int:
        return sum(int(value.nbytes) for value in self.arrays.values())


def solve_gpu_constraints(xp: Any, particles: Any, constraints: GpuConstraintBuffers, world: Any, dt: float,
                          *, solve_bending: bool = True) -> None:
    _solve_distance(xp, particles, constraints, dt)
    _solve_attachments(xp, particles, world, dt)
    _solve_area(xp, particles, constraints, dt)
    if solve_bending:
        _solve_bending(xp, particles, constraints, dt)


def solve_gpu_pairwise_neighbors(
    xp: Any, particles: Any, world: Any, dt: float, *, self_collision: bool, material_neighbors: bool,
    constraints: GpuConstraintBuffers | None = None,
) -> dict[str, int]:
    count = particles.count
    if count < 2:
        return {"self_collision_pairs": 0, "material_neighbor_pairs": 0, "broadphase_candidates": 0}
    if count > MAX_PAIRWISE_PARTICLES:
        raise ValueError(f"GPU spatial-hash broadphase is capped at {MAX_PAIRWISE_PARTICLES} particles.")
    position = particles.arrays["positions"].handle[:count]
    velocity = particles.arrays["velocities"].handle[:count]
    radii = particles.arrays["radii"].handle[:count]
    dynamic = particles.arrays["dynamic"].handle[:count]
    alive = particles.arrays["alive"].handle[:count]
    inverse_mass = particles.arrays["inverse_mass"].handle[:count]
    interaction = radii * (
        4.0 + 4.0 * xp.maximum(0.0, particles.arrays["stringiness"].handle[:count])
    )
    maximum_interaction = xp.maximum(2.0 * xp.max(radii), xp.max(interaction))
    cell_size = max(1.0e-6, float(_host(xp, maximum_interaction)))
    first, second = _spatial_hash_pairs(xp, position, alive, cell_size)
    broadphase_candidates = _scalar_int(xp, first.size)
    if broadphase_candidates > MAX_BROADPHASE_CANDIDATES:
        raise ValueError(
            f"GPU spatial-hash broadphase exceeded {MAX_BROADPHASE_CANDIDATES} local candidates."
        )
    delta = position[second] - position[first]
    distance = xp.linalg.norm(delta, axis=1)
    valid = distance > 1.0e-12
    first, second, delta, distance = first[valid], second[valid], delta[valid], distance[valid]
    self_pairs = material_pairs = 0
    if self_collision:
        minimum = radii[first] + radii[second]
        collision_group = particles.arrays["collision_group"].handle[:count]
        collision_mask = particles.arrays["collision_mask"].handle[:count]
        allowed = ((collision_mask[first] & collision_group[second]) != 0) & (
            (collision_mask[second] & collision_group[first]) != 0
        )
        if bool(getattr(world, "cloth_settings", {}).get("exclude_topological_neighbors", False)) and constraints is not None:
            topology_first = constraints.arrays["distance_first"]
            topology_second = constraints.arrays["distance_second"]
            topology_enabled = constraints.arrays["distance_enabled"]
            low = xp.minimum(topology_first[topology_enabled], topology_second[topology_enabled])
            high = xp.maximum(topology_first[topology_enabled], topology_second[topology_enabled])
            excluded = low * count + high
            allowed &= ~xp.isin(first * count + second, excluded)
        mask = (distance < minimum) & allowed
        collision_first, collision_second = first[mask], second[mask]
        collision_delta, collision_distance = delta[mask], distance[mask]
        self_pairs = _scalar_int(xp, collision_first.size)
        if self_pairs:
            normals = collision_delta / collision_distance[:, None]
            priority = particles.arrays["collision_priority"].handle[:count]
            first_weight = inverse_mass[collision_first] * dynamic[collision_first] / (
                1.0 + xp.maximum(0.0, priority[collision_first])
            )
            second_weight = inverse_mass[collision_second] * dynamic[collision_second] / (
                1.0 + xp.maximum(0.0, priority[collision_second])
            )
            total = first_weight + second_weight
            solvable = total > 1.0e-12
            collision_first, collision_second, normals = (
                collision_first[solvable], collision_second[solvable], normals[solvable]
            )
            first_weight, second_weight, total = (
                first_weight[solvable], second_weight[solvable], total[solvable]
            )
            penetration = (
                radii[collision_first] + radii[collision_second]
                - xp.linalg.norm(position[collision_second] - position[collision_first], axis=1)
            )
            correction = normals * penetration[:, None]
            accumulated = xp.zeros_like(position)
            xp.add.at(accumulated, collision_first, -correction * (first_weight / total)[:, None])
            xp.add.at(accumulated, collision_second, correction * (second_weight / total)[:, None])
            position += accumulated
    if material_neighbors:
        material_id = particles.arrays["material_id"].handle[:count]
        mask = (material_id[first] == material_id[second]) & (distance < interaction[first])
        material_first, material_second = first[mask], second[mask]
        material_delta, material_distance = delta[mask], distance[mask]
        material_pairs = _scalar_int(xp, material_first.size)
        if material_pairs:
            influence = 1.0 - material_distance / interaction[material_first]
            viscosity = particles.arrays["viscosity"].handle[material_first]
            blend = xp.minimum(0.5, viscosity * influence * dt)
            average = (velocity[material_first] + velocity[material_second]) * 0.5
            accumulated_velocity = xp.zeros_like(velocity)
            xp.add.at(accumulated_velocity, material_first, (average - velocity[material_first]) * blend[:, None])
            xp.add.at(accumulated_velocity, material_second, (average - velocity[material_second]) * blend[:, None])
            velocity += accumulated_velocity
            cohesion = particles.arrays["cohesion"].handle[material_first]
            separated = material_distance > radii[material_first] + radii[material_second]
            relative_speed = xp.linalg.norm(velocity[material_first] - velocity[material_second], axis=1)
            yield_factor = 1.0 + xp.maximum(
                0.0, particles.arrays["yield_strength"].handle[material_first] - relative_speed
            )
            tension = cohesion + particles.arrays["surface_tension"].handle[material_first] * influence
            correction = (
                material_delta / material_distance[:, None]
                * (tension * yield_factor * influence * dt * dt * separated)[:, None]
            )
            accumulated_position = xp.zeros_like(position)
            xp.add.at(accumulated_position, material_first, correction * dynamic[material_first, None])
            xp.add.at(accumulated_position, material_second, -correction * dynamic[material_second, None])
            position += accumulated_position
    return {
        "self_collision_pairs": self_pairs, "material_neighbor_pairs": material_pairs,
        "broadphase_candidates": broadphase_candidates,
    }


def _spatial_hash_pairs(xp: Any, position: Any, alive: Any, cell_size: float) -> tuple[Any, Any]:
    """Generate deterministic local candidates without allocating an N-by-N distance matrix."""
    count = len(position)
    coordinates = xp.floor(position / cell_size).astype(xp.int64)
    keys = _hash_cells(xp, coordinates)
    order = xp.argsort(keys)
    sorted_keys = keys[order]
    particle_indices = xp.arange(count, dtype=xp.int64)
    first_parts, second_parts = [], []
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            for z in (-1, 0, 1):
                target_keys = _hash_cells(xp, coordinates + xp.asarray((x, y, z), dtype=xp.int64))
                left = xp.searchsorted(sorted_keys, target_keys, side="left")
                right = xp.searchsorted(sorted_keys, target_keys, side="right")
                counts = right - left
                total = _scalar_int(xp, xp.sum(counts))
                if total <= 0:
                    continue
                first = xp.repeat(particle_indices, counts)
                repeated_left = xp.repeat(left, counts)
                group_start = xp.repeat(xp.cumsum(counts) - counts, counts)
                second = order[repeated_left + xp.arange(total, dtype=xp.int64) - group_start]
                valid = (first < second) & alive[first] & alive[second]
                first_parts.append(first[valid])
                second_parts.append(second[valid])
    if not first_parts:
        empty = xp.asarray([], dtype=xp.int64)
        return empty, empty
    first = xp.concatenate(first_parts)
    second = xp.concatenate(second_parts)
    encoded = xp.unique(first * count + second)
    return encoded // count, encoded % count


def _hash_cells(xp: Any, coordinates: Any) -> Any:
    return (
        coordinates[:, 0] * xp.int64(73856093)
        ^ coordinates[:, 1] * xp.int64(19349663)
        ^ coordinates[:, 2] * xp.int64(83492791)
    )


def _solve_distance(xp: Any, particles: Any, state: GpuConstraintBuffers, dt: float) -> None:
    arrays = state.arrays
    position = particles.arrays["positions"].handle
    inverse_mass = particles.arrays["inverse_mass"].handle
    dynamic = particles.arrays["dynamic"].handle
    for color in state.distance_colors:
        first = arrays["distance_first"][color]
        second = arrays["distance_second"][color]
        delta = position[second] - position[first]
        length = xp.linalg.norm(delta, axis=1)
        rest = arrays["distance_rest"][color]
        enabled = arrays["distance_enabled"][color]
        strain = length / xp.maximum(1.0e-12, rest)
        broken = enabled & (
            ((arrays["distance_break_distance"][color] > 0.0) &
             (xp.abs(length - rest) > arrays["distance_break_distance"][color])) |
            ((arrays["distance_break_threshold"][color] > 0.0) &
             (strain > arrays["distance_break_threshold"][color]))
        )
        arrays["distance_enabled"][color[broken]] = False
        active = enabled & ~broken & (length > 1.0e-12)
        selected = color[active]
        first, second, length = first[active], second[active], length[active]
        active_delta = delta[active]
        first_weight = inverse_mass[first] * dynamic[first]
        second_weight = inverse_mass[second] * dynamic[second]
        weight_sum = first_weight + second_weight
        strain_limit = arrays["distance_strain_limit"][selected]
        hard = (strain_limit > 1.0) & (
            length > arrays["distance_rest"][selected] * strain_limit
        ) & (weight_sum > 1.0e-12)
        excess = xp.maximum(0.0, length - arrays["distance_rest"][selected] * strain_limit)
        hard_correction = active_delta / length[:, None] * (
            excess / xp.maximum(weight_sum, 1.0e-12)
        )[:, None] * hard[:, None]
        position[first] += hard_correction * first_weight[:, None]
        position[second] -= hard_correction * second_weight[:, None]
        active_delta = position[second] - position[first]
        length = xp.linalg.norm(active_delta, axis=1)
        alpha = xp.maximum(0.0, arrays["distance_compliance"][selected]) / max(1.0e-12, dt * dt)
        denominator = first_weight + second_weight + alpha
        delta_lambda = (
            -(length - arrays["distance_rest"][selected]) - alpha * arrays["distance_lambda"][selected]
        ) / xp.maximum(denominator, 1.0e-12)
        arrays["distance_lambda"][selected] += delta_lambda
        correction = active_delta / xp.maximum(length[:, None], 1.0e-12) * delta_lambda[:, None]
        position[first] -= correction * first_weight[:, None]
        position[second] += correction * second_weight[:, None]


def _solve_area(xp: Any, particles: Any, state: GpuConstraintBuffers, dt: float) -> None:
    arrays = state.arrays
    position = particles.arrays["positions"].handle
    inverse_mass = particles.arrays["inverse_mass"].handle
    dynamic = particles.arrays["dynamic"].handle
    for color in state.area_colors:
        indices = arrays["area_indices"][color]
        first, second, third = (position[indices[:, axis]] for axis in range(3))
        cross_value = xp.cross(second - first, third - first)
        cross_length = xp.linalg.norm(cross_value, axis=1)
        area = cross_length * 0.5
        enabled = arrays["area_enabled"][color]
        broken = enabled & (arrays["area_break_threshold"][color] > 0.0) & (
            area / xp.maximum(1.0e-12, arrays["area_rest"][color]) > arrays["area_break_threshold"][color]
        )
        arrays["area_enabled"][color[broken]] = False
        active = enabled & ~broken & (cross_length > 1.0e-12)
        selected = color[active]
        indices = indices[active]
        normal = cross_value[active] / cross_length[active, None]
        gradients = xp.stack((
            xp.cross(second[active] - third[active], normal) * 0.5,
            xp.cross(third[active] - first[active], normal) * 0.5,
            xp.cross(first[active] - second[active], normal) * 0.5,
        ), axis=1)
        weights = inverse_mass[indices] * dynamic[indices]
        denominator = xp.sum(weights * xp.sum(gradients * gradients, axis=2), axis=1)
        alpha = xp.maximum(0.0, arrays["area_compliance"][selected]) / max(1.0e-12, dt * dt)
        delta_lambda = (
            -(area[active] - arrays["area_rest"][selected]) - alpha * arrays["area_lambda"][selected]
        ) / xp.maximum(denominator + alpha, 1.0e-12)
        arrays["area_lambda"][selected] += delta_lambda
        for vertex in range(3):
            position[indices[:, vertex]] += gradients[:, vertex] * weights[:, vertex, None] * delta_lambda[:, None]


def _solve_bending(xp: Any, particles: Any, state: GpuConstraintBuffers, dt: float) -> None:
    arrays = state.arrays
    if not state.bending_colors:
        return
    position = particles.arrays["positions"].handle
    inverse_mass = particles.arrays["inverse_mass"].handle
    dynamic = particles.arrays["dynamic"].handle
    for color in state.bending_colors:
        indices = arrays["bending_indices"][color]
        edge_first, edge_second, opposite_first, opposite_second = (
            position[indices[:, axis]] for axis in range(4)
        )
        edge = edge_second - edge_first
        edge_length = xp.linalg.norm(edge, axis=1)
        direction = edge / xp.maximum(edge_length[:, None], 1.0e-12)
        first_normal = xp.cross(edge, opposite_first - edge_first)
        second_normal = xp.cross(opposite_second - edge_first, edge)
        first_length = xp.linalg.norm(first_normal, axis=1)
        second_length = xp.linalg.norm(second_normal, axis=1)
        first_normal /= xp.maximum(first_length[:, None], 1.0e-12)
        second_normal /= xp.maximum(second_length[:, None], 1.0e-12)
        angle = xp.arctan2(
            xp.sum(xp.cross(first_normal, second_normal) * direction, axis=1),
            xp.sum(first_normal * second_normal, axis=1),
        )
        error = (angle - arrays["bending_rest"][color] + xp.pi) % (2.0 * xp.pi) - xp.pi
        enabled = arrays["bending_enabled"][color]
        broken = enabled & (arrays["bending_break_threshold"][color] > 0.0) & (
            xp.abs(error) > arrays["bending_break_threshold"][color]
        )
        arrays["bending_enabled"][color[broken]] = False
        active = enabled & ~broken & (edge_length > 1.0e-12) & (
            first_length > 1.0e-12
        ) & (second_length > 1.0e-12)
        selected = color[active]
        if selected.size == 0:
            continue
        active_indices = indices[active]
        first_weight = inverse_mass[active_indices[:, 2]] * dynamic[active_indices[:, 2]]
        second_weight = inverse_mass[active_indices[:, 3]] * dynamic[active_indices[:, 3]]
        weight_sum = first_weight + second_weight
        alpha = xp.maximum(0.0, arrays["bending_compliance"][selected]) / max(1.0e-12, dt * dt)
        correction = (
            error[active] - alpha * arrays["bending_lambda"][selected]
        ) / xp.maximum(weight_sum + alpha, 1.0e-12)
        arrays["bending_lambda"][selected] += correction
        origin = edge_first[active]
        active_direction = direction[active]
        position[active_indices[:, 2]] = _rotate_points(
            xp, opposite_first[active], origin, active_direction, first_weight * correction,
        )
        position[active_indices[:, 3]] = _rotate_points(
            xp, opposite_second[active], origin, active_direction, -second_weight * correction,
        )


def _rotate_points(xp: Any, points: Any, origins: Any, axes: Any, angles: Any) -> Any:
    relative = points - origins
    cosine, sine = xp.cos(angles)[:, None], xp.sin(angles)[:, None]
    rotated = relative * cosine + xp.cross(axes, relative) * sine
    rotated += axes * xp.sum(axes * relative, axis=1)[:, None] * (1.0 - cosine)
    return origins + rotated


def _graph_colors(indices: tuple[tuple[int, ...], ...]) -> list[np.ndarray]:
    colors: list[list[int]] = []
    occupied: list[set[int]] = []
    for constraint_index, vertices in enumerate(indices):
        vertex_set = set(int(value) for value in vertices)
        for color_index, used in enumerate(occupied):
            if not vertex_set & used:
                colors[color_index].append(constraint_index)
                used.update(vertex_set)
                break
        else:
            colors.append([constraint_index])
            occupied.append(set(vertex_set))
    return [np.asarray(color, dtype=np.int64) for color in colors]


def _solve_attachments(xp: Any, particles: Any, world: Any, dt: float) -> None:
    position = particles.arrays["positions"].handle
    inverse_mass = particles.arrays["inverse_mass"].handle
    dynamic = particles.arrays["dynamic"].handle
    for item in world.attachments:
        if not item.enabled or not 0 <= item.particle < particles.count:
            continue
        index = int(item.particle)
        target = xp.asarray(item.target, dtype=xp.float32)
        delta = position[index] - target
        alpha = max(0.0, float(item.compliance)) / max(1.0e-12, dt * dt)
        weight = inverse_mass[index]
        position[index] = xp.where(
            dynamic[index], position[index] - delta * (weight / xp.maximum(weight + alpha, 1.0e-12)), target
        )


def _scalar_int(xp: Any, value: Any) -> int:
    if hasattr(xp, "asnumpy"):
        return int(xp.asnumpy(value))
    return int(value)


def _host(xp: Any, value: Any) -> np.ndarray:
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value)


__all__ = [
    "GpuConstraintBuffers", "MAX_BROADPHASE_CANDIDATES", "MAX_PAIRWISE_PARTICLES", "solve_gpu_constraints",
    "solve_gpu_pairwise_neighbors",
]
