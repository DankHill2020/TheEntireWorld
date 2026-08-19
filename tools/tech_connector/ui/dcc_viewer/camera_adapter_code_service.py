"""Build executable camera authority adapters for supported DCC hosts."""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


def build_camera_possession_code(provider: str, payload: dict[str, Any]) -> str:
    """Build a standalone host script that applies a shared camera payload.

    :param provider: DCC provider name.
    :param payload: Shared camera authority payload.
    :return: Executable Python source for the selected host.
    """

    builders = {
        "maya": _maya_possession_code,
        "blender": _blender_possession_code,
        "houdini": _houdini_possession_code,
        "unreal": _unreal_possession_code,
        "motionbuilder": _motionbuilder_possession_code,
    }
    key = str(provider or "").strip().lower()
    if key not in builders:
        raise ValueError(f"Unsupported camera provider: {provider}")
    return builders[key](json.dumps(payload))


def build_maya_camera_authority_code(native_id: str) -> str:
    """Build Maya source that reads camera authority using the render gate.

    :param native_id: Maya camera transform or shape name.
    :return: Executable Maya Python source.
    """

    return dedent(f'''\
        import json
        import math
        import maya.cmds as cmds

        camera = {native_id!r}
        if not cmds.objExists(camera):
            raise RuntimeError("Camera does not exist: " + camera)
        if cmds.nodeType(camera) == "camera":
            shapes = [camera]
            parents = cmds.listRelatives(camera, parent=True, fullPath=True) or []
            transform = parents[0] if parents else camera
        else:
            transform = camera
            shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
        if not shapes:
            raise RuntimeError("Node is not a camera: " + camera)
        shape = shapes[0]
        matrix = [float(value) for value in cmds.xform(transform, q=True, ws=True, matrix=True)]
        eye = [matrix[12], matrix[13], matrix[14]]
        forward = [-matrix[8], -matrix[9], -matrix[10]]
        length = math.sqrt(sum(value * value for value in forward)) or 1.0
        forward = [value / length for value in forward]
        up = [matrix[4], matrix[5], matrix[6]]
        up_length = math.sqrt(sum(value * value for value in up)) or 1.0
        up = [value / up_length for value in up]
        target = [eye[index] + forward[index] * 10.0 for index in range(3)]
        up_target = [target[index] + up[index] * 10.0 for index in range(3)]
        horizontal_aperture = max(1.0e-6, float(cmds.getAttr(shape + ".horizontalFilmAperture") or 1.41732))
        vertical_aperture = max(1.0e-6, float(cmds.getAttr(shape + ".verticalFilmAperture") or 0.94488))
        film_aspect = horizontal_aperture / vertical_aperture
        try:
            aspect_ratio = max(0.01, float(cmds.getAttr("defaultResolution.deviceAspectRatio")))
        except Exception:
            width = max(1.0, float(cmds.getAttr("defaultResolution.width") or 1920.0))
            height = max(1.0, float(cmds.getAttr("defaultResolution.height") or 1080.0))
            pixel_aspect = max(0.01, float(cmds.getAttr("defaultResolution.pixelAspect") or 1.0))
            aspect_ratio = width * pixel_aspect / height
        film_fit = int(cmds.getAttr(shape + ".filmFit") or 0)
        use_horizontal_fit = film_fit == 1 or (film_fit == 0 and aspect_ratio >= film_aspect) or (film_fit == 3 and aspect_ratio < film_aspect)
        effective_vertical_aperture = horizontal_aperture / aspect_ratio if use_horizontal_fit else vertical_aperture
        focal_length = max(1.0e-6, float(cmds.getAttr(shape + ".focalLength") or 35.0))
        vertical_fov = math.degrees(2.0 * math.atan((effective_vertical_aperture * 25.4 * 0.5) / focal_length))
        payload = {{
            "eye": eye, "target": target, "up_target": up_target,
            "fov_degrees": float(vertical_fov), "aspect_ratio": aspect_ratio,
            "film_aspect_ratio": film_aspect, "film_fit": film_fit,
            "focal_length_mm": focal_length,
            "near_clip": float(cmds.getAttr(shape + ".nearClipPlane")),
            "far_clip": float(cmds.getAttr(shape + ".farClipPlane")),
        }}
        print(json.dumps(payload))
    ''')


def build_camera_authority_code(provider: str, native_id: str) -> str:
    """Build a standalone host script that reads camera authority.

    :param provider: DCC provider name.
    :param native_id: Native camera identifier.
    :return: Executable Python source for the selected host.
    """

    builders = {
        "maya": build_maya_camera_authority_code,
        "blender": _blender_authority_code,
        "motionbuilder": _motionbuilder_authority_code,
        "unreal": _unreal_authority_code,
    }
    key = str(provider or "").strip().lower()
    if key not in builders:
        raise ValueError(f"Unsupported camera provider: {provider}")
    return builders[key](native_id)


def build_unreal_camera_switch_code(native_id: str) -> str:
    """Build Unreal source that switches the editor viewport camera.

    :param native_id: Actor path and optional component identifier.
    :return: Executable Unreal Python source.
    """

    return dedent(f'''\
        import unreal

        target_path = {native_id!r}
        component_name = ""
        if "::" in target_path:
            target_path, component_name = target_path.split("::", 1)
        actor = None
        for candidate in unreal.EditorLevelLibrary.get_all_level_actors():
            try:
                if target_path in (candidate.get_path_name(), candidate.get_name(), candidate.get_actor_label()):
                    actor = candidate
                    break
            except Exception:
                pass
        if actor is None:
            raise RuntimeError("Camera does not exist: " + target_path)
        component = None
        if component_name:
            for candidate in actor.get_components_by_class(unreal.CameraComponent) or []:
                if candidate.get_name() == component_name:
                    component = candidate
                    break
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if component is not None:
            transform = component.get_world_transform()
            subsystem.set_level_viewport_camera_info(transform.translation, transform.rotation.rotator())
        elif isinstance(actor, unreal.CameraActor):
            if hasattr(subsystem, "pilot_level_actor"):
                subsystem.pilot_level_actor(actor)
            else:
                subsystem.set_level_viewport_camera_info(actor.get_actor_location(), actor.get_actor_rotation())
        else:
            raise RuntimeError("Actor has no camera component: " + target_path)
        print("OK")
    ''')


def _blender_authority_code(native_id: str) -> str:
    return dedent(f'''\
        import json
        import math
        import bpy
        from mathutils import Vector

        name = {native_id!r}
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "CAMERA":
            raise RuntimeError("Camera does not exist: " + name)
        eye = obj.matrix_world.translation
        rotation = obj.matrix_world.to_quaternion()
        target = eye + (rotation @ Vector((0.0, 0.0, -1.0))).normalized() * 10.0
        up_target = target + (rotation @ Vector((0.0, 1.0, 0.0))).normalized() * 10.0
        bpy.context.scene.camera = obj
        render = bpy.context.scene.render
        width = max(1.0, float(render.resolution_x) * float(render.pixel_aspect_x))
        height = max(1.0, float(render.resolution_y) * float(render.pixel_aspect_y))
        aspect_ratio = width / height
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
        payload = {{
            "eye": list(eye), "target": list(target), "up_target": list(up_target),
            "fov_degrees": float(math.degrees(obj.data.angle_y)),
            "aspect_ratio": aspect_ratio, "focal_length_mm": float(obj.data.lens),
            "near_clip": float(obj.data.clip_start), "far_clip": float(obj.data.clip_end),
        }}
        print(json.dumps(payload))
    ''')


def _motionbuilder_authority_code(native_id: str) -> str:
    return dedent(f'''\
        import json
        import math
        import pyfbsdk

        camera_name = {native_id!r}
        camera = next((cam for cam in pyfbsdk.FBSystem().Scene.Cameras if (cam.LongName or cam.Name) == camera_name or cam.Name == camera_name), None)
        if camera is None:
            raise RuntimeError("Camera does not exist: " + camera_name)
        eye = [float(camera.Translation.Data[index]) for index in range(3)]
        rx, ry, rz = [math.radians(float(camera.Rotation.Data[index])) for index in range(3)]
        def rotate(vector):
            x, y, z = vector
            cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
            y, z = y * cx - z * sx, y * sx + z * cx
            x, z = x * cy + z * sy, -x * sy + z * cy
            return [x * cz - y * sz, x * sz + y * cz, z]
        forward, up = rotate([0.0, 0.0, -1.0]), rotate([0.0, 1.0, 0.0])
        target = [eye[index] + forward[index] * 100.0 for index in range(3)]
        up_target = [target[index] + up[index] * 100.0 for index in range(3)]
        def scalar(value, fallback):
            try:
                return float(value.Data if hasattr(value, "Data") else value)
            except Exception:
                return float(fallback)
        payload = {{
            "eye": eye, "target": target, "up_target": up_target,
            "fov_degrees": scalar(getattr(camera, "FieldOfViewY", 45.0), 45.0),
            "aspect_ratio": scalar(getattr(camera, "FilmAspectRatio", 16.0 / 9.0), 16.0 / 9.0),
            "focal_length_mm": scalar(getattr(camera, "FocalLength", 35.0), 35.0),
            "near_clip": float(getattr(camera, "NearPlaneDistance", 0.1)),
            "far_clip": float(getattr(camera, "FarPlaneDistance", 10000.0)),
        }}
        print(json.dumps(payload))
    ''')


def _unreal_authority_code(native_id: str) -> str:
    return dedent(f'''\
        import json
        import math
        import unreal

        target_path = {native_id!r}
        component_name = ""
        if "::" in target_path:
            target_path, component_name = target_path.split("::", 1)
        actor = None
        for candidate in unreal.EditorLevelLibrary.get_all_level_actors():
            try:
                if target_path in (candidate.get_path_name(), candidate.get_name(), candidate.get_actor_label()):
                    actor = candidate
                    break
            except Exception:
                pass
        if actor is None:
            raise RuntimeError("Camera does not exist: " + target_path)
        components = actor.get_components_by_class(unreal.CameraComponent) or []
        component = next((item for item in components if not component_name or item.get_name() == component_name), None)
        if component is not None:
            transform = component.get_world_transform()
            location, rotation = transform.translation, transform.rotation.rotator()
        elif isinstance(actor, unreal.CameraActor):
            location, rotation = actor.get_actor_location(), actor.get_actor_rotation()
            component = getattr(actor, "camera_component", None)
        else:
            raise RuntimeError("Actor has no camera component: " + target_path)
        forward = rotation.get_forward_vector()
        up = unreal.MathLibrary.get_up_vector(rotation)
        target = location + forward * 1000.0
        up_target = target + up * 1000.0
        horizontal_fov = float(getattr(component, "field_of_view", 45.0))
        aspect_ratio = max(0.01, float(getattr(component, "aspect_ratio", 16.0 / 9.0)))
        vertical_fov = math.degrees(2.0 * math.atan(math.tan(math.radians(horizontal_fov) * 0.5) / aspect_ratio))
        payload = {{
            "eye": [location.x, location.y, location.z],
            "target": [target.x, target.y, target.z],
            "up_target": [up_target.x, up_target.y, up_target.z],
            "fov_degrees": vertical_fov, "aspect_ratio": aspect_ratio,
            "focal_length_mm": float(getattr(component, "current_focal_length", 35.0)),
            "near_clip": 10.0, "far_clip": 100000.0,
        }}
        print(json.dumps(payload))
    ''')


def _maya_possession_code(data: str) -> str:
    return dedent(f'''\
        import json
        import math
        import maya.cmds as cmds

        data = json.loads({data!r})
        name = "TechConnector_Camera"
        transforms = cmds.ls(name, long=True, type="transform") or []
        if transforms:
            transform = transforms[0]
        else:
            transform, _shape = cmds.camera(name=name)
        shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
        if not shapes:
            raise RuntimeError("Could not resolve camera shape for " + transform)
        shape = shapes[0]
        eye = [float(value) for value in data["eye"]]
        target = [float(value) for value in data["target"]]
        up_target = [float(value) for value in data.get("up_target", [target[0], target[1] + 1.0, target[2]])]
        def normalize(vector, fallback):
            length = sum(value * value for value in vector) ** 0.5
            return [value / length for value in vector] if length >= 1.0e-6 else list(fallback)
        def cross(left, right):
            return [left[1] * right[2] - left[2] * right[1], left[2] * right[0] - left[0] * right[2], left[0] * right[1] - left[1] * right[0]]
        forward = normalize([target[i] - eye[i] for i in range(3)], [0.0, 0.0, -1.0])
        up_hint = normalize([up_target[i] - target[i] for i in range(3)], [0.0, 1.0, 0.0])
        right = normalize(cross(forward, up_hint), [1.0, 0.0, 0.0])
        up = normalize(cross(right, forward), [0.0, 1.0, 0.0])
        back = [-value for value in forward]
        cmds.xform(transform, ws=True, matrix=[*right, 0.0, *up, 0.0, *back, 0.0, *eye, 1.0])
        vertical_fov = float(data.get("fov_degrees", 45.0))
        aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
        horizontal_aperture = float(cmds.getAttr(shape + ".horizontalFilmAperture") or 1.41732)
        vertical_aperture = horizontal_aperture / aspect_ratio
        focal_length = (vertical_aperture * 25.4 * 0.5) / max(1.0e-6, math.tan(math.radians(vertical_fov) * 0.5))
        cmds.setAttr(shape + ".verticalFilmAperture", vertical_aperture)
        cmds.setAttr(shape + ".filmFit", 1)
        cmds.setAttr(shape + ".focalLength", focal_length)
        height = max(1, int(cmds.getAttr("defaultResolution.height") or 1080))
        pixel_aspect = max(0.01, float(cmds.getAttr("defaultResolution.pixelAspect") or 1.0))
        cmds.setAttr("defaultResolution.width", max(1, int(round(height * aspect_ratio / pixel_aspect))))
        cmds.setAttr("defaultResolution.deviceAspectRatio", aspect_ratio)
        cmds.setAttr(shape + ".nearClipPlane", float(data.get("near_clip", 0.1)))
        cmds.setAttr(shape + ".farClipPlane", float(data.get("far_clip", 100000.0)))
        for panel in cmds.getPanel(type="modelPanel") or []:
            cmds.modelPanel(panel, edit=True, camera=transform)
        print("OK")
    ''')


def _blender_possession_code(data: str) -> str:
    return dedent(f'''\
        import json
        import math
        import bpy
        from mathutils import Vector

        data = json.loads({data!r})
        name = "TechConnector_Camera"
        obj = bpy.data.objects.get(name)
        if obj is None:
            camera = bpy.data.cameras.new(name)
            obj = bpy.data.objects.new(name, camera)
            bpy.context.collection.objects.link(obj)
        elif obj.type != "CAMERA":
            raise RuntimeError(name + " exists but is not a camera")
        eye = Vector(data["eye"])
        target = Vector(data["target"])
        obj.location = eye
        obj.rotation_euler = (target - eye).to_track_quat("-Z", "Y").to_euler()
        aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
        obj.data.sensor_fit = "VERTICAL"
        obj.data.angle_y = math.radians(float(data.get("fov_degrees", 45.0)))
        obj.data.clip_start = float(data.get("near_clip", 0.1))
        obj.data.clip_end = float(data.get("far_clip", 100000.0))
        render = bpy.context.scene.render
        render.resolution_x = max(1, int(round(render.resolution_y * aspect_ratio)))
        bpy.context.scene.camera = obj
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
        print("OK")
    ''')


def _houdini_possession_code(data: str) -> str:
    return dedent(f'''\
        import json
        import hou

        data = json.loads({data!r})
        obj = hou.node("/obj")
        camera = obj.node("tech_connector_camera") or obj.createNode("cam", "tech_connector_camera")
        eye = hou.Vector3(data["eye"])
        target = hou.Vector3(data["target"])
        up = hou.Vector3(data.get("up_target", [0.0, 1.0, 0.0])) - target
        camera.setWorldTransform(hou.hmath.buildTranslate(eye) * hou.hmath.buildRotateLookAt(eye, target, up))
        aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
        camera.parm("resx").set(max(1, int(round(camera.parm("resy").eval() * aspect_ratio))))
        camera.parm("aspect").set(1.0)
        camera.parm("focal").set(float(data.get("focal_length_mm", 35.0)))
        camera.parm("near").set(float(data.get("near_clip", 0.1)))
        camera.parm("far").set(float(data.get("far_clip", 100000.0)))
        sceneViewers = [
            pane for pane in hou.ui.paneTabs()
            if isinstance(pane, hou.SceneViewer)
        ]
        for scene_viewer in sceneViewers:
            for viewport in scene_viewer.viewports():
                viewport.setCamera(camera)
        print("OK")
    ''')


def _unreal_possession_code(data: str) -> str:
    return dedent(f'''\
        import json
        import math
        import unreal

        data = json.loads({data!r})
        eye = unreal.Vector(*[float(value) for value in data["eye"]])
        target = unreal.Vector(*[float(value) for value in data["target"]])
        rotation = unreal.MathLibrary.find_look_at_rotation(eye, target)
        aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
        vertical_fov = float(data.get("fov_degrees", 45.0))
        horizontal_fov = math.degrees(2.0 * math.atan(math.tan(math.radians(vertical_fov) * 0.5) * aspect_ratio))
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        subsystem.set_level_viewport_camera_info(eye, rotation)
        print(json.dumps({{"ok": True, "aspect_ratio": aspect_ratio, "horizontal_fov": horizontal_fov}}))
    ''')


def _motionbuilder_possession_code(data: str) -> str:
    return dedent(f'''\
        import json
        import pyfbsdk

        data = json.loads({data!r})
        scene = pyfbsdk.FBSystem().Scene
        camera = next((item for item in scene.Cameras if item.Name == "TechConnector_Camera"), None)
        if camera is None:
            camera = pyfbsdk.FBCamera("TechConnector_Camera")
            scene.Cameras.append(camera)
        eye = [float(value) for value in data["eye"]]
        camera.Translation = pyfbsdk.FBVector3d(*eye)
        aspect_ratio = max(0.01, float(data.get("aspect_ratio", 16.0 / 9.0)))
        if hasattr(camera, "FieldOfViewY"):
            camera.FieldOfViewY.Data = float(data.get("fov_degrees", 45.0))
        camera.NearPlaneDistance = float(data.get("near_clip", 0.1))
        camera.FarPlaneDistance = float(data.get("far_clip", 100000.0))
        pyfbsdk.FBSystem().Renderer.CurrentCamera = camera
        print(json.dumps({{"ok": True, "aspect_ratio": aspect_ratio}}))
    ''')
