from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.app.main_window_workflows import PipelineBridgeRunWorker


def test_pipeline_bridge_worker_keeps_call_off_ui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    started = threading.Event()
    release = threading.Event()
    worker_threads = []
    completed = []

    def execute(host, source, *, timeout):
        worker_threads.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return True, {"host": host, "source": source, "timeout": timeout}

    ui_thread = threading.get_ident()
    worker = PipelineBridgeRunWorker(
        execute, "maya", "print('demo')", timeout_seconds=45,
    )
    worker.completed.connect(
        lambda ok, result: completed.append((ok, result)),
        Qt.ConnectionType.DirectConnection,
    )

    before = time.perf_counter()
    worker.start()
    start_elapsed = time.perf_counter() - before

    assert start_elapsed < 0.1
    assert started.wait(1)
    assert worker.isRunning()
    assert worker_threads != [ui_thread]
    release.set()
    assert worker.wait(2000)
    assert completed == [(True, {"host": "maya", "source": "print('demo')", "timeout": 45.0})]


def test_pipeline_bridge_worker_reports_failure_without_cross_thread_exception() -> None:
    app = QApplication.instance() or QApplication([])
    failures = []

    def execute(*_args, **_kwargs):
        raise TimeoutError("Maya bridge timed out")

    worker = PipelineBridgeRunWorker(execute, "maya", "pass")
    worker.failed.connect(failures.append, Qt.ConnectionType.DirectConnection)
    worker.start()
    assert worker.wait(2000)

    assert failures == ["Maya bridge timed out"]
