from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.authoring.tc_mesh_modeling_service import (
    MeshTopology, bevel_edges, bridge_edge_loops, delete_faces, extrude_faces,
    merge_vertices, split_edge_loop, triangulate_faces,
)


def _quad_grid(columns: int, rows: int) -> MeshTopology:
    vertices = [(float(x), 0.0, float(y)) for y in range(rows + 1) for x in range(columns + 1)]
    stride = columns + 1
    faces = [(y * stride + x, y * stride + x + 1, (y + 1) * stride + x + 1, (y + 1) * stride + x)
             for y in range(rows) for x in range(columns)]
    return MeshTopology.from_data(vertices, faces)


def test_topology_kernel_has_bounded_representative_mesh_performance() -> None:
    topology = _quad_grid(100, 100)
    started = time.perf_counter()
    triangulated = triangulate_faces(topology)
    elapsed = time.perf_counter() - started

    assert len(triangulated.topology.vertices) == 10_201
    assert len(triangulated.topology.faces) == 20_000
    assert elapsed < 2.0


def test_topology_failure_is_transactional_and_result_round_trips() -> None:
    topology = _quad_grid(2, 2)
    before = (topology.vertices, topology.faces)
    with pytest.raises((ValueError, IndexError)):
        extrude_faces(topology, [999], distance=1.0)
    assert (topology.vertices, topology.faces) == before

    result = extrude_faces(topology, [0], distance=0.25)
    encoded = json.dumps({"vertices": result.topology.vertices, "faces": result.topology.faces}, sort_keys=True)
    restored = MeshTopology.from_data(**json.loads(encoded))
    assert restored == result.topology


def test_every_modeling_operation_produces_valid_topology() -> None:
    grid = _quad_grid(2, 2)
    operations = [
        split_edge_loop(grid, (0, 1)),
        bevel_edges(grid, [(0, 1)], width=0.1),
        extrude_faces(grid, [0], distance=0.2),
        delete_faces(grid, [0]),
        triangulate_faces(grid),
    ]
    duplicate = MeshTopology.from_data(
        [(0, 0, 0), (0, 0, 0), (1, 0, 0), (0, 1, 0)],
        [(0, 2, 3), (1, 2, 3)],
    )
    operations.append(merge_vertices(duplicate, [0, 1], threshold=0.001))
    loops = MeshTopology.from_data(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
         (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
        [(0, 1, 2, 3), (4, 7, 6, 5)],
    )
    operations.append(bridge_edge_loops(loops, [0, 1, 2, 3], [4, 5, 6, 7]))
    for result in operations:
        result.topology.validate()
        assert result.operation.startswith("modeling.")
