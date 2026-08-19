from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.game_engine.authoring.tc_mesh_modeling_service import MeshTopology
from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    def __init__(self) -> None:
        self._runtime_geometry_thread = None
        self.started = None
        self.mesh = SimpleNamespace(name="Triangle")

    def _canonical_mesh_topology(self):
        return MeshTopology.from_data(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            [(0, 1, 2)],
        ), [], []

    def _start_runtime_geometry_compile(self, kind, arguments) -> None:
        self.started = (kind, arguments)


def test_viewer_routes_point_and_virtual_compilers_to_background_worker(tmp_path) -> None:
    viewer = _ViewerHarness()
    point = ThreeDMeshPainterViewport._execute_tc_engine_command(
        viewer,
        "engine.compile_point_runtime_proxy",
        {"output_path": str(tmp_path / "mesh.tcsurfels"), "page_size": 64},
    )
    point_kind, point_arguments = viewer.started
    virtual = ThreeDMeshPainterViewport._execute_tc_engine_command(
        viewer,
        "engine.compile_virtualized_hard_surface",
        {"output_path": str(tmp_path / "mesh.tcvmesh"), "max_vertices": 32},
    )
    virtual_kind, virtual_arguments = viewer.started

    assert point["started"] and point_kind == "point"
    assert point_arguments["page_size"] == 64
    assert virtual["started"] and virtual_kind == "virtual"
    assert virtual_arguments["max_vertices"] == 32


def test_viewer_builds_valid_runtime_geometry_plan_from_active_mesh() -> None:
    viewer = _ViewerHarness()
    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        viewer,
        "engine.build_runtime_geometry_plan",
        {"target_platforms": ["desktop", "console"]},
    )

    plan = result["runtime_geometry_plan"]
    assert plan["asset_id"] == "Triangle"
    assert plan["inputs"]["triangle_count"] == 1
    assert plan["inputs"]["target_platforms"] == ["desktop", "console"]
    assert viewer.runtime_geometry_plan == plan
