"""Small background workers for recurring project intelligence checks."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class IndexSyncWorker(QThread):
    """Check whether indexed files are stale without blocking the UI."""

    finished_result = Signal(object)

    def __init__(self, active_path: str = "", limit: int = 20, parent=None):
        super().__init__(parent)
        self.active_path = active_path
        self.limit = limit

    def run(self):
        try:
            from tech_connector.services.project_service import index_sync_summary
            self.finished_result.emit(index_sync_summary(self.active_path, limit=self.limit))
        except Exception as exc:
            self.finished_result.emit({"error": str(exc), "stale": False})
