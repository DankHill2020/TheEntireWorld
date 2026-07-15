"""Visible prompt progress contracts for every routed request.

This service describes observable work only. It does not expose hidden model
reasoning; it names the expert lens, the evidence being gathered, the stop
condition, and the handoff each stage should produce for the next stage.
"""

from __future__ import annotations

from typing import Any


BASE_STAGES: tuple[dict[str, Any], ...] = (
    {
        "state": "REQUEST_RECEIVED",
        "label": "Request received",
        "expert_id": "prompt_router",
        "message": "Capture the user goal, thread context, and active project/tool state.",
        "stop_when": "The prompt has a normalized goal and the active context snapshot is attached.",
        "handoff": "normalized_goal",
    },
    {
        "state": "INTENT_CLASSIFIED",
        "label": "Intent classified",
        "expert_id": "prompt_router",
        "message": "Select the route, host, risk level, and whether this needs deterministic tools.",
        "stop_when": "A route decision has enough confidence or a clarification blocker is explicit.",
        "handoff": "route_decision",
    },
    {
        "state": "EXPERT_SELECTED",
        "label": "Expert context selected",
        "expert_id": "expert_coordinator",
        "message": "Choose the specialist lenses needed for this specific prompt.",
        "stop_when": "Required experts are selected and unrelated expert paths are excluded.",
        "handoff": "expert_plan",
    },
    {
        "state": "CONTEXT_GATHERING",
        "label": "Gathering focused context",
        "expert_id": "context_resolver",
        "message": "Collect only the files, graph facts, host state, thread facts, or operation schemas needed next.",
        "stop_when": "The next expert has enough verified evidence to act without broad guessing.",
        "handoff": "focused_context_package",
    },
    {
        "state": "KNOWLEDGE_CHECK",
        "label": "Checking known practices",
        "expert_id": "practice_advisor",
        "message": "Apply local playbooks, studio profile rules, and optionally request research if coverage is weak.",
        "stop_when": "A known-practice match, gap, or opt-in research recommendation is available.",
        "handoff": "practice_guidance",
    },
    {
        "state": "GAP_DISCOVERY",
        "label": "Discovering capability gaps",
        "expert_id": "gap_planner",
        "message": "Identify missing intermediate capabilities, possible detours, resolution options, and learning recommendations.",
        "stop_when": "Known capabilities, missing links, resolution candidates, and the recommended A-to-Z path are explicit.",
        "handoff": "capability_gap_plan",
    },
    {
        "state": "ACTION_PLANNING",
        "label": "Planning action",
        "expert_id": "technical_lead",
        "message": "Describe the intended edits/actions, validation gates, fallback, user-visible impact, and how the user can test the result.",
        "stop_when": "The plan has concrete actions, risks, validation, user test steps, and any required approval state.",
        "handoff": "action_plan",
    },
    {
        "state": "EXECUTION",
        "label": "Executing or drafting",
        "expert_id": "operator",
        "message": "Run deterministic tools, prepare the model request, or perform the approved edit.",
        "stop_when": "The requested operation finishes, blocks, or produces a model response.",
        "handoff": "execution_result",
    },
    {
        "state": "VALIDATION",
        "label": "Validating result",
        "expert_id": "validator",
        "message": "Check outputs, compile/test where possible, and identify remaining risk.",
        "stop_when": "Validation evidence or a clear reason validation could not run is recorded.",
        "handoff": "validation_report",
    },
    {
        "state": "REPORTING",
        "label": "Reporting back",
        "expert_id": "reporting_scribe",
        "message": "For quick actions, summarize completion. For multi-step work, provide a documentation-level breakdown of context, edits, validation, warnings, and outcome.",
        "stop_when": "The user has a clear outcome, exact edits/operations, verification evidence, user test guidance, and next available action.",
        "handoff": "user_report",
    },
)

FAILURE_STATES: tuple[dict[str, str], ...] = (
    {
        "state": "BLOCKED_MISSING_CONTEXT",
        "message": "Pause and ask for the minimum missing context needed to continue.",
    },
    {
        "state": "TOOL_FAILED",
        "message": "Report the failed tool, preserve partial findings, and offer a recovery path.",
    },
    {
        "state": "VALIDATION_FAILED",
        "message": "Keep the result visibly unresolved until the failed validation is fixed or accepted.",
    },
)


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _uniq(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: list[str] = []
    for value in values:
        item = _as_text(value)
        if item and item not in seen:
            seen.append(item)
    return seen


def _expert_lenses(decision: dict[str, Any]) -> list[dict[str, str]]:
    route = _as_text(decision.get("route"))
    provider = _as_text(decision.get("provider"))
    host = _as_text(decision.get("host"))
    intent = _as_text(decision.get("intent_category") or route)
    mutation = _as_text(decision.get("mutation_scope"))
    lenses: list[dict[str, str]] = [
        {
            "id": "prompt_router",
            "label": "Prompt Router",
            "reports": "Goal, route, confidence, host, and missing context.",
        },
        {
            "id": "context_resolver",
            "label": "Context Resolver",
            "reports": "Thread, project, file, graph, tool, and host state used for the answer.",
        },
    ]
    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"} or provider == "dcc":
        lenses.append(
            {
                "id": "dcc_technical_director",
                "label": "DCC Technical Director",
                "reports": "Host-specific operation path, scene impact, and DCC validation.",
            }
        )
    if host == "unreal" or "unreal" in route:
        lenses.append(
            {
                "id": "unreal_engineer",
                "label": "Unreal Engineer",
                "reports": "Asset, graph, Blueprint, C++/Python bridge, and editor safety context.",
            }
        )
    if route in {"pipeline_graph", "action_graph"} or "pipeline" in intent:
        lenses.append(
            {
                "id": "pipeline_engineer",
                "label": "Pipeline Engineer",
                "reports": "Data flow, node dependencies, validation gates, and execution order.",
            }
        )
    if route in {"project_health", "quality_audit", "project_search", "target_discovery"}:
        lenses.append(
            {
                "id": "code_quality_reviewer",
                "label": "Code Quality Reviewer",
                "reports": "Evidence-backed findings, file targets, tests, and residual risk.",
            }
        )
    if mutation and mutation != "read_only":
        lenses.append(
            {
                "id": "safety_validator",
                "label": "Safety Validator",
                "reports": "Mutation scope, approval needs, rollback/recovery, and validation state.",
            }
        )
    try:
        domain_experts = list(decision.get("domain_experts") or [])
        if not domain_experts:
            from services.domain_expert_service import select_domain_experts

            domain_experts = select_domain_experts(
                decision.get("prompt_preview") or decision.get("user_text") or "",
                decision,
                limit=4,
            )
        for expert in domain_experts[:4]:
            lenses.append(
                {
                    "id": str(expert.get("domain") or ""),
                    "label": str(expert.get("label") or expert.get("domain") or "Domain Expert"),
                    "reports": (
                        "Domain advisory: "
                        + "; ".join(str(item) for item in (expert.get("responsibilities") or [])[:2])
                    ).strip(),
                    "mode": str(expert.get("mode") or "observe"),
                }
            )
    except Exception:
        pass
    lenses.append(
        {
            "id": "reporting_scribe",
            "label": "Reporting Scribe",
            "reports": "User-facing status, final summary, changes, and verification evidence.",
        }
    )
    return lenses


def build_prompt_progress_plan(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the observable progress plan shared by every prompt path."""
    decision = dict(decision or {})
    try:
        from services.prompt_resource_orchestration_service import build_resource_orchestration_plan

        resource_plan = build_resource_orchestration_plan(prompt, decision)
    except Exception:
        resource_plan = {}
    try:
        from services.process_streamlining_service import build_process_streamlining_plan

        streamlining_plan = build_process_streamlining_plan(
            prompt,
            route=_as_text(decision.get("execution_route") or decision.get("route") or ""),
        ).to_dict()
    except Exception:
        streamlining_plan = {}
    route = _as_text(decision.get("route") or "chat")
    execution_route = _as_text(decision.get("execution_route") or route)
    host = _as_text(decision.get("host"))
    missing = _uniq(list(decision.get("missing_info") or []))
    requires_confirmation = bool(decision.get("requires_confirmation"))
    stages = []
    total = len(BASE_STAGES)
    for index, stage in enumerate(BASE_STAGES, start=1):
        item = dict(stage)
        item.update(
            {
                "index": index,
                "total": total,
                "percent": int(round((index / total) * 100)),
                "status": "pending",
                "early_exit": True,
                "handoff_required": True,
            }
        )
        if item["state"] == "EXECUTION" and requires_confirmation:
            item["message"] = "Hold execution until the user approves the planned mutation."
            item["stop_when"] = "The user approves, rejects, or asks for a revision."
            item["handoff"] = "approval_decision"
        stages.append(item)
    return {
        "framework": "visible_prompt_progress_v1",
        "enabled": True,
        "prompt_preview": (prompt or "")[:240],
        "route": route,
        "execution_route": execution_route,
        "host": host,
        "background_worker_required": True,
        "separate_os_thread_per_stage": False,
        "stage_model": "sequential_expert_handoffs_with_early_exit",
        "resource_model": resource_plan.get("framework", "resource_aware_prompt_orchestration_v1"),
        "resource_plan": resource_plan,
        "streamlining_model": streamlining_plan.get("framework", "process_streamlining_v1"),
        "streamlining_plan": streamlining_plan,
        "stop_policy": "Each expert stops as soon as it has enough verified evidence, emits its handoff, and the next expert consumes that handoff.",
        "handoff_policy": "Every stage must pass a compact observable handoff instead of hidden chain-of-thought.",
        "gap_policy": "Missing prerequisites become planning nodes. The planner should discover what produces each missing capability, rank resolution options, and recommend reusable knowledge updates after the workflow.",
        "ui_requirements": [
            "show current expert and stage in the status bar",
            "append compact activity cards for long-running work",
            "keep updating progress while context, model, tool, daemon, or validation work takes more than a few seconds",
            "keep the UI thread free while context gathering, model calls, tools, and validation run",
            "surface blocked, failed, and validation-failed states distinctly",
            "show planned actions and how-to-test notes before risky mutation",
            "for multi-step edits, report exact files/assets/graphs/functions changed and how they were validated",
        ],
        "expert_lenses": _expert_lenses({**decision, "prompt_preview": prompt}),
        "domain_experts": list(decision.get("domain_experts") or []),
        "stages": stages,
        "failure_states": list(FAILURE_STATES),
        "parallelizable_work": [
            "independent file/index searches",
            "read-only host snapshots",
            "best-practice lookup",
            "documentation/context retrieval",
        ],
        "serialized_work": [
            "route decision handoff",
            "mutating tool calls",
            "graph or file writes",
            "compile/save/validation",
            "final report",
        ],
        "missing_info": missing,
    }


def render_prompt_progress_plan(plan: dict[str, Any] | None, *, max_stages: int = 4) -> str:
    """Render a compact visible-work card for chat."""
    if not plan:
        return ""
    stages = list(plan.get("stages") or [])
    experts = list(plan.get("expert_lenses") or [])
    if not stages:
        return ""
    expert_labels = ", ".join(_as_text(expert.get("label")) for expert in experts[:4] if expert.get("label"))
    if len(experts) > 4:
        expert_labels += f", +{len(experts) - 4} more"
    lines = [
        "Visible work plan:",
        f"Route: {plan.get('execution_route') or plan.get('route') or 'chat'}",
        f"Experts: {expert_labels or 'Prompt Router, Context Resolver, Reporting Scribe'}",
        f"Stage model: {plan.get('stage_model', '')}",
        f"Stop rule: {plan.get('stop_policy', '')}",
    ]
    for stage in stages[:max_stages]:
        lines.append(
            f"- {stage.get('label', '')}: {stage.get('message', '')} "
            f"Stop: {stage.get('stop_when', '')}"
        )
    remaining = len(stages) - max_stages
    if remaining > 0:
        lines.append(f"- {remaining} later stage(s) continue in the background plan.")
    return "\n".join(lines)


def compact_prompt_progress_plan(plan: dict[str, Any] | None, *, max_stages: int = 5) -> dict[str, Any]:
    """Return a route-metadata friendly visible progress plan."""
    plan = dict(plan or {})
    return {
        "framework": plan.get("framework", "visible_prompt_progress_v1"),
        "enabled": bool(plan.get("enabled", True)),
        "route": plan.get("route", ""),
        "execution_route": plan.get("execution_route", ""),
        "host": plan.get("host", ""),
        "background_worker_required": bool(plan.get("background_worker_required", True)),
        "stage_model": plan.get("stage_model", ""),
        "streamlining_model": plan.get("streamlining_model", ""),
        "stop_policy": plan.get("stop_policy", ""),
        "stages": [
            {
                "state": stage.get("state", ""),
                "label": stage.get("label", ""),
                "expert_id": stage.get("expert_id", ""),
                "status": stage.get("status", ""),
                "handoff": stage.get("handoff", ""),
            }
            for stage in list(plan.get("stages") or [])[:max_stages]
            if isinstance(stage, dict)
        ],
        "missing_info": list(plan.get("missing_info") or [])[:4],
    }


def first_progress_status(plan: dict[str, Any] | None) -> str:
    stages = list((plan or {}).get("stages") or [])
    if not stages:
        return "Understanding request"
    stage = stages[0]
    label = _as_text(stage.get("label")) or "Understanding request"
    expert = _as_text(stage.get("expert_id"))
    return f"{label} ({expert})" if expert else label
