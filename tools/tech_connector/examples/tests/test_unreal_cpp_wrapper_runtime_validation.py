from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tech_connector.services.unreal.unreal_cpp_wrapper_service import (
    create_unreal_cpp_wrapper_plan,
    diagnose_unreal_cpp_build_environment,
    set_unreal_plugin_enabled_transactionally,
)


class TestUnrealCppWrapperRuntimeValidation(unittest.TestCase):
    def test_transactional_enable_refuses_source_only_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Probe.uproject").write_text('{"EngineAssociation":"5.8","Plugins":[]}', encoding="utf-8")
            create_unreal_cpp_wrapper_plan(root, "Expose runtime validation to Python", apply=True)
            diagnostic = diagnose_unreal_cpp_build_environment(root, root / "MissingEngine")
            result = set_unreal_plugin_enabled_transactionally(
                root,
                enabled=True,
                engine_root=root / "MissingEngine",
                apply=True,
            )
            descriptor = (root / "Probe.uproject").read_text(encoding="utf-8")

        self.assertFalse(diagnostic["gates"]["safe_to_enable"])
        self.assertFalse(result["ok"])
        self.assertNotIn("AIStudioBridge", descriptor)

    def test_runtime_montage_request_generates_pie_validation_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Probe.uproject").write_text("{}", encoding="utf-8")
            plan = create_unreal_cpp_wrapper_plan(
                root,
                "Expose PIE runtime montage validation to Python.",
                apply=True,
            ).to_dict()

        self.assertEqual(plan["capability"], "validate_character_montages_in_pie")
        self.assertEqual(plan["function_name"], "ValidateCharacterMontagesInPIE")
        self.assertIn("validate_character_montages_in_pie", plan["python_call"])

    def test_auto_placement_reuses_existing_project_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Probe.uproject").write_text("{}", encoding="utf-8")
            existing = root / "Plugins" / "AIStudioBridge"
            existing.mkdir(parents=True)
            plan = create_unreal_cpp_wrapper_plan(root, "Expose to Python", apply=False).to_dict()
        self.assertEqual(Path(plan["plugin_root"]), existing)

    def test_runtime_wrapper_contains_anim_instance_montage_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Probe.uproject").write_text("{}", encoding="utf-8")
            plan = create_unreal_cpp_wrapper_plan(
                root,
                "Expose runtime play anim montage validation in PIE.",
                apply=True,
            ).to_dict()
            plugin_root = Path(plan["plugin_root"])
            descriptor = (plugin_root / "AIStudioBridge.uplugin").read_text(encoding="utf-8")
            cpp = (plugin_root / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp").read_text(
                encoding="utf-8"
            )
            header = (plugin_root / "Source" / "AIStudioBridge" / "Public" / "AIStudioBridgeLibrary.h").read_text(
                encoding="utf-8"
            )

        self.assertIn("ValidateCharacterMontagesInPIE", header)
        self.assertIn('"EnabledByDefault": false', descriptor)
        self.assertIn("InspectAnimationSequence", header)
        self.assertIn("InspectCharacterInPIE", header)
        self.assertIn("GEditor->PlayWorld", cpp)
        self.assertIn("Montage_Play", cpp)
        self.assertIn("Montage_IsActive", cpp)
        self.assertIn("ExpectedAnimClassContains", cpp)
        self.assertIn("GetNumberOfSampledKeys", cpp)
        self.assertIn("GetMovementName", cpp)
        self.assertIn("GetCurrentActiveMontage", cpp)
        self.assertIn("FindFProperty", cpp)

    def test_apply_writes_reflected_wrapper_when_body_is_functional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Probe.uproject").write_text("{}", encoding="utf-8")
            plan = create_unreal_cpp_wrapper_plan(
                root,
                "add anim graph state to anim blueprint",
                apply=True,
            ).to_dict()
            plugin_root = Path(plan["plugin_root"])
            cpp = (plugin_root / "Source" / "AIStudioBridge" / "Private" / "AIStudioBridgeLibrary.cpp").read_text(
                encoding="utf-8"
            )
            self.assertTrue((plugin_root / "AIStudioBridge.uplugin").exists())

            self.assertTrue(plan["ok"])
            self.assertEqual("functional", plan["functional_body_contract"]["status"])
            self.assertTrue(all(row["action"] == "write" for row in plan["files"]))
            self.assertNotIn("cpp_body_required", cpp)
            self.assertIn("FEdGraphSchemaAction_NewStateNode::SpawnNodeFromTemplate<UAnimStateNode>", cpp)


if __name__ == "__main__":
    unittest.main()
