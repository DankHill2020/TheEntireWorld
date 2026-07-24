"""Tests for the Hybrid LLM Router supporting Cloud API with local Ollama fallback."""

import json
import urllib.request
import urllib.error
import io
from types import SimpleNamespace
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.llm_router_service import (
    LLMCloudProviderError,
    _query_anthropic,
    _query_gemini,
    _query_openai,
    assert_llm_provider_healthy,
    generate_llm_response,
    lock_llm_provider_for_prompt,
    resolve_llm_provider_route,
)
from tech_connector.app.main_window_editor import query_project_index_model_text
from tech_connector.services.model_provider_service import (
    cloud_provider_failure_notice,
    should_force_local,
)


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


def test_openai_payment_required_does_not_break_provider_lock(temp_settings, monkeypatch):
    """A cloud run must fail visibly instead of silently changing models."""
    settings = load_settings()
    settings["model_source_mode"] = "auto_with_local_fallback"
    settings["openai_api_key"] = "test-key"
    settings["cloud_provider_model"] = "gpt-4o"
    save_settings(settings)

    mock_opener = MockHTTPErrorOpener(code=402, msg="Payment Required")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: mock_opener)

    with pytest.raises(LLMCloudProviderError):
        generate_llm_response(
            model="qwen3:8b",
            prompt="hello, list capabilities",
            system="be concise",
        )

    assert mock_opener.ollama_calls == 0


def test_gemini_route_uses_gemini_default_when_only_gemini_key_exists():
    route = resolve_llm_provider_route(
        "qwen3:8b",
        {
            "model_source_mode": "auto_with_local_fallback",
            "cloud_provider_model": "gpt-4o",
            "gemini_api_key": "local-test-key",
        },
    )

    assert route.provider == "gemini"
    assert route.model == "gemini-2.5-flash"
    assert route.cloud_active is True


def test_explicit_selected_cloud_model_wins_for_the_complete_run():
    route = resolve_llm_provider_route(
        "google:gemini-2.5-pro",
        {
            "model_source_mode": "auto_with_local_fallback",
            "cloud_provider_model": "gpt-4o",
            "gemini_api_key": "local-test-key",
        },
    )

    assert route.provider == "gemini"
    assert route.model == "gemini-2.5-pro"


def test_retired_anthropic_selection_is_migrated_to_current_default():
    route = resolve_llm_provider_route(
        "anthropic:claude-3-5-sonnet-latest",
        {
            "model_source_mode": "auto_with_local_fallback",
            "anthropic_api_key": "local-test-key",
        },
    )

    assert route.provider == "anthropic"
    assert route.model == "claude-sonnet-5"
    assert route.cloud_active is True


def test_local_session_preserves_stage_specific_role_models(monkeypatch):
    settings = {
        "model_source_mode": "local_only",
        "model": "ollama:qwen3:8b",
    }
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "tech_connector.services.llm_router_service._query_ollama",
        lambda model, *_args, **_kwargs: model,
    )

    @lock_llm_provider_for_prompt
    def run():
        semantic = generate_llm_response("qwen2.5:1.5b", "understand")
        code = generate_llm_response("qwen3:14b", "code")
        return SimpleNamespace(
            metadata={},
            values=(semantic, code),
        )

    result = run()

    assert result.values == ("qwen2.5:1.5b", "qwen3:14b")
    assert [call["model"] for call in result.metadata["llm_model_calls"]] == [
        "qwen2.5:1.5b",
        "qwen3:14b",
    ]
    assert result.metadata["llm_provider_integrity"]["valid"] is True


def test_cloud_session_uses_exact_selected_model_for_every_stage(monkeypatch):
    settings = {
        "model_source_mode": "auto_with_local_fallback",
        "model": "google:gemini-2.5-flash",
        "cloud_provider_model": "google:gemini-2.5-flash",
        "gemini_api_key": "local-test-key",
    }
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "tech_connector.services.llm_router_service._query_gemini",
        lambda model, *_args, **_kwargs: model,
    )

    @lock_llm_provider_for_prompt
    def run():
        semantic = generate_llm_response("qwen2.5:1.5b", "understand")
        code = generate_llm_response("qwen3:14b", "code")
        return SimpleNamespace(
            metadata={},
            values=(semantic, code),
        )

    result = run()

    assert result.values == ("gemini-2.5-flash", "gemini-2.5-flash")
    assert {
        (call["provider"], call["model"])
        for call in result.metadata["llm_model_calls"]
    } == {("gemini", "gemini-2.5-flash")}
    assert result.metadata["llm_provider_integrity"]["valid"] is True


def test_swallowed_cloud_stage_failure_poison_stops_the_prompt_run(monkeypatch):
    settings = {
        "model_source_mode": "auto_with_local_fallback",
        "model": "google:gemini-2.5-flash",
        "gemini_api_key": "local-test-key",
    }
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "tech_connector.services.llm_router_service._query_gemini",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("quota")),
    )

    @lock_llm_provider_for_prompt
    def run():
        try:
            generate_llm_response("qwen2.5:1.5b", "understand")
        except LLMCloudProviderError:
            pass
        assert_llm_provider_healthy()

    with pytest.raises(LLMCloudProviderError, match="quota"):
        run()


def test_gemini_structured_request_keeps_key_out_of_url(monkeypatch):
    captured = {}

    class GeminiOpener:
        def open(self, request, timeout=None):
            captured["url"] = request.get_full_url()
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return io.BytesIO(
                json.dumps(
                    {
                        "candidates": [
                            {"content": {"parts": [{"text": '{"ok":true}'}]}}
                        ]
                    }
                ).encode("utf-8")
            )

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args: GeminiOpener(),
    )
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }

    result = _query_gemini(
        "gemini-2.5-flash",
        "secret-test-key",
        "Return a result.",
        system="Use the schema.",
        response_format=schema,
        options={"temperature": 0.0, "thinking_budget": 128},
    )

    assert result == '{"ok":true}'
    assert "secret-test-key" not in captured["url"]
    assert captured["headers"]["X-goog-api-key"] == "secret-test-key"
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "Use the schema."
    config = captured["payload"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == schema


def test_openai_planning_schema_is_forward_compatible(monkeypatch):
    captured = {}

    class OpenAIOpener:
        def open(self, request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return io.BytesIO(
                json.dumps(
                    {"choices": [{"message": {"content": '{"ok":true}'}}]}
                ).encode("utf-8")
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: OpenAIOpener())

    _query_openai(
        "gpt-5.6-sol",
        "secret-test-key",
        "Return a result.",
        response_format={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": True,
        },
    )

    schema_config = captured["payload"]["response_format"]["json_schema"]
    assert schema_config["strict"] is False


def test_anthropic_sonnet_five_omits_rejected_sampling_controls(monkeypatch):
    captured = {}

    class AnthropicOpener:
        def open(self, request, timeout=None):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return io.BytesIO(
                json.dumps(
                    {"content": [{"type": "text", "text": '{"ok":true}'}]}
                ).encode("utf-8")
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: AnthropicOpener())

    result = _query_anthropic(
        "claude-sonnet-5",
        "secret-test-key",
        "Return a result.",
        response_format="json",
        options={"temperature": 0.0},
    )

    assert result == '{"ok":true}'
    assert "temperature" not in captured["payload"]


def test_anthropic_http_error_keeps_useful_detail_and_redacts_key(monkeypatch):
    class AnthropicErrorOpener:
        def open(self, request, timeout=None):
            raise urllib.error.HTTPError(
                url=request.get_full_url(),
                code=400,
                msg="Bad Request",
                hdrs={},
                fp=io.BytesIO(
                    json.dumps(
                        {
                            "error": {
                                "message": "invalid request for secret-test-key"
                            }
                        }
                    ).encode("utf-8")
                ),
            )

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *args: AnthropicErrorOpener(),
    )

    with pytest.raises(RuntimeError) as error:
        _query_anthropic(
            "claude-sonnet-5",
            "secret-test-key",
            "Return a result.",
        )

    assert "invalid request for [REDACTED]" in str(error.value)
    assert "secret-test-key" not in str(error.value)


def test_project_index_cloud_text_stage_never_calls_local_model():
    route = SimpleNamespace(
        provider="anthropic",
        model="claude-sonnet-5",
        cloud_active=True,
    )
    calls = []

    def local_query(**_kwargs):
        raise AssertionError("cloud UI stage crossed into local generation")

    def cloud_query(model, prompt, **kwargs):
        calls.append((model, prompt, kwargs))
        return "cloud artifact"

    result = query_project_index_model_text(
        route,
        model="qwen3-coder:30b",
        system_prompt="Generate one file.",
        user_prompt="Implement it.",
        num_predict=6000,
        local_query=local_query,
        cloud_query=cloud_query,
    )

    assert result == "cloud artifact"
    assert calls[0][0] == "claude-sonnet-5"
    assert calls[0][2]["provider_route"] is route
    assert calls[0][2]["allow_cloud_fallback"] is False


def test_project_index_local_text_stage_preserves_stage_specific_model():
    route = SimpleNamespace(
        provider="ollama",
        model="qwen3:8b",
        cloud_active=False,
    )
    captured = {}

    def local_query(**kwargs):
        captured.update(kwargs)
        return "local artifact"

    result = query_project_index_model_text(
        route,
        model="qwen3-coder:30b",
        system_prompt="Generate one file.",
        user_prompt="Implement it.",
        local_query=local_query,
        cloud_query=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local UI stage crossed into cloud generation")
        ),
    )

    assert result == "local artifact"
    assert captured["model"] == "qwen3-coder:30b"


def test_exhausted_cloud_credits_warn_without_implicit_local_fallback():
    notice = cloud_provider_failure_notice(
        "Your credit balance is too low to access the Anthropic API.",
        "anthropic:claude-sonnet-5",
    )

    assert "Cloud Model Unavailable" in notice
    assert "API credits are unavailable or exhausted" in notice
    assert "no local fallback was used" in notice
    assert should_force_local(
        {
            "model_source_mode": "auto_with_local_fallback",
            "cloud_model_unavailable": True,
        }
    ) is False
    assert should_force_local({"model_source_mode": "local_only"}) is True


def test_openai_and_gemini_credit_warnings(monkeypatch):
    """Test that _query_openai and _query_gemini raise proper warnings on quota/credit HTTP errors."""
    
    # We will mock opener.open to raise an HTTPError
    def mock_build_opener(*args, **kwargs):
        class MockOpener:
            def open(self, request, timeout=None):
                raise urllib.error.HTTPError(
                    url="https://api.openai.com/v1/chat/completions",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={},
                    fp=io.BytesIO(b'{"error": {"message": "You exceeded your current quota"}}')
                )
        return MockOpener()
        
    monkeypatch.setattr(urllib.request, "build_opener", mock_build_opener)
    
    with pytest.raises(RuntimeError) as exc_info:
        _query_openai("gpt-4o", "test-key", "hello")
    assert "Insufficient API Credits / Quota Exceeded" in str(exc_info.value)
    
    def mock_build_opener_gemini(*args, **kwargs):
        class MockOpener:
            def open(self, request, timeout=None):
                raise urllib.error.HTTPError(
                    url="https://generativelanguage.googleapis.com",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={},
                    fp=io.BytesIO(b'{"error": {"message": "Quota exceeded"}}')
                )
        return MockOpener()
        
    monkeypatch.setattr(urllib.request, "build_opener", mock_build_opener_gemini)
    
    with pytest.raises(RuntimeError) as exc_info:
        _query_gemini("gemini-2.5-flash", "test-key", "hello")
    assert "Insufficient API Credits / Quota Exceeded" in str(exc_info.value)


def test_resolve_llm_provider_route_warnings(capsys):
    """Test that resolve_llm_provider_route prints a warning to stderr when cloud key is missing."""
    
    resolve_llm_provider_route(
        "google:gemini-2.5-flash",
        {
            "model_source_mode": "auto_with_local_fallback",
        }
    )
    captured = capsys.readouterr()
    assert "[WARNING] Cloud model" in captured.err
    assert "no API key is configured" in captured.err
