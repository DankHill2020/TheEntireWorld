"""Focused tests for the simple public AI namespace."""

from __future__ import annotations

from unittest.mock import patch

from tech_connector.api import TechConnectorHeadlessAPI
from tech_connector.services.local_model_optimizer_service import LocalHardwareProfile


def _api(depth: str = "balanced") -> TechConnectorHeadlessAPI:
    class FakeEntitlement:
        def to_dict(self):
            return {"tier": "test"}
    api = TechConnectorHeadlessAPI(
        settings={
            "model": "openai:gpt-6.1-sol",
            "openai_api_key": "test-key",
            "auto_select_openai_model_by_depth": True,
            "code_prompt_depth": depth,
            "model_source_mode": "auto_with_local_fallback",
            "openai_store_responses": False,
        },
        require_entitlement=False,
    )

    api._require_unlocked = lambda: FakeEntitlement()
    api._tag = lambda *_args, **_kwargs: {"operation": "ai.generate"}
    return api

@patch(
    "tech_connector.services.authenticated_provider_service.account_provider_is_connected",
    return_value=False,
)
def test_ai_route_explains_quality_tier_without_exposing_credentials(_connected):
    result = _api().ai.route(depth="maximum")

    assert result.ok, result.error
    assert result.result["requested_model"] == "openai:gpt-6-astra"
    assert result.result["route"] == {
        "provider": "openai",
        "model": "gpt-6-astra",
        "cloud_active": True,
        "transport": "api_key",
    }
    assert result.result["options"]["reasoning_effort"] == "max"
    assert "test-key" not in repr(result.to_dict())


@patch(
    "tech_connector.services.authenticated_provider_service.account_provider_is_connected",
    return_value=False,
)
def test_ai_generate_uses_stable_route_and_returns_route_metadata(
    _connected, monkeypatch
):
    captured = {}

    def fake_generate(model, prompt, **kwargs):
        captured.update(model=model, prompt=prompt, **kwargs)
        return "finished"

    monkeypatch.setattr(
        "tech_connector.services.llm_router_service.generate_llm_response",
        fake_generate,
    )
    result = _api().ai.generate("Do the work", depth="deep")

    assert result.ok, result.error
    assert result.result["text"] == "finished"
    assert result.result["route"]["model"] == "gpt-6.1-sol"
    assert captured["provider_route"].model == "gpt-6.1-sol"
    assert captured["options"]["reasoning_effort"] == "high"
    assert captured["allow_cloud_fallback"] is False


@patch(
    "tech_connector.services.authenticated_provider_service.account_provider_is_connected",
    return_value=False,
)
def test_ai_route_preserves_an_explicit_unrelated_openai_model(_connected):
    result = _api().ai.route(model="openai:gpt-4.1", depth="maximum")

    assert result.ok, result.error
    assert result.result["requested_model"] == "openai:gpt-4.1"
    assert result.result["route"]["model"] == "gpt-4.1"


def test_ai_route_rejects_unknown_depth_with_actionable_error():
    result = _api().ai.route(depth="unlimited")

    assert not result.ok
    assert "fast, balanced, deep, maximum" in result.error


def test_cloud_route_does_not_probe_local_ollama(monkeypatch):
    def fail_local_probe(_model):
        raise AssertionError("Cloud routes must not probe Ollama.")

    monkeypatch.setattr(
        "tech_connector.services.ollama_service.resolve_ollama_model_name",
        fail_local_probe,
    )
    result = _api().ai.route(depth="balanced")
    assert result.ok, result.error
    assert result.result["route"]["provider"] == "openai"


def test_ai_generate_rejects_empty_prompt_before_network_access():
    result = _api().ai.generate("   ")

    assert not result.ok
    assert result.error == "prompt must not be empty"


def test_ai_models_reports_settings_key_as_connected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _api().ai.models()

    assert result.ok, result.error
    openai = next(item for item in result.result["providers"] if item["id"] == "openai")
    assert openai["connected"] is True
    assert "openai:gpt-6.1-sol" in openai["models"]


def test_ai_model_catalog_does_not_launch_account_status_clients(monkeypatch):
    probes = []

    def credentials(provider_id, *, probe_account=True):
        probes.append((provider_id, probe_account))
        return provider_id == "ollama"

    monkeypatch.setattr(
        "tech_connector.services.model_provider_service.provider_has_credentials",
        credentials,
    )
    result = _api().ai.models()
    assert result.ok, result.error
    assert probes and all(not probe_account for _provider, probe_account in probes)


def test_local_recommendation_exposes_hardware_aware_lanes(monkeypatch):
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.installed_ollama_models",
        lambda: ["qwen3:4b-instruct", "qwen2.5-coder:7b"],
    )
    monkeypatch.setattr(
        "tech_connector.services.local_model_optimizer_service.detect_local_hardware",
        lambda: LocalHardwareProfile("RTX 3060 Ti", 8.0),
    )

    result = _api().ai.local_recommendation()

    assert result.ok, result.error
    assert result.result["targets"]["general"] == "qwen3.5:4b"
    assert result.result["targets"]["deep"] == "qwen3.5:9b"
    assert result.result["active"]["general"] == "qwen3:4b-instruct"


def test_local_benchmark_uses_recommended_active_model(monkeypatch):
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.installed_ollama_models",
        lambda: ["qwen3.5:4b"],
    )
    monkeypatch.setattr(
        "tech_connector.services.local_model_optimizer_service.benchmark_local_model",
        lambda model, **_kwargs: {"model": model, "tokens_per_second": 72.5},
    )

    result = _api().ai.benchmark_local(num_predict=16)

    assert result.ok, result.error
    assert result.result["model"] == "qwen3.5:4b"
    assert result.result["tokens_per_second"] == 72.5
