"""Inspect an Unreal-exported FBX animation in a clean Blender process."""

from pathlib import Path
import json
import sys

import bpy


values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
if len(values) != 1:
    raise ValueError("Expected -- INPUT.fbx")
source = Path(values[0]).resolve()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
actions = list(bpy.data.actions)
reference_span = []
if armatures:
    points = [
        armatures[0].matrix_world @ point
        for bone in armatures[0].pose.bones
        for point in (bone.head, bone.tail)
    ]
    reference_span = [max(point[i] for point in points) - min(point[i] for point in points) for i in range(3)]
pose_samples = []
if armatures and actions:
    armature = armatures[0]
    action = actions[0]
    major_names = {
        "pelvis", "spine_01", "spine_05", "head", "upperarm_l", "lowerarm_l", "hand_l",
        "upperarm_r", "lowerarm_r", "hand_r", "thigh_l", "calf_l", "foot_l",
        "thigh_r", "calf_r", "foot_r",
    }
    for frame in (int(action.frame_range[0]), int(sum(action.frame_range) / 2), int(action.frame_range[1])):
        bpy.context.scene.frame_set(frame)
        points = [
            armature.matrix_world @ point
            for bone in armature.pose.bones
            if bone.name.split(":")[-1] in major_names
            for point in (bone.head, bone.tail)
        ]
        pelvis = next((bone for bone in armature.pose.bones if bone.name.split(":")[-1] == "pelvis"), None)
        if points and pelvis:
            pose_samples.append({
                "frame": frame,
                "span_xyz": [max(point[i] for point in points) - min(point[i] for point in points) for i in range(3)],
                "pelvis": list((armature.matrix_world @ pelvis.matrix).translation),
            })
print(
    "AI_STUDIO_FBX_PROBE="
    + json.dumps(
        {
            "ok": len(armatures) == 1 and bool(actions),
            "source": str(source),
            "armatures": [
                {
                    "name": obj.name,
                    "bone_count": len(obj.data.bones),
                    "bones": [bone.name for bone in obj.data.bones],
                }
                for obj in armatures
            ],
            "meshes": [{"name": obj.name, "vertices": len(obj.data.vertices)} for obj in meshes],
            "actions": [
                {
                    "name": action.name,
                    "frame_range": list(action.frame_range),
                    "slots": len(action.slots),
                }
                for action in actions
            ],
            "scene_fps": bpy.context.scene.render.fps,
            "reference_span_xyz": reference_span,
            "mesh_dimensions": [list(obj.dimensions) for obj in meshes],
            "pose_samples": pose_samples,
        }
    )
)
