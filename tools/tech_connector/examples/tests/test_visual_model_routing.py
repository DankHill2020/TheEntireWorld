from types import SimpleNamespace

from tech_connector.services.adaptive.model_budget import choose_adaptive_model_budget


def _state():
    return SimpleNamespace(
        budget=SimpleNamespace(
            token_budget=6000,
            reserved_output_tokens=1200,
            runtime_budget_ms=120000,
            reasoning_level="standard",
        ),
        prediction=SimpleNamespace(
            predicted_output_tokens=800,
            complexity_score=0.2,
        ),
        confidence=SimpleNamespace(
            intent=0.9,
            target=0.9,
            knowledge=0.9,
        ),
    )


def test_visual_media_stage_uses_visual_model_not_code_model():
    budget = choose_adaptive_model_budget(
        _state(),
        stage_type="visual_media",
        settings={
            "router_visual_media": "llava:latest",
            "router_local_code": "qwen2.5-coder:7b",
            "fast_code_model": "qwen2.5-coder:7b",
        },
    )

    assert budget.model_tier == "local_visual"
    assert budget.model_name == "llava:latest"
    assert "coder" not in budget.model_name


def test_visual_media_stage_falls_back_to_general_not_code():
    budget = choose_adaptive_model_budget(
        _state(),
        stage_type="image",
        settings={
            "fast_general_model": "qwen3:4b-instruct",
            "router_local_code": "qwen2.5-coder:7b",
            "fast_code_model": "qwen2.5-coder:7b",
        },
    )

    assert budget.model_tier == "local_visual"
    assert budget.model_name == "qwen3:4b-instruct"
    assert "coder" not in budget.model_name
