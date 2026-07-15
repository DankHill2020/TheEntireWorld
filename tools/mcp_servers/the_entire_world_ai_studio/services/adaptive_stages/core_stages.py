from __future__ import annotations

"""Adapters that let existing services participate in adaptive scheduling.

They preserve the current public service APIs and write their output into
``state.artifacts`` instead of changing routing or prompt assembly.
"""

from typing import Any, Callable

from services.adaptive_execution_state import AdaptiveExecutionState, EvidenceRecord, StageDecision
from services.adaptive_stage_scheduler import AdaptiveStage


class ServiceAdapterStage(AdaptiveStage):
    artifact_key: str = ""
    confidence_dimension: str = "knowledge"
    confidence_gain: float = 0.05
    estimated_latency_ms: int = 20
    estimated_token_cost: int = 0

    def __init__(self, *, service_fn: Callable[[AdaptiveExecutionState], Any] | None = None) -> None:
        self.service_fn = service_fn

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        return True, "Stage provides relevant evidence."

    def evaluate(self, state: AdaptiveExecutionState) -> StageDecision:
        should_run, reason = self.should_run(state)
        return StageDecision(
            stage_key=self.key,
            should_run=should_run,
            priority=50.0,
            estimated_latency_ms=self.estimated_latency_ms,
            estimated_token_cost=self.estimated_token_cost,
            expected_confidence_gain=self.confidence_gain if should_run else 0.0,
            reason=reason,
        )

    def execute(self, state: AdaptiveExecutionState) -> AdaptiveExecutionState:
        result = self.service_fn(state) if self.service_fn else self.run_existing_service(state)
        state.artifacts[self.artifact_key or self.key] = result
        state.add_evidence(
            EvidenceRecord(
                kind=self.key,
                source=self.__class__.__name__,
                summary=f"{self.key} produced structured evidence.",
                confidence_delta={self.confidence_dimension: self.confidence_gain},
            )
        )
        return state

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        raise NotImplementedError


class IntentStage(ServiceAdapterStage):
    key = "intent"
    artifact_key = "prompt_intent"
    confidence_dimension = "intent"
    confidence_gain = 0.18
    estimated_latency_ms = 3

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if state.confidence.intent >= 0.9 and state.intent_category:
            return False, "Existing route decision already has high intent confidence."
        return True, "Phrase-level intent can disambiguate overloaded routing terms."

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.prompt_intent_service import classify_prompt_intent

        result = classify_prompt_intent(state.original_prompt, host=state.host).to_dict()
        confidence = float(result.get("confidence") or 0.0)
        state.confidence.intent = max(state.confidence.intent, confidence)
        if result.get("host") and not state.host:
            state.host = str(result["host"])
        if result.get("kind") and not state.intent_category:
            state.intent_category = str(result["kind"])
        return result


class CodeIntelligenceStage(ServiceAdapterStage):
    key = "code_intelligence"
    artifact_key = "code_intelligence_packet"
    confidence_dimension = "target"
    confidence_gain = 0.2
    estimated_latency_ms = 120
    estimated_token_cost = 900

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if state.route not in {"code_edit", "project_edit", "project_search", "target_discovery"} and "code" not in state.intent_category:
            return False, "Request does not currently require project code intelligence."
        if state.confidence.target >= 0.88 and state.active_file:
            return False, "Target is already explicit and strongly grounded."
        return True, "Project evidence is needed to identify or confirm the edit target."

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.code_intelligence_service import build_code_intelligence_packet

        return build_code_intelligence_packet(
            state.original_prompt,
            active_path=state.active_file or None,
            limit=max(4, state.budget.retrieval_items),
            include_repo_map=state.prediction.complexity_score >= 0.45,
        )


class DomainExpertStage(ServiceAdapterStage):
    key = "domain_experts"
    artifact_key = "domain_experts"
    confidence_dimension = "knowledge"
    confidence_gain = 0.1
    estimated_latency_ms = 15
    estimated_token_cost = 450

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if not state.budget.include_domain_experts or state.budget.expert_limit <= 0:
            return False, "Execution budget excludes expert advisory context."
        if state.prediction.complexity_score < 0.25 and state.prediction.risk_score < 0.25:
            return False, "Low-complexity, low-risk request is unlikely to benefit from expert advisory."
        return True, "Domain-specific validation and architecture concerns may change the plan."

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.domain_expert_service import select_domain_experts

        decision = dict(state.artifacts.get("route_decision") or {})
        decision.update({"host": state.host, "route": state.route, "intent_category": state.intent_category, "mutation_scope": state.mutation_scope})
        return select_domain_experts(state.original_prompt, decision, limit=state.budget.expert_limit)


class GoalGapStage(ServiceAdapterStage):
    key = "goal_gap"
    artifact_key = "goal_gap_plan"
    confidence_dimension = "execution"
    confidence_gain = 0.13
    estimated_latency_ms = 35
    estimated_token_cost = 650

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if not state.budget.include_goal_gap:
            return False, "Execution budget excludes goal-gap expansion."
        if state.prediction.complexity_score < 0.4 and not state.missing_information:
            return False, "The objective appears direct enough to execute without A-to-Z gap expansion."
        return True, "Missing prerequisites or multi-step execution need an explicit capability path."

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.goal_gap_planning_service import build_goal_gap_plan, compact_goal_gap_plan

        decision = dict(state.artifacts.get("route_decision") or {})
        decision.update({"host": state.host, "route": state.route, "mutation_scope": state.mutation_scope})
        return compact_goal_gap_plan(build_goal_gap_plan(state.original_prompt, decision))


class StudioProfileStage(ServiceAdapterStage):
    key = "studio_profile"
    artifact_key = "studio_rules"
    confidence_dimension = "execution"
    confidence_gain = 0.05
    estimated_latency_ms = 4
    estimated_token_cost = 300

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if not state.budget.include_studio_profile:
            return False, "Execution budget excludes studio decision rules."
        return True, "Studio safety and reversibility policy applies to this request."

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.studio_profile_service import matching_studio_rules

        return [
            {
                "key": rule.key,
                "title": rule.title,
                "priority": rule.priority,
                "guidance": list(rule.guidance),
                "proceed_when": list(rule.proceed_when),
                "pause_when": list(rule.pause_when),
            }
            for rule in matching_studio_rules(state.original_prompt, host=state.host, task_type=state.route, limit=4)
        ]


class ValidationPlanStage(ServiceAdapterStage):
    key = "validation_plan"
    artifact_key = "validation_plan"
    confidence_dimension = "execution"
    confidence_gain = 0.08
    estimated_latency_ms = 20

    def should_run(self, state: AdaptiveExecutionState) -> tuple[bool, str]:
        if not state.budget.include_validation_plan:
            return False, "Execution budget excludes validation planning."
        mutation = bool(state.mutation_scope and state.mutation_scope != "read_only") or state.prediction.predicted_files_touched > 0
        if not mutation:
            return False, "Read-only request does not require a mutation validation plan."
        return True, "A validation contract is required before mutation."

    def evaluate(self, state: AdaptiveExecutionState) -> StageDecision:
        decision = super().evaluate(state)
        decision.required = bool(state.mutation_scope and state.mutation_scope != "read_only")
        decision.priority = 90.0 if decision.required else decision.priority
        return decision

    def run_existing_service(self, state: AdaptiveExecutionState) -> Any:
        from services.validation_planner_service import plan_validation_for_paths

        paths = []
        if state.active_file:
            paths.append(state.active_file)
        return {
            "planned_steps": plan_validation_for_paths(paths, project_root=state.project_roots[0] if state.project_roots else None),
            "predicted_validation_types": list(state.prediction.predicted_validation_types),
            "runtime_validation_required": any("runtime" in item for item in state.prediction.predicted_validation_types),
        }


def default_shadow_stages() -> list[AdaptiveStage]:
    return [
        IntentStage(),
        CodeIntelligenceStage(),
        DomainExpertStage(),
        GoalGapStage(),
        StudioProfileStage(),
        ValidationPlanStage(),
    ]
