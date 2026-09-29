from __future__ import annotations

import math
import heapq
from pathlib import Path
import struct
import time
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QVector3D, QVector4D
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick3D import QQuick3DGeometry, QQuick3DInstancing, QQuick3DTextureData
from PySide6.QtQuickWidgets import QQuickWidget

from tech_connector.game_engine.scene.coordinate_space_service import provider_axis_basis, unit_to_centimeters
from tech_connector.game_engine.deformation.gpu_skinning_contract import (
    GpuSkinMeshSpec,
    build_skin_matrix_palette,
    sparse_render_influence_texels,
)
from tech_connector.game_engine.rendering.render_graph_service import (
    build_fx_render_graph,
    qualify_render_graph,
)
from tech_connector.game_engine.rendering.media_texture_service import (
    normalize_media_texture_source,
    plan_media_texture_residency,
)
from tech_connector.game_engine.rendering.procedural_shader_service import (
    lower_qt_quick3d_shader,
    render_procedural_preview,
)
from tech_connector.services.project_directory_service import resolve_project_asset_path

try:
    import numpy as np
except Exception:  # pragma: no cover - exercised only in stripped runtime builds.
    np = None


class DynamicSceneGeometry(QQuick3DGeometry):
    """Qt Quick 3D geometry backed by the viewer's static mesh cache."""

    STRIDE = 8 * 4

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._vertex_matrix = None
        self._vertex_count = 0
        self._index_count = 0
        self._topology_signature = ""
        self._proxy_render_maps: dict[tuple[str, str], tuple[int, int, Any]] = {}
        self._scene_center = (0.0, 0.0, 0.0)
        self._scene_scale = 1.0
        self.last_static_upload_ms = 0.0
        self.last_position_upload_ms = 0.0

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def index_count(self) -> int:
        return self._index_count

    @property
    def topology_signature(self) -> str:
        return self._topology_signature

    def upload_mesh(
        self,
        mesh: Any,
        *,
        topology_signature: str = "",
        excluded_proxy_keys: set[tuple[str, str]] | None = None,
    ) -> None:
        started = time.perf_counter()
        vertices = list(getattr(mesh, "vertices", []) or [])
        faces = list(getattr(mesh, "faces", []) or [])
        if not vertices or not faces:
            self.clear()
            self._vertex_matrix = None
            self._vertex_count = 0
            self._index_count = 0
            self._topology_signature = ""
            self._proxy_render_maps = {}
            self.update()
            return
        if np is None:
            raise RuntimeError("The GPU viewport requires NumPy for efficient scene-buffer construction.")

        positions = np.fromiter(
            (component for vertex in vertices for component in (vertex.x, vertex.y, vertex.z)),
            dtype=np.float32,
            count=len(vertices) * 3,
        ).reshape((-1, 3))
        texcoords = np.fromiter(
            (component for vertex in vertices for component in (vertex.u, vertex.v)),
            dtype=np.float32,
            count=len(vertices) * 2,
        ).reshape((-1, 2))
        indices = np.asarray(faces, dtype=np.uint32).reshape((-1, 3))
        excluded = set(excluded_proxy_keys or ())
        if excluded:
            keep = np.ones(len(indices), dtype=bool)
            for proxy in getattr(mesh, "scene_proxy_objects", []) or []:
                key = (str(proxy.get("provider_id") or "").lower(), str(proxy.get("native_id") or ""))
                if key not in excluded:
                    continue
                mesh_data = proxy.get("mesh_data")
                face_start = int(mesh_data.get("face_start") if isinstance(mesh_data, dict) else mesh_data.face_start)
                face_count = int(mesh_data.get("face_count") if isinstance(mesh_data, dict) else mesh_data.face_count)
                keep[max(0, face_start) : min(len(keep), face_start + max(0, face_count))] = False
            indices = indices[keep]
            if not len(indices):
                indices = np.empty((0, 3), dtype=np.uint32)
        if len(indices) and int(indices.max(initial=0)) >= len(vertices):
            raise ValueError("GPU mesh contains a face index outside its vertex buffer.")

        normals = np.zeros_like(positions, dtype=np.float32)
        if len(indices):
            edge_a = positions[indices[:, 1]] - positions[indices[:, 0]]
            edge_b = positions[indices[:, 2]] - positions[indices[:, 0]]
            face_normals = np.cross(edge_a, edge_b)
            for corner in range(3):
                np.add.at(normals, indices[:, corner], face_normals)
        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > 1.0e-10
        normals[valid] /= lengths[valid, None]
        normals[~valid] = (0.0, 1.0, 0.0)

        vertex_matrix = np.empty((len(vertices), 8), dtype=np.float32)
        vertex_matrix[:, 0:3] = positions
        vertex_matrix[:, 3:6] = normals
        vertex_matrix[:, 6:8] = texcoords

        bounds_min = positions.min(axis=0)
        bounds_max = positions.max(axis=0)
        self.clear()
        self.setStride(self.STRIDE)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(
            QQuick3DGeometry.Attribute.Semantic.PositionSemantic,
            0,
            QQuick3DGeometry.Attribute.ComponentType.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.Semantic.NormalSemantic,
            3 * 4,
            QQuick3DGeometry.Attribute.ComponentType.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.Semantic.TexCoordSemantic,
            6 * 4,
            QQuick3DGeometry.Attribute.ComponentType.F32Type,
        )
        self.addAttribute(
            QQuick3DGeometry.Attribute.Semantic.IndexSemantic,
            0,
            QQuick3DGeometry.Attribute.ComponentType.U32Type,
        )
        self.setVertexData(QByteArray(vertex_matrix.tobytes(order="C")))
        self.setIndexData(QByteArray(indices.reshape(-1).tobytes(order="C")))
        self.setBounds(
            QVector3D(float(bounds_min[0]), float(bounds_min[1]), float(bounds_min[2])),
            QVector3D(float(bounds_max[0]), float(bounds_max[1]), float(bounds_max[2])),
        )
        self._vertex_matrix = vertex_matrix
        self._vertex_count = len(vertices)
        self._index_count = int(indices.size)
        self._topology_signature = str(topology_signature or f"{len(vertices)}:{len(faces)}")
        self._scene_center = tuple(float(value) for value in (getattr(mesh, "scene_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))[:3])
        self._scene_scale = float(getattr(mesh, "scene_scale", 1.0) or 1.0)
        self._proxy_render_maps = {}
        for proxy in getattr(mesh, "scene_proxy_objects", []) or []:
            try:
                mesh_data = proxy.get("mesh_data")
                vertex_start = int(mesh_data.get("vertex_start") if isinstance(mesh_data, dict) else mesh_data.vertex_start)
                vertex_count = int(mesh_data.get("vertex_count") if isinstance(mesh_data, dict) else mesh_data.vertex_count)
                source_indices = (
                    mesh_data.get("source_vertex_indices", [])
                    if isinstance(mesh_data, dict)
                    else mesh_data.source_vertex_indices
                )
                if vertex_count <= 0 or len(source_indices) != vertex_count:
                    continue
                key = (str(proxy.get("provider_id") or "").lower(), str(proxy.get("native_id") or ""))
                if key in excluded:
                    continue
                self._proxy_render_maps[key] = (
                    vertex_start,
                    vertex_count,
                    np.asarray(source_indices, dtype=np.int64),
                )
            except Exception:
                continue
        self.last_static_upload_ms = (time.perf_counter() - started) * 1000.0
        self.update()

    def upload_positions(self, mesh: Any) -> bool:
        if np is None or self._vertex_matrix is None:
            return False
        vertices = list(getattr(mesh, "vertices", []) or [])
        if len(vertices) != self._vertex_count:
            return False
        started = time.perf_counter()
        positions = np.fromiter(
            (component for vertex in vertices for component in (vertex.x, vertex.y, vertex.z)),
            dtype=np.float32,
            count=self._vertex_count * 3,
        ).reshape((-1, 3))
        self._vertex_matrix[:, 0:3] = positions
        bounds_min = positions.min(axis=0)
        bounds_max = positions.max(axis=0)
        self.setVertexData(QByteArray(self._vertex_matrix.tobytes(order="C")))
        self.setBounds(
            QVector3D(float(bounds_min[0]), float(bounds_min[1]), float(bounds_min[2])),
            QVector3D(float(bounds_max[0]), float(bounds_max[1]), float(bounds_max[2])),
        )
        self.last_position_upload_ms = (time.perf_counter() - started) * 1000.0
        self.update()
        return True

    def upload_fast_snapshots(self, snapshots: dict[str, dict[str, Any]]) -> bool:
        """Map packed source points straight into render vertices and upload once."""
        if np is None or self._vertex_matrix is None or not snapshots:
            return False
        started = time.perf_counter()
        changed = False
        center = np.asarray(self._scene_center, dtype=np.float32)
        for provider, snapshot in snapshots.items():
            if not isinstance(snapshot, dict) or snapshot.get("contract_errors"):
                continue
            provider_key = str(provider or snapshot.get("provider_id") or "").lower()
            provider_base = provider_key.split(":", 1)[0]
            basis = provider_axis_basis(provider_base, snapshot.get("up_axis"))
            axes = (basis.shared_x_from_native, basis.shared_y_from_native, basis.shared_z_from_native)
            axis_indices = [int(axis[0]) for axis in axes]
            axis_signs = np.asarray([float(axis[1]) for axis in axes], dtype=np.float32)
            unit_scale = float(unit_to_centimeters(snapshot.get("unit_linear"), provider_base))
            for obj in snapshot.get("objects") or []:
                if not isinstance(obj, dict):
                    continue
                render_map = self._proxy_render_maps.get((provider_key, str(obj.get("native_id") or "")))
                if render_map is None and ":" in provider_key:
                    render_map = self._proxy_render_maps.get((provider_base, str(obj.get("native_id") or "")))
                geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
                packed = geometry.get("vertices_f32") if isinstance(geometry, dict) else None
                if render_map is None or packed is None:
                    continue
                vertex_start, vertex_count, source_indices = render_map
                source_count = int(geometry.get("vertex_count", 0) or 0)
                float_offset = max(0, int(geometry.get("vertex_float_offset", 0) or 0))
                if source_count <= 0 or len(packed) < float_offset + source_count * 3:
                    continue
                source = np.frombuffer(
                    packed, dtype=np.float32, count=source_count * 3, offset=float_offset * 4
                ).reshape((-1, 3))
                if str(geometry.get("coordinate_space") or "world").lower() == "object":
                    matrix_values = obj.get("world_matrix")
                    if not isinstance(matrix_values, (list, tuple)) or len(matrix_values) < 16:
                        continue
                    matrix = np.asarray(matrix_values[:16], dtype=np.float32)
                    linear = np.asarray(
                        [
                            [matrix[0], matrix[1], matrix[2]],
                            [matrix[4], matrix[5], matrix[6]],
                            [matrix[8], matrix[9], matrix[10]],
                        ],
                        dtype=np.float32,
                    )
                    source_world = source @ linear + matrix[[12, 13, 14]]
                else:
                    source_world = source
                shared = source_world[:, axis_indices] * axis_signs * unit_scale
                local = (shared - center) * self._scene_scale
                if int(source_indices.max(initial=0)) >= source_count:
                    continue
                self._vertex_matrix[vertex_start : vertex_start + vertex_count, 0:3] = local[source_indices]
                changed = True
        if not changed:
            return False
        positions = self._vertex_matrix[:, 0:3]
        bounds_min = positions.min(axis=0)
        bounds_max = positions.max(axis=0)
        self.setVertexData(QByteArray(self._vertex_matrix.tobytes(order="C")))
        self.setBounds(
            QVector3D(float(bounds_min[0]), float(bounds_min[1]), float(bounds_min[2])),
            QVector3D(float(bounds_max[0]), float(bounds_max[1]), float(bounds_max[2])),
        )
        self.last_position_upload_ms = (time.perf_counter() - started) * 1000.0
        self.update()
        return True


class DynamicEffectGeometry(QQuick3DGeometry):
    """Camera-facing HDR effect quads streamed into the real 3D viewport."""

    STRIDE = 12 * 4

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.particle_count = 0
        self.source_count = 0
        self.dropped_count = 0
        self.last_stream_receipt: dict[str, Any] = {}
        self.last_upload_ms = 0.0

    def upload_world(
        self,
        world: Any,
        camera_eye: tuple[float, float, float],
        camera_target: tuple[float, float, float],
        *,
        maximum_particles: int = 20000,
        maximum_distance: float = 250.0,
        render_group: str = "additive",
    ) -> None:
        started = time.perf_counter()
        if np is None:
            return
        system = getattr(world, "effect_system", None)
        from tech_connector.game_engine.runtime.tc_simulation_render_bridge_service import build_simulation_render_stream
        stream = build_simulation_render_stream(
            world, consumer="qt_quick3d", allow_synchronization=True,
        )
        self.last_stream_receipt = stream.receipt()
        position_buffer = stream.buffers.get("positions")
        stream_positions = position_buffer.handle if position_buffer is not None else None
        renderers = {
            emitter.emitter_id: dict(emitter.renderer)
            for emitter in list(getattr(system, "emitters", []) or [])
        }

        def particle_group(particle: Any) -> str:
            renderer = renderers.get(str(getattr(particle, "emitter_id", "")), {})
            if str(renderer.get("type") or "").lower() == "mesh":
                return "mesh"
            mode = str(renderer.get("material_mode") or "").lower()
            if mode in {"refractive", "refraction", "transmission"} or float(renderer.get("transmission", 0.0) or 0.0) > 0.0:
                return "refractive"
            return "additive" if str(renderer.get("blend") or "additive").lower() == "additive" else "alpha"

        matched_particles = [
            (index, particle) for index, particle in enumerate(list(getattr(world, "particles", []) or []))
            if bool(getattr(particle, "alive", True))
            and bool(getattr(particle, "emitter_id", ""))
            and particle_group(particle) == render_group
        ]
        self.source_count = len(matched_particles)
        maximum_distance_squared = max(0.0, float(maximum_distance)) ** 2
        if maximum_distance_squared > 0.0:
            matched_particles = [
                item for item in matched_particles
                if sum((float(stream_positions[item[0]][axis] if stream_positions is not None else item[1].position[axis])
                        - float(camera_eye[axis])) ** 2 for axis in range(3))
                <= maximum_distance_squared
            ]
        limit = max(0, int(maximum_particles))
        if len(matched_particles) > limit:
            particles = heapq.nsmallest(
                limit,
                matched_particles,
                key=lambda item: sum(
                    (float(stream_positions[item[0]][axis] if stream_positions is not None else item[1].position[axis])
                     - float(camera_eye[axis])) ** 2 for axis in range(3)
                ),
            )
        else:
            particles = matched_particles
        self.dropped_count = max(0, self.source_count - len(particles))
        if not particles:
            self.clear()
            self.particle_count = 0
            self.last_upload_ms = (time.perf_counter() - started) * 1000.0
            self.update()
            return
        eye = np.asarray(camera_eye, dtype=np.float32)
        target = np.asarray(camera_target, dtype=np.float32)
        forward = target - eye
        forward /= max(1.0e-8, float(np.linalg.norm(forward)))
        right = np.cross(forward, np.asarray((0.0, 1.0, 0.0), dtype=np.float32))
        if float(np.linalg.norm(right)) <= 1.0e-6:
            right = np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        right /= max(1.0e-8, float(np.linalg.norm(right)))
        up = np.cross(right, forward)
        up /= max(1.0e-8, float(np.linalg.norm(up)))
        radial_segments = 16 if render_group == "refractive" else 0
        vertices_per_particle = radial_segments + 1 if radial_segments else 4
        indices_per_particle = radial_segments * 3 if radial_segments else 6
        vertices = np.empty((len(particles) * vertices_per_particle, 12), dtype=np.float32)
        indices = np.empty((len(particles) * indices_per_particle,), dtype=np.uint32)
        for particle_index, (source_index, particle) in enumerate(particles):
            center = np.asarray(
                stream_positions[source_index] if stream_positions is not None else particle.position,
                dtype=np.float32,
            )
            initial_size = max(1.0e-6, float(particle.effect_attributes.get("initial_size", 1.0)))
            half_size = max(0.003, float(particle.radius) * float(particle.size) / initial_size)
            base = particle_index * vertices_per_particle
            color = np.asarray(particle.color, dtype=np.float32)
            if radial_segments:
                vertices[base, :3] = center
                vertices[base, 3:6] = -forward
                vertices[base, 6:10] = color
                vertices[base, 10:12] = (0.5, 0.5)
                index_base = particle_index * indices_per_particle
                for segment in range(radial_segments):
                    angle = (segment / radial_segments) * math.tau
                    horizontal, vertical = math.cos(angle), math.sin(angle)
                    vertex = base + 1 + segment
                    vertices[vertex, :3] = center + right * half_size * horizontal + up * half_size * vertical
                    rim_normal = right * horizontal * 0.94 + up * vertical * 0.94 - forward * 0.34
                    rim_normal /= max(1.0e-8, float(np.linalg.norm(rim_normal)))
                    vertices[vertex, 3:6] = rim_normal
                    vertices[vertex, 6:10] = color
                    vertices[vertex, 10:12] = (0.5 + horizontal * 0.5, 0.5 - vertical * 0.5)
                    indices[index_base + segment * 3:index_base + segment * 3 + 3] = (
                        base,
                        vertex,
                        base + 1 + ((segment + 1) % radial_segments),
                    )
            else:
                for corner_index, (horizontal, vertical, u, v) in enumerate(((-1, -1, 0, 1), (1, -1, 1, 1), (1, 1, 1, 0), (-1, 1, 0, 0))):
                    vertices[base + corner_index, :3] = center + right * half_size * horizontal + up * half_size * vertical
                    vertices[base + corner_index, 3:6] = -forward
                    vertices[base + corner_index, 6:10] = color
                    vertices[base + corner_index, 10:12] = (u, v)
                index_base = particle_index * indices_per_particle
                indices[index_base:index_base + 6] = (base, base + 1, base + 2, base, base + 2, base + 3)
        positions = vertices[:, :3]
        self.clear()
        self.setStride(self.STRIDE)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.PositionSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.NormalSemantic, 3 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.ColorSemantic, 6 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.TexCoordSemantic, 10 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.IndexSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.U32Type)
        self.setVertexData(QByteArray(vertices.tobytes(order="C")))
        self.setIndexData(QByteArray(indices.tobytes(order="C")))
        self.setBounds(QVector3D(*map(float, positions.min(axis=0))), QVector3D(*map(float, positions.max(axis=0))))
        self.particle_count = len(particles)
        self.last_upload_ms = (time.perf_counter() - started) * 1000.0
        self.update()


class DynamicEffectMeshGeometry(QQuick3DGeometry):
    """One normalized source mesh shared by the native GPU instance table."""

    STRIDE = 10 * 4

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.instance_count = 0
        self.emitter_id = ""
        self._source_signature = ""

    def upload_world(self, world: Any) -> str:
        if np is None:
            return ""
        system = getattr(world, "effect_system", None)
        emitters = {emitter.emitter_id: emitter for emitter in list(getattr(system, "emitters", []) or [])}
        for emitter_id, emitter in emitters.items():
            renderer = dict(emitter.renderer or {})
            if str(renderer.get("type") or "").lower() != "mesh":
                continue
            source_vertices = np.asarray(renderer.get("source_vertices") or (), dtype=np.float32).reshape((-1, 3))
            polygons = [tuple(int(value) for value in face) for face in renderer.get("source_faces") or ()]
            triangles = []
            for face in polygons:
                triangles.extend((face[0], face[index], face[index + 1]) for index in range(1, len(face) - 1))
            source_faces = np.asarray(triangles, dtype=np.uint32).reshape((-1, 3)) if triangles else np.empty((0, 3), dtype=np.uint32)
            if not len(source_vertices) or not len(source_faces):
                continue
            source_signature = f"{emitter_id}:{len(source_vertices)}:{len(source_faces)}:{hash(source_vertices.tobytes())}"
            self.emitter_id = str(emitter_id)
            self.instance_count = sum(
                1 for particle in world.particles if particle.alive and particle.emitter_id == emitter_id
            )
            if source_signature == self._source_signature:
                return self.emitter_id
            center = (source_vertices.min(axis=0) + source_vertices.max(axis=0)) * 0.5
            source_vertices = source_vertices - center
            extent = max(1.0e-6, float(np.max(np.ptp(source_vertices, axis=0))))
            source_vertices /= extent
            normals = _vertex_normals(source_vertices, source_faces)
            vertices = np.empty((len(source_vertices), 10), dtype=np.float32)
            vertices[:, 0:3] = source_vertices
            vertices[:, 3:6] = normals
            vertices[:, 6:10] = 1.0
            self.clear()
            self.setStride(self.STRIDE)
            self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
            self.addAttribute(QQuick3DGeometry.Attribute.Semantic.PositionSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.F32Type)
            self.addAttribute(QQuick3DGeometry.Attribute.Semantic.NormalSemantic, 3 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
            self.addAttribute(QQuick3DGeometry.Attribute.Semantic.ColorSemantic, 6 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
            self.addAttribute(QQuick3DGeometry.Attribute.Semantic.IndexSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.U32Type)
            self.setVertexData(QByteArray(vertices.tobytes(order="C")))
            self.setIndexData(QByteArray(source_faces.reshape(-1).tobytes(order="C")))
            self.setBounds(QVector3D(*map(float, vertices[:, :3].min(axis=0))), QVector3D(*map(float, vertices[:, :3].max(axis=0))))
            self._source_signature = source_signature
            self.update()
            return self.emitter_id
        self.clear()
        self.instance_count = 0
        self.emitter_id = ""
        self._source_signature = ""
        self.update()
        return ""


class DynamicEffectInstancing(QQuick3DInstancing):
    """Compact live particle transforms rendered in one native GPU draw path."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._buffer = QByteArray()
        self.instance_count = 0
        self.last_upload_ms = 0.0
        self.source_count = 0
        self.dropped_count = 0
        self.last_stream_receipt: dict[str, Any] = {}
        self.setHasTransparency(True)
        self.setDepthSortingEnabled(False)

    def getInstanceBuffer(self) -> tuple[QByteArray, int]:
        return self._buffer, self.instance_count

    def upload_world(
        self,
        world: Any,
        emitter_id: str,
        *,
        maximum_instances: int = 100000,
        camera_eye: tuple[float, float, float] = (0.0, 0.0, 0.0),
        maximum_distance: float = 250.0,
    ) -> None:
        started = time.perf_counter()
        from tech_connector.game_engine.runtime.tc_simulation_render_bridge_service import build_simulation_render_stream
        stream = build_simulation_render_stream(world, consumer="qt_quick3d", allow_synchronization=True)
        self.last_stream_receipt = stream.receipt()
        position_buffer = stream.buffers.get("positions")
        stream_positions = position_buffer.handle if position_buffer is not None else None
        matched_particles = [
            (index, particle) for index, particle in enumerate(list(getattr(world, "particles", []) or []))
            if particle.alive and str(particle.emitter_id) == str(emitter_id)
        ]
        self.source_count = len(matched_particles)
        maximum_distance_squared = max(0.0, float(maximum_distance)) ** 2
        if maximum_distance_squared > 0.0:
            matched_particles = [
                item for item in matched_particles
                if sum((float(stream_positions[item[0]][axis] if stream_positions is not None else item[1].position[axis])
                        - float(camera_eye[axis])) ** 2 for axis in range(3))
                <= maximum_distance_squared
            ]
        limit = max(0, int(maximum_instances))
        particles = (
            heapq.nsmallest(
                limit,
                matched_particles,
                key=lambda item: sum(
                    (float(stream_positions[item[0]][axis] if stream_positions is not None else item[1].position[axis])
                     - float(camera_eye[axis])) ** 2 for axis in range(3)
                ),
            )
            if len(matched_particles) > limit else matched_particles
        )
        self.dropped_count = max(0, self.source_count - len(particles))
        payload = bytearray(len(particles) * 80)
        offset = 0
        rendered_positions = []
        for source_index, particle in particles:
            particle_position = (
                stream_positions[source_index] if stream_positions is not None else particle.position
            )
            rendered_positions.append(particle_position)
            scale = max(0.004, float(particle.radius), float(particle.size) * 0.03)
            color_values = tuple(max(0.0, min(1.0, float(value))) for value in particle.color)
            color = QColor.fromRgbF(*color_values[:4])
            lifetime = max(1.0e-8, float(particle.lifetime))
            custom_data = QVector4D(
                max(0.0, min(1.0, float(particle.age) / lifetime)),
                float(particle.angular_velocity),
                float(particle.radius),
                float(particle.size),
            )
            entry = self.calculateTableEntry(
                QVector3D(*map(float, particle_position)),
                QVector3D(scale, scale, scale),
                QVector3D(0.0, math.degrees(float(particle.rotation)), 0.0),
                color,
                custom_data,
            )
            values = [
                component
                for vector in (entry.row0, entry.row1, entry.row2, entry.color, entry.instanceData)
                for component in (vector.x(), vector.y(), vector.z(), vector.w())
            ]
            struct.pack_into("20f", payload, offset, *values)
            offset += 80
        self._buffer = QByteArray(bytes(payload))
        self.instance_count = len(particles)
        self.setInstanceCountOverride(self.instance_count)
        if particles:
            positions = np.asarray(rendered_positions, dtype=np.float32)
            maximum_scale = max(
                max(0.004, float(particle.radius), float(particle.size) * 0.03) for _index, particle in particles
            )
            minimum = positions.min(axis=0) - maximum_scale
            maximum = positions.max(axis=0) + maximum_scale
            self.setShadowBoundsMinimum(QVector3D(*map(float, minimum)))
            self.setShadowBoundsMaximum(QVector3D(*map(float, maximum)))
        self.last_upload_ms = (time.perf_counter() - started) * 1000.0
        self.markDirty()


class RadialEffectTextureData(QQuick3DTextureData):
    """Soft radial RGBA sprite used by the live GPU particle renderer."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        size = 64
        pixels = bytearray(size * size * 4)
        for y in range(size):
            for x in range(size):
                dx = (x + 0.5) / size * 2.0 - 1.0
                dy = (y + 0.5) / size * 2.0 - 1.0
                radius = math.sqrt(dx * dx + dy * dy)
                alpha = max(0.0, min(1.0, 1.0 - radius))
                alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                offset = (y * size + x) * 4
                pixels[offset : offset + 4] = bytes((255, 255, 255, int(alpha * 255.0)))
        self.setSize(QSize(size, size))
        self.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.setTextureData(QByteArray(bytes(pixels)))


class DynamicRgba32TextureData(QQuick3DTextureData):
    """Mutable RGBA32F texture storage for skin influences and matrix palettes."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.width = 0
        self.height = 0

    def upload(self, values: Any, *, width: int, height: int) -> None:
        if np is None:
            raise RuntimeError("The GPU skinning path requires NumPy.")
        width = max(1, int(width))
        height = max(1, int(height))
        pixels = np.asarray(values, dtype=np.float32).reshape((height, width, 4))
        self.setSize(QSize(width, height))
        self.setFormat(QQuick3DTextureData.Format.RGBA32F)
        self.setTextureData(QByteArray(pixels.tobytes(order="C")))
        self.width = width
        self.height = height
        self.update()


class DynamicProceduralTextureData(QQuick3DTextureData):
    """Bounded procedural-material preview used until native shader lowering is installed."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.graph: dict[str, Any] = {}
        self.receipt: dict[str, Any] = {}
        self.resolution = 256
        self.animated = False

    def upload_graph(self, graph: dict[str, Any] | None, *, time_seconds: float = 0.0) -> bool:
        self.graph = dict(graph or {})
        if not self.graph:
            self.receipt = {}
            self.animated = False
            return False
        pixels, receipt = render_procedural_preview(
            self.graph, width=self.resolution, height=self.resolution, time_seconds=time_seconds,
        )
        self.setSize(QSize(self.resolution, self.resolution))
        self.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.setTextureData(QByteArray(pixels.tobytes(order="C")))
        self.receipt = receipt
        self.animated = any(str(node.get("type")) in {"time", "panner"} for node in self.graph.get("nodes", ()))
        self.update()
        return True


class DynamicSkinnedSceneGeometry(QQuick3DGeometry):
    """Bind-pose geometry whose exact 4/8 influences are evaluated by a custom shader."""

    STRIDE = 10 * 4

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._mesh_specs: list[GpuSkinMeshSpec] = []
        self._bindings: dict[str, dict[str, Any]] = {}
        self._matrix_palette = np.empty((0, 4, 4), dtype=np.float32) if np is not None else None
        self._scene_center = (0.0, 0.0, 0.0)
        self._scene_scale = 1.0
        self._vertex_count = 0
        self._index_count = 0
        self._excluded_proxy_keys: set[tuple[str, str]] = set()
        self.material_descriptors: list[dict[str, Any]] = []
        self.influence_texture_width = 1
        self.influence_texture_height = 1
        self.max_influence_pairs = 1
        self.last_pose_upload_ms = 0.0

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def excluded_proxy_keys(self) -> set[tuple[str, str]]:
        return set(self._excluded_proxy_keys)

    def upload_scene(
        self,
        mesh: Any,
        deformation_bindings: dict[str, dict[str, Any]],
        influence_texture: DynamicRgba32TextureData,
        matrix_texture: DynamicRgba32TextureData,
    ) -> set[tuple[str, str]]:
        if np is None:
            raise RuntimeError("The GPU skinning path requires NumPy.")
        bindings = {
            str(provider or "").lower(): binding
            for provider, binding in (deformation_bindings or {}).items()
            if isinstance(binding, dict) and not binding.get("contract_errors")
        }
        entries: list[dict[str, Any]] = []
        palette_offset = 0
        vertex_offset = 0
        influence_texel_offset = 0
        maximum_influences = 0
        for proxy in getattr(mesh, "scene_proxy_objects", []) or []:
            provider = str(proxy.get("provider_id") or "").lower()
            native_id = str(proxy.get("native_id") or "")
            binding = bindings.get(provider)
            if binding is None or not native_id or not bool(proxy.get("visible", True)):
                continue
            skin_mesh = next(
                (
                    item for item in binding.get("meshes") or []
                    if str(item.get("native_id") or "") == native_id
                    and str(item.get("gpu_runtime_mode") or "") == "skeletal"
                    and str(item.get("gpu_influence_mode") or "") in {"fixed4", "fixed8", "sparse"}
                ),
                None,
            )
            if skin_mesh is None:
                continue
            skeleton_id = str(skin_mesh.get("skeleton_id") or "")
            skeleton = next(
                (item for item in binding.get("skeletons") or [] if str(item.get("native_id") or "") == skeleton_id),
                None,
            )
            mesh_data = proxy.get("mesh_data")
            render_start = int(mesh_data.get("vertex_start") if isinstance(mesh_data, dict) else mesh_data.vertex_start)
            render_count = int(mesh_data.get("vertex_count") if isinstance(mesh_data, dict) else mesh_data.vertex_count)
            face_start = int(mesh_data.get("face_start") if isinstance(mesh_data, dict) else mesh_data.face_start)
            face_count = int(mesh_data.get("face_count") if isinstance(mesh_data, dict) else mesh_data.face_count)
            source_indices = list(
                mesh_data.get("source_vertex_indices", [])
                if isinstance(mesh_data, dict)
                else mesh_data.source_vertex_indices
            )
            if skeleton is None or render_count <= 0 or len(source_indices) != render_count or face_count <= 0:
                continue
            joint_count = len(skeleton.get("joints") or [])
            bind_offset = int(skin_mesh.get("bind_vertex_float_offset", 0) or 0)
            source_count = int(skin_mesh.get("vertex_count", 0) or 0)
            source_points = _numpy_float_view(
                skin_mesh.get("bind_vertices_f32"), bind_offset, source_count * 3
            ).reshape((source_count, 3))
            source_map = np.asarray(source_indices, dtype=np.int64)
            if int(source_map.max(initial=0)) >= source_count:
                continue
            local_faces = np.asarray(
                (getattr(mesh, "faces", []) or [])[face_start : face_start + face_count],
                dtype=np.int64,
            ).reshape((-1, 3)) - render_start
            if not len(local_faces) or int(local_faces.min(initial=0)) < 0 or int(local_faces.max(initial=0)) >= render_count:
                continue
            render_points = source_points[source_map]
            normals = _vertex_normals(render_points, local_faces)
            render_vertices = (getattr(mesh, "vertices", []) or [])[render_start : render_start + render_count]
            uvs = np.fromiter(
                (component for vertex in render_vertices for component in (vertex.u, vertex.v)),
                dtype=np.float32,
                count=render_count * 2,
            ).reshape((-1, 2))
            spec = GpuSkinMeshSpec(
                provider,
                native_id,
                skeleton_id,
                palette_offset,
                joint_count,
                vertex_offset,
                render_count,
                int(skin_mesh.get("gpu_influence_width", 0) or 0),
            )
            influence_metadata, influence_texels, mesh_maximum = sparse_render_influence_texels(
                skin_mesh,
                source_indices,
                palette_offset=palette_offset,
            )
            influence_metadata[:, 0] += float(influence_texel_offset)
            entries.append({
                "spec": spec,
                "points": render_points,
                "normals": normals,
                "uvs": uvs,
                "faces": local_faces + vertex_offset,
                "influence_metadata": influence_metadata,
                "influences": influence_texels,
                "material": _proxy_material_descriptor(proxy),
            })
            palette_offset += joint_count
            vertex_offset += render_count
            influence_texel_offset += len(influence_texels)
            maximum_influences = max(maximum_influences, int(mesh_maximum))

        if not entries:
            self.clear()
            self._mesh_specs = []
            self._bindings = bindings
            self._matrix_palette = np.empty((0, 4, 4), dtype=np.float32)
            self._vertex_count = 0
            self._index_count = 0
            self._excluded_proxy_keys = set()
            self.material_descriptors = []
            self.influence_texture_width = 1
            self.influence_texture_height = 1
            self.max_influence_pairs = 1
            self.update()
            return set()

        positions = np.concatenate([entry["points"] for entry in entries], axis=0).astype(np.float32, copy=False)
        normals = np.concatenate([entry["normals"] for entry in entries], axis=0).astype(np.float32, copy=False)
        uvs = np.concatenate([entry["uvs"] for entry in entries], axis=0).astype(np.float32, copy=False)
        faces = np.concatenate([entry["faces"] for entry in entries], axis=0).astype(np.uint32, copy=False)
        influences = np.concatenate([entry["influences"] for entry in entries], axis=0).astype(np.float32, copy=False)
        influence_metadata = np.concatenate(
            [entry["influence_metadata"] for entry in entries], axis=0
        ).astype(np.float32, copy=False)
        vertex_matrix = np.zeros((len(positions), 10), dtype=np.float32)
        vertex_matrix[:, 0:3] = positions
        vertex_matrix[:, 3:6] = normals
        vertex_matrix[:, 6:8] = uvs
        vertex_matrix[:, 8:10] = influence_metadata

        self.clear()
        self.setStride(self.STRIDE)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.PositionSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.NormalSemantic, 3 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.TexCoordSemantic, 6 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.TexCoord1Semantic, 8 * 4, QQuick3DGeometry.Attribute.ComponentType.F32Type)
        self.addAttribute(QQuick3DGeometry.Attribute.Semantic.IndexSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.U32Type)
        self.setVertexData(QByteArray(vertex_matrix.tobytes(order="C")))
        self.setIndexData(QByteArray(faces.reshape(-1).tobytes(order="C")))
        subset_offset = 0
        material_descriptors = []
        for index, entry in enumerate(entries):
            subset_faces = entry["faces"]
            subset_count = int(subset_faces.size)
            subset_positions = positions[subset_faces.reshape(-1)]
            subset_min = subset_positions.min(axis=0)
            subset_max = subset_positions.max(axis=0)
            self.addSubset(
                subset_offset,
                subset_count,
                QVector3D(*map(float, subset_min)),
                QVector3D(*map(float, subset_max)),
                f"skinMaterial{index}",
            )
            subset_offset += subset_count
            material_descriptors.append(dict(entry["material"]))
        bounds_min = positions.min(axis=0)
        bounds_max = positions.max(axis=0)
        self.setBounds(QVector3D(*map(float, bounds_min)), QVector3D(*map(float, bounds_max)))
        texture_width = min(4096, max(1, len(influences)))
        texture_height = max(1, int(math.ceil(len(influences) / float(texture_width))))
        padded = np.zeros((texture_width * texture_height, 4), dtype=np.float32)
        padded[: len(influences)] = influences
        influence_texture.upload(padded, width=texture_width, height=texture_height)
        self._matrix_palette = np.repeat(np.eye(4, dtype=np.float32)[None, :, :], palette_offset, axis=0)
        matrix_texture.upload(self._matrix_palette, width=4, height=max(1, palette_offset))
        self._mesh_specs = [entry["spec"] for entry in entries]
        self._bindings = bindings
        self._scene_center = tuple(float(value) for value in getattr(mesh, "scene_center", (0.0, 0.0, 0.0))[:3])
        self._scene_scale = float(getattr(mesh, "scene_scale", 1.0) or 1.0)
        self._vertex_count = len(positions)
        self._index_count = int(faces.size)
        self._excluded_proxy_keys = {(spec.provider_id, spec.native_id) for spec in self._mesh_specs}
        self.material_descriptors = material_descriptors
        self.influence_texture_width = texture_width
        self.influence_texture_height = texture_height
        self.max_influence_pairs = max(1, int(math.ceil(maximum_influences / 2.0)))
        self.update()
        return set(self._excluded_proxy_keys)

    def upload_pose(
        self,
        provider: str,
        binding: dict[str, Any],
        frame: dict[str, Any],
        matrix_texture: DynamicRgba32TextureData,
    ) -> bool:
        if np is None or self._matrix_palette is None or not len(self._matrix_palette):
            return False
        provider_key = str(provider or "").lower()
        specs = [spec for spec in self._mesh_specs if spec.provider_id == provider_key]
        if not specs:
            return False
        started = time.perf_counter()
        update = build_skin_matrix_palette(
            binding,
            frame,
            specs,
            scene_center=self._scene_center,
            scene_scale=self._scene_scale,
        )
        for spec in specs:
            start = spec.palette_offset
            end = start + spec.joint_count
            self._matrix_palette[start:end] = update[start:end]
        matrix_texture.upload(self._matrix_palette, width=4, height=len(self._matrix_palette))
        self.last_pose_upload_ms = (time.perf_counter() - started) * 1000.0
        self.update()
        return True


def _numpy_float_view(source: Any, offset: int, count: int) -> Any:
    if source is None:
        raise ValueError("A packed float buffer is missing.")
    try:
        return np.frombuffer(source, dtype=np.float32, count=count, offset=offset * 4)
    except (TypeError, ValueError):
        return np.asarray(source[offset : offset + count], dtype=np.float32)


def _vertex_normals(positions: Any, faces: Any) -> Any:
    normals = np.zeros_like(positions, dtype=np.float32)
    edge_a = positions[faces[:, 1]] - positions[faces[:, 0]]
    edge_b = positions[faces[:, 2]] - positions[faces[:, 0]]
    face_normals = np.cross(edge_a, edge_b)
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1.0e-10
    normals[valid] /= lengths[valid, None]
    normals[~valid] = (0.0, 1.0, 0.0)
    return normals


def _proxy_material_descriptor(proxy: Any) -> dict[str, Any]:
    materials = list(proxy.get("materials") or [])
    material = materials[0] if materials else None
    color = QColor(125, 145, 170)
    roughness = 0.5
    metalness = 0.0
    opacity = 1.0
    transmission = 0.0
    ior = 1.5
    thickness = 0.0
    clearcoat = 0.0
    attenuation_color = "#ffffff"
    attenuation_distance = 1000.0
    emission = QColor(0, 0, 0)
    texture_sources: dict[str, dict[str, Any]] = {}
    name = "Viewer Material"
    if material is not None:
        name = str(getattr(material, "name", "") or name)
        source_color = getattr(material, "color", None)
        if isinstance(source_color, QColor):
            color = QColor(source_color)
        roughness = float(getattr(material, "roughness", roughness) or roughness)
        metalness = float(getattr(material, "metalness", metalness) or metalness)
        opacity = max(0.0, min(1.0, color.alphaF()))
        opacity = max(0.0, min(1.0, float(getattr(material, "opacity", opacity))))
        transmission = max(0.0, min(1.0, float(getattr(material, "transmission", 0.0))))
        ior = max(1.0, min(3.0, float(getattr(material, "ior", 1.5))))
        thickness = max(0.0, float(getattr(material, "thickness", 0.0)))
        clearcoat = max(0.0, min(1.0, float(getattr(material, "clearcoat", 0.0))))
        attenuation_color = str(getattr(material, "attenuation_color", "#ffffff") or "#ffffff")
        attenuation_distance = max(0.001, float(getattr(material, "attenuation_distance", 1000.0)))
        emission_values = getattr(material, "emission_color", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
        emission = QColor.fromRgbF(*[max(0.0, min(1.0, float(value))) for value in emission_values[:3]])
        paths = dict(getattr(material, "texture_paths", {}) or {})
        paths.update(dict(getattr(material, "texture_sources", {}) or {}))
        for slot in ("base_color", "normal", "roughness", "metalness", "emission", "opacity"):
            descriptor = _viewport_media_descriptor(paths.get(slot))
            if descriptor:
                texture_sources[slot] = descriptor
    texture_urls = {slot: source["path"] for slot, source in texture_sources.items()}
    return {
        "name": name,
        "color": color.name(QColor.NameFormat.HexArgb),
        "roughness": max(0.0, min(1.0, roughness)),
        "metalness": max(0.0, min(1.0, metalness)),
        "opacity": opacity,
        "transmission": transmission,
        "ior": ior,
        "thickness": thickness,
        "clearcoat": clearcoat,
        "attenuationColor": attenuation_color,
        "attenuationDistance": attenuation_distance,
        "emission": emission.name(QColor.NameFormat.HexRgb),
        "baseColorTexture": texture_urls.get("base_color", ""),
        "useBaseColorTexture": "base_color" in texture_urls,
        "baseColorTextureSource": texture_sources.get("base_color", {}),
        "normalTexture": texture_urls.get("normal", ""),
        "useNormalTexture": "normal" in texture_urls,
        "normalTextureSource": texture_sources.get("normal", {}),
        "roughnessTexture": texture_urls.get("roughness", ""),
        "useRoughnessTexture": "roughness" in texture_urls,
        "roughnessTextureSource": texture_sources.get("roughness", {}),
        "metalnessTexture": texture_urls.get("metalness", ""),
        "useMetalnessTexture": "metalness" in texture_urls,
        "metalnessTextureSource": texture_sources.get("metalness", {}),
        "emissionTexture": texture_urls.get("emission", ""),
        "useEmissionTexture": "emission" in texture_urls,
        "emissionTextureSource": texture_sources.get("emission", {}),
        "opacityTexture": texture_urls.get("opacity", ""),
        "useOpacityTexture": "opacity" in texture_urls,
        "opacityTextureSource": texture_sources.get("opacity", {}),
        "proceduralShader": dict(getattr(material, "procedural_shader", {}) or {}) if material is not None else {},
    }


def _viewport_media_descriptor(payload: Any) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        source = normalize_media_texture_source(payload)
    except (TypeError, ValueError):
        return {}
    path = source.path
    if "://" not in path:
        if source.source_type == "image_sequence" and Path(path).is_absolute():
            resolved = Path(path)
        else:
            resolved = resolve_project_asset_path(path)
            if not resolved or not Path(resolved).is_file():
                return {}
        path = QUrl.fromLocalFile(str(resolved)).toString()
    result = source.to_dict()
    result["path"] = path
    result["playback"] = {
        "autoplay": source.autoplay,
        "loop": source.loop,
        "playback_rate": source.playback_rate,
        "start_time_seconds": source.start_time_seconds,
        "end_time_seconds": source.end_time_seconds,
        "frame_rate": source.frame_rate,
        "muted": source.muted,
        "synchronization": source.synchronization,
        "fallback_frame": source.fallback_frame,
        "sequence_start": source.sequence_start,
        "sequence_end": source.sequence_end,
        "sequence_padding": source.sequence_padding,
    }
    return result


qmlRegisterType(DynamicSceneGeometry, "TechConnector", 1, 0, "DynamicSceneGeometry")
qmlRegisterType(DynamicEffectGeometry, "TechConnector", 1, 0, "DynamicEffectGeometry")
qmlRegisterType(DynamicEffectMeshGeometry, "TechConnector", 1, 0, "DynamicEffectMeshGeometry")
qmlRegisterType(DynamicEffectInstancing, "TechConnector", 1, 0, "DynamicEffectInstancing")
qmlRegisterType(RadialEffectTextureData, "TechConnector", 1, 0, "RadialEffectTextureData")
qmlRegisterType(DynamicSkinnedSceneGeometry, "TechConnector", 1, 0, "DynamicSkinnedSceneGeometry")
qmlRegisterType(DynamicRgba32TextureData, "TechConnector", 1, 0, "DynamicRgba32TextureData")
qmlRegisterType(DynamicProceduralTextureData, "TechConnector", 1, 0, "DynamicProceduralTextureData")


class ThreeDGpuViewport(QQuickWidget):
    """Embedded Qt Quick 3D viewport for the compiled scene surface."""

    backend_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.geometry: DynamicSceneGeometry | None = None
        self.skin_geometry: DynamicSkinnedSceneGeometry | None = None
        self.skin_influence_texture: DynamicRgba32TextureData | None = None
        self.skin_matrix_texture: DynamicRgba32TextureData | None = None
        self.procedural_texture: DynamicProceduralTextureData | None = None
        self.effect_geometry: DynamicEffectGeometry | None = None
        self.effect_alpha_geometry: DynamicEffectGeometry | None = None
        self.effect_refractive_geometry: DynamicEffectGeometry | None = None
        self.effect_mesh_geometry: DynamicEffectMeshGeometry | None = None
        self.effect_mesh_instancing: DynamicEffectInstancing | None = None
        self.effect_stats: dict[str, Any] = {}
        self.media_texture_stats: dict[str, Any] = {}
        self.effect_adaptive_budget_enabled = True
        self.effect_target_upload_ms = 4.0
        self.effect_particle_budget = 20000
        self.effect_mesh_instance_budget = 100000
        self.effect_cull_distance = 250.0
        self._effect_upload_ema_ms = 0.0
        self._camera_eye = (0.0, 1.2, 6.0)
        self._camera_target = (0.0, 0.0, 0.0)
        self._last_error = ""
        self._pending_mesh: Any = None
        self._pending_topology_signature = ""
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.statusChanged.connect(self._on_status_changed)
        qml_path = Path(__file__).resolve().parent / "qml" / "ThreeDMeshGpuViewport.qml"
        self.setSource(QUrl.fromLocalFile(str(qml_path)))
        root = self.rootObject()
        if root is not None:
            self.geometry = root.findChild(DynamicSceneGeometry, "sceneGeometry")
            self.skin_geometry = root.findChild(DynamicSkinnedSceneGeometry, "skinGeometry")
            self.skin_influence_texture = root.findChild(DynamicRgba32TextureData, "skinInfluenceTexture")
            self.skin_matrix_texture = root.findChild(DynamicRgba32TextureData, "skinMatrixTexture")
            self.procedural_texture = root.findChild(DynamicProceduralTextureData, "proceduralTexture")
            self.effect_geometry = root.findChild(DynamicEffectGeometry, "effectGeometry")
            self.effect_alpha_geometry = root.findChild(DynamicEffectGeometry, "effectAlphaGeometry")
            self.effect_refractive_geometry = root.findChild(DynamicEffectGeometry, "effectRefractiveGeometry")
            self.effect_mesh_geometry = root.findChild(DynamicEffectMeshGeometry, "effectMeshGeometry")
            self.effect_mesh_instancing = root.findChild(DynamicEffectInstancing, "effectMeshInstancing")
        if self.geometry is None and self.status() != QQuickWidget.Status.Error:
            self._last_error = "Qt Quick 3D did not create the dynamic scene geometry."
            self.backend_failed.emit(self._last_error)

    @property
    def ready(self) -> bool:
        return self.status() == QQuickWidget.Status.Ready and self.rootObject() is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _on_status_changed(self, status: QQuickWidget.Status) -> None:
        if status != QQuickWidget.Status.Error:
            return
        self._last_error = "; ".join(error.toString() for error in self.errors()) or "Qt Quick 3D failed to initialize."
        self.backend_failed.emit(self._last_error)

    def set_mesh(self, mesh: Any, *, topology_signature: str = "") -> None:
        if self.geometry is None:
            raise RuntimeError(self._last_error or "GPU geometry is unavailable.")
        self._pending_mesh = mesh
        self._pending_topology_signature = str(topology_signature or "")
        if self.isVisible():
            self._flush_pending_mesh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._flush_pending_mesh)

    def _flush_pending_mesh(self) -> None:
        if self.geometry is None or self._pending_mesh is None or not self.isVisible():
            return
        mesh = self._pending_mesh
        topology_signature = self._pending_topology_signature
        self._pending_mesh = None
        self._pending_topology_signature = ""
        bindings = getattr(self, "_pending_deformation_bindings", {}) or {}
        self._pending_deformation_bindings = {}
        excluded: set[tuple[str, str]] = set()
        if self.skin_geometry and self.skin_influence_texture and self.skin_matrix_texture:
            excluded = self.skin_geometry.upload_scene(
                mesh,
                bindings,
                self.skin_influence_texture,
                self.skin_matrix_texture,
            )
        self.geometry.upload_mesh(
            mesh,
            topology_signature=topology_signature,
            excluded_proxy_keys=excluded,
        )
        root = self.rootObject()
        if root is not None:
            root.setProperty("skinReady", False)
            root.setProperty(
                "skinMaterialDescriptors",
                list(getattr(self.skin_geometry, "material_descriptors", []) or []),
            )
            root.setProperty(
                "skinInfluenceTextureWidth",
                float(getattr(self.skin_geometry, "influence_texture_width", 1) or 1),
            )
            root.setProperty(
                "skinInfluenceTextureHeight",
                float(getattr(self.skin_geometry, "influence_texture_height", 1) or 1),
            )
            root.setProperty(
                "skinMaxInfluencePairs",
                float(getattr(self.skin_geometry, "max_influence_pairs", 1) or 1),
            )
        for provider, binding in bindings.items():
            pose = binding.get("initial_pose") if isinstance(binding, dict) else None
            if isinstance(pose, dict):
                self.update_deformation_pose(provider, binding, pose)

    def set_scene(
        self,
        mesh: Any,
        deformation_bindings: dict[str, dict[str, Any]],
        *,
        topology_signature: str = "",
    ) -> None:
        self._pending_deformation_bindings = dict(deformation_bindings or {})
        self.set_mesh(mesh, topology_signature=topology_signature)

    def update_deformation_pose(
        self,
        provider: str,
        binding: dict[str, Any],
        frame: dict[str, Any],
    ) -> bool:
        changed = bool(
            self.skin_geometry
            and self.skin_matrix_texture
            and self.skin_geometry.upload_pose(provider, binding, frame, self.skin_matrix_texture)
        )
        if changed:
            root = self.rootObject()
            if root is not None:
                root.setProperty("skinReady", True)
                root.setProperty("skinMatrixHeight", max(1.0, float(self.skin_matrix_texture.height)))
        return changed

    def update_positions(self, mesh: Any) -> bool:
        return bool(self.geometry and self.geometry.upload_positions(mesh))

    def update_fast_snapshots(self, snapshots: dict[str, dict[str, Any]]) -> bool:
        return bool(self.geometry and self.geometry.upload_fast_snapshots(snapshots))

    def set_camera(
        self,
        eye: tuple[float, float, float],
        target: tuple[float, float, float],
        fov_degrees: float,
        aspect_ratio: float = 0.0,
    ) -> None:
        root = self.rootObject()
        if root is None:
            return
        root.setProperty("cameraEye", QVector3D(*[float(value) for value in eye[:3]]))
        root.setProperty("cameraTarget", QVector3D(*[float(value) for value in target[:3]]))
        root.setProperty("cameraFov", max(5.0, min(150.0, float(fov_degrees))))
        root.setProperty("cameraAspect", max(0.0, float(aspect_ratio or 0.0)))
        self._camera_eye = tuple(float(value) for value in eye[:3])
        self._camera_target = tuple(float(value) for value in target[:3])

    def update_effects(self, world: Any) -> bool:
        started = time.perf_counter()
        if self.effect_geometry is None:
            return False
        self.effect_geometry.upload_world(
            world, self._camera_eye, self._camera_target,
            render_group="additive", maximum_particles=self.effect_particle_budget,
            maximum_distance=self.effect_cull_distance,
        )
        if self.effect_alpha_geometry is not None:
            self.effect_alpha_geometry.upload_world(
                world, self._camera_eye, self._camera_target,
                render_group="alpha", maximum_particles=self.effect_particle_budget,
                maximum_distance=self.effect_cull_distance,
            )
        if self.effect_refractive_geometry is not None:
            self.effect_refractive_geometry.upload_world(
                world, self._camera_eye, self._camera_target,
                render_group="refractive", maximum_particles=self.effect_particle_budget,
                maximum_distance=self.effect_cull_distance,
            )
        if self.effect_mesh_geometry is not None:
            emitter_id = self.effect_mesh_geometry.upload_world(world)
            if self.effect_mesh_instancing is not None:
                self.effect_mesh_instancing.upload_world(
                    world,
                    emitter_id,
                    maximum_instances=self.effect_mesh_instance_budget,
                    camera_eye=self._camera_eye,
                    maximum_distance=self.effect_cull_distance,
                )
        root = self.rootObject()
        system = getattr(world, "effect_system", None)
        refractive = next((
            dict(emitter.renderer) for emitter in list(getattr(system, "emitters", []) or [])
            if str(emitter.renderer.get("material_mode") or "").lower() in {"refractive", "refraction", "transmission"}
            or float(emitter.renderer.get("transmission", 0.0) or 0.0) > 0.0
        ), None)
        if root is not None and refractive:
            root.setProperty("effectTransmission", max(0.0, min(1.0, float(refractive.get("transmission", 0.92)))))
            root.setProperty("effectIor", max(1.0, min(3.0, float(refractive.get("ior", 1.33)))))
            root.setProperty("effectThickness", max(0.0, float(refractive.get("thickness", 0.18))))
            root.setProperty("effectRoughness", max(0.0, min(1.0, float(refractive.get("roughness", 0.06)))))
            root.setProperty("effectClearcoat", max(0.0, min(1.0, float(refractive.get("clearcoat", 0.45)))))
            root.setProperty("effectAttenuationColor", QColor(str(refractive.get("attenuation_color") or "#b8e8ff")))
            root.setProperty("effectAttenuationDistance", max(0.001, float(refractive.get("attenuation_distance", 2.0))))
        streams = {
            "additive": self.effect_geometry,
            "alpha": self.effect_alpha_geometry,
            "refractive": self.effect_refractive_geometry,
        }
        stream_stats = {
            name: {
                "rendered": int(getattr(geometry, "particle_count", 0)),
                "source": int(getattr(geometry, "source_count", 0)),
                "dropped": int(getattr(geometry, "dropped_count", 0)),
                "upload_ms": float(getattr(geometry, "last_upload_ms", 0.0)),
                "buffer_handoff": dict(getattr(geometry, "last_stream_receipt", {}) or {}),
            }
            for name, geometry in streams.items() if geometry is not None
        }
        mesh_instances = int(getattr(self.effect_mesh_instancing, "instance_count", 0))
        mesh_bytes = len(self.effect_mesh_instancing.getInstanceBuffer()[0]) if self.effect_mesh_instancing is not None else 0
        total_upload_ms = (time.perf_counter() - started) * 1000.0
        self._effect_upload_ema_ms = (
            total_upload_ms if self._effect_upload_ema_ms <= 0.0
            else self._effect_upload_ema_ms * 0.85 + total_upload_ms * 0.15
        )
        if self.effect_adaptive_budget_enabled:
            if self._effect_upload_ema_ms > self.effect_target_upload_ms * 1.2:
                self.effect_particle_budget = max(1000, int(self.effect_particle_budget * 0.86))
                self.effect_mesh_instance_budget = max(1000, int(self.effect_mesh_instance_budget * 0.86))
            elif self._effect_upload_ema_ms < self.effect_target_upload_ms * 0.55:
                self.effect_particle_budget = min(100000, max(self.effect_particle_budget + 1, int(self.effect_particle_budget * 1.08)))
                self.effect_mesh_instance_budget = min(250000, max(self.effect_mesh_instance_budget + 1, int(self.effect_mesh_instance_budget * 1.08)))
        primary_handoff = dict(getattr(self.effect_geometry, "last_stream_receipt", {}) or {})
        render_graph = build_fx_render_graph(primary_handoff)
        render_graph_receipt = render_graph.to_dict()
        render_graph_receipt["qualification"] = qualify_render_graph(render_graph)
        self.effect_stats = {
            "streams": stream_stats,
            "mesh_instances": mesh_instances,
            "mesh_source_particles": int(getattr(self.effect_mesh_instancing, "source_count", 0)),
            "mesh_dropped": int(getattr(self.effect_mesh_instancing, "dropped_count", 0)),
            "mesh_instance_bytes": int(mesh_bytes),
            "mesh_upload_ms": float(getattr(self.effect_mesh_instancing, "last_upload_ms", 0.0)),
            "mesh_buffer_handoff": dict(getattr(self.effect_mesh_instancing, "last_stream_receipt", {}) or {}),
            "draw_calls": sum(1 for item in stream_stats.values() if item["rendered"] > 0) + (1 if mesh_instances else 0),
            "total_rendered": sum(item["rendered"] for item in stream_stats.values()) + mesh_instances,
            "total_dropped": sum(item["dropped"] for item in stream_stats.values()) + int(getattr(self.effect_mesh_instancing, "dropped_count", 0)),
            "total_upload_ms": total_upload_ms,
            "upload_ema_ms": self._effect_upload_ema_ms,
            "target_upload_ms": self.effect_target_upload_ms,
            "adaptive_budget": self.effect_adaptive_budget_enabled,
            "particle_budget_per_stream": self.effect_particle_budget,
            "mesh_instance_budget": self.effect_mesh_instance_budget,
            "cull_distance": self.effect_cull_distance,
            "render_handoff": primary_handoff,
            "render_graph": render_graph_receipt,
        }
        return True

    def configure_effect_budget(
        self,
        *,
        target_upload_ms: float | None = None,
        particle_budget: int | None = None,
        mesh_instance_budget: int | None = None,
        cull_distance: float | None = None,
        adaptive: bool | None = None,
    ) -> dict[str, Any]:
        if target_upload_ms is not None:
            self.effect_target_upload_ms = max(0.25, min(33.0, float(target_upload_ms)))
        if particle_budget is not None:
            self.effect_particle_budget = max(100, min(100000, int(particle_budget)))
        if mesh_instance_budget is not None:
            self.effect_mesh_instance_budget = max(100, min(250000, int(mesh_instance_budget)))
        if cull_distance is not None:
            self.effect_cull_distance = max(0.0, min(100000.0, float(cull_distance)))
        if adaptive is not None:
            self.effect_adaptive_budget_enabled = bool(adaptive)
        result = {
            "target_upload_ms": self.effect_target_upload_ms,
            "particle_budget_per_stream": self.effect_particle_budget,
            "mesh_instance_budget": self.effect_mesh_instance_budget,
            "adaptive": self.effect_adaptive_budget_enabled,
        }
        if cull_distance is not None:
            result["cull_distance"] = self.effect_cull_distance
        return result

    def set_lighting_profile(self, profile_id: str) -> None:
        """Apply a shared engine lighting profile to the interactive DCC viewport."""
        from tech_connector.game_engine.rendering.lighting_profile_service import lighting_profile

        profile = lighting_profile(profile_id)
        rendering = dict(profile.rendering)
        sun = dict(profile.sun)
        root = self.rootObject()
        if root is None:
            return

        def color(values: Any, fallback: tuple[float, float, float]) -> QColor:
            components = list(values) if isinstance(values, (list, tuple)) else list(fallback)
            components = (components + list(fallback))[:3]
            return QColor.fromRgbF(*(max(0.0, min(1.0, float(item))) for item in components))

        direction = [float(item) for item in list(sun.get("direction") or (-0.45, -1.0, -0.3))[:3]]
        while len(direction) < 3:
            direction.append(0.0)
        length = max(1.0e-8, math.sqrt(sum(item * item for item in direction)))
        direction = [item / length for item in direction]
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, direction[1]))))
        yaw = math.degrees(math.atan2(-direction[0], -direction[2]))
        intensity = max(0.0, float(sun.get("intensity", 4.0)))
        indirect = max(0.0, float(rendering.get("indirect_intensity", 1.0)))
        root.setProperty("sceneClearColor", color(rendering.get("sky_color"), (0.08, 0.18, 0.42)))
        root.setProperty("keyLightColor", color(sun.get("color"), (1.0, 0.95, 0.86)))
        root.setProperty("keyLightBrightness", intensity / 3.65)
        root.setProperty("keyLightEulerX", pitch)
        root.setProperty("keyLightEulerY", yaw)
        root.setProperty("fillLightColor", color(rendering.get("sky_color"), (0.66, 0.79, 1.0)))
        root.setProperty("fillLightBrightness", indirect * 0.38 if intensity > 0.0 else 0.0)
        root.setProperty("environmentExposure", max(0.0, min(16.0, float(rendering.get("exposure", 1.0)))))

    def set_material(
        self,
        *,
        color: QColor,
        roughness: float = 0.5,
        metalness: float = 0.0,
        base_color_texture: str = "",
        normal_texture: str = "",
        roughness_texture: str = "",
        metalness_texture: str = "",
        emission_texture: str = "",
        opacity_texture: str = "",
        emission_color: QColor | str = "#000000",
        environment_texture: str = "",
        exposure: float = 1.0,
        opacity: float = 1.0,
        transmission: float = 0.0,
        ior: float = 1.5,
        thickness: float = 0.0,
        clearcoat: float = 0.0,
        attenuation_color: QColor | str = "#ffffff",
        attenuation_distance: float = 1000.0,
        texture_sources: dict[str, Any] | None = None,
        procedural_shader: dict[str, Any] | None = None,
    ) -> None:
        root = self.rootObject()
        if root is None:
            return
        root.setProperty("materialColor", QColor(color))
        root.setProperty("materialRoughness", max(0.0, min(1.0, float(roughness))))
        root.setProperty("materialMetalness", max(0.0, min(1.0, float(metalness))))
        root.setProperty("materialOpacity", max(0.0, min(1.0, float(opacity))))
        root.setProperty("materialTransmission", max(0.0, min(1.0, float(transmission))))
        root.setProperty("materialIor", max(1.0, min(3.0, float(ior))))
        root.setProperty("materialThickness", max(0.0, float(thickness)))
        root.setProperty("materialClearcoat", max(0.0, min(1.0, float(clearcoat))))
        root.setProperty("materialAttenuationColor", QColor(attenuation_color))
        root.setProperty("materialAttenuationDistance", max(0.001, float(attenuation_distance)))
        root.setProperty("materialEmission", QColor(emission_color))
        root.setProperty("environmentExposure", max(0.0, min(16.0, float(exposure))))
        legacy_sources = {
            "base_color": base_color_texture,
            "normal": normal_texture,
            "specular_roughness": roughness_texture,
            "metalness": metalness_texture,
            "emission_color": emission_texture,
            "opacity": opacity_texture,
        }
        authored_sources = dict(texture_sources or {})
        media_descriptors: dict[str, dict[str, Any]] = {}
        for channel, fallback in legacy_sources.items():
            descriptor = _viewport_media_descriptor(authored_sources.get(channel) or fallback)
            if descriptor:
                media_descriptors[channel] = descriptor
        self.media_texture_stats = plan_media_texture_residency(media_descriptors)
        for deferred_slot in self.media_texture_stats["deferred_slots"]:
            media_descriptors[deferred_slot]["deferred"] = True
        root.setProperty("mediaTextureDescriptors", media_descriptors)
        native_shader = lower_qt_quick3d_shader(procedural_shader) if procedural_shader else {}
        native_ready = bool(native_shader.get("native_executable"))
        preview_ready = False
        if self.procedural_texture is not None:
            preview_ready = bool(procedural_shader) and not native_ready and self.procedural_texture.upload_graph(procedural_shader)
            if native_ready:
                self.procedural_texture.graph = {}
                self.procedural_texture.animated = False
        root.setProperty("proceduralNativeReady", native_ready)
        root.setProperty(
            "proceduralFragmentShader",
            QUrl.fromLocalFile(str(native_shader["shader_path"])) if native_ready else QUrl(),
        )
        root.setProperty("proceduralTextureReady", preview_ready)
        self.media_texture_stats["procedural_shader"] = dict(native_shader)
        if preview_ready:
            self.media_texture_stats["procedural_shader"]["preview"] = dict(self.procedural_texture.receipt)
        self.media_texture_stats.update({"timeline_frame": 0, "timeline_seconds": 0.0, "playing": False})
        for property_name, authored_path in (
            ("baseColorTexture", base_color_texture),
            ("normalTexture", normal_texture),
            ("roughnessTexture", roughness_texture),
            ("metalnessTexture", metalness_texture),
            ("emissionTexture", emission_texture),
            ("opacityTexture", opacity_texture),
            ("environmentTexture", environment_texture),
        ):
            channel = {
                "baseColorTexture": "base_color", "normalTexture": "normal",
                "roughnessTexture": "specular_roughness", "metalnessTexture": "metalness",
                "emissionTexture": "emission_color", "opacityTexture": "opacity",
            }.get(property_name)
            if channel and channel in media_descriptors:
                root.setProperty(property_name, QUrl(media_descriptors[channel]["path"]))
                continue
            texture_path = resolve_project_asset_path(authored_path)
            root.setProperty(
                property_name,
                QUrl.fromLocalFile(str(texture_path)) if texture_path else QUrl(),
            )

    def set_media_timeline(
        self,
        frame: int,
        fps: float,
        *,
        frame_start: int = 0,
        playing: bool = False,
    ) -> dict[str, Any]:
        """Seek timeline-synchronized media without advancing decoder clocks independently."""
        relative_frame = max(0, int(frame) - int(frame_start))
        safe_fps = max(1.0, float(fps))
        seconds = relative_frame / safe_fps
        root = self.rootObject()
        if root is not None:
            root.setProperty("mediaTimelineSeconds", float(seconds))
            root.setProperty("mediaTimelinePlaying", bool(playing))
        self.media_texture_stats.update({
            "timeline_frame": int(frame), "relative_frame": relative_frame,
            "timeline_fps": safe_fps, "timeline_seconds": seconds, "playing": bool(playing),
        })
        procedural_receipt = self.media_texture_stats.get("procedural_shader")
        if isinstance(procedural_receipt, dict) and procedural_receipt.get("gpu_execution"):
            procedural_receipt["uniform_time_seconds"] = seconds
            procedural_receipt["cpu_rebake"] = False
        if self.procedural_texture is not None and self.procedural_texture.animated:
            self.procedural_texture.upload_graph(self.procedural_texture.graph, time_seconds=seconds)
            self.media_texture_stats["procedural_shader"] = dict(self.procedural_texture.receipt)
        return dict(self.media_texture_stats)

    def frame_duration_ms(self, fps: float) -> int:
        return max(1, int(math.ceil(1000.0 / max(1.0, float(fps)))))

