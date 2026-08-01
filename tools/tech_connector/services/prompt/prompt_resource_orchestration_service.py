"""Resource-aware prompt orchestration policy.

This module does not execute prompts. It defines how Tech Connector should use
local resources for a prompt so deterministic work can overlap while local
model calls remain bounded instead of competing with each other.
"""

from __future__ import annotations

import os
import re
from typing import Any

from reasoning_runtime.prompt import ResourceLane


def build_resource_orchestration_plan(
    prompt: str,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a goal-aware resource policy for a prompt.

    The canonical goal graph is the primary source of execution semantics.
    Regex heuristics remain as a fallback and verification layer when the graph
    is missing, invalid, or incomplete.
    """

    decision = dict(decision or {})
    prompt_text = prompt or ""

    goal_graph = dict(
        decision.get("goal_graph")
        or decision.get("task_graph")
        or {}
    )
    goals = list(goal_graph.get("goals") or goal_graph.get("tasks") or [])
    graph_valid = bool(goal_graph.get("valid", True)) if goal_graph else False

    completed_goal_ids = {
        str(value)
        for value in (
            decision.get("completed_goal_ids")
            or []
        )
    }

    ready_goals, blocked_goals = _partition_goals(
        goals,
        completed_goal_ids=completed_goal_ids,
    )

    estimated_steps = int(
        goal_graph.get("estimated_steps")
        or len(goals)
        or 1
    )

    complexity = (
        _goal_graph_complexity(goals)
        if graph_valid and goals
        else _complexity_score(prompt_text)
    )

    cpu_count = os.cpu_count() or 4
    deterministic_workers = max(2, min(4, cpu_count // 2 or 2))
    if complexity >= 5:
        deterministic_workers = max(3, deterministic_workers)

    requires_project_search = _graph_flag_or_fallback(
        goal_graph,
        "requires_project_search",
        bool(
            re.search(
                r"\b(find|locate|search|inspect|analyze|analyse|review|"
                r"project|file|function|method|class|symbol|dependency|caller|usage)\b",
                prompt_text.lower(),
            )
        ),
    )
    requires_generation = _graph_flag_or_fallback(
        goal_graph,
        "requires_generation",
        bool(
            re.search(
                r"\b(generate|write|draft|create an example|show me how|"
                r"how would i|how do i|implementation example)\b",
                prompt_text.lower(),
            )
        ),
    )
    requires_execution = _graph_flag_or_fallback(
        goal_graph,
        "requires_execution",
        bool(
            re.search(
                r"\b(run|execute|call|launch|apply|perform)\b",
                prompt_text.lower(),
            )
        ),
    )
    requires_validation = _graph_flag_or_fallback(
        goal_graph,
        "requires_validation",
        bool(
            re.search(
                r"\b(validate|validation|compile|syntax|test|verify|check result)\b",
                prompt_text.lower(),
            )
        ),
    )

    requires_mutation = _requires_mutation(
        prompt_text,
        decision,
        goal_graph=goal_graph,
    )

    approval_goal_ids = [
        str(value)
        for value in (goal_graph.get("approval_goal_ids") or [])
    ]
    terminal_goal_ids = [
        str(value)
        for value in (goal_graph.get("terminal_goal_ids") or [])
    ]
    mutation_goal_ids = [
        str(value)
        for value in (goal_graph.get("mutation_goal_ids") or [])
    ]

    model_workers = 1
    lanes: list[ResourceLane] = [
        ResourceLane(
            "goal_scheduler",
            "Goal scheduling",
            1,
            (
                "validate goal graph",
                "resolve dependencies",
                "select next achievable goals",
            ),
        ),
    ]

    if requires_project_search:
        lanes.append(
            ResourceLane(
                "deterministic_discovery",
                "Parallel deterministic discovery",
                deterministic_workers,
                (
                    "project index search",
                    "symbol and dependency lookup",
                    "active file inspection",
                    "known-practice lookup",
                    "read-only host snapshots",
                    "evidence ranking",
                ),
            )
        )

    if requires_generation or any(
        bool(goal.get("requires_reasoning"))
        for goal in goals
    ):
        lanes.append(
            ResourceLane(
                "local_model_serial",
                "Serialized local model work",
                model_workers,
                (
                    "goal interpretation",
                    "design synthesis",
                    "implementation planning",
                    "code or explanation generation",
                ),
            )
        )

    if requires_execution:
        lanes.append(
            ResourceLane(
                "execution_serial",
                "Serialized deterministic execution",
                1,
                (
                    "resolve callable",
                    "validate inputs",
                    "execute function or DCC operation",
                    "collect structured outputs",
                ),
            )
        )

    if requires_mutation:
        lanes.append(
            ResourceLane(
                "mutation_serial",
                "Serialized mutation",
                1,
                (
                    "file writes",
                    "asset or graph edits",
                    "undoable mutations",
                    "artifact reporting",
                ),
            )
        )

    if requires_validation:
        lanes.append(
            ResourceLane(
                "validation_serial",
                "Serialized validation",
                1,
                (
                    "compile or syntax validation",
                    "behavior verification",
                    "read-back checks",
                    "failure diagnosis",
                ),
            )
        )

    lanes.append(
        ResourceLane(
            "reporting",
            "Continuous user reporting",
            1,
            (
                "goal status updates",
                "handoff summaries",
                "approval requests",
                "final report",
            ),
        )
    )

    goal_execution_plan = [
        _goal_execution_assignment(
            goal,
            deterministic_workers=deterministic_workers,
        )
        for goal in goals
    ]

    parallel_goal_groups = _parallel_goal_groups(goals)

    return {
        "framework": "resource_aware_goal_orchestration_v2",
        "compatibility_framework": "resource_aware_prompt_orchestration_v1",
        "goal_graph_valid": graph_valid,
        "primary_goal": (
            goal_graph.get("primary_goal")
            or goal_graph.get("goal")
            or decision.get("primary_goal")
            or ""
        ),
        "goal_type": (
            goal_graph.get("goal_type")
            or decision.get("goal_type")
            or ""
        ),
        "goal_count": len(goals),
        "estimated_steps": estimated_steps,
        "complexity": complexity,
        "requires_mutation": requires_mutation,
        "requires_project_search": requires_project_search,
        "requires_generation": requires_generation,
        "requires_execution": requires_execution,
        "requires_validation": requires_validation,
        "policy": (
            "Use the canonical goal graph when valid; otherwise fall back to "
            "prompt heuristics. Parallelize independent read-only work, serialize "
            "local model work, execution, mutation, and validation, and keep "
            "reporting active."
        ),
        "execution_strategy": {
            "goal_based": bool(graph_valid and goals),
            "regex_fallback_enabled": True,
            "parallel_read_only": True,
            "serialize_models": True,
            "serialize_execution": True,
            "serialize_mutations": True,
            "serialize_validation": True,
            "pause_for_approval": bool(approval_goal_ids),
            "validate_after_mutation": requires_mutation and requires_validation,
            "stop_when_terminal_goal_complete": bool(terminal_goal_ids),
            "resume_from_completed_goals": True,
        },
        "local_model_concurrency": model_workers,
        "deterministic_concurrency": deterministic_workers,
        "lanes": [lane.to_dict() for lane in lanes],
        "goal_execution_plan": goal_execution_plan,
        "parallel_goal_groups": parallel_goal_groups,
        "ready_goal_ids": [
            _goal_id(goal)
            for goal in ready_goals
            if _goal_id(goal)
        ],
        "blocked_goal_ids": [
            _goal_id(goal)
            for goal in blocked_goals
            if _goal_id(goal)
        ],
        "completed_goal_ids": sorted(completed_goal_ids),
        "terminal_goal_ids": terminal_goal_ids,
        "approval_goal_ids": approval_goal_ids,
        "mutation_goal_ids": mutation_goal_ids,
        "stop_conditions": [
            str(goal.get("success_condition") or "")
            for goal in goals
            if str(goal.get("success_condition") or "")
        ],
        "handoff_order": [
            "goal_scheduler -> ready read-only goals",
            "read-only goals -> model synthesis as soon as minimum evidence exists",
            "model synthesis -> execution or mutation only when dependencies and approvals are satisfied",
            "mutation -> validation before downstream dependent goals",
            "all lanes -> reporting with compact structured handoffs",
        ],
        "timeout_policy": {
            "total_work_timeout": "avoid fixed total timeout for long approved work",
            "no_progress_seconds": 30,
            "model_call_policy": "bounded per-goal timeout with visible wait status and compact goal-specific prompts",
            "deterministic_call_policy": "bounded per-function timeout with structured failure and retry metadata",
        },
        "early_completion_policy": {
            "principle": "stop a goal as soon as its success condition is satisfied",
            "applies_to": [
                "retrieval",
                "intent clarification",
                "target selection",
                "planning",
                "generation",
                "execution",
                "validation diagnosis",
                "final reporting",
            ],
            "handoff_unit": "structured outputs matching the goal's produces contract",
            "large_model_rule": "use large models only for goals requiring hard synthesis or code generation",
        },
        "compiled_pipeline_policy": {
            "principle": "after planning is sufficient, convert repeatable operations into deterministic callable pipeline steps",
            "when_to_compile": [
                "the target asset/file/function is known",
                "required inputs and approvals are resolved",
                "the operation may be rerun, validated, or promoted into a saved pipeline",
                "execution can be expressed as project functions or generated wrapper functions",
            ],
            "script_contract": [
                "typed inputs",
                "preflight validation",
                "small undoable steps",
                "structured logs",
                "artifacts/changed files report",
                "verification hooks",
                "rollback notes or rollback function when practical",
            ],
            "execution_rule": "run compiled steps through deterministic function calls; return to model reasoning only for diagnosis, missing context, or failed validation",
        },
        "function_result_loop_policy": {
            "principle": "execute the next achievable goal, inspect its structured result, and check sufficiency before continuing",
            "loop": [
                "select the next goal whose dependencies are satisfied",
                "select its deterministic function or model engine",
                "validate required inputs, approvals, and safety constraints",
                "execute the goal",
                "parse structured outputs, artifacts, warnings, and errors",
                "check the result against the goal success condition",
                "mark complete and unlock dependents, or retry/fallback/clarify",
            ],
            "model_rule": "models select, synthesize, and diagnose; deterministic functions perform bounded work",
            "stop_rule": "stop when the terminal goal succeeds, validation fails unrecoverably, or approval/context is required",
        },
        "model_tier_policy": {
            "intent": "none_deterministic_or_local_fast",
            "deterministic_discovery": "none_deterministic",
            "rag_sufficiency": "none_deterministic_or_local_fast",
            "context_summarization": "local_fast",
            "design_or_explanation": "local_fast_or_plan",
            "implementation_planning": "local_plan_or_deep_when_explicitly_complex",
            "patch_generation": "local_code",
            "validation": "none_deterministic_or_local_code_for_diagnosis",
        },
    }


def render_resource_orchestration_summary(
    plan: dict[str, Any] | None,
) -> str:
    if not plan:
        return ""

    lanes = list(plan.get("lanes") or [])
    lines = [
        "Resource plan:",
        f"- Policy: {plan.get('policy')}",
        f"- Primary goal: {plan.get('primary_goal') or 'Not specified'}",
        f"- Ready goals: {len(plan.get('ready_goal_ids') or [])}",
        f"- Blocked goals: {len(plan.get('blocked_goal_ids') or [])}",
        f"- Deterministic workers: {plan.get('deterministic_concurrency')}",
        f"- Local model workers: {plan.get('local_model_concurrency')}",
    ]

    for lane in lanes[:7]:
        lines.append(
            f"- {lane.get('label')} [{lane.get('key')}]: "
            f"max {lane.get('max_concurrent')}"
        )

    return "\n".join(lines)


def _goal_id(goal: dict[str, Any]) -> str:
    return str(
        goal.get("task_id")
        or goal.get("goal_id")
        or ""
    )


def _partition_goals(
    goals: list[dict[str, Any]],
    *,
    completed_goal_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for goal in goals:
        goal_id = _goal_id(goal)
        if goal_id and goal_id in completed_goal_ids:
            continue

        dependencies = {
            str(value)
            for value in (goal.get("depends_on") or [])
        }

        if dependencies.issubset(completed_goal_ids):
            ready.append(goal)
        else:
            blocked.append(goal)

    return ready, blocked


def _parallel_goal_groups(
    goals: list[dict[str, Any]],
) -> list[list[str]]:
    """Return dependency levels that may be scheduled together.

    Mutating, executing, model-heavy, and validating goals remain isolated even
    when they have no direct dependency conflict.
    """

    by_id = {
        _goal_id(goal): goal
        for goal in goals
        if _goal_id(goal)
    }
    remaining = set(by_id)
    completed: set[str] = set()
    groups: list[list[str]] = []

    while remaining:
        candidates = [
            goal_id
            for goal_id in remaining
            if {
                str(value)
                for value in (by_id[goal_id].get("depends_on") or [])
                if str(value) in by_id
            }.issubset(completed)
        ]

        if not candidates:
            groups.append(sorted(remaining))
            break

        parallel_group: list[str] = []
        serialized: list[str] = []

        for goal_id in candidates:
            goal = by_id[goal_id]
            if _goal_is_parallel_safe(goal):
                parallel_group.append(goal_id)
            else:
                serialized.append(goal_id)

        if parallel_group:
            groups.append(sorted(parallel_group))
            completed.update(parallel_group)
            remaining.difference_update(parallel_group)

        for goal_id in sorted(serialized):
            groups.append([goal_id])
            completed.add(goal_id)
            remaining.remove(goal_id)

    return groups


def _goal_is_parallel_safe(goal: dict[str, Any]) -> bool:
    action = str(goal.get("action") or "").lower()
    goal_type = str(goal.get("goal_type") or "").lower()

    if not bool(goal.get("read_only", True)):
        return False
    if bool(goal.get("requires_confirmation")):
        return False
    if bool(goal.get("requires_reasoning")):
        return False
    if action in {"execute", "modify_code", "validate", "generate", "compose"}:
        return False
    if goal_type in {"modify", "execute", "validate", "generate", "plan"}:
        return False

    return True


def _goal_execution_assignment(
    goal: dict[str, Any],
    *,
    deterministic_workers: int,
) -> dict[str, Any]:
    goal_id = _goal_id(goal)
    action = str(goal.get("action") or "").lower()
    goal_type = str(goal.get("goal_type") or action or "respond").lower()
    capability = str(goal.get("capability") or "").lower()
    read_only = bool(goal.get("read_only", True))
    requires_reasoning = bool(goal.get("requires_reasoning"))

    if goal_type == "locate" or action in {"search", "inspect"}:
        lane = "deterministic_discovery"
        engine = "none_deterministic"
    elif goal_type in {"learn", "explain", "compare", "respond"}:
        lane = "local_model_serial"
        engine = "local_fast"
    elif goal_type in {"generate", "design"} or action in {"generate", "design"}:
        lane = "local_model_serial"
        engine = "local_code" if "code" in capability or goal_type == "generate" else "local_plan"
    elif goal_type == "modify" or action == "modify_code":
        lane = "mutation_serial"
        engine = "local_code"
    elif goal_type == "execute" or action == "execute":
        lane = "execution_serial"
        engine = "deterministic_function"
    elif goal_type == "validate" or action == "validate":
        lane = "validation_serial"
        engine = "none_deterministic_or_local_code_for_diagnosis"
    elif action == "report":
        lane = "reporting"
        engine = "local_fast"
    else:
        lane = "local_model_serial" if requires_reasoning else "deterministic_discovery"
        engine = "local_fast" if requires_reasoning else "none_deterministic"

    return {
        "goal_id": goal_id,
        "title": str(goal.get("title") or goal.get("objective") or goal_id),
        "goal_type": goal_type,
        "action": action,
        "capability": capability,
        "lane": lane,
        "engine": engine,
        "parallel": bool(
            read_only
            and lane == "deterministic_discovery"
            and deterministic_workers > 1
        ),
        "requires_confirmation": bool(goal.get("requires_confirmation")),
        "success_condition": str(goal.get("success_condition") or ""),
        "depends_on": [
            str(value)
            for value in (goal.get("depends_on") or [])
        ],
        "required_inputs": [
            str(value)
            for value in (goal.get("required_inputs") or [])
        ],
        "produces": [
            str(value)
            for value in (goal.get("produces") or [])
        ],
    }


def _graph_flag_or_fallback(
    goal_graph: dict[str, Any],
    key: str,
    fallback: bool,
) -> bool:
    if goal_graph and key in goal_graph:
        return bool(goal_graph.get(key))
    return bool(fallback)


def _goal_graph_complexity(
    goals: list[dict[str, Any]],
) -> int:
    return max(
        1,
        sum(
            max(
                1,
                int(goal.get("estimated_complexity") or 1),
            )
            for goal in goals
        ),
    )


def _complexity_score(prompt: str) -> int:
    """Fallback complexity heuristic used when no valid goal graph exists."""
    text = prompt or ""
    score = 1
    score += min(4, len(text) // 1200)
    score += min(
        3,
        len(
            re.findall(
                r"^\s*\d+[.)]\s+",
                text,
                flags=re.MULTILINE,
            )
        ) // 6,
    )

    lower = text.lower()
    for term in (
        "before making",
        "implementation requirements",
        "after implementation",
        "validate",
        "rollback",
        "compile",
    ):
        if term in lower:
            score += 1

    return min(10, score)


def _requires_mutation(
    prompt: str,
    decision: dict[str, Any],
    *,
    goal_graph: dict[str, Any] | None = None,
) -> bool:
    """Determine mutation using graph semantics first and regexes as fallback.

    Regexes are intentionally retained for legacy callers and incomplete goal
    graphs. They do not override an explicit valid read-only graph.
    """

    graph = dict(goal_graph or {})
    goals = list(graph.get("goals") or graph.get("tasks") or [])

    if graph:
        mutation_goal_ids = {
            str(value)
            for value in (graph.get("mutation_goal_ids") or [])
        }
        if mutation_goal_ids:
            return True

        if any(
            not bool(goal.get("read_only", True))
            or str(goal.get("goal_type") or "").lower() == "modify"
            or str(goal.get("action") or "").lower() == "modify_code"
            for goal in goals
        ):
            return True

        if bool(graph.get("valid", True)) and goals:
            return False

    mutation_scope = str(
        decision.get("mutation_scope")
        or ""
    ).lower()
    if mutation_scope and mutation_scope != "read_only":
        return True

    understanding = dict(
        decision.get("request_understanding")
        or {}
    )
    if understanding:
        if bool(understanding.get("mutation_requested")):
            return True
        if bool(understanding.get("read_only_requested")):
            return False

    lower = (prompt or "").lower()
    if re.search(
        r"\b(do not edit|do not change|do not make changes|"
        r"plan only|explain how|show an example|read only)\b",
        lower,
    ):
        return False

    return bool(
        re.search(
            r"\b(add|create|implement|write|patch|modify|update|fix|"
            r"connect|wire|refactor|build|delete|remove|rename)\b",
            lower,
        )
    )
