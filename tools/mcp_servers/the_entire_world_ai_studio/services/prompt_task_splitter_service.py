"""Deterministic long-prompt staging helpers.

Large user prompts often contain a full project contract: investigate, plan,
edit, validate, and report. Feeding the entire contract into every model/tool
stage is slow and makes the UI feel stuck. This module keeps the original
contract intact for audit/history, but produces a compact first-stage prompt
for the model.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


LONG_PROMPT_STAGE_THRESHOLD = 2600


@dataclass(frozen=True)
class PromptStage:
    key: str
    title: str
    instructions: list[str]


@dataclass(frozen=True)
class PromptChunk:
    key: str
    title: str
    items: list[str]


@dataclass(frozen=True)
class StagedPromptContract:
    original_chars: int
    source_hash: str
    user_goal: str
    chunks: list[PromptChunk]
    active_stage: PromptStage
    global_constraints: list[str]
    deferred_stages: list[PromptStage]

    def render_for_llm(self) -> str:
        lines = [
            "LONG PROMPT STAGED EXECUTION",
            f"Hash: {self.source_hash}",
            f"Original chars: {self.original_chars}",
            "Synthesis rule: connect chunks into one coherent task model; preserve ordering, safety, validation, and active-stage scope.",
            "Do not treat chunks as separate unrelated requests.",
            f"Goal: {_clip_instruction(self.user_goal or 'Understand and satisfy the user request.', limit=220)}",
            "",
            "Compact source chunks:",
        ]
        for chunk in self.chunks:
            lines.append(f"{chunk.title}:")
            lines.extend(f"- {_clip_instruction(item, limit=125)}" for item in chunk.items[:1])
            if len(chunk.items) > 1:
                lines.append(f"- ...{len(chunk.items) - 1} more requirement(s)")
        lines.extend([
            "",
            f"Active stage: {self.active_stage.title}",
        ])
        lines.extend(f"- {_clip_instruction(item, limit=145)}" for item in self.active_stage.instructions[:6])
        if self.global_constraints:
            lines.extend(["", "Global constraints:"])
            lines.extend(f"- {_clip_instruction(item, limit=130)}" for item in self.global_constraints[:4])
        if self.deferred_stages:
            lines.extend(["", "Deferred stages; do not execute yet:"])
            for stage in self.deferred_stages:
                lines.append(f"- {stage.title}: {len(stage.instructions)} instruction(s)")
        lines.extend(
            [
                "",
                "Quality bar:",
                "- Prefer project evidence over assumptions.",
                "- Do not implement or mutate assets/files yet.",
                "- If context is missing, ask only for the minimum missing information.",
                "- If later stages are required, state the next stage instead of dropping it.",
            ]
        )
        return "\n".join(lines)


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


def build_request_task_graph(prompt: str, *, host: str = "") -> dict[str, Any]:
    """Build the canonical achievable-goal graph used by routing and execution.

    PromptIntentService owns semantic interpretation and goal decomposition.
    This service validates the graph, derives execution metadata, and preserves
    backward-compatible ``tasks`` output for existing consumers.
    """
    from services.prompt_intent_service import understand_prompt_request
    try:
        from services.prompt_clause_service import split_prompt_clauses
        clause_plan = split_prompt_clauses(prompt).to_dict()
    except Exception:
        clause_plan = {}

    understanding = understand_prompt_request(prompt, host=host)
    goals = [task.to_dict() for task in understanding.tasks]

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
        "framework": "canonical_request_goal_graph_v3",
        "compatibility_framework": "canonical_request_task_graph_v1",
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
        "semantic_execution_contract": dict(
            understanding.semantic_execution_contract or {}
        ),
        "semantic_plan_steps": list(
            (understanding.semantic_execution_contract or {}).get(
                "plan_steps"
            )
            or []
        ),
        "planning_rationale": str(
            (understanding.semantic_execution_contract or {}).get(
                "planning_rationale"
            )
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

    if goal_type in {"learn", "explain", "compare", "respond"}:
        return "chat"

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
