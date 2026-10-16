"""Blender host adapter for the cross-DCC Sequence Workspace."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from utilities.sequence_workspace import (
    entry_output_path, new_document, new_entry, normalize_document, safe_name,
)


SCENE_DOCUMENT_KEY = "tc_sequence_workspace"
ENGINE_PUBLISHER_KEY = "tc_sequence_engine_publisher"


def _bpy(module=None):
    if module is not None:
        return module
    import bpy
    return bpy


def frames_per_second(scene=None, *, bpy_module=None) -> float:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    render = scene.render
    return float(render.fps) / max(0.001, float(render.fps_base))


def scene_path(*, bpy_module=None) -> str:
    return str(_bpy(bpy_module).data.filepath or "").replace("\\", "/")


def display_range(scene=None, *, bpy_module=None) -> tuple[int, int]:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    return int(scene.frame_start), int(scene.frame_end)


def set_display_range(start_frame: int, end_frame: int, scene=None, *, bpy_module=None) -> None:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    start, end = sorted((int(start_frame), int(end_frame)))
    scene.frame_start, scene.frame_end = start, end
    scene.frame_set(start)


def selected_node_names(*, bpy_module=None) -> list[str]:
    return [str(item.name) for item in _bpy(bpy_module).context.selected_objects]


def camera_names(*, bpy_module=None) -> list[str]:
    bpy = _bpy(bpy_module)
    return sorted(str(item.name) for item in bpy.data.objects if getattr(item, "type", "") == "CAMERA")


def armature_names(*, bpy_module=None) -> list[str]:
    bpy = _bpy(bpy_module)
    return sorted(str(item.name) for item in bpy.data.objects if getattr(item, "type", "") == "ARMATURE")


def read_document(scene=None, *, bpy_module=None) -> dict[str, Any]:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    raw = scene.get(SCENE_DOCUMENT_KEY, "") if hasattr(scene, "get") else ""
    try:
        payload = json.loads(str(raw)) if raw else {}
    except (TypeError, ValueError):
        payload = {}
    return normalize_document(
        payload,
        host="blender",
        export_directory=_default_export_directory(bpy),
        fps=frames_per_second(scene, bpy_module=bpy),
    )


def write_document(document: Mapping[str, Any], scene=None, *, bpy_module=None) -> dict[str, Any]:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    normalized = normalize_document(
        document,
        host="blender",
        export_directory=_default_export_directory(bpy),
        fps=frames_per_second(scene, bpy_module=bpy),
    )
    scene[SCENE_DOCUMENT_KEY] = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return normalized


def set_engine_context(
    *, status: str, project: str = "", known_skeletons: Iterable[str] = (),
    message: str = "", scene=None, bpy_module=None,
) -> dict[str, Any]:
    """Update connection facts supplied by Tech Connector or an engine bridge."""
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    document = read_document(scene, bpy_module=bpy)
    document["engine"] = {
        "status": str(status), "project": str(project),
        "known_skeletons": [str(value) for value in known_skeletons],
        "message": str(message),
    }
    return write_document(document, scene, bpy_module=bpy)


def publish_document(document: Mapping[str, Any], *, bpy_module=None) -> dict[str, Any]:
    """Publish through a real engine callback installed by Tech Connector."""
    bpy = _bpy(bpy_module)
    publisher = bpy.app.driver_namespace.get(ENGINE_PUBLISHER_KEY)
    if not callable(publisher):
        raise RuntimeError("No engine publisher is connected. Local FBX export is still available.")
    result = publisher(normalize_document(document, host="blender"))
    if isinstance(result, Mapping):
        return dict(result)
    return {"ok": bool(result), "result": result}


def install_unreal_publisher(
    *, destination_path="/Game/Animations", mode="gameplay", conflict_policy="update",
    source_control_policy="auto", unreal_project_path="", unreal_command_path="",
    log_file_path="", bpy_module=None,
) -> None:
    """Install the concrete Tech Connector → Unreal Sequence publisher."""
    bpy = _bpy(bpy_module)
    from unreal_tools.sequence_publish_adapter import publish_sequence_workspace

    def publisher(document):
        return publish_sequence_workspace(
            document, mode=mode, destination_path=destination_path,
            conflict_policy=conflict_policy, source_control_policy=source_control_policy,
            unreal_project_path=unreal_project_path,
            unreal_command_path=unreal_command_path, log_file_path=log_file_path,
        )

    bpy.app.driver_namespace[ENGINE_PUBLISHER_KEY] = publisher


def entries_from_selection(scene=None, *, bpy_module=None) -> list[dict[str, Any]]:
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    selection = list(bpy.context.selected_objects)
    start, end = display_range(scene, bpy_module=bpy)
    export_directory = _default_export_directory(bpy)
    armatures = [item for item in selection if getattr(item, "type", "") == "ARMATURE"]
    targets = armatures or selection
    entries: list[dict[str, Any]] = []
    for target in targets:
        name = str(target.name)
        related = [name]
        if getattr(target, "type", "") == "ARMATURE":
            related.extend(
                str(item.name) for item in bpy.data.objects
                if getattr(item, "parent", None) == target
            )
        entries.append(new_entry(
            name, start, end, export_directory=export_directory,
            namespace=name, skeleton=name if getattr(target, "type", "") == "ARMATURE" else "",
            nodes=related,
        ))
    return entries


def entries_from_timeline(scene=None, *, bpy_module=None) -> list[dict[str, Any]]:
    """Create camera and character export rows from Blender timeline markers."""
    bpy = _bpy(bpy_module)
    scene = scene or bpy.context.scene
    start, end = display_range(scene, bpy_module=bpy)
    markers = sorted(list(scene.timeline_markers), key=lambda item: int(item.frame))
    ranges: list[tuple[str, int, int, str]] = []
    for index, marker in enumerate(markers):
        shot_start = max(start, int(marker.frame))
        shot_end = min(end, int(markers[index + 1].frame) - 1) if index + 1 < len(markers) else end
        if shot_end < shot_start:
            continue
        camera = getattr(marker, "camera", None) or getattr(scene, "camera", None)
        ranges.append((str(marker.name or f"Shot_{index + 1:03d}"), shot_start, shot_end,
                       str(camera.name) if camera is not None else ""))
    if not ranges:
        camera = getattr(scene, "camera", None)
        ranges = [("Scene", start, end, str(camera.name) if camera is not None else "")]

    directory = _default_export_directory(bpy)
    rigs = armature_names(bpy_module=bpy)
    entries: list[dict[str, Any]] = []
    for shot, shot_start, shot_end, camera in ranges:
        if camera:
            entries.append(new_entry(
                f"{shot}_{camera}", shot_start, shot_end, export_directory=directory,
                nodes=[camera], shot=shot, camera=camera, color="#4f9dd9",
            ))
        for rig in rigs:
            related = [rig] + [
                str(item.name) for item in bpy.data.objects
                if getattr(getattr(item, "parent", None), "name", "") == rig
            ]
            entries.append(new_entry(
                f"{shot}_{rig}", shot_start, shot_end, export_directory=directory,
                namespace=rig, skeleton=rig, nodes=related, shot=shot, camera=camera,
                color="#9473d1",
            ))
    return entries


def export_entry(entry: Mapping[str, Any], *, default_directory: str = "", bpy_module=None) -> dict[str, Any]:
    bpy = _bpy(bpy_module)
    scene = bpy.context.scene
    raw_path = entry_output_path(entry, default_directory)
    if hasattr(bpy, "path") and hasattr(bpy.path, "abspath"):
        raw_path = bpy.path.abspath(raw_path)
    path = Path(raw_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = _resolve_nodes(entry, bpy)
    if not nodes:
        nodes = list(bpy.context.selected_objects)
    if not nodes:
        raise ValueError(f"No Blender objects resolve for '{entry.get('name') or 'Animation'}'.")

    with _preserved_scene_state(bpy):
        for item in bpy.context.selected_objects:
            item.select_set(False)
        for item in nodes:
            item.select_set(True)
        bpy.context.view_layer.objects.active = nodes[0]
        scene.frame_start = int(entry.get("start_frame") or scene.frame_start)
        scene.frame_end = int(entry.get("end_frame") or scene.frame_end)
        result = bpy.ops.export_scene.fbx(
            filepath=str(path), use_selection=True, object_types={"ARMATURE", "MESH", "EMPTY", "CAMERA"},
            bake_anim=True, bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False,
            bake_anim_simplify_factor=0.0, add_leaf_bones=False,
        )
        if "FINISHED" not in set(result):
            raise RuntimeError(f"Blender FBX export did not finish: {result}")
    return {"ok": True, "filepath": str(path), "nodes": [str(item.name) for item in nodes]}


def show_sequence_manager() -> dict[str, Any]:
    from . import sequence_ui
    sequence_ui.register()
    return {"ok": True, "message": "Sequence Workspace is available in the Scene properties and 3D View sidebar."}


def _resolve_nodes(entry: Mapping[str, Any], bpy) -> list[Any]:
    names = [str(value) for value in entry.get("nodes") or ()]
    camera = str(entry.get("camera") or "")
    if camera:
        names.append(camera)
    namespace = str(entry.get("namespace") or "")
    values: list[Any] = []
    for item in bpy.data.objects:
        name = str(item.name)
        if name in names or (namespace and (name == namespace or name.startswith(namespace + ":"))):
            values.append(item)
    return values


@contextmanager
def _preserved_scene_state(bpy):
    scene = bpy.context.scene
    selected = list(bpy.context.selected_objects)
    active = getattr(bpy.context.view_layer.objects, "active", None)
    start, end, current = int(scene.frame_start), int(scene.frame_end), int(scene.frame_current)
    try:
        yield
    finally:
        for item in list(bpy.context.selected_objects):
            item.select_set(False)
        for item in selected:
            try:
                item.select_set(True)
            except ReferenceError:
                pass
        bpy.context.view_layer.objects.active = active
        scene.frame_start, scene.frame_end = start, end
        scene.frame_set(current)


def _default_export_directory(bpy) -> str:
    filepath = str(getattr(bpy.data, "filepath", "") or "")
    base = Path(filepath).parent if filepath else Path.home()
    return str(base / "Exports").replace("\\", "/")
