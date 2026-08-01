from __future__ import annotations

import unittest

from reasoning_runtime import ComposedRequest, GoalClause, PromptClause, PromptClausePlan


class PromptTaskContractTests(unittest.TestCase):
    def test_prompt_clause_plan_serializes_tuple_fields(self):
        clause = PromptClause(
            "c1",
            "Do the thing",
            "do the thing",
            "execute",
            depends_on=("c0",),
            constraints=("safe",),
        )
        plan = PromptClausePlan("Do the thing", "do the thing", (clause,), 0.8, False, False, False)

        data = plan.to_dict()

        self.assertEqual(data["clauses"][0]["depends_on"], ["c0"])
        self.assertEqual(data["clauses"][0]["constraints"], ["safe"])

    def test_composed_request_serializes_goals(self):
        request = ComposedRequest("x", "x", "do x", (GoalClause("g1", "c1", "execute"),), ())

        self.assertEqual(request.to_dict()["goals"][0]["goal_id"], "g1")


if __name__ == "__main__":
    unittest.main()
