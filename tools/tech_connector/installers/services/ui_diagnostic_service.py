"""UI responsiveness diagnostics for Tech Connector."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from models.constants import APP_ROOT


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
