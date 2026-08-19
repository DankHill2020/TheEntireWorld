from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.authoring.quadruped_leg_rig_service import create_quadruped_leg_rig
from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def _leg_graph() -> tuple[EditableRigGraph, list[str]]:
    graph = EditableRigGraph()
    hip = graph.add_joint("Hip", joint_id="Hip", local_matrix=_matrix(0.0, 0.0, 0.0))
    knee = graph.add_joint("Knee", parent_id=hip, joint_id="Knee", local_matrix=_matrix(2.0, -2.0, 0.0))
    hock = graph.add_joint("Hock", parent_id=knee, joint_id="Hock", local_matrix=_matrix(0.0, -2.0, 0.0))
    ankle = graph.add_joint("Ankle", parent_id=hock, joint_id="Ankle", local_matrix=_matrix(0.0, -1.0, 1.0))
    return graph, [hip, knee, hock, ankle]


def test_quadruped_leg_builds_two_live_ik_stages_and_foot_channels() -> None:
    graph, chain = _leg_graph()

    rig = create_quadruped_leg_rig(graph, joint_chain=chain, module="rear_L", gait_phase=0.25)
    evaluated = evaluate_rig_graph(graph)

    assert evaluated.ok, evaluated.errors
    assert rig.solver_ids == ("rear_L_upper_ik", "rear_L_lower_ik")
    assert all(solver in graph.constraints for solver in rig.solver_ids)
    foot_attributes = graph.nodes[rig.foot_control]["attributes"]
    assert foot_attributes["foot_roll"] == 0.0
    assert foot_attributes["bank"] == 0.0
    assert foot_attributes["gait_phase"] == 0.25


def test_quadruped_leg_graph_round_trips_and_evaluates() -> None:
    graph, chain = _leg_graph()
    rig = create_quadruped_leg_rig(graph, joint_chain=chain, module="front_R")

    restored = EditableRigGraph.from_dict(graph.to_dict())
    moved = list(restored.nodes[rig.foot_control]["attributes"]["matrix"])
    moved[12] += 1.0
    restored.nodes[rig.foot_control]["attributes"]["matrix"] = moved
    evaluated = evaluate_rig_graph(restored)

    assert evaluated.ok, evaluated.errors
    assert evaluated.world_matrices[chain[-1]][12:15] == pytest.approx(moved[12:15], abs=1.0e-5)


def test_quadruped_leg_rejects_noncontiguous_chain() -> None:
    graph, chain = _leg_graph()
    graph.joints[chain[2]]["parent_id"] = chain[0]

    with pytest.raises(ValueError, match="direct hip"):
        create_quadruped_leg_rig(graph, joint_chain=chain)


class _ViewerHarness:
    def __init__(self) -> None:
        self.editable_rig_graph, self.chain = _leg_graph()
        self._viewer_undo_stack = []
        self.refresh_count = 0

    def push_rig_undo_state(self, label: str) -> None:
        self._viewer_undo_stack.append(label)

    def refresh_scene_outliner(self) -> None:
        self.refresh_count += 1


def test_viewer_creates_quadruped_leg_command() -> None:
    viewer = _ViewerHarness()

    result = ThreeDMeshPainterViewport._execute_tc_quadruped_leg_command(
        viewer,
        {"joint_chain": viewer.chain, "module": "rear_R"},
    )

    assert result["quadruped_leg"]["module"] == "rear_R"
    assert len(result["quadruped_leg"]["solver_ids"]) == 2
    assert viewer._viewer_undo_stack == ["Create Quadruped Leg IK"]
    assert viewer.refresh_count == 1
