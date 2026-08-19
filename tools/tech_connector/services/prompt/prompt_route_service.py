"""Deterministic prompt route classification for chat requests."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


ENGINE_PROVIDERS = {"action_graph", "connection_status", "project_health", "target_discovery", "project_search", "import_coverage"}

HOST_ALIASES = {
    "maya": ("maya", "mayya"),
    "unreal": ("unreal", "ue5", "ue4", "unrel"),
    "blender": ("blender",),
    "substance_painter": ("substance painter", "substance", "painter"),
    "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
    "unity": ("unity",),
    "houdini": ("houdini", "hou", "hip"),
}

IMPLICIT_HOST_PATTERNS = {
    "unreal": re.compile(
        r"\b(?:niagara|anim\s*blueprint|anim\s*bp|metahuman|control\s*rig|blueprint\s+variables?)\b",
        re.IGNORECASE,
    ),
}

from tech_connector.services.prompt.prompt_route_rules import (
    PromptRouteDecision,
    _word_in,
    _detect_host,
    _detect_hosts,
    _goal,
    _goal_graph,
    _dcc_operation_task_graph,
    _gameplay_feature_task_graph,
    _dcc_tool_task_graph,
    _read_only_review_task_graph,
    _maya_create_locator_then_move_decision,
    _maya_to_unreal_fbx_pipeline_decision,
    _extract_maya_root_joint,
    _module_path_from_file,
    _find_function_node,
    _required_args_from_function,
    _returned_names_from_function,
    _producer_score_for_args,
    _discover_callable_prerequisite_chain,
    _maya_create_rig_from_current_scene_decision,
    _has_file_ref,
    _extract_explicit_scope_path,
    _is_unimported_files_query,
    _callable_after_execution_verb,
    _explicit_source_file_references,
    _is_explicit_source_code_mutation,
    _route_candidate_diagnostics,
    _rank_route_candidates_with_fnn,
    _looks_like_read_only_project_question,
    _is_connection_status_question,
    _is_simple_project_fact_question,
    _has_explicit_dcc_mutation,
    _has_explicit_dcc_operation,
    _simple_project_fact_progress,
    _is_unreal_live_query,
    _known_unreal_operation_from_text,
    _has_no_execute_guard,
    _is_scoped_project_guidance_request,
    _detect_compound_kind,
    _compound_operations,
    _is_generated_maya_rig_control_post_action,
    _is_unreal_graph_operation_planning_request,
    _maya_rigging_prerequisite_decision,
    decision_requires_live_dcc,
    decision_is_project_only,
    _finalize_decision,
    _is_vague_senior_improvement,
    _normalize_prompt_for_routing,
    _is_unreal_animation_blueprint_feature_request,
    _is_explicit_pipeline_build_request,
    _has_host_handoff_language,
    _read_only_host_code_query_decision,
    _looks_like_staged_long_contract,
    _evaluate_semantic_dcc_capabilities,
    classify_prompt_intent_from_understanding,
)

def classify_prompt_route(
    prompt: str,
    *,
    project_roots: list[str] | None = None,
    active_path: str | None = None,
    execution_context: dict[str, Any] | Any | None = None,
    request_understanding: Any | None = None,
    task_graph: dict[str, Any] | None = None,
) -> PromptRouteDecision:
    """Return the intended route without performing model, filesystem, DCC, or broad index work."""
    raw_text = prompt or ""
    text = re.sub(r"\s+", " ", raw_text).strip()
    lower = _normalize_prompt_for_routing(text.lower())
    roots = project_roots or []
    host = _detect_host(text)
    hosts = _detect_hosts(text)
    no_execute = _has_no_execute_guard(lower)

    if (
        _is_unreal_animation_blueprint_feature_request(lower)
        and not _is_explicit_pipeline_build_request(lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            target_identifier="animation_blueprint.feature_request",
            operation_mode="plan_or_execute",
            mutation_scope="dcc_scene_mutation",
            confidence=0.86,
            requires_confirmation=not no_execute,
            requires_dcc_connection=not no_execute,
            requires_plan=True,
            required_context=[
                "unreal_reflection_index",
                "capability_graph",
                "animation_blueprint_context",
                "argument_validation",
            ],
            model_tier="local_code",
            task_graph=_gameplay_feature_task_graph(text, read_only=no_execute),
            reasons=[
                "Prompt references an Unreal animation blueprint/ABP workflow even without explicitly naming Unreal.",
                "Animation blueprint feature requests should use Unreal capability planning before mutation.",
            ],
            alternatives=[
                {"route": "target_discovery", "reason": "Use if the user meant local code edits rather than live Unreal asset work."},
            ],
        ), lower)

    try:
        from tech_connector.services.prompt.prompt_intent_service import (
            RequestTask,
            RequestUnderstanding,
            understand_prompt_request_deterministic,
        )
        from tech_connector.services.prompt.prompt_task_splitter_service import (
            build_request_task_graph,
            task_graph_route,
        )

        # Routing consumes one already-built canonical context. Compatibility
        # callers receive a bounded deterministic understanding and task graph;
        # semantic/model planning remains owned by the request engine.
        if execution_context is None and _is_connection_status_question(lower):
            raise ValueError("Deterministic connection status does not require canonical context")
        if execution_context is None and len(text) > 1200:
            # Long contracts are staged in a background planner. Building the
            # full canonical package here duplicates the prompt across nested
            # graphs and blocks the foreground routing/UI path.
            raise ValueError("Deferred canonical context for staged long prompt")
        if execution_context is None:
            deterministic_understanding = understand_prompt_request_deterministic(
                text,
                host=host,
            )
            deterministic_task_graph = build_request_task_graph(
                text,
                host=host,
                understanding=deterministic_understanding,
            )
            execution_context = {
                "request_understanding": deterministic_understanding.to_dict(),
                "task_graph": deterministic_task_graph,
            }
        context_data = (
            execution_context.to_dict()
            if hasattr(execution_context, "to_dict")
            else dict(execution_context or {})
        )

        supplied_understanding = (
            request_understanding
            or context_data.get("request_understanding")
        )
        if isinstance(supplied_understanding, dict):
            understanding_data = dict(supplied_understanding)
            task_rows = list(
                understanding_data.pop("tasks", [])
                or understanding_data.pop("goals", [])
                or []
            )
            understanding_data.pop("goals", None)
            restored_tasks = []
            for row in task_rows:
                item = dict(row or {})
                item.pop("goal_id", None)
                restored_tasks.append(RequestTask(**item))
            request_understanding = RequestUnderstanding(
                **{**understanding_data, "tasks": restored_tasks}
            )
        elif supplied_understanding is not None:
            request_understanding = supplied_understanding
        else:
            raise ValueError("Canonical execution context is missing request understanding")

        phrase_intent = classify_prompt_intent_from_understanding(
            request_understanding,
            text,
            host=host,
        )

        goal_graph = dict(
            task_graph
            or context_data.get("task_graph")
            or context_data.get("goal_graph")
            or {}
        )
        if not goal_graph:
            raise ValueError("Canonical execution context is missing goal graph")
        task_graph = goal_graph
        semantic_route = task_graph_route(task_graph)

        primary_goal = str(
            goal_graph.get("primary_goal")
            or request_understanding.primary_goal
            or request_understanding.normalized_goal
            or ""
        )
        goal_type = str(
            goal_graph.get("goal_type")
            or request_understanding.goal_type
            or ""
        ).lower()
        goal_count = len(goal_graph.get("goals") or goal_graph.get("tasks") or [])
        estimated_steps = int(
            goal_graph.get("estimated_steps")
            or request_understanding.estimated_steps
            or goal_count
            or 0
        )
        requires_project_search = bool(
            goal_graph.get("requires_project_search")
            or request_understanding.requires_project_search
        )
        requires_generation = bool(
            goal_graph.get("requires_generation")
            or request_understanding.requires_generation
        )
        requires_execution = bool(
            goal_graph.get("requires_execution")
            or request_understanding.requires_execution
        )
        requires_validation = bool(
            goal_graph.get("requires_validation")
            or request_understanding.requires_validation
        )
        semantic_execution_contract = dict(
            context_data.get("semantic_execution_contract")
            or context_data.get("semantic_contract")
            or goal_graph.get("semantic_execution_contract")
            or {}
        )
        canonical_reasoning_pipeline = dict(
            context_data.get("reasoning_pipeline") or {}
        )
        canonical_visible_progress = dict(
            context_data.get("visible_progress") or {}
        )
        if _is_scoped_project_guidance_request(lower):
            return _finalize_with_context(PromptRouteDecision(
                route="project_search",
                provider="project_search",
                intent_category="code_generation_guidance",
                host="",
                confidence=0.88,
                operation_mode="query",
                mutation_scope="read_only",
                required_context=["project_index", "symbol_index", "scoped_file_context"],
                model_tier="none_deterministic",
                reasons=["Prompt asks for a scoped code example/guidance and explicitly avoids mutation."],
                rejected_routes=["unreal_capability", "dcc_execute", "target_discovery"],
            ))
    except Exception:
        context_data = {}
        phrase_intent = None
        request_understanding = None
        task_graph = {}
        goal_graph = {}
        semantic_route = ""
        primary_goal = ""
        goal_type = ""
        goal_count = 0
        estimated_steps = 0
        requires_project_search = False
        requires_generation = False
        requires_execution = False
        requires_validation = False
        semantic_execution_contract = {}
        canonical_reasoning_pipeline = {}
        canonical_visible_progress = {}

    route_candidates, fnn_route_scoring = _rank_route_candidates_with_fnn(
        text,
        _route_candidate_diagnostics(text, lower, host=host, hosts=hosts),
        host=host,
        hosts=hosts,
    )
    explicit_scope_path = _extract_explicit_scope_path(text)

    # Import coverage is structural dependency analysis, not semantic behavior
    # search. It must override a stale or overly generic canonical goal graph.
    authoritative_import_coverage = _is_unimported_files_query(text)

    def _finalize_with_context(decision: PromptRouteDecision, *_ignored) -> PromptRouteDecision:
        """Attach the canonical understanding package before execution routing."""
        if not decision.route_candidates:
            decision.route_candidates = [dict(item) for item in route_candidates]
        if fnn_route_scoring:
            decision.reasoning_pipeline = {
                **dict(decision.reasoning_pipeline or {}),
                "fnn_route_scoring": dict(fnn_route_scoring),
            }
            if not decision.selected_route_reason:
                decision.selected_route_reason = (
                    f"Rule route `{decision.route}` with FNN top route "
                    f"`{fnn_route_scoring.get('top_route')}` at confidence {fnn_route_scoring.get('confidence')}."
                )
        if request_understanding is not None and not decision.request_understanding:
            decision.request_understanding = request_understanding.to_dict()
        if goal_graph and not decision.task_graph:
            decision.task_graph = dict(goal_graph)
        elif not decision.task_graph and decision.operations:
            operation_goals = []
            previous_goal_id = ""
            for index, operation in enumerate(decision.operations, start=1):
                item = dict(operation or {})
                goal_id = str(
                    item.get("step_id")
                    or item.get("operation_id")
                    or item.get("id")
                    or f"operation_{index}"
                )
                dependencies = [
                    str(value)
                    for value in (
                        item.get("depends_on")
                        or ([previous_goal_id] if previous_goal_id else [])
                    )
                    if str(value)
                ]
                operation_goals.append(
                    {
                        "task_id": goal_id,
                        "title": str(
                            item.get("title")
                            or item.get("name")
                            or item.get("operation")
                            or item.get("action")
                            or goal_id
                        ),
                        "action": str(
                            item.get("action")
                            or item.get("operation")
                            or item.get("capability")
                            or "execute"
                        ),
                        "goal_type": "execute",
                        "objective": str(
                            item.get("objective")
                            or item.get("description")
                            or item.get("title")
                            or goal_id
                        ),
                        "depends_on": dependencies,
                        "required_inputs": list(item.get("requires") or []),
                        "produces": list(item.get("produces") or []),
                        "read_only": False,
                        "terminal": index == len(decision.operations),
                    }
                )
                previous_goal_id = goal_id
            decision.task_graph = {
                "framework": "typed_operation_goal_graph_v1",
                "primary_goal": decision.primary_goal or primary_goal,
                "goal_type": decision.goal_type or goal_type or "execute",
                "goals": operation_goals,
                "ordered_goals": operation_goals,
                "estimated_steps": len(operation_goals),
            }
        elif goal_graph and decision.task_graph and goal_graph != decision.task_graph:
            # Specialized operation graphs describe the callable's known
            # implementation. Preserve the semantic graph separately so a
            # broad composite operation cannot erase prompt-specific behavior.
            decision.task_graph = dict(decision.task_graph)
            decision.task_graph["semantic_request_graph"] = dict(goal_graph)
            evaluations = _evaluate_semantic_dcc_capabilities(goal_graph, decision.host or host)
            if evaluations:
                decision.task_graph["semantic_capability_evaluation"] = evaluations
                missing_operations = [
                    str(item.get("capability") or "")
                    for item in evaluations
                    if item.get("status") == "missing_unregistered_callable"
                ]
                decision.capability_gaps = list(dict.fromkeys([
                    *list(decision.capability_gaps or []),
                    *missing_operations,
                ]))
        if semantic_execution_contract and not decision.semantic_execution_contract:
            decision.semantic_execution_contract = dict(semantic_execution_contract)
        if canonical_reasoning_pipeline and not decision.reasoning_pipeline:
            decision.reasoning_pipeline = dict(canonical_reasoning_pipeline)
        if canonical_visible_progress:
            decision.visible_progress = dict(canonical_visible_progress)
        # Compatibility metadata is a derived snapshot. PromptExecutionContext
        # remains the owner and may be reconstructed by callers from this field.
        decision.execution_context = dict(context_data)
        decision.primary_goal = decision.primary_goal or primary_goal
        decision.goal_type = decision.goal_type or goal_type
        decision.estimated_steps = decision.estimated_steps or estimated_steps
        decision.requires_generation = (
            decision.requires_generation or requires_generation
        )
        decision.requires_project_search = (
            decision.requires_project_search or requires_project_search
        )
        decision.requires_validation = (
            decision.requires_validation or requires_validation
        )
        decision.requires_execution = (
            decision.requires_execution or requires_execution
        )
        finalized = _finalize_decision(decision, lower)
        if finalized.intent_category == "staged_long_contract":
            finalized.task_graph = {}
            finalized.operations = []
            finalized.senior_prompt_analysis = {}
            finalized.domain_experts = []
            finalized.execution_context = {}
            finalized.reasons = list(dict.fromkeys([
                *finalized.reasons,
                "Deferred rich route analysis to the staged background planner.",
            ]))
            return finalized
        # Route finalization may enrich execution details, but it must not
        # replace the canonical reasoning-derived progress with a legacy plan.
        if canonical_visible_progress:
            finalized.visible_progress = dict(canonical_visible_progress)
        if canonical_reasoning_pipeline:
            finalized.reasoning_pipeline = {
                **dict(canonical_reasoning_pipeline),
                **dict(finalized.reasoning_pipeline or {}),
            }
        if fnn_route_scoring:
            finalized.reasoning_pipeline = {
                **dict(finalized.reasoning_pipeline or {}),
                "fnn_route_scoring": dict(fnn_route_scoring),
            }
            if not finalized.selected_route_reason:
                finalized.selected_route_reason = (
                    f"Rule route `{finalized.route}` with FNN top route "
                    f"`{fnn_route_scoring.get('top_route')}` at confidence {fnn_route_scoring.get('confidence')}."
                )
        try:
            from tech_connector.services.reasoning.cognitive_routing_service import upgrade_route_decision
            finalized = upgrade_route_decision(raw_text, finalized, active_path=context_data.get("active_path", ""))
        except Exception:
            pass
        if finalized.capability_gaps and finalized.route == "dcc_execute":
            missing_operation = str(finalized.capability_gaps[0])
            original_operation = str(finalized.target_identifier or "")
            try:
                from tech_connector.game_engine.integration.dcc_operation_service import build_dcc_capability_gap_plan

                gap_plan = build_dcc_capability_gap_plan(
                    finalized.host or host,
                    missing_operation,
                    original_request=raw_text,
                )
            except Exception:
                gap_plan = {
                    "framework": "dcc_capability_acquisition_v1",
                    "status": "missing_unregistered_callable",
                    "requested_operation": missing_operation,
                    "execution_blocked": True,
                }
            gap_plan["all_missing_operations"] = list(finalized.capability_gaps)
            gap_plan["resume_operation"] = original_operation
            gap_plan["resume_arguments"] = dict(finalized.keyword_args or {})
            if (finalized.host or host) == "unreal":
                try:
                    from tech_connector.services.unreal.unreal_operation_service import build_unreal_execution_plan

                    original_execution_plan = build_unreal_execution_plan(raw_text)
                    matching_gap = next(
                        (
                            dict(item)
                            for item in list(original_execution_plan.get("capability_gaps") or [])
                            if str(item.get("required_capability") or "") == missing_operation
                        ),
                        {},
                    )
                    params = dict(original_execution_plan.get("params") or {})
                    fx_parameters = dict(params.get("parameters") or {})
                    gap_plan["requested_behavior_contract"] = {
                        "original_operation": original_execution_plan.get("operation"),
                        "missing_operation": missing_operation,
                        "request_fragment": matching_gap.get("request_fragment"),
                        "source_strategy": matching_gap.get("source_strategy"),
                        "required_parameter_names": sorted(
                            key for key in fx_parameters
                            if str(key).startswith("FX_")
                        ),
                        "required_arguments": ["system_path", "source_strategy", "parameters", "save"],
                        "required_implementation_layer": "reflected_cpp_bridge",
                        "required_cpp_method": "SynthesizeNiagaraSourceStrategyStack",
                        "required_python_bridge_call": "unreal.AIStudioBridgeLibrary.synthesize_niagara_source_strategy_stack",
                        "required_unreal_modules": ["Niagara", "NiagaraCore", "NiagaraEditor", "UnrealEd"],
                        "required_result_evidence": [
                            "mutated Niagara system path",
                            "source strategy applied",
                            "module or renderer stack readback",
                            "parameters accepted and rejected",
                            "asset save/readback status",
                        ],
                        "planned_steps": list(original_execution_plan.get("steps") or []),
                        "acceptance": [
                            "Implement the requested source strategy, not merely generic Niagara asset creation.",
                            "Use verified local Unreal APIs or a reflected C++ bridge body; do not invent editor APIs.",
                            "Exercise source-strategy dispatch and failure behavior in a focused disposable test.",
                            "Preserve the original operation inputs so capability acquisition can resume it losslessly.",
                        ],
                    }
                except Exception as exc:
                    gap_plan["requested_behavior_contract_error"] = str(exc)
            gap_plan["request_plan_verification"] = dict(
                goal_graph.get("request_plan_verification") or {}
            )
            finalized.capability_gap_plan = gap_plan
            finalized.route = "target_discovery"
            finalized.provider = "project_search"
            finalized.execution_route = "engine.target_discovery"
            finalized.intent_category = "dcc_capability_acquisition"
            finalized.operation_mode = "acquire_then_resume"
            finalized.target_identifier = missing_operation
            finalized.requires_plan = True
            finalized.requires_generation = True
            finalized.requires_execution = False
            finalized.requires_dcc_connection = False
            finalized.requires_confirmation = False
            finalized.can_execute_directly = False
            finalized.reasons.append(
                f"Plan verification found unregistered dependency {missing_operation!r}; acquire it before resuming {original_operation!r}."
            )
        if (
            finalized.provider == "project_search"
            and finalized.execution_route == "engine.project_search"
            and finalized.mutation_scope == "read_only"
            and not finalized.requires_dcc_connection
        ):
            finalized.route = "project_search"
        if (
            finalized.route == "project_search"
            and finalized.model_tier == "none_deterministic"
            and finalized.mutation_scope == "read_only"
        ):
            finalized.reasoning_pipeline = {}
        return finalized

    if _looks_like_staged_long_contract(text, lower):
        return _finalize_with_context(PromptRouteDecision(
            route="chat",
            provider="llm",
            intent_category="staged_long_contract",
            host=host,
            confidence=0.82,
            operation_mode="staged_plan",
            mutation_scope="read_only",
            analysis_depth="staged",
            required_context=[
                "project_context",
                "connected_application_context",
                "task_chunks",
                "global_constraints",
                "deferred_stages",
            ],
            model_tier="local_code",
            requires_plan=True,
            requires_confirmation=False,
            reasons=[
                "Prompt is a long staged contract; route to staged LLM planning before any deterministic pipeline/action graph execution.",
                "Foreground routing should not reinterpret checklist wording like pipeline nodes as a Tech Connector pipeline graph request.",
            ],
            rejected_routes=["pipeline_graph", "action_graph", "dcc_execute"],
        ))

    documentation_code_edit = bool(
        re.search(
            r"\b(docstring|docstrings|function docs|function documentation|"
            r"param docs|parameter docs|missing params?|missing parameters?)\b",
            lower,
        )
        and re.search(r"\b(add|fix|update|repair|change|write|missing)\b", lower)
    )
    pipeline_ui_code_edit = bool(
        re.search(r"\b(?:pipeline|node graph|node view)\b", lower)
        and re.search(
            r"\b(?:button|warning|right click|context menu|filter|code path|"
            r"find where|fix|patch|repair|improve|slow)\b",
            lower,
        )
    )
    if documentation_code_edit or pipeline_ui_code_edit:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category=(
                "documentation_code_edit"
                if documentation_code_edit
                else "pipeline_code_edit"
            ),
            host=host,
            confidence=0.92,
            operation_mode="edit",
            mutation_scope="file_modification",
            requires_confirmation=not no_execute,
            requires_project_search=True,
            requires_generation=True,
            requires_validation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=[
                "Prompt asks to repair existing project code; discover the owning file and symbols before proposing a patch."
            ],
            rejected_routes=["pipeline_graph", "dcc_execute"],
        ))

    ui_wrapper_discovery = bool(
        host
        and re.search(r"\b(find|locate|identify|choose|select)\b", lower)
        and re.search(r"\b(existing|project)\b", lower)
        and re.search(r"\b(function|functions|method|operation)\b", lower)
        and re.search(r"\b(create|build|make|propose|plan|design|outline)\b", lower)
        and re.search(r"\b(ui|wrapper|window|interface|panel|tool)\b", lower)
    )
    if ui_wrapper_discovery:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category=(
                "read_only_ui_wrapper_planning"
                if no_execute
                else "dcc_tool_code_edit"
            ),
            host=host,
            confidence=0.92,
            operation_mode="plan" if no_execute else "edit",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            requires_plan=True,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            task_graph=_dcc_tool_task_graph(text, read_only=no_execute),
            reasons=[
                "The terminal goal is a UI wrapper around a discovered callable, so target discovery must preserve both stages."
            ],
            rejected_routes=["project_search", "dcc_execute"],
        ))

    if host == "maya" and not _is_explicit_source_code_mutation(text, lower):
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import (
                MAYA_OPERATIONS,
                build_dcc_operation_params,
                dcc_prompt_to_operation,
            )

            early_operation = dcc_prompt_to_operation(
                "maya",
                text,
                problem_formulation={"action_mode": "execute", "deliverables": []},
            )
            if early_operation in MAYA_OPERATIONS:
                early_params = build_dcc_operation_params("maya", early_operation, text)
                early_prerequisite = _maya_rigging_prerequisite_decision(
                    host="maya",
                    operation_key=early_operation,
                    op_function=MAYA_OPERATIONS[early_operation].function,
                    text=text,
                    params=early_params,
                    no_execute=no_execute,
                )
                if early_prerequisite:
                    return _finalize_with_context(early_prerequisite, lower)
        except Exception:
            pass
        if not _looks_like_read_only_project_question(lower):
            maya_rig_scene = _maya_create_rig_from_current_scene_decision(
                raw_text,
                no_execute=no_execute,
                project_roots=roots,
            )
            if maya_rig_scene:
                return _finalize_with_context(maya_rig_scene, lower)

    read_only_host_code_query = _read_only_host_code_query_decision(lower, host)
    if read_only_host_code_query:
        return _finalize_with_context(read_only_host_code_query, lower)

    code_authoring_request = bool(
        re.search(
            r"\b(?:how\s+(?:would|do|can|should)\s+i|plan|design|propose|"
            r"write|implement|author|scaffold)\b",
            lower,
        )
        and re.search(
            r"\b(?:ui|widget|dialog|panel|window|code|class|module|script|"
            r"wrapper|tool|application|app)\b",
            lower,
        )
    )

    if host == "maya" and not code_authoring_request:
        maya_unreal_pipeline = _maya_to_unreal_fbx_pipeline_decision(raw_text, no_execute=no_execute)
        if maya_unreal_pipeline:
            return _finalize_with_context(maya_unreal_pipeline, lower)
        maya_sequence = _maya_create_locator_then_move_decision(raw_text, no_execute=no_execute)
        if maya_sequence:
            return _finalize_with_context(maya_sequence, lower)
        maya_rig_scene = _maya_create_rig_from_current_scene_decision(
            raw_text,
            no_execute=no_execute,
            project_roots=roots,
        )
        if maya_rig_scene:
            return _finalize_with_context(maya_rig_scene, lower)
    # ------------------------------------------------------------------
    # Goal-first routing
    #
    # The goal graph owns the user's terminal objective. Supporting search
    # goals do not turn teaching/example requests into project-search results.
    # Explicit mutations and host execution remain protected by later guards.
    # ------------------------------------------------------------------
    semantic_confidence = float(
        request_understanding.confidence if request_understanding else 0.0
    )

    if no_execute and re.search(r"\b(review|inspect|analyze|analyse|explain|find)\b", lower) and re.search(
        r"\b(planner|service|code|files?|functions?|dependencies|hotspots?|line numbers?|performance|graph mutation)\b",
        lower,
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="read_only_project_review",
            host=host,
            confidence=0.88,
            operation_mode="query",
            mutation_scope="read_only",
            requires_confirmation=False,
            required_context=["project_index", "symbol_index", "code_chunks", "request_goal_graph"],
            model_tier="none_deterministic",
            task_graph=_read_only_review_task_graph(text),
            reasons=["Prompt asks for a read-only project/code review with evidence, not a mutation."],
            rejected_routes=["target_discovery", "dcc_execute", "unreal_capability"],
        ))

    if re.search(r"\b(create|add|build|implement|write)\b", lower) and re.search(
        r"\b(pyside|pyqt|qt|ui|tool|panel|dialog)\b",
        lower,
    ) and re.search(r"\b(maya|rigging|skin|bind|influence|joints?)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="dcc_tool_code_edit",
            host=host,
            confidence=0.9,
            operation_mode="edit",
            mutation_scope="file_modification" if not no_execute else "read_only",
            requires_confirmation=not no_execute,
            requires_plan=True,
            required_context=["target_discovery", "symbol_index", "maya_rigging_functions", "project_ui_patterns", "tests"],
            model_tier="local_code",
            task_graph=_dcc_tool_task_graph(text, read_only=no_execute),
            reasons=["Prompt asks to discover existing Maya rigging functions and create project UI/tool code."],
            rejected_routes=["project_search", "dcc_execute", "dcc_query"],
        ))

    gameplay_feature_terms = bool(re.search(
        r"\b(stamina|sprint|dodg(?:e|ing)|melee|combo|inventory|pickup|replicated|authority|save/load|enemy ai|patrol|perception|blackboard|behavior tree|behaviour tree|chase|debug draw|hud|gameplay)\b",
        lower,
    ))
    gameplay_mutation_terms = bool(re.search(r"\b(add|create|build|implement|make|update|wire|integrate)\b", lower))
    explicit_cross_dcc_pipeline = (
        len(hosts) >= 2
        and bool(re.search(r"\b(pipeline|workflow|cross-dcc|multi-dcc|transfer)\b", lower))
    )
    if (
        gameplay_feature_terms
        and gameplay_mutation_terms
        and not no_execute
        and not explicit_cross_dcc_pipeline
        and not _is_explicit_pipeline_build_request(lower)
    ):
        try:
            from tech_connector.services.unreal.feature_planning_service import (
                build_unreal_requirement_preview,
            )

            feature_preview = build_unreal_requirement_preview(text)
        except Exception:
            feature_preview = {
                "requirements": [],
                "operations": [],
                "missing_operations": [],
            }
        feature_graph = _gameplay_feature_task_graph(text, read_only=False)
        feature_graph["implementation_requirements"] = list(
            feature_preview.get("requirements") or []
        )
        feature_graph["planned_operations"] = list(
            feature_preview.get("operations") or []
        )
        feature_graph["missing_operations"] = list(
            feature_preview.get("missing_operations") or []
        )
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="gameplay_feature_implementation",
            host=host or ("unreal" if re.search(r"\b(blueprints?|anim\s*bp|character bp|behavior tree|blackboard|replicated|authority|hud)\b", lower) else ""),
            confidence=0.86,
            operation_mode="edit",
            mutation_scope="file_modification",
            requires_confirmation=True,
            requires_plan=True,
            deterministic_steps=[
                str(requirement.get("title") or "")
                for requirement in feature_preview.get("requirements") or []
                if requirement.get("title")
            ],
            operations=list(feature_preview.get("operations") or []),
            required_context=[
                "target_discovery",
                "symbol_index",
                "gameplay_architecture",
                "asset_or_blueprint_ownership",
                "validation_plan",
            ],
            model_tier="local_code",
            task_graph=feature_graph,
            reasons=["Prompt describes a multi-part gameplay feature; discover owning code/assets and dependencies before editing."],
            rejected_routes=["chat", "project_search", "dcc_execute"],
        ))

    if authoritative_import_coverage:
        scoped_path = (
            explicit_scope_path
            or str(getattr(request_understanding, "target_container_path", "") or "")
            or (roots[0] if roots else "")
        )
        return _finalize_with_context(
            PromptRouteDecision(
                route="import_coverage",
                provider="import_coverage",
                intent_category="code_health",
                host=host,
                confidence=0.99,
                operation_mode="analyze_import_coverage",
                target_type="directory",
                target_identifier=scoped_path,
                execution_route="engine.import_coverage",
                handler_id="ImportCoverageHandler",
                execution_environment="python_ast",
                mutation_scope="read_only",
                analysis_depth="graph",
                required_context=["active_project"],
                context_resolvers=["explicit_path", "python_ast_import_graph"],
                deterministic_steps=[
                    "enumerate_python_files_in_scope",
                    "parse_codebase_imports_with_ast",
                    "resolve_inbound_module_edges",
                    "exclude_package_initializers_and_entry_points",
                    "report_unimported_files",
                ],
                search_scopes=[scoped_path] if scoped_path else [],
                index_filters={"scope_path": scoped_path, "analysis": "unimported_files"},
                requires_fresh_index=False,
                model_tier="none_deterministic",
                model_capability="none",
                can_execute_directly=True,
                primary_goal="Find Python files in the requested directory that have no inbound imports from the tool codebase.",
                goal_type="analyze",
                estimated_steps=5,
                requires_project_search=False,
                requires_generation=False,
                requires_validation=False,
                requires_execution=False,
                reasons=[
                    "The request asks for import coverage, which requires an AST import graph rather than behavior search.",
                    "The explicit directory is authoritative; open-file and conversation momentum are ignored.",
                ],
                rejected_routes=["project_search", "target_discovery", "dcc_execute", "llm.chat"],
            )
        )

    if _is_connection_status_question(lower):
        return _finalize_with_context(PromptRouteDecision(
            route="connection_status",
            provider="connection_status",
            intent_category="connection_status",
            host=host,
            confidence=0.9,
            mutation_scope="read_only",
            model_tier="none_deterministic",
            reasons=["Prompt asks for connection/status information; do not compile an action graph."],
            rejected_routes=["action_graph", "pipeline_graph", "dcc_execute"],
        ))

    if (
        host
        and no_execute
        and not _is_scoped_project_guidance_request(lower)
        and re.search(r"\b(show|explain|teach|preview|plan)\b", lower)
        and re.search(r"\b(how|would|create|make|run|execute|call|export|import)\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="chat",
            provider="llm",
            intent_category="dcc_guidance",
            host=host,
            confidence=0.86,
            operation_mode="explain",
            mutation_scope="read_only",
            requires_confirmation=False,
            requires_dcc_connection=False,
            model_tier="local_fast",
            reasons=["Prompt asks for DCC guidance and explicitly blocks execution."],
            rejected_routes=["dcc_execute", "dcc_query", "action_graph"],
        ))

    if (
        not host
        and re.search(r"\b(failed|error|exception|traceback|broken|doesn't work|does not work)\b", lower)
        and re.search(r"\b(fix|repair|resolve|debug)\b", lower)
        and re.search(r"\b(validate|test|confirm|verify)\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="failure_repair",
            confidence=0.78,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "error_context", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to repair a failure and validate the result; discover the failing target before responding."],
            rejected_routes=["chat", "project_search", "dcc_execute"],
        ))

    if host == "maya" and not _is_explicit_source_code_mutation(text, lower):
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import (
                MAYA_OPERATIONS,
                build_dcc_operation_params,
                dcc_prompt_to_operation,
            )

            early_operation = dcc_prompt_to_operation(
                "maya",
                text,
                problem_formulation={"action_mode": "execute", "deliverables": []},
            )
            if early_operation in MAYA_OPERATIONS:
                early_params = build_dcc_operation_params("maya", early_operation, text)
                early_prerequisite = _maya_rigging_prerequisite_decision(
                    host="maya",
                    operation_key=early_operation,
                    op_function=MAYA_OPERATIONS[early_operation].function,
                    text=text,
                    params=early_params,
                    no_execute=no_execute,
                )
                if early_prerequisite:
                    return _finalize_with_context(early_prerequisite, lower)
        except Exception:
            pass

    if (
        request_understanding
        and semantic_confidence >= 0.78
        and goal_type in {"learn", "explain", "compare", "respond"}
        and not request_understanding.mutation_requested
        and not requires_execution
    ):
        if semantic_route == "project_search" and _is_scoped_project_guidance_request(lower):
            return _finalize_with_context(
                PromptRouteDecision(
                    route="project_search",
                    provider="project_search",
                    confidence=semantic_confidence,
                    intent_category=request_understanding.primary_intent or "code_generation_guidance",
                    host=host,
                    operation_mode="query",
                    mutation_scope="read_only",
                    required_context=["project_index", "symbol_index", "scoped_file_context", "request_goal_graph"],
                    model_tier="none_deterministic",
                    primary_goal=primary_goal,
                    goal_type=goal_type,
                    estimated_steps=estimated_steps,
                    requires_generation=requires_generation,
                    requires_project_search=True,
                    requires_validation=requires_validation,
                    requires_execution=False,
                    request_understanding=request_understanding.to_dict(),
                    task_graph=goal_graph,
                    route_candidates=route_candidates,
                    selected_route_reason="The terminal request is a read-only scoped project example, so project evidence is the answer source.",
                    reasons=[
                        "The prompt asks for a scoped code example/guidance and explicitly avoids mutation.",
                        "Host wording is contextual and does not make the project-file example a DCC action.",
                    ],
                    rejected_routes=["chat", "target_discovery", "dcc_execute"],
                ),
                lower,
            )
        return _finalize_with_context(
            PromptRouteDecision(
                route="chat",
                provider="llm",
                confidence=semantic_confidence,
                intent_category=request_understanding.primary_intent or "code_generation_guidance",
                host=host,
                operation_mode="respond",
                mutation_scope="read_only",
                required_context=(
                    ["project_index", "symbol_index", "request_goal_graph"]
                    if requires_project_search
                    else ["request_goal_graph"]
                ),
                model_tier="local_fast",
                primary_goal=primary_goal,
                goal_type=goal_type,
                estimated_steps=estimated_steps,
                requires_generation=requires_generation,
                requires_project_search=requires_project_search,
                requires_validation=requires_validation,
                requires_execution=requires_execution,
                request_understanding=request_understanding.to_dict(),
                task_graph=goal_graph,
                route_candidates=route_candidates,
                selected_route_reason="The terminal goal is explanation or teaching; project search is supporting evidence only.",
                reasons=[
                    "The request asks for guidance, explanation, comparison, or an example rather than a project mutation.",
                    "Any project search goal supports the final explanation instead of becoming the terminal response.",
                ],
                rejected_routes=["target_discovery", "dcc_execute"],
            ),
            lower,
        )

    if (
        request_understanding
        and semantic_confidence >= 0.78
        and goal_type == "generate"
        and not request_understanding.mutation_requested
        and not requires_execution
    ):
        return _finalize_with_context(
            PromptRouteDecision(
                route="chat",
                provider="llm",
                confidence=semantic_confidence,
                intent_category=request_understanding.primary_intent or "code_generation",
                host=host,
                operation_mode="generate",
                mutation_scope="read_only",
                required_context=(
                    ["project_index", "symbol_index", "request_goal_graph"]
                    if requires_project_search
                    else ["request_goal_graph"]
                ),
                model_tier="local_code",
                primary_goal=primary_goal,
                goal_type=goal_type,
                estimated_steps=estimated_steps,
                requires_generation=True,
                requires_project_search=requires_project_search,
                requires_validation=requires_validation,
                requires_execution=False,
                request_understanding=request_understanding.to_dict(),
                task_graph=goal_graph,
                route_candidates=route_candidates,
                selected_route_reason="The terminal goal is code generation without modifying project files.",
                reasons=[
                    "Generation is the terminal goal.",
                    "Project search may supply reusable patterns before the model produces the requested example.",
                ],
                rejected_routes=["target_discovery", "dcc_execute"],
            ),
            lower,
        )

    if (
        request_understanding
        and semantic_confidence >= 0.78
        and request_understanding.primary_intent
        in {"read_only_ui_wrapper_planning", "read_only_code_planning"}
        and goal_type == "plan"
        and not request_understanding.mutation_requested
        and not requires_execution
    ):
        return _finalize_with_context(
            PromptRouteDecision(
                route="target_discovery",
                provider="target_discovery",
                intent_category=request_understanding.primary_intent,
                host=host,
                confidence=semantic_confidence,
                operation_mode="plan",
                target_type="code",
                target_identifier=request_understanding.target_file,
                mutation_scope="read_only",
                requires_confirmation=False,
                required_context=["target_discovery", "project_index", "symbol_index", "request_goal_graph"],
                model_tier="local_code",
                primary_goal=primary_goal,
                goal_type=goal_type,
                estimated_steps=estimated_steps,
                requires_generation=requires_generation,
                requires_project_search=True,
                requires_validation=requires_validation,
                requires_execution=False,
                request_understanding=request_understanding.to_dict(),
                task_graph=goal_graph,
                route_candidates=route_candidates,
                selected_route_reason="The request needs project evidence before an implementation plan can be trusted.",
                reasons=list(request_understanding.reasons),
                rejected_routes=["project_search", "dcc_execute", "pipeline_graph", "action_graph"],
            ),
            lower,
        )

    # Semantic understanding owns the primary intent for mixed-language requests.
    # Deterministic routing still verifies facts, contracts, and safety.
    if (
        request_understanding
        and semantic_confidence >= 0.78
        and semantic_route in {"target_discovery", "project_search", "pipeline_graph", "action_graph"}
    ):
        common_goal_metadata = {
            "primary_goal": primary_goal,
            "goal_type": goal_type,
            "estimated_steps": estimated_steps,
            "requires_generation": requires_generation,
            "requires_project_search": requires_project_search,
            "requires_validation": requires_validation,
            "requires_execution": requires_execution,
            "request_understanding": request_understanding.to_dict(),
            "task_graph": goal_graph,
            "semantic_execution_contract": semantic_execution_contract,
        }

        semantic_explicit_pipeline_request = (
            len(hosts) >= 2
            or bool(re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|multi-step|multi step|sequence|compose)\b", lower))
            or bool(host and _has_host_handoff_language(lower, hosts))
        )
        if semantic_explicit_pipeline_request and re.search(
            r"\b(create|make|setup|build|design|scaffold|graph|ui|nodes?|nodes? view|compose|sequence|export|import|transfer)\b",
            lower,
        ):
            return _finalize_with_context(
                PromptRouteDecision(
                    route="pipeline_graph",
                    provider="action_graph",
                    intent_category=request_understanding.primary_intent or "workflow_pipeline",
                    host=host or (hosts[0] if hosts else ""),
                    confidence=max(semantic_confidence, 0.9),
                    operation_mode="compose_pipeline",
                    mutation_scope="dcc_mutation",
                    requires_confirmation=not no_execute,
                    requires_dcc_connection=bool(host or hosts),
                    required_context=["dcc_bridge_status", "operation_catalogs", "workflow_graph", "request_goal_graph"],
                    route_candidates=route_candidates,
                    selected_route_reason="Explicit pipeline/workflow request takes precedence over project-code mutation fallback.",
                    reasons=list(request_understanding.reasons or []) + [
                        "Explicit pipeline/workflow request takes precedence over single project-code or primitive DCC inference."
                    ],
                    rejected_routes=["dcc_execute", "project_search"],
                    **common_goal_metadata,
                ),
                lower,
            )

        unreal_live_asset_mutation = bool(
            host == "unreal"
            and (
                (
                    re.search(r"\b(?:blueprint|event graph|anim graph|node|pin)\b", lower)
                    and re.search(r"\b(?:add|attach|connect|create|edit|modify|remove|wire)\w*\b", lower)
                )
                or (
                    re.search(r"\b(?:niagara|niagra|vfx|particle)\b", lower)
                    and re.search(r"\b(?:character|mesh|blueprint|bp_[a-z0-9_]+)\b", lower)
                )
            )
        )
        if semantic_route == "target_discovery" and (
            request_understanding.mutation_requested
            or goal_type == "modify"
            or bool(goal_graph.get("mutation_goal_ids"))
        ) and not unreal_live_asset_mutation:
            source_files = _explicit_source_file_references(text)
            return _finalize_with_context(
                PromptRouteDecision(
                    route="target_discovery",
                    provider="target_discovery",
                    intent_category=request_understanding.primary_intent or "project_code_edit",
                    host=host,
                    confidence=semantic_confidence,
                    target_type="code",
                    target_identifier=request_understanding.target_file or (source_files[0] if source_files else ""),
                    requires_confirmation=bool(goal_graph.get("approval_goal_ids")) or True,
                    required_context=["target_discovery", "symbol_index", "code_chunks", "request_goal_graph"],
                    model_tier="local_code",
                    route_candidates=route_candidates,
                    selected_route_reason="The goal graph contains a project-code mutation.",
                    reasons=list(
                        request_understanding.reasons
                        or ["The terminal goal modifies project code."]
                    ),
                    rejected_routes=["project_search", "action_graph", "pipeline_graph", "dcc_execute"],
                    **common_goal_metadata,
                ),
                lower,
            )

        if (
            semantic_route == "target_discovery"
            and not request_understanding.mutation_requested
            and not unreal_live_asset_mutation
        ):
            source_files = _explicit_source_file_references(text)
            return _finalize_with_context(
                PromptRouteDecision(
                    route="target_discovery",
                    provider="target_discovery",
                    intent_category=request_understanding.primary_intent or "read_only_code_planning",
                    host=host,
                    confidence=semantic_confidence,
                    operation_mode="plan" if goal_type in {"plan", "validate"} else "analyze",
                    target_type="code",
                    target_identifier=request_understanding.target_file or (source_files[0] if source_files else ""),
                    mutation_scope="read_only",
                    requires_confirmation=False,
                    required_context=["target_discovery", "project_index", "symbol_index", "code_chunks", "request_goal_graph"],
                    model_tier="local_code",
                    route_candidates=route_candidates,
                    selected_route_reason="The request needs implementation-target discovery before a read-only diagnosis or repair plan.",
                    reasons=list(
                        request_understanding.reasons
                        or ["The terminal goal needs code ownership evidence without applying a mutation."]
                    ),
                    rejected_routes=["project_search", "action_graph", "pipeline_graph", "dcc_execute"],
                    **common_goal_metadata,
                ),
                lower,
            )

        if (
            semantic_route == "project_search"
            and goal_type not in {"learn", "explain", "compare", "generate", "modify", "execute", "plan"}
            and not request_understanding.mutation_requested
        ):
            return _finalize_with_context(
                PromptRouteDecision(
                    route="project_search",
                    provider="project_search",
                    intent_category=request_understanding.primary_intent or "project_exploration",
                    host=host,
                    confidence=semantic_confidence,
                    operation_mode="query",
                    mutation_scope="read_only",
                    required_context=["project_index", "symbol_index", "request_goal_graph"],
                    model_tier="none_deterministic",
                    route_candidates=route_candidates,
                    selected_route_reason="The terminal goal is a read-only project lookup.",
                    reasons=list(request_understanding.reasons),
                    rejected_routes=["target_discovery", "dcc_execute", "action_graph"],
                    **common_goal_metadata,
                ),
                lower,
            )

        if (
            semantic_route in {"pipeline_graph", "action_graph"}
            and (
                request_understanding.workflow_requested
                or goal_type == "plan"
                or bool(goal_graph.get("requires_graph"))
            )
        ):
            route_name = "pipeline_graph" if semantic_route == "pipeline_graph" else "action_graph"
            return _finalize_with_context(
                PromptRouteDecision(
                    route=route_name,
                    provider="action_graph",
                    intent_category=request_understanding.primary_intent or "workflow_pipeline",
                    host=host,
                    confidence=semantic_confidence,
                    required_context=["project_index", "symbol_index", "workflow_graph", "request_goal_graph"],
                    route_candidates=route_candidates,
                    selected_route_reason="The goal graph requires explicit workflow orchestration.",
                    reasons=list(request_understanding.reasons),
                    **common_goal_metadata,
                ),
                lower,
            )

    # Version 1.0 Recovery precedence law: explicit source-code mutation wins
    # before DCC operation inference and workflow/pipeline classification.
    if _is_scoped_project_guidance_request(lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_generation_guidance",
            host=host,
            confidence=0.89,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "scoped_file_context"],
            model_tier="none_deterministic",
            route_candidates=route_candidates,
            selected_route_reason="The prompt explicitly asks for a read-only scoped project example.",
            request_understanding=request_understanding.to_dict() if request_understanding else {},
            task_graph=goal_graph,
            semantic_execution_contract=semantic_execution_contract,
            primary_goal=primary_goal,
            goal_type=goal_type,
            estimated_steps=estimated_steps,
            requires_generation=requires_generation,
            requires_project_search=True,
            requires_validation=requires_validation,
            requires_execution=False,
            reasons=["Prompt asks for scoped code guidance and explicitly blocks project mutation."],
            rejected_routes=["target_discovery", "dcc_execute", "dcc_prototype"],
        ))

    if _is_explicit_source_code_mutation(text, lower):
        source_files = _explicit_source_file_references(text)
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="explicit_source_code_edit",
            host=host,
            confidence=0.97,
            target_type="code",
            target_identifier=source_files[0] if source_files else "",
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            route_candidates=route_candidates,
            selected_route_reason="Explicit source filename plus code-mutation intent has highest precedence.",
            request_understanding=request_understanding.to_dict() if request_understanding else {},
            task_graph=goal_graph,
            semantic_execution_contract=semantic_execution_contract,
            primary_goal=primary_goal,
            goal_type=goal_type,
            estimated_steps=estimated_steps,
            requires_generation=requires_generation,
            requires_project_search=requires_project_search,
            requires_validation=requires_validation,
            requires_execution=requires_execution,
            reasons=[
                "Prompt explicitly names a source file and requests a code mutation.",
                "Project code edits must be resolved by target discovery before any DCC or workflow inference.",
            ],
            rejected_routes=["action_graph", "pipeline_graph", "dcc_execute", "dcc_prototype"],
        ))

    if phrase_intent and phrase_intent.kind == "host_state_query" and not _has_explicit_dcc_operation(lower):
        target = phrase_intent.target or "selection"
        if host == "unreal" and target == "project":
            return _finalize_with_context(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name="ai_studio.synthetic.project_snapshot",
                target_identifier="project.snapshot",
                operation_mode="query",
                mutation_scope="read_only",
                risk_level="low",
                confidence=phrase_intent.confidence,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                model_tier="none_deterministic",
                reasons=list(phrase_intent.reasons or ["Prompt asks for a read-only Unreal project snapshot."]),
                rejected_routes=["navigation.open_asset", "dcc_execute", "action_graph"],
            ))
        keyword_args: dict[str, Any] = {}
        if host == "maya" and target == "scene.list_joints":
            try:
                from tech_connector.game_engine.integration.dcc_operation_service import build_dcc_operation_params

                keyword_args = dict(build_dcc_operation_params("maya", "scene.list_joints", text) or {})
            except Exception:
                keyword_args = {}
        elif host == "maya" and target == "selection":
            target = "scene.ls"
            keyword_args = {"selection": True}
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host=host,
            target_identifier=target,
            keyword_args=keyword_args,
            operation_mode="query",
            mutation_scope="read_only",
            confidence=phrase_intent.confidence,
            requires_confirmation=False,
            required_context=["dcc_connection"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or [f"Prompt asks for read-only {host} state."]),
            rejected_routes=["navigation.open_asset", "unreal_capability", "dcc_execute", "action_graph"],
        ))

    if host == "maya" and no_execute and re.search(r"\b(list|show|find|get|inspect)\b", lower) and re.search(r"\b(joints?|bones?)\b", lower):
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import build_dcc_operation_params

            keyword_args = dict(build_dcc_operation_params("maya", "scene.list_joints", text) or {})
        except Exception:
            keyword_args = {}
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host="maya",
            callable_name="ai_studio.maya.generated.scene_list_joints",
            target_identifier="scene.list_joints",
            keyword_args=keyword_args,
            operation_mode="query",
            mutation_scope="read_only",
            confidence=0.9,
            requires_confirmation=False,
            required_context=["dcc_connection", "scene_context"],
            model_tier="none_deterministic",
            reasons=["Brief prompt asks for a read-only Maya joint/bone inventory query."],
            rejected_routes=["llm.chat", "dcc_execute", "project_search"],
        ))

    if not host and no_execute and re.search(r"\b(inspect|check|analyze|analyse|find|review|determine|identify)\b", lower) and re.search(
        r"\b(project|code|codebase|files|classes|functions|systems?|implementation|architecture)\b",
        lower,
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="read_only_project_investigation",
            confidence=0.82,
            operation_mode="investigate",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "code_chunks"],
            model_tier="local_fast",
            reasons=["Prompt asks for read-only project investigation and explicitly avoids editing."],
            rejected_routes=["unreal_capability", "action_graph", "target_discovery"],
        ))

    if no_execute and re.search(r"\b(qslider|slider|widget|class|example)\b", lower) and re.search(r"\b@[A-Za-z_][A-Za-z0-9_.]*|custom_widgets(?:\.py)?|custom_qt\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_generation_guidance",
            host="",
            confidence=0.86,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "scoped_file_context"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for a scoped code example/guidance and explicitly avoids mutation."],
            rejected_routes=["unreal_capability", "dcc_execute", "target_discovery"],
        ))

    if not host and re.search(r"\b(autocomplete|@ menu|at menu|mention candidate|label builder|custom widgets|custom_widgets)\b", lower) and re.search(r"\b(find|inspect|explain|why|where|says py|showing as py)\b", lower) and not re.search(r"\b(fix|patch|change|update|test that|make it|ensure)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.84,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "ui_code"],
            model_tier="none_deterministic",
            reasons=["Prompt asks to explain project autocomplete behavior, not mutate it."],
            rejected_routes=["unreal_capability", "dcc_execute"],
        ))

    if not host and re.search(r"\b(autocomplete|@ menu|at menu|mention candidate|label builder|custom widgets|custom_widgets)\b", lower) and re.search(r"\b(fix|patch|change|update|test that|make it|ensure)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="project_code_edit",
            host=host,
            confidence=0.86,
            operation_mode="edit",
            mutation_scope="file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "ui_code"],
            model_tier="local_code",
            reasons=["Prompt asks to change or test project autocomplete behavior."],
            rejected_routes=["unreal_capability", "dcc_execute"],
        ))

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ))

    if phrase_intent and phrase_intent.kind == "project_symbol_search":
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=phrase_intent.confidence,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "docstrings"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or ["Prompt asks for read-only symbol/function search."]),
            rejected_routes=["target_discovery", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ))

    explicit_pipeline_request = (
        len(hosts) >= 2
        or bool(re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|multi-step|multi step|sequence|compose)\b", lower))
        or bool(host and _has_host_handoff_language(lower, hosts))
    )
    if explicit_pipeline_request and re.search(
        r"\b(create|make|setup|build|design|scaffold|graph|ui|nodes?|nodes? view|compose|sequence|export|import|transfer)\b",
        lower,
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="pipeline_graph",
            provider="action_graph",
            intent_category="workflow_pipeline",
            host=host or (hosts[0] if hosts else ""),
            confidence=0.9,
            operation_mode="compose_pipeline",
            mutation_scope="dcc_mutation",
            requires_confirmation=not no_execute,
            requires_dcc_connection=bool(host or hosts),
            required_context=["dcc_bridge_status", "operation_catalogs", "workflow_graph"],
            model_tier="none_deterministic",
            reasons=["Explicit pipeline/workflow request takes precedence over single primitive DCC operation inference."],
            rejected_routes=["dcc_execute", "project_search"],
        ))

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                HOUDINI_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "houdini": HOUDINI_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, raw_text if op_key == "script.run" else text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "", [])
                ]
                rig_prereq_decision = _maya_rigging_prerequisite_decision(
                    host=host,
                    operation_key=op_key,
                    op_function=op.function,
                    text=text,
                    params=params,
                    no_execute=no_execute,
                )
                if rig_prereq_decision:
                    return _finalize_with_context(rig_prereq_decision, lower)
                if op_key in {"scene.list_joints", "scene.ls"}:
                    return _finalize_with_context(PromptRouteDecision(
                        route="dcc_query",
                        confidence=0.96,
                        provider="dcc",
                        intent_category="dcc_query",
                        host=host,
                        callable_name=op.function,
                        target_identifier=op_key,
                        keyword_args=params,
                        requires_confirmation=False,
                        mutation_scope="read_only",
                        required_context=["dcc_connection", "scene_context"],
                        missing_info=missing_info,
                        model_tier="none_deterministic",
                        reasons=[f"Prompt asks for a read-only {host} scene inventory query."],
                        rejected_routes=["llm.chat", "dcc_execute", "project_search"],
                    ))
                return _finalize_with_context(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    task_graph=_dcc_operation_task_graph(
                        text,
                        host=host,
                        operation_key=op_key,
                        callable_name=op.function,
                        read_only=no_execute or not op.mutates_project,
                    ),
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                    rejected_routes=["action_graph", "project_search", "target_discovery"],
                ))
        except Exception:
            pass

    if host and re.search(r"\b(where should|where would|how should|how would)\b", lower) and re.search(
        r"\b(add|create|implement|put|place|wire)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_understanding",
            host=host,
            confidence=0.82,
            required_context=["project_index", "symbol_index", "project_architecture"],
            model_tier="local_fast",
            reasons=["Prompt asks where/how to add something; answer from indexed project architecture before host execution."],
            rejected_routes=["dcc_execute", "dcc_prototype", "unreal_capability"],
        ))

    if host == "unreal" and re.search(r"\b(?:run|execute)\s+(?:unreal\s+)?python\b", lower):
        code = ""
        match = re.search(r"\b(?:code|script|python)\s*[:=]\s*(.+)$", raw_text or "", re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1).strip()
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_execute",
            confidence=0.95,
            provider="dcc",
            intent_category="dcc_execution",
            host="unreal",
            callable_name="tech_connector.bridges.unreal.unreal_bridge.execute_python",
            target_identifier="python.run",
            keyword_args={"code": code} if code else {},
            requires_confirmation=not no_execute,
            required_context=["dcc_connection", "argument_validation"],
            missing_info=[] if code else ["code"],
            model_tier="none_deterministic",
            reasons=["Prompt explicitly asks to run Python in Unreal."],
            rejected_routes=["action_graph", "project_search", "target_discovery"],
        ))

    if (
        re.search(r"\b(build|create|add|implement|write|generate|prototype|scaffold)\b", lower)
        and re.search(r"\b(qt|pyside|ui|user interface|tool panel|panel|window|widget|table|operation runner|tool|wrapper|script|cli|command|pipeline|workflow|test harness|service)\b", lower)
        and re.search(r"\b(function|functions|operation|operations|catalog|registry|backend|commandrouter|execution services?|api|apis|callable|callables)\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="function_backed_artifact_generation",
            host=host,
            confidence=0.87,
            operation_mode="plan_or_edit",
            mutation_scope="file_modification" if not no_execute else "read_only",
            requires_confirmation=not no_execute,
            requires_dcc_connection=False,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns", "operation_catalogs", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to generate local code around existing functions/operations; discover project targets before any execution route."],
            rejected_routes=["unreal_capability", "dcc_execute", "dcc_prototype", "pipeline_graph", "action_graph"],
        ))

    if host == "unreal" and _is_unreal_graph_operation_planning_request(lower):
        target_asset = ""
        try:
            from tech_connector.services.unreal.unreal_operation_service import extract_unreal_asset_name, extract_unreal_package_like_path

            target_asset = str(extract_unreal_package_like_path(text) or extract_unreal_asset_name(text) or "")
        except Exception:
            target_asset = ""
        return _finalize_with_context(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="unreal_semantic_graph_planning",
            host="unreal",
            confidence=0.9,
            callable_name="unreal_tools.graph.semantic_edit_plan",
            target_identifier=target_asset,
            keyword_args={"target_asset": target_asset} if target_asset else {},
            operation_mode="plan",
            target_type="unreal_graph",
            mutation_scope="read_only",
            risk_level="low",
            requires_confirmation=False,
            required_context=[
                "unreal_reflection_index",
                "capability_graph",
                "semantic_graph_understanding",
                "graph_node_pin_link_index",
                "argument_validation",
            ],
            model_tier="none_deterministic",
            reasons=[
                "Prompt asks to inspect or report available Unreal graph operations; keep this in graph planning instead of plain asset navigation.",
            ],
            rejected_routes=["navigation.open_asset", "pipeline_graph", "action_graph"],
        ))

    if host == "unreal":
        try:
            from tech_connector.services.unreal.semantic_graph_service import is_unreal_graph_modification_request
            from tech_connector.services.unreal.unreal_operation_service import (
                UNREAL_OPERATIONS,
                build_unreal_editable_character_fx_params,
                build_unreal_execution_plan,
                unreal_prompt_to_operation,
            )

            if is_unreal_graph_modification_request(text):
                deterministic_op = unreal_prompt_to_operation(text)
                if deterministic_op == "niagara.attach_editable_character_fx" and deterministic_op in UNREAL_OPERATIONS:
                    op = UNREAL_OPERATIONS[deterministic_op]
                    params = build_unreal_editable_character_fx_params(text)
                    missing_info = [
                        arg for arg in op.required
                        if arg not in params or params.get(arg) in (None, "", [])
                    ]
                    operation_plan = build_unreal_execution_plan(text)
                    deterministic_gaps = [
                        str(item.get("required_capability") or "").strip()
                        for item in list(operation_plan.get("capability_gaps") or [])
                        if isinstance(item, dict) and str(item.get("required_capability") or "").strip()
                    ]
                    return _finalize_with_context(PromptRouteDecision(
                        route="dcc_execute",
                        confidence=0.96,
                        provider="unreal",
                        intent_category="dcc_execution",
                        host="unreal",
                        callable_name=op.function,
                        target_identifier=deterministic_op,
                        keyword_args=params,
                        requires_confirmation=op.mutates_project and not no_execute,
                        required_context=["dcc_connection", "resolved_callable", "argument_validation", "unreal_blueprint_context"],
                        task_graph=_dcc_operation_task_graph(
                            text,
                            host="unreal",
                            operation_key=deterministic_op,
                            callable_name=op.function,
                            read_only=no_execute or not op.mutates_project,
                        ),
                        missing_info=missing_info,
                        capability_gaps=deterministic_gaps,
                        model_tier="none_deterministic",
                        reasons=[
                            f"Prompt matches registered Unreal operation: {deterministic_op}.",
                            "Deterministic composite operation wins over generic semantic graph planning for this executable character-FX workflow.",
                        ],
                        rejected_routes=["unreal_semantic_graph_modification", "pipeline_graph", "action_graph"],
                    ))
                target_asset = ""
                try:
                    from tech_connector.services.unreal.unreal_operation_service import extract_unreal_asset_name, extract_unreal_package_like_path

                    target_asset = str(extract_unreal_package_like_path(text) or extract_unreal_asset_name(text) or "")
                except Exception:
                    target_asset = ""
                return _finalize_with_context(PromptRouteDecision(
                    route="unreal_capability",
                    provider="unreal",
                    intent_category="unreal_semantic_graph_modification",
                    host="unreal",
                    confidence=0.91,
                    callable_name="unreal_tools.graph.semantic_edit_plan",
                    target_identifier=target_asset,
                    keyword_args={"target_asset": target_asset} if target_asset else {},
                    requires_confirmation=not no_execute,
                    required_context=[
                        "unreal_reflection_index",
                        "capability_graph",
                        "semantic_graph_understanding",
                        "graph_node_pin_link_index",
                        "existing_behavior_preservation",
                        "similar_project_patterns",
                        "argument_validation",
                    ],
                    mutation_scope="graph_asset",
                    risk_level="high",
                    model_tier="local_code",
                    reasons=[
                        "Prompt asks to modify an Unreal graph; route before generic pipeline graph handling.",
                        "Semantic graph understanding and preservation checks are required before graph mutation.",
                    ],
                    rejected_routes=["pipeline_graph", "action_graph"],
                ))
        except Exception:
            pass

    pipeline_code_target = bool(
        re.search(r"\b(pipeline|node graph|node view|add and connect|right click|right-click|compile button|required inputs|tool filter)\b", lower)
        and re.search(r"\b(find|where|code path|fix|improve|patch|repair|update|slow|warning|propose)\b", lower)
    )
    if pipeline_code_target:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="pipeline_code_edit",
            host=host,
            confidence=0.86,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "pipeline_graph_code", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to find or improve Tech Connector pipeline/node-graph code, not to compose or execute a pipeline graph."],
            rejected_routes=["pipeline_graph", "action_graph", "dcc_execute"],
        ))

    status_code_target = bool(
        re.search(r"\b(index|indexing|knowledge|status|status bar|status panel|progress|ready|stale|connection|connected|theme|color|ui)\b", lower)
        and re.search(r"\b(find|where|code path|owning files?|likely owning|fix|improve|patch|repair|update|wrong|bug|says|still|running|slow|freeze|frozen)\b", lower)
        and not (
            host
            and re.search(r"\b(function|functions|method|operation)\b", lower)
            and re.search(r"\b(ui|wrapper|window|interface|panel|tool)\b", lower)
        )
    )
    if status_code_target:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="status_ui_code_edit",
            host=host,
            confidence=0.84,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "status_ui_code", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to find or fix Tech Connector status/index/UI code, not to perform a broad project fact search."],
            rejected_routes=["project_search", "action_graph", "dcc_execute"],
        ))

    application_code_target = bool(
        re.search(
            r"\b(chat history|old thread|thread disappears|switch chat|switching chat|mobile app|jobs?|output logs?|job logs?|ide agent|repo map|symbol lookup|structured patching|error reporting|reporting quality|rollback status)\b",
            lower,
        )
        and re.search(r"\b(plan|propose|find|where|code path|owning files?|fix|improve|patch|repair|update|reuse|tests?)\b", lower)
    )
    if application_code_target:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="application_code_architecture",
            host=host,
            confidence=0.83,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "project_architecture", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for Tech Connector application-code planning or repair; discover owning files before synthesis."],
            rejected_routes=["project_search", "pipeline_graph", "action_graph", "dcc_execute"],
        ))

    function_backed_artifact_request = (
        re.search(r"\b(build|create|add|implement|write|generate|prototype|scaffold)\b", lower)
        and re.search(r"\b(qt|pyside|ui|user interface|tool panel|panel|window|widget|table|operation runner|tool|wrapper|script|cli|command|pipeline|workflow|test harness|service)\b", lower)
        and re.search(r"\b(function|functions|operation|operations|catalog|registry|backend|commandrouter|execution services?|api|apis|callable|callables)\b", lower)
    )
    if function_backed_artifact_request:
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="function_backed_artifact_generation",
            host=host,
            confidence=0.87,
            operation_mode="plan_or_edit",
            mutation_scope="file_modification" if not no_execute else "read_only",
            requires_confirmation=not no_execute,
            requires_dcc_connection=False,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns", "operation_catalogs", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to generate local code around existing functions/operations; discover project targets before any execution route."],
            rejected_routes=["unreal_capability", "dcc_execute", "dcc_prototype", "pipeline_graph", "action_graph"],
        ))
    
    # Check if this is a pipeline or multi-DCC request
    is_pipeline = False
    if len(hosts) >= 2:
        is_pipeline = True
    elif len(hosts) == 1 and re.search(r"\b(pipeline|workflow|bridge|connect|transfer|export|import)\b", lower):
        is_pipeline = True
    elif re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|multi-step|multi step|sequence|compose)\b", lower):
        is_pipeline = True
        
    if is_pipeline:
        route = "pipeline_graph" if re.search(r"\b(create|make|setup|build|design|scaffold|graph|ui|nodes?|nodes? view|compose|sequence)\b", lower) else "action_graph"
        return _finalize_with_context(PromptRouteDecision(
            route=route,
            provider="action_graph",
            intent_category="workflow_pipeline",
            host=host or (hosts[0] if hosts else ""),
            confidence=0.88,
            required_context=["project_index", "symbol_index", "workflow_graph"],
            reasons=["Prompt is classified as a multi-DCC or pipeline request."],
        ))

    file_ref = _has_file_ref(text) or bool(active_path and re.search(r"\b(this|current|active|selected)\s+(?:file|script)\b", lower))
    symbol_ref = bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b", text or ""))
    execution_callable = _callable_after_execution_verb(text)
    known_unreal_operation = _known_unreal_operation_from_text(text)

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ))

    if phrase_intent and phrase_intent.kind == "project_symbol_search":
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=phrase_intent.confidence,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "docstrings"],
            model_tier="none_deterministic",
            reasons=list(phrase_intent.reasons or ["Prompt asks for read-only symbol/function search."]),
            rejected_routes=["target_discovery", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ))

    if phrase_intent and phrase_intent.kind in {"asset_navigation", "graph_read_or_navigation"} and host == "unreal" and known_unreal_operation:
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        if operation_key.startswith("navigation.") or operation_key in {"blueprint.scan", "assets.inspect"}:
            return _finalize_with_context(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=operation_key,
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                operation_mode="navigate" if operation_key.startswith("navigation.") else "query",
                target_type="dcc_navigation" if operation_key.startswith("navigation.") else "dcc_callable",
                mutation_scope="read_only",
                risk_level="low",
                can_execute_directly=operation_key.startswith("navigation."),
                confidence=max(0.9, phrase_intent.confidence),
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=list(phrase_intent.reasons or ["Prompt asks for read-only Unreal asset or graph navigation."]),
                rejected_routes=["unreal_semantic_graph_modification", "pipeline_graph", "action_graph"],
            ))

    if host and re.search(r"\b(find|locate|identify|choose|select)\b", lower) and re.search(
        r"\b(existing|project)\b", lower
    ) and re.search(r"\b(function|functions|method|operation)\b", lower) and re.search(
        r"\b(ui|wrapper|window|interface|panel|tool)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="read_only_ui_wrapper_planning",
            host=host,
            confidence=0.84,
            operation_mode="plan",
            mutation_scope="read_only" if no_execute else "file_modification",
            requires_confirmation=not no_execute,
            required_context=["target_discovery", "symbol_index", "project_ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to find a real project function and plan a UI wrapper; discover targets before any edit or generic search response."],
            rejected_routes=["project_search", "dcc_execute"],
        ))

    if host == "unreal" and known_unreal_operation:
        early_unreal_operation_key = str(known_unreal_operation.get("operation_key") or "")
        if early_unreal_operation_key in {"project.snapshot", "blueprint.scan", "assets.inspect"}:
            return _finalize_with_context(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=early_unreal_operation_key,
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                mutation_scope="read_only",
                risk_level="low",
                confidence=0.92,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=["Prompt maps to a registered read-only Unreal operation; do not fall back to generic project source search."],
                rejected_routes=["project_search", "dcc_query"],
            ))

    if re.search(r"\b(docstring|docstrings|function docs|function documentation|param docs|parameter docs|missing params?|missing parameters?)\b", lower) and re.search(
        r"\b(add|create|write|generate|fill|fix|update|patch|improve)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="documentation_code_edit",
            host=host,
            confidence=0.82,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "docstrings", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks to modify code documentation; discover real target symbols before editing."],
        ))

    if re.search(r"\b(find|locate|identify|inspect|diagnose|troubleshoot)\b", lower) and re.search(
        r"\b(make|improve|fix|patch|repair|update|change|refactor|more actionable|clearer|better)\b", lower
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="discover_then_edit",
            host=host,
            confidence=0.80,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt combines target discovery with a requested code improvement."],
        ))

    # Import coverage is a dependency-graph question. Handle it before the
    # generic project-fact branch so "what files" cannot collapse into a
    # behavior/symbol search. Explicit prompt paths override open-file context.
    if _is_unimported_files_query(text):
        scoped_path = (
            explicit_scope_path
            or str(getattr(request_understanding, "target_container_path", "") or "")
            or (roots[0] if roots else "")
        )
        return _finalize_with_context(PromptRouteDecision(
            route="project_health",
            provider="project_health",
            intent_category="code_health",
            host=host,
            confidence=0.97,
            operation_mode="analyze",
            target_type="directory",
            target_identifier=scoped_path,
            mutation_scope="read_only",
            required_context=["import_graph", "dependency_graph", "project_files"],
            context_resolvers=["explicit_path", "import_graph"],
            deterministic_steps=[
                "enumerate_source_files_in_scope",
                "build_or_load_import_graph",
                "identify_files_with_no_inbound_import_edges",
                "exclude_package_initializers_and_declared_entry_points",
                "format_unimported_file_report",
            ],
            search_scopes=[scoped_path] if scoped_path else [],
            index_filters={"scope_path": scoped_path, "analysis": "unimported_files"},
            requires_fresh_index=True,
            model_tier="none_deterministic",
            reasons=[
                "Prompt asks which files are not imported, requiring import-graph coverage analysis.",
                "The explicitly supplied path is authoritative and open-file context is ignored.",
            ],
            rejected_routes=["project_search", "target_discovery", "dcc_execute", "llm.chat"],
        ))

    early_project_fact_query = (
        (
            re.search(r"\b(what|which|where|list|show|find|first|how many|arguments|args|required|dependencies|classes|functions|methods)\b", lower)
            or re.search(r"\b(callers|callees|called by|uses|usages|references)\b", lower)
            or re.search(r"\bis\s+there\s+(?:a\s+)?(?:function|method|class|symbol)\b", lower)
        )
        and (
            file_ref
            or symbol_ref
            or _looks_like_read_only_project_question(lower)
            or re.search(r"\b(project|file|files|function|functions|class|classes|method|methods|symbol|symbols|import|imports|dependency|dependencies|python|py|argument|arguments|args|caller|callers|callee|callees)\b", lower)
        )
        and not re.search(r"\b(then|after that|and then|go ahead|do it|apply|execute|run|actually add|actually create|make the change)\b", lower)
    )
    if early_project_fact_query and not re.search(r"\b(create|build|add|implement|write|modify|update|fix|patch|wire|connect)\b.*\b(ui|tool|feature|code|file|class|function|method)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.86,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for indexed project/code facts before any action-graph or host execution."],
            rejected_routes=["action_graph", "dcc_execute", "dcc_prototype", "unreal_capability"],
        ))

    if _is_unreal_animation_blueprint_feature_request(lower):
        return _finalize_with_context(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            target_identifier="animation_blueprint.feature_request",
            operation_mode="plan_or_execute",
            mutation_scope="dcc_scene_mutation",
            confidence=0.86,
            requires_confirmation=not no_execute,
            requires_dcc_connection=not no_execute,
            requires_plan=True,
            required_context=[
                "unreal_reflection_index",
                "capability_graph",
                "animation_blueprint_context",
                "argument_validation",
            ],
            model_tier="local_code",
            task_graph=_gameplay_feature_task_graph(text, read_only=no_execute),
            reasons=[
                "Prompt references an Unreal animation blueprint/ABP workflow even without explicitly naming Unreal.",
                "Animation blueprint feature requests should use Unreal capability planning before mutation.",
            ],
            alternatives=[
                {"route": "target_discovery", "reason": "Use if the user meant local code edits rather than live Unreal asset work."},
            ],
        ), lower)

    if _is_vague_senior_improvement(lower):
        return _finalize_with_context(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="senior_investigation",
            host=host,
            confidence=0.78,
            operation_mode="investigate",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "current_behavior", "failure_modes"],
            model_tier="local_code",
            reasons=["Prompt is a broad senior-level improvement request; investigate the failing dimension before editing."],
            alternatives=[
                {"route": "target_discovery", "reason": "Use after the failing dimension and edit target are identified."},
            ],
        ))

    if not host and re.search(r"\b(project details|project tree|tree refresh|tab change|prompt label|startup|ui)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="application_code_architecture",
            host=host,
            confidence=0.84,
            operation_mode="investigate",
            mutation_scope="read_only" if no_execute else "",
            requires_confirmation=not no_execute and bool(re.search(r"\b(fix|change|update|stop|avoid|make)\b", lower)),
            required_context=["target_discovery", "symbol_index", "application_ui_code"],
            model_tier="local_code",
            reasons=["Prompt names Tech Connector UI/project behavior; do not promote generic open/refresh language to Unreal navigation."],
            rejected_routes=["unreal_capability", "dcc_execute", "dcc_prototype"],
        ))

    if not host and re.search(r"\b(importing|imported|imports?|api)\b", lower) and re.search(r"\b(find|where|anywhere|are we|check|inspect|review|load)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.86,
            operation_mode="query",
            mutation_scope="read_only",
            required_context=["project_index", "symbol_index", "import_graph"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for project API/import/load evidence, not an Unreal capability."],
            rejected_routes=["unreal_capability", "dcc_execute", "dcc_prototype"],
        ))

    if not host and (
        re.search(r"\b[\w.-]+\.py\b", lower)
        or re.search(r"\b(py_compile|unittest|pytest|focused tests?|test suite|prompt tests?)\b", lower)
    ):
        is_execution = bool(re.search(r"\b(run|execute|compile|test)\b", lower))
        return _finalize_with_context(PromptRouteDecision(
            route="function_execution" if is_execution else "project_search",
            provider="function_execution" if is_execution else "project_search",
            intent_category="project_tooling" if is_execution else "project_exploration",
            host=host,
            confidence=0.84,
            operation_mode="execute" if is_execution else "query",
            mutation_scope="read_only",
            required_context=["project_files", "test_runner"],
            model_tier="none_deterministic",
            reasons=["Prompt names Python/project test artifacts; generic run/open language must not promote to Unreal."],
            rejected_routes=["unreal_capability", "dcc_execute", "dcc_prototype"],
        ))

    if not host and str(known_unreal_operation.get("operation_key") or "").startswith("navigation."):
        host = "unreal"
    if not known_unreal_operation and host == "unreal":
        try:
            from tech_connector.services.unreal.unreal_operation_service import unreal_prompt_to_operation, UNREAL_OPERATIONS
            op_key = unreal_prompt_to_operation(text)
            if op_key and op_key in UNREAL_OPERATIONS:
                op = UNREAL_OPERATIONS[op_key]
                if op.mutates_project or op_key in {"project.debug", "blueprint.compile"}:
                    known_unreal_operation = {
                        "operation_key": op_key,
                        "function": op.function,
                        "mutates_project": bool(op.mutates_project),
                        "required": list(op.required),
                    }
        except Exception:
            pass

    if (
        re.search(r"\b(dead|unused|unresolved|missing|broken)\b", lower)
        and re.search(r"\b(import|imports|code|files|functions|classes|dependencies)\b", lower)
        and not re.search(r"\b(docstring|docstrings|function docs|function documentation|param docs|parameter docs)\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="project_health",
            provider="project_health",
            intent_category="code_health",
            host=host,
            confidence=0.86,
            required_context=["dependency_graph", "call_graph", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for deterministic code health/dependency facts."],
        ))

    if re.search(r"\b(circular import|circular imports|circular dependency|circular dependencies|import cycle|dependency cycle)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_health",
            provider="project_health",
            intent_category="code_health",
            host=host,
            confidence=0.88,
            required_context=["dependency_graph", "import_graph"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for cycle detection, which should come from the dependency/import graph."],
        ))

    if re.search(r"\b(find|check|diagnose|inspect|review)\b", lower) and re.search(r"\b(problem|issue|bug|broken|error|failure)\b", lower) and re.search(r"\b(then|before|after|ask before|fix|fixing)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="guided_code_fix",
            host=host,
            confidence=0.77,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for a staged diagnose-then-fix flow with confirmation before mutation."],
        ))

    if re.search(r"\b(memory leak|memory leaks|resource leak|resource leaks|race condition|race conditions|thread safety|security issue|security issues|exception handling|error recovery)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="quality_audit",
            host=host,
            confidence=0.76,
            required_context=["symbol_index", "call_graph", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for semantic quality risks; use indexed evidence first, then bounded code reasoning if needed."],
            alternatives=[{"route": "target_discovery", "reason": "Use if the user asks to apply fixes after the audit."}],
        ))

    if re.search(r"\b(unclear|bad|poor|confusing|ambiguous|inconsistent)\b", lower) and re.search(r"\b(name|names|naming|variable|variables|function|functions|api|apis)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="quality_audit",
            provider="project_search",
            intent_category="naming_quality",
            host=host,
            confidence=0.74,
            required_context=["symbol_index", "code_chunks"],
            model_tier="local_fast",
            reasons=["Prompt asks for naming clarity analysis grounded in indexed symbols."],
            alternatives=[{"route": "target_discovery", "reason": "Use if the user asks to rename or change the code."}],
        ))

    if re.search(r"\b(optimize|profile|performance|faster|efficient|efficiency|startup|allocations|memory usage|disk io|database queries|rendering|caching|background work|hang|freeze|freezing|ui hang|ui hangs|responsive|responsiveness)\b", lower):
        wants_change = bool(re.search(r"\b(make|improve|reduce|change|fix|update|refactor|speed up|harden|patch|repair)\b", lower))
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery" if wants_change else "quality_audit",
            provider="target_discovery" if wants_change else "project_search",
            intent_category="performance",
            host=host,
            confidence=0.78,
            requires_confirmation=wants_change,
            required_context=["symbol_index", "call_graph", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for performance work; route to audit unless it explicitly asks for code changes."],
        ))

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, raw_text if op_key == "script.run" else text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "", [])
                ]
                return _finalize_with_context(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                    rejected_routes=["action_graph", "project_search", "target_discovery"],
                ))
        except Exception:
            pass

    if host == "unreal" and known_unreal_operation:
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        is_navigation = operation_key.startswith("navigation.")
        if is_navigation:
            return _finalize_with_context(PromptRouteDecision(
                route="unreal_capability",
                provider="unreal",
                intent_category="dcc_unreal_capability",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=str(operation_key or known_unreal_operation.get("function") or execution_callable),
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                operation_mode="navigate",
                target_type="dcc_navigation",
                mutation_scope="read_only",
                risk_level="low",
                can_execute_directly=True,
                confidence=0.92,
                requires_confirmation=False,
                required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=[
                    "Prompt references a registered Unreal navigation operation; route before generic action-graph grammar.",
                ],
                rejected_routes=["pipeline_graph", "action_graph"],
            ))

    try:
        from tech_connector.services.action_planner_service import should_route_to_action_graph
        action_graph = should_route_to_action_graph(text, roots)
    except Exception:
        action_graph = False

    if action_graph:
        return _finalize_with_context(PromptRouteDecision(
            route="pipeline_graph" if re.search(r"\b(pipeline|workflow|node|graph)\b", lower) else "action_graph",
            provider="action_graph",
            intent_category="workflow_pipeline",
            host=host,
            confidence=0.86 if file_ref else 0.74,
            required_context=["project_index", "symbol_index", "workflow_graph"],
            reasons=["Prompt matches deterministic action-graph grammar."],
            rejected_routes=["dcc_execute", "dcc_prototype", "unreal_capability"],
        ))

    if host == "unreal" and _is_unreal_live_query(lower):
        target = "unreal_query"
        if re.search(r"\b(selection|selected|selected actors|selected assets|what is selected|what's selected)\b", lower):
            target = "selection"
        elif re.search(r"\b(level|world|current|loaded|active)\b", lower):
            target = "level"
        elif re.search(r"\b(skeleton|skeletons)\b", lower):
            target = "skeletons"
        elif re.search(r"\b(mesh|meshes|static mesh)\b", lower):
            target = "meshes"
        elif re.search(r"\b(blueprint|blueprints|control rig|anim blueprint)\b", lower):
            target = "blueprint"
        elif re.search(r"\b(asset|assets)\b", lower):
            target = "assets"
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host="unreal",
            target_identifier=target,
            callable_name=str(known_unreal_operation.get("function") or ""),
            confidence=0.88,
            requires_confirmation=False,
            required_context=["dcc_connection", "unreal_capability_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for read-only Unreal context from registered/base Unreal Python capabilities."],
            rejected_routes=["dcc_execute", "target_discovery"],
        ))

    if host == "unreal" and known_unreal_operation:
        mutates = bool(known_unreal_operation.get("mutates_project"))
        operation_key = str(known_unreal_operation.get("operation_key") or "")
        is_navigation = operation_key.startswith("navigation.")
        if operation_key == "niagara.attach_editable_character_fx":
            return _finalize_with_context(PromptRouteDecision(
                route="dcc_execute",
                confidence=0.96,
                provider="unreal",
                intent_category="dcc_execution",
                host="unreal",
                callable_name=str(known_unreal_operation.get("function") or execution_callable),
                target_identifier=operation_key,
                keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
                requires_confirmation=mutates and not no_execute,
                required_context=["dcc_connection", "resolved_callable", "argument_validation", "unreal_blueprint_context"],
                task_graph=_dcc_operation_task_graph(
                    text,
                    host="unreal",
                    operation_key=operation_key,
                    callable_name=str(known_unreal_operation.get("function") or execution_callable),
                    read_only=no_execute or not mutates,
                ),
                missing_info=list(known_unreal_operation.get("required") or []),
                model_tier="none_deterministic",
                reasons=[
                    f"Prompt references executable registered Unreal operation: {operation_key}.",
                    "Route directly to DCC execution so the UI can run the composite Unreal operation instead of stopping at capability planning.",
                ],
                rejected_routes=["unreal_capability", "pipeline_graph", "action_graph"],
            ))
        semantic_graph_required = False
        try:
            from tech_connector.services.unreal.semantic_graph_service import is_unreal_graph_modification_request

            semantic_graph_required = is_unreal_graph_modification_request(text)
        except Exception:
            semantic_graph_required = bool(re.search(r"\b(graph|blueprint|node|pin|state machine|anim graph|control rig)\b", lower))
        required_context = ["unreal_reflection_index", "capability_graph", "argument_validation"]
        if semantic_graph_required:
            required_context.extend([
                "semantic_graph_understanding",
                "graph_node_pin_link_index",
                "existing_behavior_preservation",
                "similar_project_patterns",
            ])
        return _finalize_with_context(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            callable_name=str(known_unreal_operation.get("function") or execution_callable),
            target_identifier=str(operation_key or known_unreal_operation.get("function") or execution_callable),
            keyword_args=dict(known_unreal_operation.get("keyword_args") or {}),
            operation_mode="navigate" if is_navigation else "",
            target_type="dcc_navigation" if is_navigation else "",
            mutation_scope="read_only" if is_navigation else "",
            risk_level="low" if is_navigation else "",
            can_execute_directly=is_navigation,
            confidence=0.92,
            requires_confirmation=mutates and not no_execute,
            required_context=required_context,
            missing_info=list(known_unreal_operation.get("required") or []),
            model_tier="none_deterministic",
            reasons=[
                "Prompt references a registered/base Unreal Python callable; route directly to deterministic Unreal execution preparation.",
                "Unreal graph modification requests must build semantic graph understanding before mutation.",
            ] if semantic_graph_required else ["Prompt references a registered/base Unreal Python callable; route directly to deterministic Unreal execution preparation."],
        ))

    if host in {"maya", "blender", "houdini", "substance_painter", "motionbuilder", "unity"}:
        try:
            from tech_connector.game_engine.integration.dcc_operation_service import (
                dcc_prompt_to_operation,
                build_dcc_operation_params,
                MAYA_OPERATIONS,
                BLENDER_OPERATIONS,
                SUBSTANCE_PAINTER_OPERATIONS,
                MOTIONBUILDER_OPERATIONS,
                UNITY_OPERATIONS,
            )
            op_key = dcc_prompt_to_operation(host, text)
            if op_key:
                catalogs = {
                    "maya": MAYA_OPERATIONS,
                    "blender": BLENDER_OPERATIONS,
                    "substance_painter": SUBSTANCE_PAINTER_OPERATIONS,
                    "motionbuilder": MOTIONBUILDER_OPERATIONS,
                    "unity": UNITY_OPERATIONS,
                }
                op = catalogs[host][op_key]
                params = build_dcc_operation_params(host, op_key, raw_text if op_key == "script.run" else text)
                missing_info = [
                    arg for arg in op.required
                    if arg not in params or params.get(arg) in (None, "")
                ]
                rig_prereq_decision = _maya_rigging_prerequisite_decision(
                    host=host,
                    operation_key=op_key,
                    op_function=op.function,
                    text=text,
                    params=params,
                    no_execute=no_execute,
                )
                if rig_prereq_decision:
                    return _finalize_with_context(rig_prereq_decision, lower)
                return _finalize_with_context(PromptRouteDecision(
                    route="dcc_execute",
                    confidence=0.95,
                    provider="dcc",
                    intent_category="dcc_execution",
                    host=host,
                    callable_name=op.function,
                    target_identifier=op_key,
                    keyword_args=params,
                    requires_confirmation=op.mutates_project and not no_execute,
                    required_context=["dcc_connection", "resolved_callable", "argument_validation"],
                    missing_info=missing_info,
                    model_tier="none_deterministic",
                    reasons=[f"Prompt matches registered {host} operation: {op_key}."],
                ))
        except Exception:
            pass

    if host and re.search(r"\b(run|execute|call|test|launch)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_execute",
            provider="dcc",
            intent_category="dcc_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.90,
            requires_confirmation=not no_execute,
            required_context=["dcc_connection", "resolved_callable", "argument_validation"],
            model_tier="none_deterministic",
            reasons=[f"Prompt explicitly asks to run/execute in {host}."],
            rejected_routes=["project_search", "target_discovery"],
        ))

    if host and not _has_explicit_dcc_operation(lower) and re.search(r"\b(selection|selected|current file|scene path|scene name|current scene|current level|active level|selected actors|selected assets|what is selected|what's selected)\b", lower):
        target = "selection" if re.search(r"\b(selection|selected|selected actors|selected assets|what is selected|what's selected)\b", lower) else "scene"
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_query",
            provider="dcc",
            intent_category="dcc_query",
            host=host,
            target_identifier=target,
            confidence=0.84,
            requires_confirmation=False,
            required_context=["dcc_connection"],
            model_tier="none_deterministic",
            reasons=[f"Prompt asks for a read-only {host} host query."],
            rejected_routes=["dcc_execute", "target_discovery"],
        ))

    if (
        not host
        and not re.search(r"\brun\s+through\b", lower)
        and re.search(r"\b(run|execute|call|launch)\s+[A-Za-z_][A-Za-z0-9_]*\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="function_execution",
            provider="action_graph",
            intent_category="function_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.66,
            requires_confirmation=True,
            required_context=["symbol_index", "callable_metadata", "execution_environment"],
            missing_info=["execution_environment"],
            model_tier="none_deterministic",
            reasons=["Prompt asks to execute a function but does not specify where it should run."],
            alternatives=[
                {"route": "dcc_execute", "reason": "Use if the user names Maya, Unreal, Blender, or another host."},
                {"route": "project_search", "reason": "Use if the user meant explain rather than execute."},
            ],
        ))

    if host == "unreal" and re.search(r"\b(compile|spawn|duplicate|blueprint|asset|actor|refresh|inspect)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="unreal_capability",
            provider="unreal",
            intent_category="dcc_unreal_capability",
            host="unreal",
            confidence=0.84,
            requires_confirmation=bool(re.search(r"\b(compile|spawn|duplicate|create|modify|delete)\b", lower)) and not no_execute,
            required_context=["unreal_reflection_index", "capability_graph", "argument_validation"],
            model_tier="none_deterministic",
            reasons=["Prompt contains Unreal host plus Unreal capability terms."],
        ))

    if host and _looks_like_read_only_project_question(lower) and re.search(
        r"\b(find|identify|locate|use|reuse)\b.*\b(function|method|class|tool)\b.*\b(create|build|add|implement|write)\b.*\b(ui|tool|window|panel|interface|code)\b",
        lower,
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="code_edit",
            host=host,
            confidence=0.84,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks", "ui_patterns"],
            model_tier="local_code",
            reasons=["Prompt asks to discover an existing host-related function, then create project UI/code around it."],
            rejected_routes=["dcc_execute", "dcc_prototype", "project_search"],
        ))

    if host and _looks_like_read_only_project_question(lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.86,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt names a DCC host but asks for indexed project/code facts, not host execution."],
            rejected_routes=["dcc_execute", "dcc_prototype"],
        ))

    if host and _has_explicit_dcc_mutation(lower) and not no_execute:
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_execute",
            provider="dcc",
            intent_category="dcc_execution",
            host=host,
            callable_name=execution_callable,
            target_identifier=execution_callable,
            confidence=0.78,
            requires_confirmation=True,
            required_context=["dcc_connection", "resolved_callable", "argument_validation"],
            model_tier="none_deterministic",
            reasons=[f"Prompt explicitly requests a live {host} scene mutation."],
            rejected_routes=["project_search", "target_discovery", "action_graph"],
            route_candidates=route_candidates,
            selected_route_reason=f"Explicit live {host} mutation language selected DCC execution.",
        ))

    is_explanation = bool(re.search(r"\b(how to|how do|how can|how would|what would i|explain how|how should|can you tell me|can you show me|is there a way to)\b", lower))
    if host and re.search(r"\b(make|create|build|prototype|set up|setup|add)\b", lower) and not re.search(r"\b(pipeline|workflow)\b", lower) and not is_explanation:
        return _finalize_with_context(PromptRouteDecision(
            route="dcc_prototype",
            provider="dcc",
            intent_category="dcc_prototype",
            host=host,
            confidence=0.68,
            requires_confirmation=not no_execute,
            required_context=["dcc_connection", "scene_context", "capability_graph"],
            model_tier="local_code",
            reasons=[f"Prompt asks to create/prototype inside {host}."],
            alternatives=[{"route": "target_discovery", "reason": "Use if this is a code edit rather than an in-host operation."}],
        ))

    if re.search(r"\b(prototype|replacement)\b", lower) and re.search(r"\b(do not change|don't change|dont change|without changing|current code)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="feature_work",
            host=host,
            confidence=0.73,
            operation_mode="prototype",
            mutation_scope="read_only",
            requires_confirmation=False,
            required_context=["target_discovery", "symbol_index", "similar_implementations"],
            model_tier="local_code",
            risk_level="low",
            reasons=["Prompt asks for a prototype or replacement without changing current code."],
        ))

    if re.search(r"\b(edit|modify|change|update|refactor|improve|fix|add|implement|clean up|cleanup)\b", lower) and (
        file_ref or symbol_ref or re.search(r"\b(file|files|function|functions|class|classes|method|methods|module|modules|tool|tools|existing|current|code|route|routing|eval|evaluation|tests?)\b", lower)
    ):
        return _finalize_with_context(PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="code_edit",
            host=host,
            confidence=0.80,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "code_chunks"],
            model_tier="local_code",
            reasons=["Prompt asks for a code change and identifies a code target or target category."],
        ))

    if re.search(r"\b(prototype|implement|build|create|add support|add ui|add command|add tool|scaffold|new subsystem|new feature)\b", lower) and (
        re.search(r"\b(feature|tool|subsystem|integration|support|ui|command|workflow|pipeline node|tests?|replacement)\b", lower)
        or symbol_ref
    ):
        broad = bool(re.search(r"\b(subsystem|architecture|redesign|integration)\b", lower))
        decision = PromptRouteDecision(
            route="target_discovery",
            provider="target_discovery",
            intent_category="feature_work",
            host=host,
            confidence=0.76,
            requires_confirmation=True,
            required_context=["target_discovery", "symbol_index", "similar_implementations", "project_architecture"],
            model_tier="enterprise_optional" if broad else "local_code",
            reasons=["Prompt asks to add or prototype project code; first discover targets and existing patterns."],
            alternatives=[{"route": "dcc_prototype", "reason": "Use only if the user explicitly asks to create inside a connected DCC host."}],
        )
        if re.search(r"\b(do not change|don't change|dont change|without changing|replacement)\b", lower):
            decision.operation_mode = "prototype"
            decision.mutation_scope = "read_only"
            decision.requires_confirmation = False
            decision.can_execute_directly = False
            decision.risk_level = "low"
            decision.reasons.append("Prompt requested prototype/planning without changing current code.")
        return _finalize_with_context(decision, lower)

    if re.search(r"\b(explain|summarize|run through|how does|how do|how .+ works|why does|startup order|initialization|execution flow|architecture|what would i|how can|how would|how to|is there a way)\b", lower):
        return _finalize_with_context(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="code_understanding",
            host=host,
            confidence=0.72,
            required_context=["symbol_index", "code_chunks", "dependency_graph"],
            model_tier="local_fast",
            reasons=["Prompt asks for code understanding; gather indexed evidence before model explanation."],
        ))

    if (
        re.search(r"\b(what|which|where|list|show|find|first|how many|arguments|args|required|dependencies|classes|functions|methods)\b", lower)
        or re.search(r"\b(callers|callees|called by|uses|usages|references)\b", lower)
        or re.search(r"\bis\s+there\s+(?:a\s+)?(?:function|method|class|symbol)\b", lower)
    ) and (
        file_ref
        or symbol_ref
        or re.search(r"\b(project|file|files|function|functions|class|classes|method|methods|symbol|symbols|import|imports|dependency|dependencies|python|py|argument|arguments|args|caller|callers|callee|callees)\b", lower)
    ):
        return _finalize_decision(PromptRouteDecision(
            route="project_search",
            provider="project_search",
            intent_category="project_exploration",
            host=host,
            confidence=0.82,
            required_context=["project_index", "symbol_index"],
            model_tier="none_deterministic",
            reasons=["Prompt asks for indexed project/code facts."],
            rejected_routes=["dcc_execute"],
        ), lower)

    if re.search(r"\b(github|repo|repository|ingest|import)\b", lower) and re.search(r"\b(search|find|ingest|import|use|bring in)\b", lower):
        return _finalize_decision(PromptRouteDecision(
            route="github_ingest",
            provider="ui",
            intent_category="repository_ingestion",
            host=host,
            confidence=0.70,
            requires_confirmation=True,
            required_context=["github_search", "repository_selection"],
            model_tier="local_fast",
            reasons=["Prompt asks for repository search/import/ingestion as part of a workflow."],
        ), lower)

    return _finalize_decision(PromptRouteDecision(
        route="chat",
        provider="llm",
        intent_category="general_chat",
        host=host,
        confidence=0.35,
        model_tier="local_fast",
        reasons=["No deterministic route exceeded the confidence threshold."],
        semantic_execution_contract=semantic_execution_contract,
        alternatives=[
            {"route": "project_search", "reason": "Use for indexed project facts."},
            {"route": "target_discovery", "reason": "Use for code edits/refactors."},
            {"route": "dcc_execute", "reason": "Use for running a function inside a DCC."},
        ],
    ), lower)


def should_prepare_with_engine(prompt: str, *, project_roots: list[str] | None = None, active_path: str | None = None) -> bool:
    return classify_prompt_route(prompt, project_roots=project_roots, active_path=active_path).provider in ENGINE_PROVIDERS
