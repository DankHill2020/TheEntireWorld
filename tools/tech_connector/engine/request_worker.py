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
        """
        Initialize the worker and its lightweight immutable runtime registry.
        :param context: sanitized request context
        :param parent: optional Qt parent object
        :return: None
        """
        super().__init__(parent)
        self.context = context
        self._cancelled = False
        # Constructing the registry in the owning thread avoids lazy Python
        # imports contending with the Qt event loop after QThread starts. The
        # expensive request processing and retrieval still run in ``run``.
        prompt_provider_route = None
        settings = dict(getattr(parent, "settings", {}) or {})
        try:
            selected = str(
                settings.get("model")
                or settings.get("cloud_provider_model")
                or settings.get("general_model")
                or context.model
                or "qwen3:4b-instruct"
            )
            if selected.startswith("ollama:") or (
                ":" not in selected
                and not settings.get("cloud_provider_model")
            ):
                from reasoning_runtime.models import ModelProviderRoute

                prompt_provider_route = ModelProviderRoute(
                    "ollama",
                    selected.removeprefix("ollama:").strip()
                    or "qwen3:4b-instruct",
                )
            else:
                from tech_connector.services.llm_router_service import (
                    resolve_llm_provider_route,
                )

                prompt_provider_route = resolve_llm_provider_route(
                    selected,
                    settings,
                )
        except Exception:
            prompt_provider_route = None
        self._engine = RequestEngine(
            prompt_provider_route=prompt_provider_route,
            settings=settings,
        )

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
            self._engine.progress = self._emit_progress
            self._engine.activity = self._emit_activity
            result = self._engine.process(self.context)
            if self._cancelled:
                result = EngineResult("error", "Cancelled", "Request cancelled.")
            self.finished_result.emit(result)
        except Exception as exc:
            self.finished_result.emit(EngineResult("error", "Intelligence Engine", f"Request preparation failed: {exc}"))
