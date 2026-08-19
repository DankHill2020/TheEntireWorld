"""Bridge session preference helpers shared by UI and direct bridge callers."""

from __future__ import annotations

import socket


def preferred_session_port(provider: str) -> int | None:
    provider_key = str(provider or "").strip().lower()
    if not provider_key:
        return None
    try:
        from tech_connector.services.settings_service import load_settings

        preferred = load_settings().get("dcc_preferred_session_keys", {})
    except Exception:
        preferred = {}
    if not isinstance(preferred, dict):
        return None
    session_key = str(preferred.get(provider_key) or "").strip().lower()
    if ":" not in session_key:
        return None
    try:
        return int(session_key.split(":", 1)[1])
    except Exception:
        return None


def is_port_open(port: int | None, *, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    if not port:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False
