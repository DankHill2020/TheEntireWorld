from __future__ import annotations

from types import SimpleNamespace

from tech_connector.bridges.unreal.unreal_blueprint_inspection import _resolve_blueprint_path
from tech_connector.services.unreal.feature_planning_service import is_unreal_feature_plan_request
from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine


class _FakeClass:
    def __init__(self, name: str, path: str):
        self._name = name
        self._path = path

    def get_name(self):
        return self._name

    def get_path_name(self):
        return self._path


class _FakeAsset:
    def get_class(self):
        return _FakeClass("Blueprint", "/Script/Engine.Blueprint")

    def get_path_name(self):
        return "/Game/Characters/BP_SelectedCharacter.BP_SelectedCharacter"


def test_blank_target_resolves_single_selected_character_blueprint() -> None:
    unreal = SimpleNamespace(
        EditorUtilityLibrary=SimpleNamespace(get_selected_assets=lambda: [_FakeAsset()]),
        EditorLevelLibrary=SimpleNamespace(
            get_selected_level_actors=lambda: [],
            get_editor_world=lambda: None,
        ),
    )

    assert _resolve_blueprint_path(unreal, "") == "/Game/Characters/BP_SelectedCharacter"


def test_complex_live_feature_does_not_require_literal_bp_name() -> None:
    prompt = (
        "In the live Unreal project, build a playable ledge traversal animation system. "
        "Resolve the character Blueprint from live project evidence. Search project assets, "
        "acquire missing contextual animations, retarget, import, integrate, compile, and run "
        "PIE verification. The system must validate graph connections, asset bindings, runtime "
        "state transitions, and observed animation playback before reporting success. " * 3
    )

    assert is_unreal_feature_plan_request(prompt)


def test_ui_engine_surfaces_partial_sight_as_knowledge_choice(monkeypatch) -> None:
    prompt = (
        "In the live Unreal project, build a playable ledge traversal animation system. "
        "Resolve the character Blueprint from live project evidence. " * 8
    )
    plan = {
        "status": "knowledge_choice_required",
        "framework": "unreal_generic_feature_plan_v2",
        "target_asset": "/Game/Characters/BP_SelectedCharacter",
        "detected_domains": ["external_assets", "knowledge_gap"],
        "missing_capabilities": [{"capability": "external.asset_source_search"}],
        "knowledge_choice": {
            "recommended": "add_knowledge_first",
            "options": ["add_knowledge_first", "run_with_current_knowledge"],
        },
        "evidence": {},
    }
    monkeypatch.setattr(
        "tech_connector.services.unreal.feature_planning_service.build_live_unreal_feature_plan",
        lambda *_args, **_kwargs: plan,
    )

    result = RequestEngine(progress=lambda _event: None).process(
        RequestContext(text=prompt, extras={"host_hint": "unreal"})
    )

    assert result.action == "clarify"
    assert result.metadata["result_type"] == "unreal_feature_knowledge_choice"
    assert result.metadata["confirmation_request"]["recommended"] == "add_knowledge_first"
    assert result.metadata["pending_clarification"]["unresolved_slots"][0]["name"] == "knowledge_strategy"
    assert result.metadata["ui_controls"][0]["recommended_choice"] == "add_knowledge_first"
