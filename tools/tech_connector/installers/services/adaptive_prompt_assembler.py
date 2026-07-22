from __future__ import annotations

"""Budget-driven prompt assembly with functional contribution collection."""

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.context_contribution_service import (
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
        }


class AdaptivePromptAssembler:
    """Collect and select contributions while preserving structured function output."""

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
        base_prompt = str(base_prompt if base_prompt is not None else getattr(state, "original_prompt", ""))
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
        )
        if hasattr(state, "artifacts"):
            state.artifacts["prompt_assembly"] = result.to_dict()
            state.artifacts.setdefault("functional_outputs", {}).update(functional_outputs)
        return result
