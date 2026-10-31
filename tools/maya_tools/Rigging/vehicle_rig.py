"""Maya vehicle control rig with portable raycast ground detection."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Optional

import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui
import maya.cmds as cmds

from maya_tools.Rigging.undo_utils import undoable


RIG_SCHEMA = "tech_connector.vehicle_rig.maya.v1"
PORTABLE_SCHEMA = "tech_connector.vehicle_rig.v1"
DEFAULT_RIG_PATH = str(
    Path(__file__).resolve().parent / "templates" / "vehicle_rig.ma"
).replace("\\", "/")
DEFAULT_DEMO_PATH = str(
    Path(__file__).resolve().parent / "templates" / "vehicle_rig_demo.ma"
).replace("\\", "/")

_GROUND_SCRIPT_JOBS: dict[str, list[int]] = globals().get("_GROUND_SCRIPT_JOBS", {})
_GROUND_CALLBACK_IDS: dict[str, list[int]] = globals().get("_GROUND_CALLBACK_IDS", {})
_GROUND_CALLBACK_FUNCTIONS: dict[str, list[Any]] = globals().get(
    "_GROUND_CALLBACK_FUNCTIONS", {}
)
_SCENE_CALLBACK_IDS: list[int] = globals().get("_SCENE_CALLBACK_IDS", [])
_LAST_VIEWPORT_REFRESH = 0.0
_UPDATING_RIGS: set[str] = set()


def _short_name(node: str) -> str:
    return str(node or "").split("|")[-1].split(":")[-1]


def _nodes_with_attr_value(attribute: str, value: str, *, node_type: str = "") -> list[str]:
    nodes = cmds.ls(type=node_type, long=True) if node_type else cmds.ls(long=True)
    result = []
    for node in nodes or []:
        plug = "{}.{}".format(node, attribute)
        if not cmds.objExists(plug):
            continue
        try:
            if str(cmds.getAttr(plug) or "") == value:
                result.append(node)
        except (RuntimeError, ValueError):
            pass
    return result


def find_template_roots() -> list[str]:
    return _nodes_with_attr_value("tcVehicleSchema", PORTABLE_SCHEMA, node_type="joint")


def find_rig_roots() -> list[str]:
    return _nodes_with_attr_value("tcVehicleRigSchema", RIG_SCHEMA, node_type="transform")


def _resolve_template_root(root_joint: Optional[str] = None) -> str:
    if root_joint and cmds.objExists(root_joint + ".tcVehicleSchema"):
        return str(root_joint)
    selected = cmds.ls(selection=True, type="joint", long=True) or []
    for node in selected:
        lineage = [node] + (cmds.listRelatives(node, allParents=True, type="joint", fullPath=True) or [])
        for candidate in lineage:
            if cmds.objExists(candidate + ".tcVehicleSchema"):
                return candidate
    roots = find_template_roots()
    if len(roots) != 1:
        raise RuntimeError("Select one vehicle template root joint before building the rig.")
    return roots[0]


def _role_nodes(root_joint: str) -> dict[str, list[str]]:
    nodes = [root_joint] + (cmds.listRelatives(root_joint, allDescendents=True, type="joint", fullPath=True) or [])
    roles: dict[str, list[str]] = {}
    for node in nodes:
        plug = node + ".tcVehicleRole"
        if not cmds.objExists(plug):
            continue
        role = str(cmds.getAttr(plug) or "")
        if role:
            roles.setdefault(role, []).append(node)
    return roles


def _add_string(node: str, name: str, value: str) -> None:
    if not cmds.objExists(node + "." + name):
        cmds.addAttr(node, longName=name, dataType="string")
    cmds.setAttr(node + "." + name, str(value), type="string")


def _add_float(
    node: str, name: str, value: float, *, minimum: Optional[float] = None,
    maximum: Optional[float] = None, keyable: bool = True,
) -> None:
    if not cmds.objExists(node + "." + name):
        kwargs: dict[str, Any] = {"longName": name, "attributeType": "double", "keyable": keyable}
        if minimum is not None:
            kwargs["minValue"] = minimum
        if maximum is not None:
            kwargs["maxValue"] = maximum
        cmds.addAttr(node, **kwargs)
    cmds.setAttr(node + "." + name, float(value))


def _add_bool(node: str, name: str, value: bool, *, keyable: bool = True) -> None:
    if not cmds.objExists(node + "." + name):
        cmds.addAttr(node, longName=name, attributeType="bool", keyable=keyable)
    cmds.setAttr(node + "." + name, bool(value))


def _set_color(control: str, color: int) -> None:
    for shape in cmds.listRelatives(control, shapes=True, fullPath=True) or []:
        cmds.setAttr(shape + ".overrideEnabled", True)
        cmds.setAttr(shape + ".overrideColor", int(color))


def _curve(name: str, points, color: int) -> str:
    control = cmds.curve(name=name, degree=1, point=points)
    _set_color(control, color)
    return control


def _box_control(name: str, dimensions: tuple[float, float, float]) -> str:
    x, y, z = (component * 0.5 for component in dimensions)
    return _curve(name, [
        (-x, -y, -z), (-x, -y, z), (x, -y, z), (x, -y, -z), (-x, -y, -z),
        (-x, y, -z), (-x, y, z), (x, y, z), (x, y, -z), (-x, y, -z),
        (-x, y, z), (-x, -y, z), (x, -y, z), (x, y, z),
        (x, y, -z), (x, -y, -z),
    ], 17)


def _world_position(node: str) -> tuple[float, float, float]:
    value = cmds.xform(node, query=True, worldSpace=True, translation=True)
    return float(value[0]), float(value[1]), float(value[2])


def _scene_units_per_meter() -> float:
    unit = str(cmds.currentUnit(query=True, linear=True) or "cm")
    return {
        "mm": 1000.0, "cm": 100.0, "m": 1.0, "km": 0.001,
        "in": 39.3700787402, "ft": 3.280839895, "yd": 1.0936132983,
    }.get(unit, 100.0)


def _json_attr(node: str, name: str, default):
    plug = node + "." + name
    if not cmds.objExists(plug):
        return default
    try:
        return json.loads(cmds.getAttr(plug) or "")
    except (TypeError, ValueError, RuntimeError):
        return default


def _find_rig_root(node: Optional[str] = None) -> str:
    if node and cmds.objExists(node + ".tcVehicleRigSchema"):
        return str(node)
    selected = cmds.ls(selection=True, long=True) or []
    for item in selected:
        lineage = [item] + (cmds.listRelatives(item, allParents=True, fullPath=True) or [])
        for candidate in lineage:
            if cmds.objExists(candidate + ".tcVehicleRigSchema"):
                return candidate
    roots = find_rig_roots()
    if len(roots) != 1:
        raise RuntimeError("Select one vehicle rig root.")
    return roots[0]


def _unique_name(base: str) -> str:
    if not cmds.objExists(base):
        return base
    index = 1
    while cmds.objExists("{}{}".format(base, index)):
        index += 1
    return "{}{}".format(base, index)


@undoable("Build Vehicle Rig")
def build_vehicle_rig(
    root_joint: Optional[str] = None,
    *,
    ground_meshes: Optional[Iterable[str]] = None,
    create_preview_geometry: bool = True,
) -> dict[str, Any]:
    root_joint = _resolve_template_root(root_joint)
    roles = _role_nodes(root_joint)
    chassis_joints = roles.get("chassis", [])
    mounts = roles.get("wheel_mount", [])
    if len(chassis_joints) != 1 or not mounts:
        raise RuntimeError("Vehicle template requires one chassis joint and at least one wheel mount.")
    chassis_joint = chassis_joints[0]

    rig_root = cmds.createNode("transform", name=_unique_name("vehicle_RIG"))
    controls_group = cmds.createNode("transform", name="vehicle_controls_GRP", parent=rig_root)
    solver_group = cmds.createNode("transform", name="vehicle_solver_GRP", parent=rig_root)
    debug_group = cmds.createNode("transform", name="vehicle_ground_debug_GRP", parent=rig_root)
    geometry_group = cmds.createNode("transform", name="vehicle_preview_geo_GRP", parent=rig_root)
    _add_string(rig_root, "tcVehicleRigSchema", RIG_SCHEMA)
    _add_string(rig_root, "tcPortableRootJoint", root_joint)
    _add_string(rig_root, "tcGroundMeshes", "[]")
    _add_bool(rig_root, "groundDetection", True)
    _add_bool(rig_root, "alignWheelsToGround", True)
    _add_bool(rig_root, "liveGroundEvaluation", True)
    _add_bool(rig_root, "autoWheelSpin", True)
    _add_bool(rig_root, "debugGroundRays", True)
    _add_float(rig_root, "minimumGroundNormal", 0.15, minimum=0.0, maximum=1.0)
    _add_float(rig_root, "wheelRollMultiplier", 1.0)
    _add_float(rig_root, "groundOffset", 0.0)
    cmds.connectAttr(rig_root + ".debugGroundRays", debug_group + ".visibility", force=True)

    mount_positions = [_world_position(mount) for mount in mounts]
    width = max(point[0] for point in mount_positions) - min(point[0] for point in mount_positions)
    length = max(point[2] for point in mount_positions) - min(point[2] for point in mount_positions)
    width = max(width, 100.0)
    length = max(length, 180.0)

    global_ctrl = _curve(
        "vehicle_global_CTRL",
        [(-width * 0.75, 0, -length * 0.7), (-width * 0.75, 0, length * 0.7),
         (width * 0.75, 0, length * 0.7), (width * 0.75, 0, -length * 0.7),
         (-width * 0.75, 0, -length * 0.7)],
        14,
    )
    cmds.parent(global_ctrl, controls_group)
    _add_string(rig_root, "tcGlobalControl", global_ctrl)
    chassis_ctrl = _box_control("vehicle_chassis_CTRL", (width * 1.15, 60.0, length * 1.25))
    cmds.xform(chassis_ctrl, worldSpace=True, translation=_world_position(chassis_joint))
    cmds.parent(chassis_ctrl, global_ctrl)
    _add_string(rig_root, "tcChassisControl", chassis_ctrl)
    _add_float(chassis_ctrl, "steering", 0.0, minimum=-1.0, maximum=1.0)
    _add_float(chassis_ctrl, "throttle", 0.0, minimum=-1.0, maximum=1.0)
    _add_float(chassis_ctrl, "brake", 0.0, minimum=0.0, maximum=1.0)
    _add_float(chassis_ctrl, "maximumSteerAngle", float(cmds.getAttr(chassis_joint + ".tcMaximumSteerAngleDeg")))
    _add_float(chassis_ctrl, "ackermann", 1.0, minimum=0.0, maximum=1.0)
    _add_bool(chassis_ctrl, "autoSteering", True)
    _add_float(chassis_ctrl, "autoSteerBlend", 1.0, minimum=0.0, maximum=1.0)
    _add_float(chassis_ctrl, "autoSteerAngle", 0.0, keyable=False)
    _add_bool(chassis_ctrl, "steeringDrivesMotion", True)
    _add_bool(rig_root, "tcAutoSteerInitialized", False, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousX", 0.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousY", 0.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousZ", 0.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousForwardX", 0.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousForwardY", 0.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerPreviousForwardZ", 1.0, keyable=False)
    _add_float(rig_root, "tcAutoSteerLastTime", float(cmds.currentTime(query=True)), keyable=False)
    _add_bool(rig_root, "tcDriveInitialized", False, keyable=False)
    _add_float(rig_root, "tcDrivePreviousX", 0.0, keyable=False)
    _add_float(rig_root, "tcDrivePreviousY", 0.0, keyable=False)
    _add_float(rig_root, "tcDrivePreviousZ", 0.0, keyable=False)
    _add_float(rig_root, "tcDrivePreviousYaw", 0.0, keyable=False)
    _add_float(rig_root, "tcDriveLastTime", float(cmds.currentTime(query=True)), keyable=False)

    cmds.parentConstraint(global_ctrl, root_joint, maintainOffset=True, name="vehicle_root_parentConstraint")
    cmds.parentConstraint(chassis_ctrl, chassis_joint, maintainOffset=True, name="vehicle_chassis_parentConstraint")

    wheel_rows = []
    for mount in sorted(mounts, key=_short_name):
        wheel_id = str(cmds.getAttr(mount + ".tcWheelId"))
        wheel_candidates = [
            node for node in (cmds.listRelatives(mount, allDescendents=True, type="joint", fullPath=True) or [])
            if cmds.objExists(node + ".tcVehicleRole") and cmds.getAttr(node + ".tcVehicleRole") == "wheel"
        ]
        if len(wheel_candidates) != 1:
            raise RuntimeError("{} requires exactly one wheel joint.".format(mount))
        wheel_joint = wheel_candidates[0]
        center = _world_position(wheel_joint)

        suspension = cmds.createNode("transform", name="{}_suspension_DRV".format(wheel_id), parent=solver_group)
        steer = cmds.createNode("transform", name="{}_steer_DRV".format(wheel_id), parent=suspension)
        spin = cmds.createNode("transform", name="{}_spin_DRV".format(wheel_id), parent=steer)
        cmds.xform(suspension, worldSpace=True, translation=center)

        wheel_ctrl = cmds.circle(
            name="{}_wheel_CTRL".format(wheel_id), normal=(1.0, 0.0, 0.0),
            radius=float(cmds.getAttr(mount + ".tcRadiusM")) * _scene_units_per_meter() * 1.08,
            sections=16, constructionHistory=False,
        )[0]
        _set_color(wheel_ctrl, 6 if "left" in wheel_id else 13)
        cmds.parent(wheel_ctrl, spin)
        cmds.setAttr(wheel_ctrl + ".translate", 0.0, 0.0, 0.0, type="double3")
        _add_float(wheel_ctrl, "spin", 0.0)
        _add_float(wheel_ctrl, "autoSpin", 0.0, keyable=False)
        _add_float(wheel_ctrl, "steerOffset", 0.0, minimum=-90.0, maximum=90.0)
        _add_bool(wheel_ctrl, "grounded", False, keyable=False)
        _add_float(wheel_ctrl, "suspensionCompression", 0.0, keyable=False)
        _add_bool(wheel_ctrl, "tcRollInitialized", False, keyable=False)
        _add_float(wheel_ctrl, "tcPreviousWorldX", center[0], keyable=False)
        _add_float(wheel_ctrl, "tcPreviousWorldY", center[1], keyable=False)
        _add_float(wheel_ctrl, "tcPreviousWorldZ", center[2], keyable=False)
        _add_float(wheel_ctrl, "tcPreviousForwardX", 0.0, keyable=False)
        _add_float(wheel_ctrl, "tcPreviousForwardY", 0.0, keyable=False)
        _add_float(wheel_ctrl, "tcPreviousForwardZ", 1.0, keyable=False)
        _add_float(wheel_ctrl, "tcLastEvaluationTime", float(cmds.currentTime(query=True)), keyable=False)
        _add_string(wheel_ctrl, "tcWheelId", wheel_id)
        cmds.parentConstraint(wheel_ctrl, wheel_joint, maintainOffset=False, name="{}_wheel_parentConstraint".format(wheel_id))

        ray_length = (
            float(cmds.getAttr(mount + ".tcSuspensionRestLengthM"))
            + float(cmds.getAttr(mount + ".tcSuspensionTravelM"))
            + float(cmds.getAttr(mount + ".tcRadiusM"))
        ) * _scene_units_per_meter()
        ground_debug = _curve(
            "{}_groundRay_DBG".format(wheel_id),
            [center, (center[0], center[1] - ray_length, center[2])],
            13,
        )
        cmds.parent(ground_debug, debug_group)

        if create_preview_geometry:
            radius = float(cmds.getAttr(mount + ".tcRadiusM")) * _scene_units_per_meter()
            preview = cmds.polyCylinder(
                name="{}_preview_GEO".format(wheel_id), radius=radius, height=radius * 0.65,
                subdivisionsX=24, subdivisionsY=1, subdivisionsZ=1, axis=(1.0, 0.0, 0.0),
            )[0]
            cmds.parent(preview, geometry_group)
            cmds.parentConstraint(wheel_joint, preview, maintainOffset=False)

        wheel_rows.append({
            "id": wheel_id,
            "axle": str(cmds.getAttr(mount + ".tcAxle")),
            "side": "left" if "left" in wheel_id.lower() else "right" if "right" in wheel_id.lower() else "center",
            "mount": mount,
            "wheel_joint": wheel_joint,
            "suspension_driver": suspension,
            "steer_driver": steer,
            "spin_driver": spin,
            "control": wheel_ctrl,
            "ground_debug": ground_debug,
        })

    if create_preview_geometry:
        chassis_preview = cmds.polyCube(
            name="vehicle_chassis_preview_GEO", width=width * 1.1, height=50.0, depth=length * 1.25,
        )[0]
        cmds.parent(chassis_preview, geometry_group)
        cmds.parentConstraint(chassis_joint, chassis_preview, maintainOffset=False)

    _add_string(rig_root, "tcWheelRigMap", json.dumps(wheel_rows, sort_keys=True, separators=(",", ":")))
    if ground_meshes:
        attach_ground(ground_meshes, rig_root=rig_root)
    install_ground_callback(rig_root)
    cmds.select(global_ctrl, replace=True)
    update_ground(rig_root)
    return {
        "ok": True,
        "rig_root": rig_root,
        "template_root": root_joint,
        "global_control": global_ctrl,
        "chassis_control": chassis_ctrl,
        "wheels": wheel_rows,
    }


def _mesh_shape(node: str) -> str:
    if not cmds.objExists(node):
        return ""
    if cmds.nodeType(node) == "mesh":
        return node
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True, type="mesh") or []
    return shapes[0] if shapes else ""


@undoable("Assign Vehicle Ground")
def attach_ground(meshes: Iterable[str], *, rig_root: Optional[str] = None) -> dict[str, Any]:
    rig_root = _find_rig_root(rig_root)
    ground = []
    for node in meshes:
        shape = _mesh_shape(str(node))
        if shape and shape not in ground:
            ground.append(shape)
    if not ground:
        raise RuntimeError("Select at least one polygon ground mesh.")
    _add_string(rig_root, "tcGroundMeshes", json.dumps(ground))
    update_ground(rig_root)
    install_ground_callback(rig_root)
    return {"ok": True, "rig_root": rig_root, "ground_meshes": ground}


def attach_selected_ground(rig_root: Optional[str] = None) -> dict[str, Any]:
    selected = cmds.ls(selection=True, long=True) or []
    return attach_ground(selected, rig_root=rig_root)


def _mesh_intersection(mesh: str, origin: om.MFloatPoint, direction: om.MFloatVector, maximum: float):
    selection = om.MSelectionList()
    selection.add(mesh)
    path = selection.getDagPath(0)
    if path.apiType() == om.MFn.kTransform:
        path.extendToShape()
    fn = om.MFnMesh(path)
    hit = fn.closestIntersection(origin, direction, om.MSpace.kWorld, maximum, False)
    if not hit:
        return None
    point = hit[0]
    distance = float(hit[1])
    face = int(hit[2])
    normal = fn.getPolygonNormal(face, om.MSpace.kWorld)
    return point, normal, distance


def _normalize(value: om.MVector, fallback: om.MVector) -> om.MVector:
    return value.normal() if value.length() > 1.0e-8 else fallback


def _orientation_matrix(position, up: om.MVector, forward_hint: om.MVector) -> list[float]:
    up = _normalize(up, om.MVector(0.0, 1.0, 0.0))
    forward = forward_hint - up * (forward_hint * up)
    forward = _normalize(forward, om.MVector(0.0, 0.0, 1.0))
    right = _normalize(up ^ forward, om.MVector(1.0, 0.0, 0.0))
    forward = _normalize(right ^ up, forward)
    return [
        right.x, right.y, right.z, 0.0,
        up.x, up.y, up.z, 0.0,
        forward.x, forward.y, forward.z, 0.0,
        position[0], position[1], position[2], 1.0,
    ]


def _steering_angles(rows: list[dict[str, Any]], steering_degrees: float, maximum_degrees: float, blend: float) -> dict[str, float]:
    base_degrees = max(-maximum_degrees, min(maximum_degrees, steering_degrees))
    result = {str(row.get("id") or ""): base_degrees for row in rows if str(row.get("axle") or "") == "front"}
    if abs(base_degrees) < 1.0e-6 or blend <= 0.0 or len(result) < 2:
        return result
    front = [row for row in rows if str(row.get("axle") or "") == "front" and cmds.objExists(row.get("mount"))]
    rear = [row for row in rows if str(row.get("axle") or "") == "rear" and cmds.objExists(row.get("mount"))]
    if not front or not rear:
        return result
    front_points = [om.MVector(*_world_position(row["mount"])) for row in front]
    rear_points = [om.MVector(*_world_position(row["mount"])) for row in rear]
    front_center = sum(front_points[1:], front_points[0]) / float(len(front_points))
    rear_center = sum(rear_points[1:], rear_points[0]) / float(len(rear_points))
    wheelbase = (front_center - rear_center).length()
    track = max(((a - b).length() for index, a in enumerate(front_points) for b in front_points[index + 1:]), default=0.0)
    base_radians = math.radians(abs(base_degrees))
    if wheelbase <= 1.0e-8 or track <= 1.0e-8 or abs(math.tan(base_radians)) <= 1.0e-8:
        return result
    center_radius = wheelbase / math.tan(base_radians)
    inner = math.degrees(math.atan(wheelbase / max(1.0e-6, center_radius - track * 0.5)))
    outer = math.degrees(math.atan(wheelbase / (center_radius + track * 0.5)))
    turn_sign = 1.0 if base_degrees > 0.0 else -1.0
    inner_side = "right" if turn_sign > 0.0 else "left"
    for row in front:
        wheel_id = str(row.get("id") or "")
        target = inner if str(row.get("side") or "") == inner_side else outer
        target *= turn_sign
        result[wheel_id] = base_degrees + (target - base_degrees) * max(0.0, min(1.0, blend))
    return result


def _ensure_auto_steer_attributes(rig_root: str, chassis_control: str) -> None:
    """Upgrade previously saved vehicle rigs without resetting animator values."""
    if not cmds.objExists(chassis_control + ".autoSteering"):
        _add_bool(chassis_control, "autoSteering", True)
    if not cmds.objExists(chassis_control + ".autoSteerBlend"):
        _add_float(chassis_control, "autoSteerBlend", 1.0, minimum=0.0, maximum=1.0)
    if not cmds.objExists(chassis_control + ".autoSteerAngle"):
        _add_float(chassis_control, "autoSteerAngle", 0.0, keyable=False)
    if not cmds.objExists(chassis_control + ".steeringDrivesMotion"):
        _add_bool(chassis_control, "steeringDrivesMotion", True)
    if not cmds.objExists(rig_root + ".minimumGroundNormal"):
        _add_float(rig_root, "minimumGroundNormal", 0.15, minimum=0.0, maximum=1.0)
    state_defaults = {
        "tcAutoSteerPreviousX": 0.0,
        "tcAutoSteerPreviousY": 0.0,
        "tcAutoSteerPreviousZ": 0.0,
        "tcAutoSteerPreviousForwardX": 0.0,
        "tcAutoSteerPreviousForwardY": 0.0,
        "tcAutoSteerPreviousForwardZ": 1.0,
        "tcAutoSteerLastTime": float(cmds.currentTime(query=True)),
        "tcDrivePreviousX": 0.0,
        "tcDrivePreviousY": 0.0,
        "tcDrivePreviousZ": 0.0,
        "tcDrivePreviousYaw": 0.0,
        "tcDriveLastTime": float(cmds.currentTime(query=True)),
    }
    if not cmds.objExists(rig_root + ".tcAutoSteerInitialized"):
        _add_bool(rig_root, "tcAutoSteerInitialized", False, keyable=False)
    if not cmds.objExists(rig_root + ".tcDriveInitialized"):
        _add_bool(rig_root, "tcDriveInitialized", False, keyable=False)
    for name, value in state_defaults.items():
        if not cmds.objExists(rig_root + "." + name):
            _add_float(rig_root, name, value, keyable=False)


def _apply_bicycle_motion(
    rig_root: str,
    global_control: str,
    rows: list[dict[str, Any]],
    steering_degrees: float,
) -> dict[str, float | bool]:
    """Make forward/reverse translation follow the steered front axle.

    This is the kinematic bicycle model: curvature is tan(steer) / wheelbase.
    The signed travel distance makes reversing rotate the chassis in the
    opposite direction without any special-case sign switch.
    """
    matrix = cmds.xform(global_control, query=True, worldSpace=True, matrix=True)
    position = om.MVector(matrix[12], matrix[13], matrix[14])
    rotation = cmds.xform(global_control, query=True, worldSpace=True, rotation=True)
    yaw = float(rotation[1])
    current_time = float(cmds.currentTime(query=True))
    previous_time = float(cmds.getAttr(rig_root + ".tcDriveLastTime"))
    initialized = bool(cmds.getAttr(rig_root + ".tcDriveInitialized"))
    result: dict[str, float | bool] = {
        "applied": False, "distance": 0.0, "yaw_delta": 0.0,
    }

    if initialized and current_time + 1.0e-8 >= previous_time:
        previous = om.MVector(
            float(cmds.getAttr(rig_root + ".tcDrivePreviousX")),
            float(cmds.getAttr(rig_root + ".tcDrivePreviousY")),
            float(cmds.getAttr(rig_root + ".tcDrivePreviousZ")),
        )
        previous_yaw = float(cmds.getAttr(rig_root + ".tcDrivePreviousYaw"))
        heading = math.radians(previous_yaw)
        previous_forward = om.MVector(math.sin(heading), 0.0, math.cos(heading))
        displacement = position - previous
        signed_distance = displacement * previous_forward
        wheelbase = _wheelbase(rows)

        # A rotate-only edit is an intentional heading placement. A translate
        # edit is constrained to the no-slip bicycle arc.
        if displacement.length() <= 1.0e-6:
            previous_yaw = yaw
        elif wheelbase > 1.0e-5:
            curvature = math.tan(math.radians(steering_degrees)) / wheelbase
            yaw_delta = signed_distance * curvature
            new_yaw_radians = heading + yaw_delta
            if abs(curvature) > 1.0e-10:
                new_x = previous.x + (math.cos(heading) - math.cos(new_yaw_radians)) / curvature
                new_z = previous.z + (math.sin(new_yaw_radians) - math.sin(heading)) / curvature
            else:
                new_x = previous.x + math.sin(heading) * signed_distance
                new_z = previous.z + math.cos(heading) * signed_distance
            new_yaw = math.degrees(new_yaw_radians)
            try:
                cmds.xform(
                    global_control, worldSpace=True,
                    translation=(new_x, position.y, new_z),
                    rotation=(float(rotation[0]), new_yaw, float(rotation[2])),
                )
                position = om.MVector(new_x, position.y, new_z)
                yaw = new_yaw
                result.update({
                    "applied": True,
                    "distance": float(signed_distance),
                    "yaw_delta": math.degrees(yaw_delta),
                })
            except RuntimeError:
                # Connected output channels are treated as an explicitly
                # authored path; automatic steering can still follow it.
                pass

    cmds.setAttr(rig_root + ".tcDrivePreviousX", position.x)
    cmds.setAttr(rig_root + ".tcDrivePreviousY", position.y)
    cmds.setAttr(rig_root + ".tcDrivePreviousZ", position.z)
    cmds.setAttr(rig_root + ".tcDrivePreviousYaw", yaw)
    cmds.setAttr(rig_root + ".tcDriveLastTime", current_time)
    cmds.setAttr(rig_root + ".tcDriveInitialized", True)
    return result


def _wheelbase(rows: list[dict[str, Any]]) -> float:
    front = [
        om.MVector(*_world_position(row["mount"])) for row in rows
        if str(row.get("axle") or "") == "front" and cmds.objExists(row.get("mount"))
    ]
    rear = [
        om.MVector(*_world_position(row["mount"])) for row in rows
        if str(row.get("axle") or "") == "rear" and cmds.objExists(row.get("mount"))
    ]
    if not front or not rear:
        return 0.0
    front_center = sum(front[1:], front[0]) / float(len(front))
    rear_center = sum(rear[1:], rear[0]) / float(len(rear))
    return (front_center - rear_center).length()


def _automatic_steer_angle(
    rig_root: str,
    chassis_control: str,
    rows: list[dict[str, Any]],
    maximum_degrees: float,
) -> float:
    """Derive front-wheel steering from chassis yaw or animated path curvature."""
    _ensure_auto_steer_attributes(rig_root, chassis_control)
    matrix = cmds.xform(chassis_control, query=True, worldSpace=True, matrix=True)
    position = om.MVector(matrix[12], matrix[13], matrix[14])
    forward = _normalize(
        om.MVector(matrix[8], matrix[9], matrix[10]), om.MVector(0.0, 0.0, 1.0)
    )
    up = _normalize(
        om.MVector(matrix[4], matrix[5], matrix[6]), om.MVector(0.0, 1.0, 0.0)
    )
    current_time = float(cmds.currentTime(query=True))
    previous_time = float(cmds.getAttr(rig_root + ".tcAutoSteerLastTime"))
    initialized = bool(cmds.getAttr(rig_root + ".tcAutoSteerInitialized"))
    angle = float(cmds.getAttr(chassis_control + ".autoSteerAngle"))

    if initialized and current_time + 1.0e-8 >= previous_time:
        previous_position = om.MVector(
            float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousX")),
            float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousY")),
            float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousZ")),
        )
        previous_forward = _normalize(
            om.MVector(
                float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousForwardX")),
                float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousForwardY")),
                float(cmds.getAttr(rig_root + ".tcAutoSteerPreviousForwardZ")),
            ),
            forward,
        )
        average_forward = _normalize(previous_forward + forward, forward)
        signed_distance = (position - previous_position) * average_forward
        yaw_radians = math.atan2((previous_forward ^ forward) * up, previous_forward * forward)
        wheelbase = _wheelbase(rows)
        if abs(signed_distance) > 1.0e-5 and wheelbase > 1.0e-5:
            angle = math.degrees(math.atan(wheelbase * yaw_radians / signed_distance))
    elif initialized and current_time < previous_time:
        angle = 0.0

    # Rotating the chassis control itself is an animator-facing steering pose.
    # It takes precedence over curvature so viewport rotation responds on the
    # very first mouse event, even before the vehicle has translated.
    local_yaw = float(cmds.getAttr(chassis_control + ".rotateY"))
    if abs(local_yaw) > 1.0e-5:
        angle = local_yaw
    angle = max(-maximum_degrees, min(maximum_degrees, angle))

    cmds.setAttr(chassis_control + ".autoSteerAngle", angle)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousX", position.x)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousY", position.y)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousZ", position.z)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousForwardX", forward.x)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousForwardY", forward.y)
    cmds.setAttr(rig_root + ".tcAutoSteerPreviousForwardZ", forward.z)
    cmds.setAttr(rig_root + ".tcAutoSteerLastTime", current_time)
    cmds.setAttr(rig_root + ".tcAutoSteerInitialized", True)
    return angle


def _wheel_roll(
    rig_root: str,
    control: str,
    spin_driver: str,
    steer_driver: str,
    center: om.MVector,
    radius: float,
) -> float:
    current_time = float(cmds.currentTime(query=True))
    initialized = bool(cmds.getAttr(control + ".tcRollInitialized"))
    previous_time = float(cmds.getAttr(control + ".tcLastEvaluationTime"))
    previous = om.MVector(
        float(cmds.getAttr(control + ".tcPreviousWorldX")),
        float(cmds.getAttr(control + ".tcPreviousWorldY")),
        float(cmds.getAttr(control + ".tcPreviousWorldZ")),
    )
    auto_spin = float(cmds.getAttr(control + ".autoSpin"))
    if initialized and current_time + 1.0e-8 >= previous_time and radius > 1.0e-8:
        steer_matrix = cmds.xform(steer_driver, query=True, worldSpace=True, matrix=True)
        wheel_forward = _normalize(
            om.MVector(steer_matrix[8], steer_matrix[9], steer_matrix[10]),
            om.MVector(0.0, 0.0, 1.0),
        )
        previous_forward = _normalize(
            om.MVector(
                float(cmds.getAttr(control + ".tcPreviousForwardX")),
                float(cmds.getAttr(control + ".tcPreviousForwardY")),
                float(cmds.getAttr(control + ".tcPreviousForwardZ")),
            ),
            wheel_forward,
        )
        integration_forward = _normalize(previous_forward + wheel_forward, wheel_forward)
        signed_distance = (center - previous) * integration_forward
        multiplier = float(cmds.getAttr(rig_root + ".wheelRollMultiplier"))
        # With Maya's +X wheel axle and +Z vehicle-forward convention, positive
        # forward travel is a positive rotateX turn (the top of the wheel moves
        # toward +Z). Reverse travel naturally produces the opposite sign.
        auto_spin += (signed_distance / radius) * (180.0 / math.pi) * multiplier
    elif initialized and current_time < previous_time:
        # Stateful live evaluation cannot reconstruct a reverse scrub. Reset
        # here; bake_ground samples forward from the range start deterministically.
        auto_spin = 0.0
    cmds.setAttr(control + ".autoSpin", auto_spin)
    cmds.setAttr(control + ".tcPreviousWorldX", center.x)
    cmds.setAttr(control + ".tcPreviousWorldY", center.y)
    cmds.setAttr(control + ".tcPreviousWorldZ", center.z)
    steer_matrix = cmds.xform(steer_driver, query=True, worldSpace=True, matrix=True)
    current_forward = _normalize(
        om.MVector(steer_matrix[8], steer_matrix[9], steer_matrix[10]),
        om.MVector(0.0, 0.0, 1.0),
    )
    cmds.setAttr(control + ".tcPreviousForwardX", current_forward.x)
    cmds.setAttr(control + ".tcPreviousForwardY", current_forward.y)
    cmds.setAttr(control + ".tcPreviousForwardZ", current_forward.z)
    cmds.setAttr(control + ".tcLastEvaluationTime", current_time)
    cmds.setAttr(control + ".tcRollInitialized", True)
    manual_spin = float(cmds.getAttr(control + ".spin"))
    cmds.setAttr(spin_driver + ".rotateX", manual_spin + auto_spin)
    return auto_spin


def reset_wheel_roll(rig_root: Optional[str] = None, *, preserve_rotation: bool = False) -> dict[str, Any]:
    rig_root = _find_rig_root(rig_root)
    rows = _json_attr(rig_root, "tcWheelRigMap", [])
    current_time = float(cmds.currentTime(query=True))
    reset = 0
    for row in rows:
        control = row.get("control")
        suspension = row.get("suspension_driver")
        spin_driver = row.get("spin_driver")
        steer_driver = row.get("steer_driver")
        if not all(cmds.objExists(node) for node in (control, suspension, spin_driver, steer_driver)):
            continue
        position = _world_position(suspension)
        steer_matrix = cmds.xform(steer_driver, query=True, worldSpace=True, matrix=True)
        forward = _normalize(
            om.MVector(steer_matrix[8], steer_matrix[9], steer_matrix[10]),
            om.MVector(0.0, 0.0, 1.0),
        )
        if not preserve_rotation:
            cmds.setAttr(control + ".autoSpin", 0.0)
        cmds.setAttr(control + ".tcPreviousWorldX", position[0])
        cmds.setAttr(control + ".tcPreviousWorldY", position[1])
        cmds.setAttr(control + ".tcPreviousWorldZ", position[2])
        cmds.setAttr(control + ".tcPreviousForwardX", forward.x)
        cmds.setAttr(control + ".tcPreviousForwardY", forward.y)
        cmds.setAttr(control + ".tcPreviousForwardZ", forward.z)
        cmds.setAttr(control + ".tcLastEvaluationTime", current_time)
        cmds.setAttr(control + ".tcRollInitialized", True)
        cmds.setAttr(
            spin_driver + ".rotateX",
            float(cmds.getAttr(control + ".spin")) + float(cmds.getAttr(control + ".autoSpin")),
        )
        reset += 1
    return {"ok": True, "rig_root": rig_root, "reset": reset}


def update_ground(rig_root: Optional[str] = None) -> dict[str, Any]:
    rig_root = _find_rig_root(rig_root)
    if rig_root in _UPDATING_RIGS:
        return {"ok": True, "rig_root": rig_root, "updated": 0, "grounded": 0, "reentrant": True}
    _UPDATING_RIGS.add(rig_root)
    try:
        ground_detection = bool(cmds.getAttr(rig_root + ".groundDetection"))
        meshes = (
            [mesh for mesh in _json_attr(rig_root, "tcGroundMeshes", []) if _mesh_shape(mesh)]
            if ground_detection else []
        )
        rows = _json_attr(rig_root, "tcWheelRigMap", [])
        global_control = str(cmds.getAttr(rig_root + ".tcGlobalControl") or "")
        chassis_control = str(cmds.getAttr(rig_root + ".tcChassisControl") or "")
        steering = float(cmds.getAttr(chassis_control + ".steering")) if cmds.objExists(chassis_control + ".steering") else 0.0
        max_steer = float(cmds.getAttr(chassis_control + ".maximumSteerAngle")) if cmds.objExists(chassis_control + ".maximumSteerAngle") else 32.0
        ackermann = float(cmds.getAttr(chassis_control + ".ackermann")) if cmds.objExists(chassis_control + ".ackermann") else 0.0
        _ensure_auto_steer_attributes(rig_root, chassis_control)
        manual_steer_degrees = steering * max_steer
        drive_enabled = bool(cmds.getAttr(chassis_control + ".steeringDrivesMotion"))
        drive_state = {"applied": False, "distance": 0.0, "yaw_delta": 0.0}
        if drive_enabled and global_control and cmds.objExists(global_control):
            drive_state = _apply_bicycle_motion(
                rig_root, global_control, rows, manual_steer_degrees
            )
        calculated_auto_steer = _automatic_steer_angle(
            rig_root, chassis_control, rows, max_steer
        )
        automatic_steer = (
            calculated_auto_steer
            if bool(cmds.getAttr(chassis_control + ".autoSteering"))
            and not (drive_enabled and abs(manual_steer_degrees) > 1.0e-5)
            else 0.0
        )
        auto_blend = float(cmds.getAttr(chassis_control + ".autoSteerBlend"))
        effective_steer = max(
            -max_steer,
            min(max_steer, manual_steer_degrees + automatic_steer * auto_blend),
        )
        steering_angles = _steering_angles(rows, effective_steer, max_steer, ackermann)
        units = _scene_units_per_meter()
        grounded_count = 0
        updated = 0
        wheel_states = []
        for row in rows:
            mount = row.get("mount")
            suspension = row.get("suspension_driver")
            steer = row.get("steer_driver")
            spin = row.get("spin_driver")
            control = row.get("control")
            if not all(cmds.objExists(node) for node in (mount, suspension, steer, spin, control)):
                continue
            origin_tuple = _world_position(mount)
            mount_position = om.MVector(*origin_tuple)
            chassis_matrix = cmds.xform(chassis_control, query=True, worldSpace=True, matrix=True)
            up = _normalize(om.MVector(chassis_matrix[4], chassis_matrix[5], chassis_matrix[6]), om.MVector(0, 1, 0))
            down = up * -1.0
            forward = _normalize(om.MVector(chassis_matrix[8], chassis_matrix[9], chassis_matrix[10]), om.MVector(0, 0, 1))
            radius = float(cmds.getAttr(mount + ".tcRadiusM")) * units
            rest = float(cmds.getAttr(mount + ".tcSuspensionRestLengthM")) * units
            travel = float(cmds.getAttr(mount + ".tcSuspensionTravelM")) * units
            minimum_suspension_length = max(0.0, rest - travel)
            maximum_suspension_length = rest + travel
            compressed_center = mount_position + down * minimum_suspension_length
            minimum_ground_normal = max(
                0.01, float(cmds.getAttr(rig_root + ".minimumGroundNormal"))
            )
            query_length = (
                maximum_suspension_length - minimum_suspension_length
                + radius / minimum_ground_normal
            )
            ray_origin = om.MFloatPoint(
                compressed_center.x, compressed_center.y, compressed_center.z
            )
            nearest = None
            for mesh in meshes:
                try:
                    hit = _mesh_intersection(
                        mesh, ray_origin, om.MFloatVector(down), query_length
                    )
                except (RuntimeError, ValueError):
                    hit = None
                if hit:
                    hit_point, hit_normal, hit_distance = hit
                    hit_normal = _normalize(hit_normal, up)
                    if hit_normal * up < 0.0:
                        hit_normal *= -1.0
                    normal_alignment = hit_normal * up
                    if normal_alignment < minimum_ground_normal:
                        continue
                    candidate = (
                        hit_point, hit_normal, hit_distance, normal_alignment
                    )
                    if nearest is None or hit_distance < nearest[2]:
                        nearest = candidate
            if nearest:
                contact_point, normal, distance, normal_alignment = nearest
                # The tire touches the hit plane along its normal. Dividing by
                # n dot suspension-up keeps the wheel tangent on slopes instead
                # of sinking by using a purely vertical radius subtraction.
                suspension_length = min(
                    maximum_suspension_length,
                    max(
                        minimum_suspension_length,
                        minimum_suspension_length
                        + distance - radius / normal_alignment,
                    ),
                )
                grounded = True
                grounded_count += 1
            else:
                normal = up
                # At full droop the wheel is still solved from the moving mount.
                # It follows the chassis at this exact separation instead of
                # being left behind at its last ground-contact position.
                suspension_length = maximum_suspension_length
                grounded = False
                ray_end = compressed_center + down * query_length
                contact_point = om.MFloatPoint(ray_end.x, ray_end.y, ray_end.z)
            ground_offset = float(cmds.getAttr(rig_root + ".groundOffset"))
            center = mount_position + down * suspension_length + up * ground_offset
            align = bool(cmds.getAttr(rig_root + ".alignWheelsToGround"))
            matrix = _orientation_matrix(center, normal if align else up, forward)
            cmds.xform(suspension, worldSpace=True, matrix=matrix)
            steerable = bool(cmds.getAttr(mount + ".tcSteerable"))
            steer_offset = float(cmds.getAttr(control + ".steerOffset"))
            steer_angle = steering_angles.get(str(row.get("id") or ""), effective_steer)
            cmds.setAttr(steer + ".rotateY", steer_angle + steer_offset if steerable else steer_offset)
            if bool(cmds.getAttr(rig_root + ".autoWheelSpin")):
                auto_spin = _wheel_roll(rig_root, control, spin, steer, center, radius)
            else:
                auto_spin = float(cmds.getAttr(control + ".autoSpin"))
                cmds.setAttr(spin + ".rotateX", float(cmds.getAttr(control + ".spin")))
            cmds.setAttr(control + ".grounded", grounded)
            compression = (rest - suspension_length) / units
            cmds.setAttr(control + ".suspensionCompression", compression)
            ground_debug = row.get("ground_debug")
            if ground_debug and cmds.objExists(ground_debug):
                cmds.xform(
                    ground_debug + ".cv[0]", worldSpace=True,
                    translation=(compressed_center.x, compressed_center.y, compressed_center.z),
                )
                cmds.xform(
                    ground_debug + ".cv[1]", worldSpace=True,
                    translation=(contact_point.x, contact_point.y, contact_point.z),
                )
                _set_color(ground_debug, 14 if grounded else 13)
            wheel_states.append({
                "id": row.get("id", ""), "grounded": grounded,
                "suspension_length_m": suspension_length / units,
                "compression_m": compression, "auto_spin_degrees": auto_spin,
            })
            updated += 1
        return {
            "ok": True, "rig_root": rig_root, "updated": updated,
            "grounded": grounded_count, "wheels": wheel_states,
            "automatic_steer_degrees": automatic_steer,
            "effective_steer_degrees": effective_steer,
            "drive": drive_state,
        }
    finally:
        _UPDATING_RIGS.discard(rig_root)


def _callback_attributes(rig_root: str) -> list[str]:
    nodes = []
    attributes = []
    for name in ("tcGlobalControl", "tcChassisControl"):
        plug = rig_root + "." + name
        if cmds.objExists(plug):
            node = str(cmds.getAttr(plug) or "")
            if cmds.objExists(node):
                nodes.append(node)
    for mesh in _json_attr(rig_root, "tcGroundMeshes", []):
        shape = _mesh_shape(mesh)
        parent = (cmds.listRelatives(shape, parent=True, fullPath=True) or [""])[0] if shape else ""
        if parent:
            nodes.append(parent)
        if shape:
            for shape_attribute in ("outMesh", "worldMesh[0]"):
                plug = shape + "." + shape_attribute
                if cmds.objExists(plug):
                    attributes.append(plug)
    for node in nodes:
        for channel in ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ"):
            plug = node + "." + channel
            if cmds.objExists(plug):
                attributes.append(plug)
    chassis_control = str(cmds.getAttr(rig_root + ".tcChassisControl") or "")
    for attribute in (
        "steering", "maximumSteerAngle", "ackermann",
        "autoSteering", "autoSteerBlend", "steeringDrivesMotion",
    ):
        plug = chassis_control + "." + attribute
        if cmds.objExists(plug):
            attributes.append(plug)
    for row in _json_attr(rig_root, "tcWheelRigMap", []):
        control = str(row.get("control") or "")
        for attribute in ("spin", "steerOffset"):
            plug = control + "." + attribute
            if cmds.objExists(plug):
                attributes.append(plug)
    for attribute in (
        "groundDetection", "alignWheelsToGround", "autoWheelSpin",
        "groundOffset", "wheelRollMultiplier", "minimumGroundNormal",
    ):
        plug = rig_root + "." + attribute
        if cmds.objExists(plug):
            attributes.append(plug)
    return attributes


def remove_ground_callback(rig_root: Optional[str] = None) -> None:
    """Remove every live evaluator registered for one vehicle rig."""
    rig_root = _find_rig_root(rig_root)
    for callback_id in _GROUND_CALLBACK_IDS.pop(rig_root, []):
        try:
            om.MMessage.removeCallback(callback_id)
        except RuntimeError:
            pass
    _GROUND_CALLBACK_FUNCTIONS.pop(rig_root, None)
    for job_id in _GROUND_SCRIPT_JOBS.pop(rig_root, []):
        if job_id and cmds.scriptJob(exists=job_id):
            cmds.scriptJob(kill=job_id, force=True)


def remove_all_ground_callbacks() -> None:
    """Remove live callbacks, including entries whose scene nodes were deleted."""
    for callback_ids in list(_GROUND_CALLBACK_IDS.values()):
        for callback_id in callback_ids:
            try:
                om.MMessage.removeCallback(callback_id)
            except RuntimeError:
                pass
    _GROUND_CALLBACK_IDS.clear()
    _GROUND_CALLBACK_FUNCTIONS.clear()
    for job_ids in list(_GROUND_SCRIPT_JOBS.values()):
        for job_id in job_ids:
            if job_id and cmds.scriptJob(exists=job_id):
                cmds.scriptJob(kill=job_id, force=True)
    _GROUND_SCRIPT_JOBS.clear()


def _refresh_active_viewport() -> None:
    """Refresh at display cadence without stalling manipulator mouse events."""
    global _LAST_VIEWPORT_REFRESH
    now = time.perf_counter()
    if now - _LAST_VIEWPORT_REFRESH < (1.0 / 60.0):
        return
    _LAST_VIEWPORT_REFRESH = now
    try:
        omui.M3dView.active3dView().refresh(False, True)
    except RuntimeError:
        pass


def _live_refresh(rig_root: str, *, refresh_viewport: bool = True) -> bool:
    if not cmds.objExists(rig_root + ".liveGroundEvaluation"):
        return False
    if not bool(cmds.getAttr(rig_root + ".liveGroundEvaluation")):
        return False
    update_ground(rig_root)
    if refresh_viewport:
        _refresh_active_viewport()
    return True


def update_registered_live_rigs(*, refresh_viewport: bool = True) -> int:
    """Evaluate registered rigs now; intended for a Qt viewport heartbeat."""
    updated = 0
    for rig_root in list(_GROUND_CALLBACK_IDS):
        if not cmds.objExists(rig_root):
            _GROUND_CALLBACK_IDS.pop(rig_root, None)
            _GROUND_CALLBACK_FUNCTIONS.pop(rig_root, None)
            continue
        if _live_refresh(rig_root, refresh_viewport=False):
            updated += 1
    if updated and refresh_viewport:
        _refresh_active_viewport()
    return updated


def install_ground_callback(rig_root: Optional[str] = None) -> list[int]:
    """Install native DG/time callbacks for immediate drag and playback updates.

    ``scriptJob(attributeChange=...)`` can be coalesced until a Maya manipulator
    releases the mouse. MNodeMessage is delivered for every channel edit, while
    MEventMessage's timeChanged event runs before each playback redraw.
    """
    rig_root = _find_rig_root(rig_root)
    chassis_control = str(cmds.getAttr(rig_root + ".tcChassisControl") or "")
    if chassis_control and cmds.objExists(chassis_control):
        _ensure_auto_steer_attributes(rig_root, chassis_control)
    remove_ground_callback(rig_root)

    watched_by_node: dict[str, set[str]] = {}
    for plug_name in _callback_attributes(rig_root):
        node, attribute = plug_name.rsplit(".", 1)
        watched_by_node.setdefault(node, set()).add(attribute)

    callbacks: list[int] = []
    functions: list[Any] = []

    def time_changed(*_unused) -> None:
        _live_refresh(rig_root)

    functions.append(time_changed)
    callbacks.append(om.MEventMessage.addEventCallback("timeChanged", time_changed))

    relevant_messages = om.MNodeMessage.kAttributeSet | om.MNodeMessage.kAttributeEval
    for node, attributes in watched_by_node.items():
        selection = om.MSelectionList()
        selection.add(node)
        node_object = selection.getDependNode(0)

        def attribute_changed(message, plug, _other_plug, _data, watched=attributes):
            if not message & relevant_messages:
                return
            attribute = plug.partialName(useLongNames=True).split(".")[-1]
            if attribute in watched:
                _live_refresh(rig_root)

        functions.append(attribute_changed)
        callbacks.append(om.MNodeMessage.addAttributeChangedCallback(node_object, attribute_changed))

    _GROUND_CALLBACK_IDS[rig_root] = callbacks
    _GROUND_CALLBACK_FUNCTIONS[rig_root] = functions
    _live_refresh(rig_root)
    return callbacks


def install_ground_callbacks() -> list[int]:
    remove_all_ground_callbacks()
    callbacks = []
    for root in find_rig_roots():
        callbacks.extend(install_ground_callback(root))
    return callbacks


def install_scene_callbacks() -> list[int]:
    """Restore live vehicle evaluation whenever a scene is opened or imported."""
    global _SCENE_CALLBACK_IDS
    for callback_id in _SCENE_CALLBACK_IDS:
        try:
            om.MMessage.removeCallback(callback_id)
        except RuntimeError:
            pass

    def restore_vehicle_callbacks(*_unused) -> None:
        install_ground_callbacks()

    _SCENE_CALLBACK_IDS = [
        om.MSceneMessage.addCallback(om.MSceneMessage.kAfterOpen, restore_vehicle_callbacks),
        om.MSceneMessage.addCallback(om.MSceneMessage.kAfterImport, restore_vehicle_callbacks),
        om.MSceneMessage.addCallback(om.MSceneMessage.kAfterCreateReference, restore_vehicle_callbacks),
    ]
    return list(_SCENE_CALLBACK_IDS)


@undoable("Bake Vehicle Ground")
def bake_ground(
    rig_root: Optional[str] = None,
    *,
    start: Optional[float] = None,
    end: Optional[float] = None,
    step: float = 1.0,
) -> dict[str, Any]:
    rig_root = _find_rig_root(rig_root)
    start = float(cmds.playbackOptions(query=True, minTime=True) if start is None else start)
    end = float(cmds.playbackOptions(query=True, maxTime=True) if end is None else end)
    step = max(0.001, float(step))
    rows = _json_attr(rig_root, "tcWheelRigMap", [])
    drivers = [row[key] for row in rows for key in ("suspension_driver", "steer_driver", "spin_driver")]
    current = float(cmds.currentTime(query=True))
    live = bool(cmds.getAttr(rig_root + ".liveGroundEvaluation"))
    frame = start
    samples = 0
    try:
        cmds.setAttr(rig_root + ".liveGroundEvaluation", False)
        cmds.currentTime(start, edit=True)
        update_ground(rig_root)
        reset_wheel_roll(rig_root)
        while frame <= end + 1.0e-8:
            cmds.currentTime(frame, edit=True)
            update_ground(rig_root)
            cmds.setKeyframe(drivers, attribute=("translate", "rotate"), time=frame)
            samples += 1
            frame += step
    finally:
        cmds.setAttr(rig_root + ".liveGroundEvaluation", live)
        cmds.currentTime(current, edit=True)
    return {"ok": True, "rig_root": rig_root, "samples": samples, "range": [start, end]}


def save_vehicle_rig(path: str = DEFAULT_RIG_PATH) -> str:
    output = Path(path).expanduser()
    if output.suffix.lower() not in {".ma", ".mb"}:
        output = output.with_suffix(".ma")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmds.file(rename=str(output))
    cmds.file(save=True, type="mayaBinary" if output.suffix.lower() == ".mb" else "mayaAscii", force=True)
    return str(output).replace("\\", "/")


def build_example_scene(path: str = DEFAULT_RIG_PATH) -> dict[str, Any]:
    from maya_tools.Rigging import rig_template

    cmds.file(new=True, force=True)
    loaded = rig_template.load_default_vehicle_rig_template()
    root_joint = loaded["root_joints"][0]
    result = build_vehicle_rig(root_joint, create_preview_geometry=True)
    ground = cmds.polyPlane(
        name="vehicle_ground_GEO", width=1000.0, height=1000.0,
        subdivisionsX=20, subdivisionsY=20,
    )[0]
    attach_ground([ground], rig_root=result["rig_root"])
    result["ground_mesh"] = ground
    result["path"] = save_vehicle_rig(path)
    return result


def build_demo_scene(path: str = DEFAULT_DEMO_PATH) -> dict[str, Any]:
    """Build and bake a short uneven-ground validation scene."""
    from maya_tools.Rigging import rig_template

    cmds.file(new=True, force=True)
    loaded = rig_template.load_default_vehicle_rig_template()
    result = build_vehicle_rig(loaded["root_joints"][0], create_preview_geometry=True)
    ground = cmds.polyPlane(
        name="vehicle_demo_ground_GEO", width=1000.0, height=1000.0,
        subdivisionsX=24, subdivisionsY=48,
    )[0]
    for vertex in cmds.ls(ground + ".vtx[*]", flatten=True) or []:
        x, _y, z = cmds.xform(vertex, query=True, worldSpace=True, translation=True)
        height = 8.0 * math.sin(z / 75.0) + 0.018 * x * math.sin(z / 115.0)
        cmds.xform(vertex, worldSpace=True, translation=(x, height, z))
    attach_ground([ground], rig_root=result["rig_root"])

    global_control = result["global_control"]
    chassis_control = result["chassis_control"]
    cmds.playbackOptions(minTime=1, maxTime=80)
    for frame, x_position, z_position, heading in (
        (1, 0.0, -300.0, 0.0),
        (40, 60.0, 0.0, 12.0),
        (80, 0.0, 300.0, 0.0),
    ):
        cmds.setKeyframe(global_control, attribute="translateX", time=frame, value=x_position)
        cmds.setKeyframe(global_control, attribute="translateZ", time=frame, value=z_position)
        cmds.setKeyframe(global_control, attribute="rotateY", time=frame, value=heading)
        cmds.setKeyframe(chassis_control, attribute="steering", time=frame, value=0.0)
    bake = bake_ground(result["rig_root"], start=1, end=80, step=1.0)
    cmds.setAttr(result["rig_root"] + ".liveGroundEvaluation", False)
    cmds.currentTime(1, edit=True)
    result.update({"ground_mesh": ground, "bake": bake, "path": save_vehicle_rig(path)})
    return result


__all__ = [
    "DEFAULT_DEMO_PATH", "DEFAULT_RIG_PATH", "PORTABLE_SCHEMA", "RIG_SCHEMA", "attach_ground",
    "attach_selected_ground", "bake_ground", "build_example_scene",
    "build_demo_scene", "build_vehicle_rig", "find_rig_roots", "find_template_roots",
    "install_ground_callback", "install_ground_callbacks", "install_scene_callbacks",
    "remove_ground_callback", "remove_all_ground_callbacks",
    "update_registered_live_rigs", "save_vehicle_rig",
    "reset_wheel_roll", "update_ground",
]
