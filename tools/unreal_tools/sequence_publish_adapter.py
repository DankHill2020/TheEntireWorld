"""Publish portable DCC Sequence Workspace documents into Unreal."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
from typing import Any, Mapping

from unreal_tools.sequence_import_contract import SEQUENCE_IMPORT_SCHEMA
from utilities.sequence_workspace import entry_output_path, normalize_document


def manifest_from_workspace(
    document: Mapping[str, Any],
    *,
    mode: str = "gameplay",
    destination_path: str = "/Game/Animations",
    conflict_policy: str = "update",
    source_control_policy: str = "auto",
) -> dict[str, Any]:
    workspace = normalize_document(document)
    entries = []
    for row in workspace["entries"]:
        source_file = entry_output_path(row, workspace.get("export_directory") or "")
        entries.append({
            "id": row["id"],
            "name": row["name"],
            "kind": "camera" if row.get("camera") else "animation",
            "enabled": bool(row.get("enabled", True)),
            "source_file": source_file,
            "source_hash": _file_sha256(source_file),
            "namespace": "CAM" if row.get("camera") else str(row.get("namespace") or ""),
            "target_skeleton": str(row.get("skeleton") or ""),
            "destination_name": row["name"],
            "start_frame": int(row["start_frame"]),
            "end_frame": int(row["end_frame"]),
            "frame_rate_numerator": int(round(float(workspace.get("fps") or 24) * 1000)),
            "frame_rate_denominator": 1000,
            "shot": str(row.get("shot") or ""),
            "nodes": list(row.get("nodes") or ()),
        })
    return {
        "schema": SEQUENCE_IMPORT_SCHEMA,
        "version": 2,
        "mode": str(mode),
        "source_host": str(workspace.get("host") or ""),
        "destination_path": str(destination_path),
        "conflict_policy": str(conflict_policy),
        "source_control_policy": str(source_control_policy),
        "entries": entries,
    }


def _file_sha256(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_sequence_workspace(
    document: Mapping[str, Any],
    *,
    mode: str = "gameplay",
    destination_path: str = "/Game/Animations",
    conflict_policy: str = "update",
    source_control_policy: str = "auto",
    unreal_project_path: str = "",
    unreal_command_path: str = "",
    log_file_path: str = "",
) -> dict[str, Any]:
    """Submit one workspace through the live bridge, with command fallback when configured."""
    from unreal_tools import unreal_subprocess

    manifest = manifest_from_workspace(
        document, mode=mode, destination_path=destination_path,
        conflict_policy=conflict_policy, source_control_policy=source_control_policy,
    )
    handle, manifest_path = tempfile.mkstemp(prefix="tc_sequence_manifest_", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
        kwargs = {}
        if unreal_command_path:
            kwargs["unreal_command_path"] = unreal_command_path
        preflight = unreal_subprocess.run_preflight_sequence_import(
            manifest_path, unreal_project_path, log_file_path,
            mode=mode, destination_path=destination_path, **kwargs,
        )
        if not preflight.get("can_import"):
            first_error = next((
                issue.get("message")
                for row in preflight.get("entries") or ()
                for issue in row.get("issues") or ()
                if issue.get("severity") == "error"
            ), "Unreal import preflight failed.")
            return {
                "ok": False, "status": "blocked", "job_id": preflight.get("job_id", ""),
                "error": first_error, "preflight": preflight,
            }
        actionable = {
            "create", "update", "create_version",
        }
        if not any(row.get("action") in actionable for row in preflight.get("entries") or ()):
            return {
                "ok": True, "status": "unchanged", "job_id": preflight.get("job_id", ""),
                "message": "All enabled Sequence entries are already up to date.",
                "preflight": preflight,
            }
        if str(mode).lower() == "cinematic":
            result = unreal_subprocess.run_create_cinematic_sequence(
                manifest_path, destination_path, unreal_project_path, log_file_path, **kwargs,
            )
        else:
            result = unreal_subprocess.run_import_gameplay_animations(
                manifest_path, unreal_project_path, log_file_path, **kwargs,
            )
        if isinstance(result, dict):
            result.setdefault("preflight", preflight)
            if not result.get("message"):
                imported = len(result.get("imported") or ())
                updated = len(result.get("updated") or ())
                skipped = len(result.get("skipped") or ())
                failed = len(result.get("failed") or ())
                result["message"] = (
                    f"Unreal import: {imported} created, {updated} updated, "
                    f"{skipped} skipped, {failed} failed."
                )
        return result
    finally:
        try:
            os.unlink(manifest_path)
        except OSError:
            pass


def preflight_sequence_workspace(
    document: Mapping[str, Any],
    *,
    mode: str = "gameplay",
    destination_path: str = "/Game/Animations",
    conflict_policy: str = "update",
    source_control_policy: str = "auto",
    unreal_project_path: str = "",
    unreal_command_path: str = "",
    log_file_path: str = "",
) -> dict[str, Any]:
    """Resolve sources, skeletons, conflicts, and actions without importing."""
    from unreal_tools import unreal_subprocess

    manifest = manifest_from_workspace(
        document, mode=mode, destination_path=destination_path,
        conflict_policy=conflict_policy, source_control_policy=source_control_policy,
    )
    handle, manifest_path = tempfile.mkstemp(prefix="tc_sequence_preflight_", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
        kwargs = {}
        if unreal_command_path:
            kwargs["unreal_command_path"] = unreal_command_path
        return unreal_subprocess.run_preflight_sequence_import(
            manifest_path, unreal_project_path, log_file_path,
            mode=mode, destination_path=destination_path, **kwargs,
        )
    finally:
        try:
            os.unlink(manifest_path)
        except OSError:
            pass


__all__ = [
    "manifest_from_workspace", "preflight_sequence_workspace", "publish_sequence_workspace",
]
