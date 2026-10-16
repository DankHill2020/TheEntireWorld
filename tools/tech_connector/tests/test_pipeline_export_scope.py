from __future__ import annotations

import pytest

from tech_connector.game_engine.integration.pipeline_operation_runtime_service import (
    resolve_pipeline_context_params,
)


def _context(scope: str = "rig_contents") -> dict[str, str]:
    return {
        "$pipeline_context": "dcc_export_scope_v1",
        "host": "blender",
        "scope": scope,
        "subject": "character",
        "label": "the character rig, skinned meshes, and children",
    }


def test_export_scope_marker_resolves_immediately_before_dispatch() -> None:
    seen: list[dict[str, str]] = []

    params = resolve_pipeline_context_params(
        {"selection": _context(), "settings": {"bake_animation": True}},
        host="blender",
        context_reader=lambda spec: seen.append(spec) or ["Character_Rig", "Body_Mesh"],
    )

    assert params == {
        "selection": ["Character_Rig", "Body_Mesh"],
        "settings": {"bake_animation": True},
    }
    assert seen[0]["scope"] == "rig_contents"


def test_empty_automatic_export_scope_fails_clearly() -> None:
    with pytest.raises(RuntimeError, match="resolved no objects"):
        resolve_pipeline_context_params(
            {"selection": _context("current_selection")},
            host="blender",
            context_reader=lambda _spec: [],
        )


def test_general_function_context_resolves_single_active_object() -> None:
    marker = {
        "$pipeline_context": "dcc_input_context_v1",
        "host": "blender",
        "context_kind": "active_object",
        "input": "target",
        "multiple": False,
        "label": "Active object",
    }
    seen: list[dict[str, object]] = []
    params = resolve_pipeline_context_params(
        {"target": marker, "strength": 0.5},
        host="blender",
        context_reader=lambda spec: seen.append(spec) or ["HeroBody"],
    )
    assert params == {"target": "HeroBody", "strength": 0.5}
    assert seen[0]["scope"] == "active_object"
