from __future__ import annotations

from pathlib import Path

from tech_connector.game_engine.integration import dcc_scene_restoration_service as restoration
from tech_connector.game_engine.scene.federated_scene_service import (
    FederatedSceneDocument,
    dcc_session_state_from_snapshot,
    load_federated_scene,
    reconcile_scene_sources,
    save_federated_scene,
    source_file_fingerprint,
)


def test_launch_commands_cover_all_ten_external_host_profiles(tmp_path) -> None:
    source = tmp_path / "source.asset"
    source.write_text("scene", encoding="utf-8")
    executable = str(tmp_path / "host.exe")
    direct_hosts = {
        "blender", "3dsmax", "motionbuilder", "houdini", "substance_painter",
        "unreal", "photoshop", "gimp",
    }

    assert restoration.dcc_launch_command("maya", executable, str(source)) == [
        executable, "-file", str(source.resolve()),
    ]
    for host in direct_hosts:
        assert restoration.dcc_launch_command(host, executable, str(source)) == [
            executable, str(source.resolve()),
        ]

    unity_project = tmp_path / "UnityProject"
    unity_project.mkdir()
    assert restoration.dcc_launch_command("unity", executable, str(unity_project)) == [
        executable, "-projectPath", str(unity_project.resolve()),
    ]


def test_custom_executable_hint_is_honored_outside_default_install_roots(tmp_path) -> None:
    executable = tmp_path / "portable" / "maya.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"MZ")

    assert restoration.discover_dcc_executable("maya", str(executable)) == str(executable.resolve())


def test_unity_project_directories_are_restorable_sources(monkeypatch, tmp_path) -> None:
    project = tmp_path / "UnityProject"
    project.mkdir()
    executable = tmp_path / "Unity.exe"
    executable.write_bytes(b"MZ")
    calls = []

    class Process:
        pid = 8123

        def poll(self):
            return None

    monkeypatch.setattr(restoration, "discover_dcc_executable", lambda *_args: str(executable))
    launch = restoration.launch_dcc_source(
        {"provider": "unity", "source_path": str(project), "source_id": "unity-project"},
        popen=lambda command, **kwargs: calls.append((command, kwargs)) or Process(),
    )

    assert launch.process.pid == 8123
    assert calls[0][0] == [str(executable), "-projectPath", str(project.resolve())]
    assert calls[0][1]["env"]["TECH_CONNECTOR_RESTORING_SCENE"] == "unity-project"


def test_directory_sources_fingerprint_and_reconcile_for_launch(tmp_path) -> None:
    project = tmp_path / "UnityProject"
    project.mkdir()
    (project / "ProjectSettings").mkdir()
    document = FederatedSceneDocument(sources=[{
        "provider": "unity",
        "source_path": str(project),
        "source_fingerprint": source_file_fingerprint(project),
    }])

    fingerprint = source_file_fingerprint(project)
    result = reconcile_scene_sources(document, [])

    assert fingerprint["exists"] and fingerprint["kind"] == "directory"
    assert result[0]["source_exists"]
    assert result[0]["action"] == "launch_source"


def test_restore_launches_missing_3dsmax_session_and_captures_readback(tmp_path) -> None:
    source = tmp_path / "shot.max"
    source.write_text("max scene", encoding="utf-8")

    class Process:
        pid = 9912

        def poll(self):
            return None

    launch = restoration.DccRestoreLaunch(
        provider="3dsmax",
        source_path=str(source),
        executable_path="3dsmax.exe",
        process=Process(),
        launched_at=0.0,
    )
    discovery_count = 0

    def discover_sessions():
        nonlocal discovery_count
        discovery_count += 1
        if discovery_count == 1:
            return []
        return [{
            "provider": "3dsmax",
            "key": "3dsmax:7091",
            "scene": str(source),
            "pid": 9912,
        }]

    report = restoration.restore_scene_sources(
        [{"provider": "3dsmax", "source_path": str(source), "source_id": "max-shot"}],
        policy="automatic",
        discover_sessions=discover_sessions,
        open_source=lambda *_args: (False, "no idle session"),
        capture_snapshot=lambda key: (True, {"provider_id": "3dsmax", "session_key": key}),
        launch_source=lambda _source: launch,
        launch_timeout=0.5,
    )

    assert report["entries"][0]["status"] == "launched"
    assert report["session_keys"] == ["3dsmax:7091"]
    assert report["snapshots"]["3dsmax:7091"]["provider_id"] == "3dsmax"


def test_per_source_session_state_round_trips_for_two_maya_scenes(tmp_path) -> None:
    states = [
        dcc_session_state_from_snapshot({
            "provider_id": "maya",
            "active_camera": "|shotA|renderCam",
            "current_time": 1012,
            "frame_start": 1001,
            "frame_end": 1060,
            "fps": 24,
            "selection": ["root_ctrl", "root_ctrl"],
        }),
        dcc_session_state_from_snapshot({
            "provider_id": "maya",
            "active_camera": "persp",
            "current_time": 48,
            "frame_start": 1,
            "frame_end": 120,
            "fps": 30,
        }),
    ]
    document = FederatedSceneDocument(sources=[
        {"provider": "maya", "source_path": "shotA.ma", "session_state": states[0]},
        {"provider": "maya", "source_path": "rig.ma", "session_state": states[1]},
    ])

    path = save_federated_scene(tmp_path / "dual_maya.tcscene", document)
    restored, _blobs = load_federated_scene(path)

    assert restored.sources[0]["session_state"]["camera"]["native_id"] == "|shotA|renderCam"
    assert restored.sources[0]["session_state"]["selection_native_ids"] == ["root_ctrl"]
    assert restored.sources[1]["session_state"]["timeline"]["current"] == 48.0
    assert restored.sources[1]["session_state"]["timeline"]["fps"] == 30.0


def test_restore_applies_each_session_state_before_fresh_snapshot_capture(tmp_path) -> None:
    shot = tmp_path / "shot.ma"
    rig = tmp_path / "rig.ma"
    shot.write_text("shot", encoding="utf-8")
    rig.write_text("rig", encoding="utf-8")
    sources = [
        {
            "provider": "maya",
            "source_id": "shot",
            "source_path": str(shot),
            "session_state": dcc_session_state_from_snapshot({
                "provider_id": "maya", "active_camera": "shotCam",
                "current_time": 1012, "frame_start": 1001, "frame_end": 1060,
            }),
        },
        {
            "provider": "maya",
            "source_id": "rig",
            "source_path": str(rig),
            "session_state": dcc_session_state_from_snapshot({
                "provider_id": "maya", "active_camera": "persp",
                "current_time": 48, "frame_start": 1, "frame_end": 120,
            }),
        },
    ]
    sessions = [
        {"provider": "maya", "key": "maya:7001", "scene": str(shot), "scene_modified": False},
        {"provider": "maya", "key": "maya:7002", "scene": str(rig), "scene_modified": False},
    ]
    events = []

    def apply_state(key, state):
        events.append(("apply", key, state["timeline"]["current"], state["camera"]["native_id"]))
        return True, "restored"

    def capture(key):
        events.append(("capture", key))
        return True, {"provider_id": "maya", "session_key": key}

    report = restoration.restore_scene_sources(
        sources,
        policy="automatic",
        discover_sessions=lambda: sessions,
        open_source=lambda *_args: (False, "not used"),
        apply_session_state=apply_state,
        capture_snapshot=capture,
    )

    assert events == [
        ("apply", "maya:7001", 1012.0, "shotCam"),
        ("capture", "maya:7001"),
        ("apply", "maya:7002", 48.0, "persp"),
        ("capture", "maya:7002"),
    ]
    assert all(entry["session_state_status"] == "restored" for entry in report["entries"])
    assert all(entry["restoration_complete"] for entry in report["entries"])
    assert report["session_state_failures"] == []


def test_saved_session_state_without_adapter_is_reported_as_partial_restoration(tmp_path) -> None:
    source = tmp_path / "shot.ma"
    source.write_text("shot", encoding="utf-8")
    report = restoration.restore_scene_sources(
        [{
            "provider": "maya",
            "source_id": "shot",
            "source_path": str(source),
            "session_state": dcc_session_state_from_snapshot({"provider_id": "maya", "current_time": 10}),
        }],
        policy="automatic",
        discover_sessions=lambda: [{
            "provider": "maya", "key": "maya:7001", "scene": str(source), "scene_modified": False,
        }],
        open_source=lambda *_args: (False, "not used"),
    )

    assert report["entries"][0]["status"] == "attached"
    assert report["entries"][0]["session_state_status"] == "adapter_missing"
    assert not report["entries"][0]["restoration_complete"]
    assert report["session_state_failures"][0]["source_id"] == "shot"


def test_session_state_code_uses_ui_camera_routes_without_changing_timeline_rate() -> None:
    state = dcc_session_state_from_snapshot({
        "provider_id": "maya",
        "active_camera": "renderCam",
        "current_time": 42,
        "frame_start": 1,
        "frame_end": 100,
        "fps": 24,
    })

    maya_code = restoration.dcc_session_state_restore_code("maya", state)
    blender_code = restoration.dcc_session_state_restore_code("blender", state)

    assert "cmds.modelPanel" in maya_code and "cmds.currentTime" in maya_code
    assert "cmds.currentUnit" not in maya_code
    assert "use_local_camera" in blender_code and "scene.frame_set" in blender_code
