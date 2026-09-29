from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import AssetDatabase, AssetProductionService, GameplayClassService, TCEditorAPI
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor, editor_pages_for_asset
from tech_connector.ui.game_engine.asset_specialized_editors import (
    GameplayClassDebuggerWidget,
    GameplayClassDefinitionEditorWidget,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_gameplay_class_resolves_inheritance_and_compiles_runtime(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = GameplayClassService(tmp_path, database)
    parent = service.create(
        "BaseCharacter", class_kind="character",
        variables=[{"name": "Health", "type": "float", "default": 100.0, "replication": "replicated"}],
    )
    child = service.create("Hero", class_kind="character", parent_class_id=parent.asset_id)
    service.update(child.asset_id, {
        "components": [
            {"id": "root", "name": "Root", "type": "transform", "parent_id": "", "enabled": True, "properties": {}},
            {"id": "camera", "name": "Camera", "type": "camera", "parent_id": "root", "enabled": True, "properties": {}},
        ],
        "variables": [{"name": "Health", "type": "float", "default": 150.0, "replication": "replicated"}],
        "interfaces": ["Damageable"],
    })

    resolved = service.resolve(child.asset_id)
    assert resolved["inheritance_chain"] == [parent.asset_id, child.asset_id]
    assert next(row for row in resolved["variables"] if row["name"] == "Health")["default"] == 150.0
    assert {row["id"] for row in resolved["components"]} == {"root", "camera"}
    assert resolved["provenance"]["variables"]["Health"] == child.asset_id
    assert not [row for row in service.validate(child.asset_id) if row.severity == "error"]

    artifact = service.compile(child.asset_id, platform="windows", quality="high")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["schema"] == "tech_connector.gameplay_class_runtime.v1"
    assert payload["event_manifest"]["valid"]
    assert payload["class"]["interfaces"] == ["Damageable"]
    cook = AssetProductionService(tmp_path, database).cook_manifest([child.asset_id], platform="windows", quality="high")
    manifest = json.loads(cook.artifact.path.read_text(encoding="utf-8"))
    child_row = next(row for row in manifest["assets"] if row["asset_id"] == child.asset_id)
    assert any(row["kind"] == "gameplay_class_runtime" for row in child_row["derived_outputs"])


def test_gameplay_class_debugger_executes_source_mapped_runtime_graph(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = GameplayClassService(tmp_path, database)
    receipt = service.create("ScoreKeeper")
    service.update(receipt.asset_id, {"event_graph": {
        "entry_event": "On Begin Play",
        "nodes": [{
            "id": "set_score", "title": "Set Score", "opcode": "variable.set",
            "inputs": ["name:str", "value:any"], "outputs": ["value:any"],
            "parameters": {"name": "Score", "value": 10}, "x": 20.0, "y": 20.0,
        }],
        "connections": [],
    }})

    result = service.debug_event(receipt.asset_id, {"metadata": {"variables": {}}})
    assert result["status"] == "complete"
    assert result["outputs"]["set_score"] == 10
    assert result["runtime_state"]["metadata"]["variables"]["Score"] == 10
    assert result["traces"][0]["node_id"] == "set_score"
    assert result["traces"][0]["operation"] == "variable.set"


def test_gameplay_class_python_api_and_editor_pages_have_full_workflow(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    api = TCEditorAPI(tmp_path, database=database)
    receipt = api.create_gameplay_class("Interactable", variables=[{"name": "Enabled", "type": "bool", "default": True}])
    assert api.resolve_gameplay_class(receipt.asset_id)["class_kind"] == "actor"
    assert not [row for row in api.validate_gameplay_class(receipt.asset_id) if row["severity"] == "error"]

    editor = DedicatedAssetEditor(tmp_path, database)
    assert editor.open_asset(receipt.asset_id)
    assert editor.pages.count() == len(editor_pages_for_asset("tc.gameplay_class"))
    assert editor.findChild(GameplayClassDefinitionEditorWidget) is not None
    assert editor.findChild(GameplayClassDebuggerWidget) is not None
    assert editor.compile(silent=True)

    api.gameplay_classes.update(receipt.asset_id, {"event_graph": {
        "entry_event": "On Begin Play",
        "nodes": [
            {"id": "set_value", "title": "Set Value", "opcode": "variable.set", "inputs": ["name:str", "value:any"], "outputs": ["value:any"], "parameters": {"name": "Enabled", "value": False}},
            {"id": "set_value_again", "title": "Set Value Again", "opcode": "variable.set", "inputs": ["name:str", "value:any"], "outputs": ["value:any"], "parameters": {"name": "Enabled", "value": True}},
        ], "connections": [],
    }})
    live_context = {"metadata": {"variables": {}}}
    started = api.begin_gameplay_class_debug_session(
        receipt.asset_id, context=live_context, breakpoints=["set_value_again"], watches=["metadata.variables.Enabled"],
    )
    assert started["status"] == "paused" and started["watches"]["metadata.variables.Enabled"] is False
    stepped = api.gameplay_class_debug_command(started["session_id"], "step")
    assert stepped["status"] == "complete" and stepped["watches"]["metadata.variables.Enabled"] is True
    assert live_context["metadata"]["variables"]["Enabled"] is True
    assert api.end_gameplay_class_debug_session(started["session_id"])["status"] == "stopped"


def test_gameplay_class_rejects_inheritance_cycles(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    service = GameplayClassService(tmp_path, database)
    first = service.create("First")
    second = service.create("Second", parent_class_id=first.asset_id)
    with pytest.raises(ValueError, match="inheritance contains a cycle"):
        service.update(first.asset_id, {"parent_class_id": second.asset_id})
