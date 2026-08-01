"""Prompt plan-verification payload helpers."""

from __future__ import annotations

from typing import Any


def extract_plan_verification(value: Any) -> dict[str, Any]:
    """Find a nested request/plan verification payload."""

    if isinstance(value, (list, tuple)):
        for nested in value:
            found = extract_plan_verification(nested)
            if found:
                return found
        return {}
    if not isinstance(value, dict):
        return {}
    direct = value.get("request_plan_verification")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    for key in ("request_plan_verification", "plan_verification", "capability_gap_plan"):
        nested = value.get(key)
        if isinstance(nested, dict):
            found = extract_plan_verification(nested)
            if found:
                return found
    for nested in value.values():
        if not isinstance(nested, (dict, list, tuple)):
            continue
        found = extract_plan_verification(nested)
        if found:
            return found
    return {}
