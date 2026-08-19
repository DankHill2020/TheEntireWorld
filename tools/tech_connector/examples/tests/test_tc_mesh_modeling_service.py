import pytest

from tech_connector.services.dcc.tc_mesh_modeling_service import (
    MeshTopology,
    bevel_edges,
    bridge_edge_loops,
    delete_faces,
    extrude_faces,
    merge_vertices,
    split_edge_loop,
    triangulate_faces,
)


def _quad() -> MeshTopology:
    return MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [(0, 1, 2, 3)],
    )


def test_region_extrude_creates_top_and_boundary_walls() -> None:
    result = extrude_faces(_quad(), [0], distance=2.0)

    assert len(result.topology.vertices) == 8
    assert len(result.topology.faces) == 5
    assert result.topology.vertices[4] == pytest.approx((0, 0, 2))
    assert result.topology.faces[0] == (4, 5, 6, 7)
    assert len(result.created_faces) == 4


def test_region_extrude_does_not_build_internal_walls() -> None:
    topology = MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
        [(0, 1, 4, 3), (1, 2, 5, 4)],
    )
    result = extrude_faces(topology, [0, 1], distance=1.0)

    assert len(result.topology.vertices) == 12
    assert len(result.topology.faces) == 8


def test_triangulate_delete_merge_and_bridge_are_valid_topology_edits() -> None:
    triangulated = triangulate_faces(_quad())
    assert triangulated.topology.faces == ((0, 1, 2), (0, 2, 3))

    deleted = delete_faces(triangulated.topology, [1])
    assert deleted.topology.faces == ((0, 1, 2),)

    merged = merge_vertices(triangulated.topology, [0, 1])
    assert len(merged.topology.vertices) == 3
    assert len(merged.topology.faces) == 1

    bridge_source = MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 2), (1, 0, 2), (1, 1, 2), (0, 1, 2)],
        [(0, 1, 2, 3), (4, 7, 6, 5)],
    )
    bridged = bridge_edge_loops(bridge_source, [0, 1, 2, 3], [4, 5, 6, 7])
    assert len(bridged.topology.faces) == 6
    bridged.topology.validate()


def test_split_edge_loop_traverses_quad_strip_and_preserves_shared_vertices() -> None:
    topology = MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
        [(0, 1, 4, 3), (1, 2, 5, 4)],
    )

    result = split_edge_loop(topology, (0, 3), divisions=2)

    assert len(result.topology.vertices) == 12
    assert len(result.topology.faces) == 6
    assert len(result.created_vertices) == 6
    assert result.metadata["divisions"] == 2
    assert set(map(tuple, result.metadata["ring_edges"])) == {(0, 3), (1, 4), (2, 5)}
    result.topology.validate()


def test_split_edge_loop_rejects_non_quad_seed() -> None:
    topology = MeshTopology.from_data([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])

    with pytest.raises(ValueError, match="quadrilateral strip"):
        split_edge_loop(topology, (0, 1))


def test_bevel_boundary_edge_creates_inset_strip() -> None:
    result = bevel_edges(_quad(), [(0, 1)], width=0.2)

    assert len(result.topology.vertices) == 6
    assert len(result.topology.faces) == 2
    assert result.topology.faces[1] == (0, 1, 5, 4)
    assert result.metadata["segments"] == 1
    result.topology.validate()


def test_bevel_manifold_edge_creates_center_strip_and_endpoint_caps() -> None:
    topology = MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1, 0, 1), (1, 1, 1)],
        [(0, 1, 2, 3), (1, 4, 5, 2)],
    )

    result = bevel_edges(topology, [(1, 2)], width=0.1)

    assert len(result.topology.vertices) == 10
    assert len(result.topology.faces) == 5
    assert len(result.created_faces) == 3
    result.topology.validate()


def test_bevel_requires_vertex_disjoint_edges_per_pass() -> None:
    with pytest.raises(ValueError, match="vertex-disjoint"):
        bevel_edges(_quad(), [(0, 1), (1, 2)], width=0.1)
