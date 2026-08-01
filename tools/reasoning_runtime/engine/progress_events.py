from __future__ import annotations

"""Small shared result/event records used by request engines."""

from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True)
class ReadinessRequirement:
    """Observable requirement state owned by generated or edited symbols."""

    requirement_id: str
    text: str
    owners: tuple[str, ...] = ()
    status: str = "pending"
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationFinding:
    """One validation result with an exact category and repair owner."""

    category: str
    message: str
    owner: str = ""
    path: str = ""
    fingerprint: str = ""
    status: str = "failed"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairRecord:
    """Observable record of one bounded repair decision."""

    owner: str
    strategy: str
    model: str = ""
    failure_fingerprint: str = ""
    status: str = "pending"
    changed: bool = False
    detail: str = ""


@dataclass
class ProductionReadiness:
    """Canonical completion state shared by headless and interactive clients."""

    ready: bool
    status: str
    summary: str = ""
    requirements: list[ReadinessRequirement] = field(default_factory=list)
    validation: list[ValidationFinding] = field(default_factory=list)
    repairs: list[RepairRecord] = field(default_factory=list)
    timings: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for APIs, UIs, and logs."""

        return asdict(self)
