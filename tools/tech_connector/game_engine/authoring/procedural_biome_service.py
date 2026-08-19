from __future__ import annotations

"""Deterministic terrain synthesis, erosion, and ecological biome placement."""

from dataclasses import asdict, dataclass, field
import hashlib
import math
from typing import Any, Iterable

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralInstance,
    ProceduralPayload,
    ProceduralPoint,
)
from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField


def _random(*parts: Any) -> float:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def _smooth(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def _value_noise(x: float, z: float, seed: int) -> float:
    x0, z0 = math.floor(x), math.floor(z)
    tx, tz = _smooth(x - x0), _smooth(z - z0)

    def lattice(ix: int, iz: int) -> float:
        return _random(seed, ix, iz) * 2.0 - 1.0

    low = lattice(x0, z0) * (1.0 - tx) + lattice(x0 + 1, z0) * tx
    high = lattice(x0, z0 + 1) * (1.0 - tx) + lattice(x0 + 1, z0 + 1) * tx
    return low * (1.0 - tz) + high * tz


def generate_noise_heightfield(
    width: int,
    depth: int,
    *,
    cell_size: float = 1.0,
    seed: int = 0,
    amplitude: float = 10.0,
    frequency: float = 0.04,
    octaves: int = 5,
    lacunarity: float = 2.0,
    gain: float = 0.5,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> HeightField:
    if width < 2 or depth < 2:
        raise ValueError("Procedural terrain requires at least a 2x2 heightfield.")
    if octaves < 1 or frequency <= 0.0 or lacunarity <= 0.0:
        raise ValueError("Terrain noise requires positive frequency, lacunarity, and octaves.")
    heights: list[float] = []
    moisture: list[float] = []
    temperature: list[float] = []
    for z in range(depth):
        for x in range(width):
            value = 0.0
            weight = 1.0
            normalization = 0.0
            octave_frequency = frequency
            for octave in range(octaves):
                value += _value_noise(x * octave_frequency, z * octave_frequency, seed + octave * 7919) * weight
                normalization += weight
                weight *= gain
                octave_frequency *= lacunarity
            normalized = value / max(1e-8, normalization)
            heights.append(normalized * amplitude)
            moisture.append((_value_noise(x * frequency * 0.55, z * frequency * 0.55, seed + 104729) + 1.0) * 0.5)
            latitude = abs((z / max(1, depth - 1)) * 2.0 - 1.0)
            temperature_noise = _value_noise(x * frequency * 0.3, z * frequency * 0.3, seed + 130363) * 0.15
            temperature.append(max(0.0, min(1.0, 1.0 - latitude + temperature_noise)))
    return HeightField(
        width=width,
        depth=depth,
        cell_size=float(cell_size),
        heights=tuple(heights),
        origin=origin,
        attributes={"moisture": tuple(moisture), "temperature": tuple(temperature)},
    )


def thermal_erode_heightfield(
    heightfield: HeightField,
    *,
    iterations: int = 8,
    talus: float = 0.6,
    strength: float = 0.35,
) -> HeightField:
    """Apply deterministic mass-preserving thermal erosion to terrain heights."""
    heights = list(heightfield.heights)
    width, depth = heightfield.width, heightfield.depth
    for _iteration in range(max(0, int(iterations))):
        delta = [0.0] * len(heights)
        for z in range(depth):
            for x in range(width):
                index = z * width + x
                candidates: list[tuple[float, int]] = []
                for dx, dz in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, nz = x + dx, z + dz
                    if 0 <= nx < width and 0 <= nz < depth:
                        other = nz * width + nx
                        difference = heights[index] - heights[other]
                        if difference > talus:
                            candidates.append((difference, other))
                if not candidates:
                    continue
                difference, destination = max(candidates, key=lambda row: (row[0], -row[1]))
                amount = min((difference - talus) * max(0.0, min(1.0, strength)) * 0.5, difference * 0.5)
                delta[index] -= amount
                delta[destination] += amount
        heights = [value + change for value, change in zip(heights, delta)]
    return HeightField(
        width=width,
        depth=depth,
        cell_size=heightfield.cell_size,
        heights=tuple(heights),
        origin=heightfield.origin,
        attributes=dict(heightfield.attributes),
    )


def hydraulic_erode_heightfield(
    heightfield: HeightField,
    *,
    iterations: int = 32,
    rainfall: float = 0.02,
    evaporation: float = 0.08,
    flow_rate: float = 0.55,
    sediment_capacity: float = 1.5,
    erosion_rate: float = 0.12,
    deposition_rate: float = 0.18,
    river_threshold: float = 0.35,
) -> HeightField:
    """Erode terrain with deterministic water and preserve reusable flow fields."""
    width, depth = heightfield.width, heightfield.depth
    heights = list(heightfield.heights)
    water = [0.0] * len(heights)
    sediment = [0.0] * len(heights)
    accumulated_flow = [0.0] * len(heights)
    direction_x = [0.0] * len(heights)
    direction_z = [0.0] * len(heights)
    rain_amount = max(0.0, float(rainfall))
    flow_amount = max(0.0, min(1.0, float(flow_rate)))
    evaporate = max(0.0, min(1.0, float(evaporation)))
    capacity_scale = max(0.0, float(sediment_capacity))
    erode_amount = max(0.0, min(1.0, float(erosion_rate)))
    deposit_amount = max(0.0, min(1.0, float(deposition_rate)))
    neighbors = ((-1, 0), (1, 0), (0, -1), (0, 1))

    for _iteration in range(max(0, int(iterations))):
        water = [value + rain_amount for value in water]
        water_delta = [0.0] * len(water)
        sediment_delta = [0.0] * len(sediment)
        outgoing = [0.0] * len(water)
        local_slope = [0.0] * len(water)
        for z in range(depth):
            for x in range(width):
                index = z * width + x
                head = heights[index] + water[index]
                lower: list[tuple[int, int, int, float]] = []
                for dx, dz in neighbors:
                    nx, nz = x + dx, z + dz
                    if 0 <= nx < width and 0 <= nz < depth:
                        other = nz * width + nx
                        difference = head - (heights[other] + water[other])
                        if difference > 1.0e-12:
                            lower.append((other, dx, dz, difference))
                total_drop = sum(row[3] for row in lower)
                if total_drop <= 0.0 or water[index] <= 0.0:
                    continue
                available = water[index] * flow_amount
                sediment_ratio = sediment[index] / max(1.0e-12, water[index])
                for other, dx, dz, difference in lower:
                    transfer = available * difference / total_drop
                    carried = min(sediment[index] + sediment_delta[index], transfer * sediment_ratio)
                    water_delta[index] -= transfer
                    water_delta[other] += transfer
                    sediment_delta[index] -= carried
                    sediment_delta[other] += carried
                    outgoing[index] += transfer
                    accumulated_flow[index] += transfer
                    direction_x[index] += transfer * dx
                    direction_z[index] += transfer * dz
                    local_slope[index] = max(local_slope[index], difference / max(1.0e-9, heightfield.cell_size))
        water = [max(0.0, value + change) for value, change in zip(water, water_delta)]
        sediment = [max(0.0, value + change) for value, change in zip(sediment, sediment_delta)]

        for index in range(len(heights)):
            capacity = outgoing[index] * local_slope[index] * capacity_scale
            if sediment[index] > capacity:
                amount = min(sediment[index], (sediment[index] - capacity) * deposit_amount)
                sediment[index] -= amount
                heights[index] += amount
            else:
                amount = min((capacity - sediment[index]) * erode_amount, max(0.0, local_slope[index]) * 0.25)
                heights[index] -= amount
                sediment[index] += amount
        water = [value * (1.0 - evaporate) for value in water]

    maximum_flow = max(accumulated_flow, default=0.0)
    normalized_flow = [value / maximum_flow if maximum_flow > 1.0e-12 else 0.0 for value in accumulated_flow]
    maximum_water = max(water, default=0.0)
    wetness = [value / maximum_water if maximum_water > 1.0e-12 else 0.0 for value in water]
    threshold = max(0.0, min(1.0, float(river_threshold)))
    river_mask = [max(0.0, min(1.0, (value - threshold) / max(1.0e-9, 1.0 - threshold))) for value in normalized_flow]
    normalized_direction_x: list[float] = []
    normalized_direction_z: list[float] = []
    for dx, dz in zip(direction_x, direction_z):
        length = math.hypot(dx, dz)
        normalized_direction_x.append(dx / length if length > 1.0e-12 else 0.0)
        normalized_direction_z.append(dz / length if length > 1.0e-12 else 0.0)
    attributes = dict(heightfield.attributes)
    attributes.update({
        "water": tuple(water),
        "water_flow": tuple(normalized_flow),
        "flow_direction_x": tuple(normalized_direction_x),
        "flow_direction_z": tuple(normalized_direction_z),
        "sediment": tuple(sediment),
        "wetness": tuple(wetness),
        "river_mask": tuple(river_mask),
    })
    return HeightField(
        width=width,
        depth=depth,
        cell_size=heightfield.cell_size,
        heights=tuple(heights),
        origin=heightfield.origin,
        attributes=attributes,
    )


@dataclass(frozen=True)
class BiomeSpecies:
    asset: str
    weight: float = 1.0
    minimum_elevation: float = -math.inf
    maximum_elevation: float = math.inf
    minimum_slope: float = 0.0
    maximum_slope: float = 90.0
    minimum_moisture: float = 0.0
    maximum_moisture: float = 1.0
    minimum_temperature: float = 0.0
    maximum_temperature: float = 1.0
    minimum_spacing: float = 0.0
    scale_range: tuple[float, float] = (1.0, 1.0)
    generation_grid: float = 64.0
    asset_extent: float = 1.0
    tags: tuple[str, ...] = ()

    def accepts(self, *, elevation: float, slope: float, moisture: float, temperature: float) -> bool:
        return (
            self.weight > 0.0
            and self.minimum_elevation <= elevation <= self.maximum_elevation
            and self.minimum_slope <= slope <= self.maximum_slope
            and self.minimum_moisture <= moisture <= self.maximum_moisture
            and self.minimum_temperature <= temperature <= self.maximum_temperature
        )


@dataclass(frozen=True)
class BiomeDefinition:
    name: str
    species: tuple[BiomeSpecies, ...]
    samples_per_cell: int = 1
    density: float = 1.0
    seed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BiomeDefinition":
        return cls(
            name=str(data.get("name") or "Biome"),
            species=tuple(BiomeSpecies(**row) for row in data.get("species") or ()),
            samples_per_cell=int(data.get("samples_per_cell", 1)),
            density=float(data.get("density", 1.0)),
            seed=int(data.get("seed", 0)),
            metadata=dict(data.get("metadata") or {}),
        )


def scatter_biome(heightfield: HeightField, biome: BiomeDefinition) -> ProceduralPayload:
    accepted_positions: dict[str, dict[tuple[int, int], list[tuple[float, float]]]] = {}
    points: list[ProceduralPoint] = []
    instances: list[ProceduralInstance] = []
    density = max(0.0, min(1.0, biome.density))
    for z in range(heightfield.depth - 1):
        for x in range(heightfield.width - 1):
            for sample in range(max(0, biome.samples_per_cell)):
                candidate_id = f"{biome.name}:{x}:{z}:{sample}"
                if _random(biome.seed, candidate_id, "density") > density:
                    continue
                px = heightfield.origin[0] + (x + _random(biome.seed, candidate_id, "x")) * heightfield.cell_size
                pz = heightfield.origin[2] + (z + _random(biome.seed, candidate_id, "z")) * heightfield.cell_size
                elevation = heightfield.sample_height(px, pz)
                slope = heightfield.sample_slope_degrees(px, pz)
                moisture = heightfield.sample_attribute("moisture", px, pz, 0.5)
                temperature = heightfield.sample_attribute("temperature", px, pz, 0.5)
                eligible = [
                    species
                    for species in biome.species
                    if species.accepts(
                        elevation=elevation,
                        slope=slope,
                        moisture=moisture,
                        temperature=temperature,
                    )
                ]
                total = sum(species.weight for species in eligible)
                if total <= 0.0:
                    continue
                pick = _random(biome.seed, candidate_id, "species") * total
                selected = eligible[-1]
                cursor = 0.0
                for species in eligible:
                    cursor += species.weight
                    if pick <= cursor:
                        selected = species
                        break
                spacing = max(0.0, selected.minimum_spacing)
                species_cells = accepted_positions.setdefault(selected.asset, {})
                if spacing > 0.0:
                    cell = (math.floor(px / spacing), math.floor(pz / spacing))
                    nearby = (
                        position
                        for dx in (-1, 0, 1)
                        for dz in (-1, 0, 1)
                        for position in species_cells.get((cell[0] + dx, cell[1] + dz), ())
                    )
                    if any(math.dist((px, pz), position) < spacing for position in nearby):
                        continue
                else:
                    cell = (0, 0)
                species_cells.setdefault(cell, []).append((px, pz))
                scale_amount = selected.scale_range[0] + (
                    selected.scale_range[1] - selected.scale_range[0]
                ) * _random(biome.seed, candidate_id, "scale")
                rotation = (0.0, _random(biome.seed, candidate_id, "rotation") * 360.0, 0.0)
                attributes = {
                    "asset": selected.asset,
                    "biome": biome.name,
                    "elevation": elevation,
                    "slope_degrees": slope,
                    "moisture": moisture,
                    "temperature": temperature,
                    "generation_grid": selected.generation_grid,
                    "asset_extent": selected.asset_extent,
                    "tags": selected.tags,
                }
                point = ProceduralPoint(
                    point_id=candidate_id,
                    position=(px, elevation, pz),
                    rotation=rotation,
                    scale=(scale_amount, scale_amount, scale_amount),
                    attributes=attributes,
                    density=density,
                    steepness=slope / 90.0,
                    seed=biome.seed,
                )
                points.append(point)
                instances.append(
                    ProceduralInstance(
                        instance_id=f"biome:{candidate_id}",
                        asset=selected.asset,
                        position=point.position,
                        rotation=point.rotation,
                        scale=point.scale,
                        attributes=attributes,
                    )
                )
    return ProceduralPayload(
        points=points,
        instances=instances,
        metadata={
            "biome": biome.name,
            "seed": biome.seed,
            "species_counts": {
                species.asset: sum(1 for instance in instances if instance.asset == species.asset)
                for species in biome.species
            },
        },
    )
