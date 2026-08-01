import unreal
from custom_qt.custom_widgets import ModelessContinueDialog, BrowseDirectory
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QMessageBox,
)

class BatchRenamerDialog(ModelessContinueDialog):
    def __init__(self, parent=None):
        super(BatchRenamerDialog, self).__init__(parent)
        self.setWindowTitle("Batch Renamer")

        # Create UI components
        self.folder_picker = BrowseDirectory()
        self.find_text_box = QLineEdit()
        self.replace_text_box = QLineEdit()
        self.spinner_count = QSpinBox()

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(self.folder_picker)
        layout.addWidget(self.find_text_box)
        layout.addWidget(self.replace_text_box)
        layout.addWidget(self.spinner_count)

        # Add buttons
        button_layout = QHBoxLayout()
        self.rename_button = QPushButton("Rename Assets")
        self.cancel_button = QPushButton("Cancel")

        # Connect signals to slots
        self.rename_button.clicked.connect(self.rename_assets)
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.rename_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def rename_assets(self):
        folder_path = self.folder_picker.get_directory()
        find_text = self.find_text_box.text()
        replace_text = self.replace_text_box.text()
        count = self.spinner_count.value()

        # Get all assets in the selected folder using real Unreal Engine Python API
        asset_data_list = unreal.EditorAssetLibrary.find_asset_data_at_path(folder_path)

        if not asset_data_list:
            QMessageBox.warning(self, "Batch Renamer", f"No assets found at path: {folder_path}")
            return

        renamed_count = 0
        for i, asset_data in enumerate(asset_data_list):
            if count > 0 and renamed_count >= count:
                break

            old_name = str(asset_data.get_name())
            if find_text and find_text in old_name:
                new_name = old_name.replace(find_text, replace_text)
                unreal.EditorUtilityLibrary.rename_asset(asset_data, new_name)
                renamed_count += 1

        QMessageBox.information(self, "Batch Renamer", f"Renamed {renamed_count} assets successfully.")
