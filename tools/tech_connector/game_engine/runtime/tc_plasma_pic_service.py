"""Electrostatic particle-in-cell grid for plasma and space-weather effects."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np


Vec3 = tuple[float, float, float]


@dataclass
class ElectrostaticPicGrid:
    bounds_min: Vec3 = (-5.0, -5.0, -5.0)
    bounds_max: Vec3 = (5.0, 5.0, 5.0)
    resolution: tuple[int, int, int] = (16, 16, 16)
    permittivity: float = 1.0
    potential_iterations: int = 32
    field_strength: float = 1.0
    boundary_mode: str = "dirichlet"
    charge_density: Any = field(default=None, init=False, repr=False, compare=False)
    potential: Any = field(default=None, init=False, repr=False, compare=False)
    electric_field: Any = field(default=None, init=False, repr=False, compare=False)
    diagnostics: dict[str, Any] = field(default_factory=dict, init=False, repr=False, compare=False)

    def solve(self, particles: list[Any]) -> dict[str, Any]:
        resolution = tuple(max(3, int(value)) for value in self.resolution)
        minimum = np.asarray(self.bounds_min, dtype=np.float64)
        maximum = np.asarray(self.bounds_max, dtype=np.float64)
        extent = maximum - minimum
        if np.any(extent <= 0.0):
            raise ValueError("PIC bounds_max must be greater than bounds_min on every axis.")
        spacing = extent / (np.asarray(resolution, dtype=np.float64) - 1.0)
        density = np.zeros(resolution, dtype=np.float64)
        deposited_charge = 0.0
        active_particles = 0
        for particle in particles:
            charge = float(getattr(particle, "charge", 0.0))
            if not getattr(particle, "alive", True) or charge == 0.0:
                continue
            coordinate = (np.asarray(particle.position, dtype=np.float64) - minimum) / spacing
            if np.any(coordinate < 0.0) or np.any(coordinate > np.asarray(resolution) - 1.0):
                continue
            lower = np.floor(coordinate).astype(np.int64)
            lower = np.minimum(lower, np.asarray(resolution, dtype=np.int64) - 2)
            fraction = coordinate - lower
            for corner in range(8):
                offset = np.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)))
                weight = math.prod(
                    fraction[axis] if offset[axis] else 1.0 - fraction[axis] for axis in range(3)
                )
                density[tuple(lower + offset)] += charge * weight
            deposited_charge += charge
            active_particles += 1
        cell_volume = float(np.prod(spacing))
        density /= max(1.0e-30, cell_volume)
        potential = np.zeros(resolution, dtype=np.float64)
        inverse_spacing_sq = 1.0 / (spacing * spacing)
        denominator = 2.0 * float(np.sum(inverse_spacing_sq))
        iterations = max(1, int(self.potential_iterations))
        periodic = str(self.boundary_mode).lower() == "periodic"
        if str(self.boundary_mode).lower() not in {"dirichlet", "periodic"}:
            raise ValueError(f"Unknown PIC boundary mode: {self.boundary_mode}")
        for _ in range(iterations):
            if periodic:
                neighbor_sum = sum(
                    (np.roll(potential, 1, axis=axis) + np.roll(potential, -1, axis=axis))
                    * inverse_spacing_sq[axis]
                    for axis in range(3)
                )
                potential = (neighbor_sum + density / max(1.0e-30, float(self.permittivity))) / denominator
                potential -= float(np.mean(potential))
            else:
                next_potential = np.zeros_like(potential)
                neighbor_sum = sum(
                    (np.roll(potential, 1, axis=axis) + np.roll(potential, -1, axis=axis))
                    * inverse_spacing_sq[axis]
                    for axis in range(3)
                )
                next_potential[1:-1, 1:-1, 1:-1] = (
                    neighbor_sum[1:-1, 1:-1, 1:-1]
                    + density[1:-1, 1:-1, 1:-1] / max(1.0e-30, float(self.permittivity))
                ) / denominator
                potential = next_potential
        electric = np.zeros(resolution + (3,), dtype=np.float64)
        for axis in range(3):
            electric[..., axis] = -np.gradient(potential, spacing[axis], axis=axis, edge_order=1)
        self.charge_density = density
        self.potential = potential
        self.electric_field = electric
        gauss_divergence = sum(
            np.gradient(electric[..., axis], spacing[axis], axis=axis, edge_order=1)
            for axis in range(3)
        )
        target_divergence = density / max(1.0e-30, float(self.permittivity))
        self.diagnostics = {
            "schema": "tech_connector.pic_diagnostics.v1",
            "active_particles": active_particles,
            "deposited_charge": deposited_charge,
            "grid_charge": float(np.sum(density) * cell_volume),
            "active_cells": int(np.count_nonzero(np.abs(density) > 1.0e-15)),
            "potential_iterations": iterations,
            "maximum_field": float(np.max(np.linalg.norm(electric, axis=3))),
            "gauss_residual_l2": float(np.sqrt(np.mean((gauss_divergence - target_divergence) ** 2))),
        }
        return dict(self.diagnostics)

    def sample(self, position: Vec3) -> Vec3:
        if self.electric_field is None:
            return (0.0, 0.0, 0.0)
        resolution = np.asarray(self.electric_field.shape[:3], dtype=np.int64)
        minimum = np.asarray(self.bounds_min, dtype=np.float64)
        maximum = np.asarray(self.bounds_max, dtype=np.float64)
        coordinate = (np.asarray(position, dtype=np.float64) - minimum) / (maximum - minimum) * (resolution - 1)
        if np.any(coordinate < 0.0) or np.any(coordinate > resolution - 1):
            return (0.0, 0.0, 0.0)
        lower = np.minimum(np.floor(coordinate).astype(np.int64), resolution - 2)
        fraction = coordinate - lower
        value = np.zeros(3, dtype=np.float64)
        for corner in range(8):
            offset = np.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)))
            weight = math.prod(fraction[axis] if offset[axis] else 1.0 - fraction[axis] for axis in range(3))
            value += self.electric_field[tuple(lower + offset)] * weight
        value *= float(self.field_strength)
        return tuple(float(component) for component in value)


__all__ = ["ElectrostaticPicGrid"]
