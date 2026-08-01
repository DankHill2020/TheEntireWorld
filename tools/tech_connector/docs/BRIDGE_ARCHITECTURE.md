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

Adding a new 3D app should be progressive. A user should not need to implement
every bridge feature before Tech Connector can understand that the app exists.

Minimum viable 3D app:

1. App name / id.
2. Executable path.
3. One or more API docs, SDK references, local stubs, or internal notes.

With only those fields, Tech Connector can:

- launch or locate the app;
- index the app's API documentation;
- answer app-aware questions;
- draft bridge code, menu actions, and smoke tests;
- show the app as "docs-aware / launchable" rather than "fully connected."

Optional upgrades:

| Optional field | Unlocks |
| --- | --- |
| In-app bridge script or adapter module | live command execution, selection reads, status checks |
| Internal tool folders/modules | smart-menu capability indexing and workflow nodes |
| Scene snapshot method | outliner and federated viewport participation |
| Camera query/set methods | shared-camera viewport sync |
| Geometry extraction | true mesh display instead of bounds fallback |
| Menu contribution manifest | app-specific menu under Apps / Connected Applications |
| Icon and branding | polished app identity in menus and status cards |
| Health checks and smoke prompts | trusted/validated setup state |
| MCP server | richer model-planned tool use after direct calls are proven |

The helper module `services/dcc/three_d_app_provider_manifest.py` defines this
progressive manifest shape. Required fields stay small; optional fields upgrade
the provider from `minimum_viable` to `connected_app_ready`, `viewport_ready`, or
`smart_menu_ready`.

For a fully connected app, add or generate:

1. `bridges/{host}_bridge.py`.
2. An in-app adapter script or plugin.
3. Registry metadata in `plugins/plugin_registry.json` or an integration package.
4. Common direct UI verbs first.
5. App-specific smart-menu actions from the provider manifest.
6. MCP support after direct calls are proven.
7. Docs and tests that do not require the host app to be installed.

Keep host-specific logic inside the bridge or adapter. The UI should call common
verbs whenever possible.
