"""Reproducible performance evidence for screen-space component picking."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time

from tech_connector.ui.dcc_viewer.component_picker import (
    nearest_edge,
    nearest_vertex_index,
    unique_polygon_edges,
    vertices_in_rectangle,
)


@dataclass(frozen=True)
class ComponentPickerPerformanceReceipt:
    schema: str
    vertices: int
    triangles: int
    edges: int
    index_build_ms: float
    point_pick_ms: float
    marquee_ms: float
    selected_vertices: int
    within_baseline_budget: bool
    baseline_budget_ms: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_component_picker_performance_baseline(
    *, columns: int = 250, rows: int = 200, baseline_budget_ms: float = 5000.0,
) -> ComponentPickerPerformanceReceipt:
    """Exercise a 50k-vertex default grid without GUI or renderer variability."""
    columns = max(2, int(columns))
    rows = max(2, int(rows))
    vertices = [
        (float(column * 4), float(row * 4), 1.0)
        for row in range(rows)
        for column in range(columns)
    ]
    faces: list[tuple[int, int, int]] = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            first = row * columns + column
            second = first + 1
            third = first + columns
            fourth = third + 1
            faces.extend(((first, third, second), (second, third, fourth)))

    started = time.perf_counter()
    edges = unique_polygon_edges(faces)
    index_build_ms = (time.perf_counter() - started) * 1000.0
    center_x, center_y = columns * 2.0, rows * 2.0
    started = time.perf_counter()
    vertex = nearest_vertex_index(vertices, center_x, center_y)
    edge = nearest_edge(vertices, edges, center_x, center_y)
    point_pick_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter()
    selected = vertices_in_rectangle(
        vertices, center_x - 100.0, center_y - 100.0, center_x + 100.0, center_y + 100.0,
    )
    marquee_ms = (time.perf_counter() - started) * 1000.0
    elapsed = index_build_ms + point_pick_ms + marquee_ms
    return ComponentPickerPerformanceReceipt(
        schema="tech_connector.component_picker_performance.v1",
        vertices=len(vertices),
        triangles=len(faces),
        edges=len(edges),
        index_build_ms=index_build_ms,
        point_pick_ms=point_pick_ms,
        marquee_ms=marquee_ms,
        selected_vertices=len(selected),
        within_baseline_budget=bool(vertex is not None and edge is not None and elapsed <= float(baseline_budget_ms)),
        baseline_budget_ms=float(baseline_budget_ms),
    )
