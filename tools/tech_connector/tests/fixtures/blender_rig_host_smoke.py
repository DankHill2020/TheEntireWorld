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
    "UpperLipCenter": "SmokeRig:upper_lip", "LowerLipCenter": "SmokeRig:lower_lip",
    "LeftLipCorner": "SmokeRig:lip_l", "RightLipCorner": "SmokeRig:lip_r",
}
definition = CharacterDefinition("Smoke", slots=slots).to_dict()

for module in ("left_arm", "left_leg", "mouth"):
    result = rig.execute("rig.build_module", {"module": module, "definition": definition})
    assert result["ok"], result

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
    assert constraint.chain_count == 2 and constraint.influence == 1.0
    assert constraint.target is not None and constraint.pole_target is not None

for control in (
    "hand_l_ik_ctrl", "foot_l_ik_ctrl", "lip_main_ctrl",
    "c_upper_lip_main_ctrl", "c_lower_lip_main_ctrl",
):
    assert bpy.data.objects.get(control) is not None, control

removed = rig.execute("rig.remove_module", {"module": "mouth"})
assert removed["ok"] and bpy.data.objects.get("lip_main_ctrl") is None
ribbon_removed = rig.execute("rig.remove_module", {"module": "smoke_ribbon"})
assert ribbon_removed["ok"] and bpy.data.objects.get("smoke_ribbon_curve") is None
print("BLENDER_RIG_SMOKE_OK")
