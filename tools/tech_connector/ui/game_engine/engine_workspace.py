"""Dockable game-engine workspace built around the authoritative Garden viewport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QPlainTextEdit,
    QPushButton, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import AssetDatabase, AssetTypeRegistry, PrefabService, builtin_asset_type_registry
from tech_connector.game_engine.assets.sequence_asset_service import SequenceAssetService
from tech_connector.game_engine.runtime.level_sequence_runtime_service import LevelSequenceRuntimeDirector, SequenceRuntimeCommand
from tech_connector.ui.game_engine.asset_browser import AssetBrowserWidget
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.sequence_editor import SequenceEditorWidget
from tech_connector.ui.game_engine.production_tools import BuildDeployPanel, EngineConsolePanel, LaunchReadinessPanel, RuntimeProfilerPanel
from tech_connector.ui.game_engine.world_production_panel import WorldProductionPanel


PLACEABLE_TYPES = frozenset({
    "tc.static_mesh", "tc.skeletal_mesh", "tc.prefab", "tc.effect_system",
    "tc.simulation_profile", "tc.audio_clip", "tc.sound_cue", "tc.behavior",
    "tc.gameplay_graph", "tc.light", "tc.camera",
})


class WorldSettingsPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout()
        self.gravity_x = self._number(-100000, 100000, 0); self.gravity_y = self._number(-100000, 100000, -980); self.gravity_z = self._number(-100000, 100000, 0)
        gravity = QHBoxLayout(); gravity.addWidget(self.gravity_x); gravity.addWidget(self.gravity_y); gravity.addWidget(self.gravity_z)
        self.skybox = QLineEdit(self); self.game_ruleset = QLineEdit(self); self.time_of_day = self._number(0, 24, 12); self.exposure = self._number(-20, 20, 0)
        self.navigation = QCheckBox("Build and use navigation", self); self.navigation.setChecked(True)
        self.streaming = QComboBox(self); self.streaming.addItems(["world_partition", "sublevels", "disabled"])
        form.addRow("Gravity XYZ", gravity); form.addRow("Skybox / Environment", self.skybox); form.addRow("Default Game Ruleset", self.game_ruleset); form.addRow("Time of Day", self.time_of_day); form.addRow("Exposure", self.exposure); form.addRow("Level Streaming", self.streaming); form.addRow("Navigation", self.navigation)
        root.addLayout(form); root.addStretch(1)
        for widget in (self.gravity_x, self.gravity_y, self.gravity_z, self.time_of_day, self.exposure): widget.valueChanged.connect(self.changed)
        self.skybox.textChanged.connect(self.changed); self.game_ruleset.textChanged.connect(self.changed); self.navigation.toggled.connect(self.changed); self.streaming.currentTextChanged.connect(self.changed)

    @staticmethod
    def _number(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox(); widget.setRange(minimum, maximum); widget.setDecimals(3); widget.setValue(value); return widget

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
        super().__init__(parent); self.viewport = viewport; self._loading = False
        root = QVBoxLayout(self); self.title = QLabel("No actor selected", self); self.title.setStyleSheet("font-weight:600; font-size:14px"); root.addWidget(self.title)
        form = QFormLayout(); self.name = QLineEdit(self); form.addRow("Name", self.name)
        self.position = self._vector_row((0.0, 0.0, 0.0)); form.addRow("Location", self.position[0])
        self.rotation = self._vector_row((0.0, 0.0, 0.0)); form.addRow("Rotation", self.rotation[0])
        self.scale = self._vector_row((1.0, 1.0, 1.0)); form.addRow("Scale", self.scale[0])
        self.mobility = QComboBox(self); self.mobility.addItems(["Static", "Stationary", "Movable"]); self.mobility.setCurrentText("Movable"); form.addRow("Mobility", self.mobility)
        self.visible = QCheckBox("Visible", self); self.visible.setChecked(True); form.addRow("Rendering", self.visible)
        self.tags = QLineEdit(self); self.tags.setPlaceholderText("gameplay, interactable, enemy"); form.addRow("Tags", self.tags); root.addLayout(form)
        self.apply_button = QPushButton("Apply Actor Changes", self); self.apply_button.clicked.connect(self.apply); root.addWidget(self.apply_button)
        root.addWidget(QLabel("Components", self)); self.components = QTreeWidget(self); self.components.setHeaderLabels(["Component", "State"]); root.addWidget(self.components, 1)
        controls = QHBoxLayout(); self.add_component = QToolButton(self); self.add_component.setText("+ Add Component"); self.add_component.setPopupMode(QToolButton.InstantPopup); self.add_component.setMenu(self._component_menu()); controls.addWidget(self.add_component)
        remove = QPushButton("Remove", self); remove.clicked.connect(self.remove_selected_component); controls.addWidget(remove); root.addLayout(controls)
        self.component_properties = QTreeWidget(self); self.component_properties.setHeaderLabels(["Component Property", "Value"]); self.component_properties.setRootIsDecorated(False); root.addWidget(self.component_properties)
        self.components.itemSelectionChanged.connect(self._load_component_properties)
        save_component = QPushButton("Apply Component Changes", self); save_component.clicked.connect(self.save_component_properties); root.addWidget(save_component)
        prefab_row = QHBoxLayout(); self.apply_prefab = QPushButton("Apply Prefab Overrides", self); self.revert_prefab = QPushButton("Revert Prefab Overrides", self); prefab_row.addWidget(self.apply_prefab); prefab_row.addWidget(self.revert_prefab); root.addLayout(prefab_row)
        self.prefab_overrides = QTreeWidget(self); self.prefab_overrides.setHeaderLabels(["Prefab Override", "Value"]); self.prefab_overrides.setRootIsDecorated(False); root.addWidget(self.prefab_overrides)
        override_row = QHBoxLayout(); add_override = QPushButton("+ Override", self); add_override.clicked.connect(self.add_prefab_override); remove_override = QPushButton("Revert Selected", self); remove_override.clicked.connect(self.remove_prefab_override); override_row.addWidget(add_override); override_row.addWidget(remove_override); root.addLayout(override_row); self.add_override_button = add_override; self.remove_override_button = remove_override
        self.refresh()

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
        entity = self._entity(); editable = entity is not None; self._loading = True
        self.title.setText(str(entity.get("name") or "Actor") if entity else "Linked DCC object — source-owned")
        self.name.setText(str(entity.get("name") or "") if entity else "")
        transform = dict(entity.get("transform") or {}) if entity else {}
        for controls, key, default in ((self.position[1], "position", (0.0, 0.0, 0.0)), (self.rotation[1], "rotation", (0.0, 0.0, 0.0)), (self.scale[1], "scale", (1.0, 1.0, 1.0))):
            values = list(transform.get(key) or default)
            for index, control in enumerate(controls): control.setValue(float(values[index] if index < len(values) else default[index]))
        self.mobility.setCurrentText(str(entity.get("mobility") or "movable").title() if entity else "Movable"); self.visible.setChecked(bool(entity.get("visible", True)) if entity else False); self.tags.setText(", ".join(entity.get("tags") or []) if entity else "")
        self.components.clear()
        for component in (entity.get("components") or []) if entity else ():
            item = QTreeWidgetItem([str(component.get("type") or "component").replace("_", " ").title(), "Enabled" if component.get("enabled", True) else "Disabled"]); item.setData(0, Qt.UserRole, str(component.get("component_id") or "")); self.components.addTopLevelItem(item)
        self.prefab_overrides.clear(); overrides = dict(entity.get("prefab_instance", {}).get("overrides") or {}) if entity else {}
        for path, value in sorted(overrides.items()):
            row = QTreeWidgetItem([str(path), json.dumps(value) if not isinstance(value, str) else value]); row.setData(0, Qt.UserRole, str(path)); self.prefab_overrides.addTopLevelItem(row)
        for widget in (self.name, *self.position[1], *self.rotation[1], *self.scale[1], self.mobility, self.visible, self.tags, self.apply_button, self.add_component): widget.setEnabled(editable)
        is_prefab = bool(entity and entity.get("prefab_instance")); self.apply_prefab.setEnabled(is_prefab and bool(overrides)); self.revert_prefab.setEnabled(is_prefab and bool(overrides)); self.add_override_button.setEnabled(is_prefab); self.remove_override_button.setEnabled(is_prefab and bool(overrides)); self.prefab_overrides.setEnabled(is_prefab)
        self._loading = False

    def apply(self) -> bool:
        handler = getattr(self.viewport, "update_selected_level_actor", None)
        values = {"name": self.name.text(), "position": [item.value() for item in self.position[1]], "rotation": [item.value() for item in self.rotation[1]], "scale": [item.value() for item in self.scale[1]], "mobility": self.mobility.currentText().casefold(), "visible": self.visible.isChecked(), "tags": [tag.strip() for tag in self.tags.text().split(",") if tag.strip()]}
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

    def _load_component_properties(self) -> None:
        self.component_properties.clear(); item = self.components.currentItem(); entity = self._entity()
        if item is None or entity is None: return
        component_id = str(item.data(0, Qt.UserRole) or ""); component = next((row for row in entity.get("components") or () if str(row.get("component_id") or "") == component_id), None)
        if component is None: return
        for key, value in component.items():
            if key in {"component_id", "type"}: continue
            row = QTreeWidgetItem([str(key).replace("_", " ").title(), json.dumps(value) if isinstance(value, (dict, list, tuple, bool)) or value is None else str(value)]); row.setData(0, Qt.UserRole, str(key)); row.setFlags(row.flags() | Qt.ItemIsEditable); self.component_properties.addTopLevelItem(row)

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

    def __init__(
        self, project_root: str | Path, *, database: AssetDatabase | None = None,
        registry: AssetTypeRegistry | None = None, viewport_factory: Callable[..., QWidget] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or builtin_asset_type_registry()
        self.database = database or AssetDatabase(self.project_root / ".tech_connector" / "assets.sqlite3")
        self.sequence_service = SequenceAssetService(self.project_root, self.database)
        self.prefab_service = PrefabService(self.project_root, self.database)
        self.sequence_director = LevelSequenceRuntimeDirector(self.project_root, self.database, command_sink=self._apply_sequence_command)
        self._sequence_asset_id = ""
        self._mode = "edit"
        self._sequence_timer = QTimer(self); self._sequence_timer.timeout.connect(self._advance_sequence)
        self._build(viewport_factory)

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
        self.statusBar().addPermanentWidget(QLabel(str(self.project_root)))

    def _build_main_toolbar(self) -> None:
        toolbar = QToolBar("Level Editor", self); toolbar.setObjectName("EngineLevelToolbar"); toolbar.setMovable(False); self.addToolBar(toolbar)
        self.save_action = QAction("Save All", self); self.save_action.setShortcut(QKeySequence.Save); self.save_action.triggered.connect(self.save_all)
        self.undo_action = QAction("Undo", self); self.undo_action.setShortcut(QKeySequence.Undo); self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("Redo", self); self.redo_action.setShortcut(QKeySequence.Redo); self.redo_action.triggered.connect(self.redo)
        self.focus_action = QAction("Focus Selected", self); self.focus_action.setShortcut(QKeySequence("F")); self.focus_action.triggered.connect(self.focus_selected)
        self.duplicate_action = QAction("Duplicate Actor", self); self.duplicate_action.setShortcut(QKeySequence("Ctrl+D")); self.duplicate_action.triggered.connect(self.duplicate_selected_actor)
        self.rename_action = QAction("Rename Actor", self); self.rename_action.setShortcut(QKeySequence("F2")); self.rename_action.triggered.connect(self.rename_selected_actor)
        self.delete_action = QAction("Delete Actor", self); self.delete_action.setShortcut(QKeySequence("Delete")); self.delete_action.triggered.connect(self.delete_selected_actor)
        toolbar.addAction(self.save_action); toolbar.addSeparator(); toolbar.addAction(self.undo_action); toolbar.addAction(self.redo_action)
        add_button = QToolButton(self); add_button.setText("+ Add"); add_button.setPopupMode(QToolButton.InstantPopup); add_button.setMenu(self._actor_create_menu(add_button)); toolbar.addWidget(add_button)
        toolbar.addAction(self.focus_action); toolbar.addSeparator()
        tools = QActionGroup(self); tools.setExclusive(True); self.tool_actions: dict[str, QAction] = {}
        for key, label, shortcut in (("select", "Select", "Q"), ("translate", "Move", "W"), ("rotate", "Rotate", "E"), ("scale", "Scale", "R")):
            action = QAction(label, self); action.setCheckable(True); action.setShortcut(QKeySequence(shortcut)); action.triggered.connect(lambda _checked=False, value=key: self.set_transform_tool(value)); tools.addAction(action); toolbar.addAction(action); self.tool_actions[key] = action
        self.tool_actions["select"].setChecked(True); toolbar.addSeparator()
        self.coordinate_space = QComboBox(self); self.coordinate_space.setToolTip("Transform coordinate space")
        self.coordinate_space.addItem("World", "world"); self.coordinate_space.addItem("Local", "object"); self.coordinate_space.addItem("Parent", "parent")
        self.coordinate_space.currentIndexChanged.connect(self._coordinate_space_changed); toolbar.addWidget(self.coordinate_space)
        self.move_snap = self._snap_combo("Move Snap", (("Move: Off", 0.0), ("1 cm", 1.0), ("5 cm", 5.0), ("10 cm", 10.0), ("50 cm", 50.0), ("1 m", 100.0)))
        self.rotate_snap = self._snap_combo("Rotate Snap", (("Rotate: Off", 0.0), ("5°", 5.0), ("10°", 10.0), ("15°", 15.0), ("30°", 30.0), ("45°", 45.0)))
        self.scale_snap = self._snap_combo("Scale Snap", (("Scale: Off", 0.0), ("1%", 0.01), ("5%", 0.05), ("10%", 0.1), ("25%", 0.25)))
        for combo in (self.move_snap, self.rotate_snap, self.scale_snap): combo.currentIndexChanged.connect(self._transform_snap_changed); toolbar.addWidget(combo)
        self.view_mode = QComboBox(self); self.view_mode.setToolTip("Viewport shading mode")
        for label, value in (("Lit", "lit"), ("Unlit", "unlit"), ("Wireframe", "wireframe"), ("Resolved", "resolved")): self.view_mode.addItem(label, value)
        self.view_mode.currentIndexChanged.connect(self._view_mode_changed); toolbar.addWidget(self.view_mode); toolbar.addSeparator()
        self.edit_action = QAction("Edit", self); self.simulate_action = QAction("Simulate", self); self.play_action = QAction("Play", self); self.pause_action = QAction("Pause", self); self.step_action = QAction("Step", self); self.stop_action = QAction("Stop / Eject", self)
        modes = QActionGroup(self); modes.setExclusive(True)
        for action in (self.edit_action, self.simulate_action, self.play_action): action.setCheckable(True); modes.addAction(action)
        self.edit_action.setChecked(True)
        for action in (self.edit_action, self.simulate_action, self.play_action, self.pause_action, self.step_action, self.stop_action): toolbar.addAction(action)
        self.edit_action.triggered.connect(lambda: self.set_mode("edit")); self.simulate_action.triggered.connect(lambda: self.set_mode("simulate")); self.play_action.triggered.connect(lambda: self.set_mode("play")); self.pause_action.triggered.connect(self.pause); self.step_action.triggered.connect(self.step); self.stop_action.triggered.connect(lambda: self.set_mode("edit"))
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
        self.actor_details.apply_prefab.clicked.connect(self.apply_selected_prefab_overrides); self.actor_details.revert_prefab.clicked.connect(self.revert_selected_prefab_overrides)
        if outliner is not None and hasattr(outliner, "itemSelectionChanged"): outliner.itemSelectionChanged.connect(self.actor_details.refresh)
        internal_left = getattr(self.viewport, "scene_left_panel", None)
        if internal_left is not None: internal_left.hide()

        self.asset_browser = AssetBrowserWidget(self.project_root, database=self.database, registry=self.registry, parent=self)
        self.asset_browser.assetActivated.connect(self.open_asset); self.asset_browser.statusMessage.connect(self._status)
        self.content_dock = self._dock("Content Browser", self.asset_browser, Qt.BottomDockWidgetArea, "EngineContentBrowser")
        self.asset_editor = DedicatedAssetEditor(self.project_root, self.database, self.registry, parent=self)
        self.asset_editor.previewRequested.connect(self._preview_asset); self.asset_editor.locateRequested.connect(self.locate_asset)
        self.asset_editor.worldVisualizationRequested.connect(self._show_world_visualization)
        self.asset_editor_dock = self._dock("Asset Editor", self.asset_editor, Qt.RightDockWidgetArea, "EngineAssetEditor"); self.asset_editor_dock.hide()
        self.world_settings = WorldSettingsPanel(self); self.world_settings.changed.connect(self._world_settings_changed)
        self.world_settings_dock = self._dock("World Settings", self.world_settings, Qt.RightDockWidgetArea, "EngineWorldSettings"); self.world_settings_dock.hide()
        self.sequence_editor = SequenceEditorWidget(database=self.database, parent=self)
        self.sequence_editor.changed.connect(self._sequence_changed)
        self.sequence_dock = self._dock("Sequence Editor", self.sequence_editor, Qt.BottomDockWidgetArea, "EngineSequenceEditor"); self.sequence_dock.hide()
        self.output_log = QPlainTextEdit(self); self.output_log.setReadOnly(True); self.output_log.setMaximumBlockCount(4000)
        self.output_dock = self._dock("Output Log", self.output_log, Qt.BottomDockWidgetArea, "EngineOutputLog"); self.output_dock.hide()
        self.console_panel = EngineConsolePanel(self, self); self.console_dock = self._dock("Console", self.console_panel, Qt.BottomDockWidgetArea, "EngineConsole"); self.console_dock.hide()
        self.profiler_panel = RuntimeProfilerPanel(self); self.profiler_dock = self._dock("Profiler", self.profiler_panel, Qt.BottomDockWidgetArea, "EngineProfiler"); self.profiler_dock.hide()
        self.build_panel = BuildDeployPanel(self.project_root, self.database, self); self.build_panel.statusMessage.connect(self._status); self.build_panel.profileReady.connect(self._profile_ready)
        self.build_dock = self._dock("Build & Deploy", self.build_panel, Qt.RightDockWidgetArea, "EngineBuildDeploy"); self.build_dock.hide()
        self.world_production = WorldProductionPanel(self.project_root, self.database, self); self.world_production.statusMessage.connect(self._status); self.world_production.openRequested.connect(self.open_asset_id)
        self.world_production_dock = self._dock("World Production", self.world_production, Qt.LeftDockWidgetArea, "EngineWorldProduction"); self.world_production_dock.hide()
        self.launch_readiness = LaunchReadinessPanel(self.project_root, self.database, self); self.launch_readiness.statusMessage.connect(self._status)
        self.launch_readiness_dock = self._dock("Launch Readiness", self.launch_readiness, Qt.RightDockWidgetArea, "EngineLaunchReadiness"); self.launch_readiness_dock.hide()
        self.tabifyDockWidget(self.content_dock, self.sequence_dock); self.tabifyDockWidget(self.sequence_dock, self.output_dock); self.tabifyDockWidget(self.output_dock, self.console_dock); self.tabifyDockWidget(self.console_dock, self.profiler_dock); self.content_dock.raise_()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File"); open_level = file_menu.addAction("Open Level…"); open_level.triggered.connect(self.open_level_dialog); file_menu.addAction(self.save_action)
        edit_menu = self.menuBar().addMenu("Edit"); edit_menu.addAction(self.undo_action); edit_menu.addAction(self.redo_action); edit_menu.addSeparator(); edit_menu.addAction(self.duplicate_action); edit_menu.addAction(self.rename_action); edit_menu.addAction(self.delete_action); edit_menu.addSeparator(); edit_menu.addAction(self.focus_action)
        create_menu = self.menuBar().addMenu("Create"); actor_menu = create_menu.addMenu("Actor");
        for label, actor_type in (("Empty Actor", "empty"), ("Point Light", "point_light"), ("Directional Light", "directional_light"), ("Camera Actor", "camera"), ("Player Start", "player_start"), ("Trigger Volume", "trigger")): actor_menu.addAction(label, lambda _checked=False, value=actor_type: self.create_actor(value))
        create_menu.addSeparator(); self.asset_browser._populate_create_submenu(create_menu); create_menu.addSeparator(); create_menu.addAction("Import Assets…", self.asset_browser.import_assets); create_menu.addAction("New Folder…", self.asset_browser.create_folder)
        hierarchy_menu = self.menuBar().addMenu("Hierarchy"); hierarchy_menu.addAction("New Actor Folder…", self.create_actor_folder); hierarchy_menu.addAction("Move Selection to Folder…", self.move_selection_to_folder); hierarchy_menu.addSeparator(); hierarchy_menu.addAction("Parent Selection…", self.parent_selection); hierarchy_menu.addAction("Unparent Selection", lambda: self._parent_selection_to("")); hierarchy_menu.addSeparator(); hierarchy_menu.addAction("Offset Selection…", self.offset_selection)
        window_menu = self.menuBar().addMenu("Window")
        for dock in (self.world_outliner_dock, self.details_dock, self.world_settings_dock, self.world_production_dock, self.content_dock, self.asset_editor_dock, self.sequence_dock, self.output_dock, self.console_dock, self.profiler_dock, self.build_dock, self.launch_readiness_dock): window_menu.addAction(dock.toggleViewAction())
        tools_menu = self.menuBar().addMenu("Tools"); tools_menu.addAction("Project Settings", lambda: self.open_or_create_settings("tc.project_settings", "ProjectSettings")); tools_menu.addAction("World Settings", lambda: (self.world_settings_dock.show(), self.world_settings_dock.raise_())); tools_menu.addAction("World Production", lambda: (self.world_production.refresh(), self.world_production_dock.show(), self.world_production_dock.raise_())); tools_menu.addAction("Build & Deploy", lambda: (self.build_panel.refresh(), self.build_dock.show(), self.build_dock.raise_())); tools_menu.addAction("Launch Readiness", lambda: (self.launch_readiness.refresh(), self.launch_readiness_dock.show(), self.launch_readiness_dock.raise_())); tools_menu.addAction("Build Profile Asset", lambda: self.open_or_create_settings("tc.build_profile", "DesktopDevelopment")); tools_menu.addSeparator(); tools_menu.addAction("Console", lambda: (self.console_dock.show(), self.console_dock.raise_())); tools_menu.addAction("Profiler", lambda: (self.profiler_dock.show(), self.profiler_dock.raise_()))
        layout_menu = self.menuBar().addMenu("Layout"); layout_menu.addAction("Reset Editor Layout", self.reset_layout)

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
        if type_id == "tc.level": return self.load_level(path)
        if type_id == "tc.level_sequence":
            self._sequence_asset_id = str(asset_id); self.sequence_editor.load_settings(self.sequence_service.properties(asset_id)); self.sequence_dock.show(); self.sequence_dock.raise_(); self._status(f"Opened sequence {Path(path).name}"); return True
        opened = self.asset_editor.open_asset(asset_id)
        if opened: self.asset_editor_dock.show(); self.asset_editor_dock.raise_()
        return bool(opened)

    def open_asset_id(self, asset_id: str) -> bool:
        record = self.database.asset(asset_id)
        return self.open_asset(str(record.source_path), record.asset_type, record.asset_id) if record is not None else False

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

    def set_transform_tool(self, tool: str) -> None:
        value = str(tool); setter = getattr(self.viewport, "set_transform_tool", None)
        if callable(setter): setter(value)
        elif hasattr(self.viewport, "transform_mode"): self.viewport.transform_mode = value
        self._status(f"{value.title()} tool")

    def undo(self) -> None:
        handler = getattr(self.viewport, "undo_viewer_action", None)
        if callable(handler): handler(); self._status("Undo")
        else: self._status("Nothing in the active viewport can be undone.")

    def redo(self) -> None:
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
        handler = getattr(self.viewport, "duplicate_selected_level_actor", None); duplicated = bool(handler()) if callable(handler) else False
        self._status("Duplicated selected actor." if duplicated else "Select a native level actor to duplicate."); return duplicated

    def rename_selected_actor(self) -> bool:
        proxy = getattr(self.viewport, "_selected_scene_proxy", None)
        current = str(proxy.get("name") or "Actor") if proxy is not None and hasattr(proxy, "get") else "Actor"
        name, accepted = QInputDialog.getText(self, "Rename Actor", "Name", text=current)
        if not accepted: return False
        handler = getattr(self.viewport, "rename_selected_level_actor", None); renamed = bool(handler(name)) if callable(handler) else False
        self._status(f"Renamed actor to {name}." if renamed else "Select a native level actor to rename."); return renamed

    def delete_selected_actor(self) -> bool:
        handler = getattr(self.viewport, "delete_selected_level_actor", None); deleted = bool(handler()) if callable(handler) else False
        self._status("Deleted selected actor. Use Undo to restore it." if deleted else "Select a native level actor to delete."); return deleted

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
        if not asset_id: return False
        try: updated = self.prefab_service.apply_overrides(self.prefab_service.instantiate(asset_id, overrides=dict(instance.get("overrides") or {})))
        except (KeyError, ValueError, OSError) as exc: self._status(f"Could not apply Prefab overrides: {exc}"); return False
        entity["prefab_instance"].update(updated.to_dict()); getattr(self.viewport, "_scene_lifecycle").mark_dirty(); self.actor_details.refresh(); self._status("Applied instance overrides to the Prefab source."); return True

    def revert_selected_prefab_overrides(self) -> bool:
        entity = self.actor_details._entity(); instance = dict(entity.get("prefab_instance") or {}) if entity else {}; asset_id = str(instance.get("source_asset_id") or "")
        if not asset_id: return False
        try: updated = self.prefab_service.revert_overrides(self.prefab_service.instantiate(asset_id, overrides=dict(instance.get("overrides") or {})))
        except (KeyError, ValueError, OSError) as exc: self._status(f"Could not revert Prefab overrides: {exc}"); return False
        entity["prefab_instance"].update(updated.to_dict()); getattr(self.viewport, "_scene_lifecycle").mark_dirty(); self.actor_details.refresh(); self._status("Reverted instance overrides to the Prefab source."); return True

    def _coordinate_space_changed(self) -> None:
        value = str(self.coordinate_space.currentData() or "world")
        handler = getattr(self.viewport, "change_transform_orientation_mode", None)
        if callable(handler): handler("Object" if value == "object" else value.title())
        else: self.viewport.transform_orientation_mode = value
        self._status(f"Transform space: {'Local' if value == 'object' else value.title()}")

    def _transform_snap_changed(self) -> None:
        move = float(self.move_snap.currentData() or 0.0); rotate = float(self.rotate_snap.currentData() or 0.0); scale = float(self.scale_snap.currentData() or 0.0)
        handler = getattr(self.viewport, "configure_transform_snapping", None)
        if callable(handler): handler(translation=move, rotation=rotate, scale=scale)
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
        self._mode = value; self.modeChanged.emit(value)
        self.edit_action.setChecked(value == "edit"); self.simulate_action.setChecked(value == "simulate"); self.play_action.setChecked(value == "play")
        if value == "play": self.playRequested.emit(self.current_level_path)
        self._status({"edit": "Editing the authoritative level.", "simulate": "Simulating physics and effects in the editor viewport.", "play": "Playing an isolated runtime copy of the saved level."}[value])
        return True

    def pause(self) -> None:
        simulator = getattr(self.viewport, "set_simulation_playing", None)
        if callable(simulator): simulator(False)
        self._status("Simulation paused.")

    def step(self) -> None:
        stepper = getattr(self.viewport, "step_simulation", None) or getattr(self.viewport, "advance_simulation", None)
        if callable(stepper):
            try: stepper()
            except TypeError: stepper(1.0 / 60.0)
        self._status("Advanced one simulation frame.")

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
        if self._sequence_asset_id: self.status_label.setText("Sequence has unsaved changes • Save in the asset editor")

    def _world_settings_changed(self) -> None:
        self.viewport._engine_world_settings = self.world_settings.settings()
        lifecycle = getattr(self.viewport, "_scene_lifecycle", None)
        if lifecycle is not None and hasattr(lifecycle, "mark_dirty"): lifecycle.mark_dirty()
        self.status_label.setText("World Settings changed • Save All to update the level")

    def _status(self, message: str) -> None:
        text = str(message or ""); self.status_label.setText(text); self.output_log.appendPlainText(text); self.statusMessage.emit(text)

    def _profile_ready(self, path: str) -> None:
        self.profiler_panel.watch(path); self.profiler_dock.show(); self.profiler_dock.raise_()

    def reset_layout(self) -> None:
        for dock in (self.world_outliner_dock, self.details_dock, self.content_dock): dock.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, self.world_outliner_dock); self.addDockWidget(Qt.RightDockWidgetArea, self.details_dock); self.addDockWidget(Qt.BottomDockWidgetArea, self.content_dock)

    def save_layout_state(self) -> bytes:
        return bytes(self.saveState())

    def restore_layout_state(self, state: bytes | QByteArray) -> bool:
        return self.restoreState(QByteArray(state))
