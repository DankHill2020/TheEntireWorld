import maya.mel as mel
import os
import maya.cmds as cmds
import maya.api.OpenMaya as om
import math
import re
import copy
import json
from maya_tools.Utilities import joints as joints_util
from maya_tools.Rigging.undo_utils import undoable
from maya_tools.Rigging.temp_cleanup import cleanup_temp_bones
from utilities.p4_utils import prepare_file_for_write

DEFAULT_FACE_JOINT_MAP = {

    # ---------- BROWS (up to 5 per side) ----------
    "LeftBrow": {
        "index": 0,
        "joints": []   # e.g. l_brow1 → l_brow5
    },
    "RightBrow": {
        "index": 1,
        "joints": []   # e.g. r_brow1 → r_brow5
    },

    # ---------- EYELIDS ----------
    "LeftEyelid": {
        "index": 10,
        "outer": {"joint": ""},
        "upper": {"joints": []},
        "inner": {"joint": ""},
        "lower": {"joints": []},
        "joints": []
    },

    "RightEyelid": {
        "index": 20,
        "outer": {"joint": ""},
        "upper": {"joints": []},
        "inner": {"joint": ""},
        "lower": {"joints": []},
        "joints": []
    },

    "LeftEye": {"index": 70, "joint": ""},
    "RightEye": {"index": 71, "joint": ""},

    # ---------- LIPS ----------
    "LipChain": {
        "index": 30,
        "joints": []
    },

    "UpperLipCenter": {"index": 31, "joint": ""},
    "LowerLipCenter": {"index": 32, "joint": ""},
    "LeftLipCorner":  {"index": 33, "joint": ""},
    "RightLipCorner": {"index": 34, "joint": ""},

    # ---------- JAW ----------
    "Jaw": {"index": 40, "joint": ""},

    # ---------- TONGUE ----------
    "TongueChain": {
        "index": 50,
        "joints": []   # tongue1 → tongueN
    },

    # ---------- TEETH ----------
    "UpperTeeth": {"index": 60, "joint": ""},
    "LowerTeeth": {"index": 61, "joint": ""},

    # ---------- NOSE ----------
    "NoseRoot": {"index": 80, "joint": ""},

    # ---------- EVERYTHING ELSE ----------
    "OtherFaceJoints": {
        "index": 100,
        "joints": []
    }
}

DEFAULT_JOINT_MAP = {
    "Reference": {"index": 0, "joint": ""},
    "Hips": {"index": 1, "joint": ""},
    "LeftUpLeg": {"index": 2, "joint": ""},
    "LeftLeg": {"index": 3, "joint": ""},
    "LeftFoot": {"index": 4, "joint": ""},
    "LeftToeBase": {"index": 16, "joint": ""},
    "RightUpLeg": {"index": 5, "joint": ""},
    "RightLeg": {"index": 6, "joint": ""},
    "RightFoot": {"index": 7, "joint": ""},
    "RightToeBase": {"index": 17, "joint": ""},
    "Spine": {"index": 8, "joint": ""},
    "Spine1": {"index": 23, "joint": ""},
    "Spine2": {"index": 24, "joint": ""},
    "Spine3": {"index": 25, "joint": ""},
    "Neck": {"index": 20, "joint": ""},
    "Neck1": {"index": 32, "joint": ""},
    "Head": {"index": 15, "joint": ""},
    "LeftShoulder": {"index": 18, "joint": ""},
    "LeftArm": {"index": 9, "joint": ""},
    "LeftForeArm": {"index": 10, "joint": ""},
    "LeftHand": {"index": 11, "joint": ""},
    "LeftInHandIndex": {"index": 147, "joint": ""},
    "LeftInHandMiddle": {"index": 148, "joint": ""},
    "LeftInHandRing": {"index": 149, "joint": ""},
    "LeftInHandPinky": {"index": 150, "joint": ""},
    "LeftHandThumb1": {"index": 50, "joint": ""},
    "LeftHandIndex1": {"index": 54, "joint": ""},
    "LeftHandMiddle1": {"index": 58, "joint": ""},
    "LeftHandRing1": {"index": 62, "joint": ""},
    "LeftHandPinky1": {"index": 66, "joint": ""},
    "LeftHandThumb2": {"index": 51, "joint": ""},
    "LeftHandIndex2": {"index": 55, "joint": ""},
    "LeftHandMiddle2": {"index": 59, "joint": ""},
    "LeftHandRing2": {"index": 63, "joint": ""},
    "LeftHandPinky2": {"index": 67, "joint": ""},
    "LeftHandThumb3": {"index": 52, "joint": ""},
    "LeftHandIndex3": {"index": 56, "joint": ""},
    "LeftHandMiddle3": {"index": 60, "joint": ""},
    "LeftHandRing3": {"index": 64, "joint": ""},
    "LeftHandPinky3": {"index": 68, "joint": ""},
    "LeftHandThumb4": {"index": 53, "joint": ""},
    "LeftHandIndex4": {"index": 57, "joint": ""},
    "LeftHandMiddle4": {"index": 61, "joint": ""},
    "LeftHandRing4": {"index": 65, "joint": ""},
    "LeftHandPinky4": {"index": 69, "joint": ""},
    "RightShoulder": {"index": 19, "joint": ""},
    "RightArm": {"index": 12, "joint": ""},
    "RightForeArm": {"index": 13, "joint": ""},
    "RightHand": {"index": 14, "joint": ""},
    "RightInHandIndex": {"index": 153, "joint": ""},
    "RightInHandMiddle": {"index": 154, "joint": ""},
    "RightInHandRing": {"index": 155, "joint": ""},
    "RightInHandPinky": {"index": 156, "joint": ""},
    "RightHandThumb1": {"index": 74, "joint": ""},
    "RightHandIndex1": {"index": 78, "joint": ""},
    "RightHandMiddle1": {"index": 82, "joint": ""},
    "RightHandRing1": {"index": 86, "joint": ""},
    "RightHandPinky1": {"index": 90, "joint": ""},
    "RightHandThumb2": {"index": 75, "joint": ""},
    "RightHandIndex2": {"index": 79, "joint": ""},
    "RightHandMiddle2": {"index": 83, "joint": ""},
    "RightHandRing2": {"index": 87, "joint": ""},
    "RightHandPinky2": {"index": 91, "joint": ""},
    "RightHandThumb3": {"index": 76, "joint": ""},
    "RightHandIndex3": {"index": 80, "joint": ""},
    "RightHandMiddle3": {"index": 84, "joint": ""},
    "RightHandRing3": {"index": 88, "joint": ""},
    "RightHandPinky3": {"index": 92, "joint": ""},
    "RightHandThumb4": {"index": 77, "joint": ""},
    "RightHandIndex4": {"index": 81, "joint": ""},
    "RightHandMiddle4": {"index": 85, "joint": ""},
    "RightHandRing4": {"index": 89, "joint": ""},
    "RightHandPinky4": {"index": 93, "joint": ""},

    "LeftArmRoll": {"index": 45, "joint": ""},
    "LeafLeftArmRoll1": {"index": 176, "joint": ""},
    "LeafLeftArmRoll2": {"index": 184, "joint": ""},
    "LeafLeftArmRoll3": {"index": 192, "joint": ""},

    "RightArmRoll": {"index": 47, "joint": ""},
    "LeafRightArmRoll1": {"index": 178, "joint": ""},
    "LeafRightArmRoll2": {"index": 186, "joint": ""},
    "LeafRightArmRoll3": {"index": 194, "joint": ""},

    "LeftForeArmRoll": {"index": 46, "joint": ""},
    "LeafLeftForearmRoll1": {"index": 177, "joint": ""},
    "LeafLeftForearmRoll2": {"index": 185, "joint": ""},
    "LeafLeftForearmRoll3": {"index": 193, "joint": ""},

    "RightForeArmRoll": {"index": 48, "joint": ""},
    "LeafRightForearmRoll1": {"index": 179, "joint": ""},
    "LeafRightForearmRoll2": {"index": 187, "joint": ""},
    "LeafRightForearmRoll3": {"index": 195, "joint": ""},

    "LeftUpLegRoll": {"index": 41, "joint": ""},
    "LeafLeftUpLegRoll1": {"index": 172, "joint": ""},
    "LeafLeftUpLegRoll2": {"index": 180, "joint": ""},
    "LeafLeftUpLegRoll3": {"index": 188, "joint": ""},

    "RightUpLegRoll": {"index": 43, "joint": ""},
    "LeafRightUpLegRoll1": {"index": 174, "joint": ""},
    "LeafRightUpLegRoll2": {"index": 182, "joint": ""},
    "LeafRightUpLegRoll3": {"index": 190, "joint": ""},

    "LeftLegRoll": {"index": 42, "joint": ""},
    "LeafLeftLegRoll1": {"index": 173, "joint": ""},
    "LeafLeftLegRoll2": {"index": 181, "joint": ""},

    "RightLegRoll": {"index": 44, "joint": ""},
    "LeafRightLegRoll1": {"index": 175, "joint": ""},
    "LeafRightLegRoll2": {"index": 183, "joint": ""}

}


def get_descendant_joints(root_joint):
    """Returns all descendant joints of root_joint (including root)."""
    if not root_joint or not cmds.objExists(root_joint):
        return []
    return [root_joint] + cmds.listRelatives(root_joint, allDescendents=True, type="joint") or []


def find_face_joints(pattern, face_joints):
    """Return joints in the scene matching the pattern that are descendants of the face root."""
    all_matches = cmds.ls(pattern, type="joint") or []
    return [j for j in all_matches if j in face_joints]


def _exists(j):
    return j if j and cmds.objExists(j) else None


def get_world_position(obj):
    """
    Gets the world position
    :param obj: name of object
    :return:
    """
    pos = cmds.xform(obj, q=True, ws=True, t=True)
    return om.MVector(pos)


def align_clavicle_Y_by_rotateY(clavicle_joint, sample_range=30.0, step=0.1):
    """Level the first clavicle child by changing only rotateY."""
    if not clavicle_joint or not cmds.objExists(clavicle_joint):
        return None
    children = cmds.listRelatives(
        clavicle_joint, type="joint", children=True, fullPath=True
    ) or []
    if not children:
        print("No child joint found for {}".format(clavicle_joint))
        return None
    _ = step  # Backward-compatible argument; the bounded optimizer is adaptive.
    return _sample_rotation_axis(
        clavicle_joint,
        "Y",
        lambda: abs(
            get_world_position(clavicle_joint).y
            - get_world_position(children[0]).y
        ),
        sample_range=sample_range,
    )


def _best_oriented_rotation_axis(
        joint, world_direction=(0.0, 0.0, 1.0), candidates=("X", "Y", "Z")):
    """Return the local rotate axis most parallel to a world-space direction."""
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    world_axes = {
        "X": om.MVector(*matrix[0:3]),
        "Y": om.MVector(*matrix[4:7]),
        "Z": om.MVector(*matrix[8:11]),
    }
    direction = om.MVector(*world_direction)
    if direction.length() <= 1.0e-8:
        raise ValueError("world_direction must be non-zero")
    direction.normalize()
    valid = [str(axis).upper() for axis in candidates]
    if not valid or any(axis not in world_axes for axis in valid):
        raise ValueError("candidates must contain local X, Y, or Z axes")
    return max(
        valid,
        key=lambda axis: abs(world_axes[axis].normal() * direction),
    )


def align_clavicle_to_upperarm_height(
        clavicle_joint, upperarm_joint, sample_range=30.0, step=0.1):
    """Level clavicle local X in front view with a pure world-Z rotation.

    The studio clavicle frame uses local Y for its authored forward/back roll
    and local Z close to world vertical.  Rotating whichever local axis merely
    happens to be closest to world depth can therefore swing the clavicle
    forward.  A world-Z rotation changes only its front-view elevation while
    preserving the reference-rig depth component and roll convention.
    """
    if not all(
            joint and cmds.objExists(joint)
            for joint in (clavicle_joint, upperarm_joint)):
        return None
    _ = (sample_range, step, upperarm_joint)  # Public-call compatibility.
    translate_before = tuple(cmds.getAttr(clavicle_joint + ".translate")[0])
    joint_orient_before = tuple(cmds.getAttr(clavicle_joint + ".jointOrient")[0])
    rotate_axis_before = tuple(cmds.getAttr(clavicle_joint + ".rotateAxis")[0])
    matrix_before = cmds.xform(
        clavicle_joint, query=True, worldSpace=True, matrix=True
    )
    axes_before = [
        om.MVector(*matrix_before[0:3]),
        om.MVector(*matrix_before[4:7]),
        om.MVector(*matrix_before[8:11]),
    ]
    x_axis = axes_before[0].normal()
    current_azimuth = math.atan2(x_axis.y, x_axis.x)
    target_azimuth = 0.0 if x_axis.x >= 0.0 else math.pi
    delta = math.atan2(
        math.sin(target_azimuth - current_azimuth),
        math.cos(target_azimuth - current_azimuth),
    )
    world_z_rotation = om.MQuaternion(delta, om.MVector(0.0, 0.0, 1.0))
    target_axes = [axis.rotateBy(world_z_rotation) for axis in axes_before]
    position = cmds.xform(
        clavicle_joint, query=True, worldSpace=True, translation=True
    )
    target = cmds.createNode(
        "transform",
        name=clavicle_joint.split("|")[-1].replace(":", "_")
        + "_frontViewLiftTemp",
    )
    cmds.xform(target, worldSpace=True, matrix=[
        target_axes[0].x, target_axes[0].y, target_axes[0].z, 0.0,
        target_axes[1].x, target_axes[1].y, target_axes[1].z, 0.0,
        target_axes[2].x, target_axes[2].y, target_axes[2].z, 0.0,
        position[0], position[1], position[2], 1.0,
    ])
    constraint = cmds.orientConstraint(
        target, clavicle_joint, maintainOffset=False
    )[0]
    cmds.delete(constraint, target)

    for attribute, before in (
        ("translate", translate_before),
        ("jointOrient", joint_orient_before),
        ("rotateAxis", rotate_axis_before),
    ):
        after = tuple(cmds.getAttr(
            "{}.{}".format(clavicle_joint, attribute)
        )[0])
        if any(abs(after[index] - before[index]) > 1.0e-8 for index in range(3)):
            raise RuntimeError(
                "T-pose clavicle lift changed {}.{}".format(
                    clavicle_joint, attribute
                )
            )
    matrix_after = cmds.xform(
        clavicle_joint, query=True, worldSpace=True, matrix=True
    )
    world_x_after = tuple(matrix_after[0:3])
    if abs(world_x_after[1]) > 1.0e-5:
        raise RuntimeError(
            "T-pose clavicle X axis is not flat in front view: {}".format(
                world_x_after
            )
        )
    if abs(world_x_after[2] - x_axis.z) > 1.0e-5:
        raise RuntimeError(
            "T-pose clavicle lift changed the authored depth orientation"
        )
    return {
        "rotation_space": "world_z_only",
        "rotation_degrees": math.degrees(delta),
        "world_x_before": tuple(x_axis),
        "world_x_after": world_x_after,
        "front_view_flat": True,
        "depth_orientation_preserved": True,
    }


def _aim_frame_preserving_roll(world_matrix, target_x):
    """Aim a world frame's X axis by shortest arc without changing its roll."""
    current_x = om.MVector(*world_matrix[0:3]).normal()
    current_y = om.MVector(*world_matrix[4:7]).normal()
    current_z = om.MVector(*world_matrix[8:11]).normal()
    desired_x = om.MVector(*target_x)
    if desired_x.length() <= 1.0e-8:
        raise ValueError("target_x must be non-zero")
    desired_x.normalize()
    shortest_arc = current_x.rotateTo(desired_x)
    aimed_y = current_y.rotateBy(shortest_arc).normal()
    aimed_z = current_z.rotateBy(shortest_arc).normal()
    return (
        (desired_x.x, desired_x.y, desired_x.z),
        (aimed_y.x, aimed_y.y, aimed_y.z),
        (aimed_z.x, aimed_z.y, aimed_z.z),
    )


def _canonical_t_pose_arm_frame(target_x, side):
    """Return a mirrored T-pose frame with local Z as the elbow hinge axis."""
    x_axis = om.MVector(*target_x)
    if x_axis.length() <= 1.0e-8:
        raise ValueError("target_x must be non-zero")
    x_axis.normalize()
    # Studio arms share +X as their basis aim. Their mirrored local-Z hinge
    # points down on the left and up on the right; local Y consequently points
    # into opposite depth directions. This removes arbitrary source arm roll
    # while retaining the mirrored production-frame convention.
    z_axis = om.MVector(0.0, 1.0 if side == "r" else -1.0, 0.0)
    z_axis -= x_axis * (z_axis * x_axis)
    if z_axis.length() <= 1.0e-8:
        raise RuntimeError("T-pose arm aim is parallel to its hinge axis")
    z_axis.normalize()
    y_axis = z_axis ^ x_axis
    y_axis.normalize()
    return (
        (x_axis.x, x_axis.y, x_axis.z),
        (y_axis.x, y_axis.y, y_axis.z),
        (z_axis.x, z_axis.y, z_axis.z),
    )


def aim_joint_x_axis_to_world_x(joint_name, side=None):
    """Aim local +X at world +X and normalize mirrored arm roll for T-pose."""
    if not joint_name or not cmds.objExists(joint_name):
        return

    translate_before = tuple(cmds.getAttr(joint_name + ".translate")[0])
    joint_orient_before = tuple(cmds.getAttr(joint_name + ".jointOrient")[0])
    rotate_axis_before = tuple(cmds.getAttr(joint_name + ".rotateAxis")[0])
    joint_pos = cmds.xform(joint_name, q=True, ws=True, t=True)

    matrix_before = cmds.xform(joint_name, q=True, ws=True, matrix=True)
    if side in ("l", "r"):
        x_axis, y_axis, z_axis = _canonical_t_pose_arm_frame(
            (1.0, 0.0, 0.0), side
        )
    else:
        x_axis, y_axis, z_axis = _aim_frame_preserving_roll(
            matrix_before, (1.0, 0.0, 0.0)
        )
    target_name = (
        joint_name.split("|")[-1].replace(":", "_") + "_worldAlignTemp"
    )
    target = cmds.createNode("transform", name=target_name)
    cmds.xform(target, worldSpace=True, matrix=[
        x_axis[0], x_axis[1], x_axis[2], 0.0,
        y_axis[0], y_axis[1], y_axis[2], 0.0,
        z_axis[0], z_axis[1], z_axis[2], 0.0,
        joint_pos[0], joint_pos[1], joint_pos[2], 1.0,
    ])

    # Let Maya solve the rotate channels against the joint's real parent,
    # rotate order, rotateAxis, and jointOrient. The previous manual local
    # Euler decomposition treated the desired matrix as channel rotation and
    # therefore applied jointOrient a second time.
    constraint = cmds.orientConstraint(
        target, joint_name, maintainOffset=False
    )[0]
    cmds.delete(constraint, target)

    for attribute, before in (
        ("translate", translate_before),
        ("jointOrient", joint_orient_before),
        ("rotateAxis", rotate_axis_before),
    ):
        after = tuple(cmds.getAttr(
            "{}.{}".format(joint_name, attribute)
        )[0])
        if any(abs(after[index] - before[index]) > 1.0e-8 for index in range(3)):
            raise RuntimeError(
                "T-pose world-axis solve changed {}.{}".format(
                    joint_name, attribute
                )
            )

    matrix = cmds.xform(joint_name, q=True, ws=True, matrix=True)
    actual_axes = {
        "x": tuple(matrix[0:3]),
        "y": tuple(matrix[4:7]),
        "z": tuple(matrix[8:11]),
    }
    axis_errors = {
        "x": max(abs(actual_axes["x"][index] - x_axis[index]) for index in range(3)),
        "y": max(abs(actual_axes["y"][index] - y_axis[index]) for index in range(3)),
        "z": max(abs(actual_axes["z"][index] - z_axis[index]) for index in range(3)),
    }
    if max(axis_errors.values()) > 1.0e-5:
        raise RuntimeError(
            "T-pose arm world-axis solve failed for {}: {}".format(
                joint_name, axis_errors
            )
        )
    return {
        "world_x": actual_axes["x"],
        "world_y": actual_axes["y"],
        "world_z": actual_axes["z"],
        "axis_errors": axis_errors,
        "roll_preserved": side not in ("l", "r"),
        "roll_normalized": side in ("l", "r"),
        "joint_orient_preserved": True,
        "translate_preserved": True,
    }


def _set_oriented_elbow_prebend(elbow, hand, degrees=3.0):
    """Aim the forearm in depth while retaining its placed roll frame."""
    if not all(node and cmds.objExists(node) for node in (elbow, hand)):
        return {"skipped": True, "reason": "missing_chain"}

    name_lower = elbow.lower().split("|")[-1].split(":")[-1]
    is_right = any(
        token in name_lower for token in ("r_", "_r", "right")
    ) or name_lower.startswith("r")
    radians = math.radians(abs(float(degrees)))
    cosine = math.cos(radians)
    sine = math.sin(radians)
    matrix_before = cmds.xform(elbow, q=True, ws=True, matrix=True)
    x_axis, y_axis, z_axis = _canonical_t_pose_arm_frame(
        (cosine, 0.0, -sine if is_right else sine),
        "r" if is_right else "l",
    )
    elbow_position = cmds.xform(elbow, q=True, ws=True, t=True)
    target = cmds.createNode(
        "transform",
        name=elbow.split("|")[-1].replace(":", "_") + "_tPoseForearmTemp",
    )
    cmds.xform(target, worldSpace=True, matrix=[
        x_axis[0], x_axis[1], x_axis[2], 0.0,
        y_axis[0], y_axis[1], y_axis[2], 0.0,
        z_axis[0], z_axis[1], z_axis[2], 0.0,
        elbow_position[0], elbow_position[1], elbow_position[2], 1.0,
    ])
    constraint = cmds.orientConstraint(
        target, elbow, maintainOffset=False
    )[0]
    cmds.delete(constraint, target)

    elbow_position = get_world_position(elbow)
    hand_position = get_world_position(hand)
    matrix = cmds.xform(elbow, q=True, ws=True, matrix=True)
    return {
        "world_x": tuple(matrix[0:3]),
        "world_y": tuple(matrix[4:7]),
        "world_z": tuple(matrix[8:11]),
        "height_error": abs(hand_position.y - elbow_position.y),
        "forward_offset": hand_position.z - elbow_position.z,
    }


def _toe_tip_from_chain(toe, side):
    if not toe or not cmds.objExists(toe):
        return None
    short = toe.split("|")[-1]
    namespace = short.rsplit(":", 1)[0] if ":" in short else ""
    prefix = namespace + ":" if namespace else ""
    expected = cmds.ls(prefix + side + "_toeTip", type="joint", long=True) or []
    if len(expected) == 1:
        return expected[0]
    descendants = cmds.listRelatives(toe, ad=True, type="joint", fullPath=True) or []
    if not descendants:
        return None
    def score(joint):
        name = joint.split("|")[-1].split(":")[-1].lower()
        return ("toetip" in name, "tip" in name or "end" in name, -len(name))
    return max(descendants, key=score)


def _rotation_value(joint, axis):
    return float(cmds.getAttr("{}.rotate{}".format(joint, axis)))


def _set_rotation_value(joint, axis, value):
    """Set one rotate channel without touching translate or jointOrient."""
    attribute = "{}.rotate{}".format(joint, axis)
    if cmds.getAttr(attribute, lock=True):
        return False
    cmds.setAttr(attribute, float(value))
    return True


def _nearest_right_angle(value):
    """Return the closest 90-degree Euler value with a clean zero."""
    snapped = round(float(value) / 90.0) * 90.0
    return 0.0 if abs(snapped) < 1.0e-8 else snapped


def _sample_rotation_axis(
        joint, axis, objective, sample_range=90.0,
        absolute_min=None, absolute_max=None):
    """Minimize an objective on one rotate channel with bounded evaluations.

    The previous four dense sweeps evaluated Maya's dependency graph about 330
    times per axis. A coarse global pass followed by golden-section refinement
    preserves the same deterministic search interval with roughly 40 samples.
    """
    original = _rotation_value(joint, axis)
    if not _set_rotation_value(joint, axis, original):
        return original

    radius = max(0.0, float(sample_range))
    lower = original - radius
    upper = original + radius
    if absolute_min is not None:
        lower = max(lower, float(absolute_min))
    if absolute_max is not None:
        upper = min(upper, float(absolute_max))
    if lower > upper:
        lower = upper = min(
            max(original, float(absolute_min if absolute_min is not None else original)),
            float(absolute_max if absolute_max is not None else original),
        )
    sample_count = 18
    step = (upper - lower) / float(sample_count) if sample_count else 0.0
    samples = []
    for index in range(sample_count + 1):
        candidate = lower + (index * step)
        _set_rotation_value(joint, axis, candidate)
        samples.append((float(objective()), candidate))
    original_error = next(
        (error for error, value in samples if abs(value - original) <= 1.0e-10),
        None,
    )
    if original_error is None:
        bounded_original = min(max(original, lower), upper)
        _set_rotation_value(joint, axis, bounded_original)
        samples.append((float(objective()), bounded_original))

    best_error, best_value = min(samples, key=lambda row: row[0])
    best_index = min(
        range(sample_count + 1),
        key=lambda index: abs((lower + index * step) - best_value),
    )
    left = lower + max(0, best_index - 1) * step
    right = lower + min(sample_count, best_index + 1) * step
    inverse_phi = (math.sqrt(5.0) - 1.0) * 0.5
    c = right - ((right - left) * inverse_phi)
    d = left + ((right - left) * inverse_phi)

    def evaluate(value):
        _set_rotation_value(joint, axis, value)
        return float(objective())

    c_error = evaluate(c)
    d_error = evaluate(d)
    for _iteration in range(22):
        if c_error <= d_error:
            right, d, d_error = d, c, c_error
            c = right - ((right - left) * inverse_phi)
            c_error = evaluate(c)
        else:
            left, c, c_error = c, d, d_error
            d = left + ((right - left) * inverse_phi)
            d_error = evaluate(d)
    for error, value in ((c_error, c), (d_error, d)):
        if error < best_error:
            best_error, best_value = error, value
    _set_rotation_value(joint, axis, best_value)
    return best_value

def _front_leg_line_error(thigh, knee, ankle):
    """Normalized front-view error for thigh, knee, and ankle collinearity."""
    thigh_position = get_world_position(thigh)
    knee_position = get_world_position(knee)
    ankle_position = get_world_position(ankle)
    upper_x = knee_position.x - thigh_position.x
    upper_y = knee_position.y - thigh_position.y
    lower_x = ankle_position.x - knee_position.x
    lower_y = ankle_position.y - knee_position.y
    upper_length = max(math.sqrt((upper_x * upper_x) + (upper_y * upper_y)), 1.0e-8)
    lower_length = max(math.sqrt((lower_x * lower_x) + (lower_y * lower_y)), 1.0e-8)
    cross = abs((upper_x * lower_y) - (upper_y * lower_x)) / (upper_length * lower_length)
    dot = ((upper_x * lower_x) + (upper_y * lower_y)) / (upper_length * lower_length)
    return cross + (10.0 if dot < 0.0 else 0.0)


def _front_vertical_segment_error(start_joint, end_joint):
    """World-X difference for a segment that must be vertical in front view."""
    return abs(get_world_position(end_joint).x - get_world_position(start_joint).x)


def _flat_segment_error(start_joint, end_joint):
    """World-height difference for a segment that should rest flat."""
    return abs(get_world_position(end_joint).y - get_world_position(start_joint).y)


def _flatten_segment_with_rotation(
        start_joint, end_joint, sample_range=120.0, hinge_axis="Z"):
    """Flatten a foot segment using only its authored hinge channel.

    Searching every Euler channel can find a numerically flat result by rolling
    the foot or twisting the toe sideways. Studio leg placement authors Z as
    the knee/ankle/toe pitch hinge, so preserve X/Y and solve only rotateZ.
    """
    if not all(node and cmds.objExists(node) for node in (start_joint, end_joint)):
        return None
    axis = str(hinge_axis).upper()
    if axis not in ("X", "Y", "Z"):
        raise ValueError("Unsupported foot hinge axis: {}".format(hinge_axis))
    _sample_rotation_axis(
        start_joint,
        axis,
        lambda: _flat_segment_error(start_joint, end_joint),
        sample_range=sample_range,
    )
    return axis


def _skin_mesh_for_joints(joints):
    """Return the largest skinned mesh influenced by the supplied joints."""
    skin_clusters = []
    for joint in joints:
        if joint and cmds.objExists(joint):
            skin_clusters.extend(
                cmds.listConnections(joint, type="skinCluster") or []
            )
    best = None
    for skin_cluster in dict.fromkeys(skin_clusters):
        for geometry in cmds.skinCluster(
            skin_cluster, query=True, geometry=True
        ) or []:
            mesh = geometry
            if cmds.nodeType(geometry) == "mesh":
                mesh = (
                    cmds.listRelatives(
                        geometry, parent=True, fullPath=True
                    ) or [geometry]
                )[0]
            vertex_count = int(cmds.polyEvaluate(mesh, vertex=True) or 0)
            if best is None or vertex_count > best[0]:
                best = (vertex_count, mesh)
    return best[1] if best else None


def _foot_mesh_contact_regions(mesh, ankle, tip, sample_count=12):
    """Find longitudinal landmarks and a mesh-relative lower-envelope grid."""
    selection = om.MSelectionList()
    selection.add(mesh)
    dag_path = selection.getDagPath(0)
    if dag_path.apiType() == om.MFn.kTransform:
        dag_path.extendToShape()
    points = om.MFnMesh(dag_path).getPoints(om.MSpace.kWorld)

    ankle_position = om.MVector(*cmds.xform(
        ankle, query=True, worldSpace=True, translation=True
    ))
    tip_position = om.MVector(*cmds.xform(
        tip, query=True, worldSpace=True, translation=True
    ))
    forward = om.MVector(
        tip_position.x - ankle_position.x,
        0.0,
        tip_position.z - ankle_position.z,
    )
    foot_length = forward.length()
    if foot_length <= 1.0e-8:
        return {}
    forward.normalize()
    lateral = om.MVector(-forward.z, 0.0, forward.x)
    width = max(2.0, foot_length * 0.28)

    def _collect_region(long_interval, side_interval=None):
        candidates = []
        for index, point in enumerate(points):
            offset = om.MVector(
                point.x - ankle_position.x,
                point.y - ankle_position.y,
                point.z - ankle_position.z,
            )
            longitudinal = offset * forward
            side_distance = offset * lateral
            if not long_interval[0] <= longitudinal <= long_interval[1]:
                continue
            if side_interval and not (
                    side_interval[0] <= side_distance <= side_interval[1]):
                continue
            if not side_interval and abs(side_distance) > width:
                continue
            if point.y > ankle_position.y + (foot_length * 0.35):
                continue
            candidates.append((float(point.y), index))
        indices = [
            index
            for _height, index in sorted(candidates)[:int(sample_count)]
        ]
        return [
            "{}.vtx[{}]".format(mesh, index)
            for index in indices
        ]

    regions = {}
    bands = {
        # Keep this behind the ankle. Including the forward midfoot lets a low
        # arch vertex masquerade as heel contact while the visible rear heel
        # remains above the floor.
        "heel": (-0.35 * foot_length, -0.05 * foot_length),
        "ball": (0.52 * foot_length, 0.78 * foot_length),
        "tip": (0.84 * foot_length, 1.18 * foot_length),
    }
    for label, interval in bands.items():
        components = _collect_region(interval)
        if len(components) < 3:
            return {}
        regions[label] = components

    support_count = 0
    for long_label, normalized_long in (
            ("heel", (-0.35, 0.02)),
            ("mid", (0.18, 0.48)),
            ("ball", (0.48, 0.78)),
            ("tip", (0.78, 1.12))):
        long_interval = (
            normalized_long[0] * foot_length,
            normalized_long[1] * foot_length,
        )
        for side_label, normalized_side in (
                ("a", (-1.0, -0.18)),
                ("center", (-0.18, 0.18)),
                ("b", (0.18, 1.0))):
            side_interval = (
                normalized_side[0] * width,
                normalized_side[1] * width,
            )
            components = _collect_region(long_interval, side_interval)
            if len(components) < 3:
                continue
            regions["support_{}_{}".format(long_label, side_label)] = components
            support_count += 1
    if support_count < 5:
        return {}
    return regions


def _mesh_contact_height(components):
    """Return a trimmed-mean height for a fixed low mesh contact patch."""
    positions = cmds.xform(
        components, query=True, worldSpace=True, translation=True
    ) or []
    heights = sorted(float(value) for value in positions[1::3])
    if not heights:
        return float("inf")
    trim = min(2, max(0, (len(heights) - 3) // 4))
    core = heights[trim:len(heights) - trim] if trim else heights
    return sum(core) / float(len(core))
def _mesh_contact_heights(regions):
    """Evaluate every fixed contact patch from one deformed mesh point read."""
    first_component = next(
        (component for values in regions.values() for component in values),
        "",
    )
    mesh = first_component.split(".vtx[", 1)[0]
    if not mesh:
        return {
            label: _mesh_contact_height(components)
            for label, components in regions.items()
        }
    selection = om.MSelectionList()
    selection.add(mesh)
    dag_path = selection.getDagPath(0)
    if dag_path.apiType() == om.MFn.kTransform:
        dag_path.extendToShape()
    points = om.MFnMesh(dag_path).getPoints(om.MSpace.kWorld)
    result = {}
    for label, components in regions.items():
        heights = []
        for component in components:
            match = re.search(r"\.vtx\[(\d+)\]$", component)
            if match:
                heights.append(float(points[int(match.group(1))].y))
        heights.sort()
        if not heights:
            result[label] = float("inf")
            continue
        trim = min(2, max(0, (len(heights) - 3) // 4))
        core = heights[trim:len(heights) - trim] if trim else heights
        result[label] = sum(core) / float(len(core))
    return result

def _align_foot_front_projection_with_rotation(
        ankle, toe, tip, ankle_y_limits=None):
    """Put the whole foot on one front-view line without twisting the toe."""
    # Toe is a single-axis hinge in T-pose: X/Y must remain zero and only Z may
    # level the ball-to-tip segment. Ankle Y rolls the complete foot chain into
    # the leg's front-view line, minimizing both downstream X errors together.
    _set_rotation_value(toe, "X", 0.0)
    _set_rotation_value(toe, "Y", 0.0)
    limits = ankle_y_limits or (None, None)
    _sample_rotation_axis(
        ankle,
        "Y",
        lambda: (
            _front_vertical_segment_error(ankle, toe)
            + _front_vertical_segment_error(ankle, tip)
        ),
        sample_range=30.0,
        absolute_min=limits[0],
        absolute_max=limits[1],
    )
    ankle_toe_error = _front_vertical_segment_error(ankle, toe)
    toe_tip_error = _front_vertical_segment_error(toe, tip)
    return {
        "axis": {"ankle": "Y"},
        "toe_rotation_axes": ("Z",),
        "ankle_toe_x_error": ankle_toe_error,
        "toe_tip_x_error": toe_tip_error,
        "ankle_tip_x_error": _front_vertical_segment_error(ankle, tip),
    }


def _foot_pose_metrics(regions, ankle, toe, tip):
    """Measure anatomical foot placement without relying on rotate values."""
    heights = _mesh_contact_heights(regions)
    ankle_position = get_world_position(ankle)
    toe_position = get_world_position(toe)
    tip_position = get_world_position(tip)
    foot_length = max(
        math.sqrt(
            ((tip_position.x - ankle_position.x) ** 2)
            + ((tip_position.z - ankle_position.z) ** 2)
        ),
        1.0e-8,
    )
    toe_tip_length = max(
        math.sqrt(
            ((tip_position.x - toe_position.x) ** 2)
            + ((tip_position.y - toe_position.y) ** 2)
            + ((tip_position.z - toe_position.z) ** 2)
        ),
        1.0e-8,
    )
    support_heights = sorted(
        height for label, height in heights.items()
        if label.startswith("support_")
    )
    support_contacts = support_heights[:min(5, len(support_heights))]
    longitudinal = [heights[label] for label in ("heel", "ball", "tip")]
    return {
        "heights": heights,
        "foot_length": foot_length,
        "contact_spread": max(longitudinal) - min(longitudinal),
        "support_spread": (
            max(support_contacts) - min(support_contacts)
            if support_contacts else float("inf")
        ),
        "toe_clearance": toe_position.y - heights["ball"],
        "tip_clearance": tip_position.y - heights["tip"],
        "tip_support_offset": tip_position.y - (
            0.5 * (heights["heel"] + heights["ball"])
        ),
        "toe_tip_drop_ratio": abs(toe_position.y - tip_position.y) / toe_tip_length,
        "front_error": max(
            _front_vertical_segment_error(ankle, toe),
            _front_vertical_segment_error(ankle, tip),
        ),
    }


def _foot_pose_is_grounded(metrics):
    """Return whether an existing anatomical pose is already a valid T-pose."""
    length = metrics["foot_length"]
    minimum_toe_clearance = length * 0.03
    maximum_toe_clearance = length * 0.125
    return (
        metrics["contact_spread"] <= max(0.05, length * 0.005)
        and metrics["support_spread"] <= max(0.10, length * 0.0075)
        and minimum_toe_clearance <= metrics["toe_clearance"] <= maximum_toe_clearance
        and abs(metrics["tip_clearance"]) <= max(0.10, length * 0.01)
        and abs(metrics["tip_support_offset"]) <= max(0.05, length * 0.003)
        and 0.08 <= metrics["toe_tip_drop_ratio"] <= 0.35
        and metrics["front_error"] <= max(0.05, length * 0.01)
    )


def _flatten_foot_mesh_with_rotation(ankle, toe, tip):
    """Align the front projection and level sole contacts using rotations only."""
    mesh = _skin_mesh_for_joints((ankle, toe, tip))
    if not mesh:
        return {"available": False, "reason": "no_skinned_mesh"}

    ankle_start = {
        axis: _rotation_value(ankle, axis) for axis in ("X", "Y", "Z")
    }
    toe_start_z = _rotation_value(toe, "Z")
    # X/Y are not valid toe hinges in the T-pose. Preserve the authored Z pose,
    # however: zeroing it made a correctly grounded toe tip fold below the mesh
    # and forced the ankle to compensate.
    _set_rotation_value(toe, "X", 0.0)
    _set_rotation_value(toe, "Y", 0.0)
    ankle_limits = {
        "X": (ankle_start["X"] - 25.0, ankle_start["X"] + 25.0),
        "Y": (ankle_start["Y"] - 30.0, ankle_start["Y"] + 30.0),
        "Z": (ankle_start["Z"] - 40.0, ankle_start["Z"] + 40.0),
    }
    toe_z_limits = (toe_start_z - 45.0, toe_start_z + 45.0)

    regions = _foot_mesh_contact_regions(mesh, ankle, tip)
    if not regions:
        return {
            "available": False,
            "reason": "no_contact_regions",
            "mesh": mesh,
        }
    initial_metrics = _foot_pose_metrics(regions, ankle, toe, tip)
    if _foot_pose_is_grounded(initial_metrics):
        return {
            "available": True,
            "mesh": mesh,
            "hinge_axes": {"ankle": ("X", "Z"), "toe": "Z"},
            "front_projection": {"skipped": True, "reason": "already_grounded"},
            "contact_heights": initial_metrics["heights"],
            "contact_spread": initial_metrics["contact_spread"],
            "support_spread": initial_metrics["support_spread"],
            "toe_clearance": initial_metrics["toe_clearance"],
            "tip_clearance": initial_metrics["tip_clearance"],
            "_contact_regions": regions,
        }

    front_projection = None
    # Front alignment and ground contact are coupled: ankle Y removes lateral
    # flare, ankle X levels the lower support envelope, and the Z hinges level
    # heel-to-toe. Alternate the small solves so no correction undoes another.
    for _outer_iteration in range(2):
        front_projection = _align_foot_front_projection_with_rotation(
            ankle, toe, tip, ankle_y_limits=ankle_limits["Y"]
        )
        regions = _foot_mesh_contact_regions(mesh, ankle, tip)
        if not regions:
            return {
                "available": False,
                "reason": "no_contact_regions",
                "mesh": mesh,
            }

        def _heel_ball_objective():
            metrics = _foot_pose_metrics(regions, ankle, toe, tip)
            heights = metrics["heights"]
            length = metrics["foot_length"]
            minimum_clearance = length * 0.03
            maximum_clearance = length * 0.125
            clearance_penalty = max(
                minimum_clearance - metrics["toe_clearance"],
                metrics["toe_clearance"] - maximum_clearance,
                0.0,
            )
            return abs(heights["heel"] - heights["ball"]) + (2.0 * clearance_penalty)

        def _toe_tip_objective():
            metrics = _foot_pose_metrics(regions, ankle, toe, tip)
            heights = metrics["heights"]
            length = metrics["foot_length"]
            support_height = 0.5 * (heights["heel"] + heights["ball"])
            # The terminal pivot is a ground-contact point. Aim the pivot at
            # the same support plane as heel and ball instead of preserving a
            # scale-relative clearance that leaves it visibly above the floor.
            tip_position = get_world_position(tip)
            slope_penalty = max(
                0.08 - metrics["toe_tip_drop_ratio"],
                metrics["toe_tip_drop_ratio"] - 0.35,
                0.0,
            ) * length
            return (
                abs(heights["tip"] - support_height)
                + (2.0 * abs(tip_position.y - support_height))
                + slope_penalty
            )

        def _support_plane_objective():
            values = _mesh_contact_heights(regions)
            heights = sorted(
                height for label, height in values.items()
                if label.startswith("support_")
            )
            contacts = heights[:min(5, len(heights))]
            return max(contacts) - min(contacts)

        # Recover the distal hinge before asking the ankle to level the sole.
        # Otherwise an initially bad toe can make the ankle compensate for the
        # toe error, producing a different minimum on mirrored feet.
        _sample_rotation_axis(
            toe,
            "Z",
            _toe_tip_objective,
            sample_range=40.0,
            absolute_min=toe_z_limits[0],
            absolute_max=toe_z_limits[1],
        )

        for _ground_iteration in range(3):
            _sample_rotation_axis(
                ankle,
                "X",
                _support_plane_objective,
                sample_range=25.0,
                absolute_min=ankle_limits["X"][0],
                absolute_max=ankle_limits["X"][1],
            )
            _sample_rotation_axis(
                ankle,
                "Z",
                _heel_ball_objective,
                sample_range=40.0,
                absolute_min=ankle_limits["Z"][0],
                absolute_max=ankle_limits["Z"][1],
            )
            _sample_rotation_axis(
                toe,
                "Z",
                _toe_tip_objective,
                sample_range=40.0,
                absolute_min=toe_z_limits[0],
                absolute_max=toe_z_limits[1],
            )

    for axis in ("X", "Y", "Z"):
        _set_rotation_value(tip, axis, 0.0)
    final_metrics = _foot_pose_metrics(regions, ankle, toe, tip)
    return {
        "available": True,
        "mesh": mesh,
        "hinge_axes": {"ankle": ("X", "Z"), "toe": "Z"},
        "front_projection": front_projection,
        "contact_heights": final_metrics["heights"],
        "contact_spread": final_metrics["contact_spread"],
        "support_spread": final_metrics["support_spread"],
        "toe_clearance": final_metrics["toe_clearance"],
        "tip_clearance": final_metrics["tip_clearance"],
        "tip_support_offset": final_metrics["tip_support_offset"],
        "_contact_regions": regions,
    }


def _mirror_right_foot_pose_from_left(leg_chains, side_reports):
    """Use the solved left foot pose on a geometrically symmetric right foot.

    Studio template joints use mirrored joint orientation, so equal ankle and
    toe rotate channels produce reflected world-space endpoints. Independently
    optimizing both sides can settle into slightly different local minima; use
    the left result when the existing endpoints already prove the mesh/rig is
    symmetric, and retain the independent solve for materially asymmetric rigs.
    """
    left = leg_chains.get("l")
    right = leg_chains.get("r")
    if not left or not right or not all(left[2:5]) or not all(right[2:5]):
        return {"applied": False, "reason": "incomplete_foot_chains"}
    if not all(cmds.objExists(joint) for joint in left[2:5] + right[2:5]):
        return {"applied": False, "reason": "missing_foot_joints"}

    left_ankle, left_toe, left_tip = left[2:5]
    right_ankle, right_toe, right_tip = right[2:5]
    left_positions = {
        "ankle": get_world_position(left_ankle),
        "toe": get_world_position(left_toe),
        "tip": get_world_position(left_tip),
    }
    right_positions = {
        "ankle": get_world_position(right_ankle),
        "toe": get_world_position(right_toe),
        "tip": get_world_position(right_tip),
    }
    center_x = 0.5 * (
        left_positions["ankle"].x + right_positions["ankle"].x
    )

    def _mirrored(position):
        return om.MVector(
            (2.0 * center_x) - position.x, position.y, position.z
        )

    targets = {label: _mirrored(left_positions[label]) for label in ("toe", "tip")}
    deviations = [
        (right_positions[label] - targets[label]).length()
        for label in ("toe", "tip")
    ]
    foot_length = max(
        (left_positions["tip"] - left_positions["ankle"]).length(),
        1.0e-8,
    )
    if max(deviations) > foot_length * 0.05:
        return {
            "applied": False,
            "reason": "material_asymmetry",
            "maximum_deviation": max(deviations),
            "tolerance": foot_length * 0.05,
        }

    original = {
        right_ankle: tuple(cmds.getAttr(right_ankle + ".rotate")[0]),
        right_toe: tuple(cmds.getAttr(right_toe + ".rotate")[0]),
        right_tip: tuple(cmds.getAttr(right_tip + ".rotate")[0]),
    }
    cmds.setAttr(right_ankle + ".rotate", *cmds.getAttr(left_ankle + ".rotate")[0])
    cmds.setAttr(right_toe + ".rotate", *cmds.getAttr(left_toe + ".rotate")[0])
    cmds.setAttr(right_tip + ".rotate", *cmds.getAttr(left_tip + ".rotate")[0])
    mirrored_error = max(
        (get_world_position(joint) - targets[label]).length()
        for label, joint in (("toe", right_toe), ("tip", right_tip))
    )
    if mirrored_error > max(foot_length * 0.005, 1.0e-4):
        for joint, rotation in original.items():
            cmds.setAttr(joint + ".rotate", *rotation)
        return {
            "applied": False,
            "reason": "incompatible_joint_orientation",
            "mirrored_error": mirrored_error,
        }

    right_report = side_reports.get("r", {}).get("foot_mesh_grounding", {})
    regions = right_report.get("_contact_regions")
    if regions:
        metrics = _foot_pose_metrics(regions, right_ankle, right_toe, right_tip)
        right_report.update({
            "contact_heights": metrics["heights"],
            "contact_spread": metrics["contact_spread"],
            "support_spread": metrics["support_spread"],
            "toe_clearance": metrics["toe_clearance"],
            "tip_clearance": metrics["tip_clearance"],
            "tip_support_offset": metrics["tip_support_offset"],
        })
    return {
        "applied": True,
        "center_x": center_x,
        "maximum_deviation_before": max(deviations),
        "mirrored_error": mirrored_error,
    }

def _ground_flattened_feet_with_pelvis(pelvis, side_reports):
    """Center the solved heel/ball/tip contacts tightly around world Y=0."""
    available = [
        report["foot_mesh_grounding"]
        for report in side_reports.values()
        if report.get("foot_mesh_grounding", {}).get("available")
    ]
    heights = [
        height
        for report in available
        for height in report.get("contact_heights", {}).values()
    ]
    primary_heights = sorted(
        float(report.get("contact_heights", {}).get(label))
        for report in available
        for label in ("heel", "ball", "tip")
        if report.get("contact_heights", {}).get(label) is not None
    )
    if primary_heights:
        middle = len(primary_heights) // 2
        ground_reference = (
            primary_heights[middle]
            if len(primary_heights) % 2
            else 0.5 * (
                primary_heights[middle - 1] + primary_heights[middle]
            )
        )
    else:
        ground_reference = min(heights) if heights else None
    grounding = {
        "applied": False,
        "world_y_shift": 0.0,
        "ground_height_before": min(heights) if heights else None,
        "ground_reference_before": ground_reference,
    }
    if pelvis and cmds.objExists(pelvis) and ground_reference is not None:
        position = cmds.xform(
            pelvis, query=True, worldSpace=True, translation=True
        )
        shift = -ground_reference
        cmds.xform(
            pelvis,
            worldSpace=True,
            translation=(position[0], position[1] + shift, position[2]),
        )
        grounding.update({
            "applied": True,
            "world_y_shift": shift,
            "pelvis": pelvis,
        })

    for report in available:
        regions = report.pop("_contact_regions", {})
        if regions:
            contact_heights = _mesh_contact_heights(regions)

            report["contact_heights"] = contact_heights
            report["contact_spread"] = (
                max(contact_heights.values()) - min(contact_heights.values())
            )
    final_heights = [
        height
        for report in available
        for height in report.get("contact_heights", {}).values()
    ]
    grounding["ground_height_after"] = (
        min(final_heights) if final_heights else None
    )
    grounding["highest_contact_after"] = (
        max(final_heights) if final_heights else None
    )
    return grounding


def _prepare_legs_for_t_pose(leg_chains, pelvis=None):
    """Flatten each leg in front view using only the thigh rotate channel.

    Rotating the complete fitted chain at the thigh preserves its authored
    segment lengths, depth prebend, feet, translates, and jointOrient values.
    The studio thigh uses local Z for this frontal abduction/adduction, so the
    final value should normally resolve to an exact signed right angle.
    """
    valid = {}
    for side, chain in leg_chains.items():
        thigh, knee, ankle, toe, tip = chain
        if not all(joint and cmds.objExists(joint) for joint in (thigh, knee, ankle)):
            continue
        if not tip:
            tip = _toe_tip_from_chain(toe, side)
        valid[side] = (thigh, knee, ankle, toe, tip)
    if not valid:
        return {
            "translation_preserved": True,
            "rotated_joints": [],
            "sides": {},
        }

    result = {}
    rotated_joints = []
    for side, chain in valid.items():
        thigh, knee, ankle, toe, tip = chain
        before_rotate = tuple(cmds.getAttr(thigh + ".rotate")[0])
        before_upper_error = _front_vertical_segment_error(thigh, knee)
        before_lower_error = _front_vertical_segment_error(knee, ankle)
        solved_z = _sample_rotation_axis(
            thigh,
            "Z",
            lambda: _front_vertical_segment_error(thigh, knee),
            sample_range=30.0,
        )
        snapped_z = _nearest_right_angle(solved_z)
        _set_rotation_value(thigh, "Z", snapped_z)
        snapped_error = _front_vertical_segment_error(thigh, knee)
        if snapped_error > 1.0e-4:
            _set_rotation_value(thigh, "Z", solved_z)
        after_rotate = tuple(cmds.getAttr(thigh + ".rotate")[0])
        if any(
                abs(after_rotate[index] - before_rotate[index]) > 1.0e-8
                for index in range(3)):
            rotated_joints.append(thigh)
        result[side] = {
            "thigh_rotate_before": before_rotate,
            "thigh_rotate": after_rotate,
            "knee_rotate": tuple(cmds.getAttr(knee + ".rotate")[0]),
            "flattened": True,
            "upper_front_vertical_error_before": before_upper_error,
            "lower_front_vertical_error_before": before_lower_error,
            "upper_front_vertical_error": _front_vertical_segment_error(thigh, knee),
            "lower_front_vertical_error": _front_vertical_segment_error(knee, ankle),
            "front_line_error": _front_leg_line_error(thigh, knee, ankle),
        }

    return {
        "translation_preserved": True,
        "rotated_joints": rotated_joints,
        "sides": result,
        "foot_pose_mirroring": {"skipped": True, "reason": "rigid_chain_rotation"},
        "pelvis_grounding": {"skipped": True, "reason": "rigid_chain_rotation"},
    }


_T_POSE_SNAPSHOT_ATTR = "tcTposeWorldMatrices"
_T_POSE_SNAPSHOT_VERSION = 11
_T_POSE_MATRIX_TOLERANCE = 1.0e-5


def _t_pose_snapshot_joints(joint_map, fallback_joints=()):
    """Return the unique mapped joints whose world pose defines the T-pose."""
    candidates = list(fallback_joints or ())
    if isinstance(joint_map, dict):
        for value in joint_map.values():
            if isinstance(value, dict):
                candidates.append(value.get("joint"))
                candidates.extend(value.get("joints") or [])
            elif isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, (list, tuple)) and value:
                # Body-map tuples use (joint, HIK index).  List-valued face
                # entries are harmless here because only joint nodes survive.
                candidates.extend(value if len(value) != 2 or not isinstance(value[1], int) else value[:1])

    result = []
    seen = set()
    for joint in candidates:
        if not joint or not cmds.objExists(joint):
            continue
        try:
            if cmds.nodeType(joint) != "joint":
                continue
        except Exception:
            continue
        resolved = (cmds.ls(joint, long=True) or [joint])[0]
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


def _capture_t_pose_world_matrices(joints):
    """Capture stable world matrices for idempotence detection."""
    snapshot = {}
    for joint in joints:
        if cmds.objExists(joint):
            snapshot[joint] = [float(value) for value in cmds.xform(joint, q=True, ws=True, matrix=True)]
    return snapshot


def _capture_t_pose_authored_channels(joints):
    """Capture placement-owned channels that T-pose is forbidden to rewrite."""
    result = {}
    for joint in joints:
        if not joint or not cmds.objExists(joint):
            continue
        result[joint] = {
            attribute: tuple(cmds.getAttr(
                "{}.{}".format(joint, attribute)
            )[0])
            for attribute in ("translate", "jointOrient", "rotateAxis")
        }
    return result


def _validate_t_pose_authored_channels(before, pelvis=None):
    """Reject any T-pose edit to placement-owned orientation or offsets."""
    pelvis_path = None
    if pelvis and cmds.objExists(pelvis):
        pelvis_path = (cmds.ls(pelvis, long=True) or [pelvis])[0]
    changed = []
    for joint, attributes in before.items():
        if not cmds.objExists(joint):
            changed.append(joint + ".missing")
            continue
        for attribute, expected in attributes.items():
            if attribute == "translate" and joint == pelvis_path:
                # Pelvis Y is the one intentional deformation-skeleton
                # translation: it grounds the solved feet at world zero.
                continue
            actual = tuple(cmds.getAttr(
                "{}.{}".format(joint, attribute)
            )[0])
            if any(abs(actual[index] - expected[index]) > 1.0e-8 for index in range(3)):
                changed.append("{}.{}".format(joint, attribute))
    if changed:
        raise RuntimeError(
            "T-pose changed placement-owned channels: {}".format(
                ", ".join(changed)
            )
        )
    return {
        "joint_orient_preserved": True,
        "rotate_axis_preserved": True,
        "non_pelvis_translate_preserved": True,
        "joint_count": len(before),
    }


def _read_t_pose_snapshot(holder):
    if not holder or not cmds.objExists(holder):
        return None
    attr = "{}.{}".format(holder, _T_POSE_SNAPSHOT_ATTR)
    if not cmds.objExists(attr):
        return None
    try:
        value = cmds.getAttr(attr)
        decoded = json.loads(value) if value else None
        if not isinstance(decoded, dict):
            return None
        if decoded.get("version") != _T_POSE_SNAPSHOT_VERSION:
            return None
        matrices = decoded.get("matrices")
        return matrices if isinstance(matrices, dict) else None
    except Exception:
        return None


def _matches_t_pose_snapshot(holder, joints):
    stored = _read_t_pose_snapshot(holder)
    if not stored or set(stored) != set(joints):
        return False
    current = _capture_t_pose_world_matrices(joints)
    for joint in joints:
        previous = stored.get(joint)
        live = current.get(joint)
        if not previous or not live or len(previous) != len(live):
            return False
        if any(abs(float(a) - float(b)) > _T_POSE_MATRIX_TOLERANCE for a, b in zip(previous, live)):
            return False
    return True


def _store_t_pose_snapshot(holder, joints):
    if not holder or not cmds.objExists(holder):
        return False
    if not cmds.attributeQuery(_T_POSE_SNAPSHOT_ATTR, node=holder, exists=True):
        cmds.addAttr(holder, longName=_T_POSE_SNAPSHOT_ATTR, dataType="string", hidden=True)
    cmds.setAttr(
        "{}.{}".format(holder, _T_POSE_SNAPSHOT_ATTR),
        json.dumps(
            {
                "version": _T_POSE_SNAPSHOT_VERSION,
                "matrices": _capture_t_pose_world_matrices(joints),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        type="string",
    )
    return True


def _t_pose_rotation_blockers(joint_channels):
    """Return locked or driven rotate plugs that T-pose cannot author safely."""
    blockers = []
    seen = set()
    for joint, axes in joint_channels:
        if not joint or not cmds.objExists(joint):
            continue
        resolved = (cmds.ls(joint, long=True) or [joint])[0]
        for axis in axes:
            plug = "{}.rotate{}".format(resolved, str(axis).upper())
            if plug in seen:
                continue
            seen.add(plug)
            source = cmds.connectionInfo(
                plug, sourceFromDestination=True
            ) or ""
            if source:
                blockers.append({
                    "plug": plug,
                    "reason": "connected",
                    "source": source,
                })
            elif cmds.getAttr(plug, lock=True):
                blockers.append({
                    "plug": plug,
                    "reason": "locked",
                    "source": "",
                })
    return blockers


def _require_editable_t_pose_channels(joint_channels):
    """Fail before posing when a built rig already owns required channels."""
    blockers = _t_pose_rotation_blockers(joint_channels)
    if not blockers:
        return
    details = []
    for row in blockers:
        if row["source"]:
            details.append("{} <- {}".format(row["plug"], row["source"]))
        else:
            details.append("{} ({})".format(row["plug"], row["reason"]))
    raise RuntimeError(
        "Set T-Pose requires undriven, unlocked rotation channels. "
        "This skeleton already has rig connections, so T-pose must be run "
        "before building the rig. Remove or undo the generated rig modules "
        "and try again. The existing connections were left untouched.\n\n"
        "Blocked channels:\n  - {}".format("\n  - ".join(details))
    )


def validate_t_pose_channels(joint_map):
    """Validate mapped channels before the UI opens its pose undo transaction."""
    if not isinstance(joint_map, dict):
        return True

    def _mapped_joint(slot):
        value = joint_map.get(slot)
        if isinstance(value, dict):
            return value.get("joint")
        if isinstance(value, (list, tuple)) and value:
            return value[0]
        return value if isinstance(value, str) else None

    channel_specs = [
        ("LeftShoulder", "XYZ"),
        ("RightShoulder", "XYZ"),
        ("LeftArm", "XYZ"),
        ("RightArm", "XYZ"),
        ("LeftForeArm", "XYZ"),
        ("RightForeArm", "XYZ"),
        ("LeftHand", "XYZ"),
        ("RightHand", "XYZ"),
        ("LeftUpLeg", "Z"),
        ("RightUpLeg", "Z"),
    ]
    _require_editable_t_pose_channels([
        (_mapped_joint(slot), axes) for slot, axes in channel_specs
    ])
    return True


@undoable("Set T-Pose")
@cleanup_temp_bones
def set_t_pose(l_upperarm=None, r_upperarm=None, l_clav=None, r_clav=None, l_elbow=None, r_elbow=None, l_hand=None, r_hand=None, joint_map=None, pelvis=None):
    """
    T-pose the arms and legs before snapping reverse-foot helpers.

    Only arm and thigh rotate channels are changed on the deformation skeleton.
    Authored translate and jointOrient values remain untouched. Arms extend
    along world X while each fitted leg becomes vertical in front view without
    removing its side-view knee prebend.
    """
    if not joint_map:
        try:
            top_joints = joints_util.find_skinned_or_top_joints(namespace='')
            if top_joints:
                joint_map = guess_joint_map_from_root(top_joints[0])
        except Exception:
            pass

    leg_chains = {
        "l": [None, None, None, None, None],
        "r": [None, None, None, None, None],
    }

    if joint_map and isinstance(joint_map, dict):
        def _extract(*slots):
            for slot in slots:
                val = joint_map.get(slot)
                if val:
                    if isinstance(val, (list, tuple)) and val:
                        return val[0]
                    elif isinstance(val, dict):
                        j = val.get("joint")
                        if j:
                            return j
                    elif isinstance(val, str):
                        return val
            return None

        pelvis = pelvis or _extract("Hips", "pelvis")
        l_upperarm = l_upperarm or _extract("LeftArm", "LeftArmJoint", "l_upperarm", "arm_l")
        r_upperarm = r_upperarm or _extract("RightArm", "RightArmJoint", "r_upperarm", "arm_r")
        l_clav = l_clav or _extract("LeftShoulder", "LeftClavicle", "l_clavicle", "clavicle_l")
        r_clav = r_clav or _extract("RightShoulder", "RightClavicle", "r_clavicle", "clavicle_r")
        l_elbow = l_elbow or _extract("LeftForeArm", "LeftElbow", "l_lowerarm", "forearm_l")
        r_elbow = r_elbow or _extract("RightForeArm", "RightElbow", "r_lowerarm", "forearm_r")
        l_hand = l_hand or _extract("LeftHand", "LeftWrist", "l_hand", "hand_l")
        r_hand = r_hand or _extract("RightHand", "RightWrist", "r_hand", "hand_r")
        leg_chains["l"] = [
            _extract("LeftUpLeg", "l_thigh"),
            _extract("LeftLeg", "l_knee"),
            _extract("LeftFoot", "l_ankle"),
            _extract("LeftToeBase", "l_toe"),
            _extract("LeftToeTip", "l_toeTip"),
        ]
        leg_chains["r"] = [
            _extract("RightUpLeg", "r_thigh"),
            _extract("RightLeg", "r_knee"),
            _extract("RightFoot", "r_ankle"),
            _extract("RightToeBase", "r_toe"),
            _extract("RightToeTip", "r_toeTip"),
        ]

    pose_joints = _t_pose_snapshot_joints(
        joint_map,
        fallback_joints=(
            pelvis, l_clav, r_clav, l_upperarm, r_upperarm,
            l_elbow, r_elbow, l_hand, r_hand,
        ) + tuple(leg_chains["l"]) + tuple(leg_chains["r"]),
    )
    snapshot_holder = pelvis if pelvis and cmds.objExists(pelvis) else (pose_joints[0] if pose_joints else None)
    if _matches_t_pose_snapshot(snapshot_holder, pose_joints):
        print("[setup_hik.set_t_pose] Skeleton already matches the stored T-pose; no changes made.")
        return {
            "skipped": True,
            "reason": "already_in_t_pose",
            "legs": {
                "translation_preserved": True,
                "rotated_joints": [],
                "sides": {},
                "pelvis_grounding": {"skipped": True},
            },
            "preferred_bends": {},
            "authored_channels": {"skipped": True},
            "rfl_snap": {"stage": "already_in_t_pose", "skeleton_count": 0, "reports": []},
        }

    # Temporary orient constraints solve the arm channels against each joint's
    # real parent/jointOrient. Maya raises the opaque "Object is already
    # connected" error if a generated rig module already drives one of those
    # plugs. Detect that state before changing any joint so the user gets the
    # exact blockers and the scene does not need a mid-operation rollback.
    arm_channels = [
        (joint, "XYZ")
        for joint in (
            l_clav, r_clav, l_upperarm, r_upperarm,
            l_elbow, r_elbow, l_hand, r_hand,
        )
    ]
    leg_channels = [
        (chain[0], "Z") for chain in leg_chains.values() if chain
    ]
    _require_editable_t_pose_channels(arm_channels + leg_channels)

    authored_channel_snapshot = _capture_t_pose_authored_channels(pose_joints)

    print("[setup_hik.set_t_pose] Executing T-pose alignment:")
    print(f"  Left Arm: clav={l_clav}, upperarm={l_upperarm}, elbow={l_elbow}, hand={l_hand}")
    print(f"  Right Arm: clav={r_clav}, upperarm={r_upperarm}, elbow={r_elbow}, hand={r_hand}")

    if l_clav and l_upperarm:
        align_clavicle_to_upperarm_height(l_clav, l_upperarm)
    if r_clav and r_upperarm:
        align_clavicle_to_upperarm_height(r_clav, r_upperarm)

    arm_axis_reports = {}
    if l_upperarm and cmds.objExists(l_upperarm):
        arm_axis_reports["l"] = aim_joint_x_axis_to_world_x(
            l_upperarm, side="l"
        )
    if r_upperarm and cmds.objExists(r_upperarm):
        arm_axis_reports["r"] = aim_joint_x_axis_to_world_x(
            r_upperarm, side="r"
        )

    # An RP IK chain must not be authored perfectly straight. Resolve the
    # actual post-placement hinge closest to world up so the small prebend goes
    # into depth instead of dropping the wrist when jointOrient changes.
    elbow_prebend_reports = {}
    for label, joint in (("l_elbow", l_elbow), ("r_elbow", r_elbow)):
        if not joint or not cmds.objExists(joint):
            if joint:
                print(f"{label} not found: {joint}")
            continue
        hand = l_hand if label.startswith("l_") else r_hand
        elbow_prebend_reports[label[0]] = _set_oriented_elbow_prebend(
            joint, hand, degrees=3.0
        )

    for label, joint in (("l_hand", l_hand), ("r_hand", r_hand)):
        if joint and cmds.objExists(joint):
            for axis in ["X", "Y", "Z"]:
                attr = f"{joint}.rotate{axis}"
                try:
                    cmds.setAttr(attr, 0)
                except Exception as exc:
                    print(f"Could not zero rotation for {attr}: {exc}")
        elif joint:
            print(f"{label} not found: {joint}")

    leg_report = _prepare_legs_for_t_pose(leg_chains, pelvis=pelvis)
    rfl_report = {
        "stage": "post_t_pose",
        "skeleton_count": 0,
        "reports": [],
    }
    try:
        # Preferred angles belong to joint placement, after every mapped joint
        # has received its final position and orientation. T-pose only rotates
        # the fitted skeleton and must not rewrite that placement metadata.
        from maya_tools.Rigging import joint_placer
        if leg_report.get("sides"):
            rfl_report = joint_placer.snap_all_reverse_foot_helpers_after_t_pose()
    except Exception as exc:
        cmds.warning("T-pose completed, but post-pose rig metadata could not be refreshed: " + str(exc))
        rfl_report["error"] = str(exc)
    authored_channel_report = _validate_t_pose_authored_channels(
        authored_channel_snapshot,
        pelvis=pelvis,
    )
    _store_t_pose_snapshot(snapshot_holder, pose_joints)
    return {
        "skipped": False,
        "arm_axis_reports": arm_axis_reports,
        "elbow_prebend_reports": elbow_prebend_reports,
        "legs": leg_report,
        "preferred_bends": {},
        "authored_channels": authored_channel_report,
        "rfl_snap": rfl_report,
    }


t_pose_character = set_t_pose


def _joint_map_entry(value):
    """Return the joint name and HIK index from either supported map format."""
    if isinstance(value, dict):
        return value.get("joint", ""), value.get("index")
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return value[0], value[1]
    raise ValueError("HIK mapping values must contain a joint name and index")


def _is_joint_descendant(joint, ancestor):
    """Return True when *joint* is below *ancestor* in the Maya joint hierarchy."""
    if not joint or not ancestor or joint == ancestor:
        return False
    descendants = cmds.listRelatives(ancestor, ad=True, type="joint", fullPath=True) or []
    joint_paths = cmds.ls(joint, long=True) or [joint]
    return any(path in descendants for path in joint_paths)


def _validate_hik_mapping(joint_map):
    """Validate mapped nodes and complete arm chains before modifying the scene."""
    parsed = {}
    missing = []
    for slot, value in joint_map.items():
        joint, index = _joint_map_entry(value)
        if not joint or not cmds.objExists(joint):
            missing.append("{} -> {}".format(slot, joint or "<empty>"))
        parsed[slot] = (joint, index)
    if missing:
        raise RuntimeError("HIK mapping contains missing joints: {}".format(", ".join(missing)))

    required_slots = (
        "Hips", "Spine", "Head",
        "LeftUpLeg", "LeftLeg", "LeftFoot",
        "RightUpLeg", "RightLeg", "RightFoot",
        "LeftArm", "LeftForeArm", "LeftHand",
        "RightArm", "RightForeArm", "RightHand",
    )
    missing_slots = [slot for slot in required_slots if slot not in parsed]
    if missing_slots:
        raise RuntimeError(
            "HIK mapping is missing required body slots: {}".format(", ".join(missing_slots))
        )

    chain_slots = ("Shoulder", "Arm", "ForeArm", "Hand")
    for side in ("Left", "Right"):
        for parent_suffix, child_suffix in zip(chain_slots, chain_slots[1:]):
            parent_slot = side + parent_suffix
            child_slot = side + child_suffix
            if parent_slot in parsed and child_slot in parsed:
                parent = parsed[parent_slot][0]
                child = parsed[child_slot][0]
                if not _is_joint_descendant(child, parent):
                    raise RuntimeError(
                        "Invalid {} arm hierarchy: '{}' is not below '{}'. "
                        "Check the auto-mapped joints before characterization.".format(
                            side.lower(), child, parent
                        )
                    )
    return parsed


def _hik_definition_ui_exists():
    """The definition update MEL is unsafe unless its contextual tab was built."""
    for query in (cmds.tabLayout, cmds.layout, cmds.control):
        try:
            if query("hikContextualTabs", exists=True):
                return True
        except Exception:
            continue
    return False


def setup_hik_character(character_name, joint_map, fbx_export_path, namespace):
    """
    Setup a HIK character definition and export to FBX for MotionBuilder.

    :param character_name: Name of the HIK character to create.
    :param joint_map: Mapping of HIK slots to joint names.
    :param fbx_export_path: Full path to export the FBX file.
    :param namespace: namespace to apply on export
    :return:
    """

    parsed_joint_map = _validate_hik_mapping(joint_map)
    # Resolve output permissions before deleting the rig or changing its pose.
    prepare_file_for_write(fbx_export_path)

    mel.eval("DisableAll")
    for grp_name in ["DNT", "do_not_touch", "rig"]:
        if cmds.objExists(grp_name):
            try:
                cmds.delete(grp_name)
                print(f"[INFO] Deleted group: {grp_name}")
            except Exception as e:
                print(f"[WARNING] Could not delete group '{grp_name}': {e}")
    mel.eval("EnableAll")

    arm_slots = (
        "LeftArm", "RightArm", "LeftShoulder", "RightShoulder",
        "LeftForeArm", "RightForeArm", "LeftHand", "RightHand",
    )
    if all(slot in parsed_joint_map for slot in arm_slots):
        t_pose_character(
            parsed_joint_map["LeftArm"][0], parsed_joint_map["RightArm"][0],
            parsed_joint_map["LeftShoulder"][0], parsed_joint_map["RightShoulder"][0],
            parsed_joint_map["LeftForeArm"][0], parsed_joint_map["RightForeArm"][0],
            parsed_joint_map["LeftHand"][0], parsed_joint_map["RightHand"][0],
        )

    # Step 1: Create HumanIK character
    MAYA_LOCATION = os.environ['MAYA_LOCATION']
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikGlobalUtils.mel"')
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikCharacterControlsUI.mel"')
    mel.eval('source "' + MAYA_LOCATION + '/scripts/others/hikDefinitionOperations.mel"')

    if not cmds.objExists(character_name):
        mel.eval(f'hikCreateCharacter "{character_name}"')
    else:
        if not cmds.control("hikCharacterControls", exists=True):
            mel.eval('HIKCharacterControlsTool;')

        mel.eval('hikUpdateCharacterList();')

    for hik_slot, (joint_name, index) in parsed_joint_map.items():

        try:
            mel.eval(f'setCharacterObject "{joint_name}" "{character_name}" "{index}" 0;')

        except Exception as e:
            print(f"Failed to map {hik_slot} -> {joint_name}: {e}")
    # hikToggleLockDefinition always queries UI widgets such as
    # hikContextualTabs. Characterization also runs from command ports and
    # hidden tools, so use Autodesk's lower-level lock operation.
    escaped_character = character_name.replace('"', '\\"')
    # The validation flag in hikCharacterLock consults a Qt characterization
    # widget, even when no HIK UI exists. Required slots and hierarchy were
    # validated above, so capture the stance explicitly and bypass that widget.
    mel.eval('hikReadStancePoseTRSOffsets("{}");'.format(escaped_character))
    mel.eval('hikCharacterLock "{}" 1 0;'.format(escaped_character))
    if not mel.eval('hikIsDefinitionLocked("{}");'.format(escaped_character)):
        raise RuntimeError("HumanIK could not lock character '{}'".format(character_name))
    if _hik_definition_ui_exists():
        try:
            mel.eval('hikUpdateDefinitionUI;')
        except RuntimeError as exc:
            cmds.warning("HumanIK character was created, but its UI could not refresh: {}".format(exc))

    os.makedirs(os.path.dirname(fbx_export_path), exist_ok=True)
    cmds.select(all=True)

    if not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    excluded = {'persp', 'top', 'front', 'side'}
    all_nodes = cmds.ls(dag=True, type=["transform", "joint"], long=True)
    all_nodes = [n for n in all_nodes if cmds.nodeType(n) != "shape"]
    all_nodes.sort(key=lambda n: len(n.split('|')), reverse=True)
    renamed = {}
    for node in all_nodes:
        short_name = node.split('|')[-1]
        if short_name in excluded:
            continue

        base_name = short_name
        final_name = f"{namespace}:{base_name}"
        try:
            new_name = cmds.rename(node, final_name)
            renamed[new_name] = node
        except Exception as e:
            print(f"[WARNING] Could not rename {node} to {final_name}: {e}")

    mel.eval('FBXResetExport;')
    mel.eval('FBXExportSkeletonDefinitions -v true')
    mel.eval('FBXExportInputConnections -v false')
    mel.eval('FBXExportConstraints -v false')
    mel.eval('FBXExport -f "{}" -s;'.format(fbx_export_path.replace('\\', '/')))
    print(f"[Maya] Character exported to: {fbx_export_path}")
    return joint_map


joint_map = {
    "Hips": "root_joint",
    "LeftUpLeg": "l_thigh",
    "LeftLeg": "l_knee",
    "LeftFoot": "l_ankle",
    "RightUpLeg": "r_thigh",
    "RightLeg": "r_knee",
    "RightFoot": "r_ankle",
    "Spine": "spine_1",
    "Spine1": "spine3",
    "Neck": "neck",
    "Head": "head",
    "LeftArm": "l_upperarm",
    "LeftForeArm": "l_lowerarm",
    "LeftHand": "l_hand",
    "RightArm": "r_upperarm",
    "RightForeArm": "r_lowerarm",
    "RightHand": "r_hand"
}


def populate_default_face_map_from_scene(base_face_map=None):
    """Fill face map with default scene joints under HIK head reference."""
    if base_face_map is None:
        dm = copy.deepcopy(DEFAULT_FACE_JOINT_MAP)
    else:
        dm = base_face_map

    side = "l"
    dm["LeftBrow"]["joints"] = [f"{side}_brow{i}" for i in range(1, 6)]
    dm["LeftEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
    dm["LeftEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
    dm["LeftEyelid"]["joints"] = [
        f"{side}_inner_eyelidTip",
        f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
        f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
        f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
        f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
        f"{side}_outer_eyelidTip",
        f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
        f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
        f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
    ]
    
    side = "r"
    dm["RightBrow"]["joints"] = [f"{side}_brow{i}" for i in range(1, 6)]
    dm["RightEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
    dm["RightEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
    dm["RightEyelid"]["joints"] = [
        f"{side}_inner_eyelidTip",
        f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
        f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
        f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
        f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
        f"{side}_outer_eyelidTip",
        f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
        f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
        f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
    ]

    # ---------- Lips ----------
    dm["LipChain"]["joints"] = [
        'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
        'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
        'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
        'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
    ]
    dm["UpperLipCenter"]["joint"] = "c_upper_lip"
    dm["LowerLipCenter"]["joint"] = "c_lower_lip"
    dm["LeftLipCorner"]["joint"] = "l_lip_corner1"
    dm["RightLipCorner"]["joint"] = "r_lip_corner1"

    # ---------- Jaw ----------
    dm["Jaw"]["joint"] = "jaw"

    # ---------- Tongue ----------
    dm["TongueChain"]["joints"] = ["tongue1", "tongue2", "tongue3", "tongue4"]

    # ---------- Teeth ----------
    dm["UpperTeeth"]["joint"] = "upper_teeth"
    dm["LowerTeeth"]["joint"] = "lower_teeth"

    # ---------- Eyes ----------
    dm["LeftEye"]["joint"] = "l_eye"
    dm["RightEye"]["joint"] = "r_eye"

    # ---------- Nose ----------
    dm["NoseRoot"]["joint"] = "nose_root"

    # ---------- Other Face Joints ----------
    dm["OtherFaceJoints"]["joints"] = [
        'r_undereye_3', 'r_undereye_4', 'r_undereye_5', 'r_undereye_1',
        'r_ear_base1', 'r_ear_base', 'l_upper_cheek', 'r_undereye_2',
        'l_lower_cheek', 'l_inner_cheek', 'r_upper_nose',
        'l_inner_cheek_smile', 'r_inner_cheek_smile', 'r_inner_cheek',
        'r_upper_cheek', 'r_lower_cheek',
        'r_undereye_8', 'r_undereye_7', 'r_undereye_6',
        'l_undereye_8', 'l_undereye_7', 'l_undereye_6',
        'l_undereye_5', 'l_undereye_4', 'l_undereye_3',
        'l_undereye_2', 'l_undereye_1',
        'l_ear_base1', 'l_upper_nose', 'l_ear_base'
    ]
    return dm


def guess_joint_map_from_root(root_joint, base_joint_map=None):
    """
    Guesses HIK joint slots from a root joint based on name matching.
    
    :param root_joint: The root joint of the skeleton.
    :param base_joint_map: Optional dict to write results into (e.g. self.default_map).
                           If None, a deep copy of setup_hik.DEFAULT_JOINT_MAP is used.
    :return: A dict with HIK slots and their mapped joint names.
    """
    if not cmds.objExists(root_joint):
        return {}

    if base_joint_map is None:
        joint_map = copy.deepcopy(DEFAULT_JOINT_MAP)
    else:
        joint_map = base_joint_map

    # Reset any existing joint mappings to avoid stale cache from previous runs
    for key in joint_map:
        joint_map[key]["joint"] = ""

    def is_twist_bone(name):
        return "twist" in name or "roll" in name

    all_joints = cmds.listRelatives(root_joint, ad=True, type="joint") or []
    all_joints = list(reversed(all_joints))
    all_joints.insert(0, root_joint)

    spines = []
    necks = []

    fingers = {
        "Left": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []},
        "Right": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []}
    }

    def normalized_short_name(joint):
        short_name = joint.rsplit("|", 1)[-1].rsplit(":", 1)[-1].lower()
        return re.sub(r"[^a-z0-9]+", "_", short_name).strip("_")

    def matches_alias(joint, aliases):
        name = normalized_short_name(joint)
        return any(
            name == alias or re.fullmatch(re.escape(alias) + r"\d+", name)
            for alias in aliases
        )

    left_arm_aliases = {
        "l_upperarm", "l_upper_arm", "upperarm_l", "upper_arm_l",
        "left_upperarm", "left_upper_arm", "l_arm", "arm_l", "leftarm",
    }
    right_arm_aliases = {
        "r_upperarm", "r_upper_arm", "upperarm_r", "upper_arm_r",
        "right_upperarm", "right_upper_arm", "r_arm", "arm_r", "rightarm",
    }
    left_forearm_aliases = {
        "l_lowerarm", "l_lower_arm", "lowerarm_l", "lower_arm_l",
        "l_forearm", "forearm_l", "left_forearm", "leftforearm",
        "l_elbow", "elbow_l", "left_elbow",
    }
    right_forearm_aliases = {
        "r_lowerarm", "r_lower_arm", "lowerarm_r", "lower_arm_r",
        "r_forearm", "forearm_r", "right_forearm", "rightforearm",
        "r_elbow", "elbow_r", "right_elbow",
    }

    # Shoulder names are ambiguous only when a distinct upper-arm joint exists.
    has_l_upperarm = any(matches_alias(joint, left_arm_aliases) for joint in all_joints)
    has_r_upperarm = any(matches_alias(joint, right_arm_aliases) for joint in all_joints)

    twist_map = {
        # arms
        "upperarm": ("ArmRoll", 3),
        "lowerarm": ("ForeArmRoll", 3),
        # legs
        "thigh": ("UpLegRoll", 3),
        "knee": ("LegRoll", 2),
    }
    side_prefix = {"l": "Left", "r": "Right"}

    for jnt in all_joints:
        name = jnt.lower()
        short_name = normalized_short_name(jnt)

        def set_slot(slot):
            if slot in joint_map and not joint_map[slot].get("joint"):
                joint_map[slot]["joint"] = jnt

        # 1. Twist joints mapping
        is_twist = is_twist_bone(name)
        if is_twist:
            for side in ("l", "r"):
                for limb, (slot_base, count) in twist_map.items():
                    if limb in name:
                        # Match side prefix or suffix
                        is_side = False
                        if side == "l":
                            is_side = name.startswith("l_") or "l_upper" in name or "l_lower" in name or name.endswith("_l") or "_l_" in name or "left" in name
                        else:
                            is_side = name.startswith("r_") or "r_upper" in name or "r_lower" in name or name.endswith("_r") or "_r_" in name or "right" in name
                        
                        if is_side:
                            match = re.search(r'(\d+)', name)
                            num = int(match.group(1)) if match else 1
                            
                            slot_base_fixed = slot_base.replace('ForeArm', "Forearm")
                            if num == 1:
                                joint_map_key = f"{side_prefix[side]}{slot_base}"
                                if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                    joint_map[joint_map_key]["joint"] = jnt
                            else:
                                leaf_idx = num - 1
                                joint_map_key = f"Leaf{side_prefix[side]}{slot_base_fixed}{leaf_idx}"
                                if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                    joint_map[joint_map_key]["joint"] = jnt
            continue

        # 2. Main skeleton joints mapping
        if "spine" in name or "spn" in name:
            spines.append(jnt)

        elif "origin" in name or "root" in name:
            set_slot("Reference")

        elif "pelvis" in name:
            set_slot("Hips")

        elif "hipswing" in name or "hip_swing" in name:
            set_slot("HipSwing")

        elif matches_alias(jnt, {"l_clavicle", "clavicle_l", "left_clavicle"}) or (matches_alias(jnt, {"l_shoulder", "shoulder_l", "left_shoulder"}) and has_l_upperarm):
            set_slot("LeftShoulder")
        elif matches_alias(jnt, left_arm_aliases) or (matches_alias(jnt, {"l_shoulder", "shoulder_l", "left_shoulder"}) and not has_l_upperarm):
            set_slot("LeftArm")
        elif matches_alias(jnt, left_forearm_aliases):
            set_slot("LeftForeArm")

        elif matches_alias(jnt, {"l_hand", "hand_l", "left_hand", "lefthand"}) and "ik" not in short_name:
            set_slot("LeftHand")

        elif matches_alias(jnt, {"r_clavicle", "clavicle_r", "right_clavicle"}) or (matches_alias(jnt, {"r_shoulder", "shoulder_r", "right_shoulder"}) and has_r_upperarm):
            set_slot("RightShoulder")
        elif matches_alias(jnt, right_arm_aliases) or (matches_alias(jnt, {"r_shoulder", "shoulder_r", "right_shoulder"}) and not has_r_upperarm):
            set_slot("RightArm")
        elif matches_alias(jnt, right_forearm_aliases):
            set_slot("RightForeArm")

        elif matches_alias(jnt, {"r_hand", "hand_r", "right_hand", "righthand"}) and "ik" not in short_name:
            set_slot("RightHand")

        elif ("l_thigh" in name or "thigh_l" in name or "l_upperleg" in name):
            set_slot("LeftUpLeg")

        elif ("l_knee" in name or "knee_l" in name or "calf_l" in name or "l_lowerleg" in name):
            set_slot("LeftLeg")

        elif "l_ankle" in name or "ankle_l" in name or "foot_l" in name and "ik" not in name:
            set_slot("LeftFoot")

        elif "l_toe" in name and "tip" not in name or "ball_l" in name:
            set_slot("LeftToeBase")

        elif ("r_thigh" in name or "thigh_r" in name or "r_upperleg" in name):
            set_slot("RightUpLeg")

        elif ("r_knee" in name or "knee_r" in name or "calf_r" in name or "r_lowerleg" in name):
            set_slot("RightLeg")

        elif "r_ankle" in name or "ankle_r" in name or "foot_r" in name and "ik" not in name:
            set_slot("RightFoot")
        elif "r_toe" in name and "tip" not in name or "ball_r" in name:
            set_slot("RightToeBase")

        if "neck" in name:
            necks.append(jnt)
        elif "head" in name:
            set_slot("Head")

        for side_prefix_str, side in [("l_", "Left"), ("r_", "Right")]:
            if name.startswith(side_prefix_str):
                for finger in fingers[side].keys():
                    if finger.lower() in name:
                        fingers[side][finger].append(jnt)
            elif name.endswith("_" + side[0].lower()):
                for finger in fingers[side].keys():
                    if not len(fingers[side][finger]):
                        if cmds.objExists(f"{finger.lower()}_metacarpal_{side[0].lower()}"):
                            fingers[side][finger].append(f"{finger.lower()}_metacarpal_{side[0].lower()}")
                        if cmds.objExists(f"{finger.lower()}_01_{side[0].lower()}"):
                            fingers[side][finger].append(f"{finger.lower()}_01_{side[0].lower()}")
                            fingers[side][finger].append(f"{finger.lower()}_02_{side[0].lower()}")
                            fingers[side][finger].append(f"{finger.lower()}_03_{side[0].lower()}")

    for i, spine in enumerate(spines):
        key = "Spine" if i == 0 else f"Spine{i}"
        if key in joint_map and not joint_map[key].get("joint"):
            joint_map[key]["joint"] = spine

    for i, neck in enumerate(necks):
        key = "Neck" if i == 0 else f"Neck{i}"
        if key in joint_map and not joint_map[key].get("joint"):
            joint_map[key]["joint"] = neck

    for side in ["Left", "Right"]:
        for finger in ["Thumb", "Index", "Middle", "Ring", "Pinky"]:
            joints_list = fingers[side][finger]
            if not joints_list:
                continue
            if "_metacarpal_" not in joints_list[0]:
                joints_sorted = sorted(joints_list, key=lambda x: x.lower())
            else:
                joints_sorted = joints_list
            if "Thumb" not in finger:
                in_hand_key = f"{side}InHand{finger}"
                if in_hand_key in joint_map and not joint_map[in_hand_key].get("joint"):
                    joint_map[in_hand_key]["joint"] = joints_sorted[0]
            else:
                if len(joints_list) > 4:
                    thumb4_key = f"{side}Hand{finger}4"
                else:
                    thumb4_key = f"{side}Hand{finger}3"
                joint_map[thumb4_key]["joint"] = joints_sorted[-1]
            for i in range(1, min(5, len(joints_sorted))):
                num = i
                if "Thumb" in finger:
                    num = i - 1
                key = f"{side}Hand{finger}{i}"
                if key in joint_map and not joint_map[key].get("joint"):
                    joint_map[key]["joint"] = joints_sorted[num]
                    
    return joint_map


def create_rig_mapping(root_joint=None):
    """
    Standalone HIK mapping function. Auto-detects the skeleton root if none is provided,
    then runs guess_joint_map_from_root and populate_default_face_map_from_scene.
    Returns a tuple of (body_joint_map, face_joint_map) suitable for passing to
    create_rig.hik_map_to_rig_args.

    :param root_joint: Optional root joint name. If None, auto-detected from scene.
    :return: (body_joint_map dict, face_joint_map dict)
    """
    if root_joint is None:
        top_joints = joints_util.find_skinned_or_top_joints(namespace='')
        if not top_joints:
            print("[create_rig_mapping] No root joint found in scene.")
            return None, None
        root_joint = top_joints[0]

    body_joint_map = guess_joint_map_from_root(root_joint)
    face_joint_map = populate_default_face_map_from_scene()
    return body_joint_map, face_joint_map
