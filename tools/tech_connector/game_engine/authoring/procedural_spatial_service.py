from __future__ import annotations

"""Portable spatial data, masks, and queries for TC procedural graphs."""

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Iterable

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralPayload,
    ProceduralPoint,
    replace_procedural_point,
)


Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class HeightField:
    width: int
    depth: int
    cell_size: float
    heights: tuple[float, ...]
    origin: Vec3 = (0.0, 0.0, 0.0)
    attributes: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width < 2 or self.depth < 2 or self.cell_size <= 0.0:
            raise ValueError("Heightfields require at least 2x2 samples and a positive cell size.")
        if len(self.heights) != self.width * self.depth:
            raise ValueError("Heightfield sample count does not match width and depth.")
        for name, values in self.attributes.items():
            if len(values) != len(self.heights):
                raise ValueError(f"Heightfield attribute {name} has an invalid sample count.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HeightField":
        return cls(
            width=int(data["width"]),
            depth=int(data["depth"]),
            cell_size=float(data["cell_size"]),
            heights=tuple(float(value) for value in data["heights"]),
            origin=tuple(float(value) for value in data.get("origin", (0, 0, 0)))[:3],
            attributes={
                str(name): tuple(float(value) for value in values)
                for name, values in (data.get("attributes") or {}).items()
            },
        )

    def _sample_values(self, values: tuple[float, ...], x: float, z: float) -> float:
        local_x = (x - self.origin[0]) / self.cell_size
        local_z = (z - self.origin[2]) / self.cell_size
        local_x = max(0.0, min(self.width - 1.0, local_x))
        local_z = max(0.0, min(self.depth - 1.0, local_z))
        x0, z0 = int(math.floor(local_x)), int(math.floor(local_z))
        x1, z1 = min(self.width - 1, x0 + 1), min(self.depth - 1, z0 + 1)
        tx, tz = local_x - x0, local_z - z0

        def at(ix: int, iz: int) -> float:
            return values[iz * self.width + ix]

        low = at(x0, z0) * (1.0 - tx) + at(x1, z0) * tx
        high = at(x0, z1) * (1.0 - tx) + at(x1, z1) * tx
        return low * (1.0 - tz) + high * tz

    def sample_height(self, x: float, z: float) -> float:
        return self.origin[1] + self._sample_values(self.heights, x, z)

    def sample_attribute(self, name: str, x: float, z: float, default: float = 0.0) -> float:
        values = self.attributes.get(str(name))
        return default if values is None else self._sample_values(values, x, z)

    def sample_normal(self, x: float, z: float) -> Vec3:
        step = self.cell_size
        dx = self.sample_height(x + step, z) - self.sample_height(x - step, z)
        dz = self.sample_height(x, z + step) - self.sample_height(x, z - step)
        normal = (-dx / (2.0 * step), 1.0, -dz / (2.0 * step))
        length = math.sqrt(sum(value * value for value in normal)) or 1.0
        return tuple(value / length for value in normal)

    def sample_slope_degrees(self, x: float, z: float) -> float:
        normal = self.sample_normal(x, z)
        return math.degrees(math.acos(max(-1.0, min(1.0, normal[1]))))


@dataclass(frozen=True)
class PolygonMask2D:
    polygons: tuple[tuple[Vec2, ...], ...]
    operation: str = "union"

    def __post_init__(self) -> None:
        if self.operation not in {"union", "intersection", "difference"}:
            raise ValueError(f"Unsupported polygon mask operation: {self.operation}")
        if any(len(polygon) < 3 for polygon in self.polygons):
            raise ValueError("Each polygon mask requires at least three points.")

    @staticmethod
    def _contains(polygon: tuple[Vec2, ...], point: Vec2) -> bool:
        x, y = point
        inside = False
        previous = polygon[-1]
        for current in polygon:
            x1, y1 = previous
            x2, y2 = current
            intersects = (y1 > y) != (y2 > y)
            if intersects:
                crossing = (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1
                if x < crossing:
                    inside = not inside
            previous = current
        return inside

    def contains(self, x: float, z: float) -> bool:
        states = [self._contains(polygon, (x, z)) for polygon in self.polygons]
        if not states:
            return False
        if self.operation == "intersection":
            return all(states)
        if self.operation == "difference":
            return states[0] and not any(states[1:])
        return any(states)


def project_points_to_heightfield(
    payload: ProceduralPayload,
    heightfield: HeightField,
    *,
    offset: float = 0.0,
) -> ProceduralPayload:
    points: list[ProceduralPoint] = []
    for point in payload.points:
        x, _y, z = point.position
        normal = heightfield.sample_normal(x, z)
        slope = heightfield.sample_slope_degrees(x, z)
        points.append(
            replace_procedural_point(
                point,
                position=(x, heightfield.sample_height(x, z) + offset, z),
                attributes={**point.attributes, "surface_normal": normal, "slope_degrees": slope},
                steepness=slope / 90.0,
            )
        )
    return ProceduralPayload(points=points, instances=list(payload.instances), metadata=dict(payload.metadata))


def filter_points_by_slope(
    payload: ProceduralPayload,
    heightfield: HeightField,
    *,
    minimum: float = 0.0,
    maximum: float = 90.0,
) -> ProceduralPayload:
    return ProceduralPayload(
        points=[
            point
            for point in payload.points
            if minimum <= heightfield.sample_slope_degrees(point.position[0], point.position[2]) <= maximum
        ],
        metadata=dict(payload.metadata),
    )


def filter_points_by_heightfield_mask(
    payload: ProceduralPayload,
    heightfield: HeightField,
    attribute: str,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> ProceduralPayload:
    return ProceduralPayload(
        points=[
            point
            for point in payload.points
            if minimum <= heightfield.sample_attribute(attribute, point.position[0], point.position[2]) <= maximum
        ],
        metadata=dict(payload.metadata),
    )


def filter_points_by_polygon(payload: ProceduralPayload, mask: PolygonMask2D) -> ProceduralPayload:
    return ProceduralPayload(
        points=[point for point in payload.points if mask.contains(point.position[0], point.position[2])],
        metadata=dict(payload.metadata),
    )


def annotate_point_neighborhoods(payload: ProceduralPayload, radius: float) -> ProceduralPayload:
    """Add neighbor count and nearest distance using a deterministic spatial hash."""
    radius = float(radius)
    if radius <= 0.0:
        raise ValueError("Neighborhood radius must be positive.")
    cells: dict[tuple[int, int, int], list[ProceduralPoint]] = {}
    for point in payload.points:
        cell = tuple(math.floor(value / radius) for value in point.position)
        cells.setdefault(cell, []).append(point)
    points: list[ProceduralPoint] = []
    for point in payload.points:
        cell = tuple(math.floor(value / radius) for value in point.position)
        neighbors: list[float] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in cells.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                        if candidate.point_id == point.point_id:
                            continue
                        distance = math.dist(point.position, candidate.position)
                        if distance <= radius:
                            neighbors.append(distance)
        points.append(
            replace_procedural_point(
                point,
                attributes={
                    **point.attributes,
                    "neighbor_count": len(neighbors),
                    "nearest_distance": min(neighbors) if neighbors else math.inf,
                },
            )
        )
    return ProceduralPayload(points=points, metadata=dict(payload.metadata))


def create_heightfield(
    rows: Iterable[Iterable[float]],
    *,
    cell_size: float = 1.0,
    origin: Vec3 = (0.0, 0.0, 0.0),
    attributes: dict[str, Iterable[Iterable[float]]] | None = None,
) -> HeightField:
    rows = [tuple(float(value) for value in row) for row in rows]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("Heightfield rows must form a non-empty rectangle.")
    width, depth = len(rows[0]), len(rows)
    flattened_attributes: dict[str, tuple[float, ...]] = {}
    for name, attribute_rows in (attributes or {}).items():
        values = [tuple(float(value) for value in row) for row in attribute_rows]
        if len(values) != depth or any(len(row) != width for row in values):
            raise ValueError(f"Heightfield attribute {name} dimensions do not match heights.")
        flattened_attributes[str(name)] = tuple(value for row in values for value in row)
    return HeightField(
        width=width,
        depth=depth,
        cell_size=float(cell_size),
        heights=tuple(value for row in rows for value in row),
        origin=origin,
        attributes=flattened_attributes,
    )
