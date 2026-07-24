from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from typing import Any, Dict, Iterable, List, Literal, Optional

CapabilityMode = Literal["context_call", "operation", "function", "python"]
CapabilityRisk = Literal["read_only", "low", "medium", "high"]
CapabilityPhase = Literal["inspect", "mutate", "validate"]


@dataclass(frozen=True)
class CapabilityArgument:
    name: str
    kind: str
    required: bool = True
    cardinality: str = "one"
    aliases: tuple[str, ...] = ()
    default: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnrealCapabilitySpec:
    name: str
    domain: str
    phase: CapabilityPhase
    mode: CapabilityMode

    description: str = ""
    context_call: str = ""
    operation: str = ""
    function: str = ""

    read_only: bool = True
    risk: CapabilityRisk = "read_only"
    timeout: float = 5.0

    expects: tuple[CapabilityArgument, ...] = ()
    produces: tuple[str, ...] = ()

    preflight: tuple[str, ...] = ()
    validate: tuple[str, ...] = ()
    rollback: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()

    requires_live_unreal: bool = True
    requires_selection: bool = False
    requires_project: bool = True
    requires_asset_types: tuple[str, ...] = ()
    supports_dry_run: bool = False
    supports_batch: bool = False

    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    fallback_capabilities: tuple[str, ...] = ()

    recommended_model: str = "fast_context"
    enabled: bool = True
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expects"] = [item.to_dict() for item in self.expects]
        return data


def _arg(
    name: str,
    kind: str,
    *,
    required: bool = True,
    cardinality: str = "one",
    aliases: tuple[str, ...] = (),
    default: Any = None,
    description: str = "",
) -> CapabilityArgument:
    return CapabilityArgument(
        name=name,
        kind=kind,
        required=required,
        cardinality=cardinality,
        aliases=aliases,
        default=default,
        description=description,
    )


UNREAL_CAPABILITIES: dict[str, UnrealCapabilitySpec] = {}


def register_capability(spec: UnrealCapabilitySpec) -> None:
    if not spec.name:
        raise ValueError("Capability name cannot be empty")
    if spec.name in UNREAL_CAPABILITIES:
        raise ValueError(f"Duplicate Unreal capability: {spec.name}")
    if spec.mode == "context_call" and not spec.context_call:
        raise ValueError(f"{spec.name} uses context_call mode without context_call")
    if spec.mode == "operation" and not spec.operation:
        raise ValueError(f"{spec.name} uses operation mode without operation")
    if spec.mode == "function" and not spec.function:
        raise ValueError(f"{spec.name} uses function mode without function")
    UNREAL_CAPABILITIES[spec.name] = spec


def _register_many(specs: Iterable[UnrealCapabilitySpec]) -> None:
    for spec in specs:
        register_capability(spec)


_register_many(
    [
        UnrealCapabilitySpec(
            name="selection.current",
            domain="selection",
            phase="inspect",
            mode="context_call",
            context_call="unreal.selection.current",
            description="Return selected Unreal assets and actors as serializable handles.",
            produces=("selected_asset_handles", "selected_actor_handles"),
            timeout=2.0,
            tags=("selection", "editor", "context"),
        ),
        UnrealCapabilitySpec(
            name="actor.resolve",
            domain="selection",
            phase="inspect",
            mode="context_call",
            context_call="unreal.actor.resolve",
            description="Resolve actor text into a verified actor handle.",
            expects=(
                _arg(
                    "query",
                    "actor_name_label_path_tag_or_asset",
                    aliases=("actor", "target"),
                ),
            ),
            produces=("actor_handle",),
            timeout=5.0,
            tags=("actor", "resolver"),
        ),
        UnrealCapabilitySpec(
            name="asset.resolve",
            domain="asset",
            phase="inspect",
            mode="context_call",
            context_call="unreal.asset.resolve",
            description="Resolve an Unreal asset name or path into a verified asset handle.",
            expects=(
                _arg(
                    "query",
                    "asset_name_or_path",
                    aliases=("asset", "path", "file_name"),
                ),
                _arg(
                    "expected_class",
                    "unreal_class_name",
                    required=False,
                    default="",
                ),
            ),
            produces=("asset_handle",),
            timeout=5.0,
            tags=("asset", "resolver"),
        ),
        UnrealCapabilitySpec(
            name="selection.select_actors",
            domain="selection",
            phase="mutate",
            mode="context_call",
            context_call="unreal.selection.select_actors",
            description="Resolve one or more actor queries and select matching actors.",
            read_only=False,
            risk="low",
            expects=(
                _arg(
                    "query",
                    "actor_name_label_path_tag_or_asset",
                    cardinality="many",
                    aliases=("actors", "targets"),
                ),
            ),
            produces=("selected_actor_handles",),
            preflight=("editor.state", "actor.resolve"),
            validate=("selection.current",),
            rollback=("selection.restore_previous",),
            permissions=("editor_selection",),
            supports_batch=True,
            tags=("selection", "actor", "mutation"),
        ),
        UnrealCapabilitySpec(
            name="level.current",
            domain="selection",
            phase="inspect",
            mode="context_call",
            context_call="unreal.level.current",
            description="Return current editor world and selected actor context.",
            produces=("level_handle", "selected_actor_handles"),
            timeout=2.0,
            tags=("level", "editor", "context"),
        ),
        UnrealCapabilitySpec(
            name="editor.state",
            domain="selection",
            phase="inspect",
            mode="context_call",
            context_call="unreal.editor.state",
            description="Return engine version, project, level, and selection state.",
            produces=("editor_state",),
            timeout=3.0,
            tags=("editor", "project", "context"),
        ),
        UnrealCapabilitySpec(
            name="blueprint.inspect",
            domain="blueprint",
            phase="inspect",
            mode="operation",
            operation="blueprint.dynamic_inspect",
            description="Inspect Blueprint graphs, variables, functions, and components.",
            expects=(
                _arg("blueprint", "blueprint_asset_name_or_path"),
            ),
            produces=("blueprint_summary",),
            timeout=12.0,
            requires_asset_types=("Blueprint", "AnimBlueprint", "WidgetBlueprint"),
            fallback_capabilities=("asset.resolve",),
            recommended_model="strong_reasoning",
            tags=("blueprint", "graph", "inspection"),
        ),
        UnrealCapabilitySpec(
            name="blueprint.list_functions",
            domain="blueprint",
            phase="inspect",
            mode="operation",
            operation="blueprint.dynamic_inspect",
            description="List Blueprint functions and callable graph metadata.",
            expects=(_arg("blueprint", "blueprint_asset_name_or_path"),),
            produces=("blueprint_functions",),
            timeout=12.0,
            requires_asset_types=("Blueprint", "AnimBlueprint", "WidgetBlueprint"),
            fallback_capabilities=("blueprint.inspect",),
            recommended_model="strong_reasoning",
            tags=("blueprint", "functions"),
        ),
        UnrealCapabilitySpec(
            name="blueprint.list_variables",
            domain="blueprint",
            phase="inspect",
            mode="operation",
            operation="blueprint.dynamic_inspect",
            description="List Blueprint variables and type/default metadata.",
            expects=(_arg("blueprint", "blueprint_asset_name_or_path"),),
            produces=("blueprint_variables",),
            timeout=12.0,
            requires_asset_types=("Blueprint", "AnimBlueprint", "WidgetBlueprint"),
            fallback_capabilities=("blueprint.inspect",),
            recommended_model="strong_reasoning",
            tags=("blueprint", "variables"),
        ),
        UnrealCapabilitySpec(
            name="blueprint.list_components",
            domain="blueprint",
            phase="inspect",
            mode="operation",
            operation="blueprint.dynamic_inspect",
            description="List Blueprint components and hierarchy metadata.",
            expects=(_arg("blueprint", "blueprint_asset_name_or_path"),),
            produces=("blueprint_components",),
            timeout=12.0,
            requires_asset_types=("Blueprint", "AnimBlueprint", "WidgetBlueprint"),
            fallback_capabilities=("blueprint.inspect",),
            recommended_model="strong_reasoning",
            tags=("blueprint", "components"),
        ),
        UnrealCapabilitySpec(
            name="blueprint.list_graphs",
            domain="blueprint",
            phase="inspect",
            mode="operation",
            operation="blueprint.dynamic_inspect",
            description="List Blueprint graphs and graph-level metadata.",
            expects=(_arg("blueprint", "blueprint_asset_name_or_path"),),
            produces=("blueprint_graphs",),
            timeout=12.0,
            requires_asset_types=("Blueprint", "AnimBlueprint", "WidgetBlueprint"),
            fallback_capabilities=("blueprint.inspect",),
            recommended_model="strong_reasoning",
            tags=("blueprint", "graphs"),
        ),
        UnrealCapabilitySpec(
            name="anim_bp.inspect_graph_cpp",
            domain="anim_blueprint",
            phase="inspect",
            mode="function",
            function="unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph",
            description="Inspect AnimBlueprint graph topology through the AIStudioBridge reflected C++ wrapper.",
            expects=(_arg("anim_bp", "AnimBlueprint_asset_or_object"),),
            produces=("anim_graph_snapshot",),
            timeout=15.0,
            requires_asset_types=("AnimBlueprint",),
            fallback_capabilities=("blueprint.inspect", "blueprint.list_graphs"),
            aliases=("blueprint.scan",),
            tags=("anim_blueprint", "anim_graph", "cpp_wrapper", "inspection"),
        ),
        UnrealCapabilitySpec(
            name="anim_graph.add_state_cpp",
            domain="anim_blueprint",
            phase="mutate",
            mode="function",
            function="unreal.AIStudioBridgeLibrary.add_anim_graph_state",
            description="Create or update an AnimBlueprint state-machine state through a reflected C++ editor wrapper.",
            read_only=False,
            risk="high",
            expects=(
                _arg("anim_bp", "AnimBlueprint_asset_or_object"),
                _arg("state_machine", "state_machine_name"),
                _arg("state_name", "state_name"),
                _arg("animation_asset", "animation_asset_path", required=False, default=""),
            ),
            produces=("anim_state_handle",),
            preflight=("anim_bp.inspect_graph_cpp",),
            validate=("anim_bp.inspect_graph_cpp", "anim_bp.compile"),
            rollback=("animation.delete_state",),
            permissions=("editor_asset_mutation", "anim_graph_mutation"),
            requires_asset_types=("AnimBlueprint",),
            aliases=("anim_graph.add_state",),
            tags=("anim_blueprint", "anim_graph", "cpp_wrapper", "state", "mutation"),
        ),
        UnrealCapabilitySpec(
            name="anim_graph.add_transition_rule_cpp",
            domain="anim_blueprint",
            phase="mutate",
            mode="function",
            function="unreal.AIStudioBridgeLibrary.add_anim_graph_transition_rule",
            description="Create an AnimBlueprint state-machine transition and assign a guard expression through a reflected C++ editor wrapper.",
            read_only=False,
            risk="high",
            expects=(
                _arg("anim_bp", "AnimBlueprint_asset_or_object"),
                _arg("state_machine", "state_machine_name"),
                _arg("from_state", "state_name"),
                _arg("to_state", "state_name"),
                _arg("rule_expression", "blueprint_boolean_expression"),
            ),
            produces=("anim_transition_handle",),
            preflight=("anim_bp.inspect_graph_cpp",),
            validate=("anim_bp.inspect_graph_cpp", "anim_bp.compile"),
            rollback=("animation.delete_transition",),
            permissions=("editor_asset_mutation", "anim_graph_mutation"),
            requires_asset_types=("AnimBlueprint",),
            aliases=("anim_graph.add_transition_rule",),
            tags=("anim_blueprint", "anim_graph", "cpp_wrapper", "transition", "mutation"),
        ),
        UnrealCapabilitySpec(
            name="anim_graph.synthesize_transition_rule_expression_cpp",
            domain="anim_blueprint",
            phase="mutate",
            mode="function",
            function="unreal.AIStudioBridgeLibrary.synthesize_anim_graph_transition_rule_expression",
            description="Synthesize bounded Blueprint transition-rule nodes from a boolean expression and wire the final bool into bCanEnterTransition through a reflected C++ editor wrapper.",
            read_only=False,
            risk="high",
            expects=(
                _arg("anim_bp", "AnimBlueprint_asset_or_object"),
                _arg("state_machine", "state_machine_name"),
                _arg("from_state", "state_name"),
                _arg("to_state", "state_name"),
                _arg("rule_expression", "blueprint_boolean_expression"),
            ),
            produces=("transition_rule_graph_mutation",),
            preflight=("anim_bp.inspect_graph_cpp",),
            validate=("anim_bp.inspect_graph_cpp", "anim_bp.compile"),
            rollback=("backup_asset.restore",),
            permissions=("editor_asset_mutation", "anim_graph_mutation", "blueprint_graph_mutation"),
            requires_asset_types=("AnimBlueprint",),
            aliases=("anim_graph.synthesize_transition_rule_expression",),
            tags=("anim_blueprint", "anim_graph", "blueprint_graph", "cpp_wrapper", "transition", "mutation"),
        ),
        UnrealCapabilitySpec(
            name="anim_graph.wire_output_pose_cpp",
            domain="anim_blueprint",
            phase="mutate",
            mode="function",
            function="unreal.AIStudioBridgeLibrary.wire_anim_graph_output_pose",
            description="Wire an AnimBlueprint state machine output into the AnimGraph output pose through a reflected C++ editor wrapper.",
            read_only=False,
            risk="high",
            expects=(
                _arg("anim_bp", "AnimBlueprint_asset_or_object"),
                _arg("state_machine", "state_machine_name"),
            ),
            produces=("pose_link_result",),
            preflight=("anim_bp.inspect_graph_cpp",),
            validate=("anim_bp.inspect_graph_cpp", "anim_bp.compile"),
            rollback=("backup_asset.restore",),
            permissions=("editor_asset_mutation", "anim_graph_mutation"),
            requires_asset_types=("AnimBlueprint",),
            aliases=("anim_graph.wire_state_machine_to_output_pose",),
            tags=("anim_blueprint", "anim_graph", "cpp_wrapper", "pose", "mutation"),
        ),
    ]
)


UNREAL_CAPABILITY_PACKS: dict[str, dict[str, Any]] = {
    "selection": {
        "inspect": ["selection.current", "actor.resolve", "asset.resolve", "level.current", "editor.state", "level.get_selected_actors"],
        "mutate": ["selection.select_actors", "level.delete_actor", "level.set_selected_actors"],
        "validate": [],
        "recommended_model": "fast_context",
        "risk": "low",
    },
    "asset": {
        "inspect": ["asset.resolve", "asset.load", "assets.inspect", "assets.dependencies"],
        "mutate": ["asset.delete", "asset.rename", "asset.duplicate", "asset.save"],
        "validate": ["asset.exists"],
        "recommended_model": "fast_context",
        "risk": "low",
    },
    "niagara": {
        "inspect": [
            "niagara.inspect_system",
            "niagara.list_emitters",
            "niagara.list_user_parameters",
            "niagara.list_renderer_properties",
            "niagara.list_module_inputs",
        ],
        "mutate": [
            "niagara.create_emitter",
            "niagara.set_user_parameter",
            "niagara.set_renderer_property",
            "niagara.set_emitter_property",
            "niagara.set_module_input",
            "niagara.add_to_level",
            "niagara.attach_to_selected_actor",
            "niagara.delete_emitter",
        ],
        "validate": ["niagara.validate", "niagara.compile"],
        "recommended_model": "strong_reasoning",
        "risk": "medium",
    },
    "physics": {
        "inspect": [
            "physics.inspect_asset",
            "physics.list_bodies",
            "physics.list_constraints",
            "physics.list_profiles",
            "physics.list_body_properties",
            "physics.list_constraint_properties",
        ],
        "mutate": [
            "physics.set_body_property",
            "physics.set_constraint_property",
            "physics.set_profile_property",
            "physics.assign_to_skeletal_mesh",
            "physics.enable_disable_collision", "physics.create_physics_asset", "physics.add_body", "physics.add_constraint", "physics.set_collision_profile",
        ],
        "validate": ["physics.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "medium",
    },
    "control_rig": {
        "inspect": [
            "control_rig.inspect",
            "control_rig.list_controls",
            "control_rig.list_hierarchy",
            "control_rig.list_graphs",
            "control_rig.list_units",
            "control_rig.list_control_properties", "control_rig.list_controls", "control_rig.list_hierarchy", "control_rig.list_graphs", "control_rig.list_units", "control_rig.inspect",
        ],
        "mutate": [
            "control_rig.set_control_property",
            "control_rig.set_control_default",
            "control_rig.rename_control",
            "control_rig.set_hierarchy_property", "control_rig.set_control_property", "control_rig.set_control_default", "control_rig.rename_control", "control_rig.add_rig_element", "control_rig.connect_rig_nodes",
        ],
        "validate": ["control_rig.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "high",
    },
    "blueprint": {
        "inspect": [
            "blueprint.inspect",
            "blueprint.list_functions",
            "blueprint.list_variables",
            "blueprint.list_components",
            "blueprint.list_graphs",
            "blueprint.get_compile_errors",
        ],
        "mutate": [
            "blueprint.set_default_property",
            "blueprint.add_component",
            "blueprint.set_component_property", "gameplay.create_gameplay_ability",
            "blueprint.add_function",
            "blueprint.set_property",
            "blueprint.add_node",
            "blueprint.open_graph",
            "blueprint.open_function",
            "blueprint.create_variable",
            "blueprint.connect_node_pins",
            "blueprint.set_breakpoint",
        ],
        "validate": ["blueprint.compile", "blueprint.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "high",
    },
    "anim_blueprint": {
        "inspect": [
            "anim_bp.inspect",
            "anim_bp.inspect_graph_cpp",
            "anim_bp.list_graphs",
            "anim_bp.list_state_machines",
            "anim_bp.list_anim_layers",
            "anim_bp.list_slots",
            "animation.get_state_machine_graph",
        ],
        "mutate": [
            "anim_graph.add_state_cpp",
            "anim_graph.add_transition_rule_cpp",
            "anim_graph.synthesize_transition_rule_expression_cpp",
            "anim_graph.wire_output_pose_cpp",
            "anim_bp.set_default_property",
            "anim_bp.add_slot",
            "anim_bp.set_class_reference", "animation.set_slot_animation",
            "animation.delete_state",
            "animation.delete_transition",
            "animation.add_anim_notify", "animation.rename_state", "animation.set_state_transition_rule",
        ],
        "validate": ["anim_bp.compile", "anim_bp.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "high",
    },
    "retarget": {
        "inspect": [
            "retarget.inspect",
            "retarget.list_chains",
            "retarget.list_profiles",
            "retarget.inspect_source_target", "retarget.inspect", "retarget.list_chains", "retarget.list_profiles",
        ],
        "mutate": [
            "retarget.set_profile_property",
            "retarget.set_chain_mapping",
            "retarget.set_root_settings", "retarget.create_ik_rig", "retarget.add_ik_chain", "retarget.create_ik_retargeter", "retarget.set_chain_mapping", "retarget.set_profile_property",
        ],
        "validate": ["retarget.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "medium",
    },
    "motion_matching": {
        "inspect": [
            "motion_matching.inspect_database",
            "motion_matching.list_animations",
            "motion_matching.inspect_schema",
            "motion_matching.list_channels", "motion_matching.inspect_database", "motion_matching.list_animations", "motion_matching.inspect_schema",
        ],
        "mutate": [
            "motion_matching.add_animation",
            "motion_matching.remove_animation",
            "motion_matching.set_database_property",
            "motion_matching.set_schema_property", "motion_matching.add_animation", "motion_matching.remove_animation", "motion_matching.set_database_property", "motion_matching.create_schema", "motion_matching.add_schema_channel", "motion_matching.add_state_animations",
        ],
        "validate": ["motion_matching.validate"],
        "recommended_model": "strong_reasoning",
        "risk": "medium",
    },
    "sequencer": {
        "inspect": ["sequencer.get_tracks"],
        "mutate": ["sequencer.create", "sequencer.add_actor_track", "sequencer.animate_transform", "sequencer.add_camera_cut", "sequencer.repair_bindings", "sequencer.delete_track"],
        "validate": [],
        "recommended_model": "strong_reasoning",
        "risk": "medium",
    },
    "project": {
        "inspect": ["project.find_duplicate_logic", "project.find_deprecated_apis", "project.dependency_graph", "project.validate_naming", "project.find_references"],
        "mutate": ["project.rename_symbol"],
        "validate": [],
        "recommended_model": "strong_reasoning",
        "risk": "high",
    },
}


def get_unreal_capability_pack(asset_category: str) -> Dict[str, Any]:
    return dict(UNREAL_CAPABILITY_PACKS.get(asset_category or "", {}))


def _disable_capabilities_with_missing_operations() -> None:
    try:
        from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS
    except Exception:
        return
    for name, spec in list(UNREAL_CAPABILITIES.items()):
        if spec.mode == "operation" and spec.operation and spec.operation not in UNREAL_OPERATIONS:
            UNREAL_CAPABILITIES[name] = replace(
                spec,
                enabled=False,
                tags=tuple(dict.fromkeys([*spec.tags, "operation_not_active"])),
            )


def list_unreal_capabilities(asset_category: str) -> List[str]:
    pack = get_unreal_capability_pack(asset_category)
    ordered: List[str] = []
    for key in ("inspect", "mutate", "validate"):
        for item in pack.get(key, []) or []:
            if item not in ordered:
                ordered.append(item)
    return ordered


def get_unreal_capability_spec(capability: str) -> Dict[str, Any]:
    spec = UNREAL_CAPABILITIES.get(capability or "")
    return spec.to_dict() if spec else {}


def list_registered_unreal_capabilities(
    *,
    domain: str = "",
    phase: str = "",
    enabled_only: bool = True,
) -> List[str]:
    out: List[str] = []
    for name, spec in UNREAL_CAPABILITIES.items():
        if enabled_only and not spec.enabled:
            continue
        if domain and spec.domain != domain:
            continue
        if phase and spec.phase != phase:
            continue
        out.append(name)
    return sorted(out)


def get_unreal_capability_execution(capability: str) -> Dict[str, Any]:
    spec = UNREAL_CAPABILITIES.get(capability or "")
    if not spec:
        return {}
    return {
        "mode": spec.mode,
        "context_call": spec.context_call,
        "operation": spec.operation,
        "function": spec.function,
        "read_only": spec.read_only,
        "risk": spec.risk,
        "timeout": spec.timeout,
        "expects": [item.to_dict() for item in spec.expects],
        "produces": list(spec.produces),
        "preflight": list(spec.preflight),
        "validate": list(spec.validate),
        "rollback": list(spec.rollback),
        "permissions": list(spec.permissions),
        "supports_dry_run": spec.supports_dry_run,
        "supports_batch": spec.supports_batch,
        "fallback_capabilities": list(spec.fallback_capabilities),
    }


def list_unreal_context_call_capabilities() -> List[str]:
    return sorted(
        name
        for name, spec in UNREAL_CAPABILITIES.items()
        if spec.mode == "context_call" and spec.enabled
    )


def validate_unreal_capability_registry() -> dict[str, Any]:
    declared: set[str] = set()
    pack_phase: dict[str, str] = {}

    for domain, pack in UNREAL_CAPABILITY_PACKS.items():
        for phase in ("inspect", "mutate", "validate"):
            for name in pack.get(phase, []) or []:
                declared.add(name)
                pack_phase[name] = phase

    executable = set(UNREAL_CAPABILITIES)

    invalid_specs: list[dict[str, str]] = []
    phase_mismatches: list[dict[str, str]] = []
    missing_preflight: list[str] = []
    missing_validation: list[str] = []
    missing_rollback: list[str] = []

    for name, spec in UNREAL_CAPABILITIES.items():
        if spec.mode == "context_call" and not spec.context_call:
            invalid_specs.append({"name": name, "issue": "missing context_call"})
        elif spec.mode == "operation" and not spec.operation:
            invalid_specs.append({"name": name, "issue": "missing operation"})
        elif spec.mode == "function" and not spec.function:
            invalid_specs.append({"name": name, "issue": "missing function"})

        expected_phase = pack_phase.get(name)
        if expected_phase and expected_phase != spec.phase:
            phase_mismatches.append(
                {
                    "name": name,
                    "pack_phase": expected_phase,
                    "spec_phase": spec.phase,
                }
            )

        if not spec.read_only:
            if not spec.preflight:
                missing_preflight.append(name)
            if not spec.validate:
                missing_validation.append(name)
            if spec.risk in {"medium", "high"} and not spec.rollback:
                missing_rollback.append(name)

    return {
        "ok": not any(
            (
                declared - executable,
                executable - declared,
                invalid_specs,
                phase_mismatches,
                missing_preflight,
                missing_validation,
                missing_rollback,
            )
        ),
        "declared_but_not_executable": sorted(declared - executable),
        "executable_but_not_declared": sorted(executable - declared),
        "invalid_specs": invalid_specs,
        "phase_mismatches": phase_mismatches,
        "mutations_missing_preflight": sorted(missing_preflight),
        "mutations_missing_validation": sorted(missing_validation),
        "medium_high_risk_missing_rollback": sorted(missing_rollback),
        "registered_count": len(executable),
        "declared_count": len(declared),
    }



# Auto-register any capability declared in the packs that was not explicitly registered
for _pack_name, _pack in UNREAL_CAPABILITY_PACKS.items():
    for _phase in ("inspect", "mutate", "validate"):
        for _cap in (_pack.get(_phase, []) or []):
            if _cap not in UNREAL_CAPABILITIES:
                _mode: CapabilityMode = "operation"
                _op = _cap
                _func = ""
                _read_only = (_phase != "mutate")
                _risk: CapabilityRisk = "low"
                if _phase == "mutate":
                    _risk = "medium"
                    if _pack_name in ("blueprint", "anim_blueprint", "control_rig", "project"):
                        _risk = "high"
                
                # Determine preflight
                _preflight = ()
                if _phase == "mutate":
                    _preflight = ("backup_asset",)

                # Determine validate
                _validate = ()
                if _phase == "mutate":
                    if _pack_name in ("blueprint", "anim_blueprint"):
                        _validate = ("blueprint.compile",)
                    elif _pack_name == "asset":
                        _validate = ("asset.exists",)
                    elif _pack_name == "niagara":
                        _validate = ("niagara.compile",)
                    elif _pack_name == "physics":
                        _validate = ("physics.validate",)
                    elif _pack_name == "control_rig":
                        _validate = ("control_rig.validate",)
                    elif _pack_name == "retarget":
                        _validate = ("retarget.validate",)
                    elif _pack_name == "motion_matching":
                        _validate = ("motion_matching.validate",)
                    elif _pack_name == "sequencer":
                        _validate = ("sequencer.get_tracks",)
                    else:
                        _validate = ("editor.state",)
                
                # Determine rollback
                _rollback = ()
                if _phase == "mutate" and _risk in ("medium", "high"):
                    _rollback = ("rollback.latest",)

                register_capability(
                    UnrealCapabilitySpec(
                        name=_cap,
                        domain=_pack_name,
                        phase=_phase,
                        mode=_mode,
                        operation=_op,
                        function=_func,
                        read_only=_read_only,
                        risk=_risk,
                        expects=(),
                        produces=(),
                        preflight=_preflight,
                        validate=_validate,
                        rollback=_rollback,
                    )
                )

_disable_capabilities_with_missing_operations()
