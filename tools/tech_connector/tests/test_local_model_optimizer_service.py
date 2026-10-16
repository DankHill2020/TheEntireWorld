from tech_connector.services.local_model_optimizer_service import (
    LocalHardwareProfile,
    recommend_local_models,
)
from tech_connector.services.ollama_service import (
    code_model_for_profile,
    resolve_ollama_model_name,
)


def test_eight_gb_gpu_uses_fast_primary_and_separate_quality_lane():
    result = recommend_local_models(
        ["qwen3:4b-instruct", "qwen2.5-coder:7b"],
        LocalHardwareProfile("RTX 3060 Ti", 8.0),
    )

    assert result["targets"]["general"] == "qwen3.5:4b"
    assert result["targets"]["code"] == "qwen3.5:4b"
    assert result["targets"]["deep"] == "qwen3.5:9b"
    assert result["active"]["general"] == "qwen3:4b-instruct"
    assert result["active"]["code"] == "qwen2.5-coder:7b"
    assert result["runtime"]["default_num_ctx"] == 4096
    assert result["runtime"]["max_num_ctx"] == 8192


def test_new_fast_model_becomes_active_as_soon_as_it_is_installed():
    result = recommend_local_models(
        ["qwen3.5:4b", "qwen2.5-coder:7b"],
        LocalHardwareProfile("RTX 3060 Ti", 8.0),
    )

    assert result["active"]["intent"] == "qwen3.5:4b"
    assert result["active"]["general"] == "qwen3.5:4b"
    assert result["active"]["code"] == "qwen3.5:4b"
    assert result["active"]["deep"] == "qwen3.5:4b"


def test_large_gpu_gets_specialized_local_deep_lane():
    result = recommend_local_models(
        ["qwen3.5:9b", "qwen3-coder:30b"],
        LocalHardwareProfile("RTX 4090", 24.0),
    )

    assert result["active"]["code"] == "qwen3.5:9b"
    assert result["active"]["deep"] == "qwen3-coder:30b"


def test_explicit_profile_mapping_wins_over_hardware_policy(monkeypatch):
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.hardware_aware_local_models",
        lambda _settings: {"code": "qwen3.5:4b", "deep": "qwen3.5:9b"},
    )

    model = code_model_for_profile(
        "quality",
        {
            "local_model_policy": "hardware_aware",
            "custom_model_mappings": {"profile_quality": "my-coder:latest"},
        },
    )

    assert model == "my-coder:latest"


def test_requested_qwen35_uses_installed_fallback_until_download_finishes(
    monkeypatch,
):
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.installed_ollama_models",
        lambda: ["qwen3:4b-instruct", "qwen2.5-coder:7b"],
    )

    assert resolve_ollama_model_name("qwen3.5:4b") == "qwen3:4b-instruct"
    assert resolve_ollama_model_name("qwen3.5:9b") == "qwen2.5-coder:7b"
