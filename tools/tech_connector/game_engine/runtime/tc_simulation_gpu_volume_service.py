"""Provider-backed persistent sparse-volume combustion kernels."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import numpy as np

from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import compute_provider


@dataclass
class GpuSparseVolumeBuffers:
    provider_id: str
    keys: tuple[tuple[int, int, int], ...] = ()
    reallocations: int = 0

    def __post_init__(self) -> None:
        self.arrays: dict[str, Any] = {}

    def upload(self, volume: Any) -> None:
        provider = compute_provider(self.provider_id)
        xp = provider.array_module
        keys = tuple(sorted(volume.cells))
        if keys != self.keys:
            self.keys = keys
            count = len(keys)
            specs = {
                "density": ((count,), "float32"), "temperature": ((count,), "float32"),
                "fuel": ((count,), "float32"), "flame": ((count,), "float32"),
                "emission": ((count,), "float32"), "velocity": ((count, 3), "float32"),
                "neighbors": ((count, 6), "int64"), "pressure": ((count,), "float32"),
                "divergence": ((count,), "float32"),
            }
            self.arrays = {name: provider.allocate(shape, dtype) for name, (shape, dtype) in specs.items()}
            lookup = {key: index for index, key in enumerate(keys)}
            neighbors = np.full((count, 6), -1, dtype=np.int64)
            for index, key in enumerate(keys):
                for axis in range(3):
                    for side, offset in enumerate((-1, 1)):
                        neighbor = list(key); neighbor[axis] += offset
                        neighbors[index, axis * 2 + side] = lookup.get(tuple(neighbor), -1)
            self.arrays["neighbors"].handle[...] = xp.asarray(neighbors, dtype=xp.int64)
            self.arrays["pressure"].handle[...] = 0.0
            self.arrays["divergence"].handle[...] = 0.0
            self.reallocations += 1
        cells = [volume.cells[key] for key in keys]
        if not cells:
            return
        values = {
            "density": [cell.density for cell in cells], "temperature": [cell.temperature for cell in cells],
            "fuel": [cell.fuel for cell in cells], "flame": [cell.flame for cell in cells],
            "emission": [cell.emission for cell in cells], "velocity": [cell.velocity for cell in cells],
        }
        for name, value in values.items():
            self.arrays[name].handle[...] = xp.asarray(value, dtype=xp.float32)
            self.arrays[name].revision += 1

    def step(self, volume: Any, dt: float) -> None:
        xp = compute_provider(self.provider_id).array_module
        density = self.arrays["density"].handle
        temperature = self.arrays["temperature"].handle
        fuel = self.arrays["fuel"].handle
        flame = self.arrays["flame"].handle
        velocity = self.arrays["velocity"].handle
        density *= max(0.0, 1.0 - float(volume.dissipation) * dt)
        fuel[...] = xp.maximum(0.0, fuel - flame * dt)
        flame[...] = xp.clip(flame + fuel * dt - float(volume.cooling) * dt, 0.0, 1.0)
        temperature += (20.0 - temperature) * min(1.0, float(volume.cooling) * dt)
        velocity[:, 1] += float(volume.buoyancy) * xp.maximum(0.0, temperature - 20.0) * 0.001 * dt
        if int(getattr(volume, "pressure_iterations", 0)) > 0 and len(velocity):
            self._project_velocity(xp, volume)

    def _project_velocity(self, xp: Any, volume: Any) -> None:
        velocity = self.arrays["velocity"].handle
        neighbors = self.arrays["neighbors"].handle
        pressure = self.arrays["pressure"].handle
        divergence = self.arrays["divergence"].handle
        spacing = max(1.0e-6, float(volume.voxel_size))
        divergence[...] = 0.0
        for axis in range(3):
            negative = neighbors[:, axis * 2]
            positive = neighbors[:, axis * 2 + 1]
            negative_velocity = xp.where(negative >= 0, velocity[xp.maximum(negative, 0), axis], velocity[:, axis])
            positive_velocity = xp.where(positive >= 0, velocity[xp.maximum(positive, 0), axis], velocity[:, axis])
            divergence += (positive_velocity - negative_velocity) / (2.0 * spacing)
        pressure[...] = 0.0
        valid = neighbors >= 0
        neighbor_count = xp.sum(valid, axis=1)
        for _ in range(max(1, int(volume.pressure_iterations))):
            gathered = pressure[xp.maximum(neighbors, 0)] * valid
            pressure[...] = xp.where(
                neighbor_count > 0,
                (xp.sum(gathered, axis=1) - divergence * spacing * spacing)
                / xp.maximum(1, neighbor_count),
                0.0,
            )
        strength = max(0.0, min(1.0, float(volume.projection_strength)))
        for axis in range(3):
            negative = neighbors[:, axis * 2]
            positive = neighbors[:, axis * 2 + 1]
            negative_pressure = xp.where(negative >= 0, pressure[xp.maximum(negative, 0)], pressure)
            positive_pressure = xp.where(positive >= 0, pressure[xp.maximum(positive, 0)], pressure)
            velocity[:, axis] -= strength * (positive_pressure - negative_pressure) / (2.0 * spacing)

    def download(self, volume: Any) -> int:
        provider = compute_provider(self.provider_id)
        xp = provider.array_module
        values = {name: _host(xp, item.handle) for name, item in self.arrays.items()}
        retained = (
            (values["density"] > 1.0e-4) | (values["flame"] > 1.0e-4) | (values["emission"] > 1.0e-4)
        )
        next_cells: dict[tuple[int, int, int], Any] = {}
        for index in np.flatnonzero(retained).tolist():
            key = self.keys[index]
            cell = volume.cells[key]
            for name in ("density", "temperature", "fuel", "flame", "emission"):
                setattr(cell, name, float(values[name][index]))
            cell.velocity = tuple(float(value) for value in values["velocity"][index])
            next_cells[key] = cell
        volume.cells = next_cells
        return len(next_cells)

    @property
    def memory_bytes(self) -> int:
        return sum(item.nbytes for item in self.arrays.values())


def step_gpu_sparse_volumes(
    world: Any, dt: float, provider_id: str, *, resident_output: bool = False
) -> dict[str, Any]:
    states = getattr(world, "_gpu_sparse_volume_buffers", None)
    if not isinstance(states, dict):
        states = {}
        world._gpu_sparse_volume_buffers = states
    started = time.perf_counter()
    cells = memory = reallocations = 0
    reused_resident_state = bool(
        resident_output and getattr(world, "_gpu_volumes_authoritative", False)
        and set(states) == set(world.volumes)
    )
    for name, volume in world.volumes.items():
        state = states.get(name)
        if not isinstance(state, GpuSparseVolumeBuffers) or state.provider_id != provider_id:
            state = GpuSparseVolumeBuffers(provider_id)
            states[name] = state
        if not reused_resident_state:
            state.upload(volume)
        state.step(volume, max(0.0, float(dt)))
        cells += len(state.keys) if resident_output else state.download(volume)
        memory += state.memory_bytes
        reallocations += state.reallocations
    world._gpu_volumes_authoritative = bool(resident_output)
    return {
        "gpu_volume_ms": (time.perf_counter() - started) * 1000.0,
        "gpu_volume_cells": cells, "gpu_volume_memory_bytes": memory,
        "gpu_volume_buffer_reallocations": reallocations,
        "gpu_volume_resident": bool(resident_output),
        "gpu_volume_reused_resident_state": reused_resident_state,
        "gpu_volume_synchronization_points": 0 if reused_resident_state else (1 if resident_output else 2),
        "gpu_volume_projection_iterations": sum(
            max(0, int(getattr(volume, "pressure_iterations", 0))) for volume in world.volumes.values()
        ),
    }


def synchronize_gpu_sparse_volumes(world: Any) -> bool:
    states = getattr(world, "_gpu_sparse_volume_buffers", None)
    if not isinstance(states, dict) or not getattr(world, "_gpu_volumes_authoritative", False):
        return False
    for name, volume in world.volumes.items():
        state = states.get(name)
        if isinstance(state, GpuSparseVolumeBuffers):
            state.download(volume)
    world._gpu_volumes_authoritative = False
    return True


def _host(xp: Any, value: Any) -> np.ndarray:
    return np.asarray(xp.asnumpy(value) if hasattr(xp, "asnumpy") else value)


__all__ = [
    "GpuSparseVolumeBuffers", "step_gpu_sparse_volumes", "synchronize_gpu_sparse_volumes",
]
