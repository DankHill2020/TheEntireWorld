"""Prompt routing decision models and deterministic routing rules."""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


ENGINE_PROVIDERS = {"action_graph", "connection_status", "project_health", "target_discovery", "project_search", "import_coverage"}

HOST_ALIASES = {
    "maya": ("maya", "mayya"),
    "unreal": ("unreal", "ue5", "ue4", "unrel"),
    "blender": ("blender",),
    "substance_painter": ("substance painter", "substance", "painter"),
    "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
    "unity": ("unity",),
    "houdini": ("houdini", "hou", "hip"),
}

IMPLICIT_HOST_PATTERNS = {
    "unreal": re.compile(
        r"\b(?:niagara|anim\s*blueprint|anim\s*bp|metahuman|control\s*rig|blueprint\s+variables?)\b",
        re.IGNORECASE,
    ),
}


@dataclass
class PromptRouteDecision:
    route: str
    confidence: float
    provider: str
    intent_category: str = ""
    host: str = ""
    execution_route: str = ""
    handler_id: str = ""
    operation_mode: str = ""
    target_type: str = ""
    target_identifier: str = ""
    callable_name: str = ""
    positional_args: list[Any] = field(default_factory=list)
    keyword_args: dict[str, Any] = field(default_factory=dict)
    execution_environment: str = ""
    mutation_scope: str = ""
    analysis_depth: str = ""
    context_resolvers: list[str] = field(default_factory=list)
    deterministic_steps: list[str] = field(default_factory=list)
    search_scopes: list[str] = field(default_factory=list)
    index_filters: dict[str, Any] = field(default_factory=dict)
    model_capability: str = ""
    risk_level: str = ""
    requires_fresh_index: bool = False
    requires_dcc_connection: bool = False
    requires_plan: bool = False
    can_execute_directly: bool = False
    compound_kind: str = "atomic"
    operations: list[dict[str, Any]] = field(default_factory=list)
    requires_confirmation: bool = False
    required_context: list[str] = field(default_factory=list)
    model_tier: str = "local_fast"
    missing_info: list[str] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    rejected_routes: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    route_candidates: list[dict[str, Any]] = field(default_factory=list)
    selected_route_reason: str = ""
    senior_prompt_analysis: dict[str, Any] = field(default_factory=dict)
    reasoning_pipeline: dict[str, Any] = field(default_factory=dict)
    visible_progress: dict[str, Any] = field(default_factory=dict)
    domain_experts: list[dict[str, Any]] = field(default_factory=list)
    capability_gap_plan: dict[str, Any] = field(default_factory=dict)
    request_understanding: dict[str, Any] = field(default_factory=dict)
    semantic_execution_contract: dict[str, Any] = field(default_factory=dict)
    task_graph: dict[str, Any] = field(default_factory=dict)
    execution_context: dict[str, Any] = field(default_factory=dict)
    primary_goal: str = ""
    goal_type: str = ""
    estimated_steps: int = 0
    requires_generation: bool = False
    requires_project_search: bool = False
    requires_validation: bool = False
    requires_execution: bool = False
    expected_outcomes: list[dict[str, Any]] = field(default_factory=list)
    # Capability Acquisition & Gap Analysis
    capability_plan_id: str = ""
    capability_gaps: list[str] = field(default_factory=list)
    user_prompt_preferences: dict[str, str] = field(default_factory=dict)


    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _word_in(text: str, value: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text))


def _detect_host(text: str) -> str:
    lower = (text or "").lower()
    for host, aliases in HOST_ALIASES.items():
        if any(_word_in(lower, alias) for alias in aliases):
            return host
    for host, pattern in IMPLICIT_HOST_PATTERNS.items():
        if pattern.search(lower):
            return host
    return ""


def _detect_hosts(text: str) -> list[str]:
    lower = (text or "").lower()
    hosts = []
    for host, aliases in HOST_ALIASES.items():
        if any(_word_in(lower, alias) for alias in aliases):
            hosts.append(host)
    # An explicit host owns ambiguous domain terms such as "control rig".
    # Implicit patterns only fill the host when the prompt names none.
    if hosts:
        return hosts
    for host, pattern in IMPLICIT_HOST_PATTERNS.items():
        if host not in hosts and pattern.search(lower):
            hosts.append(host)
    return hosts


def _goal(
    task_id: str,
    title: str,
    action: str,
    goal_type: str,
    objective: str,
    *,
    depends_on: list[str] | None = None,
    read_only: bool = True,
    required_inputs: list[str] | None = None,
    produces: list[str] | None = None,
    success_condition: str = "",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "goal_id": task_id,
        "title": title,
        "action": action,
        "goal_type": goal_type,
        "objective": objective,
        "depends_on": list(depends_on or []),
        "read_only": read_only,
        "required_inputs": list(required_inputs or []),
        "produces": list(produces or []),
        "success_condition": success_condition,
    }


def _goal_graph(primary_goal: str, goal_type: str, goals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "valid": True,
        "primary_goal": primary_goal,
        "goal_type": goal_type,
        "goals": goals,
        "ordered_goals": goals,
        "estimated_steps": len(goals),
        "mutation_goal_ids": [
            str(goal.get("task_id") or "")
            for goal in goals
            if not bool(goal.get("read_only", True))
        ],
        "approval_goal_ids": [
            str(goal.get("task_id") or "")
            for goal in goals
            if not bool(goal.get("read_only", True))
        ],
    }


def _dcc_operation_task_graph(
    prompt: str,
    *,
    host: str,
    operation_key: str,
    callable_name: str = "",
    read_only: bool = False,
) -> dict[str, Any]:
    primary = f"Execute {host} operation {operation_key}."
    if host == "maya" and operation_key == "rigging.create_rig":
        goals = [
            _goal(
                "inspect_maya_rig_scene",
                "Inspect rig scene",
                "inspect",
                "locate",
                "Inspect the open Maya scene for skeleton roots, RFL joints, meshes, existing controls, and whether a rig already exists.",
                produces=["maya_rig_scene_inventory"],
                success_condition="Skeleton, existing controls, and required rigging inputs are known before mutation.",
            ),
            _goal(
                "resolve_hik_body_face_mapping",
                "Resolve HIK joint maps",
                "inspect",
                "locate",
                "Build HumanIK body and face joint maps from the current skeleton using setup_hik.create_rig_mapping.",
                depends_on=["inspect_maya_rig_scene"],
                required_inputs=["maya_rig_scene_inventory"],
                produces=["body_joint_map", "face_joint_map"],
                success_condition="Body and face maps contain required root, pelvis, spine, limb, head, and face entries.",
            ),
            _goal(
                "create_core_body_modules",
                "Create body rig modules",
                "execute",
                "execute",
                "Create root, pelvis, spine, neck, head, clavicle, arm, leg, IK/FK, and RFL modules using create_rig.create_rig_from_mapping.",
                depends_on=["resolve_hik_body_face_mapping"],
                read_only=read_only,
                required_inputs=["body_joint_map"],
                produces=["body_rig_controls"],
                success_condition="Core biped controls, IK/FK switches, RFL controls, constraints, and pads are created.",
            ),
            _goal(
                "create_face_modules",
                "Create face rig modules",
                "execute",
                "execute",
                "Create brow, eye, eyelid, mouth, tongue, teeth, and other face controls using create_rig.create_rig_from_mapping.",
                depends_on=["resolve_hik_body_face_mapping", "create_core_body_modules"],
                read_only=read_only,
                required_inputs=["face_joint_map", "body_rig_controls"],
                produces=["face_rig_controls"],
                success_condition="Mapped face joints receive controls, pads, constraints, and secondary face setup.",
            ),
            _goal(
                "validate_created_rig",
                "Validate created rig",
                "validate",
                "validate",
                "Read back created controls, constraints, mapped joints, and key expected controls such as origin, pelvis, hand IK, ankle IK, and RFL controls.",
                depends_on=["create_core_body_modules", "create_face_modules"],
                required_inputs=["body_rig_controls", "face_rig_controls"],
                produces=["validation_result"],
                success_condition="Expected body/face controls and constraints exist, or failures are reported with missing modules.",
            ),
        ]
        graph = _goal_graph(primary, "execute", goals)
        graph["required_capabilities"] = [
            "maya_scene_inventory",
            "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
            "maya_tools.Rigging.create_rig.create_rig_from_mapping",
            "dcc_validation",
        ]
        graph["operation_dependencies"] = [
            {
                "operation": "setup_hik.create_rig_mapping",
                "produces": ["body_joint_map", "face_joint_map"],
                "used_by": ["create_rig.create_rig_from_mapping"],
            },
            {
                "operation": "create_rig.create_rig_from_mapping",
                "requires": ["body_joint_map", "face_joint_map"],
                "produces": ["body_rig_controls", "face_rig_controls", "constraints"],
            },
        ]
        return graph

    if host == "unreal" and operation_key == "niagara.attach_editable_character_fx":
        goals = [
            _goal(
                "resolve_character_blueprint",
                "Resolve character Blueprint",
                "inspect",
                "locate",
                "Resolve the target character Blueprint and inspect current components, variables, and compile state.",
                produces=["character_blueprint_context"],
                success_condition="Target Blueprint is loaded and existing FX/component state is known.",
            ),
            _goal(
                "resolve_or_create_niagara_system",
                "Resolve or create Niagara System",
                "execute",
                "execute",
                "Duplicate/reuse the source Niagara System into the AIStudio prototype path.",
                depends_on=["resolve_character_blueprint"],
                read_only=read_only,
                required_inputs=["character_blueprint_context"],
                produces=["niagara_system_asset"],
                success_condition="A Niagara System asset exists at the target path and can be loaded.",
            ),
            _goal(
                "attach_niagara_component",
                "Attach Niagara component",
                "execute",
                "execute",
                "Add a NiagaraComponent to the character Blueprint, assign the system asset, and set the requested socket/bone when reflected properties allow it.",
                depends_on=["resolve_or_create_niagara_system"],
                read_only=read_only,
                required_inputs=["character_blueprint_context", "niagara_system_asset"],
                produces=["character_fx_component"],
                success_condition="The character Blueprint contains the requested Niagara component with the system assigned.",
            ),
            _goal(
                "expose_fx_tunables",
                "Expose editable FX tunables",
                "execute",
                "execute",
                "Create editable Blueprint variables for FX color, intensity, spawn rate, radius, lifetime, pulse speed, auto activate, attach socket, and attach offset.",
                depends_on=["attach_niagara_component"],
                read_only=read_only,
                required_inputs=["character_fx_component"],
                produces=["fx_tunable_variables"],
                success_condition="The requested FX variables exist on the Blueprint for designer editing.",
            ),
            _goal(
                "compile_save_and_readback_fx",
                "Compile, save, and read back FX",
                "validate",
                "validate",
                "Compile/save the Blueprint and read back variables, components, and referenced Niagara System evidence.",
                depends_on=["expose_fx_tunables"],
                required_inputs=["fx_tunable_variables"],
                produces=["validation_result"],
                success_condition="Blueprint scan confirms component and tunable variables, or reports exact missing pieces.",
            ),
        ]
        graph = _goal_graph(primary, "execute", goals)
        graph["required_capabilities"] = [
            "blueprint.scan",
            "unreal.EditorAssetLibrary.duplicate_asset",
            "blueprint.add_component",
            "blueprint.create_variable",
            "blueprint.compile",
        ]
        graph["operation_dependencies"] = [
            {
                "operation": "unreal.EditorAssetLibrary.duplicate_asset",
                "requires": ["source_system_path", "system_path"],
                "produces": ["niagara_system_asset"],
            },
            {
                "operation": "blueprint.add_component",
                "requires": ["blueprint_path", "niagara_system_asset", "component_name", "socket_name"],
                "produces": ["character_fx_component"],
            },
            {
                "operation": "blueprint.create_variable",
                "requires": ["blueprint_path", "fx_tunable_specs"],
                "produces": ["fx_tunable_variables"],
            },
        ]
        return graph

    goals = [
        _goal(
            "resolve_dcc_operation",
            "Resolve the DCC operation",
            "inspect",
            "locate",
            "Resolve the registered DCC operation, callable, arguments, and missing inputs.",
            produces=["dcc_execution_request"],
            success_condition="A callable, host, arguments, and missing inputs are known.",
        ),
        _goal(
            "preflight_dcc_operation",
            "Preflight operation dependencies",
            "inspect",
            "validate",
            "Check host connection, required arguments, target availability, mutation scope, and confirmation requirements before execution.",
            depends_on=["resolve_dcc_operation"],
            required_inputs=["dcc_execution_request"],
            produces=["dcc_preflight_result"],
            success_condition="Required inputs and host availability are verified or blockers are explicit.",
        ),
        _goal(
            "execute_dcc_operation",
            "Execute the DCC operation",
            "execute",
            "execute",
            f"Execute {operation_key} through {callable_name or 'the registered DCC callable'}.",
            depends_on=["preflight_dcc_operation"],
            read_only=read_only,
            required_inputs=["dcc_preflight_result"],
            produces=["dcc_result"],
            success_condition="The host reports a completed operation or a structured failure.",
        ),
        _goal(
            "validate_dcc_result",
            "Validate the host result",
            "validate",
            "validate",
            "Read back host state and validate the operation result.",
            depends_on=["execute_dcc_operation"],
            required_inputs=["dcc_result"],
            produces=["validation_result"],
            success_condition="Requested host state is confirmed or discrepancy is reported.",
        ),
    ]
    graph = _goal_graph(primary, "execute", goals)
    graph["required_capabilities"] = ["dcc_registry", "dcc_connection", callable_name or operation_key, "dcc_validation"]
    return graph


def _gameplay_feature_task_graph(prompt: str, *, read_only: bool = False) -> dict[str, Any]:
    goals = [
        _goal(
            "inspect_gameplay_architecture",
            "Inspect existing gameplay architecture",
            "search",
            "locate",
            "Find owning Character, Controller, Ability, Animation, UI, save/load, and networking patterns before planning changes.",
            produces=["candidate_targets", "existing_patterns"],
            success_condition="Likely owning files/assets and reusable functions are identified.",
        ),
        _goal(
            "resolve_feature_dependencies",
            "Resolve feature dependencies",
            "inspect",
            "plan",
            "Map required inputs, assets, replicated state, animation hooks, UI notifications, and validation surfaces.",
            depends_on=["inspect_gameplay_architecture"],
            required_inputs=["candidate_targets", "existing_patterns"],
            produces=["dependency_map"],
            success_condition="The plan names dependencies and missing evidence explicitly.",
        ),
        _goal(
            "design_feature_plan",
            "Design staged gameplay feature plan",
            "design",
            "plan",
            "Produce a dependency-ordered implementation plan with rollback and validation gates.",
            depends_on=["resolve_feature_dependencies"],
            required_inputs=["dependency_map"],
            produces=["implementation_plan"],
            success_condition="The user can review functions/assets to touch before mutation.",
        ),
    ]
    if not read_only:
        goals.extend([
            _goal(
                "implement_feature_changes",
                "Implement gameplay feature changes",
                "modify_code",
                "modify",
                "Apply approved code/Blueprint-support edits in the resolved owning modules.",
                depends_on=["design_feature_plan"],
                read_only=False,
                required_inputs=["implementation_plan"],
                produces=["changed_files"],
                success_condition="Feature logic is implemented without unrelated edits.",
            ),
            _goal(
                "validate_gameplay_feature",
                "Validate gameplay feature",
                "validate",
                "validate",
                "Run focused syntax/tests and define host compile/playtest checks for touched assets.",
                depends_on=["implement_feature_changes"],
                required_inputs=["changed_files"],
                produces=["validation_report"],
                success_condition="Validation evidence or explicit blockers are reported.",
            ),
        ])
    return _goal_graph(prompt, "plan" if read_only else "modify", goals)


def _dcc_tool_task_graph(prompt: str, *, read_only: bool = False) -> dict[str, Any]:
    goals = [
        _goal(
            "discover_maya_rigging_functions",
            "Discover Maya rigging functions",
            "search",
            "locate",
            "Find existing bind skin, influence, joint selection, and validation helpers.",
            produces=["rigging_function_candidates"],
        ),
        _goal(
            "inspect_ui_patterns",
            "Inspect project UI patterns",
            "search",
            "locate",
            "Find existing PySide/PyQt tool, dialog, validation, and test patterns.",
            produces=["ui_patterns"],
        ),
        _goal(
            "design_maya_tool",
            "Design Maya rigging tool",
            "design",
            "plan",
            "Map UI controls to existing rigging functions, validation states, and focused tests.",
            depends_on=["discover_maya_rigging_functions", "inspect_ui_patterns"],
            required_inputs=["rigging_function_candidates", "ui_patterns"],
            produces=["tool_plan"],
        ),
    ]
    if not read_only:
        goals.extend([
            _goal(
                "implement_maya_tool",
                "Implement Maya rigging tool",
                "modify_code",
                "modify",
                "Create or update the PySide tool and connect it to discovered rigging functions.",
                depends_on=["design_maya_tool"],
                read_only=False,
                required_inputs=["tool_plan"],
                produces=["changed_files"],
            ),
            _goal(
                "validate_maya_tool",
                "Validate Maya rigging tool",
                "validate",
                "validate",
                "Run py_compile and focused tests for selection validation and influence actions.",
                depends_on=["implement_maya_tool"],
                required_inputs=["changed_files"],
                produces=["validation_report"],
            ),
        ])
    return _goal_graph(prompt, "plan" if read_only else "modify", goals)


def _read_only_review_task_graph(prompt: str) -> dict[str, Any]:
    return _goal_graph(
        prompt,
        "locate",
        [
            _goal(
                "locate_review_targets",
                "Locate review targets",
                "search",
                "locate",
                "Find the files, functions, and symbols that own the requested behavior.",
                produces=["review_targets"],
            ),
            _goal(
                "trace_dependencies",
                "Trace dependencies and risks",
                "inspect",
                "learn",
                "Inspect call paths, dependencies, performance risks, and validation hooks.",
                depends_on=["locate_review_targets"],
                required_inputs=["review_targets"],
                produces=["risk_notes"],
            ),
            _goal(
                "report_evidence",
                "Report evidence-backed findings",
                "report",
                "explain",
                "Return findings with file/line references and no project mutation.",
                depends_on=["trace_dependencies"],
                required_inputs=["risk_notes"],
                produces=["review_report"],
            ),
        ],
    )


def _maya_create_locator_then_move_decision(text: str, *, no_execute: bool) -> PromptRouteDecision | None:
    lower = _normalize_prompt_for_routing((text or "").lower())
    if not re.search(r"\b(?:then|and then|after that)\b", lower):
        return None
    if not (re.search(r"\b(create|make|new|add)\b", lower) and "locator" in lower and re.search(r"\b(move|translate|offset|nudge)\b", lower)):
        return None
    name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?", text or "", re.IGNORECASE)
    if not name_match:
        return None
    name = name_match.group(1)
    amount = 0.0
    axis = "y"
    axis_match = re.search(r"\b(?:to|on|along|in)\s+([XYZ])\s*(-?\d+(?:\.\d+)?)\b", text or "", re.IGNORECASE)
    if axis_match:
        axis = axis_match.group(1).lower()
        amount = float(axis_match.group(2))
    else:
        amount_match = re.search(r"\b(?:up|down|left|right|forward|back|backward)?\s*(-?\d+(?:\.\d+)?)\s*(?:units?)?\b", text or "", re.IGNORECASE)
        amount = float(amount_match.group(1)) if amount_match else 0.0
        if re.search(r"\b(up|down)\b", lower):
            axis = "y"
        elif re.search(r"\b(left|right)\b", lower):
            axis = "x"
        elif re.search(r"\b(forward|back|backward)\b", lower):
            axis = "z"
        if re.search(r"\b(down|left|back|backward)\b", lower):
            amount = -abs(amount)
    translation = {
        "x": [amount, 0.0, 0.0],
        "y": [0.0, amount, 0.0],
        "z": [0.0, 0.0, amount],
    }.get(axis, [0.0, amount, 0.0])
    return PromptRouteDecision(
        route="action_graph",
        confidence=0.95,
        provider="action_graph",
        intent_category="dcc_execution",
        host="maya",
        execution_route="engine.action_graph",
        operation_mode="execute_sequence",
        target_type="dcc_action_sequence",
        target_identifier=name,
        compound_kind="sequence",
        requires_confirmation=not no_execute,
        required_context=["dcc_connection", "argument_validation"],
        model_tier="none_deterministic",
        operations=[
            {
                "id": "create_locator",
                "label": f"Create locator {name}",
                "operation": "scene.create_locator",
                "host": "maya",
                "args": {"name": name, "select": False},
                "requires_confirmation": False,
            },
            {
                "id": "move_locator",
                "label": f"Move locator {name}",
                "operation": "scene.move",
                "host": "maya",
                "args": {"objects": [name], "translation": translation, "relative": False},
                "requires_confirmation": False,
            },
        ],
        reasons=["Prompt requested an ordered Maya locator creation and move sequence."],
        rejected_routes=["target_discovery", "project_search", "dcc_execute"],
    )


def _maya_to_unreal_fbx_pipeline_decision(text: str, *, no_execute: bool) -> PromptRouteDecision | None:
    lower = _normalize_prompt_for_routing((text or "").lower())
    if not (
        "maya" in lower
        and "unreal" in lower
        and "blender" not in lower
        and "fbx" in lower
        and re.search(r"\b(pipeline|workflow|then|after|import|export)\b", lower)
        and re.search(r"\bexport(?:s|ed|ing)?\b", lower)
        and re.search(r"\bimport(?:s|ed|ing)?\b", lower)
    ):
        return None
    fbx_path_match = re.search(r"([A-Za-z]:[\\/][^\"'\s]+\.fbx)", text or "", re.IGNORECASE)
    fbx_path = (fbx_path_match.group(1) if fbx_path_match else "C:/tmp/ai_studio/maya_selected_to_unreal.fbx").replace("\\", "/")
    dest_match = re.search(r"(/Game/[A-Za-z0-9_./-]+)", text or "")
    destination_path = (dest_match.group(1) if dest_match else "/Game/AIStudio/Imported").rstrip("/")
    target_hint_match = re.search(
        r"\bselected\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:joints?|skeleton|rig)\b",
        text or "",
        re.IGNORECASE,
    )
    target_hint = (
        target_hint_match.group(1)
        if target_hint_match
        else "Manny"
        if "manny" in lower
        else ""
    )
    maya_validation_code = r"""
import json
import maya.cmds as cmds

selection = cmds.ls(selection=True, long=True) or []
if not selection:
    raise RuntimeError("Select the animated skeleton or rig hierarchy before export.")
joints = cmds.ls(selection, dag=True, type="joint", long=True) or []
if not joints:
    raise RuntimeError("The current Maya selection contains no joints.")
frame_start = float(cmds.playbackOptions(query=True, minTime=True))
frame_end = float(cmds.playbackOptions(query=True, maxTime=True))
key_count = int(cmds.keyframe(joints, query=True, keyframeCount=True) or 0)
if frame_end <= frame_start:
    raise RuntimeError("The Maya playback range is empty.")
if key_count <= 0:
    raise RuntimeError("The selected joint hierarchy has no animation keys.")
root_joint = min(joints, key=lambda item: item.count("|"))
root_values = cmds.keyframe(
    root_joint,
    attribute=("translateX", "translateY", "translateZ"),
    query=True,
    valueChange=True,
) or []
root_motion_detected = bool(root_values and (max(root_values) - min(root_values)) > 0.0001)
print(json.dumps({
    "ok": True,
    "validated_selection": selection,
    "joint_paths": joints,
    "root_joint": root_joint,
    "frame_start": frame_start,
    "frame_end": frame_end,
    "key_count": key_count,
    "root_motion_detected": root_motion_detected,
}))
""".strip()
    maya_code = r"""
import json
import os
import maya.cmds as cmds
import maya.mel as mel

selection = list(globals().get("validated_selection") or cmds.ls(selection=True, long=True) or [])
selection_source = "validated_selection" if globals().get("validated_selection") else "current_selection"
if not selection:
    fallback_roots = [name for name in ("origin", "LJ_rig") if cmds.objExists(name)]
    hierarchy = []
    for root in fallback_roots:
        hierarchy.append(root)
        hierarchy.extend(cmds.listRelatives(root, allDescendents=True, fullPath=True) or [])
    selection = list(dict.fromkeys(hierarchy))
    selection_source = "origin_and_LJ_rig_hierarchy" if selection else "whole_scene"
if selection:
    cmds.select(selection, replace=True)
else:
    cmds.select(all=True)
    selection = cmds.ls(selection=True, long=True) or []
os.makedirs(os.path.dirname(fbx_path), exist_ok=True)
if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
    cmds.loadPlugin("fbxmaya")
mel.eval("FBXResetExport;")
mel.eval("FBXExportInputConnections -v false;")
mel.eval('FBXExport -f "{}" -s;'.format(fbx_path.replace("\\", "/")))
print(json.dumps({
    "ok": True,
    "fbx_path": fbx_path,
    "selection_source": selection_source,
    "selection": selection,
    "frame_start": globals().get("frame_start"),
    "frame_end": globals().get("frame_end"),
    "root_motion_detected": globals().get("root_motion_detected"),
}))
""".strip()
    unreal_code = r"""
import json
import os
import unreal

if not os.path.exists(fbx_path):
    raise RuntimeError("FBX does not exist on disk: " + str(fbx_path))
task = unreal.AssetImportTask()
task.filename = fbx_path
task.destination_path = destination_path
task.automated = True
task.save = True
task.replace_existing = False
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
imported_paths = [str(path) for path in task.imported_object_paths]
if not imported_paths:
    raise RuntimeError("Unreal import completed without imported object paths.")
print(json.dumps({"ok": True, "fbx_path": fbx_path, "destination_path": destination_path, "asset_path": imported_paths[0], "imported_paths": imported_paths}))
""".strip()
    return PromptRouteDecision(
        route="pipeline_graph",
        confidence=0.96,
        provider="action_graph",
        intent_category="workflow_pipeline",
        host="maya",
        execution_route="engine.action_graph",
        operation_mode="compose_pipeline",
        target_type="pipeline_graph",
        execution_environment="ui_pipeline_graph",
        mutation_scope="dcc_mutation",
        required_context=["dcc_bridge_status", "workflow_graph"],
        deterministic_steps=[
            "validate Maya selection",
            "validate animation keys, frame range, and root-motion evidence",
            "export selected Maya content to FBX",
            "verify FBX exists on disk",
            "import FBX into Unreal destination path",
            "resolve the target Unreal SkeletalMesh, Skeleton, and AnimBlueprint",
            "inspect imported animation timing, root motion, and skeleton compatibility",
            "retarget incompatible animations only when required",
            "report every imported and retargeted asset with save/readback evidence",
        ],
        model_tier="none_deterministic",
        compound_kind="ordered_pipeline",
        operations=[
            {
                "id": "maya_validate_animation_export",
                "host": "maya",
                "operation": "script.run",
                "label": "Validate Maya animation export inputs",
                "args": {"code": maya_validation_code},
                "produces": [
                    "validated_selection",
                    "joint_paths",
                    "root_joint",
                    "frame_start",
                    "frame_end",
                    "key_count",
                    "root_motion_detected",
                ],
                "evidence": ["Validates selection, joints, keys, frame range, and root-motion evidence before export."],
            },
            {
                "id": "maya_export_selected_fbx",
                "host": "maya",
                "operation": "script.run",
                "label": "Maya export selected FBX",
                "args": {
                    "code": maya_code,
                    "fbx_path": fbx_path,
                    "validated_selection": "$validated_selection",
                    "frame_start": "$frame_start",
                    "frame_end": "$frame_end",
                    "root_motion_detected": "$root_motion_detected",
                },
                "requires": ["validated_selection", "frame_start", "frame_end"],
                "produces": ["fbx_path", "frame_start", "frame_end", "root_motion_detected"],
                "evidence": ["Prompt requested Maya export to FBX before Unreal import."],
            },
            {
                "id": "unreal_import_fbx",
                "host": "unreal",
                "operation": "script.run",
                "label": "Unreal import FBX",
                "args": {"code": unreal_code, "fbx_path": "$fbx_path", "destination_path": destination_path},
                "produces": ["asset_path", "imported_paths"],
                "requires": ["fbx_path"],
                "evidence": ["Uses the FBX path produced by the Maya export step."],
            },
            {
                "id": "unreal_resolve_animation_target",
                "host": "unreal",
                "operation": "animation.resolve_target",
                "label": "Resolve target Unreal skeleton and AnimBP",
                "args": {"target_hint": target_hint, "directory": "/Game/"},
                "produces": [
                    "target_skeletal_mesh_path",
                    "target_skeleton_path",
                    "target_anim_blueprint_path",
                ],
                "evidence": [
                    "Resolves a concrete target from live project assets; ambiguous or missing targets return candidates instead of guessing."
                ],
            },
            {
                "id": "unreal_validate_imported_animation",
                "host": "unreal",
                "operation": "animation.inspect_imported_pipeline",
                "label": "Validate imported animation and skeleton compatibility",
                "args": {
                    "imported_paths": "$imported_paths",
                    "target_skeleton_path": "$target_skeleton_path",
                    "target_skeletal_mesh_path": "$target_skeletal_mesh_path",
                },
                "requires": ["imported_paths", "target_skeleton_path", "target_skeletal_mesh_path"],
                "produces": [
                    "compatibility_report",
                    "animation_paths",
                    "source_skeletal_mesh_path",
                    "retarget_required",
                ],
                "evidence": [
                    "Reads imported AnimSequence duration/frame/root-motion facts and compares the source Skeleton with the resolved target."
                ],
            },
            {
                "id": "unreal_retarget_animation_if_needed",
                "host": "unreal",
                "operation": "animation.retarget_imported_if_needed",
                "label": "Retarget incompatible animation if needed",
                "args": {
                    "compatibility_report": "$compatibility_report",
                    "source_skeletal_mesh_path": "$source_skeletal_mesh_path",
                    "target_skeletal_mesh_path": "$target_skeletal_mesh_path",
                    "output_path": destination_path + "/Retargeted",
                },
                "requires": [
                    "compatibility_report",
                    "source_skeletal_mesh_path",
                    "target_skeletal_mesh_path",
                ],
                "produces": ["animation_paths", "retarget_results"],
                "evidence": ["Preserves compatible animations and retargets only sequences proven incompatible."],
            },
            {
                "id": "unreal_report_animation_pipeline_assets",
                "host": "unreal",
                "operation": "animation.report_pipeline_assets",
                "label": "Report imported and retargeted Unreal assets",
                "args": {
                    "imported_paths": "$imported_paths",
                    "animation_paths": "$animation_paths",
                    "target_skeleton_path": "$target_skeleton_path",
                    "target_anim_blueprint_path": "$target_anim_blueprint_path",
                },
                "requires": [
                    "imported_paths",
                    "animation_paths",
                    "target_skeleton_path",
                ],
                "produces": ["asset_report"],
                "evidence": ["Reports existence, class, save status, target Skeleton, AnimBP, and any failed assets."],
            },
        ],
        requires_confirmation=not no_execute,
        requires_dcc_connection=True,
        requires_generation=True,
        requires_validation=True,
        requires_execution=not no_execute,
        primary_goal="Export selected Maya content to FBX, then import that FBX into Unreal.",
        goal_type="execute" if not no_execute else "plan",
        expected_outcomes=[
            {"type": "file", "name": "fbx_path", "value": fbx_path},
            {"type": "unreal_asset", "name": "asset_path", "destination_path": destination_path},
            {"type": "validation", "name": "compatibility_report"},
            {"type": "unreal_assets", "name": "animation_paths"},
            {"type": "report", "name": "asset_report"},
        ],
        selected_route_reason="The prompt names an ordered Maya-to-Unreal FBX workflow, so it should materialize as a connected pipeline.",
        reasons=[
            "Cross-DCC ordered workflow language was detected.",
            "The Unreal step consumes the FBX path produced by the Maya step.",
        ],
        rejected_routes=["target_discovery", "project_search", "dcc_execute"],
    )


def _extract_maya_root_joint(text: str) -> str:
    match = re.search(
        r"\b(?:root\s+joint|root|skeleton\s+root)\s+(?:is|=|named|called)?\s*['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?",
        text or "",
        re.IGNORECASE,
    )
    return match.group(1).rstrip(".?!,;:") if match else "origin"


def _module_path_from_file(path: Path, project_roots: list[str]) -> str:
    for root_text in project_roots:
        try:
            root = Path(root_text).resolve()
            resolved = path.resolve()
            rel = resolved.relative_to(root)
            if rel.suffix == ".py":
                rel = rel.with_suffix("")
            return ".".join(part for part in rel.parts if part != "__init__")
        except Exception:
            continue
    if path.suffix == ".py":
        path = path.with_suffix("")
    return ".".join(path.parts[-4:])


def _find_function_node(path: Path, function_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def _required_args_from_function(node: ast.FunctionDef | ast.AsyncFunctionDef | None) -> list[str]:
    if node is None:
        return []
    args = list(node.args.posonlyargs) + list(node.args.args)
    if args and args[0].arg in {"self", "cls"}:
        args = args[1:]
    default_count = len(node.args.defaults)
    required_positional = args[: len(args) - default_count] if default_count else args
    required = [arg.arg for arg in required_positional]
    keyword_defaults = list(node.args.kw_defaults)
    for arg, default in zip(node.args.kwonlyargs, keyword_defaults):
        if default is None:
            required.append(arg.arg)
    return required


def _returned_names_from_function(node: ast.FunctionDef | ast.AsyncFunctionDef | None) -> list[str]:
    if node is None:
        return []
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        values = child.value.elts if isinstance(child.value, (ast.Tuple, ast.List)) else [child.value]
        for value in values:
            if isinstance(value, ast.Name):
                names.append(value.id)
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.append(value.value)
    return list(dict.fromkeys(names))


def _producer_score_for_args(
    *,
    producer_name: str,
    producer_node: ast.FunctionDef | ast.AsyncFunctionDef | None,
    required_args: list[str],
) -> tuple[int, list[str]]:
    returned = _returned_names_from_function(producer_node)
    doc = ast.get_docstring(producer_node) if producer_node is not None else ""
    text = " ".join([producer_name, doc or "", " ".join(returned)]).lower()
    matched = [arg for arg in required_args if arg.lower() in text or arg in returned]
    score = len(matched) * 100
    if "mapping" in producer_name and any("map" in arg for arg in required_args):
        score += 35
    if producer_name.startswith("create_") or producer_name.startswith("make_") or producer_name.startswith("build_"):
        score += 20
    return score, matched


def _discover_callable_prerequisite_chain(
    *,
    target_callable: str,
    project_roots: list[str],
    host: str,
    root_joint: str = "origin",
) -> dict[str, Any] | None:
    """Resolve target callable inputs from project functions that produce them.

    This is intentionally conservative: it only returns a chain when every
    required target argument has a named producer output backed by source
    evidence. It is generic enough to stop the rig route from being a canned
    chain, while still avoiding speculative wiring.
    """
    module_name, _, function_name = target_callable.rpartition(".")
    roots = [Path(root) for root in project_roots if root]
    if not roots:
        roots = [Path.cwd()]

    target_path: Path | None = None
    target_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    module_rel = Path(*module_name.split(".")).with_suffix(".py") if module_name else None
    candidate_target_files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if module_rel is not None:
            direct = root / module_rel
            if direct.is_file():
                candidate_target_files.append(direct)
    if not candidate_target_files:
        for root in roots:
            if root.exists():
                candidate_target_files.extend(root.rglob(f"{function_name}.py"))
                candidate_target_files.extend(root.rglob("*.py"))
    for path in candidate_target_files:
        node = _find_function_node(path, function_name)
        if node is not None:
            module_path = _module_path_from_file(path, project_roots)
            if target_callable.endswith(f"{module_path}.{function_name}") or function_name == node.name:
                target_path = path
                target_node = node
                break
    required_args = _required_args_from_function(target_node)
    if not target_path or not required_args:
        return None

    search_roots = [target_path.parent]
    if target_path.parent.name.lower() != "maya_tools":
        search_roots.append(target_path.parent / "mocap")
    candidate_files: list[Path] = []
    for search_root in search_roots:
        if search_root.exists():
            candidate_files.extend(
                path
                for path in search_root.rglob("*.py")
                if path.is_file() and path.name != "__init__.py"
            )
    candidate_files = list(dict.fromkeys(candidate_files))

    best: tuple[int, Path, ast.FunctionDef | ast.AsyncFunctionDef, list[str]] | None = None
    for path in candidate_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if path == target_path and node.name == function_name:
                continue
            score, matched = _producer_score_for_args(
                producer_name=node.name,
                producer_node=node,
                required_args=required_args,
            )
            if not matched:
                continue
            if best is None or score > best[0]:
                best = (score, path, node, matched)

    if best is None:
        return None
    _score, producer_path, producer_node, matched = best
    produced = _returned_names_from_function(producer_node)
    if not produced:
        produced = matched
    missing = [arg for arg in required_args if arg not in produced]
    if missing:
        return None

    producer_callable = f"{_module_path_from_file(producer_path, project_roots)}.{producer_node.name}"
    target_module = _module_path_from_file(target_path, project_roots)
    target_callable_resolved = f"{target_module}.{function_name}"
    producer_args: dict[str, Any] = {}
    producer_required = _required_args_from_function(producer_node)
    unsupported_producer_args = [arg for arg in producer_required if arg != "root_joint"]
    if unsupported_producer_args:
        return None
    if "root_joint" in producer_required or "root_joint" in [arg.arg for arg in producer_node.args.args]:
        producer_args["root_joint"] = root_joint

    operations: list[dict[str, Any]] = []
    if "root_joint" in producer_args:
        operations.append(
            {
                "id": "verify_root_joint",
                "label": f"Verify root joint {root_joint}",
                "operation": "scene.find_joint",
                "host": host,
                "args": {"name": root_joint},
                "requires_confirmation": False,
                "produces": ["root_joint"],
                "evidence": ["Prompt supplied a root joint required by the discovered producer function."],
            }
        )

    producer_id = producer_node.name
    operations.append(
        {
            "id": producer_id,
            "label": f"Run prerequisite producer {producer_node.name}",
            "operation": "python.call",
            "host": host,
            "callable": producer_callable,
            "args": producer_args,
            "requires_confirmation": True,
            "requires": ["root_joint"] if "root_joint" in producer_args else [],
            "produces": produced,
            "evidence": [
                f"{producer_path.as_posix()}:{producer_node.name} returns {tuple(produced)!r}",
                f"Matched required target args: {', '.join(required_args)}",
            ],
        }
    )
    operations.append(
        {
            "id": function_name,
            "label": f"Run target callable {function_name}",
            "operation": "python.call",
            "host": host,
            "callable": target_callable_resolved,
            "args": {arg: f"${arg}" for arg in required_args},
            "requires_confirmation": True,
            "requires": required_args,
            "produces": ["rig_build_state", "generated_controls"] if function_name == "create_rig_from_mapping" else ["result"],
            "evidence": [
                f"{target_path.as_posix()}:{function_name} requires {tuple(required_args)!r}",
                f"Inputs are produced by {producer_node.name}.",
            ],
        }
    )
    return {
        "target_callable": target_callable_resolved,
        "target_function": function_name,
        "target_required_args": required_args,
        "producer_callable": producer_callable,
        "producer_function": producer_node.name,
        "producer_outputs": produced,
        "operations": operations,
        "evidence": [
            f"Discovered target signature from {target_path.as_posix()}",
            f"Discovered producer returns from {producer_path.as_posix()}",
        ],
    }


def _maya_create_rig_from_current_scene_decision(
    text: str,
    *,
    no_execute: bool,
    project_roots: list[str] | None = None,
) -> PromptRouteDecision | None:
    lower = (text or "").lower()
    if "maya" not in lower:
        return None
    if not re.search(r"\b(?:create|make|build)\s+(?:a\s+)?(?:control\s+)?rig\b", lower):
        return None
    if (
        re.search(r"\b(?:for|named|called)\s+['\"]?[A-Za-z_][A-Za-z0-9_:|.-]*['\"]?\s+(?:character|mesh|asset)\b", lower)
        and not re.search(r"\b(?:current\s+scene|scene|skeleton|root\s+joint|root)\b", lower)
    ):
        return None
    root_joint = _extract_maya_root_joint(text)
    chain = _discover_callable_prerequisite_chain(
        target_callable="maya_tools.Rigging.create_rig.create_rig_from_mapping",
        project_roots=project_roots or [str(Path.cwd())],
        host="maya",
        root_joint=root_joint,
    )
    operations = chain["operations"] if chain else [
        {
            "id": "verify_root_joint",
            "label": f"Verify root joint {root_joint}",
            "operation": "scene.find_joint",
            "host": "maya",
            "args": {"name": root_joint},
            "requires_confirmation": False,
            "produces": ["root_joint"],
        },
        {
            "id": "create_rig_mapping",
            "label": f"Create rig mapping from {root_joint}",
            "operation": "python.call",
            "host": "maya",
            "callable": "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
            "args": {"root_joint": root_joint},
            "requires_confirmation": True,
            "requires": ["root_joint"],
            "produces": ["body_joint_map", "face_joint_map"],
        },
        {
            "id": "create_rig_from_mapping",
            "label": "Create rig from generated body/face maps",
            "operation": "python.call",
            "host": "maya",
            "callable": "maya_tools.Rigging.create_rig.create_rig_from_mapping",
            "args": {"body_joint_map": "$body_joint_map", "face_joint_map": "$face_joint_map"},
            "requires_confirmation": True,
            "requires": ["body_joint_map", "face_joint_map"],
            "produces": ["rig_build_state", "generated_controls"],
        },
    ]
    code = f"""
import json
import traceback

import maya.cmds as cmds
from maya_tools.Rigging.mocap import setup_hik
from maya_tools.Rigging import create_rig

root_joint = {root_joint!r}
payload = {{"root_joint": root_joint}}

try:
    if not cmds.objExists(root_joint):
        raise RuntimeError("Root joint not found: " + root_joint)
    body_joint_map, face_joint_map = setup_hik.create_rig_mapping(root_joint=root_joint)
    if not body_joint_map:
        raise RuntimeError("create_rig_mapping did not return a body_joint_map from root: " + root_joint)
    payload["body_joint_count"] = len(body_joint_map) if hasattr(body_joint_map, "__len__") else 0
    payload["face_joint_count"] = len(face_joint_map) if hasattr(face_joint_map, "__len__") else 0
    result = create_rig.create_rig_from_mapping(body_joint_map, face_joint_map)
    controls = cmds.ls("*_ctrl", type="transform") or []
    payload.update({{
        "ok": True,
        "result": str(result),
        "control_count": len(controls),
        "sample_controls": controls[:25],
        "marker": "AI_STUDIO_RIG_FROM_MAPPING_DONE",
    }})
    print(json.dumps(payload, sort_keys=True))
except Exception as exc:
    payload.update({{
        "ok": False,
        "error": str(exc),
        "traceback": traceback.format_exc(),
        "marker": "AI_STUDIO_RIG_FROM_MAPPING_FAILED",
    }})
    print(json.dumps(payload, sort_keys=True))
    raise
""".strip()
    return PromptRouteDecision(
        route="dcc_execute",
        confidence=0.96,
        provider="dcc",
        intent_category="maya_rig_from_current_scene",
        host="maya",
        callable_name="ai_studio.maya.generated.script_run",
        target_identifier="script.run",
        keyword_args={"code": code, "timeout": 180},
        operation_mode="execute",
        target_type="dcc_callable",
        execution_environment="maya",
        mutation_scope="dcc_scene_mutation",
        analysis_depth="prerequisite_graph",
        required_context=[
            "dcc_connection",
            "maya_scene_context",
            "skeleton_exists",
            "root_joint",
            "create_rig_mapping",
            "create_rig_from_mapping",
        ],
        deterministic_steps=[
            "verify_root_joint_exists",
            "call_setup_hik_create_rig_mapping",
            "pass_body_and_face_joint_maps_to_create_rig_from_mapping",
            "validate_generated_controls",
        ],
        compound_kind="prerequisite_chain",
        requires_plan=True,
        requires_confirmation=not no_execute,
        can_execute_directly=True,
        expected_outcomes=[
            {"name": "rig_script_completed", "path": "result.raw_result", "contains": "AI_STUDIO_RIG_FROM_MAPPING_DONE"},
            {"name": "root_joint_used", "path": "result.raw_result", "contains": f'"root_joint": "{root_joint}"'},
        ],
        model_tier="none_deterministic",
        operations=operations,
        reasons=[
            "Prompt asks Maya to build a rig for the current scene.",
            f"Resolved prerequisite root joint to `{root_joint}`.",
            (
                "Generic prerequisite resolver discovered create_rig_from_mapping requires "
                "body_joint_map and face_joint_map, and create_rig_mapping produces them."
                if chain
                else "Fallback prerequisite chain used because generic callable discovery did not return a complete chain."
            ),
        ],
        semantic_execution_contract={
            "dependency_resolution": chain or {},
            "resolution_strategy": "callable_signature_to_producer_outputs",
        },
        rejected_routes=["dcc_query", "project_search", "target_discovery"],
    )


def _has_file_ref(text: str) -> bool:
    return bool(re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", text or ""))


def _extract_explicit_scope_path(text: str) -> str:
    """Extract an explicitly written file or directory path from the prompt."""
    match = re.search(
        r"(?P<path>(?:[A-Za-z]:[\\/]|[.]{1,2}[\\/]|/)[^\n\r:*?\"<>|]+?)"
        r"(?=\s*(?:$|[?.!,;]|\b(?:and|but|that|which|where|under|inside|within|"
        r"are|aren['’]?t|is|isn['’]?t|was|were|not|never)\b))",
        text or "",
        re.IGNORECASE,
    )
    return match.group("path").strip().rstrip(".?!,; ") if match else ""


def _is_unimported_files_query(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        re.search(
            r"\b(?:what|which|list|show|find|check)?\s*(?:files?|modules?)\s+"
            r"(?:(?:are|is)\s+)?(?:not|never)\s+(?:being\s+)?imported\b|"
            r"\b(?:what|which|list|show|find|check)?\s*(?:files?|modules?)\s+"
            r"(?:aren['’]?t|isn['’]?t)\s+imported\b|"
            r"\bunimported\s+(?:files?|modules?)\b",
            lower,
        )
    )


def _callable_after_execution_verb(text: str) -> str:
    match = re.search(r"\b(?:run|execute|call|launch|test)\s+([A-Za-z_][A-Za-z0-9_]*)\b", text or "", re.IGNORECASE)
    if match and match.group(1).lower() not in {"the", "a", "an", "this", "that"}:
        return match.group(1)
    match = re.search(r"\b(unreal_tools(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b", text or "")
    if match:
        return match.group(1)
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*)\b", text or "")
    return match.group(1) if match else ""


def _explicit_source_file_references(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|pyi|cpp|cc|c|h|hpp|cs|qml|ui)\b", text or "", re.IGNORECASE)


def _is_explicit_source_code_mutation(text: str, lower: str) -> bool:
    """Hard precedence guard: an explicitly named source file plus code mutation is a project edit.

    Live execution verbs intentionally disqualify this guard so prompts such as
    `run create_rig_from_mapping in Maya` still reach DCC execution.
    """
    source_files = _explicit_source_file_references(text)
    if not source_files:
        return False
    if re.search(r"\b(run|execute|call|launch|perform)\b", lower or ""):
        return False
    mutation = re.search(
        r"\b(add|edit|modify|change|update|refactor|improve|fix|patch|implement|write|insert|rename|remove|delete|document|wire)\b",
        lower or "",
    )
    code_object = re.search(
        r"\b(code|helper|function|method|class|module|docstring|variable|handler|ui|button|test|tests|import|logic|line|symbol|name)\b",
        lower or "",
    )
    # An explicit source filename already supplies the code target. Commands such
    # as "rename _get_joint in create_rig.py" should not require the user to also
    # say function/symbol.
    return bool(mutation and (code_object or source_files))


def _route_candidate_diagnostics(text: str, lower: str, *, host: str, hosts: list[str]) -> list[dict[str, Any]]:
    """Cheap explainable route scores used for diagnostics and future ranker migration."""
    candidates = {
        "target_discovery": {"score": 0.0, "reasons": []},
        "dcc_execute": {"score": 0.0, "reasons": []},
        "pipeline_graph": {"score": 0.0, "reasons": []},
        "project_search": {"score": 0.0, "reasons": []},
        "chat": {"score": 0.1, "reasons": ["fallback route"]},
    }
    from tech_connector.services.project_service import is_target_discovery_edit_request

    if _is_explicit_source_code_mutation(text, lower):
        candidates["target_discovery"]["score"] += 1.0
        candidates["target_discovery"]["reasons"].append("explicit source file plus code mutation")
    if is_target_discovery_edit_request(text):
        candidates["target_discovery"]["score"] += 0.9
        candidates["target_discovery"]["reasons"].append("target discovery edit request")
    if _explicit_source_file_references(text):
        candidates["target_discovery"]["score"] += 0.45
        candidates["project_search"]["score"] += 0.25
    if host and re.search(r"\b(run|execute|call|launch|select|move|rotate|scale|create|delete|set)\b", lower):
        candidates["dcc_execute"]["score"] += 0.72
        candidates["dcc_execute"]["reasons"].append(f"host operation language for {host}")
    if len(hosts) >= 2 or re.search(r"\b(pipeline|workflow|multi-dcc|cross-dcc|compose|sequence)\b", lower):
        candidates["pipeline_graph"]["score"] += 0.8
        candidates["pipeline_graph"]["reasons"].append("explicit workflow or pipeline language")
    if _looks_like_read_only_project_question(lower):
        candidates["project_search"]["score"] += 0.7
        candidates["project_search"]["reasons"].append("read-only project fact language")
    return [
        {"route": route, "score": round(float(data["score"]), 3), "reasons": list(data["reasons"])}
        for route, data in sorted(candidates.items(), key=lambda item: item[1]["score"], reverse=True)
    ]


def _rank_route_candidates_with_fnn(
    text: str,
    candidates: list[dict[str, Any]],
    *,
    host: str,
    hosts: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from tech_connector.game_engine.integration.dcc_operation_service import dcc_prompt_to_operation
        from tech_connector.services.reasoning.request_understanding_fnn_service import SUPPORTED_DCC_HOSTS, score_prompt_routes

        registered_dcc_hint = bool(host in SUPPORTED_DCC_HOSTS and dcc_prompt_to_operation(host, text))
        result = score_prompt_routes(text, host=host, hosts=hosts, registered_dcc_hint=registered_dcc_hint)
    except Exception:
        return candidates, {}
    by_route = {str(item.get("route") or ""): dict(item) for item in candidates}
    for item in result.scores:
        row = by_route.get(item.route) or {"route": item.route, "score": 0.0, "reasons": []}
        row["fnn_score"] = item.score
        row["fnn_reasons"] = list(item.reasons)
        # Keep deterministic score primary, but let the FNN signal break close ties.
        row["combined_score"] = round(float(row.get("score") or 0.0) + float(item.score) * 0.25, 4)
        by_route[item.route] = row
    ranked = sorted(by_route.values(), key=lambda row: float(row.get("combined_score", row.get("score", 0.0)) or 0.0), reverse=True)
    return ranked, result.to_dict()


def _looks_like_read_only_project_question(lower: str) -> bool:
    if not re.search(
        r"\b(what|which|where|list|show|find|file|path|how many|arguments|args|required|dependencies|classes|functions|methods)\b",
        lower or "",
    ):
        return False
    if re.search(r"\b(run|execute|call|launch|do it|perform|apply|modify scene|in the scene)\b", lower or ""):
        return False
    if re.search(r"\b(add|create|write|generate|implement|insert|modify|update|fix|patch|wire|connect|build)\b", lower or "") and not re.search(
        r"\b(what|which|where|list|show|find|how many|arguments|args|required|dependencies|classes|functions|methods)\b",
        lower or "",
    ):
        return False
    return bool(
        re.search(r"\b(file|files|path|python|py|function|functions|method|methods|class|classes|symbol|symbols|project|code|script|tool|tools|argument|arguments|args|caller|callers|callee|callees)\b", lower or "")
        or re.search(r"\b(can|could|would)\s+i\s+(?:use\s+)?(?:create|make|build)\b", lower or "")
    )


def _is_connection_status_question(lower: str) -> bool:
    text = lower or ""
    if re.search(r"\b(connect|connection|connected|status|health|up|online|available|running)\b", text) is None:
        return False
    if re.search(r"\b(compile|create|make|add|edit|modify|run|execute|import|export|spawn|duplicate)\b", text):
        return False
    if re.search(r"\b(?:is|are|am)\b.*\b(?:up|online|available|running|connected)\b", text):
        return True
    if re.search(r"\b(testing connection|test connection|connection status|am i connected|are we connected|what am i connected to|what is connected)\b", text):
        return True
    if re.fullmatch(r"\s*(?:am i )?connected\s*\??\s*", text):
        return True
    if re.fullmatch(r"\s*(?:status|health)\s*\??\s*", text):
        return True
    return False


def _is_simple_project_fact_question(lower: str) -> bool:
    """Small deterministic lookups should not trigger expert planning scaffolds."""
    text = lower or ""
    if not re.search(
        r"\b(what|which|where|list|show|find|how many|arguments?|args?|required|functions?|methods?|classes?|symbols?|callers?|usages?|references?)\b",
        text,
    ):
        return False
    if re.search(
        r"\b(add|write|implement|insert|modify|update|fix|patch|wire|connect|refactor|delete|remove|execute|run|apply)\b",
        text,
    ):
        return False
    if re.search(r"\b(create|build|generate|make)\b", text) and not re.search(
        r"\b(what|which|where|list|show|find)\b.*\b(functions?|methods?|classes?|symbols?|files?|paths?)\b",
        text,
    ):
        return False
    return bool(
        re.search(r"\b(functions?|methods?|classes?|symbols?|files?|path|arguments?|args?|required|callers?|callees|usages?|references?|imports?|dependencies)\b", text)
        or re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", text)
    )


def _has_explicit_dcc_mutation(lower: str) -> bool:
    return bool(re.search(
        r"\b(move|translate|rotate|scale|select|frame|create|make|build|spawn|delete|remove|set|modify|change|connect|disconnect|assign|bind|skin|constrain|parent\s+constrain|orient\s+constrain|point\s+constrain)\b",
        lower or "",
    ))


def _has_explicit_dcc_operation(lower: str) -> bool:
    return bool(
        _has_explicit_dcc_mutation(lower)
        or re.search(r"\b(run|execute|call|launch|perform|export|import|bake|render|simulate|cook)\b", lower or "")
    )


def _simple_project_fact_progress() -> dict[str, Any]:
    return {
        "framework": "visible_prompt_progress_v1",
        "enabled": True,
        "progress_mode": "terse",
        "stages": [
            {
                "index": 1,
                "total": 2,
                "state": "working",
                "label": "Searching project facts",
                "message": "Checking the active file and local index.",
                "stop_when": "A direct symbol or file answer is available.",
            },
            {
                "index": 2,
                "total": 2,
                "state": "done",
                "label": "Answer ready",
                "message": "Returning the direct project answer.",
                "stop_when": "Answer is rendered in chat.",
            },
        ],
    }


def _is_unreal_live_query(lower: str) -> bool:
    if "unreal" not in lower and "ue5" not in lower and "ue4" not in lower and "unreal_tools" not in lower:
        return False
    if re.search(r"\b(create|make|build|spawn|duplicate|delete|remove|set|modify|change|compile|save|write)\b", lower):
        return False
    query_words = re.search(r"\b(what|which|show|list|get|inspect|scan|find|current|loaded|active|selected|where)\b", lower)
    unreal_terms = re.search(
        r"\b(selection|selected|actor|actors|asset|assets|level|world|blueprint|blueprints|skeleton|skeletons|mesh|meshes|static mesh|"
        r"animation|animations|plugin|plugins|component|components|project|snapshot|reference|references|dependency|dependencies|"
        r"control rig|anim blueprint|niagara|physics|material|materials)\b",
        lower,
    )
    return bool(query_words and unreal_terms)


def _known_unreal_operation_from_text(text: str) -> dict[str, Any]:
    lower = (text or "").lower()
    try:
        from tech_connector.services.unreal.unreal_operation_service import (
            UNREAL_OPERATIONS,
            extract_unreal_asset_name,
            extract_unreal_package_like_path,
            build_unreal_editable_character_fx_params,
            unreal_navigation_operation_from_text,
            unreal_prompt_to_operation,
        )
    except Exception:
        UNREAL_OPERATIONS = {}
        extract_unreal_asset_name = None
        extract_unreal_package_like_path = None
        build_unreal_editable_character_fx_params = None
        unreal_navigation_operation_from_text = None
        unreal_prompt_to_operation = None
    navigation_context = bool(
        re.search(r"\b(unreal|ue5|ue4|blueprint|anim blueprint|control rig|asset|assets)\b", lower)
        or re.search(r"/game/", lower)
        or re.search(r"\b(?:bp|abp|sk|sm|mi|m|cr|pa|ne)_[A-Za-z0-9_]+\b", text or "")
    )
    if navigation_context and callable(unreal_navigation_operation_from_text):
        navigation_key, navigation_params = unreal_navigation_operation_from_text(text)
        if navigation_key and navigation_key in UNREAL_OPERATIONS:
            op = UNREAL_OPERATIONS[navigation_key]
            return {
                "operation_key": navigation_key,
                "function": str(getattr(op, "function", "") or ""),
                "mutates_project": bool(getattr(op, "mutates_project", False)),
                "required": [
                    name for name in list(getattr(op, "required", ()) or ())
                    if not dict(navigation_params or {}).get(name)
                ],
                "keyword_args": dict(navigation_params or {}),
            }
    inspect_blueprint_context = bool(
        re.search(r"\b(inspect|scan|list|show|get)\b", lower)
        and re.search(r"\b(blueprint|graphs?|variables?|components?|bp_[A-Za-z0-9_]+)\b", lower)
    )
    inferred_key = unreal_prompt_to_operation(text) if callable(unreal_prompt_to_operation) else ""
    if inspect_blueprint_context and "blueprint.scan" in UNREAL_OPERATIONS:
        inferred_key = "blueprint.scan"
    if inferred_key and inferred_key in UNREAL_OPERATIONS:
        op = UNREAL_OPERATIONS[inferred_key]
        keyword_args: dict[str, Any] = {}
        if inferred_key == "niagara.attach_editable_character_fx" and callable(build_unreal_editable_character_fx_params):
            keyword_args.update(build_unreal_editable_character_fx_params(text))
        if inferred_key in {"assets.inspect", "blueprint.scan", "navigation.open_asset"}:
            asset_ref = ""
            if callable(extract_unreal_package_like_path):
                asset_ref = str(extract_unreal_package_like_path(text) or "")
            if not asset_ref and callable(extract_unreal_asset_name):
                asset_ref = str(extract_unreal_asset_name(text) or "")
            if asset_ref:
                keyword_args["asset_path"] = asset_ref
        return {
            "operation_key": inferred_key,
            "function": str(getattr(op, "function", "") or ""),
            "mutates_project": bool(getattr(op, "mutates_project", False)),
            "required": [
                name for name in list(getattr(op, "required", ()) or ())
                if not keyword_args.get(name)
            ],
            "keyword_args": keyword_args,
        }
    for key, op in UNREAL_OPERATIONS.items():
        function = str(getattr(op, "function", "") or "")
        label = str(getattr(op, "label", "") or "")
        if key.lower() in lower or (function and function.lower() in lower) or (label and label.lower() in lower):
            return {
                "operation_key": key,
                "function": function,
                "mutates_project": bool(getattr(op, "mutates_project", False)),
                "required": list(getattr(op, "required", ()) or ()),
                "keyword_args": {},
            }
    callable_name = _callable_after_execution_verb(text)
    if callable_name.startswith("unreal_tools."):
        return {
            "operation_key": "",
            "function": callable_name,
            "mutates_project": bool(re.search(r"\b(create|spawn|duplicate|delete|remove|set|modify|compile|save)\b", lower)),
            "required": [],
            "keyword_args": {},
        }
    return {}


def _has_no_execute_guard(lower: str) -> bool:
    return bool(
        re.search(
            r"\b(do not|don't|dont|never)\s+(run|execute|call|launch|apply|change|modify|edit|write|save)\b",
            lower,
        )
        or re.search(r"\b(just|only)\s+(show|explain|preview|plan)\b", lower)
        or re.search(r"\b(not an edit|no edit|no edits|not editing|don't mutate|dont mutate|do not mutate|no wait just explain|example only|explain the fix)\b", lower)
    )


def _is_scoped_project_guidance_request(lower: str) -> bool:
    return bool(
        _has_no_execute_guard(lower)
        and re.search(r"\b(qslider|slider|widget|class|helper|example)\b", lower)
        and re.search(
            r"\b@[A-Za-z_][A-Za-z0-9_.]*|custom_widgets(?:\.py)?|custom_qt(?:[./\\]custom_widgets)?\b",
            lower,
        )
        and not re.search(r"\b(plan|strategy|outline|propose|design|implementation\s+plan|plan\s+first)\b", lower)
    )


def _detect_compound_kind(lower: str) -> str:
    if re.search(r"\b(first|then|and then|before|after)\b", lower):
        if re.search(r"\b(find|check|analyze|inspect|diagnose|review)\b", lower) and re.search(r"\b(fix|fixing|change|edit|update|clean up|cleanup|refactor)\b", lower):
            return "analysis_then_mutation"
        return "sequence"
    if re.search(r"\b(and|plus)\b", lower) and re.search(r"\b(open|find|run|execute|edit|fix|create|connect|validate)\b", lower):
        return "sequence"
    return "atomic"


def _compound_operations(lower: str, route: str, mode: str) -> list[dict[str, Any]]:
    kind = _detect_compound_kind(lower)
    if kind == "analysis_then_mutation":
        return [
            {"route": "project_search", "operation_mode": "analyze", "requires_confirmation": False},
            {"route": route, "operation_mode": mode or "edit", "requires_confirmation": True},
        ]
    if kind == "sequence":
        return [{"route": route, "operation_mode": mode or "plan", "requires_confirmation": False}]
    return []


def _is_generated_maya_rig_control_post_action(host: str, operation_key: str, text: str, params: dict[str, Any]) -> bool:
    if host != "maya" or operation_key not in {"scene.move", "scene.select", "navigation.frame_selection"}:
        return False
    lower = (text or "").lower()
    objects = [str(obj) for obj in params.get("objects") or []]
    if not objects:
        direct = re.search(r"\b([A-Za-z_][A-Za-z0-9_:|.-]*(?:_ctrl|Ctrl|CTRL))\b", text or "")
        if direct:
            objects = [direct.group(1)]
    generated_control_targets = [
        obj for obj in objects
        if obj.lower().endswith("_ctrl") or obj.lower() in {"pelvis_ctrl", "hip_ctrl", "root_ctrl"}
    ]
    if not generated_control_targets:
        return False
    if re.search(r"\b(select only|just select|only select)\b", lower):
        return False
    return True


def _is_unreal_graph_operation_planning_request(lower: str) -> bool:
    text = lower or ""
    if "unreal" not in text and not re.search(r"\b(?:bp|abp|bpc|niagara|control rig|metasound|pcg)\b", text):
        return False
    if not re.search(r"\b(graph|event\s*graph|eventgraph|anim\s*graph|animgraph|blueprint|node|nodes|pin|pins|operation|operations)\b", text):
        return False
    if not re.search(r"\b(report|show|list|what|which|available|possible|plan|preview|inspect|explain)\b", text):
        return False
    return bool(re.search(r"\b(add|adding|insert|connect|rewire|modify|edit|create|print string|reroute)\b", text))


def _maya_rigging_prerequisite_decision(
    *,
    host: str,
    operation_key: str,
    op_function: str,
    text: str,
    params: dict[str, Any],
    no_execute: bool,
) -> PromptRouteDecision | None:
    if not _is_generated_maya_rig_control_post_action(host, operation_key, text, params):
        return None
    objects = list(params.get("objects") or [])
    target_control = str(objects[0]) if objects else "requested control"
    return PromptRouteDecision(
        route="action_graph",
        confidence=0.93,
        provider="action_graph",
        intent_category="maya_rigging_prerequisite_plan",
        host="maya",
        callable_name=op_function,
        target_identifier=operation_key,
        keyword_args=dict(params),
        operation_mode="approve_prerequisites_then_execute",
        target_type="maya_rig_control",
        execution_environment="maya_scene",
        mutation_scope="dcc_scene_mutation",
        analysis_depth="prerequisite_graph",
        required_context=[
            "dcc_connection",
            "maya_scene_context",
            "skeleton_exists",
            "root_joint_origin",
            "hik_mapping_state",
            "rig_build_state",
            "target_control_exists",
        ],
        deterministic_steps=[
            "check_maya_connection",
            "verify_target_control_exists",
            "verify_skeleton_root_origin",
            "check_hik_mapping_from_origin",
            "check_rig_or_control_rig_exists",
            "verify_target_control_after_prerequisites",
            "execute_requested_control_action",
        ],
        compound_kind="prerequisite_chain",
        requires_plan=True,
        requires_confirmation=not no_execute,
        can_execute_directly=False,
        model_tier="none_deterministic",
        operations=[
            {
                "id": "verify_target_control",
                "label": f"Check whether {target_control} already exists",
                "operation": "scene.object_exists",
                "host": "maya",
                "args": {"name": target_control},
                "requires_confirmation": False,
                "produces": ["target_control_exists", "target_control_missing"],
            },
            {
                "id": "requested_post_requisite_action",
                "label": f"Run requested action on existing {target_control}",
                "operation": operation_key,
                "host": "maya",
                "args": dict(params),
                "requires_confirmation": True,
                "condition": "target_control_exists",
                "requires": ["target_control_exists"],
            },
            {
                "id": "verify_skeleton_origin",
                "label": "Verify skeleton root joint",
                "operation": "scene.find_joint",
                "host": "maya",
                "args": {"name": "origin"},
                "requires_confirmation": False,
                "condition": "target_control_missing",
                "produces": ["skeleton_exists", "root_joint_origin"],
            },
            {
                "id": "create_hik_mapping_if_missing",
                "label": "Create HIK mapping from origin if missing",
                "operation": "python.call",
                "host": "maya",
                "callable": "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
                "args": {"root_joint": "origin"},
                "requires_confirmation": True,
                "condition": "skeleton_exists and hik_mapping_missing",
                "produces": ["body_joint_map", "face_joint_map"],
                "evidence": [
                    "maya_tools/Rigging/mocap/setup_hik.py:create_rig_mapping(root_joint=None) returns (body_joint_map, face_joint_map)",
                ],
            },
            {
                "id": "create_rig_if_missing",
                "label": "Create rig/control rig if missing",
                "operation": "python.call",
                "host": "maya",
                "callable": "maya_tools.Rigging.create_rig.create_rig_from_mapping",
                "args": {"body_joint_map": "$body_joint_map", "face_joint_map": "$face_joint_map"},
                "requires_confirmation": True,
                "condition": "skeleton_exists and target_control_missing",
                "requires": ["body_joint_map", "face_joint_map"],
                "produces": ["rig_build_state", "generated_controls"],
                "execution_notes": [
                    "Run through Maya commandPort/Python so mobile/remote execution does not depend on blocking UI popups.",
                    "After this callable returns, verify the requested control exists before running the post-requisite action.",
                ],
                "evidence": [
                    "maya_tools/Rigging/create_rig.py:create_rig_from_mapping(body_joint_map, face_joint_map)",
                ],
            },
            {
                "id": "verify_target_control_after_prerequisites",
                "label": f"Verify {target_control} exists after prerequisite setup",
                "operation": "scene.object_exists",
                "host": "maya",
                "args": {"name": target_control},
                "requires_confirmation": False,
                "requires": ["rig_build_state"],
            },
            {
                "id": "requested_post_requisite_action_after_prerequisites",
                "label": f"Run requested action on generated {target_control}",
                "operation": operation_key,
                "host": "maya",
                "args": dict(params),
                "requires_confirmation": True,
                "condition": "target_control_missing and target_control_exists_after_prerequisites",
                "requires": ["target_control_exists_after_prerequisites"],
            },
        ],
        missing_info=["approval_to_create_hik_mapping_and_rig_if_missing"],
        reasons=[
            "Prompt targets a likely generated Maya rig control, so the requested action depends on skeleton/HIK/rig prerequisites.",
            "If the skeleton exists but the rig/control does not, prerequisite automation must be approved before the final post-requisite action.",
        ],
        rejected_routes=["dcc_execute", "project_search"],
    )



def decision_requires_live_dcc(decision: PromptRouteDecision | dict[str, Any] | None) -> bool:
    """Return True only when the current request genuinely needs a live DCC.

    A DCC host hint narrows project search and expert context. It does not by
    itself justify launching a DCC/MCPHost session.
    """
    if decision is None:
        return False
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})

    if not bool(data.get("requires_dcc_connection")):
        return False

    operation_mode = str(data.get("operation_mode") or "").lower()
    route = str(data.get("route") or "").lower()
    execution_route = str(data.get("execution_route") or "").lower()

    if operation_mode in {"execute", "prototype", "navigate", "query"}:
        return route in {"dcc_execute", "dcc_prototype", "dcc_query", "unreal_capability"}

    return execution_route in {
        "dcc.execution_pipeline",
        "dcc.prototype_pipeline",
        "dcc.scene_query",
        "unreal.capability_pipeline",
    }


def decision_is_project_only(decision: PromptRouteDecision | dict[str, Any] | None) -> bool:
    """Return True when all current goals can be satisfied without a live host."""
    if decision is None:
        return False
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    if bool(data.get("requires_execution")):
        return False

    route = str(data.get("route") or "").lower()
    provider = str(data.get("provider") or "").lower()
    goal_type = str(data.get("goal_type") or "").lower()
    mutation_scope = str(data.get("mutation_scope") or "").lower()
    graph = dict(data.get("task_graph") or data.get("goal_graph") or {})
    goals = list(graph.get("goals") or graph.get("tasks") or [])

    project_routes = {
        "project_search",
        "quality_audit",
        "project_health",
        "target_discovery",
        "chat",
    }
    project_providers = {
        "project_search",
        "project_health",
        "target_discovery",
        "llm",
    }
    non_live_actions = {
        "search",
        "inspect",
        "design",
        "generate",
        "report",
        "validate",
        "approval",
        "respond",
    }

    if goals:
        actions = {
            str(goal.get("action") or "").lower()
            for goal in goals
            if isinstance(goal, dict)
        }
        if actions and actions.issubset(non_live_actions):
            return True

    if route in project_routes or provider in project_providers:
        return mutation_scope != "dcc_scene_mutation"

    return goal_type in {"locate", "learn", "explain", "compare", "generate", "respond", "plan"}

def _finalize_decision(decision: PromptRouteDecision, lower: str) -> PromptRouteDecision:
    canonical_context = dict(getattr(decision, "execution_context", {}) or {})
    canonical_progress = dict(canonical_context.get("visible_progress") or {})
    canonical_reasoning = dict(canonical_context.get("reasoning_pipeline") or {})
    if not decision.route_candidates:
        decision.route_candidates = []
    if not decision.selected_route_reason and decision.reasons:
        decision.selected_route_reason = str(decision.reasons[0])
    route_defaults: dict[str, dict[str, Any]] = {
        "project_health": {
            "execution_route": "engine.project_health",
            "handler_id": "ProjectHealthProvider",
            "operation_mode": "analyze",
            "target_type": "project",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "graph",
            "context_resolvers": ["dependency_graph", "call_graph", "symbol_index"],
            "deterministic_steps": ["load_project_index", "query_dependency_graph", "format_health_result"],
            "model_capability": "none",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "quality_audit": {
            "execution_route": "engine.project_search",
            "handler_id": "ProjectSearchProvider",
            "operation_mode": "audit",
            "target_type": "code",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "semantic",
            "context_resolvers": ["symbol_index", "call_graph", "code_chunks"],
            "deterministic_steps": ["gather_indexed_evidence", "rank_relevant_symbols", "summarize_evidence"],
            "model_capability": "local_code",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "target_discovery": {
            "execution_route": "engine.target_discovery",
            "handler_id": "TargetDiscoveryEditProvider",
            "operation_mode": "edit",
            "target_type": "code",
            "execution_environment": "project_source",
            "mutation_scope": "file_modification",
            "analysis_depth": "semantic",
            "context_resolvers": ["target_discovery", "symbol_index", "code_chunks"],
            "deterministic_steps": ["discover_targets", "rank_candidates", "build_grounded_edit_prompt"],
            "model_capability": "local_code",
            "risk_level": "medium",
            "requires_plan": True,
            "requires_fresh_index": True,
        },
        "pipeline_graph": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "compose_pipeline",
            "target_type": "pipeline_graph",
            "execution_environment": "ui_pipeline_graph",
            "mutation_scope": "local_reversible_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["project_index", "symbol_index", "workflow_graph"],
            "deterministic_steps": ["resolve_symbols", "create_nodes", "bind_literals", "connect_data", "connect_flow", "validate_graph"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
            "can_execute_directly": True,
        },
        "action_graph": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "plan_actions",
            "target_type": "action_graph",
            "execution_environment": "ai_studio",
            "mutation_scope": "local_reversible_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["project_index", "symbol_index"],
            "deterministic_steps": ["compile_action_graph", "validate_actions"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
            "can_execute_directly": True,
        },
        "project_search": {
            "execution_route": "engine.project_search",
            "handler_id": "ProjectSearchProvider",
            "operation_mode": "search",
            "target_type": "project",
            "execution_environment": "project_index",
            "mutation_scope": "read_only",
            "analysis_depth": "index",
            "context_resolvers": ["project_index", "symbol_index"],
            "deterministic_steps": ["query_project_index", "answer_from_indexed_facts"],
            "model_capability": "none_or_local_fast",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "connection_status": {
            "execution_route": "engine.connection_status",
            "handler_id": "ConnectionStatusProvider",
            "operation_mode": "status",
            "target_type": "connected_applications",
            "execution_environment": "ui_context",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": ["cached_status_cards", "connected_account_settings"],
            "deterministic_steps": ["read_cached_connection_status", "format_status_result"],
            "model_capability": "none",
            "risk_level": "low",
            "can_execute_directly": True,
        },
        "dcc_execute": {
            "execution_route": "dcc.execution_pipeline",
            "handler_id": "CommandRouter.execute_dcc_editor_operation",
            "operation_mode": "execute",
            "target_type": "dcc_callable",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["dcc_connection", "resolved_callable", "argument_validation"],
            "deterministic_steps": ["resolve_callable", "validate_arguments", "confirm_execution", "execute_dcc"],
            "model_capability": "none",
            "risk_level": "high",
            "requires_dcc_connection": True,
        },
        "dcc_query": {
            # Live host-state queries are distinct from scene mutation. Keeping
            # them off dcc.execution_pipeline prevents read-only DCC queries
            # from being treated as generic execution requests by the chat UI.
            "execution_route": "dcc.scene_query",
            "handler_id": "DCCExecutionHandler",
            "operation_mode": "query",
            "target_type": "dcc_scene_query",
            "execution_environment": "dcc_host",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": ["dcc_connection", "scene_context"],
            "deterministic_steps": [
                "check_connection",
                "execute_read_only_query_adapter",
                "format_query_result",
            ],
            "model_capability": "none",
            "risk_level": "low",
            "requires_dcc_connection": True,
            "can_execute_directly": True,
        },
        "unreal_capability": {
            "execution_route": "unreal.capability_pipeline",
            "handler_id": "CommandRouter.plan_unreal_request",
            "operation_mode": "execute_or_inspect",
            "target_type": "unreal_capability",
            "execution_environment": "unreal",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "graph",
            "context_resolvers": ["unreal_reflection_index", "capability_graph", "argument_validation"],
            "deterministic_steps": ["search_capabilities", "resolve_function", "validate_arguments", "confirm_if_mutating", "execute_unreal"],
            "model_capability": "none",
            "risk_level": "high",
            "requires_dcc_connection": True,
            "requires_fresh_index": True,
        },
        "dcc_prototype": {
            "execution_route": "dcc.prototype_pipeline",
            "handler_id": "CommandRouter.execute_dcc_editor_operation",
            "operation_mode": "prototype",
            "target_type": "dcc_scene_or_tool",
            "mutation_scope": "dcc_scene_mutation",
            "analysis_depth": "semantic",
            "context_resolvers": ["dcc_connection", "scene_context", "capability_graph"],
            "deterministic_steps": ["gather_scene_context", "plan_prototype", "confirm_execution"],
            "model_capability": "local_code",
            "risk_level": "high",
            "requires_dcc_connection": True,
            "requires_plan": True,
        },
        "function_execution": {
            "execution_route": "engine.action_graph",
            "handler_id": "ActionGraphProvider",
            "operation_mode": "execute",
            "target_type": "function",
            "execution_environment": "unknown",
            "mutation_scope": "unknown",
            "analysis_depth": "graph",
            "context_resolvers": ["symbol_index", "callable_metadata"],
            "deterministic_steps": ["resolve_function", "ask_for_execution_environment", "validate_arguments"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
        },
        "github_ingest": {
            "execution_route": "ui.github_import",
            "handler_id": "MainWindow.trigger_web_import",
            "operation_mode": "ingest",
            "target_type": "repository",
            "execution_environment": "external_repository",
            "mutation_scope": "persistent_local_mutation",
            "analysis_depth": "index",
            "context_resolvers": ["github_search", "index_repository"],
            "deterministic_steps": ["open_import_ui", "select_repository", "ingest_repository", "index_repository"],
            "model_capability": "none_or_local_fast",
            "risk_level": "medium",
            "requires_plan": True,
        },
        "chat": {
            "execution_route": "llm.chat",
            "handler_id": "ai_router.route_prompt",
            "operation_mode": "chat",
            "target_type": "conversation",
            "execution_environment": "model",
            "mutation_scope": "read_only",
            "analysis_depth": "none",
            "context_resolvers": [],
            "deterministic_steps": ["route_model"],
            "model_capability": "local_fast",
            "risk_level": "low",
            "can_execute_directly": True,
        },
    }
    defaults = route_defaults.get(decision.route, {})
    list_defaults_that_may_overwrite_when_empty = {"context_resolvers", "deterministic_steps"}
    protected_defaults = {"operations", "required_context", "missing_info", "reasons", "rejected_routes", "alternatives"}
    for key, value in defaults.items():
        if key in protected_defaults:
            continue
        current = getattr(decision, key, None)
        empty_list_allowed = key in list_defaults_that_may_overwrite_when_empty and current == []
        if (current in ("", None, False) or empty_list_allowed) and key not in {"requires_plan", "requires_fresh_index", "requires_dcc_connection", "can_execute_directly"}:
            setattr(decision, key, value)
        elif key in {"requires_plan", "requires_fresh_index", "requires_dcc_connection", "can_execute_directly"} and not getattr(decision, key):
            setattr(decision, key, bool(value))
    if decision.host and not decision.execution_environment:
        decision.execution_environment = decision.host
    if decision.host and not decision.search_scopes:
        if decision.host == "unreal":
            decision.search_scopes = ["project", "external_tools", "unreal_engine"]
            decision.index_filters = {
                "scope": "unreal_project",
                "host": "unreal",
                "source_scopes": ["project", "external_tools", "unreal_engine"],
            }
            if "host_scoped_index" not in decision.context_resolvers:
                decision.context_resolvers.append("host_scoped_index")
            decision.reasons.append("Host hint `unreal` narrows index searches to project/general Python plus Unreal-related code.")
        elif decision.host == "maya":
            decision.search_scopes = ["project", "external_tools", "maya"]
            decision.index_filters = {
                "scope": "maya_project",
                "host": "maya",
                "source_scopes": ["project", "external_tools", "maya"],
            }
            if "host_scoped_index" not in decision.context_resolvers:
                decision.context_resolvers.append("host_scoped_index")
            decision.reasons.append("Host hint `maya` narrows index searches to project/general Python plus Maya-related code.")
        else:
            decision.search_scopes = ["project", "external_tools"]
            decision.index_filters = {
                "scope": f"{decision.host}_project",
                "host": decision.host,
                "source_scopes": ["project", "external_tools"],
            }
    if _has_no_execute_guard(lower):
        read_only_navigation = (
            decision.route == "unreal_capability"
            and decision.target_type == "dcc_navigation"
            and str(decision.target_identifier or "").startswith("navigation.")
            and decision.mutation_scope == "read_only"
        )
        read_only_query = (
            decision.route in {"dcc_query", "unreal_capability"}
            and decision.operation_mode == "query"
            and decision.mutation_scope == "read_only"
            and str(decision.target_identifier or "") in {"project.snapshot", "selection", "scene.list_joints", "scene.ls", "scene"}
        )
        if read_only_navigation:
            decision.operation_mode = decision.operation_mode or "navigate"
            decision.can_execute_directly = True
        elif read_only_query:
            decision.can_execute_directly = True
        elif decision.route in {"dcc_execute", "dcc_prototype", "unreal_capability", "function_execution"}:
            decision.operation_mode = "preview"
        elif not decision.operation_mode:
            decision.operation_mode = "preview"
        decision.mutation_scope = "read_only"
        decision.requires_dcc_connection = False
        decision.requires_confirmation = False
        if not (read_only_navigation or read_only_query):
            decision.can_execute_directly = False
        decision.risk_level = "low"
        decision.disqualifiers.append("Prompt explicitly blocked execution or mutation.")
    if decision.compound_kind == "atomic":
        decision.compound_kind = _detect_compound_kind(lower)
    if not decision.operations:
        decision.operations = _compound_operations(lower, decision.route, decision.operation_mode)
    if (
        decision.route == "project_search"
        and decision.model_tier == "none_deterministic"
        and _is_simple_project_fact_question(lower)
    ):
        # Deterministic project facts are an execution fast path.  Canonical
        # understanding is already attached, so do not synthesize a multi-step
        # reasoning plan, capability-gap graph, domain-expert package, or action
        # graph before querying the index.
        decision.requires_plan = False
        decision.can_execute_directly = True
        decision.background_worker_required = False
        decision.reasoning_pipeline = {}
        decision.capability_gap_plan = {}
        decision.domain_experts = []
        decision.senior_prompt_analysis = {}
        decision.visible_progress = {
            "framework": "visible_reasoning_progress_v2",
            "enabled": True,
            "route": "project_search",
            "execution_route": "engine.project_search",
            "stage_model": "deterministic_fast_path",
            "stages": [
                {
                    "state": "SEARCHING",
                    "label": "Searching the project index",
                    "message": "Searching indexed files and symbols for the requested project fact.",
                    "index": 1,
                    "total": 1,
                    "percent": 100,
                    "status": "pending",
                    "early_exit": True,
                }
            ],
        }
        return decision
    if canonical_progress or canonical_reasoning:
        decision.visible_progress = canonical_progress
        decision.reasoning_pipeline = canonical_reasoning
        decision.capability_gap_plan = {}
        decision.domain_experts = []
        decision.senior_prompt_analysis = {}
        return decision

    rich_context_allowed = len(lower or "") <= 1200
    if not rich_context_allowed:
        decision.reasons.append("Deferred rich route analysis during foreground classification for a medium/long prompt.")
        decision.capability_gap_plan = {
            "deferred": True,
            "owner": "background_planner",
        }
        decision.visible_progress = {
            "framework": "visible_reasoning_progress_v2",
            "enabled": True,
            "stages": [
                {
                    "state": "PLANNING",
                    "label": "Preparing staged request",
                    "index": 1,
                    "total": 1,
                    "status": "pending",
                }
            ],
        }
        return decision

    try:
        from tech_connector.services.reasoning.engineering_reasoning_service import analyze_senior_prompt

        decision.senior_prompt_analysis = analyze_senior_prompt(
            lower,
            route=decision.route,
            intent_category=decision.intent_category,
            host=decision.host,
            provider=decision.provider,
            existing=decision.to_dict(),
        )
    except Exception:
        decision.senior_prompt_analysis = {}
    try:
        from tech_connector.services.domain_expert_service import select_domain_experts

        decision.domain_experts = select_domain_experts(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.domain_experts = []
    try:
        from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan

        decision.capability_gap_plan = build_goal_gap_plan(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.capability_gap_plan = {}
    try:
        from tech_connector.services.reasoning.multi_stage_reasoning_service import build_reasoning_pipeline

        decision.reasoning_pipeline = build_reasoning_pipeline(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.reasoning_pipeline = {}
    try:
        from tech_connector.services.prompt.prompt_progress_service import build_prompt_progress_plan

        decision.visible_progress = build_prompt_progress_plan(
            decision.senior_prompt_analysis.get("primary_objective") or lower,
            decision.to_dict(),
        )
    except Exception:
        decision.visible_progress = {}
    return decision


def _is_vague_senior_improvement(lower: str) -> bool:
    if not re.search(r"\b(make|improve|clean up|cleanup|production ready|scalable|maintainable|fragile|better)\b", lower or ""):
        return False
    if re.search(
        r"\b(latency|ranking|recall|memory leak|startup|specific|line|file|files|function|class|method|traceback|exception|error code|compile error|efficient|efficiency|duplicate|duplicates|refactor|change multiple)\b",
        lower or "",
    ):
        return False
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+\b", lower or ""):
        return False
    return bool(
        re.search(r"\b(system|architecture|feature|subsystem|project search|search|operation|code|project|this|that|it)\b", lower or "")
    )


def _normalize_prompt_for_routing(lower: str) -> str:
    replacements = {
        "mayya": "maya",
        "unrel": "unreal",
        "cretae": "create",
        "exprot": "export",
        "crowling": "crawling",
        "anm": "anim",
        "combt": "combat",
    }
    text = lower or ""
    for typo, replacement in replacements.items():
        text = re.sub(rf"\b{re.escape(typo)}\b", replacement, text)
    return text


def _is_unreal_animation_blueprint_feature_request(lower: str) -> bool:
    text = lower or ""
    action = re.search(r"\b(make|create|build|add|set up|setup|get|implement|wire)\b", text)
    abp_context = re.search(r"\b(abp(?:_[a-z0-9_]+)?|anim blueprint|animation blueprint|anm blueprint|anim bp|animation bp)\b", text)
    animation_context = re.search(r"\b(anim|animation|anm|crawl|crawling|crowling|locomotion|state machine|blendspace|combat|combt)\b", text)
    if action and abp_context and animation_context:
        return True
    if re.search(r"\b(crawl|crawling|crowling)\b", text) and re.search(r"\b(abp|combat|combt)\b", text):
        return True
    return False


def _is_explicit_pipeline_build_request(lower: str) -> bool:
    text = lower or ""
    return bool(
        re.search(
            r"\b(build|create|make|design|compose|set up|setup)\b",
            text,
        )
        and re.search(
            r"\b(pipeline|workflow|node graph|pipeline graph)\b",
            text,
        )
    )


def _has_host_handoff_language(lower: str, hosts: list[str]) -> bool:
    if len(hosts) >= 2:
        return True
    if re.search(r"\b(pipeline|workflow|bridge|transfer)\b", lower):
        return True
    return bool(
        re.search(r"\bconnect\b", lower)
        and re.search(r"\b(hosts?|apps?|applications?|dccs?|engines?|bridge|pipeline|workflow)\b", lower)
    )


def _read_only_host_code_query_decision(
    lower: str,
    host: str,
) -> PromptRouteDecision | None:
    code_authoring = bool(
        re.search(
            r"\b(?:how\s+(?:would|do|can|should)\s+i|plan|design|propose|"
            r"write|implement|author|scaffold)\b",
            lower,
        )
        and re.search(
            r"\b(?:ui|widget|dialog|panel|window|code|class|module|script|"
            r"wrapper|tool|application|app)\b",
            lower,
        )
    )
    if not (
        host
        and not code_authoring
        and _looks_like_read_only_project_question(lower)
        and re.search(
            r"\b(file|files|path|python|function|functions|method|methods|"
            r"class|classes|symbol|symbols|code|script|tool|tools|argument|"
            r"arguments|args|caller|callers|callee|callees)\b",
            lower,
        )
    ):
        return None
    return PromptRouteDecision(
        route="project_search",
        provider="project_search",
        intent_category="project_search",
        host=host,
        confidence=0.94,
        operation_mode="query",
        mutation_scope="read_only",
        requires_confirmation=False,
        requires_dcc_connection=False,
        required_context=["project_index", "symbol_index", "request_goal_graph"],
        model_tier="none_deterministic",
        task_graph=_read_only_review_task_graph(lower),
        reasons=[
            "Interrogative source-code language asks which project callable "
            "implements host behavior; it does not request host execution."
        ],
        rejected_routes=["dcc_execute", "dcc_query", "target_discovery"],
    )


def _looks_like_staged_long_contract(text: str, lower: str) -> bool:
    """Return True for long checklist prompts that should be staged through LLM planning."""
    if len(text or "") < 900:
        return False
    numbered_count = len(re.findall(r"(?:^|\s)\d+[.)]\s+", text or ""))
    if numbered_count < 4 and not re.search(r"\b(before making any changes|implementation requirements|after implementation)\b", lower or ""):
        return False
    if not re.search(r"\b(inspect|identify|determine|propose|plan|before editing|validate|report)\b", lower or ""):
        return False
    return bool(
        re.search(r"\b(do not skip|preserve|rollback|compile|syntax-check|ask only|before making any changes)\b", lower or "")
        or numbered_count >= 8
    )


def _evaluate_semantic_dcc_capabilities(
    goal_graph: dict[str, Any],
    host: str,
) -> list[dict[str, Any]]:
    """Compare model-proposed atomic host operations with the real registry."""
    normalized_host = str(host or "").strip().lower()
    if not normalized_host:
        return []
    try:
        from tech_connector.game_engine.integration.dcc_operation_service import (
            dcc_operation_registry,
            resolve_registered_dcc_operation_key,
        )

        registry = dcc_operation_registry(normalized_host)
    except Exception:
        registry = {}

        def resolve_registered_dcc_operation_key(_host: str, _operation: str) -> str:
            return ""

    rows = list(goal_graph.get("goals") or goal_graph.get("tasks") or [])
    verification = dict(goal_graph.get("request_plan_verification") or {})
    for index, missing in enumerate(verification.get("missing") or [], 1):
        item = dict(missing or {})
        capability = str(item.get("required_capability") or "").strip()
        if capability:
            rows.append(
                {
                    "task_id": f"plan_verifier_gap_{index}",
                    "action": "execute",
                    "objective": str(item.get("request_fragment") or item.get("reason") or ""),
                    "capability": capability,
                }
            )
    evaluations: list[dict[str, Any]] = []
    seen: set[str] = set()
    mutating_actions = {"generate", "modify", "modify_code", "execute", "validate"}
    for row in rows:
        item = dict(row or {})
        capability = str(item.get("capability") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", capability):
            continue
        if capability in seen:
            continue
        seen.add(capability)
        resolved = resolve_registered_dcc_operation_key(normalized_host, capability)
        action = str(item.get("action") or "").strip().lower()
        if resolved and resolved in registry:
            definition = registry[resolved]
            evaluations.append(
                {
                    "capability": capability,
                    "resolved_operation": resolved,
                    "status": "registered_callable",
                    "function": str(getattr(definition, "function", "") or ""),
                    "task_id": str(item.get("task_id") or item.get("goal_id") or ""),
                    "objective": str(item.get("objective") or item.get("title") or ""),
                }
            )
        else:
            evaluations.append(
                {
                    "capability": capability,
                    "resolved_operation": "",
                    "status": (
                        "missing_unregistered_callable"
                        if action in mutating_actions
                        else "requires_capability_resolution"
                    ),
                    "function": "",
                    "task_id": str(item.get("task_id") or item.get("goal_id") or ""),
                    "objective": str(item.get("objective") or item.get("title") or ""),
                    "reason": (
                        f"The semantic plan requires {capability!r}, but the {normalized_host} "
                        "operation registry has no matching callable."
                    ),
                }
            )
    return evaluations


def classify_prompt_intent_from_understanding(
    understanding: Any,
    text: str,
    *,
    host: str = "",
):
    """Build the compatibility phrase intent without re-running understanding."""
    from tech_connector.services.prompt.prompt_intent_service import prompt_intent_from_understanding

    return prompt_intent_from_understanding(understanding, text, host=host)
