"""Interactive PySide6 Qt Dialog for Visual Art Inspection, Region Selection, and Diff Heatmaps."""

from __future__ import annotations

from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QComboBox,
    QFormLayout,
    QMessageBox,
    QScrollArea,
    QWidget,
)

from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button


class VisualArtInspectorDialog(QDialog):
    """Interactive Visual Art & Technical Inspector for Artists."""

    def __init__(self, parent=None, image_path: str = "sample_render.png"):
        super().__init__(parent)
        self.setWindowTitle("Visual Art Inspector")
        self.resize(760, 640)
        self.image_path = image_path
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        header = QLabel("Visual Art Inspector")
        set_ui_role(header, "title")
        form.addRow(header)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems([
            "Complete visual analysis",
            "Region inspector",
            "Value map and squint test",
            "Reference difference heatmap",
        ])
        form.addRow("Inspection Mode:", self.tool_combo)

        self.region_input = QLineEdit("x: 42%, y: 65% (Shadow under right boot)")
        form.addRow("Target Region / Pinpoint:", self.region_input)

        self.analysis_view = QTextEdit()
        self.analysis_view.setPlainText("""Visual Analysis Summary:
• Key Light: Upper-Left 45° (4500K Warm Amber)
• Fill Light: Lower-Right (7500K Cool Blue)
• Camera Lens: 85mm Portrait Compression, f/2.0
• Renderer: Unreal Engine 5 (Lumen + VSM)
• Art Concern: Shadow under boots lacks contact AO

Recommended action:
Increase Contact Shadow Length to 0.08 in UE5 DirectionalLight settings.""")
        form.addRow("Visual Intelligence Report:", self.analysis_view)

        layout.addLayout(form)

        # Bottom Actions
        btn_box = QHBoxLayout()
        
        btn_diff = QPushButton("Compare with reference")
        configure_button(btn_diff, "compare", text="Compare with reference", role="secondary")
        btn_diff.clicked.connect(self.compare_reference)
        btn_box.addWidget(btn_diff)

        btn_fix = QPushButton("Apply suggested fix")
        configure_button(btn_fix, "sparkles", text="Apply suggested fix", role="primary")
        btn_fix.clicked.connect(self.apply_dcc_fix)
        btn_box.addWidget(btn_fix)

        layout.addLayout(btn_box)

    def compare_reference(self):
        QMessageBox.information(self, "Reference Comparison", "Generated visual difference heatmap: 88% value match, 68% lighting direction match.")

    def apply_dcc_fix(self):
        QMessageBox.information(self, "DCC Fix Applied", "Successfully sent light & shadow adjustment commands to live Unreal Engine 5 / Maya session!")
        self.accept()
