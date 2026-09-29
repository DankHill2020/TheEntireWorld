from __future__ import annotations

import base64
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    TCEditorAPI,
    compile_skin_binding_payload,
    generate_bone_lods,
    recommended_mesh_lods,
)
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor


BONES = [
    {"name": "pelvis", "parent": ""},
    {"name": "spine", "parent": "pelvis"},
    {"name": "upperarm_l", "parent": "spine"},
    {"name": "lowerarm_l", "parent": "upperarm_l"},
    {"name": "hand_l", "parent": "lowerarm_l"},
    {"name": "finger_l_01", "parent": "hand_l"},
    {"name": "finger_l_02", "parent": "finger_l_01"},
    {"name": "weapon_socket", "parent": "hand_l"},
]


SKIN_PAYLOAD = {
    "schema": "tech_connector.skin_weights.v1",
    "topology": {"vertex_count": 2, "face_count": 0, "fingerprint": "demo"},
    "cluster": {
        "influences": [{"name": "pelvis"}, {"name": "spine"}, {"name": "hand_l"}, {"name": "finger_l_01"}],
        "vertex_weights": [
            {"vertex_index": 0, "weights": {"pelvis": 0.5, "spine": 0.3, "hand_l": 0.15, "finger_l_01": 0.05}},
            {"vertex_index": 1, "weights": {"pelvis": 0.97, "finger_l_01": 0.03}},
        ],
        "max_influences": 4,
        "normalize": True,
    },
}


def test_recommended_mesh_lods_include_geometry_skin_and_bone_budgets() -> None:
    lods = recommended_mesh_lods(4)
    assert [item["triangle_percent"] for item in lods] == [100.0, 50.0, 25.0, 12.5]
    assert [item["max_influences"] for item in lods] == [8, 4, 4, 2]
    assert [item["bone_lod"] for item in lods] == [0, 1, 2, 3]


def test_bone_lods_preserve_gameplay_bones_and_remap_removed_details() -> None:
    lods = generate_bone_lods(BONES, count=4, preserve_bones=["weapon_socket"])
    assert set(lods[0]["retained_bones"]) == {item["name"] for item in BONES}
    assert "finger_l_02" in lods[2]["removed_bones"]
    assert lods[2]["parent_remap"]["finger_l_02"] == "hand_l"
    assert "weapon_socket" in lods[3]["retained_bones"]
    assert lods[3]["evaluation_rate_divisor"] == 4


def test_mobile_skin_cook_is_compact_and_does_not_mutate_source_weights() -> None:
    properties = {
        "mesh_id": "mesh", "skeleton_id": "skeleton", "topology": SKIN_PAYLOAD["topology"],
        **SKIN_PAYLOAD["cluster"], "performance_profile": "balanced", "platform_overrides": {"android": "mobile"},
    }
    original = json.loads(json.dumps(properties["vertex_weights"]))
    cooked = json.loads(compile_skin_binding_payload(properties, platform="android", quality="high"))
    assert cooked["layout"]["fixed_influence_width"] == 2
    assert cooked["layout"]["joint_index_bits"] == 8
    assert cooked["performance"]["bytes_per_vertex"] == 6
    assert len(base64.b64decode(cooked["buffers"]["weights"])) == 2 * 2 * 2
    assert properties["vertex_weights"] == original


def test_character_python_pipeline_tracks_dependencies_lods_and_runtime_buffers(tmp_path) -> None:
    project = tmp_path / "Project"; project.mkdir()
    editor = TCEditorAPI(project)
    skeleton = editor.create_asset("tc.skeleton", "HeroSkeleton", properties={"bones": BONES, "preserve_bones": ["weapon_socket"]})
    mesh = editor.create_skeletal_mesh_asset("HeroMesh", skeleton_id=skeleton.asset_id, bones=BONES, preserve_bones=["weapon_socket"])
    skin = editor.create_skin_binding("HeroSkin", mesh_id=mesh.asset_id, skeleton_id=skeleton.asset_id, dcc_payload=SKIN_PAYLOAD)
    editor.assign_skin_binding(mesh.asset_id, skin.asset_id)
    editor.set_properties(skin.asset_id, {"platform_overrides": {"android": "mobile"}})
    assert not [item for item in editor.validate_character_asset(mesh.asset_id) if item["severity"] == "error"]
    assert not [item for item in editor.validate_character_asset(skin.asset_id) if item["severity"] == "error"]
    receipt = editor.cook([mesh.asset_id], platform="android", quality="high")
    assert set(receipt.asset_ids) == {skeleton.asset_id, mesh.asset_id, skin.asset_id}
    artifact = editor.database.derived(skin.asset_id, "skin_binding_runtime:android:high")
    assert artifact is not None
    assert json.loads(artifact.path.read_text(encoding="utf-8"))["profile"]["name"] == "mobile"


def test_skeletal_mesh_editor_exposes_combined_mesh_and_bone_lods(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "Project"; project.mkdir()
    editor = TCEditorAPI(project)
    skeleton = editor.create_asset("tc.skeleton", "Skeleton")
    mesh = editor.create_skeletal_mesh_asset("Mesh", skeleton_id=skeleton.asset_id, bones=BONES)
    workspace = DedicatedAssetEditor(project, editor.database)
    assert workspace.open_asset(mesh.asset_id)
    assert "LODs & Bone LODs" in [workspace.pages.tabText(index) for index in range(workspace.pages.count())]
