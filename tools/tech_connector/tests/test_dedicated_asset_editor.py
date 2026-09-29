from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService, PrefabService
from tech_connector.ui.game_engine.asset_editor_workspace import (
    DedicatedAssetEditor, editor_pages_for_asset,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_editor_exposes_specialized_pages_and_saves_shared_properties(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Hero")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(material.asset_id)
    assert editor.pages.count() == len(editor_pages_for_asset("tc.material"))
    assert editor.pages.tabText(0) == "Preview"
    assert editor.save_button.isEnabled()

    roughness = next(
        editor.properties.topLevelItem(index)
        for index in range(editor.properties.topLevelItemCount())
        if editor.properties.topLevelItem(index).data(0, Qt.UserRole) == "roughness"
    )
    roughness.setText(1, "0.25")
    assert editor.save()

    payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert payload["properties"]["roughness"] == 0.25


def test_editor_preview_signal_and_import_settings_are_truthful(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "tone.wav"
    source.write_bytes(b"RIFF-test")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    audio = operations.import_asset(source)
    editor = DedicatedAssetEditor(project, database)
    previews = []
    editor.previewRequested.connect(lambda path, type_id, asset_id: previews.append((path, type_id, asset_id)))

    assert editor.open_asset(audio.asset_id)
    assert editor.pages.tabText(0) == "Waveform"
    assert editor._mode == "import"
    assert editor.reimport_button.isEnabled()
    editor.preview()

    assert previews[0][1:] == ("tc.audio_clip", audio.asset_id)


def test_cloth_editor_is_direct_setup_not_a_required_node_graph(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    cloth = operations.create_asset("tc.cloth", "Cape")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(cloth.asset_id)
    assert editor.pages.tabText(0) == "Setup & Paint"
    assert all("Graph" not in editor.pages.tabText(index) for index in range(editor.pages.count()))


def test_prefab_editor_uses_prefab_mode_and_compiles_runtime_artifact(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    prefab = PrefabService(project, database).create_from_entities(
        "InteractiveDoor", [{"name": "Door", "open": False}],
    )
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(prefab.asset_id)
    assert editor.pages.tabText(1) == "Hierarchy"
    assert any(key == "__prefab__" for key, _widget in editor._specialized_widgets)
    assert editor.compile()
    assert database.derived(prefab.asset_id, "prefab_runtime:desktop:high") is not None
