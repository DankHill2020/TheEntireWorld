"""Pose-test a built Blender rig made from the production Maya character."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))

from blender_tools.Rigging import rigging_host_adapter as rig  # noqa: E402


arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(arguments) < 2:
    raise RuntimeError("Expected built .blend and source snapshot paths after --")
blend_path = Path(arguments[0]).resolve()
snapshot_path = Path(arguments[1]).resolve()
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

bpy.ops.wm.open_mainfile(filepath=str(blend_path))
armature = bpy.data.objects["Armature"]
mesh = bpy.data.objects["Body_geo"]
slots = snapshot["slots"]


def update() -> None:
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def bone_world(name: str):
    return armature.matrix_world @ armature.pose.bones[name].matrix


def evaluated_vertices() -> list[Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = mesh.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ vertex.co.copy() for vertex in evaluated.data.vertices]


def maximum_vertex_delta(before: list[Vector], after: list[Vector]) -> float:
    return max((right - left).length for left, right in zip(before, after))


left_arm = slots["LeftArm"]
left_forearm = slots["LeftForeArm"]
left_hand = slots["LeftHand"]

# IK: first prove the zeroed IK and FK states match, then translate the
# world-oriented hand control and prove
# both the solved chain and the imported production skin respond.
fk_reference = {
    name: bone_world(name).copy()
    for name in (left_arm, left_forearm, left_hand)
}
ik_switch = rig.execute("rig.set_ik_fk_blend", {"limb": "left_arm", "blend": 1.0})
assert ik_switch["ok"], ik_switch
update()
ik_fk_switch_delta = max(
    abs(float(bone_world(name)[row][column] - fk_reference[name][row][column]))
    for name in (left_arm, left_forearm, left_hand)
    for row in range(4)
    for column in range(4)
)
if ik_fk_switch_delta >= 1.0e-4:
    print("IK_FK_SWITCH_DIAGNOSTICS=" + json.dumps({
        name: {
            "matrix_delta": max(
                abs(float(bone_world(name)[row][column] - fk_reference[name][row][column]))
                for row in range(4) for column in range(4)
            ),
            "position_delta": (bone_world(name).translation - fk_reference[name].translation).length,
        }
        for name in (left_arm, left_forearm, left_hand)
    }, sort_keys=True))
assert ik_fk_switch_delta < 1.0e-4, ik_fk_switch_delta
ik_control = bpy.data.objects[left_hand + "_ik_ctrl"]
ik_before_hand = bone_world(left_hand).translation.copy()
ik_before_forearm = bone_world(left_forearm).copy()
ik_before_vertices = evaluated_vertices()
upper_length = (bone_world(left_forearm).translation - bone_world(left_arm).translation).length
ik_control.matrix_world.translation += Vector((0.0, 0.0, max(upper_length * 0.2, 0.5)))
update()
ik_after_hand = bone_world(left_hand).translation.copy()
ik_after_forearm = bone_world(left_forearm).copy()
ik_after_vertices = evaluated_vertices()
ik_hand_delta = (ik_after_hand - ik_before_hand).length
ik_forearm_delta = max(
    abs(float(ik_after_forearm[row][column] - ik_before_forearm[row][column]))
    for row in range(4)
    for column in range(4)
)
ik_mesh_delta = maximum_vertex_delta(ik_before_vertices, ik_after_vertices)
assert ik_hand_delta > 1.0e-3, ik_hand_delta
assert ik_forearm_delta > 1.0e-4, ik_forearm_delta
assert ik_mesh_delta > 1.0e-4, ik_mesh_delta

# FK: switch fully to FK, rotate the upper-arm control in its own space, and
# prove the deform hierarchy and skin respond independently of the IK target.
fk_switch = rig.execute("rig.set_ik_fk_blend", {"limb": "left_arm", "blend": 0.0})
assert fk_switch["ok"], fk_switch
update()
fk_control = bpy.data.objects[f"left_arm_{left_arm}_fk_ctrl"]
fk_before_hand = bone_world(left_hand).translation.copy()
fk_before_vertices = evaluated_vertices()
fk_control.matrix_basis = fk_control.matrix_basis @ Matrix.Rotation(math.radians(12.0), 4, "Z")
update()
fk_after_hand = bone_world(left_hand).translation.copy()
fk_after_vertices = evaluated_vertices()
fk_hand_delta = (fk_after_hand - fk_before_hand).length
fk_mesh_delta = maximum_vertex_delta(fk_before_vertices, fk_after_vertices)
assert fk_hand_delta > 1.0e-3, fk_hand_delta
assert fk_mesh_delta > 1.0e-4, fk_mesh_delta

# Finger controls are part of the official full build.  Rotate one and verify
# that its mapped deform joint and the skinned production mesh both move.
finger_slot = "LeftHandIndex1"
finger_bone = slots[finger_slot]
finger_control = bpy.data.objects[finger_slot + "_ctrl"]
finger_before = bone_world(finger_bone).copy()
finger_before_vertices = evaluated_vertices()
finger_control.matrix_basis = finger_control.matrix_basis @ Matrix.Rotation(math.radians(18.0), 4, "Y")
update()
finger_after = bone_world(finger_bone).copy()
finger_after_vertices = evaluated_vertices()
finger_joint_delta = max(
    abs(float(finger_after[row][column] - finger_before[row][column]))
    for row in range(4)
    for column in range(4)
)
finger_mesh_delta = maximum_vertex_delta(finger_before_vertices, finger_after_vertices)
assert finger_joint_delta > 1.0e-4, finger_joint_delta
assert finger_mesh_delta > 1.0e-5, finger_mesh_delta

print("BLENDER_IMPORTED_CHARACTER_RIG_FUNCTIONAL_OK=" + json.dumps({
    "finger_joint_matrix_delta": finger_joint_delta,
    "finger_mesh_max_delta": finger_mesh_delta,
    "fk_hand_position_delta": fk_hand_delta,
    "fk_mesh_max_delta": fk_mesh_delta,
    "ik_forearm_matrix_delta": ik_forearm_delta,
    "ik_fk_zero_pose_delta": ik_fk_switch_delta,
    "ik_hand_position_delta": ik_hand_delta,
    "ik_mesh_max_delta": ik_mesh_delta,
    "mesh_vertex_count": len(mesh.data.vertices),
}, sort_keys=True))
