"""Prompt lifecycle quality report contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StageQualityCheck:
    stage: str
    check: str
    ok: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PromptStageQualityReport:
    prompt: str
    ok: bool
    score: float
    elapsed_ms: float
    route: str = ""
    provider: str = ""
    intent_category: str = ""
    planning_mode: str = ""
    matched_patterns: list[str] = field(default_factory=list)
    operation_sequence: list[str] = field(default_factory=list)
    planned_callables: list[str] = field(default_factory=list)
    engine_action: str = ""
    selected_target: str = ""
    checks: list[StageQualityCheck] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "ok": self.ok,
            "score": round(self.score, 4),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "route": self.route,
            "provider": self.provider,
            "intent_category": self.intent_category,
            "planning_mode": self.planning_mode,
            "matched_patterns": list(self.matched_patterns),
            "operation_sequence": list(self.operation_sequence),
            "planned_callables": list(self.planned_callables),
            "engine_action": self.engine_action,
            "selected_target": self.selected_target,
            "checks": [item.to_dict() for item in self.checks],
            "artifacts": dict(self.artifacts),
        }
