"""Canonical asset type descriptors shared by authoring, import, and runtime UX."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AssetTypeDescriptor:
    type_id: str
    display_name: str
    family: str
    extensions: tuple[str, ...] = ()
    icon: str = "asset"
    color: str = "#8da7b8"
    schema_version: int = 1
    creatable: bool = False
    importable: bool = False
    editor_id: str = "generic"
    previewer_id: str = "generic"
    inspector_id: str = "generic"
    runtime_loader_id: str = "data"
    cooker_id: str = "data"
    hot_reload_class: str = "restart_required"
    tags: tuple[str, ...] = field(default_factory=tuple)
    standard_editor_name: str = "Asset Editor"
    suite_name: str = ""
    maturity: str = "authoring_preview"
    python_api_namespace: str = "editor.assets"
    node_graph_kind: str = ""
    bake_modes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized = str(self.type_id).strip().casefold()
        if not normalized.startswith("tc.") or any(char.isspace() for char in normalized):
            raise ValueError("Asset type IDs must be stable, lowercase 'tc.*' identifiers.")
        object.__setattr__(self, "type_id", normalized)
        object.__setattr__(
            self,
            "extensions",
            tuple(sorted({value.casefold() if value.startswith(".") else f".{value.casefold()}" for value in self.extensions})),
        )
        maturity = str(self.maturity).strip().casefold()
        if maturity not in {"experimental", "authoring_preview", "runtime_ready", "production_ready"}:
            raise ValueError(f"Unsupported asset maturity: {self.maturity}")
        object.__setattr__(self, "maturity", maturity)
        object.__setattr__(self, "bake_modes", tuple(dict.fromkeys(str(value).strip() for value in self.bake_modes if str(value).strip())))


class AssetTypeRegistry:
    def __init__(self, descriptors: Iterable[AssetTypeDescriptor] = ()) -> None:
        self._types: dict[str, AssetTypeDescriptor] = {}
        self._extensions: dict[str, list[str]] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: AssetTypeDescriptor, *, replace: bool = False) -> AssetTypeDescriptor:
        type_id = descriptor.type_id
        if type_id in self._types and not replace:
            raise KeyError(f"Asset type is already registered: {type_id}")
        if type_id in self._types:
            self.unregister(type_id)
        self._types[type_id] = descriptor
        for extension in descriptor.extensions:
            self._extensions.setdefault(extension, []).append(type_id)
        return descriptor

    def unregister(self, type_id: str) -> None:
        descriptor = self._types.pop(str(type_id).casefold(), None)
        if descriptor is None:
            return
        for extension in descriptor.extensions:
            values = self._extensions.get(extension, [])
            self._extensions[extension] = [value for value in values if value != descriptor.type_id]
            if not self._extensions[extension]:
                self._extensions.pop(extension, None)

    def descriptor(self, type_id: str) -> AssetTypeDescriptor | None:
        return self._types.get(str(type_id).casefold())

    def require(self, type_id: str) -> AssetTypeDescriptor:
        descriptor = self.descriptor(type_id)
        if descriptor is None:
            raise KeyError(f"Unknown asset type: {type_id}")
        return descriptor

    def all(self, *, family: str = "", creatable: bool | None = None) -> tuple[AssetTypeDescriptor, ...]:
        values = list(self._types.values())
        if family:
            values = [item for item in values if item.family.casefold() == str(family).casefold()]
        if creatable is not None:
            values = [item for item in values if item.creatable is bool(creatable)]
        return tuple(sorted(values, key=lambda item: (item.family.casefold(), item.display_name.casefold())))

    def infer(self, path: str | Path) -> AssetTypeDescriptor | None:
        candidate = Path(path)
        suffixes = ["".join(candidate.suffixes[-count:]).casefold() for count in range(len(candidate.suffixes), 0, -1)]
        for extension in suffixes:
            type_ids = self._extensions.get(extension, ())
            if type_ids:
                return self._types[type_ids[0]]
        return None

    def families(self) -> tuple[str, ...]:
        return tuple(sorted({item.family for item in self._types.values()}, key=str.casefold))


def _type(
    type_id: str,
    name: str,
    family: str,
    extensions: tuple[str, ...] = (),
    *,
    creatable: bool = False,
    importable: bool = False,
    editor: str = "generic",
    preview: str = "generic",
    loader: str = "data",
    cooker: str = "data",
    hot_reload: str = "restart_required",
    color: str = "#8da7b8",
    standard_editor: str = "Asset Editor",
    suite: str = "",
    maturity: str = "authoring_preview",
    python_api: str = "editor.assets",
    node_graph: str = "",
    bake_modes: tuple[str, ...] = (),
) -> AssetTypeDescriptor:
    return AssetTypeDescriptor(
        type_id=type_id, display_name=name, family=family, extensions=extensions,
        icon=type_id.removeprefix("tc."), color=color, schema_version=1,
        creatable=creatable, importable=importable, editor_id=editor,
        previewer_id=preview, inspector_id="schema", runtime_loader_id=loader,
        cooker_id=cooker, hot_reload_class=hot_reload,
        standard_editor_name=standard_editor, suite_name=suite, maturity=maturity,
        python_api_namespace=python_api, node_graph_kind=node_graph,
        bake_modes=bake_modes,
    )


BUILTIN_ASSET_TYPES = (
    _type("tc.level", "Level", "World", (".tcscene",), creatable=True, importable=True, editor="garden", preview="scene", loader="level", cooker="level", hot_reload="state_migration", color="#59bfff"),
    _type("tc.terrain", "Terrain", "World", (".terrain.tcasset",), creatable=True, importable=True, editor="terrain", preview="terrain", loader="terrain", cooker="world", hot_reload="state_migration", color="#79b85a", standard_editor="Terrain Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "heightfield", "collision", "navigation")),
    _type("tc.foliage_type", "Foliage Type", "World", (".foliage.tcasset",), creatable=True, editor="foliage", preview="mesh", loader="foliage", cooker="world", hot_reload="hot_swap", color="#53a867", standard_editor="Foliage Type Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "instances")),
    _type("tc.biome", "Biome", "World", (".biome.tcasset",), creatable=True, editor="biome", preview="terrain", loader="biome", cooker="world", hot_reload="state_migration", color="#3c9970", standard_editor="Biome Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "instances")),
    _type("tc.navigation_mesh", "Navigation Mesh", "World", (".navmesh.tcasset",), creatable=True, editor="navigation", preview="navigation", loader="navigation", cooker="world", hot_reload="state_migration", color="#55c8cc", standard_editor="Navigation Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "tiles")),
    _type("tc.lighting_scenario", "Lighting Scenario", "World", (".lighting.tcasset",), creatable=True, editor="lighting", preview="scene", loader="lighting", cooker="world", hot_reload="state_migration", color="#f3cf62", standard_editor="Lighting Build Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "lightmaps", "reflections", "volumetrics")),
    _type("tc.data_layer", "Data Layer", "World", (".datalayer.tcasset",), creatable=True, editor="data_layer", preview="scene", loader="data_layer", cooker="world", hot_reload="state_migration", color="#5d9fd6", standard_editor="Data Layer Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime",)),
    _type("tc.hlod_layer", "HLOD Layer", "World", (".hlod.tcasset",), creatable=True, editor="hlod", preview="mesh", loader="hlod", cooker="world", hot_reload="restart_required", color="#6d8ebf", standard_editor="HLOD Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("merged_mesh", "simplified_mesh", "impostor")),
    _type("tc.world_partition", "World Partition", "World", (".worldpartition.tcasset",), creatable=True, editor="world_partition", preview="scene", loader="world_partition", cooker="world", hot_reload="restart_required", color="#527da7", standard_editor="World Partition Editor", suite="Garden", maturity="authoring_preview", python_api="editor.world", bake_modes=("runtime", "streaming_manifest")),
    _type("tc.procedural_graph", "Procedural Geometry Graph", "World", (".procedural.tcasset",), creatable=True, importable=True, editor="procedural_geometry", preview="scene", loader="procedural_geometry", cooker="procedural_geometry", hot_reload="state_migration", color="#42c7a5", standard_editor="Procedural Geometry Editor", suite="Garden", maturity="authoring_preview", python_api="editor.procedural", node_graph="procedural_geometry", bake_modes=("runtime", "baked_mesh", "instances", "collision", "navigation")),
    _type("tc.level_sequence", "Level Sequence", "Cinematics", (".sequence.tcasset",), creatable=True, importable=True, editor="sequence", preview="sequence", loader="level_sequence", cooker="level_sequence", hot_reload="hot_swap", color="#dc8cff", standard_editor="Sequence Editor", suite="Chronos", maturity="runtime_ready", python_api="editor.sequence", bake_modes=("runtime", "render_queue", "animation_clip")),
    _type("tc.prefab", "Prefab", "World", (".tcprefab",), creatable=True, importable=True, editor="prefab", preview="scene", loader="prefab", cooker="prefab", hot_reload="state_migration", color="#6ed6c2"),
    _type("tc.static_mesh", "Static Mesh", "Geometry", (".fbx", ".obj", ".gltf", ".glb", ".usd", ".usdc", ".usda"), importable=True, editor="static_mesh", preview="mesh", loader="mesh", cooker="mesh", hot_reload="hot_swap", color="#7dc4ff"),
    _type("tc.skeletal_mesh", "Skeletal Mesh", "Geometry", (".skmesh.tcasset",), creatable=True, importable=True, editor="skeletal_mesh", preview="skinned_mesh", loader="skeletal_mesh", cooker="skeletal_mesh", hot_reload="state_migration", color="#75a9ff"),
    _type("tc.geometry_optimization_profile", "Geometry Optimization Profile", "Geometry", (".geoopt.tcasset",), creatable=True, editor="geometry_optimization", preview="mesh", loader="none", cooker="geometry_optimization", hot_reload="restart_required", color="#58c8d8", standard_editor="Geometry Optimization Editor", suite="Forge", maturity="authoring_preview", python_api="editor.geometry_optimization", bake_modes=("reduction", "remeshing", "aggregation", "impostor", "occlusion_mesh")),
    _type("tc.skeleton", "Skeleton", "Animation", (".skeleton.tcasset",), creatable=True, importable=True, editor="skeleton", preview="skeleton", loader="skeleton", cooker="skeleton", hot_reload="state_migration", color="#c79cff"),
    _type("tc.skin_binding", "Skin Binding", "Animation", (".tcskin", ".tcskin.json"), creatable=True, importable=True, editor="skin_binding", preview="skinned_mesh", loader="skin_binding", cooker="rig_blob", hot_reload="state_migration", color="#d3a5ff"),
    _type("tc.cloth", "Cloth", "Animation", (".cloth.tcasset",), creatable=True, importable=True, editor="cloth", preview="cloth", loader="cloth", cooker="cloth", hot_reload="state_migration", color="#80d8ff", standard_editor="Cloth Editor", suite="Loom", maturity="experimental", python_api="editor.cloth", bake_modes=("runtime", "simulation_cache", "geometry_cache", "vertex_animation_texture")),
    _type("tc.fabric_material", "Fabric Material", "Animation", (".fabric.tcasset",), creatable=True, editor="fabric_material", preview="cloth", loader="fabric_material", cooker="cloth", hot_reload="hot_swap", color="#9be7c4", standard_editor="Fabric Material Editor", suite="Loom", maturity="experimental", python_api="editor.cloth", bake_modes=("runtime",)),
    _type("tc.groom", "Groom", "Animation", (".groom.tcasset",), creatable=True, importable=True, editor="groom", preview="groom", loader="groom", cooker="groom", hot_reload="state_migration", color="#d7b98e", standard_editor="Groom Editor", suite="Loom", maturity="experimental", python_api="editor.groom", bake_modes=("runtime", "cards", "mesh", "groom_cache")),
    _type("tc.groom_binding", "Groom Binding", "Animation", (".groombinding.tcasset",), creatable=True, editor="groom_binding", preview="groom", loader="groom_binding", cooker="groom", hot_reload="state_migration", color="#c9a879", standard_editor="Groom Binding Editor", suite="Loom", maturity="experimental", python_api="editor.groom", bake_modes=("runtime",)),
    _type("tc.hair_material", "Hair Material", "Rendering", (".hairmaterial.tcasset",), creatable=True, editor="hair_material", preview="groom", loader="hair_material", cooker="groom", hot_reload="hot_swap", color="#e7c99f", standard_editor="Hair Material Editor", suite="Loom", maturity="experimental", python_api="editor.groom", bake_modes=("runtime", "cards")),
    _type("tc.animation_clip", "Animation Clip", "Animation", (".anim.tcasset", ".bvh", ".abc"), creatable=True, importable=True, editor="animation", preview="animation", loader="animation", cooker="animation", hot_reload="hot_swap", color="#d8a0ff", standard_editor="Animation Clip Editor", suite="Chronos", maturity="runtime_ready", python_api="editor.animation", bake_modes=("runtime", "compressed_clip")),
    _type("tc.blend_space", "Blend Space", "Animation", (".blendspace.tcasset",), creatable=True, editor="blend_space", preview="animation", loader="blend_space", cooker="animation", hot_reload="hot_swap", color="#dd9cff", standard_editor="Blend Space Editor", suite="Chronos", maturity="runtime_ready", python_api="editor.animation", bake_modes=("runtime",)),
    _type("tc.animation_mask", "Animation Mask", "Animation", (".animmask.tcasset",), creatable=True, editor="animation_mask", preview="skeleton", loader="animation_mask", cooker="animation", hot_reload="hot_swap", color="#ca8fff", standard_editor="Animation Mask Editor", suite="Chronos", maturity="runtime_ready", python_api="editor.animation", bake_modes=("runtime",)),
    _type("tc.animation_controller", "Animation Controller", "Animation", (".animgraph.tcasset",), creatable=True, editor="animation_graph", preview="animation", loader="animation_graph", cooker="graph", hot_reload="state_migration", color="#e2a3ff", standard_editor="Animation Controller Editor", suite="Chronos", maturity="runtime_ready", python_api="editor.animation", node_graph="animation", bake_modes=("runtime",)),
    _type("tc.procedural_animation_profile", "Procedural Animation Profile", "Animation", (".procanim.tcasset",), creatable=True, editor="procedural_animation", preview="animation", loader="procedural_animation", cooker="data", hot_reload="state_migration", color="#cf8fff"),
    _type("tc.control_rig", "Control Rig", "Animation", (".controlrig.tcasset",), creatable=True, importable=True, editor="control_rig", preview="animation", loader="control_rig", cooker="rig_graph", hot_reload="state_migration", color="#d59cff", standard_editor="Control Rig Editor", suite="Chronos", maturity="experimental", python_api="editor.rig", node_graph="control_rig", bake_modes=("runtime", "animation_clip")),
    _type("tc.ik_rig", "IK Rig", "Animation", (".ikrig.tcasset",), creatable=True, editor="ik_rig", preview="animation", loader="ik_rig", cooker="rig_graph", hot_reload="state_migration", color="#c991ff", standard_editor="IK Rig Editor", suite="Chronos", maturity="experimental", python_api="editor.rig", bake_modes=("runtime",)),
    _type("tc.ik_retargeter", "IK Retargeter", "Animation", (".ikretarget.tcasset",), creatable=True, editor="ik_retargeter", preview="animation", loader="ik_retargeter", cooker="rig_graph", hot_reload="state_migration", color="#bd86ff", standard_editor="IK Retargeter Editor", suite="Chronos", maturity="experimental", python_api="editor.rig", bake_modes=("runtime", "animation_clip")),
    _type("tc.material", "Material", "Rendering", (".material.tcasset",), creatable=True, importable=True, editor="material_graph", preview="material", loader="material", cooker="material", hot_reload="hot_swap", color="#f3b45f", standard_editor="Material Editor", suite="Midas", maturity="runtime_ready", python_api="editor.material", node_graph="material", bake_modes=("runtime", "shader_library")),
    _type("tc.material_instance", "Material Instance", "Rendering", (".matinst.tcasset",), creatable=True, editor="material_instance", preview="material", loader="material", cooker="material_instance", hot_reload="hot_swap", color="#ffc66d", standard_editor="Material Instance Editor", suite="Midas", maturity="runtime_ready", python_api="editor.material", bake_modes=("runtime", "shader_library")),
    _type("tc.shader_graph", "Shader Graph", "Rendering", (".shadergraph.tcasset", ".vert", ".frag", ".comp", ".glsl", ".hlsl"), creatable=True, importable=True, editor="shader_graph", preview="material", loader="shader", cooker="shader", hot_reload="hot_swap", color="#ff9f5a", standard_editor="Shader Graph Editor", suite="Midas", maturity="authoring_preview", python_api="editor.material", node_graph="shader", bake_modes=("runtime", "shader_library")),
    _type("tc.texture", "Texture", "Rendering", (".png", ".jpg", ".jpeg", ".webp", ".tga", ".tif", ".tiff", ".bmp", ".dds", ".exr", ".hdr", ".ktx", ".ktx2"), importable=True, editor="texture", preview="image", loader="texture", cooker="texture", hot_reload="hot_swap", color="#e5c45c"),
    _type("tc.image_project", "Image Project", "Rendering", (".tcimg",), creatable=True, importable=True, editor="ophanim", preview="image", loader="texture", cooker="texture", hot_reload="hot_swap", color="#f0cb55"),
    _type("tc.collision", "Collision Geometry", "Physics", (".collision.tcasset",), creatable=True, importable=True, editor="collision", preview="collision", loader="collision", cooker="collision", hot_reload="state_migration", color="#7ee787"),
    _type("tc.physics_asset", "Physics Asset / Ragdoll", "Physics", (".physicsasset.tcasset",), creatable=True, editor="physics_asset", preview="physics", loader="physics_asset", cooker="physics_asset", hot_reload="state_migration", color="#6edb91", standard_editor="Physics Asset Editor", suite="Garden", maturity="experimental", python_api="editor.physics", bake_modes=("runtime",)),
    _type("tc.physics_constraint", "Physics Constraint", "Physics", (".constraint.tcasset",), creatable=True, editor="physics_constraint", preview="physics", loader="physics_constraint", cooker="physics_constraint", hot_reload="state_migration", color="#75e39d", standard_editor="Physics Constraint Editor", suite="Garden", maturity="experimental", python_api="editor.physics", bake_modes=("runtime",)),
    _type("tc.physical_material", "Physical Material", "Physics", (".physmat.tcasset",), creatable=True, editor="physical_material", preview="physics", loader="physical_material", cooker="data", hot_reload="hot_swap", color="#65d48c"),
    _type("tc.physics_scene", "Physics Scene", "Physics", (".physics.tcasset",), creatable=True, editor="physics_scene", preview="physics", loader="physics_scene", cooker="data", hot_reload="state_migration", color="#59cc82"),
    _type("tc.vehicle_rig", "Vehicle Rig", "Physics", (".vehicle.tcasset",), creatable=True, editor="vehicle_rig", preview="physics", loader="vehicle_rig", cooker="data", hot_reload="state_migration", color="#70d89a"),
    _type("tc.effect_system", "Effect System", "FX", (".tcfx",), creatable=True, importable=True, editor="effects", preview="effects", loader="effects", cooker="effects", hot_reload="hot_swap", color="#56e0e0", standard_editor="Effect System Editor", suite="Flux", maturity="runtime_ready", python_api="editor.effects", node_graph="effect_module", bake_modes=("runtime", "simulation_cache", "flipbook", "vertex_animation_texture")),
    _type("tc.simulation_profile", "Simulation Profile", "FX", (".tcsim",), creatable=True, editor="simulation", preview="simulation", loader="simulation", cooker="simulation", hot_reload="hot_swap", color="#4dd5c7"),
    _type("tc.audio_clip", "Audio Clip", "Audio", (".wav", ".ogg", ".mp3", ".flac", ".m4a", ".aac"), importable=True, editor="audio", preview="audio", loader="audio", cooker="audio", hot_reload="hot_swap", color="#ff83b7", standard_editor="Audio Clip Editor", suite="Resonance", maturity="runtime_ready", python_api="editor.audio", bake_modes=("runtime", "streaming")),
    _type("tc.sound_cue", "Sound Cue", "Audio", (".soundcue.tcasset",), creatable=True, editor="sound_cue", preview="audio", loader="sound_cue", cooker="audio", hot_reload="hot_swap", color="#ff72aa", standard_editor="Sound Cue Editor", suite="Resonance", maturity="runtime_ready", python_api="editor.audio", node_graph="audio", bake_modes=("runtime",)),
    _type("tc.audio_mixer", "Audio Mixer", "Audio", (".audiomixer.tcasset",), creatable=True, editor="audio_mixer", preview="audio", loader="audio_mixer", cooker="audio", hot_reload="hot_swap", color="#f66fa4", standard_editor="Audio Mixer", suite="Resonance", maturity="runtime_ready", python_api="editor.audio", node_graph="audio_mixer", bake_modes=("runtime",)),
    _type("tc.audio_attenuation", "Audio Attenuation", "Audio", (".attenuation.tcasset",), creatable=True, editor="audio_attenuation", preview="audio", loader="audio_attenuation", cooker="audio", hot_reload="hot_swap", color="#f287b3", standard_editor="Audio Attenuation Editor", suite="Resonance", maturity="runtime_ready", python_api="editor.audio", bake_modes=("runtime",)),
    _type("tc.audio_reverb", "Audio Reverb", "Audio", (".reverb.tcasset",), creatable=True, editor="audio_reverb", preview="audio", loader="audio_reverb", cooker="audio", hot_reload="hot_swap", color="#d875aa", standard_editor="Audio Reverb Editor", suite="Resonance", maturity="runtime_ready", python_api="editor.audio", bake_modes=("runtime", "impulse_response")),
    _type("tc.behavior", "Behavior Script", "Gameplay", (".py", ".lua", ".cs", ".behavior.tcasset"), creatable=True, importable=True, editor="code_graph", preview="data", loader="behavior", cooker="script", hot_reload="hot_swap", color="#6fb8ff"),
    _type("tc.gameplay_graph", "Gameplay Graph", "Gameplay", (".gameplay.tcasset",), creatable=True, editor="gameplay_graph", preview="graph", loader="gameplay_graph", cooker="graph", hot_reload="state_migration", color="#719cff"),
    _type("tc.gameplay_class", "Gameplay Class", "Gameplay", (".gameclass.tcasset",), creatable=True, editor="gameplay_class", preview="graph", loader="gameplay_class", cooker="gameplay_class", hot_reload="state_migration", color="#688cff", standard_editor="Gameplay Class Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay_class", node_graph="gameplay", bake_modes=("runtime",)),
    _type("tc.project_settings", "Project Settings", "Project", (".projectsettings.tcasset",), creatable=True, editor="project_settings", preview="data", loader="project_settings", cooker="gameplay_foundation", hot_reload="restart_required", color="#62b5ff", standard_editor="Project Settings", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.data_schema", "Data Schema", "Gameplay", (".schema.tcasset",), creatable=True, editor="data_schema", preview="data", loader="data_schema", cooker="gameplay_foundation", hot_reload="state_migration", color="#9cafff", standard_editor="Data Schema Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.struct", "Struct", "Gameplay", (".struct.tcasset",), creatable=True, editor="data_schema", preview="data", loader="struct", cooker="gameplay_foundation", hot_reload="state_migration", color="#a9b8ff", standard_editor="Struct Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.enum", "Enum", "Gameplay", (".enum.tcasset",), creatable=True, editor="enum", preview="data", loader="enum", cooker="gameplay_foundation", hot_reload="state_migration", color="#b5c0ff", standard_editor="Enum Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.data", "Data Asset", "Gameplay", (".data.tcasset", ".json", ".csv"), creatable=True, importable=True, editor="data", preview="data", loader="data", cooker="gameplay_foundation", hot_reload="hot_swap", color="#91a7ff", standard_editor="Data Asset Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.data_table", "Data Table", "Gameplay", (".datatable.tcasset",), creatable=True, importable=True, editor="data_table", preview="data", loader="data_table", cooker="gameplay_foundation", hot_reload="hot_swap", color="#86a4ff", standard_editor="Data Table Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.component_archetype", "Component Archetype", "Gameplay", (".component.tcasset",), creatable=True, editor="component_archetype", preview="data", loader="component_archetype", cooker="gameplay_foundation", hot_reload="state_migration", color="#789cff", standard_editor="Component Archetype Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.character_definition", "Character Definition", "Gameplay", (".character.tcasset",), creatable=True, editor="character_definition", preview="skinned_mesh", loader="character_definition", cooker="gameplay_foundation", hot_reload="state_migration", color="#6f92ff", standard_editor="Character Definition Editor", suite="Kingdom", maturity="runtime_ready", python_api="editor.gameplay", bake_modes=("runtime",)),
    _type("tc.input_map", "Input Map", "Gameplay", (".input.tcasset",), creatable=True, editor="input", preview="data", loader="input", cooker="data", hot_reload="hot_swap", color="#84a2ff"),
    _type("tc.game_ruleset", "Game Ruleset", "Gameplay", (".rules.tcasset",), creatable=True, editor="ruleset", preview="data", loader="ruleset", cooker="data", hot_reload="state_migration", color="#7598ff"),
    _type("tc.build_profile", "Build Profile", "Build", (".build.tcasset",), creatable=True, editor="build_profile", preview="data", loader="none", cooker="build", hot_reload="restart_required", color="#b6bec8"),
    _type("tc.video", "Video", "Media", (".mp4", ".mov", ".webm", ".mkv", ".avi", ".gif", ".apng"), importable=True, editor="media", preview="video", loader="media", cooker="media", hot_reload="hot_swap", color="#ff9db0"),
    _type("tc.font", "Font", "UI", (".ttf", ".otf", ".woff", ".woff2"), importable=True, editor="font", preview="font", loader="font", cooker="font", hot_reload="hot_swap", color="#e4d3ff"),
)


BUILTIN_ASSET_TYPE_REGISTRY = AssetTypeRegistry(BUILTIN_ASSET_TYPES)


def builtin_asset_type_registry() -> AssetTypeRegistry:
    """Return an independent registry so plugins can extend it safely."""
    return AssetTypeRegistry(BUILTIN_ASSET_TYPES)
