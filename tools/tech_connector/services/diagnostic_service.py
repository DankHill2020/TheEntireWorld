"""User-inspectable backend and UI responsiveness diagnostics."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from tech_connector.models.constants import APP_ROOT


BACKEND_LOG_DIR = APP_ROOT / ".ai_studio" / "backend_logs"
BACKEND_LOG_PATH = BACKEND_LOG_DIR / "backend.jsonl"


def _clip(value: Any, limit: int = 6000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def log_backend_event(
    category: str,
    message: str,
    *,
    command: list[str] | tuple[str, ...] | str | None = None,
    cwd: str | Path | None = None,
    returncode: int | None = None,
    stdout: Any = None,
    stderr: Any = None,
    error: Any = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a JSONL diagnostic entry. Logging must never break workflows."""
    try:
        BACKEND_LOG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "category": category,
            "message": message,
        }
        if command is not None:
            payload["command"] = list(command) if isinstance(command, (list, tuple)) else str(command)
        if cwd is not None:
            payload["cwd"] = str(cwd)
        if returncode is not None:
            payload["returncode"] = returncode
        if stdout is not None:
            payload["stdout"] = _clip(stdout)
        if stderr is not None:
            payload["stderr"] = _clip(stderr)
        if error is not None:
            payload["error"] = _clip(error)
        if details:
            payload["details"] = details
        with BACKEND_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


def read_backend_log(limit: int = 300) -> str:
    if not BACKEND_LOG_PATH.exists():
        return "No backend log entries yet."
    try:
        lines = BACKEND_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return f"Could not read backend log: {exc}"
    selected = lines[-max(1, int(limit)):]
    rendered = []
    for raw in selected:
        try:
            item = json.loads(raw)
        except Exception:
            rendered.append(raw)
            continue
        rendered.append(_format_entry(item))
    return "\n\n".join(rendered) if rendered else "No backend log entries yet."


def _format_entry(item: dict[str, Any]) -> str:
    header = f"[{item.get('time', '')}] {item.get('category', 'backend')}: {item.get('message', '')}"
    parts = [header]
    if item.get("command") is not None:
        command = item["command"]
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        parts.append(f"  command: {command}")
    if item.get("cwd"):
        parts.append(f"  cwd: {item['cwd']}")
    if item.get("returncode") is not None:
        parts.append(f"  returncode: {item['returncode']}")
    if item.get("error"):
        parts.append(f"  error: {item['error']}")
    if item.get("stdout"):
        parts.append(f"  stdout:\n{item['stdout']}")
    if item.get("stderr"):
        parts.append(f"  stderr:\n{item['stderr']}")
    if item.get("details"):
        parts.append("  details: " + json.dumps(item["details"], ensure_ascii=True))
    return "\n".join(parts)


def clear_backend_log() -> None:
    try:
        BACKEND_LOG_DIR.mkdir(parents=True, exist_ok=True)
        BACKEND_LOG_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass


DIAGNOSTIC_DIR = APP_ROOT / ".ai_studio" / "diagnostics"
DIAGNOSTIC_PATH = DIAGNOSTIC_DIR / "ui_diagnostics.jsonl"


def log_ui_event(event: str, *, enabled: bool = True, **details: Any) -> None:
    """Append a UI diagnostic event. This must never affect normal app behavior."""
    if not enabled:
        return
    try:
        DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": str(event or "ui_event"),
            "details": details,
        }
        with DIAGNOSTIC_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
    except Exception:
        pass


@contextmanager
def timed_ui_event(event: str, *, enabled: bool = True, **details: Any):
    started = time.perf_counter()
    error = ""
    try:
        yield
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        payload = dict(details)
        payload["duration_ms"] = duration_ms
        if error:
            payload["error"] = error
        log_ui_event(event, enabled=enabled, **payload)


def read_ui_diagnostics(limit: int = 250) -> str:
    if not DIAGNOSTIC_PATH.exists():
        return "No UI diagnostic events yet."
    try:
        lines = DIAGNOSTIC_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return f"Could not read UI diagnostics: {exc}"
    selected = lines[-max(1, int(limit)):]
    rendered: list[str] = []
    for raw in selected:
        try:
            item = json.loads(raw)
        except Exception:
            rendered.append(raw)
            continue
        details = item.get("details") or {}
        detail_text = json.dumps(details, ensure_ascii=True)
        rendered.append(f"[{item.get('time', '')}] {item.get('event', '')}: {detail_text}")
    return "\n".join(rendered) if rendered else "No UI diagnostic events yet."


def clear_ui_diagnostics() -> None:
    try:
        DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
        DIAGNOSTIC_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass


def diagnostic_path() -> Path:
    return DIAGNOSTIC_PATH
