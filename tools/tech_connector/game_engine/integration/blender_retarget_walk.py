"""Bake a humanoid walk onto a different FBX armature in headless Blender.

The solve is routed through Tech Connector's Blender retarget host adapter.
Sagittal leg motion and opposite-arm swing are transferred from the source
walk while keeping the target's own limb lengths and bind translations.
Root translation is omitted for an in-place cycle suitable for locomotion.

Usage: blender -b --python blender_retarget_walk.py -- source.glb target.fbx output.fbx report.json
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector


REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from blender_tools.Rigging import rigging_host_adapter as retarget  # noqa: E402


SOURCE_TO_TARGET = (
    ("Reference", "root", "origin"),
    ("Hips", "hips", "pelvis"),
    ("Spine", "spine1", "spine1"),
    ("Spine1", "spine2", "spine3"),
    ("Spine2", "chest", "spine5"),
    ("Neck", "neck", "neck1"),
    ("Neck1", "neck.001", "neck2"),
    ("Head", "head.001", "head1"),
    ("LeftShoulder", "shoulder.L", "l_clavicle"),
    ("LeftArm", "upper_arm.L", "l_upperarm"),
    ("LeftForeArm", "forearm.L", "l_lowerarm"),
    ("LeftHand", "hand.L", "l_hand"),
    ("RightShoulder", "shoulder.R", "r_clavicle"),
    ("RightArm", "upper_arm.R", "r_upperarm"),
    ("RightForeArm", "forearm.R", "r_lowerarm"),
    ("RightHand", "hand.R", "r_hand"),
    ("LeftUpLeg", "thigh.L", "l_thigh"),
    ("LeftLeg", "shin.L", "l_knee"),
    ("LeftFoot", "foot.L", "l_ankle"),
    ("LeftToeBase", "toe.L", "l_toe"),
    ("RightUpLeg", "thigh.R", "r_thigh"),
    ("RightLeg", "shin.R", "r_knee"),
    ("RightFoot", "foot.R", "r_ankle"),
    ("RightToeBase", "toe.R", "r_toe"),
)


def _bone_local(matrix: Matrix, parent: Matrix | None) -> Matrix:
    return parent.inverted_safe() @ matrix if parent is not None else matrix.copy()


def _rotation_only(matrix: Matrix) -> Matrix:
    return matrix.to_quaternion().to_matrix().to_4x4()


def _armature(objects: set[str]) -> bpy.types.Object:
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.name not in objects]
    if len(armatures) != 1:
        raise ValueError(f"Expected one newly imported armature, found {len(armatures)}")
    return armatures[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def retarget_walk(source_path: Path, target_path: Path, output_path: Path, report_path: Path) -> dict:
    if output_path.resolve() in {source_path.resolve(), target_path.resolve()}:
        raise ValueError("Retarget output must not overwrite either input")
    input_hashes = (_sha256(source_path), _sha256(target_path))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source_path))
    source = _armature(set())
    before = {obj.name for obj in bpy.data.objects}
    bpy.ops.import_scene.fbx(filepath=str(target_path), use_anim=True, ignore_leaf_bones=False)
    target = _armature(before)
    action = bpy.data.actions.get("walking_nogun-cycle")
    if action is None:
        raise ValueError("Source has no walking_nogun-cycle action")
    source.animation_data_create()
    source.animation_data.action = action
    if action.slots:
        source.animation_data.action_slot = action.slots[0]

    missing = [f"{slot}: {src}->{dst}" for slot, src, dst in SOURCE_TO_TARGET
               if src not in source.pose.bones or dst not in target.pose.bones]
    if missing:
        raise ValueError("Missing retarget bones: " + ", ".join(missing))
    definition = {"name": "SKM_Test_Walk", "slots": {
        slot: f"{target.name}:{dst}" for slot, _, dst in SOURCE_TO_TARGET
    }}
    created = retarget._op_retarget_create_definition({"mapping": definition})
    if not created["ok"]:
        raise RuntimeError(created["message"])
    definition = created["data"]["definition"]

    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start = 0
    scene.frame_end = 30
    scene.frame_set(0)
    source_reference = {}
    source_swing_reference = {}
    for slot, source_name, _ in SOURCE_TO_TARGET:
        pose = source.pose.bones[source_name]
        parent = pose.parent
        source_reference[slot] = _rotation_only(_bone_local(
            pose.matrix, parent.matrix if parent else None,
        ))
        source_swing_reference[slot] = pose.matrix_basis.to_euler().x
    target.animation_data_create()
    target.animation_data.action = None
    for _, _, target_name in SOURCE_TO_TARGET:
        target.pose.bones[target_name].rotation_mode = "QUATERNION"
    samples = {}
    arm_diagnostics = {}
    for frame in range(31):
        scene.frame_set(frame)
        for bone in target.pose.bones:
            bone.matrix_basis.identity()
        bpy.context.view_layer.update()
        for slot, source_name, target_name in SOURCE_TO_TARGET:
            source_pose = source.pose.bones[source_name]
            target_pose = target.pose.bones[target_name]
            source_parent = source_pose.parent
            source_pose_local = _bone_local(
                source_pose.matrix, source_parent.matrix if source_parent else None,
            )
            delta = _rotation_only(source_pose_local) @ source_reference[slot].inverted_safe()
            weight = 0.0
            delta = Quaternion((1, 0, 0, 0)).slerp(delta.to_quaternion(), weight).to_matrix().to_4x4()
            target_parent = target_pose.parent
            target_rest_local = _bone_local(
                target_pose.bone.matrix_local,
                target_parent.bone.matrix_local if target_parent else None,
            )
            if slot in {"LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg"}:
                source_swing = source_pose.matrix_basis.to_euler().x - source_swing_reference[slot]
                swing_weight = 0.42 if slot.endswith("UpLeg") else 0.4
                parent_rest_rotation = (target_parent.bone.matrix_local.to_quaternion()
                                        if target_parent else Quaternion((1, 0, 0, 0)))
                swing_world = Quaternion((1, 0, 0), source_swing * swing_weight)
                swing_parent = parent_rest_rotation.inverted() @ swing_world @ parent_rest_rotation
                delta = swing_parent.to_matrix().to_4x4()
            elif slot in {"LeftArm", "RightArm"}:
                opposite = "RightUpLeg" if slot == "LeftArm" else "LeftUpLeg"
                opposite_name = "thigh.R" if slot == "LeftArm" else "thigh.L"
                source_swing = (source.pose.bones[opposite_name].matrix_basis.to_euler().x
                                - source_swing_reference[opposite])
                parent_rest_rotation = (target_parent.bone.matrix_local.to_quaternion()
                                        if target_parent else Quaternion((1, 0, 0, 0)))
                swing_world = Quaternion((1, 0, 0), -source_swing * 0.3)
                swing_parent = parent_rest_rotation.inverted() @ swing_world @ parent_rest_rotation
                delta = swing_parent.to_matrix().to_4x4()
            arm_lowering = Matrix.Identity(4)
            if slot in {"LeftArm", "RightArm"}:
                parent_rest_rotation = (target_parent.bone.matrix_local.to_quaternion()
                                        if target_parent else Quaternion((1, 0, 0, 0)))
                child_name = "l_lowerarm" if slot == "LeftArm" else "r_lowerarm"
                rest_direction = (parent_rest_rotation.inverted() @ (
                    target.pose.bones[child_name].bone.head_local - target_pose.bone.head_local
                )).normalized()
                down_in_parent = parent_rest_rotation.inverted() @ Vector((0, -1, 0))
                arm_lowering = rest_direction.rotation_difference(down_in_parent).to_matrix().to_4x4()
                if frame == 0:
                    arm_diagnostics[slot] = {
                        "lowering_degrees": round(arm_lowering.to_quaternion().angle * 57.295779513, 3),
                        "rest_direction": list(rest_direction),
                        "desired_direction": list(down_in_parent),
                    }
            desired_local = (Matrix.Translation(target_rest_local.translation)
                             @ delta @ arm_lowering @ _rotation_only(target_rest_local))
            parent_pose = target_parent.matrix if target_parent else Matrix.Identity(4)
            desired_world = target.matrix_world @ parent_pose @ desired_local
            solved = retarget._op_retarget_solve_pose({
                "target": {"name": definition["name"], "slots": {slot: definition["slots"][slot]}},
                "source": {slot: retarget._matrix_values(desired_world)},
            })
            if not solved["ok"] or not solved["changed_ids"]:
                raise RuntimeError(f"Retarget solve failed at {frame} for {slot}: {solved}")
            if frame == 0 and slot in arm_diagnostics:
                arm_diagnostics[slot]["solved_head"] = list(target_pose.head)
                arm_diagnostics[slot]["solved_tail"] = list(target_pose.tail)
        for _, _, target_name in SOURCE_TO_TARGET:
            pose = target.pose.bones[target_name]
            pose.keyframe_insert("location", frame=frame)
            pose.keyframe_insert("rotation_quaternion", frame=frame)
            pose.keyframe_insert("scale", frame=frame)
        bpy.context.view_layer.update()
        if frame == 0:
            for slot, name in (("LeftArm", "l_upperarm"), ("RightArm", "r_upperarm")):
                arm_diagnostics[slot]["final_tail"] = list(target.pose.bones[name].tail)
                arm_diagnostics[slot]["rotation_quaternion"] = list(target.pose.bones[name].rotation_quaternion)
                arm_diagnostics[slot]["basis_quaternion"] = list(target.pose.bones[name].matrix_basis.to_quaternion())
        samples[frame] = {
            name: [round(float(v), 6) for v in target.pose.bones[name].head]
            for name in ("l_hand", "r_hand", "l_ankle", "r_ankle")
        }
    if not target.animation_data or not target.animation_data.action:
        raise RuntimeError("Retarget generated no Blender action")
    target.animation_data.action.name = "TC_Walk_Retarget"
    movement = max(
        sum((samples[frame][name][axis] - samples[0][name][axis]) ** 2 for axis in range(3)) ** 0.5
        for frame in samples for name in samples[0]
    )
    if movement < 0.05:
        raise RuntimeError(f"Retargeted endpoints did not move enough: {movement:.6f}")

    bpy.ops.object.select_all(action="DESELECT")
    export_objects = [target] + [obj for obj in bpy.data.objects
                                 if obj.type == "MESH" and obj.name not in before]
    for obj in export_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = target
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(output_path), use_selection=True, object_types={"ARMATURE", "MESH"},
        add_leaf_bones=False, bake_anim=True, bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_simplify_factor=0.0, use_mesh_modifiers=False,
    )
    if input_hashes != (_sha256(source_path), _sha256(target_path)):
        raise RuntimeError("Retarget unexpectedly changed an input asset")
    report = {
        "source": str(source_path), "target": str(target_path), "output": str(output_path),
        "source_sha256": input_hashes[0], "target_sha256": input_hashes[1],
        "output_sha256": _sha256(output_path), "inputs_unchanged": True,
        "source_action": action.name, "blender_action": "TC_Walk_Retarget",
        "source_attribution": {
            "creator": "Juan Linietsky and Fernando Miguel Calabro",
            "repository": "https://github.com/godotengine/tps-demo",
            "asset_path": "player/model/player.glb",
            "license": "CC-BY-3.0",
            "license_url": "https://github.com/godotengine/tps-demo/blob/master/LICENSE.md",
        },
        "frames": 31, "frame_rate": 30, "mapped_bones": len(SOURCE_TO_TARGET),
        "motion_driven_bones": 6,
        "target_bones": len(target.pose.bones), "exported_meshes": len(export_objects) - 1,
        "maximum_endpoint_movement": movement,
        "arm_diagnostics": arm_diagnostics,
        "endpoint_samples": {str(frame): samples[frame] for frame in (0, 8, 15, 23, 30)},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 4:
        raise SystemExit("Expected source GLB, target FBX, output FBX, and report JSON")
    result = retarget_walk(*(Path(arg).resolve() for arg in args))
    print("TC_RETARGET_OK " + json.dumps({k: result[k] for k in
          ("frames", "mapped_bones", "target_bones", "maximum_endpoint_movement")}))
