"""Blender-side scene extraction entry point used by native_fbx_service.

The filename is retained for packaged-install compatibility.  The worker now
normalizes every scene format Blender can import into the same typed buffers.
"""

from __future__ import annotations

import argparse
import array
import json
import os
from pathlib import Path
import sys


def _matrix_values(matrix):
    return [float(value) for row in matrix for value in row]


def _material_payload(material):
    payload = {
        "name": material.name,
        "base_color": [float(value) for value in material.diffuse_color],
        "metallic": float(getattr(material, "metallic", 0.0)),
        "roughness": float(getattr(material, "roughness", 0.5)),
        "textures": {},
        "source_provider": "blender_import",
        "source_shader": "viewport_material",
        "source_graph": {"nodes": [], "links": []},
        "unsupported_nodes": [],
    }
    if not material.use_nodes or material.node_tree is None:
        return payload
    tree = material.node_tree
    supported_node_types = {
        "BSDF_PRINCIPLED", "BUMP", "CURVE_RGB", "EMISSION", "FRESNEL", "GAMMA",
        "HUE_SAT", "INVERT", "MAPPING", "MATH", "MIX", "MIX_RGB", "NORMAL_MAP",
        "OUTPUT_MATERIAL", "RGB", "SEPARATE_COLOR", "TEX_COORD", "TEX_IMAGE", "VALUE",
        "VECT_MATH",
    }
    unsupported = set()
    graph_nodes = []
    for node in tree.nodes:
        inputs = {}
        for socket in getattr(node, "inputs", []) or []:
            if getattr(socket, "is_linked", False):
                continue
            value = _json_value(getattr(socket, "default_value", None))
            if value is not None:
                inputs[str(socket.name)] = value
        graph_nodes.append({
            "name": str(node.name),
            "label": str(getattr(node, "label", "") or ""),
            "type": str(getattr(node, "type", "") or ""),
            "bl_idname": str(getattr(node, "bl_idname", "") or ""),
            "inputs": inputs,
        })
        node_type = str(getattr(node, "type", "") or "")
        if node_type and node_type not in supported_node_types:
            unsupported.add(node_type)
        if node_type == "BSDF_PRINCIPLED":
            payload["source_shader"] = "principled_bsdf"
            _copy_shader_input(node, payload, "base_color", ("Base Color",))
            _copy_shader_input(node, payload, "metallic", ("Metallic",))
            _copy_shader_input(node, payload, "roughness", ("Roughness",))
            _copy_shader_input(node, payload, "ior", ("IOR",))
            _copy_shader_input(node, payload, "opacity", ("Alpha",))
            _copy_shader_input(node, payload, "transmission", ("Transmission Weight", "Transmission"))
            _copy_shader_input(node, payload, "clearcoat", ("Coat Weight", "Clearcoat"))
            _copy_shader_input(node, payload, "coat_roughness", ("Coat Roughness", "Clearcoat Roughness"))
            _copy_shader_input(node, payload, "emission_color", ("Emission Color", "Emission"))
            _copy_shader_input(node, payload, "emission_strength", ("Emission Strength",))
    payload["source_graph"] = {
        "nodes": graph_nodes,
        "links": [
            {
                "from_node": str(link.from_node.name),
                "from_socket": str(link.from_socket.name),
                "to_node": str(link.to_node.name),
                "to_socket": str(link.to_socket.name),
            }
            for link in tree.links
        ],
    }
    payload["unsupported_nodes"] = sorted(unsupported)
    for node in tree.nodes:
        image = getattr(node, "image", None)
        if image is None:
            continue
        path = str(Path(image.filepath_from_user()).resolve()) if image.filepath else ""
        channel = _image_texture_channel(node)
        color_space = str(getattr(getattr(image, "colorspace_settings", None), "name", "") or "")
        payload["textures"][channel] = {
            "path": path,
            "color_space": color_space,
            "source_node": str(node.name),
        }
    return payload


def _json_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    try:
        values = list(value)
    except TypeError:
        return None
    if len(values) > 16:
        return None
    try:
        return [float(item) for item in values]
    except (TypeError, ValueError):
        return None


def _copy_shader_input(node, payload, target, names):
    for name in names:
        socket = node.inputs.get(name)
        if socket is None:
            continue
        value = _json_value(getattr(socket, "default_value", None))
        if value is not None:
            payload[target] = value
        return


def _image_texture_channel(node):
    queue = list(getattr(node, "outputs", []) or [])
    visited = set()
    while queue:
        socket = queue.pop(0)
        for link in getattr(socket, "links", []) or []:
            target_node = link.to_node
            target_socket = str(link.to_socket.name or "").lower()
            key = (str(target_node.name), target_socket)
            if key in visited:
                continue
            visited.add(key)
            if "base color" in target_socket or target_socket == "color" and target_node.type == "BSDF_PRINCIPLED":
                return "base_color"
            if "roughness" in target_socket:
                return "specular_roughness"
            if "metallic" in target_socket or "metalness" in target_socket:
                return "metalness"
            if "emission" in target_socket:
                return "emission_color"
            if "alpha" in target_socket or "opacity" in target_socket:
                return "opacity"
            if target_node.type in {"NORMAL_MAP", "BUMP"}:
                return "normal" if target_node.type == "NORMAL_MAP" else "displacement"
            queue.extend(list(getattr(target_node, "outputs", []) or []))
    label = str(getattr(node, "label", "") or node.name or "image").lower()
    return label.replace(" ", "_")


def _armature_has_animation(obj, *, file_has_actions: bool = False) -> bool:
    animation_data = getattr(obj, "animation_data", None)
    if animation_data is not None:
        if getattr(animation_data, "action", None) is not None:
            return True
        if any(not bool(getattr(track, "mute", False)) for track in getattr(animation_data, "nla_tracks", []) or []):
            return True
        if getattr(animation_data, "drivers", None):
            return True
    return bool(file_has_actions) or any(
        getattr(pose_bone, "constraints", None) for pose_bone in obj.pose.bones
    )


def _animation_frame_range(scene, actions):
    ranges = [
        tuple(float(value) for value in action.frame_range)
        for action in actions
        if getattr(action, "frame_range", None) is not None
    ]
    if not ranges:
        return int(scene.frame_start), int(scene.frame_end)
    import math

    return (
        int(math.floor(min(value[0] for value in ranges))),
        int(math.ceil(max(value[1] for value in ranges))),
    )


def _append_armature_pose_caches(
    scene,
    armature_objects,
    armatures,
    floats,
    *,
    frame_start,
    frame_end,
    file_has_actions,
):
    frame_count = max(0, frame_end - frame_start + 1)
    maximum_bytes = max(
        16 * 1024 * 1024,
        int(float(os.environ.get("TECH_CONNECTOR_NATIVE_FBX_MAX_POSE_CACHE_MB", "512")) * 1024 * 1024),
    )
    original_frame = int(scene.frame_current)
    try:
        for obj, armature in zip(armature_objects, armatures):
            joint_count = len(armature.get("bones") or [])
            required_bytes = frame_count * joint_count * 16 * 4
            if frame_count <= 1 or joint_count <= 0 or not _armature_has_animation(
                obj,
                file_has_actions=file_has_actions,
            ):
                armature["pose_cache"] = {
                    "available": False,
                    "reason": "static_armature",
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                }
                continue
            if required_bytes > maximum_bytes:
                armature["pose_cache"] = {
                    "available": False,
                    "reason": "size_limit",
                    "required_bytes": required_bytes,
                    "maximum_bytes": maximum_bytes,
                    "frame_start": frame_start,
                    "frame_end": frame_end,
                }
                continue
            matrix_float_offset = len(floats)
            bone_names = [str(item.get("name") or "") for item in armature.get("bones") or []]
            for frame in range(frame_start, frame_end + 1):
                scene.frame_set(frame)
                for bone_name in bone_names:
                    pose_bone = obj.pose.bones.get(bone_name)
                    matrix = obj.matrix_world @ pose_bone.matrix if pose_bone is not None else obj.matrix_world
                    floats.extend(float(value) for row in matrix for value in row)
            armature["pose_cache"] = {
                "available": True,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "frame_count": frame_count,
                "joint_count": joint_count,
                "matrix_float_offset": matrix_float_offset,
                "matrix_layout": "frame_joint_world_column_major_rows",
                "sample_step": 1,
            }
    finally:
        scene.frame_set(original_frame)


def _clear_factory_scene(bpy) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _import_source_scene(bpy, input_path: str):
    extension = Path(input_path).suffix.lower()
    if extension == ".fbx":
        return bpy.ops.import_scene.fbx(filepath=input_path, use_anim=True, ignore_leaf_bones=False)
    if extension in {".gltf", ".glb"}:
        return bpy.ops.import_scene.gltf(filepath=input_path)
    if extension in {".usd", ".usda", ".usdc", ".usdz"}:
        return bpy.ops.wm.usd_import(filepath=input_path)
    if extension == ".abc":
        return bpy.ops.wm.alembic_import(filepath=input_path)
    if extension == ".obj":
        operation = getattr(bpy.ops.wm, "obj_import", None)
        return operation(filepath=input_path) if operation else bpy.ops.import_scene.obj(filepath=input_path)
    if extension == ".stl":
        operation = getattr(bpy.ops.wm, "stl_import", None)
        return operation(filepath=input_path) if operation else bpy.ops.import_mesh.stl(filepath=input_path)
    raise ValueError(f"Unsupported scene extension: {extension or '<none>'}")


def extract(input_path: str, manifest_path: str, float_path: str, uint_path: str) -> None:
    import bpy

    _clear_factory_scene(bpy)
    status = _import_source_scene(bpy, input_path)
    if "FINISHED" not in status:
        raise RuntimeError(f"Blender scene import did not finish: {status}")

    floats = array.array("f")
    integers = array.array("I")
    armatures = []
    armature_objects = []
    armature_bones: dict[str, dict[str, int]] = {}
    for obj in bpy.context.scene.objects:
        if obj.type != "ARMATURE" or obj.data is None:
            continue
        bones = []
        bone_index = {}
        for index, bone in enumerate(obj.data.bones):
            bone_index[bone.name] = index
            bones.append({
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else "",
                "matrix_local": _matrix_values(bone.matrix_local),
                "head_local": [float(value) for value in bone.head_local],
                "tail_local": [float(value) for value in bone.tail_local],
                "use_deform": bool(bone.use_deform),
            })
        armature_bones[obj.name_full] = bone_index
        pose_constraints = []
        for pose_bone in obj.pose.bones:
            for constraint in pose_bone.constraints:
                target = getattr(constraint, "target", None)
                pose_constraints.append({
                    "bone": pose_bone.name,
                    "name": constraint.name,
                    "type": constraint.type,
                    "target_object": target.name_full if target else "",
                    "subtarget": str(getattr(constraint, "subtarget", "") or ""),
                    "influence": float(getattr(constraint, "influence", 1.0)),
                    "mute": bool(getattr(constraint, "mute", False)),
                })
        armatures.append({
            "native_id": obj.name_full,
            "name": obj.name,
            "world_matrix": _matrix_values(obj.matrix_world),
            "bones": bones,
            "constraints": pose_constraints,
        })
        armature_objects.append(obj)

    meshes = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        position_offset = len(floats)
        for vertex in mesh.vertices:
            floats.extend(float(value) for value in vertex.co)
        index_offset = len(integers)
        loop_index_offset = len(integers)
        triangle_indices = []
        triangle_loops = []
        for triangle in mesh.loop_triangles:
            triangle_indices.extend(int(value) for value in triangle.vertices)
            triangle_loops.extend(int(value) for value in triangle.loops)
        integers.extend(triangle_indices)
        loop_index_offset = len(integers)
        integers.extend(triangle_loops)
        uv_offset = len(floats)
        uv_layer = mesh.uv_layers.active.data if mesh.uv_layers.active is not None else None
        if uv_layer is not None:
            for loop_index in triangle_loops:
                uv = uv_layer[loop_index].uv
                floats.extend((float(uv.x), float(uv.y)))

        armature_object = None
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and getattr(modifier, "object", None) is not None:
                armature_object = modifier.object
                break
        bone_lookup = armature_bones.get(armature_object.name_full if armature_object else "", {})
        group_to_bone = {
            group.index: bone_lookup[group.name]
            for group in obj.vertex_groups
            if group.name in bone_lookup
        }
        influence_offset_offset = len(integers)
        influence_counts = []
        joint_indices = []
        skin_weights = []
        for vertex in mesh.vertices:
            count = 0
            for group in vertex.groups:
                joint_index = group_to_bone.get(group.group)
                if joint_index is None or float(group.weight) <= 0.0:
                    continue
                joint_indices.append(int(joint_index))
                skin_weights.append(float(group.weight))
                count += 1
            influence_counts.append(count)
        integers.append(0)
        running = 0
        for count in influence_counts:
            running += count
            integers.append(running)
        joint_index_offset = len(integers)
        integers.extend(joint_indices)
        weight_offset = len(floats)
        floats.extend(skin_weights)
        materials = [
            _material_payload(slot.material)
            for slot in obj.material_slots
            if slot.material is not None
        ]
        meshes.append({
            "native_id": obj.name_full,
            "name": obj.name,
            "world_matrix": _matrix_values(obj.matrix_world),
            "vertex_count": len(mesh.vertices),
            "triangle_count": len(triangle_indices) // 3,
            "position_float_offset": position_offset,
            "triangle_index_offset": index_offset,
            "triangle_loop_index_offset": loop_index_offset,
            "uv_float_offset": uv_offset,
            "has_uvs": uv_layer is not None,
            "armature_id": armature_object.name_full if armature_object else "",
            "influence_offset_offset": influence_offset_offset,
            "joint_index_offset": joint_index_offset,
            "weight_float_offset": weight_offset,
            "influence_count": len(skin_weights),
            "max_influences_per_vertex": max(influence_counts or [0]),
            "materials": materials,
        })

    actions = []
    for action in bpy.data.actions:
        channels = []
        for curve in getattr(action, "fcurves", []) or []:
            channels.append({
                "data_path": curve.data_path,
                "array_index": int(curve.array_index),
                "keyframes": [
                    {
                        "frame": float(point.co.x),
                        "value": float(point.co.y),
                        "interpolation": str(point.interpolation),
                    }
                    for point in curve.keyframe_points
                ],
            })
        actions.append({"name": action.name, "frame_range": [float(value) for value in action.frame_range], "channels": channels})

    frame_start, frame_end = _animation_frame_range(bpy.context.scene, list(bpy.data.actions))
    _append_armature_pose_caches(
        bpy.context.scene,
        armature_objects,
        armatures,
        floats,
        frame_start=frame_start,
        frame_end=frame_end,
        file_has_actions=bool(bpy.data.actions),
    )

    with open(float_path, "wb") as stream:
        floats.tofile(stream)
    with open(uint_path, "wb") as stream:
        integers.tofile(stream)
    manifest = {
        "schema": "tech_connector.native_scene_asset.v1",
        "source_path": str(Path(input_path).resolve()),
        "source_format": Path(input_path).suffix.lower().lstrip("."),
        "fps": float(bpy.context.scene.render.fps) / max(1.0e-6, float(bpy.context.scene.render.fps_base)),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "unit_scale": float(bpy.context.scene.unit_settings.scale_length),
        "armatures": armatures,
        "meshes": meshes,
        "actions": actions,
    }
    Path(manifest_path).write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--floats", required=True)
    parser.add_argument("--uints", required=True)
    options = parser.parse_args(arguments)
    extract(options.input, options.manifest, options.floats, options.uints)


if __name__ == "__main__":
    main()
