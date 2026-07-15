from __future__ import annotations

import unittest

from services.goal_gap_planning_service import (
    build_goal_gap_plan,
    goal_gap_planning_context,
    render_goal_gap_plan,
)
from services.prompt_progress_service import build_prompt_progress_plan
from services.prompt_route_service import classify_prompt_route


class TestGoalGapPlanningService(unittest.TestCase):
    def test_motion_matching_prompt_creates_missing_gap_nodes(self) -> None:
        plan = build_goal_gap_plan(
            "In Unreal add Motion Matching to our climbing system",
            {"host": "unreal", "route": "dcc_prototype", "context_resolvers": ["capability_graph"]},
        )

        self.assertEqual(plan["framework"], "goal_gap_planning_v1")
        self.assertIn("unreal.motion_matching", plan["matched_patterns"])
        node_keys = {node["key"] for node in plan["capability_nodes"]}
        self.assertIn("pose_search_or_plugin", node_keys)
        self.assertIn("animation_database", node_keys)
        self.assertIn("runtime_integration", node_keys)
        self.assertGreaterEqual(len(plan["missing_links"]), 3)
        self.assertEqual(plan["resolution_options"][0]["key"], "official_pose_search")
        self.assertEqual(plan["progress_mode"], "detailed")
        self.assertTrue(plan["planned_actions"])
        self.assertTrue(plan["test_plan"])
        self.assertIn("Edits made or operations performed", plan["report_outline"])
        self.assertIn("Validation and user test steps", plan["report_outline"])
        self.assertTrue(plan["learning_recommendations"])

    def test_generic_prompt_still_builds_a_to_z_gap_contract(self) -> None:
        plan = build_goal_gap_plan(
            "Make the app figure out how to connect A to Z even if C is missing",
            {"route": "planning", "provider": "local"},
        )

        keys = [node["key"] for node in plan["capability_nodes"]]
        self.assertIn("gap_discovery", keys)
        self.assertIn("option_ranking", keys)
        self.assertIn("learning_capture", keys)
        rendered = render_goal_gap_plan(plan)
        self.assertIn("Goal gap plan:", rendered)
        self.assertIn("Learning loop:", rendered)
        context = goal_gap_planning_context("Make the app connect A to Z")
        self.assertIn("GOAL GAP PLANNING:", context)
        self.assertIn("Missing or unverified links:", context)

    def test_route_and_visible_progress_include_gap_planning(self) -> None:
        decision = classify_prompt_route("In Unreal add a reusable character stamina system and connect it to sprinting")
        data = decision.to_dict()

        self.assertEqual(data["capability_gap_plan"]["framework"], "goal_gap_planning_v1")
        self.assertIn("unreal.character_stamina", data["capability_gap_plan"]["matched_patterns"])
        progress = build_prompt_progress_plan("stamina", data)
        states = [stage["state"] for stage in progress["stages"]]
        self.assertIn("GAP_DISCOVERY", states)
        self.assertIn("gap_policy", progress)

    def test_quick_direct_actions_stay_terse(self) -> None:
        plan = build_goal_gap_plan(
            "Open the selected Maya file",
            {"route": "dcc_execute", "host": "maya", "risk_level": "low", "compound_kind": "atomic"},
        )

        self.assertEqual(plan["progress_mode"], "terse")
        self.assertEqual([], plan["planned_actions"])
        self.assertEqual([], plan["test_plan"])
        self.assertEqual(["Completed action", "Result or blocker"], plan["report_outline"])

    def test_each_capability_has_resolution_strategies(self) -> None:
        plan = build_goal_gap_plan(
            "In Unreal add Motion Matching to our climbing system",
            {
                "host": "unreal",
                "route": "dcc_prototype",
                "allow_external_research": True,
                "allow_ingestion": True,
            },
        )

        resolver_plan = plan["capability_resolution_plan"]
        self.assertTrue(resolver_plan)
        pose_search = next(item for item in resolver_plan if item["capability"] == "pose_search_or_plugin")
        strategy_keys = {strategy["key"] for strategy in pose_search["strategies"]}
        self.assertIn("official_documentation", strategy_keys)
        self.assertIn("github_ingest", strategy_keys)
        github_strategy = next(strategy for strategy in pose_search["strategies"] if strategy["key"] == "github_ingest")
        self.assertTrue(github_strategy["requires_approval"])
        self.assertTrue(github_strategy["requires_license_check"])
        self.assertTrue(github_strategy["pause_before_execution"])
        official_strategy = next(strategy for strategy in pose_search["strategies"] if strategy["key"] == "official_documentation")
        self.assertFalse(official_strategy["pause_before_execution"])
        sequence_actions = {item["action"] for item in plan["adaptive_sequence"]}
        self.assertIn("discover_then_continue", sequence_actions)
        self.assertTrue(plan["approval_gates"])
        self.assertTrue(any(gate["strategy"] == "github_ingest" for gate in plan["approval_gates"]))
        self.assertTrue(plan["source_report_requirements"])
        self.assertTrue(any(item["strategy"] == "official_documentation" for item in plan["source_report_requirements"]))

    def test_known_capability_prefers_internal_resolution(self) -> None:
        plan = build_goal_gap_plan(
            "Use the stamina system",
            {
                "route": "dcc_prototype",
                "context_resolvers": ["existing_movement_system"],
                "deterministic_steps": ["stamina_contract"],
            },
        )

        known_items = [
            item for item in plan["capability_resolution_plan"]
            if item["status"] == "known"
        ]
        self.assertTrue(known_items)
        self.assertIn(
            known_items[0]["chosen_strategy"],
            {"internal_function", "internal_workflow", "compose_internal_functions"},
        )

    def test_cross_app_animation_workflow_has_mixed_action_types(self) -> None:
        plan = build_goal_gap_plan(
            "In Blender run an internal setup, then run a Python helper, find an animation online, import it into Unreal, and run another tool",
            {
                "host": "blender",
                "route": "dcc_prototype",
                "allow_external_research": True,
                "allow_ingestion": True,
            },
        )

        self.assertIn("cross_app.animation_transfer", plan["matched_patterns"])
        action_types = {item["action_type"] for item in plan["mixed_operation_sequence"]}
        self.assertIn("run_dcc_operation", action_types)
        self.assertIn("run_python_function", action_types)
        self.assertIn("download_or_ingest_asset", action_types)
        self.assertIn("import_unreal_asset", action_types)
        self.assertIn("validate_result", action_types)
        catalog_keys = {item["key"] for item in plan["operation_action_catalog"]}
        self.assertIn("download_or_ingest_asset", catalog_keys)
        self.assertTrue(any(item["requires_approval"] for item in plan["mixed_operation_sequence"]))
        self.assertTrue(any(item["report_sources"] for item in plan["mixed_operation_sequence"]))

    def test_mixed_operations_use_existing_action_graph_with_contracts(self) -> None:
        plan = build_goal_gap_plan(
            "In Blender inspect a character, find an online animation, import it into Unreal, retarget it, and validate",
            {
                "host": "blender",
                "route": "dcc_prototype",
                "allow_external_research": True,
                "allow_ingestion": True,
            },
        )

        self.assertIn("operation_contracts", plan)
        self.assertIn("mixed_operation_graph", plan)
        self.assertIn("canonical_action_graph", plan)
        self.assertEqual(
            plan["mixed_operation_graph"]["base_graph"],
            "services.action_graph_service.ActionGraph",
        )
        self.assertEqual(plan["canonical_action_graph"]["intent"], "mixed_operation")
        self.assertTrue(plan["canonical_action_graph"]["validation"]["valid"])
        first_contract = plan["operation_contracts"][0]
        self.assertIn("inputs", first_contract)
        self.assertIn("outputs", first_contract)
        self.assertIn("execution_context", first_contract)
        self.assertIn("rollback_policy", first_contract)
        self.assertIn("provenance", first_contract)
        graph_action = plan["canonical_action_graph"]["actions"][0]
        self.assertIn("operation_contract", graph_action["args"])
        artifact_keys = {item["key"] for item in plan["artifact_type_catalog"]}
        self.assertIn("animation_clip", artifact_keys)
        self.assertIn("license_record", artifact_keys)

    def test_mixed_operation_can_materialize_into_pipeline_callables(self) -> None:
        plan = build_goal_gap_plan(
            "In Blender inspect a character, find an online animation, import it into Unreal, retarget it, and validate",
            {
                "host": "blender",
                "route": "dcc_prototype",
                "allow_external_research": True,
                "allow_ingestion": True,
            },
        )

        materializer = plan["pipeline_materialization_plan"]
        self.assertEqual(materializer["framework"], "mixed_operation_materializer_v1")
        self.assertTrue(materializer["convertible"])
        self.assertEqual(materializer["base_graph"], "services.action_graph_service.ActionGraph")
        self.assertEqual(materializer["generated_function_root"], "tool_output/generated_functions")
        self.assertEqual(materializer["third_party_wrapper_root"], "third_party/wrappers")
        self.assertEqual(materializer["default_promotion_scope"], "pipeline_local")
        self.assertIn("pipeline_local", materializer["promotion_scopes"])
        self.assertTrue(materializer["generated_callable_candidates"])

        candidate_paths = {
            item["implementation"]["path"]
            for item in materializer["generated_callable_candidates"]
            if item["implementation"]["path"]
        }
        self.assertTrue(any(path.startswith("tool_output/generated_") for path in candidate_paths))
        self.assertTrue(any(path.startswith("third_party/wrappers/") for path in candidate_paths))
        self.assertTrue(all(item["status"] == "planned_not_written" for item in materializer["generated_callable_candidates"]))
        self.assertTrue(all(item["trust_state"] == "untrusted_until_validated" for item in materializer["generated_callable_candidates"]))

        node_kinds = {item["node_kind"] for item in materializer["pipeline_node_candidates"]}
        self.assertIn("executable_operation", node_kinds)
        self.assertIn("control_flow", node_kinds)
        canonical = plan["canonical_action_graph"]
        self.assertIn("pipeline_materialization_plan", canonical)
        self.assertTrue(any(action.get("pipeline_materialization") for action in canonical["actions"]))

        compact = classify_prompt_route(
            "In Blender inspect a character, find an online animation, import it into Unreal, retarget it, and validate"
        ).to_dict()["capability_gap_plan"]
        self.assertIn("pipeline_materialization_plan", compact)
        self.assertTrue(compact["pipeline_materialization_plan"]["convertible"])
        rendered = render_goal_gap_plan(plan)
        self.assertIn("Pipeline materialization:", rendered)

    def test_adaptive_plan_respects_no_external_ingestion_policy(self) -> None:
        plan = build_goal_gap_plan(
            "In Blender inspect a character, find an online animation, import it into Unreal, retarget it, and validate",
            {
                "host": "blender",
                "route": "dcc_prototype",
                "allow_external_research": False,
                "allow_ingestion": False,
            },
        )

        action_types = {item["action_type"] for item in plan["mixed_operation_sequence"]}
        self.assertNotIn("github_candidate_review", action_types)
        self.assertNotIn("download_or_ingest_asset", action_types)
        self.assertFalse(plan["approval_gates"])
        for contract in plan["operation_contracts"]:
            self.assertNotIn("network", contract["permissions"])

    def test_adaptive_plan_allows_research_without_ingestion(self) -> None:
        plan = build_goal_gap_plan(
            "In Unreal research motion matching for climbing before recommending edits",
            {
                "host": "unreal",
                "route": "planning",
                "allow_external_research": True,
                "allow_ingestion": False,
            },
        )

        action_types = {item["action_type"] for item in plan["mixed_operation_sequence"]}
        self.assertIn("web_knowledge_search", action_types)
        self.assertNotIn("github_candidate_review", action_types)
        self.assertNotIn("download_or_ingest_asset", action_types)
        self.assertTrue(plan["source_report_requirements"])
        self.assertFalse(plan["approval_gates"])

    def test_known_external_sounding_capability_does_not_acquire_again(self) -> None:
        plan = build_goal_gap_plan(
            "Use our existing online animation source to import animation into Unreal",
            {
                "host": "unreal",
                "route": "dcc_prototype",
                "allow_external_research": True,
                "allow_ingestion": True,
                "context_resolvers": ["online animation source candidate", "animation asset ingest"],
                "deterministic_steps": ["unreal animation import"],
            },
        )

        known = {item["capability"] for item in plan["capability_resolution_plan"] if item["status"] == "known"}
        self.assertIn("online_animation_source", known)
        known_actions = [
            item["action_type"]
            for item in plan["mixed_operation_sequence"]
            if item["capability"] == "online_animation_source"
        ]
        self.assertEqual(known_actions[0], "execute_internal_function")
        self.assertNotIn("download_or_ingest_asset", known_actions)
        self.assertNotIn("github_candidate_review", known_actions)
        for item in plan["mixed_operation_sequence"]:
            if item["capability"] == "online_animation_source":
                self.assertFalse(item["requires_network"])


if __name__ == "__main__":
    unittest.main()
