"""Versioned contracts shared by Sequence publishers and Unreal importers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from typing import Any, Mapping
import uuid


SEQUENCE_IMPORT_SCHEMA = "tech_connector.sequence_import.v2"
SEQUENCE_RESULT_SCHEMA = "tech_connector.sequence_import_result.v1"
CONFLICT_POLICIES = {"update", "version", "skip", "fail"}
SOURCE_CONTROL_POLICIES = {"auto", "required", "off"}


def normalize_sequence_manifest(
    value: Mapping[str, Any] | None,
    *,
    mode: str = "gameplay",
    destination_path: str = "/Game/Animations",
) -> dict[str, Any]:
    """Normalize v2 or legacy Sequence JSON into one explicit import manifest."""
    source = deepcopy(dict(value or {}))
    if source.get("schema") == SEQUENCE_IMPORT_SCHEMA:
        manifest_destination = _package_folder(source.get("destination_path") or destination_path)
        entries = [
            _normalize_entry(row, index, default_destination=manifest_destination)
            for index, row in enumerate(source.get("entries") or ())
        ]
        policy = str(source.get("conflict_policy") or "update").strip().lower()
        if policy not in CONFLICT_POLICIES:
            raise ValueError(f"Unsupported conflict policy: {policy}")
        source_control_policy = str(source.get("source_control_policy") or "auto").strip().lower()
        if source_control_policy not in SOURCE_CONTROL_POLICIES:
            raise ValueError(f"Unsupported source control policy: {source_control_policy}")
        return {
            "schema": SEQUENCE_IMPORT_SCHEMA,
            "version": 2,
            "job_id": str(source.get("job_id") or f"sequence_{uuid.uuid4().hex}"),
            "mode": _mode(source.get("mode") or mode),
            "source_host": str(source.get("source_host") or ""),
            "source_scene": str(source.get("source_scene") or ""),
            "destination_path": manifest_destination,
            "conflict_policy": policy,
            "source_control_policy": source_control_policy,
            "entries": entries,
        }

    entries = []
    inferred_mode = _mode(mode)
    if inferred_mode == "cinematic":
        for shot, rows in source.items():
            for index, row in enumerate(rows if isinstance(rows, list) else ()):
                if not isinstance(row, Mapping):
                    continue
                item = dict(row)
                item.setdefault("shot", str(shot))
                entries.append(_normalize_entry(
                    item, len(entries), default_destination=_package_folder(destination_path),
                ))
    else:
        for index, (source_file, raw) in enumerate(source.items()):
            if not isinstance(raw, (list, tuple)) or len(raw) < 4:
                entries.append(_normalize_entry({
                    "source_file": source_file,
                    "validation_error": "Legacy animation data must contain start, end, namespace, and skeleton.",
                }, index))
                continue
            start, end, namespace, skeleton = raw[:4]
            entries.append(_normalize_entry({
                "source_file": source_file,
                "name": os.path.splitext(os.path.basename(str(source_file)))[0],
                "start_frame": start,
                "end_frame": end,
                "namespace": namespace,
                "target_skeleton": skeleton,
                "nodes": raw[5] if len(raw) > 5 else [],
            }, index))
    return {
        "schema": SEQUENCE_IMPORT_SCHEMA,
        "version": 2,
        "job_id": f"sequence_{uuid.uuid4().hex}",
        "mode": inferred_mode,
        "source_host": "legacy",
        "source_scene": "",
        "destination_path": _package_folder(destination_path),
        "conflict_policy": "update",
        "source_control_policy": "auto",
        "entries": entries,
    }


def validate_sequence_manifest(value: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    manifest = normalize_sequence_manifest(value, mode=str(value.get("mode") or "gameplay"))
    issues = []
    seen_ids = set()
    seen_outputs = set()
    for index, entry in enumerate(manifest["entries"]):
        prefix = f"entries[{index}]"
        entry_id = entry["id"]
        if entry_id in seen_ids:
            issues.append(_issue("error", "duplicate_entry_id", "Entry IDs must be unique.", prefix))
        seen_ids.add(entry_id)
        if entry.get("validation_error"):
            issues.append(_issue("error", "invalid_legacy_entry", entry["validation_error"], prefix))
        if not entry["source_file"]:
            issues.append(_issue("error", "missing_source_file", "Source FBX is required.", prefix))
        if entry["kind"] == "animation" and not entry["target_skeleton"]:
            issues.append(_issue("error", "missing_target_skeleton", "Target skeleton is required.", prefix))
        output_key = (entry["destination_path"], entry["destination_name"].casefold())
        if output_key in seen_outputs:
            issues.append(_issue("error", "duplicate_output", "Multiple entries resolve to the same asset.", prefix))
        seen_outputs.add(output_key)
    return tuple(issues)


def new_import_result(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SEQUENCE_RESULT_SCHEMA,
        "version": 1,
        "job_id": str(manifest.get("job_id") or ""),
        "mode": str(manifest.get("mode") or ""),
        "ok": False,
        "status": "running",
        "started_at": _now(),
        "finished_at": "",
        "imported": [],
        "updated": [],
        "skipped": [],
        "failed": [],
        "warnings": [],
        "sequence_path": "",
    }


def finish_import_result(result: Mapping[str, Any]) -> dict[str, Any]:
    final = deepcopy(dict(result))
    final["finished_at"] = _now()
    final["ok"] = not final.get("failed")
    if final.get("failed") and (final.get("imported") or final.get("updated")):
        final["status"] = "partial"
    elif final.get("failed"):
        final["status"] = "failed"
    elif final.get("skipped") and not (final.get("imported") or final.get("updated")):
        final["status"] = "skipped"
    else:
        final["status"] = "succeeded"
    return final


def cinematic_payload_from_manifest(value: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert the v2 contract to the established Sequencer assembly payload."""
    manifest = normalize_sequence_manifest(value, mode="cinematic", destination_path="/Game/Cinematics")
    shots: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest["entries"]:
        if not entry["enabled"]:
            continue
        shot = entry["shot"] or "Unknown_Shot"
        shots.setdefault(shot, []).append({
            "id": entry["id"],
            "export_path": entry["source_file"],
            "name_space": "CAM" if entry["kind"] == "camera" else entry["namespace"],
            "skeleton": entry["target_skeleton"],
            "blueprint": entry["blueprint"] or None,
            "actor_binding": entry["actor_binding"] or None,
            "nodes": list(entry["nodes"]),
            "start_frame": entry["start_frame"],
            "end_frame": entry["end_frame"],
            "fps": entry["frame_rate_numerator"] / entry["frame_rate_denominator"],
            "frame_rate_numerator": entry["frame_rate_numerator"],
            "frame_rate_denominator": entry["frame_rate_denominator"],
            "root_motion": entry["root_motion"],
        })
    return shots


def _normalize_entry(
    value: Mapping[str, Any], index: int, *, default_destination: str = "/Game/Animations",
) -> dict[str, Any]:
    source = dict(value)
    source_file = str(source.get("source_file") or source.get("export_path") or "").replace("\\", "/")
    namespace = str(source.get("namespace") or source.get("name_space") or "")
    kind = str(source.get("kind") or ("camera" if namespace == "CAM" else "animation")).lower()
    name = str(source.get("name") or os.path.splitext(os.path.basename(source_file))[0] or f"Entry_{index + 1}")
    destination = _package_folder(source.get("destination_path") or default_destination)
    raw_nodes = source.get("nodes") or ()
    if isinstance(raw_nodes, str):
        raw_nodes = [item.strip() for item in raw_nodes.split(",") if item.strip()]
    return {
        "id": str(source.get("id") or f"entry_{index + 1:04d}"),
        "name": name,
        "kind": kind,
        "enabled": bool(source.get("enabled", True)),
        "source_file": source_file,
        "source_hash": str(source.get("source_hash") or ""),
        "namespace": namespace,
        "target_skeleton": str(source.get("target_skeleton") or source.get("skeleton") or ""),
        "destination_path": destination,
        "destination_name": str(source.get("destination_name") or name),
        "start_frame": int(source.get("start_frame") or 0),
        "end_frame": int(source.get("end_frame") or 0),
        "frame_rate_numerator": int(source.get("frame_rate_numerator") or source.get("fps") or 24),
        "frame_rate_denominator": max(1, int(source.get("frame_rate_denominator") or 1)),
        "shot": str(source.get("shot") or ""),
        "blueprint": str(source.get("blueprint") or ""),
        "actor_binding": str(source.get("actor_binding") or ""),
        "nodes": [str(item) for item in raw_nodes if str(item)],
        "root_motion": source.get("root_motion"),
        "validation_error": str(source.get("validation_error") or ""),
    }


def _mode(value: Any) -> str:
    mode = str(value or "gameplay").strip().lower()
    if mode not in {"gameplay", "cinematic"}:
        raise ValueError(f"Unsupported sequence import mode: {mode}")
    return mode


def _package_folder(value: Any) -> str:
    folder = "/" + str(value or "").strip().strip("/")
    if not folder.startswith("/Game/") and folder != "/Game":
        raise ValueError(f"Unreal destination must be under /Game: {folder}")
    return folder.rstrip("/")


def _issue(severity: str, code: str, message: str, path: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, "path": path}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "CONFLICT_POLICIES", "SEQUENCE_IMPORT_SCHEMA", "SEQUENCE_RESULT_SCHEMA",
    "SOURCE_CONTROL_POLICIES",
    "cinematic_payload_from_manifest", "finish_import_result", "new_import_result",
    "normalize_sequence_manifest", "validate_sequence_manifest",
]
