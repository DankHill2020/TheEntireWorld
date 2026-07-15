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

        self.tools_btn = QPushButton("⋯")
        self.tools_btn.setToolTip("More chat actions")
        self.tools_btn.setMaximumWidth(34)
        self.tools_btn.setMenu(self._build_tools_menu())
        prompt_row.addWidget(self.tools_btn)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._emit_send)
        prompt_row.addWidget(self.send_btn)

        root.addLayout(prompt_row)

        self.context_label = QLabel("Context: Chat • Project • Model")
        self.context_label.setObjectName("prompt_context_label")
        self.context_label.setStyleSheet("color: #8fd6a5; font-size: 11px;")
        root.addWidget(self.context_label)

    def _build_tools_menu(self) -> QMenu:
        menu = QMenu(self)
        for key, label in [
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

    def _tool_action(self, key: str) -> None:
        if key == "clear_attachments":
            self.clear_attachments()
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
            "All Files (*.*);;Code Files (*.py *.cpp *.h *.hpp *.cs *.json *.yaml *.yml *.md *.txt);;Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)",
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
            if Path(path).suffix.lower() in IMAGE_EXTS:
                self.attached_images.append(path)
                self._add_image_chip(path)
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

    def _add_image_chip(self, path: str) -> None:
        p = Path(path)
        label = QLabel()
        pix = QPixmap(str(p))
        if not pix.isNull():
            label.setPixmap(pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText(f"🖼 {html.escape(p.name)}")
        label.setToolTip(str(p))
        label.setStyleSheet("padding: 2px; border: 1px solid #00b866; border-radius: 4px;")
        self.attachment_layout.insertWidget(max(0, self.attachment_layout.count() - 1), label)

    def append_user_message(self, text: str, files: Iterable[str] = (), images: Iterable[str] = ()) -> None:
        body = html.escape(text or "")
        attachment_html = self._attachments_html(files, images)
        self.thread.append(f"<p><b style='color:#00b866'>YOU</b><br>{body}{attachment_html}</p>")
        self._scroll_bottom()

    def append_assistant_message(self, text: str) -> None:
        self.thread.append(f"<p><b style='color:#7ddc9d'>ASSISTANT</b></p>{self._render_markdownish(text)}")
        self._scroll_bottom()

    def append_status(self, text: str) -> None:
        self.thread.append(f"<p style='color:#8fd6a5'><i>{html.escape(text)}</i></p>")
        self._scroll_bottom()

    def _attachments_html(self, files: Iterable[str], images: Iterable[str]) -> str:
        parts = []
        for image in images:
            p = Path(image)
            parts.append(
                f"<br><img src='{QUrl.fromLocalFile(str(p)).toString()}' style='max-width:420px; max-height:260px; border:1px solid #00b866;'>"
            )
        for file in files:
            p = Path(file)
            mime = mimetypes.guess_type(str(p))[0] or "file"
            parts.append(f"<br><span style='color:#8fd6a5'>📄 {html.escape(p.name)} ({html.escape(mime)})</span>")
        return "".join(parts)

    def _render_markdownish(self, text: str) -> str:
        # Render fenced code blocks as complete chunks, not line-by-line fragments.
        text = text or ""
        html_parts = []
        pos = 0
        pattern = re_compile_code_fence()
        for match in pattern.finditer(text):
            before = text[pos:match.start()]
            if before:
                html_parts.append(f"<p>{html.escape(before).replace(chr(10), '<br>')}</p>")
            lang = html.escape(match.group(1) or "text")
            code = html.escape(match.group(2) or "")
            html_parts.append(
                "<div style='border:1px solid #00b866; background:#07110b; margin:8px 0;'>"
                f"<div style='padding:4px 8px; color:#8fd6a5;'>Code • {lang}</div>"
                f"<pre style='white-space:pre-wrap; margin:0; padding:8px;'>{code}</pre>"
                "</div>"
            )
            pos = match.end()
        rest = text[pos:]
        if rest:
            html_parts.append(f"<p>{html.escape(rest).replace(chr(10), '<br>')}</p>")
        return "".join(html_parts)

    def _open_anchor(self, url: QUrl) -> None:
        QDesktopServices.openUrl(url)

    def _scroll_bottom(self) -> None:
        bar = self.thread.verticalScrollBar()
        bar.setValue(bar.maximum())


def re_compile_code_fence():
    # Kept outside the class to avoid recompiling when rendering many chunks.
    import re
    return re.compile(r"```([A-Za-z0-9_+.-]*)\n(.*?)\n```", re.DOTALL)
