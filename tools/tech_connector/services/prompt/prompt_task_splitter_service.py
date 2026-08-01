"""Deterministic long-prompt staging helpers.

Large prompts are decomposed into ordered clauses, staged chunks, and an
achievable task graph while preserving conditions, approvals, constraints, and
cross-clause references. The original contract remains intact for audit/history.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from reasoning_runtime.prompt import (
    ComposedClause,
    ComposedRequest,
    GoalClause,
    PromptChunk,
    PromptClause,
    PromptClausePlan,
    PromptStage,
    StagedPromptContract,
)


LONG_PROMPT_STAGE_THRESHOLD = 2600


def should_stage_prompt(prompt: str, threshold: int = LONG_PROMPT_STAGE_THRESHOLD) -> bool:
    text = prompt or ""
    if len(text) < int(threshold or LONG_PROMPT_STAGE_THRESHOLD):
        return False
    lower = text.lower()
    return (
        "before making any changes" in lower
        or "implementation requirements" in lower
        or "after implementation" in lower
        or len(re.findall(r"^\s*\d+[.)]\s+", text, flags=re.MULTILINE)) >= 8
    )


def build_staged_prompt_contract(prompt: str) -> StagedPromptContract:
    text = prompt or ""
    source_hash = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    user_goal = _first_nonempty_line(text)
    items = _numbered_items(text)
    if not items:
        items = [line.strip() for line in text.splitlines() if line.strip()]

    chunks = _chunk_items(items)
    investigation: list[str] = []
    implementation: list[str] = []
    validation: list[str] = []
    reporting: list[str] = []
    global_constraints: list[str] = []

    for item in items:
        lower = item.lower()
        target = global_constraints
        if any(word in lower for word in ("inspect", "identify", "determine", "found", "missing information", "propose", "plan")):
            target = investigation
        if any(word in lower for word in ("create", "extend", "integrate", "preserve", "networked", "gameplay ability", "architecture")):
            target = implementation
        if any(word in lower for word in ("compile", "syntax", "validation", "validate", "test", "rollback", "unrelated")):
            target = validation
        if any(word in lower for word in ("report", "warnings", "assumptions", "completed", "failed")):
            target = reporting
        if any(word in lower for word in ("do not fabricate", "before editing", "before making", "do not skip", "preserve existing")):
            global_constraints.append(_clip_instruction(item))
        else:
            target.append(_clip_instruction(item))

    if not investigation:
        investigation = [_clip_instruction(items[0])] if items else ["Understand the user goal and identify project evidence before changing anything."]

    active = PromptStage(
        "investigation_plan",
        "Stage 1 - Inspect existing project state and propose a staged implementation plan",
        _dedupe(investigation)[:10],
    )
    deferred = [
        PromptStage("implementation", "Stage 2 - Implement only after plan approval", _dedupe(implementation)[:12]),
        PromptStage("validation", "Stage 3 - Compile and validate behavior", _dedupe(validation)[:10]),
        PromptStage("reporting", "Stage 4 - Report verified outcome and unresolved risks", _dedupe(reporting)[:10]),
    ]
    deferred = [stage for stage in deferred if stage.instructions]
    return StagedPromptContract(
        original_chars=len(text),
        source_hash=source_hash,
        user_goal=_clip_instruction(user_goal, limit=420),
        chunks=chunks,
        active_stage=active,
        global_constraints=_dedupe(global_constraints)[:10],
        deferred_stages=deferred,
    )


def staged_prompt_for_llm(prompt: str, threshold: int = LONG_PROMPT_STAGE_THRESHOLD) -> tuple[str, StagedPromptContract | None]:
    if not should_stage_prompt(prompt, threshold):
        return prompt, None
    contract = build_staged_prompt_contract(prompt)
    return contract.render_for_llm(), contract


def _numbered_items(text: str) -> list[str]:
    matches = list(re.finditer(r"^\s*(\d+)[.)]\s+", text or "", flags=re.MULTILINE))
    if not matches:
        return []
    items: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        body = re.sub(r"\s+", " ", body)
        if body:
            items.append(f"{match.group(1)}. {body}")
    return items


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _chunk_items(items: list[str], *, chunk_size: int = 6, max_chunks: int = 8) -> list[PromptChunk]:
    if not items:
        return []
    chunks: list[PromptChunk] = []
    for idx in range(0, len(items), chunk_size):
        if len(chunks) >= max_chunks:
            remaining = len(items) - idx
            if remaining > 0:
                chunks.append(
                    PromptChunk(
                        key=f"chunk_{len(chunks) + 1}",
                        title=f"Chunk {len(chunks) + 1} - Remaining requirements",
                        items=[f"{remaining} additional requirement(s) remain in the source contract; preserve the contract hash and continue staged execution."],
                    )
                )
            break
        group = items[idx: idx + chunk_size]
        title = _chunk_title(group, len(chunks) + 1)
        chunks.append(
            PromptChunk(
                key=f"chunk_{len(chunks) + 1}",
                title=title,
                items=[_clip_instruction(item, limit=220) for item in group],
            )
        )
    return chunks


def _chunk_title(items: list[str], index: int) -> str:
    joined = " ".join(items).lower()
    if any(word in joined for word in ("inspect", "identify", "determine", "found", "plan", "missing information")):
        label = "Discovery and plan"
    elif any(word in joined for word in ("create", "extend", "integrate", "preserve", "networked", "gameplay")):
        label = "Implementation requirements"
    elif any(word in joined for word in ("compile", "syntax", "validate", "test", "rollback")):
        label = "Validation and rollback"
    elif any(word in joined for word in ("report", "warnings", "assumptions", "completed", "failed")):
        label = "Reporting"
    else:
        label = "Task requirements"
    return f"Chunk {index} - {label}"


def _clip_instruction(text: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 18].rstrip() + " ...[condensed]"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out

# --- Canonical request task graph support ---

from typing import Any


def _canonical_goal_rows(
    understanding: Any,
    *,
    problem_formulation: dict[str, Any] | None = None,
    semantic_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build canonical goals from upstream formulation/contract data.

    Goal graph ownership lives here. Intent-service task rows are used only as
    a compatibility fallback when neither upstream source exposes a plan.
    """
    formulation = dict(problem_formulation or {})
    contract = dict(semantic_contract or {})
    rows = list(formulation.get("candidate_plan") or contract.get("plan_steps") or [])
    if rows:
        goals: list[dict[str, Any]] = []
        for index, raw in enumerate(rows, start=1):
            item = dict(raw or {})
            goal_id = str(item.get("goal_id") or item.get("step_id") or f"goal_{index}")
            action = str(item.get("action") or "inspect")
            read_only = bool(item.get("read_only", action not in {"modify", "modify_code", "execute"}))
            goals.append({
                "task_id": goal_id,
                "goal_id": goal_id,
                "title": str(item.get("title") or item.get("objective") or goal_id),
                "action": action,
                "objective": str(item.get("objective") or ""),
                "target": str(item.get("target") or contract.get("subject_text") or ""),
                "capability": str(item.get("capability") or {
                    "search": "project_index", "discover": "project_index",
                    "inspect": "project_index", "resolve": "target_resolution",
                    "rank": "evidence_ranking", "plan": "implementation_planning",
                    "modify": "project_edit", "modify_code": "project_edit",
                    "execute": "dcc_execution", "validate": "validation",
                    "report": "reporting", "analyze": "semantic_reasoning",
                    "preflight": "validation",
                }.get(action, action)),
                "depends_on": [str(v) for v in item.get("depends_on") or []],
                "produces": [str(v) for v in item.get("produces") or []],
                "required_inputs": [str(v) for v in item.get("required_inputs") or []],
                "read_only": read_only,
                "goal_type": str(item.get("goal_type") or contract.get("goal_type") or getattr(understanding, "goal_type", "")),
                "success_condition": str(item.get("success_condition") or ""),
                "conditional_on": str(item.get("conditional_on") or ""),
                "requires_reasoning": bool(item.get("requires_reasoning", action in {"analyze", "rank", "plan", "modify", "modify_code", "report"})),
                "requires_confirmation": bool(item.get("requires_confirmation", not read_only and action in {"modify", "modify_code", "execute"})),
                "estimated_complexity": int(item.get("estimated_complexity") or (2 if action in {"analyze", "rank", "plan", "modify", "modify_code"} else 1)),
                "terminal": index == len(rows),
                "metadata": {"canonical_source": "problem_formulation" if formulation.get("candidate_plan") else "semantic_execution_contract"},
            })
        return goals
    return [task.to_dict() for task in getattr(understanding, "tasks", [])]


def build_request_task_graph(
    prompt: str,
    *,
    host: str = "",
    understanding: Any | None = None,
    problem_formulation: dict[str, Any] | None = None,
    semantic_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical achievable-goal graph used by routing and execution.

    PromptIntentService owns semantic interpretation. This service exclusively
    owns goal decomposition, graph validation, and execution metadata, and preserves
    backward-compatible ``tasks`` output for existing consumers.
    """
    from tech_connector.services.prompt.prompt_intent_service import understand_prompt_request
    try:
        clause_plan = split_prompt_clauses(prompt).to_dict()
    except Exception:
        clause_plan = {}
    try:
        composed_request = compose_request(prompt).to_dict()
    except Exception:
        composed_request = {}

    if understanding is None:
        understanding = understand_prompt_request(prompt, host=host)
    problem_formulation = dict(problem_formulation or {})
    semantic_contract = dict(semantic_contract or {})
    goals = _canonical_goal_rows(
        understanding,
        problem_formulation=problem_formulation,
        semantic_contract=semantic_contract,
    )

    goal_ids = {
        str(goal.get("task_id") or goal.get("goal_id") or "")
        for goal in goals
        if str(goal.get("task_id") or goal.get("goal_id") or "")
    }

    invalid_dependencies: list[dict[str, str]] = []
    duplicate_goal_ids: list[str] = []
    seen_goal_ids: set[str] = set()

    for goal in goals:
        goal_id = str(goal.get("task_id") or goal.get("goal_id") or "")
        if goal_id in seen_goal_ids:
            duplicate_goal_ids.append(goal_id)
        elif goal_id:
            seen_goal_ids.add(goal_id)

        for dependency in goal.get("depends_on") or []:
            dependency_id = str(dependency)
            if dependency_id not in goal_ids:
                invalid_dependencies.append(
                    {
                        "task_id": goal_id,
                        "goal_id": goal_id,
                        "missing_dependency": dependency_id,
                    }
                )

    dependency_cycles = _find_dependency_cycles(goals)
    ordered_goals = _topological_goal_order(goals)

    terminal_goal_ids = [
        str(goal.get("task_id") or goal.get("goal_id") or "")
        for goal in goals
        if bool(goal.get("terminal"))
    ]
    if not terminal_goal_ids and goals:
        depended_on = {
            str(dependency)
            for goal in goals
            for dependency in (goal.get("depends_on") or [])
        }
        terminal_goal_ids = [
            str(goal.get("task_id") or goal.get("goal_id") or "")
            for goal in goals
            if str(goal.get("task_id") or goal.get("goal_id") or "") not in depended_on
        ]

    required_capabilities = _ordered_unique(
        str(goal.get("capability") or "")
        for goal in goals
        if goal.get("capability")
    )
    required_inputs = _ordered_unique(
        str(value)
        for goal in goals
        for value in (goal.get("required_inputs") or [])
        if value
    )
    produced_outputs = _ordered_unique(
        str(value)
        for goal in goals
        for value in (goal.get("produces") or [])
        if value
    )
    approval_goal_ids = [
        str(goal.get("task_id") or goal.get("goal_id") or "")
        for goal in goals
        if bool(goal.get("requires_confirmation"))
    ]
    reasoning_goal_ids = [
        str(goal.get("task_id") or goal.get("goal_id") or "")
        for goal in goals
        if bool(goal.get("requires_reasoning"))
    ]
    mutation_goal_ids = [
        str(goal.get("task_id") or goal.get("goal_id") or "")
        for goal in goals
        if not bool(goal.get("read_only", True))
    ]

    graph_valid = not invalid_dependencies and not duplicate_goal_ids and not dependency_cycles

    return {
        "framework": "canonical_request_goal_graph_v4",
        "compatibility_framework": "canonical_request_task_graph_v1",
        "problem_formulation": problem_formulation,
        "composed_request": composed_request,
        "composition_framework": composed_request.get("framework", ""),
        "composition_goals": list(composed_request.get("goals") or []),
        "composition_clauses": list(composed_request.get("clauses") or []),
        "composition_shared_context": dict(composed_request.get("shared_context") or {}),
        "composition_global_constraints": list(composed_request.get("global_constraints") or []),
        "composition_unresolved_relationships": list(composed_request.get("unresolved_relationships") or []),
        "clause_framework": clause_plan.get("framework", ""),
        "clauses": list(clause_plan.get("clauses") or []),
        "clause_confidence": float(clause_plan.get("confidence") or 0.0),
        "has_conditions": bool(clause_plan.get("has_conditions")),
        "has_approval_gate": bool(clause_plan.get("has_approval_gate")),
        "target_container_type": understanding.target_container_type,
        "target_container_query": understanding.target_container_query,
        "target_container_path": understanding.target_container_path,
        "requested_member_type": understanding.requested_member_type,
        "member_behavior": understanding.member_behavior,
        "reference_scope": understanding.reference_scope,
        "semantic_execution_contract": dict(semantic_contract),
        "semantic_plan_steps": list(
            semantic_contract.get("plan_steps")
            or []
        ),
        "planning_rationale": str(
            semantic_contract.get("planning_rationale")
            or ""
        ),
        "goal": understanding.normalized_goal,
        "primary_goal": understanding.primary_goal or understanding.normalized_goal,
        "goal_type": understanding.goal_type,
        "primary_intent": understanding.primary_intent,
        "primary_route": understanding.primary_route,
        "goals": goals,
        "tasks": goals,
        "ordered_goals": ordered_goals,
        "terminal_goal_ids": terminal_goal_ids,
        "required_capabilities": required_capabilities,
        "required_inputs": required_inputs,
        "produced_outputs": produced_outputs,
        "approval_goal_ids": approval_goal_ids,
        "reasoning_goal_ids": reasoning_goal_ids,
        "mutation_goal_ids": mutation_goal_ids,
        "requires_project_search": bool(understanding.requires_project_search),
        "requires_graph": bool(understanding.requires_graph),
        "requires_generation": bool(understanding.requires_generation),
        "requires_validation": bool(understanding.requires_validation),
        "requires_execution": bool(understanding.requires_execution),
        "requires_clarification": bool(understanding.requires_clarification),
        "requires_examples": bool(understanding.requires_examples),
        "requires_reuse_search": bool(understanding.requires_reuse_search),
        "estimated_steps": int(understanding.estimated_steps or len(goals)),
        "estimated_complexity": sum(
            max(1, int(goal.get("estimated_complexity") or 1))
            for goal in goals
        ),
        "constraints": list(understanding.constraints),
        "expected_outputs": list(understanding.expected_outputs),
        "stop_conditions": list(understanding.stop_conditions),
        "valid": graph_valid,
        "invalid_dependencies": invalid_dependencies,
        "duplicate_goal_ids": duplicate_goal_ids,
        "dependency_cycles": dependency_cycles,
        "confidence": understanding.confidence,
        "source": understanding.source,
        "model_name": understanding.model_name,
    }


def task_graph_route(task_graph: dict[str, Any]) -> str:
    """Derive the route from terminal intent and achievable-goal semantics.

    Guidance and example-generation requests intentionally remain on the chat
    path even when they include project search as a supporting goal.
    """
    goals = list(task_graph.get("goals") or task_graph.get("tasks") or [])
    primary_route = str(task_graph.get("primary_route") or "chat")
    goal_type = str(task_graph.get("goal_type") or "").lower()

    actions = {str(goal.get("action") or "") for goal in goals}
    capabilities = {str(goal.get("capability") or "") for goal in goals}
    has_mutation = any(not bool(goal.get("read_only", True)) for goal in goals)

    if primary_route == "dcc_query" or "dcc_query" in capabilities:
        return "dcc_query"

    if primary_route == "project_search" and bool(task_graph.get("requires_project_search")):
        return "project_search"

    if goal_type in {"learn", "explain", "compare", "respond"}:
        return "chat"

    if primary_route == "target_discovery" and (
        goal_type in {"plan", "validate"}
        or bool(
            capabilities.intersection(
                {"target_resolution", "implementation_planning", "project_edit"}
            )
        )
    ):
        return "target_discovery"

    if has_mutation and (
        "modify_code" in actions
        or "project_edit" in capabilities
        or goal_type == "modify"
    ):
        return "target_discovery"

    if "execute" in actions or "dcc_execution" in capabilities or goal_type == "execute":
        return "dcc_execute"

    if (
        "compose" in actions
        or "action_graph" in capabilities
        or "workflow_graph" in capabilities
        or goal_type == "plan" and bool(task_graph.get("requires_graph"))
    ):
        return "pipeline_graph"

    if primary_route == "chat" and bool(task_graph.get("requires_generation")):
        return "chat"

    if actions.intersection({"search", "inspect"}) or bool(task_graph.get("requires_project_search")):
        return "project_search"

    return primary_route


def next_achievable_goals(
    task_graph: dict[str, Any],
    completed_goal_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return goals whose dependencies are satisfied and which are not complete."""
    completed = {str(value) for value in (completed_goal_ids or [])}
    goals = list(task_graph.get("ordered_goals") or task_graph.get("goals") or task_graph.get("tasks") or [])
    ready: list[dict[str, Any]] = []

    for goal in goals:
        goal_id = str(goal.get("task_id") or goal.get("goal_id") or "")
        if not goal_id or goal_id in completed:
            continue
        dependencies = {str(value) for value in (goal.get("depends_on") or [])}
        if dependencies.issubset(completed):
            ready.append(goal)

    return ready


def goal_graph_summary(task_graph: dict[str, Any]) -> dict[str, Any]:
    """Return a compact execution-facing summary of the goal graph."""
    goals = list(task_graph.get("goals") or task_graph.get("tasks") or [])
    return {
        "framework": task_graph.get("framework", "canonical_request_goal_graph_v2"),
        "primary_goal": task_graph.get("primary_goal") or task_graph.get("goal") or "",
        "goal_type": task_graph.get("goal_type") or "",
        "primary_route": task_graph.get("primary_route") or "",
        "goal_count": len(goals),
        "estimated_steps": int(task_graph.get("estimated_steps") or len(goals)),
        "estimated_complexity": int(task_graph.get("estimated_complexity") or 0),
        "valid": bool(task_graph.get("valid", True)),
        "terminal_goal_ids": list(task_graph.get("terminal_goal_ids") or []),
        "approval_goal_ids": list(task_graph.get("approval_goal_ids") or []),
        "mutation_goal_ids": list(task_graph.get("mutation_goal_ids") or []),
        "required_capabilities": list(task_graph.get("required_capabilities") or []),
        "requires_project_search": bool(task_graph.get("requires_project_search")),
        "requires_generation": bool(task_graph.get("requires_generation")),
        "requires_validation": bool(task_graph.get("requires_validation")),
        "requires_execution": bool(task_graph.get("requires_execution")),
    }


def _ordered_unique(values) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = str(value or "")
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _goal_id(goal: dict[str, Any]) -> str:
    return str(goal.get("task_id") or goal.get("goal_id") or "")


def _find_dependency_cycles(goals: list[dict[str, Any]]) -> list[list[str]]:
    graph = {
        _goal_id(goal): [str(value) for value in (goal.get("depends_on") or [])]
        for goal in goals
        if _goal_id(goal)
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            try:
                start = stack.index(node)
            except ValueError:
                start = 0
            cycle = stack[start:] + [node]
            if cycle not in cycles:
                cycles.append(cycle)
            return

        visiting.add(node)
        stack.append(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)

    return cycles


def _topological_goal_order(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {_goal_id(goal): goal for goal in goals if _goal_id(goal)}
    ordered: list[dict[str, Any]] = []
    remaining = list(goals)
    resolved: set[str] = set()

    while remaining:
        progressed = False
        next_remaining: list[dict[str, Any]] = []

        for goal in remaining:
            goal_id = _goal_id(goal)
            dependencies = {
                str(value)
                for value in (goal.get("depends_on") or [])
                if str(value) in by_id
            }
            if dependencies.issubset(resolved):
                ordered.append(goal)
                if goal_id:
                    resolved.add(goal_id)
                progressed = True
            else:
                next_remaining.append(goal)

        if not progressed:
            ordered.extend(next_remaining)
            break
        remaining = next_remaining

    return ordered


_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("approval", r"\b(wait for approval|await approval|ask for approval|stop before editing|stop before changing|do not edit until|don't edit until|dont edit until)\b"),
    ("validate", r"\b(validate|verify|compile|syntax[- ]?check|test|check the result|confirm it works)\b"),
    ("report", r"\b(report|summarize|summarise|explain what changed|show me the result|tell me what changed|document)\b"),
    ("plan", r"\b(plan|propose|outline|architect|map out|come up with improvements?|design improvements?)\b"),
    ("modify_code", r"\b(fix|patch|modify|edit|update|refactor|rename|remove|delete|wire|connect|implement)\b"),
    ("generate", r"\b(generate|write|create|build|make|add|design|draft|produce)\b"),
    ("execute", r"\b(run|execute|launch|apply|perform|open|move|select|import|export)\b"),
    ("search", r"\b(find|locate|search|look for|identify|inspect|review|analyze|analyse|determine|check whether|see if)\b"),
    ("explain", r"\b(explain|teach|show me how|how would|how do|how can|compare|describe)\b"),
)

_CONSTRAINT_PATTERN = re.compile(
    r"\b(do not|don't|dont|never|only|must|without|preserve|reuse|before|after|until)\b",
    re.IGNORECASE,
)

_LIST_PREFIX = re.compile(
    r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s+",
    re.MULTILINE,
)

_CONNECTOR_SPLIT = re.compile(
    r"\s*(?:;|\n+|(?<=[.!?])\s+|"
    r"\b(?:and then|then|after that|next|finally|before that)\b)\s*",
    re.IGNORECASE,
)

_CONDITION_PREFIX = re.compile(
    r"^\s*(if|unless|when|once|otherwise|else|or else)\b[\s,:-]*(.*)$",
    re.IGNORECASE,
)

_PRONOUN_START = re.compile(
    r"^\s*(it|that|this|them|those|these|the result|the code|the file|the function|the helper)\b",
    re.IGNORECASE,
)


def normalize_prompt_text(text: str) -> str:
    from reasoning_runtime.prompt import normalize_prompt_text as _normalize_prompt_text

    return _normalize_prompt_text(text)


def compose_request(text: str) -> ComposedRequest:
    """Build a role-aware request graph before route selection.

    Separators are treated as evidence only. Each phrase is classified as a
    goal, argument, context, validation, constraint, output request, alternative,
    or dependent goal, then attached to the goal it modifies.
    """
    original = str(text or "")
    normalized = normalize_prompt_text(original)
    if not normalized:
        return ComposedRequest(original, "", "", (), (), confidence=1.0)

    shared_context, body = _extract_shared_context(normalized)
    segments = _composition_segments_with_spans(body)
    clauses: list[ComposedClause] = []
    goal_builders: list[dict[str, Any]] = []
    last_goal_id = ""
    unresolved: list[str] = []
    global_constraints: list[str] = []

    for index, (segment, start, end, connector) in enumerate(segments, start=1):
        cleaned = segment.strip(" \t,;.?!")
        if not cleaned:
            continue
        clause_id = f"clause_{len(clauses) + 1}"
        role, action, object_type, target, args, reason, confidence = _classify_composed_clause(
            cleaned,
            connector=connector,
            prior_goal=goal_builders[-1] if goal_builders else {},
        )
        if (
            clauses
            and clauses[-1].role == "ARGUMENT"
            and clauses[-1].action == "name"
            and re.match(r"^[A-Za-z_][A-Za-z0-9_:.-]*$", cleaned)
        ):
            role, action, object_type, target = "ARGUMENT", "name", "", ""
            args = {"name": cleaned.rstrip(".?!,;:")}
            reason, confidence = "additional plural naming argument", 0.9
        references = _clause_references(cleaned, last_goal_id)
        attaches_to = ""
        depends_on: list[str] = []

        if role == "GOAL":
            goal_id = f"goal_{len(goal_builders) + 1}"
            produces = [f"${goal_id}.output"] if action in {"create", "make", "build", "add", "generate"} else []
            goal_args = dict(args)
            if goal_args.get("names"):
                goal_args.pop("name", None)
                goal_args.pop("names", None)
            goal_builders.append(
                {
                    "goal_id": goal_id,
                    "source_clause_id": clause_id,
                    "action": action,
                    "object_type": object_type,
                    "target": target,
                    "arguments": goal_args,
                    "modifiers": [],
                    "constraints": [],
                    "validations": [],
                    "depends_on": [],
                    "consumes": [],
                    "produces": produces,
                    "confidence": confidence,
                }
            )
            if args.get("names"):
                _merge_plural_name_arguments(goal_builders, list(args.get("names") or []))
            last_goal_id = goal_id
            attaches_to = goal_id
        elif role == "DEPENDENT_GOAL":
            goal_id = f"goal_{len(goal_builders) + 1}"
            dependencies = _dependent_goal_dependencies(cleaned, goal_builders, last_goal_id)
            depends_on.extend(dependencies)
            consumes = [f"${dependency}.output" for dependency in dependencies] if _uses_prior_output(cleaned) else []
            goal_builders.append(
                {
                    "goal_id": goal_id,
                    "source_clause_id": clause_id,
                    "action": action,
                    "object_type": object_type,
                    "target": target,
                    "arguments": dict(args),
                    "modifiers": [],
                    "constraints": [],
                    "validations": [],
                    "depends_on": list(depends_on),
                    "consumes": consumes,
                    "produces": [f"${goal_id}.output"] if action in {"create", "make", "build", "add", "generate"} else [],
                    "confidence": confidence,
                }
            )
            last_goal_id = goal_id
            attaches_to = goal_id
        elif role in {"ARGUMENT", "MODIFIER", "CONTEXT", "VALIDATION", "CONSTRAINT", "OUTPUT_REQUEST", "ALTERNATIVE"}:
            attaches_to = _argument_attachment_goal(goal_builders, args, cleaned) or last_goal_id
            if not attaches_to and role not in {"CONTEXT", "CONSTRAINT"}:
                unresolved.append(f"{clause_id}:{role}:no_goal_to_attach")
            if role == "CONTEXT":
                shared_context.update(args)
            elif role == "CONSTRAINT":
                if attaches_to:
                    _append_goal_list(goal_builders, attaches_to, "constraints", cleaned)
                else:
                    global_constraints.append(cleaned)
            elif role == "VALIDATION":
                _append_goal_list(goal_builders, attaches_to, "validations", cleaned)
            elif role == "ARGUMENT":
                if args.get("names"):
                    _merge_plural_name_arguments(goal_builders, list(args.get("names") or []))
                else:
                    _merge_goal_arguments(goal_builders, attaches_to, args)
            elif role == "MODIFIER":
                _append_goal_list(goal_builders, attaches_to, "modifiers", cleaned)
                _merge_goal_arguments(goal_builders, attaches_to, args)
            elif role == "OUTPUT_REQUEST":
                _append_goal_list(goal_builders, attaches_to, "modifiers", f"output:{cleaned}")
            elif role == "ALTERNATIVE":
                existing = _goal_by_id(goal_builders, attaches_to)
                if existing is not None:
                    existing.setdefault("arguments", {}).setdefault("alternatives", []).extend(args.get("alternatives", []))

        clauses.append(
            ComposedClause(
                clause_id=clause_id,
                source_text=segment,
                normalized_text=cleaned,
                role=role,
                action=action,
                object_type=object_type,
                target=target,
                attaches_to=attaches_to,
                arguments=dict(args),
                references=references,
                depends_on=tuple(depends_on),
                source_span=(start, end),
                confidence=confidence,
                reason=reason,
            )
        )

    goals = tuple(
        GoalClause(
            goal_id=str(item.get("goal_id") or ""),
            source_clause_id=str(item.get("source_clause_id") or ""),
            action=str(item.get("action") or ""),
            object_type=str(item.get("object_type") or ""),
            target=str(item.get("target") or ""),
            arguments=dict(item.get("arguments") or {}),
            modifiers=tuple(item.get("modifiers") or ()),
            constraints=tuple(item.get("constraints") or ()),
            validations=tuple(item.get("validations") or ()),
            depends_on=tuple(item.get("depends_on") or ()),
            consumes=tuple(item.get("consumes") or ()),
            produces=tuple(item.get("produces") or ()),
            confidence=float(item.get("confidence") or 0.5),
        )
        for item in goal_builders
    )
    primary = _primary_objective(goals, normalized)
    confidence = round(
        sum(clause.confidence for clause in clauses) / len(clauses),
        3,
    ) if clauses else 1.0
    return ComposedRequest(
        original_text=original,
        normalized_text=normalized,
        primary_objective=primary,
        goals=goals,
        clauses=tuple(clauses),
        shared_context=shared_context,
        global_constraints=tuple(global_constraints),
        unresolved_relationships=tuple(unresolved),
        confidence=confidence,
    )


_COMPOSITION_CONNECTOR = re.compile(
    r"\s*(?P<connector>;|,|\+|\b(?:and then|then|after that|next|finally|but|plus|also|and|while|before|after|with|using)\b)\s*",
    re.IGNORECASE,
)


def _extract_shared_context(text: str) -> tuple[dict[str, Any], str]:
    shared: dict[str, Any] = {}
    body = text
    host_match = re.match(r"^\s*in\s+(maya|unreal|blender|houdini|unity)\s*,?\s*(.+)$", text, re.IGNORECASE)
    if host_match:
        shared["host"] = host_match.group(1).lower()
        body = host_match.group(2).strip()
    return shared, body


def _composition_segments_with_spans(text: str) -> list[tuple[str, int, int, str]]:
    text = _protect_plural_name_connectors(text)
    parts: list[tuple[str, int, int, str]] = []
    cursor = 0
    connector = ""
    for match in _COMPOSITION_CONNECTOR.finditer(text):
        piece = text[cursor:match.start()].strip()
        if piece:
            leading = len(text[cursor:match.start()]) - len(text[cursor:match.start()].lstrip())
            piece_start = cursor + leading
            parts.append((piece, piece_start, piece_start + len(piece), connector))
        connector = match.group("connector").strip().lower()
        cursor = match.end()
    piece = text[cursor:].strip()
    if piece:
        leading = len(text[cursor:]) - len(text[cursor:].lstrip())
        piece_start = cursor + leading
        parts.append((piece, piece_start, piece_start + len(piece), connector))
    expanded: list[tuple[str, int, int, str]] = []
    for piece, start, end, piece_connector in parts:
        implicit = _implicit_action_segments(piece)
        if len(implicit) <= 1:
            expanded.append((piece, start, end, piece_connector))
            continue
        for implicit_index, (implicit_piece, implicit_start, implicit_end, implicit_connector) in enumerate(implicit):
            expanded.append((
                implicit_piece,
                start + implicit_start,
                start + implicit_end,
                piece_connector if implicit_index == 0 else implicit_connector,
            ))
    return expanded or parts or [(text, 0, len(text), "")]


def _protect_plural_name_connectors(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)} & {match.group(2)}"

    protected = str(text or "")
    pattern = re.compile(
        r"\b((?:call|name|rename)\s+them\s+[A-Za-z_][A-Za-z0-9_:.-]*)\s+and\s+([A-Za-z_][A-Za-z0-9_:.-]*)\b",
        re.IGNORECASE,
    )
    previous = None
    while previous != protected:
        previous = protected
        protected = pattern.sub(replace, protected)
    return protected


_IMPLICIT_ACTION_RE = re.compile(
    r"\b(create|make|build|add|generate|find|locate|search|identify|inspect|review|read|open|refresh|export|run|plan|propose|suggest|connect|wire|attach|parent|constrain|assign|move|place|position|aim|orient|skin|freeze|select|name|rename|verify|validate|check|confirm|explain|show|list|summari[sz]e|report|change|update|delete|remove)\b",
    re.IGNORECASE,
)


def _implicit_action_segments(text: str) -> list[tuple[str, int, int, str]]:
    matches = list(_IMPLICIT_ACTION_RE.finditer(text or ""))
    if len(matches) < 2:
        return [(text, 0, len(text), "")]
    segments: list[tuple[str, int, int, str]] = []
    prefix_added = False
    first_action = matches[0].group(1).lower()
    if (
        matches[0].start() > 0
        and first_action not in {"name", "rename"}
        and _looks_like_additional_object(text[:matches[0].start()])
    ):
        prefix = text[:matches[0].start()].strip(" ,;.?!")
        if prefix:
            leading = len(text[:matches[0].start()]) - len(text[:matches[0].start()].lstrip(" ,;.?!"))
            segments.append((prefix, leading, leading + len(prefix), ""))
            prefix_added = True
    for index, match in enumerate(matches):
        start = match.start() if prefix_added or index > 0 else 0
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        piece = text[start:end].strip(" ,;.?!")
        if piece:
            leading = len(text[start:end]) - len(text[start:end].lstrip(" ,;.?!"))
            piece_start = start + leading
            segments.append((piece, piece_start, piece_start + len(piece), "implicit" if index else ""))
    return segments


def _classify_composed_clause(
    text: str,
    *,
    connector: str,
    prior_goal: dict[str, Any],
) -> tuple[str, str, str, str, dict[str, Any], str, float]:
    lower = text.lower()
    args = _extract_clause_arguments(text)

    if re.search(r"\b(?:are we|do we|where|which|what|check if|check whether|see if)\b.*\b(?:import|imports|importing|load|loads|loading|refresh|route|call|calls|called)\b", lower):
        return "GOAL", "find", _infer_object_type(text), text.strip(" ."), args, "code/project question requiring discovery", 0.9
    if not prior_goal and re.search(r"\bcheck\b.*\b(?:api|project|tree|details|import|route|refresh|tab)\b", lower):
        return "GOAL", "find", _infer_object_type(text), text.strip(" ."), args, "project check requiring discovery", 0.88
    if not prior_goal and re.search(r"\bcheck\b.*\b(?:startup|path|ui|slow|slowness|freeze|freezes)\b", lower):
        return "GOAL", "find", _infer_object_type(text), text.strip(" ."), args, "project check requiring discovery", 0.88
    if not prior_goal and re.search(r"\bcheck\b.*\b(?:@|class|file|module|widget|slider|qslider|custom_widgets|custom_qt)\b", lower):
        return "GOAL", "find", _infer_object_type(text), text.strip(" ."), args, "project check requiring discovery", 0.88
    if not prior_goal and re.search(r"\b(?:tree|details|project details|project tree|tab change|startup|ui)\b", lower) and re.search(r"\b(?:slow|stale|refresh|freeze|freezes|hang|hangs)\b", lower):
        return "GOAL", "inspect", _infer_object_type(text), text.strip(" ."), args, "reported project/UI behavior requiring investigation", 0.84
    if not prior_goal and re.search(r"\b(what would|how would|show me how|example|pretend)\b", lower):
        return "GOAL", "explain", _infer_object_type(text), text.strip(" ."), args, "guidance/example request", 0.86

    if re.search(r"\b(?:include|return|output|summari[sz]e|tell me|show)\b.*\b(?:line numbers?|names? only|path|file|side effects?|signature|public methods?)\b", lower):
        return "OUTPUT_REQUEST", "report", "answer", "", args, "requested output format/detail", 0.9

    if prior_goal and re.match(r"^\s*(?:summari[sz]e|report|list|explain|describe|tell me|show|propose|suggest|include)\b", lower):
        return "OUTPUT_REQUEST", "report", "answer", "", args, "requested follow-up output/detail", 0.9
    if not prior_goal and re.match(r"^\s*include\b", lower):
        return "GOAL", "include", _infer_object_type(text), re.sub(r"^\s*include\s+", "", text, flags=re.IGNORECASE).strip(" ."), args, "leading include command", 0.82

    leading_action = bool(re.match(
        r"^\s*(?:create|make|build|add|generate|find|locate|search|identify|inspect|review|read|open|refresh|export|run|plan|connect|wire|change|update|move|parent|select)\b",
        lower,
    ))
    if not leading_action and re.search(r"\b(?:do not|don't|dont|never|without|only|keep|leave|avoid|preserve|wait for approval|before editing|before changing)\b", lower):
        role = "CONSTRAINT"
        if re.search(r"\b(verify|validate|check|confirm|make sure)\b", lower):
            role = "VALIDATION"
        return role, "constrain", "", "", args, "constraint or final-state language", 0.9

    if re.search(r"\b(verify|validate|confirm|make sure|ensure)\b", lower) or re.search(r"\bcheck\b(?!\s+(?:if|whether|where|which|what|for))", lower):
        return "VALIDATION", "validate", _infer_object_type(text), "", args, "validation phrase", 0.92

    if re.search(r"\b(tell me|return|output|show me what file|what file|which file|file it is in|include)\b", lower):
        return "OUTPUT_REQUEST", "report", "answer", "", args, "requested output format/detail", 0.88

    if connector == "or" or re.search(r"\bwhichever\b|\bi don't care which\b", lower):
        alternatives = [part.strip(" .") for part in re.split(r"\bor\b", text, flags=re.IGNORECASE) if part.strip()]
        if alternatives:
            args["alternatives"] = alternatives
        return "ALTERNATIVE", "choose", _infer_object_type(text), "", args, "alternative implementation/target set", 0.84

    if re.match(r"^\s*(?:named|called|call it|name it|call them|name them|name|rename)\b", lower):
        return "ARGUMENT", "name", "", "", args, "naming argument attached to prior goal", 0.94

    if re.match(r"^\s*(?:the\s+)?[A-Za-z_][A-Za-z0-9_:-]*\s+(?:is|are)\s+", text):
        args.setdefault("context_hint", text)
        return "CONTEXT", "context", "", "", args, "state/context evidence", 0.82

    if connector in {"and", "+", "plus", "implicit"} and prior_goal and _looks_like_additional_object(text):
        prior_action = str(prior_goal.get("action") or "create")
        object_type = _infer_object_type(text)
        return "GOAL", prior_action, object_type, text.strip(" ."), args, "additional object using prior action", 0.84

    action, object_type, target = _composed_action_object(text, prior_goal=prior_goal)
    if action:
        if _is_argument_like_action(action, lower, prior_goal):
            args.update(_position_arguments(text))
            return "ARGUMENT", action, object_type, target, args, "action supplies argument/postcondition for prior creation goal", 0.86
        if _uses_prior_output(text) or action in {
            "parent", "attach", "constrain", "assign", "move", "select",
            "orient", "skin", "freeze", "modify", "connect",
        } and prior_goal:
            return "DEPENDENT_GOAL", action, object_type, target, args, "depends on prior produced object or explicit follow-up action", 0.88
        return "GOAL", action, object_type, target, args, "independent objective", 0.9

    if connector in {"with", "using"} or (prior_goal and re.match(r"^\s*with\b", lower)):
        args.setdefault("modifier", text)
        return "MODIFIER", "modify", "", "", args, "with/using modifier", 0.78

    args.setdefault("context_hint", text)
    return "CONTEXT", "context", "", "", args, "unverbed phrase treated as context", 0.62


def _composed_action_object(text: str, *, prior_goal: dict[str, Any]) -> tuple[str, str, str]:
    lower = text.lower()
    action_map = (
        ("create", r"\b(create|make|build|add|generate)\b\s+(.+)"),
        ("find", r"\b(find|locate|search for|search|identify|inspect|review|read)\b\s+(.+)"),
        ("list", r"\b(list|show|get|summari[sz]e)\b\s+(.+)"),
        ("open", r"\b(open)\b\s+(.+)"),
        ("refresh", r"\b(refresh)\b\s+(.+)"),
        ("export", r"\b(export)\b\s+(.+)"),
        ("run", r"\b(run)\b\s+(.+)"),
        ("plan", r"\b(plan|propose|suggest)\b\s+(.+)"),
        ("include", r"\b(include)\b\s+(.+)"),
        ("modify", r"\b(change|update|modify|edit|patch)\b\s+(.+)"),
        ("connect", r"\b(connect|wire)\b\s+(.+)"),
        ("attach", r"\b(attach)\b\s+(.+)"),
        ("parent", r"\b(parent)\b\s+(.+)"),
        ("delete", r"\b(delete|remove|stop)\b\s+(.+)"),
        ("constrain", r"\b(constrain)\b\s+(.+)"),
        ("assign", r"\b(assign)\b\s+(.+)"),
        ("move", r"\b(move|place|position|aim|orient)\b\s+(.+)"),
        ("skin", r"\b(skin)\b\s+(.+)"),
        ("freeze", r"\b(freeze)\b\s+(.+)"),
        ("select", r"\b(select|keep selected|leave selected)\b\s*(.*)"),
        ("expose", r"\b(expose)\b\s+(.+)"),
        ("drive", r"\b(drive|drives)\b\s+(.+)"),
        ("explain", r"\b(explain|describe|what does|how does)\b\s*(.*)"),
    )
    for action, pattern in action_map:
        match = re.search(pattern, lower)
        if not match:
            continue
        object_text = match.group(2).strip(" .") if match.lastindex and match.lastindex >= 2 else ""
        return action, _infer_object_type(object_text or text), object_text or text.strip(" .")
    return "", "", ""


def _extract_clause_arguments(text: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    plural_name_match = re.search(
        r"\b(?:call them|name them|rename them)\s+([A-Za-z_][A-Za-z0-9_:.-]*(?:\s*(?:,|and|&)\s*[A-Za-z_][A-Za-z0-9_:.-]*)+)",
        text,
        re.IGNORECASE,
    )
    if plural_name_match:
        names = [
            item.strip(" .?!,;:")
            for item in re.split(r"\s*(?:,|and|&)\s*", plural_name_match.group(1))
            if item.strip(" .?!,;:")
        ]
        if names:
            args["names"] = names
    name_match = re.search(r"\b(?:named|called|call it|name it|call them|name them|name)\s+([A-Za-z_][A-Za-z0-9_:.-]*)", text, re.IGNORECASE)
    if name_match:
        args["name"] = name_match.group(1).rstrip(".?!,;:")
    color_match = re.search(r"\b(red|blue|green|yellow|white|black|purple|orange|gray|grey)\b", text, re.IGNORECASE)
    if color_match:
        args["color"] = color_match.group(1).lower()
    args.update(_position_arguments(text))
    return args


def _position_arguments(text: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    pos_match = re.search(r"\b(?:at|to|on|under|above|below)\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_ -]*(?:joint|bone|wrist|hand|control|ctrl)?)\b", text, re.IGNORECASE)
    if pos_match:
        args["position_source"] = pos_match.group(1).strip()
    amount_match = re.search(r"\b(up|down|left|right|forward|back)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:units?)?\b", text, re.IGNORECASE)
    if amount_match:
        args["translation"] = {"direction": amount_match.group(1).lower(), "amount": float(amount_match.group(2))}
    target_match = re.search(r"\b(?:to|under|onto)\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_:.-]*)\b", text, re.IGNORECASE)
    if target_match:
        args.setdefault("target", target_match.group(1))
    return args


def _infer_object_type(text: str) -> str:
    lower = text.lower()
    for key, value in (
        ("niagara", "niagara_emitter"),
        ("emitter", "emitter"),
        ("locator", "locator"),
        ("control", "control"),
        ("ctrl", "control"),
        ("material", "material"),
        ("cube", "cube"),
        ("function", "function"),
        ("file", "file"),
        ("project details", "project_details"),
        ("selection", "selection"),
        ("skeleton", "skeleton"),
        ("notify", "animation_notify"),
        ("parameter", "parameter"),
    ):
        if key in lower:
            return value
    return ""


def _is_argument_like_action(action: str, lower: str, prior_goal: dict[str, Any]) -> bool:
    if not prior_goal:
        return False
    if action == "move" and re.search(r"\b(place|position)\s+(?:it|this|that)\s+at\b", lower):
        return True
    return False


def _uses_prior_output(text: str) -> bool:
    return bool(re.search(r"\b(it|this|that|them|those|these|the result|the created|both)\b", text, re.IGNORECASE))


def _dependent_goal_dependencies(text: str, goals: list[dict[str, Any]], last_goal_id: str) -> list[str]:
    if re.search(r"\bboth\b|\bthem\b|\bthose\b|\bthese\b", text, re.IGNORECASE) and len(goals) >= 2:
        return [
            str(goal.get("goal_id") or "")
            for goal in goals
            if str(goal.get("goal_id") or "")
        ]
    return [last_goal_id] if last_goal_id else []


def _argument_attachment_goal(goals: list[dict[str, Any]], args: dict[str, Any], text: str) -> str:
    if "name" in args and re.search(r"\bthem\b|\bthose\b|\bthese\b", text, re.IGNORECASE):
        for goal in goals:
            if not dict(goal.get("arguments") or {}).get("name"):
                return str(goal.get("goal_id") or "")
    if "name" in args:
        previous_name_count = sum(1 for goal in goals if dict(goal.get("arguments") or {}).get("name"))
        if previous_name_count and previous_name_count < len(goals):
            for goal in goals:
                if not dict(goal.get("arguments") or {}).get("name"):
                    return str(goal.get("goal_id") or "")
    return ""


def _looks_like_additional_object(text: str) -> bool:
    return bool(re.match(r"^\s*(?:a|an|the)?\s*(locator|control|ctrl|material|cube|emitter|notify|parameter)\b", text, re.IGNORECASE))


def _clause_references(text: str, last_goal_id: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for token in re.findall(r"\b(it|this|that|them|those|these|the result|the created asset|the created object|both)\b", text, re.IGNORECASE):
        refs[token.lower()] = f"${last_goal_id}.output" if last_goal_id else "unresolved"
    return refs


def _append_goal_list(goals: list[dict[str, Any]], goal_id: str, key: str, value: str) -> None:
    goal = _goal_by_id(goals, goal_id)
    if goal is None or not value:
        return
    values = goal.setdefault(key, [])
    if value not in values:
        values.append(value)


def _merge_goal_arguments(goals: list[dict[str, Any]], goal_id: str, args: dict[str, Any]) -> None:
    goal = _goal_by_id(goals, goal_id)
    if goal is None:
        return
    target = goal.setdefault("arguments", {})
    for key, value in args.items():
        if value in (None, "", [], {}):
            continue
        if key not in target:
            target[key] = value


def _merge_plural_name_arguments(goals: list[dict[str, Any]], names: list[str]) -> None:
    clean_names = [str(name).strip(" .?!,;:") for name in names if str(name).strip(" .?!,;:")]
    if not clean_names:
        return
    unnamed_goals = [
        goal
        for goal in goals
        if not dict(goal.get("arguments") or {}).get("name")
    ]
    for goal, name in zip(unnamed_goals, clean_names):
        goal.setdefault("arguments", {})["name"] = name


def _goal_by_id(goals: list[dict[str, Any]], goal_id: str) -> dict[str, Any] | None:
    for goal in goals:
        if str(goal.get("goal_id") or "") == str(goal_id or ""):
            return goal
    return None


def _primary_objective(goals: tuple[GoalClause, ...], fallback: str) -> str:
    if not goals:
        return fallback
    first = goals[0]
    return " ".join(part for part in (first.action, first.object_type or first.target) if part).strip() or fallback


def split_prompt_clauses(text: str) -> PromptClausePlan:
    """Split a prompt into deterministic workflow clauses."""
    original = str(text or "")
    normalized = normalize_prompt_text(original)
    if not normalized:
        return PromptClausePlan(original, "", (), 1.0, False, False, False)

    segments = _segments_with_spans(normalized)
    clauses: list[PromptClause] = []
    last_action_id = ""
    last_nonapproval_id = ""
    branch_anchor_id = ""
    active_branch_group = ""

    for index, (segment, start, end) in enumerate(segments, start=1):
        cleaned = _LIST_PREFIX.sub("", segment).strip(" \t,;")
        if not cleaned:
            continue

        condition_kind = ""
        conditional_on = ""
        branch_group = ""
        condition_match = _CONDITION_PREFIX.match(cleaned)
        if condition_match:
            condition_kind = condition_match.group(1).lower()
            remainder = condition_match.group(2).strip()
            if remainder:
                cleaned = remainder
            if condition_kind in {"if", "unless", "when", "once"}:
                branch_anchor_id = last_nonapproval_id or last_action_id
                active_branch_group = f"branch_{index}"
                conditional_on = branch_anchor_id
                branch_group = active_branch_group
            else:
                conditional_on = branch_anchor_id or last_nonapproval_id
                branch_group = active_branch_group or f"branch_{index}"

        action, action_confidence = _classify_action(cleaned)
        clause_id = f"clause_{len(clauses) + 1}"
        requires_confirmation = action == "approval" or bool(
            re.search(
                r"\b(ask first|wait for approval|until i approve|before editing|before changing|do not edit until|don't edit until)\b",
                cleaned,
                re.IGNORECASE,
            )
        )

        read_only = action not in {"modify_code", "execute"}
        if action == "generate":
            read_only = bool(
                re.search(
                    r"\b(example|show me how|how would|how do i|how can i|"
                    r"do not edit|don't edit|dont edit|plan only|design only|"
                    r"without changing|without editing)\b",
                    cleaned,
                    re.IGNORECASE,
                )
            )

        dependencies: list[str] = []
        if last_action_id:
            dependencies.append(last_action_id)
        if conditional_on and conditional_on not in dependencies:
            dependencies.append(conditional_on)

        if action == "approval":
            # Approval gates depend on the plan immediately before them.
            dependencies = [last_nonapproval_id] if last_nonapproval_id else dependencies

        constraints = _extract_constraints(cleaned)
        object_text = _object_text(cleaned, action)

        clause = PromptClause(
            clause_id=clause_id,
            text=segment.strip(),
            normalized_text=cleaned,
            action=action,
            object_text=object_text,
            sequence_index=len(clauses) + 1,
            depends_on=tuple(dep for dep in dependencies if dep),
            condition_kind=condition_kind,
            conditional_on=conditional_on,
            branch_group=branch_group,
            constraints=tuple(constraints),
            requires_confirmation=requires_confirmation,
            read_only=read_only,
            confidence=action_confidence,
            source_span=(start, end),
            metadata={
                "starts_with_reference": bool(_PRONOUN_START.match(cleaned)),
                "explicit_sequence": index > 1,
            },
        )
        clauses.append(clause)
        last_action_id = clause_id
        if action != "approval":
            last_nonapproval_id = clause_id

    clauses = _repair_dependencies(clauses)
    confidence = (
        sum(clause.confidence for clause in clauses) / len(clauses)
        if clauses
        else 1.0
    )
    actions = {clause.action for clause in clauses if clause.action != "constraint"}
    return PromptClausePlan(
        original_text=original,
        normalized_text=normalized,
        clauses=tuple(clauses),
        confidence=round(confidence, 3),
        has_conditions=any(clause.condition_kind for clause in clauses),
        has_approval_gate=any(clause.requires_confirmation for clause in clauses),
        has_multiple_actions=len(actions) > 1 or len(clauses) > 1,
    )


def clause_plan_for_model(plan: PromptClausePlan | dict[str, Any]) -> str:
    """Render a compact packet for the lightweight semantic model."""
    data = plan.to_dict() if isinstance(plan, PromptClausePlan) else dict(plan or {})
    lines = ["DETERMINISTIC CLAUSE PLAN"]
    for clause in data.get("clauses") or []:
        lines.append(
            f"- {clause.get('clause_id')}: action={clause.get('action')}; "
            f"depends_on={clause.get('depends_on') or []}; "
            f"condition={clause.get('condition_kind') or '-'}; "
            f"text={clause.get('normalized_text') or clause.get('text') or ''}"
        )
    return "\n".join(lines)


def _segments_with_spans(text: str) -> list[tuple[str, int, int]]:
    # Preserve numbered/bulleted lines as independent units before connector splitting.
    line_units: list[tuple[str, int, int]] = []
    cursor = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.strip()
        start = cursor
        end = cursor + len(raw_line)
        cursor = end
        if line:
            line_units.append((line, start, end))

    if len(line_units) <= 1:
        line_units = [(text, 0, len(text))]

    output: list[tuple[str, int, int]] = []
    for line, base_start, _base_end in line_units:
        local_cursor = 0
        for match in _CONNECTOR_SPLIT.finditer(line):
            piece = line[local_cursor:match.start()].strip()
            if piece:
                piece_start = base_start + local_cursor
                output.append((piece, piece_start, piece_start + len(piece)))
            local_cursor = match.end()
        piece = line[local_cursor:].strip()
        if piece:
            piece_start = base_start + local_cursor
            output.append((piece, piece_start, piece_start + len(piece)))

    return _merge_fragments(output)


def _merge_fragments(
    segments: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Avoid turning small subordinate fragments into fake goals."""
    merged: list[tuple[str, int, int]] = []
    for segment, start, end in segments:
        action, confidence = _classify_action(segment)
        subordinate = bool(
            re.match(
                r"^\s*(that|which|who|where|with|using|based on|for|so that|to)\b",
                segment,
                re.IGNORECASE,
            )
        )
        if merged and (subordinate or (action == "respond" and confidence < 0.6)):
            previous, previous_start, _ = merged[-1]
            merged[-1] = (f"{previous} {segment}".strip(), previous_start, end)
        else:
            merged.append((segment, start, end))
    return merged


def _classify_action(text: str) -> tuple[str, float]:
    lower = text.lower()
    if re.search(
        r"\b(?:do not|don't|dont|never|without)\s+"
        r"(?:edit|change|modify|write|save|apply|create|add|insert|execute|run)\b",
        lower,
    ):
        return "constraint", 0.96
    # Question-form clauses describe facts to retrieve even when the subject's
    # behavior contains a verb such as "create" or "build".
    if re.search(
        r"^\s*(?:in\s+(?:maya|unreal|blender|houdini|unity)\s*,?\s*)?"
        r"(?:what|which|where|who|list|show|get)\b",
        lower,
    ):
        return "search", 0.94
    for action, pattern in _ACTION_PATTERNS:
        if re.search(pattern, lower):
            return action, 0.94 if action in {"approval", "validate", "report"} else 0.86
    if _CONSTRAINT_PATTERN.search(lower):
        return "constraint", 0.72
    return "respond", 0.5


def _object_text(text: str, action: str) -> str:
    patterns = {
        "search": r"\b(?:find|locate|search(?: for)?|look for|identify|inspect|review|analy[sz]e|determine)\b\s+(.+)",
        "generate": r"\b(?:generate|write|create|build|make|add|design|draft|produce)\b\s+(.+)",
        "modify_code": r"\b(?:fix|patch|modify|edit|update|refactor|rename|remove|delete|wire|connect|implement)\b\s+(.+)",
        "execute": r"\b(?:run|execute|launch|apply|perform|open|move|select|import|export)\b\s+(.+)",
        "validate": r"\b(?:validate|verify|compile|test|check)\b\s*(.*)",
        "report": r"\b(?:report|summari[sz]e|explain|show|tell|document)\b\s*(.*)",
        "plan": r"\b(?:plan|propose|outline|architect|map out|design)\b\s*(.*)",
        "explain": r"\b(?:explain|teach|show me how|how would|how do|how can|compare|describe)\b\s*(.*)",
    }
    pattern = patterns.get(action)
    if not pattern:
        return text.strip()
    match = re.search(pattern, text, re.IGNORECASE)
    return (match.group(1).strip() if match else text.strip())[:500]


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for match in re.finditer(
        r"\b(?:do not|don't|dont|never|only|must|without|preserve|reuse|before|after|until)\b[^.;]*",
        text,
        re.IGNORECASE,
    ):
        value = re.sub(r"\s+", " ", match.group(0)).strip()
        if value and value not in constraints:
            constraints.append(value)
    return constraints[:6]


def _repair_dependencies(
    clauses: list[PromptClause],
) -> list[PromptClause]:
    """Make independent repeated searches parallel while preserving synthesis."""
    if len(clauses) < 2:
        return clauses

    repaired: list[PromptClause] = []
    search_ids: list[str] = []
    for clause in clauses:
        dependencies = list(clause.depends_on)
        if clause.action == "search":
            # Consecutive independent searches should not serialize each other.
            if repaired and repaired[-1].action == "search" and not clause.condition_kind:
                dependencies = [
                    dep
                    for dep in dependencies
                    if dep != repaired[-1].clause_id
                ]
            search_ids.append(clause.clause_id)
        elif clause.action in {"report", "explain"} and len(search_ids) > 1:
            dependencies = list(dict.fromkeys([*search_ids, *dependencies]))

        repaired.append(
            PromptClause(
                clause_id=clause.clause_id,
                text=clause.text,
                normalized_text=clause.normalized_text,
                action=clause.action,
                object_text=clause.object_text,
                sequence_index=clause.sequence_index,
                depends_on=tuple(dependencies),
                condition_kind=clause.condition_kind,
                conditional_on=clause.conditional_on,
                branch_group=clause.branch_group,
                constraints=clause.constraints,
                requires_confirmation=clause.requires_confirmation,
                read_only=clause.read_only,
                confidence=clause.confidence,
                source_span=clause.source_span,
                metadata=clause.metadata,
            )
        )
    return repaired
