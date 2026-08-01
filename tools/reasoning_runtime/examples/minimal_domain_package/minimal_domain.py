"""Minimal runnable domain package for reasoning_runtime."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reasoning_runtime import (  # noqa: E402
    CapabilityBridge,
    CapabilityResult,
    CodeGenerationPolicy,
    CodeIntelligenceAdapter,
    ContextAdapter,
    EscalationDecision,
    EscalationPolicy,
    EvidencePolicy,
    EvidenceRecord,
    ReasoningAdapter,
    ReasoningKernel,
    ToolSpec,
    ValidationContract,
    ValidationReport,
)


class NotesContext(ContextAdapter):
    name = "notes_context"

    def get_active_context(self) -> dict[str, Any]:
        return {"active_note": "Ship the extension guide with examples."}


class NotesReasoning(ReasoningAdapter):
    name = "notes_reasoning"

    def get_system_instructions(self) -> str:
        return "You help organize plain-text project notes."

    def get_domain_vocabulary(self) -> dict[str, Any]:
        return {"entities": ["note", "task", "decision"]}


class NotesBridge(CapabilityBridge):
    name = "notes_bridge"

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="notes.echo",
                description="Echo a note summary.",
                input_schema={"type": "object", "required": ["text"]},
                output_schema={"type": "object"},
                mutability="read_only",
                risk="low",
            )
        ]

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> CapabilityResult:
        if tool_name != "notes.echo":
            return CapabilityResult(ok=False, error=f"Unknown tool: {tool_name}")
        return CapabilityResult(ok=True, output={"text": arguments.get("text", "")})


class NotesValidation(ValidationContract):
    name = "notes_validation"

    def validate_preconditions(self, request: dict[str, Any]) -> ValidationReport:
        return ValidationReport(ok=bool(request.get("request")), summary="Request text is present.")


class NotesEvidence(EvidencePolicy):
    name = "notes_evidence"

    def is_sufficient(self, records: list[EvidenceRecord], context: dict[str, Any]) -> bool:
        return bool(records)


class NotesEscalation(EscalationPolicy):
    name = "notes_escalation"

    def on_failure(self, failure: dict[str, Any], context: dict[str, Any]) -> EscalationDecision:
        return EscalationDecision(escalate=False, reason="Minimal example does not escalate.")


class NotesCodePolicy(CodeIntelligenceAdapter):
    name = "notes_code_policy"

    def get_generation_policy(self, context: dict[str, Any]) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(patch_constraints=("Keep examples small and runnable.",))


class MinimalNotesDomain:
    def get_context_adapters(self) -> list[ContextAdapter]:
        return [NotesContext()]

    def get_reasoning_adapters(self) -> list[ReasoningAdapter]:
        return [NotesReasoning()]

    def get_capability_bridges(self) -> list[CapabilityBridge]:
        return [NotesBridge()]

    def get_validation_contracts(self) -> list[ValidationContract]:
        return [NotesValidation()]

    def get_evidence_policies(self) -> list[EvidencePolicy]:
        return [NotesEvidence()]

    def get_escalation_policies(self) -> list[EscalationPolicy]:
        return [NotesEscalation()]

    def get_code_intelligence_adapters(self) -> list[CodeIntelligenceAdapter]:
        return [NotesCodePolicy()]


def main() -> None:
    kernel = ReasoningKernel()
    kernel.install(MinimalNotesDomain())
    result = kernel.run("Summarize the active note")
    print(
        {
            "ok": result.ok,
            "context_keys": sorted(result.context),
            "tools": [tool.name for tool in result.tools],
            "instructions": list(result.system_instructions),
        }
    )


if __name__ == "__main__":
    main()
