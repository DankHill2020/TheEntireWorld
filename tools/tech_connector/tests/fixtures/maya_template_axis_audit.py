"""Read the authored local/world limb axes from a Maya template scene."""

import json
import sys

import maya.standalone


maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402
from maya_tools.Rigging import joint_placer  # noqa: E402


WANTED = {
    "spine5", "spine5_Tip", "neck1", "neck2", "head1", "head1_Tip",
    "l_clavicle", "r_clavicle", "l_upperarm", "r_upperarm",
    "l_lowerarm", "r_lowerarm", "l_hand", "r_hand",
    "l_thigh", "r_thigh", "l_knee", "r_knee",
}


def short_name(node):
    return node.split("|")[-1].split(":")[-1]


output_path, scene_path = sys.argv[-2:]
cmds.file(scene_path, open=True, force=True, ignoreVersion=True, prompt=False)
mesh_candidates = []
for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
    transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
    if not transform:
        continue
    bounds = cmds.exactWorldBoundingBox(transform)
    height = float(bounds[4] - bounds[1])
    vertices = int(cmds.polyEvaluate(shape, vertex=True) or 0)
    mesh_candidates.append(((vertices == 29094, height, vertices), transform, bounds))
body_mesh = None
body_bounds = None
if mesh_candidates:
    _score, body_mesh, body_bounds = max(mesh_candidates, key=lambda item: item[0])
rows = []
interior_query = joint_placer.MeshInteriorQuery(body_mesh) if body_mesh else None
for joint in cmds.ls(type="joint", long=True) or []:
    name = short_name(joint)
    if name not in WANTED:
        continue
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    world_position = matrix[12:15]
    local_depth_fraction = None
    depth_interval = None
    if interior_query is not None:
        intervals = interior_query.axis_intervals(world_position, "z")
        depth_interval = joint_placer._choose_interval(intervals, world_position[2])
        if depth_interval and depth_interval[1] - depth_interval[0] > 1.0e-8:
            local_depth_fraction = (
                (world_position[2] - depth_interval[0])
                / (depth_interval[1] - depth_interval[0])
            )
    rows.append({
        "name": name,
        "node": joint,
        "translate": list(cmds.getAttr(joint + ".translate")[0]),
        "rotate": list(cmds.getAttr(joint + ".rotate")[0]),
        "joint_orient": list(cmds.getAttr(joint + ".jointOrient")[0]),
        "world_position": world_position,
        "depth_interval": depth_interval,
        "local_depth_fraction": local_depth_fraction,
        "world_x": matrix[0:3],
        "world_y": matrix[4:7],
        "world_z": matrix[8:11],
    })
with open(output_path, "w") as stream:
    json.dump({
        "scene": scene_path,
        "body_mesh": body_mesh,
        "body_bounds": body_bounds,
        "joints": rows,
    }, stream, indent=2, sort_keys=True)

maya.standalone.uninitialize()
