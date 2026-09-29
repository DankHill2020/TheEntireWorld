"""Stable project UUID manifests that do not expose local filesystem paths."""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .domain import ProjectIdentity, parse_timestamp


PROJECT_MANIFEST_NAME = ".tech_connector_project"
PROJECT_SCHEMA = "tech_connector.project.v2"


def _manifest_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / PROJECT_MANIFEST_NAME


def load_project_identity(project_root: str | Path) -> ProjectIdentity | None:
    path = _manifest_path(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Project identity manifest is unreadable: {path}") from exc
    if payload.get("schema") != PROJECT_SCHEMA:
        raise ValueError("Project identity manifest schema is not recognized")
    project_id = str(payload.get("project_id") or "")
    project_uuid = project_id[4:] if project_id.startswith("prj_") else ""
    try:
        parsed_project_uuid = uuid.UUID(project_uuid)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Project identity manifest contains an invalid project_id") from exc
    if parsed_project_uuid.hex != project_uuid.casefold():
        raise ValueError("Project identity manifest contains an invalid project_id")
    return ProjectIdentity(
        project_id=project_id,
        created_at=parse_timestamp(payload.get("created_at"), field_name="created_at"),
    )


def ensure_project_identity(project_root: str | Path) -> ProjectIdentity:
    """Return or atomically create a privacy-safe local project identity."""
    root = Path(project_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        existing = load_project_identity(root)
    except ValueError:
        # A second process may observe the exclusive-create file between its
        # creation and final fsync. Give that tiny window time to close before
        # treating the manifest as genuinely corrupt.
        existing = _load_after_concurrent_create(root)
    if existing is not None:
        return existing
    identity = ProjectIdentity(
        project_id="prj_" + uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc).replace(microsecond=0),
    )
    payload = {
        "schema": identity.schema,
        "project_id": identity.project_id,
        "created_at": identity.created_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    path = _manifest_path(root)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
    except FileExistsError:
        # Multiple host applications can open the same project together. The
        # first complete identity wins; every other process reloads that ID.
        return _load_after_concurrent_create(root)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return identity


def _load_after_concurrent_create(project_root: Path) -> ProjectIdentity:
    last_error: ValueError | None = None
    for _attempt in range(20):
        try:
            identity = load_project_identity(project_root)
            if identity is not None:
                return identity
        except ValueError as exc:
            last_error = exc
        time.sleep(0.01)
    if last_error is not None:
        raise last_error
    raise ValueError("Project identity was created but could not be loaded")
