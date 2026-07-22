"""First-party Unreal feature orchestration contracts."""

from __future__ import annotations

from typing import Any


def execute_generic_plan(plan: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """
        Execute generic plan.
    :param plan: approved Unreal feature plan
    :param dry_run: whether to validate execution readiness without mutating assets
    :return: serializable orchestration contract
    """

    plan = dict(plan or {})
    if dry_run:
        return {
            "ok": True,
            "operation": "feature.execute_generic_plan",
            "execution_channel": "approved_unreal_feature_plan_executor",
            "dry_run": True,
            "plan": plan,
            "implemented": True,
            "validated": False,
        }

    return {
        "ok": False,
        "operation": "feature.execute_generic_plan",
        "execution_channel": "approved_unreal_feature_plan_executor",
        "dry_run": False,
        "plan": plan,
        "implemented": False,
        "validated": False,
        "errors": [
            "Non-dry-run operation plans must execute in the desktop orchestrator so each registered operation can be routed and verified."
        ],
    }
