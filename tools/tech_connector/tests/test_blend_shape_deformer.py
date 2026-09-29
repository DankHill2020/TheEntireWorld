"""Portable sparse blend-shape evaluation and interchange coverage."""

from __future__ import annotations

import pytest
import numpy as np

from tech_connector.game_engine.deformation.blend_shape import (
    BlendShapeCorrectiveDriver,
    BlendShapeFrame,
    BlendShapeTarget,
    BlendShapeTelemetry,
    attach_blend_shape_deformer,
    blend_shape_export_contract,
    blend_shape_payload,
    blend_shape_target_from_positions,
    blend_shape_targets_from_payload,
    blend_shape_target_from_dict,
    evaluate_blend_shape,
    set_blend_shape_weights,
    build_blend_shape_destination_manifest,
    blend_shape_targets_from_destination_manifest,
)
from tech_connector.game_engine.deformation.weight_map import DeformationWeightMap
from tech_connector.game_engine.deformation.deformation_stack import DeformationStackRuntime
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph
from tech_connector.game_engine.scene.tc_native_scene_compiler_service import compile_graph_to_tc_native
from tech_connector.game_engine.deformation.deformation_interchange_service import build_deformation_transfer_plan
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider, COMPUTE_PROVIDERS, ComputeProviderStatus, register_compute_provider,
)


def test_sparse_inbetweens_masks_and_negative_weights_are_deterministic() -> None:
    target = BlendShapeTarget(
        "smile", "Smile",
        (BlendShapeFrame(0.5, {0: (0.0, 1.0, 0.0)}),
         BlendShapeFrame(1.0, {0: (0.0, 3.0, 0.0), 1: (1.0, 0.0, 0.0)})),
        mask=DeformationWeightMap("smile_mask", [1.0, 0.25]),
    )
    telemetry = BlendShapeTelemetry()
    result = evaluate_blend_shape(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [target], weights={"smile": 0.75}, telemetry=telemetry,
    )

    assert result[0] == pytest.approx((0.0, 2.0, 0.0))
    assert result[1] == pytest.approx((2.125, 0.0, 0.0))
    assert telemetry.active_targets == 1
    assert telemetry.active_deltas == 2

    negative = evaluate_blend_shape([(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)], [target],
                                    weights={"smile": -0.5})
    assert negative[0][1] == pytest.approx(-1.0)


def test_corrective_driver_and_animation_keys_resolve_channel_weight() -> None:
    corrective = BlendShapeTarget(
        "elbow_fix", "Elbow Fix", (BlendShapeFrame(1.0, {0: (0.0, 0.0, 2.0)}),),
        driver=BlendShapeCorrectiveDriver("elbow_flex", center=1.0, width=0.1, gain=1.0, mode="replace"),
    )
    animated = BlendShapeTarget(
        "blink", "Blink", (BlendShapeFrame(1.0, {0: (0.0, -1.0, 0.0)}),),
        animation_keys=((1.0, 0.0), (5.0, 1.0)),
    )
    result = evaluate_blend_shape(
        [(0.0, 0.0, 0.0)], [corrective, animated], driver_values={"elbow_flex": 1.0}, frame=3.0,
    )
    assert result[0] == pytest.approx((0.0, -0.5, 2.0))


def test_blend_shape_payload_round_trip_and_destination_contracts() -> None:
    target = BlendShapeTarget("smile", "Smile", (BlendShapeFrame(1.0, {1: (0.1, 0.2, 0.3)}),))
    payload = blend_shape_payload([target], 3)
    restored = blend_shape_target_from_dict(payload["targets"][0]).validated(3)

    assert restored == target
    assert blend_shape_targets_from_payload(payload, expected_vertex_count=3) == (target,)
    assert len(payload["sha256"]) == 64
    for destination in ("maya", "blender", "houdini", "unreal", "unity", "usd", "fbx", "gltf"):
        contract = blend_shape_export_contract(destination)
        assert contract["native_mapping"]
        assert contract["topology_must_match"]
        assert contract["deformer_order_preserved"]

    corrupted = dict(payload)
    corrupted["vertex_count"] = 4
    with pytest.raises(ValueError, match="checksum"):
        blend_shape_targets_from_payload(corrupted)


def test_target_from_positions_is_sparse_and_rejects_topology_changes() -> None:
    target = blend_shape_target_from_positions(
        "smile", "Smile", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        [(0.0, 0.0, 0.0), (1.0, 0.2, 0.0)],
    )
    assert target.frames[0].deltas == {1: (0.0, 0.2, 0.0)}
    with pytest.raises(ValueError, match="topology"):
        blend_shape_target_from_positions("bad", "Bad", [(0.0, 0.0, 0.0)], [])


def test_graph_attachment_and_live_weight_control_preserve_target_data() -> None:
    graph = EditableRigGraph()
    target = BlendShapeTarget("smile", "Smile", (BlendShapeFrame(1.0, {0: (0.0, 1.0, 0.0)}),))
    deformer_id = attach_blend_shape_deformer(graph, "face", 2, [target], deformer_id="face_shapes")
    response = set_blend_shape_weights(graph, deformer_id, {"smile": 0.65}, frame=12.0)

    assert graph.deformers[deformer_id]["type"] == "blend_shape"
    assert graph.deformers[deformer_id]["settings"]["schema"] == "tech_connector.blend_shape.v1"
    assert response["weights"] == {"smile": 0.65}
    assert response["frame"] == 12.0


def test_ordered_stack_evaluates_blend_shapes_and_native_compiler_remaps_identity() -> None:
    graph = EditableRigGraph()
    first = attach_blend_shape_deformer(
        graph, "face", 1,
        [BlendShapeTarget("x", "X", (BlendShapeFrame(1.0, {0: (1.0, 0.0, 0.0)}),), weight=1.0)],
        deformer_id="first",
    )
    second = attach_blend_shape_deformer(
        graph, "face", 1,
        [BlendShapeTarget("y", "Y", (BlendShapeFrame(1.0, {0: (0.0, 2.0, 0.0)}),), weight=0.5)],
        deformer_id="second",
    )
    result, telemetry = DeformationStackRuntime().evaluate(graph, "face", [(0.0, 0.0, 0.0)], 1.0 / 60.0)
    receipt = compile_graph_to_tc_native(graph, "maya")

    assert result[0] == pytest.approx((1.0, 1.0, 0.0))
    assert telemetry.evaluated_deformers == [first, second]
    assert telemetry.blend_shapes[first]["active_targets"] == 1
    assert receipt["deformer_ids"][first] in graph.deformers
    assert graph.deformers[receipt["deformer_ids"][first]]["evaluation_mode"] == "runtime_local"


def test_gpu_blend_shapes_keep_sparse_buffers_resident_and_match_cpu() -> None:
    provider_id = "test_gpu_blend_shapes"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU Blend Shapes", True), np,
    ))
    try:
        count = 256
        graph = EditableRigGraph()
        deformer_id = attach_blend_shape_deformer(
            graph, "face", count,
            [BlendShapeTarget(
                "smile", "Smile",
                (BlendShapeFrame(0.5, {0: (0.0, 0.5, 0.0), 100: (0.1, 0.0, 0.0)}),
                 BlendShapeFrame(1.0, {0: (0.0, 1.5, 0.0), 100: (0.4, 0.0, 0.0)})),
                weight=0.75,
            )], deformer_id="face_shapes",
        )
        source = [(index * 0.001, 0.0, 0.0) for index in range(count)]
        cpu, _ = DeformationStackRuntime().evaluate(graph, "face", source, 1.0 / 60.0)
        runtime = DeformationStackRuntime()
        gpu, first = runtime.evaluate_gpu(
            graph, "face", source, 1.0 / 60.0, provider_id=provider_id, target_ms=100.0,
        )
        resident, second = runtime.evaluate_gpu(
            graph, "face", source, 1.0 / 60.0, provider_id=provider_id,
            target_ms=100.0, resident_output=True,
        )

        assert np.asarray(gpu) == pytest.approx(np.asarray(cpu), abs=1.0e-6)
        assert isinstance(resident, np.ndarray)
        assert first.blend_shapes[deformer_id]["provider_buffers_resident"]
        assert first.memory_bytes > 0
        assert second.reused_states == 1
        assert second.synchronization_points == 0
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_transfer_plan_selects_native_blend_shape_and_baked_fallbacks() -> None:
    graph = EditableRigGraph()
    deformer_id = attach_blend_shape_deformer(
        graph, "face", 1,
        [BlendShapeTarget("smile", "Smile", (BlendShapeFrame(1.0, {0: (0.0, 1.0, 0.0)}),))],
    )
    maya = build_deformation_transfer_plan(graph, "face", "maya")
    unreal_baked = build_deformation_transfer_plan(
        graph, "face", "unreal", prefer_editable=False, frame_count=48,
    )
    assert maya["artifacts"][0]["deformer_id"] == deformer_id
    assert maya["artifacts"][0]["selected_path"] == "blendShape"
    assert maya["artifacts"][0]["fallback_chain"][-1] == "alembic_point_cache"
    assert unreal_baked["artifacts"][0]["selected_path"] == "geometry_cache"


@pytest.mark.parametrize("destination", ["maya", "blender", "houdini", "unreal", "unity", "usd", "fbx", "gltf"])
def test_destination_golden_manifest_round_trips_losslessly(destination: str) -> None:
    target = BlendShapeTarget(
        "smile", "Smile",
        (BlendShapeFrame(0.5, {0: (0.0, 0.4, 0.0)}),
         BlendShapeFrame(1.0, {0: (0.0, 1.0, 0.0), 2: (0.2, 0.0, 0.0)})),
        mask=DeformationWeightMap("smile_mask", [1.0, 0.5, 0.25]),
        driver=BlendShapeCorrectiveDriver("jaw_open", center=0.8, width=0.2, gain=0.5),
        animation_keys=((1.0, 0.0), (12.0, 1.0)),
    )
    manifest = build_blend_shape_destination_manifest([target], 3, destination, deformer_id="face_shapes")
    restored = blend_shape_targets_from_destination_manifest(manifest, expected_destination=destination)
    source = [(0.0, 0.0, 0.0)] * 3
    expected = evaluate_blend_shape(source, [target], weights={"smile": 0.6}, driver_values={"jaw_open": 0.8})
    actual = evaluate_blend_shape(source, restored, weights={"smile": 0.6}, driver_values={"jaw_open": 0.8})

    assert actual == pytest.approx(expected)
    assert manifest["portable_sidecar"]["sha256"]
    assert not manifest["qualification"]["live_host_claimed"]
    assert manifest["qualification"]["remaining_gates"] == [
        "live_import", "host_evaluation_readback", "animation_hash",
    ]
    if not manifest["capabilities"]["masks"]:
        assert "preapply_target_mask" in manifest["required_bakes"]
    if not manifest["capabilities"]["inbetweens"]:
        assert "expand_inbetweens_to_channels" in manifest["required_bakes"]
