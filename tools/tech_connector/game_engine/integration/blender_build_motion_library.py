"""Bake KayKit's CC0 medium-rig motions onto an FBX humanoid.

Run headless: blender -b --python blender_build_motion_library.py -- KAYKIT_DIR TARGET.fbx OUTPUT_DIR
The original FBX is never modified. Each output is a skinned FBX containing one action.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
from math import radians

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from blender_tools.Rigging import rigging_host_adapter as retarget  # noqa: E402


MAP = {
    "hips": "pelvis", "spine": "spine1", "chest": "spine5", "head": "head1",
    "upperarm.l": "l_upperarm", "lowerarm.l": "l_lowerarm", "wrist.l": "l_hand",
    "upperarm.r": "r_upperarm", "lowerarm.r": "r_lowerarm", "wrist.r": "r_hand",
    "upperleg.l": "l_thigh", "lowerleg.l": "l_knee", "foot.l": "l_ankle", "toes.l": "l_toe",
    "upperleg.r": "r_thigh", "lowerleg.r": "r_knee", "foot.r": "r_ankle", "toes.r": "r_toe",
}
CLIPS = {
    "idle": ("General", "Idle_A", "stand", True),
    "walk": ("MovementBasic", "Walking_A", "stand", True),
    "run": ("MovementBasic", "Running_A", "stand", True),
    "walk_back": ("MovementAdvanced", "Walking_Backwards", "stand", True),
    "strafe_left": ("MovementAdvanced", "Running_Strafe_Left", "stand", True),
    "strafe_right": ("MovementAdvanced", "Running_Strafe_Right", "stand", True),
    "jump_start": ("MovementBasic", "Jump_Start", "air", False),
    "jump_air": ("MovementBasic", "Jump_Idle", "air", True),
    "jump_land": ("MovementBasic", "Jump_Land", "air", False),
    "crouch_idle": ("MovementAdvanced", "Crouching", "crouch", True),
    "crouch_move": ("MovementAdvanced", "Sneaking", "crouch", True),
    "crawl_idle": ("MovementAdvanced", "Crawling", "crawl", True),
    "crawl": ("MovementAdvanced", "Crawling", "crawl", True),
}


def _place_crawl_contact(armature, upper_name: str, lower_name: str,
                         hand_name: str, floor_height: float) -> None:
    """Use a small CCD pass to put a crawling limb near the support plane."""
    hand = armature.pose.bones[hand_name]
    desired = (armature.matrix_world @ hand.matrix).translation.copy()
    desired.z = floor_height
    world_to_armature = armature.matrix_world.inverted_safe()
    for _ in range(8):
        for joint_name in (lower_name, upper_name):
            joint = armature.pose.bones[joint_name]
            joint_world = armature.matrix_world @ joint.matrix
            pivot = joint_world.translation
            current = (armature.matrix_world @ hand.matrix).translation - pivot
            target = desired - pivot
            if current.length < 1.0e-6 or target.length < 1.0e-6:
                continue
            rotation = current.rotation_difference(target)
            rotated = (Matrix.Translation(pivot) @ rotation.to_matrix().to_4x4()
                       @ Matrix.Translation(-pivot) @ joint_world)
            joint.matrix = world_to_armature @ rotated
            bpy.context.view_layer.update()


def _lower_crawl_shoulders(armature) -> None:
    spine = armature.pose.bones["spine1"]
    world = armature.matrix_world @ spine.matrix
    pivot = world.translation
    rotated = (Matrix.Translation(pivot) @ Matrix.Rotation(radians(35.0), 4, "X")
               @ Matrix.Translation(-pivot) @ world)
    spine.matrix = armature.matrix_world.inverted_safe() @ rotated
    bpy.context.view_layer.update()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(source_dir: Path, target_path: Path, output_dir: Path) -> dict:
    source_dir, target_path, output_dir = (p.resolve() for p in (source_dir, target_path, output_dir))
    source_hash = sha256(target_path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sources = {}
    source_files = {}
    for category in sorted({item[0] for item in CLIPS.values()}):
        path = source_dir / f"Rig_Medium_{category}.glb"
        if not path.is_file():
            raise FileNotFoundError(path)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(path))
        arms = [obj for obj in bpy.data.objects if obj not in before and obj.type == "ARMATURE"]
        if len(arms) != 1:
            raise ValueError(f"Expected one source armature in {path}")
        sources[category] = arms[0]
        source_files[category] = {"path": str(path), "sha256": sha256(path)}
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(target_path), use_anim=True, ignore_leaf_bones=False)
    arms = [obj for obj in bpy.data.objects if obj not in before and obj.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError("Expected one target FBX armature")
    target = arms[0]
    meshes = [obj for obj in bpy.data.objects if obj not in before and obj.type == "MESH"]
    if not meshes:
        raise ValueError("Target FBX has no skinned meshes")
    for category, source in sources.items():
        missing = [name for name in MAP if name not in source.pose.bones]
        if missing:
            raise ValueError(f"Missing KayKit {category} bones: {missing}")
    missing = [name for name in MAP.values() if name not in target.pose.bones]
    if missing:
        raise ValueError(f"Missing target bones: {missing}")
    definition_result = retarget._op_retarget_create_definition({"mapping": {
        "name": "KayKit_Medium_to_SKM_Test",
        "slots": {source_name: f"{target.name}:{target_name}"
                  for source_name, target_name in MAP.items()},
    }})
    if not definition_result["ok"]:
        raise RuntimeError(definition_result)
    definition = definition_result["data"]["definition"]
    scene = bpy.context.scene
    scene.render.fps = 30
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "tech_connector.retargeted_motion_library.v1",
        "source": "KayKit Character Animations 1.1, CC0",
        "source_url": "https://kaylousberg.itch.io/kaykit-character-animations",
        "source_files": source_files,
        "target_path": str(target_path), "target_sha256": source_hash,
        "target_bones": len(target.pose.bones), "mapped_bones": len(MAP),
        "output_dir": str(output_dir), "clips": {},
    }
    for clip_id, (category, action_name, stance, loop) in CLIPS.items():
        source = sources[category]
        action = bpy.data.actions.get(action_name)
        if action is None:
            raise ValueError(f"KayKit action missing: {action_name}")
        source.animation_data_create()
        source.animation_data.action = action
        if action.slots:
            source.animation_data.action_slot = action.slots[0]
        target.animation_data_clear()
        target.animation_data_create()
        for pose in target.pose.bones:
            pose.rotation_mode = "QUATERNION"
            pose.matrix_basis.identity()
        frames = 2 if clip_id == "crawl_idle" else max(2, round(action.frame_range[1] - action.frame_range[0]) + 1)
        scene.frame_start, scene.frame_end = 0, frames - 1
        root_samples = []
        endpoint_samples = []
        pose_features = []
        for frame in range(frames):
            scene.frame_set(0 if clip_id == "crawl_idle" else frame)
            for pose in target.pose.bones:
                pose.matrix_basis.identity()
            bpy.context.view_layer.update()
            for source_name, target_name in MAP.items():
                source_pose = source.pose.bones[source_name]
                target_pose = target.pose.bones[target_name]
                target_parent = target_pose.parent
                target_rest_local = (target_parent.bone.matrix_local.inverted_safe()
                                     @ target_pose.bone.matrix_local if target_parent
                                     else target_pose.bone.matrix_local.copy())
                source_rest_world = (source.matrix_world @ source_pose.bone.matrix_local).to_quaternion()
                target_rest_world = (target.matrix_world @ target_pose.bone.matrix_local).to_quaternion()
                delta_world = (source_rest_world @ source_pose.matrix_basis.to_quaternion()
                               @ source_rest_world.inverted())
                target_basis = target_rest_world.inverted() @ delta_world @ target_rest_world
                basis = target_basis.to_matrix().to_4x4()
                if source_name == "hips":
                    displacement_world = (source.matrix_world.to_quaternion() @ source_rest_world
                                          @ source_pose.matrix_basis.translation)
                    # Root translation is in-place; retain vertical crouch/jump displacement.
                    displacement_world.x = 0.0
                    displacement_world.y = 0.0
                    local_displacement = (target_rest_world.inverted() @ displacement_world)
                    local_displacement /= target.matrix_world.to_scale().x
                    basis.translation = local_displacement
                desired = ((target_parent.matrix if target_parent else Matrix.Identity(4))
                           @ target_rest_local @ basis)
                desired_world = target.matrix_world @ desired
                solved = retarget._op_retarget_solve_pose({
                    "target": {"name": definition["name"], "slots": {
                        source_name: definition["slots"][source_name]}},
                    "source": {source_name: retarget._matrix_values(desired_world)},
                })
                if not solved["ok"]:
                    raise RuntimeError(f"{clip_id} frame {frame} {source_name}: {solved}")
            if stance == "crawl":
                _lower_crawl_shoulders(target)
            if stance != "air":
                contacts = ("l_hand", "r_hand", "l_ankle", "r_ankle") if stance == "crawl" else ("l_ankle", "r_ankle")
                floor_height = 0.045 if stance == "crawl" else 0.07
                actual = min((target.matrix_world @ target.pose.bones[name].matrix).translation.z
                             for name in contacts)
                correction = floor_height - actual
                pelvis = target.pose.bones["pelvis"]
                pelvis_rest_world = (target.matrix_world @ pelvis.bone.matrix_local).to_quaternion()
                pelvis.location += ((pelvis_rest_world.inverted() @ Vector((0.0, 0.0, correction)))
                                    / target.matrix_world.to_scale().x)
                bpy.context.view_layer.update()
            if stance == "crawl":
                _place_crawl_contact(target, "l_upperarm", "l_lowerarm", "l_hand", 0.055)
                _place_crawl_contact(target, "r_upperarm", "r_lowerarm", "r_hand", 0.055)
                _place_crawl_contact(target, "l_thigh", "l_knee", "l_ankle", 0.055)
                _place_crawl_contact(target, "r_thigh", "r_knee", "r_ankle", 0.055)
            for target_name in MAP.values():
                pose = target.pose.bones[target_name]
                pose.keyframe_insert("location", frame=frame)
                pose.keyframe_insert("rotation_quaternion", frame=frame)
                pose.keyframe_insert("scale", frame=frame)
            bpy.context.view_layer.update()
            root_samples.append(round(float((target.matrix_world @ target.pose.bones["pelvis"].matrix).translation.z), 5))
            endpoint_samples.append([round(float((target.matrix_world @ target.pose.bones[name].matrix).translation.z), 5)
                                     for name in ("l_hand", "r_hand", "l_ankle", "r_ankle")])
            pelvis_world = (target.matrix_world @ target.pose.bones["pelvis"].matrix).translation
            pose_features.append({"frame": frame, "pelvis_height": round(float(pelvis_world.z), 5),
                                  "joints": {name: [round(float(axis), 5) for axis in
                                                    ((target.matrix_world @ target.pose.bones[name].matrix).translation
                                                     - pelvis_world)]
                                             for name in ("l_hand", "r_hand", "l_ankle", "r_ankle")}})
        target.animation_data.action.name = f"TC_{clip_id}"
        bpy.ops.object.select_all(action="DESELECT")
        for obj in [target, *meshes]:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = target
        output = output_dir / f"SKM_Test_{clip_id}.fbx"
        bpy.ops.export_scene.fbx(
            filepath=str(output), use_selection=True, object_types={"ARMATURE", "MESH"},
            add_leaf_bones=False, bake_anim=True, bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
            bake_anim_simplify_factor=0.0, use_mesh_modifiers=False,
        )
        report["clips"][clip_id] = {
            "path": str(output), "sha256": sha256(output), "source_action": action_name,
            "stance": stance, "loop": loop, "frames": frames, "fps": 30,
            "pelvis_height_range_m": [min(root_samples), max(root_samples)],
            "endpoint_height_range_m": [min(map(min, endpoint_samples)), max(map(max, endpoint_samples))],
            "pose_features": pose_features,
        }
        print("TC_MOTION_CLIP " + json.dumps({"clip": clip_id, "frames": frames, "path": str(output)}), flush=True)
    if sha256(target_path) != source_hash:
        raise RuntimeError("Source target FBX changed during baking")
    (output_dir / "motion_library_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        raise SystemExit("Expected KayKit Rig_Medium GLB directory, target FBX, output directory")
    result = build(*(Path(value) for value in args))
    print("TC_MOTION_LIBRARY_OK " + str(len(result["clips"])), flush=True)
