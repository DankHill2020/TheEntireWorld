"""Deterministic cutoff spatial hash for molecular and screened interactions."""

from __future__ import annotations

import math
from typing import Any, Sequence


Vec3 = tuple[float, float, float]


def spatial_hash_accelerations(
    positions: Sequence[Sequence[float]], masses: Sequence[float], alive: Sequence[bool], settings: Any,
) -> tuple[list[Vec3], dict[str, int | float | str]]:
    count = len(positions)
    output = [[0.0, 0.0, 0.0] for _ in range(count)]
    cutoff = max(1.0e-12, float(settings.cutoff))
    cells: dict[tuple[int, int, int], list[int]] = {}
    for index in range(count):
        if not bool(alive[index]):
            continue
        key = tuple(math.floor(float(positions[index][axis]) / cutoff) for axis in range(3))
        cells.setdefault(key, []).append(index)
    candidates = interactions = 0
    keys = sorted(cells)
    for key in keys:
        first_indices = cells[key]
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for offset_z in (-1, 0, 1):
                    neighbor = (key[0] + offset_x, key[1] + offset_y, key[2] + offset_z)
                    if neighbor not in cells or neighbor < key:
                        continue
                    second_indices = cells[neighbor]
                    for first_offset, first in enumerate(first_indices):
                        start = first_offset + 1 if neighbor == key else 0
                        for second in second_indices[start:]:
                            candidates += 1
                            delta = [float(positions[second][axis]) - float(positions[first][axis]) for axis in range(3)]
                            raw_distance_sq = sum(value * value for value in delta)
                            if raw_distance_sq > cutoff * cutoff:
                                continue
                            distance_sq = raw_distance_sq + max(1.0e-30, float(settings.softening) ** 2)
                            distance = math.sqrt(distance_sq)
                            direction = [value / max(1.0e-30, distance) for value in delta]
                            force = 0.0
                            if settings.lennard_jones_epsilon:
                                ratio = min(10.0, float(settings.lennard_jones_sigma) / max(1.0e-30, distance))
                                ratio6 = ratio ** 6
                                force += 24.0 * float(settings.lennard_jones_epsilon) * (
                                    2.0 * ratio6 * ratio6 - ratio6
                                ) / max(1.0e-30, distance)
                            if settings.yukawa_strength:
                                screening = max(0.0, float(settings.yukawa_screening))
                                force += float(settings.yukawa_strength) * math.exp(-screening * distance) * (
                                    1.0 / distance_sq + screening / max(1.0e-30, distance)
                                )
                            first_scale = -force / max(1.0e-30, float(masses[first]))
                            second_scale = force / max(1.0e-30, float(masses[second]))
                            for axis in range(3):
                                output[first][axis] += direction[axis] * first_scale
                                output[second][axis] += direction[axis] * second_scale
                            interactions += 1
    maximum = max(0.0, float(settings.maximum_acceleration))
    if maximum > 0.0:
        for index, value in enumerate(output):
            magnitude = math.sqrt(sum(component * component for component in value))
            if magnitude > maximum:
                scale = maximum / magnitude
                output[index] = [component * scale for component in value]
    return [tuple(value) for value in output], {
        "method": "spatial_hash", "particles": sum(bool(value) for value in alive),
        "active_cells": len(cells), "candidate_pairs": candidates,
        "direct_interactions": interactions, "cutoff": cutoff,
    }


__all__ = ["spatial_hash_accelerations"]
