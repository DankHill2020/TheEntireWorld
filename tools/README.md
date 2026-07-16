# AI Tools Depot Starter

Copy the contents of this folder into:

`C:\depot\tools`

This adds:
- local Maya/Unreal quick references
- AI workflow rules
- pending-review folder for generated tools
- Knowledge MCP server with:
  - `knowledge_search`
  - `read_tool_file`
  - `write_pending_tool`
  - `list_depot_tree`
  - `agent_workflow`

Install dependency:

```powershell
py -3.11 -m pip install fastmcp
```

Use config:

`C:\depot\tools\mcp_unreal_maya_knowledge_config.json`

Start:

`C:\depot\tools\start_mcp_unreal_maya_knowledge.bat`
