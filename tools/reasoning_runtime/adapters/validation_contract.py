"""Validation contracts for runtime and domain completion proof."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    summary: str = ""
    checks: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    evidence: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class ValidationContract(ABC):
    """Defines what done, safe, and proven mean for a domain."""

    name: str = "validation"

    def validate_plan(self, plan: dict[str, Any], context: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=True, summary="Plan validation passed.")

    def validate_preconditions(self, request: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=True, summary="Preconditions passed.")

    def validate_execution_result(self, result: Any, context: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=True, summary="Execution result validation passed.")

    def validate_side_effects(self, result: Any, context: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=True, summary="Side-effect validation passed.")

    def validate_completion(self, result: Any, context: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=True, summary="Completion validation passed.")
