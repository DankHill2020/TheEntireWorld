from __future__ import annotations

import json
import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    AssetDatabase,
    AssetInUseError,
    AssetOperationsService,
    AssetProductionService,
    PrefabService,
    asset_metadata_path,
    builtin_asset_type_registry,
    read_asset_metadata,
)
from tech_connector.ui.game_engine.asset_browser import AssetBrowserWidget
from tech_connector.ui.game_engine.asset_editor_routing import AssetEditorRouter


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_builtin_registry_routes_familiar_phase_one_types() -> None:
    registry = builtin_asset_type_registry()

    assert registry.require("tc.level").editor_id == "garden"
    assert registry.require("TC.MATERIAL_INSTANCE").hot_reload_class == "hot_swap"
    assert registry.infer("Hero.fbx").type_id == "tc.static_mesh"
    assert registry.infer("weights.tcskin.json").type_id == "tc.skin_binding"
    assert {"World", "Geometry", "Rendering", "Animation", "FX", "Gameplay"}.issubset(registry.families())
    assert len(registry.all()) >= 24


def test_database_persists_uuid_identity_in_sidecar(tmp_path) -> None:
    source = tmp_path / "crate.png"
    source.write_bytes(b"png-source")
    database = AssetDatabase(tmp_path / "assets.sqlite3")

    first = database.register_asset(source, "tc.texture")
    second = database.register_asset(source, "tc.texture")
    metadata = read_asset_metadata(source)

    assert first.asset_id == second.asset_id == metadata["asset_id"]
    assert first.asset_id.startswith("tc.asset.")
    assert len(first.asset_id.removeprefix("tc.asset.")) == 32
    assert asset_metadata_path(source).is_file()


def test_database_rejects_copied_duplicate_uuid_sidecars(tmp_path) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_path.write_bytes(b"first")
    database = AssetDatabase(tmp_path / "assets.sqlite3")
    database.register_asset(first_path, "tc.texture")
    second_path.write_bytes(b"second")
    shutil.copy2(asset_metadata_path(first_path), asset_metadata_path(second_path))

    with pytest.raises(ValueError, match="Duplicate asset UUID"):
        database.register_asset(second_path, "tc.texture")


def test_move_and_rename_preserve_uuid_and_dependencies(tmp_path) -> None:
    project = tmp_path / "Project"
    source_dir = project / "Assets"
    source_dir.mkdir(parents=True)
    texture_path = source_dir / "crate.png"
    material_path = source_dir / "crate.material.tcasset"
    texture_path.write_bytes(b"texture")
    material_path.write_text("{}", encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture = database.register_asset(texture_path, "tc.texture")
    material = database.register_asset(material_path, "tc.material", dependencies=[texture.asset_id])
    operations = AssetOperationsService(project, database)

    moved = operations.move_asset(texture.asset_id, "Assets/Props/crate.png")
    renamed = operations.rename_asset(texture.asset_id, "T_Crate_BaseColor")

    assert moved.asset_id == renamed.asset_id == texture.asset_id
    assert database.dependencies(material.asset_id) == (texture.asset_id,)
    assert database.asset(texture.asset_id).source_path.name.casefold() == "t_crate_basecolor.png"
    metadata = read_asset_metadata(database.asset(texture.asset_id).source_path)
    assert metadata["asset_id"] == texture.asset_id
    previous = {value.casefold() for value in metadata["previous_paths"]}
    assert "assets/crate.png" in previous
    assert "assets/props/crate.png" in previous


def test_create_and_import_return_discoverable_receipts(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    external = tmp_path / "impact.wav"
    external.write_bytes(b"RIFF-test")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)

    created = operations.create_asset("tc.material_instance", "MI Hero", folder="Assets/Materials")
    imported = operations.import_asset(external, folder="Assets/Audio")

    assert created.type_id == "tc.material_instance"
    assert imported.type_id == "tc.audio_clip"
    assert database.asset(created.asset_id).source_path.is_file()
    assert database.asset(imported.asset_id).source_path.is_file()
    payload = json.loads(database.asset(created.asset_id).source_path.read_text(encoding="utf-8"))
    assert payload["type_id"] == "tc.material_instance"
    assert read_asset_metadata(database.asset(imported.asset_id).source_path)["importer_settings"]["compression"] == "auto"


def test_reimport_refreshes_content_without_changing_identity(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    external = tmp_path / "source.wav"
    external.write_bytes(b"version-one")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    imported = operations.import_asset(external)
    external.write_bytes(b"version-two-with-new-size")

    receipt = operations.reimport_asset(imported.asset_id)
    record = database.asset(imported.asset_id)

    assert receipt.asset_id == imported.asset_id
    assert record.source_path.read_bytes() == b"version-two-with-new-size"
    assert record.revision == 2


def test_reference_report_and_legacy_path_fixup(tmp_path) -> None:
    project = tmp_path / "Project"
    assets = project / "Assets"
    assets.mkdir(parents=True)
    texture_path = assets / "T_Old.png"
    material_path = assets / "M_Uses_Texture.material.tcasset"
    texture_path.write_bytes(b"texture")
    material_path.write_text(json.dumps({"texture": "Assets/T_Old.png"}), encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture = database.register_asset(texture_path, "tc.texture")
    material = database.register_asset(material_path, "tc.material")
    operations = AssetOperationsService(project, database)
    operations.move_asset(texture.asset_id, "Assets/Textures/T_New.png")

    fixup = operations.fix_legacy_path_references(texture.asset_id)
    report = operations.reference_report(texture.asset_id)

    assert fixup.replacements == 1
    assert fixup.updated_assets == (material.asset_id,)
    assert json.loads(material_path.read_text(encoding="utf-8"))["texture"].casefold() == "assets/textures/t_new.png"
    assert [item["asset_id"] for item in report["referencers"]] == [material.asset_id]


def test_move_writes_resolvable_redirect_and_duplicate_gets_new_identity(tmp_path) -> None:
    project = tmp_path / "Project"
    assets = project / "Assets"
    assets.mkdir(parents=True)
    source = assets / "M_Master.material.tcasset"
    source.write_text("{}", encoding="utf-8")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    original = database.register_asset(source, "tc.material")
    operations = AssetOperationsService(project, database)

    operations.move_asset(original.asset_id, "Assets/Materials/M_Master.material.tcasset")
    duplicate = operations.duplicate_asset(original.asset_id)

    assert operations.resolve_redirect("Assets/M_Master.material.tcasset").asset_id == original.asset_id
    assert duplicate.asset_id != original.asset_id
    assert database.asset(duplicate.asset_id).source_path.name.casefold() == "m_master_copy.material.tcasset"


def test_safe_delete_requires_replacement_and_undo_restores_references(tmp_path) -> None:
    project = tmp_path / "Project"
    assets = project / "Assets"
    assets.mkdir(parents=True)
    old_path = assets / "T_Old.png"
    replacement_path = assets / "T_New.png"
    material_path = assets / "M_Test.material.tcasset"
    old_path.write_bytes(b"old")
    replacement_path.write_bytes(b"new")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    old = database.register_asset(old_path, "tc.texture")
    replacement = database.register_asset(replacement_path, "tc.texture")
    material_path.write_text(json.dumps({"texture_asset_id": old.asset_id}), encoding="utf-8")
    material = database.register_asset(material_path, "tc.material", dependencies=[old.asset_id])
    operations = AssetOperationsService(project, database)

    with pytest.raises(AssetInUseError):
        operations.delete_asset(old.asset_id)

    receipt = operations.delete_asset(old.asset_id, replacement_asset_id=replacement.asset_id)
    assert database.asset(old.asset_id) is None
    assert database.dependencies(material.asset_id) == (replacement.asset_id,)
    assert json.loads(material_path.read_text(encoding="utf-8"))["texture_asset_id"] == replacement.asset_id
    assert not old_path.exists() and receipt.recoverable

    operations.undo_last()
    assert database.asset(old.asset_id).source_path == old_path.resolve()
    assert database.dependencies(material.asset_id) == (old.asset_id,)
    assert json.loads(material_path.read_text(encoding="utf-8"))["texture_asset_id"] == old.asset_id


def test_validation_and_create_undo_are_user_recoverable(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)

    created = operations.create_asset("tc.data", "Settings")
    report = operations.validate_asset(created.asset_id)
    assert report.valid
    assert operations.can_undo and "Create" in operations.undo_label

    operations.undo_last()
    assert database.asset(created.asset_id) is None


def test_typed_asset_defaults_and_dependency_closed_cook_manifest(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    material = operations.create_asset("tc.material", "M_Default")
    prefab = operations.create_asset("tc.prefab", "BP_Crate")
    prefab_record = database.asset(prefab.asset_id)
    database.set_dependencies(prefab.asset_id, [(material.asset_id, "material")])

    material_payload = json.loads(database.asset(material.asset_id).source_path.read_text(encoding="utf-8"))
    assert material_payload["properties"]["shading_model"] == "pbr"
    assert material_payload["properties"]["roughness"] == 0.5

    production = AssetProductionService(project, database)
    receipt = production.cook_manifest([prefab.asset_id], platform="windows", quality="high")
    audit = production.audit()

    assert receipt.asset_ids == tuple(sorted((material.asset_id, prefab.asset_id)))
    assert receipt.artifact.path.is_file()
    assert receipt.platform == "windows"
    assert audit.ready and audit.asset_count == 2
    assert prefab_record.source_path.is_file()


def test_prefab_instances_support_nested_assets_and_apply_revert_overrides(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)
    nested = operations.create_asset("tc.prefab", "Wheel")
    prefabs = PrefabService(project, database)
    crate = prefabs.create_from_entities(
        "Vehicle",
        [{"name": "Body", "transform": {"scale": [1, 1, 1]}}, {"name": "Wheel", "prefab_asset_id": nested.asset_id}],
        dependencies=[nested.asset_id],
    )

    instance = prefabs.instantiate(crate.asset_id, overrides={"0.transform.scale": [2, 2, 2]})
    assert instance.override_state == "overridden"
    assert instance.entities[0]["transform"]["scale"] == [2, 2, 2]
    assert instance.nested_asset_ids == (nested.asset_id,)

    reverted = prefabs.revert_overrides(instance)
    assert reverted.override_state == "inherited"
    assert reverted.entities[0]["transform"]["scale"] == [1, 1, 1]

    applied = prefabs.apply_overrides(instance)
    assert applied.override_state == "inherited"
    assert applied.entities[0]["transform"]["scale"] == [2, 2, 2]


def test_editor_router_reports_ready_and_missing_routes() -> None:
    registry = builtin_asset_type_registry()
    router = AssetEditorRouter()
    opened = []
    router.register("garden", "Garden", lambda path, descriptor, asset_id: opened.append((path, asset_id)) or True)

    level = router.open("World.tcscene", registry.require("tc.level"), "level-id")
    audio = router.open("Impact.wav", registry.require("tc.audio_clip"), "audio-id")

    assert level.opened and level.workspace == "Garden"
    assert opened == [("World.tcscene", "level-id")]
    assert not audio.opened and audio.editor_id == "audio"


def test_operations_reject_destinations_outside_project(tmp_path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(project, database)

    with pytest.raises(ValueError, match="inside the project"):
        operations.create_asset("tc.data", "Escaped", folder=tmp_path / "Elsewhere")


def test_asset_browser_discovers_filters_and_inspects_registered_assets(tmp_path) -> None:
    _application()
    project = tmp_path / "Project"
    asset_folder = project / "Assets"
    asset_folder.mkdir(parents=True)
    texture_path = asset_folder / "T_Hero.png"
    audio_path = asset_folder / "S_Impact.wav"
    texture_path.write_bytes(b"texture")
    audio_path.write_bytes(b"audio")
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    texture = database.register_asset(texture_path, "tc.texture")

    browser = AssetBrowserWidget(project, database=database)
    assert browser.asset_tree.topLevelItemCount() == 2

    browser.search_edit.setText("hero rendering")
    visible = [
        browser.asset_tree.topLevelItem(index)
        for index in range(browser.asset_tree.topLevelItemCount())
        if not browser.asset_tree.topLevelItem(index).isHidden()
    ]
    assert [item.text(0) for item in visible] == ["T_Hero.png"]

    browser.asset_tree.setCurrentItem(visible[0])
    assert "Texture" in browser.inspector_type.text()
    assert texture.asset_id in browser.inspector_details.text()


def test_asset_browser_folder_navigation_context_actions_and_current_folder_creation(tmp_path) -> None:
    _application()
    project = tmp_path / "Project"
    (project / "Assets").mkdir(parents=True)
    database = AssetDatabase(project / ".tech_connector" / "assets.sqlite3")
    browser = AssetBrowserWidget(project, database=database)

    folder = browser.create_folder_named("Gameplay", parent_folder="Assets")
    assert folder == "Assets/Gameplay"
    assert (project / folder).is_dir()
    assert browser.current_content_folder() == folder

    browser.create_asset("tc.data_schema", name="EnemySchema")
    record = next(row for row in database.list_assets() if row.asset_type == "tc.data_schema")
    assert record.source_path.parent == (project / folder).resolve()

    source = tmp_path / "icon.png"
    source.write_bytes(b"png")
    messages = browser.import_asset_paths([str(source)])
    assert len(messages) == 1
    imported = next(row for row in database.list_assets() if row.asset_type == "tc.texture")
    assert imported.source_path.parent == (project / folder).resolve()

    browser._select_asset_id(record.asset_id)
    menu = browser._asset_context_menu()
    labels = []
    pending = [menu]
    while pending:
        current = pending.pop()
        for action in current.actions():
            labels.append(action.text())
        pending.extend(getattr(current, "_tc_child_menus", []))
    assert {"Open", "Create Asset", "Import Assets…", "Rename", "Duplicate", "Move To…", "Validate", "Cook Selection", "Find References", "Delete…"} <= set(labels)

    browser.go_to_parent_folder()
    assert browser.current_content_folder() == "Assets"
