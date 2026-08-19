from __future__ import annotations

import pytest

from tech_connector.services.dcc.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.services.dcc.rig_evaluation_service import evaluate_rig_graph
from tech_connector.services.dcc.rigging_host_adapter_service import create_rigging_adapter
from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    REQUIRED_BODY_SLOTS,
    RIGGING_CAPABILITIES,
    RiggingWorkspaceController,
    auto_map_character,
    validate_character_definition,
)


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def _humanoid_graph() -> tuple[EditableRigGraph, CharacterDefinition]:
    graph = EditableRigGraph()
    slots = {}

    def add(slot: str, name: str, parent: str = "", position=(0.0, 0.0, 0.0)) -> str:
        joint = graph.add_joint(name, parent_id=parent, joint_id=name, local_matrix=_matrix(*position))
        slots[slot] = joint
        return joint

    root = add("Reference", "root")
    hips = add("Hips", "pelvis", root, (0, 10, 0))
    spine = add("Spine", "spine_01", hips, (0, 4, 0))
    neck = add("Neck", "neck_01", spine, (0, 6, 0))
    add("Head", "head", neck, (0, 3, 0))
    left_arm = add("LeftArm", "l_upperarm", spine, (4, 4, 0))
    left_forearm = add("LeftForeArm", "l_forearm", left_arm, (5, 0, 0))
    add("LeftHand", "l_hand", left_forearm, (5, 0, 0))
    right_arm = add("RightArm", "r_upperarm", spine, (-4, 4, 0))
    right_forearm = add("RightForeArm", "r_forearm", right_arm, (-5, 0, 0))
    add("RightHand", "r_hand", right_forearm, (-5, 0, 0))
    left_leg = add("LeftUpLeg", "l_thigh", hips, (2, -4, 0))
    left_knee = add("LeftLeg", "l_knee", left_leg, (0, -6, 0))
    add("LeftFoot", "l_ankle", left_knee, (0, -6, 1))
    right_leg = add("RightUpLeg", "r_thigh", hips, (-2, -4, 0))
    right_knee = add("RightLeg", "r_knee", right_leg, (0, -6, 0))
    add("RightFoot", "r_ankle", right_knee, (0, -6, 1))
    return graph, CharacterDefinition("Hero", slots=slots)


def test_capability_contract_covers_create_rig_and_retarget_workflows() -> None:
    required = {
        "definition.auto_map", "definition.assign_slot", "definition.set_reference_pose",
        "rig.build_full", "rig.build_module", "rig.remove_module", "rig.rebuild_module",
        "rig.create_ik_fk_limb", "rig.create_reverse_foot", "rig.create_ribbon",
        "rig.create_twist", "rig.create_space_switch", "rig.create_mesh_attachment",
        "rig.create_face_module", "rig.store_connections", "rig.restore_connections",
        "retarget.create_definition", "retarget.solve_pose", "retarget.preview",
        "retarget.bake", "retarget.transfer_take",
    }
    assert required <= set(RIGGING_CAPABILITIES)


def test_auto_mapping_is_host_neutral_and_validates_hierarchy() -> None:
    graph, _definition = _humanoid_graph()
    adapter = create_rigging_adapter("tc", graph=graph)

    mapped = auto_map_character(adapter.scene_joints(), name="Mapped")
    validation = validate_character_definition(mapped, adapter.scene_joints())

    assert set(REQUIRED_BODY_SLOTS) <= set(mapped.slots)
    assert validation.ok, validation.to_dict()
    assert mapped.slots["LeftForeArm"] == "l_forearm"
    assert mapped.slots["RightFoot"] == "r_ankle"


def test_validation_rejects_semantically_wrong_limb_hierarchy() -> None:
    graph, definition = _humanoid_graph()
    definition.slots["LeftHand"] = "r_hand"

    validation = validate_character_definition(
        definition, create_rigging_adapter("tc", graph=graph).scene_joints()
    )

    assert not validation.ok
    assert "LeftHand is not below LeftForeArm" in validation.hierarchy_errors


def test_tc_adapter_builds_and_rebuilds_portable_modules() -> None:
    graph, definition = _humanoid_graph()
    controller = RiggingWorkspaceController(create_rigging_adapter("tech_connector", graph=graph))

    result = controller.run(
        "rig.build_full",
        definition=definition.to_dict(),
        modules=["root", "spine", "left_arm", "right_leg"],
        options={},
    )

    assert result.ok, result.message
    assert "left_arm_ik_solver" in graph.constraints
    assert "right_leg_ik_solver" in graph.constraints
    assert any((node.get("attributes") or {}).get("rig_module") == "spine" for node in graph.nodes.values())

    rebuilt = controller.run(
        "rig.rebuild_module", module="left_arm", definition=definition.to_dict(), options={}
    )
    assert rebuilt.ok, rebuilt.message
    assert rebuilt.removed_ids
    assert "left_arm_ik_solver" in graph.constraints


def test_tc_space_switch_updates_constraint_weights() -> None:
    graph, _definition = _humanoid_graph()
    world = graph.add_node("World", "dag.control", node_id="world_ctrl")
    chest = graph.add_node("Chest", "dag.control", node_id="chest_ctrl")
    hand = graph.add_node("Hand", "dag.control", node_id="hand_ctrl")
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))

    created = controller.run(
        "rig.create_space_switch", driven=hand, targets=[world, chest], names=["World", "Chest"], mode="parent"
    )
    switch_id = created.data["space_switch"]
    changed = controller.run("rig.set_space", space_switch=switch_id, space="Chest")

    assert created.ok and changed.ok
    assert graph.constraints[switch_id]["settings"]["weights"] == [0.0, 1.0]


def test_reference_pose_and_retarget_definition_round_trip() -> None:
    graph, definition = _humanoid_graph()
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))

    imported = controller.run("definition.import", definition=definition.to_dict())
    captured = controller.run("definition.set_reference_pose", definition=definition.to_dict())
    retarget = controller.run("retarget.create_definition", mapping=captured.data["definition"], name="Hero")

    assert imported.ok and captured.ok and retarget.ok
    restored = CharacterDefinition.from_dict(retarget.data["definition"])
    assert restored.reference_pose
    assert restored.slots == definition.slots


def test_public_rigging_cmds_uses_the_same_host_neutral_controller() -> None:
    from tech_connector import rigging_cmds

    graph, definition = _humanoid_graph()
    controller = rigging_cmds.session("tc", graph=graph)
    result = rigging_cmds.build_module(controller, module="spine", definition=definition.to_dict(), options={})

    assert result["ok"]
    assert result["host"] == "tech_connector"
    assert rigging_cmds.capabilities("tc", graph=graph)["rig.build_full"] == "native"


def test_tc_point_constraint_respects_selected_axes() -> None:
    graph = EditableRigGraph()
    source = graph.add_node("Source", "dag.transform", node_id="source", attributes={"translate": [8, 9, 10]})
    target = graph.add_node("Target", "dag.transform", node_id="target", attributes={"translate": [1, 2, 3]})
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))
    result = controller.run(
        "rig.create_constraint", type="point", drivers=[source], driven=target, axes=["x"], offset=False,
    )
    evaluated = evaluate_rig_graph(graph)

    assert result.ok and evaluated.errors == []
    assert evaluated.world_matrices[target][12:15] == [8.0, 2.0, 3.0]


def test_tc_point_constraint_maintain_offset_preserves_pose_then_follows_driver() -> None:
    graph = EditableRigGraph()
    source = graph.add_node("Source", "dag.transform", node_id="source", attributes={"translate": [8, 9, 10]})
    target = graph.add_node("Target", "dag.transform", node_id="target", attributes={"translate": [1, 2, 3]})
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))

    created = controller.run(
        "rig.create_constraint", type="point", drivers=[source], driven=target, axes=["x", "y", "z"], offset=True,
    )
    initial = evaluate_rig_graph(graph)
    graph.nodes[source]["attributes"]["translate"] = [9, 11, 13]
    moved = evaluate_rig_graph(graph)

    assert created.ok and initial.errors == [] and moved.errors == []
    assert initial.world_matrices[target][12:15] == pytest.approx([1.0, 2.0, 3.0])
    assert moved.world_matrices[target][12:15] == pytest.approx([2.0, 4.0, 6.0])


def test_tc_aim_constraint_uses_maya_style_aim_and_world_up_vectors() -> None:
    graph = EditableRigGraph()
    source = graph.add_node("Aim Source", "dag.transform", node_id="aim_source", attributes={"translate": [0, 10, 0]})
    target = graph.add_node("Aim Target", "dag.transform", node_id="aim_target", attributes={"translate": [0, 0, 0]})
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))
    result = controller.run(
        "rig.create_constraint",
        type="aim",
        drivers=[source],
        driven=target,
        aim_vector=[1, 0, 0],
        up_vector=[0, 1, 0],
        world_up_vector=[0, 0, 1],
        offset=False,
    )
    evaluated = evaluate_rig_graph(graph)
    aim_axis = evaluated.world_matrices[target][0:3]

    assert result.ok and evaluated.errors == []
    assert abs(aim_axis[0]) < 1.0e-6
    assert aim_axis[1] > 0.999
    assert abs(aim_axis[2]) < 1.0e-6


def test_tc_pose_reader_evaluates_driver_rotation_locally() -> None:
    graph = EditableRigGraph()
    driver = graph.add_node(
        "Shoulder", "dag.transform", node_id="shoulder", attributes={"rotate": [45.0, 0.0, 0.0]}
    )
    controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=graph))
    created = controller.run(
        "rig.create_pose_reader", driver=driver, axis="x", range=[0.0, 90.0], name="shoulder_raise_reader"
    )
    evaluated = evaluate_rig_graph(graph)

    assert created.ok and evaluated.errors == []
    assert abs(evaluated.attributes["shoulder_raise_reader"]["angle"] - 45.0) < 1.0e-5
    assert abs(evaluated.attributes["shoulder_raise_reader"]["output"] - 0.5) < 1.0e-5
    assert controller.capability_status()["rig.create_pose_reader"] == "native"
