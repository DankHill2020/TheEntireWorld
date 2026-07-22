# coding=utf-8
"""
    PySide6 Climbing Animation Selector Dialog for DCC & Game Engine Pipelines.
"""

import os
import sys
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QFormLayout,
    QMessageBox,
)

from utilities.pipeline_asset_downloader import download_pipeline_asset


class ClimbingAnimPickerDialog(QDialog):
    """
        Interactive PySide6 Dialog for selecting and downloading climbing animation clips.
    """

    animations_selected = Signal(dict)

    def __init__(self, parent=None, target_skeleton: str = ""):
        """
            Initializes the Climbing Animation Picker Dialog.
        :param parent: parent QWidget
        :param target_skeleton: target skeleton asset or file path
        """
        super().__init__(parent)
        self.setWindowTitle("Climbing Animation System - Clip Selector")
        self.resize(600, 480)
        self.target_skeleton = target_skeleton

        self.anim_entries = {}
        self.clip_keys = [
            "climb_idle",
            "climb_up",
            "climb_down",
            "climb_left",
            "climb_right",
            "ledge_mantle",
            "ledge_drop",
        ]

        self._init_ui()

    def _init_ui(self):
        """
            Constructs the dialog user interface layout.
        :return: None
        """
        main_layout = QVBoxLayout(self)

        # Header Info
        header_label = QLabel(
            "<b>Select or Download Climbing Animation Clips</b><br>"
            "Assign compatible animation files (.fbx, .glb, .uasset) for the climbing state machine."
        )
        header_label.setWordWrap(True)
        main_layout.addWidget(header_label)

        # Form Group
        form_group = QGroupBox("Climbing Animation State Clips")
        form_layout = QFormLayout(form_group)

        for key in self.clip_keys:
            label_name = key.replace("_", " ").title() + ":"
            row_layout = QHBoxLayout()

            line_edit = QLineEdit()
            line_edit.setPlaceholderText(f"Path to {label_name.lower()} animation...")
            
            browse_btn = QPushButton("Browse...")
            browse_btn.clicked.connect(lambda checked=False, k=key, le=line_edit: self._browse_anim_file(k, le))

            row_layout.addWidget(line_edit)
            row_layout.addWidget(browse_btn)

            form_layout.addRow(label_name, row_layout)
            self.anim_entries[key] = line_edit

        main_layout.addWidget(form_group)

        # Action Buttons
        btn_layout = QHBoxLayout()
        
        fetch_sample_btn = QPushButton("Fetch Sample Clips On-The-Fly")
        fetch_sample_btn.setToolTip("Download sample glTF reference animation assets dynamically")
        fetch_sample_btn.clicked.connect(self._fetch_sample_clips)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("Confirm Selection")
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._confirm_selection)

        btn_layout.addWidget(fetch_sample_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(confirm_btn)

        main_layout.addLayout(btn_layout)

    def _browse_anim_file(self, clip_key: str, line_edit: QLineEdit):
        """
            Opens a file dialog to select an animation file.
        :param clip_key: state key string
        :param line_edit: target QLineEdit widget
        :return: None
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {clip_key.replace('_', ' ').title()} Animation",
            "",
            "Animation Files (*.fbx *.glb *.gltf *.uasset *.anim);;All Files (*.*)",
        )
        if file_path:
            line_edit.setText(file_path)

    def _fetch_sample_clips(self):
        """
            Downloads sample glTF reference assets on the fly.
        :return: None
        """
        target_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "external_tools", "downloaded_assets"))
        sample_url = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/Duck/glTF-Binary/Duck.glb"
        try:
            downloaded_path = download_pipeline_asset(sample_url, target_dir)
            for key, line_edit in self.anim_entries.items():
                if not line_edit.text().strip():
                    line_edit.setText(downloaded_path)
            QMessageBox.information(
                self,
                "Sample Assets Downloaded",
                f"Successfully downloaded reference sample animation clip:\n{downloaded_path}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Download Error", f"Failed to download sample asset: {exc}")

    def _confirm_selection(self):
        """
            Validates animation entries and emits selected dictionary.
        :return: None
        """
        selected_anims = {k: le.text().strip() for k, le in self.anim_entries.items() if le.text().strip()}
        if not selected_anims:
            QMessageBox.warning(self, "No Selection", "Please select or download at least one animation clip.")
            return

        self.animations_selected.emit(selected_anims)
        self.accept()

    def get_selected_animations(self) -> dict:
        """
            Returns dictionary of selected animation clips.
        :return: dictionary mapping clip keys to file paths
        """
        return {k: le.text().strip() for k, le in self.anim_entries.items() if le.text().strip()}
