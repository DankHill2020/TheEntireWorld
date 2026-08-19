import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from tech_connector.bridges.maya.maya_bridge import MayaBridge


class FakeMayaBridge(MayaBridge):
    def __init__(self, open_ports, port_file):
        self.open_ports = set(open_ports)
        self.PORT_FILE = Path(port_file)

    def _is_port_open(self, host, port):
        return port in self.open_ports


class MayaBridgePortTests(unittest.TestCase):
    def test_execute_on_port_honors_preexisting_cancellation_without_connecting(self):
        canceled = threading.Event()
        canceled.set()
        bridge = object.__new__(MayaBridge)

        with patch("tech_connector.bridges.maya.maya_bridge.socket.socket") as socket_factory:
            ok, message = bridge.execute_on_port("print('unused')", port=7001, cancel_event=canceled)

        self.assertFalse(ok)
        self.assertEqual(message, "Maya command canceled.")
        socket_factory.assert_not_called()

    def test_execute_on_port_interrupts_a_waiting_receive(self):
        canceled = threading.Event()

        class WaitingSocket:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def settimeout(self, _timeout):
                return None

            def connect(self, _address):
                return None

            def sendall(self, _payload):
                return None

            def recv(self, _count):
                canceled.set()
                raise socket.timeout()

        bridge = object.__new__(MayaBridge)
        with patch("tech_connector.bridges.maya.maya_bridge.socket.socket", return_value=WaitingSocket()):
            ok, message = bridge.execute_on_port(
                "print('slow')", port=7001, timeout=30.0, cancel_event=canceled
            )

        self.assertFalse(ok)
        self.assertEqual(message, "Maya command canceled.")

    def test_timeline_sampler_install_does_not_report_a_scene_edit(self):
        captured = {}
        bridge = object.__new__(MayaBridge)

        def capture(code, **_kwargs):
            captured["code"] = code
            return True, "OK"

        bridge.execute_on_port = capture
        ok, _message = bridge.prepare_fast_timeline_sampler(
            port=7001,
            target_native_ids=["|mesh"],
        )

        self.assertTrue(ok)
        revision_line = next(
            line for line in captured["code"].splitlines()
            if line.startswith("_tech_connector_scene_revision =")
        )
        self.assertNotIn("+ 1", revision_line)

    def test_find_ports_scans_from_7001_and_returns_active_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            port_file = Path(tmp) / "maya_port.txt"
            with patch.dict(
                os.environ,
                {"MAYA_COMMAND_PORT": "", "MAYA_COMMAND_PORT_SCAN_COUNT": "4"},
                clear=False,
            ):
                bridge = FakeMayaBridge({7002, 7004}, port_file)

                self.assertEqual(bridge.find_ports(), [7002, 7004])
                self.assertEqual(bridge.find_port(), 7002)

    def test_file_port_is_prioritized_when_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            port_file = Path(tmp) / "maya_port.txt"
            port_file.write_text("7003", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"MAYA_COMMAND_PORT": "", "MAYA_COMMAND_PORT_SCAN_COUNT": "4"},
                clear=False,
            ):
                bridge = FakeMayaBridge({7001, 7003}, port_file)

                self.assertEqual(bridge.find_ports(), [7003, 7001])
                self.assertEqual(bridge.find_port(), 7003)

    def test_stale_file_port_is_removed_and_scan_still_finds_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            port_file = Path(tmp) / "maya_port.txt"
            port_file.write_text("7001", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"MAYA_COMMAND_PORT": "", "MAYA_COMMAND_PORT_SCAN_COUNT": "3"},
                clear=False,
            ):
                bridge = FakeMayaBridge({7002}, port_file)

                self.assertEqual(bridge.find_ports(), [7002])
                self.assertFalse(port_file.exists())


if __name__ == "__main__":
    unittest.main()
