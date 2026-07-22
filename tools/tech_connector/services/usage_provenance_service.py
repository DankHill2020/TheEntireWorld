"""Transparent project/code/asset provenance markers for Tech Connector output."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tech_connector.services.license_entitlement_service import LicenseEntitlement, verify_entitlement


PROVENANCE_DIR_NAME = ".tech_connector"
PROVENANCE_FILE_NAME = "provenance.json"
PYTHON_MARKER_PREFIX = "# Tech Connector:"
SIDECAR_SUFFIX = ".tech_connector.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_hash(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _project_hash(project_root: Path) -> str:
    try:
        value = str(project_root.resolve()).lower()
    except Exception:
        value = str(project_root).lower()
    return _stable_hash(value)


def build_usage_tag(
    entitlement: LicenseEntitlement,
    *,
    project_root: str | Path = "",
    operation: str = "",
    output_path: str | Path = "",
) -> dict[str, Any]:
    """Build a non-secret provenance record for generated code/assets."""
    project = Path(project_root) if project_root else Path()
    account_key = entitlement.license_id or entitlement.account_id or entitlement.account_email
    return {
        "schema": "tech_connector.provenance.v1",
        "created_at": _utc_now(),
        "tool": "Tech Connector",
        "license_tier": entitlement.tier,
        "license_id_hash": _stable_hash(entitlement.license_id),
        "account_hash": _stable_hash(account_key),
        "project_hash": _project_hash(project) if project_root else "",
        "operation": str(operation or ""),
        "output_path": str(output_path or ""),
        "resale_allowed": False,
        "redistribution_allowed": bool(entitlement.redistribution_allowed),
        "hosted_access_allowed": bool(entitlement.hosted_access_allowed),
        "ai_training_allowed": bool(entitlement.ai_training_allowed),
        "direct_code_reuse_allowed": bool(entitlement.direct_code_reuse_allowed),
        "official_api_required": bool(entitlement.official_api_required),
    }


def provenance_from_settings(
    settings: dict[str, Any],
    *,
    project_root: str | Path = "",
    operation: str = "",
    output_path: str | Path = "",
    **verify_kwargs: Any,
) -> dict[str, Any]:
    entitlement = verify_entitlement(settings, **verify_kwargs)
    return build_usage_tag(
        entitlement,
        project_root=project_root,
        operation=operation,
        output_path=output_path,
    )


def python_header_for_tag(tag: dict[str, Any]) -> str:
    compact = json.dumps(tag, sort_keys=True, separators=(",", ":"))
    return f"{PYTHON_MARKER_PREFIX} {compact}\n"


def apply_python_provenance(source: str, tag: dict[str, Any]) -> str:
    """Insert or replace a Tech Connector provenance header in Python code."""
    lines = str(source or "").splitlines(keepends=True)
    header = python_header_for_tag(tag)
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    else:
        insert_at = 0
    if len(lines) > insert_at and lines[insert_at].startswith(PYTHON_MARKER_PREFIX):
        lines[insert_at] = header
        return "".join(lines)
    lines.insert(insert_at, header)
    return "".join(lines)


def write_project_provenance_marker(
    project_root: str | Path,
    tag: dict[str, Any],
    *,
    append: bool = True,
) -> Path:
    root = Path(project_root)
    marker_dir = root / PROVENANCE_DIR_NAME
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / PROVENANCE_FILE_NAME
    records: list[dict[str, Any]] = []
    if append and marker_path.exists():
        try:
            existing = json.loads(marker_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                records = list(existing.get("records") or [])
        except Exception:
            records = []
    records.append(dict(tag))
    payload = {
        "schema": "tech_connector.project_provenance.v1",
        "project_hash": tag.get("project_hash", ""),
        "records": records[-200:],
    }
    marker_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return marker_path


def write_asset_sidecar(output_path: str | Path, tag: dict[str, Any]) -> Path:
    path = Path(output_path)
    sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
    sidecar.write_text(json.dumps(tag, indent=2), encoding="utf-8")
    return sidecar


def scan_for_usage_markers(path: str | Path) -> list[dict[str, Any]]:
    """Find transparent Tech Connector provenance markers in a file or tree."""
    root = Path(path)
    candidates = [root] if root.is_file() else list(root.rglob("*"))
    markers: list[dict[str, Any]] = []
    for item in candidates:
        if not item.is_file():
            continue
        if item.name == PROVENANCE_FILE_NAME and item.parent.name == PROVENANCE_DIR_NAME:
            try:
                data = json.loads(item.read_text(encoding="utf-8"))
                for record in data.get("records") or []:
                    markers.append({"path": str(item), "marker": record})
            except Exception:
                continue
        elif item.name.endswith(SIDECAR_SUFFIX):
            try:
                markers.append({"path": str(item), "marker": json.loads(item.read_text(encoding="utf-8"))})
            except Exception:
                continue
        elif item.suffix.lower() == ".py":
            try:
                first_lines = item.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
            except Exception:
                continue
            for line in first_lines:
                if line.startswith(PYTHON_MARKER_PREFIX):
                    raw = line[len(PYTHON_MARKER_PREFIX) :].strip()
                    try:
                        markers.append({"path": str(item), "marker": json.loads(raw)})
                    except Exception:
                        markers.append({"path": str(item), "marker": {"raw": raw}})
                    break
    return markers
