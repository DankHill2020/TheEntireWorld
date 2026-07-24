from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from tech_connector.app.main_window_chat_runtime import MainWindowChatRuntimeMixin
from tech_connector.services.asset_mention_service import MentionCandidate
from tech_connector.ui.growing_prompt_edit import GrowingPromptEdit


class _Candidate:
    def __init__(self, token: str, label: str) -> None:
        self.token = token
        self._label = label

    def display(self) -> str:
        return self._label


class _AutocompleteHarness(MainWindowChatRuntimeMixin, QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.input = GrowingPromptEdit(self)
        self.input.resize(320, 36)
        self.input.installEventFilter(self)

    def _log_ui_diagnostic(self, *_args, **_kwargs) -> None:
        pass


class TestChatAutocompletePopup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_popup_is_compact_and_tab_accepts_current_candidate(self) -> None:
        window = _AutocompleteHarness()
        window.resize(420, 120)
        window.input.setText("@Maya.cre")
        window.input.setCursorPosition(len("@Maya.cre"))
        window._autocomplete_query_seq = 1
        suggestions = [
            _Candidate(f"Maya.create_{index}", f"@Maya.create_{index} - very long candidate details " * 4)
            for index in range(12)
        ]

        window._apply_autocomplete_suggestions(1, 0, window.input.cursorPosition(), suggestions)

        popup = window._autocomplete_menu
        self.assertTrue(popup.isVisible())
        self.assertLessEqual(popup.count(), 5)
        self.assertLessEqual(popup.width(), 640)
        self.assertEqual(0, popup.currentRow())

        tab = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        handled = window.eventFilter(window.input, tab)

        self.assertTrue(handled)
        self.assertIn("@Maya.create_0", window.input.text())
        self.assertFalse(popup.isVisible())

    def test_down_arrow_selects_another_candidate_before_tab(self) -> None:
        window = _AutocompleteHarness()
        window.resize(420, 120)
        window.input.setText("@Maya.cre")
        window.input.setCursorPosition(len("@Maya.cre"))
        window._autocomplete_query_seq = 1
        suggestions = [_Candidate(f"Maya.create_{index}", f"@Maya.create_{index}") for index in range(3)]
        window._apply_autocomplete_suggestions(1, 0, window.input.cursorPosition(), suggestions)

        down = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        tab = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)

        self.assertTrue(window.eventFilter(window.input, down))
        self.assertEqual(1, window._autocomplete_menu.currentRow())
        self.assertTrue(window.eventFilter(window.input, tab))
        self.assertIn("@Maya.create_1", window.input.text())

    def test_project_file_candidate_displays_stem_but_inserts_module_token(self) -> None:
        window = _AutocompleteHarness()
        window.resize(420, 120)
        window.input.setText("@custom_q")
        window.input.setCursorPosition(len("@custom_q"))
        window._autocomplete_query_seq = 1
        suggestion = MentionCandidate(
            token="custom_qt.custom_widgets",
            label="custom_widgets",
            kind="project_file",
            value="custom_qt/custom_widgets.py",
            source="knowledge_index",
            detail="custom_qt/custom_widgets.py",
        )

        window._apply_autocomplete_suggestions(1, 0, window.input.cursorPosition(), [suggestion])

        popup = window._autocomplete_menu
        self.assertTrue(popup.isVisible())
        self.assertIn("@custom_widgets", popup.item(0).text())
        self.assertNotIn("@py", popup.item(0).text())
        self.assertEqual("custom_qt.custom_widgets", popup.item(0).data(Qt.UserRole))

        tab = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        self.assertTrue(window.eventFilter(window.input, tab))
        self.assertIn("@custom_qt.custom_widgets", window.input.text())


if __name__ == "__main__":
    unittest.main()
