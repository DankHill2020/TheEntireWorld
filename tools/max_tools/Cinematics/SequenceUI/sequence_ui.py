"""Qt Sequence Workspace hosted by 3ds Max."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from utilities.sequence_workspace import (
    apply_bulk_update, duplicate_entry, new_entry, normalize_document,
    sequence_preflight, validate_document,
)
from . import sequence_utils


def _max_parent():
    try:
        import qtmax
        return qtmax.GetQMaxMainWindow()
    except (ImportError, AttributeError, RuntimeError):
        return QtWidgets.QApplication.activeWindow()


class SequenceWorkspaceDialog(QtWidgets.QDialog):
    """A focused export workspace backed by scene-resident JSON."""

    def __init__(self, parent=None):
        super().__init__(parent or _max_parent())
        self.setWindowTitle("Sequence Workspace — 3ds Max")
        self.setObjectName("TechConnectorSequenceWorkspace")
        self.setMinimumSize(1050, 560)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinimizeButtonHint)
        self._document = sequence_utils.read_document()
        self._loading = False
        self._dirty = False
        self._undo_documents = []
        self._redo_documents = []
        self._history_snapshot = deepcopy(self._document)
        self._build_ui()
        self._load_document(self._document, reset_history=True)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("<b>Sequence Workspace</b>  ·  3ds Max")
        self.status = QtWidgets.QLabel("Ready")
        self.status.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status)
        root.addLayout(header)

        destination = QtWidgets.QHBoxLayout()
        destination.addWidget(QtWidgets.QLabel("Export root"))
        self.export_root = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse…")
        save = QtWidgets.QPushButton("Save Setup")
        destination.addWidget(self.export_root, 1)
        destination.addWidget(browse)
        destination.addWidget(save)
        root.addLayout(destination)
        self.engine_state = QtWidgets.QLabel(
            "Engine connection is optional. Enter a target skeleton manually now and resolve it when publishing."
        )
        self.engine_state.setStyleSheet("color:#9aa6ad;")
        root.addWidget(self.engine_state)

        tools = QtWidgets.QHBoxLayout()
        self.add_selected = QtWidgets.QPushButton("Add Selected")
        self.add_cameras = QtWidgets.QPushButton("Add Cameras")
        self.add_empty = QtWidgets.QPushButton("Add Entry")
        self.duplicate = QtWidgets.QPushButton("Duplicate")
        self.remove = QtWidgets.QPushButton("Remove")
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.redo_button = QtWidgets.QPushButton("Redo")
        for widget in (self.add_selected, self.add_cameras, self.add_empty, self.duplicate, self.remove,
                       self.undo_button, self.redo_button):
            tools.addWidget(widget)
        tools.addStretch(1)
        root.addLayout(tools)
        self.empty_state = QtWidgets.QLabel(
            "No entries yet. Add selected nodes, discover cameras, or create an empty entry."
        )
        self.empty_state.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_state.setStyleSheet("padding:14px; color:#9aa6ad; border:1px dashed #56616a;")
        root.addWidget(self.empty_state)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["On", "Animation", "In", "Out", "Source", "Export Directory"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)
        for column in (0, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        splitter.addWidget(self.table)

        inspector = QtWidgets.QWidget()
        inspector.setMinimumWidth(310)
        form = QtWidgets.QFormLayout(inspector)
        self.name = QtWidgets.QLineEdit()
        self.start = QtWidgets.QSpinBox(); self.start.setRange(-1_000_000, 1_000_000)
        self.end = QtWidgets.QSpinBox(); self.end.setRange(-1_000_000, 1_000_000)
        self.directory = QtWidgets.QLineEdit()
        self.namespace = QtWidgets.QLineEdit()
        self.skeleton = QtWidgets.QLineEdit()
        self.nodes = QtWidgets.QPlainTextEdit(); self.nodes.setMaximumHeight(70)
        self.shot = QtWidgets.QLineEdit()
        self.camera = QtWidgets.QLineEdit()
        self.enabled = QtWidgets.QCheckBox("Include in Export Enabled")
        self.set_range = QtWidgets.QPushButton("Set 3ds Max Range to Entry")
        self.bulk_apply = QtWidgets.QPushButton("Apply Target + Directory to Selection")
        form.addRow("Name", self.name)
        frames = QtWidgets.QHBoxLayout(); frames.addWidget(self.start); frames.addWidget(self.end)
        form.addRow("Frame range", frames)
        form.addRow("Directory", self.directory)
        form.addRow("Source rig / namespace", self.namespace)
        form.addRow("Target engine skeleton", self.skeleton)
        form.addRow("Nodes", self.nodes)
        form.addRow("Shot", self.shot)
        form.addRow("Camera", self.camera)
        form.addRow("", self.enabled)
        form.addRow("", self.set_range)
        form.addRow("", self.bulk_apply)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        splitter.addWidget(inspector)
        splitter.setSizes([730, 320])
        root.addWidget(splitter, 1)

        footer = QtWidgets.QHBoxLayout()
        self.validation = QtWidgets.QLabel()
        self.validation.setWordWrap(True)
        self.export_selected = QtWidgets.QPushButton("Export Selected")
        self.export_all = QtWidgets.QPushButton("Export Enabled")
        self.preflight_button = QtWidgets.QPushButton("Review Preflight")
        self.publish_button = QtWidgets.QPushButton("Publish to Engine")
        self.export_all.setDefault(True)
        footer.addWidget(self.validation, 1)
        footer.addWidget(self.preflight_button)
        footer.addWidget(self.export_selected)
        footer.addWidget(self.export_all)
        footer.addWidget(self.publish_button)
        root.addLayout(footer)

        browse.clicked.connect(self._browse)
        save.clicked.connect(self._save)
        self.add_selected.clicked.connect(self._add_from_selection)
        self.add_cameras.clicked.connect(self._add_from_cameras)
        self.add_empty.clicked.connect(self._add_blank)
        self.duplicate.clicked.connect(self._duplicate)
        self.remove.clicked.connect(self._remove)
        self.undo_button.clicked.connect(self._undo)
        self.redo_button.clicked.connect(self._redo)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._table_changed)
        self.export_root.textChanged.connect(self._root_changed)
        self.set_range.clicked.connect(self._set_scene_range)
        self.bulk_apply.clicked.connect(self._bulk_apply_selected)
        self.preflight_button.clicked.connect(self._show_preflight)
        self.export_selected.clicked.connect(lambda: self._export(True))
        self.export_all.clicked.connect(lambda: self._export(False))
        self.publish_button.clicked.connect(self._publish)
        for widget in (self.name, self.directory, self.namespace, self.skeleton, self.shot, self.camera):
            widget.textChanged.connect(self._inspector_changed)
        self.start.valueChanged.connect(self._inspector_changed)
        self.end.valueChanged.connect(self._inspector_changed)
        self.nodes.textChanged.connect(self._inspector_changed)
        self.enabled.toggled.connect(self._inspector_changed)

    def _load_document(self, value, *, reset_history=False):
        self._loading = True
        self._document = normalize_document(value, host="3dsmax", fps=sequence_utils.frames_per_second())
        self.export_root.setText(str(self._document.get("export_directory") or ""))
        self.table.setRowCount(0)
        for entry in self._document["entries"]:
            self._append_table_row(entry)
        self._loading = False
        if reset_history:
            self._undo_documents = []
            self._redo_documents = []
            self._history_snapshot = deepcopy(self._document)
        if self.table.rowCount():
            self.table.selectRow(0)
        else:
            self._clear_inspector()
        self._refresh_validation()

    def _append_table_row(self, entry):
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QtWidgets.QTableWidgetItem()
        enabled.setFlags(enabled.flags() | QtCore.Qt.ItemIsUserCheckable)
        enabled.setCheckState(QtCore.Qt.Checked if entry.get("enabled", True) else QtCore.Qt.Unchecked)
        enabled.setData(QtCore.Qt.UserRole, str(entry.get("id") or ""))
        self.table.setItem(row, 0, enabled)
        source = str(entry.get("shot") or entry.get("namespace") or entry.get("camera") or "Unbound")
        values = (entry.get("name") or "Animation", entry.get("start_frame", 0), entry.get("end_frame", 0), source,
                  entry.get("export_directory") or self.export_root.text())
        for column, value in enumerate(values, 1):
            self.table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))

    def _selected_rows(self):
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def _selected_index(self):
        rows = self._selected_rows()
        return rows[0] if rows else -1

    def _selection_changed(self):
        if self._loading:
            return
        index = self._selected_index()
        if not (0 <= index < len(self._document["entries"])):
            self._clear_inspector()
            return
        entry = self._document["entries"][index]
        self._loading = True
        self.name.setText(str(entry.get("name") or ""))
        self.start.setValue(int(entry.get("start_frame") or 0))
        self.end.setValue(int(entry.get("end_frame") or 0))
        self.directory.setText(str(entry.get("export_directory") or ""))
        self.namespace.setText(str(entry.get("namespace") or ""))
        self.skeleton.setText(str(entry.get("skeleton") or ""))
        self.nodes.setPlainText(", ".join(str(value) for value in entry.get("nodes") or ()))
        self.shot.setText(str(entry.get("shot") or ""))
        self.camera.setText(str(entry.get("camera") or ""))
        self.enabled.setChecked(bool(entry.get("enabled", True)))
        self._loading = False
        self._refresh_validation()

    def _clear_inspector(self):
        self._loading = True
        for widget in (self.name, self.directory, self.namespace, self.skeleton, self.shot, self.camera):
            widget.clear()
        self.nodes.clear(); self.start.setValue(0); self.end.setValue(0); self.enabled.setChecked(False)
        self._loading = False

    def _inspector_changed(self, *_args):
        if self._loading:
            return
        index = self._selected_index()
        if not (0 <= index < len(self._document["entries"])):
            return
        entry = self._document["entries"][index]
        entry.update({
            "name": self.name.text().strip() or "Animation",
            "start_frame": self.start.value(), "end_frame": self.end.value(),
            "export_directory": self.directory.text().strip().replace("\\", "/"),
            "namespace": self.namespace.text().strip(), "skeleton": self.skeleton.text().strip(),
            "nodes": [value.strip() for value in self.nodes.toPlainText().split(",") if value.strip()],
            "shot": self.shot.text().strip(), "camera": self.camera.text().strip(),
            "enabled": self.enabled.isChecked(),
        })
        self._loading = True
        self.table.item(index, 0).setCheckState(QtCore.Qt.Checked if entry["enabled"] else QtCore.Qt.Unchecked)
        self.table.item(index, 1).setText(entry["name"])
        self.table.item(index, 2).setText(str(entry["start_frame"]))
        self.table.item(index, 3).setText(str(entry["end_frame"]))
        self.table.item(index, 4).setText(entry["shot"] or entry["namespace"] or entry["camera"] or "Unbound")
        self.table.item(index, 5).setText(entry["export_directory"] or self.export_root.text())
        self._loading = False
        self._changed()

    def _table_changed(self, item):
        if self._loading or not (0 <= item.row() < len(self._document["entries"])):
            return
        entry = self._document["entries"][item.row()]
        try:
            if item.column() == 0: entry["enabled"] = item.checkState() == QtCore.Qt.Checked
            elif item.column() == 1: entry["name"] = item.text().strip() or "Animation"
            elif item.column() == 2: entry["start_frame"] = int(item.text())
            elif item.column() == 3: entry["end_frame"] = int(item.text())
            elif item.column() == 5: entry["export_directory"] = item.text().replace("\\", "/")
        except ValueError:
            self.status.setText("Frame values must be integers.")
        self._selection_changed()
        self._changed()

    def _root_changed(self, value):
        if self._loading:
            return
        self._document["export_directory"] = value.replace("\\", "/")
        self._changed()

    def _add_values(self, values):
        self._document["entries"].extend(deepcopy(list(values)))
        self._load_document(self._document)
        if self.table.rowCount():
            self.table.selectRow(self.table.rowCount() - 1)
        self._changed()

    def _add_from_selection(self):
        values = sequence_utils.entries_from_selection()
        if not values:
            QtWidgets.QMessageBox.information(self, "Sequence Workspace", "Select a rig, camera, or animated node first.")
            return
        self._add_values(values)

    def _add_from_cameras(self):
        self._add_values(sequence_utils.entries_from_cameras())

    def _add_blank(self):
        start, end = sequence_utils.display_range()
        self._add_values([new_entry("Animation", start, end, export_directory=self.export_root.text())])

    def _duplicate(self):
        index = self._selected_index()
        if 0 <= index < len(self._document["entries"]):
            self._add_values([duplicate_entry(self._document["entries"][index])])

    def _remove(self):
        rows = self._selected_rows()
        if not rows:
            return
        for index in reversed(rows):
            del self._document["entries"][index]
        self._load_document(self._document)
        self._changed()

    def _bulk_apply_selected(self):
        rows = self._selected_rows()
        if not rows:
            return
        identifiers = [self._document["entries"][index]["id"] for index in rows]
        self._document = apply_bulk_update(
            self._document, identifiers,
            skeleton=self.skeleton.text().strip(),
            export_directory=self.directory.text().strip() or self.export_root.text(),
        )
        self._load_document(self._document)
        selection = self.table.selectionModel()
        for row in rows:
            selection.select(
                self.table.model().index(row, 0),
                QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows,
            )
        self._changed()

    def _set_scene_range(self):
        index = self._selected_index()
        if 0 <= index < len(self._document["entries"]):
            entry = self._document["entries"][index]
            sequence_utils.set_display_range(entry["start_frame"], entry["end_frame"])
            self.status.setText(f"Scene range set to {entry['start_frame']}–{entry['end_frame']}")

    def _browse(self):
        value = QtWidgets.QFileDialog.getExistingDirectory(self, "Sequence Export Root", self.export_root.text())
        if value:
            self.export_root.setText(value.replace("\\", "/"))

    def _changed(self):
        current = deepcopy(self._document)
        if current != self._history_snapshot:
            self._undo_documents.append(deepcopy(self._history_snapshot))
            self._undo_documents = self._undo_documents[-100:]
            self._redo_documents = []
            self._history_snapshot = current
        self.status.setText("Unsaved changes")
        self._dirty = True
        self._refresh_validation()

    def _undo(self):
        if not self._undo_documents:
            return
        self._redo_documents.append(deepcopy(self._document))
        self._document = self._undo_documents.pop()
        self._history_snapshot = deepcopy(self._document)
        self._load_document(self._document)
        self.status.setText("Undo applied • unsaved changes")
        self._dirty = True

    def _redo(self):
        if not self._redo_documents:
            return
        self._undo_documents.append(deepcopy(self._document))
        self._document = self._redo_documents.pop()
        self._history_snapshot = deepcopy(self._document)
        self._load_document(self._document)
        self.status.setText("Redo applied • unsaved changes")
        self._dirty = True

    def _refresh_validation(self):
        preflight = sequence_preflight(self._document)
        issues = preflight["issues"]
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            self.validation.setText(f"{len(errors)} error(s): {errors[0]['message']}")
            self.validation.setStyleSheet("color:#ff8f8f;")
        elif issues:
            self.validation.setText(f"{len(issues)} warning(s): {issues[0]['message']}")
            self.validation.setStyleSheet("color:#e8c66a;")
        else:
            state = preflight["engine_status"].replace("_", " ").title()
            self.validation.setText(f"Local export ready • Engine: {state}")
            self.validation.setStyleSheet("color:#8fd6a3;")
        self.export_all.setEnabled(preflight["can_export"])
        self.export_selected.setEnabled(preflight["can_export"] and bool(self._selected_rows()))
        self.publish_button.setEnabled(preflight["can_publish"])
        blocker = preflight["publish_blockers"][0]["message"] if preflight["publish_blockers"] else "Ready to publish."
        self.publish_button.setToolTip(blocker)
        engine = self._document.get("engine") or {}
        state = str(engine.get("status") or "offline").replace("_", " ").title()
        project = str(engine.get("project") or "").strip()
        detail = str(engine.get("message") or "").strip()
        if preflight["engine_status"] == "connected":
            self.engine_state.setText(
                f"Engine: {state}{' • ' + project if project else ''}"
                f"{' — ' + detail if detail else ''}"
            )
            self.engine_state.setStyleSheet("color:#8fd6a3;")
        else:
            self.engine_state.setText(
                f"Engine: {state} — local authoring and FBX export remain available. "
                "Target skeletons may be entered manually."
            )
            self.engine_state.setStyleSheet("color:#e8c66a;")
        self.empty_state.setVisible(not bool(self._document["entries"]))
        self.undo_button.setEnabled(bool(self._undo_documents))
        self.redo_button.setEnabled(bool(self._redo_documents))

    def _show_preflight(self):
        report = sequence_preflight(self._document)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Sequence Preflight")
        dialog.resize(720, 430)
        root = QtWidgets.QVBoxLayout(dialog)
        summary = QtWidgets.QLabel(
            f"Engine: {report['engine_status'].replace('_', ' ').title()}   •   "
            f"Local export: {'Ready' if report['can_export'] else 'Blocked'}   •   "
            f"Publish: {'Ready' if report['can_publish'] else 'Blocked'}"
        )
        root.addWidget(summary)
        table = QtWidgets.QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Entry", "Target Skeleton", "Resolution", "Details"])
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        for entry in report["entries"]:
            row = table.rowCount(); table.insertRow(row)
            values = (entry["name"], entry["skeleton"] or "—",
                      entry["skeleton_resolution"].replace("_", " ").title(), entry["message"])
            for column, value in enumerate(values):
                table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
        root.addWidget(table, 1)
        if report["issues"]:
            root.addWidget(QtWidgets.QLabel(" • ".join(issue["message"] for issue in report["issues"][:4])))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject); buttons.clicked.connect(dialog.accept)
        root.addWidget(buttons)
        if hasattr(dialog, "exec"):
            dialog.exec()
        else:
            dialog.exec_()

    def _publish(self):
        report = sequence_preflight(self._document)
        if not report["can_publish"]:
            message = report["publish_blockers"][0]["message"] if report["publish_blockers"] else "Publish preflight failed."
            QtWidgets.QMessageBox.information(self, "Publish Unavailable", message)
            return
        try:
            result = sequence_utils.publish_document(self._document)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Publish Failed", str(exc))
            return
        if not result.get("ok", True):
            QtWidgets.QMessageBox.critical(self, "Publish Failed", str(result.get("error") or "Engine publish failed."))
            return
        self.status.setText(str(result.get("message") or "Published to connected engine"))

    def _save(self):
        self._document = sequence_utils.write_document(self._document)
        self.status.setText("Saved in 3ds Max scene")
        self._dirty = False
        self._refresh_validation()

    def _export(self, selected_only):
        issues = validate_document(self._document)
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            QtWidgets.QMessageBox.warning(self, "Cannot Export", errors[0]["message"])
            return
        rows = self._selected_rows() if selected_only else list(range(len(self._document["entries"])))
        exported = 0
        progress = QtWidgets.QProgressDialog("Exporting sequence entries…", "Cancel", 0, len(rows), self)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        for offset, index in enumerate(rows):
            if progress.wasCanceled():
                break
            entry = self._document["entries"][index]
            if not entry.get("enabled", True):
                continue
            progress.setLabelText(f"Exporting {entry['name']}…")
            QtWidgets.QApplication.processEvents()
            try:
                sequence_utils.export_entry(entry, default_directory=self.export_root.text())
                exported += 1
            except Exception as exc:
                progress.close()
                QtWidgets.QMessageBox.critical(self, "Export Failed", f"{entry['name']}:\n{exc}")
                return
            progress.setValue(offset + 1)
        progress.close()
        self._save()
        self.status.setText(f"Exported {exported} entr{'y' if exported == 1 else 'ies'}")

    def closeEvent(self, event):
        if self._dirty:
            self._save()
        super().closeEvent(event)


_DIALOG = None


def show_sequence_manager():
    global _DIALOG
    try:
        if _DIALOG is not None:
            _DIALOG.close()
            _DIALOG.deleteLater()
    except RuntimeError:
        pass
    _DIALOG = SequenceWorkspaceDialog()
    _DIALOG.show()
    _DIALOG.raise_()
    _DIALOG.activateWindow()
    return _DIALOG


if __name__ == "__main__":
    show_sequence_manager()
