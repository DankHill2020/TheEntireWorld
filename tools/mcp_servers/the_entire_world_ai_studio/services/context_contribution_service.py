from __future__ import annotations

"""Structured context contributions for adaptive prompt assembly.

Providers return evidence and optional prompt text with explicit cost/value metadata.
The assembler can then choose the highest-value subset without losing functional
outputs in ``data``.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable
import re
import time


@dataclass
class ContextContribution:
    provider: str
    kind: str
    prompt_fragment: str = ""
    data: Any = None
    priority: float = 50.0
    confidence_gain: float = 0.0
    estimated_tokens: int = 0
    actual_tokens: int = 0
    latency_ms: int = 0
    required: bool = False
    cacheable: bool = True
    deduplication_key: str = ""
    reasons: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def value_score(self) -> float:
        if self.required:
            return 1_000_000.0 + self.priority
        cost = max(1.0, self.estimated_tokens / 100.0 + self.latency_ms / 50.0)
        return (self.priority + self.confidence_gain * 100.0) / cost

    def finalize(self) -> "ContextContribution":
        if self.actual_tokens <= 0 and self.prompt_fragment:
            self.actual_tokens = estimate_tokens(self.prompt_fragment)
        if self.estimated_tokens <= 0:
            self.estimated_tokens = self.actual_tokens
        if not self.deduplication_key:
            self.deduplication_key = f"{self.provider}:{self.kind}"
        return self

    def to_dict(self) -> dict[str, Any]:
        self.finalize()
        data = asdict(self)
        data["value_score"] = round(self.value_score, 6)
        return data


@dataclass
class ContributionProvider:
    key: str
    collector: Callable[[Any], ContextContribution | None]
    estimate: Callable[[Any], ContextContribution] | None = None

    def estimate_for(self, state: Any) -> ContextContribution:
        if self.estimate:
            return self.estimate(state).finalize()
        return ContextContribution(provider=self.key, kind=self.key, priority=40.0).finalize()

    def collect(self, state: Any) -> ContextContribution | None:
        started = time.perf_counter()
        result = self.collector(state)
        if result is not None:
            result.latency_ms = max(result.latency_ms, int((time.perf_counter() - started) * 1000))
            result.finalize()
        return result


class ContributionRegistry:
    def __init__(self, providers: Iterable[ContributionProvider] = ()) -> None:
        self._providers: dict[str, ContributionProvider] = {item.key: item for item in providers}

    def register(self, provider: ContributionProvider) -> None:
        self._providers[provider.key] = provider

    def get(self, key: str) -> ContributionProvider | None:
        return self._providers.get(key)

    def keys(self) -> list[str]:
        return list(self._providers)

    def estimate_all(self, state: Any, allowlist: Iterable[str] | None = None) -> list[ContextContribution]:
        keys = list(allowlist) if allowlist is not None else self.keys()
        return [self._providers[key].estimate_for(state) for key in keys if key in self._providers]


def estimate_tokens(text: str) -> int:
    """Cheap local estimate suitable for budgeting before tokenizer access."""
    text = str(text or "")
    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    return max(1, int(max(words * 1.35, chars / 4.0)))


def normalize_facts(values: Iterable[Any], *, limit: int = 40) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out
