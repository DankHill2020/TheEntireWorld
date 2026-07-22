"""The Entire World Intelligence Engine."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Callable, Iterable

from .progress_events import ActivityEvent, EngineResult, ProgressEvent
from .request_context import RequestContext
from .providers import ProjectSearchProvider, RequestProvider, default_providers

ProgressCallback = Callable[[ProgressEvent], None]
ActivityCallback = Callable[[ActivityEvent], None]


class RequestEngine:
    """Route a request through deterministic, non-UI-thread preparation."""

    def __init__(
        self,
        progress: ProgressCallback | None = None,
        activity: ActivityCallback | None = None,
        providers: Iterable[RequestProvider] | None = None,
    ):
        self.progress = progress or (lambda _event: None)
        self.activity = activity or (lambda _event: None)
        self.providers = list(providers or default_providers())

    def emit(self, stage: str, message: str, current: int = 0, total: int = 0, detail: str = "") -> None:
        self.progress(ProgressEvent(stage=stage, message=message, current=current, total=total, detail=detail))

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
            from tech_connector.services.prompt_intent_service import understand_prompt_request

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
                from tech_connector.services.semantic_execution_contract_service import (
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

    def _fast_simple_project_index_lookup(self, context: RequestContext) -> EngineResult | None:
        """Answer simple project-index facts before semantic planning/model work."""

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
            from tech_connector.services.prompt_intent_service import understand_prompt_request

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
        try:
            from tech_connector.engine.providers import _extract_selected_file

            selected_file = _extract_selected_file(answer_text, "")
        except Exception:
            selected_file = ""

        planning_result = {
            "interpreted_request": context.text,
            "intent_category": "project_search",
            "primary_route": "project_search",
            "goal_type": "inspect",
            "deliverable": "project_index_answer",
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
                "source": "project_search_result",
            } if selected_file else {},
        }
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
                        "requires_confirmation": True,
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

    def _fast_desktop_window_request(self, context: RequestContext) -> EngineResult | None:
        """Answer explicit OS-window inspection requests through a typed local operation."""

        text = str(context.text or "")
        lower = text.lower()
        if not (
            re.search(r"\b(inspect|list|show|find|check|identify|what|which)\b", lower)
            and re.search(r"\b(windows?|dialogs?|modals?|popups?)\b", lower)
            and not re.search(r"\b(create|build|implement|code|class|widget)\b", lower)
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

    def process(self, context: RequestContext) -> EngineResult:
        self.emit("intent", "Understanding your request...")
        self.activity(ActivityEvent("intent", "Request received", context.text, status="info"))
        # Domain-specific feature requests must win over incidental nouns such
        # as "invulnerability window" or "animation popup".
        fast_unreal = self._fast_live_unreal_request(context)
        if fast_unreal is not None:
            return fast_unreal
        fast_windows = self._fast_desktop_window_request(context)
        if fast_windows is not None:
            return fast_windows
        fast_simple_lookup = self._fast_simple_project_index_lookup(context)
        if fast_simple_lookup is not None:
            return fast_simple_lookup
        fast_lookup = self._fast_semantic_project_lookup(context)
        if fast_lookup is not None:
            return fast_lookup
        extras = dict(context.extras or {})
        route_decision: dict = {}
        execution_context = None
        try:
            from tech_connector.services.prompt_execution_context_service import (
                build_prompt_execution_context,
                execution_context_from_dict,
                validate_prompt_understanding,
            )
            from tech_connector.services.prompt_route_service import classify_prompt_route

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
            self.activity(ActivityEvent("error", "Route preparation failed", str(exc), status="error"))
            return EngineResult(
                action="error",
                label="Request Preparation",
                text=f"Request preparation failed: {exc}",
                metadata={"result_type": "request_preparation_error", "error": str(exc)},
            )
        if route_decision:
            try:
                from tech_connector.services.prompt_dispatch_service import PromptDispatchService
                from tech_connector.services.prompt_progress_service import build_prompt_progress_plan
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
                    "route_decision": dict((result.metadata or {}).get("route_decision") or route_decision),
                    "prompt_execution_context": execution_context.to_dict() if execution_context is not None else {},
                    "understanding_validation": dict(route_decision.get("understanding_validation") or {}),
                }
                if result.action == "answer" and execution_context is not None:
                    from tech_connector.services.prompt_execution_context_service import (
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
                self.activity(ActivityEvent("error", "Prompt dispatcher failed", str(exc), status="error"))
                return EngineResult(
                    action="error",
                    label="Prompt Dispatcher",
                    text=f"Prompt dispatch failed: {exc}",
                    metadata={"engine_path": "prompt_dispatch", "error": str(exc), "result_type": "error", "route_decision": route_decision},
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
