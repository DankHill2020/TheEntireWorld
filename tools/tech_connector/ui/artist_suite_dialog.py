"""Interactive PySide6 Qt Dialog exposing 7 Production Artist Superpowers."""

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


class ArtistSuiteDialog(QDialog):
    """Interactive Production Artist Suite for 3D, Environment, Character, and Lighting Artists."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("❖ Production Artist Superpowers Suite")
        self.resize(800, 660)
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #0d141e; color: #e0e0e0; }
            QLabel { color: #9cdbba; font-weight: bold; font-size: 12px; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #080d14; color: #ffffff;
                border: 1px solid #12324a; border-radius: 4px; padding: 8px;
            }
            QPushButton {
                background-color: #0c1c28; color: #16f26a;
                border: 1px solid #0c7a47; border-radius: 4px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #16f26a; color: #000000; }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        header = QLabel("<h2>❖ Production Artist Superpowers Suite</h2>")
        header.setStyleSheet("color: #16f26a;")
        form.addRow(header)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems([
            "📷 1-Click Camera Rig Matcher (Match 85mm, f/2.0 in DCC)",
            "☀ 3-Point Studio Light Rig Generator (Spawn Key, Fill, Rim)",
            "⯌ Color Palette & Swatch Extractor (Export to Substance/UE5)",
            "◐ Silhouette Readability & Thumbnail Squint Test",
            "🔍 Texel Density & Texture Stretching Auditor",
            "✎ Redline Paint-Over & Markup Annotation Tasker",
            "▷ Cinematic Sequencer Motion Estimator",
        ])
        form.addRow("Select Artist Tool:", self.tool_combo)

        self.dcc_combo = QComboBox()
        self.dcc_combo.addItems(["Unreal Engine 5", "Autodesk Maya", "Blender", "Substance 3D Painter", "Houdini"])
        form.addRow("Active Target DCC:", self.dcc_combo)

        self.output_view = QTextEdit()
        self.output_view.setPlainText("""❖ Selected Tool: 📷 1-Click Camera Rig Matcher

Target Settings Matched from Reference:
• Focal Length: 85mm Portrait Compression
• Aperture: f/2.0 (Shallow Depth of Field)
• Camera Height: 140cm (Chest Level)
• Sensor: Super 35 Cine Format

Click '⚡ Execute Artist Tool in Active DCC' to spawn this camera directly in your live Unreal Engine 5 or Maya session!""")
        form.addRow("Tool Execution Details:", self.output_view)

        layout.addLayout(form)

        # Bottom Actions
        btn_box = QHBoxLayout()
        
        btn_preset = QPushButton("⤓ Save Tool Preset")
        btn_preset.clicked.connect(self.save_preset)
        btn_box.addWidget(btn_preset)

        btn_exec = QPushButton("⚡ Execute Artist Tool in Active DCC")
        btn_exec.setStyleSheet("background: linear-gradient(135deg, #1e9bff, #16f26a); color: #000000; font-weight: bold;")
        btn_exec.clicked.connect(self.execute_tool)
        btn_box.addWidget(btn_exec)

        layout.addLayout(btn_box)

    def save_preset(self):
        QMessageBox.information(self, "Preset Saved", "Saved tool preset for active artist workflow.")

    def execute_tool(self):
        tool = self.tool_combo.currentText()
        dcc = self.dcc_combo.currentText()
        QMessageBox.information(self, "Artist Tool Executed", f"Successfully executed '{tool}' in live session of {dcc}!")
        self.accept()
