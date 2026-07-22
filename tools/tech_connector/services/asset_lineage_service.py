"""Record provenance and transformation lineage for externally acquired assets."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_asset_lineage(
    output_path: str | Path,
    *,
    sources: Iterable[dict[str, Any]],
    transformations: Iterable[dict[str, Any]],
    license_record: dict[str, Any],
    semantic_contract: dict[str, Any],
    destination: str = "",
) -> dict[str, Any]:
    """Write a sidecar only when every source and the output exist."""

    output = Path(output_path).resolve()
    source_rows = []
    errors = []
    for raw in sources:
        row = dict(raw)
        local_path = Path(str(row.get("local_path") or "")).resolve()
        if not local_path.is_file():
            errors.append(f"Source file is missing: {local_path}")
            continue
        source_rows.append(
            {
                **row,
                "local_path": str(local_path),
                "bytes": local_path.stat().st_size,
                "sha256": _sha256(local_path),
            }
        )
    if not output.is_file():
        errors.append(f"Output file is missing: {output}")
    if errors:
        return {"ok": False, "errors": errors}
    payload = {
        "schema": "ai_studio.asset_lineage.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "output": {
            "local_path": str(output),
            "bytes": output.stat().st_size,
            "sha256": _sha256(output),
            "destination": destination,
        },
        "sources": source_rows,
        "transformations": [dict(row) for row in transformations],
        "license": dict(license_record),
        "semantic_contract": dict(semantic_contract),
    }
    manifest = output.with_suffix(output.suffix + ".provenance.json")
    manifest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"ok": True, "manifest_path": str(manifest), **payload}
