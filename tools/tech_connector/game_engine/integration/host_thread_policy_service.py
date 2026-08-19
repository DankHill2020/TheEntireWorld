"""Canonical thread-affinity rules for code that touches a live DCC host."""

from __future__ import annotations

import re
from typing import Any


_HOST_ADAPTERS = {
    "maya": "maya.utils.executeInMainThreadWithResult",
    "blender": "the registered Blender bridge main-thread queue/timer",
    "unreal": "the registered Unreal editor-thread bridge",
    "houdini": "the Houdini UI event-loop callback bridge",
    "motionbuilder": "the MotionBuilder main-thread timer queue",
    "substance_painter": "the Substance Painter main-thread bridge queue",
}


def build_host_thread_policy(
    prompt: str,
    understanding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(understanding or {})
    host = str(data.get("host") or data.get("host_hint") or "").strip().lower()
    if not host:
        text = str(prompt or "")
        for candidate in _HOST_ADAPTERS:
            if re.search(rf"\b{re.escape(candidate)}\b", text, re.IGNORECASE):
                host = candidate
                break
    if not host:
        return {}
    adapter = _HOST_ADAPTERS.get(host, "the registered host main-thread adapter")
    return {
        "host": host,
        "host_api_thread": "main",
        "required_adapter": adapter,
        "rules": [
            "Run live DCC API reads and mutations on the host's required main/editor thread.",
            "Use background workers only for model calls, file IO, serialization, and host-independent computation.",
            f"Marshal host API work through {adapter} when the caller is off-thread or out-of-process.",
            "Send progress and completion back to Qt widgets through signals; never touch widgets from a worker thread.",
        ],
    }
