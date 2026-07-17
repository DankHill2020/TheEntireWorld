from __future__ import annotations

import unittest

from tech_connector.services.process_streamlining_service import (
    build_process_streamlining_plan,
    render_streamlining_plan,
)
from tech_connector.services.prompt_progress_service import build_prompt_progress_plan, compact_prompt_progress_plan


class TestProcessStreamliningService(unittest.TestCase):
    def test_known_capability_uses_fast_function_loop(self) -> None:
        plan = build_process_streamlining_plan(
            "In Maya run the rig validation tool and report results",
            known_capabilities=[{"name": "validate_rig"}],
        )

        self.assertEqual("process_streamlining_v1", plan.framework)
        self.assertEqual("capability_function_loop", plan.execution_mode)
        self.assertFalse(plan.requires_model_reasoning)
        self.assertIn("execute callable", plan.fast_path)

    def test_repeatable_multi_step_operation_becomes_pipeline_candidate(self) -> None:
        plan = build_process_streamlining_plan(
            "Create a reusable pipeline that imports animation, validates the rig, exports FBX, and reports outputs",
            known_capabilities=[{"name": "import_animation"}, {"name": "validate_rig"}],
        )

        self.assertTrue(plan.compile_pipeline_candidate)
        self.assertEqual("compiled_pipeline_candidate", plan.execution_mode)
        self.assertIn("registered as a pipeline capability", " ".join(plan.promotion_criteria))

    def test_missing_capability_uses_reasoning_only_until_callable_path_is_known(self) -> None:
        plan = build_process_streamlining_plan(
            "Build a new Unreal graph repair workflow",
            known_capabilities=[],
        )

        self.assertTrue(plan.requires_model_reasoning)
        self.assertIn("matching registered callable capability", plan.missing)
        self.assertIn("Model reasoning: needed only until a callable path is known.", render_streamlining_plan(plan))

    def test_prompt_progress_carries_streamlining_metadata(self) -> None:
        plan = build_prompt_progress_plan(
            "Create a reusable Maya export pipeline and validate it",
            {"route": "pipeline_graph", "mutation_scope": "file_modification"},
        )
        compact = compact_prompt_progress_plan(plan)

        self.assertEqual("process_streamlining_v1", plan["streamlining_model"])
        self.assertEqual("process_streamlining_v1", compact["streamlining_model"])
        self.assertTrue(plan["streamlining_plan"]["compile_pipeline_candidate"])


if __name__ == "__main__":
    unittest.main()
