"""3ds Max host adapter for the cross-DCC Sequence Workspace."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Mapping

from utilities.sequence_workspace import entry_output_path, new_entry, normalize_document


ROOT_DOCUMENT_KEY = "tc_sequence_workspace"
_ENGINE_PUBLISHER = None


def _runtime(runtime=None):
    if runtime is not None:
        return runtime
    import pymxs
    return pymxs.runtime


def frames_per_second(*, runtime=None) -> float:
    return float(_runtime(runtime).frameRate)


def scene_path(*, runtime=None) -> str:
    rt = _runtime(runtime)
    return (str(rt.maxFilePath) + str(rt.maxFileName)).replace("\\", "/")


def _frame(value: Any, rt) -> int:
    try:
        return int(round(float(value) / max(1, int(rt.ticksPerFrame))))
    except (TypeError, ValueError):
        return int(value)


def display_range(*, runtime=None) -> tuple[int, int]:
    rt = _runtime(runtime)
    interval = rt.animationRange
    return _frame(interval.start, rt), _frame(interval.end, rt)


def set_display_range(start_frame: int, end_frame: int, *, runtime=None) -> None:
    rt = _runtime(runtime)
    start, end = sorted((int(start_frame), int(end_frame)))
    rt.animationRange = rt.interval(start, end)
    rt.sliderTime = start


def selected_node_names(*, runtime=None) -> list[str]:
    return [str(item.name) for item in list(_runtime(runtime).selection)]


def camera_names(*, runtime=None) -> list[str]:
    rt = _runtime(runtime)
    return sorted(str(item.name) for item in list(rt.cameras))


def rig_names(*, runtime=None) -> list[str]:
    rt = _runtime(runtime)
    result = []
    for item in list(rt.objects):
        class_name = str(rt.classOf(item)).casefold()
        name = str(item.name)
        if "biped" in class_name or "bone" in class_name or class_name == "dummy":
            parent = getattr(item, "parent", None)
            if parent is None:
                result.append(name)
    return sorted(set(result))


def read_document(*, runtime=None) -> dict[str, Any]:
    rt = _runtime(runtime)
    raw = ""
    try:
        raw = str(rt.getUserProp(rt.rootNode, ROOT_DOCUMENT_KEY) or "")
    except Exception:
        pass
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        payload = {}
    return normalize_document(
        payload, host="3dsmax", export_directory=_default_export_directory(rt),
        fps=frames_per_second(runtime=rt),
    )


def write_document(document: Mapping[str, Any], *, runtime=None) -> dict[str, Any]:
    rt = _runtime(runtime)
    normalized = normalize_document(
        document, host="3dsmax", export_directory=_default_export_directory(rt),
        fps=frames_per_second(runtime=rt),
    )
    rt.setUserProp(rt.rootNode, ROOT_DOCUMENT_KEY, json.dumps(normalized, sort_keys=True, separators=(",", ":")))
    return normalized


def set_engine_context(
    *, status: str, project: str = "", known_skeletons=(), message: str = "", runtime=None,
) -> dict[str, Any]:
    rt = _runtime(runtime)
    document = read_document(runtime=rt)
    document["engine"] = {
        "status": str(status), "project": str(project),
        "known_skeletons": [str(value) for value in known_skeletons],
        "message": str(message),
    }
    return write_document(document, runtime=rt)


def install_engine_publisher(callback) -> None:
    """Install the concrete publisher supplied by a Tech Connector session."""
    global _ENGINE_PUBLISHER
    if callback is not None and not callable(callback):
        raise TypeError("Engine publisher must be callable or None.")
    _ENGINE_PUBLISHER = callback


def publish_document(document: Mapping[str, Any]) -> dict[str, Any]:
    if not callable(_ENGINE_PUBLISHER):
        raise RuntimeError("No engine publisher is connected. Local FBX export is still available.")
    result = _ENGINE_PUBLISHER(normalize_document(document, host="3dsmax"))
    if isinstance(result, Mapping):
        return dict(result)
    return {"ok": bool(result), "result": result}


def install_unreal_publisher(
    *, destination_path="/Game/Animations", mode="gameplay", conflict_policy="update",
    source_control_policy="auto", unreal_project_path="", unreal_command_path="",
    log_file_path="",
) -> None:
    """Install the concrete Tech Connector → Unreal Sequence publisher."""
    from unreal_tools.sequence_publish_adapter import publish_sequence_workspace

    def publisher(document):
        return publish_sequence_workspace(
            document, mode=mode, destination_path=destination_path,
            conflict_policy=conflict_policy, source_control_policy=source_control_policy,
            unreal_project_path=unreal_project_path,
            unreal_command_path=unreal_command_path, log_file_path=log_file_path,
        )

    install_engine_publisher(publisher)


def entries_from_selection(*, runtime=None) -> list[dict[str, Any]]:
    rt = _runtime(runtime)
    selection = list(rt.selection)
    start, end = display_range(runtime=rt)
    directory = _default_export_directory(rt)
    entries: list[dict[str, Any]] = []
    roots = [item for item in selection if getattr(item, "parent", None) is None] or selection
    for item in roots:
        name = str(item.name)
        children = [str(child.name) for child in list(getattr(item, "children", []) or [])]
        entries.append(new_entry(
            name, start, end, export_directory=directory, namespace=_namespace(name),
            skeleton=name if _is_rig_node(item, rt) else "", nodes=[name] + children,
        ))
    return entries


def entries_from_cameras(*, runtime=None) -> list[dict[str, Any]]:
    rt = _runtime(runtime)
    start, end = display_range(runtime=rt)
    directory = _default_export_directory(rt)
    return [
        new_entry(
            f"Scene_{camera}", start, end, export_directory=directory,
            nodes=[camera], shot="Scene", camera=camera, color="#4f9dd9",
        )
        for camera in camera_names(runtime=rt)
    ]


def export_entry(entry: Mapping[str, Any], *, default_directory: str = "", runtime=None) -> dict[str, Any]:
    rt = _runtime(runtime)
    path = Path(entry_output_path(entry, default_directory)).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = _resolve_nodes(entry, rt)
    if not nodes:
        nodes = list(rt.selection)
    if not nodes:
        raise ValueError(f"No 3ds Max nodes resolve for '{entry.get('name') or 'Animation'}'.")
    with _preserved_scene_state(rt):
        rt.clearSelection()
        rt.select(nodes)
        set_display_range(int(entry.get("start_frame") or 0), int(entry.get("end_frame") or 0), runtime=rt)
        try:
            rt.FBXExporterSetParam("Animation", True)
            rt.FBXExporterSetParam("BakeAnimation", True)
            rt.FBXExporterSetParam("BakeFrameStart", int(entry.get("start_frame") or 0))
            rt.FBXExporterSetParam("BakeFrameEnd", int(entry.get("end_frame") or 0))
        except Exception:
            pass
        rt.exportFile(str(path), rt.name("noPrompt"), selectedOnly=True, using=rt.FBXEXP)
    if not path.is_file():
        raise RuntimeError(f"3ds Max did not create the expected FBX: {path}")
    return {"ok": True, "filepath": str(path), "nodes": [str(item.name) for item in nodes]}


def show_sequence_manager() -> dict[str, Any]:
    from .sequence_ui import show_sequence_manager as show
    show()
    return {"ok": True, "message": "3ds Max Sequence Workspace opened."}


def _resolve_nodes(entry: Mapping[str, Any], rt) -> list[Any]:
    names = {str(value) for value in entry.get("nodes") or ()}
    camera = str(entry.get("camera") or "")
    if camera:
        names.add(camera)
    namespace = str(entry.get("namespace") or "")
    values = []
    for item in list(rt.objects):
        name = str(item.name)
        if name in names or (namespace and (name == namespace or name.startswith(namespace + ":"))):
            values.append(item)
    return values


@contextmanager
def _preserved_scene_state(rt):
    selected = list(rt.selection)
    interval = rt.animationRange
    current = rt.sliderTime
    try:
        yield
    finally:
        rt.clearSelection()
        if selected:
            rt.select(selected)
        rt.animationRange = interval
        rt.sliderTime = current


def _is_rig_node(item: Any, rt) -> bool:
    name = str(rt.classOf(item)).casefold()
    return "biped" in name or "bone" in name or name == "dummy"


def _namespace(name: str) -> str:
    return str(name).split(":", 1)[0] if ":" in str(name) else str(name)


def _default_export_directory(rt) -> str:
    value = (str(rt.maxFilePath) or str(Path.home())).replace("\\", "/")
    return str(Path(value) / "Exports").replace("\\", "/")
