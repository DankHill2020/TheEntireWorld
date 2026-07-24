"""Asset import helpers for first-party Unreal routing."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from tech_connector.services.external_asset_destination_service import (
    normalize_asset_destination,
)


def import_local_asset(
    source_path: str,
    destination_path: str = "/Game/AIStudio/Imported",
    destination_name: str = "",
    replace_existing: bool = False,
    save: bool = True,
    automated: bool = True,
) -> dict[str, Any]:
    """
        Import local asset.
    :param source_path: local file path to import
    :param destination_path: Unreal Content Browser folder such as /Game/Folder
    :param destination_name: optional imported asset name
    :param replace_existing: replace existing asset with the same name
    :param save: save imported assets after import
    :param automated: run Unreal import without modal dialogs where possible
    :return: import result with imported object paths and validation evidence
    """
    import unreal

    started = time.monotonic()
    source = str(Path(source_path).expanduser())
    destination = normalize_asset_destination("unreal", destination_path)
    out: dict[str, Any] = {
        "ok": False,
        "elapsed_ms": 0,
        "source_path": source,
        "destination_path": destination,
        "destination_name": str(destination_name or ""),
        "imported_object_paths": [],
        "asset_checks": [],
        "warnings": [],
        "errors": [],
    }
    if not os.path.exists(source):
        out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        out["errors"].append(f"Source file does not exist: {source}")
        return out

    try:
        unreal.EditorAssetLibrary.make_directory(destination)
    except Exception as exc:
        out["warnings"].append(f"Could not ensure destination folder: {exc}")

    task = unreal.AssetImportTask()
    task.set_editor_property("filename", source)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("replace_existing", bool(replace_existing))
    task.set_editor_property("save", bool(save))
    task.set_editor_property("automated", bool(automated))
    if destination_name:
        task.set_editor_property("destination_name", str(destination_name))

    try:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    except Exception as exc:
        out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        out["errors"].append(str(exc))
        return out

    imported = [str(item) for item in (task.get_editor_property("imported_object_paths") or [])]
    out["imported_object_paths"] = imported
    for asset_path in imported:
        exists = False
        try:
            exists = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
        except Exception as exc:
            out["warnings"].append(f"{asset_path}: existence check failed: {exc}")
        out["asset_checks"].append({"asset_path": asset_path, "exists": exists})

    out["ok"] = bool(imported) and all(item.get("exists") for item in out["asset_checks"])
    if not imported:
        out["errors"].append("Unreal import completed without imported object paths.")
    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out

