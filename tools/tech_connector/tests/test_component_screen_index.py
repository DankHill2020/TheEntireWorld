"""Correctness and latency coverage for cached component picking."""

from __future__ import annotations

import time

from tech_connector.ui.dcc_viewer.component_picker import ComponentScreenIndex, unique_polygon_edges


def test_component_screen_index_matches_expected_vertex_and_edge() -> None:
    vertices = [(10.0, 10.0, 1.0), (30.0, 10.0, 1.0), (30.0, 30.0, 1.0)]
    edges = unique_polygon_edges([(0, 1, 2)])
    index = ComponentScreenIndex(vertices, edges)

    assert index.nearest_vertex(10.0, 10.0) == 0
    assert index.nearest_edge(20.0, 11.0, tolerance=3.0) == (0, 1)


def test_cached_component_queries_are_bounded_on_a_50k_vertex_grid() -> None:
    columns, rows = 250, 200
    vertices = [(float(column * 4), float(row * 4), 1.0) for row in range(rows) for column in range(columns)]
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            faces.extend(((first, first + columns, first + 1), (first + 1, first + columns, first + columns + 1)))
    index = ComponentScreenIndex(vertices, unique_polygon_edges(faces))

    started = time.perf_counter()
    for _ in range(100):
        assert index.nearest_vertex(500.0, 400.0) is not None
        assert index.nearest_edge(500.0, 400.0) is not None
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert elapsed_ms < 500.0
