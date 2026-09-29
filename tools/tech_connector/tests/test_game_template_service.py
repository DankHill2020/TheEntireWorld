from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.input_map_service import audit_input_map
from tech_connector.game_engine.assets.starter_character_service import generate_starter_mannequin_geometry
from tech_connector.game_engine.runtime.tc_player_build_service import compile_tcscene_for_runtime
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene
from tech_connector.ui.game_engine.game_template_dialog import GameTemplateDialog, TEMPLATE_ROLE, VARIANT_ROLE


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_playable_sandbox_creates_dependency_closed_ready_project(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)

    receipt = api.create_game_project_from_template(
        project_name="Starter", template_id="playable_sandbox", visual_style="pixel_8bit",
    )

    assert receipt["ready_to_play"] is True
    assert receipt["validation"]["issues"] == []
    assert len(receipt["created_asset_ids"]) == 15
    assert {api.database.asset(asset_id).asset_type for asset_id in receipt["created_asset_ids"]} == {
        "tc.input_map", "tc.animation_controller", "tc.physics_scene", "tc.prefab", "tc.level",
        "tc.game_ruleset", "tc.build_profile",
        "tc.skeleton", "tc.skeletal_mesh", "tc.skin_binding",
        "tc.material", "tc.texture", "tc.ik_rig", "tc.control_rig", "tc.physics_asset",
    }
    assert set(api.database.dependencies(receipt["ruleset_asset_id"])) == {
        receipt["level_asset_id"], receipt["player_prefab_asset_id"],
        receipt["input_map_asset_id"], receipt["physics_scene_asset_id"],
        receipt["locomotion_controller_asset_id"],
        receipt["skeleton_asset_id"], receipt["skeletal_mesh_asset_id"], receipt["skin_binding_asset_id"],
        receipt["character_material_asset_id"], receipt["ik_rig_asset_id"], receipt["character_physics_asset_id"],
        receipt["character_texture_asset_id"],
        receipt["control_rig_asset_id"],
    }
    assert set(receipt["validation"]["build_plan"]["asset_ids"]) == {
        receipt["level_asset_id"], receipt["player_prefab_asset_id"],
        receipt["input_map_asset_id"], receipt["physics_scene_asset_id"],
        receipt["locomotion_controller_asset_id"],
        receipt["skeleton_asset_id"], receipt["skeletal_mesh_asset_id"], receipt["skin_binding_asset_id"],
        receipt["character_material_asset_id"], receipt["ik_rig_asset_id"], receipt["character_physics_asset_id"],
        receipt["character_texture_asset_id"],
        receipt["control_rig_asset_id"],
    }

    level = api.database.asset(receipt["level_asset_id"])
    assert level is not None
    document, blobs = load_federated_scene(level.source_path)
    assert document.metadata["template_source"]["template_id"] == "playable_sandbox"
    assert document.metadata["presentation_profile"]["visual_style"] == "pixel_8bit"
    assert document.metadata["presentation_compile_plan"]["internal_resolution"] == [320, 180]
    assert document.metadata["starter_character"]["presentation_variant"] == "pixel_8bit"
    assert blobs
    runtime = document.metadata["runtime_world"]
    assert any(entity.get("role") == "player" for entity in runtime["entities"])
    assert any(entity.get("role") == "walkable_surface" for entity in runtime["entities"])
    assert any(entity.get("camera", {}).get("active") for entity in runtime["entities"])
    assert any(entity.get("light") for entity in runtime["entities"])
    compiled_manifest = Path(receipt["validation"]["runtime_compile"]["runtime_manifest"])
    manifest = compiled_manifest.read_text(encoding="utf-8")
    deterministic_manifest = compile_tcscene_for_runtime(
        level.source_path, tmp_path / ".tech_connector" / "determinism" / "main.tcruntime",
    ).runtime_manifest
    assert deterministic_manifest.read_bytes() == compiled_manifest.read_bytes()
    assert "GRAPH\ttick\tplayer_move\tcharacter.move" in manifest
    assert "GRAPH\ttick\tplayer_jump\tcharacter.jump" in manifest
    assert "GRAPH\ttick\tcamera_follow\tcamera.follow" in manifest
    assert "GRAPH\ttick\tlocomotion_animation\tanimation.locomotion" in manifest
    assert "SKELETON\ttc.skeleton.scene" in manifest
    assert "ANIMATION\ttc_idle" in manifest
    assert "ANIMATION\ttc_walk" in manifest
    assert "ANIMATION\ttc_walk_forward_right" in manifest
    assert "ANIMATION\ttc_walk_backward_left" in manifest
    assert "ANIMATION\ttc_start_forward" in manifest
    assert "ANIMATION\ttc_crouch_walk" in manifest
    assert "tc_starter_mannequin_albedo_v1.png" in manifest
    assert "SKIN\ttc_starter::tc_starter_biped::tc_starter_mannequin" in manifest
    assert "CAMERA\tRuntimeCamera" in manifest
    assert "LIGHT\tSun" in manifest
    assert "COLLIDER\tGround" in manifest


@pytest.mark.parametrize(
    ("template_id", "variant_id"),
    [
        ("third_person", "exploration"), ("third_person", "combat"),
        ("first_person", "shooter"), ("side_scroller", "platformer"),
        ("fighting", "versus"),
    ],
)
def test_every_catalog_variant_is_instantiable_and_has_conflict_free_input(
    tmp_path: Path, template_id: str, variant_id: str,
) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_game_project_from_template(
        template_id=template_id, variant_id=variant_id,
        project_name=f"{template_id}_{variant_id}",
    )

    assert receipt["ready_to_play"] is True
    assert audit_input_map(api.properties(receipt["input_map_asset_id"])).valid is True


def test_play_readiness_explains_a_missing_camera(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_game_project_from_template(project_name="BrokenCamera")
    level = api.database.asset(receipt["level_asset_id"])
    assert level is not None
    document, blobs = load_federated_scene(level.source_path)
    document.metadata["runtime_world"]["entities"] = [
        entity for entity in document.metadata["runtime_world"]["entities"] if not entity.get("camera")
    ]
    save_federated_scene(level.source_path, document, blobs=blobs)

    validation = api.validate_playable_project(receipt["ruleset_asset_id"], receipt["build_profile_asset_id"])

    assert validation["ready_to_play"] is False
    assert "missing_active_camera" in {issue["code"] for issue in validation["issues"]}


def test_generation_rolls_back_partial_assets_when_a_destination_exists(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    existing = api.create_asset("tc.level", "L_Collision_Default", folder="Assets/Levels")

    with pytest.raises(FileExistsError):
        api.create_game_project_from_template(project_name="Collision")

    remaining = api.database.list_assets()
    assert [record.asset_id for record in remaining] == [existing.asset_id]
    assert not (tmp_path / "Assets" / "Input" / "IM_Collision.input.tcasset").exists()
    assert not (tmp_path / "Assets" / "Physics" / "PS_Collision.physics.tcasset").exists()
    assert not (tmp_path / "Assets" / "Gameplay" / "Players" / "PF_Collision_Player.tcprefab").exists()
    assert not (tmp_path / "Assets" / "Animation" / "Locomotion" / "AC_Collision_Locomotion.animgraph.tcasset").exists()
    assert not (tmp_path / "Assets" / "Characters" / "Starter" / "Source" / "Collision_Mannequin_standard.obj").exists()


def test_python_api_advertises_project_template_parity(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    catalog = api.available_game_templates()
    contract = api.capability_contract()

    assert {row["qualified_id"] for row in catalog} >= {
        "playable_sandbox/standard", "third_person/exploration", "first_person/shooter",
        "side_scroller/platformer", "fighting/versus",
    }
    assert contract["project_template_operations"] == [
        "available_game_templates", "create_game_project_from_template", "validate_playable_project",
    ]
    assert contract["locomotion_operations"] == [
        "create_locomotion_controller", "validate_locomotion_controller", "cook_locomotion_controller",
    ]
    assert contract["starter_character_operations"] == ["create_starter_character"]


def test_starter_character_api_creates_editable_rig_mesh_skin_and_lods(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_starter_character("DemoHero", dimensionality="2.5d")

    assert receipt["presentation_variant"] == "side_2_5d"
    assert receipt["vertex_count"] > 100
    assert receipt["triangle_count"] > 150
    assert receipt["bone_count"] > 70
    assert Path(receipt["mesh_source_path"]).is_file()
    skeleton = api.properties(receipt["skeleton_asset_id"])
    mesh = api.properties(receipt["skeletal_mesh_asset_id"])
    skin = api.properties(receipt["skin_binding_asset_id"])
    assert len(skeleton["bones"]) == receipt["bone_count"]
    assert len(mesh["lods"]) == 3
    assert mesh["active_presentation_variant"] == "side_2_5d"
    assert {item["target_id"] for item in mesh["morph_targets"]} == {
        "jaw_open", "smile", "blink_l", "blink_r", "brow_raise_l", "brow_raise_r",
    }
    assert api.database.asset(receipt["texture_asset_id"]).source_path.is_file()
    assert len(skin["vertex_weights"]) == receipt["vertex_count"]
    assert all(2 <= len(row["weights"]) <= 4 for row in skin["vertex_weights"])
    assert all(abs(sum(row["weights"].values()) - 1.0) < 1.0e-6 for row in skin["vertex_weights"])
    source = Path(receipt["mesh_source_path"]).read_text(encoding="utf-8")
    assert "\nvt " in source and "\nvn " in source
    assert api.validate_character_asset(receipt["skeletal_mesh_asset_id"]) == []
    assert api.validate_character_asset(receipt["skin_binding_asset_id"]) == []
    assert api.validate_rig_asset(receipt["ik_rig_asset_id"]) == []
    assert api.validate_rig_asset(receipt["control_rig_asset_id"]) == []
    assert api.validate_physics(receipt["physics_asset_id"]) == []
    assert api.cook_character_asset(receipt["skeletal_mesh_asset_id"]).path.is_file()
    assert api.cook_character_asset(receipt["skin_binding_asset_id"]).path.is_file()
    assert api.cook_rig_asset(receipt["ik_rig_asset_id"]).path.is_file()
    assert api.cook_rig_asset(receipt["control_rig_asset_id"]).path.is_file()
    assert api.cook_physics(receipt["physics_asset_id"]).path.is_file()


def test_starter_character_v2_surface_is_watertight_and_four_weight_skinned() -> None:
    geometry = generate_starter_mannequin_geometry()
    edge_counts: dict[tuple[int, int], int] = {}
    for first, second, third in geometry.triangles:
        for edge in ((first, second), (second, third), (third, first)):
            key = tuple(sorted(edge))
            edge_counts[key] = edge_counts.get(key, 0) + 1

    assert len(geometry.vertices) > 4000
    assert all(count == 2 for count in edge_counts.values())
    assert len(geometry.normals) == len(geometry.vertices)
    assert len(geometry.uvs) == len(geometry.vertices)
    assert all(len(influences) == 4 for influences in geometry.influences)


def test_side_scroller_uses_plane_constrained_skinned_mannequin(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    receipt = api.create_game_project_from_template(
        template_id="side_scroller", variant_id="platformer", project_name="SideHero",
    )
    level = api.database.asset(receipt["level_asset_id"])
    document, _ = load_federated_scene(level.source_path)
    runtime = document.metadata["runtime_world"]
    player = next(entity for entity in runtime["entities"] if entity.get("role") == "player")

    assert document.metadata["starter_character"]["presentation_variant"] == "side_2_5d"
    assert runtime["movement_constraints"] == {"player": "Player", "locked_axis": "z", "plane_origin": 0.0}
    assert player["render"]["skin_binding"]
    assert player["render"]["presentation_variant"] == "side_2_5d"


def test_locomotion_controller_has_complete_movement_animation_and_camera_contract(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    controller = api.create_locomotion_controller("AC_Hero", preset="third_person")
    properties = api.properties(controller.asset_id)

    assert api.validate_locomotion_controller(controller.asset_id) == []
    assert properties["movement"]["acceleration"] > 0
    assert properties["movement"]["jump_impulse"] > 0
    assert properties["camera"]["follow_smoothing"] > 0
    assert {row["id"] for row in properties["state_machine"]["states"]} == {
        "idle", "walk_run", "jump_start", "airborne", "land", "crouch_idle", "crouch_move",
    }
    assert {"idle", "walk_forward", "run_forward", "jump_start", "jump_loop", "land"} <= set(
        properties["animation_slots"]
    )
    cooked = api.cook_locomotion_controller(controller.asset_id)
    assert cooked.path.suffix == ".tclocomotion"


def test_starter_game_dialog_exposes_choices_and_uses_python_api(tmp_path: Path, qapp) -> None:
    dialog = GameTemplateDialog(tmp_path)
    for index in range(dialog.template_list.count()):
        item = dialog.template_list.item(index)
        if item.data(TEMPLATE_ROLE) == "side_scroller" and item.data(VARIANT_ROLE) == "platformer":
            dialog.template_list.setCurrentItem(item)
            break
    dialog.name_edit.setText("PixelPlatformer")
    dialog.visual_style_combo.setCurrentIndex(dialog.visual_style_combo.findData("pixel_8bit"))

    dialog._create()

    assert dialog.result() == QDialog.Accepted
    assert dialog.receipt is not None
    assert dialog.receipt["ready_to_play"] is True
    assert dialog.receipt["template_id"] == "side_scroller"
    assert dialog.receipt["visual_style"] == "pixel_8bit"
