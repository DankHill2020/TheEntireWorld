"""Typed Unreal operation catalog for safe UI-driven prototyping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

PROJECT_SCAN_ASSET_CLASSES = [
    "Skeleton",
    "SkeletalMesh",
    "AnimSequence",
    "AnimBlueprint",
    "BlendSpace",
    "PoseSearchDatabase",
    "PoseSearchSchema",
    "Blueprint",
    "World",
    "DataAsset",
    "InputAction",
    "InputMappingContext",
    "GameplayAbilityBlueprint",
    "GameplayEffect",
    "StaticMesh",
    "Material",
    "Texture2D",
]

UNREAL_PROTOTYPE_VERBS = (
    "prototype",
    "create",
    "implement",
    "build",
    "make",
    "add",
    "set up",
    "setup",
    "connect",
    "attach",
    "link",
    "wire",
    "bind",
)

UNREAL_PROTOTYPE_FEATURE_ALIASES = {
    "rock_climbing": (
        "rock climbing",
        "climbing",
        "climb",
        "ledge grab",
        "mantle",
        "mantling",
    ),
    "motion_matching_locomotion": ("motion matching", "pose search", "motion matched", "locomotion", "locomotion template"),
    "combat_combo": ("combat combo", "combo attack", "melee combo", "attack chain", "combat", "combat template"),
    "time_rewind": ("rewind", "time rewind", "personal rewind", "world rewind"),
    "dash": ("dash", "air dash", "dodge"),
    "interaction": ("interact", "interaction", "pickup", "usable"),
}

UNREAL_DEBUG_TERMS = (
    "debug",
    "diagnose",
    "what is broken",
    "what's broken",
    "broken",
    "fix",
    "validate",
    "errors",
    "warnings",
    "compile errors",
    "not working",
    "failing",
    "full project",
    "whole project",
)


@dataclass(frozen=True)
class UnrealOperation:
    key: str
    label: str
    function: str
    required: tuple[str, ...] = ()
    optional: dict[str, Any] = field(default_factory=dict)
    mutates_project: bool = False
    description: str = ""


UNREAL_OPERATIONS: dict[str, UnrealOperation] = {
    "project.snapshot": UnrealOperation(
        key="project.snapshot",
        label="Unreal Project Snapshot",
        function="ai_studio.synthetic.project_snapshot",
        optional={"directory": "/Game/"},
        description="Gather loaded-level state plus core project asset inventory for model context.",
    ),
    "level.scan_loaded": UnrealOperation(
        key="level.scan_loaded",
        label="Unreal Loaded Level Scan",
        function="unreal_tools.level.scan_loaded_level",
        description="Return the current level, loaded actors, components, tags, selected actors, and streaming levels.",
    ),
    "navigation.open_content_browser": UnrealOperation(
        key="navigation.open_content_browser",
        label="Unreal Open Content Browser",
        function="unreal_tools.navigation.open_content_browser",
        required=("folder_path",),
        optional={"new_browser": False},
        description="Open or focus an Unreal Content Browser at a requested package folder.",
    ),
    "navigation.open_asset": UnrealOperation(
        key="navigation.open_asset",
        label="Unreal Open Asset",
        function="unreal_tools.navigation.open_asset",
        required=("asset_path",),
        description="Open an Unreal asset editor for a requested package path.",
    ),
    "navigation.open_window": UnrealOperation(
        key="navigation.open_window",
        label="Unreal Open Editor Window",
        function="unreal_tools.navigation.open_window",
        required=("window_name",),
        description="Open a known Unreal editor tab or tool window by name.",
    ),
    "navigation.load_level": UnrealOperation(
        key="navigation.load_level",
        label="Unreal Load Level",
        function="unreal_tools.navigation.load_level",
        required=("level_path",),
        description="Load an Unreal map or level package in the editor.",
    ),
    "assets.dependencies": UnrealOperation(
        key="assets.dependencies",
        label="Unreal Asset Dependencies",
        function="unreal_tools.assets.get_dependencies",
        required=("asset_path",),
        optional={"recursive": True},
        description="Return dependency and reference data for a specific asset.",
    ),
    "assets.inspect": UnrealOperation(
        key="assets.inspect",
        label="Unreal Inspect Asset",
        function="unreal_tools.assets.inspect_asset",
        required=("asset_path",),
        description="Return class, package, metadata, dependencies, references, tags, and asset-specific summary.",
    ),
    "blueprint.scan": UnrealOperation(
        key="blueprint.scan",
        label="Unreal Scan Blueprint",
        function="tech_connector.bridges.unreal.unreal_blueprint_inspection.scan_blueprint",
        required=("asset_path",),
        optional={"include_graphs": True, "include_defaults": True},
        description="Return Blueprint variables, functions, components, parent class, interfaces, event graph features, and compile status.",
    ),
    "blueprint.add_component": UnrealOperation(
        key="blueprint.add_component",
        label="Unreal Add Blueprint Component",
        function="unreal_tools.blueprint.add_component",
        required=("blueprint_path", "component_class", "component_name"),
        optional={"asset_path": "", "attach_bone": "", "socket_name": "", "save": True},
        mutates_project=True,
        description="Add a component to a Blueprint and optionally assign an asset/socket when exposed through editor reflection.",
    ),
    "input.create_action": UnrealOperation(
        key="input.create_action",
        label="Unreal Create Input Action",
        function="tech_connector.bridges.unreal.unreal_enhanced_input.create_input_action",
        required=("asset_path",),
        optional={"value_type": "boolean", "description": "", "save": True, "dry_run": False},
        mutates_project=True,
        description="Create or validate an Enhanced Input Action and verify its saved asset state.",
    ),
    "input.add_mapping": UnrealOperation(
        key="input.add_mapping",
        label="Unreal Add Input Mapping",
        function="tech_connector.bridges.unreal.unreal_enhanced_input.add_mapping",
        required=("mapping_context_path", "action_path", "key_name"),
        optional={"save": True, "dry_run": False},
        mutates_project=True,
        description="Idempotently add and verify a key mapping in an Enhanced Input Mapping Context.",
    ),
    "gameplay.create_stamina_component": UnrealOperation(
        key="gameplay.create_stamina_component",
        label="Unreal Create Stamina Component",
        function="tech_connector.bridges.unreal.unreal_stamina_sprint_feature.create_stamina_component",
        mutates_project=True,
        description="Create and compile the approved reusable stamina component and clean function graphs.",
    ),
    "gameplay.integrate_stamina_character": UnrealOperation(
        key="gameplay.integrate_stamina_character",
        label="Unreal Integrate Stamina Character",
        function="tech_connector.bridges.unreal.unreal_stamina_sprint_feature.integrate_stamina_character",
        mutates_project=True,
        description="Add the stamina component and IA_Sprint graph glue to BP_ThirdPersonCharacter.",
    ),
    "gameplay.validate_stamina_feature": UnrealOperation(
        key="gameplay.validate_stamina_feature",
        label="Unreal Validate Stamina Feature",
        function="tech_connector.bridges.unreal.unreal_stamina_sprint_feature.validate_stamina_feature",
        description="Compile and read back stamina variables, functions, component, input mappings, and graph layout.",
    ),
    "diagnostics.read_log_errors": UnrealOperation(
        key="diagnostics.read_log_errors",
        label="Unreal Read Recent Log Errors",
        function="tech_connector.bridges.unreal.unreal_diagnostics.read_recent_log_errors",
        optional={"contains": "", "limit": 100, "max_bytes": 2000000},
        description="Read a bounded tail of the active Unreal project log and return deduplicated runtime/compiler errors with occurrence counts.",
    ),
    "animation.find_compatible": UnrealOperation(
        key="animation.find_compatible",
        label="Unreal Compatible Animation Search",
        function="unreal_tools.animation.find_compatible_animations",
        required=("skeleton_path",),
        optional={"directory": "/Game/"},
        description="Find animation assets compatible with a skeleton before building animation systems.",
    ),
    "animation.create_anim_bp": UnrealOperation(
        key="animation.create_anim_bp",
        label="Unreal Create Animation Blueprint",
        function="unreal_tools.animation.create_or_update_animation_blueprint",
        required=("skeleton_path", "asset_path"),
        optional={"template": "locomotion"},
        mutates_project=True,
        description="Create or update an Animation Blueprint from a known template.",
    ),
    "motion_matching.create_database": UnrealOperation(
        key="motion_matching.create_database",
        label="Unreal Create Motion Matching Database",
        function="unreal_tools.motion_matching.create_pose_search_database",
        required=("skeleton_path", "animation_paths", "asset_path"),
        optional={"schema_path": "", "sample_rate": 30},
        mutates_project=True,
        description="Create a Pose Search database using compatible animations.",
    ),
    "niagara.create_emitter": UnrealOperation(
        key="niagara.create_emitter",
        label="Unreal Create Niagara Emitter",
        function="unreal_tools.niagara.create_emitter",
        required=("asset_path",),
        optional={"template": "empty", "parameters": {}},
        mutates_project=True,
        description="Create a Niagara emitter from a controlled template or safe default.",
    ),
    "niagara.inspect_system": UnrealOperation(
        key="niagara.inspect_system",
        label="Unreal Inspect Niagara System",
        function="unreal_tools.niagara.inspect_system",
        required=("asset_path",),
        description="Inspect a Niagara system or emitter and return emitter/user parameter/renderer/module summary.",
    ),
    "niagara.list_module_inputs": UnrealOperation(
        key="niagara.list_module_inputs",
        label="Unreal List Niagara Module Inputs",
        function="unreal_tools.niagara.list_module_inputs",
        required=("asset_path",),
        optional={"emitter_name": ""},
        description="List reflectable Niagara module/script inputs for a system or emitter.",
    ),
    "niagara.set_user_parameter": UnrealOperation(
        key="niagara.set_user_parameter",
        label="Unreal Set Niagara User Parameter",
        function="unreal_tools.niagara.set_user_parameter",
        required=("asset_path", "parameter_name", "value"),
        optional={"value_type": "auto"},
        mutates_project=True,
        description="Set a user/exposed Niagara parameter on a system or emitter when exposed through editor reflection.",
    ),
    "niagara.set_renderer_property": UnrealOperation(
        key="niagara.set_renderer_property",
        label="Unreal Set Niagara Renderer Property",
        function="unreal_tools.niagara.set_renderer_property",
        required=("asset_path", "property_name", "value"),
        optional={"emitter_name": "", "renderer_index": 0, "value_type": "auto"},
        mutates_project=True,
        description="Set a renderer property on a Niagara emitter renderer when exposed through editor reflection.",
    ),
    "niagara.set_module_input": UnrealOperation(
        key="niagara.set_module_input",
        label="Unreal Set Niagara Module Input",
        function="unreal_tools.niagara.set_module_input",
        required=("asset_path", "module_name", "input_name", "value"),
        optional={"emitter_name": "", "script_usage": "", "value_type": "auto"},
        mutates_project=True,
        description="Set a module/script input on a Niagara emitter or system when exposed through editor reflection.",
    ),
    "niagara.add_to_level": UnrealOperation(
        key="niagara.add_to_level",
        label="Unreal Add Niagara To Level",
        function="unreal_tools.niagara.add_to_level",
        required=("asset_path",),
        optional={"location": None, "attach_to_selected_actor": False},
        mutates_project=True,
        description="Spawn a Niagara system/actor into the current level, optionally using the current selection as context.",
    ),
    "physics.set_body_property": UnrealOperation(
        key="physics.set_body_property",
        label="Unreal Set Physics Body Property",
        function="unreal_tools.physics.set_body_property",
        required=("asset_path", "body_name", "property_name", "value"),
        optional={"save": True, "value_type": "auto"},
        mutates_project=True,
        description="Set a common tunable property on a PhysicsAsset body instance, such as mass or damping.",
    ),
    "physics.list_bodies": UnrealOperation(
        key="physics.list_bodies",
        label="Unreal List Physics Bodies",
        function="unreal_tools.physics.list_bodies",
        required=("asset_path",),
        description="List discovered bodies in a PhysicsAsset along with likely editable fields.",
    ),
    "physics.list_constraints": UnrealOperation(
        key="physics.list_constraints",
        label="Unreal List Physics Constraints",
        function="unreal_tools.physics.list_constraints",
        required=("asset_path",),
        description="List discovered constraints in a PhysicsAsset along with likely editable fields.",
    ),
    "physics.set_constraint_property": UnrealOperation(
        key="physics.set_constraint_property",
        label="Unreal Set Physics Constraint Property",
        function="unreal_tools.physics.set_constraint_property",
        required=("asset_path", "constraint_name", "property_name", "value"),
        optional={"save": True, "value_type": "auto"},
        mutates_project=True,
        description="Set a common tunable property on a PhysicsAsset constraint instance, such as disable_collision or motion mode.",
    ),
    "physics.set_profile_property": UnrealOperation(
        key="physics.set_profile_property",
        label="Unreal Set Physics Profile Property",
        function="unreal_tools.physics.set_profile_property",
        required=("asset_path", "profile_name", "property_name", "value"),
        optional={"save": True, "value_type": "auto"},
        mutates_project=True,
        description="Set a tunable property on a PhysicsAsset profile when exposed through editor reflection.",
    ),
    "blueprint.create_from_template": UnrealOperation(
        key="blueprint.create_from_template",
        label="Unreal Blueprint From Template",
        function="unreal_tools.blueprint.create_from_template",
        required=("template", "asset_path"),
        optional={"parent_class": "", "parameters": {}},
        mutates_project=True,
        description="Create a Blueprint from a controlled template rather than raw generated graph edits.",
    ),
    "blueprint.compile": UnrealOperation(
        key="blueprint.compile",
        label="Unreal Compile Blueprint",
        function="unreal_tools.blueprint.compile_blueprint",
        required=("asset_path",),
        description="Compile a Blueprint and return compiler errors/warnings.",
    ),
    "gameplay.prototype_from_template": UnrealOperation(
        key="gameplay.prototype_from_template",
        label="Unreal Gameplay Prototype From Template",
        function="unreal_tools.gameplay.prototype_from_template",
        required=("template", "target_path"),
        optional={"parameters": {}},
        mutates_project=True,
        description="Create a gameplay prototype from an approved template.",
    ),
    "validate.references": UnrealOperation(
        key="validate.references",
        label="Unreal Validate References",
        function="unreal_tools.validate.references",
        optional={"paths": [], "compile_blueprints": True, "save": False},
        description="Validate references and optionally compile touched Blueprints.",
    ),
    "project.debug": UnrealOperation(
        key="project.debug",
        label="Unreal Project Debug",
        function="ai_studio.synthetic.project_debug",
        optional={
            "directory": "/Game/",
            "paths": [],
            "compile_blueprints": True,
            "save": False,
        },
        description="Scan project/level state, validate references, compile Blueprints when supported, and report what is broken plus suggested fixes.",
    ),
    "rollback.latest": UnrealOperation(
        key="rollback.latest",
        label="Unreal Rollback Latest Operation",
        function="unreal_tools.rollback.latest",
        mutates_project=True,
        description="Rollback the latest tracked safe operation when the Unreal side supports rollback data.",
    ),
    # ── Expanded DCC Operation Catalog ──

    # ── Asset Management Additions ──
    "asset.delete": UnrealOperation(
        key="asset.delete",
        label="Unreal Delete Assets",
        function="unreal_tools.assets.delete_assets",
        required=("asset_paths",),
        mutates_project=True,
        description="Delete one or more assets from the Content Browser.",
    ),
    "asset.rename": UnrealOperation(
        key="asset.rename",
        label="Unreal Rename Asset",
        function="unreal_tools.assets.rename_asset",
        required=("asset_path", "new_name"),
        mutates_project=True,
        description="Rename an existing asset in the Content Browser.",
    ),
    "asset.duplicate": UnrealOperation(
        key="asset.duplicate",
        label="Unreal Duplicate Asset",
        function="unreal_tools.assets.duplicate_asset",
        required=("asset_path", "destination_path"),
        mutates_project=True,
        description="Duplicate an asset to a new path in the Content Browser.",
    ),
    "asset.save": UnrealOperation(
        key="asset.save",
        label="Unreal Save Assets",
        function="unreal_tools.assets.save_assets",
        optional={"asset_paths": []},
        mutates_project=True,
        description="Save dirty/unsaved assets in the editor.",
    ),

    # ── Level Editing Additions ──
    "level.delete_actor": UnrealOperation(
        key="level.delete_actor",
        label="Unreal Delete Actor",
        function="unreal_tools.level.delete_actor",
        required=("actor_query",),
        mutates_project=True,
        description="Delete a placed actor from the current level.",
    ),
    "level.get_selected_actors": UnrealOperation(
        key="level.get_selected_actors",
        label="Unreal Get Selected Actors",
        function="unreal_tools.level.get_selected_actors",
        description="Get handles/names of the currently selected actors in the level.",
    ),
    "level.set_selected_actors": UnrealOperation(
        key="level.set_selected_actors",
        label="Unreal Set Selected Actors",
        function="unreal_tools.level.select_actors_by_query",
        required=("query",),
        mutates_project=True,
        description="Set the active actor selection in the current level.",
    ),

    # ── Blueprint Additions ──
    "blueprint.add_function": UnrealOperation(
        key="blueprint.add_function",
        label="Unreal Add Blueprint Function",
        function="unreal_tools.blueprint.add_function",
        required=("blueprint_path", "function_name"),
        optional={"inputs": [], "outputs": []},
        mutates_project=True,
        description="Add a new function to a Blueprint asset.",
    ),
    "blueprint.set_property": UnrealOperation(
        key="blueprint.set_property",
        label="Unreal Set Blueprint Property",
        function="unreal_tools.blueprint.set_property",
        required=("blueprint_path", "property_name", "value"),
        mutates_project=True,
        description="Set a default property value on a Blueprint asset.",
    ),
    "blueprint.add_node": UnrealOperation(
        key="blueprint.add_node",
        label="Unreal Add Blueprint Node",
        function="unreal_tools.blueprint.add_node_to_graph",
        required=("blueprint_path", "graph_name", "node_class"),
        mutates_project=True,
        description="Add a node to a specific Blueprint graph.",
    ),
    "blueprint.open_graph": UnrealOperation(
        key="blueprint.open_graph",
        label="Unreal Open Blueprint Graph",
        function="unreal_tools.blueprint.open_graph",
        required=("blueprint_path", "graph_name"),
        mutates_project=True,
        description="Open a Blueprint graph in the editor UI.",
    ),
    "blueprint.open_function": UnrealOperation(
        key="blueprint.open_function",
        label="Unreal Open Blueprint Function",
        function="unreal_tools.blueprint.open_function",
        required=("blueprint_path", "function_name"),
        mutates_project=True,
        description="Open a Blueprint function graph in the editor UI.",
    ),

    # ── Animation Additions ──
    "animation.delete_state": UnrealOperation(
        key="animation.delete_state",
        label="Unreal Delete Animation State",
        function="unreal_tools.animation.delete_state_from_state_machine",
        required=("anim_bp_path", "state_machine_name", "state_name"),
        mutates_project=True,
        description="Delete a state from a locomotion state machine in an Animation Blueprint.",
    ),
    "animation.delete_transition": UnrealOperation(
        key="animation.delete_transition",
        label="Unreal Delete Animation Transition",
        function="unreal_tools.animation.delete_state_transition",
        required=("anim_bp_path", "from_state", "to_state"),
        mutates_project=True,
        description="Delete a transition between two states in an Animation Blueprint locomotion state machine.",
    ),

    # ── Sequencer Additions ──
    "sequencer.delete_track": UnrealOperation(
        key="sequencer.delete_track",
        label="Unreal Delete Sequencer Track",
        function="unreal_tools.sequencer.delete_track",
        required=("sequence_path", "track_name"),
        mutates_project=True,
        description="Delete a track from a Level Sequence.",
    ),
    "sequencer.get_tracks": UnrealOperation(
        key="sequencer.get_tracks",
        label="Unreal Get Sequencer Tracks",
        function="unreal_tools.sequencer.get_tracks",
        required=("sequence_path",),
        description="Get all tracks inside a Level Sequence.",
    ),

    # ── Niagara Additions ──
    "niagara.delete_emitter": UnrealOperation(
        key="niagara.delete_emitter",
        label="Unreal Delete Niagara Emitter",
        function="unreal_tools.niagara.delete_emitter",
        required=("system_path", "emitter_name"),
        mutates_project=True,
        description="Delete an emitter from a Niagara system.",
    ),
    "niagara.set_emitter_property": UnrealOperation(
        key="niagara.set_emitter_property",
        label="Unreal Set Niagara Emitter Property",
        function="unreal_tools.niagara.set_emitter_property",
        required=("system_path", "emitter_name", "property_name", "value"),
        mutates_project=True,
        description="Set a property value on a Niagara emitter inside a system.",
    ),

    # ── Project Refactoring Additions ──
    "project.rename_symbol": UnrealOperation(
        key="project.rename_symbol",
        label="Unreal Rename Project Symbol",
        function="unreal_tools.project.rename_symbol",
        required=("old_name", "new_name"),
        optional={"folder_path": ""},
        mutates_project=True,
        description="Rename a variable, function, or symbol name across all Blueprints in the folder/project.",
    ),
    "project.find_references": UnrealOperation(
        key="project.find_references",
        label="Unreal Find Project References",
        function="unreal_tools.project.find_references",
        required=("target_name",),
        optional={"folder_path": ""},
        description="Find all references to a symbol, class, or asset across all Blueprints in the folder/project.",
    ),
    # ── Technical Animator Additions ──
    "blueprint.create_variable": UnrealOperation(
        key="blueprint.create_variable",
        label="Unreal Create Blueprint Variable",
        function="unreal_tools.blueprint.create_variable",
        required=("blueprint_path", "variable_name", "variable_type"),
        optional={"is_array": False, "default_value": None},
        mutates_project=True,
        description="Create a new typed variable in a Blueprint or Animation Blueprint.",
    ),
    "blueprint.connect_node_pins": UnrealOperation(
        key="blueprint.connect_node_pins",
        label="Unreal Connect Blueprint Node Pins",
        function="unreal_tools.blueprint.connect_node_pins",
        required=("blueprint_path", "graph_name", "source_node", "source_pin", "target_node", "target_pin"),
        mutates_project=True,
        description="Connect pin A of node X to pin B of node Y in a Blueprint graph (EventGraph or AnimGraph).",
    ),
    "blueprint.get_compile_errors": UnrealOperation(
        key="blueprint.get_compile_errors",
        label="Unreal Get Blueprint Compile Errors",
        function="unreal_tools.blueprint.get_compile_errors",
        required=("blueprint_path",),
        description="Retrieve compiler errors and warnings for a Blueprint after compilation fails.",
    ),
    "blueprint.set_breakpoint": UnrealOperation(
        key="blueprint.set_breakpoint",
        label="Unreal Set Blueprint Breakpoint",
        function="unreal_tools.blueprint.set_breakpoint",
        required=("blueprint_path", "node_name"),
        optional={"enabled": True},
        mutates_project=True,
        description="Set or toggle a debugging breakpoint on a Blueprint node.",
    ),
    "animation.add_anim_notify": UnrealOperation(
        key="animation.add_anim_notify",
        label="Unreal Add Animation Notify",
        function="unreal_tools.animation.add_anim_notify",
        required=("animation_path", "notify_name"),
        optional={"notify_class": "", "time_ratio": 0.0},
        mutates_project=True,
        description="Add an Anim Notify or custom notify class to a character animation sequence at a specific timeline ratio.",
    ),
    "animation.get_state_machine_graph": UnrealOperation(
        key="animation.get_state_machine_graph",
        label="Unreal Get Locomotion State Machine Graph",
        function="unreal_tools.animation.get_state_machine_graph",
        required=("anim_bp_path", "state_machine_name"),
        description="Retrieve states and transitions for a locomotion state machine in an Animation Blueprint.",
    ),
    # ── State Machine, Retargeting, Control Rig & Motion Matching Additions ──
    "animation.rename_state": UnrealOperation(
        key="animation.rename_state",
        label="Unreal Rename Animation State",
        function="unreal_tools.animation.rename_state",
        required=("anim_bp_path", "state_machine_name", "old_state_name", "new_state_name"),
        mutates_project=True,
        description="Rename an existing state in a locomotion state machine.",
    ),
    "animation.set_state_transition_rule": UnrealOperation(
        key="animation.set_state_transition_rule",
        label="Unreal Set State Transition Rule",
        function="unreal_tools.animation.set_state_transition_rule",
        required=("anim_bp_path", "from_state", "to_state", "condition_rule"),
        mutates_project=True,
        description="Set the boolean logic rule or condition variable for a state transition.",
    ),
    "retarget.create_ik_rig": UnrealOperation(
        key="retarget.create_ik_rig",
        label="Unreal Create IK Rig",
        function="unreal_tools.retarget.create_ik_rig",
        required=("skeletal_mesh_path",),
        optional={"save_path": ""},
        mutates_project=True,
        description="Create a new IK Rig asset targeting the given Skeletal Mesh.",
    ),
    "retarget.add_ik_chain": UnrealOperation(
        key="retarget.add_ik_chain",
        label="Unreal Add IK Chain",
        function="unreal_tools.retarget.add_ik_chain",
        required=("ik_rig_path", "chain_name", "start_bone", "end_bone"),
        mutates_project=True,
        description="Add a new IK solver chain (e.g. LeftLeg) between start and end bones.",
    ),
    "retarget.create_ik_retargeter": UnrealOperation(
        key="retarget.create_ik_retargeter",
        label="Unreal Create IK Retargeter",
        function="unreal_tools.retarget.create_ik_retargeter",
        required=("source_ik_rig_path", "target_ik_rig_path"),
        optional={"save_path": ""},
        mutates_project=True,
        description="Create an IK Retargeter asset mapping source IK Rig to target IK Rig.",
    ),
    "retarget.set_chain_mapping": UnrealOperation(
        key="retarget.set_chain_mapping",
        label="Unreal Set IK Chain Mapping",
        function="unreal_tools.retarget.set_chain_mapping",
        required=("retargeter_path", "source_chain", "target_chain"),
        mutates_project=True,
        description="Map a source rig chain to a target rig chain inside the retargeter.",
    ),
    "retarget.set_root_settings": UnrealOperation(
        key="retarget.set_root_settings",
        label="Unreal Set Retarget Root Settings",
        function="unreal_tools.retarget.set_root_settings",
        required=("retargeter_path",),
        optional={"blend_height": 1.0, "scale_factor": 1.0},
        mutates_project=True,
        description="Configure root motion and scaling settings on the retargeter.",
    ),
    "retarget.inspect": UnrealOperation(
        key="retarget.inspect",
        label="Unreal Inspect IK Retargeter",
        function="unreal_tools.retarget.inspect",
        required=("retargeter_path",),
        description="Inspect retarget mappings, chains, and translation mode parameters.",
    ),
    "retarget.set_profile_property": UnrealOperation(
        key="retarget.set_profile_property",
        label="Unreal Set Retarget Profile Property",
        function="unreal_tools.retarget.set_profile_property",
        required=("retargeter_path", "profile_name", "property_name", "value"),
        mutates_project=True,
        description="Set retarget settings on a specific profile parameter.",
    ),
    "control_rig.list_controls": UnrealOperation(
        key="control_rig.list_controls",
        label="Unreal List Control Rig Controls",
        function="unreal_tools.control_rig.list_controls",
        required=("rig_path",),
        description="List all controls, types, and values in a Control Rig.",
    ),
    "control_rig.set_control_property": UnrealOperation(
        key="control_rig.set_control_property",
        label="Unreal Set Control Rig Control Property",
        function="unreal_tools.control_rig.set_control_property",
        required=("rig_path", "control_name", "property_name", "value"),
        mutates_project=True,
        description="Set a property (like position, limits) on a Control Rig control.",
    ),
    "control_rig.set_control_default": UnrealOperation(
        key="control_rig.set_control_default",
        label="Unreal Set Control Rig Control Default",
        function="unreal_tools.control_rig.set_control_default",
        required=("rig_path", "control_name", "value"),
        mutates_project=True,
        description="Set the default initialization value of a Control Rig control.",
    ),
    "control_rig.rename_control": UnrealOperation(
        key="control_rig.rename_control",
        label="Unreal Rename Control Rig Control",
        function="unreal_tools.control_rig.rename_control",
        required=("rig_path", "old_name", "new_name"),
        mutates_project=True,
        description="Rename a control inside the Control Rig hierarchy.",
    ),
    "control_rig.add_rig_element": UnrealOperation(
        key="control_rig.add_rig_element",
        label="Unreal Add Control Rig Element",
        function="unreal_tools.control_rig.add_rig_element",
        required=("rig_path", "element_name", "element_type"),
        optional={"parent_name": ""},
        mutates_project=True,
        description="Add a new control, bone, or space element to the Control Rig hierarchy.",
    ),
    "control_rig.connect_rig_nodes": UnrealOperation(
        key="control_rig.connect_rig_nodes",
        label="Unreal Connect Control Rig Nodes",
        function="unreal_tools.control_rig.connect_rig_nodes",
        required=("rig_path", "source_node", "source_pin", "target_node", "target_pin"),
        mutates_project=True,
        description="Wire execution or value pins between nodes in the Control Rig graph.",
    ),
    "motion_matching.add_animation": UnrealOperation(
        key="motion_matching.add_animation",
        label="Unreal Add Motion Matching Animation",
        function="unreal_tools.motion_matching.add_animation",
        required=("database_path", "animation_path"),
        mutates_project=True,
        description="Add an Animation Sequence or Blend Space to a Pose Search Database.",
    ),
    "motion_matching.remove_animation": UnrealOperation(
        key="motion_matching.remove_animation",
        label="Unreal Remove Motion Matching Animation",
        function="unreal_tools.motion_matching.remove_animation",
        required=("database_path", "animation_path"),
        mutates_project=True,
        description="Remove an animation from a Pose Search Database.",
    ),
    "motion_matching.set_database_property": UnrealOperation(
        key="motion_matching.set_database_property",
        label="Unreal Set Motion Matching Database Property",
        function="unreal_tools.motion_matching.set_database_property",
        required=("database_path", "property_name", "value"),
        mutates_project=True,
        description="Set settings (e.g. weights, trajectory channels) on a Pose Search Database.",
    ),
    "motion_matching.inspect_database": UnrealOperation(
        key="motion_matching.inspect_database",
        label="Unreal Inspect Motion Matching Database",
        function="unreal_tools.motion_matching.inspect_database",
        required=("database_path",),
        description="Inspect Pose Search Database settings and registered animations.",
    ),
    "motion_matching.create_schema": UnrealOperation(
        key="motion_matching.create_schema",
        label="Unreal Create Motion Matching Schema",
        function="unreal_tools.motion_matching.create_schema",
        required=("schema_name",),
        optional={"save_path": ""},
        mutates_project=True,
        description="Create a new Pose Search Schema asset defining query features.",
    ),
    "motion_matching.add_schema_channel": UnrealOperation(
        key="motion_matching.add_schema_channel",
        label="Unreal Add Motion Matching Schema Channel",
        function="unreal_tools.motion_matching.add_schema_channel",
        required=("schema_path", "channel_type"),
        optional={"bone_name": ""},
        mutates_project=True,
        description="Add a channel/feature description (like feet alignment or history) to a Pose Search Schema.",
    ),

}


def operation_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": op.key,
            "label": op.label,
            "function": op.function,
            "required": list(op.required),
            "optional": op.optional,
            "mutates_project": op.mutates_project,
            "description": op.description,
        }
        for op in UNREAL_OPERATIONS.values()
    ]


def unreal_operation_payload(
    operation_key: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    if operation_key not in UNREAL_OPERATIONS:
        valid = ", ".join(sorted(UNREAL_OPERATIONS))
        raise ValueError(
            f"Unknown Unreal operation '{operation_key}'. Valid operations: {valid}"
        )

    op = UNREAL_OPERATIONS[operation_key]
    params = dict(params or {})
    missing = [
        name for name in op.required if name not in params or params[name] in (None, "")
    ]
    if missing:
        raise ValueError(
            f"Unreal operation '{operation_key}' requires: {', '.join(missing)}"
        )

    kwargs = dict(op.optional)
    kwargs.update(params)
    return {
        "operation": op.key,
        "label": op.label,
        "function": op.function,
        "args": [],
        "kwargs": kwargs,
        "mutates_project": op.mutates_project,
    }


def unreal_project_scan_payloads(directory: str = "/Game/") -> list[dict[str, Any]]:
    clean_directory = directory or "/Game/"
    return [
        {
            "operation": "project.scan_assets",
            "label": f"Unreal Scan {asset_class}",
            "function": "unreal_tools.get_skeletons.get_all_assets_of_type",
            "args": [asset_class, clean_directory],
            "kwargs": {},
            "asset_class": asset_class,
            "mutates_project": False,
        }
        for asset_class in PROJECT_SCAN_ASSET_CLASSES
    ]


def is_unreal_niagara_create_request(text: str) -> bool:
    q = (text or "").lower()
    if "unreal" not in q:
        return False
    if not any(verb in q for verb in UNREAL_PROTOTYPE_VERBS):
        return False
    return any(
        term in q for term in ("niagara", "niagra", "emitter", "particle system", "vfx")
    )


def build_unreal_niagara_create_params(
    text: str,
    target_root: str = "/Game/AIStudio/Prototypes/Niagara",
) -> dict[str, Any]:
    q = (text or "").lower()
    wants_emitter = any(
        term in q for term in ("emitter", "niagara emitter", "niagra emitter")
    )
    requested_name = extract_unreal_asset_name(text)
    base_name = requested_name or ("NE_AIStudioEmitter" if wants_emitter else "NS_AIStudioSystem")
    parameters: dict[str, Any] = {
        "request_text": text,
        "return_created_name": True,
        "asset_kind": "emitter" if wants_emitter else "system",
    }
    color = extract_requested_color(text)
    if color:
        parameters["requested_color"] = color
    target_blueprint = extract_target_blueprint_name(text, exclude_asset=base_name)
    if target_blueprint:
        parameters["target_blueprint"] = target_blueprint
        parameters["add_to_selected_blueprint"] = True
    attach_bone = extract_attachment_bone_name(text)
    if attach_bone:
        parameters["attach_bone"] = attach_bone
    return {
        "asset_path": f"{target_root.rstrip('/')}/{base_name}",
        "template": "empty_emitter" if wants_emitter else "empty_system",
        "asset_name": base_name,
        "parameters": parameters,
    }


def is_unreal_prototype_request(text: str) -> bool:
    q = (text or "").lower()
    if "unreal" not in q:
        return False
    if not any(verb in q for verb in UNREAL_PROTOTYPE_VERBS):
        return False
    return any(
        term in q
        for term in (
            "feature",
            "prototype",
            "gameplay",
            "blueprint",
            "anim",
            "animation",
            "graph",
            "slot",
            "system",
            "mechanic",
            "ability",
            "setup",
            "set up",
        )
    )


def infer_unreal_prototype_template(text: str) -> str:
    q = (text or "").lower()
    for template, aliases in UNREAL_PROTOTYPE_FEATURE_ALIASES.items():
        if any(alias in q for alias in aliases):
            return template
    feature_match = re.search(
        r"\b(?:prototype|create|implement|build|make|add|set up|setup)\s+(?:a|an|the|new)?\s*([A-Za-z0-9 _-]{3,60}?)(?:\s+(?:feature|system|mechanic|ability|prototype|in|for|inside|with)\b|$)",
        text or "",
        re.IGNORECASE,
    )
    raw = feature_match.group(1) if feature_match else "gameplay_feature"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug or "gameplay_feature"


def research_mode_from_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    settings = settings or {}
    return {
        "project_snapshot": bool(settings.get("research_project_snapshot", True)),
        "unreal_capabilities": bool(settings.get("research_unreal_capabilities", True)),
        "official_docs": bool(settings.get("research_official_docs", True)),
        "web_techniques": bool(settings.get("research_web_techniques", False)),
        "github_examples": bool(settings.get("research_github_examples", False)),
        "compare_architectures": bool(
            settings.get("research_compare_architectures", True)
        ),
        "generate_plan": bool(settings.get("research_generate_plan", True)),
        "auto_implement": bool(settings.get("research_auto_implement", False)),
        "previous_ai_work": bool(settings.get("ai_work_memory_enabled", True)),
        "locked_knowledge": bool(settings.get("ai_work_memory_include_locked", True)),
    }


def build_unreal_prototype_params(
    text: str,
    snapshot: str = "",
    target_root: str = "/Game/AIStudio/Prototypes",
    settings: dict[str, Any] | None = None,
    previous_work_context: str = "",
) -> dict[str, Any]:
    from tech_connector.services.unreal.semantic_graph_service import build_semantic_graph_analysis

    template = infer_unreal_prototype_template(text)
    target_path = f"{target_root.rstrip('/')}/{template}"
    snapshot_excerpt = (snapshot or "")[:16000]
    semantic_graph = build_semantic_graph_analysis(
        text,
        operation="gameplay.prototype_from_template",
        params={"target_path": target_path, "template": template},
    )
    return {
        "template": template,
        "target_path": target_path,
        "parameters": {
            "feature_goal": text,
            "mode": "prototype_or_create_or_implement",
            "use_project_snapshot": True,
            "snapshot_excerpt": snapshot_excerpt,
            "previous_ai_work_context": (previous_work_context or "")[:8000],
            "research_mode": research_mode_from_settings(settings),
            "asset_awareness": {
                "scan_all_assets_first": True,
                "inspect_candidate_blueprints": True,
                "scan_blueprint_variables": True,
                "scan_blueprint_functions": True,
                "scan_components": True,
                "scan_accessible_functions": True,
                "scan_connectable_properties": True,
                "find_compatible_animations": True,
                "create_animation_slots": True,
                "prefer_existing_assets": True,
            },
            "semantic_graph_understanding": semantic_graph,
            "graph_comprehension_pipeline": [
                "discover graph structure and linked assets",
                "annotate major node clusters by behavior",
                "map execution and data dependencies",
                "map user intent to affected subsystems",
                "choose integration points that preserve existing behavior",
                "validate pins, references, compile status, and rollback path",
            ],
            "visible_edit_workflow": semantic_graph.get("visible_edit_lifecycle") or [],
            "graph_edit_state_machine": semantic_graph.get("lifecycle_states") or [],
            "graph_edit_failure_states": semantic_graph.get("failure_states") or [],
            "graph_layout_contract": semantic_graph.get("layout_contract") or [],
            "graph_edit_progress_stages": semantic_graph.get("progress_stages") or [],
            "graph_edit_threading_contract": semantic_graph.get("threading_contract") or {},
            "pre_edit_proposal_required_fields": semantic_graph.get("pre_edit_proposal_required_fields") or [],
            "open_focus_operations": semantic_graph.get("open_focus_operations") or [],
            "post_edit_report_fields": semantic_graph.get("post_edit_report_fields") or [],
            "requested_outputs": [
                "operation_plan",
                "graph_semantic_summary",
                "intent_graph",
                "integration_point_justification",
                "existing_behavior_preservation_report",
                "created_or_modified_assets",
                "animation_graph_changes",
                "animation_slots",
                "blueprint_variables",
                "blueprint_functions",
                "validation_report",
                "rollback_token",
            ],
        },
    }


def is_unreal_debug_request(text: str) -> bool:
    q = (text or "").lower()
    if "unreal" not in q:
        return False
    return any(term in q for term in UNREAL_DEBUG_TERMS)


def extract_unreal_asset_paths(text: str) -> list[str]:
    paths = []
    for match in re.finditer(r"(/Game/[A-Za-z0-9_/.-]*)", text or ""):
        path = match.group(1).rstrip(".,;:)")
        if path and path not in paths:
            paths.append(path)
    return paths


def build_unreal_debug_params(text: str, directory: str = "/Game/") -> dict[str, Any]:
    q = (text or "").lower()
    paths = extract_unreal_asset_paths(text)
    full_project = not paths or any(
        term in q
        for term in (
            "full project",
            "whole project",
            "entire project",
            "everything",
            "all",
        )
    )
    compile_blueprints = "no compile" not in q and "don't compile" not in q
    return {
        "directory": directory,
        "paths": [] if full_project else paths,
        "compile_blueprints": compile_blueprints,
        "save": False,
        "parameters": {
            "debug_goal": text,
            "scope": "full_project" if full_project else "selected_assets",
            "requested_report": [
                "broken_references",
                "missing_assets",
                "blueprint_compile_errors",
                "blueprint_compile_warnings",
                "invalid_parent_classes",
                "missing_interfaces_or_functions",
                "animation_asset_mismatches",
                "recommended_fix_order",
                "safe_fix_operations",
            ],
        },
    }


def normalize_unreal_package_path(path: str, default_name: str = "Asset") -> str:
    if not path:
        return f"/Game/{default_name}"
    p = path.replace("\\", "/").strip().strip("\"'")
    if p.endswith("/") and len(p) > 1:
        p = p.rstrip("/")
    lower = p.lower()
    if not any(lower.startswith(root) for root in ("/game", "/engine", "/script", "/plugin")):
        if any(lower.startswith(root) for root in ("game/", "engine/", "script/", "plugin/")):
            p = "/" + p
        elif p.lower() in {"game", "engine", "script", "plugin"}:
            p = f"/{p.capitalize()}/{default_name}"
        else:
            p = f"/Game/{p}"
    if p.lower() in {"/game", "/engine", "/script", "/plugin"}:
        p = f"{p}/{default_name}"
    elif p.count("/") == 1:
        p = f"{p}/{default_name}"
    return p


def normalize_unreal_folder_path(path: str) -> str:
    if not path:
        return "/Game"
    p = path.replace("\\", "/").strip().strip("\"'")
    if not p:
        return "/Game"
    lower = p.lower()
    if not any(lower.startswith(root) for root in ("/game", "/engine", "/plugin")):
        if lower.startswith(("game/", "engine/", "plugin/")):
            p = "/" + p
        else:
            p = "/Game/" + p.lstrip("/")
    return p.rstrip("/") or "/Game"


def extract_unreal_package_like_path(text: str) -> str:
    match = re.search(r"['\"]((?:/Game|/Engine|/Plugin)/[^'\"]+)['\"]", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"((?:/Game|/Engine|/Plugin)/[A-Za-z0-9_./-]+)", text or "", re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".,;:)")
    return ""


def extract_unreal_asset_name(text: str) -> str:
    match = re.search(r"\b((?:ABP|BP|BPC|BPI|WBP|MI|M|T|SK|SM|NS|NE|GA|GE|IK|RT|RTG)_[A-Za-z0-9_]+)\b", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def extract_unreal_asset_names(text: str) -> list[str]:
    names = []
    for match in re.finditer(r"\b((?:ABP|BP|BO|BPC|BPI|WBP|MI|M|T|SK|SM|NS|NE|GA|GE|IK|RT|RTG)_[A-Za-z0-9_]+)\b", text or "", re.IGNORECASE):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return names


def extract_requested_color(text: str) -> str:
    q = text or ""
    for color in (
        "orange", "red", "blue", "green", "yellow", "purple", "pink",
        "white", "black", "cyan", "magenta", "teal", "gold",
    ):
        if re.search(rf"\b{re.escape(color)}\b", q, re.IGNORECASE):
            return color
    match = re.search(r"\b(?:color|colour)\s+(?:of\s+(?:the\s+)?)?(?:effect|emitter|system|it)?\s*(?:to|=|as)?\s*([A-Za-z][A-Za-z0-9_-]*)", q, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    return ""


def extract_target_blueprint_name(text: str, exclude_asset: str = "") -> str:
    names = extract_unreal_asset_names(text)
    excluded = {exclude_asset.lower()} if exclude_asset else set()
    for pattern in (
        r"\b(?:import|add|attach|put|insert)\s+[A-Za-z0-9_]+\s+(?:into|to|onto|on)\s+((?:BP|BO|ABP|BPC)_[A-Za-z0-9_]+)\b",
        r"\b(?:into|to|onto|on)\s+((?:BP|BO|ABP|BPC)_[A-Za-z0-9_]+)\b",
    ):
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in excluded:
                return candidate
    for name in names:
        lower = name.lower()
        if lower in excluded:
            continue
        if lower.startswith(("bp_", "bo_", "abp_", "bpc_")):
            return name
    return ""


def extract_attachment_bone_name(text: str) -> str:
    q = text or ""
    match = re.search(r"\b(?:to|onto|on|at)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:bone|joint|socket))\b", q, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b([lr]_[A-Za-z0-9_]*(?:hand|foot|arm|leg)[A-Za-z0-9_]*)\b", q, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    lower = q.lower()
    if "left hand" in lower:
        return "l_hand"
    if "right hand" in lower:
        return "r_hand"
    return ""


def extract_unreal_window_name(text: str) -> str:
    patterns = (
        r"\b(?:open|show|focus|bring up|launch)\s+(?:the\s+)?(.+?)\s+(?:window|panel|tab|tool)\b",
        r"\b(?:open|show|focus|bring up|launch)\s+(?:the\s+)?(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            value = re.sub(r"\b(?:in|inside)\s+(?:unreal|ue5|ue4)\b", "", match.group(1), flags=re.IGNORECASE)
            value = re.sub(r"\b(?:window|panel|tab|tool)\b", "", value, flags=re.IGNORECASE)
            value = value.strip(" .,'\"")
            if value and "content browser" not in value.lower():
                return value
    return ""


def unreal_navigation_operation_from_text(text: str) -> tuple[str, dict[str, Any]]:
    q = (text or "").lower()
    package_path = extract_unreal_package_like_path(text)
    asset_name = extract_unreal_asset_name(text)
    if "content browser" in q:
        return (
            "navigation.open_content_browser",
            {
                "folder_path": normalize_unreal_folder_path(package_path or "/Game"),
                "asset_name": asset_name,
                "new_browser": bool(re.search(r"\b(new|another|second|separate)\b", q)),
            },
        )
    if re.search(r"\b(load|open)\b", q) and re.search(r"\b(level|map|world)\b", q):
        return ("navigation.load_level", {"level_path": normalize_unreal_package_path(package_path, default_name="Level") if package_path else ""})
    open_match = re.search(r"\b(?:open|edit|load|focus)\s+([A-Za-z0-9_\-\/\s]+(?:\s+[A-Za-z0-9_\-\/\s]+)*)\b", q)
    if open_match and "content browser" not in q and not any(w in q for w in ("level", "map", "world", "window", "panel", "tab", "tool")):
        target_name = open_match.group(1).strip()
        clean_target = target_name
        for suffix in ("in unreal", "unreal", "in ue5", "ue5", "in ue4", "ue4"):
            if clean_target.endswith(suffix):
                clean_target = clean_target[:-len(suffix)].strip()
        is_generic = clean_target.lower() in {"asset", "an asset", "the asset", "selected asset", "active asset", "current asset"}
        if is_generic:
            resolved_asset_ref = ""
        else:
            resolved_asset_ref = package_path or asset_name or clean_target
        if resolved_asset_ref:
            return (
                "navigation.open_asset",
                {
                    "asset_path": normalize_unreal_package_path(resolved_asset_ref, default_name=resolved_asset_ref) if "/" in resolved_asset_ref else resolved_asset_ref,
                    "asset_name": asset_name or clean_target,
                },
            )
        else:
            return (
                "navigation.open_asset",
                {}
            )
    if re.search(r"\b(open|show|focus|bring up|launch)\b", q) and re.search(r"\b(window|panel|tab|tool|outliner|details|sequencer|console|world settings|place actors)\b", q):
        window_name = extract_unreal_window_name(text)
        return ("navigation.open_window", {"window_name": window_name or "Content Browser"})
    return "", {}


def find_best_unreal_operation(prompt: str) -> tuple[str, float]:
    """Score all UNREAL_OPERATIONS against the prompt and return (best_key, score)."""
    q = (prompt or "").lower()
    # Replace underscores with spaces so BP_Lester becomes BP Lester, and include 2-letter tokens like 'bp'
    tokens = {part for part in re.findall(r"\b\w{2,}\b", q.replace("_", " "))}
    if not tokens:
        return "level.scan_loaded", 0.0

    best_key = "level.scan_loaded"
    best_score = 0.0

    def word_matches_any_token(word: str) -> bool:
        w = re.sub(r"\W+", "", word.lower())
        if not w:
            return False
        for tk in tokens:
            if w == tk:
                return True
            # Allow 'bp' to match 'blueprint'
            if w == "blueprint" and tk == "bp":
                return True
            if tk == "blueprint" and w == "bp":
                return True
            # General prefix matching
            if len(w) > 3 and len(tk) > 3:
                if w.startswith(tk) or tk.startswith(w):
                    return True
        return False

    for key, op in UNREAL_OPERATIONS.items():
        score = 0.0
        
        key_parts = key.lower().replace(".", " ").split()
        label_parts = op.label.lower().split()
        desc_parts = op.description.lower().split()
        
        overlap_count = sum(1 for part in (key_parts + label_parts + desc_parts) if word_matches_any_token(part))
        score += overlap_count * 8.0
        
        for part in key_parts:
            if word_matches_any_token(part):
                score += 15.0
                
        if key in q or key.replace(".", " ") in q:
            score += 60.0
            
        if "niagara" in key or "niagra" in key:
            if any(word_matches_any_token(w) for w in ("niagara", "niagra", "emitter", "emitters")):
                score += 10.0
        if "physics" in key:
            if any(word_matches_any_token(w) for w in ("physics", "body", "constraint", "constraints", "joint")):
                score += 10.0
        if "blueprint" in key:
            if any(word_matches_any_token(w) for w in ("blueprint", "blueprints", "bp")):
                score += 10.0
        if "compile" in key:
            if any(word_matches_any_token(w) for w in ("compile", "recompile", "build")):
                score += 15.0
        if "rollback" in key:
            if any(word_matches_any_token(w) for w in ("rollback", "undo", "revert")):
                score += 20.0
                
        if score > best_score:
            best_score = score
            best_key = key
            
    return best_key, best_score


def unreal_prompt_to_operation(text: str) -> str:
    q = (text or "").lower()
    if "snapshot" in q or (
        re.search(r"\b(project|active level|selected actors|selected assets)\b", q)
        and re.search(r"\b(snapshot|scan|report|inspect)\b", q)
    ):
        return "project.snapshot"
    navigation_key, _navigation_params = unreal_navigation_operation_from_text(text)
    if navigation_key:
        return navigation_key
    if is_unreal_debug_request(text):
        return "project.debug"
    if is_unreal_niagara_create_request(text):
        return "niagara.create_emitter"
    if "blueprint" in q and ("create" in q or "make" in q or "new" in q) and "template" in q:
        return "blueprint.create_from_template"
    if is_unreal_prototype_request(text):
        return "gameplay.prototype_from_template"
        
    best_key, score = find_best_unreal_operation(text)
    if score >= 20.0:
        return best_key
        
    if any(
        term in q
        for term in ("loaded level", "current level", "actors in", "level actors")
    ):
        return "level.scan_loaded"
    if any(term in q for term in ("motion matching", "pose search")):
        return "motion_matching.create_database"
    if (extract_unreal_asset_name(text) or "blueprint" in q) and any(
        term in q
        for term in ("scan", "inspect", "parse", "what does", "variables", "functions", "graphs", "components")
    ):
        return "blueprint.scan"
    if any(
        term in q
        for term in ("inspect asset", "parse asset", "scan asset", "asset details")
    ):
        return "assets.inspect"
    if any(term in q for term in ("animation blueprint", "anim bp", "anim blueprint")):
        return "animation.create_anim_bp"
    if any(
        term in q
        for term in (
            "compatible animations",
            "find animations",
            "match animations",
            "compatible animation",
        )
    ):
        return "animation.find_compatible"
    if "blueprint" in q and any(term in q for term in ("compile", "validate")):
        return "blueprint.compile"
    if "blueprint" in q and any(
        term in q for term in ("template", "create", "prototype")
    ):
        return "blueprint.create_from_template"
    if "gameplay" in q and "prototype" in q:
        return "gameplay.prototype_from_template"
    if any(term in q for term in ("validate", "references", "broken refs")):
        return "validate.references"
    return "level.scan_loaded"


def generate_gameplay_prototype_steps(feature_goal: str) -> list[str]:
    q = (feature_goal or "").lower()
    
    if any(w in q for w in ("rewind", "time rewind", "personal rewind")):
        return [
            "Create a modular Actor Component named 'BPC_TimeRewindComponent'.",
            "Define custom struct 'FTimeKeyframe' containing Location, Rotation, Velocity, ControlRotation, and AnimTime.",
            "Implement tick recording into a rolling ring-buffer bounded by MaxHistoryDuration (e.g. 5 seconds).",
            "Set up reverse-playback interpolation to retrace the keyframe location history smoothly.",
            "Integrate input bindings on the target character blueprint to trigger the rewind state.",
            "Disable standard character movement and gravity during rewind playback, and restore state upon completion."
        ]
        
    if any(w in q for w in ("zip line", "zipline", "grapple", "grappling", "hook")):
        return [
            "Create a line-trace or projectile detection system to find valid anchor points in the level.",
            "Spawn and attach a CableComponent to visually connect the character to the target anchor.",
            "Disable standard character movement and apply acceleration vectors pulling the actor towards the anchor.",
            "Interpolate sliding speed along the cable vector and update camera framing.",
            "Implement detaching logic when the player jumps, reaches the end of the line, or hits an obstacle."
        ]
        
    if any(w in q for w in ("goo", "sticky", "glue", "fluid launcher")):
        return [
            "Create a weapon projectile class named 'BP_GooProjectile' with a collision sphere.",
            "Configure on-impact logic to spawn decal visual effects and a physics puddle actor 'BP_GooPuddle'.",
            "Implement overlap triggers on the puddle to decelerate entering characters by modifying their CharacterMovement Component speed.",
            "Add a decay timeline to fade out the decal and destroy the puddle actor after a set duration.",
            "Hook up firing inputs on the character's weapon component and spawn muzzle flash effects."
        ]
        
    if any(w in q for w in ("dash", "blink", "warp", "air dash")):
        return [
            "Calculate the dash vector based on current movement input or actor forward vector.",
            "Apply a launch velocity or swept teleport to move the actor rapidly while preventing clipping through geometry.",
            "Disable gravity during the dash and spawn trail particle/decal effects.",
            "Implement a cooldown timer and restrict multiple activations in mid-air.",
            "Apply temporary invulnerability frames or collision channel modifications during the dash window."
        ]
        
    if any(w in q for w in ("climbing", "climb", "mantle", "ledge grab")):
        return [
            "Set up forward and upward line traces to detect ledges and walls in front of the character.",
            "Create a climbing movement state that restricts movement to the wall plane.",
            "Interpolate actor transform to snap to the ledge height during a mantle.",
            "Play mantling or ledge-grab animations synchronized with the movement transition.",
            "Restore standard walking movement mode once the character has climbed over the ledge."
        ]

    feature_name = "gameplay"
    feature_match = re.search(
        r"\b(?:prototype|create|implement|build|make|add|set up|setup)\s+(?:a|an|the|new)?\s*([A-Za-z0-9 _-]{3,40}?)(?:\s+(?:feature|system|mechanic|ability|prototype|in|for|inside|with)\b|$)",
        feature_goal,
        re.IGNORECASE,
    )
    if feature_match:
        feature_name = feature_match.group(1).strip()
    else:
        words = [w for w in q.split() if w not in ("i", "want", "to", "have", "an", "ability", "that", "allows", "my", "character", "please", "come", "up", "with", "implementation", "plan")]
        if words:
            feature_name = " ".join(words[:3])

    return [
        f"Define the conceptual architecture for the new custom system: '{feature_name}'.",
        f"Create a custom Blueprint class or Actor Component (e.g., 'BPC_{feature_name.title().replace(' ', '')}Component') to isolate logic.",
        "Bind input keys or trigger zones in the character blueprint to drive the feature's activation.",
        "Implement state transitions and variable tracking (e.g., cooldowns, resources, active states).",
        "Integrate movement physics modifications, timelines, or animation montages as needed.",
        "Add visual/audio feedback (particles, UI indicators, sounds) to polish the user experience.",
        "Verify compiled blueprint status, search for broken references, and test inside the active level."
    ]


def generate_unreal_execution_steps(operation: str, params: dict[str, Any], raw_text: str) -> list[str]:
    steps = []
    
    asset_path = params.get("asset_path") or params.get("target_path") or params.get("blueprint_path") or ""
    asset_name = asset_path.split("/")[-1] if asset_path else ""
    
    semantic_graph = {}
    if isinstance(params, dict):
        semantic_graph = (
            params.get("semantic_graph_understanding")
            or (params.get("parameters") or {}).get("semantic_graph_understanding")
            or {}
        )
    if semantic_graph:
        steps.append("Build a semantic graph understanding report before modifying graph structure.")
        steps.append("Present a visible planned-change preview and wait for confirmation when risk, ambiguity, or destructiveness requires it.")
        steps.append("Open and focus the affected Unreal asset/graph before applying graph changes.")
        steps.append("Re-verify the target graph, nodes, pins, connections, and stale-state assumptions immediately before mutation.")
        steps.append("Identify subsystem intent, existing behavior, integration points, and preservation checks.")
        steps.append("Reserve graph layout space, preserve local graph style, and group new logic with intent-based comments.")

    if operation == "niagara.create_emitter":
        steps.append(f"Create a new Niagara emitter asset named '{asset_name or 'NE_AIStudioEmitter'}' at '{asset_path or '/Game/AIStudio/Prototypes/Niagara/NE_AIStudioEmitter'}'.")
        q = raw_text.lower()
        if any(w in q for w in ("attach", "connect", "link", "parent")):
            joint_name = "hand_l" if "left hand" in q or "hand_l" in q else ("hand_r" if "right hand" in q or "hand_r" in q else "")
            target_bp = "BP_LesterPhoenix" if "bp lester" in q or "lester" in q else ""
            if target_bp:
                if joint_name:
                    steps.append(f"Attach the new Niagara emitter component to the '{joint_name}' joint of character '{target_bp}'.")
                else:
                    steps.append(f"Attach the new Niagara emitter component to the root mesh of character '{target_bp}'.")
            else:
                steps.append("Attach the new Niagara emitter component to the selected character or level actor.")
                
    elif operation == "niagara.add_to_level":
        steps.append(f"Spawn a Niagara system/actor for the emitter/system '{asset_name or 'emitter'}' in the current level.")
        q = raw_text.lower()
        if any(w in q for w in ("attach", "connect", "link", "parent")):
            joint_name = "hand_l" if "left hand" in q or "hand_l" in q else ("hand_r" if "right hand" in q or "hand_r" in q else "")
            target_bp = "BP_LesterPhoenix" if "bp lester" in q or "lester" in q else ""
            if target_bp:
                steps.append(f"Attach the spawned Niagara system component to the '{joint_name or 'root'}' joint of character '{target_bp}'.")
            else:
                steps.append("Attach the spawned Niagara system component to the selected target joint or bone.")
                
    elif operation == "physics.set_body_property":
        body = params.get("body_name") or "default_body"
        prop = params.get("property_name") or "property"
        val = params.get("value") or "value"
        steps.append(f"Load the physics asset for '{asset_name or 'target asset'}'.")
        steps.append(f"Find the physics body matching '{body}'.")
        steps.append(f"Set the physics property '{prop}' to '{val}' in the editor.")
        
    elif operation == "blueprint.compile":
        steps.append(f"Locate and load the target Blueprint '{asset_name or 'selected Blueprint'}'.")
        steps.append(f"Trigger the compilation of '{asset_name or 'selected Blueprint'}' in the editor.")
        steps.append("Check for compile warnings or errors and report status.")
        
    elif operation == "gameplay.prototype_from_template":
        steps.extend(generate_gameplay_prototype_steps(raw_text))
        
    elif operation == "rollback.latest":
        steps.append("Inspect the local transaction and file modify history.")
        steps.append("Revert the last modification made to Unreal assets or Blueprint graphs.")
        
    elif operation == "validate.references":
        steps.append("Scan all asset packages in the project directory.")
        steps.append("Find any missing, broken, or unresolved references between assets.")
        
    else:
        q = raw_text.lower()
        if any(w in q for w in ("ability", "system", "mechanic", "feature", "weapon", "character", "power", "skill", "prototype")):
            steps.extend(generate_gameplay_prototype_steps(raw_text))
        else:
            steps.append(f"Identify and prepare the Unreal operation: '{operation}'.")
            for k, v in params.items():
                steps.append(f"Configure parameter '{k}' with value '{v}'.")
            
    steps.append("Compile and save modified assets to prevent unsaved data loss in the editor.")
    steps.append("Validate references and check the editor log output for warnings or errors.")
    return steps


def build_unreal_execution_plan(
    text: str,
    context: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from tech_connector.bridges.unreal import unreal_intent_parser as _uip
    from tech_connector.services.unreal.semantic_graph_service import (
        build_semantic_graph_analysis,
        is_unreal_graph_modification_request,
    )

    context = context or {}
    settings = settings or {}
    raw_text = text or ""
    lower = raw_text.lower()
    intent = _uip.parse(raw_text)
    action = intent.action if intent else "llm"
    target_assets = extract_unreal_asset_paths(raw_text)
    from tech_connector.services.unreal.rewrite_plan_service import (
        build_rewrite_plan,
        detect_high_risk_graph_request,
    )

    high_risk_graph_rewrite = detect_high_risk_graph_request(raw_text)
    semantic_graph_required = is_unreal_graph_modification_request(raw_text) or high_risk_graph_rewrite
    mutating = action == "create" or high_risk_graph_rewrite

    if high_risk_graph_rewrite and action not in {"create", "debug"}:
        action = "create"

    resolved_op_key = unreal_prompt_to_operation(raw_text)
    
    if resolved_op_key and resolved_op_key in UNREAL_OPERATIONS:
        op = UNREAL_OPERATIONS[resolved_op_key]
        operation = resolved_op_key
        mutating = op.mutates_project or action == "create" or high_risk_graph_rewrite
        
        if operation == "project.debug":
            params = build_unreal_debug_params(raw_text)
        elif operation == "niagara.create_emitter":
            params = build_unreal_niagara_create_params(raw_text)
            if params.get("asset_path"):
                target_assets.append(params["asset_path"])
        elif operation == "gameplay.prototype_from_template":
            params = build_unreal_prototype_params(raw_text, settings=settings)
            if params.get("target_path"):
                target_assets.append(params["target_path"])
            params.setdefault("parameters", {})["safe_graph_rewrite"] = False
            params["parameters"]["require_plan_only_for_graph_changes"] = bool(
                high_risk_graph_rewrite
            )
        elif operation == "project.scan_assets" and intent and intent.asset_class:
            params = {
                "mode": "standard",
                "directory": intent.directory or "/Game/",
                "asset_class": intent.asset_class,
            }
        elif operation == "project.scan_assets":
            params = {"mode": "standard", "directory": "/Game/"}
        elif operation == "project.snapshot":
            params = {"mode": "standard", "directory": "/Game/"}
        elif operation == "assets.inspect":
            asset_path = target_assets[0] if target_assets else ""
            params = {"asset_path": asset_path} if asset_path else {"directory": "/Game/"}
        else:
            params = {}
            if target_assets:
                if "asset_path" in op.required or "asset_path" in op.optional:
                    params["asset_path"] = target_assets[0]
                elif "target_path" in op.required or "target_path" in op.optional:
                    params["target_path"] = target_assets[0]
                elif "blueprint_path" in op.required or "blueprint_path" in op.optional:
                    params["blueprint_path"] = target_assets[0]
                    
            num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", raw_text)
            if num_match:
                val = float(num_match.group(1))
                if val.is_integer():
                    val = int(val)
                if "value" in op.required or "value" in op.optional:
                    params["value"] = val
                    
            words = [
                w for w in re.findall(r"\b[A-Za-z0-9_]{3,}\b", raw_text)
                if w.lower() not in {
                    "unreal", "set", "physics", "body", "property", "value",
                    "parameter", "niagara", "emitter", "system", "component"
                }
            ]
            if words:
                if "property_name" in op.required or "property_name" in op.optional:
                    params["property_name"] = words[0]
                if "body_name" in op.required or "body_name" in op.optional:
                    params["body_name"] = words[-1] if len(words) > 1 else words[0]
                if "parameter_name" in op.required or "parameter_name" in op.optional:
                    params["parameter_name"] = words[0]
    else:
        operation = "llm_fallback"
        params = {}
        mutating = action == "create" or high_risk_graph_rewrite

    for p_key in ("asset_path", "target_path", "blueprint_path"):
        if p_key in params and isinstance(params[p_key], str):
            default_name = "NE_AIStudioEmitter" if "niagara" in operation else ("BP_NewBlueprint" if "blueprint" in operation else "Asset")
            params[p_key] = normalize_unreal_package_path(params[p_key], default_name=default_name)

    risk_level = (
        "high" if high_risk_graph_rewrite else ("medium" if mutating else "low")
    )
    semantic_graph = (
        build_semantic_graph_analysis(raw_text, context=context, operation=operation, params=params)
        if semantic_graph_required
        else {}
    )
    if semantic_graph:
        params.setdefault("parameters", {}) if isinstance(params, dict) else None
        if isinstance(params, dict):
            params["semantic_graph_understanding"] = semantic_graph
            if isinstance(params.get("parameters"), dict):
                params["parameters"].setdefault("semantic_graph_understanding", semantic_graph)
                params["parameters"].setdefault("visible_edit_workflow", semantic_graph.get("visible_edit_lifecycle") or [])
                params["parameters"].setdefault("graph_edit_state_machine", semantic_graph.get("lifecycle_states") or [])
                params["parameters"].setdefault("graph_layout_contract", semantic_graph.get("layout_contract") or [])
                params["parameters"].setdefault("graph_edit_progress_stages", semantic_graph.get("progress_stages") or [])
                params["parameters"].setdefault("graph_edit_threading_contract", semantic_graph.get("threading_contract") or {})
    return {
        "ok": True,
        "action": action,
        "operation": operation,
        "mutates_project": bool(mutating),
        "requires_confirmation": bool(mutating),
        "high_risk_graph_rewrite": bool(high_risk_graph_rewrite),
        "risk_level": risk_level,
        "semantic_graph_required": bool(semantic_graph_required),
        "semantic_graph_understanding": semantic_graph,
        "visible_edit_lifecycle": semantic_graph.get("visible_edit_lifecycle") if semantic_graph else [],
        "graph_edit_state_machine": semantic_graph.get("lifecycle_states") if semantic_graph else [],
        "graph_layout_contract": semantic_graph.get("layout_contract") if semantic_graph else [],
        "graph_edit_progress_stages": semantic_graph.get("progress_stages") if semantic_graph else [],
        "graph_edit_threading_contract": semantic_graph.get("threading_contract") if semantic_graph else {},
        "affected_assets": list(dict.fromkeys([str(x) for x in target_assets if x])),
        "editor_context_summary": context.get("summary") or "",
        "recommended_model": context.get("recommended_model")
        or "local|cloud|strong_reasoning",
        "steps": generate_unreal_execution_steps(operation, params, raw_text),
        "rewrite_plan": build_rewrite_plan(raw_text, context=context)
        if high_risk_graph_rewrite
        else None,
        "params": params,
        "raw_request": raw_text,
    
    # ── Traversal, Gameplay, Navigation & Physics Additions ──
    "animation.set_slot_animation": UnrealOperation(
        key="animation.set_slot_animation",
        label="Unreal Set Slot Animation",
        function="unreal_tools.animation.set_slot_animation",
        required=("anim_bp_path", "slot_name", "animation_path"),
        mutates_project=True,
        description="Assign an animation sequence or blend space to a specific slot (like UpperBody) inside an Animation Blueprint.",
    ),
    "motion_matching.add_state_animations": UnrealOperation(
        key="motion_matching.add_state_animations",
        label="Unreal Add Motion Matching State Animations",
        function="unreal_tools.motion_matching.add_state_animations",
        required=("database_path", "animation_paths", "state_tag"),
        mutates_project=True,
        description="Add a set of animations corresponding to a gameplay state (climbing, flying, traversal) into a Pose Search Database.",
    ),
    "physics.create_physics_asset": UnrealOperation(
        key="physics.create_physics_asset",
        label="Unreal Create Physics Asset",
        function="unreal_tools.physics.create_physics_asset",
        required=("skeletal_mesh_path",),
        optional={"save_path": ""},
        mutates_project=True,
        description="Create a physics asset (bodies, joints) for the given Skeletal Mesh.",
    ),
    "physics.add_body": UnrealOperation(
        key="physics.add_body",
        label="Unreal Add Physics Body",
        function="unreal_tools.physics.add_body",
        required=("physics_asset_path", "bone_name", "shape_type"),
        mutates_project=True,
        description="Add a physical body shape (capsule, sphere, box) for a specific bone in the physics asset.",
    ),
    "physics.add_constraint": UnrealOperation(
        key="physics.add_constraint",
        label="Unreal Add Physics Constraint",
        function="unreal_tools.physics.add_constraint",
        required=("physics_asset_path", "bone_name_a", "bone_name_b"),
        mutates_project=True,
        description="Add a physical constraint connecting physics body A to physics body B.",
    ),
    "physics.set_collision_profile": UnrealOperation(
        key="physics.set_collision_profile",
        label="Unreal Set Collision Profile preset",
        function="unreal_tools.physics.set_collision_profile",
        required=("actor_query", "profile_name"),
        optional={"component_name": ""},
        mutates_project=True,
        description="Assign a collision preset profile (like Ragdoll, Pawn, blockAll) to a physical component or actor.",
    ),
    "navigation.add_nav_mesh_bounds": UnrealOperation(
        key="navigation.add_nav_mesh_bounds",
        label="Unreal Add Nav Mesh Bounds Volume",
        function="unreal_tools.navigation.add_nav_mesh_bounds",
        optional={"location": [0.0, 0.0, 0.0], "extent": [1000.0, 1000.0, 500.0]},
        mutates_project=True,
        description="Place a Nav Mesh Bounds Volume in the current level to enable pathfinding.",
    ),
    "gameplay.create_gameplay_ability": UnrealOperation(
        key="gameplay.create_gameplay_ability",
        label="Unreal Create Gameplay Ability",
        function="unreal_tools.gameplay.create_gameplay_ability",
        required=("ability_name",),
        optional={"save_path": ""},
        mutates_project=True,
        description="Create a new Gameplay Ability class or Component for traversal actions (climbing, flying, dash).",
    ),
}


def explain_unreal_execution_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, default=str)
