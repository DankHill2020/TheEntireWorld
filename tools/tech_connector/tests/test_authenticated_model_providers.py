"""Focused tests for provider categories and account-backed routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from tech_connector.app.main_window_history_assets import MainWindowHistoryAssetsMixin
from tech_connector.services import authenticated_provider_service
from tech_connector.services.llm_router_service import resolve_llm_provider_route
from tech_connector.services.model_provider_service import (
    PROVIDER_ORDER,
    PROVIDERS,
    models_for_provider,
    provider_for_model,
)


class ProviderCategoryTests(unittest.TestCase):
    def test_categories_are_complete_and_ordered(self):
        self.assertEqual(
            PROVIDER_ORDER,
            ("ollama", "openai", "x", "google", "anthropic"),
        )
        self.assertEqual(
            [PROVIDERS[item].display_name for item in PROVIDER_ORDER],
            ["Local", "OpenAI", "X", "Google Gemini", "Anthropic"],
        )

    def test_each_category_only_contains_its_own_models(self):
        for provider_id in PROVIDER_ORDER:
            with self.subTest(provider=provider_id):
                models = models_for_provider(provider_id)
                self.assertTrue(models)
                self.assertTrue(
                    all(provider_for_model(model) == provider_id for model in models)
                )

    def test_qt_model_dropdown_is_filtered_by_provider(self):
        QApplication.instance() or QApplication([])

        class Harness(MainWindowHistoryAssetsMixin):
            pass

        harness = Harness()
        harness.settings = {"model": "ollama:qwen3:8b"}
        harness.model_provider_box = QComboBox()
        harness.model_box = QComboBox()
        harness._local_model_options = [
            ("Local A", "ollama:qwen3:8b"),
            ("Local B", "ollama:qwen2.5-coder:7b"),
        ]
        harness._installed_ollama_models = []

        for provider_id in PROVIDER_ORDER:
            with self.subTest(provider=provider_id):
                harness.refresh_model_options_for_provider(provider_id)
                visible_models = [
                    harness.model_box.itemData(index)
                    for index in range(harness.model_box.count())
                ]
                self.assertTrue(visible_models)
                self.assertTrue(
                    all(
                        provider_for_model(model) == provider_id
                        for model in visible_models
                    )
                )


class ProviderRouteTests(unittest.TestCase):
    @patch(
        "tech_connector.services.authenticated_provider_service."
        "account_provider_is_connected",
        return_value=True,
    )
    def test_account_login_is_preferred_to_api_key(self, _connected):
        route = resolve_llm_provider_route(
            "openai:gpt-5.3-codex",
            {
                "model_source_mode": "auto_with_local_fallback",
                "openai_api_key": "advanced-fallback",
            },
        )
        self.assertEqual(route.provider, "openai")
        self.assertEqual(route.transport, "account")
        self.assertEqual(route.api_key, "")

    @patch(
        "tech_connector.services.authenticated_provider_service."
        "account_provider_is_connected",
        return_value=False,
    )
    def test_x_api_key_remains_an_advanced_fallback(self, _connected):
        route = resolve_llm_provider_route(
            "x:grok-4.5",
            {
                "model_source_mode": "auto_with_local_fallback",
                "xai_api_key": "fallback-key",
            },
        )
        self.assertEqual(route.provider, "x")
        self.assertEqual(route.transport, "api_key")
        self.assertEqual(route.model, "grok-4.5")


class ProviderExecutableTests(unittest.TestCase):
    def test_configured_executable_path_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "claude.cmd"
            executable.write_text("@exit /b 0\n", encoding="ascii")
            with patch.object(
                authenticated_provider_service,
                "_configured_executable",
                return_value=str(executable),
            ):
                self.assertEqual(
                    authenticated_provider_service.resolve_provider_executable(
                        "anthropic"
                    ),
                    str(executable),
                )

    def test_codex_jsonl_agent_message_is_extracted(self):
        event = {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "working result"},
        }
        completed = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(event),
                "stderr": "",
            },
        )()
        with patch.object(
            authenticated_provider_service.subprocess,
            "run",
            return_value=completed,
        ):
            self.assertEqual(
                authenticated_provider_service._run_provider(
                    ["codex"],
                    prompt_input="request",
                    timeout=5,
                ),
                "working result",
            )


if __name__ == "__main__":
    unittest.main()
