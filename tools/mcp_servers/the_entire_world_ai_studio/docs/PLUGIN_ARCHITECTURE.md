# The Entire World Tech Connector Plugin Architecture

The long-term goal is a host-aware technical art IDE.

Each host plugin should expose a common shape:

```text
connect()
status()
execute_python(code)
get_selection()
get_current_file()
get_scene_objects()
get_logs()
list_tools()
run_tool()
index_docs()
```

See `BRIDGE_ARCHITECTURE.md` for the public bridge contract and contributor
guidelines.

## Built-in plugin targets

```text
Maya
Unreal
Blender
Substance Painter
MotionBuilder
```

Unity is implemented as a direct bridge and appears under
`Tools > Connected Applications > Unity`, but it is not yet present in
`plugins/plugin_registry.json`. Treat Unity as an active direct integration and
a plugin-registry parity item.

## Domain naming

Use these domains in Knowledge MCP searches:

```text
maya
maya_tools
unreal
unreal_tools
blender
blender_tools
substance_painter
substance_painter_tools
motionbuilder
mobu_tools
```

## Blender

Files:

```text
Install_Blender_AI_Studio_Bridge.bat
install_blender_bridge.py
blender_ai_studio_bridge_addon.py
blender_command_port_setup.py
bridges/blender_bridge.py
bridges/host_bridge.py
```

### Setup

1. Open Blender once so it creates the user scripts folder.
2. Start Tech Connector. It will install/update the startup bridge if Blender is found.
3. Restart Blender if Tech Connector reports that the bridge was installed or updated.
4. In the Studio, use Tools > Connected Applications > Blender.

Manual setup is also available from:

```text
Tools > Connected Applications > Blender > Install Startup Bridge
Tools > Connected Applications > Blender > Copy Script Editor Setup Snippet
Install_Blender_AI_Studio_Bridge.bat
```

For a one-session manual test, run `blender_command_port_setup.py` in Blender's
Text Editor instead of installing the add-on.

The direct bridge listens on `127.0.0.1:7021` by default and writes the active
port to:

```text
%LOCALAPPDATA%\TA_AI_Studio_MCPHost\blender_port.txt
C:\depot\tools\blender_port.txt
```

## Substance Painter

Files:

```text
Install_Substance_Painter_AI_Studio_Bridge.bat
install_substance_painter_bridge.py
substance_painter_ai_studio_bridge.py
bridges/substance_painter_bridge.py
bridges/host_bridge.py
```

### Setup

1. Start Tech Connector. It installs/updates the Substance Painter bridge plugin in the user documents plugin folder.
2. Restart Substance Painter.
3. If Painter asks, enable the plugin from its Python/plugins menu.
4. In the Studio, use Tools > Connected Applications > Substance Painter.

Manual setup is also available from:

```text
Tools > Connected Applications > Substance Painter > Install Startup Bridge
Tools > Connected Applications > Substance Painter > Copy Script Editor Setup Snippet
Install_Substance_Painter_AI_Studio_Bridge.bat
```

The direct bridge listens on `127.0.0.1:7031` by default and writes the active
port to:

```text
%LOCALAPPDATA%\TA_AI_Studio_MCPHost\substance_painter_port.txt
C:\depot\tools\substance_painter_port.txt
```

## MotionBuilder

Files:

```text
bridges/motionbuilder/motionbuilder_bridge.py
bridges/motionbuilder/motionbuilder_adapter.py
motionbuilder_tools/
```

### Setup

1. Start Tech Connector and install/update the MotionBuilder startup bridge.
2. Restart MotionBuilder so the startup script opens the local socket bridge.
3. Use Tools > Connected Applications > MotionBuilder for direct selection,
   file, scene, take, character, context-summary, and call/execute actions.

### Direct bridge

```text
127.0.0.1:7011
```

The direct function router accepts both `motionbuilder_tools.*` and
`mobu_tools.*` package functions, then executes them inside MotionBuilder
through the socket bridge.

## Implemented UI Features

The application already includes the following host-aware IDE surfaces:

- host status cards
- project explorer
- Search / Symbols
- editor file navigation
- workflow and pipeline builders
- diff approval and apply paths
- run-in-host direct bridge actions

## Suggested Architecture Work Next

- add Unity to `plugins/plugin_registry.json`
- add registry entries for newer direct bridges such as Houdini or Photoshop
  only after they have matching UI/setup documentation
- continue migrating mutation-capable menu actions behind typed command or
  dispatch adapters
- add MCP parity only after direct host calls are proven stable
