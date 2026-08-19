"""Evidence ledger and read-only live probes for supported DCC host profiles."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_receipt_integrity_service import (
    bridge_implementation_fingerprint,
    parse_receipt_datetime,
    receipt_environment_fingerprint,
    stable_receipt_digest,
)
from tech_connector.models.constants import APP_DIR


QUALIFICATION_SCHEMA = "tech_connector.dcc_host_qualification.v2"
DEFAULT_QUALIFICATION_MAX_AGE_SECONDS = 24.0 * 60.0 * 60.0
DEFAULT_LEDGER_PATH = Path(APP_DIR) / "dcc_host_qualification_receipts.json"


@dataclass(frozen=True)
class DccHostRoleProfile:
    host: str
    role: str
    representative_operations: tuple[str, ...]
    intentionally_out_of_scope: tuple[str, ...] = ()
    qualification_scope: tuple[str, ...] = ()


@dataclass(frozen=True)
class DccHostQualificationReceipt:
    host: str
    role: str
    checked_at: str
    protocol: str
    representative_operations: tuple[str, ...]
    missing_representative_operations: tuple[str, ...]
    discovered_ports: tuple[int, ...]
    responding_sessions: tuple[dict[str, Any], ...]
    preferred_port: int | None
    preferred_session_honored: bool | None
    multi_session_supported: bool
    multi_session_verified: bool
    live_readback: bool
    install_recovery_verified: bool = False
    status: str = "structural"
    missing_gates: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    qualification_scope: tuple[str, ...] = ()
    intentionally_out_of_scope: tuple[str, ...] = ()
    identity_latency_budget_ms: float = 1000.0
    identity_latency_budget_met: bool = False
    exact_session_identity_verified: bool = False
    identity_latency_sample_count: int = 1
    install_recovery_evidence: dict[str, Any] = field(default_factory=dict)
    receipt_id: str = ""
    environment_fingerprint: str = ""
    bridge_implementation: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


HOST_ROLE_PROFILES: dict[str, DccHostRoleProfile] = {
    "maya": DccHostRoleProfile(
        "maya", "Character rigging, modeling, skinning, and animation authoring",
        (
            "scene.select", "modeling.create_primitive", "skin.bind", "rigging.create_rig",
            "animation.export", "pipeline.inspect_rigged_proxy",
        ),
    ),
    "blender": DccHostRoleProfile(
        "blender", "Generalist modeling, look development, animation, rendering, and interchange",
        (
            "scene.select", "modeling.create_primitive", "material.create", "animation.set_key",
            "animation.bake", "render.render_scene", "io.export_fbx", "workflow.inspect_generalist_asset",
        ),
    ),
    "3dsmax": DccHostRoleProfile(
        "3dsmax", "Modifier-based modeling, materials, animation, and interchange",
        (
            "scene.select", "mesh.create_box", "mesh.apply_modifier", "material.assign",
            "animation.set_key", "io.export", "workflow.inspect_modifier_asset",
        ),
    ),
    "motionbuilder": DccHostRoleProfile(
        "motionbuilder", "Characterization, retargeting, take cleanup, plotting, native constraints/control rigs, and FBX interchange",
        ("character.create_character", "character.plot_animation", "character.inspect", "io.import_fbx", "io.export_fbx"),
        (
            "rig.build_full", "rig.build_module", "rig.remove_module", "rig.rebuild_module",
            "rig.edit_control_shape", "rig.create_reverse_foot", "rig.create_ribbon",
            "rig.create_twist", "rig.create_motion_path", "rig.create_mesh_attachment",
            "rig.create_pose_reader", "rig.create_face_module", "rig.create_spline_chain",
            "rig.create_quadruped_ik", "rig.skin_bind",
        ),
        qualification_scope=(
            "characterization", "retargeting", "take_management", "animation_cleanup",
            "plotting", "native_constraints", "native_control_rig", "fbx_interchange",
        ),
    ),
    "houdini": DccHostRoleProfile(
        "houdini", "Procedural geometry, effects, simulation, rendering, and USD interchange",
        (
            "node.create", "node.connect", "simulation.run", "render.submit", "usd.export",
            "workflow.inspect_procedural_fx",
        ),
    ),
    "substance_painter": DccHostRoleProfile(
        "substance_painter", "Texture-set authoring, material application, and texture export",
        ("project.create", "material.apply", "textures.export"),
    ),
    "unreal": DccHostRoleProfile(
        "unreal", "Runtime assembly, Blueprint authoring, animation systems, effects, and play validation",
        ("project.snapshot", "blueprint.compile", "runtime.pie_begin", "runtime.pie_validate", "niagara.create_emitter"),
    ),
    "unity": DccHostRoleProfile(
        "unity", "Asset import, prefab and material assembly, and scene integration",
        (
            "assets.import_fbx", "material.create", "material.assign", "prefab.create",
            "scene.add_prefab", "workflow.inspect_prefab_asset",
        ),
    ),
    "photoshop": DccHostRoleProfile(
        "photoshop", "Layered texture and image authoring through explicit UXP operations",
        ("document.info", "layer.list", "selection.info", "document.batch_play"),
    ),
    "gimp": DccHostRoleProfile(
        "gimp", "Scripted image conversion and PBR texture channel assembly",
        ("image.convert_batch", "texture.pack_pbr", "script.run"),
    ),
}


def probe_dcc_host(
    host: str,
    *,
    bridge: Any | None = None,
    timeout: float = 3.0,
    max_sessions: int = 16,
    install_recovery_verified: bool = False,
    identity_latency_budget_ms: float = 1000.0,
    identity_latency_samples: int = 3,
) -> DccHostQualificationReceipt:
    key = str(host or "").strip().lower()
    if key not in HOST_ROLE_PROFILES:
        raise ValueError(f"Unsupported DCC qualification host: {host}")
    profile = HOST_ROLE_PROFILES[key]
    registry = dcc_operation_registry(key)
    missing_operations = tuple(op for op in profile.representative_operations if op not in registry)
    target = bridge if bridge is not None else bridge_for_host(key)
    protocol = str(getattr(getattr(target, "info", None), "protocol", "unknown") or "unknown")
    preferred = preferred_session_port(key)
    ports: list[int] = []
    sessions: list[dict[str, Any]] = []
    errors: list[str] = []
    multi_supported = callable(getattr(target, "find_ports", None)) and callable(getattr(target, "session_info", None))

    try:
        if callable(getattr(target, "find_ports", None)):
            ports = [int(port) for port in target.find_ports()][:max(1, int(max_sessions))]
        else:
            port = target.find_port()
            ports = [int(port)] if port else []
    except Exception as exc:
        errors.append(f"Endpoint discovery failed: {exc}")
    sample_count = max(1, int(identity_latency_samples))
    for port in ports:
        sample_rows: list[dict[str, Any]] = []
        sample_latencies: list[float] = []
        sample_failed = False
        for _sample_index in range(sample_count):
            started = time.perf_counter()
            try:
                if callable(getattr(target, "session_info", None)):
                    info = dict(target.session_info(port=port, timeout=timeout) or {})
                else:
                    info = {"ok": True, "port": port}
                latency = round((time.perf_counter() - started) * 1000.0, 3)
                info.setdefault("port", port)
                if not info.get("ok"):
                    errors.append(f"Port {port}: {info.get('error') or 'identity readback failed'}")
                    sample_failed = True
                    break
                sample_rows.append(info)
                sample_latencies.append(latency)
            except Exception as exc:
                errors.append(f"Port {port}: {exc}")
                sample_failed = True
                break
        if sample_failed or len(sample_rows) != sample_count:
            continue
        info = sample_rows[-1]
        identities = [
            str(row.get("session_id") or row.get("pid") or row.get("scene") or "").strip()
            for row in sample_rows
        ]
        p95_index = max(0, math.ceil(0.95 * len(sample_latencies)) - 1)
        p95_latency = sorted(sample_latencies)[p95_index]
        info["requested_port"] = port
        info["identity_latency_ms"] = p95_latency
        info["identity_latency_p95_ms"] = p95_latency
        info["identity_latency_samples_ms"] = sample_latencies
        info["identity_consistent"] = bool(identities[0]) and len(set(identities)) == 1
        sessions.append(info)

    live_readback = bool(sessions)
    identity_keys = [
        str(row.get("session_id") or row.get("pid") or row.get("scene") or "").strip()
        for row in sessions
    ]
    exact_session_identity = bool(sessions) and all(identity_keys) and all(
        int(row.get("port") or 0) == int(row.get("requested_port") or -1)
        for row in sessions
    ) and all(bool(row.get("identity_consistent")) for row in sessions)
    if len(sessions) > 1:
        exact_session_identity = exact_session_identity and len(set(identity_keys)) == len(identity_keys)
    latency_budget = max(1.0, float(identity_latency_budget_ms))
    latency_budget_met = bool(sessions) and all(
        float(row.get("identity_latency_ms") or latency_budget + 1.0) <= latency_budget
        for row in sessions
    )
    install_evidence: dict[str, Any] = {}
    if key == "maya" and sessions and any("bridge_bootstrap_version" in row for row in sessions):
        try:
            from tech_connector.bridges.maya.maya_livelink_plugin import (
                BOOTSTRAP_VERSION,
                verify_maya_livelink_installation,
            )

            disk_report = verify_maya_livelink_installation()
            runtime_versions = [str(row.get("bridge_bootstrap_version") or "") for row in sessions]
            runtime_sources = [str(row.get("bridge_bootstrap_source") or "") for row in sessions]
            verified_disk_paths = {
                os.path.normcase(os.path.abspath(str(row.get("path") or "")))
                for row in disk_report.get("paths") or []
                if row.get("current") and row.get("path")
            }
            runtime_capture = all(bool(row.get("bridge_capture_installed")) for row in sessions)
            runtime_current = bool(runtime_versions) and all(
                version == BOOTSTRAP_VERSION for version in runtime_versions
            )
            runtime_started_from_managed_setup = bool(runtime_sources) and all(
                bool(source)
                and os.path.normcase(os.path.abspath(source)) in verified_disk_paths
                for source in runtime_sources
            )
            reconnect_verified = sample_count >= 2 and all(
                bool(row.get("identity_consistent")) for row in sessions
            )
            automatic_recovery_verified = bool(
                disk_report.get("ok")
                and runtime_capture
                and runtime_current
                and runtime_started_from_managed_setup
                and reconnect_verified
            )
            install_recovery_verified = bool(
                install_recovery_verified or automatic_recovery_verified
            )
            install_evidence = {
                "disk_bootstrap_verified": bool(disk_report.get("ok")),
                "runtime_capture_verified": runtime_capture,
                "runtime_bootstrap_current": runtime_current,
                "runtime_versions": runtime_versions,
                "runtime_sources": runtime_sources,
                "runtime_started_from_managed_setup": runtime_started_from_managed_setup,
                "fresh_reconnect_verified": reconnect_verified,
                "automatic_recovery_verified": automatic_recovery_verified,
                "bootstrap_version": BOOTSTRAP_VERSION,
                "disk_paths": list(disk_report.get("paths") or []),
            }
        except Exception as exc:
            install_evidence = {"automatic_recovery_verified": False, "error": str(exc)}
    preferred_honored = None if preferred is None else bool(ports and ports[0] == preferred and any(row.get("port") == preferred for row in sessions))
    multi_verified = len(sessions) >= 2 and exact_session_identity
    missing_gates: list[str] = []
    if missing_operations:
        missing_gates.append("representative_operation_contract")
    if not live_readback:
        missing_gates.append("live_identity_readback")
    elif not exact_session_identity:
        missing_gates.append("exact_session_identity_readback")
    if live_readback and not latency_budget_met:
        missing_gates.append("identity_latency_budget")
    if preferred is not None and not preferred_honored:
        missing_gates.append("preferred_session_readback")
    if not multi_supported:
        missing_gates.append("multi_session_contract")
    if not install_recovery_verified:
        missing_gates.append("install_recovery_readback")
    if missing_operations:
        status = "incomplete"
    elif live_readback and exact_session_identity and latency_budget_met and install_recovery_verified:
        status = "qualified"
    elif live_readback and exact_session_identity and latency_budget_met:
        status = "live"
    else:
        status = "structural"
    checked_at = datetime.now(timezone.utc).isoformat()
    environment = receipt_environment_fingerprint()
    bridge_implementation = bridge_implementation_fingerprint(target)
    integrity = {
        "schema": QUALIFICATION_SCHEMA,
        "host": key,
        "checked_at": checked_at,
        "protocol": protocol,
        "representative_operations": list(profile.representative_operations),
        "missing_representative_operations": list(missing_operations),
        "discovered_ports": list(ports),
        "responding_sessions": sessions,
        "preferred_port": preferred,
        "preferred_session_honored": preferred_honored,
        "multi_session_supported": multi_supported,
        "multi_session_verified": multi_verified,
        "live_readback": live_readback,
        "install_recovery_verified": bool(install_recovery_verified),
        "status": status,
        "missing_gates": missing_gates,
        "identity_latency_budget_ms": latency_budget,
        "identity_latency_budget_met": latency_budget_met,
        "exact_session_identity_verified": exact_session_identity,
        "identity_latency_sample_count": sample_count,
        "environment_fingerprint": environment,
        "bridge_implementation": bridge_implementation,
    }
    return DccHostQualificationReceipt(
        host=key,
        role=profile.role,
        checked_at=checked_at,
        protocol=protocol,
        representative_operations=profile.representative_operations,
        missing_representative_operations=missing_operations,
        discovered_ports=tuple(ports),
        responding_sessions=tuple(sessions),
        preferred_port=preferred,
        preferred_session_honored=preferred_honored,
        multi_session_supported=multi_supported,
        multi_session_verified=multi_verified,
        live_readback=live_readback,
        install_recovery_verified=bool(install_recovery_verified),
        status=status,
        missing_gates=tuple(missing_gates),
        errors=tuple(errors),
        qualification_scope=profile.qualification_scope,
        intentionally_out_of_scope=profile.intentionally_out_of_scope,
        identity_latency_budget_ms=latency_budget,
        identity_latency_budget_met=latency_budget_met,
        exact_session_identity_verified=exact_session_identity,
        identity_latency_sample_count=sample_count,
        install_recovery_evidence=install_evidence,
        receipt_id=stable_receipt_digest(integrity),
        environment_fingerprint=environment,
        bridge_implementation=bridge_implementation,
        integrity=integrity,
    )


def validate_host_qualification_receipt(
    host: str,
    receipt: DccHostQualificationReceipt | dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_QUALIFICATION_MAX_AGE_SECONDS,
    bridge: Any | None = None,
    require_live_sessions: bool = True,
    live_timeout: float = 1.0,
) -> dict[str, Any]:
    key = str(host or "").strip().lower()
    row = receipt.to_dict() if isinstance(receipt, DccHostQualificationReceipt) else (
        dict(receipt or {}) if isinstance(receipt, dict) else {}
    )
    if not row:
        return {
            "host": key, "status": "invalid", "valid": False,
            "gates": ["missing_receipt"], "age_seconds": None, "live_sessions": [],
        }
    gates: list[str] = []
    if str(row.get("host") or "").strip().lower() != key:
        gates.append("receipt_host")
    integrity = dict(row.get("integrity") or {}) if isinstance(row.get("integrity"), dict) else {}
    if not integrity or str(row.get("receipt_id") or "") != stable_receipt_digest(integrity):
        gates.append("receipt_integrity")
    if str(integrity.get("schema") or "") != QUALIFICATION_SCHEMA:
        gates.append("receipt_schema")
    binding_fields = (
        "host", "checked_at", "protocol", "representative_operations",
        "missing_representative_operations", "discovered_ports", "responding_sessions",
        "preferred_port", "preferred_session_honored", "multi_session_supported",
        "multi_session_verified", "live_readback", "install_recovery_verified", "status",
        "missing_gates", "identity_latency_budget_ms", "identity_latency_budget_met",
        "exact_session_identity_verified", "identity_latency_sample_count",
        "environment_fingerprint", "bridge_implementation",
    )
    if integrity and any(_json_value(row.get(name)) != _json_value(integrity.get(name)) for name in binding_fields):
        gates.append("receipt_binding")
    if row.get("status") != "qualified":
        gates.append("receipt_status")
    if row.get("missing_gates"):
        gates.append("qualification_gates")
    if not row.get("live_readback") or not row.get("exact_session_identity_verified"):
        gates.append("exact_session_identity_readback")
    if not row.get("identity_latency_budget_met"):
        gates.append("identity_latency_budget")
    if not row.get("install_recovery_verified"):
        gates.append("install_recovery_readback")
    if str(row.get("environment_fingerprint") or "") != receipt_environment_fingerprint():
        gates.append("receipt_environment")

    checked_at = parse_receipt_datetime(row.get("checked_at"))
    current_time = now.astimezone(timezone.utc) if isinstance(now, datetime) else datetime.now(timezone.utc)
    age_seconds: float | None = None
    if checked_at is None:
        gates.append("receipt_timestamp")
    else:
        age_seconds = (current_time - checked_at).total_seconds()
        if age_seconds < -300.0 or age_seconds > max(1.0, float(max_age_seconds)):
            gates.append("receipt_freshness")

    target = bridge
    if integrity:
        try:
            target = target if target is not None else bridge_for_host(key)
            if bridge_implementation_fingerprint(target) != row.get("bridge_implementation"):
                gates.append("bridge_implementation_changed")
        except Exception:
            gates.append("bridge_implementation_unavailable")

    live_sessions: list[dict[str, Any]] = []
    if require_live_sessions and target is not None and not any(
        gate in gates for gate in ("receipt_integrity", "receipt_binding", "bridge_implementation_changed")
    ):
        for saved in row.get("responding_sessions") or []:
            port = int(dict(saved).get("port") or 0)
            try:
                current = dict(target.session_info(port=port, timeout=max(0.1, float(live_timeout))) or {})
            except Exception as exc:
                current = {"ok": False, "port": port, "error": str(exc)}
            live_sessions.append(current)
            if not current.get("ok"):
                gates.append("live_session_unavailable")
                continue
            if int(current.get("port") or 0) != port:
                gates.append("live_session_port_changed")
            if _qualification_session_identity(current) != _qualification_session_identity(dict(saved)):
                gates.append("live_session_identity_changed")

    unique_gates = sorted(set(gates))
    return {
        "host": key,
        "status": "valid" if not unique_gates else "invalid",
        "valid": not unique_gates,
        "gates": unique_gates,
        "receipt_id": str(row.get("receipt_id") or ""),
        "age_seconds": age_seconds,
        "max_age_seconds": max(1.0, float(max_age_seconds)),
        "live_sessions": live_sessions,
    }


def _qualification_session_identity(row: dict[str, Any]) -> str:
    return str(row.get("session_id") or row.get("pid") or row.get("scene") or "").strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def qualification_ledger(path: str | Path | None = None) -> dict[str, Any]:
    ledger_path = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    receipts = dict(data.get("receipts") or {}) if isinstance(data, dict) else {}
    return {
        "schema": QUALIFICATION_SCHEMA,
        "path": str(ledger_path),
        "receipts": receipts,
        "profiles": {host: asdict(profile) for host, profile in HOST_ROLE_PROFILES.items()},
        "summary": {
            "host_count": len(HOST_ROLE_PROFILES),
            "recorded_hosts": len(receipts),
            "live_hosts": sum(dict(row).get("live_readback") is True for row in receipts.values()),
            "qualified_hosts": sum(dict(row).get("status") == "qualified" for row in receipts.values()),
        },
    }


def store_qualification_receipt(
    receipt: DccHostQualificationReceipt,
    path: str | Path | None = None,
) -> dict[str, Any]:
    ledger_path = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    ledger = qualification_ledger(ledger_path)
    receipts = dict(ledger["receipts"])
    receipts[receipt.host] = receipt.to_dict()
    payload = {"schema": QUALIFICATION_SCHEMA, "receipts": receipts}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=ledger_path.name + ".", suffix=".tmp", dir=str(ledger_path.parent))
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
    return qualification_ledger(ledger_path)


def bridge_for_host(host: str) -> Any:
    if host == "maya":
        from tech_connector.bridges.maya.maya_bridge import MayaBridge
        return MayaBridge()
    if host == "blender":
        from tech_connector.bridges.blender.blender_bridge import BlenderBridge
        return BlenderBridge()
    if host == "3dsmax":
        from tech_connector.bridges.max.max_bridge import MaxBridge
        return MaxBridge()
    if host == "motionbuilder":
        from tech_connector.bridges.motionbuilder.motionbuilder_bridge import MotionBuilderBridge
        return MotionBuilderBridge()
    if host == "houdini":
        from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
        return HoudiniBridge()
    if host == "substance_painter":
        from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
        return SubstancePainterBridge()
    if host == "unreal":
        from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
        return UnrealBridge()
    if host == "unity":
        from tech_connector.bridges.unity.unity_bridge import UnityBridge
        return UnityBridge()
    if host == "photoshop":
        from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge
        return PhotoshopBridge()
    if host == "gimp":
        from tech_connector.bridges.gimp.gimp_bridge import GimpBridge
        return GimpBridge()
    raise ValueError(f"Unsupported DCC qualification host: {host}")


__all__ = [
    "DEFAULT_LEDGER_PATH", "DEFAULT_QUALIFICATION_MAX_AGE_SECONDS", "HOST_ROLE_PROFILES", "QUALIFICATION_SCHEMA",
    "DccHostQualificationReceipt", "DccHostRoleProfile", "probe_dcc_host",
    "bridge_for_host", "qualification_ledger", "store_qualification_receipt",
    "validate_host_qualification_receipt",
]
