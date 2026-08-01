"""Process-environment normalization shared by UI and headless entrypoints."""

from __future__ import annotations

import os
from collections.abc import Mapping


def sanitized_subprocess_environment(
    source: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a case-insensitively deduplicated environment mapping."""

    values = source if source is not None else os.environ
    normalized: dict[str, tuple[str, str]] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key)
        value = str(raw_value)
        folded = key.casefold()
        existing = normalized.get(folded)
        if existing is None:
            normalized[folded] = (key, value)
            continue
        existing_key, existing_value = existing
        if folded == "path":
            merged: list[str] = []
            seen: set[str] = set()
            for item in (existing_value + os.pathsep + value).split(os.pathsep):
                cleaned = item.strip()
                identity = cleaned.casefold()
                if cleaned and identity not in seen:
                    seen.add(identity)
                    merged.append(cleaned)
            normalized[folded] = (
                "Path" if os.name == "nt" else existing_key,
                os.pathsep.join(merged),
            )

    if overrides:
        for raw_key, raw_value in overrides.items():
            key = str(raw_key)
            normalized[key.casefold()] = (key, str(raw_value))

    return {
        ("Path" if os.name == "nt" and folded == "path" else key): value
        for folded, (key, value) in normalized.items()
    }


def normalize_current_process_environment() -> None:
    """Replace inherited case-colliding keys with one canonical mapping."""

    normalized = sanitized_subprocess_environment()
    os.environ.clear()
    os.environ.update(normalized)
