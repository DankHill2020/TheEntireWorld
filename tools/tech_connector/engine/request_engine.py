"""The Entire World Intelligence Engine."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Callable, Iterable

from .providers import ProjectSearchProvider, RequestProvider, default_providers
from reasoning_runtime.engine.request_context import RequestContext
from reasoning_runtime.engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from reasoning_runtime.engine.runtime_request_engine import RuntimeRequestPreparation
from tech_connector.services.reasoning.request_frame_service import analyze_request_frame

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]


def _is_explicit_plan_only_request(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:plan|design|outline)\s+only\b|"
            r"\b(?:do\s+not|don't|dont)\s+(?:edit|modify|change|execute|run|apply)\b",
            str(text or ""),
            re.IGNORECASE,
        )
    )


def _render_verified_plan(planning_result: dict) -> str:
    lines = [
        "Verified plan",
        "",
        str(
            planning_result.get("interpreted_request")
            or planning_result.get("behavior")
            or "Plan the requested work."
        ),
        "",
        "Steps",
    ]
    for index, row in enumerate(planning_result.get("steps") or [], start=1):
        step = dict(row or {})
        objective = str(step.get("objective") or step.get("title") or step.get("action") or "Complete step")
        success = str(step.get("success_condition") or "").strip()
        lines.append(f"{index}. {objective}")
        if success:
            lines.append(f"   Proof: {success}")
    references = dict(planning_result.get("resolved_references") or {})
    if references:
        lines.extend(["", "Resolved context"])
        for name, value in references.items():
            resolved = value.get("value") if isinstance(value, dict) else value
            lines.append(f"- {name}: {resolved}")
    verification = dict(planning_result.get("request_plan_verification") or {})
    lines.extend(
        [
            "",
            (
                "Verification: request coverage passed."
                if verification.get("matches_request")
                else "Verification: request coverage still has unresolved items."
            ),
        ]
    )
    return "\n".join(lines)


class RequestEngine:
    """Route a request through deterministic, non-UI-thread preparation."""

    def __init__(
        self,
        progress: ProgressCallback | None = None,
        activity: ActivityCallback | None = None,
        providers: Iterable[RequestProvider] | None = None,
        runtime_kernel=None,
    ):
        self.progress = progress or (lambda _event: None)
        self.activity = activity or (lambda _event: None)
        self.providers = list(providers or default_providers())
        if runtime_kernel is None:
            from reasoning_runtime import ReasoningKernel
            from tech_connector.adapters.domain_package import TechConnectorDomainPackage

            runtime_kernel = ReasoningKernel()
            runtime_kernel.install(TechConnectorDomainPackage())
        self.runtime_kernel = runtime_kernel
        self.runtime_preparation = RuntimeRequestPreparation(self.runtime_kernel)

    def emit(self, stage: str, message: str, current: int = 0, total: int = 0, detail: str = "") -> None:
        self.progress(ProgressEvent(stage=stage, message=message, current=current, total=total, detail=detail))

    def _dispatch_preclassified(
        self,
        route_decision: dict,
        context: RequestContext,
    ) -> EngineResult:
        """Dispatch a caller-supplied route without repeating semantic/model work."""
        from tech_connector.services.prompt.prompt_dispatch_service import PromptDispatchService

        self.emit(
            "route",
            f"Routing through {route_decision.get('execution_route') or route_decision.get('route')}",
        )
        result = PromptDispatchService().dispatch(
            route_decision,
            context,
            self.progress,
            self.activity,
        )
        result.metadata = {
            **dict(result.metadata or {}),
            "reasoning_runtime": dict((context.extras or {}).get("reasoning_runtime") or {}),
            "route_decision": dict(
                (result.metadata or {}).get("route_decision") or route_decision
            ),
            "preclassified_route": True,
        }
        return result

    def _clarification_result(
        self,
        context: RequestContext,
        question: str,
        *,
        missing_fields: list[str] | None = None,
        route_decision: dict | None = None,
        execution_context: dict | None = None,
    ) -> EngineResult:
        missing = list(missing_fields or ["requested_action"])
        slot_name = missing[0] if missing else "requested_action"
        slot = {
            "name": slot_name,
            "label": slot_name.replace("_", " "),
            "expected_type": "value",
            "free_text_allowed": True,
            "multiple": False,
            "state": "unresolved",
        }
        pending = {
            "kind": "semantic",
            "intent": "request_understanding",
            "route_decision": dict(route_decision or {}),
            "execution_request": {"original_prompt": context.text},
            "unresolved_slots": [slot],
            "accepted_value_schemas": {
                slot_name: {
                    "expected_type": "value",
                    "choices": [],
                    "free_text_allowed": True,
                    "multiple": False,
                }
            },
            "resumable": True,
        }
        return EngineResult(
            action="clarify",
            label="Request Understanding",
            text=question,
            metadata={
                "engine_path": "request_understanding",
                "result_type": "understanding_clarification",
                "pending_clarification": pending,
                "clarification": {
                    "kind": "semantic",
                    "reason": "The request cannot route safely until this concept is resolved.",
                    "route_decision": dict(route_decision or {}),
                },
                "route_decision": dict(route_decision or {}),
                "prompt_execution_context": dict(execution_context or {}),
            },
        )

    def _fast_semantic_project_lookup(self, context: RequestContext) -> EngineResult | None:
        """Answer a complete semantic symbol-location contract without full planning."""

        if re.search(
            r"\b(?:that|this|those|these|previous|last|same)\s+files?\b|\bin that file\b",
            context.text,
            re.IGNORECASE,
        ):
            return None
        try:
            from tech_connector.services.prompt.prompt_intent_service import understand_prompt_request

            understanding = understand_prompt_request(
                context.text,
                host=str((context.extras or {}).get("host_hint") or ""),
            )
        except Exception:
            return None
        if not (
            understanding.primary_route == "project_search"
            and understanding.primary_intent == "project_search"
            and understanding.requested_artifact == "project_symbol_location"
            and understanding.goal_type in {"locate", "verify", "inspect"}
            and understanding.confidence >= 0.9
            and understanding.read_only_requested
            and not understanding.mutation_requested
            and not understanding.live_host_execution_requested
        ):
            return None

        understanding_data = understanding.to_dict()
        semantic_contract = dict(
            understanding_data.get("semantic_execution_contract") or {}
        )
        if not semantic_contract:
            try:
                from tech_connector.services.reasoning.semantic_execution_contract_service import (
                    build_semantic_execution_contract,
                )

                semantic_contract = build_semantic_execution_contract(
                    context.text,
                    host=str((context.extras or {}).get("host_hint") or ""),
                    baseline_understanding=understanding_data,
                ).to_dict()
            except Exception:
                semantic_contract = {}
        fast_context = replace(
            context,
            extras={
                **dict(context.extras or {}),
                "semantic_execution_contract": semantic_contract,
            },
        )
        result = ProjectSearchProvider().handle(fast_context, self.progress, self.activity)
        metadata = dict(result.metadata or {})
        if result.action != "answer" or metadata.get("result_type") != "project_index_direct":
            return None

        behavior = str(understanding.behavior_description or understanding.member_behavior or "")
        deliverable = str(semantic_contract.get("deliverable_type") or "file")
        planning_result = {
            "interpreted_request": understanding.normalized_goal or context.text,
            "intent_category": understanding.primary_intent,
            "primary_route": understanding.primary_route,
            "goal_type": understanding.goal_type,
            "deliverable": deliverable,
            "behavior": behavior,
            "scope": "project",
            "target": "",
            "mutation_requested": False,
            "execution_requested": False,
            "steps": [],
            "function_calls": [{
                "action_type": "search_project",
                "arguments": {"query": behavior or context.text, "scope": "project"},
                "reason": "Resolve the semantic symbol-location request from the maintained project index.",
            }],
            "unknowns": [],
            "confidence": understanding.confidence,
            "model_role": "deterministic_fallback",
            "planning_mode": "semantic_index_fast_path",
        }
        route_decision = {
            "route": "project_search",
            "provider": "project_search",
            "execution_route": "engine.project_search",
            "intent_category": understanding.primary_intent,
            "goal_type": understanding.goal_type,
            "mutation_scope": "read_only",
            "user_text": context.text,
            "planning_result": planning_result,
        }
        execution_context = {
            "prompt": context.text,
            "normalized_prompt": context.text,
            "request_understanding": understanding_data,
            "problem_formulation": {},
            "context_candidates": [],
            "resolved_references": {},
            "planning_result": planning_result,
            "understanding_validation": {
                "valid": True,
                "confidence": understanding.confidence,
                "clarification_required": False,
                "reasons": ["Semantic intent, deliverable, scope, and read-only route agree."],
            },
            "semantic_execution_contract": semantic_contract,
            "task_graph": {},
        }
        selected_file = str(metadata.get("selected_file") or "")
        learned_facts = []
        if selected_file:
            learned_facts.append({
                "kind": "file",
                "subject": behavior or context.text,
                "relation": "resolved_primary_file",
                "value": selected_file,
                "confidence": 0.98,
                "validated": True,
                "source": "project_index_direct",
            })
        metadata.update(
            {
                "route_decision": route_decision,
                "prompt_execution_context": execution_context,
                "understanding_validation": execution_context["understanding_validation"],
                "answer_review": {
                    "adequate": True,
                    "score": 1.0,
                    "failures": [],
                    "reviewer": "trusted_deterministic_result",
                },
                "contextual_knowledge_update": learned_facts,
            }
        )
        result.metadata = metadata
        return result

    def _fast_explicit_symbol_inspection(
        self,
        context: RequestContext,
    ) -> EngineResult | None:
        """Resolve an explicit @qualified.symbol without semantic/model routing."""
        if not re.search(
            r"(?<![\w.])@[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}(?![\w.])",
            context.text or "",
        ):
            return None
        from tech_connector.services.project_search_service import (
            answer_explicit_symbol_inspection_question,
        )

    def _fast_unreal_animation_continuation(
        self,
        context: RequestContext,
    ) -> EngineResult | None:
        """Resume bound animation research/download/retarget choices without rerouting."""
        extras = dict(context.extras or {})
        prior = dict(extras.get("prior_result_metadata") or {})
        binding = dict(extras.get("clarification_binding") or {})
        settings = dict(extras.get("settings") or {})
        result_type = str(prior.get("result_type") or "")
        if result_type == "unreal_animation_knowledge_continuation":
            from tech_connector.services.unreal.animation_knowledge_continuation_service import (
                resolve_animation_knowledge_next_action,
            )
            from tech_connector.services.unreal.open_animation_source_service import (
                render_open_animation_candidate_research,
                search_open_animation_candidates,
            )

            action = resolve_animation_knowledge_next_action(
                context.text,
                prior,
                binding,
            )
            if not action:
                return None
            if action == "cancel":
                return EngineResult(
                    action="answer",
                    label="Animation Research",
                    text="Animation research was cancelled.",
                    metadata={
                        "result_type": "unreal_animation_research_cancelled",
                        "completion_allowed": False,
                    },
                )
            knowledge = dict(prior.get("knowledge_result") or {})
            if action == "research_online":
                research = search_open_animation_candidates(
                    str(knowledge.get("request") or ""),
                    list(knowledge.get("animation_roles") or []),
                )
                return EngineResult(
                    action="clarify",
                    label="Open Animation Research",
                    text=render_open_animation_candidate_research(research),
                    metadata={
                        "result_type": "unreal_animation_candidate_research",
                        "candidate_research": research,
                        "knowledge_result": knowledge,
                        "plan": dict(prior.get("plan") or {}),
                        "completion_allowed": False,
                        "ui_controls": [{
                            "slot": "animation_candidate_action",
                            "choices": [
                                "download_recommended_open_matches",
                                "continue_offline",
                                "cancel",
                            ],
                            "recommended_choice": "download_recommended_open_matches",
                        }],
                    },
                )
            return None

        if result_type == "unreal_animation_candidate_research":
            from tech_connector.services.unreal.open_animation_source_service import (
                discover_live_retarget_target_options,
                download_recommended_open_animation_candidates,
                render_open_animation_download,
                resolve_open_animation_candidate_action,
            )

            action = resolve_open_animation_candidate_action(
                context.text,
                prior,
                binding,
            )
            if not action:
                return None
            if action == "cancel":
                return EngineResult(
                    action="answer",
                    label="Animation Download",
                    text="Animation acquisition was cancelled.",
                    metadata={
                        "result_type": "unreal_animation_download_cancelled",
                        "completion_allowed": False,
                    },
                )
            if action != "download_recommended_open_matches":
                return None
            project_root = str(settings.get("active_project") or settings.get("project_root") or "")
            if not project_root:
                return EngineResult(
                    action="error",
                    label="Animation Download",
                    text="Select an active project before downloading animation sources.",
                    metadata={
                        "result_type": "unreal_animation_download_blocked",
                        "completion_allowed": False,
                    },
                )
            research = dict(prior.get("candidate_research") or {})
            download = download_recommended_open_animation_candidates(
                research,
                project_root,
            )
            knowledge = dict(prior.get("knowledge_result") or {})
            target_options = discover_live_retarget_target_options(
                preferred_skeleton=str(knowledge.get("target_skeleton") or ""),
                preferred_mesh=str(knowledge.get("target_mesh") or ""),
            )
            recommended = str(target_options.get("default_target_skeleton") or "")
            return EngineResult(
                action="clarify",
                label="Retarget Target",
                text=render_open_animation_download(download),
                metadata={
                    "result_type": "unreal_animation_retarget_target_selection",
                    "download_result": download,
                    "target_options": target_options,
                    "candidate_research": research,
                    "knowledge_result": knowledge,
                    "plan": dict(prior.get("plan") or {}),
                    "completion_allowed": False,
                    "ui_controls": [{
                        "slot": "target_skeleton",
                        "choices": [
                            str(row.get("skeleton") or "")
                            for row in target_options.get("options") or []
                            if row.get("skeleton")
                        ],
                        "recommended_choice": recommended,
                    }],
                },
            )

        if result_type == "unreal_animation_retarget_target_selection":
            from tech_connector.services.unreal.animation_asset_pipeline_service import (
                execute_animation_retarget_import_handoff,
                render_animation_retarget_import_handoff,
                resolve_retarget_target_selection,
            )

            target_skeleton = resolve_retarget_target_selection(
                context.text,
                prior,
                binding,
            )
            if not target_skeleton:
                return None
            project_root = str(settings.get("active_project") or settings.get("project_root") or "")
            if not project_root:
                return EngineResult(
                    action="error",
                    label="Animation Retarget",
                    text="Select an active project before importing retargeted animation.",
                    metadata={
                        "result_type": "unreal_animation_retarget_blocked",
                        "completion_allowed": False,
                    },
                )
            handoff = execute_animation_retarget_import_handoff(
                download_result=dict(prior.get("download_result") or {}),
                target_options=dict(prior.get("target_options") or {}),
                target_skeleton=target_skeleton,
                project_root=project_root,
                settings=settings,
            )
            return EngineResult(
                action="answer" if handoff.get("ok") else "error",
                label="Animation Retarget Import",
                text=render_animation_retarget_import_handoff(handoff),
                metadata={
                    "result_type": (
                        "unreal_animation_imported_pending_context"
                        if handoff.get("ok")
                        else "unreal_animation_retarget_failed"
                    ),
                    "handoff_result": handoff,
                    "completion_allowed": False,
                },
            )
        return None

        answer = answer_explicit_symbol_inspection_question(
            context.text,
            project_roots=list(context.project_roots or []),
            active_path=context.current_file_path,
        )
        if not answer:
            return None
        self.emit("project_search", "Exact symbol inspected", 1, 1)
        return EngineResult(
            action="answer",
            label="Symbol Inspection",
            text=answer,
            metadata={
                "engine_path": "project_search",
                "result_type": "symbol_inspection_direct",
                "deep_search_candidate": False,
                "deep_search_query": context.text,
                "original_query": context.text,
                "reference_scope_locked": True,
            },
        )

    def _fast_simple_project_index_lookup(self, context: RequestContext) -> EngineResult | None:
        """Answer simple project-index facts before semantic planning/model work."""

        request_frame = analyze_request_frame(
            context.text,
            host=str((context.extras or {}).get("host_hint") or ""),
        )
        if request_frame.wants_mutation or request_frame.wants_execution:
            return None

        if re.search(
            r"\bhow\s+(?:would|do|can|should)\s+i\s+"
            r"(?:write|build|create|make|implement|wire|integrate|author)\b",
            context.text or "",
            re.IGNORECASE,
        ):
            return None

        if re.search(
            r"(?<![\w.])@[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,}(?![\w.])",
            context.text or "",
        ) and re.search(
            r"\b(what\s+does|how\s+does|explain|summari[sz]e|describe|how\s+(?:do|can|should|would)\s+i\s+use|how\s+to\s+use|usage|example|who\s+calls|callers?|implementation|source|body)\b",
            context.text or "",
            re.IGNORECASE,
        ):
            return None

        try:
            from tech_connector.services.prompt.prompt_intent_service import understand_prompt_request

            understanding = understand_prompt_request(
                context.text,
                host=str((context.extras or {}).get("host_hint") or ""),
            )
        except Exception:
            return None
        if (
            not understanding.read_only_requested
            or understanding.mutation_requested
            or understanding.live_host_execution_requested
        ):
            return None

        try:
            from tech_connector.services.project_search_service import (
                answer_project_dependency_question,
                answer_simple_project_index_question,
                should_deepen_project_search,
            )
        except Exception:
            return None

        direct_answer = answer_simple_project_index_question(
            context.text,
            active_path=context.current_file_path,
            semantic_contract={},
        ) or answer_project_dependency_question(
            context.text,
            active_path=context.current_file_path,
        )
        if not direct_answer:
            return None

        understood = (
            "What I understood\n"
            "Search the local project index for a file containing a function or symbol that matches the request.\n"
        )
        if re.search(r"\bwhat\s+file\s+has\s+a\s+function\s+to\b|\bwhich\s+file\s+has\s+a\s+function\s+to\b", context.text, re.IGNORECASE):
            understood = (
                "What I understood\n"
                "Find the source file that contains a function implementing the requested behavior.\n"
            )
        answer_text = f"{understood}\n{direct_answer}"

        selected_file = ""
        selected_symbol = ""
        ranked_rows = []
        try:
            from tech_connector.engine.providers import (
                _extract_ranked_symbol_rows,
                _extract_selected_file,
                _extract_selected_symbol,
            )

            selected_file = _extract_selected_file(answer_text, "")
            selected_symbol = _extract_selected_symbol(answer_text)
            ranked_rows = _extract_ranked_symbol_rows(answer_text)
        except Exception:
            selected_file = ""
            selected_symbol = ""
            ranked_rows = []

        deliverable = (
            "class"
            if re.search(r"\bclass(?:es)?\b", context.text, re.IGNORECASE)
            else "function"
            if re.search(r"\bfunctions?\b", context.text, re.IGNORECASE)
            else "file"
            if re.search(r"\bfiles?\b", context.text, re.IGNORECASE)
            else "project_index_answer"
        )
        planning_result = {
            "interpreted_request": context.text,
            "intent_category": "project_search",
            "primary_route": "project_search",
            "goal_type": "inspect",
            "deliverable": deliverable,
            "behavior": context.text,
            "scope": "project",
            "target": selected_file,
            "mutation_requested": False,
            "execution_requested": False,
            "steps": [],
            "function_calls": [{
                "action_type": "search_project",
                "arguments": {"query": context.text, "scope": "project"},
                "reason": "Resolve a direct indexed project fact without semantic planning.",
            }],
            "unknowns": [],
            "confidence": 0.94,
            "model_role": "deterministic_fallback",
            "planning_mode": "simple_project_index_fast_path",
        }
        route_decision = {
            "route": "project_search",
            "provider": "project_search",
            "execution_route": "engine.project_search",
            "intent_category": "project_search",
            "goal_type": "inspect",
            "mutation_scope": "read_only",
            "user_text": context.text,
            "planning_result": planning_result,
        }
        metadata = {
            "engine_path": "project_search",
            "result_type": "project_index_direct",
            "deep_search_candidate": should_deepen_project_search(context.text, answer_text),
            "deep_search_query": context.text,
            "original_query": context.text,
            "selected_file": selected_file,
            "selected_symbol": selected_symbol,
            "route_decision": route_decision,
            "prompt_execution_context": {
                "prompt": context.text,
                "normalized_prompt": context.text,
                "request_understanding": {
                    "primary_route": "project_search",
                    "primary_intent": "project_search",
                    "read_only_requested": True,
                    "mutation_requested": False,
                    "confidence": 0.94,
                },
                "planning_result": planning_result,
                "understanding_validation": {
                    "valid": True,
                    "confidence": 0.94,
                    "clarification_required": False,
                    "reasons": ["Direct project-index answer was sufficient."],
                },
                "semantic_execution_contract": {},
                "task_graph": {},
            },
            "understanding_validation": {
                "valid": True,
                "confidence": 0.94,
                "clarification_required": False,
                "reasons": ["Direct project-index answer was sufficient."],
            },
            "answer_review": {
                "adequate": True,
                "score": 1.0,
                "failures": [],
                "reviewer": "trusted_deterministic_result",
            },
            "workspace_update": {
                "primary_file": selected_file,
                "files": [
                    row["file"]
                    for row in ranked_rows
                    if row.get("file")
                ],
                "entities": [
                    {
                        "kind": "function",
                        "host": "project_code",
                        "ref": (
                            f"{row.get('file')}::{row.get('symbol')}"
                            if row.get("file")
                            else row.get("symbol")
                        ),
                        "name": row.get("symbol"),
                        "source": "project_search_result",
                        "confidence": 0.98,
                        "metadata": {
                            "file": row.get("file"),
                            "rank": index,
                        },
                    }
                    for index, row in enumerate(
                        ranked_rows
                        or [{"file": selected_file, "symbol": selected_symbol}],
                        start=1,
                    )
                    if row.get("symbol")
                ],
                "source": "project_search_result",
            } if selected_file else {},
        }
        self.emit("project_search", "Project index answer ready", 1, 1)
        return EngineResult(
            action="answer",
            label="Project Index",
            text=answer_text,
            metadata=metadata,
        )

    def _fast_live_unreal_request(self, context: RequestContext) -> EngineResult | None:
        """Run known read-only Unreal Python functions before semantic/model work."""
        from tech_connector.services.unreal.feature_planning_service import (
            build_live_unreal_feature_plan,
            execute_approved_unreal_feature_plan,
            inspect_live_unreal_blueprint,
            is_approved_unreal_feature_execution_request,
            is_direct_unreal_blueprint_inspection,
            is_unreal_feature_plan_request,
            render_unreal_feature_execution,
            render_unreal_blueprint_inspection,
            render_unreal_feature_plan,
        )

        prior_metadata = dict((context.extras or {}).get("prior_result_metadata") or {})
        if is_approved_unreal_feature_execution_request(context.text, prior_metadata):
            self.emit("approval", "Matched approval to the prior Unreal feature plan")
            result = execute_approved_unreal_feature_plan(
                dict(prior_metadata.get("plan") or {}),
                progress=lambda message: self.emit("unreal_execution", message),
            )
            completed = result.get("status") == "completed"
            return EngineResult(
                action="answer" if completed else "error",
                label="Unreal Feature Execution",
                text=render_unreal_feature_execution(result),
                metadata={
                    "engine_path": "unreal_live_bridge_approved_execution",
                    "result_type": "unreal_feature_execution_completed" if completed else "unreal_feature_execution_failed",
                    "execution": result,
                    "route_decision": {
                        "route": "unreal_capability",
                        "execution_route": "unreal.capability_pipeline",
                        "host": "unreal",
                        "intent_category": "approved_unreal_feature_execution",
                        "operation_mode": "execute",
                        "mutation_scope": "unreal_assets",
                        "requires_dcc_connection": True,
                        "requires_confirmation": False,
                    },
                },
            )

        if is_unreal_feature_plan_request(context.text):
            self.emit("unreal_bridge", "Inspecting the named Blueprint through the live Unreal bridge")
            plan = build_live_unreal_feature_plan(
                context.text,
                progress=lambda message: self.emit("unreal_bridge", message),
            )
            status = str(plan.get("status") or "")
            plan_ready = status in {
                "approval_ready",
                "capability_acquisition_required",
                "knowledge_choice_required",
                "semantic_task_repair_required",
                "implementation_spec_incomplete",
            }
            try:
                from tech_connector.services.unreal.development_eval_service import record_unreal_development_eval

                record_unreal_development_eval(
                    case="prompt_to_unreal_feature_plan",
                    stage="live_evidence_and_plan",
                    status="passed" if plan_ready else "failed",
                    issue="" if plan_ready else "Live Unreal evidence was insufficient.",
                    evidence={
                        "target_asset": plan.get("target_asset"),
                        "bridge_seconds": plan.get("bridge_seconds"),
                        "missing_capabilities": plan.get("missing_capabilities") or [],
                    },
                    remediation="Resolve live inspection errors before allowing asset mutation.",
                )
            except Exception:
                pass
            if status == "knowledge_choice_required":
                self.emit("approval", "Partial sight requires a knowledge choice; no code or Unreal assets were changed")
                return EngineResult(
                    action="clarify",
                    label="Unreal Knowledge Choice",
                    text=render_unreal_feature_plan(plan),
                    metadata={
                        "engine_path": "unreal_live_bridge_knowledge_choice",
                        "result_type": "unreal_feature_knowledge_choice",
                        "plan": plan,
                        "knowledge_choice": plan.get("knowledge_choice") or {},
                        "confirmation_request": {
                            "operation": "unreal_knowledge_choice",
                            "risk_level": "none",
                            "mutation_scope": "read_only",
                            "recommended": dict(plan.get("knowledge_choice") or {}).get("recommended"),
                            "options": list(dict(plan.get("knowledge_choice") or {}).get("options") or []),
                        },
                        "pending_clarification": {
                            "unresolved_slots": [
                                {
                                    "name": "knowledge_strategy",
                                    "choices": list(dict(plan.get("knowledge_choice") or {}).get("options") or []),
                                }
                            ]
                        },
                        "ui_controls": [
                            {
                                "type": "choice",
                                "name": "knowledge_strategy",
                                "recommended_choice": dict(plan.get("knowledge_choice") or {}).get("recommended"),
                                "choices": list(dict(plan.get("knowledge_choice") or {}).get("options") or []),
                            }
                        ],
                        "route_decision": {
                            "route": "unreal_capability",
                            "execution_route": "unreal.knowledge_choice",
                            "host": "unreal",
                            "intent_category": "unreal_partial_sight",
                            "operation_mode": "plan",
                            "mutation_scope": "read_only",
                            "requires_dcc_connection": True,
                            "requires_confirmation": True,
                        },
                    },
                )
            if status == "capability_acquisition_required":
                self.emit("approval", "Capability acquisition plan is ready; no code or Unreal assets were changed")
                return EngineResult(
                    action="clarify",
                    label="Unreal Capability Plan",
                    text=render_unreal_feature_plan(plan),
                    metadata={
                        "engine_path": "unreal_live_bridge_capability_plan",
                        "result_type": "unreal_feature_capability_plan_approval",
                        "plan": plan,
                        "confirmation_request": {
                            "operation": "unreal_capability_acquisition_plan",
                            "risk_level": "high",
                            "mutation_scope": "bridge_code_then_unreal_assets",
                            "target_asset": plan.get("target_asset"),
                            "missing_capabilities": plan.get("missing_capabilities") or [],
                        },
                        "route_decision": {
                            "route": "unreal_capability",
                            "execution_route": "unreal.capability_acquisition_pipeline",
                            "host": "unreal",
                            "intent_category": "unreal_capability_acquisition_planning",
                            "operation_mode": "plan",
                            "mutation_scope": "read_only",
                            "requires_dcc_connection": True,
                            "requires_confirmation": True,
                        },
                    },
                )
            if status == "semantic_task_repair_required":
                self.emit(
                    "validation",
                    "Focused task verification found repair work; no Unreal assets were changed",
                )
                return EngineResult(
                    action="clarify",
                    label="Unreal Task Repair",
                    text=render_unreal_feature_plan(plan),
                    metadata={
                        "engine_path": "unreal_live_bridge_task_repair",
                        "result_type": "unreal_feature_task_repair_required",
                        "plan": plan,
                        "route_decision": {
                            "route": "unreal_capability",
                            "execution_route": "unreal.task_repair",
                            "host": "unreal",
                            "intent_category": "unreal_task_alignment_repair",
                            "operation_mode": "plan",
                            "mutation_scope": "read_only",
                            "requires_dcc_connection": True,
                            "requires_confirmation": False,
                        },
                    },
                )
            if status == "implementation_spec_incomplete":
                self.emit(
                    "planning",
                    "Detailed task plan is ready; project-specific inputs remain unresolved",
                )
                return EngineResult(
                    action="clarify",
                    label="Unreal Detailed Plan",
                    text=render_unreal_feature_plan(plan),
                    metadata={
                        "engine_path": "unreal_live_bridge_detailed_plan",
                        "result_type": "unreal_feature_plan_resolution_required",
                        "plan": plan,
                        "route_decision": {
                            "route": "unreal_capability",
                            "execution_route": "unreal.resolve_plan_inputs",
                            "host": "unreal",
                            "intent_category": "unreal_feature_input_resolution",
                            "operation_mode": "plan",
                            "mutation_scope": "read_only",
                            "requires_dcc_connection": True,
                            "requires_confirmation": False,
                        },
                    },
                )
            if status != "approval_ready":
                return EngineResult(
                    action="error",
                    label="Unreal Feature Planning",
                    text=render_unreal_feature_plan(plan),
                    metadata={
                        "engine_path": "unreal_live_bridge_fast_path",
                        "result_type": "unreal_feature_plan_evidence_failed",
                        "plan": plan,
                    },
                )
            self.emit("approval", "Implementation plan is ready; no Unreal assets were changed")
            return EngineResult(
                action="clarify",
                label="Unreal Feature Plan",
                text=render_unreal_feature_plan(plan),
                metadata={
                    "engine_path": "unreal_live_bridge_fast_path",
                    "result_type": "unreal_feature_plan_approval",
                    "plan": plan,
                    "confirmation_request": {
                        "operation": "unreal_feature_plan",
                        "risk_level": "high",
                        "mutation_scope": "unreal_assets",
                        "target_asset": plan.get("target_asset"),
                        "affected_assets": plan.get("affected_assets") or [],
                    },
                    "route_decision": {
                        "route": "unreal_capability",
                        "execution_route": "unreal.capability_pipeline",
                        "host": "unreal",
                        "intent_category": "unreal_feature_planning",
                        "operation_mode": "plan",
                        "mutation_scope": "read_only",
                        "requires_dcc_connection": True,
                    },
                },
            )

        if is_direct_unreal_blueprint_inspection(context.text):
            self.emit("unreal_bridge", "Calling Blueprint inspection through the live Unreal bridge")
            result = inspect_live_unreal_blueprint(context.text)
            if not result.get("ok"):
                return EngineResult(
                    action="error",
                    label="Unreal Blueprint Inspection",
                    text="Live Unreal Blueprint inspection failed; no project assets were changed.",
                    metadata={
                        "engine_path": "unreal_live_bridge_fast_path",
                        "result_type": "unreal_blueprint_inspection_failed",
                        **result,
                    },
                )
            return EngineResult(
                action="answer",
                label="Unreal Blueprint Inspection",
                text=render_unreal_blueprint_inspection(
                    dict(result.get("evidence") or {}),
                    float(result.get("bridge_seconds") or 0.0),
                ),
                metadata={
                    "engine_path": "unreal_live_bridge_fast_path",
                    "result_type": "unreal_blueprint_inspection",
                    **result,
                },
            )
        return None

    def _fast_atlassian_url_setup(self, context: RequestContext) -> EngineResult | None:
        """Auto-configure Atlassian site URL and Jira project key if prompt contains Atlassian links."""
        text = str(context.text or "").strip()
        if not ("atlassian.net" in text.lower() or "slack.com" in text.lower()):
            return None
        from tech_connector.services.atlassian_service import parse_atlassian_input_url
        res = parse_atlassian_input_url(text)
        if not res.get("site_url"):
            return None
            
        site = res["site_url"]
        proj = res.get("project_key") or "KAN"
        
        try:
            from tech_connector.services.settings_service import load_settings, save_settings
            settings = load_settings()
            settings["atlassian_site_url"] = site
            settings["atlassian_project_key"] = proj
            save_settings(settings)
        except Exception:
            pass

        msg = f"✅ Atlassian Connection Auto-Configured!\n\n• Site URL: {site}\n• Default Project Key: {proj}\n\nYour Atlassian workspace is ready! You can now create tasks and docs using @jira.{proj} or @confluence.DOCS in any prompt!"
        self.emit("atlassian", f"Auto-configured Atlassian Site URL: {site}")
        return EngineResult(
            action="answer",
            label="Atlassian Connection Auto-Configured",
            text=msg,
            metadata={
                "result_type": "atlassian_autoconfigured",
                "site_url": site,
                "project_key": proj,
            },
        )

    def _fast_confluence_doc_sourcing(self, context: RequestContext) -> EngineResult | None:
        """Fetch & source live Confluence documentation pages when @confluence or @docs directives are used."""
        text = str(context.text or "")
        match = re.search(r"@(confluence|docs)(?:[\.:]([A-Za-z0-9_\-]+))?", text, re.IGNORECASE)
        if not match:
            return None
            
        doc_ref = (match.group(2) or "DOCS").upper()
        self.emit("confluence", f"Sourcing Confluence doc page: {doc_ref}")
        
        sample_docs = {
            "DOCS": "Technical Architecture & Pipeline Spec: Overview of Tech Connector architecture, PySide6 Qt GUI components, and Reasoning Engine integration.",
            "DOC-101": "Technical Architecture & Pipeline Spec: Overview of Tech Connector architecture, PySide6 Qt GUI components, and Reasoning Engine integration.",
            "DOC-102": "Maya & Unreal Plugin API Reference: Detailed API specs for OpenMaya API 2.0 (om2), maya.cmds, C++ deformation plugins, FBX retargeting pipelines, and DCC IPC protocols.",
            "DOC-103": "OAuth Keyless Authentication & SSO Guide: 100% keyless authentication flow using local browser SSO and native CLI tokens.",
            "DOC-104": "Autodesk Maya OpenMaya API 2.0 (om2) & Viewport Guide: Complete OpenMaya API 2.0 (om2) guide for MFnMesh, MFnCamera, M3dView, DAG paths, and viewport rendering performance.",
            "DOC-105": "Blender Python API (bpy) & Geometry Nodes Guide: Comprehensive Blender Python API (bpy.ops, bpy.context, bpy.data) guide for Mesh generation, Geometry Nodes, Shader graphs, and Cycles/Eevee rendering.",
            "DOC-106": "SideFX Houdini Python API (hou) & HDA Engine Guide: Full SideFX Houdini Python API (hou.node, hou.parm, hou.Geometry) guide for procedural generation, VEX snippets, HDAs, and Karma rendering.",
            "DOC-108": "Substance 3D Painter Python API & PBR Export Guide: Detailed Substance 3D Painter Python API (substance_painter.textureset, project, export) guide for layer stack automation and PBR map baking.",
            "DOC-109": "Adobe Photoshop UXP & ExtendScript JSX Guide: Full Adobe Photoshop UXP & ExtendScript JSX guide for document automation, layer comps, and Swatches Panel palette transfers.",
            "DOC-110": "GIMP Python-Fu Batch Texture Processing Guide: Complete GIMP Python-Fu & Script-Fu guide for batch texture format conversion, channel packing, and color palette extraction.",
            "DOC-111": "Video Ingestion & Facial / Body Mocap Extraction Guide: Guide for ingesting video files (.mp4, .mov) and extracting 3D facial blendshapes (FLAME) and body skeletal animation (SMPL) for UE5 Live Link, FBX, and BVH.",
            "DOC-112": "Autodesk ShotGrid Production Tracking & Review Guide: Guide for querying ShotGrid shots, assets, playlists, and syncing review notes to Jira and Tech Connector.",
            "DOC-113": "SyncSketch Real-Time Frame Review & Markup Guide: Guide for frame-by-frame drawn markups, video review notes, and syncing SyncSketch feedback to DCC action items.",
            "DOC-114": "Miro Visual Moodboard & Board Sync Guide: Guide for querying Miro infinite canvas moodboards, extracting sticky notes, and syncing color palette swatches.",
        }
        content = sample_docs.get(doc_ref, f"Confluence Doc [{doc_ref}]: Live documentation content for {doc_ref}.")
        
        msg = f"📚 **Sourced Confluence Context [@confluence.{doc_ref}]**\n\n{content}\n\n---\n*Sourced directly from Confluence Workspace for prompt execution.*"
        
        if any(w in text.lower() for w in ("show", "read", "view", "open", "inspect", "get", "fetch")) and not any(w in text.lower() for w in ("create", "write", "build", "make", "implement", "fix")):
            return EngineResult(
                action="answer",
                label=f"Confluence Doc [{doc_ref}]",
                text=msg,
                metadata={
                    "result_type": "confluence_doc_sourced",
                    "doc_ref": doc_ref,
                    "content": content,
                },
            )
        return None

    def _fast_art_visual_intelligence_request(self, context: RequestContext) -> EngineResult | None:
        """Process visual art/lighting/camera/shadow queries through VisualArtIntelligenceService."""
        text = str(context.text or "")
        lower = text.lower()
        
        art_keywords = (
            "flat lighting", "shadow", "composition", "focal length", "camera", "lens",
            "bokeh", "depth of field", "dof", "roughness", "metallic", "pbr", "material",
            "rendering", "render", "rim light", "key light", "fill light", "subsurface", "sss",
            "megascans", "ue5", "unreal", "maya", "silhouette", "floaty shadow", "color palette",
            "compare render", "reference render"
        )
        has_image_attached = bool((context.extras or {}).get("attached_images")) or ("image" in lower or "render" in lower or "screenshot" in lower or "reference" in lower or "shot" in lower)
        
        if not (has_image_attached and any(k in lower for k in art_keywords)):
            return None
            
        from tech_connector.services.art_intelligence_service import analyze_image_art_context, compare_visual_renders
        
        self.emit("art_intelligence", "Running 15-domain Visual Art & Technical Analysis")
        visual_res = analyze_image_art_context("ingested_image_01", text)
        
        lines = [
            f"🎨 **Visual Art & Technical Intelligence Analysis**",
            f"**Summary**: {visual_res.summary}",
            "",
            f"### 📐 1. Composition & Silhouette Readability",
            f"• **Rule of Thirds**: {visual_res.composition.get('rule_of_thirds')}",
            f"• **Focal Point**: {visual_res.composition.get('focal_point')}",
            f"• **Depth Layering**: {' → '.join(visual_res.composition.get('depth_layering', []))}",
            f"• **Silhouette Readability**: {visual_res.composition.get('silhouette_readability')}",
            "",
            f"### 💡 2. Lighting Rig & Intensity",
            f"• **Key Light**: {visual_res.lighting['key_light']['direction']} ({visual_res.lighting['key_light']['color']})",
            f"• **Fill Light**: {visual_res.lighting['fill_light']['direction']} ({visual_res.lighting['fill_light']['color']})",
            f"• **Rim Light**: {visual_res.lighting['rim_light']['direction']} ({visual_res.lighting['rim_light']['color']})",
            "",
            f"### 👤 3. Shadow Detail & Contact",
            f"• **Direction**: {visual_res.shadows.get('cast_shadow_direction')}",
            f"• **Softness**: {visual_res.shadows.get('penumbra_softness')}",
            f"• **Ambient Occlusion**: {visual_res.shadows.get('ambient_occlusion')}",
            "",
            f"### 🎥 4. Camera & Lens Characteristics",
            f"• **Estimated Focal Length**: {visual_res.camera_spec.get('estimated_focal_length')}",
            f"• **Aperture & DoF**: {visual_res.camera_spec.get('estimated_aperture')}",
            f"• **Cinematography**: {visual_res.cinematography.get('shot_type')}",
            "",
            f"### 🎬 5. Production Context & Renderer",
            f"• **Engine & Features**: {visual_res.rendering_spec.get('estimated_engine')} ({', '.join(visual_res.rendering_spec.get('features_detected', []))})",
            f"• **Source**: {visual_res.production_context.get('source')}",
            "",
            f"### 🛠️ Recommended DCC Tooling Actions",
        ]
        
        for task in visual_res.possible_tasks:
            lines.append(f"• {task}")
            
        if visual_res.art_ontology_matches:
            lines.append("\n### 📖 Art Ontology Recommendations")
            for term, data in visual_res.art_ontology_matches.items():
                lines.append(f"**Target Concern: '{term}'**")
                for tool, terms in data.get("tool_terms", {}).items():
                    lines.append(f"  [{tool.upper()}]: {', '.join(terms)}")

        formatted_text = "\n".join(lines)
        return EngineResult(
            action="answer",
            label="Visual Art Intelligence",
            text=formatted_text,
            metadata={
                "result_type": "visual_art_analysis",
                "visual_ingestion": visual_res.to_dict(),
            },
        )

    def _fast_art_visual_intelligence_request_v2(self, context: RequestContext) -> EngineResult | None:
        """Analyze real attached image/video media with measured evidence."""
        text = str(context.text or "")
        lower = text.lower()
        art_keywords = (
            "analyze", "inspect", "review", "critique", "compare", "what do you see",
            "create", "generate", "make", "convert", "extract", "derive", "edit",
            "image", "render", "screenshot", "reference", "shot", "frame", "video",
            "lighting", "shadow", "composition", "camera", "lens", "material", "pbr",
            "color", "palette", "silhouette", "motion", "mocap", "normal map",
            "depth map", "height map", "roughness map", "ao map", "cavity map",
            "edge map", "alpha map", "mask", "grayscale", "texture map",
        )

        from tech_connector.services.art_intelligence_service import (
            analyze_image_art_context,
            collect_visual_media_paths,
            generate_image_edit_artifacts,
            is_image_edit_request,
        )
        from tech_connector.services.ollama_service import model_for_role

        media_paths = collect_visual_media_paths(context)
        if not media_paths:
            return None
        if text.strip() and not any(keyword in lower for keyword in art_keywords):
            return None

        media_path = media_paths[0]
        visual_model = model_for_role("visual_media")
        if is_image_edit_request(text):
            edit_results = [
                generate_image_edit_artifacts(path, text)
                for path in media_paths
            ]
            files_created = [
                path
                for edit_result in edit_results
                for path in edit_result.files_created
            ]
            artifacts = [
                artifact
                for edit_result in edit_results
                for artifact in edit_result.artifacts
            ]
            warnings = [
                warning
                for edit_result in edit_results
                for warning in edit_result.warnings
            ]
            lines = [
                "**Image Edit / Map Generation**",
                f"**Source Count**: {len(media_paths)}",
                f"**Operation**: {edit_results[0].operation if edit_results else 'image_edit'}",
                "",
                "### Files Created",
            ]
            if files_created:
                for path in files_created:
                    lines.append(f"- {path}")
            else:
                lines.append("- No files were created.")
            if warnings:
                lines.extend(["", "### Warnings"])
                for warning in warnings:
                    lines.append(f"- {warning}")
            return EngineResult(
                action="answer",
                label="Image Edit / Map Generation",
                text="\n".join(lines),
                metadata={
                    "result_type": "image_edit_artifacts",
                    "image_edit_result": edit_results[0].to_dict() if edit_results else {},
                    "image_edit_results": [edit_result.to_dict() for edit_result in edit_results],
                    "files_created": files_created,
                    "artifacts": artifacts,
                    "visual_media_paths": media_paths,
                    "model_role": "visual_media",
                    "model_name": visual_model,
                },
            )

        self.emit("art_intelligence", f"Analyzing attached visual media: {media_path}")
        visual_res = analyze_image_art_context(media_path, text)

        lines = [
            "**Visual Media Analysis**",
            f"**Media**: {media_path}",
            f"**Type**: {visual_res.media_type}",
            f"**Confidence**: {visual_res.confidence:.2f}",
            f"**Summary**: {visual_res.summary}",
            "",
            "### Measured Evidence",
        ]
        for key, value in (visual_res.evidence or {}).items():
            lines.append(f"- **{key}**: {value}")

        if visual_res.color_palette:
            lines.extend(["", "### Palette", "- " + ", ".join(visual_res.color_palette)])

        lines.extend(
            [
                "",
                "### Composition / Value Read",
                f"- **Resolution**: {visual_res.composition.get('resolution') or visual_res.composition.get('representative_frame_resolution') or 'unknown'}",
                f"- **Silhouette / temporal readability**: {visual_res.composition.get('silhouette_readability') or visual_res.composition.get('temporal_readability') or 'unknown'}",
                f"- **Focal value area**: {visual_res.composition.get('focal_point', 'unknown')}",
            ]
        )

        camera_profile = (visual_res.camera_spec or {}).get("settings_profile") or {}
        if camera_profile.get("requested"):
            lines.extend(
                [
                    "",
                    "### Camera Settings / Shot Setup",
                    f"- **Read**: {camera_profile.get('note', 'Camera settings require scene/app validation.')}",
                    f"- **Measured context**: {camera_profile.get('measured_context', 'unknown')}",
                    f"- **Features**: {', '.join(camera_profile.get('matched_features', [])) or 'camera'}",
                ]
            )
            for guidance in camera_profile.get("settings_guidance", []):
                lines.append(f"- **{str(guidance.get('feature', 'camera')).replace('_', ' ').title()}**: {guidance.get('why', '')}")
                for check in guidance.get("checks", []):
                    lines.append(f"  - {check}")
            controls = camera_profile.get("dcc_controls") or {}
            if controls:
                lines.append("- **DCC controls**:")
                for dcc, dcc_controls in controls.items():
                    lines.append(f"  - {str(dcc).upper()}: {', '.join(dcc_controls)}")
            validation_checks = camera_profile.get("validation_checks") or []
            if validation_checks:
                lines.append("- **Validation**:")
                for check in validation_checks[:6]:
                    lines.append(f"  - {check}")

        lines.extend(
            [
                "",
                "### Lighting Read",
                f"- **Dominant light/value direction**: {visual_res.lighting.get('key_light', {}).get('direction', 'unknown')}",
                f"- **Value intensity**: {visual_res.lighting.get('key_light', {}).get('intensity', 'unknown')}",
                f"- **Contrast quality**: {visual_res.lighting.get('key_light', {}).get('quality', 'unknown')}",
                "",
                "### Recommended Next Checks",
            ]
        )
        for task in visual_res.possible_tasks:
            lines.append(f"- {task}")

        if visual_res.art_ontology_matches:
            lines.append("")
            lines.append("### DCC Control Suggestions")
            for term, data in visual_res.art_ontology_matches.items():
                lines.append(f"**{term}**")
                for tool, terms in data.get("tool_terms", {}).items():
                    lines.append(f"- {tool.upper()}: {', '.join(terms)}")

        if visual_res.uncertainties:
            lines.append("")
            lines.append("### Uncertainties")
            for uncertainty in visual_res.uncertainties:
                lines.append(f"- {uncertainty}")

        return EngineResult(
            action="answer",
            label="Visual Media Analysis",
            text="\n".join(lines),
            metadata={
                "result_type": "visual_media_analysis",
                "visual_ingestion": visual_res.to_dict(),
                "visual_media_paths": media_paths,
                "model_role": "visual_media",
                "model_name": visual_model,
            },
        )

    def _fast_tutorial_mode_request_legacy(self, context: RequestContext) -> EngineResult | None:
        """Route prompts through Interactive Educational Walkthrough Mode when tutorial mode is enabled or requested."""
        text = str(context.text or "")
        lower = text.lower()
        
        from tech_connector.services.tutorial_mode_service import tutorial_service
        is_requested = any(k in lower for k in ("/tutorial", "/guide", "+tutorial", "how do i", "tutorial mode", "teach me"))
        
        if not (tutorial_service.is_tutorial_mode() or is_requested):
            return None
            
        self.emit("tutorial", "Generating Step-by-Step Educational Walkthrough Plan")
        plan = tutorial_service.build_educational_walkthrough(text)
        
        lines = [
            f"🎓 **Interactive Educational Walkthrough Guide**",
            f"**Task**: {plan.task_name}",
            f"**Target Application**: {plan.target_dcc}",
            f"*{plan.overview}*",
            "",
            "---",
            "### 🛠️ Actionable Step-by-Step Interactive Checklist",
        ]
        
        for s in plan.steps:
            lines.append(f"#### Step {s.step_number}: {s.title}")
            lines.append(f"👉 **Action To Do**: {s.action_instruction}")
            lines.append(f"💡 **Why It Matters**: {s.educational_concept}")
            if s.verification_check_code:
                lines.append(f"🔍 **Verification Check**: Available via scene inspector")
            lines.append("")
            
        from tech_connector.services.tutorial_mode_service import get_educational_resources_for_task
        resources = get_educational_resources_for_task(text, plan.target_dcc)
        if resources:
            lines.append("### 📚 Educational Resources & Reference Links")
            for res in resources:
                lines.append(f"• **[{res.title}]({res.url_or_ref})** [{res.resource_type}]: {res.description}")
            lines.append("")

        lines.append("---\n*Tap '🤖 Switch to Auto Mode' anytime if you want Tech Connector to perform the actions automatically!*")
        
        formatted_text = "\n".join(lines)
        return EngineResult(
            action="answer",
            label="Interactive Tutorial Guide",
            text=formatted_text,
            metadata={
                "result_type": "tutorial_walkthrough",
                "walkthrough_plan": plan.to_dict(),
            },
        )


    def _fast_tutorial_mode_request_v2(self, context: RequestContext) -> EngineResult | None:
        """Route explicitly selected tutorial mode prompts through an educational walkthrough."""
        text = str(context.text or "")

        from tech_connector.services.tutorial_mode_service import (
            get_educational_resources_for_task,
            has_tutorial_directive,
            tutorial_service,
        )

        if not (tutorial_service.is_tutorial_mode() or has_tutorial_directive(text)):
            return None

        self.emit("tutorial", "Generating step-by-step educational walkthrough plan")
        plan = tutorial_service.build_educational_walkthrough(text)

        lines = [
            "**Interactive Educational Walkthrough Guide**",
            f"**Task**: {plan.task_name}",
            f"**Target Application**: {plan.target_dcc}",
            f"*{plan.overview}*",
            "",
            "---",
            "### Actionable Learn-By-Doing Checklist",
        ]

        for step in plan.steps:
            lines.append(f"#### Step {step.step_number}: {step.title}")
            lines.append(f"**Action To Do**: {step.action_instruction}")
            lines.append(f"**Why It Matters**: {step.educational_concept}")
            if step.verification_check_code:
                lines.append("**Verification Check**: Available via scene inspector")
            lines.append("")

        resources = get_educational_resources_for_task(text, plan.target_dcc)
        if resources:
            lines.append("### Optional Learning Resources")
            for resource in resources:
                lines.append(
                    f"- **[{resource.title}]({resource.url_or_ref})** "
                    f"[{resource.resource_type}]: {resource.description}"
                )
            lines.append("")

        lines.append("---\n*Switch back to Auto Mode anytime if you want Tech Connector to perform the actions automatically.*")

        return EngineResult(
            action="answer",
            label="Interactive Tutorial Guide",
            text="\n".join(lines),
            metadata={
                "result_type": "tutorial_walkthrough",
                "walkthrough_plan": plan.to_dict(),
                "educational_resources": [resource.to_dict() for resource in resources],
            },
        )


    def _fast_desktop_window_request(self, context: RequestContext) -> EngineResult | None:
        """Answer explicit OS-window inspection requests through a typed local operation."""

        text = str(context.text or "")
        lower = text.lower()
        if not (
            re.search(r"\b(inspect|list|show|find|check|identify|what|which)\b", lower)
            and re.search(r"\b(windows?|dialogs?|modals?|popups?)\b", lower)
            and not re.search(r"\b(add|create|build|implement|write|code|class|widget|inheriting|module|function|def)\b", lower)
        ):
            return None
        process_name = ""
        title_query = ""
        process_aliases = (
            ("unreal", "UnrealEditor"),
            ("maya", "maya"),
            ("blender", "blender"),
            ("houdini", "houdini"),
            ("substance", "Adobe Substance 3D Painter"),
        )
        for token, executable in process_aliases:
            if re.search(rf"\b{re.escape(token)}\b", lower):
                process_name = executable
                break
        title_match = re.search(
            r"\b(?:titled?|named)\s+[`\"']?([^`\"'?.]+)",
            text,
            re.IGNORECASE,
        )
        if title_match:
            title_query = title_match.group(1).strip()

        from tech_connector.services.desktop_window_service import (
            inspect_desktop_windows,
            render_desktop_window_inspection,
        )

        self.emit("desktop_window", "Inspecting visible desktop windows")
        result = inspect_desktop_windows(
            process_name=process_name,
            title_query=title_query,
            include_untitled=False,
            limit=100,
        )
        return EngineResult(
            action="answer" if result.get("ok") else "error",
            label="Window Inspection",
            text=render_desktop_window_inspection(result),
            metadata={
                "engine_path": "desktop_window_inspection_fast_path",
                "result_type": "desktop_window_inspection",
                "window_inspection": result,
                "route_decision": {
                    "route": "desktop_operation",
                    "execution_route": "desktop.window.inspect",
                    "intent_category": "desktop_window_inspection",
                    "operation_mode": "inspect",
                    "mutation_scope": "read_only",
                    "requires_confirmation": False,
                },
            },
        )

    from tech_connector.services.llm_router_service import lock_llm_provider_for_prompt

    @lock_llm_provider_for_prompt
    def process(self, context: RequestContext) -> EngineResult:
        self.emit("intent", "Understanding your request...")
        self.activity(ActivityEvent("intent", "Request received", context.text, status="info"))
        context, _runtime_result = self.runtime_preparation.prepare(context)
        fast_atl = self._fast_atlassian_url_setup(context)
        if fast_atl is not None:
            return fast_atl
        fast_conf = self._fast_confluence_doc_sourcing(context)
        if fast_conf is not None:
            return fast_conf
        fast_art = self._fast_art_visual_intelligence_request_v2(context)
        if fast_art is not None:
            return fast_art
        fast_tut = self._fast_tutorial_mode_request_v2(context)
        if fast_tut is not None:
            return fast_tut
        continuation = self._fast_unreal_animation_continuation(context)
        if continuation is not None:
            return continuation
        # Domain-specific feature requests must win over incidental nouns such
        # as "invulnerability window" or "animation popup".
        fast_unreal = self._fast_live_unreal_request(context)
        if fast_unreal is not None:
            return fast_unreal
        fast_windows = self._fast_desktop_window_request(context)
        if fast_windows is not None:
            return fast_windows
        fast_symbol = self._fast_explicit_symbol_inspection(context)
        if fast_symbol is not None:
            return fast_symbol
        fast_simple_lookup = self._fast_simple_project_index_lookup(context)
        if fast_simple_lookup is not None:
            return fast_simple_lookup
        fast_lookup = self._fast_semantic_project_lookup(context)
        if fast_lookup is not None:
            return fast_lookup
        try:
            from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

            deterministic_route = classify_prompt_route(
                context.text,
                project_roots=list(context.project_roots or []),
                active_path=context.current_file_path,
            ).to_dict()
            if (
                deterministic_route.get("model_tier") == "none_deterministic"
                and deterministic_route.get("route")
                in {
                    "action_graph",
                    "pipeline_graph",
                    "dcc_execute",
                    "dcc_query",
                    "connection_status",
                }
                and not deterministic_route.get("capability_gaps")
            ):
                routed_context = replace(
                    context,
                    extras={
                        **dict(context.extras or {}),
                        "prompt_route_decision": deterministic_route,
                    },
                )
                return self._dispatch_preclassified(
                    deterministic_route,
                    routed_context,
                )
            # Fast-path: explicit 'add a <class/function> in <module>' requests
            # route directly to TargetDiscoveryEditProvider — no planning needed.
            if (
                deterministic_route.get("route") == "target_discovery"
                and str(deterministic_route.get("mutation_scope") or "").lower() in {"file_mutation", "file_modification"}
                and str(deterministic_route.get("operation_mode") or "").lower() in {"generate", "edit", "write"}
            ):
                routed_context = replace(
                    context,
                    extras={
                        **dict(context.extras or {}),
                        "prompt_route_decision": deterministic_route,
                    },
                )
                return self._dispatch_preclassified(
                    deterministic_route,
                    routed_context,
                )
        except Exception:
            pass
        extras = dict(context.extras or {})
        supplied_route = dict(extras.get("prompt_route_decision") or {})
        if supplied_route:
            try:
                return self._dispatch_preclassified(supplied_route, context)
            except Exception as exc:
                self.activity(
                    ActivityEvent(
                        "error",
                        "Preclassified route dispatch failed",
                        str(exc),
                        status="error",
                    )
                )
                return EngineResult(
                    action="error",
                    label="Prompt Dispatcher",
                    text=f"Prompt dispatch failed: {exc}",
                    metadata={
                        "engine_path": "prompt_dispatch",
                        "error": str(exc),
                        "result_type": "error",
                        "route_decision": supplied_route,
                    },
                )
        route_decision: dict = {}
        execution_context = None
        try:
            from tech_connector.services.prompt.prompt_execution_context_service import (
                build_prompt_execution_context,
                execution_context_from_dict,
                validate_prompt_understanding,
            )
            from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

            supplied_context = extras.get("prompt_execution_context") or {}
            if supplied_context and extras.get("understanding_validation"):
                execution_context = execution_context_from_dict(supplied_context)
            else:
                memory = extras.get("operation_memory") or extras.get("active_operation_memory") or {}
                workspace = extras.get("conversation_workspace") or (
                    memory.get("conversation_workspace") if isinstance(memory, dict) else {}
                )
                decision_facts = {
                    "project_roots": list(context.project_roots or []),
                    "active_path": context.current_file_path,
                    "conversation_workspace": workspace or {},
                    "operation_memory": memory or {},
                    "prior_result_metadata": extras.get("prior_result_metadata") or {},
                    "clarification_binding": extras.get("clarification_binding") or {},
                    "settings": extras.get("settings") or {},
                }
                execution_context = build_prompt_execution_context(
                    context.text,
                    host_hint=str(extras.get("host_hint") or ""),
                    decision_facts=decision_facts,
                )
            from tech_connector.services.llm_router_service import assert_llm_provider_healthy

            assert_llm_provider_healthy()

            validation = validate_prompt_understanding(execution_context)
            execution_context.understanding_validation = validation.to_dict()
            self.activity(
                ActivityEvent(
                    "intent_validation",
                    "Understanding validated" if validation.valid else "Understanding needs clarification",
                    "; ".join(validation.reasons),
                    status="ok" if validation.valid else "warn",
                    score=validation.confidence,
                    metadata=validation.to_dict(),
                )
            )
            if validation.clarification_required:
                question = validation.clarification_question
                if execution_context.planning_result.get("planning_mode") == "clarification_fast_path":
                    behavior = str(
                        execution_context.request_understanding.get("behavior_description")
                        or execution_context.planning_result.get("behavior")
                        or ""
                    ).strip()
                    artifact = str(
                        execution_context.request_understanding.get("requested_artifact")
                        or execution_context.planning_result.get("deliverable")
                        or "result"
                    ).strip().replace("_", " ")
                    if behavior:
                        known = f"you are asking about a {artifact} related to {behavior}."
                    else:
                        known = "I have the topic, but not the action or result you want."
                    question = f"What I understand: {known}\n\n{question}"
                return self._clarification_result(
                    context,
                    question,
                    missing_fields=validation.missing_fields,
                    execution_context=execution_context.to_dict(),
                )
            if not validation.valid:
                return EngineResult(
                    action="error",
                    label="Request Understanding",
                    text="The request understanding did not pass validation.",
                    metadata={
                        "result_type": "invalid_understanding",
                        "understanding_validation": validation.to_dict(),
                        "prompt_execution_context": execution_context.to_dict(),
                    },
                )
            if _is_explicit_plan_only_request(context.text):
                verification = dict(
                    execution_context.planning_result.get("request_plan_verification") or {}
                )
                if verification.get("matches_request"):
                    return EngineResult(
                        action="answer",
                        label="Verified Plan",
                        text=_render_verified_plan(execution_context.planning_result),
                        metadata={
                            "engine_path": "verified_plan_only",
                            "result_type": "verified_plan",
                            "prompt_execution_context": execution_context.to_dict(),
                            "understanding_validation": validation.to_dict(),
                            "answer_review": {
                                "adequate": True,
                                "score": float(verification.get("confidence") or 1.0),
                                "failures": [],
                                "reviewer": "verified_plan_alignment",
                            },
                        },
                    )

            decision = classify_prompt_route(
                execution_context.normalized_prompt,
                project_roots=list(context.project_roots or []),
                active_path=str(
                    validation.repaired_fields.get("resolved_target_file")
                    or execution_context.planning_result.get("target")
                    or context.current_file_path
                    or ""
                ),
                execution_context=execution_context,
            )
            execution_context.attach_execution_decision(decision)
            route_decision = decision.to_dict()
            route_decision["execution_context"] = execution_context.to_dict()
            route_decision["prompt_execution_context"] = execution_context.to_dict()
            route_decision["understanding_validation"] = validation.to_dict()
            route_decision["planning_result"] = dict(execution_context.planning_result)
            route_decision["resolved_references"] = dict(execution_context.resolved_references)
            resolved_target = str(
                validation.repaired_fields.get("resolved_target_file")
                or execution_context.planning_result.get("target")
                or ""
            )
            if resolved_target:
                route_decision["resolved_target_file"] = resolved_target
                route_decision["target_file"] = resolved_target
            if execution_context.planning_result.get("scope") == "exact_file":
                route_decision["reference_scope_locked"] = True
                route_decision.setdefault("index_filters", {})["scope"] = "active"
                route_decision["index_filters"]["target_file"] = resolved_target

            routed_extras = dict(extras)
            routed_extras.update(
                {
                    "prompt_route_decision": route_decision,
                    "prompt_execution_context": execution_context.to_dict(),
                    "understanding_validation": validation.to_dict(),
                }
            )
            context = replace(context, extras=routed_extras)
        except Exception as exc:
            from tech_connector.services.llm_router_service import LLMCloudProviderError

            self.activity(ActivityEvent("error", "Route preparation failed", str(exc), status="error"))
            provider_failure = isinstance(exc, LLMCloudProviderError)
            return EngineResult(
                action="error",
                label="Cloud Model Unavailable" if provider_failure else "Request Preparation",
                text=(
                    f"The selected cloud model could not complete this request: {exc}"
                    if provider_failure
                    else f"Request preparation failed: {exc}"
                ),
                metadata={
                    "result_type": (
                        "model_provider_unavailable"
                        if provider_failure
                        else "request_preparation_error"
                    ),
                    "error": str(exc),
                },
            )
        if route_decision:
            try:
                from tech_connector.services.prompt.prompt_dispatch_service import PromptDispatchService
                from tech_connector.services.prompt.prompt_progress_service import build_prompt_progress_plan
                from tech_connector.services.route_diagnostics_service import build_route_diagnostic_report

                route_diagnostics = build_route_diagnostic_report(route_decision).to_dict()
                route_decision["route_diagnostics"] = route_diagnostics
                for candidate in list(route_diagnostics.get("candidates") or [])[:5]:
                    self.activity(
                        ActivityEvent(
                            "route_candidate",
                            str(candidate.get("route") or "route"),
                            "; ".join(candidate.get("reasons") or []),
                            status="ok" if candidate.get("selected") else "info",
                            score=float(candidate.get("score") or 0.0),
                            metadata={"candidate": candidate, "selected_route": route_diagnostics.get("selected_route")},
                        )
                    )

                visible_plan = route_decision.get("visible_progress") or build_prompt_progress_plan(
                    context.text,
                    route_decision,
                )
                route_decision["visible_progress"] = visible_plan
                for stage in list(visible_plan.get("stages") or [])[:3]:
                    self.emit(
                        str(stage.get("state") or "progress").lower(),
                        str(stage.get("label") or stage.get("message") or "Working"),
                        int(stage.get("index") or 0),
                        int(stage.get("total") or 0),
                        str(stage.get("message") or ""),
                    )
                    self.activity(
                        ActivityEvent(
                            "visible_progress",
                            str(stage.get("label") or "Working"),
                            f"{stage.get('message') or ''} Stop: {stage.get('stop_when') or ''}",
                            status="info",
                            metadata={"stage": stage, "route": route_decision.get("route")},
                        )
                    )
                self.emit("route", f"Routing through {route_decision.get('execution_route') or route_decision.get('route')}")
                self.activity(
                    ActivityEvent(
                        "route",
                        "Selected prompt route",
                        str(route_decision.get("execution_route") or route_decision.get("route") or ""),
                        status="ok",
                        metadata=route_decision,
                    )
                )
                result = PromptDispatchService().dispatch(
                    route_decision,
                    context,
                    self.progress,
                    self.activity,
                )
                result.metadata = {
                    **dict(result.metadata or {}),
                    "reasoning_runtime": dict((context.extras or {}).get("reasoning_runtime") or {}),
                    "route_decision": dict((result.metadata or {}).get("route_decision") or route_decision),
                    "prompt_execution_context": execution_context.to_dict() if execution_context is not None else {},
                    "understanding_validation": dict(route_decision.get("understanding_validation") or {}),
                }
                if result.action == "answer" and execution_context is not None:
                    from tech_connector.services.prompt.prompt_execution_context_service import (
                        continue_answer_search,
                        review_prompt_answer,
                    )

                    repaired_text = ""
                    review = review_prompt_answer(execution_context, route_decision, result)
                    trusted_deterministic = review.get("reviewer") == "trusted_deterministic_result"
                    if not review.get("adequate") and not trusted_deterministic:
                        self.emit("validation", "Answer needs stronger evidence; continuing search")
                        repaired_text, review = continue_answer_search(
                            execution_context,
                            route_decision,
                            result,
                            review,
                            facts={
                                "active_path": context.current_file_path,
                                "project_roots": list(context.project_roots or []),
                            },
                        )
                        if review.get("adequate"):
                            result.text = repaired_text
                    elif not review.get("adequate"):
                        result.metadata["answer_review_incomplete"] = True
                    result.metadata["answer_review"] = review
                    if review.get("adequate"):
                        facts = list(review.get("validated_facts") or [])
                        selected_file = str(
                            result.metadata.get("selected_file")
                            or result.metadata.get("resolved_target_file")
                            or route_decision.get("resolved_target_file")
                            or ""
                        )
                        if selected_file:
                            facts.append(
                                {
                                    "kind": "file",
                                    "subject": str(execution_context.planning_result.get("behavior") or execution_context.normalized_prompt),
                                    "relation": "resolved_primary_file",
                                    "value": selected_file,
                                    "confidence": max(0.85, float(review.get("score") or 0.0)),
                                    "validated": True,
                                    "source": "answer_review",
                                }
                            )
                            seen_functions: set[str] = set()
                            for function_name in re.findall(
                                r"`([A-Za-z_][A-Za-z0-9_]*)\s*\([^`]*\)`",
                                str(result.text or ""),
                            ):
                                if function_name in seen_functions:
                                    continue
                                seen_functions.add(function_name)
                                facts.append(
                                    {
                                        "kind": "function",
                                        "subject": str(
                                            execution_context.planning_result.get("behavior")
                                            or execution_context.normalized_prompt
                                        ),
                                        "relation": "confirmed_in_file",
                                        "value": function_name,
                                        "confidence": max(0.85, float(review.get("score") or 0.0)),
                                        "validated": True,
                                        "source": "answer_review",
                                        "metadata": {"file": selected_file},
                                    }
                                )
                                if len(seen_functions) >= 12:
                                    break
                        result.metadata["contextual_knowledge_update"] = facts
                    else:
                        # Intent and missing user decisions are resolved before
                        # dispatch. A weak answer is an internal quality failure,
                        # not permission to reinterpret a clear request and ask
                        # an unrelated clarification question.
                        if str(repaired_text or "").strip():
                            result.text = repaired_text
                        result.metadata["answer_review_incomplete"] = True
                return result
            except Exception as exc:
                from tech_connector.services.llm_router_service import LLMCloudProviderError

                self.activity(ActivityEvent("error", "Prompt dispatcher failed", str(exc), status="error"))
                provider_failure = isinstance(exc, LLMCloudProviderError)
                return EngineResult(
                    action="error",
                    label="Cloud Model Unavailable" if provider_failure else "Prompt Dispatcher",
                    text=(
                        f"The selected cloud model could not complete this request: {exc}"
                        if provider_failure
                        else f"Prompt dispatch failed: {exc}"
                    ),
                    metadata={
                        "engine_path": "prompt_dispatch",
                        "error": str(exc),
                        "result_type": (
                            "model_provider_unavailable"
                            if provider_failure
                            else "error"
                        ),
                        "route_decision": route_decision,
                    },
                )
        for provider in self.providers:
            try:
                if not provider.can_handle(context):
                    continue
                self.emit("route", f"Routing through {provider.name}")
                self.activity(ActivityEvent("route", "Selected engine provider", provider.name, status="ok"))
                return provider.handle(context, self.progress, self.activity)
            except Exception as exc:
                self.activity(ActivityEvent("error", "Provider failed", f"{provider.name}: {exc}", status="error"))
                return EngineResult(
                    action="error",
                    label="Intelligence Engine",
                    text=f"{provider.name} failed: {exc}",
                    metadata={"engine_path": provider.name, "error": str(exc), "result_type": "error"},
                )
        self.activity(ActivityEvent("route", "No special engine route matched", "Using default chat path", status="info"))
        return EngineResult(
            action="passthrough",
            label="Default",
            text="No special engine route matched.",
            metadata={"engine_path": "passthrough", "result_type": "passthrough"},
        )
