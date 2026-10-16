from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService
from tech_connector.ui.game_engine.production_tools import (
    BuildDeployPanel,
    EngineConsolePanel,
    PlayerBuildWorker,
    RuntimeProfilerPanel,
)
from tech_connector.game_engine.runtime.tc_player_build_service import PlayerBuildReceipt


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
    assert panel.assets.rowCount() == 1
    assert panel.assets.item(0, 4).text() == "READY"
    opened = []; panel.openAssetRequested.connect(opened.append); panel._open_asset_row(0, 0)
    assert opened == [level.asset_id]
    panel.platform.setCurrentText("linux")
    assert not panel.package()
    assert "Windows only" in panel.log.toPlainText()


def test_build_panel_reports_incremental_cache_and_output_sizes(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    level = AssetOperationsService(tmp_path, database).create_asset("tc.level", "Main", folder="Assets/Levels")
    database.store_derived(level.asset_id, "test-cache", b"cached-data", extension=".bin")
    panel = BuildDeployPanel(tmp_path, database); assert panel.validate()
    assert panel.assets.item(0, 4).text() == "CACHED"
    output = tmp_path / "Build" / "Windows"; content = output / "Content"; content.mkdir(parents=True); (content / "main.tcruntime").write_bytes(b"runtime")
    panel._write_checkpoint("cook", level.destination_path, output, "running")
    report_path = Path(panel._write_build_report("complete", receipt={"entities": 1}))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["output_bytes"] == 7
    assert report["size_by_group"] == {"Content": 7}
    assert report["assets"][0]["state"] == "CACHED"


def test_build_worker_resumes_after_runtime_compile_without_recompiling(tmp_path, monkeypatch) -> None:
    scene = tmp_path / "Main.tcscene"; scene.write_bytes(b"scene")
    output = tmp_path / "Build"; manifest = output / "Content" / "main.tcruntime"; manifest.parent.mkdir(parents=True); manifest.write_bytes(b"runtime")
    compiled = PlayerBuildReceipt(scene=scene, runtime_manifest=manifest, assets=("asset-1",), entities=2)
    checkpoint = {"completed_stages": ["runtime_compile"], "stage_receipts": {"runtime_compile": compiled.to_dict()}}
    monkeypatch.setattr("tech_connector.ui.game_engine.production_tools.compile_tcscene_for_runtime", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("compile repeated")))
    received = []
    def package(_scene, _output, *, compiled_receipt=None):
        assert compiled_receipt is not None and compiled_receipt.runtime_manifest == manifest
        return PlayerBuildReceipt(scene=scene, runtime_manifest=manifest, output_directory=output)
    monkeypatch.setattr("tech_connector.ui.game_engine.production_tools.build_windows_player", package)
    worker = PlayerBuildWorker("package", str(scene), str(output), checkpoint=checkpoint); worker.completed.connect(received.append); worker.run()
    assert received and received[0].output_directory == output


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
