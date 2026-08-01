"""Replaceable action planning contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PlanStep:
    key: str
    title: str
    action_type: str
    arguments: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    success_condition: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionPlan:
    goal: str
    steps: tuple[PlanStep, ...] = ()
    confidence: float = 0.0
    diagnostics: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class ActionPlanner(ABC):
    """Turns understood requests into executable or reviewable plans."""

    name: str = "action_planner"

    def plan(self, request: str, context: dict[str, Any]) -> ActionPlan:
        return ActionPlan(
            goal=request,
            diagnostics=("No action planner is configured.",),
        )
