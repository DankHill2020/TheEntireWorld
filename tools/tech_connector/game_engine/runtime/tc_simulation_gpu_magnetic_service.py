"""Persistent NumPy/CuPy-compatible magnetic induction grid kernels."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any

import numpy as np


@dataclass
class GpuMagneticGridState:
    provider_id: str
    resolution: tuple[int, int, int]
    magnetic_field: Any
    velocity_field: Any
    current_density: Any
    electric_field: Any

    @property
    def memory_bytes(self) -> int:
        return int(sum(value.nbytes for value in (
            self.magnetic_field, self.velocity_field, self.current_density, self.electric_field,
        )))


def solve_gpu_magnetic_grids(
    world: Any, particle_buffers: Any, provider: Any, dt: float, *, readback: bool,
) -> tuple[Any, dict[str, Any]]:
    xp = provider.array_module
    count = particle_buffers.count
    sampled_field = xp.zeros((count, 3), dtype=xp.float32)
    if not world.magnetic_grids or count == 0:
        return sampled_field, _empty_receipt()
    started = time.perf_counter()
    states = getattr(world, "_gpu_magnetic_states", None)
    if not isinstance(states, list) or len(states) != len(world.magnetic_grids):
        states = [None] * len(world.magnetic_grids)
        world._gpu_magnetic_states = states
    position = particle_buffers.arrays["positions"].handle[:count]
    velocity = particle_buffers.arrays["velocities"].handle[:count]
    alive = particle_buffers.arrays["alive"].handle[:count]
    diagnostics = []
    total_cells = total_memory = reused_states = 0
    for grid_index, grid in enumerate(world.magnetic_grids):
        resolution = tuple(max(3, int(value)) for value in grid.resolution)
        state = states[grid_index]
        if not isinstance(state, GpuMagneticGridState) or state.provider_id != provider.status.provider_id or state.resolution != resolution:
            magnetic = xp.zeros(resolution + (3,), dtype=xp.float32)
            magnetic[...] = xp.asarray(grid.uniform_field, dtype=xp.float32)
            state = GpuMagneticGridState(
                provider.status.provider_id, resolution, magnetic, xp.zeros_like(magnetic),
                xp.zeros_like(magnetic), xp.zeros_like(magnetic),
            )
            states[grid_index] = state
        else:
            reused_states += 1
            state.velocity_field.fill(0.0)
        minimum = xp.asarray(grid.bounds_min, dtype=xp.float32)
        maximum = xp.asarray(grid.bounds_max, dtype=xp.float32)
        resolution_array = xp.asarray(resolution, dtype=xp.int32)
        spacing = (maximum - minimum) / (resolution_array.astype(xp.float32) - 1.0)
        coordinate = (position - minimum) / spacing
        inside = alive & xp.all(coordinate >= 0.0, axis=1) & xp.all(coordinate <= resolution_array - 1, axis=1)
        lower = xp.minimum(xp.maximum(xp.floor(coordinate).astype(xp.int32), 0), resolution_array - 2)
        fraction = coordinate - lower
        weight_grid = xp.zeros(resolution, dtype=xp.float32)
        flat_weight = weight_grid.reshape(-1)
        flat_velocity = state.velocity_field.reshape((-1, 3))
        for corner in range(8):
            offset = xp.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)), dtype=xp.int32)
            node = lower + offset
            weight = xp.ones(count, dtype=xp.float32)
            for axis in range(3):
                weight *= xp.where(offset[axis] > 0, fraction[:, axis], 1.0 - fraction[:, axis])
            flat_index = (node[:, 0] * resolution[1] + node[:, 1]) * resolution[2] + node[:, 2]
            xp.add.at(flat_weight, flat_index[inside], weight[inside])
            for axis in range(3):
                xp.add.at(flat_velocity[:, axis], flat_index[inside], (velocity[:, axis] * weight)[inside])
        state.velocity_field = xp.divide(
            state.velocity_field, weight_grid[..., None], out=xp.zeros_like(state.velocity_field),
            where=weight_grid[..., None] > 1.0e-12,
        )
        motional_electric = -xp.cross(state.velocity_field, state.magnetic_field)
        induction = -_curl(xp, motional_electric, spacing)
        diffusion = _laplacian(xp, state.magnetic_field, spacing)
        next_magnetic = state.magnetic_field + max(0.0, float(dt)) * (
            float(grid.induction_strength) * induction + max(0.0, float(grid.resistivity)) * diffusion
        )
        divergence_before = _divergence(xp, next_magnetic, spacing)
        correction = xp.zeros(resolution, dtype=xp.float32)
        inverse_spacing_sq = 1.0 / (spacing * spacing)
        denominator = 2.0 * xp.sum(inverse_spacing_sq)
        for _ in range(max(0, int(grid.divergence_clean_iterations))):
            neighbor_sum = sum(
                (xp.roll(correction, 1, axis=axis) + xp.roll(correction, -1, axis=axis))
                * inverse_spacing_sq[axis] for axis in range(3)
            )
            updated = (neighbor_sum - divergence_before) / denominator
            updated[0, :, :] = updated[-1, :, :] = 0.0
            updated[:, 0, :] = updated[:, -1, :] = 0.0
            updated[:, :, 0] = updated[:, :, -1] = 0.0
            correction = updated
        for axis in range(3):
            gradient = (xp.roll(correction, -1, axis=axis) - xp.roll(correction, 1, axis=axis)) / (2.0 * spacing[axis])
            next_magnetic[..., axis] -= gradient
        magnitude = xp.linalg.norm(next_magnetic, axis=3)
        maximum_field = max(0.0, float(grid.maximum_field))
        if maximum_field > 0.0:
            scale = xp.minimum(1.0, maximum_field / xp.maximum(magnitude, 1.0e-12))
            next_magnetic *= scale[..., None]
        state.magnetic_field = next_magnetic
        state.current_density = _curl(xp, next_magnetic, spacing)
        state.electric_field = -xp.cross(state.velocity_field, next_magnetic) + max(
            0.0, float(grid.resistivity)
        ) * state.current_density
        sampled = _sample_vector_grid(xp, next_magnetic, lower, fraction) * inside[:, None]
        sampled_field += sampled
        if readback:
            divergence_after = _divergence(xp, next_magnetic, spacing)
            parallel = xp.abs(xp.sum(state.electric_field * next_magnetic, axis=3)) / xp.maximum(
                1.0e-12, xp.linalg.norm(next_magnetic, axis=3)
            )
            cell_volume = xp.prod(spacing)
            item = {
                "schema": "tech_connector.magnetic_grid_diagnostics.v1",
                "deposited_particles": int(_scalar(xp.count_nonzero(inside))),
                "active_velocity_cells": int(_scalar(xp.count_nonzero(weight_grid > 1.0e-12))),
                "magnetic_energy": float(_scalar(0.5 * xp.sum(next_magnetic * next_magnetic) * cell_volume)),
                "maximum_field": float(_scalar(xp.max(xp.linalg.norm(next_magnetic, axis=3)))),
                "current_rms": float(_scalar(xp.sqrt(xp.mean(state.current_density * state.current_density)))),
                "reconnection_energy": float(_scalar(xp.sum(parallel) * cell_volume)),
                "divergence_l2_before": float(_scalar(xp.sqrt(xp.mean(divergence_before * divergence_before)))),
                "divergence_l2_after": float(_scalar(xp.sqrt(xp.mean(divergence_after * divergence_after)))),
                "execution": provider.status.device_type, "readback_deferred": False,
            }
            grid.magnetic_field = _host(xp, state.magnetic_field)
            grid.velocity_field = _host(xp, state.velocity_field)
            grid.current_density = _host(xp, state.current_density)
            grid.electric_field = _host(xp, state.electric_field)
        else:
            item = {
                "schema": "tech_connector.magnetic_grid_diagnostics.v1",
                "execution": provider.status.device_type, "readback_deferred": True,
            }
        grid.diagnostics = item
        diagnostics.append(item)
        total_cells += math.prod(resolution)
        total_memory += state.memory_bytes
    if readback:
        provider.synchronize()
    return sampled_field, {
        "gpu_magnetic_ms": (time.perf_counter() - started) * 1000.0,
        "gpu_magnetic_cells": total_cells, "gpu_magnetic_memory_bytes": total_memory,
        "gpu_magnetic_grids": diagnostics, "gpu_magnetic_resident": not readback,
        "gpu_magnetic_reused_state": reused_states == len(world.magnetic_grids),
    }


def _sample_vector_grid(xp, values, lower, fraction):
    result = xp.zeros((len(lower), 3), dtype=xp.float32)
    for corner in range(8):
        offset = xp.asarray(tuple(1 if corner & (1 << axis) else 0 for axis in range(3)), dtype=xp.int32)
        node = lower + offset
        weight = xp.ones(len(lower), dtype=xp.float32)
        for axis in range(3):
            weight *= xp.where(offset[axis] > 0, fraction[:, axis], 1.0 - fraction[:, axis])
        result += values[node[:, 0], node[:, 1], node[:, 2]] * weight[:, None]
    return result


def _curl(xp, values, spacing):
    result = xp.empty_like(values)
    result[..., 0] = _derivative(xp, values[..., 2], 1, spacing[1]) - _derivative(xp, values[..., 1], 2, spacing[2])
    result[..., 1] = _derivative(xp, values[..., 0], 2, spacing[2]) - _derivative(xp, values[..., 2], 0, spacing[0])
    result[..., 2] = _derivative(xp, values[..., 1], 0, spacing[0]) - _derivative(xp, values[..., 0], 1, spacing[1])
    return result


def _divergence(xp, values, spacing):
    return sum(_derivative(xp, values[..., axis], axis, spacing[axis]) for axis in range(3))


def _derivative(xp, values, axis, spacing):
    return (xp.roll(values, -1, axis=axis) - xp.roll(values, 1, axis=axis)) / (2.0 * spacing)


def _laplacian(xp, values, spacing):
    result = xp.zeros_like(values)
    for axis in range(3):
        result += (xp.roll(values, 1, axis=axis) - 2.0 * values + xp.roll(values, -1, axis=axis)) / (spacing[axis] ** 2)
    return result


def _host(xp, value):
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value).copy()


def _scalar(value):
    return value.item() if hasattr(value, "item") else value


def _empty_receipt():
    return {
        "gpu_magnetic_ms": 0.0, "gpu_magnetic_cells": 0, "gpu_magnetic_memory_bytes": 0,
        "gpu_magnetic_grids": [], "gpu_magnetic_resident": False,
        "gpu_magnetic_reused_state": False,
    }


__all__ = ["GpuMagneticGridState", "solve_gpu_magnetic_grids"]
