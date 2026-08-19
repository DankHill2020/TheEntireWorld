from __future__ import annotations

import json

from tech_connector.bridges import session_discovery
from tech_connector.bridges.blender.blender_bridge import BlenderBridge
from tech_connector.bridges.gimp.gimp_bridge import GimpBridge
from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
from tech_connector.bridges.max.max_bridge import MaxBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge
from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge
from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.unity.unity_bridge import UnityBridge
from tech_connector.game_engine.integration.dcc_bridge_setup import auto_reconnect_dcc_bridges
from tech_connector.ui.three_d_mesh_painter_widget import PortBoundDccBridge, scene_snapshot_bridge_for_provider


def test_candidate_ports_keep_preferred_session_first(monkeypatch, tmp_path) -> None:
    port_file = tmp_path / "host_port.txt"
    port_file.write_text("7104", encoding="utf-8")
    monkeypatch.setattr(session_discovery, "preferred_session_port", lambda _provider: 7107)

    ports = session_discovery.candidate_session_ports(
        "host",
        port_files=(str(port_file),),
        default_port=7101,
        default_scan_count=4,
    )

    assert ports == [7107, 7104, 7101, 7102, 7103]


def test_discovery_preserves_candidate_order(monkeypatch) -> None:
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _timeout):
            pass

        def connect_ex(self, endpoint):
            return 0 if endpoint[1] in {7021, 7023} else 1

    monkeypatch.setattr(session_discovery.socket, "socket", lambda *_args, **_kwargs: FakeSocket())
    assert session_discovery.discover_open_ports([7023, 7022, 7021]) == [7023, 7021]


def test_direct_socket_bridges_share_multi_session_contract() -> None:
    bridge_types = (
        MayaBridge, BlenderBridge, MaxBridge, MotionBuilderBridge, HoudiniBridge,
        SubstancePainterBridge, UnrealBridge, UnityBridge, PhotoshopBridge, GimpBridge,
    )
    for bridge_type in bridge_types:
        assert callable(getattr(bridge_type, "find_ports", None)), bridge_type.__name__
        assert callable(getattr(bridge_type, "session_info", None)), bridge_type.__name__
        assert callable(getattr(bridge_type, "sessions", None)), bridge_type.__name__


def test_auto_reconnect_preflights_all_ten_external_hosts() -> None:
    class SocketBridge:
        def find_port(self):
            return 7001

    class UnrealHealthBridge(SocketBridge):
        def health_check(self, *, timeout: float):
            return {
                "connected": True,
                "python_available": True,
                "project_name": "Qualification",
                "loaded_level": "Main",
                "timeout": timeout,
            }

    hosts = (
        "maya", "blender", "3dsmax", "motionbuilder", "houdini",
        "substance_painter", "unreal", "unity", "photoshop", "gimp",
    )
    factories = {host: (UnrealHealthBridge if host == "unreal" else SocketBridge) for host in hosts}

    result = auto_reconnect_dcc_bridges(factories)

    assert set(result) == set(hosts)
    assert all(row["connected"] for row in result.values())
    assert result["unreal"]["identity_readback"]


def test_global_scene_picker_bridge_registry_covers_all_ten_exact_sessions() -> None:
    hosts = (
        "maya", "blender", "3dsmax", "motionbuilder", "houdini",
        "substance_painter", "unreal", "unity", "photoshop", "gimp",
    )
    for index, host in enumerate(hosts):
        port = 7200 + index
        bridge = scene_snapshot_bridge_for_provider(f"{host}:{port}")
        assert callable(getattr(bridge, "get_scene_snapshot", None)), host
        if host == "unreal":
            assert bridge._forced_port == port
        else:
            assert isinstance(bridge, PortBoundDccBridge)
            assert bridge.port == port


def test_motionbuilder_snapshot_executes_on_requested_session(monkeypatch) -> None:
    calls = []

    def execute_on_port(self, code, *, port, timeout=10):
        calls.append((port, timeout, code))
        return True, json.dumps({
            "schema": "tech_connector.motionbuilder.scene_snapshot.v1",
            "provider_id": "motionbuilder",
            "process_id": 42,
            "scene": "C:/show/walk.fbx",
            "objects": [],
        })

    monkeypatch.setattr(MotionBuilderBridge, "execute_on_port", execute_on_port)
    ok, snapshot = MotionBuilderBridge().get_scene_snapshot(port=7312, timeout=2.5)

    assert ok and snapshot["provider_id"] == "motionbuilder"
    assert calls[0][:2] == (7312, 2.5)
