from __future__ import annotations

from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel


def test_joint_editor_supports_multi_edit_duplicate_and_undo_redo() -> None:
    runtime: dict = {}
    model = PhysicsJointEditorModel(runtime)
    model.create("left", "Root", "Left", preset="ragdoll")
    model.create("right", "Root", "Right", preset="ragdoll")
    model.selected_ids = ["left", "right"]
    assert model.edit_selected({"damping": 0.8}) == 2
    assert all(joint["damping"] == 0.8 for joint in model.joints)
    copies = model.duplicate_selected()
    assert len(copies) == 2
    assert model.undo() is True
    assert len(model.joints) == 2
    assert model.redo() is True
    assert len(model.joints) == 4


def test_joint_editor_builds_limit_and_motor_visual_guides() -> None:
    model = PhysicsJointEditorModel({})
    model.create("door", "Frame", "Door", preset="door_hinge", settings={
        "motor_enabled": True, "motor_target_velocity": 2.0,
    })
    guides = model.visual_guides({"Frame": [0, 1, 0], "Door": [1, 1, 0]})
    assert guides[0]["first_anchor"] == (0.0, 1.0, 0.0)
    assert len(guides[0]["limit_arc"]) == 33
    assert guides[0]["motor_enabled"] is True


def test_continuous_joint_handle_edit_is_one_undo_operation() -> None:
    model = PhysicsJointEditorModel({})
    model.create("drag", "A", "B")
    model.begin_interaction()
    model.preview_selected({"first_anchor": [1.0, 0.0, 0.0]})
    model.preview_selected({"first_anchor": [2.0, 0.0, 0.0]})
    assert model.end_interaction()
    assert model.joints[0]["first_anchor"] == [2.0, 0.0, 0.0]
    assert model.undo()
    assert model.joints[0]["first_anchor"] == [0.0, 0.0, 0.0]
