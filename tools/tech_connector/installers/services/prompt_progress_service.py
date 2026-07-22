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


def _goal_id(goal: dict[str, Any]) -> str:
    return str(goal.get("task_id") or goal.get("goal_id") or "")


def _goal_status(
    goal: dict[str, Any],
    *,
    completed_goal_ids: set[str],
    running_goal_ids: set[str],
    failed_goal_ids: set[str],
    skipped_goal_ids: set[str],
    ready_goal_ids: set[str],
) -> str:
    goal_id = _goal_id(goal)
    if goal_id in failed_goal_ids:
        return "failed"
    if goal_id in completed_goal_ids:
        return "completed"
    if goal_id in skipped_goal_ids:
        return "skipped"
    if goal_id in running_goal_ids:
        return "running"
    if goal_id in ready_goal_ids:
        if bool(goal.get("requires_confirmation")):
            return "awaiting_approval"
        return "ready"
    return "blocked"


def _build_goal_progress(
    decision: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    goal_graph = dict(
        decision.get("goal_graph")
        or decision.get("task_graph")
        or {}
    )
    goals = list(goal_graph.get("goals") or goal_graph.get("tasks") or [])

    completed_goal_ids = {
        str(value)
        for value in (decision.get("completed_goal_ids") or [])
    }
    running_goal_ids = {
        str(value)
        for value in (decision.get("running_goal_ids") or [])
    }
    failed_goal_ids = {
        str(value)
        for value in (decision.get("failed_goal_ids") or [])
    }
    skipped_goal_ids = {
        str(value)
        for value in (decision.get("skipped_goal_ids") or [])
    }

    explicit_ready = {
        str(value)
        for value in (decision.get("ready_goal_ids") or [])
    }
    if not explicit_ready:
        explicit_ready = {
            _goal_id(goal)
            for goal in (decision.get("ready_goals") or [])
            if _goal_id(goal)
        }

    if not explicit_ready:
        for goal in goals:
            goal_id = _goal_id(goal)
            if not goal_id or goal_id in completed_goal_ids:
                continue
            dependencies = {
                str(value)
                for value in (goal.get("depends_on") or [])
            }
            if dependencies.issubset(completed_goal_ids):
                explicit_ready.add(goal_id)

    terminal_goal_ids = {
        str(value)
        for value in (goal_graph.get("terminal_goal_ids") or [])
    }
    approval_goal_ids = {
        str(value)
        for value in (goal_graph.get("approval_goal_ids") or [])
    }

    progress: list[dict[str, Any]] = []
    for index, goal in enumerate(goals, start=1):
        goal_id = _goal_id(goal)
        status = _goal_status(
            goal,
            completed_goal_ids=completed_goal_ids,
            running_goal_ids=running_goal_ids,
            failed_goal_ids=failed_goal_ids,
            skipped_goal_ids=skipped_goal_ids,
            ready_goal_ids=explicit_ready,
        )
        dependencies = [
            str(value)
            for value in (goal.get("depends_on") or [])
        ]
        progress.append(
            {
                "index": index,
                "total": len(goals),
                "goal_id": goal_id,
                "title": _as_text(
                    goal.get("title")
                    or goal.get("objective")
                    or goal_id
                    or f"Goal {index}"
                ),
                "objective": _as_text(goal.get("objective")),
                "goal_type": _as_text(goal.get("goal_type")),
                "action": _as_text(goal.get("action")),
                "capability": _as_text(goal.get("capability")),
                "status": status,
                "ready": status in {"ready", "running", "awaiting_approval"},
                "blocked": status == "blocked",
                "completed": status == "completed",
                "failed": status == "failed",
                "terminal": bool(goal.get("terminal")) or goal_id in terminal_goal_ids,
                "approval_required": (
                    bool(goal.get("requires_confirmation"))
                    or goal_id in approval_goal_ids
                ),
                "read_only": bool(goal.get("read_only", True)),
                "depends_on": dependencies,
                "required_inputs": [
                    str(value)
                    for value in (goal.get("required_inputs") or [])
                ],
                "produces": [
                    str(value)
                    for value in (goal.get("produces") or [])
                ],
                "success_condition": _as_text(goal.get("success_condition")),
                "estimated_complexity": int(
                    goal.get("estimated_complexity") or 1
                ),
            }
        )

    return goal_graph, progress


def _goal_progress_percent(goal_progress: list[dict[str, Any]]) -> int:
    if not goal_progress:
        return 0
    completed = sum(
        1
        for goal in goal_progress
        if goal.get("status") in {"completed", "skipped"}
    )
    running_credit = sum(
        0.5
        for goal in goal_progress
        if goal.get("status") == "running"
    )
    return max(
        0,
        min(
            100,
            int(round(((completed + running_credit) / len(goal_progress)) * 100)),
        ),
    )


def _current_goal(
    decision: dict[str, Any],
    goal_progress: list[dict[str, Any]],
) -> dict[str, Any]:
    explicit = dict(decision.get("current_goal") or {})
    explicit_id = str(
        decision.get("current_goal_id")
        or explicit.get("task_id")
        or explicit.get("goal_id")
        or ""
    )
    if explicit_id:
        for goal in goal_progress:
            if goal.get("goal_id") == explicit_id:
                return goal

    for preferred in ("running", "awaiting_approval", "ready", "blocked"):
        for goal in goal_progress:
            if goal.get("status") == preferred:
                return goal
    return {}


def _next_goal(
    current_goal: dict[str, Any],
    goal_progress: list[dict[str, Any]],
) -> dict[str, Any]:
    current_id = str(current_goal.get("goal_id") or "")
    found_current = not current_id
    for goal in goal_progress:
        if goal.get("goal_id") == current_id:
            found_current = True
            continue
        if found_current and goal.get("status") in {
            "ready",
            "awaiting_approval",
            "blocked",
        }:
            return goal
    return {}


def _compatibility_stages(
    goal_progress: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve the old ``stages`` contract for existing UI consumers."""
    stages: list[dict[str, Any]] = []
    total = len(goal_progress)
    for index, goal in enumerate(goal_progress, start=1):
        status = str(goal.get("status") or "pending")
        state = {
            "completed": "GOAL_COMPLETED",
            "running": "GOAL_RUNNING",
            "ready": "GOAL_READY",
            "awaiting_approval": "GOAL_AWAITING_APPROVAL",
            "failed": "GOAL_FAILED",
            "skipped": "GOAL_SKIPPED",
            "blocked": "GOAL_BLOCKED",
        }.get(status, "GOAL_PENDING")
        stages.append(
            {
                "index": index,
                "total": total,
                "percent": int(round((index / total) * 100)) if total else 0,
                "state": state,
                "label": goal.get("title", ""),
                "expert_id": goal.get("capability") or goal.get("goal_type") or "goal_executor",
                "message": goal.get("objective", ""),
                "stop_when": goal.get("success_condition", ""),
                "handoff": (
                    (goal.get("produces") or ["goal_result"])[0]
                    if isinstance(goal.get("produces"), list)
                    else "goal_result"
                ),
                "status": status,
                "goal_id": goal.get("goal_id", ""),
                "early_exit": True,
                "handoff_required": True,
            }
        )
    return stages


def build_prompt_progress_plan(
    prompt: str,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the observable goal-progress plan shared by every prompt path."""

    decision = dict(decision or {})

    try:
        from services.prompt_resource_orchestration_service import (
            build_resource_orchestration_plan,
        )

        resource_plan = build_resource_orchestration_plan(prompt, decision)
    except Exception:
        resource_plan = {}

    try:
        from services.process_streamlining_service import (
            build_process_streamlining_plan,
        )

        streamlining_plan = build_process_streamlining_plan(
            prompt,
            route=_as_text(
                decision.get("execution_route")
                or decision.get("route")
                or ""
            ),
        ).to_dict()
    except Exception:
        streamlining_plan = {}

    semantic_contract = dict(
        decision.get("semantic_execution_contract")
        or (decision.get("request_understanding") or {}).get(
            "semantic_execution_contract"
        )
        or {}
    )

    route = _as_text(decision.get("route") or "chat")
    execution_route = _as_text(
        decision.get("execution_route")
        or route
    )
    host = _as_text(decision.get("host"))
    missing = _uniq(list(decision.get("missing_info") or []))

    goal_graph, goal_progress = _build_goal_progress(decision)

    # Legacy/fallback requests may not have a goal graph yet.
    if not goal_progress:
        goal_progress = [
            {
                "index": 1,
                "total": 1,
                "goal_id": "respond_to_request",
                "title": "Respond to request",
                "objective": _as_text(
                    decision.get("primary_goal")
                    or goal_graph.get("primary_goal")
                    or prompt
                ),
                "goal_type": _as_text(
                    decision.get("goal_type")
                    or "respond"
                ),
                "action": "respond",
                "capability": route,
                "status": "ready",
                "ready": True,
                "blocked": False,
                "completed": False,
                "failed": False,
                "terminal": True,
                "approval_required": bool(
                    decision.get("requires_confirmation")
                ),
                "read_only": (
                    _as_text(decision.get("mutation_scope")) == "read_only"
                ),
                "depends_on": [],
                "required_inputs": [],
                "produces": ["user_response"],
                "success_condition": "The user receives a complete response.",
                "estimated_complexity": 1,
            }
        ]

    current_goal = _current_goal(decision, goal_progress)
    next_goal = _next_goal(current_goal, goal_progress)

    completed_goals = [
        goal
        for goal in goal_progress
        if goal.get("status") == "completed"
    ]
    ready_goals = [
        goal
        for goal in goal_progress
        if goal.get("status") in {"ready", "running", "awaiting_approval"}
    ]
    blocked_goals = [
        goal
        for goal in goal_progress
        if goal.get("status") == "blocked"
    ]
    failed_goals = [
        goal
        for goal in goal_progress
        if goal.get("status") == "failed"
    ]
    approval_goals = [
        goal
        for goal in goal_progress
        if goal.get("approval_required")
        and goal.get("status") not in {"completed", "skipped"}
    ]
    terminal_goals = [
        goal
        for goal in goal_progress
        if goal.get("terminal")
    ]

    overall_percent = _goal_progress_percent(goal_progress)
    compatibility_stages = _compatibility_stages(goal_progress)

    return {
        "framework": "visible_goal_progress_v2",
        "compatibility_framework": "visible_prompt_progress_v1",
        "enabled": True,
        "prompt_preview": (prompt or "")[:240],
        "route": route,
        "execution_route": execution_route,
        "host": host,
        "primary_goal": _as_text(
            semantic_contract.get("goal")
            or decision.get("primary_goal")
            or goal_graph.get("primary_goal")
            or goal_graph.get("goal")
            or prompt
        ),
        "semantic_execution_contract": semantic_contract,
        "understanding": {
            "deliverable_type": semantic_contract.get("deliverable_type", ""),
            "subject_type": semantic_contract.get("subject_type", ""),
            "subject_text": semantic_contract.get("subject_text", ""),
            "relationship": semantic_contract.get("relationship", ""),
            "context_source": semantic_contract.get("context_source", ""),
            "confidence": semantic_contract.get("confidence", 0.0),
            "confidence_signals": list(
                semantic_contract.get("confidence_signals") or []
            ),
            "uncertainty_signals": list(
                semantic_contract.get("uncertainty_signals") or []
            ),
            "evidence_required": list(
                semantic_contract.get("evidence_required") or []
            ),
        },
        "goal_type": _as_text(
            decision.get("goal_type")
            or goal_graph.get("goal_type")
            or ""
        ),
        "overall_percent": overall_percent,
        "current_goal": current_goal,
        "next_goal": next_goal,
        "goal_progress": goal_progress,
        "completed_goals": completed_goals,
        "ready_goals": ready_goals,
        "blocked_goals": blocked_goals,
        "failed_goals": failed_goals,
        "approval_goals": approval_goals,
        "terminal_goals": terminal_goals,
        "background_worker_required": True,
        "separate_os_thread_per_stage": False,
        "stage_model": "dependency_aware_goal_progress",
        "resource_model": resource_plan.get(
            "framework",
            "resource_aware_goal_orchestration_v2",
        ),
        "resource_plan": resource_plan,
        "streamlining_model": streamlining_plan.get(
            "framework",
            "process_streamlining_v1",
        ),
        "streamlining_plan": streamlining_plan,
        "stop_policy": (
            "A goal completes only when its success condition is satisfied. "
            "The request stops when its terminal goal succeeds, validation fails "
            "without recovery, or approval/context is required."
        ),
        "handoff_policy": (
            "Each completed goal emits only its declared structured outputs, "
            "which unlock dependent goals."
        ),
        "gap_policy": (
            "Blocked goals remain visible with their unmet dependencies. Missing "
            "capabilities become explicit recovery or acquisition goals."
        ),
        "ui_requirements": [
            "show the primary goal and current goal in the status bar",
            "show completed, running, ready, blocked, failed, and approval states distinctly",
            "show the success condition for the current goal",
            "keep updating while model, tool, host, daemon, or validation work is active",
            "keep the UI thread free while work runs",
            "show approval gates before risky mutation",
            "show exact changed files, assets, graphs, and functions after mutation",
            "show validation evidence before declaring terminal completion",
        ],
        "expert_lenses": _expert_lenses(
            {**decision, "prompt_preview": prompt}
        ),
        "domain_experts": list(
            decision.get("domain_experts")
            or []
        ),
        # Backward-compatible stage view.
        "stages": compatibility_stages,
        "failure_states": list(FAILURE_STATES),
        "parallel_ready_goal_ids": [
            str(value)
            for group in (
                resource_plan.get("parallel_goal_groups")
                or []
            )
            if isinstance(group, list) and len(group) > 1
            for value in group
        ],
        "serialized_goal_ids": [
            str(item.get("goal_id") or "")
            for item in (
                resource_plan.get("goal_execution_plan")
                or []
            )
            if not bool(item.get("parallel"))
        ],
        "missing_info": missing,
    }


def render_prompt_progress_plan(
    plan: dict[str, Any] | None,
    *,
    max_stages: int = 4,
) -> str:
    """Render a compact visible goal-progress card for chat."""

    if not plan:
        return ""

    goals = list(
        plan.get("goal_progress")
        or plan.get("stages")
        or []
    )
    if not goals:
        return ""

    current_goal = dict(plan.get("current_goal") or {})
    lines = [
        "Visible work plan:",
        f"Primary goal: {plan.get('primary_goal') or 'Complete the request'}",
        f"Route: {plan.get('execution_route') or plan.get('route') or 'chat'}",
        f"Progress: {int(plan.get('overall_percent') or 0)}%",
    ]

    if current_goal:
        lines.append(
            f"Current: {current_goal.get('title') or current_goal.get('goal_id')} "
            f"[{current_goal.get('status')}]"
        )
        if current_goal.get("success_condition"):
            lines.append(
                f"Success: {current_goal.get('success_condition')}"
            )

    for goal in goals[:max_stages]:
        status = str(goal.get("status") or "pending")
        symbol = {
            "completed": "✓",
            "running": "▶",
            "ready": "→",
            "awaiting_approval": "!",
            "failed": "×",
            "blocked": "○",
            "skipped": "–",
        }.get(status, "○")
        lines.append(
            f"- {symbol} {goal.get('title') or goal.get('label') or goal.get('goal_id')}: "
            f"{status}"
        )

    remaining = len(goals) - max_stages
    if remaining > 0:
        lines.append(f"- {remaining} later goal(s) remain.")

    return "\n".join(lines)


def compact_prompt_progress_plan(
    plan: dict[str, Any] | None,
    *,
    max_stages: int = 5,
) -> dict[str, Any]:
    """Return route-metadata-friendly goal progress."""

    plan = dict(plan or {})
    goals = list(
        plan.get("goal_progress")
        or plan.get("stages")
        or []
    )

    return {
        "framework": plan.get(
            "framework",
            "visible_goal_progress_v2",
        ),
        "compatibility_framework": plan.get(
            "compatibility_framework",
            "visible_prompt_progress_v1",
        ),
        "enabled": bool(plan.get("enabled", True)),
        "route": plan.get("route", ""),
        "execution_route": plan.get("execution_route", ""),
        "host": plan.get("host", ""),
        "primary_goal": plan.get("primary_goal", ""),
        "understanding": dict(plan.get("understanding") or {}),
        "goal_type": plan.get("goal_type", ""),
        "overall_percent": int(plan.get("overall_percent") or 0),
        "current_goal": dict(plan.get("current_goal") or {}),
        "next_goal": dict(plan.get("next_goal") or {}),
        "background_worker_required": bool(
            plan.get("background_worker_required", True)
        ),
        "stage_model": plan.get(
            "stage_model",
            "dependency_aware_goal_progress",
        ),
        "streamlining_model": plan.get("streamlining_model", ""),
        "stop_policy": plan.get("stop_policy", ""),
        "goal_progress": [
            {
                "goal_id": goal.get("goal_id", ""),
                "title": goal.get("title") or goal.get("label") or "",
                "status": goal.get("status", ""),
                "terminal": bool(goal.get("terminal")),
                "approval_required": bool(
                    goal.get("approval_required")
                ),
                "success_condition": goal.get(
                    "success_condition",
                    "",
                ),
            }
            for goal in goals[:max_stages]
            if isinstance(goal, dict)
        ],
        # Preserve the old key for route/UI consumers not migrated yet.
        "stages": [
            {
                "state": stage.get("state", ""),
                "label": stage.get("label", ""),
                "expert_id": stage.get("expert_id", ""),
                "status": stage.get("status", ""),
                "handoff": stage.get("handoff", ""),
                "goal_id": stage.get("goal_id", ""),
            }
            for stage in list(plan.get("stages") or [])[:max_stages]
            if isinstance(stage, dict)
        ],
        "completed_goal_count": len(
            plan.get("completed_goals")
            or []
        ),
        "ready_goal_count": len(
            plan.get("ready_goals")
            or []
        ),
        "blocked_goal_count": len(
            plan.get("blocked_goals")
            or []
        ),
        "failed_goal_count": len(
            plan.get("failed_goals")
            or []
        ),
        "missing_info": list(
            plan.get("missing_info")
            or []
        )[:4],
    }


def first_progress_status(
    plan: dict[str, Any] | None,
) -> str:
    plan = dict(plan or {})
    current = dict(plan.get("current_goal") or {})
    if current:
        title = _as_text(
            current.get("title")
            or current.get("goal_id")
            or "Working"
        )
        status = _as_text(current.get("status"))
        return f"{title} ({status})" if status else title

    goals = list(
        plan.get("goal_progress")
        or plan.get("stages")
        or []
    )
    if not goals:
        return "Understanding request"

    first = goals[0]
    label = _as_text(
        first.get("title")
        or first.get("label")
        or "Understanding request"
    )
    status = _as_text(first.get("status"))
    return f"{label} ({status})" if status else label
