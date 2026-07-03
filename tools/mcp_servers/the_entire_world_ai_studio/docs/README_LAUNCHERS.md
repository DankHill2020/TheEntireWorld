# Launcher Files

## start_the_entire_world_ai_studio.bat

Main launcher. Double-click this.

Installs missing Python dependencies:
- PySide6
- fastmcp
- pywinpty

Then launches the UI with `pyw` so no command window stays open.

## start_the_entire_world_ai_studio_debug.bat

Debug launcher. Use this if the UI closes or errors.

## install_components.bat

Copies:
- Knowledge MCP v2
- AST index builder
- quiet Maya MCP server

Then updates:

```text
C:\depot\tools\mcp_unreal_maya_knowledge_config.json
```

## rebuild_ast_index.bat

Runs the AST index builder manually.

## open_project_config_folder.bat

Opens:

```text
%LOCALAPPDATA%\TA_AI_Studio_MCPHost
```

## maya_command_port_setup.py

Run this inside Maya if the Maya commandPort is not active.