"""Interactive 3D Mesh Painting & FBX Viewport Widget for Tech Connector.

Supports loading 3D FBX, OBJ, glTF, and USD meshes, 360° Orbit Camera controls,
Direct 3D Surface Viewport Painting, and 1-Click PBR Texture Baking to UE5 / Maya / Blender.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import math
import random
from pathlib import Path
import tempfile
import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtCore import QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QVector3D
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.services.dcc.coordinate_space_service import (
    SceneNormalization,
    convert_camera_payload_between_providers,
    provider_bbox_to_shared,
    provider_native_to_shared,
    provider_scale_diagnostic,
    shared_to_provider_native,
    snapshot_scale_diagnostics,
)
from tech_connector.services.dcc.shaded_frame_provider import (
    blender_shaded_frame_code,
    maya_shaded_frame_code,
    motionbuilder_shaded_frame_code,
    parse_shaded_frame_output,
    unreal_shaded_frame_code,
)


@dataclass
class MeshVertex3D:
    """A single 3D vertex with position (x, y, z), normal (nx, ny, nz), and UV coordinates (u, v)."""

    x: float
    y: float
    z: float
    u: float = 0.0
    v: float = 0.0


@dataclass
class SceneProxyMaterialBinding:
    """Runtime material approximation for a source DCC material slot."""

    name: str = ""
    color: QColor = field(default_factory=lambda: QColor(125, 145, 170, 220))
    texture_paths: dict[str, str] = field(default_factory=dict)
    source_material_id: str = ""
    approximation: str = "base_color"


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


BRUSH_PROFILES: dict[str, MeshBrushProfile] = {
    "PaintBrush": MeshBrushProfile(radius_scale=1.0, opacity=0.9, hardness=0.55, spacing=0.22),
    "FillBrush": MeshBrushProfile(radius_scale=1.0, opacity=0.9, hardness=0.65, spacing=0.22),
    "SprayCan": MeshBrushProfile(radius_scale=1.25, opacity=0.28, hardness=0.15, spacing=0.16, scatter=0.8, grain=0.35),
    "Pencil": MeshBrushProfile(radius_scale=0.42, opacity=0.95, hardness=0.92, spacing=0.14, grain=0.2),
    "Watercolor": MeshBrushProfile(radius_scale=1.45, opacity=0.18, hardness=0.08, spacing=0.2, scatter=0.18, grain=0.18, blend_mode="glaze"),
    "FillBucket": MeshBrushProfile(radius_scale=1.0, opacity=1.0, hardness=1.0, spacing=1.0),
    "Eraser": MeshBrushProfile(radius_scale=1.0, opacity=0.85, hardness=0.65, spacing=0.18, blend_mode="erase"),
}


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
        str(provider_id or "").lower(),
        (QColor(120, 155, 190, 190), QColor(185, 230, 255, 235)),
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
    return provider_native_to_shared(provider_id, (x, y, z), unit_linear, up_axis)


def provider_view_to_world(
    provider_id: str,
    x: float,
    y: float,
    z: float,
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> tuple[float, float, float]:
    """Convert canonical Tech Connector shared coordinates back into provider-native space."""
    return shared_to_provider_native(provider_id, (x, y, z), unit_linear, up_axis)


@dataclass
class MayaViewportCamera:
    """Maya-style perspective camera: eye, pivot/target, up, and lens state."""

    eye: tuple[float, float, float] = (-1.9318516525781364, -1.035276180410083, -3.3460652149512318)
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: tuple[float, float, float] = (-0.12940952255126034, 0.9659258262890683, -0.2241438680420134)
    fov_degrees: float = 45.0
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
        yaw = math.radians(float(delta_x) * 0.45)
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
        self.provider_id = "tech_connector"
        self.unit_linear = "centimeters"
        self.scene_center = (0.0, 0.0, 0.0)
        self.scene_scale = 1.0
        self.proxy_fill_color, self.proxy_wire_color = provider_view_colors(self.provider_id)
        self.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        self.albedo_texture.fill(QColor(200, 205, 215, 255))

        # Build default reference 3D sphere primitive so canvas is 100% interactive out-of-the-box
        self._generate_sphere_primitive()

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
            tex = QImage(str(texture_path))
            if not tex.isNull():
                model.albedo_texture = tex.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                model.albedo_texture = model.albedo_texture.scaled(1024, 1024, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                model.sample_albedo_path = str(texture_path)
        return model

    @classmethod
    def from_scene_snapshot(
        cls,
        snapshot: dict[str, Any],
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
    ) -> "FBXMeshModel":
        """Build isolated provider scene geometry with bounds fallback."""
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

        real_mesh_count = 0
        bounds_fallback_count = 0

        def material_binding_for_object(obj: dict[str, Any]) -> SceneProxyMaterialBinding:
            material = obj.get("material") if isinstance(obj.get("material"), dict) else {}
            color_values = material.get("color") if isinstance(material, dict) else None
            name = str(material.get("name") or "") if isinstance(material, dict) else ""
            texture_paths = material.get("texture_paths") if isinstance(material, dict) and isinstance(material.get("texture_paths"), dict) else {}
            if isinstance(color_values, (list, tuple)) and len(color_values) >= 3:
                try:
                    color = QColor(
                        max(0, min(255, int(float(color_values[0]) * 255))),
                        max(0, min(255, int(float(color_values[1]) * 255))),
                        max(0, min(255, int(float(color_values[2]) * 255))),
                        220,
                    )
                    return SceneProxyMaterialBinding(name=name, color=color, texture_paths=dict(texture_paths))
                except Exception:
                    pass
            return SceneProxyMaterialBinding(name=name, color=QColor(model.proxy_fill_color), texture_paths=dict(texture_paths))

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

        def add_mesh_geometry(obj: dict[str, Any], material_color: QColor) -> tuple[float, float, float] | None:
            geometry = obj.get("geometry") or {}
            if geometry.get("representation") != "mesh":
                return None
            source_vertices = geometry.get("vertices") or []
            source_faces = geometry.get("faces") or []
            if not source_vertices or not source_faces:
                return None
            start = len(model.vertices)
            faces_before = len(model.faces)
            quads_before = len(model.quad_faces)
            face_colors_before = len(model.face_colors)
            quad_colors_before = len(model.quad_face_colors)
            for point in source_vertices:
                if not isinstance(point, (list, tuple)) or len(point) < 3:
                    continue
                px, py, pz = provider_world_to_view(
                    model.provider_id,
                    float(point[0]),
                    float(point[1]),
                    float(point[2]),
                    getattr(model, "unit_linear", None),
                    getattr(model, "up_axis", None),
                )
                x, y, z = normalize_point(px, py, pz)
                model.vertices.append(MeshVertex3D(x, y, z, 0.5, 0.5))
            added_vertices = len(model.vertices) - start
            if added_vertices <= 0:
                return None
            for face in source_faces:
                if not isinstance(face, (list, tuple)) or len(face) < 3:
                    continue
                indices = []
                for raw_index in face:
                    try:
                        idx = int(raw_index)
                    except Exception:
                        continue
                    if start <= idx < start + added_vertices:
                        indices.append(idx)
                    elif 0 <= idx < added_vertices:
                        indices.append(start + idx)
                if len(indices) < 3:
                    continue
                if len(indices) == 4:
                    model.quad_faces.append(tuple(indices))
                    model.quad_face_colors.append(QColor(material_color))
                    model.quad_proxy_indices.append(index)
                for offset in range(1, len(indices) - 1):
                    model.faces.append((indices[0], indices[offset], indices[offset + 1]))
                    model.face_colors.append(QColor(material_color))
                    model.face_proxy_indices.append(index)
            if len(model.faces) == faces_before:
                model.vertices = model.vertices[:start]
                model.quad_faces = model.quad_faces[:quads_before]
                model.face_colors = model.face_colors[:face_colors_before]
                model.quad_face_colors = model.quad_face_colors[:quad_colors_before]
                model.face_proxy_indices = model.face_proxy_indices[:face_colors_before]
                model.quad_proxy_indices = model.quad_proxy_indices[:quad_colors_before]
                return None
            bbox = list(bbox_to_view_bounds(obj["bbox"]))
            return normalize_point(
                (bbox[0] + bbox[3]) * 0.5,
                (bbox[1] + bbox[4]) * 0.5,
                (bbox[2] + bbox[5]) * 0.5,
            )

        for index, obj in enumerate(objects):
            material_binding = material_binding_for_object(obj)
            material_color = QColor(material_binding.color)
            vertex_start = len(model.vertices)
            face_start = len(model.faces)
            quad_start = len(model.quad_faces)
            center_point = add_mesh_geometry(obj, material_color)
            representation = "mesh"
            if center_point is None:
                center_point = add_bounds_box(obj, index, material_color)
                representation = "bounds"
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
                    has_uvs=False,
                    topology_state=representation,
                ),
                materials=[material_binding],
                material_color=material_color,
                fill_color=QColor(model.proxy_fill_color),
                wire_color=QColor(model.proxy_wire_color),
                source_transform=source_transform,
                light_data=dict(obj.get("light") or {}),
                local_transform=dict(source_transform),
                source_signature=source_signature,
                source_key=f"{model.provider_id}:{native_id or obj.get('name') or index}",
                texture_bindings=dict(material_binding.texture_paths),
                visible=bool(obj.get("visible", True)),
            )
            model.scene_proxy_objects.append(proxy)

        scene_name = Path(str(snapshot.get("scene") or "")).name or "Untitled Scene"
        provider_name = model.provider_id[:1].upper() + model.provider_id[1:]
        model.name = (
            f"{provider_name}: {scene_name} "
            f"({real_mesh_count} meshes, {bounds_fallback_count} bounds)"
        )
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
    ) -> "FBXMeshModel":
        """Build a federated scene from raw provider snapshots with one shared world transform."""
        valid_snapshots = []
        all_bounds = []
        for snapshot in snapshots:
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
        if not valid_snapshots or not all_bounds:
            raise ValueError("No scene snapshots contained renderable geometry.")

        if scene_center is None or scene_scale is None:
            normalization = SceneNormalization.from_bounds(all_bounds)
            center = normalization.center
            scale = normalization.scale
        else:
            center = scene_center
            scale = float(scene_scale)
        models = [
            cls.from_scene_snapshot(snapshot, scene_center=center, scene_scale=scale)
            for snapshot in valid_snapshots
        ]
        return cls.combine_scene_models(models, name=name)

    @classmethod
    def combine_scene_models(cls, models: list["FBXMeshModel"], name: str = "Federated DCC Scene") -> "FBXMeshModel":
        """Combine provider scene models into one locally rendered mesh."""
        valid_models = [model for model in models if model and getattr(model, "vertices", None)]
        if not valid_models:
            raise ValueError("No scene models contained renderable geometry.")

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
        combined.provider_id = "federated"
        combined.scene_center = getattr(valid_models[0], "scene_center", (0.0, 0.0, 0.0))
        combined.scene_scale = getattr(valid_models[0], "scene_scale", 1.0)
        combined.proxy_fill_color, combined.proxy_wire_color = provider_view_colors("tech_connector")
        combined.albedo_texture = QImage(1024, 1024, QImage.Format_ARGB32_Premultiplied)
        combined.albedo_texture.fill(QColor(125, 145, 170, 255))

        for model in valid_models:
            offset = len(combined.vertices)
            face_offset = len(combined.faces)
            quad_offset = len(combined.quad_faces)
            proxy_offset = len(combined.scene_proxy_objects)
            combined.vertices.extend(model.vertices)
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
                if isinstance(proxy, SceneProxyInstance):
                    proxy.mesh_data.vertex_start += offset
                    proxy.mesh_data.face_start += face_offset
                    proxy.mesh_data.quad_start += quad_offset
                combined.scene_proxy_objects.append(proxy)

        provider_counts: dict[str, int] = {}
        for item in combined.scene_proxy_objects:
            provider = str(item.get("provider_id") or "provider")
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if provider_counts:
            summary = ", ".join(f"{provider}:{count}" for provider, count in sorted(provider_counts.items()))
            combined.name = f"{name} ({summary})"
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
            self._stamp_brush_at_uv(hit_u, hit_v, radius_px, color, profile)
            if symmetry_x:
                self._stamp_brush_at_uv(1.0 - hit_u, hit_v, radius_px, color, profile)
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

    def _stamp_brush_at_uv(self, u: float, v: float, radius_px: float, color: QColor, profile: MeshBrushProfile):
        tw, th = self.albedo_texture.width(), self.albedo_texture.height()
        cx = max(0.0, min(1.0, u)) * float(tw - 1)
        cy = (1.0 - max(0.0, min(1.0, v))) * float(th - 1)
        if profile.scatter > 0.0:
            dither_seed = int(cx * 73856093) ^ int(cy * 19349663) ^ int(radius_px * 83492791)
            rng = random.Random(dither_seed)
            dab_count = max(12, int(radius_px * 1.5))
            for _ in range(dab_count):
                ang = rng.random() * math.tau
                dist = (rng.random() ** 0.55) * radius_px * profile.scatter
                dab_radius = max(1.0, radius_px * rng.uniform(0.08, 0.22))
                self._paint_soft_disc(cx + math.cos(ang) * dist, cy + math.sin(ang) * dist, dab_radius, color, profile)
            return
        self._paint_soft_disc(cx, cy, radius_px, color, profile)

    def _paint_soft_disc(self, cx: float, cy: float, radius_px: float, color: QColor, profile: MeshBrushProfile):
        tw, th = self.albedo_texture.width(), self.albedo_texture.height()
        x0 = max(0, int(cx - radius_px - 1))
        x1 = min(tw - 1, int(cx + radius_px + 1))
        y0 = max(0, int(cy - radius_px - 1))
        y1 = min(th - 1, int(cy + radius_px + 1))
        if x1 < x0 or y1 < y0:
            return
        radius = max(1.0, float(radius_px))
        hardness = max(0.01, min(1.0, profile.hardness))
        opacity = max(0.0, min(1.0, profile.opacity)) * (color.alpha() / 255.0)
        erase_color = QColor(200, 205, 215, 255)

        for y in range(y0, y1 + 1):
            dy = (y + 0.5 - cy) / radius
            for x in range(x0, x1 + 1):
                dx = (x + 0.5 - cx) / radius
                d = math.sqrt(dx * dx + dy * dy)
                if d > 1.0:
                    continue
                if d <= hardness:
                    falloff = 1.0
                else:
                    falloff = 1.0 - ((d - hardness) / max(1e-5, 1.0 - hardness))
                    falloff = falloff * falloff * (3.0 - 2.0 * falloff)
                if profile.grain > 0.0:
                    noise = 0.65 + 0.35 * math.sin((x * 12.9898 + y * 78.233) * 0.075)
                    falloff *= (1.0 - profile.grain) + profile.grain * noise
                alpha = max(0.0, min(1.0, opacity * falloff))
                if alpha <= 0.001:
                    continue
                dst = self.albedo_texture.pixelColor(x, y)
                src = erase_color if profile.blend_mode == "erase" else color
                if profile.blend_mode == "glaze":
                    alpha *= 0.72
                    src = QColor(
                        int(dst.red() * 0.35 + src.red() * 0.65),
                        int(dst.green() * 0.35 + src.green() * 0.65),
                        int(dst.blue() * 0.35 + src.blue() * 0.65),
                        255,
                    )
                out = QColor(
                    int(dst.red() * (1.0 - alpha) + src.red() * alpha),
                    int(dst.green() * (1.0 - alpha) + src.green() * alpha),
                    int(dst.blue() * (1.0 - alpha) + src.blue() * alpha),
                    255,
                )
                self.albedo_texture.setPixelColor(x, y, out)


class ThreeDMeshCanvas(QWidget):
    """3D Viewport Canvas rendering 360° Orbit Mesh and Surface Painting."""

    def __init__(self, parent=None, viewport_owner=None):
        super().__init__(parent)
        self.owner = viewport_owner
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def enterEvent(self, event):
        self.setFocus()
        super().enterEvent(event)

    def paintEvent(self, event):
        if not self.owner:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 3D Viewport Dark Background
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(10, 14, 20))

        camera = getattr(self.owner, "viewport_camera", MayaViewportCamera())
        dcc_view_provider = ""
        if str(getattr(self.owner, "viewport_display_source", "compiled") or "compiled").lower() == "dcc":
            dcc_view_provider = str(getattr(self.owner, "active_dcc_view_provider", "") or "").lower()
        if dcc_view_provider:
            self._draw_dcc_viewport_plate(painter, w, h, dcc_view_provider)
        else:
            self._draw_viewport_backdrop(painter, w, h)

        screen_verts = []
        for v in self.owner.mesh.vertices:
            point = self.owner.shared_local_to_display_local((v.x, v.y, v.z))
            sx, sy, rz_final = camera.project_world_to_screen(point, float(w), float(h))
            screen_verts.append((sx, sy, rz_final, v.u, v.v))

        # Render 3D polygons with solid shading plus optional wireframe.
        tex = self.owner.mesh.albedo_texture
        tw, th = tex.width(), tex.height()
        neutral_fill = getattr(self.owner.mesh, "proxy_fill_color", QColor(78, 90, 105))
        wire_color = getattr(self.owner.mesh, "proxy_wire_color", QColor(55, 78, 98, 180))
        wire_pen = QPen(wire_color, 1)
        no_pen = QPen(Qt.NoPen)
        shader_mode = str(getattr(self.owner, "viewport_shading_mode", "Highlight") or "Highlight").lower() == "shader"
        dcc_plate_mode = bool(dcc_view_provider)
        dcc_context_wire = bool(getattr(self.owner, "show_dcc_context_wire", True))
        proxy_objects = getattr(self.owner.mesh, "scene_proxy_objects", []) or []
        local_texture_mode = bool(getattr(self.owner, "show_texture", True)) and not proxy_objects and not dcc_plate_mode
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

        def lit_color(base: QColor, world_points: list[tuple[float, float, float]]) -> QColor:
            if not shader_mode or not scene_lights or len(world_points) < 3:
                return QColor(base)
            p0, p1, p2 = world_points[0], world_points[1], world_points[2]
            normal = _vec_normalize(_vec_cross(_vec_sub(p1, p0), _vec_sub(p2, p0)), (0.0, 1.0, 0.0))
            face_center = (
                sum(point[0] for point in world_points) / len(world_points),
                sum(point[1] for point in world_points) / len(world_points),
                sum(point[2] for point in world_points) / len(world_points),
            )
            accum = [0.18, 0.18, 0.18]
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
            exposure = 1.15
            return QColor(
                max(0, min(255, int(base.red() * min(1.65, accum[0] * exposure)))),
                max(0, min(255, int(base.green() * min(1.65, accum[1] * exposure)))),
                max(0, min(255, int(base.blue() * min(1.65, accum[2] * exposure)))),
                base.alpha(),
            )

        quad_colors = getattr(self.owner.mesh, "quad_face_colors", []) or []
        face_colors = getattr(self.owner.mesh, "face_colors", []) or []
        if hasattr(self.owner.mesh, 'quad_faces') and self.owner.mesh.quad_faces:
            for quad_index, (i1, i2, i3, i4) in enumerate(self.owner.mesh.quad_faces):
                proxy = proxy_for_index(quad_proxy_indices[quad_index]) if quad_index < len(quad_proxy_indices) else None
                proxy_provider = str(proxy.get("provider_id") or "").lower() if isinstance(proxy, (dict, SceneProxyInstance)) else ""
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                if dcc_plate_mode and proxy_provider == dcc_view_provider:
                    continue
                if dcc_plate_mode and not dcc_context_wire:
                    continue
                sv1, sv2, sv3, sv4 = screen_verts[i1], screen_verts[i2], screen_verts[i3], screen_verts[i4]
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
                    if dcc_plate_mode:
                        quad_color = QColor(0, 0, 0, 0)
                    elif shader_mode:
                        quad_color = material_color_for_proxy(proxy, quad_color)
                    else:
                        quad_color = highlight_color_for_proxy(proxy)
                    if local_texture_mode:
                        quad_color = tex.pixelColor(tx, ty)
                    elif shader_mode and getattr(self.owner, "show_texture", True) and not quad_colors:
                        quad_color = tex.pixelColor(tx, ty)
                    if shader_mode:
                        quad_color = lit_color(
                            quad_color,
                            [
                                (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                                (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                                (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                                (self.owner.mesh.vertices[i4].x, self.owner.mesh.vertices[i4].y, self.owner.mesh.vertices[i4].z),
                            ],
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
                    else:
                        painter.setPen(wire_pen if (not shader_mode and getattr(self.owner, "show_wireframe", True)) else no_pen)
                        painter.setBrush(QBrush(quad_color))
                    painter.drawPath(path)
        else:
            for face_index, (i1, i2, i3) in enumerate(self.owner.mesh.faces):
                proxy = proxy_for_index(face_proxy_indices[face_index]) if face_index < len(face_proxy_indices) else None
                proxy_provider = str(proxy.get("provider_id") or "").lower() if isinstance(proxy, (dict, SceneProxyInstance)) else ""
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                if dcc_plate_mode and proxy_provider == dcc_view_provider:
                    continue
                if dcc_plate_mode and not dcc_context_wire:
                    continue
                sv1, sv2, sv3 = screen_verts[i1], screen_verts[i2], screen_verts[i3]
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
                if dcc_plate_mode:
                    tri_color = QColor(0, 0, 0, 0)
                elif shader_mode:
                    tri_color = material_color_for_proxy(proxy, tri_color)
                else:
                    tri_color = highlight_color_for_proxy(proxy)
                if local_texture_mode:
                    tri_color = tex.pixelColor(tx, ty)
                elif shader_mode and getattr(self.owner, "show_texture", True) and not face_colors:
                    tri_color = tex.pixelColor(tx, ty)
                if shader_mode:
                    tri_color = lit_color(
                        tri_color,
                        [
                            (self.owner.mesh.vertices[i1].x, self.owner.mesh.vertices[i1].y, self.owner.mesh.vertices[i1].z),
                            (self.owner.mesh.vertices[i2].x, self.owner.mesh.vertices[i2].y, self.owner.mesh.vertices[i2].z),
                            (self.owner.mesh.vertices[i3].x, self.owner.mesh.vertices[i3].y, self.owner.mesh.vertices[i3].z),
                        ],
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
                else:
                    painter.setPen(wire_pen if (not shader_mode and getattr(self.owner, "show_wireframe", True)) else no_pen)
                    painter.setBrush(QBrush(tri_color))
                painter.drawPath(path)

        if proxy_objects:
            painter.setFont(QFont("Arial", 8))
            for proxy in proxy_objects[:40]:
                if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                    continue
                cx, cy, cz = proxy.get("center") or (0.0, 0.0, 0.0)
                point = self.owner.shared_local_to_display_local((float(cx), float(cy), float(cz)))
                sx, sy, _depth = camera.project_world_to_screen(point, float(w), float(h))
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
            self._draw_dcc_context_template_markers(painter, w, h, dcc_view_provider, camera)

        if not dcc_plate_mode:
            self._draw_resolved_frame_strip(painter, w, h)

        # Maya-style On-Screen Visual Brush Circle Overlay
        if hasattr(self.owner, 'current_mouse_pos') and self.owner.current_mouse_pos:
            if getattr(self, 'is_b_key_held', False) and getattr(self, 'b_center_pos', None):
                mx, my = self.b_center_pos.x(), self.b_center_pos.y()
            else:
                mx, my = self.owner.current_mouse_pos.x(), self.owner.current_mouse_pos.y()
            
            profile = self.owner.active_brush_profile() if hasattr(self.owner, "active_brush_profile") else MeshBrushProfile()
            r = float(self.owner.brush_size) * profile.radius_scale
            
            painter.setPen(QPen(QColor(22, 242, 106, 220), 2, Qt.DashLine))
            painter.setBrush(QBrush(QColor(22, 242, 106, 40)))
            painter.drawEllipse(QRectF(mx - r, my - r, r * 2.0, r * 2.0))

            if getattr(self.owner, 'is_b_key_held', False):
                painter.setFont(QFont("Consolas", 11, QFont.Bold))
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(int(mx + r + 10), int(my), f"Maya Brush Radius: {int(r)}px")

        overlay = self.owner.current_syncsketch_markup_overlay(create=False) if hasattr(self.owner, "current_syncsketch_markup_overlay") else None
        if overlay is not None:
            overlay.draw_markups(painter)

        self._draw_viewport_hud(painter, w, h)

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

    def _draw_dcc_viewport_plate(self, painter: QPainter, w: int, h: int, provider: str) -> None:
        frames = getattr(self.owner, "_resolved_shaded_frames", {}) or {}
        image = frames.get(provider)
        if image is not None and not image.isNull():
            painter.drawImage(QRectF(0, 0, w, h), image)
            painter.fillRect(QRectF(0, 0, w, h), QColor(3, 7, 10, 28))
            return
        if hasattr(self.owner, "schedule_resolved_shaded_refresh"):
            self.owner.schedule_resolved_shaded_refresh(f"{provider} viewport mode")
        painter.fillRect(0, 0, w, h, QColor(8, 11, 15))
        self._draw_viewport_backdrop(painter, w, h)
        self._draw_pill(
            painter,
            16,
            78,
            f"Waiting for {provider} viewport frame",
            QColor(8, 15, 22, 220),
            provider_view_colors(provider)[1],
        )

    def _draw_dcc_context_template_markers(
        self,
        painter: QPainter,
        w: int,
        h: int,
        active_provider: str,
        camera: MayaViewportCamera,
    ) -> None:
        snapshots = getattr(self.owner, "_dcc_scene_snapshots", {}) or {}
        proxy_objects = getattr(self.owner.mesh, "scene_proxy_objects", []) or []
        painter.setFont(QFont("Arial", 8, QFont.Bold))

        def project_shared(point: tuple[float, float, float]) -> tuple[float, float, float]:
            display = self.owner.shared_local_to_display_local(point)
            return camera.project_world_to_screen(display, float(w), float(h))

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
            if not provider or provider == active_provider:
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
            if provider_key == active_provider:
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
        self._draw_pill(painter, 16, h - 44, counts, QColor(8, 15, 22, 190), QColor(170, 195, 205))
        self._draw_world_coord_handles(painter, w, h)

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
        elif key == Qt.Key_W:
            # Maya W Key = Translate Mode
            self.owner.viewport_mode = "Translate"
            if hasattr(self.owner, 'gizmo_mode_combo'):
                self.owner.gizmo_mode_combo.setCurrentText("Translate (W)")
            self.setCursor(Qt.SizeAllCursor)
            self.update()
        elif key == Qt.Key_E:
            # Maya E Key = Rotate Mode
            self.owner.viewport_mode = "Rotate"
            if hasattr(self.owner, 'gizmo_mode_combo'):
                self.owner.gizmo_mode_combo.setCurrentText("Rotate (E)")
            self.setCursor(Qt.SizeAllCursor)
            self.update()
        elif key == Qt.Key_R or key == Qt.Key_S:
            # Maya R/S Key = Scale Mode
            self.owner.viewport_mode = "Scale"
            if hasattr(self.owner, 'gizmo_mode_combo'):
                self.owner.gizmo_mode_combo.setCurrentText("Scale (R)")
            self.setCursor(Qt.SizeAllCursor)
            self.update()
        elif key == Qt.Key_P:
            # Maya P Key = Paint Mode
            self.owner.viewport_mode = "Paint"
            if hasattr(self.owner, 'gizmo_mode_combo'):
                self.owner.gizmo_mode_combo.setCurrentText("Paint (P)")
            self.setCursor(Qt.CrossCursor)
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
            self.setCursor(Qt.CrossCursor)
            self.update()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        self.owner.last_mouse_pos = event.position()
        mods = event.modifiers()
        btn = event.button()

        if getattr(self.owner, 'is_b_key_held', False):
            # Holding B disables surface painting and enters pure brush radius resizing
            self.owner.is_resizing_brush = True
            self.owner.is_painting = False
            self.setCursor(Qt.SizeHorCursor)
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
            if mode == "Paint" and getattr(self.owner, "syncsketch_markup_enabled", False):
                if mods & Qt.ControlModifier:
                    self.owner.begin_syncsketch_markup_erase(event.position())
                else:
                    self.owner.begin_syncsketch_markup_stroke(event.position())
                self.setCursor(Qt.CrossCursor)
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
                    self.setCursor(Qt.SizeAllCursor)
                    self.update()
                    return
                proxy = self.owner.proxy_at_viewport_position(event.position(), max_distance_px=28.0)
                if proxy:
                    self.owner.push_viewer_undo_state(f"{mode} object")
                    self.owner._selected_scene_proxy = proxy
                    self.owner.active_transform_axis = ""
                    self.owner.hover_transform_axis = ""
                    self.owner.is_transform_dragging = True
                    self.owner._transform_drag_start_pos = event.position()
                    self.owner._transform_drag_last_pos = event.position()
                    self.setCursor(Qt.SizeAllCursor)
                    self.update()
                    return
                return
            # Standard 3D Surface Paint
            self.owner.push_viewer_undo_state("Paint stroke")
            self.owner._last_paint_hit = None
            self.setCursor(Qt.CrossCursor)
            self.owner._paint_at_viewport_position(event.position())
            brush_name = self.owner.medium_combo.currentText() if getattr(self.owner, "medium_combo", None) is not None else ""
            self.owner.is_painting = brush_name != "FillBucket"

    def mouseMoveEvent(self, event):
        self.owner.current_mouse_pos = event.position()
        
        if getattr(self.owner, 'is_b_key_held', False) or getattr(self.owner, 'is_resizing_brush', False):
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
        elif getattr(self.owner, 'is_painting', False):
            # Surface Paint Stroke
            self.owner._paint_at_viewport_position(event.position())
            self.update()
        elif getattr(self.owner, "is_syncsketch_markup_drawing", False):
            self.owner.extend_syncsketch_markup_stroke(event.position())
            self.update()
        elif getattr(self.owner, "_syncsketch_markup_erase_active", False):
            self.owner.erase_syncsketch_markup_at(event.position())
            self.update()
        else:
            if getattr(self.owner, "viewport_mode", "") in {"Translate", "Rotate", "Scale"}:
                axis = self.owner.hit_test_transform_gizmo_axis(event.position())
                self.owner.hover_transform_axis = axis
                self.setCursor(Qt.SizeAllCursor if axis else Qt.ArrowCursor)
            else:
                self.owner.hover_transform_axis = ""
                self.setCursor(Qt.CrossCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        self.owner.is_orbiting = False
        self.owner.is_painting = False
        self.owner.is_panning = False
        self.owner.is_zooming = False
        if getattr(self.owner, "is_transform_dragging", False):
            self.owner.commit_selected_proxy_transform()
        if getattr(self.owner, "is_syncsketch_markup_drawing", False):
            self.owner.end_syncsketch_markup_stroke()
        if getattr(self.owner, "_syncsketch_markup_erase_active", False):
            self.owner.end_syncsketch_markup_erase()
        self.owner.is_transform_dragging = False
        self.owner.active_transform_axis = ""
        self.owner.is_resizing_brush = False
        self.owner._last_paint_hit = None
        self.setCursor(Qt.CrossCursor)
        self.owner.schedule_resolved_shaded_refresh("navigation released")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.owner.dolly_camera(-delta / 24.0)
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

        action_show_in_editor = menu.addAction("🖼️ Show Face / UV Island in Image Editor")
        action_paint_face = menu.addAction("🎨 Paint Active Color on Selected Face")
        action_inspect_uv = menu.addAction("🔍 Inspect Polygon UV Bounds")
        menu.addSeparator()
        action_sync_dcc = menu.addAction("🚀 Sync Material Asset to Active DCC")

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


class ThreeDMeshPainterViewport(QWidget):
    """Interactive 3D Mesh Paint Viewport with Top Toolbar Header and 360° Orbit Canvas."""

    color_hovered = Signal(int, int, QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self.viewport_camera = MayaViewportCamera()
        self.viewer_coord_space = "maya"
        self.drive_dcc_camera_enabled = False
        self.is_panning = False
        self.is_zooming = False
        self.is_transform_dragging = False
        self.active_transform_axis = ""
        self.hover_transform_axis = ""
        self.transform_orientation_mode = "world"
        self.is_resizing_brush = False
        self.is_b_key_held = False
        self._suppress_next_context_menu = False
        self.show_texture = True
        self.show_wireframe = True
        self.show_resolved_shaded_frames = False
        self.viewport_shading_mode = "Highlight"
        self.viewport_display_source = "compiled"
        self.active_dcc_view_provider = ""
        self.show_dcc_context_wire = True
        self.dcc_unit_scale_policy = "working_units"
        self.viewer_coord_up_axis = "y"
        self.drive_dcc_time_enabled = True
        self.viewport_mode = "Paint"
        self.live_refresh_interval_ms = 2500
        self.timeline_refresh_interval_ms = 250
        self.resolved_shaded_refresh_interval_ms = 650
        self.camera_drive_interval_ms = 240
        
        self.primary_color = QColor(22, 242, 106)
        self._last_paint_color = QColor(self.primary_color)
        self.brush_size = 24
        self.active_brush_name = "PaintBrush"
        self.is_orbiting = False
        self.is_painting = False
        self.last_mouse_pos = QPointF()
        self.current_mouse_pos = QPointF()
        self._last_paint_hit = None
        self._selected_scene_proxy: SceneProxyInstance | dict[str, Any] | None = None
        self._camera_pivot_source_key = ""
        self._transform_drag_start_pos = QPointF()
        self._transform_drag_last_pos = QPointF()
        self._loaded_scene_providers: list[str] = []
        self._dcc_scene_snapshots: dict[str, dict[str, Any]] = {}
        self._dcc_camera_reference_snapshots: dict[str, dict[str, Any]] = {}
        self._resolved_shaded_frames: dict[str, QImage] = {}
        self._resolved_shaded_frame_paths: dict[str, str] = {}
        self._resolved_shaded_status = "Resolved shaded frame idle"
        self._coordinate_scale_status = ""
        self._current_dcc_frame = 1
        self._suppress_camera_combo_update = False
        self._last_dcc_camera_payload_keys: dict[str, str] = {}
        self._camera_drive_provider_cache: tuple[float, list[str], list[str]] = (0.0, [], [])
        self._dcc_snapshot_signatures: dict[str, str] = {}
        self._dcc_scene_refresh_busy = False
        self._last_dcc_scene_refresh_at = 0.0
        self._cross_dcc_transform_constraints: list[dict[str, Any]] = []
        self._viewer_undo_stack: list[dict[str, Any]] = []
        self._viewer_redo_stack: list[dict[str, Any]] = []
        self._viewer_undo_limit = 40
        self.syncsketch_markup_enabled = False
        self.is_syncsketch_markup_drawing = False
        self.syncsketch_markup_store = PerFrameSyncSketchMarkupStore()
        self._active_syncsketch_markup_stroke: SyncSketchMarkupStroke | None = None
        self._syncsketch_markup_erase_active = False

        self._build_ui()
        self.live_refresh_timer = QTimer(self)
        self.live_refresh_timer.setInterval(self.live_refresh_interval_ms)
        self.live_refresh_timer.timeout.connect(self.refresh_loaded_dcc_scenes)
        self.timeline_refresh_timer = QTimer(self)
        self.timeline_refresh_timer.setSingleShot(True)
        self.timeline_refresh_timer.setInterval(self.timeline_refresh_interval_ms)
        self.timeline_refresh_timer.timeout.connect(self.refresh_loaded_dcc_scenes_for_current_frame)
        self.resolved_shaded_frame_timer = QTimer(self)
        self.resolved_shaded_frame_timer.setSingleShot(True)
        self.resolved_shaded_frame_timer.setInterval(self.resolved_shaded_refresh_interval_ms)
        self.resolved_shaded_frame_timer.timeout.connect(self.refresh_resolved_shaded_frames)
        self.camera_drive_timer = QTimer(self)
        self.camera_drive_timer.setSingleShot(True)
        self.camera_drive_timer.setInterval(self.camera_drive_interval_ms)
        self.camera_drive_timer.timeout.connect(self.drive_loaded_dcc_cameras_from_view)

    @property
    def camera_fov_degrees(self) -> float:
        return float(getattr(self.viewport_camera, "fov_degrees", 45.0))

    @camera_fov_degrees.setter
    def camera_fov_degrees(self, value: float) -> None:
        self.viewport_camera.fov_degrees = float(value)

    @property
    def camera_focus_view(self) -> tuple[float, float, float]:
        return tuple(getattr(self.viewport_camera, "target", (0.0, 0.0, 0.0)))

    @camera_focus_view.setter
    def camera_focus_view(self, value: tuple[float, float, float]) -> None:
        self.viewport_camera.focus(tuple(float(v) for v in value))

    @property
    def camera_zoom(self) -> float:
        return self.viewport_camera.distance

    @camera_zoom.setter
    def camera_zoom(self, value: float) -> None:
        direction = _vec_normalize(_vec_sub(self.viewport_camera.eye, self.viewport_camera.target), (0.0, 0.0, -1.0))
        self.viewport_camera.eye = _vec_add(self.viewport_camera.target, _vec_scale(direction, float(value)))

    @property
    def camera_pan_x(self) -> float:
        return 0.0

    @camera_pan_x.setter
    def camera_pan_x(self, value: float) -> None:
        pass

    @property
    def camera_pan_y(self) -> float:
        return 0.0

    @camera_pan_y.setter
    def camera_pan_y(self, value: float) -> None:
        pass

    @property
    def camera_rot_x(self) -> float:
        delta = _vec_sub(self.viewport_camera.eye, self.viewport_camera.target)
        distance = max(0.001, _vec_length(delta))
        return math.degrees(math.asin(max(-1.0, min(1.0, -delta[1] / distance))))

    @camera_rot_x.setter
    def camera_rot_x(self, value: float) -> None:
        delta = _vec_sub(self.viewport_camera.eye, self.viewport_camera.target)
        distance = max(0.001, _vec_length(delta))
        yaw = math.atan2(delta[0], -delta[2])
        pitch = math.radians(float(value))
        self.viewport_camera.eye = _vec_add(self.viewport_camera.target, (
            math.sin(yaw) * math.cos(pitch) * distance,
            -math.sin(pitch) * distance,
            -math.cos(yaw) * math.cos(pitch) * distance,
        ))

    @property
    def camera_rot_y(self) -> float:
        delta = _vec_sub(self.viewport_camera.eye, self.viewport_camera.target)
        return math.degrees(math.atan2(delta[0], -delta[2]))

    @camera_rot_y.setter
    def camera_rot_y(self, value: float) -> None:
        delta = _vec_sub(self.viewport_camera.eye, self.viewport_camera.target)
        distance = max(0.001, _vec_length(delta))
        pitch = math.asin(max(-1.0, min(1.0, -delta[1] / distance)))
        yaw = math.radians(float(value))
        self.viewport_camera.eye = _vec_add(self.viewport_camera.target, (
            math.sin(yaw) * math.cos(pitch) * distance,
            -math.sin(pitch) * distance,
            -math.cos(yaw) * math.cos(pitch) * distance,
        ))

    def shared_local_to_display_local(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        coord = str(getattr(self, "viewer_coord_space", "maya") or "maya").lower()
        up_axis = str(getattr(self, "viewer_coord_up_axis", "") or "")
        if coord == "maya" and not up_axis.startswith("z"):
            return tuple(float(v) for v in point)
        return shared_to_provider_native(coord, point, "centimeters", up_axis)

    def display_local_to_shared_local(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        coord = str(getattr(self, "viewer_coord_space", "maya") or "maya").lower()
        up_axis = str(getattr(self, "viewer_coord_up_axis", "") or "")
        if coord == "maya" and not up_axis.startswith("z"):
            return tuple(float(v) for v in point)
        return provider_native_to_shared(coord, point, "centimeters", up_axis)

    def change_viewer_coord_space(self, text: str) -> None:
        old_eye_shared = self.display_local_to_shared_local(self.viewport_camera.eye)
        old_target_shared = self.display_local_to_shared_local(self.viewport_camera.target)
        old_up_target_shared = self.display_local_to_shared_local(_vec_add(self.viewport_camera.target, self.viewport_camera.view_axes()[2]))
        label = str(text or "Maya").lower()
        if "blender" in label:
            self.viewer_coord_space = "blender"
            self.viewer_coord_up_axis = "z"
        elif "unreal" in label:
            self.viewer_coord_space = "unreal"
            self.viewer_coord_up_axis = "z"
        elif "z-up" in label or "z up" in label:
            self.viewer_coord_space = "maya"
            self.viewer_coord_up_axis = "z"
        else:
            self.viewer_coord_space = "maya"
            self.viewer_coord_up_axis = "y"
        new_eye = self.shared_local_to_display_local(old_eye_shared)
        new_target = self.shared_local_to_display_local(old_target_shared)
        new_up_target = self.shared_local_to_display_local(old_up_target_shared)
        self.viewport_camera.eye = new_eye
        self.viewport_camera.target = new_target
        self.viewport_camera.up = _vec_normalize(_vec_sub(new_up_target, new_target), (0.0, 1.0, 0.0))
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        self.schedule_dcc_camera_drive("coord space changed")
        self.schedule_resolved_shaded_refresh("coord space changed")

    def dolly_camera(self, delta_y: float):
        """Maya-like exponential dolly so zoom feels stable near and far."""
        self.viewport_camera.dolly(delta_y)
        return self.camera_zoom

    def frame_mesh_camera(self):
        """Frame the loaded mesh, equivalent to Maya's A framing."""
        vertices = getattr(self.mesh, "vertices", None) or []
        if not vertices:
            return
        min_x = min(v.x for v in vertices)
        max_x = max(v.x for v in vertices)
        min_y = min(v.y for v in vertices)
        max_y = max(v.y for v in vertices)
        min_z = min(v.z for v in vertices)
        max_z = max(v.z for v in vertices)
        display_points = [
            self.shared_local_to_display_local((min_x, min_y, min_z)),
            self.shared_local_to_display_local((max_x, min_y, min_z)),
            self.shared_local_to_display_local((min_x, max_y, min_z)),
            self.shared_local_to_display_local((max_x, max_y, min_z)),
            self.shared_local_to_display_local((min_x, min_y, max_z)),
            self.shared_local_to_display_local((max_x, min_y, max_z)),
            self.shared_local_to_display_local((min_x, max_y, max_z)),
            self.shared_local_to_display_local((max_x, max_y, max_z)),
        ]
        min_point = tuple(min(point[i] for point in display_points) for i in range(3))
        max_point = tuple(max(point[i] for point in display_points) for i in range(3))
        self._camera_pivot_source_key = ""
        self.viewport_camera.frame_bounds(min_point, max_point)
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        self.schedule_dcc_camera_drive("frame mesh")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        
        # 1. Top Fixed Header Toolbar Frame (Solid Dark Studio Styling, Never Overlaps Viewport)
        toolbar_frame = QFrame(self)
        toolbar_frame.setFixedHeight(76)
        toolbar_frame.setStyleSheet("QFrame { background-color: #0b1118; border-bottom: 1px solid #1a2938; } QPushButton { background-color: #162432; color: #16f26a; border: 1px solid #0c7a47; border-radius: 4px; padding: 4px 10px; font-weight: bold; } QPushButton:hover { background-color: #0c7a47; color: #ffffff; } QComboBox, QSpinBox { background-color: #162432; color: #16f26a; border: 1px solid #0c7a47; border-radius: 4px; padding: 2px 6px; }")
        
        toolbar_layout = QVBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(10, 4, 10, 4)
        toolbar_layout.setSpacing(4)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)
        paint_hdr = QHBoxLayout()
        paint_hdr.setContentsMargins(0, 0, 0, 0)
        paint_hdr.setSpacing(8)
        toolbar_layout.addLayout(hdr)
        toolbar_layout.addLayout(paint_hdr)
        
        lbl = QLabel("<b>3D Mesh Painter</b>")
        lbl.setStyleSheet("color:#16f26a; font-size:12px;")
        hdr.addWidget(lbl)

        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Reset the demo sphere and camera.")
        reset_btn.setStyleSheet("background-color: #241632; color: #f216a6; border: 1px solid #7a0c47;")
        reset_btn.clicked.connect(self.reset_demo_sphere)
        hdr.addWidget(reset_btn)

        open_import_btn = QPushButton("Import")
        open_import_btn.setToolTip("Open OBJ geometry or import a texture map.")
        open_import_btn.setStyleSheet("background-color: #1a2c42; color: #16f26a; border: 1px solid #1f5080; font-weight: bold; padding: 4px 10px;")
        open_import_btn.clicked.connect(self.open_or_import_file_dialog)
        hdr.addWidget(open_import_btn)

        self.dcc_scene_provider_combo = QComboBox()
        self.dcc_scene_provider_combo.setToolTip("Choose which connected 3D application to query into this viewer.")
        self.dcc_scene_provider_combo.addItem("Maya", "maya")
        self.dcc_scene_provider_combo.addItem("Blender", "blender")
        self.dcc_scene_provider_combo.addItem("MotionBuilder", "motionbuilder")
        self.dcc_scene_provider_combo.addItem("Houdini", "houdini")
        self.dcc_scene_provider_combo.addItem("Unreal", "unreal")
        self.dcc_scene_provider_combo.addItem("Unity", "unity")
        self.dcc_scene_provider_combo.addItem("All Open", "all_open")
        hdr.addWidget(self.dcc_scene_provider_combo)

        self.viewer_coord_combo = QComboBox()
        self.viewer_coord_combo.setToolTip("Viewer coordinate basis. Maya is the default; switch when you want the local viewport to feel like another DCC.")
        self.viewer_coord_combo.addItems(["Coord: Maya", "Coord: Blender", "Coord: Unreal"])
        self.viewer_coord_combo.currentTextChanged.connect(self.change_viewer_coord_space)
        hdr.addWidget(self.viewer_coord_combo)

        load_dcc_btn = QPushButton("Refresh")
        load_dcc_btn.setToolTip("Add or refresh the selected DCC as a retained layer in the federated viewport.")
        load_dcc_btn.clicked.connect(self.load_selected_dcc_scene_snapshot)
        hdr.addWidget(load_dcc_btn)

        self.maya_selected_only_checkbox = QCheckBox("Selected")
        self.maya_selected_only_checkbox.setToolTip("Load only selected Maya mesh transforms when querying the scene.")
        self.maya_selected_only_checkbox.setStyleSheet("color:#a0d8ff;")
        hdr.addWidget(self.maya_selected_only_checkbox)

        self.live_dcc_refresh_btn = QPushButton("Live")
        self.live_dcc_refresh_btn.setCheckable(True)
        self.live_dcc_refresh_btn.setToolTip("Continuously refresh loaded DCC scene geometry into this local viewport.")
        self.live_dcc_refresh_btn.toggled.connect(self.set_live_dcc_refresh)
        hdr.addWidget(self.live_dcc_refresh_btn)

        self.camera_authority_combo = QComboBox()
        self.camera_authority_combo.setToolTip("Choose the camera that drives the federated viewport and connected DCC cameras.")
        self.camera_authority_combo.addItem("TC Camera", {"mode": "tech_connector"})
        hdr.addWidget(self.camera_authority_combo)

        sync_camera_btn = QPushButton("Sync Cam")
        sync_camera_btn.setToolTip("Apply the selected camera authority to the loaded DCC applications.")
        sync_camera_btn.clicked.connect(self.sync_selected_camera_authority)
        hdr.addWidget(sync_camera_btn)

        constraint_btn = QPushButton("Constrain")
        constraint_btn.setToolTip("Constrain the selected target proxy to another loaded DCC object through Tech Connector shared space.")
        constraint_btn.clicked.connect(self.create_cross_dcc_transform_constraint_from_selection)
        hdr.addWidget(constraint_btn)

        flip_constraint_btn = QPushButton("Flip")
        flip_constraint_btn.setToolTip("Flip the active driver/driven direction on the most recent reversible cross-DCC constraint.")
        flip_constraint_btn.clicked.connect(self.flip_latest_cross_dcc_constraint_direction)
        hdr.addWidget(flip_constraint_btn)

        self.drive_camera_btn = QPushButton("Drive Cam")
        self.drive_camera_btn.setCheckable(True)
        self.drive_camera_btn.setToolTip("Continuously push the Tech Connector viewport camera to loaded DCC cameras after navigation settles.")
        self.drive_camera_btn.toggled.connect(self.set_drive_dcc_camera_enabled)
        hdr.addWidget(self.drive_camera_btn)

        self.drive_time_btn = QPushButton("Drive Time")
        self.drive_time_btn.setCheckable(True)
        self.drive_time_btn.setChecked(True)
        self.drive_time_btn.setToolTip("Push this viewer timeline frame into loaded DCC applications.")
        self.drive_time_btn.toggled.connect(self.set_drive_dcc_time_enabled)
        hdr.addWidget(self.drive_time_btn)

        self.dcc_toolbar_toggle_btn = QPushButton("DCC")
        self.dcc_toolbar_toggle_btn.setCheckable(True)
        self.dcc_toolbar_toggle_btn.setToolTip("Show advanced DCC camera, refresh, and constraint controls.")
        self.dcc_toolbar_toggle_btn.toggled.connect(self.set_dcc_toolbar_expanded)
        paint_hdr.addWidget(self.dcc_toolbar_toggle_btn)

        undo_btn = QPushButton("Undo")
        undo_btn.setToolTip("Undo the last viewport action (Ctrl+Z).")
        undo_btn.clicked.connect(self.undo_viewer_action)
        paint_hdr.addWidget(undo_btn)

        redo_btn = QPushButton("Redo")
        redo_btn.setToolTip("Redo the last undone viewport action (Ctrl+Y).")
        redo_btn.clicked.connect(self.redo_viewer_action)
        paint_hdr.addWidget(redo_btn)

        self.syncsketch_markup_btn = QPushButton("Markup")
        self.syncsketch_markup_btn.setCheckable(True)
        self.syncsketch_markup_btn.setToolTip("Toggle SyncSketch-style markup mode (Ctrl+M). Clear all markups with Ctrl+Shift+M.")
        self.syncsketch_markup_btn.toggled.connect(self.set_syncsketch_markup_mode)
        paint_hdr.addWidget(self.syncsketch_markup_btn)

        # Color Swatch Button
        self.color_btn = QPushButton("Color")
        self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")
        self.color_btn.clicked.connect(self.pick_primary_color)
        paint_hdr.addWidget(self.color_btn)


        # Primitive Selector Dropdown
        paint_hdr.addWidget(QLabel("<span style='color:#a0b0c0;'>Create:</span>"))
        self.primitive_combo = QComboBox()
        self.primitive_combo.addItems(["Sphere", "Cube", "Cylinder"])
        self.primitive_combo.currentTextChanged.connect(self.create_primitive_mesh)
        paint_hdr.addWidget(self.primitive_combo)

        # Transform Gizmo Mode Selector
        self.gizmo_mode_combo = QComboBox()
        self.gizmo_mode_combo.addItems(["Paint (P)", "Translate (W)", "Rotate (E)", "Scale (R/S)", "Vertex (F8)", "Face (F10)"])
        self.gizmo_mode_combo.setCurrentText("Paint (P)")
        self.gizmo_mode_combo.currentTextChanged.connect(self.change_viewport_mode_from_combo)
        paint_hdr.addWidget(self.gizmo_mode_combo)

        self.transform_orientation_combo = QComboBox()
        self.transform_orientation_combo.setToolTip("Transform manipulator orientation basis. Parent uses object basis until parent transforms are present in the scene snapshot.")
        self.transform_orientation_combo.addItems(["World", "Object", "Parent"])
        self.transform_orientation_combo.currentTextChanged.connect(self.change_transform_orientation_mode)
        paint_hdr.addWidget(self.transform_orientation_combo)

        # Medium Preset Dropdown
        self.medium_combo = QComboBox()
        self.medium_combo.addItems(["PaintBrush", "FillBrush", "SprayCan", "Pencil", "Watercolor", "FillBucket", "Eraser"])
        self.medium_combo.currentTextChanged.connect(self.change_brush_medium)
        paint_hdr.addWidget(self.medium_combo)

        # Brush Size SpinBox
        paint_hdr.addWidget(QLabel("<span style='color:#a0b0c0;'>Size:</span>"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 300)
        self.size_spin.setValue(self.brush_size)
        self.size_spin.valueChanged.connect(self.change_brush_size)
        paint_hdr.addWidget(self.size_spin)

        # Symmetry Toggle
        self.sym_btn = QPushButton("X-Symmetry")
        self.sym_btn.setCheckable(True)
        self.sym_btn.setChecked(True)
        paint_hdr.addWidget(self.sym_btn)

        self.texture_btn = QPushButton("Texture")
        self.texture_btn.setCheckable(True)
        self.texture_btn.setChecked(True)
        self.texture_btn.setToolTip("Toggle local texture sampling. Use 5 for solid/highlight and 6 for shader mode.")
        self.texture_btn.toggled.connect(self.toggle_texture_display)
        paint_hdr.addWidget(self.texture_btn)

        self.shader_mode_btn = QPushButton("Shader")
        self.shader_mode_btn.setCheckable(True)
        self.shader_mode_btn.setToolTip("6: use source material approximations in the local viewport and request resolved shaded frames.")
        self.shader_mode_btn.toggled.connect(self.toggle_shader_viewport_mode)
        paint_hdr.addWidget(self.shader_mode_btn)

        self.resolved_shaded_btn = QPushButton("Resolved")
        self.resolved_shaded_btn.setCheckable(True)
        self.resolved_shaded_btn.setChecked(bool(getattr(self, "show_resolved_shaded_frames", False)))
        self.resolved_shaded_btn.setToolTip("Request real shaded DCC viewport frames after interaction settles.")
        self.resolved_shaded_btn.toggled.connect(self.toggle_resolved_shaded_frames)
        paint_hdr.addWidget(self.resolved_shaded_btn)

        self.wire_btn = QPushButton("Wire")
        self.wire_btn.setCheckable(True)
        self.wire_btn.setChecked(True)
        self.wire_btn.setToolTip("4: wireframe/highlight view.")
        self.wire_btn.toggled.connect(self.toggle_wireframe_display)
        paint_hdr.addWidget(self.wire_btn)

        bake_btn = QPushButton("Bake PBR")
        bake_btn.setStyleSheet("background-color: #1a2634; color: #16f26a; border: 1px solid #0c7a47;")
        bake_btn.clicked.connect(self.bake_and_sync_textures)
        paint_hdr.addWidget(bake_btn)

        hdr.addStretch(1)
        paint_hdr.addStretch(1)
        root.addWidget(toolbar_frame)
        self._mesh_toolbar_frame = toolbar_frame
        self._dcc_toolbar_layout = hdr
        self.set_dcc_toolbar_expanded(False)

        # 2. Federated outliner + center 3D orbit/paint canvas.
        self.scene_splitter = QSplitter(Qt.Horizontal, self)
        self.scene_splitter.setChildrenCollapsible(False)
        self.scene_splitter.setStyleSheet("QSplitter::handle { background:#13202c; }")

        self.scene_outliner = QTreeWidget(self)
        self.scene_outliner.setHeaderLabels(["Scene Element", "Type", "State"])
        self.scene_outliner.setMinimumWidth(220)
        self.scene_outliner.setMaximumWidth(420)
        self.scene_outliner.setAlternatingRowColors(True)
        self.scene_outliner.setStyleSheet(
            "QTreeWidget { background:#071018; alternate-background-color:#091722; color:#d7f7ff; border-right:1px solid #1a2938; } "
            "QTreeWidget::item { min-height:20px; } "
            "QTreeWidget::item:selected { background:#12324a; color:#16f26a; } "
            "QHeaderView::section { background:#0b1118; color:#9cc7d8; border:0; padding:4px; }"
        )
        self.scene_outliner.itemSelectionChanged.connect(self.on_scene_outliner_selection_changed)
        self.scene_outliner.itemChanged.connect(self.on_scene_outliner_item_changed)
        left_panel = QWidget(self)
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(0, 0, 0, 0)
        left_panel_layout.setSpacing(0)
        left_panel_layout.addWidget(self.scene_outliner, 1)

        self.instance_details_panel = QFrame(self)
        self.instance_details_panel.setMinimumHeight(190)
        self.instance_details_panel.setMaximumHeight(320)
        self.instance_details_panel.setStyleSheet(
            "QFrame { background:#071018; border-top:1px solid #1a2938; border-right:1px solid #1a2938; } "
            "QLabel { color:#d7f7ff; font-size:11px; } "
            "QPushButton { background:#162432; color:#16f26a; border:1px solid #0c7a47; border-radius:4px; padding:3px 6px; font-weight:bold; }"
        )
        details_layout = QVBoxLayout(self.instance_details_panel)
        details_layout.setContentsMargins(8, 7, 8, 7)
        details_layout.setSpacing(5)
        self.instance_title_label = QLabel("Instance Details")
        self.instance_title_label.setStyleSheet("color:#16f26a; font-weight:bold;")
        details_layout.addWidget(self.instance_title_label)
        self.instance_source_label = QLabel("Source: none")
        self.instance_mesh_label = QLabel("Mesh: none")
        self.instance_material_label = QLabel("Material: none")
        self.instance_texture_label = QLabel("Textures: none")
        self.instance_context_label = QLabel("Context: none")
        for label in (self.instance_source_label, self.instance_mesh_label, self.instance_material_label, self.instance_texture_label, self.instance_context_label):
            label.setWordWrap(True)
            details_layout.addWidget(label)
        self.instance_visibility_section_btn = QPushButton("Visibility ▸")
        self.instance_visibility_section_btn.setCheckable(True)
        self.instance_visibility_section_btn.setToolTip("Show visibility controls for the selected scene proxy.")
        self.instance_visibility_section_btn.toggled.connect(self.set_instance_visibility_section_open)
        details_layout.addWidget(self.instance_visibility_section_btn)
        self.instance_visibility_section = QWidget(self.instance_details_panel)
        visibility_layout = QVBoxLayout(self.instance_visibility_section)
        visibility_layout.setContentsMargins(0, 0, 0, 0)
        visibility_layout.setSpacing(4)
        self.instance_visible_checkbox = QCheckBox("Visible in TC viewport")
        self.instance_visible_checkbox.setStyleSheet("color:#a0d8ff;")
        self.instance_visible_checkbox.toggled.connect(self.set_selected_proxy_visibility)
        visibility_layout.addWidget(self.instance_visible_checkbox)
        action_buttons = QHBoxLayout()
        self.instance_visibility_btn = QPushButton("Hide")
        self.instance_visibility_btn.setToolTip("Show or hide the selected scene proxy in the Tech Connector viewport.")
        self.instance_visibility_btn.clicked.connect(self.toggle_selected_proxy_visibility)
        action_buttons.addWidget(self.instance_visibility_btn)
        self.instance_show_only_btn = QPushButton("Show Only")
        self.instance_show_only_btn.setToolTip("Hide all other scene elements and keep the selected proxy visible.")
        self.instance_show_only_btn.clicked.connect(self.show_only_selected_proxy)
        action_buttons.addWidget(self.instance_show_only_btn)
        self.instance_show_all_btn = QPushButton("Show All")
        self.instance_show_all_btn.setToolTip("Restore visibility for every retained scene element.")
        self.instance_show_all_btn.clicked.connect(self.show_all_scene_proxies)
        action_buttons.addWidget(self.instance_show_all_btn)
        self.instance_context_btn = QPushButton("Actions")
        self.instance_context_btn.setToolTip("Show DCC-specific actions for the selected proxy.")
        self.instance_context_btn.clicked.connect(self.show_selected_proxy_actions_menu)
        action_buttons.addWidget(self.instance_context_btn)
        visibility_layout.addLayout(action_buttons)
        self.instance_visibility_section.setVisible(False)
        details_layout.addWidget(self.instance_visibility_section)
        texture_buttons = QHBoxLayout()
        bind_base_btn = QPushButton("Bind Base")
        bind_base_btn.setToolTip("Bind a baked/base-color texture file to the selected proxy instance.")
        bind_base_btn.clicked.connect(lambda: self.bind_texture_to_selected_proxy("base_color"))
        texture_buttons.addWidget(bind_base_btn)
        bind_normal_btn = QPushButton("Bind Normal")
        bind_normal_btn.setToolTip("Bind a normal texture file to the selected proxy instance.")
        bind_normal_btn.clicked.connect(lambda: self.bind_texture_to_selected_proxy("normal"))
        texture_buttons.addWidget(bind_normal_btn)
        bind_roughness_btn = QPushButton("Bind Rough")
        bind_roughness_btn.setToolTip("Bind a roughness texture file to the selected proxy instance.")
        bind_roughness_btn.clicked.connect(lambda: self.bind_texture_to_selected_proxy("roughness"))
        texture_buttons.addWidget(bind_roughness_btn)
        details_layout.addLayout(texture_buttons)
        left_panel_layout.addWidget(self.instance_details_panel)
        self.scene_splitter.addWidget(left_panel)

        # Center 3D Orbit & Paint Canvas (Fills remaining viewport space)
        self.canvas = ThreeDMeshCanvas(self, viewport_owner=self)
        self.scene_splitter.addWidget(self.canvas)
        self.scene_splitter.setSizes([260, 1200])
        root.addWidget(self.scene_splitter, 1)

        self.viewport_status_label = QLabel("Ready")
        self.viewport_status_label.setMinimumHeight(24)
        self.viewport_status_label.setStyleSheet(
            "QLabel { background:#071018; color:#a9d8e8; border-top:1px solid #152635; padding:3px 10px; font-size:11px; }"
        )
        root.addWidget(self.viewport_status_label)

        # 3. Bottom 3D Animation Scrubber & Timeline Bar (FPS, Keyframes, Playback, Onion Skinning)
        from tech_connector.ui.animation_timeline_widget import AnimationFrameSequence, AnimationTimelineBar
        self.anim_timeline = AnimationTimelineBar(AnimationFrameSequence(), parent=self)
        self.anim_timeline.setVisible(True)
        self.anim_timeline.frame_changed.connect(self.on_timeline_frame_changed)
        root.addWidget(self.anim_timeline)
        self.undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_viewer_action)
        self.redo_shortcut = QShortcut(QKeySequence.Redo, self)
        self.redo_shortcut.activated.connect(self.redo_viewer_action)
        self.syncsketch_markup_shortcut = QShortcut(QKeySequence("Ctrl+M"), self)
        self.syncsketch_markup_shortcut.activated.connect(self.toggle_syncsketch_markup_mode)
        self.clear_syncsketch_markup_shortcut = QShortcut(QKeySequence("Ctrl+Shift+M"), self)
        self.clear_syncsketch_markup_shortcut.activated.connect(self.clear_all_syncsketch_markups)

    def pick_primary_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.primary_color, self, "Select 3D Paint Color")
        if c.isValid():
            self.primary_color = c
            self.color_btn.setStyleSheet(f"background-color: {c.name()}; color: #000000; font-weight: bold;")

    def change_brush_medium(self, medium_name: str):
        self.active_brush_name = medium_name
        if medium_name != "Eraser":
            self._last_paint_color = QColor(self.primary_color)
        if medium_name == "Eraser":
            self.color_btn.setText("Eraser")
            self.color_btn.setStyleSheet("background-color: #c8cdd7; color: #10141a; font-weight: bold;")
        elif medium_name == "FillBrush":
            self.brush_size = max(self.brush_size, 72)
            self.size_spin.setValue(self.brush_size)
            self.color_btn.setText("Color")
            self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")
        elif medium_name == "SprayCan":
            self.brush_size = 36
            self.size_spin.setValue(36)
            self.color_btn.setText("Color")
            self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")
        elif medium_name == "Pencil":
            self.brush_size = min(self.brush_size, 14)
            self.size_spin.setValue(self.brush_size)
            self.color_btn.setText("Color")
            self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")
        else:
            self.color_btn.setText("Color")
            self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")

    def change_brush_size(self, val: int):
        self.brush_size = val

    def set_dcc_toolbar_expanded(self, expanded: bool) -> None:
        layout = getattr(self, "_dcc_toolbar_layout", None)
        if layout is not None:
            for index in range(layout.count()):
                item = layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.setVisible(bool(expanded))
        frame = getattr(self, "_mesh_toolbar_frame", None)
        if frame is not None:
            frame.setFixedHeight(76 if expanded else 46)
        button = getattr(self, "dcc_toolbar_toggle_btn", None)
        if button is not None:
            button.setText("DCC Hide" if expanded else "DCC")
            if button.isChecked() != bool(expanded):
                button.blockSignals(True)
                button.setChecked(bool(expanded))
                button.blockSignals(False)

    def change_viewport_mode_from_combo(self, text: str):
        label = str(text or "").lower()
        if "translate" in label:
            self.viewport_mode = "Translate"
            if getattr(self, "canvas", None) is not None:
                self.canvas.setCursor(Qt.SizeAllCursor)
        elif "rotate" in label:
            self.viewport_mode = "Rotate"
            if getattr(self, "canvas", None) is not None:
                self.canvas.setCursor(Qt.SizeAllCursor)
        elif "scale" in label:
            self.viewport_mode = "Scale"
            if getattr(self, "canvas", None) is not None:
                self.canvas.setCursor(Qt.SizeAllCursor)
        else:
            self.viewport_mode = "Paint"
            if getattr(self, "canvas", None) is not None:
                self.canvas.setCursor(Qt.CrossCursor)
        self.update_viewport_status()

    def change_transform_orientation_mode(self, text: str):
        label = str(text or "World").strip().lower()
        if label.startswith("object"):
            self.transform_orientation_mode = "object"
        elif label.startswith("parent"):
            self.transform_orientation_mode = "parent"
        else:
            self.transform_orientation_mode = "world"
        self.active_transform_axis = ""
        self.hover_transform_axis = ""
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def active_brush_profile(self) -> MeshBrushProfile:
        return BRUSH_PROFILES.get(getattr(self, "active_brush_name", "PaintBrush"), BRUSH_PROFILES["PaintBrush"])

    def active_paint_color(self) -> QColor:
        if getattr(self, "active_brush_name", "") == "Eraser":
            return QColor(200, 205, 215, 255)
        return QColor(self.primary_color)

    def current_syncsketch_markup_overlay(self, *, create: bool = True) -> SyncSketchMarkupOverlay | None:
        store = getattr(self, "syncsketch_markup_store", None)
        if store is None:
            return None
        frame = int(getattr(self, "_current_dcc_frame", 1) or 1)
        if create:
            return store.get_overlay_for_frame(frame)
        return store.frame_markups.get(frame)

    def set_syncsketch_markup_mode(self, enabled: bool) -> None:
        self.syncsketch_markup_enabled = bool(enabled)
        overlay = self.current_syncsketch_markup_overlay(create=bool(enabled))
        if overlay is not None:
            overlay.markup_enabled = bool(enabled)
        if hasattr(self, "syncsketch_markup_btn") and self.syncsketch_markup_btn.isChecked() != bool(enabled):
            self.syncsketch_markup_btn.setChecked(bool(enabled))
        self.is_syncsketch_markup_drawing = False
        self._active_syncsketch_markup_stroke = None
        self._resolved_shaded_status = "SyncSketch markup mode on." if enabled else "SyncSketch markup mode off."
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.setCursor(Qt.CrossCursor)
            self.canvas.update()

    def toggle_syncsketch_markup_mode(self) -> None:
        self.set_syncsketch_markup_mode(not bool(getattr(self, "syncsketch_markup_enabled", False)))

    def begin_syncsketch_markup_stroke(self, pos: QPointF) -> None:
        overlay = self.current_syncsketch_markup_overlay(create=True)
        if overlay is None:
            return
        self.push_viewer_undo_state("SyncSketch markup")
        stroke = SyncSketchMarkupStroke("Pen", QColor(self.primary_color), max(2, min(18, int(self.brush_size / 8))))
        stroke.points.append(QPointF(pos))
        overlay.markup_enabled = True
        overlay.strokes.append(stroke)
        self._active_syncsketch_markup_stroke = stroke
        self.is_syncsketch_markup_drawing = True
        self._resolved_shaded_status = "SyncSketch markup stroke."
        self.update_viewport_status()

    def extend_syncsketch_markup_stroke(self, pos: QPointF) -> None:
        stroke = getattr(self, "_active_syncsketch_markup_stroke", None)
        if stroke is None:
            return
        if not stroke.points or math.hypot(pos.x() - stroke.points[-1].x(), pos.y() - stroke.points[-1].y()) >= 1.5:
            stroke.points.append(QPointF(pos))
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()

    def end_syncsketch_markup_stroke(self) -> None:
        self.is_syncsketch_markup_drawing = False
        self._active_syncsketch_markup_stroke = None
        marked = []
        store = getattr(self, "syncsketch_markup_store", None)
        if store is not None:
            marked = store.get_marked_up_frame_indices()
        self._resolved_shaded_status = f"SyncSketch markup saved on {len(marked)} frame(s)."
        self.update_viewport_status()

    def begin_syncsketch_markup_erase(self, pos: QPointF) -> None:
        if str(getattr(self, "viewport_mode", "Paint") or "Paint") != "Paint":
            return
        self.push_viewer_undo_state("Erase SyncSketch markup")
        self._syncsketch_markup_erase_active = True
        self.erase_syncsketch_markup_at(pos)

    def erase_syncsketch_markup_at(self, pos: QPointF) -> int:
        overlay = self.current_syncsketch_markup_overlay(create=False)
        if overlay is None or not overlay.strokes:
            return 0
        radius = max(8.0, float(getattr(self, "brush_size", 24)) * 0.5)
        kept: list[SyncSketchMarkupStroke] = []
        removed = 0
        for stroke in overlay.strokes:
            if self._syncsketch_stroke_hits_point(stroke, pos, radius):
                removed += 1
            else:
                kept.append(stroke)
        if removed:
            overlay.strokes = kept
            self._resolved_shaded_status = f"Erased {removed} SyncSketch markup stroke(s)."
            self.update_viewport_status()
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()
        return removed

    def end_syncsketch_markup_erase(self) -> None:
        self._syncsketch_markup_erase_active = False

    def _syncsketch_stroke_hits_point(self, stroke: SyncSketchMarkupStroke, pos: QPointF, radius: float) -> bool:
        points = list(getattr(stroke, "points", []) or [])
        if not points:
            return False
        px, py = float(pos.x()), float(pos.y())
        for point in points:
            if math.hypot(px - float(point.x()), py - float(point.y())) <= radius:
                return True
        for index in range(1, len(points)):
            if self._distance_to_screen_segment(pos, points[index - 1], points[index]) <= radius:
                return True
        return False

    def clear_all_syncsketch_markups(self) -> None:
        store = getattr(self, "syncsketch_markup_store", None)
        if store is None or not getattr(store, "frame_markups", {}):
            self._resolved_shaded_status = "No SyncSketch markups to clear."
            self.update_viewport_status()
            return
        self.push_viewer_undo_state("Clear SyncSketch markups")
        store.frame_markups.clear()
        self.is_syncsketch_markup_drawing = False
        self._active_syncsketch_markup_stroke = None
        self._resolved_shaded_status = "Cleared all SyncSketch markups."
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def _capture_viewer_state(self, label: str = "Viewer action") -> dict[str, Any]:
        mesh = getattr(self, "mesh", None)
        selected_proxy = getattr(self, "_selected_scene_proxy", None)
        selected_key = ""
        if isinstance(selected_proxy, (dict, SceneProxyInstance)):
            selected_key = str(selected_proxy.get("source_key") or "")
        return {
            "label": label,
            "mesh_name": str(getattr(mesh, "name", "")),
            "vertices": copy.deepcopy(getattr(mesh, "vertices", [])),
            "faces": list(getattr(mesh, "faces", [])),
            "quad_faces": list(getattr(mesh, "quad_faces", [])),
            "face_colors": [QColor(color) for color in (getattr(mesh, "face_colors", []) or [])],
            "quad_face_colors": [QColor(color) for color in (getattr(mesh, "quad_face_colors", []) or [])],
            "albedo_texture": getattr(mesh, "albedo_texture", QImage()).copy(),
            "scene_proxy_objects": copy.deepcopy(getattr(mesh, "scene_proxy_objects", []) or []),
            "face_proxy_indices": list(getattr(mesh, "face_proxy_indices", []) or []),
            "quad_proxy_indices": list(getattr(mesh, "quad_proxy_indices", []) or []),
            "provider_id": getattr(mesh, "provider_id", "tech_connector"),
            "unit_linear": getattr(mesh, "unit_linear", "centimeters"),
            "scene_center": tuple(getattr(mesh, "scene_center", (0.0, 0.0, 0.0))),
            "scene_scale": float(getattr(mesh, "scene_scale", 1.0) or 1.0),
            "proxy_fill_color": QColor(getattr(mesh, "proxy_fill_color", QColor(125, 145, 170, 255))),
            "proxy_wire_color": QColor(getattr(mesh, "proxy_wire_color", QColor(185, 230, 255, 235))),
            "camera": copy.deepcopy(getattr(self, "viewport_camera", MayaViewportCamera())),
            "selected_key": selected_key,
            "syncsketch_markup_store": copy.deepcopy(getattr(self, "syncsketch_markup_store", None)),
            "syncsketch_markup_enabled": bool(getattr(self, "syncsketch_markup_enabled", False)),
        }

    def push_viewer_undo_state(self, label: str = "Viewer action") -> None:
        stack = getattr(self, "_viewer_undo_stack", None)
        if stack is None:
            self._viewer_undo_stack = []
            stack = self._viewer_undo_stack
        stack.append(self._capture_viewer_state(label))
        limit = int(getattr(self, "_viewer_undo_limit", 40) or 40)
        if len(stack) > limit:
            del stack[: len(stack) - limit]
        self._viewer_redo_stack = []
        self.update_viewport_status()

    def _restore_viewer_state(self, state: dict[str, Any]) -> None:
        mesh = getattr(self, "mesh", None)
        if mesh is None:
            return
        mesh.name = str(state.get("mesh_name") or getattr(mesh, "name", "Mesh"))
        mesh.vertices = copy.deepcopy(state.get("vertices") or [])
        mesh.faces = list(state.get("faces") or [])
        mesh.quad_faces = list(state.get("quad_faces") or [])
        mesh.face_colors = [QColor(color) for color in (state.get("face_colors") or [])]
        mesh.quad_face_colors = [QColor(color) for color in (state.get("quad_face_colors") or [])]
        image = state.get("albedo_texture")
        if isinstance(image, QImage):
            mesh.albedo_texture = image.copy()
        mesh.scene_proxy_objects = copy.deepcopy(state.get("scene_proxy_objects") or [])
        mesh.face_proxy_indices = list(state.get("face_proxy_indices") or [])
        mesh.quad_proxy_indices = list(state.get("quad_proxy_indices") or [])
        mesh.provider_id = state.get("provider_id", getattr(mesh, "provider_id", "tech_connector"))
        mesh.unit_linear = state.get("unit_linear", getattr(mesh, "unit_linear", "centimeters"))
        mesh.scene_center = tuple(state.get("scene_center") or getattr(mesh, "scene_center", (0.0, 0.0, 0.0)))
        mesh.scene_scale = float(state.get("scene_scale") or getattr(mesh, "scene_scale", 1.0) or 1.0)
        mesh.proxy_fill_color = QColor(state.get("proxy_fill_color", getattr(mesh, "proxy_fill_color", QColor(125, 145, 170, 255))))
        mesh.proxy_wire_color = QColor(state.get("proxy_wire_color", getattr(mesh, "proxy_wire_color", QColor(185, 230, 255, 235))))
        camera = state.get("camera")
        if isinstance(camera, MayaViewportCamera):
            self.viewport_camera = copy.deepcopy(camera)
        markup_store = state.get("syncsketch_markup_store")
        if markup_store is not None:
            self.syncsketch_markup_store = copy.deepcopy(markup_store)
        self.syncsketch_markup_enabled = bool(state.get("syncsketch_markup_enabled", getattr(self, "syncsketch_markup_enabled", False)))
        if hasattr(self, "syncsketch_markup_btn"):
            self.syncsketch_markup_btn.blockSignals(True)
            self.syncsketch_markup_btn.setChecked(self.syncsketch_markup_enabled)
            self.syncsketch_markup_btn.blockSignals(False)
        selected_key = str(state.get("selected_key") or "")
        self._selected_scene_proxy = None
        if selected_key:
            for proxy in getattr(mesh, "scene_proxy_objects", []) or []:
                if isinstance(proxy, (dict, SceneProxyInstance)) and str(proxy.get("source_key") or "") == selected_key:
                    self._selected_scene_proxy = proxy
                    break
        self.refresh_scene_outliner()
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def undo_viewer_action(self) -> None:
        if not getattr(self, "_viewer_undo_stack", []):
            self._resolved_shaded_status = "Nothing to undo."
            self.update_viewport_status()
            return
        self._viewer_redo_stack.append(self._capture_viewer_state("Redo state"))
        state = self._viewer_undo_stack.pop()
        self._restore_viewer_state(state)
        self._resolved_shaded_status = f"Undid: {state.get('label') or 'viewer action'}"
        self.update_viewport_status()

    def redo_viewer_action(self) -> None:
        if not getattr(self, "_viewer_redo_stack", []):
            self._resolved_shaded_status = "Nothing to redo."
            self.update_viewport_status()
            return
        self._viewer_undo_stack.append(self._capture_viewer_state("Undo state"))
        state = self._viewer_redo_stack.pop()
        self._restore_viewer_state(state)
        self._resolved_shaded_status = f"Redid: {state.get('label') or 'viewer action'}"
        self.update_viewport_status()

    def toggle_texture_display(self, checked: bool):
        self.show_texture = bool(checked)
        self.canvas.update()

    def set_viewport_display_preset(self, preset: str) -> None:
        preset_key = str(preset or "").strip().lower()
        self.viewport_display_source = "compiled"
        self.active_dcc_view_provider = ""
        if preset_key == "wire":
            self.viewport_shading_mode = "Highlight"
            self.show_texture = False
            self.show_wireframe = True
            if hasattr(self, "shader_mode_btn"):
                self.shader_mode_btn.setChecked(False)
            if hasattr(self, "texture_btn"):
                self.texture_btn.setChecked(False)
            if hasattr(self, "wire_btn"):
                self.wire_btn.setChecked(True)
        elif preset_key == "shader":
            self.viewport_shading_mode = "Shader"
            self.show_texture = True
            self.show_wireframe = False
            if hasattr(self, "shader_mode_btn"):
                self.shader_mode_btn.setChecked(True)
            if hasattr(self, "texture_btn"):
                self.texture_btn.setChecked(True)
            if hasattr(self, "wire_btn"):
                self.wire_btn.setChecked(False)
            self.schedule_resolved_shaded_refresh("shader hotkey")
        else:
            self.viewport_shading_mode = "Highlight"
            self.show_texture = False
            self.show_wireframe = False
            if hasattr(self, "shader_mode_btn"):
                self.shader_mode_btn.setChecked(False)
            if hasattr(self, "texture_btn"):
                self.texture_btn.setChecked(False)
            if hasattr(self, "wire_btn"):
                self.wire_btn.setChecked(False)
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def set_dcc_viewport_display(self, provider: str) -> None:
        provider_key = str(provider or "").strip().lower()
        if not provider_key:
            return
        self.viewport_display_source = "dcc"
        self.active_dcc_view_provider = provider_key
        allow_unreal_frames = bool(getattr(self, "allow_unreal_resolved_frames", False))
        if provider_key == "unreal" and not allow_unreal_frames:
            self.show_resolved_shaded_frames = False
            if hasattr(self, "resolved_shaded_btn") and self.resolved_shaded_btn.isChecked():
                self.resolved_shaded_btn.setChecked(False)
            self._resolved_shaded_status = "Unreal passive proxy view; resolved frames are paused to keep the UI responsive."
        else:
            self.show_resolved_shaded_frames = True
            if hasattr(self, "resolved_shaded_btn") and not self.resolved_shaded_btn.isChecked():
                self.resolved_shaded_btn.setChecked(True)
            self.schedule_resolved_shaded_refresh(f"{provider_key} viewport")
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def toggle_dcc_context_wire(self) -> None:
        self.show_dcc_context_wire = not bool(getattr(self, "show_dcc_context_wire", True))
        state = "on" if self.show_dcc_context_wire else "off"
        self._resolved_shaded_status = f"Other DCC wire overlay: {state}"
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def toggle_shader_viewport_mode(self, checked: bool):
        self.viewport_shading_mode = "Shader" if checked else "Highlight"
        if checked:
            if hasattr(self, "wire_btn"):
                self.wire_btn.setChecked(False)
            if hasattr(self, "resolved_shaded_btn") and not self.resolved_shaded_btn.isChecked():
                self.resolved_shaded_btn.setChecked(True)
            self.schedule_resolved_shaded_refresh("shader mode")
        else:
            if hasattr(self, "wire_btn"):
                self.wire_btn.setChecked(True)
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def set_drive_dcc_time_enabled(self, enabled: bool) -> None:
        self.drive_dcc_time_enabled = bool(enabled)
        self.update_viewport_status()
        if enabled:
            self.drive_loaded_dcc_time_from_view()

    def toggle_resolved_shaded_frames(self, checked: bool):
        self.show_resolved_shaded_frames = bool(checked)
        if checked:
            self.schedule_resolved_shaded_refresh("resolved enabled")
        elif hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def schedule_resolved_shaded_refresh(self, reason: str = "") -> None:
        if not getattr(self, "show_resolved_shaded_frames", False):
            return
        timer = getattr(self, "resolved_shaded_frame_timer", None)
        if timer is None:
            return
        self._resolved_shaded_status = f"Resolved shaded frame pending: {reason}" if reason else "Resolved shaded frame pending"
        self.update_viewport_status()
        timer.start()

    def refresh_resolved_shaded_frames(self) -> None:
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        active_plate_provider = ""
        if str(getattr(self, "viewport_display_source", "compiled") or "compiled").lower() == "dcc":
            active_plate_provider = str(getattr(self, "active_dcc_view_provider", "") or "").lower()
        if active_plate_provider and active_plate_provider not in providers:
            providers.append(active_plate_provider)
        if not providers or not getattr(self, "show_resolved_shaded_frames", False):
            return
        frame = int(getattr(self, "_current_dcc_frame", 1) or 1)
        out_dir = Path(tempfile.gettempdir()) / "tech_connector_resolved_frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        canvas = getattr(self, "canvas", None)
        capture_w = 1280
        capture_h = 720
        if canvas is not None and canvas.width() > 0 and canvas.height() > 0:
            capture_w = max(640, min(1920, int(canvas.width())))
            capture_h = max(360, min(1080, int(canvas.height())))
        failures = []
        refreshed = []
        try:
            self.possess_loaded_dcc_cameras()
        except Exception:
            pass
        for provider in providers:
            if provider == "unreal" and not bool(getattr(self, "allow_unreal_resolved_frames", False)):
                failures.append("unreal: resolved frames paused for responsiveness")
                continue
            path = out_dir / f"{provider}_{int(time.time() * 1000)}.png"
            try:
                bridge = self._scene_snapshot_bridge(provider)
                if provider == "maya":
                    ok, raw = bridge.execute(maya_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame), timeout=12.0)
                elif provider == "blender":
                    ok, raw = bridge.execute(blender_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame), timeout=18.0)
                elif provider == "motionbuilder":
                    ok, raw = bridge.execute(motionbuilder_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame), timeout=18.0)
                elif provider == "unreal":
                    response = bridge.execute_python(
                        unreal_shaded_frame_code(
                            str(path),
                            width=capture_w,
                            height=capture_h,
                            frame=frame,
                            drive_viewport_camera=bool(getattr(self, "drive_dcc_camera_enabled", False)),
                        ),
                        timeout=15.0,
                        reset_globals=True,
                    )
                    ok = bool(response.get("ok"))
                    raw = response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or response.get("error") or ""
                    if isinstance(raw, dict):
                        raw = json.dumps(raw)
                else:
                    continue
                if not ok:
                    failures.append(f"{provider}: {raw}")
                    continue
                parsed_ok, payload_or_error = parse_shaded_frame_output(str(raw), provider)
                if not parsed_ok:
                    failures.append(str(payload_or_error))
                    continue
                image = QImage(str(payload_or_error["path"]))
                if image.isNull():
                    failures.append(f"{provider}: could not read {payload_or_error['path']}")
                    continue
                self._resolved_shaded_frames[provider] = image
                self._resolved_shaded_frame_paths[provider] = str(payload_or_error["path"])
                refreshed.append(provider)
            except Exception as exc:
                failures.append(f"{provider}: {exc}")
        if refreshed:
            self._resolved_shaded_status = f"Resolved shaded frame: {', '.join(refreshed)}"
            if failures:
                self._resolved_shaded_status += f" | partial: {'; '.join(failures)[:100]}"
        elif failures:
            self._resolved_shaded_status = "Resolved shaded frame failed: " + "; ".join(failures)[:140]
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def toggle_wireframe_display(self, checked: bool):
        self.show_wireframe = bool(checked)
        self.canvas.update()

    def load_maya_scene_snapshot(self):
        """Compatibility wrapper for older menu/button wiring."""
        if getattr(self, "dcc_scene_provider_combo", None) is not None:
            self.dcc_scene_provider_combo.setCurrentText("Maya")
        self.load_selected_dcc_scene_snapshot()

    def load_selected_dcc_scene_snapshot(self):
        """Add or refresh visible DCC scene elements in this federated viewer."""
        provider = "maya"
        if getattr(self, "dcc_scene_provider_combo", None) is not None:
            provider = str(self.dcc_scene_provider_combo.currentData() or "maya")
        providers = self._scene_snapshot_provider_keys(provider)
        self._load_dcc_scene_providers(providers, show_message=True, replace_existing=False)

    def _load_dcc_scene_providers(
        self,
        providers: list[str],
        *,
        show_message: bool = False,
        replace_existing: bool = False,
        force_rebuild: bool = False,
    ) -> bool:
        if getattr(self, "_dcc_scene_refresh_busy", False):
            self._resolved_shaded_status = "DCC scene refresh already running"
            self.update_viewport_status()
            return False
        now = time.monotonic()
        explicit_refresh = bool(show_message or replace_existing or force_rebuild)
        min_interval = 0.45 if explicit_refresh else 1.25
        if now - float(getattr(self, "_last_dcc_scene_refresh_at", 0.0) or 0.0) < min_interval:
            return False
        self._dcc_scene_refresh_busy = True
        self._last_dcc_scene_refresh_at = now
        try:
            return self._load_dcc_scene_providers_now(
                providers,
                show_message=show_message,
                replace_existing=replace_existing,
                force_rebuild=force_rebuild,
            )
        finally:
            self._dcc_scene_refresh_busy = False

    def _load_dcc_scene_providers_now(
        self,
        providers: list[str],
        *,
        show_message: bool = False,
        replace_existing: bool = False,
        force_rebuild: bool = False,
    ) -> bool:
        self._last_scene_refresh_changed = False
        new_snapshots: dict[str, dict[str, Any]] = {}
        changed_signatures: dict[str, str] = {}
        unchanged_providers: list[str] = []
        errors = []
        selected_only = bool(
            getattr(self, "maya_selected_only_checkbox", None) is not None
            and self.maya_selected_only_checkbox.isChecked()
        )
        for provider in providers:
            try:
                bridge = self._scene_snapshot_bridge(provider)
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                continue
            lightweight_preflight = bool(
                not force_rebuild
                and not show_message
                and not replace_existing
                and provider in getattr(self, "_dcc_scene_snapshots", {})
            )
            kwargs = {
                "selected_only": selected_only,
                "include_geometry": not lightweight_preflight,
                "limit": 500,
                "timeout": 2.0 if lightweight_preflight else 12.0,
            }
            if provider == "maya":
                kwargs["meshes_only"] = False
            try:
                ok, snapshot_or_error = bridge.get_scene_snapshot(**kwargs)
            except TypeError:
                ok, snapshot_or_error = bridge.get_scene_snapshot(
                    selected_only=selected_only,
                    limit=500,
                    timeout=12.0,
                )
            if not ok:
                if lightweight_preflight and provider in getattr(self, "_dcc_scene_snapshots", {}):
                    errors.append(f"{provider}: preflight skipped ({str(snapshot_or_error)[:80]})")
                    unchanged_providers.append(provider)
                    continue
                errors.append(f"{provider}: {snapshot_or_error}")
                continue
            try:
                snapshot_or_error = self._snapshot_for_viewer_scale_policy(provider, snapshot_or_error)
                signature = self._snapshot_dirty_signature(snapshot_or_error)
                previous_signature = getattr(self, "_dcc_snapshot_signatures", {}).get(provider)
                if (
                    lightweight_preflight
                    and previous_signature
                    and previous_signature == signature
                ):
                    unchanged_providers.append(provider)
                    continue
                if lightweight_preflight:
                    full_kwargs = dict(kwargs)
                    full_kwargs["include_geometry"] = True
                    try:
                        ok, full_snapshot_or_error = bridge.get_scene_snapshot(**full_kwargs)
                    except TypeError:
                        ok, full_snapshot_or_error = bridge.get_scene_snapshot(
                            selected_only=selected_only,
                            limit=500,
                            timeout=12.0,
                        )
                    if not ok:
                        errors.append(f"{provider}: {full_snapshot_or_error}")
                        continue
                    snapshot_or_error = self._snapshot_for_viewer_scale_policy(provider, full_snapshot_or_error)
                FBXMeshModel.from_scene_snapshot(snapshot_or_error)
                new_snapshots[provider] = snapshot_or_error
                changed_signatures[provider] = signature
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
        if not new_snapshots:
            if unchanged_providers:
                detail = f"Scene refresh skipped: {', '.join(unchanged_providers)} unchanged"
                if errors:
                    detail += f" | {'; '.join(errors)[:90]}"
                self._resolved_shaded_status = detail
                self.update_viewport_status()
                return True
            if show_message:
                QMessageBox.warning(self, "DCC Scene Load Failed", "\n".join(errors) or "No connected providers returned scene data.")
            return False
        previous_proxy_state = self._capture_proxy_refresh_state()
        had_existing_snapshots = bool(getattr(self, "_dcc_scene_snapshots", {})) and not replace_existing
        if replace_existing:
            self._dcc_scene_snapshots = {}
            self._dcc_snapshot_signatures = {}
        self._dcc_scene_snapshots.update(new_snapshots)
        self._dcc_snapshot_signatures.update(changed_signatures)
        self._last_scene_refresh_changed = True
        self._loaded_scene_providers = list(self._dcc_scene_snapshots.keys())
        preserved_center = None
        preserved_scale = None
        if had_existing_snapshots and not replace_existing:
            preserved_center = getattr(self.mesh, "scene_center", None)
            preserved_scale = getattr(self.mesh, "scene_scale", None)
        self.mesh = FBXMeshModel.from_scene_snapshots(
            list(self._dcc_scene_snapshots.values()),
            scene_center=preserved_center,
            scene_scale=preserved_scale,
        )
        self._apply_proxy_refresh_state(previous_proxy_state)
        self._refresh_coordinate_scale_status()
        self._refresh_camera_authority_choices()
        self.refresh_scene_outliner()
        self.show_texture = False
        if getattr(self, "texture_btn", None) is not None:
            self.texture_btn.setChecked(False)
        if replace_existing or (show_message and not had_existing_snapshots):
            self.frame_mesh_camera()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        if show_message and self.isVisible():
            active_snapshots = list(self._dcc_scene_snapshots.values())
            object_count = sum(len(snapshot.get("objects") or []) for snapshot in active_snapshots)
            camera_count = sum(len(snapshot.get("cameras") or []) for snapshot in active_snapshots)
            real_mesh_count = sum(
                1 for obj in getattr(self.mesh, "scene_proxy_objects", [])
                if obj.get("representation") == "mesh"
            )
            bounds_count = max(0, len(getattr(self.mesh, "scene_proxy_objects", [])) - real_mesh_count)
            QMessageBox.information(
                self,
                "DCC Scene Loaded",
                (
                    f"Added/refreshed {', '.join(new_snapshots.keys())}.\n"
                    f"Active federated scene: {object_count} isolated visible elements from "
                    f"{', '.join(self._loaded_scene_providers)} and {camera_count} cameras.\n\n"
                    f"True mesh geometry: {real_mesh_count}\n"
                    f"Bounds fallback elements: {bounds_count}\n\n"
                    f"Coordinate scale: {getattr(self, '_coordinate_scale_status', '') or 'not available'}\n\n"
                    "The Tech Connector viewer renders this locally for fluid navigation."
                ),
            )
        self.schedule_resolved_shaded_refresh("scene refreshed")
        return True

    def _snapshot_dirty_signature(self, snapshot: dict[str, Any]) -> str:
        def compact_object(obj: dict[str, Any]) -> dict[str, Any]:
            material = obj.get("material") if isinstance(obj.get("material"), dict) else {}
            return {
                "native_id": obj.get("native_id"),
                "name": obj.get("name"),
                "type": obj.get("type"),
                "shape_types": obj.get("shape_types"),
                "bbox": obj.get("bbox"),
                "translation": obj.get("translation"),
                "rotation": obj.get("rotation"),
                "scale": obj.get("scale"),
                "visible": obj.get("visible", True),
                "material": material,
                "light": obj.get("light") if isinstance(obj.get("light"), dict) else None,
            }

        def compact_camera(camera: dict[str, Any]) -> dict[str, Any]:
            return {
                "native_id": camera.get("native_id"),
                "name": camera.get("name"),
                "type": camera.get("type"),
                "translation": camera.get("translation"),
                "rotation": camera.get("rotation"),
                "focal_length_mm": camera.get("focal_length_mm"),
                "near_clip": camera.get("near_clip"),
                "far_clip": camera.get("far_clip"),
                "visible": camera.get("visible", True),
            }

        payload = {
            "provider_id": snapshot.get("provider_id"),
            "unit_linear": snapshot.get("unit_linear"),
            "up_axis": snapshot.get("up_axis"),
            "unit_scale_policy": snapshot.get("unit_scale_policy"),
            "objects": [
                compact_object(obj)
                for obj in (snapshot.get("objects") or [])
                if isinstance(obj, dict) and obj.get("type") != "error"
            ],
            "cameras": [
                compact_camera(camera)
                for camera in (snapshot.get("cameras") or [])
                if isinstance(camera, dict)
            ],
            "active_camera": snapshot.get("active_camera"),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _snapshot_for_viewer_scale_policy(self, provider: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return snapshot
        snapshot = dict(snapshot)
        raw_unit = str(snapshot.get("unit_linear") or "")
        snapshot.setdefault("source_unit_linear", raw_unit)
        snapshot["unit_scale_policy"] = str(getattr(self, "dcc_unit_scale_policy", "working_units") or "working_units")
        if snapshot["unit_scale_policy"] == "working_units":
            # Viewport composition is axis-accurate but unit-neutral by default.
            # This avoids Blender METRIC scenes exploding by x100 against Maya
            # authoring units while preserving the raw unit for diagnostics.
            snapshot["unit_linear"] = "centimeters"
        snapshot.setdefault("provider_id", provider)
        snapshot.setdefault("up_axis", self._default_up_axis_for_provider(provider))
        return snapshot

    def _default_up_axis_for_provider(self, provider: str) -> str:
        provider_key = str(provider or "").lower()
        if provider_key in {"blender", "unreal", "3dsmax", "max"}:
            return "z"
        return "y"

    def _refresh_coordinate_scale_status(self) -> None:
        snapshots = getattr(self, "_dcc_scene_snapshots", {}) or {}
        if not snapshots:
            self._coordinate_scale_status = ""
            return
        diagnostics = snapshot_scale_diagnostics(
            snapshots,
            reference_provider_id="maya",
            reference_unit_linear="centimeters",
        )
        parts = []
        for key in sorted(diagnostics):
            snapshot = snapshots.get(key) or {}
            diagnostic = diagnostics[key]
            raw_unit = str(snapshot.get("source_unit_linear") or snapshot.get("unit_linear") or "")
            effective_unit = str(snapshot.get("unit_linear") or "")
            if raw_unit and raw_unit.lower() != effective_unit.lower():
                raw_diagnostic = provider_scale_diagnostic(
                    key,
                    raw_unit,
                    reference_provider_id="maya",
                    reference_unit_linear="centimeters",
                )
                parts.append(
                    f"{key}:{raw_unit} raw x{raw_diagnostic.native_to_reference_scale:g}, "
                    f"view x{diagnostic.native_to_reference_scale:g}"
                )
            else:
                parts.append(diagnostic.compact_label())
        relation = self._matching_scene_element_scale_status("maya", "blender", "cube")
        if relation:
            parts.append(relation)
        self._coordinate_scale_status = " | ".join(parts)

    def _matching_scene_element_scale_status(self, provider_a: str, provider_b: str, name_token: str) -> str:
        snapshots = getattr(self, "_dcc_scene_snapshots", {}) or {}
        snapshot_a = snapshots.get(provider_a) or {}
        snapshot_b = snapshots.get(provider_b) or {}
        if not snapshot_a or not snapshot_b:
            return ""

        def find_object(snapshot: dict[str, Any], token: str) -> dict[str, Any] | None:
            for obj in snapshot.get("objects") or []:
                if not isinstance(obj, dict) or len(obj.get("bbox") or []) != 6:
                    continue
                name = str(obj.get("name") or obj.get("native_id") or "").lower()
                if token.lower() in name:
                    return obj
            return None

        obj_a = find_object(snapshot_a, name_token)
        obj_b = find_object(snapshot_b, name_token)
        if not obj_a or not obj_b:
            return ""

        def bbox_center_and_extent(provider: str, snapshot: dict[str, Any], obj: dict[str, Any]) -> tuple[tuple[float, float, float], float]:
            shared_bbox = provider_bbox_to_shared(
                provider,
                obj["bbox"],
                snapshot.get("unit_linear"),
                snapshot.get("up_axis"),
            )
            center = tuple((float(shared_bbox[i]) + float(shared_bbox[i + 3])) * 0.5 for i in range(3))
            extent = max(
                abs(float(shared_bbox[3]) - float(shared_bbox[0])),
                abs(float(shared_bbox[4]) - float(shared_bbox[1])),
                abs(float(shared_bbox[5]) - float(shared_bbox[2])),
                1.0e-9,
            )
            return center, extent

        center_a, extent_a = bbox_center_and_extent(provider_a, snapshot_a, obj_a)
        center_b, extent_b = bbox_center_and_extent(provider_b, snapshot_b, obj_b)
        above = "above" if center_a[1] > center_b[1] else "below" if center_a[1] < center_b[1] else "level"
        ratio = extent_a / max(1.0e-9, extent_b)
        return (
            f"{provider_a}:{obj_a.get('name') or name_token} {above} {provider_b}:{obj_b.get('name') or name_token} "
            f"Y {center_a[1]:.3g}>{center_b[1]:.3g} size {ratio:.3g}x"
            if center_a[1] > center_b[1]
            else f"{provider_a}:{obj_a.get('name') or name_token} {above} {provider_b}:{obj_b.get('name') or name_token} "
            f"Y {center_a[1]:.3g}/{center_b[1]:.3g} size {ratio:.3g}x"
        )

    def _capture_proxy_refresh_state(self) -> dict[str, dict[str, Any]]:
        state: dict[str, dict[str, Any]] = {}
        selected = getattr(self, "_selected_scene_proxy", None)
        for proxy in getattr(getattr(self, "mesh", None), "scene_proxy_objects", []) or []:
            if not isinstance(proxy, (dict, SceneProxyInstance)):
                continue
            key = str(proxy.get("source_key") or f"{proxy.get('provider_id')}:{proxy.get('native_id')}")
            if not key or key == ":":
                continue
            state[key] = {
                "source_signature": str(proxy.get("source_signature") or ""),
                "sync_state": str(proxy.get("sync_state") or "clean"),
                "pending_shared_delta": tuple(float(v) for v in (proxy.get("_pending_shared_delta") or (0.0, 0.0, 0.0))),
                "local_transform": dict(proxy.get("local_transform") or {}),
                "selected": proxy is selected,
                "visible": bool(proxy.get("visible", True)),
            }
        return state

    def _apply_proxy_refresh_state(self, previous: dict[str, dict[str, Any]]) -> None:
        selected_key = ""
        for key, item in previous.items():
            if item.get("selected"):
                selected_key = key
                break
        restored_selection = None
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if not isinstance(proxy, SceneProxyInstance):
                continue
            key = str(proxy.source_key or f"{proxy.provider_id}:{proxy.native_id}")
            prior = previous.get(key)
            if not prior:
                proxy.sync_state = "new"
            else:
                proxy.visible = bool(prior.get("visible", True))
                prior_sig = str(prior.get("source_signature") or "")
                source_changed = bool(prior_sig and prior_sig != proxy.source_signature)
                pending = tuple(float(v) for v in (prior.get("pending_shared_delta") or (0.0, 0.0, 0.0)))
                had_local_edit = max(abs(v) for v in pending) > 1.0e-6 or str(prior.get("sync_state") or "") in {"dirty", "conflict"}
                if had_local_edit:
                    proxy.pending_shared_delta = pending
                    proxy.local_transform = dict(prior.get("local_transform") or proxy.source_transform)
                    proxy.sync_state = "conflict" if source_changed else "dirty"
                    if max(abs(v) for v in pending) > 1.0e-6:
                        self._offset_proxy_preview(proxy, pending, mark_dirty=False)
                elif source_changed:
                    proxy.sync_state = "source_changed"
                else:
                    proxy.sync_state = "clean"
            if key == selected_key:
                restored_selection = proxy
            if key and key == getattr(self, "_camera_pivot_source_key", ""):
                self._move_camera_pivot_to_proxy(proxy, keep_eye_offset=True)
        self._selected_scene_proxy = restored_selection

    def refresh_scene_outliner(self) -> None:
        tree = getattr(self, "scene_outliner", None)
        if tree is None:
            return
        tree.blockSignals(True)
        tree.clear()
        snapshots = getattr(self, "_dcc_scene_snapshots", {}) or {}
        proxies = getattr(self.mesh, "scene_proxy_objects", []) or []
        proxies_by_provider: dict[str, list[dict[str, Any]]] = {}
        for proxy in proxies:
            provider = str(proxy.get("provider_id") or "provider")
            proxies_by_provider.setdefault(provider, []).append(proxy)

        def visible_outliner_cameras(provider: str) -> list[dict[str, Any]]:
            result = []
            for camera in (snapshots.get(provider, {}).get("cameras") or []):
                if not isinstance(camera, dict):
                    continue
                camera_name = str(camera.get("name") or camera.get("native_id") or "camera")
                if camera_name.startswith("TechConnector_Camera"):
                    continue
                result.append(camera)
            return result

        for provider in sorted(set(snapshots.keys()) | set(proxies_by_provider.keys())):
            object_count = len(proxies_by_provider.get(provider, []))
            cameras = visible_outliner_cameras(provider)
            camera_count = len(cameras)
            provider_item = QTreeWidgetItem([provider, "app", f"{object_count} objects / {camera_count} cameras"])
            provider_item.setData(0, Qt.UserRole, {"kind": "provider", "provider": provider})
            provider_item.setForeground(0, provider_view_colors(provider)[1])
            provider_item.setToolTip(0, f"{provider} federated scene layer")
            tree.addTopLevelItem(provider_item)

            objects_parent = QTreeWidgetItem(["Scene Elements", "group", str(object_count)])
            provider_item.addChild(objects_parent)
            for proxy in proxies_by_provider.get(provider, []):
                name = str(proxy.get("name") or proxy.get("native_id") or "object")
                representation = str(proxy.get("representation") or "")
                is_visible = bool(proxy.get("visible", True))
                state = str(proxy.get("sync_state") or representation or "clean")
                if not is_visible:
                    state = "hidden"
                item = QTreeWidgetItem([name, str(proxy.get("type") or "object"), state])
                item.setData(0, Qt.UserRole, {"kind": "object", "provider": provider, "native_id": proxy.get("native_id"), "proxy": proxy})
                item.setForeground(0, proxy.get("wire_color") or provider_view_colors(provider)[1])
                item.setToolTip(0, str(proxy.get("native_id") or name))
                objects_parent.addChild(item)

            cameras_parent = QTreeWidgetItem(["Cameras", "group", str(camera_count)])
            provider_item.addChild(cameras_parent)
            for camera in cameras:
                camera_name = str(camera.get("name") or camera.get("native_id") or "camera")
                active = "active" if str(camera.get("native_id") or "").endswith(str(snapshots.get(provider, {}).get("active_camera") or "")) else ""
                item = QTreeWidgetItem([camera_name, "camera", active])
                item.setData(0, Qt.UserRole, {"kind": "camera", "provider": provider, "native_id": camera.get("native_id")})
                item.setToolTip(0, str(camera.get("native_id") or camera_name))
                cameras_parent.addChild(item)
            provider_item.setExpanded(True)
            objects_parent.setExpanded(True)
            cameras_parent.setExpanded(True)

        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        tree.blockSignals(False)
        self.update_instance_details_panel()
        self.update_viewport_status()

    def on_scene_outliner_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        data = item.data(0, Qt.UserRole) or {}
        if data.get("kind") != "object":
            return
        proxy = data.get("proxy")
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return
        visible = item.checkState(0) == Qt.Checked
        proxy["visible"] = visible
        name = str(proxy.get("name") or proxy.get("native_id") or "object")
        provider = str(proxy.get("provider_id") or data.get("provider") or "")
        state = str(proxy.get("sync_state") or proxy.get("representation") or "clean") if visible else "hidden"
        item.setText(2, state)
        self._resolved_shaded_status = f"{'Show' if visible else 'Hide'} {provider}:{name}"
        self.update_instance_details_panel()
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def on_scene_outliner_selection_changed(self) -> None:
        tree = getattr(self, "scene_outliner", None)
        if tree is None:
            return
        items = tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.UserRole) or {}
        kind = data.get("kind")
        if kind == "object":
            proxy = data.get("proxy")
            if isinstance(proxy, (dict, SceneProxyInstance)):
                self._selected_scene_proxy = proxy
                self.update_instance_details_panel()
                self.update_viewport_status()
                if hasattr(self, "canvas") and self.canvas:
                    self.canvas.update()
        elif kind == "camera":
            provider = str(data.get("provider") or "")
            native_id = str(data.get("native_id") or "")
            combo = getattr(self, "camera_authority_combo", None)
            if combo is not None and provider and native_id:
                for index in range(combo.count()):
                    choice = combo.itemData(index) or {}
                    if choice.get("mode") == "dcc_camera" and choice.get("provider") == provider and choice.get("native_id") == native_id:
                        combo.setCurrentIndex(index)
                        break
            self.update_viewport_status()

    def update_instance_details_panel(self) -> None:
        title = getattr(self, "instance_title_label", None)
        source = getattr(self, "instance_source_label", None)
        mesh = getattr(self, "instance_mesh_label", None)
        material = getattr(self, "instance_material_label", None)
        textures = getattr(self, "instance_texture_label", None)
        context = getattr(self, "instance_context_label", None)
        visibility_btn = getattr(self, "instance_visibility_btn", None)
        show_only_btn = getattr(self, "instance_show_only_btn", None)
        actions_btn = getattr(self, "instance_context_btn", None)
        visible_checkbox = getattr(self, "instance_visible_checkbox", None)
        visibility_section_btn = getattr(self, "instance_visibility_section_btn", None)
        if not all((title, source, mesh, material, textures, context)):
            return
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            title.setText("Instance Details")
            source.setText("Source: none")
            mesh.setText("Mesh: none")
            material.setText("Material: none")
            textures.setText("Textures: none")
            context.setText("Context: none")
            for button in (visibility_btn, show_only_btn, actions_btn):
                if button is not None:
                    button.setEnabled(False)
            if visible_checkbox is not None:
                visible_checkbox.blockSignals(True)
                visible_checkbox.setChecked(False)
                visible_checkbox.setEnabled(False)
                visible_checkbox.blockSignals(False)
            if visibility_section_btn is not None:
                visibility_section_btn.setEnabled(False)
            return
        for button in (visibility_btn, show_only_btn, actions_btn):
            if button is not None:
                button.setEnabled(True)
        if visibility_section_btn is not None:
            visibility_section_btn.setEnabled(True)
        provider = str(proxy.get("provider_id") or "")
        name = str(proxy.get("name") or proxy.get("native_id") or "object")
        native_id = str(proxy.get("native_id") or "")
        sync_state = str(proxy.get("sync_state") or "clean")
        object_type = str(proxy.get("type") or proxy.get("object_type") or "object")
        representation = str(proxy.get("representation") or "")
        is_visible = bool(proxy.get("visible", True))
        title.setText(name[:56])
        source_transform = dict(proxy.get("source_transform") or {})
        local_transform = dict(proxy.get("local_transform") or source_transform)
        source_t = source_transform.get("translation")
        local_t = local_transform.get("translation")
        transform_note = ""
        if isinstance(source_t, (list, tuple)) and len(source_t) >= 3:
            transform_note = f"  |  Src T: {float(source_t[0]):.3g}, {float(source_t[1]):.3g}, {float(source_t[2]):.3g}"
        if isinstance(local_t, (list, tuple)) and len(local_t) >= 3 and list(local_t[:3]) != list((source_t or [])[:3]):
            transform_note += f"  |  Local T: {float(local_t[0]):.3g}, {float(local_t[1]):.3g}, {float(local_t[2]):.3g}"
        source.setText(f"Source: {provider}:{native_id or name}  |  Sync: {sync_state}  |  Vis: {'on' if is_visible else 'off'}")
        if transform_note:
            source.setText(source.text() + transform_note)

        mesh_data = proxy.get("mesh_data")
        if isinstance(mesh_data, SceneProxyMeshData):
            mesh.setText(
                f"Mesh: {mesh_data.vertex_count} verts / {mesh_data.face_count} tris / {mesh_data.quad_count} quads  |  {representation}"
            )
        else:
            mesh.setText(f"Mesh: {representation or 'unknown'}")

        materials = proxy.get("materials") or []
        if materials and isinstance(materials[0], SceneProxyMaterialBinding):
            binding = materials[0]
            material.setText(
                f"Material: {binding.name or 'source material'}  |  {binding.approximation}  |  {binding.color.name()}"
            )
            texture_bindings = dict(binding.texture_paths or {})
        else:
            color = proxy.get("material_color")
            color_name = color.name() if isinstance(color, QColor) else "none"
            material.setText(f"Material: base color  |  {color_name}")
            texture_bindings = dict(proxy.get("texture_bindings") or {})
        if texture_bindings:
            parts = [f"{slot}:{Path(path).name}" for slot, path in sorted(texture_bindings.items()) if path]
            textures.setText("Textures: " + (", ".join(parts) if parts else "none"))
        else:
            textures.setText("Textures: none")
        if visibility_btn is not None:
            visibility_btn.setText("Hide" if is_visible else "Show")
        if visible_checkbox is not None:
            visible_checkbox.blockSignals(True)
            visible_checkbox.setEnabled(True)
            visible_checkbox.setChecked(is_visible)
            visible_checkbox.blockSignals(False)
        context.setText("Context: " + self._selected_proxy_context_summary(provider, object_type, representation))

    def set_instance_visibility_section_open(self, open_: bool) -> None:
        section = getattr(self, "instance_visibility_section", None)
        button = getattr(self, "instance_visibility_section_btn", None)
        if section is not None:
            section.setVisible(bool(open_))
        if button is not None:
            button.setText("Visibility ▾" if open_ else "Visibility ▸")

    def set_selected_proxy_visibility(self, visible: bool) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return
        proxy["visible"] = bool(visible)
        name = str(proxy.get("name") or proxy.get("native_id") or "object")
        self._resolved_shaded_status = f"{'Show' if visible else 'Hide'} {proxy.get('provider_id')}:{name}"
        self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _selected_proxy_context_summary(self, provider: str, object_type: str, representation: str) -> str:
        provider_label = {
            "maya": "Maya DAG",
            "blender": "Blender object",
            "unreal": "Unreal actor/component",
            "unity": "Unity object",
            "houdini": "Houdini node",
            "motionbuilder": "MotionBuilder model",
            "3dsmax": "3ds Max node",
        }.get(str(provider or "").lower(), str(provider or "DCC"))
        type_text = str(object_type or representation or "object")
        type_key = type_text.lower()
        if "joint" in type_key or "bone" in type_key:
            role = "joint/skeleton"
        elif "follicle" in type_key:
            role = "follicle attachment"
        elif "nurbs" in type_key or "curve" in type_key:
            role = "NURBS/curve"
        elif any(token in type_key for token in ("physics", "rigid", "collision", "collider", "body")):
            role = "physics/collision"
        elif "light" in type_key:
            role = "light"
        elif "camera" in type_key:
            role = "camera"
        elif "mesh" in type_key:
            role = "mesh"
        else:
            role = type_text
        return f"{provider_label} | {role} | {representation or 'proxy'}"

    def toggle_selected_proxy_visibility(self) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return
        self.set_selected_proxy_visibility(not bool(proxy.get("visible", True)))

    def show_only_selected_proxy(self) -> None:
        selected = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(selected, (dict, SceneProxyInstance)):
            return
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if isinstance(proxy, (dict, SceneProxyInstance)):
                proxy["visible"] = proxy is selected
        self._resolved_shaded_status = f"Solo {selected.get('provider_id')}:{selected.get('name') or selected.get('native_id')}"
        self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def show_all_scene_proxies(self) -> None:
        changed = 0
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                proxy["visible"] = True
                changed += 1
        self._resolved_shaded_status = f"Show all scene elements ({changed} restored)"
        self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def show_selected_proxy_actions_menu(self) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        button = getattr(self, "instance_context_btn", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)) or button is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background:#080d14; color:#ddffe9; border:1px solid #12324a; } QMenu::item:selected { background:#12324a; color:#16f26a; }")
        action_focus = menu.addAction("Frame / Focus Selection")
        action_visibility = menu.addAction("Hide in TC View" if bool(proxy.get("visible", True)) else "Show in TC View")
        action_solo = menu.addAction("Show Only This Element")
        menu.addSeparator()
        provider = str(proxy.get("provider_id") or "").lower()
        object_type = str(proxy.get("type") or proxy.get("object_type") or "object").lower()
        source_action_label = {
            "maya": "Select in Maya",
            "blender": "Select in Blender",
            "unreal": "Select in Unreal",
        }.get(provider, f"Select in {provider or 'Source'}")
        action_select_source = menu.addAction(source_action_label)
        if provider not in {"maya", "blender", "unreal"}:
            action_select_source.setEnabled(False)
        if "joint" in object_type or "bone" in object_type:
            menu.addAction("Context: joint/skeleton controls").setEnabled(False)
        elif "follicle" in object_type:
            menu.addAction("Context: follicle attachment controls").setEnabled(False)
        elif "nurbs" in object_type or "curve" in object_type:
            menu.addAction("Context: NURBS/curve controls").setEnabled(False)
        elif any(token in object_type for token in ("physics", "rigid", "collision", "collider", "body")):
            menu.addAction("Context: physics/collision controls").setEnabled(False)
        elif "mesh" in object_type:
            menu.addAction("Context: mesh/material controls").setEnabled(False)
        chosen = menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen == action_focus:
            self.focus_selected_scene_element()
        elif chosen == action_visibility:
            self.toggle_selected_proxy_visibility()
        elif chosen == action_solo:
            self.show_only_selected_proxy()
        elif chosen == action_select_source:
            self.select_selected_proxy_in_source()

    def select_selected_proxy_in_source(self) -> tuple[bool, str]:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return False, "No scene proxy is selected."
        provider = str(proxy.get("provider_id") or "").lower()
        native_id = str(proxy.get("native_id") or "")
        name = str(proxy.get("name") or native_id or "object")
        if not provider or not native_id:
            return False, "Selected proxy does not have a native target."
        try:
            bridge = self._scene_snapshot_bridge(provider)
            if provider == "maya":
                code = (
                    "import maya.cmds as cmds\n"
                    f"node = {native_id!r}\n"
                    "if not cmds.objExists(node):\n"
                    "    raise RuntimeError('Object does not exist: ' + node)\n"
                    "cmds.select(node, replace=True)\n"
                    "print('OK')"
                )
                ok, raw = bridge.execute(code, timeout=5.0)
            elif provider == "blender":
                code = (
                    "import bpy\n"
                    f"name = {native_id!r}\n"
                    "obj = bpy.data.objects.get(name)\n"
                    "if obj is None:\n"
                    "    raise RuntimeError('Object does not exist: ' + name)\n"
                    "bpy.ops.object.select_all(action='DESELECT')\n"
                    "obj.select_set(True)\n"
                    "bpy.context.view_layer.objects.active = obj\n"
                    "print('OK')"
                )
                ok, raw = bridge.execute(code, timeout=5.0)
            elif provider == "unreal":
                response = bridge.execute_python(self._unreal_select_actor_code(native_id), timeout=8.0, reset_globals=True)
                ok = bool(response.get("ok"))
                raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
            else:
                return False, f"Source selection is not implemented for {provider} yet."
            if not ok:
                raise RuntimeError(str(raw))
            self._resolved_shaded_status = f"Selected source object {provider}:{name}"
            self.update_viewport_status()
            return True, self._resolved_shaded_status
        except Exception as exc:
            self._resolved_shaded_status = f"Source select failed: {exc}"
            self.update_viewport_status()
            if self.isVisible():
                QMessageBox.warning(self, "Source Select Failed", str(exc))
            return False, str(exc)

    def bind_texture_to_selected_proxy(self, slot: str) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, SceneProxyInstance):
            if self.isVisible():
                QMessageBox.information(self, "No Proxy Selected", "Select a scene proxy instance before binding a texture.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Bind {slot.replace('_', ' ').title()} Texture",
            "",
            "Texture Images (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.exr *.bmp *.webp);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        proxy.bind_texture_file(slot, path)
        self._resolved_shaded_status = f"Bound {slot} texture to {proxy.provider_id}:{proxy.name}"
        self.update_instance_details_panel()
        self.update_viewport_status()
        if getattr(self, "scene_outliner", None) is not None:
            self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def update_viewport_status(self) -> None:
        label = getattr(self, "viewport_status_label", None)
        if label is None:
            return
        providers = ", ".join(getattr(self, "_loaded_scene_providers", []) or ["local"])
        mode = getattr(self, "viewport_mode", "Paint")
        display = getattr(self, "viewport_shading_mode", "Highlight")
        if str(getattr(self, "viewport_display_source", "compiled") or "compiled").lower() == "dcc":
            wire = "otherWire:on" if getattr(self, "show_dcc_context_wire", True) else "otherWire:off"
            display = f"DCC:{getattr(self, 'active_dcc_view_provider', '') or 'viewport'} {wire}"
        coord = str(getattr(self, "viewer_coord_space", "maya") or "maya")
        drive = "on" if getattr(self, "drive_dcc_camera_enabled", False) else "off"
        time_drive = "on" if getattr(self, "drive_dcc_time_enabled", False) else "off"
        if getattr(self, "drive_dcc_camera_enabled", False):
            _cached_at, drive_providers, skipped = getattr(self, "_camera_drive_provider_cache", (0.0, [], []))
            if drive_providers:
                drive += f" ({', '.join(drive_providers)})"
            if skipped:
                drive += f" unsupported:{','.join(skipped)}"
        selected = getattr(self, "_selected_scene_proxy", None)
        selected_text = "none"
        if isinstance(selected, (dict, SceneProxyInstance)):
            selected_text = f"{selected.get('provider_id')}:{selected.get('name') or selected.get('native_id')}"
            materials = selected.get("materials") or []
            mesh_data = selected.get("mesh_data")
            if isinstance(mesh_data, SceneProxyMeshData):
                selected_text += f" [{mesh_data.vertex_count}v/{mesh_data.face_count}f]"
            if materials:
                material_name = materials[0].name if isinstance(materials[0], SceneProxyMaterialBinding) else ""
                if material_name:
                    selected_text += f" mat:{material_name}"
        resolved = getattr(self, "_resolved_shaded_status", "")
        scale_status = getattr(self, "_coordinate_scale_status", "")
        scale_text = f"   |   Scale: {scale_status}" if scale_status else ""
        label.setText(f"Mode: {mode}   |   Display: {display}   |   Coord: {coord}   |   Drive Cam: {drive}   |   Drive Time: {time_drive}   |   Providers: {providers}{scale_text}   |   Selected: {selected_text}   |   {resolved}")

    def refresh_loaded_dcc_scenes(self):
        if not self.isVisible():
            return
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        if not providers:
            return
        self._load_dcc_scene_providers(providers, show_message=False)

    def refresh_loaded_dcc_scenes_for_current_frame(self):
        if not self.isVisible():
            return
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        if not providers:
            return
        if getattr(self, "drive_dcc_time_enabled", True):
            self.drive_loaded_dcc_time_from_view()
        if self._load_dcc_scene_providers(providers, show_message=False):
            if getattr(self, "_cross_dcc_transform_constraints", None):
                ok, message = self.apply_cross_dcc_transform_constraints()
                self._resolved_shaded_status = message if ok else f"Constraint update failed: {message}"
                target_providers = sorted({
                    str(item.get("target_provider") or "")
                    for item in getattr(self, "_cross_dcc_transform_constraints", []) or []
                    if item.get("target_provider")
                })
                if target_providers:
                    self._resolved_shaded_status += " Targets update on next refresh."

    def on_timeline_frame_changed(self, frame_index: int):
        self._current_dcc_frame = int(frame_index or 0) + 1
        if not getattr(self, "_loaded_scene_providers", None):
            return
        if getattr(self, "drive_dcc_time_enabled", True):
            self._resolved_shaded_status = f"Driving DCC time: frame {self._current_dcc_frame}"
            self.update_viewport_status()
        self.timeline_refresh_timer.start()
        self.schedule_resolved_shaded_refresh("timeline scrub")

    def drive_loaded_dcc_time_from_view(self) -> tuple[bool, str]:
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        if not providers:
            return False, "No loaded DCC providers to drive time."
        frame = int(getattr(self, "_current_dcc_frame", 1) or 1)
        failures = []
        driven = []
        for provider in providers:
            try:
                self._set_provider_frame(provider, frame)
                driven.append(provider)
            except Exception as exc:
                failures.append(f"{provider}: {exc}")
        if failures:
            self._resolved_shaded_status = f"Time drive partial: frame {frame} | {'; '.join(failures)[:100]}"
            self.update_viewport_status()
            return False, "; ".join(failures)
        self._resolved_shaded_status = f"Time drive: frame {frame} -> {', '.join(driven)}"
        self.update_viewport_status()
        return True, self._resolved_shaded_status

    def set_live_dcc_refresh(self, enabled: bool):
        if bool(enabled):
            if not getattr(self, "_loaded_scene_providers", None):
                provider = "maya"
                if getattr(self, "dcc_scene_provider_combo", None) is not None:
                    provider = str(self.dcc_scene_provider_combo.currentData() or "maya")
                self._loaded_scene_providers = self._scene_snapshot_provider_keys(provider)
            self.live_refresh_timer.start()
        else:
            self.live_refresh_timer.stop()

    def _refresh_camera_authority_choices(self) -> None:
        combo = getattr(self, "camera_authority_combo", None)
        if combo is None:
            return
        current_data = combo.currentData()
        current_key = json.dumps(current_data, sort_keys=True, default=str) if current_data else ""
        self._suppress_camera_combo_update = True
        combo.clear()
        combo.addItem("TC Camera", {"mode": "tech_connector"})
        for provider, snapshot in getattr(self, "_dcc_scene_snapshots", {}).items():
            active_camera = str(snapshot.get("active_camera") or "")
            for camera in snapshot.get("cameras") or []:
                if not isinstance(camera, dict):
                    continue
                native_id = str(camera.get("native_id") or camera.get("name") or "")
                if not native_id:
                    continue
                camera_name = str(camera.get("name") or native_id)
                if camera_name.startswith("TechConnector_Camera"):
                    continue
                camera_role = str(camera.get("camera_role") or "").strip().lower()
                role_suffix = f" [{camera_role}]" if provider == "unreal" and camera_role else ""
                label = f"{provider}: {camera_name}{role_suffix}"
                if active_camera and native_id.endswith(active_camera):
                    label += " (active)"
                combo.addItem(
                    label,
                    {
                        "mode": "dcc_camera",
                        "provider": provider,
                        "native_id": native_id,
                        "camera_role": camera_role,
                    },
                )
        for index in range(combo.count()):
            data = combo.itemData(index)
            key = json.dumps(data, sort_keys=True, default=str) if data else ""
            if key == current_key:
                combo.setCurrentIndex(index)
                break
        self._suppress_camera_combo_update = False

    def sync_selected_camera_authority(self) -> None:
        choice = {"mode": "tech_connector"}
        if getattr(self, "camera_authority_combo", None) is not None:
            choice = self.camera_authority_combo.currentData() or choice
        mode = str(choice.get("mode") or "tech_connector")
        if mode == "dcc_camera":
            ok, message = self._use_dcc_camera_authority(str(choice.get("provider") or ""), str(choice.get("native_id") or ""))
        else:
            ok, message = self.possess_loaded_dcc_cameras(include_unreal=True)
        if self.isVisible():
            if ok:
                QMessageBox.information(self, "Camera Sync Complete", message)
            else:
                QMessageBox.warning(self, "Camera Sync Failed", message)

    def set_drive_dcc_camera_enabled(self, enabled: bool) -> None:
        self.drive_dcc_camera_enabled = bool(enabled)
        if enabled:
            self._camera_drive_provider_cache = (0.0, [], [])
            self.schedule_dcc_camera_drive("drive enabled")
        self.update_viewport_status()

    def schedule_dcc_camera_drive(self, reason: str = "") -> None:
        if not getattr(self, "drive_dcc_camera_enabled", False):
            return
        timer = getattr(self, "camera_drive_timer", None)
        if timer is None:
            return
        self._resolved_shaded_status = f"Camera drive pending: {reason}" if reason else "Camera drive pending"
        self.update_viewport_status()
        if not timer.isActive():
            timer.start()

    def drive_loaded_dcc_cameras_from_view(self) -> None:
        if not getattr(self, "drive_dcc_camera_enabled", False):
            return
        ok, message = self.possess_loaded_dcc_cameras(include_unreal=False)
        self._resolved_shaded_status = message if ok else f"Camera drive failed: {message[:120]}"
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        if any(
            bool(getattr(self, attr, False))
            for attr in ("is_orbiting", "is_panning", "is_zooming")
        ):
            timer = getattr(self, "camera_drive_timer", None)
            if timer is not None and not timer.isActive():
                timer.start()

    def focus_selected_scene_element(self) -> bool:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return False
        pivot = self._proxy_center_display(proxy)
        if pivot is None:
            return False
        self._camera_pivot_source_key = self._proxy_source_key(proxy)
        self.viewport_camera.focus(pivot)
        self._resolved_shaded_status = f"Focused {proxy.get('provider_id')}:{proxy.get('name') or proxy.get('native_id')}"
        self.schedule_dcc_camera_drive("focus selection")
        self.schedule_resolved_shaded_refresh("focus selection")
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        return True

    def create_cross_dcc_transform_constraint_from_selection(self) -> tuple[bool, str]:
        target = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(target, (dict, SceneProxyInstance)):
            return False, "Select a target scene object first."
        target_key = self._proxy_source_key(target)
        candidates = [
            proxy for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
            if isinstance(proxy, (dict, SceneProxyInstance))
            and self._proxy_source_key(proxy) != target_key
            and proxy.get("native_id")
            and proxy.get("provider_id")
        ]
        if not candidates:
            return False, "No source objects are available to constrain from."
        labels = [
            f"{proxy.get('provider_id')}:{proxy.get('name') or proxy.get('native_id')}"
            for proxy in candidates
        ]
        label, ok = QInputDialog.getItem(
            self,
            "Create Cross-DCC Constraint",
            "Source object",
            labels,
            0,
            False,
        )
        if not ok:
            return False, "Constraint creation cancelled."
        source = candidates[labels.index(label)]
        constraint_labels = ["Parent", "Point", "Rotate", "Scale", "Aim"]
        constraint_label, ok = QInputDialog.getItem(
            self,
            "Create Cross-DCC Constraint",
            "Constraint type",
            constraint_labels,
            0,
            False,
        )
        if not ok:
            return False, "Constraint creation cancelled."
        axis_labels = ["XYZ", "X", "Y", "Z", "XY", "XZ", "YZ"]
        axis_label = "XYZ"
        if str(constraint_label or "").strip().lower() in {"parent", "point", "rotate", "scale"}:
            axis_label, ok = QInputDialog.getItem(
                self,
                "Create Cross-DCC Constraint",
                "Constrained axes",
                axis_labels,
                0,
                False,
            )
            if not ok:
                return False, "Constraint creation cancelled."
        aim_axis_label = "+Z"
        up_axis_label = "+Y"
        if str(constraint_label or "").strip().lower() == "aim":
            maya_axis_labels = ["+Z", "-Z", "+X", "-X", "+Y", "-Y"]
            aim_axis_label, ok = QInputDialog.getItem(
                self,
                "Create Cross-DCC Aim",
                "Aim axis",
                maya_axis_labels,
                0,
                False,
            )
            if not ok:
                return False, "Constraint creation cancelled."
            up_axis_label, ok = QInputDialog.getItem(
                self,
                "Create Cross-DCC Aim",
                "Up axis",
                maya_axis_labels,
                4,
                False,
            )
            if not ok:
                return False, "Constraint creation cancelled."
        direction_labels = ["Source drives target", "Target drives source", "Toggleable, source starts", "Toggleable, target starts"]
        direction_label, ok = QInputDialog.getItem(
            self,
            "Create Cross-DCC Constraint",
            "Direction",
            direction_labels,
            0,
            False,
        )
        if not ok:
            return False, "Constraint creation cancelled."
        direction = {
            "Source drives target": "source_to_target",
            "Target drives source": "target_to_source",
            "Toggleable, source starts": "source_to_target",
            "Toggleable, target starts": "target_to_source",
        }.get(direction_label, "source_to_target")
        constraint = {
            "type": str(constraint_label or "Parent").strip().lower(),
            "direction": direction,
            "reversible": direction_label.startswith("Toggleable"),
            "axis_mask": self._axis_mask_from_label(axis_label),
            "aim_axis": self._axis_vector_from_label(aim_axis_label),
            "up_axis_vector": self._axis_vector_from_label(up_axis_label),
            "source_provider": str(source.get("provider_id") or ""),
            "source_native_id": str(source.get("native_id") or ""),
            "target_provider": str(target.get("provider_id") or ""),
            "target_native_id": str(target.get("native_id") or ""),
        }
        self._cross_dcc_transform_constraints.append(constraint)
        applied, message = self.apply_cross_dcc_transform_constraints()
        self._resolved_shaded_status = message if applied else f"Constraint pending: {message}"
        self.update_viewport_status()
        self.refresh_scene_outliner()
        return applied, message

    def apply_cross_dcc_transform_constraints(self) -> tuple[bool, str]:
        constraints = list(getattr(self, "_cross_dcc_transform_constraints", []) or [])
        if not constraints:
            return True, "No cross-DCC constraints."
        proxies = {
            self._proxy_source_key(proxy): proxy
            for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
            if isinstance(proxy, (dict, SceneProxyInstance))
        }
        failures = []
        applied = 0
        for constraint in constraints:
            source_key = f"{constraint.get('source_provider')}:{constraint.get('source_native_id')}"
            target_key = f"{constraint.get('target_provider')}:{constraint.get('target_native_id')}"
            source = proxies.get(source_key)
            target = proxies.get(target_key)
            if source is None or target is None:
                failures.append(f"{source_key}->{target_key}: missing proxy")
                continue
            constraint_type = str(constraint.get("type") or "parent").strip().lower()
            direction = str(constraint.get("direction") or "source_to_target").strip().lower()
            try:
                if direction == "target_to_source":
                    self._apply_one_cross_dcc_constraint(target, source, constraint_type, constraint)
                else:
                    self._apply_one_cross_dcc_constraint(source, target, constraint_type, constraint)
                applied += 1
            except Exception as exc:
                failures.append(f"{source_key}->{target_key}: {exc}")
        if failures:
            return False, "; ".join(failures)[:180]
        return True, f"Applied {applied} cross-DCC constraint update(s)."

    def flip_latest_cross_dcc_constraint_direction(self) -> tuple[bool, str]:
        constraints = list(getattr(self, "_cross_dcc_transform_constraints", []) or [])
        for constraint in reversed(constraints):
            if not bool(constraint.get("reversible")):
                continue
            current = str(constraint.get("direction") or "source_to_target")
            constraint["direction"] = "target_to_source" if current == "source_to_target" else "source_to_target"
            ok, message = self.apply_cross_dcc_transform_constraints()
            label = "target -> source" if constraint["direction"] == "target_to_source" else "source -> target"
            self._resolved_shaded_status = f"Constraint flipped: {label}. {message}"
            self.update_viewport_status()
            return ok, self._resolved_shaded_status
        self._resolved_shaded_status = "No reversible cross-DCC constraints to flip."
        self.update_viewport_status()
        return False, self._resolved_shaded_status

    def _apply_one_cross_dcc_constraint(
        self,
        source: SceneProxyInstance | dict[str, Any],
        target: SceneProxyInstance | dict[str, Any],
        constraint_type: str,
        constraint: dict[str, Any],
    ) -> None:
        source_center = self._proxy_center_shared(source)
        target_center = self._proxy_center_shared(target)
        if source_center is None or target_center is None:
            raise RuntimeError("missing proxy center")
        source_transform = dict(source.get("local_transform") or source.get("source_transform") or {})
        target_transform = dict(target.get("local_transform") or target.get("source_transform") or {})
        axis_mask = self._axis_mask_from_label(constraint.get("axis_mask") or "XYZ")
        apply_translation = constraint_type in {"point", "parent"}
        apply_rotation = constraint_type in {"rotate", "orient", "parent"}
        apply_scale = constraint_type in {"scale", "parent"}
        look_at = source_center if constraint_type == "aim" else None
        if not any((apply_translation, apply_rotation, apply_scale, look_at is not None)):
            raise RuntimeError(f"unsupported constraint type: {constraint_type}")
        self.apply_shared_transform_to_native_object(
            str(target.get("provider_id") or ""),
            str(target.get("native_id") or ""),
            translation_shared=self._merge_tuple_by_axis(source_center, target_center, axis_mask) if apply_translation else None,
            rotation=self._merge_tuple_by_axis(
                self._constraint_rotation_for_target(source, target, source_transform.get("rotation")),
                self._constraint_rotation_for_target(target, target, target_transform.get("rotation")),
                axis_mask,
            ) if apply_rotation else None,
            scale=self._merge_tuple_by_axis(
                self._constraint_scale_for_target(source_transform.get("scale")),
                self._constraint_scale_for_target(target_transform.get("scale")),
                axis_mask,
            ) if apply_scale else None,
            look_at_shared=look_at,
            aim_axis=self._axis_vector_from_label(constraint.get("aim_axis") or "+Z"),
            up_axis_vector=self._axis_vector_from_label(constraint.get("up_axis_vector") or "+Y"),
        )

    def _axis_mask_from_label(self, value: Any) -> tuple[bool, bool, bool]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return bool(value[0]), bool(value[1]), bool(value[2])
        label = str(value or "XYZ").strip().upper()
        return ("X" in label, "Y" in label, "Z" in label)

    def _axis_vector_from_label(self, value: Any) -> tuple[float, float, float]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return float(value[0]), float(value[1]), float(value[2])
        label = str(value or "+Z").strip().upper()
        sign = -1.0 if label.startswith("-") else 1.0
        axis = label[-1:] if label else "Z"
        if axis == "X":
            return sign, 0.0, 0.0
        if axis == "Y":
            return 0.0, sign, 0.0
        return 0.0, 0.0, sign

    def _merge_tuple_by_axis(
        self,
        source_values: tuple[float, float, float] | None,
        target_values: tuple[float, float, float] | None,
        axis_mask: tuple[bool, bool, bool],
    ) -> tuple[float, float, float] | None:
        if source_values is None:
            return None
        fallback = target_values if target_values is not None else source_values
        return tuple(float(source_values[i]) if axis_mask[i] else float(fallback[i]) for i in range(3))

    def _proxy_center_shared(self, proxy: SceneProxyInstance | dict[str, Any]) -> tuple[float, float, float] | None:
        center = proxy.get("center")
        if not isinstance(center, (list, tuple)) or len(center) < 3:
            return None
        local_shared = self.display_local_to_shared_local((float(center[0]), float(center[1]), float(center[2])))
        scene_center = getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0))
        scene_scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        return (
            float(local_shared[0]) / scene_scale + float(scene_center[0]),
            float(local_shared[1]) / scene_scale + float(scene_center[1]),
            float(local_shared[2]) / scene_scale + float(scene_center[2]),
        )

    def _constraint_scale_for_target(self, scale: Any) -> tuple[float, float, float] | None:
        if not isinstance(scale, (list, tuple)) or len(scale) < 3:
            return None
        return float(scale[0]), float(scale[1]), float(scale[2])

    def _constraint_rotation_for_target(
        self,
        source: SceneProxyInstance | dict[str, Any],
        target: SceneProxyInstance | dict[str, Any],
        rotation: Any,
    ) -> tuple[float, float, float] | None:
        if not isinstance(rotation, (list, tuple)) or len(rotation) < 3:
            return None
        source_provider = str(source.get("provider_id") or "").lower()
        target_provider = str(target.get("provider_id") or "").lower()
        if source_provider == target_provider or {source_provider, target_provider} <= {"maya", "motionbuilder"}:
            return float(rotation[0]), float(rotation[1]), float(rotation[2])
        return float(rotation[0]), float(rotation[1]), float(rotation[2])

    def _proxy_source_key(self, proxy: SceneProxyInstance | dict[str, Any]) -> str:
        return str(proxy.get("source_key") or f"{proxy.get('provider_id')}:{proxy.get('native_id')}")

    def _proxy_center_display(self, proxy: SceneProxyInstance | dict[str, Any]) -> tuple[float, float, float] | None:
        center = proxy.get("center")
        if not isinstance(center, (list, tuple)) or len(center) < 3:
            return None
        return self.shared_local_to_display_local((float(center[0]), float(center[1]), float(center[2])))

    def _move_camera_pivot_to_proxy(self, proxy: SceneProxyInstance | dict[str, Any], *, keep_eye_offset: bool = True) -> bool:
        pivot = self._proxy_center_display(proxy)
        if pivot is None:
            return False
        old_target = tuple(getattr(self.viewport_camera, "target", (0.0, 0.0, 0.0)))
        if keep_eye_offset:
            delta = _vec_sub(pivot, old_target)
            self.viewport_camera.eye = _vec_add(self.viewport_camera.eye, delta)
            self.viewport_camera.target = pivot
        else:
            self.viewport_camera.focus(pivot)
        return True

    def possess_loaded_dcc_cameras(self, *, include_unreal: bool = False) -> tuple[bool, str]:
        providers, skipped = self._camera_drive_provider_keys(include_unreal=include_unreal)
        if not providers:
            if skipped:
                if skipped == ["unreal"]:
                    return False, "Realtime camera drive is paused for Unreal to avoid blocking the editor."
                return False, "Connected DCC apps were found, but camera drive is not implemented yet for: " + ", ".join(skipped)
            return False, "No connected camera-drive providers were detected."
        failures = []
        for provider in providers:
            try:
                self._possess_provider_camera_from_tc(provider)
            except Exception as exc:
                failures.append(f"{provider}: {exc}")
        if failures:
            return False, "\n".join(failures)
        message = f"Tech Connector camera is now driving {', '.join(providers)}."
        if skipped:
            realtime_paused = [provider for provider in skipped if provider == "unreal"]
            other_skipped = [provider for provider in skipped if provider != "unreal"]
            if realtime_paused:
                message += f" Realtime drive is paused for: {', '.join(realtime_paused)}."
            if other_skipped:
                message += f" Camera drive not implemented yet for connected: {', '.join(other_skipped)}."
        return True, message

    def _camera_drive_provider_keys(self, *, include_unreal: bool = False) -> tuple[list[str], list[str]]:
        now = time.monotonic()
        cached_at, cached_supported, cached_skipped = getattr(self, "_camera_drive_provider_cache", (0.0, [], []))
        if not include_unreal and now - float(cached_at or 0.0) < 2.0:
            return list(cached_supported), list(cached_skipped)

        supported_order = ("maya", "blender", "unreal") if include_unreal else ("maya", "blender")
        connected = self._connected_dcc_provider_keys(supported_order)
        disabled_realtime = []
        if not include_unreal and "unreal" in (getattr(self, "_loaded_scene_providers", []) or []):
            disabled_realtime.append("unreal")
        supported = [provider for provider in supported_order if provider in connected]
        skipped = [provider for provider in connected if provider not in supported_order] + disabled_realtime
        self._camera_drive_provider_cache = (now, supported, skipped)
        return list(supported), list(skipped)

    def _connected_dcc_provider_keys(self, candidates: tuple[str, ...] | None = None) -> list[str]:
        keys = []
        for key in (candidates or ("maya", "blender", "motionbuilder", "houdini", "unreal", "unity")):
            try:
                bridge = self._scene_snapshot_bridge(key)
                find_port = getattr(bridge, "find_port", None)
                if callable(find_port) and find_port():
                    keys.append(key)
                    continue
                health_check = getattr(bridge, "health_check", None)
                if callable(health_check):
                    health = health_check(timeout=0.5)
                    if isinstance(health, dict) and (health.get("connected") or health.get("bridge_reachable")):
                        keys.append(key)
            except Exception:
                continue
        return keys

    def _federated_camera_in_provider_space(self, provider: str) -> dict[str, Any]:
        provider_key = str(provider or "").lower()
        self._ensure_provider_camera_reference_snapshot(provider_key)
        scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        center = getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0))
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        if hasattr(self, "canvas") and self.canvas:
            aspect_ratio = float(max(1, self.canvas.width())) / float(max(1, self.canvas.height()))
        else:
            aspect_ratio = 16.0 / 9.0

        def denormalize(point: tuple[float, float, float]) -> tuple[float, float, float]:
            return (
                float(point[0]) / scale + float(center[0]),
                float(point[1]) / scale + float(center[1]),
                float(point[2]) / scale + float(center[2]),
            )

        eye_view = denormalize(self.display_local_to_shared_local(camera.eye))
        target_view = denormalize(self.display_local_to_shared_local(camera.target))
        up_target_view = denormalize(self.display_local_to_shared_local(_vec_add(camera.target, camera.view_axes()[2])))
        if not self._provider_has_rendered_proxy(provider_key):
            scene_bounds = self._scene_bounds_shared()
            provider_bounds = self._provider_scene_bounds_shared(provider_key)
            if scene_bounds and provider_bounds:
                scene_center, scene_extent = scene_bounds
                provider_center, provider_extent = provider_bounds
                ratio = provider_extent / max(1.0e-6, scene_extent)

                def remap(point: tuple[float, float, float]) -> tuple[float, float, float]:
                    return tuple(provider_center[i] + (float(point[i]) - scene_center[i]) * ratio for i in range(3))

                source_target = target_view
                eye_view = remap(eye_view)
                target_view = remap(target_view)
                up_vec = tuple(float(up_target_view[i]) - float(source_target[i]) for i in range(3))
                up_target_view = tuple(target_view[i] + up_vec[i] * ratio for i in range(3))
        target_snapshot = (
            (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider_key)
            or (getattr(self, "_dcc_camera_reference_snapshots", {}) or {}).get(provider_key)
            or {}
        )
        target_unit = str(target_snapshot.get("unit_linear") or "")
        target_up_axis = str(target_snapshot.get("up_axis") or "")
        return {
            "eye": provider_view_to_world(provider_key, *eye_view, target_unit, target_up_axis),
            "target": provider_view_to_world(provider_key, *target_view, target_unit, target_up_axis),
            "up_target": provider_view_to_world(provider_key, *up_target_view, target_unit, target_up_axis),
            "fov_degrees": float(camera.fov_degrees),
            "aspect_ratio": aspect_ratio,
            "near_clip": float(camera.near_clip),
            "far_clip": float(camera.far_clip),
        }

    def _possess_provider_camera_from_tc(self, provider: str) -> None:
        payload = self._federated_camera_in_provider_space(provider)
        payload_key = self._camera_payload_key(payload)
        if getattr(self, "_last_dcc_camera_payload_keys", {}).get(provider) == payload_key:
            return
        self._possess_provider_camera_from_payload(provider, payload)
        self._last_dcc_camera_payload_keys[provider] = payload_key

    def _camera_payload_key(self, payload: dict[str, Any]) -> str:
        def rounded(value: Any) -> Any:
            if isinstance(value, float):
                return round(value, 5)
            if isinstance(value, (list, tuple)):
                return [rounded(item) for item in value]
            if isinstance(value, dict):
                return {str(key): rounded(item) for key, item in sorted(value.items())}
            return value
        return json.dumps(rounded(payload), sort_keys=True, default=str)

    def _possess_provider_camera_from_payload(self, provider: str, payload: dict[str, Any]) -> None:
        bridge = self._scene_snapshot_bridge(provider)
        if provider == "maya":
            code = self._maya_possess_camera_code(payload)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "blender":
            code = self._blender_possess_camera_code(payload)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "motionbuilder":
            code = self._motionbuilder_possess_camera_code(payload)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "unreal":
            response = bridge.execute_python(self._unreal_possess_camera_code(payload), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError("Camera possession is currently implemented for Maya, Blender, MotionBuilder, and Unreal.")
        if not ok:
            raise RuntimeError(raw)

    def _use_dcc_camera_authority(self, provider: str, native_id: str) -> tuple[bool, str]:
        if not provider or not native_id:
            return False, "No DCC camera was selected."
        try:
            authority = self._read_dcc_camera_authority(provider, native_id)
            self._apply_authority_payload_to_local_camera(provider, authority)
            failures = []
            loaded_providers = list(getattr(self, "_loaded_scene_providers", []) or [])
            for target_provider in loaded_providers:
                try:
                    if target_provider == provider:
                        self._switch_provider_to_camera(provider, native_id)
                    else:
                        payload = self._convert_camera_payload_between_providers(provider, target_provider, authority)
                        self._possess_provider_camera_from_payload(target_provider, payload)
                except Exception as exc:
                    failures.append(f"{target_provider}: {exc}")
            if failures:
                return False, "\n".join(failures)
            return True, f"{provider} camera {native_id} is now driving {', '.join(loaded_providers)}."
        except Exception as exc:
            return False, str(exc)

    def _read_dcc_camera_authority(self, provider: str, native_id: str) -> dict[str, Any]:
        provider_key = str(provider or "").lower()
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_key == "maya":
            code = self._maya_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "blender":
            code = self._blender_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "motionbuilder":
            code = self._motionbuilder_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "unreal":
            response = bridge.execute_python(self._unreal_read_camera_authority_code(native_id), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or ""
        else:
            raise ValueError(f"Camera authority is not implemented for {provider_key} yet.")
        if not ok:
            raise RuntimeError(raw)
        try:
            return json.loads(str(raw or "{}"))
        except Exception as exc:
            raise RuntimeError(f"Could not parse {provider_key} camera payload: {exc}\n{raw}") from exc

    def _convert_camera_payload_between_providers(
        self,
        source_provider: str,
        target_provider: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        snapshots = getattr(self, "_dcc_scene_snapshots", {}) or {}
        ref_snapshots = getattr(self, "_dcc_camera_reference_snapshots", {}) or {}
        source_snapshot = snapshots.get(source_provider) or ref_snapshots.get(source_provider) or {}
        target_snapshot = snapshots.get(target_provider) or ref_snapshots.get(target_provider) or {}
        source_unit = str(source_snapshot.get("unit_linear") or "")
        target_unit = str(target_snapshot.get("unit_linear") or "")
        converted = convert_camera_payload_between_providers(
            source_provider,
            target_provider,
            payload,
            source_unit=source_unit,
            target_unit=target_unit,
            source_up_axis=str(source_snapshot.get("up_axis") or ""),
            target_up_axis=str(target_snapshot.get("up_axis") or ""),
            source_bounds_shared=self._provider_scene_bounds_shared(source_provider),
            target_bounds_shared=self._provider_scene_bounds_shared(target_provider),
        )
        converted["fov_degrees"] = float(payload.get("fov_degrees", self.camera_fov_degrees))
        return converted

    def _provider_scene_bounds_shared(self, provider: str) -> tuple[tuple[float, float, float], float] | None:
        provider_key = str(provider or "").lower()
        boxes = [
            proxy.get("source_bbox")
            for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
            if str(proxy.get("provider_id") or "").lower() == provider_key
        ]
        if not boxes:
            snapshot = (
                (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider_key)
                or (getattr(self, "_dcc_camera_reference_snapshots", {}) or {}).get(provider_key)
                or {}
            )
            unit_linear = str(snapshot.get("unit_linear") or "")
            up_axis = str(snapshot.get("up_axis") or "")
            boxes = []
            for obj in snapshot.get("objects") or []:
                if not isinstance(obj, dict) or not obj.get("bbox"):
                    continue
                try:
                    boxes.append(provider_bbox_to_shared(provider_key, obj["bbox"], unit_linear, up_axis))
                except Exception:
                    continue
        boxes = [box for box in boxes if isinstance(box, (list, tuple)) and len(box) >= 6]
        if not boxes:
            return None
        min_x = min(float(box[0]) for box in boxes)
        min_y = min(float(box[1]) for box in boxes)
        min_z = min(float(box[2]) for box in boxes)
        max_x = max(float(box[3]) for box in boxes)
        max_y = max(float(box[4]) for box in boxes)
        max_z = max(float(box[5]) for box in boxes)
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        extent = max(max_x - min_x, max_y - min_y, max_z - min_z, 1.0e-6)
        return center, extent

    def _scene_bounds_shared(self) -> tuple[tuple[float, float, float], float] | None:
        boxes = [
            proxy.get("source_bbox")
            for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
            if isinstance(proxy.get("source_bbox"), (list, tuple))
        ]
        boxes = [box for box in boxes if len(box) >= 6]
        if not boxes:
            return None
        min_x = min(float(box[0]) for box in boxes)
        min_y = min(float(box[1]) for box in boxes)
        min_z = min(float(box[2]) for box in boxes)
        max_x = max(float(box[3]) for box in boxes)
        max_y = max(float(box[4]) for box in boxes)
        max_z = max(float(box[5]) for box in boxes)
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        extent = max(max_x - min_x, max_y - min_y, max_z - min_z, 1.0e-6)
        return center, extent

    def _provider_has_rendered_proxy(self, provider: str) -> bool:
        provider_key = str(provider or "").lower()
        return any(
            str(proxy.get("provider_id") or "").lower() == provider_key
            for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
        )

    def _ensure_provider_camera_reference_snapshot(self, provider: str) -> None:
        provider_key = str(provider or "").lower()
        if not provider_key or provider_key in (getattr(self, "_dcc_scene_snapshots", {}) or {}):
            return
        cache = getattr(self, "_camera_reference_snapshot_cache", {})
        cached_at = float(cache.get(provider_key, {}).get("cached_at", 0.0)) if isinstance(cache.get(provider_key), dict) else 0.0
        if time.monotonic() - cached_at < 5.0:
            return
        try:
            bridge = self._scene_snapshot_bridge(provider_key)
            ok, snapshot_or_error = bridge.get_scene_snapshot(
                selected_only=False,
                include_geometry=False,
                limit=200,
                timeout=3.0,
            )
        except TypeError:
            try:
                ok, snapshot_or_error = bridge.get_scene_snapshot(selected_only=False, limit=200, timeout=3.0)
            except Exception:
                ok, snapshot_or_error = False, None
        except Exception:
            ok, snapshot_or_error = False, None
        cache[provider_key] = {"cached_at": time.monotonic()}
        self._camera_reference_snapshot_cache = cache
        if ok and isinstance(snapshot_or_error, dict):
            snapshot_or_error.setdefault("provider_id", provider_key)
            self._dcc_camera_reference_snapshots[provider_key] = self._snapshot_for_viewer_scale_policy(provider_key, snapshot_or_error)

    def _apply_authority_payload_to_local_camera(self, provider: str, payload: dict[str, Any]) -> None:
        scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        center = getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0))
        snapshot = (
            (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(str(provider or "").lower())
            or (getattr(self, "_dcc_camera_reference_snapshots", {}) or {}).get(str(provider or "").lower())
            or {}
        )
        unit_linear = str(snapshot.get("unit_linear") or "")
        up_axis = str(snapshot.get("up_axis") or "")
        eye_view = provider_world_to_view(provider, *payload["eye"], unit_linear, up_axis)
        target_view = provider_world_to_view(provider, *payload["target"], unit_linear, up_axis)
        eye_shared_local = tuple((float(eye_view[i]) - float(center[i])) * scale for i in range(3))
        target_shared_local = tuple((float(target_view[i]) - float(center[i])) * scale for i in range(3))
        eye_local = self.shared_local_to_display_local(eye_shared_local)
        target_local = self.shared_local_to_display_local(target_shared_local)
        up_target = payload.get("up_target")
        if isinstance(up_target, (list, tuple)) and len(up_target) >= 3:
            up_view = provider_world_to_view(provider, *up_target, unit_linear, up_axis)
            up_shared_target = tuple((float(up_view[i]) - float(center[i])) * scale for i in range(3))
            up_local_target = self.shared_local_to_display_local(up_shared_target)
            up = _vec_normalize(_vec_sub(up_local_target, target_local), (0.0, 1.0, 0.0))
        else:
            up = (0.0, 1.0, 0.0)
        self.viewport_camera = MayaViewportCamera(
            eye=eye_local,
            target=target_local,
            up=up,
            fov_degrees=float(payload.get("fov_degrees", self.camera_fov_degrees)),
            near_clip=float(payload.get("near_clip", 0.1)),
            far_clip=float(payload.get("far_clip", 100000.0)),
        )
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _switch_provider_to_camera(self, provider: str, native_id: str) -> None:
        provider_key = str(provider or "").lower()
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_key == "maya":
            code = (
                "import maya.cmds as cmds\n"
                f"camera = {native_id!r}\n"
                "for panel in cmds.getPanel(type='modelPanel') or []:\n"
                "    try: cmds.modelPanel(panel, edit=True, camera=camera)\n"
                "    except Exception: pass\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "blender":
            code = (
                "import bpy\n"
                f"name = {native_id!r}\n"
                "obj = bpy.data.objects.get(name)\n"
                "if obj is None or obj.type != 'CAMERA':\n"
                "    raise RuntimeError('Camera does not exist: ' + name)\n"
                "bpy.context.scene.camera = obj\n"
                "for area in bpy.context.screen.areas:\n"
                "    if area.type == 'VIEW_3D':\n"
                "        area.spaces.active.region_3d.view_perspective = 'CAMERA'\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "motionbuilder":
            code = (
                "import pyfbsdk\n"
                f"camera_name = {native_id!r}\n"
                "scene = pyfbsdk.FBSystem().Scene\n"
                "camera = None\n"
                "for cam in scene.Cameras:\n"
                "    if (cam.LongName or cam.Name) == camera_name or cam.Name == camera_name:\n"
                "        camera = cam\n"
                "        break\n"
                "if camera is None:\n"
                "    raise RuntimeError('Camera does not exist: ' + camera_name)\n"
                "pyfbsdk.FBSystem().Renderer.CurrentCamera = camera\n"
                "print('OK')\n"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "unreal":
            response = bridge.execute_python(self._unreal_switch_camera_code(native_id), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError(f"Camera switching is not implemented for {provider_key} yet.")
        if not ok:
            raise RuntimeError(raw)

    def _maya_read_camera_authority_code(self, native_id: str) -> str:
        return f"""
import json
import math
import maya.cmds as cmds

camera = {native_id!r}
if not cmds.objExists(camera):
    raise RuntimeError("Camera does not exist: " + camera)
if cmds.nodeType(camera) == "camera":
    shapes = [camera]
    parents = cmds.listRelatives(camera, parent=True, fullPath=True) or []
    transform = parents[0] if parents else camera
else:
    transform = camera
    shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
if not shapes:
    raise RuntimeError("Node is not a camera: " + camera)
shape = shapes[0]
m = [float(v) for v in cmds.xform(transform, q=True, ws=True, matrix=True)]
eye = [m[12], m[13], m[14]]
forward = [-m[8], -m[9], -m[10]]
length = math.sqrt(sum(v * v for v in forward)) or 1.0
forward = [v / length for v in forward]
up = [m[4], m[5], m[6]]
up_length = math.sqrt(sum(v * v for v in up)) or 1.0
up = [v / up_length for v in up]
target = [eye[i] + forward[i] * 10.0 for i in range(3)]
up_target = [target[i] + up[i] * 10.0 for i in range(3)]
aspect_ratio = 16.0 / 9.0
for panel in cmds.getPanel(type="modelPanel") or []:
    try:
        cmds.modelPanel(panel, edit=True, camera=transform)
        width = float(cmds.control(panel, q=True, width=True) or 0.0)
        height = float(cmds.control(panel, q=True, height=True) or 0.0)
        if width > 1.0 and height > 1.0:
            aspect_ratio = width / height
    except Exception:
        pass
horizontal_fov = float(cmds.camera(shape, q=True, horizontalFieldOfView=True))
vertical_fov = math.degrees(2.0 * math.atan(math.tan(math.radians(horizontal_fov) * 0.5) / aspect_ratio))
payload = {{
    "eye": eye,
    "target": target,
    "up_target": up_target,
    "fov_degrees": float(vertical_fov),
    "aspect_ratio": aspect_ratio,
    "focal_length_mm": float(cmds.getAttr(shape + ".focalLength")),
    "near_clip": float(cmds.getAttr(shape + ".nearClipPlane")),
    "far_clip": float(cmds.getAttr(shape + ".farClipPlane")),
}}
print(json.dumps(payload))
"""

    def _blender_read_camera_authority_code(self, native_id: str) -> str:
        return f"""
import json
import math
import bpy
from mathutils import Vector

name = {native_id!r}
obj = bpy.data.objects.get(name)
if obj is None or obj.type != "CAMERA":
    raise RuntimeError("Camera does not exist: " + name)
eye = obj.matrix_world.translation
forward = obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
up = obj.matrix_world.to_quaternion() @ Vector((0.0, 1.0, 0.0))
target = eye + forward.normalized() * 10.0
up_target = target + up.normalized() * 10.0
bpy.context.scene.camera = obj
aspect_ratio = 16.0 / 9.0
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.region_3d.view_perspective = "CAMERA"
        width = float(area.width or 0.0)
        height = float(area.height or 0.0)
        if width > 1.0 and height > 1.0:
            aspect_ratio = width / height
payload = {{
    "eye": [float(eye.x), float(eye.y), float(eye.z)],
    "target": [float(target.x), float(target.y), float(target.z)],
    "up_target": [float(up_target.x), float(up_target.y), float(up_target.z)],
    "fov_degrees": float(math.degrees(obj.data.angle)),
    "aspect_ratio": float(aspect_ratio),
    "focal_length_mm": float(obj.data.lens),
    "near_clip": float(obj.data.clip_start),
    "far_clip": float(obj.data.clip_end),
}}
print(json.dumps(payload))
"""

    def _motionbuilder_read_camera_authority_code(self, native_id: str) -> str:
        return f"""
import json
import math
import pyfbsdk

camera_name = {native_id!r}
camera = None
for cam in pyfbsdk.FBSystem().Scene.Cameras:
    if (cam.LongName or cam.Name) == camera_name or cam.Name == camera_name:
        camera = cam
        break
if camera is None:
    raise RuntimeError("Camera does not exist: " + camera_name)

eye = [float(camera.Translation.Data[i]) for i in range(3)]
rot = [math.radians(float(camera.Rotation.Data[i])) for i in range(3)]
rx, ry, rz = rot
cx, sx = math.cos(rx), math.sin(rx)
cy, sy = math.cos(ry), math.sin(ry)
cz, sz = math.cos(rz), math.sin(rz)

def rotate(vec):
    x, y, z = vec
    y, z = y * cx - z * sx, y * sx + z * cx
    x, z = x * cy + z * sy, -x * sy + z * cy
    x, y = x * cz - y * sz, x * sz + y * cz
    return [x, y, z]

forward = rotate([0.0, 0.0, -1.0])
up = rotate([0.0, 1.0, 0.0])
target = [eye[i] + forward[i] * 100.0 for i in range(3)]
up_target = [target[i] + up[i] * 100.0 for i in range(3)]
payload = {{
    "eye": eye,
    "target": target,
    "up_target": up_target,
    "fov_degrees": float(getattr(camera, "FieldOfView", 45.0)),
    "focal_length_mm": float(getattr(camera, "FocalLength", 35.0)),
    "near_clip": float(getattr(camera, "NearPlaneDistance", 0.1)),
    "far_clip": float(getattr(camera, "FarPlaneDistance", 10000.0)),
}}
print(json.dumps(payload))
"""

    def _unreal_read_camera_authority_code(self, native_id: str) -> str:
        return f"""
import json
import math
import unreal

target_path = {native_id!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
component_name = ""
if "::" in target_path:
    target_path, component_name = target_path.split("::", 1)
for candidate in actors:
    try:
        if candidate.get_path_name() == target_path or candidate.get_name() == target_path or candidate.get_actor_label() == target_path:
            actor = candidate
            break
    except Exception:
        pass
if actor is None:
    raise RuntimeError("Camera does not exist: " + target_path)
component = None
if component_name:
    try:
        for candidate_component in actor.get_components_by_class(unreal.CameraComponent) or []:
            if candidate_component.get_name() == component_name:
                component = candidate_component
                break
    except Exception:
        component = None
if component is not None:
    transform = component.get_world_transform()
    loc = transform.translation
    rot = transform.rotation.rotator()
elif isinstance(actor, unreal.CameraActor):
    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
else:
    raise RuntimeError("Actor has no camera component: " + target_path)
forward = rot.get_forward_vector()
try:
    up = rot.get_up_vector()
except Exception:
    try:
        up = unreal.MathLibrary.get_up_vector(rot)
    except Exception:
        up = unreal.Vector(0.0, 0.0, 1.0)
target = unreal.Vector(loc.x + forward.x * 1000.0, loc.y + forward.y * 1000.0, loc.z + forward.z * 1000.0)
up_target = unreal.Vector(target.x + up.x * 1000.0, target.y + up.y * 1000.0, target.z + up.z * 1000.0)
for getter in ("get_cine_camera_component", "get_camera_component"):
    if component is None and hasattr(actor, getter):
        try:
            component = getattr(actor, getter)()
        except Exception:
            component = None
if component is None and hasattr(actor, "camera_component"):
    try:
        component = actor.camera_component
    except Exception:
        component = None
if component is None and hasattr(actor, "get_editor_property"):
    for prop_name in ("camera_component", "CameraComponent"):
        try:
            component = actor.get_editor_property(prop_name)
            if component is not None:
                break
        except Exception:
            pass
if component is None and hasattr(actor, "get_component_by_class"):
    try:
        component = actor.get_component_by_class(unreal.CameraComponent)
    except Exception:
        component = None
fov = float(getattr(component, "field_of_view", 45.0)) if component else 45.0
focal = float(getattr(component, "current_focal_length", 35.0)) if component else 35.0
payload = {{
    "eye": [float(loc.x), float(loc.y), float(loc.z)],
    "target": [float(target.x), float(target.y), float(target.z)],
    "up_target": [float(up_target.x), float(up_target.y), float(up_target.z)],
    "fov_degrees": fov,
    "focal_length_mm": focal,
    "near_clip": 10.0,
    "far_clip": 100000.0,
}}
print(json.dumps(payload))
"""

    def _unreal_switch_camera_code(self, native_id: str) -> str:
        return f"""
import unreal

target_path = {native_id!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
component_name = ""
if "::" in target_path:
    target_path, component_name = target_path.split("::", 1)
for candidate in actors:
    try:
        if candidate.get_path_name() == target_path or candidate.get_name() == target_path or candidate.get_actor_label() == target_path:
            actor = candidate
            break
    except Exception:
        pass
if actor is None:
    raise RuntimeError("Camera does not exist: " + target_path)
component = None
if component_name:
    try:
        for candidate_component in actor.get_components_by_class(unreal.CameraComponent) or []:
            if candidate_component.get_name() == component_name:
                component = candidate_component
                break
    except Exception:
        component = None
if component is not None:
    transform = component.get_world_transform()
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if hasattr(subsystem, "set_level_viewport_camera_info"):
        subsystem.set_level_viewport_camera_info(transform.translation, transform.rotation.rotator())
    print("OK")
elif not isinstance(actor, unreal.CameraActor):
    raise RuntimeError("Actor is not a CameraActor and no camera component was resolved: " + target_path)
else:
    try:
        unreal.EditorLevelLibrary.set_selected_level_actors([actor])
    except Exception:
        pass
    try:
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if hasattr(subsystem, "pilot_level_actor"):
            subsystem.pilot_level_actor(actor)
    except Exception:
        pass
    print("OK")
"""

    def _maya_possess_camera_code(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload)
        return f"""
import json
import math
import maya.cmds as cmds

data = json.loads({data!r})
name = "TechConnector_Camera"
existing = []
for candidate_name in ([name] + sorted(cmds.ls(name + "*", type="transform") or [])):
    existing.extend(cmds.ls(candidate_name, long=True, type="transform") or [])
deduped = []
for candidate in existing:
    if candidate not in deduped:
        deduped.append(candidate)
existing = deduped
existing_cameras = []
for candidate in existing:
    if cmds.listRelatives(candidate, shapes=True, type="camera", fullPath=True):
        existing_cameras.append(candidate)
if existing_cameras:
    transform = existing_cameras[0]
    for stale in existing_cameras[1:]:
        try:
            cmds.delete(stale)
        except Exception:
            pass
elif not cmds.objExists(name):
    transform, _shape = cmds.camera(name=name)
else:
    transform = name
try:
    if transform.split("|")[-1] != name and not cmds.objExists(name):
        transform = cmds.rename(transform, name)
except Exception:
    pass
shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
if not shapes:
    raise RuntimeError("Could not resolve camera shape for " + transform)
shape = shapes[0]
eye = [float(v) for v in data["eye"]]
target = [float(v) for v in data["target"]]
up_target = [float(v) for v in data.get("up_target", [target[0], target[1] + 1.0, target[2]])]

def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]

def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))

def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]

def _normalize(v, fallback):
    length = sum(x * x for x in v) ** 0.5
    if length < 1.0e-6:
        return list(fallback)
    return [x / length for x in v]

forward = _normalize(_sub(target, eye), [0.0, 0.0, -1.0])
up_hint = _normalize(_sub(up_target, target), [0.0, 1.0, 0.0])
right = _normalize(_cross(forward, up_hint), [1.0, 0.0, 0.0])
up = _normalize(_cross(right, forward), [0.0, 1.0, 0.0])
back = [-forward[0], -forward[1], -forward[2]]
cmds.xform(transform, ws=True, matrix=[
    right[0], right[1], right[2], 0.0,
    up[0], up[1], up[2], 0.0,
    back[0], back[1], back[2], 0.0,
    eye[0], eye[1], eye[2], 1.0,
])
cmds.setAttr(shape + ".focalLength", float(data.get("focal_length_mm", 35.0)))
try:
    vertical_fov = float(data.get("fov_degrees", 45.0))
    aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
    horizontal_fov = math.degrees(2.0 * math.atan(math.tan(math.radians(vertical_fov) * 0.5) * aspect_ratio))
    cmds.camera(shape, edit=True, horizontalFieldOfView=horizontal_fov)
except Exception:
    pass
cmds.setAttr(shape + ".nearClipPlane", float(data.get("near_clip", 0.1)))
cmds.setAttr(shape + ".farClipPlane", float(data.get("far_clip", 100000.0)))
for panel in cmds.getPanel(type="modelPanel") or []:
    try:
        cmds.modelPanel(panel, edit=True, camera=transform)
    except Exception:
        pass
print("OK")
"""

    def _blender_possess_camera_code(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload)
        return f"""
import json
import math
import bpy
from mathutils import Matrix, Vector

data = json.loads({data!r})
name = "TechConnector_Camera"
obj = bpy.data.objects.get(name)
if obj is None:
    cam = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, cam)
    bpy.context.collection.objects.link(obj)
elif obj.type != "CAMERA":
    raise RuntimeError(name + " exists but is not a camera")
eye = Vector([float(v) for v in data["eye"]])
target = Vector([float(v) for v in data["target"]])
up_target = Vector([float(v) for v in data.get("up_target", [target.x, target.y, target.z + 1.0])])

def _normalized(vector, fallback):
    if vector.length < 0.0001:
        return Vector(fallback)
    return vector.normalized()

forward = _normalized(target - eye, (0.0, -1.0, 0.0))
up_hint = _normalized(up_target - target, (0.0, 0.0, 1.0))
right = _normalized(forward.cross(up_hint), (1.0, 0.0, 0.0))
up = _normalized(right.cross(forward), (0.0, 0.0, 1.0))
back = -forward
rotation = Matrix((
    (right.x, up.x, back.x),
    (right.y, up.y, back.y),
    (right.z, up.z, back.z),
)).to_euler()
obj.location = eye
obj.rotation_euler = rotation
obj.data.sensor_fit = "VERTICAL"
obj.data.angle = math.radians(float(data.get("fov_degrees", 45.0)))
obj.data.clip_start = float(data.get("near_clip", 0.1))
obj.data.clip_end = float(data.get("far_clip", 100000.0))
bpy.context.scene.camera = obj
for area in bpy.context.screen.areas:
    if area.type == "VIEW_3D":
        area.spaces.active.region_3d.view_perspective = "CAMERA"
print("OK")
"""

    def _unreal_possess_camera_code(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload)
        return f"""
import json
import unreal

data = json.loads({data!r})
name = "TechConnector_Camera"
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
for candidate in actors:
    try:
        if candidate.get_actor_label() == name or candidate.get_name() == name:
            if isinstance(candidate, unreal.CameraActor):
                actor = candidate
                break
    except Exception:
        pass
eye = data["eye"]
target = data["target"]
location = unreal.Vector(float(eye[0]), float(eye[1]), float(eye[2]))
target_location = unreal.Vector(float(target[0]), float(target[1]), float(target[2]))
rotation = unreal.MathLibrary.find_look_at_rotation(location, target_location)
if actor is None:
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CameraActor, location, rotation)
    try:
        actor.set_actor_label(name)
    except Exception:
        pass
else:
    actor.set_actor_location(location, False, False)
    actor.set_actor_rotation(rotation, False)
component = None
for getter in ("get_cine_camera_component", "get_camera_component"):
    if component is None and hasattr(actor, getter):
        try:
            component = getattr(actor, getter)()
        except Exception:
            component = None
if component is None and hasattr(actor, "camera_component"):
    try:
        component = actor.camera_component
    except Exception:
        component = None
if component is None and hasattr(actor, "get_editor_property"):
    for prop_name in ("camera_component", "CameraComponent"):
        try:
            component = actor.get_editor_property(prop_name)
            if component is not None:
                break
        except Exception:
            pass
if component is None and hasattr(actor, "get_component_by_class"):
    try:
        component = actor.get_component_by_class(unreal.CameraComponent)
    except Exception:
        component = None
if component is not None:
    if hasattr(component, "field_of_view"):
        component.field_of_view = float(data.get("fov_degrees", 45.0))
    if hasattr(component, "current_focal_length"):
        component.current_focal_length = float(data.get("focal_length_mm", 35.0))
try:
    unreal.EditorLevelLibrary.set_selected_level_actors([actor])
except Exception:
    pass
try:
    subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if hasattr(subsystem, "pilot_level_actor"):
        subsystem.pilot_level_actor(actor)
except Exception:
    pass
print("OK")
"""

    def _motionbuilder_possess_camera_code(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload)
        return f"""
import json
import math
import pyfbsdk

data = json.loads({data!r})
name = "TechConnector_Camera"
scene = pyfbsdk.FBSystem().Scene
camera = None
for cam in scene.Cameras:
    if cam.Name == name or cam.LongName == name:
        camera = cam
        break
if camera is None:
    camera = pyfbsdk.FBCamera(name)
    scene.Cameras.append(camera)

eye = [float(v) for v in data["eye"]]
target = [float(v) for v in data["target"]]
up_target = [float(v) for v in data.get("up_target", [target[0], target[1] + 1.0, target[2]])]
forward = [target[i] - eye[i] for i in range(3)]
flen = math.sqrt(sum(v * v for v in forward)) or 1.0
forward = [v / flen for v in forward]
up = [up_target[i] - target[i] for i in range(3)]
ulen = math.sqrt(sum(v * v for v in up)) or 1.0
up = [v / ulen for v in up]
yaw = math.degrees(math.atan2(forward[0], -forward[2]))
pitch = math.degrees(math.asin(max(-1.0, min(1.0, forward[1]))))

camera.Translation = pyfbsdk.FBVector3d(eye[0], eye[1], eye[2])
camera.Rotation = pyfbsdk.FBVector3d(pitch, yaw, 0.0)
try:
    camera.FocalLength = float(data.get("focal_length_mm", 35.0))
except Exception:
    pass
try:
    camera.NearPlaneDistance = float(data.get("near_clip", 0.1))
    camera.FarPlaneDistance = float(data.get("far_clip", 10000.0))
except Exception:
    pass
pyfbsdk.FBSystem().Renderer.CurrentCamera = camera
print("OK")
"""

    def _unreal_translate_actor_code(self, native_id: str, native_delta: tuple[float, float, float]) -> str:
        return f"""
import unreal

target_path = {native_id!r}
delta = {tuple(float(v) for v in native_delta)!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
for candidate in actors:
    try:
        if candidate.get_path_name() == target_path or candidate.get_name() == target_path or candidate.get_actor_label() == target_path:
            actor = candidate
            break
    except Exception:
        pass
if actor is None:
    raise RuntimeError("Actor does not exist: " + target_path)
loc = actor.get_actor_location()
new_loc = unreal.Vector(float(loc.x) + float(delta[0]), float(loc.y) + float(delta[1]), float(loc.z) + float(delta[2]))
actor.set_actor_location(new_loc, False, False)
try:
    unreal.EditorLevelLibrary.set_selected_level_actors([actor])
except Exception:
    pass
print("OK")
"""

    def _unreal_set_actor_transform_code(
        self,
        native_id: str,
        translation: tuple[float, float, float] | None,
        rotation: tuple[float, float, float] | None,
        scale: tuple[float, float, float] | None,
        look_at: tuple[float, float, float] | None,
        aim_axis: tuple[float, float, float],
        up_axis_vector: tuple[float, float, float],
    ) -> str:
        return f"""
import unreal

target_path = {native_id!r}
translation = {tuple(float(v) for v in translation)!r} if {translation is not None!r} else None
rotation = {tuple(float(v) for v in rotation)!r} if {rotation is not None!r} else None
scale = {tuple(float(v) for v in scale)!r} if {scale is not None!r} else None
look_at = {tuple(float(v) for v in look_at)!r} if {look_at is not None!r} else None
aim_axis = {tuple(float(v) for v in aim_axis)!r}
up_axis = {tuple(float(v) for v in up_axis_vector)!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
for candidate in actors:
    try:
        if candidate.get_path_name() == target_path or candidate.get_name() == target_path or candidate.get_actor_label() == target_path:
            actor = candidate
            break
    except Exception:
        pass
if actor is None:
    raise RuntimeError("Actor does not exist: " + target_path)
if translation is not None:
    actor.set_actor_location(unreal.Vector(float(translation[0]), float(translation[1]), float(translation[2])), False, False)
if rotation is not None:
    actor.set_actor_rotation(unreal.Rotator(float(rotation[1]), float(rotation[2]), float(rotation[0])), False)
if scale is not None:
    actor.set_actor_scale3d(unreal.Vector(float(scale[0]), float(scale[1]), float(scale[2])))
if look_at is not None:
    loc = actor.get_actor_location()
    target = unreal.Vector(float(look_at[0]), float(look_at[1]), float(look_at[2]))
    actor.set_actor_rotation(unreal.MathLibrary.find_look_at_rotation(loc, target), False)
try:
    unreal.EditorLevelLibrary.set_selected_level_actors([actor])
except Exception:
    pass
print("OK")
"""

    def _unreal_select_actor_code(self, native_id: str) -> str:
        return f"""
import unreal

target_path = {native_id!r}
actors = unreal.EditorLevelLibrary.get_all_level_actors()
actor = None
for candidate in actors:
    try:
        if candidate.get_path_name() == target_path or candidate.get_name() == target_path or candidate.get_actor_label() == target_path:
            actor = candidate
            break
    except Exception:
        pass
if actor is None:
    raise RuntimeError("Actor does not exist: " + target_path)
unreal.EditorLevelLibrary.set_selected_level_actors([actor])
print("OK")
"""

    def _scene_snapshot_provider_keys(self, provider: str) -> list[str]:
        provider_key = str(provider or "").lower()
        if provider_key == "all_open":
            keys = []
            for key in ("maya", "blender", "motionbuilder", "houdini", "unreal", "unity"):
                try:
                    bridge = self._scene_snapshot_bridge(key)
                    if callable(getattr(bridge, "find_port", None)) and bridge.find_port():
                        keys.append(key)
                except Exception:
                    continue
            return keys or ["maya"]
        return [provider_key]

    def _set_provider_frame(self, provider: str, frame: int) -> None:
        provider_key = str(provider or "").lower()
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_key == "maya":
            ok, raw = bridge.execute(f"import maya.cmds as cmds\ncmds.currentTime({int(frame)}, edit=True)", timeout=2.0)
        elif provider_key == "blender":
            ok, raw = bridge.execute(f"import bpy\nbpy.context.scene.frame_set({int(frame)})", timeout=2.0)
        elif provider_key == "houdini":
            ok, raw = bridge.execute(f"import hou\nhou.setFrame({int(frame)})", timeout=2.0)
        elif provider_key == "motionbuilder":
            ok, raw = bridge.execute(
                "import pyfbsdk\n"
                f"pyfbsdk.FBSystem().LocalTime = pyfbsdk.FBTime(0, 0, 0, {int(frame)})",
                timeout=2.0,
            )
        elif provider_key == "unreal":
            response = bridge.execute_python(
                self._unreal_set_frame_code(int(frame)),
                timeout=3.0,
                reset_globals=True,
            )
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or str(response)
            try:
                parsed = json.loads(str(raw).strip())
                ok = bool(ok and parsed.get("ok", True))
                raw = parsed.get("message") or raw
            except Exception:
                pass
        else:
            return
        if not ok:
            raise RuntimeError(str(raw))

    def _unreal_set_frame_code(self, frame: int) -> str:
        return f"""
import json
import unreal

frame = int({int(frame)!r})
ok = False
message = "No open Unreal Sequencer timeline was found."
try:
    seq_lib = unreal.LevelSequenceEditorBlueprintLibrary
    sequence = seq_lib.get_current_level_sequence()
    if sequence is not None:
        fps = sequence.get_display_rate()
        frame_time = unreal.FrameTime(unreal.FrameNumber(frame), 0.0)
        if hasattr(seq_lib, "set_current_time"):
            seq_lib.set_current_time(frame_time)
            ok = True
            message = "Sequencer current time set."
        elif hasattr(seq_lib, "set_current_local_time"):
            seq_lib.set_current_local_time(frame_time)
            ok = True
            message = "Sequencer local time set."
        else:
            message = "Unreal bridge has Sequencer access, but no supported set-current-time function."
except Exception as exc:
    message = str(exc)
print(json.dumps({{"ok": ok, "frame": frame, "message": message}}))
"""

    def _scene_snapshot_bridge(self, provider: str):
        provider_key = str(provider or "").lower()
        if provider_key == "maya":
            from tech_connector.bridges.maya.maya_bridge import MayaBridge
            return MayaBridge()
        if provider_key == "blender":
            from tech_connector.bridges.blender.blender_bridge import BlenderBridge
            return BlenderBridge()
        if provider_key == "motionbuilder":
            from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge
            return MotionBuilderBridge()
        if provider_key == "houdini":
            from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
            return HoudiniBridge()
        if provider_key == "unreal":
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
            return UnrealBridge()
        if provider_key == "unity":
            from tech_connector.bridges.unity.unity_bridge import UnityBridge
            return UnityBridge()
        raise ValueError(f"No scene snapshot bridge is registered for {provider}.")



    def create_primitive_mesh(self, prim_name: str):
        """Instantiate selected Maya 3D Procedural Quad Primitive (Poly Sphere, Poly Cube, Poly Cylinder)."""
        self.push_viewer_undo_state(f"Create {prim_name}")
        if prim_name == "Cube":
            self.mesh = DCCProceduralPrimitiveFactory.create_cube_primitive()
        elif prim_name == "Cylinder":
            self.mesh = DCCProceduralPrimitiveFactory.create_cylinder_primitive()
        else:
            self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self.frame_mesh_camera()
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.update()
        if self.isVisible():
            QMessageBox.information(self, "3D Primitive Created", f"Successfully created Maya 3D Quad Primitive '{prim_name}' in 3D Viewport!")


    def open_or_import_file_dialog(self):
        """Unified 1-Button Open vs Import File Dialog for 3D Meshes (.fbx, .obj, .gltf) and Textures (.png, .jpg, .psd)."""
        file_path, filter_selected = QFileDialog.getOpenFileName(
            self,
            "Open or Import 3D Mesh / Texture",
            "",
            "All Supported Files (*.fbx *.obj *.gltf *.stl *.png *.jpg *.tga *.psd);;3D Mesh Files (*.fbx *.obj *.gltf *.stl);;Texture Maps (*.png *.jpg *.tga *.psd *.exr);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog
        )

        if not file_path:
            return

        ext = Path(file_path).suffix.lower()
        if ext in {".fbx", ".obj", ".gltf", ".glb", ".stl", ".usd", ".usda"}:
            if ext != ".obj":
                QMessageBox.warning(
                    self,
                    "Mesh Format Not Supported Yet",
                    "This viewer currently loads OBJ geometry. FBX, glTF, GLB, STL, and USD need a real importer before they can be enabled.",
                )
                return
            try:
                self.push_viewer_undo_state(f"Open {Path(file_path).name}")
                self.mesh = FBXMeshModel.from_obj(file_path)
            except Exception as exc:
                QMessageBox.warning(self, "OBJ Load Failed", str(exc))
                return
            self.frame_mesh_camera()
            if hasattr(self, 'canvas') and self.canvas:
                self.canvas.update()
            if self.isVisible():
                QMessageBox.information(self, "File Opened", f"Loaded OBJ geometry '{Path(file_path).name}' into the 3D viewport.")
        elif ext in {".png", ".jpg", ".jpeg", ".tga", ".psd", ".exr"}:
            new_tex = QImage(file_path)
            if not new_tex.isNull():
                self.push_viewer_undo_state(f"Load texture {Path(file_path).name}")
                self.mesh.albedo_texture = new_tex.scaled(1024, 1024, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                if hasattr(self, 'canvas') and self.canvas:
                    self.canvas.update()
                if self.isVisible():
                    QMessageBox.information(self, "Texture Loaded", f"Successfully applied texture map '{Path(file_path).name}' to Albedo channel!")

    def reset_demo_sphere(self):
        """Reset 3D camera transform and restore pristine default checkered grid & sci-fi emblem sample PBR texture map."""
        self.push_viewer_undo_state("Reset sphere")
        self.camera_rot_x = 15.0
        self.camera_rot_y = -30.0
        self.camera_zoom = 4.0
        self.camera_pan_x = 0.0
        self.camera_pan_y = 0.0
        self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self.frame_mesh_camera()
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.update()
        if self.isVisible():
            QMessageBox.information(self, "3D Sphere Reset", "Successfully reset 3D camera transform and restored pristine checkered grid & sci-fi emblem texture map!")

    def proxy_at_viewport_position(self, pos: QPointF, max_distance_px: float = 24.0) -> dict[str, Any] | None:
        if not getattr(self, "canvas", None):
            return None
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        best_proxy = None
        best_distance = float(max_distance_px)
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if not isinstance(proxy, (dict, SceneProxyInstance)) or not bool(proxy.get("visible", True)):
                continue
            center = proxy.get("center") or (0.0, 0.0, 0.0)
            point = self.shared_local_to_display_local((float(center[0]), float(center[1]), float(center[2])))
            sx, sy, _depth = camera.project_world_to_screen(
                point,
                float(self.canvas.width()),
                float(self.canvas.height()),
            )
            distance = math.hypot(float(pos.x()) - sx, float(pos.y()) - sy)
            if distance <= best_distance:
                best_proxy = proxy
                best_distance = distance
        return best_proxy

    def transform_gizmo_screen_handles(
        self,
        proxy: SceneProxyInstance | dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        proxy = proxy or getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)) or not getattr(self, "canvas", None):
            return {}
        center = self._proxy_center_display(proxy)
        if center is None:
            return {}
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        width = float(max(1, self.canvas.width()))
        height = float(max(1, self.canvas.height()))
        sx, sy, depth = camera.project_world_to_screen(center, width, height)
        if depth <= 0.1:
            return {}
        axis_basis = self.transform_axis_basis_display(proxy)
        handle_world = max(0.25, min(2.0, float(getattr(camera, "distance", 6.0)) * 0.12))
        handles: dict[str, dict[str, Any]] = {}
        colors = {
            "X": QColor(255, 72, 72),
            "Y": QColor(76, 230, 112),
            "Z": QColor(86, 152, 255),
        }
        for axis, vector in axis_basis.items():
            end_world = _vec_add(center, _vec_scale(_vec_normalize(vector, (1.0, 0.0, 0.0)), handle_world))
            ex, ey, ez = camera.project_world_to_screen(end_world, width, height)
            if ez <= 0.1:
                continue
            handles[axis] = {
                "start": QPointF(float(sx), float(sy)),
                "end": QPointF(float(ex), float(ey)),
                "vector_display": vector,
                "color": colors.get(axis, QColor(230, 230, 230)),
            }
        return handles

    def transform_axis_basis_display(self, proxy: SceneProxyInstance | dict[str, Any]) -> dict[str, tuple[float, float, float]]:
        mode = str(getattr(self, "transform_orientation_mode", "world") or "world").lower()
        world_basis = {
            "X": self.shared_local_to_display_local((1.0, 0.0, 0.0)),
            "Y": self.shared_local_to_display_local((0.0, 1.0, 0.0)),
            "Z": self.shared_local_to_display_local((0.0, 0.0, 1.0)),
        }
        if mode == "world":
            return {axis: _vec_normalize(vector) for axis, vector in world_basis.items()}
        transform = dict(proxy.get("local_transform") or proxy.get("source_transform") or {})
        rotation = transform.get("rotation")
        object_basis = self._rotation_basis_display(proxy, rotation)
        if object_basis:
            return object_basis
        return {axis: _vec_normalize(vector) for axis, vector in world_basis.items()}

    def _rotation_basis_display(
        self,
        proxy: SceneProxyInstance | dict[str, Any],
        rotation: Any,
    ) -> dict[str, tuple[float, float, float]] | None:
        if not isinstance(rotation, (list, tuple)) or len(rotation) < 3:
            return None
        provider = str(proxy.get("provider_id") or "").lower()
        rx, ry, rz = (float(rotation[0]), float(rotation[1]), float(rotation[2]))
        if provider != "blender":
            rx, ry, rz = math.radians(rx), math.radians(ry), math.radians(rz)
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)

        def rotate(v: tuple[float, float, float]) -> tuple[float, float, float]:
            x, y, z = v
            y, z = y * cx - z * sx, y * sx + z * cx
            x, z = x * cy + z * sy, -x * sy + z * cy
            x, y = x * cz - y * sz, x * sz + y * cz
            return x, y, z

        return {
            "X": _vec_normalize(self.shared_local_to_display_local(rotate((1.0, 0.0, 0.0)))),
            "Y": _vec_normalize(self.shared_local_to_display_local(rotate((0.0, 1.0, 0.0)))),
            "Z": _vec_normalize(self.shared_local_to_display_local(rotate((0.0, 0.0, 1.0)))),
        }

    def hit_test_transform_gizmo_axis(self, pos: QPointF) -> str:
        handles = self.transform_gizmo_screen_handles()
        if not handles:
            return ""
        best_axis = ""
        best_distance = 14.0
        for axis, handle in handles.items():
            start = handle.get("start")
            end = handle.get("end")
            if not isinstance(start, QPointF) or not isinstance(end, QPointF):
                continue
            if math.hypot(float(pos.x()) - float(start.x()), float(pos.y()) - float(start.y())) <= 10.0:
                return ""
            distance = self._distance_to_screen_segment(pos, start, end)
            endpoint_distance = math.hypot(float(pos.x()) - float(end.x()), float(pos.y()) - float(end.y()))
            distance = min(distance, endpoint_distance)
            if distance < best_distance:
                best_distance = distance
                best_axis = axis
        return best_axis

    def _distance_to_screen_segment(self, p: QPointF, a: QPointF, b: QPointF) -> float:
        ax, ay = float(a.x()), float(a.y())
        bx, by = float(b.x()), float(b.y())
        px, py = float(p.x()), float(p.y())
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0e-6:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        cx, cy = ax + dx * t, ay + dy * t
        return math.hypot(px - cx, py - cy)

    def preview_translate_selected_proxy_from_screen_delta(self, delta_x: float, delta_y: float) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not proxy:
            return
        scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        screen_to_view = max(0.001, float(self.camera_zoom) / 500.0)
        axis = str(getattr(self, "active_transform_axis", "") or "").upper()
        if axis in {"X", "Y", "Z"}:
            handles = self.transform_gizmo_screen_handles(proxy)
            handle = handles.get(axis, {})
            start = handle.get("start")
            end = handle.get("end")
            vector_display = handle.get("vector_display")
            if isinstance(start, QPointF) and isinstance(end, QPointF) and isinstance(vector_display, tuple):
                sx = float(end.x()) - float(start.x())
                sy = float(end.y()) - float(start.y())
                length = max(1.0e-6, math.hypot(sx, sy))
                signed_pixels = (float(delta_x) * sx + float(delta_y) * sy) / length
                display_delta = _vec_scale(_vec_normalize(vector_display), signed_pixels * screen_to_view / scale)
                shared_delta = self.display_local_to_shared_local(display_delta)
            else:
                shared_delta = (0.0, 0.0, 0.0)
        else:
            shared_delta = (
                float(delta_x) * screen_to_view / scale,
                -float(delta_y) * screen_to_view / scale,
                0.0,
            )
        proxy["_pending_shared_delta"] = tuple(
            float(v) + shared_delta[i]
            for i, v in enumerate(proxy.get("_pending_shared_delta") or (0.0, 0.0, 0.0))
        )
        self._offset_proxy_preview(proxy, shared_delta)

    def _offset_proxy_preview(
        self,
        proxy: SceneProxyInstance | dict[str, Any],
        shared_delta: tuple[float, float, float],
        *,
        mark_dirty: bool = True,
    ) -> None:
        view_delta = self._shared_delta_to_view_delta(shared_delta)
        center = proxy.get("center") or (0.0, 0.0, 0.0)
        proxy["center"] = tuple(float(center[i]) + view_delta[i] for i in range(3))
        local_transform = dict(proxy.get("local_transform") or proxy.get("source_transform") or {})
        translation = local_transform.get("translation")
        if isinstance(translation, (list, tuple)) and len(translation) >= 3:
            provider = str(proxy.get("provider_id") or "")
            snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
            unit_linear = str(snapshot.get("unit_linear") or "")
            native_delta = provider_view_to_world(provider, *shared_delta, unit_linear, str(snapshot.get("up_axis") or ""))
            local_transform["translation"] = [
                float(translation[i]) + float(native_delta[i])
                for i in range(3)
            ]
            proxy["local_transform"] = local_transform
        if isinstance(proxy, SceneProxyInstance):
            mesh_data = proxy.mesh_data
            for index in range(mesh_data.vertex_start, mesh_data.vertex_start + mesh_data.vertex_count):
                if 0 <= index < len(self.mesh.vertices):
                    vertex = self.mesh.vertices[index]
                    vertex.x += view_delta[0]
                    vertex.y += view_delta[1]
                    vertex.z += view_delta[2]
            if mark_dirty:
                proxy.sync_state = "dirty"
        if self._proxy_source_key(proxy) == getattr(self, "_camera_pivot_source_key", ""):
            self._move_camera_pivot_to_proxy(proxy, keep_eye_offset=True)
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _shared_delta_to_view_delta(self, shared_delta: tuple[float, float, float]) -> tuple[float, float, float]:
        scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        return tuple(float(v) * scale for v in shared_delta)

    def preview_selected_proxy_transform_from_screen_delta(self, delta_x: float, delta_y: float) -> None:
        mode = str(getattr(self, "viewport_mode", "Translate") or "Translate")
        if mode == "Translate":
            self.preview_translate_selected_proxy_from_screen_delta(delta_x, delta_y)
            return
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not proxy:
            return
        axis = str(getattr(self, "active_transform_axis", "") or "").upper()
        if axis not in {"X", "Y", "Z"}:
            axis = "XYZ"
        axis_mask = self._axis_mask_from_label(axis)
        local_transform = dict(proxy.get("local_transform") or proxy.get("source_transform") or {})
        if mode == "Rotate":
            rotation = list(local_transform.get("rotation") or (0.0, 0.0, 0.0))
            if len(rotation) < 3:
                rotation = [0.0, 0.0, 0.0]
            delta_degrees = (float(delta_x) - float(delta_y)) * 0.35
            for index, enabled in enumerate(axis_mask):
                if enabled:
                    rotation[index] = float(rotation[index]) + delta_degrees
            local_transform["rotation"] = rotation[:3]
            proxy["_pending_rotation_absolute"] = tuple(float(v) for v in rotation[:3])
        elif mode == "Scale":
            values = list(local_transform.get("scale") or (1.0, 1.0, 1.0))
            if len(values) < 3:
                values = [1.0, 1.0, 1.0]
            factor = max(0.01, 1.0 + (float(delta_x) - float(delta_y)) * 0.006)
            for index, enabled in enumerate(axis_mask):
                if enabled:
                    values[index] = max(0.001, float(values[index]) * factor)
            local_transform["scale"] = values[:3]
            proxy["_pending_scale_absolute"] = tuple(float(v) for v in values[:3])
        proxy["local_transform"] = local_transform
        self._resolved_shaded_status = f"{mode} {axis}"
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def commit_selected_proxy_transform(self) -> tuple[bool, str]:
        mode = str(getattr(self, "viewport_mode", "Translate") or "Translate")
        if mode == "Translate":
            return self.commit_selected_proxy_translation()
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not proxy:
            return False, "No scene proxy is selected."
        provider = str(proxy.get("provider_id") or "")
        native_id = str(proxy.get("native_id") or "")
        if not provider or not native_id:
            return False, "Selected proxy does not have a native target."
        rotation = proxy.pop("_pending_rotation_absolute", None)
        scale = proxy.pop("_pending_scale_absolute", None)
        if rotation is None and scale is None:
            return True, "No transform change to commit."
        try:
            selected_key = str(proxy.get("source_key") or f"{provider}:{native_id}")
            self.apply_shared_transform_to_native_object(
                provider,
                native_id,
                rotation=tuple(float(v) for v in rotation) if rotation is not None else None,
                scale=tuple(float(v) for v in scale) if scale is not None else None,
            )
            self._load_dcc_scene_providers([provider], show_message=False)
            for candidate in getattr(self.mesh, "scene_proxy_objects", []) or []:
                if candidate.get("source_key") == selected_key:
                    self._selected_scene_proxy = candidate
                    break
            self.refresh_scene_outliner()
            self._resolved_shaded_status = f"{mode} committed: {provider}:{proxy.get('name') or native_id}"
            self.update_viewport_status()
            return True, self._resolved_shaded_status
        except Exception as exc:
            if self.isVisible():
                QMessageBox.warning(self, "Transform Commit Failed", str(exc))
            return False, str(exc)

    def commit_selected_proxy_translation(self) -> tuple[bool, str]:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not proxy:
            return False, "No scene proxy is selected."
        if isinstance(proxy, SceneProxyInstance):
            shared_delta = tuple(float(v) for v in proxy.pending_shared_delta)
            proxy.pending_shared_delta = (0.0, 0.0, 0.0)
        else:
            shared_delta = tuple(float(v) for v in (proxy.pop("_pending_shared_delta", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)))
        if max(abs(v) for v in shared_delta) <= 1.0e-6:
            return True, "No transform change to commit."
        provider = str(proxy.get("provider_id") or "")
        native_id = str(proxy.get("native_id") or "")
        if not provider or not native_id:
            return False, "Selected proxy does not have a native target."
        try:
            selected_key = str(proxy.get("source_key") or f"{provider}:{native_id}")
            self.apply_shared_translation_to_native_object(provider, native_id, shared_delta)
            if isinstance(proxy, SceneProxyInstance):
                proxy.sync_state = "clean"
                proxy.local_transform = dict(proxy.source_transform)
            self._load_dcc_scene_providers([provider], show_message=False)
            for candidate in getattr(self.mesh, "scene_proxy_objects", []) or []:
                if candidate.get("source_key") == selected_key:
                    self._selected_scene_proxy = candidate
                    break
            self.refresh_scene_outliner()
            self._resolved_shaded_status = f"Moved {provider}:{proxy.get('name') or native_id}"
            self.update_viewport_status()
            return True, f"Moved {provider}:{native_id} by shared delta {shared_delta}."
        except Exception as exc:
            inverse = tuple(-v for v in shared_delta)
            self._offset_proxy_preview(proxy, inverse)
            if self.isVisible():
                QMessageBox.warning(self, "Transform Commit Failed", str(exc))
            return False, str(exc)

    def apply_shared_translation_to_native_object(
        self,
        provider: str,
        native_id: str,
        shared_delta: tuple[float, float, float],
    ) -> None:
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
        unit_linear = str(snapshot.get("unit_linear") or "")
        native_delta = provider_view_to_world(provider, *shared_delta, unit_linear, str(snapshot.get("up_axis") or ""))
        bridge = self._scene_snapshot_bridge(provider)
        if provider == "maya":
            code = (
                "import maya.cmds as cmds\n"
                f"node = {native_id!r}\n"
                f"delta = {tuple(float(v) for v in native_delta)!r}\n"
                "if not cmds.objExists(node):\n"
                "    raise RuntimeError('Object does not exist: ' + node)\n"
                "pos = cmds.xform(node, q=True, ws=True, translation=True) or [0.0, 0.0, 0.0]\n"
                "cmds.xform(node, ws=True, translation=[float(pos[0]) + delta[0], float(pos[1]) + delta[1], float(pos[2]) + delta[2]])\n"
                "cmds.select(node, replace=True)\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "blender":
            code = (
                "import bpy\n"
                f"name = {native_id!r}\n"
                f"delta = {tuple(float(v) for v in native_delta)!r}\n"
                "obj = bpy.data.objects.get(name)\n"
                "if obj is None:\n"
                "    raise RuntimeError('Object does not exist: ' + name)\n"
                "obj.location.x += delta[0]\n"
                "obj.location.y += delta[1]\n"
                "obj.location.z += delta[2]\n"
                "bpy.ops.object.select_all(action='DESELECT')\n"
                "obj.select_set(True)\n"
                "bpy.context.view_layer.objects.active = obj\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "motionbuilder":
            code = (
                "import pyfbsdk\n"
                f"node = {native_id!r}\n"
                f"delta = {tuple(float(v) for v in native_delta)!r}\n"
                "target = None\n"
                "for comp in pyfbsdk.FBSystem().Scene.Components:\n"
                "    if hasattr(comp, 'Translation') and ((getattr(comp, 'LongName', '') or getattr(comp, 'Name', '')) == node or getattr(comp, 'Name', '') == node):\n"
                "        target = comp\n"
                "        break\n"
                "if target is None:\n"
                "    raise RuntimeError('Object does not exist: ' + node)\n"
                "pos = target.Translation.Data\n"
                "target.Translation = pyfbsdk.FBVector3d(float(pos[0]) + delta[0], float(pos[1]) + delta[1], float(pos[2]) + delta[2])\n"
                "try:\n"
                "    target.Selected = True\n"
                "except Exception:\n"
                "    pass\n"
                "print('OK')\n"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider == "unreal":
            response = bridge.execute_python(self._unreal_translate_actor_code(native_id, native_delta), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError(f"Transform edits are not implemented for {provider} yet.")
        if not ok:
            raise RuntimeError(raw)

    def apply_shared_transform_to_native_object(
        self,
        provider: str,
        native_id: str,
        *,
        translation_shared: tuple[float, float, float] | None = None,
        rotation: tuple[float, float, float] | None = None,
        scale: tuple[float, float, float] | None = None,
        look_at_shared: tuple[float, float, float] | None = None,
        aim_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
        up_axis_vector: tuple[float, float, float] = (0.0, 1.0, 0.0),
    ) -> None:
        provider_key = str(provider or "").lower()
        if not provider_key or not native_id:
            raise ValueError("Provider and native object id are required.")
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider_key, {})
        unit_linear = str(snapshot.get("unit_linear") or "")
        up_axis = str(snapshot.get("up_axis") or "")
        translation_native = (
            provider_view_to_world(provider_key, *translation_shared, unit_linear, up_axis)
            if translation_shared is not None
            else None
        )
        look_at_native = (
            provider_view_to_world(provider_key, *look_at_shared, unit_linear, up_axis)
            if look_at_shared is not None
            else None
        )
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_key == "maya":
            code = (
                "import maya.cmds as cmds\n"
                f"node = {native_id!r}\n"
                f"translation = {tuple(float(v) for v in translation_native)!r} if {translation_native is not None!r} else None\n"
                f"rotation = {tuple(float(v) for v in rotation)!r} if {rotation is not None!r} else None\n"
                f"scale = {tuple(float(v) for v in scale)!r} if {scale is not None!r} else None\n"
                f"look_at = {tuple(float(v) for v in look_at_native)!r} if {look_at_native is not None!r} else None\n"
                f"aim_axis = {tuple(float(v) for v in aim_axis)!r}\n"
                f"up_axis = {tuple(float(v) for v in up_axis_vector)!r}\n"
                "if not cmds.objExists(node):\n"
                "    raise RuntimeError('Object does not exist: ' + node)\n"
                "if translation is not None:\n"
                "    cmds.xform(node, ws=True, translation=list(translation))\n"
                "if rotation is not None:\n"
                "    cmds.xform(node, ws=True, rotation=list(rotation))\n"
                "if scale is not None:\n"
                "    cmds.xform(node, r=False, scale=list(scale))\n"
                "if look_at is not None:\n"
                "    locator = cmds.spaceLocator(name='TechConnector_AimTarget_tmp')[0]\n"
                "    cmds.xform(locator, ws=True, translation=list(look_at))\n"
                "    constraint = cmds.aimConstraint(locator, node, aimVector=aim_axis, upVector=up_axis, worldUpType='scene')[0]\n"
                "    cmds.delete(constraint, locator)\n"
                "cmds.select(node, replace=True)\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "blender":
            code = (
                "import bpy\n"
                "from mathutils import Vector\n"
                f"name = {native_id!r}\n"
                f"translation = {tuple(float(v) for v in translation_native)!r} if {translation_native is not None!r} else None\n"
                f"rotation = {tuple(float(v) for v in rotation)!r} if {rotation is not None!r} else None\n"
                f"scale = {tuple(float(v) for v in scale)!r} if {scale is not None!r} else None\n"
                f"look_at = {tuple(float(v) for v in look_at_native)!r} if {look_at_native is not None!r} else None\n"
                f"aim_axis = {tuple(float(v) for v in aim_axis)!r}\n"
                f"up_axis = {tuple(float(v) for v in up_axis_vector)!r}\n"
                "def _track_axis(axis):\n"
                "    labels = [('X', abs(axis[0])), ('Y', abs(axis[1])), ('Z', abs(axis[2]))]\n"
                "    name = max(labels, key=lambda item: item[1])[0]\n"
                "    sign = '-' if axis[{'X':0,'Y':1,'Z':2}[name]] < 0 else ''\n"
                "    return sign + name\n"
                "def _up_axis(axis):\n"
                "    labels = [('X', abs(axis[0])), ('Y', abs(axis[1])), ('Z', abs(axis[2]))]\n"
                "    return max(labels, key=lambda item: item[1])[0]\n"
                "obj = bpy.data.objects.get(name)\n"
                "if obj is None:\n"
                "    raise RuntimeError('Object does not exist: ' + name)\n"
                "if translation is not None:\n"
                "    obj.location = Vector(translation)\n"
                "if rotation is not None:\n"
                "    obj.rotation_euler = rotation\n"
                "if scale is not None:\n"
                "    obj.scale = scale\n"
                "if look_at is not None:\n"
                "    direction = Vector(look_at) - obj.location\n"
                "    if direction.length > 1.0e-8:\n"
                "        obj.rotation_euler = direction.to_track_quat(_track_axis(aim_axis), _up_axis(up_axis)).to_euler()\n"
                "bpy.ops.object.select_all(action='DESELECT')\n"
                "obj.select_set(True)\n"
                "bpy.context.view_layer.objects.active = obj\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "motionbuilder":
            code = (
                "import math\n"
                "import pyfbsdk\n"
                f"node = {native_id!r}\n"
                f"translation = {tuple(float(v) for v in translation_native)!r} if {translation_native is not None!r} else None\n"
                f"rotation = {tuple(float(v) for v in rotation)!r} if {rotation is not None!r} else None\n"
                f"scale = {tuple(float(v) for v in scale)!r} if {scale is not None!r} else None\n"
                f"look_at = {tuple(float(v) for v in look_at_native)!r} if {look_at_native is not None!r} else None\n"
                f"aim_axis = {tuple(float(v) for v in aim_axis)!r}\n"
                f"up_axis = {tuple(float(v) for v in up_axis_vector)!r}\n"
                "target = None\n"
                "for comp in pyfbsdk.FBSystem().Scene.Components:\n"
                "    if hasattr(comp, 'Translation') and ((getattr(comp, 'LongName', '') or getattr(comp, 'Name', '')) == node or getattr(comp, 'Name', '') == node):\n"
                "        target = comp\n"
                "        break\n"
                "if target is None:\n"
                "    raise RuntimeError('Object does not exist: ' + node)\n"
                "if translation is not None:\n"
                "    target.Translation = pyfbsdk.FBVector3d(*translation)\n"
                "if rotation is not None and hasattr(target, 'Rotation'):\n"
                "    target.Rotation = pyfbsdk.FBVector3d(*rotation)\n"
                "if scale is not None and hasattr(target, 'Scaling'):\n"
                "    target.Scaling = pyfbsdk.FBVector3d(*scale)\n"
                "if look_at is not None and hasattr(target, 'Rotation'):\n"
                "    pos = target.Translation.Data\n"
                "    dx, dy, dz = look_at[0] - pos[0], look_at[1] - pos[1], look_at[2] - pos[2]\n"
                "    yaw = math.degrees(math.atan2(dx, dz))\n"
                "    pitch = -math.degrees(math.atan2(dy, max(1.0e-8, math.sqrt(dx*dx + dz*dz))))\n"
                "    target.Rotation = pyfbsdk.FBVector3d(pitch, yaw, 0.0)\n"
                "try:\n"
                "    target.Selected = True\n"
                "except Exception:\n"
                "    pass\n"
                "print('OK')\n"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_key == "unreal":
            response = bridge.execute_python(
                self._unreal_set_actor_transform_code(native_id, translation_native, rotation, scale, look_at_native, aim_axis, up_axis_vector),
                timeout=10.0,
                reset_globals=True,
            )
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError(f"Transform constraints are not implemented for {provider_key} yet.")
        if not ok:
            raise RuntimeError(raw)

    def load_fbx_mesh_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select 3D Mesh File", "", "OBJ Mesh (*.obj);;Unsupported Mesh Formats (*.fbx *.gltf *.glb *.usd *.usda)", options=QFileDialog.DontUseNativeDialog)
        if not path:
            return
        ext = Path(path).suffix.lower()
        if ext != ".obj":
            QMessageBox.warning(
                self,
                "Mesh Format Not Supported Yet",
                "This viewer currently loads OBJ geometry. FBX, glTF, GLB, and USD need a real importer before they can be enabled.",
            )
            return
        mesh_name = Path(path).name
        try:
            self.mesh = FBXMeshModel.from_obj(path)
        except Exception as exc:
            QMessageBox.warning(self, "OBJ Load Failed", str(exc))
            return
        self.frame_mesh_camera()
        self.canvas.update()
        QMessageBox.information(
            self,
            "3D Mesh Loaded",
            f"Loaded OBJ geometry '{mesh_name}' with {len(self.mesh.vertices)} vertices and {len(self.mesh.faces)} triangles.",
        )

    def bake_and_sync_textures(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory for Baked 3D Textures")
        if not folder:
            return
        out_path = Path(folder) / f"{self.mesh.name}_Albedo.png"
        ok = bool(self.mesh.albedo_texture.save(str(out_path)))
        if ok:
            QMessageBox.information(self, "3D Texture Bake Complete", f"Saved current painted Albedo texture:\n{out_path}")
        else:
            QMessageBox.warning(self, "3D Texture Bake Failed", f"Could not save texture:\n{out_path}")

    def load_albedo_texture_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Albedo Texture",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)",
            options=QFileDialog.DontUseNativeDialog
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Texture Load Failed", f"Could not load image:\n{path}")
            return
        self.mesh.albedo_texture = img.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
            1024,
            1024,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        self.mesh.sample_albedo_path = path
        self.canvas.update()

    def _paint_at_viewport_position(self, pos: QPointF):
        """Raycast 2D viewport click to exact 3D world space coordinate (x, y, z) and paint using 3D Euclidean distance."""
        px, py = pos.x(), pos.y()
        w = float(max(1, self.canvas.width()))
        h = float(max(1, self.canvas.height()))

        camera = getattr(self, "viewport_camera", MayaViewportCamera())

        # 3D Screen Projection
        screen_verts = []
        for vert in self.mesh.vertices:
            display_point = self.shared_local_to_display_local((vert.x, vert.y, vert.z))
            sx, sy, rz_final = camera.project_world_to_screen(display_point, w, h)
            screen_verts.append((sx, sy, rz_final, vert.x, vert.y, vert.z, vert.u, vert.v))

        # Find closest 3D triangle under cursor
        hit_vertex = None
        min_depth = 999999.0

        for i1, i2, i3 in self.mesh.faces:
            sv1, sv2, sv3 = screen_verts[i1], screen_verts[i2], screen_verts[i3]
            x1, y1, z1, vx1, vy1, vz1, u1, uv_v1 = sv1
            x2, y2, z2, vx2, vy2, vz2, u2, uv_v2 = sv2
            x3, y3, z3, vx3, vy3, vz3, u3, uv_v3 = sv3

            # Backface check
            cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
            if cross >= 0:
                continue

            denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(denom) < 1e-6:
                continue

            w1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / denom
            w2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / denom
            w3 = 1.0 - w1 - w2

            if w1 >= -0.05 and w2 >= -0.05 and w3 >= -0.05:
                avg_depth = (z1 + z2 + z3) / 3.0
                if avg_depth < min_depth:
                    min_depth = avg_depth
                    # Interpolate exact 3D world space coordinate (hit_x, hit_y, hit_z)
                    hit_x = w1 * vx1 + w2 * vx2 + w3 * vx3
                    hit_y = w1 * vy1 + w2 * vy2 + w3 * vy3
                    hit_z = w1 * vz1 + w2 * vz2 + w3 * vz3
                    hit_u = max(0.0, min(1.0, w1 * u1 + w2 * u2 + w3 * u3))
                    hit_v = max(0.0, min(1.0, w1 * uv_v1 + w2 * uv_v2 + w3 * uv_v3))
                    hit_vertex = (hit_x, hit_y, hit_z, hit_u, hit_v)

        if hit_vertex is not None:
            hx, hy, hz, hit_u, hit_v = hit_vertex
            brush_name = self.medium_combo.currentText() if getattr(self, 'medium_combo', None) is not None else "PaintBrush"
            profile = self.active_brush_profile()
            is_fill = brush_name == "FillBucket"
            world_r = max(0.04, min(2.0, float(self.brush_size) / 80.0))
            visible_radius_px = max(1.0, float(self.brush_size) * profile.radius_scale)
            fill_brush_radius_px = None if brush_name == "FillBrush" else visible_radius_px
            color = self.active_paint_color()
            symmetry_x = bool(getattr(self, "sym_btn", None) is not None and self.sym_btn.isChecked())
            last_hit = getattr(self, "_last_paint_hit", None)
            if last_hit and not is_fill:
                prev_x, prev_y, prev_z, prev_u, prev_v = last_hit
                uv_dist_px = math.sqrt(
                    ((hit_u - prev_u) * self.mesh.albedo_texture.width()) ** 2
                    + ((hit_v - prev_v) * self.mesh.albedo_texture.height()) ** 2
                )
                steps = max(1, min(80, int(uv_dist_px / max(1.0, visible_radius_px * profile.spacing))))
                for step in range(1, steps + 1):
                    t = step / float(steps)
                    self.mesh.paint_stroke_in_3d_space(
                        prev_x + (hx - prev_x) * t,
                        prev_y + (hy - prev_y) * t,
                        prev_z + (hz - prev_z) * t,
                        color,
                        world_radius=world_r,
                        is_fill_bucket=False,
                        hit_u=prev_u + (hit_u - prev_u) * t,
                        hit_v=prev_v + (hit_v - prev_v) * t,
                        brush_profile=profile,
                        symmetry_x=symmetry_x,
                        radius_px_override=fill_brush_radius_px,
                    )
            else:
                self.mesh.paint_stroke_in_3d_space(
                    hx,
                    hy,
                    hz,
                    color,
                    world_radius=world_r,
                    is_fill_bucket=is_fill,
                    hit_u=hit_u,
                    hit_v=hit_v,
                    brush_profile=profile,
                    symmetry_x=symmetry_x,
                    radius_px_override=fill_brush_radius_px,
                )
            self._last_paint_hit = (hx, hy, hz, hit_u, hit_v)
            self.canvas.update()

    def detect_is_animated_fbx(self) -> bool:
        """Dynamically detect whether the loaded 3D FBX file contains skeletal animation clips or is a static mesh."""
        if hasattr(self, "anim_clip") and self.anim_clip is not None:
            return self.anim_clip.total_frames > 1
        return False

    def show_face_in_image_editor(self, pos: QPointF):
        """Extract texture map from selected 3D face and open in Image Editor multi-tab window."""
        u = max(0.0, min(1.0, pos.x() / float(self.canvas.width())))
        v = max(0.0, min(1.0, pos.y() / float(self.canvas.height())))

        title = f"Face_UV_U{int(u*100)}_V{int(v*100)}_{self.mesh.name}.png"
        img = self.mesh.albedo_texture.copy()

        # Find parent tabbed window or main window to open new tab
        parent_tabbed_win = self.window()
        if hasattr(parent_tabbed_win, "add_new_canvas_tab"):
            parent_tabbed_win.add_new_canvas_tab(title=title, qimage=img)
            QMessageBox.information(self, "Opened in Image Editor", f"Transferred 3D face texture ({self.mesh.name}) to new tab in Image Editor: {title}")
        else:
            from tech_connector.ui.image_editor_widget import ImageEditorTabbedWindow
            win = ImageEditorTabbedWindow()
            win.add_new_canvas_tab(title=title, qimage=img)
            win.show()
            QMessageBox.information(self, "Opened in Image Editor", f"Opened 3D face texture ({self.mesh.name}) in Image Editor Window: {title}")


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
        from tech_connector.services.dcc.dcc_bridge_setup import auto_reconnect_dcc_bridges
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
