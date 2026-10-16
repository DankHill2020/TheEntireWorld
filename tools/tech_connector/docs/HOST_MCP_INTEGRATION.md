# Host MCP integration

Tech Connector uses a hybrid host-control architecture:

- The planner and workflow engine decide what should happen.
- Typed operations from `dcc_operation_service.py` define what may happen.
- Existing localhost bridges perform the deterministic host call.
- MCP sidecars expose the same operations to external MCP clients.

MCP is an additional protocol boundary; it does not replace the direct bridge or create a second implementation of Maya, Blender, Unity, or another host API.

## Managed hosts

The shared sidecar supports Maya, Blender, Houdini, Unity, MotionBuilder, 3ds Max, Substance Painter, Photoshop, and GIMP. Unreal keeps its specialized typed MCP server. Every host still uses its existing discovered session ports, including multiple simultaneous sessions.

The generated MCP configuration launches shared sidecars with:

```text
python tech_connector/bridges/host_mcp_server.py --host <host-id>
```

Each server exposes namespaced status, session selection, operation catalog, validation, execution, and raw-execution tools. For example, Maya tools are named `maya_status`, `maya_sessions`, and `maya_run_operation`.

## Safety policy

Read-only typed operations are available by default. A mutating operation requires both:

1. `approved=true` on that individual MCP call.
2. `TECH_CONNECTOR_MCP_ALLOW_MUTATION=1` in the server environment.

Arbitrary code and registered `script.run` or `api.call` operations additionally require:

```text
TECH_CONNECTOR_MCP_ALLOW_RAW_EXECUTION=1
```

This separates an approval for one typed edit from permission to execute arbitrary host code. Installations should leave both environment switches unset unless the MCP client and project are trusted.

## Runtime and configuration

`fastmcp>=3,<4` is part of the packaged runtime requirements. `settings_service.update_mcp_config()` replaces managed legacy entries with repository-owned sidecars while preserving unrelated user-managed MCP servers. It probes the active and installed Tech Connector Python runtimes and pins a FastMCP-capable interpreter instead of relying on an ambiguous `python` command. Set `TECH_CONNECTOR_MCP_PYTHON` to an explicit compatible executable when an installation needs to override that selection. The checked-in reference configuration is `knowledge/mcp_unreal_maya_knowledge_config.json`.

Use the session tools before a mutation when more than one copy of a host is open. A selected live port pins subsequent calls to that exact application session.
