# Bridge Architecture

The Studio treats external applications as host bridges. A bridge can be direct,
MCP-based, or both.

```text
Direct path:
UI -> bridge class -> localhost app adapter -> host API

Reasoning path:
UI -> MCPHost / LLM -> MCP server -> bridge/app tools -> host API
```

Use the direct path for deterministic actions such as selection, current file,
scene objects, logs, scripted edits, project-aware debug, and controlled
prototype operations. Use the MCP path when the AI needs to plan, search docs,
choose tools, or explain results.

The current direct UI covers Maya, Unreal, Blender, Substance Painter, Unity,
and MotionBuilder. The plugin registry currently tracks Maya, Unreal, Blender,
Substance Painter, and MotionBuilder; Unity exists as a direct bridge/menu
integration and should be added to the registry before it is treated as a full
plugin target.

## Bridge Contract

New direct bridges should expose the common shape from:

```text
bridges/host_bridge.py
```

Minimum methods:

```text
find_port()
execute(code)
get_selection_code()
get_current_file_code()
get_scene_objects_code()
```

Optional methods:

```text
call_function(function_path, args, kwargs)
parse_input(text)
get_logs()
save()
run_tool()
```

Smart-operation hosts should also expose package endpoints documented in:

```text
docs/DCC_SMART_OPERATIONS.md
```

Full adapters should subclass `DCCAdapter` and use its shared smart-operation
helpers for normal understanding, prototype, and debug responses:

```text
build_context_summary()
build_understanding_report(question)
build_prototype_plan(goal, template, context)
build_debug_report(goal, context)
```

Host-specific adapters can override these methods for deeper scans, but they
should keep the same response shape so the UI can treat every DCC consistently.

## Plugin Registry

Register bridge metadata in:

```text
plugins/plugin_registry.json
```

Example:

```json
{
  "enabled": true,
  "display_name": "Blender",
  "server": "blender_command_port_setup.py",
  "domain": "blender",
  "tool_domain": "blender_tools",
  "protocol": "socket-json",
  "default_port": 7021,
  "supports_direct_execute": true,
  "supports_mcp": false
}
```

The registry is intentionally simple so downstream users can add local apps
without changing every subsystem.

## App Adapter Pattern

Most desktop apps need a small script or plugin running inside the host:

```text
Blender: run a bpy socket server
Substance Painter: install a Python plugin with a socket server
Unity: install an Editor plugin with HTTP or WebSocket endpoints
Houdini: run a hou Python socket server
Word/Excel: use a Windows COM or Office add-in adapter
```

Adapters should listen on `127.0.0.1` by default and write their active port to
`%LOCALAPPDATA%\TA_AI_Studio_MCPHost\{host}_port.txt` when possible.

## Adding A New Bridge

1. Add `bridges/{host}_bridge.py`.
2. Add or reuse an in-app adapter script.
3. Add the host to `plugins/plugin_registry.json`.
4. Add direct UI actions only for the common verbs first.
5. Add MCP support after direct calls are proven.
6. Add docs and tests that do not require the host app to be installed.

Keep host-specific logic inside the bridge or adapter. The UI should call common
verbs whenever possible.
