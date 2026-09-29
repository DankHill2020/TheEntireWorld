from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService
from tech_connector.ui.game_engine.asset_editor_session import AssetEditorSession
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_session_tracks_history_saved_state_and_recovery(tmp_path) -> None:
    session = AssetEditorSession(tmp_path)
    assert session.begin("asset-1", "hash-1", {"roughness": 0.5}) is None
    assert not session.dirty
    assert session.record({"roughness": 0.25}, "Change Roughness")
    assert session.can_undo and session.dirty
    recovery = session.write_recovery({"roughness": 0.25})
    assert recovery is not None and recovery.is_file()

    reopened = AssetEditorSession(tmp_path)
    assert reopened.begin("asset-1", "hash-1", {"roughness": 0.5}) == {"roughness": 0.25}
    assert reopened.dirty
    assert reopened.undo() == {"roughness": 0.5}
    reopened.write_recovery({"roughness": 0.5})
    assert not recovery.exists()
    assert reopened.redo() == {"roughness": 0.25}
    reopened.mark_saved({"roughness": 0.25})
    assert not reopened.dirty


def test_recovery_is_not_applied_to_a_changed_source(tmp_path) -> None:
    session = AssetEditorSession(tmp_path)
    session.begin("asset-1", "old-hash", {"value": 1})
    session.record({"value": 2}, "Edit")
    session.write_recovery({"value": 2})

    reopened = AssetEditorSession(tmp_path)
    assert reopened.begin("asset-1", "new-hash", {"value": 3}) is None
    assert not reopened.dirty


def test_dedicated_editor_undo_redo_and_save_state(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    material = AssetOperationsService(project, database).create_asset("tc.material", "M_Undo")
    editor = DedicatedAssetEditor(project, database)
    assert editor.open_asset(material.asset_id)

    roughness = next(
        editor.properties.topLevelItem(index)
        for index in range(editor.properties.topLevelItemCount())
        if editor.properties.topLevelItem(index).data(0, Qt.UserRole) == "roughness"
    )
    original = roughness.text(1)
    roughness.setText(1, "0.125")
    editor._capture_edit_snapshot()
    assert editor.session.dirty and editor.undo_button.isEnabled()
    assert editor.undo()
    assert roughness.text(1) == original
    assert editor.redo()
    assert roughness.text(1) == "0.125"
    assert editor.save(compile_after=False)
    assert not editor.session.dirty
    assert editor.undo_button.isEnabled()
    assert not editor.title_label.text().endswith(" *")
    payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert payload["properties"]["roughness"] == pytest.approx(0.125)


def test_switching_assets_flushes_pending_recovery_to_original_asset(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    first = operations.create_asset("tc.material", "M_First")
    second = operations.create_asset("tc.material", "M_Second")
    editor = DedicatedAssetEditor(project, database)
    assert editor.open_asset(first.asset_id)
    roughness = next(
        editor.properties.topLevelItem(index)
        for index in range(editor.properties.topLevelItemCount())
        if editor.properties.topLevelItem(index).data(0, Qt.UserRole) == "roughness"
    )
    roughness.setText(1, "0.875")
    assert editor._edit_capture_timer.isActive()
    first_recovery = editor.session.recovery_path

    assert editor.open_asset(second.asset_id)
    assert first_recovery.is_file()
    recovered = json.loads(first_recovery.read_text(encoding="utf-8"))
    assert recovered["asset_id"] == first.asset_id
    assert recovered["values"]["roughness"] == pytest.approx(0.875)
