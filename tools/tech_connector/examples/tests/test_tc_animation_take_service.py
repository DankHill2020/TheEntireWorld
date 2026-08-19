import pytest

from tech_connector.services.dcc.federated_scene_service import EditableRigGraph
from tech_connector.services.dcc.tc_animation_take_service import (
    add_animation_layer,
    create_take,
    evaluate_curve,
    set_keyframe,
)


def test_take_layers_key_and_evaluate_animation_curves() -> None:
    graph = EditableRigGraph()
    graph.add_node("Control", "dag.control", node_id="control")
    take = create_take(graph, "Walk", start_frame=1, end_frame=48, frame_rate=24.0)
    set_keyframe(graph, take, "control", "translateX", 1, 0.0)
    set_keyframe(graph, take, "control", "translateX", 25, 12.0)

    assert evaluate_curve(graph, take, "control", "translateX", 13) == pytest.approx(6.0)

    layer = add_animation_layer(graph, take, "Polish", weight=0.5, additive=True)
    set_keyframe(graph, take, "control", "translateX", 1, 2.0, layer=layer)
    assert evaluate_curve(graph, take, "control", "translateX", 13) == pytest.approx(7.0)


def test_stepped_keys_hold_like_motionbuilder_constant_interpolation() -> None:
    graph = EditableRigGraph()
    graph.add_node("Control", "dag.control", node_id="control")
    take = create_take(graph, "Blocking")
    set_keyframe(graph, take, "control", "rotateY", 1, 10.0, interpolation="stepped")
    set_keyframe(graph, take, "control", "rotateY", 10, 90.0)

    assert evaluate_curve(graph, take, "control", "rotateY", 5) == 10.0
