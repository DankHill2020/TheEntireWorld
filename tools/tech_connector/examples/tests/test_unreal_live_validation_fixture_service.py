from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.services.unreal.anim_blueprint_capability_service import (
    build_anim_blueprint_capability_plan,
)
from tech_connector.services.unreal.live_validation_fixture_service import (
    build_anim_blueprint_disposable_fixture,
    build_niagara_source_strategy_disposable_fixture,
    build_physics_asset_disposable_fixture,
    build_pose_search_disposable_fixture,
)


class TestUnrealLiveValidationFixtureService(unittest.TestCase):
    def test_niagara_fixture_requires_real_stack_and_parameter_readback(self) -> None:
        fixture = build_niagara_source_strategy_disposable_fixture(
            source_system="/Game/FX/NS_Source",
            source_strategy="camera_facing_character_outline",
            parameters={"FX_EdgeThickness": 5.0},
        )

        self.assertEqual(fixture["id"], "niagara_disposable_source_strategy_fixture")
        self.assertIn("niagara.synthesize_source_strategy_stack", fixture["operations_under_test"])
        self.assertIn("stack_readback", fixture["python_script"])
        self.assertIn("parameters_reported", fixture["python_script"])
        self.assertIn("camera_facing_character_outline", fixture["python_script"])

    def test_anim_blueprint_fixture_contains_disposable_mutation_script(self) -> None:
        fixture = build_anim_blueprint_disposable_fixture(
            target_abp="/Game/Characters/ABP_Combat",
            state_machine_name="Locomotion",
            transitions=["Crouch -> Crawl when bWantsToCrawl && CrawlInputVector.X > 0.1"],
        )

        self.assertEqual("anim_blueprint_disposable_transition_rule_fixture", fixture["id"])
        self.assertEqual("/Game/Characters/ABP_Combat", fixture["target_asset"])
        self.assertIn("rollback.record_asset_snapshot", fixture["operations_under_test"])
        self.assertIn("anim_graph.synthesize_transition_rule_expression", fixture["operations_under_test"])
        self.assertIn("duplicate_asset", fixture["python_script"])
        self.assertIn("synthesize_anim_graph_transition_rule_expression", fixture["python_script"])
        self.assertIn("CrawlInputVector.X > 0.1", fixture["python_script"])

    def test_abp_capability_plan_embeds_live_fixture(self) -> None:
        plan = build_anim_blueprint_capability_plan(
            "In ABP Combat add crawling transitions when bWantsToCrawl && CrawlInputVector.X > 0.1"
        )

        fixtures = plan["live_validation_fixtures"]
        self.assertEqual(1, len(fixtures))
        self.assertIn("blueprint.compile_and_save", fixtures[0]["operations_under_test"])
        self.assertIn("disposable AnimBlueprint duplicate", " ".join(plan["validation"]))

    def test_pose_search_fixture_requires_channel_and_animation_readback(self) -> None:
        fixture = build_pose_search_disposable_fixture(
            skeleton_path="/Game/Characters/SK_Mannequin",
            animation_path="/Game/Characters/Animations/Idle",
        )

        self.assertEqual("pose_search_disposable_database_fixture", fixture["id"])
        self.assertIn("add_pose_search_schema_channel", fixture["python_script"])
        self.assertIn("animation_count", fixture["python_script"])
        self.assertEqual(2, len(fixture["related_disposable_assets"]))

    def test_physics_fixture_uses_noninteractive_native_creation(self) -> None:
        fixture = build_physics_asset_disposable_fixture(
            skeletal_mesh_path="/Game/Characters/SKM_Manny",
            test_bone="pelvis",
        )

        self.assertEqual("physics_asset_disposable_body_profile_fixture", fixture["id"])
        self.assertIn("AIStudioBridgeLibrary.create_physics_asset", fixture["python_script"])
        self.assertNotIn("PhysicsAssetFactory", fixture["python_script"])
        self.assertIn("list_physics_profiles", fixture["python_script"])

    def test_rollback_latest_reads_jsonl_journal(self) -> None:
        from unreal_tools import rollback

        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "rollback_journal.jsonl"
            journal.write_text(
                json.dumps({"token": "rollback:test", "kind": "asset_snapshot"}) + "\n",
                encoding="utf-8",
            )
            with patch.object(rollback, "_journal_path", return_value=journal):
                latest = json.loads(rollback.latest())

        self.assertTrue(latest["ok"])
        self.assertEqual("rollback:test", latest["entry"]["token"])


if __name__ == "__main__":
    unittest.main()
