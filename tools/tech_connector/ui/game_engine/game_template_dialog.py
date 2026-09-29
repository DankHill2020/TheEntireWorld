"""New-game starter dialog backed by the same public Python API as automation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.authoring.presentation_profile_service import (
    VISUAL_STYLE_LABELS,
    available_visual_styles,
)


TEMPLATE_ROLE = Qt.UserRole + 1
VARIANT_ROLE = Qt.UserRole + 2


class GameTemplateDialog(QDialog):
    """A concise template + variant + visual-fidelity creation flow."""

    def __init__(
        self,
        project_root: str | Path,
        parent=None,
        *,
        api: TCEditorAPI | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Starter Game")
        self.setMinimumSize(760, 530)
        self.api = api or TCEditorAPI(project_root)
        self.receipt: dict[str, Any] | None = None
        self._catalog = self.api.available_game_templates()
        self._build_ui()
        self._populate_templates()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        title = QLabel("Start with a playable game")
        title.setStyleSheet("font-size:20px; font-weight:700; color:#eaf6ff;")
        root.addWidget(title)
        subtitle = QLabel(
            "Choose gameplay and presentation independently. The result is ordinary editable TC assets—no locked sample content."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color:#9db5c5;")
        root.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        self.template_list = QListWidget(splitter)
        self.template_list.setMinimumWidth(300)
        self.template_list.currentItemChanged.connect(self._update_preview)
        splitter.addWidget(self.template_list)

        detail = QFrame(splitter)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(16, 12, 10, 12)
        self.template_title = QLabel("Select a template")
        self.template_title.setStyleSheet("font-size:16px; font-weight:700; color:#eaf6ff;")
        detail_layout.addWidget(self.template_title)
        self.template_description = QLabel("")
        self.template_description.setWordWrap(True)
        self.template_description.setStyleSheet("color:#adc1ce;")
        detail_layout.addWidget(self.template_description)
        self.template_facts = QLabel("")
        self.template_facts.setWordWrap(True)
        self.template_facts.setStyleSheet("color:#75d8ff;")
        detail_layout.addWidget(self.template_facts)

        form_host = QWidget(detail)
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 12, 0, 0)
        self.name_edit = QLineEdit("StarterGame", form_host)
        self.name_edit.setPlaceholderText("A unique asset prefix, such as AdventureGame")
        form.addRow("Name", self.name_edit)
        self.visual_style_combo = QComboBox(form_host)
        for style in available_visual_styles():
            self.visual_style_combo.addItem(VISUAL_STYLE_LABELS.get(style, style), style)
        default_style = self.visual_style_combo.findData("stylized_pbr")
        self.visual_style_combo.setCurrentIndex(max(0, default_style))
        form.addRow("Visual Style", self.visual_style_combo)
        self.platform_combo = QComboBox(form_host)
        for label, value in (("Windows", "windows"), ("Linux", "linux"), ("macOS", "macos"), ("Web", "web"), ("Android", "android"), ("iOS", "ios")):
            self.platform_combo.addItem(label, value)
        form.addRow("First Build Target", self.platform_combo)
        detail_layout.addWidget(form_host)

        created = QLabel(
            "Creates: Default Level · Skinned TC Starter Mannequin V3 · Editable Skeleton + Smooth Skin Binding · "
            "IK + Control Rigs · Facial Shapes · Ragdoll · Character Material + Texture · Player Prefab · "
            "8-Way Locomotion + Transition Clips · Input Map · Physics Scene · "
            "Game Ruleset · Development Build Profile"
        )
        created.setWordWrap(True)
        created.setStyleSheet("color:#8fe3b1; padding:10px; background:#0d211b; border:1px solid #194432;")
        detail_layout.addWidget(created)
        readiness = QLabel(
            "Before finishing, Tech Connector checks the active camera, lighting, skinned character, player spawn and collision, movement, jumping, camera follow, animation states, controls, runtime compile, and packaged dependency closure."
        )
        readiness.setWordWrap(True)
        readiness.setStyleSheet("color:#90a6b5;")
        detail_layout.addWidget(readiness)
        detail_layout.addStretch(1)
        splitter.addWidget(detail)
        splitter.setSizes([310, 430])
        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color:#8299aa;")
        bottom.addWidget(self.status_label, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok, self)
        self.create_button = self.buttons.button(QDialogButtonBox.Ok)
        self.create_button.setText("Create Playable Game")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._create)
        bottom.addWidget(self.buttons)
        root.addLayout(bottom)

    def _populate_templates(self) -> None:
        for row in self._catalog:
            maturity = str(row.get("maturity") or "production")
            suffix = "  ·  Preview" if maturity != "production" else ""
            item = QListWidgetItem(f"{row['display_name']}{suffix}")
            item.setData(TEMPLATE_ROLE, row["template_id"])
            item.setData(VARIANT_ROLE, row["variant_id"])
            item.setToolTip(str(row.get("description") or ""))
            self.template_list.addItem(item)
        if self.template_list.count():
            self.template_list.setCurrentRow(0)

    def _selected_template(self) -> dict[str, Any] | None:
        item = self.template_list.currentItem()
        if item is None:
            return None
        template_id = str(item.data(TEMPLATE_ROLE) or "")
        variant_id = str(item.data(VARIANT_ROLE) or "")
        return next(
            (row for row in self._catalog if row["template_id"] == template_id and row["variant_id"] == variant_id),
            None,
        )

    def _update_preview(self, _current=None, _previous=None) -> None:
        row = self._selected_template()
        if row is None:
            self.create_button.setEnabled(False)
            return
        self.create_button.setEnabled(True)
        self.template_title.setText(str(row["display_name"]))
        self.template_description.setText(str(row["description"]))
        self.template_facts.setText(
            f"{row['dimensionality'].upper()}  ·  {str(row['camera_mode']).replace('_', ' ').title()} camera"
            f"  ·  {str(row['movement_mode']).replace('_', ' ').title()} movement"
        )
        default_style = self.visual_style_combo.findData(str(row.get("default_visual_style") or "stylized_pbr"))
        if default_style >= 0:
            self.visual_style_combo.setCurrentIndex(default_style)

    def _create(self) -> None:
        row = self._selected_template()
        if row is None:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.status_label.setText("Enter a name before creating the game.")
            self.name_edit.setFocus()
            return
        self.create_button.setEnabled(False)
        self.status_label.setText("Creating and validating the playable Level…")
        try:
            self.receipt = self.api.create_game_project_from_template(
                template_id=str(row["template_id"]), variant_id=str(row["variant_id"]),
                visual_style=str(self.visual_style_combo.currentData()), project_name=name,
                platform=str(self.platform_combo.currentData()),
            )
        except Exception as exc:
            self.create_button.setEnabled(True)
            self.status_label.setText("Nothing was created; review the error and try again.")
            QMessageBox.critical(self, "Starter game was not created", str(exc))
            return
        if not self.receipt.get("ready_to_play"):
            self.create_button.setEnabled(True)
            issues = "\n".join(f"• {item['message']}" for item in self.receipt["validation"].get("issues") or ())
            QMessageBox.warning(self, "Starter game needs attention", issues or "Play-readiness checks did not pass.")
            return
        self.accept()


__all__ = ["GameTemplateDialog"]
