"""Build a Blender rig from a real Maya-exported mesh and joint hierarchy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))

from blender_tools.Rigging import rigging_host_adapter as rig  # noqa: E402
from tech_connector.services.dcc.rigging_workspace_service import (  # noqa: E402
    ALL_CHARACTER_SLOTS,
    CharacterDefinition,
)


arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(arguments) < 2:
    raise RuntimeError("Expected FBX and source snapshot paths after --")
fbx_path = Path(arguments[0]).resolve()
snapshot_path = Path(arguments[1]).resolve()
output_path = Path(arguments[2]).resolve() if len(arguments) > 2 else fbx_path.with_suffix(".blend")
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.fbx(filepath=str(fbx_path), use_anim=False)

armature = max(
    (obj for obj in bpy.data.objects if obj.type == "ARMATURE"),
    key=lambda obj: len(obj.data.bones),
)
mesh = max(
    (obj for obj in bpy.data.objects if obj.type == "MESH"),
    key=lambda obj: len(obj.data.vertices),
)
assert len(mesh.data.vertices) == int(snapshot["mesh"]["vertex_count"])
assert len(armature.data.bones) == len(snapshot["joints"])
assert any(modifier.type == "ARMATURE" for modifier in mesh.modifiers)

slots = {
    slot: f"{armature.name}:{bone_name}"
    for slot, bone_name in snapshot["slots"].items()
    if slot in ALL_CHARACTER_SLOTS and armature.data.bones.get(bone_name) is not None
}
definition = CharacterDefinition(
    "IndianWomanCrossDcc",
    slots=slots,
    source_provider="maya",
    source_root="origin",
).to_dict()
validation = rig.execute("definition.validate", {"mapping": definition})
assert validation["ok"], validation

preview = rig.execute("rig.place_joints", {
    "mesh": mesh.name,
    "definition": definition,
    "preview": True,
})
assert preview["ok"] and not preview["data"]["applied"], preview
placement = rig.execute("rig.place_joints", {
    "definition": definition,
    "positions": preview["data"]["positions"],
})
assert placement["ok"] and placement["data"]["applied"], placement
assert len(placement["changed_ids"]) == len(preview["data"]["positions"])

first_pose = rig.execute("rig.set_t_pose", {"definition": definition})
assert first_pose["ok"], first_pose
core_bones = [
    slots[key].split(":", 1)[1]
    for key in (
        "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
        "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
    )
]
pose_matrices = {name: armature.pose.bones[name].matrix.copy() for name in core_bones}
second_pose = rig.execute("rig.set_t_pose", {"definition": definition})
assert second_pose["ok"], second_pose
repeat_delta = max(
    abs(float(armature.pose.bones[name].matrix[row][column] - pose_matrices[name][row][column]))
    for name in core_bones
    for row in range(4)
    for column in range(4)
)
assert repeat_delta < 1.0e-5, repeat_delta

modules = [
    "root", "pelvis", "spine", "neck", "head",
    "left_arm", "right_arm", "left_leg", "right_leg", "fingers",
]
build = rig.execute("rig.build_full", {
    "definition": definition,
    "modules": modules,
})
assert build["ok"], build
assert build["data"]["t_pose"]["ok"], build
assert build["data"]["modules"] == modules
assert len(build["created_ids"]) >= len(modules)

for slot in ("LeftHand", "RightHand", "LeftFoot", "RightFoot"):
    bone_name = slots[slot].split(":", 1)[1]
    control = bpy.data.objects.get(bone_name + "_ik_ctrl")
    assert control is not None, bone_name
    assert max(abs(float(value)) for value in control.matrix_world.to_euler()) < 1.0e-5

for slot, module in (
    ("LeftForeArm", "left_arm"), ("RightForeArm", "right_arm"),
    ("LeftLeg", "left_leg"), ("RightLeg", "right_leg"),
):
    bone_name = slots[slot].split(":", 1)[1]
    constraint = armature.pose.bones[bone_name].constraints.get(f"TCMOD_{module}__TC_{module}_ik")
    assert constraint is not None and constraint.type == "IK", (slot, module)

for module, slots_for_limb in (
    ("left_arm", ("LeftArm", "LeftForeArm", "LeftHand")),
    ("right_arm", ("RightArm", "RightForeArm", "RightHand")),
    ("left_leg", ("LeftUpLeg", "LeftLeg", "LeftFoot")),
    ("right_leg", ("RightUpLeg", "RightLeg", "RightFoot")),
):
    for slot in slots_for_limb:
        bone_name = slots[slot].split(":", 1)[1]
        assert bpy.data.objects.get(f"{module}_{bone_name}_fk_ctrl") is not None
        constraint = armature.pose.bones[bone_name].constraints.get(
            f"TCMOD_{module}__TC_{module}_{bone_name}_fk"
        )
        assert constraint is not None and constraint.type == "COPY_TRANSFORMS"

bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
print("BLENDER_IMPORTED_CHARACTER_RIG_OK=" + json.dumps({
    "armature": armature.name,
    "bone_count": len(armature.data.bones),
    "changed_joint_count": len(placement["changed_ids"]),
    "control_count": len(build["created_ids"]),
    "mesh": mesh.name,
    "output": str(output_path),
    "repeat_t_pose_delta": repeat_delta,
    "vertex_count": len(mesh.data.vertices),
}, sort_keys=True))
