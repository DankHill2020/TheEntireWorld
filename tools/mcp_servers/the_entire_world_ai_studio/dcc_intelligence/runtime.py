"""Shared runtime helpers for DCC health checks and staged scans."""
from __future__ import annotations

from datetime import datetime
import time
from typing import Any, Callable


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000.0, 2)


def stage_result(
    name: str,
    ok: bool,
    start: float,
    *,
    count: int | None = None,
    error: str | None = None,
    used_cache: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "duration_ms": elapsed_ms(start),
        "count": count,
        "error": error,
        "used_cache": bool(used_cache),
    }


class TTLMemoryCache:
    """Tiny in-process TTL cache for read-only DCC checks."""

    def __init__(self):
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl_seconds: float) -> Any | None:
        item = self._items.get(key)
        if not item:
            return None
        created, value = item
        if ttl_seconds > 0 and time.monotonic() - created <= ttl_seconds:
            return value
        return None

    def set(self, key: str, value: Any) -> Any:
        self._items[key] = (time.monotonic(), value)
        return value

    def get_or_set(self, key: str, ttl_seconds: float, factory: Callable[[], Any]) -> tuple[Any, bool]:
        cached = self.get(key, ttl_seconds)
        if cached is not None:
            return cached, True
        value = factory()
        self.set(key, value)
        return value, False
