"""Read-only audit for comparing placed and referenced studio skeletons in Maya."""

import json

import maya.cmds as cmds


WANTED = {
    "pelvis", "l_thigh", "r_thigh", "l_knee", "r_knee",
    "l_clavicle", "r_clavicle", "l_upperarm", "r_upperarm",
    "l_lowerarm", "r_lowerarm", "l_hand", "r_hand",
    "l_index_01", "l_index_02", "l_index_03", "l_index_04",
    "r_index_01", "r_index_02", "r_index_03", "r_index_04",
}


def values(node, attribute):
    try:
        return [round(float(value), 6) for value in cmds.getAttr(node + "." + attribute)[0]]
    except Exception:
        return []


joint_rows = []
for joint in cmds.ls(type="joint", long=True) or []:
    leaf = joint.split("|")[-1]
    base = leaf.split(":")[-1]
    if base not in WANTED:
        continue
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    try:
        referenced = bool(cmds.referenceQuery(joint, isNodeReferenced=True))
    except Exception:
        referenced = False
    joint_rows.append({
        "base": base,
        "joint": joint,
        "namespace": leaf.rsplit(":", 1)[0] if ":" in leaf else "",
        "referenced": referenced,
        "translate": values(joint, "translate"),
        "rotate": values(joint, "rotate"),
        "joint_orient": values(joint, "jointOrient"),
        "world_position": [round(float(value), 6) for value in matrix[12:15]],
        "world_x": [round(float(value), 6) for value in matrix[0:3]],
        "world_y": [round(float(value), 6) for value in matrix[4:7]],
        "world_z": [round(float(value), 6) for value in matrix[8:11]],
    })

meshes = []
for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
    parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
    if not parents:
        continue
    transform = parents[0]
    meshes.append({
        "mesh": transform,
        "vertex_count": int(cmds.polyEvaluate(transform, vertex=True)),
        "bounds": [round(float(value), 6) for value in cmds.exactWorldBoundingBox(transform)],
    })

print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True),
    "modified": bool(cmds.file(query=True, modified=True)),
    "joints": joint_rows,
    "meshes": meshes,
}, sort_keys=True))
