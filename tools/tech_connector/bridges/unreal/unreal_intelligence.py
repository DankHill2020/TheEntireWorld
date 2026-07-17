"""Unreal integration helpers for the DCC local intelligence layer.

This module is intentionally dependency-light and safe to import from the Tech Connector
desktop app. It does not require the Unreal Python module to be importable locally;
it stores whatever the existing HTTP bridge/scanner can provide.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from tech_connector.dcc_intelligence.context_builder import ContextBuilder
from tech_connector.dcc_intelligence.store import IntelligenceStore, ProjectRef


INTELLIGENCE_DIR = Path(".ai_studio") / "intelligence"
DB_FILENAME = "dcc_local_intelligence.sqlite"


def resolve_project_root(project_root: Optional[str] = None) -> Path:
    """Resolve the project root used for the local intelligence database."""
    root = Path(project_root).expanduser() if project_root else Path.cwd()
    return root.resolve()


def resolve_db_path(project_root: Optional[str] = None) -> Path:
    """Return <project>/.ai_studio/intelligence/dcc_local_intelligence.sqlite."""
    return resolve_project_root(project_root) / INTELLIGENCE_DIR / DB_FILENAME


def open_store(project_root: Optional[str] = None) -> IntelligenceStore:
    return IntelligenceStore(resolve_db_path(project_root))


def project_name_from_root(project_root: Optional[str] = None) -> str:
    root = resolve_project_root(project_root)
    for uproject in root.glob("*.uproject"):
        return uproject.stem
    return root.name or "UnrealProject"


def ensure_project(store: IntelligenceStore, project_root: Optional[str] = None) -> ProjectRef:
    root = resolve_project_root(project_root)
    return store.upsert_project("Unreal", project_name_from_root(str(root)), root)


def _asset_name_from_path(asset_path: str) -> str:
    text = str(asset_path)
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text.rstrip("/").rsplit("/", 1)[-1]


def _package_path_from_asset_path(asset_path: str) -> str:
    text = str(asset_path)
    package = text.split(".", 1)[0]
    if "/" in package:
        return package.rsplit("/", 1)[0]
    return ""


def _iter_asset_records(index: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield normalized asset rows from UnrealScanner.scan_all() output."""
    buckets = {
        "selected_assets": "SelectedAsset",
        "skeletons": "Skeleton",
        "skeletal_meshes": "SkeletalMesh",
        "animations": "AnimSequence",
        "blueprints": "Blueprint",
        "available_tools": "EditorUtilityBlueprint",
    }
    seen: set[str] = set()
    for key, asset_type in buckets.items():
        values = index.get(key) or []
        for value in values:
            asset_path = str(value)
            if not asset_path or asset_path in seen:
                continue
            seen.add(asset_path)
            yield {
                "asset_path": asset_path,
                "asset_name": _asset_name_from_path(asset_path),
                "asset_type": asset_type,
                "package_path": _package_path_from_asset_path(asset_path),
                "class_name": asset_type,
                "metadata": {"source": "unreal_scanner", "bucket": key},
            }

    # Also accept parsed snapshot format from unreal_td_prompt, if present:
    # {"assets": {"Blueprint": ["BP_Player", ...]}}
    assets_by_class = index.get("assets")
    if isinstance(assets_by_class, dict):
        for asset_type, names in assets_by_class.items():
            if not isinstance(names, list):
                continue
            for name in names:
                asset_path = str(name)
                if not asset_path or asset_path in seen:
                    continue
                seen.add(asset_path)
                yield {
                    "asset_path": asset_path,
                    "asset_name": _asset_name_from_path(asset_path),
                    "asset_type": str(asset_type),
                    "package_path": _package_path_from_asset_path(asset_path),
                    "class_name": str(asset_type),
                    "metadata": {"source": "unreal_snapshot", "bucket": "assets"},
                }


def ingest_scan(index: Dict[str, Any], project_root: Optional[str] = None) -> Dict[str, Any]:
    """Persist scanner output into the local intelligence database."""
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        asset_count = 0
        for record in _iter_asset_records(index):
            store.upsert_asset(project.id, "Unreal", **record)
            asset_name = record.get("asset_name") or record.get("asset_path")
            asset_type = record.get("asset_type") or record.get("class_name") or "Asset"
            store.upsert_symbol(
                project.id,
                "Unreal",
                symbol_key=f"asset.{asset_type}.{asset_name}",
                symbol_kind="asset",
                display_name=str(asset_name),
                qualified_name=record.get("asset_path"),
                source_ref=record.get("asset_path"),
                summary=f"{asset_type} asset in {record.get('package_path') or '/Game'}",
                metadata={"asset_type": asset_type, "class_name": record.get("class_name")},
            )
            asset_count += 1

        selected = index.get("selected_assets") or []
        loaded_assets = []
        for key in ("skeletal_meshes", "animations", "blueprints", "available_tools"):
            loaded_assets.extend(index.get(key) or [])

        snapshot_id = store.add_snapshot(
            project.id,
            "Unreal",
            snapshot_kind="scan_all",
            selected=selected,
            active_level=str(index.get("loaded_level") or index.get("level") or ""),
            open_document=(index.get("open_project") or {}).get("project_dir") if isinstance(index.get("open_project"), dict) else None,
            loaded_assets=loaded_assets,
            state=index,
        )

        _register_default_capabilities(store, project.id)
        try:
            from tech_connector.services.unreal.capability_graph_service import sync_unreal_capability_graph

            sync_unreal_capability_graph(project_root)
        except Exception:
            pass
        return {
            "success": True,
            "db_path": str(resolve_db_path(project_root)),
            "project_id": project.id,
            "assets_indexed": asset_count,
            "snapshot_id": snapshot_id,
        }
    finally:
        store.close()


def _register_default_capabilities(store: IntelligenceStore, project_id: int) -> None:
    """Seed reusable Unreal capabilities so the context builder has a capability surface."""
    defaults = [
        {
            "name": "scan_unreal_project_state",
            "description": "Query selected assets, level state, skeletal meshes, animations, blueprints, plugins, and editor utility tools.",
            "entrypoint": "tech_connector.bridges.unreal.unreal_scanner.UnrealScanner.scan_all",
            "source_path": "bridges/unreal/unreal_scanner.py",
            "risk_level": "read_only",
            "tags": ["unreal", "scan", "assets", "blueprint", "context"],
        },
        {
            "name": "build_unreal_td_prompt",
            "description": "Build a project-aware Unreal Technical Director system prompt using cached intelligence and live scanner state.",
            "entrypoint": "tech_connector.bridges.unreal.unreal_td_prompt.build_for_prompt",
            "source_path": "bridges/unreal/unreal_td_prompt.py",
            "risk_level": "read_only",
            "tags": ["unreal", "prompt", "context", "td"],
        },
        {
            "name": "execute_unreal_python_http",
            "description": "Execute Unreal Python through the existing local HTTP bridge.",
            "entrypoint": "tech_connector.bridges.unreal.unreal_bridge.UnrealBridge.call",
            "source_path": "bridges/unreal/unreal_bridge.py",
            "risk_level": "medium",
            "tags": ["unreal", "python", "http", "execution"],
        },
    ]
    for cap in defaults:
        store.upsert_capability(project_id, "Unreal", **cap)
        store.upsert_symbol(
            project_id,
            "Unreal",
            symbol_key=f"capability.{cap['name']}",
            symbol_kind="capability",
            display_name=cap["name"],
            qualified_name=cap.get("entrypoint"),
            source_ref=cap.get("source_path"),
            summary=cap.get("description"),
            metadata={"risk_level": cap.get("risk_level"), "tags": cap.get("tags", [])},
        )


def lookup_symbols(query: str, project_root: Optional[str] = None, *, prefix: bool = True, limit: int = 20) -> list[dict[str, Any]]:
    """Fast DCC-agnostic symbol lookup for exact/prefix/autocomplete use."""
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        if prefix:
            return store.prefix_symbols(project.id, "Unreal", query, limit=limit)
        exact = store.get_symbol(project.id, "Unreal", query, limit=limit)
        return exact or store.search_symbols(project.id, "Unreal", query, limit=limit)
    finally:
        store.close()


def build_context(request: str, project_root: Optional[str] = None) -> str:
    """Return model-ready local intelligence context for a user request."""
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        packet = ContextBuilder(store).build(project, request, dcc="Unreal")
        return packet.to_prompt_text()
    finally:
        store.close()


def record_execution(
    request_text: str,
    project_root: Optional[str] = None,
    *,
    action_name: Optional[str] = None,
    target_ref: Optional[str] = None,
    status: str = "planned",
    risk_level: str = "unknown",
    summary: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> int:
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        return store.add_execution(
            project.id,
            "Unreal",
            request_text=request_text,
            action_name=action_name,
            target_ref=target_ref,
            status=status,
            risk_level=risk_level,
            summary=summary,
            result=result or {},
        )
    finally:
        store.close()


def status(project_root: Optional[str] = None) -> Dict[str, Any]:
    db_path = resolve_db_path(project_root)
    store = open_store(project_root)
    try:
        project = ensure_project(store, project_root)
        row = store.conn.execute("SELECT COUNT(*) AS n FROM assets WHERE project_id=?", (project.id,)).fetchone()
        symbol_row = store.conn.execute("SELECT COUNT(*) AS n FROM symbols WHERE project_id=? AND dcc=?", (project.id, "Unreal")).fetchone()
        api_row = store.conn.execute("SELECT COUNT(*) AS n FROM python_api WHERE project_id=? AND dcc=?", (project.id, "Unreal")).fetchone()
        snap = store.latest_snapshot(project.id, "Unreal")
        return {
            "db_path": str(db_path),
            "project_id": project.id,
            "project_root": project.root_path,
            "asset_count": int(row["n"]) if row else 0,
            "symbol_count": int(symbol_row["n"]) if symbol_row else 0,
            "python_api_count": int(api_row["n"]) if api_row else 0,
            "has_snapshot": bool(snap),
            "latest_snapshot": snap.get("created_at") if snap else None,
        }
    finally:
        store.close()
