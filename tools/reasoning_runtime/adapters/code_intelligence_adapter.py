"""Code comprehension and generation policy contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CodeGenerationPolicy:
    import_rules: tuple[str, ...] = ()
    patch_constraints: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    forbidden_patterns: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class CodeIntelligenceAdapter(ABC):
    """Extends generic code comprehension/generation with domain policy."""

    name: str = "code_intelligence"

    def get_generation_policy(self, context: dict[str, Any]) -> CodeGenerationPolicy:
        return CodeGenerationPolicy()

    def select_tests_for_change(
        self,
        changed_files: list[str],
        context: dict[str, Any],
    ) -> list[str]:
        return []
