"""Public entry point for the multi-file project-edit workflow."""

from __future__ import annotations

from typing import Any, cast

from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import (
    _WorkflowBreak,
    _WorkflowContinue,
    _WorkflowReturn,
)
from tech_connector.services.project_edit_workflow_runner_dependencies import (
    ProjectEditWorkflowResult,
    StatusCallback,
)
from tech_connector.services.project_edit_workflow_runner_planning import (
    _ProjectEditPlanningPhase,
)
from tech_connector.services.project_edit_workflow_runner_contracts import (
    _ProjectEditContractPhase,
)
from tech_connector.services.project_edit_workflow_runner_requirements import (
    _ProjectEditRequirementPhase,
)
from tech_connector.services.project_edit_workflow_runner_generation import (
    _ProjectEditGenerationPhase,
)
from tech_connector.services.project_edit_workflow_runner_verification import (
    _ProjectEditVerificationPhase,
)
from tech_connector.services.project_edit_workflow_runner_complete import (
    _ProjectEditCompletionPhase,
)
from tech_connector.services.project_edit_workflow_runner_attempt_prepare import (
    _ProjectEditAttemptPreparePhase,
)
from tech_connector.services.project_edit_workflow_runner_attempt_synthesize import (
    _ProjectEditAttemptSynthesizePhase,
)
from tech_connector.services.project_edit_workflow_runner_attempt_validate import (
    _ProjectEditAttemptValidatePhase,
)
from tech_connector.services.project_edit_workflow_runner_attempt_finalize import (
    _ProjectEditAttemptFinalizePhase,
)


class _ProjectEditWorkflowRunner(
    _ProjectEditPlanningPhase,
    _ProjectEditContractPhase,
    _ProjectEditRequirementPhase,
    _ProjectEditGenerationPhase,
    _ProjectEditVerificationPhase,
    _ProjectEditCompletionPhase,
    _ProjectEditAttemptPreparePhase,
    _ProjectEditAttemptSynthesizePhase,
    _ProjectEditAttemptValidatePhase,
    _ProjectEditAttemptFinalizePhase,
):
    """Execute project-edit workflow phases against shared explicit state."""

    def __init__(
        self,
        prompt: str,
        *,
        project_root: str,
        active_path: str,
        selected_model: str,
        settings: dict[str, Any] | None,
        timeout: int,
        dry_run: bool,
        max_attempts: int,
        status_callback: StatusCallback | None,
        approved_plan_id: str,
        plan_only: bool,
        original_prompt: str,
    ) -> None:
        """Initialize shared workflow state.

        :param prompt: Project-edit request.
        :param project_root: Absolute or resolvable project root.
        :param active_path: Optional active editor path.
        :param selected_model: Requested model identifier.
        :param settings: Optional provider and workflow settings.
        :param timeout: Model request timeout in seconds.
        :param dry_run: Whether edits must remain in a disposable workspace.
        :param max_attempts: Maximum generation and repair attempts.
        :param status_callback: Optional workflow status callback.
        :param approved_plan_id: Optional approved implementation plan identifier.
        :param plan_only: Whether to stop after implementation planning.
        :param original_prompt: Original user prompt before workflow augmentation.
        """

        self.prompt = prompt
        self.project_root = project_root
        self.active_path = active_path
        self.selected_model = selected_model
        self.settings = settings
        self.timeout = timeout
        self.dry_run = dry_run
        self.max_attempts = max_attempts
        self.status_callback = status_callback
        self.approved_plan_id = approved_plan_id
        self.plan_only = plan_only
        self.original_prompt = original_prompt
        self.harness_source = ""

    def run(self) -> ProjectEditWorkflowResult:
        """Run every phase and preserve the legacy return contract.

        :return: Project-edit workflow result.
        """

        try:
            self._run_planning_phase()
            self._run_contract_phase()
            self._run_requirement_phase()
            self._run_generation_phase()
            self._run_verification_phase()
            for self.attempt in _deps.itertools.count(self.starting_attempt):
                try:
                    self._run_attempt_prepare_phase()
                    self._run_attempt_synthesize_phase()
                    self._run_attempt_validate_phase()
                    self._run_attempt_finalize_phase()
                except _WorkflowContinue:
                    continue
                except _WorkflowBreak:
                    break
            self._run_completion_phase()
        except _WorkflowReturn as signal:
            return cast(ProjectEditWorkflowResult, signal.value)
        raise RuntimeError("Project-edit workflow completed without a result.")


def run_multi_file_project_edit_workflow(
    prompt: str,
    *,
    project_root: str,
    active_path: str = "",
    selected_model: str,
    settings: dict[str, Any] | None = None,
    timeout: int = 120,
    dry_run: bool = True,
    max_attempts: int = 5,
    status_callback: StatusCallback | None = None,
    approved_plan_id: str = "",
    plan_only: bool = False,
    original_prompt: str = "",
) -> ProjectEditWorkflowResult:
    """Run the shared one-or-many-file project-edit workflow.

    :param prompt: Project-edit request.
    :param project_root: Absolute or resolvable project root.
    :param active_path: Optional active editor path.
    :param selected_model: Requested model identifier.
    :param settings: Optional provider and workflow settings.
    :param timeout: Model request timeout in seconds.
    :param dry_run: Whether edits must remain in a disposable workspace.
    :param max_attempts: Maximum generation and repair attempts.
    :param status_callback: Optional workflow status callback.
    :param approved_plan_id: Optional approved implementation plan identifier.
    :param plan_only: Whether to stop after implementation planning.
    :param original_prompt: Original user prompt before workflow augmentation.
    :return: Project-edit workflow result.
    """

    return _ProjectEditWorkflowRunner(
        prompt,
        project_root=project_root,
        active_path=active_path,
        selected_model=selected_model,
        settings=settings,
        timeout=timeout,
        dry_run=dry_run,
        max_attempts=max_attempts,
        status_callback=status_callback,
        approved_plan_id=approved_plan_id,
        plan_only=plan_only,
        original_prompt=original_prompt,
    ).run()
