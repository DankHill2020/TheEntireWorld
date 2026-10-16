"""Fast, ordered endpoint discovery shared by direct DCC bridges."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from tech_connector.bridges.session_preferences import preferred_session_port
from tech_connector.models.constants import APP_DIR


PORT_DISCOVERY_SETTINGS: dict[str, tuple[str, str, int]] = {
    "maya": ("MAYA_COMMAND_PORT", "MAYA_COMMAND_PORT_SCAN_COUNT", 10),
    "blender": ("BLENDER_COMMAND_PORT", "BLENDER_COMMAND_PORT_SCAN_COUNT", 10),
    "3dsmax": ("MAX_COMMAND_PORT", "MAX_COMMAND_PORT_SCAN_COUNT", 10),
    "motionbuilder": ("MOTIONBUILDER_COMMAND_PORT", "MOTIONBUILDER_COMMAND_PORT_SCAN_COUNT", 10),
    "houdini": ("HOUDINI_COMMAND_PORT", "HOUDINI_COMMAND_PORT_SCAN_COUNT", 10),
    "substance_painter": ("SUBSTANCE_PAINTER_COMMAND_PORT", "SUBSTANCE_PAINTER_COMMAND_PORT_SCAN_COUNT", 10),
    "unreal": ("UNREAL_HTTP_PORT", "UNREAL_HTTP_PORT_SCAN_COUNT", 10),
    "unity": ("UNITY_COMMAND_PORT", "UNITY_COMMAND_PORT_SCAN_COUNT", 10),
    "photoshop": ("PHOTOSHOP_BRIDGE_PORT", "PHOTOSHOP_PORT_SCAN_COUNT", 5),
    "gimp": ("GIMP_COMMAND_PORT", "GIMP_PORT_SCAN_COUNT", 5),
}
_REGISTRY_LOCK = threading.Lock()


def bridge_port_registry_path() -> Path:
    override = os.environ.get("TECH_CONNECTOR_BRIDGE_PORT_REGISTRY_FILE", "").strip()
    return Path(override).expanduser() if override else Path(APP_DIR) / "bridge_ports.json"


def load_bridge_port_registry() -> dict:
    path = bridge_port_registry_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    providers = payload.get("providers")
    return {
        "schema": "tech_connector.bridge_port_registry.v1",
        "updated_at": str(payload.get("updated_at") or ""),
        "providers": dict(providers) if isinstance(providers, dict) else {},
        "path": str(path),
    }


def _persist_bridge_diagnostics(evidence: dict) -> None:
    path = bridge_port_registry_path()
    with _REGISTRY_LOCK:
        registry = load_bridge_port_registry()
        providers = dict(registry["providers"])
        providers.pop("", None)
        row = dict(evidence)
        row.pop("registry_path", None)
        row["observed_at"] = datetime.now(timezone.utc).isoformat()
        providers[str(evidence.get("provider") or "")] = row
        payload = {
            "schema": "tech_connector.bridge_port_registry.v1",
            "updated_at": row["observed_at"],
            "providers": providers,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp",
        )
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        for attempt in range(3):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt >= 2:
                    raise
                time.sleep(0.02 * (attempt + 1))


def bridge_session_diagnostics(
    provider: str,
    bridge: object,
    *,
    host: str = "127.0.0.1",
    live_ports: Iterable[int] | None = None,
) -> dict:
    """Explain every port source used by a bridge without hiding stale state."""

    key = str(provider or "").strip().lower()
    environment_variable, scan_variable, default_scan_count = PORT_DISCOVERY_SETTINGS.get(
        key, ("", "", 10),
    )
    info = getattr(bridge, "info", None)
    default_port = int(
        getattr(bridge, "DEFAULT_PORT", 0)
        or getattr(info, "default_port", 0)
        or 0
    )
    paths: list[Path] = []
    raw_paths = list(getattr(bridge, "PORT_FILES", ()) or ())
    single_path = getattr(bridge, "PORT_FILE", None)
    if single_path:
        raw_paths.append(single_path)
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if path not in paths:
            paths.append(path)

    file_rows = []
    source_ports: dict[int, list[str]] = {}

    def add_source(port: int | None, source: str) -> None:
        if port is None or not 0 < int(port) < 65536:
            return
        source_ports.setdefault(int(port), [])
        if source not in source_ports[int(port)]:
            source_ports[int(port)].append(source)

    preferred = preferred_session_port(key)
    add_source(preferred, "preferred_session")
    configured_environment_port = None
    if environment_variable:
        try:
            configured_environment_port = int(os.environ.get(environment_variable, "") or 0) or None
        except (TypeError, ValueError):
            configured_environment_port = None
        add_source(configured_environment_port, f"environment:{environment_variable}")

    for path in paths:
        raw_value = ""
        recorded_port = None
        try:
            raw_value = path.read_text(encoding="utf-8").strip()
            recorded_port = int(raw_value)
            if not 0 < recorded_port < 65536:
                recorded_port = None
        except (OSError, TypeError, ValueError):
            recorded_port = None
        file_rows.append({
            "path": str(path),
            "exists": path.is_file(),
            "raw_value": raw_value,
            "port": recorded_port,
            "valid": recorded_port is not None,
        })
        add_source(recorded_port, f"port_file:{path}")

    recorded_sessions = []
    session_file = getattr(bridge, "SESSION_FILE", None)
    if callable(getattr(bridge, "recorded_sessions", None)):
        try:
            recorded_sessions = list(bridge.recorded_sessions() or [])
        except Exception:
            recorded_sessions = []
    for row in recorded_sessions:
        try:
            add_source(int(row.get("port") or 0), "session_registry")
        except (AttributeError, TypeError, ValueError):
            continue

    try:
        scan_count = int(os.environ.get(scan_variable, default_scan_count)) if scan_variable else default_scan_count
    except (TypeError, ValueError):
        scan_count = default_scan_count
    scan_count = max(1, min(100, scan_count))
    scan_ports = list(range(default_port, default_port + scan_count)) if default_port else []
    for port in scan_ports:
        add_source(port, "default_scan")

    candidate_ports: list[int] = []
    if callable(getattr(bridge, "_candidate_ports", None)):
        try:
            raw_candidates = list(bridge._candidate_ports() or [])
            candidate_ports = [
                int(row[0] if isinstance(row, tuple) else row)
                for row in raw_candidates
                if 0 < int(row[0] if isinstance(row, tuple) else row) < 65536
            ]
        except Exception:
            candidate_ports = []
    if not candidate_ports:
        candidate_ports = list(source_ports)
    candidate_ports = list(dict.fromkeys(candidate_ports))

    if live_ports is None:
        try:
            current_live_ports = [int(port) for port in bridge.find_ports(host=host)]
        except TypeError:
            current_live_ports = [int(port) for port in bridge.find_ports()]
        except Exception:
            current_live_ports = []
    else:
        current_live_ports = [int(port) for port in live_ports]
    current_live_ports = list(dict.fromkeys(current_live_ports))
    persisted_ports = {
        int(row["port"]) for row in file_rows if row["port"] is not None
    }
    for row in recorded_sessions:
        try:
            persisted_ports.add(int(row.get("port") or 0))
        except (AttributeError, TypeError, ValueError):
            pass
    persisted_ports.discard(0)
    live_set = set(current_live_ports)
    evidence = {
        "schema": "tech_connector.bridge_port_diagnostics.v1",
        "provider": key,
        "host": host,
        "default_port": default_port or None,
        "preferred_port": preferred,
        "selected_port": current_live_ports[0] if current_live_ports else None,
        "environment": {
            "name": environment_variable,
            "configured": configured_environment_port is not None,
            "port": configured_environment_port,
        },
        "scan": {
            "count_environment": scan_variable,
            "count": scan_count,
            "range": [scan_ports[0], scan_ports[-1]] if scan_ports else [],
        },
        "port_files": file_rows,
        "session_registry_path": str(Path(session_file).expanduser()) if session_file else "",
        "recorded_sessions": recorded_sessions,
        "candidate_ports": candidate_ports,
        "port_sources": {str(port): sources for port, sources in source_ports.items()},
        "live_ports": current_live_ports,
        "stale_ports": sorted(persisted_ports - live_set),
        "registry_path": str(bridge_port_registry_path()),
    }
    try:
        _persist_bridge_diagnostics(evidence)
    except OSError:
        evidence["registry_write_failed"] = True
    return evidence


def candidate_session_ports(
    provider: str,
    *,
    port_files: Iterable[str] = (),
    environment_variable: str = "",
    default_port: int,
    scan_count_variable: str = "",
    default_scan_count: int = 10,
) -> list[int]:
    candidates: list[int] = []
    preferred = preferred_session_port(provider)
    if preferred:
        candidates.append(int(preferred))
    for path in port_files:
        try:
            candidates.append(int(Path(path).read_text(encoding="utf-8").strip()))
        except Exception:
            pass
    if environment_variable:
        try:
            configured = int(os.environ.get(environment_variable, "") or 0)
        except (TypeError, ValueError):
            configured = 0
        if configured:
            candidates.append(configured)
    try:
        scan_count = int(os.environ.get(scan_count_variable, default_scan_count)) if scan_count_variable else default_scan_count
    except (TypeError, ValueError):
        scan_count = default_scan_count
    candidates.extend(range(int(default_port), int(default_port) + max(1, min(100, scan_count))))
    return list(dict.fromkeys(port for port in candidates if 0 < int(port) < 65536))


def discover_open_ports(
    candidates: Iterable[int],
    *,
    host: str = "127.0.0.1",
    timeout: float = 0.05,
    max_workers: int = 16,
) -> list[int]:
    ordered = list(dict.fromkeys(int(port) for port in candidates))
    if not ordered:
        return []

    def is_open(port: int) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(max(0.01, float(timeout)))
                return probe.connect_ex((host, port)) == 0
        except Exception:
            return False

    found: set[int] = set()
    with ThreadPoolExecutor(max_workers=min(len(ordered), max(1, int(max_workers)))) as executor:
        futures = {executor.submit(is_open, port): port for port in ordered}
        for future in as_completed(futures):
            try:
                if future.result():
                    found.add(futures[future])
            except Exception:
                pass
    return [port for port in ordered if port in found]


def parse_session_output(raw: object) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    for line in reversed(text.splitlines() or [text]):
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"raw": text}


__all__ = [
    "PORT_DISCOVERY_SETTINGS",
    "bridge_port_registry_path",
    "bridge_session_diagnostics",
    "candidate_session_ports",
    "discover_open_ports",
    "load_bridge_port_registry",
    "parse_session_output",
]
