from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.tc_physics_joint_service import (
    create_physics_joint,
    remove_physics_joint,
)


def test_joint_presets_are_editable_and_replace_by_stable_id() -> None:
    runtime: dict = {}
    joint = create_physics_joint(runtime, "door", "Frame", "Door", preset="door_hinge")

    assert joint["type"] == "hinge"
    assert joint["limits_enabled"] is True
    assert joint["axis"] == [0.0, 1.0, 0.0]

    replacement = create_physics_joint(
        runtime, "door", "Frame", "Door", preset="door_hinge", settings={"motor_enabled": True},
    )
    assert runtime["physics_joints"] == [replacement]
    assert replacement["motor_enabled"] is True
    assert remove_physics_joint(runtime, "door") is True
    assert remove_physics_joint(runtime, "door") is False


def test_joint_authoring_rejects_invalid_contracts() -> None:
    with pytest.raises(ValueError, match="different"):
        create_physics_joint({}, "bad", "Body", "Body")
    with pytest.raises(ValueError, match="Unsupported"):
        create_physics_joint({}, "bad", "A", "B", joint_type="teleport")
    with pytest.raises(ValueError, match="Unknown physics joint preset"):
        create_physics_joint({}, "bad", "A", "B", preset="magic")
    with pytest.raises(ValueError, match="non-zero"):
        create_physics_joint({}, "bad", "A", "B", settings={"axis": [0.0, 0.0, 0.0]})
    with pytest.raises(ValueError, match="Unknown physics joint properties"):
        create_physics_joint({}, "bad", "A", "B", settings={"stifness": 0.5})


def test_joint_authoring_normalizes_axes_and_limit_order() -> None:
    joint = create_physics_joint(
        {}, "slide", "Rail", "Carriage", joint_type="slider",
        settings={"axis": [10.0, 0.0, 0.0], "minimum_limit": 4.0, "maximum_limit": -2.0},
    )
    assert joint["axis"] == [1.0, 0.0, 0.0]
    assert (joint["minimum_limit"], joint["maximum_limit"]) == (-2.0, 4.0)
