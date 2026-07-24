import unittest

from tech_connector.services.prompt.prompt_route_service import classify_prompt_route
from tech_connector.services.reasoning.request_understanding_fnn_service import score_prompt_routes


class TestRequestUnderstandingFnnService(unittest.TestCase):
    def test_scores_dcc_execution_for_registered_host_operation(self):
        result = score_prompt_routes(
            "In Maya create a locator named FNN_LOC",
            host="maya",
            hosts=["maya"],
            registered_dcc_hint=True,
        )

        self.assertEqual("dcc_execute", result.top_route)
        self.assertGreater(result.confidence, 0.35)
        self.assertGreater(result.features["host_mentioned"], 0)
        self.assertGreater(result.features["registered_dcc_hint"], 0)

    def test_scores_action_graph_for_multistep_host_process(self):
        result = score_prompt_routes(
            "In Maya create a locator named FNN_MULTI then move it up 4 units",
            host="maya",
            hosts=["maya"],
            registered_dcc_hint=True,
        )

        routes = {item.route: item.score for item in result.scores}
        self.assertGreater(routes["action_graph"], routes["project_search"])
        self.assertGreater(result.features["multi_step"], 0)

    def test_supported_dccs_get_equal_confidence_for_equivalent_prompts(self):
        maya_result = score_prompt_routes(
            "In Maya create a locator named FNN_LOC",
            host="maya",
            hosts=["maya"],
            registered_dcc_hint=True,
        )
        blender_result = score_prompt_routes(
            "Blender create cube named FNN_CUBE",
            host="blender",
            hosts=["blender"],
            registered_dcc_hint=True,
        )
        houdini_result = score_prompt_routes(
            "Houdini create node named FNN_NODE",
            host="houdini",
            hosts=["houdini"],
            registered_dcc_hint=False,
        )
        unity_result = score_prompt_routes(
            "Unity create empty named FNN_ROOT",
            host="unity",
            hosts=["unity"],
            registered_dcc_hint=False,
        )
        substance_result = score_prompt_routes(
            "Substance Painter export textures named FNN_TEXTURES",
            host="substance_painter",
            hosts=["substance_painter"],
            registered_dcc_hint=False,
        )

        self.assertEqual("dcc_execute", blender_result.top_route)
        self.assertGreater(blender_result.features["host_mentioned"], 0)
        self.assertEqual(maya_result.confidence, blender_result.confidence)
        self.assertEqual(maya_result.confidence, houdini_result.confidence)
        self.assertEqual(maya_result.confidence, unity_result.confidence)
        self.assertEqual(maya_result.confidence, substance_result.confidence)

    def test_placement_questions_do_not_get_pulled_into_dcc_execution(self):
        result = score_prompt_routes(
            "Where should I add a new Unreal graph rollback validator?",
            host="unreal",
            hosts=["unreal"],
            registered_dcc_hint=False,
        )

        self.assertIn(result.top_route, {"project_search", "target_discovery"})
        self.assertGreater(result.features["placement_query"], 0)

    def test_no_execute_guard_suppresses_direct_dcc_execution(self):
        result = score_prompt_routes(
            "In Maya show me how you would create a locator, do not execute it",
            host="maya",
            hosts=["maya"],
            registered_dcc_hint=True,
        )

        self.assertNotEqual("dcc_execute", result.top_route)
        self.assertGreater(result.features["no_execute_guard"], 0)

    def test_prompt_route_attaches_fnn_metadata_without_overriding_source_edit(self):
        decision = classify_prompt_route("Update helper logic in create_rig.py")

        self.assertEqual("target_discovery", decision.route)
        self.assertTrue(decision.route_candidates)
        self.assertIn("fnn_route_scoring", decision.reasoning_pipeline)
        self.assertEqual("target_discovery", decision.reasoning_pipeline["fnn_route_scoring"]["top_route"])

    def test_prompt_route_uses_fnn_evidence_for_dcc_multistep(self):
        decision = classify_prompt_route(
            "In Maya create a locator named FNN_NL_MULTI then move FNN_NL_MULTI to Y 4"
        )

        self.assertEqual("action_graph", decision.route)
        self.assertEqual("sequence", decision.compound_kind)
        self.assertIn("fnn_route_scoring", decision.reasoning_pipeline)
        candidate = next(item for item in decision.route_candidates if item["route"] == "action_graph")
        self.assertIn("fnn_score", candidate)

    def test_prompt_matrix_keeps_expected_route_in_fnn_shortlist(self):
        cases = [
            ("In Maya create a locator named FNN_LOC", "maya", ["dcc_execute"]),
            ("In Maya run script: import maya.cmds as cmds; cmds.polyCube(name='FnnCube')", "maya", ["dcc_execute"]),
            ("In Maya create a locator named FNN_MULTI then move FNN_MULTI to Y 4", "maya", ["action_graph", "dcc_execute"]),
            ("In Unreal run python: print('fnn unreal')", "unreal", ["dcc_execute"]),
            ("In Unreal open BP_LesterPhoenix and focus the Event Graph", "unreal", ["action_graph", "dcc_execute"]),
            ("Blender create cube named FnnCube", "blender", ["dcc_execute"]),
            ("Houdini create a SOP node and connect it", "houdini", ["dcc_execute", "action_graph"]),
            ("Update helper logic in create_rig.py", "", ["target_discovery"]),
            ("Which functions call classify_prompt_route?", "", ["project_search"]),
            ("Good morning, what do you think about using an FNN here?", "", ["chat", "project_search"]),
            ("Where should I add a new Unreal graph rollback validator?", "unreal", ["project_search", "target_discovery"]),
        ]

        for prompt, host, expected_routes in cases:
            with self.subTest(prompt=prompt):
                result = score_prompt_routes(
                    prompt,
                    host=host,
                    hosts=[host] if host else [],
                    registered_dcc_hint=host in {"maya", "unreal", "blender", "houdini"},
                )
                top_routes = {item.route for item in result.scores[:3]}
                self.assertTrue(top_routes.intersection(expected_routes))


if __name__ == "__main__":
    unittest.main()
