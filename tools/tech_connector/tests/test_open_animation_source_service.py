from __future__ import annotations

from tech_connector.services.unreal.open_animation_source_service import (
    download_recommended_open_animation_candidates,
    enrich_plan_with_automatic_open_animation_research,
    parse_cmu_fbx_metadata_csv,
    parse_cmu_motion_results,
    resolve_open_animation_candidate_action,
    search_open_animation_candidates,
)


CMU_FIXTURE = """
<table>
<tr><td>Subject #1 (climb and hang)</td><td><a href="/subjects/01/01.asf">asf</a></td></tr>
<tr><td></td><td>3</td><td>playground - climb, hang, swing</td>
<td><a href="/subjects/01/01_03.amc">amc</a></td>
<td><a href="/subjects/01/01_03.avi">Animated</a></td></tr>
<tr><td></td><td>4</td><td>walk forward</td>
<td><a href="/subjects/01/01_04.amc">amc</a></td></tr>
</table>
"""


def test_parser_preserves_subject_skeleton_and_trial_download_identity() -> None:
    rows = parse_cmu_motion_results(CMU_FIXTURE)

    assert rows[0]["clip_id"] == "01_03"
    assert rows[0]["skeleton_url"].endswith("/subjects/01/01.asf")
    assert rows[0]["amc_url"].endswith("/subjects/01/01_03.amc")
    assert rows[0]["download_url"].endswith("/animations/01_03.fbx")


def test_metadata_parser_builds_direct_fbx_identity() -> None:
    rows = parse_cmu_fbx_metadata_csv(
        'file_name,description,dataset_type="cmu",root_node_name="hip"\n'
        '01_03.fbx,"playground - climb, hang, swing",cmu,hip\n'
    )

    assert rows == [
        {
            "clip_id": "01_03",
            "subject_id": "01",
            "trial_id": "03",
            "description": "playground - climb, hang, swing",
            "skeleton_url": "",
            "amc_url": "",
            "preview_url": "",
            "download_url": "https://huggingface.co/datasets/gbionics/cmu-fbx/resolve/main/animations/01_03.fbx",
        }
    ]


def test_search_keeps_contextual_match_and_rejects_unrelated_motion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.register_open_knowledge_sources",
        lambda *args, **kwargs: {"added": [], "updated": [], "rejected": [], "total": 0},
    )

    result = search_open_animation_candidates(
        "Add a ledge hang",
        ["climb_hang"],
        fetcher=lambda term, timeout: CMU_FIXTURE,
    )

    assert result["status"] == "online_candidates_found"
    assert result["covered_roles"] == ["climb_hang"]
    assert result["missing_roles"] == []
    assert [row["clip_id"] for row in result["candidates"]] == ["01_03"]
    assert result["candidates"][0]["requires_retarget"]


def test_jump_down_is_not_a_ledge_to_ledge_back_jump(monkeypatch) -> None:
    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.register_open_knowledge_sources",
        lambda *args, **kwargs: {"added": [], "updated": [], "rejected": [], "total": 0},
    )

    result = search_open_animation_candidates(
        "Jump backward from a ledge to another ledge",
        ["ledge_back_jump"],
        fetcher=lambda term, timeout: CMU_FIXTURE.replace(
            "playground - climb, hang, swing",
            "playground - climb, hang, jump down",
        ),
    )

    assert result["candidates"] == []
    assert result["missing_roles"] == ["ledge_back_jump"]


def test_candidate_action_is_bound_to_research_result() -> None:
    prior = {"result_type": "unreal_animation_candidate_research"}
    binding = {"values": {"animation_candidate_action": "download_recommended_open_matches"}}

    assert resolve_open_animation_candidate_action("", prior, binding) == "download_recommended_open_matches"
    assert resolve_open_animation_candidate_action("download_recommended_open_matches", {}, binding) == ""


def test_recommended_download_deduplicates_clip_used_by_multiple_roles(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_download(candidate, cache_root, **kwargs):
        calls.append((candidate, cache_root, kwargs))
        return {"ok": True, "local_path": str(cache_root / "clip.fbx")}

    monkeypatch.setattr(
        "tech_connector.services.unreal.open_animation_source_service.download_asset_candidate",
        fake_download,
    )
    candidate = {
        "clip_id": "01_11",
        "download_url": "https://example.org/01_11.fbx",
        "matched_roles": ["climb_hang", "ledge_back_jump"],
        "semantic_evidence": {"climb_hang": {"accepted": True}, "ledge_back_jump": {"accepted": True}},
    }
    result = download_recommended_open_animation_candidates(
        {"candidates": [candidate], "missing_roles": []},
        tmp_path,
    )

    assert result["status"] == "downloaded_for_retarget_handoff"
    assert len(calls) == 1
    assert calls[0][0]["semantic_candidate_accepted_for_download"] is True
    assert calls[0][0]["contextual_preview_status"] == "pending"
    assert calls[0][0].get("contextually_usable") is not True
    assert set(result["role_downloads"]) == {"climb_hang", "ledge_back_jump"}
    assert result["requires_target_skeleton_selection"]


def test_automatic_research_does_not_search_when_local_role_is_covered() -> None:
    calls = []
    plan = {
        "request": "Build a climbing loop",
        "animation_roles": ["climb_loop"],
        "animation_role_assessment": [
            {
                "role": "climb_loop",
                "semantic_candidates": [
                    {
                        "candidate": {
                            "path": "/Game/Animation/A_ClimbLoop",
                            "source": "asset_registry",
                        },
                        "evaluation": {"accepted": True},
                    }
                ],
            }
        ],
    }

    result = enrich_plan_with_automatic_open_animation_research(
        plan,
        searcher=lambda request, roles: calls.append((request, roles)),
    )

    assert calls == []
    assert result["automatic_animation_asset_research"]["status"] == "local_candidates_available"
    assert result.get("missing_capabilities") is None


def test_automatic_research_searches_missing_roles_but_keeps_plan_blocked() -> None:
    calls = []

    def search(request, roles):
        calls.append((request, roles))
        return {
            "status": "online_candidates_found",
            "roles": roles,
            "candidates": [{"clip_id": "01_03", "matched_roles": roles}],
            "covered_roles": roles,
            "missing_roles": [],
            "completion_allowed": False,
        }

    result = enrich_plan_with_automatic_open_animation_research(
        {
            "status": "approval_ready",
            "request": "Build a ledge hang",
            "animation_roles": ["climb_hang"],
            "build_readiness": {"ready_to_execute": True, "blocked_by": []},
        },
        searcher=search,
    )

    assert calls == [("Build a ledge hang", ["climb_hang"])]
    assert result["status"] == "capability_acquisition_required"
    assert not result["build_readiness"]["ready_to_execute"]
    assert "animation.acquire_contextual_role_assets" in result["build_readiness"]["blocked_by"]
    assert result["automatic_animation_asset_research"]["policy"]["automatic_sources"] == "public_open_only"
    assert not result["automatic_animation_asset_research"]["completion_allowed"]
