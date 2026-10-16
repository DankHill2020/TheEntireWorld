from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QWidget

from tech_connector.game_engine.assets import (
    AssetDatabase, AssetDependencyEdge, AssetDependencyGraphService, AssetOperationsService,
    PrefabService, asset_metadata_path,
)
from tech_connector.ui.game_engine.asset_insights import ASSET_ID_ROLE, ISSUE_KIND_ROLE, AssetAuditDashboard, AssetDependencyExplorer
from tech_connector.ui.game_engine.asset_picker import AssetPickerDialog
from tech_connector.ui.game_engine.engine_workspace import ActorDetailsPanel, _AssetReferencePropertyTree
from tech_connector.ui.game_engine.editor_state import EngineEditorState
from tech_connector.ui.game_engine.production_tools import BuildDeployPanel
from tech_connector.ui.game_engine.recovery_center import EngineRecoveryCenter
from tech_connector.ui.game_engine.task_center import EngineTaskCenter


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_task_center_persists_history_and_recovers_interrupted_work(tmp_path: Path) -> None:
    _application()
    center = EngineTaskCenter(tmp_path)
    center.begin("asset_scan", "Scan assets", category="assets")
    center.update("asset_scan", progress=45, message="Reading metadata")
    restored = EngineTaskCenter(tmp_path)
    assert restored.tasks["asset_scan"]["state"] == "interrupted"
    assert restored.tasks["asset_scan"]["can_retry"]
    restored.finish("asset_scan", message="Scan complete")
    final = EngineTaskCenter(tmp_path)
    assert final.tasks["asset_scan"]["state"] == "complete"
    assert final.tasks["asset_scan"]["progress"] == 100


def test_task_center_pauses_resumes_and_navigates_to_task_evidence(tmp_path: Path) -> None:
    _application()
    center = EngineTaskCenter(tmp_path)
    center.begin(
        "build:package", "Package player", category="build", can_cancel=True,
        can_pause=True, can_retry=True,
        metadata={"scene_asset_id": "level-1", "output": str(tmp_path / "Build")},
    )
    center.tree.setCurrentItem(center.tree.topLevelItem(0))
    paused = []; resumed = []; opened = []; revealed = []
    center.pauseRequested.connect(paused.append); center.resumeRequested.connect(resumed.append)
    center.openAssetRequested.connect(opened.append); center.revealRequested.connect(revealed.append)
    assert center.pause_button.isEnabled() and center.pause_button.text() == "Pause"
    center.pause_or_resume_selected(); center.open_selected_asset(); center.reveal_selected_location()
    assert paused == ["build:package"]
    assert opened == ["level-1"] and revealed == [str(tmp_path / "Build")]
    center.finish("build:package", state="paused", message="Paused safely")
    assert center.pause_button.isEnabled() and center.pause_button.text() == "Resume"
    center.clear_finished()
    assert "build:package" in center.tasks
    center.pause_or_resume_selected()
    assert resumed == ["build:package"]


def test_asset_picker_filters_compatible_assets_and_returns_stable_id(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(tmp_path, database)
    texture = tmp_path / "Assets" / "Sky.hdr"; texture.parent.mkdir(parents=True); texture.write_bytes(b"hdr")
    texture_record = database.register_asset(texture, "tc.texture", metadata={"tags": ["sky", "environment"]})
    operations.create_asset("tc.game_ruleset", "Rules")
    picker = AssetPickerDialog(tmp_path, database, allowed_types=("tc.texture",))
    assert picker.assets.count() == 1
    assert not picker.assets.item(0).icon().isNull()
    picker.search.setText("environment")
    assert picker.assets.count() == 1
    assert picker.select_asset(texture_record.asset_id)
    located = []; inspected = []; picker.locateRequested.connect(located.append); picker.inspectRequested.connect(inspected.append)
    assert picker.locate_selected() and picker.inspect_selected()
    assert located == [texture_record.asset_id] and inspected == [texture_record.asset_id]
    assert picker.toggle_selected_favorite()
    picker.scope.setCurrentIndex(picker.scope.findData("favorites"))
    assert picker.assets.count() == 1
    assert picker.accept_selected()
    assert picker.selected_asset_id == texture_record.asset_id
    recent_picker = AssetPickerDialog(tmp_path, database, recent_asset_ids=(texture_record.asset_id,))
    recent_picker.scope.setCurrentIndex(recent_picker.scope.findData("recent"))
    assert recent_picker.assets.count() == 1
    context_picker = AssetPickerDialog(tmp_path, database, allowed_types=("tc.texture",), context_asset_id=texture_record.asset_id)
    assert context_picker.context_button.isEnabled()
    assert context_picker.use_context_asset()
    assert context_picker.selected_asset_id == texture_record.asset_id


def test_component_asset_reference_drop_enforces_compatible_types() -> None:
    _application()
    tree = _AssetReferencePropertyTree()
    item = QTreeWidgetItem(["Mesh", ""]); item.setData(0, Qt.UserRole, "mesh_asset_id"); tree.addTopLevelItem(item)
    assert tree.apply_asset_payload(item, {"asset_id": "mesh-1", "type_id": "tc.static_mesh"})
    assert item.text(1) == "mesh-1"
    assert not tree.apply_asset_payload(item, {"asset_id": "audio-1", "type_id": "tc.audio_clip"})
    assert item.text(1) == "mesh-1"


def test_project_editor_state_keeps_bounded_recent_assets_and_levels(tmp_path: Path) -> None:
    state = EngineEditorState(tmp_path, limit=3)
    state.touch_asset("one"); state.touch_asset("two"); state.touch_asset("one")
    level = tmp_path / "Main.tcscene"; level.write_bytes(b"scene"); state.touch_level(level)
    restored = EngineEditorState(tmp_path, limit=3)
    assert restored.recent_assets == ("one", "two")
    assert restored.recent_levels == (str(level.resolve()),)


def test_recovery_center_discovers_level_and_asset_recovery_copies(tmp_path: Path) -> None:
    _application()
    level_recovery = tmp_path / "Assets" / ".Main.autosave.tcscene"
    level_recovery.parent.mkdir(parents=True); level_recovery.write_bytes(b"scene")
    asset_recovery = tmp_path / ".tech_connector" / "recovery" / "assets" / "asset.json"
    asset_recovery.parent.mkdir(parents=True); asset_recovery.write_text(json.dumps({"asset_id": "asset-1"}), encoding="utf-8")
    center = EngineRecoveryCenter(tmp_path)
    assert center.tree.topLevelItemCount() >= 2
    kinds = {center.tree.topLevelItem(index).text(1) for index in range(center.tree.topLevelItemCount())}
    assert {"Level", "Asset"}.issubset(kinds)
    locations = {center.tree.topLevelItem(index).text(4) for index in range(center.tree.topLevelItemCount())}
    assert str(level_recovery) in locations and str(asset_recovery) in locations


def test_recovery_center_compares_assets_and_blocks_stale_conflicts(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    source = tmp_path / "Assets" / "Config.tcdata"; source.parent.mkdir(parents=True); source.write_text(json.dumps({"properties": {"speed": 1}}), encoding="utf-8")
    record = database.register_asset(source, "tc.data")
    recovery = tmp_path / ".tech_connector" / "recovery" / "assets" / f"{record.asset_id.replace(':', '_')}.json"
    recovery.parent.mkdir(parents=True); recovery.write_text(json.dumps({"asset_id": record.asset_id, "source_hash": record.content_hash, "values": {"speed": 2}}), encoding="utf-8")
    center = EngineRecoveryCenter(tmp_path, database=database)
    center.tree.setCurrentItem(center.tree.topLevelItem(0))
    comparison = center.compare_selected()
    assert comparison["compatible"]
    assert comparison["changed_sections"] == ["speed"]
    assert center.restore_button.isEnabled()

    recovery.write_text(json.dumps({"asset_id": record.asset_id, "source_hash": "older-source", "values": {"speed": 3}}), encoding="utf-8")
    center.refresh(); center.tree.setCurrentItem(center.tree.topLevelItem(0))
    comparison = center.compare_selected()
    assert not comparison["compatible"]
    assert not center.restore_button.isEnabled()
    assert "CONFLICT" in center.comparison.toPlainText()


def test_build_panel_restores_failed_checkpoint_as_resumable(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    scene = tmp_path / "Assets" / "Main.tcscene"; scene.parent.mkdir(parents=True); scene.write_bytes(b"scene")
    panel = BuildDeployPanel(tmp_path, database)
    panel._write_checkpoint("package", scene, tmp_path / "Build", "failed")
    restored = BuildDeployPanel(tmp_path, database)
    assert restored.resume_button.isEnabled()
    assert restored._checkpoint_can_resume()


def test_build_panel_records_safe_pause_as_resumable_checkpoint(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    scene = tmp_path / "Assets" / "Main.tcscene"; scene.parent.mkdir(parents=True); scene.write_bytes(b"scene")
    panel = BuildDeployPanel(tmp_path, database)

    class _Worker:
        interrupted = False
        def isRunning(self): return True
        def requestInterruption(self): self.interrupted = True

    worker = _Worker(); panel._worker = worker; panel._active_task_id = "build:package"
    panel._write_checkpoint("package", scene, tmp_path / "Build", "running")
    events = []; panel.taskEvent.connect(events.append)
    assert panel.pause()
    assert worker.interrupted and panel._pause_requested
    panel._completed({})
    assert panel._read_checkpoint()["state"] == "paused"
    assert events[-1]["state"] == "paused"
    assert panel._checkpoint_can_resume()


class _MultiEditViewport(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.proxies = [{"entity_id": "one"}, {"entity_id": "two"}]
        self.entities = {
            "one": {"name": "One", "transform": {}, "components": []},
            "two": {"name": "Two", "transform": {}, "components": []},
        }
        self._selected_scene_proxy = self.proxies[0]
        self.bulk_values = None

    def selected_level_actor_proxies(self): return self.proxies
    def _runtime_entity_for_proxy(self, proxy): return self.entities[proxy["entity_id"]]
    def update_selected_level_actors(self, values, *, fields=()): self.bulk_values = (dict(values), tuple(fields)); return 2


def test_actor_details_multi_edit_preserves_individual_transforms() -> None:
    _application()
    viewport = _MultiEditViewport()
    panel = ActorDetailsPanel(viewport)
    assert not panel.position[1][0].isEnabled()
    assert panel.mobility.isEnabled()
    assert "2 Actors" in panel.apply_button.text()
    panel.mobility.setCurrentText("Static")
    assert panel.apply()
    assert viewport.bulk_values[1] == ("mobility", "visible", "tags")
    assert "position" not in viewport.bulk_values[1]


def test_actor_details_search_favorites_and_mixed_values_are_safe() -> None:
    _application()
    viewport = _MultiEditViewport()
    viewport.entities["one"].update({"mobility": "static", "visible": True, "tags": ["hero"]})
    viewport.entities["two"].update({"mobility": "movable", "visible": False, "tags": ["enemy"]})
    panel = ActorDetailsPanel(viewport)
    assert panel._mixed_fields == {"mobility", "visible", "tags"}
    assert panel.mobility.currentText() == "— Multiple Values —"
    assert panel.visible.checkState() == Qt.PartiallyChecked
    assert not panel.apply()
    assert viewport.bulk_values is None

    panel.mobility.setCurrentText("Static")
    assert panel.apply()
    assert viewport.bulk_values[1] == ("mobility",)
    assert panel.mobility.isHidden()
    panel.property_search.setText("mobility")
    assert not panel.mobility.isHidden()
    panel.property_search.clear()
    name_favorite = panel._inspector_rows["name"][3]; name_favorite.setChecked(True)
    panel.favorites_only.setChecked(True)
    assert panel._filter_actor_fields() == 1
    assert not panel.name.isHidden() and panel.visible.isHidden()


class _ComponentViewport(QWidget):
    def __init__(self) -> None:
        super().__init__(); self._selected_scene_proxy = {"entity_id": "one"}; self.updated = None
        self.entity = {"name": "Actor", "transform": {}, "components": [{"component_id": "light-1", "type": "light", "enabled": True, "intensity": 4.0}]}
    def selected_level_actor_proxies(self): return [self._selected_scene_proxy]
    def _runtime_entity_for_proxy(self, _proxy): return self.entity
    def update_component_on_selected_level_actor(self, component_id, values): self.updated = (component_id, dict(values)); self.entity["components"][0].update(values); return True


def test_actor_details_copies_and_pastes_complete_compatible_component() -> None:
    _application()
    viewport = _ComponentViewport(); panel = ActorDetailsPanel(viewport)
    panel.components.setCurrentItem(panel.components.topLevelItem(0))
    assert panel.copy_selected_component()
    viewport.entity["components"][0]["intensity"] = 99.0
    assert panel.paste_selected_component()
    assert viewport.updated == ("light-1", {"enabled": True, "intensity": 4.0})
    assert viewport.entity["components"][0]["intensity"] == 4.0


def test_actor_details_compares_prefab_instance_with_inherited_values(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3"); prefabs = PrefabService(tmp_path, database)
    receipt = prefabs.create_from_entities("Door", [{"name": "Door", "open": False}])
    viewport = _ComponentViewport(); viewport.entity["prefab_instance"] = {"source_asset_id": receipt.asset_id, "overrides": {"Door_0.open": True}}
    panel = ActorDetailsPanel(viewport); panel.prefab_service = prefabs; panel.refresh()
    row = panel.prefab_overrides.topLevelItem(0)
    assert [row.text(index) for index in range(4)] == ["Door_0.open", "false", "true", "Modified"]
    assert panel.compare_prefab.isEnabled() and panel.unpack_prefab.isEnabled()


def test_dependency_explorer_shows_typed_dependencies_and_referencers(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    assets = tmp_path / "Assets"; assets.mkdir()
    texture_path = assets / "Surface.png"; texture_path.write_bytes(b"texture")
    material_path = assets / "Surface.tcmaterial"; material_path.write_bytes(b"material")
    level_path = assets / "Main.tcscene"; level_path.write_bytes(b"level")
    texture = database.register_asset(texture_path, "tc.texture")
    material = database.register_asset(material_path, "tc.material")
    level = database.register_asset(level_path, "tc.level")
    database.set_dependencies(material.asset_id, ((texture.asset_id, "albedo"),))
    database.set_dependencies(level.asset_id, ((material.asset_id, "scene_material"),))

    explorer = AssetDependencyExplorer(tmp_path, database)
    assert explorer.set_asset(material.asset_id)
    assert explorer.tree.topLevelItem(0).child(0).text(0) == "Depends on · albedo"
    assert explorer.tree.topLevelItem(0).child(0).data(0, ASSET_ID_ROLE) == texture.asset_id
    assert explorer.tree.topLevelItem(1).child(0).text(0) == "Used by · scene_material"
    assert "2 dependency/referencer asset(s)" in explorer.summary.text()

    opened = []
    explorer.openRequested.connect(opened.append)
    explorer.tree.setCurrentItem(explorer.tree.topLevelItem(0).child(0))
    assert explorer.open_selected()
    assert opened == [texture.asset_id]


def test_dependency_graph_reports_unique_source_derived_package_cost_and_cycles(tmp_path: Path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    assets = tmp_path / "Assets"; assets.mkdir()
    root_path = assets / "World.tcscene"; root_path.write_bytes(b"world")
    material_path = assets / "Surface.tcmaterial"; material_path.write_bytes(b"material")
    root = database.register_asset(root_path, "tc.level")
    material = database.register_asset(material_path, "tc.material")
    database.set_dependencies(root.asset_id, ((material.asset_id, "scene_material"),))
    database.store_derived(material.asset_id, "desktop", b"compiled-material", extension=".bin")
    graph = AssetDependencyGraphService(tmp_path, database).analyze(root.asset_id, include_referencers=False)
    assert graph.source_bytes == len(b"world") + len(b"material")
    assert graph.derived_bytes == len(b"compiled-material")
    assert graph.package_bytes == graph.source_bytes + graph.derived_bytes
    node = next(value for value in graph.nodes if value.asset_id == material.asset_id)
    assert node.package_bytes == len(b"material") + len(b"compiled-material")
    cycles = AssetDependencyGraphService._cycles(
        ("a", "b"), (AssetDependencyEdge("a", "b", "uses"), AssetDependencyEdge("b", "a", "uses")),
    )
    assert cycles == (("a", "b"),)


def test_reference_replacement_previews_updates_and_undoes_authored_values(tmp_path: Path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    assets = tmp_path / "Assets"; assets.mkdir()
    old_path = assets / "Old.png"; old_path.write_bytes(b"old")
    new_path = assets / "New.png"; new_path.write_bytes(b"new")
    old = database.register_asset(old_path, "tc.texture")
    new = database.register_asset(new_path, "tc.texture")
    owner_path = assets / "Surface.tcmaterial"
    owner_path.write_text(json.dumps({"texture_asset_id": old.asset_id, "texture_path": "Assets/Old.png"}), encoding="utf-8")
    owner = database.register_asset(owner_path, "tc.material", dependencies=((old.asset_id, "albedo"),))
    operations = AssetOperationsService(tmp_path, database)
    plan = operations.plan_reference_replacement(old.asset_id, new.asset_id)
    assert plan.can_execute and plan.referencers == (owner.asset_id,)
    assert plan.authored_replacements == 2
    receipt = operations.replace_asset_references(old.asset_id, new.asset_id)
    assert receipt.updated_assets == (owner.asset_id,) and receipt.authored_replacements == 2
    assert database.dependencies(owner.asset_id) == (new.asset_id,)
    assert new.asset_id in owner_path.read_text(encoding="utf-8")
    operations.undo_last()
    assert database.dependencies(owner.asset_id) == (old.asset_id,)
    assert old.asset_id in owner_path.read_text(encoding="utf-8")


def test_asset_audit_dashboard_filters_actionable_findings(tmp_path: Path) -> None:
    _application()
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    texture_path = tmp_path / "Assets" / "Unused.png"; texture_path.parent.mkdir(parents=True); texture_path.write_bytes(b"texture")
    texture = database.register_asset(texture_path, "tc.texture")
    asset_metadata_path(texture_path).unlink()
    dashboard = AssetAuditDashboard(tmp_path, database)
    dashboard._rows = dashboard._collect()
    dashboard.apply_filter()
    assert any(row["asset_id"] == texture.asset_id and row["kind"] == "unused" for row in dashboard._rows)
    missing_item = next(dashboard.tree.topLevelItem(index) for index in range(dashboard.tree.topLevelItemCount()) if dashboard.tree.topLevelItem(index).data(0, ISSUE_KIND_ROLE) == "missing_metadata")
    dashboard.tree.setCurrentItem(missing_item)
    assert dashboard.repair_button.isEnabled()
    assert dashboard.repair_selected_metadata()
    assert asset_metadata_path(texture_path).is_file()
    dashboard.search.setText("unused")
    assert dashboard.tree.topLevelItemCount() >= 1
    assert all(item.text(2).casefold().find("references") >= 0 for item in (dashboard.tree.topLevelItem(index) for index in range(dashboard.tree.topLevelItemCount())))
    dashboard.tree.setCurrentItem(dashboard.tree.topLevelItem(0))
    assert dashboard.trash_button.isEnabled()
    assert dashboard.move_selected_unused_to_trash(confirm=False)
    assert database.asset(texture.asset_id) is None
    assert not texture_path.exists()
