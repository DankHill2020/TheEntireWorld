"""Tests for the Hybrid LLM Router supporting Cloud API with local Ollama fallback."""

import json
import urllib.request
import urllib.error
import io
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.llm_router_service import generate_llm_response


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


class MockHTTPErrorOpener:
    """Mock Opener to simulate HTTP Errors (e.g. 402 Payment Required)."""
    def __init__(self, code=402, msg="Payment Required"):
        self.code = code
        self.msg = msg
        self.ollama_calls = 0

    def open(self, request, timeout=None):
        url = request.get_full_url()
        if "api.openai.com" in url:
            # Raise HTTPError for OpenAI
            raise urllib.error.HTTPError(
                url=url,
                code=self.code,
                msg=self.msg,
                hdrs={},
                fp=io.BytesIO(b"")
            )
        elif "11434" in url or "api/generate" in url:
            self.ollama_calls += 1
            return io.BytesIO(json.dumps({"response": "local_ollama_fallback_response"}).encode("utf-8"))
        raise ValueError(f"Unexpected URL: {url}")


def test_openai_payment_required_fallback(temp_settings, monkeypatch):
    """Verify that a 402 Payment Required cloud error triggers local Ollama fallback."""
    settings = load_settings()
    settings["model_source_mode"] = "auto_with_local_fallback"
    settings["openai_api_key"] = "test-key"
    settings["cloud_provider_model"] = "gpt-4o"
    save_settings(settings)

    mock_opener = MockHTTPErrorOpener(code=402, msg="Payment Required")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: mock_opener)

    response = generate_llm_response(
        model="qwen3:8b",
        prompt="hello, list capabilities",
        system="be concise"
    )

    assert response == "local_ollama_fallback_response"
    assert mock_opener.ollama_calls == 1
