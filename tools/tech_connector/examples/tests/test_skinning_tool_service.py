from __future__ import annotations

import pytest

from tech_connector.services.dcc.skinning_tool_service import (
    add_skin_influence,
    SkinInfluence,
    apply_skin_cluster_to_rig_graph,
    auto_skin_cluster,
    auto_skin_rig_graph,
    available_skin_bind_methods,
    bind_skin,
    bind_skin_from_distance,
    copy_skin_weights,
    export_skin_weights_payload,
    import_skin_weights_payload,
    mirror_influence_name,
    mirror_skin_weights,
    normalize_skin_weights,
    paint_skin_weight,
    prune_skin_weights,
    remove_skin_influence,
    skin_cluster_summary,
    spatial_smooth_skin_weights,
    smooth_skin_weights,
    transfer_skin_weights,
)
from tech_connector.game_engine.deformation.spatial_skin_smoothing_service import (
    detect_deformation_ripple_indices,
    detect_weight_outlier_indices,
    estimate_spatial_smoothing_radius,
    spatial_smooth_weight_rows,
)


def test_normalize_and_prune_skin_weights_are_engine_safe() -> None:
    weights = normalize_skin_weights({"Root": 0.2, "Spine": 0.3, "Arm": 0.5, "Tiny": 0.00001}, max_influences=3)
    pruned = prune_skin_weights(weights, threshold=0.05, max_influences=2)

    assert len(weights) == 3
    assert round(sum(weights.values()), 6) == 1.0
    assert len(pruned) == 2
    assert round(sum(pruned.values()), 6) == 1.0


def test_distance_bind_prefers_nearest_influence() -> None:
    cluster = bind_skin_from_distance(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        influences=[
            SkinInfluence("L_Hip", (0.0, 0.0, 0.0)),
            SkinInfluence("R_Hip", (10.0, 0.0, 0.0)),
        ],
        max_influences=2,
    )

    assert cluster.vertex_weights[0].weights["L_Hip"] > 0.99
    assert cluster.vertex_weights[1].weights["R_Hip"] > 0.99
    assert skin_cluster_summary(cluster)["engine_ready"]


def test_bind_methods_include_heat_geodesic_voxel_and_auto() -> None:
    methods = {row["key"]: row for row in available_skin_bind_methods()}
    result = bind_skin(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0)],
        influences=[SkinInfluence("Root", (0.0, 0.0, 0.0))],
        bind_method="geodesic voxel",
    )

    assert {"distance", "heat", "geodesic_voxel", "auto"}.issubset(methods)
    assert result.cluster.metadata["bind_method"] == "geodesic_voxel"
    assert result.warnings


def test_auto_skin_and_maya_export_payload_round_trip_to_tc_cluster() -> None:
    result = auto_skin_cluster(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)],
        influences=[SkinInfluence("Root", (0.0, 0.0, 0.0)), SkinInfluence("Tip", (4.0, 0.0, 0.0))],
        bind_method="heat",
        smooth_iterations=1,
    )
    payload = export_skin_weights_payload(result.cluster)
    imported = import_skin_weights_payload(payload)

    assert payload["schema"] == "tech_connector.skin_weights.v1"
    assert imported.mesh_id == "HeroMesh"
    assert imported.influence_names == ("Root", "Tip")
    assert imported.vertex_count == 2


def test_auto_skin_rig_graph_writes_internal_tc_skin_overrides() -> None:
    from tech_connector.services.dcc.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX

    graph = EditableRigGraph()
    root_matrix = IDENTITY_MATRIX[:]
    tip_matrix = IDENTITY_MATRIX[:]
    tip_matrix[12] = 4.0
    root = graph.add_joint("Root", joint_id="Root_JNT", local_matrix=root_matrix)
    tip = graph.add_joint("Tip", parent_id=root, joint_id="Tip_JNT", local_matrix=tip_matrix)

    result = auto_skin_rig_graph(
        graph,
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)],
        joint_ids=[root, tip],
        bind_method="auto",
        skin_id="HeroSkin",
        smooth_iterations=0,
    )

    assert result.ok
    assert result.metadata["skin_id"] == "HeroSkin"
    assert graph.skins["HeroSkin"]["runtime_mode"] == "tc_native"
    assert graph.skins["HeroSkin"]["joint_ids"] == ["Root_JNT", "Tip_JNT"]
    assert graph.skins["HeroSkin"]["weight_overrides"]["0"]["Root_JNT"] > 0.99
    assert graph.skins["HeroSkin"]["weight_overrides"]["1"]["Tip_JNT"] > 0.99


def test_apply_skin_cluster_rejects_joints_missing_from_internal_rig() -> None:
    from tech_connector.services.dcc.federated_scene_service import EditableRigGraph

    graph = EditableRigGraph()
    cluster = bind_skin_from_distance(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0)],
        influences=[SkinInfluence("Missing_JNT", (0.0, 0.0, 0.0))],
    )

    try:
        apply_skin_cluster_to_rig_graph(graph, cluster)
    except KeyError as exc:
        assert "not in the TC rig graph" in str(exc)
    else:
        raise AssertionError("Expected missing TC rig graph joint rejection")


def test_paint_smooth_mirror_and_copy_weights() -> None:
    cluster = bind_skin_from_distance(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (10.0, 0.0, 0.0)],
        influences=[
            SkinInfluence("L_Arm", (0.0, 0.0, 0.0)),
            SkinInfluence("R_Arm", (10.0, 0.0, 0.0)),
        ],
        max_influences=2,
    )

    painted = paint_skin_weight(cluster, vertex_indices=[1], influence="L_Arm", value=0.75, strength=1.0)
    smoothed = smooth_skin_weights(painted.cluster, vertex_indices=[1], strength=0.5)
    mirrored = mirror_skin_weights(smoothed.cluster)
    copied = copy_skin_weights(mirrored.cluster, target_mesh_id="TargetMesh", target_vertex_count=2)
    transferred = transfer_skin_weights(mirrored.cluster, target_mesh_id="TransferMesh", target_vertex_count=2, strategy="closestPoint")

    assert painted.ok
    assert painted.changed_vertices == (1,)
    assert round(sum(smoothed.cluster.vertex_weights[1].weights.values()), 6) == 1.0
    assert mirror_influence_name("L_Arm") == "R_Arm"
    assert "R_Arm" in mirrored.cluster.vertex_weights[0].weights
    assert mirrored.cluster.influence_names == ("R_Arm", "L_Arm")
    assert copied.mesh_id == "TargetMesh"
    assert copied.vertex_count == 2
    assert transferred.cluster.mesh_id == "TransferMesh"
    assert transferred.warnings


def test_spatial_smooth_bridges_disconnected_nearby_surface_vertices() -> None:
    cluster = bind_skin_from_distance(
        mesh_id="BrokenTopology",
        vertices=[(0.0, 0.0, 0.0), (0.05, 0.0, 0.0), (4.0, 0.0, 0.0)],
        influences=[SkinInfluence("A", (0.0, 0.0, 0.0)), SkinInfluence("B", (4.0, 0.0, 0.0))],
        max_influences=2,
    )
    cluster = cluster.with_vertex_weights((
        cluster.vertex_weights[0],
        type(cluster.vertex_weights[1])(1, {"B": 1.0}),
        cluster.vertex_weights[2],
    ))
    result = spatial_smooth_skin_weights(
        cluster,
        positions=[(0.0, 0.0, 0.0), (0.05, 0.0, 0.0), (4.0, 0.0, 0.0)],
        center=(0.025, 0.0, 0.0),
        radius=0.2,
        strength=1.0,
        iterations=1,
    )

    assert result.changed_vertices == (0, 1)
    assert result.cluster.vertex_weights[0].weights["B"] > 0.0
    assert result.cluster.vertex_weights[1].weights["A"] > 0.0


def test_spatial_smooth_area_weights_prevent_dense_patch_from_crowding_out_surface() -> None:
    positions = [(0.0, 0.0, 0.0)] + [
        (distance, 0.0, 0.0) for distance in (0.01, 0.02, 0.03, 0.04, 0.05)
    ] + [(0.1, 0.0, 0.0)]
    rows = [{"A": 1.0} for _ in positions]
    rows[-1] = {"B": 1.0}

    unweighted, _ = spatial_smooth_weight_rows(
        positions,
        rows,
        radius=1.0,
        strength=1.0,
        iterations=1,
        target_indices=[0],
        max_neighbors=3,
        max_influences=2,
    )
    area_weighted, _ = spatial_smooth_weight_rows(
        positions,
        rows,
        radius=1.0,
        strength=1.0,
        iterations=1,
        target_indices=[0],
        max_neighbors=3,
        max_influences=2,
        sample_weights=[1.0] * (len(positions) - 1) + [100.0],
    )

    assert unweighted[0]["B"] > 0.0
    assert area_weighted[0]["B"] > unweighted[0]["B"]


def test_automatic_spatial_radius_scales_and_accounts_for_sparse_regions() -> None:
    positions = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0)]
    uniform = estimate_spatial_smoothing_radius(
        positions,
        sample_weights=[1.0, 1.0, 1.0],
    )
    mixed_density = estimate_spatial_smoothing_radius(
        positions,
        sample_weights=[1.0, 1.0, 25.0],
    )
    scaled = estimate_spatial_smoothing_radius(
        [(x * 10.0, y * 10.0, z * 10.0) for x, y, z in positions],
        sample_weights=[100.0, 100.0, 2500.0],
    )

    assert mixed_density > uniform
    assert scaled == pytest.approx(mixed_density * 10.0)


def test_hybrid_surface_smoothing_follows_connected_rows_over_spatial_distractors() -> None:
    positions = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (0.01, 0.0, 0.0),
    ]
    rows = [{"A": 1.0}, {"B": 1.0}, {"A": 1.0}]
    adjacency = [[1], [0], []]

    spatial_only, _ = spatial_smooth_weight_rows(
        positions,
        rows,
        radius=0.1,
        strength=1.0,
        target_indices=[0],
        max_influences=2,
    )
    hybrid, _ = spatial_smooth_weight_rows(
        positions,
        rows,
        radius=0.1,
        strength=1.0,
        target_indices=[0],
        max_influences=2,
        topology_neighbors=adjacency,
        topology_share=0.8,
    )

    assert spatial_only[0].get("B", 0.0) == 0.0
    assert hybrid[0]["B"] > 0.75


def test_weight_outlier_detection_finds_spike_without_flagging_smooth_gradient() -> None:
    adjacency = [[1], [0, 2], [1, 3], [2, 4], [3]]
    spike_rows = [
        {"A": 1.0},
        {"A": 1.0},
        {"B": 1.0},
        {"A": 1.0},
        {"A": 1.0},
    ]
    assert detect_weight_outlier_indices(spike_rows, adjacency) == (2,)

    gradient_rows = [
        {"A": 1.0},
        {"A": 0.75, "B": 0.25},
        {"A": 0.5, "B": 0.5},
        {"A": 0.25, "B": 0.75},
        {"B": 1.0},
    ]
    assert detect_weight_outlier_indices(gradient_rows, adjacency) == ()


def test_deformation_ripple_detection_ignores_linear_bend_and_finds_saw_tooth() -> None:
    bind = [(float(index), 0.0, 0.0) for index in range(5)]
    adjacency = [[1], [0, 2], [1, 3], [2, 4], [3]]
    smooth_pose = [(x, 0.0, x * 0.2) for x, _y, _z in bind]
    jagged_pose = [
        (x, 0.0, offset) for (x, _y, _z), offset in zip(bind, (0.0, 0.4, 0.0, 0.4, 0.0))
    ]

    assert detect_deformation_ripple_indices(bind, smooth_pose, adjacency) == ()
    assert detect_deformation_ripple_indices(bind, jagged_pose, adjacency) == (1, 2, 3)


def test_add_and_remove_influence_preserve_valid_normalized_rows() -> None:
    cluster = bind_skin_from_distance(
        mesh_id="HeroMesh",
        vertices=[(0.0, 0.0, 0.0)],
        influences=[SkinInfluence("Root", (0.0, 0.0, 0.0))],
        max_influences=8,
    )
    added = add_skin_influence(cluster, SkinInfluence("Spine", (1.0, 0.0, 0.0)))
    blocked = remove_skin_influence(added.cluster, "Root")
    removed = remove_skin_influence(added.cluster, "Root", fallback_influence="Spine")

    assert added.cluster.influence_names == ("Root", "Spine")
    assert blocked.ok is False
    assert removed.ok is True
    assert removed.cluster.influence_names == ("Spine",)
    assert removed.cluster.vertex_weights[0].weights == {"Spine": 1.0}
