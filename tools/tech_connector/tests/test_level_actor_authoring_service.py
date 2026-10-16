from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene


def _actor(actor_id: str, name: str) -> dict:
    return {
        "entity_id": actor_id,
        "name": name,
        "visible": True,
        "editor_locked": False,
        "parent_entity_id": "",
        "transform": {
            "position": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        },
        "components": [
            {"component_id": f"{actor_id}-transform", "type": "transform"},
            {"component_id": f"{actor_id}-camera", "type": "camera"},
            {"component_id": f"{actor_id}-collider", "type": "collider"},
        ],
    }


def test_saved_level_actor_operations_match_editor_workflows(tmp_path: Path) -> None:
    api = TCEditorAPI(tmp_path)
    level = api.create_asset("tc.level", "L_Authoring", folder="Assets/Levels")
    level_path = Path(level.destination_path)
    document, blobs = load_federated_scene(level_path)
    document.metadata["runtime_world"] = {"entities": [_actor("actor-a", "A"), _actor("actor-b", "B")]}
    save_federated_scene(level_path, document, blobs=blobs)

    api.set_level_actor_lock(level.asset_id, ["actor-b"], True)
    receipt = api.transform_level_actors(level.asset_id, ["actor-a", "actor-b"], translation=(2, 0, 0))
    assert receipt["actor_ids"] == ("actor-a",)
    assert {row["entity_id"]: row for row in api.level_actors(level.asset_id)}["actor-b"]["transform"]["position"] == [0.0, 0.0, 0.0]

    api.set_level_actor_lock(level.asset_id, ["actor-b"], False)
    api.move_level_actors_to_folder(level.asset_id, ["actor-a", "actor-b"], "Gameplay/Heroes")
    api.parent_level_actors(level.asset_id, ["actor-b"], "actor-a")
    with pytest.raises(ValueError, match="cycle"):
        api.parent_level_actors(level.asset_id, ["actor-a"], "actor-b")

    api.reorder_level_actor_component(level.asset_id, "actor-b", "actor-b-collider", 1)
    duplicate = api.duplicate_level_actors(level.asset_id, ["actor-a", "actor-b"])
    assert duplicate["changed_count"] == 2
    assert set(duplicate["actor_ids"]).isdisjoint({"actor-a", "actor-b"})

    api.set_level_actor_visibility(level.asset_id, ["actor-a"], False)
    api.isolate_level_actors(level.asset_id, ["actor-b"])
    api.show_all_level_actors(level.asset_id)
    api.save_level_camera_bookmark(level.asset_id, 3, {
        "eye": [1.0, 2.0, 3.0], "target": [0.0, 0.0, 0.0], "up": [0.0, 1.0, 0.0],
    })
    api.delete_level_actors(level.asset_id, ["actor-a"])

    document, _blobs = load_federated_scene(level_path)
    world = document.metadata["runtime_world"]
    actors = {row["entity_id"]: row for row in world["entities"]}
    assert "actor-a" not in actors
    assert actors["actor-b"]["parent_entity_id"] == ""
    assert actors["actor-b"]["editor_folder"] == "Gameplay/Heroes"
    assert [row["type"] for row in actors["actor-b"]["components"]] == ["transform", "collider", "camera"]
    assert all(row["visible"] for row in actors.values())
    assert world["editor_camera_bookmarks"]["3"]["eye"] == [1.0, 2.0, 3.0]
    assert "level_actor_operations" in api.capability_contract()
