from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    AssetDatabase, AssetProductionService, TCEditorAPI, WORLD_ASSET_TYPES,
    WorldAssetService, builtin_asset_type_registry,
)
from tech_connector.game_engine.assets.world_asset_service import (
    apply_foliage_brush, apply_terrain_brush, build_hlod_preview,
    build_lighting_preview, build_navigation_preview, build_partition_preview,
)
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor, editor_pages_for_asset
from tech_connector.ui.game_engine.world_asset_editors import WorldAssetAuthoringWidget


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_world_asset_types_are_first_class_and_have_dedicated_editors() -> None:
    registry = builtin_asset_type_registry()
    assert len(WORLD_ASSET_TYPES) == 8
    for type_id in WORLD_ASSET_TYPES:
        descriptor = registry.require(type_id)
        assert descriptor.creatable
        assert descriptor.cooker_id == "world"
        assert descriptor.python_api_namespace == "editor.world"
        assert len(editor_pages_for_asset(type_id)) >= 5


def test_terrain_preview_is_deterministic_and_cookable(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = WorldAssetService(tmp_path, database)
    receipt = service.create("tc.terrain", "Island", properties={
        "resolution": [17, 17], "cell_size": 50.0, "height_scale": 250.0,
        "seed": 42, "erosion": {"mode": "thermal", "iterations": 2, "strength": 0.2},
    })

    first = service.build_preview(receipt.asset_id)
    second = service.build_preview(receipt.asset_id)
    assert first == second
    assert first["width"] == 17 and len(first["heights"]) == 17 * 17
    assert {"moisture", "temperature"}.issubset(first["attributes"])
    assert not [issue for issue in service.validate(receipt.asset_id) if issue.severity == "error"]

    artifact = service.compile(receipt.asset_id, platform="windows", quality="high")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema"] == "tech_connector.world_runtime.v1"
    assert payload["generated"]["heights"] == first["heights"]


def test_biome_uses_foliage_rules_and_dependency_closed_cook(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    mesh = api.create_asset("tc.data", "TreeMeshPlaceholder", folder="Assets/Test")
    terrain = api.create_world_asset("tc.terrain", "Terrain", properties={
        "resolution": [9, 9], "cell_size": 100.0, "height_scale": 10.0,
        "erosion": {"mode": "none", "iterations": 0},
    })
    foliage = api.create_world_asset("tc.foliage_type", "Tree", properties={
        "mesh_asset_id": mesh.asset_id, "minimum_spacing": 80.0,
        "slope_range": [0.0, 90.0], "scale_range": [0.8, 1.2],
    })
    biome = api.create_world_asset("tc.biome", "Forest", properties={
        "terrain_asset_id": terrain.asset_id, "seed": 7, "density": 1.0,
        "species": [{"foliage_type_id": foliage.asset_id, "weight": 1.0}],
    })

    assert set(database.dependencies(biome.asset_id)) == {terrain.asset_id, foliage.asset_id}
    preview = api.preview_world_asset(biome.asset_id, maximum_resolution=17)
    assert preview["schema"] == "tech_connector.biome_instances.v1"
    assert preview["instances"]
    assert all(row["asset"] == mesh.asset_id for row in preview["instances"])

    cook = AssetProductionService(tmp_path, database).cook_manifest(
        [biome.asset_id], platform="windows", quality="high",
    )
    manifest = json.loads(cook.artifact.path.read_text(encoding="utf-8"))
    assert {row["asset_id"] for row in manifest["assets"]} == {
        mesh.asset_id, terrain.asset_id, foliage.asset_id, biome.asset_id,
    }
    biome_row = next(row for row in manifest["assets"] if row["asset_id"] == biome.asset_id)
    assert any(row["kind"] == "biome_runtime" for row in biome_row["derived_outputs"])


def test_world_partition_validation_quality_budget_and_editor(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    level = api.create_asset("tc.prefab", "LevelPlaceholder", folder="Assets/Test")
    partition = api.create_world_asset("tc.world_partition", "OpenWorld", properties={
        "source_level_id": level.asset_id,
        "budgets": {"maximum_loaded_cells": 100, "memory_mb": 1000,
                    "io_mb_per_second": 100, "maximum_requests": 10},
    })
    assert not [row for row in api.validate_world_asset(partition.asset_id) if row["severity"] == "error"]
    artifact = api.compile_world_asset(partition.asset_id, quality="low")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["runtime"]["budgets"]["maximum_loaded_cells"] == 50
    assert payload["runtime"]["budgets"]["memory_mb"] == 500

    editor = DedicatedAssetEditor(tmp_path, database)
    assert editor.open_asset(partition.asset_id)
    assert editor.pages.count() == len(editor_pages_for_asset("tc.world_partition"))
    assert editor.compile(silent=True)


def test_interactive_terrain_and_foliage_brushes_persist_editable_data(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    terrain = api.create_world_asset("tc.terrain", "BrushTerrain", properties={
        "resolution": [17, 17], "height_scale": 100.0,
        "erosion": {"mode": "none", "iterations": 0},
    })
    original = api.preview_world_asset(terrain.asset_id)["heights"]
    sculpted = api.sculpt_terrain(terrain.asset_id, center=(0.5, 0.5), radius=0.2, strength=1.0)
    assert sculpted["source"] == "painted" and sculpted["edit_revision"] == 1
    assert api.preview_world_asset(terrain.asset_id)["heights"] != original
    painted = api.paint_terrain_layer(terrain.asset_id, "Mud", center=(0.5, 0.5), radius=0.25, strength=0.7)
    assert max(painted["layer_weights"]["Mud"]) > 0.0

    mesh = api.create_asset("tc.data", "BushMesh", folder="Assets/Test")
    foliage = api.create_world_asset("tc.foliage_type", "Bush", properties={"mesh_asset_id": mesh.asset_id})
    placed = api.paint_foliage(foliage.asset_id, center=(0.5, 0.5), radius=0.3, density=4.0, seed=9)
    assert placed["manual_instances"]
    erased = api.paint_foliage(foliage.asset_id, center=(0.5, 0.5), radius=1.0, erase=True)
    assert not erased["manual_instances"]


def test_world_build_previews_cover_navigation_lighting_partition_and_hlod() -> None:
    navigation = build_navigation_preview({"tile_size": 1000.0, "agents": [{"name": "Human"}]}, extent=(2500, 1800))
    assert (navigation["columns"], navigation["rows"], len(navigation["tiles"])) == (3, 2, 6)
    lighting = build_lighting_preview({"lightmap_resolution": 128, "source_level_ids": ["a", "b"], "reflection_captures": [{}, {}]})
    assert len(lighting["stages"]) == 5 and lighting["reflection_capture_count"] == 2
    partition = build_partition_preview({"cell_size": 1000, "loading_range": 800, "streaming_sources": [{"x": 500, "z": 500}]}, extent=(3000, 3000))
    assert len(partition["cells"]) == 9 and 0 < partition["loaded_cells"] < 9
    hlod = build_hlod_preview({"reduction_ratio": 0.2}, source_triangles=50000)
    assert hlod["proxy_triangles"] == 10000 and hlod["triangle_reduction_percent"] == 80.0


def test_world_authoring_widget_edits_and_completes_lighting_build(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = WorldAssetService(tmp_path, database)
    terrain = service.create("tc.terrain", "Interactive", properties={"resolution": [9, 9], "erosion": {"mode": "none"}})
    widget = WorldAssetAuthoringWidget(service, terrain.asset_id, "tc.terrain")
    widget.load_settings(service.properties(terrain.asset_id)); widget._stroke(0.5, 0.5, False)
    assert widget.settings()["edit_revision"] == 1
    assert not widget.canvas.grab().isNull()

    lighting = service.create("tc.lighting_scenario", "Day")
    light_widget = WorldAssetAuthoringWidget(service, lighting.asset_id, "tc.lighting_scenario")
    light_widget.load_settings(service.properties(lighting.asset_id)); light_widget.start_lighting_build()
    light_widget._build_timer.stop()
    for _ in range(6): light_widget._advance_build()
    assert light_widget.settings()["last_build"]["status"] == "complete"
