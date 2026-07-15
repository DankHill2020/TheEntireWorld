from __future__ import annotations

"""Deterministic, explainable request prediction for shadow-mode orchestration."""

import re
from typing import Any

from services.adaptive_execution_state import (
    AdaptiveExecutionState,
    ExecutionBudget,
    PredictionRecord,
)


def predict_request(
    state: AdaptiveExecutionState,
    *,
    similar_execution_history: list[dict[str, Any]] | None = None,
) -> PredictionRecord:
    prompt = state.original_prompt or ""
    lower = prompt.lower()
    route_data = dict(state.artifacts.get("route_decision") or {})
    history = list(similar_execution_history or [])

    complexity = 0.08
    reasons: list[str] = []
    word_count = len(prompt.split())
    numbered_steps = len(re.findall(r"^\s*\d+[.)]\s+", prompt, flags=re.MULTILINE))
    connector_count = len(re.findall(r"\b(then|after|before|validate|compile|rollback|repair|report|import|export|connect)\b", lower))
    mutation = bool(state.mutation_scope and state.mutation_scope != "read_only") or bool(
        re.search(r"\b(add|create|implement|modify|update|fix|patch|refactor|write|wire|connect|delete|remove)\b", lower)
    )
    hosts = {item for item in ("maya", "unreal", "blender", "houdini", "motionbuilder", "unity") if item in lower}

    if word_count >= 40:
        complexity += 0.08
        reasons.append("prompt has substantial instruction detail")
    if word_count >= 120:
        complexity += 0.12
        reasons.append("prompt is long enough to require staged handling")
    if numbered_steps >= 3 or connector_count >= 4:
        complexity += 0.2
        reasons.append("request appears multi-step")
    if mutation:
        complexity += 0.15
        reasons.append("request mutates code or application state")
    if len(hosts) > 1:
        complexity += 0.2
        reasons.append("request crosses multiple DCC or engine hosts")
    elif hosts:
        complexity += 0.08
        reasons.append("request depends on host-specific context")
    if route_data.get("requires_plan"):
        complexity += 0.1
        reasons.append("route explicitly requires planning")
    if str(route_data.get("compound_kind") or "atomic") != "atomic":
        complexity += 0.12
        reasons.append("route contains compound operations")
    if route_data.get("capability_gaps") or route_data.get("missing_info"):
        complexity += 0.12
        reasons.append("known capability or information gaps exist")
    complexity = min(1.0, complexity)

    novelty = 0.5
    if state.active_file:
        novelty -= 0.1
    if state.operation_memory:
        novelty -= 0.12
    if route_data.get("can_execute_directly"):
        novelty -= 0.12
    if route_data.get("capability_gaps"):
        novelty += 0.2
    if any(term in lower for term in ("new system", "from scratch", "architecture", "unknown", "research", "find online")):
        novelty += 0.15
    if history:
        successes = [item for item in history if item.get("actual_success") is True or item.get("status") in {"complete", "applied", "success"}]
        novelty -= min(0.2, len(successes) * 0.04)
        reasons.append("similar execution history was available")
    novelty = max(0.0, min(1.0, novelty))

    risk = 0.08
    risk_label = (state.risk_level or "").lower()
    risk += {"low": 0.05, "medium": 0.3, "high": 0.55}.get(risk_label, 0.0)
    if mutation:
        risk += 0.18
    if state.requires_confirmation:
        risk += 0.12
    if any(term in lower for term in ("delete", "overwrite", "migrate", "rename", "bake", "publish", "submit", "force")):
        risk += 0.25
        reasons.append("request contains destructive or broad mutation terms")
    if len(hosts) > 1:
        risk += 0.12
    risk = max(0.0, min(1.0, risk))

    predicted_files = 0
    if mutation:
        predicted_files = 1
        if complexity >= 0.45:
            predicted_files = 2
        if complexity >= 0.7:
            predicted_files = 4
        explicit_files = len(re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|cpp|h|hpp|cs|json|yaml|yml)\b", prompt))
        predicted_files = max(predicted_files, explicit_files)

    predicted_context = int(900 + complexity * 6200 + novelty * 1700)
    predicted_output = int(120 + complexity * 1250 + (500 if mutation else 0))
    predicted_runtime = int(500 + complexity * 50_000 + risk * 25_000 + (20_000 if hosts else 0))

    validation = []
    if mutation:
        validation.append("python_syntax" if ".py" in lower or state.route in {"code_edit", "project_edit"} else "static_validation")
    if any(term in lower for term in ("qt", "pyside", "ui", "widget", "dialog", "window")):
        validation.append("qt_ui_smoke")
    if "maya" in hosts:
        validation.append("maya_runtime_smoke")
    if "unreal" in hosts:
        validation.append("unreal_runtime_compile")
    if complexity >= 0.55 and mutation:
        validation.append("focused_tests")
    validation = list(dict.fromkeys(validation))

    failures = []
    if not state.active_file and mutation:
        failures.append("ambiguous_or_missing_target")
    if route_data.get("capability_gaps"):
        failures.append("missing_capability")
    if mutation:
        failures.extend(["patch_original_mismatch", "syntax_or_compile_failure"])
    if hosts:
        failures.append("host_unavailable_or_stale_context")
    if len(hosts) > 1:
        failures.append("cross_host_artifact_or_contract_mismatch")
    failures = list(dict.fromkeys(failures))

    success = 0.92 - risk * 0.38 - novelty * 0.2 - complexity * 0.12
    if state.active_file:
        success += 0.05
    if state.operation_memory:
        success += 0.04
    success = max(0.05, min(0.98, success))

    prediction = PredictionRecord(
        complexity_score=round(complexity, 3),
        novelty_score=round(novelty, 3),
        risk_score=round(risk, 3),
        predicted_runtime_ms=predicted_runtime,
        predicted_context_tokens=predicted_context,
        predicted_output_tokens=predicted_output,
        predicted_files_touched=predicted_files,
        predicted_validation_types=validation,
        predicted_failure_modes=failures,
        predicted_success_probability=round(success, 3),
        reasons=reasons or ["request matched the low-complexity deterministic baseline"],
    )
    state.prediction = prediction
    state.budget = budget_from_prediction(state, prediction)
    return prediction


def budget_from_prediction(state: AdaptiveExecutionState, prediction: PredictionRecord) -> ExecutionBudget:
    complexity = prediction.complexity_score
    risk = prediction.risk_score
    mutation = bool(state.mutation_scope and state.mutation_scope != "read_only") or prediction.predicted_files_touched > 0
    if complexity < 0.28 and risk < 0.25:
        budget = ExecutionBudget(
            token_budget=3072,
            reserved_output_tokens=384,
            retrieval_items=2,
            expert_limit=0,
            reasoning_level="minimal",
            validation_level="static" if mutation else "none",
            runtime_budget_ms=60_000,
            max_model_calls=1 if mutation else 0,
            include_goal_gap=False,
            include_domain_experts=False,
            include_work_memory=False,
            include_studio_profile=mutation,
            include_validation_plan=mutation,
        )
    elif complexity < 0.62:
        budget = ExecutionBudget(
            token_budget=6144,
            reserved_output_tokens=min(1200, max(512, prediction.predicted_output_tokens)),
            retrieval_items=6,
            expert_limit=2,
            reasoning_level="standard",
            validation_level="focused",
            runtime_budget_ms=180_000,
            max_model_calls=2,
            allow_live_dcc_context=bool(state.host),
            include_goal_gap=bool(state.missing_information or prediction.novelty_score > 0.6),
            include_domain_experts=True,
            include_work_memory=bool(state.operation_memory),
            include_studio_profile=True,
            include_validation_plan=True,
        )
    else:
        budget = ExecutionBudget(
            token_budget=8192,
            reserved_output_tokens=min(1800, max(900, prediction.predicted_output_tokens)),
            retrieval_items=10,
            expert_limit=4,
            reasoning_level="deep",
            validation_level="runtime_and_focused_tests",
            runtime_budget_ms=360_000,
            max_model_calls=3,
            allow_external_research=prediction.novelty_score > 0.7,
            allow_live_dcc_context=bool(state.host),
            include_goal_gap=True,
            include_domain_experts=True,
            include_work_memory=True,
            include_studio_profile=True,
            include_validation_plan=True,
        )
    budget.normalize()
    return budget


def build_shadow_execution_state(
    prompt: str,
    route_decision: dict[str, Any] | Any | None,
    *,
    active_file: str = "",
    project_roots: list[str] | tuple[str, ...] = (),
    operation_memory: dict[str, Any] | None = None,
    similar_execution_history: list[dict[str, Any]] | None = None,
) -> AdaptiveExecutionState:
    state = AdaptiveExecutionState.from_route_decision(
        prompt,
        route_decision,
        active_file=active_file,
        project_roots=project_roots,
        operation_memory=operation_memory,
    )
    predict_request(state, similar_execution_history=similar_execution_history)
    return state
