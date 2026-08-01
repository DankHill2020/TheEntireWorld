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
    limit: int = 500,
    max_vertices_per_object: int = 50000,
    max_faces_per_object: int = 50000,
) -> str:
    return f"""
import json
import mathutils
import bpy

selected_only = {bool(selected_only)!r}
include_geometry = {bool(include_geometry)!r}
limit = int({int(limit)!r})
max_vertices_per_object = int({int(max_vertices_per_object)!r})
max_faces_per_object = int({int(max_faces_per_object)!r})

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
        vertices = []
        for vert in mesh.vertices:
            p = eval_obj.matrix_world @ vert.co
            vertices.append([float(p.x), float(p.y), float(p.z)])
        faces = [[int(i) for i in poly.vertices] for poly in mesh.polygons if len(poly.vertices) >= 3]
        if not vertices or not faces:
            return None
        return {{
            "representation": "mesh",
            "vertices": vertices,
            "faces": faces,
            "shape_names": [obj.data.name if obj.data else obj.name],
        }}
    finally:
        if mesh is not None:
            eval_obj.to_mesh_clear()

def _material_payload(obj):
    mat = getattr(obj, "active_material", None)
    if mat is None and getattr(obj, "material_slots", None):
        for slot in obj.material_slots:
            if slot.material is not None:
                mat = slot.material
                break
    if mat is None:
        return None
    color = list(getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0)))
    try:
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED" and "Base Color" in node.inputs:
                    color = list(node.inputs["Base Color"].default_value)
                    break
    except Exception:
        pass
    return {{
        "name": mat.name,
        "color": [float(color[0]), float(color[1]), float(color[2]), float(color[3] if len(color) > 3 else 1.0)],
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
        material = _material_payload(obj)
        if material:
            item["material"] = material
        light = _light_payload(obj)
        if light:
            item["light"] = light
        objects.append(item)
    except Exception as exc:
        objects.append({{"native_id": obj.name_full, "name": obj.name, "type": "error", "error": str(exc)}})

cameras = []
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
        "near_clip": float(cam.clip_start),
        "far_clip": float(cam.clip_end),
        "visible": not obj.hide_get(),
    }})

payload = {{
    "schema": "tech_connector.blender.scene_snapshot.v1",
    "provider_id": "blender",
    "scene": bpy.data.filepath or "",
    "unit_linear": str(bpy.context.scene.unit_settings.system),
    "up_axis": "z",
    "current_time": float(bpy.context.scene.frame_current),
    "objects": objects,
    "cameras": cameras,
    "active_camera": bpy.context.scene.camera.name_full if bpy.context.scene.camera else "",
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": include_geometry,
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""


def motionbuilder_scene_snapshot_code(*, selected_only: bool = False, limit: int = 500) -> str:
    return f"""
import json
from pyfbsdk import FBSystem, FBModelList, FBGetSelectedModels, FBCamera

selected_only = {bool(selected_only)!r}
limit = int({int(limit)!r})

def _vec(values):
    return [float(values[i]) for i in range(3)]

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
            "focal_length_mm": float(getattr(cam, "FocalLength", 35.0)),
            "near_clip": float(getattr(cam, "NearPlaneDistance", 0.1)),
            "far_clip": float(getattr(cam, "FarPlaneDistance", 10000.0)),
            "visible": bool(cam.Show),
        }})
    except Exception:
        pass

payload = {{
    "schema": "tech_connector.motionbuilder.scene_snapshot.v1",
    "provider_id": "motionbuilder",
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
    limit: int = 500,
    max_vertices_per_object: int = 50000,
    max_faces_per_object: int = 50000,
) -> str:
    return f"""
import json
import hou

selected_only = {bool(selected_only)!r}
include_geometry = {bool(include_geometry)!r}
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
    for prim in prims:
        try:
            nums = [point_index[p.number()] for p in prim.points()]
            if len(nums) >= 3:
                faces.append(nums)
        except Exception:
            pass
    if not vertices or not faces:
        return None
    return {{"representation": "mesh", "vertices": vertices, "faces": faces, "shape_names": [node.path()]}}

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
            "near_clip": float(node.parm("near").eval()) if node.parm("near") else 0.1,
            "far_clip": float(node.parm("far").eval()) if node.parm("far") else 10000.0,
            "visible": True,
        }})
    except Exception:
        pass

payload = {{
    "schema": "tech_connector.houdini.scene_snapshot.v1",
    "provider_id": "houdini",
    "scene": hou.hipFile.path(),
    "unit_linear": "meters",
    "up_axis": "y",
    "current_time": float(hou.frame()),
    "objects": objects,
    "cameras": cameras,
    "active_camera": "",
    "isolation": {{
        "selected_only": selected_only,
        "include_geometry": include_geometry,
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


def unreal_scene_snapshot_code(*, selected_only: bool = False, limit: int = 500) -> str:
    return f"""
import json
import unreal

selected_only = {bool(selected_only)!r}
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

def _material_payload(actor):
    try:
        components = actor.get_components_by_class(unreal.MeshComponent)
    except Exception:
        components = []
    for component in components:
        try:
            material = component.get_material(0)
        except Exception:
            material = None
        if material is None:
            continue
        name = material.get_name() if hasattr(material, "get_name") else str(material)
        color = None
        for param_name in ("BaseColor", "Base Color", "Color", "Tint"):
            try:
                ok, value = material.get_vector_parameter_value(param_name)
                if ok:
                    color = [float(value.r), float(value.g), float(value.b), float(value.a)]
                    break
            except Exception:
                pass
        return {{"name": name, "color": color}}
    return None

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
        material = _material_payload(actor)
        if material:
            item["material"] = material
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
                component_name = cam.get_name() if hasattr(cam, "get_name") else f"CameraComponent{index}"
                cameras.append({{
                    "native_id": actor.get_path_name() + "::" + component_name,
                    "name": f"{{actor_name}} / {{component_name}}",
                    "type": "camera_component",
                    "camera_role": "gameplay",
                    "translation": _vec(loc),
                    "rotation": _rot(rot),
                    "focal_length_mm": float(cam.current_focal_length) if hasattr(cam, "current_focal_length") else 35.0,
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
        "transparent_background": True,
        "excluded_categories": ["background", "grid", "hud", "manipulators"],
    }},
}}
print(json.dumps(payload))
"""


def max_scene_snapshot_code(*, selected_only: bool = False, limit: int = 500) -> str:
    return (
        "Tech Connector scene snapshots for 3ds Max require a 3ds Max bridge; "
        "no installed bridge is registered in this checkout yet."
    )
