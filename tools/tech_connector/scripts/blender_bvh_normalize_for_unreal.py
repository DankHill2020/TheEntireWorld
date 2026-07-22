"""Normalize a BVH hierarchy and export matching Unreal source/animation FBXs."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
if len(values) not in {3, 5}:
    raise ValueError(
        "Expected -- INPUT.bvh SOURCE.fbx ANIMATION.fbx [ARMATURE_ROOT_NAME MOTION_ROOT_NAME]"
    )
source = Path(values[0]).resolve()
source_fbx = Path(values[1]).resolve()
animation_fbx = Path(values[2]).resolve()
armature_root_name = values[3] if len(values) == 5 else "root"
motion_root_name = values[4] if len(values) == 5 else "pelvis"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_anim.bvh(
    filepath=str(source),
    global_scale=(1.0 / 0.45) * 0.0254,
    frame_start=1,
    use_fps_scale=False,
    update_scene_fps=True,
)
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
action = armature.animation_data.action
armature.name = armature_root_name
armature.data.name = armature_root_name + "_Skeleton"
source_motion_root = armature.data.bones.get("root")
if not source_motion_root:
    raise RuntimeError("BVH did not contain expected motion bone: root")
source_motion_root.name = motion_root_name

vertices = []
faces = []
weights = {}
for bone in armature.data.bones:
    center = bone.head_local
    start = len(vertices)
    radius = 0.002
    vertices.extend(
        (
            tuple(center + Vector((radius, 0.0, 0.0))),
            tuple(center + Vector((0.0, radius, 0.0))),
            tuple(center + Vector((0.0, 0.0, radius))),
        )
    )
    faces.append((start, start + 1, start + 2))
    weights[bone.name] = [start, start + 1, start + 2]
mesh_data = bpy.data.meshes.new("AIStudio_SourceSkeletonCarrier")
mesh_data.from_pydata(vertices, [], faces)
carrier = bpy.data.objects.new("AIStudio_SourceSkeletonCarrier", mesh_data)
bpy.context.collection.objects.link(carrier)
for bone_name, indices in weights.items():
    carrier.vertex_groups.new(name=bone_name).add(indices, 1.0, "REPLACE")
modifier = carrier.modifiers.new(name="SourceSkeleton", type="ARMATURE")
modifier.object = armature
carrier.parent = armature

frame_start, frame_end = (int(value) for value in action.frame_range)
bpy.context.scene.frame_start = frame_start
bpy.context.scene.frame_end = frame_end


def export(path: Path, include_mesh: bool):
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    if include_mesh:
        carrier.hide_set(False)
        carrier.select_set(True)
    else:
        carrier.hide_set(True)
    bpy.context.view_layer.objects.active = armature
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"} if include_mesh else {"ARMATURE"},
        axis_forward="-Y",
        axis_up="Z",
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        bake_anim_simplify_factor=0.0,
        use_armature_deform_only=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
    )


export(source_fbx, True)
export(animation_fbx, False)
print(
    "AI_STUDIO_NORMALIZE="
    + json.dumps(
        {
            "ok": source_fbx.exists() and animation_fbx.exists(),
            "source_fbx": str(source_fbx),
            "animation_fbx": str(animation_fbx),
            "source_bytes": source_fbx.stat().st_size,
            "animation_bytes": animation_fbx.stat().st_size,
            "armature_root_name": armature_root_name,
            "motion_root_name": motion_root_name,
            "frame_range": [frame_start, frame_end],
            "fps": bpy.context.scene.render.fps,
            "bones": [bone.name for bone in armature.data.bones],
        }
    )
)
