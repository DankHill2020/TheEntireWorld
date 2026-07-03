# Code Workspace

v5.7 introduces the first coding-assistant workspace pass.

## Added UI

```text
Project Files tree
Editor tab
Search / Symbols tab
Find in Project
Symbols
Callers
Implementation
```

## File editor

Supports common technical art / web / code files:

```text
.py .mel .cpp .h .hpp .cs .ts .tsx .js .jsx .html .css
.json .yaml .yml .md .txt .ini .cfg .bat .ps1 .uplugin .uproject
```

The editor creates a `.tew_backup` the first time it saves a file.

## Search

Find in Project searches accessible project roots.

## Symbol tools

The Search / Symbols tab wraps the AST Knowledge MCP tools:

```text
knowledge__symbol_search
knowledge__find_callers
knowledge__read_symbol_source
```

This makes the concepts more intuitive:

```text
Symbols = What exists?
Callers = Who calls this?
Implementation = Show me the source.
```

## Next steps

- Proper collapsible dock panels
- Syntax highlighting
- Diff preview
- Apply/reject AI edits
- Go to definition from symbol result
- File watcher / incremental reindex