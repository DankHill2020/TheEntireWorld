from __future__ import annotations

"""Small shared result/event records used by the request engine."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressEvent:
    stage: str
    message: str
    current: int = 0
    total: int = 0
    detail: str = ""

    def display_text(self) -> str:
        if self.current and self.total:
            return f"{self.message} ({self.current}/{self.total})"
        return self.message


@dataclass
class ActivityEvent:
    kind: str
    title: str
    detail: str = ""
    status: str = "info"
    path: str = ""
    score: float = 0.0
    items: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    action: str
    label: str
    text: str = ""
    prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def result_type(self) -> str:
        return str((self.metadata or {}).get("result_type") or "")
