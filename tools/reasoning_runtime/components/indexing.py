"""Replaceable indexing and retrieval contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndexRecord:
    """One searchable fact or chunk in an index."""

    record_id: str
    title: str
    text: str
    source: str = ""
    kind: str = "document"
    locator: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexQuery:
    query: str
    scope: str = ""
    limit: int = 20
    filters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexSearchResult:
    record: IndexRecord
    score: float = 0.0
    highlights: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexBuildResult:
    ok: bool
    indexed_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class IndexProvider(ABC):
    """Searches and optionally maintains a knowledge/code index."""

    name: str = "index_provider"

    def search(self, query: IndexQuery) -> list[IndexSearchResult]:
        return []

    def build_or_update(self, roots: list[str], metadata: dict[str, Any] | None = None) -> IndexBuildResult:
        return IndexBuildResult(ok=False, errors=("Index build is not implemented.",))

    def status(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name}


class IndexRegistry:
    """Small broker for multiple index providers."""

    def __init__(self, providers: list[IndexProvider] | None = None) -> None:
        self.providers = list(providers or [])

    def register(self, provider: IndexProvider) -> None:
        self.providers.append(provider)

    def search(self, query: IndexQuery) -> list[IndexSearchResult]:
        results: list[IndexSearchResult] = []
        for provider in self.providers:
            results.extend(provider.search(query))
        return sorted(results, key=lambda item: item.score, reverse=True)

    def status(self) -> list[dict[str, Any]]:
        return [provider.status() for provider in self.providers]
