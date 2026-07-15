from __future__ import annotations

"""Interactive terminal dialog backed by a persistent shell session."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from services.terminal_session import TerminalSession, TerminalSessionConfig


class InteractiveTerminalDialog(QDialog):
    def __init__(self, parent=None, cwd: str = "", shell: str = "powershell"):
        super().__init__(parent)
        self.setWindowTitle("Tech Connector Terminal")
        self.resize(1040, 680)
        self.history: list[str] = []
        self.history_index = -1

        self.setStyleSheet(
            """
            QDialog { background:#050805; color:#d7dde5; }
            QLabel { color:#d7dde5; }
            QLineEdit, QComboBox {
                background:#020402; color:#d7dde5;
                border:1px solid #1f6f45; padding:5px;
            }
            QPushButton {
                background:#071107; color:#ffffff;
                border:1px solid #00c46a; border-radius:4px; padding:6px 10px;
            }
            QPlainTextEdit {
                background:#020402; color:#d7dde5; border:1px solid #1f6f45;
                font-family: Consolas, monospace; font-size: 10pt;
            }
            """
        )

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Shell:"))
        self.shell_box = QComboBox()
        self.shell_box.addItems(["powershell", "pwsh", "cmd"])
        idx = self.shell_box.findText(shell)
        if idx >= 0:
            self.shell_box.setCurrentIndex(idx)
        top.addWidget(self.shell_box)

        top.addWidget(QLabel("Working directory:"))
        self.cwd_edit = QLineEdit(cwd or str(Path.cwd()))
        top.addWidget(self.cwd_edit, 1)

        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self.restart_session)
        top.addWidget(self.restart_btn)

        self.interrupt_btn = QPushButton("Ctrl+C")
        self.interrupt_btn.clicked.connect(self.interrupt)
        top.addWidget(self.interrupt_btn)
        root.addLayout(top)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        root.addWidget(self.output, 1)

        bottom = QHBoxLayout()
        self.prompt_label = QLabel(">")
        bottom.addWidget(self.prompt_label)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type PowerShell commands here and press Enter...")
        self.input.returnPressed.connect(self.submit_command)
        self.input.installEventFilter(self)
        bottom.addWidget(self.input, 1)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.submit_command)
        bottom.addWidget(send_btn)
        root.addLayout(bottom)

        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Output")
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.output.toPlainText()))
        buttons.addWidget(self.copy_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.output.clear)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self.session = TerminalSession(
            TerminalSessionConfig(
                cwd=self.cwd_edit.text().strip(),
                shell=self.shell_box.currentText(),
            ),
            self,
        )
        self.session.output.connect(self.append_output)
        self.session.started.connect(lambda: self.input.setFocus())
        self.session.start()

    def append_output(self, text: str):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text or "")
        self.output.moveCursor(QTextCursor.End)
        self.output.ensureCursorVisible()

    def submit_command(self):
        command = self.input.text()
        if not command.strip():
            self.session.send("")
            return
        self.history.append(command)
        self.history_index = len(self.history)
        self.session.send(command)
        self.input.clear()

    def stage_command(self, command: str):
        self.input.setText(command or "")
        self.input.setFocus()
        self.input.selectAll()

    def send_command(self, command: str):
        self.stage_command(command)
        self.submit_command()

    def restart_session(self):
        self.session.close()
        self.output.appendPlainText("\n[restarting terminal]\n")
        self.session = TerminalSession(
            TerminalSessionConfig(
                cwd=self.cwd_edit.text().strip(),
                shell=self.shell_box.currentText(),
            ),
            self,
        )
        self.session.output.connect(self.append_output)
        self.session.start()

    def interrupt(self):
        self.session.interrupt()

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Up and self.history:
                self.history_index = max(0, self.history_index - 1)
                self.input.setText(self.history[self.history_index])
                return True
            if event.key() == Qt.Key_Down and self.history:
                self.history_index = min(len(self.history), self.history_index + 1)
                if self.history_index >= len(self.history):
                    self.input.clear()
                else:
                    self.input.setText(self.history[self.history_index])
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        # Keep shell state while hidden. User can Restart/close app to terminate it.
        self.hide()
        event.ignore()
