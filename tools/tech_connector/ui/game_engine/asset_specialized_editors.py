"""Interactive, serializable controls used by dedicated engine asset editors."""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave
from typing import Any
import uuid

from tech_connector.game_engine.assets import (
    AssetDatabase, PrefabService, SUPPORTED_BUILD_CONFIGURATIONS, SUPPORTED_BUILD_PLATFORMS,
    FABRIC_PRESETS, RAGDOLL_PRESETS, automatic_cloth_maps, audit_input_map,
    CHARACTER_PERFORMANCE_PROFILES, generate_bone_lods, recommended_mesh_lods,
    constraint_from_preset, plan_build_profile, validate_constraint_properties,
    validate_character_lods, validate_skeleton_properties, validate_skin_binding_properties,
    validate_physics_asset_properties,
    GEOMETRY_OPTIMIZATION_PRESETS, GEOMETRY_PROCESSORS, geometry_optimization_preset,
    plan_geometry_optimization,
    GROOM_GROUP_PRESETS, HAIR_MATERIAL_PRESETS, automatic_groom_lods, hair_material_preset,
    validate_groom_binding_properties, validate_groom_properties,
    MATERIAL_BLEND_MODES, MATERIAL_DOMAINS, MATERIAL_SHADING_MODELS,
    MaterialService, analyze_material_graph, material_preset,
    EFFECT_PHASES, MODULE_LIBRARY, RENDERER_TYPES, SIMULATION_TARGETS,
    estimate_effect_cost,
    COMPONENT_TYPES, FIELD_TYPES,
    GAMEPLAY_CLASS_KINDS, REPLICATION_MODES, GameplayClassService, ProceduralGraphAssetService,
)
from tech_connector.game_engine.authoring.procedural_graph_tooling_service import build_procedural_execution_plan
from tech_connector.game_engine.authoring.tc_physics_joint_service import PHYSICS_JOINT_PRESETS, PHYSICS_JOINT_TYPES
from tech_connector.game_engine.runtime.tc_effect_system_service import QUALITY_PROFILES
from tech_connector.game_engine.runtime.graph_debugger_service import default_graph_debug_session_manager
from tech_connector.game_engine.deformation.skinning_tool_service import normalize_skin_weights
from tech_connector.game_engine.assets.animation_asset_service import evaluate_animation_controller, evaluate_blend_space, validate_animation_clip, validate_blend_space

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QLineEdit, QPlainTextEdit, QSlider, QSpinBox, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover - minimal Qt deployments still retain waveform editing.
    QAudioOutput = QMediaPlayer = None


GRAPH_NODE_LIBRARY: dict[str, tuple[dict[str, Any], ...]] = {
    "procedural_geometry": (
        {"title": "Grid Points", "opcode": "grid_points", "inputs": [], "outputs": ["geometry:data"]},
        {"title": "Scatter Bounds", "opcode": "scatter_bounds", "inputs": [], "outputs": ["points:data"]},
        {"title": "Sample Spline", "opcode": "spline_sample", "inputs": [], "outputs": ["points:data"]},
        {"title": "Transform Points", "opcode": "transform_points", "inputs": ["geometry:data"], "outputs": ["geometry:data"]},
        {"title": "Repeat Points", "opcode": "repeat_transform", "inputs": ["geometry:data"], "outputs": ["geometry:data"]},
        {"title": "Noise Attribute", "opcode": "noise_attribute", "inputs": ["geometry:data"], "outputs": ["geometry:data"]},
        {"title": "Filter Attribute", "opcode": "filter_attribute", "inputs": ["geometry:data"], "outputs": ["geometry:data"]},
        {"title": "Select Asset", "opcode": "select_asset", "inputs": ["points:data"], "outputs": ["points:data"]},
        {"title": "Instance on Points", "opcode": "instance_on_points", "inputs": ["points:data"], "outputs": ["instances:data"]},
        {"title": "Project Heightfield", "opcode": "project_heightfield", "inputs": ["points:data"], "outputs": ["points:data"]},
        {"title": "Filter Slope", "opcode": "filter_slope", "inputs": ["points:data"], "outputs": ["points:data"]},
        {"title": "Biome Scatter", "opcode": "biome_scatter", "inputs": ["terrain:data"], "outputs": ["instances:data"]},
        {"title": "Hydraulic Erosion", "opcode": "terrain_hydraulic_erosion", "inputs": ["terrain:data"], "outputs": ["terrain:data"]},
        {"title": "Shape Grammar Spline", "opcode": "shape_grammar_spline", "inputs": ["spline:data"], "outputs": ["geometry:data"]},
        {"title": "Curve Line", "opcode": "curve_line", "inputs": [], "outputs": ["curve:data"]},
        {"title": "Curve Circle", "opcode": "curve_circle", "inputs": [], "outputs": ["curve:data"]},
        {"title": "Curve to Mesh", "opcode": "curve_to_mesh", "inputs": ["curve:data"], "outputs": ["mesh:data"]},
        {"title": "Store Field", "opcode": "field_set", "inputs": ["geometry:data"], "outputs": ["geometry:data"], "parameters": {"domain": "point", "name": "value", "data_type": "float", "value": 0.0}},
        {"title": "Field Math", "opcode": "field_math", "inputs": ["geometry:data"], "outputs": ["geometry:data"], "parameters": {"domain": "point", "source": "value", "target": "value", "operation": "multiply", "value": 1.0}},
        {"title": "Map Field Domain", "opcode": "field_map_domain", "inputs": ["geometry:data"], "outputs": ["geometry:data"], "parameters": {"source_domain": "point", "target_domain": "face", "source": "value", "target": "value"}},
        {"title": "Cube", "opcode": "mesh_cube", "inputs": [], "outputs": ["mesh:data"]},
        {"title": "Grid Mesh", "opcode": "mesh_grid", "inputs": [], "outputs": ["mesh:data"]},
        {"title": "Cylinder", "opcode": "mesh_cylinder", "inputs": [], "outputs": ["mesh:data"]},
        {"title": "UV Sphere", "opcode": "mesh_uv_sphere", "inputs": [], "outputs": ["mesh:data"]},
        {"title": "Join Geometry", "opcode": "mesh_join", "inputs": ["geometry:data"], "outputs": ["mesh:data"]},
        {"title": "Transform Geometry", "opcode": "mesh_transform", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Extrude Faces", "opcode": "mesh_extrude_faces", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Subdivide", "opcode": "mesh_subdivide", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Bevel Edges", "opcode": "mesh_bevel_edges", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Delete Faces", "opcode": "mesh_delete_faces", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Weld", "opcode": "mesh_weld", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Compute Normals", "opcode": "mesh_compute_normals", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Generate UV", "opcode": "mesh_generate_uv", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Mesh Boolean", "opcode": "mesh_boolean", "inputs": ["mesh:data", "mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Smooth Geometry", "opcode": "mesh_smooth", "inputs": ["mesh:data"], "outputs": ["mesh:data"], "parameters": {"iterations": 1, "factor": 0.5}},
        {"title": "Displace Geometry", "opcode": "mesh_displace", "inputs": ["mesh:data"], "outputs": ["mesh:data"], "parameters": {"distance": 0.1, "field": ""}},
        {"title": "Voxel Remesh", "opcode": "mesh_voxel_remesh", "inputs": ["mesh:data"], "outputs": ["mesh:data"], "parameters": {"voxel_size": 0.1}},
        {"title": "Mesh to Volume", "opcode": "mesh_to_volume", "inputs": ["mesh:data"], "outputs": ["volume:data"], "parameters": {"resolution": 16}},
        {"title": "Volume to Mesh", "opcode": "volume_to_mesh", "inputs": ["volume:data"], "outputs": ["mesh:data"]},
        {"title": "Triangulate", "opcode": "mesh_triangulate", "inputs": ["mesh:data"], "outputs": ["mesh:data"]},
        {"title": "Merge", "opcode": "merge", "inputs": ["geometry:data"], "outputs": ["geometry:data"]},
        {"title": "Output", "opcode": "output", "inputs": ["geometry:data"], "outputs": []},
    ),
    "material": (
        {"title": "Scalar Parameter", "opcode": "parameter", "inputs": [], "outputs": ["value:float"]},
        {"title": "Vector Parameter", "opcode": "parameter", "inputs": [], "outputs": ["value:vec4"]},
        {"title": "Static Switch", "opcode": "static_switch", "inputs": ["false:any", "true:any"], "outputs": ["result:any"]},
        {"title": "Texture Sample", "opcode": "sample_texture", "inputs": ["uv:vec2"], "outputs": ["color:vec4"]},
        {"title": "Normal Map", "opcode": "sample_normal", "inputs": ["uv:vec2", "strength:float"], "outputs": ["normal:vec3"]},
        {"title": "Virtual Texture", "opcode": "virtual_texture", "inputs": ["uv:vec2"], "outputs": ["color:vec4"]},
        {"title": "Texture Coordinates", "opcode": "uv", "inputs": [], "outputs": ["uv:vec2"]},
        {"title": "Vertex Color", "opcode": "vertex_color", "inputs": [], "outputs": ["color:vec4"]},
        {"title": "Ramp", "opcode": "color_ramp", "inputs": ["factor:float"], "outputs": ["color:vec4"]},
        {"title": "Noise", "opcode": "noise", "inputs": ["position:vec3", "scale:float"], "outputs": ["value:float", "color:vec4"]},
        {"title": "Add", "opcode": "add", "inputs": ["a:any", "b:any"], "outputs": ["result:any"]},
        {"title": "Subtract", "opcode": "subtract", "inputs": ["a:any", "b:any"], "outputs": ["result:any"]},
        {"title": "Multiply", "opcode": "multiply", "inputs": ["a:any", "b:any"], "outputs": ["result:any"]},
        {"title": "Divide", "opcode": "divide", "inputs": ["a:any", "b:any"], "outputs": ["result:any"]},
        {"title": "Lerp", "opcode": "lerp", "inputs": ["a:any", "b:any", "alpha:float"], "outputs": ["result:any"]},
        {"title": "Clamp", "opcode": "clamp", "inputs": ["value:any", "min:float", "max:float"], "outputs": ["result:any"]},
        {"title": "One Minus", "opcode": "one_minus", "inputs": ["value:any"], "outputs": ["result:any"]},
        {"title": "Fresnel", "opcode": "fresnel", "inputs": ["normal:vec3", "power:float"], "outputs": ["factor:float"]},
        {"title": "Parallax", "opcode": "parallax", "inputs": ["height:float", "uv:vec2", "scale:float"], "outputs": ["uv:vec2"]},
        {"title": "Material Function", "opcode": "material_function", "inputs": ["input:any"], "outputs": ["result:any"]},
        {"title": "Surface Output", "opcode": "surface_output", "inputs": ["base_color:vec4", "roughness:float", "metallic:float"], "outputs": []},
    ),
    "shader": (
        {"title": "Attribute", "opcode": "attribute", "inputs": [], "outputs": ["value:any"]},
        {"title": "Uniform Parameter", "opcode": "parameter", "inputs": [], "outputs": ["value:any"]},
        {"title": "Texture Sample", "opcode": "sample_texture", "inputs": ["uv:vec2"], "outputs": ["color:vec4"]},
        {"title": "Math", "opcode": "math", "inputs": ["a:float", "b:float"], "outputs": ["result:float"]},
        {"title": "Vector Math", "opcode": "vector_math", "inputs": ["a:vec3", "b:vec3"], "outputs": ["result:vec3"]},
        {"title": "Static Switch", "opcode": "static_switch", "inputs": ["false:any", "true:any"], "outputs": ["result:any"]},
        {"title": "Shader Function", "opcode": "material_function", "inputs": ["input:any"], "outputs": ["result:any"]},
        {"title": "Shader Output", "opcode": "shader_output", "inputs": ["result:any"], "outputs": []},
    ),
    "animation_state": (
        {"title": "State", "opcode": "state", "inputs": ["enter:flow"], "outputs": ["exit:flow"]},
        {"title": "Clip Player", "opcode": "clip_player", "inputs": ["time:float", "rate:float"], "outputs": ["pose:pose"]},
        {"title": "Blend Space", "opcode": "blend_space", "inputs": ["x:float", "y:float"], "outputs": ["pose:pose"]},
        {"title": "Transition", "opcode": "transition", "inputs": ["condition:bool"], "outputs": ["flow:flow"]},
        {"title": "State Machine", "opcode": "animation_state_machine", "inputs": ["parameters:data"], "outputs": ["pose:pose"]},
        {"title": "Layered Blend Per Bone", "opcode": "layered_blend_per_bone", "inputs": ["base:pose", "layer:pose", "weight:float"], "outputs": ["pose:pose"]},
        {"title": "Apply Additive", "opcode": "apply_additive", "inputs": ["base:pose", "additive:pose", "weight:float"], "outputs": ["pose:pose"]},
        {"title": "Slot", "opcode": "animation_slot", "inputs": ["source:pose"], "outputs": ["pose:pose"]},
        {"title": "Save Cached Pose", "opcode": "cache_pose", "inputs": ["pose:pose"], "outputs": ["pose:pose"]},
        {"title": "Two Bone IK", "opcode": "two_bone_ik", "inputs": ["pose:pose", "goal:transform", "pole:vec3"], "outputs": ["pose:pose"]},
        {"title": "Output Pose", "opcode": "output_pose", "inputs": ["pose:pose"], "outputs": []},
    ),
    "audio": (
        {"title": "Wave Player", "opcode": "wave_player", "inputs": ["play:flow"], "outputs": ["audio:audio"]},
        {"title": "Random", "opcode": "random", "inputs": ["choices:audio[]"], "outputs": ["audio:audio"]},
        {"title": "Sequence", "opcode": "sequence", "inputs": ["clips:audio[]"], "outputs": ["audio:audio"]},
        {"title": "Mixer", "opcode": "mixer", "inputs": ["inputs:audio[]"], "outputs": ["audio:audio"]},
        {"title": "Switch", "opcode": "switch", "inputs": ["selector:int", "inputs:audio[]"], "outputs": ["audio:audio"]},
        {"title": "Crossfade", "opcode": "crossfade", "inputs": ["a:audio", "b:audio", "alpha:float"], "outputs": ["audio:audio"]},
        {"title": "Modulator", "opcode": "modulator", "inputs": ["audio:audio", "volume:float", "pitch:float"], "outputs": ["audio:audio"]},
        {"title": "Delay", "opcode": "delay", "inputs": ["audio:audio", "seconds:float"], "outputs": ["audio:audio"]},
        {"title": "Loop", "opcode": "loop", "inputs": ["audio:audio", "count:int"], "outputs": ["audio:audio"]},
        {"title": "Attenuation", "opcode": "attenuation", "inputs": ["audio:audio", "distance:float"], "outputs": ["audio:audio"]},
        {"title": "Envelope", "opcode": "envelope", "inputs": ["audio:audio"], "outputs": ["audio:audio", "envelope:float"]},
        {"title": "Filter", "opcode": "filter", "inputs": ["audio:audio", "cutoff:float"], "outputs": ["audio:audio"]},
        {"title": "Oscillator", "opcode": "oscillator", "inputs": ["frequency:float"], "outputs": ["audio:audio"]},
        {"title": "Noise", "opcode": "noise", "inputs": [], "outputs": ["audio:audio"]},
        {"title": "Sound Output", "opcode": "output", "inputs": ["audio:audio"], "outputs": []},
    ),
    "simulation": (
        {"title": "Emitter", "opcode": "emitter", "inputs": ["activate:bool"], "outputs": ["particles:stream"]},
        {"title": "Gravity", "opcode": "gravity", "inputs": ["stream:stream"], "outputs": ["stream:stream"]},
        {"title": "Wind Field", "opcode": "wind", "inputs": ["stream:stream"], "outputs": ["stream:stream"]},
        {"title": "Collision", "opcode": "collision", "inputs": ["stream:stream"], "outputs": ["stream:stream"]},
        {"title": "Solver Output", "opcode": "solver_output", "inputs": ["stream:stream"], "outputs": []},
    ),
    "gameplay": (
        {"title": "Read Input Axis", "opcode": "input.read_axis", "inputs": ["axis:string"], "outputs": ["result:vector2"], "parameters": {"axis": "Move"}},
        {"title": "Calculate Movement", "opcode": "movement.calculate_velocity", "inputs": ["direction:vector2", "speed:float", "acceleration:float", "target:string"], "outputs": ["result:vector3"], "parameters": {"speed": 6.0, "acceleration": 24.0, "target": "Self"}},
        {"title": "Set Actor Velocity", "opcode": "actor.set_velocity", "inputs": ["target:string", "velocity:vector3"], "outputs": ["result:any"], "parameters": {"target": "Self"}},
        {"title": "Emit Gameplay Event", "opcode": "event.emit", "inputs": ["event:string", "payload:map"], "outputs": ["result:any"], "parameters": {"event": "Gameplay.Event", "payload": {}}},
        {"title": "Set Variable", "opcode": "variable.set", "inputs": ["name:string", "value:any"], "outputs": ["result:any"], "parameters": {"name": "Value", "value": 0}},
        {"title": "Add Variable", "opcode": "variable.add", "inputs": ["name:string", "amount:float"], "outputs": ["result:float"], "parameters": {"name": "Value", "amount": 1.0}},
        {"title": "Greater Than", "opcode": "branch.greater", "inputs": ["name:string", "threshold:float", "event:string"], "outputs": ["result:bool"], "parameters": {"name": "Value", "threshold": 0.0, "event": ""}},
        {"title": "Spawn Entity", "opcode": "entity.spawn", "inputs": ["name:string", "x:float", "y:float", "z:float"], "outputs": ["result:string"], "parameters": {"name": "Spawned", "x": 0.0, "y": 0.0, "z": 0.0}},
        {"title": "Get Component Position", "opcode": "component.get_position", "inputs": ["target:string"], "outputs": ["result:vector3"], "parameters": {"target": "Self"}},
        {"title": "Set Component Position", "opcode": "component.set_position", "inputs": ["target:string", "x:float", "y:float", "z:float"], "outputs": ["result:any"], "parameters": {"target": "Self", "x": 0.0, "y": 0.0, "z": 0.0}},
        {"title": "Set UI Text", "opcode": "ui.set_text", "inputs": ["text:string"], "outputs": ["result:string"], "parameters": {"text": "Text"}},
        {"title": "Play Audio", "opcode": "audio.play", "inputs": ["asset:string"], "outputs": ["result:any"], "parameters": {"asset": ""}},
        {"title": "Write Save Game", "opcode": "save.write", "inputs": [], "outputs": ["result:any"], "parameters": {}},
    ),
    "gameplay_components": (
        {"title": "Scene Component", "opcode": "scene_component", "inputs": ["parent:component"], "outputs": ["component:component"]},
        {"title": "Mesh Component", "opcode": "mesh_component", "inputs": ["parent:component"], "outputs": ["component:component"]},
        {"title": "Collider Component", "opcode": "collider_component", "inputs": ["parent:component"], "outputs": ["component:component"]},
    ),
    "control_rig": (
        {"title": "Control", "opcode": "control", "inputs": ["parent:transform"], "outputs": ["transform:transform"]},
        {"title": "Get Transform", "opcode": "get_transform", "inputs": ["item:name"], "outputs": ["transform:transform"]},
        {"title": "Set Transform", "opcode": "set_transform", "inputs": ["item:name", "transform:transform", "weight:float"], "outputs": ["pose:pose"]},
        {"title": "Two Bone IK", "opcode": "two_bone_ik", "inputs": ["pose:pose", "goal:transform", "pole:vec3"], "outputs": ["pose:pose"]},
        {"title": "FABRIK", "opcode": "fabrik", "inputs": ["pose:pose", "goal:transform"], "outputs": ["pose:pose"]},
        {"title": "Aim", "opcode": "aim", "inputs": ["transform:transform", "target:vec3"], "outputs": ["transform:transform"]},
        {"title": "Parent Constraint", "opcode": "parent_constraint", "inputs": ["source:transform", "target:transform"], "outputs": ["transform:transform"]},
        {"title": "Blend Transform", "opcode": "blend_transform", "inputs": ["a:transform", "b:transform", "weight:float"], "outputs": ["transform:transform"]},
        {"title": "Sequence", "opcode": "sequence", "inputs": ["execute:flow"], "outputs": ["then:flow"]},
        {"title": "Output Pose", "opcode": "output_pose", "inputs": ["pose:pose"], "outputs": []},
    ),
}


class PrefabHierarchyEditorWidget(QWidget):
    """Prefab Mode hierarchy with visible inheritance and override state."""

    changed = Signal()

    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent)
        self.prefabs = PrefabService(project_root, database)
        self.asset_id = str(asset_id)
        self._settings: dict[str, Any] = {}
        self._loading = False
        root = QVBoxLayout(self)

        summary = QHBoxLayout()
        self.mode = QLabel("PREFAB", self)
        self.mode.setStyleSheet("font-weight:700; color:#72d9ca;")
        self.parent_link = QLabel("No parent Prefab", self)
        self.parent_link.setStyleSheet("color:#91aaba;")
        summary.addWidget(self.mode)
        summary.addWidget(self.parent_link)
        summary.addStretch(1)
        root.addLayout(summary)

        self.hierarchy = QTreeWidget(self)
        self.hierarchy.setHeaderLabels(["Entity / Component", "Stable ID", "State", "Source"])
        self.hierarchy.setSelectionMode(QAbstractItemView.SingleSelection)
        root.addWidget(self.hierarchy, 2)

        actions = QHBoxLayout()
        add_entity = QPushButton("Add Entity", self)
        remove_entity = QPushButton("Remove", self)
        restore_entity = QPushButton("Restore Inherited", self)
        add_entity.clicked.connect(self._add_entity)
        remove_entity.clicked.connect(self._remove_selected)
        restore_entity.clicked.connect(self._restore_selected)
        actions.addWidget(add_entity)
        actions.addWidget(remove_entity)
        actions.addWidget(restore_entity)
        actions.addStretch(1)
        root.addLayout(actions)

        override_title = QLabel("Variant / Instance Override Layer", self)
        override_title.setStyleSheet("font-weight:700; color:#d7e8f2;")
        root.addWidget(override_title)
        self.overrides = QTableWidget(0, 3, self)
        self.overrides.setHorizontalHeaderLabels(["Property Path", "Value", "State"])
        root.addWidget(self.overrides, 1)
        override_actions = QHBoxLayout()
        add_override = QPushButton("Add Override", self)
        remove_override = QPushButton("Revert Selected", self)
        add_override.clicked.connect(self._add_override)
        remove_override.clicked.connect(self._remove_override)
        override_actions.addWidget(add_override)
        override_actions.addWidget(remove_override)
        override_actions.addStretch(1)
        root.addLayout(override_actions)
        self.status = QLabel(
            "Inherited values remain linked to the parent. Overrides are explicit and can be reverted independently.", self
        )
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.overrides.itemChanged.connect(self._table_changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True
        self._settings = dict(values or {})
        base_id = str(self._settings.get("base_prefab_id") or "")
        self.mode.setText("PREFAB VARIANT" if base_id else "PREFAB")
        self.parent_link.setText(f"Parent: {base_id}" if base_id else "No parent Prefab")
        self._refresh_hierarchy()
        self.overrides.setRowCount(0)
        for path, value in sorted(dict(self._settings.get("variant_overrides") or {}).items()):
            row = self.overrides.rowCount()
            self.overrides.insertRow(row)
            self.overrides.setItem(row, 0, QTableWidgetItem(str(path)))
            self.overrides.setItem(row, 1, QTableWidgetItem(self._render(value)))
            state = QTableWidgetItem("Overridden")
            state.setFlags(state.flags() & ~Qt.ItemIsEditable)
            self.overrides.setItem(row, 2, state)
        self._loading = False

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        layer: dict[str, Any] = {}
        for row in range(self.overrides.rowCount()):
            path_item = self.overrides.item(row, 0)
            value_item = self.overrides.item(row, 1)
            path = str(path_item.text() if path_item else "").strip()
            if path:
                layer[path] = self._parse(value_item.text() if value_item else "")
        result["variant_overrides"] = layer
        return result

    def validation_issues(self) -> list[str]:
        return [item.message for item in self.prefabs.validate(self.asset_id) if item.severity == "error"]

    def _refresh_hierarchy(self) -> None:
        self.hierarchy.clear()
        base_id = str(self._settings.get("base_prefab_id") or "")
        removed = {str(value) for value in self._settings.get("removed_entity_ids") or ()}
        added_ids = {str(item.get("entity_id") or "") for item in self._settings.get("added_entities") or ()}
        try:
            entities = list(self.prefabs.resolve(self.asset_id).entities) if base_id else list(self._settings.get("entities") or ())
            if base_id:
                base_entities = list(self.prefabs.resolve(base_id).entities)
                existing = {str(item.get("entity_id") or "") for item in entities}
                entities.extend(item for item in base_entities if str(item.get("entity_id") or "") in removed and str(item.get("entity_id") or "") not in existing)
        except (KeyError, ValueError):
            entities = [*(self._settings.get("entities") or ()), *(self._settings.get("added_entities") or ())]
        for entity in entities:
            entity_id = str(entity.get("entity_id") or "")
            state = "Removed" if entity_id in removed else ("Added" if entity_id in added_ids else ("Inherited" if base_id else "Local"))
            source = str(entity.get("prefab_asset_id") or entity.get("source_asset_id") or (base_id if state == "Inherited" else self.asset_id))
            item = QTreeWidgetItem([str(entity.get("name") or "Entity"), entity_id, state, source])
            item.setData(0, Qt.UserRole, entity_id)
            if state == "Removed":
                item.setForeground(2, QColor("#ef8793"))
            elif state == "Inherited":
                item.setForeground(2, QColor("#91aaba"))
            else:
                item.setForeground(2, QColor("#72d9ca"))
            self.hierarchy.addTopLevelItem(item)
            components = entity.get("components")
            if isinstance(components, dict):
                for component_name in sorted(components):
                    child = QTreeWidgetItem([str(component_name), "", state, "Component"])
                    child.setFlags(child.flags() & ~Qt.ItemIsSelectable)
                    item.addChild(child)
            nested_id = str(entity.get("prefab_asset_id") or entity.get("source_asset_id") or "")
            if nested_id:
                self._append_nested_prefab(item, nested_id, entity, ancestors=(self.asset_id,))
        self.hierarchy.expandAll()
        for column in range(4):
            self.hierarchy.resizeColumnToContents(column)

    def _append_nested_prefab(
        self,
        parent: QTreeWidgetItem,
        asset_id: str,
        reference: dict[str, Any],
        *,
        ancestors: tuple[str, ...],
    ) -> None:
        """Expose linked Prefab contents without making them editable in this stage."""
        link = QTreeWidgetItem(["Nested Prefab", "", "Linked", asset_id])
        link.setFlags(link.flags() & ~Qt.ItemIsSelectable)
        link.setForeground(2, QColor("#7dc4ff"))
        parent.addChild(link)
        if asset_id in ancestors:
            error = QTreeWidgetItem(["Cycle detected", "", "Error", asset_id])
            error.setFlags(error.flags() & ~Qt.ItemIsSelectable)
            error.setForeground(2, QColor("#ef8793"))
            link.addChild(error)
            return
        try:
            resolved = self.prefabs.resolve(asset_id, expand_nested=True)
            nested_entities = list(resolved.entities)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            error = QTreeWidgetItem([str(exc), "", "Unavailable", asset_id])
            error.setFlags(error.flags() & ~Qt.ItemIsSelectable)
            error.setForeground(2, QColor("#ef8793"))
            link.addChild(error)
            return
        overrides = dict(reference.get("prefab_overrides") or {})
        for nested in nested_entities:
            entity_id = str(nested.get("entity_id") or "")
            overridden = any(path == entity_id or path.startswith(entity_id + ".") for path in overrides)
            state = "Overridden" if overridden else "Inherited"
            child = QTreeWidgetItem([str(nested.get("name") or "Entity"), entity_id, state, asset_id])
            child.setFlags(child.flags() & ~Qt.ItemIsSelectable)
            child.setForeground(2, QColor("#72d9ca" if overridden else "#91aaba"))
            link.addChild(child)
            components = nested.get("components")
            names = sorted(components) if isinstance(components, dict) else [str(value.get("type") or "Component") for value in components or () if isinstance(value, dict)]
            for component_name in names:
                component = QTreeWidgetItem([str(component_name), "", state, "Component"])
                component.setFlags(component.flags() & ~Qt.ItemIsSelectable)
                child.addChild(component)
            child_nested_id = str(nested.get("prefab_asset_id") or nested.get("source_asset_id") or "")
            if child_nested_id:
                self._append_nested_prefab(child, child_nested_id, nested, ancestors=(*ancestors, asset_id))

    def _add_entity(self) -> None:
        key = "added_entities" if self._settings.get("base_prefab_id") else "entities"
        entities = list(self._settings.get(key) or ())
        suffix = len(entities) + 1
        existing = {str(item.get("entity_id") or "") for item in entities}
        entity_id = f"Entity_{suffix}"
        while entity_id in existing:
            suffix += 1
            entity_id = f"Entity_{suffix}"
        entities.append({"entity_id": entity_id, "name": f"Entity {suffix}", "transform": {"translation": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}, "components": {}})
        self._settings[key] = entities
        self._refresh_hierarchy()
        self.changed.emit()

    def _remove_selected(self) -> None:
        item = self.hierarchy.currentItem()
        entity_id = str(item.data(0, Qt.UserRole) or "") if item else ""
        if not entity_id:
            return
        if self._settings.get("base_prefab_id"):
            added = list(self._settings.get("added_entities") or ())
            if any(str(entity.get("entity_id") or "") == entity_id for entity in added):
                self._settings["added_entities"] = [entity for entity in added if str(entity.get("entity_id") or "") != entity_id]
            else:
                removed = set(str(value) for value in self._settings.get("removed_entity_ids") or ())
                removed.add(entity_id)
                self._settings["removed_entity_ids"] = sorted(removed)
        else:
            self._settings["entities"] = [entity for entity in self._settings.get("entities") or () if str(entity.get("entity_id") or "") != entity_id]
        self._refresh_hierarchy()
        self.changed.emit()

    def _restore_selected(self) -> None:
        item = self.hierarchy.currentItem()
        entity_id = str(item.data(0, Qt.UserRole) or "") if item else ""
        removed = set(str(value) for value in self._settings.get("removed_entity_ids") or ())
        if entity_id in removed:
            removed.remove(entity_id)
            self._settings["removed_entity_ids"] = sorted(removed)
            self._refresh_hierarchy()
            self.changed.emit()

    def _add_override(self) -> None:
        row = self.overrides.rowCount()
        self.overrides.insertRow(row)
        selected = self.hierarchy.currentItem()
        entity_id = str(selected.data(0, Qt.UserRole) or "Entity_0") if selected else "Entity_0"
        self.overrides.setItem(row, 0, QTableWidgetItem(f"{entity_id}.transform.scale"))
        self.overrides.setItem(row, 1, QTableWidgetItem("[1,1,1]"))
        state = QTableWidgetItem("Overridden")
        state.setFlags(state.flags() & ~Qt.ItemIsEditable)
        self.overrides.setItem(row, 2, state)
        self.changed.emit()

    def _remove_override(self) -> None:
        row = self.overrides.currentRow()
        if row >= 0:
            self.overrides.removeRow(row)
            self.changed.emit()

    def _table_changed(self, _item: QTableWidgetItem) -> None:
        if not self._loading:
            self.changed.emit()

    @staticmethod
    def _render(value: Any) -> str:
        if isinstance(value, (dict, list, bool)) or value is None:
            import json
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    @staticmethod
    def _parse(value: str) -> Any:
        import json
        try:
            return json.loads(str(value))
        except json.JSONDecodeError:
            return str(value)


class ClothSetupEditorWidget(QWidget):
    """Guided cloth setup; detailed vertex painting remains in the shared 3D viewport."""

    changed = Signal()
    paint_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.quality = QComboBox(self)
        self.quality.addItems(["preview", "realtime", "hero", "cinematic", "custom"])
        self.bake_policy = QComboBox(self)
        self.bake_policy.addItems(["automatic", "runtime", "simulation_cache", "geometry_cache", "vertex_animation_texture"])
        self.preserve_skinning = QCheckBox("Preserve imported bone weights", self)
        self.preserve_skinning.setChecked(True)
        self.preserve_skinning.setEnabled(False)
        self.vertex_count = QSpinBox(self)
        self.vertex_count.setRange(0, 100_000_000)
        self.fixed_vertices = QLineEdit(self)
        self.fixed_vertices.setPlaceholderText("Optional fixed vertices, for example: 0, 1, 24-31")
        form.addRow("Quality", self.quality)
        form.addRow("Cook / Bake", self.bake_policy)
        form.addRow("Skinning", self.preserve_skinning)
        form.addRow("Vertex Count", self.vertex_count)
        form.addRow("Initial Fixed Region", self.fixed_vertices)
        root.addLayout(form)

        actions = QHBoxLayout()
        auto_setup = QPushButton("Auto Setup Maps", self)
        auto_setup.setToolTip("Create reversible starting maps without changing imported skin weights.")
        auto_setup.clicked.connect(self._auto_setup)
        actions.addWidget(auto_setup)
        self.paint_target = QComboBox(self)
        for label, key in (
            ("Skin ↔ Simulation", "skin_simulation"),
            ("Animation Drive", "animation_drive"),
            ("Max Distance", "max_distance"),
            ("Backstop Distance", "backstop_distance"),
            ("Backstop Radius", "backstop_radius"),
            ("Stretch Stiffness", "stretch_stiffness"),
            ("Bend Stiffness", "bend_stiffness"),
            ("Collision Thickness", "collision_thickness"),
            ("Drag", "drag"),
        ):
            self.paint_target.addItem(label, key)
        actions.addWidget(self.paint_target)
        paint = QPushButton("Paint in 3D View", self)
        paint.setToolTip("Open this cloth map on the garment in Garden's shared mesh-paint viewport.")
        paint.clicked.connect(lambda: self.paint_requested.emit(str(self.paint_target.currentData())))
        actions.addWidget(paint)
        actions.addStretch(1)
        root.addLayout(actions)

        self.maps = QTableWidget(0, 4, self)
        self.maps.setHorizontalHeaderLabels(["Map", "Samples", "Minimum", "Maximum"])
        self.maps.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.maps, 1)
        self.status = QLabel("Imported bone weights remain authoritative. Cloth maps are an independent deformation layer.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._settings: dict[str, Any] = {}
        self.quality.currentTextChanged.connect(self._controls_changed)
        self.bake_policy.currentTextChanged.connect(self._controls_changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self.quality.setCurrentText(str(self._settings.get("quality_profile") or "realtime"))
        self.bake_policy.setCurrentText(str(self._settings.get("bake_policy") or "automatic"))
        maps = dict(self._settings.get("property_maps") or {})
        self.vertex_count.setValue(max((len(value) for value in maps.values() if isinstance(value, list)), default=0))
        self._refresh_maps(maps)

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        result.update({
            "quality_profile": self.quality.currentText(),
            "bake_policy": self.bake_policy.currentText(),
            "preserve_imported_skinning": True,
        })
        return result

    def _controls_changed(self, _value: str = "") -> None:
        self._settings.update({
            "quality_profile": self.quality.currentText(),
            "bake_policy": self.bake_policy.currentText(),
            "preserve_imported_skinning": True,
        })
        self.changed.emit()

    def _auto_setup(self) -> None:
        count = self.vertex_count.value()
        if count <= 0:
            self.status.setText("Enter the imported garment vertex count before running Auto Setup.")
            return
        try:
            fixed = _parse_index_ranges(self.fixed_vertices.text(), count)
            receipt = automatic_cloth_maps(count, fixed_vertices=fixed)
        except (ValueError, IndexError) as exc:
            self.status.setText(str(exc))
            return
        self._settings["property_maps"] = receipt.property_maps
        self._settings["preserve_imported_skinning"] = True
        self._refresh_maps(receipt.property_maps)
        self.status.setText(
            f"Created cloth maps for {count:,} vertices; preserved imported skinning and fixed {len(fixed):,} vertices."
        )
        self.changed.emit()

    def _refresh_maps(self, maps: dict[str, Any]) -> None:
        self.maps.setRowCount(0)
        for name, raw_values in sorted(maps.items()):
            values = [float(value) for value in raw_values] if isinstance(raw_values, list) else []
            row = self.maps.rowCount()
            self.maps.insertRow(row)
            for column, value in enumerate((name, len(values), min(values, default=0.0), max(values, default=0.0))):
                self.maps.setItem(row, column, QTableWidgetItem(str(value)))


class FabricMaterialEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.preset = QComboBox(self)
        self.preset.addItems(list(FABRIC_PRESETS))
        form.addRow("Fabric Preset", self.preset)
        self.values = QTableWidget(0, 2, self)
        self.values.setHorizontalHeaderLabels(["Physical Property", "Value"])
        root.addLayout(form)
        root.addWidget(self.values, 1)
        self.preset.currentTextChanged.connect(self._apply_preset)
        self._settings: dict[str, Any] = {}

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self.preset.blockSignals(True)
        self.preset.setCurrentText(str(self._settings.get("preset") or "cotton"))
        self.preset.blockSignals(False)
        self._refresh()

    def settings(self) -> dict[str, Any]:
        return dict(self._settings)

    def _apply_preset(self, name: str) -> None:
        self._settings = {"preset": str(name), **FABRIC_PRESETS[str(name)]}
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        values = {key: value for key, value in self._settings.items() if key != "preset"}
        self.values.setRowCount(0)
        for key, value in values.items():
            row = self.values.rowCount()
            self.values.insertRow(row)
            self.values.setItem(row, 0, QTableWidgetItem(key.replace("_", " ").title()))
            self.values.setItem(row, 1, QTableWidgetItem(str(value)))


class PhysicsAssetEditorWidget(QWidget):
    """Direct body/constraint authoring surface for a character Physics Asset."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("Ragdoll Preset"))
        self.preset = QComboBox(self)
        self.preset.addItems(list(RAGDOLL_PRESETS))
        header.addWidget(self.preset)
        add_body = QPushButton("Add Body", self)
        add_body.clicked.connect(self._add_body)
        header.addWidget(add_body)
        add_constraint = QPushButton("Add Constraint", self)
        add_constraint.clicked.connect(self._add_constraint)
        header.addWidget(add_constraint)
        header.addStretch(1)
        root.addLayout(header)
        root.addWidget(QLabel("Bodies • bind one collider to each skeleton bone; double-click a value to edit it."))
        self.bodies = QTableWidget(0, 6, self)
        self.bodies.setHorizontalHeaderLabels(["Body ID", "Bone", "Shape", "Mass", "Linear Damping", "Angular Damping"])
        root.addWidget(self.bodies, 1)
        root.addWidget(QLabel("Constraints • tune limits and damping, then preview with the actual runtime solver."))
        self.constraints = QTableWidget(0, 7, self)
        self.constraints.setHorizontalHeaderLabels(["Constraint ID", "Type", "Body A", "Body B", "Min", "Max", "Damping"])
        root.addWidget(self.constraints, 1)
        self.status = QLabel("Auto generation is also available from Python using the Skeleton joint data.", self)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._settings: dict[str, Any] = {}
        self._refreshing = False
        self.preset.currentTextChanged.connect(self._edited)
        self.bodies.itemChanged.connect(self._edited)
        self.constraints.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self._refreshing = True
        self.preset.setCurrentText(str(self._settings.get("preset") or "balanced"))
        self.bodies.setRowCount(0)
        for body in self._settings.get("bodies") or ():
            rigid = dict(body.get("rigid_body") or {})
            collider = dict(body.get("collider") or {})
            self._append_row(self.bodies, (
                body.get("id", ""), body.get("bone", ""), collider.get("shape", "capsule"),
                rigid.get("mass", 1.0), rigid.get("linear_damping", 0.08), rigid.get("angular_damping", 0.18),
            ))
        self.constraints.setRowCount(0)
        for joint in self._settings.get("constraints") or ():
            self._append_row(self.constraints, (
                joint.get("id", ""), joint.get("type", "cone_twist"), joint.get("first", ""), joint.get("second", ""),
                joint.get("minimum_limit", -35.0), joint.get("maximum_limit", 35.0), joint.get("damping", 0.4),
            ))
        self._refreshing = False

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        result["preset"] = self.preset.currentText()
        bodies = []
        original_bodies = {str(value.get("id") or ""): dict(value) for value in self._settings.get("bodies") or ()}
        for row in range(self.bodies.rowCount()):
            cells = [self.bodies.item(row, column).text() for column in range(6)]
            body = original_bodies.get(cells[0], {})
            rigid_body = dict(body.get("rigid_body") or {})
            collider = dict(body.get("collider") or {})
            rigid_body.update({"dynamic": True, "mass": _float_or(cells[3], 1.0),
                               "linear_damping": _float_or(cells[4], 0.08), "angular_damping": _float_or(cells[5], 0.18)})
            collider["shape"] = cells[2]
            body.update({"id": cells[0], "bone": cells[1], "collider": collider, "rigid_body": rigid_body})
            bodies.append(body)
        constraints = []
        original_constraints = {str(value.get("id") or ""): dict(value) for value in self._settings.get("constraints") or ()}
        for row in range(self.constraints.rowCount()):
            cells = [self.constraints.item(row, column).text() for column in range(7)]
            joint = dict(PHYSICS_JOINT_PRESETS["ragdoll"])
            joint.update(original_constraints.get(cells[0], {}))
            joint.update({
                "id": cells[0], "type": cells[1], "first": cells[2], "second": cells[3],
                "minimum_limit": _float_or(cells[4], -35.0), "maximum_limit": _float_or(cells[5], 35.0),
                "damping": _float_or(cells[6], 0.4),
            })
            constraints.append(joint)
        result.update({"bodies": bodies, "constraints": constraints})
        return result

    def validation_issues(self) -> list[str]:
        return [issue.message for issue in validate_physics_asset_properties(self.settings()) if issue.severity == "error"]

    def _add_body(self) -> None:
        index = self.bodies.rowCount() + 1
        self._append_row(self.bodies, (f"Body {index}", f"bone_{index}", "capsule", 1.0, 0.08, 0.18))
        self.changed.emit()

    def _add_constraint(self) -> None:
        row = self.constraints.rowCount() + 1
        first = self.bodies.item(max(0, row - 2), 0).text() if self.bodies.rowCount() else "Body A"
        second = self.bodies.item(min(self.bodies.rowCount() - 1, row - 1), 0).text() if self.bodies.rowCount() else "Body B"
        self._append_row(self.constraints, (f"Constraint {row}", "cone_twist", first, second, -35.0, 35.0, 0.4))
        self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._refreshing:
            self.changed.emit()

    @staticmethod
    def _append_row(table: QTableWidget, values) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))


class PhysicsConstraintAssetEditorWidget(QWidget):
    """Reusable constraint editor using the same vocabulary as the runtime joint API."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.identifier = QLineEdit(self)
        self.first = QLineEdit(self)
        self.second = QLineEdit(self)
        self.preset = QComboBox(self); self.preset.addItems(sorted(PHYSICS_JOINT_PRESETS))
        self.kind = QComboBox(self); self.kind.addItems(PHYSICS_JOINT_TYPES)
        self.minimum = QDoubleSpinBox(self); self.minimum.setRange(-1.0e6, 1.0e6)
        self.maximum = QDoubleSpinBox(self); self.maximum.setRange(-1.0e6, 1.0e6)
        self.stiffness = QDoubleSpinBox(self); self.stiffness.setRange(0.0, 1.0); self.stiffness.setSingleStep(0.05)
        self.damping = QDoubleSpinBox(self); self.damping.setRange(0.0, 1.0e6); self.damping.setSingleStep(0.05)
        self.limits = QCheckBox("Enable limits", self)
        self.collision = QCheckBox("Connected bodies collide", self)
        for label, widget in (("Name", self.identifier), ("Body A", self.first), ("Body B", self.second),
                              ("Preset", self.preset), ("Type", self.kind), ("Minimum Limit", self.minimum),
                              ("Maximum Limit", self.maximum), ("Stiffness", self.stiffness), ("Damping", self.damping),
                              ("Limits", self.limits), ("Collision", self.collision)):
            form.addRow(label, widget)
        self._settings: dict[str, Any] = {}
        self._refreshing = False
        self.preset.currentTextChanged.connect(self._preset_changed)
        for widget in (self.identifier, self.first, self.second): widget.textChanged.connect(self._edited)
        self.kind.currentTextChanged.connect(self._edited)
        for widget in (self.minimum, self.maximum, self.stiffness, self.damping): widget.valueChanged.connect(self._edited)
        for widget in (self.limits, self.collision): widget.toggled.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        joint = dict(self._settings.get("joint") or {})
        self._refreshing = True
        self.identifier.setText(str(self._settings.get("constraint_id") or joint.get("id") or "Constraint"))
        self.first.setText(str(self._settings.get("first_body") or joint.get("first") or ""))
        self.second.setText(str(self._settings.get("second_body") or joint.get("second") or ""))
        self.preset.setCurrentText(str(self._settings.get("preset") or "weld"))
        self.kind.setCurrentText(str(joint.get("type") or "fixed"))
        self.minimum.setValue(float(joint.get("minimum_limit", 0.0)))
        self.maximum.setValue(float(joint.get("maximum_limit", 0.0)))
        self.stiffness.setValue(float(joint.get("stiffness", 1.0)))
        self.damping.setValue(float(joint.get("damping", 0.1)))
        self.limits.setChecked(bool(joint.get("limits_enabled", False)))
        self.collision.setChecked(bool(joint.get("collision_enabled", False)))
        self._refreshing = False

    def settings(self) -> dict[str, Any]:
        joint = constraint_from_preset(
            self.preset.currentText(), constraint_id=self.identifier.text() or "Constraint",
            first_body=self.first.text(), second_body=self.second.text(), settings={
                "type": self.kind.currentText(), "minimum_limit": self.minimum.value(),
                "maximum_limit": self.maximum.value(), "stiffness": self.stiffness.value(),
                "damping": self.damping.value(), "limits_enabled": self.limits.isChecked(),
                "collision_enabled": self.collision.isChecked(),
            },
        )
        return {"constraint_id": joint["id"], "first_body": joint["first"], "second_body": joint["second"],
                "preset": self.preset.currentText(), "joint": joint}

    def validation_issues(self) -> list[str]:
        try:
            values = self.settings()
        except (TypeError, ValueError) as exc:
            return [str(exc)]
        return [issue.message for issue in validate_constraint_properties(values) if issue.severity == "error"]

    def _preset_changed(self, name: str) -> None:
        if self._refreshing:
            return
        values = PHYSICS_JOINT_PRESETS[str(name)]
        self._refreshing = True
        self.kind.setCurrentText(str(values.get("type") or "fixed"))
        self.minimum.setValue(float(values.get("minimum_limit", 0.0)))
        self.maximum.setValue(float(values.get("maximum_limit", 0.0)))
        self.stiffness.setValue(float(values.get("stiffness", 1.0)))
        self.damping.setValue(float(values.get("damping", 0.1)))
        self.limits.setChecked(bool(values.get("limits_enabled", False)))
        self._refreshing = False
        self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._refreshing:
            self.changed.emit()


class GroomEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self)
        actions = QHBoxLayout(); self.lod_count = QSpinBox(self); self.lod_count.setRange(1, 8); self.lod_count.setValue(5)
        add = QPushButton("+ Hair Group", self); add.clicked.connect(self.add_group)
        remove = QPushButton("Delete Group", self); remove.clicked.connect(self.delete_group)
        generate = QPushButton("Generate LOD Chain", self); generate.clicked.connect(self.generate_lods)
        actions.addWidget(add); actions.addWidget(remove); actions.addSpacing(16); actions.addWidget(QLabel("LOD Count")); actions.addWidget(self.lod_count); actions.addWidget(generate); actions.addStretch(1); root.addLayout(actions)
        self.groups = QTableWidget(0, 8, self); self.groups.setHorizontalHeaderLabels(("Group", "Preset", "Curves", "Points", "Guides", "Width mm", "Simulate", "Solver")); self.groups.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(QLabel("Hair Groups & Guides")); root.addWidget(self.groups, 1)
        self.lods = QTableWidget(0, 8, self); self.lods.setHorizontalHeaderLabels(("LOD", "Screen Size", "Geometry", "Curve Ratio", "Point Ratio", "Thickness", "Binding", "Simulate"))
        root.addWidget(QLabel("LOD Representations — strands can transition to cards and mesh")); root.addWidget(self.lods, 1)
        self.summary = QLabel(self); self.summary.setWordWrap(True); root.addWidget(self.summary)
        self._settings: dict[str, Any] = {}; self._refreshing = False
        self.groups.itemChanged.connect(self._edited); self.lods.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {}); self._refreshing = True; self.groups.setRowCount(0); self.lods.setRowCount(0)
        for group in self._settings.get("groups") or (): self._append_group(dict(group or {}))
        for lod in self._settings.get("lods") or (): self._append_lod(dict(lod or {}))
        self.lod_count.setValue(max(1, self.lods.rowCount())); self._refreshing = False; self._update_summary()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings); groups = []
        for row in range(self.groups.rowCount()):
            groups.append({"name": _table_text(self.groups, row, 0), "preset": _table_text(self.groups, row, 1),
                           "curve_count": int(_float_or(_table_text(self.groups, row, 2), 0)), "point_count": int(_float_or(_table_text(self.groups, row, 3), 0)),
                           "guide_count": int(_float_or(_table_text(self.groups, row, 4), 0)), "width_mm": _float_or(_table_text(self.groups, row, 5), 0.07),
                           "simulation": {"enabled": _table_bool(self.groups, row, 6), "solver": _table_text(self.groups, row, 7)}})
        lods = []
        for row in range(self.lods.rowCount()):
            lods.append({"lod": int(_float_or(_table_text(self.lods, row, 0), row)), "screen_size": _float_or(_table_text(self.lods, row, 1), 1.0),
                         "geometry_type": _table_text(self.lods, row, 2), "curve_decimation": _float_or(_table_text(self.lods, row, 3), 1.0),
                         "vertex_decimation": _float_or(_table_text(self.lods, row, 4), 1.0), "thickness_scale": _float_or(_table_text(self.lods, row, 5), 1.0),
                         "binding_type": _table_text(self.lods, row, 6), "simulation": _table_bool(self.lods, row, 7), "visible": True,
                         "angular_threshold_degrees": 2.0 + row * 4.0})
        result.update({"groups": groups, "lods": lods}); return result

    def add_group(self) -> None:
        preset = GROOM_GROUP_PRESETS["scalp"]
        self._append_group({"name": f"Hair Group {self.groups.rowCount() + 1}", "preset": "scalp", "curve_count": 10000,
                            "point_count": 160000, "guide_count": 1000, "width_mm": preset["width_mm"],
                            "simulation": {"enabled": True, "solver": preset["solver"]}}); self._edited()

    def delete_group(self) -> None:
        rows = sorted({index.row() for index in self.groups.selectedIndexes()}, reverse=True)
        for row in rows: self.groups.removeRow(row)
        if rows: self._edited()

    def generate_lods(self) -> None:
        self._refreshing = True; self.lods.setRowCount(0)
        for lod in automatic_groom_lods(count=self.lod_count.value()): self._append_lod(lod)
        self._refreshing = False; self._edited()

    def _append_group(self, group: dict[str, Any]) -> None:
        simulation = dict(group.get("simulation") or {})
        _append_table_row(self.groups, (group.get("name", "Group"), group.get("preset", "scalp"), group.get("curve_count", 0), group.get("point_count", 0),
                                        group.get("guide_count", 0), group.get("width_mm", 0.07), simulation.get("enabled", False), simulation.get("solver", "angular_spring")))

    def _append_lod(self, lod: dict[str, Any]) -> None:
        _append_table_row(self.lods, (lod.get("lod", 0), lod.get("screen_size", 1.0), lod.get("geometry_type", "strands"), lod.get("curve_decimation", 1.0),
                                      lod.get("vertex_decimation", 1.0), lod.get("thickness_scale", 1.0), lod.get("binding_type", "skinning"), lod.get("simulation", False)))

    def _edited(self, *_args) -> None:
        if not self._refreshing: self._update_summary(); self.changed.emit()

    def _update_summary(self) -> None:
        issues = validate_groom_properties(self.settings()); curves = sum(int(_float_or(_table_text(self.groups, row, 2), 0)) for row in range(self.groups.rowCount()))
        self.summary.setText(f"{self.groups.rowCount()} groups • {curves:,} render curves • {self.lods.rowCount()} LODs • {sum(issue.severity == 'error' for issue in issues)} blocking issue(s)")


class GroomBindingEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout()
        self.groom = QLineEdit(self); self.target = QLineEdit(self); self.source = QLineEdit(self); self.mode = QComboBox(self); self.mode.addItems(["skinning", "rigid", "rbf"])
        self.maximum = QDoubleSpinBox(self); self.maximum.setRange(0.0, 1000.0); self.maximum.setDecimals(6); self.maximum.setValue(0.05)
        form.addRow("Groom", self.groom); form.addRow("Target Skeletal Mesh", self.target); form.addRow("Source Skeletal Mesh", self.source); form.addRow("Binding Mode", self.mode); form.addRow("Maximum Root Distance", self.maximum); root.addLayout(form)
        self.summary = QLabel(self); self.summary.setWordWrap(True); root.addWidget(self.summary); root.addStretch(1)
        self._settings: dict[str, Any] = {}; self._refreshing = False
        for widget in (self.groom, self.target, self.source): widget.textChanged.connect(self._edited)
        self.mode.currentTextChanged.connect(self._edited); self.maximum.valueChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {}); self._refreshing = True; self.groom.setText(str(self._settings.get("groom_id") or "")); self.target.setText(str(self._settings.get("target_skeletal_mesh_id") or "")); self.source.setText(str(self._settings.get("source_skeletal_mesh_id") or "")); self.mode.setCurrentText(str(self._settings.get("binding_mode") or "skinning")); self.maximum.setValue(float(self._settings.get("maximum_projection_distance", 0.05))); self._refreshing = False; self._update_summary()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings); result.update({"groom_id": self.groom.text().strip(), "target_skeletal_mesh_id": self.target.text().strip(), "source_skeletal_mesh_id": self.source.text().strip(), "binding_mode": self.mode.currentText(), "maximum_projection_distance": self.maximum.value()}); return result

    def _edited(self, *_args) -> None:
        if not self._refreshing: self._update_summary(); self.changed.emit()

    def _update_summary(self) -> None:
        issues = validate_groom_binding_properties(self.settings()); self.summary.setText(f"{len(self._settings.get('root_projections') or ()):,.0f} cached roots • {sum(issue.severity == 'error' for issue in issues)} blocking issue(s)")


class HairMaterialEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout(); self.preset = QComboBox(self); self.preset.addItems(sorted(HAIR_MATERIAL_PRESETS)); apply_button = QPushButton("Apply Physical Preset", self); apply_button.clicked.connect(self._apply)
        preset_row = QHBoxLayout(); preset_row.addWidget(self.preset); preset_row.addWidget(apply_button); form.addRow("Preset", preset_row); self.controls: dict[str, QDoubleSpinBox] = {}
        for key, label in (("melanin", "Melanin"), ("melanin_redness", "Melanin Redness"), ("roughness", "Longitudinal Roughness"), ("radial_roughness", "Radial Roughness"), ("scatter", "Multiple Scattering"), ("specular", "Specular"), ("random_hue", "Random Hue")):
            control = QDoubleSpinBox(self); control.setRange(0.0, 1.0); control.setSingleStep(0.01); control.setDecimals(3); control.valueChanged.connect(self._edited); self.controls[key] = control; form.addRow(label, control)
        root.addLayout(form); summary = QLabel("Physical fiber controls are shared by strands, generated cards, and mesh fallbacks.", self); summary.setWordWrap(True); root.addWidget(summary); root.addStretch(1); self._settings: dict[str, Any] = {}; self._refreshing = False

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {}); self._refreshing = True; self.preset.setCurrentText(str(self._settings.get("preset") or "brown_hair"))
        for key, control in self.controls.items(): control.setValue(float(self._settings.get(key, 0.0)))
        self._refreshing = False

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings); result["preset"] = self.preset.currentText(); result.update({key: control.value() for key, control in self.controls.items()}); return result

    def _apply(self) -> None:
        values = hair_material_preset(self.preset.currentText()); values.update({key: value for key, value in self._settings.items() if key not in values}); self.load_settings(values); self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._refreshing: self.changed.emit()


class IKRigEditorWidget(QWidget):
    changed = Signal()

    HEADERS = ("Chain", "Start Bone", "End Bone", "Solver", "Goal", "Pole", "Iterations", "Precision", "Stretch")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        form = QHBoxLayout()
        self.retarget_root = QLineEdit(self)
        self.retarget_root.setPlaceholderText("pelvis / hips")
        add = QPushButton("+ Chain", self); add.clicked.connect(self.add_chain)
        remove = QPushButton("Delete Chain", self); remove.clicked.connect(self.delete_selected)
        form.addWidget(QLabel("Retarget Root")); form.addWidget(self.retarget_root); form.addWidget(add); form.addWidget(remove); form.addStretch(1)
        root.addLayout(form)
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        self.summary = QLabel("Define named chains once; Control Rig and IK Retargeter reuse them.", self)
        root.addWidget(self.summary)
        self._settings: dict[str, Any] = {}
        self._refreshing = False
        self.retarget_root.textChanged.connect(self._edited)
        self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self._refreshing = True
        self.retarget_root.setText(str(self._settings.get("retarget_root") or ""))
        self.table.setRowCount(0)
        for chain in self._settings.get("chains") or ():
            settings = dict(chain.get("settings") or {})
            self._append((chain.get("name", ""), chain.get("start_bone", ""), chain.get("end_bone", ""),
                          chain.get("solver", "two_bone"), chain.get("goal", ""), chain.get("pole", ""),
                          settings.get("iterations", 12), settings.get("precision", 0.001), settings.get("stretch", 0.0)))
        self._refreshing = False
        self._update_summary()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        chains = []
        for row in range(self.table.rowCount()):
            cells = [_table_text(self.table, row, column) for column in range(len(self.HEADERS))]
            chains.append({"name": cells[0], "start_bone": cells[1], "end_bone": cells[2], "solver": cells[3],
                           "goal": cells[4], "pole": cells[5], "settings": {"iterations": int(_float_or(cells[6], 12)),
                           "precision": _float_or(cells[7], 0.001), "stretch": _float_or(cells[8], 0.0)}})
        result.update({"retarget_root": self.retarget_root.text().strip(), "chains": chains})
        return result

    def add_chain(self) -> None:
        index = self.table.rowCount() + 1
        self._append((f"Chain {index}", "start_bone", "end_bone", "two_bone", f"Goal_{index}", f"Pole_{index}", 12, 0.001, 0.0))
        self._edited()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self._edited()

    def _append(self, values) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate(values): self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _edited(self, *_args) -> None:
        if not self._refreshing:
            self._update_summary(); self.changed.emit()

    def _update_summary(self) -> None:
        solvers = sorted({_table_text(self.table, row, 3) for row in range(self.table.rowCount())})
        self.summary.setText(f"{self.table.rowCount()} chains • " + (", ".join(solvers) if solvers else "no solvers"))


class IKRetargeterEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QLineEdit(self); self.target = QLineEdit(self)
        self.root_scale = QDoubleSpinBox(self); self.root_scale.setRange(0.001, 1000.0); self.root_scale.setValue(1.0)
        form.addRow("Source IK Rig", self.source); form.addRow("Target IK Rig", self.target); form.addRow("Root Scale", self.root_scale)
        root.addLayout(form)
        buttons = QHBoxLayout()
        add = QPushButton("+ Chain Mapping", self); add.clicked.connect(self.add_mapping)
        remove = QPushButton("Delete Mapping", self); remove.clicked.connect(self.delete_selected)
        buttons.addWidget(add); buttons.addWidget(remove); buttons.addStretch(1); root.addLayout(buttons)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Source Chain", "Target Chain", "Translation", "Rotation", "Weight"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        self._settings: dict[str, Any] = {}; self._refreshing = False
        for widget in (self.source, self.target): widget.textChanged.connect(self._edited)
        self.root_scale.valueChanged.connect(self._edited); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {}); root = dict(self._settings.get("root_settings") or {})
        self._refreshing = True
        self.source.setText(str(self._settings.get("source_ik_rig_id") or "")); self.target.setText(str(self._settings.get("target_ik_rig_id") or ""))
        self.root_scale.setValue(float(root.get("scale", 1.0))); self.table.setRowCount(0)
        for item in self._settings.get("chain_mapping") or ():
            self._append((item.get("source", ""), item.get("target", ""), item.get("translation_mode", "scaled"),
                          item.get("rotation_mode", "interpolated"), item.get("weight", 1.0)))
        self._refreshing = False

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        mapping = []
        for row in range(self.table.rowCount()):
            mapping.append({"source": _table_text(self.table, row, 0), "target": _table_text(self.table, row, 1),
                            "translation_mode": _table_text(self.table, row, 2), "rotation_mode": _table_text(self.table, row, 3),
                            "weight": _table_float(self.table, row, 4)})
        root = dict(result.get("root_settings") or {}); root["scale"] = self.root_scale.value()
        result.update({"source_ik_rig_id": self.source.text().strip(), "target_ik_rig_id": self.target.text().strip(),
                       "chain_mapping": mapping, "root_settings": root})
        return result

    def add_mapping(self) -> None:
        self._append(("Source Chain", "Target Chain", "scaled", "interpolated", 1.0)); self._edited()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self._edited()

    def _append(self, values) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate(values): self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _edited(self, *_args) -> None:
        if not self._refreshing: self.changed.emit()


class GeometryOptimizationEditorWidget(QWidget):
    """Ordered processor UX with honest local-backend availability."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.preset = QComboBox(self); self.preset.addItems(sorted(GEOMETRY_OPTIMIZATION_PRESETS))
        apply_preset = QPushButton("Apply Preset", self); apply_preset.clicked.connect(self._apply_preset)
        add = QPushButton("+ Processor", self); add.clicked.connect(self.add_stage)
        remove = QPushButton("Delete Stage", self); remove.clicked.connect(self.delete_selected)
        toolbar.addWidget(QLabel("Preset")); toolbar.addWidget(self.preset); toolbar.addWidget(apply_preset)
        toolbar.addWidget(add); toolbar.addWidget(remove); toolbar.addStretch(1)
        root.addLayout(toolbar)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(("Stage", "Processor", "Target", "Components", "Backend", "Readiness"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self._settings: dict[str, Any] = {}; self._refreshing = False
        self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self._refreshing = True
        self.preset.setCurrentText(str(self._settings.get("preset") or "character_balanced"))
        self.table.setRowCount(0)
        for stage in self._settings.get("stages") or ():
            self._append_stage(dict(stage or {}))
        self._refreshing = False
        self._update_summary()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings); stages = []
        for row in range(self.table.rowCount()):
            processor = _table_text(self.table, row, 1).strip().casefold()
            target = _table_text(self.table, row, 2).strip()
            settings: dict[str, Any] = {}
            if processor in {"reduction", "quad_reduction"}: settings["triangle_ratio"] = _float_or(target, 1.0)
            elif processor in {"remeshing", "occlusion_mesh"}: settings["on_screen_size"] = int(_float_or(target, 256))
            elif processor == "impostor": settings["views"] = int(_float_or(target, 16))
            components = [value.strip() for value in _table_text(self.table, row, 3).split(",") if value.strip()]
            stages.append({"stage_id": _table_text(self.table, row, 0), "processor": processor,
                           "enabled": True, "components": components, "settings": settings})
        result.update({"preset": self.preset.currentText(), "stages": stages})
        return result

    def add_stage(self) -> None:
        self._append_stage({"stage_id": f"stage_{self.table.rowCount() + 1}", "processor": "reduction",
                            "enabled": True, "components": [], "settings": {"triangle_ratio": 0.5}})
        self._edited()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self._edited()

    def _apply_preset(self) -> None:
        keep = {key: value for key, value in self._settings.items() if key in {"source_asset_ids", "selection_sets", "execution", "reports"}}
        keep.update(geometry_optimization_preset(self.preset.currentText()))
        self.load_settings(keep)
        self.changed.emit()

    def _append_stage(self, stage: dict[str, Any]) -> None:
        processor = str(stage.get("processor") or "reduction")
        descriptor = GEOMETRY_PROCESSORS.get(processor, {})
        settings = dict(stage.get("settings") or {})
        target = settings.get("triangle_ratio", settings.get("on_screen_size", settings.get("views", "—")))
        values = (stage.get("stage_id", "stage"), processor, target, ", ".join(stage.get("components") or ()),
                  descriptor.get("backend", "unavailable"), descriptor.get("maturity", "experimental"))
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column in {4, 5}: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)

    def _edited(self, *_args) -> None:
        if not self._refreshing:
            self._update_summary(); self.changed.emit()

    def _update_summary(self) -> None:
        plan = plan_geometry_optimization(self.settings())
        unavailable = sum(stage["execution_backend"] == "recipe_only" for stage in plan["stages"])
        self.summary.setText(
            f"{len(plan['stages'])} processor stages • {unavailable} awaiting a local backend • "
            "Reduction preserves mesh data; remeshing/proxy stages create new geometry."
        )


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _render_json(value: Any) -> str:
    import json
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def _json_value(value: str) -> Any:
    import json
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return str(value)


def _dotted_value(values: dict[str, Any], path: str) -> Any:
    current: Any = values
    for part in str(path).split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_dotted_value(values: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        return
    current = values
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = deepcopy(value)


def _resolved_material_instance(materials: MaterialService, values: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Resolve persisted parents plus the instance's current unsaved overrides."""
    parent_id = str(values.get("parent_material_id") or values.get("parent") or "")
    if not parent_id:
        return {}, ()
    try:
        resolution = materials.resolve(parent_id)
    except (KeyError, ValueError):
        return {}, ()
    resolved = deepcopy(resolution.properties)
    for path, value in dict(values.get("overrides") or {}).items():
        _set_dotted_value(resolved, str(path), value)
    switches = dict(resolved.get("static_switches") or {})
    switches.update({str(key): bool(value) for key, value in dict(values.get("static_switch_overrides") or {}).items()})
    resolved["static_switches"] = switches
    return resolved, tuple(resolution.inheritance_chain)


def _material_parameter_group(name: str) -> str:
    key = str(name)
    if key.startswith("texture_bindings."):
        return "Textures"
    if key in {"base_color", "roughness", "metalness", "specular", "normal_strength"}:
        return "Surface"
    if key.startswith("emissive"):
        return "Emission"
    if key in {"opacity", "transmission", "ior"}:
        return "Transparency"
    if key.startswith("clear_coat"):
        return "Clear Coat"
    if key in {"subsurface_color", "sheen"}:
        return "Advanced Shading"
    return "Custom"


def _append_table_row(table: QTableWidget, values) -> None:
    row = table.rowCount(); table.insertRow(row)
    for column, value in enumerate(values): table.setItem(row, column, QTableWidgetItem(str(value)))


def _parse_index_ranges(text: str, vertex_count: int) -> list[int]:
    result: set[int] = set()
    for token in (value.strip() for value in str(text).split(",")):
        if not token:
            continue
        if "-" in token:
            first, last = (int(value.strip()) for value in token.split("-", 1))
            result.update(range(min(first, last), max(first, last) + 1))
        else:
            result.add(int(token))
    if any(value < 0 or value >= int(vertex_count) for value in result):
        raise IndexError("A fixed vertex is outside the imported garment vertex range.")
    return sorted(result)


class GraphView(QGraphicsView):
    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        current = self.transform().m11()
        if 0.25 <= current * factor <= 3.0:
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.scale(factor, factor)
        event.accept()


class AssetNodeGraphWidget(QWidget):
    changed = Signal()

    def __init__(
        self, graph_kind: str, parent=None, *, project_root: str | Path | None = None,
        database: AssetDatabase | None = None, asset_id: str = "",
    ) -> None:
        super().__init__(parent)
        self.graph_kind = str(graph_kind)
        self.project_root = Path(project_root).expanduser().resolve() if project_root is not None else None
        self.database = database
        self.asset_id = str(asset_id)
        self._nodes: list[dict[str, Any]] = []
        self._connections: list[dict[str, str]] = []
        self._clipboard: dict[str, Any] = {"nodes": [], "connections": []}
        self._graph_extras: dict[str, Any] = {}
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.node_search = QLineEdit(self)
        self.node_search.setPlaceholderText("Search nodes…")
        self.node_search.setClearButtonEnabled(True)
        self.node_palette = QComboBox(self)
        self.node_palette.setMinimumWidth(170)
        add = QPushButton("+ Add Node")
        connect = QPushButton("Connect Selected")
        remove = QPushButton("Delete")
        frame = QPushButton("Frame All")
        self.target_platform = QComboBox(self); self.target_platform.addItems(["desktop", "windows", "linux", "macos", "mobile", "android", "ios", "web"])
        self.target_platform.setVisible(self.graph_kind in {"material", "shader"})
        self.choose_function = QPushButton("Choose Function...", self)
        self.choose_function.setVisible(self.graph_kind in {"material", "shader"})
        self.choose_function.setEnabled(database is not None and project_root is not None)
        toolbar.addWidget(self.node_search)
        toolbar.addWidget(self.node_palette)
        toolbar.addWidget(add)
        toolbar.addWidget(connect)
        toolbar.addWidget(remove)
        toolbar.addWidget(frame)
        toolbar.addWidget(self.target_platform)
        toolbar.addWidget(self.choose_function)
        toolbar.addStretch(1)
        self.summary = QLabel("")
        toolbar.addWidget(self.summary)
        root.addLayout(toolbar)
        self.scene = QGraphicsScene(self)
        self.view = GraphView(self.scene, self)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setStyleSheet("background:#071018; border:1px solid #1b3040;")
        root.addWidget(self.view, 1)
        self.compile_feedback = QLabel("", self); self.compile_feedback.setWordWrap(True)
        self.compile_feedback.setVisible(self.graph_kind in {"material", "shader"}); root.addWidget(self.compile_feedback)
        parameter_header = QHBoxLayout()
        parameter_header.addWidget(QLabel("Selected Node Parameters"))
        add_parameter = QPushButton("+ Parameter", self); add_parameter.clicked.connect(self._add_parameter)
        remove_parameter = QPushButton("Remove Parameter", self); remove_parameter.clicked.connect(self._remove_parameter)
        parameter_header.addWidget(add_parameter); parameter_header.addWidget(remove_parameter); parameter_header.addStretch(1)
        root.addLayout(parameter_header)
        self.parameter_table = QTableWidget(0, 3, self)
        self.parameter_table.setHorizontalHeaderLabels(["Name", "Value", "Type"])
        self.parameter_table.setMaximumHeight(150)
        root.addWidget(self.parameter_table)
        self._parameter_loading = False
        self._refresh_palette()
        self.node_search.textChanged.connect(self._refresh_palette)
        self.node_search.returnPressed.connect(self.add_palette_node)
        add.clicked.connect(self.add_palette_node)
        connect.clicked.connect(self.connect_selected)
        remove.clicked.connect(self.delete_selected)
        frame.clicked.connect(self.frame_all)
        self.target_platform.currentTextChanged.connect(lambda _value: self._rebuild_scene())
        self.choose_function.clicked.connect(self._choose_function_asset)
        QShortcut(QKeySequence.Copy, self, activated=self.copy_selected)
        QShortcut(QKeySequence.Paste, self, activated=self.paste)
        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        self.scene.selectionChanged.connect(self._load_selected_parameters)
        self.parameter_table.itemChanged.connect(self._parameter_changed)

    def _refresh_palette(self) -> None:
        query = self.node_search.text().strip().casefold()
        current = self.node_palette.currentText()
        self.node_palette.clear()
        entries = GRAPH_NODE_LIBRARY.get(self.graph_kind, ())
        for entry in entries:
            title = str(entry["title"])
            if not query or query in title.casefold() or query in str(entry.get("opcode", "")).casefold():
                self.node_palette.addItem(title)
        match = self.node_palette.findText(current)
        if match >= 0:
            self.node_palette.setCurrentIndex(match)

    def add_palette_node(self) -> str:
        return self.add_node(self.node_palette.currentText())

    def load_graph(self, payload: dict[str, Any] | None) -> None:
        graph = dict(payload or {})
        if self.graph_kind == "procedural_geometry":
            rows = [dict(item) for item in graph.get("nodes") or [] if isinstance(item, dict)]
            self._nodes = [{
                "id": str(item.get("node_id") or item.get("id") or ""),
                "title": str(item.get("label") or item.get("title") or item.get("operation") or "Node"),
                "opcode": str(item.get("operation") or item.get("opcode") or ""),
                "inputs": ["geometry:data"] if item.get("inputs") else [],
                "outputs": ["geometry:data"],
                "x": float(item.get("x", 40.0)), "y": float(item.get("y", 40.0)),
                "parameters": deepcopy(dict(item.get("parameters") or {})),
                "enabled": bool(item.get("enabled", True)),
            } for item in rows]
            self._connections = [
                {"source": str(source), "target": str(item.get("node_id") or item.get("id") or "")}
                for item in rows for source in item.get("inputs") or []
            ]
            self._graph_extras = {key: deepcopy(value) for key, value in graph.items() if key not in {"nodes", "connections"}}
        else:
            self._nodes = [dict(item) for item in graph.get("nodes") or [] if isinstance(item, dict)]
            self._connections = [dict(item) for item in graph.get("connections") or [] if isinstance(item, dict)]
            self._graph_extras = {}
        self._rebuild_scene()

    def graph(self) -> dict[str, Any]:
        self._capture_positions()
        if self.graph_kind == "procedural_geometry":
            incoming: dict[str, list[str]] = {str(node.get("id") or ""): [] for node in self._nodes}
            for edge in self._connections:
                incoming.setdefault(str(edge.get("target") or ""), []).append(str(edge.get("source") or ""))
            result = deepcopy(self._graph_extras)
            result.setdefault("schema", "tc.procedural_graph.v1")
            result.setdefault("name", "Procedural Graph")
            result.setdefault("graph_id", "procedural_graph")
            result.setdefault("seed", 0)
            result["nodes"] = [{
                "node_id": str(node.get("id") or ""),
                "operation": str(node.get("opcode") or ""),
                "inputs": incoming.get(str(node.get("id") or ""), []),
                "parameters": deepcopy(dict(node.get("parameters") or {})),
                "enabled": bool(node.get("enabled", True)),
                "label": str(node.get("title") or ""),
                "x": float(node.get("x", 0.0)), "y": float(node.get("y", 0.0)),
            } for node in self._nodes]
            known = {str(node.get("id") or "") for node in self._nodes}
            if str(result.get("output_node") or "") not in known:
                result["output_node"] = str(self._nodes[-1].get("id") or "") if self._nodes else ""
            result.setdefault("metadata", {})
            return result
        return {
            "kind": self.graph_kind,
            "nodes": [dict(item) for item in self._nodes],
            "connections": [dict(item) for item in self._connections],
        }

    def validation_issues(self) -> list[str]:
        identifiers = [str(item.get("id") or "") for item in self._nodes]
        issues = []
        if len(set(identifiers)) != len(identifiers) or "" in identifiers:
            issues.append("Graph node IDs must be present and unique.")
        known = set(identifiers)
        for edge in self._connections:
            if edge.get("source") not in known or edge.get("target") not in known:
                issues.append("Graph contains a connection to a missing node.")
        if self.graph_kind in {"material", "shader", "simulation", "procedural_geometry"} and _graph_has_cycle(known, self._connections):
            issues.append(f"{self.graph_kind.title()} graphs cannot contain dependency cycles.")
        return issues

    def compile_diagnostics(self) -> list[dict[str, Any]]:
        if self.graph_kind not in {"material", "shader"}:
            return []
        issues, _stats = analyze_material_graph(self.graph(), platform=self.target_platform.currentText())
        return [issue.to_dict() for issue in issues]

    def add_node(self, title: str = "") -> str:
        node_id = f"node_{uuid.uuid4().hex[:10]}"
        index = len(self._nodes)
        node_title = str(title or f"{self.graph_kind.title()} Node {index + 1}")
        descriptor = next(
            (entry for entry in GRAPH_NODE_LIBRARY.get(self.graph_kind, ()) if entry["title"] == node_title),
            {"opcode": node_title.casefold().replace(" ", "_"), "inputs": [], "outputs": []},
        )
        self._nodes.append({
            "id": node_id, "title": node_title, "opcode": str(descriptor["opcode"]),
            "inputs": list(descriptor.get("inputs") or ()), "outputs": list(descriptor.get("outputs") or ()),
            "x": float(40 + (index % 4) * 180), "y": float(40 + (index // 4) * 110),
            "parameters": deepcopy(dict(descriptor.get("parameters") or {})),
        })
        self._rebuild_scene()
        self.changed.emit()
        return node_id

    def _selected_node(self) -> dict[str, Any] | None:
        selected = [item for item in self.scene.selectedItems() if isinstance(item, QGraphicsRectItem)]
        if len(selected) != 1:
            return None
        node_id = str(selected[0].data(0) or "")
        return next((node for node in self._nodes if str(node.get("id") or "") == node_id), None)

    def _load_selected_parameters(self) -> None:
        self._parameter_loading = True
        self.parameter_table.setRowCount(0)
        node = self._selected_node()
        for name, value in sorted(dict(node.get("parameters") or {}).items()) if node else ():
            row = self.parameter_table.rowCount(); self.parameter_table.insertRow(row)
            self.parameter_table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.parameter_table.setItem(row, 1, QTableWidgetItem(_render_json(value)))
            kind = QTableWidgetItem(type(value).__name__); kind.setFlags(kind.flags() & ~Qt.ItemIsEditable)
            self.parameter_table.setItem(row, 2, kind)
        self._parameter_loading = False

    def _add_parameter(self) -> None:
        node = self._selected_node()
        if node is None:
            return
        parameters = dict(node.get("parameters") or {})
        index = len(parameters) + 1
        name = f"parameter_{index}"
        while name in parameters:
            index += 1; name = f"parameter_{index}"
        parameters[name] = 0.0
        node["parameters"] = parameters
        self._load_selected_parameters(); self.changed.emit()

    def _remove_parameter(self) -> None:
        node = self._selected_node(); row = self.parameter_table.currentRow()
        if node is None or row < 0:
            return
        name = _table_text(self.parameter_table, row, 0)
        parameters = dict(node.get("parameters") or {}); parameters.pop(name, None); node["parameters"] = parameters
        self._load_selected_parameters(); self.changed.emit()

    def _parameter_changed(self, _item: QTableWidgetItem) -> None:
        if self._parameter_loading:
            return
        node = self._selected_node()
        if node is None:
            return
        parameters: dict[str, Any] = {}
        for row in range(self.parameter_table.rowCount()):
            name = _table_text(self.parameter_table, row, 0).strip()
            if name:
                parameters[name] = _json_value(_table_text(self.parameter_table, row, 1))
        node["parameters"] = parameters
        self._load_selected_parameters(); self._refresh_compile_feedback(); self.changed.emit()

    def _choose_function_asset(self) -> None:
        node = self._selected_node()
        if node is None or str(node.get("opcode") or "") != "material_function" or self.database is None or self.project_root is None:
            self.compile_feedback.setText("Select a Material Function or Shader Function node first.")
            return
        from tech_connector.ui.game_engine.asset_picker import AssetPickerDialog
        current = str(dict(node.get("parameters") or {}).get("function_asset_id") or "")
        picker = AssetPickerDialog(
            self.project_root, self.database, allowed_types=("tc.shader_graph",), current_asset_id=current,
            title="Choose Reusable Shader Function", parent=self,
        )
        if picker.exec() != QDialog.Accepted or not picker.selected_asset_id or picker.selected_asset_id == self.asset_id:
            return
        parameters = dict(node.get("parameters") or {}); parameters["function_asset_id"] = picker.selected_asset_id; node["parameters"] = parameters
        selected_id = str(node.get("id") or ""); self._rebuild_scene()
        for item in self.scene.items():
            if isinstance(item, QGraphicsRectItem) and str(item.data(0) or "") == selected_id:
                item.setSelected(True); break
        self.changed.emit()

    def copy_selected(self) -> bool:
        self._capture_positions()
        selected_ids = {
            str(item.data(0) or "")
            for item in self.scene.selectedItems() if isinstance(item, QGraphicsRectItem)
        }
        if not selected_ids:
            return False
        self._clipboard = {
            "nodes": [dict(node) for node in self._nodes if str(node.get("id") or "") in selected_ids],
            "connections": [
                dict(edge) for edge in self._connections
                if edge.get("source") in selected_ids and edge.get("target") in selected_ids
            ],
        }
        return True

    def paste(self) -> list[str]:
        source_nodes = list(self._clipboard.get("nodes") or ())
        if not source_nodes:
            return []
        replacements: dict[str, str] = {}
        pasted: list[dict[str, Any]] = []
        for source in source_nodes:
            node = dict(source)
            old_id = str(node.get("id") or "")
            new_id = f"node_{uuid.uuid4().hex[:10]}"
            replacements[old_id] = new_id
            node["id"] = new_id
            node["x"] = float(node.get("x", 0.0)) + 32.0
            node["y"] = float(node.get("y", 0.0)) + 32.0
            pasted.append(node)
        self._nodes.extend(pasted)
        for source in self._clipboard.get("connections") or ():
            edge = dict(source)
            edge["source"] = replacements.get(str(edge.get("source") or ""), "")
            edge["target"] = replacements.get(str(edge.get("target") or ""), "")
            if edge["source"] and edge["target"]:
                self._connections.append(edge)
        self._rebuild_scene()
        pasted_ids = list(replacements.values())
        for item in self.scene.items():
            if isinstance(item, QGraphicsRectItem) and str(item.data(0) or "") in pasted_ids:
                item.setSelected(True)
        self.changed.emit()
        return pasted_ids

    def frame_all(self) -> None:
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            self.view.fitInView(bounds.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)

    def connect(
        self, source_id: str, target_id: str, *, source_pin: str = "", target_pin: str = "",
    ) -> bool:
        source = str(source_id)
        target = str(target_id)
        if not source or not target or source == target:
            return False
        known = {str(item.get("id") or "") for item in self._nodes}
        edge = {"source": source, "target": target}
        if source_pin: edge["source_pin"] = str(source_pin)
        if target_pin: edge["target_pin"] = str(target_pin)
        if source not in known or target not in known or edge in self._connections:
            return False
        self._connections.append(edge)
        self._rebuild_scene()
        self.changed.emit()
        return True

    def connect_selected(self) -> None:
        selected = [item for item in self.scene.selectedItems() if isinstance(item, QGraphicsRectItem)]
        if len(selected) == 2:
            source_id, target_id = str(selected[0].data(0) or ""), str(selected[1].data(0) or "")
            by_id = {str(node.get("id") or ""): node for node in self._nodes}
            source_node, target_node = by_id.get(source_id, {}), by_id.get(target_id, {})
            source_pin = str(next(iter(source_node.get("outputs") or ()), "")).split(":", 1)[0]
            target_pin = str(next(iter(target_node.get("inputs") or ()), "")).split(":", 1)[0]
            self.connect(source_id, target_id, source_pin=source_pin, target_pin=target_pin)

    def delete_selected(self) -> None:
        selected_ids = {
            str(item.data(0) or "")
            for item in self.scene.selectedItems() if isinstance(item, QGraphicsRectItem)
        }
        if not selected_ids:
            return
        self._nodes = [item for item in self._nodes if str(item.get("id") or "") not in selected_ids]
        self._connections = [
            item for item in self._connections
            if item.get("source") not in selected_ids and item.get("target") not in selected_ids
        ]
        self._rebuild_scene()
        self.changed.emit()

    def _capture_positions(self) -> None:
        positions = {
            str(item.data(0) or ""): item.pos()
            for item in self.scene.items() if isinstance(item, QGraphicsRectItem)
        }
        for node in self._nodes:
            position = positions.get(str(node.get("id") or ""))
            if position is not None:
                node["x"], node["y"] = float(position.x()), float(position.y())

    def _rebuild_scene(self) -> None:
        self.scene.clear()
        items: dict[str, QGraphicsRectItem] = {}
        node_issues: dict[str, list[Any]] = {}
        material_stats: dict[str, Any] = {}
        material_issues: list[Any] = []
        if self.graph_kind in {"material", "shader"}:
            material_issues, material_stats = analyze_material_graph(
                {"nodes": self._nodes, "connections": self._connections}, platform=self.target_platform.currentText(),
            )
            for issue in material_issues:
                if issue.subject:
                    node_issues.setdefault(issue.subject, []).append(issue)
        for node in self._nodes:
            ports = max(len(node.get("inputs") or ()), len(node.get("outputs") or ()))
            height = max(64, 42 + ports * 16)
            item = QGraphicsRectItem(QRectF(0, 0, 170, height))
            issues = node_issues.get(str(node.get("id") or ""), [])
            severity = "error" if any(issue.severity == "error" for issue in issues) else ("warning" if issues else "")
            item.setBrush(QColor("#3a1d25" if severity == "error" else ("#3a3017" if severity == "warning" else "#13283a")))
            item.setPen(QPen(QColor("#ff6178" if severity == "error" else ("#f5bd50" if severity == "warning" else "#4ba3d8")), 2.2 if severity else 1.4))
            item.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
            item.setData(0, str(node.get("id") or ""))
            item.setPos(float(node.get("x", 0.0)), float(node.get("y", 0.0)))
            label = QGraphicsSimpleTextItem(str(node.get("title") or "Node"), item)
            label.setBrush(QColor("#e7f6ff"))
            label.setPos(10, 8)
            if issues:
                badge = QGraphicsSimpleTextItem("! " + str(issues[0].message), item); badge.setBrush(QColor("#ffb5bf" if severity == "error" else "#ffd67a")); badge.setPos(10, height - 18)
            inputs = QGraphicsSimpleTextItem("\n".join(str(value).split(":", 1)[0] for value in node.get("inputs") or ()), item)
            inputs.setBrush(QColor("#8eb6ce"))
            inputs.setPos(10, 28)
            outputs = QGraphicsSimpleTextItem("\n".join(str(value).split(":", 1)[0] for value in node.get("outputs") or ()), item)
            outputs.setBrush(QColor("#78d6ad"))
            outputs.setPos(105, 28)
            self.scene.addItem(item)
            items[str(node.get("id") or "")] = item
        for edge in self._connections:
            source = items.get(str(edge.get("source") or ""))
            target = items.get(str(edge.get("target") or ""))
            if source is None or target is None:
                continue
            a = source.sceneBoundingRect().center()
            b = target.sceneBoundingRect().center()
            path = QPainterPath(a)
            midpoint = (a.x() + b.x()) * 0.5
            path.cubicTo(midpoint, a.y(), midpoint, b.y(), b.x(), b.y())
            self.scene.addPath(path, QPen(QColor("#6ee7b7"), 2.0))
        if self.graph_kind in {"material", "shader"}:
            self.summary.setText(f"{len(self._nodes)} nodes - {material_stats['estimated_alu']} ALU - {material_stats['texture_samples']} samples - {len(material_issues)} diagnostics")
            self.compile_feedback.setText("\n".join(
                f"{issue.severity.upper()} [{issue.subject or 'Graph'}] {issue.message}" for issue in material_issues
            ) or f"READY [{self.target_platform.currentText()}] No compile diagnostics.")
        else:
            self.summary.setText(f"{len(self._nodes)} nodes • {len(self._connections)} links")
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self._load_selected_parameters()

    def _refresh_compile_feedback(self) -> None:
        if self.graph_kind not in {"material", "shader"}:
            return
        issues, stats = analyze_material_graph(self.graph(), platform=self.target_platform.currentText())
        self.summary.setText(f"{len(self._nodes)} nodes - {stats['estimated_alu']} ALU - {stats['texture_samples']} samples - {len(issues)} diagnostics")
        self.compile_feedback.setText("\n".join(
            f"{issue.severity.upper()} [{issue.subject or 'Graph'}] {issue.message}" for issue in issues
        ) or f"READY [{self.target_platform.currentText()}] No compile diagnostics.")


class ProceduralGeometryPreviewCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.meshes: dict[str, dict[str, Any]] = {}; self.angle = 35.0
        self.setMinimumHeight(320)

    def set_geometry(self, meshes: dict[str, dict[str, Any]], angle: float | None = None) -> None:
        self.meshes = deepcopy(meshes)
        if angle is not None: self.angle = float(angle)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing, True); painter.fillRect(self.rect(), QColor("#071018"))
        all_points = [tuple(float(v) for v in point[:3]) for mesh in self.meshes.values() for point in mesh.get("vertices") or ()]
        if not all_points:
            painter.setPen(QColor("#8aa4b5")); painter.drawText(self.rect(), Qt.AlignCenter, "Cook the graph to preview generated geometry")
            return
        radians = math.radians(self.angle); cosine, sine = math.cos(radians), math.sin(radians)
        transformed = [(point[0] * cosine - point[2] * sine, point[1]) for point in all_points]
        minimum = [min(point[axis] for point in transformed) for axis in (0, 1)]; maximum = [max(point[axis] for point in transformed) for axis in (0, 1)]
        extent = max(maximum[0] - minimum[0], maximum[1] - minimum[1], 1.0e-6); scale = min(self.width(), self.height()) * 0.78 / extent
        def project(point):
            x = point[0] * cosine - point[2] * sine; y = point[1]
            return QPointF(self.width() * .5 + (x - (minimum[0] + maximum[0]) * .5) * scale,
                           self.height() * .5 - (y - (minimum[1] + maximum[1]) * .5) * scale)
        painter.setPen(QPen(QColor("#63d7c5"), 1.1))
        for mesh in self.meshes.values():
            vertices = [tuple(float(v) for v in point[:3]) for point in mesh.get("vertices") or ()]
            for face in mesh.get("faces") or ():
                polygon = [project(vertices[int(index)]) for index in face]
                for index, point in enumerate(polygon): painter.drawLine(point, polygon[(index + 1) % len(polygon)])


class ProceduralGeometryPreviewWidget(QWidget):
    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent); self.service = ProceduralGraphAssetService(project_root, database); self.asset_id = asset_id
        root = QVBoxLayout(self); toolbar = QHBoxLayout(); refresh = QPushButton("Cook Preview", self)
        self.angle = QSlider(Qt.Horizontal, self); self.angle.setRange(-180, 180); self.angle.setValue(35); self.summary = QLabel("", self)
        toolbar.addWidget(refresh); toolbar.addWidget(QLabel("Orbit")); toolbar.addWidget(self.angle, 1); toolbar.addWidget(self.summary)
        root.addLayout(toolbar); self.canvas = ProceduralGeometryPreviewCanvas(self); root.addWidget(self.canvas, 1)
        refresh.clicked.connect(self.refresh); self.angle.valueChanged.connect(lambda value: self.canvas.set_geometry(self.canvas.meshes, value)); self.refresh()

    def refresh(self) -> None:
        try:
            result = self.service.cooker.cook(self.service.graph(self.asset_id)); self.canvas.set_geometry(result.payload.meshes, self.angle.value())
            vertices = sum(len(mesh.get("vertices") or ()) for mesh in result.payload.meshes.values()); faces = sum(len(mesh.get("faces") or ()) for mesh in result.payload.meshes.values())
            self.summary.setText(f"{len(result.payload.meshes)} meshes • {vertices:,} vertices • {faces:,} faces • {len(result.payload.instances):,} instances")
        except Exception as exc:
            self.summary.setText(f"Preview failed: {exc}"); self.canvas.set_geometry({})


class ProceduralDiagnosticsWidget(QWidget):
    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent); self.service = ProceduralGraphAssetService(project_root, database); self.asset_id = asset_id
        root = QVBoxLayout(self); toolbar = QHBoxLayout(); refresh = QPushButton("Profile Graph", self); self.summary = QLabel("", self)
        toolbar.addWidget(refresh); toolbar.addWidget(self.summary, 1); root.addLayout(toolbar)
        self.table = QTableWidget(0, 7, self); self.table.setHorizontalHeaderLabels(("Node", "Operation", "Backend", "Time ms", "Cache", "Points", "Instances")); root.addWidget(self.table, 1)
        refresh.clicked.connect(self.refresh); self.refresh()

    def refresh(self) -> None:
        try:
            diagnostics = self.service.diagnostics(self.asset_id); plan = build_procedural_execution_plan(self.service.graph(self.asset_id))
            backends = {node_id: stage.backend for stage in plan.stages for node_id in stage.node_ids}; self.table.setRowCount(0)
            for row_data in diagnostics["nodes"]:
                row = self.table.rowCount(); self.table.insertRow(row)
                values = (row_data["node_id"], row_data["operation"], backends.get(row_data["node_id"], "cpu"), f"{float(row_data['elapsed_ms']):.3f}", "hit" if row_data["cache_hit"] else "miss", row_data["point_count"], row_data["instance_count"])
                for column, value in enumerate(values): self.table.setItem(row, column, QTableWidgetItem(str(value)))
            self.summary.setText(f"{diagnostics['total_ms']:.2f} ms • {diagnostics['cache_hits']}/{len(diagnostics['nodes'])} cached • {plan.transfer_count} CPU/GPU transfers")
        except Exception as exc:
            self.summary.setText(f"Profiling failed: {exc}")


class MaterialPreviewCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base_color = QColor("#ffffff")
        self.roughness = 0.5
        self.metalness = 0.0
        self.exposure = 0.0
        self.preview_mesh = "Sphere"
        self.environment = "Studio"
        self.setMinimumHeight(260)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#071018"))
        painter.setPen(QPen(QColor("#1b3040"), 1))
        for division in range(1, 10):
            x = self.width() * division / 10.0
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        size = max(40.0, min(self.width(), self.height()) * 0.68)
        bounds = QRectF((self.width() - size) / 2.0, (self.height() - size) / 2.0, size, size)
        exposure = math.pow(2.0, self.exposure)
        diffuse_scale = min(1.8, exposure * (0.72 + self.metalness * 0.2))
        surface = QColor(
            min(255, int(self.base_color.red() * diffuse_scale)),
            min(255, int(self.base_color.green() * diffuse_scale)),
            min(255, int(self.base_color.blue() * diffuse_scale)),
        )
        highlight = QColor.fromRgbF(
            min(1.0, surface.redF() + (1.0 - self.roughness) * 0.55),
            min(1.0, surface.greenF() + (1.0 - self.roughness) * 0.55),
            min(1.0, surface.blueF() + (1.0 - self.roughness) * 0.55),
        )
        gradient = QRadialGradient(
            QPointF(bounds.left() + size * 0.34, bounds.top() + size * 0.28),
            size * (0.42 + self.roughness * 0.45),
        )
        gradient.setColorAt(0.0, highlight)
        gradient.setColorAt(max(0.08, 0.3 - self.roughness * 0.18), surface)
        gradient.setColorAt(1.0, surface.darker(int(170 + self.roughness * 80)))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor("#5b7180"), 1.2))
        if self.preview_mesh == "Cube":
            painter.drawRoundedRect(bounds, 8, 8)
        elif self.preview_mesh == "Plane":
            plane = bounds.adjusted(0, size * 0.2, 0, -size * 0.2)
            painter.drawRoundedRect(plane, 4, 4)
        else:
            painter.drawEllipse(bounds)
        painter.setPen(QColor("#89a0b1"))
        painter.drawText(12, 22, f"{self.environment} • EV {self.exposure:+.1f} • {self.preview_mesh}")


class MaterialInstanceEditorWidget(QWidget):
    """Inheritance-first Material Instance inspector with explicit override state."""

    changed = Signal()

    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent)
        self.materials = MaterialService(project_root, database)
        self.asset_id = str(asset_id)
        self._settings: dict[str, Any] = {}
        self._loading = False
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.parent_id = QLineEdit(self)
        self.parent_id.setPlaceholderText("Parent Material asset ID")
        choose_parent = QPushButton("Choose…", self); choose_parent.setAccessibleName("Choose parent Material"); choose_parent.clicked.connect(self._choose_parent)
        self.inheritance = QLabel("No parent resolved", self)
        self.inheritance.setStyleSheet("color:#91aaba;")
        header.addWidget(QLabel("Parent")); header.addWidget(self.parent_id, 1); header.addWidget(choose_parent); header.addWidget(self.inheritance)
        root.addLayout(header)
        self.parameters = QTableWidget(0, 5, self)
        self.parameters.setHorizontalHeaderLabels(["Parameter", "Group", "Inherited", "Override", "State"])
        self.parameters.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.parameters, 2)
        actions = QHBoxLayout()
        add = QPushButton("Add Override", self); add.clicked.connect(self._add_override)
        revert = QPushButton("Revert Selected", self); revert.clicked.connect(self._revert_selected)
        clear = QPushButton("Revert All", self); clear.clicked.connect(self._revert_all)
        actions.addWidget(add); actions.addWidget(revert); actions.addWidget(clear); actions.addStretch(1)
        root.addLayout(actions)
        self.switches = QTableWidget(0, 4, self)
        self.switches.setHorizontalHeaderLabels(["Static Switch", "Inherited", "Override", "State"])
        root.addWidget(self.switches, 1)
        switch_actions = QHBoxLayout(); override_switch = QPushButton("Override Switch", self); revert_switch = QPushButton("Revert Switch", self); override_switch.clicked.connect(self._override_switch); revert_switch.clicked.connect(self._revert_switch); switch_actions.addWidget(override_switch); switch_actions.addWidget(revert_switch); switch_actions.addStretch(1); root.addLayout(switch_actions)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.parent_id.editingFinished.connect(self._parent_changed)
        self.parameters.itemChanged.connect(self._edited)
        self.switches.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True
        self._settings = dict(values or {})
        parent_id = str(self._settings.get("parent_material_id") or self._settings.get("parent") or "")
        self.parent_id.setText(parent_id)
        inherited: dict[str, Any] = {}
        groups: dict[str, Any] = {}
        chain: tuple[str, ...] = ()
        if parent_id:
            try:
                resolution = self.materials.resolve(parent_id)
                inherited = resolution.properties
                groups = dict(inherited.get("parameter_groups") or {})
                chain = resolution.inheritance_chain
            except (KeyError, ValueError):
                pass
        overrides = dict(self._settings.get("overrides") or {})
        standard = (
            "base_color", "roughness", "metalness", "specular", "normal_strength",
            "emissive_color", "emissive_intensity", "opacity", "clear_coat",
            "clear_coat_roughness", "subsurface_color", "transmission", "ior", "sheen",
        )
        names = list(dict.fromkeys([*standard, *dict(inherited.get("parameters") or {}), *overrides]))
        self.parameters.setRowCount(0)
        for name in names:
            inherited_value = _dotted_value(inherited, name)
            override = overrides.get(name)
            group = str(dict(groups.get(name) or {}).get("group") or _material_parameter_group(name))
            self._append_parameter(name, group, inherited_value, override, name in overrides)
        switches = dict(inherited.get("static_switches") or {})
        switch_overrides = dict(self._settings.get("static_switch_overrides") or {})
        self.switches.setRowCount(0)
        for name in sorted(set(switches) | set(switch_overrides)):
            row = self.switches.rowCount(); self.switches.insertRow(row)
            inherited_switch = bool(switches.get(name, False)); is_override = name in switch_overrides
            for column, value in enumerate((name, str(inherited_switch).lower(), str(bool(switch_overrides[name])).lower() if is_override else "", "Overridden" if is_override else "Inherited")):
                item = QTableWidgetItem(value)
                if column in {0, 1, 3}: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.switches.setItem(row, column, item)
        self.inheritance.setText(f"{len(chain)} level(s) • root {chain[0]}" if chain else "Parent unresolved")
        self._loading = False
        self._update_summary()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        result["material_version"] = 2
        result["parent_material_id"] = self.parent_id.text().strip()
        result.pop("parent", None)
        overrides: dict[str, Any] = {}
        for row in range(self.parameters.rowCount()):
            state = _table_text(self.parameters, row, 4)
            name = _table_text(self.parameters, row, 0)
            raw = _table_text(self.parameters, row, 3)
            if state == "Overridden" and name:
                overrides[name] = _json_value(raw)
        result["overrides"] = overrides
        switches: dict[str, bool] = {}
        for row in range(self.switches.rowCount()):
            if _table_text(self.switches, row, 3) == "Overridden":
                switches[_table_text(self.switches, row, 0)] = _table_text(self.switches, row, 2).casefold() in {"true", "1", "yes", "on"}
        result["static_switch_overrides"] = switches
        return result

    def resolved_properties(self) -> dict[str, Any]:
        return _resolved_material_instance(self.materials, self.settings())[0]

    def validation_issues(self) -> list[str]:
        parent_id = self.parent_id.text().strip()
        if not parent_id:
            return ["Material Instance requires a parent Material or Material Instance."]
        record = self.materials.database.asset(parent_id)
        if record is None or record.asset_type not in {"tc.material", "tc.material_instance"}:
            return ["Parent must reference an existing Material or Material Instance."]
        return []

    def _append_parameter(self, name: str, group: str, inherited: Any, override: Any, is_override: bool) -> None:
        row = self.parameters.rowCount(); self.parameters.insertRow(row)
        values = (name, group, _render_json(inherited), _render_json(override) if is_override else "", "Overridden" if is_override else "Inherited")
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column in {0, 1, 2, 4}: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.parameters.setItem(row, column, item)

    def _add_override(self) -> None:
        row = self.parameters.currentRow()
        if row < 0:
            self._append_parameter("CustomParameter", "Custom", "0.0", 0.0, True)
        else:
            inherited = _table_text(self.parameters, row, 2)
            self.parameters.item(row, 3).setText(inherited)
            self.parameters.item(row, 4).setText("Overridden")
        self._edited()

    def _revert_selected(self) -> None:
        row = self.parameters.currentRow()
        if row >= 0:
            self.parameters.item(row, 3).setText("")
            self.parameters.item(row, 4).setText("Inherited")
            self._edited()

    def _revert_all(self) -> None:
        for row in range(self.parameters.rowCount()):
            self.parameters.item(row, 3).setText("")
            self.parameters.item(row, 4).setText("Inherited")
        self._edited()

    def _parent_changed(self) -> None:
        values = self.settings()
        self.load_settings(values)
        self.changed.emit()

    def _choose_parent(self) -> None:
        from tech_connector.ui.game_engine.asset_picker import AssetPickerDialog
        picker = AssetPickerDialog(self.materials.project_root, self.materials.database, allowed_types=("tc.material", "tc.material_instance"), current_asset_id=self.parent_id.text().strip(), title="Choose Parent Material", parent=self)
        workspace = self.window()
        if hasattr(workspace, "locate_asset"): picker.locateRequested.connect(workspace.locate_asset)
        if hasattr(workspace, "open_asset_id"): picker.inspectRequested.connect(workspace.open_asset_id)
        if picker.exec() == QDialog.Accepted and picker.selected_asset_id != self.asset_id:
            self.parent_id.setText(picker.selected_asset_id); self._parent_changed()

    def _override_switch(self) -> None:
        row = self.switches.currentRow()
        if row < 0: return
        self.switches.item(row, 2).setText(self.switches.item(row, 1).text()); self.switches.item(row, 3).setText("Overridden"); self._edited()

    def _revert_switch(self) -> None:
        row = self.switches.currentRow()
        if row < 0: return
        self.switches.item(row, 2).setText(""); self.switches.item(row, 3).setText("Inherited"); self._edited()

    def _edited(self, item=None) -> None:
        if self._loading:
            return
        if isinstance(item, QTableWidgetItem) and item.tableWidget() is self.switches and item.column() == 2:
            self._loading = True
            state = self.switches.item(item.row(), 3)
            if state is not None:
                state.setText("Overridden" if item.text().strip() else "Inherited")
            self._loading = False
        self._update_summary(); self.changed.emit()

    def _update_summary(self) -> None:
        overrides = sum(_table_text(self.parameters, row, 4) == "Overridden" for row in range(self.parameters.rowCount()))
        static = sum(_table_text(self.switches, row, 3) == "Overridden" for row in range(self.switches.rowCount()))
        self.summary.setText(f"{overrides} parameter override(s) • {static} static override(s) • up to {2 ** static} compiled permutation(s)")


class MaterialInstancePreviewEditorWidget(QWidget):
    """Live resolved preview for a Material Instance without exposing parent-owned values."""

    changed = Signal()

    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent)
        self.materials = MaterialService(project_root, database)
        self.asset_id = str(asset_id)
        self._authoring: dict[str, Any] = {}
        self._loading = False
        root = QVBoxLayout(self)
        self.canvas = MaterialPreviewCanvas(self); root.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.preview_mesh = QComboBox(self); self.preview_mesh.addItems(["Sphere", "Cube", "Plane"])
        self.environment = QComboBox(self); self.environment.addItems(["Studio", "Outdoor", "Night", "Neutral"])
        self.exposure = QDoubleSpinBox(self); self.exposure.setRange(-5.0, 5.0); self.exposure.setSingleStep(0.25)
        controls.addWidget(QLabel("Preview Mesh")); controls.addWidget(self.preview_mesh)
        controls.addWidget(QLabel("Environment")); controls.addWidget(self.environment)
        controls.addWidget(QLabel("Exposure")); controls.addWidget(self.exposure); controls.addStretch(1)
        root.addLayout(controls)
        self.summary = QLabel("", self); self.summary.setWordWrap(True); root.addWidget(self.summary)
        self.preview_mesh.currentTextChanged.connect(self._preview_changed)
        self.environment.currentTextChanged.connect(self._preview_changed)
        self.exposure.valueChanged.connect(self._preview_changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True
        self._authoring = dict(values or {})
        resolved, chain = _resolved_material_instance(self.materials, self._authoring)
        mesh = str(self._authoring.get("preview_mesh") or resolved.get("preview_mesh") or "Sphere")
        environment = str(self._authoring.get("preview_environment") or resolved.get("preview_environment") or "Studio")
        exposure = float(self._authoring.get("preview_exposure", resolved.get("preview_exposure", 0.0)))
        self.preview_mesh.setCurrentText(mesh); self.environment.setCurrentText(environment); self.exposure.setValue(exposure)
        self.canvas.base_color = QColor(str(resolved.get("base_color") or "#ffffff"))
        self.canvas.roughness = float(resolved.get("roughness", 0.5)); self.canvas.metalness = float(resolved.get("metalness", 0.0))
        self.canvas.preview_mesh = mesh; self.canvas.environment = environment; self.canvas.exposure = exposure; self.canvas.update()
        override_count = len(dict(self._authoring.get("overrides") or {}))
        self.summary.setText(f"Resolved through {len(chain)} parent level(s) - {override_count} parameter override(s) - preview updates before save")
        self._loading = False

    load_instance_settings = load_settings

    def settings(self) -> dict[str, Any]:
        return {"preview_mesh": self.preview_mesh.currentText(), "preview_environment": self.environment.currentText(), "preview_exposure": float(self.exposure.value())}

    def _preview_changed(self, *_args) -> None:
        if self._loading:
            return
        self.canvas.preview_mesh = self.preview_mesh.currentText(); self.canvas.environment = self.environment.currentText(); self.canvas.exposure = float(self.exposure.value())
        self.canvas.update(); self.changed.emit()


class MaterialInstanceCostEditorWidget(QWidget):
    """Readable inherited shader cost and concrete instance permutation report."""

    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent)
        self.materials = MaterialService(project_root, database)
        self.asset_id = str(asset_id)
        self._authoring: dict[str, Any] = {}
        self._report: dict[str, Any] = {}
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout(); self.platform = QComboBox(self); self.platform.addItems(["desktop", "windows", "mobile", "android", "ios", "web"])
        toolbar.addWidget(QLabel("Target Platform")); toolbar.addWidget(self.platform); toolbar.addStretch(1); root.addLayout(toolbar)
        self.table = QTableWidget(0, 2, self); self.table.setHorizontalHeaderLabels(["Metric", "Value"]); self.table.horizontalHeader().setStretchLastSection(True); root.addWidget(self.table, 1)
        self.diagnostics = QLabel("", self); self.diagnostics.setWordWrap(True); root.addWidget(self.diagnostics)
        self.platform.currentTextChanged.connect(lambda _value: self._refresh())

    def load_settings(self, values: dict[str, Any]) -> None:
        self._authoring = dict(values or {}); self._refresh()

    load_instance_settings = load_settings

    def report(self) -> dict[str, Any]:
        return deepcopy(self._report)

    def _refresh(self) -> None:
        resolved, chain = _resolved_material_instance(self.materials, self._authoring)
        issues, stats = analyze_material_graph(dict(resolved.get("graph") or {}), platform=self.platform.currentText())
        overrides = dict(self._authoring.get("overrides") or {}); static_overrides = dict(self._authoring.get("static_switch_overrides") or {})
        active_switches = dict(resolved.get("static_switches") or {})
        permutation_key = ", ".join(f"{name}={'1' if value else '0'}" for name, value in sorted(active_switches.items())) or "Default"
        self._report = {**stats, "inheritance_depth": len(chain), "parameter_overrides": len(overrides), "static_overrides": len(static_overrides), "permutation_key": permutation_key}
        rows = (
            ("Inheritance depth", len(chain)), ("Parameter overrides", len(overrides)), ("Static overrides", len(static_overrides)),
            ("Graph nodes", stats["node_count"]), ("Estimated ALU", stats["estimated_alu"]), ("Texture samples", stats["texture_samples"]),
            ("Potential graph permutations", stats["permutations"]), ("This instance permutation", permutation_key),
        )
        self.table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(str(name))); self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        warnings = [issue.message for issue in issues]
        budget = "HIGH COST" if stats["estimated_alu"] > 120 or stats["texture_samples"] > 12 else "WITHIN GUIDANCE"
        self.diagnostics.setText(f"{budget} - " + (" - ".join(warnings) if warnings else "No graph diagnostics for this target."))


class MaterialCompileInspectorWidget(QWidget):
    """Truthful shader cost, permutation, and generated-source inspection."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.platform = QComboBox(self); self.platform.addItems(["desktop", "mobile", "windows", "linux", "macos"])
        self.quality = QComboBox(self); self.quality.addItems(["low", "medium", "high", "cinematic"])
        controls.addWidget(QLabel("Target")); controls.addWidget(self.platform)
        controls.addWidget(QLabel("Quality")); controls.addWidget(self.quality); controls.addStretch(1)
        root.addLayout(controls)
        self.stats = QTableWidget(0, 2, self); self.stats.setHorizontalHeaderLabels(["Metric", "Value"])
        root.addWidget(self.stats, 1)
        self.diagnostics = QLabel(self); self.diagnostics.setWordWrap(True); root.addWidget(self.diagnostics)
        self._values: dict[str, Any] = {}
        self.platform.currentTextChanged.connect(self._refresh)
        self.quality.currentTextChanged.connect(self._refresh)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._values = dict(values or {}); self._refresh()

    def _refresh(self, *_args) -> None:
        issues, stats = analyze_material_graph(dict(self._values.get("graph") or {}), platform=self.platform.currentText())
        rows = (
            ("Nodes", stats["node_count"]), ("Connections", stats["connection_count"]),
            ("Estimated ALU", stats["estimated_alu"]), ("Texture Samples", stats["texture_samples"]),
            ("Static Switches", stats["static_switches"]), ("Maximum Permutations", stats["permutations"]),
            ("Expensive Nodes", ", ".join(stats["expensive_nodes"]) or "None"),
        )
        self.stats.setRowCount(0)
        for label, value in rows:
            row = self.stats.rowCount(); self.stats.insertRow(row)
            self.stats.setItem(row, 0, QTableWidgetItem(str(label))); self.stats.setItem(row, 1, QTableWidgetItem(str(value)))
        self.diagnostics.setText("\n".join(f"{item.severity.upper()} • {item.message}" for item in issues) or "READY • No graph diagnostics for this target.")


class ShaderGeneratedCodeWidget(QWidget):
    """Readable generated-code preview with explicit stage and target controls."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self); controls = QHBoxLayout()
        self.stage = QComboBox(self); self.stage.addItems(["surface", "vertex", "fragment", "compute", "post_process"])
        self.language = QComboBox(self); self.language.addItems(["portable", "hlsl", "glsl", "metal", "spirv"])
        self.platform = QComboBox(self); self.platform.addItems(["desktop", "windows", "linux", "macos", "mobile"])
        controls.addWidget(QLabel("Stage")); controls.addWidget(self.stage)
        controls.addWidget(QLabel("Language")); controls.addWidget(self.language)
        controls.addWidget(QLabel("Platform")); controls.addWidget(self.platform); controls.addStretch(1)
        root.addLayout(controls)
        self.code = QPlainTextEdit(self); self.code.setReadOnly(True)
        self.code.setStyleSheet("font-family:Consolas,monospace; background:#071018; color:#cde8f6;")
        root.addWidget(self.code, 1)
        self.summary = QLabel(self); root.addWidget(self.summary)
        self._values: dict[str, Any] = {}
        self.stage.currentTextChanged.connect(self._edited)
        self.language.currentTextChanged.connect(self._edited)
        self.platform.currentTextChanged.connect(self._refresh)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._values = dict(values or {})
        for control in (self.stage, self.language): control.blockSignals(True)
        self.stage.setCurrentText(str(self._values.get("stage") or "surface"))
        self.language.setCurrentText(str(self._values.get("language") or "portable"))
        for control in (self.stage, self.language): control.blockSignals(False)
        self._refresh()

    def settings(self) -> dict[str, Any]:
        return {"stage": self.stage.currentText(), "language": self.language.currentText()}

    def _edited(self, *_args) -> None:
        self._refresh(); self.changed.emit()

    def _refresh(self, *_args) -> None:
        graph = dict(self._values.get("graph") or {})
        nodes = list(graph.get("nodes") or ())
        lines = [
            "// Tech Connector Shader Graph Preview",
            f"// stage={self.stage.currentText()} language={self.language.currentText()} platform={self.platform.currentText()}",
            "float4 TC_ShaderMain(float2 uv0) {",
            "    float4 result = float4(1.0, 1.0, 1.0, 1.0);",
        ]
        for index, node in enumerate(nodes):
            lines.append(f"    // [{index}] {node.get('opcode', 'node')} : {node.get('title', 'Node')}")
        lines.extend(["    return result;", "}"])
        self.code.setPlainText("\n".join(lines) + "\n")
        issues, stats = analyze_material_graph(graph, platform=self.platform.currentText())
        self.summary.setText(f"{stats['node_count']} nodes • {stats['estimated_alu']} ALU • {stats['texture_samples']} texture sample(s) • {len(issues)} diagnostic(s)")


class TextureInspectorEditorWidget(QWidget):
    """Texture import intent, mip, compression, and channel-packing controls."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self); form = QFormLayout()
        self.usage = QComboBox(self); self.usage.addItems(["color", "normal", "masks", "hdr", "ui", "data", "cubemap", "volume"])
        self.color_space = QComboBox(self); self.color_space.addItems(["srgb", "linear", "acescg"])
        self.compression = QComboBox(self); self.compression.addItems(["auto", "bc1", "bc3", "bc5", "bc6h", "bc7", "astc", "etc2", "uncompressed"])
        self.mips = QCheckBox("Generate full mip chain", self)
        self.max_size = QComboBox(self); self.max_size.addItems(["0", "256", "512", "1024", "2048", "4096", "8192", "16384"])
        self.streaming = QCheckBox("Stream high-resolution mips", self)
        self.virtual = QCheckBox("Virtual texture", self)
        self.channel_pack = QLineEdit(self); self.channel_pack.setPlaceholderText("R=AO, G=Roughness, B=Metalness, A=Mask")
        form.addRow("Usage", self.usage); form.addRow("Color Space", self.color_space)
        form.addRow("Compression", self.compression); form.addRow("Mips", self.mips)
        form.addRow("Maximum Size", self.max_size); form.addRow("Streaming", self.streaming)
        form.addRow("Virtual Texture", self.virtual); form.addRow("Channel Packing", self.channel_pack)
        root.addLayout(form)
        self.summary = QLabel(self); self.summary.setWordWrap(True); root.addWidget(self.summary); root.addStretch(1)
        for widget in (self.usage, self.color_space, self.compression, self.max_size): widget.currentTextChanged.connect(self._edited)
        for widget in (self.mips, self.streaming, self.virtual): widget.toggled.connect(self._edited)
        self.channel_pack.editingFinished.connect(self._edited)
        self._loading = False

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True
        self.usage.setCurrentText(str(values.get("usage") or "color"))
        self.color_space.setCurrentText(str(values.get("color_space") or "srgb"))
        self.compression.setCurrentText(str(values.get("compression") or "auto"))
        self.mips.setChecked(bool(values.get("generate_mips", True)))
        self.max_size.setCurrentText(str(values.get("max_size", 0)))
        self.streaming.setChecked(bool(values.get("streaming", True)))
        self.virtual.setChecked(bool(values.get("virtual_texture", False)))
        self.channel_pack.setText(str(values.get("channel_packing") or ""))
        self._loading = False; self._refresh_summary()

    def settings(self) -> dict[str, Any]:
        return {"usage": self.usage.currentText(), "color_space": self.color_space.currentText(),
                "compression": self.compression.currentText(), "generate_mips": self.mips.isChecked(),
                "max_size": int(self.max_size.currentText()), "streaming": self.streaming.isChecked(),
                "virtual_texture": self.virtual.isChecked(), "channel_packing": self.channel_pack.text().strip()}

    def validation_issues(self) -> list[str]:
        issues = []
        if self.usage.currentText() in {"normal", "masks", "data"} and self.color_space.currentText() != "linear":
            issues.append(f"{self.usage.currentText().title()} textures should use Linear color space.")
        if self.usage.currentText() == "normal" and self.compression.currentText() not in {"auto", "bc5", "astc", "uncompressed"}:
            issues.append("Normal maps should use BC5, ASTC, or automatic compression.")
        return issues

    def _edited(self, *_args) -> None:
        if not self._loading:
            if self.usage.currentText() in {"normal", "masks", "data"}: self.color_space.setCurrentText("linear")
            self._refresh_summary(); self.changed.emit()

    def _refresh_summary(self) -> None:
        self.summary.setText(f"{self.usage.currentText().title()} • {self.color_space.currentText()} • {self.compression.currentText().upper()} • " + ("mipped" if self.mips.isChecked() else "no mips"))


class MaterialPreviewEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.canvas = MaterialPreviewCanvas(self)
        root.addWidget(self.canvas, 1)
        controls = QFormLayout()
        preset_row = QHBoxLayout()
        self.preset = QComboBox(self)
        self.preset.addItems(["default_lit", "unlit", "glass", "clear_coat", "skin", "cloth", "decal", "post_process"])
        apply_preset = QPushButton("Apply Preset", self)
        apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.preset); preset_row.addWidget(apply_preset)
        self.domain = QComboBox(self); self.domain.addItems(list(MATERIAL_DOMAINS))
        self.shading_model = QComboBox(self); self.shading_model.addItems(list(MATERIAL_SHADING_MODELS))
        self.blend_mode = QComboBox(self); self.blend_mode.addItems(list(MATERIAL_BLEND_MODES))
        self.two_sided = QCheckBox("Render both sides", self)
        self.base_color = QLineEdit(self)
        self.base_color.setPlaceholderText("#RRGGBB")
        self.roughness = QDoubleSpinBox(self)
        self.roughness.setRange(0.0, 1.0)
        self.roughness.setDecimals(4)
        self.roughness.setSingleStep(0.05)
        self.metalness = QDoubleSpinBox(self)
        self.metalness.setRange(0.0, 1.0)
        self.metalness.setDecimals(4)
        self.metalness.setSingleStep(0.05)
        self.opacity = QDoubleSpinBox(self); self.opacity.setRange(0.0, 1.0); self.opacity.setDecimals(4); self.opacity.setValue(1.0)
        self.emissive_intensity = QDoubleSpinBox(self); self.emissive_intensity.setRange(0.0, 100000.0); self.emissive_intensity.setDecimals(3)
        self.exposure = QDoubleSpinBox(self)
        self.exposure.setRange(-5.0, 5.0)
        self.exposure.setSingleStep(0.25)
        self.preview_mesh = QComboBox(self)
        self.preview_mesh.addItems(["Sphere", "Cube", "Plane"])
        self.environment = QComboBox(self)
        self.environment.addItems(["Studio", "Outdoor", "Night", "Neutral"])
        controls.addRow("Preset", preset_row)
        controls.addRow("Domain", self.domain)
        controls.addRow("Shading Model", self.shading_model)
        controls.addRow("Blend Mode", self.blend_mode)
        controls.addRow("Two Sided", self.two_sided)
        controls.addRow("Base Color", self.base_color)
        controls.addRow("Roughness", self.roughness)
        controls.addRow("Metalness", self.metalness)
        controls.addRow("Opacity", self.opacity)
        controls.addRow("Emissive Intensity", self.emissive_intensity)
        controls.addRow("Exposure", self.exposure)
        controls.addRow("Preview Mesh", self.preview_mesh)
        controls.addRow("Environment", self.environment)
        root.addLayout(controls)
        self.base_color.editingFinished.connect(self._update_preview)
        self.roughness.valueChanged.connect(self._update_preview)
        self.metalness.valueChanged.connect(self._update_preview)
        self.opacity.valueChanged.connect(self._update_preview)
        self.emissive_intensity.valueChanged.connect(self._update_preview)
        self.domain.currentTextChanged.connect(self._update_preview)
        self.shading_model.currentTextChanged.connect(self._update_preview)
        self.blend_mode.currentTextChanged.connect(self._update_preview)
        self.two_sided.toggled.connect(self._update_preview)
        self.exposure.valueChanged.connect(self._update_preview)
        self.preview_mesh.currentTextChanged.connect(self._update_preview)
        self.environment.currentTextChanged.connect(self._update_preview)

    def load_settings(self, values: dict[str, Any]) -> None:
        controls = (
            self.base_color, self.roughness, self.metalness, self.exposure,
            self.preview_mesh, self.environment, self.preset, self.domain, self.shading_model,
            self.blend_mode, self.two_sided, self.opacity, self.emissive_intensity,
        )
        for control in controls:
            control.blockSignals(True)
        self.base_color.setText(str(values.get("base_color") or "#ffffff"))
        self.roughness.setValue(float(values.get("roughness", 0.5)))
        self.metalness.setValue(float(values.get("metalness", 0.0)))
        self.opacity.setValue(float(values.get("opacity", 1.0)))
        self.emissive_intensity.setValue(float(values.get("emissive_intensity", 0.0)))
        self.preset.setCurrentText(str(values.get("preset") or "default_lit"))
        self.domain.setCurrentText(str(values.get("domain") or "surface"))
        self.shading_model.setCurrentText(str(values.get("shading_model") or "pbr"))
        self.blend_mode.setCurrentText(str(values.get("blend_mode") or "opaque"))
        self.two_sided.setChecked(bool(values.get("two_sided", False)))
        self.exposure.setValue(float(values.get("preview_exposure", 0.0)))
        self.preview_mesh.setCurrentText(str(values.get("preview_mesh") or "Sphere"))
        self.environment.setCurrentText(str(values.get("preview_environment") or "Studio"))
        for control in controls:
            control.blockSignals(False)
        self._sync_canvas()

    def settings(self) -> dict[str, Any]:
        return {
            "base_color": self.base_color.text().strip() or "#ffffff",
            "roughness": float(self.roughness.value()),
            "metalness": float(self.metalness.value()),
            "preset": self.preset.currentText(),
            "domain": self.domain.currentText(),
            "shading_model": self.shading_model.currentText(),
            "blend_mode": self.blend_mode.currentText(),
            "two_sided": self.two_sided.isChecked(),
            "opacity": float(self.opacity.value()),
            "emissive_intensity": float(self.emissive_intensity.value()),
            "preview_exposure": float(self.exposure.value()),
            "preview_mesh": self.preview_mesh.currentText(),
            "preview_environment": self.environment.currentText(),
        }

    def validation_issues(self) -> list[str]:
        color = QColor(self.base_color.text().strip())
        return [] if color.isValid() else ["Material base color must be a valid color such as #ffffff."]

    def _sync_canvas(self) -> None:
        color = QColor(self.base_color.text().strip())
        self.canvas.base_color = color if color.isValid() else QColor("#ff4f68")
        self.canvas.roughness = float(self.roughness.value())
        self.canvas.metalness = float(self.metalness.value())
        self.canvas.exposure = float(self.exposure.value())
        self.canvas.preview_mesh = self.preview_mesh.currentText()
        self.canvas.environment = self.environment.currentText()
        self.canvas.update()

    def _update_preview(self, *_args) -> None:
        self._sync_canvas()
        self.changed.emit()

    def _apply_preset(self) -> None:
        current = self.settings()
        values = material_preset(self.preset.currentText())
        for key in ("preview_mesh", "preview_environment", "preview_exposure"):
            values[key] = current[key]
        self.load_settings(values)
        self.changed.emit()


class MeshInspectionCanvas(QWidget):
    """Lightweight mesh-analysis view with explicit diagnostic display modes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = "lit"
        self.setMinimumHeight(250)
        self.setAccessibleName("Mesh inspection preview")

    def set_mode(self, mode: str) -> None:
        self.mode = str(mode or "lit").casefold().replace(" ", "_")
        self.setAccessibleDescription(f"Mesh preview showing {self.mode.replace('_', ' ')} visualization")
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#071018"))
        width, height = float(self.width()), float(self.height())
        center = QPointF(width * 0.5, height * 0.52)
        scale = min(width, height) * 0.28
        if self.mode == "uv_checker":
            size = scale * 1.65
            left, top = center.x() - size * 0.5, center.y() - size * 0.5
            for y in range(8):
                for x in range(8):
                    color = QColor("#2b6380" if (x + y) % 2 else "#163247")
                    painter.fillRect(QRectF(left + x * size / 8, top + y * size / 8, size / 8, size / 8), color)
            painter.setPen(QPen(QColor("#75d7ff"), 2))
            painter.drawRect(QRectF(left, top, size, size))
            painter.drawLine(QPointF(left, top + size), QPointF(left + size * 0.5, top))
            painter.drawLine(QPointF(left + size * 0.5, top), QPointF(left + size, top + size))
        else:
            points = [QPointF(center.x() + x * scale, center.y() + y * scale) for x, y in ((-0.65,-0.45),(0.15,-0.72),(0.68,-0.25),(0.55,0.55),(-0.3,0.72),(-0.72,0.2))]
            painter.setBrush(QColor("#294b61" if self.mode != "collision" else "#2d413f"))
            painter.setPen(QPen(QColor("#78c9ef"), 2))
            painter.drawPolygon(QPolygonF(points))
            for first, second in ((0,2),(0,3),(0,4),(1,3),(1,5),(2,4),(2,5)):
                painter.drawLine(points[first], points[second])
            if self.mode == "normals":
                painter.setPen(QPen(QColor("#70efad"), 2))
                for point in points:
                    painter.drawLine(point, QPointF(point.x(), point.y() - scale * 0.22))
            elif self.mode == "collision":
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#ffbf69"), 3, Qt.DashLine))
                painter.drawEllipse(QRectF(center.x() - scale * 0.9, center.y() - scale * 0.82, scale * 1.8, scale * 1.64))
            elif self.mode == "wireframe":
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#8ad8ff"), 1))
                painter.drawPolygon(QPolygonF(points))
        painter.setPen(QColor("#9fb7c8"))
        painter.drawText(QRectF(12, 10, width - 24, 24), Qt.AlignLeft, self.mode.replace("_", " ").title())


class MeshInspectionEditorWidget(QWidget):
    """Mesh viewport diagnostics, source statistics, and platform cost estimates."""

    changed = Signal()
    PLATFORM_BUDGETS = {
        "desktop": (1_000_000, 128 * 1024 * 1024),
        "mobile": (250_000, 32 * 1024 * 1024),
        "web": (500_000, 64 * 1024 * 1024),
    }

    def __init__(self, source_path: str | Path, asset_type: str, parent=None) -> None:
        super().__init__(parent)
        self.source_path = Path(source_path)
        self.asset_type = str(asset_type)
        self._values: dict[str, Any] = {}
        self._statistics: dict[str, Any] = {}
        self._loading = False
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.mode = QComboBox(self)
        for label, value in (("Lit", "lit"), ("Wireframe", "wireframe"), ("UV Checker", "uv_checker"), ("Vertex Normals", "normals"), ("Collision", "collision")):
            self.mode.addItem(label, value)
        self.lod = QComboBox(self)
        self.platform = QComboBox(self)
        self.platform.addItems(["desktop", "mobile", "web"])
        controls.addWidget(QLabel("Visualization")); controls.addWidget(self.mode)
        controls.addWidget(QLabel("LOD")); controls.addWidget(self.lod)
        controls.addWidget(QLabel("Budget")); controls.addWidget(self.platform)
        controls.addStretch(1); root.addLayout(controls)
        self.canvas = MeshInspectionCanvas(self); root.addWidget(self.canvas, 2)
        self.summary = QLabel(self); self.summary.setWordWrap(True); self.summary.setAccessibleName("Mesh performance summary"); root.addWidget(self.summary)
        self.metrics = QTableWidget(0, 3, self)
        self.metrics.setHorizontalHeaderLabels(["Metric", "Value", "Meaning"])
        self.metrics.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.metrics, 1)
        self.mode.currentIndexChanged.connect(self._changed)
        self.lod.currentIndexChanged.connect(self._changed)
        self.platform.currentTextChanged.connect(self._changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._values = dict(values or {})
        preview = dict(self._values.get("mesh_preview") or {})
        self._statistics = self._inspect_source(self._values)
        self._loading = True
        mode_index = self.mode.findData(str(preview.get("visualization") or "lit"))
        self.mode.setCurrentIndex(max(0, mode_index))
        self.platform.setCurrentText(str(preview.get("platform") or "desktop"))
        self.lod.clear()
        lods = list(self._values.get("lods") or ())
        self.lod.addItem("LOD 0 · 100%", 100.0)
        authored = lods[1:] if lods and float(dict(lods[0]).get("triangle_percent", 100.0)) == 100.0 else lods
        for index, item in enumerate(authored, 1):
            percent = float(dict(item).get("triangle_percent", 100.0))
            self.lod.addItem(f"LOD {index} · {percent:g}%", percent)
        requested = int(preview.get("lod", 0))
        self.lod.setCurrentIndex(max(0, min(requested, self.lod.count() - 1)))
        self._loading = False
        self._refresh_report()

    def settings(self) -> dict[str, Any]:
        return {"mesh_preview": {"visualization": str(self.mode.currentData() or "lit"), "lod": self.lod.currentIndex(), "platform": self.platform.currentText()}}

    def update_related_settings(self, values: dict[str, Any]) -> None:
        """Refresh LOD and slot costs without reparsing a potentially large source mesh."""
        selected = self.lod.currentIndex(); self._values.update(deepcopy(dict(values or {})))
        if "material_slots" in values or "materials" in values:
            self._statistics["material_slots"] = len(values.get("material_slots") or values.get("materials") or ())
        self._loading = True; self.lod.clear(); lods = list(self._values.get("lods") or ())
        self.lod.addItem("LOD 0 · 100%", 100.0)
        authored = lods[1:] if lods and float(dict(lods[0]).get("triangle_percent", 100.0)) == 100.0 else lods
        for index, item in enumerate(authored, 1):
            percent = float(dict(item).get("triangle_percent", 100.0)); self.lod.addItem(f"LOD {index} · {percent:g}%", percent)
        self.lod.setCurrentIndex(max(0, min(selected, self.lod.count() - 1))); self._loading = False; self._refresh_report()

    def report(self) -> dict[str, Any]:
        source_triangles = int(self._statistics.get("triangles") or 0)
        ratio = float(self.lod.currentData() or 100.0) / 100.0
        triangles = max(0, round(source_triangles * ratio))
        vertices = int(self._statistics.get("vertices") or 0)
        uv_channels = max(0, int(self._statistics.get("uv_channels") or 0))
        stride = 12 + 12 + 16 + uv_channels * 8 + (16 if self.asset_type == "tc.skeletal_mesh" else 0)
        gpu_bytes = vertices * stride + triangles * 3 * (2 if vertices < 65536 else 4)
        slots = max(1, int(self._statistics.get("material_slots") or 0))
        triangle_budget, memory_budget = self.PLATFORM_BUDGETS.get(self.platform.currentText(), self.PLATFORM_BUDGETS["desktop"])
        return {**self._statistics, "lod": self.lod.currentIndex(), "triangle_percent": ratio * 100.0,
                "visible_triangles": triangles, "estimated_gpu_bytes": gpu_bytes, "estimated_draw_calls": slots,
                "triangle_budget": triangle_budget, "memory_budget": memory_budget,
                "over_budget": triangles > triangle_budget or gpu_bytes > memory_budget}

    def validation_issues(self) -> list[str]:
        return []

    def _changed(self, *_args) -> None:
        if not self._loading:
            self._refresh_report(); self.changed.emit()

    def _refresh_report(self) -> None:
        self.canvas.set_mode(str(self.mode.currentData() or "lit"))
        report = self.report(); self.metrics.setRowCount(0)
        bounds = report.get("bounds") or {}; minimum, maximum = bounds.get("minimum", []), bounds.get("maximum", [])
        rows = (
            ("Source vertices", f"{int(report.get('vertices') or 0):,}", "Imported vertex count"),
            ("Visible triangles", f"{int(report['visible_triangles']):,}", f"LOD {report['lod']} at {report['triangle_percent']:g}%"),
            ("UV channels", str(int(report.get("uv_channels") or 0)), "Texture coordinate sets"),
            ("Normals", "Present" if report.get("has_normals") else "Missing", "Imported vertex-normal data"),
            ("Material slots / draws", f"{int(report.get('material_slots') or 0)} / {report['estimated_draw_calls']}", "Estimated draw submissions"),
            ("GPU geometry", self._format_bytes(report["estimated_gpu_bytes"]), "Vertex and index buffers"),
            ("Source file", self._format_bytes(int(report.get("source_bytes") or 0)), self.source_path.name),
            ("Bounds minimum", self._vector(minimum), "Local-space XYZ"),
            ("Bounds maximum", self._vector(maximum), "Local-space XYZ"),
        )
        for values in rows:
            row = self.metrics.rowCount(); self.metrics.insertRow(row)
            for column, value in enumerate(values): self.metrics.setItem(row, column, QTableWidgetItem(str(value)))
        status = "OVER BUDGET" if report["over_budget"] else "Within budget"
        self.summary.setText(f"{status} for {self.platform.currentText()} • {report['visible_triangles']:,} / {report['triangle_budget']:,} triangles • {self._format_bytes(report['estimated_gpu_bytes'])} / {self._format_bytes(report['memory_budget'])} geometry memory")
        self.summary.setStyleSheet("color:#ef8793; font-weight:700;" if report["over_budget"] else "color:#72d9ca;")

    def _inspect_source(self, values: dict[str, Any]) -> dict[str, Any]:
        supplied = dict(values.get("mesh_statistics") or values.get("statistics") or {})
        result = {
            "vertices": int(supplied.get("vertices") or supplied.get("vertex_count") or 0),
            "triangles": int(supplied.get("triangles") or supplied.get("triangle_count") or 0),
            "uv_channels": int(supplied.get("uv_channels") or 0),
            "has_normals": bool(supplied.get("has_normals", False)),
            "material_slots": len(values.get("material_slots") or values.get("materials") or ()),
            "bounds": dict(supplied.get("bounds") or values.get("bounds") or {}),
            "source_bytes": self.source_path.stat().st_size if self.source_path.is_file() else 0,
        }
        if self.source_path.suffix.casefold() != ".obj" or not self.source_path.is_file():
            return result
        vertices: list[tuple[float, float, float]] = []; triangles = texture_coordinates = normals = 0; materials: set[str] = set()
        try:
            with self.source_path.open("r", encoding="utf-8", errors="ignore") as stream:
                for line in stream:
                    if line.startswith("v "):
                        parts = line.split()
                        if len(parts) >= 4: vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    elif line.startswith("vt "): texture_coordinates += 1
                    elif line.startswith("vn "): normals += 1
                    elif line.startswith("f "): triangles += max(0, len(line.split()) - 3)
                    elif line.startswith("usemtl "): materials.add(line[7:].strip())
        except (OSError, ValueError):
            return result
        result.update({"vertices": len(vertices), "triangles": triangles, "uv_channels": 1 if texture_coordinates else 0,
                       "has_normals": bool(normals), "material_slots": len(materials) or result["material_slots"]})
        if vertices:
            result["bounds"] = {"minimum": [min(value[index] for value in vertices) for index in range(3)],
                                "maximum": [max(value[index] for value in vertices) for index in range(3)]}
        return result

    @staticmethod
    def _vector(values: Any) -> str:
        return ", ".join(f"{float(value):g}" for value in values) if values else "Unavailable"

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, int(value)))
        for unit in ("B", "KiB", "MiB", "GiB"):
            if size < 1024.0 or unit == "GiB": return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GiB"


class MeshLodEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        guidance = QLabel(
            "Author non-destructive runtime LOD targets. LOD 0 is the source mesh; lower screen sizes transition to reduced geometry."
        )
        guidance.setWordWrap(True)
        guidance.setStyleSheet("color:#9cb4c5;")
        root.addWidget(guidance)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["LOD", "Screen Size", "Triangles %", "Max Deviation"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        controls = QHBoxLayout()
        add = QPushButton("+ LOD")
        generate = QPushButton("Generate Recommended")
        remove = QPushButton("Delete LOD")
        controls.addWidget(add)
        controls.addWidget(generate)
        controls.addWidget(remove)
        controls.addStretch(1)
        self.cost = QLabel("No authored LOD targets")
        controls.addWidget(self.cost)
        root.addLayout(controls)
        add.clicked.connect(self.add_lod)
        generate.clicked.connect(self.generate_recommended)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self._table_changed)

    def load_lods(self, values: list[dict[str, Any]] | None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for index, value in enumerate(values or ()):
            self._append_lod(
                index,
                float(value.get("screen_size", max(0.05, 1.0 / (index + 1)))),
                float(value.get("triangle_percent", 100.0 if index == 0 else 50.0)),
                float(value.get("max_deviation", 0.0)),
            )
        self.table.blockSignals(False)
        self._update_cost()

    def lods(self) -> list[dict[str, Any]]:
        result = []
        for row in range(self.table.rowCount()):
            result.append({
                "level": row,
                "screen_size": _table_float(self.table, row, 1),
                "triangle_percent": _table_float(self.table, row, 2),
                "max_deviation": _table_float(self.table, row, 3),
            })
        return result

    def add_lod(self) -> None:
        row = self.table.rowCount()
        previous = self.lods()[-1] if row else None
        self.table.blockSignals(True)
        self._append_lod(
            row,
            max(0.01, float(previous["screen_size"]) * 0.5) if previous else 1.0,
            max(1.0, float(previous["triangle_percent"]) * 0.5) if previous else 100.0,
            float(previous["max_deviation"]) + 0.5 if previous else 0.0,
        )
        self.table.blockSignals(False)
        self._table_changed()

    def generate_recommended(self) -> None:
        self.load_lods([
            {"screen_size": 1.0, "triangle_percent": 100.0, "max_deviation": 0.0},
            {"screen_size": 0.5, "triangle_percent": 50.0, "max_deviation": 0.5},
            {"screen_size": 0.2, "triangle_percent": 25.0, "max_deviation": 1.5},
            {"screen_size": 0.08, "triangle_percent": 12.5, "max_deviation": 4.0},
        ])
        self.changed.emit()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._renumber()
            self._table_changed()

    def validation_issues(self) -> list[str]:
        lods = self.lods()
        issues = []
        if lods and (lods[0]["triangle_percent"] != 100.0 or lods[0]["screen_size"] != 1.0):
            issues.append("LOD 0 must preserve 100% triangles at screen size 1.0.")
        for previous, current in zip(lods, lods[1:]):
            if current["screen_size"] >= previous["screen_size"]:
                issues.append("LOD screen sizes must decrease at every level.")
                break
            if current["triangle_percent"] >= previous["triangle_percent"]:
                issues.append("LOD triangle percentages must decrease at every level.")
                break
        if any(not 0.0 < lod["screen_size"] <= 1.0 for lod in lods):
            issues.append("LOD screen size must be greater than 0 and at most 1.")
        if any(not 0.0 < lod["triangle_percent"] <= 100.0 for lod in lods):
            issues.append("LOD triangle percentage must be greater than 0 and at most 100.")
        return issues

    def _append_lod(self, level: int, screen_size: float, triangles: float, deviation: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        level_item = QTableWidgetItem(str(level))
        level_item.setFlags(level_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, level_item)
        self.table.setItem(row, 1, QTableWidgetItem(f"{screen_size:.4g}"))
        self.table.setItem(row, 2, QTableWidgetItem(f"{triangles:.4g}"))
        self.table.setItem(row, 3, QTableWidgetItem(f"{deviation:.4g}"))

    def _renumber(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setText(str(row))

    def _table_changed(self, *_args) -> None:
        self._update_cost()
        self.changed.emit()

    def _update_cost(self) -> None:
        lods = self.lods()
        if not lods:
            self.cost.setText("No authored LOD targets")
            return
        average = sum(float(item["triangle_percent"]) for item in lods) / len(lods)
        self.cost.setText(f"{len(lods)} levels • average {average:.1f}% source triangles")


class CharacterLodEditorWidget(QWidget):
    """Coupled Mesh LOD and Bone LOD workflow for skinned characters."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        summary = QLabel(
            "Mesh LODs reduce geometry while Bone LODs reduce pose evaluation. Source geometry, skeleton, and DCC weights remain unchanged."
        )
        summary.setWordWrap(True)
        root.addWidget(summary)
        controls = QHBoxLayout()
        self.profile = QComboBox(self)
        self.profile.addItems(list(CHARACTER_PERFORMANCE_PROFILES))
        self.lod_count = QSpinBox(self); self.lod_count.setRange(1, 5); self.lod_count.setValue(4)
        self.bone_source = QLineEdit(self)
        self.bone_source.setPlaceholderText("Optional hierarchy: pelvis, spine:pelvis, head:spine, finger:hand")
        self.preserve = QLineEdit(self)
        self.preserve.setPlaceholderText("Always evaluate: weapon_socket, ik_hand_l")
        generate = QPushButton("Generate Mesh + Bone LODs", self)
        generate.clicked.connect(self.generate_recommended)
        for label, widget in (("Profile", self.profile), ("Levels", self.lod_count), ("Bones", self.bone_source), ("Preserve", self.preserve)):
            controls.addWidget(QLabel(label)); controls.addWidget(widget)
        controls.addWidget(generate)
        root.addLayout(controls)
        self.mesh_lods = QTableWidget(0, 7, self)
        self.mesh_lods.setHorizontalHeaderLabels(["LOD", "Screen Size", "Triangles %", "Max Deviation", "Influences", "Bone LOD", "Hysteresis"])
        root.addWidget(self.mesh_lods, 1)
        self.bone_lods = QTableWidget(0, 5, self)
        self.bone_lods.setHorizontalHeaderLabels(["Bone LOD", "Retained", "Removed", "Remapped", "Update Divisor"])
        self.bone_lods.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.bone_lods, 1)
        self.cost = QLabel("Generate LODs to see the runtime cost plan.", self)
        self.cost.setWordWrap(True)
        root.addWidget(self.cost)
        self._settings: dict[str, Any] = {}
        self._bone_lod_values: list[dict[str, Any]] = []
        self._refreshing = False
        self.profile.currentTextChanged.connect(self._edited)
        self.mesh_lods.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._settings = dict(values or {})
        self._refreshing = True
        self.profile.setCurrentText(str(self._settings.get("performance_profile") or "balanced"))
        lods = list(self._settings.get("lods") or ())
        self.lod_count.setValue(max(1, min(5, len(lods) or 4)))
        self.mesh_lods.setRowCount(0)
        for index, lod in enumerate(lods):
            self._append_mesh_lod(index, lod)
        self._bone_lod_values = [dict(value) for value in self._settings.get("bone_lods") or ()]
        self._refresh_bone_lods()
        self._refreshing = False
        self._update_cost()

    def settings(self) -> dict[str, Any]:
        result = dict(self._settings)
        result.update({"performance_profile": self.profile.currentText(), "lods": self._mesh_lod_values(),
                       "bone_lods": [dict(value) for value in self._bone_lod_values]})
        return result

    def validation_issues(self) -> list[str]:
        return [issue.message for issue in validate_character_lods(self.settings()) if issue.severity == "error"]

    def generate_recommended(self) -> None:
        count = self.lod_count.value()
        hierarchy = []
        for token in (item.strip() for item in self.bone_source.text().split(",")):
            if not token:
                continue
            name, _separator, parent = token.partition(":")
            hierarchy.append({"name": name.strip(), "parent": parent.strip()})
        preserve = [item.strip() for item in self.preserve.text().split(",") if item.strip()]
        self._refreshing = True
        self.mesh_lods.setRowCount(0)
        for index, lod in enumerate(recommended_mesh_lods(count)):
            self._append_mesh_lod(index, lod)
        self._bone_lod_values = generate_bone_lods(hierarchy, count=count, preserve_bones=preserve)
        self._refresh_bone_lods()
        self._refreshing = False
        self._update_cost()
        self.changed.emit()

    def _mesh_lod_values(self) -> list[dict[str, Any]]:
        values = []
        for row in range(self.mesh_lods.rowCount()):
            values.append({"level": row, "screen_size": _table_float(self.mesh_lods, row, 1),
                           "triangle_percent": _table_float(self.mesh_lods, row, 2),
                           "max_deviation": _table_float(self.mesh_lods, row, 3),
                           "max_influences": int(_table_float(self.mesh_lods, row, 4)),
                           "bone_lod": int(_table_float(self.mesh_lods, row, 5)),
                           "hysteresis": _table_float(self.mesh_lods, row, 6)})
        return values

    def _append_mesh_lod(self, index: int, lod: dict[str, Any]) -> None:
        row = self.mesh_lods.rowCount(); self.mesh_lods.insertRow(row)
        values = (index, lod.get("screen_size", 1.0), lod.get("triangle_percent", 100.0), lod.get("max_deviation", 0.0),
                  lod.get("max_influences", 4), lod.get("bone_lod", index), lod.get("hysteresis", 0.0))
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if column == 0: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.mesh_lods.setItem(row, column, item)

    def _refresh_bone_lods(self) -> None:
        self.bone_lods.setRowCount(0)
        for index, value in enumerate(self._bone_lod_values):
            row = self.bone_lods.rowCount(); self.bone_lods.insertRow(row)
            cells = (index, len(value.get("retained_bones") or ()), len(value.get("removed_bones") or ()),
                     len(value.get("parent_remap") or {}), value.get("evaluation_rate_divisor", 1))
            for column, cell in enumerate(cells): self.bone_lods.setItem(row, column, QTableWidgetItem(str(cell)))

    def _edited(self, *_args) -> None:
        if not self._refreshing:
            self._update_cost(); self.changed.emit()

    def _update_cost(self) -> None:
        lods = self._mesh_lod_values()
        if not lods:
            self.cost.setText("No Mesh LODs are authored; LOD 0 will be used at every distance.")
            return
        details = [f"LOD {item['level']}: {item['triangle_percent']:.1f}% triangles, {item['max_influences']} influences" for item in lods]
        self.cost.setText(f"{self.profile.currentText().title()} • " + " • ".join(details))


def _table_float(table: QTableWidget, row: int, column: int) -> float:
    item = table.item(row, column)
    try:
        return float(item.text()) if item is not None else 0.0
    except ValueError:
        return 0.0


class ProceduralIKEditorWidget(QWidget):
    changed = Signal()

    HEADERS = ("Limb", "Root Bone", "Joint Bone", "End Bone", "Pole X/Y/Z", "Probe Up", "Probe Down", "Foot Offset")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        note = QLabel("Ground probes run after authored animation. Each row solves one two-bone limb and contributes to pelvis compensation.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9cb4c5;")
        root.addWidget(note)
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        controls = QHBoxLayout()
        humanoid = QPushButton("Create Humanoid Legs")
        add = QPushButton("+ Limb")
        remove = QPushButton("Delete Limb")
        controls.addWidget(humanoid)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        self.summary = QLabel("No grounded limbs")
        controls.addWidget(self.summary)
        root.addLayout(controls)
        humanoid.clicked.connect(self.create_humanoid_legs)
        add.clicked.connect(self.add_limb)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self._changed)

    def load_limbs(self, limbs: list[dict[str, Any]] | None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for limb in limbs or ():
            self._append_limb(dict(limb))
        self.table.blockSignals(False)
        self._update_summary()

    def limbs(self) -> list[dict[str, Any]]:
        values = []
        for row in range(self.table.rowCount()):
            values.append({
                "id": _table_text(self.table, row, 0),
                "root_bone": _table_text(self.table, row, 1),
                "joint_bone": _table_text(self.table, row, 2),
                "end_bone": _table_text(self.table, row, 3),
                "pole_vector": _parse_vector(_table_text(self.table, row, 4), (0.0, 0.0, 1.0)),
                "probe_height": _table_float(self.table, row, 5),
                "probe_depth": _table_float(self.table, row, 6),
                "foot_offset": _table_float(self.table, row, 7),
            })
        return values

    def create_humanoid_legs(self) -> None:
        self.load_limbs([
            {"id": "left_leg", "root_bone": "thigh_l", "joint_bone": "calf_l", "end_bone": "foot_l", "pole_vector": [0, 0, 1], "probe_height": 0.5, "probe_depth": 1.0, "foot_offset": 0.04},
            {"id": "right_leg", "root_bone": "thigh_r", "joint_bone": "calf_r", "end_bone": "foot_r", "pole_vector": [0, 0, 1], "probe_height": 0.5, "probe_depth": 1.0, "foot_offset": 0.04},
        ])
        self.changed.emit()

    def add_limb(self) -> None:
        self.table.blockSignals(True)
        index = self.table.rowCount() + 1
        self._append_limb({"id": f"limb_{index}", "pole_vector": [0, 0, 1], "probe_height": 0.5, "probe_depth": 1.0, "foot_offset": 0.04})
        self.table.blockSignals(False)
        self._changed()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def validation_issues(self) -> list[str]:
        limbs = self.limbs()
        identifiers = [item["id"] for item in limbs]
        issues = []
        if "" in identifiers or len(identifiers) != len(set(identifiers)):
            issues.append("Procedural limb IDs must be present and unique.")
        for limb in limbs:
            if not all(limb[key] for key in ("root_bone", "joint_bone", "end_bone")):
                issues.append(f"{limb['id'] or 'Limb'} requires root, joint, and end bones.")
            if limb["probe_height"] < 0.0 or limb["probe_depth"] <= 0.0:
                issues.append(f"{limb['id'] or 'Limb'} requires non-negative probe height and positive probe depth.")
        return issues

    def _append_limb(self, limb: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        pole = limb.get("pole_vector") or [0, 0, 1]
        values = (
            limb.get("id", ""), limb.get("root_bone", ""), limb.get("joint_bone", ""), limb.get("end_bone", ""),
            ", ".join(str(value) for value in pole), limb.get("probe_height", 0.5),
            limb.get("probe_depth", 1.0), limb.get("foot_offset", 0.04),
        )
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _changed(self, *_args) -> None:
        self._update_summary()
        self.changed.emit()

    def _update_summary(self) -> None:
        count = self.table.rowCount()
        self.summary.setText(f"{count} grounded limb{'s' if count != 1 else ''}" if count else "No grounded limbs")


class VehicleRigEditorWidget(QWidget):
    changed = Signal()

    HEADERS = ("Wheel", "Mount X", "Mount Y", "Mount Z", "Radius", "Rest Length", "Travel", "Spring", "Damping", "Axle", "Steer", "Drive")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        note = QLabel("Raycast wheels preserve a lightweight chassis while providing independent suspension, steering, drive, braking, and anti-roll response.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9cb4c5;")
        root.addWidget(note)
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        controls = QHBoxLayout()
        preset = QPushButton("Create Four-Wheel Rig")
        add = QPushButton("+ Wheel")
        remove = QPushButton("Delete Wheel")
        controls.addWidget(preset)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        self.summary = QLabel("No wheels")
        controls.addWidget(self.summary)
        root.addLayout(controls)
        preset.clicked.connect(self.create_four_wheel_rig)
        add.clicked.connect(self.add_wheel)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self._changed)

    def load_wheels(self, wheels: list[dict[str, Any]] | None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for wheel in wheels or ():
            self._append_wheel(dict(wheel))
        self.table.blockSignals(False)
        self._update_summary()

    def wheels(self) -> list[dict[str, Any]]:
        values = []
        for row in range(self.table.rowCount()):
            values.append({
                "wheel_id": _table_text(self.table, row, 0),
                "mount_position": [_table_float(self.table, row, column) for column in (1, 2, 3)],
                "radius": _table_float(self.table, row, 4),
                "suspension_rest_length": _table_float(self.table, row, 5),
                "suspension_travel": _table_float(self.table, row, 6),
                "spring_stiffness": _table_float(self.table, row, 7),
                "spring_damping": _table_float(self.table, row, 8),
                "axle": _table_text(self.table, row, 9),
                "steerable": _table_bool(self.table, row, 10),
                "driven": _table_bool(self.table, row, 11),
            })
        return values

    def create_four_wheel_rig(self) -> None:
        wheels = []
        for axle, z, steer in (("front", 1.25, True), ("rear", -1.25, False)):
            for side, x in (("l", -0.8), ("r", 0.8)):
                wheels.append({
                    "wheel_id": f"{axle}_{side}", "mount_position": [x, 0.0, z], "radius": 0.34,
                    "suspension_rest_length": 0.32, "suspension_travel": 0.18,
                    "spring_stiffness": 32000.0, "spring_damping": 4200.0,
                    "axle": axle, "steerable": steer, "driven": True,
                })
        self.load_wheels(wheels)
        self.changed.emit()

    def add_wheel(self) -> None:
        self.table.blockSignals(True)
        self._append_wheel({"wheel_id": f"wheel_{self.table.rowCount() + 1}", "mount_position": [0, 0, 0]})
        self.table.blockSignals(False)
        self._changed()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def validation_issues(self) -> list[str]:
        wheels = self.wheels()
        identifiers = [wheel["wheel_id"] for wheel in wheels]
        issues = []
        if "" in identifiers or len(identifiers) != len(set(identifiers)):
            issues.append("Vehicle wheel IDs must be present and unique.")
        for wheel in wheels:
            if wheel["radius"] <= 0.0:
                issues.append(f"{wheel['wheel_id'] or 'Wheel'} requires a radius greater than zero.")
            if min(wheel["suspension_rest_length"], wheel["suspension_travel"], wheel["spring_stiffness"], wheel["spring_damping"]) < 0.0:
                issues.append(f"{wheel['wheel_id'] or 'Wheel'} suspension values cannot be negative.")
        return issues

    def _append_wheel(self, wheel: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        mount = list(wheel.get("mount_position") or [0, 0, 0])
        values = (
            wheel.get("wheel_id", ""), *mount, wheel.get("radius", 0.34),
            wheel.get("suspension_rest_length", 0.32), wheel.get("suspension_travel", 0.18),
            wheel.get("spring_stiffness", 32000.0), wheel.get("spring_damping", 4200.0),
            wheel.get("axle", "rear"), str(bool(wheel.get("steerable", False))).lower(),
            str(bool(wheel.get("driven", True))).lower(),
        )
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _changed(self, *_args) -> None:
        self._update_summary()
        self.changed.emit()

    def _update_summary(self) -> None:
        wheels = self.wheels()
        steer = sum(bool(wheel["steerable"]) for wheel in wheels)
        driven = sum(bool(wheel["driven"]) for wheel in wheels)
        self.summary.setText(f"{len(wheels)} wheels • {steer} steer • {driven} driven" if wheels else "No wheels")


def _table_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item is not None else ""


def _table_bool(table: QTableWidget, row: int, column: int) -> bool:
    return _table_text(table, row, column).casefold() in {"1", "true", "yes", "on"}


def _parse_vector(value: str, fallback: tuple[float, float, float]) -> list[float]:
    try:
        parts = [float(part.strip()) for part in value.replace(";", ",").split(",")]
    except ValueError:
        return list(fallback)
    return parts if len(parts) == 3 else list(fallback)


class InputMapEditorWidget(QWidget):
    changed = Signal()

    HEADERS = ("Context", "Priority", "Action", "Value Type", "Device", "Key", "Modifiers", "Scale", "Consume")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        preset = QPushButton("Create Gameplay Defaults")
        add = QPushButton("+ Binding")
        remove = QPushButton("Delete Binding")
        controls.addWidget(preset)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        root.addLayout(controls)
        self.table = QTableWidget(0, len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(list(self.HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        self.audit_label = QLabel("No bindings")
        self.audit_label.setWordWrap(True)
        self.audit_label.setStyleSheet("background:#0a121a; color:#9fb7c8; border:1px solid #1b3040; padding:6px;")
        root.addWidget(self.audit_label)
        preset.clicked.connect(self.create_gameplay_defaults)
        add.clicked.connect(self.add_binding)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self._changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        contexts = {}
        for context in values.get("contexts") or ():
            if isinstance(context, str):
                contexts[context] = 0
            elif isinstance(context, dict):
                contexts[str(context.get("id") or context.get("name") or "Gameplay")] = int(context.get("priority", 0))
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for action_name, raw in dict(values.get("actions") or {}).items():
            action = dict(raw) if isinstance(raw, dict) else {}
            for binding in action.get("bindings") or ():
                binding = dict(binding) if isinstance(binding, dict) else {}
                context = str(binding.get("context") or "Gameplay")
                self._append_binding({
                    "context": context, "priority": contexts.get(context, 0), "action": action_name,
                    "value_type": action.get("value_type", "button"), "device": binding.get("device", "keyboard_mouse"),
                    "key": binding.get("key", ""), "modifiers": binding.get("modifiers", []),
                    "scale": binding.get("scale", 1.0), "consume": binding.get("consume", True),
                })
        self.table.blockSignals(False)
        self._refresh_audit()

    def settings(self) -> dict[str, Any]:
        contexts: dict[str, dict[str, Any]] = {}
        actions: dict[str, dict[str, Any]] = {}
        for row in range(self.table.rowCount()):
            context = _table_text(self.table, row, 0) or "Gameplay"
            contexts[context] = {"id": context, "priority": int(_table_float(self.table, row, 1)), "enabled": True}
            action_name = _table_text(self.table, row, 2) or "Action"
            action = actions.setdefault(action_name, {"value_type": _table_text(self.table, row, 3) or "button", "bindings": []})
            action["bindings"].append({
                "context": context, "device": _table_text(self.table, row, 4) or "keyboard_mouse",
                "key": _table_text(self.table, row, 5),
                "modifiers": [item.strip() for item in _table_text(self.table, row, 6).split("+") if item.strip()],
                "scale": _table_float(self.table, row, 7), "consume": _table_bool(self.table, row, 8),
            })
        return {"contexts": list(contexts.values()), "actions": actions}

    def create_gameplay_defaults(self) -> None:
        defaults = (
            ("Gameplay", 0, "MoveForward", "axis1d", "keyboard_mouse", "W", "", 1, True),
            ("Gameplay", 0, "MoveForward", "axis1d", "keyboard_mouse", "S", "", -1, True),
            ("Gameplay", 0, "MoveRight", "axis1d", "keyboard_mouse", "D", "", 1, True),
            ("Gameplay", 0, "MoveRight", "axis1d", "keyboard_mouse", "A", "", -1, True),
            ("Gameplay", 0, "Jump", "button", "keyboard_mouse", "Space", "", 1, True),
            ("Gameplay", 0, "LookX", "axis1d", "mouse", "MouseX", "", 1, False),
            ("Gameplay", 0, "LookY", "axis1d", "mouse", "MouseY", "", -1, False),
        )
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for values in defaults:
            self._append_binding(dict(zip(("context", "priority", "action", "value_type", "device", "key", "modifiers", "scale", "consume"), values)))
        self.table.blockSignals(False)
        self._changed()

    def add_binding(self) -> None:
        self.table.blockSignals(True)
        self._append_binding({"context": "Gameplay", "priority": 0, "action": "Action", "value_type": "button", "device": "keyboard_mouse", "key": "", "scale": 1, "consume": True})
        self.table.blockSignals(False)
        self._changed()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def validation_issues(self) -> list[str]:
        report = audit_input_map(self.settings())
        return [item.message for item in report.diagnostics if item.severity == "error"]

    def _append_binding(self, binding: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        modifiers = binding.get("modifiers", "")
        if isinstance(modifiers, (list, tuple)):
            modifiers = "+".join(str(item) for item in modifiers)
        values = (
            binding.get("context", "Gameplay"), binding.get("priority", 0), binding.get("action", "Action"),
            binding.get("value_type", "button"), binding.get("device", "keyboard_mouse"), binding.get("key", ""),
            modifiers, binding.get("scale", 1), str(bool(binding.get("consume", True))).lower(),
        )
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _changed(self, *_args) -> None:
        self._refresh_audit()
        self.changed.emit()

    def _refresh_audit(self) -> None:
        report = audit_input_map(self.settings())
        errors = sum(item.severity == "error" for item in report.diagnostics)
        warnings = sum(item.severity == "warning" for item in report.diagnostics)
        details = "\n".join(f"[{item.severity.upper()}] {item.message}" for item in report.diagnostics[:5])
        self.audit_label.setText(f"{'READY' if report.valid else 'CONFLICTS'} • {errors} errors • {warnings} warnings" + (f"\n{details}" if details else ""))


class FxBudgetProfilerWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.quality = QComboBox(self)
        self.quality.addItem("Automatic", "auto")
        for key, profile in QUALITY_PROFILES.items():
            self.quality.addItem(profile.name, key)
        form.addRow("Scalability Target", self.quality)
        root.addLayout(form)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#0a121a; color:#9fb7c8; border:1px solid #1b3040; padding:10px;")
        root.addWidget(self.summary, 1)
        self._values: dict[str, Any] = {}
        self.quality.currentIndexChanged.connect(self._quality_changed)

    def load_effect(self, values: dict[str, Any]) -> None:
        self._values = dict(values)
        quality = str(values.get("scalability") or "auto")
        index = self.quality.findData(quality)
        self.quality.blockSignals(True)
        self.quality.setCurrentIndex(max(0, index))
        self.quality.blockSignals(False)
        self._refresh()

    def scalability(self) -> str:
        return str(self.quality.currentData() or "auto")

    def _quality_changed(self, *_args) -> None:
        self._values["scalability"] = self.scalability()
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        emitters = list(self._values.get("emitters") or ())
        profile_key = self.scalability()
        profile = QUALITY_PROFILES.get(profile_key, QUALITY_PROFILES["high"])
        estimate = estimate_effect_cost(self._values, quality=profile_key if profile_key != "auto" else "high")
        status = estimate.status.replace("_", " ").upper()
        module_applications = sum(
            max(0.0, float(emitter.get("spawn_rate") or 0.0))
            * max(1, len(emitter.get("modules") or ()))
            for emitter in emitters
        )
        recommendations = "\n".join(f"• {value}" for value in estimate.recommendations) or "No automatic optimization warnings."
        self.summary.setText(
            f"AUTHORED COST ESTIMATE • {status}\n\n"
            f"{len(emitters)} emitters • {estimate.estimated_live_particles:,} estimated live particles of {profile.max_particles:,}\n"
            f"{estimate.alu_operations_per_second:,} ALU ops/s • {estimate.texture_reads_per_second:,} texture reads/s • {estimate.estimated_memory_bytes / 1_048_576:.2f} MiB particle memory\n"
            f"{module_applications:,.0f} estimated module applications/second\n"
            f"{estimate.cpu_event_emitters} CPU event/data writers • {profile.target_frame_ms:g} ms FX target\n"
            f"Spawn scale {profile.spawn_scale:g}× • render scale {profile.render_scale:g}× • update stride {profile.update_stride}\n\n"
            f"{recommendations}\n\n"
            "Measured GPU/CPU timings appear here when a live play session supplies profiler samples."
        )


class BuildProfileEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.platform = QComboBox(self)
        self.platform.addItems(list(SUPPORTED_BUILD_PLATFORMS))
        self.configuration = QComboBox(self)
        self.configuration.addItems(list(SUPPORTED_BUILD_CONFIGURATIONS))
        self.quality = QComboBox(self)
        self.quality.addItems(["low", "medium", "high", "cinematic"])
        self.entry_level = QLineEdit(self)
        self.entry_level.setPlaceholderText("Level asset ID")
        self.included_levels = QLineEdit(self)
        self.included_levels.setPlaceholderText("Additional level asset IDs, comma separated")
        self.output_directory = QLineEdit(self)
        self.incremental = QCheckBox("Reuse unchanged cooked assets", self)
        self.debug_symbols = QCheckBox("Include crash symbols", self)
        form.addRow("Platform", self.platform)
        form.addRow("Configuration", self.configuration)
        form.addRow("Quality", self.quality)
        form.addRow("Entry Level", self.entry_level)
        form.addRow("Included Levels", self.included_levels)
        form.addRow("Output Directory", self.output_directory)
        form.addRow("", self.incremental)
        form.addRow("", self.debug_symbols)
        root.addLayout(form)
        self.plan_button = QPushButton("Validate Package Plan")
        root.addWidget(self.plan_button)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#0a121a; color:#9fb7c8; border:1px solid #1b3040; padding:10px;")
        root.addWidget(self.summary, 1)
        for control in (self.platform, self.configuration, self.quality):
            control.currentTextChanged.connect(self._changed)
        for control in (self.entry_level, self.included_levels, self.output_directory):
            control.editingFinished.connect(self._changed)
        self.incremental.toggled.connect(self._changed)
        self.debug_symbols.toggled.connect(self._changed)
        self.plan_button.clicked.connect(self._refresh_plan)

    def load_settings(self, values: dict[str, Any]) -> None:
        controls = (self.platform, self.configuration, self.quality, self.entry_level, self.included_levels, self.output_directory, self.incremental, self.debug_symbols)
        for control in controls:
            control.blockSignals(True)
        self.platform.setCurrentText(str(values.get("platform") or "windows"))
        self.configuration.setCurrentText(str(values.get("configuration") or "development"))
        self.quality.setCurrentText(str(values.get("quality_profile") or "high"))
        self.entry_level.setText(str(values.get("entry_level") or ""))
        self.included_levels.setText(", ".join(str(item) for item in values.get("included_levels") or ()))
        self.output_directory.setText(str(values.get("output_directory") or "Build"))
        self.incremental.setChecked(bool(values.get("incremental", True)))
        self.debug_symbols.setChecked(bool(values.get("include_debug_symbols", True)))
        for control in controls:
            control.blockSignals(False)
        self._refresh_plan()

    def settings(self) -> dict[str, Any]:
        return {
            "platform": self.platform.currentText(), "configuration": self.configuration.currentText(),
            "quality_profile": self.quality.currentText(), "entry_level": self.entry_level.text().strip(),
            "included_levels": [item.strip() for item in self.included_levels.text().split(",") if item.strip()],
            "output_directory": self.output_directory.text().strip() or "Build",
            "incremental": self.incremental.isChecked(), "include_debug_symbols": self.debug_symbols.isChecked(),
        }

    def validation_issues(self) -> list[str]:
        plan = plan_build_profile(self.database, self.settings())
        return [item.message for item in plan.diagnostics if item.severity == "error"]

    def _changed(self, *_args) -> None:
        self._refresh_plan()
        self.changed.emit()

    def _refresh_plan(self) -> None:
        plan = plan_build_profile(self.database, self.settings())
        details = "\n".join(f"[{item.severity.upper()}] {item.message}" for item in plan.diagnostics)
        self.summary.setText(
            f"{'READY TO PACKAGE' if plan.ready else 'PACKAGE BLOCKED'} • {len(plan.asset_ids)} dependency-closed assets\n"
            f"{plan.platform} / {plan.configuration} / {plan.quality_profile} • {plan.output_directory}"
            + (f"\n\n{details}" if details else "")
        )


class SkinWeightsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._influences: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.max_influences = QSpinBox(self)
        self.max_influences.setRange(1, 16)
        self.max_influences.setValue(4)
        self.prune_threshold = QDoubleSpinBox(self)
        self.prune_threshold.setRange(0.0, 1.0)
        self.prune_threshold.setDecimals(6)
        self.prune_threshold.setValue(0.001)
        normalize = QPushButton("Normalize & Enforce Limit")
        add = QPushButton("+ Weight")
        remove = QPushButton("Delete Weight")
        controls.addWidget(QLabel("Max Influences"))
        controls.addWidget(self.max_influences)
        controls.addWidget(QLabel("Prune Below"))
        controls.addWidget(self.prune_threshold)
        controls.addWidget(normalize)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        root.addLayout(controls)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Vertex", "Influence", "Weight"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        self.summary = QLabel("No vertex weights")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#0a121a; color:#9fb7c8; border:1px solid #1b3040; padding:6px;")
        root.addWidget(self.summary)
        normalize.clicked.connect(self.normalize_and_prune)
        add.clicked.connect(self.add_weight)
        remove.clicked.connect(self.delete_selected)
        self.max_influences.valueChanged.connect(self._changed)
        self.prune_threshold.valueChanged.connect(self._changed)
        self.table.itemChanged.connect(self._changed)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._influences = [dict(item) for item in values.get("influences") or () if isinstance(item, dict)]
        self.max_influences.blockSignals(True)
        self.max_influences.setValue(int(values.get("max_influences", 4)))
        self.max_influences.blockSignals(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for vertex in values.get("vertex_weights") or ():
            if not isinstance(vertex, dict):
                continue
            index = int(vertex.get("vertex_index", 0))
            for influence, weight in dict(vertex.get("weights") or {}).items():
                self._append_weight(index, str(influence), float(weight))
        self.table.blockSignals(False)
        self._refresh()

    def settings(self) -> dict[str, Any]:
        by_vertex: dict[int, dict[str, float]] = {}
        influence_names = {str(item.get("name") or "") for item in self._influences}
        for row in range(self.table.rowCount()):
            index = int(_table_float(self.table, row, 0))
            influence = _table_text(self.table, row, 1)
            if not influence:
                continue
            by_vertex.setdefault(index, {})[influence] = max(0.0, _table_float(self.table, row, 2))
            influence_names.add(influence)
        influence_by_name = {str(item.get("name") or ""): dict(item) for item in self._influences}
        influences = [influence_by_name.get(name, {"name": name}) for name in sorted(influence_names) if name]
        return {
            "influences": influences,
            "vertex_weights": [
                {"vertex_index": index, "weights": dict(sorted(weights.items()))}
                for index, weights in sorted(by_vertex.items())
            ],
            "max_influences": self.max_influences.value(), "normalize": True,
        }

    def normalize_and_prune(self) -> None:
        settings = self.settings()
        normalized = []
        for vertex in settings["vertex_weights"]:
            normalized.append({
                "vertex_index": vertex["vertex_index"],
                "weights": normalize_skin_weights(
                    vertex["weights"], max_influences=self.max_influences.value(),
                    threshold=self.prune_threshold.value(),
                ),
            })
        self.load_settings({**settings, "vertex_weights": normalized})
        self.changed.emit()

    def add_weight(self) -> None:
        self.table.blockSignals(True)
        self._append_weight(0, "Joint", 1.0)
        self.table.blockSignals(False)
        self._changed()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def validation_issues(self) -> list[str]:
        issues = []
        for vertex in self.settings()["vertex_weights"]:
            weights = vertex["weights"]
            if len(weights) > self.max_influences.value():
                issues.append(f"Vertex {vertex['vertex_index']} exceeds {self.max_influences.value()} influences.")
            if weights and abs(sum(weights.values()) - 1.0) > 1.0e-4:
                issues.append(f"Vertex {vertex['vertex_index']} weights sum to {sum(weights.values()):.6g}, not 1.")
            if any(value < 0.0 for value in weights.values()):
                issues.append(f"Vertex {vertex['vertex_index']} contains a negative weight.")
        return issues

    def _append_weight(self, vertex: int, influence: str, weight: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(vertex)))
        self.table.setItem(row, 1, QTableWidgetItem(influence))
        weight_item = QTableWidgetItem(f"{weight:.8g}")
        intensity = max(0.0, min(1.0, weight))
        weight_item.setBackground(QColor.fromRgbF(0.08 + intensity * 0.75, 0.16 + intensity * 0.25, 0.28 - intensity * 0.18))
        self.table.setItem(row, 2, weight_item)

    def _changed(self, *_args) -> None:
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        settings = self.settings()
        vertices = settings["vertex_weights"]
        influences = {name for vertex in vertices for name in vertex["weights"]}
        invalid = len(self.validation_issues())
        self.summary.setText(
            f"{len(vertices):,} weighted vertices • {len(influences)} influences • "
            f"{invalid} issue{'s' if invalid != 1 else ''}\n"
            "Portable TC skin data remains canonical for USD Skel, FBX, glTF, Unreal, Unity, Blender, Maya, and Houdini transfer."
        )


class CurveCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.keys: list[dict[str, float]] = []
        self.setMinimumHeight(180)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#071018"))
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#173247"), 1))
        for division in range(1, 10):
            x = self.width() * division / 10.0
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for division in range(1, 4):
            y = self.height() * division / 4.0
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        if not self.keys:
            painter.setPen(QColor("#7890a1"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Add keys to author a curve")
            return
        frames = [float(item.get("frame", 0.0)) for item in self.keys]
        values = [float(item.get("value", 0.0)) for item in self.keys]
        min_frame, max_frame = min(frames), max(max(frames), min(frames) + 1.0)
        min_value, max_value = min(values), max(max(values), min(values) + 1.0e-6)
        ordered = sorted(self.keys, key=lambda value: float(value.get("frame", 0.0)))

        def project(frame: float, value: float) -> QPointF:
            x = (frame - min_frame) / (max_frame - min_frame) * max(1, self.width() - 16) + 8
            y = self.height() - ((value - min_value) / (max_value - min_value) * max(1, self.height() - 16) + 8)
            return QPointF(x, y)

        points = [project(float(item.get("frame", 0.0)), float(item.get("value", 0.0))) for item in ordered]
        painter.setPen(QPen(QColor("#66e3b4"), 2.0))
        if points:
            curve = QPainterPath(points[0])
            for index, (first, second) in enumerate(zip(ordered, ordered[1:])):
                start = points[index]
                end = points[index + 1]
                if str(first.get("interpolation") or "linear").casefold() == "bezier":
                    frame_delta = max(1.0e-6, float(second["frame"]) - float(first["frame"]))
                    control_a = project(
                        float(first["frame"]) + frame_delta / 3.0,
                        float(first["value"]) + float(first.get("out_tangent", 0.0)) * frame_delta / 3.0,
                    )
                    control_b = project(
                        float(second["frame"]) - frame_delta / 3.0,
                        float(second["value"]) - float(second.get("in_tangent", 0.0)) * frame_delta / 3.0,
                    )
                    painter.setPen(QPen(QColor("#3b6177"), 1.0, Qt.DashLine))
                    painter.drawLine(start, control_a)
                    painter.drawLine(control_b, end)
                    painter.setPen(QPen(QColor("#66e3b4"), 2.0))
                    curve.cubicTo(control_a, control_b, end)
                else:
                    curve.lineTo(end)
            painter.drawPath(curve)
        painter.setBrush(QColor("#eafcff"))
        for point in points:
            painter.drawEllipse(point, 4, 4)


class AssetCurveEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.canvas = CurveCanvas(self)
        root.addWidget(self.canvas)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Frame", "Value", "Interpolation", "In Tangent", "Out Tangent"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table)
        controls = QHBoxLayout()
        add = QPushButton("+ Key")
        remove = QPushButton("Delete Key")
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        root.addLayout(controls)
        add.clicked.connect(self.add_key)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self._sync_from_table)

    def load_keys(self, values: list[dict[str, Any]] | None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for value in values or []:
            self._append_row(
                float(value.get("frame", 0.0)), float(value.get("value", 0.0)),
                str(value.get("interpolation") or "linear"),
                float(value.get("in_tangent", 0.0)), float(value.get("out_tangent", 0.0)),
            )
        self.table.blockSignals(False)
        self._sync_from_table()

    def keys(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.canvas.keys]

    def validation_issues(self) -> list[str]:
        frames = [float(item["frame"]) for item in self.canvas.keys]
        issues = []
        if len(frames) != len(set(frames)):
            issues.append("Animation curve keys cannot share the same frame.")
        if any(not math.isfinite(float(item["value"])) for item in self.canvas.keys):
            issues.append("Animation curve values must be finite numbers.")
        return issues

    def add_key(
        self, frame: float | None = None, value: float = 0.0, interpolation: str = "linear",
        in_tangent: float = 0.0, out_tangent: float = 0.0,
    ) -> None:
        next_frame = float(frame) if frame is not None else float(self.table.rowCount() * 10)
        self.table.blockSignals(True)
        self._append_row(next_frame, float(value), interpolation, in_tangent, out_tangent)
        self.table.blockSignals(False)
        self._sync_from_table()
        self.changed.emit()

    def _append_row(
        self, frame: float, value: float, interpolation: str, in_tangent: float, out_tangent: float,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate((
            f"{frame:g}", f"{value:g}", interpolation, f"{in_tangent:g}", f"{out_tangent:g}",
        )):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        self._sync_from_table()
        if rows:
            self.changed.emit()

    def _sync_from_table(self) -> None:
        values = []
        for row in range(self.table.rowCount()):
            try:
                frame = float(self.table.item(row, 0).text())
                value = float(self.table.item(row, 1).text())
            except (AttributeError, ValueError):
                continue
            interpolation = self.table.item(row, 2).text() if self.table.item(row, 2) else "linear"
            try:
                in_tangent = float(self.table.item(row, 3).text())
                out_tangent = float(self.table.item(row, 4).text())
            except (AttributeError, ValueError):
                in_tangent = out_tangent = 0.0
            values.append({
                "frame": frame, "value": value, "interpolation": interpolation,
                "in_tangent": in_tangent, "out_tangent": out_tangent,
            })
        self.canvas.keys = sorted(values, key=lambda item: item["frame"])
        self.canvas.update()


class DopesheetEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        transport = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.frame = QSpinBox(self)
        self.frame.setRange(0, 1_000_000)
        self.frame.setPrefix("Frame ")
        self.end_frame = QSpinBox(self)
        self.end_frame.setRange(1, 1_000_000)
        self.end_frame.setValue(120)
        self.end_frame.setPrefix("End ")
        self.fps = QSpinBox(self)
        self.fps.setRange(1, 240)
        self.fps.setValue(30)
        self.fps.setSuffix(" fps")
        self.scrubber = QSlider(Qt.Horizontal, self)
        self.scrubber.setRange(0, 120)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.frame)
        transport.addWidget(self.scrubber, 1)
        transport.addWidget(self.end_frame)
        transport.addWidget(self.fps)
        root.addLayout(transport)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Track", "Frame", "Event", "Payload"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        controls = QHBoxLayout()
        add = QPushButton("+ Event")
        remove = QPushButton("Delete Event")
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch(1)
        root.addLayout(controls)
        add.clicked.connect(self.add_event)
        remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(self.changed)
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button.clicked.connect(self.stop_playback)
        self.frame.valueChanged.connect(self.scrubber.setValue)
        self.scrubber.valueChanged.connect(self.frame.setValue)
        self.end_frame.valueChanged.connect(self._set_end_frame)
        self._playback_timer = QTimer(self)
        self._playback_timer.timeout.connect(self._advance_frame)

    def load_events(self, values: list[dict[str, Any]] | None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for event in values or []:
            self._append_event(
                str(event.get("track") or "Events"), float(event.get("frame", 0.0)),
                str(event.get("event") or "Event"), str(event.get("payload") or "{}"),
            )
        self.table.blockSignals(False)
        maximum = max((int(float(item.get("frame", 0.0))) for item in values or ()), default=0)
        if maximum > self.end_frame.value():
            self.end_frame.setValue(maximum)

    def toggle_playback(self) -> None:
        if self._playback_timer.isActive():
            self._playback_timer.stop()
            self.play_button.setText("Play")
            return
        self._playback_timer.start(max(1, round(1000.0 / self.fps.value())))
        self.play_button.setText("Pause")

    def stop_playback(self) -> None:
        self._playback_timer.stop()
        self.play_button.setText("Play")
        self.frame.setValue(0)

    def _advance_frame(self) -> None:
        next_frame = self.frame.value() + 1
        self.frame.setValue(0 if next_frame > self.end_frame.value() else next_frame)

    def _set_end_frame(self, value: int) -> None:
        self.scrubber.setMaximum(max(1, int(value)))
        if self.frame.value() > value:
            self.frame.setValue(value)

    def add_event(
        self, track: str = "Events", frame: float | None = None,
        event: str = "Event", payload: str = "{}",
    ) -> None:
        self.table.blockSignals(True)
        self._append_event(track, float(self.table.rowCount() * 10 if frame is None else frame), event, payload)
        self.table.blockSignals(False)
        self.changed.emit()

    def _append_event(self, track: str, frame: float, event: str, payload: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate((track, f"{frame:g}", event, payload)):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self.changed.emit()

    def events(self) -> list[dict[str, Any]]:
        result = []
        for row in range(self.table.rowCount()):
            try:
                frame = float(self.table.item(row, 1).text())
            except (AttributeError, ValueError):
                continue
            result.append({
                "track": self.table.item(row, 0).text() if self.table.item(row, 0) else "Events",
                "frame": frame,
                "event": self.table.item(row, 2).text() if self.table.item(row, 2) else "Event",
                "payload": self.table.item(row, 3).text() if self.table.item(row, 3) else "{}",
            })
        return sorted(result, key=lambda item: (item["frame"], item["track"]))

    def validation_issues(self) -> list[str]:
        issues = []
        for event in self.events():
            try:
                import json
                json.loads(event["payload"])
            except json.JSONDecodeError:
                issues.append(f"{event['event']} at frame {event['frame']:g} has invalid JSON payload.")
        return issues


class WaveformCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.samples: list[float] = []
        self.setMinimumHeight(180)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#071018"))
        painter.setPen(QPen(QColor("#ff83b7"), 1.0))
        if not self.samples:
            painter.setPen(QColor("#7890a1"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Waveform preview unavailable for this encoded source")
            return
        center = self.height() * 0.5
        step = max(1, len(self.samples) // max(1, self.width()))
        visible = self.samples[::step][: self.width()]
        for x, sample in enumerate(visible):
            magnitude = min(center - 3, abs(float(sample)) * (center - 3))
            painter.drawLine(QPointF(x, center - magnitude), QPointF(x, center + magnitude))


class AudioWaveformEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.canvas = WaveformCanvas(self)
        root.addWidget(self.canvas)
        transport = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.position = QSlider(Qt.Horizontal, self)
        self.position.setRange(0, 0)
        self.position_label = QLabel("0.000 / 0.000 s")
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.position, 1)
        transport.addWidget(self.position_label)
        root.addLayout(transport)
        form = QFormLayout()
        self.trim_start = QDoubleSpinBox(self)
        self.trim_end = QDoubleSpinBox(self)
        for control in (self.trim_start, self.trim_end):
            control.setRange(0.0, 86400.0)
            control.setDecimals(3)
            control.setSuffix(" s")
        self.loop = QCheckBox("Loop playback", self)
        self.volume = QDoubleSpinBox(self)
        self.volume.setRange(0.0, 1.0)
        self.volume.setSingleStep(0.05)
        self.volume.setValue(0.8)
        form.addRow("Trim Start", self.trim_start)
        form.addRow("Trim End", self.trim_end)
        form.addRow("Preview Volume", self.volume)
        form.addRow("", self.loop)
        root.addLayout(form)
        self.info = QLabel("")
        root.addWidget(self.info)
        self.trim_start.valueChanged.connect(self.changed)
        self.trim_end.valueChanged.connect(self.changed)
        self.loop.toggled.connect(self.changed)
        self.volume.valueChanged.connect(self._volume_changed)
        self.volume.valueChanged.connect(self.changed)
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button.clicked.connect(self.stop_playback)
        self.position.sliderMoved.connect(self._seek)
        self._duration_ms = 0
        self._media_player = None
        self._audio_output = None
        if QMediaPlayer is not None and QAudioOutput is not None:
            self._media_player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._media_player.setAudioOutput(self._audio_output)
            self._media_player.positionChanged.connect(self._position_changed)
            self._media_player.durationChanged.connect(self._duration_changed)
            self._media_player.playbackStateChanged.connect(self._playback_state_changed)
            self._media_player.mediaStatusChanged.connect(self._media_status_changed)

    def load_audio(self, path: str | Path, settings: dict[str, Any] | None = None) -> None:
        options = dict(settings or {})
        self.canvas.samples = []
        duration = 0.0
        try:
            with wave.open(str(path), "rb") as stream:
                channels = max(1, stream.getnchannels())
                width = stream.getsampwidth()
                rate = max(1, stream.getframerate())
                frames = stream.getnframes()
                duration = frames / float(rate)
                raw = stream.readframes(frames)
            if width in {1, 2}:
                stride = max(1, frames // 12000)
                scale = 127.0 if width == 1 else 32767.0
                samples = []
                byte_stride = width * channels
                for frame in range(0, frames, stride):
                    offset = frame * byte_stride
                    if offset + width > len(raw):
                        break
                    value = int.from_bytes(raw[offset:offset + width], "little", signed=width > 1)
                    if width == 1:
                        value -= 128
                    samples.append(float(value) / scale)
                self.canvas.samples = samples
                self.info.setText(f"{channels} channel(s) • {rate} Hz • {duration:.3f} s")
        except (OSError, wave.Error):
            decoded, duration = _decode_compressed_audio(path)
            if decoded:
                self.canvas.samples = decoded
                self.info.setText(f"Decoded waveform preview • {duration:.3f} s • local FFmpeg backend")
            else:
                self.info.setText("Encoded audio remains playable at runtime; install FFmpeg for waveform decoding.")
        self.trim_start.setValue(float(options.get("trim_start", 0.0)))
        self.trim_end.setValue(float(options.get("trim_end", duration)))
        self.loop.setChecked(bool(options.get("loop", False)))
        self.volume.setValue(float(options.get("volume", 0.8)))
        self._duration_ms = max(0, round(duration * 1000.0))
        self.position.setRange(0, self._duration_ms)
        self._update_position_label(0)
        if self._media_player is not None:
            self._media_player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
            self._volume_changed()
        self.canvas.update()

    def settings(self) -> dict[str, Any]:
        return {
            "trim_start": float(self.trim_start.value()),
            "trim_end": float(self.trim_end.value()),
            "loop": bool(self.loop.isChecked()),
            "volume": float(self.volume.value()),
        }

    def validation_issues(self) -> list[str]:
        if self.trim_end.value() and self.trim_end.value() < self.trim_start.value():
            return ["Audio trim end must be greater than or equal to trim start."]
        return []

    def toggle_playback(self) -> None:
        if self._media_player is None:
            self.info.setText("Audio playback backend is unavailable; waveform and trim editing remain active.")
            return
        if self._media_player.playbackState() == QMediaPlayer.PlayingState:
            self._media_player.pause()
        else:
            start_ms = round(self.trim_start.value() * 1000.0)
            end_ms = round(self.trim_end.value() * 1000.0)
            if self._media_player.position() < start_ms or (end_ms and self._media_player.position() >= end_ms):
                self._media_player.setPosition(start_ms)
            self._media_player.play()

    def stop_playback(self) -> None:
        if self._media_player is not None:
            self._media_player.stop()
            self._media_player.setPosition(round(self.trim_start.value() * 1000.0))

    def _seek(self, position: int) -> None:
        if self._media_player is not None:
            self._media_player.setPosition(int(position))

    def _position_changed(self, position: int) -> None:
        self.position.blockSignals(True)
        self.position.setValue(int(position))
        self.position.blockSignals(False)
        self._update_position_label(position)
        end_ms = round(self.trim_end.value() * 1000.0)
        if end_ms and position >= end_ms and self._media_player is not None:
            if self.loop.isChecked():
                self._media_player.setPosition(round(self.trim_start.value() * 1000.0))
            else:
                self._media_player.pause()

    def _duration_changed(self, duration: int) -> None:
        self._duration_ms = max(self._duration_ms, int(duration))
        self.position.setMaximum(self._duration_ms)
        self._update_position_label(self.position.value())

    def _playback_state_changed(self, state) -> None:
        self.play_button.setText("Pause" if state == QMediaPlayer.PlayingState else "Play")

    def _media_status_changed(self, status) -> None:
        if self._media_player is not None and status == QMediaPlayer.EndOfMedia and self.loop.isChecked():
            self._media_player.setPosition(round(self.trim_start.value() * 1000.0))
            self._media_player.play()

    def _volume_changed(self, *_args) -> None:
        if self._audio_output is not None:
            self._audio_output.setVolume(float(self.volume.value()))

    def _update_position_label(self, position: int) -> None:
        self.position_label.setText(f"{position / 1000.0:.3f} / {self._duration_ms / 1000.0:.3f} s")


class AudioMixerEditorWidget(QWidget):
    """Compact submix console with editable routing, levels, effects, and sends."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False
        self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        heading = QLabel("Audio Mixer")
        heading.setStyleSheet("font-size:16px; font-weight:600;")
        root.addWidget(heading)
        guidance = QLabel(
            "Route sources through submix groups, balance gain in decibels, and author DSP chains and auxiliary sends. "
            "Master output is protected so a valid runtime route always remains."
        )
        guidance.setWordWrap(True)
        root.addWidget(guidance)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(("Group", "Parent", "Volume dB", "Mute", "Solo", "DSP Chain", "Sends"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.add_button = QPushButton("Add Submix")
        self.remove_button = QPushButton("Remove Selected")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.table.itemChanged.connect(self._edited)
        self.add_button.clicked.connect(self._add_group)
        self.remove_button.clicked.connect(self._remove_selected)

    def load_settings(self, values: dict[str, Any]) -> None:
        import json
        self._loading = True
        self._values = deepcopy(values)
        groups = [dict(row) for row in values.get("groups") or ()]
        self.table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            entries = (
                str(group.get("name") or group.get("id") or "Submix"),
                str(group.get("parent_id") or ""),
                f"{float(group.get('volume_db', 0.0)):g}",
                "yes" if bool(group.get("mute")) else "no",
                "yes" if bool(group.get("solo")) else "no",
                json.dumps(group.get("effects") or [], separators=(",", ":")),
                json.dumps(group.get("sends") or [], separators=(",", ":")),
            )
            for column, value in enumerate(entries):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(group.get("id") or ""))
                if str(group.get("id")) == "master" and column in {0, 1}:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self._loading = False

    def settings(self) -> dict[str, Any]:
        import json
        groups = []
        used: set[str] = set()
        for row in range(self.table.rowCount()):
            name = self._text(row, 0) or "Submix"
            stored_id = str(self.table.item(row, 0).data(Qt.UserRole) or "") if self.table.item(row, 0) else ""
            group_id = stored_id or "".join(char.lower() if char.isalnum() else "_" for char in name).strip("_") or "submix"
            candidate = group_id; suffix = 2
            while candidate in used:
                candidate, suffix = f"{group_id}_{suffix}", suffix + 1
            group_id = candidate; used.add(group_id)
            try: effects = list(json.loads(self._text(row, 5) or "[]"))
            except (json.JSONDecodeError, TypeError): effects = []
            try: sends = list(json.loads(self._text(row, 6) or "[]"))
            except (json.JSONDecodeError, TypeError): sends = []
            try: volume = float(self._text(row, 2) or 0.0)
            except ValueError: volume = 0.0
            groups.append({
                "id": group_id, "name": name, "parent_id": self._text(row, 1),
                "volume_db": max(-96.0, min(24.0, volume)),
                "mute": self._text(row, 3).casefold() in {"1", "true", "yes", "on"},
                "solo": self._text(row, 4).casefold() in {"1", "true", "yes", "on"},
                "effects": effects, "sends": sends,
            })
        return {**self._values, "groups": groups}

    def validation_issues(self) -> list[str]:
        groups = self.settings()["groups"]
        ids = {row["id"] for row in groups}
        issues = []
        if "master" not in ids:
            issues.append("Audio Mixer requires a Master group.")
        for row in groups:
            if row["parent_id"] and row["parent_id"] not in ids:
                issues.append(f"{row['name']} routes to missing parent '{row['parent_id']}'.")
        return issues

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _edited(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def _add_group(self) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        defaults = ("New Submix", "master", "0", "no", "no", "[]", "[]")
        for column, value in enumerate(defaults): self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.selectRow(row); self.changed.emit()

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        removed = False
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None and str(item.data(Qt.UserRole) or "") == "master":
                continue
            self.table.removeRow(row); removed = True
        if removed: self.changed.emit()


class AttenuationCurveCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.minimum_distance = 1.0
        self.maximum_distance = 50.0
        self.model = "inverse"
        self.setMinimumHeight(190)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#071018"))
        area = self.rect().adjusted(44, 18, -18, -32)
        painter.setPen(QPen(QColor("#284253"), 1.0))
        for step in range(5):
            y = area.top() + area.height() * step / 4.0
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        painter.setPen(QPen(QColor("#7cdcff"), 2.0))
        path = QPainterPath(); span = max(0.001, self.maximum_distance - self.minimum_distance)
        for pixel in range(max(2, area.width())):
            distance = self.maximum_distance * pixel / max(1, area.width() - 1)
            t = max(0.0, min(1.0, (distance - self.minimum_distance) / span))
            if self.model == "linear": value = 1.0 - t
            elif self.model == "logarithmic": value = (1.0 - t) ** 2.0
            else: value = 1.0 / (1.0 + 7.0 * t) if t < 1.0 else 0.0
            point = QPointF(area.left() + pixel, area.bottom() - value * area.height())
            if pixel == 0: path.moveTo(point)
            else: path.lineTo(point)
        painter.drawPath(path)
        painter.setPen(QColor("#9eb2c0"))
        painter.drawText(4, area.top() + 5, "1.0")
        painter.drawText(4, area.bottom(), "0.0")
        painter.drawText(area.left(), self.height() - 8, "Listener distance")
        painter.drawText(area.right() - 72, self.height() - 8, f"{self.maximum_distance:g} m")


class AudioAttenuationEditorWidget(QWidget):
    """Spatial audio distance model with a live attenuation preview."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False
        self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        heading = QLabel("Distance & Spatialization")
        heading.setStyleSheet("font-size:16px; font-weight:600;")
        root.addWidget(heading)
        self.canvas = AttenuationCurveCanvas(self); root.addWidget(self.canvas)
        form = QFormLayout()
        self.model = QComboBox(self); self.model.addItems(("inverse", "linear", "logarithmic", "custom"))
        self.minimum = QDoubleSpinBox(self); self.maximum = QDoubleSpinBox(self)
        for control in (self.minimum, self.maximum):
            control.setRange(0.0, 1_000_000.0); control.setDecimals(2); control.setSuffix(" m")
        self.spatial_blend = QDoubleSpinBox(self); self.spatial_blend.setRange(0.0, 1.0); self.spatial_blend.setSingleStep(0.05)
        self.doppler = QDoubleSpinBox(self); self.doppler.setRange(0.0, 10.0); self.doppler.setSingleStep(0.1)
        self.spread = QDoubleSpinBox(self); self.spread.setRange(0.0, 360.0); self.spread.setSuffix("°")
        self.occlusion = QCheckBox("Trace geometry for obstruction", self)
        self.reverb = QCheckBox("Send by distance to reverb", self)
        form.addRow("Distance Model", self.model); form.addRow("Full Volume Until", self.minimum)
        form.addRow("Silent At", self.maximum); form.addRow("2D ↔ 3D Blend", self.spatial_blend)
        form.addRow("Doppler Scale", self.doppler); form.addRow("Source Spread", self.spread)
        form.addRow("Occlusion", self.occlusion); form.addRow("Environment", self.reverb)
        root.addLayout(form)
        for control in (self.model, self.minimum, self.maximum, self.spatial_blend, self.doppler, self.spread, self.occlusion, self.reverb):
            signal = control.currentTextChanged if isinstance(control, QComboBox) else (control.toggled if isinstance(control, QCheckBox) else control.valueChanged)
            signal.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self._values = deepcopy(values)
        self.model.setCurrentText(str(values.get("distance_model") or "inverse"))
        self.minimum.setValue(float(values.get("minimum_distance", 1.0)))
        self.maximum.setValue(float(values.get("maximum_distance", 50.0)))
        self.spatial_blend.setValue(float(values.get("spatial_blend", 1.0)))
        self.doppler.setValue(float(values.get("doppler_scale", 1.0)))
        self.spread.setValue(float(values.get("spread_degrees", 0.0)))
        self.occlusion.setChecked(bool(dict(values.get("occlusion") or {}).get("enabled")))
        self.reverb.setChecked(bool(dict(values.get("reverb_send") or {}).get("enabled", True)))
        self._loading = False; self._update_canvas()

    def settings(self) -> dict[str, Any]:
        result = deepcopy(self._values)
        occlusion = dict(result.get("occlusion") or {}); occlusion["enabled"] = self.occlusion.isChecked()
        reverb = dict(result.get("reverb_send") or {}); reverb["enabled"] = self.reverb.isChecked()
        result.update({
            "distance_model": self.model.currentText(), "minimum_distance": self.minimum.value(),
            "maximum_distance": self.maximum.value(), "spatial_blend": self.spatial_blend.value(),
            "doppler_scale": self.doppler.value(), "spread_degrees": self.spread.value(),
            "occlusion": occlusion, "reverb_send": reverb,
        })
        return result

    def validation_issues(self) -> list[str]:
        if self.maximum.value() <= self.minimum.value():
            return ["Silent distance must be greater than the full-volume distance."]
        return []

    def _edited(self, *_args) -> None:
        self._update_canvas()
        if not self._loading: self.changed.emit()

    def _update_canvas(self) -> None:
        self.canvas.minimum_distance = self.minimum.value()
        self.canvas.maximum_distance = max(self.maximum.value(), 0.001)
        self.canvas.model = self.model.currentText()
        self.canvas.update()


class DataSchemaEditorWidget(QWidget):
    """Spreadsheet-like schema editor for stable typed gameplay fields."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self._loading = False; self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        title = QLabel("Typed Fields"); title.setStyleSheet("font-size:16px; font-weight:600;"); root.addWidget(title)
        help_text = QLabel("Define stable field names, runtime types, defaults, constraints, and descriptions. Existing names should be migrated instead of silently renamed.")
        help_text.setWordWrap(True); root.addWidget(help_text)
        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(("Name", "Type", "Required", "Default (JSON)", "Minimum", "Maximum", "Description"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setAlternatingRowColors(True); root.addWidget(self.table, 1)
        actions = QHBoxLayout(); add = QPushButton("Add Field"); remove = QPushButton("Remove Selected")
        actions.addWidget(add); actions.addWidget(remove); actions.addStretch(1); root.addLayout(actions)
        add.clicked.connect(self._add_field); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        import json
        self._loading = True; self._values = deepcopy(values); fields = [dict(row) for row in values.get("fields") or []]
        self.table.setRowCount(len(fields))
        for row, field in enumerate(fields):
            default = json.dumps(field.get("default"), separators=(",", ":")) if "default" in field else ""
            entries = (str(field.get("name") or ""), str(field.get("type") or "string"), "yes" if field.get("required") else "no", default, str(field.get("minimum", "")), str(field.get("maximum", "")), str(field.get("description") or ""))
            for column, value in enumerate(entries): self.table.setItem(row, column, QTableWidgetItem(value))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        import json
        fields = []
        for row in range(self.table.rowCount()):
            item = {"name": self._text(row, 0), "type": self._text(row, 1) or "string", "required": self._text(row, 2).casefold() in {"yes", "true", "1", "on"}, "description": self._text(row, 6)}
            raw_default = self._text(row, 3)
            if raw_default:
                try: item["default"] = json.loads(raw_default)
                except json.JSONDecodeError: item["default"] = raw_default
            for key, column in (("minimum", 4), ("maximum", 5)):
                raw = self._text(row, column)
                if raw:
                    try: item[key] = float(raw)
                    except ValueError: item[key] = raw
            fields.append(item)
        return {**self._values, "fields": fields}

    def validation_issues(self) -> list[str]:
        import re
        fields = self.settings()["fields"]; names = [row["name"] for row in fields]; issues = []
        if len(names) != len(set(names)): issues.append("Field names must be unique.")
        if any(not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) for name in names): issues.append("Field names must be stable identifiers.")
        unknown = sorted({row["type"] for row in fields} - set(FIELD_TYPES))
        if unknown: issues.append("Unsupported field types: " + ", ".join(unknown))
        return issues

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column); return item.text().strip() if item else ""

    def _add_field(self) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((f"field_{row + 1}", "string", "no", '""', "", "", "")): self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.selectRow(row); self.changed.emit()

    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class ComponentArchetypeEditorWidget(QWidget):
    """Hierarchy-oriented component composition editor with JSON property payloads."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self._loading = False; self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        title = QLabel("Component Hierarchy"); title.setStyleSheet("font-size:16px; font-weight:600;"); root.addWidget(title)
        hint = QLabel("Compose reusable gameplay objects from familiar engine components. Parent IDs form the scene hierarchy; properties remain typed JSON for Python and interchange parity.")
        hint.setWordWrap(True); root.addWidget(hint)
        self.table = QTableWidget(0, 6, self); self.table.setHorizontalHeaderLabels(("Name", "Type", "Stable ID", "Parent ID", "Enabled", "Properties (JSON)"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setAlternatingRowColors(True); root.addWidget(self.table, 1)
        actions = QHBoxLayout(); self.type = QComboBox(self); self.type.addItems(sorted(COMPONENT_TYPES)); add = QPushButton("Add Component"); remove = QPushButton("Remove Selected")
        actions.addWidget(self.type); actions.addWidget(add); actions.addWidget(remove); actions.addStretch(1); root.addLayout(actions)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        import json
        self._loading = True; self._values = deepcopy(values); components = [dict(row) for row in values.get("components") or []]
        self.table.setRowCount(len(components))
        for row, component in enumerate(components):
            entries = (str(component.get("name") or component.get("id") or "Component"), str(component.get("type") or "gameplay"), str(component.get("id") or ""), str(component.get("parent_id") or ""), "yes" if component.get("enabled", True) else "no", json.dumps(component.get("properties") or {}, separators=(",", ":")))
            for column, value in enumerate(entries): self.table.setItem(row, column, QTableWidgetItem(value))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        import json
        components = []
        for row in range(self.table.rowCount()):
            try: properties = dict(json.loads(self._text(row, 5) or "{}"))
            except (json.JSONDecodeError, TypeError, ValueError): properties = {}
            components.append({"name": self._text(row, 0), "type": self._text(row, 1), "id": self._text(row, 2), "parent_id": self._text(row, 3), "enabled": self._text(row, 4).casefold() in {"yes", "true", "1", "on"}, "properties": properties})
        return {**self._values, "components": components}

    def validation_issues(self) -> list[str]:
        components = self.settings()["components"]; ids = [row["id"] for row in components]; known = set(ids); issues = []
        if any(not value for value in ids) or len(ids) != len(known): issues.append("Components require unique stable IDs.")
        missing = [row["parent_id"] for row in components if row["parent_id"] and row["parent_id"] not in known]
        if missing: issues.append("Missing component parents: " + ", ".join(sorted(set(missing))))
        return issues

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column); return item.text().strip() if item else ""

    def _add(self) -> None:
        row = self.table.rowCount(); kind = self.type.currentText(); component_id = f"{kind}_{row + 1}"
        self.table.insertRow(row)
        for column, value in enumerate((kind.replace("_", " ").title(), kind, component_id, "root" if row else "", "yes", "{}")): self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.selectRow(row); self.changed.emit()

    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class GameplayClassDefinitionEditorWidget(QWidget):
    """Class, variable, function, event, and replication authoring in one deliberate surface."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self._loading = False; self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        title = QLabel("Gameplay Class Definition"); title.setStyleSheet("font-size:16px; font-weight:600;"); root.addWidget(title)
        hint = QLabel("Define familiar Actor/Pawn-style classes with inheritance, interfaces, typed variables, callable functions, events, defaults, and network policy. Stable names preserve instances and hot reload.")
        hint.setWordWrap(True); root.addWidget(hint)
        form = QFormLayout(); self.kind = QComboBox(self); self.kind.addItems(sorted(GAMEPLAY_CLASS_KINDS)); self.parent_class = QLineEdit(self); self.abstract = QCheckBox("Cannot be spawned directly", self); self.interfaces = QLineEdit(self); self.interfaces.setPlaceholderText("Damageable, Interactable")
        self.replication = QComboBox(self); self.replication.addItems(sorted(REPLICATION_MODES)); self.replicate_movement = QCheckBox("Replicate movement", self); self.network_frequency = QDoubleSpinBox(self); self.network_frequency.setRange(0.1, 240.0); self.network_frequency.setSuffix(" Hz")
        for label, control in (("Class Kind", self.kind), ("Parent Class Asset ID", self.parent_class), ("Abstract", self.abstract), ("Interfaces", self.interfaces), ("Replication", self.replication), ("Movement", self.replicate_movement), ("Network Frequency", self.network_frequency)): form.addRow(label, control)
        root.addLayout(form)
        root.addWidget(QLabel("Variables")); self.variables = QTableWidget(0, 7, self); self.variables.setHorizontalHeaderLabels(("Name", "Type", "Default", "Instance Editable", "Expose on Spawn", "Save Game", "Replication")); self.variables.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.variables, 1)
        variable_actions = QHBoxLayout(); add_variable = QPushButton("Add Variable"); remove_variable = QPushButton("Remove Variable"); variable_actions.addWidget(add_variable); variable_actions.addWidget(remove_variable); variable_actions.addStretch(1); root.addLayout(variable_actions)
        root.addWidget(QLabel("Functions")); self.functions = QTableWidget(0, 5, self); self.functions.setHorizontalHeaderLabels(("Name", "Pure", "Authority", "Inputs (JSON)", "Outputs (JSON)")); self.functions.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.functions, 1)
        function_actions = QHBoxLayout(); add_function = QPushButton("Add Function"); remove_function = QPushButton("Remove Function"); function_actions.addWidget(add_function); function_actions.addWidget(remove_function); function_actions.addStretch(1); root.addLayout(function_actions)
        self.events = QPlainTextEdit(self); self.events.setPlaceholderText("On Begin Play\nOn Interact"); self.events.setMaximumHeight(80); root.addWidget(QLabel("Events (one per line)")); root.addWidget(self.events)
        for control in (self.kind, self.replication): control.currentTextChanged.connect(self._edited)
        for control in (self.parent_class, self.interfaces): control.textChanged.connect(self._edited)
        for control in (self.abstract, self.replicate_movement): control.toggled.connect(self._edited)
        self.network_frequency.valueChanged.connect(self._edited); self.variables.itemChanged.connect(self._edited); self.functions.itemChanged.connect(self._edited); self.events.textChanged.connect(self._edited)
        add_variable.clicked.connect(self._add_variable); remove_variable.clicked.connect(lambda: self._remove_rows(self.variables)); add_function.clicked.connect(self._add_function); remove_function.clicked.connect(lambda: self._remove_rows(self.functions))

    def load_settings(self, values: dict[str, Any]) -> None:
        import json
        self._loading = True; self._values = deepcopy(values); self.kind.setCurrentText(str(values.get("class_kind") or "actor")); self.parent_class.setText(str(values.get("parent_class_id") or "")); self.abstract.setChecked(bool(values.get("abstract"))); self.interfaces.setText(", ".join(str(row) for row in values.get("interfaces") or ()))
        replication = dict(values.get("replication") or {}); self.replication.setCurrentText(str(replication.get("mode") or "local")); self.replicate_movement.setChecked(bool(replication.get("replicate_movement"))); self.network_frequency.setValue(float(replication.get("network_frequency", 30.0)))
        variable_rows = [dict(row) for row in values.get("variables") or ()]; self.variables.setRowCount(len(variable_rows))
        for row, variable in enumerate(variable_rows):
            entries = (variable.get("name", ""), variable.get("type", "string"), json.dumps(variable.get("default"), separators=(",", ":")), "yes" if variable.get("instance_editable", True) else "no", "yes" if variable.get("expose_on_spawn", False) else "no", "yes" if variable.get("save_game", False) else "no", variable.get("replication", "local"))
            for column, value in enumerate(entries): self.variables.setItem(row, column, QTableWidgetItem(str(value)))
        function_rows = [dict(row) for row in values.get("functions") or ()]; self.functions.setRowCount(len(function_rows))
        for row, function in enumerate(function_rows):
            entries = (function.get("name", ""), "yes" if function.get("pure", False) else "no", function.get("authority", "any"), json.dumps(function.get("inputs") or [], separators=(",", ":")), json.dumps(function.get("outputs") or [], separators=(",", ":")))
            for column, value in enumerate(entries): self.functions.setItem(row, column, QTableWidgetItem(str(value)))
        self.events.setPlainText("\n".join(str(row) for row in values.get("events") or ())); self._loading = False

    def settings(self) -> dict[str, Any]:
        variables = []
        for row in range(self.variables.rowCount()):
            variables.append({"name": self._text(self.variables, row, 0), "type": self._text(self.variables, row, 1), "default": _json_value(self._text(self.variables, row, 2)), "instance_editable": self._yes(self.variables, row, 3), "expose_on_spawn": self._yes(self.variables, row, 4), "save_game": self._yes(self.variables, row, 5), "replication": self._text(self.variables, row, 6) or "local"})
        functions = []
        for row in range(self.functions.rowCount()):
            inputs = _json_value(self._text(self.functions, row, 3)); outputs = _json_value(self._text(self.functions, row, 4))
            functions.append({"name": self._text(self.functions, row, 0), "pure": self._yes(self.functions, row, 1), "authority": self._text(self.functions, row, 2) or "any", "inputs": inputs if isinstance(inputs, list) else [], "outputs": outputs if isinstance(outputs, list) else []})
        values = deepcopy(self._values); replication = dict(values.get("replication") or {}); replication.update({"mode": self.replication.currentText(), "replicate_movement": self.replicate_movement.isChecked(), "network_frequency": self.network_frequency.value()})
        values.update({"class_kind": self.kind.currentText(), "parent_class_id": self.parent_class.text().strip(), "abstract": self.abstract.isChecked(), "interfaces": [row.strip() for row in self.interfaces.text().split(",") if row.strip()], "variables": variables, "functions": functions, "events": [row.strip() for row in self.events.toPlainText().splitlines() if row.strip()], "replication": replication}); return values

    def _add_variable(self) -> None:
        row = self.variables.rowCount(); self.variables.insertRow(row)
        for column, value in enumerate((f"Variable{row + 1}", "float", "0.0", "yes", "no", "no", "local")): self.variables.setItem(row, column, QTableWidgetItem(value))
        self.variables.selectRow(row); self.changed.emit()

    def _add_function(self) -> None:
        row = self.functions.rowCount(); self.functions.insertRow(row)
        for column, value in enumerate((f"Function{row + 1}", "no", "any", "[]", "[]")): self.functions.setItem(row, column, QTableWidgetItem(value))
        self.functions.selectRow(row); self.changed.emit()

    def _remove_rows(self, table: QTableWidget) -> None:
        rows = sorted({item.row() for item in table.selectedIndexes()}, reverse=True)
        for row in rows: table.removeRow(row)
        if rows: self.changed.emit()

    @staticmethod
    def _text(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column); return item.text().strip() if item else ""

    @classmethod
    def _yes(cls, table: QTableWidget, row: int, column: int) -> bool:
        return cls._text(table, row, column).casefold() in {"yes", "true", "1", "on"}

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class GameplayClassDebuggerWidget(QWidget):
    """Breakpoint, stepping, watches, instance selection, and compatible graph hot swap."""

    def __init__(self, project_root: str | Path, database: AssetDatabase, asset_id: str, parent=None) -> None:
        super().__init__(parent); self.service = GameplayClassService(project_root, database); self.asset_id = str(asset_id); self.manager = default_graph_debug_session_manager(); self.session = None
        root = QVBoxLayout(self); title = QLabel("Gameplay Graph Debugger"); title.setStyleSheet("font-size:16px; font-weight:600;"); root.addWidget(title)
        hint = QLabel("Editor Simulation uses an isolated copy. Runtime Session attaches to an already registered live instance. Breakpoints stop before a node; Step commits one atomic node; Apply Changes rolls back automatically when validation fails."); hint.setWordWrap(True); root.addWidget(hint)
        target = QHBoxLayout(); self.mode = QComboBox(self); self.mode.addItem("Editor Simulation", "editor_simulation"); self.mode.addItem("Runtime Session", "runtime_execution"); target.addWidget(QLabel("Mode")); target.addWidget(self.mode)
        target.addWidget(QLabel("Instance")); self.instance = QComboBox(self); self.instance.setEditable(True)
        self.entity = QComboBox(self); self.entity.setEditable(True); target.addWidget(QLabel("Entity")); target.addWidget(self.entity)
        refresh = QPushButton("Refresh Targets", self); refresh.clicked.connect(self.refresh_targets); target.addWidget(refresh)
        target.addWidget(self.instance, 1); attach = QPushButton("Attach & Run", self); attach.clicked.connect(self.attach); target.addWidget(attach); root.addLayout(target)
        debug_options = QFormLayout(); self.breakpoints = QLineEdit(self); self.breakpoints.setPlaceholderText("set_health, emit_event"); self.watches = QLineEdit(self); self.watches.setPlaceholderText("metadata.variables.Health, actors.Self.velocity, outputs.node_id"); debug_options.addRow("Breakpoints", self.breakpoints); debug_options.addRow("Watches", self.watches); root.addLayout(debug_options)
        self.nodes = QTableWidget(0, 4, self); self.nodes.setHorizontalHeaderLabels(("Break", "Node", "Operation", "Execution")); self.nodes.setMaximumHeight(170); self.nodes.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.nodes)
        controls = QHBoxLayout()
        for label, handler in (("Continue", self.continue_execution), ("Pause", self.pause), ("Step", self.step), ("Restart", self.restart), ("Apply Changes", self.hot_swap), ("Stop", self.stop)): button = QPushButton(label, self); button.clicked.connect(handler); controls.addWidget(button)
        controls.addStretch(1); root.addLayout(controls)
        self.context = QPlainTextEdit(self); self.context.setMaximumHeight(105); self.context.setPlainText('{"authority":"local","input_actions":{"Move":[0.0,0.0]},"actors":{"Self":{"velocity":[0.0,0.0,0.0]}},"metadata":{"variables":{}}}'); root.addWidget(self.context)
        self.status = QLabel("Ready"); root.addWidget(self.status)
        self.traces = QTableWidget(0, 5, self); self.traces.setHorizontalHeaderLabels(("Node", "Operation", "Time ms", "Inputs", "Output")); root.addWidget(self.traces, 1)
        self.watch_values = QTableWidget(0, 2, self); self.watch_values.setHorizontalHeaderLabels(("Watch", "Live Value")); self.watch_values.setMaximumHeight(130); root.addWidget(self.watch_values)
        self.details = QPlainTextEdit(self); self.details.setReadOnly(True); self.details.setMaximumHeight(150); root.addWidget(self.details)
        self.mode.currentIndexChanged.connect(self.refresh_targets); self.entity.currentTextChanged.connect(self._entity_changed); self.refresh_targets()

    def refresh_targets(self, *_args) -> None:
        current_instance = self.instance.currentText(); current_entity = self.entity.currentText(); runtime = self.mode.currentData() == "runtime_execution"
        sessions = [row for row in self.manager.list_sessions() if str(row.get("program_id") or "") == f"gameplay_class_{self.asset_id}"]
        self.instance.blockSignals(True); self.instance.clear()
        if not runtime: self.instance.addItem("EditorPreview")
        for row in sessions:
            if not runtime or row.get("execution_mode") == "runtime_execution": self.instance.addItem(str(row.get("instance_id") or ""), str(row.get("session_id") or ""))
        if current_instance: self.instance.setCurrentText(current_instance)
        self.instance.blockSignals(False)
        entities: list[str] = []
        try: entities.extend(str(value) for value in dict(json.loads(self.context.toPlainText() or "{}").get("actors") or {}))
        except (ValueError, TypeError): pass
        for row in sessions: entities.extend(str(value) for value in dict(dict(row.get("runtime_state") or {}).get("actors") or {}))
        self.entity.blockSignals(True); self.entity.clear(); self.entity.addItems(list(dict.fromkeys(entities or ["Self"]))); self.entity.setCurrentText(current_entity or "Self"); self.entity.blockSignals(False)

    def attach(self) -> dict[str, Any]:
        import json
        try:
            context = json.loads(self.context.toPlainText() or "{}")
            instance_id = self.instance.currentText().strip() or "EditorPreview"
            existing = next((row for row in self.manager.list_sessions() if row.get("program_id") == f"gameplay_class_{self.asset_id}" and row.get("instance_id") == instance_id), None)
            execution_mode = str(self.mode.currentData() or "editor_simulation")
            if execution_mode == "runtime_execution" and not existing:
                raise RuntimeError("No live runtime session is registered for this instance. Start Play or select Editor Simulation.")
            if existing:
                self.session = self.manager.session(str(existing["session_id"]))
                self._populate_nodes(self.session.manifest)
            else:
                session_id = f"editor:{self.asset_id}:{instance_id}"
                manifest = self.service.debug_manifest(self.asset_id); self._populate_nodes(manifest)
                self.session = self.manager.attach(session_id, instance_id, manifest, self.service.debug_context(self.asset_id, context), execution_mode=execution_mode, selected_entity_id=self.entity.currentText())
            self.session.set_breakpoints(self._breakpoint_ids()); self.session.set_watches(self._csv(self.watches.text()))
            if self.entity.currentText(): self.session.select_entity(self.entity.currentText())
            result = (self.session.snapshot() if existing else self.session.start()).to_dict()
        except Exception as exc:
            result = {"status": "failed", "error": {"message": str(exc)}, "traces": []}
        self._render(result); return result

    def run_preview(self) -> dict[str, Any]:
        return self.attach()

    def continue_execution(self) -> dict[str, Any]:
        return self._command("continue_execution")

    def pause(self) -> dict[str, Any]:
        return self._command("pause")

    def step(self) -> dict[str, Any]:
        return self._command("step")

    def restart(self) -> dict[str, Any]:
        return self._command("restart")

    def stop(self) -> dict[str, Any]:
        return self._command("stop")

    def hot_swap(self) -> dict[str, Any]:
        if self.session is None: return self.attach()
        try:
            manifest = self.service.debug_manifest(self.asset_id); result = self.session.hot_swap(manifest).to_dict(); self._populate_nodes(manifest)
        except Exception as exc:
            result = self.session.reject_hot_swap(str(exc)).to_dict()
        self._render(result); return result

    def _command(self, name: str) -> dict[str, Any]:
        if self.session is None: return self.attach()
        try:
            self.session.set_breakpoints(self._breakpoint_ids()); self.session.set_watches(self._csv(self.watches.text()))
            result = getattr(self.session, name)().to_dict()
        except Exception as exc: result = {"status": "failed", "error": {"message": str(exc)}, "traces": []}
        self._render(result); return result

    def _render(self, result: dict[str, Any]) -> None:
        import json
        traces = list(result.get("traces") or ()); self.traces.setRowCount(len(traces))
        for row, trace in enumerate(traces):
            values = (trace.get("node_id", ""), trace.get("operation", ""), f"{float(trace.get('elapsed_ms', 0.0)):.3f}", ", ".join(trace.get("input_names") or ()), trace.get("output_summary", ""))
            for column, value in enumerate(values): self.traces.setItem(row, column, QTableWidgetItem(str(value)))
        status = str(result.get("status") or "failed").upper(); reason = str(result.get("pause_reason") or ""); next_node = str(result.get("next_node_id") or "")
        mode = "RUNTIME" if result.get("execution_mode") == "runtime_execution" else "SIMULATION"
        hot_reload = dict(result.get("hot_reload") or {}); reload_status = " - HOT RELOAD ROLLED BACK" if hot_reload.get("rolled_back") else (" - HOT RELOAD APPLIED" if hot_reload.get("applied") else "")
        self.status.setText(f"{mode} - {status} - {len(traces)}/{int(result.get('instruction_count', len(traces)))} nodes" + (f" - {reason}" if reason else "") + (f" - next: {next_node}" if next_node else "") + reload_status)
        watches = dict(result.get("watches") or {}); self.watch_values.setRowCount(len(watches))
        for row, (path, value) in enumerate(watches.items()): self.watch_values.setItem(row, 0, QTableWidgetItem(str(path))); self.watch_values.setItem(row, 1, QTableWidgetItem(_render_json(value)))
        completed = {str(trace.get("node_id") or "") for trace in traces}; current = str(result.get("current_node_id") or "")
        for row in range(self.nodes.rowCount()):
            node_id = _table_text(self.nodes, row, 1); state = "NEXT" if node_id == next_node else ("CURRENT" if node_id == current else ("DONE" if node_id in completed else "WAITING")); self.nodes.setItem(row, 3, QTableWidgetItem(state))
        details = result.get("error") or {"selected_entity_id": result.get("selected_entity_id") or "", "hot_reload": hot_reload, "outputs": result.get("outputs") or {}, "runtime_state": result.get("runtime_state") or {}}
        self.details.setPlainText(json.dumps(details, indent=2, default=str))

    def _populate_nodes(self, manifest: dict[str, Any]) -> None:
        selected = set(self._csv(self.breakpoints.text()))
        if self.session is not None: selected.update(self.session.breakpoints)
        self.nodes.setRowCount(0)
        for node_id in manifest.get("execution_order") or ():
            node = next((dict(row) for row in manifest.get("nodes") or () if str(dict(row).get("node_id") or "") == str(node_id)), {})
            row = self.nodes.rowCount(); self.nodes.insertRow(row); check = QTableWidgetItem(""); check.setFlags(check.flags() | Qt.ItemIsUserCheckable); check.setCheckState(Qt.Checked if str(node_id) in selected else Qt.Unchecked); self.nodes.setItem(row, 0, check)
            for column, value in enumerate((node_id, node.get("operation", ""), "WAITING"), start=1): self.nodes.setItem(row, column, QTableWidgetItem(str(value)))

    def _breakpoint_ids(self) -> list[str]:
        values = self._csv(self.breakpoints.text())
        values.extend(_table_text(self.nodes, row, 1) for row in range(self.nodes.rowCount()) if self.nodes.item(row, 0) and self.nodes.item(row, 0).checkState() == Qt.Checked)
        return list(dict.fromkeys(value for value in values if value))

    def _entity_changed(self, entity_id: str) -> None:
        if self.session is None or not entity_id: return
        try: self._render(self.session.select_entity(entity_id).to_dict())
        except KeyError: pass

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [row.strip() for row in str(value).split(",") if row.strip()]


class ProjectSettingsEditorWidget(QWidget):
    """Guided project defaults instead of a wall of nested JSON."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self._loading = False; self._values: dict[str, Any] = {}
        root = QVBoxLayout(self)
        title = QLabel("Project Settings"); title.setStyleSheet("font-size:16px; font-weight:600;"); root.addWidget(title)
        hint = QLabel("Set the defaults used by Play, packaged builds, and new levels. Asset fields accept stable asset IDs and are validated before cooking.")
        hint.setWordWrap(True); root.addWidget(hint)
        form = QFormLayout(); self.display_name = QLineEdit(self); self.company = QLineEdit(self); self.version = QLineEdit(self)
        self.default_level = QLineEdit(self); self.ruleset = QLineEdit(self); self.character = QLineEdit(self); self.input_map = QLineEdit(self)
        self.quality = QComboBox(self); self.quality.addItems(("low", "medium", "high", "ultra"))
        self.frame_limit = QSpinBox(self); self.frame_limit.setRange(0, 1000); self.frame_limit.setSpecialValueText("Unlimited")
        self.hdr = QCheckBox("Enable HDR output when supported", self)
        self.fixed_step = QDoubleSpinBox(self); self.fixed_step.setRange(0.001, 0.1); self.fixed_step.setDecimals(6); self.fixed_step.setSuffix(" s")
        self.mixer = QLineEdit(self); self.master_volume = QDoubleSpinBox(self); self.master_volume.setRange(0.0, 1.0); self.master_volume.setSingleStep(0.05)
        self.build_profile = QLineEdit(self)
        for label, control in (("Game Name", self.display_name), ("Company", self.company), ("Version", self.version), ("Default Level", self.default_level), ("Ruleset", self.ruleset), ("Default Character", self.character), ("Input Map", self.input_map), ("Quality", self.quality), ("Frame Limit", self.frame_limit), ("HDR", self.hdr), ("Physics Fixed Step", self.fixed_step), ("Audio Mixer", self.mixer), ("Master Volume", self.master_volume), ("Build Profile", self.build_profile)): form.addRow(label, control)
        root.addLayout(form); root.addStretch(1)
        for control in (self.display_name, self.company, self.version, self.default_level, self.ruleset, self.character, self.input_map, self.mixer, self.build_profile): control.textChanged.connect(self._edited)
        self.quality.currentTextChanged.connect(self._edited); self.frame_limit.valueChanged.connect(self._edited); self.hdr.toggled.connect(self._edited)
        self.fixed_step.valueChanged.connect(self._edited); self.master_volume.valueChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self._values = deepcopy(values)
        project = dict(values.get("project") or {}); startup = dict(values.get("startup") or {}); gameplay = dict(values.get("gameplay") or {})
        rendering = dict(values.get("rendering") or {}); physics = dict(values.get("physics") or {}); audio = dict(values.get("audio") or {}); build = dict(values.get("build") or {})
        self.display_name.setText(str(project.get("display_name") or "Game")); self.company.setText(str(project.get("company") or "")); self.version.setText(str(project.get("version") or "0.1.0"))
        self.default_level.setText(str(startup.get("default_level_asset_id") or "")); self.ruleset.setText(str(gameplay.get("ruleset_asset_id") or "")); self.character.setText(str(gameplay.get("default_character_asset_id") or "")); self.input_map.setText(str(gameplay.get("input_map_asset_id") or ""))
        self.quality.setCurrentText(str(rendering.get("quality_profile") or "high")); self.frame_limit.setValue(int(rendering.get("frame_rate_limit") or 0)); self.hdr.setChecked(bool(rendering.get("hdr", True)))
        self.fixed_step.setValue(float(physics.get("fixed_time_step", 0.0166667))); self.mixer.setText(str(audio.get("mixer_asset_id") or "")); self.master_volume.setValue(float(audio.get("master_volume", 1.0))); self.build_profile.setText(str(build.get("default_build_profile_asset_id") or ""))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        values = deepcopy(self._values)
        project = dict(values.get("project") or {}); project.update({"display_name": self.display_name.text().strip(), "company": self.company.text().strip(), "version": self.version.text().strip()})
        startup = dict(values.get("startup") or {}); startup["default_level_asset_id"] = self.default_level.text().strip()
        gameplay = dict(values.get("gameplay") or {}); gameplay.update({"ruleset_asset_id": self.ruleset.text().strip(), "default_character_asset_id": self.character.text().strip(), "input_map_asset_id": self.input_map.text().strip()})
        rendering = dict(values.get("rendering") or {}); rendering.update({"quality_profile": self.quality.currentText(), "frame_rate_limit": self.frame_limit.value(), "hdr": self.hdr.isChecked()})
        physics = dict(values.get("physics") or {}); physics["fixed_time_step"] = self.fixed_step.value()
        audio = dict(values.get("audio") or {}); audio.update({"mixer_asset_id": self.mixer.text().strip(), "master_volume": self.master_volume.value()})
        build = dict(values.get("build") or {}); build["default_build_profile_asset_id"] = self.build_profile.text().strip()
        values.update({"project": project, "startup": startup, "gameplay": gameplay, "rendering": rendering, "physics": physics, "audio": audio, "build": build}); return values

    def validation_issues(self) -> list[str]:
        import re
        issues = []
        if not self.display_name.text().strip(): issues.append("Game Name is required.")
        if not re.match(r"^\d+\.\d+\.\d+(?:[-+].+)?$", self.version.text().strip()): issues.append("Version should use semantic versioning, for example 1.0.0.")
        return issues

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class EmitterStackEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False
        root = QVBoxLayout(self)
        heading = QLabel("Emitter Stack")
        heading.setStyleSheet("font-size:16px; font-weight:600;")
        root.addWidget(heading)
        guidance = QLabel("Select an emitter, choose its simulation target and renderer, then build ordered phase-aware module stacks.")
        guidance.setWordWrap(True)
        root.addWidget(guidance)
        content = QHBoxLayout()
        self.stack = QListWidget(self)
        self.stack.setDragDropMode(QAbstractItemView.InternalMove)
        content.addWidget(self.stack, 1)
        right = QVBoxLayout()
        details = QFormLayout()
        self.simulation_target = QComboBox(self); self.simulation_target.addItems(list(SIMULATION_TARGETS))
        self.capacity = QSpinBox(self); self.capacity.setRange(1, 10_000_000)
        self.spawn_rate = QDoubleSpinBox(self)
        self.spawn_rate.setRange(0.0, 10_000_000.0)
        self.spawn_rate.setDecimals(2)
        self.lifetime = QDoubleSpinBox(self); self.lifetime.setRange(0.001, 3600.0); self.lifetime.setDecimals(3)
        self.renderer = QComboBox(self); self.renderer.addItems(list(RENDERER_TYPES))
        details.addRow("Simulation", self.simulation_target)
        details.addRow("Capacity", self.capacity)
        details.addRow("Spawn Rate", self.spawn_rate)
        details.addRow("Lifetime", self.lifetime)
        details.addRow("Primary Renderer", self.renderer)
        right.addLayout(details)
        self.modules = QListWidget(self); self.modules.setDragDropMode(QAbstractItemView.InternalMove)
        right.addWidget(QLabel("Modules execute top to bottom within their phase."))
        right.addWidget(self.modules, 1)
        module_controls = QHBoxLayout()
        self.module_type = QComboBox(self)
        for name, spec in MODULE_LIBRARY.items(): self.module_type.addItem(name.replace("_", " ").title(), name)
        self.module_phase = QComboBox(self); self.module_phase.addItems(list(EFFECT_PHASES))
        add_module = QPushButton("Add Module"); remove_module = QPushButton("Remove")
        module_controls.addWidget(self.module_type, 1); module_controls.addWidget(self.module_phase, 1)
        module_controls.addWidget(add_module); module_controls.addWidget(remove_module)
        right.addLayout(module_controls)
        self.module_help = QLabel(""); self.module_help.setWordWrap(True); self.module_help.setStyleSheet("color:#91a8b8;")
        right.addWidget(self.module_help)
        content.addLayout(right, 2)
        root.addLayout(content, 1)
        controls = QHBoxLayout()
        add = QPushButton("+ Emitter")
        remove = QPushButton("Delete")
        up = QPushButton("Move Up")
        down = QPushButton("Move Down")
        for button in (add, remove, up, down):
            controls.addWidget(button)
        controls.addStretch(1)
        root.addLayout(controls)
        add.clicked.connect(self.add_emitter)
        remove.clicked.connect(self.delete_selected)
        up.clicked.connect(lambda: self.move_selected(-1))
        down.clicked.connect(lambda: self.move_selected(1))
        self.stack.model().rowsMoved.connect(self.changed)
        self.stack.currentRowChanged.connect(self._load_current)
        for widget in (self.simulation_target, self.capacity, self.spawn_rate, self.lifetime, self.renderer):
            signal = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged
            signal.connect(self._update_current)
        self.modules.model().rowsMoved.connect(self._modules_changed)
        self.modules.currentRowChanged.connect(self._selected_module_changed)
        self.module_type.currentIndexChanged.connect(self._module_type_changed)
        add_module.clicked.connect(self._add_module); remove_module.clicked.connect(self._remove_module)
        self._module_type_changed()

    def load_emitters(self, emitters: list[dict[str, Any]] | None) -> None:
        self._loading = True
        self.stack.clear()
        for emitter in emitters or []:
            item = QListWidgetItem(str(emitter.get("name") or "Emitter"))
            payload = dict(emitter)
            structured = []
            for index, module in enumerate(payload.get("modules") or []):
                if isinstance(module, dict): structured.append(dict(module))
                else:
                    kind = {"forces": "gravity", "render": "color_over_life"}.get(str(module), str(module))
                    phase = MODULE_LIBRARY.get(kind, (("particle_update",),))[0][0]
                    structured.append({"id": f"{payload.get('id', 'emitter')}_module_{index}", "type": kind, "phase": phase, "enabled": True, "parameters": {}, "version": 1})
            payload["modules"] = structured
            self.stack.addItem(item)
            item.setData(Qt.UserRole, payload)
        self._loading = False
        if self.stack.count():
            self.stack.setCurrentRow(0)

    def add_emitter(self, name: str = "") -> None:
        index = self.stack.count() + 1
        payload = {
            "id": f"emitter_{uuid.uuid4().hex[:10]}", "name": str(name or f"Emitter {index}"),
            "enabled": True, "simulation_target": "auto", "capacity": 1024, "spawn_rate": 25.0,
            "lifetime": 2.0, "loop": True, "persistent_ids": False,
            "modules": [
                {"id": uuid.uuid4().hex, "type": "initialize", "phase": "particle_spawn", "enabled": True, "parameters": {}, "version": 1},
                {"id": uuid.uuid4().hex, "type": "gravity", "phase": "particle_update", "enabled": True, "parameters": {}, "version": 1},
            ],
            "renderers": [{"id": uuid.uuid4().hex, "type": "sprite", "material_asset_id": "", "blend_mode": "additive"}],
        }
        item = QListWidgetItem(payload["name"])
        item.setData(Qt.UserRole, payload)
        self.stack.addItem(item)
        self.stack.setCurrentItem(item)
        self.changed.emit()

    def delete_selected(self) -> None:
        row = self.stack.currentRow()
        if row >= 0:
            self.stack.takeItem(row)
            self.changed.emit()

    def move_selected(self, offset: int) -> None:
        row = self.stack.currentRow()
        target = row + int(offset)
        if row < 0 or target < 0 or target >= self.stack.count():
            return
        item = self.stack.takeItem(row)
        self.stack.insertItem(target, item)
        self.stack.setCurrentRow(target)
        self.changed.emit()

    def emitters(self) -> list[dict[str, Any]]:
        self._store_current()
        return [dict(self.stack.item(index).data(Qt.UserRole) or {}) for index in range(self.stack.count())]

    def validation_issues(self) -> list[str]:
        issues = []
        for emitter in self.emitters():
            if float(emitter.get("spawn_rate", 0.0)) < 0.0:
                issues.append(f"{emitter.get('name') or 'Emitter'} has a negative spawn rate.")
            if not emitter.get("modules"):
                issues.append(f"{emitter.get('name') or 'Emitter'} has no modules.")
        return issues

    def _load_current(self, _row: int = -1) -> None:
        item = self.stack.currentItem()
        payload = dict(item.data(Qt.UserRole) or {}) if item is not None else {}
        self._loading = True
        self.simulation_target.setCurrentText(str(payload.get("simulation_target") or "auto"))
        self.capacity.setValue(max(1, int(payload.get("capacity") or payload.get("max_particles") or 1024)))
        self.spawn_rate.setValue(float(payload.get("spawn_rate", 0.0)))
        self.lifetime.setValue(max(0.001, float(payload.get("lifetime") or payload.get("duration") or 1.0)))
        renderers = list(payload.get("renderers") or ([payload.get("renderer")] if payload.get("renderer") else []))
        self.renderer.setCurrentText(str(dict(renderers[0]).get("type") if renderers else "sprite"))
        self.modules.clear()
        for module in payload.get("modules") or []:
            row = dict(module); widget_item = QListWidgetItem(self._module_label(row)); widget_item.setData(Qt.UserRole, row); self.modules.addItem(widget_item)
        self._loading = False

    def _update_current(self, *_args) -> None:
        if self._loading: return
        if self._store_current():
            self.changed.emit()

    def _store_current(self) -> bool:
        item = self.stack.currentItem()
        if item is None:
            return False
        payload = dict(item.data(Qt.UserRole) or {})
        payload["simulation_target"] = self.simulation_target.currentText()
        payload["capacity"] = int(self.capacity.value())
        payload["spawn_rate"] = float(self.spawn_rate.value())
        payload["lifetime"] = float(self.lifetime.value())
        payload["modules"] = [dict(self.modules.item(index).data(Qt.UserRole) or {}) for index in range(self.modules.count())]
        renderers = list(payload.get("renderers") or [{}]); primary = dict(renderers[0] if renderers else {})
        primary.setdefault("id", f"{payload.get('id', 'emitter')}_renderer"); primary["type"] = self.renderer.currentText(); renderers[0:1] = [primary]
        payload["renderers"] = renderers
        item.setData(Qt.UserRole, payload)
        return True

    def _module_label(self, module: dict[str, Any]) -> str:
        return f"{str(module.get('phase') or 'particle_update').replace('_', ' ').title()}  ·  {str(module.get('type') or 'module').replace('_', ' ').title()}"

    def _module_type_changed(self, *_args) -> None:
        kind = str(self.module_type.currentData() or "initialize"); spec = MODULE_LIBRARY.get(kind)
        if not spec: return
        allowed = list(spec[0]); self.module_phase.clear(); self.module_phase.addItems(allowed)
        self.module_help.setText(f"{spec[4]}  •  ALU {spec[1]}  •  texture reads {spec[2]}  •  {'GPU ready' if spec[3] else 'CPU only'}")

    def _add_module(self) -> None:
        kind = str(self.module_type.currentData() or "initialize")
        module = {"id": uuid.uuid4().hex, "type": kind, "phase": self.module_phase.currentText(), "enabled": True, "parameters": {}, "version": 1}
        item = QListWidgetItem(self._module_label(module)); item.setData(Qt.UserRole, module); self.modules.addItem(item); self.modules.setCurrentItem(item)
        self._modules_changed()

    def _remove_module(self) -> None:
        row = self.modules.currentRow()
        if row >= 0: self.modules.takeItem(row); self._modules_changed()

    def _modules_changed(self, *_args) -> None:
        if not self._loading and self._store_current(): self.changed.emit()

    def _selected_module_changed(self, _row: int) -> None:
        item = self.modules.currentItem()
        if item is None: return
        module = dict(item.data(Qt.UserRole) or {}); index = self.module_type.findData(str(module.get("type") or ""))
        if index >= 0: self.module_type.setCurrentIndex(index)
        phase_index = self.module_phase.findText(str(module.get("phase") or ""))
        if phase_index >= 0: self.module_phase.setCurrentIndex(phase_index)


class CollisionPreviewCanvas(QWidget):
    scaleChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.shape = "box"
        self.preview_scale = 1.0
        self._drag_y: float | None = None
        self.setMinimumHeight(190)
        self.setToolTip("Drag vertically or use the wheel to inspect collision-proxy scale.")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#071018"))
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#65e399"), 2.0))
        size = min(self.width(), self.height()) * 0.48 * self.preview_scale
        center = QPointF(self.width() * 0.5, self.height() * 0.5)
        bounds = QRectF(center.x() - size * 0.5, center.y() - size * 0.5, size, size)
        if self.shape == "sphere":
            painter.drawEllipse(bounds)
        elif self.shape == "capsule":
            painter.drawRoundedRect(bounds.adjusted(size * 0.2, 0, -size * 0.2, 0), size * 0.3, size * 0.3)
        elif self.shape in {"convex_hull", "decomposition"}:
            path = QPainterPath(QPointF(center.x(), bounds.top()))
            for point in (
                QPointF(bounds.right(), center.y() - size * 0.12),
                QPointF(center.x() + size * 0.27, bounds.bottom()),
                QPointF(bounds.left(), center.y() + size * 0.18),
            ):
                path.lineTo(point)
            path.closeSubpath()
            painter.drawPath(path)
            if self.shape == "decomposition":
                painter.drawLine(bounds.topLeft(), bounds.bottomRight())
                painter.drawLine(bounds.topRight(), bounds.bottomLeft())
        elif self.shape == "triangle_mesh":
            painter.drawRect(bounds)
            for division in range(1, 4):
                ratio = division / 4.0
                painter.drawLine(
                    QPointF(bounds.left(), bounds.top() + bounds.height() * ratio),
                    QPointF(bounds.right(), bounds.bottom() - bounds.height() * ratio),
                )
        else:
            painter.drawRect(bounds)
        painter.setPen(QColor("#8ba2b3"))
        painter.drawText(8, 18, f"{self.shape.replace('_', ' ').title()} • gizmo scale {self.preview_scale:.2f}×")

    def set_shape(self, shape: str) -> None:
        self.shape = str(shape or "box")
        self.update()

    def wheelEvent(self, event) -> None:
        self.preview_scale = min(1.8, max(0.35, self.preview_scale + event.angleDelta().y() / 1200.0))
        self.scaleChanged.emit(self.preview_scale)
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        self._drag_y = float(event.position().y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_y is None:
            return
        delta = self._drag_y - float(event.position().y())
        self._drag_y = float(event.position().y())
        self.preview_scale = min(1.8, max(0.35, self.preview_scale + delta / 240.0))
        self.scaleChanged.emit(self.preview_scale)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_y = None
        event.accept()


class CollisionGenerationEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.preview = CollisionPreviewCanvas(self)
        root.addWidget(self.preview)
        form = QFormLayout()
        self.shape = QComboBox(self)
        self.shape.addItems(["box", "sphere", "capsule", "convex_hull", "decomposition", "triangle_mesh"])
        self.complexity = QComboBox(self)
        self.complexity.addItems(["simple", "simple_and_complex", "complex_as_simple"])
        self.margin = QDoubleSpinBox(self)
        self.margin.setRange(0.0, 100.0)
        self.margin.setValue(0.02)
        self.max_hulls = QSpinBox(self)
        self.max_hulls.setRange(1, 128)
        self.max_hulls.setValue(8)
        form.addRow("Generated Shape", self.shape)
        form.addRow("Collision Complexity", self.complexity)
        form.addRow("Margin", self.margin)
        form.addRow("Maximum Hulls", self.max_hulls)
        root.addLayout(form)
        self.status = QLabel("Collision has not been generated for this editor session.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        generate = QPushButton("Generate Collision Preview")
        generate.setObjectName("primaryAction")
        root.addWidget(generate)
        root.addStretch(1)
        generate.clicked.connect(self.generate)
        self.shape.currentTextChanged.connect(self.changed)
        self.shape.currentTextChanged.connect(self.preview.set_shape)
        self.complexity.currentTextChanged.connect(self.changed)
        self.margin.valueChanged.connect(self.changed)
        self.max_hulls.valueChanged.connect(self.changed)
        self.preview.scaleChanged.connect(self.changed)

    def load_settings(self, values: dict[str, Any] | None) -> None:
        settings = dict(values or {})
        self.shape.setCurrentText(str(settings.get("shape") or "box"))
        self.preview.set_shape(self.shape.currentText())
        self.complexity.setCurrentText(str(settings.get("complexity") or "simple"))
        self.margin.setValue(float(settings.get("margin", 0.02)))
        self.max_hulls.setValue(int(settings.get("max_hulls", 8)))

    def generate(self) -> None:
        label = self.shape.currentText().replace("_", " ").title()
        self.status.setText(
            f"{label} preview ready • margin {self.margin.value():g} • maximum {self.max_hulls.value()} hull(s). Save to invalidate the mesh cook."
        )
        self.changed.emit()

    def settings(self) -> dict[str, Any]:
        return {
            "shape": self.shape.currentText(), "complexity": self.complexity.currentText(),
            "margin": float(self.margin.value()), "max_hulls": int(self.max_hulls.value()),
        }

    def validation_issues(self) -> list[str]:
        if self.shape.currentText() == "decomposition" and self.max_hulls.value() < 2:
            return ["Convex decomposition requires at least two hulls."]
        return []


class BlendSpaceEditorWidget(QWidget):
    """Focused Blend Space authoring with live weights and actionable validation."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False
        self._values: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        title = QLabel("Blend Space Preview")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel("Move the preview inputs to inspect normalized runtime sample weights. Samples remain editable in the table.")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        controls = QHBoxLayout()
        self.x_label = QLabel("X")
        self.x = QDoubleSpinBox(); self.x.setDecimals(3); self.x.setKeyboardTracking(False)
        self.y_label = QLabel("Y")
        self.y = QDoubleSpinBox(); self.y.setDecimals(3); self.y.setKeyboardTracking(False)
        controls.addWidget(self.x_label); controls.addWidget(self.x); controls.addWidget(self.y_label); controls.addWidget(self.y); controls.addStretch(1)
        layout.addLayout(controls)
        self.samples = QTableWidget(0, 6)
        self.samples.setHorizontalHeaderLabels(("Sample", "Animation Clip", "X", "Y", "Rate", "Mirror"))
        self.samples.setAlternatingRowColors(True)
        self.samples.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.samples, 1)
        actions = QHBoxLayout()
        add = QPushButton("Add Sample"); remove = QPushButton("Remove Selected")
        actions.addWidget(add); actions.addWidget(remove); actions.addStretch(1)
        layout.addLayout(actions)
        self.weights = QLabel("No preview weights")
        self.weights.setWordWrap(True)
        self.diagnostics = QLabel("")
        self.diagnostics.setWordWrap(True)
        layout.addWidget(self.weights); layout.addWidget(self.diagnostics)
        self.x.valueChanged.connect(self._refresh_preview); self.y.valueChanged.connect(self._refresh_preview)
        self.samples.itemChanged.connect(self._table_changed)
        add.clicked.connect(self._add_sample); remove.clicked.connect(self._remove_selected)

    def load_settings(self, values: dict[str, Any] | None) -> None:
        self._loading = True
        self._values = deepcopy(dict(values or {}))
        dimensions = 1 if int(self._values.get("dimensions", 2) or 2) == 1 else 2
        axes = list(self._values.get("axes") or [])
        for spin, label, index in ((self.x, self.x_label, 0), (self.y, self.y_label, 1)):
            axis = dict(axes[index]) if index < len(axes) else {"name": "XY"[index], "minimum": -1.0, "maximum": 1.0}
            spin.setRange(float(axis.get("minimum", -1.0)), float(axis.get("maximum", 1.0)))
            label.setText(str(axis.get("name") or "XY"[index]))
        self.y.setVisible(dimensions == 2); self.y_label.setVisible(dimensions == 2)
        preview = dict(self._values.get("preview") or {})
        self.x.setValue(float(preview.get("x", 0.0))); self.y.setValue(float(preview.get("y", 0.0)))
        rows = list(self._values.get("samples") or [])
        self.samples.setRowCount(len(rows))
        for row_index, value in enumerate(rows):
            row = dict(value); position = list(row.get("position") or [0.0, 0.0])
            columns = [row.get("id", f"sample_{row_index}"), row.get("clip_asset_id", ""), position[0] if position else 0.0, position[1] if len(position) > 1 else 0.0, row.get("rate_scale", 1.0), "Yes" if row.get("mirror") else "No"]
            for column, item in enumerate(columns): self.samples.setItem(row_index, column, QTableWidgetItem(str(item)))
        self._loading = False
        self._refresh_preview()

    def settings(self) -> dict[str, Any]:
        values = deepcopy(self._values); dimensions = 1 if int(values.get("dimensions", 2) or 2) == 1 else 2
        rows = []
        for index in range(self.samples.rowCount()):
            text = lambda column: self.samples.item(index, column).text().strip() if self.samples.item(index, column) else ""
            try: position = [float(text(2) or 0.0)] + ([float(text(3) or 0.0)] if dimensions == 2 else [])
            except ValueError: position = [0.0] * dimensions
            try: rate = float(text(4) or 1.0)
            except ValueError: rate = 1.0
            rows.append({"id": text(0) or f"sample_{index}", "clip_asset_id": text(1), "position": position, "rate_scale": rate, "mirror": text(5).casefold() in {"yes", "true", "1", "on"}, "sync_marker": ""})
        values["samples"] = rows; values["preview"] = {"x": float(self.x.value()), "y": float(self.y.value())}
        return values

    def validation_issues(self) -> list[str]:
        return [item.message for item in validate_blend_space(self.settings())]

    def _refresh_preview(self, *_args) -> None:
        if self._loading: return
        values = self.settings(); weights = evaluate_blend_space(values, x=self.x.value(), y=self.y.value())
        self.weights.setText("Weights • " + ("  ·  ".join(f"{name}: {weight:.1%}" for name, weight in weights.items()) if weights else "No samples"))
        issues = validate_blend_space(values)
        self.diagnostics.setText("Ready to cook" if not issues else "  •  ".join(f"{item.severity.title()}: {item.message}" for item in issues))

    def _table_changed(self, *_args) -> None:
        if self._loading: return
        self._refresh_preview(); self.changed.emit()

    def _add_sample(self) -> None:
        row = self.samples.rowCount(); self.samples.insertRow(row)
        for column, value in enumerate((f"sample_{row}", "", self.x.value(), self.y.value(), 1.0, "No")): self.samples.setItem(row, column, QTableWidgetItem(str(value)))
        self.changed.emit()

    def _remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.samples.selectedItems()}, reverse=True)
        for row in rows: self.samples.removeRow(row)
        if rows: self._refresh_preview(); self.changed.emit()


class MaterialParameterEditorWidget(QWidget):
    """Named runtime parameters and static permutation switches."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Default", "Group", "Static"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Parameter"); remove = QPushButton("Delete")
        controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        self.summary = QLabel("0 parameters • 0 static switches"); root.addWidget(self.summary)
        self._loading = False
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for name, raw in dict(values.get("parameters") or {}).items():
            descriptor = dict(raw) if isinstance(raw, dict) and any(key in raw for key in ("default", "type", "group", "static")) else {"default": raw}
            default = descriptor.get("default")
            kind = str(descriptor.get("type") or _value_type(default))
            self._append(str(name), kind, default, str(descriptor.get("group") or "General"), bool(descriptor.get("static", False)))
        self._loading = False; self._summary()

    def settings(self) -> dict[str, Any]:
        parameters = {}
        groups = {}
        for row in range(self.table.rowCount()):
            name = _table_text(self.table, row, 0).strip()
            if not name: continue
            group = _table_text(self.table, row, 3).strip() or "General"
            descriptor = {"type": _table_text(self.table, row, 1) or "float", "default": _json_value(_table_text(self.table, row, 2)), "group": group, "static": _table_text(self.table, row, 4).casefold() in {"true", "yes", "1", "on"}}
            parameters[name] = descriptor; groups.setdefault(group, []).append(name)
        return {"parameters": parameters, "parameter_groups": groups}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).strip() for row in range(self.table.rowCount())]
        issues = []
        if any(not name for name in names): issues.append("Every material parameter needs a name.")
        if len({name.casefold() for name in names}) != len(names): issues.append("Material parameter names must be unique.")
        return issues

    def _append(self, name: str, kind: str, default: Any, group: str, static: bool) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        values = (name, kind, _json_text(default), group, "Yes" if static else "No")
        for column, value in enumerate(values): self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _add(self) -> None:
        self._append(f"Parameter{self.table.rowCount() + 1}", "float", 0.0, "General", False); self.changed.emit()

    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self._summary(); self.changed.emit()

    def _edited(self, *_args) -> None:
        if not self._loading: self._summary(); self.changed.emit()

    def _summary(self) -> None:
        static = sum(_table_text(self.table, row, 4).casefold() in {"yes", "true", "1", "on"} for row in range(self.table.rowCount()))
        self.summary.setText(f"{self.table.rowCount()} parameter(s) • {static} static switch(es) • up to {2 ** static} permutation(s)")


class MeshGeometryEditorWidget(QWidget):
    """Import-safe geometry processing controls for static and skeletal meshes."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout()
        self.normals = QComboBox(self); self.normals.addItems(["preserve", "recompute_if_missing", "recompute"])
        self.tangents = QComboBox(self); self.tangents.addItems(["preserve", "mikktspace", "recompute"])
        self.lightmap = QCheckBox("Generate non-overlapping lightmap UVs")
        self.lightmap_channel = QSpinBox(self); self.lightmap_channel.setRange(0, 15)
        self.weld = QDoubleSpinBox(self); self.weld.setRange(0.0, 10.0); self.weld.setDecimals(6)
        self.degenerate = QCheckBox("Remove degenerate triangles")
        self.cpu_access = QCheckBox("Allow CPU access")
        self.streaming = QCheckBox("Enable geometry streaming")
        form.addRow("Normals", self.normals); form.addRow("Tangents", self.tangents)
        form.addRow("Lightmap UVs", self.lightmap); form.addRow("Lightmap Channel", self.lightmap_channel)
        form.addRow("Weld Threshold", self.weld); form.addRow("Cleanup", self.degenerate)
        form.addRow("Runtime Access", self.cpu_access); form.addRow("Streaming", self.streaming)
        root.addLayout(form); root.addStretch(1); self._loading = False
        for widget in (self.normals, self.tangents): widget.currentTextChanged.connect(self._edited)
        for widget in (self.lightmap, self.degenerate, self.cpu_access, self.streaming): widget.toggled.connect(self._edited)
        for widget in (self.lightmap_channel, self.weld): widget.valueChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        settings = dict(values.get("geometry") or values.get("geometry_settings") or {})
        self._loading = True; self.normals.setCurrentText(str(settings.get("normals") or "preserve")); self.tangents.setCurrentText(str(settings.get("tangents") or "mikktspace"))
        self.lightmap.setChecked(bool(settings.get("generate_lightmap_uvs", True))); self.lightmap_channel.setValue(int(settings.get("lightmap_uv_channel", 1)))
        self.weld.setValue(float(settings.get("weld_threshold", 0.0001))); self.degenerate.setChecked(bool(settings.get("remove_degenerates", True)))
        self.cpu_access.setChecked(bool(settings.get("allow_cpu_access", False))); self.streaming.setChecked(bool(settings.get("streaming", True))); self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"geometry": {"normals": self.normals.currentText(), "tangents": self.tangents.currentText(), "generate_lightmap_uvs": self.lightmap.isChecked(), "lightmap_uv_channel": self.lightmap_channel.value(), "weld_threshold": self.weld.value(), "remove_degenerates": self.degenerate.isChecked(), "allow_cpu_access": self.cpu_access.isChecked(), "streaming": self.streaming.isChecked()}}

    def validation_issues(self) -> list[str]:
        return ["Lightmap UV channel must differ from the primary texture UV channel 0."] if self.lightmap.isChecked() and self.lightmap_channel.value() == 0 else []

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class MeshMaterialSlotsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Slot", "Material Asset ID", "Section", "Cast Shadow"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Slot"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        self._loading = False; add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for index, value in enumerate(values.get("material_slots") or values.get("materials") or []):
            row = dict(value) if isinstance(value, dict) else {"material_asset_id": value}
            self._append(str(row.get("name") or f"Slot {index}"), str(row.get("material_asset_id") or row.get("asset_id") or ""), int(row.get("section", index)), bool(row.get("cast_shadow", True)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"material_slots": [{"name": _table_text(self.table, row, 0), "material_asset_id": _table_text(self.table, row, 1), "section": _safe_int(_table_text(self.table, row, 2), row), "cast_shadow": _table_text(self.table, row, 3).casefold() in {"yes", "true", "1", "on"}} for row in range(self.table.rowCount())]}

    def validation_issues(self) -> list[str]:
        return [
            f"Material slot row {row + 1} needs a whole-number section index."
            for row in range(self.table.rowCount())
            if not _is_int(_table_text(self.table, row, 2))
        ]

    def _append(self, name: str, asset_id: str, section: int, shadow: bool) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, asset_id, section, "Yes" if shadow else "No")): self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def _add(self) -> None: self._append(f"Slot {self.table.rowCount()}", "", self.table.rowCount(), True); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationStateMachineEditorWidget(QWidget):
    """Layer and state authoring with explicit entry state and motion assignment."""

    changed = Signal()

    def __init__(self, project_root: str | Path, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent); self.project_root = Path(project_root).resolve(); self.database = database
        self._layers: list[dict[str, Any]] = []; self._current_layer = -1; self._loading = False
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Animation Layers"))
        self.layers_table = QTableWidget(0, 5, self); self.layers_table.setHorizontalHeaderLabels(["ID", "Name", "Weight", "Blend", "Mask Asset"]); self.layers_table.setMaximumHeight(145); self.layers_table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.layers_table)
        layer_actions = QHBoxLayout(); add_layer = QPushButton("+ Layer"); remove_layer = QPushButton("Delete Layer"); layer_actions.addWidget(add_layer); layer_actions.addWidget(remove_layer); layer_actions.addStretch(1); root.addLayout(layer_actions)
        entry_row = QHBoxLayout(); self.entry_state = QComboBox(self); entry_row.addWidget(QLabel("Entry State")); entry_row.addWidget(self.entry_state); entry_row.addStretch(1); root.addLayout(entry_row)
        self.states = QTableWidget(0, 7, self); self.states.setHorizontalHeaderLabels(["ID", "Name", "Motion Type", "Motion Asset", "Speed", "Loop", "Blend Parameters"]); self.states.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.states, 1)
        state_actions = QHBoxLayout(); add_state = QPushButton("+ State"); remove_state = QPushButton("Delete State"); choose_motion = QPushButton("Choose Motion..."); state_actions.addWidget(add_state); state_actions.addWidget(remove_state); state_actions.addWidget(choose_motion); state_actions.addStretch(1); root.addLayout(state_actions)
        self.summary = QLabel("", self); root.addWidget(self.summary)
        add_layer.clicked.connect(self._add_layer); remove_layer.clicked.connect(self._remove_layer); add_state.clicked.connect(self._add_state); remove_state.clicked.connect(self._remove_state); choose_motion.clicked.connect(self._choose_motion)
        self.layers_table.currentCellChanged.connect(self._switch_layer); self.layers_table.itemChanged.connect(self._layer_edited); self.states.itemChanged.connect(self._states_edited); self.entry_state.currentTextChanged.connect(self._entry_edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self._layers = deepcopy(list(values.get("layers") or []))
        if not self._layers:
            self._layers = [{"id": "base", "name": "Base Layer", "weight": 1.0, "blend_mode": "override", "mask_asset_id": "", "state_machine": {"entry_state": "entry", "states": [{"id": "entry", "name": "Entry", "motion": None, "speed": 1.0, "loop": True}], "transitions": []}}]
        self.layers_table.setRowCount(0)
        for layer in self._layers:
            row = self.layers_table.rowCount(); self.layers_table.insertRow(row)
            for column, value in enumerate((layer.get("id", "base"), layer.get("name", "Layer"), layer.get("weight", 1.0), layer.get("blend_mode", "override"), layer.get("mask_asset_id", ""))): self.layers_table.setItem(row, column, QTableWidgetItem(str(value)))
        self._current_layer = 0; self.layers_table.selectRow(0); self._load_layer(0); self._loading = False; self._update_summary()

    def settings(self) -> dict[str, Any]:
        self._sync_layer(self._current_layer)
        return {"layers": deepcopy(self._layers)}

    def validation_issues(self) -> list[str]:
        values = self.settings(); issues = []
        for index, layer in enumerate(values["layers"]):
            machine = dict(layer.get("state_machine") or {}); ids = [str(row.get("id") or "") for row in machine.get("states") or []]
            if not ids or any(not value for value in ids): issues.append(f"Animation layer {index + 1} needs named states.")
            if len(ids) != len(set(ids)): issues.append(f"Animation layer {index + 1} has duplicate state IDs.")
            if str(machine.get("entry_state") or "") not in ids: issues.append(f"Animation layer {index + 1} entry state must reference a state.")
        return issues

    def _load_layer(self, row: int) -> None:
        self.states.setRowCount(0); self.entry_state.clear()
        if not 0 <= row < len(self._layers): return
        machine = dict(self._layers[row].get("state_machine") or {})
        for raw in machine.get("states") or []:
            state = dict(raw); motion = state.get("motion"); motion = dict(motion) if isinstance(motion, dict) else ({"type": "clip", "asset_id": motion} if motion else {})
            target = self.states.rowCount(); self.states.insertRow(target)
            values = (state.get("id", "state"), state.get("name", "State"), motion.get("type", "clip"), motion.get("asset_id", ""), state.get("speed", 1.0), "Yes" if state.get("loop", True) else "No", _json_text(motion.get("parameters", {})))
            for column, value in enumerate(values): self.states.setItem(target, column, QTableWidgetItem(str(value)))
            self.entry_state.addItem(str(state.get("id") or ""))
        self.entry_state.setCurrentText(str(machine.get("entry_state") or ""))

    def _sync_layer(self, row: int) -> None:
        if not 0 <= row < len(self._layers): return
        layer = self._layers[row]
        if row < self.layers_table.rowCount():
            layer.update({"id": _table_text(self.layers_table, row, 0) or f"layer_{row}", "name": _table_text(self.layers_table, row, 1) or f"Layer {row + 1}", "weight": _safe_float(_table_text(self.layers_table, row, 2), 1.0), "blend_mode": _table_text(self.layers_table, row, 3) or "override", "mask_asset_id": _table_text(self.layers_table, row, 4)})
        machine = layer.setdefault("state_machine", {}); states = []
        for index in range(self.states.rowCount()):
            motion_asset = _table_text(self.states, index, 3); motion = None
            if motion_asset or _table_text(self.states, index, 2): motion = {"type": _table_text(self.states, index, 2) or "clip", "asset_id": motion_asset, "parameters": _json_value(_table_text(self.states, index, 6)) or {}}
            states.append({"id": _table_text(self.states, index, 0), "name": _table_text(self.states, index, 1), "motion": motion, "speed": _safe_float(_table_text(self.states, index, 4), 1.0), "loop": _table_text(self.states, index, 5).casefold() in {"yes", "true", "1", "on"}})
        machine["states"] = states; machine["entry_state"] = self.entry_state.currentText(); machine.setdefault("transitions", [])

    def _switch_layer(self, current_row: int, _current_column: int, previous_row: int, _previous_column: int) -> None:
        if self._loading or current_row < 0: return
        self._sync_layer(previous_row); self._loading = True; self._current_layer = current_row; self._load_layer(current_row); self._loading = False; self._update_summary()

    def _add_layer(self) -> None:
        self._sync_layer(self._current_layer); index = len(self._layers); layer_id = f"layer_{index + 1}"
        self._layers.append({"id": layer_id, "name": f"Layer {index + 1}", "weight": 1.0, "blend_mode": "override", "mask_asset_id": "", "state_machine": {"entry_state": "entry", "states": [{"id": "entry", "name": "Entry", "motion": None, "speed": 1.0, "loop": True}], "transitions": []}})
        self.load_settings({"layers": self._layers}); self.layers_table.selectRow(index); self.changed.emit()

    def _remove_layer(self) -> None:
        row = self.layers_table.currentRow()
        if row < 0 or len(self._layers) <= 1: return
        self._layers.pop(row); self.load_settings({"layers": self._layers}); self.changed.emit()

    def _add_state(self) -> None:
        index = self.states.rowCount(); state_id = f"state_{index + 1}"; self.states.insertRow(index)
        for column, value in enumerate((state_id, f"State {index + 1}", "clip", "", 1.0, "Yes", "{}")): self.states.setItem(index, column, QTableWidgetItem(str(value)))
        self._states_edited()

    def _remove_state(self) -> None:
        row = self.states.currentRow()
        if row >= 0: self.states.removeRow(row); self._states_edited()

    def _choose_motion(self) -> None:
        row = self.states.currentRow()
        if row < 0: return
        from tech_connector.ui.game_engine.asset_picker import AssetPickerDialog
        kind = _table_text(self.states, row, 2).casefold(); allowed = ("tc.blend_space",) if kind == "blend_space" else ("tc.animation_clip", "tc.blend_space")
        picker = AssetPickerDialog(self.project_root, self.database, allowed_types=allowed, current_asset_id=_table_text(self.states, row, 3), title="Choose State Motion", parent=self)
        if picker.exec() == QDialog.Accepted:
            self.states.item(row, 3).setText(picker.selected_asset_id)

    def _layer_edited(self, *_args) -> None:
        if not self._loading: self._sync_layer(self._current_layer); self._update_summary(); self.changed.emit()

    def _states_edited(self, *_args) -> None:
        if self._loading: return
        selected = self.entry_state.currentText(); self._loading = True; self.entry_state.clear(); self.entry_state.addItems([_table_text(self.states, row, 0) for row in range(self.states.rowCount())]); self.entry_state.setCurrentText(selected); self._loading = False
        self._sync_layer(self._current_layer); self._update_summary(); self.changed.emit()

    def _entry_edited(self, *_args) -> None:
        if not self._loading: self._sync_layer(self._current_layer); self.changed.emit()

    def _update_summary(self) -> None:
        states = sum(len(dict(layer.get("state_machine") or {}).get("states") or []) for layer in self._layers); self.summary.setText(f"{len(self._layers)} layer(s) - {states} state(s) - supports clips and Blend Spaces")


class AnimationControllerPreviewCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.state_name = ""; self.normalized_time = 0.0; self.root_motion: dict[str, Any] = {}; self.setMinimumHeight(260)

    def set_preview(self, state_name: str, normalized_time: float, root_motion: dict[str, Any]) -> None:
        self.state_name = str(state_name); self.normalized_time = float(normalized_time); self.root_motion = dict(root_motion or {}); self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing, True); painter.fillRect(self.rect(), QColor("#071018"))
        center = QPointF(self.width() * .5, self.height() * .55); phase = math.sin(self.normalized_time * math.tau)
        painter.setPen(QPen(QColor("#70d6ff"), 4)); painter.drawLine(center + QPointF(0, -75), center + QPointF(0, 0)); painter.drawEllipse(center + QPointF(-13, -102), 13, 13)
        painter.drawLine(center + QPointF(0, -55), center + QPointF(-32 - phase * 8, -18)); painter.drawLine(center + QPointF(0, -55), center + QPointF(32 + phase * 8, -18)); painter.drawLine(center, center + QPointF(-24 + phase * 10, 55)); painter.drawLine(center, center + QPointF(24 - phase * 10, 55))
        mode = str(self.root_motion.get("mode") or "in_place"); distance = 0.0 if mode in {"in_place", "ignore"} else 70.0 * self.normalized_time
        painter.setPen(QPen(QColor("#f5bd50"), 3)); painter.drawLine(center + QPointF(-35, 78), center + QPointF(-35 + distance, 78)); painter.drawText(12, 22, f"State: {self.state_name or 'None'} | Root Motion: {mode} | t={self.normalized_time:.2f}")


class AnimationControllerDebuggerWidget(QWidget):
    """Deterministic editor simulation with live state, trace, pose, and root-motion feedback."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent); self._values: dict[str, Any] = {}; self._state = ""; self._time = 0.0
        root = QVBoxLayout(self); controls = QHBoxLayout(); self.layer = QComboBox(self); self.play = QPushButton("Play"); self.play.setCheckable(True); step = QPushButton("Step"); reset = QPushButton("Reset")
        controls.addWidget(QLabel("Layer")); controls.addWidget(self.layer); controls.addWidget(self.play); controls.addWidget(step); controls.addWidget(reset); controls.addStretch(1); root.addLayout(controls)
        self.canvas = AnimationControllerPreviewCanvas(self); root.addWidget(self.canvas, 1)
        self.parameters = QTableWidget(0, 3, self); self.parameters.setHorizontalHeaderLabels(["Parameter", "Preview Value", "Type"]); self.parameters.setMaximumHeight(150); root.addWidget(self.parameters)
        self.current = QLabel("No active state", self); root.addWidget(self.current); self.trace = QListWidget(self); self.trace.setMaximumHeight(120); root.addWidget(self.trace)
        self.timer = QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self._tick); self.play.toggled.connect(lambda enabled: self.timer.start() if enabled else self.timer.stop()); step.clicked.connect(self._tick); reset.clicked.connect(self.reset); self.layer.currentTextChanged.connect(lambda _value: self.reset()); self.parameters.itemChanged.connect(lambda _item: self._evaluate())

    def load_settings(self, values: dict[str, Any]) -> None:
        self._values = deepcopy(values or {}); self.layer.blockSignals(True); self.layer.clear()
        for layer in self._values.get("layers") or []: self.layer.addItem(str(layer.get("name") or layer.get("id") or "Layer"), str(layer.get("id") or "base"))
        self.layer.blockSignals(False); self.parameters.blockSignals(True); self.parameters.setRowCount(0)
        for name, raw in dict(self._values.get("parameters") or {}).items():
            spec = dict(raw) if isinstance(raw, dict) else {"default": raw}; row = self.parameters.rowCount(); self.parameters.insertRow(row)
            for column, value in enumerate((name, _json_text(spec.get("default")), spec.get("type", _value_type(spec.get("default"))))): self.parameters.setItem(row, column, QTableWidgetItem(str(value)))
            self.parameters.item(row, 0).setFlags(self.parameters.item(row, 0).flags() & ~Qt.ItemIsEditable); self.parameters.item(row, 2).setFlags(self.parameters.item(row, 2).flags() & ~Qt.ItemIsEditable)
        self.parameters.blockSignals(False); self.reset()

    def reset(self) -> None:
        self._state = ""; self._time = 0.0; self.trace.clear(); self._evaluate()

    def preview_state(self) -> dict[str, Any]:
        return {"state": self._state, "normalized_time": self._time, "trace_count": self.trace.count()}

    def _parameter_values(self) -> dict[str, Any]:
        return {_table_text(self.parameters, row, 0): _json_value(_table_text(self.parameters, row, 1)) for row in range(self.parameters.rowCount())}

    def _tick(self) -> None:
        self._time = (self._time + 0.1) % 1.0; self._evaluate()

    def _evaluate(self) -> None:
        result = evaluate_animation_controller(self._values, parameter_values=self._parameter_values(), layer_id=str(self.layer.currentData() or ""), current_state=self._state, normalized_time=self._time)
        if result["transitioned"]:
            self.trace.insertItem(0, f"{result['previous_state']} -> {result['current_state']} ({result['transition_id'] or 'transition'})"); self._time = 0.0
        self._state = str(result["current_state"] or ""); self.current.setText(f"ACTIVE: {self._state or 'None'} - t={self._time:.2f} - motion={result['motion'] or 'None'}")
        self.canvas.set_preview(self._state, self._time, dict(result.get("root_motion") or {}))


class AnimationControllerParametersEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Name", "Type", "Default", "Replicated"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Parameter"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        self._loading = False; add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for name, raw in dict(values.get("parameters") or {}).items():
            descriptor = dict(raw) if isinstance(raw, dict) else {"default": raw}
            self._append(str(name), str(descriptor.get("type") or _value_type(descriptor.get("default"))), descriptor.get("default"), bool(descriptor.get("replicated", False)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"parameters": {_table_text(self.table, row, 0): {"type": _table_text(self.table, row, 1) or "float", "default": _json_value(_table_text(self.table, row, 2)), "replicated": _table_text(self.table, row, 3).casefold() in {"yes", "true", "1", "on"}} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)}}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0) for row in range(self.table.rowCount())]
        return ["Animation parameter names must be unique."] if len(names) != len(set(names)) else []

    def _append(self, name: str, kind: str, default: Any, replicated: bool) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, kind, _json_text(default), "Yes" if replicated else "No")): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"parameter_{self.table.rowCount() + 1}", "float", 0.0, False); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationControllerTransitionsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self)
        self.table = QTableWidget(0, 7, self); self.table.setHorizontalHeaderLabels(["Layer", "From", "To", "Condition JSON", "Blend s", "Exit Time", "Interrupt"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Transition"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        self._layers: list[dict[str, Any]] = []; self._loading = False; add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._layers = deepcopy(list(values.get("layers") or [])); self._loading = True; self.table.setRowCount(0)
        for layer in self._layers:
            machine = dict(layer.get("state_machine") or {})
            for transition in machine.get("transitions") or []:
                row = dict(transition); self._append(str(layer.get("id") or "base"), str(row.get("from") or row.get("source") or ""), str(row.get("to") or row.get("target") or ""), row.get("conditions") or row.get("condition") or [], float(row.get("blend_seconds", row.get("duration", 0.2))), row.get("exit_time", ""), str(row.get("interrupt") or "none"), transition_id=str(row.get("id") or ""))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        layers = deepcopy(self._layers) or [{"id": "base", "name": "Base Layer", "state_machine": {"entry_state": "", "states": [], "transitions": []}}]
        by_id = {str(layer.get("id") or "base"): layer for layer in layers}
        for layer in layers: layer.setdefault("state_machine", {})["transitions"] = []
        for row in range(self.table.rowCount()):
            layer_id = _table_text(self.table, row, 0) or "base"; layer = by_id.setdefault(layer_id, {"id": layer_id, "name": layer_id, "state_machine": {"states": [], "transitions": []}})
            item = self.table.item(row, 0)
            transition_id = str(item.data(Qt.UserRole) or "") if item else ""
            machine = layer.setdefault("state_machine", {}); machine.setdefault("transitions", []).append({"id": transition_id or f"transition_{uuid.uuid4().hex[:10]}", "from": _table_text(self.table, row, 1), "to": _table_text(self.table, row, 2), "conditions": _json_value(_table_text(self.table, row, 3)) or [], "blend_seconds": _safe_float(_table_text(self.table, row, 4), 0.2), "exit_time": _json_value(_table_text(self.table, row, 5)), "interrupt": _table_text(self.table, row, 6) or "none"})
        return {"layers": list(by_id.values())}

    def apply_to(self, values: dict[str, Any]) -> None:
        """Apply only transition edits to the latest layer/state authoring from the State Machine page."""
        authored_layers = deepcopy(list(values.get("layers") or self._layers))
        edited = self.settings()["layers"]
        transitions_by_id = {
            str(layer.get("id") or "base"): deepcopy(dict(layer.get("state_machine") or {}).get("transitions") or [])
            for layer in edited
        }
        for layer in authored_layers:
            layer_id = str(layer.get("id") or "base")
            layer.setdefault("state_machine", {})["transitions"] = transitions_by_id.get(layer_id, [])
        values["layers"] = authored_layers

    def validation_issues(self) -> list[str]:
        return [
            f"Transition row {row + 1} needs a numeric blend duration."
            for row in range(self.table.rowCount())
            if not _is_float(_table_text(self.table, row, 4))
        ]

    def _append(self, layer: str, source: str, target: str, condition: Any, blend: float, exit_time: Any, interrupt: str, *, transition_id: str = "") -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((layer, source, target, _json_text(condition), blend, _json_text(exit_time), interrupt)): self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.item(row, 0).setData(Qt.UserRole, transition_id or f"transition_{uuid.uuid4().hex[:10]}")
    def _add(self) -> None: self._append("base", "", "", [], 0.2, "", "none"); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class EffectTimelineEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout()
        self.duration = QDoubleSpinBox(self); self.duration.setRange(0.01, 36000.0); self.duration.setDecimals(3)
        self.loop = QCheckBox("Loop the system")
        self.warmup = QDoubleSpinBox(self); self.warmup.setRange(0.0, 3600.0); self.warmup.setDecimals(3)
        self.fixed_step = QDoubleSpinBox(self); self.fixed_step.setRange(0.0001, 1.0); self.fixed_step.setDecimals(6)
        form.addRow("Duration", self.duration); form.addRow("Playback", self.loop); form.addRow("Warmup Seconds", self.warmup); form.addRow("Warmup Step", self.fixed_step); root.addLayout(form)
        self.emitters = QTableWidget(0, 4, self); self.emitters.setHorizontalHeaderLabels(["Emitter", "Enabled", "Spawn Rate", "Lifetime"]); root.addWidget(self.emitters, 1)
        self._values: dict[str, Any] = {}; self._loading = False
        for widget in (self.duration, self.warmup, self.fixed_step): widget.valueChanged.connect(self._edited)
        self.loop.toggled.connect(self._edited); self.emitters.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._values = deepcopy(values); self._loading = True; self.duration.setValue(float(values.get("duration", 5.0))); self.loop.setChecked(bool(values.get("loop", False)))
        warmup = dict(values.get("warmup") or {}); self.warmup.setValue(float(warmup.get("seconds", 0.0))); self.fixed_step.setValue(float(warmup.get("step_seconds", 1.0 / 30.0))); self.emitters.setRowCount(0)
        for emitter in values.get("emitters") or []:
            row = self.emitters.rowCount(); self.emitters.insertRow(row)
            for column, value in enumerate((emitter.get("name", "Emitter"), "Yes" if emitter.get("enabled", True) else "No", emitter.get("spawn_rate", 0.0), emitter.get("lifetime", 1.0))):
                item = QTableWidgetItem(str(value)); item.setFlags(item.flags() & ~Qt.ItemIsEditable); self.emitters.setItem(row, column, item)
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"duration": self.duration.value(), "loop": self.loop.isChecked(), "warmup": {"seconds": self.warmup.value(), "step_seconds": self.fixed_step.value()}}

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class EffectScalabilityEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Quality", "Spawn Scale", "Capacity Scale", "Disabled Emitter IDs"]); root.addWidget(self.table, 1)
        self._loading = False; self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for quality, override in dict(values.get("quality_overrides") or {}).items():
            row = self.table.rowCount(); self.table.insertRow(row); data = dict(override)
            for column, value in enumerate((quality, data.get("spawn_scale", 1.0), data.get("capacity_scale", 1.0), ",".join(str(item) for item in data.get("disabled_emitters") or []))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"quality_overrides": {_table_text(self.table, row, 0): {"spawn_scale": _safe_float(_table_text(self.table, row, 1), 1.0), "capacity_scale": _safe_float(_table_text(self.table, row, 2), 1.0), "disabled_emitters": [item.strip() for item in _table_text(self.table, row, 3).split(",") if item.strip()]} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)}}

    def validation_issues(self) -> list[str]:
        issues = []
        for row in range(self.table.rowCount()):
            quality = _table_text(self.table, row, 0) or f"Row {row + 1}"
            spawn_text = _table_text(self.table, row, 1); capacity_text = _table_text(self.table, row, 2)
            if not _is_float(spawn_text) or not _is_float(capacity_text):
                issues.append(f"{quality} scalability values must be numeric.")
            elif float(spawn_text) <= 0 or float(capacity_text) <= 0:
                issues.append(f"{quality} scalability values must be greater than zero.")
        return issues

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class TextureChannelEditorWidget(QWidget):
    """Channel interpretation and normal/alpha transforms applied before cook."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False
        self.swizzles = []
        for channel in "RGBA":
            control = QComboBox(self); control.addItems(["R", "G", "B", "A", "0", "1"])
            form.addRow(f"Output {channel}", control); self.swizzles.append(control)
            control.currentTextChanged.connect(self._edited)
        self.alpha = QComboBox(self); self.alpha.addItems(["straight", "premultiplied", "opaque", "coverage"])
        self.flip_green = QCheckBox("Flip green channel for DirectX-style normal maps", self)
        form.addRow("Alpha Interpretation", self.alpha); form.addRow("Normal Convention", self.flip_green)
        self.alpha.currentTextChanged.connect(self._edited); self.flip_green.toggled.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        channels = dict(values.get("channels") or {}); swizzle = str(channels.get("swizzle") or "RGBA").upper()
        self._loading = True
        for index, control in enumerate(self.swizzles): control.setCurrentText(swizzle[index] if index < len(swizzle) else "RGBA"[index])
        self.alpha.setCurrentText(str(channels.get("alpha_mode") or "straight")); self.flip_green.setChecked(bool(channels.get("flip_green", False))); self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"channels": {"swizzle": "".join(control.currentText() for control in self.swizzles), "alpha_mode": self.alpha.currentText(), "flip_green": self.flip_green.isChecked()}}

    def validation_issues(self) -> list[str]:
        return []

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class TextureMipEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False
        self.filter = QComboBox(self); self.filter.addItems(["kaiser", "lanczos", "box", "nearest"])
        self.address = QComboBox(self); self.address.addItems(["wrap", "clamp", "mirror", "border"])
        self.lod_bias = QDoubleSpinBox(self); self.lod_bias.setRange(-8.0, 16.0); self.lod_bias.setDecimals(2)
        self.sharpen = QDoubleSpinBox(self); self.sharpen.setRange(0.0, 10.0); self.sharpen.setDecimals(2)
        self.preserve_coverage = QCheckBox("Preserve alpha-test coverage", self)
        self.alpha_reference = QDoubleSpinBox(self); self.alpha_reference.setRange(0.0, 1.0); self.alpha_reference.setDecimals(3); self.alpha_reference.setValue(0.5)
        for label, widget in (("Downsample Filter", self.filter), ("Address Mode", self.address), ("LOD Bias", self.lod_bias), ("Sharpen", self.sharpen), ("Alpha Coverage", self.preserve_coverage), ("Alpha Reference", self.alpha_reference)): form.addRow(label, widget)
        for widget in (self.filter, self.address): widget.currentTextChanged.connect(self._edited)
        for widget in (self.lod_bias, self.sharpen, self.alpha_reference): widget.valueChanged.connect(self._edited)
        self.preserve_coverage.toggled.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        settings = dict(values.get("mip_settings") or {}); self._loading = True
        self.filter.setCurrentText(str(settings.get("filter") or "kaiser")); self.address.setCurrentText(str(settings.get("address_mode") or "wrap")); self.lod_bias.setValue(float(settings.get("lod_bias", 0.0))); self.sharpen.setValue(float(settings.get("sharpen", 0.0))); self.preserve_coverage.setChecked(bool(settings.get("preserve_alpha_coverage", False))); self.alpha_reference.setValue(float(settings.get("alpha_reference", 0.5))); self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"mip_settings": {"filter": self.filter.currentText(), "address_mode": self.address.currentText(), "lod_bias": self.lod_bias.value(), "sharpen": self.sharpen.value(), "preserve_alpha_coverage": self.preserve_coverage.isChecked(), "alpha_reference": self.alpha_reference.value()}}

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class TexturePlatformEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False
        root.addWidget(QLabel("Optional platform overrides; Automatic inherits the shared import settings."))
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Platform", "Format", "Max Size", "Quality"]); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Platform"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for platform, override in dict(values.get("platform_overrides") or {}).items():
            data = dict(override); self._append(str(platform), str(data.get("format") or "auto"), int(data.get("max_size", 0)), str(data.get("quality") or "normal"))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"platform_overrides": {_table_text(self.table, row, 0): {"format": _table_text(self.table, row, 1) or "auto", "max_size": _safe_int(_table_text(self.table, row, 2)), "quality": _table_text(self.table, row, 3) or "normal"} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)}}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).casefold() for row in range(self.table.rowCount())]
        issues = ["Texture platform overrides must use unique platform names."] if len(names) != len(set(names)) else []
        issues.extend(f"Texture platform row {row + 1} needs a whole-number maximum size." for row in range(self.table.rowCount()) if not _is_int(_table_text(self.table, row, 2)))
        return issues

    def _append(self, platform: str, texture_format: str, max_size: int, quality: str) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((platform, texture_format, max_size, quality)): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append("windows", "auto", 0, "normal"); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class InputActionsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False; self._actions: dict[str, dict[str, Any]] = {}
        self.table = QTableWidget(0, 6, self); self.table.setHorizontalHeaderLabels(["Action", "Value Type", "Trigger", "Threshold", "Dead Zone", "Sensitivity"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Action"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._actions = deepcopy(dict(values.get("actions") or {})); self._loading = True; self.table.setRowCount(0)
        for name, raw in self._actions.items():
            data = dict(raw) if isinstance(raw, dict) else {}; self._append(str(name), str(data.get("value_type") or "button"), str(data.get("trigger") or "pressed"), float(data.get("threshold", 0.5)), float(data.get("dead_zone", 0.1)), float(data.get("sensitivity", 1.0)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        result = {}
        for row in range(self.table.rowCount()):
            name = _table_text(self.table, row, 0)
            name_item = self.table.item(row, 0)
            original_name = str(name_item.data(Qt.UserRole) or name) if name_item else name
            original = deepcopy(self._actions.get(original_name, {}))
            original.update({"value_type": _table_text(self.table, row, 1) or "button", "trigger": _table_text(self.table, row, 2) or "pressed", "threshold": _safe_float(_table_text(self.table, row, 3), 0.5), "dead_zone": _safe_float(_table_text(self.table, row, 4), 0.1), "sensitivity": _safe_float(_table_text(self.table, row, 5), 1.0)}); result[name] = original
        return {"actions": result}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).strip() for row in range(self.table.rowCount())]
        issues = []
        if any(not name for name in names): issues.append("Every input action needs a name.")
        if len({name.casefold() for name in names}) != len(names): issues.append("Input action names must be unique.")
        for row in range(self.table.rowCount()):
            if not all(_is_float(_table_text(self.table, row, column)) for column in (3, 4, 5)): issues.append(f"Input action row {row + 1} has an invalid numeric setting.")
        return issues

    def _append(self, name: str, kind: str, trigger: str, threshold: float, dead_zone: float, sensitivity: float) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, kind, trigger, threshold, dead_zone, sensitivity)): self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.item(row, 0).setData(Qt.UserRole, name)
    def _add(self) -> None: self._append(f"Action{self.table.rowCount() + 1}", "button", "pressed", 0.5, 0.1, 1.0); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class InputContextsEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Context", "Priority", "Enabled", "Exclusive"]); self.table.setSelectionBehavior(QAbstractItemView.SelectRows); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Context"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for raw in values.get("contexts") or []:
            data = {"id": raw, "priority": 0} if isinstance(raw, str) else dict(raw); self._append(str(data.get("id") or data.get("name") or "Gameplay"), int(data.get("priority", 0)), bool(data.get("enabled", True)), bool(data.get("exclusive", False)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"contexts": [{"id": _table_text(self.table, row, 0), "priority": _safe_int(_table_text(self.table, row, 1)), "enabled": _table_bool(self.table, row, 2), "exclusive": _table_bool(self.table, row, 3)} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)]}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).strip() for row in range(self.table.rowCount())]
        issues = ["Input context names must be unique."] if len({name.casefold() for name in names}) != len(names) else []
        issues.extend(f"Input context row {row + 1} needs a whole-number priority." for row in range(self.table.rowCount()) if not _is_int(_table_text(self.table, row, 1)))
        return issues

    def _append(self, name: str, priority: int, enabled: bool, exclusive: bool) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, priority, "Yes" if enabled else "No", "Yes" if exclusive else "No")): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"Context{self.table.rowCount() + 1}", self.table.rowCount(), True, False); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class InputLiveDebugWidget(QWidget):
    """Local action-value probe; it intentionally does not mutate the Input Map."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout()
        self.action = QComboBox(self); self.device = QComboBox(self); self.device.addItems(["keyboard_mouse", "gamepad", "touch"])
        self.value = QSlider(Qt.Horizontal, self); self.value.setRange(-1000, 1000)
        form.addRow("Action", self.action); form.addRow("Device", self.device); form.addRow("Simulated Value", self.value); root.addLayout(form)
        self.readout = QLabel("Select an action to inspect its normalized value and trigger state."); self.readout.setWordWrap(True); root.addWidget(self.readout); root.addStretch(1)
        self.action.currentTextChanged.connect(self._refresh); self.device.currentTextChanged.connect(self._refresh); self.value.valueChanged.connect(self._refresh)

    def load_settings(self, values: dict[str, Any]) -> None:
        current = self.action.currentText(); self.action.clear(); self.action.addItems(sorted(str(name) for name in dict(values.get("actions") or {}))); self.action.setCurrentText(current); self._refresh()

    def _refresh(self, *_args) -> None:
        value = self.value.value() / 1000.0; state = "Triggered" if abs(value) >= 0.5 else ("Actuated" if abs(value) > 0.1 else "Idle")
        self.readout.setText(f"{self.action.currentText() or 'No Action'} • {self.device.currentText()} • value {value:+.3f} • {state}\nThis probe mirrors runtime normalization without changing the authored binding.")


class PhysicsPhysicalAnimationEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False
        self.enabled = QCheckBox("Drive simulated bodies toward animation", self)
        self.blend = QDoubleSpinBox(self); self.blend.setRange(0.0, 1.0); self.blend.setDecimals(3)
        self.strength = QDoubleSpinBox(self); self.strength.setRange(0.0, 100000.0)
        self.damping = QDoubleSpinBox(self); self.damping.setRange(0.0, 10000.0)
        self.max_force = QDoubleSpinBox(self); self.max_force.setRange(0.0, 1.0e9)
        self.recovery = QDoubleSpinBox(self); self.recovery.setRange(0.0, 60.0); self.recovery.setDecimals(3)
        for label, widget in (("Enabled", self.enabled), ("Simulation Blend", self.blend), ("Drive Strength", self.strength), ("Drive Damping", self.damping), ("Maximum Force", self.max_force), ("Recovery Seconds", self.recovery)): form.addRow(label, widget)
        self.enabled.toggled.connect(self._edited)
        for widget in (self.blend, self.strength, self.damping, self.max_force, self.recovery): widget.valueChanged.connect(self._edited)

    def load_settings(self, values: dict[str, Any]) -> None:
        data = dict(values.get("physical_animation") or {}); self._loading = True
        self.enabled.setChecked(bool(data.get("enabled", True))); self.blend.setValue(float(data.get("blend", 0.0))); self.strength.setValue(float(data.get("strength", 1000.0))); self.damping.setValue(float(data.get("damping", 100.0))); self.max_force.setValue(float(data.get("max_force", 0.0))); self.recovery.setValue(float(data.get("recovery_seconds", 0.35))); self._loading = False

    def settings(self) -> dict[str, Any]:
        return {"physical_animation": {"enabled": self.enabled.isChecked(), "blend": self.blend.value(), "strength": self.strength.value(), "damping": self.damping.value(), "max_force": self.max_force.value(), "recovery_seconds": self.recovery.value()}}

    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class PhysicsSolverProfilesEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout(); self._loading = False
        self.iterations = QSpinBox(self); self.iterations.setRange(1, 128); self.substeps = QSpinBox(self); self.substeps.setRange(1, 32)
        self.projection = QCheckBox("Enable constraint projection", self); self.sleep = QDoubleSpinBox(self); self.sleep.setRange(0.0, 1000.0); self.sleep.setDecimals(4)
        form.addRow("Solver Iterations", self.iterations); form.addRow("Substeps", self.substeps); form.addRow("Stability", self.projection); form.addRow("Sleep Threshold", self.sleep); root.addLayout(form)
        root.addWidget(QLabel("Named profiles override body drive and blend values at runtime."))
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Profile", "Blend", "Strength Scale", "Damping Scale"]); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Profile"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        for widget in (self.iterations, self.substeps, self.sleep): widget.valueChanged.connect(self._edited)
        self.projection.toggled.connect(self._edited); self.table.itemChanged.connect(self._edited); add.clicked.connect(self._add); remove.clicked.connect(self._remove)

    def load_settings(self, values: dict[str, Any]) -> None:
        solver = dict(values.get("solver") or {}); self._loading = True; self.iterations.setValue(int(solver.get("iterations", 8))); self.substeps.setValue(int(solver.get("substeps", 2))); self.projection.setChecked(bool(solver.get("projection", True))); self.sleep.setValue(float(solver.get("sleep_threshold", 0.01))); self.table.setRowCount(0)
        for name, raw in dict(values.get("profiles") or {}).items():
            data = dict(raw); self._append(str(name), float(data.get("blend", 1.0)), float(data.get("strength_scale", 1.0)), float(data.get("damping_scale", 1.0)))
        self._loading = False

    def settings(self) -> dict[str, Any]:
        profiles = {_table_text(self.table, row, 0): {"blend": _safe_float(_table_text(self.table, row, 1), 1.0), "strength_scale": _safe_float(_table_text(self.table, row, 2), 1.0), "damping_scale": _safe_float(_table_text(self.table, row, 3), 1.0)} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)}
        return {"solver": {"iterations": self.iterations.value(), "substeps": self.substeps.value(), "projection": self.projection.isChecked(), "sleep_threshold": self.sleep.value()}, "profiles": profiles}

    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).casefold() for row in range(self.table.rowCount())]
        return ["Physics profile names must be unique."] if len(names) != len(set(names)) else []

    def _append(self, name: str, blend: float, strength: float, damping: float) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, blend, strength, damping)): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"Profile{self.table.rowCount() + 1}", 1.0, 1.0, 1.0); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationClipTimelineEditorWidget(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); form = QFormLayout(); self._loading = False; self._tracks: list[dict[str, Any]] = []
        self.duration = QDoubleSpinBox(self); self.duration.setRange(0.001, 86400.0); self.duration.setDecimals(4)
        self.sample_rate = QDoubleSpinBox(self); self.sample_rate.setRange(1.0, 960.0); self.sample_rate.setDecimals(3)
        self.loop = QCheckBox("Loop during playback", self); self.frame = QSlider(Qt.Horizontal, self); self.frame.setRange(0, 1000)
        form.addRow("Duration Seconds", self.duration); form.addRow("Sample Rate", self.sample_rate); form.addRow("Playback", self.loop); form.addRow("Scrub", self.frame); root.addLayout(form)
        self.table = QTableWidget(0, 5, self); self.table.setHorizontalHeaderLabels(["Track", "Target", "Property", "Keys", "Enabled"]); root.addWidget(self.table, 1)
        self.readout = QLabel("Frame 0"); root.addWidget(self.readout)
        for widget in (self.duration, self.sample_rate): widget.valueChanged.connect(self._edited)
        self.loop.toggled.connect(self._edited); self.table.itemChanged.connect(self._edited); self.frame.valueChanged.connect(self._scrub)

    def load_settings(self, values: dict[str, Any]) -> None:
        self._tracks = deepcopy(list(values.get("tracks") or [])); self._loading = True; self.duration.setValue(float(values.get("duration_seconds", 1.0))); self.sample_rate.setValue(float(values.get("sample_rate", 30.0))); self.loop.setChecked(bool(values.get("loop", True))); self.table.setRowCount(0)
        for index, raw in enumerate(self._tracks):
            track = dict(raw); keys = list(track.get("keys") or track.get("samples") or ()); self._append(str(track.get("id") or f"track_{index}"), str(track.get("target") or track.get("bone") or ""), str(track.get("property") or "transform"), len(keys), bool(track.get("enabled", True)), index)
        self._loading = False; self._scrub()

    def settings(self) -> dict[str, Any]:
        tracks = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0); source_index = int(item.data(Qt.UserRole)) if item and item.data(Qt.UserRole) is not None else -1
            track = deepcopy(self._tracks[source_index]) if 0 <= source_index < len(self._tracks) else {}
            track.update({"id": _table_text(self.table, row, 0), "target": _table_text(self.table, row, 1), "property": _table_text(self.table, row, 2) or "transform", "enabled": _table_bool(self.table, row, 4)}); tracks.append(track)
        return {"duration_seconds": self.duration.value(), "sample_rate": self.sample_rate.value(), "loop": self.loop.isChecked(), "tracks": tracks}

    def validation_issues(self) -> list[str]:
        return [item.message for item in validate_animation_clip(self.settings()) if item.severity == "error"]

    def _append(self, name: str, target: str, prop: str, key_count: int, enabled: bool, source_index: int = -1) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, target, prop, key_count, "Yes" if enabled else "No")):
            item = QTableWidgetItem(str(value));
            if column == 3: item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, column, item)
        self.table.item(row, 0).setData(Qt.UserRole, source_index)
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()
    def _scrub(self, *_args) -> None:
        seconds = self.duration.value() * self.frame.value() / 1000.0; self.readout.setText(f"{seconds:.3f} s • frame {round(seconds * self.sample_rate.value())}")


class AnimationClipCurvesEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False
        self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Curve", "Target", "Type", "Keys JSON"]); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Curve"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for index, raw in enumerate(values.get("curves") or []):
            data = dict(raw); self._append(str(data.get("name") or f"Curve{index + 1}"), str(data.get("target") or ""), str(data.get("type") or "float"), data.get("keys") or [])
        self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"curves": [{"name": _table_text(self.table, row, 0), "target": _table_text(self.table, row, 1), "type": _table_text(self.table, row, 2) or "float", "keys": _json_value(_table_text(self.table, row, 3)) or []} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)]}
    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).casefold() for row in range(self.table.rowCount())]
        return ["Animation curve names must be unique."] if len(names) != len(set(names)) else []
    def _append(self, name: str, target: str, kind: str, keys: Any) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, target, kind, _json_text(keys))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"Curve{self.table.rowCount() + 1}", "", "float", []); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationClipEventsEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False; self.duration = 1.0
        self.events = QTableWidget(0, 4, self); self.events.setHorizontalHeaderLabels(["Time", "Event", "Type", "Payload JSON"]); root.addWidget(QLabel("Events")); root.addWidget(self.events, 1)
        event_actions = QHBoxLayout(); add_event = QPushButton("+ Event"); remove_event = QPushButton("Delete Event"); event_actions.addWidget(add_event); event_actions.addWidget(remove_event); event_actions.addStretch(1); root.addLayout(event_actions)
        self.markers = QTableWidget(0, 2, self); self.markers.setHorizontalHeaderLabels(["Time", "Sync Marker"]); root.addWidget(QLabel("Sync Markers")); root.addWidget(self.markers, 1)
        marker_actions = QHBoxLayout(); add_marker = QPushButton("+ Marker"); remove_marker = QPushButton("Delete Marker"); marker_actions.addWidget(add_marker); marker_actions.addWidget(remove_marker); marker_actions.addStretch(1); root.addLayout(marker_actions)
        add_event.clicked.connect(lambda: self._append_event(0.0, "Event", "gameplay", {})); remove_event.clicked.connect(lambda: self._remove(self.events)); add_marker.clicked.connect(lambda: self._append_marker(0.0, "Footstep")); remove_marker.clicked.connect(lambda: self._remove(self.markers)); self.events.itemChanged.connect(self._edited); self.markers.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        self.duration = float(values.get("duration_seconds", 1.0)); self._loading = True; self.events.setRowCount(0); self.markers.setRowCount(0)
        for raw in values.get("events") or []:
            data = dict(raw); self._append_event(float(data.get("time", 0.0)), str(data.get("name") or data.get("event") or "Event"), str(data.get("type") or "gameplay"), data.get("payload") or {})
        for raw in values.get("sync_markers") or []:
            data = dict(raw); self._append_marker(float(data.get("time", 0.0)), str(data.get("name") or "Marker"))
        self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"events": [{"time": _safe_float(_table_text(self.events, row, 0)), "name": _table_text(self.events, row, 1), "type": _table_text(self.events, row, 2) or "gameplay", "payload": _json_value(_table_text(self.events, row, 3)) or {}} for row in range(self.events.rowCount())], "sync_markers": [{"time": _safe_float(_table_text(self.markers, row, 0)), "name": _table_text(self.markers, row, 1)} for row in range(self.markers.rowCount())]}
    def validation_issues(self) -> list[str]:
        issues = []
        for table, label in ((self.events, "event"), (self.markers, "sync marker")):
            for row in range(table.rowCount()):
                text = _table_text(table, row, 0)
                if not _is_float(text) or not 0.0 <= _safe_float(text) <= self.duration: issues.append(f"Animation {label} row {row + 1} must lie within the clip duration.")
        return issues
    def _append_event(self, time_value: float, name: str, kind: str, payload: Any) -> None:
        row = self.events.rowCount(); self.events.insertRow(row)
        for column, value in enumerate((time_value, name, kind, _json_text(payload))): self.events.setItem(row, column, QTableWidgetItem(str(value)))
    def _append_marker(self, time_value: float, name: str) -> None:
        row = self.markers.rowCount(); self.markers.insertRow(row)
        for column, value in enumerate((time_value, name)): self.markers.setItem(row, column, QTableWidgetItem(str(value)))
    def _remove(self, table: QTableWidget) -> None:
        rows = sorted({item.row() for item in table.selectedItems()}, reverse=True)
        for row in rows: table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationRootMotionEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False
        self.mode = QComboBox(self); self.mode.addItems(["preserve", "extract", "consume", "ignore"]); self.root_bone = QLineEdit(self); self.lock_height = QCheckBox("Lock vertical translation", self); self.normalize_scale = QCheckBox("Normalize root scale", self)
        self.additive = QCheckBox("Author as additive animation", self); self.base_pose = QComboBox(self); self.base_pose.addItems(["reference_pose", "first_frame", "clip"]); self.base_clip = QLineEdit(self); self.space = QComboBox(self); self.space.addItems(["local", "mesh"])
        for label, widget in (("Root Motion", self.mode), ("Root Bone", self.root_bone), ("Height", self.lock_height), ("Scale", self.normalize_scale), ("Additive", self.additive), ("Base Pose", self.base_pose), ("Base Clip Asset", self.base_clip), ("Additive Space", self.space)): form.addRow(label, widget)
        for widget in (self.mode, self.base_pose, self.space): widget.currentTextChanged.connect(self._edited)
        for widget in (self.root_bone, self.base_clip): widget.textChanged.connect(self._edited)
        for widget in (self.lock_height, self.normalize_scale, self.additive): widget.toggled.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        root = values.get("root_motion"); root = {"mode": root} if isinstance(root, str) else dict(root or {}); additive = dict(values.get("additive") or {}); self._loading = True
        self.mode.setCurrentText(str(root.get("mode") or "preserve")); self.root_bone.setText(str(root.get("root_bone") or "root")); self.lock_height.setChecked(bool(root.get("lock_height", False))); self.normalize_scale.setChecked(bool(root.get("normalize_scale", True))); self.additive.setChecked(bool(additive.get("enabled", False))); self.base_pose.setCurrentText(str(additive.get("base_pose") or "reference_pose")); self.base_clip.setText(str(additive.get("base_clip_id") or "")); self.space.setCurrentText(str(additive.get("space") or "local")); self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"root_motion": {"mode": self.mode.currentText(), "root_bone": self.root_bone.text().strip() or "root", "lock_height": self.lock_height.isChecked(), "normalize_scale": self.normalize_scale.isChecked()}, "additive": {"enabled": self.additive.isChecked(), "base_pose": self.base_pose.currentText(), "base_clip_id": self.base_clip.text().strip(), "space": self.space.currentText()}}
    def validation_issues(self) -> list[str]:
        return ["Additive clip mode requires a base Animation Clip asset."] if self.additive.isChecked() and self.base_pose.currentText() == "clip" and not self.base_clip.text().strip() else []
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class AnimationCompressionEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False
        self.preset = QComboBox(self); self.preset.addItems(["lossless", "cinematic", "balanced", "runtime", "mobile"]); self.error = QDoubleSpinBox(self); self.error.setRange(0.0, 10.0); self.error.setDecimals(6); self.rotation = QComboBox(self); self.rotation.addItems(["variable", "quat_96", "quat_48", "full"]); self.translation = QComboBox(self); self.translation.addItems(["variable", "vector_96", "vector_48", "full"]); self.scale = QComboBox(self); self.scale.addItems(["variable", "uniform", "full", "strip"])
        for label, widget in (("Preset", self.preset), ("Error Threshold", self.error), ("Rotation", self.rotation), ("Translation", self.translation), ("Scale", self.scale)): form.addRow(label, widget)
        for widget in (self.preset, self.rotation, self.translation, self.scale): widget.currentTextChanged.connect(self._edited)
        self.error.valueChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        data = dict(values.get("compression") or {}); self._loading = True; self.preset.setCurrentText(str(data.get("preset") or "balanced")); self.error.setValue(float(data.get("error_threshold", 0.001))); self.rotation.setCurrentText(str(data.get("rotation_format") or "variable")); self.translation.setCurrentText(str(data.get("translation_format") or "variable")); self.scale.setCurrentText(str(data.get("scale_format") or "variable")); self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"compression": {"preset": self.preset.currentText(), "error_threshold": self.error.value(), "rotation_format": self.rotation.currentText(), "translation_format": self.translation.currentText(), "scale_format": self.scale.currentText()}}
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkeletonHierarchyEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False
        self.table = QTableWidget(0, 6, self); self.table.setHorizontalHeaderLabels(["Bone", "Parent", "Role", "Importance", "Reference Pose JSON", "Always Evaluate"]); root.addWidget(self.table, 1)
        controls = QHBoxLayout(); add = QPushButton("+ Bone"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls); add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        preserve = set(str(name) for name in values.get("preserve_bones") or ()); self._loading = True; self.table.setRowCount(0)
        for index, raw in enumerate(values.get("bones") or []):
            data = dict(raw); name = str(data.get("name") or data.get("id") or f"bone_{index}"); self._append(name, str(data.get("parent") or data.get("parent_id") or ""), str(data.get("role") or data.get("semantic_role") or ""), float(data.get("importance", 1.0)), data.get("reference_pose") or data.get("transform") or {}, name in preserve)
        self._loading = False
    def settings(self) -> dict[str, Any]:
        bones = []; preserve = []
        for row in range(self.table.rowCount()):
            name = _table_text(self.table, row, 0); bones.append({"name": name, "parent": _table_text(self.table, row, 1), "role": _table_text(self.table, row, 2), "importance": _safe_float(_table_text(self.table, row, 3), 1.0), "reference_pose": _json_value(_table_text(self.table, row, 4)) or {}})
            if _table_bool(self.table, row, 5): preserve.append(name)
        return {"bones": bones, "preserve_bones": preserve}
    def validation_issues(self) -> list[str]:
        return [item.message for item in validate_skeleton_properties(self.settings()) if item.severity == "error" and item.code not in {"missing_socket_bone", "unknown_retarget_bone"}]
    def _append(self, name: str, parent: str, role: str, importance: float, pose: Any, preserve: bool) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, parent, role, importance, _json_text(pose), "Yes" if preserve else "No")): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"bone_{self.table.rowCount()}", "", "", 1.0, {}, False); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkeletonSocketsEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False
        self.table = QTableWidget(0, 5, self); self.table.setHorizontalHeaderLabels(["Socket", "Bone", "Translation", "Rotation", "Scale"]); root.addWidget(self.table, 1); controls = QHBoxLayout(); add = QPushButton("+ Socket"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls); add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for raw in values.get("sockets") or []:
            data = dict(raw); transform = dict(data.get("transform") or {}); self._append(str(data.get("name") or "Socket"), str(data.get("bone") or data.get("parent_bone") or ""), transform.get("translation", [0, 0, 0]), transform.get("rotation", [0, 0, 0]), transform.get("scale", [1, 1, 1]))
        self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"sockets": [{"name": _table_text(self.table, row, 0), "bone": _table_text(self.table, row, 1), "transform": {"translation": _parse_vector(_table_text(self.table, row, 2), (0, 0, 0)), "rotation": _parse_vector(_table_text(self.table, row, 3), (0, 0, 0)), "scale": _parse_vector(_table_text(self.table, row, 4), (1, 1, 1))}} for row in range(self.table.rowCount())]}
    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).casefold() for row in range(self.table.rowCount())]
        return ["Skeleton socket names must be present and unique."] if any(not name for name in names) or len(names) != len(set(names)) else []
    def _append(self, name: str, bone: str, translation: Any, rotation: Any, scale: Any) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, bone, ",".join(map(str, translation)), ",".join(map(str, rotation)), ",".join(map(str, scale)))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"Socket{self.table.rowCount() + 1}", "", (0, 0, 0), (0, 0, 0), (1, 1, 1)); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkeletonRetargetPoseEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False; self.table = QTableWidget(0, 3, self); self.table.setHorizontalHeaderLabels(["Bone", "Translation Offset", "Rotation Offset"]); root.addWidget(self.table, 1); controls = QHBoxLayout(); add = QPushButton("+ Pose Offset"); remove = QPushButton("Delete"); controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls); add.clicked.connect(self._add); remove.clicked.connect(self._remove); self.table.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for bone, raw in dict(values.get("retarget_pose") or {}).items():
            data = dict(raw); self._append(str(bone), data.get("translation", [0, 0, 0]), data.get("rotation", [0, 0, 0]))
        self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"retarget_pose": {_table_text(self.table, row, 0): {"translation": _parse_vector(_table_text(self.table, row, 1), (0, 0, 0)), "rotation": _parse_vector(_table_text(self.table, row, 2), (0, 0, 0))} for row in range(self.table.rowCount()) if _table_text(self.table, row, 0)}}
    def _append(self, bone: str, translation: Any, rotation: Any) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((bone, ",".join(map(str, translation)), ",".join(map(str, rotation)))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append("root", (0, 0, 0), (0, 0, 0)); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkinDeformerStackEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); root = QVBoxLayout(self); self._loading = False; self.table = QTableWidget(0, 4, self); self.table.setHorizontalHeaderLabels(["Deformer", "Type", "Enabled", "Settings JSON"]); root.addWidget(self.table, 1); controls = QHBoxLayout(); add = QPushButton("+ Deformer"); remove = QPushButton("Delete"); up = QPushButton("Move Up"); controls.addWidget(add); controls.addWidget(remove); controls.addWidget(up); controls.addStretch(1); root.addLayout(controls); add.clicked.connect(self._add); remove.clicked.connect(self._remove); up.clicked.connect(self._up); self.table.itemChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        self._loading = True; self.table.setRowCount(0)
        for index, raw in enumerate(values.get("deformers") or []):
            data = dict(raw); self._append(str(data.get("name") or f"Deformer{index + 1}"), str(data.get("type") or "delta_mush"), bool(data.get("enabled", True)), data.get("settings") or {})
        self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"deformers": [{"name": _table_text(self.table, row, 0), "type": _table_text(self.table, row, 1) or "delta_mush", "enabled": _table_bool(self.table, row, 2), "settings": _json_value(_table_text(self.table, row, 3)) or {}} for row in range(self.table.rowCount())]}
    def validation_issues(self) -> list[str]:
        names = [_table_text(self.table, row, 0).casefold() for row in range(self.table.rowCount())]; return ["Skin deformer names must be unique."] if len(names) != len(set(names)) else []
    def _append(self, name: str, kind: str, enabled: bool, settings: Any) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((name, kind, "Yes" if enabled else "No", _json_text(settings))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
    def _add(self) -> None: self._append(f"Deformer{self.table.rowCount() + 1}", "delta_mush", True, {"iterations": 10}); self.changed.emit()
    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()
    def _up(self) -> None:
        row = self.table.currentRow()
        if row <= 0: return
        values = [_table_text(self.table, row, column) for column in range(4)]
        previous = [_table_text(self.table, row - 1, column) for column in range(4)]
        for column in range(4): self.table.item(row - 1, column).setText(values[column]); self.table.item(row, column).setText(previous[column])
        self.table.setCurrentCell(row - 1, 0); self.changed.emit()
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkinTransferEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False; self.source = QLineEdit(self); self.mode = QComboBox(self); self.mode.addItems(["topology", "closest_point", "uv", "cage"]); self.distance = QDoubleSpinBox(self); self.distance.setRange(0.0, 1.0e6); self.distance.setDecimals(6); self.normal_weight = QDoubleSpinBox(self); self.normal_weight.setRange(0.0, 1.0); self.unmatched = QComboBox(self); self.unmatched.addItems(["keep", "nearest", "root", "fail"])
        for label, widget in (("Source Skin Binding", self.source), ("Correspondence", self.mode), ("Maximum Distance", self.distance), ("Normal Weight", self.normal_weight), ("Unmatched Vertices", self.unmatched)): form.addRow(label, widget)
        self.source.textChanged.connect(self._edited); self.mode.currentTextChanged.connect(self._edited); self.distance.valueChanged.connect(self._edited); self.normal_weight.valueChanged.connect(self._edited); self.unmatched.currentTextChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        data = dict(values.get("transfer") or {}); self._loading = True; self.source.setText(str(data.get("source_skin_binding_id") or "")); self.mode.setCurrentText(str(data.get("mode") or "topology")); self.distance.setValue(float(data.get("maximum_distance", 0.01))); self.normal_weight.setValue(float(data.get("normal_weight", 0.5))); self.unmatched.setCurrentText(str(data.get("unmatched_policy") or "keep")); self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"transfer": {"source_skin_binding_id": self.source.text().strip(), "mode": self.mode.currentText(), "maximum_distance": self.distance.value(), "normal_weight": self.normal_weight.value(), "unmatched_policy": self.unmatched.currentText()}}
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


class SkinExportEditorWidget(QWidget):
    changed = Signal()
    def __init__(self, parent=None) -> None:
        super().__init__(parent); form = QFormLayout(self); self._loading = False; self.format = QComboBox(self); self.format.addItems(["tcskin", "fbx", "usd", "gltf", "json"]); self.max_influences = QSpinBox(self); self.max_influences.setRange(1, 32); self.bake = QCheckBox("Bake deformer stack into exported weights", self); self.include_names = QCheckBox("Include joint names", self); self.destination = QLineEdit(self)
        for label, widget in (("Format", self.format), ("Maximum Influences", self.max_influences), ("Deformers", self.bake), ("Joint Metadata", self.include_names), ("Destination", self.destination)): form.addRow(label, widget)
        self.format.currentTextChanged.connect(self._edited); self.max_influences.valueChanged.connect(self._edited); self.bake.toggled.connect(self._edited); self.include_names.toggled.connect(self._edited); self.destination.textChanged.connect(self._edited)
    def load_settings(self, values: dict[str, Any]) -> None:
        data = dict(values.get("export") or {}); self._loading = True; self.format.setCurrentText(str(data.get("format") or "tcskin")); self.max_influences.setValue(int(data.get("max_influences", values.get("max_influences", 4)))); self.bake.setChecked(bool(data.get("bake_deformers", False))); self.include_names.setChecked(bool(data.get("include_joint_names", True))); self.destination.setText(str(data.get("destination") or "")); self._loading = False
    def settings(self) -> dict[str, Any]:
        return {"export": {"format": self.format.currentText(), "max_influences": self.max_influences.value(), "bake_deformers": self.bake.isChecked(), "include_joint_names": self.include_names.isChecked(), "destination": self.destination.text().strip()}}
    def validation_issues(self) -> list[str]:
        return ["Choose an export destination before using a package-specific format."] if self.format.currentText() != "tcskin" and not self.destination.text().strip() else []
    def _edited(self, *_args) -> None:
        if not self._loading: self.changed.emit()


def _json_value(text: str) -> Any:
    value = str(text).strip()
    if not value: return None
    try: return json.loads(value)
    except Exception: return value


def _json_text(value: Any) -> str:
    if value is None: return ""
    if isinstance(value, str): return value
    return json.dumps(value, separators=(",", ":"))


def _is_int(value: Any) -> bool:
    try:
        int(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _safe_int(value: Any, default: int = 0) -> int:
    return int(str(value).strip()) if _is_int(value) else int(default)


def _is_float(value: Any) -> bool:
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _safe_float(value: Any, default: float = 0.0) -> float:
    return float(str(value).strip()) if _is_float(value) else float(default)


def _value_type(value: Any) -> str:
    if isinstance(value, bool): return "bool"
    if isinstance(value, int): return "int"
    if isinstance(value, float): return "float"
    if isinstance(value, (list, tuple)) and len(value) in {2, 3, 4}: return f"vector{len(value)}"
    return "string"


def _graph_has_cycle(node_ids: set[str], connections: list[dict[str, str]]) -> bool:
    outgoing = {node_id: [] for node_id in node_ids}
    for edge in connections:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in outgoing and target in node_ids:
            outgoing[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in outgoing.get(node_id, ())):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in node_ids)


def _decode_compressed_audio(path: str | Path) -> tuple[list[float], float]:
    executable = shutil.which("ffmpeg")
    if not executable or not Path(path).is_file():
        return [], 0.0
    try:
        result = subprocess.run(
            [
                executable, "-v", "error", "-i", str(path), "-t", "120",
                "-f", "f32le", "-ac", "1", "-ar", "8000", "pipe:1",
            ],
            capture_output=True, check=False, timeout=15.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], 0.0
    if result.returncode != 0 or len(result.stdout) < 4:
        return [], 0.0
    count = len(result.stdout) // 4
    stride = max(1, count // 12000)
    samples = [
        float(struct.unpack_from("<f", result.stdout, index * 4)[0])
        for index in range(0, count, stride)
    ]
    return samples, count / 8000.0
