"""Render two pose snapshots from a baked skeletal FBX for visual QA."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy
from mathutils import Vector


def main() -> None:
    source, output = (Path(arg).resolve() for arg in sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True, ignore_leaf_bones=False)
    mesh = next(obj for obj in bpy.data.objects if obj.type == "MESH")
    corners = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
    lower = Vector(tuple(min(point[axis] for point in corners) for axis in range(3)))
    upper = Vector(tuple(max(point[axis] for point in corners) for axis in range(3)))
    center = (lower + upper) / 2
    span = max(upper - lower)
    camera_data = bpy.data.cameras.new("QA Camera")
    camera = bpy.data.objects.new("QA Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((span * 0.3, -span * 2.5, span * 0.55))
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = span * 1.35
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.render.resolution_x = 600
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100
    output.mkdir(parents=True, exist_ok=True)
    for label, position in (
        ("front", center + Vector((span * 0.3, -span * 2.5, span * 0.55))),
        ("side", center + Vector((span * 2.5, -span * 0.3, span * 0.55))),
    ):
        camera.location = position
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        for frame in (1, 16):
            scene.frame_set(frame)
            scene.render.filepath = str(output / f"{label}_pose_{frame:02d}.png")
            bpy.ops.render.render(write_still=True)
            print(f"TC_RETARGET_PREVIEW {scene.render.filepath}")


if __name__ == "__main__":
    main()
