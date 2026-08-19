"""Product-level regression tests for the visible code-agent workflow."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.services.code_prompt_profile_service import (
    apply_code_prompt_profile_to_decision,
    normalize_code_prompt_profile,
    openai_execution_options,
    preferred_openai_model,
    render_code_prompt_contract,
)
from tech_connector.services.llm_router_service import _query_openai
from tech_connector.services.project_edit_prompt_policy_service import (
    build_project_edit_task_envelope,
    compact_project_edit_system_prompt,
)
from tech_connector.services.provider_model_catalog_service import (
    discover_provider_models,
    prefixed_catalog,
)
from tech_connector.ui.game_engine.unreal_editor_dialogs import EditorDiffWidget


def _application() -> QApplication:
    """Return the shared Qt application.

    :return: Active QApplication.
    """

    return QApplication.instance() or QApplication([])


def test_read_only_modes_override_stale_mutation_permission() -> None:
    profile = normalize_code_prompt_profile(
        {"mode": "review", "permission": "automatic_safe", "depth": "deep"}
    )

    assert profile.permission == "read_only"
    assert openai_execution_options(profile)["reasoning_effort"] == "high"
    assert "Do not modify" in render_code_prompt_contract(profile)


def test_depth_presets_map_to_distinct_openai_models_and_effort() -> None:
    assert preferred_openai_model("fast") == "gpt-5.6-luna"
    assert preferred_openai_model("balanced") == "gpt-5.6-terra"
    assert preferred_openai_model("maximum") == "gpt-5.6-sol"
    maximum = openai_execution_options({"depth": "maximum"})
    assert maximum["reasoning_effort"] == "max"
    assert maximum["reasoning_mode"] == "pro"


def test_explicit_edit_mode_promotes_search_route_to_target_discovery() -> None:
    decision = SimpleNamespace(
        route="project_search",
        provider="project_search",
        execution_route="engine.project_search",
        handler_id="ProjectSearchHandler",
        mutation_scope="read_only",
        requires_confirmation=False,
        can_execute_directly=False,
        requires_execution=False,
        requires_generation=False,
        requires_validation=False,
        requires_plan=False,
        goal_type="explain",
        required_context=[],
        selected_route_reason="",
        user_prompt_preferences={},
    )

    apply_code_prompt_profile_to_decision(
        decision,
        {"mode": "edit", "permission": "preview", "scope": "project"},
    )

    assert decision.route == "target_discovery"
    assert decision.provider == "target_discovery"
    assert decision.requires_confirmation is True
    assert "project_index" in decision.required_context


def test_explicit_plan_mode_demotes_mutation_route_to_read_only_search() -> None:
    decision = SimpleNamespace(
        route="target_discovery",
        provider="target_discovery",
        execution_route="engine.target_discovery",
        handler_id="TargetDiscoveryHandler",
        mutation_scope="project_code_mutation",
        requires_confirmation=True,
        can_execute_directly=True,
        requires_execution=True,
        requires_generation=True,
        requires_validation=False,
        requires_plan=False,
        goal_type="edit",
        required_context=[],
        selected_route_reason="",
        user_prompt_preferences={},
    )

    apply_code_prompt_profile_to_decision(decision, {"mode": "plan"})

    assert decision.route == "project_search"
    assert decision.provider == "project_search"
    assert decision.mutation_scope == "read_only"
    assert decision.requires_execution is False
    assert decision.requires_plan is True


def test_project_edit_prompt_policy_deduplicates_and_reports_size() -> None:
    compacted, metrics = compact_project_edit_system_prompt(
        "Do not invent APIs.\nDo not invent APIs.\nReturn JSON."
    )
    envelope, user_metrics = build_project_edit_task_envelope(
        stage_key="generation",
        stage_label="Generate candidate",
        user_prompt="Use evidence.\nUse evidence.",
        metadata={"path": "sample.py"},
    )

    assert compacted.count("Do not invent APIs.") == 1
    assert metrics["system_chars_after"] > 0
    assert "Owner: sample.py" in envelope
    assert envelope.count("Use evidence.") == 1
    assert user_metrics["user_chars_before"] > 0


def test_provider_catalog_discovers_normalizes_and_prefixes_models() -> None:
    with patch(
        "tech_connector.services.provider_model_catalog_service._request_json",
        return_value={"data": [{"id": "gpt-z"}, {"id": "gpt-a"}, {"id": "gpt-z"}]},
    ) as request_json:
        models = discover_provider_models(
            "openai", api_key="secret", refresh=True
        )

    assert models == ("gpt-a", "gpt-z")
    assert prefixed_catalog("openai", models) == (
        "openai:gpt-a",
        "openai:gpt-z",
    )
    assert request_json.call_args.args[0].endswith("/v1/models")


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _Opener:
    def __init__(self) -> None:
        self.request = None

    def open(self, request, timeout=0):
        self.request = request
        return _Response(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ]
            }
        )


def test_openai_adapter_uses_responses_reasoning_and_structured_output() -> None:
    opener = _Opener()
    with patch("urllib.request.build_opener", return_value=opener):
        result = _query_openai(
            "gpt-5.6-sol",
            "secret",
            "implement it",
            "follow the contract",
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            {
                "reasoning_effort": "high",
                "reasoning_context": "all_turns",
                "reasoning_mode": "pro",
                "verbosity": "medium",
                "store": True,
                "temperature": 0.8,
            },
        )

    payload = json.loads(opener.request.data.decode("utf-8"))
    assert opener.request.full_url.endswith("/v1/responses")
    assert result == "done"
    assert payload["instructions"] == "follow the contract"
    assert payload["reasoning"] == {
        "effort": "high",
        "context": "all_turns",
        "mode": "pro",
    }
    assert payload["text"]["verbosity"] == "medium"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert "temperature" not in payload


def test_diff_review_can_exclude_files_and_hunks() -> None:
    _application()
    widget = EditorDiffWidget()
    widget.set_changes(
        [
            {
                "path": "first.py",
                "action": "modify",
                "original_content": "VALUE = 1\nKEEP = True\n",
                "new_content": "VALUE = 2\nKEEP = True\nADDED = 3\n",
            },
            {
                "path": "second.py",
                "action": "create",
                "original_content": "",
                "new_content": "READY = True\n",
            },
        ]
    )

    assert widget.hunk_list.count() == 2
    widget.hunk_list.item(1).setCheckState(Qt.Unchecked)
    assert "ADDED = 3" not in widget.pending_changes["first.py"]["current"]
    widget.file_selector.setCurrentIndex(1)
    widget.include_file_checkbox.setChecked(False)
    captured = []
    widget.accepted_all.connect(captured.append)
    widget.on_accept()

    assert list(captured[0]) == ["first.py"]
