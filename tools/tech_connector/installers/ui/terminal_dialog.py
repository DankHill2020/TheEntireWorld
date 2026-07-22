from __future__ import annotations

"""Small terminal runner dialog for Tech Connector."""

from pathlib import Path

from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QPlainTextEdit, QVBoxLayout,
)

from tech_connector.services.terminal_service import TerminalCommand, TerminalWorker, looks_destructive


class TerminalDialog(QDialog):
    def __init__(self, parent=None, command: str = "", cwd: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Tech Connector Terminal")
        self.resize(980, 620)
        self.worker: TerminalWorker | None = None
        self._worker_history: list[TerminalWorker] = []
        self.cwd = cwd or str(Path.cwd())
        self.setStyleSheet("""
            QDialog { background:#050805; color:#d7dde5; }
            QLabel { color:#d7dde5; }
            QLineEdit { background:#020402; color:#d7dde5; border:1px solid #1f6f45; padding:5px; }
            QPushButton { background:#071107; color:#ffffff; border:1px solid #00c46a; border-radius:4px; padding:6px 10px; }
            QPushButton:disabled { color:#667066; border-color:#21452f; }
        """)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Command:"))
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("Enter a shell / PowerShell command...")
        self.command_edit.setText(command or "")
        self.command_edit.returnPressed.connect(self.run_command)
        top.addWidget(self.command_edit, 1)
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.run_command)
        top.addWidget(self.run_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_command)
        self.cancel_btn.setEnabled(False)
        top.addWidget(self.cancel_btn)
        root.addLayout(top)
        cwd_row = QHBoxLayout()
        cwd_row.addWidget(QLabel("Working directory:"))
        self.cwd_edit = QLineEdit(self.cwd)
        cwd_row.addWidget(self.cwd_edit, 1)
        root.addLayout(cwd_row)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.output.setStyleSheet(
            "QPlainTextEdit { background:#020402; color:#d7dde5; border:1px solid #1f6f45; "
            "font-family: Consolas, monospace; font-size: 10pt; }"
        )
        root.addWidget(self.output, 1)
        buttons = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Output")
        self.copy_btn.clicked.connect(self.copy_output)
        buttons.addWidget(self.copy_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.output.clear)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def append_output(self, text: str):
        if not text:
            return
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)
        self.output.ensureCursorVisible()

    def run_command(self):
        command = self.command_edit.text().strip()
        if not command:
            return
        if looks_destructive(command):
            result = QMessageBox.question(
                self, "Confirm terminal command",
                "This command looks potentially destructive. Run it anyway?\n\n" + command,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Command running", "A terminal command is already running.")
            return
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.append_output("\n")
        self.worker = TerminalWorker(TerminalCommand(command=command, cwd=self.cwd_edit.text().strip()))
        self._worker_history.append(self.worker)
        self.worker.output.connect(self.append_output)
        self.worker.finished_with_result.connect(self._finished)
        self.worker.start()

    def cancel_command(self):
        if self.worker:
            self.worker.cancel()

    def _finished(self, ok: bool, exit_code: int, status: str):
        self.append_output(f"\n[terminal:{status}] exit={exit_code}\n")
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._worker_history = self._worker_history[-5:]

    def copy_output(self):
        QGuiApplication.clipboard().setText(self.output.toPlainText())
