from __future__ import annotations

"""Value-based adaptive stage scheduler.

This implementation is deliberately side-effect free until ``run`` is called.
It is suitable for shadow-mode comparison with the current fixed pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from services.adaptive_execution_state import AdaptiveExecutionState, StageDecision


class AdaptiveStage(ABC):
    key: str = "stage"

    @abstractmethod
    def evaluate(self, state: AdaptiveExecutionState) -> StageDecision:
        raise NotImplementedError

    @abstractmethod
    def execute(self, state: AdaptiveExecutionState) -> AdaptiveExecutionState:
        raise NotImplementedError


@dataclass
class SchedulerResult:
    state: AdaptiveExecutionState
    status: str
    iterations: int
    executed_stages: list[str] = field(default_factory=list)
    skipped_stages: list[str] = field(default_factory=list)
    next_stage: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "iterations": self.iterations,
            "executed_stages": list(self.executed_stages),
            "skipped_stages": list(self.skipped_stages),
            "next_stage": self.next_stage,
            "reason": self.reason,
            "state": self.state.to_dict(),
        }


class AdaptiveStageScheduler:
    def __init__(self, stages: Iterable[AdaptiveStage], *, max_iterations: int = 16) -> None:
        self.stages = list(stages)
        self.max_iterations = max(1, int(max_iterations))

    def evaluate(self, state: AdaptiveExecutionState) -> list[StageDecision]:
        decisions: list[StageDecision] = []
        for stage in self.stages:
            if state.has_stage_finished(stage.key):
                continue
            decision = stage.evaluate(state)
            if decision.stage_key != stage.key:
                decision.stage_key = stage.key
            decisions.append(decision)
            state.record_stage_decision(decision)
        return decisions

    def select_next(self, state: AdaptiveExecutionState) -> tuple[AdaptiveStage | None, StageDecision | None]:
        stage_by_key = {stage.key: stage for stage in self.stages}
        decisions = self.evaluate(state)
        runnable = [decision for decision in decisions if decision.should_run]
        if not runnable:
            return None, None
        runnable.sort(key=lambda item: (item.required, item.value_score, item.priority), reverse=True)
        selected = runnable[0]
        return stage_by_key.get(selected.stage_key), selected

    def run(self, state: AdaptiveExecutionState, *, shadow_mode: bool = False) -> SchedulerResult:
        executed: list[str] = []
        skipped: list[str] = []
        for iteration in range(1, self.max_iterations + 1):
            stop_reason = self._stop_reason(state)
            if stop_reason:
                return SchedulerResult(state, "stopped", iteration - 1, executed, skipped, reason=stop_reason)

            decisions = self.evaluate(state)
            for decision in decisions:
                if not decision.should_run and not state.has_stage_finished(decision.stage_key):
                    state.mark_skipped(decision.stage_key, decision.reason or "Stage did not provide enough expected value.")
                    skipped.append(decision.stage_key)

            runnable = [decision for decision in decisions if decision.should_run and not state.has_stage_finished(decision.stage_key)]
            if not runnable:
                status = "sufficient" if state.sufficiency().get("sufficient") else "no_runnable_stage"
                return SchedulerResult(state, status, iteration - 1, executed, skipped, reason="No runnable adaptive stage remains.")

            runnable.sort(key=lambda item: (item.required, item.value_score, item.priority), reverse=True)
            selected = runnable[0]
            stage = next((item for item in self.stages if item.key == selected.stage_key), None)
            if stage is None:
                state.warnings.append(f"Scheduler selected missing stage: {selected.stage_key}")
                continue
            state.current_stage = stage.key
            state.diagnostics.append({"event": "stage_selected", "decision": selected.to_dict(), "shadow_mode": shadow_mode})
            if shadow_mode:
                return SchedulerResult(
                    state,
                    "shadow_selected",
                    iteration,
                    executed,
                    skipped,
                    next_stage=stage.key,
                    reason=selected.reason,
                )
            try:
                stage.execute(state)
                state.mark_completed(stage.key)
                executed.append(stage.key)
            except Exception as exc:
                state.current_stage = ""
                state.warnings.append(f"{stage.key} failed: {exc}")
                state.diagnostics.append({"event": "stage_failed", "stage": stage.key, "error": str(exc)})
                return SchedulerResult(state, "stage_failed", iteration, executed, skipped, reason=str(exc))

        return SchedulerResult(state, "iteration_limit", self.max_iterations, executed, skipped, reason="Adaptive scheduler reached its iteration limit.")

    @staticmethod
    def _stop_reason(state: AdaptiveExecutionState) -> str:
        if state.requires_confirmation:
            return "User confirmation is required before continuing."
        if state.missing_information:
            return "Minimum required context is missing."
        if state.sufficiency().get("sufficient"):
            return "Current evidence and confidence are sufficient."
        return ""
