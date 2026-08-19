"""Persistent, compact failure ledger for live Unreal development evaluations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from tech_connector.models.constants import APP_DIR
from tech_connector.services.jsonl_retention_service import append_jsonl_record


UNREAL_DEVELOPMENT_EVAL_LOG = APP_DIR / "unreal_development_eval.jsonl"


def record_unreal_development_eval(
    *,
    case: str,
    stage: str,
    status: str,
    issue: str = "",
    evidence: dict[str, Any] | None = None,
    remediation: str = "",
    log_path: str | Path | None = None,
) -> dict[str, Any]:
    row = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "case": str(case or ""),
        "stage": str(stage or ""),
        "status": str(status or ""),
        "issue": str(issue or ""),
        "evidence": dict(evidence or {}),
        "remediation": str(remediation or ""),
    }
    path = Path(log_path or UNREAL_DEVELOPMENT_EVAL_LOG)
    append_jsonl_record(path, row)
    return row


def read_unreal_development_eval(
    *,
    limit: int = 100,
    log_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = Path(log_path or UNREAL_DEVELOPMENT_EVAL_LOG)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-max(1, int(limit or 100)):]
