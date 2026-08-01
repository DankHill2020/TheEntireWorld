from __future__ import annotations

import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.router.command_router import CommandRouter
from tech_connector.services.dcc.dcc_operation_service import (
    dcc_operation_registry,
    dcc_prompt_to_operation,
)
from tech_connector.services.unreal.expert_technique_registry import (
    load_expert_techniques,
    select_expert_techniques,
)
from tech_connector.services.unreal.expert_qualification_service import audit_expert_techniques
from tech_connector.services.unreal.external_animation_target_policy import (
    decide_external_animation_target,
)
from tech_connector.services.unreal.feature_planning_service import (
    authorize_feature_plan,
    execute_approved_unreal_feature_plan,
    seal_feature_plan,
)
from tech_connector.services.unreal.technique_episode_store import (
    match_technique_episodes,
    record_technique_episode,
)
from tech_connector.services.unreal.orchestration import execute_generic_plan


class TestUnrealPromptFeatureGeneration(unittest.TestCase):
    def test_external_animation_blocks_when_no_target_is_resolved(self):
        decision = decide_external_animation_target({})
        self.assertEqual("", decision["target_skeleton"])
        self.assertEqual("resolve_target_skeleton", decision["action"])
        self.assertFalse(decision["mutation_allowed"])
        self.assertFalse(decision["retargeting_required"])
        self.assertFalse(decision["direct_import_allowed"])

    def test_direct_manny_import_requires_hierarchy_proportion_and_pose_evidence(self):
        evidence = {
            "source_hierarchy_fingerprint": "manny-v1",
            "target_hierarchy_fingerprint": "manny-v1",
            "source_bones": ["root", "pelvis", "spine_01", "thigh_l", "thigh_r"],
            "required_target_bones": ["root", "pelvis", "spine_01", "thigh_l", "thigh_r"],
            "proportion_metrics": {
                "height": {"source": 1.805, "target": 1.8, "tolerance_ratio": 0.05},
                "arm_span": {"source": 1.82, "target": 1.8, "tolerance_ratio": 0.05},
            },
            "reference_pose_max_error_degrees": 2.0,
        }
        target = {
            "mesh_path": "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple",
            "skeleton_path": "/Game/Characters/Mannequins/Meshes/SK_Mannequin",
        }
        self.assertTrue(
            decide_external_animation_target(evidence, project_target=target)["direct_import_allowed"]
        )
        evidence["proportion_metrics"]["height"]["source"] = 2.4
        self.assertTrue(
            decide_external_animation_target(evidence, project_target=target)["retargeting_required"]
        )

    def test_claimed_compatibility_without_measurements_is_rejected(self):
        decision = decide_external_animation_target(
            {
                "hierarchy_fingerprint_match": True,
                "required_bones_match": True,
                "proportions_match": True,
                "reference_pose_match": True,
            },
            project_target={"skeleton_path": "/Game/Project/SK_Target"},
        )
        self.assertTrue(decision["retargeting_required"])

    def test_user_selected_animation_target_overrides_default_manny(self):
        decision = decide_external_animation_target(
            {}, selected_target_mesh="/Game/Hero/SKM_Hero", selected_target_skeleton="/Game/Hero/SK_Hero"
        )
        self.assertEqual("user_selected", decision["target_source"])
        self.assertEqual("/Game/Hero/SK_Hero", decision["target_skeleton"])

    def test_maya_hik_retarget_is_a_registered_prompt_callable(self):
        operation = dcc_operation_registry("maya")["animation.hik_retarget"]
        self.assertEqual(
            "maya_tools.Rigging.mocap.hik_retarget.retarget_fbx_hik", operation.function
        )
        self.assertIn("source_mapping", operation.required)
        self.assertEqual(
            "animation.hik_retarget",
            dcc_prompt_to_operation("maya", "Retarget this FBX with HumanIK"),
        )

    def test_technique_registry_is_data_driven_and_source_backed(self):
        registry = load_expert_techniques()
        self.assertEqual("ai_studio.unreal_expert_techniques.v1", registry["schema"])
        self.assertTrue(registry["techniques"])
        self.assertTrue(
            any(source.get("url", "").startswith("https://dev.epicgames.com/")
                for technique in registry["techniques"] for source in technique.get("sources") or [])
        )

    def test_general_animation_prompt_selects_foundational_experts(self):
        selection = select_expert_techniques(
            "Build and verify a context-aware character animation feature in PIE",
            required_domains=["asset_catalog", "blueprint_topology", "animation_metadata", "runtime_world"],
        )
        keys = {row["key"] for row in selection["techniques"]}
        self.assertIn("project.semantic_inspection", keys)
        self.assertIn("blueprint.transactional_graph_edit", keys)
        self.assertIn("animation.contextual_asset_acceptance", keys)
        self.assertIn("runtime.scenario_verification", keys)
        self.assertNotIn("animation.motion_matching", keys)
        self.assertNotIn("animation.ik_retarget", keys)

    def test_specialized_techniques_require_matching_request_evidence(self):
        selection = select_expert_techniques(
            "Build Motion Matching with Pose Search and retarget a downloaded FBX to the selected skeleton"
        )
        keys = {row["key"] for row in selection["techniques"]}
        self.assertIn("animation.motion_matching", keys)
        self.assertIn("animation.ik_retarget", keys)
        self.assertIn("external.https_asset_ingestion", keys)

    def test_online_tutorial_request_selects_research_expert(self):
        selection = select_expert_techniques("Search online tutorials and compare guides before building it")
        self.assertIn(
            "knowledge.source_comparison",
            {row["key"] for row in selection["techniques"]},
        )

    def test_experts_remain_provisional_without_probes_and_verified_episodes(self):
        selection = select_expert_techniques("Build a context-aware animation feature")
        with TemporaryDirectory() as root:
            audit = audit_expert_techniques(
                selection,
                project_context={"engine_version": "5.8"},
                episode_path=f"{root}/episodes.jsonl",
            )
        self.assertFalse(audit["all_experts_verified"])
        self.assertTrue(all(row["status"] == "provisional" for row in audit["experts"]))
        self.assertTrue(any(row["missing_qualifications"] for row in audit["experts"]))

    def test_only_fully_verified_episodes_are_reused(self):
        with TemporaryDirectory() as root:
            path = f"{root}/episodes.jsonl"
            common = {
                "request": "retarget contextual wall climb animation to Manny",
                "technique_keys": ["animation.ik_retarget"],
                "operations": [{"operation": "retarget.execute", "ok": True}],
                "project_context": {"engine_version": "5.8", "target_skeleton": "/Game/Manny"},
                "scope": "atomic_technique",
                "required_gates": [
                    "capabilities_resolved",
                    "assets_validated",
                    "blueprints_compiled",
                    "graph_postconditions_passed",
                    "runtime_scenarios_passed",
                    "new_log_errors_absent",
                ],
                "path": path,
            }
            record_technique_episode(verification={"runtime_scenarios_passed": True}, **common)
            record_technique_episode(
                verification={
                    "capabilities_resolved": True,
                    "assets_validated": True,
                    "blueprints_compiled": True,
                    "graph_postconditions_passed": True,
                    "runtime_scenarios_passed": True,
                    "new_log_errors_absent": True,
                },
                **common,
            )
            matches = match_technique_episodes(
                "wall climb animation retarget",
                technique_keys=["animation.ik_retarget"],
                project_context={"engine_version": "5.8", "target_skeleton": "/Game/Manny"},
                path=path,
            )
        self.assertEqual(1, len(matches))
        self.assertTrue(matches[0]["reusable"])

    def test_failed_episode_can_be_inspected_without_becoming_guidance(self):
        with TemporaryDirectory() as root:
            path = f"{root}/episodes.jsonl"
            record_technique_episode(
                request="climb prototype",
                technique_keys=["animation.contextual_asset_acceptance"],
                operations=[{"operation": "animation.preview", "ok": False}],
                repairs=[{"cause": "clip was an attack", "decision": "reject semantic role"}],
                verification={},
                path=path,
            )
            self.assertFalse(match_technique_episodes("climb", path=path))
            history = match_technique_episodes("climb", path=path, include_failed=True)
        self.assertEqual(1, len(history))
        self.assertFalse(history[0]["reusable"])

    def test_atomic_action_uses_its_declared_gate_profile(self):
        with TemporaryDirectory() as root:
            path = f"{root}/episodes.jsonl"
            episode = record_technique_episode(
                request="import animation onto selected skeleton",
                technique_keys=["asset.fbx_import_mode_selection"],
                operations=[{"operation": "animation.import_fbx", "ok": True}],
                scope="atomic_action",
                required_gates=["capabilities_resolved", "assets_validated", "new_log_errors_absent"],
                verification={
                    "capabilities_resolved": True,
                    "assets_validated": True,
                    "new_log_errors_absent": True,
                },
                path=path,
            )
        self.assertTrue(episode["reusable"])
        self.assertEqual("atomic_action", episode["scope"])

    def test_episode_cannot_qualify_a_different_technique(self):
        with TemporaryDirectory() as root:
            path = f"{root}/episodes.jsonl"
            record_technique_episode(
                request="import climbing animation",
                technique_keys=["asset.fbx_import_mode_selection"],
                operations=[{"operation": "animation.import_fbx", "ok": True}],
                scope="atomic_action",
                required_gates=["assets_validated"],
                verification={"assets_validated": True},
                path=path,
            )
            unrelated = match_technique_episodes(
                "import climbing animation",
                technique_keys=["animation.ik_retarget"],
                path=path,
            )
        self.assertFalse(unrelated)

    def test_orchestration_dry_run_never_claims_validation(self):
        result = execute_generic_plan({"feature": "generated_from_evidence"}, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["validated"])

    def test_approved_executor_requires_concrete_operation_calls(self):
        result = execute_approved_unreal_feature_plan(
            {"framework": "unreal_generic_feature_plan_v2", "feature": "generated_from_evidence"}
        )
        self.assertEqual("blocked", result["status"])

    def test_approved_executor_runs_registered_calls_and_verification(self):
        plan = {
            "framework": "unreal_generic_feature_plan_v2",
            "feature": "generated_from_evidence",
            "operation_calls": [
                {
                    "operation": "assets.inspect",
                    "params": {"asset_path": "/Game/Test"},
                    "postconditions": ["target exists"],
                },
                {
                    "operation": "runtime.pie_validate",
                    "params": {"target_assets": ["/Game/Test"]},
                    "postconditions": ["scenario passed"],
                },
            ],
            "required_verification_operations": ["runtime.pie_validate"],
        }
        plan = authorize_feature_plan(seal_feature_plan(plan))
        with patch.object(
            CommandRouter,
            "execute_unreal_operation",
            side_effect=[("Inspect", True, json.dumps({"ok": True})), ("PIE", True, json.dumps({"ok": True}))],
        ):
            result = execute_approved_unreal_feature_plan(plan)
        self.assertEqual("completed", result["status"])
        self.assertEqual(["runtime.pie_validate"], result["passed_verification_operations"])

    def test_approved_executor_rejects_unverified_operation(self):
        plan = {
            "framework": "unreal_generic_feature_plan_v2",
            "feature": "generated_from_evidence",
            "operation_calls": [{"operation": "assets.inspect", "params": {}, "postconditions": []}],
            "required_verification_operations": ["runtime.pie_validate"],
        }
        plan = authorize_feature_plan(seal_feature_plan(plan))
        result = execute_approved_unreal_feature_plan(plan)
        self.assertEqual("failed", result["status"])
        self.assertTrue(any("postconditions" in error for error in result["errors"]))

    def test_command_router_generic_dry_run_is_non_mutating(self):
        label, ok, raw = CommandRouter().execute_unreal_operation(
            "feature.execute_generic_plan",
            {"plan": {"feature": "generated_from_evidence"}, "dry_run": True},
        )
        self.assertEqual("Unreal Execute Generic Feature Plan", label)
        self.assertTrue(ok)
        payload = json.loads(raw)
        self.assertFalse(payload["validated"])

    def test_authorized_plan_rejects_changes_after_approval(self):
        plan = {
            "framework": "unreal_generic_feature_plan_v2",
            "feature": "generated_from_evidence",
            "operation_calls": [
                {
                    "operation": "assets.inspect",
                    "params": {"asset_path": "/Game/Test"},
                    "postconditions": ["target exists"],
                }
            ],
            "required_verification_operations": ["assets.inspect"],
        }
        authorized = authorize_feature_plan(seal_feature_plan(plan))
        authorized["operation_calls"][0]["params"]["asset_path"] = "/Game/Changed"
        result = execute_approved_unreal_feature_plan(authorized)
        self.assertEqual("blocked", result["status"])
        self.assertTrue(any("changed after" in error for error in result["errors"]))

    def test_router_treats_structured_operation_failure_as_failure(self):
        with patch.object(UnrealBridge, "call", return_value=(True, json.dumps({"ok": False, "errors": ["pie_active"]}))):
            _label, ok, _raw = CommandRouter().execute_unreal_operation(
                "runtime.pie_validate",
                {"target_assets": ["/Game/Test"]},
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
