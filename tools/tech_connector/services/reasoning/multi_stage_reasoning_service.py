"""Multi-stage reasoning orchestration for Tech Connector.

This layer does not execute work. It turns an already-classified prompt route
into a transparent sequence of specialist stages with focused inputs, evidence,
confidence, gates, and model recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReasoningStage:
    key: str
    title: str
    specialist: str
    responsibility: str
    context_inputs: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    verification_gate: tuple[str, ...] = ()
    deterministic_tools: tuple[str, ...] = ()
    model_tier: str = "none"
    confidence: float = 0.75
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    recommended_next_action: str = "continue"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "specialist": self.specialist,
            "responsibility": self.responsibility,
            "context_inputs": list(self.context_inputs),
            "expected_outputs": list(self.expected_outputs),
            "verification_gate": list(self.verification_gate),
            "deterministic_tools": list(self.deterministic_tools),
            "model_tier": self.model_tier,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "unknowns": list(self.unknowns),
            "risks": list(self.risks),
            "evidence": list(self.evidence),
            "recommended_next_action": self.recommended_next_action,
        }


def _uniq(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


def _risk_score(decision: dict[str, Any]) -> int:
    risk = str(decision.get("risk_level") or "").lower()
    score = {"low": 1, "medium": 2, "high": 3}.get(risk, 1)
    if decision.get("requires_confirmation"):
        score += 1
    if decision.get("requires_dcc_connection"):
        score += 1
    if decision.get("mutation_scope") not in {"", "read_only"}:
        score += 1
    return score


def _model_for_stage(stage: str, decision: dict[str, Any], risk_score: int) -> str:
    route_model = str(decision.get("model_capability") or "")
    if stage in {"intent_analysis", "discovery", "resource_discovery", "validation"}:
        return "none_or_local_fast"
    if stage in {"architecture", "pipeline_generation", "reflection"}:
        return "strong_reasoning" if risk_score >= 4 else "local_plan"
    if stage == "implementation":
        if route_model and route_model != "none":
            return route_model
        return "local_code" if decision.get("mutation_scope") not in {"", "read_only"} else "none"
    if stage in {"execution", "post_execution_validation"}:
        return "deterministic_provider"
    return "local_fast"


def _best_practice_evidence(prompt: str, host: str) -> tuple[tuple[str, ...], tuple[str, ...], str, bool]:
    try:
        from tech_connector.services.task_playbook_service import assess_best_practice_coverage, playbook_keys

        assessment = assess_best_practice_coverage(prompt, host=host, limit=3)
        evidence = []
        if assessment.matched_playbooks:
            evidence.append("local playbooks: " + ", ".join(playbook_keys(assessment.matched_playbooks)))
        evidence.extend(assessment.reasons)
        unknowns = []
        if assessment.should_offer_research:
            unknowns.append("authoritative best-practice research may improve reliability")
        return _uniq(evidence), _uniq(unknowns), assessment.confidence, assessment.should_offer_research
    except Exception:
        return (), ("best-practice coverage unavailable",), "low", False


def _studio_rule_evidence(prompt: str, host: str, task_type: str) -> tuple[str, ...]:
    try:
        from tech_connector.services.studio_profile_service import matching_studio_rules

        rules = matching_studio_rules(prompt, host=host, task_type=task_type, limit=4)
        return tuple(f"studio rule: {rule.key}" for rule in rules)
    except Exception:
        return ()


def _report_quality_evidence() -> tuple[str, ...]:
    try:
        from tech_connector.services.chat_report_service import documentation_quality_checklist

        return tuple("report quality: " + item for item in documentation_quality_checklist()[:3])
    except Exception:
        return ("report quality: include outcome, evidence, validation, and recovery",)


def build_reasoning_pipeline(
    prompt: str,
    decision: dict[str, Any] | None = None,
    *,
    thread_context: str = "",
    project_context: str = "",
    tool_context: str = "",
) -> dict[str, Any]:
    """Create a deterministic multi-stage orchestration plan for a request."""
    decision = dict(decision or {})
    senior = dict(decision.get("senior_prompt_analysis") or {})
    host = str(decision.get("host") or "")
    route = str(decision.get("route") or "chat")
    task_type = str(decision.get("intent_category") or route or "general")
    risk = _risk_score(decision)
    missing = _uniq(list(decision.get("missing_info") or []) + list(senior.get("unknown_or_ambiguous") or []))
    deterministic = _uniq(list(decision.get("deterministic_steps") or []) + list(senior.get("deterministic_tools_required") or []))
    context_resolvers = _uniq(list(decision.get("context_resolvers") or []) + list(senior.get("required_context") or []))
    best_evidence, best_unknowns, best_confidence, should_research = _best_practice_evidence(prompt, host)
    studio_evidence = _studio_rule_evidence(prompt, host, task_type)
    report_quality = _report_quality_evidence()
    gap_plan: dict[str, Any] = {}
    try:
        from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan

        gap_plan = dict(decision.get("capability_gap_plan") or {}) or build_goal_gap_plan(prompt, decision)
    except Exception:
        gap_plan = {}
    gap_missing = _uniq(
        [
            str(link.get("label") or link.get("to") or "")
            for link in list(gap_plan.get("missing_links") or [])[:6]
            if isinstance(link, dict)
        ]
    )
    gap_evidence = _uniq(
        [
            f"gap plan: {gap_plan.get('framework', '')}" if gap_plan else "",
            *[
                f"gap resolution option: {option.get('label', '')}"
                for option in list(gap_plan.get("resolution_options") or [])[:3]
                if isinstance(option, dict)
            ],
        ]
    )
    evidence_base = _uniq(
        [
            f"route={route}",
            f"provider={decision.get('provider') or 'unknown'}",
            f"confidence={decision.get('confidence', 0)}",
            *studio_evidence,
            *best_evidence,
        ]
    )
    can_execute = bool(decision.get("can_execute_directly")) and not missing
    mutation = str(decision.get("mutation_scope") or "")
    requires_plan = bool(decision.get("requires_plan") or risk >= 3)

    stages = [
        ReasoningStage(
            key="intent_analysis",
            title="Intent Analysis",
            specialist="Prompt Router",
            responsibility="Determine user goal, route, constraints, missing information, and whether clarification is required.",
            context_inputs=("current user request", "recent thread context", "active project/tool state"),
            expected_outputs=("route decision", "goal summary", "required context", "clarification blockers"),
            verification_gate=("route confidence is acceptable", "missing info is explicit", "mutation risk is classified"),
            deterministic_tools=("prompt classifier", "host detection", "compound-operation detector"),
            model_tier="none_or_local_fast",
            confidence=float(decision.get("confidence") or 0.5),
            unknowns=missing,
            evidence=evidence_base,
            recommended_next_action="clarify" if missing and not context_resolvers else "continue",
        ),
        ReasoningStage(
            key="discovery",
            title="Discovery / Context Gathering",
            specialist="Context Resolver",
            responsibility="Gather only the project, DCC, pipeline, and thread facts needed by later stages.",
            context_inputs=("route decision", *context_resolvers),
            expected_outputs=("focused context package", "verified target list", "available operation metadata"),
            verification_gate=("target evidence exists", "context package is narrow enough for downstream stages"),
            deterministic_tools=deterministic or ("project index", "symbol search", "operation registry"),
            model_tier=_model_for_stage("discovery", decision, risk),
            confidence=0.82 if context_resolvers else 0.62,
            unknowns=best_unknowns,
            evidence=evidence_base,
            recommended_next_action="research_or_discover" if should_research else "continue",
        ),
        ReasoningStage(
            key="architecture",
            title="Architecture / Planning",
            specialist="Technical Lead",
            responsibility="Select a maintainable approach, identify tradeoffs, and apply studio/profile best practices.",
            context_inputs=("intent summary", "discovery results", "studio decision profile", "known-practice assessment"),
            expected_outputs=("approved strategy", "risk notes", "fallback path", "validation contract"),
            verification_gate=("strategy reuses existing capabilities when possible", "assumptions are documented"),
            deterministic_tools=("studio profile rules", "known-practice playbooks"),
            model_tier=_model_for_stage("architecture", decision, risk),
            confidence=0.85 if best_confidence == "high" else 0.7,
            assumptions=("local route metadata is current",),
            unknowns=best_unknowns,
            risks=tuple(senior.get("likely_architectural_risks") or []),
            evidence=evidence_base,
            recommended_next_action="offer_best_practice_research" if should_research else "continue",
        ),
        ReasoningStage(
            key="gap_discovery",
            title="Capability Gap Discovery",
            specialist="Capability Gap Planner",
            responsibility="Turn missing prerequisites into explicit planning nodes, find detours, rank resolution options, and define what should be learned for next time.",
            context_inputs=("goal", "current capability graph", "known-practice assessment", "project/tool context"),
            expected_outputs=("missing links", "resolution candidates", "recommended A-to-Z path", "planned actions", "user test plan", "learning recommendations"),
            verification_gate=("every missing capability has a producer, resolution option, question, or research recommendation", "top resolution option has validation, user-test, and rollback implications"),
            deterministic_tools=("capability graph", "task playbooks", "studio profile", "project index"),
            model_tier="strong_reasoning" if gap_missing or risk >= 4 else "local_plan",
            confidence=0.78 if gap_plan else 0.58,
            unknowns=gap_missing,
            evidence=_uniq([*evidence_base, *gap_evidence]),
            recommended_next_action="resolve_missing_links" if gap_missing else "continue",
        ),
        ReasoningStage(
            key="resource_discovery",
            title="Resource Discovery",
            specialist="Reuse Finder",
            responsibility="Locate reusable internal code, workflows, graph nodes, operation schemas, docs, or external resources when permitted.",
            context_inputs=("approved strategy", "search scopes", "capability registry", "workflow graph"),
            expected_outputs=("reusable resources", "capability gaps", "external research request if needed"),
            verification_gate=("reuse candidates are verified by source/path", "external lookup is opt-in when required"),
            deterministic_tools=("symbol index", "workflow registry", "capability graph"),
            model_tier=_model_for_stage("resource_discovery", decision, risk),
            confidence=0.78,
            unknowns=tuple(decision.get("capability_gaps") or []),
            evidence=evidence_base,
        ),
        ReasoningStage(
            key="pipeline_generation",
            title="Pipeline Generation",
            specialist="Pipeline Architect",
            responsibility="Define execution graph, data flow, dependency order, and rollback/undo expectations.",
            context_inputs=("approved strategy", "resource candidates", "argument schemas"),
            expected_outputs=("execution plan", "node graph or operation sequence", "rollback plan"),
            verification_gate=("required inputs are mapped", "data flow is valid", "unsafe steps require confirmation"),
            deterministic_tools=("graph validator", "argument validator", "operation metadata"),
            model_tier=_model_for_stage("pipeline_generation", decision, risk),
            confidence=0.82 if requires_plan else 0.7,
            risks=("pipeline data flow can break if required inputs are not connected",) if route in {"pipeline_graph", "action_graph"} else (),
            evidence=evidence_base,
        ),
        ReasoningStage(
            key="implementation",
            title="Implementation",
            specialist="Builder",
            responsibility="Perform only the approved code, graph, workflow, or asset modifications.",
            context_inputs=("approved plan", "exact target files/assets", "schemas", "rollback instructions"),
            expected_outputs=("applied changes", "change report", "execution artifacts"),
            verification_gate=("implementation matches approved plan", "no unrelated targets are changed"),
            deterministic_tools=("apply patch", "registered DCC operation", "workflow writer"),
            model_tier=_model_for_stage("implementation", decision, risk),
            confidence=0.68 if mutation and mutation != "read_only" else 0.9,
            risks=(f"mutation scope: {mutation}",) if mutation and mutation != "read_only" else (),
            evidence=evidence_base,
            recommended_next_action="require_confirmation" if decision.get("requires_confirmation") else "continue",
        ),
        ReasoningStage(
            key="validation",
            title="Validation",
            specialist="QA Engineer",
            responsibility="Run static, style, type, graph, DCC, runtime, and regression checks appropriate to the change, then document the result clearly.",
            context_inputs=("change report", "validation contract", "affected resources"),
            expected_outputs=("validation results", "warnings", "unverified risks", "high-quality user-facing validation note"),
            verification_gate=("required checks pass or failures are reported with next action",),
            deterministic_tools=("py_compile", "unit tests", "graph validation", "DCC query"),
            model_tier=_model_for_stage("validation", decision, risk),
            confidence=0.8,
            evidence=_uniq([*evidence_base, *report_quality]),
        ),
        ReasoningStage(
            key="reflection",
            title="Reflection / Design Review",
            specialist="Senior Reviewer",
            responsibility="Check maintainability, reuse, assumptions, risks, simpler alternatives, and project alignment.",
            context_inputs=("plan", "implementation summary", "validation results", "studio profile"),
            expected_outputs=("review decision", "send-back reason if needed", "residual risks"),
            verification_gate=("no unresolved high-risk assumption remains", "design is simpler or justified"),
            deterministic_tools=("studio profile rules", "diff summary", "test results"),
            model_tier=_model_for_stage("reflection", decision, risk),
            confidence=0.74,
            risks=tuple(senior.get("disqualifying_assumptions") or []),
            evidence=evidence_base,
            recommended_next_action="send_back" if senior.get("disqualifying_assumptions") else "continue",
        ),
        ReasoningStage(
            key="execution",
            title="Execution",
            specialist="Execution Provider",
            responsibility="Execute approved operation through deterministic provider, bridge, workflow, or patch path.",
            context_inputs=("validated implementation", "user confirmation if required", "provider health"),
            expected_outputs=("operation result", "job status", "affected resources"),
            verification_gate=("provider accepted request", "execution result is captured"),
            deterministic_tools=("command dispatcher", "DCC bridge", "job service"),
            model_tier=_model_for_stage("execution", decision, risk),
            confidence=0.86 if can_execute else 0.66,
            risks=("execution is blocked until required confirmation/context is available",) if not can_execute else (),
            evidence=evidence_base,
            recommended_next_action="execute" if can_execute else "hold_until_ready",
        ),
        ReasoningStage(
            key="post_execution_validation",
            title="Post Execution Validation",
            specialist="Result Auditor",
            responsibility="Verify actual final state, then report outputs, changes, warnings, documentation gaps, and recovery actions.",
            context_inputs=("execution result", "expected outputs", "host/project state"),
            expected_outputs=("final verification report", "changed files/assets", "rollback notes", "error report if anything failed"),
            verification_gate=("expected state is observed", "unverified items are disclosed", "report includes evidence, validation, and recovery"),
            deterministic_tools=("job output log", "file diff", "DCC status query"),
            model_tier=_model_for_stage("post_execution_validation", decision, risk),
            confidence=0.78,
            evidence=_uniq([*evidence_base, *report_quality]),
        ),
    ]

    blocked = [stage for stage in stages if stage.recommended_next_action in {"clarify", "require_confirmation", "send_back", "hold_until_ready"}]
    recommended = "continue"
    if blocked:
        recommended = blocked[0].recommended_next_action
    elif should_research:
        recommended = "offer_best_practice_research"

    return {
        "framework": "multi_stage_reasoning_v1",
        "enabled": True,
        "route": route,
        "risk_score": risk,
        "context_policy": "focused_context_per_stage",
        "ethical_policy": [
            "accuracy_over_speed",
            "verify_before_modifying",
            "prefer_deterministic_operations",
            "reuse_existing_solutions",
            "fail_safely",
        ],
        "thread_context_used": bool(thread_context),
        "project_context_used": bool(project_context),
        "tool_context_used": bool(tool_context),
        "recommended_next_action": recommended,
        "stage_count": len(stages),
        "stages": [stage.to_dict() for stage in stages],
    }


def render_reasoning_pipeline(plan: dict[str, Any] | None, *, max_stages: int = 5) -> str:
    if not plan:
        return ""
    stages = list(plan.get("stages") or [])
    if not stages:
        return ""
    lines = [
        "Multi-stage reasoning:",
        f"Framework: {plan.get('framework', '')}",
        f"Next action: {plan.get('recommended_next_action', '')}",
        f"Context policy: {plan.get('context_policy', '')}",
    ]
    for stage in stages[:max_stages]:
        gate = "; ".join(stage.get("verification_gate") or [])[:160]
        lines.append(
            f"- {stage.get('title', '')}: {stage.get('specialist', '')} "
            f"({stage.get('model_tier', '')}, confidence {stage.get('confidence', 0):.2f})"
        )
        if gate:
            lines.append(f"  Gate: {gate}")
    remaining = len(stages) - max_stages
    if remaining > 0:
        lines.append(f"- {remaining} later stage(s) held in the execution plan.")
    return "\n".join(lines)
