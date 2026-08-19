"""Preset-aware live properties inspector for Tech Connector FX systems."""

from __future__ import annotations

import json
import random
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.runtime.tc_effect_system_service import QUALITY_PROFILES, effect_preset_names
from tech_connector.game_engine.runtime.tc_fx_workflow_service import FX_SOLVER_PROFILES
from tech_connector.game_engine.runtime.tc_simulation_ir_service import simulation_backend_statuses
from tech_connector.ui.design_system import component_stylesheet, set_status_state, set_ui_role
from tech_connector.ui.icons import configure_button


def _display_name(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


class FxPropertiesDialog(QDialog):
    """Edit the active modular effect without hiding its advanced controls."""

    create_requested = Signal(str, str, int)
    parameter_changed = Signal(str, object)
    renderer_changed = Signal(str, str)
    solo_emitter_requested = Signal(str, bool)
    emitter_manipulation_requested = Signal(str, bool, bool)
    renderer_budget_changed = Signal(object)
    renderer_stats_requested = Signal()
    preview_toggled = Signal(bool)
    bake_requested = Signal()
    reset_requested = Signal()

    def __init__(self, effect_system: Any = None, parent=None):
        super().__init__(parent)
        self.effect_system = effect_system
        self._updating = False
        self._target_upload_ms = 4.0
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(1000)
        self.telemetry_timer.timeout.connect(self.renderer_stats_requested)
        self.setWindowTitle("FX Properties")
        self.setMinimumSize(620, 640)
        self.resize(700, 760)
        self.setStyleSheet(component_stylesheet())
        self._build_ui()
        self.set_effect_system(effect_system)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("FX Properties")
        set_ui_role(title, "pageTitle")
        root.addWidget(title)
        subtitle = QLabel("Create an effect, tune its emitters live, then preview or bake the active timeline range.")
        subtitle.setWordWrap(True)
        set_ui_role(subtitle, "muted")
        root.addWidget(subtitle)

        self.property_tabs = QTabWidget(self)
        root.addWidget(self.property_tabs, 1)

        creation_panel = QFrame(self)
        set_ui_role(creation_panel, "panel")
        creation_form = QFormLayout(creation_panel)
        creation_form.setContentsMargins(12, 12, 12, 12)
        creation_form.setSpacing(8)

        self.preset_combo = QComboBox(creation_panel)
        for preset in effect_preset_names():
            self.preset_combo.addItem(_display_name(preset), preset)
        creation_form.addRow("Effect", self.preset_combo)

        self.quality_combo = QComboBox(creation_panel)
        quality_order = ("realtime", "high", "cinematic", "medium", "low", "mobile", "toony", "stylized", "retro")
        for quality in quality_order:
            profile = QUALITY_PROFILES[quality]
            self.quality_combo.addItem(
                f"{profile.name} · {profile.max_particles:,} particles · {profile.target_frame_ms:g} ms target",
                quality,
            )
        self.quality_combo.currentIndexChanged.connect(self._quality_changed)
        creation_form.addRow("Quality", self.quality_combo)
        self.quality_details = QLabel(creation_panel)
        self.quality_details.setWordWrap(True)
        set_ui_role(self.quality_details, "muted")
        creation_form.addRow("", self.quality_details)

        seed_row = QWidget(creation_panel)
        seed_layout = QHBoxLayout(seed_row)
        seed_layout.setContentsMargins(0, 0, 0, 0)
        seed_layout.setSpacing(6)
        self.seed_spin = QSpinBox(seed_row)
        self.seed_spin.setRange(0, 2_147_483_647)
        self.seed_spin.setValue(1)
        self.seed_spin.editingFinished.connect(self._seed_changed)
        seed_layout.addWidget(self.seed_spin, 1)
        randomize_btn = QPushButton("Randomize", seed_row)
        configure_button(randomize_btn, "sparkles", text="Randomize", tooltip="Choose a new deterministic variation seed.")
        randomize_btn.clicked.connect(lambda: self.seed_spin.setValue(random.randint(1, 2_147_483_647)))
        seed_layout.addWidget(randomize_btn)
        creation_form.addRow("Variation seed", seed_row)

        create_btn = QPushButton("Create effect", creation_panel)
        configure_button(create_btn, "sparkles", text="Create / Recreate", tooltip="Create this preset with the selected quality and seed.", role="primary")
        create_btn.clicked.connect(self._emit_create)
        creation_form.addRow("", create_btn)
        self.property_tabs.addTab(creation_panel, "Create")

        self.active_summary = QLabel("No active FX system")
        self.active_summary.setWordWrap(True)
        set_ui_role(self.active_summary, "status")
        root.addWidget(self.active_summary)

        emitter_panel = QFrame(self)
        set_ui_role(emitter_panel, "panel")
        emitter_form = QFormLayout(emitter_panel)
        emitter_form.setContentsMargins(12, 12, 12, 12)
        emitter_form.setSpacing(8)

        self.emitter_combo = QComboBox(emitter_panel)
        self.emitter_combo.currentIndexChanged.connect(self._emitter_selection_changed)
        emitter_form.addRow("Emitter", self.emitter_combo)

        self.emitter_enabled = QCheckBox("Enabled", emitter_panel)
        self.emitter_enabled.toggled.connect(lambda value: self._emit_emitter_property("enabled", bool(value)))
        emitter_form.addRow("State", self.emitter_enabled)

        self.spawn_rate = QDoubleSpinBox(emitter_panel)
        self.spawn_rate.setRange(0.0, 1_000_000.0)
        self.spawn_rate.setDecimals(2)
        self.spawn_rate.setSuffix(" / sec")
        self.spawn_rate.valueChanged.connect(lambda value: self._emit_emitter_property("spawn_rate", float(value)))
        emitter_form.addRow("Spawn rate", self.spawn_rate)

        self.burst_count = QSpinBox(emitter_panel)
        self.burst_count.setRange(0, 1_000_000)
        self.burst_count.valueChanged.connect(lambda value: self._emit_emitter_property("burst_count", int(value)))
        emitter_form.addRow("Burst", self.burst_count)

        self.emitter_particle_cap = QSpinBox(emitter_panel)
        self.emitter_particle_cap.setRange(0, 100_000)
        self.emitter_particle_cap.setSingleStep(500)
        self.emitter_particle_cap.setSpecialValueText("Use quality limit")
        self.emitter_particle_cap.valueChanged.connect(
            lambda value: self._emit_emitter_property("max_particles", int(value))
        )
        emitter_form.addRow("Emitter cap", self.emitter_particle_cap)

        self.update_rate_divisor = QSpinBox(emitter_panel)
        self.update_rate_divisor.setRange(1, 8)
        self.update_rate_divisor.setValue(1)
        self.update_rate_divisor.setSuffix("× frame interval")
        self.update_rate_divisor.valueChanged.connect(
            lambda value: self._emit_emitter_property("update_rate_divisor", int(value))
        )
        emitter_form.addRow("Update rate", self.update_rate_divisor)

        self.duration = QDoubleSpinBox(emitter_panel)
        self.duration.setRange(0.01, 86_400.0)
        self.duration.setDecimals(2)
        self.duration.setSuffix(" sec")
        self.duration.valueChanged.connect(lambda value: self._emit_emitter_property("duration", float(value)))
        emitter_form.addRow("Duration", self.duration)

        self.looping = QCheckBox("Loop continuously", emitter_panel)
        self.looping.toggled.connect(lambda value: self._emit_emitter_property("looping", bool(value)))
        emitter_form.addRow("Playback", self.looping)

        self.renderer_combo = QComboBox(emitter_panel)
        for label, renderer_type in (
            ("Sprite", "sprite"), ("Volume sprite", "volume_sprite"), ("Ribbon", "ribbon"),
            ("Beam", "beam"), ("Line", "line"), ("Mesh", "mesh"), ("Metaball", "metaball"),
            ("Decal", "decal"), ("Volume", "volume"),
        ):
            self.renderer_combo.addItem(label, renderer_type)
        self.renderer_combo.currentIndexChanged.connect(self._renderer_changed)
        emitter_form.addRow("Renderer", self.renderer_combo)

        self.solo_btn = QPushButton("Solo emitter", emitter_panel)
        self.solo_btn.setCheckable(True)
        configure_button(self.solo_btn, "layers", text="Solo emitter", tooltip="Temporarily mute every other emitter for focused tuning.")
        self.solo_btn.toggled.connect(self._solo_changed)
        emitter_form.addRow("Isolation", self.solo_btn)

        self.manipulate_emitter_btn = QPushButton("Manipulate in viewport", emitter_panel)
        self.manipulate_emitter_btn.setCheckable(True)
        configure_button(
            self.manipulate_emitter_btn, "move", text="Manipulate in viewport",
            tooltip="Activate this emitter, start preview, then drag its cyan viewport handle.", role="primary",
        )
        self.manipulate_emitter_btn.toggled.connect(self._toggle_emitter_manipulation)
        emitter_form.addRow("Interaction", self.manipulate_emitter_btn)

        self.carry_emitter_particles = QCheckBox("Move existing particles and trails", emitter_panel)
        self.carry_emitter_particles.setToolTip(
            "Leave off to paint a natural trail while dragging; enable to carry the whole emitted effect."
        )
        self.carry_emitter_particles.toggled.connect(self._manipulation_carry_changed)
        emitter_form.addRow("Drag behavior", self.carry_emitter_particles)
        self.property_tabs.addTab(emitter_panel, "Emitter")

        performance_title = QLabel("Performance budget")
        set_ui_role(performance_title, "sectionTitle")
        root.addWidget(performance_title)
        performance_panel = QFrame(self)
        set_ui_role(performance_panel, "panel")
        performance_form = QFormLayout(performance_panel)
        performance_form.setContentsMargins(12, 12, 12, 12)
        performance_form.setSpacing(8)

        self.performance_preset = QComboBox(performance_panel)
        self.performance_preset.addItem("Balanced desktop", "balanced")
        self.performance_preset.addItem("Cinematic", "cinematic")
        self.performance_preset.addItem("Fast realtime", "fast")
        self.performance_preset.addItem("Competitive / low latency", "competitive")
        self.performance_preset.addItem("Mobile", "mobile")
        self.performance_preset.currentIndexChanged.connect(self._apply_performance_preset)
        performance_form.addRow("Preset", self.performance_preset)

        self.adaptive_budget = QCheckBox("Adapt particle counts to hold the frame budget", performance_panel)
        self.adaptive_budget.setChecked(True)
        performance_form.addRow("Adaptive", self.adaptive_budget)

        self.upload_budget_ms = QDoubleSpinBox(performance_panel)
        self.upload_budget_ms.setRange(0.25, 33.0)
        self.upload_budget_ms.setDecimals(2)
        self.upload_budget_ms.setValue(4.0)
        self.upload_budget_ms.setSuffix(" ms")
        performance_form.addRow("GPU upload target", self.upload_budget_ms)

        self.particle_budget = QSpinBox(performance_panel)
        self.particle_budget.setRange(100, 100_000)
        self.particle_budget.setSingleStep(1000)
        self.particle_budget.setValue(20_000)
        self.particle_budget.setSuffix(" / stream")
        performance_form.addRow("Particle budget", self.particle_budget)

        self.mesh_budget = QSpinBox(performance_panel)
        self.mesh_budget.setRange(100, 250_000)
        self.mesh_budget.setSingleStep(1000)
        self.mesh_budget.setValue(50_000)
        self.mesh_budget.setSuffix(" instances")
        performance_form.addRow("Mesh budget", self.mesh_budget)

        self.cull_distance = QDoubleSpinBox(performance_panel)
        self.cull_distance.setRange(0.0, 100_000.0)
        self.cull_distance.setDecimals(1)
        self.cull_distance.setValue(250.0)
        self.cull_distance.setSuffix(" scene units")
        self.cull_distance.setSpecialValueText("No distance culling")
        performance_form.addRow("Cull distance", self.cull_distance)

        budget_actions = QWidget(performance_panel)
        budget_actions_layout = QHBoxLayout(budget_actions)
        budget_actions_layout.setContentsMargins(0, 0, 0, 0)
        budget_actions_layout.setSpacing(6)
        apply_budget_btn = QPushButton("Apply budget", budget_actions)
        configure_button(apply_budget_btn, "check", text="Apply budget", tooltip="Apply these limits to the live GPU renderer.", role="primary")
        apply_budget_btn.clicked.connect(self._emit_renderer_budget)
        budget_actions_layout.addWidget(apply_budget_btn)
        refresh_stats_btn = QPushButton("Refresh stats", budget_actions)
        configure_button(refresh_stats_btn, "refresh", text="Refresh stats", tooltip="Read current particle, draw-call, and upload telemetry.")
        refresh_stats_btn.clicked.connect(self.renderer_stats_requested)
        budget_actions_layout.addWidget(refresh_stats_btn)
        budget_actions_layout.addStretch(1)
        performance_form.addRow("", budget_actions)

        self.budget_pressure = QProgressBar(performance_panel)
        self.budget_pressure.setRange(0, 100)
        self.budget_pressure.setValue(0)
        self.budget_pressure.setFormat("Waiting for renderer telemetry")
        performance_form.addRow("Budget pressure", self.budget_pressure)
        self.telemetry_label = QLabel("Preview the effect to collect live renderer statistics.", performance_panel)
        self.telemetry_label.setWordWrap(True)
        set_ui_role(self.telemetry_label, "muted")
        performance_form.addRow("", self.telemetry_label)
        self.property_tabs.addTab(performance_panel, "Performance")

        advanced_panel = QWidget(self)
        advanced_layout = QVBoxLayout(advanced_panel)
        advanced_layout.setContentsMargins(12, 12, 12, 12)
        advanced_layout.setSpacing(8)
        advanced_title = QLabel("Advanced module properties")
        set_ui_role(advanced_title, "sectionTitle")
        advanced_layout.addWidget(advanced_title)
        advanced_help = QLabel("Double-click a value to edit it. Lists and vectors use JSON, for example [0, 1, 0].")
        advanced_help.setWordWrap(True)
        set_ui_role(advanced_help, "muted")
        advanced_layout.addWidget(advanced_help)

        self.module_tree = QTreeWidget(self)
        self.module_tree.setColumnCount(3)
        self.module_tree.setHeaderLabels(["Module", "Property", "Value"])
        self.module_tree.setAlternatingRowColors(True)
        self.module_tree.setRootIsDecorated(False)
        self.module_tree.itemChanged.connect(self._module_value_changed)
        advanced_layout.addWidget(self.module_tree, 1)
        self.property_tabs.addTab(advanced_panel, "Advanced")

        workflow_panel = QFrame(self)
        set_ui_role(workflow_panel, "panel")
        workflow_layout = QVBoxLayout(workflow_panel)
        workflow_layout.setContentsMargins(12, 12, 12, 12)
        workflow_layout.setSpacing(8)
        workflow_form = QFormLayout()

        self.solver_profile_combo = QComboBox(workflow_panel)
        for profile in FX_SOLVER_PROFILES.values():
            self.solver_profile_combo.addItem(profile.name, profile.profile_id)
        self.solver_profile_combo.currentIndexChanged.connect(self._solver_profile_changed)
        workflow_form.addRow("Solver", self.solver_profile_combo)

        self.backend_combo = QComboBox(workflow_panel)
        self.backend_combo.addItem("Automatic", "auto")
        for status in simulation_backend_statuses():
            device = str(status["execution_device"]).upper()
            state = "ready" if status["available"] else "fallback"
            self.backend_combo.addItem(
                f"{_display_name(status['backend_id'])} · {device} · {state}", status["backend_id"]
            )
        self.backend_combo.currentIndexChanged.connect(self._backend_preference_changed)
        workflow_form.addRow("Execution", self.backend_combo)
        self.initialize_gpu_btn = QPushButton("Initialize GPU compute", workflow_panel)
        configure_button(
            self.initialize_gpu_btn, "sparkles", text="Initialize GPU compute",
            tooltip="Probe and activate the qualified native D3D11 compute executor.",
        )
        self.initialize_gpu_btn.clicked.connect(self._initialize_gpu_backend)
        workflow_form.addRow("GPU", self.initialize_gpu_btn)
        workflow_layout.addLayout(workflow_form)

        self.backend_status = QLabel(workflow_panel)
        self.backend_status.setWordWrap(True)
        set_ui_role(self.backend_status, "status")
        workflow_layout.addWidget(self.backend_status)

        self.workflow_tree = QTreeWidget(workflow_panel)
        self.workflow_tree.setColumnCount(3)
        self.workflow_tree.setHeaderLabels(["Stage", "State", "Purpose"])
        self.workflow_tree.setRootIsDecorated(False)
        self.workflow_tree.setAlternatingRowColors(True)
        workflow_layout.addWidget(self.workflow_tree, 1)

        controls_title = QLabel("Artist controls", workflow_panel)
        set_ui_role(controls_title, "sectionTitle")
        workflow_layout.addWidget(controls_title)
        self.solver_controls_tree = QTreeWidget(workflow_panel)
        self.solver_controls_tree.setColumnCount(3)
        self.solver_controls_tree.setHeaderLabels(["Property", "Value", "Purpose"])
        self.solver_controls_tree.setRootIsDecorated(False)
        self.solver_controls_tree.setAlternatingRowColors(True)
        self.solver_controls_tree.itemChanged.connect(self._solver_control_changed)
        workflow_layout.addWidget(self.solver_controls_tree, 1)

        workflow_help = QLabel(
            "Simulation, secondary FX, surfacing, and caching stay separate so expensive stages can be previewed, "
            "checkpointed, or rebuilt independently.", workflow_panel
        )
        workflow_help.setWordWrap(True)
        set_ui_role(workflow_help, "muted")
        workflow_layout.addWidget(workflow_help)
        self.property_tabs.addTab(workflow_panel, "Pipeline")

        actions = QHBoxLayout()
        self.preview_btn = QPushButton("Preview", self)
        self.preview_btn.setCheckable(True)
        configure_button(self.preview_btn, "play", text="Preview", tooltip="Play or pause the live effect preview.", role="primary")
        self.preview_btn.toggled.connect(self._preview_changed)
        actions.addWidget(self.preview_btn)

        reset_btn = QPushButton("Reset", self)
        configure_button(reset_btn, "refresh", text="Reset", tooltip="Reset the active simulation to its initial state.")
        reset_btn.clicked.connect(self.reset_requested)
        actions.addWidget(reset_btn)

        bake_btn = QPushButton("Bake", self)
        configure_button(bake_btn, "save", text="Bake range", tooltip="Bake the active effect across the timeline range.")
        bake_btn.clicked.connect(self.bake_requested)
        actions.addWidget(bake_btn)
        actions.addStretch(1)

        close_btn = QPushButton("Close", self)
        configure_button(close_btn, "close", text="Close", tooltip="Close FX properties.")
        close_btn.clicked.connect(self.close)
        actions.addWidget(close_btn)
        root.addLayout(actions)
        self._update_quality_details()

    def set_effect_system(self, effect_system: Any) -> None:
        self.effect_system = effect_system
        self._updating = True
        try:
            self.emitter_combo.clear()
            if effect_system is None:
                self.active_summary.setText("No active FX system · choose a preset above to begin")
                self.active_summary.setProperty("statusState", "")
                set_ui_role(self.active_summary, "status")
                self.manipulate_emitter_btn.setChecked(False)
                self.manipulate_emitter_btn.setText("Manipulate in viewport")
                self._manipulated_emitter_id = ""
                self._set_editor_enabled(False)
                self.module_tree.clear()
                return
            set_status_state(self.active_summary, "ok", (
                f"{effect_system.name} · {len(effect_system.emitters)} emitters · "
                f"{_display_name(effect_system.quality)} quality · seed {effect_system.deterministic_seed}"
            ))
            quality_index = self.quality_combo.findData(str(effect_system.quality))
            if quality_index >= 0:
                self.quality_combo.setCurrentIndex(quality_index)
            self.seed_spin.setValue(int(effect_system.deterministic_seed))
            for emitter in effect_system.emitters:
                self.emitter_combo.addItem(emitter.name, emitter.emitter_id)
            self._set_editor_enabled(bool(effect_system.emitters))
        finally:
            self._updating = False
        self._load_selected_emitter()
        self._load_workflow()

    def set_previewing(self, previewing: bool) -> None:
        self.preview_btn.blockSignals(True)
        self.preview_btn.setChecked(bool(previewing))
        self.preview_btn.setText("Pause" if previewing else "Preview")
        self.preview_btn.blockSignals(False)
        if previewing:
            self.telemetry_timer.start()
        else:
            self.telemetry_timer.stop()

    def _set_editor_enabled(self, enabled: bool) -> None:
        for control in (
            self.emitter_combo,
            self.emitter_enabled,
            self.spawn_rate,
            self.burst_count,
            self.emitter_particle_cap,
            self.update_rate_divisor,
            self.duration,
            self.looping,
            self.renderer_combo,
            self.solo_btn,
            self.manipulate_emitter_btn,
            self.carry_emitter_particles,
            self.module_tree,
            self.solver_profile_combo,
            self.backend_combo,
            self.initialize_gpu_btn,
            self.workflow_tree,
            self.solver_controls_tree,
            self.preview_btn,
        ):
            control.setEnabled(enabled)

    def _load_workflow(self) -> None:
        self.workflow_tree.clear()
        self.solver_controls_tree.clear()
        if self.effect_system is None:
            set_status_state(self.backend_status, "warning", "Create an effect to inspect its solver pipeline.")
            return
        self._updating = True
        try:
            solver_id = str(getattr(self.effect_system, "solver_profile", "particle_realtime"))
            solver_index = self.solver_profile_combo.findData(solver_id)
            if solver_index >= 0:
                self.solver_profile_combo.setCurrentIndex(solver_index)
            backend = str(getattr(self.effect_system, "backend_preference", "auto"))
            backend_index = self.backend_combo.findData(backend)
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            workflow = dict(getattr(self.effect_system, "workflow", {}) or {})
            for stage in workflow.get("stages", []):
                detail = str(stage.get("detail", ""))
                if stage.get("optional"):
                    detail = f"Optional · {detail}"
                if stage.get("cacheable"):
                    detail = f"Cacheable · {detail}"
                self.workflow_tree.addTopLevelItem(QTreeWidgetItem([
                    str(stage.get("label", stage.get("stage_id", "Stage"))),
                    _display_name(str(stage.get("state", "ready"))),
                    detail,
                ]))
            self.workflow_tree.resizeColumnToContents(0)
            self.workflow_tree.resizeColumnToContents(1)
            profile = FX_SOLVER_PROFILES.get(solver_id)
            parameters = dict(getattr(self.effect_system, "parameters", {}) or {})
            if profile is not None:
                for control in profile.controls:
                    parameter_name = f"solver_{control.control_id}"
                    value = parameters.get(parameter_name, control.default)
                    label = f"{control.label} ({control.unit})" if control.unit else control.label
                    item = QTreeWidgetItem([label, self._format_value(value), control.help_text])
                    item.setData(1, Qt.UserRole, f"parameters.{parameter_name}")
                    item.setData(1, Qt.UserRole + 1, value)
                    item.setData(1, Qt.UserRole + 2, (control.minimum, control.maximum))
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.solver_controls_tree.addTopLevelItem(item)
            self.solver_controls_tree.resizeColumnToContents(0)
            self.solver_controls_tree.resizeColumnToContents(1)
            self._update_backend_status()
        finally:
            self._updating = False

    def _update_backend_status(self) -> None:
        requested = str(self.backend_combo.currentData() or "auto")
        statuses = {status["backend_id"]: status for status in simulation_backend_statuses()}
        if requested == "auto":
            gpu = statuses.get("gpu_compute", {})
            if gpu.get("available"):
                set_status_state(self.backend_status, "ok", "Automatic · GPU compute is installed and eligible.")
            else:
                set_status_state(
                    self.backend_status, "warning",
                    "Automatic · deterministic CPU preview is active; GPU compute is not installed. "
                    "The compiled workflow remains portable and the fallback is explicit.",
                )
            return
        status = statuses.get(requested, {})
        if status.get("available"):
            set_status_state(
                self.backend_status, "ok",
                f"{_display_name(requested)} is ready on {str(status.get('execution_device', 'cpu')).upper()}.",
            )
        else:
            set_status_state(
                self.backend_status, "warning",
                f"{_display_name(requested)} is unavailable. Preview will fall back to Reference CPU. "
                f"{status.get('reason', '')}",
            )

    def _refresh_backend_options(self) -> None:
        selected = str(self.backend_combo.currentData() or "auto")
        statuses = {status["backend_id"]: status for status in simulation_backend_statuses()}
        for index in range(1, self.backend_combo.count()):
            backend_id = str(self.backend_combo.itemData(index))
            status = statuses.get(backend_id, {})
            device = str(status.get("execution_device", "cpu")).upper()
            state = "ready" if status.get("available") else "fallback"
            self.backend_combo.setItemText(index, f"{_display_name(backend_id)} · {device} · {state}")
        selected_index = self.backend_combo.findData(selected)
        if selected_index >= 0:
            self.backend_combo.setCurrentIndex(selected_index)

    def _initialize_gpu_backend(self) -> None:
        try:
            from tech_connector.game_engine.runtime.tc_gpu_compute_service import install_native_gpu_backend
            service = install_native_gpu_backend()
        except Exception as error:
            set_status_state(self.backend_status, "error", f"GPU compute initialization failed · {error}")
            return
        self._refresh_backend_options()
        gpu_index = self.backend_combo.findData("gpu_compute")
        if gpu_index >= 0:
            self.backend_combo.setCurrentIndex(gpu_index)
        set_status_state(
            self.backend_status, "ok",
            f"GPU compute ready · {service.device_description} · qualified particle integration stage.",
        )

    def _solver_profile_changed(self) -> None:
        if self._updating or self.effect_system is None:
            return
        self.parameter_changed.emit("solver_profile", str(self.solver_profile_combo.currentData()))
        QTimer.singleShot(0, self._load_workflow)

    def _backend_preference_changed(self) -> None:
        self._update_backend_status()
        if self._updating or self.effect_system is None:
            return
        self.parameter_changed.emit("backend_preference", str(self.backend_combo.currentData()))
        QTimer.singleShot(0, self._load_workflow)

    def _solver_control_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 1:
            return
        path = str(item.data(1, Qt.UserRole) or "")
        original = item.data(1, Qt.UserRole + 1)
        limits = item.data(1, Qt.UserRole + 2) or (float("-inf"), float("inf"))
        try:
            value = float(item.text(1))
            value = max(float(limits[0]), min(float(limits[1]), value))
        except (TypeError, ValueError):
            self._updating = True
            item.setText(1, self._format_value(original))
            self._updating = False
            return
        item.setData(1, Qt.UserRole + 1, value)
        self._updating = True
        item.setText(1, self._format_value(value))
        self._updating = False
        self.parameter_changed.emit(path, value)

    def _emit_create(self) -> None:
        self.create_requested.emit(
            str(self.preset_combo.currentData()),
            str(self.quality_combo.currentData()),
            int(self.seed_spin.value()),
        )

    def _quality_changed(self) -> None:
        self._update_quality_details()
        if not self._updating and self.effect_system is not None:
            self.parameter_changed.emit("quality", str(self.quality_combo.currentData()))

    def _seed_changed(self) -> None:
        if not self._updating and self.effect_system is not None:
            self.parameter_changed.emit("deterministic_seed", int(self.seed_spin.value()))

    def _update_quality_details(self) -> None:
        quality = str(self.quality_combo.currentData() or "high")
        profile = QUALITY_PROFILES.get(quality, QUALITY_PROFILES["high"])
        features = []
        features.append("dynamic lights" if profile.enable_lights else "lights disabled")
        features.append("volumes" if profile.enable_volumes else "volumes disabled")
        features.append(f"{profile.solver_substeps} solver step{'s' if profile.solver_substeps != 1 else ''}")
        self.quality_details.setText(
            f"{profile.spawn_scale:g}× spawn density · {profile.render_scale:g}× render scale · "
            f"{', '.join(features)} · {profile.art_style} style"
        )

    def _selected_emitter(self) -> Any:
        if self.effect_system is None:
            return None
        emitter_id = str(self.emitter_combo.currentData() or "")
        return next((emitter for emitter in self.effect_system.emitters if emitter.emitter_id == emitter_id), None)

    def _load_selected_emitter(self) -> None:
        if self._updating:
            return
        emitter = self._selected_emitter()
        self._updating = True
        try:
            self.module_tree.clear()
            if emitter is None:
                self.renderer_label.setText("—")
                return
            self.emitter_enabled.setChecked(bool(emitter.enabled))
            self.spawn_rate.setValue(float(emitter.spawn_rate))
            self.burst_count.setValue(int(emitter.burst_count))
            self.emitter_particle_cap.setValue(int(getattr(emitter, "max_particles", 0)))
            self.update_rate_divisor.setValue(max(1, int(getattr(emitter, "update_rate_divisor", 1))))
            self.duration.setValue(float(emitter.duration))
            self.looping.setChecked(bool(emitter.looping))
            renderer = dict(emitter.renderer or {})
            renderer_type = str(renderer.get("type") or "sprite")
            renderer_index = self.renderer_combo.findData(renderer_type)
            if renderer_index < 0:
                self.renderer_combo.addItem(_display_name(renderer_type), renderer_type)
                renderer_index = self.renderer_combo.count() - 1
            self.renderer_combo.setCurrentIndex(renderer_index)
            self.solo_btn.setChecked(False)
            for module in emitter.modules:
                for name, value in module.parameters.items():
                    item = QTreeWidgetItem([_display_name(module.module_type), _display_name(name), self._format_value(value)])
                    item.setData(2, Qt.UserRole, f"emitter.{emitter.emitter_id}.module.{module.module_type}.{name}")
                    item.setData(2, Qt.UserRole + 1, value)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self.module_tree.addTopLevelItem(item)
            self.module_tree.resizeColumnToContents(0)
            self.module_tree.resizeColumnToContents(1)
        finally:
            self._updating = False

    def _emitter_selection_changed(self) -> None:
        if self._updating:
            return
        previous = str(getattr(self, "_manipulated_emitter_id", "") or "")
        self._load_selected_emitter()
        if not self.manipulate_emitter_btn.isChecked():
            return
        emitter = self._selected_emitter()
        current = str(getattr(emitter, "emitter_id", "") or "")
        if previous and previous != current:
            self.emitter_manipulation_requested.emit(previous, False, False)
        if current:
            self._manipulated_emitter_id = current
            self.emitter_manipulation_requested.emit(
                current, True, bool(self.carry_emitter_particles.isChecked())
            )

    def _toggle_emitter_manipulation(self, active: bool) -> None:
        if self._updating:
            return
        emitter = self._selected_emitter()
        emitter_id = str(getattr(emitter, "emitter_id", "") or "")
        if active and emitter_id:
            self._manipulated_emitter_id = emitter_id
            self.manipulate_emitter_btn.setText("Stop manipulating")
            self.emitter_manipulation_requested.emit(
                emitter_id, True, bool(self.carry_emitter_particles.isChecked())
            )
            return
        emitter_id = str(getattr(self, "_manipulated_emitter_id", "") or emitter_id)
        self._manipulated_emitter_id = ""
        self.manipulate_emitter_btn.setText("Manipulate in viewport")
        if emitter_id:
            self.emitter_manipulation_requested.emit(emitter_id, False, False)

    def _manipulation_carry_changed(self, carry: bool) -> None:
        if self._updating or not self.manipulate_emitter_btn.isChecked():
            return
        emitter_id = str(getattr(self, "_manipulated_emitter_id", "") or "")
        if emitter_id:
            self.emitter_manipulation_requested.emit(emitter_id, True, bool(carry))

    def _emit_emitter_property(self, name: str, value: Any) -> None:
        if self._updating:
            return
        emitter_id = str(self.emitter_combo.currentData() or "")
        if emitter_id:
            self.parameter_changed.emit(f"emitter.{emitter_id}.{name}", value)

    def _renderer_changed(self) -> None:
        if self._updating:
            return
        emitter_id = str(self.emitter_combo.currentData() or "")
        renderer_type = str(self.renderer_combo.currentData() or "sprite")
        if emitter_id:
            self.renderer_changed.emit(emitter_id, renderer_type)

    def _solo_changed(self, soloed: bool) -> None:
        if self._updating:
            return
        emitter_id = str(self.emitter_combo.currentData() or "")
        if emitter_id:
            self.solo_emitter_requested.emit(emitter_id, bool(soloed))

    def _emit_renderer_budget(self) -> None:
        self._target_upload_ms = float(self.upload_budget_ms.value())
        budget = {
            "target_upload_ms": self._target_upload_ms,
            "particle_budget": int(self.particle_budget.value()),
            "mesh_instance_budget": int(self.mesh_budget.value()),
            "cull_distance": float(self.cull_distance.value()),
            "adaptive": bool(self.adaptive_budget.isChecked()),
        }
        self.renderer_budget_changed.emit(budget)
        if self.effect_system is not None:
            self.parameter_changed.emit("performance_contract.target_frame_ms", self._target_upload_ms)
            self.parameter_changed.emit("performance_contract.maximum_particles", budget["particle_budget"])
            self.parameter_changed.emit("performance_contract.adaptive", budget["adaptive"])

    def _apply_performance_preset(self) -> None:
        presets = {
            "balanced": (4.0, 20_000, 50_000, 250.0, True),
            "cinematic": (8.0, 75_000, 150_000, 1000.0, True),
            "fast": (2.5, 10_000, 24_000, 180.0, True),
            "competitive": (1.5, 5_000, 12_000, 120.0, True),
            "mobile": (1.0, 3_500, 8_000, 80.0, True),
        }
        target, particles, meshes, distance, adaptive = presets[str(self.performance_preset.currentData() or "balanced")]
        self.upload_budget_ms.setValue(target)
        self.particle_budget.setValue(particles)
        self.mesh_budget.setValue(meshes)
        self.cull_distance.setValue(distance)
        self.adaptive_budget.setChecked(adaptive)

    def set_performance_budget(self, budget: dict[str, Any]) -> None:
        values = dict(budget or {})
        self._target_upload_ms = float(values.get("target_upload_ms", 4.0))
        self.upload_budget_ms.setValue(self._target_upload_ms)
        self.particle_budget.setValue(int(values.get("particle_budget_per_stream", values.get("particle_budget", 20_000))))
        self.mesh_budget.setValue(int(values.get("mesh_instance_budget", 50_000)))
        self.cull_distance.setValue(float(values.get("cull_distance", 250.0)))
        self.adaptive_budget.setChecked(bool(values.get("adaptive", True)))

    def set_renderer_stats(self, stats: dict[str, Any]) -> None:
        values = dict(stats or {})
        rendered = int(values.get("total_rendered", 0))
        draw_calls = int(values.get("draw_calls", 0))
        dropped = int(values.get("total_dropped", 0))
        upload_ms = float(values.get("upload_ema_ms", values.get("total_upload_ms", 0.0)))
        target = max(0.01, float(self._target_upload_ms))
        pressure = max(0, min(100, int(round(upload_ms / target * 100.0))))
        self.budget_pressure.setValue(pressure)
        self.budget_pressure.setFormat(f"{upload_ms:.2f} / {target:.2f} ms · {pressure}%")
        self.telemetry_label.setText(
            f"{rendered:,} particles rendered · {draw_calls} draw calls · "
            f"{dropped:,} culled or budget-limited · "
            f"{'within budget' if upload_ms <= target else 'over budget; adaptive scaling recommended'}"
        )

    def set_execution_telemetry(self, telemetry: dict[str, Any]) -> None:
        values = dict(telemetry or {})
        backend = str(values.get("backend", "reference_cpu"))
        dispatch_ms = float(values.get("dispatch_ms", 0.0))
        particle_count = int(values.get("particle_count", 0))
        resident = bool(values.get("gpu_resident", False))
        upload = int(values.get("upload_bytes", 0))
        readback = int(values.get("readback_bytes", 0))
        synchronized = bool(values.get("synchronized_readback", True))
        session_id = int(values.get("session_id", 0))
        stages = [_display_name(str(stage)) for stage in values.get("supported_stages", [])]
        state = "ok" if backend not in {"", "reference_cpu"} else "warning"
        if resident and not synchronized:
            residency = "GPU-resident · no CPU stall"
        else:
            residency = (
                f"synchronized · {upload / 1024.0:.1f} KiB up · {readback / 1024.0:.1f} KiB back"
            )
        coverage = f" · {', '.join(stages)}" if stages else ""
        session = f" · session {session_id}" if session_id > 0 else ""
        set_status_state(
            self.backend_status, state,
            f"{_display_name(backend)} · {particle_count:,} particles · {dispatch_ms:.2f} ms · "
            f"{residency}{session}{coverage}",
        )

    def _module_value_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 2:
            return
        path = str(item.data(2, Qt.UserRole) or "")
        original = item.data(2, Qt.UserRole + 1)
        try:
            value = self._parse_value(item.text(2), original)
        except (TypeError, ValueError, json.JSONDecodeError):
            self._updating = True
            item.setText(2, self._format_value(original))
            self._updating = False
            return
        item.setData(2, Qt.UserRole + 1, value)
        self.parameter_changed.emit(path, value)

    def _preview_changed(self, previewing: bool) -> None:
        self.preview_btn.setText("Pause" if previewing else "Preview")
        if previewing:
            self.telemetry_timer.start()
            self.renderer_stats_requested.emit()
        else:
            self.telemetry_timer.stop()
        self.preview_toggled.emit(bool(previewing))

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, (tuple, list, dict)):
            return json.dumps(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _parse_value(text: str, original: Any) -> Any:
        if isinstance(original, bool):
            value = text.strip().lower()
            if value not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(value)
            return value in {"true", "1", "yes"}
        if isinstance(original, int) and not isinstance(original, bool):
            return int(text)
        if isinstance(original, float):
            return float(text)
        if isinstance(original, (tuple, list, dict)):
            parsed = json.loads(text)
            return tuple(parsed) if isinstance(original, tuple) else parsed
        return text


__all__ = ["FxPropertiesDialog"]
