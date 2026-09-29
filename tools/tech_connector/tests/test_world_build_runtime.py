from __future__ import annotations

import json

from tech_connector.game_engine.assets import AssetDatabase, TCEditorAPI, WorldBuildService
from tech_connector.game_engine.runtime import StreamingSource, WorldStreamingRuntime


def _world_stack(tmp_path):
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    level = api.create_asset("tc.prefab", "WorldLevel", folder="Assets/Test")
    prop = api.create_asset("tc.data", "Rock", folder="Assets/Test")
    terrain = api.create_world_asset("tc.terrain", "Terrain", properties={
        "resolution": [17, 17], "cell_size": 100.0, "height_scale": 60.0, "seed": 4,
        "erosion": {"mode": "none", "iterations": 0},
        "lod": {"levels": 4}, "collision": {"enabled": True, "lod": 1},
    })
    layer = api.create_world_asset("tc.data_layer", "Gameplay", properties={"asset_ids": [prop.asset_id]})
    navigation = api.create_world_asset("tc.navigation_mesh", "Nav", properties={
        "terrain_asset_ids": [terrain.asset_id], "tile_size": 400.0,
        "agents": [{"name": "Human", "radius": 34.0, "height": 180.0, "maximum_slope": 89.0}],
    })
    lighting = api.create_world_asset("tc.lighting_scenario", "Day", properties={
        "terrain_asset_ids": [terrain.asset_id], "environment": {"intensity": 1.2, "rotation": 35.0},
    })
    hlod = api.create_world_asset("tc.hlod_layer", "Far", properties={
        "source_data_layer_ids": [layer.asset_id], "reduction_ratio": 0.25,
    })
    partition = api.create_world_asset("tc.world_partition", "Partition", properties={
        "source_level_id": level.asset_id, "data_layer_ids": [layer.asset_id],
        "hlod_layer_ids": [hlod.asset_id], "cell_size": 1000.0, "loading_range": 1500.0,
        "budgets": {"maximum_loaded_cells": 2, "memory_mb": 16, "io_mb_per_second": 64, "maximum_requests": 1},
    })
    return database, api, terrain, navigation, lighting, hlod, partition


def test_world_builds_generate_runtime_geometry_navigation_lighting_and_hlod(tmp_path) -> None:
    database, _api, terrain, navigation, lighting, hlod, partition = _world_stack(tmp_path)
    builds = WorldBuildService(tmp_path, database)

    terrain_build = builds.build(terrain.asset_id, quality="high")
    terrain_payload = json.loads(terrain_build.artifact.path.read_text(encoding="utf-8"))
    assert terrain_build.statistics["lod_count"] == 4
    assert terrain_build.statistics["lod0_vertices"] == 17 * 17
    assert terrain_payload["collision"]["indices"]

    nav_build = builds.build(navigation.asset_id)
    nav_payload = json.loads(nav_build.artifact.path.read_text(encoding="utf-8"))
    assert nav_build.statistics["tile_count"] > 0
    assert nav_build.statistics["polygon_count"] == 16 * 16
    assert all(tile["agent"] == "Human" for tile in nav_payload["tiles"])

    light_build = builds.build(lighting.asset_id)
    light_payload = json.loads(light_build.artifact.path.read_text(encoding="utf-8"))
    assert light_build.statistics["sample_count"] == 17 * 17
    assert len(light_payload["lightmaps"][0]["irradiance"]) == 17 * 17
    assert min(light_payload["lightmaps"][0]["irradiance"]) >= 0.0

    hlod_build = builds.build(hlod.asset_id)
    assert hlod_build.statistics["cluster_count"] == 1
    assert hlod_build.statistics["proxy_triangles"] < hlod_build.statistics["source_triangles"]

    partition_build = builds.build(partition.asset_id)
    partition_payload = json.loads(partition_build.artifact.path.read_text(encoding="utf-8"))
    assert partition_build.statistics == {"cell_count": 1, "member_count": 1}
    assert partition_payload["cells"][0]["members"][0]["asset_id"]


def test_world_streaming_runtime_respects_request_memory_and_hysteresis(tmp_path) -> None:
    database, api, _terrain, _navigation, _lighting, _hlod, partition = _world_stack(tmp_path)
    runtime = api.open_world_streaming_runtime(partition.asset_id)
    assert isinstance(runtime, WorldStreamingRuntime)
    cell = next(iter(runtime.cells.values()))
    source = StreamingSource("Player", cell.center, 500.0, priority=100)
    first = runtime.tick([source])
    assert first.loaded == (cell.cell_id,) and first.memory_mb <= first.budget_memory_mb
    for _ in range(runtime.unload_hysteresis_frames):
        receipt = runtime.tick([])
        assert cell.cell_id in receipt.resident
    unloaded = runtime.tick([])
    assert unloaded.unloaded == (cell.cell_id,)


def test_python_world_backend_and_production_cook_include_generated_outputs(tmp_path) -> None:
    database, api, terrain, navigation, _lighting, _hlod, _partition = _world_stack(tmp_path)
    result = api.build_world_backend(navigation.asset_id)
    assert result["build_kind"] == "navigation_tiles"
    cook = api.cook([navigation.asset_id])
    manifest = json.loads(cook.artifact.path.read_text(encoding="utf-8"))
    nav_row = next(row for row in manifest["assets"] if row["asset_id"] == navigation.asset_id)
    terrain_row = next(row for row in manifest["assets"] if row["asset_id"] == terrain.asset_id)
    assert {row["kind"] for row in nav_row["derived_outputs"]} >= {"navigation_mesh_runtime", "navigation_tiles"}
    assert {row["kind"] for row in terrain_row["derived_outputs"]} >= {"terrain_runtime", "terrain_geometry"}

