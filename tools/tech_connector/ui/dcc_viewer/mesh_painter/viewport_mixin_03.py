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
    BRUSH_PROFILES,
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


class ThreeDMeshPainterViewportMixin03:
    def prompt_import_skin_weights(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Import Skin Weights",
            "",
            "Tech Connector Skin Weights (*.tcskin *.json)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            result = self.execute_adaptive_scene_command(
                "skinning.import_weights",
                {"path": path, "force_local": True},
            )
            self._resolved_shaded_status = str(result.get("message") or "Importing skin weights.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Import Skin Weights", str(exc))

    def _load_preferred_palette(self) -> list[str]:
        try:
            from tech_connector.services.settings_service import load_settings
            raw_palette = load_settings().get("mesh_painter_preferred_palette", [])
        except Exception:
            raw_palette = []
        palette: list[str] = []
        for value in raw_palette if isinstance(raw_palette, list) else []:
            color = QColor(str(value))
            if color.isValid():
                hex_color = color.name().lower()
                if hex_color not in palette:
                    palette.append(hex_color)
        return palette[:24]

    def _save_preferred_palette(self) -> None:
        try:
            from tech_connector.services.settings_service import load_settings, save_settings
            settings = load_settings()
            settings["mesh_painter_preferred_palette"] = list(self.preferred_palette[:24])
            save_settings(settings)
        except Exception:
            LOGGER.warning("Could not persist the preferred paint palette.", exc_info=True)

    def add_current_color_to_palette(self) -> None:
        hex_color = self.primary_color.name().lower()
        if hex_color in self.preferred_palette:
            self.preferred_palette.remove(hex_color)
        self.preferred_palette.insert(0, hex_color)
        self.preferred_palette = self.preferred_palette[:24]
        self._save_preferred_palette()
        self.refresh_palette_swatches()
        self.viewport_status_label.setText(f"Saved {hex_color.upper()} to preferred palette.")

    def use_palette_color(self, hex_color: str) -> None:
        color = QColor(hex_color)
        if color.isValid():
            self.apply_primary_color(color)
            self.viewport_status_label.setText(f"Selected palette color {color.name().upper()}.")

    def refresh_palette_swatches(self) -> None:
        layout = getattr(self, "palette_swatch_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.palette_buttons = []
        for hex_color in self.preferred_palette[:8]:
            color = QColor(hex_color)
            if not color.isValid():
                continue
            button = QPushButton("")
            button.setFixedSize(18, 18)
            button.setToolTip(f"Use {hex_color.upper()}")
            button.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #8fb5c7; border-radius: 3px;")
            button.clicked.connect(lambda _checked=False, value=hex_color: self.use_palette_color(value))
            layout.addWidget(button)
            self.palette_buttons.append(button)

    def change_brush_medium(self, medium_name: str):
        self.active_brush_name = medium_name
        profile = (getattr(self, "custom_brush_profiles", {}) or {}).get(medium_name, BRUSH_PROFILES.get(medium_name, BRUSH_PROFILES["PaintBrush"]))
        default_softness = int(round((1.0 - max(0.01, min(1.0, profile.hardness))) * 100.0))
        if getattr(self, "softness_spin", None) is not None:
            self.softness_spin.blockSignals(True)
            self.softness_spin.setValue(default_softness)
            self.softness_spin.blockSignals(False)
        self.brush_softness = default_softness
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
        self.canvas.update()

    def change_brush_softness(self, val: int):
        self.brush_softness = max(0, min(100, int(val)))
        self.canvas.update()

    def schedule_paint_canvas_update(self, *, force: bool = False) -> None:
        now = time.perf_counter()
        if force or now - float(getattr(self, "_last_paint_canvas_update_s", 0.0)) >= 1.0 / 30.0:
            self._last_paint_canvas_update_s = now
            self._paint_canvas_update_pending = False
            self.canvas.update()
            return
        if bool(getattr(self, "_paint_canvas_update_pending", False)):
            return
        self._paint_canvas_update_pending = True
        QTimer.singleShot(34, self._flush_paint_canvas_update)

    def _flush_paint_canvas_update(self) -> None:
        self._paint_canvas_update_pending = False
        self._last_paint_canvas_update_s = time.perf_counter()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def load_custom_brush_alpha(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load Brush Alpha",
            "",
            "Brush Alpha Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*.*)",
        )
        if not path:
            return
        image = _load_brush_alpha_image(path)
        if image is None or image.isNull():
            QMessageBox.warning(self, "Brush Alpha Failed", f"Could not load brush alpha image:\n{path}")
            return
        base_name = Path(path).stem or "Custom Brush"
        label = f"Custom: {base_name}"
        suffix = 2
        while label in BRUSH_PROFILES or label in self.custom_brush_profiles:
            label = f"Custom: {base_name} {suffix}"
            suffix += 1
        profile = MeshBrushProfile(
            radius_scale=1.0,
            opacity=0.9,
            hardness=1.0,
            spacing=0.2,
            alpha_mask="texture",
            alpha_path=path,
        )
        self.custom_brush_profiles[label] = profile
        self.medium_combo.addItem(label)
        self.medium_combo.setCurrentText(label)
        self.brush_softness = 0
        if getattr(self, "softness_spin", None) is not None:
            self.softness_spin.setValue(0)
        self.viewport_status_label.setText(f"Loaded brush alpha: {Path(path).name}")

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
            button.setText("Hide DCC" if expanded else "DCC")
            if button.isChecked() != bool(expanded):
                button.blockSignals(True)
                button.setChecked(bool(expanded))
                button.blockSignals(False)

    def change_viewport_mode_from_combo(self, text: str):
        label = str(text or "").lower()
        if "vertex" in label:
            self.set_viewport_interaction_mode("Vertex", update_combo=False)
        elif "edge" in label:
            self.set_viewport_interaction_mode("Edge", update_combo=False)
        elif "face" in label:
            self.set_viewport_interaction_mode("Face", update_combo=False)
        elif "translate" in label:
            self.set_viewport_interaction_mode("Translate", update_combo=False)
        elif "rotate" in label:
            self.set_viewport_interaction_mode("Rotate", update_combo=False)
        elif "scale" in label:
            self.set_viewport_interaction_mode("Scale", update_combo=False)
        elif "paint" in label:
            self.set_viewport_interaction_mode("Paint", update_combo=False)
        else:
            self.set_viewport_interaction_mode("Selection", update_combo=False)

    def set_viewport_interaction_mode(self, mode: str, *, update_combo: bool = True) -> None:
        normalized = str(mode or "Selection").strip().title()
        if normalized == "Select":
            normalized = "Selection"
        if normalized not in {"Selection", "Paint", "Translate", "Rotate", "Scale", "Vertex", "Edge", "Face"}:
            normalized = "Selection"
        self.viewport_mode = normalized
        self.active_transform_axis = ""
        self.hover_transform_axis = ""
        if update_combo and getattr(self, "gizmo_mode_combo", None) is not None:
            labels = {
                "Selection": "Select (Q)",
                "Paint": "Paint (P)",
                "Translate": "Translate (W)",
                "Rotate": "Rotate (E)",
                "Scale": "Scale (R/S)",
                "Vertex": "Vertex (F8)",
                "Edge": "Edge (F9)",
                "Face": "Face (F10)",
            }
            target = labels.get(normalized, "Select (Q)")
            if self.gizmo_mode_combo.currentText() != target:
                self.gizmo_mode_combo.blockSignals(True)
                self.gizmo_mode_combo.setCurrentText(target)
                self.gizmo_mode_combo.blockSignals(False)
        self.refresh_viewport_cursor()
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def refresh_viewport_cursor(self, *, hover_axis: str = "") -> None:
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        if getattr(self, "is_b_key_held", False) or getattr(self, "is_resizing_brush", False):
            canvas.setCursor(Qt.SizeHorCursor)
            return
        mode = str(getattr(self, "viewport_mode", "Selection") or "Selection")
        if mode == "Paint":
            canvas.setCursor(Qt.CrossCursor)
            return
        if mode in {"Translate", "Rotate", "Scale"}:
            selected = getattr(self, "_selected_scene_proxy", None)
            axis = str(hover_axis or getattr(self, "hover_transform_axis", "") or getattr(self, "active_transform_axis", "")).upper()
            if isinstance(selected, (dict, SceneProxyInstance)) and axis in {"X", "Y", "Z"}:
                canvas.setCursor(Qt.SizeAllCursor)
            else:
                canvas.setCursor(Qt.ArrowCursor)
            return
        canvas.setCursor(Qt.ArrowCursor)

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
        name = getattr(self, "active_brush_name", "PaintBrush")
        custom_profiles = getattr(self, "custom_brush_profiles", {}) or {}
        if name in custom_profiles:
            profile = custom_profiles[name]
        else:
            profile = BRUSH_PROFILES.get(name, BRUSH_PROFILES["PaintBrush"])
        softness = max(0.0, min(1.0, float(getattr(self, "brush_softness", 35)) / 100.0))
        return replace(profile, hardness=max(0.01, min(1.0, 1.0 - softness)))

    def active_paint_color(self) -> QColor:
        if getattr(self, "active_brush_name", "") == "Eraser":
            return QColor(200, 205, 215, 255)
        return QColor(self.primary_color)

    def change_paint_target(self) -> None:
        key = str(self.paint_target_combo.currentData() or "color")
        label = self.paint_target_combo.currentText()
        if key != "color":
            self.deformation_weight_map(key)
            if key == "emission_source":
                self._resolved_shaded_status = "Painting Emission Source: blue does not emit; green emits at full density. Hold Ctrl to erase."
            else:
                self._resolved_shaded_status = f"Painting {label}: blue preserves upstream; green follows the driven result. Hold Ctrl to erase."
        else:
            self._resolved_shaded_status = "Painting material color."
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def deformation_weight_map(self, key: str):
        from tech_connector.game_engine.deformation import DeformationWeightMap

        maps = getattr(self, "deformation_weight_maps", None)
        if maps is None:
            self.deformation_weight_maps = {}
            maps = self.deformation_weight_maps
        vertex_count = len(getattr(self.mesh, "vertices", ()) or ())
        result = maps.get(str(key))
        if result is None or len(result.values) != vertex_count:
            default = 1.0 if str(key) == "skin_output" else 0.0
            result = DeformationWeightMap.create(str(key), vertex_count, default_value=default)
            maps[str(key)] = result
        if str(key) == "emission_source":
            result.semantics = "mesh_emission_density"
        return result

    def _sync_deformation_weight_map_contract(self, key: str, influence_map: Any) -> None:
        from tech_connector.game_engine.deformation import attach_deformation_map

        prefix, separator, source_id = str(key).partition(":")
        if str(key) == "emission_source":
            world = getattr(self, "simulation_world", None)
            topology, _colors, _proxies = self._canonical_mesh_topology()
            for emitter in getattr(world, "emitters", ()) or ():
                if len(emitter.vertices) == len(topology.vertices):
                    emitter.set_source_weights(
                        influence_map.values,
                        name=influence_map.name,
                        revision=influence_map.revision,
                    )
            if world is not None:
                self.simulation_initial_world = copy.deepcopy(world)
            return
        if prefix in {"skin", "deformer"} and separator and source_id:
            attach_deformation_map(self.editable_rig_graph, source_id, influence_map)
            return
        if prefix == "jiggle" and separator and source_id:
            for deformer in self.editable_rig_graph.deformers.values():
                settings = deformer.get("settings") if isinstance(deformer.get("settings"), dict) else {}
                if str(deformer.get("type") or "") == "jiggle" and str(settings.get("source_id") or "") == source_id:
                    settings["influence_map"] = influence_map.to_dict()
        if prefix == "flesh" and separator and source_id:
            for deformer in self.editable_rig_graph.deformers.values():
                settings = deformer.get("settings") if isinstance(deformer.get("settings"), dict) else {}
                if str(deformer.get("type") or "") == "flesh" and str(settings.get("source_id") or "") == source_id:
                    settings["influence_map"] = influence_map.to_dict()
        if prefix == "secondary" and separator and source_id:
            for skin_id, skin in self.editable_rig_graph.skins.items():
                for preset in skin.get("secondary_motion_presets") or []:
                    preset_key = f"{skin_id}:{preset.get('preset_id', '')}"
                    if preset_key != source_id:
                        continue
                    for deformer_id in preset.get("deformer_ids") or []:
                        deformer = self.editable_rig_graph.deformers.get(str(deformer_id)) or {}
                        settings = deformer.get("settings") if isinstance(deformer.get("settings"), dict) else {}
                        settings["influence_map"] = influence_map.to_dict()

    def _selected_skin_or_deformer(self) -> tuple[str, str, str]:
        item = self.scene_outliner.currentItem() if getattr(self, "scene_outliner", None) is not None else None
        data = item.data(0, Qt.UserRole) if item is not None else None
        data = data if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "")
        if kind == "rig_skin":
            source_id = str(data.get("skin_id") or "")
            source = self.editable_rig_graph.skins.get(source_id) or {}
            return source_id, "skin", str(source.get("mesh_id") or getattr(self.mesh, "name", "mesh"))
        if kind == "rig_deformer":
            source_id = str(data.get("deformer_id") or "")
            source = self.editable_rig_graph.deformers.get(source_id) or {}
            return source_id, "deformer", str(source.get("mesh_id") or getattr(self.mesh, "name", "mesh"))
        raise ValueError("Select a skin or deformer in the Scene Outliner first.")

    def _select_deformation_paint_target(self, key: str, label: str) -> None:
        index = self.paint_target_combo.findData(key)
        if index < 0:
            self.paint_target_combo.addItem(label, key)
            index = self.paint_target_combo.count() - 1
        self.paint_target_combo.setCurrentIndex(index)
        self.gizmo_mode_combo.setCurrentText("Paint (P)")

    def paint_selected_deformer_influence(self) -> None:
        try:
            from tech_connector.game_engine.deformation import attach_deformation_map

            source_id, source_kind, _mesh_id = self._selected_skin_or_deformer()
            key = f"{source_kind}:{source_id}"
            influence_map = self.deformation_weight_map(key)
            self.push_rig_undo_state(f"Attach paint map to {source_id}")
            attach_deformation_map(self.editable_rig_graph, source_id, influence_map)
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} Influence")
            self._resolved_shaded_status = f"Painting {source_kind} influence for {source_id}. Hold Ctrl to erase."
        except Exception as exc:
            self._resolved_shaded_status = f"Deformer map unavailable: {exc}"
        self.update_viewport_status()

    def add_jiggle_to_selected_deformer(self) -> None:
        try:
            from tech_connector.game_engine.deformation import attach_jiggle_deformer

            source_id, _source_kind, mesh_id = self._selected_skin_or_deformer()
            key = f"jiggle:{source_id}"
            influence_map = self.deformation_weight_map(key)
            self.push_rig_undo_state(f"Add jiggle after {source_id}")
            jiggle_id = attach_jiggle_deformer(
                self.editable_rig_graph,
                source_id,
                mesh_id,
                influence_map,
            )
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} Jiggle")
            self.refresh_scene_outliner()
            self._resolved_shaded_status = f"Added jiggle after {source_id}. Paint green where secondary motion should follow."
        except Exception as exc:
            self._resolved_shaded_status = f"Jiggle unavailable: {exc}"
        self.update_viewport_status()

    def enable_fleshy_selected_skin(self) -> None:
        try:
            from tech_connector.game_engine.deformation import attach_flesh_deformer

            source_id, source_kind, mesh_id = self._selected_skin_or_deformer()
            if source_kind != "skin":
                raise ValueError("Fleshy mode must start from a skin cluster so canonical weights remain portable.")
            key = f"flesh:{source_id}"
            influence_map = self.deformation_weight_map(key)
            self.push_rig_undo_state(f"Enable fleshy collision on {source_id}")
            flesh_id = attach_flesh_deformer(
                self.editable_rig_graph, source_id, mesh_id, influence_map
            )
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} Flesh")
            self.refresh_scene_outliner()
            self._resolved_shaded_status = (
                f"Fleshy collision enabled after {source_id} as {flesh_id}. "
                "Canonical skin weights remain unchanged for export; paint green where tissue should respond."
            )
        except Exception as exc:
            self._resolved_shaded_status = f"Fleshy skin unavailable: {exc}"
        self.update_viewport_status()

    def add_secondary_motion_preset_to_selected_skin(self, preset_id: str) -> None:
        try:
            from tech_connector.game_engine.deformation import (
                attach_secondary_motion_preset,
                secondary_motion_preset,
            )

            source_id, source_kind, mesh_id = self._selected_skin_or_deformer()
            if source_kind != "skin":
                raise ValueError("Secondary-motion presets start from a skin cluster to preserve portable weights.")
            preset = secondary_motion_preset(preset_id)
            key = f"secondary:{source_id}:{preset.preset_id}"
            influence_map = self.deformation_weight_map(key)
            self.push_rig_undo_state(f"Add {preset.label} to {source_id}")
            deformer_ids = attach_secondary_motion_preset(
                self.editable_rig_graph, source_id, mesh_id, influence_map, preset.preset_id
            )
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} {preset.label}")
            self.refresh_scene_outliner()
            self._resolved_shaded_status = (
                f"Added {preset.label} ({', '.join(deformer_ids)}). Paint its shared response region; "
                "all physical properties remain editable and canonical skin weights stay export-safe."
            )
        except Exception as exc:
            self._resolved_shaded_status = f"Secondary-motion preset unavailable: {exc}"
        self.update_viewport_status()

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
            "default_pose": copy.deepcopy(getattr(mesh, "default_pose", None)),
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
            "editable_rig_graph": copy.deepcopy(getattr(self, "editable_rig_graph", EditableRigGraph())),
            "simulation_world": copy.deepcopy(getattr(self, "simulation_world", None)),
            "simulation_initial_world": copy.deepcopy(getattr(self, "simulation_initial_world", None)),
            "simulation_cache": copy.deepcopy(getattr(self, "simulation_cache", None)),
            "simulation_frame": int(getattr(self, "simulation_frame", 1)),
            "character_world": copy.deepcopy(getattr(self, "character_world", None)),
            "world_intelligence_runtime": copy.deepcopy(getattr(self, "world_intelligence_runtime", None)),
            "game_experience_profile": copy.deepcopy(getattr(self, "game_experience_profile", None)),
            "deformation_weight_maps": copy.deepcopy(getattr(self, "deformation_weight_maps", {})),
        }

    def mark_scene_dirty(self) -> None:
        lifecycle = getattr(self, "_scene_lifecycle", None)
        if lifecycle is not None:
            lifecycle.mark_dirty()

    def record_nonfatal_diagnostic(self, context: str, exception: BaseException, *, surface: bool = False) -> str:
        message = str(exception) or exception.__class__.__name__
        row = {"context": str(context), "message": message, "type": exception.__class__.__name__}
        self._nonfatal_diagnostics.append(row)
        if len(self._nonfatal_diagnostics) > 200:
            del self._nonfatal_diagnostics[:100]
        LOGGER.warning("%s: %s", context, message, exc_info=True)
        if surface:
            self._resolved_shaded_status = f"{context}: {message}"
            self.update_viewport_status()
        return message

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
        self._scene_lifecycle.mark_dirty()
        self.update_viewport_status()

    def push_rig_undo_state(self, label: str = "Rig action") -> None:
        stack = getattr(self, "_viewer_undo_stack", None)
        if stack is None:
            self._viewer_undo_stack = []
            stack = self._viewer_undo_stack
        stack.append({
            "label": label,
            "rig_only": True,
            "editable_rig_graph": copy.deepcopy(getattr(self, "editable_rig_graph", EditableRigGraph())),
        })
        limit = int(getattr(self, "_viewer_undo_limit", 40) or 40)
        if len(stack) > limit:
            del stack[: len(stack) - limit]
        self._viewer_redo_stack = []
        self._scene_lifecycle.mark_dirty()
        self.update_viewport_status()

    def _restore_viewer_state(self, state: dict[str, Any]) -> None:
        if bool(state.get("rig_only")):
            rig_graph = state.get("editable_rig_graph")
            if isinstance(rig_graph, EditableRigGraph):
                self.editable_rig_graph = copy.deepcopy(rig_graph)
            available_takes = {
                key for key, value in self.editable_rig_graph.animation.items()
                if isinstance(value, dict) and value.get("type") == "animation_take"
            }
            if self.active_animation_take_id not in available_takes:
                self.active_animation_take_id = next(iter(sorted(available_takes)), "")
            if "native_fbx" in (getattr(self, "_dcc_deformation_bindings", {}) or {}):
                try:
                    self._refresh_native_fbx_rig_pose()
                except Exception as exc:
                    self._resolved_shaded_status = f"Native rig restore failed: {exc}"
            self.refresh_scene_outliner()
            self.update_viewport_status()
            return
        mesh = getattr(self, "mesh", None)
        if mesh is None:
            return
        mesh.name = str(state.get("mesh_name") or getattr(mesh, "name", "Mesh"))
        mesh.vertices = copy.deepcopy(state.get("vertices") or [])
        mesh.faces = list(state.get("faces") or [])
        mesh.quad_faces = list(state.get("quad_faces") or [])
        default_pose = state.get("default_pose")
        if isinstance(default_pose, MeshDefaultPose):
            mesh.default_pose = copy.deepcopy(default_pose)
        elif not isinstance(getattr(mesh, "default_pose", None), MeshDefaultPose):
            mesh.update_default_pose()
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
        rig_graph = state.get("editable_rig_graph")
        if isinstance(rig_graph, EditableRigGraph):
            self.editable_rig_graph = copy.deepcopy(rig_graph)
        self.simulation_world = copy.deepcopy(state.get("simulation_world"))
        self.simulation_initial_world = copy.deepcopy(state.get("simulation_initial_world"))
        self.simulation_cache = copy.deepcopy(state.get("simulation_cache"))
        self.simulation_frame = int(state.get("simulation_frame", 1))
        character_world = state.get("character_world")
        if character_world is not None:
            self.character_world = copy.deepcopy(character_world)
        world_intelligence_runtime = state.get("world_intelligence_runtime")
        if world_intelligence_runtime is not None:
            self.world_intelligence_runtime = copy.deepcopy(world_intelligence_runtime)
        self.game_experience_profile = copy.deepcopy(state.get("game_experience_profile"))
        self._sync_viewer_visual_actions()
        self.deformation_weight_maps = copy.deepcopy(state.get("deformation_weight_maps") or {})
        self.sync_gpu_viewport(full=True)
        if "native_fbx" in (getattr(self, "_dcc_deformation_bindings", {}) or {}):
            try:
                self._refresh_native_fbx_rig_pose()
            except Exception as exc:
                self._resolved_shaded_status = f"Native rig restore failed: {exc}"
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
        state = self._viewer_undo_stack.pop()
        if bool(state.get("rig_only")):
            self._viewer_redo_stack.append({
                "label": "Redo state",
                "rig_only": True,
                "editable_rig_graph": copy.deepcopy(getattr(self, "editable_rig_graph", EditableRigGraph())),
            })
        else:
            self._viewer_redo_stack.append(self._capture_viewer_state("Redo state"))
        self._restore_viewer_state(state)
        self._scene_lifecycle.mark_dirty()
        self._resolved_shaded_status = f"Undid: {state.get('label') or 'viewer action'}"
        self.update_viewport_status()

    def redo_viewer_action(self) -> None:
        if not getattr(self, "_viewer_redo_stack", []):
            self._resolved_shaded_status = "Nothing to redo."
            self.update_viewport_status()
            return
        state = self._viewer_redo_stack.pop()
        if bool(state.get("rig_only")):
            self._viewer_undo_stack.append({
                "label": "Undo state",
                "rig_only": True,
                "editable_rig_graph": copy.deepcopy(getattr(self, "editable_rig_graph", EditableRigGraph())),
            })
        else:
            self._viewer_undo_stack.append(self._capture_viewer_state("Undo state"))
        self._restore_viewer_state(state)
        self._scene_lifecycle.mark_dirty()
        self._resolved_shaded_status = f"Redid: {state.get('label') or 'viewer action'}"
        self.update_viewport_status()

    def toggle_texture_display(self, checked: bool):
        self.show_texture = bool(checked)
        self.sync_gpu_viewport(full=False)
        self._sync_display_button_states()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def material_preview_active(self) -> bool:
        return (
            str(getattr(self, "viewport_display_source", "compiled") or "compiled").lower() == "compiled"
            and str(getattr(self, "viewport_shading_mode", "Highlight") or "Highlight").lower() == "shader"
        )

    def gpu_surface_active(self) -> bool:
        gpu = getattr(self, "gpu_viewport", None)
        geometry = getattr(gpu, "geometry", None) if gpu is not None else None
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        reference_cpu_styles = {"pixel_8bit", "pixel_16bit", "retro_3d", "toon", "vector_flat"}
        return bool(
            getattr(self, "gpu_viewport_enabled", False)
            and str(getattr(presentation, "visual_style", "") or "") not in reference_cpu_styles
            and self.material_preview_active()
            and gpu is not None
            and gpu.isVisible()
            and gpu.ready
            and geometry is not None
            and geometry.vertex_count == len(getattr(self.mesh, "vertices", []) or [])
        )

    @Slot(str)
    def on_gpu_viewport_failed(self, message: str) -> None:
        self.gpu_viewport_enabled = False
        self._gpu_viewport_error = str(message or "GPU viewport initialization failed.")
        gpu = getattr(self, "gpu_viewport", None)
        if gpu is not None:
            gpu.hide()
        self._resolved_shaded_status = f"GPU viewport unavailable; CPU fallback active: {self._gpu_viewport_error[:100]}"
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def sync_gpu_camera(self) -> None:
        gpu = getattr(self, "gpu_viewport", None)
        if not getattr(self, "gpu_viewport_enabled", False) or gpu is None or not gpu.ready:
            return
        camera = getattr(self, "viewport_camera", None)
        if camera is None:
            return
        gpu.set_camera(camera.eye, camera.target, camera.fov_degrees, camera.aspect_ratio)

    def _representative_gpu_material(self) -> dict[str, Any]:
        fallback = QColor(getattr(self.mesh, "proxy_fill_color", QColor(125, 145, 170)))
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if not isinstance(proxy, (dict, SceneProxyInstance)) or not bool(proxy.get("visible", True)):
                continue
            materials = proxy.get("materials") or []
            if materials and isinstance(materials[0], SceneProxyMaterialBinding):
                material = materials[0]
                textures = dict(material.texture_paths) if self.show_texture else {}
                emission = tuple(material.emission_color or (0.0, 0.0, 0.0))
                return {
                    "color": QColor(material.color),
                    "roughness": float(material.roughness),
                    "metalness": float(material.metalness),
                    "base_color_texture": str(textures.get("base_color") or ""),
                    "normal_texture": str(textures.get("normal") or ""),
                    "roughness_texture": str(textures.get("roughness") or ""),
                    "metalness_texture": str(textures.get("metalness") or ""),
                    "emission_texture": str(textures.get("emission") or ""),
                    "opacity_texture": str(textures.get("opacity") or ""),
                    "emission_color": QColor.fromRgbF(*[max(0.0, min(1.0, float(value))) for value in emission[:3]]),
                    "opacity": float(material.opacity),
                    "transmission": float(material.transmission),
                    "ior": float(material.ior),
                    "thickness": float(material.thickness),
                    "clearcoat": float(material.clearcoat),
                    "attenuation_color": str(material.attenuation_color),
                    "attenuation_distance": float(material.attenuation_distance),
                }
            color = proxy.get("material_color")
            if isinstance(color, QColor):
                fallback = QColor(color)
                break
        return {
            "color": fallback,
            "roughness": 0.5,
            "metalness": 0.0,
            "base_color_texture": str(getattr(self.mesh, "sample_albedo_path", "") or "") if self.show_texture else "",
            "opacity": 1.0,
            "transmission": 0.0,
            "ior": 1.5,
            "thickness": 0.0,
            "clearcoat": 0.0,
            "attenuation_color": "#ffffff",
            "attenuation_distance": 1000.0,
        }

    @staticmethod
    def _load_viewport_render_preferences() -> tuple[str, float, str]:
        try:
            from tech_connector.services.settings_service import load_settings

            settings = load_settings()
            return (
                str(settings.get("viewport_environment_texture") or ""),
                max(0.0, min(16.0, float(settings.get("viewport_environment_exposure", 1.0) or 1.0))),
                str(settings.get("viewport_lighting_profile") or "daylight"),
            )
        except Exception:
            return "", 1.0, "daylight"

    def _save_viewport_render_preferences(self) -> None:
        try:
            from tech_connector.services.settings_service import load_settings, save_settings

            settings = load_settings()
            settings["viewport_environment_texture"] = str(self.viewport_environment_texture or "")
            settings["viewport_environment_exposure"] = float(self.viewport_environment_exposure)
            settings["viewport_lighting_profile"] = str(self.viewport_lighting_profile or "daylight")
            save_settings(settings)
        except Exception:
            LOGGER.warning("Could not persist viewport lighting preferences.", exc_info=True)

    @staticmethod
    def _load_viewport_debug_preferences() -> tuple[bool, bool, bool, float, float, int, bool]:
        try:
            from tech_connector.services.settings_service import load_settings

            settings = load_settings()
            return (
                bool(settings.get("viewport_show_object_vectors", False)),
                bool(settings.get("viewport_show_vertex_normals", False)),
                bool(settings.get("viewport_show_face_normals", False)),
                max(0.01, min(1000.0, float(settings.get("viewport_debug_vector_length", 0.35) or 0.35))),
                max(0.001, min(1000.0, float(settings.get("viewport_debug_normal_length", 0.2) or 0.2))),
                max(1, min(1024, int(settings.get("viewport_debug_normal_stride", 8) or 8))),
                bool(settings.get("viewport_show_simulation_diagnostics", False)),
            )
        except Exception:
            return False, False, False, 0.35, 0.2, 8, False

    def _save_viewport_debug_preferences(self) -> None:
        try:
            from tech_connector.services.settings_service import load_settings, save_settings

            settings = load_settings()
            settings["viewport_show_object_vectors"] = bool(self.show_object_vector_handles)
            settings["viewport_show_vertex_normals"] = bool(self.show_vertex_normals)
            settings["viewport_show_face_normals"] = bool(self.show_face_normals)
            settings["viewport_debug_vector_length"] = float(self.debug_vector_length)
            settings["viewport_debug_normal_length"] = float(self.debug_normal_length)
            settings["viewport_debug_normal_stride"] = int(self.debug_normal_stride)
            settings["viewport_show_simulation_diagnostics"] = bool(self.show_simulation_diagnostics)
            save_settings(settings)
        except Exception:
            LOGGER.warning("Could not persist viewport debug preferences.", exc_info=True)

    def set_viewport_debug_setting(self, name: str, value: Any) -> None:
        if name in {"show_object_vector_handles", "show_vertex_normals", "show_face_normals", "show_simulation_diagnostics"}:
            setattr(self, name, bool(value))
        elif name == "debug_vector_length":
            self.debug_vector_length = max(0.01, min(1000.0, float(value)))
        elif name == "debug_normal_length":
            self.debug_normal_length = max(0.001, min(1000.0, float(value)))
        elif name == "debug_normal_stride":
            self.debug_normal_stride = max(1, min(1024, int(value)))
        else:
            raise ValueError(f"Unknown viewport debug setting: {name}")
        self._save_viewport_debug_preferences()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def choose_viewport_environment(self) -> None:
        try:
            from tech_connector.services.project_directory_service import project_directories_from_environment

            start = str(project_directories_from_environment().art_source)
        except Exception:
            start = str(Path.home())
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Select Viewport Environment",
            start,
            "Environment Images (*.hdr *.exr *.png *.jpg *.jpeg);;All Files (*)",
        )
        if not selected:
            return
        self.viewport_environment_texture = selected
        self._save_viewport_render_preferences()
        self.sync_gpu_viewport()

    def clear_viewport_environment(self) -> None:
        self.viewport_environment_texture = ""
        self._save_viewport_render_preferences()
        self.sync_gpu_viewport()

    def set_viewport_environment_exposure(self, exposure: float) -> None:
        self.viewport_environment_exposure = max(0.0, min(16.0, float(exposure)))
        self._save_viewport_render_preferences()
        self.sync_gpu_viewport()

    def set_viewport_lighting_profile(self, profile_id: str) -> None:
        from tech_connector.game_engine.rendering.lighting_profile_service import lighting_profile

        profile = lighting_profile(profile_id)
        self.viewport_lighting_profile = profile.profile_id
        self.viewport_environment_exposure = max(
            0.0, min(16.0, float(profile.rendering.get("exposure", 1.0)))
        )
        self._save_viewport_render_preferences()
        gpu = getattr(self, "gpu_viewport", None)
        if gpu is not None:
            gpu.set_lighting_profile(profile.profile_id)
        self._resolved_shaded_status = f"Lighting: {profile.display_name}"
        self.update_viewport_status()
        self.sync_gpu_viewport()

    def sync_gpu_viewport(self, *, full: bool = False) -> bool:
        if full:
            self.invalidate_paint_raycast_cache()
        gpu = getattr(self, "gpu_viewport", None)
        if not getattr(self, "gpu_viewport_enabled", False) or gpu is None:
            return False
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        reference_cpu_styles = {"pixel_8bit", "pixel_16bit", "retro_3d", "toon", "vector_flat"}
        requested = (
            self.material_preview_active()
            and str(getattr(presentation, "visual_style", "") or "") not in reference_cpu_styles
        )
        gpu.setVisible(requested)
        if not requested:
            release = getattr(self.mesh, "release_source_texture_images", None)
            if callable(release):
                release()
            return False
        topology_signature = (
            f"{len(getattr(self.mesh, 'vertices', []) or [])}:"
            f"{len(getattr(self.mesh, 'faces', []) or [])}:"
            f"{len(getattr(self.mesh, 'scene_proxy_objects', []) or [])}"
        )
        geometry = getattr(gpu, "geometry", None)
        if full or geometry is None or geometry.topology_signature != topology_signature:
            gpu.set_scene(
                self.mesh,
                getattr(self, "_dcc_deformation_bindings", {}) or {},
                topology_signature=topology_signature,
            )
        material = self._representative_gpu_material()
        gpu.set_lighting_profile(self.viewport_lighting_profile)
        material["environment_texture"] = str(self.viewport_environment_texture or "")
        material["exposure"] = float(self.viewport_environment_exposure)
        gpu.set_material(**material)
        self.sync_gpu_camera()
        if getattr(self, "canvas", None) is not None:
            self.canvas.raise_()
        return True

    def invalidate_paint_raycast_cache(self) -> None:
        self._paint_geometry_revision = int(getattr(self, "_paint_geometry_revision", 0)) + 1
        self._paint_raycast_cache_key = None
        self._paint_raycast_cache = None

    def _stop_material_refresh_work(self) -> None:
        self.show_resolved_shaded_frames = False
        self._set_button_checked_quietly("resolved_shaded_btn", False)
        timer = getattr(self, "resolved_shaded_frame_timer", None)
        if timer is not None:
            timer.stop()
        release = getattr(self.mesh, "release_source_texture_images", None)
        if callable(release):
            release()

    def _set_button_checked_quietly(self, button_name: str, checked: bool) -> None:
        button = getattr(self, button_name, None)
        if button is None:
            return
        button.blockSignals(True)
        try:
            button.setChecked(bool(checked))
        finally:
            button.blockSignals(False)

    def _sync_display_button_states(self) -> None:
        self._set_button_checked_quietly("shader_mode_btn", str(getattr(self, "viewport_shading_mode", "")).lower() == "shader")
        self._set_button_checked_quietly("texture_btn", bool(getattr(self, "show_texture", False)))
        self._set_button_checked_quietly("wire_btn", bool(getattr(self, "show_wireframe", False)))

    def set_viewport_display_preset(self, preset: str) -> None:
        preset_key = str(preset or "").strip().lower()
        self.viewport_display_source = "compiled"
        self.active_dcc_view_provider = ""
        self.stop_dcc_viewport_stream()
        if preset_key == "wire":
            self.viewport_shading_mode = "Highlight"
            self.show_texture = False
            self.show_wireframe = True
        elif preset_key == "shader":
            self.viewport_shading_mode = "Shader"
            self.show_texture = True
            self.show_wireframe = False
            self.schedule_resolved_shaded_refresh("shader hotkey")
        else:
            self.viewport_shading_mode = "Highlight"
            self.show_texture = False
            self.show_wireframe = False
        if not self.material_preview_active():
            self._stop_material_refresh_work()
        self.sync_gpu_viewport(full=False)
        self._sync_display_button_states()
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def set_dcc_viewport_display(self, provider: str) -> None:
        provider_key = str(provider or "").strip().lower()
        if not provider_key:
            return
        provider_base = dcc_provider_base_key(provider_key)
        if ":" not in provider_key:
            preferred = str((getattr(self, "_dcc_preferred_session_keys", {}) or {}).get(provider_base, "") or "").lower()
            loaded_matches = [
                str(key).lower()
                for key in (getattr(self, "_loaded_scene_providers", []) or [])
                if dcc_provider_base_key(str(key)) == provider_base
            ]
            if preferred in loaded_matches:
                provider_key = preferred
            elif len(loaded_matches) == 1:
                provider_key = loaded_matches[0]
        self.viewport_display_source = "dcc"
        self.active_dcc_view_provider = provider_key
        self.show_resolved_shaded_frames = False
        self._set_button_checked_quietly("resolved_shaded_btn", False)
        if getattr(self, "resolved_shaded_frame_timer", None) is not None:
            self.resolved_shaded_frame_timer.stop()
        self.sync_gpu_viewport(full=False)
        self.start_dcc_viewport_stream(provider_key)
        self.drive_dcc_camera_enabled = True
        self._set_button_checked_quietly("drive_camera_btn", True)
        self.request_dcc_camera_possession_async(include_unreal=True, reason=f"{provider_base} stream mode")
        self._resolved_shaded_status = f"{provider_base.title()} isolation: source surfaces hidden; controls remain selectable"
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    @Slot(QImage, str)
    def on_dcc_viewport_stream_frame(self, image: QImage, provider: str) -> None:
        if str(getattr(self, "viewport_display_source", "") or "").lower() != "dcc":
            return
        if str(provider or "").lower() != str(getattr(self, "active_dcc_view_provider", "") or "").lower():
            return
        self._dcc_stream_frame = image
        self._dcc_stream_provider = str(provider or "").lower()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    @Slot(str)
    def on_dcc_viewport_stream_status(self, message: str) -> None:
        self._dcc_stream_status = str(message or "")
        if str(getattr(self, "viewport_display_source", "") or "").lower() == "dcc":
            self._resolved_shaded_status = self._dcc_stream_status
            self.update_viewport_status()

    def start_dcc_viewport_stream(self, provider: str) -> bool:
        stream = getattr(self, "dcc_viewport_stream", None)
        if stream is None or not self.isVisible():
            return False
        provider_key = str(provider or "").lower()
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider_key) or {}
        crop_rect = None
        metadata = snapshot.get("viewport_capture") if isinstance(snapshot.get("viewport_capture"), dict) else {}
        values = metadata.get("viewport_rect") if isinstance(metadata, dict) else None
        if isinstance(values, (list, tuple)) and len(values) >= 4:
            crop_rect = QRectF(*[float(value) for value in values[:4]])
        self._dcc_stream_frame = QImage()
        self._dcc_stream_provider = provider_key
        return bool(
            stream.start(
                provider_key,
                scene=str(snapshot.get("scene") or ""),
                crop_rect=crop_rect,
                process_id=int(snapshot.get("process_id") or snapshot.get("pid") or 0),
            )
        )

    def stop_dcc_viewport_stream(self) -> None:
        stream = getattr(self, "dcc_viewport_stream", None)
        if stream is not None:
            stream.stop()
        self._dcc_stream_frame = QImage()
        self._dcc_stream_provider = ""

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
            self.show_wireframe = False
            self._set_button_checked_quietly("wire_btn", False)
            self.show_resolved_shaded_frames = True
            self._set_button_checked_quietly("resolved_shaded_btn", True)
            self.schedule_resolved_shaded_refresh("shader mode")
        else:
            self.show_wireframe = True
            self._set_button_checked_quietly("wire_btn", True)
            self._stop_material_refresh_work()
        self.sync_gpu_viewport(full=False)
        self._sync_display_button_states()
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
        if not self.material_preview_active() or not getattr(self, "show_resolved_shaded_frames", False):
            return
        if getattr(self, "live_dcc_refresh_btn", None) is not None and self.live_dcc_refresh_btn.isChecked():
            self._resolved_shaded_status = "Resolved shaded refresh paused during Live"
            self.update_viewport_status()
            return
        timer = getattr(self, "resolved_shaded_frame_timer", None)
        if timer is None:
            return
        self._resolved_shaded_status = f"Resolved shaded frame pending: {reason}" if reason else "Resolved shaded frame pending"
        self.update_viewport_status()
        timer.start()

    def refresh_resolved_shaded_frames(self) -> None:
        if not self.material_preview_active():
            return
        if getattr(self, "_resolved_shaded_capture_thread", None) is not None:
            return
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
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
        requests: list[dict[str, Any]] = []
        immediate_errors: list[str] = []
        for provider in providers:
            provider_base = dcc_provider_base_key(provider)
            if provider_base == "unreal" and not bool(getattr(self, "allow_unreal_resolved_frames", False)):
                immediate_errors.append("unreal: resolved frames paused for responsiveness")
                continue
            path = out_dir / f"{provider}_{int(time.time() * 1000)}.png"
            if provider_base == "maya":
                code = maya_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame)
                timeout = 12.0
            elif provider_base == "blender":
                code = blender_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame)
                timeout = 18.0
            elif provider_base == "motionbuilder":
                code = motionbuilder_shaded_frame_code(str(path), width=capture_w, height=capture_h, frame=frame)
                timeout = 18.0
            elif provider_base == "unreal":
                code = unreal_shaded_frame_code(
                    str(path),
                    width=capture_w,
                    height=capture_h,
                    frame=frame,
                    drive_viewport_camera=bool(getattr(self, "drive_dcc_camera_enabled", False)),
                )
                timeout = 15.0
            else:
                continue
            requests.append({"provider": provider, "code": code, "timeout": timeout})
        if not requests:
            if immediate_errors:
                self._resolved_shaded_status = "Resolved shaded frame skipped: " + "; ".join(immediate_errors)[:140]
                self.update_viewport_status()
            return
        thread = QThread(self)
        worker = DccResolvedFrameWorker(requests)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.frames_ready.connect(lambda frames, errors: self.on_resolved_shaded_frames_ready(frames, immediate_errors + errors))
        worker.frames_ready.connect(thread.quit)
        worker.frames_ready.connect(worker.deleteLater)
        thread.finished.connect(self.on_resolved_shaded_capture_finished)
        thread.finished.connect(thread.deleteLater)
        self._resolved_shaded_capture_thread = thread
        self._resolved_shaded_capture_worker = worker
        self._resolved_shaded_status = f"Resolved shaded capture running for frame {frame}"
        self.update_viewport_status()
        thread.start()

    @Slot(list, list)
    def on_resolved_shaded_frames_ready(self, frames: list[dict[str, Any]], errors: list[str]) -> None:
        refreshed = []
        failures = list(errors or [])
        for payload in frames or []:
            provider = str(payload.get("provider_id") or "")
            image = QImage(str(payload.get("path") or ""))
            if image.isNull():
                failures.append(f"{provider}: could not read resolved frame")
                continue
            self._resolved_shaded_frames[provider] = image
            self._resolved_shaded_frame_paths[provider] = str(payload.get("path") or "")
            refreshed.append(provider)
        if refreshed:
            self._resolved_shaded_status = f"Resolved shaded frame: {', '.join(refreshed)}"
            if failures:
                self._resolved_shaded_status += f" | partial: {'; '.join(failures)[:100]}"
        elif failures:
            self._resolved_shaded_status = "Resolved shaded frame failed: " + "; ".join(failures)[:140]
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    @Slot()
    def on_resolved_shaded_capture_finished(self) -> None:
        self._resolved_shaded_capture_thread = None
        self._resolved_shaded_capture_worker = None

    def toggle_wireframe_display(self, checked: bool):
        self.show_wireframe = bool(checked)
        self._sync_display_button_states()
        if hasattr(self, "canvas") and self.canvas:
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
        # The existing DCC picker is app-scoped. Resolve it to the user's
        # preferred concrete session, or prompt only when that app has several.
        if dcc_provider_base_key(provider) != "all_open":
            provider = self.resolve_dcc_session_key(provider, purpose="import scene", interactive=True)
        providers = self._scene_snapshot_provider_keys(provider)
        self._load_dcc_scene_providers(providers, show_message=True, replace_existing=False)

    def _load_dcc_preferred_session_keys(self) -> dict[str, str]:
        try:
            from tech_connector.services.settings_service import load_settings
            raw = load_settings().get("dcc_preferred_session_keys", {})
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            return {}
        return {
            dcc_provider_base_key(key): str(value).strip().lower()
            for key, value in raw.items()
            if dcc_provider_base_key(key) and ":" in str(value)
        }

    def _load_dcc_scene_restore_policy(self) -> str:
        from tech_connector.game_engine.integration.dcc_scene_restoration_service import normalize_restore_policy

        try:
            from tech_connector.services.settings_service import load_settings

            return normalize_restore_policy(load_settings().get("dcc_scene_restore_policy", "ask"))
        except Exception:
            return "ask"

    def set_dcc_scene_restore_policy(self, policy: str) -> None:
        from tech_connector.game_engine.integration.dcc_scene_restoration_service import normalize_restore_policy

        self._dcc_scene_restore_policy = normalize_restore_policy(policy)
        try:
            from tech_connector.services.settings_service import load_settings, save_settings

            settings = load_settings()
            settings["dcc_scene_restore_policy"] = self._dcc_scene_restore_policy
            save_settings(settings)
        except Exception as exc:
            self.record_nonfatal_diagnostic("Could not save the DCC restoration policy", exc, surface=True)

    def show_dcc_scene_restore_status(self) -> None:
        report = dict(getattr(self, "_last_dcc_scene_restore_report", {}) or {})
        entries = list(report.get("entries") or [])
        if not entries:
            cached = len(getattr(self, "_dcc_scene_snapshots", {}) or {})
            QMessageBox.information(
                self,
                "Linked Source Status",
                f"No live restoration report is available. Cached DCC sources: {cached}.",
            )
            return
        lines = []
        for entry in entries[:40]:
            source = dict(entry.get("source") or {})
            provider = str(source.get("provider") or "DCC").title()
            source_path = str(source.get("source_path") or "Unsaved session")
            status = str(entry.get("status") or "unknown").replace("_", " ")
            changed = " | changed since save" if entry.get("source_changed") else ""
            message = str(entry.get("message") or "").strip()
            lines.append(f"{provider} | {status}{changed}\n{source_path}" + (f"\n{message}" if message else ""))
        QMessageBox.information(self, "Linked Source Status", "\n\n".join(lines))

    def _save_dcc_preferred_session_keys(self) -> None:
        try:
            from tech_connector.services.settings_service import load_settings, save_settings
            settings = load_settings()
            settings["dcc_preferred_session_keys"] = dict(getattr(self, "_dcc_preferred_session_keys", {}) or {})
            save_settings(settings)
        except Exception as exc:
            self.record_nonfatal_diagnostic("Could not save the preferred DCC session", exc, surface=True)

    def remember_dcc_session_choice(self, session_key: str) -> None:
        provider_base = dcc_provider_base_key(session_key)
        if not provider_base or ":" not in str(session_key):
            return
        self._dcc_preferred_session_keys[provider_base] = str(session_key).strip().lower()
        self._save_dcc_preferred_session_keys()

    def resolve_dcc_session_key(self, provider: str, *, purpose: str = "bridge call", interactive: bool = True) -> str:
        provider_raw = str(provider or "").strip().lower()
        provider_base = dcc_provider_base_key(provider_raw)
        if not provider_base or provider_base == "all_open" or ":" in provider_raw:
            return provider_raw
        preferred = (getattr(self, "_dcc_preferred_session_keys", {}) or {}).get(provider_base, "")
        live_keys = [str(source.get("key") or "") for source in self.discover_importable_dcc_scene_sources([provider_base])]
        live_keys = [key for key in live_keys if key]
        if preferred and preferred in live_keys:
            return preferred
        if len(live_keys) == 1:
            self.remember_dcc_session_choice(live_keys[0])
            return live_keys[0]
        if len(live_keys) > 1 and interactive and self.isVisible():
            dialog = DccSceneImportDialog(
                [source for source in self.discover_importable_dcc_scene_sources([provider_base]) if source.get("key") in live_keys],
                self,
                title=f"Choose {provider_base.title()} Session",
                message=f"Multiple {provider_base.title()} sessions are available. Choose which one to use for this {purpose}.",
            )
            if dialog.exec() == QDialog.Accepted and dialog.selected_sources:
                chosen = str(dialog.selected_sources[0].get("key") or provider_raw).strip().lower()
                self.remember_dcc_session_choice(chosen)
                return chosen
        return provider_raw

    def _load_dcc_scene_providers(
        self,
        providers: list[str],
        *,
        show_message: bool = False,
        replace_existing: bool = False,
        force_rebuild: bool = False,
        fast_transform_only: bool = False,
    ) -> bool:
        if getattr(self, "_dcc_scene_model_thread", None) is not None:
            self._resolved_shaded_status = "Scene model compilation already running"
            self.update_viewport_status()
            return False
        if getattr(self, "_dcc_scene_refresh_busy", False):
            self._resolved_shaded_status = "DCC scene refresh already running"
            self.update_viewport_status()
            return False
        now = time.monotonic()
        explicit_refresh = bool(show_message or replace_existing or force_rebuild)
        min_interval = 0.02 if fast_transform_only else (0.45 if explicit_refresh else 1.25)
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
                fast_transform_only=fast_transform_only,
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
        fast_transform_only: bool = False,
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
            provider_base = dcc_provider_base_key(provider)
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
                "include_geometry": False if fast_transform_only else not lightweight_preflight,
                "limit": 500,
                "timeout": 2.0 if lightweight_preflight else 12.0,
            }
            if provider_base in {"blender", "3dsmax", "houdini", "unreal", "unity", "substance_painter"}:
                kwargs["include_materials"] = not (fast_transform_only or lightweight_preflight)
            if provider_base == "maya":
                kwargs["meshes_only"] = False
                if fast_transform_only:
                    target_items: list[tuple[str, int]] = []
                    for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
                        if not isinstance(proxy, (dict, SceneProxyInstance)):
                            continue
                        if str(proxy.get("provider_id") or "").lower() != str(provider).lower():
                            continue
                        if not bool(proxy.get("visible", True)):
                            continue
                        mesh_data = proxy.get("mesh_data")
                        topology_state = str(
                            mesh_data.get("topology_state")
                            if isinstance(mesh_data, dict)
                            else getattr(mesh_data, "topology_state", "")
                        )
                        if topology_state not in {"bounds", "mesh"}:
                            continue
                        native_id = str(proxy.get("native_id") or "")
                        if native_id:
                            vertex_count = int(
                                mesh_data.get("source_vertex_count", mesh_data.get("vertex_count", 0))
                                if isinstance(mesh_data, dict)
                                else getattr(mesh_data, "source_vertex_count", 0)
                                or getattr(mesh_data, "vertex_count", 0)
                                or 0
                            )
                            target_items.append((native_id, max(0, vertex_count)))
                    if target_items:
                        max_batch_items = 12
                        max_batch_vertices = 6000
                        cursor = int((getattr(self, "_dcc_fast_refresh_cursor", {}) or {}).get(provider, 0) or 0)
                        cursor = cursor % len(target_items)
                        batch = []
                        batch_vertices = 0
                        visited = 0
                        while visited < len(target_items) and len(batch) < max_batch_items:
                            native_id, vertex_count = target_items[(cursor + visited) % len(target_items)]
                            if batch and batch_vertices + vertex_count > max_batch_vertices:
                                break
                            batch.append(native_id)
                            batch_vertices += vertex_count
                            visited += 1
                            if vertex_count > max_batch_vertices:
                                break
                        self._dcc_fast_refresh_cursor[provider] = (cursor + max(1, visited)) % len(target_items)
                        kwargs["target_native_ids"] = batch
                        kwargs["limit"] = max(1, min(500, len(batch)))
                    else:
                        unchanged_providers.append(provider)
                        continue
                    kwargs["include_geometry"] = True
                    kwargs["include_faces"] = False
                    kwargs["max_vertices_per_object"] = 200000
                    kwargs["max_faces_per_object"] = 200000
                    kwargs["include_cameras"] = False
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
                if fast_transform_only:
                    previous_snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
                    if isinstance(previous_snapshot, dict):
                        if not snapshot_or_error.get("cameras"):
                            snapshot_or_error["cameras"] = copy.deepcopy(previous_snapshot.get("cameras") or [])
                        if not snapshot_or_error.get("active_camera"):
                            snapshot_or_error["active_camera"] = previous_snapshot.get("active_camera", "")
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
        if fast_transform_only and self._apply_fast_transform_snapshot_updates(new_snapshots):
            self._dcc_scene_snapshots.update({
                provider: self._merged_fast_transform_snapshot(provider, snapshot)
                for provider, snapshot in new_snapshots.items()
            })
            self._dcc_snapshot_signatures.update(changed_signatures)
            self._last_scene_refresh_changed = True
            if not getattr(self, "_suppress_dcc_timeline_cache", False):
                self._store_timeline_snapshots(int(getattr(self, "_current_dcc_frame", 1) or 1), new_snapshots)
            self._refresh_coordinate_scale_status()
            self._refresh_camera_authority_choices()
            self.update_viewport_status()
            if hasattr(self, "canvas") and self.canvas:
                self.canvas.update()
            self.schedule_resolved_shaded_refresh("animated scene refreshed")
            return True
        if fast_transform_only:
            self._dcc_scene_snapshots.update({
                provider: self._merged_fast_transform_snapshot(provider, snapshot)
                for provider, snapshot in new_snapshots.items()
            })
            self._dcc_snapshot_signatures.update(changed_signatures)
            self._last_scene_refresh_changed = False
            object_count = sum(len(snapshot.get("objects") or []) for snapshot in new_snapshots.values())
            self._resolved_shaded_status = f"Live DCC cache: {object_count} source object(s), no cheap proxy delta"
            self._refresh_coordinate_scale_status()
            self._refresh_camera_authority_choices()
            self.update_viewport_status()
            return True
        had_existing_snapshots = bool(getattr(self, "_dcc_scene_snapshots", {})) and not replace_existing
        if replace_existing:
            self._dcc_scene_snapshots = {}
            self._dcc_snapshot_signatures = {}
            self._clear_dcc_timeline_snapshot_cache()
        self._dcc_scene_snapshots.update(new_snapshots)
        self._dcc_snapshot_signatures.update(changed_signatures)
        self._last_scene_refresh_changed = True
        if fast_transform_only and not getattr(self, "_suppress_dcc_timeline_cache", False):
            self._store_timeline_snapshots(int(getattr(self, "_current_dcc_frame", 1) or 1), new_snapshots)
        self._loaded_scene_providers = list(self._dcc_scene_snapshots.keys())
        has_renderable_dcc_source = any(
            isinstance(obj, dict) and len(obj.get("bbox") or []) == 6
            for snapshot in self._dcc_scene_snapshots.values()
            for obj in snapshot.get("objects") or []
        )
        if not has_renderable_dcc_source and not self._retained_scene_models():
            self._resolved_shaded_status = (
                "Linked metadata/lookdev source(s): " + ", ".join(self._loaded_scene_providers)
            )
            self._refresh_camera_authority_choices()
            self.update_viewport_status()
            return True
        preserved_center = None
        preserved_scale = None
        if had_existing_snapshots and not replace_existing:
            preserved_center = getattr(self.mesh, "scene_center", None)
            preserved_scale = getattr(self.mesh, "scene_scale", None)
        context = {
            "previous_proxy_state": previous_proxy_state,
            "replace_existing": bool(replace_existing),
            "show_message": bool(show_message),
            "had_existing_snapshots": bool(had_existing_snapshots),
            "new_provider_keys": list(new_snapshots.keys()),
            "new_snapshots": new_snapshots,
        }
        complexity = self._scene_model_compile_complexity()
        if self.isVisible() and complexity >= 50_000:
            return self._start_scene_model_compile(
                scene_center=preserved_center,
                scene_scale=preserved_scale,
                context=context,
                complexity=complexity,
            )
        model = self._compose_loaded_scene_model(
            scene_center=preserved_center,
            scene_scale=preserved_scale,
        )
        return self._apply_compiled_scene_model(model, context, compile_ms=0.0)

    def _scene_model_compile_complexity(self) -> int:
        total = 0
        for snapshot in (getattr(self, "_dcc_scene_snapshots", {}) or {}).values():
            for obj in snapshot.get("objects") or []:
                geometry = obj.get("geometry") if isinstance(obj, dict) else None
                if not isinstance(geometry, dict):
                    continue
                total += int(geometry.get("vertex_count", 0) or len(geometry.get("vertices") or []))
                total += int(geometry.get("face_count", 0) or len(geometry.get("faces") or []))
        native_model = getattr(self, "_native_scene_model", None)
        if native_model is not None:
            total += len(getattr(native_model, "vertices", []) or [])
            total += len(getattr(native_model, "faces", []) or [])
        return total

    def _retained_scene_models(self) -> list[FBXMeshModel]:
        native_model = getattr(self, "_native_scene_model", None)
        return [native_model] if native_model is not None and getattr(native_model, "vertices", None) else []

    def _start_scene_model_compile(
        self,
        *,
        scene_center: tuple[float, float, float] | None,
        scene_scale: float | None,
        context: dict[str, Any],
        complexity: int,
    ) -> bool:
        if getattr(self, "_dcc_scene_model_thread", None) is not None:
            return False
        thread = QThread(self)
        worker = DccSceneModelCompileWorker(
            list((getattr(self, "_dcc_scene_snapshots", {}) or {}).values()),
            scene_center=scene_center,
            scene_scale=scene_scale,
            retained_models=self._retained_scene_models(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_scene_model_compiled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_scene_model_compile)
        thread.finished.connect(thread.deleteLater)
        self._dcc_scene_model_thread = thread
        self._dcc_scene_model_worker = worker
        self._dcc_scene_model_context = dict(context)
        self._resolved_shaded_status = f"Compiling {complexity:,} scene elements in background"
        self.update_viewport_status()
        thread.start()
        return True

    @Slot(object, str, float)
    def _on_scene_model_compiled(self, model: Any, error: str, compile_ms: float) -> None:
        context = dict(getattr(self, "_dcc_scene_model_context", None) or {})
        if error or model is None:
            self._resolved_shaded_status = f"Scene model compilation failed: {str(error)[:140]}"
            self.update_viewport_status()
            if context.get("show_message") and self.isVisible():
                QMessageBox.warning(self, "DCC Scene Load Failed", self._resolved_shaded_status)
            return
        self._apply_compiled_scene_model(model, context, compile_ms=float(compile_ms or 0.0))

    @Slot()
    def _finish_scene_model_compile(self) -> None:
        sender = self.sender()
        current = getattr(self, "_dcc_scene_model_thread", None)
        if current is None or (sender is not None and sender is not current):
            return
        self._dcc_scene_model_thread = None
        self._dcc_scene_model_worker = None
        self._dcc_scene_model_context = None
        pending = dict(getattr(self, "_pending_restored_live_snapshots", {}) or {})
        self._pending_restored_live_snapshots = {}
        if pending:
            QTimer.singleShot(0, lambda snapshots=pending: self._install_restored_dcc_snapshots(snapshots))

    def _detach_scene_model_compile(self) -> None:
        thread = getattr(self, "_dcc_scene_model_thread", None)
        worker = getattr(self, "_dcc_scene_model_worker", None)
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._on_scene_model_compiled)
            except Exception:
                LOGGER.debug("Scene-model worker was already disconnected.", exc_info=True)
        try:
            thread.finished.disconnect(self._finish_scene_model_compile)
        except Exception:
            pass
        self._dcc_scene_model_thread = None
        self._dcc_scene_model_worker = None
        self._dcc_scene_model_context = None
        thread.setParent(QApplication.instance())

    def _apply_saved_mesh_default_pose(self, mesh: FBXMeshModel | None) -> bool:
        """Attach a persisted pose only when it belongs to the rebuilt mesh topology."""
        data = getattr(self, "_saved_mesh_default_pose", None)
        if mesh is None or not isinstance(data, dict) or not data:
            return False
        return mesh.load_default_pose(data)

    def _apply_compiled_scene_model(
        self,
        model: FBXMeshModel,
        context: dict[str, Any],
        *,
        compile_ms: float,
    ) -> bool:
        self.mesh = model
        self._apply_saved_mesh_default_pose(model)
        self.sync_gpu_viewport(full=True)
        self._apply_proxy_refresh_state(context.get("previous_proxy_state") or {})
        self._refresh_coordinate_scale_status()
        self._sync_timeline_range_from_snapshots()
        self._refresh_camera_authority_choices()
        self.refresh_scene_outliner()
        self.show_texture = False
        self._sync_display_button_states()
        if context.get("replace_existing") or (
            context.get("show_message") and not context.get("had_existing_snapshots")
        ):
            self.frame_mesh_camera()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        new_provider_keys = list(context.get("new_provider_keys") or [])
        if compile_ms > 0.0:
            self._resolved_shaded_status = f"Scene model compiled in {compile_ms:.0f} ms"
            self.update_viewport_status()
        if context.get("show_message") and self.isVisible():
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
                    f"Added/refreshed {', '.join(new_provider_keys)}.\n"
                    f"Active federated scene: {object_count} isolated visible elements from "
                    f"{', '.join(self._loaded_scene_providers)} and {camera_count} cameras.\n\n"
                    f"True mesh geometry: {real_mesh_count}\n"
                    f"Bounds fallback elements: {bounds_count}\n\n"
                    f"Coordinate scale: {getattr(self, '_coordinate_scale_status', '') or 'not available'}\n\n"
                    "The Tech Connector viewer renders this locally for fluid navigation."
                ),
            )
        self.schedule_resolved_shaded_refresh("scene refreshed")
        self._maybe_auto_start_timeline_cache(dict(context.get("new_snapshots") or {}))
        QTimer.singleShot(0, self._start_maya_deformation_bindings_for_loaded_scenes)
        return True

    def _compose_loaded_scene_model(
        self,
        *,
        scene_center: tuple[float, float, float] | None = None,
        scene_scale: float | None = None,
    ) -> FBXMeshModel:
        """Compose linked snapshots with locally owned geometry without changing either cache."""
        return FBXMeshModel.from_scene_snapshots(
            list((getattr(self, "_dcc_scene_snapshots", {}) or {}).values()),
            scene_center=scene_center,
            scene_scale=scene_scale,
            retained_models=self._retained_scene_models(),
        )

    def _dcc_timeline_cache_fingerprint(self, provider: str) -> str:
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
        if not isinstance(snapshot, dict):
            return ""
        scene_path = str(snapshot.get("scene") or snapshot.get("file") or snapshot.get("project") or "")
        scene_mtime = ""
        if scene_path and os.path.exists(scene_path):
            try:
                scene_mtime = f"{os.path.getmtime(scene_path):.6f}"
            except Exception:
                scene_mtime = ""
        object_keys = []
        for obj in snapshot.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            object_keys.append(
                (
                    str(obj.get("native_id") or obj.get("name") or ""),
                    str(obj.get("type") or obj.get("kind") or ""),
                    str(obj.get("mesh_topology_state") or obj.get("topology_state") or ""),
                )
            )
        payload = {
            "provider": provider,
            "scene": scene_path,
            "mtime": scene_mtime,
            "scene_revision": snapshot.get("scene_revision"),
            "objects": sorted(object_keys),
        }
        try:
            return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        except Exception:
            return str(payload)

    def _start_maya_deformation_bindings_for_loaded_scenes(self) -> None:
        if not self.isVisible():
            return
        for provider in list(getattr(self, "_loaded_scene_providers", []) or []):
            if dcc_provider_base_key(provider) == "maya":
                self._start_maya_deformation_binding(provider)

    def _start_maya_deformation_binding(self, provider: str) -> None:
        provider_key = str(provider or "").strip().lower()
        if not provider_key or provider_key in getattr(self, "_dcc_deformation_binding_threads", {}):
            return
        if (
            getattr(self, "_dcc_timeline_cache_thread", None) is not None
            and str(getattr(self, "_dcc_timeline_cache_provider", "") or "").lower() == provider_key
        ):
            self._pending_deformation_binding_providers.add(provider_key)
            self._resolved_shaded_status = (
                f"Skeletal cache for {provider_key} is waiting for timeline caching to finish"
            )
            self.update_viewport_status()
            return
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider_key, {})
        if not isinstance(snapshot, dict):
            return
        target_native_ids = [
            str(item.get("native_id") or "")
            for item in snapshot.get("objects") or []
            if isinstance(item, dict)
            and str(item.get("native_id") or "")
            and isinstance(item.get("geometry"), dict)
            and str((item.get("geometry") or {}).get("representation") or "").lower() == "mesh"
        ]
        target_native_ids = list(dict.fromkeys(target_native_ids))
        if not target_native_ids:
            return
        fingerprint = self._dcc_timeline_cache_fingerprint(provider_key)
        if (
            fingerprint
            and fingerprint == (getattr(self, "_dcc_deformation_binding_fingerprints", {}) or {}).get(provider_key)
            and provider_key in getattr(self, "_dcc_deformation_bindings", {})
        ):
            return
        thread = QThread(self)
        worker = DccDeformationBindingWorker(
            provider_key,
            target_native_ids,
            request_fingerprint=fingerprint,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_maya_deformation_binding)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda key=provider_key, current=thread: self._finish_maya_deformation_binding_thread(key, current)
        )
        thread.finished.connect(thread.deleteLater)
        self._dcc_deformation_binding_threads[provider_key] = thread
        self._dcc_deformation_binding_workers[provider_key] = worker
        self._resolved_shaded_status = f"Building skeletal cache for {provider_key} in the background"
        self.update_viewport_status()
        thread.start()

    @Slot(str, bool, object, str)
    def _capture_maya_deformation_binding(
        self,
        provider: str,
        ok: bool,
        binding: object,
        message: str,
    ) -> None:
        provider_key = str(provider or "").strip().lower()
        if ok and isinstance(binding, dict):
            request_fingerprint = str(binding.get("request_fingerprint") or "")
            current_fingerprint = self._dcc_timeline_cache_fingerprint(provider_key)
            if (
                request_fingerprint
                and current_fingerprint
                and request_fingerprint != current_fingerprint
            ):
                self._resolved_shaded_status = (
                    f"Discarded stale skeletal cache for {provider_key}; rebuilding from the current scene"
                )
                self.update_viewport_status()
                QTimer.singleShot(150, lambda key=provider_key: self._start_maya_deformation_binding(key))
                return
            self._dcc_deformation_bindings[provider_key] = binding
            self._dcc_deformation_binding_fingerprints[provider_key] = self._dcc_timeline_cache_fingerprint(provider_key)
            try:
                imported_blobs = self.editable_rig_graph.merge_deformation_binding(
                    binding,
                    provider_id=provider_key,
                )
                topology = binding.get("rig_topology")
                if isinstance(topology, dict):
                    self.editable_rig_graph.merge_rig_topology(
                        topology,
                        provider_id=provider_key,
                    )
                self._federated_scene_blobs.update(imported_blobs)
            except Exception as exc:
                message = f"{message} Rig authoring import warning: {exc}"
            self.sync_gpu_viewport(full=True)
            self.refresh_scene_outliner()
        self._resolved_shaded_status = str(message or ("Skeletal cache ready" if ok else "Skeletal cache failed"))
        self.update_viewport_status()

    def _finish_maya_deformation_binding_thread(self, provider: str, thread: QThread) -> None:
        if (getattr(self, "_dcc_deformation_binding_threads", {}) or {}).get(provider) is thread:
            self._dcc_deformation_binding_threads.pop(provider, None)
            self._dcc_deformation_binding_workers.pop(provider, None)
        pending = getattr(self, "_pending_timeline_cache_request", None)
        if isinstance(pending, dict) and str(pending.get("provider") or "").lower() == str(provider).lower():
            self._pending_timeline_cache_request = None
            QTimer.singleShot(0, lambda request=dict(pending): self.start_timeline_cache(**request))

    def _detach_deformation_binding_workers(self) -> None:
        threads = dict(getattr(self, "_dcc_deformation_binding_threads", {}) or {})
        workers = dict(getattr(self, "_dcc_deformation_binding_workers", {}) or {})
        self._dcc_deformation_binding_threads = {}
        self._dcc_deformation_binding_workers = {}
        self._pending_timeline_cache_request = None
        self._pending_deformation_binding_providers.clear()
        for provider, thread in threads.items():
            worker = workers.get(provider)
            if worker is not None:
                worker.cancel()
                try:
                    worker.finished.disconnect(self._capture_maya_deformation_binding)
                except Exception as exc:
                    LOGGER.debug("Deformation worker was already disconnected.", exc_info=True)
            try:
                thread.requestInterruption()
            except Exception:
                pass
            try:
                thread.setParent(QApplication.instance())
            except Exception:
                pass

    def _clear_dcc_timeline_snapshot_cache(self) -> None:
        archives = dict(getattr(self, "_dcc_timeline_archives", {}) or {})
        if archives:
            archive_paths = set(archives)
            for snapshot in list(self._dcc_timeline_snapshot_cache.values()):
                self._strip_timeline_archive_buffers(snapshot, archive_paths)
            for snapshot in list((getattr(self, "_dcc_scene_snapshots", {}) or {}).values()):
                self._strip_timeline_archive_buffers(snapshot, archive_paths)
        self._dcc_timeline_snapshot_cache.clear()
        self._dcc_timeline_snapshot_cache_order.clear()
        self._dcc_timeline_archives.clear()
        for archive in archives.values():
            archive.close(delete=True)

    def _strip_timeline_archive_buffers(self, snapshot: dict[str, Any], archive_paths: set[str]) -> None:
        if not isinstance(snapshot, dict):
            return
        archive = snapshot.get("timeline_archive")
        archive_path = str(getattr(archive, "path", "") or "")
        if archive_path in archive_paths:
            snapshot.pop("timeline_archive", None)
            snapshot.pop("timeline_archive_slot", None)
            snapshot.pop("timeline_archive_frame", None)
        for obj in snapshot.get("objects") or []:
            geometry = obj.get("geometry") if isinstance(obj, dict) else None
            if not isinstance(geometry, dict):
                continue
            if str(geometry.get("timeline_archive_path") or "") not in archive_paths:
                continue
            geometry.pop("vertices_f32", None)
            geometry.pop("vertex_float_offset", None)
            geometry.pop("vertex_encoding", None)
            geometry.pop("timeline_archive_path", None)

    def _cached_timeline_snapshots(self, providers: list[str], frame: int) -> dict[str, dict[str, Any]] | None:
        cached: dict[str, dict[str, Any]] = {}
        for provider in providers:
            key = (provider, int(frame), self._dcc_timeline_cache_fingerprint(provider))
            snapshot = self._dcc_timeline_snapshot_cache.get(key)
            if not isinstance(snapshot, dict):
                return None
            cached[provider] = snapshot
        return cached

    def _store_timeline_snapshots(self, frame: int, snapshots: dict[str, dict[str, Any]]) -> None:
        for provider, snapshot in (snapshots or {}).items():
            if not isinstance(snapshot, dict):
                continue
            archive = snapshot.get("timeline_archive")
            if isinstance(archive, TimelineFrameArchive):
                self._dcc_timeline_archives[archive.path] = archive
            key = (provider, int(frame), self._dcc_timeline_cache_fingerprint(provider))
            self._dcc_timeline_snapshot_cache[key] = snapshot
            if key in self._dcc_timeline_snapshot_cache_order:
                self._dcc_timeline_snapshot_cache_order.remove(key)
            self._dcc_timeline_snapshot_cache_order.append(key)
        while len(self._dcc_timeline_snapshot_cache_order) > int(getattr(self, "_dcc_timeline_snapshot_cache_limit", 480) or 480):
            old_key = self._dcc_timeline_snapshot_cache_order.pop(0)
            self._dcc_timeline_snapshot_cache.pop(old_key, None)

    def _timeline_frame_range(self) -> tuple[int, int]:
        start = int(getattr(self, "_dcc_timeline_frame_start", 1) or 1)
        end = int(getattr(self, "_dcc_timeline_frame_end", start) or start)
        if end >= start:
            return start, end
        for snapshot in (getattr(self, "_dcc_scene_snapshots", {}) or {}).values():
            if not isinstance(snapshot, dict):
                continue
            start = snapshot.get("frame_start") or snapshot.get("start_frame")
            end = snapshot.get("frame_end") or snapshot.get("end_frame")
            try:
                if start is not None and end is not None:
                    return int(float(start)), int(float(end))
            except (TypeError, ValueError):
                LOGGER.debug("A linked DCC timeline range was invalid and was ignored.", exc_info=True)
        return 1, 120

    def _sync_timeline_range_from_snapshots(self) -> None:
        start = None
        end = None
        fps = None
        for snapshot in (getattr(self, "_dcc_scene_snapshots", {}) or {}).values():
            if not isinstance(snapshot, dict):
                continue
            try:
                raw_start = snapshot.get("frame_start") or snapshot.get("start_frame")
                raw_end = snapshot.get("frame_end") or snapshot.get("end_frame")
                if raw_start is None or raw_end is None:
                    continue
                s = int(round(float(raw_start)))
                e = int(round(float(raw_end)))
                start = s if start is None else min(start, s)
                end = e if end is None else max(end, e)
                if snapshot.get("fps") is not None:
                    fps = int(round(float(snapshot.get("fps") or 24)))
            except Exception:
                continue
        if start is None or end is None or end < start:
            return
        self._dcc_timeline_frame_start = int(start)
        self._dcc_timeline_frame_end = int(end)
        timeline = getattr(self, "anim_timeline", None)
        sequence = getattr(timeline, "sequence", None)
        if sequence is not None:
            frame_count = max(1, int(end) - int(start) + 1)
            current_count = len(getattr(sequence, "frames", []) or [])
            if current_count != frame_count:
                try:
                    from tech_connector.ui.game_engine.animation_timeline import LayerStack

                    sequence.frames = [LayerStack(sequence.width, sequence.height) for _ in range(frame_count)]
                    sequence.current_frame_index = max(0, min(frame_count - 1, int(getattr(sequence, "current_frame_index", 0) or 0)))
                    if timeline is not None:
                        timeline.update_timeline_ui()
                except Exception as exc:
                    self.record_nonfatal_diagnostic("Could not resize the animation timeline", exc, surface=True)
            if fps:
                sequence.fps = max(1, int(fps))
                if getattr(timeline, "fps_spin", None) is not None and timeline.fps_spin.value() != sequence.fps:
                    timeline.fps_spin.setValue(sequence.fps)

    def _cacheable_provider_target_ids(self, provider: str) -> list[str]:
        target_native_ids = []
        seen = set()
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if not isinstance(proxy, (dict, SceneProxyInstance)):
                continue
            if str(proxy.get("provider_id") or "").lower() != str(provider).lower():
                continue
            if not bool(proxy.get("visible", True)):
                continue
            native_id = str(proxy.get("native_id") or "")
            if native_id and native_id not in seen:
                seen.add(native_id)
                target_native_ids.append(native_id)
        return target_native_ids[:500]

    def set_timeline_cache_enabled(self, enabled: bool) -> None:
        if bool(enabled):
            self.start_timeline_cache()
        else:
            self.stop_timeline_cache()

    def _maybe_auto_start_timeline_cache(self, snapshots: dict[str, dict[str, Any]]) -> None:
        if not bool(getattr(self, "auto_start_timeline_cache", False)):
            return
        if getattr(self, "_dcc_timeline_cache_thread", None) is not None:
            return
        for provider, snapshot in (snapshots or {}).items():
            if dcc_provider_base_key(provider) != "maya" or not isinstance(snapshot, dict):
                continue
            start = snapshot.get("frame_start") or snapshot.get("start_frame")
            end = snapshot.get("frame_end") or snapshot.get("end_frame")
            try:
                if start is None or end is None or int(round(float(end))) <= int(round(float(start))):
                    continue
            except Exception:
                continue
            QTimer.singleShot(250, lambda provider_key=str(provider): self.start_timeline_cache(provider=provider_key))
            break

    def start_timeline_cache(self, *, provider: str | None = None, frame_start: int | None = None, frame_end: int | None = None) -> bool:
        if getattr(self, "_dcc_timeline_cache_thread", None) is not None:
            return False
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        provider_key = str(provider or (providers[0] if providers else "")).lower()
        if not provider_key:
            self._resolved_shaded_status = "Timeline cache needs an imported DCC scene."
            self.update_viewport_status()
            if getattr(self, "cache_timeline_btn", None) is not None:
                self.cache_timeline_btn.setChecked(False)
            return False
        provider_key = self.resolve_dcc_session_key(provider_key, purpose="cache timeline", interactive=False)
        if dcc_provider_base_key(provider_key) != "maya":
            self._resolved_shaded_status = "Timeline cache currently supports Maya scene sources first."
            self.update_viewport_status()
            if getattr(self, "cache_timeline_btn", None) is not None:
                self.cache_timeline_btn.setChecked(False)
            return False
        if provider_key in (getattr(self, "_dcc_deformation_binding_threads", {}) or {}):
            self._pending_timeline_cache_request = {
                "provider": provider_key,
                "frame_start": frame_start,
                "frame_end": frame_end,
            }
            self._dcc_timeline_cache_status = (
                f"Timeline cache for {provider_key} is waiting for skeletal setup to finish"
            )
            self._resolved_shaded_status = self._dcc_timeline_cache_status
            self.update_viewport_status()
            if getattr(self, "cache_timeline_btn", None) is not None and not self.cache_timeline_btn.isChecked():
                self.cache_timeline_btn.blockSignals(True)
                self.cache_timeline_btn.setChecked(True)
                self.cache_timeline_btn.blockSignals(False)
            return True
        start, end = self._timeline_frame_range()
        if frame_start is not None:
            start = int(frame_start)
        if frame_end is not None:
            end = int(frame_end)
        target_ids = self._cacheable_provider_target_ids(provider_key)
        if not target_ids:
            self._resolved_shaded_status = "Timeline cache found no loaded Maya objects to cache."
            self.update_viewport_status()
            if getattr(self, "cache_timeline_btn", None) is not None:
                self.cache_timeline_btn.setChecked(False)
            return False
        self._dcc_timeline_cache_status = f"Geometry cache starting: {provider_key} frames {start}-{end}"
        self._resolved_shaded_status = self._dcc_timeline_cache_status
        self.update_viewport_status()
        thread = QThread(self)
        worker = DccTimelineCacheWorker(
            provider=provider_key,
            frame_start=start,
            frame_end=end,
            target_native_ids=target_ids,
            priority_frame=int(getattr(self, "_current_dcc_frame", start) or start),
            cached_frames=[
                int(frame)
                for cached_provider, frame, fingerprint in self._dcc_timeline_snapshot_cache.keys()
                if cached_provider == provider_key and fingerprint == self._dcc_timeline_cache_fingerprint(provider_key)
            ],
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.frame_cached.connect(self.on_timeline_cache_frame_cached)
        worker.progress.connect(self.on_timeline_cache_progress)
        worker.finished.connect(self._capture_timeline_cache_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_timeline_cache_thread)
        thread.finished.connect(thread.deleteLater)
        self._dcc_timeline_cache_thread = thread
        self._dcc_timeline_cache_worker = worker
        self._dcc_timeline_cache_provider = provider_key
        self._dcc_timeline_cache_finished_result = None
        thread.start()
        if getattr(self, "cache_timeline_btn", None) is not None and not self.cache_timeline_btn.isChecked():
            self.cache_timeline_btn.setChecked(True)
        return True

    def stop_timeline_cache(self) -> None:
        self._pending_timeline_cache_request = None
        worker = getattr(self, "_dcc_timeline_cache_worker", None)
        if worker is not None:
            worker.cancel()
        self._dcc_timeline_cache_status = "Timeline cache canceling..."
        self._resolved_shaded_status = self._dcc_timeline_cache_status
        self.update_viewport_status()

    def _detach_timeline_cache_for_close(self) -> None:
        thread = getattr(self, "_dcc_timeline_cache_thread", None)
        worker = getattr(self, "_dcc_timeline_cache_worker", None)
        if thread is None:
            self._clear_dcc_timeline_snapshot_cache()
            return
        if worker is not None:
            worker.cancel()
            for signal_name, slot in (
                ("frame_cached", self.on_timeline_cache_frame_cached),
                ("progress", self.on_timeline_cache_progress),
                ("finished", self._capture_timeline_cache_finished),
            ):
                try:
                    getattr(worker, signal_name).disconnect(slot)
                except Exception:
                    pass
        try:
            thread.finished.disconnect(self._finish_timeline_cache_thread)
        except Exception:
            pass
        try:
            thread.requestInterruption()
        except Exception:
            pass
        active_archive = getattr(worker, "_archive", None) if worker is not None else None
        archives = dict(getattr(self, "_dcc_timeline_archives", {}) or {})
        archive_paths = set(archives)
        for snapshot in list(self._dcc_timeline_snapshot_cache.values()):
            self._strip_timeline_archive_buffers(snapshot, archive_paths)
        for snapshot in list((getattr(self, "_dcc_scene_snapshots", {}) or {}).values()):
            self._strip_timeline_archive_buffers(snapshot, archive_paths)
        self._dcc_timeline_archives.clear()
        for archive in archives.values():
            if archive is not active_archive:
                archive.close(delete=True)
        self._dcc_timeline_snapshot_cache.clear()
        self._dcc_timeline_snapshot_cache_order.clear()
        self._dcc_timeline_cache_thread = None
        self._dcc_timeline_cache_worker = None
        self._dcc_timeline_cache_provider = ""
        self._dcc_timeline_cache_finished_result = None
        self._pending_timeline_cache_request = None
        self._pending_deformation_binding_providers.clear()
        thread.setParent(QApplication.instance())

    @Slot(str, int, dict)
    def on_timeline_cache_frame_cached(self, provider: str, frame: int, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict):
            return
        snapshot = self._snapshot_for_viewer_scale_policy(provider, snapshot)
        self._store_timeline_snapshots(int(frame), {provider: snapshot})

    @Slot(str, int, int, int, float)
    def on_timeline_cache_progress(self, provider: str, frame: int, cached: int, total: int, fps: float) -> None:
        self._dcc_timeline_cache_status = f"Caching {provider}: {cached}/{total} frames | frame {frame} | {fps:.1f} fps"
        self._resolved_shaded_status = self._dcc_timeline_cache_status
        self.update_viewport_status()

    @Slot(str, bool, str)
    def _capture_timeline_cache_finished(self, provider: str, ok: bool, message: str) -> None:
        self._dcc_timeline_cache_finished_result = (str(provider), bool(ok), str(message))

    @Slot()
    def _finish_timeline_cache_thread(self) -> None:
        sender = self.sender()
        current_thread = getattr(self, "_dcc_timeline_cache_thread", None)
        if current_thread is None or (sender is not None and sender is not current_thread):
            return
        result = getattr(self, "_dcc_timeline_cache_finished_result", None)
        self._dcc_timeline_cache_thread = None
        self._dcc_timeline_cache_worker = None
        self._dcc_timeline_cache_provider = ""
        self._dcc_timeline_cache_finished_result = None
        pending_bindings = list(getattr(self, "_pending_deformation_binding_providers", set()) or set())
        self._pending_deformation_binding_providers.clear()
        if result is None:
            message = "Timeline cache stopped."
        else:
            _provider, _ok, message = result
        self._dcc_timeline_cache_status = message
        self._resolved_shaded_status = message
        if getattr(self, "cache_timeline_btn", None) is not None:
            self.cache_timeline_btn.blockSignals(True)
            self.cache_timeline_btn.setChecked(False)
            self.cache_timeline_btn.blockSignals(False)
        self.update_viewport_status()
        for provider in pending_bindings:
            QTimer.singleShot(0, lambda key=provider: self._start_maya_deformation_binding(key))

    def _apply_cached_timeline_snapshots(self, snapshots: dict[str, dict[str, Any]], frame: int) -> bool:
        if not snapshots:
            return False
        gpu_changed = bool(self.gpu_surface_active() and self.gpu_viewport.update_fast_snapshots(snapshots))
        if self._apply_fast_transform_snapshot_updates(snapshots, apply_mesh_geometry=not gpu_changed) or gpu_changed:
            self._dcc_scene_snapshots.update({
                provider: self._merged_fast_transform_snapshot(provider, snapshot)
                for provider, snapshot in snapshots.items()
            })
            self._last_scene_refresh_changed = True
            self._resolved_shaded_status = f"Timeline cache: frame {int(frame)}"
            self._refresh_coordinate_scale_status()
            self._refresh_camera_authority_choices()
            self.update_viewport_status()
            if hasattr(self, "canvas") and self.canvas:
                self.canvas.update()
            return True
        previous_proxy_state = self._capture_proxy_refresh_state()
        had_existing_snapshots = bool(getattr(self, "_dcc_scene_snapshots", {}))
        self._dcc_scene_snapshots.update({
            provider: self._merged_fast_transform_snapshot(provider, snapshot)
            for provider, snapshot in snapshots.items()
        })
        self._loaded_scene_providers = list(self._dcc_scene_snapshots.keys())
        preserved_center = getattr(self.mesh, "scene_center", None) if had_existing_snapshots else None
        preserved_scale = getattr(self.mesh, "scene_scale", None) if had_existing_snapshots else None
        self.mesh = self._compose_loaded_scene_model(
            scene_center=preserved_center,
            scene_scale=preserved_scale,
        )
        self.sync_gpu_viewport(full=True)
        self._apply_proxy_refresh_state(previous_proxy_state)
        self._last_scene_refresh_changed = True
        self._resolved_shaded_status = f"Timeline cache: frame {int(frame)}"
        self._refresh_coordinate_scale_status()
        self._sync_timeline_range_from_snapshots()
        self._refresh_camera_authority_choices()
        self.refresh_scene_outliner()
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()
        return True

    def _merged_fast_transform_snapshot(self, provider: str, partial_snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(partial_snapshot, dict):
            return partial_snapshot
        previous = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
        if not isinstance(previous, dict):
            return partial_snapshot
        isolation = partial_snapshot.get("isolation") if isinstance(partial_snapshot.get("isolation"), dict) else {}
        target_ids = {str(native_id) for native_id in (isolation.get("target_native_ids") or []) if native_id}
        if not target_ids:
            return partial_snapshot
        # Static topology, UVs, and materials are immutable cache data. Keep those
        # buffers shared and replace only the small per-frame fields/delta buffer.
        merged = dict(previous)
        merged.update({key: value for key, value in partial_snapshot.items() if key != "objects"})
        partial_by_id = {
            str(obj.get("native_id") or ""): obj
            for obj in partial_snapshot.get("objects") or []
            if isinstance(obj, dict) and str(obj.get("native_id") or "")
        }
        merged_objects = []
        seen = set()
        for obj in previous.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            native_id = str(obj.get("native_id") or "")
            if native_id in partial_by_id:
                delta_object = partial_by_id[native_id]
                merged_object = dict(obj)
                merged_object.update(delta_object)
                static_geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else None
                delta_geometry = delta_object.get("geometry") if isinstance(delta_object.get("geometry"), dict) else None
                if static_geometry is not None and delta_geometry is not None:
                    merged_geometry = dict(static_geometry)
                    merged_geometry.update(delta_geometry)
                    merged_object["geometry"] = merged_geometry
                merged_objects.append(merged_object)
                seen.add(native_id)
            else:
                merged_objects.append(obj)
        for native_id, obj in partial_by_id.items():
            if native_id not in seen:
                merged_objects.append(obj)
        merged["objects"] = merged_objects
        if not partial_snapshot.get("cameras"):
            merged["cameras"] = previous.get("cameras") or []
        if not partial_snapshot.get("active_camera"):
            merged["active_camera"] = previous.get("active_camera", "")
        return merged

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

    def _apply_fast_transform_snapshot_updates(
        self,
        snapshots: dict[str, dict[str, Any]],
        *,
        apply_mesh_geometry: bool = True,
    ) -> bool:
        if not snapshots or not getattr(self.mesh, "scene_proxy_objects", None):
            return False
        center = getattr(self.mesh, "scene_center", None)
        scale = getattr(self.mesh, "scene_scale", None)
        if not isinstance(center, (list, tuple)) or len(center) < 3 or scale is None:
            return False
        apply_started = time.perf_counter()
        proxy_by_key: dict[tuple[str, str], SceneProxyInstance | dict[str, Any]] = {}
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if isinstance(proxy, (dict, SceneProxyInstance)):
                proxy_by_key[(str(proxy.get("provider_id") or ""), str(proxy.get("native_id") or ""))] = proxy

        def normalize_point(x: float, y: float, z: float) -> tuple[float, float, float]:
            return (
                (float(x) - float(center[0])) * float(scale),
                (float(y) - float(center[1])) * float(scale),
                (float(z) - float(center[2])) * float(scale),
            )

        changed = 0
        for provider, snapshot in snapshots.items():
            unit_linear = str(snapshot.get("unit_linear") or "")
            up_axis = str(snapshot.get("up_axis") or "")
            provider_base = dcc_provider_base_key(provider)
            maya_identity_space = (
                provider_base == "maya"
                and not up_axis.lower().startswith("z")
                and unit_linear.lower() in {"", "cm", "centimeter", "centimeters"}
            )
            for obj in snapshot.get("objects") or []:
                if not isinstance(obj, dict):
                    continue
                proxy = proxy_by_key.get((provider, str(obj.get("native_id") or "")))
                if proxy is None:
                    continue
                mesh_data = proxy.get("mesh_data")
                topology_state = str(mesh_data.get("topology_state") if isinstance(mesh_data, dict) else getattr(mesh_data, "topology_state", ""))
                vertex_start = int(mesh_data.get("vertex_start") if isinstance(mesh_data, dict) else getattr(mesh_data, "vertex_start", 0) or 0)
                vertex_count = int(mesh_data.get("vertex_count") if isinstance(mesh_data, dict) else getattr(mesh_data, "vertex_count", 0) or 0)
                source_vertex_count = int(
                    mesh_data.get("source_vertex_count", vertex_count)
                    if isinstance(mesh_data, dict)
                    else getattr(mesh_data, "source_vertex_count", vertex_count)
                    or vertex_count
                )
                source_vertex_indices = list(
                    mesh_data.get("source_vertex_indices", [])
                    if isinstance(mesh_data, dict)
                    else getattr(mesh_data, "source_vertex_indices", [])
                    or []
                )
                geometry = obj.get("geometry") if isinstance(obj.get("geometry"), dict) else {}
                source_vertices = geometry.get("vertices") if isinstance(geometry, dict) else None
                source_vertices_f32 = geometry.get("vertices_f32") if isinstance(geometry, dict) else None
                vertex_float_offset = max(0, int(geometry.get("vertex_float_offset", 0) or 0))
                object_space_points = str(geometry.get("coordinate_space") or "world").lower() == "object"
                world_matrix = obj.get("world_matrix") if object_space_points else None
                has_world_matrix = isinstance(world_matrix, (list, tuple)) and len(world_matrix) >= 16
                has_vertex_list = isinstance(source_vertices, list) and len(source_vertices) == source_vertex_count
                has_packed_vertices = (
                    source_vertices_f32 is not None
                    and len(source_vertices_f32) >= vertex_float_offset + source_vertex_count * 3
                )
                if topology_state == "mesh" and geometry.get("representation") == "mesh" and (has_vertex_list or has_packed_vertices):
                    if apply_mesh_geometry:
                        if vertex_start + vertex_count > len(self.mesh.vertices):
                            continue
                        for offset in range(vertex_count):
                            source_offset = source_vertex_indices[offset] if offset < len(source_vertex_indices) else offset
                            if not 0 <= source_offset < source_vertex_count:
                                continue
                            if has_packed_vertices:
                                packed_offset = vertex_float_offset + source_offset * 3
                                source_x = float(source_vertices_f32[packed_offset])
                                source_y = float(source_vertices_f32[packed_offset + 1])
                                source_z = float(source_vertices_f32[packed_offset + 2])
                            else:
                                point = source_vertices[source_offset]
                                if not isinstance(point, (list, tuple)) or len(point) < 3:
                                    continue
                                source_x, source_y, source_z = float(point[0]), float(point[1]), float(point[2])
                            if object_space_points:
                                if not has_world_matrix:
                                    continue
                                object_x, object_y, object_z = source_x, source_y, source_z
                                source_x = (
                                    object_x * float(world_matrix[0])
                                    + object_y * float(world_matrix[4])
                                    + object_z * float(world_matrix[8])
                                    + float(world_matrix[12])
                                )
                                source_y = (
                                    object_x * float(world_matrix[1])
                                    + object_y * float(world_matrix[5])
                                    + object_z * float(world_matrix[9])
                                    + float(world_matrix[13])
                                )
                                source_z = (
                                    object_x * float(world_matrix[2])
                                    + object_y * float(world_matrix[6])
                                    + object_z * float(world_matrix[10])
                                    + float(world_matrix[14])
                                )
                            if maya_identity_space:
                                px, py, pz = source_x, source_y, source_z
                            else:
                                px, py, pz = provider_world_to_view(
                                    provider_base,
                                    source_x,
                                    source_y,
                                    source_z,
                                    unit_linear,
                                    up_axis,
                                )
                            x = (px - float(center[0])) * float(scale)
                            y = (py - float(center[1])) * float(scale)
                            z = (pz - float(center[2])) * float(scale)
                            vertex = self.mesh.vertices[vertex_start + offset]
                            vertex.x = x
                            vertex.y = y
                            vertex.z = z
                    raw_bbox = obj.get("bbox")
                    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 6:
                        bbox = provider_bbox_to_shared(dcc_provider_base_key(provider), raw_bbox, unit_linear, up_axis)
                        cx, cy, cz = normalize_point((bbox[0] + bbox[3]) * 0.5, (bbox[1] + bbox[4]) * 0.5, (bbox[2] + bbox[5]) * 0.5)
                        proxy["center"] = (cx, cy, cz)
                        proxy["source_bbox"] = tuple(float(v) for v in bbox)
                    proxy["source_transform"] = {
                        "translation": obj.get("translation"),
                        "rotation": obj.get("rotation"),
                        "scale": obj.get("scale"),
                    }
                    proxy["local_transform"] = dict(proxy["source_transform"])
                    changed += 1
                    continue
                raw_bbox = obj.get("bbox")
                translation = obj.get("translation")
                if (
                    topology_state == "bounds"
                    and vertex_count == 8
                    and not (isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 6)
                    and isinstance(translation, (list, tuple))
                    and len(translation) >= 3
                ):
                    previous_transform = proxy.get("source_transform") or {}
                    previous_translation = previous_transform.get("translation") if isinstance(previous_transform, dict) else None
                    if isinstance(previous_translation, (list, tuple)) and len(previous_translation) >= 3:
                        old_shared = provider_world_to_view(
                            dcc_provider_base_key(provider),
                            float(previous_translation[0]),
                            float(previous_translation[1]),
                            float(previous_translation[2]),
                            unit_linear,
                            up_axis,
                        )
                        new_shared = provider_world_to_view(
                            dcc_provider_base_key(provider),
                            float(translation[0]),
                            float(translation[1]),
                            float(translation[2]),
                            unit_linear,
                            up_axis,
                        )
                        delta_shared = _vec_sub(new_shared, old_shared)
                        delta_local = _vec_scale(delta_shared, float(scale))
                        if vertex_start + 8 <= len(self.mesh.vertices):
                            for offset in range(8):
                                vertex = self.mesh.vertices[vertex_start + offset]
                                vertex.x += delta_local[0]
                                vertex.y += delta_local[1]
                                vertex.z += delta_local[2]
                            old_center = proxy.get("center") or (0.0, 0.0, 0.0)
                            proxy["center"] = _vec_add(tuple(old_center), delta_local)
                            old_bbox = proxy.get("source_bbox")
                            if isinstance(old_bbox, (list, tuple)) and len(old_bbox) >= 6:
                                proxy["source_bbox"] = (
                                    float(old_bbox[0]) + delta_shared[0],
                                    float(old_bbox[1]) + delta_shared[1],
                                    float(old_bbox[2]) + delta_shared[2],
                                    float(old_bbox[3]) + delta_shared[0],
                                    float(old_bbox[4]) + delta_shared[1],
                                    float(old_bbox[5]) + delta_shared[2],
                                )
                            updated_transform = dict(previous_transform)
                            updated_transform["translation"] = list(translation)
                            proxy["source_transform"] = updated_transform
                            proxy["local_transform"] = dict(updated_transform)
                            changed += 1
                            continue
                if topology_state != "bounds" or vertex_count != 8:
                    continue
                if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 6:
                    continue
                bbox = provider_bbox_to_shared(dcc_provider_base_key(provider), raw_bbox, unit_linear, up_axis)
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
                if vertex_start + 8 > len(self.mesh.vertices):
                    continue
                for offset, (x, y, z) in enumerate(corners):
                    vertex = self.mesh.vertices[vertex_start + offset]
                    vertex.x = x
                    vertex.y = y
                    vertex.z = z
                cx, cy, cz = normalize_point((bbox[0] + bbox[3]) * 0.5, (bbox[1] + bbox[4]) * 0.5, (bbox[2] + bbox[5]) * 0.5)
                proxy["center"] = (cx, cy, cz)
                proxy["source_bbox"] = tuple(float(v) for v in bbox)
                proxy["source_transform"] = {
                    "translation": obj.get("translation"),
                    "rotation": obj.get("rotation"),
                    "scale": obj.get("scale"),
                }
                proxy["local_transform"] = dict(proxy["source_transform"])
                changed += 1
        self._last_geometry_apply_ms = (time.perf_counter() - apply_started) * 1000.0
        if changed:
            invalidate_raycast = getattr(self, "invalidate_paint_raycast_cache", None)
            if callable(invalidate_raycast):
                invalidate_raycast()
        return changed > 0

    def _snapshot_for_viewer_scale_policy(self, provider: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return snapshot
        snapshot = dict(snapshot)
        provider_base = dcc_provider_base_key(provider)
        raw_unit = str(snapshot.get("unit_linear") or "")
        snapshot.setdefault("source_unit_linear", raw_unit)
        snapshot["unit_scale_policy"] = str(getattr(self, "dcc_unit_scale_policy", "working_units") or "working_units")
        if snapshot["unit_scale_policy"] == "working_units":
            # Viewport composition is axis-accurate but unit-neutral by default.
            # This avoids Blender METRIC scenes exploding by x100 against Maya
            # authoring units while preserving the raw unit for diagnostics.
            snapshot["unit_linear"] = "centimeters"
        snapshot["provider_id"] = str(provider or provider_base)
        snapshot.setdefault("provider_base_id", provider_base)
        snapshot.setdefault("up_axis", self._default_up_axis_for_provider(provider_base))
        return snapshot

    def _default_up_axis_for_provider(self, provider: str) -> str:
        provider_key = dcc_provider_base_key(provider)
        if provider_key in {"blender", "unreal", "3dsmax", "max"}:
            return "z"
        return "y"
