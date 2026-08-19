"""Material-aware terrain impressions and projectile penetration receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Iterable


Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class SurfaceMaterial:
    name: str
    hardness: float
    compaction: float
    recovery_rate: float
    slump_rate: float
    penetration_resistance: float
    fracture_energy: float
    moisture: float = 0.0
    conductivity: float = 0.0


SURFACE_MATERIALS = {
    "snow": SurfaceMaterial("Snow", 0.08, 0.9, 0.018, 0.06, 0.12, 0.4, conductivity=0.08),
    "mud": SurfaceMaterial("Mud", 0.12, 0.75, 0.004, 0.2, 0.22, 0.7, 0.8, 0.58),
    "sand": SurfaceMaterial("Sand", 0.16, 0.65, 0.0, 0.32, 0.3, 0.9),
    "soil": SurfaceMaterial("Soil", 0.3, 0.45, 0.001, 0.08, 0.7, 1.6, 0.25, 0.2),
    "wood": SurfaceMaterial("Wood", 0.68, 0.1, 0.0, 0.0, 2.5, 4.0, conductivity=0.04),
    "glass": SurfaceMaterial("Glass", 0.86, 0.0, 0.0, 0.0, 1.2, 1.1, conductivity=0.01),
    "metal": SurfaceMaterial("Metal", 0.95, 0.04, 0.0, 0.0, 7.5, 12.0, conductivity=1.0),
}


@dataclass
class SurfaceMark:
    mark_id: int
    kind: str
    position: Vec3
    radius: float
    depth: float
    energy: float = 0.0
    penetrated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeformableSurface:
    material: str = "snow"
    origin: Vec3 = (-2.0, 0.0, -2.0)
    cell_size: float = 0.08
    columns: int = 50
    rows: int = 50
    base_height: float = 0.0
    heights: list[float] = field(default_factory=list)
    compaction: list[float] = field(default_factory=list)
    marks: list[SurfaceMark] = field(default_factory=list)
    next_mark_id: int = 1

    def __post_init__(self) -> None:
        count = max(1, int(self.columns)) * max(1, int(self.rows))
        if not self.heights:
            self.heights = [float(self.base_height)] * count
        if not self.compaction:
            self.compaction = [0.0] * count
        if len(self.heights) != count or len(self.compaction) != count:
            raise ValueError("Deformable surface grids must match rows * columns.")

    @property
    def material_properties(self) -> SurfaceMaterial:
        return SURFACE_MATERIALS.get(self.material, SURFACE_MATERIALS["soil"])

    def apply_footprint(
        self,
        position: Vec3,
        *,
        size: tuple[float, float] = (0.28, 0.12),
        depth: float = 0.045,
        rotation: float = 0.0,
        tread: Iterable[float] | None = None,
    ) -> SurfaceMark:
        major, minor = max(0.01, float(size[0])), max(0.01, float(size[1]))
        cos_angle, sin_angle = math.cos(rotation), math.sin(rotation)

        def shape(x: float, z: float) -> float:
            dx, dz = x - position[0], z - position[2]
            local_x = dx * cos_angle + dz * sin_angle
            local_z = -dx * sin_angle + dz * cos_angle
            normalized = (local_x / major) ** 2 + (local_z / minor) ** 2
            if normalized > 1.0:
                return 0.0
            tread_values = tuple(float(value) for value in (tread or ()))
            tread_scale = 1.0
            if tread_values:
                stripe = min(len(tread_values) - 1, int(((local_x / major) * 0.5 + 0.5) * len(tread_values)))
                tread_scale = max(0.0, tread_values[stripe])
            return math.sqrt(max(0.0, 1.0 - normalized)) * tread_scale

        self._depress(shape, float(depth))
        return self._mark("footprint", position, max(major, minor), depth, metadata={"size": (major, minor), "rotation": rotation})

    def apply_contact(self, position: Vec3, *, radius: float, depth: float, kind: str = "contact") -> SurfaceMark:
        radius = max(0.001, float(radius))

        def shape(x: float, z: float) -> float:
            distance = math.hypot(x - position[0], z - position[2])
            return max(0.0, 1.0 - distance / radius) ** 1.5

        self._depress(shape, float(depth))
        return self._mark(kind, position, radius, depth)

    def apply_projectile(
        self,
        position: Vec3,
        direction: Vec3,
        *,
        energy: float,
        radius: float = 0.015,
        thickness: float = 0.1,
    ) -> SurfaceMark:
        material = self.material_properties
        normalized_energy = max(0.0, float(energy)) / max(1.0e-9, material.penetration_resistance * max(0.001, thickness))
        penetrated = normalized_energy >= 1.0
        depth = min(max(0.002, radius * 4.0), radius * (2.0 + normalized_energy))
        crater_radius = radius * (2.0 + min(8.0, math.sqrt(normalized_energy)))
        mark = self.apply_contact(position, radius=crater_radius, depth=depth, kind="penetration" if penetrated else "impact")
        mark.energy = float(energy)
        mark.penetrated = penetrated
        mark.metadata.update({"direction": tuple(direction), "thickness": thickness, "exit_wound_scale": 1.7 if penetrated else 0.0})
        return mark

    def step(self, dt: float) -> None:
        material = self.material_properties
        recovery = max(0.0, material.recovery_rate * float(dt))
        slump = max(0.0, material.slump_rate * float(dt))
        source = list(self.heights)
        for row in range(self.rows):
            for column in range(self.columns):
                index = row * self.columns + column
                height = source[index]
                if recovery > 0.0:
                    height += (self.base_height - height) * min(1.0, recovery * (1.0 - self.compaction[index] * 0.7))
                if slump > 0.0:
                    neighbors = []
                    for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        c, r = column + dc, row + dr
                        if 0 <= c < self.columns and 0 <= r < self.rows:
                            neighbors.append(source[r * self.columns + c])
                    if neighbors:
                        height += (sum(neighbors) / len(neighbors) - height) * min(0.25, slump)
                self.heights[index] = height

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.deformable_surface.v1",
            "material": self.material,
            "origin": self.origin,
            "cell_size": self.cell_size,
            "columns": self.columns,
            "rows": self.rows,
            "base_height": self.base_height,
            "heights": list(self.heights),
            "compaction": list(self.compaction),
            "marks": [asdict(mark) for mark in self.marks],
        }

    def _depress(self, shape, depth: float) -> None:
        material = self.material_properties
        for row in range(self.rows):
            z = self.origin[2] + row * self.cell_size
            for column in range(self.columns):
                x = self.origin[0] + column * self.cell_size
                influence = float(shape(x, z))
                if influence <= 0.0:
                    continue
                index = row * self.columns + column
                resistance = max(0.04, material.hardness + self.compaction[index] * 0.6)
                displacement = max(0.0, depth) * influence * (1.0 - resistance * 0.65)
                self.heights[index] -= displacement
                self.compaction[index] = min(1.0, self.compaction[index] + influence * material.compaction * 0.2)

    def _mark(
        self,
        kind: str,
        position: Vec3,
        radius: float,
        depth: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SurfaceMark:
        mark = SurfaceMark(self.next_mark_id, kind, tuple(position), float(radius), float(depth), metadata=dict(metadata or {}))
        self.next_mark_id += 1
        self.marks.append(mark)
        return mark
