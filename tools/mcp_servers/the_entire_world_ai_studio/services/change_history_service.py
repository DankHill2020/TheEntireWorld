"""Persistent change-session history for Tech Connector code edits.

This stores enough information to undo the last accepted AI edit even after the
UI has closed and reopened. It is intentionally local-only and simple JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from models.constants import APP_ROOT
except Exception:  # fallback for older builds
    APP_ROOT = Path.cwd()


HISTORY_DIR = Path(APP_ROOT) / ".ai_studio" / "change_history"
ACTIVE_SESSION_PATH = HISTORY_DIR / "latest_change_session.json"


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
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR


def create_change_session(pending_changes: dict[str, dict[str, Any]], summary: str = "AI code changes") -> ChangeSession:
    """Capture before/after text for proposed changes before they are written."""
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
    ensure_history_dir()
    path = HISTORY_DIR / f"{session.session_id}.json"
    payload = asdict(session)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    ACTIVE_SESSION_PATH.write_text(json.dumps({"path": str(path)}, indent=2), encoding="utf-8")
    return path


def load_change_session(path: str | Path | None = None) -> ChangeSession | None:
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


def undo_change_session(session: ChangeSession | None = None) -> tuple[bool, str, list[str]]:
    """Undo a saved change session by restoring modified files and removing created files."""
    session = session or load_change_session()
    if not session:
        return False, "No saved change session found.", []

    changed: list[str] = []
    errors: list[str] = []
    for item in reversed(session.files):
        p = Path(item.path)
        try:
            if item.action == "create":
                if p.exists():
                    p.unlink()
                    changed.append(str(p))
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(item.before, encoding="utf-8")
                changed.append(str(p))
        except Exception as exc:
            errors.append(f"{p}: {exc}")

    if errors:
        return False, "Undo completed with errors:\n" + "\n".join(errors), changed
    return True, f"Undid change session {session.session_id}.", changed


def list_change_sessions(limit: int = 25) -> list[Path]:
    ensure_history_dir()
    return sorted(HISTORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
