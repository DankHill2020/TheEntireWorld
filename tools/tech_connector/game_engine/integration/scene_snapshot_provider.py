"""Scene snapshot helpers for federated DCC viewport providers."""

from __future__ import annotations

import json
from typing import Any


def parse_scene_snapshot_output(raw: str, provider_id: str) -> tuple[bool, dict[str, Any] | str]:
    """Parse a provider JSON snapshot response."""
    try:
        data = json.loads(str(raw or "{}"))
    except Exception as exc:
        return False, f"Could not parse {provider_id} scene snapshot JSON: {exc}\n{raw}"
    if not isinstance(data, dict):
        return False, f"{provider_id} scene snapshot returned {type(data).__name__}, expected object."
    data.setdefault("provider_id", provider_id)
    data.setdefault("schema", "tech_connector.scene_snapshot.v1")
    return True, data


def blender_scene_snapshot_code(
    *,
    selected_only: bool = False,
    include_geometry: bool = True,
    include_materials: bool = True,
    limit: int = 500,
    max_vertices_per_object: int = 50000,
    max_faces_per_object: int = 50000,
    binary_path: str = "",
) -> str:
    return f"""
import array
import json
import mathutils
import os
import bpy

selected_only = {bool(selected_only)!r}
include_geometry = {bool(include_geometry)!r}
include_materials = {bool(include_materials)!r}
limit = int({int(limit)!r})
max_vertices_per_object = int({int(max_vertices_per_object)!r})
max_faces_per_object = int({int(max_faces_per_object)!r})
binary_path = {str(binary_path or "")!r}
geometry_binary = bytearray()

def _append_binary_array(values):
    byte_offset = len(geometry_binary)
    raw = values.tobytes()
    geometry_binary.extend(raw)
    return byte_offset, len(values)

def _vec(values):
    return [float(v) for v in values]

def _bbox_world(obj):
    corners = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return [float(min(xs)), float(min(ys)), float(min(zs)), float(max(xs)), float(max(ys)), float(max(zs))]

def _mesh_geometry(obj):
    if not include_geometry or obj.type != "MESH":
        return None
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = None
    try:
        mesh = eval_obj.to_mesh()
        if len(mesh.vertices) > max_vertices_per_object or len(mesh.polygons) > max_faces_per_object:
            return {{
                "representation": "bounds",
                "reason": "mesh_too_large",
                "vertex_count": len(mesh.vertices),
                "face_count": len(mesh.polygons),
            }}
        polygons = [poly for poly in mesh.polygons if len(poly.vertices) >= 3]
        if not mesh.vertices or not polygons:
            return None
        if binary_path:
            mesh.transform(eval_obj.matrix_world)
            vertices = array.array("f", [0.0]) * (len(mesh.vertices) * 3)
            mesh.vertices.foreach_get("co", vertices)
            face_counts = array.array("I", (len(poly.vertices) for poly in polygons))
            face_indices = array.array("I", (int(index) for poly in polygons for index in poly.vertices))
            vertex_byte_offset, vertex_float_count = _append_binary_array(vertices)
            face_count_byte_offset, face_count_count = _append_binary_array(face_counts)
            face_index_byte_offset, face_index_count = _append_binary_array(face_indices)
            geometry = {{
                "representation": "mesh",
                "vertex_encoding": "f32-file-array",
                "vertex_byte_offset": vertex_byte_offset,
                "vertex_float_count": vertex_float_count,
                "vertex_count": len(mesh.vertices),
                "face_encoding": "u32-file-counts-indices",
                "face_count_byte_offset": face_count_byte_offset,
                "face_count_count": face_count_count,
                "face_index_byte_offset": face_index_byte_offset,
                "face_index_count": face_index_count,
                "face_count": len(polygons),
                "shape_names": [obj.data.name if obj.data else obj.name],
            }}
        else:
            vertices = []
            for vert in mesh.vertices:
                p = eval_obj.matrix_world @ vert.co
                vertices.append([float(p.x), float(p.y), float(p.z)])
            faces = [[int(i) for i in poly.vertices] for poly in polygons]
            geometry = {{
                "representation": "mesh",
                "vertices": vertices,
                "faces": faces,
                "shape_names": [obj.data.name if obj.data else obj.name],
            }}
        uv_layer = mesh.uv_layers.active if include_materials and mesh.uv_layers else None
        if uv_layer is not None:
            geometry["active_uv_set"] = str(uv_layer.name)
            if binary_path:
                uvs = array.array("f", [0.0]) * (len(uv_layer.data) * 2)
                uv_layer.data.foreach_get("uv", uvs)
                face_uv_indices = array.array(
                    "I",
                    (int(loop_index) for poly in polygons for loop_index in poly.loop_indices),
                )
                uv_byte_offset, uv_float_count = _append_binary_array(uvs)
                face_uv_byte_offset, face_uv_index_count = _append_binary_array(face_uv_indices)
                geometry.update({{
                    "uv_encoding": "f32-file-array",
                    "uv_byte_offset": uv_byte_offset,
                    "uv_float_count": uv_float_count,
                    "face_uv_encoding": "u32-file-indices",
                    "face_uv_byte_offset": face_uv_byte_offset,
                    "face_uv_index_count": face_uv_index_count,
                }})
            else:
                geometry["uvs"] = [
                    [float(loop.uv.x), float(loop.uv.y)]
                    for loop in uv_layer.data
                ]
                geometry["face_uv_indices"] = [
                    [int(loop_index) for loop_index in poly.loop_indices]
                    for poly in polygons
                ]
        return geometry
    finally:
        if mesh is not None:
            eval_obj.to_mesh_clear()

def _material_payload(mat):
    if not include_materials:
        return None
    if mat is None:
        return None
    color = list(getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0)))
    roughness = float(getattr(mat, "roughness", 0.5))
    metalness = float(getattr(mat, "metallic", 0.0))
    specular = float(getattr(mat, "specular_intensity", 0.5))
    opacity = float(getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0))[3])
    transmission = 0.0
    ior = float(getattr(mat, "ior", 1.5))
    clearcoat = 0.0
    emission_color = [0.0, 0.0, 0.0]
    texture_paths = {{}}

    def _input(node, names, fallback):
        for name in names:
            socket = node.inputs.get(name)
            if socket is not None:
                return socket.default_value
        return fallback

    def _image_path(node, names):
        for name in names:
            socket = node.inputs.get(name)
            if socket is None or not socket.is_linked:
                continue
            source = socket.links[0].from_node
            image = getattr(source, "image", None)
            if source.type == "TEX_IMAGE" and image is not None and image.filepath:
                return os.path.abspath(bpy.path.abspath(image.filepath))
        return ""

    try:
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type != "BSDF_PRINCIPLED":
                    continue
                color = list(_input(node, ("Base Color",), color))
                roughness = float(_input(node, ("Roughness",), roughness))
                metalness = float(_input(node, ("Metallic",), metalness))
                specular = float(_input(node, ("Specular IOR Level", "Specular"), specular))
                opacity = float(_input(node, ("Alpha",), opacity))
                transmission = float(_input(node, ("Transmission Weight", "Transmission"), transmission))
                ior = float(_input(node, ("IOR",), ior))
                clearcoat = float(_input(node, ("Coat Weight", "Clearcoat"), clearcoat))
                emission = list(_input(node, ("Emission Color", "Emission"), emission_color))
                emission_color = [float(emission[0]), float(emission[1]), float(emission[2])]
                for key, names in (
                    ("base_color", ("Base Color",)),
                    ("roughness", ("Roughness",)),
                    ("metalness", ("Metallic",)),
                    ("normal", ("Normal",)),
                    ("emission", ("Emission Color", "Emission")),
                    ("opacity", ("Alpha",)),
                ):
                    path = _image_path(node, names)
                    if path:
                        texture_paths[key] = path
                break
    except Exception:
        pass
    return {{
        "name": mat.name,
        "source_material_id": mat.name_full,
        "source_shader": "blender_material",
        "color": [float(color[0]), float(color[1]), float(color[2]), float(color[3] if len(color) > 3 else 1.0)],
        "roughness": max(0.0, min(1.0, roughness)),
        "metalness": max(0.0, min(1.0, metalness)),
        "specular": max(0.0, min(1.0, specular)),
        "opacity": max(0.0, min(1.0, opacity)),
        "transmission": max(0.0, min(1.0, transmission)),
        "ior": max(1.0, min(3.0, ior)),
        "clearcoat": max(0.0, min(1.0, clearcoat)),
        "emission_color": emission_color,
        "texture_paths": texture_paths,
    }}

def _light_payload(obj):
    data = getattr(obj, "data", None)
    if obj.type != "LIGHT" or data is None:
        return None
    color = list(getattr(data, "color", (1.0, 1.0, 1.0)))
    return {{
        "kind": str(getattr(data, "type", "POINT")),
        "color": [float(color[0]), float(color[1]), float(color[2])],
        "intensity": float(getattr(data, "energy", 10.0)) / 10.0,
        "cone_angle": float(getattr(data, "spot_size", 0.785398)),
    }}

def _viewport_capture_payload():
    window = getattr(bpy.context, "window", None)
    screen = getattr(window, "screen", None)
    areas = list(getattr(screen, "areas", []) or [])
    view_areas = [area for area in areas if area.type == "VIEW_3D" and area.width > 1 and area.height > 1]
    if not view_areas:
        return None
    area = max(view_areas, key=lambda candidate: int(candidate.width) * int(candidate.height))
    screen_width = max([int(candidate.x) + int(candidate.width) for candidate in areas] or [int(area.width)])
    screen_height = max([int(candidate.y) + int(candidate.height) for candidate in areas] or [int(area.height)])
    if screen_width <= 1 or screen_height <= 1:
        return None
    return {{
        "area_type": "VIEW_3D",
        "aspect_ratio": float(area.width) / max(1.0, float(area.height)),
        "pixel_size": [int(area.width), int(area.height)],
        "viewport_rect": [
            max(0.0, min(1.0, float(area.x) / screen_width)),
            max(0.0, min(1.0, float(screen_height - area.y - area.height) / screen_height)),
            max(0.0, min(1.0, float(area.width) / screen_width)),
            max(0.0, min(1.0, float(area.height) / screen_height)),
        ],
    }}

source = list(bpy.context.selected_objects) if selected_only else list(bpy.context.scene.objects)
objects = []
for obj in source[:limit]:
    try:
        if obj.hide_get() or obj.hide_viewport:
            continue
        bbox = _bbox_world(obj)
        item = {{
            "native_id": obj.name_full,
            "name": obj.name,
            "type": obj.type.lower(),
            "shape_types": [obj.type.lower()],
            "bbox": bbox,
            "translation": _vec(obj.matrix_world.translation),
            "rotation": _vec(obj.rotation_euler),
            "scale": _vec(obj.scale),
            "visible": True,
        }}
        geometry = _mesh_geometry(obj)
        if geometry:
            item["geometry"] = geometry
        materials = []
        material_assignments = []
        for slot_index, slot in enumerate(getattr(obj, "material_slots", ()) or ()):
            material = _material_payload(slot.material)
            if not material:
                continue
            material["slot_index"] = int(slot_index)
            materials.append(material)
            face_indices = []
            try:
                face_indices = [
                    int(poly.index) for poly in obj.data.polygons
                    if int(poly.material_index) == int(slot_index)
                ]
            except Exception:
                pass
            material_assignments.append({{
                "material_id": material["source_material_id"],
                "slot_index": int(slot_index),
                "face_indices": face_indices,
                "uv_set": str(geometry.get("active_uv_set") or "") if geometry else "",
                "assignment_topology": "source_mesh",
            }})
        if materials:
            item["material"] = materials[0]
            item["materials"] = materials
            item["material_assignments"] = material_assignments
        light = _light_payload(obj)
        if light:
            item["light"] = light
        objects.append(item)
    except Exception as exc:
        objects.append({{"native_id": obj.name_full, "name": obj.name, "type": "error", "error": str(exc)}})

cameras = []
render = bpy.context.scene.render
camera_aspect_ratio = (
    max(1.0, float(render.resolution_x) * float(render.pixel_aspect_x))
    / max(1.0, float(render.resolution_y) * float(render.pixel_aspect_y))
)
for obj in bpy.context.scene.objects:
    if obj.type != "CAMERA":
        continue
    cam = obj.data
    cameras.append({{
        "native_id": obj.name_full,
        "name": obj.name,
        "type": "camera",
        "translation": _vec(obj.matrix_world.translation),
        "rotation": _vec(obj.rotation_euler),
        "focal_length_mm": float(cam.lens),
        "aspect_ratio": float(camera_aspect_ratio),
        "near_clip": float(cam.clip_start),
        "far_clip": float(cam.clip_end),
        "visible": not obj.hide_get(),
    }})

payload = {{
    "schema": "tech_connector.blender.scene_snapshot.v1",
    "provider_id": "blender",
    "process_id": int(os.getpid()),
    "scene": bpy.data.filepath or "",
    "scene_modified": bool(bpy.data.is_dirty),
    "application_version": str(bpy.app.version_string),
    "unit_linear": str(bpy.context.scene.unit_settings.system),
    "up_axis": "z",
    "current_time": float(bpy.context.scene.frame_current),
    "frame_start": float(bpy.context.scene.frame_start),
    "frame_end": float(bpy.context.scene.frame_end),
    "fps": float(render.fps) / max(1.0e-8, float(render.fps_base)),
    "selection": [obj.name_full for obj in bpy.context.selected_objects],
    "objects": objects,
    "cameras": cameras,
    "active_camera": bpy.context.scene.camera.name_full if bpy.context.scene.camera else "",
    "viewport_capture": _viewport_capture_payload(),
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": include_geometry,
        "include_materials": include_materials,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
if binary_path:
    with open(binary_path, "wb") as binary_file:
        binary_file.write(geometry_binary)
print(json.dumps(payload))
"""


def motionbuilder_scene_snapshot_code(*, selected_only: bool = False, limit: int = 500) -> str:
    return f"""
import json
import os
from pyfbsdk import FBSystem, FBModelList, FBGetSelectedModels, FBCamera

selected_only = {bool(selected_only)!r}
limit = int({int(limit)!r})

def _vec(values):
    return [float(values[i]) for i in range(3)]

def _scalar(value, fallback):
    try:
        return float(value.Data if hasattr(value, "Data") else value)
    except Exception:
        return float(fallback)

def _bbox_from_model(model):
    try:
        box_min = model.BoundingBoxMin
        box_max = model.BoundingBoxMax
        return [float(box_min[0]), float(box_min[1]), float(box_min[2]), float(box_max[0]), float(box_max[1]), float(box_max[2])]
    except Exception:
        try:
            t = model.Translation.Data
            return [float(t[0])-1.0, float(t[1])-1.0, float(t[2])-1.0, float(t[0])+1.0, float(t[1])+1.0, float(t[2])+1.0]
        except Exception:
            return [0, 0, 0, 0, 0, 0]

scene = FBSystem().Scene
selected = FBModelList()
FBGetSelectedModels(selected)
source = list(selected) if selected_only else [c for c in scene.Components if hasattr(c, "Translation")]

objects = []
for model in source[:limit]:
    try:
        name = model.LongName or model.Name
        item = {{
            "native_id": name,
            "name": model.Name,
            "type": model.ClassName() if hasattr(model, "ClassName") else model.__class__.__name__,
            "shape_types": [model.__class__.__name__],
            "bbox": _bbox_from_model(model),
            "translation": _vec(model.Translation.Data),
            "rotation": _vec(model.Rotation.Data) if hasattr(model, "Rotation") else [0, 0, 0],
            "scale": _vec(model.Scaling.Data) if hasattr(model, "Scaling") else [1, 1, 1],
            "visible": bool(model.Show),
        }}
        objects.append(item)
    except Exception as exc:
        objects.append({{"native_id": getattr(model, "Name", ""), "name": getattr(model, "Name", ""), "type": "error", "error": str(exc)}})

cameras = []
for cam in scene.Cameras:
    try:
        cameras.append({{
            "native_id": cam.LongName or cam.Name,
            "name": cam.Name,
            "type": "camera",
            "translation": _vec(cam.Translation.Data),
            "rotation": _vec(cam.Rotation.Data),
            "focal_length_mm": _scalar(getattr(cam, "FocalLength", 35.0), 35.0),
            "aspect_ratio": _scalar(getattr(cam, "FilmAspectRatio", 16.0 / 9.0), 16.0 / 9.0),
            "near_clip": float(getattr(cam, "NearPlaneDistance", 0.1)),
            "far_clip": float(getattr(cam, "FarPlaneDistance", 10000.0)),
            "visible": bool(cam.Show),
        }})
    except Exception:
        pass

payload = {{
    "schema": "tech_connector.motionbuilder.scene_snapshot.v1",
    "provider_id": "motionbuilder",
    "process_id": int(os.getpid()),
    "scene": FBSystem().Scene.Filename if hasattr(FBSystem().Scene, "Filename") else "",
    "unit_linear": "centimeters",
    "up_axis": "y",
    "current_time": 0.0,
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": False,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""


def houdini_scene_snapshot_code(
    *,
    selected_only: bool = False,
    include_geometry: bool = True,
    include_materials: bool = True,
    limit: int = 500,
    max_vertices_per_object: int = 50000,
    max_faces_per_object: int = 50000,
) -> str:
    return f"""
import json
import hou
import os

selected_only = {bool(selected_only)!r}
include_geometry = {bool(include_geometry)!r}
include_materials = {bool(include_materials)!r}
limit = int({int(limit)!r})
max_vertices_per_object = int({int(max_vertices_per_object)!r})
max_faces_per_object = int({int(max_faces_per_object)!r})

def _vec3(v):
    return [float(v[0]), float(v[1]), float(v[2])]

def _bbox(node):
    try:
        box = node.geometry().boundingBox()
        return [float(box.minvec()[0]), float(box.minvec()[1]), float(box.minvec()[2]), float(box.maxvec()[0]), float(box.maxvec()[1]), float(box.maxvec()[2])]
    except Exception:
        try:
            t = node.worldTransform().extractTranslates()
            return [float(t[0])-1, float(t[1])-1, float(t[2])-1, float(t[0])+1, float(t[1])+1, float(t[2])+1]
        except Exception:
            return [0, 0, 0, 0, 0, 0]

def _mesh_geometry(node):
    if not include_geometry:
        return None
    try:
        geo = node.geometry()
    except Exception:
        return None
    points = geo.points()
    prims = geo.prims()
    if len(points) > max_vertices_per_object or len(prims) > max_faces_per_object:
        return {{"representation": "bounds", "reason": "mesh_too_large", "vertex_count": len(points), "face_count": len(prims)}}
    vertices = []
    point_index = {{}}
    for index, point in enumerate(points):
        p = node.worldTransform() * point.position()
        point_index[point.number()] = index
        vertices.append([float(p[0]), float(p[1]), float(p[2])])
    faces = []
    uvs = []
    face_uv_indices = []
    vertex_uv = geo.findVertexAttrib("uv") if include_materials else None
    point_uv = geo.findPointAttrib("uv") if include_materials and vertex_uv is None else None
    for prim in prims:
        try:
            nums = [point_index[p.number()] for p in prim.points()]
            if len(nums) >= 3:
                faces.append(nums)
                uv_indices = []
                if vertex_uv is not None or point_uv is not None:
                    for vertex in prim.vertices():
                        try:
                            uv = vertex.attribValue(vertex_uv) if vertex_uv is not None else vertex.point().attribValue(point_uv)
                            uv_indices.append(len(uvs))
                            uvs.append([float(uv[0]), float(uv[1])])
                        except Exception:
                            uv_indices.append(-1)
                face_uv_indices.append(uv_indices if len(uv_indices) == len(nums) else [-1 for _value in nums])
        except Exception:
            pass
    if not vertices or not faces:
        return None
    result = {{"representation": "mesh", "vertices": vertices, "faces": faces, "shape_names": [node.path()]}}
    if uvs and face_uv_indices:
        result.update({{"uvs": uvs, "face_uv_indices": face_uv_indices, "active_uv_set": "uv"}})
    return result

def _parm_value(node, names, fallback=None):
    for name in names:
        try:
            parm = node.parm(name)
            if parm is not None:
                return parm.eval()
            parm_tuple = node.parmTuple(name)
            if parm_tuple is not None:
                return parm_tuple.eval()
        except Exception:
            pass
    return fallback

def _first_parm_name(node, names):
    for name in names:
        try:
            if node.parm(name) is not None or node.parmTuple(name) is not None:
                return name
        except Exception:
            pass
    return names[0]

def _color(value, fallback):
    try:
        return [float(value[0]), float(value[1]), float(value[2]), 1.0]
    except Exception:
        return list(fallback)

def _texture_binding(shader, channel, parm_names):
    raw_path = str(_parm_value(shader, parm_names, "") or "")
    if not raw_path:
        return None
    try:
        path = hou.text.expandString(raw_path)
    except Exception:
        path = raw_path
    return {{
        "channel": channel,
        "path": path,
        "color_space": "sRGB - Texture" if channel in ("base_color", "emission_color") else "Raw",
        "uv_set": "uv",
        "source_channel": _first_parm_name(shader, parm_names),
    }}

def _material_payload(material_path):
    shader = hou.node(material_path) if material_path else None
    if shader is None:
        return None
    color = _color(_parm_value(shader, ("basecolor", "base_color", "diff", "ogl_diff"), None), (0.5, 0.5, 0.5, 1.0))
    roughness = float(_parm_value(shader, ("rough", "roughness", "specrough"), 0.5) or 0.5)
    metalness = float(_parm_value(shader, ("metallic", "metalness", "metallicfactor"), 0.0) or 0.0)
    opacity = float(_parm_value(shader, ("opac", "opacity", "alpha"), 1.0) or 1.0)
    emission = _color(_parm_value(shader, ("emitcolor", "emission_color", "emit_color"), None), (0, 0, 0, 1))[:3]
    textures = []
    for channel, names in (
        ("base_color", ("basecolor_texture", "basecolor_texture_file", "base_color_texture", "ogl_tex1")),
        ("normal", ("normal_texture", "baseBumpAndNormal_texture", "normalmap")),
        ("specular_roughness", ("rough_texture", "roughness_texture", "specrough_texture")),
        ("metalness", ("metallic_texture", "metalness_texture")),
        ("emission_color", ("emitcolor_texture", "emission_texture")),
        ("opacity", ("opaccolor_texture", "opacity_texture")),
    ):
        binding = _texture_binding(shader, channel, names)
        if binding:
            textures.append(binding)
    return {{
        "name": shader.name(),
        "source_material_id": shader.path(),
        "source_shader": shader.type().nameWithCategory(),
        "color": color,
        "roughness": max(0.0, min(1.0, roughness)),
        "metalness": max(0.0, min(1.0, metalness)),
        "specular": 0.5,
        "opacity": max(0.0, min(1.0, opacity)),
        "emission_color": emission,
        "textures": textures,
    }}

def _material_state(node):
    if not include_materials:
        return [], []
    try:
        geo = node.geometry()
        prims = list(geo.prims())
    except Exception:
        return [], []
    paths_by_face = []
    primitive_attribute = geo.findPrimAttrib("shop_materialpath")
    for prim in prims:
        try:
            paths_by_face.append(str(prim.attribValue(primitive_attribute) or "") if primitive_attribute else "")
        except Exception:
            paths_by_face.append("")
    object_path = str(_parm_value(node, ("shop_materialpath", "material"), "") or "")
    if object_path:
        paths_by_face = [path or object_path for path in paths_by_face]
    materials = []
    assignments = []
    for slot_index, material_path in enumerate(dict.fromkeys(path for path in paths_by_face if path)):
        material = _material_payload(material_path)
        if not material:
            continue
        materials.append(material)
        assignments.append({{
            "material_id": material["source_material_id"],
            "slot_index": slot_index,
            "face_indices": [index for index, path in enumerate(paths_by_face) if path == material_path],
            "uv_set": "uv" if geo.findVertexAttrib("uv") or geo.findPointAttrib("uv") else "",
        }})
    return materials, assignments

source = hou.selectedNodes() if selected_only else hou.node("/").allSubChildren()
objects = []
for node in list(source)[:limit]:
    try:
        bbox = _bbox(node)
        item = {{
            "native_id": node.path(),
            "name": node.name(),
            "type": node.type().name(),
            "shape_types": [node.type().category().name(), node.type().name()],
            "bbox": bbox,
            "translation": _vec3(node.worldTransform().extractTranslates()) if hasattr(node, "worldTransform") else [0, 0, 0],
            "rotation": [0, 0, 0],
            "scale": [1, 1, 1],
            "visible": not node.isHidden(),
        }}
        geometry = _mesh_geometry(node)
        if geometry:
            item["geometry"] = geometry
        materials, assignments = _material_state(node)
        if materials:
            item["material"] = materials[0]
            item["materials"] = materials
            item["material_assignments"] = assignments
        objects.append(item)
    except Exception as exc:
        objects.append({{"native_id": node.path(), "name": node.name(), "type": "error", "error": str(exc)}})

cameras = []
for node in hou.node("/").allSubChildren():
    try:
        if node.type().name().lower() != "cam":
            continue
        cameras.append({{
            "native_id": node.path(),
            "name": node.name(),
            "type": "camera",
            "translation": _vec3(node.worldTransform().extractTranslates()),
            "rotation": [0, 0, 0],
            "focal_length_mm": float(node.parm("focal").eval()) if node.parm("focal") else 50.0,
            "aspect_ratio": (
                float(node.parm("resx").eval()) / max(1.0, float(node.parm("resy").eval()))
                if node.parm("resx") and node.parm("resy") else 16.0 / 9.0
            ),
            "near_clip": float(node.parm("near").eval()) if node.parm("near") else 0.1,
            "far_clip": float(node.parm("far").eval()) if node.parm("far") else 10000.0,
            "visible": True,
        }})
    except Exception:
        pass

payload = {{
    "schema": "tech_connector.houdini.scene_snapshot.v1",
    "provider_id": "houdini",
    "process_id": int(os.getpid()),
    "scene": hou.hipFile.path(),
    "scene_modified": bool(hou.hipFile.hasUnsavedChanges()),
    "application_version": str(hou.applicationVersionString()),
    "unit_linear": "meters",
    "up_axis": "y",
    "current_time": float(hou.frame()),
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": include_geometry,
        "include_materials": include_materials,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""


def unity_scene_snapshot_code(*, selected_only: bool = False, limit: int = 500) -> str:
    return (
        "Tech Connector scene snapshots for Unity require the Unity bridge to expose "
        "JSON object/camera bounds from C#; this bridge currently supports command strings only."
    )


def substance_painter_scene_snapshot_code(*, include_materials: bool = True, limit: int = 500) -> str:
    """Return defensive project lookdev introspection for Painter's evolving API."""

    return f"""
import json
import os
import substance_painter.application
import substance_painter.project
import substance_painter.textureset

limit = max(1, min(10000, int({int(limit)!r})))
include_materials = {bool(include_materials)!r}

def _call(value, names, fallback=None):
    for name in names:
        try:
            member = getattr(value, name, None)
            if callable(member):
                return member()
            if member is not None:
                return member
        except Exception:
            pass
    return fallback

def _display_name(value):
    result = _call(value, ("name", "display_name", "label"), "")
    return str(result or value)

def _channel_rows(stack):
    channels = _call(stack, ("all_channels", "channels"), []) or []
    rows = []
    for channel in channels:
        rows.append({{
            "name": _display_name(channel),
            "type": str(_call(channel, ("type", "channel_type"), type(channel).__name__)),
        }})
    return rows

objects = []
if substance_painter.project.is_open():
    for texture_set in list(substance_painter.textureset.all_texture_sets() or [])[:limit]:
        texture_set_name = _display_name(texture_set)
        stacks = list(_call(texture_set, ("all_stacks", "stacks"), []) or []) if include_materials else []
        stack_rows = [
            {{"name": _display_name(stack), "channels": _channel_rows(stack)}}
            for stack in stacks
        ]
        material_id = "textureset:" + texture_set_name
        material = {{
            "name": texture_set_name,
            "source_material_id": material_id,
            "source_shader": "substance_painter.texture_set",
            "color": [0.5, 0.5, 0.5, 1.0],
            "roughness": 0.5,
            "metalness": 0.0,
            "opacity": 1.0,
            "textures": {{}},
            "unsupported_nodes": ["substance_painter_layer_stack"],
            "texture_set_state": {{"stacks": stack_rows}},
        }}
        item = {{
            "native_id": material_id,
            "name": texture_set_name,
            "type": "texture_set",
            "visible": True,
        }}
        if include_materials:
            item.update({{
                "material": material,
                "materials": [material],
                "material_assignments": [{{
                "material_id": material_id,
                "slot_index": 0,
                "face_indices": [],
                "uv_set": "",
                }}],
            }})
        objects.append(item)

try:
    mesh_path = str(substance_painter.project.last_imported_mesh_path() or "")
except Exception:
    mesh_path = ""
payload = {{
    "schema": "tech_connector.substance_painter.scene_snapshot.v1",
    "provider_id": "substance_painter",
    "process_id": int(os.getpid()),
    "scene": str(substance_painter.project.file_path() or "") if substance_painter.project.is_open() else "",
    "application_version": str(substance_painter.application.version()),
    "scene_modified": False,
    "source_mesh_path": mesh_path,
    "objects": objects,
    "cameras": [],
    "selection": [],
    "isolation": {{
        "selected_only": False,
        "include_geometry": False,
        "include_materials": include_materials,
        "lookdev_only": True,
    }},
}}
print(json.dumps(payload, default=str))
"""


def unreal_scene_snapshot_code(*, selected_only: bool = False, include_materials: bool = True, limit: int = 500) -> str:
    return f"""
import json
import os
import unreal

selected_only = {bool(selected_only)!r}
include_materials = {bool(include_materials)!r}
limit = int({int(limit)!r})

def _vec(v):
    return [float(v.x), float(v.y), float(v.z)]

def _rot(r):
    return [float(r.roll), float(r.pitch), float(r.yaw)]

def _camera_role(actor, actor_class):
    class_name = str(actor_class or "")
    label = ""
    try:
        label = str(actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name())
    except Exception:
        label = ""
    lowered = (class_name + " " + label).lower()
    if "cinecamera" in lowered or "sequence" in lowered or "shot" in lowered or "cinematic" in lowered:
        return "sequence"
    if "playercamera" in lowered or "gameplay" in lowered or "followcamera" in lowered or "springarm" in lowered:
        return "gameplay"
    return "level"

def _actor_bbox(actor):
    try:
        origin, extent = actor.get_actor_bounds(False)
        return [
            float(origin.x - extent.x),
            float(origin.y - extent.y),
            float(origin.z - extent.z),
            float(origin.x + extent.x),
            float(origin.y + extent.y),
            float(origin.z + extent.z),
        ]
    except Exception:
        loc = actor.get_actor_location()
        return [float(loc.x)-1, float(loc.y)-1, float(loc.z)-1, float(loc.x)+1, float(loc.y)+1, float(loc.z)+1]

def _parameter_value(material, getter_name, parameter_name):
    getter = getattr(material, getter_name, None)
    if not callable(getter):
        return None
    try:
        result = getter(parameter_name)
        if isinstance(result, (tuple, list)) and len(result) == 2 and isinstance(result[0], bool):
            return result[1] if result[0] else None
        return result
    except Exception:
        return None

def _texture_source_path(texture):
    if texture is None:
        return "", ""
    package_path = texture.get_path_name() if hasattr(texture, "get_path_name") else str(texture)
    source_path = ""
    try:
        import_data = texture.get_editor_property("asset_import_data")
        filenames = list(import_data.extract_filenames() or []) if import_data else []
        source_path = str(filenames[0]) if filenames else ""
    except Exception:
        pass
    return source_path or package_path, package_path

def _material_payload(material):
    name = material.get_name() if hasattr(material, "get_name") else str(material)
    material_id = material.get_path_name() if hasattr(material, "get_path_name") else name
    color = [0.5, 0.5, 0.5, 1.0]
    for param_name in ("BaseColor", "Base Color", "Color", "Tint"):
        value = _parameter_value(material, "get_vector_parameter_value", param_name)
        if value is not None:
            color = [float(value.r), float(value.g), float(value.b), float(value.a)]
            break
    def scalar(names, fallback):
        for param_name in names:
            value = _parameter_value(material, "get_scalar_parameter_value", param_name)
            if value is not None:
                return float(value)
        return float(fallback)
    textures = {{}}
    for channel, parameter_names in (
        ("base_color", ("BaseColor", "Base Color", "Albedo")),
        ("normal", ("Normal", "NormalMap")),
        ("metalness", ("Metallic", "Metalness")),
        ("specular_roughness", ("Roughness",)),
        ("emission_color", ("Emissive", "EmissiveColor")),
        ("opacity", ("Opacity", "OpacityMask")),
    ):
        for parameter_name in parameter_names:
            texture = _parameter_value(material, "get_texture_parameter_value", parameter_name)
            path, package_path = _texture_source_path(texture)
            if path:
                textures[channel] = {{
                    "path": path,
                    "color_space": "sRGB - Texture" if channel in ("base_color", "emission_color") else "Raw",
                    "uv_set": "uv0",
                    "source_channel": parameter_name,
                    "host_asset_path": package_path,
                }}
                break
    try:
        source_shader = material.get_class().get_name()
    except Exception:
        source_shader = type(material).__name__
    return {{
        "name": name,
        "source_material_id": material_id,
        "source_shader": source_shader,
        "color": color,
        "roughness": max(0.0, min(1.0, scalar(("Roughness",), 0.5))),
        "metalness": max(0.0, min(1.0, scalar(("Metallic", "Metalness"), 0.0))),
        "specular": max(0.0, min(1.0, scalar(("Specular",), 0.5))),
        "opacity": max(0.0, min(1.0, scalar(("Opacity",), color[3]))),
        "emission_color": [0.0, 0.0, 0.0],
        "textures": textures,
    }}

def _material_state(actor):
    if not include_materials:
        return [], []
    try:
        components = actor.get_components_by_class(unreal.MeshComponent)
    except Exception:
        components = []
    materials = {{}}
    assignments = []
    for component in components:
        try:
            slot_count = int(component.get_num_materials())
        except Exception:
            slot_count = 1
        for slot_index in range(max(0, slot_count)):
            try:
                material = component.get_material(slot_index)
            except Exception:
                material = None
            if material is None:
                continue
            payload = _material_payload(material)
            material_id = payload["source_material_id"]
            materials.setdefault(material_id, payload)
            assignments.append({{
                "material_id": material_id,
                "slot_index": slot_index,
                "face_indices": [],
                "uv_set": "",
                "component_native_id": component.get_path_name() if hasattr(component, "get_path_name") else str(component),
            }})
    return list(materials.values()), assignments

try:
    editor_actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
except Exception:
    editor_actor_subsystem = None

if selected_only and editor_actor_subsystem:
    source = list(editor_actor_subsystem.get_selected_level_actors())
elif editor_actor_subsystem:
    source = list(editor_actor_subsystem.get_all_level_actors())
else:
    source = []

objects = []
for actor in source[:limit]:
    try:
        actor_class = actor.get_class().get_name()
        actor_name = actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name()
        lowered_name = str(actor_name).lower()
        if isinstance(actor, unreal.CameraActor) or "CameraActor" in str(actor_class):
            continue
        if actor_class in {"WorldDataLayers", "WorldSettings", "LevelScriptActor", "Brush"}:
            continue
        if "sky" in lowered_name or "skysphere" in lowered_name or "background" in lowered_name:
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        scale = actor.get_actor_scale3d()
        item = {{
            "native_id": actor.get_path_name(),
            "name": actor_name,
            "type": actor_class,
            "shape_types": [actor_class],
            "bbox": _actor_bbox(actor),
            "translation": _vec(loc),
            "rotation": _rot(rot),
            "scale": _vec(scale),
            "visible": not bool(actor.is_hidden_ed()) if hasattr(actor, "is_hidden_ed") else True,
        }}
        materials, material_assignments = _material_state(actor)
        if materials:
            item["material"] = materials[0]
            item["materials"] = materials
            item["material_assignments"] = material_assignments
        objects.append(item)
    except Exception as exc:
        objects.append({{"native_id": actor.get_path_name(), "name": actor.get_name(), "type": "error", "error": str(exc)}})

cameras = []
for actor in source:
    try:
        actor_class = actor.get_class().get_name()
        looks_like_camera = isinstance(actor, unreal.CameraActor) or "Camera" in str(actor_class)
        if not looks_like_camera:
            continue
        loc = actor.get_actor_location()
        rot = actor.get_actor_rotation()
        cam = None
        for getter in ("get_cine_camera_component", "get_camera_component"):
            if cam is None and hasattr(actor, getter):
                try:
                    cam = getattr(actor, getter)()
                except Exception:
                    cam = None
        if cam is None and hasattr(actor, "camera_component"):
            try:
                cam = actor.camera_component
            except Exception:
                cam = None
        if cam is None and hasattr(actor, "get_editor_property"):
            for prop_name in ("camera_component", "CameraComponent"):
                try:
                    cam = actor.get_editor_property(prop_name)
                    if cam is not None:
                        break
                except Exception:
                    pass
        if cam is None and hasattr(actor, "get_component_by_class"):
            try:
                cam = actor.get_component_by_class(unreal.CameraComponent)
            except Exception:
                cam = None
        cameras.append({{
            "native_id": actor.get_path_name(),
            "name": actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name(),
            "type": "camera",
            "camera_role": _camera_role(actor, actor_class),
            "translation": _vec(loc),
            "rotation": _rot(rot),
            "focal_length_mm": float(cam.current_focal_length) if cam is not None and hasattr(cam, "current_focal_length") else 35.0,
            "aspect_ratio": float(cam.aspect_ratio) if cam is not None and hasattr(cam, "aspect_ratio") else 16.0 / 9.0,
            "near_clip": 10.0,
            "far_clip": 100000.0,
            "visible": True,
        }})
    except Exception:
        pass

for actor in source:
    try:
        if isinstance(actor, unreal.CameraActor):
            continue
        actor_class = actor.get_class().get_name()
        actor_name = actor.get_actor_label() if hasattr(actor, "get_actor_label") else actor.get_name()
        camera_components = []
        try:
            camera_components = list(actor.get_components_by_class(unreal.CameraComponent) or [])
        except Exception:
            camera_components = []
        for index, cam in enumerate(camera_components[:4]):
            try:
                transform = cam.get_world_transform()
                loc = transform.translation
                rot = transform.rotation.rotator()
                component_name = cam.get_name() if hasattr(cam, "get_name") else f"CameraComponent{{index}}"
                cameras.append({{
                    "native_id": actor.get_path_name() + "::" + component_name,
                    "name": f"{{actor_name}} / {{component_name}}",
                    "type": "camera_component",
                    "camera_role": "gameplay",
                    "translation": _vec(loc),
                    "rotation": _rot(rot),
                "focal_length_mm": float(cam.current_focal_length) if hasattr(cam, "current_focal_length") else 35.0,
                "aspect_ratio": float(cam.aspect_ratio) if hasattr(cam, "aspect_ratio") else 16.0 / 9.0,
                    "near_clip": 10.0,
                    "far_clip": 100000.0,
                    "visible": True,
                }})
            except Exception:
                pass
    except Exception:
        pass

try:
    level_name = unreal.EditorLevelLibrary.get_editor_world().get_name()
except Exception:
    level_name = ""

payload = {{
    "schema": "tech_connector.unreal.scene_snapshot.v1",
    "provider_id": "unreal",
    "process_id": int(os.getpid()),
    "scene": level_name,
    "unit_linear": "centimeters",
    "up_axis": "z",
    "current_time": 0.0,
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": False,
        "include_materials": include_materials,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""


def max_scene_snapshot_code(
    *,
    selected_only: bool = False,
    include_materials: bool = True,
    limit: int = 500,
) -> str:
    return f"""
import json
import os
import pymxs
rt = pymxs.runtime
selected_only = {bool(selected_only)!r}
include_materials = {bool(include_materials)!r}
limit = max(1, min(10000, int({int(limit)!r})))
nodes = list(rt.selection if selected_only else rt.objects)[:limit]
objects = []
cameras = []

def _point(value):
    return [float(value.x), float(value.y), float(value.z)]

def _matrix(value):
    return [
        float(value.row1.x), float(value.row1.y), float(value.row1.z), 0.0,
        float(value.row2.x), float(value.row2.y), float(value.row2.z), 0.0,
        float(value.row3.x), float(value.row3.y), float(value.row3.z), 0.0,
        float(value.row4.x), float(value.row4.y), float(value.row4.z), 1.0,
    ]

def _world_point(value, transform):
    try:
        return _point(value * transform)
    except Exception:
        return _point(value)

def _property(value, names, fallback=None):
    for name in names:
        try:
            if rt.isProperty(value, name):
                return getattr(value, name)
        except Exception:
            pass
    return fallback

def _unit_color(value, fallback=(0.5, 0.5, 0.5, 1.0)):
    try:
        components = [float(value.r), float(value.g), float(value.b)]
        if max(components) > 1.0:
            components = [component / 255.0 for component in components]
        alpha = float(getattr(value, "a", fallback[3]))
        if alpha > 1.0:
            alpha /= 255.0
        return components + [alpha]
    except Exception:
        return list(fallback)

def _number(value, fallback):
    try:
        return float(value)
    except Exception:
        return float(fallback)

def _texture_binding(texture, channel, source_channel):
    if texture is None:
        return None
    path = str(_property(texture, ("filename", "fileName", "Filename"), "") or "")
    if not path:
        return None
    return {{
        "channel": channel,
        "path": path,
        "color_space": "sRGB - Texture" if channel in ("base_color", "emission_color") else "Raw",
        "uv_set": "map1",
        "source_channel": source_channel,
    }}

def _material_payload(material):
    if material is None:
        return None
    color = _unit_color(_property(material, ("base_color", "baseColor", "diffuse", "diffuseColor")))
    roughness = _number(_property(material, ("roughness", "base_roughness"), 0.5), 0.5)
    metalness = _number(_property(material, ("metalness", "metallic"), 0.0), 0.0)
    opacity = _number(_property(material, ("opacity",), 100.0), 100.0)
    if opacity > 1.0:
        opacity /= 100.0
    emission = _unit_color(_property(material, ("emission_color", "selfIllumColor"), None), (0, 0, 0, 1))[:3]
    textures = []
    for channel, property_names in (
        ("base_color", ("base_color_map", "baseColorMap", "diffuseMap")),
        ("normal", ("normal_map", "normalMap", "bumpMap")),
        ("metalness", ("metalness_map", "metallicMap")),
        ("specular_roughness", ("roughness_map", "roughnessMap")),
        ("emission_color", ("emission_color_map", "selfIllumMap")),
        ("opacity", ("opacityMap", "cutout_map")),
    ):
        for property_name in property_names:
            texture = _property(material, (property_name,), None)
            binding = _texture_binding(texture, channel, property_name)
            if binding:
                textures.append(binding)
                break
    try:
        native_id = str(rt.getHandleByAnim(material))
    except Exception:
        native_id = str(material.name)
    return {{
        "name": str(material.name),
        "source_material_id": native_id,
        "source_shader": str(rt.classOf(material)),
        "color": color,
        "roughness": max(0.0, min(1.0, roughness)),
        "metalness": max(0.0, min(1.0, metalness)),
        "specular": 0.5,
        "opacity": max(0.0, min(1.0, opacity)),
        "emission_color": emission,
        "textures": textures,
    }}

def _material_slots(material):
    if material is None:
        return []
    try:
        sub_count = int(rt.getNumSubMtls(material))
    except Exception:
        sub_count = 0
    slots = []
    if sub_count > 0:
        try:
            material_ids = [int(value) for value in list(material.materialIDList)]
        except Exception:
            material_ids = []
        for slot_index in range(1, sub_count + 1):
            try:
                sub_material = rt.getSubMtl(material, slot_index)
            except Exception:
                sub_material = None
            payload = _material_payload(sub_material)
            if payload:
                face_material_id = material_ids[slot_index - 1] if slot_index - 1 < len(material_ids) else slot_index
                slots.append((slot_index - 1, face_material_id, payload))
    else:
        payload = _material_payload(material)
        if payload:
            slots.append((0, 1, payload))
    return slots

for node in nodes:
    try:
        class_name = str(rt.classOf(node))
        bounds = []
        try:
            box = rt.nodeGetBoundingBox(node, node.transform)
            bounds = _point(box[0]) + _point(box[1])
        except Exception:
            pass
        row = {{
            "name": str(node.name),
            "native_id": str(node.handle),
            "type": class_name,
            "matrix": _matrix(node.transform),
            "bbox": bounds,
            "selected": bool(node.isSelected),
            "visible": not bool(node.isHidden),
            "materials": [],
            "material_assignments": [],
        }}
        try:
            mesh = rt.snapshotAsMesh(node)
            vertex_count = int(rt.getNumVerts(mesh))
            face_count = int(rt.getNumFaces(mesh))
            if vertex_count <= 1000000 and face_count <= 1000000:
                vertices = [_world_point(rt.getVert(mesh, index), node.transform) for index in range(1, vertex_count + 1)]
                faces = [
                    [int(value) - 1 for value in _point(rt.getFace(mesh, index))]
                    for index in range(1, face_count + 1)
                ]
                geometry = {{"representation": "mesh", "vertices": vertices, "faces": faces}}
                try:
                    tvert_count = int(rt.getNumTVerts(mesh))
                    if tvert_count > 0:
                        geometry["uvs"] = [
                            [float(rt.getTVert(mesh, index).x), float(rt.getTVert(mesh, index).y)]
                            for index in range(1, tvert_count + 1)
                        ]
                        geometry["face_uv_indices"] = [
                            [int(value) - 1 for value in _point(rt.getTVFace(mesh, index))]
                            for index in range(1, face_count + 1)
                        ]
                        geometry["active_uv_set"] = "map1"
                except Exception:
                    pass
                row["geometry"] = geometry
                if include_materials:
                    try:
                        face_material_ids = [int(rt.getFaceMatID(mesh, index)) for index in range(1, face_count + 1)]
                    except Exception:
                        face_material_ids = [1 for _index in range(face_count)]
                    for slot_index, face_material_id, material in _material_slots(node.material):
                        row["materials"].append(material)
                        row["material_assignments"].append({{
                            "material_id": material["source_material_id"],
                            "slot_index": slot_index,
                            "face_indices": [
                                index for index, value in enumerate(face_material_ids)
                                if value == face_material_id
                            ],
                            "uv_set": "map1" if geometry.get("uvs") else "",
                        }})
                    if row["materials"]:
                        row["material"] = row["materials"][0]
        except Exception:
            pass
        objects.append(row)
        if "camera" in class_name.lower():
            cameras.append({{
                "name": str(node.name),
                "native_id": str(node.handle),
                "matrix": row["matrix"],
                "fov_degrees": float(getattr(node, "fov", 0.78539816339)) * 57.295779513,
            }})
    except Exception:
        pass

payload = {{
    "schema": "tech_connector.3dsmax.scene_snapshot.v1",
    "provider_id": "3dsmax",
    "process_id": int(os.getpid()),
    "scene": str(rt.maxFilePath) + str(rt.maxFileName),
    "unit_linear": "generic_units",
    "up_axis": "z",
    "current_time": float(rt.sliderTime),
    "fps": float(rt.frameRate),
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{"selected_only": selected_only, "include_geometry": True, "include_materials": include_materials}},
}}
print(json.dumps(payload, default=str))
"""
