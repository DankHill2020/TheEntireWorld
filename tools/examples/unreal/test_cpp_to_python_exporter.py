# coding=utf-8
"""
    Unit Test Suite for C++ to Unreal Python Binding & Exporter Service.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.cpp_to_python_exporter_service import (
    CppToPythonExporterService,
)


class TestCppToPythonExporter(unittest.TestCase):
    """
        Test case suite for CppToPythonExporterService.
    """

    def setUp(self):
        """
            Sets up test exporter instance.
        """
        self.exporter = CppToPythonExporterService()
        self.class_name = "UTechConnectorGraphBridge"
        self.functions = [
            {
                "name": "WireAnimGraphPoseOutput",
                "return_type": "bool",
                "params": [
                    {"name": "AnimInstancePath", "type": "FString"},
                    {"name": "StateMachineName", "type": "FString"}
                ]
            },
            {
                "name": "InjectCharacterMovementNode",
                "return_type": "bool",
                "params": [
                    {"name": "CharacterBPPath", "type": "FString"},
                    {"name": "InputKey", "type": "FString"}
                ]
            }
        ]

    def test_generate_cpp_reflection_header(self):
        """
            Tests generating Unreal C++ header with UFUNCTION(BlueprintCallable) macros.
        """
        header = self.exporter.generate_cpp_reflection_header(self.class_name, self.functions)

        self.assertIn("UCLASS(BlueprintType, Blueprintable)", header)
        self.assertIn("UFUNCTION(BlueprintCallable, Category = \"TechConnector|CppBridge\")", header)
        self.assertIn("static bool WireAnimGraphPoseOutput(FString AnimInstancePath, FString StateMachineName);", header)
        self.assertIn("static bool InjectCharacterMovementNode(FString CharacterBPPath, FString InputKey);", header)

    def test_export_cpp_feature_to_python(self):
        """
            Tests exporting C++ header and Python wrapper files to disk.
        """
        with tempfile.TemporaryDirectory() as export_dir:
            files = self.exporter.export_cpp_feature_to_python(self.class_name, self.functions, export_dir)

            self.assertTrue(os.path.exists(files["cpp_header"]))
            self.assertTrue(os.path.exists(files["python_wrapper"]))

            with open(files["cpp_header"], "r", encoding="utf-8") as f:
                h_text = f.read()
            self.assertIn("UTechConnectorGraphBridge", h_text)

            with open(files["python_wrapper"], "r", encoding="utf-8") as f:
                py_text = f.read()
            self.assertIn("UTechConnectorGraphBridgeWrapper", py_text)


if __name__ == "__main__":
    unittest.main()
