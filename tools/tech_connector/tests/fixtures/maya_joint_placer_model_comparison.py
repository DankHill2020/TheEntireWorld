"""Build joint placement on a model scene and compare with an approved atlas."""

from __future__ import annotations

import importlib
import json
import math
import sys

import maya.standalone


maya.standalone.initialize(name="python")

import maya.cmds as cmds  # noqa: E402
import maya.api.OpenMaya as om  # noqa: E402

from maya_tools.Rigging import joint_placer  # noqa: E402


def short_name(node):
    return node.split("|")[-1].split(":")[-1]


def largest_body_mesh():
    candidates = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        if not transform:
            continue
        bounds = cmds.exactWorldBoundingBox(transform)
        height = float(bounds[4] - bounds[1])
        vertices = int(cmds.polyEvaluate(shape, vertex=True) or 0)
        candidates.append(((vertices == 29094, height, vertices), transform))
    if not candidates:
        raise RuntimeError("No renderable polygon mesh found")
    return max(candidates, key=lambda item: item[0])[1]


def dot(first, second):
    return sum(float(first[index]) * float(second[index]) for index in range(3))


def world_axes(joint):
    matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
    return {
        "x": matrix[0:3], "y": matrix[4:7], "z": matrix[8:11],
    }


def scene_axes(namespace=""):
    result = {}
    for joint in cmds.ls(type="joint", long=True) or []:
        leaf = joint.split("|")[-1]
        joint_namespace = leaf.rsplit(":", 1)[0] if ":" in leaf else ""
        if joint_namespace != namespace:
            continue
        result[short_name(joint)] = world_axes(joint)
    return result


def reference_namespace(names):
    counts = {}
    for joint in cmds.ls(type="joint", long=True) or []:
        leaf = joint.split("|")[-1]
        if ":" not in leaf or short_name(joint) not in names:
            continue
        namespace = leaf.rsplit(":", 1)[0]
        counts[namespace] = counts.get(namespace, 0) + 1
    return max(counts, key=counts.get) if counts else ""


def transported_roll_rows(generated, reference, names):
    rows = []
    for name in sorted(names):
        reference_name = "l_" + name[2:] if name.startswith("r_") else name
        if name not in generated or reference_name not in reference:
            continue
        reference_frame = reference[reference_name]
        if name.startswith("r_"):
            reference_frame = {
                axis: [values[0], -values[1], -values[2]]
                for axis, values in reference_frame.items()
            }
        target_x = om.MVector(*generated[name]["x"]).normal()
        expected_y = joint_placer._rotate_vector_between_directions(
            om.MVector(*reference_frame["y"]),
            om.MVector(*reference_frame["x"]),
            target_x,
        )
        expected_y -= target_x * (expected_y * target_x)
        if expected_y.length() <= 1.0e-8:
            continue
        expected_y.normalize()
        expected_z = target_x ^ expected_y
        expected_z.normalize()
        rows.append({
            "name": name,
            "transported_y_dot": dot(generated[name]["y"], expected_y),
            "transported_z_dot": dot(generated[name]["z"], expected_z),
        })
    return rows


def roll_summary(rows):
    values = [
        min(row["transported_y_dot"], row["transported_z_dot"])
        for row in rows
    ]
    return {
        "count": len(values),
        "mean_min_yz_dot": sum(values) / max(len(values), 1),
        "minimum_yz_dot": min(values) if values else 0.0,
        "worst": sorted(rows, key=lambda row: min(
            row["transported_y_dot"], row["transported_z_dot"]
        ))[:20],
    }


output_path, model_scene, atlas_path = sys.argv[-3:]
with open(atlas_path, "r") as stream:
    atlas = json.load(stream)
reference_points = atlas["skeleton"]["points"]
reference_axes = atlas["skeleton"]["axes"]
cmds.file(model_scene, open=True, force=True, ignoreVersion=True, prompt=False)
joint_placer = importlib.reload(joint_placer)
mesh = largest_body_mesh()
orientation_names = {
    "{0}_{1}".format(side, name)
    for side in ("l", "r")
    for name in (
        "clavicle", "upperarm", "lowerarm", "hand",
        "thigh", "knee", "ankle", "toe", "toeTip",
    )
}
orientation_names.update({
    "{0}_{1}_{2:02d}".format(side, digit, index)
    for side in ("l", "r")
    for digit, count in (
        ("thumb", 4), ("index", 5), ("middle", 5),
        ("ring", 5), ("pinky", 5),
    )
    for index in range(1, count + 1)
})
approved_namespace = reference_namespace(orientation_names)
approved_scene_axes = (
    scene_axes(approved_namespace) if approved_namespace else reference_axes
)
before_generated_axes = scene_axes("")
before_generated_positions = {
    short_name(joint): list(cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    ))
    for joint in cmds.ls(type="joint", long=True) or []
    if ":" not in joint.split("|")[-1]
}
before_roll_rows = transported_roll_rows(
    before_generated_axes, approved_scene_axes, orientation_names
)
scene_eye_meshes = joint_placer._scene_feature_meshes(
    ("eye", "eyes", "eyeball", "eyeballs", "ocular"),
    ("eyelid", "lid", "lash", "lashes", "brow", "brows"),
    anchor_mesh=mesh,
)
scene_teeth_meshes = joint_placer._scene_feature_meshes(
    ("tooth", "teeth"), anchor_mesh=mesh
)
scene_tongue_meshes = joint_placer._scene_feature_meshes(
    ("tongue",), anchor_mesh=mesh
)
result = joint_placer.build_basic_biped_skeleton(
    mesh=mesh,
    solver="production",
    replace_existing=True,
    create_guides=False,
)

bounds = cmds.exactWorldBoundingBox(mesh)
height = max(float(bounds[4] - bounds[1]), 1.0e-8)
origin = (
    (float(bounds[0]) + float(bounds[3])) * 0.5,
    float(bounds[1]),
    (float(bounds[2]) + float(bounds[5])) * 0.5,
)
root = result.root_joint
joints = [root] + (
    cmds.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
)
by_name = {short_name(joint): joint for joint in joints}
after_generated_axes = {
    name: world_axes(joint) for name, joint in by_name.items()
}
after_generated_positions = {
    name: list(cmds.xform(
        joint, query=True, worldSpace=True, translation=True
    ))
    for name, joint in by_name.items()
}
rerun_position_rows = []
for name in sorted(set(before_generated_positions) & set(after_generated_positions)):
    before_point = before_generated_positions[name]
    after_point = after_generated_positions[name]
    rerun_position_rows.append({
        "name": name,
        "delta": math.sqrt(sum(
            (float(after_point[index]) - float(before_point[index])) ** 2
            for index in range(3)
        )),
        "before": before_point,
        "after": after_point,
    })
rerun_position_rows.sort(key=lambda row: row["delta"], reverse=True)
face_tokens = (
    "brow", "eyelid", "eye", "lip", "nose", "jaw", "cheek",
    "tongue", "teeth", "ear", "chin", "forehead", "temple",
    "squint", "nostril",
)
face_frame_rows = []
for name in sorted(set(before_generated_axes) & set(after_generated_axes)):
    if not any(token in name.lower() for token in face_tokens):
        continue
    component_delta = max(
        abs(
            float(after_generated_axes[name][axis][index])
            - float(before_generated_axes[name][axis][index])
        )
        for axis in ("x", "y", "z")
        for index in range(3)
    )
    face_frame_rows.append({"name": name, "max_axis_component_delta": component_delta})
face_frame_rows.sort(key=lambda row: row["max_axis_component_delta"], reverse=True)

spine_forward = om.MVector(*after_generated_axes["spine5_Tip"]["y"]).normal()
neck_head_forward_rows = []
for name in ("neck1", "neck2", "head1", "head1_Tip"):
    frame = after_generated_axes[name]
    x_axis = om.MVector(*frame["x"]).normal()
    expected_y = spine_forward - (x_axis * (spine_forward * x_axis))
    if expected_y.length() <= 1.0e-8:
        continue
    expected_y.normalize()
    neck_head_forward_rows.append({
        "name": name,
        "projected_spine_forward_y_dot": dot(frame["y"], expected_y),
    })
neck_chain_frame_rows = []
for first_name, second_name in (("neck1", "neck2"), ("neck2", "head1")):
    first = after_generated_axes[first_name]
    second = after_generated_axes[second_name]
    neck_chain_frame_rows.append({
        "pair": first_name + "->" + second_name,
        "x_dot": dot(first["x"], second["x"]),
        "y_dot": dot(first["y"], second["y"]),
        "z_dot": dot(first["z"], second["z"]),
    })
after_roll_rows = transported_roll_rows(
    after_generated_axes, approved_scene_axes, orientation_names
)

position_rows = []
axis_rows = []
for name, reference in reference_points.items():
    joint = by_name.get(name)
    if not joint:
        continue
    world = cmds.xform(joint, query=True, worldSpace=True, translation=True)
    normalized = [
        (float(world[index]) - origin[index]) / height for index in range(3)
    ]
    delta = math.sqrt(sum(
        (normalized[index] - float(reference[index])) ** 2
        for index in range(3)
    ))
    position_rows.append({
        "name": name,
        "delta_over_height": delta,
        "generated": normalized,
        "reference": reference,
    })
    if name in reference_axes:
        matrix = cmds.xform(joint, query=True, worldSpace=True, matrix=True)
        generated_axes = {
            "x": matrix[0:3], "y": matrix[4:7], "z": matrix[8:11],
        }
        axis_rows.append({
            "name": name,
            "x_dot": dot(generated_axes["x"], reference_axes[name]["x"]),
            "y_dot": dot(generated_axes["y"], reference_axes[name]["y"]),
            "z_dot": dot(generated_axes["z"], reference_axes[name]["z"]),
        })

position_rows.sort(key=lambda row: row["delta_over_height"], reverse=True)
axis_rows.sort(key=lambda row: min(row["x_dot"], row["y_dot"], row["z_dot"]))
focus_names = {
    "spine5", "spine5_Tip", "neck1", "neck2", "head1", "head1_Tip",
    "nose_root", "nose_upper", "nose_tip", "nose_base",
    "c_upper_lip", "l_upper_lip4", "l_upper_lip3", "l_upper_lip2",
    "l_upper_lip1", "l_lip_corner1",
    "c_lower_lip", "l_lower_lip4", "l_lower_lip3", "l_lower_lip2",
    "l_lower_lip1",
    "l_eye", "r_eye", "upper_teeth", "lower_teeth",
    "tongue1", "tongue2", "tongue3", "tongue4",
    "l_brow1", "l_brow2", "l_brow3", "l_brow4", "l_brow5", "l_brow_end",
    "r_brow1", "r_brow2", "r_brow3", "r_brow4", "r_brow5", "r_brow_end",
    "l_upperarm", "l_lowerarm", "l_hand",
    "r_upperarm", "r_lowerarm", "r_hand",
}
payload = {
    "model_scene": model_scene,
    "mesh": mesh,
    "vertex_count": int(cmds.polyEvaluate(mesh, vertex=True) or 0),
    "generated_joint_count": len(joints),
    "approved_scene_namespace": approved_namespace,
    "orientation_before": roll_summary(before_roll_rows),
    "orientation_after": roll_summary(after_roll_rows),
    "orientation_before_axes": {
        name: before_generated_axes[name]
        for name in sorted(orientation_names)
        if name in before_generated_axes
    },
    "orientation_after_axes": {
        name: after_generated_axes[name]
        for name in sorted(orientation_names)
        if name in after_generated_axes
    },
    "rerun_position_change_count": sum(
        row["delta"] > 1.0e-5 for row in rerun_position_rows
    ),
    "rerun_position_max_delta": max(
        (row["delta"] for row in rerun_position_rows), default=0.0
    ),
    "rerun_worst_position_changes": rerun_position_rows[:30],
    "preserved_face_frame_count": len(face_frame_rows),
    "preserved_face_frame_max_axis_component_delta": max(
        (row["max_axis_component_delta"] for row in face_frame_rows),
        default=0.0,
    ),
    "worst_face_frame_changes": face_frame_rows[:20],
    "neck_head_forward_rows": neck_head_forward_rows,
    "neck_chain_frame_rows": neck_chain_frame_rows,
    "feature_meshes": {
        "eyes": scene_eye_meshes,
        "teeth": scene_teeth_meshes,
        "tongue": scene_tongue_meshes,
    },
    "compared_position_count": len(position_rows),
    "position_max_delta_over_height": max(
        (row["delta_over_height"] for row in position_rows), default=0.0
    ),
    "position_mean_delta_over_height": (
        sum(row["delta_over_height"] for row in position_rows)
        / max(len(position_rows), 1)
    ),
    "worst_positions": position_rows[:30],
    "focus_positions": [row for row in position_rows if row["name"] in focus_names],
    "worst_axes": axis_rows[:30],
    "focus_axes": [row for row in axis_rows if row["name"] in focus_names],
    "focus_local_translates": {
        name: list(cmds.getAttr(by_name[name] + ".translate")[0])
        for name in sorted(focus_names)
        if name in by_name
    },
    "focus_joint_orients": {
        name: list(cmds.getAttr(by_name[name] + ".jointOrient")[0])
        for name in sorted(focus_names)
        if name in by_name
    },
    "focus_rotates": {
        name: list(cmds.getAttr(by_name[name] + ".rotate")[0])
        for name in sorted(focus_names)
        if name in by_name
    },
    "focus_world_positions": {
        name: list(cmds.xform(
            by_name[name], query=True, worldSpace=True, translation=True
        ))
        for name in sorted(focus_names)
        if name in by_name
    },
}
with open(output_path, "w") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)

maya.standalone.uninitialize()
