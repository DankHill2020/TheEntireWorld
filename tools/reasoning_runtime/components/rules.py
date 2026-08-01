"""Replaceable reasoning rule contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReasoningRule:
    key: str
    description: str
    severity: str = "info"
    applies_to: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleSet:
    name: str
    rules: tuple[ReasoningRule, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class RuleProvider(ABC):
    """Supplies runtime and domain reasoning rules."""

    name: str = "rule_provider"

    def get_rule_sets(self, context: dict[str, Any]) -> list[RuleSet]:
        return []
