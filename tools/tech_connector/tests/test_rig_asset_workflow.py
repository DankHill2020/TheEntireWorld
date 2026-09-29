from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import TCEditorAPI, automatic_chain_mapping, automatic_ik_chains, builtin_asset_type_registry
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor


BONES = [
    {"name": "pelvis", "parent": ""}, {"name": "spine", "parent": "pelvis"}, {"name": "head", "parent": "spine"},
    {"name": "upperarm_l", "parent": "spine"}, {"name": "lowerarm_l", "parent": "upperarm_l"}, {"name": "hand_l", "parent": "lowerarm_l"},
    {"name": "upperarm_r", "parent": "spine"}, {"name": "lowerarm_r", "parent": "upperarm_r"}, {"name": "hand_r", "parent": "lowerarm_r"},
    {"name": "thigh_l", "parent": "pelvis"}, {"name": "calf_l", "parent": "thigh_l"}, {"name": "foot_l", "parent": "calf_l"},
    {"name": "thigh_r", "parent": "pelvis"}, {"name": "calf_r", "parent": "thigh_r"}, {"name": "foot_r", "parent": "calf_r"},
]


def test_rig_asset_types_use_graph_only_where_it_fits() -> None:
    registry = builtin_asset_type_registry()
    assert registry.require("tc.control_rig").node_graph_kind == "control_rig"
    assert registry.require("tc.ik_rig").node_graph_kind == ""
    assert registry.require("tc.ik_retargeter").node_graph_kind == ""


def test_automatic_ik_chains_and_mapping_are_semantic() -> None:
    chains = automatic_ik_chains(BONES)
    assert {item["name"] for item in chains} >= {"Left Arm", "Right Arm", "Left Leg", "Right Leg", "Spine"}
    mapping = automatic_chain_mapping(chains, chains)
    assert len(mapping) == len(chains)
    assert all(item["source"] == item["target"] for item in mapping)


def test_python_api_creates_dependency_closed_rig_family_and_cooks(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir()
    editor = TCEditorAPI(project)
    source_skeleton = editor.create_asset("tc.skeleton", "SourceSkeleton", properties={"bones": BONES})
    target_skeleton = editor.create_asset("tc.skeleton", "TargetSkeleton", properties={"bones": BONES})
    control = editor.create_control_rig("HeroControlRig", skeleton_id=target_skeleton.asset_id)
    source_ik = editor.create_ik_rig("SourceIK", skeleton_id=source_skeleton.asset_id, bones=BONES, retarget_root="pelvis")
    target_ik = editor.create_ik_rig("TargetIK", skeleton_id=target_skeleton.asset_id, bones=BONES, retarget_root="pelvis")
    retargeter = editor.create_ik_retargeter("SourceToTarget", source_ik_rig_id=source_ik.asset_id, target_ik_rig_id=target_ik.asset_id)
    for asset in (control, source_ik, target_ik, retargeter):
        assert not [item for item in editor.validate_rig_asset(asset.asset_id) if item["severity"] == "error"]
    receipt = editor.cook([control.asset_id, retargeter.asset_id], platform="windows", quality="high")
    assert {control.asset_id, source_ik.asset_id, target_ik.asset_id, retargeter.asset_id}.issubset(receipt.asset_ids)
    cooked = editor.database.derived(retargeter.asset_id, "ik_retargeter_runtime:windows:high")
    assert cooked is not None
    assert json.loads(cooked.path.read_text(encoding="utf-8"))["schema"] == "tech_connector.cooked_ik_retargeter.v1"


def test_dedicated_rig_editors_have_graph_chain_and_mapping_surfaces(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "Project"; project.mkdir(); editor = TCEditorAPI(project)
    skeleton = editor.create_asset("tc.skeleton", "Skeleton", properties={"bones": BONES})
    control = editor.create_control_rig("Control", skeleton_id=skeleton.asset_id)
    ik = editor.create_ik_rig("IK", skeleton_id=skeleton.asset_id, bones=BONES)
    target = editor.create_ik_rig("TargetIK", skeleton_id=skeleton.asset_id, bones=BONES)
    retarget = editor.create_ik_retargeter("Retarget", source_ik_rig_id=ik.asset_id, target_ik_rig_id=target.asset_id)
    workspace = DedicatedAssetEditor(project, editor.database)
    assert workspace.open_asset(control.asset_id) and workspace.pages.tabText(0) == "Rig Graph"
    assert workspace.open_asset(ik.asset_id) and workspace.pages.tabText(0) == "Chains & Goals"
    assert workspace.open_asset(retarget.asset_id) and workspace.pages.tabText(0) == "Chain Mapping"
