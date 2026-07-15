import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bridges.maya.maya_bridge import MayaBridge


class FakeMayaBridge(MayaBridge):
    def __init__(self, open_ports, port_file):
        self.open_ports = set(open_ports)
        self.PORT_FILE = Path(port_file)

    def _is_port_open(self, host, port):
        return port in self.open_ports


class MayaBridgePortTests(unittest.TestCase):
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
