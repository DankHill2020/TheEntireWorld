from __future__ import annotations

import unittest

from tech_connector.services.prompt.prompt_progress_service import (
    build_prompt_progress_plan,
    first_progress_status,
    narrate_progress_message,
    render_prompt_progress_plan,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


class TestPromptProgressService(unittest.TestCase):
    def test_every_stage_has_early_exit_and_handoff(self) -> None:
        plan = build_prompt_progress_plan(
            "Audit this project and fix the missing validation",
            {
                "route": "target_discovery",
                "provider": "engine",
                "mutation_scope": "file_modification",
                "requires_confirmation": True,
            },
        )
        self.assertEqual(plan["framework"], "visible_reasoning_progress_v2")
        self.assertEqual(plan["stage_model"], "sequential_expert_handoffs_with_early_exit")
        self.assertIn("stops as soon as it has enough verified evidence", plan["stop_policy"])
        for stage in plan["stages"]:
            self.assertTrue(stage["early_exit"])
            self.assertTrue(stage["handoff_required"])
            self.assertTrue(stage["stop_when"])
            self.assertTrue(stage["handoff"])

    def test_unreal_graph_prompt_gets_unreal_and_safety_experts(self) -> None:
        decision = classify_prompt_route("In Unreal edit this Blueprint graph and connect the new node safely")
        plan = decision.to_dict()["visible_progress"]
        labels = {expert["id"] for expert in plan["expert_lenses"]}
        self.assertIn("unreal_engineer", labels)
        self.assertIn("safety_validator", labels)
        self.assertEqual(plan["background_worker_required"], True)

    def test_dcc_prompt_gets_dcc_expert_without_unreal_only_assumption(self) -> None:
        decision = classify_prompt_route("Maya create a rig control and validate the scene")
        plan = decision.to_dict()["visible_progress"]
        labels = {expert["id"] for expert in plan["expert_lenses"]}
        self.assertIn("dcc_technical_director", labels)
        self.assertNotIn("unreal_engineer", labels)

    def test_render_visible_plan_is_compact(self) -> None:
        plan = build_prompt_progress_plan("Explain this function", {"route": "chat", "provider": "model"})
        text = render_prompt_progress_plan(plan, max_stages=2)
        self.assertIn("What I understood", text)
        self.assertIn("How I will approach it", text)
        self.assertIn("What I am doing", text)
        self.assertTrue(first_progress_status(plan))

    def test_existing_progress_observer_narrates_structured_unreal_task_events(self) -> None:
        raw = (
            'TASK_EVENT:{"type":"verification_batch_finished","batch_number":2,'
            '"batch_total":3,"elapsed_ms":1250,"failed_clause_ids":[]}'
        )

        message = narrate_progress_message(raw)

        self.assertEqual(
            "Task check 2/3 finished in 1.25s; all clauses matched.",
            message,
        )


if __name__ == "__main__":
    unittest.main()
