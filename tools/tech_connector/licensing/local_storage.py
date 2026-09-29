"""Local signed-token cache and soft installation identity adapters."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class FileEntitlementStore:
    """Cache a signed entitlement token separately from general application settings."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.path = self.root / "entitlement.token"

    def load_token(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def save_token(self, token: str) -> None:
        value = str(token or "").strip()
        if not value:
            raise ValueError("cannot cache an empty entitlement token")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".token.tmp")
        temporary.write_text(value + "\n", encoding="utf-8")
        _restrict_to_current_user(temporary)
        temporary.replace(self.path)
        _restrict_to_current_user(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class InstallationDeviceIdentity:
    """A replaceable-install identity that avoids invasive hardware fingerprinting."""

    SCHEMA = "tech_connector.installation_identity.v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.path = self.root / "installation.json"

    def device_id_hash(self) -> str:
        installation_id = self._load_or_create()
        digest = hashlib.sha256(
            f"tech_connector_device_v1:{installation_id}".encode("utf-8")
        ).hexdigest()
        return "sha256:" + digest

    def _load_or_create(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != self.SCHEMA:
                raise ValueError("installation identity schema is not recognized")
            value = str(payload.get("installation_id") or "")
            uuid.UUID(value)
            return value
        except FileNotFoundError:
            pass

        self.root.mkdir(parents=True, exist_ok=True)
        value = str(uuid.uuid4())
        payload = json.dumps(
            {"schema": self.SCHEMA, "installation_id": value},
            indent=2,
        ) + "\n"
        try:
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                stat.S_IRUSR | stat.S_IWUSR,
            )
        except FileExistsError:
            return self._load_or_create()
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        _restrict_to_current_user(self.path)
        return value


class FileLicensingAuditSink:
    """Append a small privacy-safe local licensing event trail."""

    ALLOWED_EVENTS = {
        "login_authenticated",
        "device_activated",
        "entitlement_refreshed",
        "project_registered",
        "device_deactivated",
        "local_sign_out",
    }
    ALLOWED_METADATA = {
        "account_id",
        "organization_id",
        "license_id",
        "activation_id",
        "project_id",
        "token_id",
    }

    def __init__(
        self,
        root: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root).expanduser()
        self.path = self.root / "licensing_audit.jsonl"
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def record(self, event: str, metadata: Mapping[str, Any]) -> None:
        event_name = str(event or "").strip()
        if event_name not in self.ALLOWED_EVENTS:
            raise ValueError("unsupported licensing audit event")
        unknown = set(metadata) - self.ALLOWED_METADATA
        if unknown:
            raise ValueError("unsupported licensing audit metadata: " + ", ".join(sorted(unknown)))
        safe_metadata = {
            str(key): str(value or "")[:160]
            for key, value in metadata.items()
            if str(value or "").strip()
        }
        timestamp = self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        line = json.dumps(
            {
                "schema_version": 1,
                "timestamp": timestamp,
                "event": event_name,
                "metadata": safe_metadata,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        try:
            os.write(descriptor, line)
        finally:
            os.close(descriptor)
        _restrict_to_current_user(self.path)


def _restrict_to_current_user(path: Path) -> None:
    """Apply portable owner-only mode bits where the platform honors them."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
