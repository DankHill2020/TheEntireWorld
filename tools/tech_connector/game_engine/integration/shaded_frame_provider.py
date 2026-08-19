"""Provider scripts for debounced shaded DCC viewport frames.

These are deliberately lightweight viewport captures, not final renders. They
are meant to give Tech Connector a material-accurate resolved frame after
camera/timeline/paint interaction settles, while the local proxy viewport stays
responsive during motion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_shaded_frame_output(raw: str, provider_id: str) -> tuple[bool, dict[str, Any] | str]:
    text = str(raw or "").strip()
    if not text:
        return False, f"{provider_id} did not return shaded frame output."
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except Exception as exc:
        return False, f"Could not parse {provider_id} shaded frame JSON: {exc}\n{raw}"
    if not payload.get("ok", True):
        return False, payload.get("error") or str(payload)
    path = Path(str(payload.get("path") or ""))
    if not path.exists():
        return False, f"{provider_id} shaded frame was not written: {path}"
    payload["provider_id"] = provider_id
    return True, payload


def blender_shaded_frame_code(output_path: str, *, width: int = 960, height: int = 540, frame: int | None = None) -> str:
    return f"""
import json
import os
import bpy

path = {str(output_path)!r}
width = int({int(width)!r})
height = int({int(height)!r})
frame = {int(frame) if frame is not None else None!r}

if frame is not None:
    bpy.context.scene.frame_set(frame)
camera = bpy.data.objects.get("TechConnector_Camera")
if camera is not None and camera.type == "CAMERA":
    bpy.context.scene.camera = camera
if bpy.context.scene.camera is None:
    raise RuntimeError("Blender scene has no active camera.")

scene = bpy.context.scene
old_filepath = scene.render.filepath
old_x = scene.render.resolution_x
old_y = scene.render.resolution_y
old_percentage = scene.render.resolution_percentage
old_format = scene.render.image_settings.file_format
old_engine = scene.render.engine
try:
    scene.render.filepath = path
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    if "BLENDER_EEVEE_NEXT" in {{item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}}:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in {{item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}}:
        scene.render.engine = "BLENDER_EEVEE"
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_perspective = "CAMERA"
            area.spaces.active.shading.type = "MATERIAL"
    try:
        bpy.ops.render.opengl(write_still=True, view_context=False)
    except Exception:
        bpy.ops.render.render(write_still=True)
finally:
    scene.render.filepath = old_filepath
    scene.render.resolution_x = old_x
    scene.render.resolution_y = old_y
    scene.render.resolution_percentage = old_percentage
    scene.render.image_settings.file_format = old_format
    scene.render.engine = old_engine

print(json.dumps({{"ok": os.path.exists(path), "path": path, "width": width, "height": height, "frame": frame}}))
"""


def maya_shaded_frame_code(output_path: str, *, width: int = 960, height: int = 540, frame: int | None = None) -> str:
    return f"""
import json
import os
import maya.cmds as cmds
import maya.api.OpenMayaUI as omui
import maya.api.OpenMaya as om

path = {str(output_path)!r}
width = int({int(width)!r})
height = int({int(height)!r})
frame = {int(frame) if frame is not None else None!r}
original_frame = float(cmds.currentTime(q=True))

if frame is not None and abs(float(frame) - original_frame) > 1.0e-6:
    cmds.currentTime(frame, edit=True)

captured = False
err = ""

# Primary Method: Direct OpenMaya GPU Viewport Buffer Capture
try:
    view = omui.M3dView.active3dView()
    mimg = om.MImage()
    view.readColorBuffer(mimg, True)
    mimg.writeToFile(path, "png")
    if os.path.exists(path):
        captured = True
except Exception as e:
    err = str(e)

# Fallback Method: Playblast image output with file renaming safety
if not captured:
    try:
        res = cmds.playblast(
            frame=[int(cmds.currentTime(q=True))],
            format="image",
            completeFilename=path,
            compression="png",
            viewer=False,
            showOrnaments=False,
            percent=100,
            widthHeight=[width, height],
            forceOverwrite=True,
        )
        if os.path.exists(path):
            captured = True
        else:
            folder = os.path.dirname(path)
            base = os.path.basename(path)
            prefix = os.path.splitext(base)[0]
            if os.path.exists(folder):
                for f in os.listdir(folder):
                    if f.startswith(prefix) and f.endswith(".png"):
                        full_p = os.path.join(folder, f)
                        if os.path.exists(full_p):
                            os.replace(full_p, path)
                            captured = True
                            break
    except Exception as exc:
        err = f"OpenMaya: {err} | Playblast: {exc}"

if abs(float(cmds.currentTime(q=True)) - original_frame) > 1.0e-6:
    cmds.currentTime(original_frame, edit=True)

written = path if captured and os.path.exists(path) else ""
print(json.dumps({{"ok": captured, "path": written, "width": width, "height": height, "frame": frame, "error": err if not captured else ""}}))
"""


def motionbuilder_shaded_frame_code(output_path: str, *, width: int = 960, height: int = 540, frame: int | None = None) -> str:
    return f"""
import json
import os
import pyfbsdk

path = {str(output_path)!r}
width = int({int(width)!r})
height = int({int(height)!r})
frame = {int(frame) if frame is not None else None!r}

if frame is not None:
    pyfbsdk.FBSystem().LocalTime = pyfbsdk.FBTime(0, 0, 0, int(frame))

ok = False
error = ""
try:
    opts = pyfbsdk.FBVideoGrabOptions()
    opts.OutputFileName = path
    opts.BitsPerPixel = pyfbsdk.FBVideoRenderDepth.FBVideoRender32Bits
    opts.ShowCameraLabel = False
    opts.ShowSafeArea = False
    opts.ShowTimeCode = False
    opts.RenderAudio = False
    opts.TimeSpan = pyfbsdk.FBTimeSpan(pyfbsdk.FBSystem().LocalTime, pyfbsdk.FBSystem().LocalTime)
    if hasattr(opts, "Resolution"):
        try:
            opts.Resolution = pyfbsdk.FBVideoRenderResolution.FBVideoRenderCustom
        except Exception:
            pass
    if hasattr(opts, "Width"):
        opts.Width = width
    if hasattr(opts, "Height"):
        opts.Height = height
    grabber = pyfbsdk.FBApplication().VideoGrabber
    ok = bool(grabber.VideoGrab(opts))
except Exception as exc:
    error = str(exc)

print(json.dumps({{"ok": bool(ok and os.path.exists(path)), "path": path, "width": width, "height": height, "frame": frame, "error": error}}))
"""


def unreal_shaded_frame_code(
    output_path: str,
    *,
    width: int = 960,
    height: int = 540,
    frame: int | None = None,
    drive_viewport_camera: bool = False,
) -> str:
    return f"""
import json
import os
import time
import unreal

path = {str(output_path)!r}
width = int({int(width)!r})
height = int({int(height)!r})
drive_viewport_camera = {bool(drive_viewport_camera)!r}

ok = False
error = ""
actor = None
try:
    for candidate in unreal.EditorLevelLibrary.get_all_level_actors():
        try:
            if isinstance(candidate, unreal.CameraActor) and (candidate.get_actor_label() == "TechConnector_Camera" or candidate.get_name().startswith("TechConnector_Camera")):
                actor = candidate
                break
        except Exception:
            pass
except Exception:
    actor = None
if actor is not None and drive_viewport_camera:
    try:
        unreal.EditorLevelLibrary.set_selected_level_actors([actor])
    except Exception:
        pass
    try:
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if hasattr(subsystem, "pilot_level_actor"):
            subsystem.pilot_level_actor(actor)
        if hasattr(subsystem, "set_level_viewport_camera_info"):
            loc = actor.get_actor_location()
            rot = actor.get_actor_rotation()
            subsystem.set_level_viewport_camera_info(loc, rot)
    except Exception:
        pass
try:
    task = unreal.AutomationLibrary.take_high_res_screenshot(width, height, path)
    ok = True
except Exception as exc:
    error = str(exc)
    try:
        unreal.SystemLibrary.execute_console_command(None, "HighResShot " + str(width) + "x" + str(height) + " filename=" + path)
        ok = True
    except Exception as fallback_exc:
        error = error + "; " + str(fallback_exc)

written = path
deadline = time.time() + 3.0
while time.time() < deadline and not os.path.exists(written):
    time.sleep(0.1)
if not os.path.exists(written):
    try:
        unreal.SystemLibrary.execute_console_command(None, 'HighResShot ' + str(width) + 'x' + str(height) + ' filename="' + path + '"')
    except Exception as fallback_exc:
        error = (error + "; " if error else "") + str(fallback_exc)
    deadline = time.time() + 3.0
    while time.time() < deadline and not os.path.exists(written):
        time.sleep(0.1)
if not os.path.exists(written):
    directory = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        for name in os.listdir(directory):
            if stem in name and name.lower().endswith((".png", ".jpg", ".jpeg")):
                written = os.path.join(directory, name)
                break
    except Exception:
        pass
exists = os.path.exists(written)
print(json.dumps({{"ok": bool(ok and exists), "path": written, "width": width, "height": height, "frame": {int(frame) if frame is not None else None!r}, "error": error if exists else (error or "Unreal screenshot command completed but no image file was written.")}}))
"""
