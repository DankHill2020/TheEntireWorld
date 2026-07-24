from __future__ import annotations

import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer

from tech_connector.app.main_window_editor import MainWindowEditorMixin


class _EditorAssistProgressHarness(MainWindowEditorMixin, QObject):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def set_live_process(self, text: str) -> None:
        self.messages.append(text)


class TestEditorAssistProgress(unittest.TestCase):
    def test_progress_timer_reports_stage_and_elapsed_time(self) -> None:
        _app = QCoreApplication.instance() or QCoreApplication([])
        harness = _EditorAssistProgressHarness()
        import time
        original_monotonic = time.monotonic
        t = [100.0]
        time.monotonic = lambda: t[0]
        try:
            harness._start_editor_assist_progress("Generating helper")
            t[0] = 101.5
            harness._refresh_editor_assist_progress()
            harness._on_editor_assist_status("Validating preview")
            harness._stop_editor_assist_progress()
        finally:
            time.monotonic = original_monotonic

        self.assertTrue(any(message == "Generating helper (0s)" for message in harness.messages))
        self.assertTrue(any("Generating helper (1s)" in message for message in harness.messages))
        self.assertEqual("Validating preview (1s)", harness.messages[-1])
        self.assertIsNone(harness._editor_assist_progress_timer)


if __name__ == "__main__":
    unittest.main()
