"""Independently verify one prompt-routed Blender → Tech Connector action run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.assets.asset_operations_service import AssetOperationsService


def verify_blender_tc_prompt_proof(report_path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"verified": False, "errors": [f"Unreadable prompt proof: {exc}"]}
    cross = dict(report.get("cross_host") or {})
    stages = list(cross.get("stages") or [])
    actions = dict(cross.get("action_results") or {})
    expected = (
        ("stage_01_blender_io_export_fbx", "blender", "io.export_fbx"),
        ("stage_02_tech_connector_asset_import_interchange", "tech_connector", "asset.import_interchange"),
    )
    if (report.get("schema") != "tech_connector.live_blender_tc_prompt.v1"
            or report.get("route") != "pipeline_graph" or not cross.get("plan_success")
            or not cross.get("plan_execution_ready")
            or cross.get("execution_status") != "completed"
            or cross.get("status_counts") != {"completed": 2}):
        errors.append("Prompt planning or two-action execution did not complete")
    if [(row.get("id"), row.get("host"), row.get("operation")) for row in stages] != list(expected):
        errors.append("Planned Blender-to-engine stage sequence changed")
    export_id, import_id = expected[0][0], expected[1][0]
    if stages and len(stages) == 2:
        reference = (stages[1].get("params") or {}).get("source_file")
        if reference != {"from_action": export_id, "result_path": "fbx_path"}:
            errors.append("Engine import was not bound to the Blender export result")
    if set(actions) != {export_id, import_id} or any(
        not actions.get(key, {}).get("ok") or actions.get(key, {}).get("status") != "succeeded"
        for key in (export_id, import_id)
    ):
        errors.append("One or more host actions did not succeed")
    export = dict((actions.get(export_id, {}).get("raw_result") or {}).get("result") or {})
    imported = dict((actions.get(import_id, {}).get("raw_result") or {}).get("result") or {})
    source = Path(str(export.get("fbx_path") or "")).resolve()
    root = Path(str(cross.get("engine_project_root") or "")).resolve()
    destination = Path(str(imported.get("asset_path") or "")).resolve()
    if (not source.is_file() or not destination.is_file()
            or not destination.is_relative_to(root / "Assets")
            or source == destination):
        errors.append("Blender FBX or engine asset is missing or out of scope")
    else:
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
            errors.append("Engine asset bytes differ from the live Blender export")
    if (str(imported.get("source_path") or "") != str(source)
            or str(imported.get("destination_path") or "") != str(destination)
            or imported.get("asset_type") != "tc.static_mesh"
            or imported.get("asset_count") != 1
            or not imported.get("asset_id")):
        errors.append("Engine receipt does not identify one imported static mesh")
    if len(stages) == 2 and (
        Path(str((stages[1].get("params") or {}).get("project_root") or "")).resolve() != root
    ):
        errors.append("Planned engine project differs from the executed project")
    if not errors:
        database = AssetDatabase(root / ".tech_connector" / "assets.sqlite3")
        validation = AssetOperationsService(root, database).validate_asset(imported["asset_id"])
        if not validation.valid:
            errors.append("Fresh engine asset-database validation failed")
    return {
        "verified": not errors,
        "continuous_action_graph_proven": not errors,
        "scope": "one custom Blender static-mesh prompt through Tech Connector engine import",
        "asset_id": str(imported.get("asset_id") or ""),
        "asset_path": str(destination) if destination.is_file() else "",
        "source_path": str(source) if source.is_file() else "",
        "errors": errors,
    }


__all__ = ["verify_blender_tc_prompt_proof"]
