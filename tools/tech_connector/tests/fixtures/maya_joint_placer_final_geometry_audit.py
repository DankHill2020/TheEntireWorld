"""Read-only final-placement audit for the active generated Maya skeleton."""

import importlib
import json

import maya.api.OpenMaya as om
import maya.cmds as cmds

from maya_tools.Rigging import joint_placer


importlib.reload(joint_placer)

mesh = "Lost_Soul_Kid:Lost_Soul_Kid"
root = joint_placer._find_template_joint("origin", namespace="")
if not root:
    raise RuntimeError("No generated unnamespaced studio skeleton found")
root = (cmds.ls(root, long=True) or [root])[0]
query = joint_placer._cached_mesh_interior_query(mesh)
bounds = cmds.exactWorldBoundingBox(mesh)
height = max(float(bounds[4] - bounds[1]), 1.0e-8)

rows = []
hierarchy = [root] + (
    cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
)
for joint in hierarchy:
    name = joint.split("|")[-1].split(":")[-1]
    point = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    closest = query.mesh_fn.getClosestPoint(
        om.MPoint(*point), om.MSpace.kWorld
    )[0]
    distance = (
        om.MVector(closest.x, closest.y, closest.z) - om.MVector(*point)
    ).length()
    outside_bounds = not (
        bounds[0] <= point[0] <= bounds[3]
        and bounds[1] <= point[1] <= bounds[4]
        and bounds[2] <= point[2] <= bounds[5]
    )
    rows.append({
        "name": name,
        "node": joint,
        "world": [round(float(value), 6) for value in point],
        "inside": bool(query.point_inside(point)),
        "outside_bounds": bool(outside_bounds),
        "surface_distance": round(float(distance), 6),
        "distance_over_height": round(float(distance / height), 8),
        "translate": [round(float(value), 6) for value in cmds.getAttr(joint + ".translate")[0]],
        "rotate": [round(float(value), 6) for value in cmds.getAttr(joint + ".rotate")[0]],
    })

worst = sorted(rows, key=lambda row: row["surface_distance"], reverse=True)
print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True),
    "modified": bool(cmds.file(query=True, modified=True)),
    "mesh": mesh,
    "root": root,
    "joint_count": len(rows),
    "outside_bounds": [row for row in rows if row["outside_bounds"]],
    "outside_volume_count": sum(not row["inside"] for row in rows),
    "worst_surface_distance": worst[:40],
    "arms": [
        row for row in rows
        if row["name"] in {
            "l_clavicle", "l_upperarm", "l_lowerarm", "l_hand",
            "r_clavicle", "r_upperarm", "r_lowerarm", "r_hand",
        }
        or any(token in row["name"] for token in (
            "index_", "middle_", "ring_", "pinky_", "thumb_",
        ))
    ],
}, sort_keys=True))
