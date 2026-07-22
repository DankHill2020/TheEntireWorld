import unittest

from tech_connector.services.ollama_resource_service import (
    build_ollama_options,
    choose_ollama_generation_budget,
    choose_project_edit_coder_profile,
    ollama_keep_alive,
)


class TestOllamaResourceService(unittest.TestCase):
    def test_defaults_leave_os_threads_available(self):
        options = build_ollama_options(num_ctx=4096, num_predict=512, settings={})
        self.assertEqual(4096, options["num_ctx"])
        self.assertEqual(512, options["num_predict"])
        self.assertGreaterEqual(options["num_thread"], 1)
        self.assertLessEqual(options["num_thread"], 8)

    def test_settings_can_override_threads_gpu_and_keep_alive(self):
        settings = {
            "ollama_num_thread": 3,
            "ollama_num_gpu": 18,
            "ollama_keep_alive": "2m",
            "ollama_temperature": 0.1,
        }
        options = build_ollama_options(num_ctx=2048, num_predict=128, settings=settings)
        self.assertEqual(3, options["num_thread"])
        self.assertEqual(18, options["num_gpu"])
        self.assertEqual(0.1, options["temperature"])
        self.assertEqual("2m", ollama_keep_alive(settings))

    def test_generation_budget_scales_for_large_evidence(self):
        small = choose_ollama_generation_budget(prompt="Summarize this result.", evidence_text="", route="project_search")
        deep = choose_ollama_generation_budget(
            prompt="Plan the implementation, validation, rollback, and reporting strategy for this edit.",
            evidence_text="evidence\n" * 1500,
            route="target_discovery",
            llm_mode="required",
        )

        self.assertEqual("small", small.tier)
        self.assertEqual("deep", deep.tier)
        self.assertGreater(deep.num_ctx, small.num_ctx)
        self.assertGreater(deep.num_predict, small.num_predict)
        self.assertGreater(deep.timeout_seconds, small.timeout_seconds)
        self.assertEqual("standard", deep.model_tier)

    def test_generation_budget_escalates_for_low_confidence(self):
        budget = choose_ollama_generation_budget(
            prompt="Which path should I take?",
            evidence_text="short evidence",
            route="target_discovery",
            llm_mode="required",
            confidence=0.42,
        )

        self.assertEqual("deep", budget.tier)
        self.assertEqual("strong", budget.model_tier)

    def test_generation_budget_respects_resource_caps(self):
        budget = choose_ollama_generation_budget(
            prompt="Plan a complex implementation with validation and rollback.",
            evidence_text="evidence\n" * 1500,
            route="target_discovery",
            llm_mode="required",
            settings={
                "ollama_max_num_ctx": 5000,
                "ollama_max_num_predict": 600,
                "ollama_max_timeout_seconds": 90,
            },
        )

        self.assertEqual(5000, budget.num_ctx)
        self.assertEqual(600, budget.num_predict)
        self.assertEqual(90, budget.timeout_seconds)

    def test_project_edit_profile_starts_micro_and_escalates_on_failed_validation(self):
        prompt = "Add a focused validation summary helper to the current service."

        self.assertEqual("micro", choose_project_edit_coder_profile(prompt=prompt))
        self.assertEqual("small", choose_project_edit_coder_profile(prompt=prompt, repair_attempt=1))
        self.assertEqual("standard", choose_project_edit_coder_profile(prompt=prompt, repair_attempt=2))
        self.assertEqual("standard", choose_project_edit_coder_profile(prompt=prompt, repair_attempt=3))
        self.assertEqual("standard", choose_project_edit_coder_profile(prompt=prompt, repair_attempt=4))

    def test_project_edit_profile_reserves_quality_model_for_fresh_tools(self):
        self.assertEqual(
            "quality",
            choose_project_edit_coder_profile(prompt="Build an entire tool from scratch with tests."),
        )
        self.assertEqual(
            "micro",
            choose_project_edit_coder_profile(prompt="Fix a docstring typo in this function."),
        )
        self.assertEqual(
            "quality",
            choose_project_edit_coder_profile(
                prompt="Build an entire tool from scratch with tests.",
                repair_attempt=4,
            ),
        )


if __name__ == "__main__":
    unittest.main()
