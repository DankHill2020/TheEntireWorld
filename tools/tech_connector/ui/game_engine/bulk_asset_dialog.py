"""Dry-run-first bulk operation dialog for the Content Browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import BULK_ASSET_OPERATIONS, BulkAssetOperationService


class BulkAssetOperationsDialog(QDialog):
    completed = Signal(object)

    def __init__(self, service: BulkAssetOperationService, asset_ids: list[str], parent=None) -> None:
        super().__init__(parent)
        self.service = service; self.asset_ids = list(dict.fromkeys(asset_ids))
        self.plan = None; self.receipt = None
        self.setWindowTitle(f"Bulk Asset Operations - {len(self.asset_ids)} selected")
        self.resize(900, 600)
        root = QVBoxLayout(self)
        header = QHBoxLayout(); header.addWidget(QLabel("Operation", self))
        self.operation = QComboBox(self)
        for action in BULK_ASSET_OPERATIONS: self.operation.addItem(action.replace("_", " ").title(), action)
        header.addWidget(self.operation); header.addStretch(1)
        self.summary = QLabel("Preview the operation before executing it.", self); header.addWidget(self.summary)
        root.addLayout(header)

        self.pages = QStackedWidget(self); root.addWidget(self.pages)
        self.rename_template = QLineEdit("{prefix}{name}{suffix}", self)
        self.rename_prefix = QLineEdit(self); self.rename_suffix = QLineEdit(self)
        self.rename_find = QLineEdit(self); self.rename_replace = QLineEdit(self)
        self.pages.addWidget(self._page([
            ("Name template", self.rename_template), ("Prefix", self.rename_prefix), ("Suffix", self.rename_suffix),
            ("Find", self.rename_find), ("Replace", self.rename_replace),
        ], "Tokens: {name}, {index}, {type}, {prefix}, and {suffix}."))
        self.move_folder = QLineEdit("Assets", self)
        self.pages.addWidget(self._page([("Destination folder", self.move_folder)], "Project-relative folders are safest."))
        self.add_tags = QLineEdit(self); self.remove_tags = QLineEdit(self)
        self.pages.addWidget(self._page([("Add tags", self.add_tags), ("Remove tags", self.remove_tags)], "Use comma-separated tags."))
        self.pages.addWidget(self._page([], "Reimports every selected asset from its recorded source. Missing sources are shown below."))
        self.pages.addWidget(self._page([], "Validates source files, metadata identity, dependencies, and type-specific rules."))
        self.cook_platform = QComboBox(self); self.cook_platform.addItems(["windows", "linux", "macos", "web", "mobile"])
        self.cook_quality = QComboBox(self); self.cook_quality.addItems(["high", "medium", "low"])
        self.pages.addWidget(self._page([("Platform", self.cook_platform), ("Quality", self.cook_quality)], "Cooking includes the dependency closure."))
        self.export_target = QComboBox(self); self.export_target.addItems(["generic", "unreal", "unity", "blender", "maya", "houdini"])
        self.export_destination = QLineEdit("Exports/Bulk", self)
        self.export_dependencies = QCheckBox("Include dependencies", self); self.export_dependencies.setChecked(True)
        self.pages.addWidget(self._page([
            ("Target", self.export_target), ("Destination", self.export_destination), ("", self.export_dependencies),
        ], "Exports a conversion report and dependency-aware manifest."))

        self.preview = QTableWidget(0, 6, self)
        self.preview.setAccessibleName("Bulk operation dry-run preview")
        self.preview.setHorizontalHeaderLabels(["Asset", "Type", "Source", "Destination", "Status", "Details"])
        self.preview.horizontalHeader().setStretchLastSection(True); root.addWidget(self.preview, 1)
        buttons = QHBoxLayout(); self.preview_button = QPushButton("Refresh Dry Run", self)
        self.execute_button = QPushButton("Execute Plan", self); self.execute_button.setEnabled(False)
        close = QPushButton("Close", self)
        buttons.addWidget(self.preview_button); buttons.addStretch(1); buttons.addWidget(self.execute_button); buttons.addWidget(close)
        root.addLayout(buttons)
        self.operation.currentIndexChanged.connect(self._operation_changed)
        self.preview_button.clicked.connect(self.refresh_plan); self.execute_button.clicked.connect(self.execute_plan); close.clicked.connect(self.reject)
        self._operation_changed(); self.refresh_plan()

    def _page(self, rows: list[tuple[str, QWidget]], help_text: str) -> QWidget:
        page = QWidget(self); layout = QFormLayout(page)
        for label, widget in rows: layout.addRow(label, widget)
        hint = QLabel(help_text, page); hint.setWordWrap(True); hint.setStyleSheet("color:#8ca2b2;")
        layout.addRow(hint); return page

    def _operation_changed(self, *_args) -> None:
        self.pages.setCurrentIndex(max(0, self.operation.currentIndex()))
        self.plan = None; self.execute_button.setEnabled(False)

    def options(self) -> dict[str, Any]:
        action = str(self.operation.currentData())
        if action == "rename":
            return {"template": self.rename_template.text(), "prefix": self.rename_prefix.text(),
                    "suffix": self.rename_suffix.text(), "find": self.rename_find.text(),
                    "replace": self.rename_replace.text(), "start_index": 1, "digits": 3}
        if action == "move": return {"destination_folder": self.move_folder.text().strip() or "Assets"}
        if action == "tag": return {"add_tags": self.add_tags.text(), "remove_tags": self.remove_tags.text()}
        if action == "cook": return {"platform": self.cook_platform.currentText(), "quality": self.cook_quality.currentText()}
        if action == "export":
            destination = Path(self.export_destination.text().strip() or "Exports/Bulk")
            if not destination.is_absolute(): destination = self.service.project_root / destination
            return {"target": self.export_target.currentText(), "destination": str(destination),
                    "include_dependencies": self.export_dependencies.isChecked()}
        return {}

    def refresh_plan(self) -> None:
        try:
            self.plan = self.service.plan(str(self.operation.currentData()), self.asset_ids, options=self.options())
        except Exception as exc:
            self.plan = None; self.preview.setRowCount(0); self.execute_button.setEnabled(False)
            self.summary.setText(str(exc)); return
        self.preview.setRowCount(0)
        for item in self.plan.items:
            row = self.preview.rowCount(); self.preview.insertRow(row)
            values = (Path(item.source_path).name or item.asset_id, item.type_id, item.source_path,
                      item.destination_path, item.status.upper(), item.message)
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value)); cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.preview.setItem(row, column, cell)
        self.summary.setText(f"{self.plan.ready_count} ready, {self.plan.blocked_count} blocked")
        self.execute_button.setEnabled(self.plan.executable)

    def execute_plan(self) -> None:
        self.refresh_plan()
        if self.plan is None or not self.plan.executable: return
        try:
            self.receipt = self.service.execute(self.plan)
        except Exception as exc:
            QMessageBox.warning(self, "Bulk operation failed", str(exc)); return
        self.completed.emit(self.receipt); self.accept()


__all__ = ["BulkAssetOperationsDialog"]
