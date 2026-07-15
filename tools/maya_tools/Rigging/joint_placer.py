"""
joint_placer.py

First-pass automatic biped joint placement for Maya.

Design goal:
    mesh -> generated skeleton -> setup_hik-owned body/face maps

This module intentionally does NOT define its own HIK map. It creates joints with
names that setup_hik.guess_joint_map_from_root() already understands, then asks
setup_hik to build the mapping used by create_rig.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import maya.cmds as cmds
import maya.api.OpenMaya as om

from maya_tools.Rigging.mocap import setup_hik


Vector3 = Tuple[float, float, float]
GENERATED_ATTR = "autoJointPlacerGenerated"
POSE_ATTR = "autoJointPlacerPose"
POSE_ANGLE_ATTR = "autoJointPlacerPoseAngle"
PLANAR_TOLERANCE = 0.001


@dataclass
class PlacementResult:
    root_joint: str
    body_joint_map: dict
    face_joint_map: dict
    points: Dict[str, Vector3]
    confidence: Dict[str, float]
    pose_type: str = "unknown"
    pose_angle_degrees: float = 0.0
    planar_deviation: Dict[str, float] = field(default_factory=dict)


# Proportional fallback template.
# Values are normalized against the mesh bounding box:
#   x: -0.5 left side of bbox to +0.5 right side of bbox
#   y:  0.0 bottom to 1.0 top
#   z: -0.5 back to +0.5 front
# This is deliberately simple and predictable. Later solvers can override
# individual entries with cross-section or landmark results.
BIPED_PROPORTIONS: Dict[str, Vector3] = {
    "origin": (0.0, 0.50, 0.0),
    "pelvis": (0.0, 0.48, 0.0),

    "spine_01": (0.0, 0.56, 0.0),
    "spine_02": (0.0, 0.64, 0.0),
    "spine_03": (0.0, 0.72, 0.0),
    "spine_04": (0.0, 0.78, 0.0),

    "neck": (0.0, 0.86, 0.0),
    "head": (0.0, 0.93, 0.0),
    "head_tip": (0.0, 0.99, 0.0),

    "l_clavicle": (0.13, 0.80, 0.0),
    "l_upperarm": (0.25, 0.78, 0.0),
    "l_lowerarm": (0.42, 0.69, 0.0),
    "l_hand": (0.56, 0.61, 0.0),
    "l_hand_tip": (0.63, 0.59, 0.0),

    "r_clavicle": (-0.13, 0.80, 0.0),
    "r_upperarm": (-0.25, 0.78, 0.0),
    "r_lowerarm": (-0.42, 0.69, 0.0),
    "r_hand": (-0.56, 0.61, 0.0),
    "r_hand_tip": (-0.63, 0.59, 0.0),

    "l_thigh": (0.13, 0.46, 0.0),
    "l_knee": (0.13, 0.27, 0.02),
    "l_ankle": (0.13, 0.08, 0.0),
    "l_toe": (0.13, 0.035, 0.18),
    "l_toeTip": (0.13, 0.03, 0.28),

    "r_thigh": (-0.13, 0.46, 0.0),
    "r_knee": (-0.13, 0.27, 0.02),
    "r_ankle": (-0.13, 0.08, 0.0),
    "r_toe": (-0.13, 0.035, 0.18),
    "r_toeTip": (-0.13, 0.03, 0.28),
}


PARENT_MAP = {
    "pelvis": "origin",
    "spine_01": "pelvis",
    "spine_02": "spine_01",
    "spine_03": "spine_02",
    "spine_04": "spine_03",
    "neck": "spine_04",
    "head": "neck",
    "head_tip": "head",

    "l_clavicle": "spine_04",
    "l_upperarm": "l_clavicle",
    "l_lowerarm": "l_upperarm",
    "l_hand": "l_lowerarm",
    "l_hand_tip": "l_hand",

    "r_clavicle": "spine_04",
    "r_upperarm": "r_clavicle",
    "r_lowerarm": "r_upperarm",
    "r_hand": "r_lowerarm",
    "r_hand_tip": "r_hand",

    "l_thigh": "pelvis",
    "l_knee": "l_thigh",
    "l_ankle": "l_knee",
    "l_toe": "l_ankle",
    "l_toeTip": "l_toe",

    "r_thigh": "pelvis",
    "r_knee": "r_thigh",
    "r_ankle": "r_knee",
    "r_toe": "r_ankle",
    "r_toeTip": "r_toe",
}


BUILD_ORDER = [
    "origin",
    "pelvis",
    "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head", "head_tip",
    "l_clavicle", "l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip",
    "r_clavicle", "r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip",
    "l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip",
    "r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip",
]


def _short_name(node: str) -> str:
    return node.split("|")[-1]


def _point_vector(points: Dict[str, Vector3], name: str) -> Optional[om.MVector]:
    value = points.get(name)
    if not value:
        return None
    return om.MVector(value[0], value[1], value[2])


def classify_arm_pose(points: Dict[str, Vector3]) -> Tuple[str, float]:
    """
    Classify generated arm placement as T-pose or A-pose from shoulder-to-hand slope.

    Returns:
        tuple[str, float]: pose label and absolute arm-down angle from horizontal.
    """
    samples = []
    for side in ("l", "r"):
        shoulder = _point_vector(points, "{0}_upperarm".format(side))
        hand = _point_vector(points, "{0}_hand".format(side))
        if not shoulder or not hand:
            continue
        delta = hand - shoulder
        horizontal = abs(delta.x)
        vertical_drop = max(0.0, shoulder.y - hand.y)
        if horizontal <= 0.0001:
            continue
        samples.append(math.degrees(math.atan2(vertical_drop, horizontal)))

    if not samples:
        return "unknown", 0.0

    angle = sum(samples) / float(len(samples))
    if angle <= 12.0:
        return "t_pose", angle
    if angle >= 22.0:
        return "a_pose", angle
    return "relaxed_t_pose", angle


def _with_z(point: Vector3, z_value: float) -> Vector3:
    return (point[0], point[1], z_value)


def enforce_limb_planarity(points: Dict[str, Vector3]) -> Dict[str, Vector3]:
    """
    Keep generated arms and legs mostly planar per side.

    Arms are flattened from upperarm/shoulder through hand tip. Clavicles keep
    their own raised placement because the T-pose setup can intentionally adjust
    them. Legs are flattened from thigh through toe tip. This avoids accidental
    out-of-plane joint chains while still allowing left/right X and height
    differences.
    """
    result = dict(points)
    chains = [
        ("l_arm", ["l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip"]),
        ("r_arm", ["r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip"]),
        ("l_leg", ["l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip"]),
        ("r_leg", ["r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip"]),
    ]

    for _, chain in chains:
        values = [result[name][2] for name in chain if name in result]
        if not values:
            continue
        plane_z = sum(values) / float(len(values))
        for name in chain:
            if name in result:
                result[name] = _with_z(result[name], plane_z)

    return result


def measure_planar_deviation(points: Dict[str, Vector3]) -> Dict[str, float]:
    deviations = {}
    chains = {
        "l_arm": ["l_upperarm", "l_lowerarm", "l_hand", "l_hand_tip"],
        "r_arm": ["r_upperarm", "r_lowerarm", "r_hand", "r_hand_tip"],
        "l_leg": ["l_thigh", "l_knee", "l_ankle", "l_toe", "l_toeTip"],
        "r_leg": ["r_thigh", "r_knee", "r_ankle", "r_toe", "r_toeTip"],
    }
    for label, chain in chains.items():
        values = [points[name][2] for name in chain if name in points]
        if not values:
            deviations[label] = 0.0
            continue
        plane_z = sum(values) / float(len(values))
        deviations[label] = max(abs(value - plane_z) for value in values)
    return deviations


def _as_mesh_transform(node: str) -> str:
    """Return a mesh transform from a selected transform or mesh shape."""
    if not node or not cmds.objExists(node):
        cmds.error("Mesh does not exist: {0}".format(node))

    if cmds.nodeType(node) == "mesh":
        parent = cmds.listRelatives(node, parent=True, fullPath=False) or []
        if not parent:
            cmds.error("Mesh shape has no transform parent: {0}".format(node))
        return parent[0]

    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=False) or []
    mesh_shapes = [s for s in shapes if cmds.nodeType(s) == "mesh"]
    if not mesh_shapes:
        cmds.error("Selected object is not a mesh transform: {0}".format(node))
    return node


def get_mesh_bounds(mesh: str) -> Dict[str, object]:
    mesh = _as_mesh_transform(mesh)
    bbox = cmds.exactWorldBoundingBox(mesh)
    min_v = om.MVector(bbox[0], bbox[1], bbox[2])
    max_v = om.MVector(bbox[3], bbox[4], bbox[5])
    center = (min_v + max_v) * 0.5

    return {
        "min": min_v,
        "max": max_v,
        "center": center,
        "width": max_v.x - min_v.x,
        "height": max_v.y - min_v.y,
        "depth": max_v.z - min_v.z,
    }


def point_from_normalized_bounds(bounds: Dict[str, object], xyz: Vector3) -> Vector3:
    x_norm, y_norm, z_norm = xyz
    min_v = bounds["min"]
    center = bounds["center"]

    x = center.x + (bounds["width"] * x_norm)
    y = min_v.y + (bounds["height"] * y_norm)
    z = center.z + (bounds["depth"] * z_norm)
    return (x, y, z)


def solve_basic_biped_points(mesh: str) -> Tuple[Dict[str, Vector3], Dict[str, float]]:
    """
    Return first-pass biped joint positions.

    The current implementation is proportional, with confidence set low/medium.
    This gives a stable baseline that can later be refined by landmark or mesh
    cross-section solvers without changing the downstream rigging code.
    """
    bounds = get_mesh_bounds(mesh)
    points = {
        name: point_from_normalized_bounds(bounds, normalized)
        for name, normalized in BIPED_PROPORTIONS.items()
    }
    points = enforce_limb_planarity(points)
    confidence = {name: 0.50 for name in points}

    # Spine/head centerline tends to be more reliable from bbox proportions.
    for name in ["origin", "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "neck", "head"]:
        confidence[name] = 0.65

    return points, confidence


def _is_generated_joint(joint: str) -> bool:
    if not joint or not cmds.objExists(joint):
        return False
    if not cmds.attributeQuery(GENERATED_ATTR, node=joint, exists=True):
        return False
    try:
        return bool(cmds.getAttr("{0}.{1}".format(joint, GENERATED_ATTR)))
    except Exception:
        return False


def _tag_generated_joint(joint: str) -> None:
    if not joint or not cmds.objExists(joint):
        return
    if not cmds.attributeQuery(GENERATED_ATTR, node=joint, exists=True):
        cmds.addAttr(joint, longName=GENERATED_ATTR, attributeType="bool")
    cmds.setAttr("{0}.{1}".format(joint, GENERATED_ATTR), True)


def _set_string_attr(node: str, attr: str, value: str) -> None:
    if not node or not cmds.objExists(node):
        return
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, longName=attr, dataType="string")
    cmds.setAttr("{0}.{1}".format(node, attr), value, type="string")


def _set_float_attr(node: str, attr: str, value: float) -> None:
    if not node or not cmds.objExists(node):
        return
    if not cmds.attributeQuery(attr, node=node, exists=True):
        cmds.addAttr(node, longName=attr, attributeType="double")
    cmds.setAttr("{0}.{1}".format(node, attr), float(value))


def tag_pose_metadata(root_joint: str, pose_type: str, pose_angle_degrees: float) -> None:
    _set_string_attr(root_joint, POSE_ATTR, pose_type)
    _set_float_attr(root_joint, POSE_ANGLE_ATTR, pose_angle_degrees)


def delete_existing_generated_skeleton(root_name: str = "origin") -> None:
    if not cmds.objExists(root_name):
        return
    if not _is_generated_joint(root_name):
        cmds.error(
            "Refusing to delete existing joint '{0}' because it was not created by joint_placer.".format(root_name)
        )
    cmds.delete(root_name)


def create_joint(name: str, position: Vector3, parent: Optional[str] = None, radius: float = 1.0) -> str:
    if cmds.objExists(name):
        if _is_generated_joint(name):
            cmds.delete(name)
        else:
            cmds.error(
                "Refusing to replace existing node '{0}' because it was not created by joint_placer.".format(name)
            )

    cmds.select(clear=True)
    joint = cmds.joint(name=name, position=position, radius=radius)
    _tag_generated_joint(joint)

    if parent and cmds.objExists(parent):
        cmds.parent(joint, parent)

    return joint


def orient_skeleton(root_joint: str) -> None:
    if not root_joint or not cmds.objExists(root_joint):
        return

    cmds.select(root_joint, hierarchy=True)
    try:
        cmds.joint(
            edit=True,
            orientJoint="xyz",
            secondaryAxisOrient="yup",
            children=True,
            zeroScaleOrient=True,
        )
    except Exception as exc:
        cmds.warning("[joint_placer] Joint orient failed: {0}".format(exc))


def _world_align_joint_preserving_children(joint: str) -> None:
    if not joint or not cmds.objExists(joint):
        return

    children = cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []
    child_world_matrices = {
        child: cmds.xform(child, query=True, worldSpace=True, matrix=True)
        for child in children
    }

    for child in children:
        cmds.parent(child, world=True)

    for attr in ("jointOrient", "rotate"):
        for axis in ("X", "Y", "Z"):
            plug = "{0}.{1}{2}".format(joint, attr, axis)
            if cmds.objExists(plug):
                try:
                    cmds.setAttr(plug, 0.0)
                except Exception:
                    pass

    for child in children:
        if cmds.objExists(child):
            cmds.parent(child, joint)
            cmds.xform(child, worldSpace=True, matrix=child_world_matrices[child])


def world_align_origin_and_pelvis(root_joint: str) -> None:
    _world_align_joint_preserving_children(root_joint)
    pelvis_children = cmds.listRelatives(root_joint, children=True, type="joint", fullPath=False) or []
    for child in pelvis_children:
        if _short_name(child) == "pelvis":
            _world_align_joint_preserving_children(child)
            return


def build_skeleton_from_points(
    points: Dict[str, Vector3],
    root_name: str = "origin",
    orient: bool = True,
    replace_existing: bool = True,
    pose_type: str = "unknown",
    pose_angle_degrees: float = 0.0,
) -> str:
    if replace_existing:
        delete_existing_generated_skeleton(root_name)

    created = {}

    for name in BUILD_ORDER:
        if name not in points:
            continue
        parent = PARENT_MAP.get(name)
        created_parent = created.get(parent) if parent else None
        created[name] = create_joint(name, points[name], parent=created_parent)

    root_joint = created.get(root_name, root_name)

    if orient:
        orient_skeleton(root_joint)

    world_align_origin_and_pelvis(root_joint)
    tag_pose_metadata(root_joint, pose_type, pose_angle_degrees)

    return root_joint


def make_hik_maps_from_root(root_joint: str) -> Tuple[dict, dict]:
    body_joint_map = setup_hik.guess_joint_map_from_root(root_joint)
    face_joint_map = setup_hik.populate_default_face_map_from_scene()
    return body_joint_map, face_joint_map


CORE_HIK_SLOTS = (
    "Reference",
    "Hips",
    "Spine",
    "Spine1",
    "Spine2",
    "Spine3",
    "Neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
)


def validate_body_joint_map(body_joint_map: dict, required_slots: Iterable[str] = CORE_HIK_SLOTS) -> List[str]:
    missing = []
    for slot in required_slots:
        joint = (body_joint_map.get(slot) or {}).get("joint")
        if not joint or not cmds.objExists(joint):
            missing.append(slot)
    return missing


def create_guides_from_points(points: Dict[str, Vector3], group_name: str = "auto_joint_guides_grp") -> List[str]:
    """Optional visual guide locators for debugging/approval before skeleton creation."""
    if cmds.objExists(group_name):
        cmds.delete(group_name)
    group = cmds.group(empty=True, name=group_name)

    locators = []
    for name in BUILD_ORDER:
        if name not in points:
            continue
        loc = cmds.spaceLocator(name="{0}_guide".format(name))[0]
        cmds.xform(loc, worldSpace=True, translation=points[name])
        cmds.parent(loc, group)
        locators.append(loc)

    return locators


def build_basic_biped_skeleton(
    mesh: str,
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
) -> PlacementResult:
    mesh = _as_mesh_transform(mesh)
    points, confidence = solve_basic_biped_points(mesh)
    pose_type, pose_angle_degrees = classify_arm_pose(points)
    planar_deviation = measure_planar_deviation(points)

    if create_guides:
        create_guides_from_points(points)

    root_joint = build_skeleton_from_points(
        points,
        root_name="origin",
        orient=orient,
        replace_existing=replace_existing,
        pose_type=pose_type,
        pose_angle_degrees=pose_angle_degrees,
    )

    body_joint_map, face_joint_map = make_hik_maps_from_root(root_joint)
    missing_slots = validate_body_joint_map(body_joint_map)
    if missing_slots:
        cmds.warning(
            "[joint_placer] Generated skeleton did not fill HIK slots: {0}".format(
                ", ".join(missing_slots)
            )
        )

    return PlacementResult(
        root_joint=root_joint,
        body_joint_map=body_joint_map,
        face_joint_map=face_joint_map,
        points=points,
        confidence=confidence,
        pose_type=pose_type,
        pose_angle_degrees=pose_angle_degrees,
        planar_deviation=planar_deviation,
    )


def create_auto_joints_for_mesh(
    mesh: str,
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
) -> Tuple[dict, dict]:
    result = build_basic_biped_skeleton(
        mesh=mesh,
        orient=orient,
        replace_existing=replace_existing,
        create_guides=create_guides,
    )
    return result.body_joint_map, result.face_joint_map


def create_auto_joints_for_selected_mesh(
    orient: bool = True,
    replace_existing: bool = True,
    create_guides: bool = False,
) -> Tuple[dict, dict]:
    selection = cmds.ls(selection=True, long=False) or []
    if not selection:
        cmds.error("Select a mesh transform first.")

    mesh = _as_mesh_transform(selection[0])
    return create_auto_joints_for_mesh(
        mesh=mesh,
        orient=orient,
        replace_existing=replace_existing,
        create_guides=create_guides,
    )
