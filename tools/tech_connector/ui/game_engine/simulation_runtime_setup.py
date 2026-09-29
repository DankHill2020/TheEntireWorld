"""Adaptive runtime setup dialog for TC simulations and effects."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.runtime.engine_runtime_experience_service import (
    build_engine_runtime_experience_plan,
    runtime_goal_options,
    runtime_target_options,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import BACKENDS, EXECUTION_PROFILES
from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button
from tech_connector.ui.ux_polish import ContextRecipeCard, WorkflowRecipe, apply_property_guidance, apply_widget_discoverability


class SimulationRuntimeSetupDialog(QDialog):
    def __init__(self, world: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.world = world
        self.plan: dict[str, Any] = {}
        self.setWindowTitle("Runtime Setup")
        self.setMinimumSize(680, 480)

        layout = QVBoxLayout(self)
        title = QLabel("Simulation Runtime")
        set_ui_role(title, "title")
        layout.addWidget(title)
        subtitle = QLabel("Choose where this should run and what matters most. TC will adapt the implementation and expose every fallback.")
        subtitle.setWordWrap(True)
        set_ui_role(subtitle, "muted")
        layout.addWidget(subtitle)

        self.workflow_guide = ContextRecipeCard(WorkflowRecipe(
            "How runtime setup works",
            ("Choose the target device", "Choose the experience goal", "Review each feature path", "Apply runtime setup"),
            preview="The table updates immediately; select a feature to see why that path was chosen.",
            output="The setup records explicit GPU/CPU paths and fallbacks so the simulation remains portable.",
            tip="Keep Automatic quality, Automatic backend, and adaptive quality until profiling shows a reason to override them.",
        ), self)
        layout.addWidget(self.workflow_guide)

        settings = QGridLayout()
        self.target_combo = QComboBox()
        for item in runtime_target_options():
            self.target_combo.addItem(item["label"], item["target_id"])
        self.goal_combo = QComboBox()
        for item in runtime_goal_options():
            self.goal_combo.addItem(item["label"], item["id"])
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Automatic (Recommended)", "auto")
        for profile in EXECUTION_PROFILES:
            self.quality_combo.addItem(profile.replace("_", " ").title(), profile)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Automatic (Recommended)", "auto")
        for backend_id, capability in BACKENDS.items():
            label = backend_id.replace("_", " ").title()
            if not capability.available:
                label += " (Not installed)"
            self.backend_combo.addItem(label, backend_id)
            model_item = self.backend_combo.model().item(self.backend_combo.count() - 1)
            if model_item is not None and not capability.available:
                model_item.setEnabled(False)
        self.tick_rate = QSpinBox()
        self.tick_rate.setRange(15, 240)
        self.tick_rate.setSuffix(" Hz")
        self.tick_rate.setValue(60)
        self.adaptive_check = QCheckBox("Adapt quality to the measured runtime budget")
        self.adaptive_check.setChecked(True)
        self.advanced_check = QCheckBox("Show technical settings")
        self.advanced_check.setChecked(False)

        settings.addWidget(QLabel("Target"), 0, 0)
        settings.addWidget(self.target_combo, 0, 1)
        settings.addWidget(QLabel("Goal"), 0, 2)
        settings.addWidget(self.goal_combo, 0, 3)
        self.quality_label = QLabel("Quality")
        self.backend_label = QLabel("Backend")
        self.tick_label = QLabel("Simulation rate")
        settings.addWidget(self.quality_label, 1, 0)
        settings.addWidget(self.quality_combo, 1, 1)
        settings.addWidget(self.backend_label, 1, 2)
        settings.addWidget(self.backend_combo, 1, 3)
        settings.addWidget(self.tick_label, 2, 0)
        settings.addWidget(self.tick_rate, 2, 1)
        settings.addWidget(self.adaptive_check, 2, 2, 1, 2)
        settings.addWidget(self.advanced_check, 3, 0, 1, 4)
        layout.addLayout(settings)

        self.feature_tree = QTreeWidget()
        self.feature_tree.setHeaderLabels(["Feature", "Runtime Path", "Status"])
        self.feature_tree.setRootIsDecorated(False)
        self.feature_tree.setAlternatingRowColors(True)
        self.feature_tree.header().setStretchLastSection(False)
        self.feature_tree.header().resizeSection(0, 180)
        self.feature_tree.header().resizeSection(1, 300)
        self.feature_tree.header().resizeSection(2, 110)
        layout.addWidget(self.feature_tree, 1)

        self.feature_detail = QLabel()
        self.feature_detail.setWordWrap(True)
        self.feature_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.feature_detail)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        apply_button = buttons.button(QDialogButtonBox.Apply)
        configure_button(
            apply_button,
            "check",
            text="Apply runtime setup",
            role="primary",
        )
        configure_button(
            buttons.button(QDialogButtonBox.Cancel),
            "close",
            text="Cancel",
            role="quiet",
        )
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for control in (
            self.target_combo,
            self.goal_combo,
            self.quality_combo,
            self.backend_combo,
        ):
            control.currentIndexChanged.connect(self._refresh)
        self.tick_rate.valueChanged.connect(self._refresh)
        self.adaptive_check.toggled.connect(self._refresh)
        self.advanced_check.toggled.connect(self._update_technical_visibility)
        self.target_combo.currentIndexChanged.connect(self._apply_target_tick_rate)
        self.feature_tree.currentItemChanged.connect(self._show_feature_detail)
        self._update_technical_visibility()
        self._refresh()
        self._apply_guidance()
        apply_widget_discoverability(self)

    def _apply_guidance(self) -> None:
        self.target_combo.setToolTip("Where the experience must run. This sets a sensible simulation-rate and feature baseline.")
        self.goal_combo.setToolTip("What to protect first when runtime cost rises: visual quality, responsiveness, or balance.")
        apply_property_guidance(self.tick_rate, "How often physics and simulation advance each second.",
                                safe_start="Use the target default; 60 Hz is a strong desktop baseline.",
                                consequence="Higher rates improve fast collision accuracy but cost more CPU/GPU time.")
        apply_property_guidance(self.adaptive_check, "Adjusts scalable features when measured runtime exceeds the budget.",
                                safe_start="Enabled for interactive and shipped realtime experiences.",
                                consequence="Visual density may change under sustained load, but behavior stays bounded.")
        self.feature_tree.setToolTip("A live explanation of the chosen implementation. Select a row for its rationale and fallback.")

    def selection(self) -> dict[str, Any]:
        selection = dict(self.plan.get("selection") or {})
        selection.update({
            "target": self.target_combo.currentData(),
            "goal": self.goal_combo.currentData(),
            "adaptive": self.adaptive_check.isChecked(),
        })
        return selection

    def _apply_target_tick_rate(self) -> None:
        target = next(
            item for item in runtime_target_options()
            if item["target_id"] == self.target_combo.currentData()
        )
        self.tick_rate.setValue(int(target["tick_rate"]))

    def _update_technical_visibility(self) -> None:
        visible = self.advanced_check.isChecked()
        for widget in (
            self.quality_label, self.quality_combo, self.backend_label,
            self.backend_combo, self.tick_label, self.tick_rate,
        ):
            widget.setVisible(visible)

    def _refresh(self) -> None:
        self.plan = build_engine_runtime_experience_plan(
            self.world,
            target=str(self.target_combo.currentData() or "desktop"),
            goal=str(self.goal_combo.currentData() or "balanced"),
            quality=str(self.quality_combo.currentData() or "auto"),
            backend=str(self.backend_combo.currentData() or "auto"),
            adaptive=self.adaptive_check.isChecked(),
            tick_rate=self.tick_rate.value(),
        )
        self.feature_tree.clear()
        for feature in self.plan["features"]:
            item = QTreeWidgetItem([
                feature["feature"].replace("_", " ").title(),
                feature["runtime_path"],
                feature["status"].title(),
            ])
            item.setToolTip(0, feature["detail"])
            item.setToolTip(1, feature["detail"])
            item.setToolTip(2, feature["detail"])
            self.feature_tree.addTopLevelItem(item)
        if self.feature_tree.topLevelItemCount() and self.feature_tree.currentItem() is None:
            self.feature_tree.setCurrentItem(self.feature_tree.topLevelItem(0))
        text = self.plan["summary"]
        if self.advanced_check.isChecked():
            controls = ", ".join(value.replace("_", " ") for value in self.plan["visible_controls"])
            text += f"\nAvailable technical controls: {controls}"
        self.summary.setText(text)

    def _show_feature_detail(self, item: QTreeWidgetItem | None) -> None:
        self.feature_detail.setText(item.toolTip(0) if item is not None else "")

