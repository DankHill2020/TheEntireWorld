"""Replaceable knowledge-gap search contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KnowledgeGap:
    key: str
    question: str
    kind: str = "unknown"
    required_confidence: float = 0.75
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeSearchResult:
    source: str
    answer: str
    confidence: float = 0.0
    locator: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeSource(ABC):
    """Searchable knowledge source for filling reasoning gaps."""

    name: str = "knowledge_source"

    def search(self, gap: KnowledgeGap, context: dict[str, Any]) -> list[KnowledgeSearchResult]:
        return []


class KnowledgeBroker:
    """Coordinates knowledge sources without knowing their domains."""

    def __init__(self, sources: list[KnowledgeSource] | None = None) -> None:
        self.sources = list(sources or [])

    def register(self, source: KnowledgeSource) -> None:
        self.sources.append(source)

    def search(self, gap: KnowledgeGap, context: dict[str, Any]) -> list[KnowledgeSearchResult]:
        results: list[KnowledgeSearchResult] = []
        for source in self.sources:
            results.extend(source.search(gap, context))
        return sorted(results, key=lambda item: item.confidence, reverse=True)
