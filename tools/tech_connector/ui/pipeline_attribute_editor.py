from __future__ import annotations
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from tech_connector.services.pipeline_context_value_service import selection_parameter_spec


_EMPTY_ARGUMENT_VALUES = (None, "", [], {})


def _display_literal_value(value) -> str:
    if isinstance(value, dict) and value.get("$pipeline_context") in {
        "dcc_export_scope_v1", "dcc_input_context_v1",
    }:
        return f"Automatic: {value.get('label') or value.get('scope') or value.get('context_kind') or 'host context'}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _source_label(source: str) -> str:
    return {
        "operation_default": "FUNCTION DEFAULT",
        "registered_function_default": "FUNCTION DEFAULT",
        "generated_pipeline_workspace": "GENERATED WORKSPACE",
        "current_content_browser_at_execution": "CURRENT CONTENT BROWSER",
        "upstream_result_reference": "UPSTREAM DATA",
        "upstream_data_binding": "UPSTREAM DATA",
        "upstream_literal_artifact": "UPSTREAM DATA",
        "user_prompt": "FROM PROMPT",
        "user_prompt_or_derived": "FROM PROMPT / CONTEXT",
        "user_setting": "USER SETTING",
        "required_user_input": "MISSING",
        "project_call_site": "OBSERVED PROJECT USAGE",
        "runtime_host_context": "AUTO FROM LIVE DCC CONTEXT",
        "user_edited": "USER VALUE",
    }.get(str(source or "").strip(), str(source or "planned value").replace("_", " ").upper())

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
    disconnectInputRequested = Signal(dict)
    contextValueRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_data = None
        self.param_widgets = {}
        self.context_buttons = {}
        self.param_status_labels = {}
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
        self.context_buttons.clear()
        self.param_status_labels.clear()
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
        provenance = step_data.get("literal_value_provenance") or {}
        value_details = step_data.get("literal_value_details") or {}
        connected_inputs = step_data.get("_connected_inputs") or {}
        connected_details = step_data.get("_connected_input_details") or {}
        if not params:
            self.form.addRow(QLabel("No editable inputs."), QLabel(""))
            return
        for param in params:
            name = param.get("name") or ""
            if not name:
                continue
            ann = param.get("annotation") or ""
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            value_row = QWidget(row)
            value_layout = QHBoxLayout(value_row)
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(4)
            edit = QLineEdit()
            edit.setObjectName(f"pipeline-argument-{name}")
            connection_source = str(connected_inputs.get(name) or "").strip()
            has_literal = name in literals
            literal_value = literals.get(name)
            detail = dict(value_details.get(name) or {})
            required = bool(param.get("required", detail.get("required", False)))
            missing = bool(detail.get("missing")) or (
                required and not connection_source and literal_value in _EMPTY_ARGUMENT_VALUES
            )
            source = str(detail.get("source") or provenance.get(name) or "planned_value")
            connection_detail = dict(connected_details.get(name) or {})
            if connection_source:
                edit.setText(f"Connected: {connection_source}")
                edit.setReadOnly(True)
                edit.setToolTip(
                    f"This input is driven by {connection_source}. "
                    "Right-click to unlock this input and disconnect the graph link."
                )
                edit.setContextMenuPolicy(Qt.CustomContextMenu)
                edit.customContextMenuRequested.connect(
                    lambda position, e=edit, n=name, source=connection_source:
                    self._show_connected_input_menu(e, n, source, position)
                )
            else:
                edit.setText(_display_literal_value(literal_value) if has_literal else "")
                if missing:
                    edit.setPlaceholderText(f"Required {ann or 'value'} — not supplied")
                elif has_literal and literal_value in _EMPTY_ARGUMENT_VALUES:
                    edit.setPlaceholderText("Optional — automatic/default behavior")
                else:
                    edit.setPlaceholderText(f"Enter {ann or 'value'}")
                edit.textChanged.connect(
                    lambda value, n=name, annotation=ann: self._set_literal(n, value, annotation)
                )
            value_layout.addWidget(edit, 1)
            self.param_widgets[name] = edit
            if is_file_path_arg(name, ann):
                file_btn = QPushButton("File")
                file_btn.clicked.connect(lambda _=False, n=name, e=edit: self._browse_file(n, e))
                file_btn.setEnabled(not connection_source)
                value_layout.addWidget(file_btn)
            elif is_folder_path_arg(name, ann):
                folder_btn = QPushButton("Folder")
                folder_btn.clicked.connect(lambda _=False, n=name, e=edit: self._browse_folder(n, e))
                folder_btn.setEnabled(not connection_source)
                value_layout.addWidget(folder_btn)
            layout.addWidget(value_row)

            status = QLabel()
            status.setObjectName(f"pipeline-argument-status-{name}")
            status.setWordWrap(True)
            status.setTextInteractionFlags(status.textInteractionFlags() | Qt.TextSelectableByMouse)
            if connection_source:
                source_type = str(connection_detail.get("source_type") or "Any")
                compatible = bool(connection_detail.get("compatible", True))
                status.setText(
                    f"{'CONNECTED DATA' if compatible else 'TYPE MISMATCH'} • "
                    f"{source_type} → {ann or 'Any'}\nSource: {connection_source}"
                )
                status.setToolTip(
                    f"This argument is populated at runtime from {connection_source}. "
                    f"The source provides {source_type}; the receiving function expects {ann or 'Any'}."
                )
                status.setStyleSheet(
                    "color: #69c7ff; font-size: 10px;"
                    if compatible
                    else "color: #ff9f1c; font-weight: bold; font-size: 10px;"
                )
                if not compatible:
                    edit.setStyleSheet("QLineEdit { border: 2px solid #ff9f1c; background: #1d1003; }")
            elif missing:
                question = str(detail.get("question") or "").strip()
                status.setText(
                    f"MISSING REQUIRED INPUT • expected {ann or 'Any'}"
                    + (f"\n{question}" if question else "")
                )
                status.setToolTip("This function cannot run reliably until this argument is supplied.")
                status.setStyleSheet("color: #ff9f1c; font-weight: bold; font-size: 10px;")
                edit.setStyleSheet("QLineEdit { border: 2px solid #ff9f1c; background: #1d1003; }")
            elif has_literal and literal_value in _EMPTY_ARGUMENT_VALUES:
                status.setText(f"{_source_label(source)} • optional {ann or 'Any'} • empty/automatic")
                status.setToolTip(
                    str(detail.get("resolution") or "The callable accepts this empty/default value; it is not a missing required argument.")
                )
                status.setStyleSheet("color: #b8a36a; font-size: 10px;")
            else:
                status.setText(f"{_source_label(source)} • {ann or 'Any'}")
                status.setToolTip(str(detail.get("resolution") or "This is the value that will be passed to the function."))
                status.setStyleSheet("color: #8fd3a8; font-size: 10px;")
            layout.addWidget(status)
            self.param_status_labels[name] = status

            selection_spec = selection_parameter_spec(symbol, name, ann)
            if selection_spec:
                auto_context = (
                    literal_value
                    if isinstance(literal_value, dict)
                    and literal_value.get("$pipeline_context") in {
                        "dcc_export_scope_v1", "dcc_input_context_v1",
                    }
                    else None
                )
                button_label = (
                    f"Override with {selection_spec['host_label']} Selection"
                    if auto_context
                    else selection_spec["label"]
                )
                selection_btn = QPushButton(button_label)
                selection_btn.setObjectName(f"pipeline-context-{name}")
                selection_btn.setEnabled(not connection_source)
                selection_btn.setProperty("connectionLocked", bool(connection_source))
                if auto_context:
                    selection_btn.setToolTip(
                        f"This input will automatically resolve {auto_context.get('label') or 'the export scope'} "
                        f"from the live {selection_spec['host_label']} scene when the pipeline runs. "
                        "Click to replace that behavior with the current selection. The scene is not modified."
                    )
                else:
                    selection_btn.setToolTip(
                        f"Read the current {selection_spec['host_label']} selection and use it for `{name}`. "
                        "The scene is not modified."
                    )
                selection_btn.clicked.connect(
                    lambda _=False, n=name, spec=dict(selection_spec):
                    self._request_context_value(n, spec)
                )
                layout.addWidget(selection_btn)
                self.context_buttons[name] = selection_btn
            label = QLabel(f"{name}: {ann or 'Any'}")
            label.setToolTip(ann)
            self.form.addRow(label, row)

    def _show_connected_input_menu(
        self,
        edit: QLineEdit,
        input_name: str,
        connection_source: str,
        position,
    ):
        menu = QMenu(edit)
        unlock_action = menu.addAction("Unlock Input (Disconnect Link)")
        unlock_action.setToolTip(f"Disconnect {connection_source} from {input_name}.")
        selected = menu.exec(edit.mapToGlobal(position))
        if selected == unlock_action and self.step_data:
            self.disconnectInputRequested.emit({
                "step_data": self.step_data,
                "input": input_name,
                "connection": connection_source,
            })

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

    def _set_literal(self, name, value, annotation=""):
        if not self.step_data:
            return
        typed_value = self._typed_value(value, annotation)
        self.step_data.setdefault("literal_values", {})[name] = typed_value
        self.step_data.setdefault("literal_value_provenance", {})[name] = "user_edited"
        param = next(
            (
                row
                for row in (self.step_data.get("params") or [])
                if str(row.get("name") or "") == name
            ),
            {},
        )
        missing = bool(param.get("required")) and typed_value in _EMPTY_ARGUMENT_VALUES
        detail = self.step_data.setdefault("literal_value_details", {}).setdefault(name, {})
        detail.update({"source": "user_edited", "missing": missing, "expected_type": annotation or "Any"})
        status = self.param_status_labels.get(name)
        edit = self.param_widgets.get(name)
        if status is not None:
            status.setText(
                f"MISSING REQUIRED INPUT • expected {annotation or 'Any'}"
                if missing
                else f"USER VALUE • {annotation or 'Any'}"
            )
            status.setStyleSheet(
                "color: #ff9f1c; font-weight: bold; font-size: 10px;"
                if missing
                else "color: #8fd3a8; font-size: 10px;"
            )
        if edit is not None:
            edit.setStyleSheet(
                "QLineEdit { border: 2px solid #ff9f1c; background: #1d1003; }"
                if missing
                else ""
            )
        self.literalChanged.emit({"step_data": self.step_data, "input": name, "value": typed_value})

    @staticmethod
    def _typed_value(value: str, annotation: str):
        expected = str(annotation or "").lower().replace(" ", "")
        text = str(value or "")
        if not text:
            return ""
        if "bool" in expected and text.lower() in {"true", "false"}:
            return text.lower() == "true"
        if expected in {"int", "integer"}:
            try:
                return int(text)
            except ValueError:
                return text
        if expected in {"float", "double"}:
            try:
                return float(text)
            except ValueError:
                return text
        if "list" in expected or "dict" in expected or "tuple" in expected:
            try:
                return json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                return text
        return text

    def _request_context_value(self, name: str, spec: dict):
        if not self.step_data:
            return
        self.contextValueRequested.emit({
            "step_data": self.step_data,
            "input": name,
            **dict(spec or {}),
        })

    def apply_context_value(self, name: str, value, *, source: str = "selection") -> None:
        """Apply a typed contextual value without converting lists/dicts to strings."""

        if not self.step_data or not name:
            return
        self.step_data.setdefault("literal_values", {})[name] = value
        self.step_data.setdefault("literal_value_provenance", {})[name] = source
        self.step_data.setdefault("literal_value_details", {}).setdefault(name, {}).update(
            {
                "source": source,
                "missing": False,
                "resolution": "Captured from the live host selection.",
            }
        )
        edit = self.param_widgets.get(name)
        if edit is not None:
            edit.blockSignals(True)
            edit.setText(_display_literal_value(value))
            edit.blockSignals(False)
            edit.setStyleSheet("")
        status = self.param_status_labels.get(name)
        if status is not None:
            status.setText(f"{_source_label(source)} • typed {type(value).__name__}")
            status.setToolTip("Read from the live host context and stored without string conversion.")
            status.setStyleSheet("color: #8fd3a8; font-size: 10px;")
        self.literalChanged.emit({
            "step_data": self.step_data,
            "input": name,
            "value": value,
            "source": source,
        })

    def set_context_busy(self, name: str, busy: bool) -> None:
        button = self.context_buttons.get(name)
        if button is None:
            return
        spec = selection_parameter_spec(
            (self.step_data or {}).get("symbol") or {},
            name,
            "",
        )
        button.setEnabled(not busy and not bool(button.property("connectionLocked")))
        button.setText("Reading Selection…" if busy else (spec or {}).get("label", "Use Selection"))

    def _browse_file(self, name, edit):
        current = str(edit.text() or "").strip()
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select file for {name}",
            current,
            "All Files (*.*)",
        )
        if path:
            edit.setText(path)

    def _browse_folder(self, name, edit):
        path = QFileDialog.getExistingDirectory(self, f"Select folder for {name}")
        if path:
            edit.setText(path)
