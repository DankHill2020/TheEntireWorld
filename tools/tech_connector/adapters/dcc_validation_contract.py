"""Validation contract for Tech Connector domain work."""

from __future__ import annotations

from typing import Any

from reasoning_runtime import ValidationContract, ValidationReport


class DccValidationContract(ValidationContract):
    """Describe the proof expectations for DCC/game-development actions."""

    name = "tech_connector_validation"

    def validate_preconditions(self, request: dict[str, Any]) -> ValidationReport:
        context = dict(request.get("context") or {})
        tech_context = dict(context.get("tech_connector_context") or {})
        warnings: list[str] = []
        if not tech_context.get("project_roots") and not tech_context.get("project_root"):
            warnings.append("No active Tech Connector project root was supplied.")
        return ValidationReport(
            ok=True,
            summary="Tech Connector preconditions inspected.",
            warnings=tuple(warnings),
            metadata={"domain": "tech_connector"},
        )

    def validate_completion(self, result: Any, context: dict[str, Any]) -> ValidationReport:
        return ValidationReport(
            ok=True,
            summary=(
                "Completion requires domain-specific proof such as bridge readback, "
                "compile logs, saved asset checks, tests, or user-visible state."
            ),
            metadata={"result_type": type(result).__name__},
        )
