"""Domain reasoning guidance contracts."""

from __future__ import annotations

from abc import ABC
from typing import Any


class ReasoningAdapter(ABC):
    """Supplies domain vocabulary, prompts, gap policy, and reasoning rules."""

    name: str = "reasoning"

    def get_system_instructions(self) -> str:
        return ""

    def get_prompt_overlays(self) -> list[str]:
        return []

    def get_domain_vocabulary(self) -> dict[str, Any]:
        return {}

    def get_gap_policies(self) -> list[dict[str, Any]]:
        return []

    def get_knowledge_sources(self) -> list[Any]:
        return []

    def get_code_generation_rules(self) -> list[str]:
        return []

    def get_patch_constraints(self) -> list[str]:
        return []
