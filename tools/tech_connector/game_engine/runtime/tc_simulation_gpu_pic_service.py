"""Persistent NumPy/CuPy-compatible electrostatic PIC kernels."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np


@dataclass
class GpuPicGridState:
    provider_id: str
    resolution: tuple[int, int, int]
    charge_density: Any
    potential: Any
    electric_field: Any

    @property
    def memory_bytes(self) -> int:
        return int(self.charge_density.nbytes + self.potential.nbytes + self.electric_field.nbytes)


def solve_gpu_pic_grids(
    world: Any, particle_buffers: Any, provider: Any, *, readback: bool,
) -> tuple[Any, dict[str, Any]]:
    xp = provider.array_module
    count = particle_buffers.count
    acceleration = xp.zeros((count, 3), dtype=xp.float32)
    if not world.pic_grids or count == 0:
        return acceleration, {"gpu_pic_ms": 0.0, "gpu_pic_cells": 0, "gpu_pic_memory_bytes": 0}
    started = time.perf_counter()
    states = getattr(world, "_gpu_pic_states", None)
    if not isinstance(states, list) or len(states) != len(world.pic_grids):
        states = [None] * len(world.pic_grids)
        world._gpu_pic_states = states
    position = particle_buffers.arrays["positions"].handle[:count]
    mass = particle_buffers.arrays["mass"].handle[:count]
    charge = particle_buffers.arrays["charge"].handle[:count]
    alive = particle_buffers.arrays["alive"].handle[:count]
    diagnostics = []
    total_cells = total_memory = 0
    reused_states = 0
    for grid_index, grid in enumerate(world.pic_grids):
        resolution = tuple(max(3, int(value)) for value in grid.resolution)
        state = states[grid_index]
        if not isinstance(state, GpuPicGridState) or state.provider_id != provider.status.provider_id or state.resolution != resolution:
            density = xp.zeros(resolution, dtype=xp.float32)
            potential = xp.zeros(resolution, dtype=xp.float32)
            electric = xp.zeros(resolution + (3,), dtype=xp.float32)
            state = GpuPicGridState(provider.status.provider_id, resolution, density, potential, electric)
            states[grid_index] = state
        else:
            reused_states += 1
            state.charge_density.fill(0.0)
            state.potential.fill(0.0)
            state.electric_field.fill(0.0)
        minimum = xp.asarray(grid.bounds_min, dtype=xp.float32)
        maximum = xp.asarray(grid.bounds_max, dtype=xp.float32)
        resolution_array = xp.asarray(resolution, dtype=xp.int32)
        spacing = (maximum - minimum) / (resolution_array.astype(xp.float32) - 1.0)
        coordinate = (position - minimum) / spacing
        inside = alive & xp.all(coordinate >= 0.0, axis=1) & xp.all(coordinate <= resolution_array - 1, axis=1)
        lower = xp.floor(coordinate).astype(xp.int32)
        lower = xp.minimum(xp.maximum(lower, 0), resolution_array - 2)
        fraction = coordinate - lower
        flat_density = state.charge_density.reshape(-1)
        for corner in range(8):
            offset = xp.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)), dtype=xp.int32)
            node = lower + offset
            weight = xp.ones(count, dtype=xp.float32)
            for axis in range(3):
                weight *= xp.where(offset[axis] > 0, fraction[:, axis], 1.0 - fraction[:, axis])
            flat_index = (node[:, 0] * resolution[1] + node[:, 1]) * resolution[2] + node[:, 2]
            xp.add.at(flat_density, flat_index[inside], (charge * weight)[inside])
        cell_volume = xp.prod(spacing)
        state.charge_density /= xp.maximum(cell_volume, 1.0e-30)
        inverse_spacing_sq = 1.0 / (spacing * spacing)
        denominator = 2.0 * xp.sum(inverse_spacing_sq)
        periodic = str(grid.boundary_mode).lower() == "periodic"
        for _ in range(max(1, int(grid.potential_iterations))):
            neighbor_sum = sum(
                (xp.roll(state.potential, 1, axis=axis) + xp.roll(state.potential, -1, axis=axis))
                * inverse_spacing_sq[axis] for axis in range(3)
            )
            next_potential = (neighbor_sum + state.charge_density / max(1.0e-30, float(grid.permittivity))) / denominator
            if periodic:
                next_potential -= xp.mean(next_potential)
            else:
                next_potential[0, :, :] = next_potential[-1, :, :] = 0.0
                next_potential[:, 0, :] = next_potential[:, -1, :] = 0.0
                next_potential[:, :, 0] = next_potential[:, :, -1] = 0.0
            state.potential = next_potential
        for axis in range(3):
            component = -(xp.roll(state.potential, -1, axis=axis) - xp.roll(state.potential, 1, axis=axis)) / (2.0 * spacing[axis])
            state.electric_field[..., axis] = component
        sampled = xp.zeros((count, 3), dtype=xp.float32)
        for corner in range(8):
            offset = xp.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)), dtype=xp.int32)
            node = lower + offset
            weight = xp.ones(count, dtype=xp.float32)
            for axis in range(3):
                weight *= xp.where(offset[axis] > 0, fraction[:, axis], 1.0 - fraction[:, axis])
            sampled += state.electric_field[node[:, 0], node[:, 1], node[:, 2]] * weight[:, None]
        acceleration += sampled * (float(grid.field_strength) * charge / xp.maximum(mass, 1.0e-30))[:, None]
        if readback:
            active_cells = int(_scalar(xp, xp.count_nonzero(xp.abs(state.charge_density) > 1.0e-15)))
            deposited = float(_scalar(xp, xp.sum(charge[inside])))
            grid_charge = float(_scalar(xp, xp.sum(state.charge_density) * cell_volume))
            maximum_field = float(_scalar(xp, xp.max(xp.linalg.norm(state.electric_field, axis=3))))
            divergence = sum(
                (xp.roll(state.electric_field[..., axis], -1, axis=axis)
                 - xp.roll(state.electric_field[..., axis], 1, axis=axis)) / (2.0 * spacing[axis])
                for axis in range(3)
            )
            residual = divergence - state.charge_density / max(1.0e-30, float(grid.permittivity))
            if not periodic:
                residual = residual[1:-1, 1:-1, 1:-1]
            gauss_residual = float(_scalar(xp, xp.sqrt(xp.mean(residual * residual))))
            item = {
                "schema": "tech_connector.pic_diagnostics.v1", "active_particles": int(_scalar(xp, xp.count_nonzero(inside))),
                "deposited_charge": deposited, "grid_charge": grid_charge, "active_cells": active_cells,
                "potential_iterations": max(1, int(grid.potential_iterations)), "maximum_field": maximum_field,
                "gauss_residual_l2": gauss_residual, "execution": provider.status.device_type,
                "readback_deferred": False,
            }
        else:
            item = {
                "schema": "tech_connector.pic_diagnostics.v1",
                "potential_iterations": max(1, int(grid.potential_iterations)),
                "execution": provider.status.device_type, "readback_deferred": True,
            }
        diagnostics.append(item)
        grid.diagnostics = item
        if readback:
            grid.charge_density = _host(xp, state.charge_density)
            grid.potential = _host(xp, state.potential)
            grid.electric_field = _host(xp, state.electric_field)
        total_cells += math.prod(resolution)
        total_memory += state.memory_bytes
    if readback:
        provider.synchronize()
    return acceleration, {
        "gpu_pic_ms": (time.perf_counter() - started) * 1000.0,
        "gpu_pic_cells": total_cells, "gpu_pic_memory_bytes": total_memory,
        "gpu_pic_grids": diagnostics, "gpu_pic_resident": not readback,
        "gpu_pic_reused_state": reused_states == len(world.pic_grids),
    }


def _host(xp: Any, value: Any) -> np.ndarray:
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value).copy()


def _scalar(xp: Any, value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


__all__ = ["GpuPicGridState", "solve_gpu_pic_grids"]
