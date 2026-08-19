"""Control-flow signals shared by project-edit workflow phases."""

from __future__ import annotations

from typing import Any


class _WorkflowControlFlow(BaseException):
    """Base signal that bypasses ordinary workflow exception handling."""


class _WorkflowContinue(_WorkflowControlFlow):
    """Continue the outer workflow retry loop."""


class _WorkflowBreak(_WorkflowControlFlow):
    """Break the outer workflow retry loop."""


class _WorkflowReturn(_WorkflowControlFlow):
    """Return a result across a workflow phase boundary."""

    def __init__(self, value: Any) -> None:
        """Store the workflow result.

        :param value: Result returned by the original workflow body.
        """

        super().__init__()
        self.value = value
