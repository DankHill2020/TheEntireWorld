"""Host-neutral document helpers for the cross-DCC Sequence Workspace.

The UI implementations in Blender, 3ds Max, Maya, and MotionBuilder use
different widget toolkits and host APIs.  This module deliberately knows
nothing about either.  It owns the small, portable export-job document that
can be stored in a scene or exchanged with Tech Connector.
"""

from __future__ import annotations

from copy import deepcopy
import os
import re
from typing import Any, Iterable, Mapping
import uuid


SEQUENCE_WORKSPACE_SCHEMA = "tech_connector.sequence_workspace.v1"
DEFAULT_ROW_COLOR = "#5f8fb8"


def new_document(
    *, host: str = "", export_directory: str = "", fps: float = 24.0,
) -> dict[str, Any]:
    return {
        "schema": SEQUENCE_WORKSPACE_SCHEMA,
        "version": 1,
        "host": str(host),
        "export_directory": _clean_path(export_directory),
        "fps": max(0.001, float(fps)),
        "entries": [],
        "engine": {
            "status": "offline",
            "project": "",
            "known_skeletons": [],
            "message": "Local authoring and FBX export are available.",
        },
    }


def new_entry(
    name: str,
    start_frame: int,
    end_frame: int,
    *,
    export_directory: str = "",
    namespace: str = "",
    skeleton: str = "",
    nodes: Iterable[str] | None = None,
    color: str = DEFAULT_ROW_COLOR,
    shot: str = "",
    camera: str = "",
    enabled: bool = True,
    entry_id: str = "",
) -> dict[str, Any]:
    start = int(start_frame)
    end = int(end_frame)
    if end < start:
        start, end = end, start
    return {
        "id": str(entry_id or f"entry_{uuid.uuid4().hex[:12]}"),
        "name": safe_name(name or "Animation"),
        "export_directory": _clean_path(export_directory),
        "start_frame": start,
        "end_frame": end,
        "namespace": str(namespace or ""),
        "skeleton": str(skeleton or ""),
        "nodes": [str(value) for value in (nodes or ()) if str(value)],
        "color": normalize_color(color),
        "shot": str(shot or ""),
        "camera": str(camera or ""),
        "enabled": bool(enabled),
    }


def normalize_document(
    value: Mapping[str, Any] | None,
    *,
    host: str = "",
    export_directory: str = "",
    fps: float = 24.0,
) -> dict[str, Any]:
    source = dict(value or {})
    result = new_document(
        host=str(source.get("host") or host),
        export_directory=str(source.get("export_directory") or export_directory),
        fps=float(source.get("fps") or fps),
    )
    engine = dict(source.get("engine") or {})
    status = str(engine.get("status") or "offline").casefold()
    if status not in {"offline", "connecting", "connected", "attention"}:
        status = "attention"
    result["engine"] = {
        "status": status,
        "project": str(engine.get("project") or ""),
        "known_skeletons": sorted({str(value) for value in engine.get("known_skeletons") or () if str(value)}),
        "message": str(engine.get("message") or ""),
    }
    seen: set[str] = set()
    for raw in source.get("entries") or ():
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        entry = new_entry(
            str(row.get("name") or "Animation"),
            int(row.get("start_frame") or 0),
            int(row.get("end_frame") or 0),
            export_directory=str(row.get("export_directory") or result["export_directory"]),
            namespace=str(row.get("namespace") or ""),
            skeleton=str(row.get("skeleton") or ""),
            nodes=_node_values(row.get("nodes")),
            color=str(row.get("color") or DEFAULT_ROW_COLOR),
            shot=str(row.get("shot") or ""),
            camera=str(row.get("camera") or ""),
            enabled=bool(row.get("enabled", True)),
            entry_id=str(row.get("id") or ""),
        )
        if entry["id"] in seen:
            entry["id"] = f"entry_{uuid.uuid4().hex[:12]}"
        seen.add(entry["id"])
        result["entries"].append(entry)
    return result


def duplicate_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    clone = deepcopy(dict(entry))
    clone["id"] = f"entry_{uuid.uuid4().hex[:12]}"
    clone["name"] = safe_name(f"{clone.get('name') or 'Animation'}_copy")
    return normalize_document({"entries": [clone]})["entries"][0]


def validate_document(value: Mapping[str, Any] | None) -> tuple[dict[str, Any], ...]:
    document = normalize_document(value)
    issues: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    output_paths: dict[str, str] = {}
    for index, entry in enumerate(document["entries"]):
        identifier = str(entry.get("id") or "")
        prefix = f"entries[{index}]"
        if not identifier or identifier in identifiers:
            issues.append(_issue("error", "duplicate_id", "Every entry needs a unique ID.", prefix))
        identifiers.add(identifier)
        if int(entry["end_frame"]) < int(entry["start_frame"]):
            issues.append(_issue("error", "invalid_range", "End frame must not be before start frame.", prefix))
        if not str(entry.get("name") or "").strip():
            issues.append(_issue("error", "missing_name", "Animation name is required.", prefix))
        if entry.get("enabled"):
            if not str(entry.get("export_directory") or document.get("export_directory") or "").strip():
                issues.append(_issue("error", "missing_directory", "Choose an export directory.", prefix))
            path = entry_output_path(entry, document.get("export_directory") or "")
            key = os.path.normcase(path)
            if key in output_paths:
                issues.append(_issue(
                    "error", "duplicate_output",
                    f"Output conflicts with '{output_paths[key]}'.", prefix,
                ))
            output_paths[key] = str(entry.get("name") or "")
        if not entry.get("nodes") and not entry.get("namespace") and not entry.get("camera"):
            issues.append(_issue(
                "warning", "unresolved_source",
                "The entry has no nodes, namespace, or camera; the host selection will be used.", prefix,
            ))
    return tuple(issues)


def entry_output_path(entry: Mapping[str, Any], default_directory: str = "") -> str:
    directory = _clean_path(str(entry.get("export_directory") or default_directory))
    return _clean_path(os.path.join(directory, safe_name(str(entry.get("name") or "Animation")) + ".fbx"))


def enabled_entries(document: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    normalized = normalize_document(document)
    return tuple(deepcopy(row) for row in normalized["entries"] if row.get("enabled", True))


def sequence_preflight(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return local-export and engine-publish readiness without mutating data."""
    document = normalize_document(value)
    issues = list(validate_document(document))
    engine = dict(document.get("engine") or {})
    status = str(engine.get("status") or "offline")
    known = {str(item) for item in engine.get("known_skeletons") or ()}
    entries = []
    publish_blockers = []
    enabled_count = 0
    for index, entry in enumerate(document["entries"]):
        is_enabled = bool(entry.get("enabled", True))
        enabled_count += int(is_enabled)
        skeleton = str(entry.get("skeleton") or "").strip()
        requires_skeleton = bool(entry.get("namespace")) and not (
            entry.get("camera") and not entry.get("namespace")
        )
        if not requires_skeleton:
            resolution = "not_required"
            message = "No target skeleton is required for this entry."
        elif not skeleton:
            resolution = "missing"
            message = "Choose a target skeleton before engine publish."
            if is_enabled:
                publish_blockers.append({"entry": index, "code": "missing_target_skeleton", "message": message})
        elif status != "connected":
            resolution = "manual"
            message = "Manual target saved; it will be resolved when an engine connects."
        elif known and skeleton not in known:
            resolution = "unresolved"
            message = f"The connected engine does not currently contain '{skeleton}'."
            if is_enabled:
                publish_blockers.append({"entry": index, "code": "unresolved_target_skeleton", "message": message})
        elif known:
            resolution = "resolved"
            message = "Target skeleton resolved in the connected engine."
        else:
            resolution = "unverified"
            message = "Engine connected, but its skeleton inventory has not been refreshed."
            if is_enabled:
                publish_blockers.append({"entry": index, "code": "skeleton_inventory_unavailable", "message": message})
        entries.append({
            "id": str(entry.get("id") or ""), "name": str(entry.get("name") or "Animation"),
            "enabled": bool(entry.get("enabled", True)), "skeleton": skeleton,
            "skeleton_resolution": resolution, "message": message,
        })
    errors = [issue for issue in issues if issue["severity"] == "error"]
    if status != "connected":
        publish_blockers.insert(0, {
            "code": "engine_offline", "message": "Connect an engine before publishing.",
        })
    return {
        "engine_status": status,
        "issues": issues,
        "entries": entries,
        "publish_blockers": publish_blockers,
        "can_export": not errors and enabled_count > 0,
        "can_publish": not errors and enabled_count > 0 and not publish_blockers,
    }


def apply_bulk_update(
    value: Mapping[str, Any], entry_ids: Iterable[str], **changes: Any,
) -> dict[str, Any]:
    """Apply supported inspector values to several entries in one command."""
    document = normalize_document(value)
    selected = {str(identifier) for identifier in entry_ids}
    allowed = {"export_directory", "namespace", "skeleton", "start_frame", "end_frame", "enabled"}
    updates = {key: deepcopy(item) for key, item in changes.items() if key in allowed}
    for entry in document["entries"]:
        if str(entry.get("id") or "") not in selected:
            continue
        entry.update(updates)
        entry["export_directory"] = _clean_path(str(entry.get("export_directory") or ""))
        if int(entry["end_frame"]) < int(entry["start_frame"]):
            entry["start_frame"], entry["end_frame"] = entry["end_frame"], entry["start_frame"]
    return normalize_document(document)


def legacy_anim_dict(document: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Return the Maya/MotionBuilder SequenceUI animation dictionary shape."""
    normalized = normalize_document(document)
    result: dict[str, list[Any]] = {}
    for entry in normalized["entries"]:
        path = entry_output_path(entry, normalized["export_directory"])
        result[path] = [
            int(entry["start_frame"]), int(entry["end_frame"]),
            str(entry.get("namespace") or ""), str(entry.get("skeleton") or ""),
            str(entry.get("color") or DEFAULT_ROW_COLOR), list(entry.get("nodes") or ()) or None,
        ]
    return result


def safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text.strip("._") or "Animation"


def normalize_color(value: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    return DEFAULT_ROW_COLOR


def _node_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value if str(item)]


def _clean_path(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/")


def _issue(severity: str, code: str, message: str, path: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "path": path}
