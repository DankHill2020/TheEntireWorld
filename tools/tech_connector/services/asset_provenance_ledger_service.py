"""Project-local registry for external binary assets and their entitlements."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


LEDGER_RELATIVE_PATH = Path(".ai_studio") / "assets" / "external_asset_ledger.json"


def asset_ledger_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / LEDGER_RELATIVE_PATH


def load_asset_ledger(project_root: str | Path) -> dict[str, Any]:
    path = asset_ledger_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    return {
        "schema": "ai_studio.external_asset_ledger.v1",
        "assets": [dict(row) for row in payload.get("assets") or [] if isinstance(row, dict)],
    }


def register_external_asset(
    project_root: str | Path,
    asset: dict[str, Any],
) -> dict[str, Any]:
    """Register project asset metadata without promoting it into knowledge."""

    payload = load_asset_ledger(project_root)
    row = dict(asset or {})
    local_path = str(row.get("local_path") or "")
    identity = str(row.get("sha256") or local_path or row.get("source_url") or "")
    if not identity:
        return {"ok": False, "error": "Asset identity requires a hash, local path, or source URL."}
    row.update(
        {
            "id": identity,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "knowledge_eligible": False,
            "community_share_eligible": False,
            "model_training_eligible": False,
            "record_scope": "project_asset",
        }
    )
    existing = [item for item in payload["assets"] if str(item.get("id") or "") != identity]
    existing.append(row)
    payload["assets"] = existing
    path = asset_ledger_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"ok": True, "ledger_path": str(path), "asset": row}
