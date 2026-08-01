from __future__ import annotations

from tech_connector.services.open_knowledge_policy_service import (
    assess_open_knowledge_source,
    partition_open_knowledge_sources,
)


def test_public_open_source_is_learning_eligible() -> None:
    result = assess_open_knowledge_source(
        {
            "url": "https://example.org/open-technique",
            "public_access": True,
            "license": "CC BY 4.0",
        }
    )

    assert result["eligible"]
    assert result["community_share_allowed"]


def test_authenticated_or_paid_source_cannot_become_learned_knowledge() -> None:
    result = assess_open_knowledge_source(
        {
            "url": "https://market.example/item",
            "public_access": True,
            "license": "Commercial",
            "auth_required": True,
            "paid": True,
        }
    )

    assert not result["eligible"]
    assert not result["community_share_allowed"]
    assert not result["task_use_allowed"]
    assert not result["local_learning_allowed"]


def test_entitled_restricted_source_can_be_used_and_learned_only_locally() -> None:
    result = assess_open_knowledge_source(
        {
            "url": "https://market.example/item",
            "license": "Commercial",
            "auth_required": True,
            "authenticated": True,
            "paid": True,
            "user_entitled": True,
            "allow_task_use": True,
            "allow_local_learning": True,
        }
    )

    assert not result["eligible"]
    assert result["task_use_allowed"]
    assert result["local_learning_allowed"]
    assert not result["community_share_allowed"]


def test_local_learning_requires_separate_opt_in() -> None:
    result = assess_open_knowledge_source(
        {
            "url": "https://private.example/guide",
            "private": True,
            "auth_required": True,
            "authenticated": True,
            "user_entitled": True,
            "allow_task_use": True,
        }
    )

    assert result["task_use_allowed"]
    assert not result["local_learning_allowed"]
    assert not result["community_share_allowed"]


def test_private_project_evidence_is_rejected_even_with_open_license_label() -> None:
    partitioned = partition_open_knowledge_sources(
        [
            {
                "url": "https://example.org/private-export",
                "public_access": True,
                "license": "MIT",
                "contains_private_data": True,
            }
        ]
    )

    assert partitioned["accepted"] == []
    assert len(partitioned["rejected"]) == 1
