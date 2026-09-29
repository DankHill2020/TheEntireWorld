from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.authoring.tc_animation_take_service import (
    add_animation_layer,
    create_take,
    evaluate_curve,
    set_keyframe,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph


def _animation_graph() -> tuple[EditableRigGraph, str, str]:
    graph = EditableRigGraph()
    node_id = graph.add_node("Root_CTRL", "dag.control", node_id="Root_CTRL")
    take_id = create_take(graph, "Gameplay", start_frame=0, end_frame=9_999, frame_rate=60.0)
    return graph, node_id, take_id


def test_animation_curve_has_bounded_large_take_performance() -> None:
    graph, node_id, take_id = _animation_graph()
    started = time.perf_counter()
    for frame in range(10_000):
        set_keyframe(graph, take_id, node_id, "translate_x", frame, frame * 0.25)
    samples = [evaluate_curve(graph, take_id, node_id, "translate_x", frame + 0.5) for frame in range(9_999)]
    elapsed = time.perf_counter() - started

    assert len(graph.animation[take_id]["layers"]["BaseAnimation"]["curves"]["Root_CTRL.translate_x"]["keys"]) == 10_000
    assert samples[0] == pytest.approx(0.125)
    assert samples[-1] == pytest.approx(2_499.625)
    assert elapsed < 3.0


def test_animation_failures_are_transactional() -> None:
    graph, node_id, take_id = _animation_graph()
    add_animation_layer(graph, take_id, "Body", weight=0.5)
    before = json.dumps(graph.to_dict(), sort_keys=True)

    with pytest.raises(ValueError, match="already exists"):
        add_animation_layer(graph, take_id, "Body")
    with pytest.raises(KeyError, match="Unknown animation node"):
        set_keyframe(graph, take_id, "Missing", "translate_x", 1, 4.0)
    with pytest.raises(KeyError, match="Unknown animation layer"):
        set_keyframe(graph, take_id, node_id, "translate_x", 1, 4.0, layer="Missing")
    with pytest.raises(ValueError, match="end frame"):
        create_take(graph, "Invalid", start_frame=20, end_frame=10)

    assert json.dumps(graph.to_dict(), sort_keys=True) == before


def test_animation_takes_layers_and_curves_round_trip_losslessly() -> None:
    graph, node_id, take_id = _animation_graph()
    layer = add_animation_layer(graph, take_id, "Body", weight=0.25, additive=True)
    set_keyframe(graph, take_id, node_id, "translate_x", 0, 0.0, layer="BaseAnimation")
    set_keyframe(graph, take_id, node_id, "translate_x", 10, 10.0, layer="BaseAnimation")
    set_keyframe(graph, take_id, node_id, "translate_x", 0, 4.0, layer=layer)
    set_keyframe(graph, take_id, node_id, "translate_x", 10, 4.0, layer=layer)

    payload = json.loads(json.dumps(graph.to_dict(), sort_keys=True))
    restored = EditableRigGraph.from_dict(payload)

    assert restored.to_dict() == graph.to_dict()
    assert evaluate_curve(restored, take_id, node_id, "translate_x", 5.0) == pytest.approx(6.0)
    assert restored.animation[take_id]["active_layer"] == "Body"
