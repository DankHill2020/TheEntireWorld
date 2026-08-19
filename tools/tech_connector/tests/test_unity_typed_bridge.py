from __future__ import annotations

from pathlib import Path

from tech_connector.bridges.unity.unity_bridge import UnityBridge
from tech_connector.game_engine.integration.dcc_capability_audit_service import audit_dcc_host
from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
from tech_connector.installers.install_unity_bridge import install_unity_bridge


def test_unity_editor_bridge_source_implements_registered_typed_commands() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "bridges" / "unity" / "TechConnectorBridge.cs"
    ).read_text(encoding="utf-8")

    for command in (
        "assets.import_fbx", "material.create", "material.assign", "prefab.create",
        "scene.add_prefab", "workflow.inspect_prefab_asset",
    ):
        assert f'case "{command}"' in source
    assert 'case "scene.snapshot"' in source
    assert "if (request.include_materials && renderer != null)" in source
    assert "CaptureRendererMaterials(renderer, info)" in source
    assert "bbox = BoundsArray(bounds)" in source
    assert 'channel = "base_color"' not in source
    assert 'AddTextureBinding(material, materialInfo, "base_color"' in source
    assert "EditorApplication.update += ProcessPending" in source
    assert "if (Pending.TryDequeue(out item))" in source
    assert "Unity command timed out before main-thread execution and was cancelled" in source
    assert "MaxInFlightRequests = 8" in source
    assert "Arbitrary C# evaluation is disabled" in source
    report = audit_dcc_host("unity")
    assert report.status == "translated"
    assert report.executable_operation_count == 6
    for parity_check in (
        "mesh import settings", "material bindings", "prefab hierarchy", "scene instance transform",
    ):
        assert f'\\"{parity_check}\\"' in source


def test_unity_pipeline_runtime_honors_the_selected_session(monkeypatch) -> None:
    calls = []

    def execute(self, command, params=None, *, port=None, timeout=120.0):
        calls.append((command, params, port, timeout))
        return True, '{"asset_path":"Assets/Models/hero.fbx"}'

    monkeypatch.setattr(UnityBridge, "execute_command", execute)
    result = execute_pipeline_operation(
        "unity",
        "assets.import_fbx",
        "unity.command.assets.import_fbx",
        {"filepath": "C:/assets/hero.fbx"},
        session_port=7047,
    )

    assert result["asset_path"] == "Assets/Models/hero.fbx"
    assert calls[0][0] == "assets.import_fbx"
    assert calls[0][2] == 7047


def test_unity_bridge_rejects_oversized_commands_without_opening_a_socket() -> None:
    ok, message = UnityBridge._send_payload(
        {"command": "scene.add_prefab", "padding": "x" * UnityBridge.MAX_PAYLOAD_BYTES},
        port=7041,
        timeout=0.01,
    )

    assert not ok
    assert "1 MiB" in message


def test_unity_scene_snapshot_is_parsed_and_material_capture_is_typed(monkeypatch) -> None:
    calls = []

    def execute(self, command, params=None, *, port=None, timeout=120.0):
        calls.append((command, params, port))
        return True, '{"schema":"tech_connector.unity.scene_snapshot.v1","objects":[]}'

    monkeypatch.setattr(UnityBridge, "execute_command", execute)
    ok, snapshot = UnityBridge().get_scene_snapshot(
        selected_only=True,
        include_materials=False,
        limit=12,
        port=7048,
    )

    assert ok and snapshot["provider_id"] == "unity"
    assert snapshot["schema"] == "tech_connector.unity.scene_snapshot.v1"
    assert calls == [("scene.snapshot", {
        "selected_only": True,
        "include_materials": False,
        "limit": 12,
    }, 7048)]


def test_unity_bridge_installer_targets_project_editor_folder(tmp_path) -> None:
    project = tmp_path / "Game"
    (project / "Assets").mkdir(parents=True)
    (project / "ProjectSettings").mkdir()

    installed = install_unity_bridge(project)

    assert installed == project / "Assets" / "Editor" / "TechConnectorBridge.cs"
    assert installed.read_text(encoding="utf-8").startswith("#if UNITY_EDITOR")
