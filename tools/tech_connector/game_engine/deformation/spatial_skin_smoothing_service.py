from __future__ import annotations

"""Topology-independent skin-weight smoothing shared by DCC brush adapters."""

from collections import defaultdict
from math import cos, floor, radians, sqrt
from typing import Iterable, Mapping, Sequence


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _distance_squared(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))


def spatial_smooth_weight_rows(
    positions: Sequence[Sequence[float]],
    weight_rows: Sequence[Mapping[str, float]],
    *,
    radius: float,
    strength: float = 0.5,
    iterations: int = 1,
    target_indices: Iterable[int] | None = None,
    center: Sequence[float] | None = None,
    normals: Sequence[Sequence[float]] | None = None,
    normal_angle: float = 120.0,
    max_neighbors: int = 96,
    max_influences: int = 8,
    locked_influences: Iterable[str] = (),
    hardness: float = 0.5,
    sample_weights: Sequence[float] | None = None,
    cross_region_share: float = 0.45,
) -> tuple[list[dict[str, float]], tuple[int, ...]]:
    """Diffuse weights through geometric neighborhoods without using edges.

    When ``center`` is supplied, only vertices inside the brush sphere change
    and strength falls off toward its edge. The complete influence field is
    diffused before a single final prune, avoiding hard radial boundaries.
    """
    count = len(positions)
    if len(weight_rows) != count:
        raise ValueError("Position and weight-row counts must match.")
    radius = float(radius)
    if radius <= 0.0:
        raise ValueError("Radius must be greater than zero.")
    strength = max(0.0, min(1.0, float(strength)))
    iterations = max(1, int(iterations))
    max_neighbors = max(2, int(max_neighbors))
    max_influences = max(1, int(max_influences))
    hardness = max(0.01, float(hardness))
    cross_region_share = max(0.0, min(0.49, float(cross_region_share)))
    locked = {str(value) for value in locked_influences}
    if sample_weights is None:
        surface_weights = [1.0] * count
    else:
        if len(sample_weights) != count:
            raise ValueError("Sample-weight count must match the position count.")
        positive = [float(value) for value in sample_weights if float(value) > 1.0e-12]
        fallback = sum(positive) / len(positive) if positive else 1.0
        surface_weights = [
            float(value) if float(value) > 1.0e-12 else fallback
            for value in sample_weights
        ]

    if target_indices is None:
        targets = list(range(count))
    else:
        targets = sorted({int(value) for value in target_indices if 0 <= int(value) < count})
    radius_squared = radius * radius
    if center is not None:
        targets = [index for index in targets if _distance_squared(positions[index], center) <= radius_squared]
    if not targets:
        return [dict(row) for row in weight_rows], ()

    inverse_cell = 1.0 / radius
    cells: list[tuple[int, int, int]] = []
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, position in enumerate(positions):
        cell = tuple(int(floor(float(position[axis]) * inverse_cell)) for axis in range(3))
        cells.append(cell)
        buckets[cell].append(index)
    normal_limit = cos(radians(max(0.0, min(180.0, float(normal_angle)))))
    neighbor_cache: dict[int, list[tuple[int, float]]] = {}

    def limit_neighbors(found: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if len(found) <= max_neighbors:
            return found
        groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for candidate, kernel_weight in found:
            row = weight_rows[candidate]
            dominant = max(row, key=lambda name: float(row[name])) if row else ""
            groups[str(dominant)].append((candidate, kernel_weight))
        for values in groups.values():
            values.sort(key=lambda item: item[1], reverse=True)
        ordered_groups = sorted(groups.values(), key=lambda values: values[0][1], reverse=True)
        quota = max(1, min(4, max_neighbors // max(1, len(ordered_groups) * 2)))
        selected: list[tuple[int, float]] = []
        selected_indices: set[int] = set()
        for values in ordered_groups:
            for item in values[:quota]:
                if len(selected) >= max_neighbors:
                    break
                selected.append(item)
                selected_indices.add(item[0])
        if len(selected) < max_neighbors:
            for item in sorted(found, key=lambda value: value[1], reverse=True):
                if item[0] in selected_indices:
                    continue
                selected.append(item)
                if len(selected) >= max_neighbors:
                    break
        return selected

    def neighbors(index: int) -> list[tuple[int, float]]:
        cached = neighbor_cache.get(index)
        if cached is not None:
            return cached
        cell = cells[index]
        found: list[tuple[int, float]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                        if candidate == index:
                            continue
                        distance_squared = _distance_squared(positions[index], positions[candidate])
                        if distance_squared > radius_squared:
                            continue
                        if normals is not None and _dot(normals[index], normals[candidate]) < normal_limit:
                            continue
                        falloff = 1.0 - min(1.0, sqrt(max(0.0, distance_squared)) / radius)
                        found.append((
                            candidate,
                            max(0.0001, falloff * falloff) * surface_weights[candidate],
                        ))
        neighbor_cache[index] = limit_neighbors(found) or [(index, 1.0)]
        return neighbor_cache[index]

    def balanced_neighbors(index: int) -> list[tuple[int, float]]:
        found = neighbors(index)
        groups: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for candidate, value in found:
            row = weight_rows[candidate]
            dominant = max(row, key=lambda name: float(row[name])) if row else ""
            groups[str(dominant)].append((candidate, value))
        if len(groups) < 2:
            return found
        totals = {key: sum(value for _candidate, value in values) for key, values in groups.items()}
        total = sum(totals.values())
        if total <= 1.0e-12:
            return found
        dominant_group = max(totals, key=totals.get)
        maximum_region_share = 1.0 - cross_region_share
        if totals[dominant_group] / total <= maximum_region_share:
            return found
        other_total = total - totals[dominant_group]
        dominant_scale = maximum_region_share / totals[dominant_group]
        other_scale = cross_region_share / other_total
        dominant_indices = {candidate for candidate, _value in groups[dominant_group]}
        return [
            (candidate, value * (dominant_scale if candidate in dominant_indices else other_scale))
            for candidate, value in found
        ]

    rows = [dict(row) for row in weight_rows]
    all_names = sorted({str(name) for row in rows for name in row})
    for _iteration in range(iterations):
        next_rows = [dict(row) for row in rows]
        for index in targets:
            current = rows[index]
            averaged = {name: 0.0 for name in all_names}
            total = 0.0
            for neighbor, falloff in balanced_neighbors(index):
                total += falloff
                for name, value in rows[neighbor].items():
                    averaged[name] = averaged.get(name, 0.0) + float(value) * falloff
            local_strength = strength
            if center is not None:
                edge = 1.0 - min(1.0, sqrt(_distance_squared(positions[index], center)) / radius)
                local_strength *= edge ** max(0.1, 2.0 - hardness)
            divisor = 1.0 / max(total, 1.0e-12)
            blended = {
                name: float(current.get(name, 0.0)) * (1.0 - local_strength)
                + float(averaged.get(name, 0.0)) * divisor * local_strength
                for name in all_names
            }
            locked_total = sum(float(current.get(name, 0.0)) for name in locked)
            for name in locked:
                blended[name] = float(current.get(name, 0.0))
            unlocked = [name for name in all_names if name not in locked]
            unlocked_total = sum(max(0.0, blended[name]) for name in unlocked)
            if unlocked_total > 1.0e-12:
                scale = max(0.0, 1.0 - locked_total) / unlocked_total
                for name in unlocked:
                    blended[name] = max(0.0, blended[name]) * scale
            next_rows[index] = blended
        rows = next_rows

    for index in targets:
        row = rows[index]
        locked_values = {name: float(row.get(name, 0.0)) for name in locked if row.get(name, 0.0) > 0.0}
        slots = max(1 if sum(locked_values.values()) < 0.999999 else 0, max_influences - len(locked_values))
        unlocked_values = sorted(
            ((name, max(0.0, float(value))) for name, value in row.items() if name not in locked and value > 1.0e-12),
            key=lambda item: (-item[1], item[0]),
        )[:slots]
        unlocked_total = sum(value for _, value in unlocked_values)
        available = max(0.0, 1.0 - sum(locked_values.values()))
        result = dict(locked_values)
        if unlocked_total > 1.0e-12:
            result.update({name: value * available / unlocked_total for name, value in unlocked_values})
        rows[index] = result
    return rows, tuple(targets)


__all__ = ["spatial_smooth_weight_rows"]
