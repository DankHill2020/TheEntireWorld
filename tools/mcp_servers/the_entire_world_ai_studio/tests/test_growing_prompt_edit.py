from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget, QVBoxLayout

from ui.growing_prompt_edit import GrowingPromptEdit


class TestGrowingPromptEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_text_api_and_height_cap(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        tabs = QTabWidget(host)
        page = QWidget()
        page.resize(400, 300)
        tabs.addTab(page, "Chat")
        layout.addWidget(tabs)
        host.workspace_tabs = tabs
        host.resize(400, 300)

        edit = GrowingPromptEdit(host)
        layout.addWidget(edit)
        edit.setText("\n".join(f"line {i}" for i in range(20)))

        self.assertIn("line 19", edit.text())
        self.assertLessEqual(edit.height(), 100)

    def test_enter_sends_shift_enter_adds_newline(self) -> None:
        edit = GrowingPromptEdit()
        sent = []
        edit.sendRequested.connect(lambda: sent.append(True))

        enter = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        edit.keyPressEvent(enter)
        self.assertTrue(sent)

        edit.setText("hello")
        shift_enter = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier)
        edit.keyPressEvent(shift_enter)
        self.assertIn("\n", edit.text())


if __name__ == "__main__":
    unittest.main()
