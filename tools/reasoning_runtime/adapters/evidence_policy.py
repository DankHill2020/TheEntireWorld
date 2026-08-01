"""Evidence and provenance policy contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceRecord:
    source: str
    claim: str
    confidence: float = 0.0
    locator: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidencePolicy(ABC):
    """Defines how evidence is recorded, trusted, and judged sufficient."""

    name: str = "evidence"

    def rank_evidence(self, records: list[EvidenceRecord], context: dict[str, Any]) -> list[EvidenceRecord]:
        return sorted(records, key=lambda item: item.confidence, reverse=True)

    def is_sufficient(self, records: list[EvidenceRecord], context: dict[str, Any]) -> bool:
        return any(record.confidence >= 0.75 for record in records)

    def required_trace_fields(self) -> list[str]:
        return ["request", "context", "tools", "evidence", "validation"]
