from __future__ import annotations

from tech_connector.services.unreal.animation_knowledge_continuation_service import (
    build_animation_knowledge_continuation,
    resolve_animation_knowledge_choice,
)
from tech_connector.services.autonomous_knowledge_retrieval_engine import (
    AutonomousKnowledgeRetrievalEngine,
)


def _prior() -> dict:
    return {
        "result_type": "unreal_feature_knowledge_choice",
        "plan": {
            "status": "knowledge_choice_required",
            "request": "Build prone crawl, prone 180 turn, and stand from prone animations in Unreal.",
            "target_asset": "/Game/Characters/BP_Player",
            "evidence": {
                "skeletal_mesh": "/Game/Characters/SK_Player",
                "animation_blueprint": "/Game/Characters/ABP_Player",
            },
            "missing_capabilities": [{"capability": "external.asset_source_search"}],
        },
    }


def test_choice_is_bound_to_prior_knowledge_gate() -> None:
    assert resolve_animation_knowledge_choice(
        "original prompt\n\nClarification answer: add_knowledge_first",
        _prior(),
        {"values": {"knowledge_strategy": "add_knowledge_first"}},
    ) == "add_knowledge_first"
    assert resolve_animation_knowledge_choice("add_knowledge_first", {}) == ""


def test_add_knowledge_builds_role_specific_online_and_offline_packet() -> None:
    result = build_animation_knowledge_continuation(
        _prior()["plan"],
        "add_knowledge_first",
        settings={"enable_live_sources": True, "research_web_techniques": True},
    )

    assert result["status"] == "online_research_ready"
    assert {"prone_transition", "prone_crawl", "prone_turn"}.issubset(result["animation_roles"])
    assert result["research_targets"]
    assert all(row["candidate_status"] == "research_target_not_asset_candidate" for row in result["research_targets"])
    assert not result["completion_allowed"]


def test_current_knowledge_blocks_when_no_contextual_clip_exists() -> None:
    result = build_animation_knowledge_continuation(
        _prior()["plan"],
        "run_with_current_knowledge",
        settings={"enable_live_sources": False, "research_web_techniques": False},
    )

    assert result["status"] == "offline_prototype_blocked"
    assert result["recommended"] == "add_knowledge_first"
    assert not result["completion_allowed"]


def test_unwritable_project_knowledge_cache_degrades_to_fallback(monkeypatch) -> None:
    original = AutonomousKnowledgeRetrievalEngine.build_acquisition_plan
    calls = {"count": 0}

    def fail_project_cache(self, *args, **kwargs):
        calls["count"] += 1
        if self.project_root:
            raise PermissionError("project cache is read-only")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        "tech_connector.services.unreal.animation_knowledge_continuation_service.AutonomousKnowledgeRetrievalEngine.build_acquisition_plan",
        fail_project_cache,
    )

    result = build_animation_knowledge_continuation(
        _prior()["plan"],
        "add_knowledge_first",
        settings={
            "active_project": "Z:/readonly/project",
            "enable_live_sources": False,
            "research_web_techniques": False,
        },
    )

    assert calls["count"] == 2
    assert result["local_knowledge"]["warnings"] == ["project cache is read-only"]
