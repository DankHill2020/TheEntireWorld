"""Divergence-controlled magnetic induction grid for plasma effects."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np


Vec3 = tuple[float, float, float]


@dataclass
class MagnetodynamicGrid:
    bounds_min: Vec3 = (-5.0, -5.0, -5.0)
    bounds_max: Vec3 = (5.0, 5.0, 5.0)
    resolution: tuple[int, int, int] = (12, 12, 12)
    uniform_field: Vec3 = (0.0, 1.0, 0.0)
    induction_strength: float = 1.0
    resistivity: float = 0.02
    divergence_clean_iterations: int = 16
    maximum_field: float = 50.0
    magnetic_field: Any = field(default=None, init=False, repr=False, compare=False)
    velocity_field: Any = field(default=None, init=False, repr=False, compare=False)
    current_density: Any = field(default=None, init=False, repr=False, compare=False)
    electric_field: Any = field(default=None, init=False, repr=False, compare=False)
    diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)

    def solve(self, particles: list[Any], dt: float) -> dict[str, Any]:
        resolution = tuple(max(3, int(value)) for value in self.resolution)
        minimum = np.asarray(self.bounds_min, dtype=np.float64)
        maximum = np.asarray(self.bounds_max, dtype=np.float64)
        extent = maximum - minimum
        if np.any(extent <= 0.0):
            raise ValueError("Magnetic bounds_max must exceed bounds_min on every axis.")
        spacing = extent / (np.asarray(resolution, dtype=np.float64) - 1.0)
        if self.magnetic_field is None or tuple(self.magnetic_field.shape[:3]) != resolution:
            self.magnetic_field = np.zeros(resolution + (3,), dtype=np.float64)
            self.magnetic_field[...] = np.asarray(self.uniform_field, dtype=np.float64)
        velocity_sum = np.zeros_like(self.magnetic_field)
        weight_sum = np.zeros(resolution, dtype=np.float64)
        deposited = 0
        for particle in particles:
            if not getattr(particle, "alive", True):
                continue
            coordinate = (np.asarray(particle.position, dtype=np.float64) - minimum) / spacing
            if np.any(coordinate < 0.0) or np.any(coordinate > np.asarray(resolution) - 1.0):
                continue
            lower = np.minimum(np.floor(coordinate).astype(np.int64), np.asarray(resolution) - 2)
            fraction = coordinate - lower
            for corner in range(8):
                offset = np.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)))
                weight = math.prod(fraction[axis] if offset[axis] else 1.0 - fraction[axis] for axis in range(3))
                node = tuple(lower + offset)
                velocity_sum[node] += np.asarray(particle.velocity, dtype=np.float64) * weight
                weight_sum[node] += weight
            deposited += 1
        velocity = np.divide(
            velocity_sum, weight_sum[..., None], out=np.zeros_like(velocity_sum), where=weight_sum[..., None] > 1.0e-12
        )
        magnetic = self.magnetic_field
        motional_electric = -np.cross(velocity, magnetic)
        induction = -_curl(motional_electric, spacing)
        diffusion = _laplacian(magnetic, spacing)
        next_magnetic = magnetic + max(0.0, float(dt)) * (
            float(self.induction_strength) * induction + max(0.0, float(self.resistivity)) * diffusion
        )
        before_divergence = _divergence(next_magnetic, spacing)
        correction = np.zeros(resolution, dtype=np.float64)
        inverse_spacing_sq = 1.0 / (spacing * spacing)
        denominator = 2.0 * float(np.sum(inverse_spacing_sq))
        for _ in range(max(0, int(self.divergence_clean_iterations))):
            neighbor_sum = sum(
                (np.roll(correction, 1, axis=axis) + np.roll(correction, -1, axis=axis))
                * inverse_spacing_sq[axis] for axis in range(3)
            )
            updated = (neighbor_sum - before_divergence) / denominator
            updated[0, :, :] = updated[-1, :, :] = 0.0
            updated[:, 0, :] = updated[:, -1, :] = 0.0
            updated[:, :, 0] = updated[:, :, -1] = 0.0
            correction = updated
        for axis in range(3):
            next_magnetic[..., axis] -= np.gradient(correction, spacing[axis], axis=axis, edge_order=1)
        maximum_field = max(0.0, float(self.maximum_field))
        magnitude = np.linalg.norm(next_magnetic, axis=3)
        if maximum_field > 0.0:
            over = magnitude > maximum_field
            next_magnetic[over] *= (maximum_field / magnitude[over])[:, None]
        current = _curl(next_magnetic, spacing)
        electric = -np.cross(velocity, next_magnetic) + max(0.0, float(self.resistivity)) * current
        parallel_energy = np.abs(np.sum(electric * next_magnetic, axis=3)) / np.maximum(
            1.0e-12, np.linalg.norm(next_magnetic, axis=3)
        )
        after_divergence = _divergence(next_magnetic, spacing)
        self.magnetic_field = next_magnetic
        self.velocity_field = velocity
        self.current_density = current
        self.electric_field = electric
        self.diagnostics = {
            "schema": "tech_connector.magnetic_grid_diagnostics.v1",
            "deposited_particles": deposited,
            "active_velocity_cells": int(np.count_nonzero(weight_sum > 1.0e-12)),
            "magnetic_energy": float(0.5 * np.sum(next_magnetic * next_magnetic) * np.prod(spacing)),
            "maximum_field": float(np.max(np.linalg.norm(next_magnetic, axis=3))),
            "current_rms": float(np.sqrt(np.mean(current * current))),
            "reconnection_energy": float(np.sum(parallel_energy) * np.prod(spacing)),
            "divergence_l2_before": float(np.sqrt(np.mean(before_divergence * before_divergence))),
            "divergence_l2_after": float(np.sqrt(np.mean(after_divergence * after_divergence))),
        }
        return dict(self.diagnostics)

    def sample(self, position: Vec3) -> Vec3:
        if self.magnetic_field is None:
            return tuple(float(value) for value in self.uniform_field)
        return _sample_grid(self.magnetic_field, position, self.bounds_min, self.bounds_max)


def _sample_grid(values, position, bounds_min, bounds_max) -> Vec3:
    resolution = np.asarray(values.shape[:3], dtype=np.int64)
    coordinate = (np.asarray(position) - np.asarray(bounds_min)) / (
        np.asarray(bounds_max) - np.asarray(bounds_min)
    ) * (resolution - 1)
    if np.any(coordinate < 0.0) or np.any(coordinate > resolution - 1):
        return (0.0, 0.0, 0.0)
    lower = np.minimum(np.floor(coordinate).astype(np.int64), resolution - 2)
    fraction = coordinate - lower
    result = np.zeros(3, dtype=np.float64)
    for corner in range(8):
        offset = np.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)))
        weight = math.prod(fraction[axis] if offset[axis] else 1.0 - fraction[axis] for axis in range(3))
        result += values[tuple(lower + offset)] * weight
    return tuple(float(value) for value in result)


def _curl(values, spacing):
    result = np.empty_like(values)
    result[..., 0] = np.gradient(values[..., 2], spacing[1], axis=1) - np.gradient(values[..., 1], spacing[2], axis=2)
    result[..., 1] = np.gradient(values[..., 0], spacing[2], axis=2) - np.gradient(values[..., 2], spacing[0], axis=0)
    result[..., 2] = np.gradient(values[..., 1], spacing[0], axis=0) - np.gradient(values[..., 0], spacing[1], axis=1)
    return result


def _divergence(values, spacing):
    return sum(np.gradient(values[..., axis], spacing[axis], axis=axis) for axis in range(3))


def _laplacian(values, spacing):
    result = np.zeros_like(values)
    for axis in range(3):
        result += (np.roll(values, 1, axis=axis) - 2.0 * values + np.roll(values, -1, axis=axis)) / (spacing[axis] ** 2)
    return result


__all__ = ["MagnetodynamicGrid"]
