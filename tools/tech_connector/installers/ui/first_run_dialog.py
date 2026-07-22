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


class FirstRunDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("The Entire World AI Setup")
        self.resize(900, 620)

        layout = QVBoxLayout(self)

        brand = QHBoxLayout()
        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(QPixmap(str(LOGO_PATH)).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            brand.addWidget(logo)
        title = QLabel("The Entire World\nTechnical Art AI")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #00b866;")
        brand.addWidget(title)
        brand.addStretch(1)
        layout.addLayout(brand)

        info = QLabel(
            "The current project is indexed by default. Add extra project/tool folders below "
            "only when you want them included in the AST index."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

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
        add_btn.clicked.connect(self.add_dir)
        row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected Extra")
        remove_btn.clicked.connect(self.remove_selected_extra)
        row.addWidget(remove_btn)
        layout.addLayout(row)

        self.auto_index = QCheckBox("Build AST knowledge index after setup")
        self.auto_index.setChecked(bool(self.settings.get("auto_index_on_first_run", True)))
        layout.addWidget(self.auto_index)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
