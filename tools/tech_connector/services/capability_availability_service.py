"""Planner-facing capability availability snapshots.

This module turns UI status lights, connected account settings, direct DCC
bridge checks, and integration package manifests into one small data contract.
It is intentionally cheap by default; live probes are opt-in.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


STATUS_TO_LIGHT = {
    "ok": "green",
    "connected": "green",
    "ready": "green",
    "busy": "yellow",
    "warn": "yellow",
    "unknown": "yellow",
    "off": "red",
    "bad": "red",
    "failed": "red",
    "disconnected": "red",
    "missing": "red",
}


@dataclass
class HostAvailability:
    id: str
    connected: bool = False
    status: str = "unknown"
    light: str = "yellow"
    detail: str = ""
    source: str = "unknown"
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrationAvailability:
    id: str
    name: str
    connected: bool = False
    configured: bool = False
    validated: bool = False
    trusted: bool = False
    status: str = "discovered"
    light: str = "yellow"
    capabilities: list[str] = field(default_factory=list)
    health: dict[str, Any] = field(default_factory=dict)
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_status_light(status: str, detail: str = "") -> tuple[bool, str]:
    state = str(status or "").strip().lower()
    detail_lower = str(detail or "").lower()
    light = STATUS_TO_LIGHT.get(state, "yellow")
    connected = light == "green"
    if state == "unknown" and any(term in detail_lower for term in ("not connected", "missing", "stopped", "unreachable")):
        light = "red"
        connected = False
    return connected, light


def snapshot_status_cards(window: Any) -> dict[str, dict[str, Any]]:
    cards = getattr(window, "status_cards", {}) or {}
    snapshot: dict[str, dict[str, Any]] = {}
    for key, card in cards.items():
        text = ""
        style = ""
        try:
            text = str(card.text())
        except Exception:
            text = ""
        try:
            style = str(card.styleSheet())
        except Exception:
            style = ""
        state = _state_from_card_style(style)
        detail = text.split(":", 1)[1].strip() if ":" in text else text
        connected, light = normalize_status_light(state, detail)
        snapshot[str(key)] = {
            "id": str(key),
            "status": state,
            "detail": detail,
            "connected": connected,
            "light": light,
            "source": "status_card",
        }
    return snapshot


def build_capability_availability(
    *,
    status_cards: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
    command_router: Any = None,
    include_live_checks: bool = False,
) -> dict[str, Any]:
    hosts = _host_availability(status_cards or {}, command_router=command_router, include_live_checks=include_live_checks)
    integrations = _integration_availability(include_live_checks=include_live_checks)
    accounts = _account_availability(settings or {})
    warnings = _planner_warnings(hosts)
    return {
        "schema": "tech_connector.capability_availability.v1",
        "hosts": {key: value.to_dict() for key, value in hosts.items()},
        "integrations": {item.id: item.to_dict() for item in integrations},
        "accounts": accounts,
        "planner_warnings": warnings,
    }


def warning_for_decision(decision: dict[str, Any], availability: dict[str, Any] | None) -> str:
    if not availability:
        return ""
    host = str(decision.get("host") or decision.get("execution_environment") or "").strip().lower()
    if not host or not bool(decision.get("requires_dcc_connection")):
        return ""
    hosts = dict(availability.get("hosts") or {})
    row = dict(hosts.get(host) or {})
    if row and not bool(row.get("connected")):
        detail = str(row.get("detail") or row.get("status") or "not connected")
        label = host.replace("_", " ").title()
        return (
            f"{label} is currently disconnected (status light: {row.get('light', 'unknown')}). "
            f"{detail}. I can prepare plans or local changes, but direct execution is disabled until the host bridge is available."
        )
    return ""


def _host_availability(
    status_cards: dict[str, Any],
    *,
    command_router: Any = None,
    include_live_checks: bool = False,
) -> dict[str, HostAvailability]:
    host_ids = ("maya", "unreal", "blender", "substance_painter", "motionbuilder", "unity", "houdini")
    hosts: dict[str, HostAvailability] = {}
    for host in host_ids:
        row = dict(status_cards.get(host) or {})
        status = str(row.get("status") or "unknown")
        detail = str(row.get("detail") or "")
        connected, light = normalize_status_light(status, detail)
        hosts[host] = HostAvailability(
            id=host,
            connected=connected,
            status=status,
            light=light,
            detail=detail,
            source=str(row.get("source") or "status_card"),
            capabilities=["live context", "execute commands"] if connected else ["plan only"],
        )
    if include_live_checks:
        _apply_live_bridge_checks(hosts, command_router)
    return hosts


def _apply_live_bridge_checks(hosts: dict[str, HostAvailability], command_router: Any = None) -> None:
    try:
        from tech_connector.services.connected_account_service import connected_application_status

        for row in connected_application_status({}, command_router):
            app_id = str(row.get("id") or "").lower()
            if app_id in hosts:
                connected = bool(row.get("connected"))
                hosts[app_id].connected = connected
                hosts[app_id].status = "ok" if connected else "off"
                hosts[app_id].light = "green" if connected else "red"
                hosts[app_id].detail = str(row.get("mode") or "")
                hosts[app_id].source = "live_bridge_check"
                hosts[app_id].capabilities = list(row.get("capabilities") or [])
    except Exception:
        pass


def _integration_availability(*, include_live_checks: bool = False) -> list[IntegrationAvailability]:
    try:
        from tech_connector.services.integration_package_service import load_integration_packages
    except Exception:
        return []
    rows: list[IntegrationAvailability] = []
    for package in load_integration_packages():
        lifecycle = dict(package.get("lifecycle") or {})
        bridge = dict(package.get("bridge_manifest") or {})
        health = _run_package_health_check(bridge) if include_live_checks else {}
        connected = bool(health.get("ok")) if health else bool(lifecycle.get("connected") or bridge.get("capability_states", {}).get("connected"))
        validated = bool(lifecycle.get("validated") or bridge.get("capability_states", {}).get("validated"))
        trusted = bool(lifecycle.get("trusted") or bridge.get("capability_states", {}).get("trusted"))
        configured = bool(lifecycle.get("configured") or connected or validated or trusted)
        status = "trusted" if trusted else "validated" if validated else "connected" if connected else "configured" if configured else "discovered"
        light = "green" if connected or validated or trusted else "yellow" if configured else "red"
        capabilities = [
            str(cap.get("id") or cap.get("name"))
            for cap in (package.get("capabilities") or [])
            if cap.get("id") or cap.get("name")
        ]
        rows.append(IntegrationAvailability(
            id=str(package.get("id") or ""),
            name=str(package.get("name") or package.get("id") or ""),
            connected=connected,
            configured=configured,
            validated=validated,
            trusted=trusted,
            status=status,
            light=light,
            capabilities=capabilities,
            health=health,
            path=str(package.get("path") or ""),
        ))
    return rows


def _run_package_health_check(bridge: dict[str, Any]) -> dict[str, Any]:
    path = str((bridge.get("entrypoints") or {}).get("health_check") or "").strip()
    if not path or "." not in path:
        return {}
    try:
        from tech_connector.services.modular_provider_utils import invoke_custom_provider

        return dict(invoke_custom_provider(path, lambda: {"ok": False, "message": "No health check."}, allow_fallback=False))
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def _account_availability(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        from tech_connector.services.connected_account_service import connected_account_summary

        return connected_account_summary(settings)
    except Exception:
        return {"connected": [], "pending": [], "rows": []}


def _planner_warnings(hosts: dict[str, HostAvailability]) -> list[str]:
    warnings = []
    for host, row in hosts.items():
        if row.light == "red":
            warnings.append(f"{host}: {row.detail or row.status}")
    return warnings


def _state_from_card_style(style: str) -> str:
    lower = str(style or "").lower()
    if "#0f3d24" in lower or "#164b2f" in lower or "ok" in lower:
        return "ok"
    if "#4d3b10" in lower or "warn" in lower or "busy" in lower:
        return "warn"
    if "#3b1010" in lower or "bad" in lower:
        return "bad"
    if "#1a1f26" in lower or "off" in lower:
        return "off"
    return "unknown"
