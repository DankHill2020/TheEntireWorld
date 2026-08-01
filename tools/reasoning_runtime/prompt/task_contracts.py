"""Prompt decomposition and task graph contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _clip_instruction(text: str, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: max(0, limit - 3)].rstrip() + "..."


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
        lines.extend(["", f"Active stage: {self.active_stage.title}"])
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


@dataclass(frozen=True)
class PromptClause:
    clause_id: str
    text: str
    normalized_text: str
    action: str
    object_text: str = ""
    sequence_index: int = 0
    depends_on: tuple[str, ...] = ()
    condition_kind: str = ""
    conditional_on: str = ""
    branch_group: str = ""
    constraints: tuple[str, ...] = ()
    requires_confirmation: bool = False
    read_only: bool = True
    confidence: float = 0.5
    source_span: tuple[int, int] = (0, 0)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        data["constraints"] = list(self.constraints)
        data["source_span"] = list(self.source_span)
        return data


@dataclass(frozen=True)
class PromptClausePlan:
    original_text: str
    normalized_text: str
    clauses: tuple[PromptClause, ...]
    confidence: float
    has_conditions: bool
    has_approval_gate: bool
    has_multiple_actions: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "prompt_clause_plan_v1",
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "clauses": [clause.to_dict() for clause in self.clauses],
            "confidence": self.confidence,
            "has_conditions": self.has_conditions,
            "has_approval_gate": self.has_approval_gate,
            "has_multiple_actions": self.has_multiple_actions,
        }


@dataclass(frozen=True)
class GoalClause:
    goal_id: str
    source_clause_id: str
    action: str
    object_type: str = ""
    target: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    modifiers: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    validations: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modifiers"] = list(self.modifiers)
        data["constraints"] = list(self.constraints)
        data["validations"] = list(self.validations)
        data["depends_on"] = list(self.depends_on)
        data["consumes"] = list(self.consumes)
        data["produces"] = list(self.produces)
        return data


@dataclass(frozen=True)
class ComposedClause:
    clause_id: str
    source_text: str
    normalized_text: str
    role: str
    action: str = ""
    object_type: str = ""
    target: str = ""
    attaches_to: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    source_span: tuple[int, int] = (0, 0)
    confidence: float = 0.5
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["depends_on"] = list(self.depends_on)
        data["source_span"] = list(self.source_span)
        return data


@dataclass(frozen=True)
class ComposedRequest:
    original_text: str
    normalized_text: str
    primary_objective: str
    goals: tuple[GoalClause, ...]
    clauses: tuple[ComposedClause, ...]
    shared_context: dict[str, Any] = field(default_factory=dict)
    global_constraints: tuple[str, ...] = ()
    unresolved_relationships: tuple[str, ...] = ()
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "compositional_request_v1",
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "primary_objective": self.primary_objective,
            "goals": [goal.to_dict() for goal in self.goals],
            "clauses": [clause.to_dict() for clause in self.clauses],
            "shared_context": dict(self.shared_context),
            "global_constraints": list(self.global_constraints),
            "unresolved_relationships": list(self.unresolved_relationships),
            "confidence": self.confidence,
        }
