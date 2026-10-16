"""Automatic per-user authorization for official DCC execution bridges.

Bridge availability is independent of product activation. A random local
capability is created automatically and is still required on every execution
request. Embedded hosts can validate it with the Python standard library,
without receiving account, project, or financial metadata.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


SCHEMA = "tech_connector.bridge_session.v1"
SUPPORTED_HOSTS = (
    "maya",
    "blender",
    "unreal",
    "houdini",
    "motionbuilder",
    "substance_painter",
    "unity",
    "3dsmax",
    "gimp",
    "standalone",
)
SESSION_FILENAME = "bridge_session.json"
BRIDGE_AUTHORIZATION_ERROR = {
    "ok": False,
    "error": "A valid local Tech Connector bridge session is required.",
    "code": "bridge_authorization_required",
}


@dataclass(frozen=True)
class BridgeSession:
    token: str
    issued_at: datetime
    expires_at: datetime
    hosts: tuple[str, ...]


def bridge_session_path(app_data_root: str | Path | None = None) -> Path:
    override = os.environ.get("TECH_CONNECTOR_BRIDGE_SESSION_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if app_data_root is None:
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
            app_data_root = (
                Path(local_app_data)
                if local_app_data
                else Path.home() / "AppData" / "Local"
            ) / "TechConnector"
        elif sys.platform == "darwin":
            app_data_root = Path.home() / "Library" / "Application Support" / "TechConnector"
        else:
            state_home = os.environ.get("XDG_STATE_HOME", "").strip()
            app_data_root = (
                Path(state_home) if state_home else Path.home() / ".local" / "state"
            ) / "tech_connector"
    return Path(app_data_root).expanduser() / "licensing" / SESSION_FILENAME


def bridge_session_path_for_context(licensing_context) -> Path:
    root = getattr(getattr(licensing_context, "entitlement_store", None), "root", None)
    return Path(root).expanduser() / SESSION_FILENAME if root else bridge_session_path()


def issue_bridge_session(
    evaluation,
    *,
    path: str | Path | None = None,
    hosts: Iterable[str] = SUPPORTED_HOSTS,
    now: datetime | None = None,
    maximum_lifetime: timedelta = timedelta(hours=12),
) -> BridgeSession:
    """Issue a host capability bounded by the verified entitlement's lifetime."""
    claims = getattr(evaluation, "claims", None)
    decision = getattr(evaluation, "decision", None)
    if claims is None or decision is None or not bool(getattr(decision, "allowed", False)):
        raise PermissionError("A valid Tech Connector entitlement is required for DCC bridge access.")
    if "dcc_host_access" not in claims.capabilities:
        raise PermissionError("This entitlement does not include DCC host access.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires_at = min(
        current + maximum_lifetime,
        claims.expires_at,
        claims.offline.expires_at,
    )
    if expires_at <= current:
        raise PermissionError("The Tech Connector entitlement is no longer valid for bridge access.")
    return _write_session(path, current, expires_at, hosts)


def issue_development_bridge_session(
    *,
    path: str | Path | None = None,
    hosts: Iterable[str] = SUPPORTED_HOSTS,
    now: datetime | None = None,
) -> BridgeSession:
    """Issue only under the explicit source-development bypass policy."""
    from tech_connector.services.licensing_startup_policy import (
        development_entitlement_bypass_allowed,
    )

    if not development_entitlement_bypass_allowed():
        raise PermissionError("The source-development entitlement bypass is not enabled.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return _write_session(path, current, current + timedelta(hours=12), hosts)


def issue_local_bridge_session(
    *,
    path: str | Path | None = None,
    hosts: Iterable[str] = SUPPORTED_HOSTS,
    now: datetime | None = None,
    lifetime: timedelta = timedelta(days=30),
) -> BridgeSession:
    """Issue an activation-independent, per-user bridge capability."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if lifetime <= timedelta(0):
        raise ValueError("bridge session lifetime must be positive")
    return _write_session(path, current, current + lifetime, hosts)


def ensure_local_bridge_session(
    host_id: str,
    *,
    path: str | Path | None = None,
    now: datetime | None = None,
) -> BridgeSession:
    """Return a current local session, creating or renewing it as needed."""
    existing = load_bridge_session(host_id, path=path, now=now)
    if existing is not None:
        return existing
    return issue_local_bridge_session(path=path, now=now)


def ensure_bridge_session_for_evaluation(
    evaluation,
    *,
    path: str | Path | None = None,
    now: datetime | None = None,
) -> BridgeSession:
    existing = load_bridge_session("standalone", path=path, now=now)
    if existing is not None and set(SUPPORTED_HOSTS).issubset(existing.hosts):
        return existing
    return issue_bridge_session(evaluation, path=path, now=now)


def _write_session(
    path: str | Path | None,
    issued_at: datetime,
    expires_at: datetime,
    hosts: Iterable[str],
) -> BridgeSession:
    allowed_hosts = tuple(sorted({str(host).strip().casefold() for host in hosts if str(host).strip()}))
    if not allowed_hosts or any(host not in SUPPORTED_HOSTS for host in allowed_hosts):
        raise ValueError("bridge session contains an unsupported host")
    session = BridgeSession(
        token=secrets.token_urlsafe(32),
        issued_at=issued_at,
        expires_at=expires_at,
        hosts=allowed_hosts,
    )
    target = Path(path).expanduser() if path is not None else bridge_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        target.name + "." + secrets.token_hex(8) + ".tmp"
    )
    temporary.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "session_token": session.token,
                "issued_at": session.issued_at.isoformat().replace("+00:00", "Z"),
                "expires_at": session.expires_at.isoformat().replace("+00:00", "Z"),
                "hosts": list(session.hosts),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _restrict_to_current_user(temporary)
    temporary.replace(target)
    _restrict_to_current_user(target)
    return session


def load_bridge_session(
    host_id: str,
    *,
    path: str | Path | None = None,
    now: datetime | None = None,
) -> BridgeSession | None:
    host = str(host_id or "").strip().casefold()
    target = Path(path).expanduser() if path is not None else bridge_session_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            return None
        token = str(payload.get("session_token") or "")
        issued_at = _parse_timestamp(payload.get("issued_at"))
        expires_at = _parse_timestamp(payload.get("expires_at"))
        hosts = tuple(str(item).strip().casefold() for item in payload.get("hosts") or ())
    except (OSError, TypeError, ValueError):
        return None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        len(token) < 32
        or host not in hosts
        or issued_at >= expires_at
        or issued_at > current
        or current >= expires_at
    ):
        return None
    return BridgeSession(token, issued_at, expires_at, hosts)


def bridge_session_token(host_id: str) -> str:
    """Return an automatically maintained per-user bridge capability."""
    try:
        return ensure_local_bridge_session(host_id).token
    except Exception:
        return ""


def validate_bridge_session(
    supplied_token: str,
    host_id: str,
    *,
    path: str | Path | None = None,
    now: datetime | None = None,
) -> bool:
    session = load_bridge_session(host_id, path=path, now=now)
    return bool(
        session is not None
        and supplied_token
        and hmac.compare_digest(session.token, str(supplied_token))
    )


def clear_bridge_session(*, path: str | Path | None = None) -> None:
    target = Path(path).expanduser() if path is not None else bridge_session_path()
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def embedded_bridge_authorization_source(host_id: str) -> str:
    """Return dependency-free validation code for an embedded DCC plugin."""
    host = str(host_id or "").strip().casefold()
    if host not in SUPPORTED_HOSTS:
        raise ValueError("unsupported embedded bridge host")
    return f'''# Tech Connector bridge session authorization (generated)
import datetime as _tc_datetime
import hmac as _tc_hmac
import json as _tc_json
import os as _tc_os
import sys as _tc_sys

_TECH_CONNECTOR_BRIDGE_HOST = {host!r}

def _tech_connector_bridge_session_path():
    override = _tc_os.environ.get("TECH_CONNECTOR_BRIDGE_SESSION_FILE", "").strip()
    if override:
        return override
    if _tc_os.name == "nt":
        base = _tc_os.environ.get("LOCALAPPDATA", "").strip()
        if not base:
            return ""
        return _tc_os.path.join(base, "TechConnector", "licensing", "bridge_session.json")
    if _tc_sys.platform == "darwin":
        return _tc_os.path.expanduser("~/Library/Application Support/TechConnector/licensing/bridge_session.json")
    base = _tc_os.environ.get("XDG_STATE_HOME", "").strip()
    if not base:
        base = _tc_os.path.expanduser("~/.local/state")
    return _tc_os.path.join(base, "tech_connector", "licensing", "bridge_session.json")

def _tech_connector_bridge_authorized(payload):
    supplied = str((payload or {{}}).get("bridge_session") or "")
    path = _tech_connector_bridge_session_path()
    if not supplied or not path:
        return False
    try:
        with open(path, "r", encoding="utf-8") as stream:
            session = _tc_json.load(stream)
        issued = str(session.get("issued_at") or "").replace("Z", "+00:00")
        expires = str(session.get("expires_at") or "").replace("Z", "+00:00")
        issued_at = _tc_datetime.datetime.fromisoformat(issued)
        expires_at = _tc_datetime.datetime.fromisoformat(expires)
        now = _tc_datetime.datetime.now(_tc_datetime.timezone.utc)
        hosts = [str(item).strip().lower() for item in session.get("hosts") or []]
        expected = str(session.get("session_token") or "")
        return bool(
            session.get("schema") == "{SCHEMA}"
            and _TECH_CONNECTOR_BRIDGE_HOST in hosts
            and issued_at.tzinfo is not None
            and expires_at.tzinfo is not None
            and issued_at.astimezone(_tc_datetime.timezone.utc) < expires_at.astimezone(_tc_datetime.timezone.utc)
            and issued_at.astimezone(_tc_datetime.timezone.utc) <= now
            and now < expires_at.astimezone(_tc_datetime.timezone.utc)
            and len(expected) >= 32
            and _tc_hmac.compare_digest(expected, supplied)
        )
    except Exception:
        return False
'''


def _parse_timestamp(value) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("bridge session timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _restrict_to_current_user(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
