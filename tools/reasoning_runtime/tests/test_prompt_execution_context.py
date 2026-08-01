from __future__ import annotations

import unittest

from reasoning_runtime import PromptExecutionContext


class PromptExecutionContextTests(unittest.TestCase):
    def test_serializes_compatibility_views(self):
        context = PromptExecutionContext(
            prompt="make a thing",
            task_graph={"primary_goal": "Build it", "goals": [{"goal_id": "a"}]},
        )

        data = context.to_dict()

        self.assertEqual(data["primary_goal"], "Build it")
        self.assertEqual(data["estimated_steps"], 1)
        self.assertEqual(data["semantic_contract"], {})

    def test_current_goal_respects_dependencies(self):
        context = PromptExecutionContext(
            prompt="x",
            task_graph={
                "goals": [
                    {"goal_id": "a", "objective": "first"},
                    {"goal_id": "b", "objective": "second", "depends_on": ["a"]},
                ]
            },
        )

        self.assertEqual(context.current_goal()["goal_id"], "a")
        self.assertEqual(context.current_goal(["a"])["goal_id"], "b")


if __name__ == "__main__":
    unittest.main()
