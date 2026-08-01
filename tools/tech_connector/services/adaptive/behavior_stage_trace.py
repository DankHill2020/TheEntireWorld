from __future__ import annotations

"""Persistent event trace for behavior synthesis and critic convergence."""

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any

from tech_connector.models.constants import temp_output_path


class BehaviorStageTrace:
    def __init__(self, prompt: str, path: str | Path | None = None):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        digest = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:10]
        self.path = Path(path) if path else temp_output_path(f"behavior_{stamp}_{digest}.jsonl", subdir="traces")
        self._lock = threading.Lock()
        self._last_stream_size = 0
        self.emit("trace_started", prompt=prompt, prompt_sha256=digest)

    def emit(self, event: str, **payload: Any) -> None:
        row = {"time": time.time(), "event": event, **payload}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, default=str, ensure_ascii=True) + "\n")

    def stream_callback(self, _chunk: str, accumulated: str) -> None:
        size = len(accumulated)
        if size - self._last_stream_size < 256:
            return
        self._last_stream_size = size
        self.emit(
            "model_stream_progress",
            characters=size,
            tail=accumulated[-600:],
        )

    def begin_stream(self) -> None:
        self._last_stream_size = 0

    def __str__(self) -> str:
        return str(self.path)
