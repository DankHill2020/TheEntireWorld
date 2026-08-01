"""Model and strategy escalation contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reason: str = ""
    target_model_tier: str = ""
    target_route: dict[str, Any] = field(default_factory=dict)
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelTier:
    """One model option in an escalation ladder."""

    tier: str
    provider: str
    model: str
    transport: str = "local"
    cost_tier: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class EscalationPolicy(ABC):
    """Controls model routing and failure escalation."""

    name: str = "escalation"

    def choose_model_tier(self, task: dict[str, Any], context: dict[str, Any]) -> str:
        return "default"

    def on_failure(self, failure: dict[str, Any], context: dict[str, Any]) -> EscalationDecision:
        return EscalationDecision(escalate=False, reason="No escalation policy matched.")


class ModelTierEscalationPolicy(EscalationPolicy):
    """Generic local/cloud model escalation ladder."""

    name = "model_tier_escalation"

    def __init__(self, tiers: list[ModelTier] | tuple[ModelTier, ...]) -> None:
        self.tiers = tuple(tiers)
        self._tier_index = {tier.tier: index for index, tier in enumerate(self.tiers)}

    def choose_model_tier(self, task: dict[str, Any], context: dict[str, Any]) -> str:
        requested = str(task.get("tier") or context.get("model_tier") or "").strip()
        if requested in self._tier_index:
            return requested
        if any(token in str(task.get("task") or task.get("request") or "").lower() for token in ("repair", "debug", "code")):
            return "standard" if "standard" in self._tier_index else self.tiers[-1].tier if self.tiers else "default"
        return self.tiers[0].tier if self.tiers else "default"

    def route_for_tier(self, tier_name: str) -> ModelTier | None:
        index = self._tier_index.get(str(tier_name or ""))
        if index is None:
            return None
        return self.tiers[index]

    def next_tier(self, current_tier: str) -> ModelTier | None:
        if not self.tiers:
            return None
        index = self._tier_index.get(str(current_tier or ""), -1)
        next_index = max(0, index + 1)
        if next_index >= len(self.tiers):
            return None
        return self.tiers[next_index]

    def on_failure(self, failure: dict[str, Any], context: dict[str, Any]) -> EscalationDecision:
        current = str(
            failure.get("model_tier")
            or failure.get("tier")
            or context.get("model_tier")
            or ""
        )
        target = self.next_tier(current)
        if target is None:
            return EscalationDecision(
                escalate=False,
                reason="No higher model tier is configured.",
                metadata={"current_tier": current},
            )
        return EscalationDecision(
            escalate=True,
            reason=str(failure.get("reason") or "Escalating after failure."),
            target_model_tier=target.tier,
            target_route={
                "provider": target.provider,
                "model": target.model,
                "transport": target.transport,
            },
            strategy="retry_with_higher_model_tier",
            metadata={"current_tier": current, **dict(target.metadata or {})},
        )
