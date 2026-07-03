# The Entire World AI Studio Plugin Architecture

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

## Built-in plugin targets

```text
Maya
Unreal
MotionBuilder
```

## Domain naming

Use these domains in Knowledge MCP searches:

```text
maya
maya_tools
unreal
unreal_tools
motionbuilder
mobu_tools
```

## MotionBuilder

Files:

```text
motionbuilder_mcp_server.py
motionbuilder_command_port_setup.py
```

### Setup

1. Run `motionbuilder_command_port_setup.py` inside MotionBuilder.
2. Add the MotionBuilder MCP entry to your config.
3. Restart MCPHost.

### MCP config entry

```json
"motionbuilder": {
  "type": "stdio",
  "command": "py",
  "args": [
    "-3.11",
    "C:\\Desktop\\UnrealGenAISupport\\Content\\Python\\motionbuilder_mcp_server.py"
  ]
}
```

## Suggested UI features next

- Host status cards
- Project explorer
- AST symbol browser
- Go to definition
- Find references
- Call hierarchy
- Diff preview
- Apply/Reject edits
- Run in host