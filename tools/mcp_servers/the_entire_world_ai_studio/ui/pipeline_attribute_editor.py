from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

def is_file_path_arg(name: str, annotation: str = "") -> bool:
    text = f"{name} {annotation}".lower()
    return any(
        t in text
        for t in (
            "file_path",
            "filepath",
            "filename",
            "maya_file",
            "reference_paths",
            "asset_path",
            "source_path",
            "destination_path",
            "dest_path",
            "export_path",
        )
    ) or text.strip() in {"file", "path"}


def is_folder_path_arg(name: str, annotation: str = "") -> bool:
    text = f"{name} {annotation}".lower()
    return any(
        t in text
        for t in (
            "folder",
            "directory",
            "dir_path",
            "directory_path",
            "root_dir",
            "root_directory",
            "folder_path",
        )
    )

class PipelineAttributeEditor(QWidget):
    literalChanged = Signal(dict)
    openFileRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_data = None
        self.param_widgets = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Node Attributes")
        title.setStyleSheet("font-weight: bold; color: #d7ffe2;")
        root.addWidget(title)
        self.summary = QLabel("Select a node.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #b9dcff;")
        root.addWidget(self.summary)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.form = QFormLayout(self.content)
        self.form.setContentsMargins(4, 4, 4, 4)
        self.form.setSpacing(6)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

    def set_node(self, step_data):
        self.step_data = step_data
        self.param_widgets.clear()
        while self.form.rowCount():
            self.form.removeRow(0)
        if not step_data:
            self.summary.setText("Select a node.")
            return
        symbol = step_data.get("symbol") or {}
        self.summary.setText(f"{symbol.get('name', 'node')}\n{symbol.get('host', 'general')} • {symbol.get('kind', 'function')}")
        self._add_file_location(symbol)
        self._add_context_details(step_data)
        params = step_data.get("params") or symbol.get("params") or []
        literals = step_data.setdefault("literal_values", {})
        if not params:
            self.form.addRow(QLabel("No editable inputs."), QLabel(""))
            return
        for param in params:
            name = param.get("name") or ""
            if not name:
                continue
            ann = param.get("annotation") or ""
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0,0,0,0)
            layout.setSpacing(4)
            edit = QLineEdit()
            edit.setText(str(literals.get(name, "")))
            edit.setPlaceholderText(ann or "value")
            edit.textChanged.connect(lambda value, n=name: self._set_literal(n, value))
            layout.addWidget(edit, 1)
            self.param_widgets[name] = edit
            if is_file_path_arg(name, ann):
                file_btn = QPushButton("File")
                file_btn.clicked.connect(lambda _=False, n=name, e=edit: self._browse_file(n, e))
                layout.addWidget(file_btn)
            elif is_folder_path_arg(name, ann):
                folder_btn = QPushButton("Folder")
                folder_btn.clicked.connect(lambda _=False, n=name, e=edit: self._browse_folder(n, e))
                layout.addWidget(folder_btn)
            label = QLabel(f"{name}: {ann or 'Any'}")
            label.setToolTip(ann)
            self.form.addRow(label, row)

    def _add_file_location(self, symbol: dict):
        path = self._symbol_file_location(symbol)
        line = self._symbol_file_line(symbol)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setText(path or "Not available for this node")
        edit.setToolTip(path or "This node did not include indexed file metadata.")
        layout.addWidget(edit, 1)

        open_btn = QPushButton("Open File")
        open_btn.setEnabled(bool(path))
        if line > 1:
            open_btn.setToolTip(f"Open the Python file this node was imported from at line {line}.")
        else:
            open_btn.setToolTip("Open the Python file this node was imported from.")
        open_btn.clicked.connect(lambda _=False, p=path, ln=line: self._request_open_file(p, ln))
        layout.addWidget(open_btn)

        label = QLabel("File Location")
        label.setToolTip("Indexed source file for this pipeline node.")
        self.form.addRow(label, row)

    def _symbol_file_location(self, symbol: dict) -> str:
        for key in ("file_path", "source_path", "path", "module_path"):
            value = str((symbol or {}).get(key) or "").strip()
            if value:
                return str(Path(value))
        source = (symbol or {}).get("source") or {}
        if isinstance(source, dict):
            for key in ("file_path", "source_path", "path", "module_path"):
                value = str(source.get(key) or "").strip()
                if value:
                    return str(Path(value))
        return ""

    def _symbol_file_line(self, symbol: dict) -> int:
        for key in ("start_line", "line", "lineno", "line_number"):
            try:
                value = int((symbol or {}).get(key) or 0)
            except Exception:
                value = 0
            if value > 0:
                return value
        source = (symbol or {}).get("source") or {}
        if isinstance(source, dict):
            for key in ("start_line", "line", "lineno", "line_number"):
                try:
                    value = int(source.get(key) or 0)
                except Exception:
                    value = 0
                if value > 0:
                    return value
        return 1

    def _request_open_file(self, path: str, line: int = 1):
        if path:
            self.openFileRequested.emit({"path": path, "line": max(1, int(line or 1))})

    def _add_context_details(self, step_data):
        details = step_data.get("context_addition_details") or {}
        if not isinstance(details, dict) or not details:
            return
        heading = QLabel("Context Addition")
        heading.setStyleSheet("font-weight: bold; color: #d7ffe2; margin-top: 8px;")
        self.form.addRow(heading, QLabel(""))

        lines = []
        for label, key in (
            ("Mode", "mode"),
            ("Pattern", "pattern"),
            ("Summary", "summary"),
        ):
            value = details.get(key)
            if value:
                lines.append(f"{label}: {value}")
        if details.get("usage"):
            lines.extend(["", "How this is normally used:", str(details.get("usage"))])
        for label, key in (
            ("Reused existing nodes", "reused"),
            ("Added context nodes", "added"),
            ("Created connections", "connections"),
            ("Unresolved context", "missing"),
            ("Evidence", "evidence"),
        ):
            values = details.get(key) or []
            if values:
                lines.append("")
                lines.append(f"{label}:")
                lines.extend(f"- {value}" for value in values)
        body = QLabel("\n".join(lines).strip() or "Context details unavailable.")
        body.setWordWrap(True)
        body.setTextInteractionFlags(body.textInteractionFlags() | Qt.TextSelectableByMouse)
        body.setStyleSheet(
            "QLabel { color: #b9dcff; background: #000711; border: 1px solid #12324a; "
            "border-radius: 4px; padding: 6px; }"
        )
        self.form.addRow(body)

    def _set_literal(self, name, value):
        if not self.step_data:
            return
        self.step_data.setdefault("literal_values", {})[name] = value
        self.literalChanged.emit({"step_data": self.step_data, "input": name, "value": value})

    def _browse_file(self, name, edit):
        path, _ = QFileDialog.getOpenFileName(self, f"Select file for {name}")
        if path:
            edit.setText(path)

    def _browse_folder(self, name, edit):
        path = QFileDialog.getExistingDirectory(self, f"Select folder for {name}")
        if path:
            edit.setText(path)
