"""Lightweight routing metrics for PromptRoute/PromptDispatch quality."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _metrics_path(project_root: str | None = None) -> Path:
    root = Path(project_root or ".").resolve()
    return root / ".ai_studio" / "routing_metrics.jsonl"


def record_route_metric(metric: dict[str, Any], *, project_root: str | None = None) -> None:
    """Append one route metric event.

    This deliberately avoids prompt text and file contents. It records behavior
    signals only: route, handler, confidence, result type, timing, and LLM use.
    """
    path = _metrics_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(metric or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
