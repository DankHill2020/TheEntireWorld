from __future__ import annotations

"""C++ bridge wrapper requirements for Unreal domains that Python cannot safely cover."""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class UnrealCppDomainWrapperRequirement:
    operation: str
    domain: str
    wrapper_function: str
    python_call: str
    reason: str
    required_modules: tuple[str, ...]
    minimum_contract: tuple[str, ...]
    validation_fixture: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DOMAIN_WRAPPER_REQUIREMENTS: tuple[UnrealCppDomainWrapperRequirement, ...] = (
    UnrealCppDomainWrapperRequirement(
        operation="niagara.delete_emitter",
        domain="niagara",
        wrapper_function="DeleteNiagaraEmitter",
        python_call="unreal.AIStudioBridgeLibrary.delete_niagara_emitter(system, emitter_name)",
        reason="Deleting emitters needs Niagara system mutation and post-mutation stack readback.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("locate emitter by name", "remove emitter", "mark modified", "save", "readback absence"),
        validation_fixture="clone Niagara system, delete emitter on clone, inspect emitter list, compile/save if supported",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="niagara.list_module_inputs",
        domain="niagara",
        wrapper_function="ListNiagaraModuleInputs",
        python_call="unreal.AIStudioBridgeLibrary.list_niagara_module_inputs(system, emitter_name, module_name)",
        reason="Module inputs need Niagara stack/script graph introspection rather than generic UObject property reads.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("resolve emitter/module", "list typed inputs", "include default/current values", "no mutation"),
        validation_fixture="open disposable Niagara asset and compare returned module/input names with stack readback",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="niagara.set_module_input",
        domain="niagara",
        wrapper_function="SetNiagaraModuleInput",
        python_call="unreal.AIStudioBridgeLibrary.set_niagara_module_input(system, emitter_name, module_name, input_name, value_json)",
        reason="Module input writes require typed Niagara variable conversion and stack graph mutation.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("snapshot", "resolve typed input", "write value", "compile/save", "readback exact value"),
        validation_fixture="clone Niagara system, set module input, compile/save, inspect value, rollback/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="niagara.set_renderer_property",
        domain="niagara",
        wrapper_function="SetNiagaraRendererProperty",
        python_call="unreal.AIStudioBridgeLibrary.set_niagara_renderer_property(system, emitter_name, renderer_index, property_name, value_json)",
        reason="Renderer writes need typed renderer property access plus Niagara system dirty/save handling.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("resolve renderer", "coerce value", "set property", "save", "readback"),
        validation_fixture="clone system, mutate renderer property, inspect renderer payload, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="niagara.set_emitter_property",
        domain="niagara",
        wrapper_function="SetNiagaraEmitterProperty",
        python_call="unreal.AIStudioBridgeLibrary.set_niagara_emitter_property(system, emitter_name, property_name, value_json)",
        reason="Emitter property writes need Niagara emitter handle/controller access and typed property conversion.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("resolve emitter", "coerce value", "set property", "save", "readback"),
        validation_fixture="clone system, mutate emitter property, inspect emitter payload, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="niagara.set_user_parameter",
        domain="niagara",
        wrapper_function="SetNiagaraUserParameter",
        python_call="unreal.AIStudioBridgeLibrary.set_niagara_user_parameter(system, parameter_name, value_json)",
        reason="User parameter writes require Niagara typed variable/value handling and readback.",
        required_modules=("Niagara", "NiagaraEditor"),
        minimum_contract=("resolve exposed/user parameter", "write typed value", "save", "readback exact value"),
        validation_fixture="clone system, set user parameter, inspect exposed parameter store, rollback/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="physics.set_profile_property",
        domain="physics",
        wrapper_function="SetPhysicsProfileProperty",
        python_call="unreal.AIStudioBridgeLibrary.set_physics_profile_property(physics_asset, profile_name, property_name, value_json)",
        reason="Physics profile mutation needs schema-specific access to profile arrays/maps, not generic body/constraint property writes.",
        required_modules=("PhysicsCore", "PhysicsAssetEditor"),
        minimum_contract=("resolve profile", "write typed property", "save", "readback profile value"),
        validation_fixture="clone PhysicsAsset, mutate profile, inspect profile, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.create_ik_rig",
        domain="ik_retarget",
        wrapper_function="CreateIKRig",
        python_call="unreal.AIStudioBridgeLibrary.create_ik_rig(skeletal_mesh, save_path)",
        reason="IK Rig asset creation and controller setup require IKRig editor APIs beyond the current Python helpers.",
        required_modules=("IKRig", "IKRigEditor", "AssetTools"),
        minimum_contract=("create asset", "assign preview mesh", "save", "readback solver/root settings"),
        validation_fixture="create disposable IK Rig for a known skeletal mesh, inspect chains/settings, delete on success",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.add_ik_chain",
        domain="ik_retarget",
        wrapper_function="AddIKRigChain",
        python_call="unreal.AIStudioBridgeLibrary.add_ik_rig_chain(ik_rig, chain_name, start_bone, end_bone)",
        reason="Chain authoring needs IKRig controller APIs and bone validation.",
        required_modules=("IKRig", "IKRigEditor"),
        minimum_contract=("validate bones", "add chain", "save", "readback chain list"),
        validation_fixture="clone IK Rig, add chain, inspect chain list, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.create_ik_retargeter",
        domain="ik_retarget",
        wrapper_function="CreateIKRetargeter",
        python_call="unreal.AIStudioBridgeLibrary.create_ik_retargeter(source_ik_rig, target_ik_rig, save_path)",
        reason="Retargeter creation needs IKRig editor asset factory/controller APIs.",
        required_modules=("IKRig", "IKRigEditor", "AssetTools"),
        minimum_contract=("create asset", "assign source/target rigs", "save", "readback paths"),
        validation_fixture="create disposable retargeter from fixture rigs, inspect, delete on success",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.set_chain_mapping",
        domain="ik_retarget",
        wrapper_function="SetIKRetargetChainMapping",
        python_call="unreal.AIStudioBridgeLibrary.set_ik_retarget_chain_mapping(retargeter, source_chain, target_chain)",
        reason="Chain mapping needs retargeter controller APIs and source/target chain validation.",
        required_modules=("IKRig", "IKRigEditor"),
        minimum_contract=("validate chains", "set mapping", "save", "readback mapping"),
        validation_fixture="clone retargeter, set mapping, inspect mapping, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.set_profile_property",
        domain="ik_retarget",
        wrapper_function="SetIKRetargetProfileProperty",
        python_call="unreal.AIStudioBridgeLibrary.set_ik_retarget_profile_property(retargeter, profile_name, property_name, value_json)",
        reason="Profile writes need typed retarget profile access and readback.",
        required_modules=("IKRig", "IKRigEditor"),
        minimum_contract=("resolve profile", "write typed value", "save", "readback"),
        validation_fixture="clone retargeter, mutate profile, inspect profile, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="retarget.set_root_settings",
        domain="ik_retarget",
        wrapper_function="SetIKRetargetRootSettings",
        python_call="unreal.AIStudioBridgeLibrary.set_ik_retarget_root_settings(retargeter, settings_json)",
        reason="Root settings writes need retargeter-specific typed controller access.",
        required_modules=("IKRig", "IKRigEditor"),
        minimum_contract=("write settings", "save", "readback settings"),
        validation_fixture="clone retargeter, set root settings, inspect, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.create_database",
        domain="pose_search",
        wrapper_function="CreatePoseSearchDatabase",
        python_call="unreal.AIStudioBridgeLibrary.create_pose_search_database(skeleton, animations, asset_path, schema)",
        reason="Pose Search database creation needs PoseSearch editor asset factory and typed animation list mutation.",
        required_modules=("PoseSearch", "PoseSearchEditor", "AssetTools"),
        minimum_contract=("create database", "assign schema", "add animations", "save", "readback animation count"),
        validation_fixture="create disposable database from fixture animation(s), inspect, delete on success",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.create_schema",
        domain="pose_search",
        wrapper_function="CreatePoseSearchSchema",
        python_call="unreal.AIStudioBridgeLibrary.create_pose_search_schema(skeleton, asset_path, channels_json)",
        reason="Schema creation and channel setup need PoseSearch editor APIs and typed channel objects.",
        required_modules=("PoseSearch", "PoseSearchEditor", "AssetTools"),
        minimum_contract=("create schema", "assign skeleton", "add channels", "save", "readback channels"),
        validation_fixture="create disposable schema, add requested channels, inspect, delete on success",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.add_schema_channel",
        domain="pose_search",
        wrapper_function="AddPoseSearchSchemaChannel",
        python_call="unreal.AIStudioBridgeLibrary.add_pose_search_schema_channel(schema, channel_name, channel_type, settings_json)",
        reason="Channel authoring needs typed PoseSearch channel construction and schema readback.",
        required_modules=("PoseSearch", "PoseSearchEditor"),
        minimum_contract=("create typed channel", "apply settings", "save", "readback channel"),
        validation_fixture="clone schema, add channel, inspect channel list, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.add_animation",
        domain="pose_search",
        wrapper_function="AddPoseSearchDatabaseAnimation",
        python_call="unreal.AIStudioBridgeLibrary.add_pose_search_database_animation(database, animation)",
        reason="Animation list mutation needs PoseSearch database typed APIs and indexing/rebuild readback.",
        required_modules=("PoseSearch", "PoseSearchEditor"),
        minimum_contract=("validate animation", "add to database", "save/reindex", "readback animation path"),
        validation_fixture="clone database, add animation, inspect count/path, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.remove_animation",
        domain="pose_search",
        wrapper_function="RemovePoseSearchDatabaseAnimation",
        python_call="unreal.AIStudioBridgeLibrary.remove_pose_search_database_animation(database, animation)",
        reason="Animation removal needs PoseSearch database typed APIs and reindex/readback.",
        required_modules=("PoseSearch", "PoseSearchEditor"),
        minimum_contract=("remove animation", "save/reindex", "readback absence"),
        validation_fixture="clone database, remove animation, inspect absence, restore/delete clone",
    ),
    UnrealCppDomainWrapperRequirement(
        operation="motion_matching.set_database_property",
        domain="pose_search",
        wrapper_function="SetPoseSearchDatabaseProperty",
        python_call="unreal.AIStudioBridgeLibrary.set_pose_search_database_property(database, property_name, value_json)",
        reason="Database property writes need typed PoseSearch property conversion and readback.",
        required_modules=("PoseSearch", "PoseSearchEditor"),
        minimum_contract=("set typed property", "save", "readback exact value"),
        validation_fixture="clone database, mutate property, inspect, restore/delete clone",
    ),
)


def get_cpp_domain_wrapper_requirement(
    operation: str,
) -> UnrealCppDomainWrapperRequirement | None:
    """Return the canonical C++ bridge contract for an operation, if required."""

    key = str(operation or "").strip()
    return next((row for row in DOMAIN_WRAPPER_REQUIREMENTS if row.operation == key), None)


def audit_cpp_domain_wrapper_requirements(active_operations: set[str] | None = None) -> dict[str, Any]:
    from tech_connector.services.unreal.unreal_operation_service import (
        UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY,
    )

    active_operations = set(active_operations or ())
    rows = [item.to_dict() for item in DOMAIN_WRAPPER_REQUIREMENTS]
    retired_without_requirement = sorted(
        op
        for op in UNREAL_OPERATIONS_REQUIRING_IMPLEMENTATION_STRATEGY
        if op not in {row.operation for row in DOMAIN_WRAPPER_REQUIREMENTS}
        and not op.startswith("project.")
    )
    requirements_for_active_ops = sorted(
        row.operation for row in DOMAIN_WRAPPER_REQUIREMENTS if row.operation in active_operations
    )
    return {
        "ok": not retired_without_requirement and not requirements_for_active_ops,
        "requirement_count": len(rows),
        "domains": sorted({row["domain"] for row in rows}),
        "requirements": rows,
        "retired_without_requirement": retired_without_requirement,
        "requirements_for_active_ops": requirements_for_active_ops,
    }
