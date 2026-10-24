"""Make a minimal skeletal FBX source revision for import/reimport qualification.

Run only on a disposable copy of a user-provided FBX. Never overwrite the input.
"""

from __future__ import annotations

import sys

import bpy


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:]
    if len(arguments) != 2:
        raise ValueError("Expected source and destination FBX paths after --.")
    source, destination = arguments
    if source == destination:
        raise ValueError("The destination must differ from the source FBX.")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=source, use_anim=True, ignore_leaf_bones=False)
    meshes = [item for item in bpy.data.objects if item.type == "MESH" and item.data.vertices]
    armatures = [item for item in bpy.data.objects if item.type == "ARMATURE"]
    if len(meshes) != 1 or len(armatures) != 1:
        raise ValueError("Qualification expects one mesh and one armature.")
    meshes[0].data.vertices[0].co.x += 0.0001
    bpy.ops.export_scene.fbx(
        filepath=destination, use_selection=False, add_leaf_bones=False,
        bake_anim=False, use_mesh_modifiers=False,
    )
    print("TC_FBX_REIMPORT_FIXTURE_OK")


if __name__ == "__main__":
    main()
