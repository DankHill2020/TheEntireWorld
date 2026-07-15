import json
import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("KnowledgeMCP")

TOOLS_ROOT = Path(r"C:\depot\tools")
DB_PATH = TOOLS_ROOT / "knowledge" / "index" / "knowledge_index_v2.sqlite"

DEFAULT_ROOTS = [
    TOOLS_ROOT,
    Path(r"C:\Program Files\Autodesk\Maya2023\devkit"),
    Path(r"C:\Program Files\Autodesk\Maya2023\Python"),
    Path(r"C:\Program Files\Autodesk\Maya2023\scripts"),
    Path(r"C:\Program Files\Autodesk\Maya2023\plug-ins"),
    Path(r"C:\Users\Aaron\Documents\maya\scripts"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Source"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Content\Python"),
    Path(r"C:\Desktop\MayaMCP"),
    Path(r"C:\Desktop\UnrealGenAISupport"),
    Path(r"C:\depot\Time_Fighters 5.8"),
]


def root_dirs():
    env = os.environ.get("AI_KNOWLEDGE_ROOTS")
    roots = [Path(p.strip()) for p in env.split(";") if p.strip()] if env else DEFAULT_ROOTS
    return [r for r in roots if r.exists()]


def connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Knowledge index v2 not found: {DB_PATH}. Run build_knowledge_index_v2.py first.")
    return sqlite3.connect(DB_PATH)


def domain_filters(domain: str) -> list[str]:
    domain = (domain or "all").lower()
    return {
        "maya": [
            r"%Autodesk\Maya%",
            r"%Documents\maya%",
            r"%MayaMCP%",
            r"%C:\depot\tools\maya_tools%",
            r"%\maya_tools\%",
            r"%/maya_tools/%",
        ],
        "maya_tools": [
            r"%C:\depot\tools\maya_tools%",
            r"%\maya_tools\%",
            r"%/maya_tools/%",
        ],
        "unreal": [
            r"%Epic Games\UE_%",
            r"%UnrealGenAISupport%",
            r"%C:\depot\tools\unreal_tools%",
            r"%\unreal_tools\%",
            r"%/unreal_tools/%",
        ],
        "unreal_tools": [
            r"%C:\depot\tools\unreal_tools%",
            r"%\unreal_tools\%",
            r"%/unreal_tools/%",
        ],
        "depot": [r"C:\depot\tools%"],
        "project": [r"%Time_Fighters%"],
        "all": [],
    }.get(domain, [])


def domain_where(domain: str, table_alias="files"):
    filters = domain_filters(domain)
    if not filters:
        return "", []
    return "AND (" + " OR ".join([f"{table_alias}.path LIKE ?" for _ in filters]) + ")", filters


def format_symbol(row, include_source=False):
    (
        rank, path, rel_path, module, name, qualname, kind, signature,
        docstring, start_line, end_line, source, calls_json,
        imports_json, maya_cmds_json, unreal_refs_json
    ) = row

    calls = json.loads(calls_json or "[]")[:40]
    imports = json.loads(imports_json or "[]")[:25]
    maya_cmds = json.loads(maya_cmds_json or "[]")[:25]
    unreal_refs = json.loads(unreal_refs_json or "[]")[:25]

    out = [
        f"## {kind}: {qualname}",
        f"Signature: {signature}",
        f"Path: {path}",
        f"Relative Path: {rel_path}",
        f"Module: {module or ''}",
        f"Lines: {start_line}-{end_line}",
        f"Rank: {rank}",
    ]

    if docstring:
        out.append(f"\nDocstring:\n```text\n{docstring[:1500]}\n```")

    if imports:
        out.append("\nImports: " + ", ".join(imports))
    if calls:
        out.append("\nCalls: " + ", ".join(calls))
    if maya_cmds:
        out.append("\nMaya cmds: " + ", ".join(maya_cmds))
    if unreal_refs:
        out.append("\nUnreal refs: " + ", ".join(unreal_refs))

    if include_source:
        out.append(f"\nSource:\n```python\n{source or ''}\n```")

    return "\n".join(out)


@mcp.tool()
def index_stats() -> str:
    """Show v2 index stats."""
    try:
        conn = connect()
        cur = conn.cursor()
        rows = [f"Index: {DB_PATH}"]
        for table in ["files", "chunks", "symbols", "symbol_calls", "imports"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            rows.append(f"{table}: {cur.fetchone()[0]}")
        return "\n".join(rows)
    except Exception as e:
        return str(e)


@mcp.tool()
def symbol_search(query: str, domain: str = "all", max_results: int = 20, include_source: bool = False) -> str:
    """
    Search Python functions/classes/methods using the AST-based v2 index.
    Returns signatures, paths, line numbers, calls/imports, and optionally source.
    """
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    where, params_extra = domain_where(domain, "files")
    params = [query] + params_extra + [max_results]

    sql = f"""
    SELECT
        bm25(symbols_fts) AS rank,
        files.path,
        files.rel_path,
        files.module,
        symbols.name,
        symbols.qualname,
        symbols.kind,
        symbols.signature,
        symbols.docstring,
        symbols.start_line,
        symbols.end_line,
        symbols.source,
        symbols.calls_json,
        symbols.imports_json,
        symbols.maya_cmds_json,
        symbols.unreal_refs_json
    FROM symbols_fts
    JOIN symbols ON symbols.id = symbols_fts.rowid
    JOIN files ON files.id = symbols.file_id
    WHERE symbols_fts MATCH ?
    {where}
    ORDER BY rank
    LIMIT ?
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        like = f"%{query}%"
        params = [like, like, like] + params_extra + [max_results]
        sql = f"""
        SELECT
            0 AS rank,
            files.path,
            files.rel_path,
            files.module,
            symbols.name,
            symbols.qualname,
            symbols.kind,
            symbols.signature,
            symbols.docstring,
            symbols.start_line,
            symbols.end_line,
            symbols.source,
            symbols.calls_json,
            symbols.imports_json,
            symbols.maya_cmds_json,
            symbols.unreal_refs_json
        FROM symbols
        JOIN files ON files.id = symbols.file_id
        WHERE (symbols.name LIKE ? OR symbols.qualname LIKE ? OR symbols.searchable_text LIKE ?)
        {where}
        LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return f"No symbol results for {query!r} in domain {domain!r}."

    return "\n\n---\n\n".join(format_symbol(row, include_source=include_source) for row in rows)


@mcp.tool()
def read_symbol_source(name: str, domain: str = "all", max_results: int = 8) -> str:
    """Read exact function/class source by symbol name or qualname."""
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    where, params_extra = domain_where(domain, "files")
    like = f"%{name}%"
    params = [name, name, like] + params_extra + [max_results]

    sql = f"""
    SELECT
        0 AS rank,
        files.path,
        files.rel_path,
        files.module,
        symbols.name,
        symbols.qualname,
        symbols.kind,
        symbols.signature,
        symbols.docstring,
        symbols.start_line,
        symbols.end_line,
        symbols.source,
        symbols.calls_json,
        symbols.imports_json,
        symbols.maya_cmds_json,
        symbols.unreal_refs_json
    FROM symbols
    JOIN files ON files.id = symbols.file_id
    WHERE (symbols.name = ? OR symbols.qualname = ? OR symbols.qualname LIKE ?)
    {where}
    ORDER BY length(symbols.qualname)
    LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return f"No source found for symbol {name!r} in domain {domain!r}."

    return "\n\n---\n\n".join(format_symbol(row, include_source=True) for row in rows)


@mcp.tool()
def find_callers(call_name: str, domain: str = "all", max_results: int = 20) -> str:
    """Find indexed functions/methods that call a given function/API, such as cmds.parentConstraint."""
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    where, params_extra = domain_where(domain, "files")
    like = f"%{call_name}%"
    params = [call_name, like] + params_extra + [max_results]

    sql = f"""
    SELECT
        0 AS rank,
        files.path,
        files.rel_path,
        files.module,
        symbols.name,
        symbols.qualname,
        symbols.kind,
        symbols.signature,
        symbols.docstring,
        symbols.start_line,
        symbols.end_line,
        symbols.source,
        symbols.calls_json,
        symbols.imports_json,
        symbols.maya_cmds_json,
        symbols.unreal_refs_json
    FROM symbol_calls
    JOIN symbols ON symbols.id = symbol_calls.symbol_id
    JOIN files ON files.id = symbols.file_id
    WHERE (symbol_calls.call_name = ? OR symbol_calls.call_name LIKE ?)
    {where}
    LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return f"No callers found for {call_name!r} in domain {domain!r}."

    return "\n\n---\n\n".join(format_symbol(row, include_source=False) for row in rows)


@mcp.tool()
def find_maya_cmd_usage(cmd_name: str, domain: str = "maya", max_results: int = 20) -> str:
    """Find functions using a Maya command, e.g. parentConstraint, skinCluster, ls, xform."""
    query1 = f"cmds.{cmd_name}"
    query2 = f"maya.cmds.{cmd_name}"
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    where, params_extra = domain_where(domain, "files")
    params = [f"%{query1}%", f"%{query2}%"] + params_extra + [max_results]

    sql = f"""
    SELECT
        0 AS rank,
        files.path,
        files.rel_path,
        files.module,
        symbols.name,
        symbols.qualname,
        symbols.kind,
        symbols.signature,
        symbols.docstring,
        symbols.start_line,
        symbols.end_line,
        symbols.source,
        symbols.calls_json,
        symbols.imports_json,
        symbols.maya_cmds_json,
        symbols.unreal_refs_json
    FROM symbols
    JOIN files ON files.id = symbols.file_id
    WHERE (symbols.maya_cmds_json LIKE ? OR symbols.maya_cmds_json LIKE ?)
    {where}
    LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return f"No Maya command usage found for {cmd_name!r} in domain {domain!r}."

    return "\n\n---\n\n".join(format_symbol(row, include_source=False) for row in rows)


@mcp.tool()
def knowledge_search(query: str, domain: str = "all", max_results: int = 8) -> str:
    """Search indexed text chunks from files/docs/examples."""
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    where, params_extra = domain_where(domain, "files")
    params = [query] + params_extra + [max_results]

    sql = f"""
    SELECT bm25(chunks_fts) AS rank, files.path, files.rel_path, chunks.text
    FROM chunks_fts
    JOIN chunks ON chunks.id = chunks_fts.rowid
    JOIN files ON files.id = chunks.file_id
    WHERE chunks_fts MATCH ?
    {where}
    ORDER BY rank
    LIMIT ?
    """

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        like = f"%{query}%"
        params = [like] + params_extra + [max_results]
        sql = f"""
        SELECT 0 AS rank, files.path, files.rel_path, chunks.text
        FROM chunks
        JOIN files ON files.id = chunks.file_id
        WHERE chunks.text LIKE ?
        {where}
        LIMIT ?
        """
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return f"No indexed text results for {query!r} in domain {domain!r}."

    out = []
    for rank, path, rel_path, text in rows:
        out.append(f"## {rel_path}\nPath: {path}\nRank: {rank}\n\n```text\n{text[:3000].strip()}\n```")
    return "\n\n---\n\n".join(out)


def is_inside(path: Path, root: Path) -> bool:
    try:
        path = path.resolve()
        root = root.resolve()
        return path == root or root in path.parents
    except Exception:
        return False


def is_allowed_path(path: Path) -> bool:
    return any(is_inside(path, root) for root in root_dirs())


@mcp.tool()
def read_tool_file(path: str, max_chars: int = 30000) -> str:
    """Read a file from approved knowledge roots."""
    p = Path(path)
    if not p.is_absolute():
        p = TOOLS_ROOT / p

    try:
        rp = p.resolve()
        if not is_allowed_path(rp):
            return f"Refusing to read outside approved roots: {rp}"
        if not rp.exists():
            return f"File not found: {rp}"
        return rp.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception as e:
        return f"Error reading file: {e}"


@mcp.tool()
def write_pending_tool(relative_path: str, code: str) -> str:
    """Write generated code to C:/depot/tools/ai_generated/pending_review only."""
    pending = (TOOLS_ROOT / "ai_generated" / "pending_review").resolve()
    target = (pending / relative_path).resolve()

    try:
        if pending not in target.parents and target != pending:
            return f"Refusing to write outside pending_review: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        return f"Wrote pending tool: {target}"
    except Exception as e:
        return f"Error writing pending tool: {e}"


if __name__ == "__main__":
    mcp.run()