"""Read-only comparison of the open scene skeleton against an approved atlas."""

import json
import math

import maya.cmds as cmds
from maya_tools.Rigging import joint_placer


ATLAS_PATH = "C:/depot/tools/maya_tools/Rigging/joint_placement_reference_atlas/studio_indian_woman_young.json"
FOCUS = {
    "pelvis", "l_thigh", "r_thigh", "l_knee", "r_knee",
    "l_clavicle", "r_clavicle", "l_upperarm", "r_upperarm",
    "l_lowerarm", "r_lowerarm", "l_hand", "r_hand",
    "l_eye", "r_eye", "upper_teeth", "lower_teeth",
    "tongue1", "tongue2", "tongue3", "tongue4",
    "l_brow1", "l_brow2", "l_brow3", "l_brow4", "l_brow5", "l_brow_end",
    "r_brow1", "r_brow2", "r_brow3", "r_brow4", "r_brow5", "r_brow_end",
}


def _short(node):
    return node.split("|")[-1].split(":")[-1]


def _dot(first, second):
    return sum(float(first[index]) * float(second[index]) for index in range(3))


with open(ATLAS_PATH, "r") as stream:
    atlas = json.load(stream)

meshes = []
for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
    parent = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
    if not parent:
        continue
    vertices = int(cmds.polyEvaluate(shape, vertex=True) or 0)
    bounds = cmds.exactWorldBoundingBox(parent)
    meshes.append(((vertices == int(atlas.get("mesh", {}).get("vertex_count", -1)), vertices), parent, bounds))
if not meshes:
    raise RuntimeError("No mesh found in open scene")
_, mesh, bounds = max(meshes, key=lambda item: item[0])
height = max(float(bounds[4] - bounds[1]), 1.0e-8)
origin = (
    (float(bounds[0]) + float(bounds[3])) * 0.5,
    float(bounds[1]),
    (float(bounds[2]) + float(bounds[5])) * 0.5,
)

unnamespaced = {}
for joint in cmds.ls(type="joint", long=True) or []:
    leaf = joint.split("|")[-1]
    if ":" not in leaf:
        unnamespaced[_short(joint)] = joint

rows = []
for name in sorted(FOCUS):
    joint = unnamespaced.get(name)
    reference = atlas["skeleton"]["points"].get(name)
    if not joint or not reference:
        rows.append({"name": name, "missing": not bool(joint)})
        continue
    world = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    normalized = [(float(world[i]) - origin[i]) / height for i in range(3)]
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    axes = atlas["skeleton"].get("axes", {}).get(name) or {}
    rows.append({
        "name": name,
        "world": [round(float(value), 6) for value in world],
        "normalized": [round(value, 8) for value in normalized],
        "reference": reference,
        "position_delta_over_height": round(math.sqrt(sum(
            (normalized[i] - float(reference[i])) ** 2 for i in range(3)
        )), 8),
        "axis_dots": {
            "x": round(_dot(matrix[0:3], axes.get("x", matrix[0:3])), 6),
            "y": round(_dot(matrix[4:7], axes.get("y", matrix[4:7])), 6),
            "z": round(_dot(matrix[8:11], axes.get("z", matrix[8:11])), 6),
        },
    })

print(json.dumps({
    "scene": cmds.file(query=True, sceneName=True),
    "modified": bool(cmds.file(query=True, modified=True)),
    "mesh": mesh,
    "mesh_bounds": bounds,
    "ranked_references": [
        [round(float(distance), 8), str(entry.get("case_id") or "")]
        for distance, entry in joint_placer._rank_reference_entries(
            mesh, require_detail=True
        )
    ],
    "rows": rows,
}, sort_keys=True))
