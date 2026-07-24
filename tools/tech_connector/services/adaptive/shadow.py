from __future__ import annotations

"""Convenience facade for running Milestone A beside the current request path."""

from typing import Any

from tech_connector.services.adaptive.stage_scheduler import AdaptiveStageScheduler
from tech_connector.services.adaptive.stages import default_shadow_stages
from tech_connector.services.reasoning.request_prediction_service import build_shadow_execution_state


def analyze_request_shadow(
    prompt: str,
    route_decision: dict[str, Any] | Any | None,
    *,
    active_file: str = "",
    project_roots: list[str] | tuple[str, ...] = (),
    operation_memory: dict[str, Any] | None = None,
    similar_execution_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = build_shadow_execution_state(
        prompt,
        route_decision,
        active_file=active_file,
        project_roots=project_roots,
        operation_memory=operation_memory,
        similar_execution_history=similar_execution_history,
    )
    scheduler = AdaptiveStageScheduler(default_shadow_stages())
    result = scheduler.run(state, shadow_mode=True)
    return result.to_dict()
