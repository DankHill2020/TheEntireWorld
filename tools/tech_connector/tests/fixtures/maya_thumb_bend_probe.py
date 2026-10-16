"""Probe the mesh-derived distal thumb bend, then undo it."""

import json
import math

import maya.cmds as cmds

from maya_tools.Rigging import joint_placer


MESH = "|Indian_Woman_Young_Model|Indian_Woman_Young_Model_Nude_Mod|Body_geo"


def _positions(side):
    return [
        tuple(cmds.xform(
            joint_placer._find_template_joint(
                "{0}_thumb_{1:02d}".format(side, index), ""
            ),
            query=True,
            worldSpace=True,
            translation=True,
        ))
        for index in range(1, 5)
    ]


def _angles(points):
    result = []
    for index in (1, 2):
        first = [
            points[index][axis] - points[index - 1][axis]
            for axis in range(3)
        ]
        second = [
            points[index + 1][axis] - points[index][axis]
            for axis in range(3)
        ]
        first_length = math.sqrt(sum(value * value for value in first))
        second_length = math.sqrt(sum(value * value for value in second))
        cosine = sum(a * b for a, b in zip(first, second)) / (
            first_length * second_length
        )
        result.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    return result


before = {side: _positions(side) for side in ("l", "r")}
fit_report = joint_placer.fit_studio_distal_thumb_joints(MESH)
after = {side: _positions(side) for side in ("l", "r")}
for side in ("l", "r"):
    for index, position in enumerate(before[side], 1):
        joint = joint_placer._find_template_joint(
            "{0}_thumb_{1:02d}".format(side, index), ""
        )
        joint_placer._set_joint_world_translation_preserving_children(
            joint, position
        )

print(json.dumps({
    "fit_report": fit_report,
    "before": {
        side: {"positions": before[side], "angles": _angles(before[side])}
        for side in ("l", "r")
    },
    "probe": {
        side: {"positions": after[side], "angles": _angles(after[side])}
        for side in ("l", "r")
    },
}, sort_keys=True))
