from __future__ import annotations

import base64
import json
import socket
import sys
import threading
from types import SimpleNamespace

from max_tools import operations
from tech_connector.bridges.max.max_bridge import MaxBridge, PLUGIN_SOURCE_CODE
from tech_connector.game_engine.integration.dcc_capability_audit_service import audit_dcc_host
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.rigging_host_adapter_service import MAX_CAPABILITY_STATUS
from tech_connector.game_engine.integration.scene_snapshot_provider import max_scene_snapshot_code
from tech_connector.game_engine.integration.dcc_bridge_setup import install_3dsmax_startup_bridge


def _one_shot_server() -> tuple[int, threading.Thread, list[dict]]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    received: list[dict] = []

    def serve() -> None:
        with listener:
            connection, _address = listener.accept()
            with connection:
                raw = b""
                while b"\n" not in raw:
                    raw += connection.recv(65536)
                request = json.loads(raw.decode("utf-8"))
                received.append(request)
                code = base64.b64decode(request["code_b64"]).decode("utf-8")
                connection.sendall((json.dumps({"ok": True, "result": "ran:" + code}) + "\n").encode("utf-8"))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, thread, received


def test_3dsmax_bridge_protocol_and_generated_sources_are_valid_python() -> None:
    compile(PLUGIN_SOURCE_CODE, "<3dsmax-plugin>", "exec")
    snapshot_code = max_scene_snapshot_code(selected_only=True, include_materials=False, limit=12)
    compile(snapshot_code, "<3dsmax-snapshot>", "exec")
    assert '"geometry"' in snapshot_code and '"bbox"' in snapshot_code
    assert "getFaceMatID" in snapshot_code and "getTVFace" in snapshot_code
    assert "if include_materials:" in snapshot_code
    port, thread, received = _one_shot_server()

    ok, output = MaxBridge().execute_on_port("print('hello')", port=port, timeout=2.0)
    thread.join(timeout=2.0)

    assert ok and output == "ran:print('hello')"
    assert received[0]["timeout_seconds"] > 0.0


def test_3dsmax_snapshot_honors_exact_session_and_parses_contract(monkeypatch) -> None:
    calls = []

    def execute_on_port(self, code, *, port, timeout=10):
        calls.append((code, port, timeout))
        return True, '{"schema":"tech_connector.3dsmax.scene_snapshot.v1","objects":[]}'

    monkeypatch.setattr(MaxBridge, "execute_on_port", execute_on_port)
    ok, snapshot = MaxBridge().get_scene_snapshot(
        selected_only=True,
        include_materials=False,
        limit=8,
        timeout=4.0,
        port=7084,
    )

    assert ok and snapshot["provider_id"] == "3dsmax"
    assert calls[0][1:] == (7084, 4.0)
    assert "include_materials = False" in calls[0][0]


def test_3dsmax_registry_is_concrete_and_audited_as_translated() -> None:
    registry = dcc_operation_registry("3dsmax")
    report = audit_dcc_host("3dsmax")

    assert len(registry) >= 12
    assert all(item.function.startswith("max_tools.operations.") for item in registry.values())
    assert report.status == "translated"
    translated_rigging = sum(status == "translated" for status in MAX_CAPABILITY_STATUS.values())
    assert report.declared_operation_count == report.executable_operation_count == len(registry) + translated_rigging


def test_pymxs_scene_operations_are_testable_without_importing_max(monkeypatch) -> None:
    class Node:
        def __init__(self, name: str):
            self.name = name

    class Runtime:
        def __init__(self) -> None:
            self.objects = [Node("Box01"), Node("Camera01")]
            self.selection = []

        def getNodeByName(self, name: str):
            return next((item for item in self.objects if item.name == name), None)

        def clearSelection(self) -> None:
            self.selection = []

        def select(self, values) -> None:
            self.selection = list(values)

    runtime = Runtime()
    monkeypatch.setitem(sys.modules, "pymxs", SimpleNamespace(runtime=runtime))

    assert operations.scene_list() == ["Box01", "Camera01"]
    assert operations.scene_select(["Camera01"]) == ["Camera01"]
    assert [item.name for item in runtime.selection] == ["Camera01"]


def test_3dsmax_startup_setup_is_idempotent(tmp_path, monkeypatch) -> None:
    from tech_connector.bridges.max import max_bridge

    monkeypatch.setattr(max_bridge, "default_startup_dir", lambda: tmp_path)
    installed = install_3dsmax_startup_bridge()
    current = install_3dsmax_startup_bridge()

    assert installed.ok and installed.restart_required and installed.installed_versions
    assert current.ok and not current.restart_required and current.current_versions
    assert (tmp_path / max_bridge.PLUGIN_FILENAME).read_text(encoding="utf-8") == max_bridge.PLUGIN_SOURCE_CODE
