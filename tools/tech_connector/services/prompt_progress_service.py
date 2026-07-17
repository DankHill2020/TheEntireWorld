"""Visible prompt progress contracts for every routed request.

This service describes and narrates observable work without exposing hidden
model reasoning. It names the expert lens, evidence, stop condition, and handoff
for each stage, then renders concise user-facing progress messages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
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
            from tech_connector.services.domain_expert_service import select_domain_experts

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
    """Build an outcome-oriented observable plan for every prompt path."""
    decision = dict(decision or {})
    try:
        reasoning_narration = build_reasoning_narration(prompt, decision)
    except Exception:
        reasoning_narration = {}
    try:
        from tech_connector.services.prompt_resource_orchestration_service import build_resource_orchestration_plan

        resource_plan = build_resource_orchestration_plan(prompt, decision)
    except Exception:
        resource_plan = {}
    try:
        from tech_connector.services.process_streamlining_service import build_process_streamlining_plan

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
    narration_steps = list(reasoning_narration.get("steps") or [])
    if narration_steps:
        total = len(narration_steps)
        for index, raw_step in enumerate(narration_steps, start=1):
            step = dict(raw_step or {})
            phase = _as_text(step.get("phase") or "planning")
            state = {
                "understanding": "UNDERSTANDING",
                "planning": "PLANNING",
                "gap_discovery": "GAP_DISCOVERY",
                "searching": "SEARCHING",
                "comparing": "COMPARING",
                "executing": "EXECUTION",
                "validating": "VALIDATION",
                "reporting": "REPORTING",
            }.get(phase, phase.upper())
            stages.append(
                {
                    "state": state,
                    "label": _as_text(step.get("title") or step.get("objective")),
                    "expert_id": "reasoning_narrator",
                    "message": _as_text(step.get("objective")),
                    "why": _as_text(step.get("why")),
                    "stop_when": _as_text(step.get("success")),
                    "handoff": _as_text(step.get("step_id")),
                    "depends_on": list(step.get("depends_on") or []),
                    "index": index,
                    "total": total,
                    "percent": int(round((index / total) * 100)),
                    "status": _as_text(step.get("status") or "pending"),
                    "early_exit": True,
                    "handoff_required": True,
                }
            )
    else:
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
        "framework": "visible_reasoning_progress_v2",
        "enabled": True,
        "reasoning_narration": reasoning_narration,
        "interpreted_request": reasoning_narration.get("interpreted_request", ""),
        "desired_outcome": reasoning_narration.get("desired_outcome", ""),
        "approach_summary": reasoning_narration.get("approach_summary", ""),
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


def render_prompt_progress_plan(
    plan: dict[str, Any] | None,
    *,
    max_stages: int = 6,
) -> str:
    """Render concise, human-readable understanding and work steps.

    This deliberately avoids internal service names, route plumbing, and hidden
    reasoning. It tells the user what the system understood and what observable
    work it will perform.
    """
    if not plan:
        return ""

    narration = dict(plan.get("reasoning_narration") or {})
    understood = _as_text(
        narration.get("interpreted_request")
        or plan.get("interpreted_request")
        or plan.get("desired_outcome")
        or plan.get("prompt_preview")
    )
    desired = _as_text(
        narration.get("desired_outcome")
        or plan.get("desired_outcome")
    )
    approach = _as_text(
        narration.get("approach_summary")
        or plan.get("approach_summary")
    )

    prompt_preview = _as_text(plan.get("prompt_preview"))

    def _is_generic_summary(value: str) -> bool:
        lower_value = (value or "").casefold()
        return any(token in lower_value for token in (
            "determine and deliver the evidence-backed answer",
            "directly resolves 'locate'",
            "resolve deliverable, subject, relationships, and success",
            "requested deliverable",
        ))

    if _is_generic_summary(understood) and prompt_preview:
        understood = prompt_preview.rstrip(" .?!")
    if _is_generic_summary(desired):
        lower_prompt = prompt_preview.casefold()
        if "what files" in lower_prompt or "which files" in lower_prompt:
            desired = "A list of matching project files with the functions that support the answer"
        elif "what functions" in lower_prompt or "which functions" in lower_prompt:
            desired = "A list of matching functions with their containing files"
        elif prompt_preview:
            desired = "A direct answer grounded in the strongest available project evidence"
    if _is_generic_summary(approach):
        approach = "Search the project index, compare matching functions, and stop as soon as the file evidence is sufficient"

    stages = [dict(item or {}) for item in list(plan.get("stages") or []) if isinstance(item, dict)]
    steps: list[str] = []
    for stage in stages[:max_stages]:
        message = _as_text(stage.get("message") or stage.get("label"))
        if not message:
            continue
        lower = message.lower()
        if any(token in lower for token in (
            "dispatch", "handler", "route", "serialization",
            "expert selected", "deterministic engine", "token",
            "resolve deliverable, subject, relationships, and success",
            "produce the requested deliverable",
        )):
            continue
        message = message.rstrip(".")
        if message and message not in steps:
            steps.append(message)

    route = _as_text(plan.get("route")).casefold()
    if not steps and route in {"project_search", "quality_audit"}:
        steps = [
            "Search indexed files and functions for the requested behavior",
            "Compare the strongest matching evidence",
            "Return the containing files and relevant functions",
        ]

    lines: list[str] = []
    if understood:
        lines.extend(["What I understood", understood.rstrip(".") + "."])
    if desired and desired.casefold() != understood.casefold():
        lines.extend(["", "Result I am aiming for", desired.rstrip(".") + "."])
    if approach:
        lines.extend(["", "How I will approach it", approach.rstrip(".") + "."])
    if steps:
        lines.extend(["", "What I am doing"])
        lines.extend(f"{index}. {step}." for index, step in enumerate(steps, start=1))

    if not lines and stages:
        lines = ["What I am doing"] + [
            f"{index}. {_as_text(stage.get('message') or stage.get('label')).rstrip('.')}."
            for index, stage in enumerate(stages[:max_stages], start=1)
            if _as_text(stage.get('message') or stage.get('label'))
        ]
    return "\n".join(lines).strip()


def compact_prompt_progress_plan(plan: dict[str, Any] | None, *, max_stages: int = 5) -> dict[str, Any]:
    """Return a route-metadata friendly visible progress plan."""
    plan = dict(plan or {})
    return {
        "framework": plan.get("framework", "visible_reasoning_progress_v2"),
        "reasoning_narration": dict(plan.get("reasoning_narration") or {}),
        "interpreted_request": plan.get("interpreted_request", ""),
        "desired_outcome": plan.get("desired_outcome", ""),
        "approach_summary": plan.get("approach_summary", ""),
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
                "message": stage.get("message", ""),
                "why": stage.get("why", ""),
                "stop_when": stage.get("stop_when", ""),
            }
            for stage in list(plan.get("stages") or [])[:max_stages]
            if isinstance(stage, dict)
        ],
        "missing_info": list(plan.get("missing_info") or [])[:4],
    }


def first_progress_status(plan: dict[str, Any] | None) -> str:
    data = dict(plan or {})
    narration = dict(data.get("reasoning_narration") or {})
    try:
        message = narrate_progress_message("Understanding request", narration)
        if message:
            return message
    except Exception:
        pass
    stages = list(data.get("stages") or [])
    if not stages:
        return "Understanding the requested outcome..."
    stage = stages[0]
    return _as_text(stage.get("message") or stage.get("label")) or "Understanding the requested outcome..."


_INTERNAL_EVENT_KINDS = {
    "route",
    "route_candidate",
    "tool",
    "intent",
    "request_goal_graph",
    "request_goal",
}

_GENERIC_RUNTIME_MESSAGES = {
    "accepted. routing and preparing context",
    "accepted request - routing",
    "routing request",
    "routing request normally",
    "running deterministic engine request",
    "searching project facts",
    "searching project index",
    "project index ready",
    "answer ready",
    "dispatching via projectsearchhandler",
    "understanding request",
}


@dataclass
class NarrationStep:
    step_id: str
    title: str
    objective: str
    why: str = ""
    success: str = ""
    phase: str = "planning"
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReasoningNarration:
    prompt: str
    interpreted_request: str
    desired_outcome: str
    approach_summary: str
    steps: list[NarrationStep] = field(default_factory=list)
    current_step_id: str = ""
    completed_step_ids: list[str] = field(default_factory=list)
    debug_events_hidden: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "reasoning_narration_v1",
            "prompt": self.prompt,
            "interpreted_request": self.interpreted_request,
            "desired_outcome": self.desired_outcome,
            "approach_summary": self.approach_summary,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_id": self.current_step_id,
            "completed_step_ids": list(self.completed_step_ids),
            "debug_events_hidden": self.debug_events_hidden,
        }


def build_reasoning_narration(
    prompt: str,
    decision: dict[str, Any] | Any | None = None,
) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    formulation = _formulation(prompt, data)
    specialized = _specialized_query_narration(prompt, formulation)
    if specialized:
        return specialized

    interpreted = str(
        formulation.get("interpreted_problem")
        or formulation.get("literal_request")
        or data.get("primary_goal")
        or prompt
    ).strip()
    desired = str(
        formulation.get("desired_outcome")
        or formulation.get("success_definition")
        or ""
    ).strip()

    plan_rows = list(
        formulation.get("candidate_plan")
        or data.get("semantic_plan_steps")
        or (data.get("semantic_execution_contract") or {}).get("plan_steps")
        or (data.get("goal_graph") or {}).get("goals")
        or (data.get("task_graph") or {}).get("goals")
        or []
    )

    steps: list[NarrationStep] = []
    for index, raw in enumerate(plan_rows):
        row = dict(raw or {})
        objective = str(
            row.get("objective")
            or row.get("goal")
            or row.get("title")
            or row.get("description")
            or ""
        ).strip()
        if not objective:
            continue
        step_id = str(
            row.get("step_id")
            or row.get("goal_id")
            or row.get("task_id")
            or f"step_{index + 1}"
        )
        why = str(
            row.get("why")
            or row.get("reason")
            or row.get("rationale")
            or _infer_why(objective, formulation)
        ).strip()
        success = str(
            row.get("success")
            or row.get("success_condition")
            or row.get("stop_when")
            or ""
        ).strip()
        phase = _phase_for_step(row, objective)
        steps.append(
            NarrationStep(
                step_id=step_id,
                title=_short_title(objective, phase),
                objective=objective,
                why=why,
                success=success,
                phase=phase,
                status=str(row.get("status") or "pending"),
                depends_on=[str(value) for value in row.get("depends_on") or []],
            )
        )

    if not steps:
        steps = _fallback_steps(formulation, interpreted)

    current = next(
        (
            step.step_id
            for step in steps
            if step.status in {"ready", "active", "running", "pending"}
            and not step.depends_on
        ),
        steps[0].step_id if steps else "",
    )

    return ReasoningNarration(
        prompt=prompt,
        interpreted_request=interpreted,
        desired_outcome=desired,
        approach_summary=_approach_summary(formulation, steps),
        steps=steps,
        current_step_id=current,
    ).to_dict()


def render_reasoning_narration(
    narration: dict[str, Any] | None,
    *,
    max_steps: int = 6,
) -> str:
    data = dict(narration or {})
    if not data:
        return ""
    lines = [
        "Reasoning Approach",
        "",
        "Understanding",
        str(data.get("interpreted_request") or "Interpreting the requested outcome."),
    ]
    if data.get("desired_outcome"):
        lines.extend(["", "Success looks like", str(data["desired_outcome"])])
    if data.get("approach_summary"):
        lines.extend(["", "Approach", str(data["approach_summary"])])
    steps = list(data.get("steps") or [])
    if steps:
        lines.extend(["", "Plan"])
        current_id = str(data.get("current_step_id") or "")
        for row in steps[:max_steps]:
            step_id = str(row.get("step_id") or "")
            marker = "▶" if step_id == current_id else "□"
            lines.append(f"{marker} {row.get('objective') or row.get('title') or step_id}")
    return "\n".join(lines)


def narrate_progress_message(
    message: str,
    narration: dict[str, Any] | None = None,
) -> str:
    """Translate a plumbing-oriented runtime message into an outcome-oriented one."""
    raw = re.sub(r"\s+", " ", str(message or "")).strip()
    if not raw:
        return ""
    lower = raw.casefold()

    # Never surface dataclass reprs or debug plumbing as normal progress.
    if "activityevent(" in lower:
        return ""
    if lower.startswith("dispatching via ") or lower.startswith("routing through "):
        return ""
    if lower.startswith("route selected:"):
        return ""

    data = dict(narration or {})
    steps = list(data.get("steps") or [])

    if "context changed:" in lower:
        return raw
    if "accepted" in lower or lower in {"routing request", "understanding request"}:
        return _message_for_phase(data, "understanding") or "Understanding the outcome you need..."
    if "searching project facts" in lower or "searching project index" in lower:
        return _message_for_phase(data, "searching") or "Gathering the evidence needed to answer the request..."
    if "project evidence gathered" in lower or "index answer ready" in lower:
        return _message_for_phase(data, "comparing") or "Comparing the strongest candidate evidence..."
    if "answer ready" in lower or lower.endswith(" ready"):
        return _message_for_phase(data, "reporting") or "Preparing the evidence-backed answer..."
    if "validat" in lower or "compile" in lower or "test" in lower:
        return _message_for_phase(data, "validating") or raw
    if "planning" in lower:
        return _message_for_phase(data, "planning") or raw
    if "preparing prompt" in lower or "applying source policy" in lower:
        return _message_for_phase(data, "understanding") or "Attaching the context needed to interpret the request accurately..."

    # Preserve already-specific user-facing messages.
    if len(raw.split()) >= 6 and not any(
        token in lower
        for token in (
            "engine request",
            "handler selected",
            "projectsearchhandler",
            "route_candidate",
        )
    ):
        return raw

    if lower in _GENERIC_RUNTIME_MESSAGES:
        return _current_step_message(data)
    return raw


def narrate_activity_event(
    event: Any,
    narration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kind = str(getattr(event, "kind", "") or "").strip().lower()
    title = str(getattr(event, "title", "") or "").strip()
    detail = str(getattr(event, "detail", "") or "").strip()
    status = str(getattr(event, "status", "") or "").strip()

    internal = kind in _INTERNAL_EVENT_KINDS
    phase = {
        "intent": "understanding",
        "route_candidate": "understanding",
        "route": "planning",
        "request_goal_graph": "planning",
        "request_goal": "planning",
        "tool": "searching",
        "visible_progress": "searching",
        "result": "comparing",
        "validation": "validating",
        "report": "reporting",
    }.get(kind, "")

    message = _message_for_phase(dict(narration or {}), phase)
    if not message:
        message = narrate_progress_message(detail or title, narration)

    return {
        "kind": kind,
        "phase": phase,
        "message": message,
        "internal": internal,
        "status": status,
        "debug_text": _debug_event_text(event),
    }


def should_show_debug_event(event: Any, *, developer_mode: bool = False) -> bool:
    if developer_mode:
        return True
    kind = str(getattr(event, "kind", "") or "").strip().lower()
    return kind not in _INTERNAL_EVENT_KINDS



def _specialized_query_narration(
    prompt: str,
    formulation: dict[str, Any],
) -> dict[str, Any]:
    lower = re.sub(r"\s+", " ", str(prompt or "")).strip().lower()

    file_behavior = bool(
        re.search(r"\b(?:what|which|find|show|list)\s+files?\b", lower)
        and re.search(r"\bfunctions?\b", lower)
        and re.search(r"\b(create|build|generate|make|setup)\b", lower)
    )
    if file_behavior:
        subject_match = re.search(
            r"\b(?:create|build|generate|make|setup)\s+(.+?)\s+functions?\b",
            lower,
        )
        subject = (subject_match.group(1) if subject_match else "rig").strip()
        narration = ReasoningNarration(
            prompt=prompt,
            interpreted_request=(
                f"Find the project files containing functions that create or build {subject}."
            ),
            desired_outcome=(
                "Return the strongest matching file paths, the supporting functions "
                "inside them, and why those functions count as primary implementations."
            ),
            approach_summary=(
                "Files do not perform the behavior directly; functions do. I will first "
                "find the implementing functions, then resolve and rank their containing files."
            ),
            steps=[
                NarrationStep(
                    "define_behavior",
                    "Define rig-creation behavior",
                    f"Define what counts as creating or building {subject}.",
                    "A filename or incidental word match is not enough to prove implementation behavior.",
                    "The behavior contract and exclusions are explicit.",
                    "understanding",
                    "ready",
                ),
                NarrationStep(
                    "find_functions",
                    "Find creating functions",
                    f"Find candidate functions that create or build {subject}.",
                    "The functions provide the evidence needed to identify the correct files.",
                    "Candidate implementation functions are found or absence is confirmed.",
                    "searching",
                    depends_on=["define_behavior"],
                ),
                NarrationStep(
                    "inspect_functions",
                    "Inspect candidate behavior",
                    "Inspect names, signatures, bodies, docstrings, and call relationships.",
                    "Related helpers must be separated from functions that actually construct the rig.",
                    "Each candidate has positive and negative behavioral evidence.",
                    "comparing",
                    depends_on=["find_functions"],
                ),
                NarrationStep(
                    "resolve_files",
                    "Resolve containing files",
                    "Determine which source files contain the supported implementation functions.",
                    "The requested deliverable is files, but the proof comes from contained functions.",
                    "Every supported function maps to an existing file.",
                    "searching",
                    depends_on=["inspect_functions"],
                ),
                NarrationStep(
                    "rank_files",
                    "Rank primary implementations",
                    "Rank complete rig builders above narrow helpers and incidental matches.",
                    "The final answer should identify the most responsible implementations, not every related function.",
                    "The strongest files are explainably separated from alternatives.",
                    "comparing",
                    depends_on=["resolve_files"],
                ),
                NarrationStep(
                    "report",
                    "Report files and evidence",
                    "Return the matching files with supporting functions and rationale.",
                    "",
                    "The answer directly identifies which files implement the behavior and why.",
                    "reporting",
                    depends_on=["rank_files"],
                ),
            ],
            current_step_id="define_behavior",
        )
        return narration.to_dict()

    reference_function = bool(
        re.search(r"\b(?:that|this|the previous|the last)\s+file\b", lower)
        and re.search(r"\bfunctions?\b", lower)
    )
    if reference_function:
        resolved_target = str(
            decision.get("resolved_target_file")
            or (decision.get("planning_result") or {}).get("target")
            or ""
        )
        target_name = Path(resolved_target).name if resolved_target else "the resolved file"
        behavior_match = re.search(
            r"\bin\s+(?:that|this|the previous|the last)\s+file\s+to\s+(.+?)(?:\?|$)",
            lower,
        )
        if not behavior_match:
            behavior_match = re.search(
                r"\bfunctions?\b.*?\b(?:to|which)\s+(.+?)(?:\?|$)",
                lower,
            )
        if not behavior_match:
            behavior_match = re.search(
                r"\b(?:to|which)\s+(.+?)(?:\?|$)",
                lower,
            )
        behavior = (
            behavior_match.group(1).strip()
            if behavior_match
            else "match the requested behavior"
        )
        narration = ReasoningNarration(
            prompt=prompt,
            interpreted_request=(
                f"Check {target_name} for functions that {behavior}."
            ),
            desired_outcome=(
                "Return the matching function if it exists, or clearly explain that no dedicated "
                "helper was found and what evidence was checked."
            ),
            approach_summary=(
                "I must resolve “that file” from conversation context, inspect only that file, "
                "and compare actual function behavior rather than searching the whole project."
            ),
            steps=[
                NarrationStep(
                    "resolve_reference",
                    "Resolve target file",
                    "Resolve “that file” to one concrete source path from recent conversation context.",
                    "The function search cannot be scoped correctly until the reference is concrete.",
                    "One source file is resolved.",
                    "understanding",
                    "ready",
                ),
                NarrationStep(
                    "inventory_file",
                    "Inspect functions in that file",
                    "Enumerate relevant functions only inside the resolved file.",
                    "The question is scoped to one file, not the whole project.",
                    "The file’s candidate functions are known.",
                    "searching",
                    depends_on=["resolve_reference"],
                ),
                NarrationStep(
                    "compare_behavior",
                    "Compare function behavior",
                    f"Determine which candidate actually {behavior}.",
                    "Names alone may describe adjacent behavior without performing the requested detection.",
                    "A dedicated match is identified or absence is established.",
                    "comparing",
                    depends_on=["inventory_file"],
                ),
                NarrationStep(
                    "report",
                    "Report the finding",
                    "Return the matching function and evidence, or explain the capability gap.",
                    "",
                    "The answer clearly distinguishes an existing helper from a proposed new one.",
                    "reporting",
                    depends_on=["compare_behavior"],
                ),
            ],
            current_step_id="resolve_reference",
        )
        return narration.to_dict()

    return {}

def _formulation(prompt: str, decision: dict[str, Any]) -> dict[str, Any]:
    existing = dict(
        decision.get("problem_formulation")
        or (decision.get("request_understanding") or {}).get("problem_formulation")
        or {}
    )
    if existing:
        return existing
    try:
        from tech_connector.services.problem_formulation_service import build_problem_formulation
        result = build_problem_formulation(
            prompt,
            decision,
            context=dict(
                decision.get("context_snapshot")
                or decision.get("operation_memory")
                or {}
            ),
        )
        return result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    except Exception:
        return {}


def _phase_for_step(row: dict[str, Any], objective: str) -> str:
    action = str(row.get("action") or "").lower()
    text = f"{action} {objective}".lower()
    if action == "capability_gap":
        return "gap_discovery"
    if any(term in text for term in ("interpret", "understand", "resolve reference", "formulate")):
        return "understanding"
    if any(term in text for term in ("plan", "design", "determine capability gap")):
        return "planning"
    if any(term in text for term in ("search", "find", "inspect", "gather", "resolve containing")):
        return "searching"
    if any(term in text for term in ("rank", "compare", "evaluate", "decide")):
        return "comparing"
    if any(term in text for term in ("validate", "verify", "compile", "test")):
        return "validating"
    if any(term in text for term in ("report", "return", "answer", "summarize")):
        return "reporting"
    if any(term in text for term in ("execute", "query", "apply", "modify", "create")):
        return "executing"
    return "planning"


def _short_title(objective: str, phase: str) -> str:
    compact = re.sub(r"\s+", " ", objective).strip().rstrip(".")
    if len(compact) <= 54:
        return compact
    return compact[:51].rstrip() + "..."


def _infer_why(objective: str, formulation: dict[str, Any]) -> str:
    lower = objective.lower()
    if "resolve" in lower and ("file" in lower or "reference" in lower):
        return "The target must be concrete before its members or behavior can be inspected."
    if "find" in lower and ("function" in lower or "symbol" in lower):
        return "The implementation symbols provide stronger evidence than matching filenames or raw words."
    if "containing file" in lower:
        return "The requested file can only be identified after the implementing symbols are known."
    if "rank" in lower or "compare" in lower:
        return "Related helpers must be separated from the implementation that actually satisfies the request."
    if "validate" in lower or "verify" in lower:
        return "The result should be proven against the requested success condition before reporting completion."
    unknowns = list(formulation.get("unknowns") or [])
    if unknowns:
        return f"This step resolves an unknown needed before action: {unknowns[0]}"
    return ""


def _approach_summary(formulation: dict[str, Any], steps: list[NarrationStep]) -> str:
    explicit = str(
        formulation.get("planning_rationale")
        or formulation.get("problem_summary")
        or ""
    ).strip()
    if explicit:
        return explicit
    if len(steps) >= 2:
        return (
            f"First {steps[0].objective.rstrip('.').lower()}, then "
            f"{steps[1].objective.rstrip('.').lower()}."
        )
    return steps[0].objective if steps else "Gather enough evidence before taking action."


def _fallback_steps(formulation: dict[str, Any], interpreted: str) -> list[NarrationStep]:
    deliverables = " ".join(str(x) for x in formulation.get("deliverables") or []).lower()
    subject = str(formulation.get("subject") or interpreted)
    if "file" in deliverables and any(term in subject.lower() for term in ("function", "create", "build", "implementation")):
        return [
            NarrationStep(
                "find_implementations",
                "Find implementing functions",
                f"Find functions that implement {subject}.",
                "Functions provide the evidence needed to identify the correct files.",
                "Relevant implementation functions are identified.",
                "searching",
            ),
            NarrationStep(
                "resolve_files",
                "Resolve containing files",
                "Determine which files contain the candidate functions.",
                "The user asked for files, but the behavior is implemented by functions.",
                "Each candidate function is associated with its source file.",
                "searching",
                depends_on=["find_implementations"],
            ),
            NarrationStep(
                "rank_implementations",
                "Compare implementations",
                "Rank primary implementations above narrow helpers and incidental matches.",
                "A related helper is not necessarily the implementation the user wants.",
                "The strongest evidence-backed files are identified.",
                "comparing",
                depends_on=["resolve_files"],
            ),
            NarrationStep(
                "report_answer",
                "Report the answer",
                "Return the matching files with supporting function evidence.",
                "",
                "The answer includes files, functions, and why they match.",
                "reporting",
                depends_on=["rank_implementations"],
            ),
        ]
    return [
        NarrationStep(
            "understand",
            "Understand the request",
            "Determine the requested outcome, constraints, and evidence needed.",
            "",
            "The request has a concrete success condition.",
            "understanding",
        ),
        NarrationStep(
            "gather",
            "Gather evidence",
            "Gather only the evidence required to satisfy the interpreted request.",
            "Action should wait until enough relevant evidence exists.",
            "The evidence is sufficient for the requested deliverable.",
            "searching",
            depends_on=["understand"],
        ),
        NarrationStep(
            "report",
            "Report the outcome",
            "Return the result with supporting evidence and remaining uncertainty.",
            "",
            "The requested outcome is delivered clearly.",
            "reporting",
            depends_on=["gather"],
        ),
    ]


def _message_for_phase(data: dict[str, Any], phase: str) -> str:
    if not phase:
        return ""
    steps = list(data.get("steps") or [])
    match = next((row for row in steps if str(row.get("phase") or "") == phase), None)
    if not match:
        return ""
    objective = str(match.get("objective") or match.get("title") or "").strip()
    why = str(match.get("why") or "").strip()
    if phase == "understanding":
        prefix = "Understanding: "
    elif phase == "planning":
        prefix = "Planning: "
    elif phase == "searching":
        prefix = "Searching: "
    elif phase == "comparing":
        prefix = "Comparing: "
    elif phase == "validating":
        prefix = "Validating: "
    elif phase == "executing":
        prefix = "Executing: "
    else:
        prefix = "Answering: "
    message = prefix + objective.rstrip(".") + "."
    if why and len(message) + len(why) < 190:
        message += " " + why.rstrip(".") + "."
    return message


def _current_step_message(data: dict[str, Any]) -> str:
    current_id = str(data.get("current_step_id") or "")
    steps = list(data.get("steps") or [])
    row = next((item for item in steps if str(item.get("step_id") or "") == current_id), None)
    if not row and steps:
        row = steps[0]
    if not row:
        return "Understanding the requested outcome..."
    return _message_for_phase(data, str(row.get("phase") or "")) or str(
        row.get("objective") or row.get("title") or ""
    )


def _debug_event_text(event: Any) -> str:
    try:
        return event.markdown() if hasattr(event, "markdown") else str(event)
    except Exception:
        return str(event)
