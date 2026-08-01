# coding=utf-8
"""
    Unit Test Suite for Unreal K2 Node Graph Bridge & Snippet Generator.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.bridges.unreal.unreal_graph_bridge import UnrealGraphBridge
from tech_connector.services.blueprint_snippet_generator_service import (
    BlueprintSnippetGeneratorService,
)
from utilities.unreal.http_bridge import send_unreal_http_command


class TestUnrealGraphBridge(unittest.TestCase):
    """
        Test case suite for UnrealGraphBridge.
    """

    def setUp(self):
        """
            Sets up test bridge instance.
        """
        self.bridge = UnrealGraphBridge(
            char_bp_path="/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix",
            anim_bp_path="/Game/Variant_Combat/Anims/ABP_Manny_Combat"
        )

    def test_build_all_k2_snippets(self):
        """
            Tests generating and saving all K2 visual node graph snippets.
        """
        snippets = self.bridge.build_all_k2_snippets()
        self.assertEqual(len(snippets), 3)

        for key, path in snippets.items():
            self.assertTrue(os.path.exists(path), f"Snippet file should exist: {path}")
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Begin Object Class=", content)

    def test_live_unreal_graph_bridge_compilation(self):
        """
            Tests live Unreal Engine compilation using UnrealGraphBridge payload.
        """
        ok1, resp1, time1_ms = send_unreal_http_command(
            "unreal_tools.blueprint.scan_blueprint",
            args=[self.bridge.char_bp_path]
        )
        ok2, resp2, time2_ms = send_unreal_http_command(
            "unreal_tools.blueprint.scan_blueprint",
            args=[self.bridge.anim_bp_path]
        )

        self.assertTrue(ok1)
        self.assertTrue(ok2)


if __name__ == "__main__":
    unittest.main()
