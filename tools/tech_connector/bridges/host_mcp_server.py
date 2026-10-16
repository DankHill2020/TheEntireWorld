"""Launch a standard MCP server for any registered Tech Connector host bridge."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

_ROOT = next(candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tech_connector.services.host_mcp_facade_service import HostMcpFacade, MCP_HOSTS


def create_host_mcp_server(host: str, *, fastmcp_class: Any | None = None):
    if fastmcp_class is None:
        try:
            from fastmcp import FastMCP as fastmcp_class
        except ImportError as exc:
            raise RuntimeError(
                "FastMCP is required for host MCP servers. Install the packaged runtime requirements."
            ) from exc
    facade = HostMcpFacade(host)
    prefix = facade.host.replace("3dsmax", "max").replace("_", "")
    server = fastmcp_class(f"TechConnector-{facade.host}")

    def register(name: str, function):
        function.__name__ = f"{prefix}_{name}"
        return server.tool()(function)

    def status() -> str:
        """Return bridge reachability, active ports, policy flags, and operation count."""
        return json.dumps(facade.status(), indent=2, default=str)

    def sessions() -> str:
        """List live application sessions and the explicitly selected target session."""
        return json.dumps(facade.sessions(), indent=2, default=str)

    def select_session(port: int) -> str:
        """Pin later tool calls to one verified live application session."""
        return json.dumps(facade.select_session(port), indent=2, default=str)

    def operation_catalog() -> str:
        """List registered typed operations, schemas, descriptions, and mutability."""
        return json.dumps(facade.operation_catalog(), indent=2, default=str)

    def validate_operation(operation_key: str, params: dict | None = None) -> str:
        """Validate a typed operation and its parameters without executing it."""
        return json.dumps(facade.validate_operation(operation_key, params), indent=2, default=str)

    def run_operation(operation_key: str, params: dict | None = None, approved: bool = False, timeout: float = 60.0) -> str:
        """Run a registered operation. Mutations also require installation policy opt-in."""
        return json.dumps(facade.run_operation(operation_key, params, approved=approved, timeout=timeout), indent=2, default=str)

    def execute_python(code: str, approved: bool = False, timeout: float = 30.0) -> str:
        """Run raw host code only when raw execution and mutation policies explicitly allow it."""
        return json.dumps(facade.execute_python(code, approved=approved, timeout=timeout), indent=2, default=str)

    for name, function in (
        ("status", status), ("sessions", sessions), ("select_session", select_session),
        ("operation_catalog", operation_catalog), ("validate_operation", validate_operation),
        ("run_operation", run_operation), ("execute_python", execute_python),
    ):
        register(name, function)
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=MCP_HOSTS)
    args = parser.parse_args(argv)
    create_host_mcp_server(args.host).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
