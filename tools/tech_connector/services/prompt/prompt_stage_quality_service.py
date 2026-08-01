from __future__ import annotations

"""Cross-stage prompt quality preservation audit.

This service verifies that request meaning and implementation quality survive
the full prompt path: semantic context, validation, route selection, capability
planning, and optional engine target dispatch.
"""

from time import perf_counter
from typing import Any, Iterable

from reasoning_runtime.prompt import (
    PromptStageQualityReport,
    StageQualityCheck,
    extract_plan_verification,
)


def audit_prompt_stage_quality(
    prompt: str,
    *,
    project_roots: Iterable[str] = (),
    host_hint: str = "",
    expected_routes: Iterable[str] = (),
    expected_patterns: Iterable[str] = (),
    required_actions: Iterable[str] = (),
    required_callables: Iterable[str] = (),
    require_quality_bar: bool = False,
    require_temp_workspace_validation: bool = False,
    require_plan_match: bool = False,
    include_engine_dispatch: bool = False,
    expected_engine_actions: Iterable[str] = (),
    expected_selected_target_suffix: str = "",
) -> PromptStageQualityReport:
    from reasoning_runtime.engine.request_context import RequestContext
    from tech_connector.engine.request_engine import RequestEngine
    from tech_connector.services.prompt.prompt_execution_context_service import (
        build_prompt_execution_context,
        validate_prompt_understanding,
    )
    from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

    started = perf_counter()
    checks: list[StageQualityCheck] = []

    def add(stage: str, check: str, ok: bool, detail: str = "", expected: Any = None, actual: Any = None) -> None:
        checks.append(StageQualityCheck(stage=stage, check=check, ok=bool(ok), detail=detail, expected=expected, actual=actual))

    roots = list(project_roots or [])
    context = build_prompt_execution_context(
        prompt,
        host_hint=host_hint,
        decision_facts={"project_roots": roots, "settings": {"ai_work_memory_enabled": False}},
    )
    validation = validate_prompt_understanding(context)
    decision = classify_prompt_route(prompt, project_roots=roots, execution_context=context).to_dict()
    context.attach_execution_decision(decision)

    planning = dict(context.planning_result or {})
    contract = dict(context.semantic_execution_contract or {})
    task_graph = dict(context.task_graph or {})
    plan = dict(decision.get("capability_gap_plan") or {})
    actions = [str(item.get("action_type") or "") for item in plan.get("mixed_operation_sequence") or [] if isinstance(item, dict)]
    callables = _planned_callables(plan)
    patterns = [str(item) for item in plan.get("matched_patterns") or []]
    quality_bars = _collect_key(plan, "quality_bar")

    add("source_prompt", "normalized_prompt_preserved", context.normalized_prompt == " ".join(str(prompt).split()), actual=context.normalized_prompt)
    add("semantic_context", "goal_not_lost", bool(contract.get("goal") or planning.get("interpreted_request") or task_graph.get("primary_goal")), actual={
        "contract_goal": contract.get("goal"),
        "planning_request": planning.get("interpreted_request"),
        "task_primary_goal": task_graph.get("primary_goal"),
    })
    add("understanding_validation", "valid_or_explicit_clarification", validation.valid or validation.clarification_required, actual=validation.to_dict())
    add("route_decision", "route_selected", bool(decision.get("route") and decision.get("provider")), actual={"route": decision.get("route"), "provider": decision.get("provider")})

    expected_route_set = {str(item) for item in expected_routes if str(item)}
    if expected_route_set:
        add("route_decision", "expected_route_preserved", str(decision.get("route") or "") in expected_route_set, expected=sorted(expected_route_set), actual=decision.get("route"))

    expected_pattern_set = {str(item) for item in expected_patterns if str(item)}
    if expected_pattern_set:
        missing_patterns = sorted(expected_pattern_set - set(patterns))
        add("capability_plan", "expected_patterns_preserved", not missing_patterns, expected=sorted(expected_pattern_set), actual=patterns, detail=", ".join(missing_patterns))

    required_action_list = [str(item) for item in required_actions if str(item)]
    if required_action_list:
        add("capability_plan", "required_actions_preserved_in_order", _contains_subsequence(actions, required_action_list), expected=required_action_list, actual=actions)
        missing_calls = [
            action for action in required_action_list
            if not _action_has_planned_callable(plan, action)
        ]
        add("capability_plan", "required_actions_have_callable_plans", not missing_calls, expected=required_action_list, actual={action: _callables_for_action(plan, action) for action in required_action_list}, detail=", ".join(missing_calls))

    required_callable_list = [str(item) for item in required_callables if str(item)]
    if required_callable_list:
        missing_callables = [
            item for item in required_callable_list
            if not any(item in callable_name for callable_name in callables)
        ]
        add("capability_plan", "required_callables_preserved", not missing_callables, expected=required_callable_list, actual=callables, detail=", ".join(missing_callables))

    if require_quality_bar:
        add("quality_bar", "quality_bar_present", bool(quality_bars), actual=quality_bars[:2])
        if quality_bars:
            best = dict(quality_bars[0])
            add("quality_bar", "quality_bar_has_proof_and_promotion", bool(best.get("current_level") and best.get("proven") and best.get("promotion_requirements")), actual=best)

    if require_temp_workspace_validation:
        add("quality_bar", "temp_workspace_validation_planned", "code.validate_patch_in_temp_workspace" in actions, actual=actions)

    if require_plan_match:
        plan_verification = extract_plan_verification(decision.get("request_plan_verification"))
        if not plan_verification:
            plan_verification = extract_plan_verification(task_graph)
        if not plan_verification:
            plan_verification = extract_plan_verification(context.planning_result or {})
        if not plan_verification:
            add("capability_plan", "request_plan_verification_present", False, detail="No plan verification payload found.")
        else:
            matches_request = plan_verification.get("matches_request")
            if isinstance(matches_request, str):
                raw_match = matches_request.strip().lower()
                matches_request = raw_match not in {"false", "0", "no", "off"}
            add(
                "capability_plan",
                "request_plan_verification_matches",
                matches_request is not False,
                expected=True,
                actual=matches_request,
                detail=(
                    str(plan_verification.get("reason") or "")
                    if matches_request is False else ""
                ),
            )
            if matches_request is False:
                missing = plan_verification.get("missing") or plan_verification.get("missing_requirements") or []
                distorted = plan_verification.get("distorted") or plan_verification.get("wrong") or plan_verification.get("distortions") or []
                unsupported = plan_verification.get("unsupported_claims") or plan_verification.get("unsupported_features") or []
                add(
                    "capability_plan",
                    "plan_verification_gap_details",
                    False,
                    actual={
                        "missing": missing,
                        "distorted": distorted,
                        "unsupported": unsupported,
                    },
                    detail="Plan verification reports gaps.",
                )

    engine_action = ""
    selected_target = ""
    engine_metadata: dict[str, Any] = {}
    if include_engine_dispatch:
        engine = RequestEngine(progress=lambda _event: None, activity=lambda _event: None)
        result = engine.process(RequestContext(text=prompt, project_roots=tuple(roots), extras={"settings": {"ai_work_memory_enabled": False}}))
        engine_action = str(result.action or "")
        engine_metadata = dict(result.metadata or {})
        discovery = dict(engine_metadata.get("discovery") or {})
        resolution = dict(discovery.get("target_resolution") or engine_metadata.get("target_resolution") or {})
        selected_target = str(engine_metadata.get("selected_target") or discovery.get("selected_path") or resolution.get("selected_path") or "")
        expected_actions = {str(item) for item in expected_engine_actions if str(item)}
        if expected_actions:
            add("engine_dispatch", "expected_engine_action", engine_action in expected_actions, expected=sorted(expected_actions), actual=engine_action)
        if expected_selected_target_suffix:
            add("engine_dispatch", "selected_target_preserved", selected_target.replace("\\", "/").endswith(expected_selected_target_suffix.replace("\\", "/")), expected=expected_selected_target_suffix, actual=selected_target)

    elapsed_ms = (perf_counter() - started) * 1000.0
    passed = sum(1 for item in checks if item.ok)
    score = passed / len(checks) if checks else 1.0
    return PromptStageQualityReport(
        prompt=prompt,
        ok=all(item.ok for item in checks),
        score=score,
        elapsed_ms=elapsed_ms,
        route=str(decision.get("route") or ""),
        provider=str(decision.get("provider") or ""),
        intent_category=str(decision.get("intent_category") or ""),
        planning_mode=str(planning.get("planning_mode") or ""),
        matched_patterns=patterns,
        operation_sequence=actions,
        planned_callables=callables,
        engine_action=engine_action,
        selected_target=selected_target,
        checks=checks,
        artifacts={
            "validation": validation.to_dict(),
            "semantic_contract": contract,
            "planning_result": planning,
            "task_graph": task_graph,
            "decision": decision,
            "engine_metadata": engine_metadata,
        },
    )


def _planned_callables(plan: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in plan.get("mixed_operation_sequence") or []:
        if not isinstance(item, dict):
            continue
        call = dict(item.get("planned_call") or {})
        callable_name = str(call.get("callable") or call.get("operation") or call.get("function") or "")
        if callable_name:
            result.append(callable_name)
    return result


def _callables_for_action(plan: dict[str, Any], action: str) -> list[str]:
    result: list[str] = []
    for item in plan.get("mixed_operation_sequence") or []:
        if not isinstance(item, dict) or str(item.get("action_type") or "") != action:
            continue
        call = dict(item.get("planned_call") or {})
        callable_name = str(call.get("callable") or call.get("operation") or call.get("function") or "")
        if callable_name:
            result.append(callable_name)
    return result


def _action_has_planned_callable(plan: dict[str, Any], action: str) -> bool:
    return bool(_callables_for_action(plan, action))


def _contains_subsequence(values: list[str], expected: list[str]) -> bool:
    if not expected:
        return True
    index = 0
    for value in values:
        if value == expected[index]:
            index += 1
            if index == len(expected):
                return True
    return False


def _collect_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        if key in value:
            found.append(value[key])
        for nested in value.values():
            found.extend(_collect_key(nested, key))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_collect_key(nested, key))
    return found

