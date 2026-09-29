"""Persistent vectorized sparse-volume state kernels."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import numpy as np


@dataclass
class NativeSparseVolumeBuffers:
    keys: tuple[tuple[int, int, int], ...] = ()
    reallocations: int = 0

    def __post_init__(self) -> None:
        self.density = np.empty(0, dtype=np.float64)
        self.temperature = np.empty(0, dtype=np.float64)
        self.fuel = np.empty(0, dtype=np.float64)
        self.flame = np.empty(0, dtype=np.float64)
        self.emission = np.empty(0, dtype=np.float64)
        self.velocity = np.empty((0, 3), dtype=np.float64)
        self.neighbors = np.empty((0, 6), dtype=np.int64)
        self.pressure = np.empty(0, dtype=np.float64)
        self.divergence = np.empty(0, dtype=np.float64)

    def upload(self, volume: Any) -> None:
        keys = tuple(sorted(volume.cells))
        if keys != self.keys:
            self.keys = keys
            count = len(keys)
            self.density = np.empty(count, dtype=np.float64)
            self.temperature = np.empty(count, dtype=np.float64)
            self.fuel = np.empty(count, dtype=np.float64)
            self.flame = np.empty(count, dtype=np.float64)
            self.emission = np.empty(count, dtype=np.float64)
            self.velocity = np.empty((count, 3), dtype=np.float64)
            lookup = {key: index for index, key in enumerate(keys)}
            self.neighbors = np.full((count, 6), -1, dtype=np.int64)
            for index, key in enumerate(keys):
                for axis in range(3):
                    for side, offset in enumerate((-1, 1)):
                        neighbor = list(key); neighbor[axis] += offset
                        self.neighbors[index, axis * 2 + side] = lookup.get(tuple(neighbor), -1)
            self.pressure = np.zeros(count, dtype=np.float64)
            self.divergence = np.zeros(count, dtype=np.float64)
            self.reallocations += 1
        cells = [volume.cells[key] for key in keys]
        if not cells:
            return
        self.density[:] = [cell.density for cell in cells]
        self.temperature[:] = [cell.temperature for cell in cells]
        self.fuel[:] = [cell.fuel for cell in cells]
        self.flame[:] = [cell.flame for cell in cells]
        self.emission[:] = [cell.emission for cell in cells]
        self.velocity[:] = [cell.velocity for cell in cells]

    def step(self, volume: Any, dt: float) -> None:
        self.density *= max(0.0, 1.0 - float(volume.dissipation) * dt)
        self.fuel = np.maximum(0.0, self.fuel - self.flame * dt)
        self.flame = np.clip(self.flame + self.fuel * dt - float(volume.cooling) * dt, 0.0, 1.0)
        self.temperature += (20.0 - self.temperature) * min(1.0, float(volume.cooling) * dt)
        self.velocity[:, 1] += (
            float(volume.buoyancy) * np.maximum(0.0, self.temperature - 20.0) * 0.001 * dt
        )
        if int(getattr(volume, "pressure_iterations", 0)) > 0 and len(self.velocity):
            self._project_velocity(volume)

    def _project_velocity(self, volume: Any) -> None:
        spacing = max(1.0e-6, float(volume.voxel_size))
        self.divergence.fill(0.0)
        for axis in range(3):
            negative = self.neighbors[:, axis * 2]
            positive = self.neighbors[:, axis * 2 + 1]
            negative_velocity = np.where(negative >= 0, self.velocity[np.maximum(negative, 0), axis], self.velocity[:, axis])
            positive_velocity = np.where(positive >= 0, self.velocity[np.maximum(positive, 0), axis], self.velocity[:, axis])
            self.divergence += (positive_velocity - negative_velocity) / (2.0 * spacing)
        self.pressure.fill(0.0)
        valid = self.neighbors >= 0
        neighbor_count = np.sum(valid, axis=1)
        for _ in range(max(1, int(volume.pressure_iterations))):
            gathered = self.pressure[np.maximum(self.neighbors, 0)] * valid
            self.pressure = np.where(
                neighbor_count > 0,
                (np.sum(gathered, axis=1) - self.divergence * spacing * spacing)
                / np.maximum(1, neighbor_count),
                0.0,
            )
        strength = max(0.0, min(1.0, float(volume.projection_strength)))
        for axis in range(3):
            negative = self.neighbors[:, axis * 2]
            positive = self.neighbors[:, axis * 2 + 1]
            negative_pressure = np.where(negative >= 0, self.pressure[np.maximum(negative, 0)], self.pressure)
            positive_pressure = np.where(positive >= 0, self.pressure[np.maximum(positive, 0)], self.pressure)
            self.velocity[:, axis] -= strength * (positive_pressure - negative_pressure) / (2.0 * spacing)

    def download(self, volume: Any) -> int:
        retained = (
            (self.density > 1.0e-4) | (self.flame > 1.0e-4) | (self.emission > 1.0e-4)
        )
        next_cells: dict[tuple[int, int, int], Any] = {}
        for index in np.flatnonzero(retained).tolist():
            key = self.keys[index]
            cell = volume.cells[key]
            cell.density = float(self.density[index])
            cell.temperature = float(self.temperature[index])
            cell.fuel = float(self.fuel[index])
            cell.flame = float(self.flame[index])
            cell.emission = float(self.emission[index])
            cell.velocity = tuple(float(value) for value in self.velocity[index])
            next_cells[key] = cell
        volume.cells = next_cells
        return len(next_cells)

    @property
    def memory_bytes(self) -> int:
        return sum(
            int(value.nbytes) for value in (
                self.density, self.temperature, self.fuel, self.flame, self.emission, self.velocity,
                self.neighbors, self.pressure, self.divergence,
            )
        )


def step_native_sparse_volumes(
    world: Any, dt: float, *, resident_output: bool = False
) -> dict[str, Any]:
    buffers = getattr(world, "_native_sparse_volume_buffers", None)
    if not isinstance(buffers, dict):
        buffers = {}
        world._native_sparse_volume_buffers = buffers
    started = time.perf_counter()
    active_cells = 0
    memory_bytes = 0
    reallocations = 0
    reused_resident_state = bool(resident_output and getattr(world, "_native_volumes_authoritative", False))
    for name, volume in world.volumes.items():
        state = buffers.get(name)
        if not isinstance(state, NativeSparseVolumeBuffers):
            state = NativeSparseVolumeBuffers()
            buffers[name] = state
        if not reused_resident_state:
            state.upload(volume)
        state.step(volume, max(0.0, float(dt)))
        if resident_output:
            active_cells += int(np.count_nonzero(
                (state.density > 1.0e-4) | (state.flame > 1.0e-4) | (state.emission > 1.0e-4)
            ))
        else:
            active_cells += state.download(volume)
        memory_bytes += state.memory_bytes
        reallocations += state.reallocations
    stale = set(buffers) - set(world.volumes)
    for name in stale:
        del buffers[name]
    world._native_volumes_authoritative = bool(resident_output)
    return {
        "volume_ms": (time.perf_counter() - started) * 1000.0,
        "volume_cells": active_cells,
        "volume_memory_bytes": memory_bytes,
        "volume_buffer_reallocations": reallocations,
        "volume_residency": "persistent_host_soa",
        "volume_resident_output": bool(resident_output),
        "volume_reused_resident_state": reused_resident_state,
        "volume_synchronization_points": 0 if reused_resident_state else (1 if resident_output else 2),
        "volume_projection_iterations": sum(
            max(0, int(getattr(volume, "pressure_iterations", 0))) for volume in world.volumes.values()
        ),
    }


def synchronize_native_sparse_volumes(world: Any) -> bool:
    states = getattr(world, "_native_sparse_volume_buffers", None)
    if not isinstance(states, dict) or not getattr(world, "_native_volumes_authoritative", False):
        return False
    for name, volume in world.volumes.items():
        state = states.get(name)
        if isinstance(state, NativeSparseVolumeBuffers):
            state.download(volume)
    world._native_volumes_authoritative = False
    return True


__all__ = [
    "NativeSparseVolumeBuffers", "step_native_sparse_volumes", "synchronize_native_sparse_volumes",
]
