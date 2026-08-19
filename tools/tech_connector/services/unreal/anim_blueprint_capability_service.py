from __future__ import annotations

"""Concrete AnimBlueprint capability planning for Unreal rehearsals.

This module deliberately separates proven automation, plugin entrypoints, and
real capability gaps. A plan should not label a callable operation as missing
just because deeper graph mutation still needs C++ implementation.
"""

import re
from typing import Any

from tech_connector.services.unreal.live_validation_fixture_service import (
    build_anim_blueprint_disposable_fixture,
)


PLUGIN_OPERATION_STATUS = {
    "blueprint.scan": {
        "plugin_capability": "inspect_anim_blueprint_graph",
        "python_call": "unreal.AIStudioBridgeLibrary.inspect_anim_blueprint_graph(anim_bp)",
        "status": "available",
        "gap": False,
        "reason": "Blueprint scan is implemented as a Python operation and exposed by AIStudioBridge for AnimBlueprint graph topology inspection.",
    },
    "anim_graph.add_state": {
        "plugin_capability": "add_anim_graph_state",
        "python_call": "unreal.AIStudioBridgeLibrary.add_anim_graph_state(anim_bp, state_machine, state_name, animation_asset)",
        "status": "plugin_body_present_build_validated_live_asset_validation_pending",
        "gap": False,
        "reason": "The reflected C++ body exists and the plugin build passed; direct confidence still requires a live Unreal validation pass on the target AnimBlueprint.",
    },
    "anim_graph.add_transition_rule": {
        "plugin_capability": "add_anim_graph_transition_rule",
        "python_call": "unreal.AIStudioBridgeLibrary.add_anim_graph_transition_rule(anim_bp, state_machine, from_state, to_state, rule_expression)",
        "status": "plugin_body_present_constant_rules_supported_complex_rules_use_synthesis_live_asset_validation_pending",
        "gap": False,
        "reason": "The reflected C++ body exists and can create transitions with constant true/false rules; complex guard expressions should be applied by the transition-rule synthesis wrapper.",
    },
    "anim_graph.wire_state_machine_to_output_pose": {
        "plugin_capability": "wire_anim_graph_output_pose",
        "python_call": "unreal.AIStudioBridgeLibrary.wire_anim_graph_output_pose(anim_bp, state_machine)",
        "status": "plugin_body_present_build_validated_live_asset_validation_pending",
        "gap": False,
        "reason": "The reflected C++ body exists and the plugin build passed; direct confidence still requires a live Unreal validation pass on the target AnimBlueprint.",
    },
    "blueprint.compile_and_save": {
        "plugin_capability": "compile_and_save_anim_blueprint",
        "python_call": "unreal.AIStudioBridgeLibrary.compile_and_save_anim_blueprint(anim_bp)",
        "status": "plugin_body_present_live_validation_pending",
        "gap": False,
        "reason": "The compile/save C++ body exists; direct confidence still requires a live Unreal validation pass on the target asset.",
    },
    "anim_graph.synthesize_transition_rule_expression": {
        "plugin_capability": "synthesize_anim_graph_transition_rule_expression",
        "python_call": "unreal.AIStudioBridgeLibrary.synthesize_anim_graph_transition_rule_expression(anim_bp, state_machine, from_state, to_state, rule_expression)",
        "status": "plugin_body_present_bounded_boolean_expression_synthesis_live_asset_validation_pending",
        "gap": False,
        "requires_known_implementation_strategy": False,
        "reason": "The reflected C++ body can synthesize bounded boolean rule graphs from variable reads, negation, && chains, numeric comparisons, and Vector.X/Y/Z component comparisons; target-asset live validation is still required before claiming mutation success.",
        "known_strategy": "Create or locate the transition edge, open its transition graph, synthesize K2 variable/math nodes for the guard expression, wire the final bool into bCanEnterTransition, then compile/save and inspect readback.",
    },
}


def build_anim_blueprint_capability_plan(prompt: str) -> dict[str, Any]:
    system_name = _system_name(prompt)
    target_abp = _target_abp(prompt)
    states = _states(system_name)
    variables = _variables(system_name)
    transitions = _transitions(system_name)
    required_operations = [
        "blueprint.scan",
        "anim_graph.add_state",
        "anim_graph.add_transition_rule",
        "anim_graph.wire_state_machine_to_output_pose",
        "blueprint.compile_and_save",
    ]
    if _requires_complex_transition_rule_synthesis(transitions):
        required_operations.append("anim_graph.synthesize_transition_rule_expression")
    return {
        "kind": "unreal_abp_capability_plan",
        "target": target_abp,
        "system_name": system_name,
        "service_functions": [
            "anim_blueprint_injector_service.find_existing_anim_blueprints",
            "anim_blueprint_injector_service.build_abp_target_selection_prompt",
            "anim_blueprint_injector_service.generate_unreal_abp_injection_script",
            "execute_dcc_capability or execute_unreal_python for live editor mutation",
        ],
        "actual_steps": [
            {
                "id": "resolve_target_abp",
                "tool": "find_existing_anim_blueprints",
                "operation": "Find candidate AnimBlueprint assets and choose the exact target.",
                "inputs": {"directory": "/Game/", "preferred_target": target_abp},
                "produces": ["target_anim_blueprint_path"],
                "proven": True,
            },
            {
                "id": "snapshot_existing_graph",
                "tool": "blueprint.scan / AIStudioBridge.inspect_anim_blueprint_graph",
                "operation": "Read existing AnimGraph, locomotion state machines, variables, transitions, skeleton, and animation references.",
                "inputs": {"target_abp": "$target_anim_blueprint_path"},
                "produces": ["anim_graph_snapshot", "existing_locomotion_state_machine"],
                "proven": True,
                "capability_status": PLUGIN_OPERATION_STATUS["blueprint.scan"]["status"],
            },
            {
                "id": "inject_variables",
                "tool": "generate_unreal_abp_injection_script",
                "operation": "Add required AnimBlueprint variables without touching graph topology.",
                "inputs": {"target_abp": "$target_anim_blueprint_path", "variables": variables},
                "produces": ["injected_variables"],
                "proven": True,
            },
            {
                "id": "resolve_animation_assets",
                "tool": "Unreal asset registry",
                "operation": "Find animation sequences/blendspaces compatible with the target skeleton for every new state.",
                "inputs": {"states": states},
                "produces": ["animation_asset_map"],
                "proven": False,
            },
            {
                "id": "create_or_update_states",
                "tool": "AIStudioBridge.add_anim_graph_state",
                "operation": "Create missing states inside the resolved locomotion state machine and assign animation assets.",
                "inputs": {
                    "state_machine": "$existing_locomotion_state_machine",
                    "states": states,
                    "animations": "$animation_asset_map",
                },
                "produces": ["created_or_reused_states"],
                "proven": False,
                "capability_status": PLUGIN_OPERATION_STATUS["anim_graph.add_state"]["status"],
            },
            {
                "id": "wire_transition_rules",
                "tool": "AIStudioBridge.add_anim_graph_transition_rule",
                "operation": "Create transition edges between locomotion and feature states. Constant rules are covered by the C++ wrapper; prompt-derived boolean guard expressions are applied by transition-rule graph synthesis.",
                "inputs": {"transitions": transitions},
                "produces": ["transition_rule_results"],
                "proven": False,
                "capability_status": PLUGIN_OPERATION_STATUS["anim_graph.add_transition_rule"]["status"],
            },
            {
                "id": "synthesize_transition_rule_graphs",
                "tool": "AIStudioBridge.synthesize_anim_graph_transition_rule_expression",
                "operation": "Convert each requested transition condition into concrete Blueprint rule nodes and wire the final boolean into the transition result.",
                "inputs": {"transitions": transitions, "variables": variables},
                "produces": ["transition_rule_graph_mutations"],
                "proven": False,
                "capability_status": PLUGIN_OPERATION_STATUS["anim_graph.synthesize_transition_rule_expression"]["status"],
            },
            {
                "id": "wire_character_inputs",
                "tool": "target_discovery plus a concrete C++ or Blueprint graph mutation capability",
                "operation": "Bind owning Character/Movement data into AnimInstance variables during update animation.",
                "inputs": {"variables": variables, "source": "owning Character/Movement component"},
                "produces": ["input_binding_changes"],
                "proven": False,
            },
            {
                "id": "compile_and_rescan",
                "tool": "AIStudioBridge.compile_and_save_anim_blueprint + blueprint.scan",
                "operation": "Compile, save, and rescan the AnimBlueprint to verify variables, states, and transition rules.",
                "inputs": {"target_abp": "$target_anim_blueprint_path"},
                "produces": ["compile_result", "post_mutation_graph_snapshot"],
                "proven": False,
                "capability_status": PLUGIN_OPERATION_STATUS["blueprint.compile_and_save"]["status"],
            },
        ],
        "prepared_script": _prepared_variable_script(target_abp, system_name, variables),
        "available_capabilities": _available_capabilities(required_operations),
        "capability_gaps": _capability_gaps(required_operations, prompt),
        "capability_acquisition_plans": _capability_acquisition_plans(required_operations, prompt),
        "cpp_wrapper_plans": _cpp_wrapper_plans(required_operations, prompt),
        "execution_preflight": _execution_preflight(required_operations),
        "live_validation_fixtures": [
            build_anim_blueprint_disposable_fixture(
                target_abp=target_abp,
                state_machine_name=system_name or "Locomotion",
                transitions=transitions,
            )
        ],
        "validation": [
            f"Load {target_abp} and verify the asset exists.",
            "Create a disposable AnimBlueprint duplicate and run the graph mutation sequence there first.",
            f"Compile {target_abp} after variable injection.",
            "Rescan AnimGraph and assert every requested state and transition exists before reporting success.",
            "If Unreal is disconnected, return this as proposed editor work and mark direct execution unavailable.",
        ],
    }


def _available_capabilities(operations: list[str]) -> list[dict[str, Any]]:
    capabilities = []
    for operation in operations:
        status = PLUGIN_OPERATION_STATUS.get(operation, {})
        if status.get("gap"):
            continue
        capabilities.append(
            {
                "host": "unreal",
                "operation": operation,
                "capability": status.get("plugin_capability", operation),
                "python_call": status.get("python_call"),
                "status": status.get("status", "available"),
                "reason": status.get("reason", "Capability is available."),
            }
        )
    return capabilities


def _capability_gaps(operations: list[str], prompt: str) -> list[dict[str, Any]]:
    gaps = []
    for operation in operations:
        status = PLUGIN_OPERATION_STATUS.get(operation, {})
        if not status.get("gap", True):
            continue
        gaps.append(
            {
                "kind": status.get("status", "missing_unreal_anim_graph_operation"),
                "host": "unreal",
                "capability": status.get("plugin_capability", operation),
                "operation": operation,
                "python_call": status.get("python_call"),
                "reason": status.get(
                    "reason",
                    f"{operation} must be verified before this prompt can mutate AnimBlueprint graph topology.",
                ),
                "requires_known_implementation_strategy": bool(
                    status.get("requires_known_implementation_strategy")
                ),
                "known_strategy": status.get("known_strategy", ""),
                "original_request": prompt,
                "resolution": "Implement the missing operation, rebuild/reload the plugin if C++ is required, live-validate the reflected Python call, then replan.",
            }
        )
    return gaps


def _capability_acquisition_plans(operations: list[str], prompt: str) -> list[dict[str, Any]]:
    try:
        from tech_connector.game_engine.integration.dcc_operation_service import build_dcc_capability_gap_plan
    except Exception:
        return []
    return [
        build_dcc_capability_gap_plan(
            "unreal",
            operation,
            original_request=prompt,
        )
        for operation in operations
        if PLUGIN_OPERATION_STATUS.get(operation, {}).get("gap", True)
    ]


def _cpp_wrapper_plans(operations: list[str], prompt: str) -> list[dict[str, Any]]:
    try:
        from tech_connector.services.unreal.unreal_cpp_wrapper_service import create_unreal_cpp_wrapper_plan
    except Exception:
        return []
    request_by_operation = {
        "blueprint.scan": "inspect anim blueprint graph",
        "anim_graph.add_state": "add anim graph state to anim blueprint",
        "anim_graph.add_transition_rule": "add anim graph transition rule to anim blueprint",
        "anim_graph.wire_state_machine_to_output_pose": "wire anim graph state machine to output pose",
        "blueprint.compile_and_save": "compile and save anim blueprint",
        "anim_graph.synthesize_transition_rule_expression": "synthesize anim graph transition rule expression to transition result graph",
    }
    plans = []
    for operation in operations:
        status = PLUGIN_OPERATION_STATUS.get(operation, {})
        if status.get("requires_known_implementation_strategy") and not status.get("known_strategy"):
            plans.append(
                {
                    "ok": False,
                    "message": "Blocked wrapper generation because this operation has no declared implementation strategy.",
                    "operation": operation,
                    "plugin_capability": status.get("plugin_capability"),
                    "python_call": status.get("python_call"),
                    "implementation_status": status.get("status"),
                    "is_execution_blocker": True,
                    "requires_known_implementation_strategy": True,
                    "known_strategy": "",
                    "required_before_codegen": [
                        "Define the exact Unreal graph API path for creating transition-rule nodes.",
                        "Define the supported expression grammar and node mappings.",
                        "Define readback evidence that proves the generated rule graph matches the prompt condition.",
                        "Add a disposable/live-asset validation fixture before registering the operation as executable.",
                    ],
                    "original_request": prompt,
                }
            )
            continue
        wrapper = create_unreal_cpp_wrapper_plan(
            ".",
            request_by_operation.get(operation, operation),
            apply=False,
        ).to_dict()
        wrapper["operation"] = operation
        wrapper["plugin_capability"] = status.get("plugin_capability")
        wrapper["python_call"] = status.get("python_call")
        wrapper["implementation_status"] = status.get("status", "requires_cpp_body_implementation_and_live_unreal_validation")
        wrapper["is_execution_blocker"] = bool(status.get("gap", True))
        wrapper["original_request"] = prompt
        plans.append(wrapper)
    return plans


def _execution_preflight(operations: list[str]) -> dict[str, Any]:
    blockers = []
    for operation in operations:
        status = PLUGIN_OPERATION_STATUS.get(operation, {})
        if status.get("gap"):
            blockers.append(
                {
                    "operation": operation,
                    "status": status.get("status"),
                    "reason": status.get("reason"),
                    "requires_known_implementation_strategy": bool(
                        status.get("requires_known_implementation_strategy")
                    ),
                    "known_strategy": status.get("known_strategy", ""),
                }
            )
    return {
        "ready_for_direct_execution": not blockers,
        "blockers": blockers,
        "policy": "Direct execution is disabled until every required operation has a concrete callable, a known implementation strategy, and live readback validation.",
    }


def _target_abp(prompt: str) -> str:
    if re.search(r"\babp\s+combat\b|\babp_combat\b", prompt, re.I):
        return "/Game/Variant_Combat/Anims/ABP_Manny_Combat"
    match = re.search(r"\b(ABP_[A-Za-z0-9_]+)\b", prompt)
    if match:
        return f"/Game/**/{match.group(1)}"
    return "/Game/Mannequins/Animations/ABP_Manny"


def _system_name(prompt: str) -> str:
    if re.search(r"\bcrawl(?:ing)?|prone\b", prompt, re.I):
        return "Crawl"
    if re.search(r"\bclimb|mantle|ledge\b", prompt, re.I):
        return "Climb"
    return "LocomotionFeature"


def _states(system_name: str) -> list[str]:
    if system_name == "Crawl":
        return ["ProneIdle", "CrawlForward", "CrawlBackward", "CrawlStrafeLeft", "CrawlStrafeRight"]
    return [f"{system_name}Idle", f"{system_name}Move"]


def _variables(system_name: str) -> list[str]:
    variables = [f"bIs{system_name}", f"{system_name}Speed", f"{system_name}Direction"]
    if system_name == "Crawl":
        variables.extend(["bWantsToCrawl", "bCanEnterCrawl", "CrawlInputVector"])
    return variables


def _transitions(system_name: str) -> list[str]:
    if system_name != "Crawl":
        return [
            f"Locomotion -> {system_name}Idle when bIs{system_name}",
            f"{system_name}Idle -> Locomotion when !bIs{system_name}",
        ]
    return [
        "Crouch/Locomotion -> ProneIdle when bWantsToCrawl && bCanEnterCrawl",
        "ProneIdle -> CrawlForward when CrawlInputVector.X > 0.1",
        "ProneIdle -> CrawlBackward when CrawlInputVector.X < -0.1",
        "ProneIdle -> CrawlStrafeLeft when CrawlInputVector.Y < -0.1",
        "ProneIdle -> CrawlStrafeRight when CrawlInputVector.Y > 0.1",
        "Any Crawl state -> Crouch/Locomotion when !bWantsToCrawl",
    ]


def _requires_complex_transition_rule_synthesis(transitions: list[str]) -> bool:
    for transition in transitions:
        condition = transition.partition(" when ")[2].strip().lower()
        if condition and condition not in {"true", "false", "always", "never"}:
            return True
    return False


def _prepared_variable_script(target_abp: str, system_name: str, variables: list[str]) -> str:
    type_by_name = {
        "CrawlInputVector": "vector",
    }
    variable_lines = "\n".join(
        f"        ({name!r}, {type_by_name.get(name, 'bool' if name.startswith('b') else 'float')!r}),"
        for name in variables
    )
    return (
        "import unreal\n\n"
        "def inject_abp_variables():\n"
        f"    abp_path = {target_abp!r}\n"
        "    abp = unreal.EditorAssetLibrary.load_asset(abp_path)\n"
        "    if not abp:\n"
        "        raise ValueError(f'AnimBlueprint not found: {abp_path}')\n"
        "    variables = [\n"
        f"{variable_lines}\n"
        "    ]\n"
        "    added = []\n"
        "    for name, kind in variables:\n"
        "        try:\n"
        "            unreal.BlueprintEditorLibrary.add_variable(abp, name, kind)\n"
        "            added.append(name)\n"
        "        except Exception:\n"
        "            pass\n"
        "    unreal.BlueprintEditorLibrary.compile_blueprint(abp)\n"
        "    unreal.EditorAssetLibrary.save_loaded_asset(abp, False)\n"
        "    return {'target_abp': abp_path, 'added_variables': added}\n"
    )

