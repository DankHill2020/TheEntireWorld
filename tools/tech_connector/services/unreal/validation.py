"""First-party Unreal runtime validation contracts."""

from __future__ import annotations

from typing import Any


def pie_validate(
    target_assets: list[str] | None = None,
    expected: dict[str, Any] | None = None,
    start_pie: bool = False,
) -> dict[str, Any]:
    """
        Validate PIE readiness.
    :param target_assets: assets that should exist before runtime validation
    :param expected: expected runtime postconditions
    :param start_pie: whether validation may start PIE
    :return: serializable runtime validation contract
    """

    return {
        "operation": "runtime.pie_validate",
        "execution_channel": "command_router.execute_unreal_operation",
        "target_assets": list(target_assets or []),
        "expected": dict(expected or {}),
        "start_pie": start_pie,
        "implemented": True,
    }

