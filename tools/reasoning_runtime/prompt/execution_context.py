"""Neutral prompt execution context schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from reasoning_runtime.prompt.execution_state import EvidenceState


@dataclass
class PromptExecutionContext:
    prompt: str
    normalized_prompt: str = ""
    host_hint: str = ""
    request_understanding: dict[str, Any] = field(default_factory=dict)
    problem_formulation: dict[str, Any] = field(default_factory=dict)
    context_candidates: list[dict[str, Any]] = field(default_factory=list)
    resolved_references: dict[str, Any] = field(default_factory=dict)
    planning_result: dict[str, Any] = field(default_factory=dict)
    understanding_validation: dict[str, Any] = field(default_factory=dict)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)
    evidence_state: EvidenceState = field(default_factory=EvidenceState)
    execution_decision: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)
    reasoning_pipeline: dict[str, Any] = field(default_factory=dict)
    visible_progress: dict[str, Any] = field(default_factory=dict)

    @property
    def understanding(self) -> dict[str, Any]:
        return self.request_understanding

    @property
    def semantic_contract(self) -> dict[str, Any]:
        return self.semantic_execution_contract

    @property
    def goal_graph(self) -> dict[str, Any]:
        return self.task_graph

    @property
    def primary_goal(self) -> str:
        return str(
            self.task_graph.get("primary_goal")
            or self.semantic_execution_contract.get("goal")
            or self.request_understanding.get("primary_goal")
            or self.normalized_prompt
            or self.prompt
        )

    @property
    def goal_type(self) -> str:
        return str(
            self.task_graph.get("goal_type")
            or self.semantic_execution_contract.get("goal_type")
            or self.request_understanding.get("goal_type")
            or "respond"
        )

    def current_goal(self, completed_goal_ids: Iterable[str] | None = None) -> dict[str, Any]:
        completed = {str(value) for value in (completed_goal_ids or [])}
        goals = list(
            self.task_graph.get("ordered_goals")
            or self.task_graph.get("goals")
            or self.task_graph.get("tasks")
            or []
        )
        for goal in goals:
            goal_id = str(goal.get("goal_id") or goal.get("task_id") or "")
            if not goal_id or goal_id in completed:
                continue
            dependencies = {str(value) for value in (goal.get("depends_on") or [])}
            if dependencies.issubset(completed):
                return dict(goal)
        return {}

    def attach_execution_decision(self, decision: dict[str, Any] | Any | None) -> None:
        self.execution_decision = (
            decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
        )

    def to_dict(self) -> dict[str, Any]:
        evidence = self.evidence_state.to_dict()
        return {
            "framework": "canonical_prompt_execution_context_v2",
            "prompt": self.prompt,
            "normalized_prompt": self.normalized_prompt or self.prompt,
            "host_hint": self.host_hint,
            "request_understanding": dict(self.request_understanding),
            "understanding": dict(self.request_understanding),
            "problem_formulation": dict(self.problem_formulation),
            "context_candidates": [dict(item) for item in self.context_candidates],
            "resolved_references": dict(self.resolved_references),
            "planning_result": dict(self.planning_result),
            "understanding_validation": dict(self.understanding_validation),
            "semantic_execution_contract": dict(self.semantic_execution_contract),
            "semantic_contract": dict(self.semantic_execution_contract),
            "task_graph": dict(self.task_graph),
            "goal_graph": dict(self.task_graph),
            "evidence_state": evidence,
            "execution_tier": evidence["current_tier"],
            "execution_tier_name": evidence["tier_name"],
            "execution_decision": dict(self.execution_decision),
            "runtime_state": dict(self.runtime_state),
            "primary_goal": self.primary_goal,
            "goal_type": self.goal_type,
            "estimated_steps": int(
                self.task_graph.get("estimated_steps")
                or len(self.task_graph.get("goals") or self.task_graph.get("tasks") or [])
            ),
            "reasoning_pipeline": dict(self.reasoning_pipeline),
            "visible_progress": dict(self.visible_progress),
        }
