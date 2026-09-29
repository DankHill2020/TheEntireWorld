"""Focused method group for the 3D mesh painter viewport."""
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

from tech_connector.ui.dcc_viewer.mesh_painter.workers import (
    DccCameraPossessionWorker,
    DccDeformationBindingWorker,
    DccResolvedFrameWorker,
    DccSceneImportDialog,
    DccSceneModelCompileWorker,
    DccSceneRestoreWorker,
    DccSceneSnapshotWorker,
    DccTimelineCacheWorker,
    DesktopColorSamplerOverlay,
    EffectBakeWorker,
    MeshBrushProfile,
    MeshDefaultPose,
    MeshLodGenerationWorker,
    MeshVertex3D,
    NativeFbxImportWorker,
    PortBoundDccBridge,
    RuntimeGeometryCompileWorker,
    SceneProxyInstance,
    SceneProxyMaterialBinding,
    SceneProxyMeshData,
    ShotTakeProfile,
    SkinWeightFileWorker,
    TCSceneConversionWorker,
    TimelineFrameArchive,
    UsdCompositionWorker,
    _ProjectedMeshRaycaster,
    _brush_alpha_array,
    _brush_alpha_from_image,
    _load_brush_alpha_image,
    _rgba_image_from_alpha,
    _shift_alpha_array,
    brush_alpha_at,
    build_brush_alpha_preview,
    build_brush_stamp_image,
    scene_snapshot_bridge_for_provider,
)

from tech_connector.ui.dcc_viewer.mesh_painter.geometry import (
    FBXMeshModel,
    MayaViewportCamera,
    ThreeDMeshCanvas,
    _rotate_vec_around_axis,
    _stable_right_axis,
    _vec_add,
    _vec_cross,
    _vec_dot,
    _vec_length,
    _vec_normalize,
    _vec_scale,
    _vec_sub,
    dcc_provider_base_key,
    provider_view_colors,
    provider_view_to_world,
    provider_world_to_view,
    scene_proxy_draws_filled_surface,
)

from tech_connector.ui.dcc_viewer.mesh_painter.support import (
    AnimatedFBXClipContainer,
    DCCProceduralPrimitiveFactory,
    FBXCameraObject,
    FBXMaterialContainer,
    MayaCameraMatrix,
    MayaComponentSelectionSuite,
    MayaSoftSelectionEngine,
    PerFrameSyncSketchMarkupStore,
    SyncSketchMarkupOverlay,
    SyncSketchMarkupStroke,
    ThreeDMeshPaintLayer,
    ThreeDMeshPaintLayerStack,
    TransformManipulatorGizmo,
    extract_cameras_from_fbx,
    extract_materials_from_fbx,
    push_updated_textures_to_dcc_asset_files,
)


class ThreeDMeshPainterViewportMixin06:
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
        provider_base = dcc_provider_base_key(provider_key)
        if provider_base == "native_fbx":
            translation_delta = None
            if translation_shared is not None:
                proxy = next(
                    (
                        item for item in getattr(self.mesh, "scene_proxy_objects", []) or []
                        if str(item.get("provider_id") or "") == "native_fbx"
                        and str(item.get("native_id") or "") == str(native_id)
                    ),
                    None,
                )
                current = self._proxy_center_shared(proxy) if proxy is not None else None
                if current is None:
                    raise RuntimeError(f"Could not resolve native FBX object center: {native_id}")
                translation_delta = tuple(float(translation_shared[index]) - float(current[index]) for index in range(3))
            if look_at_shared is not None:
                raise ValueError("Native FBX aim editing is not implemented yet.")
            self._commit_native_fbx_transform_override(
                native_id,
                translation_delta_shared=translation_delta,
                rotation=rotation,
                scale=scale,
            )
            return
        if not self._allow_dcc_outbound("selected_object", reason="explicit object transform"):
            raise RuntimeError("Selected object outbound is disabled by DCC write policy.")
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
        if provider_base == "maya":
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
        elif provider_base == "blender":
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
        elif provider_base == "motionbuilder":
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
        elif provider_base == "unreal":
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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D Scene File",
            "",
            "Supported Scenes (*.fbx *.obj *.gltf *.glb *.stl *.usd *.usda *.usdc *.usdz *.abc);;Editable FBX (*.fbx);;glTF (*.gltf *.glb);;OpenUSD (*.usd *.usda *.usdc *.usdz);;Alembic (*.abc);;OBJ/STL (*.obj *.stl)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        ext = Path(path).suffix.lower()
        if ext != ".obj":
            self.start_native_scene_import(path)
            return
        mesh_name = Path(path).name
        try:
            self.mesh = FBXMeshModel.from_obj(path)
        except Exception as exc:
            QMessageBox.warning(self, "OBJ Load Failed", str(exc))
            return
        self.sync_gpu_viewport(full=True)
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

        cache_key = (
            id(self.mesh),
            id(self.mesh.vertices),
            id(self.mesh.faces),
            len(self.mesh.vertices),
            len(self.mesh.faces),
            int(getattr(self, "_paint_geometry_revision", 0)),
            int(w),
            int(h),
            tuple(camera.eye),
            tuple(camera.target),
            tuple(camera.up),
            float(camera.fov_degrees),
            str(getattr(self, "viewer_coord_space", "")),
        )
        cached_projection = getattr(self, "_paint_raycast_cache", None)
        if cache_key == getattr(self, "_paint_raycast_cache_key", None) and cached_projection is not None:
            screen_verts, raycaster = cached_projection
        else:
            screen_verts = []
            for vert in self.mesh.vertices:
                display_point = self.shared_local_to_display_local((vert.x, vert.y, vert.z))
                sx, sy, rz_final = camera.project_world_to_screen(display_point, w, h)
                screen_verts.append((sx, sy, rz_final, vert.x, vert.y, vert.z, vert.u, vert.v))
            raycaster = _ProjectedMeshRaycaster(screen_verts, self.mesh.faces)
            self._paint_raycast_cache_key = cache_key
            self._paint_raycast_cache = (screen_verts, raycaster)

        def raycast_screen(sample_x: float, sample_y: float, tolerance: float = 0.0):
            return raycaster.hits([(sample_x, sample_y)], tolerance)[0]

        hit_vertex = raycast_screen(px, py, tolerance=0.05)

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
            paint_target = str(getattr(self, "paint_target_combo", None).currentData() or "color") if getattr(self, "paint_target_combo", None) is not None else "color"

            if paint_target == "skin_spatial_smooth":
                try:
                    from tech_connector.game_engine.deformation.skinning_tool_service import (
                        apply_skin_cluster_to_rig_graph,
                        skin_cluster_from_rig_graph,
                        spatial_smooth_skin_weights,
                    )
                    skin_id, source_kind, _mesh_id = self._selected_skin_or_deformer()
                    if source_kind != "skin":
                        raise ValueError("Select a skin in the Scene Outliner before painting spatial smoothing.")
                    cluster = skin_cluster_from_rig_graph(self.editable_rig_graph, skin_id)
                    vertices = [(vertex.x, vertex.y, vertex.z) for vertex in self.mesh.vertices]
                    result = spatial_smooth_skin_weights(
                        cluster,
                        positions=vertices,
                        center=(hx, hy, hz),
                        radius=world_r * profile.radius_scale,
                        strength=max(0.02, float(profile.opacity)),
                        iterations=1,
                        normal_angle=120.0,
                        max_neighbors=96,
                        hardness=max(0.01, float(profile.hardness)),
                    )
                    if symmetry_x:
                        result = spatial_smooth_skin_weights(
                            result.cluster,
                            positions=vertices,
                            center=(-hx, hy, hz),
                            radius=world_r * profile.radius_scale,
                            strength=max(0.02, float(profile.opacity)),
                            iterations=1,
                            normal_angle=120.0,
                            max_neighbors=96,
                            hardness=max(0.01, float(profile.hardness)),
                        )
                    apply_skin_cluster_to_rig_graph(
                        self.editable_rig_graph,
                        result.cluster,
                        skin_id=skin_id,
                        replace_existing=True,
                    )
                    changed = set(result.changed_vertices)
                    self._last_paint_screen_pos = (px, py)
                    self._last_paint_hit = (hx, hy, hz, hit_u, hit_v)
                    self._resolved_shaded_status = "Spatially smoothed skin weights on {} vertices.".format(len(changed))
                    self.update_viewport_status()
                    self.mark_scene_dirty()
                    self.schedule_paint_canvas_update()
                except Exception as exc:
                    self._resolved_shaded_status = "Skin spatial smooth failed: {}".format(exc)
                    self.update_viewport_status()
                return

            if paint_target != "color":
                weight_map = self.deformation_weight_map(paint_target)
                vertices = [(vertex.x, vertex.y, vertex.z) for vertex in self.mesh.vertices]
                erase = brush_name == "Eraser" or bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
                if is_fill:
                    fill_value = 0.0 if erase else 1.0
                    changed = [index for index, old in enumerate(weight_map.values) if abs(old - fill_value) > 1.0e-12]
                    if changed:
                        weight_map.values = [fill_value] * len(weight_map.values)
                        weight_map.revision += 1
                else:
                    changed = weight_map.paint(
                        vertices,
                        (hx, hy, hz),
                        world_r * profile.radius_scale,
                        value=1.0,
                        strength=max(0.02, float(profile.opacity)),
                        hardness=max(0.01, float(profile.hardness)),
                        mode="erase" if erase else "replace",
                    )
                    if symmetry_x:
                        changed.extend(weight_map.paint(
                            vertices,
                            (-hx, hy, hz),
                            world_r * profile.radius_scale,
                            value=1.0,
                            strength=max(0.02, float(profile.opacity)),
                            hardness=max(0.01, float(profile.hardness)),
                            mode="erase" if erase else "replace",
                        ))
                self._last_paint_screen_pos = (px, py)
                self._last_paint_hit = (hx, hy, hz, hit_u, hit_v)
                if changed:
                    self._sync_deformation_weight_map_contract(paint_target, weight_map)
                    label = self.paint_target_combo.currentText()
                    self._resolved_shaded_status = f"Painted {label} on {len(set(changed))} vertices."
                    self.update_viewport_status()
                self.schedule_paint_canvas_update()
                return

            def paint_screen_footprint(center_x: float, center_y: float) -> None:
                if is_fill:
                    self.mesh.paint_stroke_in_3d_space(
                        hx,
                        hy,
                        hz,
                        color,
                        world_radius=world_r,
                        is_fill_bucket=True,
                        hit_u=hit_u,
                        hit_v=hit_v,
                        brush_profile=profile,
                        symmetry_x=symmetry_x,
                        radius_px_override=fill_brush_radius_px,
                    )
                    return
                radius = max(1.0, visible_radius_px)
                sample_count = max(24, min(120, int(radius * 0.85)))
                texture_dab_radius = max(1.0, min(10.0, radius / max(12.0, math.sqrt(float(sample_count)))))
                footprint_mask_size = max(8, min(768, int(math.ceil(radius * 2.0))))
                footprint_alpha = _brush_alpha_array(profile, footprint_mask_size)
                samples = [(0.0, 0.0)]
                golden_angle = math.pi * (3.0 - math.sqrt(5.0))
                for idx in range(sample_count):
                    sample_r = radius * math.sqrt((idx + 0.5) / float(sample_count))
                    angle = idx * golden_angle
                    samples.append((math.cos(angle) * sample_r, math.sin(angle) * sample_r))
                sample_hits = raycaster.hits([(center_x + x, center_y + y) for x, y in samples])
                for (offset_x, offset_y), sample_hit in zip(samples, sample_hits):
                    nx = offset_x / radius
                    ny = offset_y / radius
                    if footprint_alpha is not None:
                        alpha_x = max(0, min(footprint_mask_size - 1, int((nx + 1.0) * 0.5 * footprint_mask_size)))
                        alpha_y = max(0, min(footprint_mask_size - 1, int((ny + 1.0) * 0.5 * footprint_mask_size)))
                        mask_alpha = float(footprint_alpha[alpha_y, alpha_x])
                    else:
                        mask_alpha = brush_alpha_at(profile, nx, ny)
                    if mask_alpha <= 0.01 or sample_hit is None:
                        continue
                    sample_x, sample_y, sample_z, sample_u, sample_v = sample_hit
                    self.mesh.paint_stroke_in_3d_space(
                        sample_x,
                        sample_y,
                        sample_z,
                        color,
                        world_radius=world_r,
                        is_fill_bucket=False,
                        hit_u=sample_u,
                        hit_v=sample_v,
                        brush_profile=profile,
                        symmetry_x=symmetry_x,
                        radius_px_override=texture_dab_radius,
                        opacity_scale=mask_alpha,
                    )

            last_screen_pos = getattr(self, "_last_paint_screen_pos", None)
            if last_screen_pos and not is_fill:
                prev_px, prev_py = last_screen_pos
                screen_dist = math.hypot(px - prev_px, py - prev_py)
                steps = max(1, min(32, int(screen_dist / max(1.0, visible_radius_px * profile.spacing))))
                for step in range(1, steps + 1):
                    t = step / float(steps)
                    paint_screen_footprint(prev_px + (px - prev_px) * t, prev_py + (py - prev_py) * t)
            else:
                paint_screen_footprint(px, py)

            self._last_paint_screen_pos = (px, py)
            self._last_paint_hit = (hx, hy, hz, hit_u, hit_v)
            self.schedule_paint_canvas_update()
            return

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
            from tech_connector.ui.image_viewer.editor import ImageEditorTabbedWindow
            win = ImageEditorTabbedWindow()
            win.add_new_canvas_tab(title=title, qimage=img)
            win.show()
            QMessageBox.information(self, "Opened in Image Editor", f"Opened 3D face texture ({self.mesh.name}) in Image Editor Window: {title}")
