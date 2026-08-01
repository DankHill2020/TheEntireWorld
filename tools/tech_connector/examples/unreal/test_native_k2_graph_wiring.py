# coding=utf-8
"""
    Unit Test Suite for Native Unreal C++ K2 Graph Auto-Wiring Subsystem.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.native_k2_graph_wiring_service import NativeK2GraphWiringService


class TestNativeK2GraphWiring(unittest.TestCase):
    """
        Test case suite for NativeK2GraphWiringService.
    """

    def setUp(self):
        """
            Sets up service instance.
        """
        self.service = NativeK2GraphWiringService()

    def test_cpp_subsystem_files_exist(self):
        """
            Tests that native C++ subsystem files exist in cpp_bridges directory.
        """
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cpp_dir = os.path.join(repo_root, "tech_connector", "cpp_bridges")
        h_file = os.path.join(cpp_dir, "TechConnectorK2GraphSubsystem.h")
        cpp_file = os.path.join(cpp_dir, "TechConnectorK2GraphSubsystem.cpp")

        self.assertTrue(os.path.exists(h_file), f"Header file missing: {h_file}")
        self.assertTrue(os.path.exists(cpp_file), f"CPP file missing: {cpp_file}")

        with open(h_file, "r", encoding="utf-8") as f:
            h_text = f.read()
        self.assertIn("AutoWireBlueprintExecutionPins", h_text)
        self.assertIn("AutoWireAnimGraphOutputPose", h_text)

    def test_generate_native_cpp_wiring_script(self):
        """
            Tests generating Python script invoking native C++ graph subsystem.
        """
        script = self.service.generate_native_cpp_wiring_script()
        self.assertIn("TechConnectorK2GraphSubsystem", script)
        self.assertIn("auto_wire_blueprint_execution_pins", script)


if __name__ == "__main__":
    unittest.main()
