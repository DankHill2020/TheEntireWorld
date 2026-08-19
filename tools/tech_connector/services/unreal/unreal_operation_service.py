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
    execution_host: str = "unreal"
    description: str = ""
    execution_mode: str = "host_native"
    delegation: dict[str, Any] = field(default_factory=dict)


UNREAL_OPERATIONS: dict[str, UnrealOperation] = {
    "anim_graph.add_state_machine": UnrealOperation(
        key="anim_graph.add_state_machine",
        label="Unreal Anim Graph Add State Machine",
        function="unreal_tools.animation.add_state_machine",
        required=("anim_bp_path", "state_machine_name"),
        mutates_project=True,
        description="Add a new State Machine node to the AnimGraph of an Animation Blueprint.",
    ),
    "anim_graph.add_state": UnrealOperation(
        key="anim_graph.add_state",
        label="Unreal Anim Graph Add State",
        function="unreal_tools.animation.add_state",
        required=("anim_bp_path", "state_machine_name", "state_name"),
        optional={"animation_asset_path": ""},
        mutates_project=True,
        description="Add a state (with optional animation asset) to a State Machine inside an Animation Blueprint.",
    ),
    "anim_graph.add_transition_rule": UnrealOperation(
        key="anim_graph.add_transition_rule",
        label="Unreal Anim Graph Add Transition Rule",
        function="unreal_tools.animation.add_transition_rule",
        required=("anim_bp_path", "state_machine_name", "from_state", "to_state", "rule_expression"),
        mutates_project=True,
        description="Add a transition rule between two states inside an Animation Blueprint State Machine.",
    ),
    "anim_graph.wire_state_machine_to_output_pose": UnrealOperation(
        key="anim_graph.wire_state_machine_to_output_pose",
        label="Unreal Anim Graph Wire State Machine to Output Pose",
        function="unreal_tools.animation.wire_state_machine_to_output_pose",
        required=("anim_bp_path", "state_machine_name"),
        mutates_project=True,
        description="Wire a State Machine node's output to the Output Pose node in an Animation Blueprint.",
    ),
    "anim_graph.synthesize_transition_rule_expression": UnrealOperation(
        key="anim_graph.synthesize_transition_rule_expression",
        label="Unreal Anim Graph Synthesize Transition Rule Expression",
        function="unreal_tools.animation.synthesize_transition_rule_expression",
        required=("anim_bp_path", "state_machine_name", "from_state", "to_state", "rule_expression"),
        mutates_project=True,
        description="Synthesize and apply a transition rule expression (e.g. variable comparison) between two states.",
    ),
    "project.snapshot": UnrealOperation(
        key="project.snapshot",
        label="Unreal Project Snapshot",
        function="unreal_tools.project.project_snapshot",
        optional={"directory": "/Game/"},
        description="Gather loaded-level state plus core project asset inventory for model context.",
    ),
    "knowledge.search_sources": UnrealOperation(
        key="knowledge.search_sources",
        label="Search Knowledge Sources",
        function="tech_connector.services.knowledge_research_service.search_public_sources",
        required=("query",),
        execution_host="desktop",
        description="Search public sources for research.",
    ),
    "knowledge.extract_claims": UnrealOperation(
        key="knowledge.extract_claims",
        label="Extract Claims from Sources",
        function="tech_connector.services.knowledge_research_service.extract_public_source_claims",
        required=("sources",),
        execution_host="desktop",
        description="Extract claims from search results.",
    ),
    "knowledge.compare_approaches": UnrealOperation(
        key="knowledge.compare_approaches",
        label="Compare Approaches",
        function="tech_connector.services.unreal.technique_currency_service.compare_technique_candidates",
        required=("baseline", "candidates"),
        execution_host="desktop",
        description="Compare baseline technique against candidates.",
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
        description="Add a Blueprint-authored component with SubobjectData compile/save readback.",
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
        function="unreal_tools.project.project_debug",
        optional={
            "directory": "/Game/",
            "paths": [],
            "compile_blueprints": True,
            "save": False,
        },
        mutates_project=True,
        description="Scan project/level state, validate references, compile Blueprints when supported, and report what is broken plus suggested fixes.",
    ),
    "rollback.latest": UnrealOperation(
        key="rollback.latest",
        label="Unreal Rollback Latest Operation",
        function="unreal_tools.rollback.latest",
        mutates_project=True,
        description="Rollback the latest tracked safe operation when the Unreal side supports rollback data.",
    ),
    "rollback.record_asset_snapshot": UnrealOperation(
        key="rollback.record_asset_snapshot",
        label="Record Unreal Asset Snapshot",
        function="unreal_tools.rollback.record_asset_snapshot",
        required=("asset_path",),
        optional={"reason": "", "operation": "", "metadata": {}},
        mutates_project=True,
        description="Duplicate an asset into the rollback journal before a bounded mutation.",
    ),
    "rollback.restore_asset_snapshot": UnrealOperation(
        key="rollback.restore_asset_snapshot",
        label="Restore Unreal Asset Snapshot",
        function="unreal_tools.rollback.restore_asset_snapshot",
        optional={"token": ""},
        mutates_project=True,
        description="Restore the asset recorded by a rollback journal token, or the latest snapshot.",
    ),
    "network.inspect_authority_flow": UnrealOperation(
        key="network.inspect_authority_flow",
        label="Inspect Unreal Authority Flow",
        function="unreal_tools.networking.inspect_authority_flow",
        required=("blueprint_path",),
        optional={
            "required_variables": [],
            "required_server_rpcs": [],
            "required_onrep_functions": [],
        },
        description="Read back replicated properties, RPC functions, authority nodes, and compile state.",
    ),
    "skeletal.inspect_bones": UnrealOperation(
        key="skeletal.inspect_bones",
        label="Inspect Unreal Skeletal Mesh Bones",
        function="unreal_tools.skeletal.inspect_bones",
        required=("skeletal_mesh_path",),
        optional={"include_hierarchy": True},
        description="Read bone names and hierarchy from a SkeletalMesh before attachment or retargeting.",
    ),
    "runtime.pie_begin": UnrealOperation(
        key="runtime.pie_begin",
        label="Unreal Begin PIE",
        function="unreal_tools.runtime.begin_pie",
        optional={"simulate": False},
        description="Request Play In Editor and report whether PIE was already active or started.",
    ),
    "runtime.pie_status": UnrealOperation(
        key="runtime.pie_status",
        label="Unreal Inspect PIE Status",
        function="unreal_tools.runtime.pie_status",
        description="Read the current PIE lifecycle state and available PIE worlds.",
    ),
    "runtime.pie_end": UnrealOperation(
        key="runtime.pie_end",
        label="Unreal End PIE",
        function="unreal_tools.runtime.end_pie",
        description="Request PIE shutdown and report the observed prior state.",
    ),
    "runtime.inject_key": UnrealOperation(
        key="runtime.inject_key",
        label="Unreal Inject PIE Key",
        function="unreal_tools.runtime.inject_key",
        required=("key_name",),
        optional={"pressed": True},
        description="Inject a public keyboard input into the active PIE viewport through AIStudioBridge.",
    ),
    "runtime.inspect_character": UnrealOperation(
        key="runtime.inspect_character",
        label="Unreal Inspect Character In PIE",
        function="unreal_tools.runtime.inspect_character",
        required=("character_blueprint_path",),
        optional={"expected_anim_class_contains": "", "property_names": []},
        description="Observe a live PIE character, its requested properties, active AnimInstance, and active montage.",
    ),
    "runtime.validate_character_montages": UnrealOperation(
        key="runtime.validate_character_montages",
        label="Unreal Validate Character Montages In PIE",
        function="unreal_tools.runtime.validate_character_montages",
        required=("character_blueprint_path", "montage_paths"),
        optional={"expected_anim_class_contains": ""},
        description="Play and observe montage assets on the live character AnimInstance; asset existence alone is not accepted.",
    ),
    "runtime.pie_validate": UnrealOperation(
        key="runtime.pie_validate",
        label="Unreal Validate PIE Scenario",
        function="unreal_tools.runtime.pie_validate",
        optional={"target_assets": [], "expected": {}, "start_pie": False},
        description="Fail-closed PIE validation of target assets and structured runtime expectations.",
    ),
    "runtime.multiplayer_pie_validate": UnrealOperation(
        key="runtime.multiplayer_pie_validate",
        label="Unreal Multiplayer PIE Validation",
        function="unreal_tools.runtime.multiplayer_pie_validate",
        optional={
            "target_assets": [],
            "expected": {},
            "client_count": 2,
            "start_pie": True,
        },
        description="Configure and inspect a multi-client PIE session with structured readback proof.",
    ),
    "semantic_index.record_runtime_observation": UnrealOperation(
        key="semantic_index.record_runtime_observation",
        label="Record Unreal Runtime Observation",
        function="tech_connector.services.unreal.semantic_project_index_service.record_unreal_runtime_observation",
        required=("scenario_key", "status", "assertions", "evidence"),
        optional={"subject_key": "", "project_root": None},
        execution_host="desktop",
        description="Persist structured PIE evidence in the project semantic index.",
    ),
    "feature.execute_generic_plan": UnrealOperation(
        key="feature.execute_generic_plan",
        label="Unreal Execute Generic Feature Plan",
        function="tech_connector.services.unreal.orchestration.execute_generic_plan",
        required=("plan",),
        optional={"dry_run": True},
        execution_host="desktop",
        description="Validate generic approved-plan execution readiness without embedding feature recipes.",
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
    "level.organize_actors": UnrealOperation(
        key="level.organize_actors",
        label="Organize Unreal Level Actors",
        function="unreal_tools.level.organize_actors",
        required=("actor_specs",),
        optional={"save": True},
        mutates_project=True,
        description=(
            "Transactionally organize exact loaded actors by Outliner folder, label, "
            "tags, and editor visibility with ambiguity rejection and readback."
        ),
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
        description="Set a Blueprint default property through an explicit Unreal Editor handoff until typed CDO readback is installed.",
        execution_mode="user_delegated",
        delegation={
            "surface": "Blueprint Editor > Class Defaults",
            "action": "Set the named default property to the requested value and compile/save the Blueprint.",
            "verification": "Reopen Class Defaults and confirm the persisted value after compilation.",
        },
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
        description="Open a Blueprint graph through an explicit Unreal Editor UI handoff.",
        execution_mode="user_delegated",
        delegation={
            "surface": "Blueprint Editor > My Blueprint",
            "action": "Open the requested graph in the selected Blueprint asset.",
            "verification": "Confirm the active graph tab name matches the requested graph.",
        },
    ),
    "blueprint.open_function": UnrealOperation(
        key="blueprint.open_function",
        label="Unreal Open Blueprint Function",
        function="unreal_tools.blueprint.open_function",
        required=("blueprint_path", "function_name"),
        mutates_project=True,
        description="Open a Blueprint function graph through an explicit Unreal Editor UI handoff.",
        execution_mode="user_delegated",
        delegation={
            "surface": "Blueprint Editor > My Blueprint > Functions",
            "action": "Open the requested function graph in the selected Blueprint asset.",
            "verification": "Confirm the active graph tab name matches the requested function.",
        },
    ),
    "blueprint.configure_replication": UnrealOperation(
        key="blueprint.configure_replication",
        label="Configure Blueprint Replication",
        function="unreal_tools.networking.configure_blueprint_replication",
        required=("blueprint_path",),
        optional={
            "replicated_variables": [],
            "rep_notify_variables": [],
            "server_rpc_functions": [],
            "reliable": True,
            "save": True,
        },
        mutates_project=True,
        description="Configure replicated variables, RepNotify fields, and server RPCs.",
    ),
    "asset.create_by_class_path": UnrealOperation(
        key="asset.create_by_class_path",
        label="Create Reflected Asset by Class Path",
        function="unreal_tools.assets.create_by_class_path",
        required=("asset_path", "class_path"),
        optional={"initial_properties": {}},
        mutates_project=True,
        description="Create a supported asset from an exact reflected class path.",
    ),
    "asset.inspect_reflected": UnrealOperation(
        key="asset.inspect_reflected",
        label="Inspect Reflected Asset",
        function="unreal_tools.assets.inspect_reflected",
        required=("asset_path",),
        optional={"property_names": []},
        description="Read reflected properties from an Unreal asset.",
    ),
    "asset.set_reflected_property": UnrealOperation(
        key="asset.set_reflected_property",
        label="Set Reflected Asset Property",
        function="unreal_tools.assets.set_reflected_property",
        required=("asset_path", "property_name", "value"),
        mutates_project=True,
        description="Set and read back one reflected Unreal asset property.",
    ),
    "asset.array_add_object_reference": UnrealOperation(
        key="asset.array_add_object_reference",
        label="Add Reflected Object Array Reference",
        function="unreal_tools.assets.array_add_object_reference",
        required=("asset_path", "property_name", "object_path"),
        mutates_project=True,
        description="Add an object reference to a reflected array with readback.",
    ),
    "asset.array_remove_object_reference": UnrealOperation(
        key="asset.array_remove_object_reference",
        label="Remove Reflected Object Array Reference",
        function="unreal_tools.assets.array_remove_object_reference",
        required=("asset_path", "property_name", "object_path"),
        mutates_project=True,
        description="Remove an object reference from a reflected array with readback.",
    ),
    "material.inspect": UnrealOperation(
        key="material.inspect",
        label="Inspect Unreal Material",
        function="unreal_tools.materials.inspect_material",
        required=("asset_path",),
        description="Inspect material expressions and material-property graph connections.",
    ),
    "material.create": UnrealOperation(
        key="material.create",
        label="Create Unreal Material",
        function="unreal_tools.materials.create_material",
        required=("asset_path",),
        optional={"overwrite": False, "dry_run": False},
        mutates_project=True,
        description="Create a blank Material with save and asset-registry readback.",
    ),
    "material.create_parameterized_pbr": UnrealOperation(
        key="material.create_parameterized_pbr",
        label="Create Parameterized PBR Material",
        function="unreal_tools.materials.create_parameterized_pbr_material",
        required=("asset_path",),
        optional={
            "base_color": [0.18, 0.35, 0.8, 1.0],
            "roughness": 0.5,
            "metallic": 0.0,
            "overwrite": False,
            "dry_run": False,
            "cleanup_on_failure": True,
        },
        mutates_project=True,
        description="Create, wire, compile, save, and verify a parameterized PBR material graph.",
    ),
    "material.create_from_spec": UnrealOperation(
        key="material.create_from_spec",
        label="Create Unreal Material Graph from Specification",
        function="unreal_tools.materials.create_material_from_spec",
        required=("asset_path", "nodes"),
        optional={
            "connections": [],
            "outputs": [],
            "material_domain": "MD_SURFACE",
            "material_properties": {},
            "overwrite": False,
            "dry_run": False,
            "cleanup_on_failure": True,
        },
        mutates_project=True,
        description=(
            "Create a generic Surface, Post Process, UI, or other Material graph from "
            "validated expression nodes, connections, outputs, reflected properties, and domain."
        ),
    ),
    "sound_cue.create_from_wave": UnrealOperation(
        key="sound_cue.create_from_wave",
        label="Create Playable Unreal Sound Cue",
        function="unreal_tools.sound_cue.create_from_wave",
        required=("asset_path", "sound_wave_path"),
        optional={
            "looping": False,
            "volume_multiplier": 1.0,
            "pitch_multiplier": 1.0,
            "overwrite": False,
            "dry_run": False,
            "cleanup_on_failure": True,
        },
        mutates_project=True,
        description=(
            "Create a playable Sound Cue from a Sound Wave, configure looping, volume, "
            "and pitch, save it, and verify the Wave Player root."
        ),
    ),
    "sound_cue.inspect": UnrealOperation(
        key="sound_cue.inspect",
        label="Inspect Unreal Sound Cue",
        function="unreal_tools.sound_cue.inspect_sound_cue",
        required=("asset_path",),
        description="Inspect a Sound Cue's playable root node and Sound Wave reference.",
    ),
    "data_table.create_from_rows": UnrealOperation(
        key="data_table.create_from_rows",
        label="Create Unreal Data Table From Rows",
        function="unreal_tools.data_tables.create_from_rows",
        required=("asset_path", "row_struct_path", "rows"),
        optional={"overwrite": False, "dry_run": False, "cleanup_on_failure": True},
        mutates_project=True,
        description=(
            "Create a Data Table for a native or asset-backed row struct, fill validated "
            "JSON rows, save, and verify exact row-name and column readback."
        ),
    ),
    "data_table.inspect": UnrealOperation(
        key="data_table.inspect",
        label="Inspect Unreal Data Table",
        function="unreal_tools.data_tables.inspect_data_table",
        required=("asset_path",),
        optional={"include_rows": False, "max_rows": 200},
        description="Inspect a Data Table row struct, columns, row names, and JSON export.",
    ),
    "domain_asset.create": UnrealOperation(
        key="domain_asset.create",
        label="Create Unreal Domain Asset",
        function="unreal_tools.domain_assets.create_domain_asset",
        required=("asset_type", "asset_path"),
        optional={"overwrite": False, "dry_run": False, "cleanup_on_failure": True},
        mutates_project=True,
        description=(
            "Create a Widget Blueprint, PCG Graph, Behavior Tree, Blackboard, Level Sequence, "
            "or a factory-compatible MetaSound asset with class/save/registry readback."
        ),
    ),
    "domain_asset.inspect": UnrealOperation(
        key="domain_asset.inspect",
        label="Inspect Unreal Domain Asset",
        function="unreal_tools.domain_assets.inspect_domain_asset",
        required=("asset_path",),
        optional={"expected_type": ""},
        description="Inspect a domain asset and verify its reflected class and asset-registry identity.",
    ),
    "pcg.inspect_graph": UnrealOperation(
        key="pcg.inspect_graph",
        label="Inspect PCG Graph",
        function="unreal_tools.pcg.inspect_graph",
        required=("graph_path",),
        description="Inspect PCG nodes, settings classes, positions, pins, and directed edges.",
    ),
    "pcg.create_grid_transform_graph": UnrealOperation(
        key="pcg.create_grid_transform_graph",
        label="Author PCG Grid Transform Graph",
        function="unreal_tools.pcg.create_grid_transform_graph",
        required=("graph_path",),
        optional={
            "grid_extents": [1000.0, 1000.0, 100.0],
            "cell_size": [200.0, 200.0, 200.0],
            "offset": [0.0, 0.0, 100.0],
            "save": True,
        },
        mutates_project=True,
        description="Author, connect, save, and read back a Grid to Transform PCG graph.",
    ),
    "pcg.apply_graph_spec": UnrealOperation(
        key="pcg.apply_graph_spec",
        label="Apply Typed PCG Graph Specification",
        function="unreal_tools.pcg.apply_graph_spec",
        required=("graph_path", "nodes", "edges"),
        optional={"clear_existing": True, "save": True},
        mutates_project=True,
        description="Apply validated PCG settings classes, properties, positions, and typed pin connections.",
    ),
    "metasound.create_sine_tone_source": UnrealOperation(
        key="metasound.create_sine_tone_source",
        label="Author MetaSound Sine Tone Source",
        function="unreal_tools.metasound.create_sine_tone_source",
        required=("asset_path",),
        optional={
            "frequency": 440.0,
            "author": "Tech Connector",
            "overwrite": False,
            "dry_run": False,
            "cleanup_on_failure": True,
        },
        mutates_project=True,
        description="Author, connect, serialize, save, and read back a mono MetaSound sine source.",
    ),
    "metasound.create_source_from_spec": UnrealOperation(
        key="metasound.create_source_from_spec",
        label="Create MetaSound Source From Typed Graph Specification",
        function="unreal_tools.metasound.create_source_from_spec",
        required=("asset_path", "nodes", "connections"),
        optional={
            "author": "Tech Connector",
            "overwrite": False,
            "dry_run": False,
            "cleanup_on_failure": True,
        },
        mutates_project=True,
        description="Build a mono MetaSound Source from registered classes, typed defaults, and named-vertex connections.",
    ),
    "blackboard.inspect_schema": UnrealOperation(
        key="blackboard.inspect_schema",
        label="Inspect Blackboard Schema",
        function="unreal_tools.blackboard.inspect_schema",
        required=("asset_path",),
        description="Inspect Blackboard key names, types, categories, and synchronization settings.",
    ),
    "blackboard.set_schema": UnrealOperation(
        key="blackboard.set_schema",
        label="Author Blackboard Schema",
        function="unreal_tools.blackboard.set_schema",
        required=("asset_path", "keys"),
        optional={"replace_existing": True, "save": True},
        mutates_project=True,
        description="Author, save, and read back a typed Blackboard schema.",
    ),
    "widget.author_canvas_text": UnrealOperation(
        key="widget.author_canvas_text",
        label="Author Widget Blueprint Canvas and Text",
        function="unreal_tools.widget.author_canvas_text",
        required=("widget_blueprint_path",),
        optional={
            "root_name": "RootCanvas",
            "text_name": "TitleText",
            "text": "Tech Connector",
            "save": True,
        },
        mutates_project=True,
        description="Transactionally author, compile, save, and read back a Widget Blueprint design tree.",
    ),
    "widget.author_from_spec": UnrealOperation(
        key="widget.author_from_spec",
        label="Author Widget Blueprint From Specification",
        function="unreal_tools.widget.author_from_spec",
        required=("widget_blueprint_path", "widgets"),
        optional={"save": True},
        mutates_project=True,
        description=(
            "Transactionally author, compile, save, and read back a validated "
            "Widget Blueprint hierarchy."
        ),
    ),
    "behavior_tree.author_baseline": UnrealOperation(
        key="behavior_tree.author_baseline",
        label="Author Behavior Tree Baseline",
        function="unreal_tools.behavior_tree.author_baseline",
        required=("behavior_tree_path",),
        optional={"blackboard_path": "", "wait_seconds": 1.0, "save": True},
        mutates_project=True,
        description="Author Root to Selector to Wait topology, rebuild runtime data, save, and read back.",
    ),
    "behavior_tree.author_wait_graph": UnrealOperation(
        key="behavior_tree.author_wait_graph",
        label="Author Behavior Tree Wait Graph",
        function="unreal_tools.behavior_tree.author_wait_graph",
        required=("behavior_tree_path", "composite_type", "wait_seconds"),
        optional={"blackboard_path": "", "save": True},
        mutates_project=True,
        description="Author a Selector or Sequence with multiple ordered Wait task children and runtime readback.",
    ),
    "behavior_tree.author_task_graph": UnrealOperation(
        key="behavior_tree.author_task_graph",
        label="Author Mixed Behavior Tree Task Graph",
        function="unreal_tools.behavior_tree.author_task_graph",
        required=("behavior_tree_path", "blackboard_path", "tasks"),
        optional={"composite_type": "sequence", "save": True},
        mutates_project=True,
        description=(
            "Author a Selector or Sequence containing ordered Move To and Wait tasks, "
            "resolve Blackboard keys, rebuild runtime data, save, and return dual readback."
        ),
    ),
    "physics.add_profile": UnrealOperation(
        key="physics.add_profile",
        label="Add Physics Asset Profile",
        function="unreal_tools.physics.add_profile",
        required=("asset_path", "profile_name", "profile_type"),
        optional={"assign_all": False},
        mutates_project=True,
        description="Add and optionally assign a physical animation or constraint profile.",
    ),
    "physics.remove_profile": UnrealOperation(
        key="physics.remove_profile",
        label="Remove Physics Asset Profile",
        function="unreal_tools.physics.remove_profile",
        required=("asset_path", "profile_name", "profile_type"),
        mutates_project=True,
        description="Remove a physical animation or constraint profile with readback.",
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
    "unreal.create_blendspace": UnrealOperation(
        key="unreal.create_blendspace",
        label="Create or Update Unreal BlendSpace",
        function="unreal_tools.animation.create_blendspace",
        required=("asset_path", "skeleton_path"),
        optional={
            "samples": [],
            "animation_paths": [],
            "axis_x": {},
            "axis_y": {},
            "save": True,
        },
        mutates_project=True,
        description=(
            "Create or update a BlendSpace and verify its samples through the "
            "reflected AIStudio bridge."
        ),
    ),
    "animation.inspect_imported_pipeline": UnrealOperation(
        key="animation.inspect_imported_pipeline",
        label="Inspect Imported Unreal Animation Pipeline",
        function="unreal_tools.animation.inspect_imported_animation_pipeline",
        required=("imported_paths",),
        optional={
            "target_skeleton_path": "",
            "target_skeletal_mesh_path": "",
        },
        description=(
            "Inspect imported animation timing, root motion, Skeleton ownership, "
            "and target compatibility."
        ),
    ),
    "animation.retarget_imported_if_needed": UnrealOperation(
        key="animation.retarget_imported_if_needed",
        label="Retarget Imported Unreal Animations When Needed",
        function="unreal_tools.animation.retarget_imported_animations_if_needed",
        required=("compatibility_report",),
        optional={
            "source_skeletal_mesh_path": "",
            "target_skeletal_mesh_path": "",
            "output_path": "/Game/Animations/Retargeted",
            "retargeter_path": "",
        },
        mutates_project=True,
        description=(
            "Preserve compatible AnimSequences and retarget only incompatible "
            "imports with structured readback."
        ),
    ),
    "animation.report_pipeline_assets": UnrealOperation(
        key="animation.report_pipeline_assets",
        label="Report Final Unreal Animation Pipeline Assets",
        function="unreal_tools.animation.report_animation_pipeline_assets",
        required=("imported_paths", "animation_paths"),
        optional={
            "target_skeleton_path": "",
            "target_anim_blueprint_path": "",
        },
        description=(
            "Report final imported and retargeted asset existence, save state, "
            "and Skeleton ownership."
        ),
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
    "sequencer.create_float_track": UnrealOperation(
        key="sequencer.create_float_track",
        label="Create Keyed Sequencer Float Track",
        function="unreal_tools.sequencer.create_float_track",
        required=("sequence_path", "track_name", "keys"),
        optional={"display_rate": 30, "replace_existing": True, "save": True},
        mutates_project=True,
        description="Create, key, save, and read back a master float track in a Level Sequence.",
    ),
    "sequencer.author_camera_cuts": UnrealOperation(
        key="sequencer.author_camera_cuts",
        label="Author Sequencer Camera Cuts",
        function="unreal_tools.sequencer.author_camera_cuts",
        required=("sequence_path", "cameras"),
        optional={"display_rate": 30, "replace_existing": False, "save": True},
        mutates_project=True,
        description=(
            "Author spawnable CineCameraActors, keyed transform tracks, non-overlapping "
            "camera cuts, playback range, save, and structural readback in a Level Sequence."
        ),
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
        optional={"is_array": False, "default_value": None, "save": True},
        mutates_project=True,
        description="Create a typed Blueprint variable with generated-class default-value readback.",
    ),
    "blueprint.connect_node_pins": UnrealOperation(
        key="blueprint.connect_node_pins",
        label="Unreal Connect Blueprint Node Pins",
        function="unreal_tools.blueprint.connect_node_pins",
        required=("blueprint_path", "graph_name", "source_node", "source_pin", "target_node", "target_pin"),
        mutates_project=True,
        description="Connect pin A of node X to pin B of node Y in a Blueprint graph (EventGraph or AnimGraph).",
    ),
    "blueprint.apply_graph_spec": UnrealOperation(
        key="blueprint.apply_graph_spec",
        label="Unreal Apply Approved Blueprint Graph Spec",
        function="unreal_tools.blueprint.apply_graph_spec",
        required=("blueprint_path", "graph_name", "graph_spec"),
        optional={"save": True},
        mutates_project=True,
        description="Apply an explicit node, pin-value, and link specification; reject incomplete or schema-invalid graph work.",
    ),
    "blueprint.describe_node_action": UnrealOperation(
        key="blueprint.describe_node_action",
        label="Unreal Describe Blueprint Node Action",
        function="unreal_tools.blueprint.describe_node_action",
        required=("blueprint_path", "graph_name", "palette_action"),
        description="Verify one exact context-filtered palette action and return its typed pins without modifying the Blueprint.",
    ),
    "blueprint.search_node_actions": UnrealOperation(
        key="blueprint.search_node_actions",
        label="Unreal Search Blueprint Node Actions",
        function="unreal_tools.blueprint.search_node_actions",
        required=("blueprint_path", "graph_name", "query"),
        optional={"max_results": 50},
        description="Search the live context-filtered Blueprint action database without modifying the Blueprint.",
    ),
    "blueprint.probe_node_action": UnrealOperation(
        key="blueprint.probe_node_action",
        label="Unreal Probe Blueprint Node Action",
        function="unreal_tools.blueprint.probe_node_action",
        required=("blueprint_path", "graph_name", "palette_action"),
        optional={"temp_folder": "/Game/AIStudio/Temp/NodeProbes"},
        mutates_project=True,
        description="Create and remove an action on a retained disposable Blueprint copy, verifying real pins, compile status, and reset state.",
    ),
    "blueprint.discover_action_candidates": UnrealOperation(
        key="blueprint.discover_action_candidates",
        label="Discover Blueprint Action Candidates",
        function="tech_connector.services.unreal.blueprint_action_discovery_service.discover_action_candidates",
        required=("blueprint_path", "graph_name", "semantic_operations"),
        optional={
            "max_results_per_query": 15,
            "use_reasoning": True,
            "reasoning_model": "qwen2.5-coder:7b",
        },
        execution_host="desktop",
        description="Search live context-filtered Blueprint actions for semantic operations without selecting nodes or mutating assets.",
    ),
    "blueprint.probe_selected_actions": UnrealOperation(
        key="blueprint.probe_selected_actions",
        label="Probe Selected Blueprint Actions",
        function="tech_connector.services.unreal.blueprint_action_discovery_service.probe_selected_actions",
        required=("blueprint_path", "graph_name", "selections"),
        optional={"approved": False, "temp_folder": "/Game/AIStudio/Temp/NodeProbes"},
        mutates_project=True,
        execution_host="desktop",
        description="After approval, recover real pins by adding and removing selected actions on a retained disposable Blueprint copy.",
    ),
    "blueprint.build_graph_spec_prompt": UnrealOperation(
        key="blueprint.build_graph_spec_prompt",
        label="Build Evidence-Bounded Blueprint Graph Prompt",
        function="tech_connector.services.unreal.blueprint_graph_spec_service.build_graph_spec_prompt",
        required=("semantic_operations", "available_actions"),
        execution_host="desktop",
        description="Prepare a model request containing only live-verified palette actions and exact pin signatures; does not mutate assets or claim success.",
    ),
    "blueprint.validate_graph_spec_evidence": UnrealOperation(
        key="blueprint.validate_graph_spec_evidence",
        label="Validate Blueprint Graph Spec Evidence",
        function="tech_connector.services.unreal.blueprint_graph_spec_service.validate_graph_spec_against_pin_evidence",
        required=("graph_spec",),
        execution_host="desktop",
        description="Fail closed on missing action evidence, invented pins, reversed directions, or incompatible pin types before Unreal mutation.",
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
        description="Set or toggle a Blueprint breakpoint through an explicit Unreal Editor UI handoff.",
        execution_mode="user_delegated",
        delegation={
            "surface": "Blueprint Editor > requested graph",
            "action": "Locate the requested node and set or clear its breakpoint to match the requested state.",
            "verification": "Confirm the node breakpoint marker and Debug panel state match the request.",
        },
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
    "blueprint.compile_and_save": UnrealOperation(
        key="blueprint.compile_and_save",
        label="Unreal Compile and Save Blueprint",
        function="unreal_tools.blueprint.compile_and_save_blueprint",
        required=("asset_path",),
        mutates_project=True,
        description="Compile a Blueprint and save it if compilation succeeds.",
    ),
}

UNREAL_OPERATIONS.update(
    {
        "niagara.attach_editable_character_fx": UnrealOperation(
            key="niagara.attach_editable_character_fx",
            label="Attach Editable Niagara Character FX",
            function="unreal_tools.niagara.attach_editable_character_fx",
            required=("blueprint_path",),
            optional={
                "source_system_path": "/Game/Variant_Platforming/VFX/NS_Jump_Trail",
                "system_path": "/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CharacterAura",
                "component_name": "AIStudio_AuraFX",
                "socket_name": "spine_03",
                "parameters": {},
                "extra_components": [],
                "native_binding_chunk_size": 2,
                "disable_native_graph_binding": False,
                "save": True,
            },
            mutates_project=True,
            description="Attach a reusable Niagara system to a character and expose editable Blueprint parameter bindings.",
        ),
        "animation.set_slot_animation": UnrealOperation(
            key="animation.set_slot_animation", label="Unreal Set Slot Animation",
            function="unreal_tools.animation.set_slot_animation",
            required=("anim_bp_path", "slot_name", "animation_path"), mutates_project=True,
            description="Assign an animation asset to an Animation Blueprint slot.",
        ),
        "motion_matching.add_state_animations": UnrealOperation(
            key="motion_matching.add_state_animations", label="Unreal Add Motion Matching State Animations",
            function="unreal_tools.motion_matching.add_state_animations",
            required=("database_path", "animation_paths", "state_tag"), mutates_project=True,
            description="Add state-tagged animations to a Pose Search Database.",
        ),
        "physics.create_physics_asset": UnrealOperation(
            key="physics.create_physics_asset", label="Unreal Create Physics Asset",
            function="unreal_tools.physics.create_physics_asset", required=("skeletal_mesh_path",),
            optional={"save_path": ""}, mutates_project=True,
            description="Create a PhysicsAsset for a SkeletalMesh.",
        ),
        "physics.add_body": UnrealOperation(
            key="physics.add_body", label="Unreal Add Physics Body",
            function="unreal_tools.physics.add_body", required=("physics_asset_path", "bone_name"),
            optional={"shape_type": "capsule"}, mutates_project=True,
            description="Add a physical body shape for a skeleton bone.",
        ),
        "physics.add_constraint": UnrealOperation(
            key="physics.add_constraint", label="Unreal Add Physics Constraint",
            function="unreal_tools.physics.add_constraint",
            required=("physics_asset_path", "bone_name_a", "bone_name_b"), mutates_project=True,
            description="Add a constraint between two PhysicsAsset bodies.",
        ),
        "physics.set_collision_profile": UnrealOperation(
            key="physics.set_collision_profile", label="Unreal Set Collision Profile",
            function="unreal_tools.physics.set_collision_profile", required=("actor_query", "profile_name"),
            optional={"component_name": ""}, mutates_project=True,
            description="Assign a collision profile to an actor component.",
        ),
        "navigation.add_nav_mesh_bounds": UnrealOperation(
            key="navigation.add_nav_mesh_bounds", label="Unreal Add Nav Mesh Bounds Volume",
            function="unreal_tools.navigation.add_nav_mesh_bounds",
            optional={"location": [0.0, 0.0, 0.0], "extent": [1000.0, 1000.0, 500.0]},
            mutates_project=True, description="Place a NavMeshBoundsVolume in the current level.",
        ),
        "gameplay.create_gameplay_ability": UnrealOperation(
            key="gameplay.create_gameplay_ability", label="Unreal Create Gameplay Ability",
            function="unreal_tools.gameplay.create_gameplay_ability", required=("ability_name",),
            optional={"save_path": ""}, mutates_project=True,
            description="Create a Gameplay Ability asset for an approved feature plan.",
        ),
    }
)

UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY: set[str] = set()


def build_unreal_editable_character_fx_params(text: str) -> dict[str, Any]:
    """Build niagara.attach_editable_character_fx params from a natural-language prompt."""
    q = (text or "").lower()

    # Determine target blueprint
    blueprint_path = "BP_ThirdPersonCharacter"
    for token in re.findall(r'\bBP_\w+', text):
        blueprint_path = token
        break

    # Determine socket
    socket_match = re.search(
        r'\b(spine_0[0-9]|hand_[lr]|pelvis|root|head|neck_0[0-9]|chest)\b', q
    )
    socket_name = socket_match.group(1) if socket_match else "spine_03"

    # Determine profile / component name and system path
    component_name = "AIStudio_AuraFX"
    system_path = "/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CharacterAura"
    profile = "default"

    if "silhouette" in q or "outline" in q or "camera" in q:
        component_name = "AIStudio_CameraSilhouetteOutlineFX"
        system_path = "/Game/AIStudio/Prototypes/Niagara/NS_AIStudio_CameraSilhouetteOutline"
        profile = "camera_silhouette_outline"

    # Base parameters
    params: dict[str, Any] = {
        "blueprint_path": blueprint_path,
        "component_name": component_name,
        "socket_name": socket_name,
        "system_path": system_path,
        "parameters": {
            "FX_Profile": profile,
            "FX_Color": [0.0, 0.85, 1.0, 1.0] if profile == "camera_silhouette_outline" else [0.2, 0.85, 1.0, 1.0],
            "FX_Intensity": 6.0,
            "FX_SpawnRate": 160.0,
            "FX_Radius": 72.0,
            "FX_Lifetime": 1.25,
            "FX_PulseSpeed": 2.5,
        },
    }

    # Source mode for camera-facing profiles
    if profile == "camera_silhouette_outline":
        params["parameters"]["FX_SourceMode"] = "camera_facing_character_outline"
        params["parameters"]["FX_EdgeThickness"] = 2.0
        params["parameters"]["FX_CameraFade"] = 0.85

    # Optional tunable expansion based on prompt keywords
    if "color" in q:
        params["parameters"].setdefault("FX_SecondaryColor", [0.75, 0.15, 1.0, 1.0])
    if "spawn" in q or "rate" in q:
        params["parameters"].setdefault("FX_SpawnRate", 160.0)
    if "lifetime" in q:
        params["parameters"].setdefault("FX_Lifetime", 1.25)
    if "radius" in q:
        params["parameters"].setdefault("FX_Radius", 72.0)
    if "pulse" in q:
        params["parameters"].setdefault("FX_PulseSpeed", 2.5)
    if "velocity" in q:
        params["parameters"].setdefault("FX_Velocity", [0.0, 0.0, 100.0])
    if "noise" in q:
        params["parameters"].setdefault("FX_NoiseStrength", 1.0)
    if "offset" in q:
        params["parameters"].setdefault("FX_AttachOffset", [0.0, 0.0, 0.0])
    if "auto activate" in q or "auto_activate" in q:
        params["parameters"].setdefault("FX_AutoActivate", True)

    return params


def operation_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": op.key,
            "label": op.label,
            "function": op.function,
            "required": list(op.required),
            "optional": op.optional,
            "mutates_project": op.mutates_project,
            "execution_host": op.execution_host,
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
        "execution_host": op.execution_host,
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
    """
        Extracts Unreal content paths from game and plugin mount points.
    :param text: natural-language request
    :return: unique Unreal content paths in prompt order
    """
    paths = []
    for match in re.finditer(r"(/(?:Game|[A-Za-z][A-Za-z0-9_]*)/[A-Za-z0-9_/.-]*)", text or ""):
        path = match.group(1).rstrip(".,;:)")
        if path and path not in paths:
            paths.append(path)
    return paths


def _select_unreal_asset_path(paths, prefixes=()):
    """
        Selects a content path by conventional asset-name prefix.
    :param paths: candidate Unreal content paths
    :param prefixes: accepted basename prefixes
    :return: selected content path or an empty string
    """
    normalized = tuple(str(prefix).casefold() for prefix in prefixes)
    for path in paths:
        name = str(path).rsplit("/", 1)[-1].casefold()
        if any(name.startswith(prefix) for prefix in normalized):
            return str(path)
    return str(paths[0]) if paths else ""


def _extract_blackboard_key_specs(text: str) -> list[dict[str, Any]]:
    """
        Extracts explicit Blackboard key-name and type pairs.
    :param text: natural-language Unreal request
    :return: ordered unique key specifications
    """
    aliases = {
        "boolean": "bool",
        "integer": "int",
    }
    types = "bool|boolean|class|enum|float|int|integer|name|object|rotator|string|vector"
    pairs = []
    patterns = (
        rf"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:(?::|=|\bis\b)\s*|\s+)({types})\b",
        rf"\b({types})\s+(?:key\s+)?(?:named\s+)?([A-Za-z_][A-Za-z0-9_]*)\b",
    )
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            if pattern_index == 0:
                name, key_type = match.group(1), match.group(2)
            else:
                key_type, name = match.group(1), match.group(2)
            key_type = aliases.get(key_type.casefold(), key_type.casefold())
            if name.casefold() in {"key", "keys", "blackboard", "schema", "type", "typed"}:
                continue
            pairs.append({"name": name, "type": key_type})
    result = []
    seen = set()
    for row in pairs:
        marker = row["name"].casefold()
        if marker not in seen:
            seen.add(marker)
            result.append(row)
    return result


def _extract_sequencer_key_specs(text: str) -> list[dict[str, Any]]:
    """
        Extracts explicit Sequencer frame and value pairs.
    :param text: natural-language Unreal request
    :return: sorted key specifications
    """
    rows = []
    for match in re.finditer(
        r"\b(?:frame\s*)?(\d+)\s*(?::|=|(?:(?:has|with|to)\s+)?value\s+)(-?\d+(?:\.\d+)?)\b",
        text or "",
        re.IGNORECASE,
    ):
        rows.append({"frame": int(match.group(1)), "value": float(match.group(2))})
    unique = {row["frame"]: row for row in rows}
    return [unique[frame] for frame in sorted(unique)]


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
    mounted_content_path = bool(
        re.match(r"^/[A-Za-z][A-Za-z0-9_]*/[^/]+", p)
    )
    if not mounted_content_path and not any(
        lower.startswith(root) for root in ("/game", "/engine", "/script", "/plugin")
    ):
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
    create_request = bool(re.search(r"\b(?:create|make|build|generate|new|set up|setup)\b", q))
    inspect_request = bool(re.search(r"\b(?:inspect|scan|analy[sz]e|describe|show)\b", q))
    author_request = create_request or bool(
        re.search(r"\b(?:add|author|populate|configure|connect|wire|key)\b", q)
    )
    if re.search(r"\bsound\s+cue\b", q):
        if create_request:
            return "sound_cue.create_from_wave"
        if inspect_request:
            return "sound_cue.inspect"
    if re.search(r"\bdata\s+table\b", q):
        if create_request:
            return "data_table.create_from_rows"
        if inspect_request:
            return "data_table.inspect"
    if re.search(r"\b(?:outliner|level actors?|actors?)\b", q) and re.search(
        r"\b(?:organize|folder|folders|categorize|rename|tag|hide)\b", q
    ):
        return "level.organize_actors"
    if re.search(r"\b(?:material|shader)\b", q):
        if create_request and re.search(
            r"\b(?:graph spec|node spec|json spec|specification|post[ -]?process)\b", q
        ):
            return "material.create_from_spec"
        if create_request and re.search(r"\b(?:pbr|parameter|roughness|metallic|base color)\b", q):
            return "material.create_parameterized_pbr"
        if create_request:
            return "material.create"
        if inspect_request:
            return "material.inspect"
    if re.search(r"\b(?:pcg graph|procedural content generation graph)\b", q):
        if author_request and re.search(r"\b(?:graph spec|specification|node spec|json spec)\b", q):
            return "pcg.apply_graph_spec"
        if author_request and re.search(r"\b(?:grid|points?|transform|offset|cell)\b", q):
            return "pcg.create_grid_transform_graph"
        if inspect_request:
            return "pcg.inspect_graph"
    if re.search(r"\bmeta\s?sound(?: source)?\b", q):
        if author_request and re.search(r"\b(?:graph spec|specification|node spec|json spec)\b", q):
            return "metasound.create_source_from_spec"
        if author_request and re.search(r"\b(?:sine|tone|oscillat(?:or|e)|frequency|hz)\b", q):
            return "metasound.create_sine_tone_source"
    # Behavior Tree prompts commonly contain "blackboard key". Resolve the
    # enclosing asset domain first so that phrase cannot steal a task-graph
    # request and incorrectly route it to Blackboard schema authoring.
    if re.search(r"\bbehavio(?:u)?r tree\b", q):
        if author_request and re.search(
            r"\b(?:moves? to|moveto|task spec|mixed tasks?|patrol|chase|navigate)\b", q
        ):
            return "behavior_tree.author_task_graph"
        if author_request and re.search(r"\b(?:sequence|wait tasks?|waits)\b", q):
            return "behavior_tree.author_wait_graph"
        if author_request and re.search(r"\b(?:root|selector|wait|baseline|blackboard|topology|graph)\b", q):
            return "behavior_tree.author_baseline"
    if re.search(r"\bblackboard(?: data| asset)?\b", q):
        if author_request and re.search(r"\b(?:schema|keys?|bool|float|vector|rotator|string|object)\b", q):
            return "blackboard.set_schema"
        if inspect_request and re.search(r"\b(?:schema|keys?|types?)\b", q):
            return "blackboard.inspect_schema"
    if re.search(r"\b(?:widget blueprint|umg|user widget)\b", q):
        if author_request and re.search(r"\b(?:hierarchy spec|widget spec|json spec|specification)\b", q):
            return "widget.author_from_spec"
        if author_request and re.search(r"\b(?:canvas|text|label|title|design tree|hierarchy)\b", q):
            return "widget.author_canvas_text"
    if re.search(r"\b(?:level sequence|sequencer asset|cinematic sequence|sequencer)\b", q):
        if author_request and re.search(r"\b(?:camera cuts?|cinematic cameras?|shot cameras?)\b", q):
            return "sequencer.author_camera_cuts"
        if author_request and re.search(r"\b(?:float track|float channel|keys?|keyframes?)\b", q):
            return "sequencer.create_float_track"
    domain_asset_terms = (
        ("widget_blueprint", r"\b(?:widget blueprint|umg|user widget)\b"),
        ("pcg_graph", r"\b(?:pcg graph|procedural content generation graph)\b"),
        ("behavior_tree", r"\bbehavio(?:u)?r tree\b"),
        ("blackboard", r"\bblackboard(?: data| asset)?\b"),
        ("level_sequence", r"\b(?:level sequence|sequencer asset|cinematic sequence)\b"),
        ("metasound_source", r"\bmeta\s?sound(?: source)?\b"),
    )
    if any(re.search(pattern, q) for _, pattern in domain_asset_terms):
        if create_request:
            return "domain_asset.create"
        if inspect_request:
            return "domain_asset.inspect"
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
    character_fx_request = bool(
        re.search(r"\b(?:niagara|niagra|vfx|particle)\b", q)
        and re.search(r"\b(?:character|mesh|blueprint|bp_[a-z0-9_]+)\b", q)
        and re.search(
            r"\b(?:attach|component|editable|tunable|user parameter|aura|outline|silhouette|bone|socket)\w*\b",
            q,
        )
    )
    if character_fx_request:
        return "niagara.attach_editable_character_fx"
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

    if operation == "niagara.attach_editable_character_fx":
        steps.extend(
            [
                "Duplicate or reuse Niagara System assets without modifying the source template.",
                "Attach the Niagara component to the validated character component, bone, or socket.",
                "Create editable Blueprint variables for every requested Niagara user parameter.",
                "Bind supported Blueprint variables into Niagara user parameters and verify readback.",
            ]
        )
        if str((params.get("parameters") or {}).get("FX_SourceMode") or "") == "camera_facing_character_outline":
            steps.append("Synthesize and validate the camera-facing silhouette/outline source strategy before emission.")
        if re.search(r"\b(?:play mode|play in editor|pie)\b", raw_text, re.I):
            steps.append("Run Play In Editor and capture source, attachment, parameter, and visible-state readback evidence.")
    elif operation == "niagara.create_emitter":
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
    bounded_domain_authoring = {
        "behavior_tree.author_baseline",
        "behavior_tree.author_wait_graph",
        "blackboard.set_schema",
        "metasound.create_sine_tone_source",
        "metasound.create_source_from_spec",
        "pcg.create_grid_transform_graph",
        "pcg.apply_graph_spec",
        "sequencer.create_float_track",
        "sequencer.author_camera_cuts",
        "material.create_from_spec",
        "sound_cue.create_from_wave",
        "data_table.create_from_rows",
        "level.organize_actors",
        "widget.author_canvas_text",
        "widget.author_from_spec",
    }
    if resolved_op_key in bounded_domain_authoring:
        semantic_graph_required = False
    
    if resolved_op_key and resolved_op_key in UNREAL_OPERATIONS:
        op = UNREAL_OPERATIONS[resolved_op_key]
        operation = resolved_op_key
        mutating = op.mutates_project or action == "create" or high_risk_graph_rewrite
        
        if operation == "project.debug":
            params = build_unreal_debug_params(raw_text)
        elif operation == "niagara.attach_editable_character_fx":
            params = build_unreal_editable_character_fx_params(raw_text)
            target_assets.extend(
                str(params.get(key) or "")
                for key in ("blueprint_path", "system_path")
                if params.get(key)
            )
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
        elif operation == "pcg.create_grid_transform_graph":
            graph_path = _select_unreal_asset_path(target_assets, ("pcg_",))
            params = {"graph_path": graph_path} if graph_path else {}
        elif operation == "pcg.inspect_graph":
            graph_path = _select_unreal_asset_path(target_assets, ("pcg_",))
            params = {"graph_path": graph_path} if graph_path else {}
        elif operation == "pcg.apply_graph_spec":
            graph_path = _select_unreal_asset_path(target_assets, ("pcg_",))
            params = {"graph_path": graph_path} if graph_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("graph_spec", specification)
                    if isinstance(specification, dict):
                        if isinstance(specification.get("nodes"), list):
                            params["nodes"] = specification["nodes"]
                        if isinstance(specification.get("edges"), list):
                            params["edges"] = specification["edges"]
        elif operation == "metasound.create_sine_tone_source":
            asset_path = _select_unreal_asset_path(target_assets, ("ms_", "metasound_"))
            params = {"asset_path": asset_path} if asset_path else {}
            frequency_match = re.search(
                r"\b(\d+(?:\.\d+)?)\s*(?:hz|hertz)\b",
                raw_text,
                re.IGNORECASE,
            )
            if frequency_match:
                params["frequency"] = float(frequency_match.group(1))
        elif operation == "metasound.create_source_from_spec":
            asset_path = _select_unreal_asset_path(target_assets, ("ms_", "metasound_"))
            params = {"asset_path": asset_path} if asset_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("graph_spec", specification)
                    if isinstance(specification, dict):
                        if isinstance(specification.get("nodes"), list):
                            params["nodes"] = specification["nodes"]
                        if isinstance(specification.get("connections"), list):
                            params["connections"] = specification["connections"]
        elif operation in {"blackboard.set_schema", "blackboard.inspect_schema"}:
            asset_path = _select_unreal_asset_path(target_assets, ("bb_",))
            params = {"asset_path": asset_path} if asset_path else {}
            if operation == "blackboard.set_schema":
                keys = _extract_blackboard_key_specs(raw_text)
                if keys:
                    params["keys"] = keys
        elif operation == "widget.author_canvas_text":
            widget_path = _select_unreal_asset_path(target_assets, ("wbp_",))
            params = {"widget_blueprint_path": widget_path} if widget_path else {}
            text_match = re.search(
                r"\b(?:text|label|title)\s+(?:to\s+)?[\"']([^\"']+)[\"']",
                raw_text,
                re.IGNORECASE,
            )
            if text_match:
                params["text"] = text_match.group(1)
        elif operation == "widget.author_from_spec":
            widget_path = _select_unreal_asset_path(target_assets, ("wbp_",))
            params = {"widget_blueprint_path": widget_path} if widget_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("widget_spec", specification)
                    if isinstance(specification, dict) and isinstance(
                        specification.get("widgets"), list
                    ):
                        params["widgets"] = specification["widgets"]
        elif operation == "behavior_tree.author_baseline":
            tree_path = _select_unreal_asset_path(target_assets, ("bt_",))
            blackboard_path = _select_unreal_asset_path(target_assets, ("bb_",))
            params = {"behavior_tree_path": tree_path} if tree_path else {}
            if blackboard_path and blackboard_path != tree_path:
                params["blackboard_path"] = blackboard_path
            wait_match = re.search(
                r"\bwait(?:\s+(?:for|time))?\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?\b",
                raw_text,
                re.IGNORECASE,
            )
            if wait_match:
                params["wait_seconds"] = float(wait_match.group(1))
        elif operation == "behavior_tree.author_wait_graph":
            tree_path = _select_unreal_asset_path(target_assets, ("bt_",))
            blackboard_path = _select_unreal_asset_path(target_assets, ("bb_",))
            params = {"behavior_tree_path": tree_path} if tree_path else {}
            params["composite_type"] = "sequence" if "sequence" in lower else "selector"
            if blackboard_path and blackboard_path != tree_path:
                params["blackboard_path"] = blackboard_path
            waits_match = re.search(
                r"\b(?:wait\s+tasks?|waits)\s+([0-9.,\s]+(?:and\s+)?[0-9.]+)",
                raw_text,
                re.IGNORECASE,
            )
            if waits_match:
                params["wait_seconds"] = [
                    float(value)
                    for value in re.findall(r"\d+(?:\.\d+)?", waits_match.group(1))
                ]
            else:
                wait_values = re.findall(
                    r"\bwait(?:\s+(?:for|time))?\s+(\d+(?:\.\d+)?)",
                    raw_text,
                    re.IGNORECASE,
                )
                if wait_values:
                    params["wait_seconds"] = [float(value) for value in wait_values]
        elif operation == "behavior_tree.author_task_graph":
            tree_path = _select_unreal_asset_path(target_assets, ("bt_",))
            blackboard_path = _select_unreal_asset_path(target_assets, ("bb_",))
            params = {"behavior_tree_path": tree_path} if tree_path else {}
            if blackboard_path and blackboard_path != tree_path:
                params["blackboard_path"] = blackboard_path
            elif tree_path:
                tree_folder, _, tree_name = tree_path.rpartition("/")
                blackboard_name = re.sub(
                    r"^BT_",
                    "BB_",
                    tree_name,
                    count=1,
                    flags=re.IGNORECASE,
                )
                if blackboard_name == tree_name:
                    blackboard_name = f"BB_{tree_name}"
                params["blackboard_path"] = (
                    f"{tree_folder}/{blackboard_name}"
                    if tree_folder
                    else f"/Game/{blackboard_name}"
                )
            params["composite_type"] = "selector" if "selector" in lower else "sequence"
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("behavior_tree_spec", specification)
                    if isinstance(specification, dict):
                        if isinstance(specification.get("tasks"), list):
                            params["tasks"] = specification["tasks"]
                        if specification.get("composite_type"):
                            params["composite_type"] = str(specification["composite_type"])
            if "tasks" not in params:
                task_matches = []
                for match in re.finditer(
                    r"\bmove\s*to\s+(?:(?:the\s+)?blackboard\s+key\s+)?([A-Za-z_][A-Za-z0-9_]*)"
                    r"|\bwait(?:\s+(?:for|time))?\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?",
                    raw_text,
                    re.IGNORECASE,
                ):
                    if match.group(1):
                        task_matches.append({"type": "move_to", "blackboard_key": match.group(1)})
                    else:
                        task_matches.append({"type": "wait", "seconds": float(match.group(2))})
                if task_matches:
                    params["tasks"] = task_matches
            if "tasks" not in params:
                task_matches = []
                for match in re.finditer(
                    r"\bmoves?\s*to\s+(?:(?:the\s+)?blackboard\s+key\s+)?([A-Za-z_][A-Za-z0-9_]*)"
                    r"|\bwaits?(?:\s+(?:for|time))?\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?",
                    raw_text,
                    re.IGNORECASE,
                ):
                    if match.group(1):
                        task_matches.append({"type": "move_to", "blackboard_key": match.group(1)})
                    else:
                        task_matches.append({"type": "wait", "seconds": float(match.group(2))})
                if task_matches:
                    params["tasks"] = task_matches
        elif operation == "sequencer.create_float_track":
            sequence_path = _select_unreal_asset_path(target_assets, ("ls_",))
            params = {"sequence_path": sequence_path} if sequence_path else {}
            track_match = re.search(
                r"\b(?:float\s+track|track)\s+(?:named\s+)?(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z_][A-Za-z0-9_-]*))",
                raw_text,
                re.IGNORECASE,
            )
            if track_match:
                params["track_name"] = next(
                    group.strip() for group in track_match.groups() if group
                )
            keys = _extract_sequencer_key_specs(raw_text)
            if keys:
                params["keys"] = keys
        elif operation == "sequencer.author_camera_cuts":
            sequence_path = _select_unreal_asset_path(target_assets, ("ls_",))
            params = {"sequence_path": sequence_path} if sequence_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("camera_cut_spec", specification)
                    if isinstance(specification, dict):
                        if isinstance(specification.get("cameras"), list):
                            params["cameras"] = specification["cameras"]
                        if "display_rate" in specification:
                            params["display_rate"] = specification["display_rate"]
                        if "replace_existing" in specification:
                            params["replace_existing"] = bool(specification["replace_existing"])
            if "cameras" not in params:
                between_match = re.search(
                    r"\bbetween\s+([A-Za-z_][A-Za-z0-9_]*)\s+and\s+([A-Za-z_][A-Za-z0-9_]*)",
                    raw_text,
                    re.IGNORECASE,
                )
                camera_names = list(between_match.groups()) if between_match else []
                frame_match = re.search(
                    r"\b(?:at|starting at|on)\s+frames?\s+([0-9,\s]+(?:and\s+[0-9]+)?)",
                    raw_text,
                    re.IGNORECASE,
                )
                frames = [int(value) for value in re.findall(r"\d+", frame_match.group(1))] if frame_match else []
                if camera_names and len(frames) >= len(camera_names):
                    positive_deltas = [b - a for a, b in zip(frames, frames[1:]) if b > a]
                    fallback_duration = positive_deltas[-1] if positive_deltas else 30
                    params["cameras"] = [
                        {
                            "name": name,
                            "start_frame": frames[index],
                            "end_frame": frames[index + 1] if index + 1 < len(frames) else frames[index] + fallback_duration,
                        }
                        for index, name in enumerate(camera_names)
                    ]
            if "cameras" not in params:
                count_match = re.search(
                    r"\b(\d+|one|two|three|four|five|six|seven|eight)\s+"
                    r"(?:cinematic\s+|shot\s+)?cameras?\b",
                    raw_text,
                    re.IGNORECASE,
                )
                if count_match:
                    count_words = {
                        "one": 1,
                        "two": 2,
                        "three": 3,
                        "four": 4,
                        "five": 5,
                        "six": 6,
                        "seven": 7,
                        "eight": 8,
                    }
                    raw_count = count_match.group(1).casefold()
                    camera_count = int(raw_count) if raw_count.isdigit() else count_words[raw_count]
                    camera_count = max(1, min(camera_count, 8))
                    shot_length = 30
                    params["cameras"] = [
                        {
                            "name": f"Camera_{index + 1:02d}",
                            "start_frame": index * shot_length,
                            "end_frame": (index + 1) * shot_length,
                            "location": [float(index * 300), -600.0, 180.0],
                            "rotation": [0.0, -10.0, 0.0],
                        }
                        for index in range(camera_count)
                    ]
        elif operation == "level.organize_actors":
            params = {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("outliner_spec", specification)
                    if isinstance(specification, dict):
                        if isinstance(specification.get("actors"), list):
                            params["actor_specs"] = specification["actors"]
                        if "save" in specification:
                            params["save"] = bool(specification["save"])
            if "actor_specs" not in params:
                actor_match = re.search(
                    r"\b(?:organize|actors?)\s+(?:actors?\s+)?(.+?)\s+into\s+(?:the\s+)?folder\s+([A-Za-z0-9_./-]+)",
                    raw_text,
                    re.IGNORECASE,
                )
                if actor_match:
                    actor_text, folder = actor_match.groups()
                    actor_names = [
                        value.strip(" \t\"'")
                        for value in re.split(r"\s*,\s*|\s+and\s+", actor_text)
                        if value.strip(" \t\"'")
                    ]
                    tag_match = re.search(
                        r"\btag\s+(?:them\s+)?(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*)",
                        raw_text,
                        re.IGNORECASE,
                    )
                    hidden_match = re.search(
                        r"\bhide\s+([A-Za-z_][A-Za-z0-9_]*)",
                        raw_text,
                        re.IGNORECASE,
                    )
                    hidden_name = hidden_match.group(1).casefold() if hidden_match else ""
                    params["actor_specs"] = [
                        {
                            "query": name,
                            "folder": folder,
                            **({"add_tags": [tag_match.group(1)]} if tag_match else {}),
                            **({"hidden": True} if name.casefold() == hidden_name else {}),
                        }
                        for name in actor_names
                    ]
        elif operation == "domain_asset.create":
            domain_patterns = (
                ("widget_blueprint", r"\b(?:widget blueprint|umg|user widget)\b"),
                ("pcg_graph", r"\b(?:pcg graph|procedural content generation graph)\b"),
                ("behavior_tree", r"\bbehavio(?:u)?r tree\b"),
                ("blackboard", r"\bblackboard(?: data| asset)?\b"),
                ("level_sequence", r"\b(?:level sequence|sequencer asset|cinematic sequence)\b"),
                ("metasound_source", r"\bmeta\s?sound(?: source)?\b"),
            )
            asset_type = next(
                (key for key, pattern in domain_patterns if re.search(pattern, lower)),
                "",
            )
            params = {"asset_type": asset_type}
            if target_assets:
                params["asset_path"] = target_assets[0]
            if params.get("asset_path"):
                target_assets.append(params["asset_path"])
        elif operation == "domain_asset.inspect":
            params = {"expected_type": ""}
            if target_assets:
                params["asset_path"] = target_assets[0]
        elif operation == "material.create_from_spec":
            params = {"asset_path": target_assets[0]} if target_assets else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("material_spec", specification)
                    if isinstance(specification, dict):
                        for key in (
                            "nodes", "connections", "outputs", "material_domain",
                            "material_properties", "overwrite",
                        ):
                            if key in specification:
                                params[key] = specification[key]
            if "nodes" not in params and "post" in lower and "scene" in lower and "texture" in lower:
                color_values = {
                    "red": [1.0, 0.0, 0.0, 1.0], "green": [0.0, 1.0, 0.0, 1.0],
                    "blue": [0.0, 0.0, 1.0, 1.0], "cyan": [0.0, 1.0, 1.0, 1.0],
                    "magenta": [1.0, 0.0, 1.0, 1.0], "yellow": [1.0, 1.0, 0.0, 1.0],
                    "white": [1.0, 1.0, 1.0, 1.0], "black": [0.0, 0.0, 0.0, 1.0],
                }
                tint = color_values.get(extract_requested_color(raw_text), [0.0, 1.0, 0.0, 1.0])
                params.update({
                    "material_domain": "MD_POST_PROCESS",
                    "nodes": [
                        {"id": "scene", "class": "MaterialExpressionSceneTexture", "properties": {"scene_texture_id": "PPI_POST_PROCESS_INPUT0"}},
                        {"id": "tint", "class": "MaterialExpressionVectorParameter", "properties": {"parameter_name": "Tint", "default_value": tint}},
                        {"id": "multiply", "class": "MaterialExpressionMultiply"},
                    ],
                    "connections": [
                        {"source": "scene", "target": "multiply", "target_input": "A"},
                        {"source": "tint", "target": "multiply", "target_input": "B"},
                    ],
                    "outputs": [{"source": "multiply", "material_property": "MP_EMISSIVE_COLOR"}],
                })
        elif operation == "sound_cue.create_from_wave":
            cue_path = _select_unreal_asset_path(target_assets, ("sc_", "soundcue_"))
            params = {"asset_path": cue_path} if cue_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("sound_cue_spec", specification)
                    if isinstance(specification, dict):
                        for key in (
                            "asset_path", "sound_wave_path", "looping",
                            "volume_multiplier", "pitch_multiplier", "overwrite",
                        ):
                            if key in specification:
                                params[key] = specification[key]
            if "sound_wave_path" not in params:
                wave_path = next((path for path in target_assets if path != cue_path), "")
                if wave_path:
                    params["sound_wave_path"] = wave_path
            if "modulator" in lower and "processors" not in params:
                params["processors"] = [{"class": "SoundNodeModulator"}]
            params["looping"] = bool(re.search(r"\bloop(?:ing|ed)?\b", lower))
            for key, pattern in (
                ("volume_multiplier", r"\bvolume(?:\s+multiplier)?\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)"),
                ("pitch_multiplier", r"\bpitch(?:\s+multiplier)?\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)"),
            ):
                scalar_match = re.search(pattern, raw_text, re.IGNORECASE)
                if scalar_match:
                    params[key] = float(scalar_match.group(1))
        elif operation == "sound_cue.inspect":
            cue_path = _select_unreal_asset_path(target_assets, ("sc_", "soundcue_"))
            params = {"asset_path": cue_path} if cue_path else {}
        elif operation == "data_table.create_from_rows":
            table_path = _select_unreal_asset_path(target_assets, ("dt_",))
            params = {"asset_path": table_path} if table_path else {}
            json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
            if json_match:
                try:
                    specification = json.loads(json_match.group(1))
                except (TypeError, ValueError):
                    specification = {}
                if isinstance(specification, dict):
                    specification = specification.get("data_table_spec", specification)
                    if isinstance(specification, dict):
                        for key in ("asset_path", "row_struct_path", "rows", "overwrite"):
                            if key in specification:
                                params[key] = specification[key]
                        if (
                            "rows" not in params
                            and re.search(r"\brows?\s*\{", raw_text, re.IGNORECASE)
                            and not any(
                                key in specification
                                for key in (
                                    "asset_path",
                                    "row_struct_path",
                                    "overwrite",
                                )
                            )
                        ):
                            params["rows"] = specification
            if "row_struct_path" not in params:
                struct_path = next((path for path in target_assets if path != table_path), "")
                if struct_path:
                    params["row_struct_path"] = struct_path
            if "rows" not in params:
                rows_match = re.search(r"\brows?\s+(.+?)(?:\s+with\s+|[.;]|$)", raw_text, re.IGNORECASE)
                if rows_match:
                    row_names = [
                        value.strip(" \t\"'")
                        for value in re.split(r"\s*,\s*|\s+and\s+", rows_match.group(1))
                        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value.strip(" \t\"'"))
                    ]
                    if row_names:
                        params["rows"] = [{"Name": name} for name in row_names]
        elif operation == "data_table.inspect":
            table_path = _select_unreal_asset_path(target_assets, ("dt_",))
            params = {"asset_path": table_path} if table_path else {}
        elif operation in {"material.create", "material.create_parameterized_pbr", "material.inspect"}:
            params = {}
            if target_assets:
                params["asset_path"] = target_assets[0]
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

    for p_key in (
        "asset_path",
        "target_path",
        "blueprint_path",
        "graph_path",
        "sequence_path",
        "widget_blueprint_path",
        "behavior_tree_path",
        "blackboard_path",
    ):
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
    capability_gaps: list[dict[str, Any]] = []
    selected_operation = UNREAL_OPERATIONS.get(operation)
    non_empty_required = {"keys", "nodes", "wait_seconds", "widgets"}
    missing_required = [
        name
        for name in (selected_operation.required if selected_operation else ())
        if name not in params
        or params[name] in (None, "")
        or (name in non_empty_required and not params[name])
    ]
    if missing_required:
        capability_gaps.append(
            {
                "required_capability": "request.required_parameters",
                "reason": "The prompt did not provide all parameters required for safe execution.",
                "missing_parameters": missing_required,
            }
        )
    if operation == "niagara.attach_editable_character_fx" and str(
        (params.get("parameters") or {}).get("FX_SourceMode") or ""
    ) == "camera_facing_character_outline":
        capability_gaps.append(
            {
                "required_capability": "niagara.synthesize_source_strategy_stack",
                "request_fragment": raw_text,
                "source_strategy": "camera_facing_character_outline",
                "reason": "The generic attachment callable does not synthesize a camera-visible silhouette emission stack.",
            }
        )
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
        "complete": not capability_gaps,
        "capability_gaps": capability_gaps,
    
    # ── Traversal, Gameplay, Navigation & Physics Additions ──
    }


def explain_unreal_execution_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, default=str)
