from __future__ import annotations

"""Unified AI Project Intelligence entry points.

This file is intentionally small: it coordinates existing systems instead of
replacing them. The first integration target is to let indexing optionally ingest
Unreal state when the bridge is open.
"""

from pathlib import Path
from typing import Any
import json


def unreal_is_connected(project_root: str | None = None) -> bool:
    try:
        from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner
        return bool(UnrealScanner(project_root=project_root).health_summary().get("ok"))
    except Exception:
        return False


def ingest_unreal_if_connected(project_root: str | None = None, *, mode: str = "quick") -> dict[str, Any]:
    """Scan Unreal and persist into the DCC local intelligence DB if reachable."""
    try:
        from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner
    except Exception as exc:
        return {"ok": False, "skipped": True, "reason": f"UnrealScanner import failed: {exc}"}

    scanner = UnrealScanner(project_root=project_root)
    health = scanner.health_summary()
    if not health.get("ok"):
        return {"ok": False, "skipped": True, "reason": "Unreal bridge not connected", "health": health}

    scan = scanner.scan_all(mode=mode, force=False)
    data = scan.get("data") if isinstance(scan.get("data"), dict) else scan

    try:
        from tech_connector.bridges.unreal.unreal_intelligence import ingest_scan
        ingest_result = ingest_scan(data, project_root=str(Path(project_root or ".").resolve()))
    except Exception as exc:
        ingest_result = {"success": False, "error": str(exc)}

    return {
        "ok": bool(scan.get("connected") or health.get("ok")),
        "skipped": False,
        "mode": mode,
        "scan": {
            "connected": scan.get("connected"),
            "cache_used": scan.get("cache_used"),
            "stages": scan.get("stages", []),
            "asset_counts": data.get("asset_counts", {}),
            "selected_assets": len(data.get("selected_assets") or []),
            "selected_actors": len(data.get("selected_actors") or []),
        },
        "ingest": ingest_result,
    }


def build_prompt_draft(user_text: str, project_root: str | None = None) -> str:
    from tech_connector.services.prompt_dispatch_service import PromptStagingService
    return PromptStagingService().build_draft(user_text, project_root=project_root).render_for_composer()
