"""Pump an isolated Blender bridge while the parent benchmark runs a pipeline."""

import importlib
import os
import time

import bpy


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
if os.environ.get("TC_BLENDER_BENCHMARK_MESHES") in {"two_props", "three_props"}:
    bpy.ops.mesh.primitive_cube_add(location=(-2, 0, 0))
    bpy.context.object.name = "Crate_A"
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, location=(2, 0, 0))
    bpy.context.object.name = "Barrel_B"
    if os.environ.get("TC_BLENDER_BENCHMARK_MESHES") == "three_props":
        bpy.ops.mesh.primitive_cone_add(vertices=16, location=(0, 3, 0))
        bpy.context.object.name = "Cone_C"
else:
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.object.name = "Demo Prompt Cube"

bridge = importlib.import_module("the_entire_world_ai_studio_bridge")
deadline = time.monotonic() + 90.0
print("TC_LIVE_BENCHMARK_HOST_READY", flush=True)
while time.monotonic() < deadline:
    bridge._process_jobs()
    time.sleep(0.005)
