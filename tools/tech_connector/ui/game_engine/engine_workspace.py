"""Dockable game-engine workspace built around the authoritative Garden viewport."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QByteArray, QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QPlainTextEdit, QPushButton, QToolBar, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import AssetDatabase, AssetTypeRegistry, PrefabService, builtin_asset_type_registry
from tech_connector.game_engine.assets.sequence_asset_service import SequenceAssetService
from tech_connector.game_engine.runtime.level_sequence_runtime_service import LevelSequenceRuntimeDirector, SequenceRuntimeCommand
from tech_connector.ui.game_engine.asset_browser import AssetBrowserWidget, TC_ASSET_MIME_TYPE
from tech_connector.ui.game_engine.asset_picker import AssetPickerDialog
from tech_connector.ui.game_engine.asset_insights import AssetAuditDashboard, AssetDependencyExplorer
from tech_connector.ui.game_engine.editor_state import EngineEditorState
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.sequence_editor import SequenceEditorWidget
from tech_connector.ui.game_engine.production_tools import BuildDeployPanel, EngineConsolePanel, LaunchReadinessPanel, RuntimeProfilerPanel
from tech_connector.ui.game_engine.recovery_center import EngineRecoveryCenter
from tech_connector.ui.game_engine.task_center import EngineTaskCenter
from tech_connector.ui.game_engine.world_production_panel import WorldProductionPanel


PLACEABLE_TYPES = frozenset({
    "tc.static_mesh", "tc.skeletal_mesh", "tc.prefab", "tc.effect_system",
    "tc.simulation_profile", "tc.audio_clip", "tc.sound_cue", "tc.behavior",
    "tc.gameplay_graph", "tc.light", "tc.camera",
})

ASSET_REFERENCE_TYPES = {
    "mesh_asset_id": ("tc.static_mesh", "tc.skeletal_mesh"),
    "skeleton_asset_id": ("tc.skeleton",),
    "audio_asset_id": ("tc.audio_clip", "tc.sound_cue"),
    "behavior_asset_id": ("tc.behavior", "tc.gameplay_graph"),
    "material_asset_id": ("tc.material", "tc.material_instance"),
}


class _AssetReferencePropertyTree(QTreeWidget):
    """Accept compatible Content Browser assets directly on reference rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.setAcceptDrops(True); self.setDragDropMode(QAbstractItemView.DropOnly)

    @staticmethod
    def accepts_asset_payload(item: QTreeWidgetItem | None, payload: dict[str, Any]) -> bool:
        if item is None: return False
        key = str(item.data(0, Qt.UserRole) or ""); allowed = ASSET_REFERENCE_TYPES.get(key, ())
        return bool(allowed and str(payload.get("type_id") or "") in allowed and str(payload.get("asset_id") or ""))

    @classmethod
    def apply_asset_payload(cls, item: QTreeWidgetItem | None, payload: dict[str, Any]) -> bool:
        if not cls.accepts_asset_payload(item, payload): return False
        item.setText(1, str(payload["asset_id"])); return True

    @staticmethod
    def _payload(event) -> dict[str, Any]:
        if not event.mimeData().hasFormat(TC_ASSET_MIME_TYPE): return {}
        try: return dict(json.loads(bytes(event.mimeData().data(TC_ASSET_MIME_TYPE)).decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError): return {}

    def dragEnterEvent(self, event) -> None:
        event.acceptProposedAction() if self._payload(event) else event.ignore()

    def dragMoveEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        event.acceptProposedAction() if self.accepts_asset_payload(item, self._payload(event)) else event.ignore()

    def dropEvent(self, event) -> None:
        if self.apply_asset_payload(self.itemAt(event.position().toPoint()), self._payload(event)): event.acceptProposedAction()
        else: event.ignore()


class EngineCommandPalette(QDialog):
    """Keyboard-first search over the editor's existing menu actions."""

    commandTriggered = Signal(str)

    def __init__(self, action_provider: Callable[[], list[tuple[str, str, QAction]]], parent=None) -> None:
        super().__init__(parent)
        self._action_provider = action_provider
        self._visible_actions: list[QAction] = []
        self.setWindowTitle("Engine Commands")
        self.setModal(False)
        self.resize(620, 430)
        root = QVBoxLayout(self)
        title = QLabel("Find a command", self)
        title.setStyleSheet("font-size:16px; font-weight:700;")
        root.addWidget(title)
        self.search_edit = QLineEdit(self)
        self.search_edit.setAccessibleName("Search engine commands")
        self.search_edit.setPlaceholderText("Type an action, tool, window, or shortcut…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._reload)
        self.search_edit.returnPressed.connect(self.activate_current)
        root.addWidget(self.search_edit)
        self.command_list = QListWidget(self)
        self.command_list.setAccessibleName("Matching engine commands")
        self.command_list.itemActivated.connect(lambda _item: self.activate_current())
        root.addWidget(self.command_list, 1)
        self.hint_label = QLabel("Enter runs the selected command  •  Esc closes", self)
        self.hint_label.setStyleSheet("color:#8299aa;")
        root.addWidget(self.hint_label)

    def show_palette(self) -> None:
        self.search_edit.clear()
        self._reload("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_edit.setFocus(Qt.ShortcutFocusReason)

    def _reload(self, query: str) -> None:
        words = tuple(part.casefold() for part in str(query).split() if part)
        matches: list[tuple[int, str, str, QAction]] = []
        for category, label, action in self._action_provider():
            try:
                shortcut = action.shortcut().toString(QKeySequence.NativeText)
            except RuntimeError:
                continue
            haystack = f"{label} {category} {shortcut}".casefold()
            if not all(word in haystack for word in words):
                continue
            folded = label.casefold()
            score = 0 if not words else min(
                0 if folded.startswith(word) else 1 if word in folded else 2 for word in words
            )
            matches.append((score, label.casefold(), category, action))
        matches.sort(key=lambda row: (row[0], row[1], row[2].casefold()))
        self.command_list.clear()
        self._visible_actions = []
        for _score, _sort_label, category, action in matches:
            try:
                shortcut = action.shortcut().toString(QKeySequence.NativeText)
                action_label = action.text().replace("&", "")
            except RuntimeError:
                continue
            suffix = f"    {shortcut}" if shortcut else ""
            item = QListWidgetItem(f"{action_label}{suffix}")
            item.setToolTip(category)
            item.setData(Qt.AccessibleDescriptionRole, f"{category}. {shortcut}".strip(". "))
            self.command_list.addItem(item)
            self._visible_actions.append(action)
        if self.command_list.count():
            self.command_list.setCurrentRow(0)
            self.hint_label.setText(f"{self.command_list.count()} commands  •  Enter runs the selected command")
        else:
            self.hint_label.setText("No matching commands — try a tool, window, asset, or play mode")

    def activate_current(self) -> bool:
        row = self.command_list.currentRow()
        if row < 0 or row >= len(self._visible_actions):
            return False
        action = self._visible_actions[row]
        if not action.isEnabled():
            return False
        label = action.text().replace("&", "")
        self.accept()
        action.trigger()
        self.commandTriggered.emit(label)
        return True


class WorldSettingsPanel(QWidget):
    changed = Signal()

    def __init__(self, project_root: str | Path | None = None, database: AssetDatabase | None = None, parent=None) -> None:
        super().__init__(parent); self.project_root = Path(project_root).resolve() if project_root else Path.cwd(); self.database = database; root = QVBoxLayout(self); form = QFormLayout()
        self.gravity_x = self._number(-100000, 100000, 0); self.gravity_y = self._number(-100000, 100000, -980); self.gravity_z = self._number(-100000, 100000, 0)
        gravity = QHBoxLayout(); gravity.addWidget(self.gravity_x); gravity.addWidget(self.gravity_y); gravity.addWidget(self.gravity_z)
        self.skybox = QLineEdit(self); self.game_ruleset = QLineEdit(self); self.time_of_day = self._number(0, 24, 12); self.exposure = self._number(-20, 20, 0)
        self.navigation = QCheckBox("Build and use navigation", self); self.navigation.setChecked(True)
        self.streaming = QComboBox(self); self.streaming.addItems(["world_partition", "sublevels", "disabled"])
        form.addRow("Gravity XYZ", gravity); form.addRow("Skybox / Environment", self._asset_reference_row(self.skybox, ("tc.texture",), "Choose Environment Texture")); form.addRow("Default Game Ruleset", self._asset_reference_row(self.game_ruleset, ("tc.game_ruleset",), "Choose Game Ruleset")); form.addRow("Time of Day", self.time_of_day); form.addRow("Exposure", self.exposure); form.addRow("Level Streaming", self.streaming); form.addRow("Navigation", self.navigation)
        root.addLayout(form); root.addStretch(1)
        for widget in (self.gravity_x, self.gravity_y, self.gravity_z, self.time_of_day, self.exposure): widget.valueChanged.connect(self.changed)
        self.skybox.textChanged.connect(self.changed); self.game_ruleset.textChanged.connect(self.changed); self.navigation.toggled.connect(self.changed); self.streaming.currentTextChanged.connect(self.changed)

    @staticmethod
    def _number(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox(); widget.setRange(minimum, maximum); widget.setDecimals(3); widget.setValue(value); return widget

    def _asset_reference_row(self, line_edit: QLineEdit, allowed_types: tuple[str, ...], title: str) -> QWidget:
        host = QWidget(self); layout = QHBoxLayout(host); layout.setContentsMargins(0, 0, 0, 0); layout.addWidget(line_edit, 1)
        choose = QPushButton("Choose…", host); choose.setAccessibleName(title); choose.clicked.connect(lambda: self._pick_asset_reference(line_edit, allowed_types, title)); layout.addWidget(choose)
        locate = QPushButton("Clear", host); locate.clicked.connect(line_edit.clear); layout.addWidget(locate)
        return host

    def _pick_asset_reference(self, line_edit: QLineEdit, allowed_types: tuple[str, ...], title: str) -> bool:
        if self.database is None:
            return False
        workspace = self.window(); browser = getattr(workspace, "asset_browser", None); editor_state = getattr(workspace, "editor_state", None)
        picker = AssetPickerDialog(
            self.project_root, self.database, allowed_types=allowed_types,
            current_asset_id=line_edit.text().strip(),
            recent_asset_ids=editor_state.recent_assets if editor_state is not None else (),
            context_asset_id=browser._selected_asset_id() if browser is not None else "",
            title=title, parent=self,
        )
        if hasattr(workspace, "locate_asset"): picker.locateRequested.connect(workspace.locate_asset)
        if hasattr(workspace, "open_asset_id"): picker.inspectRequested.connect(workspace.open_asset_id)
        if picker.exec() != QDialog.Accepted:
            return False
        line_edit.setText(picker.selected_asset_id)
        return True

    def load_settings(self, values: dict[str, Any] | None) -> None:
        data = dict(values or {}); gravity = list(data.get("gravity") or [0.0, -980.0, 0.0]); widgets = (self.gravity_x, self.gravity_y, self.gravity_z)
        for widget in (*widgets, self.time_of_day, self.exposure): widget.blockSignals(True)
        self.skybox.blockSignals(True); self.game_ruleset.blockSignals(True); self.navigation.blockSignals(True); self.streaming.blockSignals(True)
        for widget, value in zip(widgets, gravity): widget.setValue(float(value))
        self.skybox.setText(str(data.get("skybox_asset_id") or "")); self.game_ruleset.setText(str(data.get("game_ruleset_asset_id") or "")); self.time_of_day.setValue(float(data.get("time_of_day", 12.0))); self.exposure.setValue(float(data.get("exposure", 0.0))); self.navigation.setChecked(bool(data.get("navigation_enabled", True))); self.streaming.setCurrentText(str(data.get("streaming_mode") or "world_partition"))
        for widget in (*widgets, self.time_of_day, self.exposure): widget.blockSignals(False)
        self.skybox.blockSignals(False); self.game_ruleset.blockSignals(False); self.navigation.blockSignals(False); self.streaming.blockSignals(False)

    def settings(self) -> dict[str, Any]:
        return {"gravity": [self.gravity_x.value(), self.gravity_y.value(), self.gravity_z.value()], "skybox_asset_id": self.skybox.text().strip(), "game_ruleset_asset_id": self.game_ruleset.text().strip(), "time_of_day": self.time_of_day.value(), "exposure": self.exposure.value(), "navigation_enabled": self.navigation.isChecked(), "streaming_mode": self.streaming.currentText()}


class ActorDetailsPanel(QWidget):
    """Engine actor inspector with numeric transforms and an editable component stack."""

    def __init__(self, viewport: QWidget, parent=None) -> None:
        super().__init__(parent); self.viewport = viewport; self._loading = False; self._mixed_fields: set[str] = set(); self._inspector_rows: dict[str, tuple[QWidget, QWidget, bool, QToolButton]] = {}; self._favorite_fields = set(getattr(viewport, "_tc_inspector_favorites", set()))
        root = QVBoxLayout(self); self.title = QLabel("No actor selected", self); self.title.setStyleSheet("font-weight:600; font-size:14px"); root.addWidget(self.title)
        filters = QHBoxLayout(); self.property_search = QLineEdit(self); self.property_search.setPlaceholderText("Search actor properties…"); self.property_search.setClearButtonEnabled(True); self.property_search.setAccessibleName("Search actor properties"); self.property_search.textChanged.connect(self._filter_actor_fields); filters.addWidget(self.property_search, 1); self.show_advanced = QCheckBox("Advanced", self); self.show_advanced.toggled.connect(self._filter_actor_fields); filters.addWidget(self.show_advanced); self.favorites_only = QCheckBox("Favorites", self); self.favorites_only.toggled.connect(self._filter_actor_fields); filters.addWidget(self.favorites_only); root.addLayout(filters)
        form = QFormLayout(); self.name = QLineEdit(self); self._add_actor_field(form, "name", "Name", self.name)
        self.position = self._vector_row((0.0, 0.0, 0.0)); self._add_actor_field(form, "location", "Location", self.position[0])
        self.rotation = self._vector_row((0.0, 0.0, 0.0)); self._add_actor_field(form, "rotation", "Rotation", self.rotation[0])
        self.scale = self._vector_row((1.0, 1.0, 1.0)); self._add_actor_field(form, "scale", "Scale", self.scale[0])
        self.mobility = QComboBox(self); self.mobility.addItems(["Static", "Stationary", "Movable"]); self.mobility.setCurrentText("Movable"); self._add_actor_field(form, "mobility", "Mobility", self.mobility, advanced=True)
        self.visible = QCheckBox("Visible", self); self.visible.setChecked(True); self._add_actor_field(form, "rendering", "Rendering", self.visible)
        self.tags = QLineEdit(self); self.tags.setPlaceholderText("gameplay, interactable, enemy"); self._add_actor_field(form, "tags", "Tags", self.tags, advanced=True); root.addLayout(form)
        self.mobility.currentTextChanged.connect(lambda: self._shared_field_edited("mobility")); self.visible.stateChanged.connect(lambda: self._shared_field_edited("visible")); self.tags.textEdited.connect(lambda: self._shared_field_edited("tags"))
        self.no_property_matches = QLabel("No actor properties match this filter.", self); self.no_property_matches.hide(); root.addWidget(self.no_property_matches); self._filter_actor_fields()
        self.apply_button = QPushButton("Apply Actor Changes", self); self.apply_button.clicked.connect(self.apply); root.addWidget(self.apply_button)
        root.addWidget(QLabel("Components", self)); self.components = QTreeWidget(self); self.components.setHeaderLabels(["Component", "State"]); root.addWidget(self.components, 1)
        controls = QHBoxLayout(); self.add_component = QToolButton(self); self.add_component.setText("+ Add Component"); self.add_component.setPopupMode(QToolButton.InstantPopup); self.add_component.setMenu(self._component_menu()); controls.addWidget(self.add_component)
        move_up = QPushButton("↑", self); move_up.setToolTip("Move component up"); move_up.clicked.connect(lambda: self.move_selected_component(-1)); controls.addWidget(move_up)
        move_down = QPushButton("↓", self); move_down.setToolTip("Move component down"); move_down.clicked.connect(lambda: self.move_selected_component(1)); controls.addWidget(move_down)
        remove = QPushButton("Remove", self); remove.clicked.connect(self.remove_selected_component); controls.addWidget(remove); copy_component = QPushButton("Copy", self); copy_component.setToolTip("Copy the selected component and all of its properties"); copy_component.clicked.connect(self.copy_selected_component); controls.addWidget(copy_component); paste_component = QPushButton("Paste", self); paste_component.setToolTip("Paste compatible component properties onto the selected component"); paste_component.clicked.connect(self.paste_selected_component); controls.addWidget(paste_component); root.addLayout(controls)
        self.component_properties = _AssetReferencePropertyTree(self); self.component_properties.setHeaderLabels(["Component Property", "Value"]); self.component_properties.setRootIsDecorated(False); self.component_properties.setContextMenuPolicy(Qt.CustomContextMenu); self.component_properties.customContextMenuRequested.connect(self._show_component_property_menu); root.addWidget(self.component_properties)
        self.components.itemSelectionChanged.connect(self._load_component_properties)
        self.component_properties.itemDoubleClicked.connect(self._component_property_double_clicked)
        save_component = QPushButton("Apply Component Changes", self); save_component.clicked.connect(self.save_component_properties); root.addWidget(save_component)
        prefab_row = QHBoxLayout(); self.apply_prefab = QPushButton("Apply", self); self.apply_prefab.setToolTip("Apply all instance overrides back to the Prefab asset"); self.revert_prefab = QPushButton("Revert", self); self.revert_prefab.setToolTip("Revert all instance overrides to inherited values"); self.compare_prefab = QPushButton("Compare", self); self.compare_prefab.setToolTip("Compare this instance with its Prefab source"); self.unpack_prefab = QPushButton("Unpack", self); self.unpack_prefab.setToolTip("Break the Prefab link and create editable level actors"); prefab_row.addWidget(self.apply_prefab); prefab_row.addWidget(self.revert_prefab); prefab_row.addWidget(self.compare_prefab); prefab_row.addWidget(self.unpack_prefab); root.addLayout(prefab_row)
        self.prefab_overrides = QTreeWidget(self); self.prefab_overrides.setHeaderLabels(["Property", "Inherited", "Instance", "State"]); self.prefab_overrides.setRootIsDecorated(False); self.prefab_overrides.setAlternatingRowColors(True); root.addWidget(self.prefab_overrides)
        override_row = QHBoxLayout(); add_override = QPushButton("+ Override", self); add_override.clicked.connect(self.add_prefab_override); remove_override = QPushButton("Revert Selected", self); remove_override.clicked.connect(self.remove_prefab_override); override_row.addWidget(add_override); override_row.addWidget(remove_override); root.addLayout(override_row); self.add_override_button = add_override; self.remove_override_button = remove_override
        self.refresh()

    def _add_actor_field(self, form: QFormLayout, key: str, label: str, field: QWidget, *, advanced: bool = False) -> None:
        label_host = QWidget(self); layout = QHBoxLayout(label_host); layout.setContentsMargins(0, 0, 0, 0); favorite = QToolButton(label_host); favorite.setCheckable(True); favorite.setChecked(key in self._favorite_fields); favorite.setText("★" if favorite.isChecked() else "☆"); favorite.setToolTip(f"Favorite {label}"); favorite.toggled.connect(lambda checked, value=key, button=favorite: self._toggle_field_favorite(value, button, checked)); layout.addWidget(favorite); layout.addWidget(QLabel(label, label_host)); form.addRow(label_host, field); self._inspector_rows[key] = (label_host, field, bool(advanced), favorite)

    def _toggle_field_favorite(self, key: str, button: QToolButton, checked: bool) -> None:
        if checked: self._favorite_fields.add(key)
        else: self._favorite_fields.discard(key)
        button.setText("★" if checked else "☆"); self.viewport._tc_inspector_favorites = set(self._favorite_fields); self._filter_actor_fields()

    def _filter_actor_fields(self, _value=None) -> int:
        query = self.property_search.text().strip().casefold() if hasattr(self, "property_search") else ""; visible = 0
        for key, (label, field, advanced, _favorite) in self._inspector_rows.items():
            show = (not query or query in key.casefold()) and (not advanced or self.show_advanced.isChecked() or bool(query)) and (not self.favorites_only.isChecked() or key in self._favorite_fields)
            label.setVisible(show); field.setVisible(show); visible += int(show)
        if hasattr(self, "no_property_matches"): self.no_property_matches.setVisible(visible == 0)
        return visible

    def _shared_field_edited(self, key: str) -> None:
        if not self._loading: self._mixed_fields.discard(str(key))

    def _vector_row(self, values: tuple[float, float, float]) -> tuple[QWidget, list[QDoubleSpinBox]]:
        host = QWidget(self); layout = QHBoxLayout(host); layout.setContentsMargins(0, 0, 0, 0); widgets = []
        for axis, value in zip("XYZ", values):
            spin = QDoubleSpinBox(host); spin.setPrefix(axis + " "); spin.setRange(-10000000.0, 10000000.0); spin.setDecimals(3); spin.setValue(value); layout.addWidget(spin); widgets.append(spin)
        return host, widgets

    def _component_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, value in (("Static Mesh Renderer", "static_mesh"), ("Skeletal Mesh Renderer", "skeletal_mesh"), ("Camera", "camera"), ("Light", "light"), ("Collider", "collider"), ("Rigid Body", "rigid_body"), ("Audio Source", "audio_source"), ("Behavior / Script", "behavior")):
            menu.addAction(label, lambda _checked=False, kind=value: self.add_component_type(kind))
        return menu

    def _entity(self) -> dict[str, Any] | None:
        finder = getattr(self.viewport, "_runtime_entity_for_proxy", None)
        return finder(getattr(self.viewport, "_selected_scene_proxy", None)) if callable(finder) else None

    def refresh(self) -> None:
        entity = self._entity(); self._loading = True
        selection_provider = getattr(self.viewport, "selected_level_actor_proxies", None)
        proxies = list(selection_provider()) if callable(selection_provider) else []
        selection_count = len(proxies) if proxies else (1 if entity else 0)
        finder = getattr(self.viewport, "_runtime_entity_for_proxy", None)
        selected_entities = [value for value in (finder(proxy) for proxy in proxies) if isinstance(value, dict)] if callable(finder) else ([entity] if entity else [])
        single_editable = entity is not None and selection_count <= 1 and not bool(entity.get("editor_locked", False))
        bulk_editable = entity is not None and selection_count > 1
        title = str(entity.get("name") or "Actor") if entity else "Linked DCC object — source-owned"
        if selection_count > 1: title = f"{selection_count} actors selected · Primary: {title}"
        if entity and entity.get("editor_locked"): title += " · Locked"
        self.title.setText(title)
        self.name.setText(str(entity.get("name") or "") if entity else "")
        transform = dict(entity.get("transform") or {}) if entity else {}
        for controls, key, default in ((self.position[1], "position", (0.0, 0.0, 0.0)), (self.rotation[1], "rotation", (0.0, 0.0, 0.0)), (self.scale[1], "scale", (1.0, 1.0, 1.0))):
            values = list(transform.get(key) or default)
            for index, control in enumerate(controls): control.setValue(float(values[index] if index < len(values) else default[index]))
        self._mixed_fields.clear()
        mobility_values = {str(value.get("mobility") or "movable").title() for value in selected_entities}; visibility_values = {bool(value.get("visible", True)) for value in selected_entities}; tag_values = {tuple(value.get("tags") or ()) for value in selected_entities}
        mixed_label = "— Multiple Values —"
        if len(mobility_values) > 1:
            if self.mobility.findText(mixed_label) < 0: self.mobility.insertItem(0, mixed_label)
            self.mobility.setCurrentText(mixed_label); self._mixed_fields.add("mobility")
        else: self.mobility.setCurrentText(next(iter(mobility_values), "Movable"))
        self.visible.setTristate(len(visibility_values) > 1)
        if len(visibility_values) > 1: self.visible.setCheckState(Qt.PartiallyChecked); self._mixed_fields.add("visible")
        else: self.visible.setChecked(next(iter(visibility_values), False))
        if len(tag_values) > 1: self.tags.clear(); self.tags.setPlaceholderText("Multiple Values"); self._mixed_fields.add("tags")
        else: self.tags.setText(", ".join(next(iter(tag_values), ()))); self.tags.setPlaceholderText("gameplay, interactable, enemy")
        self.components.clear()
        for component in (entity.get("components") or []) if entity else ():
            item = QTreeWidgetItem([str(component.get("type") or "component").replace("_", " ").title(), "Enabled" if component.get("enabled", True) else "Disabled"]); item.setData(0, Qt.UserRole, str(component.get("component_id") or "")); self.components.addTopLevelItem(item)
        self.prefab_overrides.clear(); instance_data = dict(entity.get("prefab_instance") or {}) if entity else {}; overrides = dict(instance_data.get("overrides") or {})
        diff_rows: list[dict[str, Any]] = []
        source_id = str(instance_data.get("source_asset_id") or "")
        workspace = self.window(); service = getattr(workspace, "prefab_service", None)
        if source_id and service is not None:
            try: diff_rows = list(service.override_diff(service.instantiate(source_id, overrides=overrides)))
            except (KeyError, IndexError, TypeError, ValueError, OSError): diff_rows = []
        if not diff_rows:
            diff_rows = [{"path": path, "inherited": None, "value": value, "state": "conflicted" if source_id else "modified"} for path, value in sorted(overrides.items())]
        for entry in diff_rows:
            path = str(entry.get("path") or ""); inherited = self._render_prefab_value(entry.get("inherited")); value = self._render_prefab_value(entry.get("value")); state = str(entry.get("state") or "modified").title()
            row = QTreeWidgetItem([path, inherited, value, state]); row.setData(0, Qt.UserRole, path); row.setToolTip(0, path); self.prefab_overrides.addTopLevelItem(row)
        for column in range(4): self.prefab_overrides.resizeColumnToContents(column)
        for widget in (self.name, *self.position[1], *self.rotation[1], *self.scale[1], self.add_component): widget.setEnabled(single_editable)
        for widget in (self.mobility, self.visible, self.tags, self.apply_button): widget.setEnabled(single_editable or bulk_editable)
        self.apply_button.setText(f"Apply Shared Values to {selection_count} Actors" if bulk_editable else "Apply Actor Changes")
        self.apply_button.setToolTip("Multi-edit applies Mobility, Visibility, and Tags without collapsing actor transforms." if bulk_editable else "Apply all actor properties")
        self.components.setEnabled(single_editable); self.component_properties.setEnabled(single_editable)
        is_prefab = bool(single_editable and entity and entity.get("prefab_instance")); self.apply_prefab.setEnabled(is_prefab and bool(overrides)); self.revert_prefab.setEnabled(is_prefab and bool(overrides)); self.compare_prefab.setEnabled(is_prefab); self.unpack_prefab.setEnabled(is_prefab); self.add_override_button.setEnabled(is_prefab); self.remove_override_button.setEnabled(is_prefab and bool(overrides)); self.prefab_overrides.setEnabled(is_prefab)
        self._loading = False

    @staticmethod
    def _render_prefab_value(value: Any) -> str:
        if value is None: return "—"
        return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"), sort_keys=True)

    def apply(self) -> bool:
        handler = getattr(self.viewport, "update_selected_level_actor", None)
        values = {"name": self.name.text(), "position": [item.value() for item in self.position[1]], "rotation": [item.value() for item in self.rotation[1]], "scale": [item.value() for item in self.scale[1]], "mobility": self.mobility.currentText().casefold(), "visible": self.visible.isChecked(), "tags": [tag.strip() for tag in self.tags.text().split(",") if tag.strip()]}
        selection_provider = getattr(self.viewport, "selected_level_actor_proxies", None)
        selection_count = len(selection_provider()) if callable(selection_provider) else 1
        if selection_count > 1:
            bulk_handler = getattr(self.viewport, "update_selected_level_actors", None)
            fields = tuple(key for key in ("mobility", "visible", "tags") if key not in self._mixed_fields)
            updated = bool(bulk_handler(values, fields=fields)) if callable(bulk_handler) and fields else False
        else:
            updated = bool(handler(values)) if callable(handler) else False
        if updated: self.refresh()
        return updated

    def add_component_type(self, component_type: str) -> bool:
        handler = getattr(self.viewport, "add_component_to_selected_level_actor", None); added = handler(component_type) if callable(handler) else None
        if added: self.refresh()
        return bool(added)

    def remove_selected_component(self) -> bool:
        item = self.components.currentItem()
        if item is None: return False
        handler = getattr(self.viewport, "remove_component_from_selected_level_actor", None); removed = bool(handler(str(item.data(0, Qt.UserRole) or ""))) if callable(handler) else False
        if removed: self.refresh()
        return removed

    def move_selected_component(self, offset: int) -> bool:
        item = self.components.currentItem()
        if item is None: return False
        component_id = str(item.data(0, Qt.UserRole) or "")
        handler = getattr(self.viewport, "move_component_on_selected_level_actor", None)
        moved = bool(handler(component_id, int(offset))) if callable(handler) else False
        if moved:
            self.refresh()
            for index in range(self.components.topLevelItemCount()):
                candidate = self.components.topLevelItem(index)
                if str(candidate.data(0, Qt.UserRole) or "") == component_id: self.components.setCurrentItem(candidate); break
        return moved

    def _selected_component(self) -> dict[str, Any] | None:
        item = self.components.currentItem(); entity = self._entity()
        if item is None or entity is None: return None
        component_id = str(item.data(0, Qt.UserRole) or "")
        return next((dict(value) for value in entity.get("components") or () if str(value.get("component_id") or "") == component_id), None)

    def copy_selected_component(self) -> bool:
        component = self._selected_component()
        if component is None: return False
        QApplication.clipboard().setText(json.dumps({"schema": "tech_connector.component_clipboard.v1", "component": component}, indent=2, sort_keys=True))
        return True

    def paste_selected_component(self) -> bool:
        target = self._selected_component(); selected = self.components.currentItem()
        if target is None or selected is None: return False
        try: payload = json.loads(QApplication.clipboard().text())
        except json.JSONDecodeError: return False
        source = dict(payload.get("component") or {}) if isinstance(payload, dict) and payload.get("schema") == "tech_connector.component_clipboard.v1" else {}
        if not source or str(source.get("type") or "") != str(target.get("type") or ""): return False
        values = {key: value for key, value in source.items() if key not in {"component_id", "type"}}
        handler = getattr(self.viewport, "update_component_on_selected_level_actor", None)
        updated = bool(handler(str(selected.data(0, Qt.UserRole) or ""), values)) if callable(handler) else False
        if updated: self.refresh()
        return updated

    def _load_component_properties(self) -> None:
        self.component_properties.clear(); item = self.components.currentItem(); entity = self._entity()
        if item is None or entity is None: return
        component_id = str(item.data(0, Qt.UserRole) or ""); component = next((row for row in entity.get("components") or () if str(row.get("component_id") or "") == component_id), None)
        if component is None: return
        for key, value in component.items():
            if key in {"component_id", "type"}: continue
            row = QTreeWidgetItem([str(key).replace("_", " ").title(), json.dumps(value) if isinstance(value, (dict, list, tuple, bool)) or value is None else str(value)]); row.setData(0, Qt.UserRole, str(key)); row.setFlags(row.flags() | Qt.ItemIsEditable); self.component_properties.addTopLevelItem(row)

    def _component_property_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 1: return
        key = str(item.data(0, Qt.UserRole) or "")
        if not key.endswith("_asset_id"): return
        workspace = self.window()
        database = getattr(workspace, "database", None); project_root = getattr(workspace, "project_root", None)
        if database is None or project_root is None: return
        editor_state = getattr(workspace, "editor_state", None)
        picker = AssetPickerDialog(
            project_root, database, registry=getattr(workspace, "registry", None),
            allowed_types=ASSET_REFERENCE_TYPES.get(key, ()), current_asset_id=item.text(1).strip(),
            recent_asset_ids=editor_state.recent_assets if editor_state is not None else (),
            context_asset_id=workspace.asset_browser._selected_asset_id() if hasattr(workspace, "asset_browser") else "",
            title=f"Choose {item.text(0)}", parent=self,
        )
        picker.locateRequested.connect(workspace.locate_asset); picker.inspectRequested.connect(workspace.open_asset_id)
        if picker.exec() == QDialog.Accepted:
            item.setText(1, picker.selected_asset_id)

    def _show_component_property_menu(self, position) -> None:
        item = self.component_properties.itemAt(position)
        if item is None: return
        self.component_properties.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Copy Value", lambda: QApplication.clipboard().setText(item.text(1)))
        menu.addAction("Paste Value", lambda: item.setText(1, QApplication.clipboard().text()))
        key = str(item.data(0, Qt.UserRole) or "")
        if key.endswith("_asset_id"):
            menu.addAction("Choose Compatible Asset…", lambda: self._component_property_double_clicked(item, 1))
            workspace = self.window(); current_id = item.text(1).strip(); selected_id = workspace.asset_browser._selected_asset_id() if hasattr(workspace, "asset_browser") else ""; selected = getattr(workspace, "database", None).asset(selected_id) if selected_id and getattr(workspace, "database", None) is not None else None
            use_selected = menu.addAction("Use Content Browser Selection", lambda: item.setText(1, selected_id)); use_selected.setEnabled(bool(selected and selected.asset_type in ASSET_REFERENCE_TYPES.get(key, ())))
            locate = menu.addAction("Locate Current Reference", lambda: workspace.locate_asset(current_id)); locate.setEnabled(bool(current_id and hasattr(workspace, "locate_asset")))
            inspect = menu.addAction("Open Current Reference", lambda: workspace.open_asset_id(current_id)); inspect.setEnabled(bool(current_id and hasattr(workspace, "open_asset_id")))
            menu.addAction("Clear Reference", lambda: item.setText(1, ""))
        menu.exec(self.component_properties.viewport().mapToGlobal(position))

    def save_component_properties(self) -> bool:
        selected = self.components.currentItem(); entity = self._entity()
        if selected is None or entity is None: return False
        values: dict[str, Any] = {}
        for index in range(self.component_properties.topLevelItemCount()):
            row = self.component_properties.topLevelItem(index); key = str(row.data(0, Qt.UserRole) or ""); raw = row.text(1)
            try: values[key] = json.loads(raw)
            except json.JSONDecodeError: values[key] = raw
        handler = getattr(self.viewport, "update_component_on_selected_level_actor", None); updated = bool(handler(str(selected.data(0, Qt.UserRole) or ""), values)) if callable(handler) else False
        if updated: self.refresh()
        return updated

    def add_prefab_override(self) -> bool:
        path, accepted = QInputDialog.getText(self, "Add Prefab Override", "Property path", text="0.transform.position")
        if not accepted or not path.strip(): return False
        raw, accepted = QInputDialog.getText(self, "Override Value", "JSON or text value")
        if not accepted: return False
        try: value = json.loads(raw)
        except json.JSONDecodeError: value = raw
        handler = getattr(self.viewport, "set_prefab_override_on_selected_level_actor", None); changed = bool(handler(path, value)) if callable(handler) else False
        if changed: self.refresh()
        return changed

    def remove_prefab_override(self) -> bool:
        item = self.prefab_overrides.currentItem()
        if item is None: return False
        handler = getattr(self.viewport, "remove_prefab_override_from_selected_level_actor", None); changed = bool(handler(str(item.data(0, Qt.UserRole) or ""))) if callable(handler) else False
        if changed: self.refresh()
        return changed


class EngineWorkspaceWindow(QMainWindow):
    """Unreal/Unity-style project workspace with one authoritative level viewport."""

    modeChanged = Signal(str)
    levelChanged = Signal(str)
    statusMessage = Signal(str)
    playRequested = Signal(str)
    stopRequested = Signal()
    ejectRequested = Signal()
    resetRequested = Signal(str)
    runtimeStateChanged = Signal(str)

    def __init__(
        self, project_root: str | Path, *, database: AssetDatabase | None = None,
        registry: AssetTypeRegistry | None = None, viewport_factory: Callable[..., QWidget] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or builtin_asset_type_registry()
        self.database = database or AssetDatabase(self.project_root / ".tech_connector" / "assets.sqlite3")
        self.editor_state = EngineEditorState(self.project_root)
        self.sequence_service = SequenceAssetService(self.project_root, self.database)
        self.prefab_service = PrefabService(self.project_root, self.database)
        self.sequence_director = LevelSequenceRuntimeDirector(self.project_root, self.database, command_sink=self._apply_sequence_command)
        self._sequence_asset_id = ""
        self._sequence_dirty = False
        self._asset_editor_base_title = "Asset Editor"
        self._mode = "edit"
        self._paused = False
        self._sequence_timer = QTimer(self); self._sequence_timer.timeout.connect(self._advance_sequence)
        self._build(viewport_factory)
        if os.environ.get("QT_QPA_PLATFORM", "").casefold() != "offscreen":
            QTimer.singleShot(0, self._show_startup_recovery_if_needed)

    def _build(self, viewport_factory: Callable[..., QWidget] | None) -> None:
        self.setObjectName("TechConnectorEngineWorkspace")
        self.setWindowTitle(f"Tech Connector Engine — {self.project_root.name}")
        self.setDockNestingEnabled(True); self.setAnimated(True)
        if viewport_factory is None:
            from tech_connector.ui.dcc_viewer.mesh_painter.widget import ThreeDMeshPainterViewport
            viewport_factory = ThreeDMeshPainterViewport
        try: self.viewport = viewport_factory(parent=self)
        except TypeError: self.viewport = viewport_factory()
        self.setCentralWidget(self.viewport)
        self._build_main_toolbar(); self._build_docks(); self._build_menus()
        self.status_label = QLabel("Edit mode • Open a Level or drag an asset into the viewport")
        self.statusBar().addWidget(self.status_label, 1)
        self.activity_label = QLabel("")
        self.activity_label.setAccessibleName("Background engine activity")
        self.activity_label.setStyleSheet("color:#75d8ff; padding:0 8px;")
        self.activity_label.hide()
        self.statusBar().addPermanentWidget(self.activity_label)
        self.document_state_label = QLabel("Saved")
        self.document_state_label.setAccessibleName("Unsaved engine documents")
        self.document_state_label.setToolTip("Shows which level, asset, or sequence documents have unsaved changes")
        self.statusBar().addPermanentWidget(self.document_state_label)
        self.statusBar().addPermanentWidget(QLabel(str(self.project_root)))
        self._document_state_timer = QTimer(self); self._document_state_timer.setInterval(250); self._document_state_timer.timeout.connect(self._update_document_state_indicators); self._document_state_timer.start(); self._update_document_state_indicators()

    def _build_main_toolbar(self) -> None:
        toolbar = QToolBar("Level Editor", self); toolbar.setObjectName("EngineLevelToolbar"); toolbar.setMovable(False); self.addToolBar(toolbar)
        self.save_action = QAction("Save All", self); self.save_action.setShortcut(QKeySequence.Save); self.save_action.triggered.connect(self.save_all)
        self.undo_action = QAction("Undo", self); self.undo_action.setShortcut(QKeySequence.Undo); self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("Redo", self); self.redo_action.setShortcut(QKeySequence.Redo); self.redo_action.triggered.connect(self.redo)
        self.focus_action = QAction("Focus Selected", self); self.focus_action.setShortcut(QKeySequence("F")); self.focus_action.triggered.connect(self.focus_selected)
        self.duplicate_action = QAction("Duplicate Actor", self); self.duplicate_action.setShortcut(QKeySequence("Ctrl+D")); self.duplicate_action.triggered.connect(self.duplicate_selected_actor)
        self.rename_action = QAction("Rename Actor", self); self.rename_action.setShortcut(QKeySequence("F2")); self.rename_action.triggered.connect(self.rename_selected_actor)
        self.delete_action = QAction("Delete Actor", self); self.delete_action.setShortcut(QKeySequence("Delete")); self.delete_action.triggered.connect(self.delete_selected_actor)
        self.hide_action = QAction("Hide Selected", self); self.hide_action.setShortcut(QKeySequence("H")); self.hide_action.triggered.connect(self.hide_selected_actors)
        self.isolate_action = QAction("Isolate Selected", self); self.isolate_action.setShortcut(QKeySequence("Shift+H")); self.isolate_action.triggered.connect(self.isolate_selected_actors)
        self.show_all_action = QAction("Show All", self); self.show_all_action.setShortcut(QKeySequence("Ctrl+H")); self.show_all_action.triggered.connect(self.show_all_actors)
        self.lock_action = QAction("Lock / Unlock Selected", self); self.lock_action.triggered.connect(self.toggle_selected_actor_lock)
        self.pilot_camera_action = QAction("Pilot Selected Camera", self); self.pilot_camera_action.triggered.connect(self.pilot_selected_camera)
        self.stop_piloting_action = QAction("Stop Piloting Camera", self); self.stop_piloting_action.triggered.connect(self.stop_piloting_camera)
        toolbar.addAction(self.save_action); toolbar.addSeparator(); toolbar.addAction(self.undo_action); toolbar.addAction(self.redo_action)
        add_button = QToolButton(self); add_button.setText("+ Add"); add_button.setPopupMode(QToolButton.InstantPopup); add_button.setMenu(self._actor_create_menu(add_button)); toolbar.addWidget(add_button)
        toolbar.addAction(self.focus_action); toolbar.addAction(self.hide_action); toolbar.addAction(self.isolate_action); toolbar.addAction(self.lock_action); toolbar.addSeparator()
        tools = QActionGroup(self); tools.setExclusive(True); self.tool_actions: dict[str, QAction] = {}
        for key, label, shortcut in (("select", "Select", "Q"), ("translate", "Move", "W"), ("rotate", "Rotate", "E"), ("scale", "Scale", "R")):
            action = QAction(label, self); action.setCheckable(True); action.setShortcut(QKeySequence(shortcut)); action.triggered.connect(lambda _checked=False, value=key: self.set_transform_tool(value)); tools.addAction(action); toolbar.addAction(action); self.tool_actions[key] = action
        self.tool_actions["select"].setChecked(True); toolbar.addSeparator()
        self.coordinate_space = QComboBox(self); self.coordinate_space.setToolTip("Transform coordinate space")
        self.coordinate_space.addItem("World", "world"); self.coordinate_space.addItem("Local", "object"); self.coordinate_space.addItem("Parent", "parent")
        self.coordinate_space.currentIndexChanged.connect(self._coordinate_space_changed); toolbar.addWidget(self.coordinate_space)
        self.pivot_mode = QComboBox(self); self.pivot_mode.setToolTip("Transform pivot (D or Insert edits a custom pivot)")
        for label, value in (("Pivot: Object", "object"), ("Pivot: Selection", "selection"), ("Pivot: World", "world"), ("Pivot: Custom", "custom")): self.pivot_mode.addItem(label, value)
        self.pivot_mode.currentIndexChanged.connect(self._pivot_mode_changed); toolbar.addWidget(self.pivot_mode)
        self.snap_target = QComboBox(self); self.snap_target.setToolTip("Snap target; hold X for grid or V for another point/pivot")
        for label, value in (("Snap Target: Increment", "increment"), ("Snap Target: Grid", "grid"), ("Snap Target: Point", "point")): self.snap_target.addItem(label, value)
        self.snap_target.currentIndexChanged.connect(self._transform_snap_changed); toolbar.addWidget(self.snap_target)
        self.center_pivot_action = QAction("Center Pivot", self); self.center_pivot_action.setToolTip("Place a custom pivot at the selected actor origin")
        self.center_pivot_action.triggered.connect(self.center_selected_pivot); toolbar.addAction(self.center_pivot_action)
        self.move_snap = self._snap_combo("Move Snap", (("Move: Off", 0.0), ("1 cm", 1.0), ("5 cm", 5.0), ("10 cm", 10.0), ("50 cm", 50.0), ("1 m", 100.0)))
        self.rotate_snap = self._snap_combo("Rotate Snap", (("Rotate: Off", 0.0), ("5°", 5.0), ("10°", 10.0), ("15°", 15.0), ("30°", 30.0), ("45°", 45.0)))
        self.scale_snap = self._snap_combo("Scale Snap", (("Scale: Off", 0.0), ("1%", 0.01), ("5%", 0.05), ("10%", 0.1), ("25%", 0.25)))
        for combo in (self.move_snap, self.rotate_snap, self.scale_snap): combo.currentIndexChanged.connect(self._transform_snap_changed); toolbar.addWidget(combo)
        self.view_mode = QComboBox(self); self.view_mode.setToolTip("Viewport shading mode")
        for label, value in (("Lit", "lit"), ("Unlit", "unlit"), ("Wireframe", "wireframe"), ("Resolved", "resolved")): self.view_mode.addItem(label, value)
        self.view_mode.currentIndexChanged.connect(self._view_mode_changed); toolbar.addWidget(self.view_mode); toolbar.addSeparator()
        self.edit_action = QAction("Edit", self); self.simulate_action = QAction("Simulate", self); self.play_action = QAction("Play", self); self.pause_action = QAction("Pause", self); self.step_action = QAction("Step", self); self.stop_action = QAction("Stop", self); self.eject_action = QAction("Eject", self); self.reset_action = QAction("Reset", self)
        modes = QActionGroup(self); modes.setExclusive(True)
        for action in (self.edit_action, self.simulate_action, self.play_action): action.setCheckable(True); modes.addAction(action)
        self.pause_action.setCheckable(True)
        self.play_action.setShortcut(QKeySequence("Alt+P"))
        self.simulate_action.setShortcut(QKeySequence("Alt+S")); self.stop_action.setShortcut(QKeySequence("F8"))
        self.pause_action.setShortcut(QKeySequence("Pause")); self.step_action.setShortcut(QKeySequence("F10"))
        self.play_action.setToolTip("Save the current level and launch an isolated runtime copy (Alt+P)")
        self.simulate_action.setToolTip("Run physics and effects inside the editor viewport (Alt+S)")
        self.stop_action.setToolTip("Stop the active play or simulation session (F8)")
        self.pause_action.setToolTip("Pause or resume the active runtime session (Pause)")
        self.step_action.setToolTip("Advance a paused runtime session by one frame (F10)")
        self.eject_action.setToolTip("Return to the editor while the standalone play session keeps running")
        self.reset_action.setToolTip("Restart the current simulation or standalone play session")
        self.edit_action.setChecked(True)
        for action in (self.edit_action, self.simulate_action, self.play_action, self.pause_action, self.step_action, self.stop_action, self.eject_action, self.reset_action): toolbar.addAction(action)
        self.edit_action.triggered.connect(lambda: self.set_mode("edit")); self.simulate_action.triggered.connect(lambda: self.set_mode("simulate")); self.play_action.triggered.connect(lambda: self.set_mode("play")); self.pause_action.triggered.connect(self.pause); self.step_action.triggered.connect(self.step); self.stop_action.triggered.connect(self.stop); self.eject_action.triggered.connect(self.eject); self.reset_action.triggered.connect(self.reset_runtime)
        self.runtime_state_label = QLabel(" EDIT ", self); self.runtime_state_label.setStyleSheet("font-weight:700; color:#b8c7d1; background:#1d2730; padding:3px 8px; border-radius:3px;"); toolbar.addWidget(self.runtime_state_label)
        self._update_runtime_controls()
        toolbar.addSeparator(); self.sequence_play_action = QAction("Play Sequence", self); self.sequence_play_action.triggered.connect(self.toggle_sequence_playback); toolbar.addAction(self.sequence_play_action)

    def _snap_combo(self, tooltip: str, entries: tuple[tuple[str, float], ...]) -> QComboBox:
        combo = QComboBox(self); combo.setToolTip(tooltip)
        for label, value in entries: combo.addItem(label, value)
        return combo

    def _actor_create_menu(self, parent: QWidget | None = None) -> QMenu:
        menu = QMenu(parent or self)
        for label, actor_type in (("Empty Actor", "empty"), ("Point Light", "point_light"), ("Directional Light", "directional_light"), ("Camera Actor", "camera"), ("Player Start", "player_start"), ("Trigger Volume", "trigger")):
            menu.addAction(label, lambda _checked=False, value=actor_type: self.create_actor(value))
        return menu

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea, name: str) -> QDockWidget:
        dock = QDockWidget(title, self); dock.setObjectName(name); dock.setWidget(widget); dock.setAllowedAreas(Qt.AllDockWidgetAreas); self.addDockWidget(area, dock); return dock

    def _build_docks(self) -> None:
        outliner = getattr(self.viewport, "scene_outliner", None)
        details = ActorDetailsPanel(self.viewport, self)
        self.world_outliner_dock = self._dock("World Outliner", outliner or QLabel("Viewport does not expose an outliner."), Qt.LeftDockWidgetArea, "EngineWorldOutliner")
        self.details_dock = self._dock("Details", details, Qt.RightDockWidgetArea, "EngineDetails"); self.actor_details = details
        self.actor_details.apply_prefab.clicked.connect(self.apply_selected_prefab_overrides); self.actor_details.revert_prefab.clicked.connect(self.revert_selected_prefab_overrides); self.actor_details.compare_prefab.clicked.connect(self.compare_selected_prefab_instance); self.actor_details.unpack_prefab.clicked.connect(self.unpack_selected_prefab_instance)
        if outliner is not None and hasattr(outliner, "itemSelectionChanged"): outliner.itemSelectionChanged.connect(self.actor_details.refresh)
        internal_left = getattr(self.viewport, "scene_left_panel", None)
        if internal_left is not None: internal_left.hide()

        self.asset_browser = AssetBrowserWidget(
            self.project_root, database=self.database, registry=self.registry, parent=self,
            defer_initial_refresh=True,
        )
        self.asset_browser.assetActivated.connect(self.open_asset); self.asset_browser.statusMessage.connect(self._status)
        self.asset_browser.busyChanged.connect(self._asset_browser_busy_changed)
        self.asset_browser.dependencyExplorerRequested.connect(self.show_dependency_explorer)
        self.asset_browser.auditDashboardRequested.connect(self.show_asset_audit)
        self.content_dock = self._dock("Content Browser", self.asset_browser, Qt.BottomDockWidgetArea, "EngineContentBrowser")
        self.asset_editor = DedicatedAssetEditor(self.project_root, self.database, self.registry, parent=self)
        self.asset_editor.previewRequested.connect(self._preview_asset); self.asset_editor.locateRequested.connect(self.locate_asset)
        self.asset_editor.worldVisualizationRequested.connect(self._show_world_visualization)
        self.asset_editor_dock = self._dock("Asset Editor", self.asset_editor, Qt.RightDockWidgetArea, "EngineAssetEditor"); self.asset_editor_dock.hide()
        self.world_settings = WorldSettingsPanel(self.project_root, self.database, self); self.world_settings.changed.connect(self._world_settings_changed)
        self.world_settings_dock = self._dock("World Settings", self.world_settings, Qt.RightDockWidgetArea, "EngineWorldSettings"); self.world_settings_dock.hide()
        self.sequence_editor = SequenceEditorWidget(database=self.database, parent=self)
        self.sequence_editor.changed.connect(self._sequence_changed)
        self.sequence_dock = self._dock("Sequence Editor", self.sequence_editor, Qt.BottomDockWidgetArea, "EngineSequenceEditor"); self.sequence_dock.hide()
        self.output_log = QPlainTextEdit(self); self.output_log.setReadOnly(True); self.output_log.setMaximumBlockCount(4000)
        self.output_dock = self._dock("Output Log", self.output_log, Qt.BottomDockWidgetArea, "EngineOutputLog"); self.output_dock.hide()
        self.console_panel = EngineConsolePanel(self, self); self.console_dock = self._dock("Console", self.console_panel, Qt.BottomDockWidgetArea, "EngineConsole"); self.console_dock.hide()
        self.profiler_panel = RuntimeProfilerPanel(self); self.profiler_dock = self._dock("Profiler", self.profiler_panel, Qt.BottomDockWidgetArea, "EngineProfiler"); self.profiler_dock.hide()
        self.task_center = EngineTaskCenter(self.project_root, self)
        self.task_center.statusMessage.connect(self._status)
        self.asset_browser.taskEvent.connect(self.task_center.apply_event)
        self.task_center.cancelRequested.connect(self._cancel_background_task)
        self.task_center.pauseRequested.connect(self._pause_background_task)
        self.task_center.resumeRequested.connect(self._resume_background_task)
        self.task_center.retryRequested.connect(self._retry_background_task)
        self.task_center.openAssetRequested.connect(self.open_asset_id)
        self.task_center.revealRequested.connect(self._reveal_task_path)
        self.task_center_dock = self._dock("Task Center", self.task_center, Qt.BottomDockWidgetArea, "EngineTaskCenter")
        self.task_center_dock.hide()
        self.dependency_explorer = AssetDependencyExplorer(self.project_root, self.database, self.registry, self)
        self.dependency_explorer.openRequested.connect(self.open_asset_id); self.dependency_explorer.locateRequested.connect(self.locate_asset)
        self.dependency_explorer.assetsChanged.connect(self.asset_browser.refresh); self.dependency_explorer.statusMessage.connect(self._status)
        self.dependency_dock = self._dock("Dependency Explorer", self.dependency_explorer, Qt.RightDockWidgetArea, "EngineDependencyExplorer"); self.dependency_dock.hide()
        self.asset_audit = AssetAuditDashboard(self.project_root, self.database, self.registry, self)
        self.asset_audit.openRequested.connect(self.open_asset_id); self.asset_audit.locateRequested.connect(self.locate_asset); self.asset_audit.dependencyRequested.connect(self.show_dependency_explorer); self.asset_audit.assetsChanged.connect(self.asset_browser.refresh); self.asset_audit.statusMessage.connect(self._status); self.asset_audit.busyChanged.connect(self._asset_audit_busy_changed); self.asset_audit.completed.connect(self._asset_audit_completed)
        self.asset_audit_dock = self._dock("Asset Audit", self.asset_audit, Qt.BottomDockWidgetArea, "EngineAssetAudit"); self.asset_audit_dock.hide()
        self.recovery_center = EngineRecoveryCenter(self.project_root, self, database=self.database)
        self.recovery_center.statusMessage.connect(self._status)
        self.recovery_center.openSceneRequested.connect(self.open_recovery_scene)
        self.recovery_center.openAssetRequested.connect(self.open_asset_id)
        self.recovery_dock = self._dock("Autosave & Recovery", self.recovery_center, Qt.RightDockWidgetArea, "EngineRecoveryCenter")
        self.recovery_dock.hide()
        self.build_panel = BuildDeployPanel(self.project_root, self.database, self); self.build_panel.statusMessage.connect(self._status); self.build_panel.profileReady.connect(self._profile_ready); self.build_panel.openAssetRequested.connect(self.open_asset_id)
        self.build_panel.taskEvent.connect(self.task_center.apply_event)
        self.build_dock = self._dock("Build & Deploy", self.build_panel, Qt.RightDockWidgetArea, "EngineBuildDeploy"); self.build_dock.hide()
        self.world_production = WorldProductionPanel(self.project_root, self.database, self); self.world_production.statusMessage.connect(self._status); self.world_production.openRequested.connect(self.open_asset_id)
        self.world_production_dock = self._dock("World Production", self.world_production, Qt.LeftDockWidgetArea, "EngineWorldProduction"); self.world_production_dock.hide()
        self.launch_readiness = LaunchReadinessPanel(
            self.project_root, self.database, self, auto_refresh=False,
        ); self.launch_readiness.statusMessage.connect(self._status)
        self.launch_readiness_dock = self._dock("Launch Readiness", self.launch_readiness, Qt.RightDockWidgetArea, "EngineLaunchReadiness"); self.launch_readiness_dock.hide()
        self.tabifyDockWidget(self.content_dock, self.sequence_dock); self.tabifyDockWidget(self.sequence_dock, self.output_dock); self.tabifyDockWidget(self.output_dock, self.console_dock); self.tabifyDockWidget(self.console_dock, self.profiler_dock); self.tabifyDockWidget(self.profiler_dock, self.task_center_dock); self.tabifyDockWidget(self.task_center_dock, self.asset_audit_dock); self.content_dock.raise_()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self.quick_open_action = file_menu.addAction("Quick Open Asset…", self.quick_open_asset)
        self.quick_open_action.setShortcut(QKeySequence("Ctrl+P"))
        self.quick_open_action.setToolTip("Search all project assets, favorites, and recent work")
        open_level = file_menu.addAction("Open Level…"); open_level.triggered.connect(self.open_level_dialog)
        self.recent_assets_menu = file_menu.addMenu("Recent Assets")
        self.recent_levels_menu = file_menu.addMenu("Recent Levels")
        file_menu.aboutToShow.connect(self._rebuild_recent_menus)
        file_menu.addSeparator(); file_menu.addAction(self.save_action)
        edit_menu = self.menuBar().addMenu("Edit"); edit_menu.addAction(self.undo_action); edit_menu.addAction(self.redo_action); edit_menu.addSeparator(); edit_menu.addAction(self.duplicate_action); edit_menu.addAction(self.rename_action); edit_menu.addAction(self.delete_action); edit_menu.addSeparator(); edit_menu.addAction(self.focus_action)
        create_menu = self.menuBar().addMenu("Create"); actor_menu = create_menu.addMenu("Actor");
        for label, actor_type in (("Empty Actor", "empty"), ("Point Light", "point_light"), ("Directional Light", "directional_light"), ("Camera Actor", "camera"), ("Player Start", "player_start"), ("Trigger Volume", "trigger")): actor_menu.addAction(label, lambda _checked=False, value=actor_type: self.create_actor(value))
        create_menu.addSeparator(); self.asset_browser._populate_create_submenu(create_menu); create_menu.addSeparator(); create_menu.addAction("Import Assets…", self.asset_browser.import_assets); create_menu.addAction("New Folder…", self.asset_browser.create_folder)
        hierarchy_menu = self.menuBar().addMenu("Hierarchy"); hierarchy_menu.addAction("New Actor Folder…", self.create_actor_folder); hierarchy_menu.addAction("Move Selection to Folder…", self.move_selection_to_folder); hierarchy_menu.addSeparator(); hierarchy_menu.addAction("Parent Selection…", self.parent_selection); hierarchy_menu.addAction("Unparent Selection", lambda: self._parent_selection_to("")); hierarchy_menu.addSeparator(); hierarchy_menu.addAction("Offset Selection…", self.offset_selection)
        view_menu = self.menuBar().addMenu("View"); view_menu.addAction(self.focus_action); view_menu.addAction(self.hide_action); view_menu.addAction(self.isolate_action); view_menu.addAction(self.show_all_action); view_menu.addSeparator(); view_menu.addAction(self.lock_action); view_menu.addSeparator(); view_menu.addAction(self.pilot_camera_action); view_menu.addAction(self.stop_piloting_action)
        bookmarks = view_menu.addMenu("Camera Bookmarks")
        save_bookmark = bookmarks.addMenu("Save Bookmark")
        recall_bookmark = bookmarks.addMenu("Recall Bookmark")
        for slot in range(1, 10):
            save = save_bookmark.addAction(str(slot), lambda _checked=False, value=slot: self.save_camera_bookmark(value)); save.setShortcut(QKeySequence(f"Ctrl+Shift+{slot}"))
            recall = recall_bookmark.addAction(str(slot), lambda _checked=False, value=slot: self.recall_camera_bookmark(value)); recall.setShortcut(QKeySequence(f"Alt+{slot}"))
        window_menu = self.menuBar().addMenu("Window")
        for dock in (self.world_outliner_dock, self.details_dock, self.world_settings_dock, self.world_production_dock, self.content_dock, self.asset_editor_dock, self.sequence_dock, self.output_dock, self.console_dock, self.profiler_dock, self.task_center_dock, self.asset_audit_dock, self.dependency_dock, self.recovery_dock, self.build_dock, self.launch_readiness_dock): window_menu.addAction(dock.toggleViewAction())
        tools_menu = self.menuBar().addMenu("Tools"); tools_menu.addAction("Project Settings", lambda: self.open_or_create_settings("tc.project_settings", "ProjectSettings")); tools_menu.addAction("World Settings", lambda: (self.world_settings_dock.show(), self.world_settings_dock.raise_())); tools_menu.addAction("World Production", lambda: (self.world_production.refresh(), self.world_production_dock.show(), self.world_production_dock.raise_())); tools_menu.addAction("Build & Deploy", lambda: (self.build_panel.refresh(), self.build_dock.show(), self.build_dock.raise_())); tools_menu.addAction("Launch Readiness", lambda: (self.launch_readiness.refresh(), self.launch_readiness_dock.show(), self.launch_readiness_dock.raise_())); tools_menu.addAction("Build Profile Asset", lambda: self.open_or_create_settings("tc.build_profile", "DesktopDevelopment")); tools_menu.addSeparator(); tools_menu.addAction("Asset Audit", self.show_asset_audit); tools_menu.addAction("Dependency Explorer", self.show_dependency_explorer); tools_menu.addSeparator(); tools_menu.addAction("Console", lambda: (self.console_dock.show(), self.console_dock.raise_())); tools_menu.addAction("Profiler", lambda: (self.profiler_dock.show(), self.profiler_dock.raise_()))
        tools_menu.addSeparator()
        recovery_menu = tools_menu.addMenu("Autosave & Recovery")
        recovery_menu.addAction("Save Recovery Copy Now", self.save_recovery_copy_now)
        recovery_menu.addAction("Open Recovery Center", lambda: (self.recovery_center.refresh(), self.recovery_dock.show(), self.recovery_dock.raise_()))
        interval_menu = recovery_menu.addMenu("Autosave Interval")
        interval_actions = QActionGroup(self); interval_actions.setExclusive(True)
        for label, minutes in (("Off", 0), ("1 minute", 1), ("2 minutes", 2), ("5 minutes", 5), ("10 minutes", 10)):
            action = interval_menu.addAction(label); action.setCheckable(True); action.setChecked(minutes == 2); action.triggered.connect(lambda _checked=False, value=minutes: self.set_autosave_interval(value)); interval_actions.addAction(action)
        tools_menu.addSeparator()
        self.command_palette_action = tools_menu.addAction("Search Commands…")
        self.command_palette_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.command_palette_action.setToolTip("Search every engine command, tool, and window")
        self.command_palette_action.triggered.connect(self.show_command_palette)
        layout_menu = self.menuBar().addMenu("Layout"); layout_menu.addAction("Reset Editor Layout", self.reset_layout)
        self.command_palette = EngineCommandPalette(self._command_palette_actions, self)

    @property
    def current_level_path(self) -> str:
        return str(getattr(self.viewport, "_federated_scene_path", "") or "")

    def open_level_dialog(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(self, "Open Level", str(self.project_root), "Tech Connector Level (*.tcscene)")
        return self.load_level(path) if path else False

    def load_level(self, path: str | Path) -> bool:
        loader = getattr(self.viewport, "load_federated_scene_file", None)
        if not callable(loader): return False
        loaded, message = loader(str(path), interactive=True)
        self._status(message or (f"Opened {Path(path).name}" if loaded else "Level load failed"))
        if loaded: self.levelChanged.emit(str(path))
        if loaded: self.world_settings.load_settings(dict(getattr(self.viewport, "_engine_world_settings", {}) or {}))
        if loaded: self._update_runtime_controls()
        if loaded: self.editor_state.touch_level(path)
        return bool(loaded)

    def save_level(self) -> bool:
        path = self.current_level_path
        saver = getattr(self.viewport, "_save_federated_scene_to_path", None)
        saved = bool(saver(path)) if path and callable(saver) else bool(getattr(self.viewport, "save_federated_scene_dialog", lambda: False)())
        self._status("Level saved." if saved else "Level was not saved.")
        return saved

    def save_all(self) -> bool:
        self.viewport._engine_world_settings = self.world_settings.settings()
        level_saved = self.save_level()
        if self._sequence_asset_id:
            self.sequence_service.update(self._sequence_asset_id, self.sequence_editor.settings())
            self._sequence_dirty = False
            self._status("Level and Sequence saved." if level_saved else "Sequence saved; level has no saved path yet.")
            return True
        return level_saved

    def open_or_create_settings(self, type_id: str, name: str) -> bool:
        record = next((item for item in self.database.list_assets() if item.asset_type == type_id), None)
        if record is None:
            receipt = self.asset_browser.operations.create_asset(type_id, name, folder="Assets/Settings")
            record = self.database.asset(receipt.asset_id); self.asset_browser.refresh()
        if record is None: return False
        return self.open_asset(str(record.source_path), record.asset_type, record.asset_id)

    def open_asset(self, path: str, type_id: str, asset_id: str = "") -> bool:
        if type_id == "tc.level":
            opened = self.load_level(path)
            if opened and asset_id: self.editor_state.touch_asset(asset_id)
            return opened
        if type_id == "tc.level_sequence":
            self._sequence_asset_id = str(asset_id); self.sequence_editor.load_settings(self.sequence_service.properties(asset_id)); self._sequence_dirty = False; self.sequence_dock.show(); self.sequence_dock.raise_(); self._status(f"Opened sequence {Path(path).name}"); self.editor_state.touch_asset(asset_id); return True
        opened = self.asset_editor.open_asset(asset_id)
        if opened:
            prefab_mode = type_id == "tc.prefab"
            self._asset_editor_base_title = f"Prefab Mode — {Path(path).stem}" if prefab_mode else f"Asset Editor — {Path(path).stem}"
            self.asset_editor_dock.setWindowTitle(self._asset_editor_base_title)
            self.asset_editor_dock.show(); self.asset_editor_dock.raise_()
            if asset_id: self.editor_state.touch_asset(asset_id)
            if prefab_mode: self._status("Prefab opened in an isolated authoring stage. Inherited and overridden values remain explicit.")
        return bool(opened)

    def open_asset_id(self, asset_id: str) -> bool:
        record = self.database.asset(asset_id)
        return self.open_asset(str(record.source_path), record.asset_type, record.asset_id) if record is not None else False

    def quick_open_asset(self) -> bool:
        picker = AssetPickerDialog(
            self.project_root, self.database, registry=self.registry,
            recent_asset_ids=self.editor_state.recent_assets,
            context_asset_id=self.asset_browser._selected_asset_id(), title="Quick Open Asset", parent=self,
        )
        picker.locateRequested.connect(self.locate_asset); picker.inspectRequested.connect(self.open_asset_id)
        if picker.exec() != QDialog.Accepted or not picker.selected_asset_id:
            return False
        return self.open_asset_id(picker.selected_asset_id)

    def _rebuild_recent_menus(self) -> None:
        self.recent_assets_menu.clear(); self.recent_levels_menu.clear()
        asset_count = 0
        for asset_id in self.editor_state.recent_assets:
            record = self.database.asset(asset_id)
            if record is None: continue
            descriptor = self.registry.descriptor(record.asset_type)
            label = f"{record.source_path.stem} — {descriptor.display_name if descriptor else record.asset_type}"
            self.recent_assets_menu.addAction(label, lambda _checked=False, value=asset_id: self.open_asset_id(value)); asset_count += 1
        if not asset_count: self.recent_assets_menu.addAction("No recent assets").setEnabled(False)
        level_count = 0
        for path in self.editor_state.recent_levels:
            level_path = Path(path)
            if not level_path.is_file(): continue
            self.recent_levels_menu.addAction(level_path.stem, lambda _checked=False, value=path: self.load_level(value)); level_count += 1
        if not level_count: self.recent_levels_menu.addAction("No recent levels").setEnabled(False)
        self.recent_levels_menu.addSeparator(); self.recent_levels_menu.addAction("Clear Recent History", self._clear_recent_history)

    def _clear_recent_history(self) -> None:
        self.editor_state.clear_recent(); self._rebuild_recent_menus(); self._status("Cleared recent asset and level history.")

    def save_recovery_copy_now(self) -> bool:
        saver = getattr(self.viewport, "autosave_federated_scene", None)
        path = str(saver() or "") if callable(saver) else ""
        if path:
            self._status(f"Saved recovery copy: {Path(path).name}")
            self.recovery_center.refresh()
            return True
        self._status("No unsaved level changes require a recovery copy.")
        return False

    def _show_startup_recovery_if_needed(self) -> bool:
        self.recovery_center.refresh()
        if not self.recovery_center.has_actionable_recoveries(project_only=True): return False
        self.recovery_dock.show(); self.recovery_dock.raise_()
        self._status("Newer recovery data is available. Compare it with the saved source before restoring.")
        return True

    def set_autosave_interval(self, minutes: int) -> bool:
        timer = getattr(self.viewport, "scene_autosave_timer", None)
        if timer is None:
            self._status("This viewport does not expose scene autosave controls.")
            return False
        value = max(0, int(minutes))
        if value:
            timer.setInterval(value * 60_000); timer.start(); self._status(f"Level autosave set to every {value} minute(s).")
        else:
            timer.stop(); self._status("Level autosave disabled; manual recovery copies remain available.")
        return True

    def open_recovery_scene(self, path: str) -> bool:
        loaded = self.load_level(path)
        if not loaded: return False
        self.viewport._federated_scene_path = ""
        lifecycle = getattr(self.viewport, "_scene_lifecycle", None)
        if lifecycle is not None and hasattr(lifecycle, "mark_dirty"): lifecycle.mark_dirty()
        self._status("Recovered an autosaved level. Use Save As to keep it without replacing the original.")
        return True

    def _preview_asset(self, path: str, type_id: str, asset_id: str) -> None:
        if type_id in PLACEABLE_TYPES: self.place_asset(path, type_id, asset_id)
        else: self.open_asset(path, type_id, asset_id)

    def _show_world_visualization(self, visualization: dict[str, Any]) -> None:
        handler = getattr(self.viewport, "set_world_production_visualization", None)
        if callable(handler):
            handler(dict(visualization))
        else:
            self.viewport._tc_world_visualization = dict(visualization)
            self.viewport._tc_world_brush_callback = self.asset_editor.apply_world_viewport_stroke
            canvas = getattr(self.viewport, "canvas", None)
            if canvas is not None and hasattr(canvas, "update"):
                canvas.update()
        kind = str(visualization.get("kind") or "world").replace("_", " ").title()
        self._status(f"{kind} visualization shown in the level viewport.")

    def place_asset(self, path: str, type_id: str, asset_id: str = "") -> bool:
        placer = getattr(self.viewport, "place_asset_from_browser", None)
        if not callable(placer): return False
        result = bool(placer({"path": str(path), "type_id": str(type_id), "asset_id": str(asset_id), "name": Path(path).name}))
        self._status(f"Placed {Path(path).name} in the active level." if result else f"Could not place {Path(path).name}.")
        return result

    def locate_asset(self, asset_id: str) -> None:
        from tech_connector.ui.game_engine.asset_browser import ASSET_ID_ROLE
        self.content_dock.show(); self.content_dock.raise_(); self.asset_browser.search_edit.clear()
        for index in range(self.asset_browser.asset_tree.topLevelItemCount()):
            item = self.asset_browser.asset_tree.topLevelItem(index)
            if str(item.data(0, ASSET_ID_ROLE) or "") == str(asset_id): self.asset_browser.asset_tree.setCurrentItem(item); self.asset_browser.asset_tree.scrollToItem(item); break

    def show_dependency_explorer(self, asset_id: str = "") -> bool:
        selected_id = str(asset_id or self.asset_browser._selected_asset_id() or "")
        if not selected_id:
            self._status("Select an asset before opening the Dependency Explorer.")
            return False
        if not self.dependency_explorer.set_asset(selected_id):
            self._status("The selected asset is no longer available.")
            return False
        self.dependency_dock.show(); self.dependency_dock.raise_()
        self._status("Dependency Explorer updated from the asset database.")
        return True

    def show_asset_audit(self) -> bool:
        self.asset_audit_dock.show(); self.asset_audit_dock.raise_()
        started = self.asset_audit.refresh_async()
        if not started:
            self._status("The asset audit is already running.")
        return started

    def set_transform_tool(self, tool: str) -> None:
        value = str(tool); setter = getattr(self.viewport, "set_transform_tool", None)
        if callable(setter): setter(value)
        elif hasattr(self.viewport, "transform_mode"): self.viewport.transform_mode = value
        self._status(f"{value.title()} tool")

    def undo(self) -> None:
        focused = QApplication.focusWidget()
        if focused is not None and (focused is self.asset_editor or self.asset_editor.isAncestorOf(focused)):
            if self.asset_editor.undo(): self._status("Undid the last asset-editor change.")
            else: self._status("Nothing in the active asset editor can be undone.")
            return
        if focused is not None and (focused is self.asset_browser or self.asset_browser.isAncestorOf(focused)):
            if self.asset_browser.operations.can_undo: self.asset_browser.undo_last_operation()
            else: self._status("Nothing in the Content Browser can be undone.")
            return
        handler = getattr(self.viewport, "undo_viewer_action", None)
        if callable(handler): handler(); self._status("Undo")
        else: self._status("Nothing in the active viewport can be undone.")

    def redo(self) -> None:
        focused = QApplication.focusWidget()
        if focused is not None and (focused is self.asset_editor or self.asset_editor.isAncestorOf(focused)):
            if self.asset_editor.redo(): self._status("Redid the asset-editor change.")
            else: self._status("Nothing in the active asset editor can be redone.")
            return
        if focused is not None and (focused is self.asset_browser or self.asset_browser.isAncestorOf(focused)):
            self._status("Content Browser operations are recoverable with Undo; redo is not available after an asset rollback.")
            return
        handler = getattr(self.viewport, "redo_viewer_action", None)
        if callable(handler): handler(); self._status("Redo")
        else: self._status("Nothing in the active viewport can be redone.")

    def focus_selected(self) -> bool:
        handler = getattr(self.viewport, "focus_selected_scene_element", None)
        focused = bool(handler()) if callable(handler) else False
        self._status("Focused the selected level element." if focused else "Select a level element to focus it.")
        return focused

    def create_actor(self, actor_type: str) -> bool:
        handler = getattr(self.viewport, "create_level_actor", None)
        if not callable(handler): self._status("This viewport cannot create level actors."); return False
        actor = handler(actor_type); self._status(f"Created {actor.get('name') or 'actor'}"); return True

    def duplicate_selected_actor(self) -> bool:
        handler = getattr(self.viewport, "duplicate_selected_level_actors", None)
        if callable(handler): count = int(handler() or 0); duplicated = count > 0
        else:
            fallback = getattr(self.viewport, "duplicate_selected_level_actor", None); duplicated = bool(fallback()) if callable(fallback) else False; count = 1 if duplicated else 0
        self._status(f"Duplicated {count} selected actor(s)." if duplicated else "Select an unlocked native level actor to duplicate."); return duplicated

    def rename_selected_actor(self) -> bool:
        proxy = getattr(self.viewport, "_selected_scene_proxy", None)
        current = str(proxy.get("name") or "Actor") if proxy is not None and hasattr(proxy, "get") else "Actor"
        name, accepted = QInputDialog.getText(self, "Rename Actor", "Name", text=current)
        if not accepted: return False
        handler = getattr(self.viewport, "rename_selected_level_actor", None); renamed = bool(handler(name)) if callable(handler) else False
        self._status(f"Renamed actor to {name}." if renamed else "Select a native level actor to rename."); return renamed

    def delete_selected_actor(self) -> bool:
        handler = getattr(self.viewport, "delete_selected_level_actors", None)
        if callable(handler): count = int(handler() or 0); deleted = count > 0
        else:
            fallback = getattr(self.viewport, "delete_selected_level_actor", None); deleted = bool(fallback()) if callable(fallback) else False; count = 1 if deleted else 0
        self._status(f"Deleted {count} actor(s). Use Undo to restore them." if deleted else "Select an unlocked native level actor to delete."); return deleted

    def hide_selected_actors(self) -> bool:
        handler = getattr(self.viewport, "hide_selected_level_actors", None); count = int(handler() or 0) if callable(handler) else 0
        self._status(f"Hid {count} actor(s). Use Show All or Undo to restore them." if count else "Select one or more level actors to hide.")
        return count > 0

    def isolate_selected_actors(self) -> bool:
        handler = getattr(self.viewport, "isolate_selected_level_actors", None); count = int(handler() or 0) if callable(handler) else 0
        self._status(f"Isolated {count} actor(s)." if count else "Select one or more level actors to isolate.")
        return count > 0

    def show_all_actors(self) -> bool:
        handler = getattr(self.viewport, "show_all_level_actors", None); count = int(handler() or 0) if callable(handler) else 0
        self._status(f"Showing all {count} level actor(s)." if count else "There are no native level actors to show.")
        return count > 0

    def toggle_selected_actor_lock(self) -> bool:
        handler = getattr(self.viewport, "set_selected_level_actors_locked", None); count = int(handler(None) or 0) if callable(handler) else 0
        self.actor_details.refresh()
        self._status(f"Updated lock state for {count} actor(s)." if count else "Select one or more level actors to lock or unlock.")
        return count > 0

    def pilot_selected_camera(self) -> bool:
        handler = getattr(self.viewport, "pilot_selected_camera_actor", None); piloting = bool(handler()) if callable(handler) else False
        self._status("Piloting selected camera. Stop Piloting commits the view to the actor." if piloting else "Select a native Camera Actor to pilot.")
        return piloting

    def stop_piloting_camera(self) -> bool:
        handler = getattr(self.viewport, "stop_piloting_camera_actor", None); stopped = bool(handler(commit=True)) if callable(handler) else False
        self._status("Stopped piloting and committed the camera transform." if stopped else "No native camera is currently being piloted.")
        return stopped

    def save_camera_bookmark(self, slot: int) -> bool:
        handler = getattr(self.viewport, "save_camera_bookmark", None); saved = bool(handler(slot)) if callable(handler) else False
        self._status(f"Saved camera bookmark {slot}." if saved else "This viewport cannot save camera bookmarks.")
        return saved

    def recall_camera_bookmark(self, slot: int) -> bool:
        handler = getattr(self.viewport, "recall_camera_bookmark", None); recalled = bool(handler(slot)) if callable(handler) else False
        self._status(f"Recalled camera bookmark {slot}." if recalled else f"Camera bookmark {slot} has not been saved.")
        return recalled

    def create_actor_folder(self) -> bool:
        name, accepted = QInputDialog.getText(self, "New Actor Folder", "Folder name")
        handler = getattr(self.viewport, "create_actor_folder", None); created = bool(handler(name)) if accepted and callable(handler) else False
        if created: self._status(f"Created actor folder {name}.")
        return created

    def move_selection_to_folder(self) -> bool:
        folders = list(getattr(self.viewport, "_runtime_world_state", {}).get("editor_folders") or []); folder, accepted = QInputDialog.getItem(self, "Move Actors", "Folder", ["/ (Root)", *folders], 0, True)
        handler = getattr(self.viewport, "move_selected_level_actors_to_folder", None); count = int(handler("" if folder == "/ (Root)" else folder) or 0) if accepted and callable(handler) else 0
        return count > 0

    def parent_selection(self) -> bool:
        entities = [entity for entity in getattr(self.viewport, "_runtime_world_state", {}).get("entities") or () if isinstance(entity, dict)]; choices = [f"{entity.get('name') or 'Actor'} [{entity.get('entity_id')}]" for entity in entities]
        value, accepted = QInputDialog.getItem(self, "Parent Actors", "New parent", choices, 0, False)
        return self._parent_selection_to(value.rsplit("[", 1)[-1].rstrip("]")) if accepted and value else False

    def _parent_selection_to(self, parent_entity_id: str) -> bool:
        handler = getattr(self.viewport, "parent_selected_level_actors", None); return bool(handler(parent_entity_id)) if callable(handler) else False

    def offset_selection(self) -> bool:
        value, accepted = QInputDialog.getText(self, "Offset Selected Actors", "Translation X, Y, Z", text="0, 0, 0")
        if not accepted: return False
        try: values = tuple(float(part.strip()) for part in value.split(",")); assert len(values) == 3
        except (ValueError, AssertionError): self._status("Enter exactly three numeric values."); return False
        handler = getattr(self.viewport, "transform_selected_level_actors", None); return bool(handler(translation=values)) if callable(handler) else False

    def apply_selected_prefab_overrides(self) -> bool:
        entity = self.actor_details._entity(); instance = dict(entity.get("prefab_instance") or {}) if entity else {}; asset_id = str(instance.get("source_asset_id") or "")
        if not asset_id or bool(entity.get("editor_locked", False)): return False
        try: updated = self.prefab_service.apply_overrides(self.prefab_service.instantiate(asset_id, overrides=dict(instance.get("overrides") or {})))
        except (KeyError, ValueError, OSError) as exc: self._status(f"Could not apply Prefab overrides: {exc}"); return False
        entity["prefab_instance"].update(updated.to_dict()); getattr(self.viewport, "_scene_lifecycle").mark_dirty(); self.actor_details.refresh(); self._status("Applied instance overrides to the Prefab source."); return True

    def revert_selected_prefab_overrides(self) -> bool:
        entity = self.actor_details._entity(); instance = dict(entity.get("prefab_instance") or {}) if entity else {}; asset_id = str(instance.get("source_asset_id") or "")
        if not asset_id or bool(entity.get("editor_locked", False)): return False
        try: updated = self.prefab_service.revert_overrides(self.prefab_service.instantiate(asset_id, overrides=dict(instance.get("overrides") or {})))
        except (KeyError, ValueError, OSError) as exc: self._status(f"Could not revert Prefab overrides: {exc}"); return False
        entity["prefab_instance"].update(updated.to_dict()); getattr(self.viewport, "_scene_lifecycle").mark_dirty(); self.actor_details.refresh(); self._status("Reverted instance overrides to the Prefab source."); return True

    def compare_selected_prefab_instance(self) -> bool:
        entity = self.actor_details._entity(); instance = dict(entity.get("prefab_instance") or {}) if entity else {}
        if not instance: return False
        self.actor_details.refresh(); self.details_dock.show(); self.details_dock.raise_(); self.actor_details.prefab_overrides.setFocus()
        count = self.actor_details.prefab_overrides.topLevelItemCount()
        conflicts = sum(1 for index in range(count) if self.actor_details.prefab_overrides.topLevelItem(index).text(3).casefold() == "conflicted")
        self._status(f"Prefab comparison: {count} override{'s' if count != 1 else ''}, {conflicts} conflict{'s' if conflicts != 1 else ''}.")
        return True

    def unpack_selected_prefab_instance(self) -> bool:
        entity = self.actor_details._entity(); instance = dict(entity.get("prefab_instance") or {}) if entity else {}; source_id = str(instance.get("source_asset_id") or "")
        if entity is not None and source_id:
            try:
                resolved = self.prefab_service.instantiate(source_id, overrides=dict(instance.get("overrides") or {}), expand_nested=True)
                entity["prefab_instance"].update(resolved.to_dict())
            except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
                self._status(f"Could not resolve Prefab for unpacking: {exc}"); return False
        handler = getattr(self.viewport, "unpack_selected_prefab_instance", None)
        unpacked = int(handler() or 0) if callable(handler) else 0
        if unpacked:
            self.actor_details.refresh(); self._status(f"Unpacked Prefab into {unpacked} editable actor{'s' if unpacked != 1 else ''}.")
        else: self._status("Select an unlocked Prefab instance to unpack.")
        return unpacked > 0

    def _coordinate_space_changed(self) -> None:
        value = str(self.coordinate_space.currentData() or "world")
        handler = getattr(self.viewport, "change_transform_orientation_mode", None)
        if callable(handler): handler("Object" if value == "object" else value.title())
        else: self.viewport.transform_orientation_mode = value
        self._status(f"Transform space: {'Local' if value == 'object' else value.title()}")

    def _pivot_mode_changed(self) -> None:
        mode = str(self.pivot_mode.currentData() or "object")
        handler = getattr(self.viewport, "configure_transform_pivot", None)
        if callable(handler): handler(mode)
        self._status(f"Transform pivot: {mode.replace('_', ' ')}")

    def center_selected_pivot(self) -> bool:
        handler = getattr(self.viewport, "center_selected_transform_pivot", None)
        centered = bool(handler()) if callable(handler) else False
        if centered: self.pivot_mode.setCurrentIndex(self.pivot_mode.findData("custom"))
        self._status("Centered the custom pivot on the selected actor." if centered else "Select an actor to center its pivot.")
        return centered

    def _transform_snap_changed(self) -> None:
        move = float(self.move_snap.currentData() or 0.0); rotate = float(self.rotate_snap.currentData() or 0.0); scale = float(self.scale_snap.currentData() or 0.0)
        handler = getattr(self.viewport, "configure_transform_snapping", None)
        target = str(self.snap_target.currentData() or "increment")
        if callable(handler):
            handler(translation=move, rotation=rotate, scale=scale)
            if hasattr(self.viewport, "_transform_snap_settings"): handler(enabled=any(value > 0.0 for value in (move, rotate, scale)), target=target)
        placement = getattr(self.viewport, "configure_asset_placement", None)
        if callable(placement): placement(grid_snap=move > 0.0, grid_size=move if move > 0.0 else None)
        enabled = [name for name, value in (("move", move), ("rotate", rotate), ("scale", scale)) if value > 0.0]
        self._status("Snapping: " + (", ".join(enabled) if enabled else "off"))

    def _view_mode_changed(self) -> None:
        mode = str(self.view_mode.currentData() or "lit")
        wire = mode == "wireframe"; shader = mode == "lit"; resolved = mode == "resolved"
        for name, checked in (("wire_btn", wire), ("shader_mode_btn", shader), ("resolved_shaded_btn", resolved)):
            button = getattr(self.viewport, name, None)
            if button is not None and hasattr(button, "setChecked"): button.setChecked(checked)
        if not hasattr(self.viewport, "wire_btn"):
            handler = getattr(self.viewport, "toggle_wireframe_display", None)
            if callable(handler): handler(wire)
        self.viewport._engine_view_mode = mode
        self._status(f"Viewport: {self.view_mode.currentText()}")

    def set_mode(self, mode: str) -> bool:
        value = str(mode).casefold()
        if value not in {"edit", "simulate", "play"}: raise ValueError(f"Unknown engine mode: {mode}")
        if value == "play" and not self.save_level(): return False
        simulator = getattr(self.viewport, "set_simulation_playing", None)
        if callable(simulator): simulator(value == "simulate")
        self._mode = value; self._paused = False; self.modeChanged.emit(value); self.runtimeStateChanged.emit(value)
        self.edit_action.setChecked(value == "edit"); self.simulate_action.setChecked(value == "simulate"); self.play_action.setChecked(value == "play")
        if value == "play": self.playRequested.emit(self.current_level_path)
        self._update_runtime_controls()
        self._status({"edit": "Editing the authoritative level.", "simulate": "Simulating physics and effects in the editor viewport.", "play": "Playing an isolated runtime copy of the saved level."}[value])
        return True

    def pause(self) -> None:
        if self._mode != "simulate":
            self._status("Pause and frame-step are available for in-editor simulation; standalone Play is controlled in its player window.")
            self.pause_action.setChecked(False)
            return
        self._paused = not self._paused
        simulator = getattr(self.viewport, "set_simulation_playing", None)
        if callable(simulator): simulator(not self._paused)
        self.runtimeStateChanged.emit("paused" if self._paused else "simulate")
        self._update_runtime_controls()
        self._status("Simulation paused. Step advances one frame." if self._paused else "Simulation resumed.")

    def step(self) -> None:
        if self._mode != "simulate":
            self._status("Frame Step is available while using Simulate.")
            return
        if not self._paused:
            self._paused = True
            simulator = getattr(self.viewport, "set_simulation_playing", None)
            if callable(simulator): simulator(False)
        stepper = getattr(self.viewport, "step_simulation", None) or getattr(self.viewport, "advance_simulation", None)
        if callable(stepper):
            try: stepper()
            except TypeError: stepper(1.0 / 60.0)
        self.runtimeStateChanged.emit("paused")
        self._update_runtime_controls()
        self._status("Advanced one simulation frame.")

    def stop(self) -> None:
        if self._mode == "play": self.stopRequested.emit()
        simulator = getattr(self.viewport, "set_simulation_playing", None)
        if callable(simulator): simulator(False)
        self.set_mode("edit")

    def eject(self) -> None:
        if self._mode != "play":
            self._status("Eject is available while a standalone Play session is running.")
            return
        self.ejectRequested.emit()
        self.set_mode("edit")
        self._status("Ejected to the editor. The standalone play session is still running.")

    def reset_runtime(self) -> None:
        path = self.current_level_path
        if self._mode == "play":
            self.resetRequested.emit(path)
            self._status("Restarting the standalone play session from the saved level.")
            return
        resetter = getattr(self.viewport, "reset_simulation", None)
        if callable(resetter):
            resetter()
        elif path:
            self.load_level(path)
        if self._mode == "simulate":
            self._paused = False
            simulator = getattr(self.viewport, "set_simulation_playing", None)
            if callable(simulator): simulator(True)
        self.runtimeStateChanged.emit(self._mode)
        self._update_runtime_controls()
        self._status("Simulation reset to the saved level." if path else "There is no saved level to reset.")

    def _update_runtime_controls(self) -> None:
        active = self._mode in {"simulate", "play"}
        simulating = self._mode == "simulate"
        self.pause_action.setEnabled(simulating)
        self.pause_action.setChecked(simulating and self._paused)
        self.pause_action.setText("Resume" if simulating and self._paused else "Pause")
        self.step_action.setEnabled(simulating)
        self.stop_action.setEnabled(active)
        self.eject_action.setEnabled(self._mode == "play")
        self.reset_action.setEnabled(active or bool(self.current_level_path))
        state = "PAUSED" if self._paused else {"edit": "EDIT", "simulate": "SIMULATE", "play": "PLAY"}[self._mode]
        colors = {"EDIT": ("#b8c7d1", "#1d2730"), "SIMULATE": ("#ffd37a", "#3b2c0d"), "PLAY": ("#8ff0ae", "#10351d"), "PAUSED": ("#91c9ff", "#102c46")}
        foreground, background = colors[state]
        self.runtime_state_label.setText(f" {state} ")
        self.runtime_state_label.setStyleSheet(f"font-weight:700; color:{foreground}; background:{background}; padding:3px 8px; border-radius:3px;")

    def toggle_sequence_playback(self) -> None:
        if not self._sequence_asset_id: self._status("Open a Level Sequence first."); return
        if self._sequence_timer.isActive(): self._sequence_timer.stop(); self.sequence_play_action.setText("Play Sequence")
        else:
            fps = max(1, self.sequence_editor.fps.value()); self._sequence_timer.start(round(1000 / fps)); self.sequence_play_action.setText("Pause Sequence")

    def _advance_sequence(self) -> None:
        self.sequence_editor._advance(); frame = self.sequence_editor.frame.value()
        try:
            result = self.sequence_director.tick(self._sequence_asset_id, frame)
            camera = result.active_camera or {}; self._status(f"Sequence frame {frame}" + (f" • Camera: {camera.get('name', 'cut')}" if camera else ""))
        except (KeyError, ValueError) as exc: self._status(f"Sequence preview: {exc}")

    def _apply_sequence_command(self, command: SequenceRuntimeCommand) -> None:
        handler = getattr(self.viewport, "apply_level_sequence_command", None)
        if callable(handler): handler(command.to_dict())
        self.output_log.appendPlainText(f"[{command.operation}] {Path(command.level_source).name} weight={command.weight:.3f}")

    def _sequence_changed(self) -> None:
        if self._sequence_asset_id: self._sequence_dirty = True; self.status_label.setText("Sequence has unsaved changes • Save All to keep them")

    def _update_document_state_indicators(self) -> tuple[str, ...]:
        lifecycle = getattr(self.viewport, "_scene_lifecycle", None)
        level_dirty = bool(lifecycle is not None and getattr(lifecycle, "dirty", False))
        session = getattr(self.asset_editor, "session", None)
        asset_dirty = bool((session is not None and getattr(session, "dirty", False)) or getattr(self.asset_editor, "_specialized_dirty", False))
        dirty = tuple(name for name, changed in (("Level", level_dirty), ("Asset", asset_dirty), ("Sequence", self._sequence_dirty)) if changed)
        self.document_state_label.setText("Unsaved: " + ", ".join(dirty) if dirty else "Saved")
        self.document_state_label.setStyleSheet("color:#ffd37a; font-weight:700; padding:0 6px;" if dirty else "color:#8fa2ae; padding:0 6px;")
        self.setWindowTitle(f"Tech Connector Engine — {self.project_root.name}{' *' if dirty else ''}")
        self.asset_editor_dock.setWindowTitle(self._asset_editor_base_title + (" *" if asset_dirty else ""))
        self.sequence_dock.setWindowTitle("Sequence Editor *" if self._sequence_dirty else "Sequence Editor")
        return dirty

    def _world_settings_changed(self) -> None:
        self.viewport._engine_world_settings = self.world_settings.settings()
        lifecycle = getattr(self.viewport, "_scene_lifecycle", None)
        if lifecycle is not None and hasattr(lifecycle, "mark_dirty"): lifecycle.mark_dirty()
        self.status_label.setText("World Settings changed • Save All to update the level")

    def _status(self, message: str) -> None:
        text = str(message or ""); self.status_label.setText(text); self.output_log.appendPlainText(text); self.statusMessage.emit(text)

    def _command_palette_actions(self) -> list[tuple[str, str, QAction]]:
        commands: list[tuple[str, str, QAction]] = []
        seen: set[int] = set()

        def collect(menu: QMenu, category: str) -> None:
            for action in menu.actions():
                submenu = action.menu()
                label = action.text().replace("&", "").strip()
                if submenu is not None:
                    collect(submenu, f"{category} / {label}")
                elif label and not action.isSeparator() and id(action) not in seen:
                    seen.add(id(action))
                    commands.append((category, label, action))

        for top_action in self.menuBar().actions():
            menu = top_action.menu()
            if menu is not None:
                collect(menu, top_action.text().replace("&", "").strip())
        return commands

    def show_command_palette(self) -> None:
        self.command_palette.show_palette()

    def _asset_browser_busy_changed(self, busy: bool, message: str) -> None:
        if not hasattr(self, "activity_label"):
            return
        self.activity_label.setText(f"● {message}" if busy else "")
        self.activity_label.setVisible(bool(busy))
        if not hasattr(self, "task_center"):
            return
        if busy:
            self.task_center.begin("asset_scan", "Scan project assets", category="assets")
        else:
            self.task_center.finish("asset_scan", message="Asset scan complete.")

    def _asset_audit_busy_changed(self, busy: bool, message: str) -> None:
        if hasattr(self, "activity_label"):
            self.activity_label.setText(f"● {message}" if busy else "")
            self.activity_label.setVisible(bool(busy))
        if busy and hasattr(self, "task_center"):
            self.task_center.begin("asset_audit", "Audit project assets", category="assets")

    def _asset_audit_completed(self, succeeded: bool, message: str) -> None:
        if hasattr(self, "task_center"):
            self.task_center.finish("asset_audit", state="complete" if succeeded else "failed", message=message)

    def _cancel_background_task(self, task_id: str) -> None:
        if str(task_id).startswith("build:"):
            self.build_panel.cancel()
        elif str(task_id).startswith("import:"):
            self.asset_browser.cancel_background_task(task_id)

    def _pause_background_task(self, task_id: str) -> None:
        if str(task_id).startswith("build:"):
            self.build_panel.pause()

    def _resume_background_task(self, task_id: str) -> None:
        if str(task_id).startswith("build:"):
            self.build_panel.resume_last()

    def _retry_background_task(self, task_id: str) -> None:
        if str(task_id).startswith("build:"):
            self.build_panel.resume_last()
        else:
            self.asset_browser.retry_background_task(task_id)

    def _reveal_task_path(self, path: str) -> bool:
        target = Path(str(path)).expanduser().resolve()
        if not target.is_dir(): target = target.parent
        while not target.exists() and target != target.parent: target = target.parent
        opened = bool(target.exists() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))))
        self._status(f"Opened {target}." if opened else f"Could not reveal task location: {path}")
        return opened

    def _profile_ready(self, path: str) -> None:
        self.profiler_panel.watch(path); self.profiler_dock.show(); self.profiler_dock.raise_()

    def reset_layout(self) -> None:
        for dock in (self.world_outliner_dock, self.details_dock, self.content_dock): dock.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, self.world_outliner_dock); self.addDockWidget(Qt.RightDockWidgetArea, self.details_dock); self.addDockWidget(Qt.BottomDockWidgetArea, self.content_dock)

    def save_layout_state(self) -> bytes:
        return bytes(self.saveState())

    def restore_layout_state(self, state: bytes | QByteArray) -> bool:
        return self.restoreState(QByteArray(state))
