"""Regression tests for the phase-based project-edit workflow runner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_part_10 import (
    _ProjectEditWorkflowRunner,
    run_multi_file_project_edit_workflow,
)
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowContinue,
    _WorkflowReturn,
)


def _runner(tmp_path: Path) -> _ProjectEditWorkflowRunner:
    """Build a runner suitable for control-flow tests.

    :param tmp_path: Temporary project root.
    :return: Configured workflow runner.
    """

    return _ProjectEditWorkflowRunner(
        "Create tool.py",
        project_root=str(tmp_path),
        active_path="",
        selected_model="test-model",
        settings={},
        timeout=1,
        dry_run=True,
        max_attempts=2,
        status_callback=None,
        approved_plan_id="",
        plan_only=False,
        original_prompt="",
    )


def test_runner_preserves_phase_order_and_cross_phase_return(tmp_path: Path) -> None:
    """The facade should run phases in order and unwrap a return signal.

    :param tmp_path: Temporary project root.
    """

    runner = _runner(tmp_path)
    observed: list[str] = []
    for name in (
        "planning",
        "contract",
        "requirement",
        "generation",
        "verification",
    ):
        setattr(
            runner,
            f"_run_{name}_phase",
            lambda phase=name: observed.append(phase),
        )
    runner.starting_attempt = 1

    def finish() -> None:
        """Return a sentinel through the workflow control channel."""

        observed.append("attempt_prepare")
        raise _WorkflowReturn("complete")

    runner._run_attempt_prepare_phase = finish

    assert runner.run() == "complete"
    assert observed == [
        "planning",
        "contract",
        "requirement",
        "generation",
        "verification",
        "attempt_prepare",
    ]


def test_runner_preserves_retry_loop_continue(tmp_path: Path) -> None:
    """A phase continue signal should start the next retry attempt.

    :param tmp_path: Temporary project root.
    """

    runner = _runner(tmp_path)
    for name in (
        "planning",
        "contract",
        "requirement",
        "generation",
        "verification",
    ):
        setattr(runner, f"_run_{name}_phase", lambda: None)
    runner.starting_attempt = 1
    attempts: list[int] = []

    def prepare() -> None:
        """Continue once and return on the second attempt."""

        attempts.append(runner.attempt)
        if len(attempts) == 1:
            raise _WorkflowContinue()
        raise _WorkflowReturn("retried")

    runner._run_attempt_prepare_phase = prepare

    assert runner.run() == "retried"
    assert attempts == [1, 2]


def test_public_runner_preserves_early_non_artifact_result(tmp_path: Path) -> None:
    """An early planning return should retain its status and error payload.

    :param tmp_path: Temporary project root.
    """

    route = SimpleNamespace(cloud_active=False, model="test-model")
    with (
        patch.object(_deps, "resolve_llm_provider_route", return_value=route),
        patch.object(_deps, "build_project_edit_agent_request", return_value=object()),
        patch.object(
            _deps,
            "build_project_edit_artifact_manifest_stage",
            return_value=None,
        ),
    ):
        result = run_multi_file_project_edit_workflow(
            "Improve the current implementation",
            project_root=str(tmp_path),
            selected_model="test-model",
        )

    assert result.ok is False
    assert result.status == "not_multi_file_artifact"
    assert "exact artifact owner" in result.errors[0]
