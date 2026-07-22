from services.model_provider_service import (
    AUTO_WITH_LOCAL_FALLBACK,
    LOCAL_ONLY,
    credential_requirement_for_model,
    is_credit_or_quota_failure,
    provider_for_model,
    provider_setup_notes,
    provider_setup_url,
    resolve_model_for_policy,
    should_use_local_runtime,
)


def test_provider_for_model_detects_prefixes():
    assert provider_for_model("openai:gpt") == "openai"
    assert provider_for_model("google:gemini") == "google"
    assert provider_for_model("anthropic:claude") == "anthropic"
    assert provider_for_model("qwen2.5-coder:1.5b") == "ollama"


def test_local_only_forces_local_model():
    model = resolve_model_for_policy(
        "openai:gpt-4o-mini",
        "ollama:qwen2.5-coder:1.5b",
        {"model_source_mode": LOCAL_ONLY},
    )

    assert model == "ollama:qwen2.5-coder:1.5b"


def test_cloud_unavailable_forces_local_model():
    model = resolve_model_for_policy(
        "openai:gpt-4o-mini",
        "ollama:qwen2.5-coder:1.5b",
        {"model_source_mode": AUTO_WITH_LOCAL_FALLBACK, "cloud_model_unavailable": True},
    )

    assert model == "ollama:qwen2.5-coder:1.5b"


def test_quota_failure_detection():
    assert is_credit_or_quota_failure("insufficient_quota")
    assert is_credit_or_quota_failure("billing hard limit reached")
    assert is_credit_or_quota_failure("Resource exhausted")
    assert not is_credit_or_quota_failure("model loaded successfully")


def test_provider_setup_urls_and_notes_are_explicit():
    assert provider_setup_url("openai") == "https://platform.openai.com/api-keys"
    notes = provider_setup_notes("openai")

    assert "OPENAI_API_KEY" in notes
    assert "will not scrape or auto-transfer API keys" in notes


def test_should_use_local_runtime_only_for_local_policy_or_model():
    assert should_use_local_runtime("ollama:qwen", {"model_source_mode": AUTO_WITH_LOCAL_FALLBACK})
    assert should_use_local_runtime("openai:gpt", {"model_source_mode": LOCAL_ONLY})
    assert not should_use_local_runtime("openai:gpt", {"model_source_mode": AUTO_WITH_LOCAL_FALLBACK})


def test_credential_requirement_marks_cloud_model_action_required_without_key():
    info = credential_requirement_for_model("openai:gpt-4o-mini", {"model_source_mode": AUTO_WITH_LOCAL_FALLBACK})

    assert info["required"] is True
    assert "OpenAI requires setup" in info["status"]
    assert "OPENAI_API_KEY" in info["action"]


def test_credential_requirement_local_only_does_not_require_cloud_key():
    info = credential_requirement_for_model("openai:gpt-4o-mini", {"model_source_mode": LOCAL_ONLY})

    assert info["required"] is False
    assert info["provider"] == "ollama"
