from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


class _ViewerHarness:
    def __init__(self, source_path: Path) -> None:
        self._mesh_lod_thread = None
        self._native_scene_model = SimpleNamespace(source_path=str(source_path))
        self.request = None

    def _start_mesh_lod_generation(self, request) -> None:
        self.request = request


def test_viewer_mesh_lod_command_builds_background_request(tmp_path: Path) -> None:
    source = tmp_path / "mesh.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="ascii")
    viewer = _ViewerHarness(source)

    result = ThreeDMeshPainterViewport._execute_tc_engine_command(
        viewer,
        "engine.generate_mesh_lods",
        {
            "output_dir": str(tmp_path / "lods"),
            "levels": [
                {"name": "LOD0", "triangle_ratio": 1.0},
                {"name": "LOD1", "triangle_ratio": 0.5},
            ],
        },
    )

    assert result["started"] is True
    assert viewer.request.source_path == str(source)
    assert [level.triangle_ratio for level in viewer.request.levels] == [1.0, 0.5]
