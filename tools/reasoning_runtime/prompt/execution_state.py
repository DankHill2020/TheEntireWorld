"""Prompt execution state contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EVIDENCE_TIERS: tuple[str, ...] = (
    "project_index",
    "ast",
    "cross_references",
    "semantic_model",
    "host_validation",
    "execution",
)


@dataclass
class UnderstandingValidation:
    valid: bool
    confidence: float
    missing_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    repaired_fields: dict[str, Any] = field(default_factory=dict)
    clarification_required: bool = False
    clarification_question: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "confidence": self.confidence,
            "missing_fields": list(self.missing_fields),
            "ambiguous_fields": list(self.ambiguous_fields),
            "repaired_fields": dict(self.repaired_fields),
            "clarification_required": self.clarification_required,
            "clarification_question": self.clarification_question,
            "reasons": list(self.reasons),
        }


@dataclass
class EvidenceState:
    """Request-scoped evidence and escalation state."""

    current_tier: int = 0
    attempted_tiers: list[int] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    sufficient: bool = False
    confidence: float = 0.0
    answer: str = ""
    insufficiency_reasons: list[str] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def tier_name(self) -> str:
        index = max(0, min(int(self.current_tier), len(EVIDENCE_TIERS) - 1))
        return EVIDENCE_TIERS[index]

    def add(
        self,
        evidence: dict[str, Any] | None,
        *,
        tier: int | None = None,
        sufficient: bool | None = None,
        confidence: float | None = None,
        answer: str | None = None,
    ) -> None:
        if tier is not None:
            self.current_tier = max(0, min(int(tier), len(EVIDENCE_TIERS) - 1))
        if self.current_tier not in self.attempted_tiers:
            self.attempted_tiers.append(self.current_tier)
        if evidence:
            row = dict(evidence)
            row.setdefault("tier", self.current_tier)
            row.setdefault("tier_name", self.tier_name)
            self.records.append(row)
        if sufficient is not None:
            self.sufficient = bool(sufficient)
        if confidence is not None:
            self.confidence = max(0.0, min(1.0, float(confidence)))
        if answer is not None:
            self.answer = str(answer)

    def escalate(self, reason: str = "") -> bool:
        if self.sufficient or self.current_tier >= len(EVIDENCE_TIERS) - 1:
            return False
        if reason:
            self.insufficiency_reasons.append(str(reason))
        if self.current_tier not in self.attempted_tiers:
            self.attempted_tiers.append(self.current_tier)
        self.current_tier += 1
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "evidence_state_v1",
            "current_tier": self.current_tier,
            "tier_name": self.tier_name,
            "attempted_tiers": list(self.attempted_tiers),
            "attempted_tier_names": [
                EVIDENCE_TIERS[index]
                for index in self.attempted_tiers
                if 0 <= index < len(EVIDENCE_TIERS)
            ],
            "records": [dict(item) for item in self.records],
            "sufficient": self.sufficient,
            "confidence": self.confidence,
            "answer": self.answer,
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "stop_reason": self.stop_reason,
        }
