"""World-production assets shared by editor tools, Python automation, and cooks.

The module deliberately keeps authoring data declarative.  Expensive native terrain,
navigation, lighting, HLOD, and streaming backends can consume the same deterministic
runtime manifests without teaching each editor its own private format.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from tech_connector.game_engine.authoring.procedural_biome_service import (
    BiomeDefinition,
    BiomeSpecies,
    generate_noise_heightfield,
    hydraulic_erode_heightfield,
    scatter_biome,
    thermal_erode_heightfield,
)

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService


WORLD_ASSET_SCHEMA = "tech_connector.world_asset.v1"
WORLD_RUNTIME_SCHEMA = "tech_connector.world_runtime.v1"
WORLD_ASSET_TYPES = frozenset({
    "tc.terrain", "tc.foliage_type", "tc.biome", "tc.navigation_mesh",
    "tc.lighting_scenario", "tc.data_layer", "tc.hlod_layer", "tc.world_partition",
})


@dataclass(frozen=True)
class WorldAssetIssue:
    severity: str
    code: str
    message: str
    subject: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def terrain_defaults() -> dict[str, Any]:
    return {
        "terrain_version": 1, "source": "procedural", "resolution": [129, 129],
        "cell_size": 100.0, "height_scale": 2000.0, "seed": 1337,
        "noise": {"frequency": 0.018, "octaves": 6, "lacunarity": 2.0, "gain": 0.5},
        "erosion": {"mode": "thermal", "iterations": 8, "strength": 0.35},
        "heightmap_asset_id": "", "layers": [
            {"name": "Base", "material_asset_id": "", "weight": 1.0, "paintable": True},
        ],
        "lod": {"levels": 6, "screen_error": 1.0, "skirt_depth": 100.0},
        "collision": {"enabled": True, "lod": 1},
        "navigation": {"affects_navigation": True},
        "edit_layers": True, "runtime_virtual_texture": False,
    }


def foliage_type_defaults() -> dict[str, Any]:
    return {
        "foliage_version": 1, "mesh_asset_id": "", "density": 1.0,
        "scale_range": [0.85, 1.2], "yaw_range": [0.0, 360.0],
        "align_to_normal": True, "random_pitch": 4.0, "minimum_spacing": 100.0,
        "slope_range": [0.0, 50.0], "elevation_range": [-100000.0, 100000.0],
        "moisture_range": [0.0, 1.0], "temperature_range": [0.0, 1.0],
        "cull_distance": [5000.0, 30000.0], "cast_shadows": True,
        "collision": "none", "affects_navigation": False,
        "instance_lods": True, "wind": {"enabled": True, "strength": 1.0},
    }


def biome_defaults() -> dict[str, Any]:
    return {
        "biome_version": 1, "terrain_asset_id": "", "seed": 1337,
        "density": 0.55, "samples_per_cell": 1, "species": [],
        "exclusion_masks": [], "regeneration": "on_dependency_change",
        "partition_cell_size": 6400.0,
    }


def navigation_mesh_defaults() -> dict[str, Any]:
    return {
        "navigation_version": 1, "source_level_ids": [], "terrain_asset_ids": [], "bounds": [],
        "agents": [{"name": "Humanoid", "radius": 34.0, "height": 180.0,
                    "step_height": 45.0, "maximum_slope": 45.0}],
        "voxel_size": 10.0, "tile_size": 1024.0, "region_minimum_area": 2.0,
        "areas": [{"name": "Walkable", "cost": 1.0}, {"name": "Blocked", "cost": -1.0}],
        "off_mesh_links": [], "dynamic_obstacles": True, "runtime_generation": "dynamic_modifiers",
        "draw": {"polygons": True, "links": True, "tile_bounds": False},
    }


def lighting_scenario_defaults() -> dict[str, Any]:
    return {
        "lighting_version": 1, "mode": "hybrid", "source_level_ids": [], "terrain_asset_ids": [],
        "global_illumination": "dynamic", "lightmap_resolution": 64,
        "texel_density": 10.24, "indirect_bounces": 3, "quality": "production",
        "environment": {"sky_asset_id": "", "intensity": 1.0, "rotation": 0.0},
        "reflection_captures": [], "volumetric_samples": True,
        "virtual_shadow_maps": True, "denoise": True, "compression": True,
    }


def data_layer_defaults() -> dict[str, Any]:
    return {
        "data_layer_version": 1, "kind": "runtime", "parent_layer_id": "",
        "initial_state": "loaded", "asset_ids": [], "actor_paths": [],
        "runtime_rules": {"priority": 0, "distance": 0.0}, "color": "#50a8ff",
        "locked": False,
    }


def hlod_layer_defaults() -> dict[str, Any]:
    return {
        "hlod_version": 1, "method": "merged_mesh", "source_data_layer_ids": [],
        "transition_distance": 50000.0, "loading_range": 75000.0,
        "cell_size": 25600.0, "reduction_ratio": 0.25, "minimum_actor_count": 2,
        "merge_materials": True, "material_texture_size": 1024,
        "generate_collision": False, "include_impostors": True,
    }


def world_partition_defaults() -> dict[str, Any]:
    return {
        "partition_version": 1, "source_level_id": "", "enabled": True,
        "cell_size": 12800.0, "loading_range": 76800.0,
        "data_layer_ids": [], "hlod_layer_ids": [],
        "streaming_sources": [{"name": "Player", "shape": "sphere", "priority": 100,
                               "range_multiplier": 1.0}],
        "budgets": {"maximum_loaded_cells": 256, "memory_mb": 2048,
                    "io_mb_per_second": 256, "maximum_requests": 16},
        "always_loaded_asset_ids": [], "cook_empty_cells": False,
    }


_DEFAULT_FACTORIES = {
    "tc.terrain": terrain_defaults, "tc.foliage_type": foliage_type_defaults,
    "tc.biome": biome_defaults, "tc.navigation_mesh": navigation_mesh_defaults,
    "tc.lighting_scenario": lighting_scenario_defaults, "tc.data_layer": data_layer_defaults,
    "tc.hlod_layer": hlod_layer_defaults, "tc.world_partition": world_partition_defaults,
}


def defaults_for_world_asset(type_id: str) -> dict[str, Any]:
    try:
        return _DEFAULT_FACTORIES[str(type_id).casefold()]()
    except KeyError as exc:
        raise ValueError(f"Unsupported world asset type: {type_id}") from exc


class WorldAssetService:
    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.operations = AssetOperationsService(self.project_root, database)

    def create(self, type_id: str, name: str, *, folder: str | Path = "Assets/World",
               properties: Mapping[str, Any] | None = None):
        values = defaults_for_world_asset(type_id)
        values.update(deepcopy(dict(properties or {})))
        receipt = self.operations.create_asset(type_id, name, folder=folder, properties=values)
        self.update(receipt.asset_id, values, replace=True)
        return receipt

    def properties(self, asset_id: str) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        values = defaults_for_world_asset(record.asset_type)
        values.update(deepcopy(dict(payload.get("properties") or {})))
        return values

    def update(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        record, payload = self._load(asset_id)
        properties = defaults_for_world_asset(record.asset_type) if replace else self.properties(asset_id)
        properties.update(deepcopy(dict(values or {})))
        payload["properties"] = properties
        temporary = record.source_path.with_name(f".{record.source_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, record.source_path)
        dependencies = tuple((reference, "world_reference") for reference in sorted(_asset_references(properties))
                             if reference != asset_id and self.database.asset(reference) is not None)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=asset_id,
                                     metadata=record.metadata, dependencies=dependencies)
        return properties

    def validate(self, asset_id: str) -> list[WorldAssetIssue]:
        record, _payload = self._load(asset_id)
        values = self.properties(asset_id)
        issues = validate_world_asset(record.asset_type, values)
        for reference in _asset_references(values):
            if self.database.asset(reference) is None:
                issues.append(WorldAssetIssue("error", "missing_reference",
                                              f"Referenced asset does not exist: {reference}", reference))
        return _unique_issues(issues)

    def build_preview(self, asset_id: str, *, maximum_resolution: int = 257) -> dict[str, Any]:
        record, _payload = self._load(asset_id)
        values = self.properties(asset_id)
        if record.asset_type == "tc.terrain":
            return _build_terrain(values, maximum_resolution=maximum_resolution)
        if record.asset_type == "tc.biome":
            terrain_id = str(values.get("terrain_asset_id") or "")
            terrain = self.database.asset(terrain_id)
            if terrain is None or terrain.asset_type != "tc.terrain":
                raise ValueError("Biome preview requires a valid Terrain asset.")
            terrain_payload = _build_terrain(self.properties(terrain_id), maximum_resolution=maximum_resolution)
            return _build_biome(values, terrain_payload, self)
        return compile_world_payload(record.asset_type, values, platform="editor", quality="preview")

    def compile(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record, _payload = self._load(asset_id)
        errors = [item.message for item in self.validate(asset_id) if item.severity == "error"]
        if errors:
            raise ValueError(f"{record.source_path.name} is not cookable: " + "; ".join(errors))
        values = self.properties(asset_id)
        payload = compile_world_payload(record.asset_type, values, platform=platform, quality=quality)
        if record.asset_type == "tc.terrain":
            cap = {"mobile": 129, "web": 129, "switch": 129}.get(str(platform).casefold(), 513)
            payload["generated"] = _build_terrain(values, maximum_resolution=cap)
        elif record.asset_type == "tc.biome":
            terrain_id = str(values.get("terrain_asset_id") or "")
            terrain = self.database.asset(terrain_id)
            if terrain is not None and terrain.asset_type == "tc.terrain":
                terrain_payload = _build_terrain(self.properties(terrain_id), maximum_resolution=129)
                payload["generated"] = _build_biome(values, terrain_payload, self)
        extension = ".tcworldbin"
        return self.database.store_derived(
            asset_id, f"world:{record.asset_type}:{platform}:{quality}",
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            metadata={"platform": platform, "quality": quality, "type_id": record.asset_type},
            extension=extension,
        )

    def _load(self, asset_id: str):
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in WORLD_ASSET_TYPES:
            raise KeyError(f"Unknown world-production asset: {asset_id}")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read {record.source_path.name}: {exc}") from exc
        return record, payload


def validate_world_asset(type_id: str, values: Mapping[str, Any]) -> list[WorldAssetIssue]:
    issues: list[WorldAssetIssue] = []
    def error(code: str, message: str, subject: str = "") -> None:
        issues.append(WorldAssetIssue("error", code, message, subject))
    if type_id == "tc.terrain":
        resolution = list(values.get("resolution") or ())
        if len(resolution) != 2 or any(int(value) < 2 for value in resolution):
            error("resolution", "Terrain resolution must contain two values of at least 2.", "resolution")
        elif any((int(value) - 1) & (int(value) - 2) for value in resolution):
            issues.append(WorldAssetIssue("warning", "patch_alignment",
                                          "Power-of-two-plus-one terrain dimensions stream most efficiently.", "resolution"))
        if float(values.get("cell_size", 0.0)) <= 0.0:
            error("cell_size", "Terrain cell size must be positive.", "cell_size")
        layers = [dict(row) for row in values.get("layers") or ()]
        names = [str(row.get("name") or "") for row in layers]
        if not layers or any(not name for name in names) or len(names) != len(set(names)):
            error("layers", "Terrain needs uniquely named paint layers.", "layers")
    elif type_id == "tc.foliage_type":
        if not str(values.get("mesh_asset_id") or ""):
            error("mesh", "Choose a mesh for this Foliage Type.", "mesh_asset_id")
        scale = list(values.get("scale_range") or ())
        if len(scale) != 2 or float(scale[0]) <= 0.0 or float(scale[1]) < float(scale[0]):
            error("scale_range", "Foliage scale range must be positive and ordered.", "scale_range")
        if float(values.get("minimum_spacing", 0.0)) < 0.0:
            error("spacing", "Minimum spacing cannot be negative.", "minimum_spacing")
    elif type_id == "tc.biome":
        if not str(values.get("terrain_asset_id") or ""):
            error("terrain", "Choose a Terrain asset for biome generation.", "terrain_asset_id")
        species = [dict(row) for row in values.get("species") or ()]
        if not species:
            error("species", "Add at least one Foliage Type to the biome.", "species")
        if any(not str(row.get("foliage_type_id") or "") for row in species):
            error("species_reference", "Every biome species needs a Foliage Type asset.", "species")
        if not 0.0 <= float(values.get("density", 0.0)) <= 1.0:
            error("density", "Biome density must be between zero and one.", "density")
    elif type_id == "tc.navigation_mesh":
        agents = [dict(row) for row in values.get("agents") or ()]
        if not agents:
            error("agents", "Add at least one navigation agent profile.", "agents")
        for row in agents:
            if float(row.get("radius", 0.0)) <= 0.0 or float(row.get("height", 0.0)) <= 0.0:
                error("agent_size", "Navigation agents require positive radius and height.", str(row.get("name") or "agents"))
        if float(values.get("voxel_size", 0.0)) <= 0.0 or float(values.get("tile_size", 0.0)) <= 0.0:
            error("navigation_grid", "Navigation voxel and tile sizes must be positive.")
    elif type_id == "tc.lighting_scenario":
        if str(values.get("mode") or "") not in {"baked", "dynamic", "hybrid"}:
            error("mode", "Lighting mode must be baked, dynamic, or hybrid.", "mode")
        if int(values.get("lightmap_resolution", 0)) <= 0 or int(values.get("indirect_bounces", -1)) < 0:
            error("bake_settings", "Lighting bake resolution must be positive and bounces non-negative.")
    elif type_id == "tc.data_layer":
        if str(values.get("kind") or "") not in {"runtime", "editor"}:
            error("kind", "Data Layer kind must be runtime or editor.", "kind")
        if str(values.get("initial_state") or "") not in {"unloaded", "loaded", "activated"}:
            error("initial_state", "Data Layer state must be unloaded, loaded, or activated.", "initial_state")
    elif type_id == "tc.hlod_layer":
        if str(values.get("method") or "") not in {"instancing", "merged_mesh", "simplified_mesh", "impostor"}:
            error("method", "Choose a supported HLOD generation method.", "method")
        ratio = float(values.get("reduction_ratio", 0.0))
        if not 0.0 < ratio <= 1.0:
            error("reduction_ratio", "HLOD reduction ratio must be above zero and at most one.", "reduction_ratio")
    elif type_id == "tc.world_partition":
        if not str(values.get("source_level_id") or ""):
            error("source_level", "Choose the Level managed by this World Partition.", "source_level_id")
        if float(values.get("cell_size", 0.0)) <= 0.0 or float(values.get("loading_range", 0.0)) <= 0.0:
            error("streaming_grid", "World Partition cell size and loading range must be positive.")
        budgets = dict(values.get("budgets") or {})
        if any(float(budgets.get(key, 0.0)) <= 0.0 for key in ("maximum_loaded_cells", "memory_mb", "io_mb_per_second", "maximum_requests")):
            error("budgets", "All World Partition streaming budgets must be positive.", "budgets")
    else:
        error("type", f"Unsupported world asset type: {type_id}")
    return issues


def compile_world_payload(type_id: str, values: Mapping[str, Any], *, platform: str, quality: str) -> dict[str, Any]:
    runtime = deepcopy(dict(values))
    runtime.pop("draw", None)
    if type_id == "tc.terrain":
        runtime.pop("height_data", None)
        runtime.pop("layer_weights", None)
    if type_id == "tc.world_partition":
        budgets = dict(runtime.get("budgets") or {})
        scale = {"low": 0.5, "medium": 0.75, "high": 1.0, "epic": 1.25}.get(str(quality).casefold(), 1.0)
        budgets["maximum_loaded_cells"] = max(1, int(float(budgets.get("maximum_loaded_cells", 256)) * scale))
        budgets["memory_mb"] = max(64, int(float(budgets.get("memory_mb", 2048)) * scale))
        runtime["budgets"] = budgets
    return {"schema": WORLD_RUNTIME_SCHEMA, "type_id": type_id, "platform": str(platform),
            "quality": str(quality), "runtime": runtime}


def apply_terrain_brush(
    values: Mapping[str, Any], *, center: tuple[float, float], radius: float, strength: float,
    mode: str = "raise", layer: str = "Base", target_height: float | None = None,
) -> dict[str, Any]:
    """Apply a normalized UV-space sculpt or paint stroke to editable terrain samples."""
    result = deepcopy(dict(values))
    generated = _editable_terrain(result)
    width, depth = int(generated["width"]), int(generated["depth"])
    heights = [float(value) for value in generated["heights"]]
    cx = max(0.0, min(1.0, float(center[0]))) * (width - 1)
    cz = max(0.0, min(1.0, float(center[1]))) * (depth - 1)
    sample_radius = max(0.5, float(radius) * max(width - 1, depth - 1))
    amount = float(strength)
    source = list(heights)
    weights = deepcopy(dict(result.get("layer_weights") or {}))
    paint_values = [float(value) for value in weights.get(str(layer), [0.0] * (width * depth))]
    if len(paint_values) != width * depth:
        paint_values = [0.0] * (width * depth)
    for z in range(max(0, int(cz - sample_radius)), min(depth, int(cz + sample_radius) + 2)):
        for x in range(max(0, int(cx - sample_radius)), min(width, int(cx + sample_radius) + 2)):
            distance = math.hypot(x - cx, z - cz) / sample_radius
            if distance > 1.0:
                continue
            falloff = (1.0 - distance) ** 2 * (3.0 - 2.0 * (1.0 - distance))
            index = z * width + x
            if mode == "paint":
                paint_values[index] = max(0.0, min(1.0, paint_values[index] + amount * falloff))
            elif mode == "flatten":
                target = float(target_height if target_height is not None else source[int(round(cz)) * width + int(round(cx))])
                heights[index] += (target - heights[index]) * max(0.0, min(1.0, abs(amount) * falloff))
            elif mode == "smooth":
                neighbors = [source[nz * width + nx]
                             for nz in range(max(0, z - 1), min(depth, z + 2))
                             for nx in range(max(0, x - 1), min(width, x + 2))]
                average = sum(neighbors) / len(neighbors)
                heights[index] += (average - heights[index]) * max(0.0, min(1.0, abs(amount) * falloff))
            else:
                direction = -1.0 if mode == "lower" else 1.0
                heights[index] += direction * abs(amount) * falloff * float(result.get("height_scale", 1.0)) * 0.02
    if mode == "paint":
        weights[str(layer)] = paint_values
        result["layer_weights"] = weights
    else:
        result["height_data"] = heights
        result["source"] = "painted"
    result["edit_revision"] = int(result.get("edit_revision", 0)) + 1
    return result


def build_terrain_preview(values: Mapping[str, Any], *, maximum_resolution: int = 257) -> dict[str, Any]:
    return _build_terrain(values, maximum_resolution=maximum_resolution)


def apply_foliage_brush(
    values: Mapping[str, Any], *, center: tuple[float, float], radius: float,
    density: float = 1.0, erase: bool = False, seed: int = 0,
) -> dict[str, Any]:
    """Paint stable manual foliage instances in normalized terrain space."""
    result = deepcopy(dict(values))
    instances = [dict(row) for row in result.get("manual_instances") or ()]
    center_x, center_z = (max(0.0, min(1.0, float(value))) for value in center)
    brush_radius = max(0.001, float(radius))
    if erase:
        instances = [row for row in instances if math.hypot(float(row.get("u", 0.0)) - center_x,
                                                              float(row.get("v", 0.0)) - center_z) > brush_radius]
    else:
        attempts = max(1, int(max(0.0, float(density)) * 24.0 * brush_radius * brush_radius + 1))
        stroke = int(result.get("paint_revision", 0))
        spacing = max(0.002, float(result.get("minimum_spacing", 100.0)) / 100000.0)
        for index in range(attempts):
            digest = hashlib.sha256(f"{seed}|{stroke}|{index}".encode("utf-8")).digest()
            angle = int.from_bytes(digest[:4], "big") / 2**32 * math.tau
            radial = math.sqrt(int.from_bytes(digest[4:8], "big") / 2**32) * brush_radius
            u = max(0.0, min(1.0, center_x + math.cos(angle) * radial))
            v = max(0.0, min(1.0, center_z + math.sin(angle) * radial))
            if any(math.hypot(float(row.get("u", 0.0)) - u, float(row.get("v", 0.0)) - v) < spacing for row in instances):
                continue
            instances.append({"id": f"paint:{stroke}:{index}", "u": u, "v": v,
                              "yaw": int.from_bytes(digest[8:12], "big") / 2**32 * 360.0,
                              "scale": 0.85 + int.from_bytes(digest[12:16], "big") / 2**32 * 0.35})
    result["manual_instances"] = instances
    result["paint_revision"] = int(result.get("paint_revision", 0)) + 1
    return result


def build_navigation_preview(values: Mapping[str, Any], *, extent: tuple[float, float] = (10000.0, 10000.0)) -> dict[str, Any]:
    tile_size = max(1.0, float(values.get("tile_size", 1024.0)))
    columns = max(1, min(128, math.ceil(float(extent[0]) / tile_size)))
    rows = max(1, min(128, math.ceil(float(extent[1]) / tile_size)))
    tiles = []
    for z in range(rows):
        for x in range(columns):
            tiles.append({"id": f"nav:{x}:{z}", "x": x, "z": z,
                          "bounds": [x * tile_size, z * tile_size,
                                     min((x + 1) * tile_size, extent[0]), min((z + 1) * tile_size, extent[1])],
                          "area": "Walkable", "state": "built"})
    return {"schema": "tech_connector.navigation_preview.v1", "columns": columns, "rows": rows,
            "tiles": tiles, "agents": deepcopy(list(values.get("agents") or ())),
            "off_mesh_links": deepcopy(list(values.get("off_mesh_links") or ()))}


def build_lighting_preview(values: Mapping[str, Any]) -> dict[str, Any]:
    resolution = max(1, int(values.get("lightmap_resolution", 64)))
    captures = list(values.get("reflection_captures") or ())
    stages = [
        {"name": "Geometry", "weight": 0.12}, {"name": "Direct Lighting", "weight": 0.18},
        {"name": "Indirect Lighting", "weight": 0.42}, {"name": "Reflections", "weight": 0.16},
        {"name": "Denoise & Package", "weight": 0.12},
    ]
    return {"schema": "tech_connector.lighting_build.v1", "mode": values.get("mode", "hybrid"),
            "quality": values.get("quality", "production"), "stages": stages,
            "estimated_texels": resolution * resolution * max(1, len(values.get("source_level_ids") or ()) or 1),
            "reflection_capture_count": len(captures), "status": "ready_to_build"}


def build_partition_preview(values: Mapping[str, Any], *, extent: tuple[float, float] = (100000.0, 100000.0)) -> dict[str, Any]:
    cell_size = max(1.0, float(values.get("cell_size", 12800.0)))
    columns = max(1, min(128, math.ceil(extent[0] / cell_size)))
    rows = max(1, min(128, math.ceil(extent[1] / cell_size)))
    sources = [dict(row) for row in values.get("streaming_sources") or ()]
    loading_range = max(0.0, float(values.get("loading_range", 0.0)))
    cells = []
    for z in range(rows):
        for x in range(columns):
            center = ((x + 0.5) * cell_size, (z + 0.5) * cell_size)
            active = any(math.hypot(center[0] - float(source.get("x", extent[0] * 0.5)),
                                    center[1] - float(source.get("z", extent[1] * 0.5))) <=
                         loading_range * float(source.get("range_multiplier", 1.0)) for source in sources)
            cells.append({"id": f"cell:{x}:{z}", "x": x, "z": z,
                          "bounds": [x * cell_size, z * cell_size, (x + 1) * cell_size, (z + 1) * cell_size],
                          "state": "loaded" if active else "unloaded"})
    return {"schema": "tech_connector.world_partition_preview.v1", "columns": columns, "rows": rows,
            "cells": cells, "loaded_cells": sum(row["state"] == "loaded" for row in cells),
            "budgets": deepcopy(dict(values.get("budgets") or {}))}


def build_hlod_preview(values: Mapping[str, Any], *, source_triangles: int = 100000) -> dict[str, Any]:
    ratio = max(0.001, min(1.0, float(values.get("reduction_ratio", 0.25))))
    proxy = max(12, int(source_triangles * ratio))
    return {"schema": "tech_connector.hlod_preview.v1", "method": values.get("method", "merged_mesh"),
            "source_triangles": int(source_triangles), "proxy_triangles": proxy,
            "triangle_reduction_percent": round((1.0 - proxy / max(1, source_triangles)) * 100.0, 2),
            "material_bake": bool(values.get("merge_materials", True)),
            "texture_size": int(values.get("material_texture_size", 1024)),
            "transition_distance": float(values.get("transition_distance", 50000.0))}


def _build_terrain(values: Mapping[str, Any], *, maximum_resolution: int) -> dict[str, Any]:
    resolution = list(values.get("resolution") or [129, 129])
    width, depth = min(int(resolution[0]), maximum_resolution), min(int(resolution[1]), maximum_resolution)
    noise = dict(values.get("noise") or {})
    authored_heights = list(values.get("height_data") or ())
    field = generate_noise_heightfield(
        width, depth, cell_size=float(values.get("cell_size", 100.0)), seed=int(values.get("seed", 0)),
        amplitude=float(values.get("height_scale", 2000.0)), frequency=float(noise.get("frequency", 0.018)),
        octaves=int(noise.get("octaves", 6)), lacunarity=float(noise.get("lacunarity", 2.0)),
        gain=float(noise.get("gain", 0.5)),
    )
    if len(authored_heights) == width * depth:
        from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField
        field = HeightField(width, depth, field.cell_size, tuple(float(value) for value in authored_heights),
                            field.origin, dict(field.attributes))
    erosion = dict(values.get("erosion") or {})
    mode = str(erosion.get("mode") or "none")
    if mode == "thermal":
        field = thermal_erode_heightfield(field, iterations=int(erosion.get("iterations", 8)),
                                          strength=float(erosion.get("strength", 0.35)))
    elif mode == "hydraulic":
        field = hydraulic_erode_heightfield(field, iterations=int(erosion.get("iterations", 16)))
    return {"schema": "tech_connector.terrain_heightfield.v1", "width": field.width, "depth": field.depth,
            "cell_size": field.cell_size, "origin": list(field.origin), "heights": list(field.heights),
            "attributes": {key: list(rows) for key, rows in field.attributes.items()},
            "source_resolution": [int(resolution[0]), int(resolution[1])],
            "preview_limited": width != int(resolution[0]) or depth != int(resolution[1])}


def _editable_terrain(values: Mapping[str, Any]) -> dict[str, Any]:
    resolution = list(values.get("resolution") or [129, 129])
    if int(resolution[0]) > 513 or int(resolution[1]) > 513:
        raise ValueError("Interactive terrain editing is limited to 513x513 samples per component; split larger worlds into components.")
    return _build_terrain(values, maximum_resolution=513)


def _build_biome(values: Mapping[str, Any], terrain: Mapping[str, Any], service: WorldAssetService) -> dict[str, Any]:
    from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField
    species: list[BiomeSpecies] = []
    for entry in values.get("species") or ():
        row = dict(entry); foliage_id = str(row.get("foliage_type_id") or "")
        record = service.database.asset(foliage_id)
        if record is None or record.asset_type != "tc.foliage_type":
            continue
        foliage = service.properties(foliage_id)
        species.append(BiomeSpecies(
            asset=str(foliage.get("mesh_asset_id") or foliage_id), weight=float(row.get("weight", 1.0)),
            minimum_elevation=float(foliage.get("elevation_range", [-100000.0, 100000.0])[0]),
            maximum_elevation=float(foliage.get("elevation_range", [-100000.0, 100000.0])[1]),
            minimum_slope=float(foliage.get("slope_range", [0.0, 90.0])[0]),
            maximum_slope=float(foliage.get("slope_range", [0.0, 90.0])[1]),
            minimum_moisture=float(foliage.get("moisture_range", [0.0, 1.0])[0]),
            maximum_moisture=float(foliage.get("moisture_range", [0.0, 1.0])[1]),
            minimum_temperature=float(foliage.get("temperature_range", [0.0, 1.0])[0]),
            maximum_temperature=float(foliage.get("temperature_range", [0.0, 1.0])[1]),
            minimum_spacing=float(foliage.get("minimum_spacing", 0.0)),
            scale_range=tuple(float(value) for value in foliage.get("scale_range", [1.0, 1.0])),
            generation_grid=float(values.get("partition_cell_size", 6400.0)),
        ))
    field = HeightField(int(terrain["width"]), int(terrain["depth"]), float(terrain["cell_size"]),
                        tuple(float(value) for value in terrain["heights"]), tuple(terrain["origin"]),
                        {key: tuple(float(value) for value in rows) for key, rows in dict(terrain["attributes"]).items()})
    result = scatter_biome(field, BiomeDefinition("Biome", tuple(species),
                           int(values.get("samples_per_cell", 1)), float(values.get("density", 1.0)),
                           int(values.get("seed", 0))))
    return {"schema": "tech_connector.biome_instances.v1", "metadata": result.metadata,
            "instances": [asdict(row) for row in result.instances]}


def _asset_references(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).endswith("_id") or str(key).endswith("_ids"):
                candidates = nested if isinstance(nested, (list, tuple, set)) else (nested,)
                references.update(str(candidate) for candidate in candidates if str(candidate))
            references.update(_asset_references(nested))
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            references.update(_asset_references(nested))
    return references


def _unique_issues(issues: Sequence[WorldAssetIssue]) -> list[WorldAssetIssue]:
    return list(dict.fromkeys(issues))


__all__ = [
    "WORLD_ASSET_SCHEMA", "WORLD_RUNTIME_SCHEMA", "WORLD_ASSET_TYPES", "WorldAssetIssue",
    "WorldAssetService", "biome_defaults", "compile_world_payload", "data_layer_defaults",
    "defaults_for_world_asset", "foliage_type_defaults", "hlod_layer_defaults",
    "lighting_scenario_defaults", "navigation_mesh_defaults", "terrain_defaults",
    "validate_world_asset", "world_partition_defaults", "apply_terrain_brush", "apply_foliage_brush",
    "build_terrain_preview", "build_navigation_preview", "build_lighting_preview", "build_partition_preview", "build_hlod_preview",
]
