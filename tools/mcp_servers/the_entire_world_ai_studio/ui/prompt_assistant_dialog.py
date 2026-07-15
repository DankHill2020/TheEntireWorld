from __future__ import annotations

"""Optional Prompt Assistant window for Tech Connector.

This dialog is intentionally opt-in. It does not replace the existing bottom
chat prompt. It lets the user compose a larger prompt, optionally gather staged
context, preview what will be sent, and then copy/use/send that visible content.
"""

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


@dataclass
class PromptAssistantOptions:
    include_unreal: bool = True
    include_code: bool = True
    include_cpp_wrappers: bool = True
    max_items: int = 8


class PromptAssistantDialog(QDialog):
    """Large optional composer for staged context and DCC-heavy prompts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window_ref = parent
        self.current_draft = None
        self.setWindowTitle("Prompt Assistant")
        self.resize(1100, 760)
        self.setMinimumSize(760, 520)
        self._build_ui()
        self._load_current_prompt_from_main_window()
        self._refresh_status("Ready")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Prompt Assistant")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.status_label)
        root.addLayout(header)

        help_text = QLabel(
            "Use the normal chat box for quick prompts. Use this window when you want a larger prompt, "
            "staged project/DCC context, or a reviewable prompt before sending."
        )
        help_text.setWordWrap(True)
        root.addWidget(help_text)

        self.mode_tabs = QTabWidget()
        self.mode_tabs.addTab(self._build_quick_tab(), "Quick Prompt")
        self.mode_tabs.addTab(self._build_composer_tab(), "DCC / Context Composer")
        root.addWidget(self.mode_tabs, 1)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_preview_or_prompt)
        buttons.addWidget(self.copy_button)

        self.use_in_chat_button = QPushButton("Use in Chat Prompt")
        self.use_in_chat_button.clicked.connect(self.use_in_chat_prompt)
        buttons.addWidget(self.use_in_chat_button)

        self.send_button = QPushButton("Send to Chat")
        self.send_button.clicked.connect(self.send_to_chat)
        buttons.addWidget(self.send_button)

        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

    def _build_quick_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Prompt"))
        self.quick_prompt_edit = QPlainTextEdit()
        self.quick_prompt_edit.setPlaceholderText("Type a prompt here, then use it in the chat prompt or send it directly.")
        self.quick_prompt_edit.setMinimumHeight(260)
        layout.addWidget(self.quick_prompt_edit, 1)

        note = QLabel("Quick mode sends exactly the visible prompt text. It does not auto-add context.")
        note.setWordWrap(True)
        layout.addWidget(note)
        return tab

    def _build_composer_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        option_row = QHBoxLayout()
        self.include_unreal_box = QCheckBox("Unreal / DCC context")
        self.include_unreal_box.setChecked(True)
        option_row.addWidget(self.include_unreal_box)

        self.include_code_box = QCheckBox("Project code index")
        self.include_code_box.setChecked(True)
        option_row.addWidget(self.include_code_box)

        self.include_cpp_box = QCheckBox("C++ / wrapper feasibility")
        self.include_cpp_box.setChecked(True)
        option_row.addWidget(self.include_cpp_box)
        option_row.addStretch(1)

        self.build_context_button = QPushButton("Build Staged Context")
        self.build_context_button.clicked.connect(self.build_staged_context)
        option_row.addWidget(self.build_context_button)
        layout.addLayout(option_row)

        splitter = QSplitter(Qt.Vertical)

        prompt_widget = QWidget()
        prompt_layout = QVBoxLayout(prompt_widget)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(QLabel("User Prompt"))
        self.composer_prompt_edit = QPlainTextEdit()
        self.composer_prompt_edit.setPlaceholderText(
            "Describe the task. Then build staged context if needed. Nothing is sent until you choose Use in Chat Prompt or Send to Chat."
        )
        self.composer_prompt_edit.setMinimumHeight(180)
        prompt_layout.addWidget(self.composer_prompt_edit, 1)
        splitter.addWidget(prompt_widget)

        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Reviewable Prompt Preview"))
        preview_header.addStretch(1)
        self.clear_context_button = QPushButton("Clear Staged Context")
        self.clear_context_button.clicked.connect(self.clear_staged_context)
        preview_header.addWidget(self.clear_context_button)
        preview_layout.addLayout(preview_header)
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setPlaceholderText("Staged context preview appears here. You can edit it before sending.")
        self.preview_edit.setMinimumHeight(260)
        preview_layout.addWidget(self.preview_edit, 1)
        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.context_summary_label = QLabel("Staged context: none")
        self.context_summary_label.setWordWrap(True)
        layout.addWidget(self.context_summary_label)
        return tab

    # ------------------------------------------------------------- Utilities
    def _refresh_status(self, text: str) -> None:
        self.status_label.setText(text or "")

    def _project_root(self) -> str | None:
        window = self.window_ref
        if window is None:
            return None
        try:
            roots = window.project_roots() if hasattr(window, "project_roots") else []
            if roots:
                return str(roots[0])
        except Exception:
            pass
        root = getattr(window, "project_root", None)
        return str(root) if root else None

    def _input_widget(self):
        return getattr(self.window_ref, "input", None)

    def _load_current_prompt_from_main_window(self) -> None:
        widget = self._input_widget()
        text = ""
        try:
            if hasattr(widget, "text"):
                text = widget.text()
            elif hasattr(widget, "toPlainText"):
                text = widget.toPlainText()
        except Exception:
            text = ""
        if text:
            self.quick_prompt_edit.setPlainText(text)
            self.composer_prompt_edit.setPlainText(text)

    def _active_user_text(self) -> str:
        if self.mode_tabs.currentIndex() == 0:
            return self.quick_prompt_edit.toPlainText().strip()
        return self.composer_prompt_edit.toPlainText().strip()

    def _active_send_text(self) -> str:
        if self.mode_tabs.currentIndex() == 0:
            return self.quick_prompt_edit.toPlainText().strip()
        preview = self.preview_edit.toPlainText().strip()
        return preview or self.composer_prompt_edit.toPlainText().strip()

    def _set_main_window_prompt(self, text: str) -> bool:
        widget = self._input_widget()
        if widget is None:
            return False
        try:
            if hasattr(widget, "setPlainText"):
                widget.setPlainText(text)
            elif hasattr(widget, "setText"):
                # Existing main UI is still single-line. Keep it unchanged and compact text.
                widget.setText(" ".join((text or "").splitlines()))
            else:
                return False
            return True
        except Exception:
            return False

    # --------------------------------------------------------------- Actions
    def build_staged_context(self) -> None:
        user_text = self.composer_prompt_edit.toPlainText().strip()
        if not user_text:
            QMessageBox.information(self, "Prompt needed", "Add a prompt before building staged context.")
            return
        try:
            from services.prompt_dispatch_service import PromptStagingService

            service = PromptStagingService()
            draft = service.build_draft(
                user_text,
                project_root=self._project_root(),
                include_unreal=self.include_unreal_box.isChecked(),
                include_code=self.include_code_box.isChecked(),
                include_cpp_wrappers=self.include_cpp_box.isChecked(),
                max_items=8,
            )
            self.current_draft = draft
            self.preview_edit.setPlainText(draft.render_for_composer())
            self.context_summary_label.setText(draft.context_badge())
            self._refresh_status("Context staged")
        except Exception as exc:
            QMessageBox.warning(self, "Context staging failed", str(exc))
            self._refresh_status("Context staging failed")

    def clear_staged_context(self) -> None:
        self.current_draft = None
        self.preview_edit.clear()
        self.context_summary_label.setText("Staged context: none")
        self._refresh_status("Staged context cleared")

    def copy_preview_or_prompt(self) -> None:
        text = self._active_send_text()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._refresh_status("Copied")

    def use_in_chat_prompt(self) -> None:
        text = self._active_send_text()
        if not text:
            return
        if not self._set_main_window_prompt(text):
            QMessageBox.warning(self, "Unavailable", "Could not find the main chat prompt widget.")
            return
        label = getattr(self.window_ref, "prompt_context_label", None)
        if label is not None and self.current_draft is not None:
            try:
                label.setText(self.current_draft.context_badge())
            except Exception:
                pass
        self._refresh_status("Moved to chat prompt")

    def send_to_chat(self) -> None:
        text = self._active_send_text()
        if not text:
            return
        if not self._set_main_window_prompt(text):
            QMessageBox.warning(self, "Unavailable", "Could not find the main chat prompt widget.")
            return
        if hasattr(self.window_ref, "send_message"):
            self.window_ref.send_message()
            self._refresh_status("Sent")
            return
        QMessageBox.information(self, "Ready", "Prompt was moved to the chat box. Press Send in the main window.")
