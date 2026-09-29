"""Deterministic reference builders for terrain, navigation, lighting, and HLOD data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField

from .asset_database_service import AssetDatabase, DerivedArtifact
from .world_asset_service import WorldAssetService, build_terrain_preview


WORLD_BUILD_SCHEMA = "tech_connector.world_build.v1"


@dataclass(frozen=True)
class WorldBuildReceipt:
    asset_id: str
    build_kind: str
    artifact: DerivedArtifact
    statistics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "build_kind": self.build_kind,
                "artifact": asdict(self.artifact), "statistics": dict(self.statistics)}


class WorldBuildService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.world = WorldAssetService(self.project_root, database)

    def build(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> WorldBuildReceipt:
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown asset: {asset_id}")
        if record.asset_type == "tc.terrain":
            payload, statistics = self._terrain_mesh(asset_id, platform=platform, quality=quality)
            kind, extension = "terrain_geometry", ".tcterrain"
        elif record.asset_type == "tc.navigation_mesh":
            payload, statistics = self._navigation_mesh(asset_id, platform=platform, quality=quality)
            kind, extension = "navigation_tiles", ".tcnav"
        elif record.asset_type == "tc.lighting_scenario":
            payload, statistics = self._lighting(asset_id, platform=platform, quality=quality)
            kind, extension = "lighting_bake", ".tclight"
        elif record.asset_type == "tc.hlod_layer":
            payload, statistics = self._hlod(asset_id, platform=platform, quality=quality)
            kind, extension = "hlod_clusters", ".tchlod"
        elif record.asset_type == "tc.world_partition":
            payload, statistics = self._partition(asset_id, platform=platform, quality=quality)
            kind, extension = "streaming_cells", ".tcpartition"
        else:
            raise ValueError(f"{record.asset_type} does not have a generated world backend.")
        artifact = self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            metadata={"platform": platform, "quality": quality, **statistics}, extension=extension,
        )
        return WorldBuildReceipt(asset_id, kind, artifact, statistics)

    def build_many(self, asset_ids: Iterable[str], *, platform: str = "desktop", quality: str = "high") -> tuple[WorldBuildReceipt, ...]:
        return tuple(self.build(asset_id, platform=platform, quality=quality) for asset_id in dict.fromkeys(asset_ids))

    def _terrain_mesh(self, asset_id: str, *, platform: str, quality: str):
        values = self.world.properties(asset_id)
        cap = _resolution_cap(platform, quality)
        source = build_terrain_preview(values, maximum_resolution=cap)
        field = _heightfield(source)
        lod_count = max(1, int(dict(values.get("lod") or {}).get("levels", 1)))
        lods: list[dict[str, Any]] = []
        for level in range(lod_count):
            stride = 2 ** level
            x_indices = _sample_indices(field.width, stride); z_indices = _sample_indices(field.depth, stride)
            vertices = [[x * field.cell_size, field.heights[z * field.width + x], z * field.cell_size]
                        for z in z_indices for x in x_indices]
            columns = len(x_indices); indices: list[int] = []
            for z in range(len(z_indices) - 1):
                for x in range(columns - 1):
                    a = z * columns + x; b = a + 1; c = a + columns; d = c + 1
                    indices.extend((a, c, b, b, c, d))
            lods.append({"level": level, "stride": stride, "vertices": vertices, "indices": indices,
                         "triangle_count": len(indices) // 3})
            if len(x_indices) <= 2 and len(z_indices) <= 2:
                break
        collision_lod = max(0, min(len(lods) - 1, int(dict(values.get("collision") or {}).get("lod", 1))))
        payload = {"schema": WORLD_BUILD_SCHEMA, "kind": "terrain_geometry", "asset_id": asset_id,
                   "platform": platform, "quality": quality, "bounds": _terrain_bounds(field),
                   "lods": lods, "collision": {"lod": collision_lod, "vertices": lods[collision_lod]["vertices"],
                                                 "indices": lods[collision_lod]["indices"]}}
        stats = {"lod_count": len(lods), "lod0_vertices": len(lods[0]["vertices"]),
                 "lod0_triangles": lods[0]["triangle_count"], "collision_triangles": lods[collision_lod]["triangle_count"]}
        return payload, stats

    def _navigation_mesh(self, asset_id: str, *, platform: str, quality: str):
        values = self.world.properties(asset_id)
        terrain_ids = _terrain_ids(values, self.database)
        agents = [dict(row) for row in values.get("agents") or ()]
        tiles: list[dict[str, Any]] = []; polygon_count = 0
        tile_size = max(1.0, float(values.get("tile_size", 1024.0)))
        for terrain_id in terrain_ids:
            terrain = _heightfield(build_terrain_preview(self.world.properties(terrain_id), maximum_resolution=_resolution_cap(platform, quality)))
            for agent in agents:
                maximum_slope = float(agent.get("maximum_slope", 45.0))
                agent_name = str(agent.get("name") or "Agent")
                by_tile: dict[tuple[int, int], list[dict[str, Any]]] = {}
                for z in range(terrain.depth - 1):
                    for x in range(terrain.width - 1):
                        world_x, world_z = x * terrain.cell_size, z * terrain.cell_size
                        slope = terrain.sample_slope_degrees(world_x, world_z)
                        if slope > maximum_slope:
                            continue
                        heights = [terrain.heights[z * terrain.width + x], terrain.heights[z * terrain.width + x + 1],
                                   terrain.heights[(z + 1) * terrain.width + x + 1], terrain.heights[(z + 1) * terrain.width + x]]
                        polygon = {"vertices": [[world_x, heights[0], world_z], [world_x + terrain.cell_size, heights[1], world_z],
                                                 [world_x + terrain.cell_size, heights[2], world_z + terrain.cell_size],
                                                 [world_x, heights[3], world_z + terrain.cell_size]],
                                   "area": "Walkable", "cost": 1.0, "slope": slope}
                        by_tile.setdefault((int(world_x // tile_size), int(world_z // tile_size)), []).append(polygon)
                        polygon_count += 1
                for (tile_x, tile_z), polygons in sorted(by_tile.items()):
                    tiles.append({"id": f"{terrain_id}:{agent_name}:{tile_x}:{tile_z}", "terrain_asset_id": terrain_id,
                                  "agent": agent_name, "x": tile_x, "z": tile_z, "polygons": polygons})
        payload = {"schema": WORLD_BUILD_SCHEMA, "kind": "navigation_tiles", "asset_id": asset_id,
                   "platform": platform, "quality": quality, "tile_size": tile_size, "tiles": tiles,
                   "areas": list(values.get("areas") or ()), "off_mesh_links": list(values.get("off_mesh_links") or ())}
        return payload, {"tile_count": len(tiles), "polygon_count": polygon_count,
                         "agent_count": len(agents), "terrain_count": len(terrain_ids)}

    def _lighting(self, asset_id: str, *, platform: str, quality: str):
        values = self.world.properties(asset_id); terrain_ids = _terrain_ids(values, self.database)
        environment = dict(values.get("environment") or {}); intensity = max(0.0, float(environment.get("intensity", 1.0)))
        rotation = math.radians(float(environment.get("rotation", 0.0)))
        direction = (math.cos(rotation) * 0.45, 0.82, math.sin(rotation) * 0.45)
        lightmaps: list[dict[str, Any]] = []; sample_count = 0
        for terrain_id in terrain_ids:
            field = _heightfield(build_terrain_preview(self.world.properties(terrain_id), maximum_resolution=min(257, _resolution_cap(platform, quality))))
            irradiance: list[float] = []
            for z in range(field.depth):
                for x in range(field.width):
                    left = field.heights[z * field.width + max(0, x - 1)]; right = field.heights[z * field.width + min(field.width - 1, x + 1)]
                    down = field.heights[max(0, z - 1) * field.width + x]; up = field.heights[min(field.depth - 1, z + 1) * field.width + x]
                    normal = _normalize((left - right, 2.0 * field.cell_size, down - up))
                    direct = max(0.0, sum(a * b for a, b in zip(normal, direction)))
                    ambient = 0.18 + 0.32 * max(0.0, normal[1])
                    irradiance.append(round((ambient + direct * 0.82) * intensity, 6)); sample_count += 1
            lightmaps.append({"terrain_asset_id": terrain_id, "width": field.width, "height": field.depth,
                              "format": "r16f", "irradiance": irradiance})
        payload = {"schema": WORLD_BUILD_SCHEMA, "kind": "lighting_bake", "asset_id": asset_id,
                   "platform": platform, "quality": quality, "mode": values.get("mode", "hybrid"),
                   "lightmaps": lightmaps, "reflection_captures": list(values.get("reflection_captures") or ()),
                   "environment": environment, "denoised": bool(values.get("denoise", True))}
        return payload, {"lightmap_count": len(lightmaps), "sample_count": sample_count,
                         "reflection_capture_count": len(payload["reflection_captures"])}

    def _hlod(self, asset_id: str, *, platform: str, quality: str):
        values = self.world.properties(asset_id); ratio = max(0.001, min(1.0, float(values.get("reduction_ratio", 0.25))))
        members: list[dict[str, Any]] = []
        for layer_id in values.get("source_data_layer_ids") or ():
            record = self.database.asset(str(layer_id))
            if record is None or record.asset_type != "tc.data_layer": continue
            layer = self.world.properties(record.asset_id)
            for member_id in layer.get("asset_ids") or ():
                member = self.database.asset(str(member_id))
                if member is not None:
                    triangles = max(48, int(member.metadata.get("triangle_count", max(48, member.size // 36))))
                    members.append({"asset_id": member.asset_id, "source_triangles": triangles})
        source_triangles = sum(row["source_triangles"] for row in members)
        proxy_triangles = max(12 if members else 0, int(source_triangles * ratio))
        cluster = {"id": f"hlod:{asset_id}:0", "members": members, "source_triangles": source_triangles,
                   "proxy_triangles": proxy_triangles, "method": values.get("method", "merged_mesh"),
                   "material_atlas": {"enabled": bool(values.get("merge_materials", True)),
                                      "size": int(values.get("material_texture_size", 1024))}}
        payload = {"schema": WORLD_BUILD_SCHEMA, "kind": "hlod_clusters", "asset_id": asset_id,
                   "platform": platform, "quality": quality, "clusters": [cluster] if members else [],
                   "transition_distance": float(values.get("transition_distance", 50000.0))}
        return payload, {"cluster_count": int(bool(members)), "member_count": len(members),
                         "source_triangles": source_triangles, "proxy_triangles": proxy_triangles}

    def _partition(self, asset_id: str, *, platform: str, quality: str):
        values = self.world.properties(asset_id); cell_size = max(1.0, float(values.get("cell_size", 12800.0)))
        members: list[dict[str, Any]] = []
        for layer_id in values.get("data_layer_ids") or ():
            record = self.database.asset(str(layer_id))
            if record is None or record.asset_type != "tc.data_layer": continue
            layer = self.world.properties(record.asset_id)
            for index, member_id in enumerate(layer.get("asset_ids") or ()):
                # Stable fallback placement keeps unpositioned assets deterministic until actor bounds are available.
                digest = int.from_bytes(str(member_id).encode("utf-8")[:8].ljust(8, b"0"), "little")
                x, z = float((digest % 17) * cell_size), float(((digest // 17) % 17) * cell_size)
                members.append({"asset_id": str(member_id), "data_layer_id": record.asset_id,
                                "cell": [int(x // cell_size), int(z // cell_size)]})
        cells: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for member in members: cells.setdefault(tuple(member["cell"]), []).append(member)
        rows = [{"id": f"cell:{x}:{z}", "x": x, "z": z, "members": items,
                 "bounds": [x * cell_size, z * cell_size, (x + 1) * cell_size, (z + 1) * cell_size]}
                for (x, z), items in sorted(cells.items())]
        payload = {"schema": WORLD_BUILD_SCHEMA, "kind": "streaming_cells", "asset_id": asset_id,
                   "platform": platform, "quality": quality, "cell_size": cell_size,
                   "loading_range": float(values.get("loading_range", 76800.0)), "cells": rows,
                   "streaming_sources": list(values.get("streaming_sources") or ()),
                   "budgets": dict(values.get("budgets") or {})}
        return payload, {"cell_count": len(rows), "member_count": len(members)}


def _heightfield(payload: Mapping[str, Any]) -> HeightField:
    return HeightField(int(payload["width"]), int(payload["depth"]), float(payload["cell_size"]),
                       tuple(float(value) for value in payload["heights"]), tuple(payload.get("origin") or (0, 0, 0)),
                       {key: tuple(float(value) for value in rows) for key, rows in dict(payload.get("attributes") or {}).items()})


def _terrain_ids(values: Mapping[str, Any], database: AssetDatabase) -> tuple[str, ...]:
    explicit = [str(value) for value in values.get("terrain_asset_ids") or ()]
    return tuple(value for value in explicit if (database.asset(value) and database.asset(value).asset_type == "tc.terrain"))


def _resolution_cap(platform: str, quality: str) -> int:
    platform_cap = {"mobile": 129, "web": 129, "switch": 129}.get(str(platform).casefold(), 513)
    quality_cap = {"low": 65, "medium": 129, "high": 257, "epic": 513}.get(str(quality).casefold(), 257)
    return min(platform_cap, quality_cap)


def _sample_indices(length: int, stride: int) -> list[int]:
    values = list(range(0, length, max(1, stride)))
    if values[-1] != length - 1: values.append(length - 1)
    return values


def _terrain_bounds(field: HeightField) -> list[float]:
    return [0.0, min(field.heights), 0.0, (field.width - 1) * field.cell_size,
            max(field.heights), (field.depth - 1) * field.cell_size]


def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector))
    return tuple(value / max(1e-9, length) for value in vector)


__all__ = ["WORLD_BUILD_SCHEMA", "WorldBuildReceipt", "WorldBuildService"]
