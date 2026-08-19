"""Public facade for the decomposed 3D mesh painter widget."""
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

from tech_connector.ui import three_d_mesh_painter_workers as _mesh_workers
from tech_connector.ui import three_d_mesh_painter_geometry as _mesh_geometry
from tech_connector.ui import three_d_mesh_painter_support as _mesh_support

_MESH_COMPONENT_NAMESPACE = {
    name: getattr(module, name)
    for module in (_mesh_workers, _mesh_geometry, _mesh_support)
    for name in getattr(module, '__dict__', {})
    if name in ['AnimatedFBXClipContainer', 'DCCProceduralPrimitiveFactory', 'DccCameraPossessionWorker', 'DccDeformationBindingWorker', 'DccResolvedFrameWorker', 'DccSceneImportDialog', 'DccSceneModelCompileWorker', 'DccSceneRestoreWorker', 'DccSceneSnapshotWorker', 'DccTimelineCacheWorker', 'DesktopColorSamplerOverlay', 'EffectBakeWorker', 'FBXCameraObject', 'FBXMaterialContainer', 'FBXMeshModel', 'MayaCameraMatrix', 'MayaComponentSelectionSuite', 'MayaSoftSelectionEngine', 'MayaViewportCamera', 'MeshBrushProfile', 'MeshDefaultPose', 'MeshLodGenerationWorker', 'MeshVertex3D', 'NativeFbxImportWorker', 'PerFrameSyncSketchMarkupStore', 'PortBoundDccBridge', 'RuntimeGeometryCompileWorker', 'SceneProxyInstance', 'SceneProxyMaterialBinding', 'SceneProxyMeshData', 'ShotTakeProfile', 'SkinWeightFileWorker', 'SyncSketchMarkupOverlay', 'SyncSketchMarkupStroke', 'TCSceneConversionWorker', 'ThreeDMeshCanvas', 'ThreeDMeshPaintLayer', 'ThreeDMeshPaintLayerStack', 'TimelineFrameArchive', 'TransformManipulatorGizmo', 'UsdCompositionWorker', '_ProjectedMeshRaycaster', '_brush_alpha_array', '_brush_alpha_from_image', '_load_brush_alpha_image', '_rgba_image_from_alpha', '_rotate_vec_around_axis', '_shift_alpha_array', '_stable_right_axis', '_vec_add', '_vec_cross', '_vec_dot', '_vec_length', '_vec_normalize', '_vec_scale', '_vec_sub', 'brush_alpha_at', 'build_brush_alpha_preview', 'build_brush_stamp_image', 'dcc_provider_base_key', 'extract_cameras_from_fbx', 'extract_materials_from_fbx', 'provider_view_colors', 'provider_view_to_world', 'provider_world_to_view', 'push_updated_textures_to_dcc_asset_files', 'scene_proxy_draws_filled_surface', 'scene_snapshot_bridge_for_provider']
}
for _mesh_component_module in (_mesh_workers, _mesh_geometry, _mesh_support):
    _mesh_component_module.__dict__.update(_MESH_COMPONENT_NAMESPACE)

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
    _BRUSH_ALPHA_ARRAY_CACHE,
    _BRUSH_ALPHA_IMAGE_CACHE,
    _BRUSH_ALPHA_PREVIEW_CACHE,
    _BRUSH_STAMP_IMAGE_CACHE,
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
    PROVIDER_VIEW_COLORS,
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

from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_01 import ThreeDMeshPainterViewportMixin01
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_02 import ThreeDMeshPainterViewportMixin02
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_03 import ThreeDMeshPainterViewportMixin03
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_04 import ThreeDMeshPainterViewportMixin04
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_05 import ThreeDMeshPainterViewportMixin05
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_06 import ThreeDMeshPainterViewportMixin06


class ThreeDMeshPainterViewport(ThreeDMeshPainterViewportMixin01, ThreeDMeshPainterViewportMixin02, ThreeDMeshPainterViewportMixin03, ThreeDMeshPainterViewportMixin04, ThreeDMeshPainterViewportMixin05, ThreeDMeshPainterViewportMixin06, QWidget):
    """Interactive 3D mesh paint viewport with toolbar and 360-degree orbit canvas."""
    color_hovered = Signal(int, int, QColor)
