"""Shared DCC prototype/debug intent helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


@dataclass(frozen=True)
class DccOperation:
    key: str
    label: str
    function: str
    required: tuple[str, ...] = ()
    optional: dict[str, Any] = field(default_factory=dict)
    mutates_project: bool = False
    description: str = ""


MAYA_OPERATIONS: dict[str, DccOperation] = {
    "navigation.frame_selection": DccOperation(
        key="navigation.frame_selection",
        label="Maya Frame Selection",
        function="ai_studio.maya.generated.navigation_frame_selection",
        optional={"objects": []},
        description="Frame the current selection or named objects in the Maya viewport.",
    ),
    "navigation.open_panel": DccOperation(
        key="navigation.open_panel",
        label="Maya Open Panel",
        function="ai_studio.maya.generated.navigation_open_panel",
        required=("panel",),
        description="Open a common Maya editor panel such as Outliner, Node Editor, Graph Editor, Hypershade, or Script Editor.",
    ),
    "scene.select": DccOperation(
        key="scene.select",
        label="Maya Select Objects",
        function="ai_studio.maya.generated.scene_select",
        required=("objects",),
        optional={"replace": True},
        mutates_project=True,
        description="Select one or more Maya nodes by name.",
    ),
    "scene.move": DccOperation(
        key="scene.move",
        label="Maya Move Object",
        function="ai_studio.maya.generated.scene_move",
        required=("objects", "translation"),
        optional={"relative": True},
        mutates_project=True,
        description="Move one or more Maya nodes by a small translation vector.",
    ),
    "scene.ls": DccOperation(
        key="scene.ls",
        label="Maya List Nodes",
        function="ai_studio.maya.generated.scene_ls",
        optional={"selection": False, "type": "", "long": False, "flatten": False, "limit": 50, "first_only": False},
        mutates_project=False,
        description="List Maya nodes using cmds.ls flags such as selection=True or type='joint'.",
    ),
    "scene.list_joints": DccOperation(
        key="scene.list_joints",
        label="Maya List Joints",
        function="ai_studio.maya.generated.scene_list_joints",
        optional={"limit": 20, "first_only": False},
        mutates_project=False,
        description="List Maya joint/bone names from the current scene.",
    ),
    "scene.create_locator": DccOperation(
        key="scene.create_locator",
        label="Maya Create Locator",
        function="ai_studio.maya.generated.scene_create_locator",
        optional={"name": "locator", "select": True},
        mutates_project=True,
        description="Create a Maya locator and optionally select it.",
    ),
    "scene.create_control": DccOperation(
        key="scene.create_control",
        label="Maya Create Control",
        function="ai_studio.maya.generated.scene_create_control",
        optional={"name": "control_ctrl", "shape": "circle", "position": None, "select": True, "if_missing": False},
        mutates_project=True,
        description="Create a simple Maya NURBS control curve and optionally position/select it.",
    ),
    "node.connect_attr": DccOperation(
        key="node.connect_attr",
        label="Maya Connect Attributes",
        function="ai_studio.maya.generated.node_connect_attr",
        required=("source_attr", "destination_attr"),
        optional={"force": True},
        mutates_project=True,
        description="Connect one Maya attribute plug to another, such as ctrl.tx to joint.rx.",
    ),
    "node.disconnect_attr": DccOperation(
        key="node.disconnect_attr",
        label="Maya Disconnect Attributes",
        function="ai_studio.maya.generated.node_disconnect_attr",
        required=("source_attr", "destination_attr"),
        mutates_project=True,
        description="Disconnect one Maya attribute plug from another.",
    ),
    "constraints.create": DccOperation(
        key="constraints.create",
        label="Maya Create Constraint",
        function="ai_studio.maya.generated.constraints_create",
        required=("constraint_type", "targets", "driven"),
        optional={"maintain_offset": True},
        mutates_project=True,
        description="Create a parent/orient/point/scale/aim constraint between named Maya objects.",
    ),
    "material.create": DccOperation(
        key="material.create",
        label="Maya Create Material",
        function="ai_studio.maya.generated.material_create",
        required=("material_name",),
        optional={"shader_type": "lambert", "color": None},
        mutates_project=True,
        description="Create a Maya material/shader and shading group.",
    ),
    "material.assign": DccOperation(
        key="material.assign",
        label="Maya Assign Material",
        function="ai_studio.maya.generated.material_assign",
        required=("material_name",),
        optional={"objects": []},
        mutates_project=True,
        description="Assign a material to the current selection or named objects.",
    ),
    "material.set_color": DccOperation(
        key="material.set_color",
        label="Maya Set Material Color",
        function="ai_studio.maya.generated.material_set_color",
        required=("material_name", "color"),
        mutates_project=True,
        description="Set a material color from a color name, RGB triplet, or hex value.",
    ),
    "skin.bind": DccOperation(
        key="skin.bind",
        label="Maya Bind Skin",
        function="ai_studio.maya.generated.skin_bind",
        required=("mesh", "influences"),
        optional={"to_selected": False, "maximum_influences": 4, "dropoff_rate": 4.0},
        mutates_project=True,
        description="Bind a mesh to one or more joint influences with skinCluster.",
    ),
    "skin.add_influence": DccOperation(
        key="skin.add_influence",
        label="Maya Add Skin Influence",
        function="ai_studio.maya.generated.skin_add_influence",
        required=("mesh", "influence"),
        optional={"weight": 0.0},
        mutates_project=True,
        description="Add an influence joint to an existing skinCluster.",
    ),
    "skin.remove_influence": DccOperation(
        key="skin.remove_influence",
        label="Maya Remove Skin Influence",
        function="ai_studio.maya.generated.skin_remove_influence",
        required=("mesh", "influence"),
        mutates_project=True,
        description="Remove an influence joint from an existing skinCluster.",
    ),
    "skin.set_weights": DccOperation(
        key="skin.set_weights",
        label="Maya Set Skin Weights",
        function="ai_studio.maya.generated.skin_set_weights",
        required=("mesh", "influence", "weight"),
        optional={"components": []},
        mutates_project=True,
        description="Set skin weights for selected or named components with skinPercent.",
    ),
    "api.call": DccOperation(
        key="api.call",
        label="Maya API Call",
        function="ai_studio.maya.generated.api_call",
        required=("function",),
        optional={"args": [], "kwargs": {}},
        mutates_project=True,
        description="Call a Maya Python API function such as maya.cmds.setAttr with explicit args/kwargs.",
    ),
    "tool.call": DccOperation(
        key="tool.call",
        label="Maya Tool Call",
        function="ai_studio.maya.generated.tool_call",
        required=("function",),
        optional={"args": [], "kwargs": {}},
        mutates_project=True,
        description="Call a maya_tools package function with explicit args/kwargs.",
    ),
    "rigging.create_rig": DccOperation(
        key="rigging.create_rig",
        label="Maya Create Rig",
        function="maya_tools.Rigging.create_rig.create_rig",
        required=("character_name",),
        optional={"mesh_path": "", "skeleton_path": "", "skeleton_type": "Humanoid"},
        mutates_project=True,
        description="Build a control rig for a character model in Maya.",
    ),
    "rigging.auto_skinner": DccOperation(
        key="rigging.auto_skinner",
        label="Maya Auto Skinner",
        function="maya_tools.Rigging.auto_skinner.auto_skin",
        required=("mesh_name",),
        optional={"influence_joints": [], "falloff": 4.0},
        mutates_project=True,
        description="Calculate skin weights for a mesh in Maya.",
    ),
    "animation.export": DccOperation(
        key="animation.export",
        label="Maya Export Animation",
        function="maya_tools.Animation.anim_export.anim_export.export_anim",
        required=("export_path",),
        optional={"start_frame": 1, "end_frame": 120, "selected_only": True},
        mutates_project=False,
        description="Export animation curves or FBX clips from Maya.",
    ),
    "modeling.create_primitive": DccOperation(
        key="modeling.create_primitive",
        label="Maya Create Primitive",
        function="ai_studio.maya.generated.modeling_create_primitive",
        required=("primitive_type",),
        optional={"name": "Primitive", "size": 1.0},
        mutates_project=True,
        description="Create a geometric mesh primitive (cube, sphere, cylinder) in Maya.",
    ),
    "scene.cleanup": DccOperation(
        key="scene.cleanup",
        label="Maya Scene Cleanup",
        function="maya_tools.Utilities.cleanup",
        required=(),
        optional={"delete_history": True, "freeze_transforms": True, "remove_unused_nodes": True},
        mutates_project=True,
        description="Clean up scene hierarchy, delete history, and optimize nodes.",
    ),
}

BLENDER_OPERATIONS: dict[str, DccOperation] = {
    "script.run": DccOperation(
        key="script.run",
        label="Blender Run Script",
        function="ai_studio.blender.generated.script_run",
        required=("code",),
        mutates_project=True,
        description="Run explicit Blender Python code through the direct bridge.",
    ),
    "api.call": DccOperation(
        key="api.call",
        label="Blender API Call",
        function="ai_studio.blender.generated.api_call",
        required=("function",),
        optional={"args": [], "kwargs": {}},
        mutates_project=True,
        description="Call a Blender bpy function/operator with explicit args/kwargs.",
    ),
    "navigation.frame_selection": DccOperation(
        key="navigation.frame_selection",
        label="Blender Frame Selection",
        function="ai_studio.blender.generated.navigation_frame_selection",
        optional={"objects": []},
        description="Frame the current selection or named objects in the active 3D view.",
    ),
    "scene.select": DccOperation(
        key="scene.select",
        label="Blender Select Objects",
        function="ai_studio.blender.generated.scene_select",
        required=("objects",),
        optional={"replace": True},
        mutates_project=True,
        description="Select one or more Blender objects by name.",
    ),
    "material.create": DccOperation(
        key="material.create",
        label="Blender Create Material",
        function="ai_studio.blender.generated.material_create",
        required=("material_name",),
        optional={"color": None, "use_nodes": True},
        mutates_project=True,
        description="Create a Blender material and optionally set its color.",
    ),
    "material.assign": DccOperation(
        key="material.assign",
        label="Blender Assign Material",
        function="ai_studio.blender.generated.material_assign",
        required=("material_name",),
        optional={"objects": []},
        mutates_project=True,
        description="Assign a material to named objects or the current Blender selection.",
    ),
    "material.set_color": DccOperation(
        key="material.set_color",
        label="Blender Set Material Color",
        function="ai_studio.blender.generated.material_set_color",
        required=("material_name", "color"),
        mutates_project=True,
        description="Set a Blender material base color/diffuse color.",
    ),
    "modeling.create_primitive": DccOperation(
        key="modeling.create_primitive",
        label="Blender Create Primitive",
        function="ai_studio.blender.generated.modeling_create_primitive",
        required=("primitive_type",),
        optional={"name": "Primitive", "location": (0.0, 0.0, 0.0), "scale": (1.0, 1.0, 1.0)},
        mutates_project=True,
        description="Create a basic geometric mesh primitive in Blender.",
    ),
    "render.render_scene": DccOperation(
        key="render.render_scene",
        label="Blender Render Scene",
        function="blender_tools.render.render_scene",
        required=("output_path",),
        optional={"camera_name": "Camera", "resolution": (1920, 1080), "engine": "CYCLES"},
        mutates_project=False,
        description="Render the active viewport or camera view in Blender.",
    ),
    "io.export_fbx": DccOperation(
        key="io.export_fbx",
        label="Blender Export FBX",
        function="blender_tools.io.export_fbx",
        required=("filepath",),
        optional={"selected_only": True, "apply_unit_scale": True},
        mutates_project=False,
        description="Export current scene or selection as FBX.",
    ),
    "io.import_fbx": DccOperation(
        key="io.import_fbx",
        label="Blender Import FBX",
        function="blender_tools.io.import_fbx",
        required=("filepath",),
        optional={"use_image_search": True},
        mutates_project=True,
        description="Import an FBX file into the Blender scene.",
    ),
    "animation.bake": DccOperation(
        key="animation.bake",
        label="Blender Bake Animation",
        function="blender_tools.animation.bake_keyframes",
        required=("start_frame", "end_frame"),
        optional={"only_selected": True},
        mutates_project=True,
        description="Bake animation keyframes for selected objects/rigs in Blender.",
    ),
}


SUBSTANCE_PAINTER_OPERATIONS: dict[str, DccOperation] = {
    "project.create": DccOperation(
        key="project.create",
        label="Substance Painter Create Project",
        function="substance_painter_tools.project.create_project",
        required=("mesh_path",),
        optional={"template_name": "PBR - Metallic Roughness", "directory": ""},
        mutates_project=True,
        description="Create a new Substance Painter project from a mesh.",
    ),
    "textures.export": DccOperation(
        key="textures.export",
        label="Substance Painter Export Textures",
        function="substance_painter_tools.textures.export_textures",
        required=("output_path",),
        optional={"preset_name": "PBR Metallic Roughness", "resolution": 2048},
        mutates_project=False,
        description="Export textured maps to a directory.",
    ),
    "material.apply": DccOperation(
        key="material.apply",
        label="Substance Painter Apply Material",
        function="substance_painter_tools.material.apply_material",
        required=("material_name",),
        optional={"texture_set": ""},
        mutates_project=True,
        description="Apply a smart material or preset to a texture set.",
    ),
}

HOUDINI_OPERATIONS: dict[str, DccOperation] = {
    "scene.select": DccOperation(
        key="scene.select",
        label="Houdini Select Nodes",
        function="ai_studio.houdini.generated.scene_select",
        required=("nodes",),
        optional={"replace": True},
        mutates_project=True,
        description="Select one or more nodes in the Houdini scene by name or path.",
    ),
    "scene.list": DccOperation(
        key="scene.list",
        label="Houdini List Scene",
        function="ai_studio.houdini.generated.scene_list",
        optional={"network": "/obj"},
        description="List nodes in the Houdini scene under a given network path.",
    ),
    "node.create": DccOperation(
        key="node.create",
        label="Houdini Create Node",
        function="ai_studio.houdini.generated.node_create",
        required=("node_type",),
        optional={"parent": "/obj", "name": ""},
        mutates_project=True,
        description="Create a Houdini node of a given type inside a network.",
    ),
    "node.set_parm": DccOperation(
        key="node.set_parm",
        label="Houdini Set Parameter",
        function="ai_studio.houdini.generated.node_set_parm",
        required=("node_path", "parm_name", "value"),
        mutates_project=True,
        description="Set a parameter value on a Houdini node.",
    ),
    "node.connect": DccOperation(
        key="node.connect",
        label="Houdini Connect Nodes",
        function="ai_studio.houdini.generated.node_connect",
        required=("source_path", "destination_path"),
        optional={"output_index": 0, "input_index": 0},
        mutates_project=True,
        description="Connect the output of one Houdini node to the input of another.",
    ),
    "geometry.import": DccOperation(
        key="geometry.import",
        label="Houdini Import Geometry",
        function="houdini_tools.geometry.import_file",
        required=("filepath",),
        optional={"parent": "/obj", "name": "ai_import"},
        mutates_project=True,
        description="Import a geometry file (OBJ, FBX, USD) into the Houdini scene.",
    ),
    "geometry.export": DccOperation(
        key="geometry.export",
        label="Houdini Export Geometry",
        function="houdini_tools.geometry.export_file",
        required=("node_path", "filepath"),
        optional={"frame": 1},
        mutates_project=False,
        description="Export geometry from a Houdini SOP node to a file.",
    ),
    "render.submit": DccOperation(
        key="render.submit",
        label="Houdini Render Submit",
        function="houdini_tools.render.submit",
        required=("rop_path",),
        optional={"start_frame": 1, "end_frame": 100, "step": 1},
        mutates_project=False,
        description="Submit a render through a Houdini ROP node.",
    ),
    "simulation.run": DccOperation(
        key="simulation.run",
        label="Houdini Run Simulation",
        function="houdini_tools.simulation.run",
        required=("dop_network_path",),
        optional={"start_frame": 1, "end_frame": 100, "substeps": 1},
        mutates_project=True,
        description="Run a DOP simulation in Houdini for the specified frame range.",
    ),
    "material.create": DccOperation(
        key="material.create",
        label="Houdini Create Material",
        function="ai_studio.houdini.generated.material_create",
        required=("material_name",),
        optional={"shader_type": "principledshader", "network": "/mat"},
        mutates_project=True,
        description="Create a material in the Houdini /mat network.",
    ),
    "material.assign": DccOperation(
        key="material.assign",
        label="Houdini Assign Material",
        function="ai_studio.houdini.generated.material_assign",
        required=("node_path", "material_path"),
        mutates_project=True,
        description="Assign a material to a Houdini geometry node.",
    ),
    "usd.export": DccOperation(
        key="usd.export",
        label="Houdini USD Export",
        function="houdini_tools.usd.export",
        required=("filepath",),
        optional={"node_path": "/obj", "frame_range": None},
        mutates_project=False,
        description="Export the Houdini scene or selected network as a USD file.",
    ),
    "api.call": DccOperation(
        key="api.call",
        label="Houdini API Call",
        function="ai_studio.houdini.generated.api_call",
        required=("function",),
        optional={"args": [], "kwargs": {}},
        mutates_project=True,
        description="Call a Houdini Python hou API function with explicit args/kwargs.",
    ),
    "script.run": DccOperation(
        key="script.run",
        label="Houdini Run Script",
        function="ai_studio.houdini.generated.script_run",
        required=("code",),
        mutates_project=True,
        description="Run explicit Houdini Python code (hou module) through the direct bridge.",
    ),
}

MOTIONBUILDER_OPERATIONS: dict[str, DccOperation] = {
    "character.create_character": DccOperation(
        key="character.create_character",
        label="MotionBuilder Create Character",
        function="motionbuilder_tools.character.create_character",
        required=("character_name",),
        optional={"definition_file": ""},
        mutates_project=True,
        description="Define and characterize a skeletal rig in MotionBuilder.",
    ),
    "character.plot_animation": DccOperation(
        key="character.plot_animation",
        label="MotionBuilder Plot Animation",
        function="motionbuilder_tools.character.plot_animation",
        required=("character_name",),
        optional={"plot_to_rig": True, "fps": 30},
        mutates_project=True,
        description="Plot animation to Control Rig or Skeleton.",
    ),
    "io.import_fbx": DccOperation(
        key="io.import_fbx",
        label="MotionBuilder Import FBX",
        function="motionbuilder_tools.io.import_fbx",
        required=("filepath",),
        optional={"merge": True},
        mutates_project=True,
        description="Import/merge FBX file into the active MotionBuilder scene.",
    ),
    "io.export_fbx": DccOperation(
        key="io.export_fbx",
        label="MotionBuilder Export FBX",
        function="motionbuilder_tools.io.export_fbx",
        required=("filepath",),
        optional={"selected_only": False},
        mutates_project=False,
        description="Export the active MotionBuilder scene/selection to FBX.",
    ),
}

UNITY_OPERATIONS: dict[str, DccOperation] = {
    "assets.import_fbx": DccOperation(
        key="assets.import_fbx",
        label="Unity Import FBX",
        function="unity_tools.assets.import_fbx",
        required=("filepath",),
        optional={"destination_folder": "Assets/Models"},
        mutates_project=True,
        description="Import an FBX mesh or animation asset into the Unity project.",
    ),
    "prefab.create": DccOperation(
        key="prefab.create",
        label="Unity Create Prefab",
        function="unity_tools.prefab.create_prefab",
        required=("gameobject_name",),
        optional={"destination_path": "Assets/Prefabs"},
        mutates_project=True,
        description="Create a prefab asset from a GameObject in the Unity scene.",
    ),
    "material.create": DccOperation(
        key="material.create",
        label="Unity Create Material",
        function="unity_tools.material.create_material",
        required=("material_name",),
        optional={"shader_name": "Standard"},
        mutates_project=True,
        description="Create a material asset in the Unity project.",
    ),
    "scene.add_prefab": DccOperation(
        key="scene.add_prefab",
        label="Unity Add Prefab to Scene",
        function="unity_tools.scene.add_prefab",
        required=("prefab_path",),
        optional={"position": (0.0, 0.0, 0.0)},
        mutates_project=True,
        description="Instantiate a prefab asset in the active Unity scene.",
    ),
}


DCC_HOST_ALIASES = {
    "maya": ("maya",),
    "blender": ("blender",),
    "substance_painter": ("substance painter", "substance", "painter"),
    "motionbuilder": ("motionbuilder", "motion builder", "mobu"),
    "unity": ("unity",),
    "houdini": ("houdini", "hou", "hip", "hdri"),
}

DCC_TOOL_DOMAINS = {
    "maya": "maya_tools",
    "blender": "blender_tools",
    "substance_painter": "substance_painter_tools",
    "motionbuilder": "motionbuilder_tools",
    "unity": "unity_tools",
    "houdini": "houdini_tools",
}

PROTOTYPE_VERBS = (
    "prototype",
    "create",
    "implement",
    "build",
    "make",
    "add",
    "set up",
    "setup",
)

DEBUG_TERMS = (
    "debug",
    "diagnose",
    "what is broken",
    "what's broken",
    "broken",
    "fix",
    "validate",
    "errors",
    "warnings",
    "not working",
    "failing",
    "full project",
    "whole project",
)

PROTOTYPE_CONTEXT_TERMS = (
    "feature",
    "prototype",
    "tool",
    "rig",
    "animation",
    "graph",
    "slot",
    "system",
    "mechanic",
    "ability",
    "setup",
    "set up",
    "shader",
    "material",
    "asset",
    "scene",
    "prefab",
    "workflow",
    "pipeline",
)

FEATURE_ALIASES = {
    "rock_climbing": ("rock climbing", "climbing", "climb", "ledge grab", "mantle", "mantling"),
    "motion_matching_locomotion": ("motion matching", "pose search", "motion matched"),
    "combat_combo": ("combat combo", "combo attack", "melee combo", "attack chain"),
    "retargeting_setup": ("retarget", "retargeting", "hik", "human ik"),
    "material_variants": ("material variant", "shader variant", "texture set"),
    "scene_cleanup": ("scene cleanup", "cleanup", "clean up"),
}


def detect_dcc_host(text: str) -> str:
    q = (text or "").lower()
    for host, aliases in DCC_HOST_ALIASES.items():
        if any(alias in q for alias in aliases):
            return host
    return ""


def is_dcc_prototype_request(text: str, host: str = "") -> bool:
    q = (text or "").lower()
    if not host:
        host = detect_dcc_host(text)
    if not host:
        return False
    try:
        from services.prompt_route_service import classify_prompt_route
        if classify_prompt_route(text).route != "dcc_prototype":
            return False
    except Exception:
        pass
    if not any(verb in q for verb in PROTOTYPE_VERBS):
        return False
    return any(term in q for term in PROTOTYPE_CONTEXT_TERMS)


def is_dcc_debug_request(text: str, host: str = "") -> bool:
    q = (text or "").lower()
    if not host:
        host = detect_dcc_host(text)
    if not host:
        return False
    return any(term in q for term in DEBUG_TERMS)


def infer_dcc_template(text: str) -> str:
    q = (text or "").lower()
    for template, aliases in FEATURE_ALIASES.items():
        if any(alias in q for alias in aliases):
            return template
    match = re.search(
        r"\b(?:prototype|create|implement|build|make|add|set up|setup)\s+(?:a|an|the|new)?\s*([A-Za-z0-9 _-]{3,60}?)(?:\s+(?:feature|tool|system|mechanic|ability|prototype|in|for|inside|with)\b|$)",
        text or "",
        re.IGNORECASE,
    )
    raw = match.group(1) if match else "dcc_feature"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug or "dcc_feature"


def build_dcc_prototype_params(host: str, text: str, context: str = "") -> dict[str, Any]:
    template = infer_dcc_template(text)
    return {
        "host": host,
        "template": template,
        "target_path": f"/AIStudio/Prototypes/{template}",
        "parameters": {
            "feature_goal": text,
            "mode": "prototype_or_create_or_implement",
            "context_excerpt": (context or "")[:16000],
            "previous_ai_work_context": "",
            "research_mode": {},
            "awareness": {
                "scan_scene_first": True,
                "inspect_selection": True,
                "inspect_assets_or_dependencies": True,
                "inspect_variables": True,
                "inspect_functions": True,
                "scan_connectable_properties": True,
                "prefer_existing_assets": True,
            },
            "requested_outputs": [
                "operation_plan",
                "created_or_modified_assets",
                "changed_nodes_or_graphs",
                "new_slots_or_parameters",
                "validation_report",
                "rollback_token",
            ],
        },
    }


def attach_operation_context(
    params: dict[str, Any],
    *,
    previous_work_context: str = "",
    research_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach optional shared planning context to a DCC operation payload."""
    updated = dict(params or {})
    parameters = dict(updated.get("parameters") or {})
    parameters["previous_ai_work_context"] = (previous_work_context or "")[:8000]
    parameters["research_mode"] = dict(research_mode or {})
    updated["parameters"] = parameters
    return updated


def build_dcc_debug_params(host: str, text: str, context: str = "") -> dict[str, Any]:
    q = (text or "").lower()
    return {
        "host": host,
        "paths": [],
        "save": False,
        "parameters": {
            "debug_goal": text,
            "scope": "full_project" if any(term in q for term in ("full project", "whole project", "everything", "all")) else "scene_or_selection",
            "context_excerpt": (context or "")[:16000],
            "requested_report": [
                "missing_references",
                "invalid_connections",
                "broken_nodes",
                "compile_or_script_errors",
                "missing_assets",
                "dependency_issues",
                "recommended_fix_order",
                "safe_fix_operations",
            ],
        },
    }


def dcc_operation_function(host: str, mode: str) -> str:
    domain = DCC_TOOL_DOMAINS.get(host, f"{host}_tools")
    function_name = "prototype_from_template" if mode == "prototype" else "debug_project"
    return f"{domain}.ai_studio.{function_name}"


def dcc_prompt_to_operation(host: str, text: str) -> str | None:
    q = (text or "").lower()
    if host == "maya":
        if re.search(r"\b(frame selected|frame selection|zoom selected|focus selected|frame\s+[A-Za-z0-9_:|.-]+)\b", q):
            return "navigation.frame_selection"
        if re.search(r"\b(what|which|list|show|get|report)\b", q) and re.search(r"\b(selection|selected|currently selected)\b", q):
            return "scene.ls"
        if re.search(r"\b(what|which|list|show|find|get|report)\b", q) and re.search(
            r"\b(mesh|meshes|camera|cameras|light|lights|constraint|constraints|control|controls|ctrl|ctrls|locator|locators|curve|curves|node|nodes|transform|transforms|material|materials|shader|shaders)\b",
            q,
        ):
            return "scene.ls"
        if re.search(r"\b(what|which|list|show|find|get|first)\b", q) and re.search(r"\b(bone|bones|joint|joints|skeleton)\b", q):
            return "scene.list_joints"
        if re.search(r"\b(open|show)\s+(outliner|node editor|graph editor|hypershade|script editor|connection editor|attribute editor|channel box)\b", q):
            return "navigation.open_panel"
        if re.search(r"\b(create|make|new|add)\s+(?:a\s+|an\s+)?locator\b", q):
            return "scene.create_locator"
        if re.search(r"\b(create|make|new|add)\b", q) and re.search(r"\b(control|ctrl|nurbs\s+circle|circle\s+control)\b", q):
            return "scene.create_control"
        if re.search(r"\b(select|highlight)\s+([A-Za-z0-9_:|.,\s-]+)\b", q) and "selection" not in q:
            return "scene.select"
        if re.search(r"\b(connect|wire|link)\b", q) and re.search(r"[A-Za-z_][A-Za-z0-9_:|.-]*\.[A-Za-z_][A-Za-z0-9_]*", text or ""):
            return "node.connect_attr"
        if re.search(r"\b(disconnect|unwire|unlink)\b", q) and re.search(r"[A-Za-z_][A-Za-z0-9_:|.-]*\.[A-Za-z_][A-Za-z0-9_]*", text or ""):
            return "node.disconnect_attr"
        if re.search(r"\b(parent|orient|point|scale|aim)\s+(constraint|constrain|constrian|consrain)\b", q):
            return "constraints.create"
        if re.search(r"\b(move|translate|offset|nudge)\b", q) and re.search(r"\b[A-Za-z_][A-Za-z0-9_:|.-]*\b", text or ""):
            return "scene.move"
        if re.search(r"\b(create|make|new)\s+(material|shader)\b", q):
            return "material.create"
        if re.search(r"\b(assign|apply|set)\s+(material|shader)\b", q):
            return "material.assign"
        if re.search(r"\b(set|change|edit)\s+.*\b(material|shader)\s+.*\b(color|colour)\b", q):
            return "material.set_color"
        if re.search(r"\b(bind skin|skin bind|smooth bind|bind)\b", q) and re.search(r"\b(skin|mesh|joint|joints|influence|influences)\b", q):
            return "skin.bind"
        if re.search(r"\b(add influence|add joint influence)\b", q):
            return "skin.add_influence"
        if re.search(r"\b(remove influence|remove joint influence)\b", q):
            return "skin.remove_influence"
        if re.search(r"\b(set|paint|edit|change)\s+.*\b(weight|weights|skinPercent|skin percent)\b", q):
            return "skin.set_weights"
        if re.search(r"\b(openmaya|open maya|maya\.api\.openmaya|maya\.openmaya|om\.|om2\.)\b", q):
            return "api.call"
        if re.search(r"\b(maya\.cmds|cmds\.|api call|call api|python api)\b", q):
            return "api.call"
        if re.search(r"\b(maya_tools\.|tool call|call tool|run tool)\b", q):
            return "tool.call"
        if "create_rig" in q or "create rig" in q or "build rig" in q or "create control rig" in q:
            return "rigging.create_rig"
        if "auto_skinner" in q or "auto skin" in q or "skin weights" in q or "skinning" in q or "smooth skin" in q:
            return "rigging.auto_skinner"
        if "export anim" in q or "anim_export" in q or "export animation" in q:
            return "animation.export"
        if any(term in q for term in ("cube", "sphere", "cylinder", "cone", "plane", "torus", "primitive")):
            return "modeling.create_primitive"
        if "cleanup" in q or "clean scene" in q or "freeze transform" in q or "delete history" in q:
            return "scene.cleanup"
    elif host == "blender":
        if re.search(r"\b(bpy\.|blender python|python script|run script|execute script)\b", q):
            if re.search(r"\bbpy\.[A-Za-z_][A-Za-z0-9_.]*\b", text or "") and not re.search(r"\b(code|script)\s*[:=]", q):
                return "api.call"
            return "script.run"
        if re.search(r"\b(frame selected|frame selection|zoom selected|focus selected|frame\s+[A-Za-z0-9_.-]+)\b", q):
            return "navigation.frame_selection"
        if re.search(r"\b(select|highlight)\s+([A-Za-z0-9_. ,'-]+)\b", q) and "selection" not in q:
            return "scene.select"
        if re.search(r"\b(create|make|new)\s+(material|shader)\b", q):
            return "material.create"
        if re.search(r"\b(assign|apply|set)\s+(material|shader)\b", q):
            return "material.assign"
        if re.search(r"\b(set|change|edit)\s+.*\b(material|shader)\s+.*\b(color|colour)\b", q):
            return "material.set_color"
        if any(term in q for term in ("cube", "sphere", "cylinder", "cone", "plane", "torus", "primitive")):
            return "modeling.create_primitive"
        if "render" in q or "screenshot" in q or "capture viewport" in q:
            return "render.render_scene"
        if "export fbx" in q or "export selection to fbx" in q or "save as fbx" in q:
            return "io.export_fbx"
        if "import fbx" in q or "load fbx" in q or "open fbx" in q:
            return "io.import_fbx"
        if "bake" in q or "bake keyframes" in q or "bake anim" in q:
            return "animation.bake"
    elif host == "substance_painter":
        if "create_project" in q or "create project" in q or "new project" in q:
            return "project.create"
        if "export texture" in q or "export textures" in q or "export maps" in q:
            return "textures.export"
        if "apply material" in q or "apply smart material" in q or "set material" in q:
            return "material.apply"
    elif host == "motionbuilder":
        if "create_character" in q or "create character" in q or "characterize" in q:
            return "character.create_character"
        if "plot anim" in q or "plot animation" in q or "bake anim" in q or "bake animation" in q:
            return "character.plot_animation"
        if "import fbx" in q or "load fbx" in q or "open fbx" in q or "merge fbx" in q:
            return "io.import_fbx"
        if "export fbx" in q or "save fbx" in q or "save scene as fbx" in q:
            return "io.export_fbx"
    elif host == "unity":
        if "import fbx" in q or "load fbx" in q or "bring in fbx" in q:
            return "assets.import_fbx"
        if "create prefab" in q or "make prefab" in q:
            return "prefab.create"
        if "create material" in q or "make material" in q:
            return "material.create"
        if "add prefab" in q or "instantiate prefab" in q or "spawn prefab" in q:
            return "scene.add_prefab"
    elif host == "houdini":
        if re.search(r"\b(hou\.|houdini python|python script|run script|execute script)\b", q):
            return "script.run"
        if re.search(r"\b(hou\.node|node\.parm|createNode|set_parm|setparm)\b", q):
            return "api.call"
        if re.search(r"\b(select|highlight)\s+([A-Za-z0-9_./]+)\b", q) and "selection" not in q:
            return "scene.select"
        if re.search(r"\b(list|show|display|scan)\s+(nodes?|objects?|networks?|scene)\b", q):
            return "scene.list"
        if re.search(r"\b(create|make|new|add)\s+(node|geo|sop|dop|rop|cop|vop|lop|material|mat|light|camera|rig|object)\b", q):
            return "node.create"
        if re.search(r"\b(set|change|edit|modify)\s+(param|parameter|parm)\b", q) or re.search(r"\bset parm\b", q):
            return "node.set_parm"
        if re.search(r"\b(connect|wire|link)\s+(nodes?|sops?|networks?)\b", q):
            return "node.connect"
        if "import geo" in q or "import obj" in q or "import fbx" in q or "load geo" in q or "load file" in q:
            return "geometry.import"
        if "export geo" in q or "save geo" in q or "write geo" in q:
            return "geometry.export"
        if "render" in q or "submit render" in q or "cook rop" in q:
            return "render.submit"
        if "simulation" in q or "sim" in q or "dop" in q or "flip" in q or "pyro" in q or "vellum" in q:
            return "simulation.run"
        if re.search(r"\b(create|make|new)\s+(material|shader|principled)\b", q):
            return "material.create"
        if re.search(r"\b(assign|apply|set)\s+(material|shader)\b", q):
            return "material.assign"
        if "export usd" in q or "save usd" in q or "usd" in q:
            return "usd.export"
    return None


def build_dcc_operation_params(host: str, operation: str, text: str) -> dict[str, Any]:
    q = (text or "").lower()
    params = {}
    
    # Try to extract primitive types
    if "primitive" in operation:
        for p in ("cube", "sphere", "cylinder", "cone", "plane", "torus"):
            if p in q:
                params["primitive_type"] = p
                break
        params.setdefault("primitive_type", "cube")
        name_match = re.search(
            r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?",
            text or "",
            re.IGNORECASE,
        )
        if name_match:
            params["name"] = name_match.group(1)
        size_match = re.search(r"\b(?:size|scale|radius)\s*(?:=|of|to)?\s*(-?\d+(?:\.\d+)?)\b", q)
        if size_match:
            params["size"] = float(size_match.group(1))
    if host == "maya" and operation == "scene.list_joints":
        first_n = re.search(r"\bfirst\s+(\d+)\b", q)
        if first_n:
            params["limit"] = int(first_n.group(1))
            params["first_only"] = False
        else:
            params["first_only"] = bool(re.search(r"\b(first|top|initial)\b", q))
        match = re.search(r"\blimit\s+(\d+)\b", q)
        if match:
            params["limit"] = int(match.group(1))
        
        # Name argument extraction
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params["name"] = name_match.group(1)
    if host == "maya" and operation == "scene.ls":
        params["selection"] = bool(re.search(r"\b(selection|selected|currently selected)\b", q))
        maya_type_aliases = {
            "joint": ("joint", "joints", "bone", "bones", "skeleton"),
            "mesh": ("mesh", "meshes", "geometry", "geo"),
            "camera": ("camera", "cameras"),
            "light": ("light", "lights"),
            "locator": ("locator", "locators"),
            "nurbsCurve": ("curve", "curves", "nurbs curve", "nurbs curves"),
            "transform": ("transform", "transforms"),
            "parentConstraint": ("parent constraint", "parent constraints"),
            "orientConstraint": ("orient constraint", "orient constraints"),
            "pointConstraint": ("point constraint", "point constraints"),
            "scaleConstraint": ("scale constraint", "scale constraints"),
            "aimConstraint": ("aim constraint", "aim constraints"),
            "skinCluster": ("skincluster", "skin cluster", "skin clusters"),
            "shadingEngine": ("shading engine", "shading engines", "materials", "material", "shader", "shaders"),
        }
        for maya_type, aliases in maya_type_aliases.items():
            if any(_word_in_text(q, alias) for alias in aliases):
                params["type"] = maya_type
                break
        type_match = re.search(r"\btype\s*=?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text or "", re.IGNORECASE)
        if type_match:
            params["type"] = type_match.group(1)
        if re.search(r"\b(control|controls|ctrl|ctrls)\b", q):
            params["name_patterns"] = ["*ctrl*", "*_ctrl*", "*CTRL*"]
        name_match = re.search(r"\b(?:named|called|matching|match|pattern)\s+['\"]?([^'\"\n]+?)['\"]?(?:$|[.,;])", text or "", re.IGNORECASE)
        if name_match:
            params["name_patterns"] = [name_match.group(1).strip()]
        contains_match = re.search(
            r"\b(?:names?\s+)?(?:contain|contains|containing|include|includes|including)\s+['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?",
            text or "",
            re.IGNORECASE,
        )
        if contains_match:
            contains_value = contains_match.group(1).strip().rstrip(".,;:")
            params["name_patterns"] = [f"*{contains_value}*"]
        first_n = re.search(r"\bfirst\s+(\d+)\b", q)
        if first_n:
            params["limit"] = int(first_n.group(1))
        up_to_n = re.search(r"\b(?:up to|at most|max(?:imum)?(?: of)?)\s+(\d+)\b", q)
        if up_to_n:
            params["limit"] = int(up_to_n.group(1))
        limit_match = re.search(r"\blimit\s+(\d+)\b", q)
        if limit_match:
            params["limit"] = int(limit_match.group(1))
        params["first_only"] = bool(re.search(r"\b(first|top|initial)\b", q) and not first_n)
        params["long"] = bool(re.search(r"\b(long|full path|full name|dag path)\b", q))
        params["flatten"] = bool(re.search(r"\b(flatten|components?)\b", q))
            
    # Try to extract file paths or asset paths
    paths = []
    # Match Windows paths or Unix paths or Unreal-like package paths
    for match in re.finditer(r"([A-Za-z]:[\\/][^'\"\s]+|/[A-Za-z0-9_/.-]+|['\"][^'\"\s]+\.[A-Za-z0-9]+['\"])", text):
        path = match.group(1).strip("'\"").replace("\\", "/")
        if path not in paths:
            paths.append(path)
            
    if host == "maya" and operation in MAYA_OPERATIONS:
        params.update(_build_maya_operation_params(operation, text))
    elif host == "blender" and operation in BLENDER_OPERATIONS:
        params.update(_build_blender_operation_params(operation, text))

    if operation == "rigging.create_rig":
        char_match = re.search(r"\b(?:character|model|rig)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        if char_match:
            val = char_match.group(1)
            if val.lower() in {"for", "the", "a", "an", "in", "of", "to", "with", "at", "my"} or val.lower() == "character":
                char_spec = re.search(r"\b(?:character|model)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
                if char_spec:
                    val = char_spec.group(1)
            if val.lower() not in {"mesh", "skeleton", "rig"}:
                params["character_name"] = val
        # Suffix/naming heuristic
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params["character_name"] = name_match.group(1)
        if paths:
            params["mesh_path"] = paths[0]
            if len(paths) > 1:
                params["skeleton_path"] = paths[1]
                
    elif operation == "rigging.auto_skinner":
        mesh_match = re.search(r"\b(?:mesh|weights|skin)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        if mesh_match and mesh_match.group(1).lower() not in {"mesh", "skeleton", "rig"}:
            params["mesh_name"] = mesh_match.group(1)
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params["mesh_name"] = name_match.group(1)

    elif operation in ("animation.export", "io.export_fbx", "io.import_fbx", "render.render_scene", "project.create", "textures.export", "assets.import_fbx", "scene.add_prefab"):
        path_key = "export_path" if operation == "animation.export" else (
            "mesh_path" if operation == "project.create" else (
                "output_path" if operation in ("render.render_scene", "textures.export") else (
                    "prefab_path" if operation == "scene.add_prefab" else "filepath"
                )
            )
        )
        if paths:
            params[path_key] = paths[0]
            
    elif operation == "material.apply" and host == "substance_painter":
        mat_match = re.search(r"\b(?:material|smart material|texture set)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        if mat_match:
            params["material_name"] = mat_match.group(1)
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params["material_name"] = name_match.group(1)
            
    elif operation in ("character.create_character", "character.plot_animation") and host == "motionbuilder":
        char_match = re.search(r"\b(?:character|model|definition)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        if char_match:
            params["character_name"] = char_match.group(1)
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params["character_name"] = name_match.group(1)
            
    elif operation in ("prefab.create", "material.create") and host == "unity":
        key_name = "gameobject_name" if operation == "prefab.create" else "material_name"
        target_match = re.search(r"\b(?:gameobject|object|go|mesh|material|mat)\s+([A-Za-z0-9_]+)\b", text, re.IGNORECASE)
        if target_match:
            params[key_name] = target_match.group(1)
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text, re.IGNORECASE)
        if name_match:
            params[key_name] = name_match.group(1)
            
    # Try to extract frames
    frames = re.findall(r"\b(\d+)\b", text)
    if frames:
        if operation == "animation.bake":
            params["start_frame"] = int(frames[0])
            if len(frames) > 1:
                params["end_frame"] = int(frames[1])
            else:
                params["end_frame"] = int(frames[0]) + 100
        elif operation == "animation.export":
            params["start_frame"] = int(frames[0])
            if len(frames) > 1:
                params["end_frame"] = int(frames[1])

    return params


def _strip_quotes(value: str) -> str:
    return str(value or "").strip().strip("'\"`")


def _split_maya_names(raw: str) -> list[str]:
    raw = re.split(
        r"\b(?:so|to verify|to check|if|only if|when|while|because|and report|report|but|then)\b",
        raw or "",
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.sub(r"\b(objects?|nodes?|transforms?|joints?|influences?)\b", "", raw or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:with|without|no)\s+offset\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(" and ", ",")
    names: list[str] = []
    for token in re.split(r"[,\s]+", cleaned):
        token = _strip_quotes(token)
        if not token:
            continue
        if token.lower() in {
            "maya", "the", "to", "from", "with", "a", "an", "selected",
            "selection", "current", "object", "objects", "mesh", "joint",
            "joints", "influence", "influences", "using", "use", "bind",
            "skin", "smooth", "control", "exists", "existing", "verify", "check", "report",
        }:
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_:|.-]*$", token):
            names.append(token)
    return names


def _extract_maya_plugs(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z_][A-Za-z0-9_:|.-]*\.[A-Za-z_][A-Za-z0-9_]*\b", text or "")


def _extract_json_tail(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    start = raw.find("{")
    if start < 0:
        return {}
    try:
        value = json.loads(raw[start:])
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_scalar(value: str) -> Any:
    raw = _strip_quotes(value)
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    return raw


def _extract_arg_list(text: str) -> list[Any]:
    match = re.search(r"\b(?:args?|with args?)\s*[:=]\s*(\[[^\]]*\])", text or "", re.IGNORECASE)
    if match:
        try:
            value = json.loads(match.group(1).replace("'", '"'))
            if isinstance(value, list):
                return value
        except Exception:
            pass
    return []


def _extract_kwargs(text: str) -> dict[str, Any]:
    match = re.search(r"\b(?:kwargs?|with kwargs?)\s*[:=]\s*(\{[^}]*\})", text or "", re.IGNORECASE)
    if match:
        try:
            value = json.loads(match.group(1).replace("'", '"'))
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    pairs = {}
    for key, value in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,\s]+)", text or ""):
        if key not in {"args", "kwargs"}:
            pairs[key] = _parse_scalar(value)
    return pairs


def _extract_function_path(text: str) -> str:
    patterns = [
        r"\b((?:maya\.cmds|cmds|maya\.api\.OpenMaya|maya\.OpenMaya|om2?|maya_tools)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b",
        r"\b(?:call|run|execute)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            path = match.group(1)
            if path.startswith("cmds."):
                return "maya.cmds." + path[len("cmds."):]
            if path.startswith("om2."):
                return "maya.api.OpenMaya." + path[len("om2."):]
            if path.startswith("om."):
                return "maya.OpenMaya." + path[len("om."):]
            return path
    return ""


def _extract_color(text: str) -> Any:
    lower = (text or "").lower()
    named = {
        "red": (1.0, 0.0, 0.0),
        "green": (0.0, 1.0, 0.0),
        "blue": (0.0, 0.0, 1.0),
        "yellow": (1.0, 1.0, 0.0),
        "orange": (1.0, 0.5, 0.0),
        "purple": (0.5, 0.0, 1.0),
        "black": (0.0, 0.0, 0.0),
        "white": (1.0, 1.0, 1.0),
        "gray": (0.5, 0.5, 0.5),
        "grey": (0.5, 0.5, 0.5),
    }
    for name, rgb in named.items():
        if _word_in_text(lower, name):
            return rgb
    hex_match = re.search(r"#?([0-9A-Fa-f]{6})\b", text or "")
    if hex_match:
        raw = hex_match.group(1)
        return tuple(int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    nums = re.findall(r"\b(?:0(?:\.\d+)?|1(?:\.0+)?|[2-9](?:\.\d+)?)\b", text or "")
    if len(nums) >= 3:
        vals = [float(v) for v in nums[:3]]
        if any(v > 1.0 for v in vals):
            vals = [max(0.0, min(v / 255.0, 1.0)) for v in vals]
        return tuple(vals)
    return None


def _word_in_text(text: str, word: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])", text or ""))


def _build_maya_operation_params(operation: str, text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    json_payload = _extract_json_tail(text)
    if json_payload:
        params.update(json_payload)

    if operation == "navigation.frame_selection":
        match = re.search(r"\b(?:frame|focus|zoom)\s+(?:on\s+)?(.+)$", text or "", re.IGNORECASE)
        if match and "selected" not in match.group(1).lower() and "selection" not in match.group(1).lower():
            params["objects"] = _split_maya_names(match.group(1))

    elif operation == "navigation.open_panel":
        panel_aliases = {
            "outliner": "outliner",
            "node editor": "node_editor",
            "graph editor": "graph_editor",
            "hypershade": "hypershade",
            "script editor": "script_editor",
            "connection editor": "connection_editor",
            "attribute editor": "attribute_editor",
            "channel box": "channel_box",
        }
        lower = (text or "").lower()
        for alias, panel in panel_aliases.items():
            if alias in lower:
                params["panel"] = panel
                break

    elif operation == "scene.select":
        match = re.search(r"\b(?:select|highlight)\s+(.+)$", text or "", re.IGNORECASE)
        if match:
            params["objects"] = _split_maya_names(match.group(1))

    elif operation == "scene.move":
        match = re.search(r"\b(?:move|translate|offset|nudge)\s+([A-Za-z_][A-Za-z0-9_:|.-]*)\b", text or "", re.IGNORECASE)
        if match:
            params["objects"] = [match.group(1)]
        amount_match = re.search(r"\b(?:up|down|left|right|forward|back|backward)?\s*(-?\d+(?:\.\d+)?)\s*(?:units?)?\s*(?:on|in|along)?\s*([XYZ])?\b", text or "", re.IGNORECASE)
        amount = float(amount_match.group(1)) if amount_match else 0.0
        lower = (text or "").lower()
        axis = (amount_match.group(2).lower() if amount_match and amount_match.group(2) else "")
        if not axis:
            axis = "y" if re.search(r"\b(up|down)\b", lower) else ("x" if re.search(r"\b(left|right)\b", lower) else "z")
        if "down" in lower or "left" in lower or "back" in lower:
            amount = -abs(amount)
        params["translation"] = {
            "x": [amount, 0.0, 0.0],
            "y": [0.0, amount, 0.0],
            "z": [0.0, 0.0, amount],
        }.get(axis, [0.0, amount, 0.0])
        params["relative"] = True
        if re.search(r"\b(?:keep|leave|make)\s+(?:it|them|the object|the objects)?\s*selected\b|\bselect\s+(?:it|them)\b", text or "", re.IGNORECASE):
            params["select_after"] = True

    elif operation == "scene.create_locator":
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?", text or "", re.IGNORECASE)
        if name_match:
            params["name"] = name_match.group(1)
        if re.search(r"\b(do not|don't|dont)\s+select\b", text or "", re.IGNORECASE):
            params["select"] = False

    elif operation == "scene.create_control":
        name_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_:|.-]*)['\"]?", text or "", re.IGNORECASE)
        if name_match:
            params["name"] = name_match.group(1)
        if re.search(r"\b(circle|nurbs\s+circle)\b", text or "", re.IGNORECASE):
            params["shape"] = "circle"
        if re.search(r"\bif\b.{0,80}\b(?:does\s+not|doesn't|doesnt|not)\s+exist\b|\bif\b.{0,80}\bmissing\b", text or "", re.IGNORECASE):
            params["if_missing"] = True
        xyz = {}
        for axis, value in re.findall(r"\b([XYZ])\s*(-?\d+(?:\.\d+)?)\b", text or "", re.IGNORECASE):
            xyz[axis.lower()] = float(value)
        if len(xyz) == 3:
            params["position"] = [xyz["x"], xyz["y"], xyz["z"]]
        if re.search(r"\b(do not|don't|dont)\s+select\b", text or "", re.IGNORECASE):
            params["select"] = False
        elif re.search(r"\bselect\b", text or "", re.IGNORECASE):
            params["select"] = True

    elif operation in {"node.connect_attr", "node.disconnect_attr"}:
        plugs = _extract_maya_plugs(text)
        if len(plugs) >= 2:
            params["source_attr"] = plugs[0]
            params["destination_attr"] = plugs[1]
        if "without force" in (text or "").lower() or "no force" in (text or "").lower():
            params["force"] = False

    elif operation == "constraints.create":
        lower = (text or "").lower()
        for ctype in ("parent", "orient", "point", "scale", "aim"):
            if re.search(rf"\b{ctype}\s+(?:constraint|constrain|constrian|consrain)\b", lower):
                params["constraint_type"] = ctype
                break
        match = re.search(
            r"\b(?:parent|orient|point|scale|aim)\s+(?:constraint|constrain|constrian|consrain)\s+"
            r"(?:the\s+)?(?P<driven>[A-Za-z_][A-Za-z0-9_:|.-]*)\s+to\s+(?P<targets>.+)$",
            text or "",
            re.IGNORECASE,
        )
        if match:
            params["driven"] = match.group("driven")
            params["targets"] = _split_maya_names(match.group("targets"))
        else:
            names = _split_maya_names(text or "")
            if len(names) >= 2:
                params.setdefault("targets", names[:-1])
                params.setdefault("driven", names[-1])
        params["maintain_offset"] = "no offset" not in lower and "without offset" not in lower

    elif operation in {"material.create", "material.assign", "material.set_color"}:
        name_match = re.search(r"\b(?:material|shader|mat)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text or "", re.IGNORECASE)
        called_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text or "", re.IGNORECASE)
        if name_match:
            params["material_name"] = name_match.group(1)
        if called_match:
            params["material_name"] = called_match.group(1)
        shader_match = re.search(r"\b(lambert|blinn|phong|standardSurface|aiStandardSurface)\b", text or "", re.IGNORECASE)
        if shader_match:
            params["shader_type"] = shader_match.group(1)
        color = _extract_color(text)
        if color is not None:
            params["color"] = color
        if operation == "material.assign":
            object_match = re.search(r"\b(?:to|onto|on)\s+(.+)$", text or "", re.IGNORECASE)
            if object_match and "selection" not in object_match.group(1).lower():
                params["objects"] = _split_maya_names(object_match.group(1))

    elif operation in {"skin.bind", "skin.add_influence", "skin.remove_influence", "skin.set_weights"}:
        mesh_match = re.search(r"\b(?:mesh|geometry|skin)\s+([A-Za-z_][A-Za-z0-9_:|.-]*)\b", text or "", re.IGNORECASE)
        if mesh_match and mesh_match.group(1).lower() not in {"to", "with", "using", "mesh"}:
            params["mesh"] = mesh_match.group(1)
        names = _split_maya_names(text or "")
        joint_like = [name for name in names if re.search(r"(?:_jnt|jnt_|joint|bind|root|spine|clav|arm|leg|hand|foot)", name, re.IGNORECASE)]
        if operation == "skin.bind":
            if not params.get("mesh") and names:
                params["mesh"] = names[0]
            influences = [name for name in names if name != params.get("mesh")]
            params["influences"] = joint_like or influences
            params["to_selected"] = "selected" in (text or "").lower() or "selection" in (text or "").lower()
        elif operation in {"skin.add_influence", "skin.remove_influence"}:
            if joint_like:
                params["influence"] = joint_like[-1]
            elif names:
                params["influence"] = names[-1]
        elif operation == "skin.set_weights":
            if joint_like:
                params["influence"] = joint_like[-1]
            weight_match = re.search(r"\b(?:weight|value)\s+([01](?:\.\d+)?|\.\d+)\b", text or "", re.IGNORECASE)
            if weight_match:
                params["weight"] = float(weight_match.group(1))
            component_matches = re.findall(r"\b[A-Za-z_][A-Za-z0-9_:|.-]*\.vtx\[[^\]]+\]", text or "")
            if component_matches:
                params["components"] = component_matches

    elif operation in {"api.call", "tool.call"}:
        function = _extract_function_path(text)
        if operation == "tool.call" and function and not function.startswith("maya_tools."):
            function = "maya_tools." + function
        if function:
            params["function"] = function
        args = _extract_arg_list(text)
        kwargs = _extract_kwargs(text)
        if args:
            params["args"] = args
        if kwargs:
            params["kwargs"] = kwargs

    return params


def maya_operation_code(operation: str, params: dict[str, Any]) -> str:
    """Generate reviewed Maya Python for built-in Tech Connector Maya operations."""
    params = dict(params or {})
    payload = json.dumps(params, default=str)
    return f"""
import importlib
import json
import traceback

import maya.cmds as cmds

try:
    import maya.api.OpenMaya as om2
except Exception:
    om2 = None
try:
    import maya.OpenMaya as om
except Exception:
    om = None

params = json.loads({payload!r})
operation = {operation!r}

def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]

def _require_objects(names):
    missing = [name for name in _as_list(names) if not cmds.objExists(name)]
    if missing:
        raise RuntimeError("Missing Maya object(s): " + ", ".join(missing))

def _skin_cluster_for(mesh):
    history = cmds.listHistory(mesh) or []
    clusters = cmds.ls(history, type="skinCluster") or []
    if not clusters:
        raise RuntimeError("No skinCluster found for " + mesh)
    return clusters[0]

def _material_sg(material):
    sgs = cmds.listConnections(material, type="shadingEngine") or []
    if sgs:
        return sgs[0]
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=material + "SG")
    cmds.connectAttr(material + ".outColor", sg + ".surfaceShader", force=True)
    return sg

def _coerce_color(value):
    if not value:
        return None
    if isinstance(value, str):
        named = {{
            "red": (1.0, 0.0, 0.0), "green": (0.0, 1.0, 0.0), "blue": (0.0, 0.0, 1.0),
            "yellow": (1.0, 1.0, 0.0), "orange": (1.0, 0.5, 0.0), "purple": (0.5, 0.0, 1.0),
            "black": (0.0, 0.0, 0.0), "white": (1.0, 1.0, 1.0), "gray": (0.5, 0.5, 0.5), "grey": (0.5, 0.5, 0.5),
        }}
        if value.lower() in named:
            return named[value.lower()]
    vals = list(value)
    if len(vals) < 3:
        raise RuntimeError("Color must contain three values")
    vals = [float(v) for v in vals[:3]]
    if any(v > 1.0 for v in vals):
        vals = [max(0.0, min(v / 255.0, 1.0)) for v in vals]
    return tuple(vals)

def _import_callable(path):
    if path.startswith("cmds."):
        path = "maya.cmds." + path[len("cmds."):]
    if path.startswith("om2."):
        path = "maya.api.OpenMaya." + path[len("om2."):]
    if path.startswith("om."):
        path = "maya.OpenMaya." + path[len("om."):]
    if path.startswith("maya.cmds."):
        return getattr(cmds, path.rsplit(".", 1)[1])
    if path.startswith("maya.api.OpenMaya."):
        if om2 is None:
            raise RuntimeError("maya.api.OpenMaya is unavailable")
        return getattr(om2, path.rsplit(".", 1)[1])
    if path.startswith("maya.OpenMaya."):
        if om is None:
            raise RuntimeError("maya.OpenMaya is unavailable")
        return getattr(om, path.rsplit(".", 1)[1])
    module_path, func_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)

try:
    if operation == "navigation.frame_selection":
        objects = _as_list(params.get("objects"))
        if objects:
            _require_objects(objects)
            cmds.select(objects, replace=True)
        cmds.viewFit()
        print("Framed Maya selection: " + str(cmds.ls(selection=True)))

    elif operation == "navigation.open_panel":
        panel = str(params.get("panel") or "").lower()
        commands = {{
            "outliner": lambda: cmds.OutlinerWindow(),
            "node_editor": lambda: cmds.NodeEditorWindow(),
            "graph_editor": lambda: cmds.GraphEditor(),
            "hypershade": lambda: cmds.HypershadeWindow(),
            "script_editor": lambda: cmds.ScriptEditor(),
            "connection_editor": lambda: cmds.ConnectionEditor(),
            "attribute_editor": lambda: cmds.AttributeEditor(),
            "channel_box": lambda: cmds.ChannelBoxWindow(),
        }}
        if panel not in commands:
            raise RuntimeError("Unknown Maya panel: " + panel)
        commands[panel]()
        print("Opened Maya panel: " + panel)

    elif operation == "scene.select":
        objects = _as_list(params.get("objects"))
        if not objects:
            raise RuntimeError("No objects supplied")
        _require_objects(objects)
        cmds.select(objects, replace=bool(params.get("replace", True)))
        print("Selected Maya objects: " + str(cmds.ls(selection=True)))

    elif operation == "scene.move":
        objects = _as_list(params.get("objects"))
        translation = _as_list(params.get("translation"))
        if len(translation) != 3:
            raise RuntimeError("translation must be [x, y, z]")
        _require_objects(objects)
        before = {{obj: cmds.xform(obj, q=True, ws=True, t=True) for obj in objects}}
        cmds.move(
            float(translation[0]),
            float(translation[1]),
            float(translation[2]),
            objects,
            relative=bool(params.get("relative", True)),
        )
        if bool(params.get("select_after", False)):
            cmds.select(objects, replace=True)
        after = {{obj: cmds.xform(obj, q=True, ws=True, t=True) for obj in objects}}
        print("Moved Maya objects: " + str({{"before": before, "after": after, "translation": translation}}))

    elif operation == "scene.ls":
        flags = {{}}
        if params.get("selection"):
            flags["selection"] = True
        if params.get("type"):
            flags["type"] = params.get("type")
        if params.get("long"):
            flags["long"] = True
        if params.get("flatten"):
            flags["flatten"] = True
        patterns = _as_list(params.get("name_patterns"))
        items = []
        if patterns:
            for pattern in patterns:
                for item in cmds.ls(pattern, **flags) or []:
                    if item not in items:
                        items.append(item)
        else:
            items = cmds.ls(**flags) or []
        limit = int(params.get("limit") or 50)
        if limit > 0:
            items = items[:limit]
        print(json.dumps({{"kind": "maya.cmds.ls", "items": items, "count": len(items), "flags": flags, "patterns": patterns}}))

    elif operation == "scene.create_locator":
        name = str(params.get("name") or "locator")
        created = cmds.spaceLocator(name=name)
        if bool(params.get("select", True)):
            cmds.select(created[0], replace=True)
        print("Created Maya locator: " + created[0])

    elif operation == "scene.create_control":
        name = str(params.get("name") or "control_ctrl")
        shape = str(params.get("shape") or "circle").lower()
        if bool(params.get("if_missing", False)) and cmds.objExists(name):
            created = name
        else:
            if shape not in {{"circle"}}:
                raise RuntimeError("Unsupported control shape: " + shape)
            created = cmds.circle(name=name, normal=(0, 1, 0), radius=1.0)[0]
        position = params.get("position")
        if position:
            if len(position) != 3:
                raise RuntimeError("position must be [x, y, z]")
            cmds.xform(created, ws=True, t=[float(position[0]), float(position[1]), float(position[2])])
        if bool(params.get("select", True)):
            cmds.select(created, replace=True)
        print(json.dumps({{"created_or_reused": created, "position": cmds.xform(created, q=True, ws=True, t=True), "selection": cmds.ls(selection=True) or []}}))

    elif operation == "modeling.create_primitive":
        primitive = str(params.get("primitive_type") or "cube").lower()
        name = params.get("name") or primitive
        size = float(params.get("size", 1.0))
        commands = {{
            "cube": lambda: cmds.polyCube(name=name, width=size, height=size, depth=size),
            "sphere": lambda: cmds.polySphere(name=name, radius=size * 0.5),
            "cylinder": lambda: cmds.polyCylinder(name=name, radius=size * 0.5, height=size),
            "cone": lambda: cmds.polyCone(name=name, radius=size * 0.5, height=size),
            "plane": lambda: cmds.polyPlane(name=name, width=size, height=size),
            "torus": lambda: cmds.polyTorus(name=name, majorRadius=size * 0.5, minorRadius=size * 0.125),
        }}
        if primitive not in commands:
            raise RuntimeError("Unsupported primitive type: " + primitive)
        created = commands[primitive]()
        cmds.select(created[0], replace=True)
        print("Created Maya primitive: " + created[0])

    elif operation == "node.connect_attr":
        source = params.get("source_attr")
        dest = params.get("destination_attr")
        if not source or not dest:
            raise RuntimeError("source_attr and destination_attr are required")
        cmds.connectAttr(source, dest, force=bool(params.get("force", True)))
        print("Connected " + source + " -> " + dest)

    elif operation == "node.disconnect_attr":
        source = params.get("source_attr")
        dest = params.get("destination_attr")
        if not source or not dest:
            raise RuntimeError("source_attr and destination_attr are required")
        cmds.disconnectAttr(source, dest)
        print("Disconnected " + source + " -> " + dest)

    elif operation == "constraints.create":
        ctype = str(params.get("constraint_type") or "parent").lower()
        targets = _as_list(params.get("targets"))
        driven = params.get("driven")
        _require_objects(targets + [driven])
        commands = {{
            "parent": cmds.parentConstraint,
            "orient": cmds.orientConstraint,
            "point": cmds.pointConstraint,
            "scale": cmds.scaleConstraint,
            "aim": cmds.aimConstraint,
        }}
        if ctype not in commands:
            raise RuntimeError("Unsupported constraint type: " + ctype)
        result = commands[ctype](targets, driven, maintainOffset=bool(params.get("maintain_offset", True)))
        cmds.select(driven, replace=True)
        print("Created " + ctype + " constraint: " + str(result[0] if result else ""))

    elif operation == "material.create":
        name = params.get("material_name")
        if not name:
            raise RuntimeError("material_name is required")
        shader = params.get("shader_type") or "lambert"
        material = name if cmds.objExists(name) else cmds.shadingNode(shader, asShader=True, name=name)
        sg = _material_sg(material)
        color = _coerce_color(params.get("color"))
        if color is not None and cmds.attributeQuery("color", node=material, exists=True):
            cmds.setAttr(material + ".color", color[0], color[1], color[2], type="double3")
        print("Created Maya material: " + material + " shadingGroup=" + sg)

    elif operation == "material.assign":
        material = params.get("material_name")
        if not material or not cmds.objExists(material):
            raise RuntimeError("Material does not exist: " + str(material))
        objects = _as_list(params.get("objects")) or cmds.ls(selection=True)
        if not objects:
            raise RuntimeError("No objects selected or supplied for material assignment")
        _require_objects(objects)
        sg = _material_sg(material)
        cmds.sets(objects, edit=True, forceElement=sg)
        print("Assigned material " + material + " to " + str(objects))

    elif operation == "material.set_color":
        material = params.get("material_name")
        if not material or not cmds.objExists(material):
            raise RuntimeError("Material does not exist: " + str(material))
        color = _coerce_color(params.get("color"))
        if color is None:
            raise RuntimeError("color is required")
        cmds.setAttr(material + ".color", color[0], color[1], color[2], type="double3")
        print("Set material color " + material + " -> " + str(color))

    elif operation == "skin.bind":
        mesh = params.get("mesh")
        influences = _as_list(params.get("influences"))
        if params.get("to_selected") and (not mesh or not influences):
            selected = cmds.ls(selection=True) or []
            if len(selected) >= 2:
                mesh = selected[-1]
                influences = selected[:-1]
        _require_objects(influences + [mesh])
        cluster = cmds.skinCluster(
            influences,
            mesh,
            toSelectedBones=True,
            maximumInfluences=int(params.get("maximum_influences", 4)),
            dropoffRate=float(params.get("dropoff_rate", 4.0)),
        )
        print("Bound skinCluster: " + str(cluster[0] if cluster else ""))

    elif operation == "skin.add_influence":
        mesh = params.get("mesh")
        influence = params.get("influence")
        _require_objects([mesh, influence])
        cluster = _skin_cluster_for(mesh)
        cmds.skinCluster(cluster, edit=True, addInfluence=influence, weight=float(params.get("weight", 0.0)))
        print("Added influence " + influence + " to " + cluster)

    elif operation == "skin.remove_influence":
        mesh = params.get("mesh")
        influence = params.get("influence")
        _require_objects([mesh, influence])
        cluster = _skin_cluster_for(mesh)
        cmds.skinCluster(cluster, edit=True, removeInfluence=influence)
        print("Removed influence " + influence + " from " + cluster)

    elif operation == "skin.set_weights":
        mesh = params.get("mesh")
        influence = params.get("influence")
        weight = params.get("weight")
        _require_objects([mesh, influence])
        if weight is None:
            raise RuntimeError("weight is required")
        cluster = _skin_cluster_for(mesh)
        components = _as_list(params.get("components")) or cmds.ls(selection=True, flatten=True) or [mesh]
        cmds.skinPercent(cluster, components, transformValue=[(influence, float(weight))])
        print("Set skin weight " + str(weight) + " for " + influence + " on " + str(components))

    elif operation in {{"api.call", "tool.call"}}:
        function = params.get("function")
        if not function:
            raise RuntimeError("function is required")
        callable_obj = _import_callable(function)
        result = callable_obj(*_as_list(params.get("args")), **(params.get("kwargs") or {{}}))
        print(result)

    else:
        raise RuntimeError("Unsupported Maya generated operation: " + operation)
except Exception:
    traceback.print_exc()
"""


def _build_blender_operation_params(operation: str, text: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    json_payload = _extract_json_tail(text)
    if json_payload:
        params.update(json_payload)

    if operation == "script.run":
        code_match = re.search(r"\b(?:code|script)\s*[:=]\s*(.+)$", text or "", re.IGNORECASE | re.DOTALL)
        if code_match:
            params["code"] = code_match.group(1).strip()
        elif "bpy." in (text or ""):
            params["code"] = (text or "")[(text or "").find("bpy."):]

    elif operation == "api.call":
        function = _extract_blender_function_path(text)
        if function:
            params["function"] = function
        args = _extract_arg_list(text)
        kwargs = _extract_kwargs(text)
        if args:
            params["args"] = args
        if kwargs:
            params["kwargs"] = kwargs

    elif operation == "navigation.frame_selection":
        match = re.search(r"\b(?:frame|focus|zoom)\s+(?:on\s+)?(.+)$", text or "", re.IGNORECASE)
        if match and "selected" not in match.group(1).lower() and "selection" not in match.group(1).lower():
            params["objects"] = _split_blender_names(match.group(1))

    elif operation == "scene.select":
        match = re.search(r"\b(?:select|highlight)\s+(.+)$", text or "", re.IGNORECASE)
        if match:
            params["objects"] = _split_blender_names(match.group(1))

    elif operation in {"material.create", "material.assign", "material.set_color"}:
        name_match = re.search(r"\b(?:material|shader|mat)\s+['\"]?([A-Za-z_][A-Za-z0-9_.-]*)['\"]?", text or "", re.IGNORECASE)
        called_match = re.search(r"\b(?:named|called|name)\s+['\"]?([A-Za-z_][A-Za-z0-9_.-]*)['\"]?", text or "", re.IGNORECASE)
        if name_match:
            params["material_name"] = name_match.group(1)
        if called_match:
            params["material_name"] = called_match.group(1)
        color = _extract_color(text)
        if color is not None:
            params["color"] = color
        if operation == "material.assign":
            object_match = re.search(r"\b(?:to|onto|on)\s+(.+)$", text or "", re.IGNORECASE)
            if object_match and "selection" not in object_match.group(1).lower():
                params["objects"] = _split_blender_names(object_match.group(1))

    return params


def _split_blender_names(raw: str) -> list[str]:
    cleaned = re.sub(r"\b(objects?|meshes?|nodes?)\b", "", raw or "", flags=re.IGNORECASE)
    cleaned = cleaned.replace(" and ", ",")
    names: list[str] = []
    for token in re.split(r"[,\n]+|\s{2,}", cleaned):
        token = _strip_quotes(token.strip())
        if not token:
            continue
        if token.lower() in {"blender", "the", "to", "from", "with", "a", "an", "selected", "selection", "current"}:
            continue
        token = re.sub(r"^(?:to|on|onto|and)\s+", "", token, flags=re.IGNORECASE).strip()
        if token:
            names.append(token)
    if len(names) == 1 and " " in names[0]:
        maybe = [
            _strip_quotes(item)
            for item in re.split(r"\s+", names[0])
            if item.lower() not in {"to", "on", "onto", "and", "the"}
        ]
        if len(maybe) > 1:
            return maybe
    return names


def _extract_blender_function_path(text: str) -> str:
    match = re.search(r"\b(bpy(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b", text or "")
    return match.group(1) if match else ""


def blender_operation_code(operation: str, params: dict[str, Any]) -> str:
    """Generate reviewed Blender Python for built-in Tech Connector Blender operations."""
    params = dict(params or {})
    payload = json.dumps(params, default=str)
    return f"""
import importlib
import json
import traceback

import bpy

params = json.loads({payload!r})
operation = {operation!r}

def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]

def _objects(names):
    result = []
    missing = []
    for name in _as_list(names):
        obj = bpy.data.objects.get(str(name))
        if obj:
            result.append(obj)
        else:
            missing.append(str(name))
    if missing:
        raise RuntimeError("Missing Blender object(s): " + ", ".join(missing))
    return result

def _selected_or_named(names):
    return _objects(names) if _as_list(names) else list(bpy.context.selected_objects)

def _coerce_color(value):
    if not value:
        return None
    if isinstance(value, str):
        named = {{
            "red": (1.0, 0.0, 0.0, 1.0), "green": (0.0, 1.0, 0.0, 1.0), "blue": (0.0, 0.0, 1.0, 1.0),
            "yellow": (1.0, 1.0, 0.0, 1.0), "orange": (1.0, 0.5, 0.0, 1.0), "purple": (0.5, 0.0, 1.0, 1.0),
            "black": (0.0, 0.0, 0.0, 1.0), "white": (1.0, 1.0, 1.0, 1.0), "gray": (0.5, 0.5, 0.5, 1.0), "grey": (0.5, 0.5, 0.5, 1.0),
        }}
        if value.lower() in named:
            return named[value.lower()]
    vals = list(value)
    if len(vals) < 3:
        raise RuntimeError("Color must contain at least three values")
    vals = [float(v) for v in vals[:4]]
    if any(v > 1.0 for v in vals[:3]):
        vals[:3] = [max(0.0, min(v / 255.0, 1.0)) for v in vals[:3]]
    if len(vals) == 3:
        vals.append(1.0)
    return tuple(vals[:4])

def _resolve_callable(path):
    if not path.startswith("bpy."):
        raise RuntimeError("Only bpy.* calls are supported by Blender api.call")
    obj = bpy
    for part in path.split(".")[1:]:
        obj = getattr(obj, part)
    if not callable(obj):
        raise RuntimeError(path + " is not callable")
    return obj

try:
    if operation == "script.run":
        code = params.get("code") or ""
        if not code.strip():
            raise RuntimeError("code is required")
        exec(code, {{"bpy": bpy}})
        print("Executed Blender script.")

    elif operation == "api.call":
        function = params.get("function") or ""
        callable_obj = _resolve_callable(function)
        result = callable_obj(*_as_list(params.get("args")), **(params.get("kwargs") or {{}}))
        print(result)

    elif operation == "navigation.frame_selection":
        objects = _objects(params.get("objects")) if _as_list(params.get("objects")) else list(bpy.context.selected_objects)
        if objects:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = objects[-1]
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                with bpy.context.temp_override(area=area, region=next((r for r in area.regions if r.type == "WINDOW"), None)):
                    bpy.ops.view3d.view_selected(use_all_regions=False)
                break
        print("Framed Blender selection: " + str([obj.name for obj in bpy.context.selected_objects]))

    elif operation == "scene.select":
        objects = _objects(params.get("objects"))
        if not objects:
            raise RuntimeError("objects is required")
        if params.get("replace", True):
            bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[-1]
        print("Selected Blender objects: " + str([obj.name for obj in objects]))

    elif operation == "modeling.create_primitive":
        primitive = str(params.get("primitive_type") or "cube").lower()
        name = params.get("name") or primitive
        location = params.get("location") or (0.0, 0.0, 0.0)
        scale = params.get("scale") or (1.0, 1.0, 1.0)
        ops = {{
            "cube": bpy.ops.mesh.primitive_cube_add,
            "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
            "cylinder": bpy.ops.mesh.primitive_cylinder_add,
            "cone": bpy.ops.mesh.primitive_cone_add,
            "plane": bpy.ops.mesh.primitive_plane_add,
            "torus": bpy.ops.mesh.primitive_torus_add,
        }}
        if primitive not in ops:
            raise RuntimeError("Unsupported primitive type: " + primitive)
        ops[primitive](location=location)
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        print("Created Blender primitive: " + obj.name)

    elif operation == "material.create":
        name = params.get("material_name")
        if not name:
            raise RuntimeError("material_name is required")
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = bool(params.get("use_nodes", True))
        color = _coerce_color(params.get("color"))
        if color is not None:
            mat.diffuse_color = color
            if mat.use_nodes:
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf and "Base Color" in bsdf.inputs:
                    bsdf.inputs["Base Color"].default_value = color
        print("Created Blender material: " + mat.name)

    elif operation == "material.assign":
        name = params.get("material_name")
        mat = bpy.data.materials.get(str(name))
        if mat is None:
            raise RuntimeError("Material does not exist: " + str(name))
        objects = _selected_or_named(params.get("objects"))
        if not objects:
            raise RuntimeError("No objects selected or supplied for material assignment")
        for obj in objects:
            if hasattr(obj.data, "materials"):
                if mat.name not in [slot.name for slot in obj.data.materials]:
                    obj.data.materials.append(mat)
                obj.active_material = mat
        print("Assigned Blender material " + mat.name + " to " + str([obj.name for obj in objects]))

    elif operation == "material.set_color":
        name = params.get("material_name")
        mat = bpy.data.materials.get(str(name))
        if mat is None:
            raise RuntimeError("Material does not exist: " + str(name))
        color = _coerce_color(params.get("color"))
        if color is None:
            raise RuntimeError("color is required")
        mat.diffuse_color = color
        if mat.use_nodes:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf and "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = color
        print("Set Blender material color " + mat.name + " -> " + str(color))

    else:
        raise RuntimeError("Unsupported Blender generated operation: " + operation)
except Exception:
    traceback.print_exc()
"""
