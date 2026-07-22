from __future__ import annotations

from tech_connector.services.problem_formulation_service import build_problem_formulation
from tech_connector.services.prompt_execution_context_service import (
    PromptExecutionContext,
    validate_prompt_understanding,
)


def test_explicit_live_execution_overrides_weak_read_only_goal_label() -> None:
    prompt = (
        "In the live Unreal project, build a ledge traversal animation system. "
        "Search existing assets first, then download, retarget, import, integrate, "
        "compile, and run PIE verification."
    )
    understanding = {
        "primary_action": "execute",
        "primary_route": "target_discovery",
        "mutation_requested": True,
        "live_host_execution_requested": True,
    }
    contract = {
        "goal_type": "explain",
        "mutation_requested": True,
        "execution_requested": True,
        "deliverable_type": "graph",
    }

    result = build_problem_formulation(
        prompt,
        request_understanding=understanding,
        semantic_contract=contract,
        context={"host": "unreal"},
    )

    assert result.action_mode == "execute"
    assert "Mutating source files or scene state." not in result.exclusions
    assert any(not step.get("read_only", True) for step in result.candidate_plan)


def test_target_discovery_is_valid_preparation_for_live_execution() -> None:
    context = PromptExecutionContext(
        prompt="Build an unfamiliar Unreal animation system and run PIE verification.",
        normalized_prompt="Build an unfamiliar Unreal animation system and run PIE verification.",
        request_understanding={
            "primary_route": "target_discovery",
            "primary_intent": "project_code_edit",
            "mutation_requested": True,
            "live_host_execution_requested": True,
            "confidence": 0.93,
        },
        planning_result={
            "primary_route": "target_discovery",
            "goal_type": "validate",
            "deliverable": "graph",
            "scope": "project",
            "mutation_requested": True,
            "execution_requested": True,
            "confidence": 0.93,
        },
        semantic_execution_contract={
            "deliverable_type": "graph",
            "mutation_requested": True,
            "execution_requested": True,
        },
    )

    result = validate_prompt_understanding(context)

    assert result.valid
    assert "route_semantic_contract" not in result.ambiguous_fields
