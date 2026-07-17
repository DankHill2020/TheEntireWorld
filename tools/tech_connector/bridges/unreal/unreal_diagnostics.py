"""Bounded, read-only Unreal editor/runtime diagnostics."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re


def _tail_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - max(1024, int(max_bytes))))
        data = handle.read()
    return data.decode("utf-8", errors="replace")


def _error_summary(lines, *, contains="", limit=100):
    needle = str(contains or "").strip().lower()
    grouped = OrderedDict()
    for raw in lines:
        line = str(raw or "").strip()
        lower = line.lower()
        if not line or ("error" not in lower and "warning" not in lower):
            continue
        if needle and needle not in lower:
            continue
        normalized = re.sub(r"^\[[^]]+\]\[[^]]+\]", "", line).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if normalized not in grouped:
            grouped[normalized] = {"message": normalized, "count": 0}
        grouped[normalized]["count"] += 1
    rows = list(grouped.values())
    return rows[-max(1, int(limit or 100)) :]


def read_recent_log_errors(contains="", limit=100, max_bytes=2_000_000):
    """Return recent unique Unreal log errors/warnings with repetition counts."""

    import unreal

    log_dir = Path(str(unreal.Paths.project_log_dir()))
    logs = sorted(
        (path for path in log_dir.glob("*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not logs:
        return {
            "ok": False,
            "operation": "diagnostics.read_log_errors",
            "log_directory": str(log_dir),
            "entries": [],
            "errors": ["No Unreal project log was found."],
            "verified": False,
        }
    log_path = logs[0]
    text = _tail_text(log_path, max_bytes=max_bytes)
    entries = _error_summary(text.splitlines(), contains=contains, limit=limit)
    return {
        "ok": True,
        "operation": "diagnostics.read_log_errors",
        "log_path": str(log_path),
        "bytes_inspected": min(log_path.stat().st_size, max(1024, int(max_bytes))),
        "filter": str(contains or ""),
        "entry_count": len(entries),
        "occurrence_count": sum(int(row["count"]) for row in entries),
        "entries": entries,
        "errors": [],
        "mutated_project": False,
        "verified": True,
    }

