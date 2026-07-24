import unittest

from scripts.prompt_smoke_ollama import _choose_installed_synthesis_model


class TestPromptSmokeOllama(unittest.TestCase):
    def test_missing_standard_model_prefers_installed_light_coder(self):
        model = _choose_installed_synthesis_model(
            "llama3:latest",
            ["qwen3:14b", "qwen2.5-coder:7b", "qwen2.5-coder:14b"],
            model_tier="standard",
        )

        self.assertEqual("qwen2.5-coder:7b", model)

    def test_strong_model_prefers_installed_strong_reasoner(self):
        model = _choose_installed_synthesis_model(
            "missing:latest",
            ["qwen2.5-coder:7b", "qwen3:14b"],
            model_tier="strong",
        )

        self.assertEqual("qwen3:14b", model)


if __name__ == "__main__":
    unittest.main()
