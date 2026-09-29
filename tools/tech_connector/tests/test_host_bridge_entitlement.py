"""Short-lived entitlement-derived authorization for embedded DCC bridges."""

from __future__ import annotations

import base64
import importlib.util
import json
import socket
import sys
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tech_connector.bridges.blender.blender_bridge import ADDON_SOURCE_CODE
from tech_connector.bridges.houdini.houdini_bridge import PLUGIN_SOURCE_CODE as HOUDINI_SOURCE
from tech_connector.bridges.gimp.gimp_bridge import PLUGIN_SOURCE_CODE as GIMP_SOURCE
from tech_connector.bridges.max.max_bridge import PLUGIN_SOURCE_CODE as MAX_SOURCE
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.motionbuilder.motionbuilder_bridge import (
    PLUGIN_SOURCE_CODE as MOTIONBUILDER_SOURCE,
)
from tech_connector.bridges.photoshop.photoshop_bridge import (
    PhotoshopBridge,
    install_to_plugin_dir as install_photoshop_bridge,
)
from tech_connector.bridges.substance_painter.substance_painter_bridge import (
    PLUGIN_SOURCE_CODE as SUBSTANCE_PAINTER_SOURCE,
)
from tech_connector.bridges.session_authorization import (
    embedded_bridge_authorization_source,
    issue_bridge_session,
    load_bridge_session,
    validate_bridge_session,
)
from tech_connector.tests.test_licensing_foundation import NOW, _payload, _runtime_context, _sign


def _licensed_evaluation(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    context = _runtime_context(tmp_path, private_key)
    payload = _payload("perpetual")
    payload["activation"]["device_id_hash"] = context.device_identity.device_id_hash()
    context.cache_verified_token(_sign(payload, private_key), now=NOW)
    return context.evaluate(
        product="tech_connector",
        app_major_version="7",
        commercial_use=True,
        now=NOW,
    )


def test_bridge_session_contains_no_identity_project_or_financial_metadata(tmp_path) -> None:
    path = tmp_path / "bridge_session.json"
    session = issue_bridge_session(
        _licensed_evaluation(tmp_path),
        path=path,
        now=NOW,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"schema", "session_token", "issued_at", "expires_at", "hosts"}
    assert {"substance_painter", "unity", "3dsmax", "gimp"}.issubset(payload["hosts"])
    assert validate_bridge_session(session.token, "maya", path=path, now=NOW)
    assert not validate_bridge_session("wrong-token", "maya", path=path, now=NOW)
    assert not validate_bridge_session(session.token, "unsupported", path=path, now=NOW)
    serialized = json.dumps(payload).casefold()
    assert not any(
        term in serialized
        for term in ("email", "account_id", "organization_id", "license_id", "project_id", "profit")
    )


def test_bridge_session_expires_and_cannot_outlive_offline_entitlement(tmp_path) -> None:
    path = tmp_path / "bridge_session.json"
    session = issue_bridge_session(
        _licensed_evaluation(tmp_path),
        path=path,
        now=NOW,
        maximum_lifetime=timedelta(hours=12),
    )

    assert session.expires_at == NOW + timedelta(hours=12)
    assert load_bridge_session("blender", path=path, now=session.expires_at) is None


def test_bridge_session_rejects_tampered_lifetime(tmp_path) -> None:
    path = tmp_path / "bridge_session.json"
    session = issue_bridge_session(
        _licensed_evaluation(tmp_path),
        path=path,
        now=NOW,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["issued_at"] = payload["expires_at"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_bridge_session("maya", path=path, now=NOW) is None
    assert not validate_bridge_session(session.token, "maya", path=path, now=NOW)


def test_bridge_session_requires_explicit_dcc_host_capability(tmp_path) -> None:
    evaluation = _licensed_evaluation(tmp_path)
    restricted_claims = replace(
        evaluation.claims,
        capabilities=("official_api_access",),
    )
    restricted_evaluation = evaluation.__class__(restricted_claims, evaluation.decision)

    try:
        issue_bridge_session(restricted_evaluation, path=tmp_path / "bridge_session.json", now=NOW)
    except PermissionError as exc:
        assert "DCC host access" in str(exc)
    else:
        raise AssertionError("DCC bridge session was issued without dcc_host_access")


def test_embedded_validator_uses_only_standard_library_and_rejects_bad_token(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "bridge_session.json"
    current = datetime.now(timezone.utc)
    session = issue_bridge_session(
        _licensed_evaluation(tmp_path),
        path=path,
        now=current,
    )
    monkeypatch.setenv("TECH_CONNECTOR_BRIDGE_SESSION_FILE", str(path))
    namespace = {}
    source = embedded_bridge_authorization_source("houdini")
    exec(compile(source, "<embedded-bridge-auth>", "exec"), namespace, namespace)

    assert namespace["_tech_connector_bridge_authorized"](
        {"bridge_session": session.token}
    )
    assert not namespace["_tech_connector_bridge_authorized"](
        {"bridge_session": "wrong"}
    )


def test_every_protected_embedded_python_bridge_requires_session_authorization() -> None:
    for source in (
        ADDON_SOURCE_CODE,
        HOUDINI_SOURCE,
        MOTIONBUILDER_SOURCE,
        SUBSTANCE_PAINTER_SOURCE,
        MAX_SOURCE,
        GIMP_SOURCE,
    ):
        compile(source, "<embedded-host>", "exec")
        assert "bridge_authorization_required" in source or "activation is required" in source
        assert "bridge_session" in source

    maya_server = (
        Path(__file__).resolve().parents[2] / "maya_tools" / "maya_menu.py"
    ).read_text(encoding="utf-8")
    handler_start = maya_server.index("def _handle_bridge_client")
    handler_end = maya_server.index("def _serve_authenticated_bridge", handler_start)
    handler = maya_server[handler_start:handler_end]
    assert "validate_bridge_session(session_token, \"maya\")" in handler
    assert "bridge_authorization_required" in handler
    assert "executeInMainThreadWithResult" in handler
    assert handler.index("validate_bridge_session") < handler.index(
        "executeInMainThreadWithResult"
    )

    unreal_server = (
        Path(__file__).resolve().parents[2] / "unreal_tools" / "http_server.py"
    ).read_text(encoding="utf-8")
    assert 'validate_bridge_session(data.get("bridge_session", ""), "unreal")' in unreal_server
    assert "bridge_authorization_required" in unreal_server

    unreal_daemon = (
        Path(__file__).resolve().parents[1]
        / "bridges"
        / "unreal"
        / "project_intelligence_daemon.py"
    ).read_text(encoding="utf-8")
    assert 'self.headers.get("X-Tech-Connector-Bridge-Session", "")' in unreal_daemon
    assert 'validate_bridge_session(' in unreal_daemon
    assert '"bridge_authorization_required"' in unreal_daemon

    project_service = (
        Path(__file__).resolve().parents[1] / "services" / "project_service.py"
    ).read_text(encoding="utf-8")
    assert '"X-Tech-Connector-Bridge-Session": bridge_session_token("unreal")' in project_service


def test_generated_substance_server_rejects_before_queueing_code(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "TECH_CONNECTOR_BRIDGE_SESSION_FILE",
        str(tmp_path / "missing-session.json"),
    )
    namespace = {}
    exec(compile(SUBSTANCE_PAINTER_SOURCE, "<substance-host>", "exec"), namespace, namespace)
    server_socket, client_socket = socket.socketpair()
    worker = threading.Thread(
        target=namespace["_handle_client"],
        args=(server_socket,),
        daemon=True,
    )
    worker.start()
    try:
        client_socket.sendall(
            json.dumps(
                {
                    "code_b64": base64.b64encode(b"raise AssertionError('executed')").decode("ascii"),
                    "bridge_session": "invalid",
                }
            ).encode("utf-8")
            + b"\n"
        )
        response = json.loads(client_socket.recv(4096).decode("utf-8"))
    finally:
        client_socket.close()
        worker.join(timeout=2)

    assert response["code"] == "bridge_authorization_required"
    assert namespace["_jobs"].empty()


def test_maya_client_uses_authenticated_json_instead_of_raw_python(
    monkeypatch,
) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    received = []

    def serve_once():
        connection, _address = listener.accept()
        with connection:
            raw = b""
            while b"\n" not in raw:
                raw += connection.recv(4096)
            received.append(json.loads(raw.decode("utf-8")))
            connection.sendall(json.dumps({"ok": True, "result": "json-ok"}).encode("utf-8") + b"\n")
        listener.close()

    worker = threading.Thread(target=serve_once, daemon=True)
    worker.start()
    monkeypatch.setattr(
        "tech_connector.bridges.maya.maya_bridge.bridge_session_token",
        lambda host_id: "maya-session-token-with-at-least-32-characters"
        if host_id == "maya"
        else "",
    )

    ok, result = MayaBridge().execute_on_port("print('json')", port=port, timeout=2)
    worker.join(timeout=2)

    assert ok and result == "json-ok"
    assert received[0]["bridge_session"].startswith("maya-session-token")
    assert base64.b64decode(received[0]["code_b64"]).decode("utf-8") == "print('json')"


def test_maya_authenticated_json_server_round_trip(
    tmp_path,
    monkeypatch,
) -> None:
    session_token = "maya-round-trip-session-token-with-at-least-32-characters"
    now = datetime.now(timezone.utc)
    session_path = tmp_path / "bridge_session.json"
    session_path.write_text(
        json.dumps(
            {
                "schema": "tech_connector.bridge_session.v1",
                "session_token": session_token,
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "hosts": ["maya"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TECH_CONNECTOR_BRIDGE_SESSION_FILE", str(session_path))
    monkeypatch.setenv("MAYA_COMMAND_PORT_SCAN_COUNT", "1")

    maya_module = ModuleType("maya")
    maya_module.__path__ = []
    cmds_module = ModuleType("maya.cmds")
    mel_module = ModuleType("maya.mel")
    utils_module = ModuleType("maya.utils")
    api_module = ModuleType("maya.api")
    open_maya_module = ModuleType("maya.api.OpenMaya")

    def command_port(*_args, **kwargs):
        if kwargs.get("q") and kwargs.get("listPorts"):
            return []
        if kwargs.get("close"):
            return True
        raise AssertionError("the authenticated Maya server must not open commandPort")

    cmds_module.commandPort = command_port
    cmds_module.file = lambda **_kwargs: ""
    cmds_module.about = lambda **_kwargs: "2026"
    mel_module.eval = lambda _code: None
    utils_module.executeInMainThreadWithResult = lambda callback: callback()
    utils_module.executeDeferred = lambda callback: callback()
    maya_module.cmds = cmds_module
    maya_module.mel = mel_module
    maya_module.utils = utils_module
    maya_module.api = api_module
    api_module.OpenMaya = open_maya_module
    for name, module in {
        "maya": maya_module,
        "maya.cmds": cmds_module,
        "maya.mel": mel_module,
        "maya.utils": utils_module,
        "maya.api": api_module,
        "maya.api.OpenMaya": open_maya_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    port_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port_probe.bind(("127.0.0.1", 0))
    port = int(port_probe.getsockname()[1])
    port_probe.close()
    maya_menu_path = Path(__file__).resolve().parents[2] / "maya_tools" / "maya_menu.py"
    spec = importlib.util.spec_from_file_location("_test_authenticated_maya_menu", maya_menu_path)
    assert spec is not None and spec.loader is not None
    maya_menu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maya_menu)
    maya_menu.COMMAND_PORT_START = port
    maya_menu.COMMAND_PORT_FILE = str(tmp_path / "maya_port.txt")
    maya_menu.COMMAND_PORT_SESSION_FILE = str(tmp_path / "maya_sessions.json")

    try:
        assert maya_menu.initialize_command_port() == port
        ok, result = MayaBridge().execute_on_port(
            "print('maya-json-round-trip')",
            port=port,
            timeout=2,
        )
    finally:
        maya_menu.cleanup_command_port_files()

    assert ok
    assert result == "maya-json-round-trip"


def test_every_official_bridge_client_carries_the_host_session() -> None:
    source_root = Path(__file__).resolve().parents[1]
    clients = {
        "maya": source_root / "bridges" / "maya" / "maya_bridge.py",
        "blender": source_root / "bridges" / "blender" / "blender_bridge.py",
        "unreal": source_root / "bridges" / "unreal" / "unreal_bridge.py",
        "houdini": source_root / "bridges" / "houdini" / "houdini_bridge.py",
        "motionbuilder": source_root / "bridges" / "motionbuilder" / "motionbuilder_bridge.py",
        "substance_painter": source_root / "bridges" / "substance_painter" / "substance_painter_bridge.py",
        "unity": source_root / "bridges" / "unity" / "unity_bridge.py",
        "3dsmax": source_root / "bridges" / "max" / "max_bridge.py",
        "gimp": source_root / "bridges" / "gimp" / "gimp_bridge.py",
    }

    for host_id, path in clients.items():
        source = path.read_text(encoding="utf-8")
        assert f'bridge_session_token("{host_id}")' in source


def test_installed_substance_and_unity_servers_reject_before_execution() -> None:
    source_root = Path(__file__).resolve().parents[1]
    substance_installer = (
        source_root / "installers" / "substance_painter_ai_studio_bridge.py"
    ).read_text(encoding="utf-8")
    assert 'payload.get("bridge_session", "")' in substance_installer
    assert '"bridge_authorization_required"' in substance_installer
    assert substance_installer.index("validate_bridge_session(") < substance_installer.index(
        'base64.b64decode(payload["code_b64"])'
    )

    unity_server = (
        source_root / "bridges" / "unity" / "TechConnectorBridge.cs"
    ).read_text(encoding="utf-8")
    assert "public string bridge_session;" in unity_server
    assert "BridgeAuthorized(request.bridge_session)" in unity_server
    assert 'code = "bridge_authorization_required"' in unity_server
    assert 'session.schema != "tech_connector.bridge_session.v1"' in unity_server
    assert unity_server.index("BridgeAuthorized(request.bridge_session)") < unity_server.index(
        "Pending.Enqueue(item)"
    )


def test_unauthenticated_photoshop_bridge_fails_closed_outside_explicit_development(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", raising=False)
    monkeypatch.delenv(
        "TECH_CONNECTOR_ENABLE_EXPERIMENTAL_PHOTOSHOP_BRIDGE",
        raising=False,
    )

    ok, message = PhotoshopBridge().execute_on_port(
        '{"command":"document.info"}',
        port=7061,
    )
    assert not ok
    assert "entitlement-derived pairing" in message
    assert not PhotoshopBridge.info.supports_direct_execute
    try:
        install_photoshop_bridge(tmp_path / "photoshop-plugin")
    except PermissionError as exc:
        assert "entitlement-derived pairing" in str(exc)
    else:
        raise AssertionError("Photoshop's unauthenticated bridge installer did not fail closed")

    monkeypatch.setenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", "1")
    monkeypatch.setenv("TECH_CONNECTOR_ENABLE_EXPERIMENTAL_PHOTOSHOP_BRIDGE", "1")
    installed = install_photoshop_bridge(tmp_path / "photoshop-plugin")
    assert (installed / "index.js").is_file()


def test_legacy_maya_launchers_do_not_open_alternate_raw_command_ports() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    maya_setup = (repository_root / "maya_tools" / "maya_setup.py").read_text(
        encoding="utf-8"
    )
    hik_ui = (
        repository_root / "maya_tools" / "Rigging" / "mocap" / "hik_ui.py"
    ).read_text(encoding="utf-8")

    assert "TECH_CONNECTOR_SECURE_MAYA_PORT" in maya_setup
    assert "maya_menu.initialize_command_port()" in maya_setup
    assert "cmds.commandPort(" not in maya_setup
    assert "cmds.commandPort(" not in hik_ui
