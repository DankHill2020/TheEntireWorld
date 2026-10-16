"""Validate the studio leg orientation contract in an isolated Maya scene."""

import importlib
import json

import maya.standalone


maya.standalone.initialize(name="python")

import maya.api.OpenMaya as om  # noqa: E402
import maya.cmds as cmds  # noqa: E402

from maya_tools.Rigging import joint_placer  # noqa: E402


joint_placer = importlib.reload(joint_placer)
cmds.file(new=True, force=True)
cmds.select(clear=True)
hipswing = cmds.joint(name="hipswing", position=(0.0, 72.0, -2.5))

positions = {
    "l_thigh": (7.0, 70.0, -2.6),
    "l_knee": (7.0, 36.0, -1.9),
    "l_ankle": (7.0, 4.0, -3.0),
    "l_toe": (7.0, 0.5, 4.0),
    "l_toeTip": (7.0, 0.5, 10.0),
    "r_thigh": (-7.0, 70.0, -2.6),
    "r_knee": (-7.0, 36.0, -1.9),
    "r_ankle": (-7.0, 4.0, -3.0),
    "r_toe": (-7.0, 0.5, 4.0),
    "r_toeTip": (-7.0, 0.5, 10.0),
}

for side in ("l", "r"):
    cmds.select(hipswing, replace=True)
    for name in (
        "{}_thigh".format(side),
        "{}_knee".format(side),
        "{}_ankle".format(side),
        "{}_toe".format(side),
        "{}_toeTip".format(side),
    ):
        cmds.joint(name=name, position=positions[name])

joint_placer.capture_studio_template_knee_bend_axes()
offsets = joint_placer.orient_studio_leg_chains()
rows = {}
for side in ("l", "r"):
    thigh = "{}_thigh".format(side)
    knee = "{}_knee".format(side)
    ankle = "{}_ankle".format(side)
    hip_point = om.MVector(*cmds.xform(
        thigh, query=True, worldSpace=True, translation=True
    ))
    knee_point = om.MVector(*cmds.xform(
        knee, query=True, worldSpace=True, translation=True
    ))
    ankle_point = om.MVector(*cmds.xform(
        ankle, query=True, worldSpace=True, translation=True
    ))
    aim_sign = 1.0 if side == "l" else -1.0
    expected_y = joint_placer._studio_knee_hinge_direction(side)
    expected_y.normalize()
    axis_dots = {}
    for parent, child in ((thigh, knee), (knee, ankle)):
        parent_point = om.MVector(*cmds.xform(
            parent, query=True, worldSpace=True, translation=True
        ))
        child_point = om.MVector(*cmds.xform(
            child, query=True, worldSpace=True, translation=True
        ))
        expected_x = (child_point - parent_point).normal() * aim_sign
        expected_z = expected_x ^ expected_y
        expected_z.normalize()
        axes = joint_placer._joint_world_axes(parent)
        axis_dots[parent] = {
            "x": float(axes["x"] * expected_x),
            "y": float(axes["y"] * expected_y),
            "z": float(axes["z"] * expected_z),
        }
    rows[side] = {
        "axis_dots": axis_dots,
        "translate_x": [
            float(cmds.getAttr(joint + ".translateX"))
            for joint in (knee, ankle)
        ],
        "translate_yz": [
            [
                float(cmds.getAttr(joint + ".translateY")),
                float(cmds.getAttr(joint + ".translateZ")),
            ]
            for joint in (knee, ankle)
        ],
    }

failures = []
for side, row in rows.items():
    expected_sign = 1.0 if side == "l" else -1.0
    if any(min(dots.values()) < 0.999 for dots in row["axis_dots"].values()):
        failures.append("{} axes".format(side))
    if any(value * expected_sign <= 0.0 for value in row["translate_x"]):
        failures.append("{} translateX sign".format(side))
    if any(abs(value) > 1.0e-4 for pair in row["translate_yz"] for value in pair):
        failures.append("{} translateYZ".format(side))

print(json.dumps({
    "ok": not failures,
    "failures": failures,
    "rows": rows,
    "offsets": offsets,
}, sort_keys=True))

maya.standalone.uninitialize()
