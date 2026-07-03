# Knowledge Index v2 AST

This upgrades the knowledge index from simple text chunks/basic symbols into an IDE-like AST index.

## New capabilities

- functions/classes/methods with:
  - name
  - qualname
  - signature
  - docstring
  - start/end lines
  - exact source code
  - decorators
  - imports
  - calls
  - Maya `cmds.*` usage
  - Unreal API references
  - string literals
- caller search
- exact symbol source lookup
- Maya command usage lookup

## Files

Copy these into:

```text
C:\depot\tools\mcp_servers\knowledge_mcp
```

Files:

```text
build_knowledge_index_v2.py
knowledge_mcp_server_v2.py
start_build_knowledge_index_v2.bat
```

## Build

Run:

```text
C:\depot\tools\mcp_servers\knowledge_mcp\start_build_knowledge_index_v2.bat
```

This creates:

```text
C:\depot\tools\knowledge\index\knowledge_index_v2.sqlite
```

## Update MCP config

Point your `knowledge` MCP server to:

```text
C:\depot\tools\mcp_servers\knowledge_mcp\knowledge_mcp_server_v2.py
```

Example:

```json
"knowledge": {
  "type": "stdio",
  "command": "py",
  "args": [
    "-3.11",
    "C:\\depot\\tools\\mcp_servers\\knowledge_mcp\\knowledge_mcp_server_v2.py"
  ]
}
```

## Test prompts

```text
Call knowledge__index_stats and show the raw response.
```

```text
Call knowledge__symbol_search with query "brow eyebrow facial rig" domain "maya_tools" max_results 20 include_source false.
```

```text
Call knowledge__read_symbol_source with name "create_brow_main_setup" domain "maya_tools" max_results 5.
```

```text
Call knowledge__find_maya_cmd_usage with cmd_name "parentConstraint" domain "maya_tools" max_results 20.
```

```text
Call knowledge__find_callers with call_name "cmds.parentConstraint" domain "maya_tools" max_results 20.
```