from __future__ import annotations

from tech_connector.services.dcc.host_thread_policy_service import build_host_thread_policy


def test_maya_ui_plan_requires_main_thread_marshalling() -> None:
    policy = build_host_thread_policy(
        "Build a PySide6 UI that calls a Maya rig function without freezing.",
        {"host": "maya"},
    )

    assert policy["host_api_thread"] == "main"
    assert policy["required_adapter"] == "maya.utils.executeInMainThreadWithResult"
    assert any("background workers only" in rule for rule in policy["rules"])


def test_host_thread_policy_is_not_added_to_plain_project_code() -> None:
    assert build_host_thread_policy("Refactor this Python parser.", {}) == {}
