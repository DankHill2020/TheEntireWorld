"""Read-only audit of referenced bind matrices for template limb joints."""

import json

import maya.api.OpenMaya as om
import maya.cmds as cmds


WANTED = {
    "l_clavicle", "r_clavicle", "l_upperarm", "r_upperarm",
    "l_lowerarm", "r_lowerarm", "l_hand", "r_hand",
    "l_thigh", "r_thigh", "l_knee", "r_knee",
}


def short_name(node):
    return node.split("|")[-1].split(":")[-1]


rows = []
for joint in cmds.ls(type="joint", long=True) or []:
    if short_name(joint) not in WANTED:
        continue
    try:
        if not cmds.referenceQuery(joint, isNodeReferenced=True):
            continue
    except Exception:
        continue
    bind_matrix = None
    source_plug = (cmds.ls(joint, long=False) or [joint])[0] + ".worldMatrix[0]"
    destinations = cmds.listConnections(
        source_plug, source=False, destination=True, plugs=True, type="skinCluster"
    ) or []
    for destination in destinations:
        if ".matrix[" not in destination:
            continue
        index = int(destination.rsplit("[", 1)[1].split("]", 1)[0])
        skin = destination.split(".", 1)[0]
        inverse_values = cmds.getAttr("{}.bindPreMatrix[{}]".format(skin, index))
        if not inverse_values:
            continue
        bind_matrix = list(om.MMatrix(inverse_values).inverse())
        break
    rows.append({
        "joint": joint,
        "name": short_name(joint),
        "translate": list(cmds.getAttr(joint + ".translate")[0]),
        "joint_orient": list(cmds.getAttr(joint + ".jointOrient")[0]),
        "bind_position": bind_matrix[12:15] if bind_matrix else None,
        "bind_x": bind_matrix[0:3] if bind_matrix else None,
        "bind_y": bind_matrix[4:7] if bind_matrix else None,
        "bind_z": bind_matrix[8:11] if bind_matrix else None,
    })

print(json.dumps(rows, sort_keys=True))
