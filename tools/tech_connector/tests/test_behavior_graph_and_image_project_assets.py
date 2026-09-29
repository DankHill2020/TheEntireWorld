from __future__ import annotations

import json

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI


def _set_ready_program() -> dict:
    return {
        "schema": "tech_connector.engine_graph_program.v1",
        "program_id": "set_ready", "display_name": "Set Ready", "entry_event": "On Begin Play", "version": 1,
        "flow": ["set"],
        "nodes": [{
            "node_id": "set", "operation": "variable.set", "display_name": "Set Ready",
            "inputs": {"name": {"mode": "literal", "literal": "ready"},
                       "value": {"mode": "literal", "literal": True}},
            "output_name": "result", "position": [0, 0], "enabled": True,
        }],
    }


def test_behavior_and_gameplay_graphs_execute_and_cook_deterministically(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    for creator in (api.create_behavior, api.create_gameplay_graph):
        asset = creator("Ready", program=_set_ready_program())
        assert api.validate_behavior_graph(asset.asset_id) == []
        result = api.execute_behavior_graph(asset.asset_id)
        assert result["status"] == "complete"
        assert result["runtime_state"]["metadata"]["variables"]["ready"] is True
        first = api.cook_behavior_graph(asset.asset_id, platform="windows").path.read_bytes()
        second = api.cook_behavior_graph(asset.asset_id, platform="windows").path.read_bytes()
        assert second == first
        assert json.loads(first)["manifest"]["abi"] == "tc_graph_c_v1"


def test_image_project_uses_ophanim_schema_and_flattens_deterministically(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    asset = api.create_image_project("Icon", width=16, height=16, layers=[
        {"name": "Background", "color": [10, 20, 30, 255]},
        {"name": "Accent", "color": [80, 140, 255, 180], "opacity": 0.75, "blend_mode": "Screen"},
    ])
    record = api.database.asset(asset.asset_id)
    assert record is not None
    document = json.loads(record.source_path.read_text(encoding="utf-8"))
    assert document["schema"] == "tech_connector_image_project_v1"
    assert api.validate_image_project(asset.asset_id) == []
    first = api.flatten_image_project(asset.asset_id)
    second = api.cook_image_project(asset.asset_id, platform="windows").path.read_bytes()
    assert first == second
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert api.cook_image_project(asset.asset_id, platform="windows").path.read_bytes() == second


def test_new_asset_operations_are_in_python_capability_contract(tmp_path) -> None:
    contract = TCEditorAPI(tmp_path).capability_contract()
    assert set(contract["behavior_graph_operations"]) == {
        "create_behavior", "create_gameplay_graph", "validate_behavior_graph", "cook_behavior_graph", "execute_behavior_graph",
    }
    assert set(contract["image_project_operations"]) == {
        "create_image_project", "validate_image_project", "flatten_image_project", "cook_image_project",
    }
