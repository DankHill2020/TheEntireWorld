"""Verified domain knowledge gathered from live Unreal Blueprint API probes."""

from __future__ import annotations

from typing import Any


BLUEPRINT_GRAPH_EXPERT_FACTS: tuple[dict[str, Any], ...] = (
    {
        "subject": "Unreal 5.8 Blueprint inspection",
        "relation": "supported_reflection_path",
        "value": "Use BlueprintEditorLibrary.list_member_variable_names, list_functions, and list_graphs; get_blueprint_variables and get_blueprint_functions are removed.",
        "evidence": ["live UE 5.8 Python reflection", "verified Blueprint scan"],
    },
    {
        "subject": "Unreal Blueprint graph authoring",
        "relation": "supported_editor_api",
        "value": "BlueprintGraphEditor supports create_and_edit_function_graph, add_member_variable, member get/set nodes, native call nodes, branches, custom events, palette-node creation, and node listing.",
        "evidence": ["live BlueprintGraphEditor.__doc__ reflection"],
    },
    {
        "subject": "Unreal Blueprint pin authoring",
        "relation": "supported_editor_api",
        "value": "Use BlueprintGraphPinLibrary for pin values, owning nodes, connection checks, link creation, and post-edit connection readback.",
        "evidence": ["live BlueprintGraphPinLibrary reflection"],
    },
    {
        "subject": "Unreal 5.8 Enhanced Input mappings",
        "relation": "authored_storage_location",
        "value": "InputMappingContext authored mappings are in default_key_mappings.mappings; the direct mappings property can be empty even when mappings exist.",
        "evidence": ["live /Game/Input/IMC_Default readback with 22 authored mappings"],
    },
    {
        "subject": "Unreal Enhanced Input mutation",
        "relation": "verified_operation_path",
        "value": "Create InputAction assets with InputAction_Factory and add keys with InputMappingContext.map_key, then verify default_key_mappings.mappings before reporting success.",
        "evidence": ["live IA_Sprint creation", "live LeftShift and Gamepad_LeftShoulder mapping readback"],
    },
    {
        "subject": "Unreal Blueprint component authoring",
        "relation": "supported_editor_api",
        "value": "Use SubobjectDataSubsystem and AddNewSubobjectParams to add Blueprint components; verify the returned handle and component readback before compile/save.",
        "evidence": ["live UE 5.8 SubobjectDataSubsystem reflection"],
    },
    {
        "subject": "Unreal Blueprint graph layout",
        "relation": "authoring_standard",
        "value": "Lay out execution flow left-to-right on a stable grid, keep pure data dependencies near consumers, separate branches vertically, group each feature in a named comment, and reject overlapping nodes before completion.",
        "evidence": ["BlueprintEditorLibrary node position APIs", "production readability requirement"],
    },
    {
        "subject": "Unreal Blueprint component verification",
        "relation": "supported_readback_path",
        "value": "Verify Blueprint-authored components through SubobjectDataSubsystem handles, variable names, and get_object_for_blueprint class paths; generated-class get_components_by_class can miss authored Blueprint components on UE 5.8.",
        "evidence": ["official prompt execution false-negative and successful automatic rollback"],
    },
    {
        "subject": "Unreal Blueprint pure-node dataflow",
        "relation": "authoring_hazard",
        "value": "Do not reuse a state-dependent pure expression both to set that state and after the setter executes; Blueprint can reevaluate it against the mutated value. Feed downstream logic from the setter Output_Get pin or another stored value.",
        "evidence": ["live RecoverStamina boundary test", "repaired 0.5-second false recovery"],
    },
    {
        "subject": "Unreal Blueprint component behavior validation",
        "relation": "verified_test_path",
        "value": "For world-independent ActorComponent logic, instantiate the compiled generated class with new_object and call Blueprint functions with call_method(name, args_tuple), then assert property transitions and boundaries before reporting completion.",
        "evidence": ["live BPC_StaminaSprint generated-class test", "drain, recovery, clamp, and exhaustion assertions"],
    },
    {
        "subject": "Unreal 5.8 PIE Python world access",
        "relation": "verified_world_discovery_fallback",
        "value": "When UnrealEditorSubsystem.get_game_world and EditorLevelLibrary.get_game_world return None during PIE, enumerate ObjectIterator(World) and identify runtime worlds by querying expected actors with GameplayStatics before declaring world access unavailable.",
        "evidence": ["live UE 5.8 PIE probe", "runtime BP_ThirdPersonCharacter actors resolved in transient worlds"],
    },
    {
        "subject": "Unreal 5.8 PIE lifecycle",
        "relation": "verified_preflight_requirement",
        "value": "A Blueprint Asset Compilation Errors confirmation can block PIE while is_in_play_in_editor still reports true. Preflight compile status, require an expected runtime world/actor, cancel rather than bypass unresolved errors, then call editor_request_end_play and verify PIE becomes inactive.",
        "evidence": ["live compiler-error confirmation", "PIE became inactive after the IA_Sprint modal was cancelled"],
    },
    {
        "subject": "Unreal runtime diagnostics",
        "relation": "verified_operation_path",
        "value": "Use diagnostics.read_log_errors to inspect a bounded active project-log tail, deduplicate repeated runtime/compiler messages, and identify Blueprint, graph, node, and occurrence count before assigning a failure to newly edited assets.",
        "evidence": ["live Time_Fighters.log query", "BP_TestTargetDummy Accessed None source resolved with occurrence counts"],
    },
)


def blueprint_graph_expert_context() -> str:
    """Return compact, version-specific guidance for the Blueprint expert."""

    lines = ["Verified Unreal Blueprint Graph API knowledge (UE 5.8):"]
    lines.extend(f"- {fact['value']}" for fact in BLUEPRINT_GRAPH_EXPERT_FACTS)
    return "\n".join(lines)


def persist_blueprint_graph_expert_knowledge(settings: dict | None = None) -> int:
    """Store live-validated facts in contextual knowledge for future retrieval."""

    from tech_connector.services.ai_work_memory_service import record_contextual_knowledge

    facts = [
        {
            "kind": "unreal_blueprint_graph_api",
            "subject": fact["subject"],
            "relation": fact["relation"],
            "value": fact["value"],
            "confidence": 1.0,
            "validated": True,
            "evidence": list(fact["evidence"]),
            "metadata": {"engine_version": "5.8", "domain": "unreal.blueprint_graph"},
        }
        for fact in BLUEPRINT_GRAPH_EXPERT_FACTS
    ]
    return record_contextual_knowledge(
        settings,
        facts,
        request="Live Unreal Blueprint graph and Enhanced Input API capability evaluation",
        source="live_unreal_api_validation",
    )
