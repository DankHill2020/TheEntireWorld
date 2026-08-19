"""Load capability registries from monolithic or sharded JSON storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SHARD_MANIFEST_NAME = "manifest.json"


def sharded_registry_dir(registry_path: Path) -> Path:
    """
    Gets the directory used for capability registry shards.

    :param registry_path: Monolithic registry path or shard directory.
    :return: Directory containing the registry manifest and shards.
    """

    path = Path(registry_path)
    if path.suffix.lower() == ".json":
        return path.with_suffix("")
    return path


def capability_registry_payload_exists(registry_path: Path) -> bool:
    """
    Checks whether monolithic or sharded capability registry data exists.

    :param registry_path: Monolithic registry path or shard directory.
    :return: True when a loadable registry source is present.
    """

    path = Path(registry_path)
    if path.is_file():
        return True
    shard_dir = path if path.is_dir() else sharded_registry_dir(path)
    return (shard_dir / SHARD_MANIFEST_NAME).is_file()


def _resolved_shard_path(shard_dir: Path, shard_name: str) -> Path:
    """
    Resolves a manifest shard path while keeping it inside its registry directory.

    :param shard_dir: Registry shard directory.
    :param shard_name: Relative shard path stored in the manifest.
    :return: Validated absolute path to the shard.
    :raises ValueError: If the manifest path escapes the registry directory.
    """

    relative_path = Path(shard_name)
    if relative_path.is_absolute():
        raise ValueError(f"Capability registry shard must be relative: {shard_name}")
    root = shard_dir.resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Capability registry shard escapes its directory: {shard_name}")
    return candidate


def load_capability_registry_payload(registry_path: Path) -> dict[str, Any]:
    """
    Loads a capability registry payload.

    Development builds may have a generated ``capability_registry.json`` file.
    Sharded builds store the same payload as ``capability_registry/manifest.json``
    plus chunked entry files.

    :param registry_path: Monolithic registry path or shard directory.
    :return: Parsed registry payload, or an empty mapping when none exists.
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
        shard_path = _resolved_shard_path(shard_dir, shard_name)
        shard_payload = json.loads(shard_path.read_text(encoding="utf-8"))
        entries = shard_payload.get("entries", []) if isinstance(shard_payload, dict) else shard_payload
        if isinstance(entries, list):
            payload["entries"].extend(entries)

    return payload
