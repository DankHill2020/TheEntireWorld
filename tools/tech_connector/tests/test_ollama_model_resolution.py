from __future__ import annotations

import unittest

from tech_connector.knowledge.search import resolve_installed_ollama_model


class TestOllamaModelResolution(unittest.TestCase):
    def test_missing_tag_uses_installed_same_family_tag(self) -> None:
        model = resolve_installed_ollama_model(
            "ollama:qwen3:14b",
            ["qwen3:8b", "qwen2.5-coder:14b"],
        )

        self.assertEqual("qwen3:8b", model)

    def test_missing_family_uses_first_installed_model_for_non_code_paths(self) -> None:
        model = resolve_installed_ollama_model(
            "llama3:latest",
            ["qwen3:8b", "qwen2.5-coder:14b"],
        )

        self.assertEqual("qwen3:8b", model)

    def test_code_paths_can_prefer_coder_when_selected_tag_is_missing(self) -> None:
        model = resolve_installed_ollama_model(
            "ollama:qwen3:14b",
            ["qwen3:8b", "qwen2.5-coder:14b"],
            prefer_coder=True,
        )

        self.assertEqual("qwen2.5-coder:14b", model)

    def test_code_paths_promote_tiny_configured_coder_when_stronger_coder_is_installed(self) -> None:
        model = resolve_installed_ollama_model(
            "qwen2.5-coder:1.5b",
            ["qwen2.5-coder:1.5b", "qwen2.5-coder:14b", "qwen3-coder:30b", "qwen3:8b"],
            prefer_coder=True,
        )

        self.assertEqual("qwen2.5-coder:14b", model)

    def test_fast_code_stage_uses_smallest_capable_installed_coder(self) -> None:
        model = resolve_installed_ollama_model(
            "qwen2.5-coder:1.5b",
            ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b"],
            prefer_coder=True,
            coder_preference="fast",
        )

        self.assertEqual("qwen2.5-coder:7b", model)

    def test_small_code_stage_uses_installed_three_billion_coder(self) -> None:
        model = resolve_installed_ollama_model(
            "qwen2.5-coder:3b",
            ["qwen2.5-coder:1.5b", "qwen2.5-coder:3b", "qwen2.5-coder:7b"],
            prefer_coder=True,
            coder_preference="small",
        )

        self.assertEqual("qwen2.5-coder:3b", model)

    def test_small_code_stage_falls_forward_to_seven_billion_when_three_is_missing(self) -> None:
        model = resolve_installed_ollama_model(
            "qwen2.5-coder:3b",
            ["qwen2.5-coder:1.5b", "qwen2.5-coder:7b"],
            prefer_coder=True,
            coder_preference="small",
        )

        self.assertEqual("qwen2.5-coder:7b", model)

    def test_quality_repair_stage_uses_balanced_fourteen_billion_coder(self) -> None:
        model = resolve_installed_ollama_model(
            "qwen2.5-coder:1.5b",
            ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b"],
            prefer_coder=True,
            coder_preference="quality",
        )

        self.assertEqual("qwen2.5-coder:14b", model)

    def test_plan_paths_fall_back_to_fast_non_coder_when_requested_plan_model_missing(self) -> None:
        model = resolve_installed_ollama_model(
            "llama3:latest",
            ["qwen2.5-coder:3b", "qwen3:14b", "qwen3:8b", "qwen2.5:1.5b"],
            prefer_coder=False,
        )

        self.assertEqual("qwen3:8b", model)


if __name__ == "__main__":
    unittest.main()
