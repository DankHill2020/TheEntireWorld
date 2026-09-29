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
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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


class ThreeDMeshPainterViewportMixin04:
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
            if bool(proxy.get("deleted", False)):
                continue
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
            proxy_items: list[tuple[SceneProxyInstance | dict[str, Any], QTreeWidgetItem]] = []
            for proxy in proxies_by_provider.get(provider, []):
                name = str(proxy.get("name") or proxy.get("native_id") or "object")
                representation = str(proxy.get("representation") or "")
                is_visible = bool(proxy.get("visible", True))
                state = str(proxy.get("sync_state") or representation or "clean")
                if not is_visible:
                    state = "hidden"
                item = QTreeWidgetItem([name, str(proxy.get("type") or "object"), state])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if is_visible else Qt.Unchecked)
                item.setData(0, Qt.UserRole, {"kind": "object", "provider": provider, "native_id": proxy.get("native_id"), "proxy": proxy})
                item.setForeground(0, proxy.get("wire_color") or provider_view_colors(provider)[1])
                item.setToolTip(0, str(proxy.get("native_id") or name))
                proxy_items.append((proxy, item))
            if provider == "tech_connector":
                entity_by_id = {str(entity.get("entity_id") or ""): entity for entity in getattr(self, "_runtime_world_state", {}).get("entities") or () if isinstance(entity, dict)}
                item_by_id = {str(proxy.get("entity_id") or proxy.get("native_id") or ""): item for proxy, item in proxy_items}
                folder_items: dict[str, QTreeWidgetItem] = {}
                for folder in sorted(set(getattr(self, "_runtime_world_state", {}).get("editor_folders") or ()) | {str(entity.get("editor_folder") or "") for entity in entity_by_id.values()} - {""}):
                    folder_item = QTreeWidgetItem([folder, "folder", ""]); folder_item.setData(0, Qt.UserRole, {"kind": "actor_folder", "folder": folder}); objects_parent.addChild(folder_item); folder_items[folder] = folder_item
                for proxy, item in proxy_items:
                    entity_id = str(proxy.get("entity_id") or proxy.get("native_id") or ""); entity = entity_by_id.get(entity_id, {}); parent_id = str(entity.get("parent_entity_id") or ""); folder = str(entity.get("editor_folder") or "")
                    parent_item = item_by_id.get(parent_id) or folder_items.get(folder) or objects_parent; parent_item.addChild(item)
                for folder_item in folder_items.values(): folder_item.setExpanded(True)
            else:
                for _proxy, item in proxy_items: objects_parent.addChild(item)

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

        rig_graph = getattr(self, "editable_rig_graph", None)
        if isinstance(rig_graph, EditableRigGraph) and (
            rig_graph.nodes or rig_graph.connections or rig_graph.joints or rig_graph.skins
            or rig_graph.constraints or rig_graph.deformers
        ):
            rig_item = QTreeWidgetItem([
                "Editable Rig",
                "rig",
                (
                    f"{len(rig_graph.nodes)} nodes / {len(rig_graph.connections)} links"
                    if rig_graph.nodes
                    else f"{len(rig_graph.joints)} joints / {len(rig_graph.skins)} skins"
                ),
            ])
            rig_item.setData(0, Qt.UserRole, {"kind": "rig_root"})
            rig_item.setForeground(0, QColor(255, 225, 105))
            tree.addTopLevelItem(rig_item)
            hierarchy_parent: QTreeWidgetItem
            if rig_graph.nodes:
                dag_source_types = {
                    "transform", "joint", "mesh", "nurbsCurve", "nurbsSurface", "locator",
                    "ikHandle", "ikEffector",
                }
                dag_nodes = {
                    node_id: node
                    for node_id, node in rig_graph.nodes.items()
                    if str(node.get("native_id") or "").startswith("|")
                    or bool(node.get("dag_parent_id"))
                    or str(node.get("source_type") or "") in dag_source_types
                }
                hierarchy_parent = QTreeWidgetItem(["Hierarchy", "DAG", str(len(dag_nodes))])
                rig_item.addChild(hierarchy_parent)
                children_by_parent: dict[str, list[str]] = {}
                for node_id, node in dag_nodes.items():
                    parent_id = str(node.get("dag_parent_id") or "")
                    children_by_parent.setdefault(parent_id if parent_id in dag_nodes else "", []).append(node_id)

                def node_sort_key(node_id: str) -> tuple[int, str]:
                    node = dag_nodes.get(node_id) or {}
                    return int(node.get("source_order", 0) or 0), str(node.get("name") or node_id).lower()

                def add_dag_item(parent_item: QTreeWidgetItem, node_id: str, ancestry: set[str]) -> None:
                    if node_id in ancestry:
                        return
                    node = dag_nodes.get(node_id) or {}
                    node_type = str(node.get("node_type") or node.get("source_type") or "node")
                    state = str(node.get("evaluation_mode") or "source_proxy").replace("_", " ")
                    item = QTreeWidgetItem([str(node.get("name") or node_id), node_type, state])
                    item.setData(0, Qt.UserRole, {"kind": "rig_node", "node_id": node_id})
                    item.setToolTip(
                        0,
                        f"{str(node.get('native_id') or node_id)}\n{node_type} from {str(node.get('source_type') or 'unknown')}",
                    )
                    item.setForeground(0, QColor(125, 205, 255) if node.get("ownership") == "linked" else QColor(245, 215, 100))
                    parent_item.addChild(item)
                    for child_id in sorted(children_by_parent.get(node_id, []), key=node_sort_key):
                        add_dag_item(item, child_id, ancestry | {node_id})

                for root_id in sorted(children_by_parent.get("", []), key=node_sort_key):
                    add_dag_item(hierarchy_parent, root_id, set())

                dependency_nodes = [(node_id, node) for node_id, node in rig_graph.nodes.items() if node_id not in dag_nodes]
                dependency_parent = QTreeWidgetItem(["Dependency Nodes", "DG", str(len(dependency_nodes))])
                rig_item.addChild(dependency_parent)
                for node_id, node in sorted(
                    dependency_nodes,
                    key=lambda pair: (str(pair[1].get("node_type") or ""), str(pair[1].get("name") or pair[0]).lower()),
                )[:1000]:
                    state = "portable / proxied" if node.get("portable") else "source only"
                    item = QTreeWidgetItem([
                        str(node.get("name") or node_id),
                        str(node.get("node_type") or "source.opaque"),
                        state,
                    ])
                    item.setData(0, Qt.UserRole, {"kind": "rig_node", "node_id": node_id})
                    item.setToolTip(0, str(node.get("native_id") or node_id))
                    dependency_parent.addChild(item)
                if len(dependency_nodes) > 1000:
                    dependency_parent.addChild(QTreeWidgetItem([
                        f"{len(dependency_nodes) - 1000} more nodes",
                        "bounded view",
                        "stored in scene",
                    ]))

                connections_parent = QTreeWidgetItem(["Connections", "plugs", str(len(rig_graph.connections))])
                rig_item.addChild(connections_parent)
                connections_by_type: dict[str, list[dict[str, Any]]] = {}
                for connection in rig_graph.connections.values():
                    connections_by_type.setdefault(str(connection.get("connection_type") or "attribute"), []).append(connection)
                shown_connections = 0
                for connection_type, connections in sorted(connections_by_type.items()):
                    type_parent = QTreeWidgetItem([connection_type.title(), "connection", str(len(connections))])
                    connections_parent.addChild(type_parent)
                    for connection in connections:
                        if shown_connections >= 500:
                            break
                        source_node = rig_graph.nodes.get(str(connection.get("source_node") or ""), {})
                        target_node = rig_graph.nodes.get(str(connection.get("target_node") or ""), {})
                        source_label = str(source_node.get("name") or connection.get("source_node") or "?")
                        target_label = str(target_node.get("name") or connection.get("target_node") or "?")
                        item = QTreeWidgetItem([
                            f"{source_label}.{connection.get('source_attribute')}",
                            "->",
                            f"{target_label}.{connection.get('target_attribute')}",
                        ])
                        item.setData(0, Qt.UserRole, {"kind": "rig_connection", "connection_id": connection.get("id")})
                        type_parent.addChild(item)
                        shown_connections += 1
                if len(rig_graph.connections) > shown_connections:
                    connections_parent.addChild(QTreeWidgetItem([
                        f"{len(rig_graph.connections) - shown_connections} more connections",
                        "bounded view",
                        "stored in scene",
                    ]))
            else:
                hierarchy_parent = QTreeWidgetItem(["Joints", "group", str(len(rig_graph.joints))])
                rig_item.addChild(hierarchy_parent)
                children_by_parent: dict[str, list[str]] = {}
                for joint_id, joint in rig_graph.joints.items():
                    children_by_parent.setdefault(str(joint.get("parent_id") or ""), []).append(joint_id)

                def add_joint_item(parent_item: QTreeWidgetItem, joint_id: str, ancestry: set[str]) -> None:
                    if joint_id in ancestry:
                        return
                    joint = rig_graph.joints.get(joint_id) or {}
                    policy = rig_graph.joint_edit_policy(joint_id)
                    item = QTreeWidgetItem([
                        str(joint.get("name") or joint_id),
                        "joint",
                        "linked" if policy == "source_driven" else "native",
                    ])
                    item.setData(0, Qt.UserRole, {"kind": "rig_joint", "joint_id": joint_id})
                    item.setToolTip(0, joint_id)
                    parent_item.addChild(item)
                    for child_id in sorted(
                        children_by_parent.get(joint_id, []),
                        key=lambda key: (
                            int(rig_graph.joints[key].get("source_order", 0) or 0),
                            str(rig_graph.joints[key].get("name") or key).lower(),
                        ),
                    ):
                        add_joint_item(item, child_id, ancestry | {joint_id})

                for root_id in sorted(
                    children_by_parent.get("", []),
                    key=lambda key: (
                        int(rig_graph.joints[key].get("source_order", 0) or 0),
                        str(rig_graph.joints[key].get("name") or key).lower(),
                    ),
                ):
                    add_joint_item(hierarchy_parent, root_id, set())
            skins_parent = QTreeWidgetItem(["Skins", "group", str(len(rig_graph.skins))])
            rig_item.addChild(skins_parent)
            for skin_id, skin in sorted(rig_graph.skins.items()):
                item = QTreeWidgetItem([
                    str(skin.get("mesh_id") or skin_id).split("::")[-1],
                    "skin",
                    str(skin.get("runtime_mode") or "editable"),
                ])
                item.setData(0, Qt.UserRole, {"kind": "rig_skin", "skin_id": skin_id})
                item.setToolTip(0, skin_id)
                skins_parent.addChild(item)
            constraints_parent = QTreeWidgetItem(["Constraints", "group", str(len(rig_graph.constraints))])
            rig_item.addChild(constraints_parent)

            def rig_node_label(node_id: str) -> str:
                node = rig_graph.nodes.get(str(node_id)) or rig_graph.joints.get(str(node_id)) or {}
                return str(node.get("name") or node_id).split("::")[-1]

            for constraint_id, constraint in sorted(rig_graph.constraints.items()):
                source_ids = [str(value) for value in constraint.get("source_ids") or []]
                source_labels = [rig_node_label(value) for value in source_ids]
                compact_sources = ", ".join(source_labels[:2])
                if len(source_labels) > 2:
                    compact_sources += f" +{len(source_labels) - 2}"
                target_label = rig_node_label(str(constraint.get("target_id") or "target"))
                kind_label = str(constraint.get("type") or "constraint").title()
                settings = dict(constraint.get("settings") or {})
                item = QTreeWidgetItem([
                    f"{kind_label}: {compact_sources or 'source'} -> {target_label}",
                    "constraint",
                    "enabled" if constraint.get("enabled", True) else "muted",
                ])
                item.setData(0, Qt.UserRole, {"kind": "rig_constraint", "constraint_id": constraint_id})
                item.setToolTip(
                    0,
                    "\n".join((
                        f"ID: {constraint_id}",
                        f"Drivers: {', '.join(source_labels) or 'none'}",
                        f"Driven: {target_label}",
                        f"Axes: {''.join(settings.get('axes') or ('x', 'y', 'z')).upper()}",
                        f"Maintain offset: {'yes' if settings.get('maintain_offset') else 'no'}",
                    )),
                )
                constraints_parent.addChild(item)
            deformers_parent = QTreeWidgetItem(["Deformers", "stack", str(len(rig_graph.deformers))])
            rig_item.addChild(deformers_parent)
            for deformer_id, deformer in sorted(
                rig_graph.deformers.items(),
                key=lambda pair: (str(pair[1].get("mesh_id") or ""), int(pair[1].get("order", 0) or 0)),
            ):
                item = QTreeWidgetItem([
                    str(deformer.get("mesh_id") or "mesh").split("::")[-1],
                    str(deformer.get("type") or "deformer").replace("_", " "),
                    str(deformer.get("evaluation_mode") or "source_proxy").replace("_", " "),
                ])
                item.setData(0, Qt.UserRole, {"kind": "rig_deformer", "deformer_id": deformer_id})
                item.setToolTip(0, deformer_id)
                deformers_parent.addChild(item)
            takes = {
                take_id: take for take_id, take in rig_graph.animation.items()
                if isinstance(take, dict) and take.get("type") == "animation_take"
            }
            takes_parent = QTreeWidgetItem(["Animation Takes", "takes", str(len(takes))])
            rig_item.addChild(takes_parent)
            for take_id, take in sorted(takes.items(), key=lambda pair: str(pair[1].get("name") or pair[0]).lower()):
                layers = dict(take.get("layers") or {})
                take_item = QTreeWidgetItem([
                    str(take.get("name") or take_id),
                    "take",
                    f"{take.get('start_frame', 1)}-{take.get('end_frame', 120)} @ {take.get('frame_rate', 24)} fps",
                ])
                take_item.setData(0, Qt.UserRole, {"kind": "animation_take", "take_id": take_id})
                take_item.setToolTip(0, f"{take_id}\nTimecode: {take.get('timecode_start') or '00:00:00:00'}")
                takes_parent.addChild(take_item)
                for layer_name, layer in layers.items():
                    key_count = sum(len(curve.get("keys") or []) for curve in (layer.get("curves") or {}).values())
                    layer_item = QTreeWidgetItem([
                        str(layer_name),
                        "animation layer",
                        f"{key_count} keys / {float(layer.get('weight', 1.0)):.2f} weight",
                    ])
                    layer_item.setData(0, Qt.UserRole, {"kind": "animation_layer", "take_id": take_id, "layer": layer_name})
                    take_item.addChild(layer_item)
            rig_item.setExpanded(True)
            hierarchy_parent.setExpanded(True)

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
        if str(proxy.get("provider_id") or "") == "tech_connector":
            entity = getattr(self, "_runtime_entity_for_proxy", lambda _proxy: None)(proxy)
            if isinstance(entity, dict): entity["visible"] = visible; self._scene_lifecycle.mark_dirty()
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
        elif kind in {"animation_take", "animation_layer"}:
            take_id = str(data.get("take_id") or "")
            if take_id in self.editable_rig_graph.animation:
                self.active_animation_take_id = take_id
                take = self.editable_rig_graph.animation[take_id]
                if kind == "animation_layer" and str(data.get("layer") or "") in (take.get("layers") or {}):
                    take["active_layer"] = str(data["layer"])
                self._resolved_shaded_status = f"Active animation take: {take.get('name') or take_id}"
                self.update_viewport_status()
        elif kind == "rig_node":
            node_id = str(data.get("node_id") or "")
            rig_graph = getattr(self, "editable_rig_graph", EditableRigGraph())
            node = (rig_graph.nodes or {}).get(node_id, {})
            source_ref = node.get("source_ref") if isinstance(node.get("source_ref"), dict) else {}
            provider = str(source_ref.get("provider_id") or "")
            native_id = str(source_ref.get("native_id") or node.get("native_id") or "")
            source_type = str(node.get("source_type") or "unknown")
            self._selected_rig_node_id = node_id
            self._selected_rig_joint_id = ""
            self._selected_scene_proxy = None
            if source_type in {"transform", "joint", "ikHandle", "ikEffector"} and provider and native_id:
                self._selected_scene_proxy = self._scene_proxy_for_rig_node(node)
            self.update_instance_details_panel()
            if getattr(self, "instance_title_label", None) is not None:
                self.instance_title_label.setText(str(node.get("name") or "Rig Node"))
                self.instance_source_label.setText(f"{provider or 'Tech Connector'}: {native_id or node_id}")
                self.instance_mesh_label.setText(
                    f"{str(node.get('node_type') or 'source.opaque')} ({source_type})"
                )
                self.instance_material_label.setText(
                    "Portable node semantics" if node.get("portable") else "Source-specific node semantics"
                )
                self.instance_texture_label.setText(
                    f"Evaluation: {str(node.get('evaluation_mode') or 'source_proxy').replace('_', ' ')}"
                )
                self.instance_context_label.setText(
                    f"{len(node.get('attribute_specs') or {})} authored attribute(s); linked edits evaluate in the source DCC."
                )
            self.update_viewport_status()
            if hasattr(self, "canvas") and self.canvas:
                self.canvas.update()
        elif kind == "rig_joint":
            joint_id = str(data.get("joint_id") or "")
            self._selected_rig_joint_id = joint_id
            rig_graph = getattr(self, "editable_rig_graph", EditableRigGraph())
            joint = (rig_graph.joints or {}).get(joint_id, {})
            policy = rig_graph.joint_edit_policy(joint_id)
            source_ref = joint.get("source_ref") if isinstance(joint.get("source_ref"), dict) else {}
            source_label = str(source_ref.get("provider_id") or "Tech Connector")
            node = (rig_graph.nodes or {}).get(joint_id, {})
            if policy == "full":
                self._selected_scene_proxy = self._scene_proxy_for_native_rig_joint(joint_id)
            else:
                self._selected_scene_proxy = self._scene_proxy_for_rig_node(node) if node else None
            self.update_instance_details_panel()
            if getattr(self, "instance_title_label", None) is not None:
                self.instance_title_label.setText(str(joint.get("name") or "Joint"))
                self.instance_source_label.setText(f"{source_label} rig joint: {joint_id}")
                self.instance_mesh_label.setText(f"Parent: {joint.get('parent_id') or 'world'}")
                self.instance_material_label.setText(
                    "Source-driven skeleton cache" if policy == "source_driven" else "Native editable skeleton"
                )
                self.instance_texture_label.setText(
                    "Transform: live source pose" if policy == "source_driven" else "Transform: editable local matrix"
                )
                self.instance_context_label.setText(
                    "Structural edits belong in the linked DCC; local constraints remain available."
                    if policy == "source_driven"
                    else "Right-click this joint for hierarchy actions."
                )
            self.update_viewport_status()

    def _scene_proxy_for_native_rig_joint(self, joint_id: str) -> dict[str, Any] | None:
        """Create a lightweight selectable joint proxy from the current local rig evaluation."""
        rig_graph = getattr(self, "editable_rig_graph", None)
        if not isinstance(rig_graph, EditableRigGraph) or joint_id not in rig_graph.joints:
            return None
        evaluated = rig_graph.evaluate_local()
        world_matrix = self._native_fbx_cached_joint_world_matrix(joint_id)
        if world_matrix is None:
            world_matrix = list(evaluated.world_matrices.get(joint_id) or [])
        local_matrix = list(evaluated.local_matrices.get(joint_id) or [])
        if len(world_matrix) != 16 or len(local_matrix) != 16:
            return None
        scene_center = tuple(getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
        scene_scale = max(1.0e-12, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        view_center = tuple(
            (float(world_matrix[index]) - float(scene_center[axis])) * scene_scale
            for axis, index in enumerate((12, 13, 14))
        )
        joint = rig_graph.joints[joint_id]
        source_transform = {
            "world_matrix": world_matrix,
            "translation": [float(local_matrix[index]) for index in (12, 13, 14)],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        }
        return {
            "provider_id": "native_fbx",
            "native_id": str(joint_id),
            "name": str(joint.get("name") or joint_id),
            "object_type": "joint",
            "representation": "joint",
            "center": view_center,
            "source_key": f"native_fbx:{joint_id}",
            "source_transform": source_transform,
            "local_transform": copy.deepcopy(source_transform),
            "sync_state": "clean",
            "visible": True,
        }

    def _native_fbx_cached_joint_world_matrix(self, joint_id: str) -> list[float] | None:
        binding = (getattr(self, "_dcc_deformation_bindings", {}) or {}).get("native_fbx")
        pose = getattr(self, "_native_fbx_current_pose", None)
        if not isinstance(binding, dict) or not isinstance(pose, dict):
            return None
        pose_by_id = {
            str(item.get("native_id") or ""): item
            for item in pose.get("skeletons") or []
            if isinstance(item, dict)
        }
        for skeleton in binding.get("skeletons") or []:
            joints = list(skeleton.get("joints") or [])
            index = next(
                (
                    joint_index
                    for joint_index, item in enumerate(joints)
                    if str(item.get("native_id") or "") == str(joint_id)
                ),
                -1,
            )
            if index < 0:
                continue
            skeleton_pose = pose_by_id.get(str(skeleton.get("native_id") or ""))
            if skeleton_pose is None:
                return None
            import numpy as np

            packed = skeleton_pose.get("joint_matrices_f32")
            offset = int(skeleton_pose.get("joint_matrix_float_offset", 0) or 0)
            try:
                values = np.frombuffer(packed, dtype=np.float32, count=len(joints) * 16, offset=offset * 4)
            except (TypeError, ValueError):
                values = np.asarray(packed, dtype=np.float32).reshape(-1)[offset : offset + len(joints) * 16]
            if len(values) != len(joints) * 16:
                return None
            return values.reshape((-1, 16))[index].astype(float).tolist()
        return None

    def _scene_proxy_for_rig_node(self, node: dict[str, Any]) -> SceneProxyInstance | dict[str, Any] | None:
        """Resolve or lazily hydrate one selectable DAG control without loading the full graph."""
        source_ref = node.get("source_ref") if isinstance(node.get("source_ref"), dict) else {}
        provider = str(source_ref.get("provider_id") or "")
        native_id = str(source_ref.get("native_id") or node.get("native_id") or "")
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if (
                str(proxy.get("provider_id") or "") == provider
                and str(proxy.get("native_id") or "") == native_id
            ):
                return proxy

        attributes = dict(node.get("attributes") or {})
        world_matrix = list(attributes.get("worldMatrix[0]") or [])
        if len(world_matrix) < 16 and dcc_provider_base_key(provider) == "maya":
            try:
                bridge = self._scene_snapshot_bridge(provider)
                code = (
                    "import json\n"
                    "import maya.cmds as cmds\n"
                    f"node = {native_id!r}\n"
                    "if not cmds.objExists(node):\n"
                    "    raise RuntimeError('Rig node does not exist: ' + node)\n"
                    "print(json.dumps({\n"
                    "    'worldMatrix[0]': [float(value) for value in cmds.xform(node, q=True, ws=True, matrix=True)],\n"
                    "    'translate': [float(value) for value in (cmds.getAttr(node + '.translate')[0])],\n"
                    "    'rotate': [float(value) for value in (cmds.getAttr(node + '.rotate')[0])],\n"
                    "    'scale': [float(value) for value in (cmds.getAttr(node + '.scale')[0])],\n"
                    "}))"
                )
                ok, raw = bridge.execute(code, timeout=3.0)
                if ok:
                    attributes.update(json.loads(str(raw or "{}")))
                    node["attributes"] = attributes
                    world_matrix = list(attributes.get("worldMatrix[0]") or [])
            except Exception:
                return None
        if len(world_matrix) < 16:
            return None

        native_center = tuple(float(world_matrix[index]) for index in (12, 13, 14))
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
        shared_center = provider_world_to_view(
            provider,
            *native_center,
            str(snapshot.get("unit_linear") or ""),
            str(snapshot.get("up_axis") or ""),
        )
        scene_center = tuple(getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))
        scene_scale = max(1.0e-12, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        view_center = tuple(
            (float(shared_center[index]) - float(scene_center[index])) * scene_scale
            for index in range(3)
        )
        source_transform = {
            "world_matrix": world_matrix,
            "translation": list(attributes.get("translate") or (0.0, 0.0, 0.0)),
            "rotation": list(attributes.get("rotate") or (0.0, 0.0, 0.0)),
            "scale": list(attributes.get("scale") or (1.0, 1.0, 1.0)),
        }
        return {
            "provider_id": provider,
            "native_id": native_id,
            "name": str(node.get("name") or native_id),
            "object_type": str(node.get("source_type") or "transform"),
            "representation": "control",
            "center": view_center,
            "source_key": f"{provider}:{native_id}",
            "source_transform": source_transform,
            "local_transform": copy.deepcopy(source_transform),
            "sync_state": "clean",
            "visible": True,
        }

    def show_scene_outliner_context_menu(self, position: QPoint) -> None:
        tree = getattr(self, "scene_outliner", None)
        if tree is None:
            return
        item = tree.itemAt(position)
        data = item.data(0, Qt.UserRole) if item is not None else {"kind": "rig_root"}
        data = data if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "")
        if kind == "object":
            proxy = data.get("proxy")
            if not isinstance(proxy, (dict, SceneProxyInstance)): return
            self._selected_scene_proxy = proxy
            menu = QMenu(tree)
            menu.addAction("Focus Selected", self.focus_selected_scene_element)
            menu.addAction("Hide" if bool(proxy.get("visible", True)) else "Show", self.toggle_selected_proxy_visibility)
            menu.addAction("Show Only Selected", self.show_only_selected_proxy)
            if str(proxy.get("provider_id") or "") == "tech_connector" and proxy.get("entity_id"):
                menu.addSeparator()
                menu.addAction("Duplicate", self.duplicate_selected_level_actor)
                def rename_actor() -> None:
                    value, accepted = QInputDialog.getText(tree, "Rename Actor", "Name", text=str(proxy.get("name") or "Actor"))
                    if accepted: self.rename_selected_level_actor(value)
                menu.addAction("Rename…", rename_actor)
                menu.addAction("Delete", self.delete_selected_level_actor)
            else:
                menu.addSeparator(); source_action = menu.addAction("Select in Source DCC", self.select_selected_proxy_in_source)
                source_action.setEnabled(dcc_provider_base_key(str(proxy.get("provider_id") or "")) in {"maya", "blender", "unreal"})
            menu.exec(tree.viewport().mapToGlobal(position))
            return
        if kind not in {"rig_root", "rig_joint", "rig_node", "rig_constraint"}:
            return
        if kind == "rig_constraint":
            constraint_id = str(data.get("constraint_id") or "")
            constraint = self.editable_rig_graph.constraints.get(constraint_id)
            if constraint is None:
                return
            menu = QMenu(tree)
            enabled = bool(constraint.get("enabled", True))
            menu.addAction(
                "Mute Constraint" if enabled else "Enable Constraint",
                lambda: self.set_local_rig_constraint_enabled(constraint_id, not enabled),
            )
            menu.addAction("Delete Constraint", lambda: self.delete_local_rig_constraint(constraint_id))
            menu.exec(tree.viewport().mapToGlobal(position))
            return
        joint_id = str(data.get("joint_id") or "")
        node_id = joint_id
        if kind == "rig_node":
            node_id = str(data.get("node_id") or "")
            joint_id = node_id if node_id in self.editable_rig_graph.joints else ""
        menu = QMenu(tree)
        if kind in {"rig_root", "rig_joint"} or joint_id:
            menu.addAction("Add Joint", lambda: self.add_editable_rig_joint(joint_id))
        if joint_id:
            structural_editable = self.editable_rig_graph.joint_is_structurally_editable(joint_id)
            rename_action = menu.addAction("Rename Joint", lambda: self.rename_editable_rig_joint(joint_id))
            reparent_action = menu.addAction("Reparent Joint", lambda: self.reparent_editable_rig_joint(joint_id))
            menu.addSeparator()
            delete_action = menu.addAction("Delete Joint", lambda: self.delete_editable_rig_joint(joint_id))
            for action in (rename_action, reparent_action, delete_action):
                action.setEnabled(structural_editable)
                if not structural_editable:
                    action.setStatusTip("This hierarchy is owned by its linked DCC scene.")
        selected_ids = self.selected_local_rig_node_ids()
        if len(selected_ids) >= 2:
            menu.addSeparator()
            constraint_menu = menu.addMenu("Create Constraint")
            for label, constraint_type in (
                ("Parent", "parent"), ("Point", "point"), ("Orient", "orient"),
                ("Rotate", "rotate"), ("Scale", "scale"), ("Aim", "aim"),
            ):
                constraint_menu.addAction(
                    label,
                    lambda _checked=False, value=constraint_type: self.prompt_local_rig_constraint(value),
                )
        if node_id and node_id in self.editable_rig_graph.nodes:
            menu.addSeparator()
            menu.addAction("Create Pose Reader", lambda: self.prompt_local_pose_reader(node_id))
        menu.exec(tree.viewport().mapToGlobal(position))

    def selected_local_rig_node_ids(self) -> list[str]:
        tree = getattr(self, "scene_outliner", None)
        if tree is None:
            return []
        items = list(tree.selectedItems())
        current = tree.currentItem()
        if current in items:
            items = [item for item in items if item is not current] + [current]
        result = []
        for selected_item in items:
            selected_data = selected_item.data(0, Qt.UserRole) or {}
            selected_kind = str(selected_data.get("kind") or "")
            value = (
                selected_data.get("joint_id") if selected_kind == "rig_joint"
                else selected_data.get("node_id") if selected_kind == "rig_node"
                else ""
            )
            if value and str(value) in self.editable_rig_graph.nodes and str(value) not in result:
                result.append(str(value))
        return result

    def prompt_local_rig_constraint(self, constraint_type: str) -> None:
        selected_ids = self.selected_local_rig_node_ids()
        if len(selected_ids) < 2:
            QMessageBox.information(self, "Create Constraint", "Select driver node(s), then select the driven node last.")
            return
        axis_label = "XYZ"
        if constraint_type != "aim":
            axis_label, ok = QInputDialog.getItem(
                self, "Create Constraint", "Constrained axes:", ["XYZ", "X", "Y", "Z", "XY", "XZ", "YZ"], 0, False
            )
            if not ok:
                return
        aim_vector, up_vector = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        if constraint_type == "aim":
            aim_label, ok = QInputDialog.getItem(
                self, "Create Aim Constraint", "Aim axis:", ["+X", "-X", "+Y", "-Y", "+Z", "-Z"], 0, False
            )
            if not ok:
                return
            up_label, ok = QInputDialog.getItem(
                self, "Create Aim Constraint", "World up axis:", ["+Y", "-Y", "+Z", "-Z", "+X", "-X"], 0, False
            )
            if not ok:
                return
            aim_vector = self._axis_label_vector(aim_label)
            up_vector = self._axis_label_vector(up_label)
        offset_answer = QMessageBox.question(
            self,
            "Create Constraint",
            "Maintain the driven object's current offset?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if offset_answer == QMessageBox.Cancel:
            return
        self.create_local_rig_constraint(
            constraint_type,
            selected_ids[:-1],
            selected_ids[-1],
            axes=list(str(axis_label).lower()),
            aim_vector=aim_vector,
            world_up_vector=up_vector,
            maintain_offset=offset_answer == QMessageBox.Yes,
        )

    @staticmethod
    def _axis_label_vector(label: str) -> tuple[float, float, float]:
        text = str(label or "+X").strip().upper()
        sign = -1.0 if text.startswith("-") else 1.0
        axis = text[-1:]
        return (
            sign if axis == "X" else 0.0,
            sign if axis == "Y" else 0.0,
            sign if axis == "Z" else 0.0,
        )

    def create_local_rig_constraint(
        self,
        constraint_type: str,
        drivers: list[str],
        driven: str,
        *,
        axes: list[str] | None = None,
        aim_vector=(1.0, 0.0, 0.0),
        world_up_vector=(0.0, 1.0, 0.0),
        maintain_offset: bool = True,
    ) -> str:
        from tech_connector.game_engine.integration.rigging_host_adapter_service import create_rigging_adapter
        from tech_connector.game_engine.authoring.rigging_workspace_service import RiggingWorkspaceController

        self.push_rig_undo_state(f"Create {constraint_type} constraint")
        controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=self.editable_rig_graph))
        result = controller.run(
            "rig.create_constraint",
            type=str(constraint_type), drivers=list(drivers), driven=str(driven),
            axes=list(axes or ("x", "y", "z")), offset=bool(maintain_offset),
            aim_vector=list(aim_vector), up_vector=list(world_up_vector),
            world_up_vector=list(world_up_vector),
        )
        if not result.ok or not result.created_ids:
            raise RuntimeError(result.message or "Constraint creation failed.")
        self.refresh_scene_outliner()
        self._refresh_native_rig_after_authoring()
        return result.created_ids[0]

    def prompt_local_pose_reader(self, driver: str) -> None:
        axis, ok = QInputDialog.getItem(
            self, "Create Pose Reader", "Driver rotation axis:", ["X", "Y", "Z", "-X", "-Y", "-Z"], 0, False
        )
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "Create Pose Reader", "Reader name:", text=f"{driver}_pose_reader")
        if ok and str(name).strip():
            self.create_local_pose_reader(driver, name=str(name).strip(), axis=str(axis).lower())

    def create_local_pose_reader(
        self, driver: str, *, name: str = "", axis: str = "x", value_range=(-90.0, 90.0)
    ) -> str:
        from tech_connector.game_engine.integration.rigging_host_adapter_service import create_rigging_adapter
        from tech_connector.game_engine.authoring.rigging_workspace_service import RiggingWorkspaceController

        self.push_rig_undo_state("Create pose reader")
        controller = RiggingWorkspaceController(create_rigging_adapter("tc", graph=self.editable_rig_graph))
        result = controller.run(
            "rig.create_pose_reader", driver=str(driver), name=str(name or f"{driver}_pose_reader"),
            axis=str(axis), range=list(value_range),
        )
        if not result.ok or not result.created_ids:
            raise RuntimeError(result.message or "Pose reader creation failed.")
        self.refresh_scene_outliner()
        self._refresh_native_rig_after_authoring()
        return result.created_ids[0]

    def set_local_rig_constraint_enabled(self, constraint_id: str, enabled: bool) -> None:
        constraint = self.editable_rig_graph.constraints.get(str(constraint_id))
        if constraint is None:
            return
        self.push_rig_undo_state("Enable constraint" if enabled else "Mute constraint")
        constraint["enabled"] = bool(enabled)
        self.refresh_scene_outliner()
        self._refresh_native_rig_after_authoring()

    def delete_local_rig_constraint(self, constraint_id: str) -> None:
        if str(constraint_id) not in self.editable_rig_graph.constraints:
            return
        self.push_rig_undo_state("Delete constraint")
        self.editable_rig_graph.constraints.pop(str(constraint_id), None)
        if str(constraint_id) in self.editable_rig_graph.nodes:
            self.editable_rig_graph.nodes.pop(str(constraint_id), None)
        self.refresh_scene_outliner()
        self._refresh_native_rig_after_authoring()

    def _refresh_native_rig_after_authoring(self) -> None:
        if "native_fbx" in (getattr(self, "_dcc_deformation_bindings", {}) or {}):
            try:
                self._refresh_native_fbx_rig_pose()
            except Exception as exc:
                self._resolved_shaded_status = f"Rig evaluation warning: {exc}"
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def add_editable_rig_joint(self, parent_id: str = "") -> None:
        name, ok = QInputDialog.getText(self, "Add Joint", "Joint name:", text="joint")
        if not ok or not str(name).strip():
            return
        try:
            self.push_rig_undo_state("Add joint")
            joint_id = self.editable_rig_graph.add_joint(str(name).strip(), parent_id=str(parent_id or ""))
            self._selected_rig_joint_id = joint_id
            self.refresh_scene_outliner()
            self._resolved_shaded_status = f"Added joint {name}"
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Add Joint Failed", str(exc))

    def rename_editable_rig_joint(self, joint_id: str) -> None:
        joint = self.editable_rig_graph.joints.get(joint_id)
        if joint is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Joint", "Joint name:", text=str(joint.get("name") or "joint"))
        if ok and str(name).strip():
            self.push_rig_undo_state("Rename joint")
            joint["name"] = str(name).strip()
            if joint_id in self.editable_rig_graph.nodes:
                self.editable_rig_graph.nodes[joint_id]["name"] = str(name).strip()
            self.refresh_scene_outliner()

    def reparent_editable_rig_joint(self, joint_id: str) -> None:
        choices = ["World"] + [
            f"{joint.get('name') or key}  [{key}]"
            for key, joint in self.editable_rig_graph.joints.items()
            if key != joint_id
        ]
        choice, ok = QInputDialog.getItem(self, "Reparent Joint", "New parent:", choices, 0, False)
        if not ok:
            return
        parent_id = ""
        if choice != "World" and "[" in choice:
            parent_id = choice.rsplit("[", 1)[1].rstrip("]")
        try:
            self.push_rig_undo_state("Reparent joint")
            self.editable_rig_graph.reparent_joint(joint_id, parent_id)
            self.refresh_scene_outliner()
        except Exception as exc:
            QMessageBox.warning(self, "Reparent Joint Failed", str(exc))

    def delete_editable_rig_joint(self, joint_id: str) -> None:
        try:
            self.push_rig_undo_state("Delete joint")
            self.editable_rig_graph.remove_joint(joint_id)
            self._selected_rig_joint_id = ""
            self.refresh_scene_outliner()
        except Exception as exc:
            QMessageBox.warning(self, "Delete Joint Failed", str(exc))

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
            media_sources = dict(binding.texture_sources or {}) if materials and isinstance(materials[0], SceneProxyMaterialBinding) else {}
            parts = [
                f"{slot}:{Path(path).name}"
                + (f" [{str(media_sources.get(slot, {}).get('source_type')).replace('_', ' ')}]" if media_sources.get(slot, {}).get("source_type") not in {None, "", "image"} else "")
                for slot, path in sorted(texture_bindings.items()) if path
            ]
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
            button.setText("Visibility v" if open_ else "Visibility >")

    def set_selected_proxy_visibility(self, visible: bool) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, (dict, SceneProxyInstance)):
            return
        proxy["visible"] = bool(visible)
        if str(proxy.get("provider_id") or "") == "tech_connector":
            entity = getattr(self, "_runtime_entity_for_proxy", lambda _proxy: None)(proxy)
            if isinstance(entity, dict): entity["visible"] = bool(visible); self._scene_lifecycle.mark_dirty()
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
                if str(proxy.get("provider_id") or "") == "tech_connector":
                    entity = getattr(self, "_runtime_entity_for_proxy", lambda _proxy: None)(proxy)
                    if isinstance(entity, dict): entity["visible"] = proxy is selected
        self._scene_lifecycle.mark_dirty()
        self._resolved_shaded_status = f"Solo {selected.get('provider_id')}:{selected.get('name') or selected.get('native_id')}"
        self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def show_all_scene_proxies(self) -> None:
        changed = 0
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if isinstance(proxy, (dict, SceneProxyInstance)) and not bool(proxy.get("visible", True)):
                proxy["visible"] = True
                if str(proxy.get("provider_id") or "") == "tech_connector":
                    entity = getattr(self, "_runtime_entity_for_proxy", lambda _proxy: None)(proxy)
                    if isinstance(entity, dict): entity["visible"] = True
                changed += 1
        if changed: self._scene_lifecycle.mark_dirty()
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
        provider_base = dcc_provider_base_key(provider)
        object_type = str(proxy.get("type") or proxy.get("object_type") or "object").lower()
        source_action_label = {
            "maya": "Select in Maya",
            "blender": "Select in Blender",
            "unreal": "Select in Unreal",
        }.get(provider_base, f"Select in {provider or 'Source'}")
        action_select_source = menu.addAction(source_action_label)
        if provider_base not in {"maya", "blender", "unreal"}:
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
            provider_base = dcc_provider_base_key(provider)
            if provider_base == "maya":
                code = (
                    "import maya.cmds as cmds\n"
                    f"node = {native_id!r}\n"
                    "if not cmds.objExists(node):\n"
                    "    raise RuntimeError('Object does not exist: ' + node)\n"
                    "cmds.select(node, replace=True)\n"
                    "print('OK')"
                )
                ok, raw = bridge.execute(code, timeout=5.0)
            elif provider_base == "blender":
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
            elif provider_base == "unreal":
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
            "All Texture Sources (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.exr *.bmp *.webp *.gif *.apng *.mp4 *.mov *.m4v *.webm *.mkv *.avi *.ogv);;Animated Images (*.gif *.apng);;Video Textures (*.mp4 *.mov *.m4v *.webm *.mkv *.avi *.ogv);;Still Images (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.exr *.bmp *.webp);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        proxy.bind_texture_file(slot, path)
        source_type = proxy.materials[0].texture_sources.get(slot, {}).get("source_type", "image") if proxy.materials else "image"
        self._resolved_shaded_status = f"Bound {source_type.replace('_', ' ')} {slot} texture to {proxy.provider_id}:{proxy.name}"
        self.update_instance_details_panel()
        self.update_viewport_status()
        if getattr(self, "scene_outliner", None) is not None:
            self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def edit_selected_proxy_media_playback(self) -> None:
        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, SceneProxyInstance) or not proxy.materials:
            if self.isVisible():
                QMessageBox.information(self, "No Media Texture", "Select a proxy with an animated image, sequence, or video texture first.")
            return
        sources = dict(proxy.materials[0].texture_sources or {})
        animated_slots = [
            slot for slot, source in sources.items()
            if str(source.get("source_type") or "image") != "image"
        ]
        if not animated_slots:
            if self.isVisible():
                QMessageBox.information(self, "No Media Texture", "This material only has still-image textures. Bind a GIF, APNG, sequence, or video first.")
            return
        slot, accepted = QInputDialog.getItem(
            self, "Media Texture Playback", "Texture slot", animated_slots, 0, False,
        )
        if not accepted:
            return
        source = sources[str(slot)]
        playback = dict(source.get("playback") or source)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{str(slot).replace('_', ' ').title()} Playback")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        autoplay = QCheckBox("Start automatically")
        autoplay.setChecked(bool(playback.get("autoplay", True)))
        loop = QCheckBox("Loop")
        loop.setChecked(bool(playback.get("loop", True)))
        rate = QDoubleSpinBox()
        rate.setRange(0.05, 8.0)
        rate.setDecimals(2)
        rate.setSingleStep(0.05)
        rate.setValue(float(playback.get("playback_rate", 1.0)))
        start = QDoubleSpinBox()
        start.setRange(0.0, 86400.0)
        start.setDecimals(3)
        start.setValue(float(playback.get("start_time_seconds", 0.0)))
        end = QDoubleSpinBox()
        end.setRange(0.0, 86400.0)
        end.setDecimals(3)
        end.setSpecialValueText("Media end")
        end.setValue(float(playback.get("end_time_seconds") or 0.0))
        synchronization = QComboBox()
        synchronization.addItem("Timeline locked (deterministic)", "timeline")
        synchronization.addItem("Real time", "realtime")
        synchronization.addItem("Manual", "manual")
        selected_sync = synchronization.findData(str(playback.get("synchronization") or "timeline"))
        synchronization.setCurrentIndex(max(0, selected_sync))
        form.addRow("Playback", autoplay)
        form.addRow("Repeat", loop)
        form.addRow("Speed", rate)
        form.addRow("Start (seconds)", start)
        form.addRow("End (seconds)", end)
        form.addRow("Clock", synchronization)
        layout.addLayout(form)
        hint = QLabel("Timeline locked is recommended for scrubbing, rendering, and export. Real time is useful for live screens and signage.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        controls = {
            "autoplay": autoplay.isChecked(), "loop": loop.isChecked(),
            "playback_rate": rate.value(), "start_time_seconds": start.value(),
            "synchronization": synchronization.currentData(),
        }
        if end.value() > start.value():
            controls["end_time_seconds"] = end.value()
        else:
            controls["end_time_seconds"] = None
        proxy.configure_texture_playback(str(slot), **controls)
        self.sync_gpu_viewport()
        self.update_instance_details_panel()
        self._resolved_shaded_status = f"Updated {slot} media playback for {proxy.name}"
        self.update_viewport_status()

    def apply_selected_proxy_procedural_shader_preset(self) -> None:
        from tech_connector.game_engine.rendering.procedural_shader_service import (
            procedural_shader_presets,
            validate_procedural_shader_graph,
        )

        proxy = getattr(self, "_selected_scene_proxy", None)
        if not isinstance(proxy, SceneProxyInstance) or not proxy.materials:
            if self.isVisible():
                QMessageBox.information(self, "No Material Selected", "Select a scene proxy with a material first.")
            return
        presets = procedural_shader_presets()
        labels = {str(graph["name"]): key for key, graph in presets.items()}
        selected, accepted = QInputDialog.getItem(
            self, "Procedural Shader", "Start from a preset", list(labels), 0, False,
        )
        if not accepted:
            return
        graph = copy.deepcopy(presets[labels[str(selected)]])
        validation = validate_procedural_shader_graph(graph)
        if not validation["valid"]:
            QMessageBox.warning(self, "Shader Validation Failed", "\n".join(validation["errors"]))
            return
        material = proxy.materials[0]
        material.procedural_shader = graph
        material.approximation = "procedural_shader_gpu"
        proxy.sync_state = "dirty"
        self.sync_gpu_viewport()
        self.update_instance_details_panel()
        detail = f"cost {validation['estimated_cost']}"
        if validation["warnings"]:
            detail += f" | {validation['warnings'][0]}"
        self._resolved_shaded_status = f"Applied {selected} to {proxy.name} ({detail})"
        self.update_viewport_status()

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
        drive = "selected" if getattr(self, "drive_dcc_camera_enabled", False) else "off"
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
        apply_ms = float(getattr(self, "_last_geometry_apply_ms", 0.0) or 0.0)
        paint_ms = float(getattr(self, "_last_viewport_paint_ms", 0.0) or 0.0)
        total_ms = float(getattr(self, "_last_frame_total_ms", 0.0) or 0.0)
        perf_text = f"   |   Perf: apply {apply_ms:.0f}ms / draw {paint_ms:.0f}ms / frame {total_ms:.0f}ms" if any((apply_ms, paint_ms, total_ms)) else ""
        label.setText(f"Mode: {mode}   |   Display: {display}   |   Coord: {coord}   |   Drive Cam: {drive}   |   Drive Time: {time_drive}   |   Providers: {providers}{scale_text}   |   Selected: {selected_text}{perf_text}   |   {resolved}")

    def refresh_loaded_dcc_scenes(self):
        if not self.isVisible():
            return
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        if not providers:
            return
        if getattr(self, "_dcc_timeline_cache_thread", None) is not None:
            return
        fast_live = bool(getattr(self, "live_dcc_refresh_btn", None) and self.live_dcc_refresh_btn.isChecked())
        if fast_live:
            self._request_async_fast_dcc_scene_refresh(providers)
            return
        self._suppress_dcc_timeline_cache = bool(fast_live and not getattr(self, "drive_dcc_time_enabled", True))
        try:
            self._load_dcc_scene_providers(providers, show_message=False, fast_transform_only=fast_live)
        finally:
            self._suppress_dcc_timeline_cache = False

    def _fast_dcc_snapshot_kwargs_for_provider(self, provider: str) -> dict[str, Any] | None:
        provider_base = dcc_provider_base_key(provider)
        selected_only = bool(
            getattr(self, "maya_selected_only_checkbox", None) is not None
            and self.maya_selected_only_checkbox.isChecked()
        )
        kwargs: dict[str, Any] = {
            "selected_only": selected_only,
            "include_geometry": False,
            "limit": 500,
            "timeout": 8.0,
        }
        if provider_base in {"blender", "unreal"}:
            kwargs["include_materials"] = False
        if provider_base == "maya":
            kwargs["meshes_only"] = False
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
                if not native_id:
                    continue
                vertex_count = int(
                    mesh_data.get("source_vertex_count", mesh_data.get("vertex_count", 0))
                    if isinstance(mesh_data, dict)
                    else getattr(mesh_data, "source_vertex_count", 0)
                    or getattr(mesh_data, "vertex_count", 0)
                    or 0
                )
                target_items.append((native_id, max(0, vertex_count)))
            if not target_items:
                return None
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
            kwargs.update(
                {
                    "target_native_ids": batch,
                    "limit": max(1, min(500, len(batch))),
                    "include_geometry": True,
                    "include_faces": False,
                    "include_cameras": False,
                    "fast_sample": True,
                    "max_vertices_per_object": 200000,
                    "max_faces_per_object": 200000,
                }
            )
        return kwargs

    def _request_async_fast_dcc_scene_refresh(self, providers: list[str]) -> None:
        if getattr(self, "_dcc_async_scene_refresh_thread", None) is not None:
            self._dcc_async_scene_refresh_pending = True
            return
        requests = []
        for provider in providers:
            if dcc_provider_base_key(provider) == "maya":
                targets = [
                    str(proxy.get("native_id") or "")
                    for proxy in (getattr(self.mesh, "scene_proxy_objects", []) or [])
                    if isinstance(proxy, (dict, SceneProxyInstance))
                    and str(proxy.get("provider_id") or "").lower() == str(provider).lower()
                    and bool(proxy.get("visible", True))
                    and str(proxy.get("native_id") or "")
                ]
                if targets:
                    requests.append(
                        {
                            "provider": provider,
                            "kwargs": {"timeout": 10.0},
                            "maya_fast_live_targets": targets,
                            "maya_deformation_binding": (
                                getattr(self, "_dcc_deformation_bindings", {}) or {}
                            ).get(str(provider).lower()),
                            "maya_gpu_skinning_enabled": bool(self.gpu_surface_active()),
                        }
                    )
                    continue
            if dcc_provider_base_key(provider) == "blender":
                targets = []
                for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
                    if not isinstance(proxy, (dict, SceneProxyInstance)):
                        continue
                    mesh_data = proxy.get("mesh_data")
                    topology_state = str(
                        mesh_data.get("topology_state", "")
                        if isinstance(mesh_data, dict)
                        else getattr(mesh_data, "topology_state", "")
                        or ""
                    )
                    native_id = str(proxy.get("native_id") or "")
                    if (
                        str(proxy.get("provider_id") or "").lower() == str(provider).lower()
                        and bool(proxy.get("visible", True))
                        and native_id
                        and topology_state == "mesh"
                    ):
                        targets.append(native_id)
                if targets:
                    requests.append(
                        {
                            "provider": provider,
                            "kwargs": {"timeout": 10.0},
                            "blender_fast_live_targets": targets,
                        }
                    )
                    continue
            if dcc_provider_base_key(provider) == "houdini":
                targets = []
                for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
                    if not isinstance(proxy, (dict, SceneProxyInstance)):
                        continue
                    mesh_data = proxy.get("mesh_data")
                    topology_state = str(
                        mesh_data.get("topology_state", "")
                        if isinstance(mesh_data, dict)
                        else getattr(mesh_data, "topology_state", "")
                        or ""
                    )
                    native_id = str(proxy.get("native_id") or "")
                    if (
                        str(proxy.get("provider_id") or "").lower() == str(provider).lower()
                        and bool(proxy.get("visible", True))
                        and native_id
                        and topology_state == "mesh"
                    ):
                        targets.append(native_id)
                if targets:
                    requests.append(
                        {
                            "provider": provider,
                            "kwargs": {"timeout": 10.0},
                            "houdini_fast_live_targets": targets,
                        }
                    )
                    continue
            kwargs = self._fast_dcc_snapshot_kwargs_for_provider(provider)
            if kwargs:
                requests.append({"provider": provider, "kwargs": kwargs})
        if not requests:
            self._resolved_shaded_status = "Live: no lightweight targets"
            self.update_viewport_status()
            return
        thread = QThread(self)
        worker = DccSceneSnapshotWorker(requests)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.snapshots_ready.connect(self._capture_async_fast_dcc_scene_snapshots)
        worker.snapshots_ready.connect(thread.quit)
        worker.snapshots_ready.connect(worker.deleteLater)
        thread.finished.connect(self._finish_async_fast_dcc_scene_refresh)
        thread.finished.connect(thread.deleteLater)
        self._dcc_async_scene_refresh_thread = thread
        self._dcc_async_scene_refresh_worker = worker
        self._dcc_async_scene_refresh_result = None
        self._dcc_async_scene_refresh_started_s = time.perf_counter()
        thread.start()

    def _suspend_async_dcc_scene_refresh(self) -> None:
        timer = getattr(self, "live_refresh_timer", None)
        if timer is not None:
            timer.stop()
        self._dcc_async_scene_refresh_pending = False
        thread = getattr(self, "_dcc_async_scene_refresh_thread", None)
        worker = getattr(self, "_dcc_async_scene_refresh_worker", None)
        if thread is None:
            return
        try:
            worker.snapshots_ready.disconnect(self._capture_async_fast_dcc_scene_snapshots)
        except Exception:
            pass
        try:
            thread.finished.disconnect(self._finish_async_fast_dcc_scene_refresh)
        except Exception:
            pass
        self._dcc_async_scene_refresh_thread = None
        self._dcc_async_scene_refresh_worker = None
        self._dcc_async_scene_refresh_result = None
        self._dcc_async_scene_refresh_started_s = 0.0
        thread.setParent(QApplication.instance())

    @Slot(dict, list)
    def _capture_async_fast_dcc_scene_snapshots(self, snapshots: dict[str, dict[str, Any]], errors: list[str]) -> None:
        self._dcc_async_scene_refresh_result = (dict(snapshots or {}), list(errors or []))

    @Slot()
    def _finish_async_fast_dcc_scene_refresh(self) -> None:
        sender = self.sender()
        current_thread = getattr(self, "_dcc_async_scene_refresh_thread", None)
        if current_thread is None or (sender is not None and sender is not current_thread):
            return
        result = getattr(self, "_dcc_async_scene_refresh_result", None)
        started_s = float(getattr(self, "_dcc_async_scene_refresh_started_s", 0.0) or 0.0)
        self._dcc_async_scene_refresh_thread = None
        self._dcc_async_scene_refresh_worker = None
        self._dcc_async_scene_refresh_result = None
        self._dcc_async_scene_refresh_started_s = 0.0
        if result is not None:
            self._apply_async_fast_dcc_scene_snapshots(*result)
        pending = bool(getattr(self, "_dcc_async_scene_refresh_pending", False))
        self._dcc_async_scene_refresh_pending = False
        live_enabled = bool(getattr(self, "live_dcc_refresh_btn", None) and self.live_dcc_refresh_btn.isChecked())
        if pending and live_enabled and self.isVisible():
            elapsed_ms = (time.perf_counter() - started_s) * 1000.0 if started_s > 0.0 else 0.0
            target_ms = float(getattr(self, "timeline_refresh_interval_ms", 42) or 42)
            delay_ms = max(0, int(round(target_ms - elapsed_ms)))
            providers = list(getattr(self, "_loaded_scene_providers", []) or [])
            if providers:
                QTimer.singleShot(delay_ms, lambda keys=providers: self._request_async_fast_dcc_scene_refresh(keys))

    def _apply_async_fast_dcc_scene_snapshots(
        self,
        snapshots: dict[str, dict[str, Any]],
        errors: list[str],
    ) -> None:
        if not snapshots:
            if errors:
                self._resolved_shaded_status = f"Live sample failed: {'; '.join(errors)[:120]}"
                self.update_viewport_status()
            return
        processed: dict[str, dict[str, Any]] = {}
        for provider, snapshot in snapshots.items():
            try:
                previous_snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
                previous_revision = previous_snapshot.get("scene_revision") if isinstance(previous_snapshot, dict) else None
                current_revision = snapshot.get("scene_revision")
                if (
                    previous_revision is not None
                    and current_revision is not None
                    and int(previous_revision) != int(current_revision)
                ):
                    self._clear_dcc_timeline_snapshot_cache()
                    self._dcc_deformation_bindings.pop(str(provider).lower(), None)
                    self._dcc_deformation_binding_fingerprints.pop(str(provider).lower(), None)
                    self._dcc_timeline_cache_status = (
                        f"Source edit detected in {provider}; stale timeline cache cleared"
                    )
                    QTimer.singleShot(0, lambda key=str(provider).lower(): self._start_maya_deformation_binding(key))
                snapshot = self._snapshot_for_viewer_scale_policy(provider, snapshot)
                if isinstance(previous_snapshot, dict):
                    if not snapshot.get("cameras"):
                        snapshot["cameras"] = copy.deepcopy(previous_snapshot.get("cameras") or [])
                    if not snapshot.get("active_camera"):
                        snapshot["active_camera"] = previous_snapshot.get("active_camera", "")
                processed[provider] = snapshot
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
        if not processed:
            return
        gpu_pose_changed = False
        if self.gpu_surface_active():
            for provider, snapshot in processed.items():
                pose = snapshot.get("deformation_pose") if isinstance(snapshot, dict) else None
                binding = (getattr(self, "_dcc_deformation_bindings", {}) or {}).get(str(provider).lower())
                if isinstance(pose, dict) and isinstance(binding, dict):
                    gpu_pose_changed = bool(
                        self.gpu_viewport.update_deformation_pose(provider, binding, pose)
                    ) or gpu_pose_changed
        gpu_point_changed = bool(
            self.gpu_surface_active() and self.gpu_viewport.update_fast_snapshots(processed)
        )
        gpu_changed = gpu_pose_changed or gpu_point_changed
        if gpu_changed:
            geometry = getattr(getattr(self, "gpu_viewport", None), "geometry", None)
            skin_geometry = getattr(getattr(self, "gpu_viewport", None), "skin_geometry", None)
            self._last_geometry_apply_ms = max(
                float(getattr(geometry, "last_position_upload_ms", 0.0) or 0.0),
                float(getattr(skin_geometry, "last_pose_upload_ms", 0.0) or 0.0),
            )
        cpu_changed = self._apply_fast_transform_snapshot_updates(
            processed,
            apply_mesh_geometry=not gpu_changed,
        )
        if cpu_changed or gpu_changed:
            self._dcc_scene_snapshots.update({
                provider: self._merged_fast_transform_snapshot(provider, snapshot)
                for provider, snapshot in processed.items()
            })
            self._last_scene_refresh_changed = True
            self._refresh_coordinate_scale_status()
            self._refresh_camera_authority_choices()
            self._resolved_shaded_status = f"Live sampled {sum(len(s.get('objects') or []) for s in processed.values())} object(s)"
            self.update_viewport_status()
            if hasattr(self, "canvas") and self.canvas:
                self.canvas.update()
        else:
            self._dcc_scene_snapshots.update({
                provider: self._merged_fast_transform_snapshot(provider, snapshot)
                for provider, snapshot in processed.items()
            })
            self._resolved_shaded_status = "Live sample cached; no visible delta"
            self.update_viewport_status()

    def refresh_loaded_dcc_scenes_for_current_frame(self):
        if not self.isVisible():
            return
        providers = list(getattr(self, "_loaded_scene_providers", []) or [])
        if not providers:
            return
        frame = int(getattr(self, "_current_dcc_frame", 1) or 1)
        cached = self._cached_timeline_snapshots(providers, frame)
        if cached and self._apply_cached_timeline_snapshots(cached, frame):
            return
        live_follow = bool(getattr(self, "live_dcc_refresh_btn", None) and self.live_dcc_refresh_btn.isChecked())
        if getattr(self, "drive_dcc_time_enabled", True) and not live_follow:
            self.drive_loaded_dcc_time_from_view()
        if self._load_dcc_scene_providers(providers, show_message=False, fast_transform_only=True):
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
        self._frame_render_request_started_s = time.perf_counter()
        self._current_dcc_frame = int(getattr(self, "_dcc_timeline_frame_start", 1) or 1) + int(frame_index or 0)
        timeline = getattr(self, "anim_timeline", None)
        gpu = getattr(self, "gpu_viewport", None)
        if gpu is not None:
            fps_widget = getattr(timeline, "fps_spin", None)
            fps = float(fps_widget.value()) if fps_widget is not None else 24.0
            gpu.set_media_timeline(
                self._current_dcc_frame,
                fps,
                frame_start=int(getattr(self, "_dcc_timeline_frame_start", 1) or 1),
                playing=bool(getattr(timeline, "is_playing", False)),
            )
        self.apply_cached_simulation_frame(self._current_dcc_frame)
        native_changed, native_message = self._apply_native_fbx_animation_frame(self._current_dcc_frame)
        if not getattr(self, "_loaded_scene_providers", None):
            if native_message:
                self._resolved_shaded_status = native_message
                self.update_viewport_status()
            return
        if getattr(self, "drive_dcc_time_enabled", True):
            self._resolved_shaded_status = f"Driving DCC time: frame {self._current_dcc_frame}"
            self.update_viewport_status()
        self.timeline_refresh_timer.start()
        if not getattr(self, "live_dcc_refresh_btn", None) or not self.live_dcc_refresh_btn.isChecked():
            self.schedule_resolved_shaded_refresh("timeline scrub")

    def on_media_playback_toggled(self, playing: bool) -> None:
        timeline = getattr(self, "anim_timeline", None)
        gpu = getattr(self, "gpu_viewport", None)
        if gpu is None:
            return
        fps_widget = getattr(timeline, "fps_spin", None)
        fps = float(fps_widget.value()) if fps_widget is not None else 24.0
        gpu.set_media_timeline(
            int(getattr(self, "_current_dcc_frame", 1) or 1),
            fps,
            frame_start=int(getattr(self, "_dcc_timeline_frame_start", 1) or 1),
            playing=bool(playing),
        )

    def apply_cached_simulation_frame(self, frame: int) -> bool:
        cache = getattr(self, "simulation_cache", None)
        world = getattr(self, "simulation_world", None)
        cached = (getattr(cache, "frames", {}) or {}).get(int(frame)) if cache is not None else None
        if world is None or cached is None or len(cached.positions) != len(world.particles):
            return False
        for index, particle in enumerate(world.particles):
            particle.position = tuple(float(value) for value in cached.positions[index])
            if index < len(cached.velocities):
                particle.velocity = tuple(float(value) for value in cached.velocities[index])
        world.time_seconds = float(cached.time_seconds)
        self.simulation_frame = int(frame)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        return True

    def drive_loaded_dcc_time_from_view(self) -> tuple[bool, str]:
        if not self._allow_dcc_outbound("timeline", reason="timeline drive"):
            return False, "Timeline outbound is disabled by DCC write policy."
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
            self.live_refresh_timer.setInterval(int(getattr(self, "timeline_refresh_interval_ms", 42) or 42))
            self.live_refresh_timer.start()
        else:
            self.live_refresh_timer.stop()
            self.live_refresh_timer.setInterval(int(getattr(self, "live_refresh_interval_ms", 2500) or 2500))

    def _refresh_camera_authority_choices(self) -> None:
        combo = getattr(self, "camera_authority_combo", None)
        if combo is None:
            return
        desired_items: list[tuple[str, dict[str, Any]]] = [("TC Camera", {"mode": "tech_connector"})]
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
                role_suffix = f" [{camera_role}]" if dcc_provider_base_key(provider) == "unreal" and camera_role else ""
                label = f"{provider}: {camera_name}{role_suffix}"
                if active_camera and native_id.endswith(active_camera):
                    label += " (active)"
                desired_items.append(
                    (
                        label,
                        {
                            "mode": "dcc_camera",
                            "provider": provider,
                            "native_id": native_id,
                            "camera_role": camera_role,
                        },
                    )
                )

        def item_key(label: str, data: Any) -> str:
            return json.dumps({"label": label, "data": data}, sort_keys=True, default=str)

        desired_keys = [item_key(label, data) for label, data in desired_items]
        current_keys = [item_key(combo.itemText(index), combo.itemData(index)) for index in range(combo.count())]
        if desired_keys == current_keys:
            return

        current_data = combo.currentData()
        current_key = json.dumps(current_data, sort_keys=True, default=str) if current_data else ""
        self._suppress_camera_combo_update = True
        try:
            combo.clear()
            for label, data in desired_items:
                combo.addItem(label, data)
            for index in range(combo.count()):
                data = combo.itemData(index)
                key = json.dumps(data, sort_keys=True, default=str) if data else ""
                if key == current_key:
                    combo.setCurrentIndex(index)
                    break
        finally:
            self._suppress_camera_combo_update = False

    def sync_selected_camera_authority(self) -> None:
        choice = {"mode": "tech_connector"}
        if getattr(self, "camera_authority_combo", None) is not None:
            choice = self.camera_authority_combo.currentData() or choice
        mode = str(choice.get("mode") or "tech_connector")
        if mode == "dcc_camera":
            ok, message = self._use_dcc_camera_authority(str(choice.get("provider") or ""), str(choice.get("native_id") or ""))
        else:
            ok, message = self.drive_selected_dcc_camera_from_view()
            if not ok:
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
        if not self._allow_dcc_outbound("camera", reason=reason):
            return
        timer = getattr(self, "camera_drive_timer", None)
        if timer is None:
            return
        if not timer.isActive():
            timer.start()

    def _suspend_async_dcc_camera_drive(self) -> None:
        timer = getattr(self, "camera_drive_timer", None)
        if timer is not None:
            timer.stop()
        self._dcc_camera_possession_pending = False
        thread = getattr(self, "_dcc_camera_possession_thread", None)
        worker = getattr(self, "_dcc_camera_possession_worker", None)
        if worker is not None:
            try:
                worker.cancel()
            except Exception:
                pass
        if thread is None:
            self._dcc_camera_possession_thread = None
            self._dcc_camera_possession_worker = None
            self._dcc_camera_possession_payload_keys = {}
            self._dcc_camera_possession_results = {}
            return
        if not thread.isRunning():
            self._dcc_camera_possession_thread = None
            self._dcc_camera_possession_worker = None
            self._dcc_camera_possession_payload_keys = {}
            self._dcc_camera_possession_results = {}
            return
        try:
            worker.finished.disconnect(self._capture_async_dcc_camera_possession_result)
        except Exception:
            pass
        try:
            thread.finished.disconnect(self._finish_async_dcc_camera_possession)
        except Exception:
            pass
        try:
            thread.requestInterruption()
        except Exception:
            pass
        thread.quit()
        thread.wait(3000)
        self._dcc_camera_possession_thread = None
        self._dcc_camera_possession_worker = None
        self._dcc_camera_possession_payload_keys = {}
        self._dcc_camera_possession_results = {}
        thread.setParent(QApplication.instance())

    def _allow_dcc_outbound(self, kind: str, *, reason: str = "") -> bool:
        """Central outbound bridge policy.

        TODO: Keep DCC writes narrow. During live playback/follow, TC should only
        send timeline, selected-camera drive, or explicit selected-object edits.
        Never add broad scene/object write-back here without a user action.
        """
        outbound_kind = str(kind or "").strip().lower()
        if outbound_kind in {"timeline", "camera", "selected_object"}:
            return True
        self._resolved_shaded_status = f"Skipped outbound DCC {outbound_kind or 'write'} during {reason or 'viewer update'}"
        self.update_viewport_status()
        return False

    def drive_loaded_dcc_cameras_from_view(self) -> None:
        if not getattr(self, "drive_dcc_camera_enabled", False):
            return
        source = str(getattr(self, "viewport_display_source", "") or "").lower()
        reason = "stream navigation" if source == "dcc" else "camera navigation"
        self.request_dcc_camera_possession_async(include_unreal=True, reason=reason)

    def request_dcc_camera_possession_async(self, *, include_unreal: bool, reason: str = "") -> None:
        if getattr(self, "_dcc_camera_possession_thread", None) is not None:
            self._dcc_camera_possession_pending = True
            return
        providers, skipped = self._camera_drive_provider_keys(include_unreal=include_unreal)
        requests = []
        payload_keys: dict[str, str] = {}
        failures = []
        for provider in providers:
            try:
                payload = self._federated_camera_in_provider_space(provider)
                payload_key = self._camera_payload_key(payload)
                if getattr(self, "_last_dcc_camera_payload_keys", {}).get(provider) == payload_key:
                    continue
                code, execution, timeout = self._camera_possession_request_for_payload(provider, payload)
                requests.append(
                    {
                        "provider": provider,
                        "code": code,
                        "execution": execution,
                        "timeout": timeout,
                    }
                )
                payload_keys[provider] = payload_key
            except Exception as exc:
                failures.append(f"{provider}: {exc}")
        if not requests:
            if failures:
                self._resolved_shaded_status = f"Camera possession failed: {'; '.join(failures)[:140]}"
            elif skipped:
                self._resolved_shaded_status = f"Camera possession unavailable for: {', '.join(skipped)}"
            self.update_viewport_status()
            return
        thread = QThread(self)
        worker = DccCameraPossessionWorker(requests)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_async_dcc_camera_possession_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_async_dcc_camera_possession)
        thread.finished.connect(thread.deleteLater)
        self._dcc_camera_possession_thread = thread
        self._dcc_camera_possession_worker = worker
        self._dcc_camera_possession_payload_keys = payload_keys
        self._dcc_camera_possession_results = {}
        self._dcc_camera_possession_started_s = time.perf_counter()
        self._resolved_shaded_status = f"Matching DCC cameras: {reason or 'camera update'}"
        self.update_viewport_status()
        thread.start()

    @Slot(dict)
    def _capture_async_dcc_camera_possession_result(self, results: dict[str, dict[str, Any]]) -> None:
        self._dcc_camera_possession_results = dict(results or {})

    @Slot()
    def _finish_async_dcc_camera_possession(self) -> None:
        sender = self.sender()
        current_thread = getattr(self, "_dcc_camera_possession_thread", None)
        if current_thread is None or (sender is not None and sender is not current_thread):
            return
        results = dict(getattr(self, "_dcc_camera_possession_results", {}) or {})
        payload_keys = dict(getattr(self, "_dcc_camera_possession_payload_keys", {}) or {})
        started_s = float(getattr(self, "_dcc_camera_possession_started_s", 0.0) or 0.0)
        self._dcc_camera_possession_thread = None
        self._dcc_camera_possession_worker = None
        self._dcc_camera_possession_payload_keys = {}
        self._dcc_camera_possession_results = {}
        self._dcc_camera_possession_started_s = 0.0
        if started_s > 0.0:
            elapsed_ms = max(1.0, (time.perf_counter() - started_s) * 1000.0)
            previous_ms = float(getattr(self, "_camera_drive_latency_ema_ms", elapsed_ms) or elapsed_ms)
            self._camera_drive_latency_ema_ms = previous_ms * 0.75 + elapsed_ms * 0.25
            next_interval = max(16, min(100, int(round(self._camera_drive_latency_ema_ms * 1.10))))
            timer = getattr(self, "camera_drive_timer", None)
            if timer is not None:
                timer.setInterval(next_interval)
        failures = []
        succeeded = []
        for provider, result in (results or {}).items():
            if bool((result or {}).get("ok")):
                succeeded.append(provider)
                if provider in payload_keys:
                    self._last_dcc_camera_payload_keys[provider] = payload_keys[provider]
            else:
                failures.append(f"{provider}: {str((result or {}).get('message') or '')[:90]}")
        if failures:
            self._resolved_shaded_status = f"Camera match partial: {'; '.join(failures)[:150]}"
        elif succeeded:
            self._resolved_shaded_status = f"Camera matched: {', '.join(succeeded)}"
        self.update_viewport_status()
        pending = bool(getattr(self, "_dcc_camera_possession_pending", False))
        self._dcc_camera_possession_pending = False
        if pending and self.isVisible() and getattr(self, "drive_dcc_camera_enabled", False):
            QTimer.singleShot(0, lambda: self.request_dcc_camera_possession_async(include_unreal=True, reason="queued navigation"))

    def drive_selected_dcc_camera_from_view(self) -> tuple[bool, str]:
        choice = {"mode": "tech_connector"}
        if getattr(self, "camera_authority_combo", None) is not None:
            choice = self.camera_authority_combo.currentData() or choice
        mode = str(choice.get("mode") or "tech_connector")
        if mode != "dcc_camera":
            return False, "Choose a DCC camera in the dropdown before enabling Drive Selected."
        provider = str(choice.get("provider") or "").lower()
        native_id = str(choice.get("native_id") or "")
        if not provider or not native_id:
            return False, "Selected camera target is missing provider or native id."
        payload = self._federated_camera_in_provider_space(provider)
        self._possess_provider_camera_from_payload(provider, payload)
        try:
            self._switch_provider_to_camera(provider, native_id)
        except Exception as exc:
            detail = self.record_nonfatal_diagnostic("Could not switch the source DCC viewport to its camera", exc, surface=True)
            return True, f"Driving selected camera {provider}:{native_id} from TC view; source viewport switch failed: {detail}"
        return True, f"Driving selected camera {provider}:{native_id} from TC view."

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
        source_base = dcc_provider_base_key(source_provider)
        target_base = dcc_provider_base_key(target_provider)
        if source_provider == target_provider or {source_base, target_base} <= {"maya", "motionbuilder"}:
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
            realtime_paused = [provider for provider in skipped if dcc_provider_base_key(provider) == "unreal"]
            other_skipped = [provider for provider in skipped if dcc_provider_base_key(provider) != "unreal"]
            if realtime_paused:
                message += f" Realtime drive is paused for: {', '.join(realtime_paused)}."
            if other_skipped:
                message += f" Camera drive not implemented yet for connected: {', '.join(other_skipped)}."
        return True, message

    def _camera_drive_provider_keys(self, *, include_unreal: bool = False) -> tuple[list[str], list[str]]:
        supported_bases = {"maya", "blender", "motionbuilder", "houdini", "unity"}
        if include_unreal:
            supported_bases.add("unreal")
        loaded = list(dict.fromkeys(str(key or "").lower() for key in (getattr(self, "_loaded_scene_providers", []) or []) if str(key or "")))
        connected = loaded or self._connected_dcc_provider_keys(
            ("maya", "blender", "motionbuilder", "houdini", "unreal", "unity")
        )
        supported = [provider for provider in connected if dcc_provider_base_key(provider) in supported_bases]
        skipped = [provider for provider in connected if dcc_provider_base_key(provider) not in supported_bases]
        self._camera_drive_provider_cache = (time.monotonic(), supported, skipped)
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
        scale = max(1.0e-6, float(getattr(self.mesh, "scene_scale", 1.0) or 1.0))
        center = getattr(self.mesh, "scene_center", (0.0, 0.0, 0.0))
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        if float(getattr(camera, "aspect_ratio", 0.0) or 0.0) > 0.0:
            aspect_ratio = float(camera.aspect_ratio)
        elif hasattr(self, "canvas") and self.canvas:
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

    def _camera_possession_request_for_payload(
        self,
        provider: str,
        payload: dict[str, Any],
    ) -> tuple[str, str, float]:
        provider_base = dcc_provider_base_key(provider)
        if provider_base == "maya":
            return self._maya_possess_camera_code(payload), "execute", 3.0
        if provider_base == "blender":
            return self._blender_possess_camera_code(payload), "execute", 3.0
        if provider_base == "motionbuilder":
            return self._motionbuilder_possess_camera_code(payload), "execute", 3.0
        if provider_base == "houdini":
            return self._houdini_possess_camera_code(payload), "execute", 3.0
        if provider_base == "unity":
            return self._unity_possess_camera_code(payload), "execute", 3.0
        if provider_base == "unreal":
            return self._unreal_possess_camera_code(payload), "execute_python", 6.0
        raise ValueError(f"Camera possession is not implemented for {provider}.")

    def _possess_provider_camera_from_payload(self, provider: str, payload: dict[str, Any]) -> None:
        bridge = self._scene_snapshot_bridge(provider)
        code, execution, timeout = self._camera_possession_request_for_payload(provider, payload)
        if execution == "execute_python":
            response = bridge.execute_python(code, timeout=timeout, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            ok, raw = bridge.execute(code, timeout=timeout)
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
        provider_base = dcc_provider_base_key(provider_key)
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_base == "maya":
            code = self._maya_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_base == "blender":
            code = self._blender_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_base == "motionbuilder":
            code = self._motionbuilder_read_camera_authority_code(native_id)
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_base == "unreal":
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
            aspect_ratio=max(0.0, float(payload.get("aspect_ratio", 0.0) or 0.0)),
            near_clip=float(payload.get("near_clip", 0.1)),
            far_clip=float(payload.get("far_clip", 100000.0)),
        )
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _switch_provider_to_camera(self, provider: str, native_id: str) -> None:
        provider_key = str(provider or "").lower()
        provider_base = dcc_provider_base_key(provider_key)
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_base == "maya":
            code = (
                "import maya.cmds as cmds\n"
                f"camera = {native_id!r}\n"
                "for panel in cmds.getPanel(type='modelPanel') or []:\n"
                "    try: cmds.modelPanel(panel, edit=True, camera=camera)\n"
                "    except Exception: pass\n"
                "print('OK')"
            )
            ok, raw = bridge.execute(code, timeout=5.0)
        elif provider_base == "blender":
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
        elif provider_base == "motionbuilder":
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
        elif provider_base == "unreal":
            response = bridge.execute_python(self._unreal_switch_camera_code(native_id), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError(f"Camera switching is not implemented for {provider_key} yet.")
        if not ok:
            raise RuntimeError(raw)

    def _maya_read_camera_authority_code(self, native_id: str) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import (
            build_maya_camera_authority_code,
        )

        return build_maya_camera_authority_code(native_id)
