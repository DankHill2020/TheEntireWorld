"""Render a time-labelled stick-pose contact sheet from a BVH animation."""

from __future__ import annotations

from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector


values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
if len(values) != 2:
    raise ValueError("Expected -- INPUT.bvh OUTPUT.png")
source, destination = map(lambda value: Path(value).resolve(), values)

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
frame_start, frame_end = (int(value) for value in action.frame_range)
fps = bpy.context.scene.render.fps


def material(name, color):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    return value


materials = {
    "left": material("Left", (0.1, 0.45, 0.95)),
    "right": material("Right", (0.95, 0.2, 0.15)),
    "center": material("Center", (0.1, 0.75, 0.3)),
    "root": material("Root", (1.0, 0.75, 0.05)),
    "text": material("Text", (0.05, 0.05, 0.05)),
}


def bone_material(name):
    if name in {"root", "01_09"}:
        return materials["root"]
    if name.startswith("l"):
        return materials["left"]
    if name.startswith("r"):
        return materials["right"]
    return materials["center"]


def add_segment(start, end, radius, value_material):
    delta = end - start
    length = delta.length
    if length < 0.002:
        return
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=radius, depth=length, location=(start + end) / 2)
    obj = bpy.context.object
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(delta.normalized())
    obj.data.materials.append(value_material)


columns, rows = 6, 4
sample_count = columns * rows
frames = [round(frame_start + index * (frame_end - frame_start) / (sample_count - 1)) for index in range(sample_count)]
cell_width, cell_height = 2.2, 2.8
for index, frame in enumerate(frames):
    bpy.context.scene.frame_set(frame)
    root = armature.pose.bones.get("root")
    origin = (armature.matrix_world @ root.matrix).translation if root else armature.location
    column, row = index % columns, index // columns
    offset = Vector((column * cell_width, 0.0, (rows - 1 - row) * cell_height)) - Vector((origin.x, 0.0, origin.z))
    for bone in armature.pose.bones:
        start = armature.matrix_world @ bone.head + offset
        end = armature.matrix_world @ bone.tail + offset
        add_segment(start, end, 0.035, bone_material(bone.name))
    label = bpy.data.curves.new(f"Label_{index}", type="FONT")
    label.body = f"{(frame - frame_start) / fps:04.1f}s"
    label.align_x = "CENTER"
    label.size = 0.25
    text = bpy.data.objects.new(f"Label_{index}", label)
    text.location = (column * cell_width, -0.05, (rows - 1 - row) * cell_height - 1.25)
    text.rotation_euler = (math.pi / 2, 0.0, 0.0)
    label.materials.append(materials["text"])
    bpy.context.collection.objects.link(text)

bpy.data.objects.remove(armature, do_unlink=True)
bpy.ops.object.camera_add(location=((columns - 1) * cell_width / 2, -25.0, (rows - 1) * cell_height / 2))
camera = bpy.context.object
camera.data.type = "ORTHO"
camera.data.ortho_scale = max(columns * cell_width, rows * cell_height) + 1.2
camera.rotation_euler = (math.pi / 2, 0.0, 0.0)
bpy.context.scene.camera = camera

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_shadows = False
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "WORLD"
if scene.world is None:
    scene.world = bpy.data.worlds.new("ContactSheetWorld")
scene.world.color = (0.92, 0.92, 0.92)
scene.render.resolution_x = 2400
scene.render.resolution_y = 1700
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(destination)
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.render.render(write_still=True)
print(f"AI_STUDIO_CONTACT_SHEET={destination}")
