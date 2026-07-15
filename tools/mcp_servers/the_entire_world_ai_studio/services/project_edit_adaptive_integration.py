from __future__ import annotations

"""Drop-in helpers for integrating Milestone B with project_edit_agent_service."""

from typing import Any

from services.adaptive_contribution_providers import registry_from_state_artifacts
from services.adaptive_execution_engine import AdaptiveExecutionEngine
from services.adaptive_prompt_assembler import AdaptivePromptAssembler
from services.adaptive_stage_scheduler import AdaptiveStageScheduler
from services.adaptive_stages.core_stages import default_shadow_stages


def build_project_edit_adaptive_engine(function_loop=None) -> AdaptiveExecutionEngine:
    return AdaptiveExecutionEngine(
        scheduler=AdaptiveStageScheduler(default_shadow_stages()),
        prompt_assembler=AdaptivePromptAssembler(registry_from_state_artifacts()),
        function_loop=function_loop,
    )


def prepare_adaptive_project_edit(
    state: Any,
    *,
    settings: dict[str, Any] | None = None,
    selected_model: str | None = None,
) -> dict[str, Any]:
    """Run real adaptive stages and produce a bounded project-edit model request."""
    engine = build_project_edit_adaptive_engine()
    prepared = engine.prepare(
        state,
        stage_type="patch_generation" if _requires_patch(state.original_prompt) else "planning",
        settings=settings,
        selected_model=selected_model,
        system_prefix=(
            "You are a senior project code agent. Use supplied project evidence and registered functions first. "
            "Do not invent files or APIs. Produce XML patch tags only when mutation is requested and safe."
        ),
    )
    return prepared.to_dict()


def _requires_patch(prompt: str) -> bool:
    lower = (prompt or "").lower()
    if any(term in lower for term in ("plan only", "do not edit", "inspect only", "explain only")):
        return False
    return any(term in lower for term in ("fix", "add", "create", "modify", "update", "patch", "implement", "refactor", "wire"))


def project_edit_scope_guard(state: Any) -> dict[str, Any]:
    """Return a deterministic gate before any model-generated patch is accepted."""
    from services.execution_contract_service import ExecutionContract, render_execution_contract
    contract_data = dict(getattr(state, "execution_contract", {}) or {})
    contract = ExecutionContract.from_dict(contract_data) if contract_data else None
    if contract is None:
        return {"ok": False, "status": "missing_execution_contract", "reason": "No execution contract was attached."}
    if contract.requires_clarification:
        return {
            "ok": False,
            "status": "clarification_required",
            "reason": "; ".join(contract.ambiguity_reasons) or "Target ambiguity remains.",
            "contract": contract.to_dict(),
        }
    return {"ok": True, "status": "scope_ready", "contract": contract.to_dict(), "prompt_context": render_execution_contract(contract)}
