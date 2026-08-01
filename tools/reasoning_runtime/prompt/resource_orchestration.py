"""Prompt resource orchestration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResourceLane:
    key: str
    label: str
    max_concurrent: int
    work: tuple[str, ...]
    user_visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "max_concurrent": self.max_concurrent,
            "work": list(self.work),
            "user_visible": self.user_visible,
        }
