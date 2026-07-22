from __future__ import annotations

"""Milestone B facade: schedule evidence, assemble prompt, choose model, run functions."""

from dataclasses import dataclass
from typing import Any, Iterable

from services.adaptive_model_budget_service import choose_adaptive_model_budget
from services.adaptive_prompt_assembler import AdaptivePromptAssembler, PromptAssemblyResult
from services.adaptive_stage_scheduler import AdaptiveStageScheduler, SchedulerResult
from services.capability_function_loop_service import CapabilityFunctionLoop, FunctionCallSpec


@dataclass
class AdaptiveExecutionPreparation:
    scheduler_result: SchedulerResult
    prompt_assembly: PromptAssemblyResult
    model_budget: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduler_result": self.scheduler_result.to_dict(),
            "prompt_assembly": self.prompt_assembly.to_dict(),
            "model_budget": dict(self.model_budget),
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
    ) -> AdaptiveExecutionPreparation:
        scheduler_result = self.scheduler.run(state, shadow_mode=False)
        assembly = self.prompt_assembler.assemble(
            state,
            base_prompt=state.original_prompt,
            provider_keys=provider_keys,
            system_prefix=system_prefix,
        )
        model_budget = choose_adaptive_model_budget(
            state,
            stage_type=stage_type,
            settings=settings,
            selected_model=selected_model,
        ).to_dict()
        state.artifacts["model_budget"] = model_budget
        return AdaptiveExecutionPreparation(scheduler_result, assembly, model_budget)

    def execute_functions(
        self,
        state: Any,
        plan: Iterable[FunctionCallSpec],
        *,
        approval_granted: bool = False,
        sufficiency_check=None,
    ) -> dict[str, Any]:
        if self.function_loop is None:
            return {"status": "function_loop_unavailable", "reason": "No function loop was configured.", "results": []}
        return self.function_loop.run(
            state,
            plan,
            approval_granted=approval_granted,
            sufficiency_check=sufficiency_check,
        )
