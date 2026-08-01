from __future__ import annotations

from tech_connector.services.conversation_workspace_service import resolve_reference
from tech_connector.engine.providers import _extract_ranked_symbol_rows


def _workspace(*, selected: bool) -> dict:
    entity_ids = ["file_a", "file_b", "file_c", "file_d", "file_e"]
    return {
        "entities": {
            entity_id: {
                "entity_id": entity_id,
                "kind": "file",
                "ref": f"C:/project/{entity_id}.py",
                "name": f"{entity_id}.py",
            }
            for entity_id in entity_ids
        },
        "selected_entity_sets": {"file": entity_ids if selected else []},
        "result_frames": [
            {
                "frame_id": "latest",
                "selected_entity_ids": entity_ids,
                "primary_entity_ids": entity_ids,
            }
        ],
    }


def test_file_ordinals_resolve_against_ranked_selected_results() -> None:
    workspace = _workspace(selected=True)

    assert resolve_reference(workspace, "the top file", kind="file").entity_id == "file_a"
    assert resolve_reference(workspace, "the second file", kind="file").entity_id == "file_b"
    assert resolve_reference(workspace, "the middle file", kind="file").entity_id == "file_c"
    assert resolve_reference(workspace, "the bottom file", kind="file").entity_id == "file_e"


def test_file_ordinals_resolve_against_latest_result_frame() -> None:
    workspace = _workspace(selected=False)

    assert resolve_reference(workspace, "the second file", kind="file").entity_id == "file_b"
    assert resolve_reference(workspace, "the last file", kind="file").entity_id == "file_e"


def test_nested_project_index_output_preserves_ranked_callable_order() -> None:
    answer = """
Matching indexed functions:
1. `maya_tools/Rigging/create_rig.py`
   - `create_rig_from_mapping(body_joint_map, face_joint_map)` on line `4109`
   - `create_full_rig(arm_joints, leg_joints)` on line `3852`
2. `maya_tools/Rigging/mocap/setup_hik.py`
   - `create_rig_mapping(root_joint)` on line `738`
"""

    assert _extract_ranked_symbol_rows(answer) == [
        {
            "symbol": "create_rig_from_mapping",
            "file": "maya_tools/Rigging/create_rig.py",
        },
        {
            "symbol": "create_full_rig",
            "file": "maya_tools/Rigging/create_rig.py",
        },
        {
            "symbol": "create_rig_mapping",
            "file": "maya_tools/Rigging/mocap/setup_hik.py",
        },
    ]
