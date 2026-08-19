"""Restore linked DCC files without treating transient bridge ports as identity."""

from __future__ import annotations

import glob
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tech_connector.game_engine.scene.federated_scene_service import (
    normalize_dcc_session_state,
    reconcile_scene_sources,
)


RESTORE_POLICY_ASK = "ask"
RESTORE_POLICY_AUTOMATIC = "automatic"
RESTORE_POLICY_CACHED_ONLY = "cached_only"
RESTORE_POLICIES = {RESTORE_POLICY_ASK, RESTORE_POLICY_AUTOMATIC, RESTORE_POLICY_CACHED_ONLY}


@dataclass
class DccRestoreLaunch:
    provider: str
    source_path: str
    executable_path: str
    process: subprocess.Popen[Any]
    launched_at: float


def normalize_restore_policy(value: str | None) -> str:
    policy = str(value or RESTORE_POLICY_ASK).strip().lower()
    return policy if policy in RESTORE_POLICIES else RESTORE_POLICY_ASK


def discover_dcc_executable(provider: str, executable_hint: str = "") -> str:
    hint = str(Path(str(executable_hint or "")).expanduser().resolve()) if executable_hint else ""
    if hint and Path(hint).is_file():
        return hint
    patterns = {
        "maya": [r"C:\Program Files\Autodesk\Maya*\bin\maya.exe"],
        "blender": [
            r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        ],
        "3dsmax": [r"C:\Program Files\Autodesk\3ds Max *\3dsmax.exe"],
        "motionbuilder": [
            r"C:\Program Files\Autodesk\MotionBuilder*\bin\x64\motionbuilder.exe",
            r"C:\Program Files\Autodesk\MotionBuilder*\bin\motionbuilder.exe",
        ],
        "houdini": [
            r"C:\Program Files\Side Effects Software\Houdini *\bin\houdinifx.exe",
            r"C:\Program Files\Side Effects Software\Houdini *\bin\houdini.exe",
        ],
        "unreal": [
            r"C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UnrealEditor.exe",
            r"C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UE4Editor.exe",
        ],
        "unity": [r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe"],
        "substance_painter": [
            r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe",
            r"C:\Program Files\Adobe\Adobe Substance 3D Painter *\Adobe Substance 3D Painter.exe",
        ],
        "photoshop": [r"C:\Program Files\Adobe\Adobe Photoshop *\Photoshop.exe"],
        "gimp": [
            r"C:\Program Files\GIMP *\bin\gimp-*.exe",
            r"C:\Program Files\GIMP *\bin\gimp.exe",
        ],
    }
    matches: list[str] = []
    for pattern in patterns.get(str(provider or "").lower(), []):
        matches.extend(glob.glob(pattern))
    discovered = sorted({str(Path(match).resolve()) for match in matches}, key=str.lower, reverse=True)
    return discovered[0] if discovered else ""


def dcc_launch_command(provider: str, executable_path: str, source_path: str) -> list[str]:
    provider_key = str(provider or "").strip().lower().split(":", 1)[0]
    source = str(Path(source_path).expanduser().resolve())
    if provider_key == "maya":
        return [executable_path, "-file", source]
    if provider_key in {
        "blender", "3dsmax", "motionbuilder", "houdini", "substance_painter",
        "unreal", "photoshop", "gimp",
    }:
        return [executable_path, source]
    if provider_key == "unity":
        source_object = Path(source)
        if source_object.suffix.lower() == ".unity" and source_object.parent.name.lower() == "assets":
            source_object = source_object.parent.parent
        elif source_object.is_file():
            source_object = source_object.parent
        project = str(source_object)
        return [executable_path, "-projectPath", project]
    raise ValueError(f"Automatic launch is not supported for {provider_key.title()}.")


def launch_dcc_source(
    source: dict[str, Any],
    *,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> DccRestoreLaunch:
    provider = str(source.get("provider") or "").strip().lower().split(":", 1)[0]
    source_path = str(source.get("source_path") or "")
    source_object = Path(source_path).expanduser()
    source_exists = source_object.is_file() or (provider == "unity" and source_object.is_dir())
    if not source_path or not source_exists:
        raise FileNotFoundError(f"Linked source does not exist: {source_path}")
    executable = discover_dcc_executable(provider, str(source.get("executable_hint") or ""))
    if not executable:
        raise FileNotFoundError(f"No installed {provider.title()} executable was found.")
    env = dict(os.environ)
    env["TECH_CONNECTOR_RESTORING_SCENE"] = str(source.get("source_id") or source_path)
    process = popen(
        dcc_launch_command(provider, executable, source_path),
        env=env,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    return DccRestoreLaunch(provider, source_path, executable, process, time.monotonic())


def wait_for_launched_session(
    launch: DccRestoreLaunch,
    discover_sessions: Callable[[], list[dict[str, Any]]],
    *,
    cancel_event: threading.Event | None = None,
    timeout: float = 60.0,
    poll_seconds: float = 0.5,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.1, float(timeout))
    target_path = os.path.normcase(os.path.abspath(launch.source_path))
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            return None
        if launch.process.poll() is not None:
            return None
        for session in discover_sessions() or []:
            if str(session.get("provider") or "").lower().split(":", 1)[0] != launch.provider:
                continue
            scene_path = str(session.get("scene") or "")
            same_scene = bool(
                scene_path
                and os.path.normcase(os.path.abspath(os.path.expanduser(scene_path))) == target_path
            )
            same_process = int(session.get("process_id") or session.get("pid") or 0) == int(launch.process.pid)
            if same_scene or same_process:
                return dict(session)
        if cancel_event is not None:
            cancel_event.wait(max(0.05, float(poll_seconds)))
        else:
            time.sleep(max(0.05, float(poll_seconds)))
    return None


def dcc_session_state_restore_code(provider: str, state: dict[str, Any]) -> str:
    """Build bounded host-local code for portable camera/frame restoration."""

    provider_key = str(provider or "").strip().lower().split(":", 1)[0]
    normalized = normalize_dcc_session_state(state, provider=provider_key)
    timeline = normalized["timeline"]
    frame = float(timeline["current"])
    camera = str(normalized["camera"]["native_id"] or "")
    selection = list(normalized.get("selection_native_ids") or [])
    if provider_key == "maya":
        return f"""
import json
import maya.cmds as cmds
frame = {frame!r}
camera = {camera!r}
selection = {selection!r}
cmds.play(state=False)
if camera:
    matches = cmds.ls(camera, long=True) or cmds.ls(camera.split('|')[-1], long=True) or []
    if not matches:
        raise RuntimeError("Saved Maya camera no longer exists: " + camera)
    camera = matches[0]
    panels = cmds.getPanel(type="modelPanel") or []
    active = [panel for panel in panels if cmds.modelEditor(panel, q=True, activeView=True)]
    panel = (active or panels or [""])[0]
    if not panel:
        raise RuntimeError("No Maya model panel is available for camera restoration.")
    cmds.modelPanel(panel, e=True, camera=camera)
cmds.currentTime(frame, edit=True)
existing_selection = [node for node in selection if cmds.objExists(node)]
if existing_selection:
    cmds.select(existing_selection, replace=True)
print(json.dumps({{"ok": True, "frame": float(cmds.currentTime(q=True)), "camera": camera}}))
"""
    if provider_key == "blender":
        return f"""
import json
import bpy
frame = {frame!r}
camera_name = {camera!r}.split('|')[-1]
scene = bpy.context.scene
if camera_name:
    camera = bpy.data.objects.get(camera_name)
    if camera is None or camera.type != 'CAMERA':
        raise RuntimeError("Saved Blender camera no longer exists: " + camera_name)
    restored_view = False
    for area in bpy.context.screen.areas if bpy.context.screen else []:
        if area.type != 'VIEW_3D':
            continue
        space = area.spaces.active
        space.use_local_camera = True
        space.camera = camera
        space.region_3d.view_perspective = 'CAMERA'
        restored_view = True
    if not restored_view:
        raise RuntimeError("No Blender 3D viewport is available for camera restoration.")
scene.frame_set(int(round(frame)))
print(json.dumps({{"ok": True, "frame": float(scene.frame_current), "camera": camera_name}}))
"""
    if provider_key == "houdini":
        return f"""
import json
import hou
frame = {frame!r}
camera_path = {camera!r}
if camera_path:
    camera = hou.node(camera_path)
    if camera is None:
        raise RuntimeError("Saved Houdini camera no longer exists: " + camera_path)
    desktop = hou.ui.curDesktop()
    viewers = desktop.paneTabsOfType(hou.paneTabType.SceneViewer) if desktop else []
    if not viewers:
        raise RuntimeError("No Houdini Scene Viewer is available for camera restoration.")
    viewers[0].curViewport().setCamera(camera)
hou.setFrame(frame)
print(json.dumps({{"ok": True, "frame": float(hou.frame()), "camera": camera_path}}))
"""
    if provider_key == "motionbuilder":
        return f"""
import json
from pyfbsdk import FBFindModelByLabelName, FBSystem, FBTime
frame = {frame!r}
camera_name = {camera!r}.split('|')[-1]
system = FBSystem()
if camera_name:
    camera = FBFindModelByLabelName(camera_name)
    if camera is None:
        raise RuntimeError("Saved MotionBuilder camera no longer exists: " + camera_name)
    system.Renderer.CurrentCamera = camera
system.LocalTime = FBTime(0, 0, 0, int(round(frame)))
print(json.dumps({{"ok": True, "frame": frame, "camera": camera_name}}))
"""
    if provider_key == "3dsmax":
        return f"""
import json
from pymxs import runtime as rt
frame = {frame!r}
camera_name = {camera!r}.split('|')[-1]
if camera_name:
    camera = rt.getNodeByName(camera_name)
    if camera is None:
        raise RuntimeError("Saved 3ds Max camera no longer exists: " + camera_name)
    rt.viewport.setCamera(camera)
rt.sliderTime = frame
print(json.dumps({{"ok": True, "frame": float(rt.sliderTime), "camera": camera_name}}))
"""
    if provider_key == "unreal" and not camera:
        return f"""
import json
import unreal
frame = int(round({frame!r}))
library = unreal.LevelSequenceEditorBlueprintLibrary
sequence = library.get_current_level_sequence()
if sequence is None:
    raise RuntimeError("No open Unreal Sequencer timeline is available for restoration.")
frame_time = unreal.FrameTime(unreal.FrameNumber(frame), 0.0)
if hasattr(library, "set_current_time"):
    library.set_current_time(frame_time)
elif hasattr(library, "set_current_local_time"):
    library.set_current_local_time(frame_time)
else:
    raise RuntimeError("This Unreal version cannot set Sequencer time through Python.")
print(json.dumps({{"ok": True, "frame": frame, "camera": ""}}))
"""
    if provider_key == "unreal":
        raise NotImplementedError("Unreal camera-cut restoration requires a Sequencer binding identifier.")
    raise NotImplementedError(f"Portable session-state restoration is not available for {provider_key or 'unknown'}.")


def restore_scene_sources(
    sources: list[dict[str, Any]],
    *,
    policy: str,
    discover_sessions: Callable[[], list[dict[str, Any]]],
    open_source: Callable[[str, str], tuple[bool, str]],
    capture_snapshot: Callable[[str], tuple[bool, Any]] | None = None,
    apply_session_state: Callable[[str, dict[str, Any]], tuple[bool, str]] | None = None,
    launch_source: Callable[[dict[str, Any]], DccRestoreLaunch] = launch_dcc_source,
    cancel_event: threading.Event | None = None,
    launch_timeout: float = 60.0,
) -> dict[str, Any]:
    """Reattach exact sessions, safely reuse idle sessions, or launch a separate DCC."""
    normalized_policy = normalize_restore_policy(policy)
    report: dict[str, Any] = {
        "policy": normalized_policy,
        "entries": [],
        "session_keys": [],
        "snapshots": {},
        "launches": [],
        "session_state_failures": [],
        "canceled": False,
    }
    if normalized_policy == RESTORE_POLICY_CACHED_ONLY:
        report["entries"] = [
            {"source": dict(source), "status": "cached_only", "message": "Using embedded cached scene."}
            for source in sources
        ]
        return report

    sessions = discover_sessions() or []
    document = type("RestoreDocument", (), {"sources": sources})()
    reconciliation = reconcile_scene_sources(document, sessions)
    for item in reconciliation:
        if cancel_event is not None and cancel_event.is_set():
            report["canceled"] = True
            break
        source = dict(item.get("source") or {})
        action = str(item.get("action") or "offline")
        session_key = str(item.get("session_key") or "")
        status = action
        message = ""
        launch: DccRestoreLaunch | None = None
        state_status = "not_applicable"
        state_message = ""
        if action == "attach":
            status = "attached"
        elif action == "open_source":
            ok, message = open_source(session_key, str(source.get("source_path") or ""))
            if not ok:
                target_path = os.path.normcase(os.path.abspath(os.path.expanduser(str(source.get("source_path") or ""))))
                recovered = next(
                    (
                        session for session in (discover_sessions() or [])
                        if str(session.get("provider") or "").lower().split(":", 1)[0]
                        == str(source.get("provider") or "").lower().split(":", 1)[0]
                        and str(session.get("scene") or "")
                        and os.path.normcase(os.path.abspath(os.path.expanduser(str(session.get("scene"))))) == target_path
                    ),
                    None,
                )
                if recovered is not None:
                    ok = True
                    session_key = str(recovered.get("key") or session_key)
                    message = "The DCC bridge reconnected after opening the linked source."
            status = "opened" if ok else "open_failed"
            if not ok:
                action = "launch_source"
        if action == "launch_source":
            try:
                launch = launch_source(source)
                report["launches"].append(launch)
                session = wait_for_launched_session(
                    launch,
                    discover_sessions,
                    cancel_event=cancel_event,
                    timeout=launch_timeout,
                )
                if session is None:
                    status = "launch_timeout"
                    message = "The DCC launched but its bridge did not identify the linked scene in time."
                    session_key = ""
                else:
                    session_key = str(session.get("key") or "")
                    status = "launched"
                    message = f"Launched {source.get('provider', '')} and restored the linked file."
            except Exception as exc:
                status = "launch_failed"
                message = str(exc)
                session_key = ""
        if session_key and status in {"attached", "opened", "launched"}:
            report["session_keys"].append(session_key)
            saved_state = source.get("session_state") if isinstance(source.get("session_state"), dict) else None
            state_status = "not_saved"
            if saved_state is not None:
                normalized_state = normalize_dcc_session_state(
                    saved_state,
                    provider=str(source.get("provider") or ""),
                )
                if apply_session_state is None:
                    state_status = "adapter_missing"
                    state_message = "No session-state restoration adapter is registered."
                else:
                    try:
                        state_ok, state_message = apply_session_state(session_key, normalized_state)
                    except Exception as exc:
                        state_ok, state_message = False, str(exc)
                    state_status = "restored" if state_ok else "restore_failed"
                if state_status != "restored":
                    report["session_state_failures"].append({
                        "session_key": session_key,
                        "source_id": str(source.get("source_id") or ""),
                        "status": state_status,
                        "message": state_message,
                    })
            if capture_snapshot is not None:
                ok, snapshot_or_error = capture_snapshot(session_key)
                if ok and isinstance(snapshot_or_error, dict):
                    report["snapshots"][session_key] = snapshot_or_error
                else:
                    message = (message + " " + str(snapshot_or_error)).strip()
        report["entries"].append({
            "source": source,
            "action": item.get("action"),
            "status": status,
            "session_key": session_key,
            "message": message,
            "source_changed": bool(item.get("source_changed")),
            "launched_process_id": int(launch.process.pid) if launch is not None else 0,
            "session_state_status": state_status,
            "session_state_message": state_message,
            "restoration_complete": (
                status in {"attached", "opened", "launched"}
                and state_status in {"not_saved", "restored"}
            ),
        })
    report["session_keys"] = list(dict.fromkeys(key for key in report["session_keys"] if key))
    return report
