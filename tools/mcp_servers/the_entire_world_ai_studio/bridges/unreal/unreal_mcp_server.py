"""MCP tools for Unreal Engine via the Tech Connector HTTP bridge.

This server intentionally sits beside the direct Unreal bridge instead of
replacing it. Direct calls stay useful for deterministic UI buttons; MCP tools
give the LLM a discoverable Unreal surface when it needs to inspect, plan, or
compose editor actions.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastmcp import FastMCP

from bridges.unreal.unreal_bridge import UnrealBridge
from bridges.unreal.unreal_scanner import UnrealScanner
from services.unreal.unreal_operation_service import (
    operation_catalog,
    unreal_operation_payload,
    unreal_project_scan_payloads,
)
from services.unreal.unreal_cpp_wrapper_service import create_unreal_cpp_wrapper_plan

mcp = FastMCP("UnrealMCP")
_bridge = UnrealBridge()


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def unreal_status() -> str:
    """Return Unreal HTTP bridge connection status and detected port."""
    health = _bridge.health_check()
    health["message"] = "Unreal HTTP bridge is reachable." if health.get("connected") else "Unreal HTTP bridge is not reachable."
    return _json(health)


@mcp.tool()
def unreal_call(function: str, args: list | None = None, kwargs: dict | None = None, timeout: float = 30) -> str:
    """Call a specific Unreal Python bridge function path with JSON arguments."""
    return _json(_bridge.safe_call(function, args=args or [], kwargs=kwargs or {}, timeout=timeout, label="mcp"))


@mcp.tool()
def unreal_execute_python(code: str, timeout: float = 30) -> str:
    """Execute Python through the Unreal HTTP bridge when a raw script is explicitly appropriate."""
    return _json(_bridge.execute_python(code, timeout=timeout))


@mcp.tool()
def unreal_operation_catalog() -> str:
    """List Tech Connector's typed Unreal operations and their required parameters."""
    return _json(operation_catalog())


@mcp.tool()
def unreal_run_operation(operation_key: str, params: dict | None = None, timeout: float = 60) -> str:
    """Run a typed Tech Connector Unreal operation, such as project.snapshot or blueprint.scan."""
    payload = unreal_operation_payload(operation_key, params or {})
    ok, result = _bridge.call(
        payload["function"],
        args=payload["args"],
        kwargs=payload["kwargs"],
        timeout=timeout,
    )
    return _json({"ok": ok, "operation": payload, "result": result})


@mcp.tool()
def unreal_project_scan(directory: str = "/Game/", timeout_per_call: float = 30) -> str:
    """Inventory core Unreal asset classes under a Content Browser directory."""
    return _json(UnrealScanner().scan_all(mode="standard"))


@mcp.tool()
def unreal_project_snapshot(directory: str = "/Game/") -> str:
    """Gather loaded-level state plus core asset inventory for expert Unreal context."""
    return _json(UnrealScanner().scan_all(mode="standard"))


@mcp.tool()
def unreal_inspect_asset(asset_path: str, include_blueprint_graphs: bool = True) -> str:
    """Inspect an Unreal asset or scan Blueprint structure when the asset appears to be a Blueprint."""
    operation = "blueprint.scan" if "bp_" in asset_path.lower() or "blueprint" in asset_path.lower() else "assets.inspect"
    params = {"asset_path": asset_path}
    if operation == "blueprint.scan":
        params.update({"include_graphs": include_blueprint_graphs, "include_defaults": True})
    return unreal_run_operation(operation, params)


@mcp.tool()
def unreal_create_cpp_python_wrapper(project_root: str, request_text: str, apply: bool = False) -> str:
    """Preview or create an AIStudioBridge reflected C++ wrapper callable from Unreal Python."""
    plan = create_unreal_cpp_wrapper_plan(project_root, request_text, apply=apply)
    return _json(plan.to_dict())


if __name__ == "__main__":
    mcp.run()
