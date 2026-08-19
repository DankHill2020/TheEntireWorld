"""Collision response and interchange coverage for fleshy skin clusters."""

from __future__ import annotations

from tech_connector.game_engine.deformation import (
    DeformationWeightMap,
    DeformationStackRuntime,
    FleshDeformerSettings,
    FleshRuntimeState,
    attach_flesh_deformer,
    attach_jiggle_deformer,
    evaluate_flesh,
    flesh_export_contract,
)
from tech_connector.game_engine.deformation.skinning_tool_service import (
    export_skin_weights_payload,
    import_skin_weights_payload,
    skin_cluster_from_rig_graph,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph
from tech_connector.game_engine.scene.tc_native_scene_compiler_service import compile_graph_to_tc_native


def test_flesh_projects_painted_vertices_out_of_sphere_collision() -> None:
    targets = [(0.0, 0.5, 0.0), (2.0, 0.0, 0.0)]
    influence = DeformationWeightMap("flesh", [1.0, 0.0])
    state = FleshRuntimeState()
    settings = FleshDeformerSettings(collision_radius=0.05, substeps=2)
    evaluate_flesh(targets, influence, state, settings, 1.0 / 60.0)

    result = evaluate_flesh(
        targets, influence, state, settings, 1.0 / 60.0,
        colliders=[{"type": "sphere", "center": (0.0, 0.0, 0.0), "radius": 1.0}],
    )

    assert result[0][1] >= 1.05 - 1.0e-6
    assert result[1] == targets[1]
    assert state.collision_count > 0


def test_fleshy_skin_keeps_canonical_weights_round_trip_portable() -> None:
    graph = EditableRigGraph()
    joint = graph.add_joint("Root", joint_id="joint_root")
    skin_id = graph.add_skin("body_mesh", [joint], skin_id="body_skin")
    graph.skins[skin_id].update({
        "vertex_count": 2,
        "max_influences_per_vertex": 4,
        "weight_overrides": {"0": {joint: 1.0}, "1": {joint: 1.0}},
    })
    influence = DeformationWeightMap("flesh", [0.25, 1.0])

    flesh_id = attach_flesh_deformer(graph, skin_id, "body_mesh", influence)
    cluster = skin_cluster_from_rig_graph(graph, skin_id)
    payload = export_skin_weights_payload(cluster)
    imported = import_skin_weights_payload(payload)

    assert graph.deformers[flesh_id]["type"] == "flesh"
    assert graph.deformers[flesh_id]["evaluation_mode"] == "runtime_local"
    assert graph.skins[skin_id]["fleshy"]["canonical_skin_preserved"]
    assert imported.vertex_weights == cluster.vertex_weights
    assert imported.influence_names == cluster.influence_names
    assert imported.metadata["flesh"]["deformer_id"] == flesh_id
    assert imported.metadata["interchange_contract"]["canonical_skin_weights_preserved"]
    assert payload["interchange"]["canonical_skin_weights"] == "authoritative"
    assert payload["interchange"]["safe_without_extension"]
    assert payload["extensions"]["tech_connector.flesh.v1"]["deformer_id"] == flesh_id


def test_flesh_export_contracts_keep_skin_and_report_destination_fallback() -> None:
    for destination in ("maya", "blender", "houdini", "unreal", "usd", "fbx", "gltf"):
        contract = flesh_export_contract(destination)
        assert contract["canonical_skin_preserved"]
        assert contract["canonical_skin"]
        assert contract["flesh_transfer"]
        assert "point_cache" in contract["fallback_priority"]


def test_ordered_jiggle_then_flesh_stack_reports_collision_telemetry() -> None:
    graph = EditableRigGraph()
    joint = graph.add_joint("Root", joint_id="root")
    skin_id = graph.add_skin("body", [joint], skin_id="skin")
    influence = DeformationWeightMap("secondary", [1.0])
    jiggle_id = attach_jiggle_deformer(graph, skin_id, "body", influence, deformer_id="jiggle")
    flesh_id = attach_flesh_deformer(graph, skin_id, "body", influence, deformer_id="flesh")
    runtime = DeformationStackRuntime()
    target = [(0.0, 0.5, 0.0)]
    collider = [{"type": "sphere", "center": (0.0, 0.0, 0.0), "radius": 1.0}]

    runtime.evaluate(graph, "body", target, 1.0 / 60.0, colliders=collider)
    result, telemetry = runtime.evaluate(graph, "body", target, 1.0 / 60.0, colliders=collider)

    assert telemetry.evaluated_deformers == [jiggle_id, flesh_id]
    assert telemetry.collision_contacts > 0
    assert telemetry.evaluation_ms > 0.0
    assert result[0][1] >= 1.01 - 1.0e-6


def test_native_identity_compilation_remaps_flesh_to_canonical_skin() -> None:
    graph = EditableRigGraph()
    joint = graph.add_joint("Root", joint_id="source_joint")
    skin_id = graph.add_skin("body", [joint], skin_id="source_skin")
    flesh_id = attach_flesh_deformer(
        graph, skin_id, "body", DeformationWeightMap("flesh", [1.0]), deformer_id="source_flesh"
    )

    receipt = compile_graph_to_tc_native(graph, "maya")
    compiled_skin_id = receipt["skin_ids"][skin_id]
    compiled_flesh_id = receipt["deformer_ids"][flesh_id]

    assert graph.skins[compiled_skin_id]["fleshy"]["deformer_id"] == compiled_flesh_id
    assert graph.deformers[compiled_flesh_id]["settings"]["source_id"] == compiled_skin_id
