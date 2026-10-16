from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tech_connector.services.knowledge_background_service import KnowledgeBuildWorker


def test_silent_knowledge_child_is_stopped_at_wall_clock_limit() -> None:
    QApplication.instance() or QApplication([])
    worker = KnowledgeBuildWorker(max_runtime_seconds=0.2)
    worker._phase_cmds = lambda: [
        ("Silent demo index", [sys.executable, "-c", "import time; time.sleep(30)"])
    ]
    results = []
    worker.finished_ok.connect(
        lambda ok, message: results.append((ok, message)),
        Qt.ConnectionType.DirectConnection,
    )

    worker.start()
    assert worker.wait(5000)

    assert results
    assert results[-1][0] is False
    assert "exceeded the 0.2s safety limit" in results[-1][1]
