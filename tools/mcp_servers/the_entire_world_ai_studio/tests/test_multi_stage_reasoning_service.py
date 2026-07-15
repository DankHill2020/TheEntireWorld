from __future__ import annotations

import unittest

from services.multi_stage_reasoning_service import (
    build_reasoning_pipeline,
    render_reasoning_pipeline,
)
from services.prompt_route_service import classify_prompt_route


class TestMultiStageReasoningService(unittest.TestCase):
    def test_build_reasoning_pipeline_has_all_specialist_stages(self) -> None:
        decision = {
            "route": "dcc_prototype",
            "provider": "dcc",
            "confidence": 0.82,
            "host": "unreal",
            "intent_category": "dcc_prototype",
            "requires_plan": True,
            "requires_dcc_connection": True,
            "requires_confirmation": True,
            "mutation_scope": "dcc_scene_mutation",
            "risk_level": "high",
            "context_resolvers": ["dcc_connection", "scene_context", "capability_graph"],
            "deterministic_steps": ["gather_scene_context", "plan_prototype", "confirm_execution"],
            "senior_prompt_analysis": {
                "primary_objective": "Create a Niagara emitter and attach it to a character hand",
                "unknown_or_ambiguous": ["target character/socket may need discovery"],
                "verification_criteria": ["verify emitter attachment in editor"],
            },
        }
        plan = build_reasoning_pipeline(
            "In Unreal create a niagara emitter attached to my character hand",
            decision,
        )
        self.assertEqual(plan["framework"], "multi_stage_reasoning_v1")
        self.assertEqual(plan["stage_count"], 11)
        keys = [stage["key"] for stage in plan["stages"]]
        self.assertEqual(keys[0], "intent_analysis")
        self.assertIn("gap_discovery", keys)
        self.assertIn("reflection", keys)
        self.assertIn("post_execution_validation", keys)
        self.assertIn(plan["recommended_next_action"], {"require_confirmation", "hold_until_ready", "offer_best_practice_research"})

    def test_render_reasoning_pipeline_is_compact(self) -> None:
        plan = build_reasoning_pipeline("Audit the Maya rig and report issues", {"route": "quality_audit", "confidence": 0.9})
        text = render_reasoning_pipeline(plan, max_stages=3)
        self.assertIn("Multi-stage reasoning:", text)
        self.assertIn("Intent Analysis", text)
        self.assertIn("later stage", text)

    def test_prompt_route_attaches_reasoning_pipeline(self) -> None:
        decision = classify_prompt_route("Maya bind skin mesh body_GEO with root_JNT spine_JNT")
        data = decision.to_dict()
        self.assertIn("reasoning_pipeline", data)
        self.assertIn("capability_gap_plan", data)
        self.assertEqual(data["reasoning_pipeline"]["framework"], "multi_stage_reasoning_v1")
        self.assertEqual(data["capability_gap_plan"]["framework"], "goal_gap_planning_v1")
        self.assertGreaterEqual(len(data["reasoning_pipeline"]["stages"]), 8)

    def test_stage_fields_are_lists_not_character_split_strings(self) -> None:
        plan = build_reasoning_pipeline(
            "Find a Maya rigging function, build a UI for it, compile it, and report validation.",
            {"route": "project_edit", "confidence": 0.8, "mutation_scope": "code_change"},
        )

        for stage in plan["stages"]:
            self.assertIsInstance(stage["verification_gate"], list)
            self.assertFalse(
                stage["verification_gate"] and stage["verification_gate"][0] == "r",
                stage["title"],
            )


if __name__ == "__main__":
    unittest.main()
