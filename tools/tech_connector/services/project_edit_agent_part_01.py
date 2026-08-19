"""Shared imports and constants for project edit agent implementation."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import time
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from tech_connector.services.project_edit_requirement_semantics import (
    is_project_edit_quality_requirement,
)


PROJECT_EDIT_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "modify",
                            "replace_symbol",
                            "insert_before_symbol",
                            "insert_after_symbol",
                            "replace_text",
                            "insert_before_text",
                            "insert_after_text",
                            "ensure_import",
                        ],
                    },
                    "path": {"type": "string"},
                    "target_symbol": {"type": "string"},
                    "original_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["action", "path", "target_symbol", "original_content", "new_content"],
                "additionalProperties": False,
            },
        },
        "report": {
            "type": "object",
            "properties": {
                "changed": {"type": "array", "items": {"type": "string"}},
                "reused": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "array", "items": {"type": "string"}},
                "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                "requirement_coverage": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "requirement": {"type": "string"},
                            "production_owners": {"type": "array", "items": {"type": "string"}},
                            "test_owners": {"type": "array", "items": {"type": "string"}},
                            "validation": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "requirement",
                            "production_owners",
                            "test_owners",
                            "validation",
                            "status",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "changed",
                "reused",
                "verification",
                "remaining_gaps",
                "requirement_coverage",
            ],
            "additionalProperties": False,
        },
        "blocked_reason": {"type": "string"},
    },
    "required": ["changes", "report", "blocked_reason"],
    "additionalProperties": False,
}

PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"corrected_source": {"type": "string"}},
    "required": ["corrected_source"],
    "additionalProperties": False,
}

PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "algorithm_steps": {"type": "array", "items": {"type": "string"}},
        "preserve": {"type": "array", "items": {"type": "string"}},
        "postconditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["root_cause", "algorithm_steps", "preserve", "postconditions"],
    "additionalProperties": False,
}

PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": {
            "type": "object",
            "properties": {
                "canonical_owners": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "signatures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "shared_invariants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "data_layout": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "errors": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            ],
            "additionalProperties": False,
            "description": (
                "Concrete package-wide API/data contracts: canonical owners, exact signatures "
                "and defaults, shared layouts/constants, bounds, and errors."
            ),
        },
        "files": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "contracts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "algorithm_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "validation_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "contracts",
                    "algorithm_steps",
                    "validation_steps",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["integration_contracts", "files"],
    "additionalProperties": False,
}

PROJECT_EDIT_INTEGRATION_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA[
            "properties"
        ]["integration_contracts"],
    },
    "required": ["integration_contracts"],
    "additionalProperties": False,
}

PROJECT_EDIT_FILE_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}


@dataclass
class ProjectEditPlan:
    prompt: str
    discovery: dict[str, Any]
    discovery_context: str
    model_prompt: str
    active_path: str = ""
    intelligence_packet: dict[str, Any] = field(default_factory=dict)
    adaptive_plan: dict[str, Any] = field(default_factory=dict)
    domain_experts: list[dict[str, Any]] = field(default_factory=list)
    success_contract: list[str] = field(default_factory=list)
    stages: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ProjectEditPromptStage:
    key: str
    label: str
    system_prompt: str
    user_prompt: str
    model_tier: str = "local_code"
    num_ctx: int = 8192
    num_predict: int = 1200
    timeout: int = 180
    resource_lane: str = "local_model_serial"
    no_progress_seconds: int = 30
    prefer_coder: bool = True
    coder_preference: str = "balanced"
    response_format: str | dict[str, Any] = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectEditLeafWorkUnits:
    """Evidence-backed boundaries for one helper, integration, and test edit."""

    helper_name: str
    target_path: str
    integration_symbol: str
    integration_source: str
    test_path: str
    test_anchor_symbol: str
    test_anchor_source: str
    owner_module: str
    target_revision: str = ""
    test_revision: str = ""


@dataclass
class ProjectEditApplyResult:
    ok: bool
    status: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    validation: list[dict[str, Any]] = field(default_factory=list)
    change_session_path: str = ""
    errors: list[str] = field(default_factory=list)


def _generated_artifact_project_discovery(
    prompt: str,
    *,
    active_path: str | None,
) -> dict[str, Any]:
    """Return project-scope evidence for a new artifact without inventing an owner file."""

    candidate_root = Path(str(active_path or Path.cwd())).resolve()
    if candidate_root.suffix or (candidate_root.exists() and candidate_root.is_file()):
        candidate_root = candidate_root.parent
    target = {
        "path": str(candidate_root),
        "score": 1000,
        "symbols": [],
        "chunks": [],
        "candidate_source": "generated_artifact_scope",
        "purpose": "Project scope for a new disposable generated artifact.",
    }
    return {
        "question": prompt,
        "terms": re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")[:20],
        "scope": "project",
        "project_roots": [str(candidate_root)],
        "active_path": "",
        "best_target": target,
        "candidates": [target],
        "confidence": "high",
        "evidence_mode": "generated_artifact_scope",
    }


def _project_edit_needs_deep_intelligence(prompt: str, discovery: dict[str, Any]) -> bool:
    confidence = str(discovery.get("confidence") or "none")
    if confidence not in {"high", "medium"}:
        return True
    return bool(re.search(
        r"\b(entire tool|whole tool|new tool|fresh tool|from scratch|large restructure|major refactor|"
        r"architecture rewrite|cross[- ]module|multi[- ]file|across .* files|new application|new app)\b",
        str(prompt or "").lower(),
    ))


def _lightweight_project_edit_intelligence_packet(
    prompt: str,
    discovery: dict[str, Any],
) -> dict[str, Any]:
    best = dict(discovery.get("best_target") or {})
    confidence = str(discovery.get("confidence") or "unknown")
    return {
        "objective": prompt or "",
        "active_path": discovery.get("active_path") or best.get("path") or "",
        "mode": "reuse_target_discovery",
        "scope": discovery.get("scope") or "project",
        "terms": list(discovery.get("terms") or [])[:12],
        "repo_map": {},
        "symbols": list(best.get("symbols") or [])[:12],
        "usages": {},
        "project_context": "",
        "sufficiency": {
            "answerable": confidence in {"high", "medium"},
            "confidence": 0.9 if confidence == "high" else 0.7 if confidence == "medium" else 0.4,
            "reasons": ["Reusing canonical target-discovery evidence."],
            "recommended_next_stage": "implementation_plan",
        },
        "validation_plan": [
            {"command": "ast.parse + compile", "reason": "Validate changed Python in memory."},
            {"command": "focused unittest", "reason": "Verify requested behavior before completion."},
        ],
        "deterministic_answer": "",
        "can_answer_without_model": False,
    }


def _build_project_edit_intelligence_packet(
    prompt: str,
    *,
    active_path: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    try:
        from tech_connector.services.code_intelligence_service import build_code_intelligence_packet

        return build_code_intelligence_packet(
            prompt,
            active_path=active_path,
            limit=max(8, min(int(limit or 8) * 3, 30)),
            include_repo_map=True,
        )
    except Exception as exc:
        return {
            "objective": prompt or "",
            "active_path": active_path or "",
            "mode": "unknown",
            "scope": "project",
            "terms": [],
            "repo_map": {},
            "symbols": [],
            "usages": {},
            "project_context": "",
            "sufficiency": {
                "answerable": False,
                "confidence": 0.0,
                "reasons": ["code_intelligence_failed"],
                "missing_requirements": [str(exc)],
            },
            "validation_plan": [],
            "deterministic_answer": "",
            "can_answer_without_model": False,
        }


def _render_project_edit_intelligence_packet(packet: dict[str, Any]) -> str:
    try:
        from tech_connector.services.code_intelligence_service import render_code_intelligence_packet

        return render_code_intelligence_packet(packet, max_context_chars=4500)
    except Exception:
        return ""


def _fallback_project_edit_discovery(
    prompt: str,
    *,
    active_path: str | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    """Build minimal target evidence when the project index is unavailable."""

    target = {
        "path": active_path or "",
        "score": 1 if active_path else 0,
        "symbols": [],
        "chunks": [],
    }
    return {
        "question": prompt,
        "terms": re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")[:12],
        "scope": "project",
        "project_roots": [],
        "best_target": target if active_path else {},
        "targets": [target] if active_path else [],
        "confidence": "low" if active_path else "none",
        "warnings": [
            "Project index target discovery was unavailable; using active file fallback.",
            str(error or ""),
        ],
    }


def build_code_agent_adaptive_plan(
    prompt: str,
    *,
    discovery: dict[str, Any] | None = None,
    active_path: str | None = None,
    intelligence_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, adaptive code-agent plan for an objective."""

    discovery = dict(discovery or {})
    intelligence_packet = dict(intelligence_packet or {})
    confidence = str(discovery.get("confidence") or "unknown")
    best_target = dict(discovery.get("best_target") or {})
    target_path = str(best_target.get("path") or active_path or "")
    requires_confirmation = confidence not in {"high", "medium"}
    target_available = bool(target_path)
    decision = {
        "route": "project_edit",
        "provider": "project_index",
        "confidence": 0.9 if confidence == "high" else 0.7 if confidence == "medium" else 0.45,
        "intent_category": "code_edit",
        "mutation_scope": "code_change",
        "risk_level": "medium" if confidence in {"high", "medium"} else "high",
        "requires_plan": True,
        "requires_confirmation": requires_confirmation,
        "can_execute_directly": target_available and not requires_confirmation,
        "context_resolvers": [
            "code_intelligence_packet",
            "repo_map",
            "symbol_lookup",
            "references_usages",
            "active_file_context",
            "validation_planner",
        ],
        "deterministic_steps": [
            "build_code_intelligence_packet",
            "build_repo_map",
            "search_symbols_docstrings_and_signatures",
            "search_references_usages_imports_and_calls",
            "discover_edit_targets",
            "format_edit_target_context",
            "parse_multi_file_changes",
            "replace_content_resilient",
            "save_change_session",
            "plan_validation_for_paths",
            "py_compile_or_targeted_tests",
        ],
        "capability_gaps": [] if target_available else ["verified edit target"],
    }
    if target_available and confidence == "high":
        gap_plan = {"framework": "goal_gap_plan_v1", "missing_links": []}
        reasoning = {
            "framework": "multi_stage_reasoning_v1",
            "stages": [
                {
                    "title": "Implement approved scope",
                    "responsibility": "Generate only evidence-backed bounded changes.",
                    "verification_gate": ["requested behavior represented", "no unsupported API"],
                },
                {
                    "title": "Validate candidate",
                    "responsibility": "Compose deterministically and run syntax, import, and test gates.",
                    "verification_gate": ["parse and compile", "imports resolve", "focused tests included"],
                },
            ],
        }
    else:
        try:
            from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan
            from tech_connector.services.reasoning.multi_stage_reasoning_service import build_reasoning_pipeline

            gap_plan = build_goal_gap_plan(prompt, decision)
            reasoning = build_reasoning_pipeline(prompt, decision)
        except Exception:
            gap_plan = {}
            reasoning = {}

    return {
        "framework": "adaptive_code_agent_v1",
        "objective": (prompt or "").strip() or "Complete requested code objective",
        "target_confidence": confidence,
        "best_target": target_path,
        "requires_confirmation": requires_confirmation,
        "deterministic_steps": list(decision.get("deterministic_steps") or []),
        "code_intelligence": {
            "mode": intelligence_packet.get("mode"),
            "scope": intelligence_packet.get("scope"),
            "can_answer_without_model": intelligence_packet.get("can_answer_without_model"),
            "terms": list(intelligence_packet.get("terms") or [])[:12],
            "validation_plan": list(intelligence_packet.get("validation_plan") or [])[:8],
        },
        "reasoning_pipeline": reasoning,
        "capability_gap_plan": gap_plan,
        "success_contract": [
            "Produce a successful output for the user objective, not just a detached snippet.",
            "Run deterministic code intelligence before model synthesis: repo map, symbol lookup, references, usages, tests, structured patching, and validation.",
            "Reuse existing project functions, classes, services, and helpers when indexed evidence shows they fit.",
            "Decompose vague or multi-step objectives into inspect, plan, edit, validate, repair, and report stages.",
            "If a direct edit is unsafe, ask for the smallest missing decision and provide the best evidenced default.",
            "For every changed file, provide XML patch tags that can be previewed and applied by the diff system.",
            "After edits, define concrete validation and fallback or rollback steps.",
            "If validation fails, diagnose and repair only from evidence; otherwise report partial completion clearly.",
            "New public callables use clear domain names, explicit interfaces, and substantive docstrings with a behavioral summary, one :param name: field per public parameter, and :return: when a value is returned.",
            "Every changed Python file must parse and compile, and every newly introduced import must resolve or be identified as a host-provided runtime dependency.",
            "Behavior changes include focused automated tests; DCC or UI runtime checks supplement rather than replace static tests.",
        ],
        "completion_loop": [
            "implement_work_supported_by_current_evidence",
            "identify_remaining_behavior_context_or_capability_gaps",
            "resolve_gaps_from_project_patterns_and_authoritative_apis",
            "bridge_each_gap_with_real_importable_code",
            "run_syntax_import_behavior_and_runtime_validation",
            "repeat_from_remaining_failures_until_complete_or_explicitly_blocked",
        ],
        "required_outputs": [
            "project facts used",
            "target decision with confidence",
            "implementation stages",
            "reused functions/classes/helpers",
            "exact patch tags or an explicit blocker",
            "validation commands/results",
            "rollback or recovery path",
            "final outcome status",
        ],
        "fallback_policy": [
            "Do not fabricate missing APIs or paths.",
            "If the target is ambiguous, return a clarification request plus the likely target and why.",
            "If no internal function fits, identify the gap and suggest creating a reusable helper in an appropriate project folder.",
            "If an edit cannot be safely completed, stop before mutation and report what evidence is missing.",
        ],
    }


def render_code_agent_expert_context(experts: list[dict[str, Any]] | None) -> str:
    """Render a compact advisory packet for code-generation prompts."""

    experts = list(experts or [])
    if not experts:
        return ""
    lines = [
        "Code/domain expert advisory context:",
        "Experts advise only; existing deterministic services still own execution.",
    ]
    for expert in experts[:5]:
        lines.append(
            f"- {expert.get('label') or expert.get('domain')} "
            f"[{expert.get('domain')}; mode={expert.get('mode')}; confidence={expert.get('confidence')}]"
        )
        responsibilities = list(expert.get("responsibilities") or [])[:2]
        required_context = list(expert.get("required_context") or [])[:3]
        validation = list(expert.get("validation_steps") or [])[:3]
        brief = list(expert.get("expert_brief") or [])[:2]
        if responsibilities:
            lines.append("  responsibilities: " + " | ".join(str(item) for item in responsibilities))
        if required_context:
            lines.append("  required context: " + ", ".join(str(item) for item in required_context))
        if validation:
            lines.append("  validation: " + " | ".join(str(item) for item in validation))
        if brief:
            lines.append("  senior brief: " + " | ".join(str(item) for item in brief))
    return "\n".join(lines)


def render_code_agent_adaptive_plan(plan: dict[str, Any] | None) -> str:
    """Render adaptive code-agent rules for the coding-model prompt."""

    if not plan:
        return ""
    lines = [
        "Adaptive code agent execution plan:",
        f"- Framework: {plan.get('framework', '')}",
        f"- Objective: {plan.get('objective', '')}",
        f"- Best target: {plan.get('best_target') or '(none)'}",
        f"- Target confidence: {plan.get('target_confidence', '')}",
        f"- Requires confirmation before mutation: {bool(plan.get('requires_confirmation'))}",
        "",
        "Success contract:",
    ]
    lines.extend(f"- {item}" for item in list(plan.get("success_contract") or []))
    completion_loop = list(plan.get("completion_loop") or [])
    if completion_loop:
        lines.append("")
        lines.append("Repeat-until-done implementation loop:")
        lines.extend(f"- {item}" for item in completion_loop)
    deterministic_steps = list(plan.get("deterministic_steps") or [])
    if deterministic_steps:
        lines.append("")
        lines.append("Deterministic IDE-agent steps before model synthesis:")
        lines.extend(f"- {item}" for item in deterministic_steps)
    lines.append("")
    lines.append("Required output sections:")
    lines.extend(f"- {item}" for item in list(plan.get("required_outputs") or []))
    lines.append("")
    lines.append("Fallback policy:")
    lines.extend(f"- {item}" for item in list(plan.get("fallback_policy") or []))
    reasoning = dict(plan.get("reasoning_pipeline") or {})
    stages = list(reasoning.get("stages") or [])
    if stages:
        lines.append("")
        lines.append("Adaptive stages to follow:")
        for stage in stages[:8]:
            gates = "; ".join(stage.get("verification_gate") or [])
            lines.append(f"- {stage.get('title')}: {stage.get('responsibility')}")
            if gates:
                lines.append(f"  Gate: {gates}")
    gap = dict(plan.get("capability_gap_plan") or {})
    missing = list(gap.get("missing_links") or [])
    if missing:
        lines.append("")
        lines.append("Capability gaps to resolve before claiming success:")
        for item in missing[:5]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('label') or item.get('to') or item}")
            else:
                lines.append(f"- {item}")
    return "\n".join(lines)


def complete_project_edit_integration_contract_response(
    response: str,
    requirement_ledger: list[dict[str, str]],
) -> tuple[str, list[str]]:
    """Complete universally implied coordination contracts before validation."""

    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError):
        return response, []
    contracts = payload.get("integration_contracts") if isinstance(payload, dict) else None
    if not isinstance(contracts, dict):
        return response, []
    required = " ".join(
        str(item.get("text") or "")
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    ).lower()
    signatures = [
        str(value) for value in contracts.setdefault("signatures", [])
    ]
    invariants = [
        str(value) for value in contracts.setdefault("shared_invariants", [])
    ]
    data_layout = [
        str(value) for value in contracts.setdefault("data_layout", [])
    ]
    fixes: list[str] = []
    signature_blob = " ".join(signatures).lower()
    if "observer" in required and not re.search(
        r"\b(?:add|register|remove|emit|notify)_[A-Za-z0-9_]*observer"
        r"\s*\([^)]*\)",
        signature_blob,
    ):
        signatures.extend([
            "register_observer(observer: Callable[[str], None]) -> None",
            "remove_observer(observer: Callable[[str], None]) -> None",
            "emit_observer_event(event: str) -> None",
        ])
        invariants.append(
            "Observer callback failures are isolated so one observer cannot block others."
        )
        fixes.append("completed observer registration, removal, and emission contracts")
    contract_blob = " ".join([*signatures, *invariants, *data_layout]).lower()
    if (
        "drain" in required
        and re.search(r"\bin[-_\s]?flight\b", required)
        and not re.search(
            r"\b(?:condition|wait|wake|notify|active[-_\s]?call "
            r"(?:set|registry)|call registry)\b",
            contract_blob,
        )
    ):
        signatures.extend([
            "register_in_flight_call(module_path: str, call_id: str) -> None",
            "unregister_in_flight_call(module_path: str, call_id: str) -> None",
            "async drain_in_flight_calls(module_path: str, timeout: float | None = None) -> None",
        ])
        invariants.append(
            "An asyncio.Condition wakes drain waiters whenever the active call-ID set changes; "
            "drain returns only when that set is empty and preserves timeout/cancellation."
        )
        data_layout.append(
            "active_calls: dict[str, set[str]] guarded by one asyncio.Condition"
        )
        fixes.append("completed in-flight call registry and async wait/wake contracts")
    if (
        re.search(r"\bqueue\b", required)
        and not re.search(r"\b(?:submit|enqueue|put)\s*\([^)]*\)", signature_blob)
    ):
        signatures.append("submit(job: JobSpec) -> None")
        invariants.append(
            "Every accepted job enters through submit(), receives a stable submission "
            "index, and is consumed exactly once."
        )
    if (
        "cancellation" in required
        and not re.search(r"\bcancel\s*\([^)]*\)", signature_blob)
    ):
        signatures.append("cancel(job_id: str) -> bool")
        invariants.append(
            "Cancellation reports whether a queued or running job was found and preserves "
            "a terminal cancelled result at its submission-order position."
        )
    contracts["signatures"] = list(dict.fromkeys(signatures))
    contracts["shared_invariants"] = list(dict.fromkeys(invariants))
    contracts["data_layout"] = list(dict.fromkeys(data_layout))
    return json.dumps(payload), fixes


def _required_project_edit_protocol_terms(text: str) -> list[str]:
    lowered = str(text or "").lower()
    return [
        term
        for term in (
            "async",
            "atomic",
            "cancellation",
            "checkpoint",
            "crc",
            "dependency",
            "endianness",
            "journal",
            "observer",
            "pause",
            "resume",
            "rollback",
            "sync",
            "transaction",
        )
        if re.search(rf"\b{re.escape(term)}\b", lowered)
    ]


def build_project_edit_integration_contract_stage(
    plan: ProjectEditPlan,
) -> ProjectEditPromptStage:
    """Build the first compact package-contract decision."""

    required_protocol_terms = _required_project_edit_protocol_terms(plan.prompt)
    protocol_instruction = (
        "The contract must explicitly preserve these exact protocol terms: "
        + ", ".join(required_protocol_terms)
        + "."
        if required_protocol_terms
        else "Preserve every prompt-critical protocol term."
    )
    synchronization_instruction = ""
    prompt_lower = plan.prompt.lower()
    if (
        "drain" in prompt_lower
        and re.search(r"\bin[-_\s]?flight\b", prompt_lower)
    ):
        synchronization_instruction = (
            " Because the objective drains in-flight work, define the concrete async wait/wake "
            "mechanism (for example an asyncio.Condition/Event plus the active-call registry), "
            "the register/unregister state transitions, timeout/cancellation behavior, and the "
            "exact drain signature."
        )
    observer_instruction = ""
    if "observer" in prompt_lower:
        observer_instruction = (
            " Define exact observer registration, removal, and event-emission signatures, "
            "including failure isolation."
        )
    return ProjectEditPromptStage(
        key="artifact_integration_contract",
        label="Defining shared package contract",
        system_prompt=(
            "You are a package integration architect. Return only the compact JSON object "
            "required by the schema. Do not propose files or implementation code."
        ),
        user_prompt=f"""Original objective:
{plan.prompt}

Define only the shared contract needed before independent files can be implemented. Name canonical owners by
concept (the file map comes next), exact public signatures with defaults, cross-file invariants, exact data layout
when relevant, and shared error behavior. Preserve every prompt-critical protocol term. Use one concise statement
per distinct contract fact and no more than five canonical owner concepts.
Every operation must receive caller-selected values through its public signature or an explicitly named record
argument. Never hard-code undeclared endpoint names, versions, asset names, paths, job IDs, or other sentinel domain
values inside reusable methods. If one file stores executable records and another consumes a path, specify whether
that path contains the records or the exact public lookup used to retrieve each record.

If the objective requests detecting, finding, listing, or reporting unresolved, missing, invalid, cyclic, or failed
state, define exactly how that state can be represented through the public mutation/input API before it is queried.
Do not pair a query requirement with an input rule that makes the queried state impossible to construct.
Unless explicitly requested otherwise, read/query/report/find/list/format/order methods must not mutate persistent
object state, and repeated calls with unchanged inputs must return equivalent results.
For every stateful multi-step API, define how canonical record metadata reaches each consuming operation: pass the
record/manifest or the exact identity, offset, length, and digest fields. Never infer declared metadata from payload
length, iteration order, or temporary filenames. If atomic publication is requested, define one stable staging path,
complete validation before publication, atomic replacement, and failure cleanup that cannot expose partial output.
If immutable records are requested, require an actually immutable representation such as a frozen dataclass or named
tuple rather than relying on convention.

{protocol_instruction}{synchronization_instruction}{observer_instruction}
""",
        model_tier="local_code",
        num_ctx=6144,
        num_predict=-1,
        timeout=20,
        no_progress_seconds=5,
        prefer_coder=True,
        coder_preference="standard",
        response_format=PROJECT_EDIT_INTEGRATION_CONTRACT_SCHEMA,
    )


def _project_edit_protocol_term_present(term: str, text: str) -> bool:
    """Match protocol concepts across ordinary identifier and inflection variants."""

    normalized = re.sub(r"[_-]+", " ", str(text or "").lower())
    patterns = {
        "async": r"\b(?:async|asynchronous|await|coroutine)\b",
        "atomic": r"\batomic(?:ally|ity)?\b",
        "cancellation": r"\bcancel(?:lation|led|ing)?\b",
        "dependency": r"\bdependenc(?:y|ies)\b|\bdag\b",
        "observer": r"\b(?:observer|listener|subscriber)s?\b",
        "rollback": (
            r"\brollbacks?\b|\broll\s+back\b|"
            r"\b(?:leave|leaves|remain|remains|preserve|preserves|restore|restores)"
            r".{0,50}\b(?:unchanged|original|prior)\b.{0,30}\b(?:failure|error)\b|"
            r"\ball[-\s]?or[-\s]?nothing\b"
        ),
        "transaction": r"\btransactions?\b",
    }
    return bool(re.search(
        patterns.get(term, rf"\b{re.escape(term)}\b"),
        normalized,
    ))


def validate_project_edit_integration_contract_response(
    response: str,
    requirement_ledger: list[dict[str, str]],
) -> list[str]:
    """Validate the shared contract before spending time on file decomposition."""
    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError) as exc:
        return [f"Integration contract JSON did not parse: {exc}"]
    contracts = payload.get("integration_contracts") if isinstance(payload, dict) else None
    if not isinstance(contracts, dict):
        return ["Integration contract omitted integration_contracts."]
    values = [
        str(value)
        for field in (
            "canonical_owners",
            "signatures",
            "shared_invariants",
            "data_layout",
            "errors",
        )
        for value in contracts.get(field) or []
    ]
    blob = " ".join(values).lower()
    errors: list[str] = []
    if not re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\s*\([^)]*\)", blob):
        errors.append("Integration contract lacks an exact callable signature.")
    required_blob = " ".join(
        str(item.get("text") or "")
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    )
    missing = [
        term
        for term in _required_project_edit_protocol_terms(required_blob)
        if not _project_edit_protocol_term_present(term, blob)
    ]
    if missing:
        errors.append(
            "Integration contract omits prompt-critical protocol terms: "
            + ", ".join(missing)
        )
    if (
        re.search(r"\b(binary|byte|frame)\b", required_blob.lower())
        and not list(contracts.get("data_layout") or [])
    ):
        errors.append("Integration contract does not define shared binary/data layout.")
    required_lower = required_blob.lower()
    if (
        "drain" in required_lower
        and re.search(r"\bin[-_\s]?flight\b", required_lower)
        and not re.search(
            r"\b(?:condition|wait|wake|notify|active[-_\s]?call "
            r"(?:set|registry)|call registry)\b",
            blob,
        )
    ):
        errors.append(
            "Integration contract does not define the wait/wake synchronization mechanism "
            "used to drain in-flight calls."
        )
    if (
        "observer" in required_lower
        and not re.search(
            r"\b(?:add|register|remove|emit|notify)_[A-Za-z0-9_]*observer"
            r"\s*\([^)]*\)",
            blob,
        )
    ):
        errors.append(
            "Integration contract does not define an exact observer registration or emission signature."
        )
    graph_behavior = bool(
        re.search(
            r"\b(?:shortest[-_\s]?path|detect[-_\s]?cycles?|directed[-_\s]?edge|"
            r"dependency[-_\s]?graph|topological)\b",
            required_lower,
        )
    )
    executable_graph_payload = bool(
        re.search(
            r"\b(?:apply|execute|callable|function|handler|migration|transform)\b",
            required_lower,
        )
    )
    if graph_behavior and executable_graph_payload:
        graph_contract_lines = [
            str(value).lower()
            for field in ("signatures", "data_layout")
            for value in contracts.get(field) or []
        ]
        endpoint_payload_line = any(
            re.search(
                r"\b(?:from|source|start)(?:_[a-z0-9]+)?\b",
                line,
            )
            and re.search(
                r"\b(?:to|target|end|destination)(?:_[a-z0-9]+)?\b",
                line,
            )
            and re.search(
                r"\b(?:callable|function|handler|payload|operation|transform)\b",
                line,
            )
            for line in graph_contract_lines
        )
        if not endpoint_payload_line:
            errors.append(
                "Executable graph contract must define both directed endpoints and the "
                "executable payload together in a record layout or mutation signature."
            )
    return errors


def build_project_edit_file_map_stage(
    plan: ProjectEditPlan,
    *,
    requirement_ledger: list[dict[str, str]],
    integration_contract_response: str,
) -> ProjectEditPromptStage:
    """Build the second compact file/dependency ownership decision."""

    requirement_lines = "\n".join(
        f"- {item['id']}: {item['text']}"
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    )
    return ProjectEditPromptStage(
        key="artifact_file_map",
        label="Mapping incremental file ownership",
        system_prompt=(
            "You are a package decomposition architect. Return only the compact JSON file map "
            "required by the schema. Do not emit algorithms, contracts, source code, or prose."
        ),
        user_prompt=f"""Original objective:
{plan.prompt}

Accepted shared contract:
{integration_contract_response}

Authoritative artifact requirements:
{requirement_lines}

Map 2-5 focused Python files, including at least one production file and at least one behavioral test file. Reserve
the final map entry for a test. Use terse purposes and project-relative safe paths. Production files precede consumers; tests are last,
live under tech_connector/examples/tests/test_*.py, and depend on every production file they exercise. Assign every
requirement ID to production and behavioral-test ownership. Name only the public symbols each file owns. Shared
types/constants have exactly one production owner. Dependencies may name only another path in this map.
""",
        model_tier="local_code",
        num_ctx=6144,
        num_predict=-1,
        timeout=20,
        no_progress_seconds=5,
        prefer_coder=True,
        coder_preference="standard",
        response_format=PROJECT_EDIT_FILE_MAP_SCHEMA,
    )


def compose_project_edit_incremental_manifest_response(
    integration_contract_response: str,
    file_map_response: str,
    requirement_ledger: list[dict[str, str]],
) -> tuple[str, list[str]]:
    """Combine compact architecture decisions and derive local file work packets."""

    try:
        contracts_payload = json.loads(str(integration_contract_response or ""))
        file_map_payload = json.loads(str(file_map_response or ""))
    except (TypeError, ValueError) as exc:
        return "", [f"Incremental architecture JSON did not parse: {exc}"]
    contracts = contracts_payload.get("integration_contracts")
    files = file_map_payload.get("files")
    if not isinstance(contracts, dict) or not isinstance(files, list):
        return "", ["Incremental architecture omitted its contract object or file map."]
    repairs: list[str] = []
    production_paths = [
        str(item.get("path") or "")
        for item in files
        if isinstance(item, dict)
        and not bool(item.get("is_test"))
        and str(item.get("path") or "")
    ]
    has_test = any(
        isinstance(item, dict) and bool(item.get("is_test"))
        for item in files
    )
    if production_paths and not has_test:
        artifact_ids = [
            str(item.get("id") or "")
            for item in requirement_ledger
            if str(item.get("scope") or "artifact") == "artifact"
            and str(item.get("id") or "")
        ]
        files = [
            *files,
            {
                "path": "tech_connector/examples/tests/test_generated_artifact.py",
                "purpose": "Behavioral proof for every generated artifact requirement.",
                "requirement_ids": artifact_ids,
                "public_symbols": [],
                "depends_on": production_paths,
                "is_test": True,
            },
        ]
        repairs.append(
            "Added the required behavioral-test owner after the bounded model "
            "response ended with production files only."
        )
    requirement_text = {
        str(item.get("id") or ""): str(item.get("text") or "")
        for item in requirement_ledger
    }
    enriched_files = []
    for raw in files:
        item = dict(raw) if isinstance(raw, dict) else {}
        requirement_ids = [
            str(value) for value in item.get("requirement_ids") or []
        ]
        owned_requirements = [
            requirement_text[value]
            for value in requirement_ids
            if value in requirement_text
        ]
        is_test = bool(item.get("is_test"))
        item["contracts"] = [
            "Obey every accepted package integration contract and declared dependency interface.",
            "Own only the public symbols declared in this file map.",
        ]
        item["algorithm_steps"] = [
            (
                "Prove " if is_test else "Implement "
            ) + requirement
            for requirement in owned_requirements[:4]
        ] or ["Implement the file's declared public ownership."]
        item["validation_steps"] = [
            (
                "Run focused disposable behavioral tests for owned requirement IDs."
                if is_test
                else "Import the completed file and read back its declared public interface."
            )
        ]
        enriched_files.append(item)
    return json.dumps({
        "integration_contracts": contracts,
        "files": enriched_files,
        "deterministic_repairs": repairs,
    }), []


def _project_edit_requirement_scope(requirement: str) -> str:
    """Separate generated behavior from controller-owned delivery and safety behavior."""

    normalized = " ".join(str(requirement or "").lower().split())
    if normalized.startswith("plan only"):
        return "workflow"
    if re.search(
        r"\b(?:do not|never)\s+(?:edit|change|create|modify|touch|write|apply)\b.*\blive\b",
        normalized,
    ):
        return "workflow"
    if "disposable workspace" in normalized or "temporary workspace" in normalized:
        return "workflow"
    delivery_nouns = (
        "generated code",
        "planning decision",
        "repair log",
        "test log",
        "per-stage timing",
        "stage timing",
        "requirement coverage matrix",
        "full output",
    )
    if normalized.startswith(("return ", "show ", "display ", "report ", "provide ")):
        if any(noun in normalized for noun in delivery_nouns):
            return "workflow"
    return "artifact"


def project_edit_artifact_architecture_requires_coder(
    requirement_ledger: list[dict[str, str]],
) -> bool:
    """Return whether a manifest needs the coding model on its first pass."""

    artifact_requirements = [
        str(item.get("text") or "")
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    ]
    return (
        len(artifact_requirements) >= 8
        or sum(len(item.split()) for item in artifact_requirements) >= 80
    )


def project_edit_file_worker_profile(attempt: int) -> str:
    """Keep retries on the run's already loaded bounded coder."""

    return "standard"


def project_edit_file_worker_model_override(
    attempt: int,
    settings: dict[str, Any] | None = None,
) -> str:
    """Keep bounded retries on the worker model already selected for this run."""

    return ""


def _split_top_level_requirement_list(value: str) -> list[str]:
    """Split a prose list without breaking callable signatures.

    :param value: Requirement text following a list-introducing clause.
    :return: Top-level comma- and conjunction-delimited list items.
    """

    items: list[str] = []
    start = 0
    depth = 0
    quote = ""
    index = 0
    while index < len(value):
        character = value[index]
        if quote:
            if character == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            index += 1
            continue
        if character in "([{":
            depth += 1
            index += 1
            continue
        if character in ")]}":
            depth = max(0, depth - 1)
            index += 1
            continue
        delimiter_end = 0
        if depth == 0 and character == ",":
            delimiter_end = index + 1
            conjunction = re.match(r"\s*(?:and\s+)?", value[delimiter_end:])
            if conjunction:
                delimiter_end += conjunction.end()
        elif depth == 0 and character.isspace():
            conjunction = re.match(r"\s+and\s+", value[index:])
            if conjunction:
                delimiter_end = index + conjunction.end()
        if delimiter_end:
            item = value[start:index].strip(" ,")
            if item:
                items.append(item)
            start = delimiter_end
            index = delimiter_end
            continue
        index += 1
    final_item = value[start:].strip(" ,")
    if final_item:
        items.append(final_item)
    return items


def extract_project_edit_artifact_requirements(prompt: str) -> list[dict[str, str]]:
    """Extract auditable atomic requirements without replacing the original prompt."""

    text = " ".join(str(prompt or "").split())
    raw_sentences = [
        part.strip(" .")
        for part in re.split(r"(?<=[.!?])\s+|;\s+", text)
        if part.strip(" .")
    ]
    declaration_sentences: list[str] = []
    declaration_start_pattern = re.compile(
        r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b\s+"
        r"(?=(?:define|defines|defining|contain|contains|containing|"
        r"implement|implements|provide|provides|with)\b)",
        flags=re.IGNORECASE,
    )
    for raw_sentence in raw_sentences:
        declaration_starts = list(
            declaration_start_pattern.finditer(raw_sentence)
        )
        if len(declaration_starts) < 2:
            declaration_sentences.append(raw_sentence)
            continue
        prefix = raw_sentence[:declaration_starts[0].start()].strip(" ,:")
        if prefix:
            declaration_sentences.append(prefix)
        for declaration_index, declaration_start in enumerate(
            declaration_starts
        ):
            end = (
                declaration_starts[declaration_index + 1].start()
                if declaration_index + 1 < len(declaration_starts)
                else len(raw_sentence)
            )
            declaration = raw_sentence[declaration_start.start():end]
            declaration = re.sub(
                r"\s+and\s*$",
                "",
                declaration,
                flags=re.IGNORECASE,
            ).strip(" ,:")
            if declaration:
                declaration_sentences.append(declaration)
    raw_sentences = declaration_sentences
    sentences: list[str] = []
    for sentence in raw_sentences:
        additive_parts = [
            part.strip(" ,")
            for part in re.split(
                r",\s*(?:plus|as well as)\s+"
                r"|,\s*and\s+(?=(?:include|add|provide)\s+(?:a\s+)?"
                r"(?:guarded\s+)?__main__\b)"
                r"|\s+and\s+(?=(?:do\s+not|must\s+not|never|without)\b)",
                sentence,
                flags=re.IGNORECASE,
            )
            if part.strip(" ,")
        ]
        if len(additive_parts) <= 1:
            sentences.append(sentence)
            continue
        action_match = re.match(
            r"^(add|build|connect|create|define|implement|include|provide|wire)\b",
            additive_parts[0],
            flags=re.IGNORECASE,
        )
        sentences.append(additive_parts[0])
        for additive_part in additive_parts[1:]:
            if action_match and not re.match(
                r"^(?:add|build|connect|create|define|implement|include|provide|wire"
                r"|do\s+not|must\s+not|never|without)\b",
                additive_part,
                flags=re.IGNORECASE,
            ):
                additive_part = f"{action_match.group(1)} {additive_part}"
            sentences.append(additive_part)
    action_clause_pattern = (
        r"(?:add|allow|apply|build|check|connect|construct|create|define|detect|"
        r"emit|ensure|execute|export|generate|import|include|load|normalize|"
        r"persist|preserve|provide|raise|read|reject|report|return|run|save|set|stop|"
        r"stream|update|validate|verify|wire|write)"
    )
    atomic_sentences: list[str] = []
    for sentence in sentences:
        file_context_match = re.search(
            r"\b(?:in|inside|under|within)\s+"
            r"([A-Za-z_][A-Za-z0-9_./\\-]*\.py)\b",
            sentence,
            flags=re.IGNORECASE,
        )
        action_parts = (
            [sentence]
            if re.match(r"^\s*because\b", sentence, flags=re.IGNORECASE)
            else [
                part.strip(" ,")
                for part in re.split(
                    rf",\s*(?={action_clause_pattern}\b)"
                    rf"|\s+and\s+(?={action_clause_pattern}\b)"
                    r"(?!run\s+(?:buttons?|controls?|widgets?|actions?)\b)",
                    sentence,
                    flags=re.IGNORECASE,
                )
                if part.strip(" ,")
            ]
        )
        merged_parts: list[str] = []
        for part in action_parts or [sentence]:
            if (
                merged_parts
                and re.fullmatch(
                    action_clause_pattern,
                    merged_parts[-1],
                )
            ):
                merged_parts[-1] = f"{merged_parts[-1]} and {part}"
            else:
                merged_parts.append(part)
        sentence_file_contexts = {
            value.casefold()
            for value in re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.py\b",
                sentence,
            )
        }
        if (
            file_context_match
            and len(merged_parts) > 1
            and len(sentence_file_contexts) == 1
        ):
            file_context = file_context_match.group(1)
            merged_parts = [
                merged_parts[0],
                *[
                    (
                        part
                        if re.search(
                            r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.py\b",
                            part,
                        )
                        else f"In {file_context} {part}"
                    )
                    for part in merged_parts[1:]
                ],
            ]
        atomic_sentences.extend(merged_parts)
    sentences = atomic_sentences
    requirements: list[str] = []
    for sentence in sentences:
        proof_match = re.search(
            r"\b(?:tests?|unittest|pytest|coverage)\b.*?\b"
            r"(?:prove|proves|proving|cover|covers|covering|"
            r"verify|verifies|verifying)\s+(.+)$",
            sentence,
            flags=re.IGNORECASE,
        )
        if proof_match:
            proof_file_match = re.search(
                r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.py)\b",
                sentence,
            )
            proof_prefix = (
                f"In {proof_file_match.group(1)} "
                if proof_file_match
                else ""
            )
            proof_items = [
                part.strip(" ,")
                for part in re.split(
                    r",\s*(?:and\s+)?|\s+and\s+",
                    proof_match.group(1),
                )
                if part.strip(" ,")
            ]
            requirements.extend(
                f"{proof_prefix}Test proof: {proof_item}"
                for proof_item in proof_items
            )
        match = re.search(r"\bmust\s+provide\b\s*(.+)", sentence, flags=re.IGNORECASE)
        if match:
            provided_items = _split_top_level_requirement_list(match.group(1))
            if len(provided_items) > 1:
                prefix = sentence[: match.start(1)]
                requirements.extend(prefix + item for item in provided_items)
                continue
        requirements.append(sentence)
    unique: list[str] = []
    seen: set[str] = set()
    for requirement in requirements:
        key = requirement.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(requirement)
    scope_expanded: list[str] = []
    for requirement in unique:
        mixed_scope = re.match(
            r"(?is)^(.*?\b(?:complete|detailed|descriptive)?\s*docstrings?\b)"
            r"\s+and\s+"
            r"((?:a\s+)?(?:runnable|standalone)\b.*"
            r"|.*\b(?:module\s+entry\s+point|if\s+__name__|__main__)\b.*)$",
            requirement,
        )
        if not mixed_scope:
            scope_expanded.append(requirement)
            continue
        left = mixed_scope.group(1).strip(" ,;")
        right = mixed_scope.group(2).strip(" ,;")
        explicit_file = re.search(
            r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.py)\b",
            left,
        )
        scope_expanded.append(left)
        scope_expanded.append(
            f"In {explicit_file.group(1)} include {right}"
            if explicit_file
            else f"include {right}"
        )
    unique = scope_expanded
    ledger: list[dict[str, str]] = []
    active_file_context = ""
    action_prefix = re.compile(
        rf"^\s*(?:In\s+[A-Za-z_][A-Za-z0-9_./\\-]*\.py\s+)?"
        rf"(?:Test proof\s*:|{action_clause_pattern}\b)",
        flags=re.IGNORECASE,
    )
    for index, requirement in enumerate(unique, start=1):
        explicit_files = re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.py)\b",
            requirement,
        )
        explicit_file = explicit_files[0] if len(set(explicit_files)) == 1 else ""
        if explicit_file:
            active_file_context = explicit_file
        elif not action_prefix.search(requirement):
            active_file_context = ""
        inherit_file_context = bool(
            active_file_context
            and not explicit_file
            and action_prefix.search(requirement)
            and not re.match(
                r"^\s*(?:use|do\s+not|must\s+not|never|without)\b",
                requirement,
                flags=re.IGNORECASE,
            )
        )
        requirement_text = (
            f"In {active_file_context} {requirement}"
            if inherit_file_context
            else requirement
        )
        row = {
            "id": f"R{index}",
            "text": requirement_text,
            "source_span": requirement,
            "exact_code_spans": re.findall(
                r"\b[A-Za-z_][A-Za-z0-9_.]*\s*\([^;\n]*?\)"
                r"(?:\s*->\s*[A-Za-z_][A-Za-z0-9_\[\], .|]*)?",
                requirement_text,
            ),
            "scope": _project_edit_requirement_scope(requirement_text),
        }
        ledger.append(row)
    return ledger


def _select_artifact_requirement_owner(
    files: dict[str, dict[str, Any]],
    requirement: str,
) -> dict[str, Any]:
    """Choose the most relevant manifest owner for an unassigned requirement."""

    stop_words = {
        "and", "for", "from", "into", "must", "only", "that", "the", "this",
        "with", "without", "after", "before", "return", "provide",
    }
    requirement_tokens = {
        token for token in re.findall(r"[a-z][a-z0-9_]+", requirement.lower())
        if token not in stop_words
    }
    proof_requirement = bool(
        re.search(
            r"\b(?:test|tests|validate|validation|prove|proof|report|timings?|outputs?|syntax|import)\b",
            requirement,
            flags=re.IGNORECASE,
        )
    )

    def score(item: dict[str, Any]) -> tuple[int, int, str]:
        evidence = " ".join([
            str(item.get("path") or ""),
            str(item.get("purpose") or ""),
            *[str(value) for value in item.get("requirements") or []],
            *[str(value) for value in item.get("public_symbols") or []],
        ]).lower()
        evidence_tokens = set(re.findall(r"[a-z][a-z0-9_]+", evidence))
        overlap = len(requirement_tokens & evidence_tokens)
        type_fit = 1 if bool(item.get("is_test")) == proof_requirement else 0
        return overlap, type_fit, str(item.get("path") or "")

    return max(files.values(), key=score)


def render_project_edit_artifact_architecture(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, str]],
) -> str:
    """Render the exact generated-artifact architecture for user approval."""

    integration_contracts = list(
        (manifest[0].get("integration_contracts") if manifest else []) or []
    )
    lines = ["Artifact architecture:", ""]
    if integration_contracts:
        lines.append("Package integration contracts:")
        lines.extend(f"- {contract}" for contract in integration_contracts)
        lines.append("")
    for item in manifest:
        lines.append(f"- `{item['path']}`: {item['purpose']}")
        lines.append(
            "  - role: " + ("behavioral tests" if item["is_test"] else "production")
        )
        lines.append(
            "  - requirement IDs: " + ", ".join(item.get("requirement_ids") or [])
        )
        if item.get("public_symbols"):
            lines.append("  - public API: " + "; ".join(item["public_symbols"]))
        if item.get("contracts"):
            lines.append("  - contracts: " + "; ".join(item["contracts"]))
        if item.get("algorithm_steps"):
            lines.append("  - algorithm: " + " -> ".join(item["algorithm_steps"]))
        if item.get("depends_on"):
            lines.append("  - dependencies: " + ", ".join(item["depends_on"]))
        if item.get("dependency_repairs"):
            lines.append(
                "  - dependency repairs for review: "
                + "; ".join(item["dependency_repairs"])
            )
        lines.append("  - validation: " + "; ".join(item.get("validation_steps") or []))
        if item.get("ownership_attributions"):
            lines.append(
                "  - inferred ownership for review: "
                + "; ".join(
                    f"{entry['requirement_id']} ({entry['reason']})"
                    for entry in item["ownership_attributions"]
                )
            )

    lines.extend(["", "Requirement ownership matrix:", ""])
    for requirement in requirement_ledger:
        requirement_id = str(requirement.get("id") or "")
        if str(requirement.get("scope") or "artifact") == "workflow":
            lines.append(
                f"- {requirement_id}: {requirement.get('text', '')} -> "
                "project-edit controller (workflow validation)"
            )
            continue
        owners = [
            item["path"]
            for item in manifest
            if requirement_id in item.get("requirement_ids", [])
        ]
        lines.append(
            f"- {requirement_id}: {requirement.get('text', '')} -> "
            + ", ".join(owners)
        )
    return "\n".join(lines)


def build_project_edit_requirement_coverage(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, str]],
    *,
    validation_errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build structured prompt-to-code-and-test attribution for the final result."""

    status = "blocked" if validation_errors else "verified"
    rows: list[dict[str, Any]] = []
    for requirement in requirement_ledger:
        requirement_id = str(requirement.get("id") or "")
        scope = str(requirement.get("scope") or "artifact")
        owners = [
            item
            for item in manifest
            if requirement_id in item.get("requirement_ids", [])
        ]
        workflow_validation = []
        if scope == "workflow":
            workflow_validation = [
                "project-edit controller safety, execution, and result-reporting gates"
            ]
        rows.append({
            "id": requirement_id,
            "requirement": str(requirement.get("text") or ""),
            "scope": scope,
            "system_owners": ["project_edit_flow"] if scope == "workflow" else [],
            "production_owners": [
                item["path"] for item in owners if not item.get("is_test")
            ],
            "test_owners": [
                item["path"] for item in owners if item.get("is_test")
            ],
            "validation": list(dict.fromkeys([
                *workflow_validation,
                *[
                    step
                    for item in owners
                    for step in item.get("validation_steps") or []
                ],
            ])),
            "status": status,
        })
    return rows


def _chunk_manifest_declarations(
    manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return stable declaration candidates for semantic ownership planning."""

    declarations: list[dict[str, Any]] = []
    for file_index, item in enumerate(manifest, start=1):
        path = str(item.get("absolute_path") or item.get("path") or "").strip()
        declarations.append({
            "declaration_id": f"D{file_index}_MODULE",
            "path": path,
            "owner": "<module>",
            "kind": "module",
        })
        for symbol_index, raw_symbol in enumerate(
            item.get("public_symbols") or [],
            start=1,
        ):
            if isinstance(raw_symbol, dict):
                owner = str(
                    raw_symbol.get("qualified_name")
                    or raw_symbol.get("name")
                    or raw_symbol.get("owner")
                    or ""
                ).strip()
                kind = str(raw_symbol.get("kind") or "symbol").strip()
            else:
                owner = str(raw_symbol).split("(", 1)[0].strip()
                kind = "class" if owner.rsplit(".", 1)[-1][:1].isupper() else "function"
            if not owner:
                continue
            owner_name = owner.rsplit(".", 1)[-1]
            if hasattr(builtins, owner_name):
                continue
            declarations.append({
                "declaration_id": f"D{file_index}_{symbol_index}",
                "path": path,
                "owner": owner,
                "kind": kind,
                "existing_declaration": bool(
                    isinstance(raw_symbol, Mapping)
                    and raw_symbol.get("existing_declaration")
                ),
                "inferred_from_request": bool(
                    isinstance(raw_symbol, Mapping)
                    and raw_symbol.get("inferred_from_request")
                ),
            })
    return declarations


def build_user_visible_implementation_plan(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    plan: ProjectEditPlan | None = None,
    grounding_packet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the approval artifact shown before any implementation call."""

    declarations = _chunk_manifest_declarations(manifest)
    declaration_by_id = {
        item["declaration_id"]: item for item in declarations
    }
    requirement_text = {
        str(item.get("id") or item.get("requirement_id") or ""): str(
            item.get("text")
            or item.get("requirement")
            or item.get("description")
            or ""
        )
        for item in requirement_ledger
    }
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        requirement_id = str(assignment.get("requirement_id") or "")
        for declaration_id in assignment.get("declaration_ids") or []:
            declaration = declaration_by_id[str(declaration_id)]
            chunk = chunks_by_id.setdefault(
                str(declaration_id),
                {
                    "chunk_id": str(declaration_id),
                    "path": declaration["path"],
                    "owner": declaration["owner"],
                    "kind": declaration["kind"],
                    "existing_declaration": bool(
                        declaration.get("existing_declaration")
                    ),
                    "requirements": [],
                    "depends_on": [],
                    "resolution": [],
                },
            )
            semantic_role = str(
                assignment.get("semantic_role") or "behavior"
            )
            if is_project_edit_quality_requirement(
                requirement_text.get(requirement_id, "")
            ):
                semantic_role = "quality"
            chunk["requirements"].append({
                "id": requirement_id,
                "text": requirement_text.get(requirement_id, ""),
                "semantic_role": semantic_role,
            })
            for dependency in assignment.get("depends_on") or []:
                if dependency != declaration_id and dependency not in chunk["depends_on"]:
                    chunk["depends_on"].append(str(dependency))
            reason = str(assignment.get("reason") or "semantic reasoning")
            if reason not in chunk["resolution"]:
                chunk["resolution"].append(reason)

    for chunk_id, chunk in chunks_by_id.items():
        same_file_chunks = [
            (other_id, other)
            for other_id, other in chunks_by_id.items()
            if other_id != chunk_id and other["path"] == chunk["path"]
        ]
        if chunk["owner"] == "<module>":
            for dependency_id, dependency in same_file_chunks:
                if dependency["owner"] != "<module>" and dependency_id not in chunk["depends_on"]:
                    chunk["depends_on"].append(dependency_id)
        if any(
            requirement.get("semantic_role") == "verification"
            for requirement in chunk["requirements"]
        ):
            for dependency_id, dependency in same_file_chunks:
                if dependency["kind"] == "class" and dependency_id not in chunk["depends_on"]:
                    chunk["depends_on"].append(dependency_id)

    unique_symbol_chunks: dict[str, str] = {}
    duplicate_symbol_names: set[str] = set()
    for chunk_id, chunk in chunks_by_id.items():
        if chunk["owner"] == "<module>":
            continue
        symbol = str(chunk["owner"]).split("(", 1)[0].rsplit(".", 1)[-1]
        if symbol in unique_symbol_chunks:
            duplicate_symbol_names.add(symbol)
        else:
            unique_symbol_chunks[symbol] = chunk_id
    for symbol in duplicate_symbol_names:
        unique_symbol_chunks.pop(symbol, None)
    for chunk_id, chunk in chunks_by_id.items():
        owned_text = "\n".join(
            str(item.get("text") or "") for item in chunk["requirements"]
        )
        owned_requirement_ids = {
            str(item.get("id") or "") for item in chunk["requirements"]
        }
        for symbol, dependency_id in unique_symbol_chunks.items():
            if dependency_id == chunk_id:
                continue
            dependency_requirement_ids = {
                str(item.get("id") or "")
                for item in chunks_by_id[dependency_id]["requirements"]
            }
            shared_requirement_ids = (
                owned_requirement_ids & dependency_requirement_ids
            )
            if shared_requirement_ids:
                current_symbol = str(chunk["owner"]).split("(", 1)[0].rsplit(".", 1)[-1]
                dependency_precedes = False
                shared_mentions_both = False
                for requirement in chunk["requirements"]:
                    if str(requirement.get("id") or "") not in shared_requirement_ids:
                        continue
                    requirement_text = str(requirement.get("text") or "")
                    current_match = re.search(
                        rf"\b{re.escape(current_symbol)}\b",
                        requirement_text,
                    )
                    dependency_match = re.search(
                        rf"\b{re.escape(symbol)}\b",
                        requirement_text,
                    )
                    if (
                        current_match
                        and dependency_match
                    ):
                        shared_mentions_both = True
                        if dependency_match.start() < current_match.start():
                            dependency_precedes = True
                            break
                if dependency_precedes and dependency_id not in chunk["depends_on"]:
                    chunk["depends_on"].append(dependency_id)
                if shared_mentions_both:
                    continue
            positive_symbol_reference = any(
                re.search(
                    rf"\b{re.escape(symbol)}\b",
                    str(requirement.get("text") or ""),
                )
                and not re.search(
                    r"\b(?:do\s+not|must\s+not|never)\s+"
                    r"(?:define|duplicate|implement|redeclare|reimplement)\b",
                    str(requirement.get("text") or ""),
                    flags=re.IGNORECASE,
                )
                for requirement in chunk["requirements"]
            )
            if positive_symbol_reference:
                if dependency_id not in chunk["depends_on"]:
                    chunk["depends_on"].append(dependency_id)

    absolute_path_by_manifest_path = {
        str(item.get("path") or ""): str(
            item.get("absolute_path") or item.get("path") or ""
        )
        for item in manifest
    }
    manifest_dependencies = {
        str(item.get("absolute_path") or item.get("path") or ""): {
            absolute_path_by_manifest_path.get(str(value), str(value))
            for value in item.get("depends_on") or []
        }
        for item in manifest
    }
    chunks_by_path: dict[str, list[str]] = {}
    for chunk_id, chunk in chunks_by_id.items():
        chunks_by_path.setdefault(str(chunk["path"]), []).append(chunk_id)
    for chunk_id, chunk in chunks_by_id.items():
        for dependency_path in manifest_dependencies.get(
            str(chunk["path"]), set()
        ):
            for dependency_id in chunks_by_path.get(dependency_path, []):
                dependency = chunks_by_id[dependency_id]
                if (
                    dependency_id != chunk_id
                    and dependency["owner"] != "<module>"
                    and dependency_id not in chunk["depends_on"]
                ):
                    chunk["depends_on"].append(dependency_id)

    for chunk in chunks_by_id.values():
        chunk["depends_on"] = [
            dependency_id
            for dependency_id in dict.fromkeys(chunk["depends_on"])
            if dependency_id in chunks_by_id
        ]

    packet = dict((plan.intelligence_packet if plan else {}) or {})
    raw_evidence: list[dict[str, Any]] = [
        item
        for item in packet.get("symbols") or []
        if isinstance(item, dict)
    ]
    usages = packet.get("usages") or {}
    if isinstance(usages, dict):
        for key in (
            "exact_symbols",
            "exact_calls",
            "exact_chunks",
            "related_symbols",
        ):
            raw_evidence.extend(
                item
                for item in usages.get(key) or []
                if isinstance(item, dict)
            )
    grounding_packet = dict(grounding_packet or {})
    raw_evidence.extend(
        dict(item)
        for item in grounding_packet.get("evidence") or []
        if isinstance(item, Mapping)
    )
    for chunk in chunks_by_id.values():
        evidence_query = " ".join([
            str(chunk["owner"]),
            *[
                str(item.get("text") or "")
                for item in chunk["requirements"]
            ],
        ]).casefold()
        query_identifiers = [
            token.casefold()
            for token in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]{3,}",
                evidence_query,
            )
            if token.casefold() not in {
                "behavior",
                "class",
                "create",
                "implementation",
                "method",
                "module",
                "requirement",
                "verified",
            }
        ]
        ranked: list[tuple[int, dict[str, Any]]] = []
        seen_evidence: set[tuple[str, str]] = set()
        for row in raw_evidence:
            name = str(
                row.get("qualified_name")
                or row.get("qualname")
                or row.get("name")
                or row.get("call")
                or ""
            ).strip()
            path = str(row.get("path") or row.get("file") or "").strip()
            if not name:
                continue
            tokens = [
                token.casefold()
                for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", name)
                if len(token) > 2
            ]
            name_score = sum(
                1 for token in tokens if token in evidence_query
            )
            source_text = str(
                row.get("source_excerpt")
                or row.get("source")
                or ""
            ).casefold()
            source_score = min(
                3,
                sum(
                    1
                    for token in query_identifiers
                    if token in source_text
                ),
            )
            score = name_score * 3 + source_score
            if score <= 0:
                continue
            key = (path.casefold(), name.casefold())
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            source_scope = str(
                row.get("source_scope")
                or row.get("provider")
                or "project"
            )
            signature = str(row.get("signature") or "").strip()
            if bool(row.get("authoritative_signature")) and signature:
                strength = "authoritative_api_signature"
            elif source_scope in {
                "unreal_engine",
                "maya",
                "blender",
                "motionbuilder",
                "installed_package",
            }:
                strength = (
                    "authoritative_api_signature"
                    if signature
                    else "api_index_entry"
                )
            elif name_score and signature and str(row.get("kind") or ""):
                strength = "internal_definition"
            else:
                strength = "indexed_usage_example"
            ranked.append((
                score,
                {
                    "name": name,
                    "kind": str(row.get("kind") or ""),
                    "signature": signature,
                    "path": path,
                    "source_scope": source_scope,
                    "strength": strength,
                },
            ))
        chunk["evidence"] = [
            evidence
            for _score, evidence in sorted(
                ranked,
                key=lambda item: (
                    -item[0],
                    item[1]["name"],
                    item[1]["path"],
                ),
            )[:6]
        ]

    pending = set(chunks_by_id)
    ordered_ids: list[str] = []
    while pending:
        ready = sorted(
            chunk_id
            for chunk_id in pending
            if not (set(chunks_by_id[chunk_id]["depends_on"]) & pending)
        )
        if not ready:
            ready = [sorted(pending)[0]]
        ordered_ids.extend(ready)
        pending.difference_update(ready)

    files: list[dict[str, Any]] = []
    for item in manifest:
        path = str(item.get("absolute_path") or item.get("path") or "")
        files.append({
            "path": path,
            "purpose": str(item.get("purpose") or ""),
            "depends_on": list(item.get("depends_on") or []),
            "validation_steps": list(item.get("validation_steps") or []),
            "chunks": [
                chunk_id
                for chunk_id in ordered_ids
                if chunks_by_id[chunk_id]["path"] == path
            ],
        })
    return {
        "plan_version": "semantic-owner-plan-v1",
        "grounding_snapshot_id": str(
            grounding_packet.get("snapshot_id") or ""
        ),
        "capability_intents": list(
            grounding_packet.get("capability_intents") or []
        ),
        "files": files,
        "chunks": [chunks_by_id[chunk_id] for chunk_id in ordered_ids],
        "requirement_coverage": [
            {
                "requirement_id": str(
                    item.get("id") or item.get("requirement_id") or ""
                ),
                "owners": [
                    declaration_id
                    for assignment in assignments
                    if str(assignment.get("requirement_id") or "")
                    == str(item.get("id") or item.get("requirement_id") or "")
                    for declaration_id in assignment.get("declaration_ids") or []
                ],
            }
            for item in requirement_ledger
        ],
        "approval_instructions": (
            "Approve this exact plan or correct its files, owners, requirements, "
            "dependencies, or validation expectations before generation."
        ),
        "quality_gate": (
            "After approval and assembly, run the established ordered quality passes "
            "and final whole-request review. No implementation is complete while any "
            "pass has a remaining failure."
        ),
    }


def build_project_edit_chunk_plan_stage(
    plan: ProjectEditPlan,
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
    grounding_packet: Mapping[str, Any] | None = None,
) -> ProjectEditPromptStage:
    """Build one bounded semantic mapping from requirements to real owners."""

    declarations = _chunk_manifest_declarations(manifest)
    requirements = [
        {
            "requirement_id": str(item.get("id") or item.get("requirement_id") or ""),
            "text": str(
                item.get("text")
                or item.get("requirement")
                or item.get("description")
                or ""
            ),
        }
        for item in requirement_ledger
    ]
    grounding_packet = dict(grounding_packet or {})
    grounded_capabilities = [
        {
            "name": str(item.get("qualified_name") or ""),
            "signature": str(item.get("signature") or ""),
            "provider": str(item.get("provider") or ""),
            "authoritative": bool(item.get("authoritative_signature")),
            "supports": list(item.get("supports") or []),
        }
        for item in grounding_packet.get("evidence") or []
        if isinstance(item, Mapping)
        and str(item.get("qualified_name") or "")
    ][:48]
    payload = {
        "objective": plan.prompt,
        "requirements": requirements,
        "candidate_declarations": declarations,
        "capability_intents": list(
            grounding_packet.get("capability_intents") or []
        ),
        "grounded_capabilities": grounded_capabilities,
        "instructions": {
            "task": (
                "Classify each requirement semantically, then assign it to every supplied "
                "declaration that must implement or assemble that behavior."
            ),
            "symbol_mentions": (
                "A mentioned symbol may be a target, dependency, base class, API reference, "
                "return type, example, or part of a broader request. Do not treat mention as ownership."
            ),
            "ownership": (
                "Use only supplied declaration_id values. Assign module behavior such as imports, "
                "constants, and entry points to that file's MODULE declaration."
            ),
            "coverage": "Every requirement_id must appear exactly once as an assignment row.",
            "dependencies": (
                "depends_on contains declaration_id values that must be generated first."
            ),
            "grounding": (
                "Use grounded capabilities to distinguish implementation dependencies "
                "from declaration ownership. An API mention is not an owner. Never "
                "invent an owner or callable absent from candidate declarations and "
                "grounded capabilities."
            ),
        },
        "output_schema": {
            "assignments": [
                {
                    "requirement_id": (
                        requirements[0]["requirement_id"]
                        if requirements
                        else ""
                    ),
                    "semantic_role": "behavior",
                    "declaration_ids": [
                        declarations[0]["declaration_id"]
                    ] if declarations else [],
                    "depends_on": [],
                }
            ]
        },
    }
    return ProjectEditPromptStage(
        key="artifact_chunk_plan",
        label="Assigning requirements to implementation chunks",
        system_prompt=(
            "You are a bounded semantic code planner. Return JSON only. Resolve ownership "
            "from meaning and supplied evidence; never invent a file, symbol, or API."
        ),
        user_prompt=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        model_tier="local_reasoning",
        num_ctx=4096,
        num_predict=max(180, min(600, len(requirements) * 120)),
        timeout=45,
        no_progress_seconds=20,
        prefer_coder=False,
        coder_preference="fast",
        response_format="json",
        metadata={
            "requirements": requirements,
            "declarations": declarations,
            "grounding_snapshot_id": str(
                grounding_packet.get("snapshot_id") or ""
            ),
        },
    )


def parse_project_edit_chunk_plan(
    response: str,
    *,
    stage: ProjectEditPromptStage,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate complete requirement coverage and evidence-bounded ownership."""

    try:
        payload = json.loads(str(response or "").strip())
    except (TypeError, ValueError) as exc:
        return [], [f"Chunk plan is not valid JSON: {exc}"]
    assignments = payload.get("assignments") if isinstance(payload, dict) else None
    if not isinstance(assignments, list):
        return [], ["Chunk plan must contain an assignments list."]

    requirement_rows = list((stage.metadata or {}).get("requirements") or [])
    declaration_rows = list((stage.metadata or {}).get("declarations") or [])
    required_ids = {
        str(item.get("requirement_id") or "")
        for item in requirement_rows
        if str(item.get("requirement_id") or "")
    }
    declaration_ids = {
        str(item.get("declaration_id") or "")
        for item in declaration_rows
        if str(item.get("declaration_id") or "")
    }
    declaration_by_id = {
        str(item.get("declaration_id") or ""): item
        for item in declaration_rows
        if str(item.get("declaration_id") or "")
    }
    requirement_text_by_id = {
        str(item.get("requirement_id") or ""): str(item.get("text") or "")
        for item in requirement_rows
        if str(item.get("requirement_id") or "")
    }
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in assignments:
        if not isinstance(row, dict):
            errors.append("Every chunk assignment must be an object.")
            continue
        requirement_id = str(row.get("requirement_id") or "").strip()
        if requirement_id not in required_ids:
            errors.append(f"Unknown requirement_id in chunk plan: {requirement_id!r}.")
            continue
        if requirement_id in seen:
            errors.append(f"Requirement {requirement_id} was assigned more than once.")
            continue
        raw_owners = row.get("declaration_ids") or []
        if isinstance(raw_owners, str):
            raw_owners = [raw_owners]
        owners = [str(item) for item in raw_owners if str(item)]
        unknown_owners = [item for item in owners if item not in declaration_ids]
        if unknown_owners:
            errors.append(
                f"Requirement {requirement_id} invented declaration IDs: "
                + ", ".join(unknown_owners)
            )
            continue
        module_behavior_requested = bool(re.search(
            r"\b(?:__main__|entry\s*point|module[- ]level|registration|"
            r"register|constant|global|initiali[sz]ation|configure\s+the\s+module)\b",
            requirement_text_by_id.get(requirement_id, ""),
            flags=re.IGNORECASE,
        ))
        non_module_owner_paths = {
            str(declaration_by_id[owner].get("path") or "")
            for owner in owners
            if str(declaration_by_id[owner].get("kind") or "") != "module"
        }
        if non_module_owner_paths and not module_behavior_requested:
            owners = [
                owner
                for owner in owners
                if not (
                    str(declaration_by_id[owner].get("kind") or "") == "module"
                    and str(declaration_by_id[owner].get("path") or "")
                    in non_module_owner_paths
                )
            ]
        if (
            not module_behavior_requested
            and owners
            and all(
                str(declaration_by_id[owner].get("kind") or "") == "module"
                for owner in owners
            )
        ):
            module_paths = {
                str(declaration_by_id[owner].get("path") or "")
                for owner in owners
            }
            same_file_symbol_owners = [
                declaration_id
                for declaration_id, declaration in declaration_by_id.items()
                if (
                    str(declaration.get("kind") or "") != "module"
                    and str(declaration.get("path") or "") in module_paths
                )
            ]
            if len(same_file_symbol_owners) == 1:
                owners = same_file_symbol_owners
        if not owners:
            errors.append(f"Requirement {requirement_id} has no implementation owner.")
            continue
        raw_dependencies = row.get("depends_on") or []
        if isinstance(raw_dependencies, str):
            raw_dependencies = [raw_dependencies]
        dependencies = [str(item) for item in raw_dependencies if str(item)]
        unknown_dependencies = [
            item for item in dependencies if item not in declaration_ids
        ]
        if unknown_dependencies:
            errors.append(
                f"Requirement {requirement_id} invented dependency IDs: "
                + ", ".join(unknown_dependencies)
            )
            continue
        seen.add(requirement_id)
        normalized.append({
            "requirement_id": requirement_id,
            "semantic_role": str(row.get("semantic_role") or "behavior"),
            "declaration_ids": owners,
            "depends_on": dependencies,
            "reason": str(row.get("reason") or ""),
        })
    missing = sorted(required_ids - seen)
    if missing:
        errors.append("Chunk plan omitted requirement IDs: " + ", ".join(missing))
    return normalized, errors


def build_project_edit_artifact_chunk_stages(
    plan: ProjectEditPlan,
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    implementation_plan: Mapping[str, Any] | None = None,
) -> list[tuple[str, str, ProjectEditPromptStage]]:
    """Build dependency-ordered symbol generation stages from semantic ownership."""

    declarations = _chunk_manifest_declarations(manifest)
    declaration_by_id = {
        item["declaration_id"]: item for item in declarations
    }
    requirement_by_id = {
        str(item.get("id") or item.get("requirement_id") or ""): str(
            item.get("text")
            or item.get("requirement")
            or item.get("description")
            or ""
        )
        for item in requirement_ledger
    }
    owned_requirements: dict[str, list[dict[str, str]]] = {}
    dependencies: dict[str, set[str]] = {}
    for assignment in assignments:
        requirement_id = str(assignment["requirement_id"])
        for declaration_id in assignment["declaration_ids"]:
            owned_requirements.setdefault(declaration_id, []).append({
                "id": requirement_id,
                "text": requirement_by_id.get(requirement_id, ""),
                "semantic_role": str(assignment.get("semantic_role") or "behavior"),
                "reason": str(assignment.get("reason") or ""),
            })
            dependencies.setdefault(declaration_id, set()).update(
                str(item)
                for item in assignment.get("depends_on") or []
                if str(item) != declaration_id
            )

    approved_chunks = {
        str(item.get("chunk_id") or ""): item
        for item in (implementation_plan or {}).get("chunks") or []
        if isinstance(item, Mapping)
    }
    declaration_ids_by_path: dict[str, list[str]] = {}
    for declaration_id, declaration in declaration_by_id.items():
        normalized_path = str(declaration.get("path") or "").replace(
            "\\", "/"
        ).casefold()
        declaration_ids_by_path.setdefault(normalized_path, []).append(
            declaration_id
        )
    file_dependencies_by_path = {
        str(item.get("path") or "").replace("\\", "/").casefold(): [
            str(value) for value in item.get("depends_on") or [] if str(value)
        ]
        for item in (implementation_plan or {}).get("files") or []
        if isinstance(item, Mapping)
    }

    def dependency_declaration_ids(value: str) -> set[str]:
        if value in declaration_by_id:
            return {value}
        normalized = str(value or "").replace("\\", "/").casefold()
        return {
            declaration_id
            for path, declaration_ids in declaration_ids_by_path.items()
            if path == normalized
            or path.endswith("/" + normalized.lstrip("./"))
            for declaration_id in declaration_ids
        }

    for declaration_id, declaration in declaration_by_id.items():
        approved_chunk = approved_chunks.get(declaration_id, {})
        dependency_values = [
            *[
                str(item)
                for item in approved_chunk.get("depends_on") or []
                if str(item)
            ],
            *file_dependencies_by_path.get(
                str(declaration.get("path") or "")
                .replace("\\", "/")
                .casefold(),
                [],
            ),
        ]
        for dependency_value in dependency_values:
            dependencies.setdefault(declaration_id, set()).update(
                dependency_declaration_ids(dependency_value)
                - {declaration_id}
            )

    pending = {
        declaration_id
        for declaration_id in owned_requirements
        if bool(
            approved_chunks.get(declaration_id, {}).get(
                "generation_required",
                True,
            )
        )
    }
    ordered_ids: list[str] = []
    while pending:
        ready = sorted(
            item
            for item in pending
            if not (dependencies.get(item, set()) & pending)
        )
        if not ready:
            ready = [sorted(pending)[0]]
        ordered_ids.extend(ready)
        pending.difference_update(ready)

    stages: list[tuple[str, str, ProjectEditPromptStage]] = []
    for capsule_index, declaration_id in enumerate(ordered_ids, start=1):
        path = declaration_by_id[declaration_id]["path"]
        existing_source_read_error = ""
        try:
            existing_source = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            existing_source = ""
            if Path(path).exists():
                existing_source_read_error = str(exc)
        file_chunk_ids = [declaration_id]
        file_chunk_set = set(file_chunk_ids)
        file_dependencies = sorted({
            dependency_id
            for declaration_id in file_chunk_ids
            for dependency_id in dependencies.get(declaration_id, set())
            if dependency_id not in file_chunk_set
        })
        contracts = [
            approved_chunks.get(declaration_id, {})
            for declaration_id in file_chunk_ids
        ]
        declarations_for_file = [
            declaration_by_id[declaration_id]
            for declaration_id in file_chunk_ids
        ]
        expected_public_symbols = [
            declaration["owner"]
            for declaration in declarations_for_file
            if declaration["owner"] != "<module>"
        ]
        all_file_owners = [
            declaration["owner"]
            for declaration in declarations
            if declaration["path"] == path
            and declaration["owner"] != "<module>"
        ]
        all_file_owners.extend(
            str(helper.get("owner") or "")
            for declaration in declarations
            if declaration["path"] == path
            for helper in (
                (
                    approved_chunks.get(
                        declaration["declaration_id"], {}
                    ).get("declaration_contract")
                    or {}
                ).get("helper_declarations")
                or []
            )
            if isinstance(helper, Mapping)
            and str(helper.get("owner") or "")
        )
        all_file_owners = list(dict.fromkeys(all_file_owners))
        requirement_ids = list(dict.fromkeys(
            item["id"]
            for declaration_id in file_chunk_ids
            for item in owned_requirements[declaration_id]
        ))
        file_owned_requirements = list({
            str(item["id"]): dict(item)
            for declaration_id in file_chunk_ids
            for item in owned_requirements[declaration_id]
        }.values())
        canonical_contract_hash = hashlib.sha256(
            json.dumps(
                contracts,
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        owner_declaration = declarations_for_file[0]
        owner_contract = contracts[0] if contracts else {}
        declaration_contract = (
            owner_contract.get("declaration_contract")
            if isinstance(owner_contract, Mapping)
            else {}
        ) or {}
        exact_dependency_signatures = [
            {
                "name": str(item.get("name") or ""),
                "signature": str(item.get("signature") or ""),
                "requirement_ids": list(item.get("requirement_ids") or []),
                "provider": str(item.get("provider") or ""),
                "usage_role": str(item.get("usage_role") or "invoke"),
                "access_kind": str(item.get("access_kind") or ""),
                "import_statement": str(item.get("import_statement") or ""),
                "source_excerpt": str(
                    item.get("source_excerpt") or item.get("source") or ""
                )[:1200],
                "return_schema": item.get("return_schema")
                or item.get("schema")
                or {},
            }
            for item in owner_contract.get("evidence") or []
            if isinstance(item, Mapping)
            and (
                bool(item.get("selected_for_generation"))
                or bool(item.get("dependency_for_selected"))
            )
        ]
        payload = {
            "mode": "generate_approved_owner_capsule",
            "target_path": path,
            "owner": {
                "declaration_id": declaration_id,
                "qualified_name": str(
                    owner_declaration.get("owner") or "<module>"
                ),
                "kind": str(owner_declaration.get("kind") or ""),
                "base": str(owner_declaration.get("base") or ""),
            },
            "owned_requirements": file_owned_requirements,
            "declaration_contract": declaration_contract,
            "implementation_mechanics": list(
                owner_contract.get("implementation_mechanics") or []
            ),
            "method_tasks": list(owner_contract.get("method_tasks") or []),
            "observable_contracts": list(
                owner_contract.get("observable_contracts") or []
            ),
            "exact_dependency_signatures": exact_dependency_signatures,
            "integration_boundary": {
                "depends_on": file_dependencies,
                "required_interfaces": list(
                    owner_contract.get("required_dependency_interfaces") or []
                ),
                "proposed_interfaces": list(
                    owner_contract.get("proposed_interfaces") or []
                ),
            },
            "canonical_contract_sha256": canonical_contract_hash,
            "output": {
                "format": (
                    "one complete raw Python declaration plus only its required "
                    "imports; module owners may emit module wiring"
                ),
                "exact_owner_only": True,
                "approved_contracts_are_authoritative": True,
                "placeholders_forbidden": True,
                "unrelated_declarations_forbidden": True,
            },
        }
        assertion_lines: list[str] = [
            "Every owned_requirements entry above is mandatory executable behavior.",
            "Return syntactically valid production code with complete public type "
            "annotations and substantive public docstrings. Use concrete public "
            "types inferred from the request, verified dependencies, and return "
            "shape; `Any` does not satisfy a concretely inferable public contract.",
            "Keep the module docstring as the first statement, before imports. For "
            "requested reStructuredText docstrings, place a blank line after the "
            "summary, indent one `:param name:` field per parameter and one "
            "`:return:` field inside the docstring, and describe the domain value; "
            "generic text such as `result`, `value`, or `Gets item` is incomplete.",
            "Emit no placeholder body, invented dependency, invented public symbol, "
            "unverified API call, unreachable requested behavior, or introduced "
            "dead code.",
            "Accept no public constructor parameter unless it is request-owned, "
            "data-flow-owned, or required by a verified base signature.",
            "Keep one canonical implementation per behavior. Do not add an "
            "unreferenced private helper or duplicate working logic under another "
            "method name.",
            "For ordered output use a complete deterministic key with a semantic "
            "tie-breaker; for named exclusions compare canonical units exactly.",
            "For iterative progress derive totals from real work. Threaded UI "
            "owners must prevent overlapping starts and connect finished cleanup.",
            "For a background operation, instantiate the approved dependency owner "
            "and pass its exact bound callable to the worker. Never substitute a "
            "lambda, demonstration payload, or locally invented operation.",
            "Dependency callable signatures are invocation evidence only. Never "
            "redeclare or copy a dependency method onto the generated owner unless "
            "that method is explicitly present in the owner's declaration contract.",
            "Use one self-consistent handler per signal role. Every private self-call "
            "must resolve to a method declared in the same class, every handler must "
            "be reachable from construction or a constructor-connected signal, and "
            "the worker's result, error, progress, and finished paths must connect "
            "before start(). Keep the initiating control disabled or guard the "
            "retained worker until finished cleanup releases it.",
        ]
        dependency_assertions: list[str] = []
        for dependency_id in file_dependencies:
            dependency_declaration = declaration_by_id.get(dependency_id, {})
            dependency_owner = str(
                dependency_declaration.get("owner") or ""
            )
            if not dependency_owner or dependency_owner == "<module>":
                continue
            dependency_contract = approved_chunks.get(dependency_id, {}).get(
                "declaration_contract"
            ) or {}
            dependency_signatures = [
                str(value)
                for value in dependency_contract.get(
                    "callable_signatures"
                ) or []
                if str(value)
            ]
            dependency_assertions.append(
                f"{owner_declaration.get('owner')}: import and consume validated "
                f"dependency owner {dependency_owner}"
                + (
                    " through " + "; ".join(dependency_signatures)
                    if dependency_signatures
                    else ""
                )
                + "; do not copy its implementation or replace it with lower-level "
                "dependencies."
            )
        assertion_lines.extend(dependency_assertions)
        for contract in contracts:
            owner = str(contract.get("owner") or "<module>")
            declaration_contract = contract.get("declaration_contract") or {}
            dependency_policy = (
                declaration_contract.get("dependency_policy")
                if isinstance(
                    declaration_contract.get("dependency_policy"), Mapping
                )
                else {}
            )
            forbidden_imports = [
                str(module)
                for module in dependency_policy.get("forbidden_imports") or []
                if str(module).strip()
            ]
            if forbidden_imports:
                assertion_lines.append(
                    f"{owner}: the explicit request forbids importing "
                    + ", ".join(forbidden_imports)
                    + "; this overrides every general host-import allowance. "
                    "Use only the approved dependency owner or transport."
                )
            selected_dependency_names = {
                str(item.get("name") or "").casefold()
                for item in exact_dependency_signatures
            }
            required_owners = [
                str(owner_name)
                for owner_name in dependency_policy.get("required_owners") or []
                if str(owner_name).strip()
                and any(
                    str(owner_name).casefold() in dependency_name
                    or str(owner_name).casefold().rsplit(".", 1)[-1]
                    in dependency_name.rsplit(".", 1)[0].split(".")
                    for dependency_name in selected_dependency_names
                )
            ]
            if required_owners:
                assertion_lines.append(
                    f"{owner}: invoke external operations only through selected "
                    "callables owned by "
                    + ", ".join(required_owners)
                    + "."
                )
            assertion_lines.extend(
                f"{owner}: governing dependency constraint: {clause}"
                for clause in dependency_policy.get("constraints") or []
                if str(clause).strip()
            )
            execution_constraints = (
                declaration_contract.get("execution_constraints")
                if isinstance(
                    declaration_contract.get("execution_constraints"), Mapping
                )
                else {}
            )
            if execution_constraints.get("requires_off_ui_thread"):
                assertion_lines.append(
                    f"{owner}: dispatch blocking work outside the UI thread; the "
                    "signal handler must return immediately and must not sleep, "
                    "pump events, wait, join, poll, or run a blocking loop."
                )
            if execution_constraints.get("requires_completion_path"):
                assertion_lines.append(
                    f"{owner}: provide an event-loop-safe completion path from the "
                    "background operation back to the owner."
                )
            if execution_constraints.get("requires_error_path"):
                assertion_lines.append(
                    f"{owner}: provide an event-loop-safe error path from the "
                    "background operation back to the owner."
                )
            required_calls = [
                item
                for item in declaration_contract.get("required_calls") or []
                if isinstance(item, Mapping)
                and str(item.get("name") or "")
                and str(item.get("usage_role") or "invoke") == "invoke"
            ]
            assertion_lines.extend(
                f"{owner}: call verified capability `{item.get('name')}` "
                f"with signature `{item.get('signature')}` for requirement IDs "
                + ", ".join(str(value) for value in item.get("requirement_ids") or [])
                + "."
                for item in required_calls
            )
            assertion_lines.extend(
                f"{owner}: read verified property {item.get('name')} without "
                "calling it for requirement IDs "
                + ", ".join(
                    str(value)
                    for value in item.get("requirement_ids") or []
                )
                + "."
                for item in (
                    declaration_contract.get("required_accesses") or []
                )
                if isinstance(item, Mapping)
                and str(item.get("name") or "")
            )
            verified_imports: list[str] = []
            for dependency_item in [
                *required_calls,
                *[
                    item
                    for item in (
                        declaration_contract.get("required_accesses") or []
                    )
                    if isinstance(item, Mapping)
                ],
            ]:
                qualified_name = str(dependency_item.get("name") or "")
                explicit_import = str(
                    dependency_item.get("import_statement") or ""
                ).strip()
                if explicit_import:
                    verified_imports.append(explicit_import)
                    continue
                signature = str(dependency_item.get("signature") or "")
                if not re.search(
                    r"\(\s*(?:self|cls)\b",
                    signature,
                    flags=re.IGNORECASE,
                ):
                    module_path, separator, binding_name = (
                        qualified_name.rpartition(".")
                    )
                    if (
                        separator
                        and module_path
                        and re.fullmatch(
                            r"[A-Za-z_][A-Za-z0-9_]*",
                            binding_name,
                        )
                    ):
                        verified_imports.append(
                            f"from {module_path} import {binding_name}"
                        )
                        continue
                owner_path = qualified_name.rsplit(".", 1)[0]
                module_path, separator, binding_name = owner_path.rpartition(".")
                if (
                    separator
                    and module_path
                    and binding_name
                    and binding_name[:1].isupper()
                ):
                    verified_imports.append(
                        f"from {module_path} import {binding_name}"
                    )
            assertion_lines.extend(
                "Import the verified dependency exactly with "
                f"`{import_statement}` and invoke it through its imported binding; "
                "never emit an unimported fully-qualified root."
                for import_statement in dict.fromkeys(verified_imports)
            )
            instance_owners = list(dict.fromkeys(
                str(item.get("name") or "").rsplit(".", 1)[0]
                for item in required_calls
                if re.search(
                    r"\(\s*\$?self\b",
                    str(item.get("signature") or ""),
                    flags=re.IGNORECASE,
                )
            ))
            assertion_lines.extend(
                f"{owner}: construct an instance of {dependency_owner} before "
                "calling its verified instance methods; never invoke a `self` "
                "method on the class object."
                for dependency_owner in instance_owners
            )
            for helper in declaration_contract.get("helper_declarations") or []:
                if not isinstance(helper, Mapping):
                    continue
                assertion_lines.append(
                    f"{owner}: declare helper {helper.get('owner')} in this same "
                    "target file; do not import it from another module. Declare it as "
                    f"{helper.get('kind')} inheriting {helper.get('base')}; "
                    "implement exact callables "
                    + "; ".join(
                        str(value)
                        for value in helper.get("callable_signatures") or []
                    )
                    + f". Responsibility: {helper.get('responsibility')}."
                )
                helper_signals = [
                    signal
                    for signal in helper.get("signals") or []
                    if isinstance(signal, Mapping)
                ]
                if helper_signals:
                    assertion_lines.append(
                        f"{owner}: helper {helper.get('owner')} must declare, emit, "
                        "and expose these Qt signals for connection before dispatch: "
                        + ", ".join(
                            str(signal.get("name") or "")
                            for signal in helper_signals
                            if str(signal.get("name") or "")
                        )
                        + "."
                    )
                operation_protocol = (
                    helper.get("operation_protocol")
                    if isinstance(
                        helper.get("operation_protocol"),
                        Mapping,
                    )
                    else {}
                )
                if operation_protocol:
                    assertion_lines.append(
                        f"{owner}: helper {helper.get('owner')} must apply this "
                        "operation protocol exactly: "
                        + json.dumps(
                            operation_protocol,
                            ensure_ascii=True,
                            sort_keys=True,
                        )
                        + "."
                    )
            signal_contracts = [
                signal
                for signal in declaration_contract.get("signals") or []
                if isinstance(signal, Mapping)
            ]
            if signal_contracts:
                assertion_lines.append(
                    f"{owner}: declare these exact Qt signals at class scope and "
                    "connect them before background dispatch: "
                    + ", ".join(
                        str(signal.get("name") or "")
                        for signal in signal_contracts
                        if str(signal.get("name") or "")
                    )
                    + "."
                )
            required_call_order = [
                str(value)
                for value in declaration_contract.get("required_call_order") or []
                if str(value)
            ]
            if required_call_order:
                assertion_lines.append(
                    f"{owner}: one orchestration callable must execute this verified "
                    "capability chain in order: "
                    + " -> ".join(required_call_order)
                    + "."
                )
            for decorator in declaration_contract.get("decorators") or []:
                assertion_lines.append(
                    f"{owner}: declare and import @{decorator}."
                )
            fields = declaration_contract.get("fields") or []
            if fields:
                assertion_lines.append(
                    f"{owner}: exact typed fields: "
                    + ", ".join(
                        f"{field.get('name')}: {field.get('type')}"
                        for field in fields
                        if isinstance(field, Mapping)
                    )
                    + "."
                )
            signatures = declaration_contract.get("callable_signatures") or []
            if signatures:
                assertion_lines.append(
                    f"{owner}: exact callable signatures: "
                    + "; ".join(str(value) for value in signatures)
                    + "."
                )
            for method_task in contract.get("method_tasks") or []:
                if not isinstance(method_task, Mapping):
                    continue
                method_name = str(method_task.get("name") or "")
                if not method_name:
                    continue
                assertion_lines.append(
                    f"{owner}.{method_name}: implement exact signature "
                    f"`{method_task.get('signature')}` and satisfy every owned "
                    "mechanic: "
                    + " | ".join(
                        str(step)
                        for step in method_task.get(
                            "implementation_mechanics",
                        ) or []
                        if str(step).strip()
                    )
                    + "."
                )
            for mechanic in contract.get("implementation_mechanics") or []:
                if not isinstance(mechanic, Mapping):
                    continue
                assertion_lines.extend(
                    f"{owner}: {step}"
                    for step in mechanic.get("steps") or []
                    if not str(step).startswith(
                        "Implement the requirement inside its approved owner"
                    )
                )
        baseline_assertion_count = 7
        unique_execution_markers = (
            "import and consume validated dependency owner",
            "explicit request forbids importing",
            "governing dependency constraint",
            "dispatch blocking work outside the UI thread",
            "provide an event-loop-safe completion path",
            "provide an event-loop-safe error path",
            "call verified capability",
            "read verified property",
            "Import the verified dependency exactly",
            "construct an instance of",
            "must apply this operation protocol exactly",
            "must declare, emit, and expose these Qt signals",
            "execute this verified capability chain in order",
        )
        compact_assertion_lines = list(assertion_lines[:baseline_assertion_count])
        compact_assertion_lines.extend(
            assertion
            for assertion in assertion_lines[baseline_assertion_count:]
            if any(marker in assertion for marker in unique_execution_markers)
        )
        assertion_lines = list(dict.fromkeys(compact_assertion_lines))
        contract_hashes = {
            declaration_id: hashlib.sha256(
                json.dumps(
                    approved_chunks.get(declaration_id, {}),
                    ensure_ascii=True,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            for declaration_id in file_chunk_ids
        }
        capsule_prompt = (
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + "\n\nNON-NEGOTIABLE MACHINE ASSERTIONS:\n- "
            + "\n- ".join(assertion_lines)
            + "\nReturn code only after satisfying every assertion above."
        )
        estimated_input_tokens = max(1, len(capsule_prompt) // 3)
        owner_num_ctx = max(
            8192,
            ((estimated_input_tokens + 3071) // 1024) * 1024,
        )
        capsule_error = (
            "Owner capsule has no declaration identity."
            if not str(owner_declaration.get("owner") or "").strip()
            else ""
        )
        stages.append((
            path,
            existing_source,
            ProjectEditPromptStage(
                key=f"artifact_owner_generation_{capsule_index}",
                label=(
                    "Generating "
                    + str(owner_declaration.get("owner") or "<module>")
                    + f" in {Path(path).name}"
                ),
                system_prompt=(
                    "You are a bounded senior Python implementation worker. Produce "
                    "one complete owner capsule from the exact approved contract. "
                    "Emit the named owner plus every explicitly approved helper "
                    "declaration in declaration_contract.helper_declarations, and no "
                    "other declarations. "
                    "Every owned requirement is mandatory executable behavior, not "
                    "background context. Never invent dependencies, APIs, declarations, "
                    "or requirements. Do not restate, revise, or re-plan the approved "
                    "contract. Use precise public types, one canonical implementation "
                    "per behavior, deterministic ordering, exact semantic filtering, "
                    "real progress totals, and complete background-worker lifecycle "
                    "ownership. Return only this owner and its required imports; "
                    "deterministic assembly will construct the final file."
                ),
                user_prompt=capsule_prompt,
                model_tier="local_code",
                num_ctx=owner_num_ctx,
                num_predict=-1,
                timeout=120,
                no_progress_seconds=90,
                prefer_coder=True,
                coder_preference="standard",
                response_format="",
                metadata={
                    "mode": "approved_owner",
                    "chunk_id": declaration_id,
                    "chunk_ids": file_chunk_ids,
                    "owner": str(
                        owner_declaration.get("owner") or "<module>"
                    ),
                    "kind": str(owner_declaration.get("kind") or "symbol"),
                    "owners": [
                        declaration["owner"]
                        for declaration in declarations_for_file
                    ],
                    "all_file_owners": all_file_owners,
                    "path": path,
                    "requirement_ids": requirement_ids,
                    "depends_on": file_dependencies,
                    "expected_public_symbols": expected_public_symbols,
                    "approved_contract_hashes": contract_hashes,
                    "approved_contracts": contracts,
                    "declaration_contract": dict(declaration_contract),
                    "required_methods": list(dict.fromkeys(
                        str(task.get("name") or "").strip()
                        for task in payload.get("method_tasks") or []
                        if isinstance(task, Mapping)
                        and str(task.get("name") or "").strip()
                    )),
                    "machine_assertions": assertion_lines,
                    "existing_source_read_error": existing_source_read_error,
                    "capsule_error": capsule_error,
                    "capsule_input_characters": len(capsule_prompt),
                    "capsule_estimated_input_tokens": estimated_input_tokens,
                    "capsule_num_ctx": owner_num_ctx,
                    "context_packing": (
                        "mandatory_owner_sections_only_no_runtime_truncation"
                    ),
                },
            ),
        ))
    return stages


def parse_project_edit_generated_chunk(
    response: str,
    *,
    owner: str,
    kind: str,
    allowed_declarations: Iterable[str] = (),
    required_methods: Iterable[str] = (),
) -> tuple[str, list[str]]:
    """Validate one exact raw-Python implementation chunk."""

    source = str(response or "").strip()
    source = re.sub(r"^```(?:python|py)?\s*", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s*```$", "", source)
    try:
        tree = ast.parse(source, filename=f"<chunk:{owner}>")
    except SyntaxError as exc:
        return "", [f"[owner:{owner}] Chunk syntax error: {exc}"]

    def placeholder_callables(root: ast.AST) -> list[str]:
        names: list[str] = []
        for node in ast.walk(root):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            executable_body = list(node.body)
            if (
                executable_body
                and isinstance(executable_body[0], ast.Expr)
                and isinstance(executable_body[0].value, ast.Constant)
                and isinstance(executable_body[0].value.value, str)
            ):
                executable_body = executable_body[1:]
            if len(executable_body) != 1:
                continue
            statement = executable_body[0]
            if isinstance(statement, ast.Pass):
                names.append(node.name)
            elif (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and statement.value.value is Ellipsis
            ):
                names.append(node.name)
            elif (
                isinstance(statement, ast.Raise)
                and isinstance(statement.exc, ast.Call)
                and isinstance(statement.exc.func, ast.Name)
                and statement.exc.func.id == "NotImplementedError"
            ):
                names.append(node.name)
        return names

    if owner != "<module>":
        expected_name = owner.split("(", 1)[0].rsplit(".", 1)[-1]
        allowed_names = {
            str(value).strip()
            for value in allowed_declarations
            if str(value).strip()
            and str(value).strip().rsplit(".", 1)[-1].startswith("_")
        }
        top_level = [
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == expected_name
        ]
        if len(top_level) != 1:
            return "", [
                f"[owner:{owner}] Expected exactly one top-level declaration "
                f"named {expected_name!r}; found {len(top_level)}."
            ]
        missing_allowed = [
            name
            for name in sorted(allowed_names)
            if not any(
                isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == name
                for node in tree.body
            )
        ]
        if missing_allowed:
            return source.rstrip() + "\n", [
                f"[owner:{owner}] Missing approved helper declarations: "
                + ", ".join(missing_allowed)
            ]
        # Small local models sometimes return a complete file despite an exact
        # owner contract. If the requested declaration is independently valid,
        # extract it deterministically rather than spending another inference.
        selected_nodes = [
            node
            for node in tree.body
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            or isinstance(node, (ast.Import, ast.ImportFrom))
            or (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in ({expected_name} | allowed_names)
            )
        ]
        if len(selected_nodes) != len(tree.body):
            lines = source.splitlines()
            source = "\n\n".join(
                "\n".join(lines[node.lineno - 1:node.end_lineno]).strip()
                for node in selected_nodes
            ).rstrip() + "\n"
            tree = ast.parse(source, filename=f"<chunk:{owner}:scoped>")
            top_level = [
                node
                for node in tree.body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == expected_name
            ]
        required_method_names = {
            str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip()
            for value in required_methods
            if str(value).strip()
        }
        scoped_issues: list[str] = []
        scoped_placeholder_names = placeholder_callables(tree)
        if scoped_placeholder_names:
            scoped_issues.append(
                f"[owner:{owner}] Placeholder callable bodies: "
                + ", ".join(scoped_placeholder_names)
            )
        if (
            top_level
            and isinstance(top_level[0], ast.ClassDef)
            and required_method_names
        ):
            declared_methods = {
                node.name
                for node in top_level[0].body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            missing_methods = sorted(required_method_names - declared_methods)
            if missing_methods:
                scoped_issues.append(
                    f"[owner:{owner}] Missing approved methods: "
                    + ", ".join(missing_methods)
                )
        if scoped_issues:
            return source.rstrip() + "\n", scoped_issues
    else:
        allowed_names = {
            str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip()
            for value in allowed_declarations
            if str(value).strip()
        }
        retained_nodes: list[ast.stmt] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                retained_nodes.append(node)
            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                retained_nodes.append(node)
            elif (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in allowed_names
            ):
                retained_nodes.append(node)
            elif (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
            ):
                retained_nodes.append(node)
        if len(retained_nodes) != len(tree.body):
            lines = source.splitlines()
            source = "\n\n".join(
                "\n".join(lines[node.lineno - 1:node.end_lineno]).strip()
                for node in retained_nodes
            ).rstrip() + "\n"
            tree = ast.parse(source, filename="<chunk:<module>:scoped>")
        scoped_placeholder_names = placeholder_callables(tree)
        if scoped_placeholder_names:
            return source.rstrip() + "\n", [
                f"[owner:{owner}] Placeholder callable bodies: "
                + ", ".join(scoped_placeholder_names)
            ]
    return source.rstrip() + "\n", []


def assemble_project_edit_generated_chunks(
    chunks: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Assemble validated owner chunks into importable files deterministically."""

    by_path: dict[str, list[tuple[str, str]]] = {}
    for path, owner, source in chunks:
        by_path.setdefault(path, []).append((owner, source))

    assembled: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for path, path_chunks in by_path.items():
        imports: list[str] = []
        declarations: list[str] = []
        module_prefix: list[str] = []
        module_suffix: list[str] = []
        for owner, source in path_chunks:
            tree = ast.parse(source, filename=f"<assembly:{path}:{owner}>")
            lines = source.splitlines()
            for node in tree.body:
                segment = "\n".join(lines[node.lineno - 1:node.end_lineno]).strip()
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if segment not in imports:
                        imports.append(segment)
                elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    declarations.append(segment)
                elif (
                    isinstance(node, ast.If)
                    and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                ):
                    module_suffix.append(segment)
                elif (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    if owner == "<module>" and not module_prefix:
                        module_prefix.append(segment)
                elif owner == "<module>":
                    module_prefix.append(segment)
                else:
                    errors.append(
                        f"[owner:{owner}] Unsupported non-declaration statement in chunk "
                        f"for {path}: {type(node).__name__}."
                    )
        source_parts = [
            "\n\n".join(imports),
            "\n\n".join(module_prefix),
            "\n\n".join(declarations),
            "\n\n".join(module_suffix),
        ]
        output = "\n\n".join(part for part in source_parts if part).rstrip() + "\n"
        try:
            ast.parse(output, filename=path)
        except SyntaxError as exc:
            errors.append(f"Chunk assembly syntax failure for {path}: {exc}")
            continue
        assembled.append((path, "", output))
    return assembled, errors


def build_project_edit_artifact_file_stages(
    plan: ProjectEditPlan,
    manifest: list[dict[str, Any]],
) -> list[tuple[str, str, ProjectEditPromptStage]]:
    """Build dependency-ordered full-file workers from a validated manifest."""

    stages: list[tuple[str, str, ProjectEditPromptStage]] = []
    for index, item in enumerate(manifest, start=1):
        target_path = str(item["absolute_path"])
        original_source_read_error = ""
        try:
            original_source = Path(target_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            original_source = ""
            if Path(target_path).exists():
                original_source_read_error = str(exc)
        requirements = "\n".join(f"- {value}" for value in item["requirements"])
        dependencies = "\n".join(f"- {value}" for value in item["depends_on"]) or "- none"
        public_symbols = "\n".join(f"- {value}" for value in item["public_symbols"]) or "- derive from requirements"
        contracts = "\n".join(f"- {value}" for value in item.get("contracts") or []) or "- none"
        algorithm_steps = "\n".join(
            f"{step_index}. {value}"
            for step_index, value in enumerate(item.get("algorithm_steps") or [], start=1)
        ) or "- none"
        validation_steps = "\n".join(
            f"- {value}" for value in item.get("validation_steps") or []
        ) or "- none"
        integration_contracts = "\n".join(
            f"- {value}" for value in item.get("integration_contracts") or []
        ) or "- none"
        is_test = bool(item["is_test"])
        stage = ProjectEditPromptStage(
            key=f"artifact_file_generation_{index}",
            label=f"Generating {Path(target_path).name}",
            system_prompt=(
                "You are a bounded senior Python implementation worker. Return one complete importable Python "
                "file as raw source. Do not return JSON, Markdown, commentary, a diff, or a partial symbol."
            ),
            user_prompt=f"""Original objective:
{plan.prompt}

File owned by this stage:
{item["path"]}

Purpose:
{item["purpose"]}

Requirements owned by this file:
{requirements}

Expected public symbols:
{public_symbols}

Callable and state contracts:
{contracts}

Required implementation algorithm:
{algorithm_steps}

Required validation proof:
{validation_steps}

Manifest dependencies:
{dependencies}

Package-wide integration contracts:
{integration_contracts}

Implement this file completely using only the Python standard library and visible completed dependency files.
Do not use placeholders, ellipses, pass-only bodies, invented external packages, or live user data.
Before defining any class, event, record, enum, protocol constant, or serialization layout, inspect the completed
dependency files. Import and reuse a dependency-owned concept instead of defining a second version. A consumer must
honor the dependency's exact signatures, defaults, state transitions, byte/data layout, and error semantics.
Every manifest dependency is an implementation dependency: import the exact API you consume from that file.
Do not leave a requested public record disconnected from storage and execution. Store the canonical record itself
or expose the exact public lookup needed by consumers. Never hard-code undeclared domain values that belong in public
arguments. Tests must call accepted signatures with accepted types and exercise the named behavior directly; a
reporting test calls the report/query API rather than expecting an unrelated registration method to raise.
Production implementations must preserve the concrete container shapes established by initialization. Membership
and duplicate checks must compare the actual stored element shape, not a tuple or wrapper that the container never
stores. Tests must never inspect, infer, or assert a production container's private representation. Query, report,
find, list, format, and ordering operations must work from local snapshots or local counters rather than mutating
persistent state unless mutation is explicitly part of the accepted contract.
Preserve canonical record metadata across method boundaries. A writer or validator must receive the record or exact
declared identity, offset, length, and digest fields; it must not reconstruct them from payload length, iteration
order, or temporary filenames. Atomic output must use one stable staging path, validate completeness before publish,
replace the final path atomically, and clean up failures without exposing partial output. Implement immutable records
with a frozen dataclass or named tuple.
{"Write substantive unittest coverage with deterministic temporary fixtures, including success, failure, and recovery behavior. Import production APIs from the completed dependency files. Never copy or redeclare a production class, function, protocol, or constant in a test file. Test methods must use unittest.TestCase or unittest.IsolatedAsyncioTestCase as appropriate. Treat the original request and accepted contracts as the specification: construct representative requested states and assert the requested observable result. Use only the exact approved production methods and attributes listed above. Trigger UI operations through the approved widgets and their public Qt signals. Never call implementation slots directly, invent convenience methods, inspect production storage, or assume a storage element shape. Never change a requested report, find, return, create, save, load, callback, or UI behavior into an exception expectation unless the request or accepted contract explicitly requires rejection for that case. Call non-mutating query/report/find/list/order operations repeatedly with unchanged state and assert equivalent results." if is_test else "Use precise typed interfaces; when the request, dependency signature, or produced value proves a concrete type, `Any` is not acceptable on the public surface. Keep one canonical implementation per behavior and emit no unreferenced private helper. Ordered results require a stable semantic tie-breaker, named exclusions require exact canonical matching, iterative progress requires totals derived from real work, and threaded UI owners must guard repeated starts and connect finished cleanup. Document every public callable with a domain-specific behavioral summary, one `:param name:` field per public parameter, and `:return:` whenever it returns a value."}
Do not execute demonstrations, print, start workers, access files, or invoke public APIs at module import time.
The first response character must belong to valid Python source. Return raw Python only.
""",
            model_tier="local_code",
            num_ctx=6144,
            # A complete file is bounded by validation and timeout, not a guessed token count.
            num_predict=-1,
            timeout=120,
            no_progress_seconds=25,
            prefer_coder=True,
            coder_preference="standard",
            response_format="",
            metadata={
                "expected_public_symbols": list(item["public_symbols"]),
                "requirement_ids": list(item.get("requirement_ids") or []),
                "depends_on": list(item.get("depends_on") or []),
                "contracts": list(item.get("contracts") or []),
                "algorithm_steps": list(item.get("algorithm_steps") or []),
                "validation_steps": list(item.get("validation_steps") or []),
                "is_test": is_test,
                "existing_source_read_error": original_source_read_error,
            },
        )
        stages.append((target_path, original_source, stage))
    return stages


def build_project_edit_missing_symbol_stage(
    *,
    path: str,
    symbol: str,
    source: str,
    objective: str,
    contracts: list[str] | None = None,
    algorithm_steps: list[str] | None = None,
    container: str = "",
) -> ProjectEditPromptStage:
    """Build one bounded declaration insertion without regenerating its file."""

    return ProjectEditPromptStage(
        key="artifact_missing_symbol",
        label=f"Implementing missing {symbol}",
        system_prompt=(
            "You are a bounded senior Python implementation worker. Return exactly one complete "
            + (
                f"class `{container}` containing only the missing `{symbol}` method as raw Python. "
                if container
                else "top-level class or function declaration as raw Python. "
            )
            + "Do not return imports, JSON, "
            "Markdown, commentary, or the surrounding file."
        ),
        user_prompt=f"""Original objective:
{objective}

File:
{path}

Missing manifest-owned public symbol:
{container + '.' if container else ''}{symbol}

Contracts:
{chr(10).join(f"- {value}" for value in contracts or []) or "- none"}

Required algorithm:
{chr(10).join(f"- {value}" for value in algorithm_steps or []) or "- none"}

Existing validated file:
```python
{source}
```

Implement the missing public symbol completely. {f'Return class {container} with only method {symbol}; the method will be spliced into the existing class.' if container else ''}
Use only builtins, names already imported or defined
in the existing file, and exact visible interfaces. Preserve every existing declaration. Do not add
placeholder bodies, demonstrations, or module-level execution. Return raw Python only.
""",
        model_tier="local_code",
        num_ctx=6144,
        num_predict=2400,
        timeout=60,
        no_progress_seconds=20,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "symbol": f"{container}.{symbol}" if container else symbol,
            "scope": "class_member" if container else "module",
            "container": container,
            "objective": objective,
            "owner_source": source,
        },
    )


def _remove_generated_top_level_await(source: str, *, path: str) -> str:
    """Remove forbidden module-execution blocks containing top-level await."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return source
    removals = [
        statement
        for statement in tree.body
        if not isinstance(
            statement,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
        and any(isinstance(node, ast.Await) for node in ast.walk(statement))
    ]
    if not removals:
        return source
    lines = source.splitlines(keepends=True)
    for statement in sorted(removals, key=lambda item: item.lineno, reverse=True):
        del lines[statement.lineno - 1:int(statement.end_lineno or statement.lineno)]
    return "".join(lines)
