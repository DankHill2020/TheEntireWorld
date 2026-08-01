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

    from tech_connector.services.prompt.artifact_contract_service import restricts_live_mutation

    generated_artifact = (
        _project_edit_requires_patch(prompt)
        or _project_edit_requests_new_artifact_plan(prompt)
    ) and restricts_live_mutation(prompt)
    discovery = (
        _generated_artifact_project_discovery(prompt, active_path=active_path)
        if generated_artifact
        else _build_explicit_active_edit_discovery(
            prompt,
            active_path=active_path,
            limit=limit,
        )
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
    if not generated_artifact and _project_edit_needs_deep_intelligence(prompt, discovery):
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
        active_path=None if generated_artifact else active_path,
        generated_artifact=generated_artifact,
        live_tree_mutation_allowed=not generated_artifact,
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
    roots = [str(snapshot.get("root") or "").strip()]
    roots = [root for root in roots if root]
    project_root = Path(roots[0]).resolve() if roots else path.parent.resolve()

    def candidate_from_snapshot(indexed_snapshot: dict[str, Any], score: int) -> dict[str, Any]:
        indexed_path = str(indexed_snapshot.get("path") or "")
        symbols: list[dict[str, Any]] = []
        for indexed_symbol in indexed_snapshot.get("symbols") or []:
            symbol = dict(indexed_symbol)
            qualname = str(symbol.get("qualname") or symbol.get("name") or "")
            source = str(symbol.get("source") or "")
            relevance = sum(12 for term in terms if term in qualname.lower())
            relevance += sum(min(source.lower().count(term), 3) for term in terms)
            symbol.update({"path": indexed_path, "relevance": relevance})
            symbols.append(symbol)
        symbols.sort(key=lambda item: (-int(item.get("relevance") or 0), int(item.get("start_line") or 1)))
        return {
            "path": indexed_path,
            "score": score,
            "symbols": symbols[: max(8, int(limit or 8) * 2)],
            "chunks": [],
            "index_revision": str(indexed_snapshot.get("sha1") or ""),
        }

    candidate = candidate_from_snapshot(snapshot, 100)
    candidates = [candidate]
    named_files = list(dict.fromkeys(
        match.group(0).lower()
        for match in re.finditer(r"(?<![\w.-])[\w.-]+\.py\b", lowered)
    ))
    for filename in named_files:
        if filename == path.name.lower():
            continue
        matches = [
            Path(candidate_path)
            for candidate_path in file_index_service.find_indexed_paths_by_name(filename)
            if _path_is_within(Path(candidate_path), project_root)
            and not any(part.startswith(".") for part in Path(candidate_path).relative_to(project_root).parts)
        ]
        if len(matches) != 1:
            continue
        sibling_snapshot = file_index_service.get_file_snapshot(
            str(matches[0]),
            symbol_limit=max(24, int(limit or 8) * 4),
        )
        if sibling_snapshot is not None:
            candidates.append(candidate_from_snapshot(sibling_snapshot, 95 - len(candidates)))
    return {
        "question": prompt,
        "terms": sorted(terms)[:20],
        "scope": "active_file",
        "project_roots": roots,
        "active_path": candidate["path"],
        "best_target": candidate,
        "candidates": candidates,
        "confidence": "high",
        "evidence_mode": "explicit_index_snapshot",
        "index_revision": str(snapshot.get("sha1") or ""),
    }


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
    evidence_targets = [
        item
        for item in (plan.discovery.get("candidates") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    objective_lower = objective.lower()
    mentioned_target_count = len({
        str(item.get("path"))
        for item in evidence_targets
        if Path(str(item.get("path"))).name.lower() in objective_lower
    })
    coder_profile = choose_project_edit_coder_profile(
        prompt=objective,
        target_count=max(1, mentioned_target_count),
    )
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
        "standard": (2200, 1000, 650, 5200),
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
        "Do not invent files, APIs, imports, attributes, signatures, or call sites. Resolve required "
        "symbols lazily from generated/current code, indexed internal code, plugin/catalog source, then "
        "installed or official API evidence. Search only a specifically named unresolved gap. Every "
        "external call needs evidence for its exact qualified owner, callable member, and signature; "
        "module importability alone is not evidence that a member exists. Never emit speculative code "
        "for an unresolved gap. Work iteratively: implement what is evidenced, "
        "identify gaps, resolve them from project patterns or authoritative APIs, bridge them with real code, "
        "then validate and repeat. Completion requires working behavior, not a plausible-looking patch. "
        "During planning, never emit code, pseudocode, code fences, or replacement bodies."
    )
    quick_plan_prompt = f"""Focused exact source excerpts:
{planning_source or '(no source excerpt could be resolved)'}

User objective:
{objective}

Compact target evidence:
{compact_discovery}

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
    patch_prompt = f"""Focused exact source excerpts:
{focused_source or '(no source excerpt could be resolved)'}

User objective:
{objective}

Chosen target:
{target_path or '(none)'}

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
- Give new public functions/classes clear domain names and type-aware interfaces. Document each public callable with a behavioral summary, one `:param name:` field per public parameter, and `:return:` whenever it returns a value.
- Account for every new import. Use only standard-library, installed, project-local, or explicitly host-provided modules.
- Add or update focused unittest tests that prove the requested behavior and failure handling and can run without a live DCC by mocking host boundaries.
- Ensure all emitted Python parses and all test imports resolve before claiming completion.
- If target confidence is low or evidence is insufficient, do not invent. Return a blocker report.
- Return exactly one JSON object with this shape and no Markdown fences:
  {{"changes": [{{"action": "replace_symbol", "path": "absolute/or/relative/path.py", "target_symbol": "existing_function_or_Class.method", "original_content": "", "new_content": "complete replacement symbol source"}}], "report": {{"changed": [], "reused": [], "verification": [], "remaining_gaps": [], "requirement_coverage": []}}, "blocked_reason": ""}}
- Prefer action "replace_symbol" for Python edits. Name an exact indexed symbol and provide its complete replacement source; the AST resolver owns exact source matching and indentation.
- For replace_symbol, copy the exact existing symbol from the source excerpt and make the smallest necessary edit. Preserve its docstring, quote style, and unrelated lines.
- To add a new helper, use "insert_before_symbol" with an existing function at the same scope as target_symbol.
- To add a test method, use "insert_after_symbol" with an existing Class.method as target_symbol.
- To add one import without rewriting an import block, use "ensure_import" with the module in target_symbol and the imported name in new_content.
- For non-Python files, use replace_text/insert_before_text/insert_after_text with an exact, unique source excerpt in target_symbol. These actions are language-neutral and never interpret the anchor as a Python symbol.
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
    if (
        _project_edit_requires_patch(objective)
        or _project_edit_requests_new_artifact_plan(objective)
    ):
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


def build_project_edit_file_generation_stages(
    plan: ProjectEditPlan,
) -> list[tuple[str, str, ProjectEditPromptStage]]:
    """Build bounded full-file stages for an explicitly named multi-file edit."""

    discovery = dict(plan.discovery or {})
    if discovery.get("evidence_mode") != "explicit_index_snapshot":
        return []
    candidates = [
        item
        for item in discovery.get("candidates") or []
        if isinstance(item, dict) and Path(str(item.get("path") or "")).suffix.lower() == ".py"
    ]
    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        unique.setdefault(str(Path(str(item.get("path"))).resolve()), item)
    if len(unique) < 3:
        return []

    active = str(Path(str(discovery.get("active_path") or plan.active_path or "")).resolve())
    ordered_paths = sorted(
        unique,
        key=lambda value: (
            2 if _is_test_path(Path(value)) else 1 if value == active else 0,
            value.lower(),
        ),
    )
    stages: list[tuple[str, str, ProjectEditPromptStage]] = []
    for index, path_text in enumerate(ordered_paths, start=1):
        path = Path(path_text)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return []
        is_test = _is_test_path(path)
        stage = ProjectEditPromptStage(
            key=f"file_generation_{index}",
            label=f"Generating {path.name}",
            system_prompt=(
                "You are a bounded senior Python implementation worker. Return one complete importable Python "
                "file as raw source. Do not return JSON, Markdown, commentary, a diff, or a partial symbol."
            ),
            user_prompt=f"""User objective:
{plan.prompt}

File owned by this stage:
{path}

Exact current file:
```python
{source}
```

Task:
Return the complete final source for this file after fulfilling every part of the objective owned by it.
Preserve behavior not changed by the request. Resolve project-local imports at function scope when needed to avoid cycles.
Use clear parameter and local names. Document every public callable with a behavioral summary, one `:param name:` field per public parameter, and `:return:` whenever it returns a value.
{"Implement substantive unittest methods for every requested behavior; a pass-only test class is forbidden. Every test_* method must directly assert an explicit expected value, state transition, ordered result, callback argument sequence, or requested exception. Merely calling production code, relying on assertions inside an indirectly invoked callback, or checking only broad types is not behavioral proof." if is_test else "Implement production behavior fully; do not add placeholders, pass bodies, or speculative APIs."}
{"Call only public functions, classes, and methods visibly defined in the completed dependency context. Never invent convenience APIs for a test." if is_test else ""}
The first response character must belong to valid Python source. Return raw Python only.
""",
            model_tier="local_code",
            num_ctx=6144,
            num_predict=1300 if is_test else 1100,
            timeout=90,
            no_progress_seconds=22,
            prefer_coder=True,
            coder_preference="standard" if is_test else "small",
            response_format="",
        )
        stages.append((path_text, source, stage))
    return stages


def build_project_edit_artifact_manifest_stage(
    plan: ProjectEditPlan,
    *,
    approved_plan: str = "",
) -> ProjectEditPromptStage | None:
    """Build a bounded manifest stage for a new disposable multi-file artifact."""

    from tech_connector.services.prompt.artifact_contract_service import restricts_live_mutation

    if not (
        _project_edit_requires_patch(plan.prompt)
        or _project_edit_requests_new_artifact_plan(plan.prompt)
    ) or not restricts_live_mutation(plan.prompt):
        return None
    requirement_ledger = extract_project_edit_artifact_requirements(plan.prompt)
    artifact_requirements = [
        item for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    ]
    requirement_lines = "\n".join(
        f"- {item['id']}: {item['text']}" for item in artifact_requirements
    )
    workflow_lines = "\n".join(
        f"- {item['id']}: {item['text']}"
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "workflow"
    )
    return ProjectEditPromptStage(
        key="artifact_manifest",
        label="Designing generated file contract",
        system_prompt=(
            "You are a senior software architect defining a bounded Python artifact. "
            "Return only the requested JSON manifest. Do not emit source code or prose."
        ),
        user_prompt=f"""Original objective:
{plan.prompt}

Approved implementation plan:
{approved_plan or "(none supplied)"}

Project root:
{(plan.discovery.get("project_roots") or [""])[0]}

Define 2-5 focused Python modules and unittest files that collectively satisfy every requested behavior. Group
closely related behavior in one owner module and keep each requirement phrase concise. Put production files before
their consumers and tests last. Use project-relative paths only. Keep files
inside existing top-level source and examples test conventions. Do not use dot-prefixed folders, SQLite files,
third-party dependencies, placeholders, or live user data. Every requirement from the objective must be owned by
at least one file. Dependencies may name only another path in this manifest. Every test file must set is_test=true,
must be under tech_connector/examples/tests/, and its filename must start with test_. Production files must set
is_test=false and must not use a test_ filename.

For each production file, public_symbols must list exact public API names or signatures, contracts must state inputs,
outputs, errors, state transitions, and invariants, algorithm_steps must describe the actual implementation algorithm,
and validation_steps must identify concrete readback or test proof. Test files must name the public behavior they call,
the fixture strategy, and success/failure/recovery assertions. Every behavior requirement must be owned by at least one
production file and at least one test file. Test files may not duplicate the same requirement set and purpose.

Populate every field of the top-level integration_contracts object with the exact package-wide source of truth that
all files must obey. canonical_owners names the one file/API that owns each shared record/type/constant. signatures
contains exact callable signatures including defaults. shared_invariants contains state, bounds, and round-trip
rules. data_layout contains exact byte/file/message field order, sizes, endianness, markers, flags, and units when
relevant. errors contains shared exception and rejection behavior. These are contract statements, not a contracts.py
file proposal, and must be concrete enough that independent file workers produce compatible code without guessing.

Authoritative requirement ledger:
{requirement_lines}

Assign every requirement ID to at least one owning file in requirement_ids. Use only IDs from this ledger. The
application validates complete ID coverage and gives each worker the original requirement text, so do not merge,
drop, invent, or repeat requirement text in the JSON.

The following workflow requirements are owned and validated by the project-edit controller. Do not create files,
tests, APIs, or requirement ownership for them:
{workflow_lines or "- none"}
""",
        model_tier="local_semantic",
        num_ctx=8192,
        num_predict=3600,
        timeout=150,
        no_progress_seconds=20,
        prefer_coder=False,
        coder_preference="small",
        response_format=PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA,
    )


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
    return json.dumps(payload), []


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
            requirements.append(sentence)
        else:
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


def parse_project_edit_artifact_manifest(
    response: str,
    *,
    project_root: str,
    requirement_ledger: list[dict[str, str]] | None = None,
    strict_architecture: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate and dependency-order a generated artifact manifest."""

    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError) as exc:
        return [], [f"Artifact manifest JSON did not parse: {exc}"]
    raw_files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(raw_files, list) or len(raw_files) < 2:
        return [], ["Artifact manifest must contain focused production and test files."]
    raw_contracts = (
        payload.get("integration_contracts") if isinstance(payload, dict) else []
    ) or []
    if isinstance(raw_contracts, dict):
        integration_contracts = [
            f"{field}: {str(value).strip()}"
            for field in (
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            )
            for value in raw_contracts.get(field) or []
            if str(value).strip()
        ]
    else:
        integration_contracts = [
            str(value).strip()
            for value in raw_contracts
            if str(value).strip()
        ]
    if not integration_contracts:
        integration_contracts = list(dict.fromkeys(
            str(value).strip()
            for raw in raw_files
            if isinstance(raw, dict)
            for value in raw.get("integration_contracts") or []
            if str(value).strip()
        ))

    root = Path(project_root).resolve()
    authoritative_requirements = {
        str(item.get("id") or ""): str(item.get("text") or "")
        for item in requirement_ledger or []
        if str(item.get("id") or "") and str(item.get("text") or "")
        and str(item.get("scope") or "artifact") == "artifact"
    }
    normalized_paths: dict[str, str] = {}
    for raw in raw_files:
        item = dict(raw) if isinstance(raw, dict) else {}
        original_path = str(item.get("path") or "").replace("\\", "/").strip("/")
        path = Path(original_path)
        if path.is_absolute():
            try:
                normalized_paths[original_path] = str(path.resolve().relative_to(root)).replace("\\", "/")
                path = Path(normalized_paths[original_path])
            except ValueError:
                pass
        if (
            len(path.parts) >= 2
            and path.parts[0].lower() == "src"
            and (root / path.parts[1]).is_dir()
        ):
            normalized_paths[original_path] = str(Path(*path.parts[1:])).replace("\\", "/")
            path = Path(normalized_paths[original_path])
        declared_test = _artifact_manifest_item_is_test(item)
        if (
            declared_test
            and original_path
            and not path.is_absolute()
            and path.suffix.lower() == ".py"
            and not any(part.startswith(".") for part in path.parts)
            and tuple(part.lower() for part in path.parts[:3])
            != ("examples", "tech_connector", "tests")
        ):
            filename = path.name
            if not filename.startswith("test_"):
                filename = f"test_{filename}"
            normalized_paths[original_path] = f"tech_connector/examples/tests/{filename}"
        elif (
            not declared_test
            and original_path
            and path.parent == Path(".")
            and path.suffix.lower() == ".py"
        ):
            normalized_paths[original_path] = f"tech_connector/services/generated/{path.name}"

    files: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for raw in raw_files:
        item = dict(raw) if isinstance(raw, dict) else {}
        declared_test = _artifact_manifest_item_is_test(item)
        original_path = str(item.get("path") or "").replace("\\", "/").strip("/")
        path_text = normalized_paths.get(original_path, original_path)
        path = Path(path_text)
        if (
            not declared_test
            and path.parent == Path(".")
            and path.suffix.lower() == ".py"
        ):
            path_text = f"tech_connector/services/generated/{path.name}"
            path = Path(path_text)
        parts = path.parts
        if (
            not path_text
            or path.is_absolute()
            or path.suffix.lower() != ".py"
            or any(part.startswith(".") for part in parts)
            or any(part.lower().endswith((".sqlite", ".sqlite3", ".db")) for part in parts)
        ):
            errors.append(f"Artifact manifest has an unsafe or non-Python path: {path_text or '(empty)'}")
            continue
        resolved = (root / path).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"Artifact manifest path escapes the project root: {path_text}")
            continue
        requirements = [
            str(value).strip() for value in item.get("requirements") or [] if str(value).strip()
        ]
        requirement_ids = [
            str(value).strip() for value in item.get("requirement_ids") or [] if str(value).strip()
        ]
        if authoritative_requirements:
            requirement_ids = [
                f"R{value}" if value.isdigit() and f"R{value}" in authoritative_requirements else value
                for value in requirement_ids
            ]
            unknown_ids = [value for value in requirement_ids if value not in authoritative_requirements]
            if unknown_ids:
                errors.append(
                    f"Artifact manifest uses unknown requirement IDs ({path_text}): {', '.join(unknown_ids)}"
                )
            requirements = [
                authoritative_requirements[value]
                for value in requirement_ids
                if value in authoritative_requirements
            ]
        purpose = str(item.get("purpose") or "").strip()
        if not purpose or not requirements:
            errors.append(f"Artifact manifest file lacks purpose or owned requirements: {path_text}")
        contracts = [
            str(value).strip() for value in item.get("contracts") or [] if str(value).strip()
        ]
        algorithm_steps = [
            str(value).strip() for value in item.get("algorithm_steps") or [] if str(value).strip()
        ]
        validation_steps = [
            str(value).strip() for value in item.get("validation_steps") or [] if str(value).strip()
        ]
        public_symbols: list[str] = []
        for value in item.get("public_symbols") or []:
            raw_symbol = str(value).strip()
            if not raw_symbol:
                continue
            public_symbols.extend(
                part.strip(" '\"")
                for part in re.split(r"['\"]\s*,\s*['\"]", raw_symbol)
                if part.strip(" '\"")
            )
        inferred_test = _is_test_path(path)
        if declared_test != inferred_test:
            errors.append(
                "Artifact manifest test classification does not match its path: "
                f"{path_text}. Test files must use tech_connector/examples/tests/test_*.py with is_test=true; "
                "production files must use is_test=false."
            )
        manifest_entry = {
            "path": path_text,
            "absolute_path": str(resolved),
            "purpose": purpose,
            "requirements": requirements,
            "requirement_ids": requirement_ids,
            "public_symbols": public_symbols,
            "contracts": contracts,
            "algorithm_steps": algorithm_steps,
            "validation_steps": validation_steps,
            "integration_contracts": integration_contracts,
            "ownership_attributions": [],
            "dependency_repairs": [],
            "depends_on": [
                normalized_paths.get(
                    str(value).replace("\\", "/").strip("/"),
                    str(value).replace("\\", "/").strip("/"),
                )
                for value in item.get("depends_on") or []
                if str(value).strip()
                and str(value).split(".", 1)[0] not in set(getattr(sys, "stdlib_module_names", ()))
            ],
            "is_test": inferred_test,
        }
        existing = files.get(path_text)
        if existing is None:
            files[path_text] = manifest_entry
        elif existing["is_test"] != manifest_entry["is_test"]:
            errors.append(
                f"Artifact manifest assigns conflicting roles to one path: {path_text}"
            )
        else:
            for key in (
                "requirements",
                "requirement_ids",
                "public_symbols",
                "contracts",
                "algorithm_steps",
                "validation_steps",
                "depends_on",
            ):
                existing[key] = list(dict.fromkeys([*existing[key], *manifest_entry[key]]))
            if manifest_entry["purpose"] not in existing["purpose"]:
                existing["purpose"] += "; " + manifest_entry["purpose"]

    if strict_architecture and len(files) > 5:
        while len(files) > 5:
            role_groups = [
                [item for item in files.values() if not item["is_test"]],
                [item for item in files.values() if item["is_test"]],
            ]
            merge_group = next(
                (group for group in role_groups if len(group) > 1),
                [],
            )
            if not merge_group:
                break
            source = min(
                merge_group,
                key=lambda item: (
                    len(item["requirement_ids"]),
                    len(item["public_symbols"]),
                    item["path"],
                ),
            )
            targets = {
                item["path"]: item
                for item in merge_group
                if item is not source
            }
            target = _select_artifact_requirement_owner(
                targets,
                " ".join([
                    source["purpose"],
                    *source["requirements"],
                    *source["public_symbols"],
                ]),
            )
            source_path = source["path"]
            target_path = target["path"]
            target["purpose"] += "; " + source["purpose"]
            for key in (
                "requirements",
                "requirement_ids",
                "public_symbols",
                "contracts",
                "algorithm_steps",
                "validation_steps",
            ):
                target[key] = list(dict.fromkeys([*target[key], *source[key]]))
            target["ownership_attributions"] = [
                *target["ownership_attributions"],
                *source["ownership_attributions"],
            ]
            target["depends_on"] = list(dict.fromkeys([
                target_path if dependency == source_path else dependency
                for dependency in [*target["depends_on"], *source["depends_on"]]
                if dependency not in {source_path, target_path}
            ]))
            target["dependency_repairs"].append(
                f"Combined bounded owner {source_path} into {target_path}."
            )
            del files[source_path]
            for item in files.values():
                item["depends_on"] = list(dict.fromkeys(
                    target_path if dependency == source_path else dependency
                    for dependency in item["depends_on"]
                    if (target_path if dependency == source_path else dependency)
                    != item["path"]
                ))

    if strict_architecture:
        symbol_owners: dict[str, list[str]] = {}
        for item in files.values():
            if item["is_test"]:
                continue
            for public_symbol in item["public_symbols"]:
                symbol_name = public_symbol.split("(", 1)[0].rsplit(".", 1)[-1]
                symbol_owners.setdefault(symbol_name, []).append(item["path"])
        duplicate_owners = {
            symbol: owners
            for symbol, owners in symbol_owners.items()
            if len(set(owners)) > 1
            and symbol[:1].isupper()
        }
        if duplicate_owners:
            return [], [
                "Artifact manifest assigns one production API to multiple owners: "
                + "; ".join(
                    f"{symbol} -> {', '.join(sorted(set(owners)))}"
                    for symbol, owners in sorted(duplicate_owners.items())
                )
            ]

    if strict_architecture:
        signature_contracts = [
            value.split(":", 1)[-1].strip()
            for value in integration_contracts
            if value.startswith("signatures:")
        ]
        state_contracts = [
            value
            for value in integration_contracts
            if value.startswith(("shared_invariants:", "data_layout:", "errors:"))
        ]

        def contract_terms(value: str) -> set[str]:
            expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
            return {
                token
                for token in re.findall(r"[a-z0-9]+", expanded.lower())
                if token not in {
                    "a", "an", "and", "class", "handler", "manager",
                    "module", "object", "returns", "the",
                }
            }

        for item in files.values():
            if item["is_test"]:
                continue
            for public_symbol in item["public_symbols"]:
                symbol_name = public_symbol.split("(", 1)[0].rsplit(".", 1)[-1]
                if symbol_name.endswith(("Error", "Exception")):
                    continue
                symbol_terms = contract_terms(symbol_name)
                ranked_signatures = sorted(
                    (
                        (len(symbol_terms & contract_terms(signature)), signature)
                        for signature in signature_contracts
                    ),
                    reverse=True,
                )
                best_score = ranked_signatures[0][0] if ranked_signatures else 0
                matched = [
                    signature
                    for score, signature in ranked_signatures
                    if score > 0 and score == best_score
                ][:2]
                for signature in matched:
                    item["contracts"].append(
                        f"{symbol_name} implements exact package signature {signature}."
                    )
                    item["algorithm_steps"].append(
                        f"Implement {signature} using the accepted package state, "
                        "invariants, synchronization, and error contracts."
                    )
            if state_contracts:
                item["contracts"].append(
                    "Relevant accepted state and failure contracts: "
                    + " | ".join(state_contracts)
                )
            item["contracts"] = list(dict.fromkeys(item["contracts"]))
            item["algorithm_steps"] = list(dict.fromkeys(item["algorithm_steps"]))

    if strict_architecture:
        if not integration_contracts:
            errors.append(
                "Artifact manifest lacks package-wide integration_contracts."
            )
        else:
            path_like_contracts = [
                value
                for value in integration_contracts
                if not value.startswith("canonical_owners:")
                and (
                    value.lower().endswith(".py")
                    or re.match(r"^[A-Za-z]:[\\/]", value)
                    or (
                        ("/" in value or "\\" in value)
                        and len(value.split()) <= 3
                    )
                )
            ]
            if path_like_contracts:
                errors.append(
                    "Artifact integration_contracts contain file paths instead of executable "
                    "cross-file contracts: " + ", ".join(path_like_contracts)
                )
            contract_blob = " ".join(integration_contracts)
            if not re.search(r"\b[A-Za-z_][A-Za-z0-9_.]*\s*\([^)]*\)", contract_blob):
                errors.append(
                    "Artifact integration_contracts lack an exact callable signature with defaults."
                )
            requirement_blob = " ".join(authoritative_requirements.values()).lower()
            contract_lower = contract_blob.lower()
            required_protocol_terms = _required_project_edit_protocol_terms(
                requirement_blob
            )
            missing_protocol_terms = [
                term
                for term in required_protocol_terms
                if not _project_edit_protocol_term_present(term, contract_lower)
            ]
            if missing_protocol_terms:
                errors.append(
                    "Artifact integration_contracts omit prompt-critical protocol terms: "
                    + ", ".join(missing_protocol_terms)
                )
            if (
                any(term in requirement_blob for term in ("binary", "byte", "frame"))
                and not any(
                    term in contract_lower
                    for term in ("layout", "field order", "offset", "struct", "byte order")
                )
            ):
                errors.append(
                    "Artifact integration_contracts do not define the shared binary/data layout."
                )
        for path_text, item in files.items():
            missing_contract_parts = []
            if not item["contracts"]:
                missing_contract_parts.append("contracts")
            if not item["algorithm_steps"]:
                missing_contract_parts.append("algorithm_steps")
            if not item["validation_steps"]:
                missing_contract_parts.append("validation_steps")
            if not item["is_test"] and not item["public_symbols"]:
                missing_contract_parts.append("public_symbols")
            if missing_contract_parts:
                errors.append(
                    f"Artifact manifest lacks executable architecture details ({path_text}): "
                    + ", ".join(missing_contract_parts)
                )
    if errors:
        return [], errors
    if not any(not item["is_test"] for item in files.values()) or not any(
        item["is_test"] for item in files.values()
    ):
        return [], ["Artifact manifest must include at least one production file and one test file."]
    production_symbols = {
        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        for item in files.values()
        if not item["is_test"]
        for symbol in item["public_symbols"]
        if str(symbol).strip()
    }
    duplicated_test_symbols = sorted({
        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        for item in files.values()
        if item["is_test"]
        for symbol in item["public_symbols"]
        if str(symbol).strip()
    } & production_symbols)
    if duplicated_test_symbols:
        return [], [
            "Artifact test files must import production APIs instead of redeclaring them: "
            + ", ".join(duplicated_test_symbols)
        ]

    if authoritative_requirements:
        assigned = {
            requirement_id
            for item in files.values()
            for requirement_id in item["requirement_ids"]
        }
        missing_ids = [value for value in authoritative_requirements if value not in assigned]
        for requirement_id in missing_ids:
            requirement_text = authoritative_requirements[requirement_id]
            for owner_kind in (False, True) if strict_architecture else (None,):
                candidates = {
                    path: item
                    for path, item in files.items()
                    if owner_kind is None or bool(item["is_test"]) == owner_kind
                }
                if not candidates:
                    continue
                owner = _select_artifact_requirement_owner(candidates, requirement_text)
                owner["requirement_ids"].append(requirement_id)
                owner["requirements"].append(requirement_text)
                owner["ownership_attributions"].append({
                    "requirement_id": requirement_id,
                    "reason": "deterministic semantic ownership fallback",
                })

        if strict_architecture:
            for requirement_id in authoritative_requirements:
                requirement_text = authoritative_requirements[requirement_id]
                owners = [
                    item for item in files.values()
                    if requirement_id in item["requirement_ids"]
                ]
                if not any(not item["is_test"] for item in owners):
                    production = {
                        path: item for path, item in files.items() if not item["is_test"]
                    }
                    if production:
                        owner = _select_artifact_requirement_owner(production, requirement_text)
                        owner["requirement_ids"].append(requirement_id)
                        owner["requirements"].append(requirement_text)
                        owner["ownership_attributions"].append({
                            "requirement_id": requirement_id,
                            "reason": "missing production owner inferred deterministically",
                        })
                if not any(item["is_test"] for item in owners):
                    tests = {
                        path: item for path, item in files.items() if item["is_test"]
                    }
                    if tests:
                        owner = _select_artifact_requirement_owner(tests, requirement_text)
                        owner["requirement_ids"].append(requirement_id)
                        owner["requirements"].append(requirement_text)
                        owner["ownership_attributions"].append({
                            "requirement_id": requirement_id,
                            "reason": "missing behavioral proof owner inferred deterministically",
                        })

    if strict_architecture:
        seen_test_contracts: dict[tuple[tuple[str, ...], str], str] = {}
        for item in files.values():
            if not item["is_test"]:
                continue
            signature = (
                tuple(sorted(item["requirement_ids"])),
                " ".join(item["purpose"].lower().split()),
            )
            prior = seen_test_contracts.get(signature)
            if prior:
                errors.append(
                    "Artifact manifest duplicates test responsibility: "
                    f"{prior} and {item['path']} own the same requirement set."
                )
            else:
                seen_test_contracts[signature] = item["path"]

    for item in files.values():
        reconciled_dependencies = []
        for dependency in item["depends_on"]:
            if dependency in files:
                reconciled_dependencies.append(dependency)
                continue
            dependency_path = Path(dependency)
            matches = [
                path
                for path in files
                if Path(path).name == dependency_path.name
                or Path(path).stem == dependency_path.stem
            ]
            if len(matches) == 1:
                reconciled_dependencies.append(matches[0])
            else:
                reconciled_dependencies.append(dependency)
        item["depends_on"] = list(dict.fromkeys(reconciled_dependencies))
        if not item["is_test"]:
            item["depends_on"] = [
                dependency
                for dependency in item["depends_on"]
                if not (
                    (dependency in files and files[dependency]["is_test"])
                    or _is_test_path(Path(dependency))
                )
            ]
        unknown = [dependency for dependency in item["depends_on"] if dependency not in files]
        if unknown:
            if strict_architecture:
                item["depends_on"] = [
                    dependency
                    for dependency in item["depends_on"]
                    if dependency not in unknown
                ]
                item["dependency_repairs"].append(
                    "Collapsed absent manifest dependency into this file's owned "
                    "implementation: " + ", ".join(unknown)
                )
            else:
                errors.append(
                    f"Artifact manifest dependency is not another manifest path ({item['path']}): {', '.join(unknown)}"
                )
        item["depends_on"] = [
            dependency for dependency in item["depends_on"] if dependency != item["path"]
        ]
    production_paths = [item["path"] for item in files.values() if not item["is_test"]]
    for item in files.values():
        if item["is_test"]:
            item["depends_on"] = list(dict.fromkeys([*item["depends_on"], *production_paths]))
    if errors:
        return [], errors

    ordered: list[dict[str, Any]] = []
    pending = dict(files)
    while pending:
        ready = [
            item for item in pending.values()
            if all(dependency not in pending for dependency in item["depends_on"])
        ]
        if not ready:
            return [], ["Artifact manifest contains a dependency cycle."]
        ready.sort(key=lambda item: (item["is_test"], item["path"].lower()))
        for item in ready:
            ordered.append(item)
            pending.pop(item["path"])
    return ordered, []


def _artifact_manifest_item_is_test(item: dict[str, Any]) -> bool:
    """Infer test ownership from the complete manifest row, not one model boolean."""

    path = Path(str(item.get("path") or "").replace("\\", "/"))
    evidence = " ".join([
        path.stem,
        str(item.get("purpose") or ""),
    ]).lower()
    return bool(item.get("is_test")) or _is_test_path(path) or bool(
        re.search(r"\b(?:tests?|unittest|testcase|coverage|behavioral proof)\b", evidence)
    )


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
                "inferred_from_request": bool(
                    isinstance(raw_symbol, Mapping)
                    and raw_symbol.get("inferred_from_request")
                ),
            })
    return declarations


def build_deterministic_project_edit_chunk_plan(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve only requirements whose implementation owner is structurally proven."""

    for item in manifest:
        public_symbols = list(item.get("public_symbols") or [])

        def public_symbol_name(value: Any) -> str:
            if isinstance(value, Mapping):
                return str(value.get("name") or value.get("owner") or "")
            return str(value).split("(", 1)[0].strip()

        requirement_texts = [
            str(row.get("text") or row.get("requirement") or "")
            for row in requirement_ledger
        ]
        combined_requirement_text = " ".join(requirement_texts)
        ui_surface_requested = bool(
            re.search(
                r"\b(?:qt|pyside[26]?|pyqt[56]?)\b",
                combined_requirement_text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:ui|dialog|window|widget|panel)\b",
                combined_requirement_text,
                flags=re.IGNORECASE,
            )
        )
        explicitly_named_class = bool(re.search(
            r"\b[A-Z][A-Za-z0-9_]*(?:Dialog|Window|Widget|Panel|UI)\b",
            combined_requirement_text,
        ))
        has_class_symbol = any(
            (
                isinstance(value, Mapping)
                and str(value.get("kind") or "").casefold() == "class"
            )
            or public_symbol_name(value).rsplit(".", 1)[-1].endswith(
                ("Dialog", "Window", "Widget", "Panel", "Dock")
            )
            for value in public_symbols
        )
        if (
            ui_surface_requested
            and not explicitly_named_class
            and not has_class_symbol
        ):
            from tech_connector.services.capability_resolution_service import (
                extract_capability_intents,
            )

            intents = extract_capability_intents(combined_requirement_text)
            primary_intent = next(
                (
                    intent
                    for intent in intents
                    if intent.action not in {"create", "build"}
                ),
                intents[0] if intents else None,
            )
            name_parts: list[str] = []
            if primary_intent is not None:
                contextual_terms = {
                    str(host).casefold() for host in primary_intent.hosts
                }
                contextual_terms.update({
                    "api",
                    "build",
                    "capability",
                    "code",
                    "control",
                    "controls",
                    "create",
                    "expose",
                    "exposes",
                    "file",
                    "function",
                    "internal",
                    "method",
                    "panel",
                    "pyside",
                    "pyside2",
                    "pyside6",
                    "pyqt",
                    "pyqt5",
                    "pyqt6",
                    "qt",
                    "tool",
                    "ui",
                    "use",
                    "uses",
                    "widget",
                    "window",
                    "write",
                    "writing",
                })
                name_parts.extend(
                    term
                    for term in primary_intent.object_terms
                    if term.casefold() not in contextual_terms
                )
                name_parts = list(dict.fromkeys(name_parts))[:3]
                if (
                    primary_intent.action.casefold() not in contextual_terms
                    and primary_intent.action.casefold()
                    not in {part.casefold() for part in name_parts}
                ):
                    name_parts.append(primary_intent.action)
            if not name_parts:
                name_parts.extend(
                    part
                    for part in Path(
                        str(item.get("absolute_path") or item.get("path") or "tool")
                    ).stem.split("_")
                    if part
                )
            inferred_class_name = "".join(
                part[:1].upper() + part[1:]
                for part in name_parts
                if part
            ) + "Dialog"
            public_symbols = [{
                "name": inferred_class_name,
                "qualified_name": inferred_class_name,
                "kind": "class",
                "inferred_from_request": True,
            }]

        def has_declaration_evidence(value: Any) -> bool:
            if (
                isinstance(value, Mapping)
                and bool(value.get("inferred_from_request"))
            ):
                return True
            symbol_name = public_symbol_name(value).rsplit(".", 1)[-1]
            if not symbol_name or not symbol_name[:1].isupper():
                return True
            declaration_nouns = (
                r"class|dataclass|dialog|window|widget|service|manager|"
                r"adapter|record|model|exception|enum|protocol"
            )
            return any(
                re.search(
                    rf"\b{re.escape(symbol_name)}\b\s+(?:{declaration_nouns})\b"
                    rf"|\b(?:{declaration_nouns})\s+(?:named\s+|called\s+)?"
                    rf"\b{re.escape(symbol_name)}\b"
                    rf"|\b(?:add|build|create|define|defining|implement|"
                    rf"introduce|provide|write)\s+(?:an?\s+|the\s+|new\s+)*"
                    rf"\b{re.escape(symbol_name)}\b",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in requirement_texts
            )

        public_symbols = [
            value for value in public_symbols if has_declaration_evidence(value)
        ]

        verification_function_symbols = list(dict.fromkeys(
            match.group(1)
            for row in requirement_ledger
            for text in [
                str(row.get("text") or row.get("requirement") or "")
            ]
            for match in [
                re.search(
                    r"\b(?:add|define|implement|include|provide|expose)\s+"
                    r"(?:an?\s+|the\s+)?"
                    r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
                    r"[^.!?\n]{0,180}\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|"
                    r"validates?|self[- ]test|fake\s+"
                    r"(?:clock|client|host|service))\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ]
            if match
        ))
        for verification_symbol in verification_function_symbols:
            if verification_symbol not in {
                public_symbol_name(value).rsplit(".", 1)[-1]
                for value in public_symbols
            }:
                public_symbols.append(verification_symbol)
        item["public_symbols"] = public_symbols

        class_symbols = [
            public_symbol_name(value)
            for value in public_symbols
            if public_symbol_name(value).rsplit(".", 1)[-1][:1].isupper()
        ]
        if len(class_symbols) != 1:
            continue
        class_name = class_symbols[0].rsplit(".", 1)[-1]
        class_requirement_index = next(
            (
                index
                for index, row in enumerate(requirement_ledger)
                if re.search(
                    rf"\b{re.escape(class_name)}\b",
                    str(row.get("text") or row.get("requirement") or ""),
                )
                and re.search(
                    r"\b(?:class|dataclass|dialog|window|widget|service|manager|"
                    r"adapter|record|model)\b",
                    str(row.get("text") or row.get("requirement") or ""),
                    flags=re.IGNORECASE,
                )
            ),
            None,
        )
        if class_requirement_index is None:
            continue
        retained_symbols: list[Any] = []
        for value in public_symbols:
            symbol_name = public_symbol_name(value).rsplit(".", 1)[-1]
            if not symbol_name or not symbol_name[:1].islower():
                retained_symbols.append(value)
                continue
            continuation_rows = [
                str(row.get("text") or row.get("requirement") or "")
                for index, row in enumerate(requirement_ledger)
                if index > class_requirement_index
                and re.search(
                    rf"(?<![.\w]){re.escape(symbol_name)}\s*\(",
                    str(row.get("text") or row.get("requirement") or ""),
                )
            ]
            explicitly_module_owned = any(
                re.search(
                    rf"\b(?:top[- ]level|module[- ]level|standalone)\b"
                    rf"[^.!?\n]{{0,60}}\b{re.escape(symbol_name)}\b"
                    rf"|\b(?:function|callable)\s+{re.escape(symbol_name)}\b"
                    rf"|\b{re.escape(symbol_name)}\s+(?:function|callable)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            verification_helper = any(
                re.search(
                    r"\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|validates?|"
                    r"self[- ]test|fake\s+(?:clock|client|host|service))\b",
                    text,
                    flags=re.IGNORECASE,
                )
                and re.search(
                    rf"\b(?:add|define|implement|include|provide|expose)\b"
                    rf"[^.!?\n]{{0,80}}\b{re.escape(symbol_name)}\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            class_continuation = any(
                re.search(
                    rf"\b(?:add|define|implement|include|provide|expose)\b"
                    rf"[^.!?\n]{{0,80}}\b{re.escape(symbol_name)}\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
                for text in continuation_rows
            )
            if (
                class_continuation
                and not explicitly_module_owned
                and not verification_helper
            ):
                continue
            retained_symbols.append(value)
        item["public_symbols"] = retained_symbols

    declarations = _chunk_manifest_declarations(manifest)
    declaration_by_id = {
        item["declaration_id"]: item for item in declarations
    }
    file_items = {
        str(item.get("absolute_path") or item.get("path") or ""): item
        for item in manifest
    }
    files_by_requirement: dict[str, list[str]] = {}
    for path, item in file_items.items():
        for requirement_id in item.get("requirement_ids") or []:
            files_by_requirement.setdefault(str(requirement_id), []).append(path)
    passive_owner_names = {
        owner
        for raw_requirement in requirement_ledger
        for text in [
            str(
                raw_requirement.get("text")
                or raw_requirement.get("requirement")
                or raw_requirement.get("description")
                or ""
            )
        ]
        for owner in [
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b",
                text,
            ),
            *re.findall(
                r"\b(?:immutable\s+)?([A-Z][A-Za-z0-9_]*)\s+"
                r"(?:dataclass|record|enum|protocol)\b"
                r"|\b(?:dataclass|record|enum|protocol)\s+"
                r"([A-Z][A-Za-z0-9_]*)\b",
                text,
                flags=re.IGNORECASE,
            ),
        ]
        for owner in (
            [owner]
            if isinstance(owner, str)
            else [value for value in owner if value]
        )
        if owner
    }
    explicit_state_owner_names = {
        owner
        for raw_requirement in requirement_ledger
        for text in [
            str(
                raw_requirement.get("text")
                or raw_requirement.get("requirement")
                or raw_requirement.get("description")
                or ""
            )
        ]
        for owner in [
            *[
                match[0]
                for match in re.findall(
                    r"\b([A-Z][A-Za-z0-9_]*)\."
                    r"([a-z_][A-Za-z0-9_]*)\s*\(",
                    text,
                )
            ],
            *[
                match[0]
                for match in re.findall(
                    r"\b([A-Z][A-Za-z0-9_]*)\s+with\s+"
                    r"([a-z_][A-Za-z0-9_]*)\s*\(",
                    text,
                    flags=re.IGNORECASE,
                )
            ],
        ]
    }

    assignments: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    active_declarations_by_path: dict[str, list[str]] = {}
    declaration_actions = (
        r"\b(?:add|create|implement|define|write|build|introduce|provide)\b"
    )
    module_roles = {
        "module",
        "module_behavior",
        "entry_point",
        "file_contract",
        "package_contract",
        "imports",
    }
    for raw_requirement in requirement_ledger:
        requirement_id = str(
            raw_requirement.get("id")
            or raw_requirement.get("requirement_id")
            or ""
        ).strip()
        text = str(
            raw_requirement.get("text")
            or raw_requirement.get("requirement")
            or raw_requirement.get("description")
            or ""
        ).strip()
        semantic_role = str(
            raw_requirement.get("semantic_role")
            or raw_requirement.get("role")
            or ""
        ).strip()
        explicit_path = str(
            raw_requirement.get("path")
            or raw_requirement.get("file")
            or ""
        ).strip()
        requirement_paths = (
            [explicit_path]
            if explicit_path
            else list(files_by_requirement.get(requirement_id) or [])
        )
        file_declarations = [
            item
            for item in declarations
            if not requirement_paths or item["path"] in requirement_paths
        ]
        module_declarations = [
            item for item in file_declarations if item["owner"] == "<module>"
        ]
        named_declaration_ids = [
            item["declaration_id"]
            for item in file_declarations
            if item["owner"] != "<module>"
            and re.search(
                rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                text,
            )
        ]
        explicit_owner = str(
            raw_requirement.get("owner")
            or raw_requirement.get("resolved_owner")
            or ""
        ).strip()
        owners: list[str] = []
        multi_owner_proven = False
        explicitly_introduced_callable_ids = [
            item["declaration_id"]
            for item in file_declarations
            if item["kind"] == "function"
            and re.search(
                declaration_actions
                + rf"[^.!?\n]{{0,80}}\b"
                + re.escape(item["owner"].rsplit(".", 1)[-1])
                + r"\s*\(",
                text,
                flags=re.IGNORECASE,
            )
        ]
        if (
            not explicit_owner
            and len(explicitly_introduced_callable_ids) == 1
        ):
            owners = explicitly_introduced_callable_ids
        non_error_classes = [
            item
            for item in file_declarations
            if (
                item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            )
            and not item["owner"].rsplit(".", 1)[-1].endswith(
                ("Error", "Exception")
            )
        ]
        error_classes = [
            item
            for item in file_declarations
            if item["owner"].rsplit(".", 1)[-1].endswith(
                ("Error", "Exception")
            )
        ]
        cross_cutting_constraint = bool(
            re.search(
                r"\b(?:use only|standard library|no external|without external"
                r"|all generated files|entire package|package-wide"
                r"|(?:both|each|all|every)\s+files?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        callable_quality_constraint = bool(
            re.search(
                r"\b(?:detailed|complete|descriptive)\b"
                r"[^.!?\n]{0,120}\bdocstrings?\b"
                r"|\bdocstrings?\b[^.!?\n]{0,80}\b"
                r"(?:where applicable|public callables?|parameters?|returns?)\b"
                r"|\b(?:complete|explicit|full)\b[^.!?\n]{0,80}\b"
                r"(?:type hints?|annotations?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if not explicit_owner and callable_quality_constraint:
            owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] != "<module>"
            ]
            if not owners:
                owners = [
                    item["declaration_id"] for item in module_declarations
                ]
            multi_owner_proven = len(owners) > 1
        if not explicit_owner and cross_cutting_constraint:
            owners = [
                item["declaration_id"] for item in file_declarations
            ]
            multi_owner_proven = len(owners) > 1
        if explicit_owner:
            owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] == explicit_owner
                or item["owner"].endswith(f".{explicit_owner}")
            ]

        inferred_ui_owners = [
            item["declaration_id"]
            for item in file_declarations
            if item["owner"] != "<module>"
            and bool(item.get("inferred_from_request"))
            and (
                item.get("kind") == "class"
                or item["owner"].rsplit(".", 1)[-1].endswith(
                    ("Dialog", "Window", "Widget", "Panel", "Dock")
                )
            )
        ]
        ui_behavior_requirement = bool(
            re.search(
                r"\b(?:qt|pyside[26]?|pyqt[56]?)\b",
                text,
                flags=re.IGNORECASE,
            )
            and re.search(
                r"\b(?:ui|dialog|window|widget|panel|control|input|"
                r"button|field|filter|selection)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if (
            not explicit_owner
            and not owners
            and ui_behavior_requirement
            and len(inferred_ui_owners) == 1
        ):
            owners = inferred_ui_owners

        package_or_file_contract = bool(re.search(
            r"\b(?:create|add|build|generate|write|produce)\b"
            r"[^.!?\n]{0,140}\b(?:package|files?|modules?)\b"
            r"|\b(?:under|inside|within)\s+[A-Za-z_][A-Za-z0-9_./\\-]*"
            r"\s*:\s*[^.!?\n]*\.py\b"
            r"|\bdo\s+not\s+write\b[^.!?\n]{0,120}\b"
            r"(?:project\s+root|workspace|directory)\b",
            text,
            flags=re.IGNORECASE,
        ))
        if (
            not explicit_owner
            and not owners
            and package_or_file_contract
            and module_declarations
        ):
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        test_file_requirement = bool(
            requirement_paths
            and all(
                _is_test_path(Path(requirement_path))
                for requirement_path in requirement_paths
            )
        )
        if (
            not explicit_owner
            and not owners
            and test_file_requirement
            and module_declarations
        ):
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        proof_requirement = bool(
            re.match(r"^\s*Test proof\s*:", text, flags=re.IGNORECASE)
        )
        test_module_declarations = [
            item
            for item in declarations
            if item["owner"] == "<module>"
            and _is_test_path(Path(item["path"]))
        ]
        if (
            not explicit_owner
            and not owners
            and proof_requirement
            and len(test_module_declarations) == 1
        ):
            owners = [test_module_declarations[0]["declaration_id"]]

        if not explicit_owner and not owners:
            declared_error_ids = [
                item["declaration_id"]
                for item in error_classes
                if re.match(
                    rf"^\s*(?:and\s+)?"
                    rf"{re.escape(item['owner'].rsplit('.', 1)[-1])}\b"
                    r"(?:\s+(?:containing|with|that|which)\b[^.!?\n]*)?\s*$",
                    text,
                    flags=re.IGNORECASE,
                )
            ]
            if len(declared_error_ids) == 1:
                owners = declared_error_ids

        if not explicit_owner and not owners:
            qualified_owner_names = set(re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\.[a-z_][A-Za-z0-9_]*\s*\(",
                text,
            ))
            qualified_owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1]
                in qualified_owner_names
            ]
            if qualified_owners:
                owners = list(dict.fromkeys(qualified_owners))
                multi_owner_proven = len(owners) > 1

        if not explicit_owner and not owners:
            state_owner_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1]
                in explicit_state_owner_names
                and item["owner"].rsplit(".", 1)[-1]
                not in passive_owner_names
            ]
            operational_behavior = bool(re.search(
                r"\b(?:accept|allow|apply|call|cancel|check|connect|dequeue|"
                r"enqueue|execute|find|load|normalize|order|populate|progress|"
                r"raise|reject|report|return|run|save|schedule|set|snapshot|"
                r"update|validate)\w*\b",
                text,
                flags=re.IGNORECASE,
            ))
            declaration_only = bool(
                re.search(declaration_actions, text, flags=re.IGNORECASE)
                and named_declaration_ids
                and all(
                    declaration_by_id[declaration_id]["owner"].rsplit(
                        ".", 1
                    )[-1]
                    in passive_owner_names
                    for declaration_id in named_declaration_ids
                )
            )
            if (
                len(state_owner_candidates) == 1
                and operational_behavior
                and not declaration_only
            ):
                owners = state_owner_candidates

        if (
            not explicit_owner
            and not owners
        ):
            continuation_candidates = list(dict.fromkeys(
                declaration_id
                for path in requirement_paths
                for declaration_id in active_declarations_by_path.get(path, [])
            ))
            continuation_is_explicit = bool(re.match(
                r"^\s*(?:it|this|that|they|these|those)\b",
                text,
                flags=re.IGNORECASE,
            ))
            continuation_is_function_behavior = bool(
                len(continuation_candidates) == 1
                and declaration_by_id[
                    continuation_candidates[0]
                ]["kind"] == "function"
                and re.match(
                    r"^\s*(?:accept|allow|apply|build|call|connect|convert|create|"
                    r"delete|dequeue|emit|enqueue|export|find|generate|import|load|"
                    r"normalize|parse|read|reject|report|return|save|set|snapshot|"
                    r"update|validate|"
                    r"write)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            if (
                len(continuation_candidates) == 1
                and (
                    continuation_is_explicit
                    or continuation_is_function_behavior
                )
            ):
                owners = continuation_candidates

        if not explicit_owner and not owners:
            introduced_declarations = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"] != "<module>"
                and re.search(
                    rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                    text,
                )
            ]
            if (
                len(introduced_declarations) > 1
                and re.search(declaration_actions, text, flags=re.IGNORECASE)
                and not re.search(
                    r"\b(?:reject|raise|throw|fail)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ):
                owners = introduced_declarations
                multi_owner_proven = True

        if not explicit_owner and not owners:
            direct_owner_names = list(dict.fromkeys(re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\s+"
                r"(?:must|should|shall|will|provides?|implements?|exposes?)\b",
                text,
                flags=re.IGNORECASE,
            )))
            direct_owners = [
                item["declaration_id"]
                for item in file_declarations
                if item["owner"].rsplit(".", 1)[-1] in direct_owner_names
            ]
            if direct_owners:
                owners = direct_owners
                multi_owner_proven = len(owners) > 1

        if (
            not explicit_owner
            and not owners
            and len(non_error_classes) == 1
            and (
                re.search(
                    r"\b(?:thread-safe|deterministic|FIFO|immutable snapshot|"
                    r"insertion order|without mutating|state|cycle|self-depend|"
                    r"allow|dequeue|enqueue|reject|raise)\b",
                    text,
                    flags=re.IGNORECASE,
                )
                or (
                    error_classes
                    and any(
                        re.search(
                            rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                            text,
                        )
                        for item in error_classes
                    )
                )
            )
        ):
            owners = [non_error_classes[0]["declaration_id"]]

        workflow_artifact_constraint = bool(re.search(
            r"\b(?:do\s+not|don't|without|no)\s+"
            r"(?:(?:create|add|generate|write|include|produce|use)\s+)?"
            r"(?:any\s+|new\s+|project\s+)*"
            r"(?:test\s+files?|tests?)\b"
            r"|\bvalidation\s+artifacts?\s+(?:must\s+be\s+)?temporary\b",
            text,
            flags=re.IGNORECASE,
        ))
        if not owners and not named_declaration_ids and (
            semantic_role in module_roles
            or workflow_artifact_constraint
            or re.search(
                r"\b(?:module entry point|run as (?:a )?script|executed as (?:a )?script"
                r"|runs?\s+standalone|standalone\s+entry\s+point"
                r"|runnable\s+(?:main\s+)?example"
                r"|create(?: exactly)? (?:one|two|three|a|\w+)?\s*new "
                r"(?:files?|modules?)"
                r"|new Python file|if\s+__name__"
                r"|(?:do\s+not|don't|without|no)\s+"
                r"(?:create|add|generate|write|include|produce|use|new|project\s+)*"
                r"(?:test\s+files?|tests?)"
                r"|validation\s+artifacts?\s+(?:must\s+be\s+)?temporary)\b",
                text,
                flags=re.IGNORECASE,
            )
        ) and module_declarations:
            owners = [
                item["declaration_id"] for item in module_declarations
            ]
            multi_owner_proven = len(owners) > 1

        if not explicit_owner and not owners:
            declared_candidates: list[str] = []
            for item in file_declarations:
                if item["owner"] == "<module>":
                    continue
                symbol = item["owner"].split("(", 1)[0].rsplit(".", 1)[-1]
                if re.search(
                    declaration_actions
                    + rf"[^.!?\n]{{0,100}}\b{re.escape(symbol)}\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b[^.!?\n]{{0,40}}"
                    r"\b(?:class|function|callable)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b\s+"
                    r"[A-Z][A-Za-z0-9_.]*\s+"
                    r"(?:containing|with|that|which|inheriting|subclassing|extending)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"\b{re.escape(symbol)}\b\s+"
                    r"(?:inheriting\s+from|subclassing|extends)\s+"
                    r"[A-Z][A-Za-z0-9_.]*\b",
                    text,
                    flags=re.IGNORECASE,
                ) or re.search(
                    rf"^\s*{re.escape(symbol)}\b\s+"
                    r"(?:must|should|shall|will|exposes?|provides?|implements?|uses?)\b",
                    text,
                    flags=re.IGNORECASE,
                ) or (
                    len(requirement_paths) == 1
                    and re.search(rf"\b{re.escape(symbol)}\b", text)
                ):
                    declared_candidates.append(item["declaration_id"])
            if len(declared_candidates) == 1:
                owners.extend(declared_candidates)
                multi_owner_proven = len(owners) > 1
            elif len(declared_candidates) > 1 and (
                len(requirement_paths) == 1
                or re.search(
                    r"\b(?:both|each|all|every)\s+(?:of\s+the\s+)?files?\b",
                    text,
                    flags=re.IGNORECASE,
                )
            ):
                owners.extend(declared_candidates)
                multi_owner_proven = True
            owners = list(dict.fromkeys(owners))

        if not owners and re.search(
            r"\b(?:method|constructor|property|attribute|signal|slot)\b",
            text,
            flags=re.IGNORECASE,
        ):
            class_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            ]
            if len(class_candidates) == 1:
                owners = class_candidates

        if not owners:
            class_candidates = [
                item["declaration_id"]
                for item in file_declarations
                if item["kind"] == "class"
                or item["owner"].rsplit(".", 1)[-1][:1].isupper()
            ]
            class_owned_behavior = bool(
                re.search(
                    r"\b[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)"
                    r"|\.(?:clicked|triggered|toggled|accepted|rejected)\b"
                    r"|\b(?:dialogs?|windows?|widgets?|buttons?|inputs?|labels?|"
                    r"spinboxes?|comboboxes?|event\s+filters?|mouse|keyboard|escape)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            module_owned_behavior = bool(
                re.search(
                    r"\b(?:module entry point|run as (?:a )?script|"
                    r"runs?\s+standalone|standalone\s+entry\s+point|"
                    r"executed as (?:a )?script|if\s+__name__)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
            if (
                len(class_candidates) == 1
                and class_owned_behavior
                and not module_owned_behavior
                and not any(
                    item["kind"] == "function"
                    for item in file_declarations
                )
            ):
                owners = class_candidates

        module_owned_behavior = bool(
            re.search(
                r"\b(?:module entry point|run as (?:a )?script|"
                r"runs?\s+standalone|standalone\s+entry\s+point|"
                r"executed as (?:a )?script|if\s+__name__|"
                r"runnable\s+(?:main\s+)?example|"
                r"runnable\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?__main__|"
                r"__main__)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        class_owned_behavior = bool(
            re.search(
                r"\b(?:class|constructor|method|event\s+handling|cleanup|"
                r"dialogs?|windows?|widgets?|buttons?|inputs?|labels?|"
                r"spinboxes?|comboboxes?|signals?|clicked|progress|mouse|"
                r"keyboard|escape)\b"
                r"|\bQ[A-Z][A-Za-z0-9_]*(?:Widget|Button|Bar|Label|Box)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        class_candidates = [
            item["declaration_id"]
            for item in file_declarations
            if item["kind"] == "class"
            or item["owner"].rsplit(".", 1)[-1][:1].isupper()
        ]
        if module_owned_behavior and module_declarations:
            if class_owned_behavior and len(class_candidates) == 1:
                owners.append(class_candidates[0])
            owners.extend(
                item["declaration_id"] for item in module_declarations
            )
            owners = list(dict.fromkeys(owners))
            multi_owner_proven = len(owners) > 1

        if owners and (len(owners) == 1 or multi_owner_proven):
            owner_id = owners[0]
            owner_declaration = declaration_by_id[owner_id]
            resolved_role = (
                "constraint"
                if cross_cutting_constraint
                else semantic_role or "behavior"
            )
            if re.search(
                r"(?:self[-_ ]?test|\btests?\b|\bproof\b|\bprov(?:e[sd]?|ing)\b"
                r"|\bverif(?:y|ies|ication)\b)",
                text,
                flags=re.IGNORECASE,
            ) and any(
                declaration_by_id[item]["kind"] == "function"
                for item in owners
            ):
                resolved_role = "verification"
            dependencies: list[str] = []
            dependencies.extend(
                item["declaration_id"]
                for item in error_classes
                if item["declaration_id"] not in owners
                and re.search(
                    rf"\b{re.escape(item['owner'].rsplit('.', 1)[-1])}\b",
                    text,
                )
            )
            if all(
                declaration_by_id[item]["owner"] == "<module>"
                for item in owners
            ):
                if len(owners) == 1:
                    module_path = declaration_by_id[owners[0]]["path"]
                    dependencies.extend([
                        item["declaration_id"]
                        for item in file_declarations
                        if item["owner"] != "<module>"
                        and item["path"] == module_path
                    ])
            elif resolved_role == "verification" and len(owners) == 1:
                dependencies.extend([
                    item["declaration_id"]
                    for item in file_declarations
                    if item["declaration_id"] != owner_id
                    and item["owner"] != "<module>"
                    and item["kind"] != "function"
                ])
            dependencies = list(dict.fromkeys(dependencies))
            assignments.append({
                "requirement_id": requirement_id,
                "semantic_role": resolved_role,
                "declaration_ids": owners,
                "depends_on": dependencies,
                "reason": "deterministic structural ownership",
            })
        else:
            unresolved.append({
                "id": requirement_id,
                "text": text,
                "semantic_role": semantic_role,
                "path": (
                    explicit_path
                    or (
                        requirement_paths[0]
                        if len(requirement_paths) == 1
                        else ""
                    )
                ),
            })
        if (
            named_declaration_ids
            and (
                re.search(declaration_actions, text, flags=re.IGNORECASE)
                or re.fullmatch(
                    r"\s*[a-z_][A-Za-z0-9_]*\s*\([^()\n]*\)\s*",
                    text,
                )
            )
        ):
            for path in requirement_paths:
                active_declarations_by_path[path] = list(
                    dict.fromkeys(named_declaration_ids)
                )
    return assignments, unresolved


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
                    "requirements": [],
                    "depends_on": [],
                    "resolution": [],
                },
            )
            chunk["requirements"].append({
                "id": requirement_id,
                "text": requirement_text.get(requirement_id, ""),
                "semantic_role": str(
                    assignment.get("semantic_role") or "behavior"
                ),
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
) -> ProjectEditPromptStage:
    """Build one bounded declaration insertion without regenerating its file."""

    return ProjectEditPromptStage(
        key="artifact_missing_symbol",
        label=f"Implementing missing {symbol}",
        system_prompt=(
            "You are a bounded senior Python implementation worker. Return exactly one complete "
            "top-level class or function declaration as raw Python. Do not return imports, JSON, "
            "Markdown, commentary, or the surrounding file."
        ),
        user_prompt=f"""Original objective:
{objective}

File:
{path}

Missing manifest-owned public symbol:
{symbol}

Contracts:
{chr(10).join(f"- {value}" for value in contracts or []) or "- none"}

Required algorithm:
{chr(10).join(f"- {value}" for value in algorithm_steps or []) or "- none"}

Existing validated file:
```python
{source}
```

Implement the missing public symbol completely. Use only builtins, names already imported or defined
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
            "symbol": symbol,
            "scope": "module",
            "objective": objective,
            "owner_source": source,
        },
    )


def apply_project_edit_missing_symbol(
    source: str,
    *,
    path: str,
    symbol: str,
    response: str,
    objective: str = "",
) -> tuple[str, list[str]]:
    """Insert one validated missing module declaration before its entry point."""

    text = str(response or "").strip()
    text = re.sub(r"^```(?:python|py)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        tree = ast.parse(text, filename=f"<missing:{symbol}>")
    except SyntaxError as exc:
        return source, [f"Missing symbol {symbol} did not parse: {exc}"]
    declarations = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    declaration: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    if len(declarations) == 1 and len(tree.body) == 1:
        declaration = declarations[0]
    else:
        return source, [
            f"Missing symbol repair must return exactly one top-level declaration named {symbol}."
        ]
    placeholder_callables = [
        name
        for name, node in _callable_definition_map(tree).items()
        if any(
            isinstance(statement, ast.Pass)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and statement.value.value is Ellipsis
            )
            for statement in node.body
        )
    ]
    if placeholder_callables:
        return source, [
            f"Missing symbol {symbol} contains placeholder callables: "
            + ", ".join(placeholder_callables)
        ]
    declaration_source = ast.get_source_segment(text, declaration) or ast.unparse(declaration)
    try:
        owner_tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return source, [f"Missing symbol owner did not parse: {exc}"]
    source_lines = source.rstrip().splitlines()
    existing_declarations = [
        node
        for node in owner_tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    main_nodes = [
        node
        for node in owner_tree.body
        if isinstance(node, ast.If)
        and "__name__" in ast.unparse(node.test)
        and "__main__" in ast.unparse(node.test)
    ]
    if len(existing_declarations) > 1:
        return source, [
            f"Missing symbol owner contains duplicate top-level declarations named {symbol}."
        ]
    if existing_declarations:
        existing = existing_declarations[0]
        start = int(existing.lineno) - 1
        decorators = list(getattr(existing, "decorator_list", []) or [])
        if decorators:
            start = min(int(item.lineno) for item in decorators) - 1
        end = int(existing.end_lineno)
        inserted_lines = [
            *source_lines[:start],
            *declaration_source.rstrip().splitlines(),
            *source_lines[end:],
        ]
    else:
        insertion_index = (
            min(int(node.lineno) for node in main_nodes) - 1
            if main_nodes
            else len(source_lines)
        )
        inserted_lines = [
            *source_lines[:insertion_index],
            "",
            "",
            *declaration_source.rstrip().splitlines(),
            "",
            "",
            *source_lines[insertion_index:],
        ]
    corrected = "\n".join(inserted_lines).strip() + "\n"
    direct_main_relation = bool(
        re.search(
            rf"__main__[^\n.;]*?\b(?:runs?|calls?|invokes?)\s+"
            rf"{re.escape(symbol)}\s*\(",
            objective,
            flags=re.IGNORECASE,
        )
    )
    if direct_main_relation:
        corrected_tree = ast.parse(corrected, filename=path)
        offsets = [0]
        for line in corrected.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        replacements: list[tuple[int, int, str]] = []
        for main_node in corrected_tree.body:
            if not (
                isinstance(main_node, ast.If)
                and "__name__" in ast.unparse(main_node.test)
                and "__main__" in ast.unparse(main_node.test)
            ):
                continue
            for call in ast.walk(main_node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == symbol
                ):
                    start = offsets[call.lineno - 1] + call.col_offset
                    end = offsets[call.end_lineno - 1] + call.end_col_offset
                    replacements.append((start, end, f"{symbol}()"))
        for start, end, replacement in sorted(replacements, reverse=True):
            corrected = corrected[:start] + replacement + corrected[end:]
    try:
        compile(ast.parse(corrected, filename=path), path, "exec")
    except (SyntaxError, ValueError) as exc:
        return source, [f"Missing symbol {symbol} did not integrate: {exc}"]
    return corrected, []


def parse_project_edit_generated_file(
    source_response: str,
    *,
    path: str,
    expected_public_symbols: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Normalize and validate one raw full-file generation result."""

    source = str(source_response or "").strip()
    fenced_blocks = re.findall(
        r"```(?:python|py)?\s*(.*?)```",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_blocks:
        source = "\n\n".join(
            block.strip("\r\n") for block in fenced_blocks if block.strip()
        )
    else:
        source = re.sub(
            r"^```(?:python|py)?\s*",
            "",
            source,
            flags=re.IGNORECASE,
        )
        source = re.sub(r"\s*```$", "", source)
    if not source:
        return "", [f"Generated file returned no source: {path}"]
    try:
        tree = ast.parse(source, filename=path)
        source = _remove_redundant_generated_initializers(source, tree)
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        syntax_detail = ""
        if isinstance(exc, SyntaxError):
            offending_text = str(exc.text or "").rstrip()
            syntax_detail = (
                f"; offending source line {exc.lineno}: {offending_text}"
                if offending_text
                else ""
            )
        sanitized = _remove_generated_top_level_await(source, path=path)
        if sanitized != source:
            try:
                tree = ast.parse(sanitized, filename=path)
                compile(tree, path, "exec")
                source = sanitized
            except (SyntaxError, ValueError):
                return source.rstrip() + "\n", [
                    f"Generated file did not parse and compile ({Path(path).name}): "
                    f"{exc}{syntax_detail}"
                ]
        else:
            return source.rstrip() + "\n", [
                f"Generated file did not parse and compile ({Path(path).name}): "
                f"{exc}{syntax_detail}"
            ]
    expected = {
        match.group(0)
        for value in expected_public_symbols or []
        if (
            match := re.match(
                r"[A-Za-z_]\w*",
                str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip(),
            )
        )
    }
    declared_symbols = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    declared_symbols.update(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param))
    )
    missing_symbols = sorted(expected - declared_symbols)
    if missing_symbols:
        return source.rstrip() + "\n", [
            f"Generated file omitted manifest-declared public symbols ({Path(path).name}): "
            + ", ".join(missing_symbols)
        ]
    if _is_test_path(Path(path)):
        tests = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        ]
        if not tests:
            return source.rstrip() + "\n", [
                f"Generated test file defines no test_* methods: {path}"
            ]
        if all(any(isinstance(item, ast.Pass) for item in ast.walk(test)) for test in tests):
            return source.rstrip() + "\n", [
                f"Generated test file contains only placeholder tests: {path}"
            ]
    else:
        placeholders = [
            name
            for name, node in _callable_definition_map(tree).items()
            if any(
                isinstance(statement, ast.Pass)
                or (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value is Ellipsis
                )
                for statement in node.body
            )
        ]
        if placeholders:
            return source.rstrip() + "\n", [
                f"Generated production file contains placeholder callable bodies ({Path(path).name}): "
                + ", ".join(sorted(placeholders))
            ]
        source = _remove_generated_top_level_calls(source, tree=tree)
        tree = ast.parse(source, filename=path)
        side_effects = _generated_module_import_side_effects(tree)
        if side_effects:
            return source.rstrip() + "\n", [
                f"Generated production file executes behavior at import time ({Path(path).name}): "
                + ", ".join(side_effects)
            ]
    return source.rstrip() + "\n", []


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


def _remove_generated_top_level_calls(source: str, *, tree: ast.Module) -> str:
    """Remove generated module-level call expressions forbidden by the file contract."""

    removals = [
        statement
        for statement in tree.body
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        )
        or (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and isinstance(statement.value, ast.Call)
        )
    ]
    if not removals:
        return source
    lines = source.splitlines(keepends=True)
    for statement in sorted(removals, key=lambda item: item.lineno, reverse=True):
        del lines[statement.lineno - 1:int(statement.end_lineno or statement.lineno)]
    return "".join(lines)


def _remove_redundant_generated_initializers(source: str, tree: ast.Module) -> str:
    """Remove no-op constructors from classes that already expose real behavior."""

    removals: list[tuple[int, int]] = []
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        methods = [
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not any(method.name != "__init__" for method in methods):
            continue
        for method in methods:
            if method.name != "__init__":
                continue
            meaningful_body = [
                statement
                for statement in method.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
            ]
            if len(meaningful_body) == 1 and isinstance(meaningful_body[0], ast.Pass):
                removals.append((method.lineno - 1, method.end_lineno or method.lineno))
    if not removals:
        return source
    lines = source.splitlines(keepends=True)
    for start, end in sorted(removals, reverse=True):
        del lines[start:end]
    return "".join(lines)


def _generated_module_import_side_effects(tree: ast.Module) -> list[str]:
    """Return top-level executable statements that make importing generated code unsafe."""

    issues: list[str] = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue
            if isinstance(statement.value, ast.Call):
                issues.append(f"call on line {statement.lineno}")
        elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            issues.append(f"{statement.__class__.__name__} on line {statement.lineno}")
        elif isinstance(statement, ast.Try):
            issues.append(f"Try on line {statement.lineno}")
    return issues


def validate_project_edit_generated_module_graph(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
    declared_dependencies: list[str] | None = None,
) -> list[str]:
    """Validate imports against completed generated files and declared manifest edges."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [f"Generated module graph could not parse {Path(path).name}: {exc}"]

    target_path = Path(path).resolve()
    candidate_sources = {
        str(Path(file_path).resolve()): generated_source
        for file_path, _original, generated_source in generated_files
    }
    candidate_sources[str(target_path)] = source
    declared = {
        str((Path(project_root) / dependency).resolve())
        for dependency in declared_dependencies or []
    }
    errors: list[str] = []
    if not _is_test_path(target_path):
        current_classes = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        }
        for dependency_path, dependency_source in candidate_sources.items():
            if dependency_path == str(target_path):
                continue
            try:
                dependency_tree = ast.parse(dependency_source, filename=dependency_path)
            except SyntaxError:
                continue
            dependency_classes = {
                node.name
                for node in dependency_tree.body
                if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
            }
            duplicate_classes = sorted(current_classes.intersection(dependency_classes))
            if duplicate_classes:
                errors.append(
                    f"Generated module duplicates dependency-owned public type "
                    f"({Path(path).name} -> {Path(dependency_path).name}): "
                    f"{', '.join(duplicate_classes)}. Import and reuse the canonical type."
                )
    for module, level, imported_name in _import_specs(tree):
        ok, detail = _resolve_import_spec(
            target_path,
            module,
            level,
            imported_name,
            project_root=project_root,
            candidate_sources=candidate_sources,
        )
        if not ok:
            errors.append(detail)
            continue
        local_path = _local_module_path(
            target_path,
            module,
            level,
            project_root=project_root,
            candidate_paths=set(candidate_sources),
        )
        if (
            local_path is not None
            and local_path.resolve() != target_path
            and str(local_path.resolve()) in candidate_sources
            and str(local_path.resolve()) not in declared
        ):
            errors.append(
                f"Generated import is missing its manifest dependency edge "
                f"({Path(path).name} -> {local_path.name})."
            )
    return list(dict.fromkeys(errors))


def repair_project_edit_duplicate_dependency_symbols(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
) -> tuple[str, list[str]]:
    """Remove echoed dependency definitions and import canonical owners when used."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return source, []
    root = Path(project_root).resolve()
    target = Path(path).resolve()
    owners: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for dependency_path, _original, dependency_source in generated_files:
        dependency = Path(dependency_path).resolve()
        if dependency == target:
            continue
        try:
            dependency_tree = ast.parse(dependency_source, filename=dependency_path)
            module = ".".join(dependency.relative_to(root).with_suffix("").parts)
        except (SyntaxError, ValueError):
            continue
        for node in dependency_tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            if node.name in owners:
                ambiguous.add(node.name)
            else:
                owners[node.name] = (module, str(dependency))

    duplicates = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in owners
        and node.name not in ambiguous
    ]
    if not duplicates:
        return source, []

    lines = source.splitlines(keepends=True)
    removed_names = {node.name for node in duplicates}
    for node in sorted(duplicates, key=lambda item: item.lineno, reverse=True):
        del lines[node.lineno - 1:int(node.end_lineno or node.lineno)]
    repaired = "".join(lines)
    repaired_tree = ast.parse(repaired, filename=path)
    loaded_names = {
        node.id
        for node in ast.walk(repaired_tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    required_imports = {
        name: owners[name][0]
        for name in removed_names & loaded_names
    }
    if required_imports:
        import_lines = [
            f"from {module} import {name}\n"
            for name, module in sorted(required_imports.items())
        ]
        insertion = 1 if lines and re.match(r"^#.*coding[:=]", lines[0]) else 0
        while insertion < len(lines) and (
            not lines[insertion].strip()
            or lines[insertion].startswith("import ")
            or lines[insertion].startswith("from ")
        ):
            insertion += 1
        lines[insertion:insertion] = import_lines
        repaired = "".join(lines)
    compile(ast.parse(repaired, filename=path), path, "exec")
    fixes = [
        f"{Path(path).name}: removed echoed {name} owned by "
        f"{Path(owners[name][1]).name}"
        for name in sorted(removed_names)
    ]
    fixes.extend(
        f"{Path(path).name}: imported {name} from {module}"
        for name, module in sorted(required_imports.items())
    )
    return repaired, fixes


def infer_project_edit_generated_dependencies(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Return completed generated files imported by the current generated source."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    root = Path(project_root).resolve()
    target = Path(path).resolve()
    candidate_paths = {
        str(Path(file_path).resolve())
        for file_path, _original, _generated in generated_files
    }
    dependencies: list[str] = []
    for module, level, imported_name in _import_specs(tree):
        local_path = _local_module_path(
            target,
            module,
            level,
            project_root=project_root,
            candidate_paths=candidate_paths,
        )
        if local_path is None or str(local_path.resolve()) not in candidate_paths:
            continue
        try:
            relative = local_path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        dependencies.append(relative)
    return list(dict.fromkeys(dependencies))


def summarize_project_edit_generated_interface(path: str, source: str) -> str:
    """Render a compact AST readback for the next incremental file worker."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return f"{Path(path).name}: interface unavailable because source did not parse"

    entries: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            entries.append(f"{node.name}{_render_ast_arguments(node.args)}")
        elif isinstance(node, ast.ClassDef):
            constructor = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "__init__"
                ),
                None,
            )
            class_signature = (
                _render_ast_arguments(constructor.args, drop_first=True)
                if constructor is not None
                else "()"
            )
            entries.append(f"{node.name}{class_signature}")
            entries.extend(
                f"{node.name}.{child.name}{_render_ast_arguments(child.args, drop_first=True)}"
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        rendered_value = repr(ast.literal_eval(value))
                    except (TypeError, ValueError):
                        rendered_value = "<computed>"
                    entries.append(f"{target.id}={rendered_value}")
    return f"{Path(path).name}: " + ("; ".join(entries) if entries else "(no public API)")


def _render_ast_arguments(arguments: ast.arguments, *, drop_first: bool = False) -> str:
    positional = [*arguments.posonlyargs, *arguments.args]
    if drop_first and positional:
        positional = positional[1:]
    defaults_offset = len(positional) - len(arguments.defaults)
    rendered: list[str] = []
    for index, argument in enumerate(positional):
        value = argument.arg
        default_index = index - defaults_offset
        if default_index >= 0:
            value += "=" + ast.unparse(arguments.defaults[default_index])
        rendered.append(value)
    if arguments.vararg:
        rendered.append("*" + arguments.vararg.arg)
    elif arguments.kwonlyargs:
        rendered.append("*")
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        value = argument.arg
        if default is not None:
            value += "=" + ast.unparse(default)
        rendered.append(value)
    if arguments.kwarg:
        rendered.append("**" + arguments.kwarg.arg)
    return "(" + ", ".join(rendered) + ")"


def build_project_edit_cross_file_failure_notes(
    generated_files: list[tuple[str, str, str]],
    validation_errors: list[str],
) -> list[str]:
    """Describe shared undefined-name ownership failures for the architecture worker."""

    undefined_uses: dict[str, int] = {}
    for error in validation_errors:
        for match in re.finditer(
            r"Generated callables reference undefined names in ([^:]+):\s*([^;\n]+)",
            str(error),
        ):
            callable_count = max(
                1,
                len([value for value in match.group(1).split(",") if value.strip()]),
            )
            for name in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", match.group(2)):
                undefined_uses[name] = undefined_uses.get(name, 0) + callable_count
    if not undefined_uses:
        return []

    owners: dict[str, list[str]] = {}
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [node.name]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [
                    target.id for target in targets if isinstance(target, ast.Name)
                ]
            for name in names:
                owners.setdefault(name, []).append(path_text)

    notes: list[str] = []
    for name, use_count in sorted(undefined_uses.items()):
        if use_count < 2:
            continue
        name_owners = list(dict.fromkeys(owners.get(name) or []))
        if len(name_owners) > 1:
            notes.append(
                f"Cross-file contract conflict: {name} is used unresolved by {use_count} callables "
                f"and is defined by multiple modules ({', '.join(name_owners)}). Select one "
                "canonical production owner and make every consumer depend on and import it."
            )
        elif not name_owners:
            notes.append(
                f"Cross-file contract gap: {name} is used unresolved by {use_count} callables "
                "but no generated module owns it. Add one canonical production owner and explicit "
                "dependency/import edges."
            )
    return notes


def project_edit_validation_failure_signature(
    validation_errors: list[str],
) -> tuple[str, ...]:
    """Normalize disposable failures to stable root-cause evidence."""

    facts: set[str] = set()
    for error in validation_errors:
        text = re.sub(
            r"tech_connector_patch_validation_[^\\/\s]+",
            "tech_connector_patch_validation_<temp>",
            str(error),
        )
        for line in text.splitlines():
            stripped = " ".join(line.strip().split())
            if not stripped:
                continue
            exception = re.match(
                r"^(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)|AssertionError):\s*(.*)$",
                stripped,
            )
            if exception:
                normalized = re.sub(r"\bline\s+\d+\b", "line <n>", stripped)
                facts.add(normalized)
                continue
            if stripped.startswith((
                "Generated callables reference undefined names",
                "Generated production callables are placeholders",
                "New import could not be resolved",
                "Generated import is missing its manifest dependency edge",
                "Project-local import does not expose",
            )):
                facts.add(stripped)
    if facts:
        return tuple(sorted(facts))
    return tuple(sorted(
        re.sub(r"\bline\s+\d+\b", "line <n>", " ".join(str(item).split()))
        for item in validation_errors
    ))


def build_project_edit_function_repair_contract(
    generated_files: list[tuple[str, str, str]],
    *,
    target: dict[str, str],
    validation_errors: list[str],
    objective: str,
    requirements: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Describe one failing callable without handing the worker its whole file."""

    path = str(target.get("path") or "")
    symbol = str(target.get("symbol") or "")
    module_source = next(
        (
            source
            for path_text, _original, source in generated_files
            if Path(path_text).resolve() == Path(path).resolve()
        ),
        "",
    )
    if not path or not symbol or not module_source:
        return {}, ["Function repair target is incomplete or no longer exists."]
    parts = symbol.split(".")
    target_source_override = ""
    try:
        tree = ast.parse(module_source, filename=path)
    except SyntaxError as exc:
        source_lines = module_source.splitlines(keepends=True)
        class_name = parts[0] if len(parts) == 2 else ""
        callable_name = parts[-1]
        active_class = ""
        class_indent = -1
        target_start = -1
        target_end = len(source_lines)
        target_indent = ""
        definition_line = -1
        for line_index, line in enumerate(source_lines):
            stripped = line.lstrip()
            if not stripped:
                continue
            indent_text = line[:len(line) - len(stripped)]
            indent_size = len(indent_text.expandtabs(4))
            class_match = re.match(
                r"class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                stripped,
            )
            if class_match:
                active_class = class_match.group(1)
                class_indent = indent_size
                continue
            if active_class and indent_size <= class_indent:
                active_class = ""
                class_indent = -1
            if not re.match(
                rf"(?:async\s+)?def\s+{re.escape(callable_name)}\s*\(",
                stripped,
            ):
                continue
            if class_name and active_class != class_name:
                continue
            if not class_name and active_class:
                continue
            target_indent = indent_text
            definition_line = line_index
            target_start = line_index
            while (
                target_start > 0
                and source_lines[target_start - 1].lstrip().startswith("@")
                and source_lines[target_start - 1].startswith(target_indent)
            ):
                target_start -= 1
            for following_index in range(line_index + 1, len(source_lines)):
                following = source_lines[following_index]
                if not following.strip():
                    continue
                following_indent = len(following) - len(following.lstrip())
                if following_indent <= len(target_indent):
                    target_end = following_index
                    break
            break
        if target_start < 0 or definition_line < 0:
            return {}, [
                f"Function repair owner does not parse and lexical target "
                f"{symbol} was not found: {exc}"
            ]
        target_source_override = textwrap.dedent(
            "".join(source_lines[target_start:target_end])
        ).strip()
        sanitized_lines = list(source_lines)
        prefix_lines = source_lines[target_start:definition_line + 1]
        replacement_lines = [
            *prefix_lines,
            target_indent + "    pass\n",
        ]
        replacement_lines.extend(
            "\n"
            for _ in range(
                max(0, target_end - target_start - len(replacement_lines))
            )
        )
        sanitized_lines[target_start:target_end] = replacement_lines
        try:
            tree = ast.parse("".join(sanitized_lines), filename=path)
        except SyntaxError as sanitized_exc:
            return {}, [
                f"Function repair target {symbol} could not be isolated from its "
                f"syntax failure: {sanitized_exc}"
            ]

    owner: ast.ClassDef | None = None
    candidates: list[ast.FunctionDef | ast.AsyncFunctionDef]
    if len(parts) == 2:
        owner = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == parts[0]
            ),
            None,
        )
        candidates = [
            node
            for node in (owner.body if owner is not None else [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == parts[1]
        ]
    else:
        candidates = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == parts[-1]
        ]
    if len(candidates) != 1:
        return {}, [f"Function repair target must resolve to one callable: {symbol}"]
    node = candidates[0]

    module_imports = [
        ast.get_source_segment(module_source, item) or ast.unparse(item)
        for item in tree.body
        if isinstance(item, (ast.Import, ast.ImportFrom))
    ]
    sibling_nodes = [
        item
        for item in (owner.body if owner is not None else tree.body)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item is not node
    ]
    sibling_symbols = [
        f"{owner.name}.{item.name}" if owner is not None else item.name
        for item in sibling_nodes
    ]
    module_symbols = [
        item.name
        for item in tree.body
        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    sibling_signatures = [
        ast.unparse(item).splitlines()[0]
        for item in sibling_nodes
        if ast.unparse(item)
    ]
    state_context: list[str] = []
    if owner is not None:
        for item in owner.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "__init__"
            ) or isinstance(item, (ast.Assign, ast.AnnAssign)):
                state_context.append(
                    ast.get_source_segment(module_source, item) or ast.unparse(item)
                )
        for sibling in sibling_nodes:
            for statement in ast.walk(sibling):
                if not isinstance(
                    statement,
                    (ast.Assign, ast.AnnAssign, ast.AugAssign),
                ):
                    continue
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                writes_instance_state = any(
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                    for target_node in targets
                    for child in ast.walk(target_node)
                )
                if not writes_instance_state:
                    continue
                rendered = (
                    ast.get_source_segment(module_source, statement)
                    or ast.unparse(statement)
                )
                if rendered not in state_context:
                    state_context.append(rendered)
    callsite_excerpts: list[str] = []
    all_callsite_excerpts: list[str] = []
    for path_text, _original, candidate_source in generated_files:
        try:
            candidate_tree = ast.parse(candidate_source, filename=path_text)
        except SyntaxError:
            continue
        for callable_node in [
            item
            for item in ast.walk(candidate_tree)
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            if path_text == path and callable_node is node:
                continue
            calls_target = any(
                isinstance(child, ast.Call)
                and (
                    isinstance(child.func, ast.Name)
                    and child.func.id == node.name
                    or isinstance(child.func, ast.Attribute)
                    and child.func.attr == node.name
                )
                for child in ast.walk(callable_node)
            )
            if not calls_target:
                continue
            parent_by_id = {
                id(child): parent
                for parent in ast.walk(callable_node)
                for child in ast.iter_child_nodes(parent)
            }
            call_node = next(
                (
                    child
                    for child in ast.walk(callable_node)
                    if isinstance(child, ast.Call)
                    and (
                        isinstance(child.func, ast.Name)
                        and child.func.id == node.name
                        or isinstance(child.func, ast.Attribute)
                        and child.func.attr == node.name
                    )
                ),
                None,
            )
            selected_statements: list[ast.stmt] = []
            if call_node is not None:
                call_statement: ast.AST = call_node
                while not isinstance(call_statement, ast.stmt):
                    call_statement = parent_by_id.get(id(call_statement), call_statement)
                    if call_statement is call_node:
                        break
                if not isinstance(call_statement, ast.stmt):
                    continue
                argument_names = {
                    child.id
                    for argument in call_node.args
                    for child in ast.walk(argument)
                    if isinstance(child, ast.Name)
                }
                for statement in ast.walk(callable_node):
                    if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        continue
                    if int(getattr(statement, "lineno", 0) or 0) >= int(call_statement.lineno):
                        continue
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    assigned_names = {
                        child.id
                        for target_node in targets
                        for child in ast.walk(target_node)
                        if isinstance(child, ast.Name)
                    }
                    value = statement.value
                    if assigned_names & argument_names and isinstance(
                        value,
                        (ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set),
                    ):
                        selected_statements.append(statement)
                selected_statements.extend(
                    statement
                    for statement in ast.walk(callable_node)
                    if isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Call)
                    and int(getattr(statement, "lineno", 0) or 0)
                    < int(call_statement.lineno)
                )
                selected_statements.append(call_statement)
                selected_statements.extend(
                    statement
                    for statement in ast.walk(callable_node)
                    if int(getattr(statement, "lineno", 0) or 0) > int(call_statement.lineno)
                    and (
                        isinstance(statement, ast.Assert)
                        or (
                            isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                            and isinstance(statement.value.func, ast.Attribute)
                            and statement.value.func.attr.startswith("assert")
                        )
                    )
                )
                selected_statements.sort(key=lambda statement: int(statement.lineno))
                preceding = [
                    statement
                    for statement in selected_statements
                    if int(statement.lineno) < int(call_statement.lineno)
                ][-4:]
                selected_statements = preceding + [
                    statement
                    for statement in selected_statements
                    if int(statement.lineno) >= int(call_statement.lineno)
                ][:3]
            excerpt = "\n".join(
                ast.get_source_segment(candidate_source, statement) or ast.unparse(statement)
                for statement in selected_statements[:6]
            )
            if excerpt:
                callsite_excerpts.append(
                    f"{Path(path_text).name}:{callable_node.name}\n{excerpt}"
                )
                complete_caller = (
                    ast.get_source_segment(candidate_source, callable_node)
                    or ast.unparse(callable_node)
                )
                all_callsite_excerpts.append(
                    f"{Path(path_text).name}:{callable_node.name}\n{complete_caller}"
                )
    failure_text = "\n".join(str(item) for item in validation_errors)
    needles = [Path(path).name.lower(), parts[-1].lower(), symbol.lower()]
    lower_failure = failure_text.lower()
    positions = [
        lower_failure.find(needle)
        for needle in needles
        if needle and lower_failure.find(needle) >= 0
    ]
    if positions:
        position = max(positions)
        relevant_failure = failure_text[max(0, position - 1400): position + 3200]
    else:
        relevant_failure = failure_text[-4600:]
    target_failure_text = "\n".join(
        str(error)
        for error in validation_errors
        if (
            "Generated callables reference undefined names in " in str(error)
            and any(
                owner.strip() in {symbol, parts[-1]}
                for owner in str(error).split(":", 1)[0]
                .split(" in ", 1)[-1]
                .split(",")
            )
        )
    ) or relevant_failure
    forbidden_names = sorted({
        value
        for group in re.findall(
            r"Generated callables reference undefined names in [^:]+:\s*"
            r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
            target_failure_text,
        )
        for value in (item.strip() for item in group.split(","))
        if value
    })
    forbidden_names.extend(
        value
        for value in re.findall(
            r"NameError:\s+name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined",
            target_failure_text,
        )
        if value not in forbidden_names
    )
    forbidden_names.extend(
        terminal_name
        for qualified_name in re.findall(
            r"\buses\s+`([A-Za-z_][A-Za-z0-9_.]*)`,\s*expected\b",
            failure_text,
            flags=re.IGNORECASE,
        )
        for terminal_name in [qualified_name.rsplit(".", 1)[-1]]
        if terminal_name not in forbidden_names
    )
    forbidden_names = [
        value
        for value in forbidden_names
        if not (
            value.split(".", 1)[0] in _HOST_RUNTIME_MODULES
            or _verified_installed_qt_symbol(value)
            or (
                value[:1].isupper()
                and re.search(
                    rf"\b{re.escape(value)}\b",
                    str(objective or ""),
                )
            )
        )
    ]
    verified_repair_symbols = sorted(
        {
            name
            for name in re.findall(r"\bQ[A-Za-z0-9_]+\b", failure_text)
            if _verified_installed_qt_symbol(name)
        }
    )
    module_symbols.extend(
        name for name in verified_repair_symbols if name not in module_symbols
    )

    source = (
        target_source_override
        or ast.get_source_segment(module_source, node)
        or str(target.get("source") or "")
    )
    rendered_callable = ast.unparse(node)
    signature = rendered_callable.splitlines()[0] if rendered_callable else ""
    generated_interfaces = [
        summarize_project_edit_generated_interface(path_text, generated_source)
        for path_text, _original, generated_source in generated_files
    ]
    derived_requirements = [
        str(value) for value in requirements or [] if str(value).strip()
    ]
    objective_lower = str(objective or "").lower()
    symbol_lower = symbol.lower()
    if node.name.startswith("test_"):
        stored_names = {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Store)
        }
        loaded_names = {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
        }
        unused_fixtures = sorted(
            value
            for value in stored_names - loaded_names
            if value not in {"self", "cls"} and not value.startswith("_")
        )
        if unused_fixtures:
            derived_requirements.append(
                "Consume every constructed fixture through the public API before "
                "assertions; currently unused fixtures: "
                + ", ".join(unused_fixtures)
            )
        if (
            any(term in symbol_lower for term in ("report", "find", "list", "order"))
            and not re.search(
                r"\b(?:raise|raises|reject|error|exception)\b",
                objective_lower,
            )
        ):
            derived_requirements.append(
                "Assert the requested returned value; do not use assertRaises for this observable behavior."
            )
        if (
            any(term in symbol_lower for term in ("missing", "unresolved", "not_found"))
            and any(term in objective_lower for term in ("missing", "unresolved", "not found"))
        ):
            derived_requirements.append(
                "Introduce every expected missing/unresolved identifier through a preceding public input or "
                "mutation call before querying and asserting that identifier."
            )
    if (
        any(term in symbol_lower for term in ("cycle", "loop"))
        and any(term in objective_lower for term in ("cycle", "loop"))
    ):
        derived_requirements.append(
            "Start detection from every unvisited candidate, not only candidates whose initial state excludes "
            "the condition being detected; return the detected structures unless the objective requests an error."
        )
    if (
        any(term in objective_lower for term in ("missing target", "missing dependency", "unresolved"))
        and any(term in symbol_lower for term in ("add", "set", "load", "ingest", "import"))
    ):
        derived_requirements.append(
            "Preserve an input that references an unresolved target so the requested missing-state query can "
            "observe it; validate the owning/source identity separately from the unresolved referenced identity."
        )
    if "require the requested input file to exist before" in lower_failure:
        derived_requirements.append(
            "Validate a disk input with pathlib.Path(...).is_file() or "
            "os.path.isfile() before any host-runtime call. A host asset registry "
            "or editor asset-existence API does not validate a filesystem source."
        )
    if "validate optional callback inputs before" in lower_failure:
        derived_requirements.append(
            "Before any host-runtime call, accept None for each optional callback "
            "and raise TypeError when a non-None callback is not callable."
        )
    if "replace the inline ui progress callback" in lower_failure:
        derived_requirements.append(
            "Replace the inline callback with a local callback accepting "
            "(current, total, message). It must consume all three values, call "
            "progress_bar.setRange(0, total), progress_bar.setValue(current), "
            "and status_label.setText(message), then pass that callback to the "
            "backend operation."
        )
    elif "replace the ui progress callback" in lower_failure:
        derived_requirements.append(
            "Use a callback accepting exactly (current, total, message). It "
            "must call progress_bar.setRange(0, total), "
            "progress_bar.setValue(current), and "
            "status_label.setText(message)."
        )
    missing_request_fields = re.findall(
        r"validate or normalize every request field before[^;\r\n]*missing:\s*"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)",
        failure_text,
        flags=re.IGNORECASE,
    )
    for missing_group in missing_request_fields:
        derived_requirements.append(
            "Read, validate, and normalize these request fields before the first "
            "host-runtime call: "
            + ", ".join(
                value.strip()
                for value in missing_group.split(",")
                if value.strip()
            )
            + "."
        )
    if "exactly-one returned path contract" in lower_failure:
        derived_requirements.append(
            "After the host import completes, require len(imported_paths) == 1 "
            "before indexing the sole returned path."
        )
    if "normalize host paths with .replace" in lower_failure:
        derived_requirements.append(
            "Normalize each host package path before the first host-runtime call "
            "using a single-backslash replacement equivalent to "
            r'.replace("\\", "/").'
        )
    if "normalize the value assigned to" in lower_failure:
        derived_requirements.append(
            "Trace every value assigned to a host property ending in `_path` "
            "back to a normalized string produced with a single-backslash "
            r'.replace("\\", "/"); do not normalize an unrelated filename instead.'
        )
    if "host package paths must not be validated as filesystem" in lower_failure:
        derived_requirements.append(
            "Treat host package destinations as host paths, not disk directories. "
            "Validate non-empty package-string form and forward slashes without "
            "calling pathlib.Path.is_dir(), exists(), or is_file() on that value."
        )
    if "validate or normalize boolean request field" in lower_failure:
        derived_requirements.append(
            "Before any host-runtime call, validate boolean-like request fields "
            "with isinstance(value, bool), or normalize them explicitly with bool()."
        )
    if "typeerror:" in lower_failure and "magicmock" in lower_failure:
        derived_requirements.append(
            "Replace mock values that participate in arithmetic, ordering, or "
            "comparison with a deterministic value-producing fake of the required "
            "runtime type. Keep mocks only for call recording and assertion APIs."
        )
    assertion_proven_invalid = any(
        marker in lower_failure
        for marker in (
            "invalid verification expectation",
            "validator-proven invalid assertion",
        )
    )
    if (
        re.search(r"(?:^|_)(?:self_)?test(?:_|$)", node.name)
        and "assertionerror" in lower_failure
        and assertion_proven_invalid
    ):
        failing_assertions = list(dict.fromkeys(
            line.strip()
            for line in failure_text.splitlines()
            if line.strip().startswith("assert ")
        ))
        derived_requirements.append(
            "Replace the traceback assertion that just failed; it is "
            "validator-proven invalid. Do not leave that assertion in place and "
            "append a second fixture afterward."
            + (
                " Invalid assertion: " + failing_assertions[-1]
                if failing_assertions
                else ""
            )
        )
    invalid_assertion_lines = (
        list(dict.fromkeys(
            line.strip()
            for line in failure_text.splitlines()
            if line.strip().startswith("assert ")
        ))
        if assertion_proven_invalid
        else []
    )
    if invalid_assertion_lines:
        invalid_assertion_set = set(invalid_assertion_lines)
        sanitized_source_lines: list[str] = []
        for source_line in source.splitlines():
            if source_line.strip() in invalid_assertion_set:
                indent = source_line[:len(source_line) - len(source_line.lstrip())]
                sanitized_source_lines.append(
                    f"{indent}# INVALID ASSERTION REMOVED BY CONTRACT"
                )
            else:
                sanitized_source_lines.append(source_line)
        source = "\n".join(sanitized_source_lines)
    return {
        "path": path,
        "symbol": symbol,
        "callable_name": node.name,
        "source": source,
        "signature": signature,
        "signature_fingerprint": ast.dump(node.args, include_attributes=False),
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "owner_class": owner.name if owner is not None else "",
        "module_imports": module_imports,
        "module_symbols": module_symbols,
        "generated_interfaces": generated_interfaces,
        "sibling_symbols": sibling_symbols,
        "sibling_signatures": sibling_signatures,
        "state_context": state_context,
        "callsite_excerpts": callsite_excerpts,
        "all_callsite_excerpts": all_callsite_excerpts,
        "forbidden_names": forbidden_names,
        "requirements": list(dict.fromkeys(derived_requirements)),
        "full_requirements": [
            str(value) for value in requirements or [] if str(value).strip()
        ],
        "objective": str(objective or ""),
        "full_objective": str(objective or ""),
        "failure": relevant_failure,
        "all_validation_errors": [
            str(value) for value in validation_errors if str(value).strip()
        ],
        "invalid_assertion_lines": invalid_assertion_lines,
        "atomic_owner_capsule": True,
    }, []


def build_project_edit_function_repair_stage(
    contract: dict[str, Any],
    *,
    attempt: int = 1,
    repair_plan: dict[str, Any] | None = None,
) -> ProjectEditPromptStage:
    """Build a bounded callable-only repair worker from a validated contract."""

    requirements = "\n".join(
        f"- {value}" for value in contract.get("requirements") or []
    ) or "- preserve the objective behavior owned by this callable"
    imports = "\n".join(contract.get("module_imports") or []) or "(none)"
    module_symbols = ", ".join(contract.get("module_symbols") or []) or "(none)"
    generated_interfaces = "\n".join(
        contract.get("generated_interfaces") or []
    ) or "(none)"
    sibling_symbols = ", ".join(contract.get("sibling_symbols") or []) or "(none)"
    sibling_signatures = "\n".join(contract.get("sibling_signatures") or []) or "(none)"
    state_context = "\n\n".join(contract.get("state_context") or []) or "(none)"
    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    forbidden_names = ", ".join(contract.get("forbidden_names") or []) or "(none)"
    symbol = str(contract.get("symbol") or "")
    callable_name = symbol.rsplit(".", 1)[-1]
    verification_callable = (
        callable_name in {"run_self_test", "self_test"}
        or callable_name.startswith("test_")
    )
    plan_text = json.dumps(repair_plan or {}, indent=2)
    forbidden_set = {
        str(value) for value in contract.get("forbidden_names") or [] if str(value)
    }
    invalid_assertion_lines = {
        str(value).strip()
        for value in contract.get("invalid_assertion_lines") or []
        if str(value).strip()
    }
    source_lines = []
    for line in str(contract.get("source") or "").splitlines():
        if line.strip() in invalid_assertion_lines:
            indent = line[: len(line) - len(line.lstrip())]
            source_lines.append(
                f"{indent}# INVALID ASSERTION REMOVED BY CONTRACT"
            )
        elif any(re.search(rf"\b{re.escape(name)}\b", line) for name in forbidden_set):
            indent = line[: len(line) - len(line.lstrip())]
            source_lines.append(
                f"{indent}# INVALID FAILURE LINE REMOVED BY CONTRACT"
            )
        else:
            source_lines.append(line)
    bounded_source = "\n".join(source_lines)
    if contract.get("atomic_owner_capsule"):
        atomic_failures = "\n".join(
            f"- {value}"
            for value in contract.get("all_validation_errors") or []
        ) or f"- {contract.get('failure') or 'Repair the supplied callable contract.'}"
        return ProjectEditPromptStage(
            key="function_repair",
            label=f"Repairing {symbol}",
            system_prompt=(
                "You are a senior Python callable repair worker. Every supplied "
                "field is authoritative and must be satisfied. Return exactly one "
                "complete replacement function or method with the exact signature. "
                "Change the executable statements responsible for every listed "
                "failure. An unchanged, AST-equivalent, formatting-only, placeholder, "
                "module, class, diff, Markdown, JSON, or explanatory response is "
                "invalid. Preserve unrelated behavior and use only supplied evidence, "
                "visible imports, owner state, arguments, locals, and builtins."
            ),
            user_prompt=f"""EXACT REPAIR OWNER
{symbol}

FAILURES THAT MUST ALL BE ABSENT AFTER THIS REPLACEMENT
{atomic_failures}

APPROVED OWNER CAPSULE
{json.dumps(
    contract.get("atomic_owner_capsule_payload") or {},
    ensure_ascii=True,
    separators=(",", ":"),
)}

EXACT SIGNATURE
{contract.get("signature") or ""}

CURRENT CALLABLE TO REPLACE
```python
{bounded_source}
```

AVAILABLE MODULE IMPORTS
```python
{imports}
```

RELEVANT OWNER STATE
```python
{state_context}
```

RELEVANT CALLERS
```python
{callsites}
```

FINAL CHECK BEFORE RESPONDING
Compare executable AST behavior against CURRENT CALLABLE TO REPLACE. If it is
equivalent or any listed failure remains, revise it now. Return only the complete
raw Python callable named {contract.get("callable_name") or ""}.
""",
            num_predict=max(
                512,
                min(1800, (len(bounded_source) // 2) + 256),
            ),
            model_tier="local_code",
            num_ctx=8192,
            timeout=120,
            no_progress_seconds=30,
            prefer_coder=True,
            coder_preference="standard",
            response_format="",
            metadata={
                "path": str(contract.get("path") or ""),
                "symbol": symbol,
                "signature_fingerprint": str(
                    contract.get("signature_fingerprint") or ""
                ),
                "owner_source": str(contract.get("source") or ""),
                "canonical_repair_contract": dict(contract),
                "atomic_prepared": True,
            },
        )
    return ProjectEditPromptStage(
        key="function_repair",
        label=f"Repairing {symbol}",
        system_prompt=(
            "You are a bounded senior Python function repair worker. Return exactly one complete "
            "replacement function or method. Preserve its exact signature and repair only the supplied "
            "failure. The replacement must be materially different from the supplied current "
            "implementation: returning the same body, an AST-equivalent body, or formatting-only "
            "changes is forbidden. Before responding, compare your replacement with the current "
            "implementation and confirm internally that an executable statement responsible for "
            "the failure changed. "
            + (
                "A verification callable may define a private local fixture class "
                "inside its own body, but must not return a class or add a module-level "
                "declaration. "
                if verification_callable
                else
                "Do not return or introduce a class, including a nested class inside "
                "the callable. When mutable closure state is needed, use a built-in "
                "mutable container captured by a nested function. "
            )
            + "Do not return a module, diff, Markdown, "
            "JSON, or explanation."
        ),
        user_prompt=f"""Original objective:
{contract.get("objective") or ""}

Callable owned by this worker:
{symbol}

Exact required signature:
{contract.get("signature") or ""}

Current implementation:
```python
{bounded_source}
```

Requirements owned by this file:
{requirements}

Imports already available in the module:
```python
{imports}
```

Available module symbols:
{module_symbols}
Symbols listed here because validation verified an installed public API owner may
be used even when their import is not present yet; deterministic import
normalization will add the verified owner import after this symbol repair.

Exact generated package interfaces already available:
```text
{generated_interfaces}
```
Call only methods shown in this interface readback; do not invent aliases or renamed variants.

Relevant sibling callables:
{sibling_symbols}

Sibling interfaces available to call:
```python
{sibling_signatures}
```

Owning class state initialization and class-level assignments:
```python
{state_context}
```
Preserve these container types and state invariants exactly.

Bounded callers and behavioral tests that define the input/output contract:
```python
{callsites}
```
Caller-local fixture names are evidence only. They do not exist inside the repaired callable and must not be copied.

Names proven invalid by the current failure and forbidden in the replacement:
{forbidden_names}

Assertion lines proven invalid by runtime validation and forbidden in the replacement:
{chr(10).join(sorted(invalid_assertion_lines)) or "(none)"}

Smallest matching disposable validation failure:
{contract.get("failure") or ""}

Complete owner validation snapshot:
{chr(10).join(contract.get("all_validation_errors") or [])}

Approved repair micro-plan:
```json
{plan_text}
```

Return one complete replacement callable named {contract.get("callable_name") or ""}.
Keep the exact parameter list, defaults, annotations, async form, and decorators.
Use only arguments, local names, builtins, visible imports, and available module symbols.
If a new standard-library helper is needed only here, import it locally inside the callable.
Fix the root cause and preserve behavior outside this callable. Return raw Python only.
MANDATORY PRE-RETURN CHECK: compare the proposed callable against Current implementation.
Do not respond until the proposed body is materially different and the changed executable
logic directly addresses Smallest matching disposable validation failure. An identical,
AST-equivalent, comment-only, whitespace-only, or formatting-only response is invalid.
If this callable is a test, keep the original objective and accepted behavior as the
specification. Do not weaken assertions, delete coverage, or replace requested observable
behavior with assertRaises unless the objective or contract explicitly requires that error.
""",
        model_tier="local_code",
        num_ctx=6144 if attempt > 1 else 5120,
        num_predict=1100 if attempt > 1 else 850,
        timeout=90,
        no_progress_seconds=20,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "path": str(contract.get("path") or ""),
            "symbol": symbol,
            "signature_fingerprint": str(contract.get("signature_fingerprint") or ""),
            "owner_source": str(contract.get("source") or ""),
            "canonical_repair_contract": dict(contract),
        },
    )


def build_project_edit_class_repair_stage(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    class_name: str,
    objective: str,
    validation_errors: list[str],
) -> ProjectEditPromptStage:
    """Build a bounded class-chunk repair for a newly generated file."""

    target_context: list[str] = []
    package_interfaces: list[str] = []
    for file_path, _original, source in generated_files:
        package_interfaces.append(
            summarize_project_edit_generated_interface(file_path, source)
        )
        if Path(file_path).resolve() != Path(path).resolve():
            continue
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            target_context.append(f"File: {file_path}\n```python\n{source}\n```")
            continue
        target_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if target_node is not None:
            class_source = ast.get_source_segment(source, target_node) or ast.unparse(target_node)
            target_context.append(f"File: {file_path}\n```python\n{class_source}\n```")
    return ProjectEditPromptStage(
        key="class_repair",
        label=f"Repairing class {class_name}",
        system_prompt=(
            "You are a bounded senior Python integration repair worker. Return exactly one "
            "complete replacement class declaration as raw Python. Do not return imports, a "
            "module, a diff, Markdown, JSON, or explanation."
        ),
        user_prompt=f"""Original objective:
{objective}

Class chunk to replace:
{class_name}

Exact current class source:
{chr(10).join(target_context) or "(class source unavailable)"}

Generated package interfaces:
{chr(10).join(package_interfaces)}

Complete deterministic validation failures:
- {chr(10).join(validation_errors)}

Repair this class as one coherent chunk. You may correct its constructor and method signatures when runtime proof
shows that the generated contract cannot represent the requested behavior. Preserve unrelated module-level records,
exceptions, functions, and classes. Use the exact visible APIs of sibling files. If a standard-library helper is
needed, import it locally inside the method that uses it. Do not invent exceptions or external APIs.
For an immutable record class, preserve actual immutability while correcting its fields so the requested producer,
storage, traversal, and execution operations can all use the same canonical record.
For a test class, repair setup and every affected test together, keep substantive coverage, call the production API
that directly owns each named behavior, and never weaken assertions merely to make the suite pass.
Return exactly one complete class named {class_name}.
""",
        model_tier="local_code",
        num_ctx=8192,
        num_predict=-1,
        timeout=120,
        no_progress_seconds=25,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "path": str(path),
            "symbol": str(class_name),
            "owner_source": "\n\n".join(target_context),
            "all_validation_errors": list(validation_errors),
            "full_objective": str(objective or ""),
        },
    )


def apply_project_edit_generated_class_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    class_name: str,
    replacement_response: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Splice one complete class replacement into a newly generated module."""

    replacement = str(replacement_response or "").strip()
    replacement = re.sub(r"^```(?:python|py)?\s*", "", replacement, flags=re.IGNORECASE)
    replacement = re.sub(r"\s*```$", "", replacement)
    try:
        replacement_tree = ast.parse(
            textwrap.dedent(replacement),
            filename=f"<class-repair:{class_name}>",
        )
    except SyntaxError as exc:
        return generated_files, [f"Class repair did not parse: {exc}"]
    declarations = [
        node
        for node in replacement_tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(declarations) != 1:
        return generated_files, [
            f"Class repair must contain exactly one class named {class_name}."
        ]
    class_node = declarations[0]
    placeholders = [
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_placeholder_callable(node)
    ]
    if placeholders:
        return generated_files, [
            f"Class repair contains placeholder methods: {', '.join(placeholders)}"
        ]
    class_source = ast.unparse(class_node)
    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).resolve() != Path(path).resolve():
            continue
        try:
            unresolved_before = set(
                _unresolved_generated_names(ast.parse(source, filename=path_text))
            )
        except SyntaxError as exc:
            return generated_files, [f"Generated class owner did not parse: {exc}"]
        matched, corrected, error = _edit_python_symbol_source(
            source,
            target_symbol=class_name,
            replacement=class_source,
            filename=path_text,
            operation="replace_symbol",
        )
        if not matched:
            return generated_files, [
                error or f"Could not replace generated class {class_name}."
            ]
        try:
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
        except (SyntaxError, ValueError) as exc:
            return generated_files, [f"Repaired class owner did not compile: {exc}"]
        corrected_records, _fixes = resolve_project_edit_standard_library_symbols(
            [(path_text, original, corrected)]
        )
        corrected = corrected_records[0][2]
        corrected_tree = ast.parse(corrected, filename=path_text)
        package_symbols: set[str] = set()
        for package_path, _package_original, package_source in generated_files:
            try:
                package_tree = ast.parse(package_source, filename=package_path)
            except SyntaxError:
                continue
            package_symbols.update(
                node.name
                for node in package_tree.body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
            )
        unresolved = sorted(
            (
                set(_unresolved_generated_names(corrected_tree))
                - unresolved_before
            )
            - package_symbols
        )
        unresolved = [
            name for name in unresolved if not _verified_installed_qt_symbol(name)
        ]
        if unresolved:
            return generated_files, [
                "Repaired class owner references undefined names: "
                + ", ".join(unresolved)
            ]
        updated[index] = (path_text, original, corrected)
        return updated, []
    return generated_files, [f"Generated class repair path was not found: {path}"]


def build_project_edit_class_set_repair_stage(
    generated_files: list[tuple[str, str, str]],
    *,
    class_targets: list[tuple[str, str]],
    objective: str,
    approved_contract: str,
    validation_errors: list[str],
    repair_attempt: int = 1,
) -> ProjectEditPromptStage:
    """Build one coherent repair decision returned as independent class chunks."""

    target_names = [class_name for _path, class_name in class_targets]
    target_context: list[str] = []
    package_interfaces = [
        summarize_project_edit_generated_interface(file_path, source)
        for file_path, _original, source in generated_files
    ]
    for target_path, class_name in class_targets:
        target_source = next(
            (
                source
                for file_path, _original, source in generated_files
                if Path(file_path).resolve() == Path(target_path).resolve()
            ),
            "",
        )
        try:
            target_tree = ast.parse(target_source, filename=target_path)
        except SyntaxError:
            target_context.append(
                f"File: {target_path}\n```python\n{target_source}\n```"
            )
            continue
        target_node = next(
            (
                node
                for node in target_tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if target_node is not None:
            class_source = (
                ast.get_source_segment(target_source, target_node)
                or ast.unparse(target_node)
            )
            target_context.append(
                f"File: {target_path}\n```python\n{class_source}\n```"
            )
    api_checklist: list[str] = []
    for target_path, class_name in class_targets:
        target_source = next(
            (
                source
                for file_path, _original, source in generated_files
                if file_path == target_path
            ),
            "",
        )
        try:
            target_tree = ast.parse(target_source)
        except SyntaxError:
            target_tree = ast.Module(body=[], type_ignores=[])
        target_class = next(
            (
                node
                for node in target_tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        signatures = [
            f"{child.name}({ast.unparse(child.args)})"
            for child in (target_class.body if target_class is not None else [])
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not child.name.startswith("__")
        ]
        consumer_calls: set[str] = set()
        for file_path, _original, source in generated_files:
            if not Path(file_path).name.startswith("test_"):
                continue
            try:
                consumer_tree = ast.parse(source)
            except SyntaxError:
                continue
            instance_names = {
                target.id
                for assignment in ast.walk(consumer_tree)
                if isinstance(assignment, ast.Assign)
                and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Name)
                and assignment.value.func.id == class_name
                for target in assignment.targets
                if isinstance(target, ast.Name)
            }
            consumer_calls.update(
                call.func.attr
                for call in ast.walk(consumer_tree)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in instance_names
                and not call.func.attr.startswith("_")
            )
        api_checklist.append(
            f"- {class_name}: current public signatures: "
            + (", ".join(signatures) or "(none)")
            + "; consumer-called methods that must remain available: "
            + (", ".join(sorted(consumer_calls)) or "(none)")
        )
    return ProjectEditPromptStage(
        key="class_set_repair",
        label="Repairing coherent class chunks",
        system_prompt=(
            "You are a senior Python package integration repair worker. Return raw Python "
            "containing exactly the requested complete class declarations plus only the "
            "imports newly required by those declarations. Do not return unrelated "
            "declarations, module execution, diffs, Markdown, JSON, or explanation. "
            "Approved helper declarations that are not explicitly listed under Class "
            "chunks to replace together are preserved separately and must not be returned."
        ),
        user_prompt=f"""Original objective:
{objective}

Authoritative validated shared contract:
```json
{approved_contract}
```

Class chunks to replace together:
{chr(10).join(f"- {name}" for name in target_names)}

Mandatory public API preservation checklist:
{chr(10).join(api_checklist)}

Exact current target class sources:
{chr(10).join(target_context) or "(class source unavailable)"}

Generated package interfaces:
{chr(10).join(package_interfaces)}

Complete deterministic validation failures:
- {chr(10).join(validation_errors)}

Repair these declarations as one coherent package decision. All record fields, constructors, public method
signatures, stored state, consumers, and tests must agree exactly. You may correct generated signatures and immutable
record fields when runtime evidence proves the generated contract cannot represent the request. Preserve actual
immutability where requested. Use public APIs to construct every tested success, failure, cycle, missing, recovery,
and immutability state. Do not weaken tests or invent unrelated exceptions. Return each requested class exactly once.
The validated shared contract is authoritative over every generated signature and field shown in the broken package.
{"This is a repeated failed repair. Reconstruct the class APIs and tests from the objective and authoritative contract; do not preserve a broken generated signature, record layout, fixture, or hard-coded domain sentinel merely because it appears in current code." if repair_attempt > 1 else ""}
""",
        model_tier="local_code",
        num_ctx=8192,
        num_predict=3000,
        timeout=150,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "class_targets": list(class_targets),
            "symbols": list(target_names),
            "owner_source": "\n\n".join(target_context),
            "all_validation_errors": list(validation_errors),
            "full_objective": str(objective or ""),
        },
    )


def apply_project_edit_generated_class_set_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    class_targets: list[tuple[str, str]],
    replacement_response: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Extract and splice a coherent response as separate class-only patches."""

    raw_text = str(replacement_response or "").strip()
    fenced_blocks = re.findall(
        r"```(?:python|py)?\s*(.*?)```",
        raw_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidates = fenced_blocks or [raw_text]
    by_name: dict[str, list[ast.ClassDef]] = {}
    imports_by_name: dict[str, list[ast.Import | ast.ImportFrom]] = {}
    parse_errors: list[SyntaxError] = []
    for candidate in candidates:
        text = candidate.strip()
        try:
            tree = ast.parse(text, filename="<class-set-repair>")
        except SyntaxError as exc:
            parse_errors.append(exc)
            tree = None
            lines = text.splitlines()
            for end in range(len(lines) - 1, 0, -1):
                try:
                    prefix_tree = ast.parse(
                        "\n".join(lines[:end]),
                        filename="<class-set-repair>",
                    )
                except SyntaxError:
                    continue
                if any(isinstance(node, ast.ClassDef) for node in prefix_tree.body):
                    tree = prefix_tree
                    break
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                by_name.setdefault(node.name, []).append(node)
                imports_by_name.setdefault(node.name, []).extend(
                    import_node
                    for import_node in tree.body
                    if isinstance(import_node, (ast.Import, ast.ImportFrom))
                )
    if not by_name and parse_errors:
        return generated_files, [
            f"Class-set repair did not parse: {parse_errors[-1]}"
        ]
    missing = [
        name
        for _path, name in class_targets
        if not by_name.get(name)
    ]
    if missing:
        return generated_files, [
            "Class-set repair is missing required target(s): "
            + ", ".join(missing)
        ]
    selected_classes = {
        name: max(
            by_name[name],
            key=lambda node: (
                sum(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for child in node.body
                ),
                len(ast.unparse(node)),
            ),
        )
        for _path, name in class_targets
    }
    updated = generated_files
    for path, class_name in class_targets:
        class_source = ast.unparse(selected_classes[class_name])
        updated, errors = apply_project_edit_generated_class_repair(
            updated,
            path=path,
            class_name=class_name,
            replacement_response=class_source,
        )
        if errors:
            return generated_files, errors
        required_imports = list(dict.fromkeys(
            ast.unparse(node)
            for node in imports_by_name.get(class_name, [])
        ))
        if required_imports:
            for index, (path_text, original, source) in enumerate(updated):
                if Path(path_text).resolve() != Path(path).resolve():
                    continue
                source_tree = ast.parse(source, filename=path_text)
                existing_imports = {
                    ast.unparse(node)
                    for node in source_tree.body
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                }
                missing_imports = [
                    statement
                    for statement in required_imports
                    if statement not in existing_imports
                ]
                if not missing_imports:
                    break
                lines = source.splitlines(keepends=True)
                insertion_line = 0
                for node in source_tree.body:
                    if (
                        isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and node is source_tree.body[0]
                    ) or isinstance(node, (ast.Import, ast.ImportFrom)):
                        insertion_line = max(
                            insertion_line,
                            int(node.end_lineno or node.lineno),
                        )
                        continue
                    break
                lines[insertion_line:insertion_line] = [
                    statement + "\n" for statement in missing_imports
                ]
                corrected = "".join(lines)
                compile(corrected, path_text, "exec")
                updated[index] = (path_text, original, corrected)
                break
    return updated, []


def build_project_edit_function_repair_plan_stage(
    contract: dict[str, Any],
) -> ProjectEditPromptStage:
    """Build a small reasoning stage that diagnoses one callable before coding."""

    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    generated_interfaces = "\n".join(
        contract.get("generated_interfaces") or []
    ) or "(none)"
    state_context = "\n\n".join(contract.get("state_context") or []) or "(none)"
    forbidden = ", ".join(contract.get("forbidden_names") or []) or "(none)"
    return ProjectEditPromptStage(
        key="function_repair_plan",
        label=f"Diagnosing {contract.get('symbol') or 'failing callable'}",
        system_prompt=(
            "You are a bounded code-repair diagnostician. Determine the root cause and a concrete "
            "algorithm for one callable from its signature, current body, callers, assertions, and "
            "failure. Return JSON only. Do not write Python."
        ),
        user_prompt=f"""Objective:
{contract.get("objective") or ""}

Callable and exact signature:
{contract.get("symbol") or ""}
{contract.get("signature") or ""}

Current body:
```python
{contract.get("source") or ""}
```

Caller and assertion evidence:
```python
{callsites}
```

Exact generated package interfaces:
```text
{generated_interfaces}
```

Owning class state initialization and class-level assignments:
```python
{state_context}
```

Validation failure:
{contract.get("failure") or ""}

Proven-invalid names that the implementation may not use:
{forbidden}

Return a minimal repair algorithm using only values actually available through the signature or visible module
interfaces. State exact output postconditions from the assertions. Do not invent paths, globals, fixtures, APIs,
or new parameters. Changing the callable signature is forbidden. If the existing inputs already contain the values
needed to compute an answer, derive it from those inputs instead of reacquiring unavailable external context.
Respect the concrete container types shown in class-state initialization. For query/report/find/list/order methods,
use local traversal state and local copies of counters; do not mutate persistent fields unless the contract explicitly
requires mutation. Identify how every requested observable state is made representable by the public input methods.
Keep every JSON string concise.
""",
        model_tier="local_semantic_verify",
        num_ctx=4096,
        num_predict=900,
        timeout=45,
        no_progress_seconds=15,
        prefer_coder=False,
        coder_preference="small",
        response_format=PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA,
    )


def parse_project_edit_function_repair_plan(
    response: str,
    *,
    contract: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a function-repair diagnosis before a coder receives it."""

    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError) as exc:
        return {}, [f"Function repair plan JSON did not parse: {exc}"]
    if not isinstance(payload, dict):
        return {}, ["Function repair plan must be a JSON object."]
    errors: list[str] = []
    root_cause = str(payload.get("root_cause") or "").strip()
    algorithm_steps = [
        str(value).strip()
        for value in payload.get("algorithm_steps") or []
        if str(value).strip()
    ]
    preserve = [
        str(value).strip()
        for value in payload.get("preserve") or []
        if str(value).strip()
    ]
    postconditions = [
        str(value).strip()
        for value in payload.get("postconditions") or []
        if str(value).strip()
    ]
    if not root_cause:
        errors.append("Function repair plan omitted the root cause.")
    if not algorithm_steps:
        errors.append("Function repair plan omitted concrete algorithm steps.")
    if not postconditions:
        errors.append("Function repair plan omitted output postconditions.")
    combined_algorithm = " ".join([root_cause, *algorithm_steps]).lower()
    normalized_algorithm = re.sub(r"[`'\"*]", "", combined_algorithm)
    if re.search(
        r"\b(?:add|introduce|append|change|modify|extend)\b.{0,40}\b"
        r"(?:parameter|argument|signature)\b",
        combined_algorithm,
    ):
        errors.append("Function repair plan changes the callable signature.")
    for forbidden in (contract or {}).get("forbidden_names") or []:
        name = str(forbidden).lower()
        if name not in normalized_algorithm:
            continue
        safe_mentions = (
            f"remove {name}",
            f"avoid {name}",
            f"avoid using {name}",
            f"without {name}",
            f"do not use {name}",
            f"undefined variable {name}",
            f"undefined name {name}",
            f"undefined variable '{name}'",
            f"undefined name '{name}'",
        )
        if not any(value in normalized_algorithm for value in safe_mentions):
            errors.append(
                f"Function repair plan still depends on proven-invalid name {forbidden}."
            )
    contract_evidence = " ".join([
        str((contract or {}).get("objective") or ""),
        *[str(value) for value in (contract or {}).get("requirements") or []],
        *[str(value) for value in (contract or {}).get("callsite_excerpts") or []],
    ]).lower()
    if re.search(r"\brename(?:d|s)?\b", contract_evidence):
        has_identity_basis = bool(
            re.search(r"\b(?:digest|hash|content|identity|snapshot value|mapping value)\b", normalized_algorithm)
        )
        has_candidate_sets = bool(
            re.search(r"\bremoved\b", normalized_algorithm)
            and re.search(r"\badded\b", normalized_algorithm)
        )
        if not (has_identity_basis and has_candidate_sets):
            errors.append(
                "Rename repair plan must compute removed old keys and added new keys, pair only those "
                "candidates when their snapshot digest/content values match, process them deterministically, "
                "and remove paired paths from the added and removed outputs."
            )
    return {
        "root_cause": root_cause,
        "algorithm_steps": algorithm_steps,
        "preserve": preserve,
        "postconditions": postconditions,
    }, errors


def resolve_project_edit_failure_symbol(
    generated_files: list[tuple[str, str, str]],
    validation_errors: list[str],
    *,
    deprioritized_symbols: set[str] | None = None,
) -> dict[str, str]:
    """Resolve the smallest generated callable implicated by a validation traceback."""

    failure_text = "\n".join(str(item) for item in validation_errors)
    deprioritized = set(deprioritized_symbols or ())
    if any(
        marker in failure_text.lower()
        for marker in (
            "new import could not be resolved",
            "missing its manifest dependency edge",
            "project-local import does not expose",
            "executes behavior at import time",
        )
    ):
        return {}
    placeholder_tests: list[str] = []
    for group in re.findall(
        r"Generated test methods (?:are placeholders|need stronger behavioral proof):\s*"
        r"([A-Za-z0-9_., ]+)",
        failure_text,
    ):
        placeholder_tests.extend(
            item.rsplit(".", 1)[-1].strip()
            for item in group.split(",")
            if item.strip()
        )
    placeholder_callables: list[str] = []
    for group in re.findall(
        r"Generated production callables are placeholders:\s*([A-Za-z0-9_., ]+)",
        failure_text,
    ):
        placeholder_callables.extend(
            item.strip() for item in group.split(",") if item.strip()
        )
    failing_tests = list(dict.fromkeys(
        placeholder_tests
        + re.findall(r"(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)", failure_text)
    ))
    if re.search(r"\bin setUp\b", failure_text):
        for path_text, _original, source in generated_files:
            if not _is_test_path(Path(path_text)) or Path(path_text).name not in failure_text:
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                setup = next(
                    (
                        node for node in class_node.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "setUp"
                    ),
                    None,
                )
                symbol = f"{class_node.name}.setUp"
                if setup is not None and symbol not in deprioritized:
                    return {
                        "path": path_text,
                        "symbol": symbol,
                        "source": ast.get_source_segment(source, setup) or "",
                    }
    if len(placeholder_tests) > 3:
        return {}
    for path_text, _original, source in generated_files:
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for target_symbol in placeholder_callables:
            parts = target_symbol.split(".")
            if len(parts) == 2:
                owner = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == parts[0]
                    ),
                    None,
                )
                node = next(
                    (
                        child
                        for child in (owner.body if owner is not None else [])
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[1]
                    ),
                    None,
                )
            else:
                node = next(
                    (
                        child
                        for child in tree.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[-1]
                    ),
                    None,
                )
            if node is not None and target_symbol not in deprioritized:
                return {
                    "path": path_text,
                    "symbol": target_symbol,
                    "source": ast.get_source_segment(source, node) or "",
                }
    for path_text, _original, source in generated_files:
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        ordered_placeholders = sorted(
            placeholder_tests,
            key=lambda name: any(symbol.endswith(f".{name}") for symbol in deprioritized),
        )
        fresh_placeholders = [
            name for name in ordered_placeholders
            if not any(symbol.endswith(f".{name}") for symbol in deprioritized)
        ]
        for failing_test in fresh_placeholders:
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                node = next(
                    (
                        child for child in class_node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == failing_test
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": f"{class_node.name}.{node.name}",
                        "source": ast.get_source_segment(source, node) or "",
                    }
    undefined_symbols = [
        item.strip()
        for group in re.findall(
            r"Generated callables reference undefined names in ([A-Za-z0-9_., ]+):",
            failure_text,
        )
        for item in group.split(",")
        if item.strip()
    ]
    contract_identifiers = [
        identifier.strip()
        for group in re.findall(
            r"Requested (?:removed|renamed) identifiers remain:\s*([A-Za-z0-9_., ]+)",
            failure_text,
        )
        for identifier in group.split(",")
        if identifier.strip()
    ]
    unrequested_symbols = [
        symbol.strip()
        for group in re.findall(
            r"Unrequested public callables were introduced:\s*([A-Za-z0-9_., ]+)",
            failure_text,
        )
        for symbol in group.split(",")
        if symbol.strip()
    ]
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for target_symbol in unrequested_symbols:
            parts = target_symbol.split(".")
            candidates = [
                node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == parts[-1]
            ]
            if candidates:
                node = candidates[0]
                return {
                    "path": path_text,
                    "symbol": target_symbol,
                    "source": ast.get_source_segment(source, node) or "",
                }
        for identifier in contract_identifiers:
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and _tree_uses_identifier(node, identifier)
                    ):
                        return {
                            "path": path_text,
                            "symbol": f"{class_node.name}.{node.name}",
                            "source": ast.get_source_segment(source, node) or "",
                        }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and _tree_uses_identifier(node, identifier)
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        ordered_undefined = sorted(
            (symbol for symbol in undefined_symbols if symbol not in deprioritized),
        )
        for target_symbol in ordered_undefined:
            parts = target_symbol.split(".")
            if len(parts) == 2:
                class_node = next(
                    (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == parts[0]),
                    None,
                )
                if class_node is not None:
                    node = next(
                        (
                            child for child in class_node.body
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and child.name == parts[1]
                        ),
                        None,
                    )
                    if node is not None:
                        return {
                            "path": path_text,
                            "symbol": target_symbol,
                            "source": ast.get_source_segment(source, node) or "",
                        }
            elif len(parts) == 1:
                node = next(
                    (
                        child for child in tree.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == parts[0]
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": target_symbol,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    production_frames = re.findall(
        r'File "[^"]*[\\/](?P<name>[^"\\/]+\.py)", line (?P<line>\d+), '
        r'in (?P<symbol>[A-Za-z_]\w*)',
        failure_text,
    )
    for filename, line_text, symbol_name in reversed(production_frames):
        for path_text, _original, source in generated_files:
            if (
                _is_test_path(Path(path_text))
                or Path(path_text).name.lower() != filename.lower()
            ):
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            line = int(line_text)
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == symbol_name
                        and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    ):
                        qualified = f"{class_node.name}.{node.name}"
                        if qualified not in deprioritized:
                            return {
                                "path": path_text,
                                "symbol": qualified,
                                "source": ast.get_source_segment(source, node) or "",
                            }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == symbol_name
                    and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    and node.name not in deprioritized
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    production_callables: dict[str, dict[str, str]] = {}
    for path_text, _original, source in generated_files:
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                production_callables[node.name] = {
                    "path": path_text,
                    "symbol": node.name,
                    "source": ast.get_source_segment(source, node) or "",
                }
    if "assertionerror" in failure_text.lower() and failing_tests:
        for path_text, _original, source in generated_files:
            if not _is_test_path(Path(path_text)):
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            for test_node in [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in failing_tests
            ]:
                called_production = list(dict.fromkeys(
                    child.func.id
                    for child in ast.walk(test_node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id in production_callables
                    and child.func.id not in deprioritized
                ))
                if len(called_production) == 1:
                    return production_callables[called_production[0]]
    for path_text, _original, source in generated_files:
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            if failure_text.lower().count("permissionerror") > 1:
                setup = next(
                    (
                        node for node in class_node.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "setUp"
                    ),
                    None,
                )
                if setup is not None:
                    return {
                        "path": path_text,
                        "symbol": f"{class_node.name}.setUp",
                        "source": ast.get_source_segment(source, setup) or "",
                    }
            ordered_failures = sorted(
                failing_tests,
                key=lambda name: f"{class_node.name}.{name}" in deprioritized,
            )
            for failing_test in ordered_failures:
                qualified = f"{class_node.name}.{failing_test}"
                if qualified in deprioritized:
                    continue
                node = next(
                    (
                        child for child in class_node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == failing_test
                    ),
                    None,
                )
                if node is not None:
                    return {
                        "path": path_text,
                        "symbol": qualified,
                        "source": ast.get_source_segment(source, node) or "",
                    }

    frames = re.findall(
        r'File "[^"]*[\\/](?P<name>[^"\\/]+\.py)", line (?P<line>\d+), in (?P<symbol>[A-Za-z_]\w*)',
        failure_text,
    )
    for filename, line_text, symbol_name in reversed(frames):
        for path_text, _original, source in generated_files:
            if Path(path_text).name.lower() != filename.lower():
                continue
            try:
                tree = ast.parse(source, filename=path_text)
            except SyntaxError:
                continue
            line = int(line_text)
            for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
                for node in class_node.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == symbol_name
                        and node.lineno <= line <= int(node.end_lineno or node.lineno)
                    ):
                        return {
                            "path": path_text,
                            "symbol": f"{class_node.name}.{node.name}",
                            "source": ast.get_source_segment(source, node) or "",
                        }
            for node in tree.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == symbol_name
                    and node.lineno <= line <= int(node.end_lineno or node.lineno)
                ):
                    return {
                        "path": path_text,
                        "symbol": node.name,
                        "source": ast.get_source_segment(source, node) or "",
                    }
    return {}


def apply_project_edit_generated_symbol_repair(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    symbol: str,
    replacement_response: str,
    forbidden_names: list[str] | None = None,
    approved_signature: str = "",
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Parse and splice one model-repaired callable into a generated file."""

    replacement = str(replacement_response or "").strip()
    replacement = re.sub(r"^```(?:python|py)?\s*", "", replacement, flags=re.IGNORECASE)
    replacement = re.sub(r"\s*```$", "", replacement)
    try:
        tree = ast.parse(textwrap.dedent(replacement), filename=f"<repair:{symbol}>")
        compile(tree, f"<repair:{symbol}>", "exec")
    except (SyntaxError, ValueError) as exc:
        return generated_files, [f"Repaired symbol did not parse and compile: {exc}"]
    expected_name = symbol.rsplit(".", 1)[-1]
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == expected_name
    ]
    if len(definitions) != 1:
        return generated_files, [f"Repair must return exactly one function named {expected_name}."]
    nested_definitions = [
        node
        for node in ast.walk(definitions[0])
        if node is not definitions[0]
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    is_disposable_test = Path(path).name.startswith("test_")
    existing_nested_names: set[str] = set()
    for current_path, _original, current_source in generated_files:
        if str(Path(current_path).resolve()) != str(Path(path).resolve()):
            continue
        try:
            current_tree = ast.parse(current_source, filename=current_path)
        except SyntaxError:
            break
        current_definition: ast.AST | None = None
        if "." in symbol:
            class_name, method_name = symbol.split(".", 1)
            class_node = next(
                (
                    node
                    for node in current_tree.body
                    if isinstance(node, ast.ClassDef)
                    and node.name == class_name
                ),
                None,
            )
            if class_node is not None:
                current_definition = next(
                    (
                        node
                        for node in class_node.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == method_name
                    ),
                    None,
                )
        else:
            current_definition = next(
                (
                    node
                    for node in current_tree.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == expected_name
                ),
                None,
            )
        if current_definition is not None:
            existing_nested_names = {
                str(getattr(node, "name", "") or "")
                for node in ast.walk(current_definition)
                if node is not current_definition
                and isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
            }
        break
    introduced_nested_classes = [
        node
        for node in nested_definitions
        if isinstance(node, ast.ClassDef)
        if str(getattr(node, "name", "") or "") not in existing_nested_names
    ]
    verification_callable = (
        expected_name in {"run_self_test", "self_test"}
        or expected_name.startswith("test_")
    )
    if (
        introduced_nested_classes
        and not is_disposable_test
        and not verification_callable
    ):
        nested_names = ", ".join(
            sorted({
                str(getattr(node, "name", "") or "")
                for node in introduced_nested_classes
            })
        )
        return generated_files, [
            (
                f"Repair for {expected_name} introduced local class declaration(s): "
                f"{nested_names}. Return only the owned callable implementation; "
                "new classes require their own declared symbol owners."
            )
        ]
    parsed_replacement = textwrap.dedent(replacement)
    replacement_lines = parsed_replacement.splitlines()
    replacement_definition = definitions[0]
    replacement_start = min(
        [int(replacement_definition.lineno)]
        + [
            int(decorator.lineno)
            for decorator in replacement_definition.decorator_list
        ]
    )
    replacement_end = int(
        replacement_definition.end_lineno or replacement_definition.lineno
    )
    replacement = "\n".join(
        replacement_lines[replacement_start - 1:replacement_end]
    ).strip()
    repaired_tree = ast.parse(replacement, filename=f"<repair:{symbol}>")
    repaired_definition = repaired_tree.body[0]
    if current_definition is not None and ast.dump(
        repaired_definition,
        include_attributes=False,
    ) == ast.dump(
        current_definition,
        include_attributes=False,
    ):
        return generated_files, [
            (
                f"Repair response for {symbol} is AST-equivalent to the "
                "rejected source."
            )
        ]
    meaningful_body = [
        statement
        for statement in repaired_definition.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if meaningful_body and all(
        isinstance(statement, ast.Pass)
        or (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is Ellipsis
        )
        for statement in meaningful_body
    ):
        return generated_files, [f"Repaired symbol {expected_name} contains a placeholder pass body."]
    forbidden_set = set(forbidden_names or ())
    retained_forbidden = sorted(
        {
            node.id
            for node in ast.walk(repaired_definition)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in forbidden_set
        }
        | {
            node.attr
            for node in ast.walk(repaired_definition)
            if isinstance(node, ast.Attribute)
            and node.attr in forbidden_set
        }
    )
    if retained_forbidden:
        return generated_files, [
            f"Repaired symbol {expected_name} retained proven-invalid names: "
            + ", ".join(retained_forbidden)
        ]

    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).resolve() != Path(path).resolve():
            continue
        try:
            owner_tree = ast.parse(source, filename=path_text)
        except SyntaxError as exc:
            source_lines = source.splitlines(keepends=True)
            target_indent = ""
            target_start = -1
            target_end = len(source_lines)
            class_name = symbol.split(".", 1)[0] if "." in symbol else ""
            class_indent = -1
            active_class = ""
            for line_index, line in enumerate(source_lines):
                stripped = line.lstrip()
                if not stripped:
                    continue
                indent_text = line[:len(line) - len(stripped)]
                indent_size = len(indent_text.expandtabs(4))
                class_match = re.match(
                    r"class\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                    stripped,
                )
                if class_match:
                    active_class = class_match.group(1)
                    class_indent = indent_size
                    continue
                if active_class and indent_size <= class_indent:
                    active_class = ""
                    class_indent = -1
                function_match = re.match(
                    rf"(?:async\s+)?def\s+{re.escape(expected_name)}\s*\(",
                    stripped,
                )
                if not function_match:
                    continue
                if class_name and active_class != class_name:
                    continue
                if not class_name and active_class:
                    continue
                target_indent = indent_text
                target_start = line_index
                while (
                    target_start > 0
                    and source_lines[target_start - 1].lstrip().startswith("@")
                    and source_lines[target_start - 1].startswith(target_indent)
                ):
                    target_start -= 1
                for following_index in range(line_index + 1, len(source_lines)):
                    following = source_lines[following_index]
                    if not following.strip():
                        continue
                    following_indent = len(following) - len(following.lstrip())
                    if following_indent <= len(target_indent):
                        target_end = following_index
                        break
                break
            if target_start < 0:
                return generated_files, [
                    f"Generated repair owner did not parse and lexical owner "
                    f"{symbol} was not found: {exc}"
                ]
            indented_replacement = "\n".join(
                target_indent + line if line.strip() else ""
                for line in replacement.splitlines()
            ).rstrip() + "\n"
            corrected = "".join([
                *source_lines[:target_start],
                indented_replacement,
                *source_lines[target_end:],
            ])
            try:
                compile(ast.parse(corrected, filename=path_text), path_text, "exec")
            except (SyntaxError, ValueError) as repaired_exc:
                return generated_files, [
                    f"Lexical repair for {symbol} did not restore module syntax: "
                    f"{repaired_exc}"
                ]
            updated[index] = (path_text, original, corrected)
            return updated, []
        symbol_parts = symbol.split(".")
        if len(symbol_parts) == 2:
            owner_class = next(
                (
                    node
                    for node in owner_tree.body
                    if isinstance(node, ast.ClassDef) and node.name == symbol_parts[0]
                ),
                None,
            )
            original_definitions = [
                node
                for node in (owner_class.body if owner_class is not None else [])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == expected_name
            ]
        else:
            original_definitions = [
                node
                for node in owner_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == expected_name
            ]
        if len(original_definitions) != 1:
            return generated_files, [
                f"Generated repair owner does not contain exactly one {expected_name} callable."
            ]
        original_definition = original_definitions[0]
        def argument_shape(arguments: ast.arguments) -> tuple[Any, ...]:
            return (
                tuple(item.arg for item in arguments.posonlyargs),
                tuple(item.arg for item in arguments.args),
                arguments.vararg.arg if arguments.vararg else "",
                tuple(item.arg for item in arguments.kwonlyargs),
                arguments.kwarg.arg if arguments.kwarg else "",
                tuple(
                    ast.dump(item, include_attributes=False)
                    for item in arguments.defaults
                ),
                tuple(
                    ast.dump(item, include_attributes=False)
                    if item is not None else ""
                    for item in arguments.kw_defaults
                ),
            )

        approved_definition: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        if approved_signature:
            try:
                approved_tree = ast.parse(
                    approved_signature.rstrip().rstrip(":")
                    + ":\n    pass",
                    filename=f"<approved:{symbol}>",
                )
                approved_candidate = approved_tree.body[0]
                if isinstance(
                    approved_candidate,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    approved_definition = approved_candidate
            except (IndexError, SyntaxError):
                approved_definition = None
        approved_signature_correction = bool(
            approved_definition is not None
            and argument_shape(original_definition.args)
            != argument_shape(approved_definition.args)
            and argument_shape(repaired_definition.args)
            == argument_shape(approved_definition.args)
        )
        if (
            original_definition.decorator_list
            and not repaired_definition.decorator_list
            and not approved_signature_correction
        ):
            original_decorators = [
                ast.get_source_segment(source, decorator) or ast.unparse(decorator)
                for decorator in original_definition.decorator_list
            ]
            replacement = "\n".join([
                *(
                    decorator
                    if decorator.lstrip().startswith("@")
                    else "@" + decorator
                    for decorator in original_decorators
                ),
                replacement,
            ])
            repaired_tree = ast.parse(
                replacement,
                filename=f"<repair:{symbol}>",
            )
            repaired_definition = repaired_tree.body[0]
        if isinstance(original_definition, ast.AsyncFunctionDef) != isinstance(
            repaired_definition, ast.AsyncFunctionDef
        ):
            return generated_files, [f"Repair changed async form for {symbol}."]

        if argument_shape(original_definition.args) != argument_shape(
            repaired_definition.args
        ) and not approved_signature_correction:
            return generated_files, [f"Repair changed the callable signature for {symbol}."]

        original_parameters = [
            *original_definition.args.posonlyargs,
            *original_definition.args.args,
            *original_definition.args.kwonlyargs,
            *(
                [original_definition.args.vararg]
                if original_definition.args.vararg
                else []
            ),
            *(
                [original_definition.args.kwarg]
                if original_definition.args.kwarg
                else []
            ),
        ]
        repaired_parameters = [
            *repaired_definition.args.posonlyargs,
            *repaired_definition.args.args,
            *repaired_definition.args.kwonlyargs,
            *(
                [repaired_definition.args.vararg]
                if repaired_definition.args.vararg
                else []
            ),
            *(
                [repaired_definition.args.kwarg]
                if repaired_definition.args.kwarg
                else []
            ),
        ]
        for original_parameter, repaired_parameter in zip(
            original_parameters,
            repaired_parameters,
        ):
            if (
                original_parameter.annotation is not None
                and ast.dump(
                    original_parameter.annotation,
                    include_attributes=False,
                )
                != ast.dump(
                    repaired_parameter.annotation,
                    include_attributes=False,
                )
            ):
                return generated_files, [
                    f"Repair changed the annotation for "
                    f"{symbol}.{original_parameter.arg}."
                ]
        original_return = (
            ast.dump(original_definition.returns, include_attributes=False)
            if original_definition.returns is not None
            else ""
        )
        repaired_return = (
            ast.dump(repaired_definition.returns, include_attributes=False)
            if repaired_definition.returns is not None
            else ""
        )
        if (
            original_return
            and original_return != repaired_return
            and str(original or "").strip()
        ):
            return generated_files, [f"Repair changed the return annotation for {symbol}."]
        if [
            ast.dump(item, include_attributes=False)
            for item in original_definition.decorator_list
        ] != [
            ast.dump(item, include_attributes=False)
            for item in repaired_definition.decorator_list
        ]:
            return generated_files, [f"Repair changed decorators for {symbol}."]
        unresolved_before = set(_unresolved_generated_names(owner_tree))
        matched, corrected, error = _edit_python_symbol_source(
            source,
            target_symbol=symbol,
            replacement=replacement,
            filename=path_text,
            operation="replace_symbol",
        )
        if not matched:
            return generated_files, [error or f"Could not replace generated symbol {symbol}."]
        try:
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
        except (SyntaxError, ValueError) as exc:
            return generated_files, [f"Repaired owner module did not compile: {exc}"]
        introduced_unresolved = sorted(
            set(_unresolved_generated_names(corrected_tree)) - unresolved_before
        )
        introduced_unresolved = [
            name
            for name in introduced_unresolved
            if not _verified_installed_qt_symbol(name)
        ]
        introduced_unresolved = [
            name
            for name in introduced_unresolved
            if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
        ]
        if introduced_unresolved:
            resolved_records, _import_fixes = (
                resolve_project_edit_standard_library_symbols([
                    (path_text, original, corrected)
                ])
            )
            corrected = resolved_records[0][2]
            corrected_tree = ast.parse(corrected, filename=path_text)
            compile(corrected_tree, path_text, "exec")
            introduced_unresolved = sorted(
                set(_unresolved_generated_names(corrected_tree)) - unresolved_before
            )
        invented_exceptions = {
            name
            for name in introduced_unresolved
            if name.endswith(("Error", "Exception"))
        }
        if introduced_unresolved and invented_exceptions == set(introduced_unresolved):
            class _UseRuntimeError(ast.NodeTransformer):
                def visit_Name(self, child: ast.Name) -> ast.AST:
                    if (
                        isinstance(child.ctx, ast.Load)
                        and child.id in invented_exceptions
                    ):
                        return ast.copy_location(
                            ast.Name(id="RuntimeError", ctx=child.ctx),
                            child,
                        )
                    return child

            corrected_tree = _UseRuntimeError().visit(corrected_tree)
            ast.fix_missing_locations(corrected_tree)
            corrected = ast.unparse(corrected_tree).rstrip() + "\n"
            compile(corrected_tree, path_text, "exec")
            introduced_unresolved = sorted(
                set(_unresolved_generated_names(corrected_tree)) - unresolved_before
            )
        if introduced_unresolved:
            return generated_files, [
                "Repaired owner module introduces undefined names: "
                + ", ".join(introduced_unresolved)
            ]
        updated[index] = (path_text, original, corrected)
        return updated, []
    return generated_files, [f"Generated repair path was not found: {path}"]


def isolate_project_edit_generated_test_fixture(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Give a no-argument generated test fixture a disposable filesystem path."""

    generated_classes = {
        node.name
        for path_text, _original, source in generated_files
        if not _is_test_path(Path(path_text))
        for node in ast.parse(source, filename=path_text).body
        if isinstance(node, ast.ClassDef)
    }
    updated = list(generated_files)
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        tree = ast.parse(source, filename=path_text)
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            setup = next(
                (
                    node for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "setUp"
                ),
                None,
            )
            if setup is None:
                continue
            fixture_assignments = [
                node
                for node in setup.body
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in generated_classes
                and not node.value.args
                and not node.value.keywords
            ]
            if not fixture_assignments:
                continue
            assignment = fixture_assignments[0]
            target_text = ast.get_source_segment(source, assignment.targets[0]) or "self.tool"
            class_name = assignment.value.func.id
            replacement = (
                "def setUp(self):\n"
                "    import os\n"
                "    import tempfile\n"
                "    self._generated_workspace = tempfile.TemporaryDirectory()\n"
                "    self.addCleanup(self._generated_workspace.cleanup)\n"
                f"    {target_text} = {class_name}("
                "os.path.join(self._generated_workspace.name, 'generated_test_data.json'))\n"
            )
            matched, corrected, error = _edit_python_symbol_source(
                source,
                target_symbol=f"{class_node.name}.setUp",
                replacement=replacement,
                filename=path_text,
                operation="replace_symbol",
            )
            if not matched:
                return generated_files, [error or f"Could not isolate {class_node.name}.setUp."]
            updated[index] = (path_text, original, corrected)
            return updated, [f"{Path(path_text).name}:{class_node.name}.setUp"]
    return generated_files, []


def normalize_project_edit_async_test_lifecycle(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Use unittest's recognized async fixture lifecycle names."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        changed = False
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            is_isolated_async_case = any(
                (
                    isinstance(base, ast.Attribute)
                    and base.attr == "IsolatedAsyncioTestCase"
                )
                or (
                    isinstance(base, ast.Name)
                    and base.id == "IsolatedAsyncioTestCase"
                )
                for base in class_node.bases
            )
            if not is_isolated_async_case:
                continue
            for method in class_node.body:
                if not isinstance(method, ast.AsyncFunctionDef):
                    continue
                replacement = {
                    "setUp": "asyncSetUp",
                    "tearDown": "asyncTearDown",
                }.get(method.name)
                if not replacement:
                    continue
                fixes.append(
                    f"{Path(path_text).name}: renamed async {method.name} to {replacement}"
                )
                method.name = replacement
                changed = True
        if changed:
            ast.fix_missing_locations(tree)
            updated[index] = (
                path_text,
                original,
                ast.unparse(tree).rstrip() + "\n",
            )
    return updated, fixes


def build_project_edit_multi_file_candidate(
    generated_files: list[tuple[str, str, str]],
) -> str:
    """Compose validated full-file worker outputs into one structured candidate."""

    changes = [
        {
            "action": "modify" if original else "create",
            "path": path,
            "target_symbol": "",
            "original_content": original,
            "new_content": generated,
        }
        for path, original, generated in generated_files
    ]
    return json.dumps(
        {
            "changes": changes,
            "report": {
                "changed": [Path(path).name for path, _original, _generated in generated_files],
                "reused": [],
                "verification": ["parse", "compile", "cross-file imports", "focused unittest"],
                "remaining_gaps": [],
                "requirement_coverage": [],
            },
            "blocked_reason": "",
        },
        ensure_ascii=True,
    )


def stabilize_project_edit_import_cycles(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Move project-local imports into their use sites when generated modules form a cycle."""

    root = Path(project_root).resolve()
    module_by_path: dict[str, str] = {}
    source_by_module: dict[str, str] = {}
    record_by_module: dict[str, tuple[str, str, str]] = {}
    for record in generated_files:
        path_text, original, generated = record
        path = Path(path_text).resolve()
        try:
            relative = path.relative_to(root).with_suffix("")
        except ValueError:
            continue
        module = ".".join(relative.parts)
        module_by_path[path_text] = module
        source_by_module[module] = generated
        record_by_module[module] = (path_text, original, generated)

    graph: dict[str, set[str]] = {module: set() for module in source_by_module}
    imports_by_module: dict[str, list[ast.ImportFrom]] = {}
    for module, source in source_by_module.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        local_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 0
            and str(node.module or "") in source_by_module
        ]
        imports_by_module[module] = local_imports
        graph[module].update(str(node.module) for node in local_imports)

    def reaches(start: str, target: str) -> bool:
        pending = [start]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(graph.get(current, set()) - seen)
        return False

    stabilized = list(generated_files)
    fixes: list[str] = []
    for module, import_nodes in imports_by_module.items():
        cyclic_nodes = [
            node for node in import_nodes
            if reaches(str(node.module), module)
        ]
        if not cyclic_nodes:
            continue
        path_text, original, source = record_by_module[module]
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, int, str]] = []
        callable_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                callable_nodes.append(node)
            elif isinstance(node, ast.ClassDef):
                callable_nodes.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        for import_node in cyclic_nodes:
            local_names = {alias.asname or alias.name for alias in import_node.names}
            non_callable_body = [
                node
                for node in tree.body
                if node is not import_node
                and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            if any(
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in local_names
                for statement in non_callable_body
                for node in ast.walk(statement)
            ):
                continue
            import_text = "".join(lines[import_node.lineno - 1: import_node.end_lineno]).strip()
            users = [
                function
                for function in callable_nodes
                if any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in local_names
                    for node in ast.walk(function)
                )
            ]
            edits.append((import_node.lineno - 1, import_node.end_lineno, ""))
            for function in users:
                body = list(function.body)
                insertion_line = function.lineno
                if body:
                    first = body[0]
                    insertion_line = first.lineno - 1
                    if (
                        isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)
                    ):
                        insertion_line = int(first.end_lineno or first.lineno)
                indent = " " * (int(function.col_offset or 0) + 4)
                insertion = "".join(indent + part + "\n" for part in import_text.splitlines())
                edits.append((insertion_line, insertion_line, insertion))
            fixes.append(
                f"{Path(path_text).name}: moved cyclic import from {import_node.module} "
                f"into {len(users)} callable use site(s)"
            )
        for start, end, replacement in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
            lines[start:end] = [replacement] if replacement else []
        corrected = "".join(lines)
        for index, record in enumerate(stabilized):
            if record[0] == path_text:
                stabilized[index] = (path_text, original, corrected)
                break
    return stabilized, fixes


def resolve_project_edit_cross_file_symbols(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Wire uniquely owned generated symbols into callables that reference them."""

    root = Path(project_root).resolve()
    module_by_path: dict[str, str] = {}
    owners: dict[str, list[str]] = {}
    trees: dict[str, ast.Module] = {}
    for path_text, _original, generated in generated_files:
        try:
            module = ".".join(Path(path_text).resolve().relative_to(root).with_suffix("").parts)
            tree = ast.parse(generated, filename=path_text)
        except (ValueError, SyntaxError):
            continue
        module_by_path[path_text] = module
        trees[path_text] = tree
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owners.setdefault(node.name, []).append(module)

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        tree = trees.get(path_text)
        module = module_by_path.get(path_text)
        if tree is None or module is None:
            continue
        unresolved = set(_unresolved_generated_names(tree))
        uniquely_owned = {
            name: modules[0]
            for name, modules in owners.items()
            if name in unresolved and len(modules) == 1 and modules[0] != module
        }
        if not uniquely_owned:
            continue
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, str]] = []
        callables = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for function in callables:
            used = sorted({
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in uniquely_owned
            })
            if not used:
                continue
            insertion_line = function.lineno
            if function.body:
                first = function.body[0]
                insertion_line = first.lineno - 1
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    insertion_line = int(first.end_lineno or first.lineno)
            indent = " " * (int(function.col_offset or 0) + 4)
            imports = "".join(
                f"{indent}from {uniquely_owned[name]} import {name}\n"
                for name in used
            )
            edits.append((insertion_line, imports))
            fixes.extend(
                f"{Path(path_text).name}:{function.name} -> {uniquely_owned[name]}.{name}"
                for name in used
            )
        for insertion_line, import_text in sorted(edits, reverse=True):
            lines[insertion_line:insertion_line] = [import_text]
        updated[index] = (path_text, original, "".join(lines))
    return updated, fixes


def ensure_project_edit_requested_docstrings(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
    force: bool = False,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Insert baseline docstrings for every generated public callable."""
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, str]] = []
        for name, node in _public_definition_map(tree).items():
            if ast.get_docstring(node) or not getattr(node, "body", None):
                continue
            bare_name = name.rsplit(".", 1)[-1]
            words = re.sub(r"(?<!^)(?=[A-Z])", " ", bare_name).replace("_", " ").strip().lower()
            description = (
                f"Provide {words} behavior."
                if isinstance(node, ast.ClassDef)
                else f"{words.capitalize()}."
            )
            indent = " " * (int(node.col_offset or 0) + 4)
            first_body_node = node.body[0]
            insertion_lineno = int(first_body_node.lineno)
            if isinstance(first_body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                insertion_lineno = min(
                    [insertion_lineno]
                    + [
                        int(decorator.lineno)
                        for decorator in first_body_node.decorator_list
                    ]
                )
            edits.append((insertion_lineno - 1, f'{indent}"""{description}"""\n'))
            fixes.append(f"{Path(path_text).name}:{name}")
        for insertion_line, docstring in sorted(edits, reverse=True):
            lines[insertion_line:insertion_line] = [docstring]
        updated[index] = (path_text, original, "".join(lines))
    return updated, fixes


def enforce_project_edit_explicit_cleanup(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply explicit identifier cleanup without rewriting unrelated source."""

    removed_identifiers, rename_pairs = _requested_identifier_contracts(request_prompt)
    if not removed_identifiers and not rename_pairs:
        return generated_files, []

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
            original_tree = ast.parse(original, filename=path_text) if original else ast.parse("")
        except SyntaxError:
            continue

        lines = source.splitlines(keepends=True)
        deletion_ranges: list[tuple[int, int, str]] = []
        for identifier in removed_identifiers:
            statements = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.stmt)
                and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and _tree_uses_identifier(node, identifier)
            ]
            for statement in sorted(
                statements,
                key=lambda node: (int(node.end_lineno or node.lineno) - node.lineno, node.lineno),
            ):
                statement_range = (
                    statement.lineno - 1,
                    int(statement.end_lineno or statement.lineno),
                    identifier,
                )
                if not any(
                    statement_range[0] <= start and statement_range[1] >= end
                    for start, end, _name in deletion_ranges
                ):
                    deletion_ranges.append(statement_range)

        for start, end, identifier in sorted(deletion_ranges, reverse=True):
            del lines[start:end]
            fixes.append(f"{Path(path_text).name}: removed statement using {identifier}")
        cleaned = "".join(lines)

        rename_map = dict(rename_pairs)
        if rename_map:
            rewritten = [
                tokenize.TokenInfo(
                    token.type,
                    rename_map.get(token.string, token.string)
                    if token.type == tokenize.NAME else token.string,
                    token.start,
                    token.end,
                    token.line,
                )
                for token in tokenize.generate_tokens(io.StringIO(cleaned).readline)
            ]
            cleaned = tokenize.untokenize(rewritten)
            for source_name, target_name in rename_pairs:
                if _tree_uses_identifier(tree, source_name) and source_name not in removed_identifiers:
                    fixes.append(f"{Path(path_text).name}: renamed {source_name} to {target_name}")

        try:
            cleaned_tree = ast.parse(cleaned, filename=path_text)
        except SyntaxError:
            continue
        before_defs = _public_definition_map(original_tree)
        after_defs = _public_definition_map(cleaned_tree)
        requested_symbols = _requested_public_symbol_names(request_prompt)
        unrequested_nodes = [
            node
            for name, node in after_defs.items()
            if name not in before_defs
            and name.rsplit(".", 1)[-1] not in requested_symbols
            and not re.search(
                rf"\b{re.escape(name.rsplit('.', 1)[-1])}\b",
                request_prompt,
                flags=re.IGNORECASE,
            )
        ]
        cleaned_lines = cleaned.splitlines(keepends=True)
        for node in sorted(unrequested_nodes, key=lambda item: item.lineno, reverse=True):
            del cleaned_lines[node.lineno - 1:int(node.end_lineno or node.lineno)]
            fixes.append(f"{Path(path_text).name}: removed unrequested public {node.name}")
        final_source = "".join(cleaned_lines).rstrip() + "\n"
        try:
            compile(ast.parse(final_source, filename=path_text), path_text, "exec")
        except (SyntaxError, ValueError):
            continue
        updated[index] = (path_text, original, final_source)
    return updated, fixes


def resolve_project_edit_standard_library_symbols(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str | None = None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """
    Add known standard-library imports required by otherwise complete generated code.
    Also normalize imports when local modules expose symbols through dependencies.
    """

    symbol_imports = {
        "AsyncMock": "from unittest.mock import AsyncMock",
        "MagicMock": "from unittest.mock import MagicMock",
        "Mock": "from unittest.mock import Mock",
        "NamedTemporaryFile": "from tempfile import NamedTemporaryFile",
        "TemporaryDirectory": "from tempfile import TemporaryDirectory",
        "json": "import json",
        "os": "import os",
        "tempfile": "import tempfile",
        "unittest": "import unittest",
        "mock": "from unittest import mock",
        "patch": "from unittest.mock import patch",
    }
    import typing as typing_module

    typing_symbols = set(getattr(typing_module, "__all__", ()))
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        source, repair_fixes = _repair_local_module_fallback_imports(
            source,
            target_path=Path(path_text),
            project_root=project_root,
        )
        if repair_fixes:
            fixes.extend(repair_fixes)
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        unresolved = set(_unresolved_generated_names(tree))
        updated[index] = (path_text, original, source)
        module_bindings = {
            alias.asname or (
                alias.name.split(".", 1)[0]
                if isinstance(node, ast.Import)
                else alias.name
            )
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if alias.name != "*"
        }
        loaded_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        unresolved.update(
            name
            for name in loaded_names & symbol_imports.keys()
            if name not in module_bindings
        )
        imports = [
            symbol_imports[name]
            for name in sorted(unresolved & symbol_imports.keys())
        ]
        imports.extend(
            f"import {name}"
            for name in sorted(unresolved & set(getattr(sys, "stdlib_module_names", ())))
            if name not in symbol_imports
        )
        imports.extend(
            f"from typing import {name}"
            for name in sorted(unresolved & typing_symbols)
            if name not in module_bindings
        )
        annotation_roots: list[ast.AST] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                annotation_roots.append(node.annotation)
            elif isinstance(node, ast.AnnAssign):
                annotation_roots.append(node.annotation)
            elif isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ) and node.returns is not None:
                annotation_roots.append(node.returns)
        annotation_names = {
            child.id
            for annotation in annotation_roots
            for child in ast.walk(annotation)
            if isinstance(child, ast.Name)
        }
        inferred_typevars = sorted(
            name
            for name in unresolved & annotation_names
            if re.fullmatch(
                r"(?:[TUVK]|KT|VT)(?:_(?:co|contra))?",
                name,
            )
        )
        if inferred_typevars:
            if "TypeVar" not in module_bindings:
                imports.append("from typing import TypeVar")
            imports.extend(
                f'{name} = TypeVar("{name}")'
                for name in inferred_typevars
            )
        if not imports:
            continue
        lines = source.splitlines(keepends=True)
        insertion = 1 if lines and re.match(r"^#.*coding[:=]", lines[0]) else 0
        while insertion < len(lines) and (
            not lines[insertion].strip()
            or lines[insertion].startswith("import ")
            or lines[insertion].startswith("from ")
        ):
            insertion += 1
        lines[insertion:insertion] = [statement + "\n" for statement in imports]
        updated[index] = (path_text, original, "".join(lines))
        fixes.extend(f"{Path(path_text).name}: added {statement}" for statement in imports)
    return updated, fixes


def _repair_local_module_fallback_imports(
    source: str,
    *,
    target_path: Path,
    project_root: str | None,
) -> tuple[str, list[str]]:
    """
    Replace from-imports that target a local module but request symbols that are
    only exposed through that module's imported dependencies.
    """
    try:
        tree = ast.parse(source, filename=str(target_path))
    except SyntaxError:
        return source, []

    replacements: list[tuple[int, int, list[str]]] = []
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.lineno is None or node.end_lineno is None:
            continue
        if node.module is None:
            continue

        local_path = _local_module_path(
            target_path,
            node.module,
            0,
            project_root=project_root,
            candidate_paths=set(),
        )
        if local_path is None:
            continue
        try:
            local_source = local_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            local_source = None

        if local_source is None:
            continue

        keep: list[ast.alias] = []
        fallback: dict[str, list[ast.alias]] = {}
        for alias in node.names:
            if _local_module_exports(
                local_path,
                alias.name,
                source_override=local_source,
            ):
                keep.append(alias)
                continue
            fallback_module = _resolve_local_module_symbol_fallback(
                local_path,
                local_source,
                alias.name,
            )
            if fallback_module is None:
                keep.append(alias)
                continue
            fallback.setdefault(fallback_module, []).append(alias)

        if not fallback:
            continue

        replacement_lines: list[str] = []
        if keep:
            keep_text = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in keep
            )
            replacement_lines.append(f"from {node.module} import {keep_text}")
        for fallback_module, fallback_aliases in sorted(fallback.items()):
            alias_text = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in fallback_aliases
            )
            replacement_lines.append(f"from {fallback_module} import {alias_text}")

        replacements.append((node.lineno - 1, node.end_lineno, replacement_lines))

    if not replacements:
        return source, []

    for start, end, replacement_lines in sorted(replacements, reverse=True):
        lines[start:end] = [f"{item}\n" for item in replacement_lines]
    return "".join(lines), [
        f"{target_path.name}: rewrote local imports using fallback symbol providers."
    ]


def remove_project_edit_unused_imports(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove unused generated import aliases without discarding used siblings."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).name == "__init__.py":
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        loaded_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        module_import_ids = {
            id(node) for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        module_bindings = {
            alias.asname or (
                alias.name.split(".", 1)[0]
                if isinstance(node, ast.Import)
                else alias.name
            )
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if alias.name != "*"
        }
        replacements: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            kept_aliases = [
                alias
                for alias in node.names
                if alias.name == "*"
                or (
                    alias.asname or (
                        alias.name.split(".", 1)[0]
                        if isinstance(node, ast.Import)
                        else alias.name
                    )
                ) in loaded_names
            ]
            bindings = [
                alias.asname or (
                    alias.name.split(".", 1)[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                for alias in node.names
                if alias.name != "*"
            ]
            if id(node) not in module_import_ids and set(bindings) <= module_bindings:
                kept_aliases = []
            if len(kept_aliases) == len(node.names):
                continue
            if kept_aliases:
                node.names = kept_aliases
                replacement = ast.unparse(node)
            else:
                replacement = ""
            replacements.append((
                node.lineno - 1,
                int(node.end_lineno or node.lineno),
                replacement,
            ))
        if not replacements:
            continue
        fixes_start = len(fixes)
        lines = source.splitlines(keepends=True)
        for start, end, replacement in sorted(replacements, reverse=True):
            lines[start:end] = [replacement + "\n"] if replacement else []
            fixes.append(f"{Path(path_text).name}: removed unused import alias")
        final_source = "".join(lines)
        try:
            compile(
                ast.parse(final_source, filename=path_text),
                path_text,
                "exec",
            )
        except (SyntaxError, ValueError):
            del fixes[fixes_start:]
            continue
        updated[index] = (path_text, original, final_source)
    return updated, fixes


def enforce_project_edit_requested_test_contracts(
    generated_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Materialize explicit path-related test contracts from the request."""

    prompt = str(request_prompt or "")
    expanduser_match = re.search(
        r"os\.path\.expanduser\(\s*(['\"])(?P<path>.+?)\1\s*\)",
        prompt,
    )
    wants_invalid_json = "invalid json" in prompt.lower()
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if not _is_test_path(Path(path_text)):
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        class_names = [
            alias.asname or alias.name
            for node in tree.body if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name.lower().endswith("tool")
        ]
        tool_class = class_names[0] if class_names else ""
        replacements: list[tuple[str, str]] = []
        for class_node in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            for method in [
                node for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                name_lower = method.name.lower()
                if expanduser_match and "dynamic" in name_lower and "path" in name_lower and tool_class:
                    replacement = (
                        f"def {method.name}(self):\n"
                        f"    tool = {tool_class}()\n"
                        f"    expected_path = os.path.expanduser({expanduser_match.group('path')!r})\n"
                        "    self.assertEqual(tool.path, expected_path)\n"
                    )
                    replacements.append((f"{class_node.name}.{method.name}", replacement))
                elif wants_invalid_json and "invalid" in name_lower and "json" in name_lower:
                    imported_loaders = [
                        (node.module or "", alias.name, alias.asname or alias.name)
                        for node in ast.walk(method) if isinstance(node, ast.ImportFrom)
                        for alias in node.names
                        if "load" in alias.name.lower()
                    ]
                    loader_module, loader_name, loader = (
                        imported_loaders[0]
                        if imported_loaders
                        else ("", "load_tasks", "load_tasks")
                    )
                    loader_import = (
                        f"    from {loader_module} import {loader_name}\n"
                        if loader_module
                        else ""
                    )
                    replacement = (
                        f"def {method.name}(self):\n"
                        f"{loader_import}"
                        "    with open(self.tool.path, 'w', encoding='utf-8') as handle:\n"
                        "        handle.write('invalid json')\n"
                        f"    self.assertEqual({loader}(self.tool.path), [])\n"
                    )
                    replacements.append((f"{class_node.name}.{method.name}", replacement))
        corrected = source
        for symbol, replacement in replacements:
            matched, corrected, _error = _edit_python_symbol_source(
                corrected,
                target_symbol=symbol,
                replacement=replacement,
                filename=path_text,
                operation="replace_symbol",
            )
            if matched:
                fixes.append(f"{Path(path_text).name}: materialized {symbol} test contract")
        updated[index] = (path_text, original, corrected)
    return updated, fixes


def format_project_edit_generated_python(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Normalize complete generated Python files before final validation."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path_text)
            formatted = ast.unparse(tree).rstrip() + "\n"
            formatted_tree = ast.parse(formatted, filename=path_text)
            lines = formatted.splitlines()
            top_imports = [
                node for node in formatted_tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))
            ]
            if top_imports:
                import_lines = [ast.unparse(node) for node in top_imports]
                import_lines.sort(
                    key=lambda line: (
                        0 if line.startswith("from __future__") else
                        1 if (
                            line.split()[1].split(".", 1)[0]
                            if line.startswith(("import ", "from "))
                            else ""
                        ) in sys.stdlib_module_names else 2,
                        line,
                    )
                )
                start = top_imports[0].lineno - 1
                end = int(top_imports[-1].end_lineno or top_imports[-1].lineno)
                lines[start:end] = import_lines
                formatted_tree = ast.parse("\n".join(lines) + "\n", filename=path_text)
            for node in sorted(
                (
                    node for node in formatted_tree.body
                    if not isinstance(node, (ast.Import, ast.ImportFrom))
                ),
                key=lambda item: item.lineno,
                reverse=True,
            ):
                insertion = node.lineno - 1
                while insertion > 0 and not lines[insertion - 1].strip():
                    del lines[insertion - 1]
                    insertion -= 1
                lines[insertion:insertion] = ["", ""]
            formatted = "\n".join(lines).rstrip() + "\n"
            if re.match(r"^#.*coding[:=]", source):
                formatted = "# coding=utf-8\n" + formatted
            else:
                formatted = formatted.lstrip("\n")
            compile(ast.parse(formatted, filename=path_text), path_text, "exec")
        except (SyntaxError, ValueError):
            continue
        if formatted != source:
            updated[index] = (path_text, original, formatted)
            fixes.append(f"{Path(path_text).name}: normalized generated Python formatting")
    return updated, fixes


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
    generated_artifact = discovery.get("evidence_mode") == "generated_artifact_scope"
    planned_files = [] if generated_artifact else [target_path] if target_path else []
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
        (
            f"Generated-artifact project scope: {target_path}."
            if generated_artifact
            else f"Best evidence-backed target: {target_path or '(no target established)' }."
        ),
        f"Target confidence: {confidence}.",
        "Existing symbols and behavior to reuse or inspect:",
        _compact_discovery_evidence(plan),
        "Proposed changes:",
        f"- {'Generate the smallest focused implementation and matching tests for the stated objective.' if requires_patch else 'Return the evidence-backed analysis without producing a patch.'}",
        "Planned files: " + (
            "selected after approval by a validated dependency-ordered artifact manifest"
            if generated_artifact
            else ", ".join(planned_files) if planned_files else "not established"
        ),
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
    prompt = f"""Exact existing source boundary:
```python
{exact_source}
```

User objective:
{objective}

Approved implementation plan:
{_trim_text(approved_plan, 3500)}

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
                "requirement_coverage": [],
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
    if selected_model:
        selected = str(selected_model)
        try:
            from tech_connector.services.ollama_service import (
                resolve_ollama_model_name,
            )

            return resolve_ollama_model_name(selected)
        except Exception:
            return selected.removeprefix("ollama:").strip()
    tier = (stage.model_tier or "").strip()
    if tier == "local_plan":
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
    elif tier == "local_semantic":
        model = settings.get("semantic_intent_model") or "qwen3:4b-instruct"
    elif tier == "local_semantic_verify":
        model = settings.get("semantic_verifier_model") or "qwen3:4b-instruct"
    elif tier == "local_deep":
        model = settings.get("router_local_deep") or settings.get("model") or selected_model
    elif tier == "local_fast":
        model = settings.get("router_fast_llm_model") or settings.get("router_local_plan") or settings.get("general_model")
    elif tier == "local_code":
        from tech_connector.services.ollama_service import code_model_for_profile
        import re

        profile = str(stage.coder_preference or "small").strip().lower()
        base_code_model = settings.get("router_local_code") or settings.get("code_model")
        
        model = (
            settings.get(f"router_local_code_{profile}")
            or settings.get(f"code_model_{profile}")
        )
        if not model:
            default_profile_model = code_model_for_profile(profile)
            if base_code_model:
                def model_size(name: str) -> float:
                    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", str(name or "").lower())
                    return float(match.group(1)) if match else 0.0
                
                if model_size(default_profile_model) > model_size(base_code_model):
                    model = base_code_model
                else:
                    model = default_profile_model
            else:
                model = default_profile_model
    else:
        model = None
    selected = str(model or selected_model or settings.get("model") or "qwen2.5-coder:7b")
    try:
        from tech_connector.services.ollama_service import resolve_ollama_model_name

        return resolve_ollama_model_name(selected)
    except Exception:
        return selected.removeprefix("ollama:").strip()


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
    for item in discovery.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        candidate_path = Path(str(item.get("path") or ""))
        if candidate_path.suffix.lower() == ".py" and candidate_path not in paths:
            paths.append(candidate_path)
    for root in roots:
        test_path = root / "tests" / f"test_{target_path.stem}.py"
        if test_path not in paths:
            paths.append(test_path)
        break
    paths = paths[:8]

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
    included_symbol_blocks = 0
    included_by_path: dict[str, int] = {}
    for _score, path, line, segment in sorted(ranked, key=lambda item: (-item[0], item[1], item[2])):
        is_test_excerpt = _is_test_path(Path(path))
        if is_test_excerpt and included_test_excerpts >= 1:
            continue
        if included_by_path.get(path, 0) >= 2:
            continue
        excerpt = segment if len(segment) <= 1800 else _trim_text(segment, 1800)
        block = f"File: {path}:{line}\n```python\n{excerpt}\n```"
        if lines and len("\n\n".join(lines + [block])) > max_chars:
            continue
        lines.append(block)
        included_symbol_blocks += 1
        included_by_path[path] = included_by_path.get(path, 0) + 1
        if is_test_excerpt:
            included_test_excerpts += 1
        if included_symbol_blocks >= 10:
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


def _project_edit_requests_new_artifact_plan(prompt: str) -> bool:
    """Preserve a new generated deliverable even when live mutation is forbidden."""
    lower = " ".join(str(prompt or "").lower().split())
    implementation_verb = bool(
        re.search(
            r"\b(create|write|generate|implement|make|build|design)\b",
            lower,
        )
    )
    new_artifact_scope = bool(
        re.search(
            r"\b(multi[- ]file|new (?:tool|app|application|service|package|module|"
            r"library|system|artifact)|from scratch|complete (?:python |code |"
            r"software )?(?:artifact|implementation|package|tool|application|system)|"
            r"generated (?:code|artifact|implementation))\b",
            lower,
        )
    )
    return implementation_verb and new_artifact_scope


def preview_project_edit_agent_response(
    model_response: str,
    *,
    project_root: str | None = None,
    request_prompt: str = "",
    allowed_external_paths: set[str] | None = None,
    behavioral_proof_deferred: bool = False,
) -> ProjectEditApplyResult:
    """Parse and resolve model-produced file changes without writing them."""

    changes, errors = _resolve_model_changes(
        model_response,
        project_root=project_root,
        allowed_external_paths=allowed_external_paths,
    )
    if changes and not errors:
        generated_records = [
            (
                str(item.get("path") or ""),
                str(item.get("before") or ""),
                str(item.get("after") or ""),
            )
            for item in changes
            if str(item.get("path") or "").lower().endswith(".py")
        ]
        normalized_records, _docstring_fixes = ensure_project_edit_requested_docstrings(
            generated_records,
            request_prompt=request_prompt,
            force=True,
        )
        normalized_by_path = {
            path: source for path, _original, source in normalized_records
        }
        for item in changes:
            path = str(item.get("path") or "")
            if path in normalized_by_path:
                item["after"] = normalized_by_path[path]
                item["new_content"] = normalized_by_path[path]
    validation = _validate_candidate_changes(
        changes,
        project_root=project_root,
        request_prompt=request_prompt,
        allowed_external_paths=allowed_external_paths,
        behavioral_proof_deferred=behavioral_proof_deferred,
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
    behavioral_proof_satisfied: bool = False,
) -> ProjectEditApplyResult:
    """Apply model-produced XML file changes, save undo, and run validation."""

    preview = preview_project_edit_agent_response(
        model_response,
        project_root=project_root,
        request_prompt=request_prompt,
        behavioral_proof_deferred=behavioral_proof_satisfied,
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
    allowed_external_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    from tech_connector.knowledge.search import parse_multi_file_changes, replace_content_resilient

    root = Path(project_root).resolve() if project_root else None

    def _normalize_candidate_path(raw_path: str) -> str:
        path_text = str(raw_path or "").strip().replace("\\", "/")
        if not path_text:
            return ""
        if root is None or not _is_forbidden_edit_path(path_text):
            return path_text
        path_obj = Path(path_text)
        if path_obj.is_absolute():
            parts = path_obj.parts
            for idx, part in enumerate(parts):
                if part.lower() == "unreal_tools":
                    return str(root.joinpath(*parts[idx:]))
            return str(root / path_obj.name)
        return path_text

    changes, errors, structured = _parse_structured_project_changes(
        model_response,
        project_root=project_root,
        allowed_external_paths=allowed_external_paths,
    )
    if not structured:
        changes = parse_multi_file_changes(model_response or "", project_root or "")
    states: dict[str, dict[str, Any]] = {}
    for change in changes:
        action = str(change.get("action") or "")
        path = _normalize_candidate_path(str(change.get("path") or ""))
        if not path:
            errors.append("Change is missing a path.")
            continue
        if _is_forbidden_edit_path(path):
            errors.append(_edit_error_for_forbidden_path(path))
            continue
        if not action:
            action = "modify"
        if action == "create":
            states[path] = {
                "action": "create",
                "path": path,
                "before": "",
                "after": _sanitize_python_candidate_text(change.get("new_content")),
            }
            continue
        p = Path(path)
        if not p.exists():
            if p.suffix.lower() == ".py":
                states[path] = {
                    "action": "create",
                    "path": path,
                    "before": "",
                    "after": _sanitize_python_candidate_text(change.get("new_content")),
                }
            else:
                errors.append(f"Cannot modify missing file: {path}; switch to create or provide existing target.")
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
        if action in {"replace_text", "insert_before_text", "insert_after_text"}:
            anchor = str(change.get("target_symbol") or "")
            if not anchor:
                errors.append(f"{action} change is missing exact text anchor: {path}")
                continue
            occurrences = current.count(anchor)
            if occurrences != 1:
                errors.append(
                    f"{action} requires one exact anchor occurrence, found {occurrences}: {path}"
                )
                continue
            replacement = _sanitize_python_candidate_text(change.get("new_content"))
            if action == "insert_before_text":
                replacement = replacement + anchor
            elif action == "insert_after_text":
                replacement = anchor + replacement
            state["after"] = current.replace(anchor, replacement, 1)
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
                replacement=_sanitize_python_candidate_text(change.get("new_content")),
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
            _sanitize_python_candidate_text(change.get("new_content")),
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
        class_node = node
        node = next(
            (item for item in class_node.body if getattr(item, "name", None) == parts[1]),
            None,
        )
        if node is None and operation in {"insert_before_symbol", "insert_after_symbol"}:
            if class_node.body:
                node = class_node.body[-1]
                operation = "insert_after_symbol"
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        lines = source.splitlines(keepends=True)
        matching_line_idx = -1
        target_clean = target_symbol.strip()
        for idx, line in enumerate(lines):
            if target_clean in line:
                matching_line_idx = idx
                break
        if matching_line_idx != -1 and operation in {"insert_before_symbol", "insert_after_symbol"}:
            start_offset = sum(len(line) for line in lines[:matching_line_idx])
            end_offset = sum(len(line) for line in lines[:matching_line_idx + 1])
            replacement_text = textwrap.dedent(replacement).strip("\r\n") + "\n"
            if operation == "insert_before_symbol":
                return True, source[:start_offset] + replacement_text + source[start_offset:], ""
            if operation == "insert_after_symbol":
                return True, source[:end_offset] + replacement_text + source[end_offset:], ""
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
    if _is_self_import(Path(filename), module, 0, project_root=None):
        return True, source, ""
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
    allowed_external_paths: set[str] | None = None,
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
    allowed_external = {
        str(Path(path).resolve()).casefold()
        for path in (allowed_external_paths or set())
    }
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
            "replace_text",
            "insert_before_text",
            "insert_after_text",
            "ensure_import",
        }:
            errors.append(f"Structured change {index} has unsupported action: {action or '(missing)' }.")
            continue
        if not raw_path:
            errors.append(f"Structured change {index} is missing a path.")
            continue
        normalized_path = raw_path
        if root is not None and _is_forbidden_edit_path(raw_path):
            candidate_path = Path(raw_path)
            if candidate_path.is_absolute():
                parts = candidate_path.parts
                for idx, part in enumerate(parts):
                    if part.lower() == "unreal_tools":
                        normalized_path = str(root.joinpath(*parts[idx:]))
                        break
                else:
                    normalized_path = str(root / candidate_path.name)
            elif root:
                normalized_path = raw_path
        raw_path = normalized_path
        if _is_forbidden_edit_path(raw_path):
            errors.append(_edit_error_for_forbidden_path(raw_path))
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
                if str(resolved_path).casefold() not in allowed_external:
                    errors.append(
                        "Structured change path is outside the project root: "
                        f"{resolved_path}"
                    )
                    continue
        new_content = item.get("new_content")
        if not isinstance(new_content, str):
            errors.append(f"Structured change {index} is missing string new_content.")
            continue
        raw_target = str(item.get("target_symbol") or "")
        change = {
            "action": action,
            "path": str(resolved_path),
            "target_symbol": raw_target if action in {"replace_text", "insert_before_text", "insert_after_text"} else raw_target.strip(),
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

_FORBIDDEN_EDIT_ROOT_MARKERS = tuple(
    marker.strip().lower()
    for marker in re.split(r"[;,]", os.getenv("TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS", "time_fighters 5.8"))
    if marker.strip()
)


def _is_forbidden_edit_path(path_text: str) -> bool:
    """Return true when a candidate edit path should never be written by design."""
    normalized = str(path_text or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _FORBIDDEN_EDIT_ROOT_MARKERS)


def _edit_error_for_forbidden_path(path_text: str) -> str:
    return (
        "Attempted edit target is inside a forbidden project root: "
        f"{path_text}. Set TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS to include/remove scope."
    )
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
_UI_WIDGET_IDENTIFIER_STOPWORDS = {
    "a",
    "an",
    "and",
    "button",
    "combo",
    "in",
    "bound",
    "on",
    "the",
    "connect",
    "every",
    "value",
    "widget",
    "widgets",
}


def _infer_prompt_requirements(question: str) -> dict[str, bool]:
    """Infer generic runtime, UI, and API intent from a natural-language request."""

    lowered = (question or "").lower()
    signal_intent = bool(re.search(
        r"\b(clicked|signal|on\s+click|bind|value\s*changed|text\s*changed)\b"
        r"|\.connect\s*\(",
        lowered,
    ))
    explicit_qt_intent = bool(
        re.search(r"\b(?:qt|pyside6?|pyqt[56]?)\b", lowered)
    )
    explicit_control_intent = bool(re.search(
        r"\b(button|combo(?:\s*box)?|dropdown|spin(?:ner|\s*box)?|"
        r"text\s*(?:box|field)|line\s*edit|progress\s*bar)\b",
        lowered,
    ))
    explicit_ui_surface_intent = bool(
        re.search(r"\b(?:ui|dialog|widget|panel)\b", lowered)
        or re.search(
            r"\b(?:add|build|create|implement|launch|open|show)\b"
            r"[^\n.;]{0,60}\bwindow\b",
            lowered,
        )
    )
    ui_intent = bool(
        explicit_qt_intent
        or explicit_control_intent
        or explicit_ui_surface_intent
        or signal_intent
    )
    requirements: dict[str, bool] = {
        "needs_unreal_import": "unreal" in lowered,
        "needs_maya_import": any(
            token in lowered
            for token in ("maya", "blender", "motionbuilder", "pyfbsdk", "bpy")
        ),
        "needs_qt_import": ui_intent,
        "needs_signal_connect": ui_intent and signal_intent,
        "needs_factory_create_asset": "create_asset" in lowered and "unreal" in lowered,
        "needs_widget_entrypoint": bool(
            ui_intent
            and re.search(r"\b(dialog|window|widget)\b", lowered)
        )
        and any(
            token in lowered
            for token in (
                "add",
                "create",
                "implement",
                "build",
                "new",
                "launch",
                "show",
            )
        ),
    }
    return requirements


def _infer_ui_widget_requirements(question: str) -> list[tuple[str, str]]:
    """Infer explicit widget names and rough control kinds from prompt phrasing."""

    lowered = str(question or "").lower()
    qt_type_names = {
        name.casefold()
        for name in re.findall(r"\bQ[A-Z][A-Za-z0-9_]*\b", str(question or ""))
    }
    widget_requirements: dict[str, str] = {}

    noun_to_kind = (
        ("text box", "text"),
        ("text field", "text"),
        ("textbox", "text"),
        ("input box", "text"),
        ("input", "text"),
        ("line edit", "text"),
        ("dropdown", "combo"),
        ("combo box", "combo"),
        ("combobox", "combo"),
        ("spinner", "spin"),
        ("spin box", "spin"),
        ("spinbox", "spin"),
        ("button", "button"),
        ("progress bar", "progress"),
        ("progress", "progress"),
    )

    for noun, kind in noun_to_kind:
        noun_pattern = re.escape(noun)
        for expr in (
            rf"\b{noun_pattern}\b[^\\n]*?\b(?:for|named|called)\b[^\\n]*?`?([a-z_][a-z0-9_]*)`?",
            rf"`?([a-z_][a-z0-9_]*)`?[^\\n]*?\b(?:for|named|called)\b[^\\n]*?\b{noun_pattern}\b",
        ):
            for match in re.finditer(expr, lowered, flags=re.IGNORECASE):
                name = match.group(1).strip("`_") if match.groups() else ""
                if not name:
                    continue
                normalized_name = name.strip("`").strip("'\"")
                if (
                    re.fullmatch(r"[a-z_][a-z0-9_]*", normalized_name)
                    and normalized_name.lower() not in _UI_WIDGET_IDENTIFIER_STOPWORDS
                ):
                    widget_requirements.setdefault(normalized_name, kind)

    # Heuristic fallbacks from explicit widget-like identifiers.
    for name in re.findall(r"\b[a-z_][a-z0-9_]*\b", lowered):
        if re.search(
            r"(?:_btn$|button$|_combo$|_spin(?:ner|box)$|_input$|_label$|"
            r"_text(?:_input|_box)?$|_progress(?:_?bar)?$|_bar$)",
            name,
        ):
            kind = "button" if "_btn" in name or "button" in name else (
                "combo" if "_combo" in name else (
                    "spin" if "_spin" in name else (
                        "text" if "_text" in name or "_input" in name else (
                            "label" if "_label" in name else "progress"
                        )
                    )
                )
            )
            if (
                name not in _UI_WIDGET_IDENTIFIER_STOPWORDS
                and name not in qt_type_names
            ):
                widget_requirements.setdefault(name, kind)

    ordered = sorted(widget_requirements.items(), key=lambda item: (item[0], item[1]))
    return ordered


def _qt_widget_import_coverage(imported_modules: set[str], imported_names: set[str]) -> bool:
    """
    Determine whether generated imports provide a plausible Qt/PySide/PyQt surface.

    This intentionally checks for:
    - Known Qt/PySide/PyQt-style module names.
    - Uppercase QWidget-style constructor symbols (QLineEdit, QDialog, etc.).
    """

    qt_module_markers = (
        "qt",
        "pyside",
        "pyqt",
        "qtpy",
        "shiboken",
    )
    if any(
        any(marker in module for marker in qt_module_markers)
        for module in imported_modules
    ):
        return True
    return any(
        bool(re.match(r"^Q[A-Z][A-Za-z0-9_]*$", name))
        for name in imported_names
    )


def _expected_widget_accessor(widget_name: str, kind_hint: str | None = None) -> str | None:
    """Return the most likely value accessor for a widget kind/name."""

    lowered = widget_name.lower()
    if kind_hint == "spin" or "_spin" in lowered:
        return "value"
    if kind_hint == "combo":
        return "currentText"
    if kind_hint == "text":
        return "text"
    return None


def _widget_expected_constructors(kind_hint: str) -> set[str]:
    """Return likely Qt constructor classes for a widget-kind hint."""

    if kind_hint == "button":
        return {"QPushButton"}
    if kind_hint == "combo":
        return {"QComboBox"}
    if kind_hint == "spin":
        return {"QSpinBox", "QDoubleSpinBox"}
    if kind_hint == "text":
        return {"QLineEdit", "QTextEdit", "QPlainTextEdit"}
    if kind_hint == "progress":
        return {"QProgressBar", "ListProgressBar"}
    return set()


def _widget_ctor_base_name(ctor_name: str | None) -> str:
    if not ctor_name:
        return ""
    return str(ctor_name).rsplit(".", 1)[-1]


def _widget_ctor_is_imported(ctor_name: str, imported_names: set[str], top_level_names: set[str]) -> bool:
    base = _widget_ctor_base_name(ctor_name)
    return (
        ctor_name in imported_names
        or base in imported_names
        or ctor_name in top_level_names
        or base in top_level_names
        or (("." in ctor_name) and ctor_name.split(".", 1)[0] in imported_names)
    )


def _callable_signature_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return ast.unparse(func)
    return None


def _extract_self_chain_attr(expr: ast.AST) -> str | None:
    """Extract the attribute name immediately following ``self`` in an attribute chain."""

    attrs: list[str] = []
    current = expr
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name) and current.id == "self" and attrs:
        return attrs[-1]
    return None


def _is_placeholder_callable(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue
        if isinstance(child, ast.Pass):
            continue
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and child.value.value is Ellipsis
        ):
            continue
        if isinstance(child, ast.Return) and child.value is None:
            continue
        return False
    return True


def _infer_signal_handler_requirements(question: str) -> set[str]:
    lowered = str(question or "").lower()
    if not lowered:
        return set()
    required: set[str] = set()
    patterns = (
        r"\b(?:connect|bind|wire)\b[^\n]{0,200}?\b(?:to|with)\b[^\n]{0,120}?`?(?:self\.)?([a-z_][a-z0-9_]*)`?(?:\(\))?(?:\b|$)",
        r"\b([a-z_][a-z0-9_]*)`?\s*\.\s*connect\(\s*self\.([a-z_][a-z0-9_]*)`?(?:\(\))?\s*\)",
        r"\bconnect\(\s*self\.([a-z_][a-z0-9_]*)`?(?:\(\))?\s*\)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            for group in match.groups():
                if not group:
                    continue
                name = group.strip("`'\" ")
                if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                    required.add(name)
    return required


def _is_placeholder_class(node: ast.ClassDef) -> bool:
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue
        if isinstance(child, ast.Pass):
            continue
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and child.value.value is Ellipsis
        ):
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_placeholder_callable(child):
                continue
        else:
            return False
    return True

def _imported_name_bindings(tree: ast.AST) -> set[str]:
    """Collect all symbols imported into module namespace."""

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                names.add("*")
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _has_top_level_import_for_module(tree: ast.AST, module: str) -> bool:
    """Detect module-level import statements for a given module."""

    normalized = module.lower()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if _import_targets_module(node, normalized):
                return True
    return False


def _method_uses_widget_access(node: ast.AST, widget_name: str, accessor: str | None = None) -> bool:
    """Check whether a method accesses a widget (optionally through a specific accessor)."""

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute):
            continue
        if (
            isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == widget_name
        ):
            if accessor is None:
                return True
            if func.attr == accessor:
                return True
    return False


def _method_updates_widget(node: ast.AST, widget_name: str) -> bool:
    """Return whether a handler writes observable state to a widget."""

    update_methods = {
        "addItem",
        "addItems",
        "clear",
        "display",
        "insertItem",
        "setChecked",
        "setCurrentIndex",
        "setCurrentText",
        "setEnabled",
        "setIcon",
        "setPalette",
        "setPixmap",
        "setPlainText",
        "setProperty",
        "setStyleSheet",
        "setText",
        "setValue",
        "setVisible",
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in update_methods
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == widget_name
        ):
            return True
    return False


def _unresolved_module_scope_names(tree: ast.Module) -> list[str]:
    """Return undefined names evaluated at module or class construction time."""

    available = set(dir(builtins))
    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def inside_callable(node: ast.AST) -> bool:
        current = parent_by_node.get(id(node))
        while current is not None and not isinstance(current, ast.Module):
            if isinstance(
                current,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
            ):
                return True
            current = parent_by_node.get(id(current))
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            available.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            available.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            available.update(
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            )
    available.update(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and not inside_callable(node)
    )
    available.update(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.name
        and not inside_callable(node)
    )
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if not inside_callable(node) and node.id not in available:
            unresolved.add(node.id)
    return sorted(unresolved)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                modules.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                modules.add(module)
                modules.add(module.split(".", 1)[0])
    return modules


def _node_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for parent_node in ast.walk(tree):
        for child in ast.iter_child_nodes(parent_node):
            parent[child] = parent_node
    return parent


def _import_targets_module(node: ast.AST, module: str) -> bool:
    normalized = module.lower()
    if isinstance(node, ast.Import):
        return any(
            alias.name.lower() == normalized or alias.name.lower().startswith(f"{normalized}.")
            or alias.name.split(".", 1)[0].lower() == normalized
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        if not node.module:
            return False
        candidate = node.module.lower()
        return candidate == normalized or candidate.startswith(f"{normalized}.") or candidate.split(".", 1)[0] == normalized
    return False


def _is_importerror_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id == "ImportError"
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(item, ast.Name) and item.id == "ImportError"
            for item in handler.type.elts
        )
    return False


def _is_sys_modules(expr: ast.AST) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "sys"
        and expr.attr == "modules"
    )


def _is_module_module_guard(test: ast.AST, module: str) -> bool:
    for node in ast.walk(test):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        left = node.left
        comparators = node.comparators or ()
        for comparator in comparators:
            if isinstance(left, ast.Constant) and isinstance(left.value, str) and left.value == module and _is_sys_modules(comparator):
                return True
            if _is_sys_modules(left) and isinstance(comparator, ast.Constant) and isinstance(comparator.value, str) and comparator.value == module:
                return True
    return False


def _has_optional_import_guard(tree: ast.AST, module: str) -> bool:
    """Accept try/except ImportError imports and sys.modules gating patterns."""

    parent = _node_parent_map(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not _import_targets_module(node, module):
            continue
        parent_node = parent.get(node)
        if isinstance(parent_node, ast.Try):
            if any(_is_importerror_handler(handler) for handler in parent_node.handlers):
                return True
        if isinstance(parent_node, ast.If):
            if _is_module_module_guard(parent_node.test, module):
                return True
    return False


def _has_launch_show_call(node: ast.stmt) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "show"
            and isinstance(func.value, (ast.Name, ast.Attribute))
        ):
            return True
    return False


def _is_dunder_main_guard(test: ast.AST) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    return (
        (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and isinstance(right, ast.Constant)
            and right.value == "__main__"
        )
        or (
            isinstance(right, ast.Name)
            and right.id == "__name__"
            and isinstance(left, ast.Constant)
            and left.value == "__main__"
        )
    )


def _has_main_window_entrypoint(tree: ast.AST) -> bool:
    local_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if not _is_dunder_main_guard(node.test):
            continue
        for child in node.body:
            if _has_launch_show_call(child):
                return True
            for call in ast.walk(child):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id in local_functions
                    and _has_launch_show_call(local_functions[call.func.id])
                ):
                    return True
    return False


def _has_widget_class_surface(tree: ast.AST, inferred_widget_requirements: list[tuple[str, str]]) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        class_name = node.name.lower()
        if any(token in class_name for token in ("dialog", "widget", "window")):
            return True
        for base in node.bases:
            base_name: str | None = None
            if isinstance(base, ast.Name):
                base_name = base.id.lower()
            elif isinstance(base, ast.Attribute):
                base_name = base.attr.lower()
            if base_name is not None and any(
                token in base_name for token in (
                    "dialog",
                    "widget",
                    "window",
                    "qdialog",
                    "qwidget",
                    "qmainwindow",
                )
            ):
                return True
    return bool(inferred_widget_requirements)


def _iter_signal_connects(tree: ast.AST) -> tuple[
    dict[str, list[str]],
    list[str],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, dict[str, ast.FunctionDef]],
    dict[str, list[tuple[str, str | None]]],
    dict[str, dict[str, str]],
]:
    """Collect signal wiring locations and method/call details per class."""

    parent = _node_parent_map(tree)

    module_level: list[str] = []
    class_connects: dict[str, list[str]] = {}
    class_connected_self_handlers: dict[str, set[str]] = {}
    class_connecting_methods: dict[str, set[str]] = {}
    class_widget_defs: dict[str, set[str]] = {}
    class_method_nodes: dict[str, dict[str, ast.FunctionDef]] = {}
    class_signal_targets: dict[str, list[tuple[str, str | None]]] = {}
    class_widget_ctors: dict[str, dict[str, str]] = {}
    init_calls: dict[str, set[str]] = {}
    class_methods_by_class: dict[str, set[str]] = {}
    class_method_calls: dict[str, dict[str, set[str]]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            class_methods_by_class[class_name] = {
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef)
            }
            class_method_nodes[class_name] = {}
            class_method_calls[class_name] = {}
            class_widget_defs.setdefault(class_name, set())
            class_signal_targets.setdefault(class_name, [])
            class_widget_ctors.setdefault(class_name, {})
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    self_calls = {
                        call.func.attr
                        for call in ast.walk(child)
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                            and isinstance(call.func.attr, str)
                        )
                    }
                    class_method_calls[class_name][child.name] = self_calls
                    class_method_nodes[class_name][child.name] = child
                    if child.name == "__init__":
                        init_calls[class_name] = self_calls
                    for stmt in ast.walk(child):
                        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                            continue
                        if isinstance(stmt, ast.Assign):
                            targets = list(stmt.targets)
                        else:
                            targets = [stmt.target]
                        value = stmt.value
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and isinstance(target.attr, str)
                            ):
                                class_widget_defs[class_name].add(target.attr)
                                if isinstance(value, ast.Call):
                                    call_func = _callable_signature_name(value)
                                    if call_func is not None:
                                        class_widget_ctors[class_name][target.attr] = call_func

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
        ):
            continue

        containing_function: ast.AST | None = None
        containing_class: ast.AST | None = None
        cursor = node
        while cursor in parent:
            cursor = parent[cursor]
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)) and containing_function is None:
                containing_function = cursor
            if isinstance(cursor, ast.ClassDef):
                containing_class = cursor
                break

        if containing_class is None:
            module_level.append(ast.unparse(node).strip())
            continue
        if not isinstance(containing_function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        class_name = getattr(containing_class, "name", "")
        function_name = getattr(containing_function, "name", "")
        class_connects.setdefault(class_name, [])
        class_connected_self_handlers.setdefault(class_name, set())
        class_connecting_methods.setdefault(class_name, set())
        class_signal_targets.setdefault(class_name, [])
        class_connects[class_name].append(function_name or "<unknown>")

        if node.args:
            arg0 = node.args[0]
            if (
                isinstance(arg0, ast.Attribute)
                and isinstance(arg0.value, ast.Name)
                and arg0.value.id == "self"
            ):
                class_connected_self_handlers[class_name].add(arg0.attr)
                handler_name = arg0.attr
                if function_name and node.func:
                    target_widget = _extract_self_chain_attr(node.func.value)
                    class_signal_targets[class_name].append((target_widget or "", handler_name))
            elif function_name and node.func:
                target_widget = _extract_self_chain_attr(node.func.value)
                if target_widget:
                    class_signal_targets[class_name].append((target_widget, None))
        if function_name and function_name != "__init__":
            class_connecting_methods[class_name].add(function_name)

    return (
        class_connects,
        module_level,
        class_connected_self_handlers,
        class_connecting_methods,
        init_calls,
        class_methods_by_class,
        class_method_calls,
        class_widget_defs,
        class_method_nodes,
        class_signal_targets,
        class_widget_ctors,
    )


def _has_factory_argument_call(tree: ast.AST) -> bool:
    verified_factory_names = {
        target.id
        for assignment in ast.walk(tree)
        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
        for target in (
            assignment.targets
            if isinstance(assignment, ast.Assign)
            else [assignment.target]
        )
        if isinstance(target, ast.Name)
        and isinstance(assignment.value, ast.Call)
        and "factory" in ast.unparse(assignment.value.func).lower()
    }

    def is_factory_expression(expression: ast.AST) -> bool:
        if isinstance(expression, ast.Constant) and expression.value is None:
            return False
        if isinstance(expression, ast.Call):
            return "factory" in ast.unparse(expression.func).lower()
        if isinstance(expression, ast.Name):
            return expression.id in verified_factory_names
        return False

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_asset"
        ):
            if any(
                isinstance(keyword, ast.keyword)
                and keyword.arg == "factory"
                and is_factory_expression(keyword.value)
                for keyword in node.keywords
            ):
                return True
            if len(node.args) < 4:
                continue
            factory_arg = node.args[3]
            if is_factory_expression(factory_arg):
                return True
    return False


def _real_unreal_get_asset_tools_targets(tree: ast.AST) -> set[str]:
    """Collect `get_asset_tools` call sites that need API-ownership validation."""

    candidates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "get_asset_tools":
            candidates.add("get_asset_tools")
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_asset_tools"
        ):
            candidates.add(ast.unparse(node.func.value))
    return candidates


def _validated_api_membership_call_chain(call_base: str, module_name: str = "unreal") -> bool:
    """Resolve `unreal.<owner>.get_asset_tools` against a real Unreal module, if available."""

    try:
        unreal_module = __import__(module_name)
    except Exception:
        return False

    segments = [segment.strip() for segment in call_base.split(".") if segment.strip()]
    if len(segments) < 2 or segments[0] != module_name:
        return False

    owner = unreal_module
    for segment in segments[1:]:
        if not hasattr(owner, segment):
            return False
        try:
            owner = getattr(owner, segment)
        except Exception:
            return False
    return hasattr(owner, "get_asset_tools")


def _invalid_unreal_get_asset_tools_calls(tree: ast.AST) -> tuple[list[str], list[str]]:
    """Find Unreal `get_asset_tools` calls that appear invalid or unverified."""

    candidates = _real_unreal_get_asset_tools_targets(tree)
    invalid: list[str] = []
    unverifiable: list[str] = []
    for call_expr in sorted(candidates):
        if call_expr == "get_asset_tools":
            invalid.append(call_expr)
            continue
        if not call_expr.startswith("unreal."):
            invalid.append(call_expr + ".get_asset_tools")
            continue
        if not _validated_api_membership_call_chain(call_expr):
            try:
                __import__("unreal")
            except Exception:
                unverifiable.append(f"{call_expr}.get_asset_tools")
            else:
                invalid.append(f"{call_expr}.get_asset_tools")
    return sorted(invalid), sorted(unverifiable)


def _infer_explicit_runtime_api_requests(request_prompt: str) -> set[str]:
    """Infer exact runtime API names requested in prompt text."""

    text = str(request_prompt or "")
    if not text:
        return set()

    request_paths: set[str] = set()
    for module in sorted(_HOST_RUNTIME_MODULES):
        pattern = rf"\b{re.escape(module)}\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){{1,4}}\b"
        request_paths.update(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return request_paths


def _runtime_api_calls_in_tree(tree: ast.AST) -> set[str]:
    """Collect explicitly written runtime dot-chains from call expressions."""

    call_paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        parts: list[str] = []
        cursor = func
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if not isinstance(cursor, ast.Name):
            continue
        if cursor.id not in _HOST_RUNTIME_MODULES:
            continue
        if not parts:
            continue
        call_paths.add(".".join([cursor.id] + list(reversed(parts))))
    return call_paths


def _runtime_api_paths_in_tree(tree: ast.AST) -> set[str]:
    """Collect every qualified host attribute chain used by generated code."""

    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts: list[str] = []
        cursor: ast.AST = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if (
            isinstance(cursor, ast.Name)
            and cursor.id in _HOST_RUNTIME_MODULES
            and parts
        ):
            paths.add(".".join([cursor.id, *reversed(parts)]))
    return paths


def _progress_callback_contract_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate the shared integer-step progress callback contract."""

    prompt_lower = str(request_prompt or "").lower()
    callback_requested = (
        "progress_callback" in prompt_lower
        or "progress callback" in prompt_lower
        or (
            "callback arguments" in prompt_lower
            and "integer" in prompt_lower
        )
    )
    issues: list[str] = []
    owned_functions: list[
        tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
    ] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owned_functions.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            owned_functions.extend(
                (f"{node.name}.{method.name}", method)
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    for owner, function in owned_functions:
        owner_prefix = f"[scope:callable][owner:{owner}] "
        parameter_names = {
            argument.arg
            for argument in (
                list(function.args.posonlyargs)
                + list(function.args.args)
                + list(function.args.kwonlyargs)
            )
        }
        callback_names = {
            name for name in parameter_names
            if name == "progress_callback" or name.endswith("_progress_callback")
        }
        progress_bar_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"setValue", "set_value"}
            and len(call.args) == 1
            and "progress" in ast.unparse(call.func.value).casefold()
        ]
        for call in progress_bar_calls:
            argument = call.args[0]
            safely_coerced = (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id in {"int", "round"}
            )
            contains_true_division = any(
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                for node in ast.walk(argument)
            )
            if contains_true_division and not safely_coerced:
                issues.append(
                    f"{owner_prefix}progress widgets must receive an integer "
                    "value; wrap division-based progress math in int() or round()"
                )
        if not callback_names:
            continue
        direct_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in callback_names
        ]
        assertion_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in callback_names
            and call.func.attr.startswith("assert")
        ]
        for call in direct_calls:
            first_two_are_not_float_math = all(
                not any(
                    (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, float)
                    )
                    or (
                        isinstance(node, ast.BinOp)
                        and isinstance(node.op, ast.Div)
                    )
                    for node in ast.walk(argument)
                )
                for argument in call.args[:2]
            )
            status_is_text = (
                len(call.args) >= 3
                and isinstance(call.args[2], (ast.Constant, ast.JoinedStr, ast.Name))
                and not (
                    isinstance(call.args[2], ast.Constant)
                    and not isinstance(call.args[2].value, str)
                )
            )
            if (
                len(call.args) != 3
                or call.keywords
                or not first_two_are_not_float_math
                or not status_is_text
            ):
                issues.append(
                    f"{owner_prefix}progress callbacks must use exactly "
                    "(current_int, total_int, status_str) without float math"
                )
        explicit_terminal_step_requested = bool(
            re.search(
                r"\b(?:explicit\s+)?(?:terminal|final)\s+"
                r"(?:progress\s+)?(?:callback|step|update)\b"
                r"|\bcurrent\s*==\s*total\b",
                request_prompt,
                flags=re.IGNORECASE,
            )
        )
        if explicit_terminal_step_requested and direct_calls and not any(
            len(call.args) == 3
            and ast.dump(call.args[0], include_attributes=False)
            == ast.dump(call.args[1], include_attributes=False)
            for call in direct_calls
        ):
            issues.append(
                f"{owner_prefix}progress callback sequence must emit an "
                "explicit terminal current == total step"
            )
        if callback_requested and function.name.startswith("test_"):
            if not assertion_calls or any(
                len(call.args) != 3 for call in assertion_calls
            ):
                issues.append(
                    f"{owner_prefix}requested callback proof must assert all "
                    "three callback arguments"
                )
    return sorted(set(issues))


def _requested_pre_side_effect_contract_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate request-driven input and result guards around host side effects."""

    prompt_lower = str(request_prompt or "").casefold()
    requires_existing_file = bool(
        re.search(r"\brequir\w*\b[^\n.;]{0,80}\bexisting\b[^\n.;]{0,40}\bfile\b", prompt_lower)
    )
    requires_prevalidation = bool(
        re.search(
            r"\bvalidat\w*\b[^\n.;]{0,120}\bbefore\b[^\n.;]{0,80}\bside effect",
            prompt_lower,
        )
    )
    requires_forward_slashes = bool(
        re.search(
            r"\bnormaliz\w*\b[^\n.;]{0,100}\bforward[- ]slash",
            prompt_lower,
        )
    )
    requires_exactly_one = bool(
        re.search(r"\brequir\w*\s+exactly\s+one\b", prompt_lower)
    )
    if not any((
        requires_existing_file,
        requires_prevalidation,
        requires_forward_slashes,
        requires_exactly_one,
    )):
        return []

    request_fields: dict[str, set[str]] = {}
    for class_node in (
        node for node in tree.body if isinstance(node, ast.ClassDef)
    ):
        fields = {
            statement.target.id
            for statement in class_node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
        if fields:
            request_fields[class_node.name] = fields

    def dotted_name(node: ast.AST) -> str:
        parts: list[str] = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
        return ".".join(reversed(parts))

    issues: list[str] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in functions:
        host_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and dotted_name(call.func).split(".", 1)[0]
            in _HOST_RUNTIME_MODULES
        ]
        if not host_calls:
            continue
        first_host_line = min(
            int(getattr(call, "lineno", 10**9)) for call in host_calls
        )
        owner_prefix = f"[scope:callable][owner:{function.name}] "
        preceding_nodes = [
            node
            for statement in function.body
            if int(getattr(statement, "lineno", 10**9)) < first_host_line
            for node in ast.walk(statement)
        ]
        if requires_existing_file:
            has_existing_file_guard = any(
                isinstance(node, ast.Call)
                and (
                    (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"exists", "is_file"}
                    )
                    or dotted_name(node.func).endswith(
                        ("os.path.exists", "os.path.isfile")
                    )
                )
                for node in preceding_nodes
            )
            if not has_existing_file_guard:
                issues.append(
                    owner_prefix
                    + "require the requested input file to exist before the "
                    "first host-runtime side effect"
                )
            if any(
                isinstance(node, ast.Call)
                and dotted_name(node.func).endswith(
                    "EditorAssetLibrary.does_asset_exist"
                )
                and node.args
                and "file" in ast.unparse(node.args[0]).casefold()
                for node in ast.walk(function)
            ):
                issues.append(
                    owner_prefix
                    + "do not validate a filesystem source with the host asset "
                    "registry; use only the disk file guard for that input"
                )
        if requires_prevalidation:
            parameter_to_fields: dict[str, set[str]] = {}
            for argument in (
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            ):
                if isinstance(argument.annotation, ast.Name):
                    fields = request_fields.get(argument.annotation.id)
                    if fields:
                        parameter_to_fields[argument.arg] = fields
            for parameter_name, fields in parameter_to_fields.items():
                referenced_before = {
                    node.attr
                    for node in preceding_nodes
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == parameter_name
                }
                missing_fields = sorted(fields - referenced_before)
                if missing_fields:
                    issues.append(
                        owner_prefix
                        + "validate or normalize every request field before the "
                        "first host-runtime side effect; missing: "
                        + ", ".join(missing_fields)
                    )
                boolean_fields = {
                    field
                    for field in fields
                    if field.casefold() in {"srgb", "enabled", "disabled", "checked"}
                    or field.casefold().endswith(("_flag", "_enabled"))
                }
                for field in sorted(boolean_fields):
                    field_expression = f"{parameter_name}.{field}"
                    has_boolean_validation = any(
                        isinstance(node, ast.Call)
                        and (
                            (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "isinstance"
                                and len(node.args) >= 2
                                and ast.unparse(node.args[0]) == field_expression
                                and isinstance(node.args[1], ast.Name)
                                and node.args[1].id == "bool"
                            )
                            or (
                                isinstance(node.func, ast.Name)
                                and node.func.id == "bool"
                                and node.args
                                and ast.unparse(node.args[0]) == field_expression
                            )
                        )
                        for node in preceding_nodes
                    )
                    if not has_boolean_validation:
                        issues.append(
                            owner_prefix
                            + f"validate or normalize boolean request field "
                            f"{field_expression} before the first host-runtime "
                            "side effect"
                        )
            callback_parameters = {
                argument.arg
                for argument in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
                if "callback" in argument.arg.casefold()
            }
            referenced_names = {
                node.id
                for node in preceding_nodes
                if isinstance(node, ast.Name)
            }
            missing_callbacks = sorted(
                callback_parameters - referenced_names
            )
            if missing_callbacks:
                issues.append(
                    owner_prefix
                    + "validate optional callback inputs before the first "
                    "host-runtime side effect; missing: "
                    + ", ".join(missing_callbacks)
                )
        if requires_forward_slashes:
            normalized_names: set[str] = set()
            for assignment in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                valid_replace = any(
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "replace"
                    and len(child.args) >= 2
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value == "\\"
                    and isinstance(child.args[1], ast.Constant)
                    and child.args[1].value == "/"
                    for child in ast.walk(assignment.value)
                )
                if valid_replace:
                    normalized_names.add(assignment.targets[0].id)
            host_path_assignments = [
                assignment
                for assignment in ast.walk(function)
                if isinstance(assignment, ast.Assign)
                and any(
                    isinstance(target, ast.Attribute)
                    and target.attr.casefold().endswith("_path")
                    for target in assignment.targets
                )
            ]
            for assignment in host_path_assignments:
                assigned_names = {
                    node.id
                    for node in ast.walk(assignment.value)
                    if isinstance(node, ast.Name)
                }
                inline_normalization = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "replace"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "\\"
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "/"
                    for node in ast.walk(assignment.value)
                )
                if not inline_normalization and not (
                    assigned_names & normalized_names
                ):
                    target_names = ", ".join(
                        ast.unparse(target)
                        for target in assignment.targets
                    )
                    issues.append(
                        owner_prefix
                        + f"normalize the value assigned to {target_names} with "
                        '.replace("\\\\", "/") before passing it to the host'
                    )
            if (
                re.search(r"\b(?:host|unreal)\s+package\s+paths?\b", prompt_lower)
                and any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"exists", "is_dir", "is_file"}
                    and "destination" in ast.unparse(node.func.value).casefold()
                    for node in preceding_nodes
                )
            ):
                issues.append(
                    owner_prefix
                    + "host package paths must not be validated as filesystem "
                    "directories; validate their string/package form instead"
                )
        if requires_exactly_one:
            import_execution_lines = [
                int(getattr(call, "lineno", 10**9))
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "import_asset_tasks"
            ]
            if import_execution_lines and any(
                isinstance(node, ast.Attribute)
                and node.attr == "imported_object_paths"
                and int(getattr(node, "lineno", 10**9))
                < min(import_execution_lines)
                for node in ast.walk(function)
            ):
                issues.append(
                    owner_prefix
                    + "read imported object paths only after host import execution"
                )
            path_collection_names = {
                target.id
                for assignment in ast.walk(function)
                if isinstance(assignment, ast.Assign)
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and any(
                    isinstance(child, ast.Attribute)
                    and "path" in child.attr.casefold()
                    for child in ast.walk(assignment.value)
                )
                for target in assignment.targets
            }
            exact_count_guard = any(
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Call)
                and isinstance(node.left.func, ast.Name)
                and node.left.func.id == "len"
                and len(node.left.args) == 1
                and (
                    any(
                        isinstance(child, ast.Attribute)
                        and "path" in child.attr.casefold()
                        for child in ast.walk(node.left.args[0])
                    )
                    or (
                        isinstance(node.left.args[0], ast.Name)
                        and node.left.args[0].id in path_collection_names
                    )
                )
                and any(
                    isinstance(comparator, ast.Constant)
                    and comparator.value == 1
                    for comparator in node.comparators
                )
                for node in ast.walk(function)
            )
            if not exact_count_guard:
                issues.append(
                    owner_prefix
                    + "enforce the requested exactly-one returned path contract "
                    "with an explicit len(... ) comparison to 1"
                )
    return sorted(set(issues))


def _host_result_and_redundant_guard_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Require checked host load/save results and reject impossible guards."""

    prompt_lower = str(request_prompt or "").casefold()
    checks_loads = "load" in prompt_lower
    checks_saves = "save" in prompt_lower
    issues: list[str] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def direct_call_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and parts:
            return ".".join([cursor.id, *reversed(parts)])
        return ""

    explicit_save_paths = list(dict.fromkeys(
        path
        for path in re.findall(
            r"\b((?:unreal|maya(?:\.cmds)?|cmds|bpy|pyfbsdk)"
            r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\(",
            str(request_prompt or ""),
        )
        if path.rsplit(".", 1)[-1].casefold().startswith("save")
    ))
    generated_calls = [
        (
            function,
            direct_call_path(call.func),
        )
        for function in functions
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
    ]
    for expected_path in explicit_save_paths:
        expected_suffix = ".".join(expected_path.split(".")[-2:]).casefold()
        if any(
            actual_path.casefold() == expected_path.casefold()
            or actual_path.casefold().endswith("." + expected_suffix)
            or actual_path.casefold() == expected_suffix
            for _function, actual_path in generated_calls
            if actual_path
        ):
            continue
        ranked_owners: list[tuple[int, str]] = []
        for function in functions:
            score = 0
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
            ):
                path = direct_call_path(call.func).casefold()
                leaf = path.rsplit(".", 1)[-1]
                if path.startswith(
                    ("unreal.", "maya.", "cmds.", "bpy.", "pyfbsdk.")
                ):
                    score += 2
                if leaf.startswith(("load", "create", "import", "set_")):
                    score += 3
                if leaf in {"set_editor_property", "modify"}:
                    score += 4
            if function.name == "__init__":
                score -= 3
            ranked_owners.append((score, function.name))
        owner = (
            max(ranked_owners, key=lambda item: item[0])[1]
            if ranked_owners
            else "<module>"
        )
        scope = "callable" if owner != "<module>" else "module"
        issues.append(
            f"[scope:{scope}][owner:{owner}] perform requested host save "
            f"operation `{expected_path}` before returning and check its "
            "boolean result"
        )

    for function in functions:
        owner_prefix = f"[scope:callable][owner:{function.name}] "
        parent_by_id = {
            id(child): parent
            for parent in ast.walk(function)
            for child in ast.iter_child_nodes(parent)
        }
        bool_locals = {
            target.id
            for assignment in ast.walk(function)
            if isinstance(assignment, ast.Assign)
            and isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id == "bool"
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }
        for statement in ast.walk(function):
            if (
                isinstance(statement, ast.If)
                and isinstance(statement.test, ast.Attribute)
                and any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "set_editor_property"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Constant)
                    and isinstance(call.args[1].value, bool)
                    for call in ast.walk(statement)
                )
            ):
                issues.append(
                    owner_prefix
                    + "set the requested boolean editor property "
                    "unconditionally from the request field so False is applied"
                )
        for guard in (
            node for node in ast.walk(function) if isinstance(node, ast.If)
        ):
            guard_text = ast.unparse(guard.test)
            for local_name in bool_locals:
                if re.search(
                    rf"\b{re.escape(local_name)}\s+is\s+not\s+None\b",
                    guard_text,
                ):
                    issues.append(
                        owner_prefix
                        + f"remove the redundant `{local_name} is not None` "
                        "guard because bool normalization cannot produce None"
                    )

        for assignment in (
            node for node in ast.walk(function) if isinstance(node, ast.Assign)
        ):
            if not (
                checks_loads
                and len(assignment.targets) == 1
                and isinstance(assignment.targets[0], ast.Name)
                and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Attribute)
                and assignment.value.func.attr.startswith("load")
            ):
                continue
            loaded_name = assignment.targets[0].id
            guarded = any(
                isinstance(candidate, ast.If)
                and int(getattr(candidate, "lineno", 0))
                > int(getattr(assignment, "lineno", 0))
                and re.search(
                    rf"(?:not\s+{re.escape(loaded_name)}\b|"
                    rf"\b{re.escape(loaded_name)}\s+is\s+None\b)",
                    ast.unparse(candidate.test),
                )
                and any(isinstance(child, ast.Raise) for child in ast.walk(candidate))
                for candidate in ast.walk(function)
            )
            if not guarded:
                issues.append(
                    owner_prefix
                    + f"explicitly reject a failed host load when "
                    f"`{loaded_name}` is None before using or returning it"
                )

        if checks_saves:
            for call in (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("save")
            ):
                parent = parent_by_id.get(id(call))
                checked_inline = isinstance(parent, (ast.UnaryOp, ast.If))
                assigned_name = ""
                if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
                    target = parent.targets[0]
                    if isinstance(target, ast.Name):
                        assigned_name = target.id
                checked_assignment = bool(
                    assigned_name
                    and any(
                        isinstance(candidate, ast.If)
                        and int(getattr(candidate, "lineno", 0))
                        > int(getattr(parent, "lineno", 0))
                        and assigned_name in ast.unparse(candidate.test)
                        and any(
                            isinstance(child, ast.Raise)
                            for child in ast.walk(candidate)
                        )
                        for candidate in ast.walk(function)
                    )
                )
                if not checked_inline and not checked_assignment:
                    issues.append(
                        owner_prefix
                        + f"check the boolean result of `{call.func.attr}` and "
                        "raise an actionable error when saving fails"
                    )
    return sorted(set(issues))


def _qt_progress_surface_issues(
    tree: ast.AST,
    request_prompt: str,
    path: str = "",
) -> list[str]:
    """Require UI callbacks to expose current, total, and status values."""

    prompt_lower = str(request_prompt or "").casefold()
    qt_module = any(
        (
            isinstance(node, ast.ImportFrom)
            and str(node.module or "").startswith(
                ("PySide", "PyQt", "custom_qt")
            )
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name.startswith(("PySide", "PyQt", "custom_qt"))
                for alias in node.names
            )
        )
        for node in getattr(tree, "body", [])
    )
    if (
        "progress" not in prompt_lower
        or "callback" not in prompt_lower
        or not re.search(r"\b(?:qt|pyside|pyqt|widget|dialog)\b", prompt_lower)
        or not qt_module
    ):
        return []
    issues: list[str] = []
    callback_names: set[str] = set()
    callback_lambda_ids: set[int] = set()
    for call in (
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
    ):
        arguments = [
            (argument, "")
            for argument in call.args
        ] + [
            (keyword.value, str(keyword.arg or ""))
            for keyword in call.keywords
        ]
        for argument, keyword_name in arguments:
            argument_name = (
                argument.id
                if isinstance(argument, ast.Name)
                else argument.attr
                if isinstance(argument, ast.Attribute)
                else ""
            )
            if "progress" not in (
                keyword_name.casefold() + " " + argument_name.casefold()
            ):
                continue
            if isinstance(argument, (ast.Name, ast.Attribute)):
                callback_names.add(argument_name)
            elif isinstance(argument, ast.Lambda):
                callback_lambda_ids.add(id(argument))
    callback_nodes = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in callback_names
        )
        or (isinstance(node, ast.Lambda) and id(node) in callback_lambda_ids)
    ]
    for callback in callback_nodes:
        parameter_offset = (
            1
            if isinstance(callback, (ast.FunctionDef, ast.AsyncFunctionDef))
            and callback.args.args
            and callback.args.args[0].arg in {"self", "cls"}
            else 0
        )
        parameters = [
            argument.arg
            for argument in callback.args.args[
                parameter_offset:parameter_offset + 3
            ]
        ]
        invalid_arity = len(parameters) != 3
        callback_text = ast.unparse(callback)
        missing_parameters = [
            parameter
            for parameter in parameters
            if len(re.findall(rf"\b{re.escape(parameter)}\b", callback_text)) < 2
        ]
        required_methods = {"setRange", "setValue", "setText"}
        called_methods = {
            call.func.attr
            for call in ast.walk(callback)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
        }
        missing_methods = sorted(required_methods - called_methods)
        if invalid_arity or missing_parameters or missing_methods:
            details: list[str] = []
            if invalid_arity:
                details.append(
                    "callback must accept current, total, and message"
                )
            if missing_parameters:
                details.append(
                    "unused callback values: " + ", ".join(missing_parameters)
                )
            if missing_methods:
                details.append(
                    "missing visible updates: " + ", ".join(missing_methods)
                )
            issues.append(
                f"[scope:callable][owner:{callback.name if isinstance(callback, (ast.FunctionDef, ast.AsyncFunctionDef)) else '<lambda>'}] "
                "replace the UI progress callback with a callback that sets "
                "range from total, value from current, and status text from "
                "message; " + "; ".join(details)
            )
    return sorted(set(issues))


def _dynamic_host_api_member_issues(tree: ast.AST) -> list[str]:
    """Reject unverified dynamic member names on host-integrated callables."""

    issues: list[str] = []
    for function in [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _runtime_api_paths_in_tree(node)
    ]:
        dynamic_members = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in {"getattr", "hasattr"}
            and len(call.args) >= 2
            and not (
                isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, str)
            )
        ]
        if dynamic_members:
            issues.append(
                f"[scope:callable][owner:{function.name}] "
                "Host API member names must be exact indexed "
                "members, not dynamically constructed getattr/hasattr names. "
                "Replace the dynamic lookup with an explicit normalized-input "
                "mapping whose values are exact verified enum or API members, "
                "and reject unknown keys"
            )
    return issues


def _official_unreal_call_signature_issues(tree: ast.AST) -> list[str]:
    """Validate Unreal call arity against cached authoritative signatures."""

    try:
        from tech_connector.bridges.unreal.unreal_api_docs import (
            lookup_official_unreal_api,
        )
    except Exception:
        return []

    def direct_api_path(expression: ast.AST) -> str:
        parts: list[str] = []
        cursor = expression
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and cursor.id == "unreal" and parts:
            return ".".join(["unreal", *reversed(parts)])
        return ""

    def parameter_contract(signature: str) -> tuple[list[str], int, int] | None:
        match = re.search(r"\((.*)\)\s*(?:→|$)", signature)
        if not match:
            return None
        parameters = [
            value.strip()
            for value in match.group(1).split(",")
            if value.strip()
        ]
        names = [
            re.split(r"\s*(?::|=|\s)\s*", value, maxsplit=1)[0]
            for value in parameters
        ]
        required = sum(
            1
            for value in parameters
            if "=" not in value and not value.startswith(("*", "/"))
        )
        maximum = sum(
            1 for value in parameters if not value.startswith(("*", "/"))
        )
        return names, required, maximum

    issues: list[str] = []
    functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for top_level in tree.body:
        if isinstance(top_level, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append((top_level.name, top_level))
        elif isinstance(top_level, ast.ClassDef):
            functions.extend(
                (f"{top_level.name}.{method.name}", method)
                for method in top_level.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            )

    for owner, function in functions:
        local_api_owners: dict[str, str] = {}
        for assignment in ast.walk(function):
            if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                continue
            value = assignment.value
            if not isinstance(value, ast.Call):
                continue
            called_path = direct_api_path(value.func)
            if not called_path:
                continue
            evidence = lookup_official_unreal_api(called_path)
            return_match = re.search(
                r"→\s*([A-Za-z_][A-Za-z0-9_]*)",
                str((evidence or {}).get("signature") or ""),
            )
            if not return_match:
                continue
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    local_api_owners[target.id] = (
                        f"unreal.{return_match.group(1)}"
                    )

        for call in [
            node for node in ast.walk(function) if isinstance(node, ast.Call)
        ]:
            api_path = direct_api_path(call.func)
            if (
                not api_path
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in local_api_owners
            ):
                api_path = (
                    f"{local_api_owners[call.func.value.id]}.{call.func.attr}"
                )
            if not api_path:
                continue
            evidence = lookup_official_unreal_api(api_path)
            signature = str((evidence or {}).get("signature") or "")
            if not evidence or not evidence.get("authoritative_signature"):
                continue
            contract = parameter_contract(signature)
            if contract is None:
                continue
            parameter_names, minimum, maximum = contract
            supplied = len(call.args) + len(call.keywords)
            unknown_keywords = sorted(
                keyword.arg
                for keyword in call.keywords
                if keyword.arg
                and keyword.arg not in parameter_names
            )
            if minimum <= supplied <= maximum and not unknown_keywords:
                continue
            detail = (
                f"expects {minimum}..{maximum} argument(s), received {supplied}"
            )
            if unknown_keywords:
                detail += (
                    "; unknown keyword(s): " + ", ".join(unknown_keywords)
                )
            issues.append(
                f"[scope:callable][owner:{owner}] {api_path} {detail}. "
                f"Authoritative signature: {signature}"
            )
    return sorted(set(issues))


def _official_unreal_editor_property_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate string-based Unreal editor properties against official docs."""

    try:
        from tech_connector.bridges.unreal.unreal_api_docs import (
            lookup_official_unreal_api,
        )
    except Exception:
        return []

    prompt_lower = str(request_prompt or "").casefold()
    owner_candidates = [
        owner
        for token, owner in (
            ("texture", "Texture"),
            ("material", "Material"),
            ("static mesh", "StaticMesh"),
            ("skeletal mesh", "SkeletalMesh"),
        )
        if token in prompt_lower
    ]
    if not owner_candidates:
        return []

    issues: list[str] = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        property_calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"set_editor_property", "get_editor_property"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ]
        for call in property_calls:
            accessor = call.func.attr
            literal = str(call.args[0].value)
            snake = re.sub(
                r"(?<!^)(?=[A-Z])",
                "_",
                literal,
            ).casefold()
            member_candidates = list(dict.fromkeys([
                literal.casefold(),
                snake,
            ]))
            evidence = None
            for owner in owner_candidates:
                for member in member_candidates:
                    evidence = lookup_official_unreal_api(
                        f"unreal.{owner}.{member}",
                        timeout=3.0,
                    )
                    if evidence:
                        break
                if evidence:
                    break
            if not evidence:
                getter_name = f"get_{snake}"
                getter_evidence = None
                if accessor == "get_editor_property":
                    for owner in [*owner_candidates, "Object"]:
                        getter_evidence = lookup_official_unreal_api(
                            f"unreal.{owner}.{getter_name}",
                            timeout=3.0,
                        )
                        if getter_evidence:
                            break
                if getter_evidence:
                    issues.append(
                        f"[scope:callable][owner:{function.name}] "
                        f"get_editor_property uses unverified literal `{literal}`; "
                        f"use verified Unreal getter `{getter_name}()`. "
                        f"Authoritative source: "
                        f"{getter_evidence.get('source') or ''}"
                    )
                else:
                    issues.append(
                        f"[scope:callable][owner:{function.name}] {accessor} "
                        f"uses unverified Unreal property literal `{literal}`; "
                        "no authoritative property evidence was found"
                    )
                continue
            canonical = str(
                evidence.get("canonical_qualified_name")
                or evidence.get("qualified_name")
                or ""
            ).rsplit(".", 1)[-1]
            if canonical and canonical != literal:
                issues.append(
                    f"[scope:callable][owner:{function.name}] "
                    f"{accessor} uses `{literal}`, expected the exact "
                    f"official Unreal property `{canonical}`. "
                    f"Authoritative source: {evidence.get('source') or ''}"
                )
    return sorted(set(issues))


def _bridge_query_unreal_api_contract(api_path: str, project_root: str | None) -> bool | None:
    """
    Validate Unreal Python API paths from indexed capability/metadata sources.

    Returns True when an indexed entry matches api_path, False when the index is
    empty for the query, and None when metadata lookup is unavailable.
    """

    if not api_path:
        return None
    try:
        from tech_connector.services.unreal.capability_graph_service import resolve_unreal_graph_item
    except Exception:
        return None

    try:
        lookup = resolve_unreal_graph_item(api_path, project_root=project_root, sync=False)
    except Exception:
        return None

    if not isinstance(lookup, dict) or not lookup.get("success"):
        return None

    lowered_target = api_path.strip().lower()
    candidate_keys = ("functions", "capabilities", "symbols", "python_api")
    candidate_rows: list[dict[str, Any]] = []
    for key in candidate_keys:
        rows = lookup.get(key) or []
        candidate_rows.extend(row for row in rows if isinstance(row, dict))

    if not candidate_rows:
        return None

    for row in candidate_rows:
        values = {
            str(row.get("qualified_name") or "").strip().lower(),
            str(row.get("name") or "").strip().lower(),
            str(row.get("symbol_key") or "").strip().lower(),
            str(row.get("entrypoint") or "").strip().lower(),
        }
        if any(
            value
            and (value == lowered_target or value.startswith(f"{lowered_target}.") or lowered_target.startswith(f"{value}."))
            for value in values
        ):
            return True
    return None


_RUNTIME_API_VALIDATION_CACHE: dict[tuple[str, str], bool | None] = {}


def _prime_runtime_api_validation_cache(
    api_paths: set[str],
    project_root: str | None,
) -> None:
    """Resolve qualified Unreal APIs in one exact indexed lookup pass."""

    unreal_paths = sorted(
        path for path in api_paths if str(path).startswith("unreal.")
    )
    if not unreal_paths:
        return
    try:
        from tech_connector.services.unreal.capability_graph_service import (
            validate_unreal_api_paths,
        )

        resolved = validate_unreal_api_paths(unreal_paths, project_root)
    except Exception:
        resolved = {path: None for path in unreal_paths}
    try:
        from tech_connector.services.symbol_evidence_service import (
            resolve_runtime_api_evidence,
        )

        for path in unreal_paths:
            if resolved.get(path) is True:
                continue
            official = resolve_runtime_api_evidence(
                path,
                project_root=project_root or "",
                allow_official_research=True,
            )
            if official is True:
                resolved[path] = True
    except Exception:
        pass
    root_key = str(Path(project_root).resolve()) if project_root else ""
    for path in unreal_paths:
        _RUNTIME_API_VALIDATION_CACHE[(root_key, path)] = resolved.get(path)


def _resolved_runtime_chain_exists(
    api_path: str,
    *,
    project_root: str | None = None,
) -> bool | None:
    """
    Resolve a runtime dot-chain without guessing.

    Returns:
        True: chain exists in imported runtime module.
        False: runtime is importable and chain is missing.
        None: runtime module unavailable in this environment.
    """

    parts = [part for part in (api_path or "").strip().split(".") if part]
    if len(parts) < 2:
        return None
    root = parts[0]
    root_key = str(Path(project_root).resolve()) if project_root else ""
    cache_key = (root_key, api_path)
    if cache_key in _RUNTIME_API_VALIDATION_CACHE:
        return _RUNTIME_API_VALIDATION_CACHE[cache_key]
    if root in _HOST_RUNTIME_MODULES and project_root:
        try:
            from tech_connector.services.symbol_evidence_service import (
                resolve_runtime_api_evidence,
            )

            evidenced = resolve_runtime_api_evidence(
                api_path,
                project_root=project_root,
                allow_official_research=True,
            )
            if evidenced is not None:
                _RUNTIME_API_VALIDATION_CACHE[cache_key] = evidenced
                return evidenced
        except Exception:
            pass
    if root == "unreal":
        bridged = _bridge_query_unreal_api_contract(api_path, project_root)
        if bridged is not None:
            _RUNTIME_API_VALIDATION_CACHE[cache_key] = bridged
            return bridged

    if root in _HOST_RUNTIME_MODULES:
        module_obj = sys.modules.get(root)
        if module_obj is None:
            return None
    else:
        try:
            module_obj = __import__(root)
        except Exception:
            return None

    current = module_obj
    for part in parts[1:]:
        if not hasattr(current, part):
            return False
        try:
            current = getattr(current, part)
        except Exception:
            return False
    return True


def _invalid_runtime_api_contracts(
    request_prompt: str,
    tree: ast.AST | None = None,
    *,
    project_root: str | None = None,
) -> tuple[list[str], list[str]]:
    """
    Cross-check explicitly requested runtime APIs against live introspection.

    Returns (invalid, unverifiable) paths.
    """

    contracts = set(_infer_explicit_runtime_api_requests(request_prompt))
    if tree is not None:
        contracts.update(_runtime_api_paths_in_tree(tree))
    invalid: list[str] = []
    unverifiable: list[str] = []

    def owned_contract(api_path: str) -> str:
        if tree is None:
            return api_path
        owners: list[str] = []
        for top_level in tree.body:
            if isinstance(
                top_level,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ) and api_path in _runtime_api_paths_in_tree(top_level):
                owners.append(top_level.name)
            elif isinstance(top_level, ast.ClassDef):
                owners.extend(
                    f"{top_level.name}.{method.name}"
                    for method in top_level.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and api_path in _runtime_api_paths_in_tree(method)
                )
        return (
            f"[scope:callable][owner:{owners[0]}] {api_path}"
            if len(owners) == 1
            else api_path
        )

    for api_path in sorted(contracts):
        result = _resolved_runtime_chain_exists(api_path, project_root=project_root)
        if result is True:
            continue
        if result is None:
            unverifiable.append(owned_contract(api_path))
        else:
            invalid.append(owned_contract(api_path))

    return invalid, unverifiable


def _imported_call_api_contracts(
    tree: ast.AST,
    *,
    current_module: str,
    candidate_module_trees: dict[str, ast.Module],
    project_root: str | None = None,
) -> tuple[list[str], list[str]]:
    """Validate calls rooted in imports without guessing missing API members."""

    imports: dict[str, str] = {}
    package_parts = current_module.split(".")[:-1]
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            relative_package = list(package_parts)
            if node.level:
                trim = max(0, node.level - 1)
                relative_package = (
                    relative_package[: len(relative_package) - trim]
                    if trim
                    else relative_package
                )
                module_name = ".".join(
                    [*relative_package, *str(node.module or "").split(".")]
                ).strip(".")
            else:
                module_name = str(node.module or "").strip(".")
            for alias in node.names:
                if alias.name == "*":
                    continue
                imports[alias.asname or alias.name] = ".".join(
                    part for part in (module_name, alias.name) if part
                )

    def expression_chain(node: ast.AST) -> list[str]:
        parts: list[str] = []
        cursor = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
            return list(reversed(parts))
        return []

    def generated_symbol_exists(path: str) -> bool | None:
        matching_module = next(
            (
                module_name
                for module_name in sorted(
                    candidate_module_trees,
                    key=len,
                    reverse=True,
                )
                if path == module_name or path.startswith(module_name + ".")
            ),
            "",
        )
        if not matching_module:
            return None
        remainder = path[len(matching_module):].strip(".").split(".")
        remainder = [part for part in remainder if part]
        if not remainder:
            return True
        current_nodes = list(candidate_module_trees[matching_module].body)
        for index, part in enumerate(remainder):
            found: ast.AST | None = None
            for candidate in current_nodes:
                names: list[str] = []
                if isinstance(candidate, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = [candidate.name]
                elif isinstance(candidate, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        candidate.targets
                        if isinstance(candidate, ast.Assign)
                        else [candidate.target]
                    )
                    names = [
                        target.id for target in targets if isinstance(target, ast.Name)
                    ]
                elif isinstance(candidate, ast.Import):
                    names = [
                        alias.asname or alias.name.split(".", 1)[0]
                        for alias in candidate.names
                    ]
                elif isinstance(candidate, ast.ImportFrom):
                    names = [alias.asname or alias.name for alias in candidate.names]
                if part in names:
                    found = candidate
                    break
            if found is None:
                return False
            if index == len(remainder) - 1:
                return True
            if isinstance(found, ast.ClassDef):
                current_nodes = list(found.body)
            else:
                return False
        return True

    def installed_symbol_exists(path: str) -> bool | None:
        parts = path.split(".")
        imported_any_owner = False
        for split_at in range(1, len(parts) + 1):
            module_name = ".".join(parts[:split_at])
            try:
                current: Any = __import__(module_name, fromlist=["*"])
            except Exception:
                continue
            imported_any_owner = True
            for part in parts[split_at:]:
                if not hasattr(current, part):
                    current = None
                    break
                try:
                    current = getattr(current, part)
                except Exception:
                    current = None
                    break
            if current is not None:
                return callable(current)

        # Host-facing internal modules can be source-valid even when importing
        # their package would execute an unavailable DCC dependency. Resolve
        # those symbols from Python source before treating an import failure as
        # evidence that the callable was invented.
        for split_at in range(len(parts) - 1, 0, -1):
            module_parts = parts[:split_at]
            remainder = parts[split_at:]
            for search_root in sys.path:
                root = Path(search_root or Path.cwd())
                source_candidates = (
                    root.joinpath(*module_parts).with_suffix(".py"),
                    root.joinpath(*module_parts, "__init__.py"),
                )
                source_path = next(
                    (candidate for candidate in source_candidates if candidate.is_file()),
                    None,
                )
                if source_path is None:
                    continue
                try:
                    source_tree = ast.parse(
                        source_path.read_text(encoding="utf-8"),
                        filename=str(source_path),
                    )
                except (OSError, UnicodeError, SyntaxError):
                    continue
                current_nodes: list[ast.stmt] = list(source_tree.body)
                for index, part in enumerate(remainder):
                    found = next(
                        (
                            candidate
                            for candidate in current_nodes
                            if isinstance(
                                candidate,
                                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and candidate.name == part
                        ),
                        None,
                    )
                    if found is None:
                        break
                    if index == len(remainder) - 1:
                        return isinstance(
                            found,
                            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    current_nodes = (
                        list(found.body)
                        if isinstance(found, ast.ClassDef)
                        else []
                    )
                else:
                    return True
                return False
        return False if imported_any_owner else None

    invalid: set[str] = set()
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = expression_chain(node.func)
        if not chain or chain[0] not in imports:
            continue
        imported_parts = [
            part for part in imports[chain[0]].split(".") if part
        ]
        call_tail = list(chain[1:])
        overlap = 0
        for candidate_overlap in range(
            min(len(imported_parts), len(call_tail)),
            0,
            -1,
        ):
            if (
                imported_parts[-candidate_overlap:]
                == call_tail[:candidate_overlap]
            ):
                overlap = candidate_overlap
                break
        qualified = ".".join([
            *imported_parts,
            *call_tail[overlap:],
        ])
        host_local_call = qualified.split(".", 1)[0] in _HOST_RUNTIME_MODULES
        if host_local_call:
            resolution = _resolved_runtime_chain_exists(
                qualified,
                project_root=project_root,
            )
        else:
            resolution = generated_symbol_exists(qualified)
            if resolution is None:
                resolution = installed_symbol_exists(qualified)
        if resolution is False:
            invalid.add(qualified)
        elif resolution is None and not host_local_call:
            unresolved.add(qualified)
    return sorted(invalid), sorted(unresolved)


def _validate_candidate_changes(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None,
    request_prompt: str,
    allowed_external_paths: set[str] | None = None,
    behavioral_proof_deferred: bool = False,
) -> list[dict[str, Any]]:
    """Validate generated Python in memory before a diff can be approved."""

    validation_started = time.perf_counter()
    _RUNTIME_API_VALIDATION_CACHE.clear()
    disposable_elapsed_ms = 0.0
    results: list[dict[str, Any]] = []
    inferred_requirements = _infer_prompt_requirements(request_prompt)
    inferred_widget_requirements = _infer_ui_widget_requirements(request_prompt)
    candidate_sources = {
        str(Path(str(item.get("path") or "")).resolve()): str(item.get("after") or "")
        for item in changes
        if str(item.get("path") or "")
    }
    final_candidate_path = next(
        reversed(candidate_sources),
        "",
    )
    candidate_module_trees: dict[str, ast.Module] = {}
    root_path = Path(project_root).resolve() if project_root else None
    for path_text, source in candidate_sources.items():
        candidate_path = Path(path_text)
        if candidate_path.suffix.lower() != ".py" or root_path is None:
            continue
        try:
            relative = candidate_path.relative_to(root_path).with_suffix("")
            module_parts = list(relative.parts)
            if module_parts and module_parts[-1] == "__init__":
                module_parts.pop()
            module_name = ".".join(module_parts)
            if module_name:
                candidate_module_trees[module_name] = ast.parse(
                    source,
                    filename=path_text,
                )
        except (SyntaxError, ValueError):
            continue
    package_generated_runtime_apis: set[str] = set()
    for path_text, source in candidate_sources.items():
        if _is_test_path(Path(path_text)):
            continue
        try:
            package_generated_runtime_apis.update(
                _runtime_api_calls_in_tree(ast.parse(source, filename=path_text))
            )
        except SyntaxError:
            continue
    _prime_runtime_api_validation_cache(
        {
            *_infer_explicit_runtime_api_requests(request_prompt),
            *package_generated_runtime_apis,
            *(
                path
                for tree in candidate_module_trees.values()
                for path in _runtime_api_paths_in_tree(tree)
            ),
        },
        project_root,
    )

    def patch_target_exists(
        target: str,
        seen: set[str] | None = None,
    ) -> bool:
        target = str(target or "").strip()
        if not target or "." not in target:
            return False
        seen = set(seen or ())
        if target in seen:
            return False
        seen.add(target)
        candidate_module = next(
            (
                module_name
                for module_name in sorted(
                    candidate_module_trees,
                    key=len,
                    reverse=True,
                )
                if target.startswith(module_name + ".")
            ),
            "",
        )
        if candidate_module:
            tree = candidate_module_trees[candidate_module]
            remaining = target[len(candidate_module) + 1 :].split(".")
            top_level = {
                node.name: node
                for node in tree.body
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            imported_bindings: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_bindings[alias.asname or alias.name.split(".")[0]] = (
                            alias.name
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        imported_bindings[alias.asname or alias.name] = (
                            f"{node.module}.{alias.name}"
                        )
            first = remaining.pop(0)
            current_node = top_level.get(first)
            if current_node is not None:
                for attribute in remaining:
                    if not isinstance(current_node, ast.ClassDef):
                        return False
                    current_node = next(
                        (
                            child
                            for child in current_node.body
                            if isinstance(
                                child,
                                (
                                    ast.ClassDef,
                                    ast.FunctionDef,
                                    ast.AsyncFunctionDef,
                                ),
                            )
                            and child.name == attribute
                        ),
                        None,
                    )
                    if current_node is None:
                        return False
                return True
            imported_path = imported_bindings.get(first)
            if not imported_path:
                return False
            if not remaining:
                return True
            runtime_parts = imported_path.split(".") + remaining
            forwarded_target = ".".join(runtime_parts)
            if any(
                forwarded_target == module_name
                or forwarded_target.startswith(module_name + ".")
                for module_name in candidate_module_trees
            ):
                return patch_target_exists(forwarded_target, seen)
        else:
            runtime_parts = target.split(".")

        if runtime_parts and runtime_parts[0] in _HOST_RUNTIME_MODULES:
            runtime_resolution = _resolved_runtime_chain_exists(
                ".".join(runtime_parts),
                project_root=project_root,
            )
            if runtime_resolution is not None:
                return runtime_resolution

        runtime_object: Any = None
        consumed = 0
        for index in range(len(runtime_parts), 0, -1):
            module_name = ".".join(runtime_parts[:index])
            try:
                runtime_object = importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
                continue
            consumed = index
            break
        if runtime_object is None:
            return False
        for attribute in runtime_parts[consumed:]:
            if not hasattr(runtime_object, attribute):
                return False
            runtime_object = getattr(runtime_object, attribute)
        return True

    standalone_entrypoint_symbols = list(dict.fromkeys(
        re.findall(
            r"__main__[^\n.;]*?\b(?:runs?|calls?|invokes?)\s+"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            request_prompt,
            flags=re.IGNORECASE,
        )
    ))
    requested_symbols = _requested_public_symbol_names(request_prompt)
    requested_symbols.update(standalone_entrypoint_symbols)
    requested_verification_symbols = set(re.findall(
        r"\b(?:add|define|implement|include|provide|expose)\s+"
        r"(?:an?\s+|the\s+)?"
        r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
        r"[^.!?\n]{0,180}\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|"
        r"validates?|self[- ]test|fake\s+"
        r"(?:clock|client|host|service))\b",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    requested_signal_handlers = _infer_signal_handler_requirements(request_prompt)
    available_public_symbols: set[str] = set()
    explicit_single_file_scope = bool(
        re.search(
            r"\b(?:exactly|only)\s+(?:one|1)\s+"
            r"(?:new\s+)?(?:[A-Za-z0-9_+-]+\s+){0,3}files?\b"
            r"|\bno\s+(?:other|extra|additional)\s+files?\b"
            r"|\bdo\s+not\s+(?:add|create|generate|write)\s+(?:any\s+)?"
            r"(?:other|extra|additional)\s+files?\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    standalone_self_test = (
        len(candidate_sources) == 1
        and any(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in (
                    set(standalone_entrypoint_symbols)
                    | requested_verification_symbols
                )
                and any(isinstance(child, ast.Assert) for child in ast.walk(node))
                for node in tree.body
            )
            and (
                not standalone_entrypoint_symbols
                or any(
                    isinstance(node, ast.If)
                    and "__name__" in ast.unparse(node.test)
                    and "__main__" in ast.unparse(node.test)
                    and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id in standalone_entrypoint_symbols
                        for call in ast.walk(node)
                        if isinstance(call, ast.Call)
                    )
                    for node in tree.body
                )
            )
            for tree in candidate_module_trees.values()
        )
    )
    changed_test = (
        any(_is_test_path(Path(str(item.get("path") or ""))) for item in changes)
        or standalone_self_test
        or (
            explicit_single_file_scope
            and len(candidate_sources) == 1
        )
    )
    for item in changes:
        path = Path(str(item.get("path") or ""))
        if _is_forbidden_edit_path(str(path)):
            results.append(_quality_result(
                False,
                path,
                "forbidden_edit_path",
                _edit_error_for_forbidden_path(str(path)),
            ))
            continue
        if path.suffix.lower() != ".py":
            continue
        before = str(item.get("before") or "")
        after = _sanitize_python_candidate_text(item.get("after"))
        is_new_file = before.strip() == ""
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
        callback_issues = _progress_callback_contract_issues(
            after_tree,
            request_prompt,
        )
        results.append(_quality_result(
            not callback_issues,
            path,
            "progress_callback_contract",
            "Progress callback calls and proofs use integer current/total steps."
            if not callback_issues
            else "Invalid progress callback contract: " + "; ".join(callback_issues),
        ))
        side_effect_contract_issues = (
            []
            if _is_test_path(path)
            else _requested_pre_side_effect_contract_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not side_effect_contract_issues,
            path,
            "pre_side_effect_contract",
            "Requested input, path, cardinality, and host-side-effect guards are present."
            if not side_effect_contract_issues
            else "Invalid pre-side-effect contract: "
            + "; ".join(side_effect_contract_issues),
        ))
        host_result_issues = (
            []
            if _is_test_path(path)
            else _host_result_and_redundant_guard_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not host_result_issues,
            path,
            "host_result_contract",
            "Host load/save results and normalized-value guards are explicit."
            if not host_result_issues
            else "Invalid host result contract: "
            + "; ".join(host_result_issues),
        ))
        qt_progress_issues = (
            []
            if _is_test_path(path)
            else _qt_progress_surface_issues(after_tree, request_prompt, path)
        )
        results.append(_quality_result(
            not qt_progress_issues,
            path,
            "qt_progress_surface",
            "Qt progress callbacks expose integer range, value, and status."
            if not qt_progress_issues
            else "Invalid Qt progress surface: "
            + "; ".join(qt_progress_issues),
        ))
        dynamic_host_issues = (
            []
            if _is_test_path(path)
            else _dynamic_host_api_member_issues(after_tree)
        )
        results.append(_quality_result(
            not dynamic_host_issues,
            path,
            "dynamic_host_api_members",
            "Host API member ownership is statically verifiable."
            if not dynamic_host_issues
            else f"Unverifiable dynamic host API usage in {path}: "
            + "; ".join(dynamic_host_issues),
        ))
        unreal_signature_issues = (
            []
            if _is_test_path(path)
            else _official_unreal_call_signature_issues(after_tree)
        )
        results.append(_quality_result(
            not unreal_signature_issues,
            path,
            "official_unreal_signatures",
            "Unreal calls match cached authoritative signatures."
            if not unreal_signature_issues
            else "Invalid authoritative Unreal call signature in "
            f"{path}: " + "; ".join(unreal_signature_issues),
        ))
        unreal_property_issues = (
            []
            if _is_test_path(path)
            else _official_unreal_editor_property_issues(
                after_tree,
                request_prompt,
            )
        )
        results.append(_quality_result(
            not unreal_property_issues,
            path,
            "official_unreal_editor_properties",
            "String-based Unreal editor properties match official API names."
            if not unreal_property_issues
            else "Invalid authoritative Unreal editor property in "
            f"{path}: " + "; ".join(unreal_property_issues),
        ))

        before_defs = _public_definition_map(before_tree)
        after_defs = _public_definition_map(after_tree)
        if not _is_test_path(path):
            available_public_symbols.update(name.rsplit(".", 1)[-1] for name in after_defs)
        introduced = {
            name: node for name, node in after_defs.items()
            if name not in before_defs
        }
        before_top_level_defs = {
            name.rsplit(".", 1)[-1]
            for name in before_defs
        }
        imported_modules = _imported_modules(after_tree)
        imported_names = _imported_name_bindings(after_tree)
        path_ui_hint = bool(re.search(
            r"(?:^|[_-])(dialog|window|widget|panel|ui)(?:[_-]|$)",
            path.stem.lower(),
        ))
        imported_qt_surface = any(
            module.lower().startswith(("pyside", "pyqt"))
            for module in imported_modules
        ) or any(
            name.startswith("Q") or name in {"Signal", "Slot"}
            for name in imported_names
        )
        owns_ui_surface = (
            not _is_test_path(path)
            and inferred_requirements["needs_qt_import"]
            and (path_ui_hint or imported_qt_surface)
        )
        file_requirements = dict(inferred_requirements)
        if not owns_ui_surface:
            file_requirements["needs_qt_import"] = False
            file_requirements["needs_signal_connect"] = False
            file_requirements["needs_widget_entrypoint"] = False
        file_widget_requirements = (
            inferred_widget_requirements if owns_ui_surface else []
        )
        file_signal_handlers = requested_signal_handlers if owns_ui_surface else set()
        class_definitions = {
            node.name: node
            for node in after_tree.body
            if isinstance(node, ast.ClassDef)
        }
        unreal_referenced = _tree_uses_identifier(after_tree, "unreal")
        maya_referenced = (
            _tree_uses_identifier(after_tree, "maya")
            or _tree_uses_identifier(after_tree, "cmds")
        )
        cross_dcc = (
            inferred_requirements["needs_unreal_import"]
            and inferred_requirements["needs_maya_import"]
        )
        if (
            not _is_test_path(path)
            and cross_dcc
            and unreal_referenced
            and maya_referenced
        ):
            results.append(_quality_result(
                False,
                path,
                "bridge_architecture:cross_dcc",
                (
                    "A multi-DCC module directly references both Unreal and Maya SDKs. "
                    "Coordinators must use an indexed bridge/adapter and place native SDK "
                    "calls in separate host-local leaf modules; merely localizing both "
                    "imports is not a valid cross-DCC pipeline."
                ),
            ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_unreal_import"]
            and unreal_referenced
        ):
            has_unreal_import = "unreal" in imported_modules
            has_unreal_guard = _has_optional_import_guard(after_tree, "unreal")
            has_unreal_bridge_ref = any(
                _tree_uses_identifier(after_tree, identifier)
                for identifier in (
                    "ProjectIntelligenceService",
                    "execute_unreal_capability",
                    "validate_unreal_capability",
                    "resolve_unreal_capability",
                )
            )
            results.append(_quality_result(
                has_unreal_import or has_unreal_guard or has_unreal_bridge_ref,
                path,
                "import_guard:unreal",
                (
                    "Unreal is imported with a standard top-level import or guarded runtime-safe fallback."
                    if (has_unreal_import or has_unreal_guard or has_unreal_bridge_ref)
                    else "Add Unreal host-module access through either import, optional guarded import, or bridge client/path."
                ),
            ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_maya_import"]
            and maya_referenced
        ):
            has_maya_import = "maya" in imported_modules or "cmds" in imported_modules
            has_maya_guard = _has_optional_import_guard(after_tree, "maya")
            results.append(_quality_result(
                has_maya_import or has_maya_guard,
                path,
                "import_guard:maya",
                (
                    "Maya command access is imported with a standard top-level import or guarded runtime-safe fallback."
                    if (has_maya_import or has_maya_guard)
                    else "Add import/availability handling for Maya commands (preferred: `import maya.cmds as cmds` or `import maya`, fallback-safe: try/except ImportError or `if \"maya\" in sys.modules:`) when used."
                ),
            ))
        added_widget_classes = [
            name.rsplit(".", 1)[-1]
            for name, node in introduced.items()
            if (
                isinstance(node, ast.ClassDef)
                and any(token in name.lower() for token in ("dialog", "widget", "window"))
            )
        ]
        if (
            file_requirements["needs_widget_entrypoint"]
            and (
                is_new_file
                or (
                    added_widget_classes
                    and _has_widget_class_surface(after_tree, file_widget_requirements)
                )
            )
        ):
            has_entrypoint = _has_main_window_entrypoint(after_tree)
            results.append(_quality_result(
                has_entrypoint,
                path,
                "ui_entrypoint",
                (
                    "New widget/dialog/window module defines a guarded launch entrypoint (if __name__ == \"__main__\") with show()."
                    if has_entrypoint
                    else "For a newly created UI window/widget/dialog file, include a `if __name__ == \"__main__\":` block that constructs and shows the window."
                ),
            ))
        if file_requirements["needs_qt_import"] and not _qt_widget_import_coverage(
            {module.lower() for module in imported_modules},
            imported_names,
        ):
            results.append(_quality_result(
                False,
                path,
                "import_guard:qt",
                "Prompt requests UI behavior, but generated code is not importing a Qt-compatible symbol surface.",
            ))
        (
            class_connects,
            module_level_connects,
            class_connected_self_handlers,
            class_connecting_methods,
            init_calls,
            class_methods_by_class,
            class_method_calls,
            class_widget_defs,
            class_method_nodes,
            class_signal_targets,
            class_widget_ctors,
        ) = _iter_signal_connects(after_tree)
        class_active_methods: dict[str, set[str]] = {}
        for class_name in (
            set(class_methods_by_class)
            | set(init_calls)
            | set(class_connected_self_handlers)
        ):
            seed_methods = (
                set(init_calls.get(class_name, set()))
                | set(class_connected_self_handlers.get(class_name, set()))
                | {"__init__"}
            )
            worklist = list(seed_methods)
            seen = set(seed_methods)
            while worklist:
                method = worklist.pop(0)
                referenced_methods = set(
                    class_method_calls.get(class_name, {}).get(method, set())
                )
                method_node = class_method_nodes.get(class_name, {}).get(method)
                if method_node is not None:
                    referenced_methods.update(
                        node.attr
                        for node in ast.walk(method_node)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in {"self", "cls"}
                        and node.attr
                        in class_methods_by_class.get(class_name, set())
                    )
                for callee in referenced_methods:
                    if callee in seen:
                        continue
                    seen.add(callee)
                    worklist.append(callee)
            class_active_methods[class_name] = seen
        for class_name in class_methods_by_class:
            class_active_methods.setdefault(class_name, {"__init__"})
        for class_name, method_nodes in class_method_nodes.items():
            connection_locations: dict[str, list[str]] = {}
            for method_name in sorted(
                class_active_methods.get(class_name, {"__init__"})
            ):
                method_node = method_nodes.get(method_name)
                if method_node is None:
                    continue
                for call in ast.walk(method_node):
                    if not (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "connect"
                        and call.args
                    ):
                        continue
                    key = "|".join((
                        ast.dump(call.func.value, include_attributes=False),
                        ast.dump(call.args[0], include_attributes=False),
                    ))
                    connection_locations.setdefault(key, []).append(method_name)
            duplicate_locations = [
                locations
                for locations in connection_locations.values()
                if len(locations) > 1
            ]
            if duplicate_locations:
                results.append(_quality_result(
                    False,
                    path,
                    f"duplicate_signal_connection:{class_name}",
                    (
                        f"{class_name} connects the same signal and handler "
                        "more than once along its constructor-reachable path: "
                        + "; ".join(
                            ", ".join(locations)
                            for locations in duplicate_locations
                        )
                    ),
                ))
        flagged_api_bases: set[str] = set()
        for class_name, class_node in class_definitions.items():
            for base_node in class_node.bases:
                if not isinstance(base_node, ast.Name):
                    continue
                base_name = base_node.id
                if base_name not in class_definitions:
                    continue
                if base_name in before_top_level_defs or base_name in flagged_api_bases:
                    continue
                base_node_definition = class_definitions[base_name]
                if (
                    base_name not in requested_symbols
                    and _is_placeholder_class(base_node_definition)
                ):
                    flagged_api_bases.add(base_name)
                    results.append(_quality_result(
                        False,
                        path,
                        f"local_placeholder_api_base:{base_name}",
                        (
                            f"Class `{base_name}` looks like a local placeholder API base; "
                            "prefer importing the canonical implementation instead of defining a stub."
                        ),
                    ))
        if file_requirements["needs_signal_connect"]:
            has_connect_statements = any(connects for connects in class_connects.values())
            if not has_connect_statements:
                results.append(_quality_result(
                    False,
                    path,
                    "signal_connect_present",
                    "Prompt requests UI signal wiring but no `.connect(...)` calls were found in the generated class code.",
                ))
            if module_level_connects:
                results.append(_quality_result(
                    False,
                    path,
                    "signal_connect_scope",
                    "Signal connections must be configured inside class construction paths, not at module scope.",
                ))
            for class_name, handlers in class_connected_self_handlers.items():
                missing_handlers = sorted(
                    handler
                    for handler in handlers
                    if handler not in class_methods_by_class.get(class_name, set())
                )
                results.append(_quality_result(
                    not missing_handlers,
                    path,
                    f"signal_connect_method:{class_name}",
                    (
                        f"All signal handlers for {class_name} resolve to existing methods."
                        if not missing_handlers
                    else f"{class_name} has missing signal handler methods: "
                    + ", ".join(missing_handlers)
                ),
                ))
                for _, handler in class_signal_targets.get(class_name, []):
                    if not handler:
                        continue
                    handler_node = class_method_nodes.get(class_name, {}).get(handler)
                    if handler_node and _is_placeholder_callable(handler_node):
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_signal_handler_placeholder:{handler}",
                            f"Signal handler `{handler}` in {class_name} is a placeholder method and never implemented.",
                        ))
            if file_signal_handlers:
                connected_handlers = {
                    handler
                    for pairs in class_signal_targets.values()
                    for _, handler in pairs
                    if handler
                }
                for handler in sorted(file_signal_handlers):
                    if handler not in connected_handlers:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_signal_handler_missing:{handler}",
                            f"Prompt requests a signal handler `{handler}`, but no `.connect(...)` targets it.",
                        ))
            for class_name, connected_methods in class_connecting_methods.items():
                init_reachable = set(init_calls.get(class_name, set()))
                worklist = list(init_reachable)
                seen = set(init_reachable)
                while worklist:
                    method = worklist.pop(0)
                    for callee in class_method_calls.get(class_name, {}).get(method, set()):
                        if callee in seen:
                            continue
                        seen.add(callee)
                        worklist.append(callee)
                missing_constructors = sorted(
                    method
                    for method in connected_methods
                    if method != "__init__" and method not in seen
                )
                if connected_methods:
                    results.append(_quality_result(
                        not missing_constructors,
                        path,
                        f"signal_connect_in_init:{class_name}",
                        (
                            f"Signal connection setup methods in {class_name} are reachable from class construction."
                            if not missing_constructors
                            else f"{class_name} has connection setup methods not reachable from __init__: "
                            + ", ".join(missing_constructors)
                        ),
                    ))
        if file_widget_requirements:
            imported_names = _imported_name_bindings(after_tree)
            top_level_names = {
                node.name
                for node in after_tree.body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for widget_name, widget_kind in file_widget_requirements:
                owning_classes = sorted(
                    class_name
                    for class_name, widgets in class_widget_defs.items()
                    if widget_name in widgets
                )
                if not owning_classes:
                    results.append(_quality_result(
                        False,
                        path,
                        f"ui_widget_declared:{widget_name}",
                        f"Prompt requests `{widget_name}`, but no class assigns `self.{widget_name}`.",
                    ))
                    continue
                class_name = owning_classes[0]
                ctor_name = class_widget_ctors.get(class_name, {}).get(widget_name)
                if not ctor_name:
                    results.append(_quality_result(
                        False,
                        path,
                        f"ui_widget_constructor:{widget_name}",
                        f"Prompt requests `{widget_name}`, but `{class_name}` assigns it without a constructor call.",
                    ))
                else:
                    expected_ctors = _widget_expected_constructors(widget_kind)
                    ctor_name_tail = _widget_ctor_base_name(ctor_name)
                    if expected_ctors and ctor_name_tail not in expected_ctors:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_constructor:{widget_name}:kind",
                            (
                                f"{widget_name} uses `{ctor_name}`, expected a widget constructor for a {widget_kind} widget "
                                f"like {', '.join(sorted(expected_ctors))}."
                            ),
                        ))
                    if "*" not in imported_names and not _widget_ctor_is_imported(
                        ctor_name,
                        imported_names,
                        top_level_names,
                    ):
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_import:{widget_name}",
                            f"Add explicit import for `{ctor_name}` used by `{widget_name}`.",
                        ))
                if widget_kind == "button":
                    button_links = [
                        (widget, handler)
                        for widget, handler in class_signal_targets.get(class_name, [])
                        if widget == widget_name
                    ]
                    if not button_links:
                        results.append(_quality_result(
                            False,
                            path,
                            f"ui_widget_connected:{widget_name}",
                            (
                                f"`{widget_name}` has no signal wiring for `{class_name}`. "
                                "Connect it during construction using a class method handler."
                            ),
                        ))
                    else:
                        handlers = sorted(
                            handler
                            for _, handler in button_links
                            if handler
                        )
                        if handlers:
                            missing = sorted(
                                handler
                                for handler in handlers
                                if handler not in class_methods_by_class.get(class_name, set())
                            )
                            results.append(_quality_result(
                                not missing,
                                path,
                                f"ui_widget_connected:{widget_name}:method_exists",
                                (
                                    f"{widget_name} is connected to existing methods on {class_name}."
                                    if not missing
                                    else f"{widget_name} connects to missing methods: "
                                    + ", ".join(missing)
                                ),
                            ))
                        else:
                            results.append(_quality_result(
                                False,
                                path,
                                f"ui_widget_connected:{widget_name}:method_exists",
                                f"{widget_name} is connected to non-method callables; use a class handler.",
                            ))
                expected_accessor = _expected_widget_accessor(widget_name, widget_kind)
                active_methods = class_active_methods.get(class_name, {"__init__"})
                handler_reads_widget = False
                output_widget = (
                    widget_name.endswith(("_label", "_preview", "_output"))
                    or bool(
                        re.search(
                            rf"\bread[- ]only\b[^.!?\n]{{0,100}}"
                            rf"\b{re.escape(widget_name)}\b"
                            rf"|\b{re.escape(widget_name)}\b[^.!?\n]{{0,100}}"
                            r"\bread[- ]only\b",
                            request_prompt,
                            flags=re.IGNORECASE,
                        )
                    )
                )
                for method_name, method_node in class_method_nodes.get(class_name, {}).items():
                    if method_name not in active_methods and method_name != "__init__":
                        continue
                    if (
                        output_widget
                        and method_name != "__init__"
                        and _method_updates_widget(method_node, widget_name)
                    ) or _method_uses_widget_access(
                        method_node,
                        widget_name,
                        expected_accessor,
                    ):
                        handler_reads_widget = True
                        break
                results.append(_quality_result(
                    handler_reads_widget if widget_kind != "button" else True,
                    path,
                    f"ui_widget_used:{widget_name}",
                    (
                        f"{widget_name} is consumed by construction-reachable handlers."
                        if (handler_reads_widget or widget_kind == "button")
                        else (
                            f"{widget_name} is never read in connected/constructing handlers. "
                            f"Use `self.{widget_name}` values in a handler."
                        )
                    ),
                ))
        if (
            not _is_test_path(path)
            and inferred_requirements["needs_factory_create_asset"]
            and unreal_referenced
            and not _has_factory_argument_call(after_tree)
        ):
            create_asset_owners: list[str] = []
            for top_level in after_tree.body:
                if isinstance(
                    top_level,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and any(
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "create_asset"
                    for call in ast.walk(top_level)
                    if isinstance(call, ast.Call)
                ):
                    create_asset_owners.append(top_level.name)
                elif isinstance(top_level, ast.ClassDef):
                    create_asset_owners.extend(
                        f"{top_level.name}.{method.name}"
                        for method in top_level.body
                        if isinstance(
                            method,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and any(
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr == "create_asset"
                            for call in ast.walk(method)
                            if isinstance(call, ast.Call)
                        )
                    )
            owner_marker = (
                f"[scope:callable][owner:{create_asset_owners[0]}] "
                if len(create_asset_owners) == 1
                else "[scope:module] "
            )
            results.append(_quality_result(
                False,
                path,
                "create_asset_factory",
                owner_marker
                + "Prompt asks for Unreal asset creation via create_asset; "
                "include the verified factory argument in the exact indexed "
                "create_asset signature.",
            ))
        screen_color_picker_requested = bool(
            re.search(r"\b(?:pick|sample|capture|eyedropper)\b", request_prompt, re.I)
            and re.search(r"\bcolou?r\b", request_prompt, re.I)
            and re.search(
                r"\b(?:anywhere|any point|outside|desktop|screen)\b",
                request_prompt,
                re.I,
            )
        )
        if screen_color_picker_requested and not Path(path).name.startswith("test_"):
            rendered_source = ast.unparse(after_tree)
            captures_desktop = bool(
                re.search(r"\.grabWindow\s*\(\s*0\s*\)", rendered_source)
                or re.search(r"\.grab_window\s*\(\s*0\s*\)", rendered_source)
            )
            samples_pixel = bool(
                re.search(r"\.(?:pixelColor|pixel_color|pixel)\s*\(", rendered_source)
            )
            interactive_pick = bool(
                re.search(
                    r"\b(?:mousePressEvent|mouseReleaseEvent|eventFilter)\b",
                    rendered_source,
                )
            )
            event_filter_hooked = not re.search(
                r"\bdef\s+eventFilter\s*\(",
                rendered_source,
            ) or bool(
                re.search(r"\.installEventFilter\s*\(", rendered_source)
            )
            global_pick_surface = bool(
                re.search(
                    r"\b(?:showFullScreen|show_full_screen|FullScreen|"
                    r"grabMouse|grab_mouse|virtualGeometry|virtual_geometry)\b",
                    rendered_source,
                )
            )
            crosshair_cursor = bool(
                re.search(r"\b(?:CrossCursor|setCursor|set_cursor)\b", rendered_source)
            )
            capture_method_safety: list[bool] = []
            activation_surface_ready = False
            click_uses_global_position = False
            saves_previous_color = False
            restores_previous_color = False
            activation_owner_names: set[str] = set()
            capture_owner_names: set[str] = set()
            event_owner_names: set[str] = set()
            click_owner_names: set[str] = set()
            cancellation_owner_names: set[str] = set()
            timer_owner_names: set[str] = set()
            activation_signal_owner_names: set[str] = set()
            for class_node in [
                node for node in after_tree.body if isinstance(node, ast.ClassDef)
            ]:
                method_map = {
                    method.name: method
                    for method in class_node.body
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for call in ast.walk(class_node):
                    if (
                        not isinstance(call, ast.Call)
                        or not isinstance(call.func, ast.Attribute)
                        or call.func.attr != "connect"
                        or not isinstance(call.func.value, ast.Attribute)
                        or not call.args
                        or not isinstance(call.args[0], ast.Attribute)
                        or not isinstance(call.args[0].value, ast.Name)
                        or call.args[0].value.id != "self"
                    ):
                        continue
                    qualified_owner = (
                        f"{class_node.name}.{call.args[0].attr}"
                    )
                    signal_name = call.func.value.attr
                    if signal_name == "timeout":
                        timer_owner_names.add(qualified_owner)
                    elif signal_name in {
                        "clicked",
                        "pressed",
                        "released",
                        "triggered",
                    }:
                        activation_signal_owner_names.add(qualified_owner)
                connected_handlers = {
                    handler
                    for _widget, handler in class_signal_targets.get(
                        class_node.name,
                        [],
                    )
                    if handler
                }
                activation_methods = {
                    owner.split(".", 1)[1]
                    for owner in activation_signal_owner_names
                    if owner.startswith(class_node.name + ".")
                } or set(connected_handlers)
                pending_methods = list(activation_methods)
                while pending_methods:
                    method_name = pending_methods.pop()
                    method = method_map.get(method_name)
                    if method is None:
                        continue
                    for call in ast.walk(method):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                            and call.func.attr in method_map
                            and call.func.attr not in activation_methods
                        ):
                            activation_methods.add(call.func.attr)
                            pending_methods.append(call.func.attr)
                activation_owner_names.update(
                    f"{class_node.name}.{method_name}"
                    for method_name in activation_methods
                    if method_name in method_map
                )
                activation_surface_ready = activation_surface_ready or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "show",
                        "showFullScreen",
                        "show_full_screen",
                    }
                    and (
                        "overlay" in ast.unparse(call.func.value).casefold()
                        or "surface" in ast.unparse(call.func.value).casefold()
                    )
                    for method_name in activation_methods
                    for method in [method_map.get(method_name)]
                    if method is not None
                    for call in ast.walk(method)
                )
                event_methods = [
                    method
                    for name, method in method_map.items()
                    if name in {
                        "eventFilter",
                        "mousePressEvent",
                        "mouseReleaseEvent",
                        "keyPressEvent",
                        "keyReleaseEvent",
                    }
                ]
                event_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                )
                click_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                    if re.search(
                        r"\bLeftButton\b",
                        ast.unparse(method),
                    )
                )
                cancellation_owner_names.update(
                    f"{class_node.name}.{method.name}"
                    for method in event_methods
                    if re.search(
                        r"\b(?:Key_Escape|Key\.Escape)\b",
                        ast.unparse(method),
                    )
                )
                click_uses_global_position = click_uses_global_position or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "globalPosition",
                        "globalPos",
                    }
                    for method in event_methods
                    for call in ast.walk(method)
                )
                saves_previous_color = saves_previous_color or any(
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and any(
                            marker in target.attr.casefold()
                            for marker in ("previous", "prior", "original")
                        )
                        for target in node.targets
                    )
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in {
                        "text",
                        "currentText",
                        "value",
                    }
                    for node in ast.walk(class_node)
                )
                restores_previous_color = restores_previous_color or any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "setText",
                        "setCurrentText",
                        "setValue",
                    }
                    and any(
                        isinstance(argument, ast.Attribute)
                        and isinstance(argument.value, ast.Name)
                        and argument.value.id == "self"
                        and any(
                            marker in argument.attr.casefold()
                            for marker in ("previous", "prior", "original")
                        )
                        for argument in call.args
                    )
                    for method in event_methods
                    for call in ast.walk(method)
                )
                for method in [
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]:
                    calls = [
                        call
                        for call in ast.walk(method)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                    ]
                    grab_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {"grabWindow", "grab_window"}
                    ]
                    if not grab_lines:
                        continue
                    capture_owner_names.add(
                        f"{class_node.name}.{method.name}"
                    )
                    hide_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {
                            "hide",
                            "setVisible",
                            "set_visible",
                            "close",
                            "hide_overlay",
                        }
                        and (
                            "overlay" in ast.unparse(call.func.value).casefold()
                            or "surface" in ast.unparse(call.func.value).casefold()
                            or "overlay" in call.func.attr.casefold()
                        )
                    ]
                    flush_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {"processEvents", "process_events"}
                    ]
                    show_lines = [
                        call.lineno
                        for call in calls
                        if call.func.attr in {
                            "show",
                            "showFullScreen",
                            "show_full_screen",
                        }
                        and (
                            "overlay" in ast.unparse(call.func.value).casefold()
                            or "surface" in ast.unparse(call.func.value).casefold()
                            or "overlay" in call.func.attr.casefold()
                        )
                    ]
                    first_grab = min(grab_lines)
                    capture_method_safety.append(
                        (
                            any(line < first_grab for line in hide_lines)
                            and any(line < first_grab for line in flush_lines)
                        )
                        or any(first_grab < line for line in show_lines)
                    )
            avoids_overlay_capture = bool(capture_method_safety) and all(
                capture_method_safety
            )
            cancellation_restore_requested = bool(
                re.search(
                    r"\b(?:cancel|escape)\b[^.!?\n]{0,120}\brestor"
                    r"|\brestor[^.!?\n]{0,120}\b(?:cancel|escape)\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            cancellation_state_valid = (
                not cancellation_restore_requested
                or (saves_previous_color and restores_previous_color)
            )
            default_screen_owners = (
                activation_owner_names
                or event_owner_names
                or capture_owner_names
            )
            screen_behavior_checks = (
                (
                    captures_desktop,
                    "capture the desktop with QScreen.grabWindow(0)",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    samples_pixel,
                    "read a pixel from the captured image",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    interactive_pick,
                    "handle mouse input while eyedropper mode is active",
                    event_owner_names,
                ),
                (
                    crosshair_cursor,
                    "show a crosshair cursor",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    global_pick_surface,
                    "provide a screen-wide pick surface or global input",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    avoids_overlay_capture,
                    "hide the actual overlay and flush events before capture",
                    capture_owner_names or timer_owner_names,
                ),
                (
                    event_filter_hooked,
                    "install the declared event filter",
                    activation_owner_names or event_owner_names,
                ),
                (
                    activation_surface_ready,
                    "show the pick surface from the connected activation path",
                    activation_owner_names or default_screen_owners,
                ),
                (
                    click_uses_global_position,
                    "sample the exact left-click global position",
                    click_owner_names,
                ),
                (
                    cancellation_state_valid,
                    "save and restore the pre-pick color on cancellation",
                    cancellation_owner_names,
                ),
            )
            requires_class_owned_repair = any(
                not passed and not owners
                for passed, _description, owners in screen_behavior_checks
            )
            missing_screen_behaviors = [
                description
                + "".join(
                    f" [owner:{owner}]"
                    for owner in sorted(owners)
                )
                for passed, description, owners in screen_behavior_checks
                if not passed
            ]
            results.append(_quality_result(
                captures_desktop
                and samples_pixel
                and interactive_pick
                and crosshair_cursor
                and global_pick_surface
                and avoids_overlay_capture
                and event_filter_hooked
                and activation_surface_ready
                and click_uses_global_position
                and cancellation_state_valid,
                path,
                "screen_color_sampling",
                (
                    "Screen color picker provides a global/full-screen pick surface, "
                    "uses a crosshair, avoids capturing its own overlay, captures a "
                    "desktop QScreen, and samples the user-selected pixel."
                    if captures_desktop
                    and samples_pixel
                    and interactive_pick
                    and global_pick_surface
                    and crosshair_cursor
                    and avoids_overlay_capture
                    and event_filter_hooked
                    and activation_surface_ready
                    and click_uses_global_position
                    and cancellation_state_valid
                    else (
                        "Missing eyedropper behaviors: "
                        + "; ".join(missing_screen_behaviors)
                        + (
                            " [repair-scope:class]"
                            if requires_class_owned_repair
                            else ""
                        )
                        + ". A screen-wide color picker must use a real eyedropper interaction: "
                        "provide a full-screen/virtual-desktop pick surface (or verified "
                        "global input), use a crosshair, hide/process events before capture "
                        "or capture before showing the overlay, call QScreen.grabWindow(0), "
                        "obtain the clicked global position, and read the corresponding "
                        "image pixel, and install any declared eventFilter on the overlay. "
                        "Show the pick surface from the activation handler, hide that "
                        "surface rather than the dialog before capture, sample the exact "
                        "click global position when committing, and preserve/restore "
                        "the prior value when cancellation requires restoration. "
                        "A small ordinary window or QColorDialog alone does not pick from "
                        "anywhere on screen."
                    )
                ),
            ))
        invalid_api_contracts, unverifiable_api_contracts = _invalid_runtime_api_contracts(
            request_prompt,
            after_tree,
            project_root=project_root,
        )
        requested_runtime_apis = _infer_explicit_runtime_api_requests(request_prompt)
        generated_runtime_apis = _runtime_api_calls_in_tree(after_tree)
        missing_requested_runtime_apis = (
            []
            if _is_test_path(path)
            else sorted(
                requested
                for requested in requested_runtime_apis
                if not any(
                    generated == requested
                    or generated.startswith(requested + ".")
                    or requested.startswith(generated + ".")
                    for generated in package_generated_runtime_apis
                )
            )
        )
        results.append(_quality_result(
            not missing_requested_runtime_apis,
            path,
            "requested_runtime_api_coverage",
            "Explicitly requested runtime API call chains are used."
            if not missing_requested_runtime_apis
            else "Generated code replaced or omitted explicitly requested runtime API "
            "call chains: "
            + ", ".join(missing_requested_runtime_apis),
        ))
        if root_path is not None:
            try:
                current_module = ".".join(
                    Path(path).resolve().relative_to(root_path).with_suffix("").parts
                )
            except (OSError, ValueError):
                current_module = Path(path).stem
        else:
            current_module = Path(path).stem
        invalid_imported_calls, unresolved_imported_calls = _imported_call_api_contracts(
            after_tree,
            current_module=current_module,
            candidate_module_trees=candidate_module_trees,
            project_root=project_root,
        )
        results.append(_quality_result(
            not invalid_imported_calls,
            path,
            "imported_api_members",
            "Imported callable members resolve to real generated or installed API symbols."
            if not invalid_imported_calls
            else "Imported callable members do not exist: "
            + ", ".join(invalid_imported_calls),
        ))
        results.append(_quality_result(
            not unresolved_imported_calls,
            path,
            "imported_api_evidence",
            "Every imported call has resolvable API evidence."
            if not unresolved_imported_calls
            else "Capability gap: imported calls lack project, plugin, catalog, installed, "
            "or official API evidence: "
            + ", ".join(unresolved_imported_calls),
        ))
        if invalid_api_contracts:
            results.append(_quality_result(
                False,
                path,
                "api_contract",
                "Prompt requested explicit runtime APIs that are not present in "
                f"{path}: "
                + ", ".join(invalid_api_contracts),
            ))
        elif unverifiable_api_contracts:
            results.append(_quality_result(
                False,
                path,
                "api_contract",
                "Capability gap in "
                f"{path}: host runtime calls lack indexed, bridge, installed, "
                "or official API evidence: "
                + ", ".join(unverifiable_api_contracts),
            ))
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
            docstring_contract_issues = sorted(
                issue
                for name, node in introduced.items()
                if ast.get_docstring(node)
                for issue in _generated_docstring_contract_issues(name, node)
            )
            results.append(_quality_result(
                not docstring_contract_issues,
                path,
                "public_docstring_contract",
                "New public callable docstrings describe behavior, parameters, and returned values."
                if not docstring_contract_issues
                else "Requested useful docstrings are too vague: "
                + "; ".join(docstring_contract_issues),
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
            placeholder_callables = sorted(
                name
                for name, node in introduced.items()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(
                    isinstance(statement, ast.Pass)
                    or (
                        isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Constant)
                        and statement.value.value is Ellipsis
                    )
                    for statement in node.body
                )
            )
            results.append(_quality_result(
                not placeholder_callables,
                path,
                "placeholder_callables",
                "Generated production callables have substantive bodies."
                if not placeholder_callables
                else "Generated production callables are placeholders: "
                + ", ".join(placeholder_callables),
            ))
            if "docstring" in request_prompt.lower():
                undocumented = sorted(
                    name for name, node in introduced.items()
                    if not ast.get_docstring(node)
                )
                results.append(_quality_result(
                    not undocumented,
                    path,
                    "requested_docstrings",
                    "Requested public callable docstrings are present."
                    if not undocumented
                    else "Requested docstrings are missing: " + ", ".join(undocumented),
                ))
            incomplete_type_hints = _incomplete_generated_type_hints(after_tree)
            results.append(_quality_result(
                not incomplete_type_hints,
                path,
                "complete_type_hints",
                "Every generated callable has complete, valid type hints."
                if not incomplete_type_hints
                else "Requested complete type hints are invalid or missing: "
                + ", ".join(incomplete_type_hints),
            ))
            missing_bool_rejections = _missing_explicit_bool_rejections(
                after_tree,
                request_prompt,
            )
            results.append(_quality_result(
                not missing_bool_rejections,
                path,
                "explicit_bool_rejection",
                "Every explicitly invalid boolean input is rejected."
                if not missing_bool_rejections
                else "Explicitly invalid boolean inputs are not proven rejected in: "
                + ", ".join(missing_bool_rejections),
            ))
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            introduced_callable_ids = {
                id(node)
                for node in introduced.values()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            unresolved = sorted({
                name
                for node_id, names in unresolved_by_callable.items()
                for name in names
                if node_id in introduced_callable_ids
            })
            unresolved = sorted({
                *unresolved,
                *_unresolved_module_scope_names(after_tree),
                *(
                    name
                    for name in _unresolved_generated_names(after_tree)
                    if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
                ),
            })
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if id(node) in introduced_callable_ids and unresolved_by_callable.get(id(node))
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_names",
                "Generated callables do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners or ["<module>"])
                + ": "
                + ", ".join(unresolved),
            ))
            removed_identifiers, rename_pairs = _requested_identifier_contracts(request_prompt)
            remaining_removed = sorted(
                identifier
                for identifier in removed_identifiers
                if _tree_uses_identifier(after_tree, identifier)
            )
            remaining_renamed = sorted(
                source_name
                for source_name, _target_name in rename_pairs
                if _tree_uses_identifier(after_tree, source_name)
            )
            results.append(_quality_result(
                not remaining_removed,
                path,
                "requested_identifier_removal",
                "Explicitly requested dead identifiers were removed."
                if not remaining_removed
                else "Requested removed identifiers remain: " + ", ".join(remaining_removed),
            ))
            results.append(_quality_result(
                not remaining_renamed,
                path,
                "requested_identifier_renames",
                "Explicitly requested identifier renames were completed."
                if not remaining_renamed
                else "Requested renamed identifiers remain: " + ", ".join(remaining_renamed),
            ))
            unrequested_public = sorted(
                name
                for name in introduced
                if (removed_identifiers or rename_pairs)
                and before_defs
                and name.rsplit(".", 1)[-1] not in requested_symbols
                and not re.search(
                    rf"\b{re.escape(name.rsplit('.', 1)[-1])}\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                )
            )
            results.append(_quality_result(
                not unrequested_public,
                path,
                "public_scope",
                "No unrelated public callables were introduced."
                if not unrequested_public
                else "Unrequested public callables were introduced: " + ", ".join(unrequested_public),
            ))
        else:
            placeholder_tests = sorted(
                name
                for name, node in after_defs.items()
                if name.rsplit(".", 1)[-1].startswith("test_")
                and any(isinstance(child, ast.Pass) for child in ast.walk(node))
            )
            results.append(_quality_result(
                not placeholder_tests,
                path,
                "placeholder_tests",
                "Focused tests contain substantive assertions."
                if not placeholder_tests
                else "Generated test methods are placeholders: " + ", ".join(placeholder_tests),
            ))
            proof_issues: list[str] = []
            proof_details: list[str] = []
            prompt_lower = request_prompt.lower()
            imported_modules = {
                node.module
                for node in after_tree.body
                if isinstance(node, ast.ImportFrom) and node.module
            }
            imported_modules.update(
                alias.name
                for node in after_tree.body
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            for name, node in after_defs.items():
                test_name = name.rsplit(".", 1)[-1].lower()
                if not test_name.startswith("test_"):
                    continue
                assertion_names = {
                    child.func.attr
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                }
                has_direct_behavior_assertion = any(
                    isinstance(child, ast.Assert)
                    or (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and (
                            child.func.attr.startswith("assert")
                            or child.func.attr == "raises"
                        )
                    )
                    for child in ast.walk(node)
                )
                if not has_direct_behavior_assertion:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: executes behavior without a direct assertion or "
                        "expected-exception assertion in the test method"
                    )
                stored_names = {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Store)
                }
                loaded_names = {
                    child.id
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                }
                unused_fixtures = sorted(
                    value
                    for value in stored_names - loaded_names
                    if value not in {"self", "cls"}
                    and not value.startswith("_")
                )
                if unused_fixtures:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: fixture variables never consumed: "
                        + ", ".join(unused_fixtures)
                    )
                command_fixtures = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and (
                        any(
                            keyword.arg == "command"
                            and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, str)
                            for keyword in child.keywords
                        )
                        or (
                            isinstance(child.func, ast.Name)
                            and child.func.id.endswith(("JobSpec", "CommandSpec"))
                            and len(child.args) >= 2
                            and isinstance(child.args[1], ast.Constant)
                            and isinstance(child.args[1].value, str)
                        )
                    )
                ]
                has_process_mock = any(
                    isinstance(child, ast.Call)
                    and (
                        (
                            isinstance(child.func, ast.Name)
                            and child.func.id in {"patch", "patch.object", "AsyncMock"}
                        )
                        or (
                            isinstance(child.func, ast.Attribute)
                            and (
                                child.func.attr == "patch"
                                or (
                                    child.func.attr == "object"
                                    and isinstance(child.func.value, ast.Name)
                                    and child.func.value.id == "patch"
                                )
                            )
                        )
                    )
                    for child in ast.walk(node)
                ) or any(
                    isinstance(child, ast.With)
                    and "patch(" in ast.unparse(child)
                    for child in ast.walk(node)
                )
                if command_fixtures and not has_process_mock:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: external command fixtures require a mocked or "
                        "injected process boundary"
                    )
                patch_targets = [
                    str(child.args[0].value)
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and child.args
                    and isinstance(child.args[0], ast.Constant)
                    and isinstance(child.args[0].value, str)
                    and (
                        (
                            isinstance(child.func, ast.Name)
                            and child.func.id == "patch"
                        )
                        or (
                            isinstance(child.func, ast.Attribute)
                            and child.func.attr == "patch"
                        )
                    )
                ]
                invalid_patch_targets = [
                    target
                    for target in patch_targets
                    if not patch_target_exists(target)
                ]
                if invalid_patch_targets:
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: patch targets do not resolve to real generated or "
                        "installed API symbols: "
                        + ", ".join(invalid_patch_targets)
                    )
                query_terms = ("report", "find", "return", "list", "order")
                prompt_requires_error = bool(re.search(
                    r"\b(?:raise|raises|reject|error|exception)\b"
                    r"|\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b",
                    request_prompt,
                    flags=re.IGNORECASE,
                ))
                if (
                    any(term in test_name for term in query_terms)
                    and "assertRaises" in assertion_names
                    and not prompt_requires_error
                ):
                    proof_issues.append(name)
                    proof_details.append(
                        f"{name}: query/report behavior is asserted only as an "
                        "exception even though the request does not require one"
                    )
                if (
                    "add with summary" in prompt_lower
                    and "summary" in test_name
                    and not assertion_names.intersection({"assertEqual", "assertDictEqual"})
                ):
                    proof_issues.append(name)
                if (
                    "dynamic default path" in prompt_lower
                    and "dynamic" in test_name
                    and "path" in test_name
                    and not any(
                        isinstance(child, ast.Attribute) and child.attr == "expanduser"
                        for child in ast.walk(node)
                    )
                ):
                    proof_issues.append(name)
            proof_issues = sorted(set(proof_issues))
            results.append(_quality_result(
                not proof_issues,
                path,
                "behavioral_test_proof",
                "Focused tests prove the named requested behavior."
                if not proof_issues
                else "Generated test methods need stronger behavioral proof: "
                + ", ".join(proof_issues)
                + (
                    "; " + " | ".join(proof_details)
                    if proof_details
                    else ""
                ),
            ))
            unresolved = _unresolved_generated_names(after_tree)
            unresolved = {
                name
                for name in unresolved
                if name.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
            }
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if {
                    value
                    for value in unresolved_by_callable.get(id(node), set())
                    if value.split(".", 1)[0] not in _HOST_RUNTIME_MODULES
                }
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_test_names",
                "Generated tests do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners or ["<module>"])
                + ": "
                + ", ".join(unresolved),
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
            disposable_harness_required = bool(re.search(
                r"\bvalidation\s+artifacts?\s+(?:must\s+be\s+)?temporary\b"
                r"|\b(?:do\s+not|don't|without|no)\s+"
                r"(?:(?:create|add|generate|write|include|produce|use)\s+)?"
                r"(?:any\s+|new\s+|project\s+)*"
                r"(?:test\s+files?|tests?)\b",
                request_prompt,
                flags=re.IGNORECASE,
            )) or behavioral_proof_deferred
            standalone_owner = (
                standalone_entrypoint_symbols[0]
                if standalone_entrypoint_symbols
                else ""
            )
            behavior_failure = (
                f"[scope:module][owner:{standalone_owner}] The explicitly requested "
                f"standalone behavior-proof contract is incomplete: require a "
                f"module-level {standalone_owner}() with assertions and a __main__ "
                "block that calls it."
                if explicit_single_file_scope and standalone_owner
                else "[scope:package] Behavior-changing work requires focused "
                "automated behavioral proof before preview approval."
            )
            results.append({
                "ok": changed_test or disposable_harness_required,
                "path": "",
                "check": "behavior_tests",
                "command": "focused behavior test required",
                "message": (
                    "The candidate includes focused automated test changes for the requested behavior."
                    if changed_test
                    else (
                        "Focused behavioral proof is deferred to the required "
                        "disposable validation harness and may not be returned as "
                        "a project artifact."
                    )
                    if disposable_harness_required
                    else behavior_failure
                ),
            })
        static_failures = [
            result
            for result in results
            if not result.get("ok")
        ]
        is_final_candidate = (
            str(path.resolve()) == final_candidate_path
        )
        if changed_test and is_final_candidate and not static_failures:
            disposable_started = time.perf_counter()
            disposable_results = _validate_candidate_changes_in_disposable_workspace(
                changes,
                project_root=project_root,
                request_prompt=request_prompt,
                allowed_external_paths=allowed_external_paths,
            )
            disposable_elapsed_ms += (
                time.perf_counter() - disposable_started
            ) * 1000.0
            results.extend(disposable_results)
    total_elapsed_ms = (time.perf_counter() - validation_started) * 1000.0
    results.append({
        "ok": True,
        "path": "",
        "check": "validation_timing",
        "command": "candidate:validation_timing",
        "message": (
            f"Validation timing: static={max(0.0, total_elapsed_ms - disposable_elapsed_ms):.0f}ms, "
            f"disposable={disposable_elapsed_ms:.0f}ms, total={total_elapsed_ms:.0f}ms."
        ),
    })
    return results


def _sanitize_python_candidate_text(source: str) -> str:
    """Normalize generated code snippets before parsing/patch application."""

    text = str(source or "")
    text = text.strip()
    if not text:
        return text

    # Strip markdown fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:xml|python|py)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    # Strip model metadata headers.
    text = re.sub(r"(?im)^#\s*file:\s*.*\r?\n", "", text)

    # Remove accidental XML/marker wrappers.
    text = re.sub(r"(?is)^\s*<modify_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)^\s*<create_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?s)\n\s*</(?:modify_file|create_file)>\s*$", "", text)
    # In cases where the model returns wrapper tags with no matching ORIGINAL block,
    # keep the innermost replacement body.
    text = re.sub(r"(?is)^.*?<modify_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)^.*?<create_file\b[^>]*>\s*", "", text)
    text = re.sub(r"(?is)\n\s*</(?:modify_file|create_file)>\s*$", "", text)
    text = re.sub(r"\r", "", text)
    replacement_match = re.search(r"<<<<\s*ORIGINAL.*?\n====\n(.*?)\n>>>>", text, flags=re.IGNORECASE | re.DOTALL)
    if replacement_match:
        text = replacement_match.group(1)
    replacement_only_match = re.search(r"<<<<\s*ORIGINAL(?:\n.*)?\n====\n(.*)", text, flags=re.IGNORECASE | re.DOTALL)
    if replacement_only_match:
        text = replacement_only_match.group(1)
    text = re.sub(r"(?is)<<<<\s*ORIGINAL\b.*?(?:\n|$)", "", text)
    text = re.sub(r"(?is)\n>>>>\s*$", "", text)

    return text.strip()


def _unresolved_generated_names(tree: ast.AST) -> list[str]:
    """Return obvious undefined globals without importing generated modules."""

    return sorted({
        name
        for names in _unresolved_generated_names_by_callable(tree).values()
        for name in names
    })


def _generated_docstring_contract_issues(
    qualified_name: str,
    node: ast.AST,
) -> list[str]:
    """Return signature-derived documentation gaps for one generated callable."""

    issues: list[str] = []
    if isinstance(node, ast.ClassDef):
        docstring = str(ast.get_docstring(node) or "")
        for statement in node.body:
            if not (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            ):
                continue
            field = statement.target.id
            if not re.search(
                rf":param\s+(?:[^:\s]+\s+)?{re.escape(field)}\s*:",
                docstring,
            ):
                issues.append(f"{qualified_name} is missing :param {field}:")
        return issues
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return issues

    arguments = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    parameter_names = [
        argument.arg
        for argument in arguments
        if argument.arg not in {"self", "cls"}
    ]
    if node.args.vararg is not None:
        parameter_names.append(node.args.vararg.arg)
    if node.args.kwarg is not None:
        parameter_names.append(node.args.kwarg.arg)

    docstring = str(ast.get_docstring(node) or "")
    if re.search(
        r"\b(?:supplied to this operation|result produced by|"
        r"request value consumed by(?: the documented operation)?|"
        r"containing the validated inputs for this operation|"
        r"produced after the operation completes successfully|"
        r"the calculated [a-z_ ]+ value)\b",
        docstring,
        flags=re.IGNORECASE,
    ):
        issues.append(
            f"{qualified_name} uses generic parameter or return descriptions"
        )
    for parameter_name in parameter_names:
        if not re.search(
            rf":param\s+(?:[^:\s]+\s+)?{re.escape(parameter_name)}\s*:",
            docstring,
        ):
            issues.append(
                f"{qualified_name} is missing :param {parameter_name}:"
            )

    class ReturnVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.returns_value = False

        def visit_Return(self, return_node: ast.Return) -> None:
            if (
                return_node.value is not None
                and not (
                    isinstance(return_node.value, ast.Constant)
                    and return_node.value.value is None
                )
            ):
                self.returns_value = True

        def visit_Yield(self, _yield_node: ast.Yield) -> None:
            self.returns_value = True

        def visit_YieldFrom(self, _yield_node: ast.YieldFrom) -> None:
            self.returns_value = True

        def visit_FunctionDef(self, _nested: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(
            self,
            _nested: ast.AsyncFunctionDef,
        ) -> None:
            return

        def visit_Lambda(self, _nested: ast.Lambda) -> None:
            return

    return_visitor = ReturnVisitor()
    for statement in node.body:
        return_visitor.visit(statement)
    if (
        return_visitor.returns_value
        and not re.search(r":returns?\s*:", docstring)
    ):
        issues.append(f"{qualified_name} is missing :return:")
    return issues


def _generated_docstring_is_useful(
    qualified_name: str,
    node: ast.AST,
) -> bool:
    """Return whether a generated callable docstring explains more than its name."""

    docstring = str(ast.get_docstring(node) or "").strip()
    summary = re.split(
        r"(?m)^\s*:(?:param|return|returns|raise|raises|type)\b",
        docstring,
        maxsplit=1,
    )[0].strip()
    callable_name = qualified_name.rsplit(".", 1)[-1]
    if (
        re.search(r"(?:[\\/]|\.py\b)", summary, flags=re.IGNORECASE)
        or re.search(
            r"\b(?:requested (?:behavior|change|feature|implementation)|"
            r"provide [a-z0-9_ ]+ behavior|"
            r"apply [a-z0-9_ ]+ and update only its documented state|"
            r"compute and return the [a-z0-9_ ]+ result|"
            r"store validated [a-z0-9_ ]+ state and expose|"
            r"unrelated state|surrounding state|"
            r"observable behavior|validation invariants?|state contract|"
            r"behavioral contracts?|preserving validated inputs, state transitions, "
            r"and failure behavior|after validating construction inputs)\b",
            summary,
            flags=re.IGNORECASE,
        )
        or re.match(
            rf"^\s*{re.escape(callable_name)}\s+must\b",
            summary,
            flags=re.IGNORECASE,
        )
    ):
        return False
    words = re.findall(r"[A-Za-z0-9]+", summary)
    if len(words) < 4:
        return False
    name_words = {
        word.casefold()
        for word in re.findall(
            r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+",
            qualified_name.rsplit(".", 1)[-1],
        )
    }
    meaningful_words = {
        word.casefold()
        for word in words
        if word.casefold() not in name_words
    }
    return len(meaningful_words) >= 3


def _incomplete_generated_type_hints(tree: ast.AST) -> list[str]:
    """Return generated callables with missing or invalid annotation surfaces."""

    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def qualified_name(function: ast.AST) -> str:
        parent = parent_by_node.get(id(function))
        if isinstance(parent, ast.ClassDef):
            return f"{parent.name}.{function.name}"
        return str(function.name)

    def invalid_annotation(
        annotation: ast.AST | None,
        *,
        reject_any: bool = False,
    ) -> bool:
        if annotation is None:
            return True
        if reject_any and any(
            isinstance(child, ast.Name) and child.id == "Any"
            for child in ast.walk(annotation)
        ):
            return True
        if any(
            isinstance(child, ast.Name) and child.id == "callable"
            for child in ast.walk(annotation)
        ):
            return True
        if isinstance(annotation, ast.Tuple):
            return True
        return any(
            isinstance(child, ast.Subscript)
            and isinstance(child.slice, ast.Tuple)
            and any(
                isinstance(element, ast.Tuple)
                for element in child.slice.elts
            )
            for child in ast.walk(annotation)
        )

    failures: list[str] = []
    for function in (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        arguments = [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ]
        if function.args.vararg:
            arguments.append(function.args.vararg)
        if function.args.kwarg:
            arguments.append(function.args.kwarg)
        parent = parent_by_node.get(id(function))
        public_surface = (
            not function.name.startswith("_")
            or (
                function.name == "__init__"
                and isinstance(parent, ast.ClassDef)
                and not parent.name.startswith("_")
            )
        )
        missing_parameters = [
            argument.arg
            for argument in arguments
            if argument.arg not in {"self", "cls"}
            and invalid_annotation(
                argument.annotation,
                reject_any=public_surface
                and argument is not function.args.vararg
                and argument is not function.args.kwarg,
            )
        ]
        reasons: list[str] = []
        if missing_parameters:
            reasons.append("parameters " + "/".join(missing_parameters))
        if invalid_annotation(
            function.returns,
            reject_any=public_surface,
        ):
            reasons.append("return")
        invalid_local_annotations = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.AnnAssign)
            and invalid_annotation(node.annotation)
        ]
        if invalid_local_annotations:
            reasons.append("local annotations")
        untyped_empty_collection_attributes = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.List, ast.Dict, ast.Set))
            and not getattr(node.value, "elts", None)
            and not getattr(node.value, "keys", None)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                for target in node.targets
            )
        ]
        if untyped_empty_collection_attributes:
            reasons.append("empty collection attributes")
        if reasons:
            failures.append(
                f"{qualified_name(function)} ({'; '.join(reasons)})"
            )
    return sorted(failures)


def _missing_explicit_bool_rejections(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Return requested callables that do not explicitly exclude bool values."""

    relevant_sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", request_prompt)
        if re.search(r"\bbool(?:ean)?\b", sentence, flags=re.IGNORECASE)
        and re.search(
            r"\b(?:reject|invalid|not\s+accept|raise)\w*\b",
            sentence,
            flags=re.IGNORECASE,
        )
    ]
    if not relevant_sentences:
        return []
    callable_map = _callable_definition_map(tree)
    requested_owners: set[str] = set()
    for sentence in relevant_sentences:
        if re.search(r"\bconstructor\b", sentence, flags=re.IGNORECASE):
            requested_owners.update(
                name for name in callable_map if name.endswith(".__init__")
            )
        before_requirement = re.split(
            r"\b(?:must|should|rejects?|raises?)\b",
            sentence,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        for qualified_name in callable_map:
            leaf_name = qualified_name.rsplit(".", 1)[-1]
            if leaf_name.startswith("__") and leaf_name != "__init__":
                continue
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(leaf_name)}"
                rf"(?:\s*\(|(?![A-Za-z0-9_]))",
                before_requirement,
                flags=re.IGNORECASE,
            ):
                requested_owners.add(qualified_name)

    missing: list[str] = []
    for qualified_name in sorted(requested_owners):
        function = callable_map[qualified_name]
        has_bool_reference = any(
            isinstance(node, ast.Name) and node.id == "bool"
            for node in ast.walk(function)
        )
        has_exact_type_check = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "type"
            for node in ast.walk(function)
        )
        if not has_bool_reference and not has_exact_type_check:
            missing.append(qualified_name)
    return missing


def _verified_installed_qt_symbol(name: str) -> bool:
    """Return whether an unresolved name is owned by an installed Qt module."""

    if not str(name).startswith("Q") and name != "Qt":
        return False
    for binding in ("PySide6", "PyQt6", "PyQt5", "PySide2"):
        try:
            if importlib.util.find_spec(binding) is None:
                continue
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
        for suffix in ("QtCore", "QtGui", "QtWidgets", "QtTest"):
            try:
                module = importlib.import_module(f"{binding}.{suffix}")
            except (ImportError, ModuleNotFoundError):
                continue
            if hasattr(module, name):
                return True
    return False


def _unresolved_generated_names_by_callable(tree: ast.AST) -> dict[int, list[str]]:
    """Return unresolved names for each callable independently."""

    module_names = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module_names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            module_names.update(
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            )

    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    unresolved_by_callable: dict[int, list[str]] = {}
    for function in [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not isinstance(
            parent_by_node.get(id(node)),
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
        )
    ]:
        arguments = (
            list(function.args.posonlyargs)
            + list(function.args.args)
            + list(function.args.kwonlyargs)
            + ([function.args.vararg] if function.args.vararg else [])
            + ([function.args.kwarg] if function.args.kwarg else [])
        )
        local_names = {argument.arg for argument in arguments}
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local_names.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                local_names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local_names.add(node.name)
            elif isinstance(node, ast.Lambda):
                local_names.update(
                    argument.arg
                    for argument in (
                        list(node.args.posonlyargs)
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                        + ([node.args.vararg] if node.args.vararg else [])
                        + ([node.args.kwarg] if node.args.kwarg else [])
                    )
                )
            elif (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node is not function
            ):
                local_names.add(node.name)
                local_names.update(
                    argument.arg
                    for argument in (
                        list(node.args.posonlyargs)
                        + list(node.args.args)
                        + list(node.args.kwonlyargs)
                        + ([node.args.vararg] if node.args.vararg else [])
                        + ([node.args.kwarg] if node.args.kwarg else [])
                    )
                )
            elif isinstance(node, ast.ClassDef):
                local_names.add(node.name)
        unresolved_by_callable[id(function)] = sorted({
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in local_names
            and node.id not in module_names
        })
    return unresolved_by_callable


def _requested_identifier_contracts(request_prompt: str) -> tuple[set[str], list[tuple[str, str]]]:
    """Extract explicit rename and removal contracts from a natural-language edit request."""

    prompt = str(request_prompt or "")
    removed: set[str] = set()
    for group in re.findall(
        r"(?:^|[.!?]\s+|\b(?:please|also|then)\s+|\band\s+)"
        r"remove\s+(?:the\s+)?"
        r"([A-Za-z_]\w*(?:\s*(?:,|and)\s*[A-Za-z_]\w*)*)",
        prompt,
        flags=re.IGNORECASE,
    ):
        removed.update(re.findall(r"[A-Za-z_]\w*", group))

    renames: list[tuple[str, str]] = []
    for source_group, target_group in re.findall(
        r"\brename\s+([A-Za-z_]\w*(?:/[A-Za-z_]\w*)*)\s+to\s+"
        r"([A-Za-z_]\w*(?:/[A-Za-z_]\w*)*)",
        prompt,
        flags=re.IGNORECASE,
    ):
        sources = source_group.split("/")
        targets = target_group.split("/")
        if len(sources) == len(targets):
            renames.extend(zip(sources, targets))
    return removed, renames


def _tree_uses_identifier(tree: ast.AST, identifier: str) -> bool:
    """Return whether executable Python still defines or references an identifier."""

    return any(
        (isinstance(node, ast.Name) and node.id == identifier)
        or (isinstance(node, ast.arg) and node.arg == identifier)
        or (isinstance(node, ast.Attribute) and node.attr == identifier)
        for node in ast.walk(tree)
    )


def _validate_candidate_changes_in_disposable_workspace(
    changes: list[dict[str, Any]],
    *,
    project_root: str | None,
    request_prompt: str = "",
    allowed_external_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Run the complete generated patch and focused tests outside the real project."""

    if not project_root:
        return [{
            "ok": False,
            "path": "",
            "check": "disposable_workspace",
            "command": "candidate:disposable_workspace",
            "message": "A project root is required for disposable generated-patch validation.",
        }]

    root = Path(project_root).resolve()
    allowed_external = {
        str(Path(path).resolve()).casefold()
        for path in (allowed_external_paths or set())
    }
    patch_files: list[dict[str, str]] = []
    copy_paths: list[str] = []
    python_paths: list[str] = []
    test_paths: list[str] = []
    qt_smoke_targets: list[tuple[str, str]] = []
    verification_targets: list[tuple[str, str]] = []
    requested_verification_symbols = set(re.findall(
        r"\b(?:add|define|implement|include|provide|expose)\s+"
        r"(?:an?\s+|the\s+)?"
        r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
        r"[^.!?\n]{0,180}\b(?:asserts?|prov(?:e[sd]?|ing)|verif(?:y|ies)|"
        r"validates?|self[- ]test|fake\s+"
        r"(?:clock|client|host|service))\b",
        request_prompt,
        flags=re.IGNORECASE,
    ))
    unavailable_host_roots: set[str] = set()
    dependency_source_roots = list(dict.fromkeys(
        Path(value).resolve()
        for value in (
            root,
            Path(__file__).resolve().parents[2],
            Path(str(os.environ.get("TOOLSROOT") or "")).resolve()
            if str(os.environ.get("TOOLSROOT") or "").strip()
            else None,
        )
        if value is not None
    ))
    inspected_dependency_modules: set[str] = set()

    def inspect_dependency_host_imports(module_name: str) -> None:
        """Collect unavailable host roots from one exact local dependency module."""

        normalized_module = str(module_name or "").strip(".")
        if (
            not normalized_module
            or normalized_module in inspected_dependency_modules
        ):
            return
        inspected_dependency_modules.add(normalized_module)
        relative_module = Path(*normalized_module.split("."))
        dependency_source = next(
            (
                candidate
                for source_root in dependency_source_roots
                for candidate in (
                    source_root / relative_module.with_suffix(".py"),
                    source_root / relative_module / "__init__.py",
                )
                if candidate.is_file()
            ),
            None,
        )
        if dependency_source is None:
            return
        try:
            dependency_tree = ast.parse(
                dependency_source.read_text(encoding="utf-8"),
                filename=str(dependency_source),
            )
        except (OSError, UnicodeError, SyntaxError):
            return
        imported_modules = [
            alias.name
            for node in dependency_tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imported_modules.extend(
            str(node.module or "")
            for node in dependency_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
        )
        for imported_module in imported_modules:
            imported_root = imported_module.split(".", 1)[0]
            if imported_root in _HOST_RUNTIME_MODULES:
                try:
                    host_available = (
                        importlib.util.find_spec(imported_root) is not None
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    host_available = False
                if not host_available:
                    unavailable_host_roots.add(imported_root)

    for item in changes:
        path = Path(str(item.get("path") or "")).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            if str(path).casefold() not in allowed_external:
                return [{
                    "ok": False,
                    "path": str(path),
                    "check": "disposable_workspace",
                    "command": "candidate:disposable_workspace",
                    "message": (
                        "Generated patch path is outside the disposable project "
                        f"root: {path}"
                    ),
                }]
            relative = Path("__tech_connector_validation__") / path.name
        relative_text = relative.as_posix()
        patch_files.append({"path": relative_text, "content": str(item.get("after") or "")})
        if path.suffix.lower() == ".py":
            try:
                candidate_tree = ast.parse(
                    str(item.get("after") or ""),
                    filename=str(path),
                )
            except SyntaxError:
                candidate_tree = None
            if candidate_tree is not None:
                verification_targets.extend(
                    (relative_text, node.name)
                    for node in candidate_tree.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name in requested_verification_symbols
                    and any(
                        isinstance(child, ast.Assert)
                        for child in ast.walk(node)
                    )
                )
                qt_imported = any(
                    (
                        isinstance(node, ast.Import)
                        and any(
                            alias.name.startswith(("PySide", "PyQt"))
                            for alias in node.names
                        )
                    )
                    or (
                        isinstance(node, ast.ImportFrom)
                        and str(node.module or "").startswith(("PySide", "PyQt"))
                    )
                    for node in candidate_tree.body
                )
                if qt_imported:
                    for class_node in candidate_tree.body:
                        if not isinstance(class_node, ast.ClassDef):
                            continue
                        base_names = {
                            ast.unparse(base).rsplit(".", 1)[-1]
                            for base in class_node.bases
                        }
                        if base_names & {
                            "QDialog",
                            "QMainWindow",
                            "QWidget",
                        }:
                            qt_smoke_targets.append(
                                (relative_text, class_node.name)
                            )
                            break
                imported_roots = {
                    alias.name.split(".", 1)[0]
                    for node in candidate_tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported_roots.update(
                    str(node.module or "").split(".", 1)[0]
                    for node in candidate_tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                )
                imported_modules = {
                    alias.name
                    for node in candidate_tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                imported_modules.update(
                    str(node.module or "")
                    for node in candidate_tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                )
                for imported_module in sorted(imported_modules):
                    inspect_dependency_host_imports(imported_module)
                for imported_root in sorted(imported_roots):
                    dependency_path = root / imported_root
                    dependency_file = root / f"{imported_root}.py"
                    if (
                        dependency_path.exists() or dependency_file.exists()
                    ) and imported_root not in copy_paths:
                        copy_paths.append(imported_root)
                    if imported_root in _HOST_RUNTIME_MODULES:
                        try:
                            host_available = (
                                importlib.util.find_spec(imported_root) is not None
                            )
                        except (ImportError, ModuleNotFoundError, ValueError):
                            host_available = False
                        if not host_available:
                            unavailable_host_roots.add(imported_root)
        if path.suffix.lower() == ".py":
            python_paths.append(relative_text)
            if _is_test_path(path):
                test_paths.append(relative_text)

    for host_root in sorted(unavailable_host_roots):
        if "." in host_root:
            continue
        if host_root == "maya":
            patch_files.extend([
                {
                    "path": "maya/__init__.py",
                    "content": '"""Disposable Maya package stub."""\n',
                },
                {
                    "path": "maya/cmds.py",
                    "content": (
                        '"""Disposable dynamic maya.cmds stub."""\n'
                        "from unittest.mock import MagicMock\n\n"
                        "def __getattr__(name):\n"
                        "    value = MagicMock(name=name)\n"
                        "    globals()[name] = value\n"
                        "    return value\n"
                    ),
                },
            ])
            continue
        patch_files.append({
            "path": f"{host_root}.py",
            "content": (
                '"""Disposable dynamic host API stub for focused tests."""\n'
                "from unittest.mock import MagicMock\n\n"
                "def __getattr__(name):\n"
                "    value = MagicMock(name=name)\n"
                "    globals()[name] = value\n"
                "    return value\n"
            ),
        })

    commands: list[list[str]] = []
    if python_paths:
        commands.append(["python", "-m", "py_compile", *python_paths])
    for test_path in test_paths:
        test = Path(test_path)
        commands.append([
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            test.parent.as_posix() or ".",
            "-p",
            test.name,
        ])
    for verification_path, verification_symbol in verification_targets:
        commands.append([
            "python",
            "-c",
            (
                "import importlib.util, sys; "
                "spec=importlib.util.spec_from_file_location("
                "'generated_verification', sys.argv[1]); "
                "module=importlib.util.module_from_spec(spec); "
                "sys.modules[spec.name]=module; "
                "spec.loader.exec_module(module); "
                "getattr(module, sys.argv[2])()"
            ),
            verification_path,
            verification_symbol,
        ])
    explicit_single_file_scope = bool(
        re.search(
            r"\b(?:exactly|only)\s+(?:one|1)\s+"
            r"(?:new\s+)?(?:[A-Za-z0-9_+-]+\s+){0,3}files?\b"
            r"|\bno\s+(?:other|extra|additional)\s+files?\b"
            r"|\bdo\s+not\s+(?:add|create|generate|write)\s+(?:any\s+)?"
            r"(?:other|extra|additional)\s+files?\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    )
    if explicit_single_file_scope and not test_paths and len(python_paths) == 1:
        if qt_smoke_targets:
            smoke_path, smoke_class = qt_smoke_targets[0]
            requested_buttons = list(dict.fromkeys(
                re.findall(
                    r"\b([a-z_][A-Za-z0-9_]*(?:_btn|_button))\b",
                    request_prompt,
                )
            ))
            commands.append([
                "python",
                "-c",
                (
                    "import importlib.util, os, sys; "
                    "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen'); "
                    "from PySide6.QtWidgets import QApplication, QPushButton; "
                    "spec=importlib.util.spec_from_file_location('generated_ui', sys.argv[1]); "
                    "module=importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(module); "
                    "app=QApplication.instance() or QApplication([]); "
                    "widget=getattr(module, sys.argv[2])(); "
                    "assert widget is not None; "
                    "buttons=[getattr(widget, name) for name in sys.argv[3:] "
                    "if hasattr(widget, name)]; "
                    "assert all(isinstance(button, QPushButton) for button in buttons); "
                    "[button.click() for button in buttons]; app.processEvents(); "
                    "widget.close(); app.processEvents()"
                ),
                smoke_path,
                smoke_class,
                *requested_buttons,
            ])
        else:
            commands.append(["python", python_paths[0]])

    from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

    validation = validate_patch_in_temp_workspace(
        source_root=root,
        patch_files=patch_files,
        validation_commands=commands,
        copy_paths=copy_paths,
        additional_python_paths=list(dict.fromkeys(
            value
            for value in (
                str(Path(__file__).resolve().parents[2]),
                str(os.environ.get("TOOLSROOT") or "").strip(),
            )
            if value
        )),
        timeout_seconds=8,
        keep_workspace=False,
    )
    results: list[dict[str, Any]] = []
    for command_result in validation.get("commands") or []:
        command = [str(value) for value in command_result.get("command") or []]
        output = "\n".join(
            part.strip()
            for part in (
                str(command_result.get("stdout") or ""),
                str(command_result.get("stderr") or ""),
            )
            if part.strip()
        )
        is_unittest = len(command) >= 3 and command[1:3] == ["-m", "unittest"]
        match = re.search(r"Ran\s+(\d+)\s+tests?", output) if is_unittest else None
        ran_tests = int(match.group(1)) if match else 0
        ok = command_result.get("exit_code") == 0 and (not is_unittest or ran_tests > 0)
        if ok and is_unittest:
            message = f"Disposable focused behavior tests passed ({ran_tests} test{'s' if ran_tests != 1 else ''})."
        elif ok:
            message = "Disposable generated patch parses and compiles."
        else:
            detail = output[-10000:] or str(
                command_result.get("error")
                or (
                    f"Process exited with code {command_result.get('exit_code')} and no output. "
                    "For Qt tests that construct a QWidget, create or reuse QApplication before "
                    "constructing the widget and use a headless Qt platform."
                    if is_unittest
                    else f"Process exited with code {command_result.get('exit_code')} and no output."
                )
            )
            message = "Disposable generated-patch validation failed: " + detail
        results.append({
            "ok": ok,
            "path": "",
            "check": "disposable_unittest" if is_unittest else "disposable_compile",
            "command": " ".join(command),
            "message": message,
        })
    if not results:
        results.append({
            "ok": False,
            "path": "",
            "check": "disposable_workspace",
            "command": "candidate:disposable_workspace",
            "message": "Disposable generated-patch validation did not execute any commands.",
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


def _callable_definition_map(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return qualified callable names, including private lifecycle methods."""

    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def walk(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
                found[qualified] = node
            elif isinstance(node, ast.ClassDef):
                qualified = f"{prefix}.{node.name}" if prefix else node.name
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


def _resolve_local_module_symbol_fallback(
    module_path: Path,
    module_source: str | None,
    symbol: str,
) -> str | None:
    if not symbol or module_path.suffix != ".py":
        return None

    try:
        parsed = ast.parse(
            module_source
            if module_source is not None
            else module_path.read_text(encoding="utf-8", errors="replace"),
            filename=str(module_path),
        )
    except (OSError, SyntaxError):
        return None

    candidate_bases: list[tuple[str, str]] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name
                binding = alias.asname or alias.name.rsplit(".", 1)[-1]
                candidate_bases.append((base, binding))
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            base = node.module
            for alias in node.names:
                if alias.name == "*":
                    continue
                binding = alias.asname or alias.name
                candidate_bases.append((base, binding))
                candidate_bases.append((f"{base}.{binding}", binding))

    for base_module, binding in candidate_bases:
        try:
            module_spec = importlib.util.find_spec(base_module)
        except (AttributeError, ImportError, ModuleNotFoundError, ValueError):
            continue
        if module_spec is None:
            continue
        try:
            base_imported = importlib.import_module(base_module)
        except Exception:
            continue
        if hasattr(base_imported, symbol):
            return base_module
        attribute = getattr(base_imported, binding, None)
        if attribute is not None and hasattr(attribute, symbol):
            return f"{base_module}.{binding}"
    return None


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
        if imported_name and imported_name != "*":
            try:
                stdlib_module = importlib.import_module(module)
            except (ImportError, ModuleNotFoundError) as exc:
                return False, f"Standard-library import failed: {module}: {exc}"
            public_exports = getattr(stdlib_module, "__all__", None)
            is_public_attribute = (
                hasattr(stdlib_module, imported_name)
                and (
                    public_exports is None
                    or imported_name in public_exports
                )
            )
            if not is_public_attribute:
                try:
                    child_spec = importlib.util.find_spec(
                        f"{module}.{imported_name}"
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    child_spec = None
                if child_spec is None:
                    return False, (
                        f"Standard-library module {module!r} does not expose "
                        f"{imported_name!r}."
                    )
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
            child = local_path.parent / imported_name
            child_file = child.with_suffix(".py")
            child_init = child / "__init__.py"
            source_override = candidate_sources.get(str(local_path.resolve()))
            if not _local_module_exports(local_path, imported_name, source_override=source_override):
                if not (
                    child_file.is_file()
                    or child_init.is_file()
                    or str(child_file.resolve()) in candidate_sources
                    or str(child_init.resolve()) in candidate_sources
                ):
                    fallback_module = _resolve_local_module_symbol_fallback(
                        local_path,
                        source_override,
                        imported_name,
                    )
                    if fallback_module is not None:
                        return True, (
                            f"Project-local import does not expose {imported_name!r}; "
                            f"resolved via {fallback_module}."
                        )
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
    if "TOOLSROOT" in os.environ:
        tools_root = Path(os.environ["TOOLSROOT"]).resolve()
        if tools_root.exists():
            roots.append(tools_root)
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
    stem = path.stem.lower()
    return (
        stem.startswith("test_")
        or stem.endswith(("_test", "_tests"))
        or any(part.lower() in {"test", "tests"} for part in path.parts)
    )


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
