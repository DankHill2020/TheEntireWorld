from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel
from tech_connector.game_engine.authoring.tc_physics_joint_service import PHYSICS_JOINT_PRESETS, PHYSICS_JOINT_TYPES
from tech_connector.ui.ux_polish import ContextRecipeCard, WorkflowRecipe, apply_property_guidance, apply_widget_discoverability


class PhysicsJointEditorWidget(QWidget):
    """Compact multi-edit surface for engine physics joints."""

    changed = Signal()
    anchorPickRequested = Signal(str, str)

    def __init__(self, model: PhysicsJointEditorModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self._refreshing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.workflow_guide = ContextRecipeCard(WorkflowRecipe(
            "How to connect physics bodies",
            ("Choose body A and body B", "Add a joint preset", "Select the joint", "Pick anchors in the viewport",
             "Enable limits or a motor, then simulate"),
            requires="The two bodies must already exist in the runtime world.",
            preview="Tune one property family at a time: limits first, damping second, motor last.",
            output="Joint type, anchors, limits, motors, and break thresholds remain explicit for engine export.",
            tip="Start with a preset. Keep connected collision off unless the two attached bodies should strike each other.",
        ), self)
        layout.addWidget(self.workflow_guide)

        create_row = QHBoxLayout()
        self.joint_id = QLineEdit()
        self.joint_id.setPlaceholderText("Joint name")
        self.first_body = QComboBox()
        self.second_body = QComboBox()
        for combo in (self.first_body, self.second_body):
            combo.setEditable(True)
            combo.addItems(self._entity_names())
        self.preset = QComboBox()
        self.preset.addItems(sorted(PHYSICS_JOINT_PRESETS))
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_joint)
        for widget in (self.joint_id, self.first_body, self.second_body, self.preset, add_button):
            create_row.addWidget(widget)
        layout.addLayout(create_row)

        tool_row = QHBoxLayout()
        for text, tooltip, callback in (
            ("Undo", "Undo joint edit", self._undo), ("Redo", "Redo joint edit", self._redo),
            ("Duplicate", "Duplicate selected joints", self._duplicate), ("Delete", "Delete selected joints", self._delete),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            tool_row.addWidget(button)
        tool_row.addStretch(1)
        layout.addLayout(tool_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("Joint", "Type", "First", "Second", "State"))
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.tree, 1)

        form = QFormLayout()
        self.joint_type = QComboBox()
        self.joint_type.addItems(PHYSICS_JOINT_TYPES)
        self.minimum_limit = self._number(-1.0e6, 1.0e6)
        self.maximum_limit = self._number(-1.0e6, 1.0e6)
        self.stiffness = self._number(0.0, 1.0, 0.05)
        self.damping = self._number(0.0, 1.0e6, 0.05)
        self.motor_speed = self._number(-1.0e6, 1.0e6)
        self.motor_force = self._number(0.0, 1.0e12)
        self.break_force = self._number(0.0, 1.0e15)
        self.break_torque = self._number(0.0, 1.0e15)
        self.limits_enabled = QCheckBox()
        self.motor_enabled = QCheckBox()
        self.collision_enabled = QCheckBox()
        for label, widget in (
            ("Type", self.joint_type), ("Minimum limit", self.minimum_limit), ("Maximum limit", self.maximum_limit),
            ("Stiffness", self.stiffness), ("Damping", self.damping), ("Motor", self.motor_enabled),
            ("Motor speed", self.motor_speed), ("Motor force", self.motor_force),
            ("Break force", self.break_force), ("Break torque", self.break_torque),
            ("Use limits", self.limits_enabled), ("Connected collision", self.collision_enabled),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)

        self.dof_tree = QTreeWidget()
        self.dof_tree.setHeaderLabels(("Six-DOF axis property", "X", "Y", "Z"))
        self.dof_tree.setMaximumHeight(250)
        self._dof_items: dict[str, QTreeWidgetItem] = {}
        for key, label in (
            ("linear_lower_limit", "Linear lower"), ("linear_upper_limit", "Linear upper"),
            ("angular_lower_limit", "Angular lower"), ("angular_upper_limit", "Angular upper"),
            ("linear_spring_stiffness", "Linear spring"), ("linear_spring_damping", "Linear damping"),
            ("angular_spring_stiffness", "Angular spring"), ("angular_spring_damping", "Angular damping"),
            ("linear_drive_velocity", "Linear drive speed"), ("linear_drive_maximum_force", "Linear drive force"),
            ("angular_drive_velocity", "Angular drive speed"), ("angular_drive_maximum_force", "Angular drive force"),
        ):
            item = QTreeWidgetItem((label, "0", "0", "0"))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setData(0, Qt.UserRole, key)
            self.dof_tree.addTopLevelItem(item)
            self._dof_items[key] = item
        self.dof_tree.itemChanged.connect(self._six_dof_item_changed)
        layout.addWidget(self.dof_tree)

        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Anchors"))
        for body in ("first", "second"):
            button = QPushButton("Pick A in View" if body == "first" else "Pick B in View")
            button.clicked.connect(lambda _checked=False, value=body: self._request_anchor_pick(value))
            anchor_row.addWidget(button)
        anchor_row.addStretch(1)
        layout.addLayout(anchor_row)

        self.joint_type.currentTextChanged.connect(lambda value: self._edit({"type": value}))
        for widget, key in (
            (self.minimum_limit, "minimum_limit"), (self.maximum_limit, "maximum_limit"),
            (self.stiffness, "stiffness"), (self.damping, "damping"),
            (self.motor_speed, "motor_target_velocity"), (self.motor_force, "motor_maximum_force"),
            (self.break_force, "break_force"), (self.break_torque, "break_torque"),
        ):
            widget.editingFinished.connect(lambda control=widget, name=key: self._edit({name: control.value()}))
        for widget, key in (
            (self.limits_enabled, "limits_enabled"), (self.motor_enabled, "motor_enabled"),
            (self.collision_enabled, "collision_enabled"),
        ):
            widget.toggled.connect(lambda value, name=key: self._edit({name: value}))
        self._apply_guidance()
        self.refresh()
        apply_widget_discoverability(self)

    def _apply_guidance(self) -> None:
        self.first_body.setToolTip("Body A: the first existing physics entity connected by this joint.")
        self.second_body.setToolTip("Body B: the second existing physics entity connected by this joint.")
        self.preset.setToolTip("Choose a safe starting configuration; every generated property remains editable.")
        self.tree.setToolTip("Select one joint to edit it, or select several to apply the same property to all of them.")
        apply_property_guidance(self.stiffness, "How strongly the joint corrects displacement.",
                                safe_start="Increase gradually after limits are correct.",
                                consequence="Very high stiffness can jitter unless damping and substeps are sufficient.")
        apply_property_guidance(self.damping, "Removes oscillation and excess joint motion.",
                                safe_start="Raise until bouncing settles without feeling sluggish.",
                                consequence="Too much damping makes the connection feel heavy or locked.")
        apply_property_guidance(self.motor_force, "Maximum force the motor may apply to reach its target speed.",
                                safe_start="Use the smallest force that moves the expected load.",
                                consequence="Large forces can destabilize light bodies or fight other constraints.")
        apply_property_guidance(self.break_force, "Linear force required to break the joint; zero means unbreakable.",
                                safe_start="Leave at zero until the stable motion is approved.",
                                consequence="Thresholds depend on scene scale and mass.")
        apply_property_guidance(self.break_torque, "Twisting force required to break the joint; zero means unbreakable.",
                                safe_start="Leave at zero until the stable motion is approved.",
                                consequence="Test breakage at final simulation rate and mass values.")
        apply_property_guidance(self.collision_enabled, "Allows the two connected bodies to collide with each other.",
                                safe_start="Off for hinges and limbs.",
                                consequence="Enabling it can cause jitter when the bodies begin overlapped.")

    @staticmethod
    def _number(minimum: float, maximum: float, step: float = 0.1) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(5)
        control.setSingleStep(step)
        return control

    def _entity_names(self) -> list[str]:
        return sorted({str(item.get("name") or item.get("id") or "") for item in self.model.runtime_world.get("entities") or () if isinstance(item, dict)})

    def refresh(self) -> None:
        self._refreshing = True
        selected = set(self.model.selected_ids)
        self.tree.clear()
        for joint in self.model.joints:
            item = QTreeWidgetItem((str(joint.get("id") or ""), str(joint.get("type") or ""),
                                    str(joint.get("first") or ""), str(joint.get("second") or ""),
                                    "Broken" if joint.get("broken") else "Enabled" if joint.get("enabled", True) else "Disabled"))
            self.tree.addTopLevelItem(item)
            item.setSelected(item.text(0) in selected)
        self._refresh_properties()
        self._refreshing = False

    def _selection_changed(self) -> None:
        if self._refreshing:
            return
        self.model.selected_ids = [item.text(0) for item in self.tree.selectedItems()]
        self._refresh_properties()

    def _refresh_properties(self) -> None:
        selected = [joint for joint in self.model.joints if str(joint.get("id") or "") in set(self.model.selected_ids)]
        enabled = bool(selected)
        controls = (self.joint_type, self.minimum_limit, self.maximum_limit, self.stiffness, self.damping,
                    self.motor_speed, self.motor_force, self.break_force, self.break_torque,
                    self.limits_enabled, self.motor_enabled, self.collision_enabled)
        for control in controls:
            control.setEnabled(enabled)
            if not enabled:
                base = control.property("uxEnabledTooltip") or control.toolTip()
                control.setProperty("uxEnabledTooltip", base)
                control.setToolTip((str(base) + "\n\n" if base else "") +
                                   "Unavailable: Select one or more joints in the list to edit properties.")
            elif control.property("uxEnabledTooltip") is not None:
                control.setToolTip(str(control.property("uxEnabledTooltip")))
        self.dof_tree.setEnabled(enabled and any(str(item.get("type")) == "six_dof" for item in selected))
        if enabled and not self.dof_tree.isEnabled():
            self.dof_tree.setToolTip("Six-DOF axis controls become available when a Six DOF joint is selected.")
        if not selected:
            return
        source = selected[0]
        self._refreshing = True
        self.joint_type.setCurrentText(str(source.get("type") or "fixed"))
        for control, key in ((self.minimum_limit, "minimum_limit"), (self.maximum_limit, "maximum_limit"),
                             (self.stiffness, "stiffness"), (self.damping, "damping"),
                             (self.motor_speed, "motor_target_velocity"), (self.motor_force, "motor_maximum_force"),
                             (self.break_force, "break_force"), (self.break_torque, "break_torque")):
            control.setValue(float(source.get(key, 0.0)))
        for control, key in ((self.limits_enabled, "limits_enabled"), (self.motor_enabled, "motor_enabled"),
                             (self.collision_enabled, "collision_enabled")):
            control.setChecked(bool(source.get(key, False)))
        for key, item in self._dof_items.items():
            values = list(source.get(key) or (0.0, 0.0, 0.0))
            for axis in range(3):
                item.setText(axis + 1, f"{float(values[axis]):.6g}")
        self._refreshing = False

    def _six_dof_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._refreshing:
            return
        key = str(item.data(0, Qt.UserRole) or "")
        if not key:
            return
        try:
            values = [float(item.text(axis + 1)) for axis in range(3)]
        except ValueError:
            self._refresh_properties()
            return
        self._edit({key: values})

    def _add_joint(self) -> None:
        identifier = self.joint_id.text().strip() or f"Joint {len(self.model.joints) + 1}"
        self.model.create(identifier, self.first_body.currentText(), self.second_body.currentText(), preset=self.preset.currentText())
        self._changed()

    def _edit(self, changes: dict[str, Any]) -> None:
        if self._refreshing:
            return
        self.model.edit_selected(changes)
        self._changed()

    def _undo(self) -> None:
        if self.model.undo(): self._changed()

    def _redo(self) -> None:
        if self.model.redo(): self._changed()

    def _duplicate(self) -> None:
        if self.model.duplicate_selected(): self._changed()

    def _delete(self) -> None:
        if self.model.remove_selected(): self._changed()

    def _request_anchor_pick(self, body: str) -> None:
        if len(self.model.selected_ids) == 1:
            self.anchorPickRequested.emit(self.model.selected_ids[0], body)

    def _changed(self) -> None:
        self.refresh()
        self.changed.emit()


__all__ = ["PhysicsJointEditorWidget"]
