from __future__ import annotations

import unittest

from tech_connector.services.prompt_intent_service import classify_prompt_intent
from tech_connector.services.prompt_route_service import classify_prompt_route


class TestPromptIntentService(unittest.TestCase):
    def test_host_state_query_beats_unreal_asset_navigation_keyword_collision(self) -> None:
        intent = classify_prompt_intent(
            "In Unreal, report selected actors and selected assets. Do not edit anything.",
            host="unreal",
        )
        decision = classify_prompt_route(
            "In Unreal, report selected actors and selected assets. Do not edit anything.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(intent.kind, "host_state_query")
        self.assertEqual(decision.route, "dcc_query")
        self.assertEqual(decision.target_identifier, "selection")
        self.assertIn("navigation.open_asset", decision.rejected_routes)

    def test_maya_selection_query_routes_to_cmds_ls_primitive(self) -> None:
        decision = classify_prompt_route(
            "In Maya, what is currently selected? Do not edit anything.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(decision.route, "dcc_query")
        self.assertEqual(decision.target_identifier, "scene.ls")
        self.assertTrue(decision.keyword_args["selection"])

    def test_read_only_symbol_search_beats_docstring_edit_rule(self) -> None:
        intent = classify_prompt_intent(
            "What Maya project functions create controls for a rig? Search symbols and docstrings, not filenames.",
            host="maya",
        )
        decision = classify_prompt_route(
            "What Maya project functions create controls for a rig? Search symbols and docstrings, not filenames.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(intent.kind, "project_symbol_search")
        self.assertEqual(decision.route, "project_search")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertIn("target_discovery", decision.rejected_routes)

    def test_read_only_unreal_focus_node_is_navigation_not_graph_mutation(self) -> None:
        intent = classify_prompt_intent(
            "In Unreal open BP_LesterPhoenix and focus the Event Graph node named BeginPlay. Do not edit anything.",
            host="unreal",
        )
        decision = classify_prompt_route(
            "In Unreal open BP_LesterPhoenix and focus the Event Graph node named BeginPlay. Do not edit anything.",
            project_roots=["C:/depot/tools"],
        )

        self.assertIn(intent.kind, {"asset_navigation", "graph_read_or_navigation"})
        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.target_identifier, "navigation.open_asset")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertIn("unreal_semantic_graph_modification", decision.rejected_routes)

    def test_maya_joint_list_beats_generic_scene_query(self) -> None:
        decision = classify_prompt_route(
            "In Maya, list the first 10 joints in the current scene. Do not edit anything.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(decision.route, "dcc_query")
        self.assertEqual(decision.target_identifier, "scene.list_joints")
        self.assertEqual(decision.mutation_scope, "read_only")

    def test_unreal_current_project_inspection_beats_navigation_keyword_noise(self) -> None:
        decision = classify_prompt_route(
            "In Unreal, inspect the current project for sprint or stamina systems. Do not edit anything yet.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.target_identifier, "project.snapshot")
        self.assertEqual(decision.operation_mode, "query")
        self.assertEqual(decision.mutation_scope, "read_only")
        self.assertIn("navigation.open_asset", decision.rejected_routes)

    def test_do_not_edit_does_not_preview_read_only_unreal_navigation(self) -> None:
        decision = classify_prompt_route(
            "In Unreal open BP_LesterPhoenix and focus it for review. Do not edit anything.",
            project_roots=["C:/depot/tools"],
        )

        self.assertEqual(decision.route, "unreal_capability")
        self.assertEqual(decision.target_identifier, "navigation.open_asset")
        self.assertEqual(decision.operation_mode, "navigate")
        self.assertTrue(decision.can_execute_directly)


if __name__ == "__main__":
    unittest.main()
