"""First-run setup dialog."""

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
        subtitle = QLabel("Choose which projects and tools should be searchable")
        set_ui_role(subtitle, "muted")
        title_column.addWidget(subtitle)
        brand.addLayout(title_column)
        brand.addStretch(1)
        layout.addLayout(brand)

        info = QLabel(
            "The current project is indexed by default. Add extra project/tool folders below "
            "only when you want them included in the AST index."
        )
        info.setWordWrap(True)
        set_ui_role(info, "muted")
        layout.addWidget(info)

        directories_title = QLabel("Indexed directories")
        set_ui_role(directories_title, "sectionTitle")
        layout.addWidget(directories_title)

        self.dir_list = QListWidget()
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
        row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected Extra")
        configure_button(remove_btn, "close", text="Remove selected", role="danger")
        remove_btn.clicked.connect(self.remove_selected_extra)
        row.addWidget(remove_btn)
        layout.addLayout(row)

        self.auto_index = QCheckBox("Build AST knowledge index after setup")
        self.auto_index.setChecked(bool(self.settings.get("auto_index_on_first_run", True)))
        layout.addWidget(self.auto_index)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        configure_button(
            buttons.button(QDialogButtonBox.Ok),
            "check",
            text="Save setup",
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
