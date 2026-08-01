"""Reusable chat panel for Tech Connector.

Provides a compact prompt row, action buttons, and rich thread rendering for
text, code blocks, images, and attached files. Designed to be embedded by
MainWindow rather than owning routing logic.
"""

from __future__ import annotations

import html
import mimetypes
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


class ChatPanel(QWidget):
    """Compact chat panel with rich message/attachment rendering.

    Signals:
        send_requested(str): emitted when the user presses Send/Enter.
        paste_image_requested(): let MainWindow provide clipboard image handling.
        files_attached(list[str]): emitted after file picker selection.
        tool_action_requested(str): emitted for compact tool/action buttons.
    """

    send_requested = Signal(str)
    paste_image_requested = Signal()
    files_attached = Signal(list)
    tool_action_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.attached_files: list[str] = []
        self.attached_images: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.thread = QTextBrowser()
        self.thread.setOpenExternalLinks(False)
        self.thread.anchorClicked.connect(self._open_anchor)
        self.thread.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.thread.setStyleSheet(
            "QTextBrowser {"
            " background-color:#080b10;"
            " color:#ecfff3;"
            " border:1px solid #12324a;"
            " border-radius:6px;"
            " selection-background-color:#5bd000;"
            " selection-color:#041105;"
            "}"
        )
        root.addWidget(self.thread, 1)

        self.attachment_strip = QScrollArea()
        self.attachment_strip.setWidgetResizable(True)
        self.attachment_strip.setFrameShape(QFrame.NoFrame)
        self.attachment_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attachment_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_strip.setMaximumHeight(84)
        self.attachment_container = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_container)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_layout.setSpacing(6)
        self.attachment_layout.addStretch(1)
        self.attachment_strip.setWidget(self.attachment_container)
        self.attachment_strip.setVisible(False)
        root.addWidget(self.attachment_strip)

        prompt_row = QHBoxLayout()
        prompt_row.setContentsMargins(0, 0, 0, 0)
        prompt_row.setSpacing(6)

        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText(
            "Ask anything. I’ll infer chat vs current file vs selection vs project search vs pipeline."
        )
        self.prompt.returnPressed.connect(self._emit_send)
        prompt_row.addWidget(self.prompt, 1)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setToolTip("Attach files to this request")
        self.attach_btn.setMaximumWidth(34)
        self.attach_btn.clicked.connect(self.choose_files)
        prompt_row.addWidget(self.attach_btn)

        self.image_btn = QPushButton("🖼")
        self.image_btn.setToolTip("Paste or attach an image")
        self.image_btn.setMaximumWidth(34)
        self.image_btn.clicked.connect(self.paste_image_requested.emit)
        prompt_row.addWidget(self.image_btn)

        # Quick Helper Buttons for Connected Services (+JIRA, +Confluence, +Slack, +Discord, +Tutorial)
        helper_buttons = [
            ("+JIRA", "@jira ", "Add a Jira directive to the prompt"),
            ("+Confluence", "@confluence ", "Add a Confluence directive to the prompt"),
            ("+Slack", "@slack ", "Add a Slack directive to the prompt"),
            ("+Discord", "@discord ", "Add a Discord directive to the prompt"),
            ("+Tutorial", "/tutorial ", "Ask for a learn-by-doing walkthrough instead of auto execution"),
        ]
        for service_label, directive, tooltip in helper_buttons:
            btn = QPushButton(service_label)
            btn.setToolTip(tooltip)
            btn.setStyleSheet("background-color: #1a2634; color: #5bd000; font-weight: bold; border: 1px solid #12324a; border-radius: 4px; padding: 4px 8px;")
            btn.clicked.connect(lambda _chk=False, d=directive: self._append_directive_to_prompt(d))
            prompt_row.addWidget(btn)

        self.tools_btn = QPushButton("⋯")
        self.tools_btn.setToolTip("More chat actions")
        self.tools_btn.setMaximumWidth(34)
        self.tools_btn.setMenu(self._build_tools_menu())
        prompt_row.addWidget(self.tools_btn)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._emit_send)
        prompt_row.addWidget(self.send_btn)

        root.addLayout(prompt_row)

        self.context_label = QLabel("Context: Chat • Project • Model | Mode: 🤖 Auto")
        self.context_label.setObjectName("prompt_context_label")
        self.context_label.setStyleSheet("color: #8fd6a5; font-size: 11px;")
        root.addWidget(self.context_label)

    def _build_tools_menu(self) -> QMenu:
        menu = QMenu(self)
        for key, label in [
            ("toggle_tutorial_mode", "🎓 Toggle Tutorial Walkthrough Mode"),
            ("insert_jira", "+JIRA (@jira)"),
            ("insert_confluence", "+Confluence (@confluence)"),
            ("open_jira_creator", "📋 Create Jira Task Details..."),
            ("open_jira_viewer", "🔍 Inspect / Edit Jira Issues..."),
            ("open_confluence_viewer", "📚 Confluence Doc Viewer & Editor..."),
            ("copy_last_prompt", "Copy Last Prompt"),
            ("copy_last_response", "Copy Last Response"),
            ("copy_full_log", "Copy Full Log"),
            ("health_check", "Health Check"),
            ("save_pipeline", "Save Response as Pipeline"),
            ("clear_attachments", "Clear Attachments"),
        ]:
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, k=key: self._tool_action(k))
        return menu

    def _append_directive_to_prompt(self, directive: str) -> None:
        current = self.prompt.text()
        if not current.strip():
            self.prompt.setText(directive)
        else:
            self.prompt.setText(f"{current.rstrip()} {directive}")
        self.prompt.setFocus()

    def _tool_action(self, key: str) -> None:
        if key == "toggle_tutorial_mode":
            from tech_connector.services.tutorial_mode_service import tutorial_service
            new_mode = "automation" if tutorial_service.is_tutorial_mode() else "interactive_guide"
            tutorial_service.set_mode(new_mode)
            mode_label = "🎓 Tutorial Walkthrough" if new_mode == "interactive_guide" else "🤖 Auto"
            self.context_label.setText(f"Context: Chat • Project • Model | Mode: {mode_label}")
        elif key == "clear_attachments":
            self.clear_attachments()
        elif key == "insert_jira":
            self._append_directive_to_prompt("@jira ")
        elif key == "insert_confluence":
            self._append_directive_to_prompt("@confluence ")
        elif key == "open_jira_creator":
            from tech_connector.ui.jira_task_dialog import JiraTaskCreatorDialog
            dialog = JiraTaskCreatorDialog(self)
            dialog.exec_()
        elif key == "open_jira_viewer":
            from tech_connector.ui.jira_task_dialog import JiraTaskViewerDialog
            dialog = JiraTaskViewerDialog(self)
            dialog.exec_()
        elif key == "open_confluence_viewer":
            from tech_connector.ui.confluence_doc_dialog import ConfluenceDocViewerDialog
            dialog = ConfluenceDocViewerDialog(self)
            dialog.exec_()
        self.tool_action_requested.emit(key)

    def _emit_send(self) -> None:
        text = self.prompt.text().strip()
        if not text and not self.attached_files and not self.attached_images:
            return
        self.prompt.clear()
        self.send_requested.emit(text)

    def set_context_text(self, text: str) -> None:
        self.context_label.setText(text or "Context: Chat")

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files",
            "",
            "All Files (*.*);;Code Files (*.py *.cpp *.h *.hpp *.cs *.json *.yaml *.yml *.md *.txt);;Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;Videos (*.mp4 *.mov *.avi *.mkv *.webm *.m4v)",
        )
        if not paths:
            return
        self.add_attachments(paths)
        self.files_attached.emit(paths)

    def add_attachments(self, paths: Iterable[str]) -> None:
        for raw in paths:
            path = str(Path(raw))
            if path in self.attached_files or path in self.attached_images:
                continue
            suffix = Path(path).suffix.lower()
            if suffix in IMAGE_EXTS:
                self.attached_images.append(path)
                self._add_image_chip(path)
            elif suffix in VIDEO_EXTS:
                self.attached_files.append(path)
                self._add_video_chip(path)
            else:
                self.attached_files.append(path)
                self._add_file_chip(path)
        self.attachment_strip.setVisible(bool(self.attached_files or self.attached_images))

    def clear_attachments(self) -> None:
        self.attached_files.clear()
        self.attached_images.clear()
        while self.attachment_layout.count() > 1:
            item = self.attachment_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.attachment_strip.setVisible(False)

    def _add_file_chip(self, path: str) -> None:
        p = Path(path)
        label = QLabel(f"📄 {html.escape(p.name)}")
        label.setToolTip(str(p))
        label.setStyleSheet("padding: 4px 8px; border: 1px solid #00b866; border-radius: 4px;")
        self.attachment_layout.insertWidget(max(0, self.attachment_layout.count() - 1), label)

    def _add_video_chip(self, path: str) -> None:
        p = Path(path)
        label = QLabel(f"Video {html.escape(p.name)}")
        label.setToolTip(str(p))
        label.setStyleSheet("padding: 4px 8px; border: 1px solid #1e9bff; border-radius: 4px; color:#b9dcff;")
        self.attachment_layout.insertWidget(max(0, self.attachment_layout.count() - 1), label)

    def _add_image_chip(self, path: str) -> None:
        p = Path(path)
        label = QLabel()
        pix = QPixmap(str(p))
        if not pix.isNull():

def re_compile_code_fence():
    # Kept outside the class to avoid recompiling when rendering many chunks.
    import re
    return re.compile(r"```([A-Za-z0-9_+.-]*)\n(.*?)\n```", re.DOTALL)
