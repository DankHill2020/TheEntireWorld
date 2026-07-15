from __future__ import annotations

"""Default contribution providers backed by Milestone A stage artifacts.

These providers preserve structured outputs for execution while rendering only a
compact prompt fragment when the budget says the information is worthwhile.
"""

from typing import Any

from services.context_contribution_service import ContextContribution, ContributionProvider, ContributionRegistry


def registry_from_state_artifacts() -> ContributionRegistry:
    registry = ContributionRegistry()
    registry.register(ContributionProvider("code_intelligence", _code_intelligence, _estimate_code_intelligence))
    registry.register(ContributionProvider("domain_experts", _domain_experts, _estimate_domain_experts))
    registry.register(ContributionProvider("goal_gap", _goal_gap, _estimate_goal_gap))
    registry.register(ContributionProvider("studio_profile", _studio_profile, _estimate_studio_profile))
    registry.register(ContributionProvider("validation_plan", _validation_plan, _estimate_validation_plan))
    registry.register(ContributionProvider("operation_memory", _operation_memory, _estimate_operation_memory))
    return registry


def _artifact(state: Any, key: str, default=None):
    return getattr(state, "artifacts", {}).get(key, default)


def _estimate_code_intelligence(state: Any) -> ContextContribution:
    required = bool(getattr(state, "mutation_scope", "") and getattr(state, "mutation_scope") != "read_only") and not getattr(state, "active_file", "")
    return ContextContribution(
        provider="code_intelligence",
        kind="project_evidence",
        priority=95 if required else 82,
        confidence_gain=0.2,
        estimated_tokens=1600 if state.prediction.complexity_score >= 0.5 else 800,
        required=required,
        reasons=["Project symbols and usages ground target selection."],
    )


def _code_intelligence(state: Any) -> ContextContribution | None:
    packet = _artifact(state, "code_intelligence_packet")
    if not packet:
        return None
    symbols = list(packet.get("symbols") or [])[:8] if isinstance(packet, dict) else []
    lines = ["PROJECT CODE INTELLIGENCE:"]
    facts: list[str] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("symbol") or ""
        path = item.get("path") or item.get("file") or ""
        signature = item.get("signature") or item.get("summary") or ""
        line = f"- {name} | {path} | {signature}".strip()
        lines.append(line)
        facts.append(line[2:])
    suff = packet.get("sufficiency") if isinstance(packet, dict) else None
    if isinstance(suff, dict):
        lines.append(f"Sufficiency: answerable={suff.get('answerable')} confidence={suff.get('confidence')}")
    return ContextContribution(
        provider="code_intelligence",
        kind="project_evidence",
        prompt_fragment="\n".join(lines),
        data=packet,
        priority=88,
        confidence_gain=0.2,
        facts=facts,
        deduplication_key="project:code_intelligence",
    )


def _estimate_domain_experts(state: Any) -> ContextContribution:
    enabled = bool(getattr(state.budget, "include_domain_experts", False) and getattr(state.budget, "expert_limit", 0) > 0)
    return ContextContribution(
        provider="domain_experts",
        kind="expert_guidance",
        priority=62 if enabled else 1,
        confidence_gain=0.1 if enabled else 0.0,
        estimated_tokens=450,
        reasons=["Expert validation and architecture advice is useful for complex work."],
    )


def _domain_experts(state: Any) -> ContextContribution | None:
    experts = list(_artifact(state, "domain_experts", []) or [])
    if not experts:
        return None
    lines = ["SELECTED EXPERT GUIDANCE:"]
    facts: list[str] = []
    for expert in experts[: max(1, state.budget.expert_limit)]:
        label = expert.get("label") or expert.get("domain") or "Expert"
        validation = list(expert.get("validation_steps") or [])[:2]
        responsibility = list(expert.get("responsibilities") or [])[:1]
        line = f"- {label}: {'; '.join(responsibility + validation)}"
        lines.append(line)
        facts.append(line[2:])
    return ContextContribution(
        provider="domain_experts",
        kind="expert_guidance",
        prompt_fragment="\n".join(lines),
        data=experts,
        priority=64,
        confidence_gain=0.1,
        facts=facts,
        deduplication_key="advisory:domain_experts",
    )


def _estimate_goal_gap(state: Any) -> ContextContribution:
    enabled = bool(getattr(state.budget, "include_goal_gap", False))
    return ContextContribution(
        provider="goal_gap",
        kind="execution_plan",
        priority=78 if enabled else 1,
        confidence_gain=0.13 if enabled else 0.0,
        estimated_tokens=700,
        required=bool(enabled and state.missing_information),
        reasons=["Capability gaps and mixed-operation prerequisites need explicit resolution."],
    )


def _goal_gap(state: Any) -> ContextContribution | None:
    plan = _artifact(state, "goal_gap_plan")
    if not plan:
        return None
    lines = ["GOAL GAP / FUNCTION PATH:"]
    missing = list(plan.get("missing_links") or [])[:5]
    sequence = list(plan.get("adaptive_sequence") or [])[:6]
    for item in missing:
        lines.append(f"- Missing: {item.get('label')} ({item.get('status')})")
    for item in sequence:
        lines.append(f"- {item.get('action')}: {item.get('capability')} via {item.get('strategy')}")
    return ContextContribution(
        provider="goal_gap",
        kind="execution_plan",
        prompt_fragment="\n".join(lines),
        data=plan,
        priority=80,
        confidence_gain=0.13,
        facts=[line[2:] for line in lines[1:]],
        deduplication_key="plan:goal_gap",
    )


def _estimate_studio_profile(state: Any) -> ContextContribution:
    mutation = bool(state.mutation_scope and state.mutation_scope != "read_only")
    return ContextContribution(
        provider="studio_profile",
        kind="safety_policy",
        priority=90 if mutation else 35,
        confidence_gain=0.05,
        estimated_tokens=320,
        required=mutation and state.risk_level == "high",
    )


def _studio_profile(state: Any) -> ContextContribution | None:
    rules = list(_artifact(state, "studio_rules", []) or [])
    if not rules:
        return None
    lines = ["EXECUTION SAFETY RULES:"]
    for rule in rules[:4]:
        guidance = list(rule.get("guidance") or [])[:1]
        lines.append(f"- {rule.get('title')}: {'; '.join(guidance)}")
    return ContextContribution(
        provider="studio_profile",
        kind="safety_policy",
        prompt_fragment="\n".join(lines),
        data=rules,
        priority=86,
        confidence_gain=0.05,
        facts=[line[2:] for line in lines[1:]],
        deduplication_key="policy:studio_profile",
    )


def _estimate_validation_plan(state: Any) -> ContextContribution:
    mutation = bool(state.mutation_scope and state.mutation_scope != "read_only") or state.prediction.predicted_files_touched > 0
    return ContextContribution(
        provider="validation_plan",
        kind="validation",
        priority=98 if mutation else 10,
        confidence_gain=0.08,
        estimated_tokens=350,
        required=mutation,
    )


def _validation_plan(state: Any) -> ContextContribution | None:
    plan = _artifact(state, "validation_plan")
    if not plan:
        return None
    steps = list(plan.get("planned_steps") or [])
    predicted = list(plan.get("predicted_validation_types") or [])
    lines = ["VALIDATION CONTRACT:"]
    for step in steps[:6]:
        lines.append(f"- {step.get('command')}: {step.get('reason')}")
    for name in predicted[:5]:
        lines.append(f"- Predicted validation: {name}")
    return ContextContribution(
        provider="validation_plan",
        kind="validation",
        prompt_fragment="\n".join(lines),
        data=plan,
        priority=98,
        confidence_gain=0.08,
        required=bool(state.mutation_scope and state.mutation_scope != "read_only"),
        facts=[line[2:] for line in lines[1:]],
        deduplication_key="validation:plan",
    )


def _estimate_operation_memory(state: Any) -> ContextContribution:
    has_memory = bool(getattr(state, "operation_memory", {}))
    return ContextContribution(
        provider="operation_memory",
        kind="prior_execution",
        priority=70 if has_memory else 0,
        confidence_gain=0.08 if has_memory else 0.0,
        estimated_tokens=500,
    )


def _operation_memory(state: Any) -> ContextContribution | None:
    memory = dict(getattr(state, "operation_memory", {}) or {})
    if not memory:
        return None
    compact = {key: memory[key] for key in list(memory)[:8]}
    lines = ["RELEVANT PRIOR EXECUTION MEMORY:"] + [f"- {key}: {value}" for key, value in compact.items()]
    return ContextContribution(
        provider="operation_memory",
        kind="prior_execution",
        prompt_fragment="\n".join(lines),
        data=compact,
        priority=70,
        confidence_gain=0.08,
        facts=[line[2:] for line in lines[1:]],
        deduplication_key="memory:operation",
    )
