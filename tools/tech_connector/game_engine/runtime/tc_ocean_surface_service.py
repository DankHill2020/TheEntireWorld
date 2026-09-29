from __future__ import annotations

"""Deterministic realtime ocean surface with bounded Gerstner waves and wakes."""

from dataclasses import asdict, dataclass, field
from functools import lru_cache
import math
import random
from typing import Any

import numpy as np


Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class OceanWave:
    direction: tuple[float, float]
    wavelength: float
    amplitude: float
    steepness: float
    phase: float


@dataclass
class OceanWake:
    wake_id: int
    position: tuple[float, float]
    velocity: tuple[float, float]
    radius: float
    strength: float
    lifetime: float
    age: float = 0.0


@dataclass(frozen=True)
class OceanSample:
    position: Vec3
    normal: Vec3
    foam: float
    velocity: Vec3

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass
class OceanSurface:
    waves: list[OceanWave]
    wind_speed: float = 12.0
    choppiness: float = 1.0
    fetch: float = 10_000.0
    foam_threshold: float = 0.55
    gravity: float = 9.80665
    time_seconds: float = 0.0
    wakes: list[OceanWake] = field(default_factory=list)
    next_wake_id: int = 1
    maximum_wakes: int = 64

    def __post_init__(self) -> None:
        if not self.waves or len(self.waves) > 32: raise ValueError("Ocean surfaces require 1-32 wave components.")
        if self.wind_speed < 0.0 or self.choppiness < 0.0 or self.fetch <= 0.0: raise ValueError("Ocean controls must be finite and non-negative, with positive fetch.")

    def step(self, dt: float) -> None:
        delta = float(dt)
        if not math.isfinite(delta) or delta < 0.0: raise ValueError("Ocean delta time must be finite and non-negative.")
        self.time_seconds += delta
        for wake in self.wakes: wake.age += delta
        self.wakes[:] = [wake for wake in self.wakes if wake.age < wake.lifetime]

    def add_wake(
        self, position: tuple[float, float], velocity: tuple[float, float], *,
        radius: float = 1.0, strength: float = 0.25, lifetime: float = 6.0,
    ) -> OceanWake:
        values = (float(radius), float(strength), float(lifetime), *map(float, position), *map(float, velocity))
        if not all(math.isfinite(value) for value in values) or radius <= 0.0 or lifetime <= 0.0: raise ValueError("Wake values must be finite; radius and lifetime must be positive.")
        wake = OceanWake(self.next_wake_id, tuple(map(float, position)), tuple(map(float, velocity)), float(radius), float(strength), float(lifetime))
        self.next_wake_id += 1; self.wakes.append(wake)
        if len(self.wakes) > max(1, int(self.maximum_wakes)): del self.wakes[:-int(self.maximum_wakes)]
        return wake

    def sample(self, x: float, z: float, time_seconds: float | None = None) -> OceanSample:
        x, z = float(x), float(z); current_time = self.time_seconds if time_seconds is None else float(time_seconds)
        displacement_x = displacement_z = height = slope_x = slope_z = vertical_velocity = 0.0
        crest = 0.0
        for wave in self.waves:
            k = math.tau / wave.wavelength; omega = math.sqrt(self.gravity * k)
            phase = k * (wave.direction[0] * x + wave.direction[1] * z) - omega * current_time + wave.phase
            sine, cosine = math.sin(phase), math.cos(phase); amplitude = wave.amplitude
            height += amplitude * sine; crest += max(0.0, sine) * amplitude
            lateral = wave.steepness * self.choppiness * amplitude * cosine
            displacement_x += wave.direction[0] * lateral; displacement_z += wave.direction[1] * lateral
            slope_x += amplitude * k * wave.direction[0] * cosine; slope_z += amplitude * k * wave.direction[1] * cosine
            vertical_velocity -= amplitude * omega * cosine
        wake_height, wake_slope_x, wake_slope_z, wake_velocity, wake_foam = self._wake_sample(x, z)
        height += wake_height; slope_x += wake_slope_x; slope_z += wake_slope_z; vertical_velocity += wake_velocity
        normal = _normalize((-slope_x, 1.0, -slope_z))
        steepness = math.hypot(slope_x, slope_z)
        foam = min(1.0, max(0.0, (steepness - self.foam_threshold) * 2.5 + crest * 0.08 + wake_foam))
        return OceanSample((x + displacement_x, height, z + displacement_z), normal, foam, (0.0, vertical_velocity, 0.0))

    def mesh_patch(self, *, center: tuple[float, float] = (0.0, 0.0), size: float = 20.0, rows: int = 32, columns: int = 32) -> dict[str, Any]:
        rows, columns = int(rows), int(columns)
        if not 2 <= rows <= 512 or not 2 <= columns <= 512: raise ValueError("Ocean patch rows and columns must be between 2 and 512.")
        extent = max(0.01, float(size))
        grid_x, grid_z = np.meshgrid(
            np.linspace(float(center[0]) - extent * 0.5, float(center[0]) + extent * 0.5, columns),
            np.linspace(float(center[1]) - extent * 0.5, float(center[1]) + extent * 0.5, rows),
        )
        x = grid_x.reshape(-1); z = grid_z.reshape(-1)
        displacement_x = np.zeros_like(x); displacement_z = np.zeros_like(z)
        height = np.zeros_like(x); slope_x = np.zeros_like(x); slope_z = np.zeros_like(z)
        vertical_velocity = np.zeros_like(x); crest = np.zeros_like(x)
        current_time = float(self.time_seconds)
        for wave in self.waves:
            k = math.tau / float(wave.wavelength); omega = math.sqrt(float(self.gravity) * k)
            phase = k * (float(wave.direction[0]) * x + float(wave.direction[1]) * z) - omega * current_time + float(wave.phase)
            sine = np.sin(phase); cosine = np.cos(phase); amplitude = float(wave.amplitude)
            height += amplitude * sine; crest += np.maximum(0.0, sine) * amplitude
            lateral = float(wave.steepness) * float(self.choppiness) * amplitude * cosine
            displacement_x += float(wave.direction[0]) * lateral
            displacement_z += float(wave.direction[1]) * lateral
            slope_x += amplitude * k * float(wave.direction[0]) * cosine
            slope_z += amplitude * k * float(wave.direction[1]) * cosine
            vertical_velocity -= amplitude * omega * cosine
        wake_foam = np.zeros_like(x)
        for wake in self.wakes:
            decay = max(0.0, 1.0 - float(wake.age) / float(wake.lifetime)) ** 2
            dx = x - (float(wake.position[0]) + float(wake.velocity[0]) * float(wake.age))
            dz = z - (float(wake.position[1]) + float(wake.velocity[1]) * float(wake.age))
            distance = np.sqrt(dx * dx + dz * dz); radius = max(1.0e-6, float(wake.radius))
            envelope = np.exp(-np.square((distance - float(wake.age) * 2.2) / radius))
            phase = distance * math.tau / radius - float(wake.age) * 7.0
            contribution = float(wake.strength) * decay * envelope * np.sin(phase)
            height += contribution
            derivative = float(wake.strength) * decay * envelope * (math.tau / radius) * np.cos(phase)
            inverse_distance = np.divide(1.0, distance, out=np.zeros_like(distance), where=distance > 1.0e-8)
            slope_x += derivative * dx * inverse_distance; slope_z += derivative * dz * inverse_distance
            vertical_velocity += -7.0 * float(wake.strength) * decay * envelope * np.cos(phase)
            wake_foam += np.minimum(1.0, np.abs(contribution) * 3.0)
        inverse_normal_length = 1.0 / np.maximum(1.0e-12, np.sqrt(slope_x * slope_x + 1.0 + slope_z * slope_z))
        vertices_array = np.column_stack((x + displacement_x, height, z + displacement_z))
        normals_array = np.column_stack((-slope_x * inverse_normal_length, inverse_normal_length, -slope_z * inverse_normal_length))
        foam_array = np.clip((np.sqrt(slope_x * slope_x + slope_z * slope_z) - float(self.foam_threshold)) * 2.5 + crest * 0.08 + wake_foam, 0.0, 1.0)
        vertices = [tuple(map(float, value)) for value in vertices_array.tolist()]
        normals = [tuple(map(float, value)) for value in normals_array.tolist()]
        foam = [float(value) for value in foam_array.tolist()]
        triangles = list(_patch_triangles(rows, columns))
        return {"schema": "tech_connector.ocean_patch.v1", "rows": rows, "columns": columns,
                "vertices": vertices, "normals": normals, "foam": foam, "triangles": triangles}

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "tech_connector.ocean_surface.v1", "wind_speed": self.wind_speed,
                "choppiness": self.choppiness, "fetch": self.fetch, "foam_threshold": self.foam_threshold,
                "time_seconds": self.time_seconds, "waves": [asdict(wave) for wave in self.waves],
                "wakes": [asdict(wake) for wake in self.wakes]}

    def _wake_sample(self, x: float, z: float) -> tuple[float, float, float, float, float]:
        height = slope_x = slope_z = velocity = foam = 0.0
        for wake in self.wakes:
            decay = max(0.0, 1.0 - wake.age / wake.lifetime) ** 2
            center_x = wake.position[0] + wake.velocity[0] * wake.age
            center_z = wake.position[1] + wake.velocity[1] * wake.age
            dx, dz = x - center_x, z - center_z; distance = math.hypot(dx, dz); radius = max(1.0e-6, wake.radius)
            envelope = math.exp(-((distance - wake.age * 2.2) / radius) ** 2)
            phase = distance * math.tau / radius - wake.age * 7.0
            contribution = wake.strength * decay * envelope * math.sin(phase); height += contribution
            if distance > 1.0e-8:
                derivative = wake.strength * decay * envelope * (math.tau / radius) * math.cos(phase)
                slope_x += derivative * dx / distance; slope_z += derivative * dz / distance
            velocity += -7.0 * wake.strength * decay * envelope * math.cos(phase)
            foam += min(1.0, abs(contribution) * 3.0)
        return height, slope_x, slope_z, velocity, foam


def create_ocean_surface(preset: str = "open_ocean", *, seed: int = 1, wave_count: int = 12, **overrides: float) -> OceanSurface:
    profiles = {
        "calm": {"wind_speed": 4.0, "choppiness": 0.35, "fetch": 2_000.0, "foam_threshold": 0.8},
        "open_ocean": {"wind_speed": 12.0, "choppiness": 1.0, "fetch": 10_000.0, "foam_threshold": 0.55},
        "storm": {"wind_speed": 28.0, "choppiness": 1.8, "fetch": 80_000.0, "foam_threshold": 0.35},
    }
    values = dict(profiles.get(str(preset).casefold(), profiles["open_ocean"])); values.update({key: float(value) for key, value in overrides.items()})
    count = max(1, min(32, int(wave_count))); rng = random.Random(int(seed)); waves: list[OceanWave] = []
    dominant = rng.uniform(-math.pi, math.pi); wind = max(0.1, values["wind_speed"]); fetch = max(1.0, values["fetch"])
    dominant_length = max(0.5, min(180.0, wind * wind / 9.80665 * (0.65 + min(1.0, fetch / 100_000.0))))
    for index in range(count):
        octave = index / max(1, count - 1); wavelength = dominant_length * (0.18 + 1.82 * octave * octave)
        angle = dominant + rng.gauss(0.0, 0.22 + 0.35 * (1.0 - octave)); direction = (math.cos(angle), math.sin(angle))
        amplitude = min(wavelength * 0.07, (wind / 12.0) * (0.015 + 0.12 * octave * octave))
        steepness = min(0.92, 0.15 + values["choppiness"] * 0.32) / count
        waves.append(OceanWave(direction, wavelength, amplitude, steepness, rng.random() * math.tau))
    return OceanSurface(waves, **values)


def _normalize(value: Vec3) -> Vec3:
    length = math.sqrt(sum(component * component for component in value))
    return tuple(component / max(1.0e-12, length) for component in value)  # type: ignore[return-value]


@lru_cache(maxsize=64)
def _patch_triangles(rows: int, columns: int) -> tuple[tuple[int, int, int], ...]:
    triangles: list[tuple[int, int, int]] = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            triangles.extend((
                (first, first + columns, first + 1),
                (first + 1, first + columns, first + columns + 1),
            ))
    return tuple(triangles)


__all__ = ["OceanSample", "OceanSurface", "OceanWake", "OceanWave", "create_ocean_surface"]
