"""Canonical UI prompt-to-pipeline resolution.

Both Pipeline View and audits use this service so routing, understanding
validation, action planning, and workflow materialization cannot drift.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from tech_connector.services.action_planner_service import (
    plan_prompt_to_action_graph,
    workflow_plan_from_action_graph,
)
from tech_connector.services.prompt.prompt_execution_context_service import (
    build_prompt_execution_context,
    validate_prompt_understanding,
)
from tech_connector.services.prompt.prompt_route_service import classify_prompt_route


def resolve_pipeline_prompt_flow(
    prompt: str,
    project_roots: list[str] | None = None,
    *,
    host_hint: str = "cross_dcc",
    decision_facts: dict[str, Any] | None = None,
    progress_callback=None,
) -> dict[str, Any]:
    """Resolve one full UI prompt into a validated, materializable pipeline."""
    original_prompt = str(prompt or "").strip()
    roots = [str(root) for root in (project_roots or []) if str(root).strip()]
    timings: dict[str, float] = {}
    progress_events: list[dict[str, Any]] = []
    total_started = perf_counter()

    def emit(state: str, label: str, status: str, **details: Any) -> None:
        event = {
            "index": len(progress_events) + 1,
            "state": state,
            "label": label,
            "status": status,
            "elapsed_ms": round((perf_counter() - total_started) * 1000.0, 3),
            "details": details,
        }
        progress_events.append(event)
        if callable(progress_callback):
            try:
                progress_callback(dict(event))
            except Exception:
                pass

    emit("REQUEST_RECEIVED", "Request received", "complete", prompt=original_prompt)

    started = perf_counter()
    emit("CONTEXT_GATHERING", "Gathering project and host context", "running")
    execution_context = build_prompt_execution_context(
        original_prompt,
        host_hint=host_hint,
        decision_facts={
            "project_roots": roots,
            **dict(decision_facts or {}),
        },
        fast_preview=True,
        semantic_understanding=bool(
            (
                (decision_facts or {}).get("planning_preferences") or {}
            ).get("semantic_understanding", False)
        ),
    )
    timings["context_build_ms"] = (perf_counter() - started) * 1000.0
    emit(
        "CONTEXT_GATHERING",
        "Project and host context ready",
        "complete",
        host_hint=host_hint,
        project_roots=roots,
    )

    started = perf_counter()
    emit("UNDERSTANDING_VALIDATION", "Checking request understanding", "running")
    understanding = validate_prompt_understanding(execution_context)
    timings["understanding_validation_ms"] = (perf_counter() - started) * 1000.0
    emit(
        "UNDERSTANDING_VALIDATION",
        "Request understanding checked",
        "complete" if understanding.valid else "blocked",
        valid=bool(understanding.valid),
        reasons=list(understanding.reasons or []),
    )

    started = perf_counter()
    emit("INTENT_CLASSIFIED", "Selecting execution route", "running")
    route_decision = classify_prompt_route(
        original_prompt,
        project_roots=roots,
        execution_context=execution_context,
    )
    decision_data = route_decision.to_dict()
    execution_context.attach_execution_decision(decision_data)
    timings["route_classification_ms"] = (perf_counter() - started) * 1000.0
    emit(
        "INTENT_CLASSIFIED",
        "Execution route selected",
        "complete",
        route=route_decision.route,
        host=(
            host_hint
            if route_decision.route in {"pipeline_graph", "action_graph"} and host_hint == "cross_dcc"
            else decision_data.get("host") or host_hint
        ),
        confidence=decision_data.get("confidence"),
    )

    action_graph: dict[str, Any] = {}
    workflow_plan: dict[str, Any] | None = None
    if route_decision.route in {"pipeline_graph", "action_graph"}:
        from tech_connector.services.dcc.pipeline_requirement_coverage_service import (
            build_pipeline_requirement_manifest,
        )

        requirement_manifest = build_pipeline_requirement_manifest(original_prompt)
        planning_preferences = dict(
            (decision_facts or {}).get("planning_preferences") or {}
        )
        planning_preferences["requirement_manifest"] = requirement_manifest
        started = perf_counter()
        emit("ACTION_PLANNING", "Resolving operations and dependencies", "running")
        action_graph = plan_prompt_to_action_graph(
            original_prompt,
            roots,
            planning_preferences=planning_preferences,
        )
        timings["action_planning_ms"] = (perf_counter() - started) * 1000.0
        emit(
            "ACTION_PLANNING",
            "Operations and dependencies resolved",
            "blocked" if action_graph.get("capability_gaps") else "complete",
            intent=action_graph.get("intent"),
            action_count=len(action_graph.get("actions") or []),
            diagnostics=list(action_graph.get("diagnostics") or []),
            capability_gaps=list(action_graph.get("capability_gaps") or []),
        )

        if (
            action_graph.get("framework") == "dynamic_typed_pipeline_v1"
            and planning_preferences.get("semantic_verification", False)
            and not action_graph.get("required_inputs")
            and not action_graph.get("capability_gaps")
        ):
            started = perf_counter()
            emit(
                "PLAN_ALIGNMENT",
                "Verifying every requested requirement",
                "running",
                requirement_count=(
                    action_graph.get("requirement_ledger") or {}
                ).get("requirement_count", 0),
            )
            from tech_connector.services.dcc.pipeline_requirement_coverage_service import (
                verify_pipeline_requirement_ledger,
            )

            requirement_verification = verify_pipeline_requirement_ledger(
                original_prompt,
                list(action_graph.get("stages") or []),
                requirement_manifest=requirement_manifest,
            )
            action_graph["requirement_verification"] = requirement_verification
            timings["plan_alignment_ms"] = (perf_counter() - started) * 1000.0
            verdict = dict(
                requirement_verification.get("semantic_verdict") or {}
            )
            if (
                requirement_verification.get("verification_available")
                and not requirement_verification.get("matches_request")
            ):
                action_graph.setdefault("capability_gaps", []).extend(
                    {
                        "kind": "uncovered_prompt_requirement",
                        "request_fragment": item.get("request_fragment") or "",
                        "reason": item.get("reason") or "",
                        "required_capability": item.get("required_capability") or "",
                    }
                    for item in verdict.get("missing") or []
                )
            elif not requirement_verification.get("verification_available"):
                action_graph.setdefault("capability_gaps", []).append(
                    {
                        "kind": "requirement_verification_unavailable",
                        "request_fragment": original_prompt,
                        "reason": (
                            "The bounded semantic requirement verifier was unavailable, "
                            "so the UI will not claim that every prompt clause is covered."
                        ),
                        "required_capability": "semantic_plan_critic",
                    }
                )
            emit(
                "PLAN_ALIGNMENT",
                "Requirement verification complete",
                (
                    "complete"
                    if requirement_verification.get("matches_request")
                    else "blocked"
                    if requirement_verification.get("verification_available")
                    else "unavailable"
                ),
                matches_request=requirement_verification.get("matches_request"),
                verifier_tier=verdict.get("verifier_tier"),
                elapsed_ms=verdict.get("elapsed_ms"),
                missing=list(verdict.get("missing") or []),
            )
        elif (
            action_graph.get("framework") == "dynamic_typed_pipeline_v1"
            and planning_preferences.get("semantic_verification", False)
            and (
                action_graph.get("required_inputs")
                or action_graph.get("capability_gaps")
            )
        ):
            emit(
                "PLAN_ALIGNMENT",
                (
                    "Requirement verification deferred until capability acquisition completes"
                    if action_graph.get("capability_gaps")
                    else "Requirement verification deferred until required values are supplied"
                ),
                "blocked",
                unresolved_inputs=list(action_graph.get("required_inputs") or []),
                capability_gaps=list(action_graph.get("capability_gaps") or []),
            )

        started = perf_counter()
        emit("WORKFLOW_MATERIALIZATION", "Building nodes and data links", "running")
        workflow_plan = workflow_plan_from_action_graph(action_graph)
        timings["workflow_materialization_ms"] = (perf_counter() - started) * 1000.0
        emit(
            "WORKFLOW_MATERIALIZATION",
            "Pipeline graph ready",
            "complete" if workflow_plan and workflow_plan.get("success") else "blocked",
            node_count=len((workflow_plan or {}).get("steps") or []),
            data_link_count=len((workflow_plan or {}).get("data_links") or []),
            flow_link_count=len((workflow_plan or {}).get("flow_links") or []),
            unresolved_inputs=list((workflow_plan or {}).get("unresolved_inputs") or []),
        )

    timings["total_ms"] = (perf_counter() - total_started) * 1000.0
    ok = bool(understanding.valid and workflow_plan and workflow_plan.get("success"))
    emit(
        "READY",
        "Ready to execute" if ok else "Pipeline needs attention",
        "complete" if ok else "blocked",
        total_ms=round(timings["total_ms"], 3),
    )
    return {
        "schema": "pipeline_prompt_flow_v1",
        "original_prompt": original_prompt,
        "normalized_prompt": execution_context.normalized_prompt,
        "execution_context": execution_context.to_dict(),
        "understanding_validation": understanding.to_dict(),
        "route_decision": decision_data,
        "action_graph": action_graph,
        "workflow_plan": workflow_plan,
        "progress_events": progress_events,
        "timings": {key: round(value, 3) for key, value in timings.items()},
        "ok": ok,
    }
