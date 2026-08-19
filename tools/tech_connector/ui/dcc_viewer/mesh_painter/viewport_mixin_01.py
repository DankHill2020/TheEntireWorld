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
from tech_connector.ui.design_system import component_stylesheet, set_ui_role
from tech_connector.ui.icons import configure_button
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


class ThreeDMeshPainterViewportMixin01:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(WHOLE_PICTURE_WINDOW_TITLE)
        self.setStyleSheet(component_stylesheet())
        self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self.viewport_camera = MayaViewportCamera()
        self._paint_raycast_cache_key: tuple[Any, ...] | None = None
        self._paint_raycast_cache: tuple[list[tuple[float, ...]], _ProjectedMeshRaycaster] | None = None
        self._paint_geometry_revision = 0
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
        self.viewport_environment_texture, self.viewport_environment_exposure, self.viewport_lighting_profile = (
            self._load_viewport_render_preferences()
        )
        (
            self.show_object_vector_handles,
            self.show_vertex_normals,
            self.show_face_normals,
            self.debug_vector_length,
            self.debug_normal_length,
            self.debug_normal_stride,
            self.show_simulation_diagnostics,
        ) = self._load_viewport_debug_preferences()
        self.show_resolved_shaded_frames = False
        self.viewport_shading_mode = "Highlight"
        self.viewport_display_source = "compiled"
        self.active_dcc_view_provider = ""
        self.show_dcc_context_wire = True
        self.dcc_unit_scale_policy = "working_units"
        self.viewer_coord_up_axis = "y"
        self.drive_dcc_time_enabled = True
        self.viewport_mode = "Selection"
        self.live_refresh_interval_ms = 2500
        self.timeline_refresh_interval_ms = 42
        self.resolved_shaded_refresh_interval_ms = 650
        self.camera_drive_interval_ms = 33

        self.primary_color = QColor(22, 242, 106)
        self._last_paint_color = QColor(self.primary_color)
        self.preferred_palette: list[str] = self._load_preferred_palette()
        self.palette_buttons: list[QPushButton] = []
        self._desktop_color_sampler: DesktopColorSamplerOverlay | None = None
        self.brush_size = 24
        self.brush_softness = int(round((1.0 - BRUSH_PROFILES["PaintBrush"].hardness) * 100.0))
        self.active_brush_name = "PaintBrush"
        self.custom_brush_profiles: dict[str, MeshBrushProfile] = {}
        self.is_orbiting = False
        self.is_painting = False
        self._last_paint_canvas_update_s = 0.0
        self._paint_canvas_update_pending = False
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
        self._dcc_viewport_capture_metadata: dict[str, tuple[float, dict[str, Any]]] = {}
        self._dcc_preferred_session_keys: dict[str, str] = self._load_dcc_preferred_session_keys()
        self._resolved_shaded_frames: dict[str, QImage] = {}
        self._resolved_shaded_frame_paths: dict[str, str] = {}
        self._resolved_shaded_capture_thread: QThread | None = None
        self._resolved_shaded_capture_worker: DccResolvedFrameWorker | None = None
        self._resolved_shaded_status = "Resolved shaded frame idle"
        self._coordinate_scale_status = ""
        self._current_dcc_frame = 1
        self._compact_scene_panel_auto = False
        self._dcc_timeline_frame_start = 1
        self._dcc_timeline_frame_end = 120
        self._suppress_camera_combo_update = False
        self._last_dcc_camera_payload_keys: dict[str, str] = {}
        self._camera_drive_provider_cache: tuple[float, list[str], list[str]] = (0.0, [], [])
        self._dcc_snapshot_signatures: dict[str, str] = {}
        self._dcc_timeline_snapshot_cache: dict[tuple[str, int, str], dict[str, Any]] = {}
        self._dcc_timeline_snapshot_cache_order: list[tuple[str, int, str]] = []
        self._dcc_timeline_snapshot_cache_limit = 6000
        self._dcc_timeline_archives: dict[str, TimelineFrameArchive] = {}
        self._dcc_fast_refresh_cursor: dict[str, int] = {}
        self._dcc_timeline_cache_thread: QThread | None = None
        self._dcc_timeline_cache_worker: DccTimelineCacheWorker | None = None
        self._dcc_timeline_cache_provider = ""
        self._dcc_timeline_cache_status = ""
        self._dcc_timeline_cache_finished_result: tuple[str, bool, str] | None = None
        self._pending_timeline_cache_request: dict[str, Any] | None = None
        self._pending_deformation_binding_providers: set[str] = set()
        self._dcc_async_scene_refresh_thread: QThread | None = None
        self._dcc_async_scene_refresh_worker: DccSceneSnapshotWorker | None = None
        self._dcc_async_scene_refresh_result: tuple[dict[str, dict[str, Any]], list[str]] | None = None
        self._dcc_async_scene_refresh_pending = False
        self._dcc_async_scene_refresh_started_s = 0.0
        self._dcc_scene_model_thread: QThread | None = None
        self._dcc_scene_model_worker: DccSceneModelCompileWorker | None = None
        self._dcc_scene_model_context: dict[str, Any] | None = None
        self._dcc_scene_restore_thread: QThread | None = None
        self._dcc_scene_restore_worker: DccSceneRestoreWorker | None = None
        self._dcc_scene_restore_report: dict[str, Any] | None = None
        self._last_dcc_scene_restore_report: dict[str, Any] = {}
        self._dcc_scene_restore_policy = self._load_dcc_scene_restore_policy()
        self._dcc_processes_launched_for_restore: dict[int, Any] = {}
        self._pending_restored_live_snapshots: dict[str, dict[str, Any]] = {}
        self._cached_restored_source_keys_by_id: dict[str, str] = {}
        self._dcc_camera_possession_thread: QThread | None = None
        self._dcc_camera_possession_worker: DccCameraPossessionWorker | None = None
        self._dcc_camera_possession_pending = False
        self._dcc_camera_possession_payload_keys: dict[str, str] = {}
        self._dcc_camera_possession_results: dict[str, dict[str, Any]] = {}
        self._dcc_camera_possession_started_s = 0.0
        self._dcc_deformation_bindings: dict[str, dict[str, Any]] = {}
        self._dcc_deformation_binding_fingerprints: dict[str, str] = {}
        self._dcc_deformation_binding_threads: dict[str, QThread] = {}
        self._dcc_deformation_binding_workers: dict[str, DccDeformationBindingWorker] = {}
        self._native_fbx_import_thread: QThread | None = None
        self._native_fbx_import_worker: NativeFbxImportWorker | None = None
        self._usd_composition_thread: QThread | None = None
        self._usd_composition_worker: UsdCompositionWorker | None = None
        self._usd_composition: Any = None
        self._usd_composition_result: Any = None
        self._skin_weight_io_thread: QThread | None = None
        self._skin_weight_io_worker: SkinWeightFileWorker | None = None
        self._skin_weight_io_context: dict[str, Any] = {}
        self._mesh_lod_thread: QThread | None = None
        self._mesh_lod_worker: MeshLodGenerationWorker | None = None
        self._mesh_lod_result: dict[str, Any] = {}
        self._runtime_geometry_thread: QThread | None = None
        self._runtime_geometry_worker: RuntimeGeometryCompileWorker | None = None
        self._runtime_geometry_results: dict[str, dict[str, Any]] = {}
        self._tc_scene_conversion_thread: QThread | None = None
        self._tc_scene_conversion_worker: TCSceneConversionWorker | None = None
        self._native_scene_model: FBXMeshModel | None = None
        self._native_fbx_asset: Any = None
        self._native_fbx_current_pose: dict[str, Any] | None = None
        self._camera_drive_latency_ema_ms = float(self.camera_drive_interval_ms)
        self._last_geometry_apply_ms = 0.0
        self._last_viewport_paint_ms = 0.0
        self._last_frame_total_ms = 0.0
        self._frame_render_request_started_s = 0.0
        self.auto_start_timeline_cache = False
        self._dcc_scene_refresh_busy = False
        self._last_dcc_scene_refresh_at = 0.0
        self._cross_dcc_transform_constraints: list[dict[str, Any]] = []
        self._runtime_world_state: dict[str, Any] = {"entities": [], "physics_joints": []}
        self._physics_joint_editor_dialog: QDialog | None = None
        self._physics_joint_editor_model: Any = None
        self.editable_rig_graph = EditableRigGraph()
        self._federated_scene_path = ""
        self._federated_scene_blobs: dict[str, bytes] = {}
        self._scene_lifecycle = SceneDocumentLifecycle()
        self._startup_recovery_checked = False
        self._tc_native_scene_snapshot: dict[str, Any] | None = None
        self._tc_scene_conversion_report: dict[str, Any] = {}
        self._procedural_graphs: dict[str, Any] = {}
        self._procedural_results: dict[str, Any] = {}
        self._procedural_task_graphs: dict[str, Any] = {}
        self._procedural_task_results: dict[str, Any] = {}
        self._procedural_scene_metadata: dict[str, Any] = {"metadata": {}}
        self._dcc_workflow_receipts: dict[str, dict[str, Any]] = {}
        self._active_procedural_graph_id = ""
        self._active_procedural_task_graph_id = ""
        self._procedural_graph_cooker: Any = None
        self._procedural_task_cooker: Any = None
        self._viewer_undo_stack: list[dict[str, Any]] = []
        self._viewer_redo_stack: list[dict[str, Any]] = []
        self._viewer_undo_limit = 40
        self._nonfatal_diagnostics: list[dict[str, str]] = []
        self.syncsketch_markup_enabled = False
        self.is_syncsketch_markup_drawing = False
        self.syncsketch_markup_store = PerFrameSyncSketchMarkupStore()
        self._active_syncsketch_markup_stroke: SyncSketchMarkupStroke | None = None
        self._syncsketch_markup_erase_active = False
        self.shot_guides_enabled = False
        self.shot_guide_mode = "Off"
        self._active_shot_guide_handle = ""
        self._shot_guide_points_normalized: dict[str, tuple[float, float]] = {}
        self.last_shot_guide_solution: dict[str, Any] = {}
        self.shot_camera_profiles: list[dict[str, Any]] = []
        self.active_shot_take_index = -1
        self.active_animation_take_id = ""
        self.auto_key_enabled = self._load_auto_key_enabled()
        self.selected_mesh_face_indices: set[int] = set()
        self.selected_mesh_vertex_indices: set[int] = set()
        self.selected_mesh_edges: set[tuple[int, int]] = set()
        self._component_marquee_start: QPointF | None = None
        self._component_marquee_current: QPointF | None = None
        self._component_marquee_mode = ""
        self._component_marquee_modifiers = Qt.NoModifier
        self._component_marquee_dragging = False
        self._component_marquee_start: QPointF | None = None
        self._component_marquee_current: QPointF | None = None
        self._component_marquee_mode = ""
        self._component_marquee_modifiers = Qt.NoModifier
        self._component_marquee_dragging = False
        self.simulation_world = None
        from tech_connector.game_engine.authoring.character_intelligence_service import CharacterWorldAsset
        from tech_connector.game_engine.integration.world_intelligence_command_service import WorldIntelligenceRuntimeState

        self.character_world = CharacterWorldAsset()
        self.world_intelligence_runtime = WorldIntelligenceRuntimeState()
        self.game_experience_profile = None
        self.simulation_initial_world = None
        self.simulation_cache = None
        self.simulation_frame = 1
        self.simulation_playing = False
        self.simulation_frame_rate = 30.0
        self._effect_renderer_budget = {
            "target_upload_ms": 4.0,
            "particle_budget_per_stream": 20000,
            "mesh_instance_budget": 50000,
            "cull_distance": 250.0,
            "adaptive": True,
        }
        self._effect_bake_thread: QThread | None = None
        self._effect_bake_worker: EffectBakeWorker | None = None
        self._effect_bake_progress: tuple[int, int, int, float] = (0, 0, 0, 0.0)

        self._build_ui()
        self._apply_accessibility_metadata()
        from tech_connector.game_engine.integration.active_viewer_command_service import register_active_viewer
        register_active_viewer(self)
        self.simulation_timer = QTimer(self)
        self.simulation_timer.setInterval(int(round(1000.0 / self.simulation_frame_rate)))
        self.simulation_timer.timeout.connect(self.step_active_simulation)
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
        self.scene_autosave_timer = QTimer(self)
        self.scene_autosave_timer.setInterval(120_000)
        self.scene_autosave_timer.timeout.connect(self.autosave_federated_scene)
        self.scene_autosave_timer.start()
        from tech_connector.game_engine.integration.active_viewer_command_service import (
            register_active_viewer,
        )

        register_active_viewer(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if str(getattr(self, "viewport_display_source", "") or "").lower() == "dcc":
            QTimer.singleShot(0, lambda: self.start_dcc_viewport_stream(self.active_dcc_view_provider))
        if bool(getattr(self, "live_dcc_refresh_btn", None) and self.live_dcc_refresh_btn.isChecked()):
            self.live_refresh_timer.setInterval(int(getattr(self, "timeline_refresh_interval_ms", 42) or 42))
            self.live_refresh_timer.start()
        if getattr(self, "drive_dcc_camera_enabled", False):
            QTimer.singleShot(0, lambda: self.schedule_dcc_camera_drive("viewer shown"))
        QTimer.singleShot(0, self._start_maya_deformation_bindings_for_loaded_scenes)
        if not self._startup_recovery_checked and os.environ.get("QT_QPA_PLATFORM", "").casefold() != "offscreen":
            self._startup_recovery_checked = True
            QTimer.singleShot(0, self._offer_startup_scene_recovery)

    def hideEvent(self, event) -> None:
        self._suspend_async_dcc_camera_drive()
        self._suspend_async_dcc_scene_refresh()
        self._detach_deformation_binding_workers()
        self._detach_native_fbx_import_worker()
        self._detach_usd_composition_worker()
        self._detach_skin_weight_io_worker()
        self._detach_mesh_lod_worker()
        self._detach_runtime_geometry_worker()
        self.stop_dcc_viewport_stream()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        noninteractive = os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen"
        if self._scene_lifecycle.dirty and noninteractive and not getattr(self, "_force_close_prompt_for_testing", False):
            self.autosave_federated_scene()
        elif self._scene_lifecycle.dirty:
            answer = QMessageBox.question(
                self,
                "Unsaved Scene Changes",
                "Save changes to the Tech Connector scene before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Save:
                saved = (
                    self._save_federated_scene_to_path(self._federated_scene_path)
                    if self._federated_scene_path
                    else self.save_federated_scene_dialog()
                )
                if not saved:
                    event.ignore()
                    return
        from tech_connector.game_engine.integration.active_viewer_command_service import unregister_active_viewer
        unregister_active_viewer(self)
        self._suspend_async_dcc_camera_drive()
        self.cancel_effect_bake()
        bake_thread = self._effect_bake_thread
        if bake_thread is not None and bake_thread.isRunning():
            bake_thread.quit()
            bake_thread.wait(2000)
        self._detach_timeline_cache_for_close()
        self._detach_scene_model_compile()
        self._detach_dcc_scene_restore()
        self._detach_deformation_binding_workers()
        self._detach_native_fbx_import_worker()
        self._detach_usd_composition_worker()
        self._detach_skin_weight_io_worker()
        self._detach_mesh_lod_worker()
        self._detach_runtime_geometry_worker()
        self._detach_tc_scene_conversion_worker()
        super().closeEvent(event)

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

    def active_shot_guide_names(self) -> list[str]:
        mode = str(getattr(self, "shot_guide_mode", "Off") or "Off")
        if mode.startswith("1-Point"):
            return ["VP1"]
        if mode.startswith("2-Point"):
            return ["VP1", "VP2"]
        if mode.startswith("3-Point"):
            return ["VP1", "VP2", "VP3"]
        if mode.startswith("4-Point"):
            return ["VP1", "VP2", "VP3", "VP4", "VP5"]
        if mode.startswith("5-Point"):
            return ["VP1", "VP2", "VP3", "VP4", "VP5"]
        if mode.startswith("6-Point"):
            return ["VP1", "VP2", "VP3", "VP4", "VP5", "VP6"]
        return []

    def default_shot_guide_points_normalized(self, mode: str) -> dict[str, tuple[float, float]]:
        if str(mode or "").startswith(("4-Point", "5-Point", "6-Point")):
            return {
                "VP1": (0.08, 0.5),
                "VP2": (0.92, 0.5),
                "VP3": (0.5, 0.08),
                "VP4": (0.5, 0.92),
                "VP5": (0.5, 0.5),
                "VP6": (0.5, 0.55),
            }
        if str(mode or "").startswith("1-Point"):
            return {"VP1": (0.5, 0.42), "VP5": (0.5, 0.5)}
        return {
            "VP1": (-0.3, 0.42),
            "VP2": (1.3, 0.42),
            "VP3": (0.5, -0.55),
            "VP5": (0.5, 0.5),
        }

    def shot_guide_points_for_view(self, width: float, height: float) -> dict[str, QPointF]:
        points = dict(getattr(self, "_shot_guide_points_normalized", {}) or {})
        if not points:
            points = self.default_shot_guide_points_normalized(str(getattr(self, "shot_guide_mode", "Off") or "Off"))
            self._shot_guide_points_normalized = dict(points)
        w = max(1.0, float(width or 1.0))
        h = max(1.0, float(height or 1.0))
        return {name: QPointF(float(value[0]) * w, float(value[1]) * h) for name, value in points.items()}

    def set_shot_guide_mode(self, mode: str) -> None:
        self.shot_guide_mode = str(mode or "Off")
        self.shot_guides_enabled = self.shot_guide_mode != "Off"
        self._shot_guide_points_normalized = self.default_shot_guide_points_normalized(self.shot_guide_mode)
        self.last_shot_guide_solution = {}
        self.mark_scene_dirty()
        if getattr(self, "shot_guides_btn", None) is not None:
            self.shot_guides_btn.setText("Shot Guides" if not self.shot_guides_enabled else self.shot_guide_mode.split(" Perspective")[0])
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def toggle_shot_guides(self) -> None:
        if self.shot_guides_enabled:
            self.set_shot_guide_mode("Off")
        else:
            self.set_shot_guide_mode("2-Point Perspective")

    def reset_shot_guides(self) -> None:
        self._shot_guide_points_normalized = self.default_shot_guide_points_normalized(self.shot_guide_mode)
        self.last_shot_guide_solution = {}
        self.mark_scene_dirty()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def hit_test_shot_guide_handle(self, position: QPointF, width: float, height: float) -> str:
        points = self.shot_guide_points_for_view(width, height)
        active = self.active_shot_guide_names()
        best_name = ""
        best_dist = 13.0
        for name in active:
            point = points.get(name)
            if point is None:
                continue
            dist = math.hypot(float(position.x()) - point.x(), float(position.y()) - point.y())
            if dist <= best_dist:
                best_name = name
                best_dist = dist
        return best_name

    def move_shot_guide_handle(self, name: str, position: QPointF, width: float, height: float) -> None:
        if name not in self.active_shot_guide_names():
            return
        w = max(1.0, float(width or 1.0))
        h = max(1.0, float(height or 1.0))
        points = dict(getattr(self, "_shot_guide_points_normalized", {}) or {})
        points[name] = (float(position.x()) / w, float(position.y()) / h)
        self._shot_guide_points_normalized = points
        self.mark_scene_dirty()
        self.solve_shot_guides(apply_camera=False)

    def solve_shot_guides(self, *, apply_camera: bool = False) -> dict[str, Any]:
        if not getattr(self, "shot_guides_enabled", False):
            return {}
        width = float(getattr(getattr(self, "canvas", None), "width", lambda: 1280)())
        height = float(getattr(getattr(self, "canvas", None), "height", lambda: 720)())
        qpoints = self.shot_guide_points_for_view(width, height)
        points = {name: (point.x(), point.y()) for name, point in qpoints.items()}
        result = solve_perspective_guides(self.shot_guide_mode, points, width, height).to_dict()
        self.last_shot_guide_solution = result
        if apply_camera:
            self.apply_shot_guides_to_camera(result)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        return result

    def apply_shot_guides_to_camera(self, result: dict[str, Any] | None = None) -> None:
        result = result or self.solve_shot_guides(apply_camera=False)
        if not result:
            return
        camera_settings = result.get("camera_settings") or {}
        fov = float(camera_settings.get("fov_degrees", self.viewport_camera.fov_degrees) or self.viewport_camera.fov_degrees)
        self.push_viewer_undo_state("Apply shot guides to camera")
        self.viewport_camera.fov_degrees = max(5.0, min(175.0, fov))
        rotation = camera_settings.get("rotation_degrees") or {}
        projection_model = str(result.get("projection_model") or "rectilinear")
        if projection_model == "rectilinear":
            if abs(float(rotation.get("yaw", 0.0) or 0.0)) > 0.001:
                self.camera_rot_y = float(rotation.get("yaw", 0.0) or 0.0)
            if abs(float(rotation.get("pitch", 0.0) or 0.0)) > 0.001:
                self.camera_rot_x = float(rotation.get("pitch", 0.0) or 0.0)
            roll = math.radians(float(rotation.get("roll", 0.0) or 0.0))
            if abs(roll) > 1.0e-4:
                forward = self.viewport_camera.view_axes()[0]
                self.viewport_camera.up = _vec_normalize(
                    _rotate_vec_around_axis(self.viewport_camera.up, forward, roll),
                    self.viewport_camera.up,
                )
        self.last_shot_guide_solution = result
        self.update_viewport_status()
        if getattr(self, "viewport_status_label", None) is not None:
            focal = float(camera_settings.get("focal_length_mm", 0.0) or 0.0)
            self.viewport_status_label.setText(
                f"Shot guides applied: {projection_model}, FOV {self.viewport_camera.fov_degrees:.1f}, {focal:.1f}mm equivalent."
            )
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        self.schedule_dcc_camera_drive("shot guides applied")
        self.schedule_resolved_shaded_refresh("shot guides applied")

    def _format_timecode(self, frame: int, fps: float | int | None = None, *, start_frame: int | None = None) -> str:
        rate = max(1, int(round(float(fps or self.current_shot_fps()))))
        origin = int(start_frame if start_frame is not None else getattr(self, "_dcc_timeline_frame_start", 1) or 1)
        local_frame = max(0, int(frame) - origin)
        seconds, ff = divmod(local_frame, rate)
        minutes, ss = divmod(seconds, 60)
        hh, mm = divmod(minutes, 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"

    def current_shot_fps(self) -> float:
        timeline = getattr(self, "anim_timeline", None)
        sequence = getattr(timeline, "sequence", None)
        if sequence is not None:
            try:
                return max(1.0, float(sequence.fps))
            except (TypeError, ValueError):
                LOGGER.debug("Timeline FPS was invalid; using 24 FPS.", exc_info=True)
        return 24.0

    def _camera_profile_from_viewer(self) -> dict[str, Any]:
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        return {
            "eye": [float(value) for value in getattr(camera, "eye", (0.0, 0.0, -4.0))],
            "target": [float(value) for value in getattr(camera, "target", (0.0, 0.0, 0.0))],
            "up": [float(value) for value in getattr(camera, "up", (0.0, 1.0, 0.0))],
            "fov_degrees": float(getattr(camera, "fov_degrees", 45.0) or 45.0),
            "near_clip": float(getattr(camera, "near_clip", 0.1) or 0.1),
            "far_clip": float(getattr(camera, "far_clip", 100000.0) or 100000.0),
            "coord_space": str(getattr(self, "viewer_coord_space", "maya") or "maya"),
            "projection": copy.deepcopy(getattr(self, "last_shot_guide_solution", {}) or {}),
        }

    def _selected_context_for_shot(self) -> dict[str, Any]:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return {}
        return {
            "provider": str(proxy.get("provider_id") or ""),
            "native_id": str(proxy.get("native_id") or ""),
            "name": str(proxy.get("name") or proxy.get("native_id") or ""),
            "type": str(proxy.get("type") or proxy.get("object_type") or ""),
            "source_key": str(proxy.get("source_key") or ""),
        }

    def _capture_shot_take_profile(self, name: str | None = None) -> ShotTakeProfile:
        frame_start = int(getattr(self, "_dcc_timeline_frame_start", 1) or 1)
        frame_end = int(getattr(self, "_dcc_timeline_frame_end", frame_start) or frame_start)
        current_frame = int(getattr(self, "_current_dcc_frame", frame_start) or frame_start)
        fps = self.current_shot_fps()
        if not name:
            name = f"Shot_{len(getattr(self, 'shot_camera_profiles', []) or []) + 1:03d}"
        guide_solution = dict(getattr(self, "last_shot_guide_solution", {}) or {})
        if getattr(self, "shot_guides_enabled", False) and not guide_solution:
            guide_solution = self.solve_shot_guides(apply_camera=False)
        retarget_status = {
            "status": "not_configured",
            "route": "",
            "target_skeleton": "",
            "target_mesh": "",
            "validation": "pending",
        }
        return ShotTakeProfile(
            name=str(name),
            frame_start=frame_start,
            frame_end=frame_end,
            current_frame=current_frame,
            fps=fps,
            timecode_start=self._format_timecode(frame_start, fps, start_frame=frame_start),
            camera=self._camera_profile_from_viewer(),
            shot_guides={
                "enabled": bool(getattr(self, "shot_guides_enabled", False)),
                "mode": str(getattr(self, "shot_guide_mode", "Off") or "Off"),
                "points_normalized": copy.deepcopy(getattr(self, "_shot_guide_points_normalized", {}) or {}),
                "solution": guide_solution,
            },
            selected_context=self._selected_context_for_shot(),
            retarget=retarget_status,
        )

    def capture_current_shot_take_profile(self) -> None:
        default_name = f"Shot_{len(getattr(self, 'shot_camera_profiles', []) or []) + 1:03d}"
        name, ok = QInputDialog.getText(self, "Capture Shot / Take", "Shot name:", text=default_name)
        if not ok:
            return
        profile = self._capture_shot_take_profile(str(name or default_name).strip() or default_name)
        self.shot_camera_profiles.append(profile.to_dict())
        self.active_shot_take_index = len(self.shot_camera_profiles) - 1
        self.refresh_shot_take_combo()
        self._resolved_shaded_status = f"Captured {profile.name}: frames {profile.frame_start}-{profile.frame_end} @ {profile.fps:g}fps"
        self.update_viewport_status()

    def refresh_shot_take_combo(self) -> None:
        combo = getattr(self, "shot_take_combo", None)
        if combo is None:
            return
        current = int(getattr(self, "active_shot_take_index", -1))
        combo.blockSignals(True)
        combo.clear()
        profiles = list(getattr(self, "shot_camera_profiles", []) or [])
        if not profiles:
            combo.addItem("No shots", -1)
        else:
            for index, profile in enumerate(profiles):
                name = str(profile.get("name") or f"Shot {index + 1}")
                start = int(profile.get("frame_start", 1) or 1)
                end = int(profile.get("frame_end", start) or start)
                fps = float(profile.get("fps", 24.0) or 24.0)
                combo.addItem(f"{name}  {start}-{end}  {fps:g}fps", index)
        combo.setCurrentIndex(max(0, min(current, combo.count() - 1)))
        combo.blockSignals(False)

    def on_shot_take_combo_changed(self, _index: int) -> None:
        combo = getattr(self, "shot_take_combo", None)
        if combo is None:
            return
        self.active_shot_take_index = int(combo.currentData() if combo.currentData() is not None else -1)

    def active_shot_take_profile(self) -> dict[str, Any] | None:
        profiles = list(getattr(self, "shot_camera_profiles", []) or [])
        index = int(getattr(self, "active_shot_take_index", -1))
        if 0 <= index < len(profiles):
            return profiles[index]
        return None

    def apply_active_shot_take_profile(self) -> None:
        profile = self.active_shot_take_profile()
        if not profile:
            self._resolved_shaded_status = "No shot/take profile is selected."
            self.update_viewport_status()
            return
        self.push_viewer_undo_state("Apply shot/take profile")
        camera = dict(profile.get("camera") or {})
        try:
            self.viewport_camera = MayaViewportCamera(
                eye=tuple(float(value) for value in camera.get("eye", self.viewport_camera.eye)),
                target=tuple(float(value) for value in camera.get("target", self.viewport_camera.target)),
                up=tuple(float(value) for value in camera.get("up", self.viewport_camera.up)),
                fov_degrees=float(camera.get("fov_degrees", self.viewport_camera.fov_degrees)),
                near_clip=float(camera.get("near_clip", self.viewport_camera.near_clip)),
                far_clip=float(camera.get("far_clip", self.viewport_camera.far_clip)),
            )
        except Exception:
            LOGGER.warning("Could not apply the saved shot camera profile.", exc_info=True)
        self._dcc_timeline_frame_start = int(profile.get("frame_start", self._dcc_timeline_frame_start) or self._dcc_timeline_frame_start)
        self._dcc_timeline_frame_end = int(profile.get("frame_end", self._dcc_timeline_frame_end) or self._dcc_timeline_frame_end)
        self._current_dcc_frame = int(profile.get("current_frame", self._current_dcc_frame) or self._current_dcc_frame)
        guides = dict(profile.get("shot_guides") or {})
        self.shot_guides_enabled = bool(guides.get("enabled", False))
        self.shot_guide_mode = str(guides.get("mode") or "Off")
        self._shot_guide_points_normalized = dict(guides.get("points_normalized") or {})
        self.last_shot_guide_solution = dict(guides.get("solution") or {})
        self._resolved_shaded_status = f"Applied shot/take: {profile.get('name')}"
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        self.schedule_dcc_camera_drive("shot/take applied")
        self.schedule_resolved_shaded_refresh("shot/take applied")

    def show_active_shot_retarget_status(self) -> None:
        profile = self.active_shot_take_profile()
        if not profile:
            QMessageBox.information(self, "Retarget Status", "No shot/take profile is selected.")
            return
        retarget = dict(profile.get("retarget") or {})
        selected = dict(profile.get("selected_context") or {})
        lines = [
            f"Shot: {profile.get('name')}",
            f"Frames: {profile.get('frame_start')} - {profile.get('frame_end')} @ {profile.get('fps')} fps",
            f"Timecode Start: {profile.get('timecode_start')}",
            "",
            f"Selected Source: {selected.get('provider', 'none')}:{selected.get('name') or selected.get('native_id') or 'none'}",
            f"Retarget Status: {retarget.get('status', 'not_configured')}",
            f"Route: {retarget.get('route', '') or 'unresolved'}",
            f"Target Skeleton: {retarget.get('target_skeleton', '') or 'unresolved'}",
            f"Validation: {retarget.get('validation', 'pending')}",
        ]
        QMessageBox.information(self, "Shot Retarget Status", "\n".join(lines))

    def send_active_shot_to_unreal_sequence(self) -> None:
        profile = self.active_shot_take_profile()
        if not profile:
            profile = self._capture_shot_take_profile("Shot_001").to_dict()
        default_path = str((profile.get("unreal") or {}).get("sequence_path") or f"/Game/AIStudio/Shots/{profile.get('name') or 'Shot_001'}")
        sequence_path, ok = QInputDialog.getText(self, "Send Shot To Unreal", "Level Sequence asset path:", text=default_path)
        if not ok or not str(sequence_path or "").strip():
            return
        result = self._send_shot_profile_to_unreal_sequence(profile, str(sequence_path).strip())
        if result.get("ok"):
            profile.setdefault("unreal", {})["sequence_path"] = result.get("sequence_path") or sequence_path
            self._resolved_shaded_status = f"Sent shot to Unreal: {result.get('sequence_path') or sequence_path}"
            QMessageBox.information(self, "Unreal Shot Export", self._resolved_shaded_status)
        else:
            self._resolved_shaded_status = f"Unreal shot export failed: {result.get('error') or result.get('message')}"
            QMessageBox.warning(self, "Unreal Shot Export Failed", self._resolved_shaded_status)
        self.update_viewport_status()

    def _send_shot_profile_to_unreal_sequence(self, profile: dict[str, Any], sequence_path: str) -> dict[str, Any]:
        try:
            bridge = self._scene_snapshot_bridge("unreal")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        payload = json.dumps({"profile": profile, "sequence_path": sequence_path})
        code = self._unreal_create_or_update_sequence_code(payload)
        response = bridge.execute_python(code, timeout=30.0, reset_globals=True)
        if not response.get("ok"):
            return {"ok": False, "error": response.get("error") or response.get("stdout") or str(response)}
        raw = response.get("data") or response.get("stdout") or response.get("output") or response.get("result") or "{}"
        try:
            if isinstance(raw, str):
                return dict(json.loads(raw.strip().splitlines()[-1]))
            return dict(raw or {})
        except Exception:
            return {"ok": True, "message": str(raw), "sequence_path": sequence_path}

    def _unreal_create_or_update_sequence_code(self, payload_json: str) -> str:
        return f"""
    import json
    import math
    import unreal

    payload = json.loads({payload_json!r})
    profile = payload.get("profile") or {{}}
    sequence_path = str(payload.get("sequence_path") or "/Game/AIStudio/Shots/Shot_001")
    folder, name = sequence_path.rsplit("/", 1) if "/" in sequence_path else ("/Game/AIStudio/Shots", sequence_path)
    if not folder.startswith("/Game"):
    folder = "/Game/AIStudio/Shots"
    unreal.EditorAssetLibrary.make_directory(folder)
    sequence = unreal.EditorAssetLibrary.load_asset(folder + "/" + name)
    created = False
    if sequence is None:
    factory = unreal.LevelSequenceFactoryNew()
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.LevelSequence, factory)
    created = True
    if sequence is None:
    raise RuntimeError("Could not create or load Level Sequence: " + folder + "/" + name)

    fps = max(1, int(round(float(profile.get("fps") or 24))))
    start = int(profile.get("frame_start") or 1)
    end = max(start, int(profile.get("frame_end") or start))
    if hasattr(sequence, "set_display_rate"):
    sequence.set_display_rate(unreal.FrameRate(fps, 1))
    if hasattr(sequence, "set_playback_start"):
    sequence.set_playback_start(start)
    if hasattr(sequence, "set_playback_end"):
    sequence.set_playback_end(end)

    camera_data = profile.get("camera") or {{}}
    eye = camera_data.get("eye") or [0.0, 0.0, -400.0]
    target = camera_data.get("target") or [0.0, 0.0, 0.0]
    dx, dy, dz = float(target[0]) - float(eye[0]), float(target[1]) - float(eye[1]), float(target[2]) - float(eye[2])
    yaw = math.degrees(math.atan2(dy, dx))
    dist_xy = max(1.0e-6, math.sqrt(dx * dx + dy * dy))
    pitch = math.degrees(math.atan2(dz, dist_xy))
    location = unreal.Vector(float(eye[0]), float(eye[1]), float(eye[2]))
    rotation = unreal.Rotator(float(pitch), float(yaw), 0.0)
    actor_label = "TC_" + str(profile.get("name") or name) + "_Camera"
    world = unreal.EditorLevelLibrary.get_editor_world()
    camera_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, location, rotation)
    camera_actor.set_actor_label(actor_label)
    camera_component = camera_actor.get_cine_camera_component()
    if camera_component:
    camera_component.set_editor_property("field_of_view", float(camera_data.get("fov_degrees") or 45.0))
    try:
    binding = sequence.add_possessable(camera_actor)
    camera_cut_track = sequence.add_master_track(unreal.MovieSceneCameraCutTrack)
    section = camera_cut_track.add_section()
    section.set_range(start, end)
    section.set_camera_binding_id(binding.get_id())
    except Exception:
    binding = None
    unreal.EditorAssetLibrary.save_asset(folder + "/" + name, only_if_is_dirty=False)
    print(json.dumps({{"ok": True, "created": created, "sequence_path": folder + "/" + name, "camera_actor": actor_label, "frame_start": start, "frame_end": end, "fps": fps}}))
    """

    def show_fx_properties(self) -> None:
        from tech_connector.ui.game_engine.fx_properties import FxPropertiesDialog

        dialog = getattr(self, "_fx_properties_dialog", None)
        if dialog is None:
            dialog = FxPropertiesDialog(parent=self)
            dialog.create_requested.connect(self._create_fx_from_properties)
            dialog.parameter_changed.connect(self._set_fx_property_from_dialog)
            dialog.renderer_changed.connect(self._set_fx_renderer_from_dialog)
            dialog.solo_emitter_requested.connect(self._solo_fx_emitter_from_dialog)
            dialog.emitter_manipulation_requested.connect(self._set_fx_emitter_manipulation_from_dialog)
            dialog.renderer_budget_changed.connect(self._configure_fx_renderer_budget_from_dialog)
            dialog.renderer_stats_requested.connect(self._refresh_fx_renderer_stats_for_dialog)
            dialog.preview_toggled.connect(self.set_simulation_playing)
            dialog.bake_requested.connect(self._bake_active_fx_from_properties)
            dialog.reset_requested.connect(self.reset_active_simulation)
            self._fx_properties_dialog = dialog
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        dialog.set_effect_system(system)
        dialog.set_performance_budget(dict(getattr(self, "_effect_renderer_budget", {}) or {}))
        dialog.set_previewing(bool(getattr(self, "simulation_playing", False)))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _create_fx_from_properties(self, preset: str, quality: str, seed: int) -> None:
        self.create_simulation_preset_from_payload(
            "simulation.create_effect",
            {"preset": str(preset), "quality": str(quality), "seed": int(seed)},
        )
        self.set_simulation_playing(True)
        dialog = getattr(self, "_fx_properties_dialog", None)
        if dialog is not None:
            dialog.set_effect_system(self.simulation_world.effect_system)
            dialog.set_previewing(True)

    def _set_fx_property_from_dialog(self, path: str, value: Any) -> None:
        self.create_simulation_preset_from_payload(
            "simulation.set_effect_parameter",
            {"path": str(path), "value": value},
        )
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def _set_fx_renderer_from_dialog(self, emitter_id: str, renderer_type: str) -> None:
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        if system is None:
            return
        emitter = next((item for item in system.emitters if item.emitter_id == str(emitter_id)), None)
        if emitter is None:
            return
        renderer = dict(emitter.renderer or {})
        renderer["type"] = str(renderer_type)
        self._set_fx_property_from_dialog(f"emitter.{emitter.emitter_id}.renderer", renderer)

    def _solo_fx_emitter_from_dialog(self, emitter_id: str, soloed: bool) -> None:
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        if system is None:
            return
        from tech_connector.game_engine.runtime.tc_effect_system_service import set_effect_parameter

        if soloed:
            self._fx_solo_restore = {emitter.emitter_id: bool(emitter.enabled) for emitter in system.emitters}
            for emitter in system.emitters:
                set_effect_parameter(system, f"emitter.{emitter.emitter_id}.enabled", emitter.emitter_id == str(emitter_id))
            self._resolved_shaded_status = f"Soloing FX emitter {emitter_id}."
        else:
            restore = dict(getattr(self, "_fx_solo_restore", {}) or {})
            for emitter in system.emitters:
                set_effect_parameter(system, f"emitter.{emitter.emitter_id}.enabled", restore.get(emitter.emitter_id, True))
            self._fx_solo_restore = {}
            self._resolved_shaded_status = "Restored all FX emitters."
        self.simulation_initial_world = copy.deepcopy(self.simulation_world)
        self.update_viewport_status()

    def _set_fx_emitter_manipulation_from_dialog(
        self, emitter_id: str, active: bool, move_live_particles: bool
    ) -> None:
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        if system is None:
            return
        from tech_connector.game_engine.runtime.tc_effect_system_service import set_effect_emitter_interactive

        previous = str(getattr(self, "_fx_manipulator_emitter_id", "") or "")
        if previous and (not active or previous != str(emitter_id)):
            try:
                set_effect_emitter_interactive(system, previous, False)
            except KeyError:
                pass
        if active:
            set_effect_emitter_interactive(system, str(emitter_id), True)
            self._fx_manipulator_emitter_id = str(emitter_id)
            self._fx_manipulator_move_particles = bool(move_live_particles)
            self.set_simulation_playing(True)
            self._resolved_shaded_status = (
                f"Emitter {emitter_id} active · drag the cyan viewport handle to sculpt the effect live."
            )
        else:
            self._fx_manipulator_emitter_id = ""
            self._fx_emitter_drag = None
            self._resolved_shaded_status = "FX emitter manipulation stopped."
        initial_system = getattr(getattr(self, "simulation_initial_world", None), "effect_system", None)
        if initial_system is not None:
            try:
                set_effect_emitter_interactive(initial_system, str(emitter_id), bool(active))
            except KeyError:
                pass
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def active_fx_emitter(self) -> Any:
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        emitter_id = str(getattr(self, "_fx_manipulator_emitter_id", "") or "")
        if system is None or not emitter_id:
            return None
        return next((item for item in system.emitters if item.emitter_id == emitter_id), None)

    def fx_emitter_screen_handle(self) -> dict[str, Any] | None:
        emitter = self.active_fx_emitter()
        if emitter is None or getattr(self, "canvas", None) is None:
            return None
        from tech_connector.game_engine.runtime.tc_effect_system_service import effect_emitter_anchor

        anchor_shared = effect_emitter_anchor(emitter)
        anchor_display = self.shared_local_to_display_local(anchor_shared)
        rect = self.canvas.dcc_viewport_projection_rect()
        sx, sy, depth = self.viewport_camera.project_world_to_screen(
            anchor_display, max(1.0, rect.width()), max(1.0, rect.height())
        )
        return {
            "emitter_id": emitter.emitter_id,
            "anchor_shared": anchor_shared,
            "anchor_display": anchor_display,
            "screen": QPointF(float(sx + rect.x()), float(sy + rect.y())),
            "depth": float(depth),
        }

    def begin_fx_emitter_drag(self, position: QPointF, *, max_distance_px: float = 28.0) -> bool:
        handle = self.fx_emitter_screen_handle()
        if handle is None:
            return False
        screen = handle["screen"]
        if math.hypot(float(position.x() - screen.x()), float(position.y() - screen.y())) > max_distance_px:
            return False
        self._fx_emitter_drag = {
            **handle,
            "start_screen": QPointF(position),
            "last_position": handle["anchor_shared"],
        }
        self._resolved_shaded_status = f"Dragging FX emitter {handle['emitter_id']} live."
        return True

    def update_fx_emitter_drag(self, position: QPointF) -> tuple[float, float, float] | None:
        drag = getattr(self, "_fx_emitter_drag", None)
        system = getattr(getattr(self, "simulation_world", None), "effect_system", None)
        if not drag or system is None or getattr(self, "canvas", None) is None:
            return None
        rect = self.canvas.dcc_viewport_projection_rect()
        width, height = max(1.0, rect.width()), max(1.0, rect.height())
        delta = position - drag["start_screen"]
        _forward, right, up = self.viewport_camera.view_axes()
        world_per_px_y = (
            2.0 * max(0.1, float(drag["depth"]))
            * math.tan(math.radians(self.viewport_camera.fov_degrees * 0.5)) / height
        )
        world_per_px_x = world_per_px_y * width / height
        display_delta = _vec_add(
            _vec_scale(right, float(delta.x()) * world_per_px_x),
            _vec_scale(up, -float(delta.y()) * world_per_px_y),
        )
        target_display = _vec_add(drag["anchor_display"], display_delta)
        target_shared = self.display_local_to_shared_local(target_display)
        from tech_connector.game_engine.runtime.tc_effect_system_service import move_effect_emitter

        moved = move_effect_emitter(
            system, drag["emitter_id"], target_shared, world=self.simulation_world,
            move_live_particles=bool(getattr(self, "_fx_manipulator_move_particles", False)),
        )
        drag["last_position"] = moved
        self._resolved_shaded_status = (
            f"Emitter {drag['emitter_id']} · {moved[0]:.2f}, {moved[1]:.2f}, {moved[2]:.2f}"
        )
        self.update_viewport_status()
        return moved

    def end_fx_emitter_drag(self) -> tuple[float, float, float] | None:
        drag = getattr(self, "_fx_emitter_drag", None)
        if not drag:
            return None
        moved = tuple(float(value) for value in drag["last_position"])
        initial_system = getattr(getattr(self, "simulation_initial_world", None), "effect_system", None)
        if initial_system is not None:
            from tech_connector.game_engine.runtime.tc_effect_system_service import move_effect_emitter
            try:
                move_effect_emitter(initial_system, drag["emitter_id"], moved)
            except KeyError:
                pass
        self._fx_emitter_drag = None
        self._resolved_shaded_status = f"Emitter {drag['emitter_id']} moved · live preview remains active."
        self.update_viewport_status()
        return moved

    def _configure_fx_renderer_budget_from_dialog(self, budget: object) -> None:
        result = self.create_simulation_preset_from_payload(
            "simulation.configure_renderer_budget", dict(budget or {})
        )
        dialog = getattr(self, "_fx_properties_dialog", None)
        if dialog is not None:
            dialog.set_performance_budget(dict(result.get("budget") or {}))
            self._refresh_fx_renderer_stats_for_dialog()

    def _refresh_fx_renderer_stats_for_dialog(self) -> None:
        result = self.create_simulation_preset_from_payload("simulation.renderer_stats", {})
        dialog = getattr(self, "_fx_properties_dialog", None)
        if dialog is not None:
            dialog.set_renderer_stats(dict(result.get("stats") or {}))

    def _bake_active_fx_from_properties(self) -> None:
        self.create_simulation_preset_from_payload(
            "simulation.bake_effect",
            {
                "start_frame": int(getattr(self, "_dcc_timeline_frame_start", 1)),
                "end_frame": int(getattr(self, "_dcc_timeline_frame_end", 120)),
                "frame_rate": float(getattr(self, "simulation_frame_rate", 30.0)),
            },
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Compact command surface. Advanced DCC controls expand into the first row.
        toolbar_frame = QFrame(self)
        toolbar_frame.setFixedHeight(76)
        toolbar_frame.setObjectName("meshPainterToolbar")

        toolbar_layout = QVBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(10, 4, 10, 4)
        toolbar_layout.setSpacing(4)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)
        paint_toolbar_widget = QWidget(toolbar_frame)
        paint_hdr = QHBoxLayout(paint_toolbar_widget)
        paint_hdr.setContentsMargins(0, 0, 0, 0)
        paint_hdr.setSpacing(8)
        paint_toolbar_scroll = QScrollArea(toolbar_frame)
        paint_toolbar_scroll.setFrameShape(QFrame.NoFrame)
        paint_toolbar_scroll.setWidgetResizable(True)
        paint_toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        paint_toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        paint_toolbar_scroll.setWidget(paint_toolbar_widget)
        paint_toolbar_scroll.setFixedHeight(34)
        paint_toolbar_scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; } QWidget { background: transparent; }")
        toolbar_layout.addLayout(hdr)
        toolbar_layout.addWidget(paint_toolbar_scroll)

        lbl = QLabel(f"<b>{WHOLE_PICTURE_VIEWER_NAME}</b>")
        set_ui_role(lbl, "sectionTitle")
        lbl.setToolTip("Adaptive local and bridged DCC scene viewport.")
        hdr.addWidget(lbl)

        reset_btn = QPushButton("Reset")
        configure_button(reset_btn, "refresh", text="Reset", tooltip="Reset the demo sphere and camera.", role="danger")
        reset_btn.clicked.connect(self.reset_demo_sphere)
        hdr.addWidget(reset_btn)

        open_import_btn = QPushButton("Import")
        configure_button(open_import_btn, "folder", text="Import", tooltip="Open OBJ geometry or import a texture map.", role="primary")
        open_import_btn.clicked.connect(self.open_or_import_file_dialog)
        hdr.addWidget(open_import_btn)

        scene_menu_btn = QPushButton("Scene")
        configure_button(scene_menu_btn, "document", text="Scene", tooltip="Open or save a Tech Connector multi-DCC scene.")
        scene_menu = QMenu(scene_menu_btn)
        scene_menu.addAction("Open Scene...", self.open_federated_scene_dialog)
        scene_menu.addAction("Save Scene...", self.save_federated_scene_dialog)
        scene_menu.addAction("Compose USD Layers...", self.compose_usd_layers_dialog)
        scene_menu.addAction("USD Composition Status...", self.show_usd_composition_status)
        restore_menu = scene_menu.addMenu("Restore Linked DCCs")
        restore_group = QActionGroup(self)
        restore_group.setExclusive(True)
        restore_options = (
            ("Ask Before Launching", "ask"),
            ("Restore Automatically", "automatic"),
            ("Use Cached Sources Only", "cached_only"),
        )
        for label, policy in restore_options:
            action = restore_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(policy == self._dcc_scene_restore_policy)
            action.triggered.connect(lambda checked=False, value=policy: self.set_dcc_scene_restore_policy(value))
            restore_group.addAction(action)
        restore_menu.addSeparator()
        restore_menu.addAction("Linked Source Status...", self.show_dcc_scene_restore_status)
        self._dcc_scene_restore_action_group = restore_group
        scene_menu.addSeparator()
        scene_menu.addAction("Convert Loaded DCC Scene To TC", self.convert_loaded_dcc_scene_to_tc)
        scene_menu.addAction("Convert Selected DCC Object To TC", lambda: self.convert_loaded_dcc_scene_to_tc(selection=True))
        scene_menu_btn.setMenu(scene_menu)
        self.scene_menu_btn = scene_menu_btn

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
        configure_button(load_dcc_btn, "refresh", text="Refresh", tooltip="Add or refresh the selected DCC. If multiple sessions are live, choose or reuse the preferred session.")
        load_dcc_btn.clicked.connect(self.load_selected_dcc_scene_snapshot)
        hdr.addWidget(load_dcc_btn)
        import_scene_btn = QPushButton("Import Scene")
        configure_button(import_scene_btn, "external_link", text="Import scene", tooltip="Browse all live DCC sessions from every supported app and import selected scenes.")
        import_scene_btn.clicked.connect(self.show_import_scene_dialog)
        hdr.addWidget(import_scene_btn)

        self.maya_selected_only_checkbox = QCheckBox("Selected")
        self.maya_selected_only_checkbox.setToolTip("Load only selected Maya mesh transforms when querying the scene.")
        hdr.addWidget(self.maya_selected_only_checkbox)

        self.live_dcc_refresh_btn = QPushButton("Live")
        self.live_dcc_refresh_btn.setCheckable(True)
        self.live_dcc_refresh_btn.setToolTip("Continuously follow the loaded DCC scene. Cached frames are used when available.")
        self.live_dcc_refresh_btn.toggled.connect(self.set_live_dcc_refresh)
        hdr.addWidget(self.live_dcc_refresh_btn)

        self.cache_timeline_btn = QPushButton("Cache Timeline")
        self.cache_timeline_btn.setCheckable(True)
        self.cache_timeline_btn.setToolTip("Cache the loaded Maya timeline in the background for 1:1 local playback.")
        self.cache_timeline_btn.toggled.connect(self.set_timeline_cache_enabled)
        hdr.addWidget(self.cache_timeline_btn)

        self.camera_authority_combo = QComboBox()
        self.camera_authority_combo.setToolTip("Choose a camera. Use Cam makes this viewer follow it; Drive Selected pushes this viewer camera to it.")
        self.camera_authority_combo.addItem("TC Camera", {"mode": "tech_connector"})
        hdr.addWidget(self.camera_authority_combo)

        self.use_selected_camera_btn = QPushButton("Use Cam")
        self.use_selected_camera_btn.setToolTip("Make the Tech Connector viewer follow the camera selected in the dropdown.")
        self.use_selected_camera_btn.clicked.connect(self.sync_selected_camera_authority)
        hdr.addWidget(self.use_selected_camera_btn)

        constraint_btn = QPushButton("Constrain")
        constraint_btn.setToolTip("Constrain the selected target proxy to another loaded DCC object through Tech Connector shared space.")
        constraint_btn.clicked.connect(self.create_cross_dcc_transform_constraint_from_selection)
        hdr.addWidget(constraint_btn)

        flip_constraint_btn = QPushButton("Flip")
        flip_constraint_btn.setToolTip("Flip the active driver/driven direction on the most recent reversible cross-DCC constraint.")
        flip_constraint_btn.clicked.connect(self.flip_latest_cross_dcc_constraint_direction)
        hdr.addWidget(flip_constraint_btn)

        self.drive_camera_btn = QPushButton("Drive Selected")
        self.drive_camera_btn.setCheckable(True)
        self.drive_camera_btn.setToolTip("Continuously push this viewer camera to the selected DCC camera after navigation settles.")
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
        configure_button(self.dcc_toolbar_toggle_btn, "external_link", text="DCC", tooltip="Show advanced DCC camera, refresh, and constraint controls.")
        paint_hdr.addWidget(self.dcc_toolbar_toggle_btn)
        paint_hdr.addWidget(self.scene_menu_btn)

        undo_btn = QPushButton("Undo")
        configure_button(undo_btn, "undo", text="Undo", tooltip="Undo the last viewport action (Ctrl+Z).", icon_only=True)
        undo_btn.clicked.connect(self.undo_viewer_action)
        paint_hdr.addWidget(undo_btn)

        redo_btn = QPushButton("Redo")
        configure_button(redo_btn, "redo", text="Redo", tooltip="Redo the last undone viewport action (Ctrl+Y).", icon_only=True)
        redo_btn.clicked.connect(self.redo_viewer_action)
        paint_hdr.addWidget(redo_btn)

        self.syncsketch_markup_btn = QPushButton("Markup")
        self.syncsketch_markup_btn.setCheckable(True)
        self.syncsketch_markup_btn.setToolTip("Toggle SyncSketch-style markup mode (Ctrl+M). Clear all markups with Ctrl+Shift+M.")
        self.syncsketch_markup_btn.toggled.connect(self.set_syncsketch_markup_mode)
        configure_button(self.syncsketch_markup_btn, "edit", text="Markup", tooltip="Toggle markup mode (Ctrl+M). Clear all markups with Ctrl+Shift+M.")
        paint_hdr.addWidget(self.syncsketch_markup_btn)

        self.shot_guides_btn = QPushButton("Shot")
        self.shot_guides_btn.setToolTip("Perspective shot guides. Drag guide points, then apply their math to the viewer camera.")
        shot_menu = QMenu(self.shot_guides_btn)
        shot_menu.addAction("Off", lambda: self.set_shot_guide_mode("Off"))
        shot_menu.addSeparator()
        for guide_mode in (
            "1-Point Perspective",
            "2-Point Perspective",
            "3-Point Perspective",
            "4-Point Perspective (Curvilinear)",
            "5-Point Perspective (Fisheye Lens)",
            "6-Point Perspective (360 Spherical)",
        ):
            shot_menu.addAction(guide_mode, lambda _checked=False, value=guide_mode: self.set_shot_guide_mode(value))
        shot_menu.addSeparator()
        shot_menu.addAction("Reset Guide Points", self.reset_shot_guides)
        shot_menu.addAction("Solve Guide Camera", lambda: self.solve_shot_guides(apply_camera=False))
        shot_menu.addAction("Apply To Viewer Camera", lambda: self.solve_shot_guides(apply_camera=True))
        self.shot_guides_btn.setMenu(shot_menu)
        configure_button(self.shot_guides_btn, "camera", text="Shot", tooltip="Configure perspective guides and apply their solve to the viewer camera.")
        paint_hdr.addWidget(self.shot_guides_btn)

        self.shot_take_combo = QComboBox()
        self.shot_take_combo.setToolTip("Captured shot/take profiles: camera, frame range, timecode, guide solve, and retarget handoff state.")
        self.shot_take_combo.setMinimumWidth(180)
        self.shot_take_combo.currentIndexChanged.connect(self.on_shot_take_combo_changed)
        paint_hdr.addWidget(self.shot_take_combo)
        self.refresh_shot_take_combo()

        self.motion_btn = QPushButton(HEPHAESTUS_SECTION_THREAD)
        self.motion_btn.setToolTip("Chronos-style shot/take controls for timecode, retargeting, and Unreal Sequencer handoff.")
        motion_menu = QMenu(self.motion_btn)
        motion_menu.addAction("Capture Current Shot / Take", self.capture_current_shot_take_profile)
        motion_menu.addAction("Apply Selected Shot / Take", self.apply_active_shot_take_profile)
        motion_menu.addSeparator()
        motion_menu.addAction("Create Animation Take...", self.prompt_create_animation_take)
        motion_menu.addAction("Add Animation Layer...", self.prompt_add_animation_layer)
        motion_menu.addAction("Key Selected Controls", self.key_selected_rig_controls)
        self.auto_key_action = motion_menu.addAction("Auto Key On Change")
        self.auto_key_action.setCheckable(True)
        self.auto_key_action.setChecked(self.auto_key_enabled)
        self.auto_key_action.setToolTip("Set keys for changed transform channels when a manipulator edit is committed.")
        self.auto_key_action.toggled.connect(self.set_auto_key_enabled)
        motion_menu.addSeparator()
        motion_menu.addAction("Send Selected Shot To Unreal Sequencer", self.send_active_shot_to_unreal_sequence)
        motion_menu.addAction("Retarget / Take Status", self.show_active_shot_retarget_status)
        self.motion_btn.setMenu(motion_menu)
        paint_hdr.addWidget(self.motion_btn)

        self.skinning_btn = QPushButton(HEPHAESTUS_SECTION_HAMMER)
        self.skinning_btn.setToolTip("Hephaestus-style sculpting, deformation, and weight-painting tools for TC-native meshes and bridged DCC selections.")
        skinning_menu = QMenu(self.skinning_btn)
        bind_menu = skinning_menu.addMenu("Bind Skin")
        bind_menu.addAction("Heat Map Bind", lambda: self.run_skinning_command_from_ui("skinning.bind_skin", {"bind_method": "heat"}))
        bind_menu.addAction("Geodesic Voxel Bind", lambda: self.run_skinning_command_from_ui("skinning.bind_skin", {"bind_method": "geodesic_voxel"}))
        bind_menu.addAction("Closest Distance Bind", lambda: self.run_skinning_command_from_ui("skinning.bind_skin", {"bind_method": "distance"}))
        bind_menu.addAction("Current / Existing Weights", lambda: self.run_skinning_command_from_ui("skinning.bind_skin", {"bind_method": "current"}))
        skinning_menu.addAction("Auto Skinner...", lambda: self.run_skinning_command_from_ui("skinning.auto_skin", {"bind_method": "auto"}))
        skinning_menu.addAction("Paint Weights...", self.prompt_paint_skin_weights)
        skinning_menu.addAction("Normalize Weights", lambda: self.run_skinning_command_from_ui("skinning.normalize_weights"))
        skinning_menu.addAction("Prune Weights", lambda: self.run_skinning_command_from_ui("skinning.prune_weights"))
        skinning_menu.addAction("Smooth Weights", lambda: self.run_skinning_command_from_ui("skinning.smooth_weights"))
        skinning_menu.addAction("Mirror Weights", lambda: self.run_skinning_command_from_ui("skinning.mirror_weights"))
        skinning_menu.addAction("Copy Weights", lambda: self.preview_skinning_route("skinning.copy_weights", "Copy Weights"))
        skinning_menu.addAction("Transfer Weights...", lambda: self.preview_skinning_route("skinning.transfer_weights", "Transfer Weights"))
        skinning_menu.addSeparator()
        skinning_menu.addAction("Paint Selected Deformer Influence", self.paint_selected_deformer_influence)
        skinning_menu.addAction("Add Jiggle To Selected Skin / Deformer", self.add_jiggle_to_selected_deformer)
        skinning_menu.addAction("Enable Fleshy Collision On Selected Skin", self.enable_fleshy_selected_skin)
        secondary_menu = skinning_menu.addMenu("Add Secondary Motion Preset")
        for preset_id, label in (
            ("subtle_skin", "Subtle Skin"), ("soft_tissue", "Soft Tissue"),
            ("belly_chest", "Belly / Chest"), ("face_flesh", "Facial Soft Tissue"),
            ("cartilage", "Cartilage"), ("ears_tendrils", "Ears / Tendrils"),
            ("tail_overlap", "Tail Overlap"), ("muscle_follow", "Muscle Follow-through"),
            ("stylized_goop", "Stylized Goop"),
        ):
            secondary_menu.addAction(
                label, lambda _checked=False, key=preset_id: self.add_secondary_motion_preset_to_selected_skin(key)
            )
        skinning_menu.addSeparator()
        skinning_menu.addAction("Import Weights...", self.prompt_import_skin_weights)
        skinning_menu.addAction("Export Weights...", self.prompt_export_skin_weights)
        self.skinning_btn.setMenu(skinning_menu)
        paint_hdr.addWidget(self.skinning_btn)

        self.modeling_btn = QPushButton(HEPHAESTUS_SECTION_ANVIL)
        self.modeling_btn.setToolTip("Native polygon component modeling. All edits share the chat-callable command layer and Viewer undo stack.")
        modeling_menu = QMenu(self.modeling_btn)
        modeling_menu.addAction("Select Faces By Index...", self.prompt_mesh_face_selection)
        modeling_menu.addAction("Select Vertices By Index...", self.prompt_mesh_vertex_selection)
        modeling_menu.addAction("Select Edges By Vertex Pair...", self.prompt_mesh_edge_selection)
        pose_menu = modeling_menu.addMenu("Default Pose")
        pose_menu.addAction(
            "Restore Default Shape",
            lambda: self.run_modeling_command_from_ui("modeling.restore_default_pose"),
        )
        pose_menu.addAction(
            "Set Current Shape As Default",
            lambda: self.run_modeling_command_from_ui("modeling.update_default_pose"),
        )
        modeling_menu.addSeparator()
        modeling_menu.addAction("Insert Edge Loop...", self.prompt_split_selected_edge_loop)
        modeling_menu.addAction("Bevel Selected Edges...", self.prompt_bevel_selected_edges)
        modeling_menu.addSeparator()
        modeling_menu.addAction("Generate Mesh LODs...", self.prompt_generate_mesh_lods)
        modeling_menu.addAction("Compile Point Runtime Proxy...", lambda: self.prompt_compile_runtime_geometry("point"))
        modeling_menu.addAction("Compile Virtualized Hard Surface...", lambda: self.prompt_compile_runtime_geometry("virtual"))
        modeling_menu.addSeparator()
        modeling_menu.addAction("Extrude Selected Faces...", self.prompt_extrude_selected_faces)
        modeling_menu.addAction("Extrude All Faces...", lambda: self.prompt_extrude_selected_faces(all_faces=True))
        modeling_menu.addAction("Delete Selected Faces", lambda: self.run_modeling_command_from_ui("modeling.delete_faces"))
        modeling_menu.addAction("Triangulate Selected Faces", lambda: self.run_modeling_command_from_ui("modeling.triangulate_faces"))
        modeling_menu.addAction("Triangulate Entire Mesh", lambda: self.run_modeling_command_from_ui("modeling.triangulate_faces", {"all_faces": True}))
        modeling_menu.addAction("Merge Selected Vertices", lambda: self.run_modeling_command_from_ui("modeling.merge_vertices"))
        self.modeling_btn.setMenu(modeling_menu)
        paint_hdr.addWidget(self.modeling_btn)

        self.fx_btn = QPushButton("FX")
        configure_button(
            self.fx_btn,
            "sparkles",
            text="FX",
            tooltip="Create particle, energy, weather, and world effects, then preview or bake them.",
        )
        self.fluids_btn = QPushButton("Water & Fluids")
        configure_button(
            self.fluids_btn,
            "bucket",
            text="Water & Fluids",
            tooltip="Create liquids, soft matter, smoke, fire, and volume simulations.",
        )
        self.dynamics_btn = QPushButton("Dynamics")
        configure_button(
            self.dynamics_btn,
            "graph",
            text="Dynamics",
            tooltip="Create cloth, soft bodies, reformable materials, destruction, and reactive surfaces.",
        )
        self.simulation_btn = QPushButton("Simulation")
        configure_button(
            self.simulation_btn,
            "play",
            text="Simulation",
            tooltip="Configure, play, cache, diagnose, and transfer the active simulation.",
        )
        simulation_menu = QMenu(self.simulation_btn)
        simulation_menu.addAction("Simulation Setup...", self.show_simulation_runtime_setup)
        simulation_menu.addAction("Physics Joints...", self.show_physics_joint_editor)
        self.live_game_save_action = simulation_menu.addAction("Update Running Game on Save")
        self.live_game_save_action.setCheckable(True)
        self.live_game_save_action.setChecked(True)
        simulation_menu.addAction("Update Running Game Now", self.update_running_game_now)
        simulation_menu.addSeparator()
        dynamics_menu = QMenu(self.dynamics_btn)
        dynamics_menu.setTitle("Dynamics")
        cloth_menu = dynamics_menu.addMenu("Cloth & fabric")
        for label, material in (("Cotton", "cotton"), ("Silk", "silk"), ("Denim", "denim")):
            cloth_menu.addAction(label, lambda _checked=False, value=material: self.create_simulation_preset("cloth", value))
        cloth_menu.addSeparator()
        cloth_menu.addAction("Convert Current Mesh To Cloth", lambda: self.create_current_mesh_cloth("cotton"))
        fluid_menu = QMenu(self.fluids_btn)
        fluid_menu.setTitle("Water & Fluids")
        liquids_menu = fluid_menu.addMenu("Liquid presets")
        for label, material in (("Water", "water"), ("Goop / Slime", "goo"), ("Viscous Gravy", "gravy"), ("Soup", "soup")):
            liquids_menu.addAction(label, lambda _checked=False, value=material: self.create_simulation_preset("fluid", value))
        liquids_menu.addSeparator()
        liquids_menu.addAction("Fill Current Mesh With Soup", lambda: self.create_simulation_preset_from_payload(
            "simulation.fill_geometry_fluid", {"material": "soup"}
        ))
        soft_body_menu = dynamics_menu.addMenu("Soft bodies & reformable matter")
        soft_body_menu.addAction("Current Mesh To Jello", lambda: self.create_simulation_preset_from_payload(
            "simulation.create_soft_body", {"material": "jello"}
        ))
        soft_body_menu.addAction("Current Mesh To Reformable Playdoh", lambda: self.create_simulation_preset_from_payload(
            "simulation.create_reformable_dough", {"material": "playdoh"}
        ))
        destruction_menu = dynamics_menu.addMenu("Destruction & phase change")
        destruction_menu.addAction("Current Mesh To Breakable Glass", lambda: self.create_simulation_preset_from_payload(
            "simulation.create_breakable_solid", {"material": "glass"}
        ))
        destruction_menu.addAction("Current Mesh To Meltable Metal", lambda: self.create_simulation_preset_from_payload(
            "simulation.create_breakable_solid", {"material": "metal"}
        ))
        volume_menu = fluid_menu.addMenu("Fire, smoke & volumes")
        volume_menu.addAction("Fire / Smoke", lambda: self.create_simulation_preset("volume", "fire"))
        volume_menu.addAction("Plasma", lambda: self.create_simulation_preset("volume", "plasma"))
        fluid_menu.addSeparator()
        fluid_menu.addAction("Use Current Mesh As Water Emitter", lambda: self.add_current_mesh_as_simulation_emitter("water"))
        fluid_menu.addAction("Use Current Mesh As Collider", self.add_current_mesh_as_simulation_collider)

        fx_menu = QMenu(self.fx_btn)
        fx_menu.setTitle("FX")
        fx_menu.addAction("FX Properties...", self.show_fx_properties)
        fx_menu.addSeparator()
        fx_energy = fx_menu.addMenu("Energy / Magic")
        for label, preset in (("Sparks", "sparks"), ("Explosion", "explosion"), ("Portal", "portal"), ("Magic Ribbons", "magic_ribbons"), ("Lightning", "lightning"), ("Chain Lightning", "chain_lightning"), ("Tesla Coil", "tesla_coil"), ("Plasma Arc", "plasma_arc"), ("Shield Impact", "shield_impact"), ("Refractive Bubbles", "refractive_bubbles"), ("Heat Haze", "heat_haze"), ("Fireworks", "fireworks"), ("Disintegration", "disintegration")):
            fx_energy.addAction(label, lambda _checked=False, value=preset: self.create_simulation_preset_from_payload("simulation.create_effect", {"preset": value}))
        fx_weather = fx_menu.addMenu("Atmosphere / Weather")
        for label, preset in (("Rain", "rain"), ("Snow", "snow"), ("Fog", "fog"), ("Cloud Bank", "clouds"), ("Dust", "dust"), ("Sandstorm", "sandstorm"), ("Electrical Storm", "electrical_storm"), ("Aurora", "aurora")):
            fx_weather.addAction(label, lambda _checked=False, value=preset: self.create_simulation_preset_from_payload("simulation.create_effect", {"preset": value}))
        fx_disasters = fx_menu.addMenu("World / Disasters")
        for label, preset in (("Tornado", "tornado"), ("Hurricane", "hurricane"), ("Volcano", "volcano"), ("Earthquake", "earthquake"), ("Mudslide", "mudslide"), ("Avalanche", "avalanche")):
            fx_disasters.addAction(label, lambda _checked=False, value=preset: self.create_simulation_preset_from_payload("simulation.create_effect", {"preset": value}))
        fx_menu.addSeparator()
        fx_menu.addAction("Use Current Mesh As Particle", lambda: self.create_simulation_preset_from_payload("simulation.set_effect_renderer", {"renderer_type": "mesh"}))
        fx_menu.addSeparator()
        fx_menu.addAction(
            "Bake Active FX (Timeline Range)",
            lambda: self.create_simulation_preset_from_payload(
                "simulation.bake_effect",
                {
                    "start_frame": int(getattr(self, "_dcc_timeline_frame_start", 1)),
                    "end_frame": int(getattr(self, "_dcc_timeline_frame_end", 120)),
                    "frame_rate": float(getattr(self, "simulation_frame_rate", 30.0)),
                },
            ),
        )
        fx_menu.addAction(
            "Renderer Performance...",
            lambda: self.create_simulation_preset_from_payload("simulation.renderer_stats", {}),
        )
        surface_menu = dynamics_menu.addMenu("Reactive surfaces")
        for label, material in (("Snow", "snow"), ("Mud", "mud"), ("Sand", "sand"), ("Soil", "soil"), ("Wood", "wood"), ("Glass", "glass"), ("Metal", "metal")):
            surface_menu.addAction(label, lambda _checked=False, value=material: self.create_simulation_preset_from_payload("simulation.create_deformable_surface", {"material": value}))
        surface_menu.addSeparator()
        surface_menu.addAction("Stamp Footprint", lambda: self.create_simulation_preset_from_payload("simulation.apply_footprint", {}))
        surface_menu.addAction("Projectile Impact", lambda: self.create_simulation_preset_from_payload("simulation.apply_projectile", {"energy": 8.0}))
        simulation_menu.addSeparator()
        simulation_menu.addAction("Use Current Mesh As Collider", self.add_current_mesh_as_simulation_collider)
        fields_menu = simulation_menu.addMenu("Fields")
        fields_menu.addAction("Point Gravity At Origin", self.add_default_simulation_gravity_source)
        fields_menu.addAction("Curve Flow", lambda: self.create_simulation_preset_from_payload(
            "simulation.add_curve_flow", {}
        ))
        fields_menu.addAction("Heat At Origin", lambda: self.create_simulation_preset_from_payload(
            "simulation.add_temperature_source", {"temperature_rate": 2200.0, "radius": 2.0}
        ))
        simulation_menu.addSeparator()
        self.simulation_play_action = simulation_menu.addAction("Play Simulation")
        self.simulation_play_action.setCheckable(True)
        self.simulation_play_action.toggled.connect(self.set_simulation_playing)
        simulation_menu.addAction("Step One Frame", self.step_active_simulation)
        simulation_menu.addAction("Reset Simulation", self.reset_active_simulation)
        runtime_profile_menu = simulation_menu.addMenu("Advanced Runtime")
        for label, profile in (
            ("Cinematic", "cinematic"), ("Photoreal Realtime", "photoreal"),
            ("Realtime", "realtime"), ("Mobile", "mobile"), ("Toony", "toony"),
            ("Stylized", "stylized"), ("Retro", "retro"),
        ):
            runtime_profile_menu.addAction(
                label,
                lambda _checked=False, value=profile: self.create_simulation_preset_from_payload(
                    "simulation.compile_runtime_profile", {"profile": value}
                ),
            )
        runtime_profile_menu.addSeparator()
        runtime_profile_menu.addAction(
            "Inspect Execution Plan",
            lambda: self.create_simulation_preset_from_payload("simulation.inspect_execution_plan", {}),
        )
        simulation_menu.addAction("Transfer Manifest...", self.show_simulation_transfer_manifest)
        self.fx_btn.setMenu(fx_menu)
        self.fluids_btn.setMenu(fluid_menu)
        self.dynamics_btn.setMenu(dynamics_menu)
        self.simulation_btn.setMenu(simulation_menu)
        paint_hdr.addWidget(self.fx_btn)
        paint_hdr.addWidget(self.fluids_btn)
        paint_hdr.addWidget(self.dynamics_btn)
        paint_hdr.addWidget(self.simulation_btn)

        self.look_btn = QPushButton(HEPHAESTUS_SECTION_ORACLE)
        self.look_btn.setToolTip("Oracle (Rendering): choose visual style and world layout without changing gameplay or simulation.")
        look_menu = QMenu(self.look_btn)
        visual_style_menu = look_menu.addMenu("Visual Style")
        for label, style in (
            ("8-Bit Pixel Art", "pixel_8bit"),
            ("16-Bit Pixel Art", "pixel_16bit"),
            ("Clean Vector", "vector_flat"),
            ("Hand Painted", "hand_painted"),
            ("Toon / Cel Shaded", "toon"),
            ("Low Poly", "low_poly"),
            ("Retro 3D", "retro_3d"),
            ("Stylized Real-Time", "stylized_pbr"),
            ("Photoreal", "photoreal"),
            ("Hyper Real", "hyperreal"),
        ):
            visual_style_menu.addAction(label, lambda _checked=False, value=style: self.set_viewer_visual_style(value))
        world_layout_menu = look_menu.addMenu("World Layout")
        for label, layout in (("2D", "2d"), ("2.5D", "2.5d"), ("3D", "3d"), ("Mixed", "mixed")):
            world_layout_menu.addAction(label, lambda _checked=False, value=layout: self.set_viewer_world_layout(value))
        environment_menu = look_menu.addMenu("Environment")
        lighting_profile_menu = environment_menu.addMenu(f"{HEPHAESTUS_SECTION_HELIOS} Profile")
        from tech_connector.game_engine.rendering.lighting_profile_service import lighting_profiles
        for profile in lighting_profiles():
            action = lighting_profile_menu.addAction(profile.display_name)
            action.setToolTip(profile.description)
            action.triggered.connect(
                lambda _checked=False, value=profile.profile_id: self.set_viewport_lighting_profile(value)
            )
        environment_menu.addSeparator()
        environment_menu.addAction("Load HDRI / Environment...", self.choose_viewport_environment)
        environment_menu.addAction("Clear Environment", self.clear_viewport_environment)
        exposure_menu = environment_menu.addMenu("Exposure")
        for label, exposure in (
            ("Dark Studio", 0.65),
            ("Neutral", 1.0),
            ("Bright Exterior", 1.5),
            ("Fantasy Glow", 2.25),
        ):
            exposure_menu.addAction(
                label,
                lambda _checked=False, value=exposure: self.set_viewport_environment_exposure(value),
            )
        debug_display_menu = look_menu.addMenu("Debug Display")
        self.object_vectors_action = debug_display_menu.addAction("Object Local Axes")
        self.object_vectors_action.setCheckable(True)
        self.object_vectors_action.setChecked(self.show_object_vector_handles)
        self.object_vectors_action.toggled.connect(
            lambda enabled: self.set_viewport_debug_setting("show_object_vector_handles", enabled)
        )
        self.vertex_normals_action = debug_display_menu.addAction("Vertex Normals")
        self.vertex_normals_action.setCheckable(True)
        self.vertex_normals_action.setChecked(self.show_vertex_normals)
        self.vertex_normals_action.toggled.connect(
            lambda enabled: self.set_viewport_debug_setting("show_vertex_normals", enabled)
        )
        self.face_normals_action = debug_display_menu.addAction("Face Normals")
        self.face_normals_action.setCheckable(True)
        self.face_normals_action.setChecked(self.show_face_normals)
        self.face_normals_action.toggled.connect(
            lambda enabled: self.set_viewport_debug_setting("show_face_normals", enabled)
        )
        self.simulation_diagnostics_action = debug_display_menu.addAction("Simulation Physics Diagnostics")
        self.simulation_diagnostics_action.setCheckable(True)
        self.simulation_diagnostics_action.setChecked(self.show_simulation_diagnostics)
        self.simulation_diagnostics_action.toggled.connect(
            lambda enabled: self.set_viewport_debug_setting("show_simulation_diagnostics", enabled)
        )
        debug_display_menu.addSeparator()
        vector_length_menu = debug_display_menu.addMenu("Object Axis Length")
        for label, length in (("Short", 0.15), ("Medium", 0.35), ("Long", 0.75), ("Extra Long", 1.5)):
            vector_length_menu.addAction(
                label,
                lambda _checked=False, value=length: self.set_viewport_debug_setting("debug_vector_length", value),
            )
        normal_length_menu = debug_display_menu.addMenu("Normal Length")
        for label, length in (("Short", 0.05), ("Medium", 0.2), ("Long", 0.5), ("Extra Long", 1.0)):
            normal_length_menu.addAction(
                label,
                lambda _checked=False, value=length: self.set_viewport_debug_setting("debug_normal_length", value),
            )
        normal_density_menu = debug_display_menu.addMenu("Normal Density")
        for label, stride in (("Every Normal", 1), ("1 in 4", 4), ("1 in 8", 8), ("1 in 16", 16)):
            normal_density_menu.addAction(
                label,
                lambda _checked=False, value=stride: self.set_viewport_debug_setting("debug_normal_stride", value),
            )
        look_menu.addSeparator()
        self.pixel_perfect_action = look_menu.addAction("Pixel Perfect")
        self.pixel_perfect_action.setCheckable(True)
        self.pixel_perfect_action.toggled.connect(
            lambda enabled: self.update_viewer_visual_setting("pixel_perfect", enabled)
        )
        look_menu.addAction("Explain Current Look", self.explain_viewer_visual_settings)
        look_menu.addAction("Preview Desktop Render Plan", self.preview_viewer_visual_plan)
        self.look_btn.setMenu(look_menu)
        paint_hdr.addWidget(self.look_btn)

        rigging_btn = QPushButton(HEPHAESTUS_SECTION_FORGE)
        rigging_btn.setToolTip("Open Charon rigging tools or attach selected controls to the active mesh face.")
        rigging_menu = QMenu(rigging_btn)
        rigging_menu.addAction("Open Rigging Workspace", self.open_rigging_workspace)
        rigging_menu.addSeparator()
        rigging_menu.addAction(
            "Constrain Selected Control To Face",
            lambda: self.run_surface_constraint_from_ui("rigging.constrain_to_mesh"),
        )
        rigging_menu.addAction(
            "Align Selected Control To Face Normal",
            lambda: self.run_surface_constraint_from_ui("rigging.constrain_to_normal"),
        )
        rigging_menu.addSeparator()
        rigging_menu.addAction("Create Quadruped Leg IK...", self.prompt_create_quadruped_leg)
        rigging_menu.addAction("Create Mechanical Relationship...", self.prompt_create_mechanical_rig)
        rigging_btn.setMenu(rigging_menu)
        paint_hdr.addWidget(rigging_btn)

        # Color Swatch Button
        self.color_btn = QPushButton("Color")
        self.color_btn.setStyleSheet(f"background-color: {self.primary_color.name()}; color: #000000; font-weight: bold;")
        self.color_btn.clicked.connect(self.pick_primary_color)
        paint_hdr.addWidget(self.color_btn)
        screen_pick_btn = QPushButton("Pick")
        screen_pick_btn.setToolTip("Sample a color from anywhere on the screen.")
        screen_pick_btn.clicked.connect(self.start_desktop_color_pick)
        paint_hdr.addWidget(screen_pick_btn)
        save_palette_btn = QPushButton("Save")
        save_palette_btn.setToolTip("Save the active paint color to your preferred palette.")
        save_palette_btn.clicked.connect(self.add_current_color_to_palette)
        paint_hdr.addWidget(save_palette_btn)
        self.palette_swatch_row = QWidget(self)
        palette_swatch_layout = QHBoxLayout(self.palette_swatch_row)
        palette_swatch_layout.setContentsMargins(0, 0, 0, 0)
        palette_swatch_layout.setSpacing(3)
        self.palette_swatch_layout = palette_swatch_layout
        paint_hdr.addWidget(self.palette_swatch_row)


        # Primitive Selector Dropdown
        paint_hdr.addWidget(QLabel("<span style='color:#a0b0c0;'>Create:</span>"))
        self.primitive_combo = QComboBox()
        self.primitive_combo.addItems(["Sphere", "Cube", "Cylinder"])
        self.primitive_combo.currentTextChanged.connect(self.create_primitive_mesh)
        paint_hdr.addWidget(self.primitive_combo)

        # Transform Gizmo Mode Selector
        self.gizmo_mode_combo = QComboBox()
        self.gizmo_mode_combo.addItems(["Select (Q)", "Paint (P)", "Translate (W)", "Rotate (E)", "Scale (R/S)", "Vertex (F8)", "Edge (F9)", "Face (F10)"])
        self.gizmo_mode_combo.setCurrentText("Select (Q)")
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
        self.paint_target_combo = QComboBox()
        self.paint_target_combo.setToolTip("Choose what the brush edits. Deformation maps use blue for upstream and green for fully driven.")
        self.paint_target_combo.addItem("Color", "color")
        self.paint_target_combo.addItem("Skin Output", "skin_output")
        self.paint_target_combo.addItem("Simulation Drive", "simulation_drive")
        self.paint_target_combo.addItem("Emission Source", "emission_source")
        self.paint_target_combo.addItem("Jiggle", "jiggle")
        self.paint_target_combo.currentIndexChanged.connect(self.change_paint_target)
        paint_hdr.addWidget(self.paint_target_combo)
        custom_brush_btn = QPushButton("Load Alpha")
        custom_brush_btn.setToolTip("Load a custom brush alpha image. PNG alpha is used when present; grayscale masks also work.")
        custom_brush_btn.clicked.connect(self.load_custom_brush_alpha)
        paint_hdr.addWidget(custom_brush_btn)

        # Brush Size SpinBox
        paint_hdr.addWidget(QLabel("<span style='color:#a0b0c0;'>Size:</span>"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 300)
        self.size_spin.setValue(self.brush_size)
        self.size_spin.valueChanged.connect(self.change_brush_size)
        paint_hdr.addWidget(self.size_spin)
        paint_hdr.addWidget(QLabel("<span style='color:#a0b0c0;'>Soft:</span>"))
        self.softness_spin = QSpinBox()
        self.softness_spin.setRange(0, 100)
        self.softness_spin.setValue(self.brush_softness)
        self.softness_spin.setToolTip("Brush edge softness. Works on built-in and loaded alpha brushes.")
        self.softness_spin.valueChanged.connect(self.change_brush_softness)
        paint_hdr.addWidget(self.softness_spin)

        # Symmetry Toggle
        self.sym_btn = QPushButton("X-Symmetry")
        self.sym_btn.setCheckable(True)
        self.sym_btn.setChecked(False)
        paint_hdr.addWidget(self.sym_btn)

        self.texture_btn = QPushButton(HEPHAESTUS_SECTION_KILN)
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
        self.scene_outliner.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        self.scene_outliner.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scene_outliner.customContextMenuRequested.connect(self.show_scene_outliner_context_menu)
        left_panel = QWidget(self)
        self.scene_left_panel = left_panel
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
        self.instance_visibility_section_btn = QPushButton("Visibility >")
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
        self.viewport_stack = QWidget(self.scene_splitter)
        viewport_stack_layout = QStackedLayout(self.viewport_stack)
        viewport_stack_layout.setContentsMargins(0, 0, 0, 0)
        viewport_stack_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.gpu_viewport = None
        self.gpu_viewport_enabled = os.environ.get("TECH_CONNECTOR_GPU_VIEWPORT", "1").strip().lower() not in {"0", "false", "off"}
        if self.gpu_viewport_enabled:
            try:
                from tech_connector.ui.three_d_gpu_viewport import ThreeDGpuViewport

                self.gpu_viewport = ThreeDGpuViewport(self.viewport_stack)
                self.gpu_viewport.backend_failed.connect(self.on_gpu_viewport_failed)
                viewport_stack_layout.addWidget(self.gpu_viewport)
            except Exception as exc:
                self.gpu_viewport_enabled = False
                self._gpu_viewport_error = str(exc)
        self.dcc_viewport_stream = None
        self._dcc_stream_frame = QImage()
        self._dcc_stream_provider = ""
        stream_env = os.environ.get("TECH_CONNECTOR_DCC_VIEWPORT_STREAM", "1").strip().lower()
        offscreen_platform = os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen"
        if stream_env in {"0", "false", "off"} or offscreen_platform:
            self._dcc_stream_status = "DCC window streaming disabled for this session."
        else:
            try:
                from tech_connector.game_engine.integration.dcc_viewport_stream import DccViewportStream

                self.dcc_viewport_stream = DccViewportStream(self, max_fps=30.0)
                self.dcc_viewport_stream.frame_ready.connect(self.on_dcc_viewport_stream_frame)
                self.dcc_viewport_stream.status_changed.connect(self.on_dcc_viewport_stream_status)
            except Exception as exc:
                self._dcc_stream_status = f"DCC window streaming unavailable: {exc}"
        self.canvas = ThreeDMeshCanvas(self.viewport_stack, viewport_owner=self)
        self.canvas.setAttribute(Qt.WA_TranslucentBackground, True)
        self.canvas.setAttribute(Qt.WA_NoSystemBackground, True)
        self.canvas.setAutoFillBackground(False)
        viewport_stack_layout.addWidget(self.canvas)
        self.canvas.raise_()
        self.scene_splitter.addWidget(self.viewport_stack)
        self.scene_splitter.setSizes([260, 1200])
        root.addWidget(self.scene_splitter, 1)

        self.viewport_status_label = QLabel("Ready")
        self.viewport_status_label.setMinimumHeight(24)
        self.viewport_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        set_ui_role(self.viewport_status_label, "muted")
        root.addWidget(self.viewport_status_label)

        # 3. Bottom 3D Animation Scrubber & Timeline Bar (FPS, Keyframes, Playback, Onion Skinning)
        from tech_connector.ui.game_engine.animation_timeline import AnimationFrameSequence, AnimationTimelineBar
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
        self.key_selected_shortcut = QShortcut(QKeySequence("K"), self)
        self.key_selected_shortcut.activated.connect(self.key_selected_rig_controls)
        self.refresh_palette_swatches()
        QTimer.singleShot(0, lambda: self.sync_gpu_viewport(full=True))

    def _apply_accessibility_metadata(self) -> None:
        """Give keyboard and assistive-technology users stable control names."""
        self.setAccessibleName("Tech Connector 3D scene editor")
        explicit_names = {
            "canvas": "3D scene viewport",
            "dcc_scene_provider_combo": "DCC scene provider",
            "viewer_coord_combo": "Viewport coordinate system",
            "camera_authority_combo": "Camera authority",
            "shot_take_combo": "Shot and take profile",
            "gizmo_mode_combo": "Viewport interaction mode",
            "medium_combo": "Paint medium",
            "paint_target_combo": "Paint target",
            "scene_outliner": "Scene hierarchy",
            "instance_details_panel": "Selected object properties",
            "viewport_status_label": "Viewport status",
            "anim_timeline": "Animation timeline",
        }
        for attribute, accessible_name in explicit_names.items():
            control = getattr(self, attribute, None)
            if control is not None:
                control.setAccessibleName(accessible_name)
        for control in self.findChildren(QWidget):
            if not control.accessibleName():
                text_method = getattr(control, "text", None)
                label = str(text_method() if callable(text_method) else "").replace("&", "").strip()
                if label:
                    control.setAccessibleName(label)
            if not control.accessibleDescription() and control.toolTip():
                control.setAccessibleDescription(control.toolTip())
        self.gizmo_mode_combo.setAccessibleDescription(
            "Choose object, paint, transform, vertex, edge, or face interaction. Keyboard shortcuts are Q, P, W, E, R, F8, F9, and F10."
        )
        tab_controls = [
            getattr(self, name, None) for name in (
                "scene_menu_btn", "dcc_scene_provider_combo", "viewer_coord_combo",
                "live_dcc_refresh_btn", "cache_timeline_btn", "camera_authority_combo",
                "use_selected_camera_btn", "drive_camera_btn", "drive_time_btn",
                "gizmo_mode_combo", "medium_combo", "paint_target_combo", "canvas", "anim_timeline",
            )
        ]
        tab_controls = [control for control in tab_controls if isinstance(control, QWidget)]
        for first, second in zip(tab_controls, tab_controls[1:]):
            QWidget.setTabOrder(first, second)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        splitter = getattr(self, "scene_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        left_panel = getattr(self, "scene_left_panel", None)
        if event.size().width() < 760 and left_panel is not None and not left_panel.isHidden():
            self._compact_scene_panel_auto = True
            left_panel.hide()
        elif event.size().width() >= 760 and self._compact_scene_panel_auto:
            self._compact_scene_panel_auto = False
            if left_panel is not None:
                left_panel.show()
            splitter.setSizes([260, max(1, event.size().width() - 260)])

    def pick_primary_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.primary_color, self, "Select 3D Paint Color")
        if c.isValid():
            self.apply_primary_color(c)

    def apply_primary_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.primary_color = QColor(color)
        if getattr(self, "active_brush_name", "") != "Eraser":
            self._last_paint_color = QColor(color)
            self.color_btn.setText("Color")
            self.color_btn.setStyleSheet(f"background-color: {color.name()}; color: #000000; font-weight: bold;")
        self.canvas.update()

    def start_desktop_color_pick(self) -> None:
        if getattr(self, "_desktop_color_sampler", None) is not None:
            self._desktop_color_sampler.close()
        sampler = DesktopColorSamplerOverlay(None)
        sampler.color_picked.connect(self.on_desktop_color_picked)
        sampler.canceled.connect(lambda: self.viewport_status_label.setText("Screen color pick canceled."))
        self._desktop_color_sampler = sampler
        self.viewport_status_label.setText("Pick a color from anywhere on screen.")
        sampler.show()
        sampler.activateWindow()
        sampler.raise_()

    def on_desktop_color_picked(self, color: QColor) -> None:
        self.apply_primary_color(color)
        self.viewport_status_label.setText(f"Picked screen color {color.name().upper()}.")

    def open_rigging_workspace(self) -> None:
        try:
            from maya_tools.Rigging.mocap.hik_ui import launch_hik_ui

            def selected_rig_nodes() -> list[str]:
                tree = getattr(self, "scene_outliner", None)
                items = list(tree.selectedItems()) if tree is not None else []
                current = tree.currentItem() if tree is not None else None
                if current in items:
                    items = [item for item in items if item is not current] + [current]
                selected_ids = []
                for item in items:
                    data = item.data(0, Qt.UserRole) or {}
                    kind = str(data.get("kind") or "")
                    if kind == "rig_joint":
                        value = data.get("joint_id")
                    elif kind == "rig_node":
                        value = data.get("node_id")
                    elif kind == "object":
                        proxy = data.get("proxy") or {}
                        getter = proxy.get if hasattr(proxy, "get") else lambda key, default=None: getattr(proxy, key, default)
                        value = getter("native_id", "") or getter("mesh_id", "") or getter("key", "") or getter("name", "")
                    else:
                        value = ""
                    if value and str(value) not in selected_ids:
                        selected_ids.append(str(value))
                return selected_ids

            self._rigging_workspace_window = launch_hik_ui(
                parent=self,
                graph=self.editable_rig_graph,
                selection_provider=selected_rig_nodes,
                undo_callback=self.push_rig_undo_state,
                refresh_callback=self.refresh_scene_outliner,
            )
        except Exception as exc:
            QMessageBox.warning(self, "HIK & Rig Builder unavailable", str(exc))

    def _active_scene_command_target_payload(self, *, component_type: str = "object") -> dict[str, Any]:
        selected = getattr(self, "_selected_scene_proxy", None)
        if selected is not None:
            getter = selected.get if hasattr(selected, "get") else lambda key, default=None: getattr(selected, key, default)
            return {
                "provider": str(getter("provider_id", getter("provider", "tech_connector")) or "tech_connector"),
                "native_id": str(getter("native_id", getter("name", "")) or ""),
                "source_key": str(getter("source_key", "") or ""),
                "object_type": str(getter("object_type", getter("type", "mesh")) or "mesh"),
                "component_type": component_type,
                "components": (),
                "metadata": {
                    "name": str(getter("name", "") or getter("native_id", "")),
                    "representation": str(getter("representation", "") or ""),
                },
            }
        mesh_name = str(getattr(getattr(self, "mesh", None), "name", "") or "TC_Local_Mesh")
        return {
            "provider": "tech_connector",
            "native_id": mesh_name,
            "source_key": f"tech_connector:{mesh_name}",
            "object_type": "mesh",
            "component_type": component_type,
            "components": (),
            "metadata": {"name": mesh_name, "representation": "local_mesh"},
        }

    @staticmethod
    def _parse_component_index_text(text: str) -> set[int]:
        result: set[int] = set()
        for raw_token in str(text or "").replace(" ", "").split(","):
            token = raw_token.strip()
            if not token:
                continue
            if "-" in token:
                first_text, last_text = token.split("-", 1)
                first, last = int(first_text), int(last_text)
                result.update(range(min(first, last), max(first, last) + 1))
            else:
                result.add(int(token))
        return result

    def prompt_mesh_face_selection(self) -> None:
        current = ",".join(str(value) for value in sorted(self.selected_mesh_face_indices))
        text, ok = QInputDialog.getText(self, "Select Faces", "Face indices (commas and ranges):", text=current)
        if not ok:
            return
        try:
            selected = self._parse_component_index_text(text)
            face_count = len(self._canonical_mesh_topology()[0].faces)
            if selected and max(selected) >= face_count:
                raise IndexError(f"Face index must be below {face_count}.")
            self.selected_mesh_face_indices = selected
            self._resolved_shaded_status = f"Selected {len(selected)} mesh face(s)."
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Face Selection Failed", str(exc))

    def _project_mesh_component_data(self):
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        width = float(max(1, self.canvas.width()))
        height = float(max(1, self.canvas.height()))
        cache_key = (
            id(self.mesh), id(self.mesh.vertices), id(self.mesh.faces),
            id(getattr(self.mesh, "quad_faces", None)), len(self.mesh.vertices), len(self.mesh.faces),
            len(getattr(self.mesh, "quad_faces", ()) or ()), int(getattr(self, "_paint_geometry_revision", 0)),
            int(width), int(height), tuple(camera.eye), tuple(camera.target), tuple(camera.up),
            float(camera.fov_degrees), str(getattr(self, "viewer_coord_space", "")),
        )
        cached = getattr(self, "_component_projection_cache", None)
        if cache_key == getattr(self, "_component_projection_cache_key", None) and cached is not None:
            return cached
        topology, _colors, _proxies = self._canonical_mesh_topology()
        forward = camera.view_axes()[0]
        raycast_vertices: list[tuple[float, ...]] = []
        projected_vertices: list[tuple[float, float, float]] = []
        for vertex in topology.vertices:
            display_point = self.shared_local_to_display_local(tuple(vertex))
            screen_x, screen_y, projected_depth = camera.project_world_to_screen(display_point, width, height)
            raw_depth = _vec_dot(_vec_sub(display_point, camera.eye), forward)
            raycast_vertices.append((screen_x, screen_y, projected_depth, *display_point, 0.0, 0.0))
            projected_vertices.append((screen_x, screen_y, raw_depth))
        result = (topology, raycast_vertices, projected_vertices, camera)
        self._component_projection_cache_key = cache_key
        self._component_projection_cache = result
        return result

    def _component_selection_for_mode(self, mode: str) -> set:
        if mode != "Vertex":
            self.selected_mesh_vertex_indices.clear()
        if mode != "Edge":
            self.selected_mesh_edges.clear()
        if mode != "Face":
            self.selected_mesh_face_indices.clear()
        if mode == "Vertex":
            return self.selected_mesh_vertex_indices
        if mode == "Edge":
            return self.selected_mesh_edges
        return self.selected_mesh_face_indices

    def select_mesh_component_at_viewport_position(self, position: QPointF, mode: str, modifiers: Any = Qt.NoModifier) -> Any:
        """Select a visible mesh vertex, edge, or polygon from a viewport click."""
        topology, raycast_vertices, projected_vertices, camera = self._project_mesh_component_data()

        selected_component: Any = None
        if mode == "Vertex":
            selected_component = nearest_vertex_index(
                projected_vertices, position.x(), position.y(), near_clip=camera.near_clip,
            )
        elif mode == "Edge":
            selected_component = nearest_edge(
                projected_vertices,
                unique_polygon_edges(topology.faces),
                position.x(),
                position.y(),
                near_clip=camera.near_clip,
            )
        else:
            triangles: list[tuple[int, int, int]] = []
            triangle_to_face: list[int] = []
            for face_index, face in enumerate(topology.faces):
                for offset in range(1, len(face) - 1):
                    triangles.append((int(face[0]), int(face[offset]), int(face[offset + 1])))
                    triangle_to_face.append(face_index)
            triangle_index = _ProjectedMeshRaycaster(raycast_vertices, triangles).face_indices_at(
                [(position.x(), position.y())], tolerance=0.02,
            )[0]
            if triangle_index is not None:
                selected_component = triangle_to_face[triangle_index]

        selection = self._component_selection_for_mode(mode)
        update_selection(
            selection,
            () if selected_component is None else (selected_component,),
            shift=bool(modifiers & Qt.ShiftModifier),
            control=bool(modifiers & Qt.ControlModifier),
        )

        component_name = mode.casefold()
        self._resolved_shaded_status = f"Selected {len(selection)} mesh {component_name}{'' if len(selection) == 1 else 's'}."
        self.update_viewport_status()
        self.canvas.update()
        return selected_component

    def select_mesh_components_in_viewport_rectangle(
        self, start: QPointF, end: QPointF, mode: str, modifiers: Any = Qt.NoModifier,
    ) -> set:
        topology, _raycast_vertices, projected_vertices, camera = self._project_mesh_component_data()
        bounds = (start.x(), start.y(), end.x(), end.y())
        if mode == "Vertex":
            hits = vertices_in_rectangle(projected_vertices, *bounds, near_clip=camera.near_clip)
        elif mode == "Edge":
            hits = edges_in_rectangle(
                projected_vertices, unique_polygon_edges(topology.faces), *bounds, near_clip=camera.near_clip,
            )
        else:
            hits = faces_in_rectangle(
                projected_vertices, topology.faces, *bounds, near_clip=camera.near_clip,
            )
        selection = self._component_selection_for_mode(mode)
        update_selection(
            selection,
            hits,
            shift=bool(modifiers & Qt.ShiftModifier),
            control=bool(modifiers & Qt.ControlModifier),
        )
        self._resolved_shaded_status = f"Marquee selected {len(selection)} mesh {mode.casefold()}{'' if len(selection) == 1 else 's'}."
        self.update_viewport_status()
        self.canvas.update()
        return set(selection)

    def clear_mesh_component_selection(self) -> None:
        self.selected_mesh_vertex_indices.clear()
        self.selected_mesh_edges.clear()
        self.selected_mesh_face_indices.clear()
        self._resolved_shaded_status = "Mesh component selection cleared."
        self.update_viewport_status()
        self.canvas.update()

    def select_all_mesh_components(self, mode: str) -> set:
        topology, _colors, _proxies = self._canonical_mesh_topology()
        selection = self._component_selection_for_mode(mode)
        if mode == "Vertex":
            selection.update(range(len(topology.vertices)))
        elif mode == "Edge":
            selection.update(unique_polygon_edges(topology.faces))
        else:
            selection.update(range(len(topology.faces)))
        self._resolved_shaded_status = f"Selected all {len(selection)} mesh {mode.casefold()} components."
        self.update_viewport_status()
        self.canvas.update()
        return set(selection)

    def prompt_mesh_vertex_selection(self) -> None:
        current = ",".join(str(value) for value in sorted(self.selected_mesh_vertex_indices))
        text, ok = QInputDialog.getText(self, "Select Vertices", "Vertex indices (commas and ranges):", text=current)
        if not ok:
            return
        try:
            selected = self._parse_component_index_text(text)
            if selected and max(selected) >= len(self.mesh.vertices):
                raise IndexError(f"Vertex index must be below {len(self.mesh.vertices)}.")
            self.selected_mesh_vertex_indices = selected
            self._resolved_shaded_status = f"Selected {len(selected)} mesh vertex/vertices."
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Vertex Selection Failed", str(exc))

    def prompt_mesh_edge_selection(self) -> None:
        current = ", ".join(f"{first}-{second}" for first, second in sorted(self.selected_mesh_edges))
        text, ok = QInputDialog.getText(
            self,
            "Select Edges",
            "Vertex pairs (for example 0-1, 4-5):",
            text=current,
        )
        if not ok:
            return
        try:
            selected: set[tuple[int, int]] = set()
            for token in str(text).replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                values = token.split("-")
                if len(values) != 2:
                    raise ValueError(f"Invalid edge pair: {token}")
                edge = tuple(sorted((int(values[0]), int(values[1]))))
                if edge[0] == edge[1] or edge[0] < 0 or edge[1] >= len(self.mesh.vertices):
                    raise IndexError(f"Invalid mesh edge: {token}")
                selected.add(edge)
            self.selected_mesh_edges = selected
            self._resolved_shaded_status = f"Selected {len(selected)} mesh edge(s)."
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Edge Selection Failed", str(exc))

    def prompt_split_selected_edge_loop(self) -> None:
        if len(self.selected_mesh_edges) != 1:
            QMessageBox.warning(self, "Insert Edge Loop", "Select exactly one seed edge first.")
            return
        divisions, ok = QInputDialog.getInt(self, "Insert Edge Loop", "Cuts:", 1, 1, 64, 1)
        if ok:
            self.run_modeling_command_from_ui(
                "modeling.split_edge_loop",
                {"edge": list(next(iter(self.selected_mesh_edges))), "divisions": int(divisions)},
            )

    def prompt_bevel_selected_edges(self) -> None:
        if not self.selected_mesh_edges:
            QMessageBox.warning(self, "Bevel Edges", "Select one or more edges first.")
            return
        width, ok = QInputDialog.getDouble(self, "Bevel Edges", "Width:", 0.1, 0.000001, 100000.0, 5)
        if ok:
            self.run_modeling_command_from_ui(
                "modeling.bevel_edges",
                {"edges": [list(edge) for edge in sorted(self.selected_mesh_edges)], "width": float(width)},
            )

    def prompt_generate_mesh_lods(self) -> None:
        native_model = getattr(self, "_native_scene_model", None)
        source_path = str(getattr(native_model, "source_path", "") or "")
        if not source_path or not Path(source_path).is_file():
            QMessageBox.warning(
                self,
                "Generate Mesh LODs",
                "Import a saved FBX, glTF, USD, Alembic, OBJ, or STL scene before generating LODs.",
            )
            return
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Mesh LOD Output Folder",
            str(Path(source_path).parent / (Path(source_path).stem + "_LODs")),
            options=QFileDialog.DontUseNativeDialog,
        )
        if not output_dir:
            return
        try:
            result = self.execute_adaptive_scene_command(
                "engine.generate_mesh_lods",
                {"source_path": source_path, "output_dir": output_dir, "force_local": True},
            )
            self._resolved_shaded_status = str(result.get("message") or "Generating mesh LODs.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Generate Mesh LODs", str(exc))

    def prompt_compile_runtime_geometry(self, kind: str) -> None:
        is_point = str(kind) == "point"
        suffix = ".tcsurfels" if is_point else ".tcvmesh"
        title = "Compile Point Runtime Proxy" if is_point else "Compile Virtualized Hard Surface"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            title,
            str(Path.home() / f"{getattr(self.mesh, 'name', 'mesh')}{suffix}"),
            f"Tech Connector Runtime Geometry (*{suffix})",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        command = "engine.compile_point_runtime_proxy" if is_point else "engine.compile_virtualized_hard_surface"
        try:
            result = self.execute_adaptive_scene_command(command, {"output_path": path, "force_local": True})
            self._resolved_shaded_status = str(result.get("message") or f"Compiling {kind} runtime geometry.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, title, str(exc))

    def prompt_extrude_selected_faces(self, *, all_faces: bool = False) -> None:
        distance, ok = QInputDialog.getDouble(self, "Extrude Faces", "Distance:", 0.1, -100000.0, 100000.0, 4)
        if ok:
            self.run_modeling_command_from_ui(
                "modeling.extrude_faces",
                {"distance": float(distance), "all_faces": bool(all_faces)},
            )

    def run_modeling_command_from_ui(self, command: str, payload: dict[str, Any] | None = None) -> None:
        try:
            result = self.execute_adaptive_scene_command(command, dict(payload or {}))
            self._resolved_shaded_status = str(result.get("message") or f"Executed {command}.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Modeling Command Failed", str(exc))

    def prompt_create_animation_take(self) -> None:
        name, ok = QInputDialog.getText(self, "Create Animation Take", "Take name:", text="Take 001")
        if not ok or not str(name).strip():
            return
        try:
            result = self.execute_adaptive_scene_command(
                "animation.create_take",
                {
                    "name": str(name).strip(),
                    "start_frame": int(getattr(self, "_dcc_timeline_frame_start", 1)),
                    "end_frame": int(getattr(self, "_dcc_timeline_frame_end", 120)),
                    "force_local": True,
                },
            )
            self._resolved_shaded_status = str(result.get("message") or "Animation take created.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Create Animation Take Failed", str(exc))

    def _load_auto_key_enabled(self) -> bool:
        try:
            from tech_connector.services.settings_service import load_settings

            return bool(load_settings().get("scene_viewer_auto_key_enabled", False))
        except Exception:
            return False

    def set_auto_key_enabled(self, enabled: bool) -> None:
        self.auto_key_enabled = bool(enabled)
        try:
            from tech_connector.services.settings_service import load_settings, save_settings

            settings = load_settings()
            settings["scene_viewer_auto_key_enabled"] = self.auto_key_enabled
            save_settings(settings)
        except Exception:
            LOGGER.warning("Could not persist the Auto Key preference.", exc_info=True)
        action = getattr(self, "auto_key_action", None)
        if action is not None and action.isChecked() != self.auto_key_enabled:
            action.blockSignals(True)
            action.setChecked(self.auto_key_enabled)
            action.blockSignals(False)
        self._resolved_shaded_status = f"Auto Key {'enabled' if self.auto_key_enabled else 'disabled'}."
        if getattr(self, "viewport_status_label", None) is not None:
            self.update_viewport_status()

    def auto_key_committed_transform(
        self,
        proxy: SceneProxyInstance | dict[str, Any],
        channel_group: str,
    ) -> tuple[bool, str]:
        if not self.auto_key_enabled:
            return False, "Auto Key is disabled."
        provider = str(proxy.get("provider_id") or "")
        native_id = str(proxy.get("native_id") or "")
        frame = int(getattr(self, "_current_dcc_frame", 1))
        group = str(channel_group or "translate").strip().lower()
        if group == "translation":
            group = "translate"
        try:
            node_id = native_id if native_id in self.editable_rig_graph.nodes else ""
            selected_rig_node = str(getattr(self, "_selected_rig_node_id", "") or "")
            if not node_id and selected_rig_node in self.editable_rig_graph.nodes:
                node_id = selected_rig_node
            if node_id and dcc_provider_base_key(provider) in {"native_fbx", "tech_connector", "tc", "local"}:
                return self._auto_key_local_node(proxy, node_id, group, frame)
            return self._auto_key_bridge_target(provider, native_id, group, frame)
        except Exception as exc:
            self._resolved_shaded_status = f"Transform committed; Auto Key failed: {exc}"
            self.update_viewport_status()
            return False, str(exc)

    def _auto_key_local_node(
        self,
        proxy: SceneProxyInstance | dict[str, Any],
        node_id: str,
        channel_group: str,
        frame: int,
    ) -> tuple[bool, str]:
        from tech_connector.game_engine.authoring.tc_animation_take_service import create_take, set_keyframe

        take_id = str(self.active_animation_take_id or "")
        if take_id not in self.editable_rig_graph.animation:
            take_id = create_take(
                self.editable_rig_graph,
                "Take 001",
                start_frame=int(getattr(self, "_dcc_timeline_frame_start", 1)),
                end_frame=int(getattr(self, "_dcc_timeline_frame_end", 120)),
            )
            self.active_animation_take_id = take_id
        transform = dict(proxy.get("local_transform") or proxy.get("source_transform") or {})
        source_key = {"translate": "translation", "rotate": "rotation", "scale": "scale"}[channel_group]
        default = (1.0, 1.0, 1.0) if channel_group == "scale" else (0.0, 0.0, 0.0)
        values = transform.get(source_key, default)
        if not isinstance(values, (list, tuple)) or len(values) < 3:
            values = default
        take = self.editable_rig_graph.animation[take_id]
        layer = str(take.get("active_layer") or "BaseAnimation")
        for axis, value in zip("XYZ", values[:3]):
            set_keyframe(
                self.editable_rig_graph,
                take_id,
                node_id,
                channel_group + axis,
                frame,
                float(value),
                layer=layer,
                interpolation="auto",
            )
        self.refresh_scene_outliner()
        message = f"Auto Key: {node_id}.{channel_group} on frame {frame}."
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return True, message

    def _auto_key_bridge_target(
        self,
        provider: str,
        native_id: str,
        channel_group: str,
        frame: int,
    ) -> tuple[bool, str]:
        provider_base = dcc_provider_base_key(provider)
        if not native_id:
            raise ValueError("The selected bridge target has no native ID.")
        if provider_base == "maya":
            attributes = [channel_group + axis for axis in "XYZ"]
            code = (
                "import maya.cmds as cmds\n"
                f"target = {native_id!r}\n"
                "if not cmds.objExists(target):\n"
                "    raise RuntimeError('Object does not exist: ' + target)\n"
                f"cmds.setKeyframe(target, attribute={attributes!r}, time={int(frame)})\n"
            )
        elif provider_base == "blender":
            data_path = {"translate": "location", "rotate": "rotation_euler", "scale": "scale"}[channel_group]
            code = (
                "import bpy\n"
                f"target = bpy.data.objects.get({native_id!r})\n"
                "if target is None:\n"
                f"    raise RuntimeError('Object does not exist: ' + {native_id!r})\n"
                f"target.keyframe_insert(data_path={data_path!r}, frame={int(frame)}, group='TC Auto Key')\n"
            )
        elif provider_base == "motionbuilder":
            property_name = {"translate": "Translation", "rotate": "Rotation", "scale": "Scaling"}[channel_group]
            code = (
                "from pyfbsdk import FBFindModelByLabelName, FBTime\n"
                f"target = FBFindModelByLabelName({native_id!r})\n"
                "if target is None:\n"
                f"    raise RuntimeError('Model does not exist: ' + {native_id!r})\n"
                f"prop = target.{property_name}\n"
                "prop.SetAnimated(True)\n"
                "node = prop.GetAnimationNode()\n"
                f"time = FBTime(0, 0, 0, {int(frame)})\n"
                "for child in node.Nodes:\n"
                "    child.FCurve.KeyAdd(time, child.ReadData()[0])\n"
            )
        else:
            raise ValueError(f"Auto Key is not implemented for {provider_base.title()} bridge targets yet.")
        ok, response = self._scene_snapshot_bridge(provider).execute(code, timeout=5.0)
        if not ok:
            raise RuntimeError(str(response))
        message = f"Auto Key: {provider_base}:{native_id}.{channel_group} on frame {frame}."
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return True, message

    def prompt_add_animation_layer(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Animation Layer", "Layer name:", text="Polish")
        if not ok or not str(name).strip():
            return
        try:
            result = self.execute_adaptive_scene_command(
                "animation.add_layer",
                {"name": str(name).strip(), "take_id": self.active_animation_take_id, "force_local": True},
            )
            self._resolved_shaded_status = str(result.get("message") or "Animation layer created.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Add Animation Layer Failed", str(exc))

    def key_selected_rig_controls(self) -> None:
        try:
            selected = self.selected_local_rig_node_ids()
            if not selected:
                raise ValueError("Select one or more local joints or controls before keying.")
            result = self.execute_adaptive_scene_command(
                "animation.set_keyframe",
                {
                    "node_ids": selected,
                    "frame": int(getattr(self, "_current_dcc_frame", 1)),
                    "take_id": self.active_animation_take_id,
                    "force_local": True,
                },
            )
            self._resolved_shaded_status = str(result.get("message") or "Keyframes set.")
            self.update_viewport_status()
        except Exception as exc:
            self._resolved_shaded_status = f"Keying failed: {exc}"
            self.update_viewport_status()

    def set_viewer_visual_style(self, visual_style: str) -> dict[str, Any]:
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        world_layout = getattr(presentation, "dimensionality", "3d")
        result = self.execute_adaptive_scene_command(
            "gameplay.set_visual_style",
            {"style": str(visual_style), "world_layout": world_layout, "force_local": True},
        )
        self._sync_viewer_visual_actions()
        self._resolved_shaded_status = str(result.get("message") or "Visual style updated.")
        self.update_viewport_status()
        return result

    def set_viewer_world_layout(self, world_layout: str) -> dict[str, Any]:
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        if presentation is None:
            result = self.execute_adaptive_scene_command(
                "gameplay.set_visual_style",
                {"style": "stylized_pbr", "world_layout": str(world_layout), "force_local": True},
            )
        else:
            result = self.execute_adaptive_scene_command(
                "gameplay.update_visual_setting",
                {"setting": "world_layout", "value": str(world_layout), "force_local": True},
            )
        self._sync_viewer_visual_actions()
        self._resolved_shaded_status = str(result.get("message") or "World layout updated.")
        self.update_viewport_status()
        return result

    def update_viewer_visual_setting(self, setting: str, value: Any) -> dict[str, Any]:
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        if presentation is None:
            result = self.execute_adaptive_scene_command(
                "gameplay.set_visual_style",
                {"style": "stylized_pbr", "world_layout": "3d", str(setting): value, "force_local": True},
            )
        else:
            result = self.execute_adaptive_scene_command(
                "gameplay.update_visual_setting",
                {"setting": str(setting), "value": value, "force_local": True},
            )
        self._sync_viewer_visual_actions()
        self._resolved_shaded_status = str(result.get("message") or "Visual setting updated.")
        self.update_viewport_status()
        return result

    def explain_viewer_visual_settings(self) -> dict[str, Any]:
        if getattr(getattr(self, "game_experience_profile", None), "presentation", None) is None:
            self.set_viewer_visual_style("stylized_pbr")
        result = self.execute_adaptive_scene_command(
            "gameplay.explain_visual_settings", {"force_local": True}
        )
        self._resolved_shaded_status = str(result.get("message") or "Visual settings ready.")
        self.update_viewport_status()
        return result

    def preview_viewer_visual_plan(self) -> dict[str, Any]:
        if getattr(getattr(self, "game_experience_profile", None), "presentation", None) is None:
            self.set_viewer_visual_style("stylized_pbr")
        result = self.execute_adaptive_scene_command(
            "gameplay.preview_visual_plan",
            {"target": "desktop", "viewport_size": [max(1, self.width()), max(1, self.height())], "force_local": True},
        )
        self._resolved_shaded_status = str(result.get("message") or "Visual plan ready.")
        self.update_viewport_status()
        return result

    def _sync_viewer_visual_actions(self) -> None:
        presentation = getattr(getattr(self, "game_experience_profile", None), "presentation", None)
        action = getattr(self, "pixel_perfect_action", None)
        if action is not None:
            enabled = bool(
                presentation is not None
                and presentation.resolution.pixel_snap
                and presentation.resolution.integer_scaling
            )
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        button = getattr(self, "look_btn", None)
        if button is not None:
            from tech_connector.game_engine.authoring.presentation_profile_service import VISUAL_STYLE_LABELS

            button.setToolTip(
                "Choose visual style and world layout without changing gameplay or simulation."
                if presentation is None
                else f"{VISUAL_STYLE_LABELS.get(presentation.visual_style, presentation.visual_style)} / {presentation.dimensionality.upper()}; gameplay and simulation unchanged."
            )
        if getattr(self, "gpu_viewport", None) is not None:
            self.sync_gpu_viewport(full=False)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def execute_adaptive_scene_command(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        revision_before = self._scene_lifecycle.revision
        result = self._execute_adaptive_scene_command_impl(command, payload)
        return finalize_adaptive_command(self._scene_lifecycle, command, result, revision_before)

    def _execute_adaptive_scene_command_impl(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from tech_connector.game_engine.integration.adaptive_scene_command_service import resolve_adaptive_scene_command

        payload = dict(payload or {})
        target = self._active_scene_command_target_payload(component_type=str(payload.get("component_type") or "object"))
        if payload.pop("force_local", False):
            target.update({"provider": "tech_connector", "native_id": str(getattr(self.mesh, "name", "TC_Local_Mesh"))})
        fallback_route = {
            "command": {"key": str(command)},
            "target": dict(target),
            "host": "tech_connector",
            "execution_mode": "tc_native",
            "status": "unresolved",
            "callable": "",
            "script": "",
            "required_payload": dict(payload),
            "validation": [],
            "fallback": "Adaptive command execution is temporarily unavailable.",
            "notes": [],
        }
        route = dict(fallback_route)
        try:
            route = resolve_adaptive_scene_command(command, target, payload).to_dict()
            if route["host"] != "tech_connector":
                return {
                    **route,
                    "executed": False,
                    "message": "Command resolved to the selected bridge target; execution remains with that host bridge.",
                }
            if command in {"scene.convert_to_tc", "scene.convert_selection_to_tc"}:
                result = self._execute_tc_scene_conversion_command(command, {**route.get("required_payload", {}), **payload})
                return {**route, **result, "executed": True}
            if command in {
                "scene.compose_usd",
                "scene.inspect_usd_composition",
                "scene.set_usd_variant",
                "scene.set_usd_payload",
                "scene.set_usd_override",
            }:
                result = self._execute_tc_usd_composition_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("animation."):
                result = self._execute_tc_animation_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("simulation."):
                result = self._execute_tc_simulation_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("procedural."):
                result = self._execute_tc_procedural_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("engine."):
                result = self._execute_tc_engine_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("characters.") or str(command).startswith("narrative."):
                result = self._execute_tc_character_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("world_ai.") or str(command).startswith("gameplay."):
                result = self._execute_tc_world_intelligence_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("deformation."):
                result = self._execute_tc_deformation_command(command, payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("skinning."):
                result = self._execute_tc_skinning_command(command, payload)
                return {**route, **result, "executed": True}
            if command in {"rigging.constrain_to_mesh", "rigging.constrain_to_normal"}:
                result = self._execute_tc_surface_constraint_command(command, payload)
                return {**route, **result, "executed": True}
            if command == "rigging.create_mechanical_ik":
                result = self._execute_tc_mechanical_rig_command(payload)
                return {**route, **result, "executed": True}
            if command == "rigging.create_quadruped_leg_ik":
                result = self._execute_tc_quadruped_leg_command(payload)
                return {**route, **result, "executed": True}
            if str(command).startswith("rigging."):
                result = self._execute_tc_rigging_command(command, payload)
                return {**route, **result, "executed": True}
            if not str(command).startswith("modeling."):
                return {**route, "executed": False, "message": "This native command is routable but has no live Viewer executor yet."}
            result = self._execute_tc_modeling_command(command, payload)
            return {**route, **result, "executed": True}
        except Exception as exc:
            return {**route, "executed": False, "message": str(exc) if str(exc) else "Adaptive command failed."}

    def _execute_tc_rigging_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.integration.rigging_host_adapter_service import create_rigging_adapter
        from tech_connector.game_engine.authoring.rigging_workspace_service import RiggingWorkspaceController

        if command == "rigging.create_joint":
            name = str(payload.get("name") or payload.get("joint_name") or "Joint")
            parent_id = str(payload.get("parent_id") or payload.get("parent") or "")
            local_matrix = payload.get("local_matrix")
            self.push_rig_undo_state("Create Joint")
            try:
                joint_id = self.editable_rig_graph.add_joint(
                    name,
                    parent_id=parent_id,
                    local_matrix=list(local_matrix) if local_matrix is not None else None,
                    joint_id=str(payload.get("joint_id") or "") or None,
                )
            except Exception:
                if getattr(self, "_viewer_undo_stack", None):
                    self._viewer_undo_stack.pop()
                raise
            self.refresh_scene_outliner()
            return {"joint_id": joint_id, "created_ids": [joint_id], "message": f"Created joint {joint_id}."}

        operation_payload: dict[str, Any]
        capability: str
        if command == "rigging.parent_constraint":
            capability = "rig.create_constraint"
            drivers = payload.get("drivers") or payload.get("source_ids") or ([payload.get("driver")] if payload.get("driver") else [])
            operation_payload = {
                "type": "parent",
                "drivers": list(drivers),
                "driven": str(payload.get("driven") or payload.get("target_id") or ""),
                "axes": list(payload.get("axes") or ("x", "y", "z")),
                "offset": bool(payload.get("maintain_offset", payload.get("offset", True))),
            }
        elif command == "rigging.create_ik_handle":
            solver = str(payload.get("solver") or payload.get("solver_type") or "rp").lower()
            if solver not in {"rp", "rotate_plane", "two_bone", "ikrp"}:
                raise ValueError("TC-native adaptive IK currently requires an RP/two-bone solver; use the specialized ribbon, motion-path, or quadruped command for those solvers.")
            capability = "rig.create_ik_fk_limb"
            operation_payload = {
                "start": str(payload.get("start") or payload.get("start_joint") or ""),
                "mid": str(payload.get("mid") or payload.get("mid_joint") or ""),
                "end": str(payload.get("end") or payload.get("end_joint") or ""),
                "target": str(payload.get("target") or payload.get("target_node") or ""),
                "pole": str(payload.get("pole") or payload.get("pole_node") or ""),
                "module": str(payload.get("module") or "ik_limb"),
                "blend": float(payload.get("blend", 1.0)),
            }
        elif command == "rigging.create_ribbon_ik":
            capability = "rig.create_ribbon"
            operation_payload = {
                "joint_chain": list(payload.get("joint_chain") or payload.get("joints") or ()),
                "width": float(payload.get("width", 1.0)),
                "up_vector": list(payload.get("up_vector") or (0.0, 1.0, 0.0)),
            }
        elif command == "rigging.create_motion_path_ik":
            capability = "rig.create_motion_path"
            operation_payload = {
                "target": str(payload.get("target") or ""),
                "curve": payload.get("curve") or payload.get("control_points") or [],
                "parameter": float(payload.get("parameter", 0.0)),
                "follow": bool(payload.get("follow", True)),
                "closed": bool(payload.get("closed", False)),
            }
        elif command == "rigging.create_pose_reader":
            capability = "rig.create_pose_reader"
            operation_payload = {
                "driver": str(payload.get("driver") or ""),
                "name": str(payload.get("name") or ""),
                "axis": str(payload.get("axis") or "x"),
                "range": list(payload.get("range") or (-90.0, 90.0)),
            }
        elif command == "rigging.create_space_switch":
            capability = "rig.create_space_switch"
            operation_payload = {
                "driven": str(payload.get("driven") or ""),
                "targets": list(payload.get("targets") or ()),
                "names": list(payload.get("names") or payload.get("targets") or ()),
                "mode": str(payload.get("mode") or "parent"),
                "active": int(payload.get("active", 0)),
            }
        else:
            raise ValueError(f"No TC-native rigging executor is registered for {command}.")

        self.push_rig_undo_state(command.replace("rigging.", "").replace("_", " ").title())
        controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=self.editable_rig_graph))
        result = controller.run(capability, **operation_payload)
        if not result.ok:
            if getattr(self, "_viewer_undo_stack", None):
                self._viewer_undo_stack.pop()
            raise ValueError(result.message or "; ".join(result.warnings) or f"{command} failed.")
        self.refresh_scene_outliner()
        return {**result.to_dict(), "message": result.message or f"Executed {command}."}

    def _execute_tc_mechanical_rig_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.mechanical_rig_service import create_mechanical_rig

        self.push_rig_undo_state("Create Mechanical Rig")
        try:
            result = create_mechanical_rig(
                self.editable_rig_graph,
                mode=str(payload.get("mode") or "gear"),
                driver=str(payload.get("driver") or ""),
                driven=str(payload.get("driven") or ""),
                driver_axis=str(payload.get("driver_axis") or "y"),
                driven_axis=str(payload.get("driven_axis") or "y"),
                ratio=float(payload["ratio"]) if payload.get("ratio") is not None else None,
                module=str(payload.get("module") or "mechanical"),
                bidirectional_aim=bool(payload.get("bidirectional_aim", False)),
            )
        except Exception:
            if getattr(self, "_viewer_undo_stack", None):
                self._viewer_undo_stack.pop()
            raise
        self.refresh_scene_outliner()
        created = list(result.created_node_ids + result.created_connection_ids + result.created_constraint_ids)
        return {
            "mechanical_rig": result.to_dict(),
            "created_ids": created,
            "message": f"Created {result.mode.replace('_', ' ')} relationship from {result.driver} to {result.driven}.",
        }

    def _execute_tc_quadruped_leg_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.quadruped_leg_rig_service import create_quadruped_leg_rig

        self.push_rig_undo_state("Create Quadruped Leg IK")
        try:
            result = create_quadruped_leg_rig(
                self.editable_rig_graph,
                joint_chain=payload.get("joint_chain") or (),
                module=str(payload.get("module") or "quadruped_leg"),
                foot_control=str(payload.get("foot_control") or ""),
                pole_control=str(payload.get("pole_control") or ""),
                pole_distance=float(payload.get("pole_distance", 5.0)),
                gait_phase=float(payload.get("gait_phase", 0.0)),
                stride_scale=float(payload.get("stride_scale", 1.0)),
            )
        except Exception:
            if getattr(self, "_viewer_undo_stack", None):
                self._viewer_undo_stack.pop()
            raise
        self.refresh_scene_outliner()
        return {
            "quadruped_leg": result.to_dict(),
            "created_ids": [result.foot_control, result.pole_control, result.hock_target, *result.solver_ids],
            "message": f"Created quadruped leg {result.module} with upper and hock IK stages.",
        }

    def _execute_tc_surface_constraint_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.rig_evaluation_service import (
            calculate_constraint_offset_matrix,
            evaluate_rig_graph,
        )
        from tech_connector.game_engine.authoring.surface_attachment_service import create_surface_attachment
        from tech_connector.game_engine.deformation.skinning_tool_service import skin_topology_identity

        target_id = str(payload.get("driven") or payload.get("target_id") or getattr(self, "_selected_rig_node_id", "") or "")
        if target_id not in self.editable_rig_graph.nodes:
            raise ValueError("Select a TC rig control/joint or provide a valid driven node.")
        requested_face = payload.get("face_index")
        if requested_face is None:
            selected_faces = sorted(self.selected_mesh_face_indices)
            if len(selected_faces) != 1:
                raise ValueError("Select exactly one mesh face or provide face_index for a surface constraint.")
            requested_face = selected_faces[0]
        topology, _colors, _proxies = self._canonical_mesh_topology()
        mesh_id = str(payload.get("mesh_id") or getattr(self.mesh, "name", "mesh"))
        identity = skin_topology_identity(topology.vertices, topology.faces)
        attachment = create_surface_attachment(
            mesh_id,
            topology.vertices,
            topology.faces,
            face_index=int(requested_face),
            barycentric=payload.get("barycentric") or (1.0 / 3.0,) * 3,
            triangle_offset=int(payload.get("triangle_offset", 0)),
            topology_fingerprint=identity["fingerprint"],
        )
        kind = "normal" if command == "rigging.constrain_to_normal" else "geometry"
        settings: dict[str, Any] = {
            "attachment": attachment.to_dict(),
            "maintain_offset": bool(payload.get("maintain_offset", False)),
            "source_mesh_id": mesh_id,
        }
        if settings["maintain_offset"]:
            current = evaluate_rig_graph(self.editable_rig_graph).world_matrices.get(target_id)
            if current is None:
                raise ValueError(f"Cannot evaluate driven node {target_id} for maintain offset.")
            settings["offset_matrix"] = calculate_constraint_offset_matrix(current, list(attachment.matrix))
        self.push_rig_undo_state("Constrain To Surface Normal" if kind == "normal" else "Constrain To Mesh")
        constraint_id = self.editable_rig_graph.add_constraint(
            kind,
            [mesh_id],
            target_id,
            constraint_id=str(payload.get("constraint_id") or "") or None,
            settings=settings,
        )
        evaluated = evaluate_rig_graph(self.editable_rig_graph)
        if not evaluated.ok:
            self.editable_rig_graph.constraints.pop(constraint_id, None)
            raise ValueError("Surface constraint did not evaluate: " + "; ".join(evaluated.errors[:4]))
        self.refresh_scene_outliner()
        return {
            "constraint_id": constraint_id,
            "attachment": attachment.to_dict(),
            "world_matrix": evaluated.world_matrices.get(target_id),
            "message": f"Constrained {target_id} to {mesh_id} face {int(requested_face)} ({kind}).",
        }
