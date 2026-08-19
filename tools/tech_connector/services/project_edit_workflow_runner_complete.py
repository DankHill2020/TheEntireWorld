"""Project-edit workflow phase: _run_completion_phase."""

from __future__ import annotations
from tech_connector.services import project_edit_workflow_runner_dependencies as _deps
from tech_connector.services.project_edit_workflow_runner_control import _WorkflowReturn


class _ProjectEditCompletionPhase:
    """Provide the completion workflow phase."""

    def _run_completion_phase(self) -> None:
        """Run the completion phase.

        :return: None.
        """
        raise _WorkflowReturn(
            _deps.ProjectEditWorkflowResult(
                ok=False,
                status="preview_failed",
                candidate=self.candidate,
                preview=self.preview,
                errors=(
                    list(self.preview.errors or [])
                    if self.preview
                    else ["No preview was produced."]
                ),
                timings=self.timings,
            )
        )
