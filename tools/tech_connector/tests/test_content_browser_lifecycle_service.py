from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetImportCancelled, AssetOperationsService
from tech_connector.game_engine.assets.content_browser_lifecycle_service import AssetImportQueue, ContentBrowserLifecycleService
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.integration.content_browser_qualification_service import qualify_content_browser_scale
from tech_connector.ui.game_engine.asset_browser import AssetBrowserWidget


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_deferred_asset_browser_inventory_finishes_off_ui_thread(tmp_path: Path) -> None:
    app = _application()
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    AssetOperationsService(project, database).create_asset("tc.material", "M_Async")
    browser = AssetBrowserWidget(project, database=database, defer_initial_refresh=True)
    assert browser.asset_tree.topLevelItem(0).text(0) == "Loading project assets…"
    browser.refresh_async()
    deadline = time.perf_counter() + 5.0
    while browser._asset_refresh_task is not None and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert browser._asset_refresh_task is None
    assert any(
        browser.asset_tree.topLevelItem(index).text(0).startswith("M_Async")
        for index in range(browser.asset_tree.topLevelItemCount())
    )
    browser.close()


def test_collections_structured_search_content_state_and_revision_history(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Hero")
    data = operations.create_asset("tc.data", "DA_Hero")
    material_record = database.asset(material.asset_id)
    data_record = database.asset(data.asset_id)
    assert material_record and data_record
    database.store_derived(material.asset_id, "desktop/high", b"cooked", extension=".bin")
    lifecycle = ContentBrowserLifecycleService(project, database, operations=operations)

    static = lifecycle.save_collection("Hero", asset_ids=[material.asset_id, data.asset_id])
    dynamic = lifecycle.save_collection("Needs Cook", kind="dynamic", query="cook:uncooked state:authored")
    documents = [
        lifecycle.asset_document(material_record.source_path, material_record.asset_type, material_record.asset_id, collections=("Hero",)),
        lifecycle.asset_document(data_record.source_path, data_record.asset_type, data_record.asset_id, collections=("Hero",)),
    ]

    assert static.asset_ids == (material.asset_id, data.asset_id)
    assert dynamic.query == "cook:uncooked state:authored"
    assert lifecycle.collection_asset_ids("Needs Cook", documents) == (data.asset_id,)
    assert lifecycle.matches(documents[0], "type:tc.material state:authored cook:cooked rev>=1 -status:missing")
    assert not lifecycle.matches(documents[1], "cook:cooked")
    assert documents[0]["state_label"] == "Authored Asset"
    assert documents[0]["cook_label"] == "Cooked"
    assert lifecycle.revision_history(material.asset_id)[-1]["payload"]["revision"] == 1

    restored = ContentBrowserLifecycleService(project, database, operations=operations)
    assert [row.name for row in restored.collections()] == ["Hero", "Needs Cook"]


def test_recoverable_import_queue_cancel_retry_and_python_parity(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    first = tmp_path / "first.png"; first.write_bytes(b"first")
    second = tmp_path / "second.png"; second.write_bytes(b"second")
    api = TCEditorAPI(project)

    queued = api.queue_asset_imports([first, second], folder="Assets/Textures")
    assert len(queued) == 2
    assert api.cancel_asset_import(queued[1]["queue_id"])
    processed = api.process_asset_import_queue()
    assert len(processed) == 1 and processed[0]["status"] == "complete"
    assert Path(processed[0]["source_path"]).name == "first.png"

    assert api.content_browser.import_queue.retry(queued[1]["queue_id"])
    processed = api.process_asset_import_queue()
    assert processed[0]["status"] == "complete"
    assert {row["name"] for row in api.content_browser_assets(query="type:tc.texture state:imported")} == {
        "first.png", "second.png",
    }
    api.save_content_browser_collection("Imported", query="state:imported", kind="dynamic")
    assert len(api.content_browser_assets(collection="Imported")) == 2
    assert "content_browser_operations" in api.capability_contract()

    restored = ContentBrowserLifecycleService(project, api.database, operations=api.assets)
    assert {item.status for item in restored.import_queue.items()} == {"complete"}


def test_reference_repair_and_perforce_status_are_auditable(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    assets = project / "Assets"
    assets.mkdir(parents=True)
    texture_path = assets / "T_Old.png"; texture_path.write_bytes(b"texture")
    material_path = assets / "M_Test.material.tcasset"
    material_path.write_text(json.dumps({"texture": "Assets/T_Old.png"}), encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture = database.register_asset(texture_path, "tc.texture")
    database.register_asset(material_path, "tc.material")
    operations = AssetOperationsService(project, database)
    operations.move_asset(texture.asset_id, "Assets/Textures/T_New.png")
    lifecycle = ContentBrowserLifecycleService(project, database, operations=operations)

    health = lifecycle.reference_health()
    repaired = operations.repair_project_references()
    assert health["valid_redirectors"] == 1
    assert repaired["replacements"] == 1
    assert json.loads(material_path.read_text(encoding="utf-8"))["texture"] == "Assets/Textures/T_New.png"

    current_path = database.asset(texture.asset_id).source_path
    output = (
        f"... clientFile {current_path}\n"
        "... depotFile //depot/Project/Assets/Textures/T_New.png\n"
        "... headRev 7\n... haveRev 6\n"
    )
    snapshot = lifecycle.source_control_snapshot(
        [current_path], runner=lambda *args, **kwargs: SimpleNamespace(stdout=output, returncode=0),
    )
    vcs = next(iter(snapshot.values()))
    assert vcs["status"] == "out_of_date"
    assert vcs["head_revision"] == 7


def test_content_browser_ui_exposes_lifecycle_columns_collections_and_queue(tmp_path: Path) -> None:
    _application()
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    texture = operations.create_asset("tc.material", "M_UI")
    browser = AssetBrowserWidget(project, database=database)

    assert browser.asset_tree.columnCount() == 7
    assert browser.asset_tree.headerItem().text(2) == "Content"
    assert browser.asset_tree.headerItem().text(4) == "Source Control"
    browser.lifecycle.save_collection("UI Assets", asset_ids=[texture.asset_id])
    browser.refresh()
    browser.set_collection_filter("UI Assets")
    assert sum(not browser.asset_tree.topLevelItem(index).isHidden() for index in range(browser.asset_tree.topLevelItemCount())) == 1
    browser.asset_tree.setCurrentItem(browser.asset_tree.topLevelItem(0))
    assert browser.toggle_selected_favorites()
    assert texture.asset_id in browser.lifecycle.collection("Favorites").asset_ids
    browser.show_favorites(True)
    assert browser.favorites_button.isChecked()
    assert sum(not browser.asset_tree.topLevelItem(index).isHidden() for index in range(browser.asset_tree.topLevelItemCount())) == 1
    assert browser.toggle_selected_favorites()
    assert texture.asset_id not in browser.lifecycle.collection("Favorites").asset_ids
    assert not browser.empty_state.isHidden()
    browser.set_folder_filter("Assets")
    browser.set_folder_filter("Assets/Materials")
    assert browser.navigate_folder_history(-1) and browser._folder_filter == "Assets"
    assert browser.navigate_folder_history(1) and browser._folder_filter == "Assets/Materials"
    browser.set_folder_filter("")
    browser.set_collection_filter("")
    browser._select_asset_id(texture.asset_id)
    assert browser.add_tags_to_selected("hero, environment") == 1
    assert set(database.asset(texture.asset_id).metadata["tags"]) == {"hero", "environment"}
    browser._select_asset_id(texture.asset_id)
    if browser.property_tree.topLevelItemCount():
        property_item = browser.property_tree.topLevelItem(0)
        property_item.setText(1, "not-the-default")
        assert browser.reset_property_to_default(property_item)
        assert property_item.text(1) != "not-the-default"

    source = tmp_path / "queued.wav"; source.write_bytes(b"audio")
    browser.import_asset_paths([str(source)], process_immediately=False)
    assert browser.import_queue_tree.topLevelItemCount() == 1
    assert browser.import_queue_tree.topLevelItem(0).text(2) == "Queued"


def test_content_browser_reports_import_validation_and_cook_to_task_center(tmp_path: Path) -> None:
    app = _application()
    project = tmp_path / "Project"; project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Task")
    browser = AssetBrowserWidget(project, database=database)
    events: list[dict] = []; browser.taskEvent.connect(lambda event: events.append(dict(event)))

    source = tmp_path / "queued.png"; source.write_bytes(b"texture")
    browser.import_asset_paths([str(source)], process_immediately=False)
    browser.process_import_queue()
    deadline = time.perf_counter() + 5.0
    while browser._import_queue_running and time.perf_counter() < deadline:
        app.processEvents(); time.sleep(0.005)
    app.processEvents()
    import_events = [event for event in events if str(event.get("task_id", "")).startswith("import:")]
    assert import_events[0]["operation"] == "begin"
    assert import_events[-1]["operation"] == "finish" and import_events[-1]["state"] == "complete"
    assert import_events[-1]["metadata"]["asset_id"]

    browser._select_asset_id(material.asset_id)
    browser.validate_selected(); browser.cook_selected()
    deadline = time.perf_counter() + 5.0
    while browser._tracked_asset_tasks and time.perf_counter() < deadline:
        app.processEvents(); time.sleep(0.005)
    app.processEvents()
    validation = [event for event in events if str(event.get("task_id", "")).startswith("validate:")]
    cooking = [event for event in events if str(event.get("task_id", "")).startswith("cook:")]
    assert validation[0]["operation"] == "begin" and validation[-1]["operation"] == "finish"
    assert cooking[-1]["state"] == "complete"
    assert cooking[-1]["metadata"]["output"]
    browser.close()


def test_content_browser_drop_import_classifies_folders_and_offers_place_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _application()
    project_root = tmp_path / "Project"
    project_root.mkdir()
    drop_root = tmp_path / "Drop"
    drop_root.mkdir()
    mesh_source = drop_root / "crate.fbx"
    texture_source = drop_root / "crate.png"
    unsupported_source = drop_root / "notes.txt"
    mesh_source.write_bytes(b"mesh")
    texture_source.write_bytes(b"texture")
    unsupported_source.write_text("not importable", encoding="utf-8")
    inside_project = project_root / "Assets" / "existing.png"
    inside_project.parent.mkdir(parents=True)
    inside_project.write_bytes(b"existing")

    browser = AssetBrowserWidget(project_root=project_root)
    assert browser.asset_stack.currentWidget() is browser.asset_grid
    assert browser.asset_grid.accessibleName() == "Asset thumbnail grid"
    assert browser.asset_tree.accessibleName() == "Assets detail list"
    assert len(browser._asset_shortcuts) == 6
    supported, skipped = browser.classify_import_paths([str(drop_root), str(inside_project)])

    assert {Path(path).name for path in supported} == {"crate.fbx", "crate.png"}
    assert {Path(path).name for path in skipped} == {"notes.txt", "existing.png"}

    monkeypatch.setattr(browser, "process_import_queue", lambda: None)
    browser.import_preset_combo.setCurrentText("Fast iteration")
    receipt = browser.queue_dropped_imports([str(drop_root), str(inside_project)])

    assert len(receipt["queued"]) == 2
    assert len(receipt["skipped"]) == 2
    assert receipt["folder"] == "Assets"
    assert browser.import_queue_tree.topLevelItemCount() == 2
    queued_mesh = next(item for item in browser.lifecycle.import_queue.items() if item.type_id == "tc.static_mesh")
    assert queued_mesh.importer_settings["generate_collision"] is False
    assert queued_mesh.conflict_policy == "rename"
    assert "Assets" in browser.import_drop_zone.text()

    place_source = tmp_path / "place.obj"
    place_source.write_bytes(b"mesh")
    imported = browser.operations.import_asset(place_source, folder="Assets")
    placements: list[tuple[str, str, str]] = []
    activations: list[tuple[str, str, str]] = []
    browser.assetPlacementRequested.connect(
        lambda path, type_id, asset_id: placements.append((path, type_id, asset_id))
    )
    browser.assetActivated.connect(
        lambda path, type_id, asset_id: activations.append((path, type_id, asset_id))
    )

    browser._show_import_result(imported.asset_id)
    assert not browser.import_result_panel.isHidden()
    assert browser.place_import_button.isEnabled()

    browser.open_latest_import()
    browser.place_latest_import()

    record = browser.database.asset(imported.asset_id)
    assert record is not None
    expected = (str(record.source_path), record.asset_type, record.asset_id)
    assert activations == [expected]
    assert placements == [expected]
    browser.refresh()
    assert browser.asset_grid.count() == browser.asset_tree.topLevelItemCount()
    assert not browser.asset_grid.item(0).icon().isNull()


def test_content_browser_detects_changed_external_import_source(tmp_path: Path) -> None:
    _application()
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"one")
    browser = AssetBrowserWidget(project_root=project)
    receipt = browser.operations.import_asset(source)
    record = browser.database.asset(receipt.asset_id)
    assert record is not None
    source.write_bytes(b"two-and-newer")
    future = int(record.metadata["import_source_modified_ns"]) + 2_000_000_000
    os.utime(source, ns=(future, future))

    stale = browser.check_external_source_updates()

    assert stale == (receipt.asset_id,)
    assert receipt.asset_id in browser._stale_source_asset_ids


def test_import_cancellation_is_mid_file_and_never_publishes_partial_asset(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    source = tmp_path / "large.png"
    source.write_bytes(b"a" * (3 * 1024 * 1024 + 17))
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    cancelled = threading.Event()
    progress = []

    def stop_after_first_chunk(completed: int, total: int) -> None:
        progress.append((completed, total))
        cancelled.set()

    with pytest.raises(AssetImportCancelled):
        operations.import_asset(source, cancellation_event=cancelled, progress_callback=stop_after_first_chunk)

    assert progress and progress[0][0] < progress[0][1]
    assert not (project / "Assets" / source.name).exists()
    assert not list((project / "Assets").glob("*.import"))
    assert database.list_assets() == []


def test_import_queue_can_cancel_an_item_while_its_importer_is_running(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    started = threading.Event()

    class SlowImporter:
        def import_asset(self, _source_path, *, cancellation_event=None, progress_callback=None, **_kwargs):
            started.set()
            completed = 0
            while not cancellation_event.is_set():
                completed += 1
                progress_callback(completed, 100)
                time.sleep(0.001)
            raise AssetImportCancelled("Importer stopped at a cooperative checkpoint")

    queue = AssetImportQueue(project, SlowImporter())
    item = queue.enqueue([tmp_path / "long-running.fbx"])[0]
    worker = threading.Thread(target=queue.process_next)
    worker.start()
    assert started.wait(timeout=2.0)
    assert queue.cancel(item.queue_id)
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    final = next(value for value in queue.items() if value.queue_id == item.queue_id)
    assert final.status == "cancelled"
    assert "cooperative checkpoint" in final.message


def test_perforce_history_changelists_and_confirmed_actions(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    lifecycle = ContentBrowserLifecycleService(project, database)
    commands: list[list[str]] = []

    def runner(command, **_kwargs):
        commands.append(command)
        if "filelog" in command:
            return SimpleNamespace(stdout="\n".join((
                "... depotFile //depot/Project/Assets/Hero.png",
                "... rev0 9", "... change0 1724", "... action0 edit",
                "... user0 artist", "... desc0 Tune hero texture",
            )), stderr="", returncode=0)
        if "changes" in command:
            return SimpleNamespace(stdout="\n".join((
                "... change 1801", "... user artist", "... status pending", "... desc Demo polish",
                "... change 1799", "... user lead", "... status pending", "... desc Lighting fixes",
            )), stderr="", returncode=0)
        return SimpleNamespace(stdout="opened for edit", stderr="", returncode=0)

    history = lifecycle.perforce_history(project / "Assets" / "Hero.png", runner=runner)
    changes = lifecycle.perforce_changelists(runner=runner)
    assert history == ({
        "depot_path": "//depot/Project/Assets/Hero.png", "rev": 9, "change": 1724,
        "action": "edit", "user": "artist", "desc": "Tune hero texture",
    },)
    assert [row["change"] for row in changes] == [1801, 1799]
    with pytest.raises(PermissionError):
        lifecycle.perforce_action([project / "Assets" / "Hero.png"], "edit", runner=runner)
    receipt = lifecycle.perforce_action(
        [project / "Assets" / "Hero.png"], "edit", changelist="1801", confirmed=True, runner=runner,
    )
    assert receipt["returncode"] == 0
    assert receipt["changelist"] == "1801"
    assert commands[-1][1:4] == ["edit", "-c", "1801"]


def test_large_project_qualification_emits_measured_evidence(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    lifecycle = ContentBrowserLifecycleService(project, database)

    receipt = qualify_content_browser_scale(
        lifecycle, sample_count=50_000, query_budget_ms=5_000.0, inventory_budget_ms=5_000.0,
    )

    assert receipt.qualified
    assert receipt.sample_count == 50_000
    assert receipt.minimum_documents_per_second > 0
    assert receipt.capabilities["cooperative_mid_file_cancellation"]
    assert receipt.capabilities["perforce_history_and_changelists"]
