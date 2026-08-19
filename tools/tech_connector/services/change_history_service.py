"""Persistent change-session history for Tech Connector code edits.

This stores enough information to undo the last accepted AI edit even after the
UI has closed and reopened. It is intentionally local-only and simple JSON.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from tech_connector.models.constants import APP_ROOT
except Exception:  # fallback for older builds
    APP_ROOT = Path.cwd()


HISTORY_DIR = Path(APP_ROOT) / ".ai_studio" / "change_history"
ACTIVE_SESSION_PATH = HISTORY_DIR / "latest_change_session.json"


def _write_text_atomically(path: Path, content: str) -> None:
    """Write a history or restored source file using atomic replacement.

    :param path: Destination path.
    :param content: Complete text content.
    :return: None.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tech-connector-",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline=None) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


@dataclass
class FileSnapshot:
    path: str
    action: str
    before: str
    after: str


@dataclass
class ChangeSession:
    session_id: str
    created_at: str
    summary: str
    files: list[FileSnapshot]


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def ensure_history_dir() -> Path:
    """Ensure the local change-history directory exists.

    :return: Change-history directory.
    """

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR


def create_change_session(pending_changes: dict[str, dict[str, Any]], summary: str = "AI code changes") -> ChangeSession:
    """Capture proposed changes before they are written.

    :param pending_changes: Changes keyed by destination path.
    :param summary: Human-readable session summary.
    :return: In-memory change session.
    """

    files: list[FileSnapshot] = []
    for raw_path, data in pending_changes.items():
        path = str(Path(raw_path).resolve())
        action = str(data.get("action") or "modify")
        after = str(data.get("current") or data.get("new_content") or "")
        before = str(data.get("original") or data.get("original_content") or "")
        if action == "modify" and not before:
            try:
                before = Path(path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                before = ""
        files.append(FileSnapshot(path=path, action=action, before=before, after=after))
    return ChangeSession(
        session_id=_now_id(),
        created_at=datetime.now().isoformat(timespec="seconds"),
        summary=summary,
        files=files,
    )


def save_change_session(session: ChangeSession) -> Path:
    """Persist a change session and make it the active undo target.

    :param session: Change session to save.
    :return: Saved session path.
    """

    ensure_history_dir()
    path = HISTORY_DIR / f"{session.session_id}.json"
    payload = asdict(session)
    _write_text_atomically(path, json.dumps(payload, indent=2))
    _write_text_atomically(
        ACTIVE_SESSION_PATH,
        json.dumps({"path": str(path)}, indent=2),
    )
    return path


def load_change_session(path: str | Path | None = None) -> ChangeSession | None:
    """Load an explicit or active change session.

    :param path: Optional saved session path.
    :return: Loaded session or None.
    """

    try:
        if path is None:
            if not ACTIVE_SESSION_PATH.exists():
                return None
            pointer = json.loads(ACTIVE_SESSION_PATH.read_text(encoding="utf-8"))
            path = pointer.get("path")
        p = Path(path)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return ChangeSession(
            session_id=data.get("session_id") or p.stem,
            created_at=data.get("created_at") or "",
            summary=data.get("summary") or "AI code changes",
            files=[FileSnapshot(**item) for item in data.get("files", [])],
        )
    except Exception:
        return None


def deactivate_change_session(session: ChangeSession) -> None:
    """Remove a rolled-back session from the active undo pointer.

    :param session: Session that is no longer applied.
    :return: None.
    """

    try:
        if not ACTIVE_SESSION_PATH.exists():
            return
        pointer = json.loads(ACTIVE_SESSION_PATH.read_text(encoding="utf-8"))
        active_path = Path(str(pointer.get("path") or ""))
        if active_path.stem != session.session_id:
            return
        candidates = [
            path for path in list_change_sessions()
            if path.stem != session.session_id
        ]
        if candidates:
            _write_text_atomically(
                ACTIVE_SESSION_PATH,
                json.dumps({"path": str(candidates[0])}, indent=2),
            )
        else:
            ACTIVE_SESSION_PATH.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return


def undo_change_session(
    session: ChangeSession | None = None,
    *,
    force: bool = False,
) -> tuple[bool, str, list[str]]:
    """Undo a change session without overwriting newer user changes.

    :param session: Change session to undo, or the latest saved session.
    :param force: Whether to overwrite content changed after the session.
    :return: Success flag, message, and changed paths.
    """
    session = session or load_change_session()
    if not session:
        return False, "No saved change session found.", []

    ordered_files = list(reversed(session.files))
    conflicts: list[str] = []
    if not force:
        for item in ordered_files:
            path = Path(item.path)
            try:
                if item.action == "create":
                    if (
                        path.exists()
                        and path.read_text(encoding="utf-8", errors="replace")
                        != item.after
                    ):
                        conflicts.append(
                            f"{path}: changed after the AI edit; refusing to remove it."
                        )
                elif not path.exists():
                    conflicts.append(
                        f"{path}: removed after the AI edit; refusing to recreate it."
                    )
                elif (
                    path.read_text(encoding="utf-8", errors="replace")
                    != item.after
                ):
                    conflicts.append(
                        f"{path}: changed after the AI edit; refusing to overwrite it."
                    )
            except Exception as exc:
                conflicts.append(f"{path}: could not verify current content: {exc}")
    if conflicts:
        return False, "Undo refused before changing files:\n" + "\n".join(conflicts), []

    changed: list[str] = []
    rollback_snapshots: list[tuple[Path, bool, str]] = []
    try:
        for item in ordered_files:
            path = Path(item.path)
            existed = path.exists()
            current = (
                path.read_text(encoding="utf-8", errors="replace")
                if existed
                else ""
            )
            if not force:
                expected = item.after
                if item.action == "create" and existed and current != expected:
                    raise RuntimeError(
                        f"{path}: changed while undo was starting; refusing to remove it."
                    )
                if item.action != "create" and (
                    not existed or current != expected
                ):
                    raise RuntimeError(
                        f"{path}: changed while undo was starting; refusing to overwrite it."
                    )
            if item.action == "create":
                if not existed:
                    continue
                rollback_snapshots.append((path, True, current))
                path.unlink()
            else:
                rollback_snapshots.append((path, existed, current))
                _write_text_atomically(path, item.before)
            changed.append(str(path))
    except Exception as exc:
        rollback_errors: list[str] = []
        for path, existed, content in reversed(rollback_snapshots):
            try:
                if existed:
                    _write_text_atomically(path, content)
                else:
                    path.unlink(missing_ok=True)
            except Exception as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            return (
                False,
                "Undo failed and rollback was incomplete:\n"
                + str(exc)
                + "\n"
                + "\n".join(rollback_errors),
                changed,
            )
        return False, f"Undo failed and was rolled back:\n{exc}", []

    return True, f"Undid change session {session.session_id}.", changed


def list_change_sessions(limit: int = 25) -> list[Path]:
    """List saved sessions without including the active pointer file.

    :param limit: Maximum number of sessions.
    :return: Session paths ordered newest first.
    """

    ensure_history_dir()
    sessions = [
        path for path in HISTORY_DIR.glob("*.json")
        if path.resolve() != ACTIVE_SESSION_PATH.resolve()
    ]
    return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
