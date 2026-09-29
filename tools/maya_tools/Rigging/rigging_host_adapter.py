"""Maya translation endpoint for Tech Connector's DCC-neutral rigging UI."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from typing import Any

from maya import cmds

from maya_tools.Rigging import create_rig
from maya_tools.Rigging.mocap import setup_hik
from tech_connector.services.dcc.rigging_workspace_service import (
    CharacterDefinition,
    RiggingOperationResult,
    auto_map_character,
    mirror_character_slots,
    validate_character_definition,
)


HOST = "maya"


def reload_dependencies() -> str:
    """Refresh the complete Maya rig stack for bridge-driven operations."""
    global create_rig, setup_hik

    from maya_tools.Rigging import create_rig_core
    from maya_tools.Rigging import create_rig_modules
    from maya_tools.Rigging import enum_attrs
    from maya_tools.Rigging import rig_template
    from maya_tools.Rigging import skinning_utils
    from maya_tools.Utilities import dag, joints

    importlib.invalidate_caches()
    for module in (enum_attrs, skinning_utils, joints, dag, rig_template, setup_hik, create_rig_core):
        importlib.reload(module)

    modules_name = "maya_tools.Rigging.create_rig_modules"
    if (
            sys.modules.get(modules_name) is not create_rig_modules
            or getattr(create_rig_modules, "__name__", None) != modules_name
    ):
        sys.modules.pop(modules_name, None)
        importlib.import_module(modules_name)
    else:
        importlib.reload(create_rig_modules)

    create_rig = importlib.reload(create_rig)
    setup_hik = sys.modules["maya_tools.Rigging.mocap.setup_hik"]
    return str(getattr(create_rig_core, "RIG_BUILD_REVISION", "unknown"))


def _result(ok: bool, capability: str, message: str = "", **kwargs: Any) -> dict[str, Any]:
    return RiggingOperationResult(ok, capability, HOST, message, **kwargs).to_dict()


def scene_joints() -> dict[str, Any]:
    joints = []
    for joint in cmds.ls(type="joint", long=True) or []:
        parent = cmds.listRelatives(joint, parent=True, type="joint", fullPath=True) or []
        depth = max(0, joint.count("|") - 1)
        joints.append({
            "id": joint,
            "native_id": joint,
            "name": joint.split("|")[-1],
            "parent_id": parent[0] if parent else "",
            "depth": depth,
            "local_matrix": [float(value) for value in cmds.xform(joint, query=True, objectSpace=True, matrix=True)],
            "world_matrix": [float(value) for value in cmds.xform(joint, query=True, worldSpace=True, matrix=True)],
        })
    return _result(True, "host.query", data={"joints": joints})


def selection() -> dict[str, Any]:
    return _result(True, "host.query", data={"selection": cmds.ls(selection=True, long=True) or []})


def execute(capability: str, payload: dict[str, Any]) -> dict[str, Any]:
    handler = globals().get("_op_" + str(capability).replace(".", "_"))
    if handler is None:
        return _result(False, capability, f"Maya translation is not implemented: {capability}")
    try:
        return handler(dict(payload))
    except Exception as exc:
        return _result(False, capability, str(exc))


def _definition(value: Any) -> CharacterDefinition:
    if isinstance(value, CharacterDefinition):
        return value
    if isinstance(value, dict):
        if "schema" in value or "slots" in value:
            return CharacterDefinition.from_dict(value)
        return CharacterDefinition("Character", {str(key): str(node) for key, node in value.items() if node})
    raise ValueError("A portable character definition is required.")


def _maya_maps(definition: CharacterDefinition) -> tuple[dict[str, Any], dict[str, Any]]:
    body = copy.deepcopy(setup_hik.DEFAULT_JOINT_MAP)
    face = copy.deepcopy(setup_hik.DEFAULT_FACE_JOINT_MAP)
    for slot, joint in definition.slots.items():
        target = body if slot in body else face if slot in face else None
        if target is None:
            continue
        if "joints" in target[slot] and isinstance(joint, (list, tuple)):
            target[slot]["joints"] = list(joint)
        else:
            target[slot]["joint"] = str(joint)
    return body, face


def _op_definition_auto_map(payload: dict[str, Any]) -> dict[str, Any]:
    root = str(payload.get("root_joint") or "")
    rows = scene_joints()["data"]["joints"]
    if root:
        descendants = set(cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []) | {root}
        rows = [row for row in rows if row["id"] in descendants]
    definition = auto_map_character(rows, name=str(payload.get("name") or "Character"), source_provider="maya", source_root=root)
    validation = validate_character_definition(definition, rows)
    return _result(True, "definition.auto_map", f"Mapped {len(definition.slots)} Maya joints.",
                   data={"definition": definition.to_dict(), "validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_assign_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    joint = str(payload["joint"])
    if not cmds.objExists(joint) or cmds.nodeType(joint) != "joint":
        raise ValueError(f"Maya joint does not exist: {joint}")
    definition.slots[str(payload["slot"])] = joint
    return _result(True, "definition.assign_slot", "Assigned Maya character slot.", data={"definition": definition.to_dict()})


def _op_definition_clear_slot(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.slots.pop(str(payload["slot"]), None)
    return _result(True, "definition.clear_slot", "Cleared Maya character slot.", data={"definition": definition.to_dict()})


def _op_definition_mirror_slots(payload: dict[str, Any]) -> dict[str, Any]:
    definition = mirror_character_slots(_definition(payload.get("definition")), str(payload.get("source_side") or "left"))
    return _result(True, "definition.mirror_slots", "Mirrored Maya slot assignments.", data={"definition": definition.to_dict()})


def _op_definition_validate(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["mapping"])
    validation = validate_character_definition(definition, scene_joints()["data"]["joints"])
    return _result(validation.ok, "definition.validate", "Definition is valid." if validation.ok else "Definition needs attention.",
                   data={"validation": validation.to_dict()}, warnings=validation.warnings)


def _op_definition_set_reference_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload.get("definition"))
    definition.reference_pose = {
        joint: [float(value) for value in cmds.xform(joint, query=True, worldSpace=True, matrix=True)]
        for joint in set(definition.slots.values()) if cmds.objExists(joint)
    }
    return _result(True, "definition.set_reference_pose", "Captured Maya reference pose.",
                   changed_ids=list(definition.reference_pose), data={"definition": definition.to_dict()})


def _op_definition_import(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.import", f"Loaded {definition.name} into the shared workspace.", data={"definition": definition.to_dict()})


def _op_definition_export(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    return _result(True, "definition.export", f"Prepared {definition.name} for export.", data={"definition": definition.to_dict()})


_op_retarget_create_definition = _op_definition_import
_op_retarget_validate_definition = _op_definition_validate


def _op_rig_build_full(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    requested_modules = list(payload.get("modules") or [])
    if requested_modules:
        created = []
        warnings = []
        for module in requested_modules:
            try:
                result = _op_rig_build_module({"module": module, "definition": definition.to_dict(), "options": payload.get("options") or {}})
                created.extend(result.get("created_ids") or [])
            except Exception as exc:
                warnings.append(f"{module}: {exc}")
        return _result(not warnings, "rig.build_full", f"Built {len(requested_modules) - len(warnings)} Maya rig modules.",
                       created_ids=created, warnings=warnings, data={"modules": requested_modules})
    body, face = _maya_maps(definition)
    before = set(cmds.ls(long=True) or [])
    result = create_rig.create_rig_from_mapping(body, face)
    created = sorted(set(cmds.ls(long=True) or []) - before)
    return _result(True, "rig.build_full", "Built Maya control rig from the portable definition.",
                   created_ids=created, data={"maya_result": result})


def _op_rig_build_module(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["definition"])
    body, face = _maya_maps(definition)
    module = str(payload["module"]).lower()
    routes = {
        "left_arm": (create_rig.rig_arm_module, ("l", body)),
        "right_arm": (create_rig.rig_arm_module, ("r", body)),
        "left_leg": (create_rig.rig_leg_module, ("l", body)),
        "right_leg": (create_rig.rig_leg_module, ("r", body)),
        "left_clavicle": (create_rig.rig_clavicle_module, ("l", body)),
        "right_clavicle": (create_rig.rig_clavicle_module, ("r", body)),
        "root": (create_rig.rig_root_module, (body,)),
        "pelvis": (create_rig.rig_pelvis_module, (body,)),
        "spine": (create_rig.rig_spine_module, (body,)),
        "neck": (create_rig.rig_neck_module, (body,)),
        "head": (create_rig.rig_head_module, (body, face)),
        "brows": (create_rig.rig_brows_module, ("l", face)),
        "eyes": (create_rig.rig_eyes_module, (face,)),
        "mouth": (create_rig.rig_mouth_module, (face,)),
        "tongue": (create_rig.rig_tongue_module, (face,)),
        "teeth": (create_rig.rig_teeth_module, (face,)),
    }
    if module not in routes:
        raise ValueError(f"Maya Create Rig has no module route for {module}")
    before = set(cmds.ls(long=True) or [])
    function, arguments = routes[module]
    function(*arguments)
    created = sorted(set(cmds.ls(long=True) or []) - before)
    return _result(True, "rig.build_module", f"Built Maya module {module}.", created_ids=created, data={"module": module})


def _op_rig_remove_module(payload: dict[str, Any]) -> dict[str, Any]:
    module = str(payload["module"]).lower()
    definition = _definition(payload.get("definition") or {"slots": {}})
    body, face = _maya_maps(definition)
    routes = {
        "left_arm": (create_rig.remove_arm_module, ("l", body)), "right_arm": (create_rig.remove_arm_module, ("r", body)),
        "left_leg": (create_rig.remove_leg_module, ("l", body)), "right_leg": (create_rig.remove_leg_module, ("r", body)),
        "root": (create_rig.remove_root_module, (body,)), "pelvis": (create_rig.remove_pelvis_module, (body,)),
        "spine": (create_rig.remove_spine_module, (body,)), "neck": (create_rig.remove_neck_module, (body,)),
        "head": (create_rig.remove_head_module, (body,)), "brows": (create_rig.remove_brows_module, ("l", face)),
        "eyes": (create_rig.remove_eyes_module, (face,)), "mouth": (create_rig.remove_mouth_module, (face,)),
        "tongue": (create_rig.remove_tongue_module, (face,)), "teeth": (create_rig.remove_teeth_module, (face,)),
    }
    if module not in routes:
        raise ValueError(f"Maya Create Rig has no removal route for {module}")
    function, arguments = routes[module]
    result = function(*arguments)
    return _result(True, "rig.remove_module", f"Removed Maya module {module}.", data={"maya_result": result})


def _op_rig_rebuild_module(payload: dict[str, Any]) -> dict[str, Any]:
    _op_rig_remove_module(payload)
    result = _op_rig_build_module(payload)
    result["capability"] = "rig.rebuild_module"
    return result


def _op_rig_create_control(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload["target"])
    result = create_rig.create_joint_controls(
        [target], control_shape=str(payload.get("shape") or "circle"),
        root_parent=str(payload.get("parent") or "") or None,
        keep_constraint=bool(payload.get("constrain", True)),
    )
    controls = [str(row.get("ctrl")) for row in result or [] if row.get("ctrl")]
    return _result(True, "rig.create_control", "Created Maya control.", created_ids=controls, data={"controls": result})


def _op_rig_create_constraint(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload["type"]).lower()
    command = {
        "parent": cmds.parentConstraint, "point": cmds.pointConstraint, "orient": cmds.orientConstraint,
        "rotate": cmds.orientConstraint, "scale": cmds.scaleConstraint, "aim": cmds.aimConstraint,
        "pole_vector": cmds.poleVectorConstraint,
    }.get(kind)
    if command is None:
        raise ValueError(f"Unsupported Maya constraint: {kind}")
    axes = set(payload.get("axes") or ("x", "y", "z"))
    kwargs = {"maintainOffset": bool(payload.get("offset", True))}
    if kind in {"point", "orient", "scale", "parent"}:
        kwargs["skip"] = [axis for axis in ("x", "y", "z") if axis not in axes]
    nodes = command(*(list(payload["drivers"]) + [str(payload["driven"])]), **kwargs) or []
    return _result(True, "rig.create_constraint", f"Created Maya {kind} constraint.", created_ids=nodes)


def _op_rig_create_ik_fk_limb(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_rig.create_ik_fk_limb([payload["start"], payload["mid"], payload["end"]], payload.get("parent"))
    return _result(True, "rig.create_ik_fk_limb", "Created Maya IK/FK limb.", data={"maya_result": result})


def _op_rig_create_space_switch(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_rig.create_space_switch(
        driven=str(payload["driven"]), targets=list(payload["targets"]),
        attr_name=str(payload.get("name") or "space"), constraint_type=str(payload.get("mode") or "parent"),
        default_index=int(payload.get("active", 0) or 0),
    )
    return _result(True, "rig.create_space_switch", "Created Maya space switch.", data={"maya_result": result})


def _op_rig_create_ribbon(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_rig.setup_surface_rig_with_drivers(
        list(payload["joint_chain"]),
        loft_name=str(payload.get("name") or payload.get("module") or "surface"),
        offset=max(0.001, abs(float(payload.get("width", 0.5) or 0.5))),
        driver_follicle_indices=payload.get("driver_follicle_indices"),
        side=str(payload.get("side") or "c"),
        region=str(payload.get("region") or payload.get("module") or "other"),
        root_parent=str(payload.get("parent") or "") or None,
    )
    return _result(True, "rig.create_ribbon", "Created Maya ribbon/surface rig.", data={"maya_result": result})


def _op_skin_surface_spatial_smooth_brush(payload: dict[str, Any]) -> dict[str, Any]:
    from maya_tools.Rigging import skinning_utils

    result = skinning_utils.activate_surface_spatial_smooth_brush(
        radius=float(payload.get("radius", 1.0)),
        strength=float(payload.get("strength", 0.5)),
        iterations=int(payload.get("iterations", 1)),
        max_influences=int(payload.get("max_influences", 8)),
        normal_angle=float(payload.get("normal_angle", 120.0)),
        max_neighbors=int(payload.get("max_neighbors", 96)),
    )
    return _result(True, "skin.surface_spatial_smooth_brush",
                   "Activated Maya surface-spatial skin smoothing brush.", data=result)


def _op_rig_create_twist(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_rig.create_twist_driver(
        payload["start"], payload["end"],
        str(payload.get("parent") or ""), str(payload.get("surface") or ""),
    )
    return _result(True, "rig.create_twist", "Created Maya twist distribution.", data={"maya_result": result})


def _op_rig_create_motion_path(payload: dict[str, Any]) -> dict[str, Any]:
    node = cmds.pathAnimation(payload["target"], curve=payload["curve"], follow=bool(payload.get("follow", True)))
    return _result(True, "rig.create_motion_path", "Created Maya motion path.", created_ids=[node])


def _op_rig_create_curve_joints(payload: dict[str, Any]) -> dict[str, Any]:
    result = create_rig.create_joints_along_curve(
        payload["curve"],
        joint_count=int(payload.get("joint_count", 5) or 5),
        keep_attached=bool(payload.get("keep_attached", True)),
        name_prefix=payload.get("name_prefix"),
    )
    return _result(
        True,
        "rig.create_curve_joints",
        f"Created {len(result['joints'])} Maya joints along the curve.",
        created_ids=list(result["joints"]),
        data=result,
    )


def _op_rig_create_reverse_foot(payload: dict[str, Any]) -> dict[str, Any]:
    joints = create_rig.create_rfl_joints_template(str(payload.get("side") or "l"), payload["ankle"], payload["ball"], payload["toe"])
    return _result(True, "rig.create_reverse_foot", "Created Maya reverse-foot template.", created_ids=list(joints or []))


def _op_rig_store_connections(payload: dict[str, Any]) -> dict[str, Any]:
    controls = list(payload.get("controls") or cmds.ls("*_ctrl", type="transform") or [])
    data = create_rig.store_rig_connections(controls, str(payload["module"]))
    return _result(True, "rig.store_connections", "Stored Maya rig connections.", data={"connections": data})


def _op_rig_restore_connections(payload: dict[str, Any]) -> dict[str, Any]:
    data = create_rig.restore_rig_connections(str(payload["module"]))
    return _result(True, "rig.restore_connections", "Restored Maya rig connections.", data={"connections": data})


def _op_rig_create_face_module(payload: dict[str, Any]) -> dict[str, Any]:
    return _op_rig_build_module(payload)


def _op_retarget_solve_pose(payload: dict[str, Any]) -> dict[str, Any]:
    definition = _definition(payload["target"])
    pose = dict(payload["source"])
    changed = []
    for slot, joint in definition.slots.items():
        matrix = pose.get(slot)
        if cmds.objExists(joint) and isinstance(matrix, (list, tuple)) and len(matrix) == 16:
            cmds.xform(joint, worldSpace=True, matrix=list(matrix))
            changed.append(joint)
    return _result(True, "retarget.solve_pose", f"Solved {len(changed)} Maya joints.", changed_ids=changed)


_op_retarget_preview = _op_retarget_solve_pose


def _op_retarget_bake(payload: dict[str, Any]) -> dict[str, Any]:
    targets = list(_definition(payload["target"]).slots.values())
    start, end = payload["range"]
    cmds.bakeResults(targets, time=(float(start), float(end)), simulation=True,
                     sampleBy=float(payload.get("sample_rate", 1) or 1))
    return _result(True, "retarget.bake", "Baked retargeted Maya animation.", changed_ids=targets)


def _op_retarget_transfer_take(payload: dict[str, Any]) -> dict[str, Any]:
    return _result(True, "retarget.transfer_take", "Take metadata accepted for Maya bake/export.", data={"take": payload["take"]})


def _op_rig_set_ik_fk_blend(payload: dict[str, Any]) -> dict[str, Any]:
    plug = str(payload["limb"])
    if "." not in plug:
        plug += ".ikFk"
    cmds.setAttr(plug, float(payload["blend"]))
    return _result(True, "rig.set_ik_fk_blend", "Updated Maya IK/FK blend.", changed_ids=[plug])


def _op_rig_set_space(payload: dict[str, Any]) -> dict[str, Any]:
    plug = str(payload["space_switch"])
    if "." not in plug:
        plug += ".space"
    cmds.setAttr(plug, int(payload["space"]))
    return _result(True, "rig.set_space", "Updated Maya active space.", changed_ids=[plug])


def _op_rig_create_mesh_attachment(payload: dict[str, Any]) -> dict[str, Any]:
    nodes = cmds.geometryConstraint(payload["mesh"], payload["driven"]) or []
    return _result(True, "rig.create_mesh_attachment", "Created Maya geometry attachment.", created_ids=nodes)


def _op_rig_create_pose_reader(payload: dict[str, Any]) -> dict[str, Any]:
    node = cmds.createNode("angleBetween", name=str(payload.get("name") or "tc_poseReader"))
    return _result(True, "rig.create_pose_reader", "Created Maya pose reader node.", created_ids=[node])


def _op_rig_edit_control_shape(payload: dict[str, Any]) -> dict[str, Any]:
    control = str(payload["control"])
    positions = payload.get("cv_positions")
    if positions:
        for index, position in enumerate(positions):
            cmds.xform(f"{control}.cv[{index}]", objectSpace=True, translation=position)
    return _result(True, "rig.edit_control_shape", "Updated Maya control shape.", changed_ids=[control])
