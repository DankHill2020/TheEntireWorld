"""Capability bridge exposing Tech Connector DCC operation surfaces."""

from __future__ import annotations

import json
from typing import Any

from reasoning_runtime import CapabilityBridge, CapabilityResult, ToolSpec


class DccCapabilityBridge(CapabilityBridge):
    """Expose existing Tech Connector command routing as structured tools."""

    name = "tech_connector_dcc_bridge"

    def __init__(self, *, command_router: Any = None) -> None:
        self.command_router = command_router

    def get_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="tech_connector.dcc.call_function",
                description="Execute a registered DCC package function through the appropriate host bridge.",
                input_schema={
                    "type": "object",
                    "required": ["entry_point"],
                    "properties": {
                        "host": {"type": "string"},
                        "entry_point": {"type": "string"},
                        "args": {"type": "array"},
                        "kwargs": {"type": "object"},
                    },
                },
                output_schema={"type": "object"},
                mutability="dcc_mutation",
                risk="medium",
                permissions=("dcc_bridge_access",),
                execution_target="tech_connector.router.command_router",
            ),
            ToolSpec(
                name="tech_connector.project.search",
                description="Search indexed project files, symbols, and tool catalogs.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                output_schema={"type": "object"},
                mutability="read_only",
                risk="low",
                execution_target="tech_connector.services.project_search_service",
            ),
        ]

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> CapabilityResult:
        if tool_name != "tech_connector.dcc.call_function":
            return CapabilityResult(ok=False, error=f"Unsupported Tech Connector tool: {tool_name}")
        if self.command_router is None:
            return CapabilityResult(ok=False, error="No command router is attached.")
        entry_point = str(arguments.get("entry_point") or "")
        payload = {
            "function": entry_point,
            "args": list(arguments.get("args") or []),
            "kwargs": dict(arguments.get("kwargs") or {}),
        }
        try:
            label, ok, output = self.command_router.execute_tool_function_from_text(json.dumps(payload))
        except Exception as exc:
            return CapabilityResult(ok=False, error=str(exc))
        return CapabilityResult(ok=bool(ok), output={"label": label, "output": output})
