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
import uuid
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


class ThreeDMeshPainterViewportMixin05:
    def _push_level_actor_undo(self, label: str) -> None:
        handler = getattr(self, "push_viewer_undo_state", None)
        if callable(handler): handler(label)

    def configure_transform_snapping(
        self, *, translation: float | None = None, rotation: float | None = None,
        scale: float | None = None,
    ) -> dict[str, float]:
        """Configure editor transform snapping; zero disables an individual channel."""
        settings = dict(getattr(self, "_transform_snap_settings", {}) or {})
        settings.setdefault("translation", 0.0); settings.setdefault("rotation", 0.0); settings.setdefault("scale", 0.0)
        for key, value in (("translation", translation), ("rotation", rotation), ("scale", scale)):
            if value is not None: settings[key] = max(0.0, float(value))
        self._transform_snap_settings = settings
        return dict(settings)

    def configure_asset_placement(
        self, *, grid_snap: bool | None = None, grid_size: float | None = None,
        surface_align: bool | None = None,
    ) -> dict[str, Any]:
        settings = dict(getattr(self, "_asset_placement_settings", {}) or {})
        settings.setdefault("grid_snap", False)
        settings.setdefault("grid_size", 0.5)
        settings.setdefault("surface_align", True)
        if grid_snap is not None:
            settings["grid_snap"] = bool(grid_snap)
        if grid_size is not None:
            settings["grid_size"] = max(0.001, float(grid_size))
        if surface_align is not None:
            settings["surface_align"] = bool(surface_align)
        self._asset_placement_settings = settings
        return dict(settings)

    def select_asset_for_authoring(self, path: str, type_id: str, asset_id: str = "") -> bool:
        self._selected_authoring_asset = {
            "path": str(path or ""), "type_id": str(type_id or ""), "asset_id": str(asset_id or ""),
        }
        self._resolved_shaded_status = (
            f"Authoring asset: {Path(path).name}. Drag it from Assets into the viewport to place an instance."
        )
        self.update_viewport_status()
        return True

    def place_asset_from_browser(
        self,
        payload: dict[str, Any],
        screen_position: QPointF | None = None,
        view_width: float = 0.0,
        view_height: float = 0.0,
    ) -> dict[str, Any] | None:
        path = str(payload.get("path") or "")
        type_id = str(payload.get("type_id") or "")
        asset_id = str(payload.get("asset_id") or "")
        if not path or not type_id:
            return None
        selected = getattr(self, "_selected_scene_proxy", None)
        if type_id in {"tc.texture", "tc.video", "tc.image_project"} and selected is not None:
            if not selected.get("materials"):
                selected.materials = [SceneProxyMaterialBinding(name="Dropped Texture")]
            selected.bind_texture_file("base_color", path)
            texture_asset_ids = dict(selected.get("texture_asset_ids") or {})
            texture_asset_ids["base_color"] = asset_id
            selected["texture_asset_ids"] = texture_asset_ids
            self._scene_lifecycle.mark_dirty()
            self.sync_gpu_viewport(full=False)
            self.update_instance_details_panel()
            self._resolved_shaded_status = f"Applied {Path(path).name} to the selected asset."
            self.update_viewport_status()
            return {"action": "assign_texture", "asset_id": asset_id, "path": path}
        if type_id in {"tc.material", "tc.material_instance", "tc.shader_graph"} and selected is not None:
            selected["material_asset_id"] = asset_id
            selected["material_asset_path"] = path
            selected.sync_state = "dirty"
            self._scene_lifecycle.mark_dirty()
            self.update_instance_details_panel()
            self._resolved_shaded_status = f"Assigned {Path(path).name} to the selected asset."
            self.update_viewport_status()
            return {"action": "assign_material", "asset_id": asset_id, "path": path}

        position = self._asset_drop_world_position(screen_position, view_width, view_height)
        entities = self._runtime_world_state.setdefault("entities", [])
        base_name = Path(path).name.split(".", 1)[0] or "Asset"
        instance_name = base_name
        existing_names = {str(item.get("name") or "") for item in entities if isinstance(item, dict)}
        suffix = 2
        while instance_name in existing_names:
            instance_name = f"{base_name}_{suffix}"
            suffix += 1
        entity = {
            "entity_id": uuid.uuid4().hex,
            "name": instance_name,
            "transform": {"position": [float(value) for value in position]},
            "asset_instance": {"asset_id": asset_id, "type_id": type_id, "source": path},
            "components": [{"component_id": uuid.uuid4().hex, "type": "transform", "enabled": True}],
        }
        if type_id in {"tc.static_mesh", "tc.skeletal_mesh", "tc.prefab"}:
            entity["render"] = {"mesh": path, "material": "builtin:default_pbr"}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": type_id.removeprefix("tc."), "enabled": True, "asset_id": asset_id})
            if type_id == "tc.prefab":
                entity["prefab_instance"] = {
                    "source_asset_id": asset_id, "overrides": {}, "override_state": "inherited",
                }
                try:
                    prefab_payload = json.loads(Path(path).read_text(encoding="utf-8"))
                    prefab_properties = dict(prefab_payload.get("properties") or {})
                    entity["prefab_instance"]["entities"] = copy.deepcopy(
                        list(prefab_properties.get("entities") or ())
                    )
                    entity["prefab_instance"]["exposed_properties"] = copy.deepcopy(
                        dict(prefab_properties.get("exposed_properties") or {})
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
                    entity["prefab_instance"]["load_state"] = "fallback"
        elif type_id in {"tc.effect_system", "tc.simulation_profile"}:
            entity["effect"] = {"asset": path, "active": True}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "effect", "enabled": True, "asset_id": asset_id})
        elif type_id == "tc.audio_clip":
            entity["audio_source"] = {"asset": path, "autoplay": False, "spatial": True}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "audio_source", "enabled": True, "asset_id": asset_id})
        elif type_id in {"tc.behavior", "tc.gameplay_graph", "tc.game_ruleset", "tc.input_map"}:
            entity["behavior"] = {"asset": path, "enabled": True}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "behavior", "enabled": True, "asset_id": asset_id})
        else:
            entity["data_asset"] = {"asset": path}
        self._push_level_actor_undo(f"Place {instance_name}")
        entities.append(entity)
        proxy = self._append_asset_placeholder_proxy(entity, position)
        self._selected_scene_proxy = proxy
        self._scene_lifecycle.mark_dirty()
        self.refresh_scene_outliner()
        self.update_instance_details_panel()
        self.sync_gpu_viewport(full=True)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        self._resolved_shaded_status = f"Placed {instance_name} from Assets. Save & Sync to update Kingdom."
        self.update_viewport_status()
        return entity

    def create_level_actor(self, actor_type: str, name: str = "") -> dict[str, Any]:
        """Create a native level actor with engine-ready default components."""
        kind = str(actor_type or "empty").strip().casefold().replace(" ", "_")
        labels = {"empty": "EmptyActor", "point_light": "PointLight", "directional_light": "DirectionalLight", "camera": "CameraActor", "player_start": "PlayerStart", "trigger": "TriggerVolume"}
        entity_id = uuid.uuid4().hex
        entities = self._runtime_world_state.setdefault("entities", [])
        base_name = str(name or labels.get(kind) or kind.title().replace("_", ""))
        existing = {str(item.get("name") or "") for item in entities if isinstance(item, dict)}
        unique_name = base_name; suffix = 2
        while unique_name in existing: unique_name = f"{base_name}_{suffix}"; suffix += 1
        position = tuple(float(value) for value in self.viewport_camera.target)
        entity: dict[str, Any] = {
            "entity_id": entity_id, "name": unique_name,
            "transform": {"position": list(position), "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "asset_instance": {"asset_id": "", "type_id": f"tc.{kind}", "source": f"builtin:{kind}"},
            "components": [{"component_id": uuid.uuid4().hex, "type": "transform", "enabled": True}],
        }
        if kind in {"point_light", "directional_light"}:
            entity["light"] = {"type": kind.removesuffix("_light"), "color": [1.0, 1.0, 1.0], "intensity": 1000.0 if kind == "point_light" else 10.0, "cast_shadows": True}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "light", "enabled": True})
        elif kind == "camera":
            entity["camera"] = {"fov_degrees": 60.0, "near_clip": 10.0, "far_clip": 100000.0}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "camera", "enabled": True})
        elif kind == "player_start":
            entity["spawn_point"] = {"player_index": 0, "enabled": True}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "player_start", "enabled": True})
        elif kind == "trigger":
            entity["collision"] = {"shape": "box", "is_trigger": True, "size": [100.0, 100.0, 100.0]}
            entity["components"].append({"component_id": uuid.uuid4().hex, "type": "trigger", "enabled": True})
        self._push_level_actor_undo(f"Create {unique_name}")
        entities.append(entity); proxy = self._append_asset_placeholder_proxy(entity, position, queue_native=False)
        self._selected_scene_proxy = proxy; self._finish_level_actor_edit(f"Created {unique_name}")
        return entity

    def _runtime_entity_for_proxy(self, proxy: SceneProxyInstance | dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(proxy, (dict, SceneProxyInstance)): return None
        entity_id = str(proxy.get("entity_id") or proxy.get("native_id") or "")
        for entity in self._runtime_world_state.get("entities") or ():
            if isinstance(entity, dict) and str(entity.get("entity_id") or "") == entity_id:
                for component in entity.setdefault("components", []):
                    if isinstance(component, dict) and not component.get("component_id"): component["component_id"] = uuid.uuid4().hex
                return entity
        return None

    def selected_level_actor_proxies(self) -> list[SceneProxyInstance | dict[str, Any]]:
        tree = getattr(self, "scene_outliner", None); result: list[SceneProxyInstance | dict[str, Any]] = []
        for item in tree.selectedItems() if tree is not None else ():
            data = item.data(0, Qt.UserRole) or {}; proxy = data.get("proxy") if isinstance(data, dict) else None
            if isinstance(proxy, (dict, SceneProxyInstance)) and str(proxy.get("provider_id") or "") == "tech_connector" and proxy not in result: result.append(proxy)
        selected = getattr(self, "_selected_scene_proxy", None)
        if not result and isinstance(selected, (dict, SceneProxyInstance)) and str(selected.get("provider_id") or "") == "tech_connector": result.append(selected)
        return result

    def create_actor_folder(self, name: str) -> bool:
        value = str(name or "").replace("\\", "/").strip(" /")
        if not value: return False
        folders = self._runtime_world_state.setdefault("editor_folders", [])
        if value not in folders: self._push_level_actor_undo(f"Create folder {value}"); folders.append(value); folders.sort(); self._finish_level_actor_edit(f"Created actor folder {value}")
        return True

    def move_selected_level_actors_to_folder(self, folder: str) -> int:
        proxies = self.selected_level_actor_proxies(); value = str(folder or "").replace("\\", "/").strip(" /")
        if not proxies: return 0
        self._push_level_actor_undo(f"Move actors to {value or 'root'}"); changed = 0
        if value:
            folders = self._runtime_world_state.setdefault("editor_folders", [])
            if value not in folders: folders.append(value); folders.sort()
        for proxy in proxies:
            entity = self._runtime_entity_for_proxy(proxy)
            if entity is not None: entity["editor_folder"] = value; changed += 1
        self._finish_level_actor_edit(f"Moved {changed} actor(s) to {value or 'root'}"); return changed

    def parent_selected_level_actors(self, parent_entity_id: str) -> int:
        proxies = self.selected_level_actor_proxies(); parent_id = str(parent_entity_id or "")
        selected_ids = {str(proxy.get("entity_id") or "") for proxy in proxies}
        if not proxies or parent_id in selected_ids: return 0
        known = {str(entity.get("entity_id") or "") for entity in self._runtime_world_state.get("entities") or () if isinstance(entity, dict)}
        if parent_id and parent_id not in known: return 0
        self._push_level_actor_undo("Parent level actors"); changed = 0
        for proxy in proxies:
            entity = self._runtime_entity_for_proxy(proxy)
            if entity is not None: entity["parent_entity_id"] = parent_id; changed += 1
        self._finish_level_actor_edit(f"Updated hierarchy for {changed} actor(s)"); return changed

    def transform_selected_level_actors(self, *, translation: tuple[float, float, float] = (0.0, 0.0, 0.0), rotation: tuple[float, float, float] = (0.0, 0.0, 0.0), scale_multiplier: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> int:
        proxies = self.selected_level_actor_proxies()
        if not proxies: return 0
        self._push_level_actor_undo("Transform actor group")
        for proxy in proxies:
            entity = self._runtime_entity_for_proxy(proxy); transform = entity.setdefault("transform", {}) if entity else None
            if transform is None: continue
            position = list(transform.get("position") or (0.0, 0.0, 0.0)); angles = list(transform.get("rotation") or (0.0, 0.0, 0.0)); scale = list(transform.get("scale") or (1.0, 1.0, 1.0))
            new_position = [float(position[i]) + float(translation[i]) for i in range(3)]; transform["position"] = new_position; transform["rotation"] = [float(angles[i]) + float(rotation[i]) for i in range(3)]; transform["scale"] = [float(scale[i]) * float(scale_multiplier[i]) for i in range(3)]
            self._offset_proxy_preview(proxy, tuple(float(value) for value in translation)); local = dict(proxy.get("local_transform") or {}); local.update({"translation": new_position, "rotation": transform["rotation"], "scale": transform["scale"]}); proxy["local_transform"] = local
        self._finish_level_actor_edit(f"Transformed {len(proxies)} actor(s)"); return len(proxies)

    def duplicate_selected_level_actor(self) -> bool:
        source_proxy = getattr(self, "_selected_scene_proxy", None); source = self._runtime_entity_for_proxy(source_proxy)
        if source is None: return False
        self._push_level_actor_undo(f"Duplicate {source.get('name') or 'actor'}")
        duplicate = copy.deepcopy(source); duplicate["entity_id"] = uuid.uuid4().hex
        base_name = str(source.get("name") or "Actor") + "_Copy"; names = {str(item.get("name") or "") for item in self._runtime_world_state.get("entities") or ()}
        duplicate["name"] = base_name; suffix = 2
        while duplicate["name"] in names: duplicate["name"] = f"{base_name}_{suffix}"; suffix += 1
        transform = duplicate.setdefault("transform", {}); position = list(transform.get("position") or (0.0, 0.0, 0.0)); position += [0.0] * (3 - len(position))
        step = float((getattr(self, "_transform_snap_settings", {}) or {}).get("translation", 0.0) or 100.0); position[0] = float(position[0]) + step; transform["position"] = position[:3]
        self._runtime_world_state.setdefault("entities", []).append(duplicate)
        proxy = self._append_asset_placeholder_proxy(duplicate, tuple(float(value) for value in position[:3]))
        self._selected_scene_proxy = proxy; self._finish_level_actor_edit(f"Duplicated {duplicate['name']}")
        return True

    def rename_selected_level_actor(self, name: str) -> bool:
        proxy = getattr(self, "_selected_scene_proxy", None); entity = self._runtime_entity_for_proxy(proxy); value = str(name or "").strip()
        if entity is None or not value: return False
        self._push_level_actor_undo(f"Rename {entity.get('name') or 'actor'}")
        entity["name"] = value; proxy["name"] = value; self._finish_level_actor_edit(f"Renamed actor to {value}")
        return True

    def update_selected_level_actor(self, values: dict[str, Any]) -> bool:
        proxy = getattr(self, "_selected_scene_proxy", None); entity = self._runtime_entity_for_proxy(proxy)
        if entity is None: return False
        self._push_level_actor_undo(f"Edit {entity.get('name') or 'actor'}")
        if str(values.get("name") or "").strip(): entity["name"] = str(values["name"]).strip(); proxy["name"] = entity["name"]
        transform = entity.setdefault("transform", {}); local = dict(proxy.get("local_transform") or {})
        old_position = list(transform.get("position") or proxy.get("center") or (0.0, 0.0, 0.0)); old_position += [0.0] * (3 - len(old_position))
        for key, default in (("position", (0.0, 0.0, 0.0)), ("rotation", (0.0, 0.0, 0.0)), ("scale", (1.0, 1.0, 1.0))):
            raw = list(values.get(key) or transform.get(key) or default); raw += list(default[len(raw):]); transform[key] = [float(value) for value in raw[:3]]; local[key if key != "position" else "translation"] = list(transform[key])
        new_position = transform["position"]; delta = tuple(float(new_position[i]) - float(old_position[i]) for i in range(3))
        if max(abs(value) for value in delta) > 1.0e-9: self._offset_proxy_preview(proxy, delta)
        proxy["local_transform"] = local; proxy["visible"] = bool(values.get("visible", entity.get("visible", True)))
        entity["visible"] = bool(proxy.get("visible", True)); entity["mobility"] = str(values.get("mobility") or entity.get("mobility") or "movable")
        entity["tags"] = [str(tag).strip() for tag in values.get("tags", entity.get("tags", [])) if str(tag).strip()]
        self._finish_level_actor_edit(f"Updated {entity['name']}"); return True

    def add_component_to_selected_level_actor(self, component_type: str) -> dict[str, Any] | None:
        entity = self._runtime_entity_for_proxy(getattr(self, "_selected_scene_proxy", None))
        if entity is None: return None
        kind = str(component_type or "").strip().casefold().replace(" ", "_")
        defaults = {
            "static_mesh": {"mesh_asset_id": "", "materials": []}, "skeletal_mesh": {"mesh_asset_id": "", "skeleton_asset_id": "", "materials": []},
            "camera": {"fov_degrees": 60.0}, "light": {"light_type": "point", "intensity": 1000.0, "color": [1.0, 1.0, 1.0]},
            "collider": {"shape": "box", "is_trigger": False}, "rigid_body": {"mass": 1.0, "kinematic": False},
            "audio_source": {"audio_asset_id": "", "spatial": True}, "behavior": {"behavior_asset_id": "", "enabled": True},
        }
        if kind not in defaults: return None
        self._push_level_actor_undo(f"Add {kind} component")
        component = {"component_id": uuid.uuid4().hex, "type": kind, "enabled": True, **copy.deepcopy(defaults[kind])}
        entity.setdefault("components", []).append(component); self._finish_level_actor_edit(f"Added {kind.replace('_', ' ')} component"); return component

    def remove_component_from_selected_level_actor(self, component_id: str) -> bool:
        entity = self._runtime_entity_for_proxy(getattr(self, "_selected_scene_proxy", None))
        if entity is None: return False
        components = list(entity.get("components") or []); target = next((item for item in components if str(item.get("component_id") or "") == str(component_id)), None)
        if target is None or str(target.get("type") or "") == "transform": return False
        self._push_level_actor_undo(f"Remove {target.get('type') or 'component'}")
        entity["components"] = [item for item in components if item is not target]; self._finish_level_actor_edit(f"Removed {target.get('type') or 'component'} component"); return True

    def update_component_on_selected_level_actor(self, component_id: str, properties: dict[str, Any]) -> bool:
        entity = self._runtime_entity_for_proxy(getattr(self, "_selected_scene_proxy", None))
        if entity is None: return False
        component = next((item for item in entity.get("components") or () if str(item.get("component_id") or "") == str(component_id)), None)
        if component is None: return False
        self._push_level_actor_undo(f"Edit {component.get('type') or 'component'}")
        for key, value in dict(properties or {}).items():
            if key not in {"component_id", "type"}: component[str(key)] = copy.deepcopy(value)
        self._finish_level_actor_edit(f"Updated {str(component.get('type') or 'component').replace('_', ' ')} component"); return True

    def set_prefab_override_on_selected_level_actor(self, path: str, value: Any) -> bool:
        entity = self._runtime_entity_for_proxy(getattr(self, "_selected_scene_proxy", None)); key = str(path or "").strip()
        instance = entity.get("prefab_instance") if entity else None
        if not isinstance(instance, dict) or not key: return False
        self._push_level_actor_undo(f"Override Prefab {key}"); instance.setdefault("overrides", {})[key] = copy.deepcopy(value); instance["override_state"] = "overridden"; self._finish_level_actor_edit(f"Overrode Prefab property {key}"); return True

    def remove_prefab_override_from_selected_level_actor(self, path: str) -> bool:
        entity = self._runtime_entity_for_proxy(getattr(self, "_selected_scene_proxy", None)); instance = entity.get("prefab_instance") if entity else None; key = str(path or "")
        if not isinstance(instance, dict) or key not in dict(instance.get("overrides") or {}): return False
        self._push_level_actor_undo(f"Revert Prefab {key}"); instance["overrides"].pop(key, None); instance["override_state"] = "overridden" if instance["overrides"] else "inherited"; self._finish_level_actor_edit(f"Reverted Prefab property {key}"); return True

    def delete_selected_level_actor(self) -> bool:
        proxy = getattr(self, "_selected_scene_proxy", None); entity = self._runtime_entity_for_proxy(proxy)
        if entity is None: return False
        self._push_level_actor_undo(f"Delete {entity.get('name') or 'actor'}")
        self._runtime_world_state["entities"] = [item for item in self._runtime_world_state.get("entities") or () if item is not entity]
        proxy["visible"] = False; proxy["deleted"] = True; self._selected_scene_proxy = None
        self._finish_level_actor_edit(f"Deleted {entity.get('name') or 'actor'}")
        return True

    def _finish_level_actor_edit(self, message: str) -> None:
        self._scene_lifecycle.mark_dirty(); self.refresh_scene_outliner(); self.update_instance_details_panel(); self.sync_gpu_viewport(full=True)
        if getattr(self, "canvas", None) is not None: self.canvas.update()
        self._resolved_shaded_status = str(message); self.update_viewport_status()

    def _asset_drop_world_position(
        self,
        screen_position: QPointF | None,
        view_width: float,
        view_height: float,
    ) -> tuple[float, float, float]:
        camera = self.viewport_camera
        target = tuple(float(value) for value in camera.target)
        if screen_position is None or view_width <= 1.0 or view_height <= 1.0:
            return target
        _forward, right, up = camera.view_axes()
        nx = (float(screen_position.x()) / view_width - 0.5) * 2.0
        ny = (float(screen_position.y()) / view_height - 0.5) * 2.0
        half_height = camera.distance * math.tan(math.radians(camera.fov_degrees * 0.5))
        half_width = half_height * (view_width / view_height)
        position = _vec_add(target, _vec_add(_vec_scale(right, nx * half_width), _vec_scale(up, -ny * half_height)))
        settings = self.configure_asset_placement()
        if settings["grid_snap"]:
            step = float(settings["grid_size"])
            position = tuple(round(value / step) * step for value in position)
        return position

    def _append_asset_placeholder_proxy(
        self,
        entity: dict[str, Any],
        position: tuple[float, float, float],
        *,
        preview_model: FBXMeshModel | None = None,
        queue_native: bool = True,
    ) -> SceneProxyInstance:
        asset = dict(entity["asset_instance"]); entity_id = str(entity.get("entity_id") or uuid.uuid4().hex); entity["entity_id"] = entity_id
        type_id = str(asset.get("type_id") or "")
        source_path = Path(str(asset.get("source") or ""))
        preview = preview_model
        preview_error = ""
        if preview is None and type_id in {"tc.static_mesh", "tc.skeletal_mesh"} and source_path.suffix.casefold() == ".obj":
            try:
                preview = FBXMeshModel.from_obj(str(source_path))
            except (OSError, ValueError, IndexError) as exc:
                preview_error = str(exc)
        placeholder = preview or DCCProceduralPrimitiveFactory.create_cube_primitive(size=1.5)
        topology_state = "asset_preview" if preview is not None else "asset_placeholder"
        asset["preview_state"] = "native" if preview is not None else "fallback"
        if preview_error:
            asset["preview_error"] = preview_error
        entity["asset_instance"] = asset
        vertex_start = len(self.mesh.vertices)
        face_start = len(self.mesh.faces)
        quad_start = len(self.mesh.quad_faces)
        for vertex in placeholder.vertices:
            self.mesh.vertices.append(
                MeshVertex3D(vertex.x + position[0], vertex.y + position[1], vertex.z + position[2], vertex.u, vertex.v)
            )
        self.mesh.faces.extend((a + vertex_start, b + vertex_start, c + vertex_start) for a, b, c in placeholder.faces)
        self.mesh.quad_faces.extend(
            (a + vertex_start, b + vertex_start, c + vertex_start, d + vertex_start)
            for a, b, c, d in placeholder.quad_faces
        )
        colors = {
            "tc.effect_system": QColor("#56e0e0"), "tc.simulation_profile": QColor("#4dd5c7"),
            "tc.audio_clip": QColor("#ff83b7"), "tc.behavior": QColor("#6fb8ff"),
            "tc.gameplay_graph": QColor("#719cff"), "tc.prefab": QColor("#6ed6c2"),
        }
        color = colors.get(type_id, QColor("#7dc4ff"))
        source_face_colors = list(getattr(placeholder, "face_colors", ()) or ())
        source_quad_colors = list(getattr(placeholder, "quad_face_colors", ()) or ())
        self.mesh.face_colors.extend(
            QColor(source_face_colors[index]) if index < len(source_face_colors) else QColor(color)
            for index, _face in enumerate(placeholder.faces)
        )
        self.mesh.quad_face_colors.extend(
            QColor(source_quad_colors[index]) if index < len(source_quad_colors) else QColor(color)
            for index, _face in enumerate(placeholder.quad_faces)
        )
        proxy_index = len(self.mesh.scene_proxy_objects)
        self.mesh.face_proxy_indices.extend(proxy_index for _ in placeholder.faces)
        self.mesh.quad_proxy_indices.extend(proxy_index for _ in placeholder.quad_faces)
        placed_vertices = self.mesh.vertices[vertex_start:]
        min_x = min((vertex.x for vertex in placed_vertices), default=position[0] - 0.75)
        min_y = min((vertex.y for vertex in placed_vertices), default=position[1] - 0.75)
        min_z = min((vertex.z for vertex in placed_vertices), default=position[2] - 0.75)
        max_x = max((vertex.x for vertex in placed_vertices), default=position[0] + 0.75)
        max_y = max((vertex.y for vertex in placed_vertices), default=position[1] + 0.75)
        max_z = max((vertex.z for vertex in placed_vertices), default=position[2] + 0.75)
        proxy = SceneProxyInstance(
            index=proxy_index,
            provider_id="tech_connector",
            native_id=entity_id,
            name=str(entity["name"]),
            object_type=type_id.removeprefix("tc."),
            representation="mesh",
            center=position,
            source_bbox=(min_x, min_y, min_z, max_x, max_y, max_z),
            mesh_data=SceneProxyMeshData(
                vertex_start=vertex_start, vertex_count=len(placeholder.vertices),
                face_start=face_start, face_count=len(placeholder.faces),
                quad_start=quad_start, quad_count=len(placeholder.quad_faces),
                has_uvs=True, source_vertex_count=len(placeholder.vertices),
                source_vertex_indices=list(range(len(placeholder.vertices))), topology_state=topology_state,
            ),
            material_color=QColor(color), fill_color=QColor(color),
            source_transform={"translation": list(position), "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            local_transform={"translation": list(position), "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            source_signature=json.dumps(asset, sort_keys=True),
            source_key=f"entity:{entity_id}",
            visible=bool(entity.get("visible", True)),
        )
        proxy["entity_id"] = entity_id
        proxy["asset_id"] = str(asset.get("asset_id") or "")
        proxy["asset_path"] = str(asset.get("source") or "")
        self.mesh.scene_proxy_objects.append(proxy)
        self.mesh.update_default_pose()
        if (
            queue_native and preview is None
            and type_id in {"tc.static_mesh", "tc.skeletal_mesh"}
            and source_path.suffix.casefold() in {".fbx", ".gltf", ".glb", ".stl", ".usd", ".usda", ".usdc", ".usdz", ".abc"}
        ):
            self._queue_native_asset_preview(entity, position, proxy)
        return proxy

    def _queue_native_asset_preview(
        self, entity: dict[str, Any], position: tuple[float, float, float], placeholder_proxy: SceneProxyInstance,
    ) -> bool:
        from tech_connector.game_engine.scene.native_fbx_service import native_scene_import_capabilities

        if not isinstance(self, QObject):
            entity["asset_instance"]["preview_state"] = "fallback_noninteractive_host"
            return False
        source = str(entity.get("asset_instance", {}).get("source") or "")
        extension = Path(source).suffix.casefold()
        capability = dict((native_scene_import_capabilities().get("formats") or {}).get(extension) or {})
        if not capability.get("available"):
            entity["asset_instance"]["preview_state"] = "fallback_backend_unavailable"
            return False
        thread = QThread(self)
        worker = NativeFbxImportWorker(source)
        worker.moveToThread(thread)
        jobs = getattr(self, "_asset_preview_import_jobs", None)
        if not isinstance(jobs, list):
            jobs = []
            self._asset_preview_import_jobs = jobs
        job = {"thread": thread, "worker": worker, "asset_id": entity["asset_instance"].get("asset_id")}
        jobs.append(job)
        entity["asset_instance"]["preview_state"] = "converting"
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ok, asset, message, current=job, placed=entity, at=position, old=placeholder_proxy:
            self._complete_native_asset_preview(current, placed, at, old, ok, asset, message)
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._resolved_shaded_status = f"Converting {Path(source).name} for an in-place Garden preview…"
        self.update_viewport_status()
        thread.start()
        return True

    def _complete_native_asset_preview(
        self,
        job: dict[str, Any],
        entity: dict[str, Any],
        position: tuple[float, float, float],
        placeholder_proxy: SceneProxyInstance,
        ok: bool,
        asset: object,
        message: str,
    ) -> None:
        jobs = getattr(self, "_asset_preview_import_jobs", [])
        if job in jobs:
            jobs.remove(job)
        if not ok or asset is None:
            entity["asset_instance"]["preview_state"] = "fallback_import_failed"
            entity["asset_instance"]["preview_error"] = str(message)
            self._resolved_shaded_status = f"Using fallback preview: {message}"
            self.update_viewport_status()
            return
        try:
            model = FBXMeshModel.from_native_fbx_asset(asset)
        except Exception as exc:
            entity["asset_instance"]["preview_state"] = "fallback_import_failed"
            entity["asset_instance"]["preview_error"] = str(exc)
            self._resolved_shaded_status = f"Using fallback preview: {exc}"
            self.update_viewport_status()
            return
        placeholder_proxy.visible = False
        old_mesh = placeholder_proxy.mesh_data
        for index in range(old_mesh.face_start, old_mesh.face_start + old_mesh.face_count):
            if index < len(self.mesh.face_colors):
                self.mesh.face_colors[index].setAlpha(0)
        for index in range(old_mesh.quad_start, old_mesh.quad_start + old_mesh.quad_count):
            if index < len(self.mesh.quad_face_colors):
                self.mesh.quad_face_colors[index].setAlpha(0)
        entity["asset_instance"]["preview_state"] = "native"
        entity["asset_instance"].pop("preview_error", None)
        proxy = self._append_asset_placeholder_proxy(
            entity, position, preview_model=model, queue_native=False
        )
        self._selected_scene_proxy = proxy
        self._scene_lifecycle.mark_dirty()
        self.refresh_scene_outliner()
        self.update_instance_details_panel()
        self.sync_gpu_viewport(full=True)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        self._resolved_shaded_status = f"Native preview ready: {Path(str(asset.source_path)).name}"
        self.update_viewport_status()

    def _restore_asset_placement_proxies(self) -> int:
        existing = {str(proxy.get("source_key") or "") for proxy in self.mesh.scene_proxy_objects}
        restored = 0
        for entity in self._runtime_world_state.get("entities") or ():
            if not isinstance(entity, dict) or not isinstance(entity.get("asset_instance"), dict):
                continue
            entity_id = str(entity.get("entity_id") or uuid.uuid4().hex); entity["entity_id"] = entity_id
            source_key = f"entity:{entity_id}"
            if source_key in existing:
                continue
            transform = dict(entity.get("transform") or {})
            raw_position = list(transform.get("position") or (0.0, 0.0, 0.0))
            position = tuple(float(raw_position[index] if index < len(raw_position) else 0.0) for index in range(3))
            self._append_asset_placeholder_proxy(entity, position)
            existing.add(source_key)
            restored += 1
        return restored

    def _blender_read_camera_authority_code(self, native_id: str) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import (
            build_camera_authority_code,
        )

        return build_camera_authority_code("blender", native_id)

    def _motionbuilder_read_camera_authority_code(self, native_id: str) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import (
            build_camera_authority_code,
        )

        return build_camera_authority_code("motionbuilder", native_id)

    def _unreal_read_camera_authority_code(self, native_id: str) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import (
            build_camera_authority_code,
        )

        return build_camera_authority_code("unreal", native_id)

    def _unreal_switch_camera_code(self, native_id: str) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import (
            build_unreal_camera_switch_code,
        )

        return build_unreal_camera_switch_code(native_id)

    def _maya_possess_camera_code(self, payload: dict[str, Any]) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import build_camera_possession_code

        return build_camera_possession_code("maya", payload)

    def _blender_possess_camera_code(self, payload: dict[str, Any]) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import build_camera_possession_code

        return build_camera_possession_code("blender", payload)

    def _houdini_possess_camera_code(self, payload: dict[str, Any]) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import build_camera_possession_code

        return build_camera_possession_code("houdini", payload)

    def _unity_possess_camera_code(self, payload: dict[str, Any]) -> str:
        eye = [float(value) for value in payload["eye"]]
        target = [float(value) for value in payload["target"]]
        up_target = [float(value) for value in payload.get("up_target", [target[0], target[1] + 1.0, target[2]])]

        def vector(values: list[float]) -> str:
            return "new UnityEngine.Vector3(" + ", ".join(f"{value!r}f" for value in values) + ")"

        fov = float(payload.get("fov_degrees", 45.0))
        aspect = max(0.01, float(payload.get("aspect_ratio", 16.0 / 9.0)))
        near_clip = float(payload.get("near_clip", 0.1))
        far_clip = float(payload.get("far_clip", 10000.0))
        return f"""((System.Func<string>)(() => {{
    var view = UnityEditor.SceneView.lastActiveSceneView;
    if (view == null) return "No active Unity Scene View";
    var eye = {vector(eye)};
    var target = {vector(target)};
    var up = {vector(up_target)} - target;
    var forward = target - eye;
    if (forward.sqrMagnitude < 0.000001f) return "Camera eye and target overlap";
    if (up.sqrMagnitude < 0.000001f) up = UnityEngine.Vector3.up;
    var rotation = UnityEngine.Quaternion.LookRotation(forward.normalized, up.normalized);
    view.LookAtDirect(target, rotation, UnityEngine.Mathf.Max(0.01f, forward.magnitude));
    if (view.camera != null) {{
        view.camera.transform.SetPositionAndRotation(eye, rotation);
        view.camera.fieldOfView = {fov!r}f;
        view.camera.aspect = {aspect!r}f;
        view.camera.nearClipPlane = {near_clip!r}f;
        view.camera.farClipPlane = {far_clip!r}f;
    }}
    view.Repaint();
    return "OK";
    }}))()"""

    def _unreal_possess_camera_code(self, payload: dict[str, Any]) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import build_camera_possession_code

        return build_camera_possession_code("unreal", payload)

    def _motionbuilder_possess_camera_code(self, payload: dict[str, Any]) -> str:
        from tech_connector.ui.dcc_viewer.camera_adapter_code_service import build_camera_possession_code

        return build_camera_possession_code("motionbuilder", payload)

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
            for key in (
                "maya", "blender", "3dsmax", "motionbuilder", "houdini",
                "substance_painter", "unreal", "unity", "photoshop", "gimp",
            ):
                try:
                    bridge = self._scene_snapshot_bridge(key)
                    if callable(getattr(bridge, "find_ports", None)):
                        keys.extend(f"{key}:{int(port)}" for port in bridge.find_ports() or [])
                    elif callable(getattr(bridge, "find_port", None)):
                        port = bridge.find_port()
                        if port:
                            keys.append(f"{key}:{int(port)}")
                except Exception:
                    continue
            return keys or ["maya"]
        return [provider_key]

    def build_federated_scene_document(self) -> FederatedSceneDocument:
        """Capture stable DCC links and locally authored state for a `.tcscene`."""
        for blob_name in list((getattr(self, "_federated_scene_blobs", {}) or {}).keys()):
            if str(blob_name).replace("\\", "/").startswith("scene_sources/"):
                self._federated_scene_blobs.pop(blob_name, None)
        sources: list[dict[str, Any]] = []
        for session_key, snapshot in (getattr(self, "_dcc_scene_snapshots", {}) or {}).items():
            if not isinstance(snapshot, dict):
                continue
            if str(snapshot.get("conversion_state") or "") == "tc_native":
                from tech_connector.game_engine.scene.tc_scene_conversion_service import EMBEDDED_SCENE_SNAPSHOT_BLOB

                self._federated_scene_blobs[EMBEDDED_SCENE_SNAPSHOT_BLOB] = json.dumps(
                    snapshot, separators=(",", ":"), sort_keys=True, default=list
                ).encode("utf-8")
                sources.append({
                    "source_id": "tech_connector-native-converted",
                    "provider": "tech_connector",
                    "session_key": "tc_native_converted",
                    "source_path": "",
                    "reload_policy": "embedded",
                    "snapshot_blob": EMBEDDED_SCENE_SNAPSHOT_BLOB,
                })
                continue
            source_path = str(snapshot.get("scene") or snapshot.get("file") or snapshot.get("project") or "")
            provider = dcc_provider_base_key(session_key)
            source_id = stable_scene_source_id(provider, source_path, str(session_key or ""))
            snapshot_blob = source_snapshot_blob_name(source_id)
            try:
                self._federated_scene_blobs[snapshot_blob] = json.dumps(
                    snapshot,
                    separators=(",", ":"),
                    sort_keys=True,
                    default=list,
                ).encode("utf-8")
            except Exception:
                snapshot_blob = ""
            try:
                from tech_connector.game_engine.integration.dcc_scene_restoration_service import discover_dcc_executable

                executable_hint = discover_dcc_executable(provider)
            except Exception:
                executable_hint = ""
            from tech_connector.game_engine.rendering.material_contract import (
                embed_portable_lookdev_textures,
                lookdev_state_from_snapshot,
            )

            lookdev_state, lookdev_blobs = embed_portable_lookdev_textures(
                lookdev_state_from_snapshot(
                    snapshot,
                    source_provider=provider,
                    source_path=source_path,
                ),
                source_id=source_id,
            )
            self._federated_scene_blobs.update(lookdev_blobs)
            sources.append({
                "source_id": source_id,
                "provider": provider,
                "session_key": str(session_key or "").lower(),
                "source_path": source_path,
                "source_fingerprint": source_file_fingerprint(source_path) if source_path else {"exists": False},
                "process_id": snapshot.get("process_id"),
                "dcc_version": snapshot.get("version") or snapshot.get("application_version") or "",
                "executable_hint": executable_hint,
                "scene_modified": bool(snapshot.get("scene_modified", False)),
                "scene_revision": snapshot.get("scene_revision"),
                "session_state": dcc_session_state_from_snapshot(snapshot, provider=provider),
                "lookdev_state": lookdev_state,
                "reload_policy": "reconnect_or_open",
                "snapshot_blob": snapshot_blob,
                "relaunchable": bool(source_path),
            })
        native_model = getattr(self, "_native_scene_model", None)
        native_manifest = dict(getattr(native_model, "native_fbx_manifest", {}) or {})
        native_path = str(getattr(native_model, "source_path", "") or "")
        if native_manifest:
            native_source_id = stable_scene_source_id("native_fbx", native_path, "native_fbx")
            from tech_connector.game_engine.rendering.material_contract import (
                embed_portable_lookdev_textures,
                lookdev_state_from_snapshot,
            )

            native_lookdev, native_lookdev_blobs = embed_portable_lookdev_textures(
                lookdev_state_from_snapshot(
                    {"provider_id": "native_fbx", "scene": native_path, "objects": native_manifest.get("meshes") or []},
                    source_provider="native_fbx",
                    source_path=native_path,
                ),
                source_id=native_source_id,
            )
            self._federated_scene_blobs.update(native_lookdev_blobs)
            sources.append({
                "source_id": native_source_id,
                "provider": "native_fbx",
                "session_key": "native_fbx",
                "source_path": native_path,
                "source_fingerprint": source_file_fingerprint(native_path) if native_path else {"exists": False},
                "lookdev_state": native_lookdev,
                "reload_policy": "embedded_or_source",
            })
        camera = getattr(self, "viewport_camera", None)
        viewport = {
            "coordinate_system": str(getattr(self, "viewer_coordinate_system", "maya") or "maya"),
            "active_view_provider": str(getattr(self, "active_dcc_view_provider", "") or ""),
            "display_source": str(getattr(self, "viewport_display_source", "local") or "local"),
            "camera": {
                "eye": [float(value) for value in (getattr(camera, "eye", (0.0, 0.0, -4.0)) or (0.0, 0.0, -4.0))],
                "target": [float(value) for value in (getattr(camera, "target", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0))],
                "up": [float(value) for value in (getattr(camera, "up", (0.0, 1.0, 0.0)) or (0.0, 1.0, 0.0))],
                "fov_degrees": float(getattr(camera, "fov_degrees", 45.0) or 45.0),
                "aspect_ratio": float(getattr(camera, "aspect_ratio", 0.0) or 0.0),
                "near_clip": float(getattr(camera, "near_clip", 0.1) or 0.1),
                "far_clip": float(getattr(camera, "far_clip", 100000.0) or 100000.0),
            },
        }
        timeline = {
            "frame": int(getattr(self, "_current_dcc_frame", 1) or 1),
            "start": int(getattr(self, "_dcc_timeline_frame_start", 1) or 1),
            "end": int(getattr(self, "_dcc_timeline_frame_end", 120) or 120),
        }
        name = Path(self._federated_scene_path).stem if self._federated_scene_path else "Untitled Federated Scene"
        metadata: dict[str, Any] = {
            "shot_camera_profiles": copy.deepcopy(getattr(self, "shot_camera_profiles", []) or []),
            "active_shot_take_index": int(getattr(self, "active_shot_take_index", -1)),
            "shot_guides": {
                "enabled": bool(getattr(self, "shot_guides_enabled", False)),
                "mode": str(getattr(self, "shot_guide_mode", "Off") or "Off"),
                "points_normalized": copy.deepcopy(getattr(self, "_shot_guide_points_normalized", {}) or {}),
                "solution": copy.deepcopy(getattr(self, "last_shot_guide_solution", {}) or {}),
            },
            "runtime_world": copy.deepcopy(getattr(self, "_runtime_world_state", {}) or {}),
            "engine_world_settings": copy.deepcopy(getattr(self, "_engine_world_settings", {}) or {}),
            "mesh_default_pose": getattr(self.mesh, "default_pose_to_dict", lambda: {})(),
        }
        if native_manifest:
            metadata["native_fbx_manifest"] = native_manifest
        usd_composition = getattr(self, "_usd_composition", None)
        if usd_composition is not None:
            metadata["usd_composition"] = usd_composition.to_dict()
            usd_result = getattr(self, "_usd_composition_result", None)
            if usd_result is not None:
                metadata["usd_composition"]["last_result"] = copy.deepcopy(
                    dict(getattr(usd_result, "manifest", {}) or {})
                )
        if isinstance(getattr(self, "_tc_native_scene_snapshot", None), dict):
            from tech_connector.game_engine.scene.tc_scene_conversion_service import EMBEDDED_SCENE_SNAPSHOT_BLOB

            metadata["tc_native_scene_snapshot_blob"] = EMBEDDED_SCENE_SNAPSHOT_BLOB
            metadata["conversion_report"] = copy.deepcopy(getattr(self, "_tc_scene_conversion_report", {}) or {})
        runtime = getattr(self, "simulation_runtime", None)
        if runtime is not None:
            metadata["runtime_simulation"] = runtime.deployment_manifest()
        experience = getattr(self, "engine_runtime_experience_plan", None)
        if isinstance(experience, dict):
            metadata["runtime_experience"] = {
                key: copy.deepcopy(value)
                for key, value in experience.items()
                if key != "compiled_ir"
            }
        deformation_maps = getattr(self, "deformation_weight_maps", {}) or {}
        if deformation_maps:
            metadata["deformation_weight_maps"] = {
                str(key): value.to_dict()
                for key, value in deformation_maps.items()
            }
        procedural_graphs = getattr(self, "_procedural_graphs", {}) or {}
        procedural_task_graphs = getattr(self, "_procedural_task_graphs", {}) or {}
        if procedural_graphs or procedural_task_graphs:
            from tech_connector.game_engine.authoring.procedural_workspace_service import ProceduralWorkspaceState

            metadata["procedural_workspace"] = ProceduralWorkspaceState(
                graphs=procedural_graphs,
                task_graphs=procedural_task_graphs,
                active_graph_id=str(getattr(self, "_active_procedural_graph_id", "") or ""),
                active_task_graph_id=str(getattr(self, "_active_procedural_task_graph_id", "") or ""),
                scene_metadata=copy.deepcopy(getattr(self, "_procedural_scene_metadata", {"metadata": {}}) or {"metadata": {}}),
            ).to_dict()
        character_world = getattr(self, "character_world", None)
        if character_world is not None:
            metadata["character_world"] = character_world.to_dict()
        game_experience = getattr(self, "game_experience_profile", None)
        if game_experience is not None:
            metadata["game_experience"] = game_experience.to_dict()
        intelligence_runtime = getattr(self, "world_intelligence_runtime", None)
        if intelligence_runtime is not None:
            metadata["world_intelligence_runtime"] = {
                "reservations": intelligence_runtime.reservations.to_dict(),
                "authority_revision": int(intelligence_runtime.authority_revision),
            }
        document = FederatedSceneDocument(
            name=name,
            sources=sources,
            rig_graph=getattr(self, "editable_rig_graph", EditableRigGraph()),
            cross_dcc_constraints=copy.deepcopy(getattr(self, "_cross_dcc_transform_constraints", []) or []),
            viewport=viewport,
            timeline=timeline,
            restoration={
                "policy": "inherit",
                "cached_sources": True,
                "launch_missing_sources": True,
                "saved_policy_hint": str(getattr(self, "_dcc_scene_restore_policy", "ask") or "ask"),
            },
            metadata=metadata,
        )
        workflow_receipts = getattr(self, "_dcc_workflow_receipts", {}) or {}
        if workflow_receipts:
            from tech_connector.game_engine.integration.dcc_production_workflow_service import attach_workflow_receipt_to_scene

            for record in workflow_receipts.values():
                if not isinstance(record, dict) or not isinstance(record.get("receipt"), dict):
                    continue
                attach_workflow_receipt_to_scene(
                    document,
                    record["receipt"],
                    source_path=str(record.get("source_path") or ""),
                    session_key=str(record.get("session_key") or ""),
                    executable_hint=str(record.get("executable_hint") or ""),
                )
        return document

    def _save_federated_scene_to_path(self, path: str, *, publish_live: bool = True) -> bool:
        if not path:
            return False
        try:
            document = self.build_federated_scene_document()
            document.name = Path(path).stem
            saved_path = save_federated_scene(
                path,
                document,
                blobs=dict(getattr(self, "_federated_scene_blobs", {}) or {}),
            )
            previous_scene_path = self._federated_scene_path
            self._federated_scene_path = str(saved_path)
            self._scene_lifecycle.mark_clean()
            self._scene_lifecycle.remove_recovery(previous_scene_path)
            self._scene_lifecycle.remove_recovery(self._federated_scene_path)
            live_receipt = None
            live_action = getattr(self, "live_game_save_action", None)
            if publish_live and (live_action is None or live_action.isChecked()):
                try:
                    from tech_connector.game_engine.runtime.tc_live_game_sync_service import publish_tcscene_save
                    live_receipt = publish_tcscene_save(document.to_dict(), saved_path)
                except Exception as exc:
                    self._resolved_shaded_status = f"Saved scene: {saved_path.name}. Live sync failed: {exc}"
                    self.update_viewport_status()
                    return True
            self._resolved_shaded_status = f"Saved scene: {saved_path.name}"
            if live_receipt is not None and live_receipt["connected_sessions"]:
                self._resolved_shaded_status += f". {live_receipt['message']}"
            self.update_viewport_status()
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Scene Save Failed", str(exc))
            return False

    def save_federated_scene_dialog(self) -> bool:
        initial = self._federated_scene_path or "Untitled.tcscene"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Tech Connector Scene",
            initial,
            "Tech Connector Scene (*.tcscene)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not path:
            return False
        if not str(path).lower().endswith(".tcscene"):
            path += ".tcscene"
        return self._save_federated_scene_to_path(path)

    def autosave_federated_scene(self) -> str:
        if not self._scene_lifecycle.dirty:
            return ""
        recovery_path = self._scene_lifecycle.recovery_path(self._federated_scene_path)
        temporary_path = recovery_path.with_name(recovery_path.stem + ".tmp.tcscene")
        try:
            recovery_path.parent.mkdir(parents=True, exist_ok=True)
            document = self.build_federated_scene_document()
            document.name = Path(self._federated_scene_path).stem if self._federated_scene_path else "Untitled (Recovered)"
            save_federated_scene(
                temporary_path,
                document,
                blobs=dict(getattr(self, "_federated_scene_blobs", {}) or {}),
            )
            os.replace(temporary_path, recovery_path)
            self._resolved_shaded_status = f"Recovery copy saved: {recovery_path.name}"
            self.update_viewport_status()
            return str(recovery_path)
        except Exception as exc:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            self._resolved_shaded_status = f"Autosave failed: {exc}"
            self.update_viewport_status()
            return ""

    def _offer_startup_scene_recovery(self) -> None:
        recoveries = self._scene_lifecycle.discover_untitled_recoveries()
        if not recoveries or self._scene_lifecycle.dirty or self._federated_scene_path:
            return
        recovery = recoveries[0]
        answer = QMessageBox.question(
            self,
            "Recover Autosaved Scene",
            f"Recover the most recent unsaved scene from {time.ctime(recovery.stat().st_mtime)}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        restored, _message = self.load_federated_scene_file(str(recovery), interactive=True)
        if restored:
            self._federated_scene_path = ""
            self._scene_lifecycle.mark_dirty()
            self._resolved_shaded_status = "Recovered an autosaved untitled scene. Save it to keep the recovery."
            self.update_viewport_status()

    def open_federated_scene_dialog(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Tech Connector Scene",
            self._federated_scene_path or "",
            "Tech Connector Scene (*.tcscene)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if path:
            self.load_federated_scene_file(path, interactive=True)

    def _cached_dcc_snapshots_from_scene(
        self,
        document: FederatedSceneDocument,
        blobs: dict[str, bytes],
    ) -> dict[str, dict[str, Any]]:
        cached: dict[str, dict[str, Any]] = {}
        self._cached_restored_source_keys_by_id = {}
        self._lookdev_texture_resolution_reports = {}
        for source in document.sources:
            provider = str(source.get("provider") or "").strip().lower()
            if provider in {"native_fbx", "tech_connector"}:
                continue
            blob_name = str(source.get("snapshot_blob") or "")
            payload = blobs.get(blob_name) if blob_name else None
            if not payload:
                continue
            try:
                snapshot = json.loads(payload.decode("utf-8"))
            except Exception:
                continue
            if not isinstance(snapshot, dict):
                continue
            session_key = str(source.get("session_key") or provider).strip().lower()
            source_id = str(source.get("source_id") or stable_scene_source_id(provider, str(source.get("source_path") or ""), session_key))
            lookdev_state = source.get("lookdev_state") if isinstance(source.get("lookdev_state"), dict) else None
            if lookdev_state:
                from tech_connector.game_engine.rendering.material_contract import resolve_embedded_lookdev_textures

                snapshot, resolution_report = resolve_embedded_lookdev_textures(
                    snapshot,
                    lookdev_state,
                    blobs,
                    cache_root=(
                        Path(tempfile.gettempdir())
                        / "tech_connector"
                        / "scene_textures"
                        / str(document.scene_id)
                        / source_id
                    ),
                )
                self._lookdev_texture_resolution_reports[source_id] = resolution_report
            cached[session_key] = snapshot
            self._cached_restored_source_keys_by_id[source_id] = session_key
        return cached

    def _install_restored_dcc_snapshots(
        self,
        snapshots: dict[str, dict[str, Any]],
        *,
        replace_existing: bool = False,
    ) -> bool:
        if not snapshots:
            return False
        if getattr(self, "_dcc_scene_model_thread", None) is not None:
            self._pending_restored_live_snapshots.update(snapshots)
            return True
        normalized = {
            str(provider).lower(): self._snapshot_for_viewer_scale_policy(str(provider), snapshot)
            for provider, snapshot in snapshots.items()
            if isinstance(snapshot, dict)
        }
        if not normalized:
            return False
        previous_proxy_state = self._capture_proxy_refresh_state()
        had_existing = bool(getattr(self, "_dcc_scene_snapshots", {})) and not replace_existing
        if replace_existing:
            self._dcc_scene_snapshots = {}
            self._dcc_snapshot_signatures = {}
            self._clear_dcc_timeline_snapshot_cache()
        self._dcc_scene_snapshots.update(normalized)
        for provider, snapshot in normalized.items():
            self._dcc_snapshot_signatures[provider] = self._snapshot_dirty_signature(snapshot)
        self._loaded_scene_providers = list(self._dcc_scene_snapshots.keys())
        context = {
            "previous_proxy_state": previous_proxy_state,
            "replace_existing": bool(replace_existing),
            "show_message": False,
            "had_existing_snapshots": had_existing,
            "new_provider_keys": list(normalized.keys()),
            "new_snapshots": normalized,
        }
        preserved_center = getattr(self.mesh, "scene_center", None) if had_existing else None
        preserved_scale = getattr(self.mesh, "scene_scale", None) if had_existing else None
        complexity = self._scene_model_compile_complexity()
        if self.isVisible() and complexity >= 50_000:
            return self._start_scene_model_compile(
                scene_center=preserved_center,
                scene_scale=preserved_scale,
                context=context,
                complexity=complexity,
            )
        model = self._compose_loaded_scene_model(scene_center=preserved_center, scene_scale=preserved_scale)
        return self._apply_compiled_scene_model(model, context, compile_ms=0.0)

    def _capture_restored_source_snapshot(
        self,
        session_key: str,
        cancel_event: threading.Event | None = None,
    ) -> tuple[bool, Any]:
        provider = dcc_provider_base_key(session_key)
        bridge = self._scene_snapshot_bridge(session_key)
        kwargs: dict[str, Any] = {
            "selected_only": False,
            "include_geometry": True,
            "limit": 500,
            "timeout": 90.0,
        }
        if provider in {"blender", "3dsmax", "houdini", "unreal", "unity"}:
            kwargs["include_materials"] = True
        if provider in {"maya", "blender"}:
            kwargs["cancel_event"] = cancel_event
        if provider == "maya":
            kwargs["meshes_only"] = False
        try:
            ok, snapshot_or_error = bridge.get_scene_snapshot(**kwargs)
        except TypeError:
            ok, snapshot_or_error = bridge.get_scene_snapshot(selected_only=False, limit=500, timeout=90.0)
        if ok and isinstance(snapshot_or_error, dict):
            return True, self._snapshot_for_viewer_scale_policy(session_key, snapshot_or_error)
        return False, snapshot_or_error

    def _apply_restored_source_session_state(
        self,
        session_key: str,
        state: dict[str, Any],
        cancel_event: threading.Event | None = None,
    ) -> tuple[bool, str]:
        from tech_connector.game_engine.integration.dcc_scene_restoration_service import (
            dcc_session_state_restore_code,
        )

        provider = dcc_provider_base_key(session_key)
        try:
            code = dcc_session_state_restore_code(provider, state)
        except Exception as exc:
            return False, str(exc)
        bridge = self._scene_snapshot_bridge(session_key)
        if provider == "unreal":
            response = bridge.execute_python(code, timeout=5.0, reset_globals=True)
            ok = bool(response.get("ok")) if isinstance(response, dict) else False
            raw = response.get("data") or response.get("output") or response.get("error") or response if isinstance(response, dict) else response
            return ok, str(raw)
        try:
            return bridge.execute(code, timeout=5.0, cancel_event=cancel_event)
        except TypeError:
            return bridge.execute(code, timeout=5.0)

    def _start_dcc_scene_restore(
        self,
        sources: list[dict[str, Any]],
        *,
        interactive: bool,
    ) -> bool:
        from tech_connector.game_engine.integration.dcc_scene_restoration_service import (
            RESTORE_POLICY_AUTOMATIC,
            RESTORE_POLICY_CACHED_ONLY,
            normalize_restore_policy,
        )

        linked_sources = [
            dict(source) for source in sources
            if str(source.get("provider") or "") not in {"native_fbx", "tech_connector"}
            and str(source.get("reload_policy") or "") != "embedded"
        ]
        if not linked_sources:
            return False
        policy = normalize_restore_policy(getattr(self, "_dcc_scene_restore_policy", "ask"))
        if policy == "ask":
            if not interactive:
                policy = RESTORE_POLICY_CACHED_ONLY
            else:
                launchable = sum(1 for source in linked_sources if source.get("source_path"))
                answer = QMessageBox.question(
                    self,
                    "Restore Linked DCC Sources",
                    f"Restore {len(linked_sources)} linked DCC source(s) now? "
                    f"Up to {launchable} missing application session(s) may be launched.\n\n"
                    "Choose No to keep using the embedded cached scene only.",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                policy = RESTORE_POLICY_AUTOMATIC if answer == QMessageBox.Yes else RESTORE_POLICY_CACHED_ONLY
        if policy == RESTORE_POLICY_CACHED_ONLY:
            return False
        self._detach_dcc_scene_restore()
        thread = QThread(self)
        worker = DccSceneRestoreWorker(
            linked_sources,
            policy,
            self.discover_importable_dcc_scene_sources,
            self._open_saved_source_in_dcc,
            self._capture_restored_source_snapshot,
            self._apply_restored_source_session_state,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_dcc_scene_restore_report)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_dcc_scene_restore)
        thread.finished.connect(thread.deleteLater)
        self._dcc_scene_restore_thread = thread
        self._dcc_scene_restore_worker = worker
        self._dcc_scene_restore_report = None
        self._resolved_shaded_status = "Restoring linked DCC sources in background"
        self.update_viewport_status()
        thread.start()
        return True

    @Slot(object)
    def _capture_dcc_scene_restore_report(self, report: Any) -> None:
        self._dcc_scene_restore_report = dict(report or {})

    @Slot()
    def _finish_dcc_scene_restore(self) -> None:
        sender = self.sender()
        current = getattr(self, "_dcc_scene_restore_thread", None)
        if current is None or (sender is not None and sender is not current):
            return
        report = dict(getattr(self, "_dcc_scene_restore_report", None) or {})
        self._last_dcc_scene_restore_report = {
            "policy": str(report.get("policy") or ""),
            "entries": copy.deepcopy(report.get("entries") or []),
            "canceled": bool(report.get("canceled")),
            "error": str(report.get("error") or ""),
        }
        self._dcc_scene_restore_thread = None
        self._dcc_scene_restore_worker = None
        self._dcc_scene_restore_report = None
        for launch in report.get("launches") or []:
            process = getattr(launch, "process", None)
            if process is not None:
                self._dcc_processes_launched_for_restore[int(process.pid)] = launch
        successful = {"attached", "opened", "launched"}
        for entry in report.get("entries") or []:
            if str(entry.get("status") or "") not in successful:
                continue
            source = dict(entry.get("source") or {})
            source_id = str(source.get("source_id") or "")
            cached_key = self._cached_restored_source_keys_by_id.get(source_id)
            live_key = str(entry.get("session_key") or "")
            if cached_key and cached_key != live_key:
                self._dcc_scene_snapshots.pop(cached_key, None)
                self._dcc_snapshot_signatures.pop(cached_key, None)
            if live_key:
                self.remember_dcc_session_choice(live_key)
        live_snapshots = dict(report.get("snapshots") or {})
        if live_snapshots:
            self._install_restored_dcc_snapshots(live_snapshots, replace_existing=False)
        entries = list(report.get("entries") or [])
        connected = sum(1 for entry in entries if str(entry.get("status") or "") in successful)
        failed = [entry for entry in entries if str(entry.get("status") or "") not in successful]
        if report.get("error"):
            self._resolved_shaded_status = f"DCC source restoration failed: {str(report['error'])[:140]}"
        elif report.get("canceled"):
            self._resolved_shaded_status = "DCC source restoration canceled; cached sources remain available"
        else:
            self._resolved_shaded_status = f"Restored {connected}/{len(entries)} linked DCC source(s)"
            if failed:
                self._resolved_shaded_status += f"; {len(failed)} remain cached/offline"
            changed = sum(1 for entry in entries if bool(entry.get("source_changed")))
            if changed:
                self._resolved_shaded_status += f"; {changed} source file(s) changed since save"
        self.update_viewport_status()

    def _detach_dcc_scene_restore(self) -> None:
        thread = getattr(self, "_dcc_scene_restore_thread", None)
        worker = getattr(self, "_dcc_scene_restore_worker", None)
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._capture_dcc_scene_restore_report)
            except Exception:
                LOGGER.debug("Scene-restore worker was already disconnected.", exc_info=True)
        try:
            thread.finished.disconnect(self._finish_dcc_scene_restore)
        except Exception:
            pass
        self._dcc_scene_restore_thread = None
        self._dcc_scene_restore_worker = None
        self._dcc_scene_restore_report = None
        thread.setParent(QApplication.instance())

    def load_federated_scene_file(self, path: str, *, interactive: bool = True) -> tuple[bool, str]:
        """Restore local authoring state and reconnect or reopen linked DCC files."""
        requested_path = Path(path).resolve()
        load_path = requested_path
        recovered_autosave = False
        recovery_path = self._scene_lifecycle.recovery_path(str(requested_path))
        if (
            interactive
            and ".autosave" not in requested_path.stem
            and recovery_path.is_file()
            and (not requested_path.is_file() or recovery_path.stat().st_mtime > requested_path.stat().st_mtime)
        ):
            answer = QMessageBox.question(
                self,
                "Newer Autosave Found",
                f"A newer recovery copy exists for {requested_path.name}. Recover it?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Cancel:
                return False, "Scene open cancelled."
            if answer == QMessageBox.Yes:
                load_path = recovery_path
                recovered_autosave = True
        try:
            document, blobs = load_federated_scene(load_path)
        except Exception as exc:
            if interactive:
                QMessageBox.warning(self, "Scene Open Failed", str(exc))
            return False, str(exc)

        self._detach_timeline_cache_for_close()
        self._detach_dcc_scene_restore()
        self._detach_scene_model_compile()
        self._detach_deformation_binding_workers()
        self._pending_restored_live_snapshots = {}
        self._cached_restored_source_keys_by_id = {}
        self._dcc_scene_snapshots = {}
        self._dcc_snapshot_signatures = {}
        self._loaded_scene_providers = []
        self._dcc_deformation_bindings = {}
        self._dcc_deformation_binding_fingerprints = {}
        self._native_scene_model = None
        self._native_fbx_asset = None
        self._native_fbx_current_pose = None
        self._usd_composition = None
        self._usd_composition_result = None
        self._tc_native_scene_snapshot = None
        self._tc_scene_conversion_report = {}
        self._procedural_graphs = {}
        self._procedural_results = {}
        self._procedural_task_graphs = {}
        self._procedural_task_results = {}
        self._procedural_scene_metadata = {"metadata": {}}
        self._active_procedural_graph_id = ""
        self._active_procedural_task_graph_id = ""
        self._procedural_graph_cooker = None
        self._procedural_task_cooker = None
        self._federated_scene_path = str(requested_path)
        self.editable_rig_graph = document.rig_graph
        self._federated_scene_blobs = blobs
        self._cross_dcc_transform_constraints = copy.deepcopy(document.cross_dcc_constraints)
        self._runtime_world_state = copy.deepcopy(dict(document.metadata.get("runtime_world") or {}))
        self._engine_world_settings = copy.deepcopy(dict(document.metadata.get("engine_world_settings") or {}))
        self._saved_mesh_default_pose = copy.deepcopy(dict(document.metadata.get("mesh_default_pose") or {}))
        self._runtime_world_state.setdefault("entities", [])
        self._runtime_world_state.setdefault("physics_joints", [])
        self._physics_joint_editor_model = None
        self._current_dcc_frame = int(document.timeline.get("frame", 1) or 1)
        self._dcc_timeline_frame_start = int(document.timeline.get("start", 1) or 1)
        self._dcc_timeline_frame_end = int(document.timeline.get("end", 120) or 120)
        self.shot_camera_profiles = [
            ShotTakeProfile.from_dict(dict(profile or {})).to_dict()
            for profile in (document.metadata.get("shot_camera_profiles") or [])
            if isinstance(profile, dict)
        ]
        self.active_shot_take_index = int(document.metadata.get("active_shot_take_index", -1))
        guide_state = dict(document.metadata.get("shot_guides") or {})
        self.shot_guides_enabled = bool(guide_state.get("enabled", False))
        self.shot_guide_mode = str(guide_state.get("mode") or "Off")
        self._shot_guide_points_normalized = dict(guide_state.get("points_normalized") or {})
        self.last_shot_guide_solution = dict(guide_state.get("solution") or {})
        usd_composition_data = document.metadata.get("usd_composition")
        if isinstance(usd_composition_data, dict):
            from tech_connector.game_engine.scene.usd_composition_service import (
                UsdComposition,
                UsdCompositionResult,
            )

            self._usd_composition = UsdComposition.from_dict(usd_composition_data)
            last_result = usd_composition_data.get("last_result")
            if isinstance(last_result, dict):
                self._usd_composition_result = UsdCompositionResult(
                    str(last_result.get("output_path") or ""),
                    dict(last_result),
                )
        from tech_connector.game_engine.authoring.character_intelligence_service import CharacterWorldAsset

        character_world_data = document.metadata.get("character_world")
        self.character_world = (
            CharacterWorldAsset.from_dict(dict(character_world_data))
            if isinstance(character_world_data, dict)
            else CharacterWorldAsset()
        )
        from tech_connector.game_engine.authoring.game_experience_service import GameExperienceProfile
        from tech_connector.game_engine.integration.world_intelligence_command_service import WorldIntelligenceRuntimeState
        from tech_connector.game_engine.runtime.world_intelligence_runtime_service import SmartObjectReservationManager

        game_experience_data = document.metadata.get("game_experience")
        self.game_experience_profile = (
            GameExperienceProfile.from_dict(dict(game_experience_data))
            if isinstance(game_experience_data, dict)
            else None
        )
        procedural_workspace = document.metadata.get("procedural_workspace")
        if isinstance(procedural_workspace, dict):
            from tech_connector.game_engine.authoring.procedural_workspace_service import ProceduralWorkspaceState

            workspace = ProceduralWorkspaceState.from_dict(procedural_workspace)
            self._procedural_graphs = workspace.graphs
            self._procedural_task_graphs = workspace.task_graphs
            self._active_procedural_graph_id = workspace.active_graph_id
            self._active_procedural_task_graph_id = workspace.active_task_graph_id
            self._procedural_scene_metadata = workspace.scene_metadata
        self._dcc_workflow_receipts = {
            str(key): {
                "receipt": dict(record.get("receipt") or {}),
                "source_path": str(record.get("source_path") or ""),
                "session_key": str(record.get("session_key") or ""),
                "executable_hint": str(record.get("executable_hint") or ""),
            }
            for key, record in dict(document.metadata.get("dcc_workflow_receipts") or {}).items()
            if isinstance(record, dict) and isinstance(record.get("receipt"), dict)
        }
        intelligence_runtime_data = dict(document.metadata.get("world_intelligence_runtime") or {})
        self.world_intelligence_runtime = WorldIntelligenceRuntimeState(
            reservations=SmartObjectReservationManager.from_dict(
                dict(intelligence_runtime_data.get("reservations") or {})
            ),
            authority_revision=int(intelligence_runtime_data.get("authority_revision", 0)),
        )
        self._sync_viewer_visual_actions()
        from tech_connector.game_engine.deformation import DeformationWeightMap

        self.deformation_weight_maps = {
            str(key): DeformationWeightMap.from_dict(dict(value))
            for key, value in dict(document.metadata.get("deformation_weight_maps") or {}).items()
            if isinstance(value, dict)
        }
        self.refresh_shot_take_combo()
        try:
            camera = document.viewport.get("camera") or {}
            self.viewport_camera = MayaViewportCamera(
                eye=tuple(float(value) for value in camera.get("eye", self.viewport_camera.eye)),
                target=tuple(float(value) for value in camera.get("target", self.viewport_camera.target)),
                up=tuple(float(value) for value in camera.get("up", self.viewport_camera.up)),
                fov_degrees=float(camera.get("fov_degrees", self.viewport_camera.fov_degrees)),
                aspect_ratio=float(camera.get("aspect_ratio", self.viewport_camera.aspect_ratio)),
                near_clip=float(camera.get("near_clip", self.viewport_camera.near_clip)),
                far_clip=float(camera.get("far_clip", self.viewport_camera.far_clip)),
            )
        except Exception as exc:
            self.record_nonfatal_diagnostic("Saved viewport camera was invalid", exc, surface=interactive)

        native_manifest = document.metadata.get("native_fbx_manifest")
        if isinstance(native_manifest, dict) and native_manifest:
            float_bytes = blobs.get("native_fbx/buffers.f32", b"")
            uint_bytes = blobs.get("native_fbx/buffers.u32", b"")
            if float_bytes and uint_bytes:
                try:
                    from tech_connector.game_engine.scene.native_fbx_service import NativeFbxAsset

                    packed_floats = array.array("f")
                    packed_floats.frombytes(float_bytes)
                    packed_integers = array.array("I")
                    packed_integers.frombytes(uint_bytes)
                    native_source = next(
                        (
                            str(item.get("source_path") or "")
                            for item in document.sources
                            if str(item.get("provider") or "") == "native_fbx"
                        ),
                        "",
                    )
                    asset = NativeFbxAsset(native_source, native_manifest, packed_floats, packed_integers)
                    self._native_scene_model = FBXMeshModel.from_native_fbx_asset(asset)
                    self._native_fbx_asset = asset
                    self.mesh = self._native_scene_model
                    self._install_native_fbx_deformation_runtime(asset)
                    self.sync_gpu_viewport(full=True)
                    self.refresh_scene_outliner()
                except Exception as exc:
                    if interactive:
                        QMessageBox.warning(self, "Embedded FBX Restore Failed", str(exc))

        embedded_snapshot_blob = str(document.metadata.get("tc_native_scene_snapshot_blob") or "")
        if embedded_snapshot_blob:
            try:
                embedded_snapshot = json.loads(blobs[embedded_snapshot_blob].decode("utf-8"))
                if not isinstance(embedded_snapshot, dict):
                    raise ValueError("Embedded TC scene snapshot is not a dictionary.")
                self._tc_native_scene_snapshot = embedded_snapshot
                self._tc_scene_conversion_report = dict(document.metadata.get("conversion_report") or {})
                self._dcc_scene_snapshots = {"tc_native_converted": embedded_snapshot}
                self.mesh = FBXMeshModel.from_scene_snapshot(embedded_snapshot)
                self.sync_gpu_viewport(full=True)
                self.refresh_scene_outliner()
            except Exception as exc:
                if interactive:
                    QMessageBox.warning(self, "Embedded TC Scene Restore Failed", str(exc))

        cached_snapshots = self._cached_dcc_snapshots_from_scene(document, blobs)
        if cached_snapshots:
            self._install_restored_dcc_snapshots(cached_snapshots, replace_existing=False)
        restored_placements = self._restore_asset_placement_proxies()
        if restored_placements:
            self.refresh_scene_outliner()
        self._apply_saved_mesh_default_pose(self.mesh)
        restoration_started = self._start_dcc_scene_restore(document.sources, interactive=interactive)
        timeline = getattr(self, "anim_timeline", None)
        sequence = getattr(timeline, "sequence", None)
        if sequence is not None:
            sequence.current_frame_index = max(
                0,
                min(len(sequence.frames) - 1, self._current_dcc_frame - self._dcc_timeline_frame_start),
            )
            if timeline is not None:
                timeline.update_timeline_ui()
        self.sync_gpu_viewport(full=False)
        parts = [f"Opened {Path(path).name}."]
        if cached_snapshots:
            parts.append(f"Restored {len(cached_snapshots)} cached DCC source(s).")
        if restoration_started:
            parts.append("Live DCC restoration is continuing in the background.")
        lookdev_report = federated_scene_lookdev_report(document)
        if lookdev_report["source_count"]:
            counts = lookdev_report["status_counts"]
            parts.append(
                "Lookdev parity: "
                f"{counts['complete']} complete, {counts['partial']} partial, "
                f"{counts['unavailable']} unavailable."
            )
        message = " ".join(parts)
        self._viewer_undo_stack = []
        self._viewer_redo_stack = []
        self._scene_lifecycle.mark_clean()
        if recovered_autosave:
            self._scene_lifecycle.mark_dirty()
            message = f"Recovered newer autosave for {requested_path.name}. Save to preserve it. " + message
        self._resolved_shaded_status = message
        self.update_viewport_status()
        return True, message

    def _open_saved_source_in_dcc(
        self,
        session_key: str,
        source_path: str,
        cancel_event: threading.Event | None = None,
    ) -> tuple[bool, str]:
        """Open a saved source without discarding unsaved DCC changes."""
        provider = dcc_provider_base_key(session_key)
        if not source_path or not Path(source_path).is_file():
            return False, f"Source file does not exist: {source_path}"
        bridge = self._scene_snapshot_bridge(session_key)
        if provider == "maya":
            code = f"""
    import maya.cmds as cmds
    path = {source_path!r}
    if cmds.file(q=True, modified=True):
    raise RuntimeError("Maya has unsaved changes; the linked scene was not replaced.")
    cmds.file(path, open=True, force=False, prompt=False)
    print(path)
    """
        elif provider == "blender":
            code = f"""
    import bpy
    path = {source_path!r}
    if bpy.data.is_dirty:
    raise RuntimeError("Blender has unsaved changes; the linked scene was not replaced.")
    bpy.ops.wm.open_mainfile(filepath=path)
    print(path)
    """
        elif provider == "houdini":
            code = f"""
    import hou
    path = {source_path!r}
    if hou.hipFile.hasUnsavedChanges():
    raise RuntimeError("Houdini has unsaved changes; the linked scene was not replaced.")
    hou.hipFile.load(path, suppress_save_prompt=True)
    print(path)
    """
        elif provider == "motionbuilder":
            code = f"""
    from pyfbsdk import FBApplication
    path = {source_path!r}
    if not FBApplication().FileOpen(path):
    raise RuntimeError("MotionBuilder could not open " + path)
    print(path)
    """
        else:
            return False, f"Automatic project reopening is not supported for {provider.title()} yet."
        try:
            return bridge.execute(code, timeout=90.0, cancel_event=cancel_event)
        except TypeError:
            return bridge.execute(code, timeout=90.0)

    def show_import_scene_dialog(self) -> None:
        # Import Scene is intentionally global: it always shows every available
        # DCC session, regardless of the quick picker selection or preference.
        sources = self.discover_importable_dcc_scene_sources()
        if not sources:
            QMessageBox.information(
                self,
                "Import DCC Scene",
                "No live DCC scene bridge sessions were found. Start a DCC bridge, then try Import Scene again.",
            )
            return
        dialog = DccSceneImportDialog(sources, self)
        if dialog.exec() != QDialog.Accepted:
            return
        keys = [str(source.get("key") or "") for source in dialog.selected_sources if source.get("key")]
        if keys:
            for key in keys:
                self.remember_dcc_session_choice(key)
            self._load_dcc_scene_providers(keys, show_message=True, replace_existing=False, force_rebuild=True)

    def discover_importable_dcc_scene_sources(self, providers: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        provider_list = [dcc_provider_base_key(provider) for provider in (providers or (
            "maya", "blender", "3dsmax", "motionbuilder", "houdini",
            "substance_painter", "unreal", "unity", "photoshop", "gimp",
        ))]
        for provider in provider_list:
            if not provider:
                continue
            try:
                bridge = self._scene_snapshot_bridge(provider)
            except Exception:
                continue
            ports: list[int] = []
            try:
                if callable(getattr(bridge, "find_ports", None)):
                    ports = [int(port) for port in (bridge.find_ports() or [])]
                elif callable(getattr(bridge, "find_port", None)):
                    port = bridge.find_port()
                    if port:
                        ports = [int(port)]
            except Exception:
                ports = []
            for port in ports:
                key = f"{provider}:{port}"
                provider_base = dcc_provider_base_key(provider)
                session_bridge = self._scene_snapshot_bridge(key)
                kwargs = {
                    "selected_only": False,
                    "include_geometry": False,
                    "limit": 500,
                    "timeout": 3.0,
                }
                if provider_base in {
                    "blender", "3dsmax", "houdini", "substance_painter", "unreal", "unity",
                }:
                    kwargs["include_materials"] = False
                if provider_base == "maya":
                    kwargs["meshes_only"] = False
                try:
                    ok, snapshot = session_bridge.get_scene_snapshot(**kwargs)
                except TypeError:
                    try:
                        ok, snapshot = session_bridge.get_scene_snapshot(selected_only=False, limit=500, timeout=3.0)
                    except Exception as exc:
                        ok, snapshot = False, str(exc)
                except Exception as exc:
                    ok, snapshot = False, str(exc)
                if not ok or not isinstance(snapshot, dict):
                    sources.append(
                        {
                            "provider": provider,
                            "key": key,
                            "port": port,
                            "scene": "",
                            "process_id": 0,
                            "scene_modified": None,
                            "object_count": "",
                            "selection_count": "",
                            "status": str(snapshot)[:160],
                        }
                    )
                    continue
                objects = snapshot.get("objects") or []
                selection = snapshot.get("selection") or snapshot.get("selected") or []
                sources.append(
                    {
                        "provider": provider,
                        "key": key,
                        "port": port,
                        "scene": snapshot.get("scene") or snapshot.get("file") or snapshot.get("project") or "",
                        "process_id": int(snapshot.get("process_id") or snapshot.get("pid") or 0),
                        "scene_modified": snapshot.get("scene_modified"),
                        "object_count": len(objects) if isinstance(objects, list) else "",
                        "selection_count": len(selection) if isinstance(selection, list) else "",
                        "status": "ready",
                    }
                )
        return sources

    def _set_provider_frame(self, provider: str, frame: int) -> None:
        provider_key = str(provider or "").lower()
        provider_base = dcc_provider_base_key(provider_key)
        bridge = self._scene_snapshot_bridge(provider_key)
        if provider_base == "maya":
            ok, raw = bridge.execute(f"import maya.cmds as cmds\ncmds.currentTime({int(frame)}, edit=True)", timeout=2.0)
        elif provider_base == "blender":
            ok, raw = bridge.execute(f"import bpy\nbpy.context.scene.frame_set({int(frame)})", timeout=2.0)
        elif provider_base == "houdini":
            ok, raw = bridge.execute(f"import hou\nhou.setFrame({int(frame)})", timeout=2.0)
        elif provider_base == "motionbuilder":
            ok, raw = bridge.execute(
                "import pyfbsdk\n"
                f"pyfbsdk.FBSystem().LocalTime = pyfbsdk.FBTime(0, 0, 0, {int(frame)})",
                timeout=2.0,
            )
        elif provider_base == "unreal":
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
            except (json.JSONDecodeError, TypeError, ValueError):
                LOGGER.debug("DCC command response was plain text rather than JSON.", exc_info=True)
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
        provider_raw = str(provider or "").strip().lower()
        provider_key = dcc_provider_base_key(provider_raw)
        preferred = (getattr(self, "_dcc_preferred_session_keys", {}) or {}).get(provider_key, "")
        if ":" not in provider_raw and preferred:
            provider_raw = preferred
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

    def create_primitive_mesh(self, prim_name: str):
        """Instantiate selected Maya 3D Procedural Quad Primitive (Poly Sphere, Poly Cube, Poly Cylinder)."""
        self.push_viewer_undo_state(f"Create {prim_name}")
        if prim_name == "Cube":
            self.mesh = DCCProceduralPrimitiveFactory.create_cube_primitive()
        elif prim_name == "Cylinder":
            self.mesh = DCCProceduralPrimitiveFactory.create_cylinder_primitive()
        else:
            self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self.sync_gpu_viewport(full=True)
        self.frame_mesh_camera()
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.update()
        if self.isVisible():
            QMessageBox.information(
                self,
                f"{THE_GARDEN_DCC_VIEWER_NAME} Primitive Created",
                f"Created TC primitive '{prim_name}' in {THE_GARDEN_DCC_VIEWER_NAME}.",
            )

    def open_or_import_file_dialog(self):
        """Open supported scene assets and texture maps."""
        file_path, filter_selected = QFileDialog.getOpenFileName(
            self,
            "Open or Import 3D Mesh / Texture",
            "",
            "All Supported Files (*.fbx *.obj *.gltf *.glb *.stl *.usd *.usda *.usdc *.usdz *.abc *.png *.jpg *.tga *.psd);;3D Scene Files (*.fbx *.obj *.gltf *.glb *.stl *.usd *.usda *.usdc *.usdz *.abc);;Texture Maps (*.png *.jpg *.tga *.psd *.exr);;All Files (*)",
            options=QFileDialog.DontUseNativeDialog
        )

        if not file_path:
            return

        ext = Path(file_path).suffix.lower()
        if ext in {".fbx", ".obj", ".gltf", ".glb", ".stl", ".usd", ".usda", ".usdc", ".usdz", ".abc"}:
            if ext != ".obj":
                self.start_native_scene_import(file_path)
                return
            try:
                self.push_viewer_undo_state(f"Open {Path(file_path).name}")
                self.mesh = FBXMeshModel.from_obj(file_path)
            except Exception as exc:
                QMessageBox.warning(self, "OBJ Load Failed", str(exc))
                return
            self.sync_gpu_viewport(full=True)
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
                self.mesh.sample_albedo_path = file_path
                self.sync_gpu_viewport(full=False)
                if hasattr(self, 'canvas') and self.canvas:
                    self.canvas.update()
                if self.isVisible():
                    QMessageBox.information(self, "Texture Loaded", f"Successfully applied texture map '{Path(file_path).name}' to Albedo channel!")

    def compose_usd_layers_dialog(self) -> None:
        if self._usd_composition_thread is not None:
            QMessageBox.information(self, "OpenUSD Composition", "A USD composition is already running.")
            return
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select OpenUSD Layers (Strongest First)",
            "",
            "OpenUSD Layers (*.usd *.usda *.usdc *.usdz)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not paths:
            return
        output_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Composed OpenUSD Stage",
            str(Path(paths[0]).with_name(Path(paths[0]).stem + "_composed.usda")),
            "OpenUSD ASCII (*.usda);;OpenUSD (*.usd);;OpenUSD Crate (*.usdc)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not output_path:
            return
        from tech_connector.game_engine.scene.usd_composition_service import UsdComposition, UsdLayerSpec

        composition = UsdComposition([
            UsdLayerSpec(str(path), role="source" if index else "strongest_override")
            for index, path in enumerate(paths)
        ])
        self._start_usd_composition(composition, output_path)

    def _start_usd_composition(self, composition: object, output_path: str) -> None:
        thread = QThread(self)
        worker = UsdCompositionWorker(composition, output_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_usd_composition)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._finish_usd_composition_thread(current))
        thread.finished.connect(thread.deleteLater)
        self._usd_composition_thread = thread
        self._usd_composition_worker = worker
        self._resolved_shaded_status = f"Composing OpenUSD stage: {Path(output_path).name}"
        self.update_viewport_status()
        thread.start()

    @Slot(bool, object, object, str)
    def _capture_usd_composition(self, ok: bool, composition: object, result: object, message: str) -> None:
        if not ok or result is None:
            self._resolved_shaded_status = f"OpenUSD composition failed: {message}"
            self.update_viewport_status()
            if self.isVisible():
                QMessageBox.warning(self, "OpenUSD Composition Failed", str(message))
            return
        self._usd_composition = composition
        self._usd_composition_result = result
        manifest = dict(getattr(result, "manifest", {}) or {})
        self._resolved_shaded_status = (
            f"OpenUSD ready: {manifest.get('prim_count', 0)} prim(s), "
            f"{manifest.get('layer_count', 0)} layer(s)"
        )
        self.update_viewport_status()
        self.start_native_scene_import(str(getattr(result, "output_path", "") or ""))

    def _finish_usd_composition_thread(self, thread: QThread) -> None:
        if self._usd_composition_thread is thread:
            self._usd_composition_thread = None
            self._usd_composition_worker = None

    def _detach_usd_composition_worker(self) -> None:
        thread = getattr(self, "_usd_composition_thread", None)
        worker = getattr(self, "_usd_composition_worker", None)
        self._usd_composition_thread = None
        self._usd_composition_worker = None
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._capture_usd_composition)
            except Exception:
                pass
        thread.quit()
        thread.wait(2500)

    def show_usd_composition_status(self) -> None:
        composition = getattr(self, "_usd_composition", None)
        if composition is None:
            QMessageBox.information(self, "USD Composition Status", "No OpenUSD composition is attached to this scene.")
            return
        changes = composition.source_changes()
        result = getattr(self, "_usd_composition_result", None)
        manifest = dict(getattr(result, "manifest", {}) or {})
        lines = [
            f"Layers: {len(composition.layers)}",
            f"Prims: {manifest.get('prim_count', 'not composed')}",
            f"Output: {getattr(result, 'output_path', '') or 'not composed'}",
            "",
        ]
        for index, (layer, change) in enumerate(zip(composition.layers, changes), 1):
            state = "changed" if change.get("changed") else ("available" if change.get("current", {}).get("exists") else "missing")
            lines.append(f"{index}. [{state}] {layer.role}: {layer.path}")
        diagnostics = manifest.get("diagnostics") or []
        if diagnostics:
            lines.extend(["", "Diagnostics:"])
            lines.extend(str(item.get("message") or item) for item in diagnostics[:20])
        QMessageBox.information(self, "USD Composition Status", "\n".join(lines))

    def start_native_scene_import(self, path: str) -> None:
        if getattr(self, "_native_fbx_import_thread", None) is not None:
            QMessageBox.information(self, "Scene Import", "A scene import is already running.")
            return
        from tech_connector.game_engine.scene.native_fbx_service import native_scene_import_capabilities

        capabilities = native_scene_import_capabilities()
        extension = Path(path).suffix.lower()
        format_capability = dict((capabilities.get("formats") or {}).get(extension) or {})
        if not format_capability.get("available"):
            limitations = "\n".join(str(item) for item in capabilities.get("limitations") or [])
            QMessageBox.warning(
                self,
                "Scene Import Backend Unavailable",
                limitations or f"No importer is available for {extension or 'this file type'}.",
            )
            return
        thread = QThread(self)
        worker = NativeFbxImportWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._capture_native_fbx_import)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda current=thread: self._finish_native_fbx_import_thread(current))
        thread.finished.connect(thread.deleteLater)
        self._native_fbx_import_thread = thread
        self._native_fbx_import_worker = worker
        self._resolved_shaded_status = f"Importing via external Blender converter: {Path(path).name}"
        self.update_viewport_status()
        thread.start()

    def start_native_fbx_import(self, path: str) -> None:
        """Compatibility entry point retained for existing callers."""
        self.start_native_scene_import(path)

    @Slot(bool, object, str)
    def _capture_native_fbx_import(self, ok: bool, asset: object, message: str) -> None:
        if not ok or asset is None:
            self._resolved_shaded_status = f"Scene import failed: {message}"
            self.update_viewport_status()
            if self.isVisible():
                QMessageBox.warning(self, "Scene Import Failed", str(message))
            return
        try:
            model = FBXMeshModel.from_native_fbx_asset(asset)
            graph, blobs = asset.to_editable_rig_graph()
            self._clear_dcc_timeline_snapshot_cache()
            self._dcc_scene_snapshots = {}
            self._dcc_snapshot_signatures = {}
            self._loaded_scene_providers = []
            self._dcc_deformation_bindings = {}
            self._dcc_deformation_binding_fingerprints = {}
            self._native_scene_model = model
            self._native_fbx_asset = asset
            self._native_scene_asset = asset
            self.mesh = model
            self.editable_rig_graph = graph
            self._federated_scene_blobs = blobs
            self._federated_scene_path = ""
            self._scene_lifecycle.mark_dirty()
            self._scene_lifecycle.mark_dirty()
            self._scene_lifecycle.mark_dirty()
            self._install_native_fbx_deformation_runtime(asset)
            manifest = dict(getattr(asset, "manifest", {}) or {})
            self._dcc_timeline_frame_start = int(manifest.get("frame_start", 1) or 1)
            self._dcc_timeline_frame_end = int(manifest.get("frame_end", self._dcc_timeline_frame_start) or self._dcc_timeline_frame_start)
            self._current_dcc_frame = self._dcc_timeline_frame_start
            timeline = getattr(self, "anim_timeline", None)
            sequence = getattr(timeline, "sequence", None)
            if sequence is not None:
                from tech_connector.ui.game_engine.animation_timeline import LayerStack

                frame_count = max(1, self._dcc_timeline_frame_end - self._dcc_timeline_frame_start + 1)
                sequence.frames = [LayerStack(sequence.width, sequence.height) for _ in range(frame_count)]
                sequence.current_frame_index = 0
                sequence.fps = max(1, int(round(float(manifest.get("fps", 24.0) or 24.0))))
                timeline.update_timeline_ui()
            self.sync_gpu_viewport(full=True)
            self.frame_mesh_camera()
            self.refresh_scene_outliner()
            self._resolved_shaded_status = (
                f"Editable {str(manifest.get('source_format') or 'scene').upper()} ready: "
                f"{len(manifest.get('meshes') or [])} mesh(es), "
                f"{len(graph.joints)} joint(s), {len(graph.skins)} skin(s)"
            )
            self.update_viewport_status()
            if hasattr(self, "canvas") and self.canvas:
                self.canvas.update()
        except Exception as exc:
            self._resolved_shaded_status = f"Imported scene build failed: {exc}"
            self.update_viewport_status()
            if self.isVisible():
                QMessageBox.warning(self, "Imported Scene Build Failed", str(exc))

    def _finish_native_fbx_import_thread(self, thread: QThread) -> None:
        if getattr(self, "_native_fbx_import_thread", None) is thread:
            self._native_fbx_import_thread = None
            self._native_fbx_import_worker = None

    def _detach_native_fbx_import_worker(self) -> None:
        thread = getattr(self, "_native_fbx_import_thread", None)
        worker = getattr(self, "_native_fbx_import_worker", None)
        self._native_fbx_import_thread = None
        self._native_fbx_import_worker = None
        if thread is None:
            return
        if worker is not None:
            worker.cancel()
            try:
                worker.finished.disconnect(self._capture_native_fbx_import)
            except Exception:
                pass
        try:
            thread.requestInterruption()
            thread.setParent(QApplication.instance())
        except Exception:
            pass

    def reset_demo_sphere(self):
        """Reset 3D camera transform and restore pristine default checkered grid & sci-fi emblem sample PBR texture map."""
        self.push_viewer_undo_state("Reset sphere")
        self.camera_rot_x = 15.0
        self.camera_rot_y = -30.0
        self.camera_zoom = 4.0
        self.camera_pan_x = 0.0
        self.camera_pan_y = 0.0
        self.mesh = FBXMeshModel("Sphere_Primitive_Demo")
        self._native_scene_model = None
        self._native_fbx_asset = None
        self._native_fbx_current_pose = None
        self._dcc_deformation_bindings.pop("native_fbx", None)
        self.sync_gpu_viewport(full=True)
        self.frame_mesh_camera()
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.update()
        if self.isVisible():
            QMessageBox.information(self, "3D Sphere Reset", "Successfully reset 3D camera transform and restored pristine checkered grid & sci-fi emblem texture map!")

    def proxy_at_viewport_position(
        self,
        pos: QPointF,
        max_distance_px: float = 24.0,
        candidate_filter: Any = None,
    ) -> dict[str, Any] | None:
        if not getattr(self, "canvas", None):
            return None
        camera = getattr(self, "viewport_camera", MayaViewportCamera())
        projection_rect = self.canvas.dcc_viewport_projection_rect()
        best_proxy = None
        best_distance = float(max_distance_px)
        for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []:
            if not isinstance(proxy, (dict, SceneProxyInstance)) or not bool(proxy.get("visible", True)):
                continue
            if candidate_filter is not None and not bool(candidate_filter(proxy)):
                continue
            center = proxy.get("center") or (0.0, 0.0, 0.0)
            point = self.shared_local_to_display_local((float(center[0]), float(center[1]), float(center[2])))
            sx, sy, _depth = camera.project_world_to_screen(
                point,
                max(1.0, projection_rect.width()),
                max(1.0, projection_rect.height()),
            )
            sx += projection_rect.x()
            sy += projection_rect.y()
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
        projection_rect = self.canvas.dcc_viewport_projection_rect()
        width = max(1.0, projection_rect.width())
        height = max(1.0, projection_rect.height())
        sx, sy, depth = camera.project_world_to_screen(center, width, height)
        sx += projection_rect.x()
        sy += projection_rect.y()
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
            ex += projection_rect.x()
            ey += projection_rect.y()
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
        raw_total = tuple(
            float(v) + shared_delta[i]
            for i, v in enumerate(proxy.get("_pending_shared_delta") or (0.0, 0.0, 0.0))
        )
        proxy["_pending_shared_delta"] = raw_total
        snap = float((getattr(self, "_transform_snap_settings", {}) or {}).get("translation", 0.0) or 0.0)
        if snap > 0.0:
            snapped_total = tuple(round(value / snap) * snap for value in raw_total)
            previous = tuple(proxy.get("_pending_shared_snapped_delta") or (0.0, 0.0, 0.0))
            shared_delta = tuple(snapped_total[i] - float(previous[i]) for i in range(3))
            proxy["_pending_shared_snapped_delta"] = snapped_total
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
        source_key = getattr(self, "_proxy_source_key", lambda value: str(value.get("source_key") or ""))(proxy)
        if source_key == getattr(self, "_camera_pivot_source_key", ""):
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
            snap = float((getattr(self, "_transform_snap_settings", {}) or {}).get("rotation", 0.0) or 0.0)
            if snap > 0.0: rotation = [round(float(value) / snap) * snap for value in rotation]
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
            snap = float((getattr(self, "_transform_snap_settings", {}) or {}).get("scale", 0.0) or 0.0)
            if snap > 0.0: values = [max(0.001, round(float(value) / snap) * snap) for value in values]
            local_transform["scale"] = values[:3]
            proxy["_pending_scale_absolute"] = tuple(float(v) for v in values[:3])
        proxy["local_transform"] = local_transform
        self._resolved_shaded_status = f"{mode} {axis}"
        self.update_viewport_status()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _commit_native_fbx_transform_override(
        self,
        native_id: str,
        *,
        translation_delta_shared: tuple[float, float, float] | None = None,
        rotation: tuple[float, float, float] | None = None,
        scale: tuple[float, float, float] | None = None,
    ) -> None:
        """Persist one local FBX object override and rebuild from immutable source buffers."""
        native_model = getattr(self, "_native_scene_model", None)
        if native_model is None:
            raise RuntimeError("No editable native FBX asset is loaded.")
        manifest = copy.deepcopy(dict(getattr(native_model, "native_fbx_manifest", {}) or {}))
        mesh_item = next(
            (
                item for item in manifest.get("meshes") or []
                if str(item.get("native_id") or item.get("name") or "") == str(native_id)
            ),
            None,
        )
        if mesh_item is None:
            raise KeyError(f"Native FBX object does not exist: {native_id}")
        authored = dict(mesh_item.get("tech_connector_transform") or {})
        if translation_delta_shared is not None:
            previous = list(authored.get("translation_shared_cm") or (0.0, 0.0, 0.0))
            previous = (previous + [0.0, 0.0, 0.0])[:3]
            authored["translation_shared_cm"] = [
                float(previous[index]) + float(translation_delta_shared[index])
                for index in range(3)
            ]
        if rotation is not None:
            authored["rotation_degrees"] = [float(value) for value in rotation[:3]]
        if scale is not None:
            authored["scale"] = [max(0.001, float(value)) for value in scale[:3]]
        mesh_item["tech_connector_transform"] = authored

        float_bytes = (getattr(self, "_federated_scene_blobs", {}) or {}).get("native_fbx/buffers.f32", b"")
        integer_bytes = (getattr(self, "_federated_scene_blobs", {}) or {}).get("native_fbx/buffers.u32", b"")
        if not float_bytes or not integer_bytes:
            raise RuntimeError("The native FBX source buffers are not available for an editable rebuild.")
        from tech_connector.game_engine.scene.native_fbx_service import NativeFbxAsset

        packed_floats = array.array("f")
        packed_floats.frombytes(float_bytes)
        packed_integers = array.array("I")
        packed_integers.frombytes(integer_bytes)
        asset = NativeFbxAsset(
            str(getattr(native_model, "source_path", "") or ""),
            manifest,
            packed_floats,
            packed_integers,
        )
        replacement = FBXMeshModel.from_native_fbx_asset(asset)
        selected_key = f"native_fbx:{native_id}"
        preserved_center = getattr(self.mesh, "scene_center", None)
        preserved_scale = getattr(self.mesh, "scene_scale", None)
        self._native_scene_model = replacement
        self._native_fbx_asset = asset
        self._install_native_fbx_deformation_runtime(asset)
        self.mesh = self._compose_loaded_scene_model(
            scene_center=preserved_center,
            scene_scale=preserved_scale,
        )
        self._selected_scene_proxy = next(
            (
                proxy for proxy in getattr(self.mesh, "scene_proxy_objects", []) or []
                if str(proxy.get("source_key") or "") == selected_key
                or (
                    str(proxy.get("provider_id") or "") == "native_fbx"
                    and str(proxy.get("native_id") or "") == str(native_id)
                )
            ),
            None,
        )
        self.sync_gpu_viewport(full=True)
        self.refresh_scene_outliner()
        if hasattr(self, "canvas") and self.canvas:
            self.canvas.update()

    def _install_native_fbx_deformation_runtime(self, asset: Any) -> dict[str, Any] | None:
        """Compile one native skin once; subsequent rig edits upload only joint matrices."""
        if not isinstance(getattr(self, "editable_rig_graph", None), EditableRigGraph):
            return None
        binding = asset.build_deformation_binding(self.editable_rig_graph)
        if not binding.get("meshes"):
            self._dcc_deformation_bindings.pop("native_fbx", None)
            self._native_fbx_current_pose = None
            return None
        self._dcc_deformation_bindings["native_fbx"] = binding
        self._native_fbx_current_pose = binding.get("initial_pose")
        return binding

    def _apply_native_fbx_animation_frame(self, frame: int) -> tuple[bool, str]:
        asset = getattr(self, "_native_fbx_asset", None)
        binding = (getattr(self, "_dcc_deformation_bindings", {}) or {}).get("native_fbx")
        if asset is None or not isinstance(binding, dict):
            return False, ""
        try:
            pose = asset.deformation_pose_at_frame(
                binding,
                int(frame),
                graph=self.editable_rig_graph,
            )
            binding["current_pose"] = pose
            self._native_fbx_current_pose = pose
            changed = False
            gpu = getattr(self, "gpu_viewport", None)
            if self.gpu_surface_active() and gpu is not None:
                changed = bool(gpu.update_deformation_pose("native_fbx", binding, pose))
            selected_joint_id = str(getattr(self, "_selected_rig_joint_id", "") or "")
            if selected_joint_id:
                self._selected_scene_proxy = self._scene_proxy_for_native_rig_joint(selected_joint_id)
            if getattr(self, "canvas", None) is not None:
                self.canvas.update()
            source = str(pose.get("pose_source") or "local_graph").replace("_", " ")
            return changed, f"Native FBX frame {int(frame)}: {source} pose"
        except Exception as exc:
            return False, f"Native FBX frame {int(frame)} failed: {exc}"

    def _refresh_native_fbx_rig_pose(self) -> tuple[bool, str]:
        binding = (getattr(self, "_dcc_deformation_bindings", {}) or {}).get("native_fbx")
        if not isinstance(binding, dict):
            return False, "The native FBX has no compiled skin binding."
        from tech_connector.game_engine.scene.native_fbx_service import build_native_fbx_deformation_pose

        pose = build_native_fbx_deformation_pose(self.editable_rig_graph, binding)
        binding["current_pose"] = pose
        self._native_fbx_current_pose = pose
        changed = False
        gpu = getattr(self, "gpu_viewport", None)
        if self.gpu_surface_active() and gpu is not None:
            changed = bool(gpu.update_deformation_pose("native_fbx", binding, pose))
        selected_joint_id = str(getattr(self, "_selected_rig_joint_id", "") or "")
        if selected_joint_id:
            self._selected_scene_proxy = self._scene_proxy_for_native_rig_joint(selected_joint_id)
        if getattr(self, "canvas", None) is not None:
            self.canvas.update()
        return changed, "Native rig pose evaluated locally."

    def _commit_native_fbx_joint_transform(
        self,
        joint_id: str,
        *,
        translation_delta_shared: tuple[float, float, float] | None = None,
        rotation: tuple[float, float, float] | None = None,
        scale: tuple[float, float, float] | None = None,
    ) -> None:
        from tech_connector.game_engine.scene.native_fbx_service import apply_native_joint_matrix_override

        apply_native_joint_matrix_override(
            self.editable_rig_graph,
            joint_id,
            translation_delta=translation_delta_shared,
            rotation_degrees=rotation,
            scale=scale,
        )
        self._refresh_native_fbx_rig_pose()

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
            if provider == "tech_connector":
                entity = self._runtime_entity_for_proxy(proxy)
                if entity is None: return False, "The selected level actor no longer exists."
                transform = entity.setdefault("transform", {})
                if rotation is not None: transform["rotation"] = [float(v) for v in rotation]
                if scale is not None: transform["scale"] = [float(v) for v in scale]
                proxy["sync_state"] = "dirty"; self._scene_lifecycle.mark_dirty()
                self._resolved_shaded_status = f"{mode} committed: {entity.get('name') or native_id}"
                self.auto_key_committed_transform(proxy, "rotate" if rotation is not None else "scale"); self.update_viewport_status()
                return True, self._resolved_shaded_status
            if dcc_provider_base_key(provider) == "native_fbx":
                if native_id in self.editable_rig_graph.joints:
                    self._commit_native_fbx_joint_transform(
                        native_id,
                        rotation=tuple(float(v) for v in rotation) if rotation is not None else None,
                        scale=tuple(float(v) for v in scale) if scale is not None else None,
                    )
                    target_label = "joint"
                else:
                    self._commit_native_fbx_transform_override(
                        native_id,
                        rotation=tuple(float(v) for v in rotation) if rotation is not None else None,
                        scale=tuple(float(v) for v in scale) if scale is not None else None,
                    )
                    target_label = "object"
                self._resolved_shaded_status = (
                    f"{mode} committed: native FBX {target_label} {proxy.get('name') or native_id}"
                )
                self.auto_key_committed_transform(proxy, "rotate" if rotation is not None else "scale")
                self.update_viewport_status()
                return True, self._resolved_shaded_status
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
            self.auto_key_committed_transform(proxy, "rotate" if rotation is not None else "scale")
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
        snapped_delta = proxy.pop("_pending_shared_snapped_delta", None)
        if isinstance(proxy, SceneProxyInstance):
            shared_delta = tuple(float(v) for v in proxy.pending_shared_delta)
            proxy.pending_shared_delta = (0.0, 0.0, 0.0)
        else:
            shared_delta = tuple(float(v) for v in (proxy.pop("_pending_shared_delta", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)))
        if snapped_delta is not None:
            shared_delta = tuple(float(v) for v in snapped_delta)
        if max(abs(v) for v in shared_delta) <= 1.0e-6:
            return True, "No transform change to commit."
        provider = str(proxy.get("provider_id") or "")
        native_id = str(proxy.get("native_id") or "")
        if not provider or not native_id:
            return False, "Selected proxy does not have a native target."
        try:
            if provider == "tech_connector":
                entity = self._runtime_entity_for_proxy(proxy)
                if entity is None: return False, "The selected level actor no longer exists."
                transform = entity.setdefault("transform", {}); transform["position"] = [float(v) for v in (proxy.get("local_transform") or {}).get("translation", proxy.get("center") or (0.0, 0.0, 0.0))]
                proxy["sync_state"] = "dirty"; self._scene_lifecycle.mark_dirty()
                self._resolved_shaded_status = f"Moved level actor: {entity.get('name') or native_id}"
                self.auto_key_committed_transform(proxy, "translate"); self.update_viewport_status()
                return True, self._resolved_shaded_status
            if dcc_provider_base_key(provider) == "native_fbx":
                if native_id in self.editable_rig_graph.joints:
                    self._commit_native_fbx_joint_transform(
                        native_id,
                        translation_delta_shared=shared_delta,
                    )
                    target_label = "joint"
                else:
                    self._commit_native_fbx_transform_override(
                        native_id,
                        translation_delta_shared=shared_delta,
                    )
                    target_label = "object"
                self._resolved_shaded_status = (
                    f"Moved native FBX {target_label}: {proxy.get('name') or native_id}"
                )
                self.auto_key_committed_transform(proxy, "translate")
                self.update_viewport_status()
                return True, self._resolved_shaded_status
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
            self.auto_key_committed_transform(proxy, "translate")
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
        if dcc_provider_base_key(provider) == "native_fbx":
            self._commit_native_fbx_transform_override(
                native_id,
                translation_delta_shared=shared_delta,
            )
            return
        if not self._allow_dcc_outbound("selected_object", reason="explicit object move"):
            raise RuntimeError("Selected object outbound is disabled by DCC write policy.")
        snapshot = (getattr(self, "_dcc_scene_snapshots", {}) or {}).get(provider, {})
        unit_linear = str(snapshot.get("unit_linear") or "")
        native_delta = provider_view_to_world(provider, *shared_delta, unit_linear, str(snapshot.get("up_axis") or ""))
        bridge = self._scene_snapshot_bridge(provider)
        provider_base = dcc_provider_base_key(provider)
        if provider_base == "maya":
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
        elif provider_base == "blender":
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
        elif provider_base == "motionbuilder":
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
        elif provider_base == "unreal":
            response = bridge.execute_python(self._unreal_translate_actor_code(native_id, native_delta), timeout=10.0, reset_globals=True)
            ok = bool(response.get("ok"))
            raw = response.get("error") or response.get("stdout") or response.get("output") or response.get("result") or response.get("raw") or str(response)
        else:
            raise ValueError(f"Transform edits are not implemented for {provider} yet.")
        if not ok:
            raise RuntimeError(raw)
