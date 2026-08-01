"""Domain-neutral repair provider contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reasoning_runtime.engine.progress_events import RepairRecord, ValidationFinding


@dataclass(frozen=True)
class RepairContext:
    """Inputs supplied to one bounded domain repair provider."""

    request: str
    candidate: Any
    findings: tuple["ValidationFinding", ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairProposal:
    """Candidate returned by a provider without deciding whether to accept it."""

    candidate: Any
    changed: bool
    records: tuple["RepairRecord", ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class RepairProvider(ABC):
    """Produces bounded domain repairs while the runtime owns convergence."""

    name: str = "repair_provider"
    priority: int = 100

    @abstractmethod
    def supports(self, context: RepairContext) -> bool:
        """Return whether this provider can address the supplied findings."""

    @abstractmethod
    def repair(self, context: RepairContext) -> RepairProposal:
        """Return a candidate proposal without applying it permanently."""
