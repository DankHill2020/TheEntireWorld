from __future__ import annotations

import unittest

from services.prompt_resource_orchestration_service import (
    build_resource_orchestration_plan,
    render_resource_orchestration_summary,
)


class TestPromptResourceOrchestrationService(unittest.TestCase):
    def test_serializes_local_model_work_while_parallelizing_discovery(self) -> None:
        plan = build_resource_orchestration_plan(
            "Inspect the project, plan the edit, implement it, compile it, validate it, and report rollback steps.",
            {"route": "project_edit", "mutation_scope": "code_change"},
        )

        self.assertEqual("resource_aware_prompt_orchestration_v1", plan["framework"])
        self.assertEqual(1, plan["local_model_concurrency"])
        self.assertGreaterEqual(plan["deterministic_concurrency"], 2)
        lanes = {lane["key"]: lane for lane in plan["lanes"]}
        self.assertEqual(1, lanes["local_model_serial"]["max_concurrent"])
        self.assertGreaterEqual(lanes["deterministic_discovery"]["max_concurrent"], 2)
        self.assertIn("serialize local model", plan["policy"].lower())
        self.assertIn("early_completion_policy", plan)
        self.assertIn("compiled_pipeline_policy", plan)
        self.assertEqual("local_plan_or_fast", plan["model_tier_policy"]["context_summarization"])
        self.assertEqual("local_code", plan["model_tier_policy"]["patch_generation"])
        self.assertEqual("none_deterministic_or_local_fast", plan["model_tier_policy"]["rag_sufficiency"])

    def test_render_summary_is_user_visible(self) -> None:
        plan = build_resource_orchestration_plan("What functions do I have to create a rig?", {"route": "project_search"})
        text = render_resource_orchestration_summary(plan)

        self.assertIn("Resource plan:", text)
        self.assertIn("Local model workers: 1", text)


if __name__ == "__main__":
    unittest.main()
