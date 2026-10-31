from __future__ import annotations

"""Topology-independent skin-weight smoothing shared by DCC brush adapters."""

from collections import defaultdict
from math import cos, floor, radians, sqrt
from typing import Iterable, Mapping, Sequence


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _distance_squared(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))


def estimate_spatial_smoothing_radius(
    positions: Sequence[Sequence[float]],
    *,
    sample_weights: Sequence[float] | None = None,
) -> float:
    """Choose a scale-aware radius for a whole-surface smoothing pass.

    ``sample_weights`` should contain the world-space surface area represented
    by each vertex.  Using both typical and sparse-region areas keeps the
    radius useful on production meshes that mix dense torso topology with long,
    stretched garment polygons.  The bounds based on the mesh diagonal prevent
    tiny numerical radii and broad cross-body weight bleeding.
    """
    if not positions:
        raise ValueError("At least one position is required to estimate a radius.")
    if sample_weights is not None and len(sample_weights) != len(positions):
        raise ValueError("Sample-weight count must match the position count.")

    coordinates = [tuple(float(point[axis]) for axis in range(3)) for point in positions]
    extents = [
        max(point[axis] for point in coordinates) - min(point[axis] for point in coordinates)
        for axis in range(3)
    ]
    diagonal = sqrt(sum(value * value for value in extents))
    if diagonal <= 1.0e-12:
        return 1.0

    if sample_weights is None:
        # A surface's characteristic vertex spacing scales with sqrt(area/N).
        # The diagonal is a stable area proxy when topology data is unavailable.
        characteristic = diagonal / sqrt(max(1.0, float(len(coordinates))))
        typical_spacing = sparse_spacing = characteristic
    else:
        areas = sorted(float(value) for value in sample_weights if float(value) > 1.0e-12)
        if not areas:
            characteristic = diagonal / sqrt(max(1.0, float(len(coordinates))))
            typical_spacing = sparse_spacing = characteristic
        else:
            def percentile(fraction: float) -> float:
                index = int(round((len(areas) - 1) * fraction))
                return areas[max(0, min(len(areas) - 1, index))]

            typical_spacing = sqrt(percentile(0.5))
            sparse_spacing = sqrt(percentile(0.9))

    radius = max(
        typical_spacing * 4.0,
        sparse_spacing * 2.0,
        diagonal * 0.005,
    )
    return max(diagonal * 1.0e-5, min(radius, diagonal * 0.08))


def detect_weight_outlier_indices(
    weight_rows: Sequence[Mapping[str, float]],
    topology_neighbors: Sequence[Iterable[int]],
    *,
    minimum_difference: float = 0.06,
    consensus_ratio: float = 1.0,
) -> tuple[int, ...]:
    """Find isolated weight spikes suitable for a Weight-Hammer-like repair.

    A vertex is selected only when it differs from the average of at least
    three connected neighbors substantially more than those neighbors differ
    from one another.  Linear and otherwise coherent weight gradients therefore
    remain untouched instead of becoming progressively soft or "noodly".
    """
    count = len(weight_rows)
    if len(topology_neighbors) != count:
        raise ValueError("Topology-neighbor count must match the weight-row count.")
    minimum_difference = max(0.0, min(1.0, float(minimum_difference)))
    consensus_ratio = max(1.0, float(consensus_ratio))
    names = sorted({str(name) for row in weight_rows for name in row})
    if not names:
        return ()

    def row_distance(left: Mapping[str, float], right: Mapping[str, float]) -> float:
        # Total-variation distance is bounded by one for normalized rows.
        return 0.5 * sum(
            abs(float(left.get(name, 0.0)) - float(right.get(name, 0.0)))
            for name in names
        )

    outliers: list[int] = []
    for index, candidate_values in enumerate(topology_neighbors):
        connected = sorted({
            int(value) for value in candidate_values
            if int(value) != index and 0 <= int(value) < count
        })
        # Two connected samples are sufficient for a boundary row. Endpoints
        # with only one neighbor still lack enough evidence and remain fixed.
        if len(connected) < 2:
            continue
        average = {
            name: sum(float(weight_rows[neighbor].get(name, 0.0)) for neighbor in connected)
            / float(len(connected))
            for name in names
        }
        difference = row_distance(weight_rows[index], average)
        neighbor_dispersion = sum(
            row_distance(weight_rows[neighbor], average) for neighbor in connected
        ) / float(len(connected))
        if (
            difference >= minimum_difference
            and difference >= (neighbor_dispersion * consensus_ratio) + (minimum_difference * 0.25)
        ):
            outliers.append(index)
    return tuple(outliers)


def detect_deformation_ripple_indices(
    bind_positions: Sequence[Sequence[float]],
    posed_positions: Sequence[Sequence[float]],
    topology_neighbors: Sequence[Iterable[int]],
    *,
    minimum_edge_fraction: float = 0.015,
    curvature_ratio: float = 0.55,
) -> tuple[int, ...]:
    """Detect high-frequency posed ripples absent from the input surface.

    The signal is the Laplacian of skinning displacement, not mesh curvature,
    so folds already present before deformation are ignored. Smooth bends have
    a near-linear displacement field; saw-tooth weighting produces a large
    second difference and is selected for conservative hammering.
    """
    count = len(bind_positions)
    if len(posed_positions) != count or len(topology_neighbors) != count:
        raise ValueError("Bind, posed, and topology counts must match.")
    minimum_edge_fraction = max(0.0, float(minimum_edge_fraction))
    curvature_ratio = max(0.0, float(curvature_ratio))

    bind = [tuple(float(point[axis]) for axis in range(3)) for point in bind_positions]
    posed = [tuple(float(point[axis]) for axis in range(3)) for point in posed_positions]
    displacement = [
        tuple(posed[index][axis] - bind[index][axis] for axis in range(3))
        for index in range(count)
    ]

    def length(vector: Sequence[float]) -> float:
        return sqrt(sum(float(value) * float(value) for value in vector))

    ripples: list[int] = []
    for index, candidate_values in enumerate(topology_neighbors):
        connected = sorted({
            int(value) for value in candidate_values
            if int(value) != index and 0 <= int(value) < count
        })
        if len(connected) < 2:
            continue
        average = tuple(
            sum(displacement[neighbor][axis] for neighbor in connected) / float(len(connected))
            for axis in range(3)
        )
        curvature = length(tuple(displacement[index][axis] - average[axis] for axis in range(3)))
        first_difference = sum(
            length(tuple(
                displacement[index][axis] - displacement[neighbor][axis]
                for axis in range(3)
            ))
            for neighbor in connected
        ) / float(len(connected))
        local_edge_scale = sum(
            sqrt(_distance_squared(bind[index], bind[neighbor])) for neighbor in connected
        ) / float(len(connected))
        if (
            curvature >= local_edge_scale * minimum_edge_fraction
            and curvature >= first_difference * curvature_ratio
        ):
            ripples.append(index)
    return tuple(ripples)


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
    topology_neighbors: Sequence[Iterable[int]] | None = None,
    topology_share: float = 0.0,
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
    topology_share = max(0.0, min(1.0, float(topology_share)))
    if topology_neighbors is not None and len(topology_neighbors) != count:
        raise ValueError("Topology-neighbor count must match the position count.")
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

    def smoothing_neighbors(index: int) -> list[tuple[int, float]]:
        """Blend surface connectivity with proximity samples.

        Spatial-only neighborhoods can alternate across long or uneven polygon
        rows, producing a saw-tooth deformation even though the bind surface is
        clean.  Connected neighbors provide a continuous weight gradient while
        the spatial portion still bridges cracks and disconnected pieces.
        """
        spatial = balanced_neighbors(index)
        if topology_neighbors is None or topology_share <= 0.0:
            return spatial
        connected: list[tuple[int, float]] = []
        for candidate_value in topology_neighbors[index]:
            candidate = int(candidate_value)
            if candidate == index or not 0 <= candidate < count:
                continue
            distance = sqrt(max(_distance_squared(positions[index], positions[candidate]), 1.0e-12))
            connected.append((candidate, 1.0 / sqrt(distance)))
        if not connected:
            return spatial

        spatial_total = sum(value for _candidate, value in spatial)
        connected_total = sum(value for _candidate, value in connected)
        combined: dict[int, float] = defaultdict(float)
        spatial_share = 1.0 - topology_share
        if spatial_total > 1.0e-12 and spatial_share > 0.0:
            for candidate, value in spatial:
                combined[candidate] += spatial_share * value / spatial_total
        for candidate, value in connected:
            combined[candidate] += topology_share * value / connected_total
        return list(combined.items())

    rows = [dict(row) for row in weight_rows]
    all_names = sorted({str(name) for row in rows for name in row})
    for _iteration in range(iterations):
        next_rows = [dict(row) for row in rows]
        for index in targets:
            current = rows[index]
            averaged = {name: 0.0 for name in all_names}
            total = 0.0
            for neighbor, falloff in smoothing_neighbors(index):
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


__all__ = [
    "detect_weight_outlier_indices",
    "detect_deformation_ripple_indices",
    "estimate_spatial_smoothing_radius",
    "spatial_smooth_weight_rows",
]
