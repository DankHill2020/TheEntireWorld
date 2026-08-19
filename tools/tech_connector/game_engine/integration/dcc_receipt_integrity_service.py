"""Shared deterministic integrity primitives for machine-local DCC receipts."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import source_file_fingerprint


def stable_receipt_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def receipt_environment_fingerprint() -> str:
    identity = "|".join((
        platform.node(), platform.system(), platform.machine(),
        str(os.environ.get("USERDOMAIN") or ""), str(os.environ.get("COMPUTERNAME") or ""),
    ))
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()


def bridge_implementation_fingerprint(bridge: Any) -> dict[str, Any]:
    bridge_type = type(bridge)
    source_path = inspect.getsourcefile(bridge_type) or ""
    return {
        "module": str(bridge_type.__module__),
        "class": str(bridge_type.__qualname__),
        "source_path": str(Path(source_path).resolve()) if source_path else "",
        "source_fingerprint": safe_source_fingerprint(source_path),
    }


def safe_source_fingerprint(path: str) -> dict[str, Any]:
    if not str(path or "").strip():
        return {"exists": False}
    try:
        return source_file_fingerprint(path)
    except OSError:
        return {"exists": False}


def parse_receipt_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "bridge_implementation_fingerprint", "parse_receipt_datetime",
    "receipt_environment_fingerprint", "safe_source_fingerprint", "stable_receipt_digest",
]
