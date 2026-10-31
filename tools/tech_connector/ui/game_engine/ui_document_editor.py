"""Small visual authoring surface for preview-stage UI documents."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets.ui_document_asset_service import (
    layout_ui_document, validate_ui_document,
)


class _FittedGraphicsView(QGraphicsView):
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.scene() is not None and not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)


class UIDocumentEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values = {"canvas": {"size": [1920, 1080]}, "widgets": []}
        self._loading = False
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        for kind in ("panel", "text", "button", "image"):
            button = QPushButton(f"Add {kind.title()}", self)
            button.clicked.connect(lambda _checked=False, value=kind: self._add_widget(value))
            controls.addWidget(button)
        remove = QPushButton("Remove Selected", self)
        remove.clicked.connect(self._remove_selected)
        controls.addWidget(remove)
        self.viewport = QComboBox(self)
        self.viewport.addItem("Reference canvas", None)
        self.viewport.addItem("Desktop 1920 × 1080", (1920, 1080))
        self.viewport.addItem("Mobile 390 × 844", (390, 844))
        self.viewport.currentIndexChanged.connect(self._draw_preview)
        controls.addWidget(self.viewport)
        root.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal, self)
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.tree = QTreeWidget(left)
        self.tree.setHeaderLabels(["Widget", "Type"])
        self.tree.setAccessibleName("UI widget hierarchy")
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        left_layout.addWidget(self.tree, 1)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit | QDoubleSpinBox] = {}
        for key, label in (
            ("text", "Text"), ("accessible_name", "Accessible name"),
            ("on_activate", "Activation event"), ("image_asset_id", "Image asset ID"),
            ("font_asset_id", "Font asset ID"),
        ):
            field = QLineEdit(left)
            field.setAccessibleName(label)
            field.editingFinished.connect(self._fields_changed)
            self.fields[key] = field
            form.addRow(label, field)
        for key, label, maximum in (
            ("anchor_x", "Anchor X", 1), ("anchor_y", "Anchor Y", 1),
            ("pivot_x", "Pivot X", 1), ("pivot_y", "Pivot Y", 1),
            ("offset_x", "Offset X", 100000), ("offset_y", "Offset Y", 100000),
            ("width", "Width", 100000), ("height", "Height", 100000),
        ):
            field = QDoubleSpinBox(left)
            field.setDecimals(3)
            field.setRange(-100000 if key.startswith("offset") else 0, maximum)
            field.setAccessibleName(label)
            field.valueChanged.connect(self._fields_changed)
            self.fields[key] = field
            form.addRow(label, field)
        left_layout.addLayout(form)
        splitter.addWidget(left)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.preview = _FittedGraphicsView(right)
        self.preview.setAccessibleName("Responsive UI layout preview")
        self.scene = QGraphicsScene(self.preview)
        self.preview.setScene(self.scene)
        right_layout.addWidget(self.preview, 1)
        self.message = QLabel(right)
        self.message.setWordWrap(True)
        right_layout.addWidget(self.message)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)
        self.load_settings(self._values)

    def load_settings(self, values: dict) -> None:
        self._loading = True
        self._values = deepcopy(dict(values))
        self._values.setdefault("canvas", {"size": [1920, 1080]})
        self._values.setdefault("widgets", [])
        self._rebuild_tree()
        self._loading = False
        self._draw_preview()

    def settings(self) -> dict:
        return deepcopy(self._values)

    def validation_issues(self) -> list[str]:
        return [item.message for item in validate_ui_document(self._values) if item.severity == "error"]

    def _selected_id(self) -> str:
        item = self.tree.currentItem()
        return str(item.data(0, Qt.UserRole) or "") if item else ""

    def _selected_widget(self) -> dict | None:
        identifier = self._selected_id()
        return next((item for item in self._values["widgets"] if item.get("id") == identifier), None)

    def _rebuild_tree(self, selected_id: str = "") -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        items = {}
        invalid_hierarchy = any(issue.code in {"ui_parent", "ui_parent_type", "ui_cycle", "ui_duplicate_id"}
                                for issue in validate_ui_document(self._values))
        for widget in self._values.get("widgets", ()):
            identifier = str(widget.get("id") or "")
            item = QTreeWidgetItem([identifier, str(widget.get("type") or "")])
            item.setData(0, Qt.UserRole, identifier)
            items[identifier] = item
        for widget in self._values.get("widgets", ()):
            identifier = str(widget.get("id") or "")
            parent_id = str(widget.get("parent_id") or "")
            item = items[identifier]
            if not invalid_hierarchy and parent_id in items and parent_id != identifier:
                items[parent_id].addChild(item)
            else:
                self.tree.addTopLevelItem(item)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        selected = items.get(selected_id)
        if selected is not None:
            self.tree.setCurrentItem(selected)
        elif self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self._selection_changed()

    def _add_widget(self, kind: str) -> None:
        selected = self._selected_widget()
        parent_id = selected["id"] if selected and selected.get("type") == "panel" else str(selected.get("parent_id") or "") if selected else ""
        base = kind.title()
        names = {str(item.get("id")) for item in self._values["widgets"]}
        number = 1
        while f"{base}{number}" in names:
            number += 1
        identifier = f"{base}{number}"
        self._values["widgets"].append({
            "id": identifier, "type": kind, "parent_id": parent_id,
            "anchor": [0.5, 0.5], "pivot": [0.5, 0.5], "offset": [0, 0],
            "size": [240, 80] if kind == "panel" else [180, 48],
            "text": "Button" if kind == "button" else "Text" if kind == "text" else "",
            "accessible_name": "Button" if kind == "button" else "",
            "on_activate": "", "image_asset_id": "", "font_asset_id": "",
        })
        self._rebuild_tree(identifier)
        self._draw_preview()
        self.changed.emit()

    def _remove_selected(self) -> None:
        identifier = self._selected_id()
        if not identifier:
            return
        remove = {identifier}
        while True:
            children = {str(item.get("id")) for item in self._values["widgets"] if item.get("parent_id") in remove}
            if children.issubset(remove):
                break
            remove.update(children)
        self._values["widgets"] = [item for item in self._values["widgets"] if item.get("id") not in remove]
        self._rebuild_tree()
        self._draw_preview()
        self.changed.emit()

    def _selection_changed(self) -> None:
        widget = self._selected_widget()
        self._loading = True
        for key in ("text", "accessible_name", "on_activate", "image_asset_id", "font_asset_id"):
            self.fields[key].setText(str(widget.get(key) or "") if widget else "")
        values = {
            "anchor_x": ("anchor", 0), "anchor_y": ("anchor", 1),
            "pivot_x": ("pivot", 0), "pivot_y": ("pivot", 1),
            "offset_x": ("offset", 0), "offset_y": ("offset", 1),
            "width": ("size", 0), "height": ("size", 1),
        }
        for key, (source, index) in values.items():
            pair = widget.get(source) if widget else None
            self.fields[key].setValue(float(pair[index]) if isinstance(pair, (list, tuple)) and len(pair) == 2 else 0)
            self.fields[key].setEnabled(widget is not None)
        for key in ("text", "accessible_name", "on_activate", "image_asset_id", "font_asset_id"):
            self.fields[key].setEnabled(widget is not None)
        self._loading = False

    def _fields_changed(self, *_args) -> None:
        if self._loading:
            return
        widget = self._selected_widget()
        if widget is None:
            return
        for key in ("text", "accessible_name", "on_activate", "image_asset_id", "font_asset_id"):
            widget[key] = self.fields[key].text()
        for target, x, y in (
            ("anchor", "anchor_x", "anchor_y"), ("pivot", "pivot_x", "pivot_y"),
            ("offset", "offset_x", "offset_y"), ("size", "width", "height"),
        ):
            widget[target] = [self.fields[x].value(), self.fields[y].value()]
        self._draw_preview()
        self.changed.emit()

    def _draw_preview(self, *_args) -> None:
        self.scene.clear()
        problems = self.validation_issues()
        if problems:
            self.message.setText("Preview paused: " + "; ".join(problems[:3]))
            return
        layout = layout_ui_document(self._values, viewport=self.viewport.currentData())
        width, height = layout["viewport"]
        self.scene.setSceneRect(0, 0, width, height)
        self.scene.addRect(0, 0, width, height, QPen(QColor("#708396")), QBrush(QColor("#172635")))
        for widget in layout["widgets"]:
            x, y, w, h = widget["rect"]
            kind = widget["type"]
            fill = QColor("#334a63") if kind == "panel" else QColor("#506f93") if kind == "button" else QColor("#253548")
            self.scene.addRect(x, y, w, h, QPen(QColor("#9bb9d3")), QBrush(fill))
            label = self.scene.addText(widget["text"] or widget["id"])
            label.setDefaultTextColor(QColor("#eaf3ff"))
            label.setPos(x + 5, y + 3)
        self.preview.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.message.setText(f"{len(layout['widgets'])} widgets · layout preview only; player rendering is not qualified")


__all__ = ["UIDocumentEditorWidget"]
