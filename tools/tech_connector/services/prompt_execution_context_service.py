"""Canonical prompt execution context built before route selection.

The context is the single request-scoped source of truth.  Semantic services
populate it once; routing, retrieval, progress, dispatch, and UI code consume
it without reparsing the raw prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import threading
from typing import Any, Iterable
import urllib.request


EVIDENCE_TIERS: tuple[str, ...] = (
    "project_index",
    "ast",
    "cross_references",
    "semantic_model",
    "host_validation",
    "execution",
)

_PLANNING_CACHE: dict[str, dict[str, Any]] = {}
_PLANNING_CACHE_LOCK = threading.Lock()


@dataclass
class UnderstandingValidation:
    valid: bool
    confidence: float
    missing_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    repaired_fields: dict[str, Any] = field(default_factory=dict)
    clarification_required: bool = False
    clarification_question: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "confidence": self.confidence,
            "missing_fields": list(self.missing_fields),
            "ambiguous_fields": list(self.ambiguous_fields),
            "repaired_fields": dict(self.repaired_fields),
            "clarification_required": self.clarification_required,
            "clarification_question": self.clarification_question,
            "reasons": list(self.reasons),
        }


@dataclass
class EvidenceState:
    """Request-scoped evidence and escalation state.

    This object records what has actually been checked.  It does not choose a
    route and it does not manufacture a plan.  Retrieval services append
    evidence and advance one tier only when the current evidence is
    insufficient.
    """

    current_tier: int = 0
    attempted_tiers: list[int] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    sufficient: bool = False
    confidence: float = 0.0
    answer: str = ""
    insufficiency_reasons: list[str] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def tier_name(self) -> str:
        index = max(0, min(int(self.current_tier), len(EVIDENCE_TIERS) - 1))
        return EVIDENCE_TIERS[index]

    def add(
        self,
        evidence: dict[str, Any] | None,
        *,
        tier: int | None = None,
        sufficient: bool | None = None,
        confidence: float | None = None,
        answer: str | None = None,
    ) -> None:
        if tier is not None:
            self.current_tier = max(0, min(int(tier), len(EVIDENCE_TIERS) - 1))
        if self.current_tier not in self.attempted_tiers:
            self.attempted_tiers.append(self.current_tier)
        if evidence:
            row = dict(evidence)
            row.setdefault("tier", self.current_tier)
            row.setdefault("tier_name", self.tier_name)
            self.records.append(row)
        if sufficient is not None:
            self.sufficient = bool(sufficient)
        if confidence is not None:
            self.confidence = max(0.0, min(1.0, float(confidence)))
        if answer is not None:
            self.answer = str(answer)

    def escalate(self, reason: str = "") -> bool:
        """Advance exactly one tier.  Return False at the final tier."""
        if self.sufficient or self.current_tier >= len(EVIDENCE_TIERS) - 1:
            return False
        if reason:
            self.insufficiency_reasons.append(str(reason))
        if self.current_tier not in self.attempted_tiers:
            self.attempted_tiers.append(self.current_tier)
        self.current_tier += 1
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "evidence_state_v1",
            "current_tier": self.current_tier,
            "tier_name": self.tier_name,
            "attempted_tiers": list(self.attempted_tiers),
            "attempted_tier_names": [
                EVIDENCE_TIERS[index]
                for index in self.attempted_tiers
                if 0 <= index < len(EVIDENCE_TIERS)
            ],
            "records": [dict(item) for item in self.records],
            "sufficient": self.sufficient,
            "confidence": self.confidence,
            "answer": self.answer,
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "stop_reason": self.stop_reason,
        }


@dataclass
class PromptExecutionContext:
    prompt: str
    normalized_prompt: str = ""
    host_hint: str = ""
    request_understanding: dict[str, Any] = field(default_factory=dict)
    problem_formulation: dict[str, Any] = field(default_factory=dict)
    context_candidates: list[dict[str, Any]] = field(default_factory=list)
    resolved_references: dict[str, Any] = field(default_factory=dict)
    planning_result: dict[str, Any] = field(default_factory=dict)
    understanding_validation: dict[str, Any] = field(default_factory=dict)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)
    evidence_state: EvidenceState = field(default_factory=EvidenceState)
    execution_decision: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)
    reasoning_pipeline: dict[str, Any] = field(default_factory=dict)
    visible_progress: dict[str, Any] = field(default_factory=dict)

    @property
    def understanding(self) -> dict[str, Any]:
        return self.request_understanding

    @property
    def semantic_contract(self) -> dict[str, Any]:
        return self.semantic_execution_contract

    @property
    def goal_graph(self) -> dict[str, Any]:
        return self.task_graph

    @property
    def primary_goal(self) -> str:
        return str(
            self.task_graph.get("primary_goal")
            or self.semantic_execution_contract.get("goal")
            or self.request_understanding.get("primary_goal")
            or self.normalized_prompt
            or self.prompt
        )

    @property
    def goal_type(self) -> str:
        return str(
            self.task_graph.get("goal_type")
            or self.semantic_execution_contract.get("goal_type")
            or self.request_understanding.get("goal_type")
            or "respond"
        )

    def current_goal(self, completed_goal_ids: Iterable[str] | None = None) -> dict[str, Any]:
        completed = {str(value) for value in (completed_goal_ids or [])}
        goals = list(
            self.task_graph.get("ordered_goals")
            or self.task_graph.get("goals")
            or self.task_graph.get("tasks")
            or []
        )
        for goal in goals:
            goal_id = str(goal.get("goal_id") or goal.get("task_id") or "")
            if not goal_id or goal_id in completed:
                continue
            dependencies = {str(value) for value in (goal.get("depends_on") or [])}
            if dependencies.issubset(completed):
                return dict(goal)
        return {}

    def attach_execution_decision(self, decision: dict[str, Any] | Any | None) -> None:
        self.execution_decision = (
            decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
        )

    def to_dict(self) -> dict[str, Any]:
        evidence = self.evidence_state.to_dict()
        return {
            "framework": "canonical_prompt_execution_context_v2",
            "prompt": self.prompt,
            "normalized_prompt": self.normalized_prompt or self.prompt,
            "host_hint": self.host_hint,
            "request_understanding": dict(self.request_understanding),
            "understanding": dict(self.request_understanding),
            "problem_formulation": dict(self.problem_formulation),
            "context_candidates": [dict(item) for item in self.context_candidates],
            "resolved_references": dict(self.resolved_references),
            "planning_result": dict(self.planning_result),
            "understanding_validation": dict(self.understanding_validation),
            "semantic_execution_contract": dict(self.semantic_execution_contract),
            "semantic_contract": dict(self.semantic_execution_contract),
            "task_graph": dict(self.task_graph),
            "goal_graph": dict(self.task_graph),
            "evidence_state": evidence,
            "execution_tier": evidence["current_tier"],
            "execution_tier_name": evidence["tier_name"],
            "execution_decision": dict(self.execution_decision),
            "runtime_state": dict(self.runtime_state),
            # Compatibility fields.  These are views, not independent owners.
            "primary_goal": self.primary_goal,
            "goal_type": self.goal_type,
            "estimated_steps": int(
                self.task_graph.get("estimated_steps")
                or len(self.task_graph.get("goals") or self.task_graph.get("tasks") or [])
            ),
            "reasoning_pipeline": dict(self.reasoning_pipeline),
            "visible_progress": dict(self.visible_progress),
        }


def _normalize_prompt(prompt: str) -> str:
    try:
        from tech_connector.services.prompt_task_splitter_service import normalize_prompt_text

        return " ".join(normalize_prompt_text(prompt).split())
    except Exception:
        return " ".join(str(prompt or "").split())


def _model_json(system: str, packet: dict[str, Any], *, timeout: int | None = None) -> dict[str, Any]:
    """Run the configured planning model and return one JSON object."""
    try:
        from tech_connector.services.ollama_service import OLLAMA_BASE_URL
        from tech_connector.services.ollama_resource_service import (
            build_ollama_options,
            choose_ollama_generation_budget,
        )

        settings = dict(packet.get("settings") or {})
        budget = choose_ollama_generation_budget(
            prompt=str(packet.get("raw_prompt") or ""),
            evidence_text=json.dumps(packet.get("context_candidates") or [], default=str),
            route=str((packet.get("semantic_hypothesis") or {}).get("primary_route") or ""),
            llm_mode="planning",
            confidence=(packet.get("semantic_hypothesis") or {}).get("confidence"),
            settings=settings,
        )
        model = os.environ.get("AI_STUDIO_PLANNING_MODEL", "qwen3:8b")
        options = build_ollama_options(
            num_ctx=budget.num_ctx,
            num_predict=budget.num_predict,
            settings=settings,
            temperature=0.0,
        )
        options.update({"top_k": 1, "top_p": 0.1, "repeat_penalty": 1.0})
        effective_timeout = int(timeout) if timeout is not None else int(budget.timeout_seconds)
        
        from tech_connector.services.llm_router_service import generate_llm_response
        value = generate_llm_response(
            model=model,
            prompt=json.dumps(packet, default=str),
            system=system,
            response_format="json",
            options=options,
            timeout=effective_timeout
        ).strip()
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _cached_planning_model_json(packet: dict[str, Any]) -> dict[str, Any]:
    key = json.dumps(packet, sort_keys=True, default=str)
    with _PLANNING_CACHE_LOCK:
        has_cached = key in _PLANNING_CACHE
        cached = _PLANNING_CACHE.get(key)
    if has_cached:
        return json.loads(json.dumps(cached))
    plan = _model_json(_PLANNING_SYSTEM, packet)
    snapshot = json.loads(json.dumps(plan or {}, default=str))
    with _PLANNING_CACHE_LOCK:
        if len(_PLANNING_CACHE) >= 128:
            _PLANNING_CACHE.pop(next(iter(_PLANNING_CACHE)))
        _PLANNING_CACHE[key] = snapshot
    return json.loads(json.dumps(snapshot))


def _add_context_candidate(
    candidates: list[dict[str, Any]],
    *,
    kind: str,
    value: Any,
    source: str,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    if value in (None, "", [], {}):
        return
    key = json.dumps([kind, value], sort_keys=True, default=str).casefold()
    if any(item.get("_key") == key for item in candidates):
        return
    candidates.append(
        {
            "candidate_id": f"context_{len(candidates) + 1}",
            "kind": kind,
            "value": value,
            "source": source,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "metadata": dict(metadata or {}),
            "_key": key,
        }
    )


def gather_prompt_context_candidates(
    prompt: str,
    understanding: dict[str, Any],
    facts: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect bounded context guesses after the cheap semantic pass."""
    facts = dict(facts or {})
    candidates: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}
    lower = str(prompt or "").lower()
    workspace = facts.get("conversation_workspace") or {}
    memory = facts.get("operation_memory") or {}
    if not workspace and isinstance(memory, dict):
        workspace = memory.get("conversation_workspace") or {}

    try:
        from tech_connector.services.ai_work_memory_service import relevant_contextual_knowledge

        for learned in relevant_contextual_knowledge(facts.get("settings") or {}, prompt, limit=10):
            _add_context_candidate(
                candidates,
                kind="validated_knowledge",
                value={
                    "subject": learned.get("subject") or "",
                    "relation": learned.get("relation") or "",
                    "value": learned.get("value"),
                },
                source="contextual_knowledge",
                confidence=float(learned.get("confidence") or 0.85),
                metadata={"timestamp": learned.get("timestamp") or ""},
            )
    except Exception:
        pass

    for entity in _safe_target_entities(prompt):
        _add_context_candidate(
            candidates,
            kind=str(entity.get("kind") or "target"),
            value=entity.get("normalized") or entity.get("value"),
            source="explicit_prompt",
            confidence=float(entity.get("confidence") or 0.9),
            metadata=entity,
        )

    clarification = dict(facts.get("clarification_binding") or {})
    clarified_values = dict(clarification.get("values") or {})
    clarified_file = str(clarified_values.get("target_file") or clarified_values.get("file") or "")
    if clarified_file:
        _add_context_candidate(
            candidates,
            kind="file",
            value=clarified_file,
            source="clarification",
            confidence=1.0,
        )

    has_file_reference = bool(
        re.search(r"\b(that|this|those|these|the previous|the last|same)\s+files?\b|\bin that file\b", lower)
    )
    if has_file_reference and workspace:
        try:
            from tech_connector.services.conversation_workspace_service import resolve_reference, workspace_from_dict

            resolution = resolve_reference(workspace, prompt, kind="file")
            current = workspace_from_dict(workspace)
            refs = [
                current.entities[entity_id].ref
                for entity_id in resolution.entity_ids
                if entity_id in current.entities and current.entities[entity_id].ref
            ]
            if refs:
                plural = bool(re.search(r"\b(those|these)\s+files\b", lower))
                resolved["those_files" if plural else "that_file"] = {
                    "value": refs if plural else refs[0],
                    "source": resolution.source,
                    "confidence": resolution.confidence,
                }
                for ref in refs:
                    _add_context_candidate(
                        candidates,
                        kind="file",
                        value=ref,
                        source=resolution.source,
                        confidence=resolution.confidence,
                    )
        except Exception:
            pass

    explicit_target = str(understanding.get("target_file") or clarified_file or "")
    if explicit_target:
        _add_context_candidate(
            candidates,
            kind="file",
            value=explicit_target,
            source="semantic_hypothesis",
            confidence=0.98,
        )

    if has_file_reference and not resolved:
        prior = dict(facts.get("prior_result_metadata") or {})
        memory_values = [
            prior.get("selected_file"),
            prior.get("resolved_target_file"),
        ]
        if isinstance(memory, dict):
            memory_values.extend(
                [memory.get("selected_file"), memory.get("recent_file"), memory.get("active_file")]
            )
        for value in memory_values:
            if str(value or "").strip():
                resolved["that_file"] = {
                    "value": str(value),
                    "source": "prior_result_or_operation_memory",
                    "confidence": 0.9,
                }
                _add_context_candidate(
                    candidates,
                    kind="file",
                    value=str(value),
                    source="prior_result_or_operation_memory",
                    confidence=0.9,
                )
                break

    active_path = str(facts.get("active_path") or "")
    if active_path:
        _add_context_candidate(
            candidates,
            kind="file",
            value=active_path,
            source="active_editor",
            confidence=0.7 if has_file_reference else 0.85,
        )
        if has_file_reference and not resolved:
            resolved["that_file"] = {
                "value": active_path,
                "source": "active_editor_fallback",
                "confidence": 0.7,
            }

    resolved_file = str((resolved.get("that_file") or {}).get("value") or explicit_target or "")
    if resolved_file:
        _collect_file_symbol_candidate(candidates, _resolve_candidate_file(resolved_file, facts))
    elif str(understanding.get("primary_route") or "") == "project_search":
        _collect_project_file_guesses(candidates, prompt, active_path)
    elif (
        str(understanding.get("primary_route") or "") == "dcc_execute"
        and str(understanding.get("target_symbol") or "")
    ):
        _collect_project_file_guesses(
            candidates,
            str(understanding.get("target_symbol") or ""),
            active_path,
        )

    for item in candidates:
        item.pop("_key", None)
    return candidates[:24], resolved


def _safe_target_entities(prompt: str) -> list[dict[str, Any]]:
    try:
        from tech_connector.services.target_entity_service import extract_target_entities

        return [item.to_dict() for item in extract_target_entities(prompt)]
    except Exception:
        return []


def _resolve_candidate_file(value: str, facts: dict[str, Any]) -> str:
    path = Path(str(value or ""))
    if path.is_absolute() and path.exists():
        return str(path)
    for root in facts.get("project_roots") or []:
        candidate = Path(str(root)) / path
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return str(value or "")


def _collect_file_symbol_candidate(candidates: list[dict[str, Any]], file_path: str) -> None:
    try:
        from tech_connector.services.project_search_service import _symbol_rows_for_file

        rows = _symbol_rows_for_file(file_path, kinds=("function", "method", "class"), limit=40)
        symbols = [
            {
                "name": row.get("name") or row.get("qualname") or "",
                "kind": row.get("kind") or "",
                "line": row.get("start_line") or 0,
                "signature": row.get("signature") or "",
                "docstring": str(row.get("docstring") or "")[:240],
            }
            for row in rows[:30]
        ]
        if symbols:
            _add_context_candidate(
                candidates,
                kind="file_symbols",
                value={"file": file_path, "symbols": symbols},
                source="project_index",
                confidence=0.92,
            )
    except Exception:
        pass


def _collect_project_file_guesses(candidates: list[dict[str, Any]], prompt: str, active_path: str) -> None:
    try:
        from tech_connector.services.project_search_service import _function_location_rows, _function_location_terms

        terms = _function_location_terms(prompt, active_path=active_path or None)
        rows = _function_location_rows(
            terms,
            active_path=active_path or None,
            question=prompt,
            limit=8,
        )
        for index, row in enumerate(rows[:8]):
            path = str(row.get("rel_path") or row.get("path") or "")
            _add_context_candidate(
                candidates,
                kind="file_guess",
                value=path,
                source="project_index",
                confidence=max(0.55, 0.9 - index * 0.05),
                metadata={
                    "symbol": row.get("signature") or row.get("name") or "",
                    "score": row.get("match_score") or 0,
                },
            )
    except Exception:
        pass


_PLANNING_SYSTEM = """You are the authoritative planning and intent-validation stage for a coding and DCC assistant.
You receive the raw request, a cheap semantic hypothesis, deterministic contract, and bounded context candidates.
Return ONLY JSON. Resolve references from supplied candidates and never invent files, symbols, hosts, or callable actions.
If required evidence is absent, list a focused context_request so the system can search and ask you again.
The plan must match the user's actual requested deliverable. Distinguish finding existing code, explaining or writing sample code,
editing project code, and executing a live DCC operation. Exact-file scope is a hard constraint.
Use only action_type values in action_catalog for function_calls. Every non-chat request must include at least one usable function_call.
Schema:
{
  "interpreted_request":"...",
  "intent_category":"project_search|code_generation_guidance|project_code_edit|dcc_query|dcc_execution|workflow_pipeline|general_chat",
  "primary_route":"project_search|target_discovery|dcc_query|dcc_execute|pipeline_graph|action_graph|chat",
  "goal_type":"locate|verify|learn|explain|generate|modify|execute|validate|compare|plan|debug|respond",
  "deliverable":"file|files|function|functions|code|answer|action_result|plan",
  "behavior":"...",
  "scope":"exact_file|selected_files|project|conversation|host",
  "target":"...",
  "resolved_references":{},
  "mutation_requested":false,
  "execution_requested":false,
  "steps":[{"step_id":"...","action":"resolve|search|inspect|analyze|generate|modify_code|execute|validate|report","objective":"...","depends_on":[],"success_condition":"..."}],
  "function_calls":[{"action_type":"...","arguments":{},"reason":"..."}],
  "answer_contract":{"must_answer":[],"must_not_include":[],"success_condition":"..."},
  "unknowns":[],
  "context_requests":[{"kind":"project_file_candidates|file_symbols|file_source|project_search","query":"...","target":"...","reason":"..."}],
  "clarification_question":"",
  "confidence":0.0,
  "reasons":[]
}"""


def _action_catalog() -> list[dict[str, Any]]:
    try:
        from tech_connector.services.action_execution_engine import default_action_handler_registry

        return [
            {
                "action_type": item.get("action_type"),
                "mutability": item.get("mutability"),
                "approval_policy": item.get("approval_policy"),
            }
            for item in default_action_handler_registry().ownership_map()
        ]
    except Exception:
        return []


def plan_prompt_with_context(
    prompt: str,
    understanding: dict[str, Any],
    semantic_contract: dict[str, Any],
    formulation: dict[str, Any],
    candidates: list[dict[str, Any]],
    resolved_references: dict[str, Any],
    facts: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Ask the planning model, search its unknowns, and replan up to two times."""
    facts = dict(facts or {})
    action_catalog = _action_catalog()
    compact_understanding = {
        key: understanding.get(key)
        for key in (
            "normalized_goal", "primary_intent", "primary_route", "primary_action",
            "requested_artifact", "behavior_description", "target_file",
            "target_container_type", "target_container_query", "requested_member_type",
            "member_behavior", "reference_scope", "goal_type", "mutation_requested",
            "live_host_execution_requested", "read_only_requested", "confidence", "reasons",
        )
    }
    compact_contract = {
        key: semantic_contract.get(key)
        for key in (
            "goal", "goal_type", "deliverable_type", "subject_type", "subject_text",
            "relationship", "container_type", "container_query", "action", "behavior",
            "read_only", "mutation_requested", "execution_requested", "constraints",
            "unresolved_fields", "expected_outputs", "evidence_required", "success_definition",
            "confidence",
        )
    }
    compact_formulation = {
        key: formulation.get(key)
        for key in (
            "interpreted_problem", "desired_outcome", "deliverables", "subject", "action_mode",
            "scope", "relationships", "knowns", "unknowns", "blocking_unknowns", "constraints",
            "evidence_required", "success_conditions", "confidence", "requires_clarification",
        )
    }
    packet = {
        "raw_prompt": prompt,
        "settings": dict(facts.get("settings") or {}),
        "semantic_hypothesis": compact_understanding,
        "deterministic_contract": compact_contract,
        "problem_formulation": compact_formulation,
        "context_candidates": candidates,
        "resolved_references": resolved_references,
        "action_catalog": action_catalog,
        "instruction": "Build the smallest executable plan that can satisfy and later validate the answer.",
    }
    plan = _cached_planning_model_json(packet)
    used_planning_model = bool(plan)
    rounds = 0
    while plan and list(plan.get("context_requests") or []) and rounds < 2:
        before = len(candidates)
        candidates = expand_prompt_context_candidates(
            candidates,
            list(plan.get("context_requests") or []),
            prompt=prompt,
            facts=facts,
        )
        rounds += 1
        if len(candidates) == before:
            break
        packet.update(
            {
                "context_candidates": candidates,
                "previous_plan": plan,
                "search_round": rounds,
                "instruction": "Replan using the new evidence. Keep only unknowns that still cannot be resolved.",
            }
        )
        plan = _cached_planning_model_json(packet)

    fallback_plan = _fallback_planning_result(
        prompt,
        understanding,
        semantic_contract,
        resolved_references,
    )
    if plan:
        plan = _complete_planning_result(plan, fallback_plan, understanding)
    else:
        plan = fallback_plan
    plan = _validate_planning_result(
        plan,
        action_catalog,
        resolved_references,
        context_candidates=candidates,
    )
    plan["search_rounds"] = rounds
    plan["model_role"] = "plan" if used_planning_model else "deterministic_fallback"
    return plan, candidates


def _complete_planning_result(
    plan: dict[str, Any],
    fallback: dict[str, Any],
    understanding: dict[str, Any],
) -> dict[str, Any]:
    """Complete partial planner JSON and preserve explicit semantic facts."""
    completed = dict(fallback)
    for key, value in dict(plan or {}).items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        completed[key] = value

    confidence = float(understanding.get("confidence") or 0.0)
    intent = str(understanding.get("primary_intent") or "")
    if confidence >= 0.9 and intent in {
        "project_search",
        "code_generation_guidance",
        "read_only_ui_wrapper_planning",
        "read_only_code_planning",
        "comparison",
        "project_code_edit",
        "dcc_query",
        "graph_read_or_navigation",
        "asset_navigation",
    }:
        completed["intent_category"] = intent
        completed["primary_route"] = str(understanding.get("primary_route") or completed.get("primary_route") or "chat")
        completed["goal_type"] = str(understanding.get("goal_type") or completed.get("goal_type") or "respond")
        if completed["primary_route"] in {"dcc_query", "dcc_execute"}:
            completed["scope"] = "host"
            completed["host"] = str(understanding.get("host") or fallback.get("host") or "")
            if str(completed.get("target") or "").casefold() == str(completed.get("host") or "").casefold():
                completed["target"] = str(fallback.get("target") or completed.get("behavior") or "")

    if bool(understanding.get("mutation_requested")):
        completed["mutation_requested"] = True
    elif bool(understanding.get("read_only_requested")):
        completed["mutation_requested"] = False
    if bool(understanding.get("live_host_execution_requested")):
        completed["execution_requested"] = True

    artifact = str(understanding.get("requested_artifact") or "")
    if confidence >= 0.9:
        if artifact == "project_symbol_location":
            completed["deliverable"] = str(
                understanding.get("requested_member_type") or "file"
            )
        elif artifact in {"comparison", "ui_wrapper_plan"}:
            completed["deliverable"] = artifact
    return completed


def expand_prompt_context_candidates(
    candidates: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    *,
    prompt: str,
    facts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    facts = dict(facts or {})
    expanded = [dict(item) for item in candidates]
    active_path = str(facts.get("active_path") or "")
    for request in requests[:6]:
        kind = str(request.get("kind") or "")
        query = str(request.get("query") or prompt)
        target = str(request.get("target") or "")
        if kind == "project_file_candidates":
            _collect_project_file_guesses(expanded, query, active_path)
        elif kind == "file_symbols" and target:
            _collect_file_symbol_candidate(expanded, target)
        elif kind == "file_source" and target:
            try:
                path = Path(_resolve_candidate_file(target, facts))
                if path.exists() and path.is_file():
                    source = path.read_text(encoding="utf-8", errors="replace")[:16000]
                    _add_context_candidate(
                        expanded,
                        kind="file_source",
                        value={"file": target, "source": source},
                        source="filesystem",
                        confidence=0.98,
                    )
            except Exception:
                pass
        elif kind == "project_search":
            try:
                from tech_connector.services.project_search_service import gather_project_search_context

                evidence = gather_project_search_context(
                    query,
                    active_path=target or active_path or None,
                    limit=30,
                    scope="active" if target else None,
                )
                _add_context_candidate(
                    expanded,
                    kind="project_search_evidence",
                    value=str(evidence)[:16000],
                    source="project_index",
                    confidence=0.9,
                )
            except Exception:
                pass
    for item in expanded:
        item.pop("_key", None)
    return expanded[:36]


def _fallback_planning_result(
    prompt: str,
    understanding: dict[str, Any],
    contract: dict[str, Any],
    resolved_references: dict[str, Any],
) -> dict[str, Any]:
    primary_route = str(understanding.get("primary_route") or "")
    if primary_route in {"dcc_query", "dcc_execute"}:
        target = str(
            understanding.get("target_symbol")
            or understanding.get("behavior_description")
            or contract.get("subject_text")
            or ""
        )
    else:
        target = str(understanding.get("target_file") or contract.get("container_query") or "")
    if not target and resolved_references.get("that_file"):
        target = str(resolved_references["that_file"].get("value") or "")
    deliverable = str(contract.get("deliverable_type") or understanding.get("requested_artifact") or "answer")
    scope = (
        "selected_files"
        if resolved_references.get("those_files")
        else "exact_file"
        if target and _looks_like_file(target)
        else "host"
        if primary_route in {"dcc_query", "dcc_execute"}
        else "project"
        if primary_route in {"project_search", "target_discovery"}
        else "conversation"
    )
    unknowns = []
    if re.search(r"\b(that|this|those|these)\s+files?\b", prompt, re.I) and not resolved_references:
        unknowns.append("conversational file reference")
    return {
        "interpreted_request": str(understanding.get("normalized_goal") or prompt),
        "intent_category": str(understanding.get("primary_intent") or "general_chat"),
        "primary_route": str(understanding.get("primary_route") or "chat"),
        "goal_type": str(understanding.get("goal_type") or contract.get("goal_type") or "respond"),
        "deliverable": deliverable,
        "behavior": str(understanding.get("member_behavior") or understanding.get("behavior_description") or contract.get("behavior") or ""),
        "scope": scope,
        "target": target,
        "host": str(understanding.get("host") or contract.get("host_domain") or ""),
        "resolved_references": dict(resolved_references),
        "mutation_requested": bool(understanding.get("mutation_requested")),
        "execution_requested": bool(understanding.get("live_host_execution_requested")),
        "steps": list(contract.get("plan_steps") or []),
        "function_calls": [],
        "answer_contract": {
            "must_answer": [str(contract.get("success_definition") or "Satisfy the requested deliverable.")],
            "must_not_include": ["evidence outside a locked exact-file scope"] if scope == "exact_file" else [],
            "success_condition": str(contract.get("success_definition") or "The request is answered directly."),
        },
        "unknowns": unknowns,
        "context_requests": [],
        "clarification_question": "",
        "confidence": float(understanding.get("confidence") or 0.5),
        "reasons": ["Planning model unavailable; deterministic contract retained."],
    }


def _is_deterministic_project_lookup(
    prompt: str,
    understanding: dict[str, Any],
    contract: dict[str, Any],
    formulation: dict[str, Any],
) -> bool:
    """Return whether semantic understanding already defines a complete lookup."""
    if str(understanding.get("primary_route") or "") != "project_search":
        return False
    if str(understanding.get("primary_intent") or "") != "project_search":
        return False
    if str(understanding.get("requested_artifact") or "") != "project_symbol_location":
        return False
    if str(understanding.get("goal_type") or "") not in {"locate", "verify", "inspect"}:
        return False
    if float(understanding.get("confidence") or 0.0) < 0.9:
        return False
    if bool(understanding.get("mutation_requested") or understanding.get("live_host_execution_requested")):
        return False
    if not bool(understanding.get("read_only_requested")):
        return False
    if list(contract.get("unresolved_fields") or formulation.get("blocking_unknowns") or []):
        return False
    if bool(formulation.get("requires_clarification")):
        return False
    return not bool(re.search(
        r"\b(?:and then|after that|also (?:change|edit|modify|create|build|run|execute))\b",
        str(prompt or ""),
        re.IGNORECASE,
    ))


def _needs_context_reference_resolution(prompt: str) -> bool:
    return bool(re.search(
        r"\b(?:that|this|those|these|previous|last|same)\s+files?\b|\bin that file\b",
        str(prompt or ""),
        re.IGNORECASE,
    ))


def _should_pause_for_user_context(
    prompt: str,
    understanding: dict[str, Any],
    contract: dict[str, Any],
    formulation: dict[str, Any],
    resolved_references: dict[str, Any],
) -> bool:
    """Pause only for missing meaning or context that tools cannot resolve."""
    confidence = float(understanding.get("confidence") or 0.0)
    unresolved_reference = (
        _needs_context_reference_resolution(prompt)
        and not resolved_references
    )
    malformed_outcome = bool(re.search(
        r"^\s*(?:file|files|function|functions|method|methods|class|classes|code)\s+to\b",
        str(prompt or ""),
        re.IGNORECASE,
    ))
    missing_outcome = (
        confidence < 0.7
        and str(understanding.get("primary_route") or "") == "chat"
        and str(understanding.get("goal_type") or "") in {"", "respond", "unknown"}
        and not str(understanding.get("requested_artifact") or "").strip()
        and not str(
            understanding.get("behavior_description")
            or understanding.get("member_behavior")
            or contract.get("behavior")
            or ""
        ).strip()
    )
    # Unknown implementation facts and tool ordering belong to the planner.
    # Only missing conversational context or an absent user outcome belongs to
    # a clarification turn.
    return unresolved_reference or malformed_outcome or missing_outcome


def _deterministic_planning_result(
    prompt: str,
    understanding: dict[str, Any],
    contract: dict[str, Any],
    resolved_references: dict[str, Any],
    context_candidates: list[dict[str, Any]],
    *,
    planning_mode: str,
) -> dict[str, Any]:
    plan = _fallback_planning_result(
        prompt,
        understanding,
        contract,
        resolved_references,
    )
    plan = _validate_planning_result(
        plan,
        _action_catalog(),
        resolved_references,
        context_candidates=context_candidates,
    )
    plan["search_rounds"] = 0
    plan["model_role"] = "deterministic_fallback"
    plan["planning_mode"] = planning_mode
    if planning_mode == "deterministic_project_lookup":
        plan["reasons"] = [
            "High-confidence semantic intent and a complete read-only answer contract make model planning unnecessary."
        ]
    else:
        plan["reasons"] = [
            "A material user-owned ambiguity remains, so the long planning path was paused for clarification."
        ]
    return plan


def _validate_planning_result(
    plan: dict[str, Any],
    action_catalog: list[dict[str, Any]],
    resolved_references: dict[str, Any],
    *,
    context_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cleaned = dict(plan or {})
    allowed = {str(item.get("action_type") or "") for item in action_catalog}
    calls = []
    rejected = []
    for call in list(cleaned.get("function_calls") or []):
        action_type = str(call.get("action_type") or "")
        if action_type and action_type in allowed:
            calls.append(dict(call))
        elif action_type:
            rejected.append(action_type)
    cleaned["function_calls"] = calls
    if rejected:
        cleaned.setdefault("reasons", []).append(
            "Rejected unsupported planner actions: " + ", ".join(sorted(set(rejected)))
        )
        cleaned["confidence"] = min(float(cleaned.get("confidence") or 0.0), 0.84)

    if str(cleaned.get("primary_route") or "") == "dcc_query" and "query_dcc" in allowed:
        operation, params = _canonical_dcc_query_call(cleaned)
        cleaned["scope"] = "host"
        cleaned["function_calls"] = [
            {
                "action_type": "query_dcc",
                "arguments": {
                    "host": str(cleaned.get("host") or ""),
                    "operation": operation,
                    "params": params,
                    "operation_mode": "query",
                },
                "reason": "Read the requested live host state through the canonical non-mutating DCC query path.",
            }
        ]
        calls = list(cleaned["function_calls"])

    if str(cleaned.get("primary_route") or "") == "dcc_execute":
        operation, params = _planned_dcc_call(cleaned)
        if not _is_verified_dcc_capability(
            cleaned,
            operation,
            params,
            context_candidates=context_candidates,
        ):
            from tech_connector.services.dcc.dcc_operation_service import build_dcc_capability_gap_plan

            gap = build_dcc_capability_gap_plan(
                str(cleaned.get("host") or ""),
                operation,
                original_request=str(cleaned.get("interpreted_request") or ""),
            )
            search_call = {
                "action_type": "search_project",
                "arguments": {
                    "query": (
                        f"registered {cleaned.get('host') or 'DCC'} operation or bridge adapter "
                        f"for {operation}"
                    ),
                    "scope": "project",
                },
                "reason": "Prove whether an equivalent callable exists before creating a new adapter.",
            }
            cleaned.update(
                {
                    "intent_category": "dcc_capability_acquisition",
                    "primary_route": "target_discovery",
                    "goal_type": "modify",
                    "deliverable": "registered_dcc_capability",
                    "scope": "project",
                    "target": operation,
                    "mutation_requested": True,
                    "execution_requested": False,
                    "steps": list(gap.get("steps") or []),
                    "function_calls": [search_call] if "search_project" in allowed else [],
                    "capability_gap": gap,
                    "unknowns": [f"verified registered DCC callable for {operation}"],
                    "clarification_question": "",
                    "confidence": max(float(cleaned.get("confidence") or 0.0), 0.9),
                }
            )
            cleaned.setdefault("reasons", []).append(
                "Blocked an unregistered DCC callable and planned concrete capability acquisition before execution."
            )
            calls = list(cleaned["function_calls"])
        elif "execute_dcc" in allowed:
            cleaned["scope"] = "host"
            cleaned["function_calls"] = [
                {
                    "action_type": "execute_dcc",
                    "arguments": {
                        "host": str(cleaned.get("host") or ""),
                        "operation": operation,
                        "params": params,
                    },
                    "reason": "Execute the verified registered DCC operation after approval and preflight.",
                }
            ]
            calls = list(cleaned["function_calls"])

    if not calls and str(cleaned.get("primary_route") or "") in {"project_search", "target_discovery"} and "search_project" in allowed:
        target = str(cleaned.get("target") or "")
        cleaned["function_calls"] = [
            {
                "action_type": "search_project",
                "arguments": {
                    "query": str(cleaned.get("behavior") or cleaned.get("interpreted_request") or ""),
                    "target_file": target,
                    "scope": "exact_file" if target else "project",
                },
                "reason": "Gather evidence required by the planned project request.",
            }
        ]
    if not calls and str(cleaned.get("primary_route") or "") == "dcc_execute" and "execute_dcc" in allowed:
        cleaned["function_calls"] = [
            {
                "action_type": "execute_dcc",
                "arguments": {
                    "host": str(cleaned.get("host") or ""),
                    "callable": str(cleaned.get("target") or cleaned.get("behavior") or ""),
                },
                "reason": "Execute the resolved host operation after argument validation and approval.",
            }
        ]

    locked = resolved_references.get("that_file") or {}
    locked_target = str(locked.get("value") or "")
    if locked_target:
        proposed_target = str(cleaned.get("target") or "")
        if proposed_target and Path(proposed_target).name.casefold() != Path(locked_target).name.casefold():
            cleaned.setdefault("reasons", []).append(
                "Replaced a planner target that contradicted the resolved conversation reference."
            )
        cleaned["target"] = locked_target
        cleaned["scope"] = "exact_file"
        cleaned.setdefault("resolved_references", {})["that_file"] = locked
        for call in cleaned.get("function_calls") or []:
            arguments = dict(call.get("arguments") or {})
            if call.get("action_type") == "search_project":
                arguments["target_file"] = locked_target
                arguments["scope"] = "exact_file"
                call["arguments"] = arguments
    selected = resolved_references.get("those_files") or {}
    if selected.get("value"):
        cleaned["scope"] = "selected_files"
        cleaned.setdefault("resolved_references", {})["those_files"] = selected
    cleaned["confidence"] = max(0.0, min(1.0, float(cleaned.get("confidence") or 0.0)))
    raw_unknowns = [str(item) for item in cleaned.get("unknowns") or [] if str(item).strip()]
    has_explicit_dcc_target = bool(
        str(cleaned.get("primary_route") or "") == "dcc_execute"
        and str(cleaned.get("target") or "").strip()
    )
    cleaned["unknowns"] = [
        item
        for item in raw_unknowns
        if not re.search(
            r"observable validation|proves? (?:that )?.*succeed|how .*success .*observed|validation .*success",
            item,
            re.IGNORECASE,
        )
        and not (
            has_explicit_dcc_target
            and re.search(
                r"(?:the )?exact target (?:to|for) (?:modify|execute)",
                item,
                re.IGNORECASE,
            )
        )
    ]
    if len(cleaned["unknowns"]) != len(raw_unknowns):
        cleaned.setdefault("reasons", []).append(
            "Removed planner unknowns already resolved by explicit targets or the standard validation contract."
        )
    cleaned["context_requests"] = [dict(item) for item in cleaned.get("context_requests") or [] if isinstance(item, dict)]
    return cleaned


def _canonical_dcc_query_call(plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    host = str(plan.get("host") or "").lower()
    intent = str(plan.get("intent_category") or "").lower()
    target = str(plan.get("target") or "").strip()
    behavior = str(plan.get("behavior") or "").strip()
    evidence = " ".join((intent, target, behavior, str(plan.get("interpreted_request") or ""))).lower()

    if host == "maya":
        if re.search(r"\b(joints?|bones?|skeleton)\b", evidence):
            return "scene.list_joints", {}
        if re.search(r"\b(selected|selection)\b", evidence):
            return "scene.ls", {"selection": True}
        if re.search(r"\b(current\s+(?:file|scene)|scene\s+(?:path|name))\b", evidence):
            return "scene", {}

    if host == "unreal":
        if intent == "graph_read_or_navigation" or re.search(
            r"\b(blueprint|bp_[a-z0-9_]+|event\s*graph|compile\s+status)\b",
            evidence,
        ):
            params = {"target_asset": target} if target else {}
            return "blueprint.scan", params
        if intent == "asset_navigation":
            params = {"target_asset": target} if target else {}
            return "navigation.open_asset", params
        if re.search(r"\b(project|snapshot)\b", evidence):
            return "project.snapshot", {}
        if re.search(r"\b(selected|selection)\b", evidence):
            return "selection", {}

    return target or behavior or "state", {}


def _planned_dcc_call(plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for call in plan.get("function_calls") or []:
        if str(call.get("action_type") or "") != "execute_dcc":
            continue
        arguments = dict(call.get("arguments") or {})
        operation = str(
            arguments.get("operation")
            or arguments.get("target_identifier")
            or arguments.get("callable")
            or ""
        ).strip()
        params = dict(arguments.get("params") or arguments.get("payload") or {})
        if operation:
            from tech_connector.services.dcc.dcc_operation_service import (
                resolve_registered_dcc_operation_key,
            )

            canonical = resolve_registered_dcc_operation_key(
                str(plan.get("host") or ""),
                operation,
            )
            return canonical or operation, params
    operation = str(
        plan.get("target") or plan.get("behavior") or "requested_operation"
    ).strip()
    from tech_connector.services.dcc.dcc_operation_service import (
        resolve_registered_dcc_operation_key,
    )

    canonical = resolve_registered_dcc_operation_key(
        str(plan.get("host") or ""),
        operation,
    )
    return canonical or operation, {}


def _is_verified_dcc_capability(
    plan: dict[str, Any],
    operation: str,
    params: dict[str, Any],
    *,
    context_candidates: list[dict[str, Any]] | None = None,
) -> bool:
    from tech_connector.services.dcc.dcc_operation_service import registered_dcc_operation

    registered = registered_dcc_operation(str(plan.get("host") or ""), operation)
    if registered is not None and operation not in {"api.call", "tool.call"}:
        return True

    if _context_confirms_callable(operation, context_candidates or []):
        return True
    if registered is None:
        return False

    function_name = str(params.get("function") or "").strip()
    original_request = str(plan.get("interpreted_request") or "")
    return bool(function_name and function_name.casefold() in original_request.casefold())


def _context_confirms_callable(
    operation: str,
    candidates: list[dict[str, Any]],
) -> bool:
    requested = str(operation or "").split(".")[-1].casefold()
    if not requested:
        return False
    for candidate in candidates:
        if str(candidate.get("source") or "") not in {"project_index", "current_file_ast"}:
            continue
        metadata = dict(candidate.get("metadata") or {})
        symbol_text = str(metadata.get("symbol") or "")
        if re.search(rf"\b{re.escape(requested)}\b", symbol_text, re.IGNORECASE):
            return True
        value = candidate.get("value")
        if isinstance(value, dict):
            for symbol in value.get("symbols") or []:
                if str(symbol.get("name") or "").casefold() == requested:
                    return True
    return False


def _looks_like_file(value: str) -> bool:
    return bool(re.search(r"\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui)$", str(value or ""), re.I))


def _apply_planning_result(
    understanding: Any,
    understanding_data: dict[str, Any],
    contract: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    mapping = {
        "primary_intent": "intent_category",
        "primary_route": "primary_route",
        "goal_type": "goal_type",
        "behavior_description": "behavior",
        "target_file": "target",
        "confidence": "confidence",
        "mutation_requested": "mutation_requested",
        "live_host_execution_requested": "execution_requested",
    }
    for field_name, plan_name in mapping.items():
        value = plan.get(plan_name)
        if value in (None, ""):
            continue
        if field_name == "target_file" and not _looks_like_file(str(value)):
            continue
        setattr(understanding, field_name, value)
        understanding_data[field_name] = value

    deliverable = str(plan.get("deliverable") or "")
    if deliverable:
        understanding.requested_artifact = deliverable
        understanding_data["requested_artifact"] = deliverable
    target = str(plan.get("target") or "")
    if target and _looks_like_file(target):
        understanding.target_container_type = "file"
        understanding.target_container_query = target
        understanding.target_container_path = target
        understanding.reference_scope = "exact_file" if plan.get("scope") == "exact_file" else understanding.reference_scope
        understanding_data.update(
            {
                "target_container_type": "file",
                "target_container_query": target,
                "target_container_path": target,
                "reference_scope": understanding.reference_scope,
            }
        )
    if "function" in deliverable:
        understanding.requested_member_type = "function"
        understanding.member_behavior = str(plan.get("behavior") or "")
        understanding_data["requested_member_type"] = "function"
        understanding_data["member_behavior"] = understanding.member_behavior

    contract.update(
        {
            "goal": str(plan.get("interpreted_request") or contract.get("goal") or ""),
            "goal_type": str(plan.get("goal_type") or contract.get("goal_type") or "respond"),
            "deliverable_type": deliverable or contract.get("deliverable_type") or "answer",
            "action": str((list(plan.get("steps") or [{}]) or [{}])[0].get("action") or contract.get("action") or ""),
            "behavior": str(plan.get("behavior") or contract.get("behavior") or ""),
            "container_type": "file" if target and _looks_like_file(target) else contract.get("container_type") or "",
            "container_query": target or contract.get("container_query") or "",
            "read_only": not bool(plan.get("mutation_requested") or plan.get("execution_requested")),
            "mutation_requested": bool(plan.get("mutation_requested")),
            "execution_requested": bool(plan.get("execution_requested")),
            "confidence": float(plan.get("confidence") or contract.get("confidence") or 0.0),
            "scope": str(plan.get("scope") or ""),
            "target": target,
            "resolved_references": dict(plan.get("resolved_references") or {}),
            "answer_contract": dict(plan.get("answer_contract") or {}),
            "planner_function_calls": [dict(item) for item in plan.get("function_calls") or []],
        }
    )
    if plan.get("steps"):
        contract["plan_steps"] = [dict(item) for item in plan.get("steps") or []]
    contract["unresolved_fields"] = [str(item) for item in plan.get("unknowns") or []]
    contract["source"] = "planning_model_verified" if plan.get("model_role") == "plan" else contract.get("source") or "deterministic"
    understanding_data["semantic_execution_contract"] = dict(contract)


def build_prompt_execution_context(
    prompt: str,
    *,
    host_hint: str = "",
    decision_facts: dict[str, Any] | None = None,
) -> PromptExecutionContext:
    """Build the canonical request context exactly once before routing."""
    from tech_connector.services.prompt_intent_service import understand_prompt_request
    from tech_connector.services.prompt_task_splitter_service import build_request_task_graph
    from tech_connector.services.problem_formulation_service import build_problem_formulation
    from tech_connector.services.semantic_execution_contract_service import build_semantic_execution_contract

    normalized_prompt = _normalize_prompt(prompt)
    # Stage 1: the small semantic model sees only the normalized request and a
    # host hint. Context guesses are deliberately gathered after this pass.
    understanding = understand_prompt_request(
        normalized_prompt,
        host=host_hint,
        context={
            "active_path": (decision_facts or {}).get("active_path") or "",
            "settings": dict((decision_facts or {}).get("settings") or {}),
        },
    )
    understanding_data = understanding.to_dict()

    # PromptIntentService may still provide a compatibility contract during the
    # migration.  Rebuild only when it did not provide one; otherwise normalize
    # the supplied contract through the canonical service once.
    existing_contract = dict(understanding_data.get("semantic_execution_contract") or {})
    if existing_contract:
        semantic_contract = existing_contract
    else:
        semantic_contract = build_semantic_execution_contract(
            normalized_prompt,
            host=host_hint,
            baseline_understanding=understanding_data,
        ).to_dict()

    formulation_result = build_problem_formulation(
        normalized_prompt,
        decision={
            **dict(decision_facts or {}),
            "host": host_hint,
        },
        request_understanding=understanding_data,
        semantic_contract=semantic_contract,
    )
    formulation = formulation_result.to_dict()

    # The contract may use formulation evidence to close semantic gaps, but it
    # remains one canonical object in this context.
    if not existing_contract or semantic_contract.get("unresolved_fields"):
        semantic_contract = build_semantic_execution_contract(
            normalized_prompt,
            host=host_hint,
            baseline_understanding=understanding_data,
            problem_formulation=formulation,
        ).to_dict()

    deterministic_lookup = _is_deterministic_project_lookup(
        normalized_prompt,
        understanding_data,
        semantic_contract,
        formulation,
    )
    if deterministic_lookup and not _needs_context_reference_resolution(normalized_prompt):
        context_candidates, resolved_references = [], {}
    else:
        context_candidates, resolved_references = gather_prompt_context_candidates(
            normalized_prompt,
            understanding_data,
            decision_facts,
        )

    if deterministic_lookup:
        planning_result = _deterministic_planning_result(
            normalized_prompt,
            understanding_data,
            semantic_contract,
            resolved_references,
            context_candidates,
            planning_mode="deterministic_project_lookup",
        )
    elif _should_pause_for_user_context(
        normalized_prompt,
        understanding_data,
        semantic_contract,
        formulation,
        resolved_references,
    ):
        planning_result = _deterministic_planning_result(
            normalized_prompt,
            understanding_data,
            semantic_contract,
            resolved_references,
            context_candidates,
            planning_mode="clarification_fast_path",
        )
    else:
        # Bounded context resolvers feed the larger planning model only when
        # semantic understanding leaves real reasoning or execution work.
        planning_result, context_candidates = plan_prompt_with_context(
            normalized_prompt,
            understanding_data,
            semantic_contract,
            formulation,
            context_candidates,
            resolved_references,
            decision_facts,
        )
    _apply_planning_result(
        understanding,
        understanding_data,
        semantic_contract,
        planning_result,
    )
    if planning_result.get("capability_gap"):
        formulation["action_mode"] = "mutate"
        formulation["candidate_plan"] = [
            dict(item) for item in planning_result.get("steps") or []
        ]
        formulation["desired_outcome"] = (
            "A concrete DCC adapter is implemented, registered, validated, and then used "
            "to replan the original request."
        )
        formulation["blocking_unknowns"] = list(planning_result.get("unknowns") or [])

    understanding_data["semantic_execution_contract"] = dict(semantic_contract)
    task_graph = build_request_task_graph(
        normalized_prompt,
        host=host_hint,
        understanding=understanding,
        problem_formulation=formulation,
        semantic_contract=semantic_contract,
    )
    task_graph["semantic_execution_contract"] = dict(semantic_contract)

    return PromptExecutionContext(
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        host_hint=host_hint,
        request_understanding=understanding_data,
        problem_formulation=formulation,
        context_candidates=context_candidates,
        resolved_references=resolved_references,
        planning_result=planning_result,
        semantic_execution_contract=semantic_contract,
        task_graph=task_graph,
        evidence_state=EvidenceState(),
    )


def validate_prompt_understanding(
    execution_context: PromptExecutionContext | dict[str, Any],
) -> UnderstandingValidation:
    """Gate routing until intent, deliverable, scope, and references agree."""
    context = (
        execution_context
        if isinstance(execution_context, PromptExecutionContext)
        else execution_context_from_dict(dict(execution_context or {}))
    )
    plan = dict(context.planning_result or {})
    understanding = dict(context.request_understanding or {})
    contract = dict(context.semantic_execution_contract or {})
    prompt = str(context.normalized_prompt or context.prompt or "")
    lower = prompt.lower()
    repaired: dict[str, Any] = {}
    reasons: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []

    target = str(plan.get("target") or understanding.get("target_file") or contract.get("target") or contract.get("container_query") or "")
    if not target and context.resolved_references.get("that_file"):
        target = str(context.resolved_references["that_file"].get("value") or "")
        if target:
            repaired["resolved_target_file"] = target
            plan["target"] = target
            plan["scope"] = "exact_file"
    selected_files = (context.resolved_references.get("those_files") or {}).get("value") or []
    if selected_files:
        repaired["resolved_target_files"] = list(selected_files)

    goal_type = str(plan.get("goal_type") or understanding.get("goal_type") or "").lower()
    route = str(plan.get("primary_route") or understanding.get("primary_route") or "").lower()
    deliverable = str(plan.get("deliverable") or contract.get("deliverable_type") or understanding.get("requested_artifact") or "").lower()
    behavior = str(plan.get("behavior") or contract.get("behavior") or understanding.get("behavior_description") or "").strip()
    scope = str(plan.get("scope") or contract.get("scope") or "").lower()
    unknowns = [str(item) for item in plan.get("unknowns") or contract.get("unresolved_fields") or [] if str(item).strip()]
    reference_required = bool(re.search(r"\b(that|this|those|these|previous|last|same)\s+files?\b|\bin that file\b", lower))
    reference_resolved = not reference_required or bool(target or selected_files)

    actionable_domain = bool(
        re.search(r"\b(file|files|function|functions|method|methods|class|code|project|run|execute|edit|modify|create|build|write|find|locate|search|verify)\b", lower)
    )
    malformed_fragment = bool(re.search(r"^\s*(?:file|files|function|functions|code)\s+to\b", lower))
    clear_action = bool(goal_type and goal_type not in {"", "unknown"})
    if actionable_domain and goal_type == "respond" and route == "chat":
        clear_action = False
    if malformed_fragment:
        clear_action = False
        ambiguous.append("requested_action")
        reasons.append("The prompt is a noun fragment and does not establish whether to search, explain, generate, or edit.")
    if not clear_action:
        missing.append("requested_action")

    clear_deliverable = bool(deliverable and deliverable not in {"unknown", "project_fact"})
    if not clear_deliverable:
        missing.append("deliverable")

    if scope in {"exact_file", "selected_files"}:
        clear_scope = bool(target or selected_files)
    elif scope in {"project", "conversation", "host"}:
        clear_scope = True
    else:
        clear_scope = bool(target) or not actionable_domain
    if not clear_scope:
        missing.append("target_or_scope")

    if not reference_resolved:
        missing.append("resolved_references")
        reasons.append("A conversational reference remains unresolved.")

    mutation = bool(plan.get("mutation_requested") or understanding.get("mutation_requested"))
    execution = bool(plan.get("execution_requested") or understanding.get("live_host_execution_requested"))
    route_consistent = not (
        (mutation and route in {"project_search", "chat"} and goal_type not in {"generate", "explain", "learn"})
        or (
            execution
            and route not in {
                "dcc_execute",
                "action_graph",
                "pipeline_graph",
                "target_discovery",
            }
        )
        or (scope == "exact_file" and not target)
    )
    if not route_consistent:
        ambiguous.append("route_semantic_contract")
        reasons.append("The proposed route contradicts the semantic contract.")

    checks = [clear_action, clear_deliverable, clear_scope, reference_resolved, route_consistent]
    structural = sum(1.0 for value in checks if value) / len(checks)
    declared = float(plan.get("confidence") or understanding.get("confidence") or contract.get("confidence") or 0.0)
    confidence = round(structural * 0.7 + max(0.0, min(1.0, declared)) * 0.3, 3)
    if unknowns:
        confidence = min(confidence, 0.84)
        missing.extend(item for item in unknowns if item not in missing)
        reasons.append("The planning model still reports unresolved evidence or meaning.")
    if malformed_fragment:
        confidence = min(confidence, 0.64)

    valid = confidence >= 0.85 and all(checks) and not unknowns
    clarification_required = not valid
    question = str(plan.get("clarification_question") or "").strip()
    if clarification_required and not question:
        if not reference_resolved:
            question = "Which file do you mean by 'that file'?"
        elif "requested_action" in missing:
            subject = behavior or "that code"
            question = f"Do you want me to find an existing implementation for {subject}, or help write one?"
        elif "deliverable" in missing:
            question = "What should I return: a file path, matching functions, an explanation, or code?"
        elif "target_or_scope" in missing:
            question = "Should I inspect the current file, selected files, or the whole project?"
        else:
            question = "Which part of this request should I treat as the required outcome?"

    result = UnderstandingValidation(
        valid=valid,
        confidence=confidence,
        missing_fields=list(dict.fromkeys(missing)),
        ambiguous_fields=list(dict.fromkeys(ambiguous)),
        repaired_fields=repaired,
        clarification_required=clarification_required,
        clarification_question=question,
        reasons=reasons or (["Intent, deliverable, scope, references, and route agree."] if valid else []),
    )
    context.understanding_validation = result.to_dict()
    context.planning_result = plan
    if repaired.get("resolved_target_file"):
        context.request_understanding["target_file"] = repaired["resolved_target_file"]
        context.semantic_execution_contract["target"] = repaired["resolved_target_file"]
        context.semantic_execution_contract["container_query"] = repaired["resolved_target_file"]
        context.semantic_execution_contract["scope"] = "exact_file"
    return result


_ANSWER_REVIEW_SYSTEM = """You are the answer-quality reviewer for a coding and DCC assistant.
Return ONLY JSON. Compare the candidate answer with the original request, authoritative plan, exact scope,
resolved references, and answer contract. Do not reward a nonempty answer unless it proves the requested result.
If evidence is missing, request focused context so the system can continue searching. Do not invent facts.
Schema: {"adequate":false,"score":0.0,"failures":[],"context_requests":[],"clarification_question":"","validated_facts":[],"reasons":[]}"""


def review_prompt_answer(
    execution_context: PromptExecutionContext,
    route_decision: dict[str, Any],
    result: Any,
) -> dict[str, Any]:
    """Have the planning model verify the answer against its own contract."""
    text = str(getattr(result, "text", "") or "")
    metadata = dict(getattr(result, "metadata", None) or {})
    plan = dict(execution_context.planning_result or {})
    deterministic = _deterministic_answer_review(execution_context, text, metadata)
    if str(metadata.get("result_type") or "") in {
        "project_index_direct",
        "project_health",
        "connection_status",
        "import_coverage",
    }:
        deterministic["reviewer"] = "trusted_deterministic_result"
        return deterministic
    packet = {
        "original_request": execution_context.normalized_prompt or execution_context.prompt,
        "authoritative_plan": plan,
        "resolved_references": execution_context.resolved_references,
        "route_decision": {
            key: route_decision.get(key)
            for key in ("route", "provider", "intent_category", "resolved_target_file", "reference_scope_locked")
        },
        "candidate_answer": text[:18000],
        "result_metadata": {
            key: metadata.get(key)
            for key in ("result_type", "selected_file", "resolved_target_file", "reference_scope_locked")
        },
        "deterministic_checks": deterministic,
    }
    model_review = _model_json(_ANSWER_REVIEW_SYSTEM, packet)
    if not model_review:
        return deterministic

    model_review["score"] = max(0.0, min(1.0, float(model_review.get("score") or 0.0)))
    model_review["failures"] = [str(item) for item in model_review.get("failures") or []]
    model_review["context_requests"] = [dict(item) for item in model_review.get("context_requests") or [] if isinstance(item, dict)]
    model_review["validated_facts"] = [dict(item) if isinstance(item, dict) else {"fact": str(item)} for item in model_review.get("validated_facts") or []]
    if not deterministic["adequate"]:
        model_review["adequate"] = False
        model_review["score"] = min(model_review["score"], deterministic["score"])
        model_review["failures"] = list(dict.fromkeys([*deterministic["failures"], *model_review["failures"]]))
    model_review["reviewer"] = "planning_model"
    return model_review


def _deterministic_answer_review(
    context: PromptExecutionContext,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    plan = dict(context.planning_result or {})
    target = str(plan.get("target") or context.semantic_execution_contract.get("target") or "")
    scope = str(plan.get("scope") or context.semantic_execution_contract.get("scope") or "")
    deliverable = str(plan.get("deliverable") or context.semantic_execution_contract.get("deliverable_type") or "")
    behavior = str(plan.get("behavior") or context.semantic_execution_contract.get("behavior") or "")
    checks: dict[str, bool] = {"result_present": bool(text.strip())}
    failures: list[str] = []
    if scope == "exact_file":
        returned_target = str(metadata.get("resolved_target_file") or metadata.get("selected_file") or target)
        checks["exact_scope"] = bool(target and returned_target and Path(target).name.casefold() == Path(returned_target).name.casefold())
    else:
        checks["exact_scope"] = True
    if "function" in deliverable:
        checks["deliverable"] = bool(
            re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\([^\n]*\)", text)
            or re.search(r"\bfunction|method\b", text, re.I)
        )
    elif "file" in deliverable:
        checks["deliverable"] = bool(re.search(r"\.(?:py|cpp|h|hpp|cs|qml|ui)\b", text, re.I))
    else:
        checks["deliverable"] = bool(text.strip())
    behavior_terms = [
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", behavior.lower())
        if token not in {
            "find", "finds", "finding", "create", "creates", "creating",
            "build", "builds", "building", "make", "makes", "making",
            "use", "uses", "using", "locate", "search", "inspect", "review",
            "report", "respond", "discuss", "explain", "list", "show",
            "do", "does", "have", "has", "any", "existing",
            "the", "that", "with", "from", "into", "project",
        }
    ]
    behavior_terms = [token[:-1] if token.endswith("s") and len(token) > 4 else token for token in behavior_terms]
    checks["behavior"] = not behavior_terms or any(term in text.lower() for term in behavior_terms)
    negative_answer = bool(re.search(r"\b(no|did not find|could not find|none)\b", text, re.I))
    candidate_text = json.dumps(context.context_candidates, default=str).lower()
    candidate_support = bool(behavior_terms) and all(term in candidate_text for term in set(behavior_terms))
    checks["evidence_consistency"] = not (negative_answer and candidate_support)
    if negative_answer and scope == "exact_file":
        checks["negative_evidence_tier"] = int(metadata.get("evidence_tier") or 0) >= 2
    else:
        checks["negative_evidence_tier"] = True
    if re.search(
        r"^\s*(?:are\s+there|is\s+there|does\s+.+?\s+have|do\s+.+?\s+have)\b",
        context.normalized_prompt,
        re.I,
    ):
        checks["explicit_conclusion"] = bool(re.search(r"\b(yes|no|found|did not find|could not find|none)\b", text, re.I))
    else:
        checks["explicit_conclusion"] = True
    for name, passed in checks.items():
        if not passed:
            failures.append(
                {
                    "result_present": "No answer was returned.",
                    "exact_scope": "The answer did not remain inside the resolved exact-file scope.",
                    "deliverable": "The answer did not return the requested deliverable type.",
                    "behavior": "The answer did not establish behavioral relevance.",
                    "evidence_consistency": "The answer claims no match even though gathered source context contains behaviorally relevant candidates.",
                    "negative_evidence_tier": "A negative exact-file conclusion was returned without AST or source-body evidence.",
                    "explicit_conclusion": "The answer did not explicitly say whether the requested implementation exists.",
                }[name]
            )
    score = round(sum(1.0 for value in checks.values() if value) / max(1, len(checks)), 3)
    context_requests = []
    if (
        not checks.get("behavior")
        or not checks.get("deliverable")
        or not checks.get("evidence_consistency")
        or not checks.get("negative_evidence_tier")
    ):
        context_requests.append(
            {
                "kind": "file_source" if target else "project_search",
                "query": behavior or context.normalized_prompt,
                "target": target,
                "reason": "Inspect stronger source evidence for the requested behavior.",
            }
        )
    return {
        "adequate": not failures and score >= 0.8,
        "score": score,
        "checks": checks,
        "failures": failures,
        "context_requests": context_requests,
        "clarification_question": "",
        "validated_facts": [],
        "reasons": ["Deterministic answer-contract checks completed."],
        "reviewer": "deterministic_fallback",
    }


def continue_answer_search(
    execution_context: PromptExecutionContext,
    route_decision: dict[str, Any],
    result: Any,
    review: dict[str, Any],
    facts: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Gather missing evidence, repair the answer, and review it one more time."""
    requests = list(review.get("context_requests") or [])
    target = str(execution_context.planning_result.get("target") or "")
    if not requests:
        requests = [
            {
                "kind": "file_source" if target else "project_search",
                "query": execution_context.planning_result.get("behavior") or execution_context.normalized_prompt,
                "target": target,
                "reason": "Answer review failed; gather the next stronger evidence tier.",
            }
        ]
    expanded = expand_prompt_context_candidates(
        execution_context.context_candidates,
        requests,
        prompt=execution_context.normalized_prompt,
        facts=facts,
    )
    execution_context.context_candidates = expanded
    repair_system = """You repair a rejected answer using only supplied evidence. Return ONLY JSON with
{\"answer\":\"...\",\"confidence\":0.0,\"validated_facts\":[],\"remaining_unknowns\":[],\"clarification_question\":\"\"}.
Honor exact-file scope, answer the requested deliverable directly, explicitly state yes/no for existence questions,
and never invent symbols or paths."""
    packet = {
        "original_request": execution_context.normalized_prompt,
        "authoritative_plan": execution_context.planning_result,
        "rejected_answer": str(getattr(result, "text", "") or "")[:12000],
        "review_failures": list(review.get("failures") or []),
        "new_context": expanded,
        "route_decision": route_decision,
    }
    repaired = _model_json(repair_system, packet)
    answer = str(repaired.get("answer") or "").strip()
    if not answer:
        return str(getattr(result, "text", "") or ""), review

    from tech_connector.engine.progress_events import EngineResult

    candidate = EngineResult(
        action="answer",
        label=str(getattr(result, "label", "Answer") or "Answer"),
        text=answer,
        metadata=dict(getattr(result, "metadata", None) or {}),
    )
    second_review = review_prompt_answer(execution_context, route_decision, candidate)
    second_review["search_continued"] = True
    second_review["repair_confidence"] = float(repaired.get("confidence") or 0.0)
    if repaired.get("validated_facts"):
        second_review["validated_facts"] = list(repaired.get("validated_facts") or [])
    if repaired.get("remaining_unknowns"):
        second_review["remaining_unknowns"] = list(repaired.get("remaining_unknowns") or [])
    if repaired.get("clarification_question") and not second_review.get("clarification_question"):
        second_review["clarification_question"] = str(repaired.get("clarification_question"))
    return answer, second_review


def execution_context_from_dict(data: dict[str, Any] | None) -> PromptExecutionContext:
    """Restore a context from serialized state without reinterpreting a prompt."""
    payload = dict(data or {})
    evidence_data = dict(payload.get("evidence_state") or {})
    evidence = EvidenceState(
        current_tier=int(evidence_data.get("current_tier") or payload.get("execution_tier") or 0),
        attempted_tiers=[int(value) for value in evidence_data.get("attempted_tiers") or []],
        records=[dict(item) for item in evidence_data.get("records") or []],
        sufficient=bool(evidence_data.get("sufficient")),
        confidence=float(evidence_data.get("confidence") or 0.0),
        answer=str(evidence_data.get("answer") or ""),
        insufficiency_reasons=[str(value) for value in evidence_data.get("insufficiency_reasons") or []],
        stop_reason=str(evidence_data.get("stop_reason") or ""),
    )
    return PromptExecutionContext(
        prompt=str(payload.get("prompt") or ""),
        normalized_prompt=str(payload.get("normalized_prompt") or payload.get("prompt") or ""),
        host_hint=str(payload.get("host_hint") or ""),
        request_understanding=dict(payload.get("request_understanding") or payload.get("understanding") or {}),
        problem_formulation=dict(payload.get("problem_formulation") or {}),
        context_candidates=[dict(item) for item in payload.get("context_candidates") or []],
        resolved_references=dict(payload.get("resolved_references") or {}),
        planning_result=dict(payload.get("planning_result") or {}),
        understanding_validation=dict(payload.get("understanding_validation") or {}),
        semantic_execution_contract=dict(payload.get("semantic_execution_contract") or payload.get("semantic_contract") or {}),
        task_graph=dict(payload.get("task_graph") or payload.get("goal_graph") or {}),
        evidence_state=evidence,
        execution_decision=dict(payload.get("execution_decision") or {}),
        runtime_state=dict(payload.get("runtime_state") or {}),
        reasoning_pipeline=dict(payload.get("reasoning_pipeline") or {}),
        visible_progress=dict(payload.get("visible_progress") or {}),
    )
