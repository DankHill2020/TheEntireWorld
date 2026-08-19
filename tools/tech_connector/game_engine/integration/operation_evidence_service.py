from __future__ import annotations

"""Durable live-validation receipts for planner-visible operations."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _receipt_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "reports"
        / "runtime"
        / "operation_validation_receipts.json"
    )


def _load() -> dict[str, Any]:
    path = _receipt_path()
    if not path.is_file():
        return {"schema": "operation_validation_receipts_v1", "operations": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema": "operation_validation_receipts_v1", "operations": {}}
    payload.setdefault("schema", "operation_validation_receipts_v1")
    payload.setdefault("operations", {})
    return payload


def operation_validation_receipt(operation: str) -> dict[str, Any]:
    payload = _load()
    return dict((payload.get("operations") or {}).get(str(operation or "")) or {})


def record_operation_validation(
    operation: str,
    *,
    callable_path: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    key = str(operation or "").strip()
    if not key:
        raise ValueError("operation is required")
    fixture = dict(evidence.get("fixture") or {})
    fixture_result = dict(evidence.get("fixture_result") or {})
    if not evidence.get("ok") or not fixture or not fixture_result.get("ok"):
        raise ValueError("A successful disposable fixture result is required.")
    payload = _load()
    receipt = {
        "operation": key,
        "callable": str(callable_path or ""),
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture_id": str(fixture.get("id") or ""),
        "fixture_asset": str(fixture.get("disposable_asset") or ""),
        "expected_evidence": list(fixture.get("expected_evidence") or []),
        "fixture_result": fixture_result,
        "ok": True,
    }
    payload.setdefault("operations", {})[key] = receipt
    path = _receipt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        from tech_connector.game_engine.integration.operation_contract_service import (
            build_operation_contract_inventory,
        )

        build_operation_contract_inventory.cache_clear()
    except Exception:
        pass
    return receipt

