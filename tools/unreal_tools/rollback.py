"""Rollback journal entrypoints for AI Studio Unreal operations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4


def _journal_path() -> Path:
    try:
        import unreal

        saved_dir = Path(unreal.Paths.project_saved_dir())
    except Exception:
        saved_dir = Path.cwd() / "Saved"
    path = saved_dir / "AIStudioBridge" / "rollback_journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _append(entry: dict) -> dict:
    payload = {
        "token": entry.get("token") or f"rollback:{_utc_timestamp()}:{uuid4().hex[:8]}",
        "created_at": entry.get("created_at") or datetime.now(timezone.utc).isoformat(),
        **entry,
    }
    path = _journal_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def _read_entries() -> list[dict]:
    path = _journal_path()
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            rows.append({"ok": False, "status": "corrupt_journal_row", "raw": line})
    return rows


def latest():
    entries = _read_entries()
    if not entries:
        return json.dumps({
            "ok": False,
            "status": "no_rollback_journal",
            "message": "No rollback journal entries are available for the active Unreal project.",
            "journal_path": str(_journal_path()),
        }, indent=2)
    return json.dumps({
        "ok": True,
        "status": "latest_rollback_entry",
        "journal_path": str(_journal_path()),
        "entry": entries[-1],
    }, indent=2)


def record_asset_snapshot(asset_path, reason="", operation="", metadata=None):
    try:
        import unreal
    except Exception as exc:
        return json.dumps({"ok": False, "status": "unreal_python_unavailable", "error": str(exc)}, indent=2)

    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        return json.dumps({"ok": False, "status": "asset_not_found", "asset_path": asset_path}, indent=2)

    clean_name = str(asset.get_name()).replace(" ", "_")
    snapshot_path = f"/Game/AIStudio/Rollback/{clean_name}_{_utc_timestamp()}_{uuid4().hex[:6]}"
    duplicated = unreal.EditorAssetLibrary.duplicate_asset(asset_path, snapshot_path)
    if not duplicated:
        return json.dumps({
            "ok": False,
            "status": "snapshot_failed",
            "asset_path": asset_path,
            "snapshot_path": snapshot_path,
        }, indent=2)

    unreal.EditorAssetLibrary.save_asset(snapshot_path, only_if_is_dirty=False)
    entry = _append({
        "kind": "asset_snapshot",
        "operation": operation,
        "reason": reason,
        "asset_path": asset_path,
        "snapshot_path": snapshot_path,
        "metadata": dict(metadata or {}),
    })
    return json.dumps({
        "ok": True,
        "status": "asset_snapshot_recorded",
        "journal_path": str(_journal_path()),
        "entry": entry,
    }, indent=2)


def restore_asset_snapshot(token=""):
    try:
        import unreal
    except Exception as exc:
        return json.dumps({"ok": False, "status": "unreal_python_unavailable", "error": str(exc)}, indent=2)

    entries = _read_entries()
    if token:
        matches = [entry for entry in entries if entry.get("token") == token]
    else:
        matches = [entry for entry in entries if entry.get("kind") == "asset_snapshot"]
    if not matches:
        return json.dumps({"ok": False, "status": "rollback_entry_not_found", "token": token}, indent=2)

    entry = matches[-1]
    asset_path = entry.get("asset_path")
    snapshot_path = entry.get("snapshot_path")
    if not asset_path or not snapshot_path:
        return json.dumps({"ok": False, "status": "rollback_entry_missing_paths", "entry": entry}, indent=2)
    snapshot = unreal.EditorAssetLibrary.load_asset(snapshot_path)
    if not snapshot:
        return json.dumps({"ok": False, "status": "snapshot_asset_not_found", "snapshot_path": snapshot_path}, indent=2)

    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        unreal.EditorAssetLibrary.delete_asset(asset_path)
    restored = unreal.EditorAssetLibrary.duplicate_asset(snapshot_path, asset_path)
    if restored:
        unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)
    restore_entry = _append({
        "kind": "asset_restore",
        "operation": "rollback.restore_asset_snapshot",
        "restored_from_token": entry.get("token"),
        "asset_path": asset_path,
        "snapshot_path": snapshot_path,
    })
    return json.dumps({
        "ok": bool(restored),
        "status": "asset_snapshot_restored" if restored else "asset_restore_failed",
        "journal_path": str(_journal_path()),
        "source_entry": entry,
        "restore_entry": restore_entry,
    }, indent=2)
