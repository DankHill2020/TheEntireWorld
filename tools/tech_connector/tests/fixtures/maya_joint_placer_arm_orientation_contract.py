"""Validate the studio arm orientation contract in an isolated Maya scene."""

import importlib
import json

import maya.standalone


maya.standalone.initialize(name="python")

import maya.api.OpenMaya as om  # noqa: E402
import maya.cmds as cmds  # noqa: E402

from maya_tools.Rigging import joint_placer  # noqa: E402


joint_placer = importlib.reload(joint_placer)
cmds.file(new=True, force=True)

positions = {
    "l_clavicle": (1.786101, 104.042664, 1.045606),
    "l_upperarm": (12.646540, 103.688395, -4.652945),
    "l_lowerarm": (29.888790, 102.813679, -4.645300),
    "l_hand": (45.926020, 103.737197, -4.638187),
    "l_handTip": (59.0, 103.7, -4.3),
    "r_clavicle": (-1.940031, 104.031460, 1.133782),
    "r_upperarm": (-12.791302, 103.705297, -4.686500),
    "r_lowerarm": (-30.060655, 102.821787, -4.645000),
    "r_hand": (-46.054155, 103.737057, -4.637425),
    "r_handTip": (-59.0, 103.7, -4.3),
}

for side in ("l", "r"):
    cmds.select(clear=True)
    for name in (
        "{}_clavicle".format(side),
        "{}_upperarm".format(side),
        "{}_lowerarm".format(side),
        "{}_hand".format(side),
        "{}_handTip".format(side),
    ):
        cmds.joint(name=name, position=positions[name])

offsets = joint_placer.orient_studio_arm_chains()
rows = {}
for side in ("l", "r"):
    upperarm = "{}_upperarm".format(side)
    elbow = "{}_lowerarm".format(side)
    hand = "{}_hand".format(side)
    shoulder_point = om.MVector(*cmds.xform(
        upperarm, query=True, worldSpace=True, translation=True
    ))
    elbow_point = om.MVector(*cmds.xform(
        elbow, query=True, worldSpace=True, translation=True
    ))
    wrist_point = om.MVector(*cmds.xform(
        hand, query=True, worldSpace=True, translation=True
    ))
    first = elbow_point - shoulder_point
    second = wrist_point - elbow_point
    aim_sign = 1.0 if side == "l" else -1.0
    expected_x = first.normal() * aim_sign
    expected_y = first ^ second
    expected_y.normalize()
    expected_z = expected_x ^ expected_y
    expected_z.normalize()
    axes = joint_placer._joint_world_axes(upperarm)
    rows[side] = {
        "axis_dots": {
            "x": float(axes["x"] * expected_x),
            "y": float(axes["y"] * expected_y),
            "z": float(axes["z"] * expected_z),
        },
        "translate_x": [
            float(cmds.getAttr(joint + ".translateX"))
            for joint in (upperarm, elbow, hand)
        ],
        "translate_yz": [
            [
                float(cmds.getAttr(joint + ".translateY")),
                float(cmds.getAttr(joint + ".translateZ")),
            ]
            for joint in (upperarm, elbow, hand)
        ],
    }

failures = []
for side, row in rows.items():
    expected_sign = 1.0 if side == "l" else -1.0
    if min(row["axis_dots"].values()) < 0.999:
        failures.append("{} axes".format(side))
    if any(value * expected_sign <= 0.0 for value in row["translate_x"]):
        failures.append("{} translateX sign".format(side))
    if any(abs(value) > 1.0e-5 for pair in row["translate_yz"] for value in pair):
        failures.append("{} translateYZ".format(side))

print(json.dumps({
    "ok": not failures,
    "failures": failures,
    "rows": rows,
    "offsets": offsets,
}, sort_keys=True))

maya.standalone.uninitialize()
