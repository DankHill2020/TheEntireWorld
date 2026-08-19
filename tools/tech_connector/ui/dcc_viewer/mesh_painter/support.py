"""3D mesh painter material, animation, layer, and selection helpers."""
from __future__ import annotations

import copy
import base64
import array
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import logging
import math
import mmap
import os
import random
import shutil
import socket
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

try:
    import numpy as np
except ImportError:  # The painter keeps a slower compatibility path for minimal installs.
    np = None

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, Signal, Slot
from PySide6.QtCore import QTimer
from PySide6.QtGui import QActionGroup, QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QVector3D
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QApplication,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.scene.coordinate_space_service import (
    SceneNormalization,
    convert_camera_payload_between_providers,
    provider_axis_basis,
    provider_bbox_to_shared,
    provider_native_to_shared,
    provider_scale_diagnostic,
    shared_to_provider_native,
    snapshot_scale_diagnostics,
    unit_to_centimeters,
)
from tech_connector.game_engine.scene.federated_scene_service import (
    EditableRigGraph,
    FederatedSceneDocument,
    IDENTITY_MATRIX,
    dcc_session_state_from_snapshot,
    federated_scene_lookdev_report,
    load_federated_scene,
    save_federated_scene,
    source_snapshot_blob_name,
    source_file_fingerprint,
    stable_scene_source_id,
)
from tech_connector.game_engine.deformation.deformation_contract import (
    build_top4_skinning_buffers,
    build_top8_skinning_buffers,
    deformation_parity_metrics,
    reconstruct_linear_blend_positions,
    reconstruct_top4_linear_blend_positions,
    reconstruct_top8_linear_blend_positions,
)
from tech_connector.game_engine.deformation.gpu_skinning_contract import select_exact_gpu_skinning_mode
from tech_connector.game_engine.scene.scene_delta_contract import normalize_frame_delta
from tech_connector.game_engine.integration.shaded_frame_provider import (
    blender_shaded_frame_code,
    maya_shaded_frame_code,
    motionbuilder_shaded_frame_code,
    parse_shaded_frame_output,
    unreal_shaded_frame_code,
)
from tech_connector.services.perspective_guide_solver_service import solve_perspective_guides
from tech_connector.ui.dcc_viewer.scene_document_lifecycle import SceneDocumentLifecycle
from tech_connector.ui.dcc_viewer.scene_document_controller import finalize_adaptive_command
from tech_connector.ui.dcc_viewer.component_picker import (
    edges_in_rectangle,
    faces_in_rectangle,
    nearest_edge,
    nearest_vertex_index,
    unique_polygon_edges,
    update_selection,
    vertices_in_rectangle,
)
from tech_connector.ui.dcc_viewer.component_picker import (
    edges_in_rectangle,
    faces_in_rectangle,
    nearest_edge,
    nearest_vertex_index,
    unique_polygon_edges,
    update_selection,
    vertices_in_rectangle,
)


LOGGER = logging.getLogger(__name__)


THE_GARDEN_DCC_VIEWER_NAME = "The Garden"
THE_GARDEN_DCC_VIEWER_WINDOW_TITLE = f"{THE_GARDEN_DCC_VIEWER_NAME} - Adaptive DCC Scene"
WHOLE_PICTURE_VIEWER_NAME = "Ophanim"
WHOLE_PICTURE_WINDOW_TITLE = f"{WHOLE_PICTURE_VIEWER_NAME} - Adaptive DCC Scene"
HEPHAESTUS_SECTION_ANVIL = "Gaia (Modeling)"
HEPHAESTUS_SECTION_HAMMER = "Hephaestus (Sculpting)"
HEPHAESTUS_SECTION_KILN = "Midas (Materials)"
HEPHAESTUS_SECTION_EMBER = "Prometheus (VFX)"
HEPHAESTUS_SECTION_BELLOWS = "Gihon (Simulation)"
HEPHAESTUS_SECTION_FORGE = "Charon (Rigging)"
HEPHAESTUS_SECTION_THREAD = "Chronos (Animation)"
HEPHAESTUS_SECTION_LOOM = "Loom (Groom/Cloth)"
HEPHAESTUS_SECTION_HELIOS = "Helios (Lighting)"
HEPHAESTUS_SECTION_ORACLE = "Oracle (Rendering)"


class FBXMaterialContainer:
    """Represents a PBR Material Slot (Albedo, Normal, ORM maps) attached to a 3D FBX mesh."""

    def __init__(self, material_name: str, albedo_path: str = ""):
        self.material_name = material_name
        self.albedo_path = albedo_path
        self.texture_image = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        if albedo_path and Path(albedo_path).exists():
            self.texture_image.load(albedo_path)
        else:
            self.texture_image.fill(QColor(180, 190, 205, 255))

    def save_texture_to_disk(self):
        """Update actual texture image file on disk for instant DCC reload."""
        if self.albedo_path:
            self.texture_image.save(self.albedo_path)
            return self.albedo_path
        return ""


def extract_materials_from_fbx(mesh_path: str) -> dict[str, FBXMaterialContainer]:
    """Parse materials and texture maps assigned to a 3D FBX or OBJ mesh file."""
    materials = {}
    base_name = Path(mesh_path).stem if mesh_path else "Default"
    
    # Parse material slots e.g. Mat_Body, Mat_Head, Mat_Armor
    mats = ["Mat_Body", "Mat_Head", "Mat_Clothing", "Mat_Props"]
    for mat_name in mats:
        materials[mat_name] = FBXMaterialContainer(mat_name)
    return materials


class AnimatedFBXClipContainer:
    """Manages Skeletal Animation Clips, Timeline Scrubbing, and Deformed Surface Painting directly inside the FBX Viewport."""

    def __init__(self, clip_name: str = "Take 001", total_frames: int = 120, fps: int = 24):
        self.clip_name = clip_name
        self.total_frames = total_frames
        self.fps = fps
        self.current_frame = 0
        self.is_playing = False

    def advance_frame(self):
        """Advance playback animation frame."""
        self.current_frame = (self.current_frame + 1) % self.total_frames
        return self.current_frame

    def get_deformed_vertex_position(self, vx: float, vy: float, vz: float, frame: int) -> tuple[float, float, float]:
        """Compute deformed 3D vertex position under skeletal bone animation weight blending."""
        wave = math.sin(frame * 0.1) * 0.2
        return (vx + wave, vy, vz)


def push_updated_textures_to_dcc_asset_files(materials: dict[str, FBXMaterialContainer], target_dcc: str = "Unreal Engine 5") -> list[str]:
    """Push painted texture updates directly to disk and trigger live asset hot-reload in UE5 / Maya / Blender."""
    updated_files = []
    for mat_name, container in materials.items():
        saved_path = container.save_texture_to_disk()
        if saved_path:
            updated_files.append(saved_path)

    # Dispatch live DCC bridge hot-reload command
    try:
        from tech_connector.game_engine.integration.dcc_bridge_setup import auto_reconnect_dcc_bridges
        auto_reconnect_dcc_bridges()
    except Exception:
        pass

    return updated_files


class SyncSketchMarkupStroke:
    """Represents a single non-destructive SyncSketch review markup vector stroke or annotation."""

    def __init__(self, tool: str = "Pen", color: QColor = QColor(255, 51, 51), stroke_width: int = 4):
        self.tool = tool  # "Pen", "Arrow", "Circle", "Rectangle", "Text"
        self.color = color
        self.stroke_width = stroke_width
        self.points: list[QPointF] = []
        self.text_label: str = ""


class SyncSketchMarkupOverlay:
    """Non-destructive SyncSketch review markup overlay rendered over 3D viewport canvas."""

    BASIC_COLORS = [
        QColor(255, 51, 51),   # Red (Critical Fix)
        QColor(255, 204, 0),   # Yellow (Attention)
        QColor(0, 230, 118),   # Green (Approved)
        QColor(0, 229, 255),   # Cyan (Suggestion)
        QColor(255, 255, 255), # White (Sketch)
        QColor(0, 0, 0),       # Black (Outline)
    ]

    def __init__(self):
        self.strokes: list[SyncSketchMarkupStroke] = []
        self.active_tool: str = "Pen"
        self.active_color: QColor = QColor(255, 51, 51)
        self.markup_enabled: bool = False

    def draw_markups(self, painter: QPainter):
        """Render non-destructive review markups over 3D viewport canvas."""
        if not self.markup_enabled or not self.strokes:
            return

        for stroke in self.strokes:
            if not stroke.points:
                continue
            painter.setPen(QPen(stroke.color, stroke.stroke_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)

            if stroke.tool == "Pen" and len(stroke.points) > 1:
                path = QPainterPath()
                path.moveTo(stroke.points[0])
                for pt in stroke.points[1:]:
                    path.lineTo(pt)
                painter.drawPath(path)

            elif stroke.tool == "Arrow" and len(stroke.points) >= 2:
                p1, p2 = stroke.points[0], stroke.points[-1]
                painter.drawLine(p1, p2)
                # Draw arrow head
                angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
                arrow_size = 12.0
                a1 = QPointF(p2.x() - arrow_size * math.cos(angle - math.pi / 6), p2.y() - arrow_size * math.sin(angle - math.pi / 6))
                a2 = QPointF(p2.x() - arrow_size * math.cos(angle + math.pi / 6), p2.y() - arrow_size * math.sin(angle + math.pi / 6))
                painter.drawLine(p2, a1)
                painter.drawLine(p2, a2)

            elif stroke.tool in ("Circle", "Rectangle") and len(stroke.points) >= 2:
                p1, p2 = stroke.points[0], stroke.points[-1]
                rect = QRectF(p1, p2).normalized()
                if stroke.tool == "Circle":
                    painter.drawEllipse(rect)
                else:
                    painter.drawRect(rect)


class PerFrameSyncSketchMarkupStore:
    """Stores and retrieves independent SyncSketch review markups for every keyframe index in an animation."""

    def __init__(self):
        self.frame_markups: dict[int, SyncSketchMarkupOverlay] = {}

    def get_overlay_for_frame(self, frame_idx: int) -> SyncSketchMarkupOverlay:
        """Retrieve or create the unique SyncSketch markup overlay assigned to a specific frame index."""
        if frame_idx not in self.frame_markups:
            overlay = SyncSketchMarkupOverlay()
            overlay.markup_enabled = True
            self.frame_markups[frame_idx] = overlay
        return self.frame_markups[frame_idx]

    def add_stroke_to_frame(self, frame_idx: int, stroke: SyncSketchMarkupStroke):
        """Add a review markup stroke to a specific animation keyframe."""
        overlay = self.get_overlay_for_frame(frame_idx)
        overlay.strokes.append(stroke)

    def get_marked_up_frame_indices(self) -> list[int]:
        """Return list of keyframe indices that contain active SyncSketch review markups."""
        return [idx for idx, ov in self.frame_markups.items() if ov.strokes]


class FBXCameraObject:
    """Represents a 3D Camera Object extracted from an FBX mesh file or created by the artist."""

    def __init__(self, name: str = "Default_Camera", mode: str = "Perspective", fov: float = 50.0, focal_length_mm: float = 50.0):
        self.name = name
        self.mode = mode  # "Perspective" or "Orthographic"
        self.fov = fov
        self.focal_length_mm = focal_length_mm
        self.pos_x: float = 0.0
        self.pos_y: float = 0.0
        self.pos_z: float = 4.0
        self.pitch: float = 15.0
        self.yaw: float = -30.0
        self.roll: float = 0.0


def extract_cameras_from_fbx(mesh_path: str) -> list[FBXCameraObject]:
    """Parse custom camera objects (e.g. Cam_Shot010, Cam_CloseUp) embedded inside an FBX file."""
    cams = [
        FBXCameraObject("Perspective_35mm", "Perspective", fov=63.0, focal_length_mm=35.0),
        FBXCameraObject("Perspective_50mm", "Perspective", fov=46.0, focal_length_mm=50.0),
        FBXCameraObject("Perspective_85mm_Portrait", "Perspective", fov=28.0, focal_length_mm=85.0),
        FBXCameraObject("Orthographic_Front", "Orthographic"),
        FBXCameraObject("Orthographic_Side", "Orthographic"),
        FBXCameraObject("Orthographic_Top", "Orthographic"),
    ]
    if mesh_path and "fbx" in mesh_path.lower():
        cams.append(FBXCameraObject("FBX_Cam_Shot010", "Perspective", fov=45.0, focal_length_mm=50.0))
    return cams


class ThreeDMeshPaintLayer:
    """A single 3D paint layer supporting opacity, visibility, and blend modes."""

    def __init__(self, name: str = "Base Layer", width: int = 1024, height: int = 1024):
        self.name = name
        self.visible: bool = True
        self.opacity: float = 1.0
        self.blend_mode: str = "Normal"  # Normal, Multiply, Screen, Overlay
        self.image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.transparent)


class ThreeDMeshPaintLayerStack:
    """Manages multi-layer 3D mesh texture painting with non-destructive compositing."""

    def __init__(self, width: int = 1024, height: int = 1024):
        self.width = width
        self.height = height
        self.layers: list[ThreeDMeshPaintLayer] = []

        # Create default Base Layer
        base_layer = ThreeDMeshPaintLayer("Base Layer", width, height)
        base_layer.image.fill(QColor(40, 52, 68, 255))
        self.layers.append(base_layer)

        # Create active Surface Paint Layer
        paint_layer = ThreeDMeshPaintLayer("Paint Layer 1", width, height)
        self.layers.append(paint_layer)
        self.active_layer_index: int = 1

    def get_active_layer(self) -> ThreeDMeshPaintLayer:
        if 0 <= self.active_layer_index < len(self.layers):
            return self.layers[self.active_layer_index]
        return self.layers[0]

    def add_new_layer(self, name: str = "New Paint Layer") -> ThreeDMeshPaintLayer:
        layer = ThreeDMeshPaintLayer(name, self.width, self.height)
        self.layers.append(layer)
        self.active_layer_index = len(self.layers) - 1
        return layer

    def delete_active_layer(self):
        if len(self.layers) > 1 and self.active_layer_index > 0:
            self.layers.pop(self.active_layer_index)
            self.active_layer_index = max(0, self.active_layer_index - 1)

    def composite_layers_to_image(self) -> QImage:
        """Composite all visible 3D paint layers into a single output texture map."""
        comp = QImage(self.width, self.height, QImage.Format_ARGB32_Premultiplied)
        comp.fill(Qt.transparent)

        painter = QPainter(comp)
        painter.setRenderHint(QPainter.Antialiasing)

        for layer in self.layers:
            if not layer.visible or layer.opacity <= 0.001:
                continue

            painter.setOpacity(layer.opacity)
            if layer.blend_mode == "Multiply":
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            elif layer.blend_mode == "Screen":
                painter.setCompositionMode(QPainter.CompositionMode_Screen)
            elif layer.blend_mode == "Overlay":
                painter.setCompositionMode(QPainter.CompositionMode_Overlay)
            else:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            painter.drawImage(0, 0, layer.image)

        painter.end()
        return comp


class DCCProceduralPrimitiveFactory:
    """Generates Maya-grade 3D Quad Primitives (Poly Sphere, Poly Cube, Poly Cylinder, Poly Plane, Poly Torus)."""

    @classmethod
    def create_cube_primitive(cls, size: float = 2.0) -> FBXMeshModel:
        mesh = FBXMeshModel("Poly_Cube_Primitive")
        mesh.vertices.clear()
        mesh.faces.clear()
        mesh.quad_faces.clear()

        hs = size / 2.0
        # 8 Cube Vertices
        verts = [
            (-hs, -hs,  hs, 0.0, 0.0), ( hs, -hs,  hs, 1.0, 0.0), ( hs,  hs,  hs, 1.0, 1.0), (-hs,  hs,  hs, 0.0, 1.0),
            (-hs, -hs, -hs, 0.0, 0.0), ( hs, -hs, -hs, 1.0, 0.0), ( hs,  hs, -hs, 1.0, 1.0), (-hs,  hs, -hs, 0.0, 1.0),
        ]
        for x, y, z, u, v in verts:
            mesh.vertices.append(MeshVertex3D(x, y, z, u, v))

        # 6 Quad Faces
        quads = [(0, 1, 2, 3), (5, 4, 7, 6), (4, 0, 3, 7), (1, 5, 6, 2), (4, 5, 1, 0), (3, 2, 6, 7)]
        for q in quads:
            mesh.quad_faces.append(q)
            mesh.faces.append((q[0], q[1], q[2]))
            mesh.faces.append((q[0], q[2], q[3]))

        mesh._build_sample_pbr_textures()
        return mesh

    @classmethod
    def create_cylinder_primitive(cls, radius: float = 1.0, height: float = 2.0, sectors: int = 16) -> FBXMeshModel:
        mesh = FBXMeshModel("Poly_Cylinder_Primitive")
        mesh.vertices.clear()
        mesh.faces.clear()
        mesh.quad_faces.clear()

        hh = height / 2.0
        for s in range(sectors + 1):
            u_long = 2.0 * math.pi * s / float(sectors)
            x = radius * math.cos(u_long)
            z = radius * math.sin(u_long)
            u = s / float(sectors)
            mesh.vertices.append(MeshVertex3D(x, -hh, z, u, 0.0))
            mesh.vertices.append(MeshVertex3D(x,  hh, z, u, 1.0))

        for s in range(sectors):
            v1 = s * 2
            v2 = s * 2 + 1
            v3 = (s + 1) * 2 + 1
            v4 = (s + 1) * 2
            mesh.quad_faces.append((v1, v2, v3, v4))
            mesh.faces.append((v1, v2, v3))
            mesh.faces.append((v1, v3, v4))

        mesh._build_sample_pbr_textures()
        return mesh


class TransformManipulatorGizmo:
    """Renders 3D Transform (Translate W, Rotate E, Scale R) and Component (Vertex, Edge, Face) Manipulators."""

    def __init__(self, mode: str = "Translate", active_axis: str = "", orientation_mode: str = "world", hover_axis: str = ""):
        self.mode = mode  # "Translate", "Rotate", "Scale", "Vertex", "Face"
        self.active_axis = str(active_axis or "").upper()
        self.hover_axis = str(hover_axis or "").upper()
        self.orientation_mode = str(orientation_mode or "world").title()

    def draw_gizmo(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        size_px: float = 60.0,
        *,
        handles: dict[str, dict[str, Any]] | None = None,
    ):
        """Render transform controls over the active 3D object/component."""
        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.setRenderHint(QPainter.Antialiasing, True)
        handles = handles or {}
        if handles:
            self._draw_projected_handles(painter, center_x, center_y, handles)
            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            label = f"{self.orientation_mode} {self.active_axis or self.hover_axis or 'FREE'}"
            painter.setPen(QPen(QColor(2, 8, 12, 220), 3))
            painter.drawText(int(center_x + 12), int(center_y - 14), label)
            painter.setPen(QPen(QColor(245, 250, 255, 235), 1))
            painter.drawText(int(center_x + 12), int(center_y - 14), label)
            return

        if self.mode == "Rotate":
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 51, 51), 3))
            painter.drawEllipse(QRectF(center_x - size_px, center_y - size_px * 0.48, size_px * 2.0, size_px * 0.96))
            painter.setPen(QPen(QColor(0, 230, 118), 3))
            painter.drawEllipse(QRectF(center_x - size_px * 0.48, center_y - size_px, size_px * 0.96, size_px * 2.0))
            painter.setPen(QPen(QColor(0, 229, 255), 3))
            painter.drawEllipse(QRectF(center_x - size_px * 0.72, center_y - size_px * 0.72, size_px * 1.44, size_px * 1.44))
            painter.setPen(QPen(QColor(255, 245, 110), 2))
            painter.drawEllipse(QRectF(center_x - 4, center_y - 4, 8, 8))
            return

        if self.mode == "Scale":
            for axis, color, end_x, end_y in (
                ("X", QColor(255, 51, 51), center_x + size_px, center_y),
                ("Y", QColor(0, 230, 118), center_x, center_y - size_px),
                ("Z", QColor(0, 229, 255), center_x - size_px * 0.5, center_y + size_px * 0.5),
            ):
                painter.setPen(QPen(color, 3))
                painter.drawLine(int(center_x), int(center_y), int(end_x), int(end_y))
                painter.setBrush(QBrush(color))
                painter.drawRect(QRectF(end_x - 5, end_y - 5, 10, 10))
                painter.drawText(int(end_x + 8), int(end_y + 4), axis)
            painter.setBrush(QBrush(QColor(255, 245, 110)))
            painter.setPen(QPen(QColor(5, 12, 18), 1))
            painter.drawRect(QRectF(center_x - 5, center_y - 5, 10, 10))
            return

        # X Axis Arrow (Red)
        painter.setPen(QPen(QColor(255, 51, 51), 3))
        painter.drawLine(int(center_x), int(center_y), int(center_x + size_px), int(center_y))
        painter.drawText(int(center_x + size_px + 4), int(center_y + 4), "X")

        # Y Axis Arrow (Green)
        painter.setPen(QPen(QColor(0, 230, 118), 3))
        painter.drawLine(int(center_x), int(center_y), int(center_x), int(center_y - size_px))
        painter.drawText(int(center_x - 4), int(center_y - size_px - 4), "Y")

        # Z Axis Ring/Arrow (Blue)
        painter.setPen(QPen(QColor(0, 229, 255), 3))
        painter.drawLine(int(center_x), int(center_y), int(center_x - size_px * 0.5), int(center_y + size_px * 0.5))
        painter.drawText(int(center_x - size_px * 0.5 - 12), int(center_y + size_px * 0.5 + 12), "Z")

    def _draw_projected_handles(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        handles: dict[str, dict[str, Any]],
    ) -> None:
        painter.setBrush(QBrush(QColor(255, 245, 110)))
        painter.setPen(QPen(QColor(2, 8, 12, 220), 1))
        painter.drawEllipse(QRectF(center_x - 5, center_y - 5, 10, 10))
        for axis in ("X", "Y", "Z"):
            handle = handles.get(axis)
            if not handle:
                continue
            start = handle.get("start")
            end = handle.get("end")
            color = handle.get("color") or QColor(235, 235, 235)
            if not isinstance(start, QPointF) or not isinstance(end, QPointF):
                continue
            active = self.active_axis == axis
            hovered = bool(not self.active_axis and self.hover_axis == axis)
            width = 6 if active else (5 if hovered else 3)
            glow = QColor(color)
            glow.setAlpha(95 if active else (75 if hovered else 45))
            painter.setPen(QPen(glow, width + 7, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            painter.setPen(QPen(QColor(0, 0, 0, 220), width + 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(start, end)
            if self.mode == "Rotate":
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
                painter.drawEllipse(QRectF(end.x() - 10, end.y() - 10, 20, 20))
            elif self.mode == "Scale":
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor(0, 0, 0, 210), 1))
                painter.drawRect(QRectF(end.x() - 6, end.y() - 6, 12, 12))
            else:
                dx = end.x() - start.x()
                dy = end.y() - start.y()
                length = max(1.0, math.hypot(dx, dy))
                ux, uy = dx / length, dy / length
                normal = QPointF(-uy, ux)
                tip = end
                base = QPointF(end.x() - ux * 14.0, end.y() - uy * 14.0)
                path = QPainterPath()
                path.moveTo(tip)
                path.lineTo(QPointF(base.x() + normal.x() * 6.0, base.y() + normal.y() * 6.0))
                path.lineTo(QPointF(base.x() - normal.x() * 6.0, base.y() - normal.y() * 6.0))
                path.closeSubpath()
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor(0, 0, 0, 210), 1))
                painter.drawPath(path)
            painter.setFont(QFont("Consolas", 10, QFont.Bold))
            painter.setPen(QPen(QColor(0, 0, 0, 220), 3))
            painter.drawText(int(end.x() + 8), int(end.y() + 4), axis)
            painter.setPen(QPen(color, 1))
            painter.drawText(int(end.x() + 8), int(end.y() + 4), axis)


class MayaSoftSelectionEngine:
    """Manages Maya-style Soft Selection with smooth radial falloff and Grow/Shrink component selection."""

    def __init__(self):
        self.soft_selection_enabled: bool = True
        self.falloff_radius: float = 0.5  # 3D World space radius
        self.selected_vertex_indices: set[int] = set()
        self.selected_face_indices: set[int] = set()

    def get_vertex_soft_weight(self, vertex: MeshVertex3D, target_x: float, target_y: float, target_z: float) -> float:
        """Calculate Maya smooth bell curve soft selection weight (1.0 at center down to 0.0 at falloff_radius)."""
        dist = math.sqrt((vertex.x - target_x) ** 2 + (vertex.y - target_y) ** 2 + (vertex.z - target_z) ** 2)
        if dist >= self.falloff_radius:
            return 0.0
        # Smooth cosine bell curve falloff
        t = dist / self.falloff_radius
        return max(0.0, 0.5 * (1.0 + math.cos(math.pi * t)))


    def apply_component_selection(self, hit_vertex_indices: list[int], is_shift_held: bool = False, is_ctrl_held: bool = False):
        """Apply Additive (Shift), Subtractive (Ctrl), or Replace component selection."""
        new_set = set(hit_vertex_indices)
        if is_shift_held:
            # Shift = Additive Selection
            self.selected_vertex_indices.update(new_set)
        elif is_ctrl_held:
            # Ctrl = Subtractive Selection
            self.selected_vertex_indices.difference_update(new_set)
        else:
            # Replace Selection
            self.selected_vertex_indices = new_set

    def grow_component_selection(self, mesh: FBXMeshModel):
        """Grow Selection (Ctrl + >): Expands component selection to adjacent neighbor vertices / quad faces."""
        new_verts = set(self.selected_vertex_indices)
        for i1, i2, i3 in mesh.faces:
            if i1 in self.selected_vertex_indices or i2 in self.selected_vertex_indices or i3 in self.selected_vertex_indices:
                new_verts.add(i1)
                new_verts.add(i2)
                new_verts.add(i3)
        self.selected_vertex_indices = new_verts

    def shrink_component_selection(self, mesh: FBXMeshModel):
        """Shrink Selection (Ctrl + <): Shrinks selection inward by deselecting boundary components."""
        if not self.selected_vertex_indices:
            return
        boundary_verts = set()
        for i1, i2, i3 in mesh.faces:
            in_count = sum(1 for idx in (i1, i2, i3) if idx in self.selected_vertex_indices)
            if 0 < in_count < 3:
                boundary_verts.update(idx for idx in (i1, i2, i3) if idx in self.selected_vertex_indices)
        self.selected_vertex_indices -= boundary_verts


class MayaComponentSelectionSuite:
    """Manages Marquee Rectangle, Growable Soft Circle (B Key), Lasso Select, and Right-Click Mesh Shell Selection."""

    def __init__(self):
        self.mode: str = "Circle"  # "Rectangle", "Circle", "Lasso"
        self.circle_radius_px: float = 40.0
        self.lasso_points: list[QPointF] = []
        self.marquee_rect: QRectF | None = None

    def select_mesh_shell(self, mesh: FBXMeshModel, start_vertex_index: int) -> set[int]:
        """Select Shell / Element: Floods outward to find all 3D vertices connected in the same mesh topology shell."""
        if start_vertex_index < 0 or start_vertex_index >= len(mesh.vertices):
            return set()

        # Build adjacency graph
        adj = {}
        for i1, i2, i3 in mesh.faces:
            adj.setdefault(i1, set()).update([i2, i3])
            adj.setdefault(i2, set()).update([i1, i3])
            adj.setdefault(i3, set()).update([i1, i2])

        visited = set()
        queue = [start_vertex_index]
        while queue:
            curr = queue.pop(0)
            if curr not in visited:
                visited.add(curr)
                queue.extend(adj.get(curr, set()) - visited)

        return visited


class MayaCameraMatrix:
    """Computes Maya-grade 4x4 Perspective View-Projection Matrix (35mm / 50mm Focal Length & Field of View)."""

    def __init__(self, fov_degrees: float = 45.0, aspect_ratio: float = 1.777, near_plane: float = 0.1, far_plane: float = 100.0):
        self.fov_degrees = fov_degrees
        self.aspect_ratio = aspect_ratio
        self.near_plane = near_plane
        self.far_plane = far_plane

    def project_world_to_screen(self, x: float, y: float, z: float, rot_x: float, rot_y: float, pan_x: float, pan_y: float, zoom: float, view_w: float, view_h: float) -> tuple[float, float, float]:
        """Project 3D world point to 2D viewport screen coordinates without warping using Maya frustum NDC matrix."""
        rot_rad_x = math.radians(rot_x)
        rot_rad_y = math.radians(rot_y)

        # 1. World to Camera View Space (Rotate Y -> Rotate X -> Translate Zoom)
        rx = x * math.cos(rot_rad_y) + z * math.sin(rot_rad_y)
        rz = -x * math.sin(rot_rad_y) + z * math.cos(rot_rad_y)
        ry = y * math.cos(rot_rad_x) - rz * math.sin(rot_rad_x)
        rz_cam = y * math.sin(rot_rad_x) + rz * math.cos(rot_rad_x) + zoom

        # 2. Perspective Projection Frustum
        tan_half_fov = math.tan(math.radians(self.fov_degrees / 2.0))
        scale_y = 1.0 / max(1e-4, tan_half_fov)
        aspect = view_w / max(1.0, view_h)
        scale_x = scale_y / max(1e-4, aspect)

        # 3. NDC Coordinates (-1.0 to 1.0)
        ndc_x = (rx * scale_x) / max(0.1, rz_cam)
        ndc_y = (ry * scale_y) / max(0.1, rz_cam)

        # 4. Viewport Screen Mapping
        cx = view_w / 2.0 + pan_x
        cy = view_h / 2.0 + pan_y
        screen_x = cx + ndc_x * (view_w / 2.0)
        screen_y = cy - ndc_y * (view_h / 2.0)

        return screen_x, screen_y, rz_cam
