from __future__ import annotations

"""Goal-scoped adaptive execution orchestration.

This service schedules evidence, chooses a model budget, and assembles a prompt
for the next executable goal.  It does not collapse a multi-goal request back
into one monolithic model call.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from tech_connector.services.adaptive.model_budget import choose_adaptive_model_budget
from tech_connector.services.adaptive.prompt_assembler import AdaptivePromptAssembler, PromptAssemblyResult
from tech_connector.services.adaptive.stage_scheduler import AdaptiveStageScheduler, SchedulerResult
from tech_connector.services.capability_function_loop_service import CapabilityFunctionLoop, FunctionCallSpec


@dataclass
class AdaptiveExecutionPreparation:
    scheduler_result: SchedulerResult
    prompt_assembly: PromptAssemblyResult
    model_budget: dict[str, Any]
    current_goal: dict[str, Any] | None = None
    is_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduler_result": self.scheduler_result.to_dict(),
            "prompt_assembly": self.prompt_assembly.to_dict(),
            "model_budget": dict(self.model_budget),
            "current_goal": dict(self.current_goal or {}),
            "is_complete": self.is_complete,
        }


class AdaptiveExecutionEngine:
    def __init__(
        self,
        *,
        scheduler: AdaptiveStageScheduler,
        prompt_assembler: AdaptivePromptAssembler,
        function_loop: CapabilityFunctionLoop | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.prompt_assembler = prompt_assembler
        self.function_loop = function_loop

    def prepare(
        self,
        state: Any,
        *,
        stage_type: str = "planning",
        provider_keys: Iterable[str] | None = None,
        system_prefix: str = "",
        settings: dict[str, Any] | None = None,
        selected_model: str | None = None,
        goal: Mapping[str, Any] | Any | None = None,
    ) -> AdaptiveExecutionPreparation:
        """Prepare the next goal, falling back to legacy request assembly."""
        scheduler_result = self.scheduler.run(state, shadow_mode=False)
        current_goal = _as_goal_dict(goal) if goal is not None else self.next_executable_goal(state)
        is_complete = current_goal is None and bool(self.goal_graph(state))

        model_budget = choose_adaptive_model_budget(
            state,
            stage_type=stage_type,
            settings=settings,
            selected_model=selected_model,
        ).to_dict()
        state.artifacts["model_budget"] = model_budget

        if current_goal is None:
            assembly = self.prompt_assembler.assemble(
                state,
                base_prompt=state.original_prompt,
                provider_keys=provider_keys,
                system_prefix=system_prefix,
            )
        else:
            state.artifacts["current_goal"] = dict(current_goal)
            assembly = self.prompt_assembler.assemble_goal(
                state,
                current_goal,
                provider_keys=provider_keys,
                system_prefix=system_prefix,
                previous_outputs=self.goal_outputs(state),
                evidence=getattr(state, "evidence", None),
            )

        return AdaptiveExecutionPreparation(
            scheduler_result=scheduler_result,
            prompt_assembly=assembly,
            model_budget=model_budget,
            current_goal=current_goal,
            is_complete=is_complete,
        )

    def goal_graph(self, state: Any) -> list[dict[str, Any]]:
        artifacts = getattr(state, "artifacts", {}) or {}
        candidates = (
            artifacts.get("goal_graph")
            or artifacts.get("task_graph")
            or artifacts.get("prompt_execution_context", {}).get("goal_graph")
            or artifacts.get("route_decision", {}).get("goal_graph")
            or []
        )
        if isinstance(candidates, Mapping):
            candidates = candidates.get("goals") or candidates.get("nodes") or candidates.get("tasks") or []
        return [_as_goal_dict(item) for item in candidates if item is not None]

    def goal_outputs(self, state: Any) -> dict[str, Any]:
        artifacts = getattr(state, "artifacts", {})
        return artifacts.setdefault("goal_outputs", {})

    def completed_goal_ids(self, state: Any) -> set[str]:
        artifacts = getattr(state, "artifacts", {})
        return set(str(item) for item in artifacts.setdefault("completed_goal_ids", []) if item)

    def next_executable_goal(self, state: Any) -> dict[str, Any] | None:
        completed = self.completed_goal_ids(state)
        for index, goal in enumerate(self.goal_graph(state), start=1):
            goal_id = _goal_id(goal, index)
            if goal_id in completed:
                continue
            dependencies = [str(item) for item in goal.get("depends_on") or goal.get("dependencies") or [] if item]
            if all(dependency in completed for dependency in dependencies):
                goal.setdefault("goal_id", goal_id)
                return goal
        return None

    def commit_goal_result(
        self,
        state: Any,
        goal: Mapping[str, Any] | Any,
        result: Any,
        *,
        validated: bool | None = None,
        validation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a goal result only when it satisfies the answer contract."""
        goal_data = _as_goal_dict(goal)
        goal_id = str(goal_data.get("goal_id") or goal_data.get("id") or "")
        if not goal_id:
            raise ValueError("Cannot commit a goal result without a goal_id or id")

        from tech_connector.services.answer_sufficiency_service import validate_answer_sufficiency

        adequacy = validate_answer_sufficiency(state, result, goal=goal_data)
        externally_valid = True if validated is None else bool(validated)
        final_valid = externally_valid and adequacy.sufficient
        merged_validation = dict(validation or {})
        merged_validation["answer_sufficiency"] = adequacy.to_dict()

        record = {
            "goal_id": goal_id,
            "result": result,
            "validated": final_valid,
            "validation": merged_validation,
        }
        self.goal_outputs(state)[goal_id] = record
        state.artifacts.setdefault("answer_validation_history", []).append(adequacy.to_dict())
        if final_valid:
            completed = self.completed_goal_ids(state)
            completed.add(goal_id)
            state.artifacts["completed_goal_ids"] = sorted(completed)
            state.artifacts.pop("current_goal", None)
            state.artifacts.pop("pending_evidence_escalation", None)
        else:
            failed = state.artifacts.setdefault("failed_goal_ids", [])
            if goal_id not in failed:
                failed.append(goal_id)
            state.artifacts["pending_evidence_escalation"] = {
                "goal_id": goal_id,
                "next_action": adequacy.next_action,
                "execution_tier": adequacy.escalation_tier,
                "failures": list(adequacy.failures),
                "expected_target": adequacy.expected_target,
                "expected_scope": adequacy.expected_scope,
            }
        return record

    def execute_functions(
        self,
        state: Any,
        plan: Iterable[FunctionCallSpec],
        *,
        approval_granted: bool = False,
        sufficiency_check=None,
    ) -> dict[str, Any]:
        if self.function_loop is None:
            return {
                "status": "function_loop_unavailable",
                "reason": "No function loop was configured.",
                "results": [],
            }
        return self.function_loop.run(
            state,
            plan,
            approval_granted=approval_granted,
            sufficiency_check=sufficiency_check,
        )


def _as_goal_dict(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    raise TypeError("goal must be a mapping or expose to_dict()/__dict__")


def _goal_id(goal: Mapping[str, Any], index: int) -> str:
    return str(goal.get("goal_id") or goal.get("id") or goal.get("step_id") or f"goal_{index}")

