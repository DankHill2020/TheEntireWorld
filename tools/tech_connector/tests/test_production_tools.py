from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService
from tech_connector.ui.game_engine.production_tools import (
    BuildDeployPanel,
    EngineConsolePanel,
    RuntimeProfilerPanel,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_build_deploy_panel_uses_registered_level_and_blocks_unshipped_target(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    level = AssetOperationsService(tmp_path, database).create_asset("tc.level", "Main", folder="Assets/Levels")
    panel = BuildDeployPanel(tmp_path, database)

    assert panel.entry_level.currentData() == level.asset_id
    assert panel.validate()
    assert "Assets: 1" in panel.log.toPlainText()
    panel.platform.setCurrentText("linux")
    assert not panel.package()
    assert "Windows only" in panel.log.toPlainText()


def test_engine_console_panel_keeps_a_persistent_python_session(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    workspace = SimpleNamespace(project_root=tmp_path, database=database, viewport=SimpleNamespace())
    panel = EngineConsolePanel(workspace)

    panel.input.setPlainText("answer = 40")
    assert panel.execute()
    panel.input.setPlainText("answer + 2")
    assert panel.execute()
    assert "42" in panel.output.toPlainText()


def test_runtime_profiler_panel_summarizes_capture_and_diagnostics(tmp_path) -> None:
    capture = tmp_path / "runtime-profile.jsonl"
    rows = [
        {"type": "frame", "frame_ms": 10.0, "graph_ms": 2.0, "physics_ms": 1.0, "gpu_ms": 5.0},
        {"type": "frame", "frame_ms": 20.0, "graph_ms": 4.0, "physics_ms": 3.0, "gpu_ms": 9.0},
    ]
    capture.write_text("\n".join([*(json.dumps(row) for row in rows), "OK graph node_1", "warning: sample"]), encoding="utf-8")
    panel = RuntimeProfilerPanel()

    panel.watch(capture)

    assert panel.metrics.item(0, 1).text() == "15.000"
    assert panel.metrics.item(1, 3).text() == "4.000"
    assert "OK graph node_1" in panel.details.toPlainText()
    assert "warning: sample" in panel.details.toPlainText()
