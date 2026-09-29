"""Jiggle controls, collision, presets, performance paths, and portability."""

from __future__ import annotations

import numpy as np
import pytest

from tech_connector.game_engine.deformation import (
    SECONDARY_MOTION_PRESETS,
    DeformationStackRuntime,
    DeformationWeightMap,
    JiggleDeformerSettings,
    JiggleRuntimeState,
    attach_secondary_motion_preset,
    evaluate_jiggle,
    secondary_motion_export_contract,
)
from tech_connector.game_engine.deformation.skinning_tool_service import (
    export_skin_weights_payload,
    skin_cluster_from_rig_graph,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph
from tech_connector.game_engine.scene.tc_native_scene_compiler_service import compile_graph_to_tc_native
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider, COMPUTE_PROVIDERS, ComputeProviderStatus, register_compute_provider,
)


def _skin_graph(vertex_count: int = 1):
    graph = EditableRigGraph()
    joint = graph.add_joint("Root", joint_id="root")
    skin_id = graph.add_skin("body", [joint], skin_id="skin")
    graph.skins[skin_id].update({
        "vertex_count": vertex_count,
        "max_influences_per_vertex": 4,
        "weight_overrides": {str(index): {joint: 1.0} for index in range(vertex_count)},
    })
    return graph, skin_id


def test_jiggle_projects_through_sphere_and_reports_contacts() -> None:
    targets = [(0.0, 0.5, 0.0)]
    state = JiggleRuntimeState()
    settings = JiggleDeformerSettings(collision_radius=0.025, substeps=2)
    weights = DeformationWeightMap("jiggle", [1.0])
    evaluate_jiggle(targets, weights, state, settings, 1 / 60)
    result = evaluate_jiggle(
        targets, weights, state, settings, 1 / 60,
        colliders=[{"type": "sphere", "radius": 1.0, "center": (0.0, 0.0, 0.0)}],
    )
    assert result[0][1] >= 1.025 - 1.0e-6
    assert state.collision_count > 0


def test_jiggle_axis_control_speed_limit_and_driver_follow_are_stable() -> None:
    state = JiggleRuntimeState()
    weights = DeformationWeightMap("jiggle", [1.0])
    settings = JiggleDeformerSettings(axis_weights=(1.0, 0.0, 1.0), max_velocity=0.5, follow=1.0, substeps=4)
    evaluate_jiggle([(0.0, 0.0, 0.0)], weights, state, settings, 1 / 60)
    evaluate_jiggle([(2.0, 3.0, 0.0)], weights, state, settings, 1 / 60)
    driver_velocity = (2.0 / (1 / 60), 3.0 / (1 / 60), 0.0)
    relative_speed = sum(
        (state.velocities[0][axis] - driver_velocity[axis]) ** 2 for axis in range(3)
    ) ** 0.5
    assert relative_speed <= 0.5 + 1.0e-8
    assert state.positions[0][1] == 3.0


def test_large_jiggle_evaluation_preserves_painted_zero_vertices() -> None:
    count = 512
    targets = [(float(index) * 0.01, 0.0, 0.0) for index in range(count)]
    state = JiggleRuntimeState()
    weights = DeformationWeightMap("jiggle", [1.0] * (count - 1) + [0.0])
    settings = JiggleDeformerSettings()
    evaluate_jiggle(targets, weights, state, settings, 1 / 60)
    moved = [(x, 1.0, z) for x, _y, z in targets]
    result = evaluate_jiggle(moved, weights, state, settings, 1 / 60)
    assert len(result) == count
    assert result[-1] == moved[-1]


def test_preset_stack_is_editable_ordered_and_export_safe() -> None:
    graph, skin_id = _skin_graph()
    weights = DeformationWeightMap("soft_tissue", [1.0])
    identifiers = attach_secondary_motion_preset(graph, skin_id, "body", weights, "muscle_follow")
    cluster = skin_cluster_from_rig_graph(graph, skin_id)
    payload = export_skin_weights_payload(cluster)
    runtime = DeformationStackRuntime()
    runtime.evaluate(graph, "body", [(0.0, 2.0, 0.0)], 1 / 60)
    _result, telemetry = runtime.evaluate(graph, "body", [(0.0, 2.1, 0.0)], 1 / 60)

    assert len(identifiers) == 2
    assert [graph.deformers[item]["type"] for item in identifiers] == ["jiggle", "flesh"]
    assert telemetry.evaluated_deformers == identifiers
    assert set(telemetry.deformer_ms) == set(identifiers)
    assert payload["extensions"]["tech_connector.secondary_motion.v1"]["presets"][0]["preset_id"] == "muscle_follow"
    assert payload["interchange"]["canonical_skin_weights"] == "authoritative"
    assert payload["interchange"]["safe_without_extension"]


def test_secondary_motion_identity_remaps_and_contracts_cover_destinations() -> None:
    graph, skin_id = _skin_graph()
    identifiers = attach_secondary_motion_preset(
        graph, skin_id, "body", DeformationWeightMap("ears", [1.0]), "ears_tendrils"
    )
    receipt = compile_graph_to_tc_native(graph, "blender")
    compiled_skin = graph.skins[receipt["skin_ids"][skin_id]]
    assert compiled_skin["secondary_motion_presets"][0]["deformer_ids"] == [
        receipt["deformer_ids"][identifiers[0]]
    ]
    for destination in ("maya", "blender", "houdini", "unreal", "unity", "usd", "fbx", "gltf"):
        contract = secondary_motion_export_contract(destination)
        assert contract["canonical_skin_preserved"]
        assert contract["secondary_motion_transfer"]
    assert {"soft_tissue", "muscle_follow", "stylized_goop"} <= set(SECONDARY_MOTION_PRESETS)


def test_gpu_secondary_motion_stack_is_resident_budgeted_and_reference_compatible() -> None:
    provider_id = "test_gpu_secondary_motion"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU Deformation", True), np,
    ))
    try:
        vertex_count = 256
        graph, skin_id = _skin_graph(vertex_count)
        attach_secondary_motion_preset(
            graph, skin_id, "body", DeformationWeightMap("soft", [1.0] * vertex_count), "muscle_follow",
        )
        reference_runtime = DeformationStackRuntime()
        gpu_runtime = DeformationStackRuntime()
        start = [(index * 0.001, 2.0, 0.0) for index in range(vertex_count)]
        moved = [(x + 0.08, y + 0.12, -0.03) for x, y, _z in start]
        reference_runtime.evaluate(graph, "body", start, 1.0 / 60.0)
        gpu_runtime.evaluate_gpu(graph, "body", start, 1.0 / 60.0, provider_id=provider_id, target_ms=100.0)
        reference, _reference_telemetry = reference_runtime.evaluate(graph, "body", moved, 1.0 / 60.0)
        gpu, telemetry = gpu_runtime.evaluate_gpu(
            graph, "body", moved, 1.0 / 60.0, provider_id=provider_id, target_ms=100.0,
        )

        assert np.asarray(gpu) == pytest.approx(np.asarray(reference), abs=2.0e-5)
        assert telemetry.backend == "gpu_compute"
        assert telemetry.reused_states == 2
        assert telemetry.state_count == 2
        assert telemetry.memory_bytes > 0
        assert telemetry.synchronization_points == 1

        collision_runtime = DeformationStackRuntime()
        inside = [(0.1, index * 0.0001, 0.0) for index in range(vertex_count)]
        collision_runtime.evaluate_gpu(
            graph, "body", inside, 1.0 / 60.0, provider_id=provider_id, target_ms=100.0,
        )
        collided, collision_telemetry = collision_runtime.evaluate_gpu(
            graph, "body", inside, 1.0 / 60.0, provider_id=provider_id, target_ms=100.0,
            colliders=[{"type": "capsule", "start": (0.0, -1.0, 0.0),
                        "end": (0.0, 1.0, 0.0), "radius": 0.5}],
        )
        assert min(row[0] for row in collided) >= 0.51 - 1.0e-5
        assert collision_telemetry.collision_contacts > 0

        resident_runtime = DeformationStackRuntime()
        resident_runtime.evaluate_gpu(
            graph, "body", start, 1.0 / 60.0, provider_id=provider_id,
            target_ms=0.01, resident_output=True,
        )
        resident, resident_telemetry = resident_runtime.evaluate_gpu(
            graph, "body", moved, 1.0 / 60.0, provider_id=provider_id,
            target_ms=0.01, resident_output=True,
        )
        assert isinstance(resident, np.ndarray)
        assert resident_telemetry.readback_deferred
        assert resident_telemetry.synchronization_points == 0
        assert resident_telemetry.reused_states == 2
        assert resident_telemetry.lod_quality < 1.0
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)
