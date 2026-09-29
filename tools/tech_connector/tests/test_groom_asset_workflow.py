from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    HAIR_MATERIAL_PRESETS, automatic_groom_lods, builtin_asset_type_registry,
    hair_material_preset, project_groom_roots, validate_groom_properties,
)
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.asset_specialized_editors import (
    GroomBindingEditorWidget, GroomEditorWidget, HairMaterialEditorWidget,
)


GROUP = {"name": "Scalp", "preset": "scalp", "curve_count": 12000, "point_count": 192000, "guide_count": 1200}


def test_automatic_groom_lods_transition_from_strands_to_cards_and_mesh() -> None:
    lods = automatic_groom_lods(count=6)
    assert len(lods) == 6
    assert lods[0]["geometry_type"] == "strands"
    assert "cards" in {lod["geometry_type"] for lod in lods}
    assert lods[-1]["geometry_type"] == "mesh"
    assert [lod["screen_size"] for lod in lods] == sorted((lod["screen_size"] for lod in lods), reverse=True)
    assert [lod["curve_decimation"] for lod in lods] == sorted((lod["curve_decimation"] for lod in lods), reverse=True)
    assert lods[0]["simulation"] is True and lods[-1]["simulation"] is False


def test_root_projection_caches_triangle_barycentrics_and_distance() -> None:
    projections = project_groom_roots(
        [(0.25, 0.25, 0.1), (0.8, 0.1, 0.0)],
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
    )
    assert projections[0]["triangle"] == 0
    assert projections[0]["barycentric"] == pytest.approx([0.5, 0.25, 0.25])
    assert projections[0]["surface_position"] == pytest.approx([0.25, 0.25, 0.0])
    assert projections[0]["distance"] == pytest.approx(0.1)
    assert sum(projections[1]["barycentric"]) == pytest.approx(1.0)


def test_groom_validation_requires_guides_for_simulation() -> None:
    properties = {"groups": [{"name": "Scalp", "curve_count": 10, "point_count": 40, "guide_count": 0,
                               "width_mm": 0.07, "simulation": {"enabled": True, "solver": "angular_spring"}}],
                  "lods": automatic_groom_lods(count=2), "cards": {"entries": []}}
    assert "missing_guides" in {issue.code for issue in validate_groom_properties(properties)}


def test_hair_material_presets_are_physical_and_editable() -> None:
    assert {"black_hair", "brown_hair", "blonde_hair", "red_hair", "gray_hair", "fur"} <= set(HAIR_MATERIAL_PRESETS)
    blonde = hair_material_preset("blonde_hair")
    assert blonde["melanin"] < hair_material_preset("black_hair")["melanin"]
    assert 0.0 <= blonde["roughness"] <= 1.0


def test_python_api_creates_projects_and_dependency_cooks_groom_family(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    skeleton = api.create_asset("tc.skeleton", "HeroSkeleton")
    mesh = api.create_skeletal_mesh_asset("HeroMesh", skeleton_id=skeleton.asset_id)
    material = api.create_hair_material("Brown Hair", preset="brown_hair", overrides={"random_hue": 0.035})
    groom = api.create_groom("Hero Groom", groups=[GROUP], material_ids=[material.asset_id], lod_count=5)
    binding = api.create_groom_binding("Hero Groom Binding", groom_id=groom.asset_id, target_skeletal_mesh_id=mesh.asset_id)
    projections = api.project_groom_binding(
        binding.asset_id, [(0.2, 0.2, 0.02)],
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [(0, 1, 2)],
    )
    assert projections[0]["distance"] == pytest.approx(0.02)
    assert not [issue for issue in api.validate_groom(groom.asset_id) if issue["severity"] == "error"]
    assert not [issue for issue in api.validate_groom(binding.asset_id) if issue["severity"] == "error"]
    receipt = api.cook([binding.asset_id], platform="windows", quality="high")
    assert set(receipt.asset_ids) == {skeleton.asset_id, mesh.asset_id, material.asset_id, groom.asset_id, binding.asset_id}
    artifact = api.database.derived(groom.asset_id, "groom_runtime:windows:high")
    assert artifact is not None
    assert json.loads(artifact.path.read_bytes())["schema"] == "tech_connector.groom_runtime.v1"
    assert "project_groom_binding" in api.capability_contract()["groom_operations"]


def test_groom_family_has_first_class_types_and_dedicated_editors(tmp_path) -> None:
    registry = builtin_asset_type_registry()
    assert registry.require("tc.groom").standard_editor_name == "Groom Editor"
    assert registry.require("tc.groom_binding").standard_editor_name == "Groom Binding Editor"
    assert registry.require("tc.hair_material").python_api_namespace == "editor.groom"
    QApplication.instance() or QApplication([])
    api = TCEditorAPI(tmp_path)
    skeleton = api.create_asset("tc.skeleton", "Skeleton")
    mesh = api.create_skeletal_mesh_asset("Mesh", skeleton_id=skeleton.asset_id)
    material = api.create_hair_material("Hair")
    groom = api.create_groom("Groom", groups=[GROUP], material_ids=[material.asset_id])
    binding = api.create_groom_binding("Binding", groom_id=groom.asset_id, target_skeletal_mesh_id=mesh.asset_id)
    for asset_id, widget_type in ((groom.asset_id, GroomEditorWidget), (binding.asset_id, GroomBindingEditorWidget),
                                  (material.asset_id, HairMaterialEditorWidget)):
        editor = DedicatedAssetEditor(tmp_path, api.database)
        assert editor.open_asset(asset_id)
        assert any(isinstance(widget, widget_type) for _key, widget in editor._specialized_widgets)

