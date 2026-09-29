from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX


def _translated(x: float) -> list[float]:
    matrix = list(IDENTITY_MATRIX)
    matrix[12] = x
    return matrix


def test_large_rig_graph_evaluates_and_round_trips_inside_budget() -> None:
    graph = EditableRigGraph()
    parent = ""
    started = time.perf_counter()
    for index in range(1_000):
        parent = graph.add_node(
            f"Control_{index}",
            "dag.control",
            parent_id=parent,
            node_id=f"Control_{index}",
            attributes={"matrix": _translated(0.01)},
        )

    evaluated = evaluate_rig_graph(graph)
    payload = json.loads(json.dumps(graph.to_dict(), sort_keys=True))
    restored = EditableRigGraph.from_dict(payload)
    restored_evaluation = evaluate_rig_graph(restored)
    elapsed = time.perf_counter() - started

    assert evaluated.ok, evaluated.errors
    assert restored_evaluation.ok, restored_evaluation.errors
    assert len(restored_evaluation.world_matrices) == 1_000
    assert restored_evaluation.world_matrices["Control_999"][12] == pytest.approx(10.0)
    assert restored.to_dict() == graph.to_dict()
    assert elapsed < 3.0


def test_invalid_rig_edits_are_transactional() -> None:
    graph = EditableRigGraph()
    root = graph.add_joint("Root", joint_id="Root", local_matrix=_translated(0.0))
    mid = graph.add_joint("Mid", parent_id=root, joint_id="Mid", local_matrix=_translated(1.0))
    end = graph.add_joint("End", parent_id=mid, joint_id="End", local_matrix=_translated(1.0))
    graph.add_node("Target", "dag.control", node_id="Target", attributes={"matrix": _translated(3.0)})
    before = json.dumps(graph.to_dict(), sort_keys=True)

    with pytest.raises(ValueError, match="already exists"):
        graph.add_node("Duplicate", "dag.control", node_id="Target")
    with pytest.raises(ValueError, match="descendant"):
        graph.reparent_joint(root, end)
    with pytest.raises(KeyError, match="Unknown IK control"):
        graph.add_ik_solver(root, mid, end, "Missing")

    assert json.dumps(graph.to_dict(), sort_keys=True) == before
