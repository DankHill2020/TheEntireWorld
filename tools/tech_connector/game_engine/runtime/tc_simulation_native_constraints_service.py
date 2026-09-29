"""Deterministic SoA XPBD constraint and material-neighbor kernels."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from typing import Any

import numpy as np


@dataclass
class NativeConstraintBuffers:
    """Persistent compiled constraint topology and mutable XPBD state."""

    topology_signature: tuple[Any, ...] = ()
    parameter_signature: tuple[Any, ...] = ()
    reallocations: int = 0

    def __post_init__(self) -> None:
        self.distance_first = np.empty(0, dtype=np.int64)
        self.distance_second = np.empty(0, dtype=np.int64)
        self.distance_rest = np.empty(0, dtype=np.float64)
        self.distance_compliance = np.empty(0, dtype=np.float64)
        self.distance_break_threshold = np.empty(0, dtype=np.float64)
        self.distance_break_distance = np.empty(0, dtype=np.float64)
        self.distance_enabled = np.empty(0, dtype=np.bool_)
        self.distance_lambda = np.empty(0, dtype=np.float64)
        self.distance_plastic_yield = np.empty(0, dtype=np.float64)
        self.distance_plastic_creep = np.empty(0, dtype=np.float64)
        self.distance_colors: list[np.ndarray] = []
        self.area_indices = np.empty((0, 3), dtype=np.int64)
        self.area_rest = np.empty(0, dtype=np.float64)
        self.area_compliance = np.empty(0, dtype=np.float64)
        self.area_break_threshold = np.empty(0, dtype=np.float64)
        self.area_enabled = np.empty(0, dtype=np.bool_)
        self.area_lambda = np.empty(0, dtype=np.float64)
        self.area_colors: list[np.ndarray] = []
        self.volume_topology: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    def upload(self, world: Any, *, force: bool = False) -> None:
        signature = (
            tuple((item.first, item.second) for item in world.constraints),
            tuple((item.first, item.second, item.third) for item in world.area_constraints),
            tuple((tuple(item.particle_indices), tuple(item.faces)) for item in world.volume_constraints),
            tuple(item.particle for item in world.attachments),
        )
        topology_changed = signature != self.topology_signature
        parameter_signature = (
            tuple((item.rest_length, item.compliance, item.break_threshold, item.break_distance, item.enabled,
                   item.plastic_yield, item.plastic_creep) for item in world.constraints),
            tuple((item.rest_area, item.compliance, item.break_threshold, item.enabled)
                  for item in world.area_constraints),
        )
        parameters_changed = parameter_signature != self.parameter_signature
        if topology_changed:
            self.topology_signature = signature
            self.distance_first = np.asarray([item.first for item in world.constraints], dtype=np.int64)
            self.distance_second = np.asarray([item.second for item in world.constraints], dtype=np.int64)
            self.distance_colors = _graph_colors(
                [(int(first), int(second)) for first, second in zip(self.distance_first, self.distance_second)]
            )
            self.area_indices = np.asarray(
                [(item.first, item.second, item.third) for item in world.area_constraints], dtype=np.int64
            ).reshape((-1, 3))
            self.area_colors = _graph_colors([tuple(map(int, row)) for row in self.area_indices])
            self.volume_topology = []
            for item in world.volume_constraints:
                particle_indices = np.asarray(item.particle_indices, dtype=np.int64)
                local = {int(index): offset for offset, index in enumerate(particle_indices)}
                faces = np.asarray(item.faces, dtype=np.int64).reshape((-1, 3))
                local_faces = np.asarray(
                    [[local[int(index)] for index in face] for face in faces], dtype=np.int64
                ).reshape((-1, 3))
                self.volume_topology.append((particle_indices, faces, local_faces))
            self.reallocations += 1
        if not topology_changed and not force and not parameters_changed:
            return
        self.parameter_signature = parameter_signature
        self.distance_rest = np.asarray([item.rest_length for item in world.constraints], dtype=np.float64)
        self.distance_compliance = np.asarray([item.compliance for item in world.constraints], dtype=np.float64)
        self.distance_break_threshold = np.asarray([item.break_threshold for item in world.constraints], dtype=np.float64)
        self.distance_break_distance = np.asarray([item.break_distance for item in world.constraints], dtype=np.float64)
        self.distance_enabled = np.asarray([item.enabled for item in world.constraints], dtype=np.bool_)
        self.distance_lambda = np.asarray([item.lagrange for item in world.constraints], dtype=np.float64)
        self.distance_plastic_yield = np.asarray([item.plastic_yield for item in world.constraints], dtype=np.float64)
        self.distance_plastic_creep = np.asarray([item.plastic_creep for item in world.constraints], dtype=np.float64)
        self.area_rest = np.asarray([item.rest_area for item in world.area_constraints], dtype=np.float64)
        self.area_compliance = np.asarray([item.compliance for item in world.area_constraints], dtype=np.float64)
        self.area_break_threshold = np.asarray([item.break_threshold for item in world.area_constraints], dtype=np.float64)
        self.area_enabled = np.asarray([item.enabled for item in world.area_constraints], dtype=np.bool_)
        self.area_lambda = np.asarray([item.lagrange for item in world.area_constraints], dtype=np.float64)

    def begin_substep(self, world: Any) -> None:
        self.distance_lambda.fill(0.0)
        self.area_lambda.fill(0.0)
        for item in world.volume_constraints:
            item.lagrange = 0.0

    def download_mutable_state(self, world: Any) -> None:
        for index, item in enumerate(world.constraints):
            item.rest_length = float(self.distance_rest[index])
            item.enabled = bool(self.distance_enabled[index])
            item.lagrange = float(self.distance_lambda[index])
        for index, item in enumerate(world.area_constraints):
            item.enabled = bool(self.area_enabled[index])
            item.lagrange = float(self.area_lambda[index])

    @property
    def memory_bytes(self) -> int:
        return sum(
            int(value.nbytes) for value in vars(self).values() if isinstance(value, np.ndarray)
        )


def solve_native_constraints(buffers: Any, constraints: NativeConstraintBuffers, world: Any, dt: float) -> None:
    if constraints.distance_first.size <= 128:
        _solve_distance_batched(buffers, constraints, dt)
    else:
        _solve_distance(buffers, constraints, dt)
    _solve_attachments(buffers, world, dt)
    if constraints.area_indices.shape[0] <= 128:
        _solve_area_batched(buffers, constraints, dt)
    else:
        _solve_area(buffers, constraints, dt)
    _solve_volume(buffers, constraints, world, dt)


def solve_native_material_neighbors(buffers: Any, world: Any, dt: float) -> int:
    """Stable spatial-hash neighborhood solve; returns the number of interacting pairs."""
    count = buffers.count
    if count < 2:
        return 0
    position = buffers.positions[:count]
    velocity = buffers.velocities[:count]
    materials: dict[str, list[int]] = {}
    for index, particle in enumerate(world.particles):
        if particle.alive:
            materials.setdefault(particle.material, []).append(index)
    pair_count = 0
    for material_name, indices in materials.items():
        material = world.materials.get(material_name)
        if material is None or (material.viscosity <= 0.0 and material.cohesion <= 0.0):
            continue
        maximum_radius = max(float(buffers.radii[index]) for index in indices)
        interaction_radius = maximum_radius * (4.0 + 4.0 * max(0.0, float(material.stringiness)))
        if interaction_radius <= 1.0e-12:
            continue
        grid: dict[tuple[int, int, int], list[int]] = {}
        for index in indices:
            key = tuple(np.floor(position[index] / interaction_radius).astype(np.int64).tolist())
            grid.setdefault(key, []).append(index)
        for first_index in indices:
            first_radius = float(buffers.radii[first_index])
            first_range = first_radius * (4.0 + 4.0 * max(0.0, float(material.stringiness)))
            key = tuple(np.floor(position[first_index] / interaction_radius).astype(np.int64).tolist())
            candidates = sorted(set(itertools.chain.from_iterable(
                grid.get((key[0] + x, key[1] + y, key[2] + z), ())
                for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)
            )))
            for second_index in candidates:
                if second_index <= first_index:
                    continue
                delta = position[second_index] - position[first_index]
                distance = float(np.linalg.norm(delta))
                if distance <= 1.0e-12 or distance >= first_range:
                    continue
                pair_count += 1
                influence = 1.0 - distance / first_range
                if material.viscosity > 0.0:
                    blend = min(0.5, float(material.viscosity) * influence * dt)
                    average = (velocity[first_index] + velocity[second_index]) * 0.5
                    velocity[first_index] += (average - velocity[first_index]) * blend
                    velocity[second_index] += (average - velocity[second_index]) * blend
                if material.cohesion > 0.0 and distance > first_radius + float(buffers.radii[second_index]):
                    relative_speed = float(np.linalg.norm(velocity[first_index] - velocity[second_index]))
                    yield_factor = 1.0 + max(0.0, float(material.yield_strength) - relative_speed)
                    tension = float(material.cohesion) + float(material.surface_tension) * influence
                    correction = delta / distance * (tension * yield_factor * influence * dt * dt)
                    if buffers.dynamic[first_index]:
                        position[first_index] += correction
                    if buffers.dynamic[second_index]:
                        position[second_index] -= correction
    return pair_count


def solve_native_self_collision(buffers: Any, world: Any, record_contact: Any = None) -> int:
    """Deterministic spatial-hash particle contact solve with stable pair ordering."""
    count = buffers.count
    if count < 2:
        return 0
    position = buffers.positions[:count]
    radii = buffers.radii[:count]
    alive = buffers.alive[:count]
    cell_size = max(1.0e-6, float(np.max(radii[alive], initial=0.025)) * 2.0)
    grid: dict[tuple[int, int, int], list[int]] = {}
    for index in np.flatnonzero(alive).tolist():
        key = tuple(np.floor(position[index] / cell_size).astype(np.int64).tolist())
        grid.setdefault(key, []).append(index)
    pairs: set[tuple[int, int]] = set()
    for key, indices in grid.items():
        neighbors = itertools.chain.from_iterable(
            grid.get((key[0] + x, key[1] + y, key[2] + z), ())
            for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)
        )
        neighbor_list = tuple(neighbors)
        for first in indices:
            pairs.update((min(first, second), max(first, second)) for second in neighbor_list if first != second)
    contact_count = 0
    for first, second in sorted(pairs):
        delta = position[second] - position[first]
        distance = float(np.linalg.norm(delta))
        minimum = float(radii[first] + radii[second])
        if distance >= minimum:
            continue
        normal = delta / distance if distance > 1.0e-12 else np.asarray((1.0, 0.0, 0.0))
        first_weight = float(buffers.inverse_mass[first]) if buffers.dynamic[first] else 0.0
        second_weight = float(buffers.inverse_mass[second]) if buffers.dynamic[second] else 0.0
        total = first_weight + second_weight
        if total <= 0.0:
            continue
        penetration = minimum - distance
        if record_contact is not None:
            record_contact(
                position[first] + normal * radii[first], normal, np.asarray((penetration,)), "particle"
            )
        correction = normal * penetration
        position[first] -= correction * (first_weight / total)
        position[second] += correction * (second_weight / total)
        contact_count += 1
    return contact_count


def _solve_distance(buffers: Any, constraints: NativeConstraintBuffers, dt: float) -> None:
    position = buffers.positions
    inverse_mass = buffers.inverse_mass
    for color in constraints.distance_colors:
        if color.size == 0:
            continue
        first = constraints.distance_first[color]
        second = constraints.distance_second[color]
        enabled = constraints.distance_enabled[color]
        delta = position[second] - position[first]
        length = np.linalg.norm(delta, axis=1)
        rest = constraints.distance_rest[color]
        strain = length / np.maximum(1.0e-12, rest)
        broken = enabled & (
            ((constraints.distance_break_distance[color] > 0.0) &
             (np.abs(length - rest) > constraints.distance_break_distance[color])) |
            ((constraints.distance_break_threshold[color] > 0.0) &
             (strain > constraints.distance_break_threshold[color]))
        )
        if np.any(broken):
            constraints.distance_enabled[color[broken]] = False
        active = enabled & ~broken & (length > 1.0e-12)
        if not np.any(active):
            continue
        selected = color[active]
        selected_first = first[active]
        selected_second = second[active]
        selected_length = length[active]
        selected_strain = strain[active]
        plastic = (
            (constraints.distance_plastic_yield[selected] > 0.0)
            & (np.abs(selected_strain - 1.0) > constraints.distance_plastic_yield[selected])
            & (constraints.distance_lambda[selected] == 0.0)
        )
        if np.any(plastic):
            creep = np.minimum(1.0, np.maximum(0.0, constraints.distance_plastic_creep[selected[plastic]]) * dt)
            old_rest = constraints.distance_rest[selected[plastic]]
            constraints.distance_rest[selected[plastic]] = old_rest + (selected_length[plastic] - old_rest) * creep
        first_weight = inverse_mass[selected_first] * buffers.dynamic[selected_first]
        second_weight = inverse_mass[selected_second] * buffers.dynamic[selected_second]
        weight_sum = first_weight + second_weight
        alpha = np.maximum(0.0, constraints.distance_compliance[selected]) / max(1.0e-12, dt * dt)
        solvable = weight_sum + alpha > 1.0e-12
        if not np.any(solvable):
            continue
        selected = selected[solvable]
        selected_first = selected_first[solvable]
        selected_second = selected_second[solvable]
        normal = delta[active][solvable] / selected_length[solvable, None]
        first_weight = first_weight[solvable]
        second_weight = second_weight[solvable]
        alpha = alpha[solvable]
        delta_lambda = (
            -(selected_length[solvable] - constraints.distance_rest[selected])
            - alpha * constraints.distance_lambda[selected]
        ) / (first_weight + second_weight + alpha)
        constraints.distance_lambda[selected] += delta_lambda
        correction = normal * delta_lambda[:, None]
        position[selected_first] -= correction * first_weight[:, None]
        position[selected_second] += correction * second_weight[:, None]


def _solve_distance_batched(buffers: Any, constraints: NativeConstraintBuffers, dt: float) -> None:
    """Solve a small topology in one deterministic Jacobi batch.

    Graph-colour dispatch is ideal for large meshes, but issuing many tiny NumPy
    operations costs more than the useful work on preview-sized soft bodies.
    ``np.add.at`` preserves deterministic accumulation when vertices are shared.
    """
    if constraints.distance_first.size == 0:
        return
    position = buffers.positions
    first = constraints.distance_first
    second = constraints.distance_second
    delta = position[second] - position[first]
    length = np.sqrt(np.sum(delta * delta, axis=1))
    rest = constraints.distance_rest
    strain = length / np.maximum(1.0e-12, rest)
    enabled = constraints.distance_enabled
    broken = enabled & (
        ((constraints.distance_break_distance > 0.0)
         & (np.abs(length - rest) > constraints.distance_break_distance))
        | ((constraints.distance_break_threshold > 0.0)
           & (strain > constraints.distance_break_threshold))
    )
    if np.any(broken):
        constraints.distance_enabled[broken] = False
    active = enabled & ~broken & (length > 1.0e-12)
    if not np.any(active):
        return
    selected = np.flatnonzero(active)
    selected_first = first[selected]
    selected_second = second[selected]
    selected_length = length[selected]
    selected_strain = strain[selected]
    plastic = (
        (constraints.distance_plastic_yield[selected] > 0.0)
        & (np.abs(selected_strain - 1.0) > constraints.distance_plastic_yield[selected])
        & (constraints.distance_lambda[selected] == 0.0)
    )
    if np.any(plastic):
        plastic_indices = selected[plastic]
        creep = np.minimum(
            1.0, np.maximum(0.0, constraints.distance_plastic_creep[plastic_indices]) * dt
        )
        old_rest = constraints.distance_rest[plastic_indices]
        constraints.distance_rest[plastic_indices] = (
            old_rest + (selected_length[plastic] - old_rest) * creep
        )
    first_weight = buffers.inverse_mass[selected_first] * buffers.dynamic[selected_first]
    second_weight = buffers.inverse_mass[selected_second] * buffers.dynamic[selected_second]
    alpha = np.maximum(0.0, constraints.distance_compliance[selected]) / max(1.0e-12, dt * dt)
    denominator = first_weight + second_weight + alpha
    solvable = denominator > 1.0e-12
    if not np.any(solvable):
        return
    selected = selected[solvable]
    selected_first = selected_first[solvable]
    selected_second = selected_second[solvable]
    first_weight = first_weight[solvable]
    second_weight = second_weight[solvable]
    alpha = alpha[solvable]
    selected_length = selected_length[solvable]
    normal = delta[selected] / selected_length[:, None]
    delta_lambda = (
        -(selected_length - constraints.distance_rest[selected])
        - alpha * constraints.distance_lambda[selected]
    ) / denominator[solvable]
    constraints.distance_lambda[selected] += delta_lambda
    correction = normal * delta_lambda[:, None]
    accumulated = np.zeros((buffers.count, 3), dtype=np.float64)
    np.add.at(accumulated, selected_first, -correction * first_weight[:, None])
    np.add.at(accumulated, selected_second, correction * second_weight[:, None])
    position[:buffers.count] += accumulated


def _solve_area(buffers: Any, constraints: NativeConstraintBuffers, dt: float) -> None:
    position = buffers.positions
    for color in constraints.area_colors:
        if color.size == 0:
            continue
        indices = constraints.area_indices[color]
        first, second, third = (position[indices[:, axis]] for axis in range(3))
        cross_value = np.cross(second - first, third - first)
        cross_length = np.linalg.norm(cross_value, axis=1)
        area = cross_length * 0.5
        enabled = constraints.area_enabled[color]
        broken = enabled & (constraints.area_break_threshold[color] > 0.0) & (
            area / np.maximum(1.0e-12, constraints.area_rest[color]) > constraints.area_break_threshold[color]
        )
        constraints.area_enabled[color[broken]] = False
        active = enabled & ~broken & (cross_length > 1.0e-12)
        if not np.any(active):
            continue
        selected = color[active]
        selected_indices = indices[active]
        normal = cross_value[active] / cross_length[active, None]
        gradients = np.stack((
            np.cross(second[active] - third[active], normal) * 0.5,
            np.cross(third[active] - first[active], normal) * 0.5,
            np.cross(first[active] - second[active], normal) * 0.5,
        ), axis=1)
        weights = buffers.inverse_mass[selected_indices] * buffers.dynamic[selected_indices]
        denominator = np.sum(weights * np.sum(gradients * gradients, axis=2), axis=1)
        alpha = np.maximum(0.0, constraints.area_compliance[selected]) / max(1.0e-12, dt * dt)
        solvable = denominator + alpha > 1.0e-12
        if not np.any(solvable):
            continue
        delta_lambda = (
            -(area[active][solvable] - constraints.area_rest[selected[solvable]])
            - alpha[solvable] * constraints.area_lambda[selected[solvable]]
        ) / (denominator[solvable] + alpha[solvable])
        constraints.area_lambda[selected[solvable]] += delta_lambda
        for vertex in range(3):
            position[selected_indices[solvable, vertex]] += (
                gradients[solvable, vertex] * weights[solvable, vertex, None] * delta_lambda[:, None]
            )


def _solve_area_batched(buffers: Any, constraints: NativeConstraintBuffers, dt: float) -> None:
    if constraints.area_indices.shape[0] == 0:
        return
    position = buffers.positions
    indices = constraints.area_indices
    first, second, third = (position[indices[:, axis]] for axis in range(3))
    cross_value = _cross_rows(second - first, third - first)
    cross_length = np.sqrt(np.sum(cross_value * cross_value, axis=1))
    area = cross_length * 0.5
    enabled = constraints.area_enabled
    broken = enabled & (constraints.area_break_threshold > 0.0) & (
        area / np.maximum(1.0e-12, constraints.area_rest) > constraints.area_break_threshold
    )
    if np.any(broken):
        constraints.area_enabled[broken] = False
    active = enabled & ~broken & (cross_length > 1.0e-12)
    if not np.any(active):
        return
    selected = np.flatnonzero(active)
    selected_indices = indices[selected]
    normal = cross_value[selected] / cross_length[selected, None]
    selected_first = first[selected]
    selected_second = second[selected]
    selected_third = third[selected]
    gradients = np.stack((
        _cross_rows(selected_second - selected_third, normal) * 0.5,
        _cross_rows(selected_third - selected_first, normal) * 0.5,
        _cross_rows(selected_first - selected_second, normal) * 0.5,
    ), axis=1)
    weights = buffers.inverse_mass[selected_indices] * buffers.dynamic[selected_indices]
    denominator = np.sum(weights * np.sum(gradients * gradients, axis=2), axis=1)
    alpha = np.maximum(0.0, constraints.area_compliance[selected]) / max(1.0e-12, dt * dt)
    solvable = denominator + alpha > 1.0e-12
    if not np.any(solvable):
        return
    selected = selected[solvable]
    selected_indices = selected_indices[solvable]
    gradients = gradients[solvable]
    weights = weights[solvable]
    delta_lambda = (
        -(area[selected] - constraints.area_rest[selected])
        - alpha[solvable] * constraints.area_lambda[selected]
    ) / (denominator[solvable] + alpha[solvable])
    constraints.area_lambda[selected] += delta_lambda
    accumulated = np.zeros((buffers.count, 3), dtype=np.float64)
    for vertex in range(3):
        np.add.at(
            accumulated, selected_indices[:, vertex],
            gradients[:, vertex] * weights[:, vertex, None] * delta_lambda[:, None],
        )
    position[:buffers.count] += accumulated


def _solve_attachments(buffers: Any, world: Any, dt: float) -> None:
    for item in world.attachments:
        if not item.enabled or not 0 <= item.particle < buffers.count:
            continue
        index = int(item.particle)
        target = np.asarray(item.target, dtype=np.float64)
        delta = buffers.positions[index] - target
        distance = float(np.linalg.norm(delta))
        if item.break_threshold > 0.0 and distance > item.break_threshold:
            item.enabled = False
            continue
        if not buffers.dynamic[index]:
            buffers.positions[index] = target
            continue
        alpha = max(0.0, float(item.compliance)) / max(1.0e-12, dt * dt)
        weight = float(buffers.inverse_mass[index])
        buffers.positions[index] -= delta * (weight / (weight + alpha))


def _solve_volume(
    buffers: Any, constraints: NativeConstraintBuffers, world: Any, dt: float
) -> None:
    position = buffers.positions
    for item_index, item in enumerate(world.volume_constraints):
        if not item.enabled:
            continue
        particle_indices, faces, local_faces = constraints.volume_topology[item_index]
        gradients = np.zeros((len(particle_indices), 3), dtype=np.float64)
        a, b, c = (position[faces[:, axis]] for axis in range(3))
        cross_bc = _cross_rows(b, c)
        cross_ca = _cross_rows(c, a)
        cross_ab = _cross_rows(a, b)
        current_volume = float(np.sum(a * cross_bc)) / 6.0
        np.add.at(gradients, local_faces[:, 0], cross_bc / 6.0)
        np.add.at(gradients, local_faces[:, 1], cross_ca / 6.0)
        np.add.at(gradients, local_faces[:, 2], cross_ab / 6.0)
        weights = buffers.inverse_mass[particle_indices] * buffers.dynamic[particle_indices]
        denominator = float(np.sum(weights * np.sum(gradients * gradients, axis=1)))
        alpha = max(0.0, float(item.compliance)) / max(1.0e-12, dt * dt)
        if denominator + alpha <= 1.0e-12:
            continue
        error = current_volume - float(item.rest_volume) * float(item.pressure)
        delta_lambda = (-error - alpha * float(item.lagrange)) / (denominator + alpha)
        item.lagrange += delta_lambda
        position[particle_indices] += gradients * weights[:, None] * delta_lambda


def _cross_rows(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Vector cross product without ``np.cross``'s axis-normalization overhead."""
    result = np.empty_like(first)
    result[:, 0] = first[:, 1] * second[:, 2] - first[:, 2] * second[:, 1]
    result[:, 1] = first[:, 2] * second[:, 0] - first[:, 0] * second[:, 2]
    result[:, 2] = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    return result


def _graph_colors(vertices: list[tuple[int, ...]]) -> list[np.ndarray]:
    colors: list[list[int]] = []
    occupied: list[set[int]] = []
    for constraint_index, members in enumerate(vertices):
        member_set = set(members)
        for color_index, used in enumerate(occupied):
            if member_set.isdisjoint(used):
                colors[color_index].append(constraint_index)
                used.update(member_set)
                break
        else:
            colors.append([constraint_index])
            occupied.append(set(member_set))
    return [np.asarray(color, dtype=np.int64) for color in colors]


__all__ = [
    "NativeConstraintBuffers", "solve_native_constraints", "solve_native_material_neighbors",
    "solve_native_self_collision",
]
