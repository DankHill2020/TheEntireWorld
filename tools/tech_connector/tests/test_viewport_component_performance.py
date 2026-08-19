from __future__ import annotations

from tech_connector.ui.viewport_component_performance_service import run_component_picker_performance_baseline


def test_component_picker_50k_vertex_performance_baseline() -> None:
    receipt = run_component_picker_performance_baseline()

    assert receipt.vertices == 50_000
    assert receipt.triangles > 98_000
    assert receipt.edges > 148_000
    assert receipt.selected_vertices > 1_000
    assert receipt.within_baseline_budget
