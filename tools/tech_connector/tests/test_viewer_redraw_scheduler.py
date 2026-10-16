from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_03 import (
    ThreeDMeshPainterViewportMixin03,
)
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_02 import (
    ThreeDMeshPainterViewportMixin02,
)


class _CountingCanvas:
    def __init__(self) -> None:
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


class _Host(ThreeDMeshPainterViewportMixin03):
    def __init__(self) -> None:
        self.canvas = _CountingCanvas()
        self._last_paint_canvas_update_s = 0.0
        self._paint_canvas_update_pending = False


def test_dcc_canvas_redraw_requests_are_coalesced() -> None:
    app = QApplication.instance() or QApplication([])
    host = _Host()

    host.schedule_paint_canvas_update(interval_ms=40)
    host.schedule_paint_canvas_update(interval_ms=40)
    host.schedule_paint_canvas_update(interval_ms=40)

    assert host.canvas.updates == 1
    QTest.qWait(55)
    assert host.canvas.updates == 2
    assert host._paint_canvas_update_pending is False
    assert app is QApplication.instance()


class _SignalStub:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _ThreadStub:
    def __init__(self) -> None:
        self.interrupted = False
        self.quit_requested = False
        self.parent = None
        self.finished = _SignalStub()

    def requestInterruption(self) -> None:
        self.interrupted = True

    def quit(self) -> None:
        self.quit_requested = True

    def isRunning(self) -> bool:
        return True

    def setParent(self, parent) -> None:
        self.parent = parent


class _BackgroundHost(ThreeDMeshPainterViewportMixin02):
    pass


def test_hiding_viewer_releases_background_thread_without_waiting() -> None:
    app = QApplication.instance() or QApplication([])
    host = _BackgroundHost()
    thread = _ThreadStub()

    host._release_background_thread(thread)

    assert thread.interrupted is True
    assert thread.quit_requested is True
    assert thread.parent is app
    assert host._detached_background_threads == [thread]
    assert len(thread.finished.callbacks) == 1
