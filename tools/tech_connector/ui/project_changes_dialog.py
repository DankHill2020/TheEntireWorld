"""Compatibility exports for project-change review dialogs.

The canonical dialog implementations live in ``chat_worker_dialogs``. This
module keeps the older import path without carrying duplicate Qt class bodies.
"""

from tech_connector.ui.chat_worker_dialogs import (  # noqa: F401
    ChatLogBrowser,
    ProjectChangesDialog,
    WorkflowOutputSelectorDialog,
)
