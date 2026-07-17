import unittest

from tech_connector.bridges.unreal.unreal_enhanced_input import _asset_path
from tech_connector.bridges.unreal.unreal_diagnostics import _error_summary
from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS, unreal_operation_payload


class TestUnrealEnhancedInput(unittest.TestCase):
    def test_asset_path_normalizes_object_suffix(self):
        self.assertEqual("/Game/Input/IA_Test", _asset_path("/Game/Input/IA_Test.IA_Test"))

    def test_asset_path_rejects_non_project_path(self):
        with self.assertRaises(ValueError):
            _asset_path("IA_Test")

    def test_input_operations_are_real_first_party_callables(self):
        create = UNREAL_OPERATIONS["input.create_action"]
        mapping = UNREAL_OPERATIONS["input.add_mapping"]

        self.assertTrue(create.function.endswith("unreal_enhanced_input.create_input_action"))
        self.assertTrue(mapping.function.endswith("unreal_enhanced_input.add_mapping"))
        self.assertTrue(create.mutates_project)
        self.assertTrue(mapping.mutates_project)

    def test_stamina_feature_operations_are_registered_real_callables(self):
        for key in (
            "gameplay.create_stamina_component",
            "gameplay.integrate_stamina_character",
            "gameplay.validate_stamina_feature",
        ):
            operation = UNREAL_OPERATIONS[key]
            self.assertIn("unreal_stamina_sprint_feature", operation.function)

    def test_mapping_payload_requires_explicit_assets_and_key(self):
        payload = unreal_operation_payload(
            "input.add_mapping",
            {
                "mapping_context_path": "/Game/Input/IMC_Default",
                "action_path": "/Game/Input/IA_Sprint",
                "key_name": "LeftShift",
                "dry_run": True,
            },
        )

        self.assertEqual("LeftShift", payload["kwargs"]["key_name"])
        self.assertTrue(payload["kwargs"]["dry_run"])

    def test_runtime_log_operation_is_registered_read_only(self):
        operation = UNREAL_OPERATIONS["diagnostics.read_log_errors"]

        self.assertIn("unreal_diagnostics.read_recent_log_errors", operation.function)
        self.assertFalse(operation.mutates_project)

    def test_runtime_log_summary_deduplicates_repeated_errors(self):
        rows = _error_summary(
            [
                "[2026.07.16][1] Blueprint Runtime Error: Accessed None",
                "[2026.07.16][2] Blueprint Runtime Error: Accessed None",
                "LogTemp: Warning: One warning",
            ]
        )

        self.assertEqual(2, len(rows))
        self.assertEqual(2, rows[0]["count"])


if __name__ == "__main__":
    unittest.main()
