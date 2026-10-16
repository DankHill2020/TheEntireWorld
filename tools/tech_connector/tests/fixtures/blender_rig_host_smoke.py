"""Live Blender smoke check for the shared rigging host adapter.

Run with Blender's Python, not pytest directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))

from blender_tools.Rigging import rigging_host_adapter as rig  # noqa: E402
from tech_connector.services.dcc.rigging_workspace_service import CharacterDefinition  # noqa: E402


bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

armature_data = bpy.data.armatures.new("SmokeRigData")
armature = bpy.data.objects.new("SmokeRig", armature_data)
bpy.context.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
armature.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")


def bone(name, head, tail, parent=None):
    item = armature_data.edit_bones.new(name)
    item.head, item.tail = head, tail
    if parent:
        item.parent = armature_data.edit_bones[parent]
    return item


bone("root", (0, 0, 0), (0, 0, 1))
bone("pelvis", (0, 0, 1), (0, 0, 2), "root")
bone("spine", (0, 0, 2), (0, 0, 4), "pelvis")
bone("neck", (0, 0, 4), (0, 0, 5), "spine")
bone("head", (0, 0, 5), (0, 0, 6), "neck")
bone("upperarm_l", (0, 0, 4), (2, 0, 4), "spine")
bone("forearm_l", (2, 0, 4), (4, 0, 4), "upperarm_l")
bone("hand_l", (4, 0, 4), (5, 0, 4), "forearm_l")
bone("thigh_l", (0.5, 0, 1), (0.5, 0, -1), "pelvis")
bone("shin_l", (0.5, 0, -1), (0.5, 0, -3), "thigh_l")
bone("foot_l", (0.5, 0, -3), (0.5, -1, -3), "shin_l")
bone("toe_l", (0.5, -1, -3), (0.5, -2, -3), "foot_l")
bone("toe_tip_l", (0.5, -2, -3), (0.5, -2.5, -3), "toe_l")
bone("upper_lip", (-0.3, -0.2, 5.4), (0.3, -0.2, 5.4), "head")
bone("lower_lip", (-0.3, -0.2, 5.2), (0.3, -0.2, 5.2), "head")
bone("lip_l", (0.3, -0.2, 5.3), (0.5, -0.2, 5.3), "head")
bone("lip_r", (-0.3, -0.2, 5.3), (-0.5, -0.2, 5.3), "head")
bpy.ops.object.mode_set(mode="POSE")

slots = {
    "Reference": "SmokeRig:root", "Hips": "SmokeRig:pelvis", "Spine": "SmokeRig:spine",
    "Neck": "SmokeRig:neck", "Head": "SmokeRig:head",
    "LeftArm": "SmokeRig:upperarm_l", "LeftForeArm": "SmokeRig:forearm_l", "LeftHand": "SmokeRig:hand_l",
    "LeftUpLeg": "SmokeRig:thigh_l", "LeftLeg": "SmokeRig:shin_l", "LeftFoot": "SmokeRig:foot_l",
    "LeftToeBase": "SmokeRig:toe_l",
    "UpperLipCenter": "SmokeRig:upper_lip", "LowerLipCenter": "SmokeRig:lower_lip",
    "LeftLipCorner": "SmokeRig:lip_l", "RightLipCorner": "SmokeRig:lip_r",
}
definition = CharacterDefinition("Smoke", slots=slots).to_dict()

bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.0), scale=(3.0, 2.0, 6.0))
placement_mesh = bpy.context.object
placement_mesh.name = "PlacementMesh"
preview = rig.execute("rig.place_joints", {
    "mesh": placement_mesh.name,
    "definition": definition,
    "preview": True,
})
assert preview["ok"] and not preview["data"]["applied"]
assert "LeftArm" in preview["data"]["positions"]
placement = rig.execute("rig.place_joints", {
    "definition": definition,
    "positions": preview["data"]["positions"],
})
assert placement["ok"] and placement["data"]["applied"], placement
assert len(placement["changed_ids"]) == len(preview["data"]["positions"])
expected_hand = preview["data"]["positions"]["LeftHand"]
actual_hand = armature.matrix_world @ armature.data.bones["hand_l"].head_local
assert max(abs(float(actual_hand[index]) - expected_hand[index]) for index in range(3)) < 1.0e-6

posed_once = rig.execute("rig.set_t_pose", {"definition": definition})
assert posed_once["ok"], posed_once
pose_before = {
    bone_name: armature.pose.bones[bone_name].matrix.copy()
    for bone_name in ("upperarm_l", "forearm_l", "thigh_l", "shin_l", "foot_l", "toe_l")
}
posed_again = rig.execute("rig.set_t_pose", {"definition": definition})
assert posed_again["ok"], posed_again
for bone_name, matrix in pose_before.items():
    current = armature.pose.bones[bone_name].matrix
    pose_delta = max(
        abs(float(current[row][column] - matrix[row][column]))
        for row in range(4) for column in range(4)
    )
    assert pose_delta < 1.0e-6

result = rig.execute("rig.build_full", {
    "modules": ["left_arm", "left_leg", "mouth"],
    "definition": definition,
    "options": {"ik_fk_blend": 0.0},
})
assert result["ok"], result
assert result["data"]["t_pose"]["ok"]
assert result["data"]["behavior_revision"] == rig.RIG_BEHAVIOR_REVISION

ribbon = rig.execute("rig.create_ribbon", {
    "joint_chain": ["SmokeRig:spine", "SmokeRig:neck", "SmokeRig:head"],
    "name": "smoke_ribbon",
    "module": "smoke_ribbon",
    "control_count": 3,
    "width": 0.5,
})
assert ribbon["ok"], ribbon
ribbon_constraint = armature.pose.bones["head"].constraints.get(
    "TCMOD_smoke_ribbon__TC_smoke_ribbon_spline_ik"
)
assert ribbon_constraint is not None and ribbon_constraint.type == "SPLINE_IK"
assert ribbon_constraint.chain_count == 3 and ribbon_constraint.target is not None
assert len(ribbon_constraint.target.modifiers) == 3
assert all(bpy.data.objects.get(f"smoke_ribbon_ctrl_{index:02d}") for index in range(1, 4))

for owner, module in (("forearm_l", "left_arm"), ("shin_l", "left_leg")):
    constraint = armature.pose.bones[owner].constraints.get(f"TCMOD_{module}__TC_{module}_ik")
    assert constraint is not None and constraint.type == "IK"
    assert constraint.chain_count == 2 and constraint.influence == 0.0
    assert constraint.target is not None and constraint.pole_target is not None

for control_name in ("hand_l_ik_ctrl", "foot_l_ik_ctrl"):
    control = bpy.data.objects[control_name]
    rotation = control.matrix_world.to_euler()
    assert max(abs(float(value)) for value in rotation) < 1.0e-6

foot_world = armature.matrix_world @ armature.pose.bones["foot_l"].head
toe_world = armature.matrix_world @ armature.pose.bones["toe_l"].head
assert abs(float(foot_world.z)) < 1.0e-6
assert abs(float(toe_world.z)) < 1.0e-6

for control in (
    "hand_l_ik_ctrl", "foot_l_ik_ctrl", "lip_main_ctrl",
    "c_upper_lip_main_ctrl", "c_lower_lip_main_ctrl",
):
    assert bpy.data.objects.get(control) is not None, control

edited = rig.execute("rig.edit_control_shape", {"control": "hand_l_ik_ctrl", "shape": "CUBE"})
assert edited["ok"] and bpy.data.objects["hand_l_ik_ctrl"].empty_display_type == "CUBE", edited

reverse_foot = rig.execute("rig.create_reverse_foot", {
    "ankle": "SmokeRig:foot_l", "ball": "SmokeRig:toe_l", "toe": "SmokeRig:toe_tip_l",
    "module": "smoke_reverse_foot",
})
assert reverse_foot["ok"] and len(reverse_foot["created_ids"]) == 5, reverse_foot

curve_data = bpy.data.curves.new("SmokePathData", type="CURVE")
curve_data.dimensions = "3D"
spline = curve_data.splines.new("POLY")
spline.points.add(1)
spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
spline.points[1].co = (4.0, 0.0, 0.0, 1.0)
curve = bpy.data.objects.new("SmokePath", curve_data)
bpy.context.scene.collection.objects.link(curve)
path_target = bpy.data.objects.new("SmokePathTarget", None)
bpy.context.scene.collection.objects.link(path_target)
motion_path = rig.execute("rig.create_motion_path", {"target": path_target.name, "curve": curve.name})
assert motion_path["ok"] and path_target.constraints[-1].type == "FOLLOW_PATH", motion_path

space_a = bpy.data.objects.new("SmokeSpaceA", None)
space_b = bpy.data.objects.new("SmokeSpaceB", None)
space_driven = bpy.data.objects.new("SmokeSpaceDriven", None)
for item in (space_a, space_b, space_driven):
    bpy.context.scene.collection.objects.link(item)
space_switch = rig.execute("rig.create_space_switch", {
    "driven": space_driven.name, "targets": [space_a.name, space_b.name],
    "names": ["World", "Chest"], "module": "smoke_space",
})
assert space_switch["ok"], space_switch
space_set = rig.execute("rig.set_space", {"space_switch": space_switch["data"]["space_switch"], "space": "Chest"})
assert space_set["ok"] and space_driven.constraints[-1].influence == 1.0, space_set

attachment_target = bpy.data.objects.new("SmokeAttachment", None)
bpy.context.scene.collection.objects.link(attachment_target)
attachment = rig.execute("rig.create_mesh_attachment", {
    "driven": attachment_target.name, "mesh": placement_mesh.name,
})
assert attachment["ok"] and attachment_target.constraints[-1].type == "SHRINKWRAP", attachment

pose_reader = rig.execute("rig.create_pose_reader", {
    "driver": "SmokeRig:upperarm_l", "axis": "x", "range": [0.0, 90.0], "name": "SmokePoseReader",
})
assert pose_reader["ok"] and bpy.data.objects["SmokePoseReader"].animation_data.drivers, pose_reader

stored = rig.execute("rig.store_connections", {"module": "left_arm"})
assert stored["ok"] and stored["data"]["connections"], stored
restored = rig.execute("rig.restore_connections", {"module": "left_arm"})
assert restored["ok"], restored

source_pose = {"LeftHand": rig._matrix_values(armature.matrix_world @ armature.pose.bones["hand_l"].matrix)}
preview_retarget = rig.execute("retarget.preview", {"source": source_pose, "target": definition})
assert preview_retarget["ok"], preview_retarget
baked = rig.execute("retarget.bake", {"source": source_pose, "target": definition, "range": [1, 1]})
assert baked["ok"] and baked["changed_ids"], baked
take = rig.execute("retarget.transfer_take", {"take": {"name": "SmokeTake"}, "target": definition})
assert take["ok"], take

removed = rig.execute("rig.remove_module", {"module": "mouth"})
assert removed["ok"] and bpy.data.objects.get("lip_main_ctrl") is None
ribbon_removed = rig.execute("rig.remove_module", {"module": "smoke_ribbon"})
assert ribbon_removed["ok"] and bpy.data.objects.get("smoke_ribbon_curve") is None
print("BLENDER_RIG_SMOKE_OK")
