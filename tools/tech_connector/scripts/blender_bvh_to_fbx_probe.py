"""Import a BVH in Blender, measure it, and export a source-skeleton FBX."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


def _args() -> tuple[Path, Path, str]:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(values) not in {2, 3}:
        raise ValueError("Expected -- INPUT.bvh OUTPUT.fbx [source_skeleton|animation_only]")
    return Path(values[0]).resolve(), Path(values[1]).resolve(), values[2] if len(values) == 3 else "source_skeleton"


source, destination, export_mode = _args()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_anim.bvh(
    filepath=str(source),
    global_scale=(1.0 / 0.45) * 0.0254,
    frame_start=1,
    use_fps_scale=False,
    update_scene_fps=True,
)
armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
if len(armatures) != 1:
    raise RuntimeError(f"Expected one imported armature, found {len(armatures)}")
armature = armatures[0]
action = armature.animation_data.action if armature.animation_data else None
if action is None:
    raise RuntimeError("BVH import produced no animation action")

# Unreal cannot establish a new Skeleton from an armature-only FBX. Add a tiny
# triangulated carrier mesh with one weighted triangle per deform bone. It exists
# only to make source-skeleton ingestion explicit and is never a gameplay mesh.
vertices = []
faces = []
weighted_vertices = {}
for bone in armature.data.bones:
    center = bone.head_local
    start = len(vertices)
    radius = 0.002
    vertices.extend(
        (
            tuple(center + __import__("mathutils").Vector((radius, 0.0, 0.0))),
            tuple(center + __import__("mathutils").Vector((0.0, radius, 0.0))),
            tuple(center + __import__("mathutils").Vector((0.0, 0.0, radius))),
        )
    )
    faces.append((start, start + 1, start + 2))
    weighted_vertices[bone.name] = [start, start + 1, start + 2]
mesh_data = bpy.data.meshes.new("AIStudio_SourceSkeletonCarrier")
mesh_data.from_pydata(vertices, [], faces)
mesh_data.update()
carrier = bpy.data.objects.new("AIStudio_SourceSkeletonCarrier", mesh_data)
bpy.context.collection.objects.link(carrier)
for bone_name, indices in weighted_vertices.items():
    carrier.vertex_groups.new(name=bone_name).add(indices, 1.0, "REPLACE")
modifier = carrier.modifiers.new(name="SourceSkeleton", type="ARMATURE")
modifier.object = armature
carrier.parent = armature
if export_mode == "animation_only":
    bpy.data.objects.remove(carrier, do_unlink=True)

frame_start, frame_end = (int(value) for value in action.frame_range)
bpy.context.scene.frame_start = frame_start
bpy.context.scene.frame_end = frame_end
root = armature.pose.bones.get("root")
samples = []
for frame in sorted({frame_start, (frame_start + frame_end) // 2, frame_end}):
    bpy.context.scene.frame_set(frame)
    matrix = armature.matrix_world @ root.matrix if root else armature.matrix_world
    samples.append({"frame": frame, "location_m": [round(value, 6) for value in matrix.translation]})

bpy.context.view_layer.objects.active = armature
armature.select_set(True)
if export_mode != "animation_only":
    carrier.select_set(True)
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.fbx(
    filepath=str(destination),
    use_selection=True,
    object_types={"ARMATURE"} if export_mode == "animation_only" else {"ARMATURE", "MESH"},
    add_leaf_bones=False,
    bake_anim=True,
    bake_anim_use_all_actions=False,
    bake_anim_use_nla_strips=False,
    bake_anim_simplify_factor=0.0,
    use_armature_deform_only=False,
    apply_unit_scale=True,
)

print(
    "AI_STUDIO_PROBE="
    + json.dumps(
        {
            "ok": destination.exists() and destination.stat().st_size > 0,
            "source": str(source),
            "destination": str(destination),
            "export_mode": export_mode,
            "fbx_bytes": destination.stat().st_size if destination.exists() else 0,
            "armature": armature.name,
            "bone_count": len(armature.data.bones),
            "bones": [bone.name for bone in armature.data.bones],
            "frame_start": frame_start,
            "frame_end": frame_end,
            "scene_fps": bpy.context.scene.render.fps,
            "duration_seconds": round((frame_end - frame_start) / bpy.context.scene.render.fps, 3),
            "root_samples": samples,
        }
    )
)
