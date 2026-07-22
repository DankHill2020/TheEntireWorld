from __future__ import annotations

"""Short-lived context momentum for files, symbols, assets, widgets, and graphs."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class MomentumTarget:
    value: str
    kind: str
    source: str = "execution"
    confidence: float = 0.8
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextMomentum:
    targets: list[MomentumTarget] = field(default_factory=list)
    max_targets: int = 24
    sequence: int = 0

    def remember(self, value: str, kind: str, *, source: str = "execution", confidence: float = 0.8, **metadata: Any) -> MomentumTarget:
        normalized = _normalize(value, kind)
        self.sequence += 1
        self.targets = [item for item in self.targets if not (item.kind == kind and _normalize(item.value, item.kind).casefold() == normalized.casefold())]
        target = MomentumTarget(value=value, kind=kind, source=source, confidence=max(0.0, min(1.0, confidence)), sequence=self.sequence, metadata=metadata)
        self.targets.insert(0, target)
        del self.targets[self.max_targets:]
        return target

    def recent(self, *, kind: str = "", limit: int = 8) -> list[MomentumTarget]:
        selected = [item for item in self.targets if not kind or item.kind == kind]
        return selected[:max(0, limit)]

    def score_bonus(self, value: str, kind: str = "") -> tuple[float, list[str]]:
        normalized = _normalize(value, kind)
        for rank, item in enumerate(self.targets):
            candidate = _normalize(item.value, item.kind)
            if candidate.casefold() != normalized.casefold():
                continue
            recency = max(0.2, 1.0 - rank * 0.08)
            bonus = 180.0 * recency * item.confidence
            return bonus, [f"recent {item.kind} context rank={rank + 1}", f"momentum source={item.source}"]
        return 0.0, []

    def to_dict(self) -> dict[str, Any]:
        return {"targets": [item.to_dict() for item in self.targets], "max_targets": self.max_targets, "sequence": self.sequence}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ContextMomentum":
        data = dict(data or {})
        return cls(
            targets=[MomentumTarget(**item) for item in data.get("targets") or []],
            max_targets=int(data.get("max_targets") or 24),
            sequence=int(data.get("sequence") or 0),
        )


def momentum_from_operation_memory(memory: dict[str, Any] | None) -> ContextMomentum:
    memory = dict(memory or {})
    existing = memory.get("context_momentum")
    momentum = ContextMomentum.from_dict(existing if isinstance(existing, dict) else {})
    for key, kind in (
        ("active_file", "file"),
        ("recent_file", "file"),
        ("selected_file", "file"),
        ("recent_symbol", "symbol"),
        ("selected_symbol", "symbol"),
        ("recent_asset", "asset"),
        ("recent_widget", "widget"),
        ("recent_graph", "graph"),
    ):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            momentum.remember(value, kind, source="operation_memory", confidence=0.9)
    return momentum


def _normalize(value: str, kind: str) -> str:
    value = str(value or "").strip()
    if kind in {"file", "path", "filename"}:
        try:
            return str(Path(value)).replace("\\", "/")
        except Exception:
            return value.replace("\\", "/")
    return value
