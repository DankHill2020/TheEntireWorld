from __future__ import annotations

from tech_connector.game_engine.assets import AssetDatabase
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI


def test_editor_python_api_covers_runtime_joint_editing_and_stress_scenes(tmp_path) -> None:
    api = TCEditorAPI(tmp_path, database=AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3"))
    runtime: dict = {}
    joint = api.create_runtime_physics_joint(runtime, "door", "Frame", "Door", preset="door_hinge")
    assert joint["type"] == "hinge"
    assert api.edit_runtime_physics_joints(runtime, ("door",), {"damping": 0.75}) == 1
    assert runtime["physics_joints"][0]["damping"] == 0.75
    assert api.remove_runtime_physics_joint(runtime, "door")
    stress = api.build_physics_stress_scene("chain", count=32)
    assert stress["audit"]["ready"] is True
    assert "generate_runtime_ragdoll" in api.capability_contract()["physics_operations"]
