from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


class _ViewerHarness:
    def __init__(self) -> None:
        self.editable_rig_graph = EditableRigGraph()
        self._viewer_undo_stack = []
        self.refresh_count = 0

    def push_rig_undo_state(self, label: str) -> None:
        self._viewer_undo_stack.append(label)

    def refresh_scene_outliner(self) -> None:
        self.refresh_count += 1


def test_adaptive_joint_and_parent_constraint_execute_in_native_graph() -> None:
    viewer = _ViewerHarness()
    driver = viewer.editable_rig_graph.add_node("Driver", "dag.control", node_id="Driver", attributes={"matrix": _matrix(2.0, 0.0, 0.0)})
    driven = viewer.editable_rig_graph.add_node("Driven", "dag.control", node_id="Driven", attributes={"matrix": _matrix(4.0, 0.0, 0.0)})

    joint = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.create_joint",
        {"name": "Root", "joint_id": "Root_JNT"},
    )
    constraint = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.parent_constraint",
        {"driver": driver, "driven": driven, "maintain_offset": True},
    )

    assert joint["joint_id"] == "Root_JNT"
    assert constraint["ok"] is True
    assert any(item["type"] == "parent" for item in viewer.editable_rig_graph.constraints.values())
    assert viewer.refresh_count == 2


def test_adaptive_ik_ribbon_pose_reader_and_space_switch_use_shared_controller() -> None:
    viewer = _ViewerHarness()
    root = viewer.editable_rig_graph.add_joint("Root", joint_id="Root", local_matrix=_matrix(0.0, 0.0, 0.0))
    mid = viewer.editable_rig_graph.add_joint("Mid", parent_id=root, joint_id="Mid", local_matrix=_matrix(2.0, 0.0, 0.0))
    end = viewer.editable_rig_graph.add_joint("End", parent_id=mid, joint_id="End", local_matrix=_matrix(2.0, 0.0, 0.0))
    world = viewer.editable_rig_graph.add_node("World", "dag.control", node_id="World")

    ik = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.create_ik_handle",
        {"start": root, "mid": mid, "end": end, "module": "arm"},
    )
    ribbon = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.create_ribbon_ik",
        {"joint_chain": [root, mid, end], "width": 0.5},
    )
    reader = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.create_pose_reader",
        {"driver": root, "name": "RootReader"},
    )
    switch = ThreeDMeshPainterViewport._execute_tc_rigging_command(
        viewer,
        "rigging.create_space_switch",
        {"driven": ik["data"]["ik_control"], "targets": [world]},
    )

    assert ik["ok"] and ribbon["ok"] and reader["ok"] and switch["ok"]
    assert "arm_ik_solver" in viewer.editable_rig_graph.constraints
    assert "RootReader" in viewer.editable_rig_graph.nodes
    assert viewer.refresh_count == 4
