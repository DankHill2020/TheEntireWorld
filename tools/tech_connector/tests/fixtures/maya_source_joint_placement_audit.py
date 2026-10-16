"""Read-only standalone audit of an approved Maya rig scene.

Usage:
    mayapy maya_source_joint_placement_audit.py <scene.ma>
"""

from __future__ import annotations

import json
import sys

import maya.standalone


maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402


WANTED = {
    "origin", "pelvis", "spine1", "spine3", "spine5", "spine5_Tip",
    "neck1", "head1", "head1_Tip", "jaw", "jaw_Tip",
    "l_clavicle", "r_clavicle", "l_upperarm", "r_upperarm",
    "l_lowerarm", "r_lowerarm", "l_hand", "r_hand",
    "l_thigh", "r_thigh", "l_knee", "r_knee",
    "l_index_01", "l_index_02", "l_index_03", "l_index_04",
    "l_middle_01", "l_middle_02", "l_middle_03", "l_middle_04",
    "l_ring_01", "l_ring_02", "l_ring_03", "l_ring_04",
    "l_pinky_01", "l_pinky_02", "l_pinky_03", "l_pinky_04",
    "l_thumb_01", "l_thumb_02", "l_thumb_03", "l_thumb_04",
    "r_index_01", "r_index_02", "r_index_03", "r_index_04",
    "r_middle_01", "r_middle_02", "r_middle_03", "r_middle_04",
    "r_ring_01", "r_ring_02", "r_ring_03", "r_ring_04",
    "r_pinky_01", "r_pinky_02", "r_pinky_03", "r_pinky_04",
    "r_thumb_01", "r_thumb_02", "r_thumb_03", "r_thumb_04",
}


def short_name(node):
    return node.split("|")[-1].split(":")[-1]


def largest_body_mesh():
    candidates = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        parent = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        if not parent:
            continue
        bounds = cmds.exactWorldBoundingBox(parent)
        height = float(bounds[4] - bounds[1])
        vertices = int(cmds.polyEvaluate(shape, vertex=True) or 0)
        width = float(bounds[3] - bounds[0])
        candidates.append(((height, vertices, width), parent, bounds))
    if not candidates:
        raise RuntimeError("No renderable mesh found")
    return max(candidates, key=lambda item: item[0])


scene = sys.argv[-1]
cmds.file(scene, open=True, force=True, ignoreVersion=True, prompt=False)
_score, mesh, bounds = largest_body_mesh()
height = max(float(bounds[4] - bounds[1]), 1.0e-8)
origin = (
    (float(bounds[0]) + float(bounds[3])) * 0.5,
    float(bounds[1]),
    (float(bounds[2]) + float(bounds[5])) * 0.5,
)

rows = []
for joint in cmds.ls(type="joint", long=True) or []:
    name = short_name(joint)
    if name not in WANTED:
        continue
    position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    rows.append({
        "name": name,
        "node": joint,
        "world": [round(float(value), 6) for value in position],
        "normalized": [
            round((float(position[index]) - origin[index]) / height, 8)
            for index in range(3)
        ],
        "world_x": [round(float(value), 8) for value in matrix[0:3]],
        "world_y": [round(float(value), 8) for value in matrix[4:7]],
        "world_z": [round(float(value), 8) for value in matrix[8:11]],
    })

payload = {
    "scene": scene,
    "mesh": mesh,
    "bounds": [round(float(value), 6) for value in bounds],
    "vertex_count": int(cmds.polyEvaluate(mesh, vertex=True) or 0),
    "joint_count": len(rows),
    "joints": sorted(rows, key=lambda row: (row["name"], row["node"])),
}
serialized = json.dumps(payload, indent=2, sort_keys=True)
if len(sys.argv) >= 3:
    with open(sys.argv[-2], "w") as stream:
        stream.write(serialized)
else:
    print("JOINT_PLACEMENT_AUDIT=" + serialized)

maya.standalone.uninitialize()
