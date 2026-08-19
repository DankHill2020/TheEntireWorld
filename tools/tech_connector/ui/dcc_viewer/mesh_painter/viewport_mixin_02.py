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


class ThreeDMeshPainterViewportMixin02:
    def _execute_tc_skinning_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command in {"skinning.export_weights", "skinning.import_weights"}:
            return self._execute_tc_skin_weight_file_command(command, payload)
        from tech_connector.game_engine.deformation.skinning_tool_service import (
            add_skin_influence,
            apply_skin_cluster_to_rig_graph,
            auto_skin_cluster,
            bind_skin,
            copy_skin_weights,
            influences_from_rig_graph,
            mirror_skin_weights,
            normalize_skin_cluster,
            paint_skin_weight,
            prune_skin_cluster,
            remove_skin_influence,
            SkinningOperationResult,
            skin_cluster_from_rig_graph,
            skin_cluster_summary,
            smooth_skin_weights,
            transfer_skin_weights,
        )

        topology, _colors, _proxies = self._canonical_mesh_topology()
        mesh_id = str(payload.get("mesh_id") or getattr(self.mesh, "name", "mesh"))
        skin_id = str(payload.get("skin_id") or "")
        if not skin_id and command not in {"skinning.bind_skin", "skinning.auto_skin"}:
            skin_id, source_kind, mesh_id = self._selected_skin_or_deformer()
            if source_kind != "skin":
                raise ValueError("Select a skin in the Scene Outliner first.")

        if command in {"skinning.bind_skin", "skinning.auto_skin"}:
            joint_ids = [str(value) for value in payload.get("influences") or self.editable_rig_graph.joints]
            if str(payload.get("bind_method") or "") == "current":
                if not skin_id:
                    candidates = [
                        key for key, value in self.editable_rig_graph.skins.items()
                        if str(value.get("mesh_id") or "") == mesh_id
                    ]
                    skin_id = candidates[0] if candidates else ""
                if not skin_id:
                    raise ValueError("No existing skin weights are attached to this mesh.")
                cluster = skin_cluster_from_rig_graph(self.editable_rig_graph, skin_id)
                return {"skin_id": skin_id, "summary": skin_cluster_summary(cluster), "message": f"Using existing weights from {skin_id}."}
            influences = influences_from_rig_graph(self.editable_rig_graph, joint_ids=joint_ids)
            if not influences:
                raise ValueError("Create or import joints before binding skin.")
            bind_callable = auto_skin_cluster if command == "skinning.auto_skin" else bind_skin
            result = bind_callable(
                mesh_id=mesh_id,
                vertices=topology.vertices,
                influences=influences,
                bind_method=str(payload.get("bind_method") or ("auto" if command.endswith("auto_skin") else "distance")),
                max_influences=max(1, min(32, int(payload.get("max_influences", 8) or 8))),
                falloff=float(payload.get("falloff", 2.0)),
                **({
                    "prune_threshold": float(payload.get("prune_threshold", 0.001)),
                    "smooth_iterations": int(payload.get("smooth_iterations", 1)),
                } if command == "skinning.auto_skin" else {}),
            )
            if not result.ok or result.cluster is None:
                raise ValueError(" ".join(result.warnings) or "Skin bind failed.")
            cluster = result.cluster
            skin_id = str(payload.get("skin_id") or f"tc::{mesh_id}::skin")
        else:
            cluster = skin_cluster_from_rig_graph(self.editable_rig_graph, skin_id)
            if command == "skinning.paint_weights":
                vertex_indices = payload.get("vertex_indices") or payload.get("vertices") or sorted(self.selected_mesh_vertex_indices)
                if not vertex_indices:
                    raise ValueError("Select vertices or provide vertex_indices before painting skin weights.")
                result = paint_skin_weight(
                    cluster,
                    vertex_indices=vertex_indices,
                    influence=str(payload.get("influence") or ""),
                    value=float(payload.get("weight", payload.get("value", 1.0))),
                    mode=str(payload.get("mode") or "replace"),
                    strength=float(payload.get("strength", 1.0)),
                )
            elif command == "skinning.normalize_weights":
                result = normalize_skin_cluster(cluster)
            elif command == "skinning.prune_weights":
                result = prune_skin_cluster(
                    cluster,
                    threshold=float(payload.get("threshold", 0.001)),
                    max_influences=int(payload.get("max_influences", cluster.max_influences)),
                )
            elif command == "skinning.smooth_weights":
                result = smooth_skin_weights(
                    cluster,
                    vertex_indices=payload.get("vertex_indices"),
                    iterations=int(payload.get("iterations", 1)),
                    strength=float(payload.get("strength", 0.5)),
                )
            elif command == "skinning.mirror_weights":
                result = mirror_skin_weights(cluster)
            elif command == "skinning.add_influence":
                influence_id = str(payload.get("influence") or "")
                influences = influences_from_rig_graph(self.editable_rig_graph, joint_ids=[influence_id])
                if not influences:
                    raise ValueError(f"Unknown TC joint influence: {influence_id}")
                result = add_skin_influence(cluster, influences[0])
            elif command == "skinning.remove_influence":
                result = remove_skin_influence(
                    cluster,
                    str(payload.get("influence") or ""),
                    fallback_influence=str(payload.get("fallback_influence") or ""),
                )
            elif command in {"skinning.copy_weights", "skinning.transfer_weights"}:
                target_mesh_id = str(payload.get("target_mesh_id") or payload.get("target_mesh") or "")
                if not target_mesh_id:
                    raise ValueError("target_mesh_id is required when copying or transferring skin weights.")
                if command == "skinning.copy_weights":
                    copied = copy_skin_weights(
                        cluster,
                        target_mesh_id=target_mesh_id,
                        target_vertex_count=payload.get("target_vertex_count"),
                    )
                    result = SkinningOperationResult(
                        True,
                        "copy_skin_weights",
                        copied,
                        changed_vertices=tuple(range(copied.vertex_count)),
                    )
                else:
                    result = transfer_skin_weights(
                        cluster,
                        target_mesh_id=target_mesh_id,
                        target_vertex_count=payload.get("target_vertex_count"),
                        strategy=str(payload.get("strategy") or "index"),
                    )
                skin_id = str(payload.get("target_skin_id") or f"tc::{target_mesh_id}::skin")
            else:
                raise ValueError(f"No TC-native skinning executor is registered for {command}.")
            if not result.ok or result.cluster is None:
                raise ValueError(" ".join(result.warnings) or f"{command} failed.")
            cluster = result.cluster

        self.push_rig_undo_state(command.replace("skinning.", "").replace("_", " ").title())
        native_skin_id = apply_skin_cluster_to_rig_graph(
            self.editable_rig_graph,
            cluster,
            skin_id=skin_id or None,
        )
        self.refresh_scene_outliner()
        warnings = tuple(getattr(result, "warnings", ()) or ())
        summary = skin_cluster_summary(cluster)
        message = (
            f"{command.split('.')[-1].replace('_', ' ').title()} complete on {native_skin_id}: "
            f"{summary['weighted_vertices']}/{summary['vertex_count']} weighted vertices, "
            f"up to {summary['max_influences']} influences."
        )
        if warnings:
            message += f" {warnings[0]}"
        return {"skin_id": native_skin_id, "summary": summary, "warnings": list(warnings), "message": message}

    def _execute_tc_skin_weight_file_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.deformation.skinning_tool_service import (
            skin_cluster_from_rig_graph,
            skin_topology_identity,
        )

        thread = getattr(self, "_skin_weight_io_thread", None)
        if thread is not None and thread.isRunning():
            raise RuntimeError("A skin-weight import or export is already running.")
        topology, _colors, _proxies = self._canonical_mesh_topology()
        vertices = [tuple(float(value) for value in vertex) for vertex in topology.vertices]
        faces = [tuple(int(value) for value in face) for face in topology.faces]
        path = str(payload.get("path") or "").strip()
        if not path:
            raise ValueError("path is required for skin-weight import or export.")

        if command == "skinning.export_weights":
            skin_id = str(payload.get("skin_id") or "")
            if not skin_id:
                skin_id, source_kind, _mesh_id = self._selected_skin_or_deformer()
                if source_kind != "skin":
                    raise ValueError("Select a skin in the Scene Outliner before exporting weights.")
            cluster = skin_cluster_from_rig_graph(self.editable_rig_graph, skin_id)
            operation = "export"
            arguments = {
                "path": path,
                "cluster": cluster,
                "vertex_positions": vertices,
                "faces": faces,
            }
            context = {"skin_id": skin_id}
            message = f"Exporting {cluster.vertex_count} skin-weight row(s) in the background."
        else:
            skin_id = str(payload.get("skin_id") or "")
            target_mesh_id = str(payload.get("target_mesh_id") or getattr(self.mesh, "name", "mesh"))
            if not skin_id:
                try:
                    selected_id, source_kind, selected_mesh_id = self._selected_skin_or_deformer()
                    if source_kind == "skin":
                        skin_id = selected_id
                        target_mesh_id = selected_mesh_id or target_mesh_id
                except ValueError:
                    pass
            identity = skin_topology_identity(vertices, faces)
            operation = "import"
            arguments = {
                "path": path,
                "target_mesh_id": target_mesh_id,
                "expected_vertex_count": len(vertices),
                "expected_topology_fingerprint": identity["fingerprint"],
                "available_influences": tuple(self.editable_rig_graph.joints),
                "influence_map": dict(payload.get("influence_map") or {}),
                "allow_partial": bool(payload.get("allow_partial", False)),
            }
            context = {"skin_id": skin_id, "target_mesh_id": target_mesh_id}
            message = "Validating and importing skin weights in the background."

        self._start_skin_weight_io(operation, arguments, context)
        return {"started": True, "operation": operation, "path": str(Path(path).expanduser()), "message": message}

    def _start_skin_weight_io(self, operation: str, arguments: dict[str, Any], context: dict[str, Any]) -> None:
        thread = QThread(self)
        worker = SkinWeightFileWorker(operation, arguments)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_skin_weight_io)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._finish_skin_weight_io_thread(current))
        thread.finished.connect(thread.deleteLater)
        self._skin_weight_io_thread = thread
        self._skin_weight_io_worker = worker
        self._skin_weight_io_context = dict(context)
        thread.start()

    @Slot(bool, str, object, str)
    def _capture_skin_weight_io(self, ok: bool, operation: str, result: object, message: str) -> None:
        if not ok or result is None:
            self._resolved_shaded_status = f"Skin-weight {operation} failed: {message}"
            self.update_viewport_status()
            if self.isVisible():
                QMessageBox.warning(self, "Skin Weights", str(message))
            return
        if operation == "import":
            from tech_connector.game_engine.deformation.skinning_tool_service import apply_skin_cluster_to_rig_graph

            context = dict(getattr(self, "_skin_weight_io_context", {}) or {})
            self.push_rig_undo_state("Import skin weights")
            skin_id = apply_skin_cluster_to_rig_graph(
                self.editable_rig_graph,
                result.cluster,
                skin_id=str(context.get("skin_id") or "") or None,
            )
            self.refresh_scene_outliner()
            warnings = tuple(getattr(result, "warnings", ()) or ())
            message = f"Imported skin weights into {skin_id}." + (f" {warnings[0]}" if warnings else "")
        self._resolved_shaded_status = str(message)
        self.update_viewport_status()

    def _finish_skin_weight_io_thread(self, thread: QThread) -> None:
        if self._skin_weight_io_thread is thread:
            self._skin_weight_io_thread = None
            self._skin_weight_io_worker = None
            self._skin_weight_io_context = {}

    def _detach_skin_weight_io_worker(self) -> None:
        thread = getattr(self, "_skin_weight_io_thread", None)
        self._skin_weight_io_thread = None
        self._skin_weight_io_worker = None
        self._skin_weight_io_context = {}
        if thread is None:
            return
        try:
            thread.requestInterruption()
        except Exception as exc:
            LOGGER.debug("Could not interrupt the USD composition worker during cleanup.", exc_info=True)
        thread.quit()
        thread.wait(5000)

    def _execute_tc_usd_composition_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.scene.usd_composition_command_service import apply_usd_composition_command

        outcome = apply_usd_composition_command(
            command,
            payload,
            composition=getattr(self, "_usd_composition", None),
            result=getattr(self, "_usd_composition_result", None),
        )
        response = dict(outcome.response)
        if not outcome.requires_compose:
            return response
        thread = getattr(self, "_usd_composition_thread", None)
        if thread is not None and thread.isRunning():
            raise RuntimeError("An OpenUSD composition is already running.")
        self._start_usd_composition(outcome.composition, outcome.output_path)
        response["started"] = True
        return response

    def _execute_tc_deformation_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "deformation.add_jiggle":
            from tech_connector.game_engine.deformation import (
                JiggleDeformerSettings,
                attach_jiggle_deformer,
            )

            source_id = str(payload.get("source_id") or "")
            mesh_id = str(payload.get("mesh_id") or "")
            if not source_id:
                source_id, _source_kind, selected_mesh_id = self._selected_skin_or_deformer()
                mesh_id = mesh_id or selected_mesh_id
            key = str(payload.get("map_key") or f"jiggle:{source_id}")
            influence_map = self.deformation_weight_map(key)
            settings = JiggleDeformerSettings(
                stiffness=float(payload.get("stiffness", 85.0)),
                damping=float(payload.get("damping", 14.0)),
                mass=float(payload.get("mass", 1.0)),
                gravity=tuple(float(value) for value in payload.get("gravity", (0.0, 0.0, 0.0))),
                max_offset=float(payload.get("max_offset", 0.25)),
                substeps=int(payload.get("substeps", 2)),
                space=str(payload.get("space") or "object"),
                follow=float(payload.get("follow", 0.72)),
                axis_weights=tuple(float(value) for value in payload.get("axis_weights", (1.0, 1.0, 1.0))),
                max_velocity=float(payload.get("max_velocity", 8.0)),
                settle_speed=float(payload.get("settle_speed", 0.002)),
                collision_radius=float(payload.get("collision_radius", 0.005)),
                friction=float(payload.get("friction", 0.25)),
                restitution=float(payload.get("restitution", 0.08)),
                quality=str(payload.get("quality") or "realtime"),
            )
            self.push_rig_undo_state(f"Add jiggle after {source_id}")
            jiggle_id = attach_jiggle_deformer(
                self.editable_rig_graph,
                source_id,
                mesh_id or str(getattr(self.mesh, "name", "mesh")),
                influence_map,
                settings=settings,
                deformer_id=str(payload.get("deformer_id") or "") or None,
            )
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} Jiggle")
            self.refresh_scene_outliner()
            return {"deformer_id": jiggle_id, "map_key": key, "message": f"Added paintable jiggle after {source_id}."}
        if command == "deformation.add_secondary_motion_preset":
            from tech_connector.game_engine.deformation import (
                attach_secondary_motion_preset,
                secondary_motion_preset,
            )

            source_id = str(payload.get("skin_id") or payload.get("source_id") or "")
            mesh_id = str(payload.get("mesh_id") or "")
            if not source_id:
                source_id, source_kind, selected_mesh_id = self._selected_skin_or_deformer()
                if source_kind != "skin":
                    raise ValueError("Select a skin cluster for a secondary-motion preset.")
                mesh_id = mesh_id or selected_mesh_id
            preset = secondary_motion_preset(str(payload.get("preset_id") or "soft_tissue"))
            key = str(payload.get("map_key") or f"secondary:{source_id}:{preset.preset_id}")
            influence_map = self.deformation_weight_map(key)
            self.push_rig_undo_state(f"Add {preset.label} to {source_id}")
            identifiers = attach_secondary_motion_preset(
                self.editable_rig_graph, source_id, mesh_id, influence_map, preset.preset_id
            )
            self._select_deformation_paint_target(key, f"{source_id.split('::')[-1]} {preset.label}")
            self.refresh_scene_outliner()
            return {"deformer_ids": identifiers, "preset": preset.to_dict(), "map_key": key,
                    "message": f"Added editable {preset.label} secondary motion to {source_id}."}
        if command == "deformation.paint_influence":
            key = str(payload.get("map_key") or "simulation_drive")
            influence_map = self.deformation_weight_map(key)
            vertices = [(vertex.x, vertex.y, vertex.z) for vertex in self.mesh.vertices]
            changed = influence_map.paint(
                vertices,
                tuple(float(value) for value in payload.get("center", (0.0, 0.0, 0.0))),
                float(payload.get("radius", 0.25)),
                value=float(payload.get("value", 1.0)),
                strength=float(payload.get("strength", 1.0)),
                hardness=float(payload.get("hardness", 0.5)),
                mode=str(payload.get("mode") or "replace"),
            )
            self._sync_deformation_weight_map_contract(key, influence_map)
            self._select_deformation_paint_target(key, str(payload.get("label") or key.replace("_", " ").title()))
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()
            return {"map_key": key, "changed_vertices": changed, "message": f"Painted {key} on {len(changed)} vertices."}
        raise ValueError(f"No TC-native deformation executor is registered for {command}.")

    def _execute_tc_scene_conversion_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Promote one captured bridge scene into a standalone TC-native scene."""
        from tech_connector.game_engine.scene.tc_scene_conversion_service import convert_scene_packets_to_tc

        source_provider = str(payload.get("source_provider") or "maya").strip().lower()
        provider_base = dcc_provider_base_key(source_provider)
        snapshot_key = next(
            (
                key for key in (getattr(self, "_dcc_scene_snapshots", {}) or {})
                if str(key).lower() == source_provider or dcc_provider_base_key(key) == provider_base
            ),
            "",
        )
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(snapshot_key)
        if not isinstance(snapshot, dict):
            raise ValueError(f"Load a {provider_base.title()} scene into {THE_GARDEN_DCC_VIEWER_NAME} before converting it.")
        if provider_base == "maya" and ":" in snapshot_key and not bool(payload.get("use_cached_packets", False)):
            try:
                port = int(snapshot_key.rsplit(":", 1)[-1])
            except ValueError:
                port = 0
            if port:
                return self._start_live_tc_scene_conversion(provider_base, port, {
                    **payload,
                    "scope": "selection" if command.endswith("selection_to_tc") else "scene",
                })
        binding = (getattr(self, "_dcc_deformation_bindings", {}) or {}).get(snapshot_key)
        topology = binding.get("rig_topology") if isinstance(binding, dict) else None
        if provider_base == "maya" and not isinstance(topology, dict):
            raise ValueError("The Maya rig warmup is still running. Wait for 'Skeletal cache ready' and convert again.")

        self.push_viewer_undo_state("Convert scene to TC")
        result = convert_scene_packets_to_tc(
            snapshot,
            rig_topology=topology,
            deformation_binding=binding,
            source_provider=provider_base,
            source_native_id=str(payload.get("source_native_id") or ""),
            scope="selection" if command.endswith("selection_to_tc") else "scene",
            include_animation=bool(payload.get("include_animation", True)),
            include_materials=bool(payload.get("include_materials", True)),
        )
        output_path = str(payload.get("output_path") or "")
        if output_path:
            result.save(output_path)
            self._federated_scene_path = str(Path(output_path).resolve())
        return self._install_tc_scene_conversion_result(result, output_path=output_path)

    def _start_live_tc_scene_conversion(self, provider: str, port: int, payload: dict[str, Any]) -> dict[str, Any]:
        thread = getattr(self, "_tc_scene_conversion_thread", None)
        if thread is not None and thread.isRunning():
            return {"started": False, "message": "A scene conversion is already running."}
        self.push_viewer_undo_state("Convert scene to TC")
        thread = QThread(self)
        worker = TCSceneConversionWorker(provider, int(port), payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_live_tc_scene_conversion_finished)
        worker.progress.connect(self._on_live_tc_scene_conversion_progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_live_tc_scene_conversion_thread)
        thread.finished.connect(thread.deleteLater)
        self._tc_scene_conversion_thread = thread
        self._tc_scene_conversion_worker = worker
        self._resolved_shaded_status = "Converting DCC assets to TC in independent geometry, skeleton, skin, and rig chunks"
        self.update_viewport_status()
        thread.start()
        return {"started": True, "message": self._resolved_shaded_status}

    @Slot(int, str)
    def _on_live_tc_scene_conversion_progress(self, percent: int, description: str) -> None:
        self._resolved_shaded_status = f"TC conversion {int(percent)}%: {description}"
        self.update_viewport_status()

    @Slot(bool, object, str)
    def _on_live_tc_scene_conversion_finished(self, ok: bool, result: object, message: str) -> None:
        if not ok or result is None:
            self._resolved_shaded_status = f"TC scene conversion failed: {message}"
            self.update_viewport_status()
            return
        try:
            self._install_tc_scene_conversion_result(result)
        except Exception as exc:
            self._resolved_shaded_status = f"TC scene conversion install failed: {exc}"
            self.update_viewport_status()

    @Slot()
    def _finish_live_tc_scene_conversion_thread(self) -> None:
        self._tc_scene_conversion_thread = None
        self._tc_scene_conversion_worker = None

    def _detach_tc_scene_conversion_worker(self) -> None:
        thread = getattr(self, "_tc_scene_conversion_thread", None)
        worker = getattr(self, "_tc_scene_conversion_worker", None)
        self._tc_scene_conversion_thread = None
        self._tc_scene_conversion_worker = None
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._on_live_tc_scene_conversion_finished)
            except Exception:
                pass
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(2000)

    def _install_tc_scene_conversion_result(self, result: object, *, output_path: str = "") -> dict[str, Any]:
        """Atomically replace bridge state only after every conversion chunk validates."""
        document = getattr(result, "document")
        scene_snapshot = getattr(result, "scene_snapshot")
        report = getattr(result, "report")
        blobs = getattr(result, "blobs")
        self.editable_rig_graph = document.rig_graph
        self._federated_scene_blobs = dict(blobs)
        self._tc_native_scene_snapshot = scene_snapshot
        self._tc_scene_conversion_report = report
        self._dcc_scene_snapshots = {"tc_native_converted": scene_snapshot}
        self._dcc_snapshot_signatures = {}
        self._loaded_scene_providers = []
        self._dcc_deformation_bindings = {}
        self._dcc_deformation_binding_fingerprints = {}
        self._native_scene_model = None
        self._native_fbx_asset = None
        self.mesh = FBXMeshModel.from_scene_snapshot(scene_snapshot)
        self.sync_gpu_viewport(full=True)
        self.refresh_scene_outliner()
        counts = report.get("counts") or {}
        warning_count = len(report.get("issues") or [])
        message = (
            f"Converted to TC: {counts.get('meshes', 0)} mesh(es), {counts.get('joints', 0)} joints, "
            f"{counts.get('skins', 0)} skin(s), {counts.get('animation_takes', 0)} take(s)"
        )
        if warning_count:
            message += f"; {warning_count} item(s) retained with conversion warnings"
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return {"message": message, "report": report, "output_path": output_path}

    def convert_loaded_dcc_scene_to_tc(self, *, selection: bool = False) -> None:
        """Run the migration command from the Scene menu without adding toolbar clutter."""
        selected = getattr(self, "_selected_scene_proxy", None)
        selected_provider = ""
        selected_native_id = ""
        if selected is not None:
            getter = selected.get if hasattr(selected, "get") else lambda key, default=None: getattr(selected, key, default)
            selected_provider = str(getter("provider_id", getter("provider", "")) or "")
            selected_native_id = str(getter("native_id", "") or "")
        if selection and not selected_provider:
            QMessageBox.information(self, "Convert To TC", "Select a bridged DCC object before converting the selection.")
            return
        provider = selected_provider if selection else next(
            (
                str(key) for key, snapshot in (getattr(self, "_dcc_scene_snapshots", {}) or {}).items()
                if isinstance(snapshot, dict) and str(snapshot.get("conversion_state") or "") != "tc_native"
            ),
            "",
        )
        if not provider:
            QMessageBox.information(self, "Convert To TC", "Load a DCC scene before converting it.")
            return
        try:
            result = self.execute_adaptive_scene_command(
                "scene.convert_selection_to_tc" if selection else "scene.convert_to_tc",
                {
                    "source_provider": provider,
                    "source_native_id": selected_native_id if selection else "",
                    "include_animation": True,
                    "include_materials": True,
                },
            )
            self._resolved_shaded_status = str(result.get("message") or "Scene converted to TC.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Convert To TC Failed", str(exc))

    def create_simulation_preset(self, simulation_type: str, material: str) -> dict[str, Any]:
        result = self._execute_tc_simulation_command(
            "simulation.create_" + ("volume" if simulation_type == "volume" else simulation_type),
            {"material": material, "preset": material},
        )
        self._resolved_shaded_status = str(result.get("message") or "Simulation created.")
        self.update_viewport_status()
        return result

    def create_current_mesh_cloth(self, material: str = "cotton") -> dict[str, Any]:
        return self.create_simulation_preset_from_payload(
            "simulation.create_cloth",
            {"material": material, "use_current_mesh": True, "tear_threshold": 1.8},
        )

    def create_simulation_preset_from_payload(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._execute_tc_simulation_command(command, payload)
        self._resolved_shaded_status = str(result.get("message") or "Simulation created.")
        self.update_viewport_status()
        return result

    def _install_simulation_world(self, world, label: str) -> None:
        from tech_connector.game_engine.runtime.tc_simulation_service import SimulationCache
        from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
        from tech_connector.ui.design_system import set_ui_role

        self.push_viewer_undo_state(f"Create {label} simulation")
        self.simulation_world = world
        quality = str(getattr(getattr(world, "effect_system", None), "quality", "realtime") or "realtime").lower()
        profile = {"low": "mobile", "medium": "realtime", "high": "realtime"}.get(quality, quality)
        if profile not in {"cinematic", "photoreal", "realtime", "mobile", "toony", "stylized", "retro"}:
            profile = "realtime"
        self.simulation_runtime = SimulationRuntimeInstance(
            world, profile=profile, tick_rate=max(1.0, float(self.simulation_frame_rate))
        )
        self.simulation_initial_world = copy.deepcopy(world)
        self.simulation_frame = 1
        self.simulation_cache = SimulationCache(
            frame_rate=self.simulation_frame_rate,
            metadata={"label": label, "unit_linear": "centimeters", "up_axis": self.viewer_coord_up_axis},
        )
        self.simulation_cache.store(world.capture_frame(1))
        if getattr(world, "effect_system", None) is not None:
            if getattr(self, "fx_btn", None) is not None:
                set_ui_role(self.fx_btn, "primary")
                self.fx_btn.setToolTip(
                    f"Active FX: {world.effect_system.name} · {world.effect_system.quality} quality. "
                    "Open for presets and live properties."
                )
            self.viewport_display_source = "compiled"
            self.viewport_shading_mode = "Shader"
            self.show_texture = True
            QTimer.singleShot(0, lambda: self.sync_gpu_viewport(full=False))
        elif getattr(self, "fx_btn", None) is not None:
            set_ui_role(self.fx_btn, "secondary")
            self.fx_btn.setToolTip("Create particle, energy, weather, and world effects, then preview or bake them.")
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def set_simulation_playing(self, playing: bool) -> None:
        self.simulation_playing = bool(playing)
        if self.simulation_playing and self.simulation_world is not None:
            self.simulation_timer.start()
        else:
            self.simulation_timer.stop()
        action = getattr(self, "simulation_play_action", None)
        if action is not None:
            action.setText("Pause Simulation" if self.simulation_playing else "Play Simulation")
            if action.isChecked() != self.simulation_playing:
                action.blockSignals(True)
                action.setChecked(self.simulation_playing)
                action.blockSignals(False)

    def start_effect_bake(self, *, start_frame: int, end_frame: int, frame_rate: float) -> dict[str, Any]:
        if self.simulation_world is None or self.simulation_world.effect_system is None:
            raise ValueError("Create an FX system before baking it.")
        if self._effect_bake_thread is not None and self._effect_bake_thread.isRunning():
            return {"started": False, "message": "An effect bake is already running."}
        worker = EffectBakeWorker(
            self.simulation_world,
            start_frame=int(start_frame),
            end_frame=int(end_frame),
            frame_rate=float(frame_rate),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.on_effect_bake_progress)
        worker.finished.connect(self.on_effect_bake_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.on_effect_bake_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._effect_bake_worker = worker
        self._effect_bake_thread = thread
        self._effect_bake_progress = (0, max(0, int(end_frame) - int(start_frame) + 1), int(start_frame), 0.0)
        self._resolved_shaded_status = f"Effect bake queued: frames {int(start_frame)}-{int(end_frame)}"
        self.update_viewport_status()
        thread.start()
        return {
            "started": True,
            "message": self._resolved_shaded_status,
            "start_frame": int(start_frame),
            "end_frame": int(end_frame),
            "frame_rate": float(frame_rate),
        }

    @Slot(int, int, int, float)
    def on_effect_bake_progress(self, completed: int, total: int, frame: int, frames_per_second: float) -> None:
        self._effect_bake_progress = (int(completed), int(total), int(frame), float(frames_per_second))
        self._resolved_shaded_status = (
            f"Baking FX frame {int(frame)}: {int(completed)}/{int(total)} "
            f"({float(frames_per_second):.1f} fps)"
        )
        self.update_viewport_status()

    @Slot(object, bool, str)
    def on_effect_bake_finished(self, cache: Any, success: bool, message: str) -> None:
        if cache is not None:
            self.simulation_cache = cache
        self._resolved_shaded_status = str(message)
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    @Slot()
    def on_effect_bake_thread_finished(self) -> None:
        self._effect_bake_worker = None
        self._effect_bake_thread = None

    def cancel_effect_bake(self) -> bool:
        worker = self._effect_bake_worker
        if worker is None:
            return False
        worker.cancel()
        self._resolved_shaded_status = "Canceling effect bake..."
        self.update_viewport_status()
        return True

    def step_active_simulation(self) -> dict[str, Any]:
        world = getattr(self, "simulation_world", None)
        if world is None:
            return {"stepped": False, "message": "Create a simulation before stepping."}
        frame_dt = 1.0 / max(1.0, float(self.simulation_frame_rate))
        self._sync_live_simulation_colliders(frame_dt)
        runtime = getattr(self, "simulation_runtime", None)
        if runtime is None or runtime.world is not world:
            from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
            runtime = SimulationRuntimeInstance(world, tick_rate=max(1.0, float(self.simulation_frame_rate)))
            self.simulation_runtime = runtime
        runtime_packet = runtime.advance(frame_dt)
        self.simulation_world = runtime.world
        world = self.simulation_world
        self.simulation_frame += 1
        if self.simulation_cache is not None:
            self.simulation_cache.store(world.capture_frame(self.simulation_frame))
        gpu = getattr(self, "gpu_viewport", None)
        if gpu is not None and gpu.ready:
            gpu.update_effects(world)
        stats = dict(getattr(gpu, "effect_stats", {}) or {}) if gpu is not None else {}
        gpu_summary = (
            f", GPU {float(stats.get('total_upload_ms', 0.0)):.2f} ms / {int(stats.get('draw_calls', 0))} draws"
            if stats else ""
        )
        self._resolved_shaded_status = (
            f"Simulation frame {self.simulation_frame}: {len(world.particles)} particles, "
            f"{sum(len(volume.cells) for volume in world.volumes.values())} active voxels{gpu_summary}"
        )
        self.update_viewport_status()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        return {
            "stepped": True,
            "frame": self.simulation_frame,
            "runtime_tick": runtime_packet.tick,
            "runtime_packet": runtime_packet.to_dict(),
            "message": self._resolved_shaded_status,
        }

    def reset_active_simulation(self) -> None:
        if self.simulation_initial_world is None:
            return
        self.set_simulation_playing(False)
        self.simulation_world = copy.deepcopy(self.simulation_initial_world)
        from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
        self.simulation_runtime = SimulationRuntimeInstance(
            self.simulation_world, tick_rate=max(1.0, float(self.simulation_frame_rate))
        )
        self.simulation_frame = 1
        from tech_connector.game_engine.runtime.tc_simulation_service import SimulationCache
        self.simulation_cache = SimulationCache(frame_rate=self.simulation_frame_rate, metadata={"reset": True})
        self.simulation_cache.store(self.simulation_world.capture_frame(1))
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def add_current_mesh_as_simulation_collider(self) -> dict[str, Any]:
        from tech_connector.game_engine.runtime.tc_simulation_service import SimulationWorld, TriangleMeshCollider

        topology, _colors, _proxies = self._canonical_mesh_topology()
        if self.simulation_world is None:
            self._install_simulation_world(SimulationWorld(), "collision")
        self.simulation_world.mesh_colliders.append(TriangleMeshCollider(
            list(topology.vertices), list(topology.faces),
            source_id="current_mesh", live=True,
        ))
        self.simulation_initial_world = copy.deepcopy(self.simulation_world)
        message = f"Added quad-preserving mesh collider: {len(topology.faces)} polygon faces."
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return {"collider_faces": len(topology.faces), "message": message}

    def _sync_live_simulation_colliders(self, dt: float) -> None:
        world = getattr(self, "simulation_world", None)
        live_colliders = [collider for collider in getattr(world, "mesh_colliders", ()) if collider.live]
        if not live_colliders:
            return
        topology, _colors, _proxies = self._canonical_mesh_topology()
        vertices = list(topology.vertices)
        if not vertices:
            return
        new_center = tuple(sum(point[axis] for point in vertices) / len(vertices) for axis in range(3))
        for collider in live_colliders:
            old_vertices = list(collider.vertices)
            old_center = tuple(sum(point[axis] for point in old_vertices) / len(old_vertices) for axis in range(3)) if old_vertices else new_center
            collider.velocity = tuple((new_center[axis] - old_center[axis]) / max(1.0e-9, dt) for axis in range(3))
            topology_changed = tuple(collider.faces) != tuple(topology.faces)
            collider.vertices = list(vertices)
            collider.faces = list(topology.faces)
            collider.mark_geometry_dirty(topology_changed=topology_changed)

    def add_current_mesh_as_simulation_emitter(self, material: str = "water") -> dict[str, Any]:
        from tech_connector.game_engine.runtime.tc_simulation_service import GeometryEmitter, SimulationWorld

        topology, _colors, _proxies = self._canonical_mesh_topology()
        if self.simulation_world is None:
            self._install_simulation_world(SimulationWorld(), "emitter")
        emitter = GeometryEmitter(
            list(topology.vertices), list(topology.faces), material=str(material), rate=120.0,
        )
        source_map = (getattr(self, "deformation_weight_maps", {}) or {}).get("emission_source")
        if source_map is not None and len(source_map.values) == len(topology.vertices):
            emitter.set_source_weights(source_map.values, name=source_map.name, revision=source_map.revision)
        self.simulation_world.emitters.append(emitter)
        self.simulation_initial_world = copy.deepcopy(self.simulation_world)
        message = f"Added geometry emitter: {len(topology.faces)} polygon faces -> {material}."
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return {"emitter_faces": len(topology.faces), "material": material, "message": message}

    def add_default_simulation_gravity_source(self) -> dict[str, Any]:
        from tech_connector.game_engine.runtime.tc_simulation_service import ForceField, SimulationWorld

        if self.simulation_world is None:
            self._install_simulation_world(SimulationWorld(fields=[]), "gravity")
        self.simulation_world.fields.append(ForceField(
            "gravity_source", vector=(0.05, 0.0, 0.0), center=(0.0, 0.0, 0.0), strength=9.81, radius=0.0,
        ))
        self.simulation_initial_world = copy.deepcopy(self.simulation_world)
        return {"message": "Added inverse-square gravity source at the origin."}

    def show_simulation_transfer_manifest(self) -> None:
        target, ok = QInputDialog.getItem(
            self, "Simulation Transfer", "Destination:", ["Unreal", "Unity", "Houdini", "Maya", "Blender", "Generic"], 0, False
        )
        if not ok:
            return
        try:
            result = self._execute_tc_simulation_command("simulation.build_transfer_manifest", {"target": str(target).lower()})
            QMessageBox.information(self, "Simulation Transfer Manifest", json.dumps(result["manifest"], indent=2))
        except Exception as exc:
            QMessageBox.warning(self, "Simulation Transfer Failed", str(exc))

    def show_simulation_runtime_setup(self) -> None:
        if self.simulation_world is None:
            QMessageBox.information(self, "Runtime Setup", "Create an effect or simulation before configuring its game runtime.")
            return
        from tech_connector.ui.simulation_runtime_setup_dialog import SimulationRuntimeSetupDialog

        dialog = SimulationRuntimeSetupDialog(self.simulation_world, self)
        if dialog.exec() != QDialog.Accepted:
            return
        result = self._execute_tc_engine_command("engine.configure_runtime", dialog.selection())
        self._resolved_shaded_status = str(result.get("message") or "Runtime setup applied.")
        self.update_viewport_status()

    def update_running_game_now(self) -> None:
        try:
            result = self._execute_tc_engine_command("engine.live_update_scene", {})
            self._resolved_shaded_status = str(result.get("message") or "Running game updated.")
        except Exception as exc:
            self._resolved_shaded_status = f"Live game update failed: {exc}"
        self.update_viewport_status()

    def _execute_tc_engine_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command in {"engine.compile_point_runtime_proxy", "engine.compile_virtualized_hard_surface"}:
            thread = getattr(self, "_runtime_geometry_thread", None)
            if thread is not None and thread.isRunning():
                raise RuntimeError("A runtime geometry compilation is already running.")
            output_path = str(payload.get("output_path") or "")
            if not output_path:
                raise ValueError("output_path is required for runtime geometry compilation.")
            topology, _colors, _proxies = self._canonical_mesh_topology()
            kind = "point" if command.endswith("point_runtime_proxy") else "virtual"
            arguments: dict[str, Any] = {
                "vertices": [tuple(float(value) for value in point) for point in topology.vertices],
                "faces": [tuple(int(value) for value in face) for face in topology.faces],
                "output_path": output_path,
            }
            if kind == "point":
                arguments.update({
                    "face_material_ids": payload.get("face_material_ids"),
                    "materials": list(payload.get("materials") or ()),
                    "page_size": int(payload.get("page_size", 512)),
                })
            else:
                arguments.update({
                    "max_vertices": int(payload.get("max_vertices", 64)),
                    "max_triangles": int(payload.get("max_triangles", 126)),
                    "meshlets_per_page": int(payload.get("meshlets_per_page", 32)),
                })
            self._start_runtime_geometry_compile(kind, arguments)
            return {
                "started": True,
                "kind": kind,
                "output_path": output_path,
                "message": f"Compiling {len(topology.faces)} polygon faces into a {kind} runtime package in the background.",
            }
        if command == "engine.generate_mesh_lods":
            from tech_connector.game_engine.runtime.mesh_lod_service import MeshLodLevel, MeshLodRequest

            thread = getattr(self, "_mesh_lod_thread", None)
            if thread is not None and thread.isRunning():
                raise RuntimeError("Mesh LOD generation is already running.")
            native_model = getattr(self, "_native_scene_model", None)
            source_path = str(payload.get("source_path") or getattr(native_model, "source_path", "") or "")
            if not source_path or not Path(source_path).is_file():
                raise ValueError("Import or provide a saved FBX/glTF/USD/Alembic/OBJ/STL source before generating LODs.")
            output_dir = str(payload.get("output_dir") or (Path(source_path).parent / (Path(source_path).stem + "_LODs")))
            raw_levels = payload.get("levels") or (
                {"name": "LOD0", "triangle_ratio": 1.0, "screen_error_px": 0.5},
                {"name": "LOD1", "triangle_ratio": 0.5, "screen_error_px": 1.0},
                {"name": "LOD2", "triangle_ratio": 0.2, "screen_error_px": 2.0},
                {"name": "LOD3", "triangle_ratio": 0.05, "screen_error_px": 4.0},
            )
            request = MeshLodRequest(
                source_path,
                output_dir,
                levels=tuple(MeshLodLevel(**dict(level)) for level in raw_levels),
                include_animation=bool(payload.get("include_animation", False)),
            )
            errors = request.validate()
            if errors:
                raise ValueError("Invalid mesh LOD request: " + "; ".join(errors))
            self._start_mesh_lod_generation(request)
            return {"started": True, "source_path": source_path, "output_dir": output_dir, "message": f"Generating {len(request.levels)} mesh LODs in the background."}
        if command == "engine.audit_capability_maturity":
            from tech_connector.game_engine.integration.adaptive_scene_command_service import ADAPTIVE_SCENE_COMMANDS
            from tech_connector.game_engine.integration.capability_maturity_service import audit_capability_maturity

            audit = audit_capability_maturity(ADAPTIVE_SCENE_COMMANDS.values())
            department = str(payload.get("department") or "").strip().lower()
            maturity = str(payload.get("maturity") or "").strip().lower()
            rows = [
                row for row in audit["capabilities"]
                if (not department or ADAPTIVE_SCENE_COMMANDS[row["capability"]].department == department)
                and (not maturity or row["verified_maturity"] == maturity)
            ]
            return {
                "capability_audit": {**audit, "capabilities": rows, "filtered_count": len(rows)},
                "message": (
                    f"Capability audit: {audit['production_ready']} production-ready, "
                    f"{audit['declaration_gap']} declared implementations still below production qualification."
                ),
            }
        if command == "engine.audit_dcc_hosts":
            from tech_connector.game_engine.integration.dcc_capability_audit_service import audit_dcc_capabilities
            from tech_connector.game_engine.integration.dcc_host_qualification_service import qualification_ledger

            audit = audit_dcc_capabilities()
            ledger = qualification_ledger(payload.get("ledger_path") or None)
            profiles = ledger["profiles"]
            receipts = ledger["receipts"]
            audited_hosts = []
            for row in audit["hosts"]:
                profile = profiles.get(row["host"], {})
                receipt = receipts.get(row["host"])
                audited_hosts.append({
                    **row,
                    "role_profile": profile,
                    "qualification": receipt or {
                        "status": "unrecorded",
                        "live_readback": False,
                        "missing_gates": ["live_identity_readback", "install_recovery_readback"],
                    },
                })
            host = str(payload.get("host") or "").strip().lower()
            department = str(payload.get("department") or "").strip().lower()
            hosts = [row for row in audited_hosts if not host or row["host"] == host]
            if department:
                hosts = [
                    {**row, "departments": [item for item in row["departments"] if item["department"] == department]}
                    for row in hosts
                ]
                hosts = [row for row in hosts if row["departments"]]
            external = [row for row in audit["hosts"] if row["host"] != "tech_connector"]
            return {
                "dcc_host_audit": {
                    **audit,
                    "hosts": hosts,
                    "filtered_count": len(hosts),
                    "qualification_summary": ledger["summary"],
                },
                "message": (
                    f"DCC host audit: {sum(row['status'] in {'translated', 'native'} for row in external)}/"
                    f"{len(external)} external host profiles are structurally operational; live-host qualification is tracked separately."
                ),
            }
        if command == "engine.qualify_dcc_host":
            from tech_connector.game_engine.integration.dcc_host_qualification_service import (
                HOST_ROLE_PROFILES,
                probe_dcc_host,
                store_qualification_receipt,
            )

            host = str(payload.get("host") or "").strip().lower()
            if host not in HOST_ROLE_PROFILES:
                raise ValueError(f"Choose one external DCC host to qualify: {', '.join(HOST_ROLE_PROFILES)}")
            receipt = probe_dcc_host(
                host,
                timeout=max(0.25, min(15.0, float(payload.get("timeout", 3.0)))),
                max_sessions=max(1, min(100, int(payload.get("max_sessions", 16)))),
            )
            ledger = store_qualification_receipt(receipt, payload.get("ledger_path") or None)
            return {
                "dcc_host_qualification": receipt.to_dict(),
                "qualification_summary": ledger["summary"],
                "message": (
                    f"{host} qualification status: {receipt.status}. "
                    f"{len(receipt.responding_sessions)} live session(s) returned identity data; "
                    f"remaining gates: {', '.join(receipt.missing_gates) or 'none'}."
                ),
            }
        if command == "engine.qualify_dcc_source_parity":
            from tech_connector.bridges.session_preferences import preferred_session_port
            from tech_connector.game_engine.integration.dcc_host_qualification_service import (
                HOST_ROLE_PROFILES,
                bridge_for_host,
            )
            from tech_connector.game_engine.integration.dcc_source_parity_qualification_service import (
                qualify_available_dcc_sources,
                qualify_dcc_source_parity,
                store_source_parity_receipt,
            )

            host = str(payload.get("host") or "").strip().lower()
            if bool(payload.get("all_available")):
                batch = qualify_available_dcc_sources(
                    hosts=payload.get("hosts") or None,
                    session_ports=payload.get("session_ports") or None,
                    timeout=max(0.25, min(30.0, float(payload.get("timeout", 5.0)))),
                    latency_budget_ms=max(1.0, float(payload.get("latency_budget_ms", 5000.0))),
                    object_limit=max(1, min(500, int(payload.get("object_limit", 24)))),
                    persist=True,
                    ledger_path=payload.get("source_parity_ledger_path") or None,
                )
                return {
                    "dcc_source_parity_batch": batch,
                    "message": (
                        f"Source parity: {batch['summary']['qualified']} qualified, "
                        f"{batch['summary']['selection_required']} require session selection, "
                        f"{batch['summary']['unavailable']} unavailable, and "
                        f"{batch['summary']['failed']} failed."
                    ),
                }
            if host not in HOST_ROLE_PROFILES:
                raise ValueError(f"Choose one external DCC host to qualify: {', '.join(HOST_ROLE_PROFILES)}")
            bridge = bridge_for_host(host)
            ports = [int(value) for value in bridge.find_ports()]
            requested_port = payload.get("session_port")
            if requested_port in (None, ""):
                preferred = preferred_session_port(host)
                if preferred in ports:
                    requested_port = preferred
                elif len(ports) == 1:
                    requested_port = ports[0]
                elif len(ports) > 1:
                    raise ValueError(f"Multiple {host} sessions are available; select an exact session port.")
                else:
                    raise ConnectionError(f"No live {host} session is available for source-parity qualification.")
            requested_port = int(requested_port)
            if requested_port not in ports:
                raise ConnectionError(f"The selected {host} session on port {requested_port} is not available.")
            receipt = qualify_dcc_source_parity(
                host,
                requested_port,
                bridge=bridge,
                timeout=max(0.25, min(30.0, float(payload.get("timeout", 5.0)))),
                latency_budget_ms=max(1.0, float(payload.get("latency_budget_ms", 5000.0))),
                object_limit=max(1, min(500, int(payload.get("object_limit", 24)))),
            )
            ledger = store_source_parity_receipt(
                receipt, payload.get("source_parity_ledger_path") or None,
            )
            return {
                "dcc_source_parity_qualification": receipt,
                "source_parity_summary": ledger["summary"],
                "message": (
                    f"{host} source-parity status: {receipt['status']} on port {requested_port}; "
                    f"remaining gates: {', '.join(receipt['missing_gates']) or 'none'}."
                ),
            }
        if command == "engine.audit_dcc_workflows":
            from dataclasses import asdict
            from tech_connector.game_engine.integration.dcc_host_qualification_service import qualification_ledger
            from tech_connector.game_engine.integration.dcc_production_workflow_service import (
                PRODUCTION_WORKFLOWS,
                validate_workflow_catalog,
            )
            from tech_connector.game_engine.integration.dcc_release_readiness_service import (
                audit_dcc_release_readiness,
            )
            from tech_connector.game_engine.integration.dcc_source_parity_qualification_service import (
                source_parity_ledger,
            )

            audit = validate_workflow_catalog()
            host = str(payload.get("host") or "").strip().lower()
            workflows = [
                asdict(workflow)
                for workflow in PRODUCTION_WORKFLOWS.values()
                if not host or workflow.host == host
            ]
            ledger = qualification_ledger(payload.get("ledger_path") or None)
            parity_ledger = source_parity_ledger(payload.get("source_parity_ledger_path") or None)
            readiness = audit_dcc_release_readiness(
                qualification_receipts=ledger["receipts"],
                workflow_receipts=getattr(self, "_dcc_workflow_receipts", {}) or {},
                source_parity_receipts=parity_ledger["receipts"],
            )
            if host:
                readiness = {
                    **readiness,
                    "hosts": [row for row in readiness["hosts"] if row["host"] == host],
                }
            return {
                "dcc_workflow_audit": {
                    **audit,
                    "workflows": workflows,
                    "filtered_count": len(workflows),
                    "release_readiness": readiness,
                },
                "message": (
                    f"DCC workflow audit: {audit['workflow_count']} role-specific journeys cover "
                    f"{audit['host_count']} external hosts; {readiness['summary']['release_qualified']} "
                    "currently have stored release-qualification evidence."
                ),
            }
        if command == "engine.run_dcc_workflow":
            from tech_connector.game_engine.integration.dcc_production_workflow_service import (
                PRODUCTION_WORKFLOWS,
                execute_dcc_workflow,
                resolve_workflow_session_port,
            )

            workflow_key = str(payload.get("workflow") or "").strip()
            workflow = PRODUCTION_WORKFLOWS.get(workflow_key)
            if workflow is None:
                raise ValueError(f"Choose a DCC production workflow: {', '.join(PRODUCTION_WORKFLOWS)}")
            workspace = str(payload.get("workspace") or "").strip()
            if not workspace:
                raise ValueError("A workflow workspace is required for portable outputs and receipts.")
            requested_port = payload.get("session_port")
            if requested_port in (None, ""):
                session_key = str(payload.get("session_key") or "").strip()
                if ":" in session_key:
                    try:
                        requested_port = int(session_key.rsplit(":", 1)[1])
                    except (TypeError, ValueError):
                        requested_port = None
            session_port = resolve_workflow_session_port(
                workflow.host,
                int(requested_port) if requested_port not in (None, "") else None,
            )
            receipt = execute_dcc_workflow(
                workflow_key,
                workspace=workspace,
                step_inputs=dict(payload.get("step_inputs") or {}),
                session_port=session_port,
                confirm_mutating=bool(payload.get("confirm_mutating", False)),
                delegated_step_receipts=dict(payload.get("delegated_step_receipts") or {}),
            )
            source_path = str(payload.get("source_path") or "").strip()
            workflow_receipts = getattr(self, "_dcc_workflow_receipts", None)
            if not isinstance(workflow_receipts, dict):
                workflow_receipts = {}
                self._dcc_workflow_receipts = workflow_receipts
            workflow_receipts[workflow_key] = {
                "receipt": receipt.to_dict(),
                "source_path": source_path,
                "session_key": str(payload.get("session_key") or (f"{workflow.host}:{session_port}" if session_port else "")),
                "executable_hint": str(payload.get("executable_hint") or ""),
            }
            return {
                "dcc_workflow_receipt": receipt.to_dict(),
                "message": (
                    f"{workflow.label}: {receipt.status}; {len(receipt.steps)} step(s), "
                    f"{len(receipt.artifacts)} portable artifact receipt(s), session {receipt.session_port or 'automatic'}."
                ),
            }
        if command == "engine.build_runtime_geometry_plan":
            from tech_connector.game_engine.runtime.runtime_geometry_scalability_service import (
                build_runtime_geometry_plan,
                validate_runtime_geometry_plan,
            )

            topology, _colors, _proxies = self._canonical_mesh_topology()
            triangle_count = sum(max(0, len(face) - 2) for face in topology.faces)
            plan = build_runtime_geometry_plan(
                str(payload.get("asset_id") or getattr(self.mesh, "name", "TC_Local_Mesh")),
                triangle_count=int(payload.get("triangle_count", triangle_count)),
                material_features=tuple(payload.get("material_features") or ()),
                deforming=bool(payload.get("deforming", False)),
                collision_required=bool(payload.get("collision_required", True)),
                target_platforms=tuple(payload.get("target_platforms") or ("desktop",)),
            )
            errors = validate_runtime_geometry_plan(plan)
            if errors:
                raise ValueError("Invalid runtime geometry plan: " + "; ".join(errors))
            self.runtime_geometry_plan = copy.deepcopy(plan)
            point_candidate = next(
                item for item in plan["representations"] if item["kind"] == "surfel_point_runtime"
            )["candidate"]
            return {
                "runtime_geometry_plan": plan,
                "message": (
                    f"Planned {plan['inputs']['triangle_count']} triangles for mesh LOD and virtualized geometry; "
                    f"the surfel proxy is {'eligible for benchmarking' if point_candidate else 'held to mesh fallback'}."
                ),
            }
        if command == "engine.configure_runtime":
            if self.simulation_world is None:
                raise ValueError("Create an effect or simulation before configuring its game runtime.")
            from tech_connector.game_engine.runtime.engine_runtime_experience_service import build_engine_runtime_experience_plan
            from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance

            plan = build_engine_runtime_experience_plan(
                self.simulation_world,
                target=str(payload.get("target") or "desktop"),
                goal=str(payload.get("goal") or "balanced"),
                quality=str(payload.get("quality") or "auto"),
                backend=str(payload.get("backend_requested") or payload.get("backend") or "auto"),
                adaptive=bool(payload.get("adaptive", True)),
                tick_rate=int(payload.get("tick_rate") or 60),
            )
            selection = plan["selection"]
            if getattr(self.simulation_world, "effect_system", None) is not None:
                self.simulation_world.effect_system.quality = (
                    "high" if selection["quality"] == "photoreal" else selection["quality"]
                )
            self.simulation_runtime = SimulationRuntimeInstance(
                self.simulation_world,
                profile=selection["quality"],
                backend=selection["backend_requested"],
                tick_rate=selection["tick_rate"],
            )
            self.compiled_simulation_ir = self.simulation_runtime.compiled
            self.engine_runtime_experience_plan = plan
            return {
                "runtime_plan": {key: value for key, value in plan.items() if key != "compiled_ir"},
                "message": plan["summary"],
            }
        if command == "engine.live_update_scene":
            from tech_connector.game_engine.runtime.tc_live_game_sync_service import publish_tcscene_save

            document = self.build_federated_scene_document()
            path = str(payload.get("scene_path") or self._federated_scene_path or "Untitled.tcscene")
            receipt = publish_tcscene_save(document.to_dict(), path, force_full=bool(payload.get("force_full", False)))
            return {"live_update": receipt, "message": receipt["message"]}
        if command == "engine.plan_playtest":
            from tech_connector.game_engine.runtime.tc_live_game_sync_service import build_playtest_iteration_plan, live_game_sessions

            plan = build_playtest_iteration_plan(
                target=str(payload.get("target") or "desktop"),
                session_mode=str(payload.get("session_mode") or "play_in_editor"),
                changed_modes=list(payload.get("changed_modes") or ()),
                session_connected=bool(payload.get("session_connected", live_game_sessions())),
            )
            return {"playtest_plan": plan, "message": plan["explanation"]}
        raise ValueError(f"No TC-native engine executor is registered for {command}.")

    def _start_mesh_lod_generation(self, request: object) -> None:
        thread = QThread(self)
        worker = MeshLodGenerationWorker(request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_mesh_lod_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._finish_mesh_lod_thread(current))
        thread.finished.connect(thread.deleteLater)
        self._mesh_lod_thread = thread
        self._mesh_lod_worker = worker
        thread.start()

    @Slot(bool, object, str)
    def _capture_mesh_lod_result(self, ok: bool, result: object, message: str) -> None:
        if ok and isinstance(result, dict):
            self._mesh_lod_result = dict(result)
            self._resolved_shaded_status = str(message)
        else:
            self._resolved_shaded_status = f"Mesh LOD generation failed: {message}"
            if self.isVisible():
                QMessageBox.warning(self, "Mesh LOD Generation", str(message))
        self.update_viewport_status()

    def _finish_mesh_lod_thread(self, thread: QThread) -> None:
        if self._mesh_lod_thread is thread:
            self._mesh_lod_thread = None
            self._mesh_lod_worker = None

    def _detach_mesh_lod_worker(self) -> None:
        thread = getattr(self, "_mesh_lod_thread", None)
        worker = getattr(self, "_mesh_lod_worker", None)
        self._mesh_lod_thread = None
        self._mesh_lod_worker = None
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._capture_mesh_lod_result)
            except Exception:
                pass
        thread.quit()
        thread.wait(5000)

    def _start_runtime_geometry_compile(self, kind: str, arguments: dict[str, Any]) -> None:
        thread = QThread(self)
        worker = RuntimeGeometryCompileWorker(kind, arguments)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_runtime_geometry_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._finish_runtime_geometry_thread(current))
        thread.finished.connect(thread.deleteLater)
        self._runtime_geometry_thread = thread
        self._runtime_geometry_worker = worker
        thread.start()

    @Slot(bool, str, object, str)
    def _capture_runtime_geometry_result(self, ok: bool, kind: str, result: object, message: str) -> None:
        if ok and isinstance(result, dict):
            self._runtime_geometry_results[str(kind)] = dict(result)
            self._resolved_shaded_status = str(message)
        else:
            self._resolved_shaded_status = f"Runtime geometry compilation failed: {message}"
            if self.isVisible():
                QMessageBox.warning(self, "Runtime Geometry", str(message))
        self.update_viewport_status()

    def _finish_runtime_geometry_thread(self, thread: QThread) -> None:
        if self._runtime_geometry_thread is thread:
            self._runtime_geometry_thread = None
            self._runtime_geometry_worker = None

    def _detach_runtime_geometry_worker(self) -> None:
        thread = getattr(self, "_runtime_geometry_thread", None)
        worker = getattr(self, "_runtime_geometry_worker", None)
        self._runtime_geometry_thread = None
        self._runtime_geometry_worker = None
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._capture_runtime_geometry_result)
            except Exception:
                pass
        thread.quit()
        thread.wait(5000)

    def _execute_tc_world_intelligence_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.integration.world_intelligence_command_service import (
            WORLD_AI_AUTHORING_COMMANDS,
            execute_gameplay_experience_command,
            execute_world_intelligence_command,
        )

        if command.startswith("gameplay."):
            if command in {
                "gameplay.configure_experience",
                "gameplay.set_visual_style",
                "gameplay.update_visual_setting",
            }:
                self.push_viewer_undo_state("Configure game experience")
            self.game_experience_profile, result = execute_gameplay_experience_command(
                self.game_experience_profile,
                command,
                payload,
            )
            return result
        if command in WORLD_AI_AUTHORING_COMMANDS or (
            command == "world_ai.sense" and bool(payload.get("apply", True))
        ) or command == "world_ai.tick_group":
            self.push_viewer_undo_state(str(command))
        return execute_world_intelligence_command(
            self.character_world,
            self.world_intelligence_runtime,
            command,
            payload,
        )

    def _execute_tc_character_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.character_intelligence_service import (
            CharacterMemory,
            CharacterObjective,
            CharacterParameterSpec,
            CharacterProfile,
            CharacterRule,
            CharacterState,
            FactCondition,
            NarrativeBeat,
            RelationshipState,
        )
        from tech_connector.game_engine.runtime.character_brain_service import (
            CharacterAction,
            ModelActionProposal,
            apply_narrative_beat,
            choose_character_action,
            execute_character_action,
            record_character_memory,
            select_narrative_beat,
        )

        world = self.character_world

        def conditions(rows: Any) -> tuple[FactCondition, ...]:
            return tuple(
                FactCondition(
                    str(row.get("path") or ""),
                    str(row.get("operator") or "equals"),
                    row.get("value"),
                )
                for row in (rows or ())
                if isinstance(row, dict)
            )

        def objective(row: dict[str, Any]) -> CharacterObjective:
            return CharacterObjective(
                objective_id=str(row.get("objective_id") or row.get("id") or "objective"),
                description=str(row.get("description") or ""),
                desired_facts=dict(row.get("desired_facts") or {}),
                priority=float(row.get("priority", 0.5)),
                status=str(row.get("status") or "active"),
                deadline=float(row["deadline"]) if row.get("deadline") is not None else None,
                source=str(row.get("source") or "designer"),
                parent_objective=str(row.get("parent_objective") or ""),
                tags=tuple(row.get("tags") or ()),
            )

        character_id = str(payload.get("character_id") or "")
        if command == "characters.create":
            character_id = character_id or str(payload.get("id") or f"character_{len(world.characters) + 1}")
            if character_id in world.characters:
                raise ValueError(f"Character already exists: {character_id}")
            specs = {
                str(name): CharacterParameterSpec(
                    name=str(name),
                    default=float(dict(row).get("default", 0.5)),
                    minimum=float(dict(row).get("minimum", 0.0)),
                    maximum=float(dict(row).get("maximum", 1.0)),
                    description=str(dict(row).get("description") or ""),
                    designer_locked=bool(dict(row).get("designer_locked", False)),
                )
                for name, row in dict(payload.get("parameter_specs") or {}).items()
            }
            self.push_viewer_undo_state(f"Create character {character_id}")
            profile = CharacterProfile(
                character_id=character_id,
                display_name=str(payload.get("display_name") or character_id),
                parameter_specs=specs,
                parameters=dict(payload.get("parameters") or {}),
                traits=dict(payload.get("traits") or {}),
                drives=dict(payload.get("drives") or {}),
                values=dict(payload.get("values") or {}),
                knowledge_tags=set(payload.get("knowledge_tags") or ()),
                faction_tags=set(payload.get("faction_tags") or ()),
                dialogue_style=dict(payload.get("dialogue_style") or {}),
            )
            world.characters[character_id] = CharacterState(profile)
            return {"character": world.characters[character_id].to_dict(), "message": f"Created intelligent character {profile.display_name}."}

        if command == "narrative.set_world_fact":
            path = str(payload.get("path") or "")
            if not path:
                raise ValueError("A world-fact path is required.")
            self.push_viewer_undo_state(f"Set world fact {path}")
            world.world_facts[path] = payload.get("value")
            return {"path": path, "value": payload.get("value"), "message": f"Set world fact {path}."}

        if command == "narrative.add_beat":
            beat_id = str(payload.get("beat_id") or payload.get("id") or f"beat_{len(world.narrative_beats) + 1}")
            self.push_viewer_undo_state(f"Add narrative beat {beat_id}")
            beat = NarrativeBeat(
                beat_id=beat_id,
                description=str(payload.get("description") or ""),
                conditions=conditions(payload.get("conditions")),
                effects=dict(payload.get("effects") or {}),
                objectives=tuple(objective(row) for row in payload.get("objectives") or () if isinstance(row, dict)),
                eligible_characters=tuple(payload.get("eligible_characters") or ()),
                priority=float(payload.get("priority", 0.5)),
                cooldown=float(payload.get("cooldown", 0.0)),
                once=bool(payload.get("once", False)),
                tags=tuple(payload.get("tags") or ()),
            )
            world.narrative_beats[beat_id] = beat
            return {"beat": asdict(beat), "message": f"Added narrative beat {beat_id}."}

        if command == "narrative.select_beat":
            now = float(payload.get("now", 0.0))
            receipt = select_narrative_beat(world, now=now, focus_character=character_id)
            applied = None
            if receipt.chosen_beat and bool(payload.get("apply", False)):
                self.push_viewer_undo_state(f"Apply narrative beat {receipt.chosen_beat}")
                applied = apply_narrative_beat(
                    world,
                    world.narrative_beats[receipt.chosen_beat],
                    receipt,
                    now=now,
                    focus_character=character_id,
                )
            return {"narrative_decision": asdict(receipt), "applied": applied, "message": receipt.explanation}

        character = world.characters.get(character_id)
        if character is None:
            raise KeyError(f"Unknown character: {character_id}")
        if command == "characters.set_parameter":
            name = str(payload.get("name") or "")
            self.push_viewer_undo_state(f"Set {character_id}.{name}")
            value = character.profile.set_parameter(name, float(payload.get("value", 0.0)))
            character.revision += 1
            return {"name": name, "value": value, "message": f"Set {character_id}.{name} to {value:.3f}."}
        if command == "characters.add_rule":
            rule = CharacterRule(
                rule_id=str(payload.get("rule_id") or payload.get("id") or f"rule_{len(character.profile.rules) + 1}"),
                conditions=conditions(payload.get("conditions")),
                action_tags=tuple(payload.get("action_tags") or ()),
                outcome=str(payload.get("outcome") or "deny"),
                utility_delta=float(payload.get("utility_delta", 0.0)),
                priority=int(payload.get("priority", 0)),
                explanation=str(payload.get("explanation") or ""),
            )
            self.push_viewer_undo_state(f"Add rule {rule.rule_id}")
            character.profile.rules.append(rule)
            character.revision += 1
            return {"rule": asdict(rule), "message": f"Added rule {rule.rule_id} to {character_id}."}
        if command == "characters.add_objective":
            result = objective(payload)
            self.push_viewer_undo_state(f"Add objective {result.objective_id}")
            character.objectives.append(result)
            character.revision += 1
            return {"objective": asdict(result), "message": f"Added objective {result.objective_id} to {character_id}."}
        if command == "characters.set_relationship":
            target = str(payload.get("target_character") or "")
            if not target:
                raise ValueError("A target_character is required.")
            clamp = lambda value: max(-1.0, min(1.0, float(value)))
            relation = RelationshipState(
                target,
                trust=clamp(payload.get("trust", 0.0)),
                affection=clamp(payload.get("affection", 0.0)),
                fear=clamp(payload.get("fear", 0.0)),
                respect=clamp(payload.get("respect", 0.0)),
                familiarity=max(0.0, min(1.0, float(payload.get("familiarity", 0.0)))),
                obligations=dict(payload.get("obligations") or {}),
            )
            self.push_viewer_undo_state(f"Set relationship {character_id} to {target}")
            character.relationships[target] = relation
            character.revision += 1
            return {"relationship": asdict(relation), "message": f"Updated {character_id}'s relationship with {target}."}
        if command == "characters.record_memory":
            memory = CharacterMemory(
                memory_id=str(payload.get("memory_id") or payload.get("id") or f"memory_{len(character.memories) + 1}"),
                kind=str(payload.get("kind") or "episodic"),
                subject=str(payload.get("subject") or character_id),
                predicate=str(payload.get("predicate") or "experienced"),
                value=payload.get("value"),
                confidence=float(payload.get("confidence", 1.0)),
                salience=float(payload.get("salience", 0.5)),
                created_at=float(payload.get("created_at", 0.0)),
                expires_at=float(payload["expires_at"]) if payload.get("expires_at") is not None else None,
                source=str(payload.get("source") or "experience"),
                private=bool(payload.get("private", False)),
            )
            self.push_viewer_undo_state(f"Record memory for {character_id}")
            result = record_character_memory(character, memory)
            return {"memory": asdict(result), "message": f"Recorded {result.kind} memory for {character_id}."}
        if command == "characters.choose_action":
            actions = [
                CharacterAction(
                    action_id=str(row.get("action_id") or row.get("id") or "action"),
                    description=str(row.get("description") or ""),
                    tags=tuple(row.get("tags") or ()),
                    preconditions=conditions(row.get("preconditions")),
                    effects=dict(row.get("effects") or {}),
                    base_utility=float(row.get("base_utility", 0.0)),
                    parameter_weights=dict(row.get("parameter_weights") or {}),
                    required_affordance=str(row.get("required_affordance") or ""),
                    target_character=str(row.get("target_character") or ""),
                    cost=float(row.get("cost", 0.0)),
                )
                for row in payload.get("actions") or ()
                if isinstance(row, dict)
            ]
            proposal_data = payload.get("model_proposal")
            proposal = ModelActionProposal(**dict(proposal_data)) if isinstance(proposal_data, dict) else None
            receipt = choose_character_action(
                character,
                world,
                actions,
                available_affordances=payload.get("available_affordances") or (),
                now=float(payload.get("now", 0.0)),
                model_proposal=proposal,
            )
            action_receipt = None
            if receipt.chosen_action and bool(payload.get("execute", False)):
                self.push_viewer_undo_state(f"Execute {character_id}:{receipt.chosen_action}")
                chosen = next(item for item in actions if item.action_id == receipt.chosen_action)
                action_receipt = execute_character_action(character, world, chosen, receipt)
            return {"decision": receipt.to_dict(), "action_receipt": action_receipt, "message": receipt.explanation}
        raise ValueError(f"No TC-native character executor is registered for {command}.")

    def _execute_tc_procedural_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.procedural_biome_service import (
            BiomeDefinition,
            BiomeSpecies,
            generate_noise_heightfield,
        )
        from tech_connector.game_engine.authoring.procedural_generation_service import (
            ProceduralGraph,
            ProceduralGraphCooker,
            attach_procedural_graph,
            create_scatter_graph,
        )
        from tech_connector.game_engine.authoring.procedural_layout_service import GrammarModule, ShapeGrammar
        from tech_connector.game_engine.authoring.procedural_task_graph_service import (
            ProceduralTaskCooker,
            ProceduralTaskGraph,
        )
        from tech_connector.game_engine.integration.procedural_transfer_service import build_procedural_transfer_manifest

        graphs = getattr(self, "_procedural_graphs", None)
        if graphs is None:
            graphs = self._procedural_graphs = {}
        results = getattr(self, "_procedural_results", None)
        if results is None:
            results = self._procedural_results = {}
        task_graphs = getattr(self, "_procedural_task_graphs", None)
        if task_graphs is None:
            task_graphs = self._procedural_task_graphs = {}
        task_results = getattr(self, "_procedural_task_results", None)
        if task_results is None:
            task_results = self._procedural_task_results = {}
        if getattr(self, "_procedural_graph_cooker", None) is None:
            self._procedural_graph_cooker = ProceduralGraphCooker()
        if getattr(self, "_procedural_task_cooker", None) is None:
            self._procedural_task_cooker = ProceduralTaskCooker(max_workers=4)

        def register_graph(graph: ProceduralGraph) -> dict[str, Any]:
            graphs[graph.graph_id] = graph
            self._active_procedural_graph_id = graph.graph_id
            return {
                "graph_id": graph.graph_id,
                "graph": graph.to_dict(),
                "message": f"Created editable procedural graph {graph.graph_id}.",
            }

        def active_graph() -> ProceduralGraph:
            graph_id = str(payload.get("graph_id") or getattr(self, "_active_procedural_graph_id", "") or "")
            graph = graphs.get(graph_id)
            if graph is None:
                raise KeyError("No matching procedural graph is active. Create a graph or provide graph_id.")
            self._active_procedural_graph_id = graph_id
            return graph

        def cook(graph: ProceduralGraph) -> Any:
            result = self._procedural_graph_cooker.cook(graph, output_node=str(payload.get("output_node") or ""))
            results[graph.graph_id] = result
            return result

        if command == "procedural.create_scatter_graph":
            graph = create_scatter_graph(
                assets=payload.get("assets") or ("Instance",),
                count=max(0, min(1_000_000, int(payload.get("count", 100)))),
                bounds_min=tuple(payload.get("bounds_min") or (-10.0, 0.0, -10.0)),
                bounds_max=tuple(payload.get("bounds_max") or (10.0, 0.0, 10.0)),
                seed=int(payload.get("seed", 0)),
                density=float(payload.get("density", 1.0)),
            )
            requested_id = str(payload.get("graph_id") or "").strip()
            if requested_id:
                graph.graph_id = requested_id
            return register_graph(graph)

        if command == "procedural.generate_terrain":
            width = int(payload.get("width", 64))
            depth = int(payload.get("depth", 64))
            if not 2 <= width <= 2048 or not 2 <= depth <= 2048 or width * depth > 4_000_000:
                raise ValueError("Procedural terrain dimensions must be 2-2048 with at most 4,000,000 samples.")
            terrain = generate_noise_heightfield(
                width,
                depth,
                cell_size=float(payload.get("cell_size", 1.0)),
                seed=int(payload.get("seed", 0)),
                amplitude=float(payload.get("amplitude", 10.0)),
                frequency=float(payload.get("frequency", 0.04)),
                octaves=int(payload.get("octaves", 5)),
                lacunarity=float(payload.get("lacunarity", 2.0)),
                gain=float(payload.get("gain", 0.5)),
                origin=tuple(payload.get("origin") or (0.0, 0.0, 0.0)),
            )
            graph = ProceduralGraph(
                name=str(payload.get("name") or "Terrain"),
                graph_id=str(payload.get("graph_id") or f"terrain_{int(payload.get('seed', 0))}"),
                seed=int(payload.get("seed", 0)),
            )
            graph.add_node(
                "terrain",
                "terrain_hydraulic_erosion",
                parameters={
                    "heightfield": terrain.to_dict(),
                    "iterations": max(0, int(payload.get("erosion_iterations", 0))),
                },
            )
            response = register_graph(graph)
            if bool(payload.get("cook", True)):
                response["cook"] = cook(graph).to_dict()
            return response

        if command == "procedural.erode_terrain":
            graph = active_graph()
            previous = results.get(graph.graph_id)
            heightfield = payload.get("heightfield")
            if heightfield is None and previous is not None:
                heightfield = previous.payload.metadata.get("heightfield")
            if heightfield is None:
                for node in reversed(list(graph.nodes.values())):
                    if isinstance(node.parameters.get("heightfield"), dict):
                        heightfield = node.parameters["heightfield"]
                        break
            if not isinstance(heightfield, dict):
                raise ValueError("Terrain erosion requires an active cooked terrain or serialized heightfield.")
            index = 1
            node_id = "erosion"
            while node_id in graph.nodes:
                index += 1
                node_id = f"erosion_{index}"
            graph.add_node(
                node_id,
                "terrain_hydraulic_erosion",
                parameters={
                    "heightfield": heightfield,
                    "iterations": max(0, int(payload.get("iterations", 32))),
                    "rainfall": float(payload.get("rainfall", 0.02)),
                    "evaporation": float(payload.get("evaporation", 0.08)),
                    "flow_rate": float(payload.get("flow_rate", 0.55)),
                    "sediment_capacity": float(payload.get("sediment_capacity", 1.5)),
                    "erosion_rate": float(payload.get("erosion_rate", 0.12)),
                    "deposition_rate": float(payload.get("deposition_rate", 0.18)),
                    "river_threshold": float(payload.get("river_threshold", 0.35)),
                },
            )
            result = cook(graph)
            return {"graph_id": graph.graph_id, "node_id": node_id, "cook": result.to_dict(), "message": "Eroded terrain and retained reusable flow fields."}

        if command == "procedural.generate_biome":
            graph_id = str(payload.get("terrain_graph_id") or getattr(self, "_active_procedural_graph_id", "") or "")
            terrain_result = results.get(graph_id)
            heightfield = payload.get("heightfield")
            if heightfield is None and terrain_result is not None:
                heightfield = terrain_result.payload.metadata.get("heightfield")
            if not isinstance(heightfield, dict):
                raise ValueError("Biome generation requires a cooked terrain graph or serialized heightfield.")
            species_rows = payload.get("species") or ({"asset": "Vegetation"},)
            species = tuple(BiomeSpecies(**dict(row)) if isinstance(row, dict) else BiomeSpecies(str(row)) for row in species_rows)
            biome = BiomeDefinition(
                name=str(payload.get("name") or "Biome"),
                species=species,
                samples_per_cell=max(0, int(payload.get("samples_per_cell", 1))),
                density=float(payload.get("density", 1.0)),
                seed=int(payload.get("seed", 0)),
                metadata=dict(payload.get("metadata") or {}),
            )
            graph = ProceduralGraph(
                name=biome.name,
                graph_id=str(payload.get("graph_id") or f"biome_{biome.seed}"),
                seed=biome.seed,
            )
            graph.add_node("biome", "biome_scatter", parameters={"heightfield": heightfield, "biome": biome.to_dict()})
            response = register_graph(graph)
            response["cook"] = cook(graph).to_dict()
            return response

        if command == "procedural.generate_spline_layout":
            control_points = tuple(tuple(float(axis) for axis in point[:3]) for point in (payload.get("control_points") or ((0, 0, 0), (10, 0, 0))))
            modules_data = payload.get("modules") or ({"symbol": "A", "asset": str(payload.get("asset") or "Module"), "length": float(payload.get("module_length", 1.0))},)
            modules = tuple(GrammarModule(**dict(row)) for row in modules_data)
            grammar = ShapeGrammar(
                axiom=tuple(payload.get("axiom") or (modules[0].symbol,)),
                modules=modules,
                productions=dict(payload.get("productions") or {}),
                seed=int(payload.get("seed", 0)),
                max_depth=int(payload.get("max_depth", 4)),
                max_modules=min(100_000, int(payload.get("max_modules", 10_000))),
                fit=str(payload.get("fit") or "repeat"),
            )
            graph = ProceduralGraph(
                name=str(payload.get("name") or "Spline Layout"),
                graph_id=str(payload.get("graph_id") or f"spline_{grammar.seed}"),
                seed=grammar.seed,
            )
            graph.add_node("layout", "shape_grammar_spline", parameters={"control_points": control_points, "closed": bool(payload.get("closed", False)), "grammar": grammar.to_dict()})
            response = register_graph(graph)
            response["cook"] = cook(graph).to_dict()
            return response

        if command == "procedural.create_mesh_graph":
            graph = ProceduralGraph(
                name=str(payload.get("name") or "Procedural Mesh"),
                graph_id=str(payload.get("graph_id") or "procedural_mesh"),
                seed=int(payload.get("seed", 0)),
            )
            primitive = str(payload.get("primitive") or "cube").lower()
            if primitive == "grid":
                graph.add_node("source", "mesh_grid", parameters={"name": str(payload.get("mesh_name") or "Grid"), "width": float(payload.get("width", 10.0)), "depth": float(payload.get("depth", 10.0)), "columns": int(payload.get("columns", 10)), "rows": int(payload.get("rows", 10))})
            elif primitive == "cube":
                graph.add_node("source", "mesh_cube", parameters={"name": str(payload.get("mesh_name") or "Cube"), "size": tuple(payload.get("size") or (1.0, 1.0, 1.0))})
            else:
                raise ValueError("Procedural mesh graph currently supports cube or grid sources.")
            previous = "source"
            for index, operation in enumerate(payload.get("operations") or (), 1):
                row = dict(operation or {})
                kind = str(row.pop("operation", "")).strip().lower()
                if kind not in {"mesh_transform", "mesh_extrude_faces", "mesh_triangulate"}:
                    raise ValueError(f"Unsupported procedural mesh operation: {kind}")
                node_id = str(row.pop("node_id", "") or f"operation_{index}")
                graph.add_node(node_id, kind, inputs=(previous,), parameters=row)
                previous = node_id
            response = register_graph(graph)
            response["cook"] = cook(graph).to_dict()
            return response

        if command == "procedural.cook_graph":
            graph = active_graph()
            result = cook(graph)
            return {"graph_id": graph.graph_id, "cook": result.to_dict(), "message": f"Cooked {graph.graph_id}; {sum(row.cache_hit for row in result.diagnostics)}/{len(result.diagnostics)} nodes reused cache."}

        if command == "procedural.cook_task_graph":
            graph_data = payload.get("task_graph")
            if isinstance(graph_data, dict):
                task_graph = ProceduralTaskGraph.from_dict(graph_data)
            else:
                task_id = str(payload.get("task_graph_id") or getattr(self, "_active_procedural_task_graph_id", "") or "procedural_tasks")
                task_graph = task_graphs.get(task_id)
                if task_graph is None:
                    task_graph = ProceduralTaskGraph(task_id)
                    task_graph.add_node("work", parameters={"attributes": dict(payload.get("attributes") or {})}, fan_out=max(1, int(payload.get("fan_out", 1))))
            task_graphs[task_graph.graph_id] = task_graph
            self._active_procedural_task_graph_id = task_graph.graph_id
            result = self._procedural_task_cooker.cook(task_graph, initial_attributes=dict(payload.get("initial_attributes") or {}))
            task_results[task_graph.graph_id] = result
            return {
                "task_graph_id": task_graph.graph_id,
                "output_node": result.output_node,
                "work_items": [asdict(item) for item in result.work_items],
                "diagnostics": [asdict(item) for item in result.diagnostics],
                "cache_hits": result.cache_hits,
                "message": f"Cooked {len(result.work_items)} procedural work items.",
            }

        if command == "procedural.attach_to_scene":
            graph = active_graph()
            result = results.get(graph.graph_id)
            if result is None and bool(payload.get("cook", True)):
                result = cook(graph)
            scene = getattr(self, "_procedural_scene_metadata", None)
            if not isinstance(scene, dict):
                scene = self._procedural_scene_metadata = {"metadata": {}}
            entry = attach_procedural_graph(scene, graph, result)
            return {"graph_id": graph.graph_id, "attachment": entry, "message": f"Attached editable graph {graph.graph_id} to the TC scene."}

        if command == "procedural.build_transfer_manifest":
            graph = active_graph()
            result = results.get(graph.graph_id) or cook(graph)
            target = str(payload.get("target") or payload.get("host") or "unreal")
            manifest = build_procedural_transfer_manifest(graph, result, target)
            return {"graph_id": graph.graph_id, "manifest": manifest, "message": f"Built {target} transfer manifest for {graph.graph_id}."}

        raise ValueError(f"Unsupported TC procedural command: {command}")

    def show_physics_joint_editor(self) -> None:
        from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel
        from tech_connector.ui.physics_joint_editor_widget import PhysicsJointEditorWidget

        dialog = getattr(self, "_physics_joint_editor_dialog", None)
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
        model = PhysicsJointEditorModel(self._runtime_world_state)
        editor = PhysicsJointEditorWidget(model)
        editor.changed.connect(self._refresh_physics_joint_visual_guides)
        editor.anchorPickRequested.connect(self._set_physics_joint_anchor_to_view_target)
        dialog = QDialog(self)
        dialog.setWindowTitle("Physics Joint Editor")
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.resize(820, 720)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(editor)
        dialog.finished.connect(lambda _result: setattr(self, "_physics_joint_editor_dialog", None))
        self._physics_joint_editor_model = model
        self._physics_joint_editor_dialog = dialog
        self._refresh_physics_joint_visual_guides()
        dialog.show()

    def _runtime_entity_positions(self) -> dict[str, tuple[float, float, float]]:
        positions: dict[str, tuple[float, float, float]] = {}
        for entity in self._runtime_world_state.get("entities") or ():
            if not isinstance(entity, dict):
                continue
            position = list(dict(entity.get("transform") or {}).get("position") or (0.0, 0.0, 0.0))
            if len(position) == 3:
                positions[str(entity.get("name") or entity.get("id") or "")] = tuple(float(value) for value in position)
        return positions

    def _refresh_physics_joint_visual_guides(self) -> None:
        model = getattr(self, "_physics_joint_editor_model", None)
        world = getattr(self, "simulation_world", None)
        if model is not None and world is not None:
            world.debug_physics_joints = model.visual_guides(self._runtime_entity_positions())
        viewport = getattr(self, "viewport", None)
        if viewport is not None:
            viewport.update()

    def _physics_joint_screen_handles(self, view_w: float, view_h: float) -> list[dict[str, Any]]:
        model = getattr(self, "_physics_joint_editor_model", None)
        camera = getattr(self, "viewport_camera", None)
        if model is None or camera is None:
            return []
        selected = set(model.selected_ids)
        handles: list[dict[str, Any]] = []
        for guide in model.visual_guides(self._runtime_entity_positions()):
            joint_id = str(guide.get("id") or "")
            if selected and joint_id not in selected:
                continue
            first = tuple(float(value) for value in guide["first_anchor"])
            second = tuple(float(value) for value in guide["second_anchor"])
            axis = _vec_normalize(tuple(float(value) for value in guide["axis"]), (1.0, 0.0, 0.0))
            for kind, world_point in (
                ("first_anchor", first),
                ("second_anchor", second),
                ("axis", _vec_add(first, _vec_scale(axis, 0.75))),
            ):
                display = self.shared_local_to_display_local(world_point)
                sx, sy, depth = camera.project_world_to_screen(display, view_w, view_h)
                if depth > camera.near_clip:
                    handles.append({
                        "joint_id": joint_id, "kind": kind, "screen": QPointF(sx, sy),
                        "world": world_point, "depth": depth, "axis": axis,
                    })
        return handles

    def hit_test_physics_joint_handle(
        self, pos: QPointF, view_w: float, view_h: float, radius_px: float = 11.0
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        best_distance = float(radius_px)
        for handle in self._physics_joint_screen_handles(view_w, view_h):
            point = handle["screen"]
            distance = math.hypot(float(pos.x()) - point.x(), float(pos.y()) - point.y())
            if distance <= best_distance:
                best, best_distance = handle, distance
        self._hover_physics_joint_handle = best
        return best

    def begin_physics_joint_handle_drag(self, handle: dict[str, Any], pos: QPointF) -> None:
        model = getattr(self, "_physics_joint_editor_model", None)
        if model is None:
            return
        model.selected_ids = [str(handle["joint_id"])]
        model.begin_interaction()
        self._active_physics_joint_handle = dict(handle)
        self._active_physics_joint_handle["start_screen"] = QPointF(pos)
        self._active_physics_joint_handle["start_world"] = tuple(handle["world"])
        self._active_physics_joint_handle["start_axis"] = tuple(handle["axis"])
        self._refresh_physics_joint_visual_guides()

    def update_physics_joint_handle_drag(self, pos: QPointF, view_w: float, view_h: float) -> None:
        handle = getattr(self, "_active_physics_joint_handle", None)
        model = getattr(self, "_physics_joint_editor_model", None)
        camera = getattr(self, "viewport_camera", None)
        if not handle or model is None or camera is None:
            return
        delta_x = float(pos.x() - handle["start_screen"].x())
        delta_y = float(pos.y() - handle["start_screen"].y())
        depth = max(camera.near_clip, float(handle["depth"]))
        world_per_pixel = 2.0 * depth * math.tan(math.radians(camera.fov_degrees * 0.5)) / max(1.0, view_h)
        _forward, right, up = camera.view_axes()
        display_delta = _vec_add(
            _vec_scale(right, delta_x * world_per_pixel),
            _vec_scale(up, -delta_y * world_per_pixel),
        )
        shared_origin = self.display_local_to_shared_local((0.0, 0.0, 0.0))
        shared_delta_end = self.display_local_to_shared_local(display_delta)
        shared_delta = _vec_sub(shared_delta_end, shared_origin)
        if handle["kind"] == "axis":
            axis = _vec_normalize(_vec_add(handle["start_axis"], _vec_scale(shared_delta, 1.0 / 0.75)), handle["start_axis"])
            model.preview_selected({"axis": list(axis)})
        else:
            world_point = _vec_add(handle["start_world"], shared_delta)
            joint = next(item for item in model.joints if str(item.get("id") or "") == str(handle["joint_id"]))
            body = "first" if handle["kind"] == "first_anchor" else "second"
            entity_name = str(joint.get(body) or "")
            entity_origin = self._runtime_entity_positions().get(entity_name, (0.0, 0.0, 0.0))
            model.preview_selected({handle["kind"]: list(_vec_sub(world_point, entity_origin))})
        self._refresh_physics_joint_visual_guides()

    def end_physics_joint_handle_drag(self, commit: bool = True) -> None:
        model = getattr(self, "_physics_joint_editor_model", None)
        self._active_physics_joint_handle = None
        if model is None:
            return
        model.end_interaction(commit=commit)
        from tech_connector.ui.physics_joint_editor_widget import PhysicsJointEditorWidget
        editor = self._physics_joint_editor_dialog.findChild(PhysicsJointEditorWidget) if self._physics_joint_editor_dialog else None
        if editor is not None:
            editor.refresh()
        self._refresh_physics_joint_visual_guides()

    def _set_physics_joint_anchor_to_view_target(self, joint_id: str, body: str) -> None:
        from tech_connector.ui.physics_joint_editor_widget import PhysicsJointEditorWidget

        model = getattr(self, "_physics_joint_editor_model", None)
        camera = getattr(self, "viewport_camera", None)
        if model is None or camera is None:
            return
        joint = next((item for item in model.joints if str(item.get("id") or "") == joint_id), None)
        if joint is None:
            return
        entity_name = str(joint.get("first" if body == "first" else "second") or "")
        origin = self._runtime_entity_positions().get(entity_name, (0.0, 0.0, 0.0))
        target = tuple(float(value) for value in (camera.target or (0.0, 0.0, 0.0)))
        model.set_anchor(joint_id, body, [target[index] - origin[index] for index in range(3)])
        editor = self._physics_joint_editor_dialog.findChild(PhysicsJointEditorWidget) if self._physics_joint_editor_dialog else None
        if editor is not None:
            editor.refresh()
        self._refresh_physics_joint_visual_guides()

    def _execute_tc_simulation_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.runtime.tc_simulation_service import (
            CurveFlowField,
            ForceField,
            create_breakable_solid_from_geometry,
            create_cloth_from_geometry,
            create_cloth_grid,
            create_fluid_from_geometry,
            create_particle_block,
            create_reformable_dough_from_geometry,
            create_soft_body_from_geometry,
            create_sparse_fire_volume,
        )

        if command == "simulation.create_physics_joint":
            from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel

            model = getattr(self, "_physics_joint_editor_model", None) or PhysicsJointEditorModel(self._runtime_world_state)
            self._physics_joint_editor_model = model
            joint = model.create(
                str(payload.get("id") or f"Joint {len(model.joints) + 1}"),
                str(payload.get("first") or payload.get("body_a") or ""),
                str(payload.get("second") or payload.get("body_b") or ""),
                preset=str(payload.get("preset") or "weld"), settings=dict(payload.get("settings") or {}),
            )
            self._refresh_physics_joint_visual_guides()
            return {"ok": True, "command": command, "joint": copy.deepcopy(joint)}
        if command == "simulation.edit_physics_joints":
            from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel

            model = getattr(self, "_physics_joint_editor_model", None) or PhysicsJointEditorModel(self._runtime_world_state)
            self._physics_joint_editor_model = model
            model.selected_ids = [str(value) for value in payload.get("joint_ids") or ()]
            changed = model.edit_selected(dict(payload.get("changes") or {}))
            self._refresh_physics_joint_visual_guides()
            return {"ok": changed > 0, "command": command, "changed_joint_count": changed}
        if command == "simulation.generate_ragdoll":
            from tech_connector.game_engine.authoring.tc_ragdoll_service import generate_ragdoll

            manifest = generate_ragdoll(
                self.editable_rig_graph, self._runtime_world_state,
                root_joint=str(payload.get("root_joint") or ""), density=float(payload.get("density", 985.0)),
                include_leaf_joints=bool(payload.get("include_leaf_joints", False)),
            )
            self._refresh_physics_joint_visual_guides()
            return {"ok": True, "command": command, "ragdoll": manifest}
        if command == "simulation.build_physics_stress_scene":
            from tech_connector.game_engine.runtime.tc_physics_stress_service import audit_physics_stress_scene, build_physics_stress_scene

            world = build_physics_stress_scene(str(payload.get("scenario") or "chain"), int(payload.get("count", 1000)))
            if bool(payload.get("apply", False)):
                self._runtime_world_state = world
                self._physics_joint_editor_model = None
            return {"ok": True, "command": command, "audit": audit_physics_stress_scene(world), "applied": bool(payload.get("apply", False))}

        if command == "simulation.create_cloth":
            material = str(payload.get("material") or "cotton")
            if payload.get("use_current_mesh"):
                topology, _colors, _proxies = self._canonical_mesh_topology()
                pinned_vertices = [int(value) for value in payload.get("pinned_vertices", ())]
                if not pinned_vertices and topology.vertices:
                    maximum_y = max(point[1] for point in topology.vertices)
                    tolerance = max(1.0e-5, (max(point[1] for point in topology.vertices) - min(point[1] for point in topology.vertices)) * 0.02)
                    candidates = [index for index, point in enumerate(topology.vertices) if maximum_y - point[1] <= tolerance]
                    pinned_vertices = candidates[: max(2, min(8, len(candidates)))]
                world = create_cloth_from_geometry(
                    topology.vertices,
                    topology.faces,
                    material=material,
                    pinned_vertices=pinned_vertices,
                    particle_radius=float(payload.get("particle_radius", 0.02)),
                    tear_threshold=float(payload.get("tear_threshold", 0.0)),
                )
            else:
                world = create_cloth_grid(
                    int(payload.get("columns", 12)), int(payload.get("rows", 12)),
                    spacing=float(payload.get("spacing", 0.08)), material=material,
                )
            self._install_simulation_world(world, material)
            return {"message": f"Created {material} cloth with {len(world.particles)} particles and {len(world.constraints)} constraints."}
        if command == "simulation.add_effect_jiggle":
            if self.simulation_world is None or self.simulation_world.effect_system is None:
                raise ValueError("Create an effect before adding effect jiggle.")
            from tech_connector.game_engine.runtime.tc_effect_system_service import add_effect_jiggle

            emitter_id = str(payload.get("emitter_id") or self.simulation_world.effect_system.emitters[0].emitter_id)
            result = add_effect_jiggle(
                self.simulation_world.effect_system,
                emitter_id,
                stiffness=float(payload.get("stiffness", 35.0)),
                damping=float(payload.get("damping", 8.0)),
                influence=float(payload.get("influence", 1.0)),
                max_offset=float(payload.get("max_offset", 1.0)),
                target=tuple(payload["target"]) if payload.get("target") is not None else None,
            )
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"emitter_id": emitter_id, "module": asdict(result), "message": f"Added jiggle to effect emitter {emitter_id}."}
        if command == "simulation.create_fluid":
            material = str(payload.get("material") or "water")
            dimensions = tuple(int(value) for value in payload.get("dimensions", (4, 4, 4)))
            world = create_particle_block(dimensions, material=material)
            self._install_simulation_world(world, material)
            return {"message": f"Created {material} particle fluid with {len(world.particles)} particles."}
        if command in {"simulation.create_soft_body", "simulation.create_breakable_solid"}:
            topology, _colors, _proxies = self._canonical_mesh_topology()
            material = str(payload.get("material") or ("jello" if command.endswith("soft_body") else "glass"))
            if command == "simulation.create_soft_body":
                world = create_soft_body_from_geometry(
                    topology.vertices, topology.faces, material=material,
                    volume_compliance=float(payload.get("volume_compliance", 2.0e-7)),
                )
            else:
                world = create_breakable_solid_from_geometry(topology.vertices, topology.faces, material=material)
            self._install_simulation_world(world, material)
            return {
                "message": f"Converted current mesh to {material}: {len(world.particles)} particles, "
                           f"{len(world.volume_constraints)} volume constraints.",
                "particle_count": len(world.particles),
            }
        if command == "simulation.fill_geometry_fluid":
            topology, _colors, _proxies = self._canonical_mesh_topology()
            material = str(payload.get("material") or "soup")
            if topology.vertices:
                extents = [
                    max(point[axis] for point in topology.vertices) - min(point[axis] for point in topology.vertices)
                    for axis in range(3)
                ]
                default_spacing = max(0.02, max(extents) / 11.0)
            else:
                default_spacing = 0.08
            world = create_fluid_from_geometry(
                topology.vertices, topology.faces,
                material=material,
                spacing=float(payload.get("spacing", default_spacing)),
                max_particles=int(payload.get("max_particles", 4096)),
            )
            self._install_simulation_world(world, material)
            return {"message": f"Filled current mesh with {len(world.particles)} {material} particles."}
        if command == "simulation.create_reformable_dough":
            topology, _colors, _proxies = self._canonical_mesh_topology()
            extents = [
                max(point[axis] for point in topology.vertices) - min(point[axis] for point in topology.vertices)
                for axis in range(3)
            ] if topology.vertices else [0.8]
            spacing = float(payload.get("spacing", max(0.025, max(extents) / 10.0)))
            material = str(payload.get("material") or "playdoh")
            world = create_reformable_dough_from_geometry(
                topology.vertices, topology.faces,
                spacing=spacing,
                max_particles=int(payload.get("max_particles", 4096)),
                material=material,
            )
            self._install_simulation_world(world, material)
            return {
                "message": f"Created reformable {material}: {len(world.particles)} particles and "
                           f"{len(world.constraints)} plastic bonds.",
                "particle_count": len(world.particles),
                "bond_count": len(world.constraints),
            }
        if command == "simulation.create_volume":
            preset = str(payload.get("preset") or payload.get("material") or "fire")
            world = create_sparse_fire_volume(plasma=preset == "plasma")
            self._install_simulation_world(world, preset)
            return {"message": f"Created sparse {preset} volume."}
        if command == "simulation.create_effect":
            from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world

            preset = str(payload.get("preset") or "sparks")
            world = create_effect_world(
                preset,
                quality=str(payload.get("quality") or "high"),
                seed=int(payload.get("seed", 1)),
            )
            self._install_simulation_world(world, preset)
            return {
                "message": f"Created {world.effect_system.name} with {len(world.effect_system.emitters)} modular emitters.",
                "effect_system": world.effect_system.to_dict(),
            }
        if command == "simulation.set_effect_renderer":
            if self.simulation_world is None or self.simulation_world.effect_system is None:
                raise ValueError("Create an FX system before assigning its particle renderer.")
            from tech_connector.game_engine.runtime.tc_effect_system_service import set_emitter_renderer

            topology, _colors, _proxies = self._canonical_mesh_topology()
            system = self.simulation_world.effect_system
            emitter_id = str(payload.get("emitter_id") or system.emitters[0].emitter_id)
            renderer = set_emitter_renderer(
                system, emitter_id, str(payload.get("renderer_type") or "mesh"),
                asset_id=str(payload.get("asset_id") or getattr(self.mesh, "name", "TC_Local_Mesh")),
                renderer_parameters={
                    "source_vertex_count": len(topology.vertices),
                    "source_face_count": len(topology.faces),
                    "source_vertices": [tuple(point) for point in topology.vertices],
                    "source_faces": [tuple(face) for face in topology.faces],
                    **dict(payload.get("renderer_parameters") or {}),
                },
            )
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"message": f"Emitter {emitter_id} now renders with the current mesh.", "renderer": renderer}
        if command == "simulation.set_effect_parameter":
            if self.simulation_world is None or self.simulation_world.effect_system is None:
                raise ValueError("Create an FX system before editing its parameters.")
            from tech_connector.game_engine.runtime.tc_effect_system_service import set_effect_parameter

            value = set_effect_parameter(
                self.simulation_world.effect_system,
                str(payload.get("path") or ""), payload.get("value"),
            )
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"message": f"Updated live effect parameter {payload.get('path')}.", "value": value}
        if command == "simulation.bake_effect":
            if self.simulation_world is None or self.simulation_world.effect_system is None:
                raise ValueError("Create an FX system before baking it.")
            start_frame = int(payload.get("start_frame", 1))
            end_frame = int(payload.get("end_frame", 120))
            frame_rate = float(payload.get("frame_rate", self.simulation_frame_rate))
            if bool(payload.get("blocking", False)):
                from tech_connector.game_engine.runtime.tc_effect_system_service import bake_effect_system

                cache = bake_effect_system(
                    self.simulation_world,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    frame_rate=frame_rate,
                )
                self.simulation_cache = cache
                return {"message": f"Baked {len(cache.frames)} effect frames.", "cache": cache.to_dict()}
            return self.start_effect_bake(
                start_frame=start_frame,
                end_frame=end_frame,
                frame_rate=frame_rate,
            )
        if command == "simulation.renderer_stats":
            gpu = getattr(self, "gpu_viewport", None)
            stats = {
                "total_rendered": 0,
                "draw_calls": 0,
                "total_upload_ms": 0.0,
                "upload_ema_ms": 0.0,
                **(dict(getattr(gpu, "effect_stats", {}) or {}) if gpu is not None else {}),
            }
            return {
                "message": (
                    f"FX renderer: {int(stats.get('total_rendered', 0))} particles, "
                    f"{int(stats.get('draw_calls', 0))} draw calls, "
                    f"{float(stats.get('total_upload_ms', 0.0)):.2f} ms upload."
                ),
                "stats": stats,
            }
        if command == "simulation.configure_renderer_budget":
            gpu = getattr(self, "gpu_viewport", None)
            if gpu is not None:
                budget = gpu.configure_effect_budget(
                    target_upload_ms=payload.get("target_upload_ms"),
                    particle_budget=payload.get("particle_budget"),
                    mesh_instance_budget=payload.get("mesh_instance_budget"),
                    cull_distance=payload.get("cull_distance"),
                    adaptive=payload.get("adaptive"),
                )
                message = "Updated the live FX renderer budget."
            else:
                budget = dict(self._effect_renderer_budget)
                if payload.get("target_upload_ms") is not None:
                    budget["target_upload_ms"] = max(0.25, min(33.0, float(payload["target_upload_ms"])))
                if payload.get("particle_budget") is not None:
                    budget["particle_budget_per_stream"] = max(100, min(100000, int(payload["particle_budget"])))
                if payload.get("mesh_instance_budget") is not None:
                    budget["mesh_instance_budget"] = max(100, min(250000, int(payload["mesh_instance_budget"])))
                if payload.get("cull_distance") is not None:
                    budget["cull_distance"] = max(0.0, min(100000.0, float(payload["cull_distance"])))
                if payload.get("adaptive") is not None:
                    budget["adaptive"] = bool(payload["adaptive"])
                message = "Stored the FX renderer budget; it will apply when the GPU viewport is available."
            self._effect_renderer_budget = dict(budget)
            return {"message": message, "budget": budget}
        if command == "simulation.create_deformable_surface":
            from tech_connector.game_engine.runtime.tc_deformable_surface_service import DeformableSurface
            from tech_connector.game_engine.runtime.tc_simulation_service import SimulationWorld

            if self.simulation_world is None:
                self._install_simulation_world(SimulationWorld(fields=[]), "reactive surface")
            surface = DeformableSurface(
                material=str(payload.get("material") or "snow"),
                origin=tuple(float(value) for value in payload.get("origin", (-2.0, 0.0, -2.0))),
                cell_size=float(payload.get("cell_size", 0.08)),
                columns=int(payload.get("columns", 50)), rows=int(payload.get("rows", 50)),
            )
            self.simulation_world.deformable_surfaces.append(surface)
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"message": f"Created reactive {surface.material} surface.", "surface": surface.to_dict()}
        if command in {"simulation.apply_footprint", "simulation.apply_projectile"}:
            if self.simulation_world is None or not self.simulation_world.deformable_surfaces:
                raise ValueError("Create a reactive surface before applying contacts.")
            surface = self.simulation_world.deformable_surfaces[0]
            position = tuple(float(value) for value in payload.get("position", (0.0, 0.0, 0.0)))
            if command == "simulation.apply_footprint":
                mark = surface.apply_footprint(
                    position, size=tuple(float(value) for value in payload.get("size", (0.28, 0.12))),
                    depth=float(payload.get("depth", 0.045)), rotation=float(payload.get("rotation", 0.0)),
                    tread=payload.get("tread"),
                )
            else:
                mark = surface.apply_projectile(
                    position, tuple(float(value) for value in payload.get("direction", (0.0, -1.0, 0.0))),
                    energy=float(payload.get("energy", 8.0)), radius=float(payload.get("radius", 0.015)),
                    thickness=float(payload.get("thickness", 0.1)),
                )
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()
            return {"message": f"Applied {mark.kind} to {surface.material}.", "mark": asdict(mark)}
        if command == "simulation.step":
            count = max(1, int(payload.get("frames", 1)))
            result = {}
            for _index in range(count):
                result = self.step_active_simulation()
            return result
        if command == "simulation.add_geometry_collider":
            return self.add_current_mesh_as_simulation_collider()
        if command == "simulation.add_geometry_emitter":
            return self.add_current_mesh_as_simulation_emitter(str(payload.get("material") or "water"))
        if command == "simulation.paint_emission_source":
            topology, _colors, _proxies = self._canonical_mesh_topology()
            influence_map = self.deformation_weight_map("emission_source")
            self.push_viewer_undo_state("Paint emission source")
            changed: list[int] = []
            if payload.get("values") is not None:
                values = [max(0.0, min(1.0, float(value))) for value in payload.get("values", ())]
                if len(values) != len(topology.vertices):
                    raise ValueError("Emission source values must match the current mesh vertex count.")
                changed = [index for index, (old, new) in enumerate(zip(influence_map.values, values)) if abs(old - new) > 1.0e-12]
                if changed:
                    influence_map.values = values
                    influence_map.revision += 1
            elif payload.get("center") is not None:
                changed = influence_map.paint(
                    topology.vertices,
                    tuple(float(value) for value in payload["center"][:3]),
                    float(payload.get("radius", 1.0)),
                    value=float(payload.get("value", 1.0)),
                    strength=float(payload.get("strength", 1.0)),
                    hardness=float(payload.get("hardness", 0.5)),
                    mode=str(payload.get("mode") or "replace"),
                )
            self._sync_deformation_weight_map_contract("emission_source", influence_map)
            self._select_deformation_paint_target("emission_source", "Emission Source")
            return {
                "message": "Emission Source paint mode is active." if not changed else f"Painted emission source on {len(changed)} vertices.",
                "changed_vertices": sorted(set(changed)),
                "map": influence_map.to_dict(),
            }
        if command == "simulation.add_gravity_source":
            if self.simulation_world is None:
                raise ValueError("Create a simulation before adding a custom gravity source.")
            self.simulation_world.fields.append(ForceField(
                "gravity_source",
                vector=(float(payload.get("softening", 0.05)), 0.0, 0.0),
                center=tuple(float(value) for value in payload.get("center", (0.0, 0.0, 0.0))),
                strength=float(payload.get("strength", 9.81)),
                radius=float(payload.get("radius", 0.0)),
            ))
            return {"message": "Added inverse-square gravity source."}
        if command == "simulation.add_curve_flow":
            if self.simulation_world is None:
                raise ValueError("Create a simulation before adding curve flow.")
            points = payload.get("points") or ((-1.2, 0.6, 0.0), (-0.5, 1.0, 0.5), (0.5, 1.0, -0.5), (1.2, 0.6, 0.0))
            curve = CurveFlowField(
                [tuple(float(value) for value in point[:3]) for point in points],
                flow_strength=float(payload.get("flow_strength", 8.0)),
                attraction_strength=float(payload.get("attraction_strength", 12.0)),
                radius=float(payload.get("radius", 1.0)),
                falloff_power=float(payload.get("falloff_power", 1.0)),
                closed=bool(payload.get("closed", False)),
            )
            self.simulation_world.curve_fields.append(curve)
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"message": f"Added curve flow with {len(curve.points)} control points."}
        if command == "simulation.add_temperature_source":
            if self.simulation_world is None:
                raise ValueError("Create a simulation before adding a temperature source.")
            rate = float(payload.get("temperature_rate", 2200.0))
            self.simulation_world.fields.append(ForceField(
                "heat" if rate >= 0.0 else "cold",
                center=tuple(float(value) for value in payload.get("center", (0.0, 0.0, 0.0))),
                strength=rate,
                radius=float(payload.get("radius", 2.0)),
            ))
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            return {"message": f"Added {'heat' if rate >= 0.0 else 'cold'} field at the origin."}
        if command == "simulation.build_transfer_manifest":
            if self.simulation_world is None or self.simulation_cache is None:
                raise ValueError("Create and cache a simulation before building a transfer manifest.")
            from tech_connector.game_engine.runtime.tc_simulation_transfer_service import build_simulation_transfer_manifest

            manifest = build_simulation_transfer_manifest(
                self.simulation_world, self.simulation_cache, str(payload.get("target") or "generic"),
                prefer_live=bool(payload.get("prefer_live", True)),
            ).to_dict()
            return {"manifest": manifest, "message": f"Built {manifest['target']} simulation transfer manifest."}
        if command == "simulation.create_data_channel":
            if self.simulation_world is None or self.simulation_world.effect_system is None:
                raise ValueError("Create an effect system before adding an FX data channel.")
            from tech_connector.game_engine.runtime.tc_fx_data_channel_service import (
                FxChannelField, FxDataChannel, FxDataChannelSchema, impact_data_channel,
            )

            channel_id = str(payload.get("channel_id") or "fx.impacts")
            if payload.get("fields"):
                fields = tuple(FxChannelField(
                    str(item["name"]), str(item["value_type"]), item.get("default"),
                    bool(item.get("required", True)), str(item.get("semantic") or ""),
                ) for item in payload["fields"])
                channel = FxDataChannel(FxDataChannelSchema(
                    channel_id, fields, int(payload.get("capacity", 4096)),
                    str(payload.get("scope") or "world"), int(payload.get("retention_ticks", 2)),
                    str(payload.get("overflow_policy") or "drop_oldest"),
                ))
            else:
                channel = impact_data_channel(channel_id, capacity=int(payload.get("capacity", 8192)))
            self.simulation_world.effect_system.data_channels[channel_id] = channel
            self.simulation_initial_world = copy.deepcopy(self.simulation_world)
            runtime = getattr(self, "simulation_runtime", None)
            if runtime is not None:
                from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world
                runtime.compiled = compile_simulation_world(runtime.world, profile=runtime.profile, backend=runtime.backend)
            return {"channel": channel.to_dict(), "message": f"Created typed FX data channel {channel_id}."}
        if command == "simulation.publish_data_channel":
            runtime = getattr(self, "simulation_runtime", None)
            if runtime is None:
                raise ValueError("Create a running effect before publishing FX data.")
            channel_id = str(payload.get("channel_id") or "fx.impacts")
            tick = int(payload.get("tick", runtime.tick_index + 1))
            queued = runtime.queue_data_channel(channel_id, dict(payload.get("values") or {}), tick=tick)
            return {"channel_id": channel_id, "tick": queued.tick,
                    "message": f"Queued {channel_id} payload for simulation tick {queued.tick}."}
        if command == "simulation.inspect_fx_profiler":
            runtime = getattr(self, "simulation_runtime", None)
            if runtime is None:
                raise ValueError("Create and step a simulation before inspecting its profiler.")
            system = runtime.world.effect_system
            report = {
                "compiled_backend": runtime.compiled.backend.backend_id,
                "execution_backend": runtime.compiled.metadata.get("execution_backend", "reference_cpu"),
                "gpu_resident": bool(runtime.compiled.metadata.get("gpu_resident", False)),
                "last_execution": dict(runtime.compiled.metadata.get("last_execution") or {}),
                "history": list(runtime.compiled.metadata.get("execution_history") or []),
                "data_channels": {key: value.statistics() for key, value in
                                  (getattr(system, "data_channels", {}) or {}).items()},
                "effect_metrics": dict(getattr(system, "performance_metrics", {}) or {}),
            }
            return {"profiler": report,
                    "message": f"{report['execution_backend']} profiler: GPU resident={report['gpu_resident']}."}
        if command in {"simulation.compile_runtime_profile", "simulation.inspect_execution_plan"}:
            if self.simulation_world is None:
                raise ValueError("Create a simulation before compiling a runtime profile.")
            from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world

            profile = str(payload.get("profile") or getattr(getattr(self.simulation_world, "effect_system", None), "quality", "realtime"))
            if profile not in {"cinematic", "photoreal", "realtime", "mobile", "toony", "stylized", "retro"}:
                profile = "realtime"
            if command == "simulation.compile_runtime_profile" or not hasattr(self, "compiled_simulation_ir"):
                self.compiled_simulation_ir = compile_simulation_world(
                    self.simulation_world,
                    profile=profile,
                    backend=str(payload.get("backend") or "auto"),
                )
            compiled = self.compiled_simulation_ir
            summary = {
                "profile": compiled.profile.name,
                "backend": compiled.backend.backend_id,
                "domains": list(compiled.domains),
                "stages": [stage.stage_id for stage in compiled.stages],
                "outputs": list(compiled.outputs),
                "diagnostics": list(compiled.diagnostics),
                "target_frame_ms": compiled.profile.target_frame_ms,
                "particle_budget": compiled.metadata["particle_budget"],
                "execution_backend": compiled.metadata.get("execution_backend", "reference_cpu"),
                "gpu_resident": bool(compiled.metadata.get("gpu_resident", False)),
                "resources": [resource.resource_id for resource in compiled.resources],
                "last_execution": dict(compiled.metadata.get("last_execution") or {}),
            }
            fallback = next((item["message"] for item in compiled.diagnostics if item.get("severity") == "warning"), "")
            return {
                "execution_plan": summary,
                "message": (
                    f"{compiled.profile.name.title()} plan: {compiled.backend.backend_id}, "
                    f"{len(compiled.stages)} stages, {compiled.profile.target_frame_ms:g} ms simulation target."
                    + (f" {fallback}" if fallback else "")
                ),
            }
        raise ValueError(f"No TC-native simulation executor is registered for {command}.")

    def _execute_tc_animation_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.tc_animation_take_service import (
            add_animation_layer,
            create_take,
            set_keyframe,
        )

        self.push_rig_undo_state(command)
        if command == "animation.create_take":
            take_id = create_take(
                self.editable_rig_graph,
                str(payload.get("name") or "Take"),
                start_frame=int(payload.get("start_frame", 1)),
                end_frame=int(payload.get("end_frame", 120)),
                frame_rate=float(payload.get("frame_rate", 24.0)),
                timecode_start=str(payload.get("timecode_start") or "00:00:00:00"),
            )
            self.active_animation_take_id = take_id
            self.refresh_scene_outliner()
            return {"take_id": take_id, "message": f"Created animation take {payload.get('name') or 'Take'}."}

        take_id = str(payload.get("take_id") or self.active_animation_take_id)
        if not take_id:
            take_id = create_take(
                self.editable_rig_graph,
                "Take 001",
                start_frame=int(getattr(self, "_dcc_timeline_frame_start", 1)),
                end_frame=int(getattr(self, "_dcc_timeline_frame_end", 120)),
            )
            self.active_animation_take_id = take_id
        if command == "animation.add_layer":
            layer = add_animation_layer(
                self.editable_rig_graph,
                take_id,
                str(payload.get("name") or "Layer"),
                weight=float(payload.get("weight", 1.0)),
                additive=bool(payload.get("additive", True)),
            )
            self.refresh_scene_outliner()
            return {"take_id": take_id, "layer": layer, "message": f"Added animation layer {layer}."}
        if command != "animation.set_keyframe":
            raise ValueError(f"No TC-native animation executor is registered for {command}.")

        node_ids = [str(value) for value in payload.get("node_ids", ())]
        if payload.get("node_id"):
            node_ids.append(str(payload["node_id"]))
        node_ids = list(dict.fromkeys(node_ids or self.selected_local_rig_node_ids()))
        if not node_ids:
            raise ValueError("Set keyframe requires node_ids or a Viewer rig selection.")
        frame = int(payload.get("frame", getattr(self, "_current_dcc_frame", 1)))
        layer = str(payload.get("layer") or "")
        interpolation = str(payload.get("interpolation") or "auto")
        keyed = []
        explicit_attribute = str(payload.get("attribute") or "")
        for node_id in node_ids:
            node = self.editable_rig_graph.nodes.get(node_id)
            if node is None:
                raise KeyError(f"Unknown animation node: {node_id}")
            if explicit_attribute:
                if "value" not in payload:
                    raise ValueError("An explicit animation attribute requires a value.")
                set_keyframe(
                    self.editable_rig_graph, take_id, node_id, explicit_attribute, frame, float(payload["value"]),
                    layer=layer, interpolation=interpolation,
                )
                keyed.append(f"{node_id}.{explicit_attribute}")
                continue
            attributes = dict(node.get("attributes") or {})
            for base, default in (("translate", (0.0, 0.0, 0.0)), ("rotate", (0.0, 0.0, 0.0)), ("scale", (1.0, 1.0, 1.0))):
                values = attributes.get(base, default)
                if not isinstance(values, (list, tuple)) or len(values) < 3:
                    values = default
                for axis, value in zip("XYZ", values[:3]):
                    attribute = base + axis
                    set_keyframe(
                        self.editable_rig_graph, take_id, node_id, attribute, frame, float(value),
                        layer=layer, interpolation=interpolation,
                    )
                    keyed.append(f"{node_id}.{attribute}")
        self.refresh_scene_outliner()
        return {
            "take_id": take_id,
            "frame": frame,
            "keyed_attributes": keyed,
            "message": f"Set {len(keyed)} keyframe value(s) on frame {frame}.",
        }

    def _canonical_mesh_topology(self):
        from collections import Counter
        from tech_connector.game_engine.authoring.tc_mesh_modeling_service import MeshTopology

        mesh = self.mesh
        vertices = [(vertex.x, vertex.y, vertex.z) for vertex in mesh.vertices]
        quad_faces = list(getattr(mesh, "quad_faces", []) or [])
        triangle_faces = list(getattr(mesh, "faces", []) or [])
        fallback_triangles = Counter()
        for face in quad_faces:
            fallback_triangles[tuple(sorted((face[0], face[1], face[2])))] += 1
            fallback_triangles[tuple(sorted((face[0], face[2], face[3])))] += 1
        unmatched_triangles = []
        unmatched_indices = []
        for index, face in enumerate(triangle_faces):
            key = tuple(sorted(face))
            if fallback_triangles[key] > 0:
                fallback_triangles[key] -= 1
            else:
                unmatched_triangles.append(tuple(face))
                unmatched_indices.append(index)
        polygons = [tuple(face) for face in quad_faces] + unmatched_triangles
        default_color = QColor(getattr(mesh, "proxy_fill_color", QColor(125, 145, 170, 255)))
        quad_colors = list(getattr(mesh, "quad_face_colors", []) or [])
        triangle_colors = list(getattr(mesh, "face_colors", []) or [])
        quad_proxies = list(getattr(mesh, "quad_proxy_indices", []) or [])
        triangle_proxies = list(getattr(mesh, "face_proxy_indices", []) or [])
        colors = [QColor(quad_colors[index]) if index < len(quad_colors) else QColor(default_color) for index in range(len(quad_faces))]
        colors.extend(QColor(triangle_colors[index]) if index < len(triangle_colors) else QColor(default_color) for index in unmatched_indices)
        proxies = [quad_proxies[index] if index < len(quad_proxies) else -1 for index in range(len(quad_faces))]
        proxies.extend(triangle_proxies[index] if index < len(triangle_proxies) else -1 for index in unmatched_indices)
        return MeshTopology.from_data(vertices, polygons), colors, proxies

    def _apply_mesh_edit_result(self, result, source_colors: list[QColor], source_proxies: list[int]) -> None:
        old_vertices = list(self.mesh.vertices)
        vertex_sources = {int(key): int(value) for key, value in dict(result.metadata.get("vertex_sources") or {}).items()}
        vertex_interpolation = dict(result.metadata.get("vertex_interpolation") or {})
        new_vertices = []
        for index, point in enumerate(result.topology.vertices):
            blend = vertex_interpolation.get(str(index))
            if isinstance(blend, dict):
                sources = [int(value) for value in blend.get("sources", ())]
                weights = [float(value) for value in blend.get("weights", ())]
                if sources and len(sources) == len(weights) and all(0 <= value < len(old_vertices) for value in sources):
                    u = sum(old_vertices[source].u * weight for source, weight in zip(sources, weights))
                    v = sum(old_vertices[source].v * weight for source, weight in zip(sources, weights))
                    new_vertices.append(MeshVertex3D(point[0], point[1], point[2], u, v))
                    continue
            source_index = vertex_sources.get(index, index)
            source = old_vertices[source_index] if 0 <= source_index < len(old_vertices) else None
            new_vertices.append(MeshVertex3D(point[0], point[1], point[2], source.u if source else 0.0, source.v if source else 0.0))

        face_sources = list(result.face_sources or range(len(result.topology.faces)))
        polygons = list(result.topology.faces)
        polygon_colors = [
            QColor(source_colors[source]) if 0 <= source < len(source_colors) else QColor(self.mesh.proxy_fill_color)
            for source in face_sources
        ]
        polygon_proxies = [source_proxies[source] if 0 <= source < len(source_proxies) else -1 for source in face_sources]
        self.mesh.vertices = new_vertices
        self.mesh.quad_faces = []
        self.mesh.quad_face_colors = []
        self.mesh.quad_proxy_indices = []
        self.mesh.faces = []
        self.mesh.face_colors = []
        self.mesh.face_proxy_indices = []
        for polygon_index, polygon in enumerate(polygons):
            color = polygon_colors[polygon_index]
            proxy = polygon_proxies[polygon_index]
            if len(polygon) == 4:
                self.mesh.quad_faces.append(tuple(polygon))
                self.mesh.quad_face_colors.append(QColor(color))
                self.mesh.quad_proxy_indices.append(proxy)
            for offset in range(1, len(polygon) - 1):
                self.mesh.faces.append((polygon[0], polygon[offset], polygon[offset + 1]))
                self.mesh.face_colors.append(QColor(color))
                self.mesh.face_proxy_indices.append(proxy)
        self.sync_gpu_viewport(full=True)
        self.refresh_scene_outliner()
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()

    def _execute_tc_modeling_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "modeling.restore_default_pose":
            self.push_viewer_undo_state("Restore default mesh pose")
            try:
                vertex_count = self.mesh.restore_default_pose()
            except Exception:
                self._viewer_undo_stack.pop()
                raise
            self.sync_gpu_viewport(full=True)
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()
            return {
                "operation": command,
                "message": f"Restored the default shape for {vertex_count} vertices.",
                "vertex_count": vertex_count,
                "default_pose_revision": self.mesh.default_pose.revision,
            }
        if command == "modeling.update_default_pose":
            self.push_viewer_undo_state("Update default mesh pose")
            pose = self.mesh.update_default_pose()
            return {
                "operation": command,
                "message": f"Stored the current shape as default for {len(pose.positions)} vertices.",
                "vertex_count": len(pose.positions),
                "default_pose_revision": pose.revision,
            }

        from tech_connector.game_engine.authoring.tc_mesh_modeling_service import (
            bevel_edges,
            bridge_edge_loops,
            delete_faces,
            extrude_faces,
            merge_vertices,
            split_edge_loop,
            triangulate_faces,
        )

        topology, colors, proxies = self._canonical_mesh_topology()
        face_indices = set(int(value) for value in payload.get("face_indices", payload.get("faces", ())))
        vertex_indices = set(int(value) for value in payload.get("vertex_indices", payload.get("vertices", ())))
        if not face_indices:
            face_indices = set(self.selected_mesh_face_indices)
        if not vertex_indices:
            vertex_indices = set(self.selected_mesh_vertex_indices)
        if payload.get("all_faces"):
            face_indices = set(range(len(topology.faces)))
        if command == "modeling.extrude_faces":
            result = extrude_faces(topology, face_indices, distance=float(payload.get("distance", 0.1)))
        elif command == "modeling.delete_faces":
            if not face_indices:
                raise ValueError("Select at least one face before deleting.")
            result = delete_faces(topology, face_indices)
        elif command == "modeling.triangulate_faces":
            if not face_indices and not payload.get("all_faces"):
                raise ValueError("Select faces or request all_faces=True before triangulating.")
            result = triangulate_faces(topology, face_indices)
        elif command == "modeling.merge_vertices":
            result = merge_vertices(topology, vertex_indices, threshold=float(payload.get("threshold", 1.0e-5)))
        elif command == "modeling.bridge_edge_loops":
            result = bridge_edge_loops(topology, payload.get("first_loop", ()), payload.get("second_loop", ()))
        elif command == "modeling.split_edge_loop":
            edge = payload.get("edge") or (next(iter(self.selected_mesh_edges)) if len(self.selected_mesh_edges) == 1 else ())
            result = split_edge_loop(topology, edge, divisions=int(payload.get("divisions", 1)))
        elif command == "modeling.bevel_edges":
            edges = payload.get("edges") or self.selected_mesh_edges
            result = bevel_edges(topology, edges, width=float(payload.get("width", 0.1)))
        else:
            raise ValueError(f"No TC-native modeling executor is registered for {command}.")
        self.push_viewer_undo_state(result.operation)
        self._apply_mesh_edit_result(result, colors, proxies)
        self.selected_mesh_face_indices = set(result.affected_faces or result.created_faces)
        self.selected_mesh_vertex_indices = set(result.created_vertices)
        self.selected_mesh_edges = set()
        return {
            "operation": result.operation,
            "message": f"{result.operation.split('.')[-1].replace('_', ' ').title()} complete: {len(result.topology.vertices)} vertices, {len(result.topology.faces)} polygon faces.",
            "vertex_count": len(result.topology.vertices),
            "face_count": len(result.topology.faces),
            "created_vertices": list(result.created_vertices),
            "created_faces": list(result.created_faces),
            "affected_faces": list(result.affected_faces),
        }

    def preview_skinning_route(self, command_key: str, label: str, extra_payload: dict[str, Any] | None = None) -> None:
        try:
            from tech_connector.game_engine.integration.adaptive_scene_command_service import resolve_adaptive_scene_command

            payload: dict[str, Any] = dict(extra_payload or {})
            if command_key == "skinning.bind_skin":
                payload.setdefault("bind_method", "heat")
                payload["influences"] = ["Root_JNT", "Spine_JNT"]
                payload["max_influences"] = 4
            elif command_key == "skinning.auto_skin":
                payload.setdefault("bind_method", "auto")
                payload.update({"influences": ["Root_JNT", "Spine_JNT"], "max_influences": 4, "falloff": 4.0})
            elif command_key == "skinning.paint_weights":
                payload.update({"influence": "Spine_JNT", "weight": 0.5, "mode": "replace"})
            elif command_key == "skinning.prune_weights":
                payload.update({"threshold": 0.001, "max_influences": 4})
            elif command_key in {"skinning.transfer_weights", "skinning.copy_weights"}:
                payload.setdefault("source_mesh", "SourceMesh")
                payload.setdefault("target_mesh", self._active_scene_command_target_payload().get("native_id") or "TargetMesh")
                payload.setdefault("strategy", "closestPoint")
            elif command_key in {"skinning.import_weights", "skinning.export_weights"}:
                payload.setdefault("path", "")
            route = resolve_adaptive_scene_command(command_key, self._active_scene_command_target_payload(), payload).to_dict()
            self.viewport_status_label.setText(f"{label}: {route['host']} {route['status']} via {route['execution_mode']}.")
            details = [
                f"Command: {route['command']['label']}",
                f"Target: {route['target'].get('provider')} / {route['target'].get('native_id')}",
                f"Route: {route['host']} -> {route['execution_mode']} ({route['status']})",
                f"Callable: {route.get('callable') or 'planned'}",
            ]
            if route.get("required_payload"):
                details.append("Payload: " + json.dumps(route["required_payload"], indent=2))
            QMessageBox.information(self, f"{WHOLE_PICTURE_VIEWER_NAME} Skinning", "\n".join(details))
        except Exception as exc:
            QMessageBox.warning(self, "Skinning Tool Route Failed", str(exc))

    def run_skinning_command_from_ui(self, command: str, payload: dict[str, Any] | None = None) -> None:
        arguments = {**dict(payload or {}), "force_local": True}
        try:
            result = self.execute_adaptive_scene_command(command, arguments)
            self._resolved_shaded_status = str(result.get("message") or f"Executed {command}.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Skinning Command Failed", str(exc))

    def run_surface_constraint_from_ui(self, command: str) -> None:
        try:
            result = self.execute_adaptive_scene_command(command, {"force_local": True})
            self._resolved_shaded_status = str(result.get("message") or "Surface constraint created.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Surface Constraint Failed", str(exc))

    def prompt_create_mechanical_rig(self) -> None:
        node_ids = sorted(str(value) for value in self.editable_rig_graph.nodes)
        if len(node_ids) < 2:
            QMessageBox.warning(self, "Mechanical Rig", "Create at least two TC rig controls or joints first.")
            return
        mode, ok = QInputDialog.getItem(
            self,
            "Mechanical Rig",
            "Relationship:",
            ["gear", "rack_pinion", "pulley", "hinge", "piston", "hydraulic"],
            0,
            False,
        )
        if not ok:
            return
        driver, ok = QInputDialog.getItem(self, "Mechanical Rig", "Driver:", node_ids, 0, False)
        if not ok:
            return
        driven_options = [value for value in node_ids if value != driver]
        driven, ok = QInputDialog.getItem(self, "Mechanical Rig", "Driven:", driven_options, 0, False)
        if not ok:
            return
        payload: dict[str, Any] = {"mode": str(mode), "driver": str(driver), "driven": str(driven), "force_local": True}
        if str(mode) in {"gear", "rack_pinion", "pulley"}:
            ratio, ok = QInputDialog.getDouble(self, "Mechanical Rig", "Ratio:", -1.0 if mode == "gear" else 1.0, -100000.0, 100000.0, 5)
            if not ok or abs(float(ratio)) <= 1.0e-12:
                return
            payload["ratio"] = float(ratio)
        try:
            result = self.execute_adaptive_scene_command("rigging.create_mechanical_ik", payload)
            self._resolved_shaded_status = str(result.get("message") or "Mechanical relationship created.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Mechanical Rig", str(exc))

    def prompt_create_quadruped_leg(self) -> None:
        joint_ids = sorted(str(value) for value in self.editable_rig_graph.joints)
        if len(joint_ids) < 4:
            QMessageBox.warning(self, "Quadruped Leg IK", "Create or import at least four joints first.")
            return
        labels = ("Hip", "Knee", "Hock", "Ankle")
        chain: list[str] = []
        available = list(joint_ids)
        for label in labels:
            joint_id, ok = QInputDialog.getItem(self, "Quadruped Leg IK", f"{label} joint:", available, 0, False)
            if not ok:
                return
            chain.append(str(joint_id))
            available.remove(str(joint_id))
        module, ok = QInputDialog.getText(self, "Quadruped Leg IK", "Module name:", text="quadruped_leg")
        if not ok or not str(module).strip():
            return
        try:
            result = self.execute_adaptive_scene_command(
                "rigging.create_quadruped_leg_ik",
                {"joint_chain": chain, "module": str(module).strip(), "force_local": True},
            )
            self._resolved_shaded_status = str(result.get("message") or "Quadruped leg created.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Quadruped Leg IK", str(exc))

    def prompt_paint_skin_weights(self) -> None:
        try:
            skin_id, source_kind, _mesh_id = self._selected_skin_or_deformer()
            if source_kind != "skin":
                raise ValueError("Select a skin in the Scene Outliner first.")
            skin = self.editable_rig_graph.skins.get(skin_id) or {}
            influences = [str(value) for value in skin.get("joint_ids") or []]
            if not influences:
                raise ValueError("The selected skin has no influences.")
            if not self.selected_mesh_vertex_indices:
                raise ValueError("Select one or more mesh vertices before setting skin weights.")
        except Exception as exc:
            QMessageBox.warning(self, "Paint Skin Weights", str(exc))
            return
        influence, ok = QInputDialog.getItem(self, "Paint Skin Weights", "Influence:", influences, 0, False)
        if not ok:
            return
        weight, ok = QInputDialog.getDouble(self, "Paint Skin Weights", "Weight:", 1.0, 0.0, 1.0, 4)
        if not ok:
            return
        self.run_skinning_command_from_ui("skinning.paint_weights", {
            "skin_id": skin_id,
            "vertex_indices": sorted(self.selected_mesh_vertex_indices),
            "influence": str(influence),
            "weight": float(weight),
        })

    def prompt_export_skin_weights(self) -> None:
        try:
            skin_id, source_kind, mesh_id = self._selected_skin_or_deformer()
            if source_kind != "skin":
                raise ValueError("Select a skin in the Scene Outliner before exporting weights.")
        except Exception as exc:
            QMessageBox.warning(self, "Export Skin Weights", str(exc))
            return
        suggested = str(Path.home() / f"{Path(mesh_id).name or 'skin'}_weights.tcskin")
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Skin Weights",
            suggested,
            "Tech Connector Skin Weights (*.tcskin);;JSON (*.json)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            result = self.execute_adaptive_scene_command(
                "skinning.export_weights",
                {"path": path, "skin_id": skin_id, "force_local": True},
            )
            self._resolved_shaded_status = str(result.get("message") or "Exporting skin weights.")
            self.update_viewport_status()
        except Exception as exc:
            QMessageBox.warning(self, "Export Skin Weights", str(exc))
