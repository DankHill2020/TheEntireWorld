from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.services.dcc.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.services.dcc.rig_evaluation_service import rig_runtime_capabilities
from tech_connector.services.dcc.rig_evaluation_service import evaluate_rig_graph
from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    REQUIRED_BODY_SLOTS,
    validate_character_definition,
)
from tech_connector.services.dcc.tc_hik_ui_host import (
    bind_tc_hik_host,
    create_rig,
    rig_template,
    setup_hik,
    skinning_utils,
)


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def _humanoid_graph() -> EditableRigGraph:
    graph = EditableRigGraph()

    def add(name: str, parent: str = "", position=(0.0, 0.0, 0.0)) -> str:
        return graph.add_joint(
            name, parent_id=parent, joint_id=name, local_matrix=_matrix(*position)
        )

    root = add("root")
    hips = add("pelvis", root, (0, 10, 0))
    spine = add("spine_01", hips, (0, 4, 0))
    neck = add("neck_01", spine, (0, 6, 0))
    add("head", neck, (0, 3, 0))
    for side, sign in (("l", 1), ("r", -1)):
        shoulder = add(f"{side}_clavicle", spine, (sign * 2, 3, 0))
        arm = add(f"{side}_upperarm", shoulder, (sign * 4, 0, 0))
        forearm = add(f"{side}_forearm", arm, (sign * 5, 0, 0))
        add(f"{side}_hand", forearm, (sign * 4, 0, 0))
        thigh = add(f"{side}_thigh", hips, (sign * 2, -4, 0))
        knee = add(f"{side}_knee", thigh, (0, -6, 0))
        ankle = add(f"{side}_ankle", knee, (0, -6, 1))
        add(f"{side}_ball", ankle, (0, -1, 2))
    add("l_brow1", "head", (1, 1, 1))
    add("r_brow1", "head", (-1, 1, 1))
    graph.add_node("source_mesh", "dag.mesh", node_id="source_mesh")
    graph.add_node("target_mesh", "dag.mesh", node_id="target_mesh")
    return graph


def _body_map(graph: EditableRigGraph) -> dict:
    return setup_hik.guess_joint_map_from_root("root", setup_hik.DEFAULT_JOINT_MAP)


def test_literal_hik_ui_builds_tc_modules_and_automatic_spaces() -> None:
    from maya_tools.Rigging.mocap.hik_ui import launch_hik_ui

    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    app = QApplication.instance() or QApplication([])
    window = launch_hik_ui(graph=graph, selection_provider=lambda: ["root"])
    mapping = window.guess_joint_map_from_root("root")
    for slot, row in mapping.items():
        if row.get("joint"):
            window.fields[slot] = row["joint"]

    for module in ("Root / Origin", "Pelvis & Hips", "Spine", "Left Arm", "Left Leg"):
        window.create_body_module_setup(module, silent=True)

    assert window.host_mode == "tech_connector"
    assert window.tabs.count() == 2
    assert "left_arm_ik_solver" in graph.constraints
    assert "left_leg_ik_solver" in graph.constraints
    assert any(
        (item.get("settings") or {}).get("auto_space_switch") == "left_arm"
        for item in graph.constraints.values()
    )
    assert "dag.control" not in rig_runtime_capabilities(graph)["unsupported_local_node_types"]
    window.close()
    app.processEvents()


def test_tc_limb_stretch_is_zero_to_one_and_zero_preserves_legacy_solution() -> None:
    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    create_rig.rig_arm_module("l", _body_map(graph))

    switch_attrs = graph.nodes["left_arm_switch_ctrl"]["attributes"]
    assert switch_attrs["stretch"] == 0.0
    assert switch_attrs["stretch_min"] == 0.0
    assert switch_attrs["stretch_max"] == 1.0
    assert graph.nodes["left_arm_switch_ctrl"]["attribute_specs"]["stretch"]["type"] == "float"

    solver = graph.constraints["left_arm_ik_solver"]
    assert solver["settings"]["measurement"] == "per_segment_distance"
    assert len(solver["settings"]["distance_segments"]) == 2
    baseline = evaluate_rig_graph(graph)
    stretch_settings = {
        key: solver["settings"].pop(key)
        for key in ("stretch_control_id", "stretch_attribute", "rest_upper_length", "rest_lower_length")
    }
    legacy = evaluate_rig_graph(graph)
    solver["settings"].update(stretch_settings)
    assert baseline.world_matrices["l_hand"] == legacy.world_matrices["l_hand"]

    target_matrix = list(graph.nodes["left_arm_ik_ctrl"]["attributes"]["matrix"])
    target_matrix[12:15] = [30.0, 14.0, 0.0]
    graph.nodes["left_arm_ik_ctrl"]["attributes"]["matrix"] = target_matrix
    switch_attrs["stretch"] = 0.0
    rigid = evaluate_rig_graph(graph)
    switch_attrs["stretch"] = 1.0
    stretched = evaluate_rig_graph(graph)

    target = target_matrix[12:15]
    rigid_end = rigid.world_matrices["l_hand"][12:15]
    stretched_end = stretched.world_matrices["l_hand"][12:15]
    rigid_error = sum((rigid_end[index] - target[index]) ** 2 for index in range(3))
    stretched_error = sum((stretched_end[index] - target[index]) ** 2 for index in range(3))
    assert stretched_error < rigid_error


def test_tc_spine_stretch_requires_three_contiguous_joints_and_is_zero_safe() -> None:
    graph = EditableRigGraph()
    root = graph.add_joint("root", joint_id="root", local_matrix=_matrix(0, 0, 0))
    hips = graph.add_joint("pelvis", parent_id=root, joint_id="pelvis", local_matrix=_matrix(0, 10, 0))
    first = graph.add_joint("spine_01", parent_id=hips, joint_id="spine_01", local_matrix=_matrix(0, 4, 0))
    second = graph.add_joint("spine_02", parent_id=first, joint_id="spine_02", local_matrix=_matrix(0, 4, 0))
    third = graph.add_joint("spine_03", parent_id=second, joint_id="spine_03", local_matrix=_matrix(0, 4, 0))
    body = {
        "Hips": {"joint": hips},
        "Spine": {"joint": first},
        "Spine1": {"joint": second},
        "Spine2": {"joint": third},
    }
    bind_tc_hik_host(graph)
    create_rig.rig_pelvis_module(body)
    create_rig.rig_spine_module(body)

    pelvis_attrs = graph.nodes["pelvis_Hips_ctrl"]["attributes"]
    assert pelvis_attrs["stretch"] == 0.0
    assert pelvis_attrs["stretch_min"] == 0.0
    assert pelvis_attrs["stretch_max"] == 1.0
    assert graph.nodes["pelvis_Hips_ctrl"]["attribute_specs"]["stretch"]["type"] == "float"
    solver = graph.constraints.pop("spine_stretch_solver")
    assert solver["settings"]["measurement"] == "per_segment_distance"
    assert len(solver["settings"]["rest_lengths"]) == 2
    legacy = evaluate_rig_graph(graph)
    graph.constraints["spine_stretch_solver"] = solver
    zero_stretch = evaluate_rig_graph(graph)
    assert zero_stretch.errors == []
    assert zero_stretch.world_matrices[third] == legacy.world_matrices[third]
    top_control = "spine_Spine2_ctrl"
    top_matrix = list(graph.nodes[top_control]["attributes"]["matrix"])
    top_matrix[13] += 6.0
    graph.nodes[top_control]["attributes"]["matrix"] = top_matrix
    pelvis_attrs["stretch"] = 1.0
    stretched = evaluate_rig_graph(graph)
    assert stretched.errors == []
    for joint_id, control_id in zip(
        (first, second, third),
        ("spine_Spine_ctrl", "spine_Spine1_ctrl", top_control),
    ):
        assert stretched.world_matrices[joint_id][12:15] == stretched.world_matrices[control_id][12:15]
    create_rig.remove_spine_module(body)
    assert "spine_stretch_solver" not in graph.constraints


def test_side_specific_face_modules_remove_independently() -> None:
    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    face = setup_hik.DEFAULT_FACE_JOINT_MAP.copy()
    face["LeftBrow"] = {"index": 0, "joints": ["l_brow1"]}
    face["RightBrow"] = {"index": 1, "joints": ["r_brow1"]}

    create_rig.rig_brows_module("l", face)
    create_rig.rig_brows_module("r", face)
    assert any((node.get("attributes") or {}).get("rig_module") == "l_brows" for node in graph.nodes.values())
    assert any((node.get("attributes") or {}).get("rig_module") == "r_brows" for node in graph.nodes.values())

    create_rig.remove_brows_module("l", face)
    assert not any((node.get("attributes") or {}).get("rig_module") == "l_brows" for node in graph.nodes.values())
    assert any((node.get("attributes") or {}).get("rig_module") == "r_brows" for node in graph.nodes.values())


def test_portable_mouth_module_survives_cleanup_and_removes_cleanly() -> None:
    graph = _humanoid_graph()
    lip_joints = []
    for name, position in (
        ("c_upper_lip", (0, 13, 1)),
        ("r_lip_corner1", (-2, 12, 1)),
        ("c_lower_lip", (0, 11, 1)),
        ("l_lip_corner1", (2, 12, 1)),
    ):
        lip_joints.append(graph.add_joint(name, parent_id="head", joint_id=name, local_matrix=_matrix(*position)))
    jaw = graph.add_joint("jaw", parent_id="head", joint_id="jaw", local_matrix=_matrix(0, 11, 0))
    face = {
        "LipChain": {"joints": lip_joints},
        "UpperLipCenter": {"joint": "c_upper_lip"},
        "LowerLipCenter": {"joint": "c_lower_lip"},
        "LeftLipCorner": {"joint": "l_lip_corner1"},
        "RightLipCorner": {"joint": "r_lip_corner1"},
        "Jaw": {"joint": jaw},
    }
    bind_tc_hik_host(graph)

    result = create_rig.rig_mouth_module(face)
    created = set(result["created_ids"])
    assert created
    assert all(node in graph.nodes for node in created)

    assert create_rig.delete_unused_scaffold_nodes() == 0
    assert all(node in graph.nodes for node in created)

    # Removal also counts the control constraints owned by the mouth module.
    assert create_rig.remove_mouth_module(face) >= len(created)
    assert not created.intersection(graph.nodes)


def test_surface_rig_accepts_the_literal_ui_signature() -> None:
    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    result = create_rig.setup_surface_rig_with_drivers(
        joint_list=["spine_01", "neck_01"],
        loft_name="neck_ribbon",
        offset=0.75,
        driver_follicle_indices=[0, 1],
        side="c",
        region="neck",
    )
    assert result["ok"]
    assert len(result["created_ids"]) == 2


def test_tc_ribbon_uses_lengthwise_uvs_and_continuous_transport_frames() -> None:
    graph = EditableRigGraph()
    first = graph.add_joint("surface_01", joint_id="surface_01", local_matrix=_matrix(0, 0, 0))
    second = graph.add_joint("surface_02", parent_id=first, joint_id="surface_02", local_matrix=_matrix(0, 10, 0))
    third = graph.add_joint("surface_03", parent_id=second, joint_id="surface_03", local_matrix=_matrix(2, 10, 1))
    bind_tc_hik_host(graph)

    result = create_rig.setup_surface_rig_with_drivers(
        joint_list=[first, second, third], loft_name="stable_surface", offset=1.5,
    )
    assert [graph.constraints[item]["target_id"] for item in result["created_ids"]] == [first, second, third]
    settings = [graph.constraints[item]["settings"] for item in result["created_ids"]]
    assert [row["u"] for row in settings] == [0.5, 0.5, 0.5]
    assert [row["v"] for row in settings] == [0.0, 0.5, 1.0]
    assert all(row["frame_method"] == "parallel_transport" for row in settings)

    grid = settings[0]["control_grid"]
    width_vectors = [
        [row[1][axis] - row[0][axis] for axis in range(3)]
        for row in grid
    ]
    assert all(
        sum(first[axis] * second[axis] for axis in range(3)) > 0.0
        for first, second in zip(width_vectors, width_vectors[1:])
    )
    evaluated = evaluate_rig_graph(graph)
    assert evaluated.errors == []
    first_aim = evaluated.world_matrices[first][:3]
    assert abs(first_aim[1]) > 0.99


def test_packaged_tc_biped_template_loads_complete_hik_skeleton_with_namespace() -> None:
    graph = EditableRigGraph()
    checkpoints = []
    bind_tc_hik_host(graph, undo_callback=checkpoints.append)

    result = rig_template.load_biped_rig_template(namespace="Hero")
    mapped = {
        slot: row["joint"] for slot, row in result["joint_map"].items() if row.get("joint")
    }
    definition = CharacterDefinition("Hero", slots=mapped)
    validation = validate_character_definition(definition, _scene_joint_rows(graph))

    assert set(REQUIRED_BODY_SLOTS) <= set(mapped)
    assert validation.ok, validation.to_dict()
    assert result["new_node_count"] >= 100
    assert result["finger_joint_count"] == 48
    assert result["roll_joint_count"] == 8
    assert mapped["Reference"] == "Hero:tc_root"
    assert result["face_map"]["TongueChain"]["joints"][-1] == "Hero:tc_tongue_03"
    assert checkpoints == ["Load TC biped skeleton template"]
    assert graph.metadata["rig_templates"][0]["template_id"] == "tc_biped_v1"

    second = rig_template.load_biped_rig_template(namespace="Background")
    assert second["joint_map"]["Hips"]["joint"] == "Background:tc_hips"


def test_literal_ui_loads_tc_template_and_populates_mapping_fields() -> None:
    from maya_tools.Rigging.mocap.hik_ui import launch_hik_ui

    graph = EditableRigGraph()
    app = QApplication.instance() or QApplication([])
    window = launch_hik_ui(graph=graph, selection_provider=lambda: [])
    window.rig_template_namespace_field.setText("UIHero")
    with patch("PySide6.QtWidgets.QMessageBox.information", return_value=0), patch(
        "PySide6.QtWidgets.QMessageBox.critical", return_value=0
    ):
        result = window.load_biped_rig_template(reference=False)

    assert result["template_id"] == "tc_biped_v1"
    assert window.fields["Hips"] == "UIHero:tc_hips"
    assert window.default_face_map["LeftBrow"]["joints"][0] == "UIHero:tc_l_brow_01"
    assert window.rig_template_path_field.text().endswith("tc_biped_v1.tcrig.json")
    window.close()
    app.processEvents()


def test_literal_ui_surface_action_builds_stable_ribbon() -> None:
    from maya_tools.Rigging.mocap.hik_ui import launch_hik_ui

    graph = EditableRigGraph()
    first = graph.add_joint("curve_01", joint_id="curve_01", local_matrix=_matrix(0, 0, 0))
    second = graph.add_joint("curve_02", parent_id=first, joint_id="curve_02", local_matrix=_matrix(0, 8, 0))
    third = graph.add_joint("curve_03", parent_id=second, joint_id="curve_03", local_matrix=_matrix(2, 8, 1))
    app = QApplication.instance() or QApplication([])
    window = launch_hik_ui(graph=graph, selection_provider=lambda: [first, second, third])
    window.surf_name_field.setText("ui_stable_ribbon")
    window.surf_indices_field.setText("0, 1, 2")
    window.create_surface_rig_with_drivers()

    ribbons = [item for item in graph.constraints.values() if item.get("type") == "ribbon"]
    assert len(ribbons) == 3
    assert all((item.get("settings") or {}).get("frame_method") == "parallel_transport" for item in ribbons)
    window.close()
    app.processEvents()


def _scene_joint_rows(graph: EditableRigGraph) -> list[dict]:
    from tech_connector.services.dcc.tc_rigging_host_adapter import TCRiggingHostAdapter

    return TCRiggingHostAdapter(graph).scene_joints()


def test_tc_skin_weights_export_import_and_transfer(tmp_path) -> None:
    graph = _humanoid_graph()
    selection = ["source_mesh"]
    bind_tc_hik_host(graph, selection_provider=lambda: list(selection))
    skin_id = graph.add_skin("source_mesh", ["pelvis", "spine_01"], skin_id="source_skin")
    graph.set_vertex_weights(skin_id, 0, {"pelvis": 0.75, "spine_01": 0.25})

    exported = skinning_utils.export_skin_weights(["source_mesh"], str(tmp_path))
    assert len(exported) == 1
    graph.skins.clear()
    assert skinning_utils.import_skin_weights(["source_mesh"], str(tmp_path)) == ["source_skin"]

    selection[:] = ["source_mesh", "target_mesh"]
    result = skinning_utils.transfer_skin_weights_from_selection()
    assert result["skinCluster"] == "target_mesh_skin"
    assert graph.skins["target_mesh_skin"]["weight_overrides"]["0"]["pelvis"] == 0.75


def test_removing_module_removes_owned_control_constraints() -> None:
    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    body = _body_map(graph)
    create_rig.rig_arm_module("l", body)
    create_rig.create_arm_space_switches("l", body)
    create_rig.remove_arm_module("l", body)

    assert not any((node.get("attributes") or {}).get("rig_module") == "left_arm" for node in graph.nodes.values())
    assert not any((item.get("settings") or {}).get("rig_module") == "left_arm" for item in graph.constraints.values())


def test_tc_ui_metadata_and_control_shapes_survive_rebinding_and_scene_round_trip() -> None:
    graph = _humanoid_graph()
    bind_tc_hik_host(graph)
    create_rig.save_module_metadata("Spine", {"built": True, "parent": "root"})
    create_rig.hik_map_to_rig_args(_body_map(graph), setup_hik.DEFAULT_FACE_JOINT_MAP)
    graph.nodes["root"].setdefault("attributes", {})["control_cv_positions"] = [[1.0, 2.0, 3.0]]
    create_rig.store_all_control_cv_positions()

    restored_graph = EditableRigGraph.from_dict(graph.to_dict())
    bind_tc_hik_host(restored_graph)
    assert create_rig.load_module_metadata("Spine")["built"] is True
    assert restored_graph.metadata["hik_ui"]["character_definition"]["slots"]["Hips"] == "pelvis"
    assert create_rig.restore_all_control_cv_positions() == 1
    assert restored_graph.nodes["root"]["attributes"]["control_cv_positions"] == [[1.0, 2.0, 3.0]]


def test_unwrapped_tc_rig_actions_create_viewer_undo_checkpoints() -> None:
    graph = _humanoid_graph()
    checkpoints = []
    bind_tc_hik_host(graph, undo_callback=checkpoints.append)

    create_rig.create_joint_controls(["head"])
    create_rig.create_space_switch("head_ctrl", ["root"], constraint_type="orient")

    assert checkpoints == ["Create joint controls", "Create space switch"]
