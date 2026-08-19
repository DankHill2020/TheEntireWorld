"""3D mesh painter geometry, camera, and canvas models."""
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


def dcc_provider_base_key(provider_id: str) -> str:
    return str(provider_id or "").strip().lower().split(":", 1)[0]


PROVIDER_VIEW_COLORS: dict[str, tuple[QColor, QColor]] = {
    "maya": (QColor(74, 170, 255, 190), QColor(130, 215, 255, 235)),
    "blender": (QColor(255, 145, 55, 190), QColor(255, 195, 125, 235)),
    "motionbuilder": (QColor(78, 220, 145, 190), QColor(155, 255, 205, 235)),
    "houdini": (QColor(110, 205, 235, 190), QColor(175, 240, 255, 235)),
    "unreal": (QColor(170, 125, 255, 190), QColor(215, 190, 255, 235)),
    "unity": (QColor(210, 210, 220, 190), QColor(245, 245, 255, 235)),
    "3dsmax": (QColor(95, 205, 180, 190), QColor(160, 245, 220, 235)),
    "tech_connector": (QColor(235, 215, 90, 190), QColor(255, 238, 145, 235)),
}


def provider_view_colors(provider_id: str) -> tuple[QColor, QColor]:
    return PROVIDER_VIEW_COLORS.get(
        dcc_provider_base_key(provider_id),
        (QColor(120, 155, 190, 190), QColor(185, 230, 255, 235)),
    )


def scene_proxy_draws_filled_surface(proxy: SceneProxyInstance | dict[str, Any] | None) -> bool:
    if not isinstance(proxy, (dict, SceneProxyInstance)):
        return True
    if str(proxy.get("representation") or "").lower() == "mesh":
        return True
    values = " ".join(
        [
            str(proxy.get("object_type") or ""),
            str(proxy.get("type") or ""),
            " ".join(str(item) for item in (proxy.get("shape_types") or [])),
            str(proxy.get("name") or ""),
        ]
    ).lower()
    return not any(
        token in values
        for token in (
            "joint",
            "constraint",
            "nurbssurface",
            "nurbscurve",
            "nurbs",
            "curve",
            "ctrl",
            "control",
            "space",
            "target",
            "locator",
            "ikhandle",
        )
    )


def provider_world_to_view(
    provider_id: str,
    x: float,
    y: float,
    z: float,
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> tuple[float, float, float]:
    """Convert provider-native coordinates into canonical Tech Connector shared space."""
    return provider_native_to_shared(dcc_provider_base_key(provider_id), (x, y, z), unit_linear, up_axis)


def provider_view_to_world(
    provider_id: str,
    x: float,
    y: float,
    z: float,
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> tuple[float, float, float]:
    """Convert canonical Tech Connector shared coordinates back into provider-native space."""
    return shared_to_provider_native(dcc_provider_base_key(provider_id), (x, y, z), unit_linear, up_axis)


@dataclass
class MayaViewportCamera:
    """Maya-style perspective camera: eye, pivot/target, up, and lens state."""

    eye: tuple[float, float, float] = (-1.9318516525781364, -1.035276180410083, -3.3460652149512318)
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: tuple[float, float, float] = (-0.12940952255126034, 0.9659258262890683, -0.2241438680420134)
    fov_degrees: float = 45.0
    aspect_ratio: float = 0.0
    near_clip: float = 0.1
    far_clip: float = 100000.0

    def view_axes(self) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        forward = _vec_normalize(_vec_sub(self.target, self.eye), (0.0, 0.0, 1.0))
        right = _vec_normalize(_vec_cross(forward, self.up), _stable_right_axis(forward))
        up = _vec_normalize(_vec_cross(right, forward), (0.0, 1.0, 0.0))
        return forward, right, up

    @property
    def distance(self) -> float:
        return max(0.001, _vec_length(_vec_sub(self.eye, self.target)))

    def project_world_to_screen(self, point: tuple[float, float, float], view_w: float, view_h: float) -> tuple[float, float, float]:
        forward, right, up = self.view_axes()
        rel = _vec_sub(point, self.eye)
        cam_x = _vec_dot(rel, right)
        cam_y = _vec_dot(rel, up)
        cam_z = max(0.1, _vec_dot(rel, forward))
        tan_half_fov = math.tan(math.radians(self.fov_degrees / 2.0))
        scale_y = 1.0 / max(1.0e-4, tan_half_fov)
        aspect = view_w / max(1.0, view_h)
        scale_x = scale_y / max(1.0e-4, aspect)
        sx = view_w * 0.5 + (cam_x * scale_x / cam_z) * (view_w * 0.5)
        sy = view_h * 0.5 - (cam_y * scale_y / cam_z) * (view_h * 0.5)
        return sx, sy, cam_z

    def tumble(self, delta_x: float, delta_y: float) -> None:
        offset = _vec_sub(self.eye, self.target)
        radius = max(0.001, _vec_length(offset))
        world_up = (0.0, 1.0, 0.0)
        yaw = math.radians(float(-delta_x) * 0.45)
        pitch = math.radians(float(delta_y) * 0.45)

        yawed_offset = _rotate_vec_around_axis(offset, world_up, yaw)
        forward_after_yaw = _vec_normalize(_vec_scale(yawed_offset, -1.0), (0.0, 0.0, 1.0))
        right = _vec_normalize(_vec_cross(forward_after_yaw, world_up), _stable_right_axis(forward_after_yaw))

        pitched_offset = _rotate_vec_around_axis(yawed_offset, right, pitch)
        pitched_forward = _vec_normalize(_vec_scale(pitched_offset, -1.0), forward_after_yaw)
        if abs(_vec_dot(pitched_forward, world_up)) > 0.985:
            pitched_offset = yawed_offset
            pitched_forward = forward_after_yaw

        self.eye = _vec_add(self.target, _vec_scale(_vec_normalize(pitched_offset, offset), radius))
        right = _vec_normalize(_vec_cross(pitched_forward, world_up), right)
        self.up = _vec_normalize(_vec_cross(right, pitched_forward), world_up)

    def track(self, delta_x: float, delta_y: float, view_w: float, view_h: float) -> None:
        _forward, right, up = self.view_axes()
        tan_half_fov = math.tan(math.radians(self.fov_degrees / 2.0))
        world_per_px_y = (2.0 * self.distance * tan_half_fov) / max(1.0, view_h)
        world_per_px_x = world_per_px_y * (view_w / max(1.0, view_h))
        move = _vec_add(_vec_scale(right, -delta_x * world_per_px_x), _vec_scale(up, delta_y * world_per_px_y))
        self.eye = _vec_add(self.eye, move)
        self.target = _vec_add(self.target, move)

    def dolly(self, delta_y: float) -> None:
        factor = 1.0 + max(-0.75, min(0.75, float(delta_y) * 0.01))
        direction = _vec_sub(self.eye, self.target)
        distance = max(0.35, min(80.0, _vec_length(direction) * factor))
        self.eye = _vec_add(self.target, _vec_scale(_vec_normalize(direction, (0.0, 0.0, -1.0)), distance))

    def frame_bounds(self, min_point: tuple[float, float, float], max_point: tuple[float, float, float]) -> None:
        center = tuple((min_point[i] + max_point[i]) * 0.5 for i in range(3))
        radius = max(0.001, _vec_length(tuple((max_point[i] - min_point[i]) * 0.5 for i in range(3))))
        view_dir = _vec_normalize(_vec_sub(self.eye, self.target), (0.0, 0.0, -1.0))
        distance = max(4.0, radius / max(0.1, math.tan(math.radians(self.fov_degrees / 2.0))) * 1.4)
        self.target = center
        self.eye = _vec_add(center, _vec_scale(view_dir, distance))

    def focus(self, target: tuple[float, float, float]) -> None:
        view_dir = _vec_normalize(_vec_sub(self.eye, self.target), (0.0, 0.0, -1.0))
        distance = self.distance
        self.target = target
        self.eye = _vec_add(target, _vec_scale(view_dir, distance))


def _vec_add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _vec_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _vec_scale(v: tuple[float, float, float], scale: float) -> tuple[float, float, float]:
    return v[0] * scale, v[1] * scale, v[2] * scale


def _vec_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _rotate_vec_around_axis(
    vector: tuple[float, float, float],
    axis: tuple[float, float, float],
    radians_: float,
) -> tuple[float, float, float]:
    axis = _vec_normalize(axis, (0.0, 1.0, 0.0))
    cos_a = math.cos(radians_)
    sin_a = math.sin(radians_)
    term_a = _vec_scale(vector, cos_a)
    term_b = _vec_scale(_vec_cross(axis, vector), sin_a)
    term_c = _vec_scale(axis, _vec_dot(axis, vector) * (1.0 - cos_a))
    return _vec_add(_vec_add(term_a, term_b), term_c)


def _vec_length(v: tuple[float, float, float]) -> float:
    return math.sqrt(_vec_dot(v, v))


def _vec_normalize(
    v: tuple[float, float, float],
    fallback: tuple[float, float, float],
) -> tuple[float, float, float]:
    length = _vec_length(v)
    if length < 1.0e-6:
        return fallback
    return v[0] / length, v[1] / length, v[2] / length


def _stable_right_axis(forward: tuple[float, float, float]) -> tuple[float, float, float]:
    world_up = (0.0, 1.0, 0.0)
    right = _vec_cross(forward, world_up)
    if _vec_length(right) < 1.0e-4:
        right = _vec_cross(forward, (1.0, 0.0, 0.0))
    return _vec_normalize(right, (1.0, 0.0, 0.0))


class FBXMeshModel:
    """3D Mesh Container supporting FBX, OBJ, glTF, and USD geometry."""

    def __init__(self, name: str = "Sphere_Primitive_Demo"):
        self.name = name
        self.vertices: list[MeshVertex3D] = []
        self.faces: list[tuple[int, int, int]] = []
        self.face_colors: list[QColor] = []
        self.quad_face_colors: list[QColor] = []
        self.scene_proxy_objects: list[SceneProxyInstance] = []
        self.source_texture_images: dict[str, QImage] = {}
        self.provider_id = "tech_connector"
        self.unit_linear = "centimeters"
        self.scene_center = (0.0, 0.0, 0.0)
        self.scene_scale = 1.0
        self.proxy_fill_color, self.proxy_wire_color = provider_view_colors(self.provider_id)
        self.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        self.albedo_texture.fill(QColor(200, 205, 215, 255))

        # Build default reference 3D sphere primitive so canvas is 100% interactive out-of-the-box
        self._generate_sphere_primitive()
        self.update_default_pose()

    def update_default_pose(self) -> MeshDefaultPose:
        """Make the current undeformed shape this mesh's new default pose."""
        previous = getattr(self, "default_pose", None)
        revision = int(getattr(previous, "revision", 0) or 0) + 1
        self.default_pose = MeshDefaultPose(
            positions=[(float(vertex.x), float(vertex.y), float(vertex.z)) for vertex in self.vertices],
            triangle_faces=[tuple(int(value) for value in face) for face in self.faces],
            quad_faces=[tuple(int(value) for value in face) for face in getattr(self, "quad_faces", ())],
            revision=revision,
        )
        return self.default_pose

    def default_pose_matches_topology(self) -> bool:
        pose = getattr(self, "default_pose", None)
        if not isinstance(pose, MeshDefaultPose):
            return False
        return (
            len(pose.positions) == len(self.vertices)
            and pose.triangle_faces == [tuple(face) for face in self.faces]
            and pose.quad_faces == [tuple(face) for face in getattr(self, "quad_faces", ())]
        )

    def restore_default_pose(self) -> int:
        """Restore vertex positions while retaining UV, paint, material, and topology data."""
        pose = getattr(self, "default_pose", None)
        if not isinstance(pose, MeshDefaultPose) or not pose.positions:
            raise ValueError("This mesh does not have a default pose.")
        if not self.default_pose_matches_topology():
            raise ValueError(
                "The mesh topology has changed since its default pose was stored. "
                "Update the default pose for the current topology before restoring it."
            )
        for vertex, position in zip(self.vertices, pose.positions):
            vertex.x, vertex.y, vertex.z = position
        return len(self.vertices)

    def default_pose_to_dict(self) -> dict[str, Any]:
        pose = getattr(self, "default_pose", None)
        return pose.to_dict() if isinstance(pose, MeshDefaultPose) else {}

    def load_default_pose(self, data: dict[str, Any]) -> bool:
        pose = MeshDefaultPose.from_dict(data)
        previous = getattr(self, "default_pose", None)
        self.default_pose = pose
        if not self.default_pose_matches_topology():
            self.default_pose = previous
            return False
        return True

    def source_texture_image(self, texture_path: str) -> QImage | None:
        """Decode an imported material texture only when a material view needs it."""
        path = str(texture_path or "")
        if not path:
            return None
        cached = self.source_texture_images.get(path)
        if path in self.source_texture_images and isinstance(cached, QImage):
            return cached if not cached.isNull() else None
        image = QImage(path)
        if image.isNull():
            self.source_texture_images[path] = QImage()
            return None
        image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.source_texture_images[path] = image
        return image

    def release_source_texture_images(self) -> None:
        """Release decoded source textures when material display is inactive."""
        self.source_texture_images.clear()

    def ensure_albedo_texture_loaded(self) -> QImage:
        """Load a file-backed local albedo only for an active texture view."""
        if getattr(self, "_albedo_texture_loaded", True):
            return self.albedo_texture
        self._albedo_texture_loaded = True
        texture_path = str(getattr(self, "sample_albedo_path", "") or "")
        image = QImage(texture_path) if texture_path else QImage()
        if not image.isNull():
            self.albedo_texture = image.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
                1024,
                1024,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        return self.albedo_texture

    @classmethod
    def from_obj(cls, mesh_path: str) -> "FBXMeshModel":
        path = Path(mesh_path)
        positions: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        vertices: list[MeshVertex3D] = []
        faces: list[tuple[int, int, int]] = []
        vertex_lookup: dict[tuple[int, int], int] = {}
        mtllibs: list[str] = []

        def vertex_index(token: str) -> int:
            parts = token.split("/")
            pos_index = int(parts[0]) - 1
            uv_index = int(parts[1]) - 1 if len(parts) > 1 and parts[1] else -1
            key = (pos_index, uv_index)
            if key in vertex_lookup:
                return vertex_lookup[key]
            x, y, z = positions[pos_index]
            if 0 <= uv_index < len(uvs):
                u, v = uvs[uv_index]
            else:
                u, v = 0.0, 0.0
            vertex_lookup[key] = len(vertices)
            vertices.append(MeshVertex3D(x, y, z, u, v))
            return vertex_lookup[key]

        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    positions.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith("mtllib "):
                mtllibs.extend(line.split()[1:])
            elif line.startswith("vt "):
                parts = line.split()
                if len(parts) >= 3:
                    uvs.append((float(parts[1]), float(parts[2])))
            elif line.startswith("f "):
                tokens = line.split()[1:]
                if len(tokens) < 3:
                    continue
                indices = [vertex_index(token) for token in tokens]
                for offset in range(1, len(indices) - 1):
                    faces.append((indices[0], indices[offset], indices[offset + 1]))

        if not vertices or not faces:
            raise ValueError("OBJ file did not contain usable vertices and faces.")

        min_x = min(v.x for v in vertices)
        max_x = max(v.x for v in vertices)
        min_y = min(v.y for v in vertices)
        max_y = max(v.y for v in vertices)
        min_z = min(v.z for v in vertices)
        max_z = max(v.z for v in vertices)
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        scale = max(max_x - min_x, max_y - min_y, max_z - min_z, 0.0001) / 3.0
        for v in vertices:
            v.x = (v.x - center[0]) / scale
            v.y = (v.y - center[1]) / scale
            v.z = (v.z - center[2]) / scale
            if v.u == 0.0 and v.v == 0.0 and not uvs:
                v.u = max(0.0, min(1.0, (v.x + 1.5) / 3.0))
                v.v = max(0.0, min(1.0, (v.z + 1.5) / 3.0))

        model = cls(path.name)
        model.vertices = vertices
        model.faces = faces
        model.face_colors = [QColor(190, 196, 205, 255) for _ in faces]
        model.quad_faces = []
        model.quad_face_colors = []
        model.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        model.albedo_texture.fill(QColor(190, 196, 205, 255))
        texture_path = cls._first_diffuse_texture_from_mtls(path.parent, mtllibs)
        if texture_path:
            model.sample_albedo_path = str(texture_path)
            model._albedo_texture_loaded = False
        model.update_default_pose()
        return model

    @classmethod
    def from_native_fbx_asset(cls, asset: Any) -> "FBXMeshModel":
        """Build editable render geometry from the Blender-backed native FBX contract."""
        import numpy as np

        manifest = copy.deepcopy(dict(getattr(asset, "manifest", {}) or {}))
        packed_floats = getattr(asset, "floats", None)
        packed_integers = getattr(asset, "integers", None)
        if packed_floats is None or packed_integers is None:
            raise ValueError("Native FBX asset buffers are missing.")
        vertices: list[MeshVertex3D] = []
        faces: list[tuple[int, int, int]] = []
        proxies: list[SceneProxyInstance] = []
        all_positions: list[tuple[float, float, float]] = []
        centimeters_per_blender_unit = max(
            1.0e-12,
            float(manifest.get("unit_scale", 1.0) or 1.0) * 100.0,
        )
        for mesh_index, item in enumerate(manifest.get("meshes") or []):
            source_count = int(item.get("vertex_count", 0) or 0)
            triangle_count = int(item.get("triangle_count", 0) or 0)
            if source_count <= 0 or triangle_count <= 0:
                continue
            position_offset = int(item.get("position_float_offset", 0) or 0)
            index_offset = int(item.get("triangle_index_offset", 0) or 0)
            uv_offset = int(item.get("uv_float_offset", 0) or 0)
            positions = np.frombuffer(
                packed_floats,
                dtype=np.float32,
                count=source_count * 3,
                offset=position_offset * 4,
            ).reshape((-1, 3))
            world = np.asarray(item.get("world_matrix") or IDENTITY_MATRIX, dtype=np.float64).reshape((4, 4))
            positions_h = np.ones((source_count, 4), dtype=np.float64)
            positions_h[:, :3] = positions
            world_positions = (world @ positions_h.T).T[:, :3] * centimeters_per_blender_unit
            authored_transform = (
                dict(item.get("tech_connector_transform") or {})
                if isinstance(item.get("tech_connector_transform"), dict)
                else {}
            )
            authored_translation = np.asarray(
                list(authored_transform.get("translation_shared_cm") or (0.0, 0.0, 0.0))[:3],
                dtype=np.float64,
            )
            authored_rotation = [
                math.radians(float(value))
                for value in list(authored_transform.get("rotation_degrees") or (0.0, 0.0, 0.0))[:3]
            ]
            authored_scale = np.asarray(
                list(authored_transform.get("scale") or (1.0, 1.0, 1.0))[:3],
                dtype=np.float64,
            )
            if len(authored_translation) < 3:
                authored_translation = np.zeros(3, dtype=np.float64)
            if len(authored_rotation) < 3:
                authored_rotation = [0.0, 0.0, 0.0]
            if len(authored_scale) < 3:
                authored_scale = np.ones(3, dtype=np.float64)
            rx, ry, rz = authored_rotation
            cx, sx = math.cos(rx), math.sin(rx)
            cy, sy = math.cos(ry), math.sin(ry)
            cz, sz = math.cos(rz), math.sin(rz)
            rotation_matrix = np.asarray(
                [
                    [cy * cz, cz * sx * sy - cx * sz, sx * sz + cx * cz * sy],
                    [cy * sz, cx * cz + sx * sy * sz, cx * sy * sz - cz * sx],
                    [-sy, cy * sx, cx * cy],
                ],
                dtype=np.float64,
            )
            base_pivot = (world_positions.min(axis=0) + world_positions.max(axis=0)) * 0.5
            world_positions = (
                ((world_positions - base_pivot) * authored_scale) @ rotation_matrix.T
                + base_pivot
                + authored_translation
            )
            source_indices = np.frombuffer(
                packed_integers,
                dtype=np.uint32,
                count=triangle_count * 3,
                offset=index_offset * 4,
            ).astype(np.int64, copy=False)
            uvs = None
            if bool(item.get("has_uvs")):
                uvs = np.frombuffer(
                    packed_floats,
                    dtype=np.float32,
                    count=triangle_count * 3 * 2,
                    offset=uv_offset * 4,
                ).reshape((-1, 2))
            vertex_start = len(vertices)
            face_start = len(faces)
            render_source_indices: list[int] = []
            for corner_index, source_index in enumerate(source_indices):
                point = world_positions[int(source_index)]
                uv = uvs[corner_index] if uvs is not None else (0.0, 0.0)
                vertices.append(
                    MeshVertex3D(
                        float(point[0]),
                        float(point[1]),
                        float(point[2]),
                        float(uv[0]),
                        float(uv[1]),
                    )
                )
                all_positions.append((float(point[0]), float(point[1]), float(point[2])))
                render_source_indices.append(int(source_index))
            for triangle_index in range(triangle_count):
                base = vertex_start + triangle_index * 3
                faces.append((base, base + 1, base + 2))
            materials = []
            texture_bindings: dict[str, str] = {}
            for material in item.get("materials") or []:
                from tech_connector.game_engine.rendering.material_contract import (
                    normalize_portable_material,
                    viewer_material_approximation,
                )

                portable = normalize_portable_material(
                    material,
                    source_provider=f"native_{getattr(asset, 'source_format', 'scene')}",
                    source_path=str(getattr(asset, "source_path", "") or ""),
                )
                approximation = viewer_material_approximation(portable)
                color_values = list(approximation.get("base_color") or (0.75, 0.78, 0.82, 1.0))
                color = QColor.fromRgbF(*[max(0.0, min(1.0, float(value))) for value in color_values[:4]])
                textures = {
                    str(key): str(value)
                    for key, value in (approximation.get("textures") or {}).items()
                    if value
                }
                if textures and not texture_bindings:
                    texture_bindings.update(textures)
                materials.append(SceneProxyMaterialBinding(
                    name=str(approximation.get("name") or "Material"),
                    color=color,
                    texture_paths=textures,
                    source_material_id=str(approximation.get("source_material_id") or ""),
                    approximation=str(approximation.get("approximation") or "openpbr"),
                    roughness=float(approximation.get("roughness", 0.5)),
                    metalness=float(approximation.get("metallic", 0.0)),
                    specular=float(approximation.get("specular", 0.5)),
                    emission_color=tuple(approximation.get("emission_color") or (0.0, 0.0, 0.0)),
                    opacity=float(approximation.get("opacity", 1.0)),
                    transmission=float(approximation.get("transmission", 0.0)),
                    ior=float(approximation.get("ior", 1.5)),
                    clearcoat=float(approximation.get("clearcoat", 0.0)),
                    texture_color_spaces=dict(approximation.get("texture_color_spaces") or {}),
                    portable_material=dict(approximation.get("portable_material") or {}),
                ))
            proxy_color = materials[0].color if materials else QColor(190, 196, 205, 255)
            mesh_min = world_positions.min(axis=0)
            mesh_max = world_positions.max(axis=0)
            mesh_center = (mesh_min + mesh_max) * 0.5
            proxies.append(SceneProxyInstance(
                index=mesh_index,
                provider_id="native_fbx",
                native_id=str(item.get("native_id") or item.get("name") or f"Mesh{mesh_index}"),
                name=str(item.get("name") or f"Mesh {mesh_index + 1}"),
                object_type="mesh",
                representation="mesh",
                center=tuple(float(value) for value in mesh_center),
                source_bbox=tuple(float(value) for value in (*mesh_min, *mesh_max)),
                mesh_data=SceneProxyMeshData(
                    vertex_start=vertex_start,
                    vertex_count=triangle_count * 3,
                    face_start=face_start,
                    face_count=triangle_count,
                    has_uvs=uvs is not None,
                    source_vertex_count=source_count,
                    source_vertex_indices=render_source_indices,
                    topology_state="mesh",
                ),
                materials=materials,
                material_color=QColor(proxy_color),
                fill_color=QColor(proxy_color),
                texture_bindings=texture_bindings,
                source_key=f"native_fbx:{str(item.get('native_id') or item.get('name') or f'Mesh{mesh_index}')}",
                source_transform={
                    "world_matrix": list(item.get("world_matrix") or IDENTITY_MATRIX),
                    "translation": [float(value) for value in authored_translation],
                    "rotation": [math.degrees(value) for value in authored_rotation],
                    "scale": [float(value) for value in authored_scale],
                },
                local_transform={
                    "world_matrix": list(item.get("world_matrix") or IDENTITY_MATRIX),
                    "translation": [float(value) for value in authored_translation],
                    "rotation": [math.degrees(value) for value in authored_rotation],
                    "scale": [float(value) for value in authored_scale],
                },
            ))
        if not vertices or not faces:
            raise ValueError("The FBX did not contain renderable mesh triangles.")
        mins = tuple(min(point[axis] for point in all_positions) for axis in range(3))
        maxs = tuple(max(point[axis] for point in all_positions) for axis in range(3))
        center = tuple((mins[axis] + maxs[axis]) * 0.5 for axis in range(3))
        extent = max(maxs[axis] - mins[axis] for axis in range(3))
        scale = 4.0 / max(extent, 1.0e-6)
        for vertex in vertices:
            vertex.x = (vertex.x - center[0]) * scale
            vertex.y = (vertex.y - center[1]) * scale
            vertex.z = (vertex.z - center[2]) * scale
        for proxy in proxies:
            proxy.center = tuple((float(proxy.center[axis]) - center[axis]) * scale for axis in range(3))
        model = cls(Path(getattr(asset, "source_path", "Native FBX")).name)
        model.vertices = vertices
        model.faces = faces
        model.face_colors = [QColor(190, 196, 205, 255) for _ in faces]
        model.quad_faces = []
        model.quad_face_colors = []
        model.scene_proxy_objects = proxies
        model.provider_id = "native_fbx"
        model.unit_linear = "meters"
        model.scene_center = center
        model.scene_scale = scale
        model.source_path = str(getattr(asset, "source_path", "") or "")
        model.native_fbx_manifest = manifest
        model.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        model.albedo_texture.fill(QColor(190, 196, 205, 255))
        first_texture = next(
            (path for proxy in proxies for path in proxy.texture_bindings.values() if path),
            "",
        )
        if first_texture:
            model.sample_albedo_path = first_texture
            model._albedo_texture_loaded = False
        model.update_default_pose()
        return model

    @classmethod
    def from_scene_snapshot(
        cls,
        snapshot: dict[str, Any],
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> "FBXMeshModel":
        """Build isolated provider scene geometry with bounds fallback."""
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Scene model compilation canceled.")
        provider_id = str(snapshot.get("provider_id") or "provider")
        objects = [
            obj for obj in (snapshot.get("objects") or [])
            if isinstance(obj, dict)
            and obj.get("type") != "error"
            and cls._include_snapshot_object_as_scene_element(obj)
            and len(obj.get("bbox") or []) == 6
        ]
        if not objects:
            raise ValueError("Scene snapshot did not contain visible element bounds.")
        unit_linear = str(snapshot.get("unit_linear") or "")
        up_axis = str(snapshot.get("up_axis") or "")
        provider_base = dcc_provider_base_key(provider_id)
        basis = provider_axis_basis(provider_base, up_axis)
        source_axes = (
            basis.shared_x_from_native,
            basis.shared_y_from_native,
            basis.shared_z_from_native,
        )
        source_unit_scale = unit_to_centimeters(unit_linear, provider_base)

        def bbox_to_view_bounds(bbox_values: list[Any]) -> tuple[float, float, float, float, float, float]:
            return provider_bbox_to_shared(provider_id, bbox_values, unit_linear, up_axis)

        all_bounds = [bbox_to_view_bounds(obj["bbox"]) for obj in objects]
        min_x = min(float(b[0]) for b in all_bounds)
        min_y = min(float(b[1]) for b in all_bounds)
        min_z = min(float(b[2]) for b in all_bounds)
        max_x = max(float(b[3]) for b in all_bounds)
        max_y = max(float(b[4]) for b in all_bounds)
        max_z = max(float(b[5]) for b in all_bounds)
        center = scene_center or (
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        )
        extent = max(max_x - min_x, max_y - min_y, max_z - min_z, 0.001)
        scale = float(scene_scale) if scene_scale is not None else 4.0 / extent

        model = object.__new__(cls)
        model.name = "Scene Snapshot"
        model.vertices = []
        model.faces = []
        model.quad_faces = []
        model.face_colors = []
        model.quad_face_colors = []
        model.face_proxy_indices = []
        model.quad_proxy_indices = []
        model.scene_proxy_objects = []
        model.source_texture_images = {}
        model.provider_id = provider_id
        model.unit_linear = unit_linear
        model.up_axis = up_axis
        model.scene_center = center
        model.scene_scale = scale
        model.proxy_fill_color, model.proxy_wire_color = provider_view_colors(model.provider_id)
        model.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        model.albedo_texture.fill(model.proxy_fill_color)

        def normalize_point(x: float, y: float, z: float) -> tuple[float, float, float]:
            return (
                (float(x) - center[0]) * scale,
                (float(y) - center[1]) * scale,
                (float(z) - center[2]) * scale,
            )

        def source_point_to_view(point: list[Any] | tuple[Any, ...]) -> tuple[float, float, float]:
            native = (float(point[0]), float(point[1]), float(point[2]))
            shared = tuple(
                native[axis_index] * axis_sign * source_unit_scale
                for axis_index, axis_sign in source_axes
            )
            return normalize_point(shared[0], shared[1], shared[2])

        real_mesh_count = 0
        bounds_fallback_count = 0

        def material_binding_for_object(obj: dict[str, Any]) -> SceneProxyMaterialBinding:
            material = obj.get("material") if isinstance(obj.get("material"), dict) else {}
            from tech_connector.game_engine.rendering.material_contract import (
                normalize_portable_material,
                viewer_material_approximation,
            )

            portable = normalize_portable_material(
                material,
                source_provider=provider_id,
                source_path=str(snapshot.get("scene") or ""),
            )
            approximation = viewer_material_approximation(portable)
            color_values = list(approximation.get("base_color") or (0.75, 0.78, 0.82, 1.0))
            name = str(approximation.get("name") or "")
            texture_paths = dict(approximation.get("textures") or {})
            roughness = float(approximation.get("roughness", 0.5))
            metalness = float(approximation.get("metallic", 0.0))
            specular = float(approximation.get("specular", 0.5))
            emission_color = tuple(approximation.get("emission_color") or (0.0, 0.0, 0.0))
            opacity = float(approximation.get("opacity", 1.0))
            transmission = float(approximation.get("transmission", 0.0))
            ior = float(approximation.get("ior", 1.5))
            thickness = max(0.0, float(material.get("thickness", material.get("thickness_factor", 0.0)) or 0.0))
            clearcoat = float(approximation.get("clearcoat", 0.0))
            attenuation_color = str(material.get("attenuation_color") or "#ffffff")
            attenuation_distance = max(0.001, float(material.get("attenuation_distance", 1000.0) or 1000.0))
            color = QColor(
                max(0, min(255, int(float(color_values[0]) * 255))),
                max(0, min(255, int(float(color_values[1]) * 255))),
                max(0, min(255, int(float(color_values[2]) * 255))),
                int(opacity * 255),
            )
            return SceneProxyMaterialBinding(
                name=name,
                color=color,
                texture_paths=dict(texture_paths),
                source_material_id=str(approximation.get("source_material_id") or name),
                approximation=str(approximation.get("approximation") or "openpbr"),
                roughness=roughness,
                metalness=metalness,
                specular=specular,
                emission_color=emission_color,
                opacity=opacity,
                transmission=transmission,
                ior=ior,
                thickness=thickness,
                clearcoat=clearcoat,
                attenuation_color=attenuation_color,
                attenuation_distance=attenuation_distance,
                texture_color_spaces=dict(approximation.get("texture_color_spaces") or {}),
                portable_material=dict(approximation.get("portable_material") or {}),
            )

        def material_bindings_for_object(obj: dict[str, Any]) -> list[SceneProxyMaterialBinding]:
            payloads = [
                material for material in (obj.get("materials") or [])
                if isinstance(material, dict)
            ]
            if isinstance(obj.get("material"), dict):
                payloads.insert(0, obj["material"])
            bindings: list[SceneProxyMaterialBinding] = []
            seen: set[str] = set()
            for material in payloads:
                binding = material_binding_for_object({**obj, "material": material})
                material_id = str(binding.source_material_id or binding.name)
                if material_id in seen:
                    continue
                seen.add(material_id)
                bindings.append(binding)
            return bindings or [material_binding_for_object(obj)]

        def add_bounds_box(obj: dict[str, Any], index: int, material_color: QColor) -> tuple[float, float, float]:
            bbox = list(bbox_to_view_bounds(obj["bbox"]))
            raw_size = (
                max(0.001, bbox[3] - bbox[0]),
                max(0.001, bbox[4] - bbox[1]),
                max(0.001, bbox[5] - bbox[2]),
            )
            min_proxy_size = max(0.025, extent * 0.006)
            if raw_size[0] <= 0.001:
                bbox[0] -= min_proxy_size
                bbox[3] += min_proxy_size
            if raw_size[1] <= 0.001:
                bbox[1] -= min_proxy_size
                bbox[4] += min_proxy_size
            if raw_size[2] <= 0.001:
                bbox[2] -= min_proxy_size
                bbox[5] += min_proxy_size

            corners = [
                normalize_point(bbox[0], bbox[1], bbox[2]),
                normalize_point(bbox[3], bbox[1], bbox[2]),
                normalize_point(bbox[3], bbox[4], bbox[2]),
                normalize_point(bbox[0], bbox[4], bbox[2]),
                normalize_point(bbox[0], bbox[1], bbox[5]),
                normalize_point(bbox[3], bbox[1], bbox[5]),
                normalize_point(bbox[3], bbox[4], bbox[5]),
                normalize_point(bbox[0], bbox[4], bbox[5]),
            ]
            start = len(model.vertices)
            for x, y, z in corners:
                model.vertices.append(MeshVertex3D(x, y, z, 0.5, 0.5))

            quads = [
                (0, 1, 2, 3),
                (4, 7, 6, 5),
                (0, 4, 5, 1),
                (1, 5, 6, 2),
                (2, 6, 7, 3),
                (3, 7, 4, 0),
            ]
            for q1, q2, q3, q4 in quads:
                model.quad_faces.append((start + q1, start + q2, start + q3, start + q4))
                model.quad_face_colors.append(QColor(material_color))
                model.quad_proxy_indices.append(index)
                model.faces.append((start + q1, start + q2, start + q3))
                model.face_colors.append(QColor(material_color))
                model.face_proxy_indices.append(index)
                model.faces.append((start + q1, start + q3, start + q4))
                model.face_colors.append(QColor(material_color))
                model.face_proxy_indices.append(index)

            return normalize_point(
                (bbox[0] + bbox[3]) * 0.5,
                (bbox[1] + bbox[4]) * 0.5,
                (bbox[2] + bbox[5]) * 0.5,
            )

        def add_mesh_geometry(
            obj: dict[str, Any],
            material_color: QColor,
            material_colors_by_face: dict[int, QColor] | None = None,
        ) -> tuple[tuple[float, float, float] | None, list[int], int, bool]:
            geometry = obj.get("geometry") or {}
            if geometry.get("representation") != "mesh":
                return None, [], 0, False
            source_vertices = geometry.get("vertices") or []
            source_faces = geometry.get("faces") or []
            if not source_vertices or not source_faces:
                return None, [], 0, False
            source_uvs = geometry.get("uvs") or []
            face_uv_indices = geometry.get("face_uv_indices") or []
            start = len(model.vertices)
            faces_before = len(model.faces)
            quads_before = len(model.quad_faces)
            face_colors_before = len(model.face_colors)
            quad_colors_before = len(model.quad_face_colors)
            render_vertex_by_corner: dict[tuple[int, int], int] = {}
            render_source_indices: list[int] = []

            def render_vertex(source_index: int, uv_index: int) -> int | None:
                if not 0 <= source_index < len(source_vertices):
                    return None
                valid_uv_index = uv_index if 0 <= uv_index < len(source_uvs) else -1
                key = (source_index, valid_uv_index)
                cached = render_vertex_by_corner.get(key)
                if cached is not None:
                    return cached
                point = source_vertices[source_index]
                if not isinstance(point, (list, tuple)) or len(point) < 3:
                    return None
                x, y, z = source_point_to_view(point)
                if valid_uv_index >= 0:
                    uv = source_uvs[valid_uv_index]
                    u = float(uv[0]) if isinstance(uv, (list, tuple)) and len(uv) >= 2 else 0.5
                    v = float(uv[1]) if isinstance(uv, (list, tuple)) and len(uv) >= 2 else 0.5
                else:
                    u, v = 0.5, 0.5
                render_index = len(model.vertices)
                model.vertices.append(MeshVertex3D(x, y, z, u, v))
                render_source_indices.append(source_index)
                render_vertex_by_corner[key] = render_index
                return render_index

            for face_index, face in enumerate(source_faces):
                if face_index % 2048 == 0 and cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Scene model compilation canceled.")
                if not isinstance(face, (list, tuple)) or len(face) < 3:
                    continue
                source_face_uvs = face_uv_indices[face_index] if face_index < len(face_uv_indices) else []
                indices: list[int] = []
                for corner_index, raw_index in enumerate(face):
                    try:
                        source_index = int(raw_index)
                    except Exception:
                        continue
                    try:
                        uv_index = int(source_face_uvs[corner_index]) if corner_index < len(source_face_uvs) else -1
                    except Exception:
                        uv_index = -1
                    index = render_vertex(source_index, uv_index)
                    if index is not None:
                        indices.append(index)
                if len(indices) < 3:
                    continue
                face_color = (material_colors_by_face or {}).get(face_index, material_color)
                if len(indices) == 4:
                    model.quad_faces.append(tuple(indices))
                    model.quad_face_colors.append(QColor(face_color))
                    model.quad_proxy_indices.append(index)
                for offset in range(1, len(indices) - 1):
                    model.faces.append((indices[0], indices[offset], indices[offset + 1]))
                    model.face_colors.append(QColor(face_color))
                    model.face_proxy_indices.append(index)
            if len(model.faces) == faces_before:
                model.vertices = model.vertices[:start]
                model.quad_faces = model.quad_faces[:quads_before]
                model.face_colors = model.face_colors[:face_colors_before]
                model.quad_face_colors = model.quad_face_colors[:quad_colors_before]
                model.face_proxy_indices = model.face_proxy_indices[:face_colors_before]
                model.quad_proxy_indices = model.quad_proxy_indices[:quad_colors_before]
                return None, [], 0, False
            bbox = list(bbox_to_view_bounds(obj["bbox"]))
            return (
                normalize_point(
                    (bbox[0] + bbox[3]) * 0.5,
                    (bbox[1] + bbox[4]) * 0.5,
                    (bbox[2] + bbox[5]) * 0.5,
                ),
                render_source_indices,
                len(source_vertices),
                bool(source_uvs and face_uv_indices),
            )

        for index, obj in enumerate(objects):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            material_bindings = material_bindings_for_object(obj)
            material_binding = material_bindings[0]
            material_color = QColor(material_binding.color)
            material_color_by_id = {
                str(binding.source_material_id or binding.name): QColor(binding.color)
                for binding in material_bindings
            }
            material_colors_by_face: dict[int, QColor] = {}
            for assignment in obj.get("material_assignments") or []:
                if not isinstance(assignment, dict):
                    continue
                assignment_color = material_color_by_id.get(str(
                    assignment.get("material_id") or assignment.get("source_material_id") or ""
                ))
                if assignment_color is None:
                    continue
                for raw_face_index in assignment.get("face_indices") or assignment.get("faces") or []:
                    try:
                        material_colors_by_face[int(raw_face_index)] = assignment_color
                    except (TypeError, ValueError):
                        continue
            vertex_start = len(model.vertices)
            face_start = len(model.faces)
            quad_start = len(model.quad_faces)
            center_point, source_vertex_indices, source_vertex_count, has_uvs = add_mesh_geometry(
                obj,
                material_color,
                material_colors_by_face,
            )
            representation = "mesh"
            if center_point is None:
                center_point = add_bounds_box(obj, index, material_color)
                representation = "bounds"
                source_vertex_indices = list(range(len(model.vertices) - vertex_start))
                source_vertex_count = len(source_vertex_indices)
                has_uvs = False
                bounds_fallback_count += 1
            else:
                real_mesh_count += 1
            cx, cy, cz = center_point
            source_transform = {
                "translation": obj.get("translation"),
                "rotation": obj.get("rotation"),
                "scale": obj.get("scale"),
            }
            geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
            source_signature = json.dumps(
                {
                    "bbox": obj.get("bbox"),
                    "transform": source_transform,
                    "geometry": {
                        "representation": geometry.get("representation"),
                        "vertex_count": len(geometry.get("vertices") or []),
                        "face_count": len(geometry.get("faces") or []),
                    },
                },
                sort_keys=True,
                default=str,
            )
            native_id = str(obj.get("native_id") or "")
            proxy = SceneProxyInstance(
                index=index,
                provider_id=model.provider_id,
                native_id=native_id,
                name=str(obj.get("name") or obj.get("native_id") or f"{model.provider_id}_object_{index}"),
                object_type=str(obj.get("type") or "mesh"),
                representation=representation,
                center=(cx, cy, cz),
                source_bbox=tuple(float(v) for v in bbox_to_view_bounds(obj["bbox"])),
                mesh_data=SceneProxyMeshData(
                    vertex_start=vertex_start,
                    vertex_count=len(model.vertices) - vertex_start,
                    face_start=face_start,
                    face_count=len(model.faces) - face_start,
                    quad_start=quad_start,
                    quad_count=len(model.quad_faces) - quad_start,
                    has_uvs=has_uvs,
                    source_vertex_count=source_vertex_count,
                    source_vertex_indices=source_vertex_indices,
                    topology_state=representation,
                ),
                materials=material_bindings,
                material_color=material_color,
                fill_color=QColor(model.proxy_fill_color),
                wire_color=QColor(model.proxy_wire_color),
                source_transform=source_transform,
                light_data=dict(obj.get("light") or {}),
                local_transform=dict(source_transform),
                source_signature=source_signature,
                source_key=f"{model.provider_id}:{native_id or obj.get('name') or index}",
                texture_bindings={
                    channel: path
                    for binding in material_bindings
                    for channel, path in binding.texture_paths.items()
                },
                visible=bool(obj.get("visible", True)),
            )
            model.scene_proxy_objects.append(proxy)
        scene_name = Path(str(snapshot.get("scene") or "")).name or "Untitled Scene"
        provider_name = model.provider_id[:1].upper() + model.provider_id[1:]
        model.name = (
            f"{provider_name}: {scene_name} "
            f"({real_mesh_count} meshes, {bounds_fallback_count} bounds)"
        )
        model.update_default_pose()
        return model

    @classmethod
    def from_maya_scene_snapshot(cls, snapshot: dict[str, Any]) -> "FBXMeshModel":
        """Build isolated Maya scene geometry with bounds fallback."""
        return cls.from_scene_snapshot(snapshot)

    @classmethod
    def from_scene_snapshots(
        cls,
        snapshots: list[dict[str, Any]],
        name: str = "Federated DCC Scene",
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
        retained_models: list["FBXMeshModel"] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> "FBXMeshModel":
        """Build a federated scene from raw provider snapshots with one shared world transform."""
        valid_snapshots = []
        all_bounds = []
        for snapshot in snapshots:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            objects = [
                obj for obj in (snapshot.get("objects") or [])
                if isinstance(obj, dict)
                and obj.get("type") != "error"
                and cls._include_snapshot_object_as_scene_element(obj)
                and len(obj.get("bbox") or []) == 6
            ]
            if objects:
                valid_snapshots.append(snapshot)
                provider_id = str(snapshot.get("provider_id") or "provider")
                unit_linear = str(snapshot.get("unit_linear") or "")
                up_axis = str(snapshot.get("up_axis") or "")
                for obj in objects:
                    all_bounds.append(provider_bbox_to_shared(provider_id, obj["bbox"], unit_linear, up_axis))
        retained = [model for model in (retained_models or []) if model and getattr(model, "vertices", None)]
        all_bounds.extend(cls._shared_bounds_for_model(model) for model in retained)
        if not all_bounds:
            raise ValueError("No scene sources contained renderable geometry.")

        if scene_center is None or scene_scale is None:
            normalization = SceneNormalization.from_bounds(all_bounds)
            center = normalization.center
            scale = normalization.scale
        else:
            center = scene_center
            scale = float(scene_scale)
        models = []
        for snapshot in valid_snapshots:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            models.append(cls.from_scene_snapshot(
                snapshot,
                scene_center=center,
                scene_scale=scale,
                cancel_event=cancel_event,
            ))
        models.extend(retained)
        if len(models) == 1 and not retained:
            models[0].name = name
            return models[0]
        return cls.combine_scene_models(
            models,
            name=name,
            scene_center=center,
            scene_scale=scale,
            cancel_event=cancel_event,
        )

    @staticmethod
    def _shared_bounds_for_model(model: "FBXMeshModel") -> tuple[float, float, float, float, float, float]:
        """Recover source-space bounds from a model's normalized render vertices."""
        vertices = list(getattr(model, "vertices", []) or [])
        if not vertices:
            raise ValueError("A retained scene model has no vertices.")
        center = tuple(float(value) for value in getattr(model, "scene_center", (0.0, 0.0, 0.0)))
        scale = max(1.0e-12, float(getattr(model, "scene_scale", 1.0) or 1.0))
        shared = [
            (
                float(vertex.x) / scale + center[0],
                float(vertex.y) / scale + center[1],
                float(vertex.z) / scale + center[2],
            )
            for vertex in vertices
        ]
        return (
            min(point[0] for point in shared),
            min(point[1] for point in shared),
            min(point[2] for point in shared),
            max(point[0] for point in shared),
            max(point[1] for point in shared),
            max(point[2] for point in shared),
        )

    @classmethod
    def combine_scene_models(
        cls,
        models: list["FBXMeshModel"],
        name: str = "Federated DCC Scene",
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> "FBXMeshModel":
        """Clone and combine provider models under one shared normalization."""
        valid_models = [model for model in models if model and getattr(model, "vertices", None)]
        if not valid_models:
            raise ValueError("No scene models contained renderable geometry.")

        center = tuple(
            float(value)
            for value in (
                scene_center
                if scene_center is not None
                else getattr(valid_models[0], "scene_center", (0.0, 0.0, 0.0))
            )
        )
        scale = float(
            scene_scale
            if scene_scale is not None
            else getattr(valid_models[0], "scene_scale", 1.0)
        )
        scale = max(1.0e-12, scale)

        combined = object.__new__(cls)
        combined.name = name
        combined.vertices = []
        combined.faces = []
        combined.quad_faces = []
        combined.face_colors = []
        combined.quad_face_colors = []
        combined.face_proxy_indices = []
        combined.quad_proxy_indices = []
        combined.scene_proxy_objects = []
        combined.source_texture_images = {}
        combined.provider_id = "federated"
        combined.unit_linear = "centimeters"
        combined.up_axis = "Y"
        combined.scene_center = center
        combined.scene_scale = scale
        combined.proxy_fill_color, combined.proxy_wire_color = provider_view_colors("tech_connector")
        combined.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        combined.albedo_texture.fill(QColor(125, 145, 170, 255))

        for model in valid_models:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Scene model compilation canceled.")
            combined.source_texture_images.update(getattr(model, "source_texture_images", {}) or {})
            source_center = tuple(float(value) for value in getattr(model, "scene_center", center))
            source_scale = max(1.0e-12, float(getattr(model, "scene_scale", scale) or scale))

            def reframe(point: tuple[float, float, float]) -> tuple[float, float, float]:
                shared = tuple(float(point[axis]) / source_scale + source_center[axis] for axis in range(3))
                return tuple((shared[axis] - center[axis]) * scale for axis in range(3))

            offset = len(combined.vertices)
            face_offset = len(combined.faces)
            quad_offset = len(combined.quad_faces)
            proxy_offset = len(combined.scene_proxy_objects)
            for vertex_index, vertex in enumerate(model.vertices):
                if vertex_index % 4096 == 0 and cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Scene model compilation canceled.")
                x, y, z = reframe((vertex.x, vertex.y, vertex.z))
                combined.vertices.append(MeshVertex3D(x, y, z, float(vertex.u), float(vertex.v)))
            combined.faces.extend((a + offset, b + offset, c + offset) for a, b, c in getattr(model, "faces", []))
            combined.face_colors.extend(getattr(model, "face_colors", []) or [getattr(model, "proxy_fill_color", QColor(125, 145, 170, 255)) for _ in getattr(model, "faces", [])])
            source_face_proxy_indices = list(getattr(model, "face_proxy_indices", []) or [])
            if source_face_proxy_indices:
                combined.face_proxy_indices.extend(proxy_offset + int(index) for index in source_face_proxy_indices)
            else:
                combined.face_proxy_indices.extend([-1 for _ in getattr(model, "faces", [])])
            combined.quad_faces.extend(
                (a + offset, b + offset, c + offset, d + offset)
                for a, b, c, d in getattr(model, "quad_faces", [])
            )
            combined.quad_face_colors.extend(getattr(model, "quad_face_colors", []) or [getattr(model, "proxy_fill_color", QColor(125, 145, 170, 255)) for _ in getattr(model, "quad_faces", [])])
            source_quad_proxy_indices = list(getattr(model, "quad_proxy_indices", []) or [])
            if source_quad_proxy_indices:
                combined.quad_proxy_indices.extend(proxy_offset + int(index) for index in source_quad_proxy_indices)
            else:
                combined.quad_proxy_indices.extend([-1 for _ in getattr(model, "quad_faces", [])])
            for proxy in getattr(model, "scene_proxy_objects", []) or []:
                cloned_proxy = copy.deepcopy(proxy)
                if isinstance(cloned_proxy, SceneProxyInstance):
                    cloned_proxy.index = len(combined.scene_proxy_objects)
                    cloned_proxy.center = reframe(tuple(cloned_proxy.center))
                    cloned_proxy.mesh_data.vertex_start += offset
                    cloned_proxy.mesh_data.face_start += face_offset
                    cloned_proxy.mesh_data.quad_start += quad_offset
                elif isinstance(cloned_proxy, dict):
                    cloned_proxy["index"] = len(combined.scene_proxy_objects)
                    if isinstance(cloned_proxy.get("center"), (list, tuple)) and len(cloned_proxy["center"]) >= 3:
                        cloned_proxy["center"] = reframe(tuple(cloned_proxy["center"][:3]))
                    mesh_data = cloned_proxy.get("mesh_data")
                    if isinstance(mesh_data, dict):
                        mesh_data["vertex_start"] = int(mesh_data.get("vertex_start", 0) or 0) + offset
                        mesh_data["face_start"] = int(mesh_data.get("face_start", 0) or 0) + face_offset
                        mesh_data["quad_start"] = int(mesh_data.get("quad_start", 0) or 0) + quad_offset
                combined.scene_proxy_objects.append(cloned_proxy)

            native_manifest = getattr(model, "native_fbx_manifest", None)
            if isinstance(native_manifest, dict) and native_manifest:
                combined.native_fbx_manifest = copy.deepcopy(native_manifest)
                combined.source_path = str(getattr(model, "source_path", "") or "")

        provider_counts: dict[str, int] = {}
        for item in combined.scene_proxy_objects:
            provider = str(item.get("provider_id") or "provider")
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if provider_counts:
            summary = ", ".join(f"{provider}:{count}" for provider, count in sorted(provider_counts.items()))
            combined.name = f"{name} ({summary})"
        combined.update_default_pose()
        return combined

    @staticmethod
    def _include_snapshot_object_as_scene_element(obj: dict[str, Any]) -> bool:
        object_type = str(obj.get("type") or "").lower()
        name = str(obj.get("name") or obj.get("native_id") or "").lower()
        shape_types = {str(item).lower() for item in (obj.get("shape_types") or [])}
        if "camera" in object_type or "camera" in shape_types or name.startswith("techconnector_camera"):
            return False
        if "sky" in name or "skysphere" in name or "background" in name:
            return False
        if object_type in {"worlddatalayers", "worldsettings", "levelscriptactor", "brush"}:
            return False
        template_tokens = {
            "joint",
            "follicle",
            "nurbssurface",
            "nurbscurve",
            "locator",
            "ikhandle",
            "constraint",
            "rigidbody",
            "rigid_body",
            "physics",
            "collision",
            "collider",
            "light",
            "pointlight",
            "spotlight",
            "directionallight",
            "arealight",
            "volumelight",
            "ambientlight",
        }
        if object_type in template_tokens or shape_types.intersection(template_tokens):
            return True
        return True

    @staticmethod
    def _first_diffuse_texture_from_mtls(base_dir: Path, mtllibs: list[str]) -> Path | None:
        for mtllib in mtllibs:
            mtl_path = (base_dir / mtllib).resolve()
            if not mtl_path.exists():
                continue
            for raw in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                lower = line.lower()
                if lower.startswith("map_kd "):
                    texture_name = line.split(None, 1)[1].strip().strip('"')
                    texture_path = (mtl_path.parent / texture_name).resolve()
                    if texture_path.exists():
                        return texture_path
        return None


    def _generate_sphere_primitive(self, radius: float = 1.5, rings: int = 20, sectors: int = 20):
        """Construct Maya Poly Sphere Quad Topology (Clean 4-corner Quadrilateral Grid)."""
        self.vertices.clear()
        self.faces.clear()
        self.quad_faces: list[tuple[int, int, int, int]] = []

        for r in range(rings + 1):
            v_lat = math.pi * r / float(rings)
            for s in range(sectors + 1):
                u_long = 2.0 * math.pi * s / float(sectors)
                x = radius * math.sin(v_lat) * math.cos(u_long)
                y = radius * math.cos(v_lat)
                z = radius * math.sin(v_lat) * math.sin(u_long)
                u = s / float(sectors)
                v = r / float(rings)
                self.vertices.append(MeshVertex3D(x, y, z, u, v))

        # Generate Maya Poly Sphere Quad Faces (v1 -> v2 -> v3 -> v4)
        for r in range(rings):
            for s in range(sectors):
                v1 = r * (sectors + 1) + s
                v2 = r * (sectors + 1) + s + 1
                v3 = (r + 1) * (sectors + 1) + s + 1
                v4 = (r + 1) * (sectors + 1) + s
                self.quad_faces.append((v1, v2, v3, v4))
                # Triangulated fallback representation
                self.faces.append((v1, v2, v3))
                self.faces.append((v1, v3, v4))

        # Generate Rich Mock PBR Sample Textures (Albedo Checkered Grid, Normal Map, Roughness)
        self._build_sample_pbr_textures()

    def _build_sample_pbr_textures(self):
        """Generate rich mock PBR sample texture files (Checkered Albedo, Normal Map, Roughness) for testing."""
        w, h = 1024, 1024
        self.albedo_texture = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        self.albedo_texture.fill(QColor(40, 52, 68))

        painter = QPainter(self.albedo_texture)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw 16x16 Studio Checkered Grid
        grid_size = 64
        c1 = QColor(50, 65, 85)
        c2 = QColor(70, 90, 115)
        for gx in range(0, w, grid_size):
            for gy in range(0, h, grid_size):
                col = c1 if ((gx // grid_size) + (gy // grid_size)) % 2 == 0 else c2
                painter.fillRect(gx, gy, grid_size, grid_size, QBrush(col))

        # Draw Sci-Fi Panel Accents & Center Emblem
        painter.setPen(QPen(QColor(22, 242, 106), 4))
        painter.drawRect(128, 128, 768, 768)
        painter.setPen(QPen(QColor(0, 229, 255), 3))
        painter.drawEllipse(384, 384, 256, 256)
        painter.setFont(QFont("Consolas", 24, QFont.Bold))
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "TECH CONNECTOR 3D")
        painter.end()

        # Save Sample Texture Files to Disk
        sample_dir = Path(tempfile.gettempdir()) / "tech_connector_mesh_painter"
        sample_dir.mkdir(parents=True, exist_ok=True)
        self.sample_albedo_path = str(sample_dir / "Sphere_Demo_Albedo.png")
        self.sample_normal_path = str(sample_dir / "Sphere_Demo_Normal.png")
        self.albedo_texture.save(self.sample_albedo_path)


    def paint_stroke_in_3d_space(
        self,
        hit_x: float,
        hit_y: float,
        hit_z: float,
        color: QColor,
        world_radius: float = 0.3,
        is_fill_bucket: bool = False,
        hardness: float = 0.8,
        hit_u: float | None = None,
        hit_v: float | None = None,
        brush_profile: MeshBrushProfile | None = None,
        symmetry_x: bool = False,
        radius_px_override: float | None = None,
        opacity_scale: float = 1.0,
    ):
        """Paint a stamp from the raycast hit. UV hits get dense brush stamps; world hits remain a fallback."""
        tw, th = self.albedo_texture.width(), self.albedo_texture.height()

        if is_fill_bucket:
            painter = QPainter(self.albedo_texture)
            painter.fillRect(0, 0, tw, th, QBrush(color))
            painter.end()
            return

        if hit_u is not None and hit_v is not None:
            profile = brush_profile or MeshBrushProfile(hardness=hardness)
            radius_px = max(1.0, float(radius_px_override) if radius_px_override is not None else world_radius * 95.0 * profile.radius_scale)
            self._stamp_brush_at_uv(hit_u, hit_v, radius_px, color, profile, opacity_scale)
            if symmetry_x:
                self._stamp_brush_at_uv(1.0 - hit_u, hit_v, radius_px, color, profile, opacity_scale)
            return

        painter = QPainter(self.albedo_texture)
        painter.setRenderHint(QPainter.Antialiasing)

        # For every 3D vertex within world_radius, project smooth 2D texture stroke at vertex UV
        for v in self.vertices:
            dist = math.sqrt((v.x - hit_x) ** 2 + (v.y - hit_y) ** 2 + (v.z - hit_z) ** 2)
            if dist <= world_radius:
                alpha_factor = max(0.0, 1.0 - (dist / world_radius))
                px = int(v.u * tw)
                py = int((1.0 - v.v) * th)

                stamp_rad = max(4, int(world_radius * 24.0 * alpha_factor))
                stamp_color = QColor(color.red(), color.green(), color.blue(), int(color.alpha() * alpha_factor))

                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(stamp_color))
                painter.drawEllipse(QRectF(px - stamp_rad, py - stamp_rad, stamp_rad * 2.0, stamp_rad * 2.0))

        painter.end()

    def _stamp_brush_at_uv(
        self,
        u: float,
        v: float,
        radius_px: float,
        color: QColor,
        profile: MeshBrushProfile,
        opacity_scale: float = 1.0,
    ):
        tw, th = self.albedo_texture.width(), self.albedo_texture.height()
        cx = max(0.0, min(1.0, u)) * float(tw - 1)
        cy = (1.0 - max(0.0, min(1.0, v))) * float(th - 1)
        if profile.scatter > 0.0:
            dither_seed = int(cx * 73856093) ^ int(cy * 19349663) ^ int(radius_px * 83492791)
            rng = random.Random(dither_seed)
            dab_count = max(12, min(48, int(radius_px * 0.45)))
            for _ in range(dab_count):
                ang = rng.random() * math.tau
                dist = (rng.random() ** 0.55) * radius_px * profile.scatter
                dab_radius = max(1.0, radius_px * rng.uniform(0.08, 0.22))
                self._paint_soft_disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist, dab_radius, color, profile, opacity_scale)
            return
        self._paint_soft_disc(cx, cy, radius_px, color, profile, opacity_scale)

    def _paint_soft_disc(
        self,
        cx: float,
        cy: float,
        radius_px: float,
        color: QColor,
        profile: MeshBrushProfile,
        opacity_scale: float = 1.0,
    ):
        tw, th = self.albedo_texture.width(), self.albedo_texture.height()
        x0 = max(0, int(cx - radius_px - 1))
        x1 = min(tw - 1, int(cx + radius_px + 1))
        y0 = max(0, int(cy - radius_px - 1))
        y1 = min(th - 1, int(cy + radius_px + 1))
        if x1 < x0 or y1 < y0:
            return
        radius = max(1.0, float(radius_px))
        stamp = build_brush_stamp_image(profile, radius, color)
        if stamp.isNull():
            return
        painter = QPainter(self.albedo_texture)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setOpacity(max(0.0, min(1.0, float(opacity_scale))))
        painter.drawImage(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0), stamp)
        painter.end()


class ThreeDMeshCanvas(QWidget):
    """3D viewport canvas rendering 360-degree orbit mesh and surface painting."""

    def __init__(self, parent=None, viewport_owner=None):
        super().__init__(parent)
        self.owner = viewport_owner
        self._debug_normal_cache_key: tuple[Any, ...] | None = None
        self._debug_vertex_normals: list[tuple[float, float, float]] = []
        self._debug_face_normals: list[
            tuple[tuple[float, float, float], tuple[float, float, float]]
        ] = []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def enterEvent(self, event):
        self.setFocus()
        super().enterEvent(event)

    def paintEvent(self, event):
        if not self.owner:
            return
        paint_started = time.perf_counter()
        painter = QPainter(self)
        presentation = getattr(getattr(self.owner, "game_experience_profile", None), "presentation", None)
        visual_style = str(getattr(presentation, "visual_style", "") or "")
        pixel_preview = visual_style in {"pixel_8bit", "pixel_16bit", "retro_3d"}
        painter.setRenderHint(QPainter.Antialiasing, not pixel_preview)

        if self.owner.gpu_surface_active():
            self.owner.sync_gpu_camera()
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            self._draw_gpu_interaction_overlay(painter, self.width(), self.height())
            painter.end()
            self.owner._last_viewport_paint_ms = (time.perf_counter() - paint_started) * 1000.0
            request_started = float(getattr(self.owner, "_frame_render_request_started_s", 0.0) or 0.0)
            if request_started > 0.0:
                self.owner._last_frame_total_ms = (time.perf_counter() - request_started) * 1000.0
                self.owner._frame_render_request_started_s = 0.0
            return

        # 3D Viewport Dark Background
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(10, 14, 20))

        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        dcc_view_provider = ""
        if str(getattr(self.owner, "viewport_display_source", "compiled") or "compiled").lower() == "dcc":
            dcc_view_provider = str(getattr(self.owner, "active_dcc_view_provider", "") or "").lower()
        dcc_context_wire = bool(getattr(self.owner, "show_dcc_context_wire", True))
        dcc_plate_rect = self.dcc_viewport_projection_rect()
        if dcc_view_provider:
            dcc_plate_rect = self._draw_dcc_viewport_plate(painter, w, h, dcc_view_provider)
        else:
            self._draw_viewport_backdrop(painter, w, h)

        proxy_objects = getattr(self.owner.mesh, "scene_proxy_objects", []) or []
        camera_forward = camera.view_axes()[0]

        def provider_matches_dcc_view(provider: str) -> bool:
            provider_key = str(provider or "").lower()
            return bool(
                dcc_view_provider
                and (
                    provider_key == dcc_view_provider
                    or (
                        ":" not in dcc_view_provider
                        and dcc_provider_base_key(provider_key) == dcc_provider_base_key(dcc_view_provider)
                    )
                )
            )

        def project_display_point(point: tuple[float, float, float]) -> tuple[float, float, float]:
            projection_rect = dcc_plate_rect
            sx, sy, depth = camera.project_world_to_screen(
                point,
                max(1.0, projection_rect.width()),
                max(1.0, projection_rect.height()),
            )
            display_x = sx + projection_rect.x()
            display_y = sy + projection_rect.y()
            if presentation is not None and presentation.resolution.pixel_snap:
                base_width = max(1, int(presentation.resolution.base_width))
                base_height = max(1, int(presentation.resolution.base_height))
                pixel_step = max(1, min(int(max(1.0, projection_rect.width())) // base_width, int(max(1.0, projection_rect.height())) // base_height))
                display_x = round(display_x / pixel_step) * pixel_step
                display_y = round(display_y / pixel_step) * pixel_step
            return display_x, display_y, depth

        def projected_vertex(v: MeshVertex3D) -> tuple[float, float, float, float, float]:
            point = self.owner.shared_local_to_display_local((v.x, v.y, v.z))
            sx, sy, _projected_depth = project_display_point(point)
            raw_depth = _vec_dot(_vec_sub(point, camera.eye), camera_forward)
            return sx, sy, raw_depth, v.u, v.v

        if dcc_view_provider and proxy_objects:
            screen_verts = [(0.0, 0.0, -1.0, 0.0, 0.0)] * len(self.owner.mesh.vertices)
            for proxy in proxy_objects:
                if not isinstance(proxy, (dict, SceneProxyInstance)) or not bool(proxy.get("visible", True)):
                    continue
                proxy_provider = str(proxy.get("provider_id") or "").lower()
                provider_matches = provider_matches_dcc_view(proxy_provider)
                if provider_matches:
                    continue
                if not provider_matches and not dcc_context_wire:
                    continue
                mesh_data = proxy.get("mesh_data")
                vertex_start = int(mesh_data.get("vertex_start") if isinstance(mesh_data, dict) else getattr(mesh_data, "vertex_start", 0) or 0)
                vertex_count = int(mesh_data.get("vertex_count") if isinstance(mesh_data, dict) else getattr(mesh_data, "vertex_count", 0) or 0)
                end = min(len(screen_verts), vertex_start + max(0, vertex_count))
                if 0 <= vertex_start < end:
                    for vertex_index in range(vertex_start, end):
                        screen_verts[vertex_index] = projected_vertex(self.owner.mesh.vertices[vertex_index])
        else:
            screen_verts = [projected_vertex(vertex) for vertex in self.owner.mesh.vertices]

        # Render 3D polygons with solid shading plus optional wireframe.
        shader_mode = str(getattr(self.owner, "viewport_shading_mode", "Highlight") or "Highlight").lower() == "shader"
        dcc_plate_mode = bool(dcc_view_provider)
        local_texture_mode = shader_mode and bool(getattr(self.owner, "show_texture", True)) and not proxy_objects and not dcc_plate_mode
        tex = self.owner.mesh.ensure_albedo_texture_loaded() if local_texture_mode else self.owner.mesh.albedo_texture
        tw, th = tex.width(), tex.height()
        neutral_fill = getattr(self.owner.mesh, "proxy_fill_color", QColor(78, 90, 105))
        wire_color = getattr(self.owner.mesh, "proxy_wire_color", QColor(55, 78, 98, 180))

        def presentation_color(source: QColor) -> QColor:
            color = QColor(source)
            levels = {
                "pixel_8bit": 4,
                "pixel_16bit": 8,
                "retro_3d": 12,
                "toon": 5,
                "vector_flat": 8,
            }.get(visual_style, 0)
            if levels <= 1:
                return color
            step = 255.0 / float(levels - 1)
            return QColor(
                int(round(color.red() / step) * step),
                int(round(color.green() / step) * step),
                int(round(color.blue() / step) * step),
                color.alpha(),
            )

        neutral_fill = presentation_color(neutral_fill)
        wire_color = presentation_color(wire_color)
        wire_pen = QPen(wire_color, 1)
        no_pen = QPen(Qt.NoPen)
        face_proxy_indices = getattr(self.owner.mesh, "face_proxy_indices", []) or []
        quad_proxy_indices = getattr(self.owner.mesh, "quad_proxy_indices", []) or []

        def proxy_for_index(proxy_index: int) -> SceneProxyInstance | dict[str, Any] | None:
            try:
                if 0 <= int(proxy_index) < len(proxy_objects):
                    return proxy_objects[int(proxy_index)]
            except Exception:
                pass
            return None

        def highlight_color_for_proxy(proxy: SceneProxyInstance | dict[str, Any] | None) -> QColor:
            if isinstance(proxy, (dict, SceneProxyInstance)):
                color = proxy.get("fill_color")
                if isinstance(color, QColor):
                    return QColor(color)
                return QColor(provider_view_colors(str(proxy.get("provider_id") or ""))[0])
            return QColor(neutral_fill)

        def material_color_for_proxy(proxy: SceneProxyInstance | dict[str, Any] | None, fallback: QColor) -> QColor:
            if isinstance(proxy, (dict, SceneProxyInstance)):
                color = proxy.get("material_color")
                if isinstance(color, QColor):
                    return QColor(color)
                materials = proxy.get("materials") or []
                if materials and isinstance(materials[0], SceneProxyMaterialBinding):
                    return QColor(materials[0].color)
            return QColor(fallback)

        def base_color_texture_for_proxy(
            proxy: SceneProxyInstance | dict[str, Any] | None,
        ) -> QImage | None:
            if not isinstance(proxy, (dict, SceneProxyInstance)):
                return None
            materials = proxy.get("materials") or []
            texture_path = ""
            if materials and isinstance(materials[0], SceneProxyMaterialBinding):
                texture_path = str(materials[0].texture_paths.get("base_color") or "")
            if not texture_path:
                texture_path = str((proxy.get("texture_bindings") or {}).get("base_color") or "")
            image = self.owner.mesh.source_texture_image(texture_path)
            return image if isinstance(image, QImage) and not image.isNull() else None

        def proxy_draws_filled_surface(proxy: SceneProxyInstance | dict[str, Any] | None) -> bool:
            return scene_proxy_draws_filled_surface(proxy)

        def proxy_is_light(proxy: SceneProxyInstance | dict[str, Any]) -> bool:
            values = " ".join(
                [
                    str(proxy.get("object_type") or ""),
                    str(proxy.get("type") or ""),
                    str(proxy.get("name") or ""),
                    str((proxy.get("light_data") or {}).get("kind") if isinstance(proxy.get("light_data"), dict) else ""),
                ]
            ).lower()
            return "light" in values

        def visible_scene_lights() -> list[dict[str, Any]]:
            lights = []
            for proxy in proxy_objects:
                if not isinstance(proxy, (dict, SceneProxyInstance)):
                    continue
                if not bool(proxy.get("visible", True)) or not proxy_is_light(proxy):
                    continue
                center = proxy.get("center")
                if not isinstance(center, (list, tuple)) or len(center) < 3:
                    continue
                light_data = proxy.get("light_data") if isinstance(proxy.get("light_data"), dict) else {}
                color_values = light_data.get("color") if isinstance(light_data, dict) else None
                if isinstance(color_values, (list, tuple)) and len(color_values) >= 3:
                    color = (
                        max(0.0, float(color_values[0])),
                        max(0.0, float(color_values[1])),
                        max(0.0, float(color_values[2])),
                    )
                else:
                    color = (1.0, 0.94, 0.78)
                intensity = max(0.05, min(12.0, float(light_data.get("intensity", 1.0) if isinstance(light_data, dict) else 1.0)))
                lights.append(
                    {
                        "provider": str(proxy.get("provider_id") or ""),
                        "kind": str(light_data.get("kind") or proxy.get("type") or "pointLight") if isinstance(light_data, dict) else "pointLight",
                        "position": (float(center[0]), float(center[1]), float(center[2])),
                        "color": color,
                        "intensity": intensity,
                    }
                )
            return lights

        scene_lights = visible_scene_lights()

        def lit_color(
            base: QColor,
            world_points: list[tuple[float, float, float]],
            proxy: SceneProxyInstance | dict[str, Any] | None = None,
        ) -> QColor:
            if not shader_mode or len(world_points) < 3:
                return QColor(base)
            p0, p1, p2 = world_points[0], world_points[1], world_points[2]
            normal = _vec_normalize(_vec_cross(_vec_sub(p1, p0), _vec_sub(p2, p0)), (0.0, 1.0, 0.0))
            face_center = (
                sum(point[0] for point in world_points) / len(world_points),
                sum(point[1] for point in world_points) / len(world_points),
                sum(point[2] for point in world_points) / len(world_points),
            )
            roughness = 0.5
            metalness = 0.0
            specular_weight = 0.5
            emission = (0.0, 0.0, 0.0)
            if isinstance(proxy, (dict, SceneProxyInstance)):
                materials = proxy.get("materials") or []
                if materials and isinstance(materials[0], SceneProxyMaterialBinding):
                    binding = materials[0]
                    roughness = max(0.0, min(1.0, float(binding.roughness)))
                    metalness = max(0.0, min(1.0, float(binding.metalness)))
                    specular_weight = max(0.0, min(1.0, float(binding.specular)))
                    emission = binding.emission_color
            view_direction = _vec_normalize(_vec_sub(camera.eye, face_center), (0.0, 0.0, -1.0))
            facing = max(0.0, _vec_dot(normal, view_direction))
            accum = [0.2 + facing * 0.8] * 3
            for light in scene_lights[:12]:
                kind = str(light.get("kind") or "").lower()
                light_pos = light["position"]
                to_light = _vec_sub(light_pos, face_center)
                distance = max(0.25, _vec_length(to_light))
                direction = _vec_normalize(to_light, (0.0, 1.0, 0.0))
                ndotl = max(0.0, _vec_dot(normal, direction))
                if "directional" in kind:
                    attenuation = 1.0
                else:
                    attenuation = 1.0 / (1.0 + 0.06 * distance * distance)
                strength = float(light.get("intensity") or 1.0) * ndotl * attenuation
                color = light.get("color") or (1.0, 1.0, 1.0)
                accum[0] += strength * float(color[0])
                accum[1] += strength * float(color[1])
                accum[2] += strength * float(color[2])
            highlight_power = 4.0 + (1.0 - roughness) * 60.0
            highlight = (facing ** highlight_power) * specular_weight * (0.2 + 0.8 * (1.0 - roughness))
            diffuse_weight = 1.0 - metalness * 0.45
            exposure = 1.08
            return presentation_color(QColor(
                max(0, min(255, int(base.red() * min(1.65, accum[0] * exposure) * diffuse_weight + 255.0 * (highlight + emission[0])))),
                max(0, min(255, int(base.green() * min(1.65, accum[1] * exposure) * diffuse_weight + 255.0 * (highlight + emission[1])))),
                max(0, min(255, int(base.blue() * min(1.65, accum[2] * exposure) * diffuse_weight + 255.0 * (highlight + emission[2])))),
                base.alpha(),
            ))

        def texture_sample_color(
            u: float,
            v: float,
            world_points: list[tuple[float, float, float]] | None = None,
            proxy: SceneProxyInstance | dict[str, Any] | None = None,
        ) -> QColor:
            source_texture = base_color_texture_for_proxy(proxy) or tex
            source_width, source_height = source_texture.width(), source_texture.height()
            tx = max(0, min(source_width - 1, int(max(0.0, min(1.0, u)) * float(source_width - 1))))
            ty = max(0, min(source_height - 1, int((1.0 - max(0.0, min(1.0, v))) * float(source_height - 1))))
            sampled = source_texture.pixelColor(tx, ty)
            return lit_color(sampled, world_points or [], proxy) if shader_mode else presentation_color(sampled)

        def patch_steps(points: list[QPointF]) -> int:
            if len(points) < 2:
                return 1
            min_x = min(point.x() for point in points)
            max_x = max(point.x() for point in points)
            min_y = min(point.y() for point in points)
            max_y = max(point.y() for point in points)
            max_span = max(max_x - min_x, max_y - min_y)
            return max(1, min(6, int(max_span / 42.0) + 1))

        def draw_subpath(vertices: list[QPointF], fill: QColor) -> None:
            if len(vertices) < 3:
                return
            subpath = QPainterPath()
            subpath.moveTo(vertices[0])
            for vertex in vertices[1:]:
                subpath.lineTo(vertex)
            subpath.closeSubpath()
            painter.setPen(no_pen)
            painter.setBrush(QBrush(fill))
            painter.drawPath(subpath)

        def lerp_point(a: QPointF, b: QPointF, t: float) -> QPointF:
            return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)

        def lerp_uv(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

        def draw_textured_quad(
            points: list[QPointF],
            uvs: list[tuple[float, float]],
            world_points: list[tuple[float, float, float]],
            proxy: SceneProxyInstance | dict[str, Any] | None = None,
        ) -> None:
            steps = patch_steps(points)
            for sy_idx in range(steps):
                v0 = sy_idx / float(steps)
                v1 = (sy_idx + 1) / float(steps)
                left0 = lerp_point(points[0], points[3], v0)
                right0 = lerp_point(points[1], points[2], v0)
                left1 = lerp_point(points[0], points[3], v1)
                right1 = lerp_point(points[1], points[2], v1)
                uv_left0 = lerp_uv(uvs[0], uvs[3], v0)
                uv_right0 = lerp_uv(uvs[1], uvs[2], v0)
                uv_left1 = lerp_uv(uvs[0], uvs[3], v1)
                uv_right1 = lerp_uv(uvs[1], uvs[2], v1)
                for sx_idx in range(steps):
                    u0 = sx_idx / float(steps)
                    u1 = (sx_idx + 1) / float(steps)
                    p00 = lerp_point(left0, right0, u0)
                    p10 = lerp_point(left0, right0, u1)
                    p11 = lerp_point(left1, right1, u1)
                    p01 = lerp_point(left1, right1, u0)
                    sample_a = lerp_uv(uv_left0, uv_right0, (u0 + u1) * 0.5)
                    sample_b = lerp_uv(uv_left1, uv_right1, (u0 + u1) * 0.5)
                    sample = lerp_uv(sample_a, sample_b, 0.5)
                    draw_subpath([p00, p10, p11, p01], texture_sample_color(sample[0], sample[1], world_points, proxy))

        def tri_point(a: QPointF, b: QPointF, c: QPointF, ba: float, bb: float, bc: float) -> QPointF:
            return QPointF(a.x() * ba + b.x() * bb + c.x() * bc, a.y() * ba + b.y() * bb + c.y() * bc)

        def tri_uv(
            uva: tuple[float, float],
            uvb: tuple[float, float],
            uvc: tuple[float, float],
            ba: float,
            bb: float,
            bc: float,
        ) -> tuple[float, float]:
            return (uva[0] * ba + uvb[0] * bb + uvc[0] * bc, uva[1] * ba + uvb[1] * bb + uvc[1] * bc)

        def draw_textured_triangle(
            points: list[QPointF],
            uvs: list[tuple[float, float]],
            world_points: list[tuple[float, float, float]],
            proxy: SceneProxyInstance | dict[str, Any] | None = None,
        ) -> None:
            steps = patch_steps(points)
            pa, pb, pc = points
            uva, uvb, uvc = uvs
            for row in range(steps):
                for col in range(steps - row):
                    a0 = 1.0 - (row + col) / float(steps)
                    b0 = col / float(steps)
                    c0 = row / float(steps)
                    a1 = 1.0 - (row + col + 1) / float(steps)
                    b1 = (col + 1) / float(steps)
                    c1 = row / float(steps)
                    a2 = 1.0 - (row + col + 1) / float(steps)
                    b2 = col / float(steps)
                    c2 = (row + 1) / float(steps)
                    sample = tri_uv(uva, uvb, uvc, (a0 + a1 + a2) / 3.0, (b0 + b1 + b2) / 3.0, (c0 + c1 + c2) / 3.0)
                    draw_subpath(
                        [tri_point(pa, pb, pc, a0, b0, c0), tri_point(pa, pb, pc, a1, b1, c1), tri_point(pa, pb, pc, a2, b2, c2)],
                        texture_sample_color(sample[0], sample[1], world_points, proxy),
                    )
                    if col < steps - row - 1:
                        a3 = 1.0 - (row + col + 2) / float(steps)
                        b3 = (col + 1) / float(steps)
                        c3 = (row + 1) / float(steps)
                        sample = tri_uv(uva, uvb, uvc, (a1 + a3 + a2) / 3.0, (b1 + b3 + b2) / 3.0, (c1 + c3 + c2) / 3.0)
                        draw_subpath(
                            [tri_point(pa, pb, pc, a1, b1, c1), tri_point(pa, pb, pc, a3, b3, c3), tri_point(pa, pb, pc, a2, b2, c2)],
                            texture_sample_color(sample[0], sample[1], world_points, proxy),
                        )

        quad_colors = getattr(self.owner.mesh, "quad_face_colors", []) or []
        face_colors = getattr(self.owner.mesh, "face_colors", []) or []
        render_face_indices: range | list[int] = range(len(self.owner.mesh.faces))
        if dcc_plate_mode and proxy_objects:
            visible_ranges: list[range] = []
            for proxy in proxy_objects:
                if not isinstance(proxy, (dict, SceneProxyInstance)) or not bool(proxy.get("visible", True)):
                    continue
                proxy_provider = str(proxy.get("provider_id") or "").lower()
                provider_matches = provider_matches_dcc_view(proxy_provider)
                if provider_matches:
                    continue
                if not provider_matches and not dcc_context_wire:
                    continue
                mesh_data = proxy.get("mesh_data")
                face_start = int(mesh_data.get("face_start") if isinstance(mesh_data, dict) else getattr(mesh_data, "face_start", 0) or 0)
                face_count = int(mesh_data.get("face_count") if isinstance(mesh_data, dict) else getattr(mesh_data, "face_count", 0) or 0)
                end = min(len(self.owner.mesh.faces), face_start + max(0, face_count))
                if 0 <= face_start < end:
                    visible_ranges.append(range(face_start, end))
            render_face_indices = [index for face_range in visible_ranges for index in face_range]
        if not self.owner.mesh.faces and hasattr(self.owner.mesh, 'quad_faces') and self.owner.mesh.quad_faces:
            quad_order = sorted(
                range(len(self.owner.mesh.quad_faces)),
                key=lambda index: sum(screen_verts[vertex][2] for vertex in self.owner.mesh.quad_faces[index]) / 4.0,
                reverse=True,
            )
            for quad_index in quad_order:
                i1, i2, i3, i4 = self.owner.mesh.quad_faces[quad_index]
                proxy = proxy_for_index(quad_proxy_indices[quad_index]) if quad_index < len(quad_proxy_indices) else None
                proxy_provider = str(proxy.get("provider_id") or "").lower() if isinstance(proxy, (dict, SceneProxyInstance)) else ""
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                proxy_matches_dcc_view = provider_matches_dcc_view(proxy_provider)
                if dcc_plate_mode and proxy_matches_dcc_view:
                    continue
                if dcc_plate_mode and not dcc_context_wire and not proxy_matches_dcc_view:
                    continue
                sv1, sv2, sv3, sv4 = screen_verts[i1], screen_verts[i2], screen_verts[i3], screen_verts[i4]
                if min(sv1[2], sv2[2], sv3[2], sv4[2]) <= camera.near_clip:
                    continue
                v1 = QPointF(sv1[0], sv1[1])
                v2 = QPointF(sv2[0], sv2[1])
                v3 = QPointF(sv3[0], sv3[1])
                v4 = QPointF(sv4[0], sv4[1])

                cross = (v2.x() - v1.x()) * (v3.y() - v1.y()) - (v2.y() - v1.y()) * (v3.x() - v1.x())
                if cross < 0:
                    u_sub = (sv1[3] + sv2[3] + sv3[3] + sv4[3]) / 4.0
                    v_sub = (sv1[4] + sv2[4] + sv3[4] + sv4[4]) / 4.0
                    tx = max(0, min(tw - 1, int(u_sub * tw)))
                    ty = max(0, min(th - 1, int((1.0 - v_sub) * th)))
                    quad_color = quad_colors[quad_index] if quad_index < len(quad_colors) else neutral_fill
                    fill_proxy_surface = proxy_draws_filled_surface(proxy)
                    if not fill_proxy_surface:
                        quad_color = QColor(0, 0, 0, 0)
                    if dcc_plate_mode:
                        quad_color = QColor(0, 0, 0, 0)
                    elif shader_mode:
                        quad_color = material_color_for_proxy(proxy, quad_color)
                    else:
                        quad_color = highlight_color_for_proxy(proxy)
                    if local_texture_mode:
                        quad_color = tex.pixelColor(tx, ty)
                    elif shader_mode and getattr(self.owner, "show_texture", True) and base_color_texture_for_proxy(proxy):
                        quad_color = texture_sample_color(u_sub, v_sub, proxy=proxy)
                    if shader_mode:
                        quad_color = lit_color(
                            quad_color,
                            [
                                (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                                (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                                (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                                (self.owner.mesh.vertices[i4].x, self.owner.mesh.vertices[i4].y, self.owner.mesh.vertices[i4].z),
                            ],
                            proxy,
                        )

                    path = QPainterPath()
                    path.moveTo(v1)
                    path.lineTo(v2)
                    path.lineTo(v3)
                    path.lineTo(v4)
                    path.closeSubpath()

                    if dcc_plate_mode:
                        overlay_pen = QPen(provider_view_colors(proxy_provider)[1], 1)
                        painter.setPen(overlay_pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawPath(path)
                    elif fill_proxy_surface and (
                        local_texture_mode
                        or (shader_mode and getattr(self.owner, "show_texture", True) and base_color_texture_for_proxy(proxy))
                    ):
                        quad_world_points = [
                            (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                            (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                            (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                            (self.owner.mesh.vertices[i4].x, self.owner.mesh.vertices[i4].y, self.owner.mesh.vertices[i4].z),
                        ]
                        draw_textured_quad(
                            [v1, v2, v3, v4],
                            [(sv1[3], sv1[4]), (sv2[3], sv2[4]), (sv3[3], sv3[4]), (sv4[3], sv4[4])],
                            quad_world_points,
                            proxy,
                        )
                        if not shader_mode and getattr(self.owner, "show_wireframe", True):
                            painter.setPen(wire_pen)
                            painter.setBrush(Qt.NoBrush)
                            painter.drawPath(path)
                    else:
                        if fill_proxy_surface:
                            painter.setPen(wire_pen if (not shader_mode and getattr(self.owner, "show_wireframe", True)) else no_pen)
                            painter.setBrush(QBrush(presentation_color(quad_color)))
                        else:
                            painter.setPen(wire_pen)
                            painter.setBrush(Qt.NoBrush)
                        painter.drawPath(path)
        else:
            visible_face_depths = []
            for index in render_face_indices:
                face_i1, face_i2, face_i3 = self.owner.mesh.faces[index]
                face_sv1, face_sv2, face_sv3 = screen_verts[face_i1], screen_verts[face_i2], screen_verts[face_i3]
                if min(face_sv1[2], face_sv2[2], face_sv3[2]) <= camera.near_clip:
                    continue
                face_cross = (
                    (face_sv2[0] - face_sv1[0]) * (face_sv3[1] - face_sv1[1])
                    - (face_sv2[1] - face_sv1[1]) * (face_sv3[0] - face_sv1[0])
                )
                if face_cross < 0:
                    visible_face_depths.append(((face_sv1[2] + face_sv2[2] + face_sv3[2]) / 3.0, index))
            face_order = [index for _depth, index in sorted(visible_face_depths, reverse=True)]
            for face_index in face_order:
                i1, i2, i3 = self.owner.mesh.faces[face_index]
                proxy = proxy_for_index(face_proxy_indices[face_index]) if face_index < len(face_proxy_indices) else None
                proxy_provider = str(proxy.get("provider_id") or "").lower() if isinstance(proxy, (dict, SceneProxyInstance)) else ""
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                proxy_matches_dcc_view = provider_matches_dcc_view(proxy_provider)
                if dcc_plate_mode and proxy_matches_dcc_view:
                    continue
                if dcc_plate_mode and not dcc_context_wire and not proxy_matches_dcc_view:
                    continue
                sv1, sv2, sv3 = screen_verts[i1], screen_verts[i2], screen_verts[i3]
                if min(sv1[2], sv2[2], sv3[2]) <= camera.near_clip:
                    continue
                v1 = QPointF(sv1[0], sv1[1])
                v2 = QPointF(sv2[0], sv2[1])
                v3 = QPointF(sv3[0], sv3[1])
                cross = (v2.x() - v1.x()) * (v3.y() - v1.y()) - (v2.y() - v1.y()) * (v3.x() - v1.x())
                if cross >= 0:
                    continue
                u_sub = (sv1[3] + sv2[3] + sv3[3]) / 3.0
                v_sub = (sv1[4] + sv2[4] + sv3[4]) / 3.0
                tx = max(0, min(tw - 1, int(u_sub * tw)))
                ty = max(0, min(th - 1, int((1.0 - v_sub) * th)))
                tri_color = face_colors[face_index] if face_index < len(face_colors) else neutral_fill
                fill_proxy_surface = proxy_draws_filled_surface(proxy)
                if not fill_proxy_surface:
                    tri_color = QColor(0, 0, 0, 0)
                if dcc_plate_mode:
                    tri_color = QColor(0, 0, 0, 0)
                elif shader_mode:
                    tri_color = material_color_for_proxy(proxy, tri_color)
                else:
                    tri_color = highlight_color_for_proxy(proxy)
                if local_texture_mode:
                    tri_color = tex.pixelColor(tx, ty)
                elif shader_mode and getattr(self.owner, "show_texture", True) and base_color_texture_for_proxy(proxy):
                    tri_color = texture_sample_color(u_sub, v_sub, proxy=proxy)
                if shader_mode:
                    tri_color = lit_color(
                        tri_color,
                        [
                            (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                            (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                            (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                        ],
                        proxy,
                    )

                path = QPainterPath()
                path.moveTo(v1)
                path.lineTo(v2)
                path.lineTo(v3)
                path.closeSubpath()

                if dcc_plate_mode:
                    overlay_pen = QPen(provider_view_colors(proxy_provider)[1], 1)
                    painter.setPen(overlay_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(path)
                elif fill_proxy_surface and (
                    local_texture_mode
                    or (shader_mode and getattr(self.owner, "show_texture", True) and base_color_texture_for_proxy(proxy))
                ):
                    tri_world_points = [
                        (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                        (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                        (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                    ]
                    draw_textured_triangle(
                        [v1, v2, v3],
                        [(sv1[3], sv1[4]), (sv2[3], sv2[4]), (sv3[3], sv3[4])],
                        tri_world_points,
                        proxy,
                    )
                    if not shader_mode and getattr(self.owner, "show_wireframe", True):
                        painter.setPen(wire_pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawPath(path)
                else:
                    if fill_proxy_surface:
                        painter.setPen(wire_pen if (not shader_mode and getattr(self.owner, "show_wireframe", True)) else no_pen)
                        painter.setBrush(QBrush(presentation_color(tri_color)))
                    else:
                        painter.setPen(wire_pen)
                        painter.setBrush(Qt.NoBrush)
                    painter.drawPath(path)

        if proxy_objects:
            painter.setFont(QFont("Arial", 8))
            for proxy in proxy_objects[:40]:
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                if dcc_plate_mode and isinstance(proxy, (dict, SceneProxyInstance)) and provider_matches_dcc_view(str(proxy.get("provider_id") or "")):
                    continue
                cx, cy, cz = proxy.get("center") or (0.0, 0.0, 0.0)
                point = self.owner.shared_local_to_display_local((float(cx), float(cy), float(cz)))
                sx, sy, _depth = project_display_point(point)
                name = str(proxy.get("name") or "maya_object")
                selected = proxy is getattr(self.owner, "_selected_scene_proxy", None)
                if selected:
                    painter.setPen(QPen(QColor(255, 245, 110, 230), 2))
                    painter.setBrush(QBrush(QColor(255, 245, 110, 22 if shader_mode else 35)))
                    painter.drawEllipse(QRectF(sx - 13, sy - 13, 26, 26))
                if (shader_mode or dcc_plate_mode) and not selected:
                    continue
                painter.setPen(QPen(QColor(5, 12, 18, 220), 3))
                painter.drawText(int(sx + 7), int(sy - 7), name[:42])
                label_color = proxy.get("wire_color") or wire_color
                if selected:
                    label_color = QColor(255, 245, 110)
                painter.setPen(QPen(label_color, 1))
                painter.drawText(int(sx + 7), int(sy - 7), name[:42])
                if selected and getattr(self.owner, "viewport_mode", "Paint") in {"Translate", "Rotate", "Scale"}:
                    TransformManipulatorGizmo(
                        getattr(self.owner, "viewport_mode", "Translate"),
                        getattr(self.owner, "active_transform_axis", ""),
                        getattr(self.owner, "transform_orientation_mode", "world"),
                        getattr(self.owner, "hover_transform_axis", ""),
                    ).draw_gizmo(
                        painter,
                        float(sx),
                        float(sy),
                        68.0,
                        handles=self.owner.transform_gizmo_screen_handles(proxy),
                    )

        if dcc_plate_mode and dcc_context_wire:
            self._draw_dcc_context_template_markers(painter, w, h, dcc_view_provider, camera, dcc_plate_rect)

        if not dcc_plate_mode:
            self._draw_resolved_frame_strip(painter, w, h)

        # Maya-style On-Screen Visual Brush Circle Overlay
        show_brush_preview = (
            getattr(self.owner, "viewport_mode", "Paint") == "Paint"
            or getattr(self.owner, "is_b_key_held", False)
            or getattr(self.owner, "is_resizing_brush", False)
        )
        if show_brush_preview and hasattr(self.owner, 'current_mouse_pos') and self.owner.current_mouse_pos:
            if getattr(self, 'is_b_key_held', False) and getattr(self, 'b_center_pos', None):
                mx, my = self.b_center_pos.x(), self.b_center_pos.y()
            else:
                mx, my = self.owner.current_mouse_pos.x(), self.owner.current_mouse_pos.y()

            profile = self.owner.active_brush_profile() if hasattr(self.owner, "active_brush_profile") else MeshBrushProfile()
            r = float(self.owner.brush_size) * profile.radius_scale

            preview_size = max(8, min(384, int(r * 2.0)))
            preview = build_brush_alpha_preview(profile, preview_size, QColor(22, 242, 106))
            painter.drawImage(QRectF(mx - r, my - r, r * 2.0, r * 2.0), preview)
            painter.setPen(QPen(QColor(22, 242, 106, 220), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            if str(getattr(profile, "alpha_mask", "round")) == "square":
                painter.drawRect(QRectF(mx - r, my - r, r * 2.0, r * 2.0))
            else:
                painter.drawEllipse(QRectF(mx - r, my - r, r * 2.0, r * 2.0))

            if getattr(self.owner, 'is_b_key_held', False):
                painter.setFont(QFont("Consolas", 11, QFont.Bold))
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(int(mx + r + 10), int(my), f"Maya Brush Radius: {int(r)}px")

        overlay = self.owner.current_syncsketch_markup_overlay(create=False) if hasattr(self.owner, "current_syncsketch_markup_overlay") else None
        if overlay is not None:
            overlay.draw_markups(painter)

        self._draw_deformation_weight_overlay(painter, w, h)
        self._draw_debug_vectors(painter, w, h)
        self._draw_simulation_world(painter, w, h)
        self._draw_viewport_hud(painter, w, h)
        self._draw_component_marquee(painter)
        painter.end()
        self.owner._last_viewport_paint_ms = (time.perf_counter() - paint_started) * 1000.0
        request_started = float(getattr(self.owner, "_frame_render_request_started_s", 0.0) or 0.0)
        if request_started > 0.0:
            self.owner._last_frame_total_ms = (time.perf_counter() - request_started) * 1000.0
            self.owner._frame_render_request_started_s = 0.0

    def _draw_gpu_interaction_overlay(self, painter: QPainter, w: int, h: int) -> None:
        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        selected = getattr(self.owner, "_selected_scene_proxy", None)
        if isinstance(selected, (dict, SceneProxyInstance)) and bool(selected.get("visible", True)):
            cx, cy, cz = selected.get("center") or (0.0, 0.0, 0.0)
            point = self.owner.shared_local_to_display_local((float(cx), float(cy), float(cz)))
            sx, sy, depth = camera.project_world_to_screen(point, float(w), float(h))
            if depth > camera.near_clip:
                painter.setPen(QPen(QColor(255, 245, 110, 230), 2))
                painter.setBrush(QBrush(QColor(255, 245, 110, 22)))
                painter.drawEllipse(QRectF(sx - 13, sy - 13, 26, 26))
                if getattr(self.owner, "viewport_mode", "Paint") in {"Translate", "Rotate", "Scale"}:
                    TransformManipulatorGizmo(
                        getattr(self.owner, "viewport_mode", "Translate"),
                        getattr(self.owner, "active_transform_axis", ""),
                        getattr(self.owner, "transform_orientation_mode", "world"),
                        getattr(self.owner, "hover_transform_axis", ""),
                    ).draw_gizmo(
                        painter,
                        float(sx),
                        float(sy),
                        68.0,
                        handles=self.owner.transform_gizmo_screen_handles(selected),
                    )

        show_brush_preview = (
            getattr(self.owner, "viewport_mode", "Paint") == "Paint"
            or getattr(self.owner, "is_b_key_held", False)
            or getattr(self.owner, "is_resizing_brush", False)
        )
        if show_brush_preview and hasattr(self.owner, "current_mouse_pos") and self.owner.current_mouse_pos:
            if getattr(self, "is_b_key_held", False) and getattr(self, "b_center_pos", None):
                mx, my = self.b_center_pos.x(), self.b_center_pos.y()
            else:
                mx, my = self.owner.current_mouse_pos.x(), self.owner.current_mouse_pos.y()
            profile = self.owner.active_brush_profile() if hasattr(self.owner, "active_brush_profile") else MeshBrushProfile()
            radius = float(self.owner.brush_size) * profile.radius_scale
            preview_size = max(8, min(384, int(radius * 2.0)))
            preview = build_brush_alpha_preview(profile, preview_size, QColor(22, 242, 106))
            painter.drawImage(QRectF(mx - radius, my - radius, radius * 2.0, radius * 2.0), preview)
            painter.setPen(QPen(QColor(22, 242, 106, 220), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            shape = QRectF(mx - radius, my - radius, radius * 2.0, radius * 2.0)
            if str(getattr(profile, "alpha_mask", "round")) == "square":
                painter.drawRect(shape)
            else:
                painter.drawEllipse(shape)

        overlay = self.owner.current_syncsketch_markup_overlay(create=False) if hasattr(self.owner, "current_syncsketch_markup_overlay") else None
        if overlay is not None:
            overlay.draw_markups(painter)
        self._draw_deformation_weight_overlay(painter, w, h)
        self._draw_debug_vectors(painter, w, h)
        self._draw_simulation_world(painter, w, h)
        self._draw_resolved_frame_strip(painter, w, h)
        self._draw_viewport_hud(painter, w, h)
        self._draw_component_marquee(painter)

    def _draw_component_marquee(self, painter: QPainter) -> None:
        if not getattr(self.owner, "_component_marquee_dragging", False):
            return
        start = getattr(self.owner, "_component_marquee_start", None)
        current = getattr(self.owner, "_component_marquee_current", None)
        if start is None or current is None:
            return
        rectangle = QRectF(start, current).normalized()
        painter.setPen(QPen(QColor(70, 190, 255, 230), 1, Qt.DashLine))
        painter.setBrush(QBrush(QColor(40, 145, 225, 35)))
        painter.drawRect(rectangle)

    def _draw_debug_vectors(self, painter: QPainter, w: int, h: int) -> None:
        show_axes = bool(getattr(self.owner, "show_object_vector_handles", False))
        show_vertex_normals = bool(getattr(self.owner, "show_vertex_normals", False))
        show_face_normals = bool(getattr(self.owner, "show_face_normals", False))
        if not (show_axes or show_vertex_normals or show_face_normals):
            return

        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        projection_rect = self.dcc_viewport_projection_rect()
        projection_width = max(1.0, projection_rect.width())
        projection_height = max(1.0, projection_rect.height())

        def project(point: tuple[float, float, float]) -> tuple[QPointF, float]:
            display_point = self.owner.shared_local_to_display_local(point)
            sx, sy, depth = camera.project_world_to_screen(
                display_point, projection_width, projection_height
            )
            return QPointF(sx + projection_rect.x(), sy + projection_rect.y()), depth

        if show_axes:
            self._draw_object_axes(painter, project, camera)
        if show_vertex_normals or show_face_normals:
            self._draw_mesh_normals(
                painter,
                project,
                camera,
                show_vertex_normals=show_vertex_normals,
                show_face_normals=show_face_normals,
            )

    def _draw_object_axes(self, painter: QPainter, project: Any, camera: MayaViewportCamera) -> None:
        proxies = [
            proxy
            for proxy in (getattr(self.owner.mesh, "scene_proxy_objects", []) or [])
            if isinstance(proxy, (dict, SceneProxyInstance)) and bool(proxy.get("visible", True))
        ]
        selected = getattr(self.owner, "_selected_scene_proxy", None)
        if isinstance(selected, (dict, SceneProxyInstance)) and selected not in proxies:
            proxies.insert(0, selected)
        if not proxies:
            proxies = [{"center": getattr(self.owner.mesh, "scene_center", (0.0, 0.0, 0.0))}]

        axis_length = max(
            0.08,
            float(getattr(self.owner, "debug_vector_length", 0.35)),
        )
        colors = {
            "X": QColor(245, 76, 76, 235),
            "Y": QColor(62, 222, 112, 235),
            "Z": QColor(78, 145, 255, 235),
        }
        fallback_basis = {
            "X": (1.0, 0.0, 0.0),
            "Y": (0.0, 1.0, 0.0),
            "Z": (0.0, 0.0, 1.0),
        }
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        for proxy in proxies[:256]:
            center_value = proxy.get("center") or (0.0, 0.0, 0.0)
            center = tuple(float(value) for value in center_value[:3])
            rotation = dict(proxy.get("local_transform") or proxy.get("source_transform") or {}).get("rotation")
            basis_display = self.owner._rotation_basis_display(proxy, rotation)
            basis_local: dict[str, tuple[float, float, float]] = {}
            if basis_display:
                for axis, vector in basis_display.items():
                    basis_local[axis] = _vec_normalize(self.owner.display_local_to_shared_local(vector))
            else:
                basis_local = fallback_basis
            start, start_depth = project(center)
            if start_depth <= camera.near_clip:
                continue
            for axis, vector in basis_local.items():
                end_world = _vec_add(
                    center,
                    _vec_scale(_vec_normalize(vector, fallback_basis[axis]), axis_length),
                )
                end, end_depth = project(end_world)
                if end_depth <= camera.near_clip:
                    continue
                color = colors[axis]
                painter.setPen(QPen(color, 2.0))
                painter.drawLine(start, end)
                dx, dy = end.x() - start.x(), end.y() - start.y()
                screen_length = math.hypot(dx, dy)
                if screen_length > 3.0:
                    ux, uy = dx / screen_length, dy / screen_length
                    side_x, side_y = -uy, ux
                    arrow = QPolygonF([
                        end,
                        QPointF(end.x() - ux * 8.0 + side_x * 4.0, end.y() - uy * 8.0 + side_y * 4.0),
                        QPointF(end.x() - ux * 8.0 - side_x * 4.0, end.y() - uy * 8.0 - side_y * 4.0),
                    ])
                    painter.setBrush(QBrush(color))
                    painter.drawPolygon(arrow)
                    painter.drawText(QPointF(end.x() + side_x * 5.0, end.y() + side_y * 5.0), axis)
            painter.setBrush(Qt.NoBrush)

    def _ensure_debug_normal_cache(self) -> None:
        mesh = self.owner.mesh
        key = (
            id(mesh),
            id(mesh.vertices),
            id(mesh.faces),
            len(mesh.vertices),
            len(mesh.faces),
            int(getattr(self.owner, "_paint_geometry_revision", 0)),
        )
        if key == self._debug_normal_cache_key:
            return
        vertices = [(float(v.x), float(v.y), float(v.z)) for v in mesh.vertices]
        accumulated = [(0.0, 0.0, 0.0) for _vertex in vertices]
        face_normals: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        for face in mesh.faces:
            if len(face) < 3 or any(index < 0 or index >= len(vertices) for index in face[:3]):
                continue
            a, b, c = (vertices[face[index]] for index in range(3))
            cross = _vec_cross(_vec_sub(b, a), _vec_sub(c, a))
            if _vec_length(cross) <= 1.0e-12:
                continue
            normal = _vec_normalize(cross, (0.0, 1.0, 0.0))
            center = tuple((a[index] + b[index] + c[index]) / 3.0 for index in range(3))
            face_normals.append((center, normal))
            for vertex_index in face[:3]:
                accumulated[vertex_index] = _vec_add(accumulated[vertex_index], cross)
        self._debug_vertex_normals = [_vec_normalize(normal, (0.0, 1.0, 0.0)) for normal in accumulated]
        self._debug_face_normals = face_normals
        self._debug_normal_cache_key = key

    def _draw_mesh_normals(
        self,
        painter: QPainter,
        project: Any,
        camera: MayaViewportCamera,
        *,
        show_vertex_normals: bool,
        show_face_normals: bool,
    ) -> None:
        self._ensure_debug_normal_cache()
        length = max(0.001, float(getattr(self.owner, "debug_normal_length", 0.2)))
        stride = max(1, int(getattr(self.owner, "debug_normal_stride", 8)))
        max_vectors = 5000

        def draw_vector(origin: tuple[float, float, float], normal: tuple[float, float, float], color: QColor) -> None:
            start, start_depth = project(origin)
            end, end_depth = project(_vec_add(origin, _vec_scale(normal, length)))
            if start_depth <= camera.near_clip or end_depth <= camera.near_clip:
                return
            painter.setPen(QPen(color, 1.25))
            painter.drawLine(start, end)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(end, 1.8, 1.8)

        if show_vertex_normals:
            vertices = self.owner.mesh.vertices
            effective_stride = max(stride, int(math.ceil(max(1, len(vertices)) / max_vectors)))
            color = QColor(56, 225, 238, 210)
            for index in range(0, min(len(vertices), len(self._debug_vertex_normals)), effective_stride):
                vertex = vertices[index]
                draw_vector((float(vertex.x), float(vertex.y), float(vertex.z)), self._debug_vertex_normals[index], color)
        if show_face_normals:
            effective_stride = max(stride, int(math.ceil(max(1, len(self._debug_face_normals)) / max_vectors)))
            color = QColor(255, 183, 65, 220)
            for center, normal in self._debug_face_normals[::effective_stride]:
                draw_vector(center, normal, color)
        painter.setBrush(Qt.NoBrush)

    def _draw_viewport_backdrop(self, painter: QPainter, w: int, h: int) -> None:
        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        extent = max(6.0, min(80.0, float(getattr(camera, "distance", 8.0)) * 3.0))
        step = self._nice_grid_step(extent / 12.0)
        line_count = max(6, min(40, int(math.ceil(extent / step))))
        coord = str(getattr(self.owner, "viewer_coord_space", "maya") or "maya").lower()

        def point(a: float, b: float) -> tuple[float, float, float]:
            if coord == "maya":
                return (a, 0.0, b)
            return (a, b, 0.0)

        def draw_segment(p1: tuple[float, float, float], p2: tuple[float, float, float], pen: QPen) -> None:
            sx1, sy1, z1 = camera.project_world_to_screen(p1, float(w), float(h))
            sx2, sy2, z2 = camera.project_world_to_screen(p2, float(w), float(h))
            if z1 <= 0.11 and z2 <= 0.11:
                return
            if max(abs(sx1), abs(sx2), abs(sy1), abs(sy2)) > 100000:
                return
            painter.setPen(pen)
            painter.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))

        minor_pen = QPen(QColor(28, 42, 54, 95), 1)
        major_pen = QPen(QColor(65, 95, 120, 150), 1)
        axis_x_pen = QPen(QColor(120, 55, 55, 155), 1)
        axis_z_pen = QPen(QColor(55, 120, 75, 155), 1)
        limit = line_count * step
        for i in range(-line_count, line_count + 1):
            value = i * step
            pen = major_pen if i % 5 == 0 else minor_pen
            draw_segment(point(-limit, value), point(limit, value), axis_z_pen if i == 0 else pen)
            draw_segment(point(value, -limit), point(value, limit), axis_x_pen if i == 0 else pen)

    def _nice_grid_step(self, raw_step: float) -> float:
        raw = max(0.01, float(raw_step))
        power = 10.0 ** math.floor(math.log10(raw))
        normalized = raw / power
        if normalized <= 1.0:
            nice = 1.0
        elif normalized <= 2.0:
            nice = 2.0
        elif normalized <= 5.0:
            nice = 5.0
        else:
            nice = 10.0
        return nice * power

    def dcc_viewport_projection_rect(self) -> QRectF:
        w = float(max(1, self.width()))
        h = float(max(1, self.height()))
        source_aspect = 0.0
        if str(getattr(self.owner, "viewport_display_source", "") or "").lower() == "dcc":
            frame = getattr(self.owner, "_dcc_stream_frame", QImage())
            provider = str(getattr(self.owner, "active_dcc_view_provider", "") or "").lower()
            frame_provider = str(getattr(self.owner, "_dcc_stream_provider", "") or "").lower()
            if isinstance(frame, QImage) and not frame.isNull() and provider == frame_provider:
                source_aspect = float(frame.width()) / max(1.0, float(frame.height()))
        else:
            camera = getattr(self.owner, "viewport_camera", None)
            source_aspect = max(0.0, float(getattr(camera, "aspect_ratio", 0.0) or 0.0))
        if source_aspect <= 0.0:
            return QRectF(0.0, 0.0, w, h)
        target_aspect = w / h
        target = QRectF(0.0, 0.0, w, h)
        if source_aspect > target_aspect:
            target_height = w / max(1.0e-6, source_aspect)
            target.setY((h - target_height) * 0.5)
            target.setHeight(target_height)
        elif source_aspect < target_aspect:
            target_width = h * source_aspect
            target.setX((w - target_width) * 0.5)
            target.setWidth(target_width)
        return target

    def _draw_dcc_viewport_plate(self, painter: QPainter, w: int, h: int, provider: str) -> QRectF:
        frame = getattr(self.owner, "_dcc_stream_frame", QImage())
        frame_provider = str(getattr(self.owner, "_dcc_stream_provider", "") or "").lower()
        if isinstance(frame, QImage) and not frame.isNull() and frame_provider == str(provider or "").lower():
            target = self.dcc_viewport_projection_rect()
            painter.fillRect(0, 0, w, h, QColor(5, 8, 11))
            painter.drawImage(target, frame, QRectF(0.0, 0.0, float(frame.width()), float(frame.height())))
            return target
        painter.fillRect(0, 0, w, h, QColor(8, 11, 15))
        self._draw_viewport_backdrop(painter, w, h)
        return QRectF(0.0, 0.0, float(w), float(h))

    def _draw_dcc_context_template_markers(
        self,
        painter: QPainter,
        w: int,
        h: int,
        active_provider: str,
        camera: MayaViewportCamera,
        projection_rect: QRectF,
    ) -> None:
        snapshots = getattr(self.owner, "_dcc_scene_snapshots", {}) or {}
        proxy_objects = getattr(self.owner.mesh, "scene_proxy_objects", []) or []
        painter.setFont(QFont("Arial", 8, QFont.Bold))

        def project_shared(point: tuple[float, float, float]) -> tuple[float, float, float]:
            display = self.owner.shared_local_to_display_local(point)
            sx, sy, depth = camera.project_world_to_screen(
                display,
                max(1.0, projection_rect.width()),
                max(1.0, projection_rect.height()),
            )
            return sx + projection_rect.x(), sy + projection_rect.y(), depth

        def draw_cross_marker(sx: float, sy: float, color: QColor, label: str, radius: float = 8.0) -> None:
            painter.setPen(QPen(QColor(2, 6, 9, 210), 3))
            painter.drawLine(QPointF(sx - radius, sy), QPointF(sx + radius, sy))
            painter.drawLine(QPointF(sx, sy - radius), QPointF(sx, sy + radius))
            painter.setPen(QPen(color, 1))
            painter.drawLine(QPointF(sx - radius, sy), QPointF(sx + radius, sy))
            painter.drawLine(QPointF(sx, sy - radius), QPointF(sx, sy + radius))
            if label:
                painter.setPen(QPen(QColor(2, 6, 9, 220), 3))
                painter.drawText(int(sx + radius + 4), int(sy - 4), label[:32])
                painter.setPen(QPen(color, 1))
                painter.drawText(int(sx + radius + 4), int(sy - 4), label[:32])

        def kind_for_proxy(proxy: SceneProxyInstance | dict[str, Any]) -> str:
            values = " ".join(
                [
                    str(proxy.get("object_type") or ""),
                    str(proxy.get("type") or ""),
                    " ".join(str(item) for item in (proxy.get("shape_types") or [])),
                    str(proxy.get("name") or ""),
                ]
            ).lower()
            if any(token in values for token in ("joint", "skeleton", "bone", "ik", "constraint")):
                return "joint"
            if "follicle" in values:
                return "fol"
            if any(token in values for token in ("nurbssurface", "nurbs surface", "nurbscurve", "nurbs curve", "curve")):
                return "nurbs"
            if any(token in values for token in ("physics", "rigid", "collision", "collider", "body", "cloth")):
                return "phys"
            if "light" in values:
                return "light"
            if "camera" in values:
                return "cam"
            if "mesh" in values or str(proxy.get("representation") or "") == "mesh":
                return ""
            return "tmpl"

        for proxy in proxy_objects:
            if not isinstance(proxy, (dict, SceneProxyInstance)):
                continue
            provider = str(proxy.get("provider_id") or "").lower()
            provider_matches_active = (
                provider == active_provider
                or (":" not in active_provider and dcc_provider_base_key(provider) == dcc_provider_base_key(active_provider))
            )
            if not provider or provider_matches_active:
                continue
            if not bool(proxy.get("visible", True)):
                continue
            kind = kind_for_proxy(proxy)
            if not kind:
                continue
            center = proxy.get("center")
            if not isinstance(center, (list, tuple)) or len(center) < 3:
                continue
            sx, sy, depth = project_shared((float(center[0]), float(center[1]), float(center[2])))
            if depth <= 0.11:
                continue
            color = provider_view_colors(provider)[1]
            label = f"{kind}:{proxy.get('name') or proxy.get('native_id') or provider}"
            radius = 10.0 if kind in {"joint", "phys", "nurbs"} else 8.0
            draw_cross_marker(sx, sy, color, label, radius)

        for provider, snapshot in snapshots.items():
            provider_key = str(provider or "").lower()
            provider_matches_active = (
                provider_key == active_provider
                or (":" not in active_provider and dcc_provider_base_key(provider_key) == dcc_provider_base_key(active_provider))
            )
            if provider_matches_active:
                continue
            unit_linear = str(snapshot.get("unit_linear") or "")
            up_axis = str(snapshot.get("up_axis") or "")
            color = provider_view_colors(provider_key)[1]
            for cam in (snapshot.get("cameras") or [])[:80]:
                if not isinstance(cam, dict):
                    continue
                translation = cam.get("translation")
                if not isinstance(translation, (list, tuple)) or len(translation) < 3:
                    continue
                try:
                    shared = provider_world_to_view(
                        provider_key,
                        float(translation[0]),
                        float(translation[1]),
                        float(translation[2]),
                        unit_linear,
                        up_axis,
                    )
                except Exception:
                    continue
                sx, sy, depth = project_shared(shared)
                if depth <= 0.11:
                    continue
                draw_cross_marker(sx, sy, color, f"cam:{cam.get('name') or cam.get('native_id') or provider_key}", 9.0)

    def _draw_resolved_frame_strip(self, painter: QPainter, w: int, h: int) -> None:
        resolved_frames = getattr(self.owner, "_resolved_shaded_frames", {}) or {}
        if not getattr(self.owner, "show_resolved_shaded_frames", False):
            return
        if not resolved_frames:
            status = getattr(self.owner, "_resolved_shaded_status", "")
            if status:
                self._draw_pill(painter, 16, h - 44, status[:120], QColor(20, 31, 42, 210), QColor(125, 178, 205))
            return
        thumb_w = min(260, max(170, int(w * 0.19)))
        first_image = next((image for image in resolved_frames.values() if not image.isNull()), None)
        aspect = (float(first_image.height()) / max(1.0, float(first_image.width()))) if first_image is not None else 9.0 / 16.0
        thumb_h = max(90, min(190, int(thumb_w * aspect)))
        margin = 14
        x = w - thumb_w - margin
        y = margin + 24
        panel_h = (thumb_h + 30) * min(4, len(resolved_frames)) + 12
        painter.fillRect(QRectF(x - 10, y - 30, thumb_w + 20, panel_h), QColor(5, 9, 14, 185))
        painter.setPen(QPen(QColor(52, 88, 112, 185), 1))
        painter.drawRect(QRectF(x - 10, y - 30, thumb_w + 20, panel_h))
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        painter.setPen(QPen(QColor(210, 235, 245)))
        painter.drawText(x, y - 12, "Resolved material frames")
        for provider, image in list(resolved_frames.items())[:4]:
            if image.isNull():
                continue
            image_aspect = float(image.height()) / max(1.0, float(image.width()))
            item_h = max(80, min(210, int(thumb_w * image_aspect)))
            painter.setPen(QPen(provider_view_colors(provider)[1], 1))
            painter.drawText(x, y + item_h + 14, provider)
            painter.drawImage(QRectF(x, y, thumb_w, item_h), image)
            painter.setPen(QPen(provider_view_colors(provider)[1], 1))
            painter.drawRect(x, y, thumb_w, item_h)
            y += item_h + 30

    def _draw_deformation_weight_overlay(self, painter: QPainter, w: int, h: int) -> None:
        combo = getattr(self.owner, "paint_target_combo", None)
        target = str(combo.currentData() or "color") if combo is not None else "color"
        if target == "color" or str(getattr(self.owner, "viewport_mode", "")) != "Paint":
            return
        maps = getattr(self.owner, "deformation_weight_maps", {}) or {}
        weight_map = maps.get(target)
        mesh = getattr(self.owner, "mesh", None)
        if weight_map is None or mesh is None or len(weight_map.values) != len(mesh.vertices):
            return
        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        projected = [
            camera.project_world_to_screen(
                self.owner.shared_local_to_display_local((vertex.x, vertex.y, vertex.z)),
                float(w),
                float(h),
            )
            for vertex in mesh.vertices
        ]
        faces = list(getattr(mesh, "faces", ()) or ())
        depth_order = sorted(
            (
                (sum(projected[index][2] for index in face) / len(face), face)
                for face in faces
                if len(face) >= 3 and min(face) >= 0 and max(face) < len(projected)
            ),
            reverse=True,
            key=lambda item: item[0],
        )
        painter.save()
        for _depth, face in depth_order:
            points = [projected[index] for index in face]
            if min(point[2] for point in points) <= camera.near_clip:
                continue
            amount = sum(weight_map.values[index] for index in face) / len(face)
            color = QColor(
                int(30 + 20 * amount),
                int(80 + 165 * amount),
                int(220 - 170 * amount),
                145,
            )
            painter.setPen(QPen(color.lighter(125), 1))
            painter.setBrush(QBrush(color))
            painter.drawPolygon(QPolygonF([QPointF(point[0], point[1]) for point in points]))
        painter.restore()

    def _draw_simulation_world(self, painter: QPainter, w: int, h: int) -> None:
        world = getattr(self.owner, "simulation_world", None)
        if world is None:
            return
        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())

        def project(point) -> tuple[float, float, float]:
            display = self.owner.shared_local_to_display_local(tuple(float(value) for value in point))
            return camera.project_world_to_screen(display, float(w), float(h))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        for curve in list(getattr(world, "curve_fields", []) or []):
            projected = [project(point) for point in curve.points]
            painter.setPen(QPen(QColor(245, 205, 70, 210), 2, Qt.DashLine))
            for first, second in zip(projected, projected[1:]):
                if first[2] > camera.near_clip and second[2] > camera.near_clip:
                    painter.drawLine(QPointF(first[0], first[1]), QPointF(second[0], second[1]))
            if curve.closed and len(projected) > 2 and projected[-1][2] > camera.near_clip and projected[0][2] > camera.near_clip:
                painter.drawLine(QPointF(projected[-1][0], projected[-1][1]), QPointF(projected[0][0], projected[0][1]))
        for constraint in list(getattr(world, "constraints", []) or [])[:6000]:
            if not constraint.enabled:
                continue
            first = world.particles[constraint.first]
            second = world.particles[constraint.second]
            ax, ay, ad = project(first.position)
            bx, by, bd = project(second.position)
            if ad <= camera.near_clip or bd <= camera.near_clip:
                continue
            if constraint.constraint_type == "bend":
                color = QColor(90, 145, 255, 80)
            elif constraint.constraint_type == "shear":
                color = QColor(255, 165, 65, 105)
            else:
                color = QColor(80, 235, 170, 135)
            painter.setPen(QPen(color, 1))
            painter.drawLine(QPointF(ax, ay), QPointF(bx, by))
        colors = {
            "water": QColor(45, 155, 255, 210),
            "goo": QColor(90, 230, 95, 220),
            "gravy": QColor(165, 95, 45, 225),
            "soup": QColor(215, 145, 55, 225),
            "jello": QColor(235, 70, 125, 215),
            "playdoh": QColor(230, 75, 95, 230),
            "glass": QColor(175, 225, 245, 150),
            "metal": QColor(165, 175, 190, 235),
            "cotton": QColor(230, 230, 225, 220),
            "silk": QColor(225, 130, 210, 220),
            "denim": QColor(55, 95, 185, 225),
            "fire": QColor(255, 105, 20, 225),
            "plasma": QColor(80, 225, 255, 235),
        }
        surface_faces = list(getattr(world, "surface_faces", []) or [])
        for face in surface_faces[:6000]:
            if len(face) < 3 or min(face) < 0 or max(face) >= len(world.particles):
                continue
            projected = [project(world.particles[index].position) for index in face]
            if any(point[2] <= camera.near_clip for point in projected):
                continue
            material = world.particles[face[0]].material
            face_color = QColor(colors.get(material, QColor(210, 220, 230, 210)))
            face_color.setAlpha(90 if material == "glass" else 65)
            painter.setPen(QPen(face_color.lighter(135), 1))
            painter.setBrush(QBrush(face_color))
            painter.drawPolygon(QPolygonF([QPointF(point[0], point[1]) for point in projected]))
        effect_system = getattr(world, "effect_system", None)
        if effect_system is not None:
            handle = self.owner.fx_emitter_screen_handle() if getattr(
                self.owner, "_fx_manipulator_emitter_id", ""
            ) else None
            if handle is not None and float(handle["depth"]) > camera.near_clip:
                center = handle["screen"]
                pulse = 1.0 + 0.08 * math.sin(time.monotonic() * 7.0)
                painter.setBrush(QBrush(QColor(45, 225, 255, 65)))
                painter.setPen(QPen(QColor(80, 235, 255, 245), 2.5))
                painter.drawEllipse(center, 13.0 * pulse, 13.0 * pulse)
                painter.setPen(QPen(QColor(220, 252, 255, 235), 1.5))
                painter.drawLine(QPointF(center.x() - 20.0, center.y()), QPointF(center.x() + 20.0, center.y()))
                painter.drawLine(QPointF(center.x(), center.y() - 20.0), QPointF(center.x(), center.y() + 20.0))
                painter.setPen(QPen(QColor(190, 248, 255, 245), 1.0))
                painter.drawText(QPointF(center.x() + 18.0, center.y() - 14.0), "LIVE EMITTER")
            for emitter in effect_system.emitters:
                renderer_type = str(emitter.renderer.get("type") or "sprite").lower()
                emitter_particles = [
                    particle for particle in world.particles
                    if particle.alive and particle.emitter_id == emitter.emitter_id
                ]
                if renderer_type == "beam":
                    points = [project(particle.position) for particle in sorted(emitter_particles, key=lambda item: item.particle_id)]
                    painter.setPen(QPen(QColor(150, 220, 255, 220), 2))
                    for first, second in zip(points, points[1:]):
                        if first[2] > camera.near_clip and second[2] > camera.near_clip:
                            painter.drawLine(QPointF(first[0], first[1]), QPointF(second[0], second[1]))
                elif renderer_type == "ribbon":
                    for particle in emitter_particles[:4000]:
                        trail = effect_system.trail_history.get(particle.particle_id, ())
                        points = [project(position) for position in trail]
                        color = QColor.fromRgbF(*particle.color)
                        painter.setPen(QPen(color, max(1.0, particle.size * 1.5)))
                        for first, second in zip(points, points[1:]):
                            if first[2] > camera.near_clip and second[2] > camera.near_clip:
                                painter.drawLine(QPointF(first[0], first[1]), QPointF(second[0], second[1]))
        if bool(getattr(self.owner, "show_simulation_diagnostics", False)):
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 196, 55, 210), 1.5, Qt.DashLine))
            for collider in list(getattr(world, "plane_colliders", []) or [])[:64]:
                normal = tuple(float(value) for value in collider.normal)
                origin = tuple(float(value) * float(collider.offset) for value in normal)
                start = project(origin)
                end = project(tuple(origin[index] + normal[index] for index in range(3)))
                if start[2] > camera.near_clip and end[2] > camera.near_clip:
                    painter.drawLine(QPointF(start[0], start[1]), QPointF(end[0], end[1]))
                    painter.drawEllipse(QPointF(start[0], start[1]), 5.0, 5.0)
            for collider in list(getattr(world, "sphere_colliders", []) or [])[:512]:
                center = tuple(float(value) for value in collider.center)
                projected_center = project(center)
                edge_x = project((center[0] + float(collider.radius), center[1], center[2]))
                edge_y = project((center[0], center[1] + float(collider.radius), center[2]))
                if projected_center[2] <= camera.near_clip:
                    continue
                radius = max(
                    3.0,
                    math.hypot(edge_x[0] - projected_center[0], edge_x[1] - projected_center[1]),
                    math.hypot(edge_y[0] - projected_center[0], edge_y[1] - projected_center[1]),
                )
                painter.drawEllipse(QPointF(projected_center[0], projected_center[1]), radius, radius)
            painter.setPen(QPen(QColor(255, 135, 45, 150), 1.0))
            remaining_edges = 6000
            for collider in list(getattr(world, "mesh_colliders", []) or []):
                vertices = list(getattr(collider, "vertices", []) or [])
                for face in list(getattr(collider, "faces", []) or []):
                    if remaining_edges <= 0 or len(face) < 2:
                        break
                    for first_index, second_index in zip(face, (*face[1:], face[0])):
                        if min(first_index, second_index) < 0 or max(first_index, second_index) >= len(vertices):
                            continue
                        first, second = project(vertices[first_index]), project(vertices[second_index])
                        if first[2] > camera.near_clip and second[2] > camera.near_clip:
                            painter.drawLine(QPointF(first[0], first[1]), QPointF(second[0], second[1]))
                            remaining_edges -= 1
            for contact in list(getattr(world, "debug_contacts", []) or [])[-4096:]:
                point = tuple(contact.get("point") or (0.0, 0.0, 0.0))
                normal = tuple(contact.get("normal") or (0.0, 1.0, 0.0))
                penetration = max(0.0, float(contact.get("penetration", 0.0) or 0.0))
                start = project(point)
                normal_length = max(0.08, min(0.75, 0.15 + penetration))
                end = project(tuple(float(point[index]) + float(normal[index]) * normal_length for index in range(3)))
                if start[2] <= camera.near_clip or end[2] <= camera.near_clip:
                    continue
                color = QColor(255, 72, 95, 235)
                painter.setPen(QPen(color, 2.0))
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QPointF(start[0], start[1]), 3.0, 3.0)
                painter.drawLine(QPointF(start[0], start[1]), QPointF(end[0], end[1]))
            for joint in list(getattr(world, "debug_physics_joints", []) or [])[:2048]:
                first_anchor = tuple(joint.get("first_anchor") or (0.0, 0.0, 0.0))
                second_anchor = tuple(joint.get("second_anchor") or first_anchor)
                first_point, second_point = project(first_anchor), project(second_anchor)
                if first_point[2] <= camera.near_clip or second_point[2] <= camera.near_clip:
                    continue
                broken = bool(joint.get("broken", False))
                color = QColor(255, 72, 95, 235) if broken else QColor(80, 225, 155, 235)
                painter.setPen(QPen(color, 2.0, Qt.DashLine if broken else Qt.SolidLine))
                painter.setBrush(QBrush(color))
                painter.drawLine(QPointF(first_point[0], first_point[1]), QPointF(second_point[0], second_point[1]))
                painter.drawEllipse(QPointF(first_point[0], first_point[1]), 6.0, 6.0)
                painter.drawEllipse(QPointF(second_point[0], second_point[1]), 6.0, 6.0)
                axis = _vec_normalize(tuple(float(value) for value in joint.get("axis") or (1.0, 0.0, 0.0)))
                axis_end = project(_vec_add(first_anchor, _vec_scale(axis, 0.75)))
                if axis_end[2] > camera.near_clip:
                    painter.setPen(QPen(QColor(80, 180, 255, 245), 3.0))
                    painter.setBrush(QBrush(QColor(80, 180, 255, 245)))
                    painter.drawLine(QPointF(first_point[0], first_point[1]), QPointF(axis_end[0], axis_end[1]))
                    painter.drawEllipse(QPointF(axis_end[0], axis_end[1]), 5.0, 5.0)
                arc_points = [project(tuple(point)) for point in joint.get("limit_arc") or ()]
                painter.setPen(QPen(QColor(255, 196, 55, 225), 2.0))
                for arc_first, arc_second in zip(arc_points, arc_points[1:]):
                    if arc_first[2] > camera.near_clip and arc_second[2] > camera.near_clip:
                        painter.drawLine(QPointF(arc_first[0], arc_first[1]), QPointF(arc_second[0], arc_second[1]))
                if bool(joint.get("motor_enabled", False)):
                    speed = float(joint.get("motor_speed", 0.0) or 0.0)
                    motor_end = project(tuple(first_anchor[index] + axis[index] * (0.35 if speed >= 0.0 else -0.35) for index in range(3)))
                    if motor_end[2] > camera.near_clip:
                        painter.setPen(QPen(QColor(80, 180, 255, 235), 3.0))
                        painter.drawLine(QPointF(first_point[0], first_point[1]), QPointF(motor_end[0], motor_end[1]))
        for particle in list(getattr(world, "particles", []) or [])[:12000]:
            if not particle.alive:
                continue
            sx, sy, depth = project(particle.position)
            if depth <= camera.near_clip:
                continue
            color = QColor.fromRgbF(*particle.color) if particle.emitter_id else QColor(colors.get(particle.material, QColor(220, 225, 235, 220)))
            if particle.frozen:
                color = QColor(170, 235, 255, 235)
            elif particle.state == "molten":
                color = QColor(255, 105, 20, 240)
            elif particle.burn_damage > 0.0:
                color = QColor(255, max(30, int(170 * (1.0 - particle.burn_damage))), 20, 235)
            radius = max(1.0, min(16.0, float(particle.radius) * max(0.1, particle.size) * 900.0 / max(0.2, depth)))
            painter.setPen(QPen(color.lighter(130), 1))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(sx - radius, sy - radius, radius * 2.0, radius * 2.0))
        for volume_name, volume in (getattr(world, "volumes", {}) or {}).items():
            plasma = "plasma" in str(volume_name).lower()
            for key, cell in list(volume.cells.items())[:8000]:
                point = tuple(float(value) * volume.voxel_size for value in key)
                sx, sy, depth = project(point)
                if depth <= camera.near_clip:
                    continue
                alpha = max(20, min(220, int((cell.density + cell.flame + cell.emission * 0.15) * 130)))
                color = QColor(60, 210, 255, alpha) if plasma else QColor(255, 95 + int(80 * cell.flame), 20, alpha)
                radius = max(3.0, min(12.0, volume.voxel_size * 1100.0 / max(0.2, depth)))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QRectF(sx - radius, sy - radius, radius * 2.0, radius * 2.0))
        for surface in list(getattr(world, "deformable_surfaces", []) or []):
            for mark in surface.marks[-2000:]:
                sx, sy, depth = project(mark.position)
                if depth <= camera.near_clip:
                    continue
                radius = max(3.0, min(80.0, mark.radius * 850.0 / max(0.2, depth)))
                color = QColor(15, 20, 28, 190) if mark.penetrated else QColor(70, 105, 135, 135)
                painter.setPen(QPen(color.lighter(150), 1))
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QRectF(sx - radius, sy - radius * 0.45, radius * 2.0, radius * 0.9))
        painter.restore()

    def _draw_viewport_hud(self, painter: QPainter, w: int, h: int) -> None:
        selected = getattr(self.owner, "_selected_scene_proxy", None)
        providers = ", ".join(getattr(self.owner, "_loaded_scene_providers", []) or ["local"])
        mode = getattr(self.owner, "viewport_mode", "Paint")
        shading = getattr(self.owner, "viewport_shading_mode", "Highlight")
        if str(getattr(self.owner, "viewport_display_source", "compiled") or "compiled").lower() == "dcc":
            wire = "wire9:on" if getattr(self.owner, "show_dcc_context_wire", True) else "wire9:off"
            shading = f"DCC:{getattr(self.owner, 'active_dcc_view_provider', '') or 'viewport'} {wire}"
        frame = int(getattr(self.owner, "_current_dcc_frame", 1) or 1)
        selected_name = "none"
        selected_provider = ""
        if isinstance(selected, (dict, SceneProxyInstance)):
            selected_name = str(selected.get("name") or selected.get("native_id") or "object")[:42]
            selected_provider = str(selected.get("provider_id") or "")
        orientation = str(getattr(self.owner, "transform_orientation_mode", "world") or "world").title()
        active_axis = str(getattr(self.owner, "active_transform_axis", "") or "free").upper()
        transform_suffix = f"  |  {orientation} {active_axis}" if mode in {"Translate", "Rotate", "Scale"} else ""
        self._draw_pill(painter, 16, 14, f"{mode} / {shading}{transform_suffix}  |  frame {frame}  |  {providers}", QColor(8, 15, 22, 215), QColor(145, 215, 235))
        if selected_name != "none":
            color = provider_view_colors(selected_provider)[1]
            self._draw_pill(painter, 16, 46, f"Selected: {selected_provider}:{selected_name}", QColor(8, 15, 22, 215), color)
        counts = f"{len(getattr(self.owner.mesh, 'vertices', []) or [])} verts / {len(getattr(self.owner.mesh, 'faces', []) or [])} tris"
        paint_ms = float(getattr(self.owner, "_last_viewport_paint_ms", 0.0) or 0.0)
        total_ms = float(getattr(self.owner, "_last_frame_total_ms", 0.0) or 0.0)
        if paint_ms > 0.0:
            counts += f"  |  draw {paint_ms:.0f} ms"
        if total_ms > 0.0:
            counts += f"  |  frame {total_ms:.0f} ms"
        self._draw_pill(painter, 16, h - 44, counts, QColor(8, 15, 22, 190), QColor(170, 195, 205))
        self._draw_perspective_guides(painter, w, h)
        self._draw_world_coord_handles(painter, w, h)

    def _draw_perspective_guides(self, painter: QPainter, w: int, h: int) -> None:
        if not getattr(self.owner, "shot_guides_enabled", False):
            return
        mode = str(getattr(self.owner, "shot_guide_mode", "Off") or "Off")
        if mode == "Off":
            return
        points = self.owner.shot_guide_points_for_view(float(w), float(h))
        active = self.owner.active_shot_guide_names()
        if not active:
            return

        colors = {
            "VP1": QColor(30, 155, 255, 190),
            "VP2": QColor(240, 140, 30, 190),
            "VP3": QColor(200, 60, 255, 190),
            "VP4": QColor(30, 220, 120, 190),
            "VP5": QColor(255, 40, 120, 210),
            "VP6": QColor(255, 210, 40, 190),
        }

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        density = 12

        def draw_ray_fan(name: str) -> None:
            point = points.get(name)
            if point is None:
                return
            color = QColor(colors.get(name, QColor(125, 210, 235)))
            color.setAlpha(115)
            painter.setPen(QPen(color, 1, Qt.DashLine))
            for index in range(max(6, density)):
                angle = (math.pi * 2.0 / float(max(6, density))) * index
                end = QPointF(point.x() + math.cos(angle) * 6000.0, point.y() + math.sin(angle) * 6000.0)
                painter.drawLine(point, end)

        if mode.startswith("1-Point"):
            draw_ray_fan("VP1")
        elif mode.startswith(("2-Point", "3-Point")):
            vp1 = points.get("VP1")
            vp2 = points.get("VP2")
            if vp1 and vp2:
                painter.setPen(QPen(QColor(22, 242, 106, 210), 2, Qt.SolidLine))
                painter.drawLine(vp1, vp2)
            draw_ray_fan("VP1")
            draw_ray_fan("VP2")
            if mode.startswith("3-Point"):
                draw_ray_fan("VP3")
        else:
            center = points.get("VP5") or QPointF(w * 0.5, h * 0.5)
            vp_names = ["VP1", "VP2", "VP3", "VP4"]
            painter.setPen(QPen(QColor(22, 242, 106, 145), 1, Qt.DashLine))
            for name in vp_names:
                if name in points:
                    painter.drawLine(center, points[name])
            rx = max(1.0, (abs(center.x() - points.get("VP1", center).x()) + abs(points.get("VP2", center).x() - center.x())) * 0.5)
            ry = max(1.0, (abs(center.y() - points.get("VP3", center).y()) + abs(points.get("VP4", center).y() - center.y())) * 0.5)
            painter.setPen(QPen(QColor(255, 40, 120, 125), 1.5, Qt.DotLine))
            painter.drawEllipse(center, rx, ry)
            for index in range(12):
                angle = math.pi * index / 12.0
                p1 = QPointF(center.x() - math.cos(angle) * rx, center.y() - math.sin(angle) * ry)
                p2 = QPointF(center.x() + math.cos(angle) * rx, center.y() + math.sin(angle) * ry)
                painter.drawLine(p1, p2)
            if mode.startswith("6-Point") and "VP6" in points:
                painter.setPen(QPen(QColor(255, 210, 40, 185), 1.5, Qt.SolidLine))
                painter.drawLine(center, points["VP6"])

        painter.setFont(QFont("Arial", 8, QFont.Bold))
        for name in active:
            point = points.get(name)
            if point is None:
                continue
            color = colors.get(name, QColor(220, 240, 245))
            painter.setPen(QPen(QColor(0, 0, 0, 210), 4))
            painter.drawEllipse(point, 8, 8)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(5, 11, 18, 185)))
            painter.drawEllipse(point, 8, 8)
            painter.setPen(QPen(color, 1))
            painter.drawText(QRectF(point.x() + 11, point.y() - 10, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, name)

        solved = getattr(self.owner, "last_shot_guide_solution", None)
        if isinstance(solved, dict) and solved.get("projection_model"):
            camera = solved.get("camera_settings") or {}
            text = f"{solved.get('projection_model')}  FOV {float(camera.get('fov_degrees', 0.0)):.1f}  conf {float(solved.get('confidence', 0.0)):.0%}"
            self._draw_pill(painter, 16, 78, text, QColor(8, 15, 22, 210), QColor(255, 210, 40))
        painter.restore()

    def _draw_world_coord_handles(self, painter: QPainter, w: int, h: int) -> None:
        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        _forward, cam_right, cam_up = camera.view_axes()
        origin = QPointF(float(w) - 76.0, float(h) - 76.0)
        axis_len = 42.0
        axes = [
            ("X", (1.0, 0.0, 0.0), QColor(240, 78, 78)),
            ("Y", (0.0, 1.0, 0.0), QColor(95, 225, 120)),
            ("Z", (0.0, 0.0, 1.0), QColor(88, 145, 255)),
        ]
        projected = []
        for label, axis, color in axes:
            sx = _vec_dot(axis, cam_right)
            sy = -_vec_dot(axis, cam_up)
            depth = _vec_dot(axis, _vec_sub(camera.target, camera.eye))
            projected.append((depth, label, sx, sy, color))
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(2, 8, 12, 220), 1))
        painter.setBrush(QBrush(QColor(5, 12, 18, 185)))
        painter.drawEllipse(QRectF(origin.x() - 48, origin.y() - 48, 96, 96))
        for _depth, label, sx, sy, color in sorted(projected, key=lambda item: item[0]):
            end = QPointF(origin.x() + sx * axis_len, origin.y() + sy * axis_len)
            painter.setPen(QPen(QColor(0, 0, 0, 190), 4))
            painter.drawLine(origin, end)
            painter.setPen(QPen(color, 2))
            painter.drawLine(origin, end)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QRectF(end.x() - 4, end.y() - 4, 8, 8))
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.setPen(QPen(QColor(2, 6, 9, 230), 3))
            painter.drawText(int(end.x() + 7), int(end.y() + 4), label)
            painter.setPen(QPen(color, 1))
            painter.drawText(int(end.x() + 7), int(end.y() + 4), label)
        painter.setBrush(QBrush(QColor(225, 235, 240)))
        painter.setPen(QPen(QColor(2, 8, 12, 220), 1))
        painter.drawEllipse(QRectF(origin.x() - 3, origin.y() - 3, 6, 6))

    def _draw_pill(self, painter: QPainter, x: int, y: int, text: str, fill: QColor, pen: QColor) -> None:
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        metrics = painter.fontMetrics()
        width = min(max(130, metrics.horizontalAdvance(text) + 22), max(160, self.width() - 32))
        rect = QRectF(x, y, width, 24)
        painter.setPen(QPen(pen, 1))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QPen(pen, 1))
        painter.drawText(QRectF(x + 10, y + 2, width - 18, 20), Qt.AlignVCenter | Qt.AlignLeft, text)


    def keyPressEvent(self, event):
        key = event.key()
        mode = str(getattr(self.owner, "viewport_mode", "Selection") or "Selection")
        if key == Qt.Key_Escape:
            if mode in {"Vertex", "Edge", "Face"}:
                self.owner.clear_mesh_component_selection()
                self.update()
                return
        if key == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
            if mode in {"Vertex", "Edge", "Face"}:
                if event.modifiers() & Qt.ShiftModifier:
                    self.owner.clear_mesh_component_selection()
                else:
                    self.owner.select_all_mesh_components(mode)
                self.update()
                return
        if event.matches(QKeySequence.Undo):
            if hasattr(self.owner, "undo_viewer_action"):
                self.owner.undo_viewer_action()
            return
        if event.matches(QKeySequence.Redo):
            if hasattr(self.owner, "redo_viewer_action"):
                self.owner.redo_viewer_action()
            return
        if key == Qt.Key_M and (event.modifiers() & Qt.ControlModifier) and (event.modifiers() & Qt.ShiftModifier):
            if hasattr(self.owner, "clear_all_syncsketch_markups"):
                self.owner.clear_all_syncsketch_markups()
            return
        if key == Qt.Key_M and (event.modifiers() & Qt.ControlModifier):
            if hasattr(self.owner, "toggle_syncsketch_markup_mode"):
                self.owner.toggle_syncsketch_markup_mode()
            return
        if key == Qt.Key_B:
            self.owner.is_b_key_held = True
            self.is_b_key_held = True
            self.b_center_pos = getattr(self.owner, 'current_mouse_pos', None)
            self.b_initial_radius = float(self.owner.brush_size)
            self.setCursor(Qt.SizeHorCursor)
            self.update()
        elif key == Qt.Key_Q:
            # Maya Q Key = Selection Mode
            if hasattr(self.owner, "set_viewport_interaction_mode"):
                self.owner.set_viewport_interaction_mode("Selection")
            else:
                self.owner.viewport_mode = "Selection"
                self.setCursor(Qt.ArrowCursor)
            self.update()
        elif key == Qt.Key_W:
            # Maya W Key = Translate Mode
            if hasattr(self.owner, "set_viewport_interaction_mode"):
                self.owner.set_viewport_interaction_mode("Translate")
            else:
                self.owner.viewport_mode = "Translate"
                self.setCursor(Qt.ArrowCursor)
            self.update()
        elif key == Qt.Key_E:
            # Maya E Key = Rotate Mode
            if hasattr(self.owner, "set_viewport_interaction_mode"):
                self.owner.set_viewport_interaction_mode("Rotate")
            else:
                self.owner.viewport_mode = "Rotate"
                self.setCursor(Qt.ArrowCursor)
            self.update()
        elif key == Qt.Key_R or key == Qt.Key_S:
            # Maya R/S Key = Scale Mode
            if hasattr(self.owner, "set_viewport_interaction_mode"):
                self.owner.set_viewport_interaction_mode("Scale")
            else:
                self.owner.viewport_mode = "Scale"
                self.setCursor(Qt.ArrowCursor)
            self.update()
        elif key == Qt.Key_P:
            # Maya P Key = Paint Mode
            if hasattr(self.owner, "set_viewport_interaction_mode"):
                self.owner.set_viewport_interaction_mode("Paint")
            else:
                self.owner.viewport_mode = "Paint"
                self.setCursor(Qt.CrossCursor)
            self.update()
        elif key == Qt.Key_F8:
            self.owner.set_viewport_interaction_mode("Vertex")
            self.update()
        elif key == Qt.Key_F9:
            self.owner.set_viewport_interaction_mode("Edge")
            self.update()
        elif key == Qt.Key_F10:
            self.owner.set_viewport_interaction_mode("Face")
            self.update()
        elif key == Qt.Key_F8:
            self.owner.set_viewport_interaction_mode("Vertex")
            self.update()
        elif key == Qt.Key_F9:
            self.owner.set_viewport_interaction_mode("Edge")
            self.update()
        elif key == Qt.Key_F10:
            self.owner.set_viewport_interaction_mode("Face")
            self.update()
        elif key == Qt.Key_1:
            if hasattr(self.owner, "set_dcc_viewport_display"):
                self.owner.set_dcc_viewport_display("maya")
            self.update()
        elif key == Qt.Key_2:
            if hasattr(self.owner, "set_dcc_viewport_display"):
                self.owner.set_dcc_viewport_display("unreal")
            self.update()
        elif key == Qt.Key_3:
            if hasattr(self.owner, "set_dcc_viewport_display"):
                self.owner.set_dcc_viewport_display("blender")
            self.update()
        elif key == Qt.Key_4:
            if hasattr(self.owner, "set_viewport_display_preset"):
                self.owner.set_viewport_display_preset("wire")
            self.update()
        elif key == Qt.Key_5:
            if hasattr(self.owner, "set_viewport_display_preset"):
                self.owner.set_viewport_display_preset("solid")
            self.update()
        elif key == Qt.Key_6:
            if hasattr(self.owner, "set_viewport_display_preset"):
                self.owner.set_viewport_display_preset("shader")
            self.update()
        elif key == Qt.Key_9:
            if hasattr(self.owner, "toggle_dcc_context_wire"):
                self.owner.toggle_dcc_context_wire()
            self.update()
        elif key in (Qt.Key_F, Qt.Key_A):
            if key == Qt.Key_F and hasattr(self.owner, "focus_selected_scene_element"):
                self.owner.focus_selected_scene_element()
            elif hasattr(self.owner, "frame_mesh_camera"):
                self.owner.frame_mesh_camera()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_B:
            self.owner.is_b_key_held = False
            self.is_b_key_held = False
            if hasattr(self.owner, "refresh_viewport_cursor"):
                self.owner.refresh_viewport_cursor()
            else:
                self.setCursor(Qt.CrossCursor)
            self.update()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        self.owner.last_mouse_pos = event.position()
        mods = event.modifiers()
        btn = event.button()

        if (
            btn == Qt.LeftButton
            and not (mods & Qt.AltModifier)
            and getattr(self.owner, "_fx_manipulator_emitter_id", "")
            and self.owner.begin_fx_emitter_drag(event.position())
        ):
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return

        if btn == Qt.LeftButton:
            joint_handle = self.owner.hit_test_physics_joint_handle(
                event.position(), float(self.width()), float(self.height())
            )
            if joint_handle:
                self.owner.begin_physics_joint_handle_drag(joint_handle, event.position())
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
                return

        if getattr(self.owner, 'is_b_key_held', False):
            # Holding B disables surface painting and enters pure brush radius resizing
            self.owner.is_resizing_brush = True
            self.owner.is_painting = False
            self.setCursor(Qt.SizeHorCursor)
            return

        if btn == Qt.LeftButton and getattr(self.owner, "shot_guides_enabled", False):
            hit = self.owner.hit_test_shot_guide_handle(event.position(), float(self.width()), float(self.height()))
            if hit:
                self.owner._active_shot_guide_handle = hit
                if hasattr(self.owner, "refresh_viewport_cursor"):
                    self.owner.refresh_viewport_cursor()
                else:
                    self.setCursor(Qt.SizeAllCursor)
                self.update()
                return

        if btn == Qt.LeftButton and (mods & Qt.AltModifier):
            # Maya Orbit (Alt + Left Click Drag)
            self.owner.is_orbiting = True
            self.setCursor(Qt.ClosedHandCursor)
        elif btn == Qt.MiddleButton and (mods & Qt.AltModifier):
            # Maya Track (Alt + Middle Mouse Drag)
            self.owner.is_panning = True
            self.setCursor(Qt.SizeAllCursor)
        elif btn == Qt.RightButton and (mods & Qt.AltModifier):
            # Maya Zoom (Alt + Right Click Drag)
            self.owner.is_zooming = True
            self.owner._suppress_next_context_menu = True
            self.setCursor(Qt.SizeVerCursor)
        elif btn == Qt.LeftButton:
            mode = getattr(self.owner, "viewport_mode", "")
            if mode in {"Vertex", "Edge", "Face"}:
                self.owner._component_marquee_start = QPointF(event.position())
                self.owner._component_marquee_current = QPointF(event.position())
                self.owner._component_marquee_mode = mode
                self.owner._component_marquee_modifiers = mods
                self.owner._component_marquee_dragging = False
                self.owner.select_mesh_component_at_viewport_position(event.position(), mode, mods)
                self.update()
                return
            if mode == "Paint" and getattr(self.owner, "syncsketch_markup_enabled", False):
                if mods & Qt.ControlModifier:
                    self.owner.begin_syncsketch_markup_erase(event.position())
                else:
                    self.owner.begin_syncsketch_markup_stroke(event.position())
                self.setCursor(Qt.CrossCursor)
                self.update()
                return
            active_provider = str(getattr(self.owner, "active_dcc_view_provider", "") or "").lower()
            if (
                str(getattr(self.owner, "viewport_display_source", "compiled") or "compiled").lower() == "dcc"
                and active_provider
            ):
                def active_control(proxy: SceneProxyInstance | dict[str, Any]) -> bool:
                    proxy_provider = str(proxy.get("provider_id") or "").lower()
                    provider_matches = (
                        proxy_provider == active_provider
                        or (
                            ":" not in active_provider
                            and dcc_provider_base_key(proxy_provider) == dcc_provider_base_key(active_provider)
                        )
                    )
                    return provider_matches and not scene_proxy_draws_filled_surface(proxy)

                proxy = self.owner.proxy_at_viewport_position(
                    event.position(),
                    max_distance_px=28.0,
                    candidate_filter=active_control,
                )
                if proxy:
                    self.owner._selected_scene_proxy = proxy
                    self.owner.update_instance_details_panel()
                    self.owner.update_viewport_status()
                    QTimer.singleShot(0, self.owner.select_selected_proxy_in_source)
                    self.update()
                    return
            if mode in {"Translate", "Rotate", "Scale"}:
                axis = self.owner.hit_test_transform_gizmo_axis(event.position())
                if axis:
                    self.owner.push_viewer_undo_state(f"{mode} {axis}")
                    self.owner.active_transform_axis = axis
                    self.owner.hover_transform_axis = axis
                    self.owner.is_transform_dragging = True
                    self.owner._transform_drag_start_pos = event.position()
                    self.owner._transform_drag_last_pos = event.position()
                    if hasattr(self.owner, "refresh_viewport_cursor"):
                        self.owner.refresh_viewport_cursor()
                    else:
                        self.setCursor(Qt.SizeAllCursor)
                    self.update()
                    return
                proxy = self.owner.proxy_at_viewport_position(event.position(), max_distance_px=28.0)
                if proxy:
                    self.owner._selected_scene_proxy = proxy
                    self.owner.active_transform_axis = ""
                    self.owner.hover_transform_axis = ""
                    self.owner.update_instance_details_panel()
                    self.owner.update_viewport_status()
                    QTimer.singleShot(0, self.owner.select_selected_proxy_in_source)
                    if hasattr(self.owner, "refresh_viewport_cursor"):
                        self.owner.refresh_viewport_cursor()
                    else:
                        self.setCursor(Qt.ArrowCursor)
                    self.update()
                    return
                return
            if mode == "Selection":
                proxy = self.owner.proxy_at_viewport_position(event.position(), max_distance_px=28.0)
                if proxy:
                    self.owner._selected_scene_proxy = proxy
                    self.owner.active_transform_axis = ""
                    self.owner.hover_transform_axis = ""
                    self.owner.update_instance_details_panel()
                    self.owner.update_viewport_status()
                    QTimer.singleShot(0, self.owner.select_selected_proxy_in_source)
                else:
                    self.owner._selected_scene_proxy = None
                    self.owner.active_transform_axis = ""
                    self.owner.hover_transform_axis = ""
                    self.owner.update_instance_details_panel()
                    self.owner.update_viewport_status()
                if hasattr(self.owner, "refresh_viewport_cursor"):
                    self.owner.refresh_viewport_cursor()
                else:
                    self.setCursor(Qt.ArrowCursor)
                self.update()
                return
            # Standard 3D Surface Paint
            self.owner.push_viewer_undo_state("Paint stroke")
            self.owner._last_paint_hit = None
            self.owner._last_paint_screen_pos = None
            self.setCursor(Qt.CrossCursor)
            self.owner._paint_at_viewport_position(event.position())
            brush_name = self.owner.medium_combo.currentText() if getattr(self.owner, "medium_combo", None) is not None else ""
            self.owner.is_painting = brush_name != "FillBucket"

    def mouseMoveEvent(self, event):
        self.owner.current_mouse_pos = event.position()

        marquee_start = getattr(self.owner, "_component_marquee_start", None)
        if marquee_start is not None and (event.buttons() & Qt.LeftButton):
            self.owner._component_marquee_current = QPointF(event.position())
            delta = event.position() - marquee_start
            if abs(delta.x()) + abs(delta.y()) >= 5.0:
                self.owner._component_marquee_dragging = True
            self.update()
            return

        if getattr(self.owner, "_fx_emitter_drag", None):
            self.owner.update_fx_emitter_drag(event.position())
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
        elif getattr(self.owner, "_active_physics_joint_handle", None):
            self.owner.update_physics_joint_handle_drag(
                event.position(), float(self.width()), float(self.height())
            )
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
        elif getattr(self.owner, 'is_b_key_held', False) or getattr(self.owner, 'is_resizing_brush', False):
            # Pure Maya B + Left Click Drag brush sizing without painting
            delta_x = event.position().x() - self.owner.last_mouse_pos.x()
            new_size = max(1, min(300, int(self.owner.brush_size + delta_x * 0.5)))
            self.owner.brush_size = new_size
            if hasattr(self.owner, 'size_spin'):
                self.owner.size_spin.setValue(new_size)
            self.owner.last_mouse_pos = event.position()
            self.update()
        elif getattr(self.owner, 'is_panning', False):
            # Maya Pan Track
            delta = event.position() - self.owner.last_mouse_pos
            self.owner.last_mouse_pos = event.position()
            self.owner.viewport_camera.track(delta.x(), delta.y(), float(self.width()), float(self.height()))
            self.owner.schedule_dcc_camera_drive("pan")
            self.update()
        elif getattr(self.owner, 'is_zooming', False):
            # Maya Zoom Dolly
            delta = event.position() - self.owner.last_mouse_pos
            self.owner.last_mouse_pos = event.position()
            self.owner.dolly_camera(delta.y())
            self.owner.schedule_dcc_camera_drive("dolly")
            self.update()
        elif getattr(self.owner, 'is_orbiting', False):
            # Maya Orbit Tumble
            delta = event.position() - self.owner.last_mouse_pos
            self.owner.last_mouse_pos = event.position()
            dx = delta.x()
            dy = delta.y()
            if event.modifiers() & Qt.ShiftModifier:
                if abs(dx) >= abs(dy):
                    dy = 0.0
                else:
                    dx = 0.0
            self.owner.viewport_camera.tumble(dx, dy)
            self.owner.schedule_dcc_camera_drive("orbit")
            self.update()
        elif getattr(self.owner, 'is_transform_dragging', False):
            delta = event.position() - self.owner._transform_drag_last_pos
            self.owner._transform_drag_last_pos = event.position()
            self.owner.preview_selected_proxy_transform_from_screen_delta(delta.x(), delta.y())
            self.update()
        elif getattr(self.owner, "_active_shot_guide_handle", ""):
            self.owner.move_shot_guide_handle(
                str(self.owner._active_shot_guide_handle),
                event.position(),
                float(self.width()),
                float(self.height()),
            )
            self.update()
        elif getattr(self.owner, 'is_painting', False):
            # Surface Paint Stroke
            self.owner._paint_at_viewport_position(event.position())
        elif getattr(self.owner, "is_syncsketch_markup_drawing", False):
            self.owner.extend_syncsketch_markup_stroke(event.position())
            self.update()
        elif getattr(self.owner, "_syncsketch_markup_erase_active", False):
            self.owner.erase_syncsketch_markup_at(event.position())
            self.update()
        else:
            emitter_handle = self.owner.fx_emitter_screen_handle() if getattr(
                self.owner, "_fx_manipulator_emitter_id", ""
            ) else None
            if emitter_handle is not None:
                screen = emitter_handle["screen"]
                if math.hypot(
                    float(event.position().x() - screen.x()), float(event.position().y() - screen.y())
                ) <= 28.0:
                    self.setCursor(Qt.OpenHandCursor)
                    self.update()
                    return
            joint_handle = self.owner.hit_test_physics_joint_handle(
                event.position(), float(self.width()), float(self.height())
            )
            if joint_handle:
                self.setCursor(Qt.OpenHandCursor)
                self.update()
                return
            if getattr(self.owner, "viewport_mode", "") in {"Translate", "Rotate", "Scale"}:
                axis = self.owner.hit_test_transform_gizmo_axis(event.position())
                self.owner.hover_transform_axis = axis
                if hasattr(self.owner, "refresh_viewport_cursor"):
                    self.owner.refresh_viewport_cursor(hover_axis=axis)
                else:
                    self.setCursor(Qt.SizeAllCursor if axis else Qt.ArrowCursor)
            else:
                self.owner.hover_transform_axis = ""
                if hasattr(self.owner, "refresh_viewport_cursor"):
                    self.owner.refresh_viewport_cursor()
                else:
                    self.setCursor(Qt.CrossCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if getattr(self.owner, "_component_marquee_start", None) is not None:
            if getattr(self.owner, "_component_marquee_dragging", False):
                self.owner.select_mesh_components_in_viewport_rectangle(
                    self.owner._component_marquee_start,
                    getattr(self.owner, "_component_marquee_current", event.position()),
                    str(getattr(self.owner, "_component_marquee_mode", "Vertex")),
                    getattr(self.owner, "_component_marquee_modifiers", Qt.NoModifier),
                )
            self.owner._component_marquee_start = None
            self.owner._component_marquee_current = None
            self.owner._component_marquee_dragging = False
            self.update()
        navigated = bool(self.owner.is_orbiting or self.owner.is_panning or self.owner.is_zooming)
        if getattr(self.owner, "_active_physics_joint_handle", None):
            self.owner.end_physics_joint_handle_drag(commit=True)
        if getattr(self.owner, "_fx_emitter_drag", None):
            self.owner.end_fx_emitter_drag()
        self.owner.is_orbiting = False
        self.owner.is_painting = False
        self.owner.is_panning = False
        self.owner.is_zooming = False
        if navigated:
            self.owner.mark_scene_dirty()
        if hasattr(self.owner, "schedule_paint_canvas_update"):
            self.owner.schedule_paint_canvas_update(force=True)
        if getattr(self.owner, "is_transform_dragging", False):
            self.owner.commit_selected_proxy_transform()
        if getattr(self.owner, "is_syncsketch_markup_drawing", False):
            self.owner.end_syncsketch_markup_stroke()
        if getattr(self.owner, "_syncsketch_markup_erase_active", False):
            self.owner.end_syncsketch_markup_erase()
        self.owner._active_shot_guide_handle = ""
        self.owner.is_transform_dragging = False
        self.owner.active_transform_axis = ""
        self.owner.is_resizing_brush = False
        self.owner._last_paint_hit = None
        self.owner._last_paint_screen_pos = None
        if hasattr(self.owner, "refresh_viewport_cursor"):
            self.owner.refresh_viewport_cursor()
        else:
            self.setCursor(Qt.CrossCursor)
        self.owner.schedule_resolved_shaded_refresh("navigation released")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.owner.dolly_camera(-delta / 24.0)
            self.owner.mark_scene_dirty()
            self.owner.schedule_dcc_camera_drive("wheel dolly")
            self.owner.schedule_resolved_shaded_refresh("wheel dolly")
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def contextMenuEvent(self, event):
        """Right-click context menu on 3D mesh face for 1-click transfer to Image Editor."""
        if (event.modifiers() & Qt.AltModifier) or getattr(self.owner, "_suppress_next_context_menu", False):
            self.owner._suppress_next_context_menu = False
            event.ignore()
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background:#080d14; color:#ddffe9; border:1px solid #12324a; } QMenu::item:selected { background:#12324a; color:#16f26a; }")

        action_show_in_editor = menu.addAction("Show Face / UV Island in Image Editor")
        action_paint_face = menu.addAction("Paint Active Color on Selected Face")
        action_inspect_uv = menu.addAction("Inspect Polygon UV Bounds")
        menu.addSeparator()
        action_sync_dcc = menu.addAction("Sync Material Asset to Active DCC")

        pos = event.pos()
        chosen = menu.exec_(self.mapToGlobal(pos))

        if chosen == action_show_in_editor:
            self.owner.show_face_in_image_editor(pos)
        elif chosen == action_paint_face:
            self.owner._paint_at_viewport_position(pos)
        elif chosen == action_inspect_uv:
            u = pos.x() / float(self.width())
            v = pos.y() / float(self.height())
            QMessageBox.information(self, "Polygon UV Inspection", f"Selected 3D Face UV Coordinates: U={u:.4f}, V={v:.4f}")
        elif chosen == action_sync_dcc:
            self.owner.bake_and_sync_textures()
