from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from tech_connector.bridges.mcphost_bridge import TerminalBridge


class MCPHostLifecycleTests(unittest.TestCase):
    def test_stop_terminates_waits_and_clears_process(self):
        bridge = TerminalBridge()
        process = MagicMock()
        process.poll.return_value = None
        bridge.mode = "pipes"
        bridge.proc = process
        bridge.running = True

        self.assertTrue(bridge.stop())

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=1.0)
        self.assertIsNone(bridge.proc)
        self.assertFalse(bridge.running)

    def test_stop_is_idempotent(self):
        bridge = TerminalBridge()
        self.assertTrue(bridge.stop())
        self.assertTrue(bridge.stop())


if __name__ == "__main__":
    unittest.main()
