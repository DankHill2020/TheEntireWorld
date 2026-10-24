from __future__ import annotations

"""Typed local-engine operations used by cross-DCC pipeline execution."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetOperationsService, validate_fbx_import


def import_interchange_asset(
    source_file: str | list[str] | tuple[str, ...],
    project_root: str,
    *,
    folder: str = "Assets",
    type_id: str = "",
    importer_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import one interchange artifact into a Tech Connector engine project."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Tech Connector project root does not exist: {root}")
    source_values = (
        list(source_file)
        if isinstance(source_file, (list, tuple))
        else [source_file]
    )
    sources = [Path(value).expanduser().resolve() for value in source_values]
    if not sources:
        raise ValueError("At least one pipeline handoff artifact is required.")
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise FileNotFoundError(
            "Pipeline handoff artifact does not exist: " + ", ".join(missing)
        )
    # Preflight the entire batch so a later character artifact cannot leave
    # earlier static assets partially imported.
    for source in sources:
        validate_fbx_import(source, type_id or ("tc.static_mesh" if source.suffix.casefold() == ".fbx" else ""))
    database = AssetDatabase(root / ".tech_connector" / "assets.sqlite3")
    service = AssetOperationsService(root, database)
    receipts = [
        service.import_asset(
            source,
            folder=folder,
            type_id=type_id,
            importer_settings=dict(importer_settings or {}),
        )
        for source in sources
    ]
    receipt = receipts[0]
    receipt_rows = [asdict(row) for row in receipts]
    return {
        **receipt_rows[0],
        "asset_id": receipt.asset_id,
        "asset_path": receipt.destination_path,
        "asset_type": receipt.type_id,
        "asset_ids": [row.asset_id for row in receipts],
        "asset_paths": [row.destination_path for row in receipts],
        "asset_types": [row.type_id for row in receipts],
        "asset_count": len(receipts),
        "imported_paths": [row.destination_path for row in receipts],
        "receipts": receipt_rows,
    }


__all__ = ["import_interchange_asset"]
