"""Project-scoped Python API mirroring asset-editor operations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService
from .asset_production_service import AssetCookReceipt, AssetProductionService
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry
from .asset_metadata_service import read_asset_metadata, write_asset_metadata
from .asset_graph_compile_service import AssetGraphCompileService
from .asset_export_service import AssetExportService
from .cloth_asset_service import (
    CLOTH_MAPS,
    automatic_cloth_maps,
    compile_cloth_payload,
    fabric_preset,
    validate_cloth_properties,
)
from .physics_asset_service import (
    automatic_physics_asset,
    compile_constraint_payload,
    compile_physics_asset_payload,
    constraint_from_preset,
    validate_constraint_properties,
    validate_physics_asset_properties,
)
from .character_asset_service import (
    compile_skeletal_mesh_plan,
    compile_skin_binding_payload,
    generate_bone_lods,
    recommended_mesh_lods,
    validate_character_lods,
    validate_skin_binding_properties,
)
from .rig_asset_service import (
    automatic_chain_mapping,
    automatic_ik_chains,
    compile_rig_asset_payload,
    validate_control_rig_properties,
    validate_ik_retargeter_properties,
    validate_ik_rig_properties,
)
from .mesh_lod_generation_service import CharacterMeshLodLevel, CharacterMeshLodRequest, generate_character_mesh_lods
from .geometry_optimization_service import (
    compile_geometry_optimization_payload, geometry_optimization_preset,
    plan_geometry_optimization, validate_geometry_optimization_profile,
)
from .groom_asset_service import (
    automatic_groom_lods, compile_groom_binding_payload, compile_groom_payload,
    compile_hair_material_payload, groom_group_preset, hair_material_preset, project_groom_roots,
    validate_groom_binding_properties, validate_groom_properties, validate_hair_material_properties,
)
from .locomotion_service import (
    compile_locomotion_payload, locomotion_preset, validate_locomotion_controller,
)
from .starter_character_service import StarterCharacterService
from .prefab_service import PrefabService
from .material_asset_service import MaterialService, analyze_material_graph, material_preset, shader_backend_capabilities
from .animation_asset_service import AnimationAssetService
from .effect_asset_service import EffectAssetService
from .audio_asset_service import AudioAssetService, AUDIO_ASSET_TYPES
from .sequence_asset_service import (
    SequenceAssetService, add_channel_key, build_render_jobs, evaluate_channel, evaluate_sequence,
    native_to_unity_timeline, native_to_unreal_level_sequence,
    new_binding, new_level_blend_section, new_section, new_track, track_preset, unity_timeline_to_native,
    unreal_level_sequence_to_native,
)
from .gameplay_foundation_service import GameplayFoundationService, GAMEPLAY_FOUNDATION_TYPES
from .gameplay_class_service import GameplayClassService
from .behavior_graph_asset_service import BehaviorGraphAssetService, BEHAVIOR_GRAPH_TYPES
from .image_project_asset_service import ImageProjectAssetService
from .world_asset_service import (
    WORLD_ASSET_TYPES, WorldAssetService, apply_foliage_brush, apply_terrain_brush,
    build_hlod_preview, build_lighting_preview, build_navigation_preview,
    build_partition_preview, build_terrain_preview,
)
from .world_build_service import WorldBuildService
from .procedural_graph_asset_service import ProceduralGraphAssetService
from tech_connector.game_engine.authoring.procedural_generation_service import ProceduralGraph
from tech_connector.game_engine.authoring.procedural_graph_tooling_service import (
    ProceduralSimulationSession, build_procedural_execution_plan,
)
from tech_connector.game_engine.authoring.procedural_task_graph_service import ProceduralTaskCooker, ProceduralTaskGraph
from tech_connector.game_engine.integration.procedural_native_serializer_service import (
    deserialize_native_procedural_graph, serialize_native_procedural_graph,
)
from tech_connector.game_engine.runtime.world_streaming_runtime_service import WorldStreamingRuntime
from tech_connector.game_engine.runtime.graph_debugger_service import default_graph_debug_session_manager
from tech_connector.game_engine.authoring.tc_physics_joint_service import create_physics_joint, remove_physics_joint
from tech_connector.game_engine.authoring.tc_physics_joint_editor_service import PhysicsJointEditorModel
from tech_connector.game_engine.authoring.tc_ragdoll_service import generate_ragdoll
from tech_connector.game_engine.runtime.tc_physics_stress_service import audit_physics_stress_scene, build_physics_stress_scene
from tech_connector.game_engine.runtime.tc_simulation_service import create_soft_body_from_geometry
from tech_connector.game_engine.runtime.tc_ocean_surface_service import OceanSurface, create_ocean_surface


class TCEditorAPI:
    """Stable Python surface used by the UI, scripts, tests, and assisted workflows."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        database: AssetDatabase | None = None,
        registry: AssetTypeRegistry | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or builtin_asset_type_registry()
        self.database = database or AssetDatabase(self.project_root / ".tech_connector" / "assets.sqlite3")
        self.assets = AssetOperationsService(self.project_root, self.database, self.registry)
        self.exports = AssetExportService(self.project_root, self.database)
        self.production = AssetProductionService(self.project_root, self.database, self.registry)
        self.prefabs = PrefabService(self.project_root, self.database)
        self.materials = MaterialService(self.project_root, self.database)
        self.animation = AnimationAssetService(self.project_root, self.database)
        self.effects = EffectAssetService(self.project_root, self.database)
        self.audio = AudioAssetService(self.project_root, self.database)
        self.sequence = SequenceAssetService(self.project_root, self.database)
        self.gameplay = GameplayFoundationService(self.project_root, self.database)
        self.gameplay_classes = GameplayClassService(self.project_root, self.database)
        self.behavior_graphs = BehaviorGraphAssetService(self.project_root, self.database)
        self.image_projects = ImageProjectAssetService(self.project_root, self.database)
        self.world = WorldAssetService(self.project_root, self.database)
        self.world_builds = WorldBuildService(self.project_root, self.database)
        self.procedural = ProceduralGraphAssetService(self.project_root, self.database)
        self._procedural_simulations: dict[str, ProceduralSimulationSession] = {}
        self.gameplay_debug_sessions = default_graph_debug_session_manager()

    def create_asset(self, type_id: str, name: str, *, folder: str | Path = "Assets", properties: Mapping[str, Any] | None = None):
        return self.assets.create_asset(type_id, name, folder=folder, properties=dict(properties or {}))

    def create_world_asset(
        self, type_id: str, name: str, *, folder: str | Path = "Assets/World",
        properties: Mapping[str, Any] | None = None,
    ):
        """Create Terrain, Foliage, Biome, Navigation, Lighting, Data Layer, HLOD, or World Partition data."""
        return self.world.create(type_id, name, folder=folder, properties=properties)

    def get_world_asset(self, asset_id: str) -> dict[str, Any]:
        return self.world.properties(asset_id)

    def update_world_asset(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        return self.world.update(asset_id, values, replace=replace)

    def validate_world_asset(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.world.validate(asset_id)]

    def preview_world_asset(self, asset_id: str, *, maximum_resolution: int = 257) -> dict[str, Any]:
        return self.world.build_preview(asset_id, maximum_resolution=maximum_resolution)

    def compile_world_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.world.compile(asset_id, platform=platform, quality=quality)

    def sculpt_terrain(
        self, asset_id: str, *, center: tuple[float, float], radius: float,
        strength: float, mode: str = "raise", target_height: float | None = None,
    ) -> dict[str, Any]:
        values = apply_terrain_brush(self.world.properties(asset_id), center=center, radius=radius,
                                     strength=strength, mode=mode, target_height=target_height)
        return self.world.update(asset_id, values, replace=True)

    def paint_terrain_layer(
        self, asset_id: str, layer: str, *, center: tuple[float, float], radius: float,
        strength: float,
    ) -> dict[str, Any]:
        values = apply_terrain_brush(self.world.properties(asset_id), center=center, radius=radius,
                                     strength=strength, mode="paint", layer=layer)
        return self.world.update(asset_id, values, replace=True)

    def paint_foliage(
        self, asset_id: str, *, center: tuple[float, float], radius: float,
        density: float = 1.0, erase: bool = False, seed: int = 0,
    ) -> dict[str, Any]:
        values = apply_foliage_brush(self.world.properties(asset_id), center=center, radius=radius,
                                     density=density, erase=erase, seed=seed)
        return self.world.update(asset_id, values, replace=True)

    def world_asset_visualization(self, asset_id: str) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in WORLD_ASSET_TYPES:
            raise ValueError(f"Asset is not a world-production asset: {asset_id}")
        values = self.world.properties(asset_id)
        builders = {
            "tc.terrain": build_terrain_preview, "tc.navigation_mesh": build_navigation_preview,
            "tc.lighting_scenario": build_lighting_preview, "tc.world_partition": build_partition_preview,
            "tc.hlod_layer": build_hlod_preview,
        }
        if record.asset_type in builders:
            return builders[record.asset_type](values)
        return self.world.build_preview(asset_id)

    def build_world_backend(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> dict[str, Any]:
        return self.world_builds.build(asset_id, platform=platform, quality=quality).to_dict()

    def open_world_streaming_runtime(self, world_partition_asset_id: str) -> WorldStreamingRuntime:
        receipt = self.world_builds.build(world_partition_asset_id)
        manifest = json.loads(receipt.artifact.path.read_text(encoding="utf-8"))
        return WorldStreamingRuntime.from_manifest(manifest)

    def create_procedural_graph(
        self, name: str, *, graph: ProceduralGraph | None = None,
        folder: str | Path = "Assets/Procedural",
    ):
        """Create an editable procedural geometry asset with deterministic runtime cooking."""
        return self.procedural.create(name, graph=graph, folder=folder)

    def get_procedural_graph(self, asset_id: str) -> dict[str, Any]:
        return self.procedural.properties(asset_id)

    def set_procedural_graph(
        self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False,
    ) -> dict[str, Any]:
        return self.procedural.update(asset_id, values, replace=replace)

    def validate_procedural_graph(self, asset_id: str) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.procedural.validate(asset_id)]

    def cook_procedural_graph(
        self, asset_id: str, *, platform: str = "desktop", quality: str = "high",
    ) -> DerivedArtifact:
        return self.procedural.cook(asset_id, platform=platform, quality=quality)

    def procedural_operation_catalog(self) -> tuple[str, ...]:
        return self.procedural.operation_catalog()

    def procedural_execution_plan(self, asset_id: str, *, backend: str = "auto") -> dict[str, Any]:
        return build_procedural_execution_plan(self.procedural.graph(asset_id), backend=backend).to_dict()

    def procedural_native_document(self, asset_id: str, target: str) -> dict[str, Any]:
        """Serialize an editable Unreal, Blender, Houdini, Unity, or Godot adapter document."""
        return serialize_native_procedural_graph(self.procedural.graph(asset_id), target).to_dict()

    def import_procedural_native_document(
        self, document: Mapping[str, Any], *, name: str = "ImportedProceduralGraph",
        folder: str | Path = "Assets/Procedural",
    ):
        """Convert an adapter document from Unreal, Blender, Houdini, Unity, or Godot into a TC graph asset."""
        graph = deserialize_native_procedural_graph(document)
        graph.name = str(name or graph.name)
        return self.procedural.create(graph.name, graph=graph, folder=folder)

    def procedural_diagnostics(self, asset_id: str) -> dict[str, Any]:
        return self.procedural.diagnostics(asset_id)

    def cook_procedural_tasks(
        self, asset_id: str, *, initial_attributes: Mapping[str, Any] | None = None, workers: int = 1,
    ) -> dict[str, Any]:
        values = self.procedural.properties(asset_id)
        result = ProceduralTaskCooker(max_workers=workers).cook(
            ProceduralTaskGraph.from_dict(dict(values.get("task_graph") or {})),
            initial_attributes=dict(initial_attributes or {}),
        )
        return {"graph_id": result.graph_id, "output_node": result.output_node,
                "work_items": [item.__dict__.copy() for item in result.work_items],
                "diagnostics": [item.__dict__.copy() for item in result.diagnostics]}

    def step_procedural_simulation(
        self, asset_id: str, *, session_id: str = "preview", delta_time: float | None = None,
    ) -> dict[str, Any]:
        values = self.procedural.properties(asset_id); settings = dict(values.get("simulation") or {})
        key = f"{asset_id}:{session_id}"; session = self._procedural_simulations.setdefault(key, ProceduralSimulationSession(key))
        result = self.procedural.cooker.cook(self.procedural.graph(asset_id))
        payload = session.step(result, delta_time=float(delta_time if delta_time is not None else settings.get("fixed_timestep", 1 / 60)),
                               gravity=tuple(settings.get("gravity") or (0, -9.81, 0)),
                               damping=float(settings.get("damping", 0.02)))
        return payload.to_dict()

    def reset_procedural_simulation(self, asset_id: str, *, session_id: str = "preview") -> bool:
        session = self._procedural_simulations.pop(f"{asset_id}:{session_id}", None)
        if session is not None: session.reset()
        return session is not None

    def export_assets(self, asset_ids: Iterable[str], destination: str | Path, *, target: str = "generic", include_dependencies: bool = True) -> dict[str, Any]:
        """Export a dependency-closed package for Unreal, Unity, Blender, Maya, Houdini, or generic interchange."""
        return self.exports.export_assets(asset_ids, destination, target=target, include_dependencies=include_dependencies).to_dict()

    def create_level_sequence(
        self, name: str, *, folder: str | Path = "Assets/Cinematics",
        duration_frames: int = 300, fps: int = 30,
    ):
        """Create a native cinematic Level Sequence asset."""
        return self.sequence.create(name, folder=folder, duration_frames=duration_frames, fps=fps)

    @staticmethod
    def sequence_binding(
        name: str, *, object_id: str = "", binding_type: str = "possessable",
        parent_binding_id: str = "", component_path: str = "", bone_name: str = "",
        socket_name: str = "", skeleton_asset_id: str = "",
    ) -> dict[str, Any]:
        return new_binding(name, object_id=object_id, binding_type=binding_type,
                           parent_binding_id=parent_binding_id, component_path=component_path,
                           bone_name=bone_name, socket_name=socket_name,
                           skeleton_asset_id=skeleton_asset_id)

    @staticmethod
    def sequence_track(track_type: str, name: str = "", *, binding_id: str = "", parent_id: str = "") -> dict[str, Any]:
        return track_preset(track_type, name, binding_id=binding_id) if not parent_id else new_track(track_type, name, binding_id=binding_id, parent_id=parent_id)

    @staticmethod
    def sequence_section(name: str, start_frame: int, end_frame: int, *, asset_id: str = "", row: int = 0) -> dict[str, Any]:
        return new_section(name, start_frame, end_frame, asset_id=asset_id, row=row)

    @staticmethod
    def sequence_level_blend(name: str, level_asset_id: str, start_frame: int, end_frame: int, *, ease_in: int = 30, ease_out: int = 30, blend_mode: str = "crossfade") -> dict[str, Any]:
        return new_level_blend_section(name, level_asset_id, start_frame, end_frame, ease_in=ease_in, ease_out=ease_out, blend_mode=blend_mode)

    @staticmethod
    def sequence_key(section: dict[str, Any], channel_name: str, frame: float, value: Any, *, interpolation: str = "linear") -> dict[str, Any]:
        return add_channel_key(section, channel_name, frame, value, interpolation=interpolation)

    def get_level_sequence(self, asset_id: str) -> dict[str, Any]:
        return self.sequence.properties(asset_id)

    def update_level_sequence(self, asset_id: str, values: Mapping[str, Any]):
        return self.sequence.update(asset_id, values)

    def validate_level_sequence(self, asset_id: str):
        return self.sequence.validate(asset_id)

    def evaluate_level_sequence(self, asset_id: str, frame: int) -> dict[str, Any]:
        return evaluate_sequence(self.sequence.properties(asset_id), frame)

    def level_sequence_render_jobs(self, asset_id: str) -> tuple[dict[str, Any], ...]:
        return build_render_jobs(self.sequence.properties(asset_id))

    def cook_level_sequence(self, asset_id: str, *, platform: str = "windows", quality: str = "high"):
        return self.sequence.cook(asset_id, platform=platform, quality=quality)

    def add_sequence_binding(self, asset_id: str, name: str, **target: Any) -> dict[str, Any]:
        return self.sequence.add_binding(asset_id, name, **target)

    def add_sequence_track(self, asset_id: str, track_type: str, name: str = "", *, binding_id: str = "", parent_id: str = "") -> dict[str, Any]:
        return self.sequence.add_track(asset_id, track_type, name, binding_id=binding_id, parent_id=parent_id)

    def add_sequence_section(self, asset_id: str, track_id: str, name: str, start_frame: int, end_frame: int, *, referenced_asset_id: str = "", row: int = 0) -> dict[str, Any]:
        return self.sequence.add_section(asset_id, track_id, name, start_frame, end_frame, referenced_asset_id=referenced_asset_id, row=row)

    def add_sequence_key(self, asset_id: str, track_id: str, section_id: str, channel_name: str, frame: float, value: Any, *, interpolation: str = "linear") -> dict[str, Any]:
        return self.sequence.add_key(asset_id, track_id, section_id, channel_name, frame, value, interpolation=interpolation)

    def remove_sequence_track(self, asset_id: str, track_id: str) -> bool:
        return self.sequence.remove_track(asset_id, track_id)

    def remove_sequence_section(self, asset_id: str, track_id: str, section_id: str) -> bool:
        return self.sequence.remove_section(asset_id, track_id, section_id)

    @staticmethod
    def sequence_from_unreal(payload: Mapping[str, Any]) -> dict[str, Any]:
        return unreal_level_sequence_to_native(payload)

    @staticmethod
    def sequence_from_unity(payload: Mapping[str, Any]) -> dict[str, Any]:
        return unity_timeline_to_native(payload)

    @staticmethod
    def sequence_to_unreal(payload: Mapping[str, Any]) -> dict[str, Any]:
        return native_to_unreal_level_sequence(payload)

    @staticmethod
    def sequence_to_unity(payload: Mapping[str, Any]) -> dict[str, Any]:
        return native_to_unity_timeline(payload)

    def create_prefab(
        self, name: str, entities: Sequence[Mapping[str, Any]], *,
        folder: str | Path = "Assets/World", exposed_properties: Mapping[str, Any] | None = None,
    ):
        """Create a reusable Prefab with stable entity IDs."""
        return self.prefabs.create_from_entities(
            name, entities, folder=folder, exposed_properties=exposed_properties,
        )

    def material_presets(self) -> tuple[str, ...]:
        return ("default_lit", "unlit", "glass", "clear_coat", "skin", "cloth", "decal", "post_process")

    def create_material(
        self, name: str, *, preset: str = "default_lit", domain: str = "",
        shading_model: str = "", blend_mode: str = "",
        folder: str | Path = "Assets/Materials",
    ):
        return self.materials.create_material(
            name, preset=preset, domain=domain, shading_model=shading_model,
            blend_mode=blend_mode, folder=folder,
        )

    def apply_material_preset(self, asset_id: str, preset: str) -> dict[str, Any]:
        return self.materials.apply_preset(asset_id, preset).to_dict()

    def create_material_instance(
        self, name: str, parent_material_id: str, *, overrides: Mapping[str, Any] | None = None,
        static_switch_overrides: Mapping[str, bool] | None = None,
        folder: str | Path = "Assets/Materials/Instances",
    ):
        return self.materials.create_instance(
            name, parent_material_id, overrides=overrides,
            static_switch_overrides=static_switch_overrides, folder=folder,
        )

    def resolve_material(self, asset_id: str) -> dict[str, Any]:
        return self.materials.resolve(asset_id).to_dict()

    def set_material_instance_overrides(
        self, asset_id: str, overrides: Mapping[str, Any], *, replace: bool = False,
        static_switches: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        return self.materials.set_instance_overrides(
            asset_id, overrides, replace=replace, static_switches=static_switches,
        ).to_dict()

    def revert_material_instance_overrides(
        self, asset_id: str, names: Sequence[str] = (),
    ) -> dict[str, Any]:
        return self.materials.revert_instance_overrides(asset_id, names).to_dict()

    def assign_material_texture(
        self, asset_id: str, slot: str, texture_asset_id: str, *, channel: str = "rgba",
        color_space: str = "auto", sampler: str = "linear_wrap", uv_set: int = 0,
    ) -> dict[str, Any]:
        return self.materials.assign_texture(
            asset_id, slot, texture_asset_id, channel=channel, color_space=color_space,
            sampler=sampler, uv_set=uv_set,
        ).to_dict()

    def material_graph_statistics(
        self, asset_id: str, *, platform: str = "desktop",
    ) -> dict[str, Any]:
        resolution = self.materials.resolve(asset_id)
        issues, statistics = analyze_material_graph(
            dict(resolution.properties.get("graph") or {}), platform=platform,
        )
        return {"statistics": statistics, "issues": [item.to_dict() for item in issues]}

    def validate_material(self, asset_id: str, *, platform: str = "desktop") -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.materials.validate(asset_id, platform=platform)]

    def cook_material(
        self, asset_id: str, *, platform: str = "desktop", quality: str = "high",
    ) -> DerivedArtifact:
        return self.materials.compile(asset_id, platform=platform, quality=quality)

    def create_shader_graph(
        self, name: str, *, stage: str = "surface", language: str = "portable",
        graph: Mapping[str, Any] | None = None, include_asset_ids: Sequence[str] = (),
        folder: str | Path = "Assets/Shaders",
    ):
        receipt = self.assets.create_asset(
            "tc.shader_graph", name, folder=folder,
            properties={"shader_version": 2, "stage": stage, "language": language,
                        "graph": dict(graph or {"nodes": [], "connections": []}),
                        "include_asset_ids": list(include_asset_ids)},
        )
        self.database.set_dependencies(receipt.asset_id, [(str(value), "shader_include") for value in include_asset_ids])
        return receipt

    def shader_backend_capabilities(self) -> dict[str, Any]:
        return shader_backend_capabilities()

    def validate_shader_graph(self, asset_id: str, *, platform: str = "desktop") -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.shader_graph":
            raise ValueError(f"Asset is not a Shader Graph: {asset_id}")
        issues, _statistics = analyze_material_graph(dict(self.properties(asset_id).get("graph") or {}), platform=platform)
        return [item.to_dict() for item in issues]

    def compile_shader_graph(self, asset_id: str, *, target: str = "desktop") -> dict[str, Any]:
        receipt = AssetGraphCompileService(self.database, self.registry).compile_asset(asset_id, target=target)
        return {
            "succeeded": receipt.succeeded, "operation_count": receipt.operation_count,
            "diagnostics": [item.__dict__.copy() for item in receipt.diagnostics],
            "artifact": str(receipt.artifact.path) if receipt.artifact else "", "ir": receipt.ir,
        }

    def texture_import_settings(self, asset_id: str) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.texture":
            raise ValueError(f"Asset is not a Texture: {asset_id}")
        return dict(read_asset_metadata(record.source_path).get("importer_settings") or {})

    def set_texture_import_settings(self, asset_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.texture":
            raise ValueError(f"Asset is not a Texture: {asset_id}")
        metadata = read_asset_metadata(record.source_path)
        settings = dict(metadata.get("importer_settings") or {})
        settings.update(dict(values or {}))
        write_asset_metadata(
            record.source_path, asset_id=record.asset_id, type_id=record.asset_type,
            importer=str(metadata.get("importer") or "texture"), importer_settings=settings,
            previous_paths=list(metadata.get("previous_paths") or ()),
        )
        self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata={**record.metadata, "importer_settings": settings},
            dependencies=self.database.dependency_edges(record.asset_id),
        )
        return settings

    def create_prefab_variant(
        self, name: str, base_prefab_id: str, *, overrides: Mapping[str, Any] | None = None,
        added_entities: Sequence[Mapping[str, Any]] = (), removed_entity_ids: Sequence[str] = (),
        folder: str | Path = "Assets/World/Variants",
    ):
        """Create a non-destructive Prefab Variant inherited from a parent."""
        return self.prefabs.create_variant(
            name, base_prefab_id, overrides=overrides, added_entities=added_entities,
            removed_entity_ids=removed_entity_ids, folder=folder,
        )

    def resolve_prefab(self, asset_id: str, *, expand_nested: bool = True) -> dict[str, Any]:
        return self.prefabs.resolve(asset_id, expand_nested=expand_nested).to_dict()

    def instantiate_prefab(
        self, asset_id: str, *, overrides: Mapping[str, Any] | None = None,
        expand_nested: bool = False,
    ) -> dict[str, Any]:
        return self.prefabs.instantiate(
            asset_id, overrides=overrides, expand_nested=expand_nested,
        ).to_dict()

    def apply_prefab_overrides(
        self, asset_id: str, overrides: Mapping[str, Any], *, paths: Sequence[str] = (),
    ) -> dict[str, Any]:
        instance = self.prefabs.instantiate(asset_id, overrides=overrides)
        return self.prefabs.apply_overrides(instance, paths=paths or None).to_dict()

    def revert_prefab_overrides(
        self, asset_id: str, overrides: Mapping[str, Any], *, paths: Sequence[str] = (),
    ) -> dict[str, Any]:
        instance = self.prefabs.instantiate(asset_id, overrides=overrides)
        return self.prefabs.revert_overrides(instance, paths=paths or None).to_dict()

    def validate_prefab(self, asset_id: str) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.prefabs.validate(asset_id)]

    def cook_prefab(
        self, asset_id: str, *, platform: str = "desktop", quality: str = "high",
    ) -> DerivedArtifact:
        return self.prefabs.cook(asset_id, platform=platform, quality=quality)

    def available_game_templates(self) -> tuple[dict[str, Any], ...]:
        """List versioned project templates and variants shown by the editor."""

        from tech_connector.game_engine.authoring.game_template_service import available_game_templates

        return available_game_templates()

    def create_game_project_from_template(
        self,
        *,
        template_id: str = "playable_sandbox",
        variant_id: str = "",
        visual_style: str = "",
        project_name: str = "StarterGame",
        platform: str = "windows",
        root_folder: str | Path = "Assets",
    ) -> dict[str, Any]:
        """Create the same playable starter assets as the New Project UI."""

        from tech_connector.game_engine.authoring.game_template_service import GameTemplateService

        return GameTemplateService(self.project_root, self.database, self.registry).create_project(
            template_id=template_id,
            variant_id=variant_id,
            visual_style=visual_style,
            project_name=project_name,
            platform=platform,
            root_folder=root_folder,
        ).to_dict()

    def validate_playable_project(self, ruleset_asset_id: str, build_profile_asset_id: str = "") -> dict[str, Any]:
        """Run actionable pre-Play and package-readiness checks."""

        from tech_connector.game_engine.authoring.game_template_service import GameTemplateService

        return GameTemplateService(self.project_root, self.database, self.registry).validate_project(
            ruleset_asset_id, build_profile_asset_id,
        )

    def create_locomotion_controller(
        self,
        name: str,
        *,
        preset: str = "third_person",
        movement_mode: str = "",
        folder: str | Path = "Assets/Animation/Locomotion",
    ):
        """Create the editable controller used by template player prefabs."""

        return self.assets.create_asset(
            "tc.animation_controller", name, folder=folder,
            properties=locomotion_preset(preset, movement_mode=movement_mode),
        )

    def create_animation_clip(
        self, name: str, *, skeleton_id: str = "", duration_seconds: float = 1.0,
        sample_rate: float = 30.0, loop: bool = True,
        folder: str | Path = "Assets/Animation/Clips",
    ):
        """Create an editable clip with curves, events, root motion, additive, and compression settings."""
        return self.animation.create_clip(
            name, skeleton_id=skeleton_id, duration_seconds=duration_seconds,
            sample_rate=sample_rate, loop=loop, folder=folder,
        )

    def effect_presets(self) -> tuple[str, ...]:
        return self.effects.presets()

    def audio_clip_settings(self, asset_id: str) -> dict[str, Any]:
        return self.audio.clip_settings(asset_id)

    def set_audio_clip_settings(self, asset_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        return self.audio.set_clip_settings(asset_id, values)

    def create_sound_cue(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Cues"):
        return self.audio.create_sound_cue(name, properties=properties, folder=folder)

    def create_audio_mixer(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Mixers"):
        return self.audio.create_mixer(name, properties=properties, folder=folder)

    def create_audio_attenuation(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Attenuation"):
        return self.audio.create_attenuation(name, properties=properties, folder=folder)

    def create_audio_reverb(self, name: str, *, preset: str = "room", properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Audio/Reverb"):
        return self.audio.create_reverb(name, preset=preset, properties=properties, folder=folder)

    def validate_audio_asset(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.audio.validate(asset_id)]

    def cook_audio_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.audio.cook(asset_id, platform=platform, quality=quality)

    def convert_unreal_audio(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Audio/Converted/Unreal") -> dict[str, Any]:
        return self.audio.convert_unreal(exported_data, folder=folder).to_dict()

    def convert_unity_audio(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Audio/Converted/Unity") -> dict[str, Any]:
        return self.audio.convert_unity(exported_data, folder=folder).to_dict()

    def create_project_settings(self, name: str = "ProjectSettings", *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Settings"):
        return self.gameplay.create_project_settings(name, properties=properties, folder=folder)

    def create_data_schema(self, name: str, *, fields: Sequence[Mapping[str, Any]] = (), parent_schema_id: str = "", folder: str | Path = "Assets/Data/Schemas"):
        return self.gameplay.create_schema(name, fields=fields, parent_schema_id=parent_schema_id, folder=folder)

    def create_struct(self, name: str, *, fields: Sequence[Mapping[str, Any]] = (), parent_schema_id: str = "", folder: str | Path = "Assets/Data/Structs"):
        return self.gameplay.create_struct(name, fields=fields, parent_schema_id=parent_schema_id, folder=folder)

    def create_enum(self, name: str, *, entries: Sequence[Mapping[str, Any] | str] = (), flags: bool = False, folder: str | Path = "Assets/Data/Enums"):
        return self.gameplay.create_enum(name, entries=entries, flags=flags, folder=folder)

    def create_typed_data_asset(self, name: str, *, schema_asset_id: str = "", values: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Data"):
        return self.gameplay.create_data_asset(name, schema_asset_id=schema_asset_id, values=values, folder=folder)

    def create_data_table(self, name: str, *, row_schema_id: str = "", rows: Sequence[Mapping[str, Any]] = (), key_field: str = "id", folder: str | Path = "Assets/Data/Tables"):
        return self.gameplay.create_data_table(name, row_schema_id=row_schema_id, rows=rows, key_field=key_field, folder=folder)

    def create_component_archetype(self, name: str, *, components: Sequence[Mapping[str, Any]] = (), parent_archetype_id: str = "", folder: str | Path = "Assets/Gameplay/Components"):
        return self.gameplay.create_component_archetype(name, components=components, parent_archetype_id=parent_archetype_id, folder=folder)

    def create_character_definition(self, name: str, *, properties: Mapping[str, Any] | None = None, folder: str | Path = "Assets/Gameplay/Characters"):
        return self.gameplay.create_character_definition(name, properties=properties, folder=folder)

    def create_gameplay_class(
        self, name: str, *, class_kind: str = "actor", parent_class_id: str = "",
        components: Sequence[Mapping[str, Any]] = (), variables: Sequence[Mapping[str, Any]] = (),
        folder: str | Path = "Assets/Gameplay/Classes",
    ):
        """Create an inherited, component-based executable Gameplay Class."""
        return self.gameplay_classes.create(
            name, class_kind=class_kind, parent_class_id=parent_class_id,
            components=components, variables=variables, folder=folder,
        )

    def resolve_gameplay_class(self, asset_id: str) -> dict[str, Any]:
        return self.gameplay_classes.resolve(asset_id)

    def create_behavior(self, name: str, *, program: Mapping[str, Any] | None = None,
                        folder: str | Path = "Assets/Gameplay/Behaviors"):
        return self.behavior_graphs.create("tc.behavior", name, program=program, folder=folder)

    def create_gameplay_graph(self, name: str, *, program: Mapping[str, Any] | None = None,
                              folder: str | Path = "Assets/Gameplay/Graphs"):
        return self.behavior_graphs.create("tc.gameplay_graph", name, program=program, folder=folder)

    def validate_behavior_graph(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.behavior_graphs.validate(asset_id)]

    def cook_behavior_graph(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.behavior_graphs.cook(asset_id, platform=platform, quality=quality)

    def execute_behavior_graph(self, asset_id: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.behavior_graphs.execute(asset_id, context)

    def create_image_project(self, name: str, *, width: int = 1024, height: int = 1024,
                             layers: Sequence[Mapping[str, Any]] = (), folder: str | Path = "Assets/Images"):
        return self.image_projects.create(name, width=width, height=height, layers=layers, folder=folder)

    def validate_image_project(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.image_projects.validate(asset_id)]

    def flatten_image_project(self, asset_id: str) -> bytes:
        return self.image_projects.flatten(asset_id)

    def cook_image_project(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.image_projects.cook(asset_id, platform=platform, quality=quality)

    def validate_gameplay_class(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.gameplay_classes.validate(asset_id)]

    def compile_gameplay_class(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.gameplay_classes.compile(asset_id, platform=platform, quality=quality)

    def debug_gameplay_class(self, asset_id: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.gameplay_classes.debug_event(asset_id, context)

    def begin_gameplay_class_debug_session(
        self, asset_id: str, *, instance_id: str = "EditorPreview",
        session_id: str = "", context: Mapping[str, Any] | None = None,
        breakpoints: Sequence[str] = (), watches: Sequence[str] = (),
    ) -> dict[str, Any]:
        identifier = str(session_id or f"{asset_id}:{instance_id}")
        seeded_context = self.gameplay_classes.debug_context(asset_id, context)
        attach_context: Any = seeded_context
        if isinstance(context, MutableMapping):
            context["authority"] = seeded_context.authority
            context["input_actions"] = dict(seeded_context.input_actions)
            context["actors"] = dict(seeded_context.actors)
            context["events"] = list(seeded_context.events)
            context["metadata"] = dict(seeded_context.metadata)
            attach_context = context
        session = self.gameplay_debug_sessions.attach(
            identifier, instance_id, self.gameplay_classes.debug_manifest(asset_id),
            attach_context,
        )
        session.set_breakpoints(breakpoints); session.set_watches(watches)
        return session.start().to_dict()

    def gameplay_class_debug_command(self, session_id: str, command: str, **options: Any) -> dict[str, Any]:
        session = self.gameplay_debug_sessions.session(session_id); action = str(command).casefold().replace(" ", "_")
        if action in {"continue", "resume"}: snapshot = session.continue_execution()
        elif action == "step": snapshot = session.step()
        elif action == "pause": snapshot = session.pause()
        elif action == "restart": snapshot = session.restart()
        elif action == "stop": snapshot = session.stop(keep_changes=bool(options.get("keep_changes", False)))
        elif action == "breakpoints": snapshot = session.set_breakpoints(options.get("node_ids") or ())
        elif action == "watches": snapshot = session.set_watches(options.get("paths") or ())
        elif action == "hot_swap":
            asset_id = str(options.get("asset_id") or session.program_id.removeprefix("gameplay_class_"))
            snapshot = session.hot_swap(self.gameplay_classes.debug_manifest(asset_id))
        elif action in {"snapshot", "status"}: snapshot = session.snapshot()
        else: raise ValueError(f"Unknown gameplay debug command: {command}")
        return snapshot.to_dict()

    def list_gameplay_class_debug_sessions(self) -> tuple[dict[str, Any], ...]:
        return self.gameplay_debug_sessions.list_sessions()

    def end_gameplay_class_debug_session(self, session_id: str, *, keep_changes: bool = False) -> dict[str, Any]:
        return self.gameplay_debug_sessions.detach(session_id, keep_changes=keep_changes).to_dict()

    def validate_gameplay_foundation_asset(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.gameplay.validate(asset_id)]

    def resolve_data_schema(self, asset_id: str) -> dict[str, Any]:
        return self.gameplay.resolve_schema(asset_id)

    def cook_gameplay_foundation_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.gameplay.cook(asset_id, platform=platform, quality=quality)

    def convert_unreal_data_assets(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Data/Converted/Unreal") -> dict[str, Any]:
        return self.gameplay.convert_unreal(exported_data, folder=folder)

    def convert_unity_scriptable_objects(self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Data/Converted/Unity") -> dict[str, Any]:
        return self.gameplay.convert_unity(exported_data, folder=folder)

    def effect_module_library(self) -> dict[str, dict[str, Any]]:
        return self.effects.module_library()

    def create_effect_system(
        self, name: str, *, preset: str = "sparks", quality: str = "high", seed: int = 1,
        folder: str | Path = "Assets/Effects",
    ):
        return self.effects.create(name, preset=preset, quality=quality, seed=seed, folder=folder)

    def apply_effect_preset(self, asset_id: str, preset: str, *, preserve_parameters: bool = True) -> dict[str, Any]:
        return self.effects.apply_preset(asset_id, preset, preserve_parameters=preserve_parameters)

    def effect_properties(self, asset_id: str) -> dict[str, Any]:
        return self.effects.properties(asset_id)

    def set_effect_properties(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        return self.effects.update(asset_id, values, replace=replace)

    def validate_effect_system(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.effects.validate(asset_id, platform=platform, quality=quality)]

    def estimate_effect_cost(self, asset_id: str, *, quality: str = "high") -> dict[str, Any]:
        return self.effects.estimate(asset_id, quality=quality).to_dict()

    def cook_effect_system(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.effects.cook(asset_id, platform=platform, quality=quality)

    def convert_unreal_effects(
        self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Effects/Converted/Unreal",
    ) -> dict[str, Any]:
        return self.effects.convert_unreal(exported_data, folder=folder).to_dict()

    def convert_unity_effects(
        self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Effects/Converted/Unity",
    ) -> dict[str, Any]:
        return self.effects.convert_unity(exported_data, folder=folder).to_dict()

    def create_blend_space(
        self, name: str, *, skeleton_id: str = "", dimensions: int = 2,
        axes: Sequence[Mapping[str, Any]] = (), samples: Sequence[Mapping[str, Any]] = (),
        folder: str | Path = "Assets/Animation/BlendSpaces",
    ):
        """Create a one- or two-dimensional editable Blend Space."""
        return self.animation.create_blend_space(
            name, skeleton_id=skeleton_id, dimensions=dimensions,
            axes=axes, samples=samples, folder=folder,
        )

    def create_animation_mask(
        self, name: str, *, skeleton_id: str = "", weights: Mapping[str, float] | None = None,
        folder: str | Path = "Assets/Animation/Masks",
    ):
        return self.animation.create_mask(name, skeleton_id=skeleton_id, weights=weights, folder=folder)

    def create_animation_controller(
        self, name: str, *, skeleton_id: str = "", properties: Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/Animation/Controllers",
    ):
        """Create a layered controller with state machines and a final pose graph."""
        return self.animation.create_controller(name, skeleton_id=skeleton_id, properties=properties, folder=folder)

    def animation_properties(self, asset_id: str) -> dict[str, Any]:
        return self.animation.properties(asset_id)

    def set_animation_properties(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        return self.animation.update(asset_id, values, replace=replace)

    def validate_animation_asset(self, asset_id: str) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.animation.validate(asset_id)]

    def evaluate_blend_space(self, asset_id: str, x: float, y: float = 0.0) -> dict[str, float]:
        return self.animation.evaluate_blend_space(asset_id, x, y)

    def cook_animation_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        return self.animation.cook(asset_id, platform=platform, quality=quality)

    def convert_unreal_animation(
        self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted/Unreal",
    ) -> dict[str, Any]:
        """Convert Unreal Editor-exported animation reflection data; raw .uasset parsing is intentionally unsupported."""
        return self.animation.convert_unreal(exported_data, folder=folder).to_dict()

    def convert_unity_animation(
        self, exported_data: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted/Unity",
    ) -> dict[str, Any]:
        """Convert Unity Editor-exported AnimatorController/BlendTree data."""
        return self.animation.convert_unity(exported_data, folder=folder).to_dict()

    def convert_animation_export_file(
        self, source_path: str | Path, *, provider: str,
        folder: str | Path = "Assets/Animation/Converted",
    ) -> dict[str, Any]:
        """Import a Tech Connector Unreal or Unity editor export as native animation assets."""
        return self.animation.convert_file(source_path, provider=provider, folder=folder).to_dict()

    def convert_live_unity_animation(
        self, controller_asset_path: str, *, port: int | None = None,
        folder: str | Path = "Assets/Animation/Converted/Unity",
    ) -> dict[str, Any]:
        """Export from a running Unity Editor and immediately create native Tech Connector assets."""
        from tech_connector.bridges.unity.unity_bridge import UnityBridge

        ok, payload = UnityBridge().export_animation_controller(controller_asset_path, port=port)
        if not ok or not isinstance(payload, Mapping):
            raise RuntimeError(str(payload))
        return self.animation.convert_unity(payload, folder=folder).to_dict()

    def convert_live_unreal_animation(
        self, asset_paths: Sequence[str], *,
        folder: str | Path = "Assets/Animation/Converted/Unreal",
    ) -> dict[str, Any]:
        """Reflect from a running Unreal Editor and immediately create native Tech Connector assets."""
        from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

        response = UnrealBridge().export_animation_assets(tuple(str(value) for value in asset_paths))
        payload = response.get("data")
        if not response.get("ok") or not isinstance(payload, Mapping):
            raise RuntimeError(str(response.get("error") or "Unreal animation export failed."))
        return self.animation.convert_unreal(payload, folder=folder).to_dict()

    def export_animation_interchange(self, asset_ids: Iterable[str]) -> dict[str, Any]:
        return self.animation.export_interchange(asset_ids)

    def import_animation_interchange(
        self, payload: Mapping[str, Any], *, folder: str | Path = "Assets/Animation/Converted",
    ) -> dict[str, Any]:
        return self.animation.import_interchange(payload, folder=folder).to_dict()

    def validate_locomotion_controller(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.animation_controller":
            raise ValueError(f"Asset is not an Animation/Locomotion Controller: {asset_id}")
        return [item.to_dict() for item in validate_locomotion_controller(self.properties(asset_id))]

    def cook_locomotion_controller(
        self, asset_id: str, *, platform: str = "desktop", quality: str = "high",
    ) -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.animation_controller":
            raise ValueError(f"Asset is not an Animation/Locomotion Controller: {asset_id}")
        return self.database.store_derived(
            asset_id, f"locomotion_runtime:{platform}:{quality}",
            compile_locomotion_payload(self.properties(asset_id), platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality}, extension=".tclocomotion",
        )

    def create_starter_character(
        self,
        name: str = "TC_Starter_Mannequin",
        *,
        visual_style: str = "stylized_pbr",
        dimensionality: str = "3d",
        folder: str | Path = "Assets/Characters/Starter",
    ) -> dict[str, Any]:
        """Generate the editable TC biped skeleton, mesh, and skin-binding package."""

        return StarterCharacterService(self.project_root, self.database, self.registry).create(
            name, visual_style=visual_style, dimensionality=dimensionality, folder=folder,
        ).to_dict()

    def import_asset(self, source_path: str | Path, *, folder: str | Path = "Assets", type_id: str = "", importer_settings: Mapping[str, Any] | None = None):
        return self.assets.import_asset(source_path, folder=folder, type_id=type_id, importer_settings=dict(importer_settings or {}))

    def properties(self, asset_id: str) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is not None and record.asset_type in AUDIO_ASSET_TYPES:
            return self.audio.properties(asset_id)
        if record is not None and record.asset_type in GAMEPLAY_FOUNDATION_TYPES:
            return self.gameplay.properties(asset_id)
        if record is not None and record.asset_type == "tc.gameplay_class":
            return self.gameplay_classes.properties(asset_id)
        if record is not None and record.asset_type in BEHAVIOR_GRAPH_TYPES:
            return self.behavior_graphs.properties(asset_id)
        if record is not None and record.asset_type == "tc.image_project":
            return self.image_projects.properties(asset_id)
        if record is not None and record.asset_type in WORLD_ASSET_TYPES:
            return self.world.properties(asset_id)
        if record is not None and record.asset_type == "tc.procedural_graph":
            return self.procedural.properties(asset_id)
        _record, payload = self._authored_payload(asset_id)
        return dict(payload.get("properties") or {})

    def set_properties(self, asset_id: str, values: Mapping[str, Any], *, replace: bool = False) -> dict[str, Any]:
        existing = self.database.asset(asset_id)
        if existing is not None and existing.asset_type in AUDIO_ASSET_TYPES:
            return self.audio.update(asset_id, values, replace=replace)
        if existing is not None and existing.asset_type in GAMEPLAY_FOUNDATION_TYPES:
            return self.gameplay.update(asset_id, values, replace=replace)
        if existing is not None and existing.asset_type == "tc.gameplay_class":
            return self.gameplay_classes.update(asset_id, values, replace=replace)
        if existing is not None and existing.asset_type in BEHAVIOR_GRAPH_TYPES:
            return self.behavior_graphs.update(asset_id, dict(values.get("program") or values))
        if existing is not None and existing.asset_type == "tc.image_project":
            return self.image_projects.update(asset_id, values)
        if existing is not None and existing.asset_type in WORLD_ASSET_TYPES:
            return self.world.update(asset_id, values, replace=replace)
        if existing is not None and existing.asset_type == "tc.procedural_graph":
            return self.procedural.update(asset_id, values, replace=replace)
        record, payload = self._authored_payload(asset_id)
        if record.asset_type in {"tc.material", "tc.material_instance"}:
            return self.materials.update_properties(asset_id, values, replace=replace)
        properties = {} if replace else dict(payload.get("properties") or {})
        properties.update(dict(values or {}))
        payload["properties"] = properties
        self._write_payload(record.source_path, payload)
        self.database.register_asset(record.source_path, record.asset_type, asset_id=record.asset_id, metadata=record.metadata)
        return properties

    def create_fabric_material(self, name: str, *, preset: str = "cotton", folder: str | Path = "Assets/Cloth"):
        return self.assets.create_asset("tc.fabric_material", name, folder=folder, properties=fabric_preset(preset))

    def create_control_rig(
        self, name: str, *, skeleton_id: str, graph: Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/Animation/Rigs",
    ):
        authored_graph = dict(graph or {"nodes": [
            {"id": "OutputPose", "title": "Output Pose", "opcode": "output_pose", "position": [560, 160], "inputs": ["pose:pose"], "outputs": []},
        ], "connections": []})
        receipt = self.assets.create_asset("tc.control_rig", name, folder=folder, properties={
            "skeleton_id": str(skeleton_id), "graph": authored_graph,
        })
        self.database.set_dependencies(receipt.asset_id, [(str(skeleton_id), "skeleton")])
        return receipt

    def create_ik_rig(
        self, name: str, *, skeleton_id: str, bones: Iterable[Mapping[str, Any] | str] = (),
        retarget_root: str = "", folder: str | Path = "Assets/Animation/Rigs",
    ):
        chains = automatic_ik_chains(bones)
        receipt = self.assets.create_asset("tc.ik_rig", name, folder=folder, properties={
            "skeleton_id": str(skeleton_id), "retarget_root": str(retarget_root), "chains": chains,
            "skeleton_bones": [dict(value) if isinstance(value, Mapping) else {"name": str(value)} for value in bones],
        })
        self.database.set_dependencies(receipt.asset_id, [(str(skeleton_id), "skeleton")])
        return receipt

    def create_ik_retargeter(
        self, name: str, *, source_ik_rig_id: str, target_ik_rig_id: str,
        folder: str | Path = "Assets/Animation/Retargeting",
    ):
        source = self.properties(source_ik_rig_id)
        target = self.properties(target_ik_rig_id)
        mapping = automatic_chain_mapping(source.get("chains") or (), target.get("chains") or ())
        receipt = self.assets.create_asset("tc.ik_retargeter", name, folder=folder, properties={
            "source_ik_rig_id": str(source_ik_rig_id), "target_ik_rig_id": str(target_ik_rig_id),
            "chain_mapping": mapping,
        })
        self.database.set_dependencies(receipt.asset_id, [
            (str(source_ik_rig_id), "source_ik_rig"), (str(target_ik_rig_id), "target_ik_rig"),
        ])
        return receipt

    def auto_setup_ik_rig(self, asset_id: str, bones: Iterable[Mapping[str, Any] | str]) -> list[dict[str, Any]]:
        materialized = [dict(value) if isinstance(value, Mapping) else {"name": str(value)} for value in bones]
        chains = automatic_ik_chains(materialized)
        self.set_properties(asset_id, {"chains": chains, "skeleton_bones": materialized})
        return chains

    def auto_map_ik_retargeter(self, asset_id: str) -> list[dict[str, Any]]:
        values = self.properties(asset_id)
        source = self.properties(str(values.get("source_ik_rig_id") or ""))
        target = self.properties(str(values.get("target_ik_rig_id") or ""))
        mapping = automatic_chain_mapping(source.get("chains") or (), target.get("chains") or ())
        self.set_properties(asset_id, {"chain_mapping": mapping})
        return mapping

    def validate_rig_asset(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        validators = {"tc.control_rig": validate_control_rig_properties, "tc.ik_rig": validate_ik_rig_properties,
                      "tc.ik_retargeter": validate_ik_retargeter_properties}
        if record is None or record.asset_type not in validators:
            raise ValueError(f"Asset is not a Control Rig, IK Rig, or IK Retargeter: {asset_id}")
        return [issue.__dict__.copy() for issue in validators[record.asset_type](self.properties(asset_id))]

    def cook_rig_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in {"tc.control_rig", "tc.ik_rig", "tc.ik_retargeter"}:
            raise ValueError(f"Asset is not a Control Rig, IK Rig, or IK Retargeter: {asset_id}")
        kind = record.asset_type.removeprefix("tc.") + "_runtime"
        return self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}",
            compile_rig_asset_payload(record.asset_type, self.properties(asset_id), platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality}, extension=".tcrigbin",
        )

    def create_skin_binding(
        self,
        name: str,
        *,
        mesh_id: str,
        skeleton_id: str,
        dcc_payload: Mapping[str, Any],
        folder: str | Path = "Assets/Characters",
    ):
        payload = dict(dcc_payload or {})
        cluster = dict(payload.get("cluster") or payload)
        properties = {
            "mesh_id": str(mesh_id), "skeleton_id": str(skeleton_id),
            "influences": list(cluster.get("influences") or ()),
            "vertex_weights": list(cluster.get("vertex_weights") or ()),
            "max_influences": int(cluster.get("max_influences", 4) or 4),
            "normalize": bool(cluster.get("normalize", True)),
            "topology": dict(payload.get("topology") or cluster.get("topology") or {}),
            "performance_profile": "balanced",
        }
        receipt = self.assets.create_asset("tc.skin_binding", name, folder=folder, properties=properties)
        # The Skeletal Mesh owns its Skin Binding. Keeping the compatibility
        # mesh ID in the payload avoids a Mesh <-> Binding dependency cycle.
        self.database.set_dependencies(receipt.asset_id, [(str(skeleton_id), "skeleton")])
        return receipt

    def create_skeletal_mesh_asset(
        self,
        name: str,
        *,
        skeleton_id: str,
        skin_binding_id: str = "",
        bones: Iterable[Mapping[str, Any] | str] = (),
        preserve_bones: Iterable[str] = (),
        lod_count: int = 4,
        folder: str | Path = "Assets/Characters",
    ):
        lods = recommended_mesh_lods(lod_count)
        bone_lods = generate_bone_lods(bones, count=len(lods), preserve_bones=preserve_bones)
        receipt = self.assets.create_asset("tc.skeletal_mesh", name, folder=folder, properties={
            "skeleton_id": str(skeleton_id), "skin_binding_id": str(skin_binding_id),
            "lods": lods, "bone_lods": bone_lods, "performance_profile": "balanced",
        })
        dependencies = [(str(skeleton_id), "skeleton")]
        if skin_binding_id:
            dependencies.append((str(skin_binding_id), "skin_binding"))
        self.database.set_dependencies(receipt.asset_id, dependencies)
        return receipt

    def create_geometry_optimization_profile(
        self, name: str, *, preset: str = "character_balanced",
        source_asset_ids: Iterable[str] = (), folder: str | Path = "Assets/Geometry",
    ):
        properties = geometry_optimization_preset(preset)
        properties["source_asset_ids"] = list(dict.fromkeys(str(value) for value in source_asset_ids if str(value)))
        properties.setdefault("selection_sets", [])
        properties.setdefault("execution", {"mode": "isolated_process", "workers": 1, "cache": True,
                                             "retry_limit": 2, "progress_events": True})
        properties.setdefault("reports", {})
        receipt = self.assets.create_asset("tc.geometry_optimization_profile", name, folder=folder, properties=properties)
        # Source IDs are batch targets, not cook dependencies. Keeping the
        # profile reusable avoids Mesh -> Profile -> Mesh dependency cycles.
        return receipt

    def create_hair_material(
        self, name: str, *, preset: str = "brown_hair", overrides: Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/Grooms/Materials",
    ):
        properties = hair_material_preset(preset); properties.update(dict(overrides or {}))
        return self.assets.create_asset("tc.hair_material", name, folder=folder, properties=properties)

    def create_groom(
        self, name: str, *, groups: Iterable[Mapping[str, Any]], material_ids: Iterable[str] = (),
        source_path: str = "", physics_asset_id: str = "", lod_count: int = 5,
        folder: str | Path = "Assets/Grooms",
    ):
        authored_groups: list[dict[str, Any]] = []
        for index, value in enumerate(groups):
            source = dict(value or {}); preset_name = str(source.pop("preset", "scalp"))
            preset = groom_group_preset(preset_name)
            simulation = {key: preset.pop(key) for key in ("simulation", "solver", "bend_stiffness", "stretch_stiffness", "damping")}
            simulation["enabled"] = bool(simulation.pop("simulation"))
            simulation.update(dict(source.pop("simulation", {}) or {}))
            group = {"name": str(source.pop("name", f"Group {index}")), **preset, **source, "simulation": simulation}
            authored_groups.append(group)
        materials = list(dict.fromkeys(str(value) for value in material_ids if str(value)))
        properties = {
            "source": {"mode": "alembic" if source_path else "procedural", "path": str(source_path),
                       "coordinate_system": "auto", "scale": 1.0},
            "groups": authored_groups, "lod_mode": "auto", "lods": automatic_groom_lods(count=lod_count),
            "cards": {"entries": [], "texture_layout": "compact",
                      "bake_maps": ["depth", "coverage", "tangent", "attributes", "color_roughness"]},
            "meshes": {"entries": []}, "material_ids": materials, "physics_asset_id": str(physics_asset_id),
            "interpolation": {"quality": "high", "randomize_guides": True, "rbf": True},
            "platform_overrides": {}, "diagnostics": {},
        }
        receipt = self.assets.create_asset("tc.groom", name, folder=folder, properties=properties)
        dependencies = [(value, "hair_material") for value in materials]
        if physics_asset_id: dependencies.append((str(physics_asset_id), "physics_asset"))
        self.database.set_dependencies(receipt.asset_id, dependencies)
        return receipt

    def create_groom_binding(
        self, name: str, *, groom_id: str, target_skeletal_mesh_id: str,
        source_skeletal_mesh_id: str = "", binding_mode: str = "skinning",
        folder: str | Path = "Assets/Grooms/Bindings",
    ):
        properties = {"groom_id": str(groom_id), "target_skeletal_mesh_id": str(target_skeletal_mesh_id),
                      "source_skeletal_mesh_id": str(source_skeletal_mesh_id), "root_count": 0,
                      "root_projections": [], "maximum_projection_distance": 0.05,
                      "binding_mode": str(binding_mode)}
        receipt = self.assets.create_asset("tc.groom_binding", name, folder=folder, properties=properties)
        dependencies = [(str(groom_id), "groom"), (str(target_skeletal_mesh_id), "target_skeletal_mesh")]
        if source_skeletal_mesh_id and source_skeletal_mesh_id != target_skeletal_mesh_id:
            dependencies.append((str(source_skeletal_mesh_id), "source_skeletal_mesh"))
        self.database.set_dependencies(receipt.asset_id, dependencies)
        return receipt

    def generate_groom_lods(
        self, asset_id: str, *, count: int = 5, include_cards: bool = True, include_mesh: bool = True,
    ) -> list[dict[str, Any]]:
        lods = automatic_groom_lods(count=count, include_cards=include_cards, include_mesh=include_mesh)
        self.set_properties(asset_id, {"lod_mode": "auto", "lods": lods})
        return lods

    def project_groom_binding(
        self, asset_id: str, roots: Sequence[Sequence[float]], vertices: Sequence[Sequence[float]],
        triangles: Sequence[Sequence[int]],
    ) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.groom_binding":
            raise ValueError(f"Asset is not a Groom Binding: {asset_id}")
        projections = project_groom_roots(roots, vertices, triangles)
        self.set_properties(asset_id, {"root_count": len(roots), "root_projections": projections})
        return projections

    def validate_groom(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        validators = {"tc.groom": validate_groom_properties, "tc.groom_binding": validate_groom_binding_properties,
                      "tc.hair_material": validate_hair_material_properties}
        if record is None or record.asset_type not in validators:
            raise ValueError(f"Asset is not a Groom, Groom Binding, or Hair Material: {asset_id}")
        return [issue.__dict__.copy() for issue in validators[record.asset_type](self.properties(asset_id))]

    def cook_groom(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        compilers = {"tc.groom": (compile_groom_payload, "groom_runtime"),
                     "tc.groom_binding": (compile_groom_binding_payload, "groom_binding_runtime"),
                     "tc.hair_material": (compile_hair_material_payload, "hair_material_runtime")}
        if record is None or record.asset_type not in compilers:
            raise ValueError(f"Asset is not a Groom, Groom Binding, or Hair Material: {asset_id}")
        compiler, kind = compilers[record.asset_type]
        return self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}", compiler(self.properties(asset_id), platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality}, extension=".tcgroombin",
        )

    def assign_geometry_optimization_profile(self, skeletal_mesh_id: str, profile_id: str) -> dict[str, Any]:
        record = self.database.asset(skeletal_mesh_id)
        profile = self.database.asset(profile_id)
        if record is None or record.asset_type != "tc.skeletal_mesh":
            raise ValueError(f"Asset is not a Skeletal Mesh: {skeletal_mesh_id}")
        if profile is None or profile.asset_type != "tc.geometry_optimization_profile":
            raise ValueError(f"Asset is not a Geometry Optimization Profile: {profile_id}")
        result = self.set_properties(skeletal_mesh_id, {"optimization_profile_id": str(profile_id)})
        edges = [(value, kind) for value, kind in self.database.dependency_edges(skeletal_mesh_id) if kind != "optimization_profile"]
        edges.append((str(profile_id), "optimization_profile"))
        self.database.set_dependencies(skeletal_mesh_id, edges)
        return result

    def plan_geometry_optimization(self, asset_id: str) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.geometry_optimization_profile":
            raise ValueError(f"Asset is not a Geometry Optimization Profile: {asset_id}")
        return plan_geometry_optimization(self.properties(asset_id))

    def validate_geometry_optimization(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.geometry_optimization_profile":
            raise ValueError(f"Asset is not a Geometry Optimization Profile: {asset_id}")
        return [issue.__dict__.copy() for issue in validate_geometry_optimization_profile(self.properties(asset_id))]

    def cook_geometry_optimization(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.geometry_optimization_profile":
            raise ValueError(f"Asset is not a Geometry Optimization Profile: {asset_id}")
        return self.database.store_derived(
            asset_id, f"geometry_optimization_plan:{platform}:{quality}",
            compile_geometry_optimization_payload(self.properties(asset_id), platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality}, extension=".tcgeooptbin",
        )

    def assign_skin_binding(self, skeletal_mesh_id: str, skin_binding_id: str) -> dict[str, Any]:
        record = self.database.asset(skeletal_mesh_id)
        if record is None or record.asset_type != "tc.skeletal_mesh":
            raise ValueError(f"Asset is not a Skeletal Mesh: {skeletal_mesh_id}")
        properties = self.set_properties(skeletal_mesh_id, {"skin_binding_id": str(skin_binding_id)})
        dependencies = [(value, kind) for value, kind in self.database.dependency_edges(skeletal_mesh_id) if kind != "skin_binding"]
        dependencies.append((str(skin_binding_id), "skin_binding"))
        self.database.set_dependencies(skeletal_mesh_id, dependencies)
        return properties

    def generate_character_lods(
        self,
        asset_id: str,
        bones: Iterable[Mapping[str, Any] | str],
        *,
        count: int = 4,
        preserve_bones: Iterable[str] = (),
    ) -> dict[str, Any]:
        lods = recommended_mesh_lods(count)
        bone_lods = generate_bone_lods(bones, count=len(lods), preserve_bones=preserve_bones)
        self.set_properties(asset_id, {"lods": lods, "bone_lods": bone_lods})
        return {"lods": lods, "bone_lods": bone_lods}

    def generate_mesh_lod_geometry(
        self,
        asset_id: str,
        source_path: str | Path,
        *,
        custom_lod_sources: Mapping[int, str | Path] | None = None,
        output_folder: str | Path = "Derived/CharacterLODs",
        include_animation: bool = False,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.skeletal_mesh":
            raise ValueError(f"Asset is not a Skeletal Mesh: {asset_id}")
        properties = self.properties(asset_id)
        lods = list(properties.get("lods") or recommended_mesh_lods())
        custom = {int(key): str(Path(value).expanduser().resolve()) for key, value in dict(custom_lod_sources or {}).items()}
        levels = tuple(
            CharacterMeshLodLevel(
                f"LOD{index}", float(lod.get("triangle_percent", 100.0)) / 100.0,
                max(0.0, float(lod.get("max_deviation", 0.0))), custom.get(index, ""),
            ) for index, lod in enumerate(lods)
        )
        output = self.project_root / Path(output_folder)
        receipt = generate_character_mesh_lods(
            CharacterMeshLodRequest(str(source_path), str(output), levels=levels,
                                    include_animation=include_animation, preserve_skinning=True), timeout=timeout,
        )
        artifacts = []
        for level in receipt.get("levels") or ():
            path = Path(str(level.get("output_path") or "")).resolve()
            try: rendered_path = path.relative_to(self.project_root).as_posix()
            except ValueError: rendered_path = path.as_posix()
            artifacts.append({"level": str(level.get("name") or ""), "path": rendered_path,
                              "source_kind": str(level.get("source_kind") or "generated"),
                              "triangles": int(level.get("output_triangles", 0)),
                              "skinning_preserved": bool(level.get("skinning_preserved", False))})
        self.set_properties(asset_id, {"lod_artifacts": artifacts, "lod_generation_receipt": receipt})
        return receipt

    def validate_character_asset(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in {"tc.skeletal_mesh", "tc.skin_binding"}:
            raise ValueError(f"Asset is not a Skeletal Mesh or Skin Binding: {asset_id}")
        validator = validate_character_lods if record.asset_type == "tc.skeletal_mesh" else validate_skin_binding_properties
        return [issue.__dict__.copy() for issue in validator(self.properties(asset_id))]

    def cook_character_asset(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in {"tc.skeletal_mesh", "tc.skin_binding"}:
            raise ValueError(f"Asset is not a Skeletal Mesh or Skin Binding: {asset_id}")
        if record.asset_type == "tc.skin_binding":
            kind, extension, payload = "skin_binding_runtime", ".tcskinbin", compile_skin_binding_payload(
                self.properties(asset_id), platform=platform, quality=quality,
            )
        else:
            kind, extension, payload = "skeletal_mesh_plan", ".tcskmeshbin", compile_skeletal_mesh_plan(
                self.properties(asset_id), platform=platform, quality=quality,
            )
        return self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}", payload,
            metadata={"platform": platform, "quality": quality}, extension=extension,
        )

    def create_cloth(
        self,
        name: str,
        *,
        source_mesh_id: str,
        skin_binding_id: str,
        fabric_material_id: str = "",
        vertex_count: int | None = None,
        fixed_vertices: Iterable[int] = (),
        transition_vertices: Mapping[int, float] | None = None,
        folder: str | Path = "Assets/Cloth",
    ):
        properties: dict[str, Any] = {
            "source_mesh_id": str(source_mesh_id),
            "skin_binding_id": str(skin_binding_id),
            "fabric_material_id": str(fabric_material_id),
            "preserve_imported_skinning": True,
        }
        if vertex_count is not None:
            properties["property_maps"] = automatic_cloth_maps(
                vertex_count,
                fixed_vertices=fixed_vertices,
                transition_vertices=transition_vertices,
            ).property_maps
        receipt = self.assets.create_asset("tc.cloth", name, folder=folder, properties=properties)
        dependencies = [(str(source_mesh_id), "source_mesh"), (str(skin_binding_id), "skin_binding")]
        if fabric_material_id:
            dependencies.append((str(fabric_material_id), "fabric_material"))
        self.database.set_dependencies(receipt.asset_id, dependencies)
        return receipt

    def auto_setup_cloth(
        self,
        asset_id: str,
        vertex_count: int,
        *,
        fixed_vertices: Iterable[int] = (),
        transition_vertices: Mapping[int, float] | None = None,
        max_distance: float = 1.0,
    ) -> dict[str, Any]:
        receipt = automatic_cloth_maps(
            vertex_count,
            fixed_vertices=fixed_vertices,
            transition_vertices=transition_vertices,
            max_distance=max_distance,
        )
        self.set_properties(asset_id, {"property_maps": receipt.property_maps, "preserve_imported_skinning": True})
        return receipt.to_dict()

    def set_cloth_map(self, asset_id: str, map_name: str, values: Sequence[float]) -> dict[str, Any]:
        name = str(map_name).strip().casefold()
        if name not in CLOTH_MAPS:
            raise KeyError(f"Unknown cloth map: {map_name}")
        properties = self.properties(asset_id)
        maps = dict(properties.get("property_maps") or {})
        maps[name] = [float(value) for value in values]
        return self.set_properties(asset_id, {"property_maps": maps, "preserve_imported_skinning": True})

    def validate_cloth(self, asset_id: str, *, vertex_count: int | None = None) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.cloth":
            raise ValueError(f"Asset is not a cloth asset: {asset_id}")
        return [issue.__dict__.copy() for issue in validate_cloth_properties(self.properties(asset_id), vertex_count=vertex_count)]

    def cook_cloth(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type != "tc.cloth":
            raise ValueError(f"Asset is not a cloth asset: {asset_id}")
        payload = compile_cloth_payload(self.properties(asset_id), platform=platform, quality=quality)
        return self.database.store_derived(
            asset_id,
            f"cloth_runtime:{platform}:{quality}",
            payload,
            metadata={"platform": platform, "quality": quality, "preserved_imported_skinning": True},
            extension=".tcclothbin",
        )

    def create_physics_asset(
        self,
        name: str,
        *,
        skeleton_id: str,
        skeletal_mesh_id: str = "",
        preset: str = "balanced",
        folder: str | Path = "Assets/Physics",
    ):
        receipt = self.assets.create_asset("tc.physics_asset", name, folder=folder, properties={
            "skeleton_id": str(skeleton_id), "skeletal_mesh_id": str(skeletal_mesh_id), "preset": str(preset),
        })
        dependencies = [(str(skeleton_id), "skeleton")]
        if skeletal_mesh_id:
            dependencies.append((str(skeletal_mesh_id), "skeletal_mesh"))
        self.database.set_dependencies(receipt.asset_id, dependencies)
        return receipt

    def auto_setup_physics_asset(
        self,
        asset_id: str,
        joints: Mapping[str, Mapping[str, Any]],
        *,
        root_joint: str = "",
        preset: str | None = None,
        include_leaf_joints: bool = False,
    ) -> dict[str, Any]:
        properties = self.properties(asset_id)
        receipt = automatic_physics_asset(
            joints, root_joint=root_joint,
            preset=str(preset or properties.get("preset") or "balanced"),
            include_leaf_joints=include_leaf_joints,
        )
        self.set_properties(asset_id, {
            "bodies": receipt.bodies,
            "constraints": receipt.constraints,
            "animation_binding": receipt.animation_binding,
            "preset": str(preset or properties.get("preset") or "balanced"),
        })
        return receipt.to_dict()

    def create_physics_constraint(
        self,
        name: str,
        *,
        first_body: str,
        second_body: str,
        preset: str = "weld",
        settings: Mapping[str, Any] | None = None,
        folder: str | Path = "Assets/Physics",
    ):
        joint = constraint_from_preset(
            preset, constraint_id=name, first_body=first_body, second_body=second_body, settings=settings,
        )
        return self.assets.create_asset("tc.physics_constraint", name, folder=folder, properties={
            "constraint_id": name, "first_body": first_body, "second_body": second_body,
            "preset": preset, "joint": joint,
        })

    def validate_physics(self, asset_id: str) -> list[dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in {"tc.physics_asset", "tc.physics_constraint"}:
            raise ValueError(f"Asset is not a character physics asset or constraint: {asset_id}")
        validator = validate_physics_asset_properties if record.asset_type == "tc.physics_asset" else validate_constraint_properties
        return [issue.__dict__.copy() for issue in validator(self.properties(asset_id))]

    def cook_physics(self, asset_id: str, *, platform: str = "desktop", quality: str = "high") -> DerivedArtifact:
        record = self.database.asset(asset_id)
        if record is None or record.asset_type not in {"tc.physics_asset", "tc.physics_constraint"}:
            raise ValueError(f"Asset is not a character physics asset or constraint: {asset_id}")
        compiler = compile_physics_asset_payload if record.asset_type == "tc.physics_asset" else compile_constraint_payload
        kind = "physics_asset_runtime" if record.asset_type == "tc.physics_asset" else "physics_constraint_runtime"
        return self.database.store_derived(
            asset_id, f"{kind}:{platform}:{quality}",
            compiler(self.properties(asset_id), platform=platform, quality=quality),
            metadata={"platform": platform, "quality": quality}, extension=".tcphysicsbin",
        )

    def create_runtime_physics_joint(
        self, runtime_world: MutableMapping[str, Any], joint_id: str, first: str, second: str,
        *, joint_type: str = "fixed", preset: str = "", settings: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return create_physics_joint(runtime_world, joint_id, first, second, joint_type=joint_type,
                                    preset=preset, settings=settings)

    def edit_runtime_physics_joints(
        self, runtime_world: MutableMapping[str, Any], joint_ids: Iterable[str], changes: Mapping[str, Any],
    ) -> int:
        editor = PhysicsJointEditorModel(runtime_world); editor.selected_ids = [str(value) for value in joint_ids]
        return editor.edit_selected(dict(changes))

    def remove_runtime_physics_joint(self, runtime_world: MutableMapping[str, Any], joint_id: str) -> bool:
        return remove_physics_joint(runtime_world, joint_id)

    def generate_runtime_ragdoll(
        self, rig_graph: Any, runtime_world: dict[str, Any], *, root_joint: str = "",
        density: float = 985.0, include_leaf_joints: bool = False,
    ) -> dict[str, Any]:
        return generate_ragdoll(rig_graph, runtime_world, root_joint=root_joint, density=density,
                                include_leaf_joints=include_leaf_joints)

    def build_physics_stress_scene(self, scenario: str, *, count: int = 1000) -> dict[str, Any]:
        world = build_physics_stress_scene(scenario, count)
        return {"world": world, "audit": audit_physics_stress_scene(world)}

    def create_runtime_soft_body(
        self, vertices: Iterable[Sequence[float]], faces: Iterable[Sequence[int]], *,
        material: str = "jello", pinned_vertices: Iterable[int] = (), volume_compliance: float = 2.0e-7,
    ) -> Any:
        return create_soft_body_from_geometry(
            (tuple(map(float, point[:3])) for point in vertices),
            (tuple(map(int, face)) for face in faces), material=material,
            pinned_vertices=pinned_vertices, volume_compliance=volume_compliance,
        )

    def create_ocean_surface(
        self, preset: str = "open_ocean", *, seed: int = 1, wave_count: int = 12,
        controls: Mapping[str, float] | None = None,
    ) -> OceanSurface:
        return create_ocean_surface(preset, seed=seed, wave_count=wave_count, **dict(controls or {}))

    def sample_ocean_surface(self, ocean: OceanSurface, x: float, z: float, *, time_seconds: float | None = None) -> dict[str, Any]:
        return ocean.sample(x, z, time_seconds).to_dict()

    def generate_ocean_patch(
        self, ocean: OceanSurface, *, center: Sequence[float] = (0.0, 0.0),
        size: float = 20.0, rows: int = 32, columns: int = 32,
    ) -> dict[str, Any]:
        return ocean.mesh_patch(center=(float(center[0]), float(center[1])), size=size, rows=rows, columns=columns)

    def add_ocean_wake(
        self, ocean: OceanSurface, position: Sequence[float], velocity: Sequence[float], *,
        radius: float = 1.0, strength: float = 0.25, lifetime: float = 6.0,
    ) -> dict[str, Any]:
        return ocean.add_wake(
            (float(position[0]), float(position[1])), (float(velocity[0]), float(velocity[1])),
            radius=radius, strength=strength, lifetime=lifetime,
        ).__dict__.copy()

    def cook(self, asset_ids: Iterable[str], *, platform: str = "desktop", quality: str = "high") -> AssetCookReceipt:
        roots = tuple(dict.fromkeys(str(value) for value in asset_ids))
        for asset_id in self.database.dependency_closure(roots):
            record = self.database.asset(asset_id)
            if record is not None and record.asset_type == "tc.cloth":
                self.cook_cloth(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.physics_asset", "tc.physics_constraint"}:
                self.cook_physics(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.skeletal_mesh", "tc.skin_binding"}:
                self.cook_character_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.control_rig", "tc.ik_rig", "tc.ik_retargeter"}:
                self.cook_rig_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.geometry_optimization_profile":
                self.cook_geometry_optimization(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.groom", "tc.groom_binding", "tc.hair_material"}:
                self.cook_groom(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.animation_clip", "tc.blend_space", "tc.animation_mask", "tc.animation_controller"}:
                # Legacy template locomotion controllers are migrated in-memory by the animation service.
                self.cook_animation_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.effect_system":
                self.cook_effect_system(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in AUDIO_ASSET_TYPES:
                self.cook_audio_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in GAMEPLAY_FOUNDATION_TYPES:
                self.cook_gameplay_foundation_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.gameplay_class":
                self.compile_gameplay_class(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in BEHAVIOR_GRAPH_TYPES:
                self.cook_behavior_graph(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.image_project":
                self.cook_image_project(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in WORLD_ASSET_TYPES:
                self.compile_world_asset(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.procedural_graph":
                self.cook_procedural_graph(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type == "tc.prefab":
                self.cook_prefab(asset_id, platform=platform, quality=quality)
            elif record is not None and record.asset_type in {"tc.material", "tc.material_instance"}:
                self.cook_material(asset_id, platform=platform, quality=quality)
        return self.production.cook_manifest(roots, platform=platform, quality=quality)

    def capability_contract(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.editor_python_api.v1",
            "asset_operations": ["create_asset", "import_asset", "properties", "set_properties", "cook"],
            "launch_operations": ["audit_launch_readiness", "qualify_playable_project", "qualify_realtime_fx", "qualify_world_production", "qualify_content_production", "qualify_capability_evidence"],
            "prefab_operations": ["create_prefab", "create_prefab_variant", "resolve_prefab", "instantiate_prefab", "apply_prefab_overrides", "revert_prefab_overrides", "validate_prefab", "cook_prefab"],
            "material_operations": ["material_presets", "create_material", "apply_material_preset", "create_material_instance", "resolve_material", "set_material_instance_overrides", "revert_material_instance_overrides", "assign_material_texture", "material_graph_statistics", "validate_material", "cook_material"],
            "shader_operations": ["create_shader_graph", "validate_shader_graph", "compile_shader_graph", "shader_backend_capabilities"],
            "texture_operations": ["texture_import_settings", "set_texture_import_settings", "assign_material_texture"],
            "project_template_operations": ["available_game_templates", "create_game_project_from_template", "validate_playable_project"],
            "locomotion_operations": ["create_locomotion_controller", "validate_locomotion_controller", "cook_locomotion_controller"],
            "animation_operations": ["create_animation_clip", "create_blend_space", "create_animation_mask", "create_animation_controller", "animation_properties", "set_animation_properties", "validate_animation_asset", "evaluate_blend_space", "cook_animation_asset", "convert_unreal_animation", "convert_unity_animation", "convert_animation_export_file", "convert_live_unity_animation", "convert_live_unreal_animation", "export_animation_interchange", "import_animation_interchange"],
            "effect_operations": ["effect_presets", "effect_module_library", "create_effect_system", "apply_effect_preset", "effect_properties", "set_effect_properties", "validate_effect_system", "estimate_effect_cost", "cook_effect_system", "convert_unreal_effects", "convert_unity_effects"],
            "audio_operations": ["audio_clip_settings", "set_audio_clip_settings", "create_sound_cue", "create_audio_mixer", "create_audio_attenuation", "create_audio_reverb", "validate_audio_asset", "cook_audio_asset", "convert_unreal_audio", "convert_unity_audio"],
            "gameplay_foundation_operations": ["create_project_settings", "create_data_schema", "create_struct", "create_enum", "create_typed_data_asset", "create_data_table", "create_component_archetype", "create_character_definition", "resolve_data_schema", "validate_gameplay_foundation_asset", "cook_gameplay_foundation_asset", "convert_unreal_data_assets", "convert_unity_scriptable_objects"],
            "gameplay_class_operations": ["create_gameplay_class", "resolve_gameplay_class", "validate_gameplay_class", "compile_gameplay_class", "debug_gameplay_class", "begin_gameplay_class_debug_session", "gameplay_class_debug_command", "list_gameplay_class_debug_sessions", "end_gameplay_class_debug_session"],
            "behavior_graph_operations": ["create_behavior", "create_gameplay_graph", "validate_behavior_graph", "cook_behavior_graph", "execute_behavior_graph"],
            "image_project_operations": ["create_image_project", "validate_image_project", "flatten_image_project", "cook_image_project"],
            "world_operations": ["create_world_asset", "get_world_asset", "update_world_asset", "validate_world_asset", "preview_world_asset", "compile_world_asset", "sculpt_terrain", "paint_terrain_layer", "paint_foliage", "world_asset_visualization", "build_world_backend", "open_world_streaming_runtime"],
            "procedural_geometry_operations": ["create_procedural_graph", "get_procedural_graph", "set_procedural_graph", "validate_procedural_graph", "cook_procedural_graph", "procedural_operation_catalog", "procedural_execution_plan", "procedural_native_document", "import_procedural_native_document", "procedural_diagnostics", "cook_procedural_tasks", "step_procedural_simulation", "reset_procedural_simulation"],
            "starter_character_operations": ["create_starter_character"],
            "cloth_operations": ["create_cloth", "create_fabric_material", "auto_setup_cloth", "set_cloth_map", "validate_cloth", "cook_cloth"],
            "physics_operations": ["create_physics_asset", "auto_setup_physics_asset", "create_physics_constraint", "validate_physics", "cook_physics", "create_runtime_physics_joint", "edit_runtime_physics_joints", "remove_runtime_physics_joint", "generate_runtime_ragdoll", "build_physics_stress_scene"],
            "simulation_authoring_operations": ["create_runtime_soft_body", "create_ocean_surface", "sample_ocean_surface", "generate_ocean_patch", "add_ocean_wake"],
            "character_operations": ["create_skin_binding", "create_skeletal_mesh_asset", "assign_skin_binding", "generate_character_lods", "generate_mesh_lod_geometry", "validate_character_asset", "cook_character_asset"],
            "rig_operations": ["create_control_rig", "create_ik_rig", "create_ik_retargeter", "auto_setup_ik_rig", "auto_map_ik_retargeter", "validate_rig_asset", "cook_rig_asset"],
            "geometry_optimization_operations": ["create_geometry_optimization_profile", "assign_geometry_optimization_profile", "plan_geometry_optimization", "validate_geometry_optimization", "cook_geometry_optimization", "generate_mesh_lod_geometry"],
            "groom_operations": ["create_groom", "create_groom_binding", "create_hair_material", "generate_groom_lods", "project_groom_binding", "validate_groom", "cook_groom"],
            "cloth_maps": list(CLOTH_MAPS),
            "ui_api_parity": True,
        }

    def audit_launch_readiness(self, *, production: bool = False) -> dict[str, Any]:
        from tech_connector.game_engine.integration.launch_readiness_service import audit_launch_readiness

        return audit_launch_readiness(self.project_root, editor_api=self, production=production)

    def qualify_playable_project(
        self, player_executable: str | Path, *, frames: int = 120,
        budgets_ms: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        from tech_connector.game_engine.integration.playable_project_qualification_service import qualify_playable_project

        source_root = Path(__file__).resolve().parents[3]
        output = self.project_root / ".tech_connector" / "qualification" / "playable_project"
        return qualify_playable_project(
            source_root, output, player_executable, frames=frames, budgets_ms=budgets_ms,
        )

    def qualify_realtime_fx(
        self, *, presets: Sequence[str] | None = None, frames: int = 120,
        frame_budget_ms: float = 16.667, maximum_particles: int = 2_048,
        maximum_preset_seconds: float = 8.0,
    ) -> dict[str, Any]:
        from tech_connector.game_engine.integration.fx_qualification_service import DEFAULT_PRESETS, qualify_realtime_fx

        source_root = Path(__file__).resolve().parents[3]
        output = self.project_root / ".tech_connector" / "qualification" / "realtime_fx"
        return qualify_realtime_fx(
            source_root, output, presets=tuple(presets or DEFAULT_PRESETS),
            frames=frames, frame_budget_ms=frame_budget_ms, maximum_particles=maximum_particles,
            maximum_preset_seconds=maximum_preset_seconds,
        )

    def qualify_world_production(self, *, maximum_total_seconds: float = 30.0) -> dict[str, Any]:
        from tech_connector.game_engine.integration.world_production_qualification_service import qualify_world_production

        source_root = Path(__file__).resolve().parents[3]
        output = self.project_root / ".tech_connector" / "qualification" / "world_production"
        return qualify_world_production(source_root, output, maximum_total_seconds=maximum_total_seconds)

    def qualify_content_production(self, *, maximum_total_seconds: float = 30.0) -> dict[str, Any]:
        from tech_connector.game_engine.integration.content_production_qualification_service import qualify_content_production
        source_root = Path(__file__).resolve().parents[3]
        output = self.project_root / ".tech_connector" / "qualification" / "content_production"
        return qualify_content_production(source_root, output, maximum_total_seconds=maximum_total_seconds)

    def qualify_capability_evidence(self, *, timeout_seconds: float = 300.0) -> dict[str, Any]:
        from tech_connector.game_engine.integration.capability_qualification_service import qualify_capability_evidence
        source_root = Path(__file__).resolve().parents[3]
        output = self.project_root / ".tech_connector" / "qualification" / "capabilities"
        return qualify_capability_evidence(source_root, output, timeout_seconds=timeout_seconds)

    def _authored_payload(self, asset_id: str) -> tuple[Any, dict[str, Any]]:
        record = self.database.asset(asset_id)
        if record is None:
            raise KeyError(f"Unknown asset: {asset_id}")
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Asset is not an authored JSON asset: {record.source_path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("properties"), dict):
            raise ValueError(f"Asset has no editable property payload: {record.source_path}")
        return record, payload

    @staticmethod
    def _write_payload(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def open_editor_api(project_root: str | Path, **options: Any) -> TCEditorAPI:
    return TCEditorAPI(project_root, **options)


__all__ = ["TCEditorAPI", "open_editor_api"]
