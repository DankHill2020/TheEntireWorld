from __future__ import annotations

import threading

import pytest

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase, AssetWatchService


def test_asset_database_invalidates_dependency_closed_derived_data(tmp_path) -> None:
    texture_path = tmp_path / "base_color.bin"
    material_path = tmp_path / "hero.material"
    scene_path = tmp_path / "shot.tcscene"
    texture_path.write_bytes(b"texture-v1")
    material_path.write_text("material-v1", encoding="utf-8")
    scene_path.write_text("scene-v1", encoding="utf-8")

    database = AssetDatabase(tmp_path / "assets.sqlite3", tmp_path / "ddc")
    texture = database.register_asset(texture_path, "texture")
    material = database.register_asset(material_path, "material", dependencies=[texture.asset_id])
    scene = database.register_asset(scene_path, "scene", dependencies=[material.asset_id])

    material_cache = database.store_derived(material.asset_id, "compiled", b"material-cache")
    scene_cache = database.store_derived(scene.asset_id, "runtime", b"scene-cache")
    assert material_cache.path.is_file()
    assert scene_cache.path.is_file()
    assert database.dependency_closure([scene.asset_id]) == tuple(
        sorted((scene.asset_id, material.asset_id, texture.asset_id))
    )

    texture_path.write_bytes(b"texture-v2")
    changes = database.scan_changes()

    assert len(changes) == 1
    assert changes[0].asset_id == texture.asset_id
    assert changes[0].affected_assets == tuple(sorted((texture.asset_id, material.asset_id, scene.asset_id)))
    assert database.derived(material.asset_id, "compiled") is None
    assert database.derived(scene.asset_id, "runtime") is None
    assert database.asset(texture.asset_id).revision == 2


def test_asset_database_rejects_dependency_cycles(tmp_path) -> None:
    first_path = tmp_path / "first.asset"
    second_path = tmp_path / "second.asset"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    database = AssetDatabase(tmp_path / "assets.sqlite3")
    first = database.register_asset(first_path, "data")
    second = database.register_asset(second_path, "data", dependencies=[first.asset_id])

    with pytest.raises(ValueError, match="cycle"):
        database.set_dependencies(first.asset_id, [second.asset_id])

    assert database.dependencies(first.asset_id) == ()
    assert database.dependencies(second.asset_id) == (first.asset_id,)


def test_asset_watch_service_emits_changes_off_thread(tmp_path) -> None:
    source_path = tmp_path / "watched.asset"
    source_path.write_text("before", encoding="utf-8")
    database = AssetDatabase(tmp_path / "assets.sqlite3")
    asset = database.register_asset(source_path, "data")
    received = []
    ready = threading.Event()

    def capture(changes) -> None:
        received.extend(changes)
        ready.set()

    watcher = AssetWatchService(database, capture, interval_seconds=0.05)
    watcher.start()
    try:
        source_path.write_text("after-with-different-size", encoding="utf-8")
        assert ready.wait(2.0)
    finally:
        watcher.stop()

    assert not watcher.running
    assert received[0].asset_id == asset.asset_id
    assert received[0].kind == "changed"
