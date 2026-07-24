# coding=utf-8
"""
    Unit Test Suite for Automated K2 Graph Pin Wire Injector Engine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.unreal_k2_graph_wire_injector import UnrealK2GraphWireInjector


class TestUnrealK2GraphWireInjector(unittest.TestCase):
    """
        Test case suite for UnrealK2GraphWireInjector.
    """

    def setUp(self):
        """
            Sets up injector instance.
        """
        self.injector = UnrealK2GraphWireInjector(character_bp_path="/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix")

    def test_generate_k2_wire_injection_script(self):
        """
            Tests generating Unreal Engine Python K2 node pin wiring script.
        """
        script = self.injector.generate_k2_wire_injection_script()

        self.assertIn("import unreal", script)
        self.assertIn("beginplay_existed", script)
        self.assertIn("Sequence node chain", script)
        self.assertIn("EXISTING_BEGINPLAY_LINKED_AND_WIRED_SUCCESSFULLY", script)


if __name__ == "__main__":
    unittest.main()
