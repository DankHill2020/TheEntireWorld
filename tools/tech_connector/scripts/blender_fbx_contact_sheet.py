"""Render major-bone poses from an Unreal-exported animation FBX."""

from pathlib import Path
import math
import sys

import bpy
from mathutils import Vector


values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
if len(values) != 2:
    raise ValueError("Expected -- INPUT.fbx OUTPUT.png")
source, destination = map(lambda value: Path(value).resolve(), values)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source), use_anim=True)
armature = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE")
action = next(iter(bpy.data.actions))
imported_objects = list(bpy.context.scene.objects)
frame_start, frame_end = (int(value) for value in action.frame_range)
fps = bpy.context.scene.render.fps


def make_material(name, color):
    value = bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    return value


materials = {
    "left": make_material("Left", (0.1, 0.45, 0.95)),
    "right": make_material("Right", (0.95, 0.2, 0.15)),
    "center": make_material("Center", (0.1, 0.75, 0.3)),
    "text": make_material("Text", (0.05, 0.05, 0.05)),
}


def material_for(name):
    base_name = name.split(":")[-1]
    if base_name.endswith("_l"):
        return materials["left"]
    if base_name.endswith("_r"):
        return materials["right"]
    return materials["center"]


major = {
    "pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05",
    "neck_01", "neck_02", "head", "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l",
    "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r", "thigh_l", "calf_l", "foot_l",
    "ball_l", "thigh_r", "calf_r", "foot_r", "ball_r",
}
links = (
    ("pelvis", "spine_01"), ("spine_01", "spine_02"), ("spine_02", "spine_03"),
    ("spine_03", "spine_04"), ("spine_04", "spine_05"), ("spine_05", "neck_01"),
    ("neck_01", "neck_02"), ("neck_02", "head"),
    ("spine_05", "clavicle_l"), ("clavicle_l", "upperarm_l"),
    ("upperarm_l", "lowerarm_l"), ("lowerarm_l", "hand_l"),
    ("spine_05", "clavicle_r"), ("clavicle_r", "upperarm_r"),
    ("upperarm_r", "lowerarm_r"), ("lowerarm_r", "hand_r"),
    ("pelvis", "thigh_l"), ("thigh_l", "calf_l"), ("calf_l", "foot_l"),
    ("foot_l", "ball_l"), ("pelvis", "thigh_r"), ("thigh_r", "calf_r"),
    ("calf_r", "foot_r"), ("foot_r", "ball_r"),
)


def add_segment(start, end, value_material):
    delta = end - start
    length = delta.length
    if length < 0.002:
        return
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.035, depth=length, location=(start + end) / 2)
    obj = bpy.context.object
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(delta.normalized())
    obj.data.materials.append(value_material)


columns, rows = 6, 4
frames = [round(frame_start + index * (frame_end - frame_start) / 23) for index in range(24)]
cell_width, cell_height = 2.2, 2.8
for index, frame in enumerate(frames):
    bpy.context.scene.frame_set(frame)
    pelvis = next(bone for bone in armature.pose.bones if bone.name.split(":")[-1] == "pelvis")
    origin = (armature.matrix_world @ pelvis.matrix).translation
    column, row = index % columns, index // columns
    offset = Vector((column * cell_width, 0.0, (rows - 1 - row) * cell_height)) - Vector((origin.x, 0.0, origin.z))
    bones = {bone.name.split(":")[-1]: bone for bone in armature.pose.bones}
    for parent_name, child_name in links:
        parent = bones.get(parent_name)
        child = bones.get(child_name)
        if not parent or not child:
            continue
        add_segment(
            armature.matrix_world @ parent.head + offset,
            armature.matrix_world @ child.head + offset,
            material_for(child.name),
        )
    label = bpy.data.curves.new(f"Label_{index}", type="FONT")
    label.body = f"{(frame - frame_start) / fps:04.1f}s"
    label.align_x = "CENTER"
    label.size = 0.25
    text = bpy.data.objects.new(f"Label_{index}", label)
    text.location = (column * cell_width, -0.05, (rows - 1 - row) * cell_height - 1.25)
    text.rotation_euler = (math.pi / 2, 0.0, 0.0)
    label.materials.append(materials["text"])
    bpy.context.collection.objects.link(text)

for imported in imported_objects:
    bpy.data.objects.remove(imported, do_unlink=True)
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
