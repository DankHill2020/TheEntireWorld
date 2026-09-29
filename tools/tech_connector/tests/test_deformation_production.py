from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.deformation import (
    BlendShapeFrame,
    BlendShapeTarget,
    DeformationStackRuntime,
    DeformationWeightMap,
    MuscleDeformerSettings,
    attach_blend_shape_deformer,
    attach_muscle_deformer,
    attach_secondary_motion_preset,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph


def _dense_graph(vertex_count: int) -> tuple[EditableRigGraph, list[tuple[float, float, float]]]:
    graph = EditableRigGraph()
    root = graph.add_joint("Root", joint_id="Root")
    skin_id = graph.add_skin("Body", [root], skin_id="BodySkin")
    graph.skins[skin_id].update({"vertex_count": vertex_count, "max_influences_per_vertex": 4})
    weights = DeformationWeightMap.create("BodyInfluence", vertex_count, default_value=1.0)
    attach_muscle_deformer(
        graph,
        skin_id,
        "Body",
        weights,
        settings=MuscleDeformerSettings(contraction=0.04, bulge=0.02, substeps=2),
        deformer_id="BodyMuscle",
    )
    attach_secondary_motion_preset(graph, skin_id, "Body", weights, "subtle_skin")
    sparse_deltas = {index: (0.0, 0.01, 0.0) for index in range(0, vertex_count, 4)}
    attach_blend_shape_deformer(
        graph,
        "Body",
        vertex_count,
        [BlendShapeTarget("breath", "Breath", (BlendShapeFrame(1.0, sparse_deltas),), weight=0.5)],
        deformer_id="BreathShape",
    )
    positions = [(index * 0.001, 0.0, 0.0) for index in range(vertex_count)]
    return graph, positions


def test_dense_deformation_stack_evaluates_and_round_trips_inside_budget() -> None:
    graph, positions = _dense_graph(10_000)
    started = time.perf_counter()
    expected, expected_telemetry = DeformationStackRuntime().evaluate(
        graph, "Body", positions, 1.0 / 60.0, normals=[(0.0, 0.0, 1.0)] * len(positions),
    )
    serialized = json.dumps(graph.to_dict(), sort_keys=True)
    restored = EditableRigGraph.from_dict(json.loads(serialized))
    actual, actual_telemetry = DeformationStackRuntime().evaluate(
        restored, "Body", positions, 1.0 / 60.0, normals=[(0.0, 0.0, 1.0)] * len(positions),
    )
    elapsed = time.perf_counter() - started

    assert len(expected) == len(actual) == 10_000
    assert actual == pytest.approx(expected)
    assert set(actual_telemetry.evaluated_deformers) == set(expected_telemetry.evaluated_deformers)
    assert json.dumps(restored.to_dict(), sort_keys=True) == serialized
    assert elapsed < 3.0


def test_invalid_deformation_authoring_is_transactional() -> None:
    graph, positions = _dense_graph(8)
    before = json.dumps(graph.to_dict(), sort_keys=True)
    influence = DeformationWeightMap.create("Paint", len(positions))
    values_before = list(influence.values)

    with pytest.raises(ValueError, match="matching vertex counts"):
        influence.paint(positions[:-1], (0.0, 0.0, 0.0), 1.0)
    with pytest.raises(ValueError, match="Invalid blend-shape delta"):
        attach_blend_shape_deformer(
            graph,
            "Body",
            len(positions),
            [BlendShapeTarget("bad", "Bad", (BlendShapeFrame(1.0, {99: (1.0, 0.0, 0.0)}),))],
        )
    with pytest.raises(KeyError, match="Unknown secondary-motion preset"):
        attach_secondary_motion_preset(graph, "BodySkin", "Body", influence, "missing")

    assert influence.values == values_before
    assert json.dumps(graph.to_dict(), sort_keys=True) == before
