# Launcher Files

## Start_The_Entire_World_AI_Studio.bat

Main launcher. Double-click this.

The source launcher requires the Windows `py` launcher and Python 3.14. It performs a
first-run dependency check, then starts the UI with:

```text
pyw -3.14 -m tech_connector.app.main_window
```

Installs missing Python dependencies:
- PySide6
- fastmcp
- pywinpty

It also installs/updates local MCP components by copying available bridge
servers into:

```text
C:\Desktop\UnrealGenAISupport\Content\Python
```

Currently copied when present:

- Knowledge MCP v2
- quiet Maya MCP server
- MotionBuilder MCP server
- MotionBuilder command-port setup

Then updates:

```text
C:\depot\tools\tech_connector\knowledge\mcp_unreal_maya_knowledge_config.json
```

The generated config registers:

```text
knowledge
maya
motionbuilder
ludus-mcp
```

## Host Setup Scripts

Host setup scripts now live under `installers/`:

```text
installers\maya_command_port_setup.py
installers\blender_command_port_setup.py
installers\Install_Blender_AI_Studio_Bridge.bat
installers\Install_Substance_Painter_AI_Studio_Bridge.bat
installers\motionbuilder_command_port_setup.py
```

Run `installers\maya_command_port_setup.py` inside Maya if the Maya
commandPort is not active.

The old root-level helper batch files `start_the_entire_world_ai_studio_debug.bat`,
`install_components.bat`, `rebuild_ast_index.bat`, and
`open_project_config_folder.bat` are not present in the current checkout.
