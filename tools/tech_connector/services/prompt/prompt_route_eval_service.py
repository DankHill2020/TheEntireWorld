from __future__ import annotations

"""Deterministic prompt-route evaluation helpers.

The optional Ollama fuzzer discovers new phrasings; this module scores the
reviewed corpus that should stay stable in normal tests and local benchmarks.
"""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Iterable


@dataclass
class PromptRouteEvalCase:
    id: str
    prompt: str
    expected_routes: set[str]
    category: str = "uncategorized"
    max_ms: float = 250.0
    expected_mutation_scope: str = ""
    code_prompt_profile: dict[str, str] = field(default_factory=dict)
    expected_provider: str = ""
    expected_requires_confirmation: bool | None = None
    expected_requires_execution: bool | None = None


@dataclass
class PromptRouteEvalRow:
    id: str
    category: str
    prompt: str
    expected_routes: list[str]
    actual_route: str
    elapsed_ms: float
    ok: bool
    mutation_scope: str = ""
    expected_mutation_scope: str = ""
    max_ms: float = 250.0
    timing_ok: bool = True
    code_prompt_profile: dict[str, str] = field(default_factory=dict)
    provider: str = ""
    requires_confirmation: bool = False
    requires_execution: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed_ms"] = round(self.elapsed_ms, 3)
        return data


@dataclass
class PromptRouteEvalReport:
    total: int
    passed: int
    failed: int
    accuracy: float
    average_ms: float
    max_ms: float
    by_category: dict[str, dict[str, Any]] = field(default_factory=dict)
    rows: list[PromptRouteEvalRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": round(self.accuracy, 4),
            "average_ms": round(self.average_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "by_category": self.by_category,
            "rows": [row.to_dict() for row in self.rows],
        }


def load_prompt_route_eval_cases(path: str | Path) -> list[PromptRouteEvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[PromptRouteEvalCase] = []
    for item in data:
        expected = {
            str(route).strip()
            for route in item.get("expected_routes") or []
            if str(route).strip()
        }
        cases.append(
            PromptRouteEvalCase(
                id=str(item.get("id") or "").strip(),
                prompt=str(item.get("prompt") or ""),
                expected_routes=expected,
                category=str(item.get("category") or "uncategorized"),
                max_ms=float(item.get("max_ms") or 250.0),
                expected_mutation_scope=str(item.get("expected_mutation_scope") or ""),
                code_prompt_profile=dict(item.get("code_prompt_profile") or {}),
                expected_provider=str(item.get("expected_provider") or ""),
                expected_requires_confirmation=(
                    bool(item["expected_requires_confirmation"])
                    if "expected_requires_confirmation" in item
                    else None
                ),
                expected_requires_execution=(
                    bool(item["expected_requires_execution"])
                    if "expected_requires_execution" in item
                    else None
                ),
            )
        )
    return cases


def evaluate_prompt_route_cases(
    cases: Iterable[PromptRouteEvalCase],
    *,
    classifier: Callable[..., Any] | None = None,
    project_roots: list[str] | None = None,
    include_details: bool = False,
) -> PromptRouteEvalReport:
    if classifier is None:
        from tech_connector.services.prompt.prompt_route_service import classify_prompt_route

        classifier = classify_prompt_route

    rows: list[PromptRouteEvalRow] = []
    for case in cases:
        start = perf_counter()
        execution_context = None
        if include_details:
            from tech_connector.services.prompt.prompt_execution_context_service import build_prompt_execution_context

            execution_context = build_prompt_execution_context(
                case.prompt,
                decision_facts={"project_roots": list(project_roots or [])},
                fast_preview=True,
            )
        decision_kwargs: dict[str, Any] = {"project_roots": project_roots or []}
        if execution_context is not None:
            decision_kwargs["execution_context"] = execution_context.to_dict()
        decision = classifier(case.prompt, **decision_kwargs)
        if case.code_prompt_profile:
            from tech_connector.services.code_prompt_profile_service import (
                apply_code_prompt_profile_to_decision,
            )

            decision = apply_code_prompt_profile_to_decision(
                decision,
                case.code_prompt_profile,
            )
        elapsed_ms = (perf_counter() - start) * 1000.0
        actual_route = str(getattr(decision, "route", "") or "")
        mutation_scope = str(getattr(decision, "mutation_scope", "") or "")
        provider = str(getattr(decision, "provider", "") or "")
        requires_confirmation = bool(
            getattr(decision, "requires_confirmation", False)
        )
        requires_execution = bool(getattr(decision, "requires_execution", False))
        details = (
            _decision_details(decision, execution_context=execution_context, prompt=case.prompt)
            if include_details
            else {}
        )
        scope_ok = (
            not case.expected_mutation_scope
            or mutation_scope == case.expected_mutation_scope
        )
        timing_ok = elapsed_ms <= case.max_ms
        provider_ok = not case.expected_provider or provider == case.expected_provider
        confirmation_ok = (
            case.expected_requires_confirmation is None
            or requires_confirmation == case.expected_requires_confirmation
        )
        execution_ok = (
            case.expected_requires_execution is None
            or requires_execution == case.expected_requires_execution
        )
        ok = (
            actual_route in case.expected_routes
            and scope_ok
            and provider_ok
            and confirmation_ok
            and execution_ok
            and (timing_ok or include_details)
        )
        rows.append(
            PromptRouteEvalRow(
                id=case.id,
                category=case.category,
                prompt=case.prompt,
                expected_routes=sorted(case.expected_routes),
                actual_route=actual_route,
                elapsed_ms=elapsed_ms,
                ok=ok,
                mutation_scope=mutation_scope,
                expected_mutation_scope=case.expected_mutation_scope,
                max_ms=case.max_ms,
                timing_ok=timing_ok,
                code_prompt_profile=dict(case.code_prompt_profile),
                provider=provider,
                requires_confirmation=requires_confirmation,
                requires_execution=requires_execution,
                details=details,
            )
        )

    total = len(rows)
    passed = sum(1 for row in rows if row.ok)
    elapsed = [row.elapsed_ms for row in rows]
    by_category: dict[str, dict[str, Any]] = {}
    for category in sorted({row.category for row in rows}):
        subset = [row for row in rows if row.category == category]
        category_passed = sum(1 for row in subset if row.ok)
        category_elapsed = [row.elapsed_ms for row in subset]
        by_category[category] = {
            "total": len(subset),
            "passed": category_passed,
            "failed": len(subset) - category_passed,
            "accuracy": round(category_passed / len(subset), 4) if subset else 1.0,
            "average_ms": round(sum(category_elapsed) / len(category_elapsed), 3) if category_elapsed else 0.0,
            "max_ms": round(max(category_elapsed), 3) if category_elapsed else 0.0,
        }

    return PromptRouteEvalReport(
        total=total,
        passed=passed,
        failed=total - passed,
        accuracy=(passed / total) if total else 1.0,
        average_ms=(sum(elapsed) / len(elapsed)) if elapsed else 0.0,
        max_ms=max(elapsed) if elapsed else 0.0,
        by_category=by_category,
        rows=rows,
    )


def _decision_details(
    decision: Any,
    *,
    execution_context: Any | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    decision_dict = decision.to_dict() if hasattr(decision, "to_dict") else {}
    context_dict = (
        execution_context.to_dict()
        if hasattr(execution_context, "to_dict")
        else dict(execution_context or {})
    )
    returned_context = dict(decision_dict.get("execution_context") or {})
    merged_context = {**context_dict, **returned_context}
    planning_result = dict(merged_context.get("planning_result") or {})
    task_graph = dict(decision_dict.get("task_graph") or merged_context.get("task_graph") or {})
    contract = dict(decision_dict.get("semantic_execution_contract") or merged_context.get("semantic_execution_contract") or {})
    understanding = dict(decision_dict.get("request_understanding") or merged_context.get("request_understanding") or {})
    goals = [
        dict(goal)
        for goal in (
            task_graph.get("ordered_goals")
            or task_graph.get("goals")
            or task_graph.get("tasks")
            or []
        )
        if isinstance(goal, dict)
    ]
    details = {
        "route": decision_dict.get("route"),
        "confidence": decision_dict.get("confidence"),
        "provider": decision_dict.get("provider"),
        "intent_category": decision_dict.get("intent_category"),
        "host": decision_dict.get("host"),
        "mutation_scope": decision_dict.get("mutation_scope"),
        "requires_plan": decision_dict.get("requires_plan"),
        "requires_generation": decision_dict.get("requires_generation"),
        "requires_project_search": decision_dict.get("requires_project_search"),
        "requires_execution": decision_dict.get("requires_execution"),
        "requires_validation": decision_dict.get("requires_validation"),
        "requires_dcc_connection": decision_dict.get("requires_dcc_connection"),
        "can_execute_directly": decision_dict.get("can_execute_directly"),
        "required_context": list(decision_dict.get("required_context") or []),
        "missing_info": list(decision_dict.get("missing_info") or []),
        "reasons": list(decision_dict.get("reasons") or []),
        "selected_route_reason": decision_dict.get("selected_route_reason") or "",
        "route_candidates": list(decision_dict.get("route_candidates") or []),
        "rejected_routes": list(decision_dict.get("rejected_routes") or []),
        "operations": list(decision_dict.get("operations") or []),
        "deterministic_steps": list(decision_dict.get("deterministic_steps") or []),
        "context_resolvers": list(decision_dict.get("context_resolvers") or []),
        "planning_result": {
            "mode": planning_result.get("planning_mode"),
            "model_role": planning_result.get("model_role"),
            "authoritative": planning_result.get("authoritative"),
            "requires_deeper_planning": planning_result.get("requires_deeper_planning"),
            "confidence": planning_result.get("confidence"),
            "intent_category": planning_result.get("intent_category"),
            "primary_route": planning_result.get("primary_route"),
            "goal_type": planning_result.get("goal_type"),
            "deliverable": planning_result.get("deliverable"),
            "scope": planning_result.get("scope"),
            "target": planning_result.get("target"),
            "host": planning_result.get("host"),
            "behavior": planning_result.get("behavior"),
            "unknowns": list(planning_result.get("unknowns") or []),
            "reasons": list(planning_result.get("reasons") or []),
            "function_calls": list(planning_result.get("function_calls") or []),
            "deterministic_authority": dict(planning_result.get("deterministic_authority") or {}),
        },
        "understanding": {
            "primary_route": understanding.get("primary_route"),
            "primary_intent": understanding.get("primary_intent"),
            "primary_action": understanding.get("primary_action"),
            "requested_artifact": understanding.get("requested_artifact"),
            "goal_type": understanding.get("goal_type"),
            "confidence": understanding.get("confidence"),
            "mutation_requested": understanding.get("mutation_requested"),
            "read_only_requested": understanding.get("read_only_requested"),
            "requires_execution": understanding.get("requires_execution"),
            "requires_validation": understanding.get("requires_validation"),
            "reasons": list(understanding.get("reasons") or []),
        },
        "semantic_contract": {
            "goal": contract.get("goal"),
            "goal_type": contract.get("goal_type"),
            "deliverable_type": contract.get("deliverable_type"),
            "subject_type": contract.get("subject_type"),
            "subject_text": contract.get("subject_text"),
            "action": contract.get("action"),
            "behavior": contract.get("behavior"),
            "host_domain": contract.get("host_domain"),
            "read_only": contract.get("read_only"),
            "mutation_requested": contract.get("mutation_requested"),
            "execution_requested": contract.get("execution_requested"),
            "unresolved_fields": list(contract.get("unresolved_fields") or []),
            "expected_outputs": list(contract.get("expected_outputs") or []),
            "evidence_required": list(contract.get("evidence_required") or []),
            "success_definition": contract.get("success_definition"),
        },
        "task_graph": {
            "primary_goal": task_graph.get("primary_goal"),
            "goal_type": task_graph.get("goal_type"),
            "estimated_steps": task_graph.get("estimated_steps"),
            "required_context": list(task_graph.get("required_context") or []),
            "goals": goals,
        },
    }
    details["execution_rehearsal"] = _execution_rehearsal(prompt, details)
    return details


def _execution_rehearsal(prompt: str, details: dict[str, Any]) -> dict[str, Any]:
    plan = dict(details.get("planning_result") or {})
    contract = dict(details.get("semantic_contract") or {})
    goals = list((details.get("task_graph") or {}).get("goals") or [])
    function_calls = list(plan.get("function_calls") or [])
    operations = list(details.get("operations") or [])
    authoritative = bool(plan.get("authoritative"))
    deeper = bool(plan.get("requires_deeper_planning"))
    rehearsal_steps = []
    for goal in goals:
        goal = dict(goal)
        action = str(goal.get("action") or "")
        rehearsal_steps.append(
            {
                "goal_id": str(goal.get("task_id") or goal.get("goal_id") or goal.get("id") or ""),
                "goal_title": str(goal.get("title") or goal.get("objective") or ""),
                "depends_on": list(goal.get("depends_on") or []),
                "tool_or_function": _tool_for_goal(action, goal, function_calls),
                "would_do": _would_do_for_goal(action, goal, plan, contract),
                "expected_artifacts": list(goal.get("produces") or []),
                "approval_required": bool(goal.get("requires_confirmation") or (not goal.get("read_only", True))),
            }
        )
    return {
        "status": "ready" if authoritative and not deeper else "needs_deeper_planning",
        "summary": _rehearsal_summary(details, plan),
        "tool_sequence": _tool_sequence(function_calls, operations, rehearsal_steps),
        "steps": rehearsal_steps,
        "generated_outputs": _generated_outputs(prompt, details),
        "validation_plan": _validation_plan(prompt, details, goals),
        "blocking_feedback": _blocking_feedback(details, plan),
        "advisory_feedback": _advisory_feedback(plan),
    }


def _tool_for_goal(action: str, goal: dict[str, Any], calls: list[dict[str, Any]]) -> str:
    if action in {"search", "discover", "resolve", "inspect"}:
        for call in calls:
            if str(call.get("action_type") or "") == "search_project":
                return "search_project"
        return "project_index_or_symbol_search"
    if action in {"modify", "modify_code"}:
        return "apply_patch"
    if action == "execute":
        for call in calls:
            if str(call.get("action_type") or "") in {"execute_dcc", "execute_dcc_capability"}:
                return str(call.get("action_type"))
        return "execute_registered_operation"
    if action == "validate":
        return "pytest_or_host_validation"
    if action in {"design", "plan", "analyze"}:
        return "planner_reasoning"
    if action == "report":
        return "final_report"
    return action or "reasoning"


def _would_do_for_goal(
    action: str,
    goal: dict[str, Any],
    plan: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    target = str(goal.get("target") or plan.get("target") or contract.get("subject_text") or "resolved target")
    if action in {"search", "discover", "resolve"}:
        return f"Search for {target} and rank candidate files/assets/functions by behavioral evidence."
    if action == "inspect":
        return f"Read the resolved target and adjacent dependencies before designing changes."
    if action in {"design", "plan", "analyze"}:
        return "Convert evidence into an ordered implementation plan with dependencies, rollback, and validation gates."
    if action in {"modify", "modify_code"}:
        return "Apply the minimal scoped patch only after target evidence and dependencies are resolved."
    if action == "execute":
        return "Call the registered host operation after connection, argument validation, and approval."
    if action == "validate":
        return "Run the smallest available automated checks plus host-specific compile/state validation."
    if action == "report":
        return "Return changed files, evidence, validation results, warnings, and remaining risks."
    return str(goal.get("objective") or "")


def _tool_sequence(
    calls: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    for call in calls:
        sequence.append(
            {
                "kind": "planned_action_call",
                "name": str(call.get("action_type") or ""),
                "arguments": dict(call.get("arguments") or {}),
                "reason": str(call.get("reason") or ""),
            }
        )
    for op in operations:
        sequence.append(
            {
                "kind": "pipeline_operation",
                "name": str(op.get("operation") or op.get("id") or ""),
                "host": str(op.get("host") or ""),
                "arguments": dict(op.get("args") or {}),
                "depends_on": list(op.get("depends_on") or []),
            }
        )
    if not sequence:
        for step in steps:
            sequence.append(
                {
                    "kind": "goal_tool",
                    "name": step["tool_or_function"],
                    "goal_id": step["goal_id"],
                    "reason": step["would_do"],
                }
            )
    return sequence


def _generated_outputs(prompt: str, details: dict[str, Any]) -> list[dict[str, Any]]:
    lower = prompt.lower()
    route = str(details.get("route") or "")
    plan = dict(details.get("planning_result") or {})
    outputs: list[dict[str, Any]] = []
    if route == "dcc_execute" and str(details.get("host") or "") == "maya":
        operation = str(plan.get("target") or plan.get("behavior") or "")
        locator_match = re.search(r"\blocator(?:\s+named)?\s+([A-Za-z_][A-Za-z0-9_]*)\b", prompt, re.I)
        if operation == "scene.create_locator" or "locator" in lower:
            name = locator_match.group(1) if locator_match else "locator1"
            outputs.append(
                {
                    "kind": "dcc_python_preview",
                    "language": "python",
                    "target": "maya",
                    "code": f"import maya.cmds as cmds\ncmds.spaceLocator(name={name!r})",
                }
            )
    if "abp" in lower or "anim blueprint" in lower:
        try:
            from tech_connector.services.unreal.anim_blueprint_capability_service import (
                build_anim_blueprint_capability_plan,
            )

            outputs.append(build_anim_blueprint_capability_plan(prompt))
        except Exception as exc:
            outputs.append(
                {
                    "kind": "unreal_abp_capability_plan_error",
                    "target": "ABP",
                    "capability_gaps": [f"ABP capability planner failed: {exc}"],
                }
            )
    if route == "target_discovery" and str(details.get("mutation_scope") or "") == "file_modification":
        outputs.append(
            {
                "kind": "project_patch_preview",
                "target": plan.get("target") or "to be resolved by target discovery",
                "patch_shape": [
                    "search_project to resolve owning files",
                    "read candidate files and tests",
                    "apply_patch with the smallest behavior-preserving edit",
                    "run focused compile/tests",
                ],
            }
        )
    return outputs


def _validation_plan(prompt: str, details: dict[str, Any], goals: list[dict[str, Any]]) -> list[str]:
    lower = prompt.lower()
    validations = []
    if any(str(goal.get("action") or "") == "validate" for goal in goals):
        validations.append("Run validation goal after mutation/execution completes.")
    if str(details.get("host") or "") == "maya":
        validations.append("Verify Maya operation result via scene query and structured DCC response.")
    if "unreal" in lower or "abp" in lower or "blueprint" in lower:
        validations.append("Compile touched Unreal Blueprint/assets when Unreal is connected; otherwise report proposed validation.")
    if str(details.get("mutation_scope") or "") == "file_modification":
        validations.append("Run focused pytest/py_compile for changed Python files.")
    return validations or ["Return evidence-backed answer and residual risks."]


def _blocking_feedback(details: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    feedback = []
    audit = dict(plan.get("deterministic_authority") or {})
    if audit.get("requires_deeper_planning"):
        feedback.append("Fast deterministic preview is not authoritative; use deeper planning before executing.")
    for check in audit.get("hard_failures") or []:
        feedback.append(f"Hard authority check failed: {check}.")
    if details.get("requires_dcc_connection") and not details.get("can_execute_directly"):
        feedback.append("Direct host execution is gated until connection/approval is available.")
    return feedback


def _advisory_feedback(plan: dict[str, Any]) -> list[str]:
    audit = dict(plan.get("deterministic_authority") or {})
    hard = set(str(item) for item in audit.get("hard_failures") or [])
    return [
        f"Soft authority check failed: {check}."
        for check in audit.get("failed_checks") or []
        if str(check) not in hard
    ]


def _rehearsal_summary(details: dict[str, Any], plan: dict[str, Any]) -> str:
    if plan.get("authoritative"):
        return "The deterministic preview is strong enough to proceed through the listed tool sequence."
    return "The final route may be usable, but the deterministic preview needs deeper planning before mutation/execution."


def format_prompt_route_eval_detail(report: PromptRouteEvalReport) -> str:
    lines = [
        (
            f"Prompt route eval: {report.passed}/{report.total} passed, "
            f"accuracy={report.accuracy:.1%}, avg={report.average_ms:.1f}ms, max={report.max_ms:.1f}ms"
        )
    ]
    for row in report.rows:
        status = "PASS" if row.ok else "FAIL"
        details = row.details or {}
        plan = dict(details.get("planning_result") or {})
        audit = dict(plan.get("deterministic_authority") or {})
        task_graph = dict(details.get("task_graph") or {})
        contract = dict(details.get("semantic_contract") or {})
        understanding = dict(details.get("understanding") or {})
        lines.extend([
            "",
            f"## {row.id} [{status}]",
            f"Category: {row.category}",
            f"Prompt: {row.prompt}",
            f"Expected route(s): {', '.join(row.expected_routes)}",
            f"Actual route: {row.actual_route} | mutation_scope={row.mutation_scope or '(none)'}",
            f"Timing: {row.elapsed_ms:.1f}ms / budget {row.max_ms:.1f}ms | timing_ok={row.timing_ok}",
            f"Decision: intent={details.get('intent_category') or '(none)'} confidence={details.get('confidence')} provider={details.get('provider')}",
            f"Host: {details.get('host') or '(none)'} | requires_plan={details.get('requires_plan')} generation={details.get('requires_generation')} search={details.get('requires_project_search')} execution={details.get('requires_execution')} validation={details.get('requires_validation')}",
        ])
        if details.get("selected_route_reason"):
            lines.append(f"Selected reason: {details['selected_route_reason']}")
        _append_list(lines, "Reasons", details.get("reasons") or [])
        _append_list(lines, "Required context", details.get("required_context") or [])
        _append_list(lines, "Context resolvers", details.get("context_resolvers") or [])
        _append_list(lines, "Deterministic steps", details.get("deterministic_steps") or [])
        lines.extend([
            "Understanding:",
            f"- route={understanding.get('primary_route')} intent={understanding.get('primary_intent')} action={understanding.get('primary_action')} artifact={understanding.get('requested_artifact')}",
            f"- goal_type={understanding.get('goal_type')} confidence={understanding.get('confidence')} mutation={understanding.get('mutation_requested')} read_only={understanding.get('read_only_requested')}",
        ])
        _append_list(lines, "Understanding reasons", understanding.get("reasons") or [])
        lines.extend([
            "Semantic contract:",
            f"- goal={contract.get('goal')}",
            f"- deliverable={contract.get('deliverable_type')} subject={contract.get('subject_type')}:{contract.get('subject_text')} action={contract.get('action')}",
            f"- behavior={contract.get('behavior')}",
            f"- success={contract.get('success_definition')}",
        ])
        _append_list(lines, "Evidence required", contract.get("evidence_required") or [])
        _append_list(lines, "Unresolved fields", contract.get("unresolved_fields") or [])
        lines.extend([
            "Planning result:",
            f"- mode={plan.get('mode')} model_role={plan.get('model_role')} confidence={plan.get('confidence')} authoritative={plan.get('authoritative')} deeper={plan.get('requires_deeper_planning')}",
            f"- route={plan.get('primary_route')} intent={plan.get('intent_category')} goal_type={plan.get('goal_type')} deliverable={plan.get('deliverable')} scope={plan.get('scope')}",
            f"- target={plan.get('target') or '(none)'} host={plan.get('host') or '(none)'}",
            f"- behavior={plan.get('behavior') or '(none)'}",
        ])
        _append_list(lines, "Planning reasons", plan.get("reasons") or [])
        _append_list(lines, "Planning unknowns", plan.get("unknowns") or [])
        if audit:
            lines.append(
                f"Authority audit: authoritative={audit.get('authoritative')} confidence={audit.get('confidence')} deeper={audit.get('requires_deeper_planning')}"
            )
            for check in audit.get("checks") or []:
                mark = "ok" if check.get("ok") else "fail"
                lines.append(
                    f"- [{mark}] {check.get('id')} weight={check.get('weight')}: {check.get('evidence')}"
                )
        _append_function_calls(lines, plan.get("function_calls") or [])
        _append_operations(lines, details.get("operations") or [])
        _append_goals(lines, task_graph.get("goals") or [])
        _append_rehearsal(lines, details.get("execution_rehearsal") or {})
    return "\n".join(lines)


def _append_list(lines: list[str], title: str, values: list[Any]) -> None:
    if not values:
        return
    lines.append(f"{title}:")
    for value in values:
        lines.append(f"- {value}")


def _append_function_calls(lines: list[str], calls: list[dict[str, Any]]) -> None:
    if not calls:
        return
    lines.append("Planned function/action calls:")
    for index, call in enumerate(calls, start=1):
        lines.append(f"- {index}. {call.get('action_type')}: {call.get('reason') or ''}")
        arguments = call.get("arguments") or {}
        if arguments:
            lines.append(f"  args={json.dumps(arguments, sort_keys=True)}")


def _append_operations(lines: list[str], operations: list[dict[str, Any]]) -> None:
    if not operations:
        return
    lines.append("Pipeline operations:")
    for op in operations:
        lines.append(
            f"- {op.get('id')}: host={op.get('host')} operation={op.get('operation')} depends_on={op.get('depends_on') or []}"
        )
        if op.get("args"):
            lines.append(f"  args={json.dumps(op.get('args'), sort_keys=True)}")


def _append_goals(lines: list[str], goals: list[dict[str, Any]]) -> None:
    if not goals:
        return
    lines.append("Ordered goals:")
    for index, goal in enumerate(goals, start=1):
        goal_id = goal.get("task_id") or goal.get("goal_id") or goal.get("id")
        lines.append(
            f"- {index}. {goal_id}: {goal.get('title') or goal.get('objective') or ''}"
        )
        lines.append(
            f"  action={goal.get('action')} goal_type={goal.get('goal_type')} read_only={goal.get('read_only')} depends_on={goal.get('depends_on') or []}"
        )
        if goal.get("required_inputs"):
            lines.append(f"  required_inputs={goal.get('required_inputs')}")
        if goal.get("produces"):
            lines.append(f"  produces={goal.get('produces')}")
        if goal.get("success_condition"):
            lines.append(f"  success={goal.get('success_condition')}")


def _append_rehearsal(lines: list[str], rehearsal: dict[str, Any]) -> None:
    if not rehearsal:
        return
    lines.append("Execution rehearsal:")
    lines.append(f"- status={rehearsal.get('status')}")
    lines.append(f"- summary={rehearsal.get('summary')}")
    _append_list(lines, "Blocking feedback", rehearsal.get("blocking_feedback") or [])
    _append_list(lines, "Advisory feedback", rehearsal.get("advisory_feedback") or [])
    _append_list(lines, "Validation plan", rehearsal.get("validation_plan") or [])
    sequence = list(rehearsal.get("tool_sequence") or [])
    if sequence:
        lines.append("Tool sequence:")
        for index, item in enumerate(sequence, start=1):
            lines.append(f"- {index}. {item.get('name')} ({item.get('kind')})")
            if item.get("reason"):
                lines.append(f"  reason={item.get('reason')}")
            if item.get("arguments"):
                lines.append(f"  args={json.dumps(item.get('arguments'), sort_keys=True)}")
            if item.get("depends_on"):
                lines.append(f"  depends_on={item.get('depends_on')}")
    outputs = list(rehearsal.get("generated_outputs") or [])
    if outputs:
        lines.append("Generated/prepared outputs:")
        for output in outputs:
            lines.append(f"- {output.get('kind')} target={output.get('target')}")
            if output.get("code"):
                lines.append("  code:")
                for code_line in str(output.get("code")).splitlines():
                    lines.append(f"    {code_line}")
            if output.get("prepared_script"):
                lines.append("  prepared_script:")
                for code_line in str(output.get("prepared_script")).splitlines():
                    lines.append(f"    {code_line}")
            for key in ("service_functions", "assets_or_functions", "pseudo_steps", "patch_shape", "capability_gaps", "validation"):
                if output.get(key):
                    lines.append(f"  {key}:")
                    for value in output.get(key) or []:
                        lines.append(f"  - {value}")
            actual_steps = list(output.get("actual_steps") or [])
            if actual_steps:
                lines.append("  actual_steps:")
                for step in actual_steps:
                    lines.append(f"  - {step.get('id')}: {step.get('operation')}")
                    lines.append(f"    tool={step.get('tool')}")
                    if step.get("inputs"):
                        lines.append(f"    inputs={json.dumps(step.get('inputs'), sort_keys=True)}")
                    if step.get("produces"):
                        lines.append(f"    produces={step.get('produces')}")
            acquisition_plans = list(output.get("capability_acquisition_plans") or [])
            if acquisition_plans:
                lines.append("  capability_acquisition_plans:")
                for plan in acquisition_plans[:3]:
                    lines.append(f"  - {plan.get('requested_operation')}: {plan.get('status')}")
                    lines.append(f"    block_reason={plan.get('block_reason')}")
                    step_ids = [step.get("step_id") for step in plan.get("steps") or []]
                    lines.append(f"    steps={step_ids}")
            wrapper_plans = list(output.get("cpp_wrapper_plans") or [])
            if wrapper_plans:
                lines.append("  cpp_wrapper_plans:")
                for plan in wrapper_plans:
                    lines.append(f"  - {plan.get('operation')}: {plan.get('implementation_status')}")
                    lines.append(f"    capability={plan.get('capability')} function={plan.get('function_name')}")
                    lines.append(f"    python_call={plan.get('python_call')}")
                    if plan.get("warnings"):
                        lines.append(f"    warnings={plan.get('warnings')}")
                    phases = list(plan.get("progress_phases") or [])
                    if phases:
                        lines.append("    progress_phases:")
                        for phase in phases:
                            lines.append(
                                f"    - {phase.get('progress')}% {phase.get('id')}: {phase.get('message')}"
                            )
    steps = list(rehearsal.get("steps") or [])
    if steps:
        lines.append("Goal-by-goal execution:")
        for step in steps:
            lines.append(
                f"- {step.get('goal_id')}: tool={step.get('tool_or_function')} approval={step.get('approval_required')}"
            )
            lines.append(f"  would_do={step.get('would_do')}")
            if step.get("expected_artifacts"):
                lines.append(f"  expected_artifacts={step.get('expected_artifacts')}")
