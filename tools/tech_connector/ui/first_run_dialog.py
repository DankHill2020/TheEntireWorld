"""First-run setup dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from tech_connector.models.constants import ASSUMED_DIRS, LOGO_PATH
from tech_connector.services.settings_service import save_settings
from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button


class FirstRunDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Tech Connector Setup")
        self.resize(780, 560)

        layout = QVBoxLayout(self)

        brand = QHBoxLayout()
        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(QPixmap(str(LOGO_PATH)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            brand.addWidget(logo)
        title_column = QVBoxLayout()
        title = QLabel("Set up Tech Connector")
        set_ui_role(title, "title")
        title_column.addWidget(title)
        subtitle = QLabel("A two-minute setup for project-aware answers and safer tool actions")
        set_ui_role(subtitle, "muted")
        title_column.addWidget(subtitle)
        brand.addLayout(title_column)
        brand.addStretch(1)
        layout.addLayout(brand)

        step = QLabel("STEP 1 OF 2  •  Choose what Tech Connector may search")
        set_ui_role(step, "sectionTitle")
        layout.addWidget(step)

        info = QLabel(
            "The current project is included automatically. Add another folder only when its files should be used "
            "for search, code understanding, or answers. This does not upload, modify, or execute those files."
        )
        info.setWordWrap(True)
        set_ui_role(info, "muted")
        layout.addWidget(info)

        directories_title = QLabel("Indexed directories")
        set_ui_role(directories_title, "sectionTitle")
        layout.addWidget(directories_title)

        self.dir_list = QListWidget()
        self.dir_list.setAccessibleName("Indexed project and tool directories")
        self.dir_list.setToolTip(
            "Folders Tech Connector can index for project-aware search. Default folders cannot be removed here."
        )
        for d in ASSUMED_DIRS:
            item = QListWidgetItem("[default] " + d)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.dir_list.addItem(item)

        for d in self.settings.get("extra_dirs", []):
            self.dir_list.addItem("[extra] " + d)

        layout.addWidget(self.dir_list, 1)

        row = QHBoxLayout()
        add_btn = QPushButton("Add Tool/Project Directory")
        configure_button(add_btn, "folder", text="Add directory", role="secondary")
        add_btn.clicked.connect(self.add_dir)
        add_btn.setToolTip("Add another project or tools folder to the searchable knowledge index.")
        row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected Extra")
        configure_button(remove_btn, "close", text="Remove selected", role="danger")
        remove_btn.clicked.connect(self.remove_selected_extra)
        remove_btn.setToolTip("Remove the selected extra folder from future indexing. Files on disk are not deleted.")
        row.addWidget(remove_btn)
        layout.addLayout(row)

        next_step = QLabel("STEP 2 OF 2  •  Prepare project knowledge")
        set_ui_role(next_step, "sectionTitle")
        layout.addWidget(next_step)

        self.auto_index = QCheckBox("Index new and changed files after setup (recommended)")
        self.auto_index.setChecked(bool(self.settings.get("auto_index_on_first_run", True)))
        self.auto_index.setToolTip(
            "Builds a local searchable index so questions can use real files and symbols. "
            "You can rebuild or disable indexing later from Project Tools."
        )
        layout.addWidget(self.auto_index)

        outcome = QLabel(
            "After setup: load a project, ask what you want in ordinary language, and review the context strip before sending. "
            "Tech Connector will surface relevant tools when they are needed."
        )
        outcome.setWordWrap(True)
        set_ui_role(outcome, "muted")
        layout.addWidget(outcome)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        configure_button(
            buttons.button(QDialogButtonBox.Ok),
            "check",
            text="Save and continue",
            role="primary",
        )
        configure_button(
            buttons.button(QDialogButtonBox.Cancel),
            "close",
            text="Cancel",
            role="quiet",
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Add knowledge directory")
        if d:
            existing = [
                self.dir_list.item(i).text().replace("[extra] ", "").replace("[default] ", "")
                for i in range(self.dir_list.count())
            ]
            if d not in existing:
                self.dir_list.addItem("[extra] " + d)

    def remove_selected_extra(self):
        for item in self.dir_list.selectedItems():
            if item.text().startswith("[extra] "):
                self.dir_list.takeItem(self.dir_list.row(item))

    def accept(self):
        extras = []
        for i in range(self.dir_list.count()):
            text = self.dir_list.item(i).text()
            if text.startswith("[extra] "):
                extras.append(text.replace("[extra] ", "", 1))
        self.settings["extra_dirs"] = extras
        self.settings["first_run_complete"] = True
        self.settings["auto_index_on_first_run"] = self.auto_index.isChecked()
        save_settings(self.settings)
        super().accept()
