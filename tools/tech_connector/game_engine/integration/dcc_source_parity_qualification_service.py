"""Read-only, exact-session source snapshot qualification for DCC providers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tech_connector.game_engine.integration.dcc_host_qualification_service import (
    HOST_ROLE_PROFILES,
    bridge_for_host,
)
from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.game_engine.integration.dcc_receipt_integrity_service import (
    bridge_implementation_fingerprint,
    parse_receipt_datetime,
    receipt_environment_fingerprint,
    safe_source_fingerprint,
    stable_receipt_digest,
)
from tech_connector.game_engine.rendering.material_contract import (
    lookdev_state_from_snapshot,
    provider_lookdev_capture_profile,
)
from tech_connector.models.constants import APP_DIR


SOURCE_PARITY_QUALIFICATION_SCHEMA = "tech_connector.dcc_source_parity_qualification.v2"
DEFAULT_SOURCE_PARITY_LEDGER_PATH = Path(APP_DIR) / "dcc_source_parity_receipts.json"
DEFAULT_SOURCE_PARITY_MAX_AGE_SECONDS = 24.0 * 60.0 * 60.0
_OBSERVER_STATE_KEYS = (
    "scene", "project", "project_path", "document", "document_path", "file", "file_path",
    "dirty", "is_dirty", "modified", "scene_modified", "has_unsaved_changes",
    "frame", "current_frame", "time", "current_time", "take", "timeline", "selection",
)


def qualify_dcc_source_parity(
    host: str,
    port: int,
    *,
    bridge: Any | None = None,
    timeout: float = 5.0,
    latency_budget_ms: float = 5000.0,
    object_limit: int = 24,
) -> dict[str, Any]:
    """Prove a bounded snapshot is exact-session, role-appropriate, and non-mutating."""

    key = _provider_key(host)
    if key not in HOST_ROLE_PROFILES:
        raise ValueError(f"Unsupported DCC source-parity host: {host}")
    requested_port = int(port)
    target = bridge if bridge is not None else bridge_for_host(key)
    profile = provider_lookdev_capture_profile(key)
    checked_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    missing_gates: list[str] = []
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    snapshot: dict[str, Any] = {}
    started = time.perf_counter()

    try:
        before = dict(target.session_info(port=requested_port, timeout=timeout) or {})
        if not before.get("ok"):
            raise RuntimeError(str(before.get("error") or "Initial session identity readback failed."))
        snapshot_options = {
            "port": requested_port,
            "selected_only": False,
            "include_geometry": False,
            "include_materials": True,
            "include_faces": False,
            "limit": max(1, int(object_limit)),
            "timeout": timeout,
        }
        if key == "maya":
            snapshot_options["meshes_only"] = True
        result = target.get_scene_snapshot(**snapshot_options)
        ok, payload = _snapshot_result(result)
        if not ok:
            raise RuntimeError(str(payload or "Source snapshot failed."))
        if not isinstance(payload, dict):
            raise RuntimeError("Source snapshot did not return a mapping.")
        snapshot = dict(payload)
        after = dict(target.session_info(port=requested_port, timeout=timeout) or {})
        if not after.get("ok"):
            raise RuntimeError(str(after.get("error") or "Final session identity readback failed."))
    except Exception as exc:
        errors.append(str(exc))

    latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if errors:
        missing_gates.append("source_snapshot_readback")

    schema = str(snapshot.get("schema") or "")
    provider = _provider_key(snapshot.get("provider_id") or "")
    schema_verified = bool(schema.startswith("tech_connector.") and "snapshot.v" in schema)
    provider_verified = provider == key
    if not schema_verified:
        missing_gates.append("snapshot_schema")
    if not provider_verified:
        missing_gates.append("snapshot_provider_identity")

    before_identity = _session_identity(before)
    after_identity = _session_identity(after)
    exact_session = bool(
        before
        and after
        and int(before.get("port") or 0) == requested_port
        and int(after.get("port") or 0) == requested_port
        and before_identity
        and before_identity == after_identity
        and _snapshot_matches_session(snapshot, before)
    )
    if not exact_session:
        missing_gates.append("exact_session_snapshot")

    changed_state = _changed_observer_state(before, after)
    non_mutating = bool(before and after and not changed_state)
    if not non_mutating:
        missing_gates.append("non_mutating_readback")
    if latency_ms > max(1.0, float(latency_budget_ms)):
        missing_gates.append("source_snapshot_latency_budget")

    evidence = _role_evidence(key, snapshot, profile)
    if not evidence["sufficient"]:
        missing_gates.append("role_source_evidence")

    source_path = _scene_identity(snapshot) or _scene_identity(before)
    source_fingerprint = safe_source_fingerprint(source_path)
    environment_fingerprint = receipt_environment_fingerprint()
    bridge_implementation = bridge_implementation_fingerprint(target)
    application_version = str(
        snapshot.get("application_version") or before.get("version") or before.get("application_version") or ""
    )
    protocol = str(getattr(getattr(target, "info", None), "protocol", "unknown") or "unknown")
    snapshot_digest = stable_receipt_digest(snapshot)
    gates = sorted(set(missing_gates))
    integrity = {
        "schema": SOURCE_PARITY_QUALIFICATION_SCHEMA,
        "checked_at": checked_at,
        "host": key,
        "port": requested_port,
        "session_identity": before_identity,
        "session_process_id": str(before.get("pid") or before.get("process_id") or ""),
        "source_path": source_path,
        "source_fingerprint": source_fingerprint,
        "environment_fingerprint": environment_fingerprint,
        "application_version": application_version,
        "bridge_protocol": protocol,
        "bridge_implementation": bridge_implementation,
        "snapshot_schema": schema,
        "snapshot_provider": provider,
        "snapshot_digest": snapshot_digest,
        "role_evidence": evidence,
        "changed_state": changed_state,
        "exact_session_verified": exact_session,
        "non_mutating_verified": non_mutating,
        "qualification_gates": gates,
    }
    receipt_id = stable_receipt_digest(integrity)
    return {
        "schema": SOURCE_PARITY_QUALIFICATION_SCHEMA,
        "receipt_id": receipt_id,
        "checked_at": checked_at,
        "host": key,
        "role": HOST_ROLE_PROFILES[key].role,
        "port": requested_port,
        "status": "qualified" if not gates else "unqualified",
        "missing_gates": gates,
        "errors": errors,
        "capture_profile": profile,
        "snapshot_schema": schema,
        "snapshot_provider": provider,
        "schema_verified": schema_verified,
        "provider_verified": provider_verified,
        "exact_session_verified": exact_session,
        "non_mutating_verified": non_mutating,
        "changed_observer_state": changed_state,
        "observer_state_before": _observer_state(before),
        "observer_state_after": _observer_state(after),
        "session_identity_before": before_identity,
        "session_identity_after": after_identity,
        "session_process_id": integrity["session_process_id"],
        "source_path": source_path,
        "source_fingerprint": source_fingerprint,
        "environment_fingerprint": environment_fingerprint,
        "application_version": application_version,
        "bridge_protocol": protocol,
        "bridge_implementation": bridge_implementation,
        "snapshot_digest": snapshot_digest,
        "latency_ms": latency_ms,
        "latency_budget_ms": max(1.0, float(latency_budget_ms)),
        "role_evidence": evidence,
        "integrity": integrity,
    }


def validate_source_parity_receipt(
    host: str,
    receipt: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_SOURCE_PARITY_MAX_AGE_SECONDS,
    bridge: Any | None = None,
    check_source: bool = True,
    require_live_session: bool = True,
    live_timeout: float = 1.0,
) -> dict[str, Any]:
    """Validate receipt integrity, freshness, environment, bridge, and source revision."""

    key = _provider_key(host)
    row = dict(receipt or {}) if isinstance(receipt, dict) else {}
    if not row:
        return {
            "host": key,
            "status": "invalid",
            "valid": False,
            "gates": ["missing_receipt"],
            "receipt_id": "",
            "age_seconds": None,
            "max_age_seconds": max(1.0, float(max_age_seconds)),
            "source_path": "",
            "saved_source_fingerprint": {},
            "current_source_fingerprint": {},
        }
    gates: list[str] = []
    if str(row.get("schema") or "") != SOURCE_PARITY_QUALIFICATION_SCHEMA:
        gates.append("receipt_schema")
    if _provider_key(row.get("host")) != key:
        gates.append("receipt_host")
    if str(row.get("status") or "") != "qualified":
        gates.append("receipt_status")
    integrity = dict(row.get("integrity") or {}) if isinstance(row.get("integrity"), dict) else {}
    if not integrity or str(row.get("receipt_id") or "") != stable_receipt_digest(integrity):
        gates.append("receipt_integrity")
    if integrity and (
        _provider_key(integrity.get("host")) != key
        or int(integrity.get("port") or 0) != int(row.get("port") or 0)
        or str(integrity.get("checked_at") or "") != str(row.get("checked_at") or "")
    ):
        gates.append("receipt_binding")
    binding_fields = (
        "session_process_id", "source_path", "source_fingerprint", "environment_fingerprint",
        "application_version", "bridge_protocol", "bridge_implementation", "snapshot_digest",
    )
    if integrity and any(row.get(name) != integrity.get(name) for name in binding_fields):
        gates.append("receipt_binding")
    if integrity and (
        list(row.get("missing_gates") or []) != list(integrity.get("qualification_gates") or [])
        or bool(integrity.get("qualification_gates"))
    ):
        gates.append("receipt_qualification_gates")
    if not row.get("exact_session_verified") or not integrity.get("exact_session_verified"):
        gates.append("exact_session_proof")
    if not row.get("non_mutating_verified") or not integrity.get("non_mutating_verified"):
        gates.append("non_mutating_proof")
    evidence = dict(row.get("role_evidence") or {}) if isinstance(row.get("role_evidence"), dict) else {}
    if not evidence.get("sufficient") or evidence != integrity.get("role_evidence"):
        gates.append("role_source_evidence")

    checked_at = parse_receipt_datetime(row.get("checked_at"))
    current_time = now.astimezone(timezone.utc) if isinstance(now, datetime) else datetime.now(timezone.utc)
    age_seconds: float | None = None
    if checked_at is None:
        gates.append("receipt_timestamp")
    else:
        age_seconds = (current_time - checked_at).total_seconds()
        if age_seconds < -300.0 or age_seconds > max(1.0, float(max_age_seconds)):
            gates.append("receipt_freshness")
    if str(row.get("environment_fingerprint") or "") != receipt_environment_fingerprint():
        gates.append("receipt_environment")

    target = bridge
    live_session: dict[str, Any] = {}
    if integrity:
        try:
            target = target if target is not None else bridge_for_host(key)
            current_bridge = bridge_implementation_fingerprint(target)
            if current_bridge != row.get("bridge_implementation"):
                gates.append("bridge_implementation_changed")
        except Exception:
            gates.append("bridge_implementation_unavailable")

    source_path = str(row.get("source_path") or "")
    saved_source = row.get("source_fingerprint") if isinstance(row.get("source_fingerprint"), dict) else {}
    current_source = safe_source_fingerprint(source_path) if check_source else saved_source
    if check_source and saved_source.get("exists"):
        if not current_source.get("exists"):
            gates.append("source_unavailable")
        elif current_source != saved_source:
            gates.append("source_revision_changed")

    if require_live_session and integrity and target is not None and not any(
        gate in gates for gate in ("receipt_integrity", "receipt_binding", "bridge_implementation_changed")
    ):
        try:
            live_session = dict(target.session_info(
                port=int(row.get("port") or 0),
                timeout=max(0.1, float(live_timeout)),
            ) or {})
        except Exception as exc:
            live_session = {"ok": False, "error": str(exc)}
        if not live_session.get("ok"):
            gates.append("live_session_unavailable")
        else:
            if int(live_session.get("port") or 0) != int(row.get("port") or 0):
                gates.append("live_session_port_changed")
            if _session_identity(live_session) != str(row.get("session_identity_before") or ""):
                gates.append("live_session_identity_changed")
            saved_version = str(row.get("application_version") or "")
            live_version = str(live_session.get("version") or live_session.get("application_version") or "")
            if saved_version and live_version and saved_version != live_version:
                gates.append("live_application_version_changed")
            saved_state = dict(row.get("observer_state_after") or {})
            dirty_keys = ("dirty", "is_dirty", "modified", "scene_modified", "has_unsaved_changes")
            if any(
                key in saved_state and key in live_session and saved_state[key] != live_session[key]
                for key in dirty_keys
            ):
                gates.append("live_source_state_changed")

    unique_gates = sorted(set(gates))
    return {
        "host": key,
        "status": "valid" if not unique_gates else "invalid",
        "valid": not unique_gates,
        "gates": unique_gates,
        "receipt_id": str(row.get("receipt_id") or ""),
        "age_seconds": age_seconds,
        "max_age_seconds": max(1.0, float(max_age_seconds)),
        "source_path": source_path,
        "saved_source_fingerprint": saved_source,
        "current_source_fingerprint": current_source,
        "live_session": live_session,
        "live_session_required": bool(require_live_session),
    }


def qualify_available_dcc_sources(
    *,
    hosts: list[str] | tuple[str, ...] | None = None,
    session_ports: dict[str, int] | None = None,
    bridge_factory=None,
    timeout: float = 5.0,
    latency_budget_ms: float = 5000.0,
    object_limit: int = 24,
    persist: bool = False,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Qualify available exact sessions without guessing among multiple endpoints."""

    requested_hosts = [_provider_key(value) for value in (hosts or tuple(HOST_ROLE_PROFILES))]
    invalid = [value for value in requested_hosts if value not in HOST_ROLE_PROFILES]
    if invalid:
        raise ValueError(f"Unsupported DCC source-parity host(s): {', '.join(invalid)}")
    factory = bridge_factory or bridge_for_host
    selected_ports = {_provider_key(key): int(value) for key, value in dict(session_ports or {}).items()}
    rows: list[dict[str, Any]] = []
    for host in requested_hosts:
        try:
            bridge = factory(host)
            ports = [int(value) for value in bridge.find_ports()]
        except Exception as exc:
            rows.append({"host": host, "status": "discovery_failed", "ports": [], "error": str(exc)})
            continue
        requested_port = selected_ports.get(host)
        preferred = preferred_session_port(host)
        if requested_port is not None and requested_port not in ports:
            rows.append({
                "host": host, "status": "selected_session_unavailable", "ports": ports,
                "selected_port": requested_port,
            })
            continue
        if requested_port is None:
            if preferred in ports:
                requested_port = int(preferred)
            elif len(ports) == 1:
                requested_port = ports[0]
            elif len(ports) > 1:
                rows.append({"host": host, "status": "selection_required", "ports": ports})
                continue
            else:
                rows.append({"host": host, "status": "unavailable", "ports": []})
                continue
        receipt = qualify_dcc_source_parity(
            host,
            requested_port,
            bridge=bridge,
            timeout=timeout,
            latency_budget_ms=latency_budget_ms,
            object_limit=object_limit,
        )
        if persist:
            store_source_parity_receipt(receipt, ledger_path)
        rows.append({
            "host": host,
            "status": receipt["status"],
            "ports": ports,
            "selected_port": requested_port,
            "receipt": receipt,
        })
    return {
        "schema": "tech_connector.dcc_source_parity_batch.v1",
        "hosts": rows,
        "summary": {
            "host_count": len(rows),
            "qualified": sum(row["status"] == "qualified" for row in rows),
            "unavailable": sum(row["status"] == "unavailable" for row in rows),
            "selection_required": sum(row["status"] == "selection_required" for row in rows),
            "failed": sum(row["status"] in {"unqualified", "discovery_failed", "selected_session_unavailable"} for row in rows),
        },
    }


def source_parity_ledger(path: str | Path | None = None) -> dict[str, Any]:
    ledger_path = Path(path) if path is not None else DEFAULT_SOURCE_PARITY_LEDGER_PATH
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    receipts = dict(data.get("receipts") or {}) if isinstance(data, dict) else {}
    return {
        "schema": SOURCE_PARITY_QUALIFICATION_SCHEMA,
        "path": str(ledger_path),
        "receipts": receipts,
        "summary": {
            "host_count": len(HOST_ROLE_PROFILES),
            "recorded_hosts": len(receipts),
            "qualified_hosts": sum(
                isinstance(row, dict) and row.get("status") == "qualified"
                for row in receipts.values()
            ),
        },
    }


def store_source_parity_receipt(
    receipt: dict[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    host = _provider_key(receipt.get("host") if isinstance(receipt, dict) else "")
    if host not in HOST_ROLE_PROFILES:
        raise ValueError("A source-parity receipt must identify a supported host.")
    ledger_path = Path(path) if path is not None else DEFAULT_SOURCE_PARITY_LEDGER_PATH
    ledger = source_parity_ledger(ledger_path)
    receipts = dict(ledger["receipts"])
    receipts[host] = dict(receipt)
    payload = {"schema": SOURCE_PARITY_QUALIFICATION_SCHEMA, "receipts": receipts}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=ledger_path.name + ".", suffix=".tmp", dir=str(ledger_path.parent),
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        Path(temp_name).replace(ledger_path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return source_parity_ledger(ledger_path)


def _snapshot_result(result: Any) -> tuple[bool, Any]:
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[0]), result[1]
    if isinstance(result, dict) and "ok" in result:
        return bool(result.get("ok")), result.get("snapshot", result.get("data", result))
    return isinstance(result, dict), result


def _provider_key(value: Any) -> str:
    key = str(value or "").strip().lower().split(":", 1)[0]
    return "3dsmax" if key in {"max", "3ds_max", "3ds max"} else key


def _session_identity(row: dict[str, Any]) -> str:
    process = str(row.get("session_id") or row.get("pid") or row.get("process_id") or "").strip()
    scene = _scene_identity(row)
    return "|".join(value for value in (process, scene) if value)


def _scene_identity(row: dict[str, Any]) -> str:
    for name in ("scene", "project", "project_path", "document", "document_path", "file", "file_path"):
        value = str(row.get(name) or "").strip()
        if value:
            return value
    return ""


def _snapshot_matches_session(snapshot: dict[str, Any], session: dict[str, Any]) -> bool:
    snapshot_pid = str(snapshot.get("process_id") or snapshot.get("pid") or "").strip()
    session_pid = str(session.get("pid") or session.get("process_id") or "").strip()
    if snapshot_pid and session_pid and snapshot_pid != session_pid:
        return False
    comparable_identity = False
    for name in ("scene", "project", "project_path", "document", "document_path", "file", "file_path"):
        snapshot_value = str(snapshot.get(name) or "").strip()
        session_value = str(session.get(name) or "").strip()
        if snapshot_value and session_value:
            comparable_identity = True
            if snapshot_value != session_value:
                return False
    return bool(snapshot_pid or session_pid or comparable_identity or session.get("session_id"))


def _observer_state(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _OBSERVER_STATE_KEYS if key in row}


def _changed_observer_state(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    changed: dict[str, dict[str, Any]] = {}
    for key in _OBSERVER_STATE_KEYS:
        if key in before and key in after and before[key] != after[key]:
            changed[key] = {"before": before[key], "after": after[key]}
    return changed


def _role_evidence(host: str, snapshot: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    objects = [row for row in snapshot.get("objects") or [] if isinstance(row, dict) and row.get("type") != "error"]
    lookdev = lookdev_state_from_snapshot(snapshot, source_provider=host).to_dict()
    material_count = len(lookdev.get("materials") or {})
    assignments = list(lookdev.get("assignments") or [])
    texture_count = len(lookdev.get("texture_assets") or {})
    capture_status = str(profile.get("capture_status") or "unsupported")
    details: dict[str, Any] = {
        "capture_status": capture_status,
        "object_count": len(objects),
        "material_count": material_count,
        "assignment_count": len(assignments),
        "texture_asset_count": texture_count,
        "sufficient": False,
    }
    if capture_status in {"native", "partial"}:
        details["sufficient"] = bool(objects and material_count and assignments)
        details["required"] = "visible object plus material definition and assignment"
    elif capture_status == "lookdev_only":
        texture_sets = [row for row in objects if str(row.get("type") or "").lower() == "texture_set"]
        details["texture_set_count"] = len(texture_sets)
        details["sufficient"] = bool(texture_sets and material_count and assignments)
        details["required"] = "texture-set inventory plus material and assignment metadata"
    elif capture_status == "not_role_required":
        details["sufficient"] = bool(_scene_identity(snapshot) or objects or snapshot.get("cameras"))
        details["required"] = "stable scene/animation interchange identity or scene elements"
    elif capture_status == "image_document_native":
        document = snapshot.get("image_document_state")
        document = dict(document) if isinstance(document, dict) else {}
        details["document_width"] = int(document.get("width") or 0)
        details["document_height"] = int(document.get("height") or 0)
        details["layer_count"] = len(document.get("layers") or [])
        details["sufficient"] = bool(
            details["document_width"] > 0
            and details["document_height"] > 0
            and "layers" in document
        )
        details["required"] = "document dimensions and layer inventory"
    return details


__all__ = [
    "DEFAULT_SOURCE_PARITY_LEDGER_PATH", "DEFAULT_SOURCE_PARITY_MAX_AGE_SECONDS",
    "SOURCE_PARITY_QUALIFICATION_SCHEMA", "qualify_available_dcc_sources",
    "qualify_dcc_source_parity", "source_parity_ledger", "store_source_parity_receipt",
    "validate_source_parity_receipt",
]
