"""Rebuild the active production mesh and validate placement contracts."""

import importlib
import json

import maya.cmds as cmds

from maya_tools.Rigging import joint_placer


joint_placer = importlib.reload(joint_placer)
mesh = "Lost_Soul_Kid:Lost_Soul_Kid"
if not cmds.objExists(mesh):
    raise RuntimeError("Expected active test mesh: " + mesh)

result = joint_placer.build_basic_biped_skeleton(
    mesh=mesh,
    solver="production",
    replace_existing=True,
    create_guides=False,
)


def vector(node, attribute):
    return tuple(float(value) for value in cmds.getAttr(node + "." + attribute)[0])


def point(node):
    return tuple(float(value) for value in cmds.xform(
        node, query=True, worldSpace=True, translation=True
    ))


def axes(node):
    matrix = cmds.xform(node, query=True, worldSpace=True, matrix=True)
    return {
        "x": tuple(float(value) for value in matrix[0:3]),
        "y": tuple(float(value) for value in matrix[4:7]),
        "z": tuple(float(value) for value in matrix[8:11]),
    }


def dot(first, second):
    return sum(first[index] * second[index] for index in range(3))


bounds = cmds.exactWorldBoundingBox(mesh)
width = max(float(bounds[3] - bounds[0]), 1.0e-8)
height = max(float(bounds[4] - bounds[1]), 1.0e-8)
root = result.root_joint
report = {
    "root": root,
    "mesh": mesh,
    "hands": {},
    "arms": {},
    "elbows": {},
    "thighs": {},
    "fingers": {},
}
failures = []

for side in ("l", "r"):
    hand = side + "_hand"
    elbow = side + "_lowerarm"
    thigh = side + "_thigh"
    hand_translate = vector(hand, "translate")
    elbow_rotate = vector(elbow, "rotate")
    thigh_position = point(thigh)
    upper_position = point(side + "_upperarm")
    elbow_position = point(elbow)
    hand_position = point(hand)
    report["hands"][side] = {
        "translate": hand_translate,
        "joint_orient": vector(hand, "jointOrient"),
    }
    report["elbows"][side] = {"rotate": elbow_rotate}
    report["arms"][side] = {
        "upperarm_position": upper_position,
        "elbow_position": elbow_position,
        "hand_position": hand_position,
        "upperarm_normalized_half_width": abs(upper_position[0]) / (width * 0.5),
        "elbow_normalized_half_width": abs(elbow_position[0]) / (width * 0.5),
        "hand_normalized_half_width": abs(hand_position[0]) / (width * 0.5),
        "upperarm_normalized_height": abs(upper_position[0]) / height,
        "elbow_normalized_height": abs(elbow_position[0]) / height,
        "hand_normalized_height": abs(hand_position[0]) / height,
    }
    report["thighs"][side] = {
        "position": thigh_position,
        "normalized_half_width": abs(thigh_position[0]) / (width * 0.5),
    }
    if max(abs(hand_translate[1]), abs(hand_translate[2])) > 1.0e-5:
        failures.append(side + "_hand_translate_not_x_only")
    if max(abs(elbow_rotate[0]), abs(elbow_rotate[1])) > 1.0e-5:
        failures.append(side + "_elbow_not_z_only")
    if report["thighs"][side]["normalized_half_width"] < 0.09:
        failures.append(side + "_thigh_too_medial")
    if not 0.075 <= report["arms"][side]["upperarm_normalized_height"] <= 0.11:
        failures.append(side + "_upperarm_not_anatomical")
    if not 0.19 <= report["arms"][side]["elbow_normalized_height"] <= 0.25:
        failures.append(side + "_elbow_not_anatomical")
    if not 0.32 <= report["arms"][side]["hand_normalized_height"] <= 0.39:
        failures.append(side + "_wrist_not_anatomical")

    for digit in ("index", "middle", "ring", "pinky"):
        chain_report = []
        for index in range(1, 6):
            joint = "{0}_{1}_{2:02d}".format(side, digit, index)
            if not cmds.objExists(joint):
                continue
            joint_axes = axes(joint)
            bend_axis = (
                cmds.getAttr(joint + "." + joint_placer.BEND_AXIS_ATTR)
                if cmds.attributeQuery(joint_placer.BEND_AXIS_ATTR, node=joint, exists=True)
                else ""
            )
            row = {
                "joint": joint,
                "dorsal_z_dot_world_y": dot(joint_axes["z"], (0.0, 1.0, 0.0)),
                "bend_axis": bend_axis,
                "translate": vector(joint, "translate"),
            }
            chain_report.append(row)
            if index >= 3 and bend_axis != "z":
                failures.append(joint + "_curl_axis_not_z")
            if index >= 2 and max(abs(row["translate"][1]), abs(row["translate"][2])) > 1.0e-5:
                failures.append(joint + "_translate_not_x_only")
            if index >= 2 and row["dorsal_z_dot_world_y"] < 0.75:
                failures.append(joint + "_z_not_dorsal")
            rotate = vector(joint, "rotate")
            if max(abs(rotate[0]), abs(rotate[1])) > 1.0e-5:
                failures.append(joint + "_non_curl_rotate")
        report["fingers"][side + "_" + digit] = chain_report

for joint in ("l_hand", "r_hand", "l_lowerarm", "r_lowerarm"):
    rotate = vector(joint, "rotate")
    preferred = vector(joint, "preferredAngle")
    if max(abs(rotate[index] - preferred[index]) for index in range(3)) > 1.0e-5:
        failures.append(joint + "_preferred_angle_mismatch")

report["failures"] = sorted(set(failures))
report["passed"] = not report["failures"]
print("MAYA_JOINT_PLACER_APPLY=" + json.dumps(report, sort_keys=True))
if failures:
    raise RuntimeError("Joint placer validation failed: " + ", ".join(sorted(set(failures))))
