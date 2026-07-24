import unittest

from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


class TestPromptUnderstandingMatrix(unittest.TestCase):
    def test_whole_system_routes_labeled_prompt_matrix(self):
        cases = [
            ("In Maya create a locator named STRESS_LOC", {"dcc_execute"}),
            ("In Maya run script: import maya.cmds as cmds; cmds.polyCube(name='StressCube')", {"dcc_execute"}),
            ("In Maya create a locator named STRESS_MULTI then move STRESS_MULTI to Y 4", {"action_graph"}),
            ("In Maya what is the first bone name you can find?", {"dcc_query", "dcc_execute"}),
            ("In Maya show me how you would create a locator, do not execute it", {"chat"}),
            ("In Unreal run python: print('stress unreal')", {"dcc_execute"}),
            ("In Unreal open BP_LesterPhoenix and focus the Event Graph", {"unreal_capability", "dcc_execute"}),
            ("In Unreal take a project snapshot and report selected actors", {"dcc_query", "unreal_capability"}),
            ("Blender create cube named StressCube", {"dcc_execute"}),
            ("Houdini create a SOP node and connect it", {"dcc_execute"}),
            ("In Substance Painter export textures for the selected asset", {"dcc_execute"}),
            ("Unity create an empty GameObject named StressRoot", {"dcc_execute"}),
            ("Update helper logic in create_rig.py", {"target_discovery"}),
            ("Fix the error handling in tech_connector/services/action_execution_engine.py", {"target_discovery"}),
            ("Which functions call classify_prompt_route?", {"project_search"}),
            ("Which files are not being imported under tech_connector/services?", {"import_coverage", "project_health"}),
            ("Create a workflow that exports Maya selection then imports it into Unreal", {"pipeline_graph", "action_graph"}),
            ("Good morning, what do you think about using an FNN here?", {"chat"}),
            ("It failed, try to fix it and validate the result", {"target_discovery"}),
            ("Check Maya and Unreal status, then report what is connected", {"connection_status"}),
            ("Call create_rig_from_mapping in Maya with the current selection", {"dcc_execute"}),
            ("Explain what prompt_route_service.py does", {"project_search"}),
            ("Where should I add a new Unreal graph rollback validator?", {"project_search"}),
            (
                "In Maya run this:\n```python\nimport maya.cmds as cmds\ncmds.spaceLocator(name='BlockLoc')\n```",
                {"dcc_execute"},
            ),
        ]

        for prompt, expected_routes in cases:
            with self.subTest(prompt=prompt):
                decision = classify_prompt_route(prompt)
                self.assertIn(decision.route, expected_routes)


if __name__ == "__main__":
    unittest.main()
