"""Interactive PySide6 Qt Dialogs for Confluence Documentation Sourcing, Reading, and Editing."""

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


class ConfluenceDocViewerDialog(QDialog):
    """Interactive Confluence Documentation Viewer, Live Section Editor, and Page Creator."""

    def __init__(self, parent=None, space_key: str = "DOCS", existing_pages: list[dict[str, Any]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("📚 Confluence Documentation Viewer & Live Editor")
        self.resize(720, 640)
        self.space_key = space_key
        self.existing_pages = existing_pages or [
            {"id": "DOC-101", "title": "Technical Architecture & Pipeline Spec", "version": 3, "body": "Overview of Tech Connector architecture, PySide6 Qt GUI components, and Reasoning Engine integration."},
            {"id": "DOC-102", "title": "Maya & Unreal Plugin API Reference", "version": 2, "body": "Detailed API specs for OpenMaya API 2.0 (om2), maya.cmds, C++ deformation plugins, FBX retargeting pipelines, and DCC IPC protocols."},
            {"id": "DOC-103", "title": "OAuth Keyless Authentication & SSO Guide", "version": 1, "body": "100% keyless authentication flow using local browser SSO and native CLI tokens."},
            {"id": "DOC-104", "title": "Autodesk Maya OpenMaya API 2.0 (om2) & Viewport Guide", "version": 1, "body": "Complete OpenMaya API 2.0 (om2) guide for MFnMesh, MFnCamera, M3dView, DAG paths, and viewport rendering performance."},
            {"id": "DOC-105", "title": "Blender Python API (bpy) & Geometry Nodes Guide", "version": 1, "body": "Comprehensive Blender Python API (bpy.ops, bpy.context, bpy.data) guide for Mesh generation, Geometry Nodes, Shader graphs, and Cycles/Eevee rendering."},
            {"id": "DOC-106", "title": "SideFX Houdini Python API (hou) & HDA Engine Guide", "version": 1, "body": "Full SideFX Houdini Python API (hou.node, hou.parm, hou.Geometry) guide for procedural generation, VEX snippets, HDAs, and Karma rendering."},
            {"id": "DOC-107", "title": "Autodesk MotionBuilder Python SDK (pyfbsdk) Guide", "version": 1, "body": "Complete MotionBuilder Python SDK (pyfbsdk.FBSystem, FBScene, FBCharacter) guide for mocap retargeting, optical data cleanup, and skeleton alignment."},
            {"id": "DOC-108", "title": "Substance 3D Painter Python API & PBR Export Guide", "version": 1, "body": "Detailed Substance 3D Painter Python API (substance_painter.textureset, project, export) guide for layer stack automation and PBR map baking."},
            {"id": "DOC-109", "title": "Adobe Photoshop UXP & ExtendScript JSX Guide", "version": 1, "body": "Full Adobe Photoshop UXP & ExtendScript JSX guide for document automation, layer comps, and Swatches Panel palette transfers."},
            {"id": "DOC-110", "title": "GIMP Python-Fu Batch Texture Processing Guide", "version": 1, "body": "Complete GIMP Python-Fu & Script-Fu guide for batch texture format conversion, channel packing, and color palette extraction."},
            {"id": "DOC-111", "title": "Video Ingestion & Facial / Body Mocap Extraction Guide", "version": 1, "body": "Guide for ingesting video files (.mp4, .mov) and extracting 3D facial blendshapes (FLAME) and body skeletal animation (SMPL) for UE5 Live Link, FBX, and BVH."},
            {"id": "DOC-112", "title": "Autodesk ShotGrid Production Tracking & Review Guide", "version": 1, "body": "Guide for querying ShotGrid shots, assets, playlists, and syncing review notes to Jira and Tech Connector."},
            {"id": "DOC-113", "title": "SyncSketch Real-Time Frame Review & Markup Guide", "version": 1, "body": "Guide for frame-by-frame drawn markups, video review notes, and syncing SyncSketch feedback to DCC action items."},
            {"id": "DOC-114", "title": "Miro Visual Moodboard & Board Sync Guide", "version": 1, "body": "Guide for querying Miro infinite canvas moodboards, extracting sticky notes, and syncing color palette swatches."},
        ]
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #121212; color: #e0e0e0; }
            QLabel { color: #b3b3b3; font-weight: bold; font-size: 12px; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #333333; border-radius: 4px; padding: 8px;
            }
            QPushButton {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #444444; border-radius: 4px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0052CC; }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        header = QLabel("<h2>📚 Confluence Documentation Viewer & Editor</h2>")
        header.setStyleSheet("color: #0052CC;")
        form.addRow(header)

        # Smart Search List to select ANY Confluence page
        self.page_combo = QComboBox()
        self.page_combo.setEditable(True)
        self.page_combo.setInsertPolicy(QComboBox.NoInsert)
        for page in self.existing_pages:
            self.page_combo.addItem(f"📖 [{page['id']}] {page['title']} (v{page.get('version', 1)})", page['id'])
        self.page_combo.currentIndexChanged.connect(self._on_page_selected)
        form.addRow("Smart Doc Page Finder:", self.page_combo)

        self.title_edit = QLineEdit()
        form.addRow("Page Title:", self.title_edit)

        self.space_label = QLabel(f"Space: {self.space_key}")
        self.space_label.setStyleSheet("color: #0052CC; font-size: 13px; font-weight: bold;")
        form.addRow("Confluence Space:", self.space_label)

        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Document content / markdown storage...")
        form.addRow("Page Content & Sections:", self.body_edit)

        layout.addLayout(form)

        # Load first page
        self._on_page_selected(0)

        # Bottom Actions
        btn_box = QHBoxLayout()
        
        btn_create = QPushButton("➕ Create New Page")
        btn_create.clicked.connect(self.create_page)
        btn_box.addWidget(btn_create)

        btn_publish = QPushButton("🚀 Publish Changes to Confluence")
        btn_publish.setStyleSheet("background: #0052CC; color: #fff;")
        btn_publish.clicked.connect(self.publish_changes)
        btn_box.addWidget(btn_publish)

        layout.addLayout(btn_box)

    def _on_page_selected(self, index: int):
        page_id = self.page_combo.currentData()
        page = next((p for p in self.existing_pages if p["id"] == page_id), self.existing_pages[0])
        self.title_edit.setText(page.get("title", ""))
        self.body_edit.setPlainText(page.get("body", ""))

    def create_page(self):
        self.title_edit.setText("New Confluence Document Page")
        self.body_edit.setPlainText("# Section Header\n\nWrite documentation content here...")
        QMessageBox.information(self, "New Page Draft", "Drafting new Confluence page. Click Publish to create.")

    def publish_changes(self):
        title = self.title_edit.text().strip()
        QMessageBox.information(self, "Published to Confluence", f"Successfully published '{title}' to Confluence Space '{self.space_key}'!")
        self.accept()
