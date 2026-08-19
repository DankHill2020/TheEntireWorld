"""3D mesh painter DCC workers and brush data models."""
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
from typing import Any, Callable

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


@dataclass
class MeshVertex3D:
    """A single 3D vertex with position (x, y, z), normal (nx, ny, nz), and UV coordinates (u, v)."""

    x: float
    y: float
    z: float
    u: float = 0.0
    v: float = 0.0


@dataclass
class MeshDefaultPose:
    """Mesh-owned rest shape tied to one exact topology revision."""

    positions: list[tuple[float, float, float]] = field(default_factory=list)
    triangle_faces: list[tuple[int, int, int]] = field(default_factory=list)
    quad_faces: list[tuple[int, int, int, int]] = field(default_factory=list)
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "positions": [list(position) for position in self.positions],
            "triangle_faces": [list(face) for face in self.triangle_faces],
            "quad_faces": [list(face) for face in self.quad_faces],
            "revision": int(self.revision),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeshDefaultPose":
        return cls(
            positions=[tuple(float(value) for value in position[:3]) for position in data.get("positions", ())],
            triangle_faces=[tuple(int(value) for value in face[:3]) for face in data.get("triangle_faces", ())],
            quad_faces=[tuple(int(value) for value in face[:4]) for face in data.get("quad_faces", ())],
            revision=max(1, int(data.get("revision", 1) or 1)),
        )


@dataclass
class SceneProxyMaterialBinding:
    """Runtime material approximation for a source DCC material slot."""

    name: str = ""
    color: QColor = field(default_factory=lambda: QColor(125, 145, 170, 220))
    texture_paths: dict[str, str] = field(default_factory=dict)
    source_material_id: str = ""
    approximation: str = "base_color"
    roughness: float = 0.5
    metalness: float = 0.0
    specular: float = 0.5
    emission_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    opacity: float = 1.0
    transmission: float = 0.0
    ior: float = 1.5
    thickness: float = 0.0
    clearcoat: float = 0.0
    attenuation_color: str = "#ffffff"
    attenuation_distance: float = 1000.0
    texture_color_spaces: dict[str, str] = field(default_factory=dict)
    portable_material: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShotTakeProfile:
    """Viewer-owned shot/take state that can later become an Unreal Level Sequence."""

    name: str
    frame_start: int = 1
    frame_end: int = 120
    current_frame: int = 1
    fps: float = 24.0
    timecode_start: str = "00:00:00:00"
    camera: dict[str, Any] = field(default_factory=dict)
    shot_guides: dict[str, Any] = field(default_factory=dict)
    selected_context: dict[str, Any] = field(default_factory=dict)
    retarget: dict[str, Any] = field(default_factory=dict)
    unreal: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "frame_start": int(self.frame_start),
            "frame_end": int(self.frame_end),
            "current_frame": int(self.current_frame),
            "fps": float(self.fps),
            "timecode_start": self.timecode_start,
            "camera": copy.deepcopy(self.camera),
            "shot_guides": copy.deepcopy(self.shot_guides),
            "selected_context": copy.deepcopy(self.selected_context),
            "retarget": copy.deepcopy(self.retarget),
            "unreal": copy.deepcopy(self.unreal),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShotTakeProfile":
        return cls(
            name=str(data.get("name") or "Shot"),
            frame_start=int(data.get("frame_start", 1) or 1),
            frame_end=int(data.get("frame_end", 120) or 120),
            current_frame=int(data.get("current_frame", 1) or 1),
            fps=float(data.get("fps", 24.0) or 24.0),
            timecode_start=str(data.get("timecode_start") or "00:00:00:00"),
            camera=dict(data.get("camera") or {}),
            shot_guides=dict(data.get("shot_guides") or {}),
            selected_context=dict(data.get("selected_context") or {}),
            retarget=dict(data.get("retarget") or {}),
            unreal=dict(data.get("unreal") or {}),
        )


@dataclass
class SceneProxyMeshData:
    """Local renderable mesh data for one source scene element."""

    vertex_start: int = 0
    vertex_count: int = 0
    face_start: int = 0
    face_count: int = 0
    quad_start: int = 0
    quad_count: int = 0
    has_uvs: bool = False
    source_vertex_count: int = 0
    source_vertex_indices: list[int] = field(default_factory=list)
    topology_state: str = "snapshot"


@dataclass
class SceneProxyInstance:
    """A local, syncable scene element instance backed by a source DCC object."""

    index: int
    provider_id: str
    native_id: str
    name: str
    object_type: str = "mesh"
    representation: str = "mesh"
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    source_bbox: tuple[float, float, float, float, float, float] | None = None
    mesh_data: SceneProxyMeshData = field(default_factory=SceneProxyMeshData)
    materials: list[SceneProxyMaterialBinding] = field(default_factory=list)
    material_color: QColor = field(default_factory=lambda: QColor(125, 145, 170, 220))
    fill_color: QColor = field(default_factory=lambda: QColor(125, 145, 170, 190))
    wire_color: QColor = field(default_factory=lambda: QColor(185, 230, 255, 235))
    source_transform: dict[str, Any] = field(default_factory=dict)
    light_data: dict[str, Any] = field(default_factory=dict)
    local_transform: dict[str, Any] = field(default_factory=dict)
    source_signature: str = ""
    source_key: str = ""
    texture_bindings: dict[str, str] = field(default_factory=dict)
    sync_state: str = "clean"
    pending_shared_delta: tuple[float, float, float] = (0.0, 0.0, 0.0)
    selected: bool = False
    visible: bool = True

    def get(self, key: str, default: Any = None) -> Any:
        if key == "type":
            return self.object_type
        if key == "_pending_shared_delta":
            return self.pending_shared_delta
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, None)
        if value is None and not hasattr(self, key):
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "type":
            self.object_type = str(value)
        elif key == "_pending_shared_delta":
            self.pending_shared_delta = tuple(float(v) for v in value)
        else:
            setattr(self, key, value)

    def pop(self, key: str, default: Any = None) -> Any:
        if key == "_pending_shared_delta":
            value = self.pending_shared_delta
            self.pending_shared_delta = (0.0, 0.0, 0.0)
            return value
        if hasattr(self, key):
            value = getattr(self, key)
            try:
                delattr(self, key)
            except Exception:
                pass
            return value
        return default

    def bind_texture_file(self, slot: str, path: str) -> None:
        self.texture_bindings[str(slot or "base_color")] = str(path or "")
        if self.materials:
            self.materials[0].texture_paths[str(slot or "base_color")] = str(path or "")
            self.materials[0].approximation = "texture_bound"
        self.sync_state = "dirty"


@dataclass(frozen=True)
class MeshBrushProfile:
    radius_scale: float = 1.0
    opacity: float = 1.0
    hardness: float = 0.75
    spacing: float = 0.25
    scatter: float = 0.0
    grain: float = 0.0
    blend_mode: str = "normal"
    alpha_mask: str = "round"
    alpha_path: str = ""


BRUSH_PROFILES: dict[str, MeshBrushProfile] = {
    "PaintBrush": MeshBrushProfile(radius_scale=1.0, opacity=0.9, hardness=0.55, spacing=0.22),
    "FillBrush": MeshBrushProfile(radius_scale=1.0, opacity=0.9, hardness=0.65, spacing=0.22),
    "SprayCan": MeshBrushProfile(radius_scale=1.25, opacity=0.28, hardness=0.15, spacing=0.16, scatter=0.8, grain=0.35),
    "Pencil": MeshBrushProfile(radius_scale=0.42, opacity=0.95, hardness=0.92, spacing=0.14, grain=0.2),
    "Watercolor": MeshBrushProfile(radius_scale=1.45, opacity=0.18, hardness=0.08, spacing=0.2, scatter=0.18, grain=0.18, blend_mode="glaze"),
    "FillBucket": MeshBrushProfile(radius_scale=1.0, opacity=1.0, hardness=1.0, spacing=1.0),
    "Eraser": MeshBrushProfile(radius_scale=1.0, opacity=0.85, hardness=0.65, spacing=0.18, blend_mode="erase"),
}

_BRUSH_ALPHA_IMAGE_CACHE: dict[str, QImage] = {}
_BRUSH_ALPHA_ARRAY_CACHE: dict[tuple[Any, ...], Any] = {}
_BRUSH_ALPHA_PREVIEW_CACHE: dict[tuple[Any, ...], QImage] = {}
_BRUSH_STAMP_IMAGE_CACHE: dict[tuple[Any, ...], QImage] = {}


def _load_brush_alpha_image(path: str) -> QImage | None:
    if not path:
        return None
    cached = _BRUSH_ALPHA_IMAGE_CACHE.get(path)
    if cached is not None:
        return cached
    image = QImage(path)
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format_ARGB32)
    _BRUSH_ALPHA_IMAGE_CACHE[path] = image
    return image


def _brush_alpha_from_image(image: QImage, nx: float, ny: float) -> float:
    if image.isNull() or abs(nx) > 1.0 or abs(ny) > 1.0:
        return 0.0
    px = max(0, min(image.width() - 1, int(((nx + 1.0) * 0.5) * float(image.width() - 1))))
    py = max(0, min(image.height() - 1, int(((ny + 1.0) * 0.5) * float(image.height() - 1))))
    pixel = image.pixelColor(px, py)
    if image.hasAlphaChannel() and pixel.alpha() < 255:
        return pixel.alpha() / 255.0
    return (pixel.red() * 0.299 + pixel.green() * 0.587 + pixel.blue() * 0.114) / 255.0


def brush_alpha_at(profile: MeshBrushProfile, nx: float, ny: float) -> float:
    """Sample the brush tip alpha at normalized stamp coordinates in the -1..1 range."""
    if abs(nx) > 1.0 or abs(ny) > 1.0:
        return 0.0

    mask = str(getattr(profile, "alpha_mask", "round") or "round")
    hardness = max(0.01, min(1.0, profile.hardness))
    if mask == "texture":
        image = _load_brush_alpha_image(getattr(profile, "alpha_path", ""))
        if image is not None:
            alpha = _brush_alpha_from_image(image, nx, ny)
            softness = 1.0 - hardness
            if softness > 0.001:
                blur_radius = 0.02 + softness * 0.16
                samples = [
                    (nx - blur_radius, ny),
                    (nx + blur_radius, ny),
                    (nx, ny - blur_radius),
                    (nx, ny + blur_radius),
                    (nx - blur_radius * 0.7, ny - blur_radius * 0.7),
                    (nx + blur_radius * 0.7, ny - blur_radius * 0.7),
                    (nx - blur_radius * 0.7, ny + blur_radius * 0.7),
                    (nx + blur_radius * 0.7, ny + blur_radius * 0.7),
                ]
                alpha = (alpha * 2.0 + sum(_brush_alpha_from_image(image, sx, sy) for sx, sy in samples)) / 10.0
            return max(0.0, min(1.0, alpha))

    if mask == "square":
        d = max(abs(nx), abs(ny))
    else:
        d = math.sqrt(nx * nx + ny * ny)
    if d > 1.0:
        return 0.0

    if d <= hardness:
        alpha = 1.0
    else:
        alpha = 1.0 - ((d - hardness) / max(1e-5, 1.0 - hardness))
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    if mask == "noisy_round":
        alpha *= 0.55 + 0.45 * math.sin((nx * 43.0 + ny * 71.0) * 12.0)
    elif mask == "soft_blot":
        wobble = 0.72 + 0.28 * math.sin(nx * 15.0 + math.cos(ny * 9.0) * 2.5)
        alpha *= wobble
    return max(0.0, min(1.0, alpha))


def _shift_alpha_array(source: Any, dx: int, dy: int) -> Any:
    shifted = np.zeros_like(source)
    height, width = source.shape
    source_x0 = max(0, dx)
    source_x1 = min(width, width + dx)
    source_y0 = max(0, dy)
    source_y1 = min(height, height + dy)
    target_x0 = max(0, -dx)
    target_x1 = target_x0 + max(0, source_x1 - source_x0)
    target_y0 = max(0, -dy)
    target_y1 = target_y0 + max(0, source_y1 - source_y0)
    if source_x1 > source_x0 and source_y1 > source_y0:
        shifted[target_y0:target_y1, target_x0:target_x1] = source[source_y0:source_y1, source_x0:source_x1]
    return shifted


def _brush_alpha_array(profile: MeshBrushProfile, size: int, include_grain: bool = False) -> Any:
    if np is None:
        return None
    cache_key = (
        int(size),
        round(float(profile.hardness), 4),
        round(float(profile.grain if include_grain else 0.0), 4),
        str(profile.alpha_mask),
        str(profile.alpha_path),
    )
    cached = _BRUSH_ALPHA_ARRAY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pixel_axis = (np.arange(size, dtype=np.float32) + 0.5) * (2.0 / float(size)) - 1.0
    nx, ny = np.meshgrid(pixel_axis, pixel_axis)
    mask_name = str(getattr(profile, "alpha_mask", "round") or "round")
    hardness = max(0.01, min(1.0, float(profile.hardness)))
    alpha = None
    if mask_name == "texture":
        source = _load_brush_alpha_image(getattr(profile, "alpha_path", ""))
        if source is not None:
            scaled = source.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            rgba = scaled.convertToFormat(QImage.Format_RGBA8888)
            pixels = np.frombuffer(
                rgba.bits(),
                dtype=np.uint8,
                count=rgba.bytesPerLine() * rgba.height(),
            ).reshape((rgba.height(), rgba.bytesPerLine()))[:, : rgba.width() * 4].reshape((rgba.height(), rgba.width(), 4))
            luminance = pixels[:, :, 0] * 0.299 + pixels[:, :, 1] * 0.587 + pixels[:, :, 2] * 0.114
            if source.hasAlphaChannel():
                alpha = np.where(pixels[:, :, 3] < 255, pixels[:, :, 3], luminance).astype(np.float32) / 255.0
            else:
                alpha = luminance.astype(np.float32) / 255.0
            softness = 1.0 - hardness
            if softness > 0.001:
                offset = max(1, int(round((0.02 + softness * 0.16) * size * 0.5)))
                diagonal = max(1, int(round(offset * 0.7)))
                alpha = (
                    alpha * 2.0
                    + _shift_alpha_array(alpha, -offset, 0)
                    + _shift_alpha_array(alpha, offset, 0)
                    + _shift_alpha_array(alpha, 0, -offset)
                    + _shift_alpha_array(alpha, 0, offset)
                    + _shift_alpha_array(alpha, -diagonal, -diagonal)
                    + _shift_alpha_array(alpha, diagonal, -diagonal)
                    + _shift_alpha_array(alpha, -diagonal, diagonal)
                    + _shift_alpha_array(alpha, diagonal, diagonal)
                ) / 10.0

    if alpha is None:
        distance = np.maximum(np.abs(nx), np.abs(ny)) if mask_name == "square" else np.sqrt(nx * nx + ny * ny)
        edge = np.clip((1.0 - distance) / max(1.0e-5, 1.0 - hardness), 0.0, 1.0)
        alpha = np.where(distance <= hardness, 1.0, edge * edge * (3.0 - 2.0 * edge))
        alpha = np.where(distance <= 1.0, alpha, 0.0)
        if mask_name == "noisy_round":
            alpha *= 0.55 + 0.45 * np.sin((nx * 43.0 + ny * 71.0) * 12.0)
        elif mask_name == "soft_blot":
            alpha *= 0.72 + 0.28 * np.sin(nx * 15.0 + np.cos(ny * 9.0) * 2.5)

    if include_grain and profile.grain > 0.0:
        x_pixels, y_pixels = np.meshgrid(np.arange(size, dtype=np.float32), np.arange(size, dtype=np.float32))
        noise = 0.65 + 0.35 * np.sin((x_pixels * 12.9898 + y_pixels * 78.233) * 0.075)
        alpha *= (1.0 - profile.grain) + profile.grain * noise
    alpha = np.clip(alpha, 0.0, 1.0).astype(np.float32)
    if len(_BRUSH_ALPHA_ARRAY_CACHE) >= 48:
        _BRUSH_ALPHA_ARRAY_CACHE.pop(next(iter(_BRUSH_ALPHA_ARRAY_CACHE)))
    _BRUSH_ALPHA_ARRAY_CACHE[cache_key] = alpha
    return alpha


def _rgba_image_from_alpha(alpha: Any, color: QColor, opacity: float) -> QImage:
    size = int(alpha.shape[0])
    rgba = np.empty((size, size, 4), dtype=np.uint8)
    rgba[:, :, 0] = color.red()
    rgba[:, :, 1] = color.green()
    rgba[:, :, 2] = color.blue()
    rgba[:, :, 3] = np.rint(np.clip(alpha * opacity, 0.0, 1.0) * 255.0).astype(np.uint8)
    return QImage(rgba.data, size, size, int(rgba.strides[0]), QImage.Format_RGBA8888).copy()


class _ProjectedMeshRaycaster:
    """Reuse projected triangle data while resolving all samples in a brush footprint."""

    def __init__(self, screen_vertices: list[tuple[float, ...]], faces: list[tuple[int, int, int]]):
        self.screen_vertices = screen_vertices
        self.faces = faces
        self._triangles = None
        if np is None or not screen_vertices or not faces:
            return
        projected = np.asarray(screen_vertices, dtype=np.float32)
        indices = np.asarray(faces, dtype=np.int64).reshape((-1, 3))
        valid = np.all((indices >= 0) & (indices < len(screen_vertices)), axis=1)
        if not np.any(valid):
            return
        triangles = projected[indices[valid]]
        self._face_indices = np.flatnonzero(valid)
        x1, y1 = triangles[:, 0, 0], triangles[:, 0, 1]
        x2, y2 = triangles[:, 1, 0], triangles[:, 1, 1]
        x3, y3 = triangles[:, 2, 0], triangles[:, 2, 1]
        cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
        denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        self._triangles = triangles
        self._x1, self._y1 = x1, y1
        self._x2, self._y2 = x2, y2
        self._x3, self._y3 = x3, y3
        self._denominator = denominator
        self._front_facing = (cross < 0.0) & (np.abs(denominator) >= 1.0e-6)
        self._min_x = np.minimum(np.minimum(x1, x2), x3)
        self._max_x = np.maximum(np.maximum(x1, x2), x3)
        self._min_y = np.minimum(np.minimum(y1, y2), y3)
        self._max_y = np.maximum(np.maximum(y1, y2), y3)
        self._extent = np.maximum(self._max_x - self._min_x, self._max_y - self._min_y)
        self._depth = triangles[:, :, 2].mean(axis=1)

    def face_indices_at(self, points: list[tuple[float, float]], tolerance: float = 0.0) -> list[int | None]:
        """Return the nearest visible source-triangle index for each screen point."""
        if self._triangles is None:
            results: list[int | None] = []
            for sample_x, sample_y in points:
                best_index = None
                best_depth = float("inf")
                for face_index, (i1, i2, i3) in enumerate(self.faces):
                    if min(i1, i2, i3) < 0 or max(i1, i2, i3) >= len(self.screen_vertices):
                        continue
                    first, second, third = self.screen_vertices[i1], self.screen_vertices[i2], self.screen_vertices[i3]
                    denominator = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1])
                    cross = (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0])
                    if cross >= 0.0 or abs(denominator) < 1.0e-6:
                        continue
                    w1 = ((second[1] - third[1]) * (sample_x - third[0]) + (third[0] - second[0]) * (sample_y - third[1])) / denominator
                    w2 = ((third[1] - first[1]) * (sample_x - third[0]) + (first[0] - third[0]) * (sample_y - third[1])) / denominator
                    w3 = 1.0 - w1 - w2
                    depth = (first[2] + second[2] + third[2]) / 3.0
                    if w1 >= -tolerance and w2 >= -tolerance and w3 >= -tolerance and depth < best_depth:
                        best_index, best_depth = face_index, depth
                results.append(best_index)
            return results
        results = []
        padding = self._extent * max(0.0, float(tolerance))
        for sample_x, sample_y in points:
            candidates = np.flatnonzero(
                self._front_facing
                & (sample_x >= self._min_x - padding) & (sample_x <= self._max_x + padding)
                & (sample_y >= self._min_y - padding) & (sample_y <= self._max_y + padding)
            )
            if candidates.size == 0:
                results.append(None)
                continue
            denominator = self._denominator[candidates]
            w1 = ((self._y2[candidates] - self._y3[candidates]) * (sample_x - self._x3[candidates]) + (self._x3[candidates] - self._x2[candidates]) * (sample_y - self._y3[candidates])) / denominator
            w2 = ((self._y3[candidates] - self._y1[candidates]) * (sample_x - self._x3[candidates]) + (self._x1[candidates] - self._x3[candidates]) * (sample_y - self._y3[candidates])) / denominator
            inside = (w1 >= -tolerance) & (w2 >= -tolerance) & ((1.0 - w1 - w2) >= -tolerance)
            inside_candidates = candidates[inside]
            if inside_candidates.size == 0:
                results.append(None)
                continue
            nearest = int(inside_candidates[int(np.argmin(self._depth[inside_candidates]))])
            results.append(int(self._face_indices[nearest]))
        return results

    def hits(self, points: list[tuple[float, float]], tolerance: float = 0.0) -> list[tuple[float, ...] | None]:
        if self._triangles is None:
            return [self._scalar_hit(x, y, tolerance) for x, y in points]
        results: list[tuple[float, ...] | None] = []
        padding = self._extent * max(0.0, float(tolerance))
        for sample_x, sample_y in points:
            broad_phase = (
                self._front_facing
                & (sample_x >= self._min_x - padding)
                & (sample_x <= self._max_x + padding)
                & (sample_y >= self._min_y - padding)
                & (sample_y <= self._max_y + padding)
            )
            candidate_indices = np.flatnonzero(broad_phase)
            if candidate_indices.size == 0:
                results.append(None)
                continue
            denominator = self._denominator[candidate_indices]
            w1 = (
                (self._y2[candidate_indices] - self._y3[candidate_indices]) * (sample_x - self._x3[candidate_indices])
                + (self._x3[candidate_indices] - self._x2[candidate_indices]) * (sample_y - self._y3[candidate_indices])
            ) / denominator
            w2 = (
                (self._y3[candidate_indices] - self._y1[candidate_indices]) * (sample_x - self._x3[candidate_indices])
                + (self._x1[candidate_indices] - self._x3[candidate_indices]) * (sample_y - self._y3[candidate_indices])
            ) / denominator
            w3 = 1.0 - w1 - w2
            inside = (w1 >= -tolerance) & (w2 >= -tolerance) & (w3 >= -tolerance)
            if not np.any(inside):
                results.append(None)
                continue
            inside_candidates = candidate_indices[inside]
            local_index = int(np.argmin(self._depth[inside_candidates]))
            face_index = int(inside_candidates[local_index])
            weights = (float(w1[inside][local_index]), float(w2[inside][local_index]), float(w3[inside][local_index]))
            triangle = self._triangles[face_index]
            interpolated = triangle[0, 3:8] * weights[0] + triangle[1, 3:8] * weights[1] + triangle[2, 3:8] * weights[2]
            results.append((
                float(interpolated[0]),
                float(interpolated[1]),
                float(interpolated[2]),
                max(0.0, min(1.0, float(interpolated[3]))),
                max(0.0, min(1.0, float(interpolated[4]))),
            ))
        return results

    def _scalar_hit(self, sample_x: float, sample_y: float, tolerance: float) -> tuple[float, ...] | None:
        hit = None
        min_depth = float("inf")
        for i1, i2, i3 in self.faces:
            if min(i1, i2, i3) < 0 or max(i1, i2, i3) >= len(self.screen_vertices):
                continue
            sv1, sv2, sv3 = self.screen_vertices[i1], self.screen_vertices[i2], self.screen_vertices[i3]
            x1, y1, z1, vx1, vy1, vz1, u1, uv_v1 = sv1
            x2, y2, z2, vx2, vy2, vz2, u2, uv_v2 = sv2
            x3, y3, z3, vx3, vy3, vz3, u3, uv_v3 = sv3
            cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
            denominator = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if cross >= 0.0 or abs(denominator) < 1.0e-6:
                continue
            w1 = ((y2 - y3) * (sample_x - x3) + (x3 - x2) * (sample_y - y3)) / denominator
            w2 = ((y3 - y1) * (sample_x - x3) + (x1 - x3) * (sample_y - y3)) / denominator
            w3 = 1.0 - w1 - w2
            depth = (z1 + z2 + z3) / 3.0
            if w1 >= -tolerance and w2 >= -tolerance and w3 >= -tolerance and depth < min_depth:
                min_depth = depth
                hit = (
                    w1 * vx1 + w2 * vx2 + w3 * vx3,
                    w1 * vy1 + w2 * vy2 + w3 * vy3,
                    w1 * vz1 + w2 * vz2 + w3 * vz3,
                    max(0.0, min(1.0, w1 * u1 + w2 * u2 + w3 * u3)),
                    max(0.0, min(1.0, w1 * uv_v1 + w2 * uv_v2 + w3 * uv_v3)),
                )
        return hit


def build_brush_alpha_preview(profile: MeshBrushProfile, size_px: int, tint: QColor) -> QImage:
    size = max(8, int(size_px))
    cache_key = (
        size,
        tint.red(),
        tint.green(),
        tint.blue(),
        profile.radius_scale,
        profile.opacity,
        profile.hardness,
        profile.scatter,
        profile.grain,
        profile.alpha_mask,
        profile.alpha_path,
    )
    cached = _BRUSH_ALPHA_PREVIEW_CACHE.get(cache_key)
    if cached is not None:
        return cached
    alpha_array = _brush_alpha_array(profile, size)
    if alpha_array is not None:
        image = _rgba_image_from_alpha(alpha_array, tint, 96.0 / 255.0)
        if len(_BRUSH_ALPHA_PREVIEW_CACHE) >= 48:
            _BRUSH_ALPHA_PREVIEW_CACHE.pop(next(iter(_BRUSH_ALPHA_PREVIEW_CACHE)))
        _BRUSH_ALPHA_PREVIEW_CACHE[cache_key] = image
        return image
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    for y in range(size):
        ny = ((y + 0.5) / float(size)) * 2.0 - 1.0
        for x in range(size):
            nx = ((x + 0.5) / float(size)) * 2.0 - 1.0
            alpha = brush_alpha_at(profile, nx, ny)
            if alpha <= 0.001:
                continue
            image.setPixelColor(x, y, QColor(tint.red(), tint.green(), tint.blue(), int(96 * alpha)))
    _BRUSH_ALPHA_PREVIEW_CACHE[cache_key] = image
    return image


def build_brush_stamp_image(profile: MeshBrushProfile, radius_px: float, color: QColor) -> QImage:
    radius = max(1.0, float(radius_px))
    size = max(2, min(768, int(math.ceil(radius * 2.0))))
    sample_size = size if profile.alpha_mask == "texture" else min(size, 256)
    src = QColor(200, 205, 215, 255) if profile.blend_mode == "erase" else QColor(color)
    opacity = max(0.0, min(1.0, profile.opacity)) * (color.alpha() / 255.0)
    if profile.blend_mode == "glaze":
        opacity *= 0.72
    cache_key = (
        size,
        src.red(),
        src.green(),
        src.blue(),
        src.alpha(),
        round(opacity, 4),
        profile.hardness,
        profile.grain,
        profile.blend_mode,
        profile.alpha_mask,
        profile.alpha_path,
    )
    cached = _BRUSH_STAMP_IMAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    alpha_array = _brush_alpha_array(profile, sample_size, include_grain=True)
    if alpha_array is not None:
        image = _rgba_image_from_alpha(alpha_array, src, opacity)
        if sample_size != size:
            image = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if len(_BRUSH_STAMP_IMAGE_CACHE) > 96:
            _BRUSH_STAMP_IMAGE_CACHE.pop(next(iter(_BRUSH_STAMP_IMAGE_CACHE)))
        _BRUSH_STAMP_IMAGE_CACHE[cache_key] = image
        return image
    image = QImage(sample_size, sample_size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    for y in range(sample_size):
        ny = ((y + 0.5) / float(sample_size)) * 2.0 - 1.0
        for x in range(sample_size):
            nx = ((x + 0.5) / float(sample_size)) * 2.0 - 1.0
            mask_alpha = brush_alpha_at(profile, nx, ny)
            if mask_alpha <= 0.001:
                continue
            if profile.grain > 0.0:
                noise = 0.65 + 0.35 * math.sin((x * 12.9898 + y * 78.233) * 0.075)
                mask_alpha *= (1.0 - profile.grain) + profile.grain * noise
            alpha = max(0.0, min(1.0, opacity * mask_alpha))
            if alpha <= 0.001:
                continue
            image.setPixelColor(x, y, QColor(src.red(), src.green(), src.blue(), int(255 * alpha)))
    if sample_size != size:
        image = image.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if len(_BRUSH_STAMP_IMAGE_CACHE) > 96:
        _BRUSH_STAMP_IMAGE_CACHE.pop(next(iter(_BRUSH_STAMP_IMAGE_CACHE)))
    _BRUSH_STAMP_IMAGE_CACHE[cache_key] = image
    return image


class DesktopColorSamplerOverlay(QWidget):
    """Temporary full-desktop eyedropper overlay that samples from pre-captured screens."""

    color_picked = Signal(QColor)
    canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self._screens: list[tuple[QRect, QImage]] = []
        virtual_rect = QRect()
        for screen in QApplication.screens():
            geometry = screen.geometry()
            pixmap = screen.grabWindow(0)
            image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
            self._screens.append((QRect(geometry), image))
            virtual_rect = geometry if virtual_rect.isNull() else virtual_rect.united(geometry)
        if virtual_rect.isNull():
            virtual_rect = QApplication.primaryScreen().geometry() if QApplication.primaryScreen() else QRect(0, 0, 1, 1)
        self.setGeometry(virtual_rect)
        self._last_global_pos = QCursor.pos()

    def _color_at_global(self, global_pos: QPoint) -> QColor:
        for geometry, image in self._screens:
            if geometry.contains(global_pos) and not image.isNull():
                local_x = global_pos.x() - geometry.x()
                local_y = global_pos.y() - geometry.y()
                scale_x = image.width() / float(max(1, geometry.width()))
                scale_y = image.height() / float(max(1, geometry.height()))
                px = max(0, min(image.width() - 1, int(local_x * scale_x)))
                py = max(0, min(image.height() - 1, int(local_y * scale_y)))
                return image.pixelColor(px, py)
        return QColor()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pos = self.mapFromGlobal(self._last_global_pos)
        color = self._color_at_global(self._last_global_pos)
        painter.setPen(QPen(QColor(5, 12, 18, 230), 4))
        painter.setBrush(QBrush(color if color.isValid() else QColor(255, 255, 255)))
        painter.drawEllipse(QRectF(pos.x() + 18, pos.y() + 18, 34, 34))
        painter.setPen(QPen(QColor(230, 245, 250, 235), 1))
        painter.drawEllipse(QRectF(pos.x() + 18, pos.y() + 18, 34, 34))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.setPen(QPen(QColor(5, 12, 18, 230), 3))
        painter.drawText(pos.x() + 60, pos.y() + 40, "Click to sample color. Esc cancels.")
        painter.setPen(QPen(QColor(230, 245, 250, 235), 1))
        painter.drawText(pos.x() + 60, pos.y() + 40, "Click to sample color. Esc cancels.")
        painter.end()

    def mouseMoveEvent(self, event):
        self._last_global_pos = event.globalPosition().toPoint()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            color = self._color_at_global(event.globalPosition().toPoint())
            if color.isValid():
                self.color_picked.emit(color)
            self.close()
            return
        self.canceled.emit()
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.canceled.emit()
            self.close()
            return
        super().keyPressEvent(event)


class PortBoundDccBridge:
    """Adapter that routes a DCC bridge call to one explicit localhost port."""

    def __init__(self, provider: str, bridge: Any, port: int):
        self.provider = dcc_provider_base_key(provider)
        self.bridge = bridge
        self.port = int(port)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.bridge, name)

    def find_port(self, host: str = "127.0.0.1") -> int:
        return self.port

    def execute(self, code: str, timeout: float = 10.0, cancel_event: Any = None) -> tuple[bool, str]:
        if hasattr(self.bridge, "execute_on_port"):
            try:
                return self.bridge.execute_on_port(code, port=self.port, timeout=timeout, cancel_event=cancel_event)
            except TypeError:
                return self.bridge.execute_on_port(code, port=self.port, timeout=timeout)
        if self.provider == "unity":
            payload = json.dumps({"code": code}).encode("utf-8") + b"\n"
        else:
            encoded = base64.b64encode(code.encode("utf-8")).decode("utf-8")
            payload = json.dumps({"code_b64": encoded}).encode("utf-8") + b"\n"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(("127.0.0.1", self.port))
                sock.sendall(payload)
                chunks: list[str] = []
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return False, f"{self.provider} command canceled."
                    data = sock.recv(4096)
                    if not data:
                        break
                    chunks.append(data.decode("utf-8", errors="replace"))
                    if "\n" in chunks[-1]:
                        break
            raw = "".join(chunks).strip()
            if not raw:
                return True, f"{self.provider} returned no output."
            try:
                parsed = json.loads(raw)
                return bool(parsed.get("ok", True)), str(parsed.get("result") or parsed.get("error") or raw).strip()
            except Exception:
                return True, raw
        except Exception as exc:
            return False, str(exc)

    def get_scene_snapshot(self, **kwargs) -> tuple[bool, dict[str, Any] | str]:
        timeout = float(kwargs.pop("timeout", 10.0))
        cancel_event = kwargs.pop("cancel_event", None)
        if callable(getattr(self.bridge, "get_scene_snapshot", None)):
            try:
                return self.bridge.get_scene_snapshot(
                    port=self.port,
                    timeout=timeout,
                    cancel_event=cancel_event,
                    **kwargs,
                )
            except TypeError:
                return self.bridge.get_scene_snapshot(
                    port=self.port,
                    timeout=timeout,
                    **kwargs,
                )
        if not hasattr(self.bridge, "get_scene_snapshot_code"):
            return False, f"{self.provider} bridge does not expose scene snapshot code."
        code = self.bridge.get_scene_snapshot_code(**kwargs)
        ok, raw = self.execute(code, timeout=timeout, cancel_event=cancel_event)
        if not ok:
            return False, raw
        if self.provider == "maya":
            try:
                data = json.loads(str(raw or "{}"))
                from tech_connector.bridges.maya.maya_bridge import decode_maya_snapshot_geometry

                data = decode_maya_snapshot_geometry(data)
                data.setdefault("provider_id", self.provider)
                return True, data
            except Exception as exc:
                return False, f"Could not parse Maya scene snapshot JSON: {exc}\n{raw}"
        from tech_connector.game_engine.integration.scene_snapshot_provider import parse_scene_snapshot_output
        return parse_scene_snapshot_output(raw, self.provider)


class DccSceneImportDialog(QDialog):
    """Choose one or more connected DCC scene endpoints to reference into the viewer."""

    def __init__(self, sources: list[dict[str, Any]], parent=None, *, title: str = "Import DCC Scene", message: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 360)
        self.selected_sources: list[dict[str, Any]] = []
        layout = QVBoxLayout(self)
        header = QLabel(message or "Select one or more live DCC scenes to reference into the viewer.")
        header.setStyleSheet("color:#d7f7ff;")
        layout.addWidget(header)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["DCC", "Session", "Open File", "Objects", "Selection"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(
            "QTreeWidget { background:#071018; alternate-background-color:#091722; color:#d7f7ff; border:1px solid #1a2938; } "
            "QTreeWidget::item:selected { background:#12324a; color:#16f26a; } "
            "QHeaderView::section { background:#0b1118; color:#9cc7d8; border:0; padding:4px; }"
        )
        for source in sources:
            scene = str(source.get("scene") or "Untitled")
            item = QTreeWidgetItem(
                [
                    str(source.get("provider") or "").title(),
                    str(source.get("key") or ""),
                    Path(scene).name if scene else "Untitled",
                    str(source.get("object_count", "")),
                    str(source.get("selection_count", "")),
                ]
            )
            item.setToolTip(2, scene)
            item.setData(0, Qt.UserRole, source)
            self.tree.addTopLevelItem(item)
        for col in range(5):
            self.tree.resizeColumnToContents(col)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.selected_sources = [
            item.data(0, Qt.UserRole)
            for item in self.tree.selectedItems()
            if isinstance(item.data(0, Qt.UserRole), dict)
        ]
        if not self.selected_sources and self.tree.topLevelItemCount() == 1:
            source = self.tree.topLevelItem(0).data(0, Qt.UserRole)
            if isinstance(source, dict):
                self.selected_sources = [source]
        if not self.selected_sources:
            QMessageBox.information(self, "Import DCC Scene", "Select at least one scene to import.")
            return
        super().accept()


class TimelineFrameArchive:
    """Disk-backed float archive shared by cached frame snapshots."""

    MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024

    def __init__(self, path: str, mapping: mmap.mmap, frame_count: int, floats_per_frame: int):
        self.path = str(path)
        self.mapping = mapping
        self.frame_count = int(frame_count)
        self.floats_per_frame = int(floats_per_frame)
        self.float_view = memoryview(mapping).cast("f")
        self._closed = False

    @classmethod
    def create(cls, *, provider: str, frame_count: int, floats_per_frame: int) -> "TimelineFrameArchive":
        frames = max(1, int(frame_count))
        floats = max(1, int(floats_per_frame))
        required_bytes = frames * floats * 4
        cache_dir = Path(tempfile.gettempdir()) / "tech_connector" / "timeline_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        free_bytes = int(shutil.disk_usage(cache_dir).free)
        allowed_bytes = min(cls.MAX_ARCHIVE_BYTES, max(0, free_bytes // 2))
        if required_bytes > allowed_bytes:
            raise OSError(
                f"timeline cache needs {required_bytes / (1024 ** 3):.2f} GB; "
                f"safe cache budget is {allowed_bytes / (1024 ** 3):.2f} GB"
            )
        safe_provider = "".join(character if character.isalnum() else "_" for character in str(provider or "dcc"))[:48]
        descriptor, path = tempfile.mkstemp(prefix=f"{safe_provider}_", suffix=".f32cache", dir=str(cache_dir))
        try:
            os.ftruncate(descriptor, required_bytes)
            mapping = mmap.mmap(descriptor, required_bytes, access=mmap.ACCESS_WRITE)
        except Exception:
            os.close(descriptor)
            try:
                os.unlink(path)
            except Exception:
                pass
            raise
        os.close(descriptor)
        return cls(path, mapping, frames, floats)

    @property
    def size_bytes(self) -> int:
        return self.frame_count * self.floats_per_frame * 4

    def write_frame(self, slot: int, packed: Any) -> int:
        if self._closed:
            raise RuntimeError("timeline archive is closed")
        frame_slot = int(slot)
        if not 0 <= frame_slot < self.frame_count:
            raise IndexError(f"timeline archive slot {frame_slot} is out of range")
        if len(packed) != self.floats_per_frame:
            raise ValueError(
                f"timeline frame has {len(packed)} floats; expected {self.floats_per_frame}"
            )
        source = memoryview(packed)
        source_bytes = source if source.format == "B" else source.cast("B")
        byte_offset = frame_slot * self.floats_per_frame * 4
        self.mapping[byte_offset : byte_offset + len(source_bytes)] = source_bytes
        return frame_slot * self.floats_per_frame

    def close(self, *, delete: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.float_view.release()
        except Exception:
            LOGGER.debug("Could not release the timeline cache view during cleanup.", exc_info=True)
        try:
            self.mapping.close()
        except Exception:
            LOGGER.debug("Could not close the mapped timeline cache during cleanup.", exc_info=True)
        if delete:
            try:
                os.unlink(self.path)
            except Exception:
                pass

    def __del__(self):
        try:
            self.close(delete=True)
        except Exception:
            LOGGER.debug("Could not clean up the timeline archive.", exc_info=True)


class EffectBakeWorker(QObject):
    progress = Signal(int, int, int, float)
    finished = Signal(object, bool, str)

    def __init__(self, world: Any, *, start_frame: int, end_frame: int, frame_rate: float):
        super().__init__()
        self.world = copy.deepcopy(world)
        self.start_frame = int(start_frame)
        self.end_frame = int(end_frame)
        self.frame_rate = float(frame_rate)
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            from tech_connector.game_engine.runtime.tc_effect_system_service import bake_effect_system

            def report(completed: int, total: int, frame: int) -> None:
                elapsed = max(1.0e-6, time.perf_counter() - started)
                self.progress.emit(int(completed), int(total), int(frame), float(completed) / elapsed)

            cache = bake_effect_system(
                self.world,
                start_frame=self.start_frame,
                end_frame=self.end_frame,
                frame_rate=self.frame_rate,
                progress_callback=report,
                cancel_event=self._cancel_event,
            )
            canceled = bool(cache.metadata.get("canceled"))
            message = (
                f"Effect bake canceled after {len(cache.frames)} frame(s)."
                if canceled else f"Baked {len(cache.frames)} effect frame(s)."
            )
            self.finished.emit(cache, not canceled, message)
        except Exception as exc:
            self.finished.emit(None, False, f"Effect bake failed: {exc}")

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()


class DccTimelineCacheWorker(QObject):
    frame_cached = Signal(str, int, dict)
    progress = Signal(str, int, int, int, float)
    finished = Signal(str, bool, str)

    def __init__(
        self,
        *,
        provider: str,
        frame_start: int,
        frame_end: int,
        target_native_ids: list[str],
        priority_frame: int | None = None,
        cached_frames: list[int] | None = None,
        include_cameras_every: int = 24,
        timeout: float = 10.0,
    ):
        super().__init__()
        self.provider = str(provider or "").strip().lower()
        self.frame_start = int(frame_start)
        self.frame_end = int(frame_end)
        self.target_native_ids = [str(item) for item in (target_native_ids or []) if str(item)]
        self.priority_frame = int(priority_frame) if priority_frame is not None else self.frame_start
        self.cached_frames = {int(frame) for frame in (cached_frames or [])}
        self.include_cameras_every = max(1, int(include_cameras_every or 24))
        self.timeout = float(timeout or 10.0)
        self._cancel_event = threading.Event()
        self._archive: TimelineFrameArchive | None = None
        self._source_revision: int | None = None

    @Slot()
    def run(self) -> None:
        start_time = time.perf_counter()
        provider_base = dcc_provider_base_key(self.provider)
        if provider_base != "maya":
            self.finished.emit(self.provider, False, "Timeline caching is currently implemented for Maya sessions first.")
            return
        if not self.target_native_ids:
            self.finished.emit(self.provider, False, "No cacheable Maya proxies are loaded.")
            return
        try:
            from tech_connector.bridges.maya.maya_bridge import MayaBridge

            bridge = MayaBridge()
            forced_port = None
            if ":" in self.provider:
                try:
                    forced_port = int(self.provider.split(":", 1)[1])
                except Exception:
                    forced_port = None
            port = forced_port or bridge.find_port()
            if not port:
                self.finished.emit(self.provider, False, "No Maya commandPort found for timeline cache.")
                return
            total = max(0, self.frame_end - self.frame_start + 1)
            if total <= 0:
                self.finished.emit(self.provider, False, "Invalid Maya frame range for timeline cache.")
                return
            priority = max(self.frame_start, min(self.frame_end, self.priority_frame))
            frame_order = list(range(priority, self.frame_end + 1)) + list(range(self.frame_start, priority))
            frame_order = [frame for frame in frame_order if frame not in self.cached_frames]
            if not frame_order:
                self.finished.emit(self.provider, True, f"All {total} frame(s) are already cached for {self.provider}.")
                return
            original_frame = None
            ok, raw = bridge.execute_on_port(
                "import maya.cmds as cmds\nprint(cmds.currentTime(q=True))",
                port=port,
                timeout=min(self.timeout, 3.0),
                cancel_event=self._cancel_event,
            )
            if ok:
                try:
                    original_frame = float(str(raw).strip())
                except Exception:
                    original_frame = None
            sampler_ready, _sampler_message = bridge.prepare_fast_timeline_sampler(
                port=port,
                target_native_ids=self.target_native_ids,
                max_vertices_per_object=200000,
                timeout=self.timeout,
                cancel_event=self._cancel_event,
            )

            def restore_original_frame() -> None:
                if original_frame is None:
                    return
                bridge.execute_on_port(
                    f"import maya.cmds as cmds\ncmds.currentTime({original_frame!r}, edit=True, update=True)\ncmds.refresh()\nprint('OK')",
                    port=port,
                    timeout=min(self.timeout, 1.0 if self._cancel_event.is_set() else 5.0),
                )

            completed = 0
            for offset, frame in enumerate(frame_order, start=1):
                if self._cancel_event.is_set():
                    break
                include_cameras = offset == 1 or offset % self.include_cameras_every == 0
                if sampler_ready:
                    ok, snapshot = bridge.get_fast_timeline_sample(
                        port=port,
                        frame=frame,
                        include_cameras=include_cameras,
                        timeout=self.timeout,
                        cancel_event=self._cancel_event,
                    )
                else:
                    ok, snapshot = bridge.get_scene_snapshot(
                        selected_only=False,
                        meshes_only=False,
                        include_geometry=True,
                        include_cameras=include_cameras,
                        include_faces=False,
                        target_native_ids=self.target_native_ids,
                        limit=max(1, min(500, len(self.target_native_ids))),
                        max_vertices_per_object=200000,
                        max_faces_per_object=200000,
                        timeout=self.timeout,
                        port=port,
                        sample_frame=frame,
                        fast_sample=True,
                        suspend_refresh=True,
                        cancel_event=self._cancel_event,
                    )
                if self._cancel_event.is_set():
                    break
                if not ok or not isinstance(snapshot, dict):
                    restore_original_frame()
                    self.finished.emit(self.provider, False, f"Could not cache Maya frame {frame}: {str(snapshot)[:180]}")
                    return
                try:
                    snapshot = self._archive_frame_snapshot(snapshot, frame, len(frame_order), completed)
                except Exception as exc:
                    restore_original_frame()
                    self.finished.emit(self.provider, False, f"Could not archive Maya frame {frame}: {exc}")
                    return
                self.frame_cached.emit(self.provider, int(frame), snapshot)
                completed += 1
                elapsed = max(1.0e-6, time.perf_counter() - start_time)
                self.progress.emit(self.provider, int(frame), completed + len(self.cached_frames), total, float(completed) / elapsed)
            restore_original_frame()
            if self._cancel_event.is_set():
                self.finished.emit(self.provider, False, f"Timeline cache canceled after {completed} new frame(s).")
            else:
                self.finished.emit(self.provider, True, f"Cached {completed} new frame(s) for {self.provider}.")
        except Exception as exc:
            self.finished.emit(self.provider, False, f"Timeline cache failed: {exc}")

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()

    def _archive_frame_snapshot(
        self,
        snapshot: dict[str, Any],
        frame: int,
        frame_count: int,
        slot: int,
    ) -> dict[str, Any]:
        if self._cancel_event.is_set():
            raise RuntimeError("timeline cache canceled")
        packed = None
        raw_revision = snapshot.get("scene_revision")
        if raw_revision is not None:
            revision = int(raw_revision)
            if self._source_revision is None:
                self._source_revision = revision
            elif revision != self._source_revision:
                raise RuntimeError(
                    f"source scene changed during caching (revision {self._source_revision} -> {revision})"
                )
        for obj in snapshot.get("objects") or []:
            geometry = obj.get("geometry") if isinstance(obj, dict) else None
            candidate = geometry.get("vertices_f32") if isinstance(geometry, dict) else None
            if candidate is not None:
                packed = candidate
                break
        if packed is None:
            return snapshot
        float_count = len(packed)
        if self._archive is None:
            self._archive = TimelineFrameArchive.create(
                provider=self.provider,
                frame_count=max(1, int(frame_count)),
                floats_per_frame=float_count,
            )
        if self._archive.floats_per_frame != float_count:
            raise ValueError(
                f"topology changed from {self._archive.floats_per_frame} to {float_count} floats"
            )
        frame_float_offset = self._archive.write_frame(int(slot), packed)
        for obj in snapshot.get("objects") or []:
            geometry = obj.get("geometry") if isinstance(obj, dict) else None
            if not isinstance(geometry, dict) or geometry.get("vertices_f32") is not packed:
                continue
            geometry["vertices_f32"] = self._archive.float_view
            geometry["vertex_float_offset"] = frame_float_offset + max(
                0,
                int(geometry.get("vertex_float_offset", 0) or 0),
            )
            geometry["vertex_encoding"] = "f32-memoryview"
            geometry["timeline_archive_path"] = self._archive.path
        snapshot["timeline_archive"] = self._archive
        snapshot["timeline_archive_slot"] = int(slot)
        snapshot["timeline_archive_frame"] = int(frame)
        return snapshot


def scene_snapshot_bridge_for_provider(provider: str):
    provider_raw = str(provider or "").strip().lower()
    provider_key = dcc_provider_base_key(provider_raw)
    forced_port = None
    if ":" in provider_raw:
        try:
            forced_port = int(provider_raw.split(":", 1)[1])
        except Exception:
            forced_port = None
    if provider_key == "maya":
        from tech_connector.bridges.maya.maya_bridge import MayaBridge

        bridge = MayaBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "blender":
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge

        bridge = BlenderBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "motionbuilder":
        from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge

        bridge = MotionBuilderBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "houdini":
        from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge

        bridge = HoudiniBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key in {"3dsmax", "max"}:
        from tech_connector.bridges.max.max_bridge import MaxBridge

        bridge = MaxBridge()
        return PortBoundDccBridge("3dsmax", bridge, forced_port) if forced_port else bridge
    if provider_key == "unreal":
        from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

        return UnrealBridge(forced_port=forced_port)
    if provider_key == "unity":
        from tech_connector.bridges.unity.unity_bridge import UnityBridge

        bridge = UnityBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "substance_painter":
        from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge

        bridge = SubstancePainterBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "photoshop":
        from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge

        bridge = PhotoshopBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    if provider_key == "gimp":
        from tech_connector.bridges.gimp.gimp_bridge import GimpBridge

        bridge = GimpBridge()
        return PortBoundDccBridge(provider_key, bridge, forced_port) if forced_port else bridge
    raise ValueError(f"No scene snapshot bridge is registered for {provider}.")


class DccSceneSnapshotWorker(QObject):
    snapshots_ready = Signal(dict, list)

    def __init__(self, requests: list[dict[str, Any]]):
        super().__init__()
        self.requests = list(requests or [])

    @Slot()
    def run(self) -> None:
        snapshots: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for request in self.requests:
            provider = str(request.get("provider") or "").strip().lower()
            kwargs = dict(request.get("kwargs") or {})
            if not provider:
                continue
            try:
                fast_live_targets = [str(item) for item in (request.get("maya_fast_live_targets") or []) if str(item)]
                if dcc_provider_base_key(provider) == "maya" and fast_live_targets:
                    from tech_connector.bridges.maya.maya_bridge import MayaBridge

                    raw_bridge = MayaBridge()
                    forced_port = None
                    if ":" in provider:
                        try:
                            forced_port = int(provider.split(":", 1)[1])
                        except Exception:
                            forced_port = None
                    port = forced_port or raw_bridge.find_port()
                    if not port:
                        errors.append(f"{provider}: no Maya commandPort found")
                        continue
                    deformation_binding = request.get("maya_deformation_binding")
                    gpu_skinning_enabled = bool(request.get("maya_gpu_skinning_enabled"))
                    runtime_summary = (
                        deformation_binding.get("runtime_summary")
                        if isinstance(deformation_binding, dict)
                        else {}
                    ) or {}
                    gpu_skinning_enabled = bool(
                        gpu_skinning_enabled
                        and int(runtime_summary.get("gpu_top4_meshes", 0) or 0)
                        + int(runtime_summary.get("gpu_top8_meshes", 0) or 0)
                        + int(runtime_summary.get("gpu_sparse_meshes", 0) or 0) > 0
                    )
                    if (
                        isinstance(deformation_binding, dict)
                        and not deformation_binding.get("contract_errors")
                        and (
                            gpu_skinning_enabled
                            or bool(runtime_summary.get("hybrid_enabled"))
                        )
                    ):
                        pose_ok, pose = raw_bridge.get_fast_deformation_sample(
                            port=int(port),
                            frame=None,
                            timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                        )
                        if not pose_ok or not isinstance(pose, dict):
                            ready, _message = raw_bridge.prepare_fast_deformation_sampler(
                                port=int(port),
                                binding=deformation_binding,
                                timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                            )
                            if ready:
                                pose_ok, pose = raw_bridge.get_fast_deformation_sample(
                                    port=int(port),
                                    frame=None,
                                    timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                                )
                        if pose_ok and isinstance(pose, dict):
                            runtime_key = "gpu_runtime_mode" if gpu_skinning_enabled else "runtime_mode"
                            skeletal_meshes = [
                                mesh for mesh in deformation_binding.get("meshes") or []
                                if mesh.get(runtime_key) == "skeletal"
                                and str(mesh.get("native_id") or "") in fast_live_targets
                            ]
                            fallback_targets = [
                                str(mesh.get("native_id") or "")
                                for mesh in deformation_binding.get("meshes") or []
                                if mesh.get(runtime_key) != "skeletal"
                                and str(mesh.get("native_id") or "") in fast_live_targets
                            ]
                            fallback_packet: dict[str, Any] = {}
                            if fallback_targets:
                                ok, fallback_or_error = raw_bridge.get_fast_timeline_sample(
                                    port=int(port),
                                    frame=None,
                                    include_cameras=True,
                                    timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                                )
                                sampled_targets = (
                                    list((fallback_or_error.get("isolation") or {}).get("target_native_ids") or [])
                                    if ok and isinstance(fallback_or_error, dict)
                                    else []
                                )
                                if not ok or sampled_targets != fallback_targets:
                                    ready, _message = raw_bridge.prepare_fast_timeline_sampler(
                                        port=int(port),
                                        target_native_ids=fallback_targets,
                                        max_vertices_per_object=500000,
                                        timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                                    )
                                    if ready:
                                        ok, fallback_or_error = raw_bridge.get_fast_timeline_sample(
                                            port=int(port),
                                            frame=None,
                                            include_cameras=True,
                                            timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                                        )
                                if ok and isinstance(fallback_or_error, dict):
                                    fallback_packet = fallback_or_error
                                else:
                                    errors.append(f"{provider}: {str(fallback_or_error)[:180]}")
                            object_poses = {
                                str(item.get("native_id") or ""): item
                                for item in pose.get("objects") or []
                                if isinstance(item, dict)
                            }
                            skeletal_objects = []
                            for mesh in ([] if gpu_skinning_enabled else skeletal_meshes):
                                native_id = str(mesh.get("native_id") or "")
                                try:
                                    reconstructed = reconstruct_linear_blend_positions(
                                        deformation_binding,
                                        pose,
                                        native_id,
                                    )
                                except Exception as exc:
                                    errors.append(f"{provider}:{native_id}: skeletal fallback ({str(exc)[:100]})")
                                    continue
                                object_pose = object_poses.get(native_id) or {}
                                skeletal_objects.append({
                                    "native_id": native_id,
                                    "name": native_id.split("|")[-1],
                                    "type": "mesh",
                                    "visible": True,
                                    "world_matrix": list(object_pose.get("world_matrix") or []),
                                    "geometry": {
                                        "representation": "mesh",
                                        "coordinate_space": "object",
                                        "vertex_count": int(mesh.get("vertex_count", 0) or 0),
                                        "vertices_f32": reconstructed.reshape(-1),
                                        "vertex_encoding": "f32-array",
                                        "faces": [],
                                        "topology_included": False,
                                    },
                                })
                            packet = dict(fallback_packet)
                            packet.update({
                                "provider_id": "maya",
                                "scene": deformation_binding.get("scene", ""),
                                "unit_linear": deformation_binding.get("unit_linear", "cm"),
                                "up_axis": deformation_binding.get("up_axis", "y"),
                                "current_time": pose.get("current_time"),
                                "scene_revision": pose.get("scene_revision"),
                                "objects": skeletal_objects + list(fallback_packet.get("objects") or []),
                                "deformation_pose": pose if gpu_skinning_enabled else None,
                                "deformation_runtime": {
                                    "skeletal_meshes": len(skeletal_meshes),
                                    "gpu_skeletal_meshes": len(skeletal_meshes) if gpu_skinning_enabled else 0,
                                    "point_cache_meshes": len(fallback_packet.get("objects") or []),
                                },
                            })
                            snapshots[provider] = normalize_frame_delta(packet, provider)
                            continue
                    ok, snapshot_or_error = raw_bridge.get_fast_timeline_sample(
                        port=int(port),
                        frame=None,
                        include_cameras=True,
                        timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                    )
                    sampled_targets = (
                        list((snapshot_or_error.get("isolation") or {}).get("target_native_ids") or [])
                        if ok and isinstance(snapshot_or_error, dict)
                        else []
                    )
                    if not ok or sampled_targets != fast_live_targets:
                        ready, _message = raw_bridge.prepare_fast_timeline_sampler(
                            port=int(port),
                            target_native_ids=fast_live_targets,
                            max_vertices_per_object=200000,
                            timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                        )
                        if ready:
                            ok, snapshot_or_error = raw_bridge.get_fast_timeline_sample(
                                port=int(port),
                                frame=None,
                                include_cameras=True,
                                timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                            )
                    if ok and isinstance(snapshot_or_error, dict):
                        snapshots[provider] = snapshot_or_error
                    else:
                        errors.append(f"{provider}: {str(snapshot_or_error)[:180]}")
                    continue
                blender_fast_targets = [str(item) for item in (request.get("blender_fast_live_targets") or []) if str(item)]
                if dcc_provider_base_key(provider) == "blender" and blender_fast_targets:
                    from tech_connector.bridges.blender.blender_bridge import BlenderBridge

                    raw_bridge = BlenderBridge()
                    forced_port = None
                    if ":" in provider:
                        try:
                            forced_port = int(provider.split(":", 1)[1])
                        except Exception:
                            forced_port = None
                    port = forced_port or raw_bridge.find_port()
                    if not port:
                        errors.append(f"{provider}: no Blender bridge port found")
                        continue
                    ok, snapshot_or_error = raw_bridge.get_fast_timeline_sample(
                        port=int(port),
                        target_native_ids=blender_fast_targets,
                        frame=None,
                        include_cameras=True,
                        timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                    )
                    if ok and isinstance(snapshot_or_error, dict):
                        snapshots[provider] = snapshot_or_error
                    else:
                        errors.append(f"{provider}: {str(snapshot_or_error)[:180]}")
                    continue
                houdini_fast_targets = [str(item) for item in (request.get("houdini_fast_live_targets") or []) if str(item)]
                if dcc_provider_base_key(provider) == "houdini" and houdini_fast_targets:
                    from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge

                    raw_bridge = HoudiniBridge()
                    forced_port = None
                    if ":" in provider:
                        try:
                            forced_port = int(provider.split(":", 1)[1])
                        except Exception:
                            forced_port = None
                    port = forced_port or raw_bridge.find_port()
                    if not port:
                        errors.append(f"{provider}: no Houdini bridge port found")
                        continue
                    ok, snapshot_or_error = raw_bridge.get_fast_timeline_sample(
                        port=int(port),
                        target_native_ids=houdini_fast_targets,
                        frame=None,
                        include_cameras=True,
                        timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                    )
                    if ok and isinstance(snapshot_or_error, dict):
                        snapshots[provider] = snapshot_or_error
                    else:
                        errors.append(f"{provider}: {str(snapshot_or_error)[:180]}")
                    continue
                bridge = scene_snapshot_bridge_for_provider(provider)
                try:
                    ok, snapshot_or_error = bridge.get_scene_snapshot(**kwargs)
                except TypeError:
                    ok, snapshot_or_error = bridge.get_scene_snapshot(
                        selected_only=bool(kwargs.get("selected_only", False)),
                        limit=int(kwargs.get("limit", 500) or 500),
                        timeout=float(kwargs.get("timeout", 10.0) or 10.0),
                    )
                if ok and isinstance(snapshot_or_error, dict):
                    snapshots[provider] = snapshot_or_error
                else:
                    errors.append(f"{provider}: {str(snapshot_or_error)[:180]}")
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
        self.snapshots_ready.emit(snapshots, errors)


class DccSceneModelCompileWorker(QObject):
    """Compile large provider snapshots without occupying Qt's UI thread."""

    finished = Signal(object, str, float)

    def __init__(
        self,
        snapshots: list[dict[str, Any]],
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
        retained_models: list[Any] | None = None,
    ):
        super().__init__()
        self.snapshots = list(snapshots or [])
        self.scene_center = scene_center
        self.scene_scale = scene_scale
        self.retained_models = list(retained_models or [])
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            if self._cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            model = FBXMeshModel.from_scene_snapshots(
                self.snapshots,
                scene_center=self.scene_center,
                scene_scale=self.scene_scale,
                retained_models=self.retained_models,
                cancel_event=self._cancel_event,
            )
            if self._cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            self.finished.emit(model, "", (time.perf_counter() - started) * 1000.0)
        except Exception as exc:
            self.finished.emit(None, str(exc), (time.perf_counter() - started) * 1000.0)

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()


class DccSceneRestoreWorker(QObject):
    """Reconnect, launch, and snapshot linked DCC sources outside Qt's UI thread."""

    finished = Signal(object)

    def __init__(
        self,
        sources: list[dict[str, Any]],
        policy: str,
        discover_sessions: Any,
        open_source: Any,
        capture_snapshot: Any,
        apply_session_state: Any,
    ):
        super().__init__()
        self.sources = [dict(source) for source in sources if isinstance(source, dict)]
        self.policy = str(policy or "ask")
        self.discover_sessions = discover_sessions
        self.open_source = open_source
        self.capture_snapshot = capture_snapshot
        self.apply_session_state = apply_session_state
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        from tech_connector.game_engine.integration.dcc_scene_restoration_service import restore_scene_sources

        try:
            providers = list(dict.fromkeys(
                dcc_provider_base_key(str(source.get("provider") or ""))
                for source in self.sources
                if dcc_provider_base_key(str(source.get("provider") or ""))
            ))

            def discover_linked_sessions() -> list[dict[str, Any]]:
                return self.discover_sessions(providers)

            def open_linked_source(session_key: str, source_path: str) -> tuple[bool, str]:
                return self.open_source(session_key, source_path, self._cancel_event)

            def capture_linked_snapshot(session_key: str) -> tuple[bool, Any]:
                return self.capture_snapshot(session_key, self._cancel_event)

            def apply_linked_session_state(session_key: str, state: dict[str, Any]) -> tuple[bool, str]:
                return self.apply_session_state(session_key, state, self._cancel_event)

            report = restore_scene_sources(
                self.sources,
                policy=self.policy,
                discover_sessions=discover_linked_sessions,
                open_source=open_linked_source,
                capture_snapshot=capture_linked_snapshot,
                apply_session_state=apply_linked_session_state,
                cancel_event=self._cancel_event,
            )
        except Exception as exc:
            report = {
                "policy": self.policy,
                "entries": [],
                "session_keys": [],
                "snapshots": {},
                "launches": [],
                "canceled": self._cancel_event.is_set(),
                "error": str(exc),
            }
        self.finished.emit(report)

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()


class TCSceneConversionWorker(QObject):
    """Capture and convert a live DCC scene without blocking Qt."""

    finished = Signal(bool, object, str)
    progress = Signal(int, str)

    def __init__(self, provider: str, port: int, payload: dict[str, Any]):
        super().__init__()
        self.provider = str(provider or "maya")
        self.port = int(port)
        self.payload = dict(payload or {})
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.scene.tc_scene_conversion_service import convert_to_tc

            result = convert_to_tc(
                source_provider=self.provider,
                port=self.port,
                source_native_id=str(self.payload.get("source_native_id") or ""),
                scope=str(self.payload.get("scope") or "scene"),
                include_animation=bool(self.payload.get("include_animation", True)),
                include_materials=bool(self.payload.get("include_materials", True)),
                progress_callback=self.progress.emit,
                cancel_event=self._cancel_event,
            )
            self.finished.emit(True, result, "Live DCC conversion complete.")
        except Exception as exc:
            self.finished.emit(False, None, str(exc))


class DccDeformationBindingWorker(QObject):
    """Build and calibrate a Maya skin cache without blocking the viewer UI."""

    finished = Signal(str, bool, object, str)

    def __init__(
        self,
        provider: str,
        target_native_ids: list[str],
        request_fingerprint: str = "",
    ):
        super().__init__()
        self.provider = str(provider or "").strip().lower()
        self.target_native_ids = [str(item) for item in target_native_ids if str(item)]
        self.request_fingerprint = str(request_fingerprint or "")
        self._cancel_event = threading.Event()

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise RuntimeError("Skeletal cache canceled.")

    @Slot()
    def run(self) -> None:
        original_frame = None
        run_started = time.perf_counter()
        build_timings_ms: dict[str, float] = {}
        try:
            import numpy as np
            from tech_connector.bridges.maya.maya_bridge import MayaBridge

            bridge = MayaBridge()
            forced_port = None
            if ":" in self.provider:
                try:
                    forced_port = int(self.provider.split(":", 1)[1])
                except Exception:
                    forced_port = None
            port = forced_port or bridge.find_port()
            if not port:
                raise RuntimeError("No Maya commandPort found for deformation binding.")
            self._raise_if_cancelled()
            phase_started = time.perf_counter()
            ok, binding = bridge.get_deformation_binding(
                port=int(port),
                target_native_ids=self.target_native_ids,
                timeout=120.0,
                cancel_event=self._cancel_event,
            )
            if not ok or not isinstance(binding, dict):
                raise RuntimeError(str(binding))
            build_timings_ms["binding"] = (time.perf_counter() - phase_started) * 1000.0
            self._raise_if_cancelled()
            topology_note = ""
            phase_started = time.perf_counter()
            topology_ok, topology = bridge.get_rig_topology(
                port=int(port),
                target_native_ids=self.target_native_ids,
                include_attribute_values=True,
                timeout=120.0,
                cancel_event=self._cancel_event,
            )
            build_timings_ms["topology"] = (time.perf_counter() - phase_started) * 1000.0
            self._raise_if_cancelled()
            if topology_ok and isinstance(topology, dict):
                binding["rig_topology"] = topology
                topology_note = (
                    f" {len(topology.get('nodes') or [])} rig node(s) and "
                    f"{len(topology.get('connections') or [])} connection(s) captured."
                )
                if topology.get("truncated"):
                    topology_note += " Rig graph reached its configured safety limit."
            else:
                binding["rig_topology_warning"] = str(topology)
                topology_note = f" Rig topology warning: {str(topology)[:180]}"
            original_frame = float(binding.get("current_time", 0.0) or 0.0)
            phase_started = time.perf_counter()
            ready, message = bridge.prepare_fast_deformation_sampler(
                port=int(port),
                binding=binding,
                timeout=30.0,
                cancel_event=self._cancel_event,
            )
            if not ready:
                raise RuntimeError(str(message))
            ready, message = bridge.prepare_fast_timeline_sampler(
                port=int(port),
                target_native_ids=self.target_native_ids,
                max_vertices_per_object=500000,
                timeout=30.0,
                cancel_event=self._cancel_event,
            )
            if not ready:
                raise RuntimeError(str(message))
            build_timings_ms["sampler_setup"] = (time.perf_counter() - phase_started) * 1000.0

            start = float(binding.get("frame_start", original_frame) or original_frame)
            end = float(binding.get("frame_end", original_frame) or original_frame)
            calibration_frames = list(dict.fromkeys((original_frame, start, (start + end) * 0.5, end)))
            initial_pose: dict[str, Any] | None = None
            metrics_by_mesh: dict[str, list[dict[str, Any]]] = {
                str(mesh.get("native_id") or ""): [] for mesh in binding.get("meshes") or []
            }
            gpu_metrics_by_mesh: dict[str, list[dict[str, Any]]] = {
                str(mesh.get("native_id") or ""): [] for mesh in binding.get("meshes") or []
            }
            gpu_top8_metrics_by_mesh: dict[str, list[dict[str, Any]]] = {
                str(mesh.get("native_id") or ""): [] for mesh in binding.get("meshes") or []
            }
            skeleton_joint_counts = {
                str(skeleton.get("native_id") or ""): len(skeleton.get("joints") or [])
                for skeleton in binding.get("skeletons") or []
            }
            phase_started = time.perf_counter()
            for mesh in binding.get("meshes") or []:
                self._raise_if_cancelled()
                if mesh.get("deformation_mode") != "linear_blend_skinning":
                    continue
                joint_count = skeleton_joint_counts.get(str(mesh.get("skeleton_id") or ""), 0)
                try:
                    packed = build_top4_skinning_buffers(mesh, joint_count)
                    mesh["gpu_joint_indices_u16"] = packed["joint_indices_u16"]
                    mesh["gpu_weights_f32"] = packed["weights_f32"]
                    mesh["gpu_weight_reduction"] = {
                        key: value for key, value in packed.items()
                        if key not in {"joint_indices_u16", "weights_f32"}
                    }
                    packed8 = build_top8_skinning_buffers(mesh, joint_count)
                    mesh["gpu_joint_indices_u16_8"] = packed8["joint_indices_u16"]
                    mesh["gpu_weights_f32_8"] = packed8["weights_f32"]
                    mesh["gpu_weight_reduction_8"] = {
                        key: value for key, value in packed8.items()
                        if key not in {"joint_indices_u16", "weights_f32"}
                    }
                except Exception as exc:
                    mesh["gpu_weight_reduction"] = {"error": str(exc)}
                    mesh["gpu_weight_reduction_8"] = {"error": str(exc)}
            build_timings_ms["gpu_influence_packing"] = (time.perf_counter() - phase_started) * 1000.0
            phase_started = time.perf_counter()
            for frame in calibration_frames:
                self._raise_if_cancelled()
                pose_ok, pose = bridge.get_fast_deformation_sample(
                    port=int(port), frame=frame, timeout=30.0, cancel_event=self._cancel_event
                )
                if not pose_ok or not isinstance(pose, dict):
                    continue
                point_ok, points = bridge.get_fast_timeline_sample(
                    port=int(port),
                    frame=None,
                    include_cameras=False,
                    timeout=30.0,
                    cancel_event=self._cancel_event,
                )
                self._raise_if_cancelled()
                if not point_ok or not isinstance(points, dict):
                    continue
                if abs(float(frame) - float(original_frame)) <= 1.0e-6:
                    initial_pose = pose
                evaluated_by_id = {
                    str(item.get("native_id") or ""): item
                    for item in points.get("objects") or []
                    if isinstance(item, dict)
                }
                for mesh in binding.get("meshes") or []:
                    native_id = str(mesh.get("native_id") or "")
                    if mesh.get("deformation_mode") != "linear_blend_skinning":
                        continue
                    geometry = (evaluated_by_id.get(native_id) or {}).get("geometry") or {}
                    packed = geometry.get("vertices_f32")
                    vertex_count = int(geometry.get("vertex_count", 0) or 0)
                    if packed is None or vertex_count != int(mesh.get("vertex_count", 0) or 0):
                        continue
                    float_offset = int(geometry.get("vertex_float_offset", 0) or 0)
                    evaluated = np.frombuffer(
                        packed,
                        dtype=np.float32,
                        count=vertex_count * 3,
                        offset=float_offset * 4,
                    ).reshape((-1, 3))
                    rebuilt = reconstruct_linear_blend_positions(binding, pose, native_id)
                    metrics_by_mesh[native_id].append(deformation_parity_metrics(rebuilt, evaluated))
                    if mesh.get("gpu_joint_indices_u16") is not None:
                        rebuilt_gpu = reconstruct_top4_linear_blend_positions(binding, pose, native_id)
                        gpu_metrics_by_mesh[native_id].append(deformation_parity_metrics(rebuilt_gpu, evaluated))
                    if mesh.get("gpu_joint_indices_u16_8") is not None:
                        rebuilt_gpu8 = reconstruct_top8_linear_blend_positions(binding, pose, native_id)
                        gpu_top8_metrics_by_mesh[native_id].append(
                            deformation_parity_metrics(rebuilt_gpu8, evaluated)
                        )
            build_timings_ms["parity_calibration"] = (time.perf_counter() - phase_started) * 1000.0

            accepted = 0
            for mesh in binding.get("meshes") or []:
                native_id = str(mesh.get("native_id") or "")
                samples = metrics_by_mesh.get(native_id) or []
                gpu_samples = gpu_metrics_by_mesh.get(native_id) or []
                gpu_top8_samples = gpu_top8_metrics_by_mesh.get(native_id) or []
                eligible = bool(
                    mesh.get("deformation_mode") == "linear_blend_skinning"
                    and not mesh.get("unsupported_deformers")
                    and samples
                    and all(bool(item.get("accepted")) for item in samples)
                )
                top4_parity_accepted = bool(
                    eligible and gpu_samples and all(bool(item.get("accepted")) for item in gpu_samples)
                )
                top8_parity_accepted = bool(
                    eligible
                    and gpu_top8_samples
                    and all(bool(item.get("accepted")) for item in gpu_top8_samples)
                )
                gpu_influence_mode, gpu_influence_width = select_exact_gpu_skinning_mode(
                    mesh,
                    exact_parity_accepted=eligible,
                    top4_parity_accepted=top4_parity_accepted,
                    top8_parity_accepted=top8_parity_accepted,
                )
                gpu_top4_eligible = gpu_influence_width == 4
                gpu_top8_eligible = gpu_influence_width == 8
                gpu_eligible = gpu_influence_mode != "point_cache"
                mesh["runtime_mode"] = "skeletal" if eligible else "point_cache"
                mesh["gpu_runtime_mode"] = "skeletal" if gpu_eligible else "point_cache"
                mesh["gpu_influence_mode"] = gpu_influence_mode
                mesh["gpu_influence_width"] = gpu_influence_width
                mesh["calibration"] = {
                    "frames": calibration_frames,
                    "sample_count": len(samples),
                    "accepted": eligible,
                    "worst_rms_error": max((float(item.get("rms_error", 0.0)) for item in samples), default=0.0),
                    "worst_max_error": max((float(item.get("max_error", 0.0)) for item in samples), default=0.0),
                    "gpu_top4_sample_count": len(gpu_samples),
                    "gpu_top4_accepted": gpu_top4_eligible,
                    "gpu_top4_worst_rms_error": max(
                        (float(item.get("rms_error", 0.0)) for item in gpu_samples),
                        default=0.0,
                    ),
                    "gpu_top4_worst_max_error": max(
                        (float(item.get("max_error", 0.0)) for item in gpu_samples),
                        default=0.0,
                    ),
                    "gpu_top8_sample_count": len(gpu_top8_samples),
                    "gpu_top8_accepted": gpu_top8_eligible,
                    "gpu_top8_worst_rms_error": max(
                        (float(item.get("rms_error", 0.0)) for item in gpu_top8_samples),
                        default=0.0,
                    ),
                    "gpu_top8_worst_max_error": max(
                        (float(item.get("max_error", 0.0)) for item in gpu_top8_samples),
                        default=0.0,
                    ),
                }
                accepted += int(eligible)

            fallback_targets = [
                str(mesh.get("native_id") or "")
                for mesh in binding.get("meshes") or []
                if mesh.get("runtime_mode") != "skeletal" and str(mesh.get("native_id") or "")
            ]
            hybrid_ms = float("inf")
            full_point_ms = float("inf")
            phase_started = time.perf_counter()
            try:
                benchmark_started = time.perf_counter()
                pose_ok, benchmark_pose = bridge.get_fast_deformation_sample(
                    port=int(port),
                    frame=original_frame,
                    timeout=30.0,
                    cancel_event=self._cancel_event,
                )
                if not pose_ok or not isinstance(benchmark_pose, dict):
                    raise RuntimeError(str(benchmark_pose))
                initial_pose = benchmark_pose
                if fallback_targets:
                    ready, _message = bridge.prepare_fast_timeline_sampler(
                        port=int(port),
                        target_native_ids=fallback_targets,
                        max_vertices_per_object=500000,
                        timeout=30.0,
                        cancel_event=self._cancel_event,
                    )
                    if not ready:
                        raise RuntimeError(str(_message))
                    point_ok, fallback_sample = bridge.get_fast_timeline_sample(
                        port=int(port),
                        frame=None,
                        include_cameras=False,
                        timeout=30.0,
                        cancel_event=self._cancel_event,
                    )
                    if not point_ok:
                        raise RuntimeError(str(fallback_sample))
                for mesh in binding.get("meshes") or []:
                    if mesh.get("runtime_mode") == "skeletal":
                        reconstruct_linear_blend_positions(
                            binding,
                            benchmark_pose,
                            str(mesh.get("native_id") or ""),
                        )
                hybrid_ms = (time.perf_counter() - benchmark_started) * 1000.0

                ready, _message = bridge.prepare_fast_timeline_sampler(
                    port=int(port),
                    target_native_ids=self.target_native_ids,
                    max_vertices_per_object=500000,
                    timeout=30.0,
                    cancel_event=self._cancel_event,
                )
                if not ready:
                    raise RuntimeError(str(_message))
                point_started = time.perf_counter()
                point_ok, full_sample = bridge.get_fast_timeline_sample(
                    port=int(port),
                    frame=None,
                    include_cameras=False,
                    timeout=30.0,
                    cancel_event=self._cancel_event,
                )
                if not point_ok:
                    raise RuntimeError(str(full_sample))
                full_point_ms = (time.perf_counter() - point_started) * 1000.0
            except Exception:
                if self._cancel_event.is_set():
                    raise RuntimeError("Skeletal cache canceled.")
                pass
            build_timings_ms["runtime_benchmark"] = (time.perf_counter() - phase_started) * 1000.0
            self._raise_if_cancelled()
            hybrid_enabled = bool(
                hybrid_ms != float("inf")
                and full_point_ms != float("inf")
                and hybrid_ms <= full_point_ms * 0.9
            )
            sampler_targets = fallback_targets if hybrid_enabled and fallback_targets else self.target_native_ids
            ready, message = bridge.prepare_fast_timeline_sampler(
                port=int(port),
                target_native_ids=sampler_targets,
                max_vertices_per_object=500000,
                timeout=30.0,
                cancel_event=self._cancel_event,
            )
            if not ready:
                raise RuntimeError(str(message))
            binding["runtime_summary"] = {
                "skeletal_meshes": accepted,
                "gpu_top4_meshes": sum(
                    1 for mesh in binding.get("meshes") or []
                    if int(mesh.get("gpu_influence_width", 0) or 0) == 4
                ),
                "gpu_top8_meshes": sum(
                    1 for mesh in binding.get("meshes") or []
                    if int(mesh.get("gpu_influence_width", 0) or 0) == 8
                ),
                "gpu_sparse_meshes": sum(
                    1 for mesh in binding.get("meshes") or []
                    if str(mesh.get("gpu_influence_mode") or "") == "sparse"
                ),
                "gpu_point_cache_meshes": sum(
                    1 for mesh in binding.get("meshes") or []
                    if str(mesh.get("gpu_runtime_mode") or "") != "skeletal"
                ),
                "point_cache_meshes": len(binding.get("meshes") or []) - accepted,
                "calibration_frames": calibration_frames,
                "hybrid_enabled": hybrid_enabled,
                "hybrid_benchmark_ms": None if hybrid_ms == float("inf") else hybrid_ms,
                "full_point_benchmark_ms": None if full_point_ms == float("inf") else full_point_ms,
            }
            build_timings_ms["total"] = (time.perf_counter() - run_started) * 1000.0
            binding["build_timings_ms"] = {
                key: round(value, 3) for key, value in build_timings_ms.items()
            }
            if initial_pose is not None:
                binding["initial_pose"] = initial_pose
                binding_revision = binding.get("scene_revision")
                pose_revision = initial_pose.get("scene_revision")
                if (
                    binding_revision is not None
                    and pose_revision is not None
                    and int(binding_revision) != int(pose_revision)
                ):
                    raise RuntimeError(
                        "Maya scene changed while the skeletal cache was being calibrated."
                    )
            binding["request_fingerprint"] = self.request_fingerprint
            gpu_meshes = sum(
                1 for mesh in binding.get("meshes") or []
                if str(mesh.get("gpu_runtime_mode") or "") == "skeletal"
            )
            runtime_note = (
                f"{gpu_meshes} exact GPU skin(s) ready"
                if gpu_meshes
                else (
                    "hybrid skeletal playback enabled"
                    if hybrid_enabled
                    else "bulk point playback retained until GPU skinning is faster"
                )
            )
            self._raise_if_cancelled()
            self.finished.emit(
                self.provider,
                True,
                binding,
                f"Skeletal cache ready: {accepted}/{len(binding.get('meshes') or [])} mesh(es) passed parity; {runtime_note}.{topology_note}",
            )
        except Exception as exc:
            self.finished.emit(self.provider, False, {}, str(exc))
        finally:
            if original_frame is not None:
                try:
                    from tech_connector.bridges.maya.maya_bridge import MayaBridge

                    bridge = MayaBridge()
                    port = int(self.provider.split(":", 1)[1]) if ":" in self.provider else bridge.find_port()
                    if port:
                        bridge.execute_on_port(
                            f"import maya.cmds as cmds\ncmds.currentTime({float(original_frame)!r}, edit=True, update=True)\nprint(cmds.currentTime(q=True))",
                            port=int(port),
                            timeout=2.0 if self._cancel_event.is_set() else 30.0,
                        )
                except Exception:
                    pass


class NativeFbxImportWorker(QObject):
    finished = Signal(bool, object, str)

    def __init__(self, path: str):
        super().__init__()
        self.path = str(path or "")
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.scene.native_fbx_service import import_native_scene

            asset = import_native_scene(self.path, cancel_event=self._cancel_event)
            self.finished.emit(True, asset, f"Imported scene: {Path(self.path).name}")
        except Exception as exc:
            self.finished.emit(False, None, str(exc))


class UsdCompositionWorker(QObject):
    finished = Signal(bool, object, object, str)

    def __init__(self, composition: object, output_path: str):
        super().__init__()
        self.composition = composition
        self.output_path = str(output_path or "")
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.scene.usd_composition_service import compose_usd_stage

            result = compose_usd_stage(
                self.composition,
                self.output_path,
                cancel_event=self._cancel_event,
            )
            self.finished.emit(True, self.composition, result, f"Composed OpenUSD stage: {Path(self.output_path).name}")
        except Exception as exc:
            self.finished.emit(False, self.composition, None, str(exc))


class SkinWeightFileWorker(QObject):
    finished = Signal(bool, str, object, str)

    def __init__(self, operation: str, arguments: dict[str, Any]):
        super().__init__()
        self.operation = str(operation or "")
        self.arguments = dict(arguments or {})

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.deformation.skinning_tool_service import (
                load_skin_weights_file,
                save_skin_weights_file,
            )

            if self.operation == "export":
                result = save_skin_weights_file(**self.arguments)
                message = f"Exported skin weights: {Path(result['path']).name}"
            elif self.operation == "import":
                result = load_skin_weights_file(**self.arguments)
                message = f"Imported {result.cluster.vertex_count} skin-weight row(s)."
            else:
                raise ValueError(f"Unsupported skin-weight file operation: {self.operation}")
            self.finished.emit(True, self.operation, result, message)
        except Exception as exc:
            self.finished.emit(False, self.operation, None, str(exc))


class MeshLodGenerationWorker(QObject):
    finished = Signal(bool, object, str)

    def __init__(self, request: object):
        super().__init__()
        self.request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.runtime.mesh_lod_service import generate_mesh_lods

            result = generate_mesh_lods(self.request, cancel_event=self._cancel_event)
            self.finished.emit(True, result, f"Generated {len(result.get('levels') or [])} mesh LOD level(s).")
        except Exception as exc:
            self.finished.emit(False, None, str(exc))


class RuntimeGeometryCompileWorker(QObject):
    finished = Signal(bool, str, object, str)

    def __init__(self, kind: str, arguments: dict[str, Any]):
        super().__init__()
        self.kind = str(kind or "")
        self.arguments = dict(arguments or {})
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            from tech_connector.game_engine.runtime.runtime_geometry_compiler_service import (
                compile_point_runtime_proxy,
                compile_virtualized_hard_surface,
            )

            compiler = compile_point_runtime_proxy if self.kind == "point" else compile_virtualized_hard_surface
            result = compiler(**self.arguments, cancel_event=self._cancel_event)
            self.finished.emit(True, self.kind, result, f"Compiled {self.kind} runtime geometry package.")
        except Exception as exc:
            self.finished.emit(False, self.kind, None, str(exc))


class DccCameraPossessionWorker(QObject):
    finished = Signal(dict)

    def __init__(
        self,
        requests: list[dict[str, Any]],
        *,
        bridge_factory: Callable[[str], Any] | None = None,
    ) -> None:
        """Initialize a camera-possession worker.

        :param requests: Provider execution requests.
        :param bridge_factory: Optional bridge factory for testing or embedding.
        """

        super().__init__()
        self.requests = list(requests or [])
        self._bridge_factory = bridge_factory
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        results: dict[str, dict[str, Any]] = {}

        def execute_request(request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            if self._cancel_event.is_set():
                return "", {"ok": False, "message": "Camera possession was canceled."}
            provider = str(request.get("provider") or "").lower()
            if not provider:
                return "", {"ok": False, "message": "Missing camera provider."}
            try:
                if self._bridge_factory is not None:
                    bridge = self._bridge_factory(provider)
                else:
                    from tech_connector.ui import three_d_mesh_painter_widget

                    bridge = three_d_mesh_painter_widget.scene_snapshot_bridge_for_provider(
                        provider
                    )
                timeout = float(request.get("timeout", 5.0) or 5.0)
                if str(request.get("execution") or "execute") == "execute_python":
                    response = bridge.execute_python(
                        str(request.get("code") or ""),
                        timeout=timeout,
                        reset_globals=True,
                    )
                    ok = bool(response.get("ok"))
                    raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or str(response)
                else:
                    ok, raw = bridge.execute(str(request.get("code") or ""), timeout=timeout)
                return provider, {"ok": bool(ok), "message": str(raw or "")[:240]}
            except Exception as exc:
                return provider, {"ok": False, "message": str(exc)[:240]}

        if len(self.requests) == 1:
            if self._cancel_event.is_set():
                self.finished.emit(results)
                return
            provider, result = execute_request(self.requests[0])
            if provider:
                results[provider] = result
            self.finished.emit(results)
            return

        max_workers = max(1, min(8, len(self.requests)))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dcc-camera") as executor:
            futures = {executor.submit(execute_request, request) for request in self.requests}
            while futures:
                done, futures = wait(futures, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in done:
                    provider, result = future.result()
                    if provider:
                        results[provider] = result
                if self._cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    break
        self.finished.emit(results)


class DccResolvedFrameWorker(QObject):
    frames_ready = Signal(list, list)

    def __init__(self, requests: list[dict[str, Any]]):
        super().__init__()
        self.requests = list(requests or [])

    @Slot()
    def run(self) -> None:
        frames: list[dict[str, Any]] = []
        errors: list[str] = []
        for request in self.requests:
            provider = str(request.get("provider") or "").strip().lower()
            provider_base = dcc_provider_base_key(provider)
            try:
                bridge = scene_snapshot_bridge_for_provider(provider)
                timeout = float(request.get("timeout", 15.0) or 15.0)
                code = str(request.get("code") or "")
                if provider_base == "unreal":
                    response = bridge.execute_python(code, timeout=timeout, reset_globals=True)
                    ok = bool(response.get("ok"))
                    raw = response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or response.get("error") or ""
                    if isinstance(raw, dict):
                        raw = json.dumps(raw)
                else:
                    ok, raw = bridge.execute(code, timeout=timeout)
                if not ok:
                    errors.append(f"{provider}: {str(raw)[:180]}")
                    continue
                parsed_ok, payload = parse_shaded_frame_output(str(raw), provider)
                if parsed_ok and isinstance(payload, dict):
                    frames.append(payload)
                else:
                    errors.append(str(payload)[:180])
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
        self.frames_ready.emit(frames, errors)
