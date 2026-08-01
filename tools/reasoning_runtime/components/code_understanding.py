"""Replaceable code comprehension and generation contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CodeUnderstandingRequest:
    query: str
    project_roots: tuple[str, ...] = ()
    active_file: str = ""
    symbols: tuple[str, ...] = ()
    intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeContext:
    summary: str = ""
    files: tuple[dict[str, Any], ...] = ()
    symbols: tuple[dict[str, Any], ...] = ()
    dependencies: tuple[dict[str, Any], ...] = ()
    validation_candidates: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class CodeUnderstandingProvider(ABC):
    """Provides repo/file/symbol comprehension to the runtime."""

    name: str = "code_understanding"

    def understand(self, request: CodeUnderstandingRequest) -> CodeContext:
        return CodeContext(gaps=("No code understanding provider is configured.",))

    def plan_patch(self, request: CodeUnderstandingRequest, context: CodeContext) -> dict[str, Any]:
        return {"ok": False, "error": "Patch planning is not implemented."}

    def validate_patch(self, patch: dict[str, Any], context: CodeContext) -> dict[str, Any]:
        return {"ok": False, "error": "Patch validation is not implemented."}


class CodeUnderstandingBroker:
    """Aggregates one or more code-understanding providers."""

    def __init__(self, providers: list[CodeUnderstandingProvider] | None = None) -> None:
        self.providers = list(providers or [])

    def register(self, provider: CodeUnderstandingProvider) -> None:
        self.providers.append(provider)

    def understand(self, request: CodeUnderstandingRequest) -> list[CodeContext]:
        return [provider.understand(request) for provider in self.providers]

    def summarize(self, contexts: list[CodeContext]) -> dict[str, Any]:
        return {
            "provider_count": len(self.providers),
            "context_count": len(contexts),
            "summaries": [context.summary for context in contexts if context.summary],
            "gaps": [
                gap
                for context in contexts
                for gap in context.gaps
                if gap
            ],
        }
