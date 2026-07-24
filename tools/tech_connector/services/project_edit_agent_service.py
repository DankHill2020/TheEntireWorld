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
import importlib.util
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import textwrap
import tokenize
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
        "Do not invent files, APIs, imports, or call sites. Work iteratively: implement what is evidenced, "
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
- Give new public functions/classes clear domain names, type-aware interfaces, and useful docstrings.
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
Use clear parameter and local names. Add useful docstrings to public classes, functions, and methods.
{"Implement substantive unittest methods for every requested behavior; a pass-only test class is forbidden." if is_test else "Implement production behavior fully; do not add placeholders, pass bodies, or speculative APIs."}
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
must be under examples/tech_connector/tests/, and its filename must start with test_. Production files must set
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
            "import",
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
        "import": r"\bimports?\b",
        "observer": r"\b(?:observer|listener|subscriber)s?\b",
        "rollback": r"\brollbacks?\b|\broll\s+back\b",
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
live under examples/tech_connector/tests/test_*.py, and depend on every production file they exercise. Assign every
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
                "path": "examples/tech_connector/tests/test_generated_artifact.py",
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
    sentences = [
        part.strip(" .")
        for part in re.split(r"(?<=[.!?])\s+|;\s+", text)
        if part.strip(" .")
    ]
    requirements: list[str] = []
    for sentence in sentences:
        match = re.search(r"\bmust\s+provide\b\s*(.+)", sentence, flags=re.IGNORECASE)
        if match:
            prefix = sentence[:match.start()].strip(" ,")
            if prefix and prefix.casefold() not in {"it", "this", "the system", "the subsystem"}:
                requirements.append(prefix)
            tail = match.group(1)
            requirements.extend(
                part.strip(" ,")
                for part in re.split(r",\s*(?:and\s+)?", tail)
                if part.strip(" ,")
            )
        else:
            imperative = re.match(
                r"^(Support|Include|Expose|Return|Generate|Detect|Preserve|Reject|Verify|Produce)\s+(.+)$",
                sentence,
                flags=re.IGNORECASE,
            )
            if imperative and "," in imperative.group(2):
                verb = imperative.group(1)
                requirements.extend(
                    f"{verb} {part.strip(' ,')}"
                    for part in re.split(r",\s*", imperative.group(2))
                    if part.strip(" ,")
                )
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
    return [
        {
            "id": f"R{index}",
            "text": requirement,
            "scope": _project_edit_requirement_scope(requirement),
        }
        for index, requirement in enumerate(unique[:60], start=1)
    ]


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
            normalized_paths[original_path] = f"examples/tech_connector/tests/{filename}"
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
                f"{path_text}. Test files must use examples/tech_connector/tests/test_*.py with is_test=true; "
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


def build_project_edit_artifact_file_stages(
    plan: ProjectEditPlan,
    manifest: list[dict[str, Any]],
) -> list[tuple[str, str, ProjectEditPromptStage]]:
    """Build dependency-ordered full-file workers from a validated manifest."""

    stages: list[tuple[str, str, ProjectEditPromptStage]] = []
    for index, item in enumerate(manifest, start=1):
        target_path = str(item["absolute_path"])
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
{"Write substantive unittest coverage with deterministic temporary fixtures, including success, failure, and recovery behavior. Import production APIs from the completed dependency files. Never copy or redeclare a production class, function, protocol, or constant in a test file. Test methods must use unittest.TestCase or unittest.IsolatedAsyncioTestCase as appropriate." if is_test else "Give every public class, function, and method a useful docstring and use explicit typed interfaces."}
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
            },
        )
        stages.append((target_path, "", stage))
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
{source[-10000:]}
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
    )


def apply_project_edit_missing_symbol(
    source: str,
    *,
    path: str,
    symbol: str,
    response: str,
) -> tuple[str, list[str]]:
    """Append one validated missing top-level declaration to generated source."""

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
        method_candidates = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
        ]
        try:
            owner_tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            return source, [f"Missing symbol owner did not parse: {exc}"]
        owner_classes = [
            node for node in owner_tree.body if isinstance(node, ast.ClassDef)
        ]
        if len(method_candidates) != 1 or len(owner_classes) != 1:
            return source, [
                f"Missing symbol repair must return exactly one declaration named {symbol}."
            ]
        owner = owner_classes[0]
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
            for node in owner.body
        ):
            return source, [f"Missing method {owner.name}.{symbol} already exists."]
        owner.body.append(method_candidates[0])
        ast.fix_missing_locations(owner_tree)
        corrected = ast.unparse(owner_tree).rstrip() + "\n"
        compile(owner_tree, path, "exec")
        return corrected, []
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
    corrected = source.rstrip() + "\n\n\n" + declaration_source.rstrip() + "\n"
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
    source = re.sub(r"^```(?:python|py)?\s*", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s*```$", "", source)
    if not source:
        return "", [f"Generated file returned no source: {path}"]
    try:
        tree = ast.parse(source, filename=path)
        source = _remove_redundant_generated_initializers(source, tree)
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        sanitized = _remove_generated_top_level_await(source, path=path)
        if sanitized != source:
            try:
                tree = ast.parse(sanitized, filename=path)
                compile(tree, path, "exec")
                source = sanitized
            except (SyntaxError, ValueError):
                return "", [
                    f"Generated file did not parse and compile ({Path(path).name}): {exc}"
                ]
        else:
            return "", [
                f"Generated file did not parse and compile ({Path(path).name}): {exc}"
            ]
    expected = {
        str(value).split("(", 1)[0].rsplit(".", 1)[-1].strip()
        for value in expected_public_symbols or []
        if str(value).strip()
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
            return "", [f"Generated test file defines no test_* methods: {path}"]
        if all(any(isinstance(item, ast.Pass) for item in ast.walk(test)) for test in tests):
            return "", [f"Generated test file contains only placeholder tests: {path}"]
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
            return "", [
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
    try:
        tree = ast.parse(module_source, filename=path)
    except SyntaxError as exc:
        return {}, [f"Function repair owner does not parse: {exc}"]

    parts = symbol.split(".")
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
    callsite_excerpts: list[str] = []
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
            excerpt = "\n".join(
                ast.get_source_segment(candidate_source, statement) or ast.unparse(statement)
                for statement in selected_statements[:6]
            )
            if excerpt:
                callsite_excerpts.append(
                    f"{Path(path_text).name}:{callable_node.name}\n{excerpt[:1800]}"
                )
            if len(callsite_excerpts) >= 4:
                break
        if len(callsite_excerpts) >= 4:
            break
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

    source = ast.get_source_segment(module_source, node) or str(target.get("source") or "")
    rendered_callable = ast.unparse(node)
    signature = rendered_callable.splitlines()[0] if rendered_callable else ""
    generated_interfaces = [
        summarize_project_edit_generated_interface(path_text, generated_source)
        for path_text, _original, generated_source in generated_files
    ]
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
        "callsite_excerpts": callsite_excerpts,
        "forbidden_names": forbidden_names,
        "requirements": [str(value) for value in requirements or [] if str(value).strip()],
        "objective": str(objective or ""),
        "failure": relevant_failure,
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
    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    forbidden_names = ", ".join(contract.get("forbidden_names") or []) or "(none)"
    symbol = str(contract.get("symbol") or "")
    plan_text = json.dumps(repair_plan or {}, indent=2)
    forbidden_set = {
        str(value) for value in contract.get("forbidden_names") or [] if str(value)
    }
    source_lines = []
    for line in str(contract.get("source") or "").splitlines():
        if any(re.search(rf"\b{re.escape(name)}\b", line) for name in forbidden_set):
            indent = line[: len(line) - len(line.lstrip())]
            source_lines.append(
                f"{indent}# INVALID FAILURE LINE REMOVED BY CONTRACT"
            )
        else:
            source_lines.append(line)
    bounded_source = "\n".join(source_lines)
    return ProjectEditPromptStage(
        key="function_repair",
        label=f"Repairing {symbol}",
        system_prompt=(
            "You are a bounded senior Python function repair worker. Return exactly one complete "
            "replacement function or method. Preserve its exact signature and repair only the supplied "
            "failure. Do not return a class, module, diff, Markdown, JSON, or explanation."
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

Bounded callers and behavioral tests that define the input/output contract:
```python
{callsites}
```
Caller-local fixture names are evidence only. They do not exist inside the repaired callable and must not be copied.

Names proven invalid by the current failure and forbidden in the replacement:
{forbidden_names}

Smallest matching disposable validation failure:
{contract.get("failure") or ""}

Approved repair micro-plan:
```json
{plan_text}
```

Return one complete replacement callable named {contract.get("callable_name") or ""}.
Keep the exact parameter list, defaults, annotations, async form, and decorators.
Use only arguments, local names, builtins, visible imports, and available module symbols.
If a new standard-library helper is needed only here, import it locally inside the callable.
Fix the root cause and preserve behavior outside this callable. Return raw Python only.
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
        },
    )


def build_project_edit_function_repair_plan_stage(
    contract: dict[str, Any],
) -> ProjectEditPromptStage:
    """Build a small reasoning stage that diagnoses one callable before coding."""

    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    generated_interfaces = "\n".join(
        contract.get("generated_interfaces") or []
    ) or "(none)"
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

Validation failure:
{contract.get("failure") or ""}

Proven-invalid names that the implementation may not use:
{forbidden}

Return a minimal repair algorithm using only values actually available through the signature or visible module
interfaces. State exact output postconditions from the assertions. Do not invent paths, globals, fixtures, APIs,
or new parameters. Changing the callable signature is forbidden. If the existing inputs already contain the values
needed to compute an answer, derive it from those inputs instead of reacquiring unavailable external context.
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
    replacement = textwrap.dedent(
        ast.get_source_segment(replacement, definitions[0]) or replacement
    ).strip()
    repaired_tree = ast.parse(replacement, filename=f"<repair:{symbol}>")
    repaired_definition = repaired_tree.body[0]
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
    retained_forbidden = sorted(
        {
            node.id
            for node in ast.walk(repaired_definition)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in set(forbidden_names or ())
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
            return generated_files, [f"Generated repair owner did not parse: {exc}"]
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
        if isinstance(original_definition, ast.AsyncFunctionDef) != isinstance(
            repaired_definition, ast.AsyncFunctionDef
        ):
            return generated_files, [f"Repair changed async form for {symbol}."]
        if ast.dump(original_definition.args, include_attributes=False) != ast.dump(
            repaired_definition.args, include_attributes=False
        ):
            return generated_files, [f"Repair changed the callable signature for {symbol}."]
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
        if original_return != repaired_return:
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
    """Insert concise docstrings for generated public callables when explicitly requested."""

    if not force and "docstring" not in str(request_prompt or "").lower():
        return generated_files, []
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
            edits.append((node.body[0].lineno - 1, f'{indent}"""{description}"""\n'))
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
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Add known standard-library imports required by otherwise complete generated code."""

    symbol_imports = {
        "Mock": "from unittest.mock import Mock",
        "NamedTemporaryFile": "from tempfile import NamedTemporaryFile",
        "TemporaryDirectory": "from tempfile import TemporaryDirectory",
        "json": "import json",
        "os": "import os",
        "tempfile": "import tempfile",
        "unittest": "import unittest",
        "mock": "from unittest import mock",
    }
    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        unresolved = set(_unresolved_generated_names(tree))
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


def remove_project_edit_unused_imports(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove whole generated import statements whose bindings are never loaded."""

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
        unused_imports = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            bindings = {
                alias.asname or (
                    alias.name.split(".", 1)[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                for alias in node.names
                if alias.name != "*"
            }
            if bindings and (
                bindings.isdisjoint(loaded_names)
                or (id(node) not in module_import_ids and bindings <= module_bindings)
            ):
                unused_imports.append(node)
        if not unused_imports:
            continue
        lines = source.splitlines(keepends=True)
        for node in sorted(unused_imports, key=lambda item: item.lineno, reverse=True):
            del lines[node.lineno - 1:int(node.end_lineno or node.lineno)]
            fixes.append(f"{Path(path_text).name}: removed unused import")
        final_source = "".join(lines)
        compile(ast.parse(final_source, filename=path_text), path_text, "exec")
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
    tier = (stage.model_tier or "").strip()
    if tier == "local_plan":
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
    elif tier == "local_semantic":
        model = settings.get("semantic_intent_model") or "qwen2.5:1.5b"
    elif tier == "local_semantic_verify":
        model = settings.get("semantic_verifier_model") or "qwen2.5:3b"
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
            replacement = str(change.get("new_content") or "")
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
            placeholder_callables = sorted(
                name
                for name, node in after_defs.items()
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
                    name for name, node in after_defs.items()
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
            unresolved = _unresolved_generated_names(after_tree)
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if unresolved_by_callable.get(id(node))
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_names",
                "Generated callables do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners)
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
            prompt_lower = request_prompt.lower()
            for name, node in after_defs.items():
                test_name = name.rsplit(".", 1)[-1].lower()
                if not test_name.startswith("test_"):
                    continue
                assertion_names = {
                    child.func.attr
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                }
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
                + ", ".join(proof_issues),
            ))
            unresolved = _unresolved_generated_names(after_tree)
            unresolved_by_callable = _unresolved_generated_names_by_callable(after_tree)
            unresolved_owners = sorted(
                name
                for name, node in _callable_definition_map(after_tree).items()
                if unresolved_by_callable.get(id(node))
            )
            results.append(_quality_result(
                not unresolved,
                path,
                "undefined_test_names",
                "Generated tests do not reference undefined Python names."
                if not unresolved
                else "Generated callables reference undefined names in "
                + ", ".join(unresolved_owners)
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
        if changed_test:
            results.extend(
                _validate_candidate_changes_in_disposable_workspace(
                    changes,
                    project_root=project_root,
                )
            )
    return results


def _unresolved_generated_names(tree: ast.AST) -> list[str]:
    """Return obvious undefined globals without importing generated modules."""

    return sorted({
        name
        for names in _unresolved_generated_names_by_callable(tree).values()
        for name in names
    })


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

    unresolved_by_callable: dict[int, list[str]] = {}
    for function in [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
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
        r"\bremove\s+([A-Za-z_]\w*(?:\s*(?:,|and)\s*[A-Za-z_]\w*)*)",
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
    patch_files: list[dict[str, str]] = []
    copy_paths: list[str] = []
    python_paths: list[str] = []
    test_paths: list[str] = []
    for item in changes:
        path = Path(str(item.get("path") or "")).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            return [{
                "ok": False,
                "path": str(path),
                "check": "disposable_workspace",
                "command": "candidate:disposable_workspace",
                "message": f"Generated patch path is outside the disposable project root: {path}",
            }]
        relative_text = relative.as_posix()
        patch_files.append({"path": relative_text, "content": str(item.get("after") or "")})
        top_level = relative.parts[0] if relative.parts else relative_text
        if top_level and top_level not in copy_paths:
            copy_paths.append(top_level)
        if path.suffix.lower() == ".py":
            python_paths.append(relative_text)
            if _is_test_path(path):
                test_paths.append(relative_text)

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

    from tech_connector.services.code_operation_service import validate_patch_in_temp_workspace

    validation = validate_patch_in_temp_workspace(
        source_root=root,
        patch_files=patch_files,
        validation_commands=commands,
        copy_paths=copy_paths,
        timeout_seconds=60,
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
            detail = output[-10000:] or str(command_result.get("error") or "No command output was returned.")
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
