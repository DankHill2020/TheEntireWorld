"""Activation, pose-space, runtime, GPU, and interchange muscle coverage."""

from __future__ import annotations

import numpy as np
import pytest

from tech_connector.game_engine.deformation import (
    DeformationStackRuntime,
    DeformationWeightMap,
    MuscleDeformerSettings,
    MuscleRuntimeState,
    PoseSpaceTissueDriver,
    attach_muscle_deformer,
    evaluate_muscle,
    muscle_export_contract,
    set_muscle_activation,
    build_deformation_transfer_plan,
    qualify_deformation_point_cache,
)
from tech_connector.game_engine.deformation.skinning_tool_service import (
    export_skin_weights_payload,
    skin_cluster_from_rig_graph,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph
from tech_connector.game_engine.scene.tc_native_scene_compiler_service import compile_graph_to_tc_native
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider,
    COMPUTE_PROVIDERS,
    ComputeProviderStatus,
    register_compute_provider,
)


def _skin_graph(vertex_count: int = 2):
    graph = EditableRigGraph()
    joint = graph.add_joint("Root", joint_id="root")
    skin_id = graph.add_skin("body", [joint], skin_id="skin")
    graph.skins[skin_id].update({
        "vertex_count": vertex_count,
        "max_influences_per_vertex": 4,
        "weight_overrides": {str(index): {joint: 1.0} for index in range(vertex_count)},
    })
    return graph, skin_id


def test_muscle_activation_contracts_fibers_bulges_and_respects_paint() -> None:
    state = MuscleRuntimeState()
    result = evaluate_muscle(
        [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        DeformationWeightMap("biceps", [1.0, 0.0]),
        state,
        MuscleDeformerSettings(
            fiber_direction=(1.0, 0.0, 0.0), contraction=0.2, bulge=0.1,
        ),
        1.0 / 60.0,
        normals=[(0.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
    )

    assert result[0] == pytest.approx((-0.8, 0.0, 0.1))
    assert result[1] == pytest.approx((1.0, 0.0, 0.0))
    assert state.activation_mean == pytest.approx(0.5)
    assert state.activated_vertices == 1


def test_pose_space_driver_adds_localized_tissue_response() -> None:
    driver = PoseSpaceTissueDriver("elbow_flex", center=1.0, width=0.1, gain=1.0, bulge_scale=2.0)
    settings = MuscleDeformerSettings(
        fiber_direction=(1.0, 0.0, 0.0), contraction=0.0, bulge=0.1,
    )
    targets = [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    activation = DeformationWeightMap("base", [0.0, 0.0])
    pose_map = DeformationWeightMap("elbow", [1.0, 0.0])

    result = evaluate_muscle(
        targets, activation, MuscleRuntimeState(), settings, 1.0 / 60.0,
        normals=[(0.0, 0.0, 1.0)] * 2, pose_drivers=[driver],
        pose_values={"elbow_flex": 1.0}, pose_maps={"elbow_flex": pose_map},
    )

    assert result[0][2] == pytest.approx(0.2)
    assert result[1] == pytest.approx(targets[1])


def test_muscle_teleport_resets_velocity_without_explosion() -> None:
    state = MuscleRuntimeState()
    settings = MuscleDeformerSettings(teleport_distance=0.5)
    activation = DeformationWeightMap("muscle", [1.0])
    evaluate_muscle([(0.0, 0.0, 0.0)], activation, state, settings, 1.0 / 60.0,
                    normals=[(0.0, 1.0, 0.0)])
    result = evaluate_muscle([(10.0, 0.0, 0.0)], activation, state, settings, 1.0 / 60.0,
                             normals=[(0.0, 1.0, 0.0)])

    assert state.teleport_count == 1
    assert np.asarray(state.velocities) == pytest.approx(np.zeros((1, 3)))
    assert np.isfinite(result).all()
    assert result[0][0] == pytest.approx(10.0)


def test_muscle_stack_live_activation_and_export_preserve_canonical_skin() -> None:
    graph, skin_id = _skin_graph()
    muscle_id = attach_muscle_deformer(
        graph, skin_id, "body", DeformationWeightMap("biceps", [1.0, 0.25]),
        pose_drivers=[PoseSpaceTissueDriver("elbow")],
        pose_maps={"elbow": DeformationWeightMap("elbow", [1.0, 0.0])},
        deformer_id="muscle",
    )
    activation = set_muscle_activation(graph, muscle_id, 0.8, pose_values={"elbow": 1.0})
    runtime = DeformationStackRuntime()
    _result, telemetry = runtime.evaluate(
        graph, "body", [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0)], 1.0 / 60.0,
        normals=[(0.0, 0.0, 1.0)] * 2,
    )
    payload = export_skin_weights_payload(skin_cluster_from_rig_graph(graph, skin_id))

    assert activation["activation"] == pytest.approx(0.8)
    assert telemetry.evaluated_deformers == [muscle_id]
    assert telemetry.muscle_activation[muscle_id]["active_vertices"] == 2
    assert payload["interchange"]["canonical_skin_weights"] == "authoritative"
    assert payload["interchange"]["safe_without_extension"]
    assert payload["extensions"]["tech_connector.muscle.v1"]["deformers"][0]["deformer_id"] == muscle_id


def test_native_identity_remaps_muscle_and_export_contracts_are_explicit() -> None:
    graph, skin_id = _skin_graph(1)
    muscle_id = attach_muscle_deformer(
        graph, skin_id, "body", DeformationWeightMap("muscle", [1.0]),
        deformer_id="source_muscle",
    )
    receipt = compile_graph_to_tc_native(graph, "houdini")
    compiled_skin = graph.skins[receipt["skin_ids"][skin_id]]
    compiled_muscle = graph.deformers[receipt["deformer_ids"][muscle_id]]

    assert compiled_skin["muscles"][0]["deformer_id"] == receipt["deformer_ids"][muscle_id]
    assert compiled_muscle["settings"]["source_id"] == receipt["skin_ids"][skin_id]
    for destination in ("maya", "blender", "houdini", "unreal", "unity", "usd", "fbx", "gltf"):
        contract = muscle_export_contract(destination)
        assert contract["canonical_skin_preserved"]
        assert contract["muscle_transfer"]
        assert "point_cache" in contract["fallback_priority"]


def test_gpu_muscle_is_resident_pose_driven_and_reference_compatible() -> None:
    provider_id = "test_gpu_muscle"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU Muscle", True), np,
    ))
    try:
        count = 128
        graph, skin_id = _skin_graph(count)
        muscle_id = attach_muscle_deformer(
            graph, skin_id, "body", DeformationWeightMap("muscle", [1.0] * count),
            settings=MuscleDeformerSettings(
                fiber_direction=(1.0, 0.0, 0.0), contraction=0.1, bulge=0.05,
            ),
            pose_drivers=[PoseSpaceTissueDriver("flex", gain=0.25)],
            pose_maps={"flex": DeformationWeightMap("flex", [1.0] * count)},
        )
        set_muscle_activation(graph, muscle_id, 0.75, pose_values={"flex": 1.0})
        start = [(index * 0.01, 0.0, 0.0) for index in range(count)]
        moved = [(x + 0.02, 0.03, 0.0) for x, _y, _z in start]
        normals = [(0.0, 0.0, 1.0)] * count
        cpu_runtime = DeformationStackRuntime()
        gpu_runtime = DeformationStackRuntime()
        cpu_runtime.evaluate(graph, "body", start, 1.0 / 60.0, normals=normals)
        gpu_runtime.evaluate_gpu(
            graph, "body", start, 1.0 / 60.0, provider_id=provider_id,
            target_ms=100.0, normals=normals,
        )
        reference, _ = cpu_runtime.evaluate(graph, "body", moved, 1.0 / 60.0, normals=normals)
        gpu, telemetry = gpu_runtime.evaluate_gpu(
            graph, "body", moved, 1.0 / 60.0, provider_id=provider_id,
            target_ms=100.0, normals=normals,
        )

        assert np.asarray(gpu) == pytest.approx(np.asarray(reference), abs=2.0e-5)
        assert telemetry.evaluated_deformers == [muscle_id]
        assert telemetry.reused_states == 1
        assert telemetry.muscle_activation[muscle_id]["active_vertices"] == count

        resident_runtime = DeformationStackRuntime()
        resident, resident_telemetry = resident_runtime.evaluate_gpu(
            graph, "body", start, 1.0 / 60.0, provider_id=provider_id,
            target_ms=100.0, normals=normals, resident_output=True,
        )
        assert isinstance(resident, np.ndarray)
        assert resident_telemetry.synchronization_points == 0
        assert resident_telemetry.muscle_activation[muscle_id]["readback_deferred"]
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_deformation_transfer_plan_keeps_skin_and_reports_honest_host_gates() -> None:
    graph, skin_id = _skin_graph(2)
    muscle_id = attach_muscle_deformer(
        graph, skin_id, "body", DeformationWeightMap("muscle", [1.0, 0.5]),
    )
    editable = build_deformation_transfer_plan(graph, "body", "houdini")
    baked = build_deformation_transfer_plan(
        graph, "body", "unreal", prefer_editable=False, frame_rate=60.0, frame_count=120,
    )

    assert editable["canonical_skin"] == {"authoritative": True, "skin_ids": [skin_id], "required": True}
    assert editable["artifacts"][0]["deformer_id"] == muscle_id
    assert editable["artifacts"][0]["selected_path"] == "muscles_and_tissue"
    assert not editable["qualification"]["live_host_claimed"]
    assert "live_target_import" in editable["qualification"]["remaining_gates"]
    assert baked["artifacts"][0]["selected_path"] == "geometry_cache"
    assert baked["cache"]["frame_count"] == 120
    assert baked["receipt_sha256"] == build_deformation_transfer_plan(
        graph, "body", "unreal", prefer_editable=False, frame_rate=60.0, frame_count=120,
    )["receipt_sha256"]


def test_deformation_point_cache_qualification_rejects_topology_and_nan() -> None:
    valid = qualify_deformation_point_cache([
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(0.0, 0.1, 0.0), (1.0, 0.1, 0.0)],
    ])
    invalid = qualify_deformation_point_cache([
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(float("nan"), 0.1, 0.0)],
    ])

    assert valid["qualified"] and valid["constant_topology"] and valid["finite_samples"]
    assert len(valid["sample_sha256"]) == 64
    assert not invalid["qualified"]
    assert not invalid["constant_topology"]
    assert not invalid["finite_samples"]
