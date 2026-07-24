from __future__ import annotations

from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine


def _knowledge_metadata() -> dict:
    return {
        "result_type": "unreal_animation_knowledge_continuation",
        "knowledge_result": {
            "request": "Build a ledge hang animation system.",
            "target_asset": "/Game/Characters/BP_Player",
            "target_mesh": "/Game/Characters/SK_Player",
            "animation_roles": ["climb_hang"],
            "online_allowed": True,
        },
        "plan": {"target_asset": "/Game/Characters/BP_Player"},
    }


def _candidate_research() -> dict:
    return {
        "status": "online_candidates_found",
        "request": "Build a ledge hang animation system.",
        "roles": ["climb_hang"],
        "covered_roles": ["climb_hang"],
        "missing_roles": [],
        "candidates": [
            {
                "clip_id": "01_03",
                "description": "climb and hang",
                "matched_roles": ["climb_hang"],
                "preview_url": "https://example.org/preview.avi",
            }
        ],
        "completion_allowed": False,
    }


def test_research_online_choice_executes_bound_provider_search(monkeypatch) -> None:
    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.search_open_animation_candidates",
        lambda request, roles: _candidate_research(),
    )
    result = RequestEngine().process(
        RequestContext(
            text="research_online",
            extras={
                "prior_result_metadata": _knowledge_metadata(),
                "clarification_binding": {"values": {"knowledge_next_action": "research_online"}},
            },
        )
    )

    assert result.action == "clarify"
    assert result.metadata["result_type"] == "unreal_animation_candidate_research"
    assert result.metadata["candidate_research"]["candidates"][0]["clip_id"] == "01_03"
    assert result.metadata["ui_controls"][0]["recommended_choice"] == "download_recommended_open_matches"
    assert not result.metadata["completion_allowed"]


def test_download_choice_writes_then_requests_live_target_skeleton(tmp_path, monkeypatch) -> None:
    download = {
        "status": "downloaded_for_retarget_handoff",
        "cache_root": str(tmp_path / "ArtSource"),
        "role_downloads": {"climb_hang": {"download": {"ok": True, "local_path": "clip.fbx", "bytes": 12}}},
        "missing_roles": [],
        "failed_roles": [],
        "requires_target_skeleton_selection": True,
        "completion_allowed": False,
    }
    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.download_recommended_open_animation_candidates",
        lambda research, project_root: download,
    )
    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.discover_live_retarget_target_options",
        lambda **kwargs: {
            "ok": True,
            "default_target_skeleton": "/Game/Characters/SK_PlayerSkeleton",
            "options": [
                {
                    "skeleton": "/Game/Characters/SK_PlayerSkeleton",
                    "exists": True,
                    "skeletal_meshes": ["/Game/Characters/SK_Player"],
                }
            ],
        },
    )
    prior = {
        "result_type": "unreal_animation_candidate_research",
        "candidate_research": _candidate_research(),
        "knowledge_result": _knowledge_metadata()["knowledge_result"],
        "plan": _knowledge_metadata()["plan"],
    }
    result = RequestEngine().process(
        RequestContext(
            text="download_recommended_open_matches",
            extras={
                "prior_result_metadata": prior,
                "clarification_binding": {
                    "values": {"animation_candidate_action": "download_recommended_open_matches"}
                },
                "settings": {"active_project": str(tmp_path)},
            },
        )
    )

    assert result.action == "clarify"
    assert result.metadata["result_type"] == "unreal_animation_retarget_target_selection"
    assert result.metadata["ui_controls"][0]["slot"] == "target_skeleton"
    assert result.metadata["ui_controls"][0]["recommended_choice"] == "/Game/Characters/SK_PlayerSkeleton"
    assert not result.metadata["completion_allowed"]


def test_download_choice_without_project_root_fails_before_download(monkeypatch) -> None:
    called = {"download": False}

    def unexpected_download(*args, **kwargs):
        called["download"] = True
        return {}

    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.download_recommended_open_animation_candidates",
        unexpected_download,
    )
    prior = {
        "result_type": "unreal_animation_candidate_research",
        "candidate_research": _candidate_research(),
    }
    result = RequestEngine().process(
        RequestContext(
            text="download_recommended_open_matches",
            extras={
                "prior_result_metadata": prior,
                "clarification_binding": {
                    "values": {"animation_candidate_action": "download_recommended_open_matches"}
                },
            },
        )
    )

    assert result.action == "error"
    assert not called["download"]


def test_target_skeleton_followup_executes_retarget_import_handoff(tmp_path, monkeypatch) -> None:
    observed = {}

    def execute(**kwargs):
        observed.update(kwargs)
        return {
            "ok": True,
            "status": "imported_pending_contextual_preview",
            "target_skeleton": kwargs["target_skeleton"],
            "target_mesh": "/Game/Characters/SKM_Player",
            "rows": [],
            "completion_allowed": False,
        }

    monkeypatch.setattr(
        "tech_connector.services.unreal.animation_asset_pipeline_service.execute_animation_retarget_import_handoff",
        execute,
    )
    prior = {
        "result_type": "unreal_animation_retarget_target_selection",
        "download_result": {"role_downloads": {"climb_hang": {}}},
        "target_options": {"options": []},
    }
    result = RequestEngine().process(
        RequestContext(
            text="/Game/Characters/SK_PlayerSkeleton",
            extras={
                "prior_result_metadata": prior,
                "clarification_binding": {
                    "values": {"target_skeleton": "/Game/Characters/SK_PlayerSkeleton"}
                },
                "settings": {"active_project": str(tmp_path)},
            },
        )
    )

    assert result.action == "answer"
    assert observed["target_skeleton"] == "/Game/Characters/SK_PlayerSkeleton"
    assert result.metadata["result_type"] == "unreal_animation_imported_pending_context"
    assert not result.metadata["completion_allowed"]
