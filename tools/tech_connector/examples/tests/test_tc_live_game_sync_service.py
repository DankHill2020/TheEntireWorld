from tech_connector.services.dcc.tc_live_game_sync_service import (
    HOT_SWAP,
    RESTART_REQUIRED,
    build_playtest_iteration_plan,
    publish_tcscene_save,
    register_live_game_session,
    reset_live_sync_state,
)


def _document(**metadata):
    return {
        "scene_id": "scene-1",
        "sources": [],
        "rig_graph": {"nodes": {}},
        "cross_dcc_constraints": [],
        "timeline": {"frame": 1},
        "metadata": metadata,
    }


def setup_function():
    reset_live_sync_state()


def test_scene_save_sends_only_changed_chunks_after_initial_sync() -> None:
    packets = []
    register_live_game_session("game", lambda packet: packets.append(packet) or {"ok": True})

    first = publish_tcscene_save(_document(), "sample.tcscene")
    second = publish_tcscene_save(_document(), "sample.tcscene")
    changed = _document(runtime_simulation={"effect_system": {"spawn_rate": 40}})
    third = publish_tcscene_save(changed, "sample.tcscene")

    assert first["updated_sessions"] == 1
    assert second["changed_chunk_count"] == 0
    assert second["message"] == "Saved. The running game is already up to date."
    assert third["changed_chunk_count"] == 1
    assert len(packets) == 2
    assert packets[-1]["changed_chunks"][0]["chunk_id"] == "scene.runtime_simulation"
    assert packets[-1]["required_mode"] == HOT_SWAP


def test_native_runtime_change_requires_restart_when_session_cannot_apply_it() -> None:
    register_live_game_session("game", lambda packet: {"ok": True}, capabilities={HOT_SWAP})

    receipt = publish_tcscene_save(_document(native_runtime={"module": "game.dll"}), "sample.tcscene")

    assert receipt["required_mode"] == RESTART_REQUIRED
    assert receipt["updated_sessions"] == 0
    assert receipt["deliveries"][0]["status"] == "restart_required"


def test_native_runtime_removal_requires_restart_mode_for_later_publish() -> None:
    register_live_game_session("game", lambda packet: {"ok": True}, capabilities={HOT_SWAP})

    receipt_with_native = publish_tcscene_save(_document(native_runtime={"module": "game.dll"}), "sample.tcscene")
    removal_receipt = publish_tcscene_save(_document(), "sample.tcscene")

    assert receipt_with_native["required_mode"] == RESTART_REQUIRED
    assert receipt_with_native["removed_chunk_count"] == 0
    assert removal_receipt["required_mode"] == RESTART_REQUIRED
    assert removal_receipt["changed_chunk_count"] == 0
    assert removal_receipt["removed_chunk_count"] == 1
    assert removal_receipt["removed_chunks"] == ["runtime.native"]
    assert removal_receipt["deliveries"][0]["status"] == "restart_required"


def test_playtest_iteration_avoids_packaging_for_live_scene_changes() -> None:
    plan = build_playtest_iteration_plan(
        target="desktop", session_mode="external_playtest", changed_modes=[HOT_SWAP], session_connected=True
    )

    assert plan["package_required"] is False
    assert plan["strategy"] == "incremental_live_sync"
    assert "No package build" in plan["explanation"]


def test_remote_native_change_uses_incremental_package_not_full_rebuild() -> None:
    plan = build_playtest_iteration_plan(
        target="console", session_mode="remote_device", changed_modes=[RESTART_REQUIRED], session_connected=True
    )

    assert plan["package_required"] is True
    assert plan["strategy"] == "incremental_package"
    assert plan["rebuild_scope"] == ["changed chunks", "dependency closure"]
