"""Resource-aware prompt orchestration policy.

This module does not execute prompts. It defines how Tech Connector should use
local resources for a prompt so deterministic work can overlap while local
model calls remain bounded instead of competing with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any


@dataclass(frozen=True)
class ResourceLane:
    key: str
    label: str
    max_concurrent: int
    work: tuple[str, ...]
    user_visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "max_concurrent": self.max_concurrent,
            "work": list(self.work),
            "user_visible": self.user_visible,
        }


def build_resource_orchestration_plan(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the resource policy for a prompt.

    The important default is that read-only deterministic discovery may run in
    parallel, but local Ollama/model work is serialized. On a workstation this
    tends to beat multiple simultaneous model requests, which compete for RAM,
    disk, and CPU/GPU scheduling and make all agents slower.
    """

    decision = dict(decision or {})
    prompt_text = prompt or ""
    complexity = _complexity_score(prompt_text)
    cpu_count = os.cpu_count() or 4
    deterministic_workers = max(2, min(4, cpu_count // 2 or 2))
    if complexity >= 5:
        deterministic_workers = max(3, deterministic_workers)
    requires_mutation = _requires_mutation(prompt_text, decision)
    model_workers = 1
    lanes = [
        ResourceLane(
            "intent",
            "Intent and routing",
            1,
            ("normalize goal", "classify route", "select host/context"),
        ),
        ResourceLane(
            "deterministic_discovery",
            "Parallel deterministic discovery",
            deterministic_workers,
            ("project index search", "active file inspection", "known practices", "read-only host snapshots"),
        ),
        ResourceLane(
            "local_model_serial",
            "Serialized local model work",
            model_workers,
            ("target selection", "implementation planning", "patch generation"),
        ),
        ResourceLane(
            "mutation_serial",
            "Serialized mutation and validation",
            1,
            ("file/asset writes", "graph edits", "compile", "validation"),
        ),
        ResourceLane(
            "reporting",
            "Continuous user reporting",
            1,
            ("progress cards", "handoff summaries", "final report"),
        ),
    ]
    return {
        "framework": "resource_aware_prompt_orchestration_v1",
        "complexity": complexity,
        "requires_mutation": requires_mutation,
        "policy": "Parallelize deterministic reads; serialize local model and mutation lanes; keep reporting active.",
        "local_model_concurrency": model_workers,
        "deterministic_concurrency": deterministic_workers,
        "lanes": [lane.to_dict() for lane in lanes],
        "handoff_order": [
            "intent -> deterministic_discovery",
            "deterministic_discovery -> local_model_serial as soon as minimum evidence exists",
            "local_model_serial -> mutation_serial only when mutation is required and approved/safe",
            "all lanes -> reporting with compact observable handoffs",
        ],
        "timeout_policy": {
            "total_work_timeout": "avoid fixed total timeout for long approved work",
            "no_progress_seconds": 30,
            "model_call_policy": "bounded per-stage timeout with visible wait status and smaller prompt packets",
        },
        "early_completion_policy": {
            "principle": "stop a stage as soon as its answer is sufficient for the next handoff",
            "applies_to": [
                "retrieval",
                "intent clarification",
                "target selection",
                "planning",
                "validation diagnosis",
                "final reporting",
            ],
            "handoff_unit": "structured evidence, decision, assumptions, missing fields, and next action",
            "large_model_rule": "use large models for hard synthesis/code only; do not spend them on presentation once the answer is known",
        },
        "compiled_pipeline_policy": {
            "principle": "after planning is sufficient, convert repeatable operations into deterministic callable pipeline steps",
            "when_to_compile": [
                "the target asset/file/function is known",
                "required inputs and approvals are resolved",
                "the operation may be rerun, validated, or promoted into a saved pipeline",
                "execution can be expressed as project functions or generated wrapper functions",
            ],
            "script_contract": [
                "typed inputs",
                "preflight validation",
                "small undoable steps",
                "structured logs",
                "artifacts/changed files report",
                "verification hooks",
                "rollback notes or rollback function when practical",
            ],
            "execution_rule": "run compiled steps through deterministic function calls; return to model reasoning only for diagnosis, missing context, or failed validation",
        },
        "function_result_loop_policy": {
            "principle": "agents should call the next best deterministic function, inspect its structured result, then decide whether another function is needed",
            "loop": [
                "select callable from indexed capabilities or compiled pipeline script",
                "validate inputs and safety requirements",
                "execute callable",
                "parse structured result, artifacts, warnings, and errors",
                "run sufficiency check against the current objective",
                "report if sufficient; otherwise choose the next callable or ask for missing context",
            ],
            "model_rule": "the model chooses and interprets steps; deterministic functions perform the work",
            "stop_rule": "stop the loop once the objective is satisfied, validation fails unrecoverably, or user approval/context is required",
        },
        "model_tier_policy": {
            "intent": "none_deterministic",
            "deterministic_discovery": "none_deterministic",
            "rag_sufficiency": "none_deterministic_or_local_fast",
            "context_summarization": "local_plan_or_fast",
            "implementation_planning": "local_plan_or_deep_when_explicitly_complex",
            "patch_generation": "local_code",
            "validation": "none_deterministic_or_local_code_for_diagnosis",
        },
    }


def render_resource_orchestration_summary(plan: dict[str, Any] | None) -> str:
    if not plan:
        return ""
    lanes = list(plan.get("lanes") or [])
    lines = [
        "Resource plan:",
        f"- Policy: {plan.get('policy')}",
        f"- Deterministic workers: {plan.get('deterministic_concurrency')}",
        f"- Local model workers: {plan.get('local_model_concurrency')}",
    ]
    for lane in lanes[:5]:
        lines.append(
            f"- {lane.get('label')} [{lane.get('key')}]: max {lane.get('max_concurrent')}"
        )
    return "\n".join(lines)


def _complexity_score(prompt: str) -> int:
    text = prompt or ""
    score = 1
    score += min(4, len(text) // 1200)
    score += min(3, len(re.findall(r"^\s*\d+[.)]\s+", text, flags=re.MULTILINE)) // 6)
    lower = text.lower()
    for term in ("before making", "implementation requirements", "after implementation", "validate", "rollback", "compile"):
        if term in lower:
            score += 1
    return min(10, score)


def _requires_mutation(prompt: str, decision: dict[str, Any]) -> bool:
    mutation = str(decision.get("mutation_scope") or "").lower()
    if mutation and mutation != "read_only":
        return True
    lower = (prompt or "").lower()
    if re.search(r"\b(do not edit|do not change|do not make changes|plan only|explain how)\b", lower):
        return False
    return bool(re.search(r"\b(add|create|implement|write|patch|modify|update|fix|connect|wire|refactor|build)\b", lower))
