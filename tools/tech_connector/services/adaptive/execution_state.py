from __future__ import annotations

"""Shared, serializable execution state for adaptive request orchestration.

Milestone A keeps this state in shadow mode: it can observe and score the current
request path without changing existing routing, prompt assembly, or execution.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4


CONFIDENCE_DIMENSIONS = ("intent", "target", "knowledge", "execution", "validation")


@dataclass
class EvidenceRecord:
    kind: str
    source: str
    summary: str
    confidence_delta: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        return cls(**dict(data or {}))


@dataclass
class ConfidenceProfile:
    intent: float = 0.5
    target: float = 0.0
    knowledge: float = 0.0
    execution: float = 0.0
    validation: float = 0.0
    history: list[dict[str, Any]] = field(default_factory=list)

    def clamp(self) -> None:
        for name in CONFIDENCE_DIMENSIONS:
            setattr(self, name, max(0.0, min(1.0, float(getattr(self, name, 0.0)))))

    def update(self, dimension: str, delta: float, *, reason: str = "", source: str = "") -> float:
        if dimension not in CONFIDENCE_DIMENSIONS:
            raise ValueError(f"Unknown confidence dimension: {dimension}")
        before = float(getattr(self, dimension))
        after = max(0.0, min(1.0, before + float(delta)))
        setattr(self, dimension, after)
        self.history.append(
            {
                "dimension": dimension,
                "before": round(before, 4),
                "after": round(after, 4),
                "delta": round(float(delta), 4),
                "reason": reason,
                "source": source,
            }
        )
        return after

    def overall(self, weights: dict[str, float] | None = None) -> float:
        weights = weights or {
            "intent": 0.2,
            "target": 0.25,
            "knowledge": 0.2,
            "execution": 0.2,
            "validation": 0.15,
        }
        total_weight = sum(max(0.0, float(weights.get(name, 0.0))) for name in CONFIDENCE_DIMENSIONS)
        if total_weight <= 0:
            return 0.0
        score = sum(float(getattr(self, name)) * max(0.0, float(weights.get(name, 0.0))) for name in CONFIDENCE_DIMENSIONS)
        return round(score / total_weight, 4)

    def to_dict(self) -> dict[str, Any]:
        self.clamp()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfidenceProfile":
        obj = cls(**dict(data or {}))
        obj.clamp()
        return obj


@dataclass
class ExecutionBudget:
    token_budget: int = 4096
    reserved_output_tokens: int = 512
    retrieval_items: int = 4
    expert_limit: int = 2
    reasoning_level: str = "minimal"
    validation_level: str = "static"
    runtime_budget_ms: int = 120_000
    max_model_calls: int = 1
    allow_external_research: bool = False
    allow_live_dcc_context: bool = False
    include_goal_gap: bool = False
    include_domain_experts: bool = False
    include_work_memory: bool = False
    include_studio_profile: bool = True
    include_validation_plan: bool = True

    def normalize(self) -> None:
        self.token_budget = max(512, int(self.token_budget))
        self.reserved_output_tokens = max(32, min(int(self.reserved_output_tokens), self.token_budget - 1))
        self.retrieval_items = max(0, int(self.retrieval_items))
        self.expert_limit = max(0, int(self.expert_limit))
        self.runtime_budget_ms = max(1_000, int(self.runtime_budget_ms))
        self.max_model_calls = max(0, int(self.max_model_calls))

    def to_dict(self) -> dict[str, Any]:
        self.normalize()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionBudget":
        obj = cls(**dict(data or {}))
        obj.normalize()
        return obj


@dataclass
class PredictionRecord:
    complexity_score: float = 0.0
    novelty_score: float = 0.0
    risk_score: float = 0.0
    predicted_runtime_ms: int = 0
    predicted_context_tokens: int = 0
    predicted_output_tokens: int = 0
    predicted_files_touched: int = 0
    predicted_validation_types: list[str] = field(default_factory=list)
    predicted_failure_modes: list[str] = field(default_factory=list)
    predicted_success_probability: float = 0.5
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictionRecord":
        return cls(**dict(data or {}))


@dataclass
class StageDecision:
    stage_key: str
    should_run: bool
    priority: float = 0.0
    required: bool = False
    estimated_latency_ms: int = 0
    estimated_token_cost: int = 0
    expected_confidence_gain: float = 0.0
    required_evidence: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def value_score(self) -> float:
        if self.required:
            return 1_000_000.0 + self.priority
        cost = max(1.0, self.estimated_latency_ms / 100.0 + self.estimated_token_cost / 100.0)
        return (max(0.0, self.expected_confidence_gain) * 100.0 + self.priority) / cost

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["value_score"] = round(self.value_score, 6)
        return data


@dataclass
class ObservedOutcome:
    status: str = "unknown"
    actual_runtime_ms: int = 0
    actual_context_tokens: int = 0
    actual_files_touched: int = 0
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    observed_failures: list[str] = field(default_factory=list)
    repair_attempts: int = 0
    user_corrected: bool = False
    user_accepted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObservedOutcome":
        return cls(**dict(data or {}))


@dataclass
class AdaptiveExecutionState:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    original_prompt: str = ""
    normalized_goal: str = ""
    route: str = ""
    provider: str = ""
    host: str = ""
    intent_category: str = ""
    mutation_scope: str = ""
    risk_level: str = ""
    requires_confirmation: bool = False
    active_file: str = ""
    project_roots: list[str] = field(default_factory=list)
    operation_memory: dict[str, Any] = field(default_factory=dict)
    confidence: ConfidenceProfile = field(default_factory=ConfidenceProfile)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    prediction: PredictionRecord = field(default_factory=PredictionRecord)
    execution_contract: dict[str, Any] = field(default_factory=dict)
    intent_frame: dict[str, Any] = field(default_factory=dict)
    outcome: ObservedOutcome | None = None
    evidence: list[EvidenceRecord] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    skipped_stages: list[dict[str, str]] = field(default_factory=list)
    stage_decisions: list[StageDecision] = field(default_factory=list)
    current_stage: str = ""
    missing_information: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    goal_graph: list[dict[str, Any]] = field(default_factory=list)
    current_goal_id: str = ""
    completed_goal_ids: list[str] = field(default_factory=list)
    failed_goal_ids: list[str] = field(default_factory=list)
    goal_outputs: dict[str, Any] = field(default_factory=dict)
    goal_attempts: dict[str, int] = field(default_factory=dict)
    answer_validation_history: list[dict[str, Any]] = field(default_factory=list)
    pending_evidence_escalation: dict[str, Any] = field(default_factory=dict)
    max_goal_attempts: int = 2
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_route_decision(
        cls,
        prompt: str,
        decision: dict[str, Any] | Any | None,
        *,
        active_file: str = "",
        project_roots: Iterable[str] = (),
        operation_memory: dict[str, Any] | None = None,
    ) -> "AdaptiveExecutionState":
        if decision is None:
            data: dict[str, Any] = {}
        elif hasattr(decision, "to_dict"):
            data = dict(decision.to_dict())
        elif isinstance(decision, dict):
            data = dict(decision)
        else:
            data = {key: getattr(decision, key) for key in dir(decision) if not key.startswith("_") and not callable(getattr(decision, key, None))}
        route_confidence = float(data.get("confidence") or 0.5)
        target_confidence = route_confidence if data.get("target_identifier") or active_file else min(0.45, route_confidence)
        from tech_connector.services.execution_contract_service import build_execution_contract
        from tech_connector.services.prompt.prompt_intent_service import parse_intent_frame
        execution_contract = build_execution_contract(
            prompt,
            active_file=active_file or str(data.get("target_identifier") or ""),
            selected_symbol=str(data.get("target_symbol") or ""),
            route_decision=data,
        )
        intent_frame = parse_intent_frame(prompt)
        return cls(
            original_prompt=prompt or "",
            normalized_goal=_normalize_goal(prompt),
            route=str(data.get("route") or ""),
            provider=str(data.get("provider") or ""),
            host=str(data.get("host") or ""),
            intent_category=str(data.get("intent_category") or ""),
            mutation_scope=str(data.get("mutation_scope") or ""),
            risk_level=str(data.get("risk_level") or ""),
            requires_confirmation=bool(data.get("requires_confirmation")),
            active_file=active_file or str(data.get("target_identifier") or ""),
            project_roots=[str(item) for item in project_roots if item],
            operation_memory=dict(operation_memory or {}),
            confidence=ConfidenceProfile(intent=max(route_confidence, intent_frame.confidence), target=target_confidence),
            execution_contract=execution_contract.to_dict(),
            intent_frame=intent_frame.to_dict(),
            missing_information=[str(item) for item in data.get("missing_info") or []],
            artifacts={"route_decision": data},
            goal_graph=_extract_goal_graph(data),
        )

    def set_goal_graph(self, graph: Any) -> None:
        self.goal_graph = _normalize_goal_graph(graph)
        self.artifacts["goal_graph"] = list(self.goal_graph)
        if self.current_goal_id and not any(self.goal_id(item, index) == self.current_goal_id for index, item in enumerate(self.goal_graph, start=1)):
            self.current_goal_id = ""

    @staticmethod
    def goal_id(goal: dict[str, Any], index: int = 1) -> str:
        return str(goal.get("goal_id") or goal.get("id") or goal.get("step_id") or f"goal_{index}")

    def completed_goal_set(self) -> set[str]:
        return {str(item) for item in self.completed_goal_ids if item}

    def next_executable_goal(self) -> dict[str, Any] | None:
        completed = self.completed_goal_set()
        for index, raw_goal in enumerate(self.goal_graph, start=1):
            goal = dict(raw_goal or {})
            goal_id = self.goal_id(goal, index)
            if goal_id in completed:
                continue
            dependencies = [str(item) for item in goal.get("depends_on") or goal.get("dependencies") or [] if item]
            if all(item in completed for item in dependencies):
                goal.setdefault("goal_id", goal_id)
                self.current_goal_id = goal_id
                self.artifacts["current_goal"] = dict(goal)
                return goal
        self.current_goal_id = ""
        self.artifacts.pop("current_goal", None)
        return None

    def current_goal(self) -> dict[str, Any] | None:
        if self.current_goal_id:
            for index, raw_goal in enumerate(self.goal_graph, start=1):
                goal = dict(raw_goal or {})
                if self.goal_id(goal, index) == self.current_goal_id:
                    goal.setdefault("goal_id", self.current_goal_id)
                    return goal
        return self.next_executable_goal()

    def dependency_outputs(self, goal: dict[str, Any] | None = None) -> dict[str, Any]:
        goal = dict(goal or self.current_goal() or {})
        dependencies = [str(item) for item in goal.get("depends_on") or goal.get("dependencies") or [] if item]
        return {key: self.goal_outputs[key] for key in dependencies if key in self.goal_outputs}

    def begin_goal_attempt(self, goal: dict[str, Any] | None = None) -> int:
        goal = dict(goal or self.current_goal() or {})
        goal_id = str(goal.get("goal_id") or self.current_goal_id or "")
        if not goal_id:
            raise ValueError("Cannot begin a goal attempt without a goal id")
        attempt = int(self.goal_attempts.get(goal_id, 0)) + 1
        self.goal_attempts[goal_id] = attempt
        self.current_goal_id = goal_id
        return attempt

    def commit_goal_result(
        self,
        result: Any,
        *,
        goal: dict[str, Any] | None = None,
        validated: bool | None = None,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal = dict(goal or self.current_goal() or {})
        goal_id = str(goal.get("goal_id") or self.current_goal_id or "")
        if not goal_id:
            raise ValueError("Cannot commit a goal result without a goal id")
        from tech_connector.services.reasoning.answer_sufficiency_service import validate_answer_sufficiency

        adequacy = validate_answer_sufficiency(self, result, goal=goal)
        externally_valid = True if validated is None else bool(validated)
        final_valid = externally_valid and adequacy.sufficient
        merged_validation = dict(validation or {})
        merged_validation["answer_sufficiency"] = adequacy.to_dict()
        record = {
            "goal_id": goal_id,
            "result": result,
            "validated": final_valid,
            "validation": merged_validation,
            "attempt": int(self.goal_attempts.get(goal_id, 0)),
        }
        self.goal_outputs[goal_id] = record
        self.answer_validation_history.append(adequacy.to_dict())
        if final_valid:
            if goal_id not in self.completed_goal_ids:
                self.completed_goal_ids.append(goal_id)
            self.failed_goal_ids = [item for item in self.failed_goal_ids if item != goal_id]
            self.pending_evidence_escalation = {}
        else:
            if goal_id not in self.failed_goal_ids:
                self.failed_goal_ids.append(goal_id)
            self.pending_evidence_escalation = {
                "goal_id": goal_id,
                "next_action": adequacy.next_action,
                "execution_tier": adequacy.escalation_tier,
                "failures": list(adequacy.failures),
                "expected_target": adequacy.expected_target,
                "expected_scope": adequacy.expected_scope,
            }
        self.current_goal_id = ""
        self.artifacts["goal_outputs"] = dict(self.goal_outputs)
        self.artifacts["completed_goal_ids"] = list(self.completed_goal_ids)
        self.artifacts["failed_goal_ids"] = list(self.failed_goal_ids)
        self.artifacts.pop("current_goal", None)
        return record

    def goal_execution_complete(self) -> bool:
        return bool(self.goal_graph) and len(self.completed_goal_set()) >= len(self.goal_graph)

    def goal_retry_available(self, goal_id: str | None = None) -> bool:
        goal_id = str(goal_id or self.current_goal_id or "")
        return bool(goal_id) and int(self.goal_attempts.get(goal_id, 0)) < max(1, int(self.max_goal_attempts))

    def add_evidence(self, record: EvidenceRecord) -> None:
        self.evidence.append(record)
        for dimension, delta in record.confidence_delta.items():
            self.confidence.update(dimension, delta, reason=record.summary, source=record.source)

    def mark_completed(self, stage_key: str) -> None:
        if stage_key and stage_key not in self.completed_stages:
            self.completed_stages.append(stage_key)
        if self.current_stage == stage_key:
            self.current_stage = ""

    def mark_skipped(self, stage_key: str, reason: str) -> None:
        if stage_key and not any(item.get("stage_key") == stage_key for item in self.skipped_stages):
            self.skipped_stages.append({"stage_key": stage_key, "reason": reason})
        if self.current_stage == stage_key:
            self.current_stage = ""

    def record_stage_decision(self, decision: StageDecision) -> None:
        self.stage_decisions.append(decision)

    def has_stage_finished(self, stage_key: str) -> bool:
        return stage_key in self.completed_stages or any(item.get("stage_key") == stage_key for item in self.skipped_stages)

    def sufficiency(self) -> dict[str, Any]:
        mutation = bool(self.mutation_scope and self.mutation_scope != "read_only")
        thresholds = {
            "intent": 0.72,
            "target": 0.78 if mutation else 0.58,
            "knowledge": 0.7 if mutation else 0.55,
            "execution": 0.7 if mutation else 0.4,
            "validation": 0.7 if mutation else 0.0,
        }
        unmet = [name for name, threshold in thresholds.items() if float(getattr(self.confidence, name)) < threshold]
        return {
            "sufficient": not unmet and not self.missing_information and not self.requires_confirmation,
            "unmet": unmet,
            "thresholds": thresholds,
            "overall_confidence": self.confidence.overall(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "original_prompt": self.original_prompt,
            "normalized_goal": self.normalized_goal,
            "route": self.route,
            "provider": self.provider,
            "host": self.host,
            "intent_category": self.intent_category,
            "mutation_scope": self.mutation_scope,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "active_file": self.active_file,
            "project_roots": list(self.project_roots),
            "operation_memory": dict(self.operation_memory),
            "confidence": self.confidence.to_dict(),
            "budget": self.budget.to_dict(),
            "prediction": self.prediction.to_dict(),
            "outcome": self.outcome.to_dict() if self.outcome else None,
            "evidence": [item.to_dict() for item in self.evidence],
            "completed_stages": list(self.completed_stages),
            "skipped_stages": list(self.skipped_stages),
            "stage_decisions": [item.to_dict() for item in self.stage_decisions],
            "current_stage": self.current_stage,
            "missing_information": list(self.missing_information),
            "warnings": list(self.warnings),
            "artifacts": dict(self.artifacts),
            "diagnostics": list(self.diagnostics),
            "goal_graph": list(self.goal_graph),
            "current_goal_id": self.current_goal_id,
            "completed_goal_ids": list(self.completed_goal_ids),
            "failed_goal_ids": list(self.failed_goal_ids),
            "goal_outputs": dict(self.goal_outputs),
            "goal_attempts": dict(self.goal_attempts),
            "answer_validation_history": list(self.answer_validation_history),
            "pending_evidence_escalation": dict(self.pending_evidence_escalation),
            "max_goal_attempts": int(self.max_goal_attempts),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdaptiveExecutionState":
        raw = dict(data or {})
        return cls(
            request_id=str(raw.get("request_id") or uuid4().hex),
            original_prompt=str(raw.get("original_prompt") or ""),
            normalized_goal=str(raw.get("normalized_goal") or ""),
            route=str(raw.get("route") or ""),
            provider=str(raw.get("provider") or ""),
            host=str(raw.get("host") or ""),
            intent_category=str(raw.get("intent_category") or ""),
            mutation_scope=str(raw.get("mutation_scope") or ""),
            risk_level=str(raw.get("risk_level") or ""),
            requires_confirmation=bool(raw.get("requires_confirmation")),
            active_file=str(raw.get("active_file") or ""),
            project_roots=[str(item) for item in raw.get("project_roots") or []],
            operation_memory=dict(raw.get("operation_memory") or {}),
            confidence=ConfidenceProfile.from_dict(raw.get("confidence") or {}),
            budget=ExecutionBudget.from_dict(raw.get("budget") or {}),
            prediction=PredictionRecord.from_dict(raw.get("prediction") or {}),
            outcome=ObservedOutcome.from_dict(raw["outcome"]) if raw.get("outcome") else None,
            evidence=[EvidenceRecord.from_dict(item) for item in raw.get("evidence") or []],
            completed_stages=[str(item) for item in raw.get("completed_stages") or []],
            skipped_stages=[dict(item) for item in raw.get("skipped_stages") or []],
            stage_decisions=[
                StageDecision(**{key: value for key, value in dict(item).items() if key != "value_score"})
                for item in raw.get("stage_decisions") or []
            ],
            current_stage=str(raw.get("current_stage") or ""),
            missing_information=[str(item) for item in raw.get("missing_information") or []],
            warnings=[str(item) for item in raw.get("warnings") or []],
            artifacts=dict(raw.get("artifacts") or {}),
            diagnostics=[dict(item) for item in raw.get("diagnostics") or []],
            goal_graph=_normalize_goal_graph(raw.get("goal_graph") or (raw.get("artifacts") or {}).get("goal_graph") or []),
            current_goal_id=str(raw.get("current_goal_id") or ""),
            completed_goal_ids=[str(item) for item in raw.get("completed_goal_ids") or []],
            failed_goal_ids=[str(item) for item in raw.get("failed_goal_ids") or []],
            goal_outputs=dict(raw.get("goal_outputs") or {}),
            goal_attempts={str(key): int(value) for key, value in dict(raw.get("goal_attempts") or {}).items()},
            answer_validation_history=[dict(item) for item in raw.get("answer_validation_history") or []],
            pending_evidence_escalation=dict(raw.get("pending_evidence_escalation") or {}),
            max_goal_attempts=max(1, int(raw.get("max_goal_attempts") or 2)),
            created_at=str(raw.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )


def _normalize_goal_graph(graph: Any) -> list[dict[str, Any]]:
    if hasattr(graph, "to_dict"):
        graph = graph.to_dict()
    if isinstance(graph, dict):
        graph = graph.get("goals") or graph.get("nodes") or graph.get("tasks") or []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(graph or [], start=1):
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        elif not isinstance(item, dict) and hasattr(item, "__dict__"):
            item = {key: value for key, value in vars(item).items() if not key.startswith("_")}
        if not isinstance(item, dict):
            continue
        goal = dict(item)
        goal.setdefault("goal_id", str(goal.get("id") or goal.get("step_id") or f"goal_{index}"))
        normalized.append(goal)
    return normalized


def _extract_goal_graph(data: dict[str, Any]) -> list[dict[str, Any]]:
    execution_context = dict(data.get("execution_context") or data.get("prompt_execution_context") or {})
    graph = (
        data.get("goal_graph")
        or data.get("task_graph")
        or execution_context.get("goal_graph")
        or execution_context.get("task_graph")
        or []
    )
    return _normalize_goal_graph(graph)


def _normalize_goal(prompt: str) -> str:
    text = " ".join((prompt or "").split()).strip()
    prefixes = ("please ", "can you ", "could you ", "i want you to ", "i need you to ")
    lower = text.lower()
    for prefix in prefixes:
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text[:500]
