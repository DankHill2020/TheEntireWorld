"""Reusable compact chat panel for Tech Connector."""

from __future__ import annotations

import html
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
CODE_FENCE_RE = re.compile(r"```([A-Za-z0-9_+.-]*)\n(.*?)\n```", re.DOTALL)


class ChatPanel(QWidget):
    """Prompt, thread, and attachment surface reusable by a main window."""

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
        self.context_label = QLabel("Context: Chat")
        set_ui_role(self.context_label, "context")
        root.addWidget(self.context_label)

        self.thread = QTextBrowser()
        self.thread.setOpenExternalLinks(False)
        self.thread.anchorClicked.connect(self._open_anchor)
        self.thread.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self.attachment_strip.hide()
        root.addWidget(self.attachment_strip)

        prompt_row = QHBoxLayout()
        self.prompt = QLineEdit()
        set_ui_role(self.prompt, "composer")
        self.prompt.setPlaceholderText("Ask anything...")
        self.prompt.returnPressed.connect(self._emit_send)
        prompt_row.addWidget(self.prompt, 1)
        attach = QPushButton("Attach")
        configure_button(attach, "paperclip", text="Attach", role="secondary")
        attach.setToolTip("Attach files")
        attach.clicked.connect(self.choose_files)
        prompt_row.addWidget(attach)
        image = QPushButton("Image")
        configure_button(image, "image", text="Image", role="secondary")
        image.setToolTip("Paste or attach an image")
        image.clicked.connect(self.paste_image_requested.emit)
        prompt_row.addWidget(image)
        send = QPushButton("Send")
        configure_button(send, "send", text="Send", role="primary")
        send.clicked.connect(self._emit_send)
        prompt_row.addWidget(send)
        root.addLayout(prompt_row)

    def append_message(self, role: str, text: str) -> None:
        role_text = html.escape(str(role or "Message"))
        source = str(text or "")
        chunks: list[str] = []
        position = 0
        for match in CODE_FENCE_RE.finditer(source):
            chunks.append(html.escape(source[position:match.start()]).replace("\n", "<br>"))
            language = html.escape(match.group(1) or "text")
            code = html.escape(match.group(2))
            chunks.append(f"<pre><code data-language='{language}'>{code}</code></pre>")
            position = match.end()
        chunks.append(html.escape(source[position:]).replace("\n", "<br>"))
        self.thread.append(f"<p><b>{role_text}</b><br>{''.join(chunks)}</p>")

    def set_context_text(self, text: str) -> None:
        self.context_label.setText(str(text or "Context: Chat"))

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Attach files", "", "All Files (*.*)")
        if paths:
            self.add_attachments(paths)
            self.files_attached.emit(paths)

    def add_attachments(self, paths: Iterable[str]) -> None:
        for raw in paths:
            path = str(Path(raw).resolve())
            if path in self.attached_files or path in self.attached_images:
                continue
            suffix = Path(path).suffix.lower()
            if suffix in IMAGE_EXTS:
                self.attached_images.append(path)
                self._add_image_chip(path)
            elif suffix in VIDEO_EXTS:
                self.attached_files.append(path)
                self._add_text_chip(path, "Video", "#1e9bff")
            else:
                self.attached_files.append(path)
                self._add_text_chip(path, "File", "#00b866")
        self.attachment_strip.setVisible(bool(self.attached_files or self.attached_images))

    def clear_attachments(self) -> None:
        self.attached_files.clear()
        self.attached_images.clear()
        while self.attachment_layout.count() > 1:
            item = self.attachment_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.attachment_strip.hide()

    def _add_text_chip(self, path: str, kind: str, color: str) -> None:
        label = QLabel(f"{kind}: {Path(path).name}")
        label.setToolTip(path)
        label.setStyleSheet(f"padding: 4px 8px; border: 1px solid {color};")
        self.attachment_layout.insertWidget(self.attachment_layout.count() - 1, label)

    def _add_image_chip(self, path: str) -> None:
        label = QLabel()
        pixmap = QPixmap(path)
        if pixmap.isNull():
            label.setText(f"Image: {Path(path).name}")
        else:
            label.setPixmap(pixmap.scaled(96, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label.setToolTip(path)
        self.attachment_layout.insertWidget(self.attachment_layout.count() - 1, label)

    def _append_directive_to_prompt(self, directive: str) -> None:
        current = self.prompt.text().strip()
        self.prompt.setText(f"{current} {directive}".strip())
        self.prompt.setFocus()

    def _tool_action(self, key: str) -> None:
        if key == "clear_attachments":
            self.clear_attachments()
        elif key == "insert_jira":
            self._append_directive_to_prompt("@jira ")
        elif key == "insert_confluence":
            self._append_directive_to_prompt("@confluence ")
        self.tool_action_requested.emit(str(key))

    def _emit_send(self) -> None:
        text = self.prompt.text().strip()
        if not text and not self.attached_files and not self.attached_images:
            return
        self.prompt.clear()
        self.send_requested.emit(text)

    def _open_anchor(self, url: QUrl) -> None:
        if url.isLocalFile() or url.scheme() in {"http", "https", "mailto"}:
            QDesktopServices.openUrl(url)


def file_anchor(path: str, label: str = "Open file") -> str:
    return f'<a href="file:///{quote(str(Path(path).resolve()).replace(chr(92), "/"))}">{html.escape(label)}</a>'


__all__ = ["ChatPanel", "IMAGE_EXTS", "VIDEO_EXTS", "file_anchor"]
