from __future__ import annotations

"""Integration helpers for target discovery, project search, and request routing."""

from typing import Any, Iterable

from services.project_validation_intent_service import classify_validation_intent, run_validation_intent
from services.target_resolution_service import apply_resolution_to_state, resolve_target_candidates


def resolve_project_edit_target(
    state: Any,
    candidates: Iterable[dict[str, Any] | str],
    *,
    open_files: Iterable[str] = (),
) -> dict[str, Any]:
    resolution = resolve_target_candidates(
        state.original_prompt,
        candidates,
        active_file=state.active_file,
        open_files=open_files,
        operation_memory=state.operation_memory,
        allowed_roots=state.project_roots,
    )
    apply_resolution_to_state(state, resolution)
    return resolution.to_dict()


def deterministic_pre_route(state: Any) -> dict[str, Any]:
    """Handle evidence-producing intents before generic search/model routing."""
    validation_intent = classify_validation_intent(state.original_prompt)
    if validation_intent is not None:
        result = run_validation_intent(
            validation_intent,
            project_roots=state.project_roots,
            active_file=state.active_file,
        )
        state.artifacts["deterministic_validation_result"] = result
        state.route = "project_validation"
        state.provider = "python_ast"
        state.completed_stages.append("project_validation_intent")
        state.confidence.update("intent", max(0.0, validation_intent.confidence - state.confidence.intent), reason=validation_intent.reason, source="project_validation_intent")
        state.confidence.update("validation", 0.9 if result.get("issues") else 0.85, reason="Deterministic project syntax scan completed", source="python_ast")
        return {"handled": True, "route": state.route, "result": result}
    return {"handled": False}
