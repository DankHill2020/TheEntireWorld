"""Growing prompt editor for the unified chat input."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QTextEdit


class GrowingPromptEdit(QTextEdit):
    """A QTextEdit with QLineEdit-compatible helpers used by the chat runtime."""

    sendRequested = Signal()
    textChangedString = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min_height = 36
        self._resize_pending_text = ""
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._apply_pending_resize)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.document().setDocumentMargin(4)
        self.textChanged.connect(self._on_text_changed)
        self._resize_to_document()

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt compatibility shim
        self.setPlainText(text or "")
        self.moveCursor(self.textCursor().MoveOperation.End)
        self._schedule_resize(text or "")

    def cursorPosition(self) -> int:  # noqa: N802 - QLineEdit compatibility shim
        return self.textCursor().position()

    def setCursorPosition(self, position: int) -> None:  # noqa: N802 - QLineEdit compatibility shim
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(int(position or 0), len(self.text()))))
        self.setTextCursor(cursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            event.accept()
            self.sendRequested.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_resize(self.toPlainText(), delay_ms=0)

    def _on_text_changed(self) -> None:
        text = self.toPlainText()
        self._schedule_resize(text)
        self.textChangedString.emit(text)

    def _schedule_resize(self, text: str, delay_ms: int = 45) -> None:
        self._resize_pending_text = text or ""
        self._resize_timer.start(max(0, int(delay_ms)))

    def _apply_pending_resize(self) -> None:
        self._resize_to_document(self._resize_pending_text)

    def _max_prompt_height(self) -> int:
        window = self.window()
        tabs = getattr(window, "workspace_tabs", None)
        current = tabs.currentWidget() if tabs is not None and hasattr(tabs, "currentWidget") else None
        source_height = current.height() if current is not None else window.height()
        return max(72, int(source_height / 3))

    def _resize_to_document(self, text=None) -> None:
        doc_height = int(self.document().size().height()) + 12
        wanted = max(self._min_height, doc_height)
        self.setFixedHeight(min(wanted, self._max_prompt_height()))
