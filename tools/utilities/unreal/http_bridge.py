"""Small compatibility helper for runnable Unreal examples."""

from __future__ import annotations

import time
from typing import Any

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge


def send_unreal_http_command(
    function_path: str,
    *,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[bool, str, float]:
    """Call one Unreal Python function and return success, payload, and milliseconds."""

    started = time.perf_counter()
    ok, response = UnrealBridge().call(
        function_path,
        args=args or [],
        kwargs=kwargs or {},
        timeout=timeout,
    )
    return ok, response, (time.perf_counter() - started) * 1000.0
