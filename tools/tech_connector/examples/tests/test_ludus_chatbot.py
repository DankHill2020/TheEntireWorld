"""Tests for the swappable Chatbot/Reasoning Provider."""

import json
from typing import Any
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.modular_provider_utils import invoke_custom_provider


@pytest.fixture
def temp_settings():
    backup = None
    if SETTINGS_PATH.exists():
        try:
            backup = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    yield
    if backup is not None:
        try:
            SETTINGS_PATH.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        except Exception:
            pass


def test_chatbot_provider_routing(temp_settings):
    """Verify invoke_custom_provider successfully imports and invokes the custom chatbot response generator."""
    settings = load_settings()
    settings["chatbot_provider_module"] = "tech_connector.services.custom_providers.ludus_chatbot_provider"
    save_settings(settings)

    def generate_chat_response(*args, **kwargs):
        return "fallback"

    chunks_collected = []
    def on_chunk(chunk: str):
        chunks_collected.append(chunk)

    res = invoke_custom_provider(
        settings["chatbot_provider_module"],
        generate_chat_response,
        "test prompt",
        [],
        on_chunk
    )

    # Verify mock chatbot executed and streamed content
    assert "Compiled ABP_Manny_Combat successfully." in res
    assert len(chunks_collected) > 0
    assert any("Ludus AI" in chunk for chunk in chunks_collected)
