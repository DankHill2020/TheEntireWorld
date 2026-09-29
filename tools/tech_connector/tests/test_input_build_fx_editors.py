from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    AssetDatabase, AssetOperationsService, audit_input_map, plan_build_profile,
)
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.asset_specialized_editors import (
    BuildProfileEditorWidget, FxBudgetProfilerWidget, InputMapEditorWidget, SkinWeightsEditorWidget,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_input_audit_distinguishes_conflicts_from_priority_shadowing() -> None:
    conflict = audit_input_map({
        "contexts": [{"id": "Gameplay", "priority": 0}],
        "actions": {
            "Jump": {"bindings": [{"context": "Gameplay", "key": "Space"}]},
            "Interact": {"bindings": [{"context": "Gameplay", "key": "Space"}]},
        },
    })
    assert not conflict.valid
    assert any(item.code == "binding_conflict" for item in conflict.diagnostics)

    shadow = audit_input_map({
        "contexts": [{"id": "Gameplay", "priority": 0}, {"id": "Menu", "priority": 10}],
        "actions": {
            "Jump": {"bindings": [{"context": "Gameplay", "key": "Space"}]},
            "Accept": {"bindings": [{"context": "Menu", "key": "Space"}]},
        },
    })
    assert shadow.valid
    assert any(item.code == "priority_shadow" for item in shadow.diagnostics)


def test_build_plan_requires_real_level_and_closes_dependencies(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    level = operations.create_asset("tc.level", "L_Start")
    material = operations.create_asset("tc.material", "M_Level")
    level_record = database.asset(level.asset_id)
    database.register_asset(
        level_record.source_path, level_record.asset_type, asset_id=level_record.asset_id,
        metadata=level_record.metadata, dependencies=[(material.asset_id, "hard")],
    )
    blocked = plan_build_profile(database, {"platform": "windows"})
    assert not blocked.ready
    ready = plan_build_profile(database, {
        "platform": "windows", "configuration": "development", "entry_level": level.asset_id,
        "quality_profile": "high", "incremental": True,
    })
    assert ready.ready
    assert set(ready.asset_ids) == {level.asset_id, material.asset_id}


def test_input_fx_and_build_widgets_expose_actionable_state(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    level = AssetOperationsService(project, database).create_asset("tc.level", "L_Main")

    inputs = InputMapEditorWidget()
    inputs.create_gameplay_defaults()
    assert len(inputs.settings()["actions"]) == 5
    assert not inputs.validation_issues()
    assert "READY" in inputs.audit_label.text()

    profiler = FxBudgetProfilerWidget()
    profiler.load_effect({
        "duration": 5.0, "scalability": "mobile",
        "emitters": [{"spawn_rate": 200.0, "modules": ["initialize", "gravity", "render"]}],
    })
    assert profiler.scalability() == "mobile"
    assert "AUTHORED COST ESTIMATE" in profiler.summary.text()
    assert "module applications/second" in profiler.summary.text()

    build = BuildProfileEditorWidget(database)
    build.load_settings({"entry_level": level.asset_id, "platform": "windows", "configuration": "development"})
    assert not build.validation_issues()
    assert "READY TO PACKAGE" in build.summary.text()


def test_dedicated_input_and_build_editors_persist_models(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    input_asset = operations.create_asset("tc.input_map", "IM_Player")
    build_asset = operations.create_asset("tc.build_profile", "BP_Desktop")
    level = operations.create_asset("tc.level", "L_Game")
    editor = DedicatedAssetEditor(project, database)

    assert editor.open_asset(input_asset.asset_id)
    input_widget = next(widget for key, widget in editor._specialized_widgets if key == "__input_map__")
    input_widget.create_gameplay_defaults()
    assert editor.save(compile_after=False)
    input_payload = json.loads(database.asset(input_asset.asset_id).source_path.read_text(encoding="utf-8"))
    assert input_payload["properties"]["actions"]["Jump"]["bindings"][0]["key"] == "Space"

    assert editor.open_asset(build_asset.asset_id)
    build_widget = next(widget for key, widget in editor._specialized_widgets if key == "__build_profile__")
    build_widget.entry_level.setText(level.asset_id)
    build_widget._changed()
    assert editor.save(compile_after=False)
    build_payload = json.loads(database.asset(build_asset.asset_id).source_path.read_text(encoding="utf-8"))
    assert build_payload["properties"]["entry_level"] == level.asset_id
    assert not build_widget.validation_issues()


def test_skin_weight_editor_visualizes_normalizes_and_enforces_limits() -> None:
    editor = SkinWeightsEditorWidget()
    editor.load_settings({
        "max_influences": 2,
        "influences": [{"name": "Hip"}, {"name": "Knee"}, {"name": "Ankle"}],
        "vertex_weights": [{"vertex_index": 0, "weights": {"Hip": 0.7, "Knee": 0.2, "Ankle": 0.1}}],
    })
    assert editor.validation_issues()
    editor.normalize_and_prune()
    weights = editor.settings()["vertex_weights"][0]["weights"]
    assert len(weights) == 2
    assert sum(weights.values()) == pytest.approx(1.0)
    assert not editor.validation_issues()
    assert "Portable TC skin data" in editor.summary.text()
