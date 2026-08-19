"""Fast, ordered endpoint discovery shared by direct DCC bridges."""

from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from tech_connector.bridges.session_preferences import preferred_session_port


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


__all__ = ["candidate_session_ports", "discover_open_ports", "parse_session_output"]
