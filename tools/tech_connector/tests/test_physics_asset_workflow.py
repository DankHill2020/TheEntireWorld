from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import TCEditorAPI, automatic_physics_asset, builtin_asset_type_registry
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor


JOINTS = {
    "pelvis": {"parent_id": "", "local_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1]},
    "thigh_l": {"parent_id": "pelvis", "local_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -0.2, -0.4, 0, 1], "attributes": {"joint_role": "thigh"}},
    "knee_l": {"parent_id": "thigh_l", "local_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -0.45, 0, 1], "attributes": {"joint_role": "knee"}},
    "ankle_l": {"parent_id": "knee_l", "local_matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -0.4, 0, 1]},
}


def test_physics_assets_are_direct_first_class_types() -> None:
    registry = builtin_asset_type_registry()
    physics = registry.require("tc.physics_asset")
    constraint = registry.require("tc.physics_constraint")
    assert physics.standard_editor_name == "Physics Asset Editor"
    assert physics.node_graph_kind == ""
    assert physics.python_api_namespace == "editor.physics"
    assert constraint.standard_editor_name == "Physics Constraint Editor"


def test_auto_generation_uses_runtime_ragdoll_contract() -> None:
    receipt = automatic_physics_asset(JOINTS, root_joint="pelvis", preset="heavy")
    assert receipt.body_count == 3
    assert receipt.constraint_count == 2
    assert {value["bone"] for value in receipt.bodies} == {"pelvis", "thigh_l", "knee_l"}
    knee = next(value for value in receipt.constraints if value["id"] == "RagdollJoint::knee_l")
    assert knee["type"] == "hinge"


def test_python_api_creates_valid_physics_assets_and_cooks(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    editor = TCEditorAPI(project)
    skeleton = editor.create_asset("tc.skeleton", "HeroSkeleton")
    mesh = editor.create_asset("tc.skeletal_mesh", "HeroMesh")
    physics = editor.create_physics_asset("HeroPhysics", skeleton_id=skeleton.asset_id, skeletal_mesh_id=mesh.asset_id)
    setup = editor.auto_setup_physics_asset(physics.asset_id, JOINTS, root_joint="pelvis")
    assert setup["body_count"] == 3
    assert not editor.validate_physics(physics.asset_id)
    editor.cook([physics.asset_id], platform="windows", quality="hero")
    artifact = editor.database.derived(physics.asset_id, "physics_asset_runtime:windows:hero")
    assert artifact is not None
    cooked = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert cooked["schema"] == "tech_connector.cooked_physics_asset.v1"
    assert len(cooked["constraints"]) == 2


def test_constraint_asset_has_complete_python_and_editor_path(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    editor = TCEditorAPI(project)
    constraint = editor.create_physics_constraint(
        "Door", first_body="Frame", second_body="Door", preset="door_hinge",
        settings={"break_torque": 250.0},
    )
    assert not editor.validate_physics(constraint.asset_id)
    assert "create_physics_constraint" in editor.capability_contract()["physics_operations"]
    QApplication.instance() or QApplication([])
    workspace = DedicatedAssetEditor(project, editor.database)
    assert workspace.open_asset(constraint.asset_id)
    assert workspace.pages.tabText(0) == "Constraint Setup"
