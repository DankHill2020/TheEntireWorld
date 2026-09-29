"""Deterministic Barnes-Hut acceleration for scale-aware particle worlds."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence


Vec3 = tuple[float, float, float]


@dataclass
class BarnesHutNode:
    center: Vec3
    half_size: float
    count: int
    mass: float
    mass_center: Vec3
    charge: float
    absolute_charge: float
    charge_center: Vec3
    charge_coherent: bool
    indices: tuple[int, ...] = ()
    children: tuple["BarnesHutNode", ...] = ()


def barnes_hut_accelerations(
    positions: Sequence[Sequence[float]],
    masses: Sequence[float],
    charges: Sequence[float],
    alive: Sequence[bool],
    settings: Any,
) -> tuple[list[Vec3], dict[str, int | float | str]]:
    """Approximate long-range gravity/electrostatics with a deterministic octree."""
    count = len(positions)
    result: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(count)]
    active = tuple(index for index in range(count) if bool(alive[index]))
    if len(active) < 2:
        return [tuple(value) for value in result], _receipt(0, 0, 0, settings)
    root = _build_root(positions, masses, charges, active, max(1, int(settings.tree_leaf_capacity)), 0,
                       max(4, int(settings.maximum_tree_depth)))
    theta = max(0.05, min(2.0, float(settings.opening_angle)))
    softening_sq = max(1.0e-30, float(settings.softening) ** 2)
    gravity = float(settings.gravity_constant)
    coulomb = float(settings.coulomb_constant)
    maximum = max(0.0, float(settings.maximum_acceleration))
    approximated = direct = visited = 0
    for target in active:
        target_position = positions[target]
        target_mass = max(1.0e-30, float(masses[target]))
        target_charge = float(charges[target])
        stack = [root]
        while stack:
            node = stack.pop()
            visited += 1
            if node.indices:
                for source in node.indices:
                    if source == target:
                        continue
                    direct += 1
                    _add_pair(
                        result[target], target_position, target_mass, target_charge,
                        positions[source], float(masses[source]), float(charges[source]),
                        gravity, coulomb, softening_sq,
                    )
                continue
            contains_target = all(
                abs(float(target_position[axis]) - node.center[axis]) <= node.half_size * 1.0000001
                for axis in range(3)
            )
            delta = tuple(node.mass_center[axis] - float(target_position[axis]) for axis in range(3))
            distance = math.sqrt(sum(value * value for value in delta) + softening_sq)
            can_approximate = (
                not contains_target and node.half_size * 2.0 / max(1.0e-30, distance) < theta
                and (not coulomb or node.charge_coherent)
            )
            if can_approximate:
                approximated += 1
                if gravity and node.mass > 0.0:
                    _add_monopole(result[target], target_position, node.mass_center, gravity * node.mass, softening_sq)
                if coulomb and target_charge and node.charge:
                    _add_monopole(
                        result[target], target_position, node.charge_center,
                        -coulomb * target_charge * node.charge / target_mass, softening_sq,
                    )
            else:
                stack.extend(reversed(node.children))
        if maximum > 0.0:
            magnitude = math.sqrt(sum(value * value for value in result[target]))
            if magnitude > maximum:
                scale = maximum / magnitude
                result[target] = [value * scale for value in result[target]]
    receipt = _receipt(len(active), visited, direct, settings)
    receipt["approximated_nodes"] = approximated
    receipt["tree_nodes"] = _count_nodes(root)
    return [tuple(value) for value in result], receipt


def _build_root(positions, masses, charges, indices, leaf_capacity, depth, maximum_depth) -> BarnesHutNode:
    minimum = [min(float(positions[index][axis]) for index in indices) for axis in range(3)]
    maximum = [max(float(positions[index][axis]) for index in indices) for axis in range(3)]
    center = tuple((minimum[axis] + maximum[axis]) * 0.5 for axis in range(3))
    half_size = max(1.0e-9, max(maximum[axis] - minimum[axis] for axis in range(3)) * 0.5000001)
    return _build_node(positions, masses, charges, indices, center, half_size, leaf_capacity, depth, maximum_depth)


def _build_node(positions, masses, charges, indices, center, half_size, leaf_capacity, depth, maximum_depth):
    total_mass = sum(max(0.0, float(masses[index])) for index in indices)
    mass_center = tuple(
        sum(float(positions[index][axis]) * max(0.0, float(masses[index])) for index in indices)
        / max(1.0e-30, total_mass)
        for axis in range(3)
    ) if total_mass > 0.0 else center
    total_charge = sum(float(charges[index]) for index in indices)
    absolute_charge = sum(abs(float(charges[index])) for index in indices)
    coherent = absolute_charge <= 1.0e-30 or abs(total_charge) >= absolute_charge * 0.25
    charge_center = tuple(
        sum(float(positions[index][axis]) * float(charges[index]) for index in indices)
        / total_charge for axis in range(3)
    ) if coherent and abs(total_charge) > 1.0e-30 else center
    if len(indices) <= leaf_capacity or depth >= maximum_depth or half_size <= 1.0e-12:
        return BarnesHutNode(center, half_size, len(indices), total_mass, mass_center, total_charge,
                             absolute_charge, charge_center, coherent, tuple(indices))
    buckets: list[list[int]] = [[] for _ in range(8)]
    for index in indices:
        octant = sum((1 << axis) for axis in range(3) if float(positions[index][axis]) >= center[axis])
        buckets[octant].append(index)
    child_half = half_size * 0.5
    children = []
    for octant, bucket in enumerate(buckets):
        if not bucket:
            continue
        child_center = tuple(
            center[axis] + child_half * (1.0 if octant & (1 << axis) else -1.0)
            for axis in range(3)
        )
        children.append(_build_node(
            positions, masses, charges, tuple(bucket), child_center, child_half,
            leaf_capacity, depth + 1, maximum_depth,
        ))
    if len(children) == 1 and len(indices) > leaf_capacity:
        # Coincident/near-coincident points terminate deterministically at maximum depth.
        child = children[0]
        if child.indices:
            return BarnesHutNode(center, half_size, len(indices), total_mass, mass_center, total_charge,
                                 absolute_charge, charge_center, coherent, tuple(indices))
    return BarnesHutNode(center, half_size, len(indices), total_mass, mass_center, total_charge,
                         absolute_charge, charge_center, coherent, children=tuple(children))


def _add_pair(output, target_position, target_mass, target_charge, source_position, source_mass,
              source_charge, gravity, coulomb, softening_sq):
    if gravity and source_mass > 0.0:
        _add_monopole(output, target_position, source_position, gravity * source_mass, softening_sq)
    if coulomb and target_charge and source_charge:
        _add_monopole(
            output, target_position, source_position,
            -coulomb * target_charge * source_charge / target_mass, softening_sq,
        )


def _add_monopole(output, target_position, source_position, strength, softening_sq):
    delta = [float(source_position[axis]) - float(target_position[axis]) for axis in range(3)]
    distance_sq = sum(value * value for value in delta) + softening_sq
    scale = float(strength) / (distance_sq * math.sqrt(distance_sq))
    for axis in range(3):
        output[axis] += delta[axis] * scale


def _count_nodes(root: BarnesHutNode) -> int:
    return 1 + sum(_count_nodes(child) for child in root.children)


def _receipt(particles: int, visits: int, direct: int, settings: Any) -> dict[str, int | float | str]:
    return {
        "method": "barnes_hut",
        "particles": particles,
        "opening_angle": float(settings.opening_angle),
        "node_visits": visits,
        "direct_interactions": direct,
        "approximated_nodes": 0,
        "tree_nodes": 0,
    }


__all__ = ["BarnesHutNode", "barnes_hut_accelerations"]
