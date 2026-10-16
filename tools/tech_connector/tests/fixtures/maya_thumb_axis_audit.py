"""Report live thumb frames and compare them with the approved atlas frame."""

import json
from pathlib import Path

import maya.cmds as cmds
import maya.api.OpenMaya as om

from maya_tools.Rigging import joint_placer


ATLAS_PATH = Path(
    "C:/depot/tools/maya_tools/Rigging/joint_placement_reference_atlas/"
    "studio_indian_woman_young.json"
)


def _short(node):
    return node.split("|")[-1].split(":")[-1]


atlas = json.loads(ATLAS_PATH.read_text())
approved = atlas["skeleton"]["axes"]
rows = {}
joint_by_name = {
    _short(joint): joint for joint in (cmds.ls(type="joint", long=True) or [])
}
desired_x = {}
for name, joint in joint_by_name.items():
    if "_thumb_" not in name or name.endswith("_04"):
        continue
    children = cmds.listRelatives(
        joint, children=True, type="joint", fullPath=True
    ) or []
    if not children:
        continue
    start = om.MVector(*cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    ))
    end = om.MVector(*cmds.xform(
        children[0], query=True, worldSpace=True, translation=True
    ))
    direction = end - start
    if name.startswith("r_"):
        direction *= -1.0
    if direction.length() > 1.0e-8:
        desired_x[name] = direction.normal()
for side in ("l", "r"):
    parent = side + "_thumb_03"
    terminal = side + "_thumb_04"
    if parent in desired_x:
        desired_x[terminal] = om.MVector(desired_x[parent])
transported_y, reference_ids = joint_placer.solve_reference_joint_roll_vectors(
    "|Indian_Woman_Young_Model|Indian_Woman_Young_Model_Nude_Mod|Body_geo",
    desired_x,
)
knuckle_z = joint_placer.solve_reference_thumb_knuckle_z_vectors(
    "|Indian_Woman_Young_Model|Indian_Woman_Young_Model_Nude_Mod|Body_geo"
)
for joint in cmds.ls(type="joint", long=True) or []:
    name = _short(joint)
    if name not in approved or "_thumb_" not in name:
        continue
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    live = {
        "x": [float(value) for value in matrix[0:3]],
        "y": [float(value) for value in matrix[4:7]],
        "z": [float(value) for value in matrix[8:11]],
    }
    dots = {
        live_axis + "_to_approved_" + approved_axis: sum(
            live[live_axis][index] * approved[name][approved_axis][index]
            for index in range(3)
        )
        for live_axis in ("x", "y", "z")
        for approved_axis in ("x", "y", "z")
    }
    fitted_y = transported_y.get(name)
    fitted = None
    fitted_dots = None
    if fitted_y is not None and name in desired_x:
        fitted_x = om.MVector(desired_x[name]).normal()
        fitted_z = fitted_x ^ fitted_y
        fitted_z.normalize()
        fitted = {
            "x": [fitted_x.x, fitted_x.y, fitted_x.z],
            "y": [fitted_y.x, fitted_y.y, fitted_y.z],
            "z": [fitted_z.x, fitted_z.y, fitted_z.z],
        }
        fitted_dots = {
            axis: sum(live[axis][index] * fitted[axis][index] for index in range(3))
            for axis in ("x", "y", "z")
        }
    expected_surface_z = knuckle_z.get(name)
    if name.endswith(("_03", "_04")):
        expected_surface_z = knuckle_z.get(name.rsplit("_", 1)[0] + "_02")
    surface_basis = None
    surface_dots = None
    if expected_surface_z is not None and name in desired_x:
        expected = joint_placer._reference_z_basis(
            desired_x[name], om.MVector(*expected_surface_z)
        )
        surface_basis = {
            axis: [vector.x, vector.y, vector.z]
            for axis, vector in zip(("x", "y", "z"), expected)
        }
        surface_dots = {
            axis: sum(
                live[axis][index] * surface_basis[axis][index]
                for index in range(3)
            )
            for axis in ("x", "y", "z")
        }
    rows[name] = {
        "position": [float(value) for value in cmds.xform(
            joint, query=True, worldSpace=True, translation=True
        )],
        "live": live,
        "approved": approved[name],
        "axis_dots": dots,
        "transported_approved": fitted,
        "transported_same_axis_dots": fitted_dots,
        "surface_approved": surface_basis,
        "surface_same_axis_dots": surface_dots,
        "rotate": [float(value) for value in cmds.getAttr(joint + ".rotate")[0]],
        "joint_orient": [
            float(value) for value in cmds.getAttr(joint + ".jointOrient")[0]
        ],
    }

print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True),
    "modified": bool(cmds.file(query=True, modified=True)),
    "selection": cmds.ls(selection=True, long=True) or [],
    "reference_ids": reference_ids,
    "thumbs": rows,
}, sort_keys=True))
