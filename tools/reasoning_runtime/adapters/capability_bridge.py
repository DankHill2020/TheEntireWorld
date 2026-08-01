"""Capability and tool execution contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """Structured capability metadata exposed by a domain package."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    mutability: str = "read_only"
    risk: str = "low"
    permissions: tuple[str, ...] = ()
    execution_target: str = ""
    examples: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityResult:
    ok: bool
    output: Any = None
    error: str = ""
    evidence: tuple[Any, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityBridge(ABC):
    """Defines tools the runtime can discover and execute."""

    name: str = "capability_bridge"

    @abstractmethod
    def get_tools(self) -> list[ToolSpec]:
        """Return structured tool metadata."""

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> CapabilityResult:
        return CapabilityResult(ok=False, error=f"Tool execution is not implemented: {tool_name}")

    def get_rollback_strategies(self) -> list[Any]:
        return []
