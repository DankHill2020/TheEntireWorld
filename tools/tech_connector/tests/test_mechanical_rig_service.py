from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.mechanical_rig_service import create_mechanical_rig
from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX


def _matrix(x: float, y: float, z: float) -> list[float]:
    value = list(IDENTITY_MATRIX)
    value[12:15] = [x, y, z]
    return value


def test_gear_relationship_evaluates_ratio_through_portable_graph() -> None:
    graph = EditableRigGraph()
    graph.add_node("Driver", "dag.control", node_id="Driver", attributes={"rotateY": 30.0})
    graph.add_node("Driven", "dag.control", node_id="Driven", attributes={"rotateY": 0.0})

    rig = create_mechanical_rig(graph, mode="gear", driver="Driver", driven="Driven", ratio=-0.5)
    evaluated = evaluate_rig_graph(graph)

    assert evaluated.ok, evaluated.errors
    assert evaluated.attributes["Driven"]["rotateY"] == pytest.approx(-15.0)
    assert len(rig.created_node_ids) == 1
    assert len(rig.created_connection_ids) == 2


def test_mechanical_graph_round_trips_and_re_evaluates() -> None:
    graph = EditableRigGraph()
    graph.add_node("Pinion", "dag.control", node_id="Pinion", attributes={"rotateX": 12.0})
    graph.add_node("Rack", "dag.control", node_id="Rack", attributes={"translateZ": 0.0})
    create_mechanical_rig(
        graph,
        mode="rack_pinion",
        driver="Pinion",
        driven="Rack",
        driver_axis="x",
        driven_axis="z",
        ratio=2.5,
    )

    restored = EditableRigGraph.from_dict(graph.to_dict())
    evaluated = evaluate_rig_graph(restored)

    assert evaluated.ok, evaluated.errors
    assert evaluated.attributes["Rack"]["translateZ"] == pytest.approx(30.0)


def test_piston_aims_live_driven_axis_at_driver() -> None:
    graph = EditableRigGraph()
    graph.add_node("Anchor", "dag.control", node_id="Anchor", attributes={"matrix": _matrix(4.0, 0.0, 0.0)})
    graph.add_node("Rod", "dag.control", node_id="Rod", attributes={"matrix": _matrix(0.0, 0.0, 0.0)})
    rig = create_mechanical_rig(graph, mode="piston", driver="Anchor", driven="Rod", driven_axis="x")

    evaluated = evaluate_rig_graph(graph)

    assert evaluated.ok, evaluated.errors
    assert len(rig.created_constraint_ids) == 1
    assert evaluated.world_matrices["Rod"][0:3] == pytest.approx((1.0, 0.0, 0.0))


def test_mechanical_rig_rejects_zero_ratio_and_unknown_endpoints() -> None:
    graph = EditableRigGraph()
    graph.add_node("Driver", "dag.control", node_id="Driver")
    graph.add_node("Driven", "dag.control", node_id="Driven")

    with pytest.raises(ValueError, match="cannot be zero"):
        create_mechanical_rig(graph, mode="gear", driver="Driver", driven="Driven", ratio=0.0)
    with pytest.raises(KeyError, match="must resolve"):
        create_mechanical_rig(graph, mode="gear", driver="Missing", driven="Driven")
