from __future__ import annotations

"""Budget-driven, goal-scoped prompt assembly.

The assembler remains backward compatible with request-scoped callers, but its
preferred API is :meth:`assemble_goal`.  A model call should receive only the
current executable goal, the evidence required for that goal, and bounded
outputs from completed dependencies.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from tech_connector.services.context_contribution_service import (
    ContextContribution,
    ContributionRegistry,
    estimate_tokens,
    normalize_facts,
)


@dataclass
class PromptAssemblyResult:
    prompt: str
    included: list[ContextContribution] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    available_context_tokens: int = 0
    base_prompt_tokens: int = 0
    facts: list[str] = field(default_factory=list)
    functional_outputs: dict[str, Any] = field(default_factory=dict)
    goal_id: str = ""
    goal: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "included": [item.to_dict() for item in self.included],
            "excluded": list(self.excluded),
            "input_tokens": self.input_tokens,
            "available_context_tokens": self.available_context_tokens,
            "base_prompt_tokens": self.base_prompt_tokens,
            "facts": list(self.facts),
            "functional_outputs": dict(self.functional_outputs),
            "goal_id": self.goal_id,
            "goal": dict(self.goal),
        }


class AdaptivePromptAssembler:
    """Collect the smallest useful context packet for one executable goal."""

    def __init__(self, registry: ContributionRegistry) -> None:
        self.registry = registry

    def assemble(
        self,
        state: Any,
        *,
        base_prompt: str | None = None,
        provider_keys: Iterable[str] | None = None,
        system_prefix: str = "",
    ) -> PromptAssemblyResult:
        """Backward-compatible request assembly.

        New orchestration code should call ``assemble_goal``.  Legacy callers
        still receive budgeted contribution selection without behavior changes.
        """
        return self._assemble(
            state,
            base_prompt=str(base_prompt if base_prompt is not None else getattr(state, "original_prompt", "")),
            provider_keys=provider_keys,
            system_prefix=system_prefix,
            goal=None,
            previous_outputs=None,
            evidence=None,
        )

    def assemble_goal(
        self,
        state: Any,
        goal: Mapping[str, Any] | Any,
        *,
        provider_keys: Iterable[str] | None = None,
        system_prefix: str = "",
        previous_outputs: Mapping[str, Any] | None = None,
        evidence: Iterable[Any] | None = None,
    ) -> PromptAssemblyResult:
        """Assemble a bounded prompt for the current goal only."""
        goal_data = _as_dict(goal)
        base_prompt = self._goal_prompt(
            state,
            goal_data,
            previous_outputs=previous_outputs,
            evidence=evidence,
        )
        return self._assemble(
            state,
            base_prompt=base_prompt,
            provider_keys=provider_keys,
            system_prefix=system_prefix,
            goal=goal_data,
            previous_outputs=previous_outputs,
            evidence=evidence,
        )

    def _assemble(
        self,
        state: Any,
        *,
        base_prompt: str,
        provider_keys: Iterable[str] | None,
        system_prefix: str,
        goal: dict[str, Any] | None,
        previous_outputs: Mapping[str, Any] | None,
        evidence: Iterable[Any] | None,
    ) -> PromptAssemblyResult:
        budget = getattr(state, "budget")
        total_budget = int(getattr(budget, "token_budget", 4096))
        reserved_output = int(getattr(budget, "reserved_output_tokens", 512))
        base_tokens = estimate_tokens(base_prompt) + estimate_tokens(system_prefix)
        available = max(0, total_budget - reserved_output - base_tokens)

        keys = list(provider_keys) if provider_keys is not None else self.registry.keys()
        estimates = self.registry.estimate_all(state, keys)
        estimates.sort(key=lambda item: (item.required, item.value_score, item.priority), reverse=True)

        included: list[ContextContribution] = []
        excluded: list[dict[str, Any]] = []
        used = 0
        seen_keys: set[str] = set()
        functional_outputs: dict[str, Any] = {}
        all_facts: list[str] = []

        for estimate in estimates:
            provider = self.registry.get(estimate.provider)
            if provider is None:
                excluded.append({"provider": estimate.provider, "reason": "provider_not_registered"})
                continue
            if estimate.deduplication_key in seen_keys:
                excluded.append({"provider": estimate.provider, "reason": "duplicate_estimate"})
                continue
            projected = used + max(0, estimate.estimated_tokens)
            if not estimate.required and projected > available:
                excluded.append({
                    "provider": estimate.provider,
                    "reason": "estimated_token_budget_exceeded",
                    "estimated_tokens": estimate.estimated_tokens,
                })
                continue
            contribution = provider.collect(state)
            if contribution is None:
                excluded.append({"provider": estimate.provider, "reason": "provider_returned_no_contribution"})
                continue
            if contribution.deduplication_key in seen_keys:
                excluded.append({"provider": contribution.provider, "reason": "duplicate_contribution"})
                continue
            actual = contribution.actual_tokens
            if not contribution.required and used + actual > available:
                excluded.append({
                    "provider": contribution.provider,
                    "reason": "actual_token_budget_exceeded",
                    "actual_tokens": actual,
                })
                continue
            seen_keys.add(contribution.deduplication_key)
            used += actual
            included.append(contribution)
            all_facts.extend(contribution.facts)
            if contribution.data is not None:
                functional_outputs[contribution.provider] = contribution.data

        fragments = [item.prompt_fragment.strip() for item in included if item.prompt_fragment.strip()]
        sections = [section for section in (system_prefix.strip(), *fragments, base_prompt.strip()) if section]
        prompt = "\n\n".join(sections)
        result = PromptAssemblyResult(
            prompt=prompt,
            included=included,
            excluded=excluded,
            input_tokens=estimate_tokens(prompt),
            available_context_tokens=available,
            base_prompt_tokens=base_tokens,
            facts=normalize_facts(all_facts),
            functional_outputs=functional_outputs,
            goal_id=str((goal or {}).get("goal_id") or (goal or {}).get("id") or ""),
            goal=dict(goal or {}),
        )
        if hasattr(state, "artifacts"):
            key = "goal_prompt_assembly" if goal else "prompt_assembly"
            state.artifacts[key] = result.to_dict()
            if goal:
                state.artifacts.setdefault("goal_prompt_assemblies", {})[result.goal_id or "current"] = result.to_dict()
            state.artifacts.setdefault("functional_outputs", {}).update(functional_outputs)
        return result

    def _goal_prompt(
        self,
        state: Any,
        goal: dict[str, Any],
        *,
        previous_outputs: Mapping[str, Any] | None,
        evidence: Iterable[Any] | None,
    ) -> str:
        goal_id = str(goal.get("goal_id") or goal.get("id") or "current")
        objective = str(goal.get("objective") or goal.get("goal") or goal.get("label") or "Complete the current goal.")
        success = str(goal.get("success_condition") or goal.get("success") or "Return a result that directly satisfies the goal.")
        dependencies = [str(item) for item in goal.get("depends_on") or goal.get("dependencies") or [] if item]

        lines = [
            "CURRENT EXECUTABLE GOAL",
            f"Goal ID: {goal_id}",
            f"Objective: {objective}",
            f"Success condition: {success}",
        ]
        if dependencies:
            lines.append("Dependencies: " + ", ".join(dependencies))

        bounded_outputs = _bounded_mapping(previous_outputs or {}, keys=dependencies or None, max_chars=5000)
        if bounded_outputs:
            lines.extend(["", "COMPLETED DEPENDENCY OUTPUTS", bounded_outputs])

        evidence_text = _bounded_evidence(evidence, max_chars=5000)
        if evidence_text:
            lines.extend(["", "RELEVANT EVIDENCE", evidence_text])

        intent = dict(getattr(state, "intent_frame", {}) or {})
        contract = dict(getattr(state, "execution_contract", {}) or {})
        active_file = str(getattr(state, "active_file", "") or "")
        lines.extend([
            "",
            "ANSWER CONTRACT",
            f"Requested deliverable: {contract.get('deliverable') or intent.get('object_type') or 'direct answer'}",
            f"Requested scope: {intent.get('requested_scope') or contract.get('scope') or 'use the narrowest resolved scope'}",
            f"Resolved target: {goal.get('target') or contract.get('target') or active_file or '(unresolved)'}",
            "Do not include results from other files when the request is scoped to one file.",
            "Do not treat retrieval matches as completion until they satisfy the target, scope, deliverable, and success condition.",
            "",
            "EXECUTION RULES",
            "Work only on this goal.",
            "Do not repeat the full request plan.",
            "Use supplied evidence before requesting broader context.",
            "Return the concrete goal result, not progress narration.",
            "State a blocker explicitly if the success condition cannot be met.",
        ])
        return "\n".join(lines)


def _as_dict(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    raise TypeError("goal must be a mapping or expose to_dict()/__dict__")


def _bounded_mapping(values: Mapping[str, Any], *, keys: list[str] | None, max_chars: int) -> str:
    selected = values
    if keys:
        selected = {key: values[key] for key in keys if key in values}
    lines: list[str] = []
    for key, value in selected.items():
        text = str(value).strip()
        if not text:
            continue
        lines.append(f"[{key}]\n{text}")
        if sum(len(item) for item in lines) >= max_chars:
            break
    return "\n\n".join(lines)[:max_chars].rstrip()


def _bounded_evidence(evidence: Iterable[Any] | None, *, max_chars: int) -> str:
    if not evidence:
        return ""
    lines: list[str] = []
    for item in evidence:
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, Mapping):
            source = str(item.get("source") or item.get("kind") or "evidence")
            summary = str(item.get("summary") or item.get("text") or item.get("content") or item)
            lines.append(f"- {source}: {summary}")
        else:
            lines.append(f"- {item}")
        if sum(len(line) for line in lines) >= max_chars:
            break
    return "\n".join(lines)[:max_chars].rstrip()
