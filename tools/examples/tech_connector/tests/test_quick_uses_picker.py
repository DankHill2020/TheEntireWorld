import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from tech_connector.app.main_window_workflows import MainWindowWorkflowsMixin


class _QuickUsesHarness(MainWindowWorkflowsMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.previewed = []

    def _collect_uses_results(self, query, project_wide=False, max_results=500):
        return [
            {"path": "", "line": 10, "text": "first use"},
            {"path": "", "line": 20, "text": "second use"},
        ]

    def _open_or_focus_file_at_line(self, path, line_number, preview=False):
        self.previewed.append((line_number, preview))


class QuickUsesPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_down_recovers_list_focus_while_popup_is_active(self):
        harness = _QuickUsesHarness()
        harness.show()
        popup = harness._quick_uses_popup("get_twists", project_wide=True)
        QTest.qWait(180)
        result_list = popup.findChild(QListWidget)

        harness.setFocus()
        QApplication.processEvents()
        QTest.keyClick(harness, Qt.Key_Down)
        QApplication.processEvents()

        self.assertTrue(result_list.hasFocus())
        self.assertEqual(result_list.currentRow(), 1)
        self.assertEqual(harness.previewed[-1], (20, True))

        harness.setFocus()
        QTest.keyClick(harness, Qt.Key_Up)
        QApplication.processEvents()
        self.assertTrue(result_list.hasFocus())
        self.assertEqual(result_list.currentRow(), 0)
        self.assertEqual(harness.previewed[-1], (10, True))
        popup.reject()
        harness.close()

    def test_inactivity_timeout_keeps_focused_popup_open(self):
        harness = _QuickUsesHarness()
        harness.show()
        popup = harness._quick_uses_popup("get_twists", project_wide=False)
        QTest.qWait(180)
        result_list = popup.findChild(QListWidget)
        result_list.setFocus()
        QApplication.processEvents()

        popup._quick_uses_inactivity_timer.timeout.emit()
        QApplication.processEvents()

        self.assertTrue(popup.isVisible())
        self.assertEqual(popup._quick_uses_inactivity_timer.interval(), 3000)
        popup.reject()
        harness.close()


if __name__ == "__main__":
    unittest.main()
