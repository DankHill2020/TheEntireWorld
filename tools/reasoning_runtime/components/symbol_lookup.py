"""Replaceable fast symbol lookup contracts."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SymbolQuery:
    query: str
    kind: str = ""
    scope: str = "project"
    limit: int = 50
    active_path: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SymbolHit:
    symbol_id: int
    name: str
    qualname: str
    kind: str
    path: str
    rel_path: str = ""
    start_line: int = 0
    end_line: int = 0
    score: float = 0.0
    source_scope: str = "project"
    metadata: dict[str, Any] = field(default_factory=dict)


class SymbolLookupProvider(ABC):
    """Fast deterministic symbol lookup for code-aware runtimes."""

    name: str = "symbol_lookup_provider"

    def find_symbols(self, query: SymbolQuery) -> list[SymbolHit]:
        return []

    def read_symbol(self, symbol_id: int) -> dict[str, Any]:
        return {}

    def status(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name}


class SymbolLookupBroker:
    """Small broker for querying multiple symbol lookup providers."""

    def __init__(self, providers: list[SymbolLookupProvider] | None = None) -> None:
        self.providers = list(providers or [])

    def register(self, provider: SymbolLookupProvider) -> None:
        self.providers.append(provider)

    def find_symbols(self, query: SymbolQuery) -> list[SymbolHit]:
        hits: list[SymbolHit] = []
        for provider in self.providers:
            hits.extend(provider.find_symbols(query))
        deduped: dict[tuple[str, str, str], SymbolHit] = {}
        for hit in sorted(hits, key=lambda item: item.score, reverse=True):
            key = (hit.path, hit.qualname, hit.kind)
            deduped.setdefault(key, hit)
        return list(deduped.values())[: max(1, int(query.limit or 50))]

    def status(self) -> list[dict[str, Any]]:
        return [provider.status() for provider in self.providers]
