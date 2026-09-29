from __future__ import annotations

import json

import pytest

from tech_connector.game_engine.assets import (
    TCEditorAPI,
    automatic_cloth_maps,
    builtin_asset_type_registry,
    fabric_preset,
)
from tech_connector.game_engine.runtime.tc_cloth_authoring_service import (
    apply_cloth_property_maps,
)
from tech_connector.game_engine.runtime.tc_simulation_service import create_cloth_grid
from tech_connector.game_engine.runtime.tc_engine_api import engine


def test_cloth_is_direct_asset_not_mandatory_node_graph() -> None:
    registry = builtin_asset_type_registry()
    cloth = registry.require("tc.cloth")
    fabric = registry.require("tc.fabric_material")

    assert cloth.standard_editor_name == "Cloth Editor"
    assert cloth.suite_name == "Loom"
    assert cloth.node_graph_kind == ""
    assert cloth.python_api_namespace == "editor.cloth"
    assert fabric.standard_editor_name == "Fabric Material Editor"


def test_automatic_setup_layers_simulation_over_imported_skinning() -> None:
    receipt = automatic_cloth_maps(
        5, fixed_vertices=[0], transition_vertices={1: 0.25, 2: 0.75}, max_distance=2.0,
    )

    assert receipt.preserved_imported_skinning
    assert receipt.property_maps["skin_simulation"] == [0.0, 0.25, 0.75, 1.0, 1.0]
    assert receipt.property_maps["animation_drive"] == [1.0, 0.75, 0.25, 0.0, 0.0]
    assert receipt.property_maps["max_distance"] == [0.0, 0.5, 1.5, 2.0, 2.0]


def test_runtime_skin_simulation_map_creates_hard_and_soft_attachments() -> None:
    world = create_cloth_grid(2, 2, spacing=0.25)
    apply_cloth_property_maps(world, {"skin_simulation": [0.0, 0.5, 1.0, 1.0]})

    assert world.particles[0].pinned
    assert not world.particles[1].pinned
    assert any(item.tag == "cloth_pin_map" and item.particle == 1 for item in world.attachments)
    assert [particle.effect_attributes["cloth_skin_simulation"] for particle in world.particles] == [0.0, 0.5, 1.0, 1.0]


def test_python_api_creates_valid_cloth_and_cooks_dependency_closed_manifest(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    editor = TCEditorAPI(project)
    mesh = editor.create_asset("tc.skeletal_mesh", "CoatMesh")
    skin = editor.create_asset("tc.skin_binding", "CoatSkin")
    fabric = editor.create_fabric_material("HeavyDenim", preset="denim")
    cloth = editor.create_cloth(
        "CoatCloth",
        source_mesh_id=mesh.asset_id,
        skin_binding_id=skin.asset_id,
        fabric_material_id=fabric.asset_id,
        vertex_count=4,
        fixed_vertices=[0],
    )

    properties = editor.properties(cloth.asset_id)
    assert properties["preserve_imported_skinning"] is True
    assert properties["property_maps"]["skin_simulation"] == [0.0, 1.0, 1.0, 1.0]
    assert not [item for item in editor.validate_cloth(cloth.asset_id, vertex_count=4) if item["severity"] == "error"]

    receipt = editor.cook([cloth.asset_id], platform="windows", quality="hero")
    artifact = editor.database.derived(cloth.asset_id, "cloth_runtime:windows:hero")
    assert artifact is not None and artifact.path.is_file()
    cooked = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert cooked["preserve_imported_skinning"] is True
    assert set(receipt.asset_ids) == {mesh.asset_id, skin.asset_id, fabric.asset_id, cloth.asset_id}


def test_fabric_presets_are_editable_physical_values() -> None:
    silk = fabric_preset("silk")
    denim = fabric_preset("denim")
    assert silk["density"] < denim["density"]
    assert silk["bend_stiffness"] < denim["bend_stiffness"]
    with pytest.raises(KeyError):
        fabric_preset("unobtainium")


def test_engine_exposes_same_project_editor_api_to_python(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    editor = engine.editor(project)
    contract = editor.capability_contract()
    assert contract["ui_api_parity"] is True
    assert "set_cloth_map" in contract["cloth_operations"]
