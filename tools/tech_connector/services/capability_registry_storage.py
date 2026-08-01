"""Load capability registries from monolithic or sharded JSON storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SHARD_MANIFEST_NAME = "manifest.json"


def sharded_registry_dir(registry_path: Path) -> Path:
    """Return the sibling directory used for Git-friendly registry shards."""

    path = Path(registry_path)
    if path.suffix.lower() == ".json":
        return path.with_suffix("")
    return path


def load_capability_registry_payload(registry_path: Path) -> dict[str, Any]:
    """Load a capability registry payload.

    Development builds may have a generated ``capability_registry.json`` file.
    GitHub builds store the same payload as ``capability_registry/manifest.json``
    plus chunked entry files so no single blob crosses GitHub's 100 MB limit.
    """

    path = Path(registry_path)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    shard_dir = path if path.is_dir() else sharded_registry_dir(path)
    manifest_path = shard_dir / SHARD_MANIFEST_NAME
    if not manifest_path.is_file():
        return {}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return {}

    payload = dict(manifest.get("payload", {}))
    payload.setdefault("schema", manifest.get("schema", "1.0"))
    payload.setdefault("saved_at", manifest.get("saved_at", ""))
    payload["entries"] = []

    for shard in manifest.get("shards", []):
        if not isinstance(shard, dict):
            continue
        shard_name = str(shard.get("path", "")).strip()
        if not shard_name:
            continue
        shard_path = shard_dir / shard_name
        shard_payload = json.loads(shard_path.read_text(encoding="utf-8"))
        entries = shard_payload.get("entries", []) if isinstance(shard_payload, dict) else shard_payload
        if isinstance(entries, list):
            payload["entries"].extend(entries)

    return payload
