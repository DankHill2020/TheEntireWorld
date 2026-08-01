"""Qt worker wrapper for The Entire World Intelligence Engine."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .request_engine import RequestEngine
from reasoning_runtime.engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from reasoning_runtime.engine.request_context import RequestContext


class RequestPreparationWorker(QThread):
    """Prepare expensive request context away from the UI thread."""

    progress = Signal(str)
    activity = Signal(object)
    finished_result = Signal(object)

    def __init__(self, context: RequestContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _emit_progress(self, event: ProgressEvent) -> None:
        if not self._cancelled:
            self.progress.emit(event.display_text())

    def _emit_activity(self, event: ActivityEvent) -> None:
        if not self._cancelled:
            self.activity.emit(event)

    def run(self) -> None:
        if self._cancelled:
            self.finished_result.emit(EngineResult("error", "Cancelled", "Request cancelled."))
            return
        try:
            engine = RequestEngine(progress=self._emit_progress, activity=self._emit_activity)
            result = engine.process(self.context)
            if self._cancelled:
                result = EngineResult("error", "Cancelled", "Request cancelled.")
            self.finished_result.emit(result)
        except Exception as exc:
            self.finished_result.emit(EngineResult("error", "Intelligence Engine", f"Request preparation failed: {exc}"))
