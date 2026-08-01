from __future__ import annotations

from tech_connector.services.unreal.animation_context_service import (
    evaluate_animation_candidate,
    infer_animation_roles,
)


def test_prone_prompt_expands_to_transition_crawl_and_turn_contracts() -> None:
    roles = infer_animation_roles(
        "Enter prone, crawl forward and backward, perform a prone 180 turn, then stand from prone."
    )

    assert {"prone_transition", "prone_crawl", "prone_turn"}.issubset(roles)


def test_paired_disarm_requires_both_attacker_and_victim_roles() -> None:
    roles = infer_animation_roles("Paired attacker/victim disarm takedown animation")

    assert "paired_disarm_attacker" in roles
    assert "paired_disarm_victim" in roles


def test_generic_provider_page_cannot_satisfy_paired_motion_contract() -> None:
    result = evaluate_animation_candidate(
        "paired_disarm_attacker",
        {"name": "Generic Animation Marketplace", "description": "Thousands of FBX motions"},
    )

    assert not result["accepted"]
    assert "does not prove" in result["reason"]


def test_natural_ledge_prompt_preserves_each_contextual_motion_role() -> None:
    roles = infer_animation_roles(
        "Enter a hang from a jump, shimmies left and right, turns around an outside corner, "
        "and jumps backward to another ledge."
    )

    assert {
        "climb_hang",
        "ledge_shimmy",
        "ledge_corner",
        "ledge_back_jump",
    }.issubset(roles)


def test_natural_prone_system_wording_preserves_each_motion_role() -> None:
    roles = infer_animation_roles(
        "Entering prone, crawling under an obstacle, turning 180 degrees while prone, "
        "crawling backward, and returning to standing."
    )

    assert {"prone_transition", "prone_crawl", "prone_turn"}.issubset(roles)
