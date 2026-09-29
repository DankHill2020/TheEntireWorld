"""Persistent UUID identity and import metadata for project assets."""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid
from typing import Any


ASSET_METADATA_SCHEMA = "tech_connector.asset_metadata.v1"


def asset_metadata_path(source_path: str | Path) -> Path:
    source = Path(source_path)
    return source.with_name(source.name + ".tcmeta")


def new_asset_id() -> str:
    return f"tc.asset.{uuid.uuid4().hex}"


def read_asset_metadata(source_path: str | Path) -> dict[str, Any]:
    path = asset_metadata_path(source_path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid asset metadata sidecar: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != ASSET_METADATA_SCHEMA:
        raise ValueError(f"Unsupported asset metadata sidecar: {path}")
    asset_id = str(payload.get("asset_id") or "")
    if not asset_id.startswith("tc.asset."):
        raise ValueError(f"Asset metadata is missing a stable asset ID: {path}")
    return dict(payload)


def write_asset_metadata(
    source_path: str | Path,
    *,
    asset_id: str,
    type_id: str,
    importer: str = "",
    importer_settings: dict[str, Any] | None = None,
    previous_paths: list[str] | tuple[str, ...] = (),
) -> Path:
    source = Path(source_path).expanduser().resolve()
    path = asset_metadata_path(source)
    payload = {
        "schema": ASSET_METADATA_SCHEMA,
        "asset_id": str(asset_id),
        "type_id": str(type_id),
        "source": source.name,
        "importer": str(importer),
        "importer_settings": dict(importer_settings or {}),
        "previous_paths": list(dict.fromkeys(str(value) for value in previous_paths if value)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def ensure_asset_metadata(
    source_path: str | Path,
    type_id: str,
    *,
    preferred_asset_id: str = "",
    importer: str = "",
    importer_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = read_asset_metadata(source_path)
    if existing:
        if preferred_asset_id and existing["asset_id"] != preferred_asset_id:
            raise ValueError(
                f"Asset identity conflict for {source_path}: {existing['asset_id']} != {preferred_asset_id}"
            )
        if str(existing.get("type_id") or "") != str(type_id):
            write_asset_metadata(
                source_path,
                asset_id=str(existing["asset_id"]),
                type_id=type_id,
                importer=str(existing.get("importer") or importer),
                importer_settings=dict(existing.get("importer_settings") or importer_settings or {}),
                previous_paths=list(existing.get("previous_paths") or ()),
            )
            existing["type_id"] = str(type_id)
        return existing
    asset_id = str(preferred_asset_id or new_asset_id())
    write_asset_metadata(
        source_path,
        asset_id=asset_id,
        type_id=type_id,
        importer=importer,
        importer_settings=importer_settings,
    )
    return read_asset_metadata(source_path)

