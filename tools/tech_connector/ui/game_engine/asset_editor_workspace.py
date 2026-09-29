"""Consistent dedicated editor shell for first-class engine assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import (
    GRAPH_ASSET_TYPES, AssetDatabase, AssetGraphCompileService, AssetOperationsService,
    AssetProductionService, AssetTypeRegistry, GameplayClassService, MaterialService, PrefabService,
    WORLD_ASSET_TYPES, WorldAssetService, WorldBuildService,
    ProceduralGraphAssetService,
    asset_property_schema, builtin_asset_type_registry, read_asset_metadata, write_asset_metadata,
)
from tech_connector.ui.game_engine.asset_specialized_editors import (
    AssetCurveEditorWidget, AssetNodeGraphWidget, AudioWaveformEditorWidget, AudioMixerEditorWidget,
    AudioAttenuationEditorWidget, DopesheetEditorWidget,
    DataSchemaEditorWidget, ComponentArchetypeEditorWidget,
    GameplayClassDefinitionEditorWidget, GameplayClassDebuggerWidget,
    ProjectSettingsEditorWidget,
    CollisionGenerationEditorWidget, EmitterStackEditorWidget, MaterialPreviewEditorWidget,
    MaterialInstanceEditorWidget, MaterialCompileInspectorWidget, ShaderGeneratedCodeWidget,
    TextureInspectorEditorWidget,
    MeshLodEditorWidget, ProceduralIKEditorWidget, VehicleRigEditorWidget,
    InputMapEditorWidget, FxBudgetProfilerWidget, BuildProfileEditorWidget,
    ClothSetupEditorWidget, FabricMaterialEditorWidget, SkinWeightsEditorWidget,
    PhysicsAssetEditorWidget, PhysicsConstraintAssetEditorWidget,
    CharacterLodEditorWidget,
    IKRigEditorWidget, IKRetargeterEditorWidget,
    GeometryOptimizationEditorWidget,
    GroomEditorWidget, GroomBindingEditorWidget, HairMaterialEditorWidget,
    PrefabHierarchyEditorWidget,
    BlendSpaceEditorWidget,
    ProceduralGeometryPreviewWidget, ProceduralDiagnosticsWidget,
)
from tech_connector.ui.game_engine.asset_editor_session import AssetEditorSession
from tech_connector.ui.game_engine.sequence_editor import (
    SequenceBindingsEditorWidget, SequenceCurveEditorWidget, SequenceEditorWidget,
    SequenceRenderExportWidget,
)
from tech_connector.ui.game_engine.world_asset_editors import WorldAssetAuthoringWidget


EDITOR_PAGES: dict[str, tuple[str, ...]] = {
    "tc.procedural_graph": ("Graph", "Parameters", "Geometry Preview", "Cook & Cache", "Runtime Generation", "Interchange", "Diagnostics"),
    "tc.terrain": ("Sculpt", "Paint", "Layers", "Erosion", "LODs & Collision", "Build & Validate"),
    "tc.foliage_type": ("Placement", "Terrain Rules", "Instance LODs", "Collision & Navigation", "Wind", "Validation"),
    "tc.biome": ("Biome Preview", "Species", "Climate Rules", "Masks & Exclusions", "Generation", "Validation"),
    "tc.navigation_mesh": ("Navigation Preview", "Agents", "Areas & Costs", "Links", "Build", "Runtime Debug"),
    "tc.lighting_scenario": ("Lighting Preview", "Environment", "Lightmaps", "Reflections", "Build", "Diagnostics"),
    "tc.data_layer": ("Layer Contents", "Hierarchy", "Runtime State", "Outliner", "Validation"),
    "tc.hlod_layer": ("Clustering", "Proxy Generation", "Material Baking", "Transitions", "Build Report"),
    "tc.world_partition": ("World Grid", "Data Layers", "HLOD", "Streaming Sources", "Budgets", "Diagnostics"),
    "tc.level_sequence": ("Sequence", "Curve Editor", "Bindings", "Render & Export", "Validation"),
    "tc.project_settings": ("Project", "Startup", "Gameplay", "Rendering", "Physics", "Audio", "Build", "Platforms", "Validation"),
    "tc.static_mesh": ("Viewport", "Geometry", "LODs", "Materials", "Collision", "Import"),
    "tc.skeletal_mesh": ("Viewport", "Skeleton", "Skin", "Morphs", "LODs & Bone LODs", "Materials", "Import"),
    "tc.geometry_optimization_profile": ("Pipeline", "Material Baking", "Skinning", "Visibility & Culling", "Selection Sets", "Reports", "Batch & Distributed"),
    "tc.skeleton": ("Hierarchy", "Sockets", "Retarget Pose", "Validation"),
    "tc.skin_binding": ("Weights", "Deformers", "Transfer", "Export"),
    "tc.cloth": ("Setup & Paint", "Fabric Regions", "Seams", "Collision", "Simulation LODs", "Validate & Bake"),
    "tc.fabric_material": ("Fabric Properties", "Drape Preview", "Usage"),
    "tc.groom": ("Groups, Guides & LODs", "Viewport", "Cards & Meshes", "Materials", "Physics", "Interpolation", "Diagnostics", "Platform Overrides", "Import & Rebuild"),
    "tc.groom_binding": ("Binding Setup", "Root Projection", "Preview", "Validation"),
    "tc.hair_material": ("Fiber Properties", "Strand Preview", "Card Preview", "Usage"),
    "tc.physics_asset": ("Bodies & Constraints", "Collision", "Physical Animation", "Profiles", "Validate & Cook"),
    "tc.physics_constraint": ("Constraint Setup", "Limits & Drives", "Breakability", "Validate & Cook"),
    "tc.animation_clip": ("Timeline", "Curves", "Events", "Root Motion", "Compression"),
    "tc.blend_space": ("Blend Space", "Samples", "Axes", "Preview", "Diagnostics"),
    "tc.animation_mask": ("Skeleton", "Bone Weights", "Feathering", "Preview"),
    "tc.animation_controller": ("State Graph", "Parameters", "Transitions", "Debugger"),
    "tc.procedural_animation_profile": ("Rig Preview", "Ground IK", "Limb Setup", "Pelvis", "Runtime Debug"),
    "tc.control_rig": ("Rig Graph", "Controls", "Hierarchy", "Variables", "Rig LOD", "Debugger", "Validate & Bake"),
    "tc.ik_rig": ("Chains & Goals", "Solver Preview", "Excluded Bones", "Debug", "Validate & Cook"),
    "tc.ik_retargeter": ("Chain Mapping", "Retarget Poses", "Root Motion", "Preview", "Validate & Bake"),
    "tc.material": ("Preview", "Material Graph", "Parameters", "Compile", "Usage"),
    "tc.material_instance": ("Preview", "Parent & Overrides", "Parameters", "Permutation Cost"),
    "tc.shader_graph": ("Preview", "Shader Graph", "Generated Code", "Compile Targets", "Errors"),
    "tc.texture": ("Preview & Import", "Channels", "Mips", "Compression", "Usage"),
    "tc.effect_system": ("Viewport", "System Timeline", "Emitter Stack", "Modules", "Scalability", "Profiler"),
    "tc.simulation_profile": ("Viewport", "Solver Graph", "Domains", "Fields", "Cache", "Profiler"),
    "tc.physical_material": ("Surface Response", "Collision Preview", "Usage"),
    "tc.physics_scene": ("World Physics", "Gravity & Fields", "Collision Layers", "Solver", "Profiler"),
    "tc.vehicle_rig": ("Vehicle Preview", "Wheel Setup", "Suspension", "Steering & Drive", "Tire Response", "Runtime Debug"),
    "tc.audio_clip": ("Waveform", "Playback", "Loop & Trim", "Compression", "Spatial Preview"),
    "tc.sound_cue": ("Sound Graph", "Parameters", "Attenuation", "Concurrency", "Source Effects", "Profiler"),
    "tc.audio_mixer": ("Mixer", "DSP Chains", "Sends", "Snapshots", "Meters", "Profiler"),
    "tc.audio_attenuation": ("Distance", "Spatialization", "Occlusion", "Reverb Send", "Preview"),
    "tc.audio_reverb": ("Reverb", "Impulse Response", "Frequency Response", "Preview"),
    "tc.input_map": ("Actions", "Contexts", "Bindings", "Live Input Debug"),
    "tc.gameplay_graph": ("Components", "Event Graph", "Variables", "Debug"),
    "tc.gameplay_class": ("Class Definition", "Components", "Event Graph", "Debugger", "Validation"),
    "tc.data_schema": ("Fields", "Inheritance", "Defaults & Constraints", "Usage", "Validation"),
    "tc.struct": ("Fields", "Inheritance", "Defaults & Constraints", "Usage", "Validation"),
    "tc.enum": ("Entries", "Usage", "Validation"),
    "tc.data": ("Values", "Schema", "Bundles & Tags", "Usage", "Validation"),
    "tc.data_table": ("Table", "Row Schema", "Import & Export", "Usage", "Validation"),
    "tc.component_archetype": ("Component Hierarchy", "Exposed Properties", "Inheritance", "Replication", "Preview", "Validation"),
    "tc.character_definition": ("Character", "Component Setup", "Movement", "Animation", "Input & Camera", "Abilities & Attributes", "Networking", "Validation"),
    "tc.game_ruleset": ("Game Setup", "Player & Spawn", "Input", "Physics", "Validation"),
    "tc.build_profile": ("Target", "Included Levels", "Quality", "Validation", "Package Output"),
    "tc.prefab": ("Prefab Viewport", "Hierarchy", "Components", "Exposed Properties", "Overrides"),
}


class DedicatedAssetEditor(QWidget):
    previewRequested = Signal(str, str, str)
    locateRequested = Signal(str)
    statusMessage = Signal(str)
    worldVisualizationRequested = Signal(dict)

    def __init__(
        self,
        project_root: str | Path,
        database: AssetDatabase,
        registry: AssetTypeRegistry | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self.operations = AssetOperationsService(self.project_root, database, self.registry)
        self.production = AssetProductionService(self.project_root, database, self.registry)
        self.compiler = AssetGraphCompileService(database, self.registry)
        self.session = AssetEditorSession(self.project_root)
        self.asset_id = ""
        self._asset_display_name = ""
        self._mode = ""
        self._specialized_dirty = False
        self._applying_snapshot = False
        self._edit_capture_timer = QTimer(self)
        self._edit_capture_timer.setSingleShot(True)
        self._edit_capture_timer.setInterval(350)
        self._edit_capture_timer.timeout.connect(self._capture_edit_snapshot)
        self._specialized_widgets: list[tuple[str, QWidget]] = []
        self._build_ui()
        self._show_empty_state()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)
        header = QHBoxLayout()
        self.title_label = QLabel("Asset Editor")
        self.title_label.setStyleSheet("font-size:16px; font-weight:700; color:#eff9ff;")
        header.addWidget(self.title_label)
        self.type_badge = QLabel("NO ASSET")
        self.type_badge.setStyleSheet(
            "background:#172635; color:#91cff5; border:1px solid #29465e; border-radius:8px; padding:2px 8px; font-size:9px; font-weight:700;"
        )
        header.addWidget(self.type_badge)
        header.addStretch(1)
        self.save_button = QPushButton("Save")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.compile_button = QPushButton("Compile")
        self.reimport_button = QPushButton("Reimport")
        self.validate_button = QPushButton("Validate")
        self.references_button = QPushButton("References")
        self.locate_button = QPushButton("Locate in Assets")
        self.preview_button = QPushButton("Preview")
        self.preview_button.setObjectName("primaryAction")
        for button in (
            self.save_button, self.undo_button, self.redo_button, self.compile_button,
            self.reimport_button, self.validate_button,
            self.references_button, self.locate_button, self.preview_button,
        ):
            header.addWidget(button)
        root.addLayout(header)

        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color:#879dad; font-size:10px;")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.path_label)

        splitter = QSplitter(Qt.Horizontal, self)
        self.properties = QTreeWidget(splitter)
        self.properties.setHeaderLabels(["Property", "Value"])
        self.properties.setRootIsDecorated(False)
        self.properties.setAlternatingRowColors(True)
        self.properties.setMinimumWidth(310)
        splitter.addWidget(self.properties)
        self.pages = QTabWidget(splitter)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 900])
        root.addWidget(splitter, 1)
        self.diagnostics = QLabel("")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setStyleSheet("background:#0a121a; color:#9fb7c8; border:1px solid #1b3040; padding:6px;")
        root.addWidget(self.diagnostics)

        self.save_button.clicked.connect(self.save)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.compile_button.clicked.connect(self.compile)
        self.reimport_button.clicked.connect(self.reimport)
        self.validate_button.clicked.connect(self.validate)
        self.references_button.clicked.connect(self.show_references)
        self.locate_button.clicked.connect(lambda: self.locateRequested.emit(self.asset_id))
        self.preview_button.clicked.connect(self.preview)
        self.properties.itemChanged.connect(self._mark_specialized_dirty)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.Redo, self, activated=self.redo)
        QShortcut(QKeySequence.Save, self, activated=self.save)

    def open_asset(self, asset_id: str) -> bool:
        record = self.database.asset(asset_id)
        if record is None:
            self._show_error(f"The asset is no longer registered: {asset_id}")
            return False
        descriptor = self.registry.descriptor(record.asset_type)
        if descriptor is None:
            self._show_error(f"No editor descriptor is registered for {record.asset_type}.")
            return False
        if self.asset_id and self.asset_id != record.asset_id and self._edit_capture_timer.isActive():
            self._edit_capture_timer.stop()
            self._capture_edit_snapshot()
        self.asset_id = record.asset_id
        self._asset_display_name = record.source_path.name
        self.title_label.setText(self._asset_display_name)
        self.type_badge.setText(descriptor.display_name.upper())
        self.type_badge.setStyleSheet(
            f"background:#172635; color:{descriptor.color}; border:1px solid {descriptor.color}; border-radius:8px; padding:2px 8px; font-size:9px; font-weight:700;"
        )
        self.path_label.setText(str(record.source_path))
        self._applying_snapshot = True
        self._load_properties(record)
        self._build_type_pages(record, descriptor)
        self._applying_snapshot = False
        self._update_actions(record)
        self._specialized_dirty = False
        self.validate(silent=True)
        recovered = self.session.begin(record.asset_id, record.content_hash, self._collect_editor_values())
        if recovered is not None:
            self._apply_editor_values(recovered)
            self.diagnostics.setText("RECOVERED • Unsaved editor state was restored after the previous session.")
        self._update_session_actions()
        return True

    def _load_properties(self, record) -> None:
        self.properties.blockSignals(True)
        self.properties.clear()
        self._mode = ""
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        values = payload.get("properties") if isinstance(payload, dict) else None
        if isinstance(values, dict):
            self._mode = "authored"
        else:
            try:
                metadata = read_asset_metadata(record.source_path)
            except ValueError:
                metadata = {}
            values = metadata.get("importer_settings") if isinstance(metadata, dict) else None
            self._mode = "import" if isinstance(values, dict) else "readonly"
        schema = {item.key: item for item in asset_property_schema(record.asset_type)}
        for key, value in dict(values or {}).items():
            definition = schema.get(str(key))
            display = definition.display_name if definition else str(key).replace("_", " ").title()
            rendered = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list, bool)) or value is None else str(value)
            item = QTreeWidgetItem([display, rendered])
            item.setData(0, Qt.UserRole, str(key))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            if definition:
                item.setToolTip(0, definition.tooltip)
                item.setToolTip(1, definition.tooltip)
            self.properties.addTopLevelItem(item)
        if self.properties.topLevelItemCount() == 0:
            item = QTreeWidgetItem(["No editable properties", "Use the specialized pages or Reimport settings."])
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.properties.addTopLevelItem(item)
        self.properties.resizeColumnToContents(0)
        self.properties.blockSignals(False)
        self._specialized_dirty = False

    def _build_type_pages(self, record, descriptor) -> None:
        self.pages.clear()
        self._specialized_widgets = []
        values = self._current_asset_values(record)
        page_names = EDITOR_PAGES.get(record.asset_type, ("Overview", "Properties", "Dependencies"))
        metrics = self._asset_metrics(record)
        for index, name in enumerate(page_names):
            page = QFrame(self.pages)
            layout = QVBoxLayout(page)
            heading = QLabel(name)
            heading.setStyleSheet("font-size:15px; font-weight:700; color:#e7f6ff;")
            layout.addWidget(heading)
            specialized = self._specialized_page(record, name, values)
            if specialized is not None:
                layout.addWidget(specialized, 1)
            else:
                body = QLabel(self._page_guidance(record.asset_type, name, metrics))
                body.setWordWrap(True)
                body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                body.setStyleSheet("color:#9cb4c5; padding:8px;")
                layout.addWidget(body, 1)
            self.pages.addTab(page, name)
        self.pages.setCurrentIndex(0)

    def _current_asset_values(self, record) -> dict[str, Any]:
        if self._mode == "authored":
            try:
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return dict(payload.get("properties") or {})
        try:
            return dict(read_asset_metadata(record.source_path).get("importer_settings") or {})
        except ValueError:
            return {}

    def _specialized_page(self, record, page_name: str, values: dict[str, Any]) -> QWidget | None:
        if page_name == "Graph" and record.asset_type == "tc.procedural_graph":
            widget = AssetNodeGraphWidget("procedural_geometry", self)
            widget.load_graph(dict(values.get("graph") or {}))
            self._specialized_widgets.append(("graph", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Geometry Preview" and record.asset_type == "tc.procedural_graph":
            return ProceduralGeometryPreviewWidget(self.project_root, self.database, record.asset_id, self)
        if page_name == "Diagnostics" and record.asset_type == "tc.procedural_graph":
            return ProceduralDiagnosticsWidget(self.project_root, self.database, record.asset_id, self)
        world_primary_pages = {
            "tc.terrain": "Sculpt", "tc.foliage_type": "Placement", "tc.biome": "Biome Preview",
            "tc.navigation_mesh": "Navigation Preview", "tc.lighting_scenario": "Lighting Preview",
            "tc.data_layer": "Layer Contents", "tc.hlod_layer": "Clustering", "tc.world_partition": "World Grid",
        }
        if record.asset_type in world_primary_pages and page_name == world_primary_pages[record.asset_type]:
            widget = WorldAssetAuthoringWidget(
                WorldAssetService(self.project_root, self.database), record.asset_id, record.asset_type, self,
            )
            self._specialized_widgets.append(("__world_asset__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            widget.visualizationChanged.connect(self.worldVisualizationRequested)
            widget.load_settings(values)
            return widget
        if page_name == "Sequence" and record.asset_type == "tc.level_sequence":
            widget = SequenceEditorWidget(database=self.database, parent=self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__sequence__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Curve Editor" and record.asset_type == "tc.level_sequence":
            widget = SequenceCurveEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__sequence_curves__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Bindings" and record.asset_type == "tc.level_sequence":
            widget = SequenceBindingsEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__sequence_bindings__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Render & Export" and record.asset_type == "tc.level_sequence":
            widget = SequenceRenderExportWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__sequence_render__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Parent & Overrides" and record.asset_type == "tc.material_instance":
            widget = MaterialInstanceEditorWidget(self.project_root, self.database, record.asset_id, self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__material_instance__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Compile" and record.asset_type == "tc.material":
            widget = MaterialCompileInspectorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__material_compile__", widget))
            return widget
        if page_name == "Generated Code" and record.asset_type == "tc.shader_graph":
            widget = ShaderGeneratedCodeWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__shader_code__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Preview & Import" and record.asset_type == "tc.texture":
            widget = TextureInspectorEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__texture_import__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Hierarchy" and record.asset_type == "tc.prefab":
            widget = PrefabHierarchyEditorWidget(self.project_root, self.database, record.asset_id, self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__prefab__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Setup & Paint" and record.asset_type == "tc.cloth":
            widget = ClothSetupEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__cloth__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            widget.paint_requested.connect(
                lambda map_name: self.statusMessage.emit(
                    f"Preview this Cloth asset in Garden and choose {str(map_name).replace('_', ' ').title()} from Paint Target."
                )
            )
            return widget
        if page_name == "Fabric Properties" and record.asset_type == "tc.fabric_material":
            widget = FabricMaterialEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__fabric__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Bodies & Constraints" and record.asset_type == "tc.physics_asset":
            widget = PhysicsAssetEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__physics_asset__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Constraint Setup" and record.asset_type == "tc.physics_constraint":
            widget = PhysicsConstraintAssetEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__physics_constraint__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Chains & Goals" and record.asset_type == "tc.ik_rig":
            widget = IKRigEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__ik_rig__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Chain Mapping" and record.asset_type == "tc.ik_retargeter":
            widget = IKRetargeterEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__ik_retargeter__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Pipeline" and record.asset_type == "tc.geometry_optimization_profile":
            widget = GeometryOptimizationEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__geometry_optimization__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Groups, Guides & LODs" and record.asset_type == "tc.groom":
            widget = GroomEditorWidget(self); widget.load_settings(values)
            self._specialized_widgets.append(("__groom__", widget)); widget.changed.connect(self._mark_specialized_dirty); return widget
        if page_name == "Binding Setup" and record.asset_type == "tc.groom_binding":
            widget = GroomBindingEditorWidget(self); widget.load_settings(values)
            self._specialized_widgets.append(("__groom_binding__", widget)); widget.changed.connect(self._mark_specialized_dirty); return widget
        if page_name == "Fiber Properties" and record.asset_type == "tc.hair_material":
            widget = HairMaterialEditorWidget(self); widget.load_settings(values)
            self._specialized_widgets.append(("__hair_material__", widget)); widget.changed.connect(self._mark_specialized_dirty); return widget
        if page_name == "Preview" and record.asset_type == "tc.material":
            widget = MaterialPreviewEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__material_preview__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "LODs" and record.asset_type in {"tc.static_mesh", "tc.skeletal_mesh"}:
            widget = MeshLodEditorWidget(self)
            widget.load_lods(list(values.get("lods") or ()))
            self._specialized_widgets.append(("lods", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "LODs & Bone LODs" and record.asset_type == "tc.skeletal_mesh":
            widget = CharacterLodEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__character_lods__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Ground IK" and record.asset_type == "tc.procedural_animation_profile":
            widget = ProceduralIKEditorWidget(self)
            widget.load_limbs(list(values.get("limbs") or ()))
            self._specialized_widgets.append(("limbs", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Wheel Setup" and record.asset_type == "tc.vehicle_rig":
            widget = VehicleRigEditorWidget(self)
            widget.load_wheels(list(values.get("wheels") or ()))
            self._specialized_widgets.append(("wheels", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Bindings" and record.asset_type == "tc.input_map":
            widget = InputMapEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__input_map__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Profiler" and record.asset_type == "tc.effect_system":
            widget = FxBudgetProfilerWidget(self)
            widget.load_effect(values)
            self._specialized_widgets.append(("__fx_profiler__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Validation" and record.asset_type == "tc.build_profile":
            widget = BuildProfileEditorWidget(self.database, self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__build_profile__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Weights" and record.asset_type == "tc.skin_binding":
            widget = SkinWeightsEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__skin_weights__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Blend Space" and record.asset_type == "tc.blend_space":
            widget = BlendSpaceEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__blend_space__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        graph_pages = {
            "Material Graph": "material", "Shader Graph": "shader", "State Graph": "animation_state",
            "Event Graph": "gameplay", "Solver Graph": "simulation", "Components": "gameplay_components",
            "Rig Graph": "control_rig", "Sound Graph": "audio",
        }
        if page_name in graph_pages and not (record.asset_type == "tc.gameplay_class" and page_name == "Components"):
            widget = AssetNodeGraphWidget(graph_pages[page_name], self)
            widget.load_graph(dict(values.get("event_graph") or values.get("pose_graph") or values.get("graph") or values.get("solver_graph") or {}))
            key = "event_graph" if record.asset_type == "tc.gameplay_class" and page_name == "Event Graph" else ("solver_graph" if page_name == "Solver Graph" else ("pose_graph" if page_name == "State Graph" else "graph"))
            self._specialized_widgets.append((key, widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Curves":
            widget = AssetCurveEditorWidget(self)
            widget.load_keys(list(values.get("curves") or ()))
            self._specialized_widgets.append(("curves", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Timeline" and record.asset_type == "tc.animation_clip":
            widget = DopesheetEditorWidget(self)
            widget.load_events(list(values.get("events") or ()))
            self._specialized_widgets.append(("events", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Waveform":
            widget = AudioWaveformEditorWidget(self)
            widget.load_audio(record.source_path, values)
            self._specialized_widgets.append(("audio_edit", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Mixer" and record.asset_type == "tc.audio_mixer":
            widget = AudioMixerEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__audio_mixer__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Distance" and record.asset_type == "tc.audio_attenuation":
            widget = AudioAttenuationEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__audio_attenuation__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Fields" and record.asset_type in {"tc.data_schema", "tc.struct"}:
            widget = DataSchemaEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__data_schema__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Project" and record.asset_type == "tc.project_settings":
            widget = ProjectSettingsEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__project_settings__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Component Hierarchy" and record.asset_type == "tc.component_archetype":
            widget = ComponentArchetypeEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__component_archetype__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Class Definition" and record.asset_type == "tc.gameplay_class":
            widget = GameplayClassDefinitionEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__gameplay_class__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Components" and record.asset_type == "tc.gameplay_class":
            widget = ComponentArchetypeEditorWidget(self)
            widget.load_settings(values)
            self._specialized_widgets.append(("__gameplay_components__", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name == "Debugger" and record.asset_type == "tc.gameplay_class":
            return GameplayClassDebuggerWidget(self.project_root, self.database, record.asset_id, self)
        if page_name == "Emitter Stack":
            widget = EmitterStackEditorWidget(self)
            widget.load_emitters(list(values.get("emitters") or ()))
            self._specialized_widgets.append(("emitters", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        if page_name in {"Collision", "Collision Preview"}:
            widget = CollisionGenerationEditorWidget(self)
            widget.load_settings(dict(values.get("collision") or {}))
            self._specialized_widgets.append(("collision", widget))
            widget.changed.connect(self._mark_specialized_dirty)
            return widget
        return None

    def _mark_specialized_dirty(self, *args) -> None:
        if self._applying_snapshot:
            return
        if args and isinstance(args[0], QTreeWidgetItem):
            properties = self._property_tree_values()
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, MaterialPreviewEditorWidget):
                    preview_values = widget.settings()
                    for key in ("base_color", "roughness", "metalness"):
                        if key in properties:
                            preview_values[key] = properties[key]
                    widget.load_settings(preview_values)
                elif isinstance(widget, InputMapEditorWidget):
                    widget.load_settings(properties)
                elif isinstance(widget, FxBudgetProfilerWidget):
                    widget.load_effect(properties)
                elif isinstance(widget, BuildProfileEditorWidget):
                    widget.load_settings(properties)
                elif isinstance(widget, SkinWeightsEditorWidget):
                    widget.load_settings(properties)
        sender = self.sender()
        if isinstance(sender, SequenceEditorWidget):
            sequence_values = sender.settings()
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, (SequenceCurveEditorWidget, SequenceBindingsEditorWidget, SequenceRenderExportWidget)):
                    widget.load_settings(sequence_values)
        elif isinstance(sender, SequenceBindingsEditorWidget):
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, SequenceEditorWidget):
                    widget._values["bindings"] = sender.bindings()
                    widget._rebuild()
        elif isinstance(sender, SequenceRenderExportWidget):
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, SequenceEditorWidget):
                    widget._values["render_settings"] = sender.render_settings()
        if isinstance(sender, (AssetNodeGraphWidget, MaterialPreviewEditorWidget)):
            values = self._collect_editor_values()
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, MaterialCompileInspectorWidget):
                    widget.load_settings(values)
                elif isinstance(widget, ShaderGeneratedCodeWidget):
                    widget.load_settings(values)
        if isinstance(sender, EmitterStackEditorWidget):
            effect_values = self._property_tree_values()
            effect_values["emitters"] = sender.emitters()
            for _key, widget in self._specialized_widgets:
                if isinstance(widget, FxBudgetProfilerWidget):
                    effect_values["scalability"] = widget.scalability()
                    widget.load_effect(effect_values)
        self._specialized_dirty = True
        self.diagnostics.setText("UNSAVED • Specialized editor values changed. Save to update the asset and invalidate its cook.")
        self._edit_capture_timer.start()

    def apply_world_viewport_stroke(self, u: float, v: float, erase: bool = False) -> bool:
        for _key, widget in self._specialized_widgets:
            if isinstance(widget, WorldAssetAuthoringWidget) and widget.type_id in {"tc.terrain", "tc.foliage_type"}:
                widget._stroke(float(u), float(v), bool(erase))
                return True
        return False

    def _collect_editor_values(self) -> dict[str, Any]:
        values = self._property_tree_values()
        for key, widget in self._specialized_widgets:
            if isinstance(widget, AssetNodeGraphWidget):
                values[key] = widget.graph()
            elif isinstance(widget, AssetCurveEditorWidget):
                values[key] = widget.keys()
            elif isinstance(widget, DopesheetEditorWidget):
                values[key] = widget.events()
            elif isinstance(widget, AudioWaveformEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, SequenceEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, SequenceCurveEditorWidget):
                widget.apply_to(values)
            elif isinstance(widget, SequenceBindingsEditorWidget):
                values["bindings"] = widget.bindings()
            elif isinstance(widget, SequenceRenderExportWidget):
                values["render_settings"] = widget.render_settings()
            elif isinstance(widget, (AudioMixerEditorWidget, AudioAttenuationEditorWidget)):
                values.update(widget.settings())
            elif isinstance(widget, (DataSchemaEditorWidget, ComponentArchetypeEditorWidget, GameplayClassDefinitionEditorWidget, ProjectSettingsEditorWidget)):
                values.update(widget.settings())
            elif isinstance(widget, EmitterStackEditorWidget):
                values[key] = widget.emitters()
            elif isinstance(widget, CollisionGenerationEditorWidget):
                values[key] = widget.settings()
            elif isinstance(widget, BlendSpaceEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, MaterialPreviewEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, MeshLodEditorWidget):
                values[key] = widget.lods()
            elif isinstance(widget, ProceduralIKEditorWidget):
                values[key] = widget.limbs()
            elif isinstance(widget, VehicleRigEditorWidget):
                values[key] = widget.wheels()
            elif isinstance(widget, InputMapEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, FxBudgetProfilerWidget):
                values["scalability"] = widget.scalability()
            elif isinstance(widget, BuildProfileEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, SkinWeightsEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, ClothSetupEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, FabricMaterialEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, PhysicsAssetEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, PhysicsConstraintAssetEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, CharacterLodEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, IKRigEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, IKRetargeterEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, GeometryOptimizationEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, (GroomEditorWidget, GroomBindingEditorWidget, HairMaterialEditorWidget)):
                values.update(widget.settings())
            elif isinstance(widget, PrefabHierarchyEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, MaterialInstanceEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, TextureInspectorEditorWidget):
                values.update(widget.settings())
            elif isinstance(widget, ShaderGeneratedCodeWidget):
                values.update(widget.settings())
            elif isinstance(widget, WorldAssetAuthoringWidget):
                values.update(widget.settings())
        return values

    def _property_tree_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for index in range(self.properties.topLevelItemCount()):
            item = self.properties.topLevelItem(index)
            key = str(item.data(0, Qt.UserRole) or "")
            if not key:
                continue
            raw = item.text(1).strip()
            try:
                values[key] = json.loads(raw)
            except json.JSONDecodeError:
                values[key] = raw
        return values

    def _capture_edit_snapshot(self) -> None:
        if not self.asset_id or self._applying_snapshot:
            return
        values = self._collect_editor_values()
        self.session.record(values, "Edit Asset")
        self.session.write_recovery(values)
        self._update_session_actions()

    def _apply_editor_values(self, values: dict[str, Any]) -> None:
        self._applying_snapshot = True
        self.properties.blockSignals(True)
        for index in range(self.properties.topLevelItemCount()):
            item = self.properties.topLevelItem(index)
            key = str(item.data(0, Qt.UserRole) or "")
            if key not in values:
                continue
            value = values[key]
            rendered = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list, bool)) or value is None else str(value)
            item.setText(1, rendered)
        self.properties.blockSignals(False)
        record = self.database.asset(self.asset_id)
        for key, widget in self._specialized_widgets:
            value = values.get(key)
            if isinstance(widget, AssetNodeGraphWidget):
                widget.load_graph(dict(value or {}))
            elif isinstance(widget, AssetCurveEditorWidget):
                widget.load_keys(list(value or ()))
            elif isinstance(widget, DopesheetEditorWidget):
                widget.load_events(list(value or ()))
            elif isinstance(widget, AudioWaveformEditorWidget) and record is not None:
                widget.load_audio(record.source_path, values)
            elif isinstance(widget, SequenceEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, (SequenceCurveEditorWidget, SequenceBindingsEditorWidget, SequenceRenderExportWidget)):
                widget.load_settings(values)
            elif isinstance(widget, WorldAssetAuthoringWidget):
                widget.load_settings(values)
            elif isinstance(widget, (AudioMixerEditorWidget, AudioAttenuationEditorWidget)):
                widget.load_settings(values)
            elif isinstance(widget, (DataSchemaEditorWidget, ComponentArchetypeEditorWidget, GameplayClassDefinitionEditorWidget, ProjectSettingsEditorWidget)):
                widget.load_settings(values)
            elif isinstance(widget, EmitterStackEditorWidget):
                widget.load_emitters(list(value or ()))
            elif isinstance(widget, CollisionGenerationEditorWidget):
                widget.load_settings(dict(value or {}))
            elif isinstance(widget, MaterialPreviewEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, MeshLodEditorWidget):
                widget.load_lods(list(value or ()))
            elif isinstance(widget, ProceduralIKEditorWidget):
                widget.load_limbs(list(value or ()))
            elif isinstance(widget, VehicleRigEditorWidget):
                widget.load_wheels(list(value or ()))
            elif isinstance(widget, InputMapEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, FxBudgetProfilerWidget):
                widget.load_effect(values)
            elif isinstance(widget, BuildProfileEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, SkinWeightsEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, ClothSetupEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, FabricMaterialEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, PhysicsAssetEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, PhysicsConstraintAssetEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, CharacterLodEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, IKRigEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, IKRetargeterEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, PrefabHierarchyEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, MaterialInstanceEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, MaterialCompileInspectorWidget):
                widget.load_settings(values)
            elif isinstance(widget, TextureInspectorEditorWidget):
                widget.load_settings(values)
            elif isinstance(widget, ShaderGeneratedCodeWidget):
                widget.load_settings(values)
        self._applying_snapshot = False
        self._specialized_dirty = self.session.dirty
        self._update_session_actions()

    def undo(self) -> bool:
        self._edit_capture_timer.stop()
        self._capture_edit_snapshot()
        values = self.session.undo()
        if values is None:
            return False
        self._apply_editor_values(values)
        self.session.write_recovery(values)
        self.diagnostics.setText("UNDO • Restored the previous editor state.")
        return True

    def redo(self) -> bool:
        self._edit_capture_timer.stop()
        values = self.session.redo()
        if values is None:
            return False
        self._apply_editor_values(values)
        self.session.write_recovery(values)
        self.diagnostics.setText("REDO • Reapplied the editor state.")
        return True

    def _update_session_actions(self) -> None:
        self.undo_button.setEnabled(self.session.can_undo)
        self.redo_button.setEnabled(self.session.can_redo)
        self.undo_button.setText(f"Undo {self.session.undo_label}" if self.session.can_undo else "Undo")
        self.redo_button.setText(f"Redo {self.session.redo_label}" if self.session.can_redo else "Redo")
        self.title_label.setText(f"{self._asset_display_name}{' *' if self.session.dirty else ''}")

    def _asset_metrics(self, record) -> dict[str, Any]:
        return {
            "size": int(record.size), "revision": int(record.revision),
            "dependencies": len(self.database.dependencies(record.asset_id)),
            "referencers": len(self.database.referencers(record.asset_id)),
        }

    @staticmethod
    def _page_guidance(type_id: str, page: str, metrics: dict[str, Any]) -> str:
        if page in {"Viewport", "Preview", "Prefab Viewport", "Waveform", "Timeline"}:
            return "Interactive preview uses the same authored asset and runtime loader as Garden/Kingdom. Use Preview to open the live contextual surface."
        if page in {"Compile", "Validation", "Errors", "Profiler", "Package Output"}:
            return "Run Validate for actionable diagnostics. Cook Selection in Assets produces the dependency-closed runtime manifest."
        return (
            f"Type workspace: {type_id}\n\nSource size: {metrics['size'] / 1024:.1f} KiB\n"
            f"Revision: {metrics['revision']}\nDependencies: {metrics['dependencies']}\n"
            f"Referencers: {metrics['referencers']}\n\nEdit common values in the property panel. Advanced controls remain grouped on this page."
        )

    def _update_actions(self, record) -> None:
        self.save_button.setEnabled(self._mode in {"authored", "import"})
        compilable = record.asset_type in GRAPH_ASSET_TYPES | {"tc.effect_system", "tc.animation_clip", "tc.prefab", "tc.gameplay_class", "tc.procedural_graph"} | WORLD_ASSET_TYPES
        self.compile_button.setEnabled(self._mode == "authored" and compilable)
        source = str(record.metadata.get("import_source") or "")
        self.reimport_button.setEnabled(bool(source and Path(source).is_file()))
        for button in (self.validate_button, self.references_button, self.locate_button, self.preview_button):
            button.setEnabled(True)

    def save(self, _checked: bool = False, *, compile_after: bool = True) -> bool:
        record = self.database.asset(self.asset_id)
        if record is None or self._mode not in {"authored", "import"}:
            return False
        self._edit_capture_timer.stop()
        values = self._collect_editor_values()
        updated = None
        if self._mode == "authored" and record.asset_type == "tc.gameplay_class":
            try:
                GameplayClassService(self.project_root, self.database).update(record.asset_id, values, replace=True)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            updated = self.database.asset(record.asset_id)
        elif self._mode == "authored":
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
            payload["properties"] = values
            record.source_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            metadata = record.metadata
        else:
            sidecar = read_asset_metadata(record.source_path)
            write_asset_metadata(
                record.source_path, asset_id=record.asset_id, type_id=record.asset_type,
                importer=str(sidecar.get("importer") or ""), importer_settings=values,
                previous_paths=list(sidecar.get("previous_paths") or ()),
            )
            metadata = {**record.metadata, "importer_settings": values}
        if updated is None:
            updated = self.database.register_asset(
                record.source_path, record.asset_type, asset_id=record.asset_id,
                metadata=metadata, dependencies=self.database.dependency_edges(record.asset_id),
            )
        if updated.asset_type == "tc.prefab":
            PrefabService(self.project_root, self.database).rebuild_dependencies(updated.asset_id)
            updated = self.database.asset(updated.asset_id) or updated
        if updated.asset_type in {"tc.material", "tc.material_instance"}:
            MaterialService(self.project_root, self.database).rebuild_dependencies(updated.asset_id)
            updated = self.database.asset(updated.asset_id) or updated
        if updated.asset_type == "tc.shader_graph":
            include_ids = [
                str(value) for value in values.get("include_asset_ids") or ()
                if self.database.asset(str(value)) is not None
            ]
            self.database.set_dependencies(updated.asset_id, [(value, "shader_include") for value in include_ids])
            updated = self.database.asset(updated.asset_id) or updated
        if updated.asset_type in WORLD_ASSET_TYPES:
            WorldAssetService(self.project_root, self.database).update(updated.asset_id, values, replace=True)
            updated = self.database.asset(updated.asset_id) or updated
        if updated.asset_type == "tc.procedural_graph":
            ProceduralGraphAssetService(self.project_root, self.database).update(updated.asset_id, values, replace=True)
            updated = self.database.asset(updated.asset_id) or updated
        self.statusMessage.emit(f"Saved {updated.source_path.name}; {self.registry.require(updated.asset_type).hot_reload_class.replace('_', ' ')} update ready.")
        self.session.source_hash = updated.content_hash
        self.session.mark_saved(values)
        self._specialized_dirty = False
        self._update_session_actions()
        self.validate(silent=True)
        if compile_after and updated.asset_type in GRAPH_ASSET_TYPES | {"tc.effect_system", "tc.animation_clip", "tc.prefab", "tc.gameplay_class", "tc.procedural_graph"} | WORLD_ASSET_TYPES:
            self.compile(auto_save=False, silent=True)
        return True

    def compile(
        self, _checked: bool = False, *, auto_save: bool = True, silent: bool = False,
    ) -> bool:
        if not self.asset_id:
            return False
        if auto_save and self._specialized_dirty and not self.save(compile_after=False):
            return False
        record = self.database.asset(self.asset_id)
        if record is not None and record.asset_type in {"tc.material", "tc.material_instance"}:
            try:
                if record.asset_type == "tc.material":
                    graph_receipt = self.compiler.compile_asset(self.asset_id)
                    if not graph_receipt.succeeded:
                        raise ValueError("; ".join(item.message for item in graph_receipt.diagnostics if item.severity == "error"))
                artifact = MaterialService(self.project_root, self.database).compile(self.asset_id)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            self.diagnostics.setText(f"COMPILED • Material runtime • {artifact.path.name}")
            self.statusMessage.emit(f"Compiled {record.source_path.name}: material runtime and shader permutation are ready.")
            return True
        if record is not None and record.asset_type == "tc.prefab":
            try:
                artifact = PrefabService(self.project_root, self.database).cook(self.asset_id)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            self.diagnostics.setText(f"COMPILED • Resolved Prefab runtime • {artifact.path.name}")
            self.statusMessage.emit(f"Compiled {record.source_path.name}: Prefab runtime is ready.")
            return True
        if record is not None and record.asset_type == "tc.gameplay_class":
            try:
                artifact = GameplayClassService(self.project_root, self.database).compile(self.asset_id)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            self.diagnostics.setText(f"COMPILED • Gameplay Class runtime • {artifact.path.name}")
            self.statusMessage.emit(f"Compiled {record.source_path.name}: inherited class and event graph are runtime ready.")
            return True
        if record is not None and record.asset_type in WORLD_ASSET_TYPES:
            try:
                artifact = WorldAssetService(self.project_root, self.database).compile(self.asset_id)
                built = None
                if record.asset_type in {"tc.terrain", "tc.navigation_mesh", "tc.lighting_scenario", "tc.hlod_layer", "tc.world_partition"}:
                    built = WorldBuildService(self.project_root, self.database).build(self.asset_id)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            backend = f" • {built.build_kind}: {built.statistics}" if built is not None else ""
            self.diagnostics.setText(f"BUILT • {self.registry.require(record.asset_type).display_name} runtime • {artifact.path.name}{backend}")
            self.statusMessage.emit(f"Built {record.source_path.name}: validated world-production data is runtime ready.")
            return True
        if record is not None and record.asset_type == "tc.procedural_graph":
            try:
                artifact = ProceduralGraphAssetService(self.project_root, self.database).cook(self.asset_id)
            except Exception as exc:
                self._show_error(str(exc))
                return False
            self.diagnostics.setText(f"COOKED • Procedural geometry runtime • {artifact.path.name}")
            self.statusMessage.emit(f"Cooked {record.source_path.name}: procedural geometry is runtime ready.")
            return True
        try:
            receipt = self.compiler.compile_asset(self.asset_id)
        except Exception as exc:
            self._show_error(str(exc))
            return False
        diagnostics = [
            f"[{item.severity.upper()}] {item.message}{f' • {item.subject}' if item.subject else ''}"
            for item in receipt.diagnostics
        ]
        if receipt.succeeded:
            diagnostics.append(
                f"COMPILED • {receipt.operation_count} operation(s) • {receipt.artifact.path.name}"
            )
            self.statusMessage.emit(
                f"Compiled {Path(self.path_label.text()).name}: {receipt.operation_count} runtime operation(s)."
            )
        self.diagnostics.setText("\n".join(diagnostics) or "Compiled without diagnostics.")
        if not silent and not receipt.succeeded:
            QMessageBox.warning(self, "Asset Compile Failed", self.diagnostics.text())
        return receipt.succeeded

    def reimport(self) -> bool:
        try:
            receipt = self.operations.reimport_asset(self.asset_id)
        except Exception as exc:
            self._show_error(str(exc))
            return False
        self.statusMessage.emit(receipt.message)
        return self.open_asset(receipt.asset_id)

    def validate(self, *, silent: bool = False) -> bool:
        if not self.asset_id:
            return False
        report = self.operations.validate_asset(self.asset_id)
        specialized_issues = []
        record = self.database.asset(self.asset_id)
        if record is not None and record.asset_type == "tc.gameplay_class":
            specialized_issues.extend(
                item.message for item in GameplayClassService(self.project_root, self.database).validate(self.asset_id)
                if item.severity == "error"
            )
        for _key, widget in self._specialized_widgets:
            validator = getattr(widget, "validation_issues", None)
            if callable(validator):
                specialized_issues.extend(str(value) for value in validator())
        if report.issues or specialized_issues:
            lines = [f"[{item.severity.upper()}] {item.message}" for item in report.issues]
            lines.extend(f"[ERROR] {message}" for message in specialized_issues)
            text = "\n".join(lines)
        else:
            text = "Ready • identity, source, dependencies, and import provenance are valid."
        self.diagnostics.setText(text)
        if not silent:
            QMessageBox.information(self, "Asset Validation", text)
        return report.valid and not specialized_issues

    def show_references(self) -> None:
        report = self.operations.reference_report(self.asset_id)
        lines = [f"Uses ({len(report['dependencies'])})"]
        lines.extend(f"  • {Path(item['path']).name}" for item in report["dependencies"])
        lines.append(f"\nUsed by ({len(report['referencers'])})")
        lines.extend(f"  • {Path(item['path']).name}" for item in report["referencers"])
        QMessageBox.information(self, "Asset References", "\n".join(lines))

    def preview(self) -> None:
        record = self.database.asset(self.asset_id)
        if record is not None:
            self.previewRequested.emit(str(record.source_path), record.asset_type, record.asset_id)

    def _show_empty_state(self) -> None:
        self.title_label.setText("Asset Editor")
        self.path_label.setText("Open an asset from Assets to begin.")
        self.properties.clear()
        self.pages.clear()
        page = QLabel("No asset selected\n\nDouble-click an asset in Assets. The correct specialized editor will open here.")
        page.setAlignment(Qt.AlignCenter)
        page.setStyleSheet("color:#8197a8;")
        self.pages.addTab(page, "Welcome")
        self.diagnostics.setText("Waiting for an asset.")
        for button in (
            self.save_button, self.undo_button, self.redo_button, self.compile_button,
            self.reimport_button, self.validate_button, self.references_button,
            self.locate_button, self.preview_button,
        ):
            button.setEnabled(False)

    def _show_error(self, message: str) -> None:
        self.diagnostics.setText(f"ERROR • {message}")
        QMessageBox.warning(self, "Asset Editor", str(message))


def editor_pages_for_asset(type_id: str) -> tuple[str, ...]:
    return EDITOR_PAGES.get(str(type_id).casefold(), ("Overview", "Properties", "Dependencies"))
