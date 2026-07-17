"""Project-aware edit agent orchestration.

This module ties together existing Tech Connector pieces:

- project edit target discovery from :mod:`services.project_service`
- XML file-change parsing and resilient replacement from :mod:`knowledge.search`
- persistent undo sessions from :mod:`services.change_history_service`
- lightweight Python validation via ``py_compile``

It does not call an LLM by itself. The UI/router can use
``build_project_edit_agent_request`` to prepare the grounded prompt, pass that to
the selected coding model, then feed the model text into
``apply_project_edit_agent_response``.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import py_compile
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
            },
            "required": ["changed", "reused", "verification", "remaining_gaps"],
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


def build_project_edit_agent_request(
    prompt: str,
    *,
    active_path: str | None = None,
    limit: int = 8,
) -> ProjectEditPlan:
    """Build the grounded edit request sent to the coding model."""

    from tech_connector.services.project_service import (
        build_project_edit_target_prompt,
        discover_edit_targets,
        format_edit_target_context,
    )

    discovery = _build_explicit_active_edit_discovery(
        prompt,
        active_path=active_path,
        limit=limit,
    )
    if discovery is None:
        try:
            discovery = discover_edit_targets(prompt, active_path=active_path, limit=limit)
        except Exception as exc:
            discovery = _fallback_project_edit_discovery(
                prompt,
                active_path=active_path,
                error=exc,
            )
    discovery_context = format_edit_target_context(discovery)
    if _project_edit_needs_deep_intelligence(prompt, discovery):
        intelligence_packet = _build_project_edit_intelligence_packet(
            prompt,
            active_path=active_path,
            limit=limit,
        )
    else:
        intelligence_packet = _lightweight_project_edit_intelligence_packet(
            prompt,
            discovery,
        )
    adaptive_plan = build_code_agent_adaptive_plan(
        prompt,
        discovery=discovery,
        active_path=active_path,
        intelligence_packet=intelligence_packet,
    )
    domain_experts = select_code_agent_experts(
        prompt,
        discovery=discovery,
        active_path=active_path,
    )
    model_prompt = build_project_edit_target_prompt(
        question=prompt,
        discovery_context=discovery_context,
        active_path=active_path,
    )
    adaptive_section = render_code_agent_adaptive_plan(adaptive_plan)
    if adaptive_section:
        model_prompt = f"{model_prompt}\n\n{adaptive_section}\n"
    expert_section = render_code_agent_expert_context(domain_experts)
    if expert_section:
        model_prompt = f"{model_prompt}\n\n{expert_section}\n"
    intelligence_section = _render_project_edit_intelligence_packet(intelligence_packet)
    if intelligence_section:
        model_prompt = f"{model_prompt}\n\n{intelligence_section}\n"
    return ProjectEditPlan(
        prompt=prompt,
        active_path=active_path or "",
        discovery=discovery,
        discovery_context=discovery_context,
        intelligence_packet=intelligence_packet,
        adaptive_plan=adaptive_plan,
        domain_experts=domain_experts,
        success_contract=list(adaptive_plan.get("success_contract") or []),
        model_prompt=model_prompt,
        stages=[
            _stage("request", "Accepted project edit request"),
            _stage("code_intelligence", "Built IDE-style code intelligence packet"),
            _stage("target_discovery", "Gathered indexed target evidence"),
            _stage("expert_selection", "Selected code and domain expert lenses"),
            _stage("adaptive_planning", "Built objective-to-output code plan"),
            _stage("planning", "Prepared grounded coding-model prompt"),
        ],
    )


def _build_explicit_active_edit_discovery(
    prompt: str,
    *,
    active_path: str | None,
    limit: int,
) -> dict[str, Any] | None:
    """Resolve an explicitly named active Python file from indexed facts only."""

    path = Path(str(active_path or ""))
    if path.suffix.lower() != ".py":
        return None
    lowered = str(prompt or "").lower().replace("\\", "/")
    explicit_file = path.name.lower() in lowered or str(path).lower().replace("\\", "/") in lowered
    active_reference = bool(re.search(r"\b(this|current|active)\s+file\b", lowered))
    if not (explicit_file or active_reference):
        return None

    from tech_connector.services.file_index_service import file_index_service

    snapshot = file_index_service.get_file_snapshot(
        str(path),
        symbol_limit=max(24, int(limit or 8) * 4),
    )
    if snapshot is None:
        return None
    terms = {
        term.lower()
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", prompt or "")
        if term.lower() not in {"add", "and", "file", "function", "method", "only", "the", "this", "with"}
    }
    indexed_path = str(snapshot.get("path") or path)
    symbols: list[dict[str, Any]] = []
    for indexed_symbol in snapshot.get("symbols") or []:
        symbol = dict(indexed_symbol)
        qualname = str(symbol.get("qualname") or symbol.get("name") or "")
        source = str(symbol.get("source") or "")
        relevance = sum(12 for term in terms if term in qualname.lower())
        relevance += sum(min(source.lower().count(term), 3) for term in terms)
        symbol.update({"path": indexed_path, "relevance": relevance})
        symbols.append(symbol)
    symbols.sort(key=lambda item: (-int(item.get("relevance") or 0), int(item.get("start_line") or 1)))
    roots = [str(snapshot.get("root") or "").strip()]
    roots = [root for root in roots if root]
    candidate = {
        "path": indexed_path,
        "score": 100,
        "symbols": symbols[: max(8, int(limit or 8) * 2)],
        "chunks": [],
        "index_revision": str(snapshot.get("sha1") or ""),
    }
    return {
        "question": prompt,
        "terms": sorted(terms)[:20],
        "scope": "active_file",
        "project_roots": roots,
        "active_path": indexed_path,
        "best_target": candidate,
        "candidates": [candidate],
        "confidence": "high",
        "evidence_mode": "explicit_index_snapshot",
        "index_revision": str(snapshot.get("sha1") or ""),
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
            from tech_connector.services.goal_gap_planning_service import build_goal_gap_plan
            from tech_connector.services.multi_stage_reasoning_service import build_reasoning_pipeline

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
            "New public callables use clear domain names, useful docstrings, and explicit interfaces.",
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


def select_code_agent_experts(
    prompt: str,
    *,
    discovery: dict[str, Any] | None = None,
    active_path: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Select existing domain experts that should advise a project code edit."""

    discovery = dict(discovery or {})
    host = _infer_code_agent_host(prompt, discovery, active_path)
    expert_prompt = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            str((discovery.get("best_target") or {}).get("path") or ""),
            " ".join(str(item.get("path") or "") for item in discovery.get("candidates") or [] if isinstance(item, dict)),
        ]
    )
    decision = {
        "route": "code_edit",
        "intent_category": "project_edit",
        "host": host,
        "mutation_scope": "code_change",
        "provider": "project_index",
    }
    try:
        from tech_connector.services.domain_expert_service import select_domain_experts

        return select_domain_experts(expert_prompt, decision, limit=limit)
    except Exception:
        return []


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


def build_project_edit_model_stages(plan: ProjectEditPlan) -> list[ProjectEditPromptStage]:
    """Build smaller LLM stages so large code edits do not rely on one huge call."""

    from tech_connector.services.ollama_resource_service import choose_project_edit_coder_profile

    objective = plan.prompt
    coder_profile = choose_project_edit_coder_profile(prompt=objective)
    patch_budgets = {
        "micro": (5120, 1100, 120, 18),
        "small": (6144, 1350, 135, 20),
        "standard": (7168, 1550, 165, 22),
        "quality": (8192, 1800, 210, 25),
    }
    patch_ctx, patch_predict, patch_timeout, patch_no_progress = patch_budgets.get(
        coder_profile,
        patch_budgets["micro"],
    )
    compact_discovery = _compact_discovery_evidence(plan)
    context_limits = {
        "micro": (1600, 800, 450, 4500),
        "small": (2200, 1100, 650, 5500),
        "standard": (3000, 1400, 900, 6500),
        "quality": (3800, 1800, 1200, 7500),
    }
    discovery_limit, adaptive_limit, expert_limit, source_limit = context_limits.get(
        coder_profile,
        context_limits["small"],
    )
    discovery = _trim_text(plan.discovery_context, discovery_limit)
    adaptive = _trim_text(render_code_agent_adaptive_plan(plan.adaptive_plan), adaptive_limit)
    experts = _trim_text(render_code_agent_expert_context(plan.domain_experts), expert_limit)
    focused_source = _focused_project_edit_source_context(plan, max_chars=source_limit)
    planning_source = _trim_text(focused_source, 4000)
    target_path = str((plan.discovery.get("best_target") or {}).get("path") or plan.active_path or "")
    common_system = (
        "You are a senior Python/PySide/Maya/Unreal tools engineer inside Tech Connector. "
        "Use only the supplied project evidence. Reuse existing functions, classes, and helpers. "
        "Do not invent files, APIs, imports, or call sites. Work iteratively: implement what is evidenced, "
        "identify gaps, resolve them from project patterns or authoritative APIs, bridge them with real code, "
        "then validate and repeat. Completion requires working behavior, not a plausible-looking patch. "
        "During planning, never emit code, pseudocode, code fences, or replacement bodies."
    )
    quick_plan_prompt = f"""User objective:
{objective}

Compact target evidence:
{compact_discovery}

Focused exact source excerpts:
{planning_source or '(no source excerpt could be resolved)'}

Selected expert lenses:
{experts or '(none)'}

Stage task:
Create an approval-ready implementation plan. Do not emit XML patches or implementation code.
When the request asks for a change, including preview-only changes, plan patch generation rather than a search-only answer.
Use exact files and existing symbol names from the evidence. Do not describe behavior as "likely" or inferred.
Keep the response under 450 words. Describe signatures and behavior in prose only.
Before returning, compare the proposed changes with the objective and evidence. Resolve contradictory file scope,
unsupported symbols, missing tests, and any claim that conflicts with another section.

Return exactly these prose sections:
Intent:
Evidence-backed targets:
Existing symbols to reuse:
Proposed changes:
Tests and verification:
Blockers:
Plan self-check:
Approval scope:
"""
    patch_prompt = f"""User objective:
{objective}

Chosen target:
{target_path or '(none)'}

Focused exact source excerpts:
{focused_source or '(no source excerpt could be resolved)'}

Focused target-discovery evidence:
{discovery}

Selected expert lenses:
{experts or '(none)'}

Adaptive execution contract:
{adaptive}

Stage task:
Produce the smallest safe patchable implementation that completes the objective, or explicitly stop with a blocker.

Preview contract:
- A preview still requires a complete structured change payload; the application will not write it until the user approves.
- "Do not apply" means emit a patch preview without touching files. It does not mean return an empty changes list.

Rules:
- Reuse the original project function rather than duplicating it.
- Use project-local classes/helpers/patterns when evidence shows they fit.
- Keep changes narrow and testable.
- Give new public functions/classes clear domain names, type-aware interfaces, and useful docstrings.
- Account for every new import. Use only standard-library, installed, project-local, or explicitly host-provided modules.
- Add or update focused unittest tests that prove the requested behavior and failure handling and can run without a live DCC by mocking host boundaries.
- Ensure all emitted Python parses and all test imports resolve before claiming completion.
- If target confidence is low or evidence is insufficient, do not invent. Return a blocker report.
- Return exactly one JSON object with this shape and no Markdown fences:
  {{"changes": [{{"action": "replace_symbol", "path": "absolute/or/relative/path.py", "target_symbol": "existing_function_or_Class.method", "original_content": "", "new_content": "complete replacement symbol source"}}], "report": {{"changed": [], "reused": [], "verification": [], "remaining_gaps": []}}, "blocked_reason": ""}}
- Prefer action "replace_symbol" for Python edits. Name an exact indexed symbol and provide its complete replacement source; the AST resolver owns exact source matching and indentation.
- For replace_symbol, copy the exact existing symbol from the source excerpt and make the smallest necessary edit. Preserve its docstring, quote style, and unrelated lines.
- To add a new helper, use "insert_before_symbol" with an existing function at the same scope as target_symbol.
- To add a test method, use "insert_after_symbol" with an existing Class.method as target_symbol.
- To add one import without rewriting an import block, use "ensure_import" with the module in target_symbol and the imported name in new_content.
- Multiple operations on one file are composed transactionally in list order.
- Use action "create" only for clearly required new files; set target_symbol and original_content to empty strings and place the full file in new_content.
- Use action "modify" only when no symbol boundary fits; copy original_content exactly from supplied excerpts. Never use ellipses.

Required report after patch tags:
1. What was changed.
2. Existing systems reused.
3. Verification to run.
4. Static vs runtime verification.
5. Rollback path.
6. Remaining gaps, if any; do not claim completion while a required gate is unverified.
"""
    stages = [
        ProjectEditPromptStage(
            key="target_selection_plan",
            label="Selecting target and first implementation plan",
            system_prompt=common_system,
            user_prompt=quick_plan_prompt,
            model_tier="local_plan",
            num_ctx=4096,
            num_predict=550,
            timeout=180,
            no_progress_seconds=25,
            prefer_coder=False,
        )
    ]
    if _project_edit_requires_patch(objective):
        stages.append(
            ProjectEditPromptStage(
                key="patch_generation",
                label="Generating patchable code changes",
                system_prompt=common_system,
                user_prompt=patch_prompt,
                model_tier="local_code",
                num_ctx=patch_ctx,
                num_predict=patch_predict,
                timeout=patch_timeout,
                no_progress_seconds=patch_no_progress,
                prefer_coder=True,
                coder_preference=coder_profile,
                response_format=PROJECT_EDIT_CHANGE_SCHEMA,
            )
        )
    return stages


def validate_project_edit_plan_output(plan: ProjectEditPlan, output: str) -> list[str]:
    """Return evidence failures that make a model-authored plan unsafe to hand off."""

    text = str(output or "").strip()
    if len(text) < 120:
        return ["Planning output was empty or too short to establish a grounded handoff."]

    errors: list[str] = []
    lowered = text.lower()
    patch_markers = ("<modify_file", "<create_file", "<<<< original", "```")
    if any(marker in lowered for marker in patch_markers) or re.search(
        r"(?m)^\s*(?:async\s+def|def|class)\s+[A-Za-z_]\w*", text
    ):
        errors.append("Planning output contained implementation code instead of a target plan.")

    discovery = dict(plan.discovery or {})
    candidates: list[dict[str, Any]] = []
    best_target = discovery.get("best_target")
    if isinstance(best_target, dict) and best_target:
        candidates.append(best_target)
    for key in ("candidates", "targets"):
        candidates.extend(item for item in discovery.get(key) or [] if isinstance(item, dict))

    known_paths: list[str] = []
    for item in candidates:
        path = str(item.get("path") or "").strip()
        if path and path.lower() not in {known.lower() for known in known_paths}:
            known_paths.append(path)
    if plan.active_path and plan.active_path.lower() not in {path.lower() for path in known_paths}:
        known_paths.append(plan.active_path)

    if known_paths and not any(
        path.lower() in lowered or Path(path).name.lower() in lowered
        for path in known_paths
    ):
        errors.append("Planning output did not identify any evidence-backed target file.")
    known_symbols: list[str] = []
    known_symbol_keys: set[str] = set()
    for item in candidates:
        for symbol in item.get("symbols") or []:
            name = str(symbol.get("name") if isinstance(symbol, dict) else symbol).strip()
            if name and name.lower() not in known_symbol_keys:
                known_symbols.append(name)
                known_symbol_keys.add(name.lower())
    if known_paths:
        try:
            from tech_connector.services.file_index_service import file_index_service

            for path in known_paths:
                snapshot = file_index_service.get_file_snapshot(path, symbol_limit=500)
                for symbol in (snapshot or {}).get("symbols") or []:
                    name = str(symbol.get("qualname") or symbol.get("name") or "").strip()
                    bare_name = name.rsplit(".", 1)[-1]
                    for candidate_name in (name, bare_name):
                        if candidate_name and candidate_name.lower() not in known_symbol_keys:
                            known_symbols.append(candidate_name)
                            known_symbol_keys.add(candidate_name.lower())
        except Exception:
            pass
    if known_symbols and not any(
        re.search(rf"\b{re.escape(name.lower())}\b", lowered)
        for name in known_symbols
    ):
        errors.append("Planning output did not name any indexed existing symbol to inspect or reuse.")
    if _project_edit_requires_patch(plan.prompt) and any(
        phrase in lowered for phrase in ("search-only", "search only", "analysis-only", "analysis only")
    ):
        errors.append("Planning output selected a non-mutation stage for an implementation request.")
    if not any(term in lowered for term in ("reuse", "existing", "helper", "function", "class", "service")):
        errors.append("Planning output did not identify existing project behavior to reuse or inspect.")
    if not any(term in lowered for term in ("test", "verify", "validation", "compile", "import")):
        errors.append("Planning output omitted concrete implementation verification gates.")
    if "plan self-check" not in lowered:
        errors.append("Planning output omitted its evidence and scope self-check.")
    mentioned_python_files = {
        match.lower()
        for match in re.findall(r"[A-Za-z0-9_./\\-]+\.py", text, flags=re.IGNORECASE)
    }
    if "no other files" in lowered and len(mentioned_python_files) > 1:
        errors.append("Planning output contradicted its own multi-file change scope.")
    return errors


def render_grounded_project_edit_handoff(
    plan: ProjectEditPlan,
    *,
    rejected_plan_errors: list[str] | None = None,
) -> str:
    """Render a deterministic handoff when model planning is absent or ungrounded."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = str(best_target.get("path") or plan.active_path or "").strip()
    confidence = str(discovery.get("confidence") or "unknown")
    requires_patch = _project_edit_requires_patch(plan.prompt)
    planned_files = [target_path] if target_path else []
    roots = [Path(str(root)) for root in discovery.get("project_roots") or [] if str(root).strip()]
    if target_path and re.search(r"\b(test|tests|unittest|coverage)\b", plan.prompt, flags=re.IGNORECASE):
        for root in roots:
            test_path = root / "tests" / f"test_{Path(target_path).stem}.py"
            if test_path.is_file():
                planned_files.append(str(test_path))
                break
    lines = [
        "Implementation Plan",
        f"Objective: {plan.prompt}",
        f"Mutation requested: {'yes, generate a preview after approval' if requires_patch else 'no'}.",
        f"Best evidence-backed target: {target_path or '(no target established)'}.",
        f"Target confidence: {confidence}.",
        "Existing symbols and behavior to reuse or inspect:",
        _compact_discovery_evidence(plan),
        "Proposed changes:",
        f"- {'Generate the smallest focused implementation and matching tests for the stated objective.' if requires_patch else 'Return the evidence-backed analysis without producing a patch.'}",
        "Planned files: " + (", ".join(planned_files) if planned_files else "not established"),
        f"Next stage after approval: {'generate a focused patch preview' if requires_patch else 'return the evidence-backed analysis'}.",
        "Completion gates: parse and compile changed Python; account for imports; run focused tests; "
        "verify host/UI boundaries; leave no unresolved required gap.",
        "Plan self-check: target evidence is present, requested tests are included, file scope is explicit, "
        "and implementation remains deferred until approval.",
        "Approval scope: approval permits code generation and diff preview only; it does not write files.",
    ]
    if rejected_plan_errors:
        lines.append("Planner output was replaced because it failed the grounded handoff contract.")
    if not target_path or confidence not in {"high", "medium"}:
        lines.append("Blocker: continue project search before mutation until a supported target is established.")
    return "\n".join(lines)


def project_edit_plan_fingerprint(plan: ProjectEditPlan) -> str:
    """Fingerprint the grounded target so an approved plan cannot resume stale code."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    path = Path(str(best_target.get("path") or plan.active_path or ""))
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8", errors="replace"))
    index_revision = str(
        best_target.get("index_revision")
        or discovery.get("index_revision")
        or ""
    )
    if index_revision:
        digest.update(index_revision.encode("ascii", errors="replace"))
        return digest.hexdigest()
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<missing>")
    return digest.hexdigest()


def build_project_edit_repair_stage(
    plan: ProjectEditPlan,
    candidate_response: str,
    validation_failures: list[str],
    *,
    attempt: int,
    approved_plan: str = "",
) -> ProjectEditPromptStage:
    """Build a focused repair pass from deterministic candidate failures."""

    from tech_connector.services.ollama_resource_service import choose_project_edit_coder_profile

    failure_text = "\n".join(f"- {item}" for item in validation_failures) or "- Candidate validation failed."
    syntax_reset = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("syntax", "did not parse", "unterminated", "eol while scanning", "f-string")
    )
    implementation_reset = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("requested public symbols", "cannot import its requested implementation from itself")
    )
    completion_focus = any(
        marker in str(item).lower()
        for item in validation_failures
        for marker in ("need useful docstrings", "focused test file")
    )
    repair_strategy = (
        "Implementation reset: discard the entire rejected changes list. Define every missing requested symbol as real "
        "source using insert_before_symbol or insert_after_symbol anchored to an existing symbol. Wire the definition "
        "into the approved existing behavior, update the focused test import, and add the requested test. Never import "
        "a requested symbol from the module in which it is being defined."
        if implementation_reset
        else
        "Syntax reset: discard every candidate new_content value for the affected Python file. "
        "Re-copy each affected existing symbol from the exact source excerpt, preserve its quote style, "
        "and reapply only the requested behavior change."
        if syntax_reset
        else
        "Completion focus: preserve all passing operations. Add a useful docstring directly to each named public "
        "callable reported by the gate. For missing test coverage, include an operation on the existing focused test "
        "file, import the requested public symbol from its owner module, and add assertions for success and failure cases."
        if completion_focus
        else "Preserve candidate operations that already satisfy the gates; replace only failing operations and dependencies."
    )
    coder_profile = choose_project_edit_coder_profile(
        prompt=plan.prompt,
        repair_attempt=attempt,
    )
    repair_budgets = {
        "small": (5632, 1150, 105, 18, 9000),
        "standard": (6144, 1300, 135, 20, 10000),
        "quality": (7168, 1500, 210, 22, 11000),
    }
    repair_ctx, repair_predict, repair_timeout, repair_no_progress, candidate_limit = repair_budgets.get(
        coder_profile,
        repair_budgets["quality"],
    )
    repair_source_limits = {"small": 5000, "standard": 6000, "quality": 7000}
    focused_source = _focused_project_edit_source_context(
        plan,
        max_chars=repair_source_limits.get(coder_profile, 7000),
    )
    candidate_context = (
        "(discarded because the candidate failed a core implementation or syntax contract)"
        if implementation_reset or syntax_reset
        else _trim_text(candidate_response, candidate_limit)
    )
    prompt = f"""Original user objective:
{plan.prompt}

User-approved implementation plan:
{_trim_text(approved_plan, 5000) if approved_plan else '(approved plan unavailable; follow the grounded objective and source evidence)'}

Current exact source excerpts:
{focused_source or '(no exact source excerpt was resolved)'}

Deterministic quality failures:
{failure_text}

Repair strategy:
{repair_strategy}

Rejected candidate response:
{candidate_context}

Repair task:
Return a corrected, complete replacement response. Reuse only evidenced project APIs and paths.
Return one valid JSON change object, fixing every reported syntax, import, naming, docstring, and test-coverage issue.
Even when the user requested preview-only or said not to apply changes, emit a non-empty changes list; do not write files.
Focus only on the listed failures and their direct dependencies.
Include focused tests for behavior changes. Do not claim success for checks that were not represented in the patch.
The response must be exactly one JSON object with keys changes, report, and blocked_reason, with no Markdown or prose.
Use exact original_content text from the source excerpts. Never use ellipses, simulated bodies, or placeholder comments.
When a prior failure says an original block did not match, switch that change to replace_symbol with an exact existing target_symbol.
When a target symbol is new and does not exist yet, use insert_before_symbol or insert_after_symbol anchored to an existing symbol instead.
Use a bare function name for top-level target_symbol values and Class.method only for methods nested in a class.
Mentally compile every new_content string. Avoid quote delimiters that conflict with quotes inside f-string expressions.
Update the focused test import block when a new public service symbol is used by name.
If a required fact remains unknown, return an empty changes list and put the exact missing evidence in blocked_reason.
"""
    return ProjectEditPromptStage(
        key=f"quality_repair_{attempt}",
        label=f"Repairing implementation quality failures ({attempt}/5)",
        system_prompt=(
            "You are the final code-quality repair engineer. Produce importable, test-backed project code. "
            "Never replace an unresolved capability with a guessed function or placeholder implementation. "
            "A requested new symbol must be defined in its owner module, never self-imported."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=repair_ctx,
        num_predict=repair_predict,
        timeout=repair_timeout,
        no_progress_seconds=repair_no_progress,
        prefer_coder=True,
        coder_preference=coder_profile,
        response_format=PROJECT_EDIT_CHANGE_SCHEMA,
    )


def inspect_project_edit_structured_syntax(model_response: str) -> list[dict[str, Any]]:
    """Find independently parseable Python snippets with syntax errors in a change payload."""

    text = str(model_response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return []

    failures: list[dict[str, Any]] = []
    parseable_actions = {
        "create",
        "modify",
        "replace_symbol",
        "insert_before_symbol",
        "insert_after_symbol",
    }
    for index, change in enumerate(payload["changes"]):
        if not isinstance(change, dict):
            continue
        action = str(change.get("action") or "")
        path = str(change.get("path") or "")
        source = str(change.get("new_content") or "")
        if action not in parseable_actions or not path.lower().endswith(".py") or not source.strip():
            continue
        candidate = source if action == "create" else textwrap.dedent(source)
        try:
            ast.parse(candidate, filename=path)
        except SyntaxError as exc:
            failures.append(
                {
                    "change_index": index,
                    "action": action,
                    "path": path,
                    "target_symbol": str(change.get("target_symbol") or ""),
                    "source": source,
                    "error": f"{exc.msg} at line {exc.lineno}",
                }
            )
    return failures


def build_project_edit_syntax_repair_stage(
    issue: dict[str, Any],
    *,
    attempt: int,
) -> ProjectEditPromptStage:
    """Build a bounded small-model task that repairs one generated Python snippet."""

    profile = "small" if attempt <= 1 else "standard"
    source = str(issue.get("source") or "")
    prompt = f"""Repair only the Python syntax in this generated change snippet.

Operation: {issue.get('action')}
Target: {issue.get('path')}::{issue.get('target_symbol') or '(file)'}
Parser error: {issue.get('error')}

Generated source:
```python
{source}
```

Preserve the intended behavior, names, signature, docstring, and indentation semantics.
Do not add imports, placeholders, ellipses, new behavior, Markdown, or explanation.
Return exactly one JSON object containing corrected_source.
"""
    return ProjectEditPromptStage(
        key=f"syntax_subagent_{attempt}",
        label=f"Repairing one generated syntax defect ({attempt}/2)",
        system_prompt=(
            "You are a bounded Python syntax repair worker. Fix only the supplied parser error and "
            "return source that ast.parse accepts without changing behavior."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=5120 if profile == "small" else 6144,
        num_predict=1400 if profile == "small" else 1800,
        timeout=90 if profile == "small" else 120,
        no_progress_seconds=15,
        prefer_coder=True,
        coder_preference=profile,
        response_format=PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA,
    )


def apply_project_edit_syntax_repair(
    model_response: str,
    *,
    change_index: int,
    repair_response: str,
) -> str:
    """Replace one structured change snippet with a syntax worker's corrected source."""

    try:
        payload = json.loads(str(model_response or "").strip())
        repair = json.loads(str(repair_response or "").strip())
        corrected = repair.get("corrected_source")
        changes = payload.get("changes")
        if not isinstance(corrected, str) or not isinstance(changes, list):
            return model_response
        if not 0 <= int(change_index) < len(changes) or not isinstance(changes[int(change_index)], dict):
            return model_response
        try:
            ast.parse(textwrap.dedent(corrected), filename=str(changes[int(change_index)].get("path") or "<generated>"))
        except SyntaxError:
            return model_response
        changes[int(change_index)]["new_content"] = corrected
        return json.dumps(payload, ensure_ascii=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return model_response


def compile_project_edit_leaf_work_units(
    plan: ProjectEditPlan,
    approved_plan: str,
) -> ProjectEditLeafWorkUnits | None:
    """Compile bounded leaf tasks when the plan proves every edit boundary."""

    requested_symbols = sorted(_requested_public_symbol_names(plan.prompt))
    if len(requested_symbols) != 1 or not _requires_behavior_test(plan.prompt):
        return None

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = Path(str(best_target.get("path") or plan.active_path or ""))
    if target_path.suffix.lower() != ".py":
        return None

    roots = [Path(str(root)).resolve() for root in discovery.get("project_roots") or [] if str(root).strip()]
    from tech_connector.services.file_index_service import file_index_service

    target_snapshot = file_index_service.get_file_snapshot(str(target_path), symbol_limit=300)
    if target_snapshot is None:
        return None

    project_root = None
    test_path = None
    test_snapshot = None
    for ancestor in target_path.resolve().parents:
        if roots and not any(ancestor == root or _path_is_within(ancestor, root) for root in roots):
            continue
        candidate = ancestor / "tests" / f"test_{target_path.stem}.py"
        candidate_snapshot = file_index_service.get_file_snapshot(str(candidate), symbol_limit=300)
        if candidate_snapshot is not None:
            project_root = ancestor
            test_path = candidate
            test_snapshot = candidate_snapshot
            break
    if project_root is None or test_path is None or test_snapshot is None:
        return None

    target_symbols = _indexed_symbol_source_entries(target_snapshot)
    integration = _select_leaf_integration_symbol(
        target_symbols,
        approved_plan=approved_plan,
        objective=plan.prompt,
    )
    if integration is None:
        return None

    helper_name = requested_symbols[0]
    test_symbols = [
        entry for entry in _indexed_symbol_source_entries(test_snapshot)
        if entry[0].rsplit(".", 1)[-1].startswith("test_")
    ]
    test_anchor = _select_leaf_test_anchor(
        test_symbols,
        approved_plan=approved_plan,
        objective=plan.prompt,
        helper_name=helper_name,
        integration_symbol=integration[0],
    )
    if test_anchor is None:
        return None

    try:
        relative_module = target_path.resolve().relative_to(project_root).with_suffix("")
    except (OSError, ValueError):
        return None
    if not relative_module.parts or not all(part.isidentifier() for part in relative_module.parts):
        return None

    return ProjectEditLeafWorkUnits(
        helper_name=helper_name,
        target_path=str(target_path.resolve()),
        integration_symbol=integration[0],
        integration_source=integration[1],
        test_path=str(test_path.resolve()),
        test_anchor_symbol=test_anchor[0],
        test_anchor_source=test_anchor[1],
        owner_module=".".join(relative_module.parts),
        target_revision=str(target_snapshot.get("sha1") or ""),
        test_revision=str(test_snapshot.get("sha1") or ""),
    )


def project_edit_leaf_work_units_handoff(
    work_units: ProjectEditLeafWorkUnits,
) -> dict[str, Any]:
    """Serialize bounded edit ownership without carrying source blobs in UI state."""

    payload = {
        "version": 1,
        "helper_name": work_units.helper_name,
        "target_path": work_units.target_path,
        "integration_symbol": work_units.integration_symbol,
        "test_path": work_units.test_path,
        "test_anchor_symbol": work_units.test_anchor_symbol,
        "owner_module": work_units.owner_module,
        "target_revision": work_units.target_revision,
        "test_revision": work_units.test_revision,
    }
    payload["fingerprint"] = _project_edit_leaf_handoff_fingerprint(payload)
    return payload


def restore_project_edit_leaf_work_units(
    payload: dict[str, Any] | None,
    request_prompt: str,
) -> tuple[ProjectEditLeafWorkUnits | None, list[str]]:
    """Restore approved work units after exact-file revision validation."""

    data = dict(payload or {})
    if int(data.get("version") or 0) != 1:
        return None, ["The approved work-unit handoff version is unsupported."]
    expected_fingerprint = str(data.pop("fingerprint", ""))
    if expected_fingerprint != _project_edit_leaf_handoff_fingerprint(data):
        return None, ["The approved work-unit handoff was modified."]
    helper_name = str(data.get("helper_name") or "")
    if helper_name not in _requested_public_symbol_names(request_prompt):
        return None, ["The approved helper no longer matches the request."]
    owner_module = str(data.get("owner_module") or "")
    if not owner_module or not all(part.isidentifier() for part in owner_module.split(".")):
        return None, ["The approved owner module is invalid."]

    target_path = Path(str(data.get("target_path") or ""))
    test_path = Path(str(data.get("test_path") or ""))
    if target_path.suffix.lower() != ".py" or test_path.suffix.lower() != ".py":
        return None, ["The approved bounded files are not Python source files."]
    revision_errors: list[str] = []
    for label, path, revision in (
        ("target", target_path, str(data.get("target_revision") or "")),
        ("test", test_path, str(data.get("test_revision") or "")),
    ):
        actual = _sha1_file(path)
        if not revision or actual != revision:
            revision_errors.append(
                f"The approved {label} file changed after indexing: {path}. Refresh that file in the index and regenerate the plan."
            )
    if revision_errors:
        return None, revision_errors

    target_entries = dict(_python_symbol_source_entries(target_path))
    test_entries = dict(_python_symbol_source_entries(test_path))
    integration_symbol = str(data.get("integration_symbol") or "")
    test_anchor_symbol = str(data.get("test_anchor_symbol") or "")
    integration_source = target_entries.get(integration_symbol, "")
    test_anchor_source = test_entries.get(test_anchor_symbol, "")
    if not integration_source or not test_anchor_source:
        return None, ["An approved symbol boundary is no longer present in its exact file."]
    return ProjectEditLeafWorkUnits(
        helper_name=helper_name,
        target_path=str(target_path.resolve()),
        integration_symbol=integration_symbol,
        integration_source=integration_source,
        test_path=str(test_path.resolve()),
        test_anchor_symbol=test_anchor_symbol,
        test_anchor_source=test_anchor_source,
        owner_module=owner_module,
        target_revision=str(data.get("target_revision") or ""),
        test_revision=str(data.get("test_revision") or ""),
    ), []


def build_project_edit_plan_from_leaf_work_units(
    prompt: str,
    work_units: ProjectEditLeafWorkUnits,
) -> ProjectEditPlan:
    """Rehydrate the minimal grounded plan needed by approved execution."""

    target = Path(work_units.target_path)
    module_parts = work_units.owner_module.split(".")
    project_root = target.parents[max(0, len(module_parts) - 1)]
    best_target = {
        "path": work_units.target_path,
        "score": 100,
        "index_revision": work_units.target_revision,
        "symbols": [{
            "path": work_units.target_path,
            "name": work_units.integration_symbol.rsplit(".", 1)[-1],
            "qualname": work_units.integration_symbol,
            "kind": "function",
            "source": work_units.integration_source,
        }],
        "chunks": [],
    }
    discovery = {
        "question": prompt,
        "terms": sorted(_leaf_ranking_terms(prompt)),
        "scope": "approved_snapshot",
        "project_roots": [str(project_root)],
        "active_path": work_units.target_path,
        "best_target": best_target,
        "candidates": [best_target, {
            "path": work_units.test_path,
            "score": 90,
            "index_revision": work_units.test_revision,
            "symbols": [{
                "path": work_units.test_path,
                "name": work_units.test_anchor_symbol.rsplit(".", 1)[-1],
                "qualname": work_units.test_anchor_symbol,
                "kind": "method",
                "source": work_units.test_anchor_source,
            }],
            "chunks": [],
        }],
        "confidence": "high",
        "evidence_mode": "approved_index_handoff",
        "index_revision": work_units.target_revision,
    }
    intelligence = _lightweight_project_edit_intelligence_packet(prompt, discovery)
    adaptive = build_code_agent_adaptive_plan(
        prompt,
        discovery=discovery,
        active_path=work_units.target_path,
        intelligence_packet=intelligence,
    )
    from tech_connector.services.project_service import build_project_edit_target_prompt, format_edit_target_context

    context = format_edit_target_context(discovery)
    return ProjectEditPlan(
        prompt=prompt,
        active_path=work_units.target_path,
        discovery=discovery,
        discovery_context=context,
        intelligence_packet=intelligence,
        adaptive_plan=adaptive,
        success_contract=list(adaptive.get("success_contract") or []),
        model_prompt=build_project_edit_target_prompt(
            question=prompt,
            discovery_context=context,
            active_path=work_units.target_path,
        ),
        stages=[_stage("approved_handoff", "Restored approved indexed work units")],
    )


def build_project_edit_leaf_stage(
    work_units: ProjectEditLeafWorkUnits,
    *,
    kind: str,
    attempt: int,
    objective: str,
    approved_plan: str,
    dependency_source: str = "",
) -> ProjectEditPromptStage:
    """Build one source-only subagent task with no file mutation authority."""

    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"define", "integrate", "test"}:
        raise ValueError(f"Unsupported project edit leaf task: {kind}")
    if normalized_kind in {"define", "test"}:
        profile = "micro" if attempt <= 1 else "small"
    else:
        profile = "small" if attempt <= 1 else "standard"
    budgets = {
        "define": (4096, 700, 75),
        "integrate": (6144, 1500, 120),
        "test": (5120, 950, 90),
    }
    num_ctx, num_predict, timeout = budgets[normalized_kind]
    exact_source = (
        work_units.integration_source
        if normalized_kind in {"define", "integrate"}
        else work_units.test_anchor_source
    )
    collection_contract = ""
    if _objective_requires_validation_result_collection(objective):
        collection_contract = (
            " The helper receives validation-result dictionaries directly, not ProjectEditApplyResult or another "
            "wrapper object, and returns a list of individual human-readable failure lines, not a joined report "
            "string. Use precise built-in collection annotations equivalent to list[dict[str, object]] and "
            "list[str]. Exclude entries whose ok value is true. The integration function must pass its validation "
            "collection to the helper."
        )
    task_instructions = {
        "define": (
            f"Return only one complete top-level function named {work_units.helper_name}. "
            "Give it a useful docstring and type-aware interface. It must implement the requested behavior "
            "without imports, placeholders, ellipses, or unrelated helpers. Use built-in list and dict "
            "annotations rather than typing.List or typing.Dict. Do not use f-strings; use str(), concatenation, "
            "or format() so dictionary-key quotes cannot corrupt the generated source."
            + collection_contract
        ),
        "integrate": (
            f"Return a complete replacement for {work_units.integration_symbol}. Preserve its signature, "
            f"docstring, and unrelated behavior, and make the smallest edit that calls {work_units.helper_name}. "
            "Do not add imports or any other function."
            + collection_contract
        ),
        "test": (
            f"Return one complete unittest method whose name starts with test_. Directly exercise "
            f"{work_units.helper_name} with focused success and failure-shaped inputs. Use the existing test style, "
            "but do not include a class wrapper, imports, placeholders, or unrelated tests. Your first non-whitespace "
            "text must be def test_ and the response must contain exactly that one method."
        ),
    }[normalized_kind]
    prompt = f"""User objective:
{objective}

Approved implementation plan:
{_trim_text(approved_plan, 3500)}

Exact existing source boundary:
```python
{exact_source}
```

Dependency source produced by an earlier bounded worker:
```python
{dependency_source or '(none)'}
```

Bounded task:
{task_instructions}

Return raw Python source only, with no JSON, Markdown fences, or explanation.
The source must parse independently after dedenting. You do not own files, imports, composition, or writes.
"""
    return ProjectEditPromptStage(
        key=f"leaf_{normalized_kind}_{attempt}",
        label=f"Generating bounded {normalized_kind} work unit ({attempt}/2)",
        system_prompt=(
            "You are a bounded Python code subagent. Produce only the requested leaf source. "
            "The deterministic integrator owns files, imports, composition, and validation."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=num_ctx if profile in {"micro", "small"} else max(num_ctx, 6144),
        num_predict=num_predict,
        timeout=timeout,
        no_progress_seconds=15,
        prefer_coder=True,
        coder_preference=profile,
        response_format="",
    )


def parse_project_edit_leaf_source(
    response: str,
    *,
    kind: str,
    expected_symbol: str,
    required_reference: str = "",
    objective: str = "",
) -> tuple[str, list[str]]:
    """Validate a source-only worker result before deterministic composition."""

    text = str(response or "").strip()
    source: str | None = None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            return "", [f"Leaf {kind} response was not valid JSON: {exc}"]
        source = payload.get("source") if isinstance(payload, dict) else None
    else:
        source = re.sub(r"^```(?:python|py)?\s*", "", text, flags=re.IGNORECASE)
        source = re.sub(r"\s*```$", "", source)
    if not isinstance(source, str) or not source.strip():
        return "", [f"Leaf {kind} response did not contain source."]
    source = textwrap.dedent(source).strip("\r\n")
    try:
        tree = ast.parse(source, filename=f"<project-edit-{kind}>")
        compile(tree, f"<project-edit-{kind}>", "exec")
    except (SyntaxError, ValueError) as exc:
        return "", [f"Leaf {kind} source did not parse and compile: {exc}"]

    if kind == "test":
        unwrapped = _unwrap_single_test_method(
            source,
            tree,
            required_reference=required_reference,
        )
        if unwrapped:
            source = unwrapped
            tree = ast.parse(source, filename="<project-edit-test>")

    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    non_definitions = [node for node in tree.body if node not in definitions]
    if len(definitions) != 1 or non_definitions:
        return "", [f"Leaf {kind} source must contain exactly one function and no imports or extra statements."]
    function = definitions[0]
    expected_name = str(expected_symbol or "").rsplit(".", 1)[-1]
    if kind == "test":
        if not function.name.startswith("test_"):
            return "", ["Leaf test source must define one test_* method."]
    elif function.name != expected_name:
        return "", [f"Leaf {kind} source defined {function.name}, expected {expected_name}."]
    if kind == "define" and not ast.get_docstring(function):
        return "", [f"Leaf definition {expected_name} needs a useful docstring."]
    if any(isinstance(node, ast.Pass) for node in ast.walk(function)) or any(
        isinstance(node, ast.Constant) and node.value is Ellipsis for node in ast.walk(function)
    ):
        return "", [f"Leaf {kind} source contained a placeholder body."]
    if required_reference and not _ast_references_name(function, required_reference):
        return "", [f"Leaf {kind} source did not reference required symbol {required_reference}."]
    contract_errors = _validate_project_edit_leaf_objective_contract(
        function,
        kind=kind,
        objective=objective,
        required_reference=required_reference,
    )
    if contract_errors:
        return "", contract_errors
    return source, []


def build_project_edit_leaf_candidate(
    work_units: ProjectEditLeafWorkUnits,
    *,
    helper_source: str,
    integration_source: str,
    test_source: str,
) -> str:
    """Compose validated leaf sources into one typed, preview-only candidate."""

    changes = [
        {
            "action": "insert_before_symbol",
            "path": work_units.target_path,
            "target_symbol": work_units.integration_symbol,
            "original_content": "",
            "new_content": helper_source,
        },
        {
            "action": "replace_symbol",
            "path": work_units.target_path,
            "target_symbol": work_units.integration_symbol,
            "original_content": "",
            "new_content": integration_source,
        },
        {
            "action": "ensure_import",
            "path": work_units.test_path,
            "target_symbol": work_units.owner_module,
            "original_content": "",
            "new_content": work_units.helper_name,
        },
        {
            "action": "insert_after_symbol",
            "path": work_units.test_path,
            "target_symbol": work_units.test_anchor_symbol,
            "original_content": "",
            "new_content": test_source,
        },
    ]
    return json.dumps(
        {
            "changes": changes,
            "report": {
                "changed": [work_units.helper_name, work_units.integration_symbol],
                "reused": [work_units.test_anchor_symbol],
                "verification": ["parse", "compile", "focused unittest"],
                "remaining_gaps": [],
            },
            "blocked_reason": "",
        },
        ensure_ascii=True,
    )


def model_for_project_edit_stage(
    stage: ProjectEditPromptStage,
    settings: dict[str, Any] | None = None,
    *,
    selected_model: str | None = None,
) -> str:
    """Return the configured model for a project-edit stage.

    Reuses the existing router model tier settings instead of defining another
    model-routing table. Context-heavy planning stages can use a smaller plan
    model while patch/code generation can reserve the coder model.
    """

    settings = dict(settings or {})
    tier = (stage.model_tier or "").strip()
    if tier == "local_plan":
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
    elif tier == "local_deep":
        model = settings.get("router_local_deep") or settings.get("model") or selected_model
    elif tier == "local_fast":
        model = settings.get("router_fast_llm_model") or settings.get("router_local_plan") or settings.get("general_model")
    elif tier == "local_code":
        from tech_connector.services.ollama_service import code_model_for_profile

        profile = str(stage.coder_preference or "small").strip().lower()
        model = (
            settings.get(f"router_local_code_{profile}")
            or settings.get(f"code_model_{profile}")
            or code_model_for_profile(profile)
            or settings.get("router_local_code")
            or settings.get("code_model")
        )
    else:
        model = None
    return str(model or selected_model or settings.get("model") or "ollama:qwen2.5-coder:14b")


def _compact_discovery_evidence(plan: ProjectEditPlan) -> str:
    discovery = dict(plan.discovery or {})
    lines = [
        f"Active path: {plan.active_path or '(none)'}",
        f"Target confidence: {discovery.get('confidence') or 'unknown'}",
    ]
    best = discovery.get("best_target")
    if isinstance(best, dict) and best:
        lines.append("Best target:")
        lines.append(_format_candidate_line(best))
    candidates = [item for item in discovery.get("candidates") or [] if isinstance(item, dict)]
    if candidates:
        lines.append("Top candidates:")
        for item in candidates[:5]:
            lines.append(_format_candidate_line(item))
    if not best and not candidates:
        context = _trim_text(plan.discovery_context, 1800)
        if context:
            lines.append("Discovery context:")
            lines.append(context)
    return "\n".join(lines)


def _format_candidate_line(item: dict[str, Any]) -> str:
    name = item.get("name") or item.get("symbol") or item.get("label") or "(unnamed)"
    kind = item.get("kind") or item.get("type") or ""
    path = item.get("path") or item.get("file") or ""
    line = item.get("line") or item.get("lineno") or ""
    summary = str(item.get("summary") or item.get("signature") or item.get("text") or "")
    location = f"{path}:{line}" if path and line else str(path or "")
    parts = [str(name)]
    if kind:
        parts.append(f"kind={kind}")
    if location:
        parts.append(f"location={location}")
    if summary:
        parts.append(f"summary={_trim_text(summary, 220)}")
    symbols = item.get("symbols") or []
    symbol_names = [
        str(symbol.get("name") if isinstance(symbol, dict) else symbol).strip()
        for symbol in symbols[:8]
    ]
    symbol_names = [name for name in symbol_names if name]
    if symbol_names:
        parts.append(f"symbols={', '.join(symbol_names)}")
    return "- " + " | ".join(parts)


def _compact_indexed_import_context(imports: list[dict[str, Any]], *, max_chars: int = 900) -> str:
    """Render useful import evidence already captured by the project index."""

    lines: list[str] = []
    for item in imports:
        raw = str(item.get("import_name") or "").strip()
        if not raw:
            module = str(item.get("module") or "").strip()
            name = str(item.get("name") or "").strip()
            alias = str(item.get("alias") or "").strip()
            if module and name:
                raw = f"from {'.' * int(item.get('level') or 0)}{module} import {name}"
            elif module:
                raw = f"import {module}"
            if alias:
                raw += f" as {alias}"
        if raw in lines:
            continue
        if lines and len("\n".join(lines + [raw])) > max_chars:
            lines.append("# Additional existing imports omitted from this compact context.")
            break
        lines.append(raw)
    return "\n".join(lines)


def _focused_project_edit_source_context(plan: ProjectEditPlan, *, max_chars: int) -> str:
    """Return ranked indexed source excerpts without reading or parsing files."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    target_path = Path(str(best_target.get("path") or plan.active_path or ""))
    if target_path.suffix.lower() != ".py":
        return ""
    roots = [Path(str(root)) for root in discovery.get("project_roots") or [] if str(root).strip()]
    paths = [target_path]
    for root in roots:
        test_path = root / "tests" / f"test_{target_path.stem}.py"
        paths.append(test_path)
        break

    raw_terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", plan.prompt or "")
    terms: set[str] = set()
    ignored = {
        "add", "agent", "apply", "changes", "concise", "coverage", "dictionaries", "edit",
        "focused", "function", "human", "named", "only", "preview", "produce", "project",
        "readable", "reported", "result", "returns", "reusable", "reuse", "service",
        "unittest", "where",
    }
    for raw in raw_terms:
        for term in raw.lower().split("_"):
            if len(term) >= 4 and term not in ignored:
                terms.add(term)
    terms.update({"validation", "failure", "error", "report"})

    from tech_connector.services.file_index_service import file_index_service

    ranked: list[tuple[int, str, int, str]] = []
    source_headers: list[tuple[str, str]] = []
    for path in paths:
        snapshot = file_index_service.get_file_snapshot(str(path), symbol_limit=500)
        if snapshot is None:
            continue
        indexed_path = str(snapshot.get("path") or path)
        header = _compact_indexed_import_context(list(snapshot.get("imports") or []))
        if header and len(header) <= 1800:
            source_headers.append((indexed_path, header))
        for symbol in snapshot.get("symbols") or []:
            if str(symbol.get("kind") or "").lower() not in {
                "function", "async_function", "method", "async_method", "class"
            }:
                continue
            segment = str(symbol.get("source") or "")
            name = str(symbol.get("name") or "")
            lowered_name = name.lower()
            lowered_segment = segment.lower()
            score = sum(8 for term in terms if term in lowered_name)
            score += sum(min(lowered_segment.count(term), 3) for term in terms)
            if terms.intersection({"error", "failure", "report", "validation"}) and any(
                marker in lowered_name for marker in ("format", "render", "report", "summarize")
            ):
                score += 12
            if Path(indexed_path) != target_path:
                score += 2
            if score:
                ranked.append((score, indexed_path, int(symbol.get("start_line") or 1), segment))

    lines: list[str] = []
    for path, header in source_headers:
        block = f"Import summary: {path}\n```python\n{header}\n```"
        if not lines or len("\n\n".join(lines + [block])) <= max_chars:
            lines.append(block)
    included_test_excerpts = 0
    for _score, path, line, segment in sorted(ranked, key=lambda item: (-item[0], item[1], item[2])):
        is_test_excerpt = Path(path) != target_path
        if is_test_excerpt and included_test_excerpts >= 1:
            continue
        excerpt = segment if len(segment) <= 1800 else _trim_text(segment, 1800)
        block = f"File: {path}:{line}\n```python\n{excerpt}\n```"
        if lines and len("\n\n".join(lines + [block])) > max_chars:
            continue
        lines.append(block)
        if is_test_excerpt:
            included_test_excerpts += 1
        if len(lines) >= 5:
            break
    return _trim_text("\n\n".join(lines), max_chars)


def _project_edit_requires_patch(prompt: str) -> bool:
    lower = (prompt or "").lower()
    if re.search(r"\b(do not edit|do not change|do not make changes|don't edit|no edits|without editing|explain how|plan only)\b", lower):
        return False
    if re.search(r"\b(what functions|which functions|where is|where are|list|show|explain|summarize|inspect|identify|determine|report what you find)\b", lower) and not re.search(
        r"\b(then|after that|and add|and create|implement|patch|modify|change|update|fix|wire|connect|build it|make it)\b",
        lower,
    ):
        return False
    return bool(
        re.search(
            r"\b(add|create|write|generate|implement|insert|improve|refactor|fix|update|patch|wire|connect|repair|make|build)\b",
            lower,
        )
    )


def preview_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    request_prompt: str = "",
) -> ProjectEditApplyResult:
    """Parse and resolve model-produced file changes without writing them."""

    changes, errors = _resolve_model_changes(model_response, project_root=project_root)
    validation = _validate_candidate_changes(
        changes,
        project_root=project_root,
        request_prompt=request_prompt,
    ) if changes and not errors else []
    validation_errors = [
        str(item.get("message") or item.get("check") or "Candidate quality validation failed.")
        for item in validation
        if not item.get("ok")
    ]
    errors.extend(validation_errors)
    return ProjectEditApplyResult(
        ok=not errors and bool(changes),
        status="preview_ready" if changes and not errors else "preview_failed",
        changes=changes,
        validation=validation,
        errors=errors or ([] if changes else ["No <modify_file> or <create_file> changes found."]),
    )


def project_edit_preview_error_score(errors: list[str]) -> int:
    """Rank candidate failures so a nearly complete patch beats malformed output."""

    score = 0
    for error in errors:
        lowered = str(error or "").lower()
        if any(marker in lowered for marker in ("json did not parse", "syntax validation failed", "did not parse")):
            score += 100
        elif any(marker in lowered for marker in ("requested public symbols", "cannot import its requested")):
            score += 70
        elif any(marker in lowered for marker in ("symbol was not found", "cannot resolve", "missing file")):
            score += 50
        elif any(marker in lowered for marker in ("docstring", "focused test file")):
            score += 5
        elif "import" in lowered:
            score += 20
        else:
            score += 30
    return score


def project_edit_has_core_contract_failure(errors: list[str], request_prompt: str) -> bool:
    """Return whether a candidate failed to define a specifically requested symbol."""

    requested = {name.lower() for name in _requested_public_symbol_names(request_prompt)}
    for error in errors:
        lowered = str(error or "").lower()
        if any(
            marker in lowered
            for marker in (
                "requested public symbols",
                "cannot import its requested implementation from itself",
            )
        ):
            return True
        unresolved_requested_symbol = any(name in lowered for name in requested) and any(
            marker in lowered
            for marker in (
                "symbol was not found",
                "could not resolve symbol",
                "cannot resolve",
            )
        )
        if unresolved_requested_symbol:
            return True
    return False


def apply_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    validate: bool = True,
    request_prompt: str = "",
) -> ProjectEditApplyResult:
    """Apply model-produced XML file changes, save undo, and run validation."""

    preview = preview_project_edit_agent_response(
        model_response,
        project_root=project_root,
        request_prompt=request_prompt,
    )
    if not preview.ok:
        return preview

    pending = {
        item["path"]: {
            "action": item["action"],
            "original_content": item.get("before", ""),
            "new_content": item.get("after", ""),
            "current": item.get("after", ""),
        }
        for item in preview.changes
    }

    change_session_path = ""
    try:
        from tech_connector.services.change_history_service import create_change_session, save_change_session

        session = create_change_session(pending, summary="Project Edit Agent changes")
        change_session_path = str(save_change_session(session))
    except Exception as exc:
        preview.errors.append(f"Could not save undo session: {exc}")
        return ProjectEditApplyResult(
            ok=False,
            status="undo_session_failed",
            changes=preview.changes,
            errors=preview.errors,
        )

    write_errors: list[str] = []
    written: list[dict[str, Any]] = []
    for item in preview.changes:
        path = Path(item["path"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.get("after", ""), encoding="utf-8")
            written.append(item)
        except Exception as exc:
            write_errors.append(f"{path}: {exc}")

    validation = _validate_changes(written, project_root=project_root) if validate else []
    validation_failed = [item for item in validation if not item.get("ok")]
    ok = not write_errors and not validation_failed
    return ProjectEditApplyResult(
        ok=ok,
        status="applied" if ok else "applied_with_validation_errors",
        changes=written,
        validation=validation,
        change_session_path=change_session_path,
        errors=write_errors + [str(item.get("message")) for item in validation_failed],
    )


def render_project_edit_agent_report(result: ProjectEditApplyResult) -> str:
    """Render a concise Codex-style report for chat."""

    lines = [
        "Project Edit Agent Report",
        f"Status: {result.status}",
        f"Outcome: {'complete' if result.ok else 'needs attention'}",
        "",
        "Files:",
    ]
    if not result.changes:
        lines.append("- No file changes were applied.")
    for item in result.changes:
        before = item.get("before", "")
        after = item.get("after", "")
        delta = _line_delta(before, after)
        lines.append(f"- {item.get('action')} {item.get('path')} ({delta})")
    if result.change_session_path:
        lines.extend(["", f"Undo session: {result.change_session_path}"])
    if result.validation:
        lines.append("")
        lines.append("Validation:")
        for item in result.validation:
            label = "passed" if item.get("ok") else "failed"
            lines.append(f"- {label}: {item.get('command') or item.get('path')} - {item.get('message')}")
    if result.errors:
        lines.append("")
        lines.append("Warnings / Errors:")
        lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines)


def validate_project_edit_paths(paths: list[str]) -> list[dict[str, Any]]:
    """Validate changed files using the same checks as the project edit agent."""

    return _validate_changes([{"path": path} for path in paths])


def _resolve_model_changes(
    model_response: str,
    *,
    project_root: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from tech_connector.knowledge.search import parse_multi_file_changes, replace_content_resilient

    changes, errors, structured = _parse_structured_project_changes(
        model_response,
        project_root=project_root,
    )
    if not structured:
        changes = parse_multi_file_changes(model_response or "", project_root or "")
    states: dict[str, dict[str, Any]] = {}
    for change in changes:
        action = str(change.get("action") or "")
        path = str(change.get("path") or "")
        if not path:
            errors.append("Change is missing a path.")
            continue
        if action == "create":
            states[path] = {
                "action": "create",
                "path": path,
                "before": "",
                "after": str(change.get("new_content") or ""),
            }
            continue
        p = Path(path)
        if not p.exists():
            errors.append(f"Cannot modify missing file: {path}")
            continue
        state = states.get(path)
        if state is None:
            before = p.read_text(encoding="utf-8", errors="replace")
            state = {"action": "modify", "path": path, "before": before, "after": before}
            states[path] = state
        current = str(state.get("after") or "")
        if action == "ensure_import":
            if p.suffix.lower() != ".py":
                errors.append(f"Cannot ensure a Python import in a non-Python file: {path}")
                continue
            module = str(change.get("target_symbol") or "").strip()
            symbol = str(change.get("new_content") or "").strip()
            matched, after, error = _ensure_python_from_import(
                current,
                module=module,
                symbol=symbol,
                filename=str(p),
            )
            if not matched:
                errors.append(error or f"Could not ensure import {module}.{symbol}: {path}")
                continue
            state["after"] = after
            continue
        if action in {"replace_symbol", "insert_before_symbol", "insert_after_symbol"}:
            if p.suffix.lower() != ".py":
                errors.append(f"Cannot edit a Python symbol in a non-Python file: {path}")
                continue
            target_symbol = str(change.get("target_symbol") or "").strip()
            if not target_symbol:
                errors.append(f"{action} change is missing target_symbol: {path}")
                continue
            matched, after, error = _edit_python_symbol_source(
                current,
                target_symbol=target_symbol,
                replacement=str(change.get("new_content") or ""),
                filename=str(p),
                operation=action,
            )
            if not matched:
                errors.append(error or f"Could not resolve symbol {target_symbol}: {path}")
                continue
            state["after"] = after
            continue
        if action != "modify":
            errors.append(f"Unsupported change action for {path}: {action}")
            continue
        matched, after = replace_content_resilient(
            current,
            str(change.get("original_content") or ""),
            str(change.get("new_content") or ""),
        )
        if not matched:
            errors.append(f"Original block did not match: {path}")
            continue
        state["after"] = after
    return list(states.values()), errors


def _edit_python_symbol_source(
    source: str,
    *,
    target_symbol: str,
    replacement: str,
    filename: str,
    operation: str,
) -> tuple[bool, str, str]:
    """Edit a top-level or ``Class.method`` symbol using AST-owned boundaries."""

    if not replacement.strip():
        return False, source, f"Replacement source is empty for symbol {target_symbol}: {filename}"
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return False, source, f"Cannot resolve {target_symbol}; existing Python did not parse: {exc}"

    parts = [part for part in target_symbol.split(".") if part]
    if not parts or len(parts) > 2:
        return False, source, f"Unsupported target symbol path: {target_symbol}"
    node: ast.AST | None = next(
        (item for item in tree.body if getattr(item, "name", None) == parts[0]),
        None,
    )
    if len(parts) == 1 and node is None:
        nested_matches = [
            child
            for parent in tree.body
            if isinstance(parent, ast.ClassDef)
            for child in parent.body
            if getattr(child, "name", None) == parts[0]
        ]
        if len(nested_matches) == 1:
            node = nested_matches[0]
        elif len(nested_matches) > 1:
            return False, source, f"Bare method target is ambiguous: {target_symbol} in {filename}"
    if len(parts) == 2 and isinstance(node, ast.ClassDef):
        node = next(
            (item for item in node.body if getattr(item, "name", None) == parts[1]),
            None,
        )
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False, source, f"Indexed Python symbol was not found: {target_symbol} in {filename}"

    decorators = list(getattr(node, "decorator_list", []) or [])
    start_line = min([int(getattr(item, "lineno", node.lineno)) for item in decorators] + [int(node.lineno)])
    end_line = int(getattr(node, "end_lineno", 0) or 0)
    if end_line < start_line:
        return False, source, f"Python symbol has invalid source bounds: {target_symbol} in {filename}"
    lines = source.splitlines(keepends=True)
    start_offset = sum(len(line) for line in lines[: start_line - 1])
    end_offset = sum(len(line) for line in lines[:end_line])
    indent = " " * int(getattr(node, "col_offset", 0) or 0)
    replacement_text = textwrap.dedent(replacement).strip("\r\n")
    if indent:
        replacement_text = textwrap.indent(replacement_text, indent)
    replacement_text += "\n"
    if operation == "replace_symbol":
        return True, source[:start_offset] + replacement_text + source[end_offset:], ""
    separator = "\n" if indent else "\n\n"
    if operation == "insert_before_symbol":
        return True, source[:start_offset] + replacement_text.rstrip() + separator + source[start_offset:], ""
    if operation == "insert_after_symbol":
        return True, source[:end_offset] + separator + replacement_text.lstrip("\r\n") + source[end_offset:], ""
    return False, source, f"Unsupported Python symbol operation: {operation}"


def _ensure_python_from_import(
    source: str,
    *,
    module: str,
    symbol: str,
    filename: str,
) -> tuple[bool, str, str]:
    """Insert one validated from-import without rewriting existing imports."""

    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
        return False, source, f"Invalid import module for {filename}: {module or '(missing)'}"
    if not symbol.isidentifier():
        return False, source, f"Invalid imported symbol for {filename}: {symbol or '(missing)'}"
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return False, source, f"Cannot ensure import; existing Python did not parse: {exc}"

    matching_imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module
    ]
    if any(alias.name == symbol for node in matching_imports for alias in node.names):
        return True, source, ""

    anchors: list[ast.AST] = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    if matching_imports:
        anchor = matching_imports[-1]
    elif anchors:
        anchor = anchors[-1]
    elif tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        anchor = tree.body[0]
    else:
        anchor = None

    lines = source.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[: int(getattr(anchor, "end_lineno", 0) or 0)]) if anchor else 0
    prefix = source[:offset]
    suffix = source[offset:]
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += "\n"
    statement = f"from {module} import {symbol}\n"
    if anchor and not isinstance(anchor, (ast.Import, ast.ImportFrom)):
        statement = "\n" + statement
    if suffix and not suffix.startswith(("\n", "\r")) and not statement.endswith(("\n", "\r")):
        statement += "\n"
    return True, prefix + statement + suffix, ""


def _parse_structured_project_changes(
    model_response: str,
    *,
    project_root: str | None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Parse the typed JSON change payload used by staged local coders."""

    text = str(model_response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        return [], [], False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"Structured change JSON did not parse: {exc.msg} at line {exc.lineno}."], True
    if not isinstance(payload, dict):
        return [], ["Structured change payload must be a JSON object."], True

    raw_changes = payload.get("changes")
    if not isinstance(raw_changes, list):
        return [], ["Structured change payload is missing a changes list."], True
    errors: list[str] = []
    parsed: list[dict[str, Any]] = []
    root = Path(project_root).resolve() if project_root else None
    for index, item in enumerate(raw_changes, start=1):
        if not isinstance(item, dict):
            errors.append(f"Structured change {index} must be an object.")
            continue
        action = str(item.get("action") or "").strip().lower()
        raw_path = str(item.get("path") or "").strip()
        if action not in {
            "create",
            "modify",
            "replace_symbol",
            "insert_before_symbol",
            "insert_after_symbol",
            "ensure_import",
        }:
            errors.append(f"Structured change {index} has unsupported action: {action or '(missing)' }.")
            continue
        if not raw_path:
            errors.append(f"Structured change {index} is missing a path.")
            continue
        path = Path(raw_path)
        if not path.is_absolute() and root is not None:
            path = root / path
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path
        if action != "create" and root is not None and not resolved_path.exists():
            basename_matches = [
                candidate.resolve()
                for candidate in root.rglob(path.name)
                if candidate.is_file()
            ]
            if len(basename_matches) == 1:
                resolved_path = basename_matches[0]
            elif len(basename_matches) > 1:
                errors.append(
                    f"Structured change path is ambiguous within the project root: {raw_path}"
                )
                continue
        if root is not None:
            try:
                resolved_path.relative_to(root)
            except ValueError:
                errors.append(f"Structured change path is outside the project root: {resolved_path}")
                continue
        new_content = item.get("new_content")
        if not isinstance(new_content, str):
            errors.append(f"Structured change {index} is missing string new_content.")
            continue
        change = {
            "action": action,
            "path": str(resolved_path),
            "target_symbol": str(item.get("target_symbol") or "").strip(),
            "new_content": new_content,
        }
        if action == "modify":
            original_content = item.get("original_content")
            if not isinstance(original_content, str) or not original_content:
                errors.append(f"Structured modify change {index} is missing exact original_content.")
                continue
            change["original_content"] = original_content
        parsed.append(change)

    blocked_reason = str(payload.get("blocked_reason") or "").strip()
    if blocked_reason and not parsed:
        errors.append(f"Coder reported a blocker: {blocked_reason}")
    return parsed, errors, True


_HOST_RUNTIME_MODULES = {
    "bpy",
    "hou",
    "maya",
    "pyfbsdk",
    "substance_painter",
    "unreal",
}
_PLACEHOLDER_PUBLIC_NAMES = {
    "do_it",
    "foo",
    "bar",
    "new_class",
    "new_function",
    "placeholder",
    "stuff",
    "thing",
}


def _validate_candidate_changes(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None,
    request_prompt: str,
) -> list[dict[str, Any]]:
    """Validate generated Python in memory before a diff can be approved."""

    results: list[dict[str, Any]] = []
    candidate_sources = {
        str(Path(str(item.get("path") or "")).resolve()): str(item.get("after") or "")
        for item in changes
        if str(item.get("path") or "")
    }
    requested_symbols = _requested_public_symbol_names(request_prompt)
    available_public_symbols: set[str] = set()
    changed_test = any(_is_test_path(Path(str(item.get("path") or ""))) for item in changes)
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() != ".py":
            continue
        before = str(item.get("before") or "")
        after = str(item.get("after") or "")
        try:
            after_tree = ast.parse(after, filename=str(path))
            compile(after_tree, str(path), "exec")
            results.append(_quality_result(True, path, "syntax", "Python parses and compiles in memory."))
        except (SyntaxError, ValueError) as exc:
            results.append(_quality_result(False, path, "syntax", f"Python syntax validation failed: {exc}"))
            continue

        try:
            before_tree = ast.parse(before, filename=str(path)) if before else ast.parse("")
        except SyntaxError:
            before_tree = ast.parse("")

        before_defs = _public_definition_map(before_tree)
        after_defs = _public_definition_map(after_tree)
        if not _is_test_path(path):
            available_public_symbols.update(name.rsplit(".", 1)[-1] for name in after_defs)
        introduced = {
            name: node for name, node in after_defs.items()
            if name not in before_defs
        }
        if not _is_test_path(path):
            missing_docs = sorted(
                name for name, node in introduced.items()
                if not ast.get_docstring(node)
            )
            results.append(_quality_result(
                not missing_docs,
                path,
                "public_docstrings",
                "New public callables have docstrings."
                if not missing_docs
                else "New public callables need useful docstrings: " + ", ".join(missing_docs),
            ))
            placeholder_names = sorted(
                name for name in introduced
                if name.rsplit(".", 1)[-1].lower() in _PLACEHOLDER_PUBLIC_NAMES
            )
            results.append(_quality_result(
                not placeholder_names,
                path,
                "clear_names",
                "New public callable names are domain-specific."
                if not placeholder_names
                else "Replace placeholder public names: " + ", ".join(placeholder_names),
            ))

        before_imports = _import_specs(before_tree)
        new_imports = [spec for spec in _import_specs(after_tree) if spec not in before_imports]
        if not new_imports:
            results.append(_quality_result(True, path, "imports", "No unresolved new imports were introduced."))
        for module, level, imported_name in new_imports:
            if _is_self_import(path, module, level, project_root=project_root):
                label = "." * level + module
                results.append(_quality_result(
                    False,
                    path,
                    f"import:{label}",
                    f"A module cannot import its requested implementation from itself: {label}.",
                ))
                continue
            ok, detail = _resolve_import_spec(
                path,
                module,
                level,
                imported_name,
                project_root=project_root,
                candidate_sources=candidate_sources,
            )
            label = "." * level + module
            if imported_name and imported_name != "*":
                label += f".{imported_name}"
            results.append(_quality_result(ok, path, f"import:{label}", detail))

    missing_requested_symbols = sorted(requested_symbols - available_public_symbols)
    if requested_symbols:
        results.append({
            "ok": not missing_requested_symbols,
            "path": "",
            "check": "requested_symbols",
            "command": "candidate:requested_symbols",
            "message": (
                "Every explicitly requested public symbol exists in the candidate."
                if not missing_requested_symbols
                else "Candidate did not implement requested public symbols: "
                + ", ".join(missing_requested_symbols)
            ),
        })

    if _requires_behavior_test(request_prompt):
        results.append({
            "ok": changed_test,
            "path": "",
            "check": "behavior_tests",
            "command": "focused behavior test required",
            "message": (
                "The candidate includes focused automated test changes for the requested behavior."
                if changed_test
                else "Behavior-changing tool work must add or update a focused test file before preview approval."
            ),
        })
    return results


def _quality_result(ok: bool, path: Path, check: str, message: str) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "path": str(path),
        "check": check,
        "command": f"candidate:{check}",
        "message": message,
    }


def _public_definition_map(tree: ast.AST) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = str(node.name)
            qualified = f"{prefix}.{name}" if prefix else name
            if not name.startswith("_"):
                found[qualified] = node
            if isinstance(node, ast.ClassDef):
                walk(node.body, qualified)

    walk(list(getattr(tree, "body", []) or []))
    return found


def _import_specs(tree: ast.AST) -> list[tuple[str, int, str]]:
    specs: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            specs.extend((alias.name, 0, "") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            specs.extend((node.module or "", int(node.level or 0), alias.name) for alias in node.names)
    return list(dict.fromkeys(specs))


def _resolve_import_spec(
    target_path: Path,
    module: str,
    level: int,
    imported_name: str,
    *,
    project_root: str | None,
    candidate_sources: dict[str, str],
) -> tuple[bool, str]:
    top_level = module.split(".", 1)[0] if module else imported_name.split(".", 1)[0]
    if top_level in _HOST_RUNTIME_MODULES:
        return True, f"Host-provided runtime import is explicitly accounted for: {top_level}."
    if level == 0 and top_level in getattr(sys, "stdlib_module_names", set()):
        return True, f"Standard-library import resolved: {module or imported_name}."

    local_path = _local_module_path(
        target_path,
        module,
        level,
        project_root=project_root,
        candidate_paths=set(candidate_sources),
    )
    if local_path is not None:
        if imported_name and imported_name != "*" and local_path.suffix == ".py":
            source_override = candidate_sources.get(str(local_path.resolve()))
            if not _local_module_exports(local_path, imported_name, source_override=source_override):
                child = local_path.parent / imported_name
                child_file = child.with_suffix(".py")
                child_init = child / "__init__.py"
                if not (
                    child_file.is_file()
                    or child_init.is_file()
                    or str(child_file.resolve()) in candidate_sources
                    or str(child_init.resolve()) in candidate_sources
                ):
                    return False, f"Project-local import does not expose {imported_name!r}: {local_path}."
        return True, f"Project-local import resolved statically: {local_path}."

    if level == 0:
        try:
            if importlib.util.find_spec(top_level) is not None:
                return True, f"Installed dependency resolved: {top_level}."
        except (ImportError, AttributeError, ValueError):
            pass
    import_label = "." * level + module + (f".{imported_name}" if imported_name else "")
    return False, f"New import could not be resolved or accounted for: {import_label}."


def _local_module_path(
    target_path: Path,
    module: str,
    level: int,
    *,
    project_root: str | None,
    candidate_paths: set[str],
) -> Path | None:
    if level:
        base = target_path.parent
        for _index in range(max(0, level - 1)):
            base = base.parent
        candidate = base.joinpath(*[part for part in module.split(".") if part])
        return _existing_module_path(candidate, candidate_paths=candidate_paths)

    roots: list[Path] = []
    if project_root:
        roots.append(Path(project_root))
    package_root = target_path.parent
    while (package_root / "__init__.py").is_file():
        package_root = package_root.parent
    roots.append(package_root)
    for root in roots:
        candidate = root.joinpath(*[part for part in module.split(".") if part])
        resolved = _existing_module_path(candidate, candidate_paths=candidate_paths)
        if resolved is not None:
            return resolved
    return None


def _existing_module_path(candidate: Path, *, candidate_paths: set[str]) -> Path | None:
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if str(candidate.with_suffix(".py").resolve()) in candidate_paths:
        return candidate.with_suffix(".py")
    package_init = candidate / "__init__.py"
    if package_init.is_file() or str(package_init.resolve()) in candidate_paths:
        return package_init
    return None


def _local_module_exports(path: Path, name: str, *, source_override: str | None = None) -> bool:
    try:
        source = source_override if source_override is not None else path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name.rsplit(".", 1)[-1]) == name for alias in node.names):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                return True
    return False


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or any(part.lower() in {"test", "tests"} for part in path.parts)


def _requires_behavior_test(prompt: str) -> bool:
    lower = str(prompt or "").lower()
    if not lower:
        return False
    if re.search(r"\b(docstring|documentation|comment|comments|formatting|rename only)\b", lower):
        return False
    mutation = bool(re.search(r"\b(add|build|create|fix|implement|improve|patch|refactor|repair|update|wire)\b", lower))
    behavior = bool(re.search(r"\b(behavior|class|feature|function|functionality|helper|method|pipeline|tool|ui|workflow)\b", lower))
    if mutation and re.search(r"\b(test|tests|unittest|coverage)\b", lower):
        return True
    return mutation and behavior


def _requested_public_symbol_names(prompt: str) -> set[str]:
    text = str(prompt or "")
    patterns = (
        r"\b(?:function|class|method|helper)\s+(?:named|called)\s+`?([A-Za-z_]\w*)`?",
        r"\b(?:add|create|implement)\s+(?:a\s+)?(?:new\s+)?(?:function|class|method|helper)\s+`?([A-Za-z_]\w*)`?",
    )
    return {
        match.group(1)
        for pattern in patterns
        for match in re.finditer(pattern, text, flags=re.IGNORECASE)
    }


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _python_symbol_source_entries(path: Path) -> list[tuple[str, str]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return []
    entries: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entries.append((node.name, ast.get_source_segment(source, node) or ""))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entries.append((f"{node.name}.{child.name}", ast.get_source_segment(source, child) or ""))
    return [(name, segment) for name, segment in entries if segment.strip()]


def _indexed_symbol_source_entries(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    """Return callable boundaries already captured by the project index."""

    entries: list[tuple[str, str]] = []
    for item in snapshot.get("symbols") or []:
        kind = str(item.get("kind") or "").lower()
        if kind not in {"function", "async_function", "method", "async_method"}:
            continue
        name = str(item.get("qualname") or item.get("name") or "").strip()
        source = str(item.get("source") or "").strip()
        if name and source:
            entries.append((name, source))
    return entries


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _project_edit_leaf_handoff_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _select_leaf_integration_symbol(
    entries: list[tuple[str, str]],
    *,
    approved_plan: str,
    objective: str,
) -> tuple[str, str] | None:
    lowered_plan = str(approved_plan or "").lower()
    lowered_objective = str(objective or "").lower()
    terms = _leaf_ranking_terms(objective)
    ranked: list[tuple[int, int, int, str, str]] = []
    for name, source in entries:
        bare_name = name.rsplit(".", 1)[-1]
        plan_positions = [
            position for candidate in (name.lower(), bare_name.lower())
            if (position := lowered_plan.find(candidate)) >= 0
        ]
        objective_positions = [
            position for candidate in (name.lower(), bare_name.lower())
            if (position := lowered_objective.find(candidate)) >= 0
        ]
        if not plan_positions and not objective_positions:
            continue
        lowered_source = source.lower()
        relevance = sum(12 for term in terms if term in bare_name.lower())
        relevance += sum(min(lowered_source.count(term), 4) for term in terms)
        explicit_objective = 1 if objective_positions else 0
        first_position = min(objective_positions or plan_positions)
        ranked.append((explicit_objective, relevance, -first_position, name, source))
    if not ranked:
        return None
    _objective, _relevance, _position, name, source = max(ranked)
    return name, source


def _select_leaf_test_anchor(
    entries: list[tuple[str, str]],
    *,
    approved_plan: str,
    objective: str,
    helper_name: str,
    integration_symbol: str,
) -> tuple[str, str] | None:
    if not entries:
        return None
    lowered_plan = str(approved_plan or "").lower()
    terms = _leaf_ranking_terms(" ".join((objective, helper_name, integration_symbol)))
    integration_name = integration_symbol.rsplit(".", 1)[-1].lower()
    ranked: list[tuple[int, str, str]] = []
    for name, source in entries:
        bare_name = name.rsplit(".", 1)[-1]
        lowered_source = source.lower()
        score = 200 if name.lower() in lowered_plan or bare_name.lower() in lowered_plan else 0
        if integration_name and re.search(rf"\b{re.escape(integration_name)}\b", lowered_source):
            score += 300
        score += sum(12 for term in terms if term in bare_name.lower())
        score += sum(min(lowered_source.count(term), 4) for term in terms)
        ranked.append((score, name, source))
    _score, name, source = max(ranked)
    return name, source


def _leaf_ranking_terms(text: str) -> set[str]:
    ignored = {
        "accepts", "actual", "after", "apply", "changes", "concise", "coverage", "dictionaries",
        "focused", "function", "human", "named", "only", "preview", "produce", "readable", "returns",
        "reusable", "reuse", "unittest", "where", "with",
    }
    return {
        term.lower()
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(text or ""))
        if term.lower() not in ignored
    }


def _ast_references_name(node: ast.AST, name: str) -> bool:
    return any(
        (isinstance(child, ast.Name) and child.id == name)
        or (isinstance(child, ast.Attribute) and child.attr == name)
        for child in ast.walk(node)
    )


def _unwrap_single_test_method(
    source: str,
    tree: ast.Module,
    *,
    required_reference: str = "",
) -> str:
    """Extract one relevant generated test from an unnecessary class wrapper."""

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not classes:
        return ""
    methods = [
        node
        for class_node in classes
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    relevant = [
        method for method in methods
        if not required_reference or _ast_references_name(method, required_reference)
    ]
    if len(relevant) != 1:
        return ""
    segment = ast.get_source_segment(source, relevant[0]) or ""
    return textwrap.dedent(segment).strip("\r\n")


def _objective_requires_validation_result_collection(objective: str) -> bool:
    lowered = str(objective or "").lower()
    return (
        "validation" in lowered
        and bool(re.search(r"\b(dict|dictionaries|results?)\b", lowered))
        and bool(re.search(r"\b(lines?|messages?)\b", lowered))
    )


def _validate_project_edit_leaf_objective_contract(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    kind: str,
    objective: str,
    required_reference: str,
) -> list[str]:
    if not _objective_requires_validation_result_collection(objective):
        return []
    if kind == "define":
        positional = list(function.args.posonlyargs) + list(function.args.args)
        if not positional:
            return ["Leaf definition must accept validation result dictionaries directly."]
        parameter = positional[0]
        annotation = ast.unparse(parameter.annotation).lower() if parameter.annotation is not None else ""
        return_annotation = ast.unparse(function.returns).lower() if function.returns is not None else ""
        if "projecteditapplyresult" in annotation or any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == parameter.arg
            and node.attr == "validation"
            for node in ast.walk(function)
        ):
            return ["Leaf definition must accept validation dictionaries, not a result wrapper object."]
        if annotation and "dict" not in annotation:
            return ["Leaf definition needs a precise collection-of-dictionaries input annotation."]
        if return_annotation and "str" in return_annotation and not any(
            collection in return_annotation for collection in ("list", "sequence", "iterable", "tuple")
        ):
            return ["Leaf definition must return individual failure lines as a collection, not one string."]
        if return_annotation and not (
            "str" in return_annotation
            and any(collection in return_annotation for collection in ("list", "sequence", "iterable", "tuple"))
        ):
            return ["Leaf definition needs a precise collection-of-string-lines return annotation."]
        if any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "join"
            for node in ast.walk(function)
        ):
            return ["Leaf definition must return individual failure lines, not a joined report string."]
        if not _ast_has_validation_failure_filter(function):
            return ["Leaf definition must exclude validation entries whose ok value is true."]
    if kind == "integrate" and required_reference:
        wrapper_parameters = {
            arg.arg
            for arg in list(function.args.posonlyargs) + list(function.args.args)
            if arg.annotation is not None
            and "projecteditapplyresult" in ast.unparse(arg.annotation).lower()
        }
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name) and node.func.id == required_reference
                or isinstance(node.func, ast.Attribute) and node.func.attr == required_reference
            )
        ]
        if calls and all(
            call.args
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in wrapper_parameters
            for call in calls
        ):
            return ["Leaf integration must pass the validation collection, not its wrapper parameter."]
    return []


def _ast_has_validation_failure_filter(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    def references_ok(node: ast.AST) -> bool:
        return any(
            (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "get"
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and child.args[0].value == "ok"
            )
            or (
                isinstance(child, ast.Subscript)
                and isinstance(child.slice, ast.Constant)
                and child.slice.value == "ok"
            )
            for child in ast.walk(node)
        )

    if any(isinstance(node, ast.If) and references_ok(node.test) for node in ast.walk(function)):
        return True
    return any(
        references_ok(condition)
        for node in ast.walk(function)
        if isinstance(node, ast.comprehension)
        for condition in node.ifs
    )


def _is_self_import(
    target_path: Path,
    module: str,
    level: int,
    *,
    project_root: str | None,
) -> bool:
    if level or not module:
        return False
    try:
        root = Path(project_root).resolve() if project_root else target_path.parent.resolve()
        relative = target_path.resolve().relative_to(root).with_suffix("")
    except (OSError, ValueError):
        return False
    current_module = ".".join(relative.parts)
    return module == current_module


def _validate_changes(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    test_paths: list[Path] = []
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if path.suffix.lower() != ".py":
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            results.append(
                {
                    "ok": True,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": "Python syntax check passed.",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "path": str(path),
                    "command": f"py_compile {path.name}",
                    "message": str(exc),
                }
            )
        if _is_test_path(path):
            test_paths.append(path)

    for path in test_paths:
        root = Path(project_root) if project_root else path.parent
        env = os.environ.copy()
        python_paths = [str(root), str(path.parent)]
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(python_paths))
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(path.parent),
            "-p",
            path.name,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
            output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
            match = re.search(r"Ran\s+(\d+)\s+tests?", output)
            ran_tests = int(match.group(1)) if match else 0
            ok = completed.returncode == 0 and ran_tests > 0
            message = (
                f"Focused behavior tests passed ({ran_tests} test{'s' if ran_tests != 1 else ''})."
                if ok
                else f"Focused behavior test failed or ran no tests: {output[-2000:]}"
            )
        except subprocess.TimeoutExpired:
            ok = False
            message = "Focused behavior test exceeded the 120 second timeout."
        except OSError as exc:
            ok = False
            message = f"Focused behavior test could not start: {exc}"
        results.append({
            "ok": ok,
            "path": str(path),
            "command": " ".join(command),
            "message": message,
        })
    return results


def _stage(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": "completed"}


def _trim_text(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 80
    return text[:head].rstrip() + "\n\n... [middle omitted for staged prompt] ...\n\n" + text[-tail:].lstrip()


def _infer_code_agent_host(prompt: str, discovery: dict[str, Any], active_path: str | None) -> str:
    text = " ".join(
        [
            str(prompt or ""),
            str(active_path or ""),
            " ".join(str(root) for root in discovery.get("project_roots") or []),
            str((discovery.get("best_target") or {}).get("path") or ""),
        ]
    ).lower().replace("\\", "/")
    if "maya" in text or "cmds" in text or "/maya_tools/" in text:
        return "maya"
    if "unreal" in text or "blueprint" in text or "/unreal" in text:
        return "unreal"
    if "blender" in text or "/blender" in text:
        return "blender"
    if "houdini" in text:
        return "houdini"
    return "python"


def _line_delta(before: str, after: str) -> str:
    before_lines = len((before or "").splitlines())
    after_lines = len((after or "").splitlines())
    delta = after_lines - before_lines
    return f"{before_lines} -> {after_lines} lines, delta {delta:+d}"
