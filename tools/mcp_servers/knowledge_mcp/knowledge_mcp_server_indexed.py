import os
import sqlite3
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("KnowledgeMCP")

TOOLS_ROOT = Path(r"C:\depot\tools")
DB_PATH = TOOLS_ROOT / "knowledge" / "index" / "knowledge_index.sqlite"

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


def db_exists() -> bool:
    return DB_PATH.exists()


def connect():
    if not db_exists():
        raise FileNotFoundError(f"Knowledge index not found: {DB_PATH}. Run build_knowledge_index.py first.")
    return sqlite3.connect(DB_PATH)


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
def domain_filters(domain: str) -> list[str]:
    domain = (domain or "all").lower()

    filters = {
        "maya": [
            r"%Autodesk\Maya%",
            r"%Documents\maya%",
            r"%MayaMCP%",
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
        "depot": [
            r"C:\depot\tools%",
        ],
        "project": [
            r"%Time_Fighters%",
        ],
        "all": [],
    }

    return filters.get(domain, [])

@mcp.tool()
def knowledge_search(query: str, domain: str = "all", max_results: int = 8) -> str:
    """Search indexed text chunks with optional domain filtering."""
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    filters = domain_filters(domain)
    where = ""
    params = [query]

    if filters:
        where = "AND (" + " OR ".join(["files.path LIKE ?" for _ in filters]) + ")"
        params.extend(filters)

    params.append(max_results)

    sql = f"""
    SELECT
        bm25(chunks_fts) AS rank,
        files.path,
        files.rel_path,
        chunks.text
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
    except Exception as e:
        return f"knowledge_search error: {e}"

    if not rows:
        return f"No results for '{query}' in domain '{domain}'."

    out = []
    for rank, path, rel_path, text in rows:
        out.append(
            f"## {rel_path}\n\n"
            f"Path:\n{path}\n\n"
            f"Rank:\n{rank}\n\n"
            f"```text\n{text[:2500].strip()}\n```"
        )

    return "\n\n---\n\n".join(out)


@mcp.tool()
def symbol_search(query: str, domain: str = "all", max_results: int = 20) -> str:
    """Search indexed Python functions/classes with optional domain filtering."""
    try:
        conn = connect()
    except Exception as e:
        return str(e)

    filters = domain_filters(domain)
    where = ""
    params = [query]

    if filters:
        where = "AND (" + " OR ".join(["files.path LIKE ?" for _ in filters]) + ")"
        params.extend(filters)

    params.append(max_results)

    sql = f"""
    SELECT
        bm25(symbols_fts) AS rank,
        files.path,
        files.rel_path,
        symbols.name,
        symbols.kind,
        symbols.signature,
        symbols.docstring
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
    except Exception as e:
        return f"symbol_search error: {e}"

    if not rows:
        return f"No results for '{query}' in domain '{domain}'."

    out = []
    for rank, path, rel_path, name, kind, signature, docstring in rows:
        out.append(
            f"## {kind}: {name}\n\n"
            f"Signature:\n{signature}\n\n"
            f"Path:\n{path}\n\n"
            f"Relative Path:\n{rel_path}\n\n"
            f"Rank:\n{rank}\n\n"
            f"```text\n{docstring or ''}\n```"
        )

    return "\n\n---\n\n".join(out)


@mcp.tool()
def read_tool_file(path: str, max_chars: int = 20000) -> str:
    """
    Read a file from any approved knowledge root.
    """
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
    """
    Write generated code to C:/depot/tools/ai_generated/pending_review only.
    """
    pending = (TOOLS_ROOT / "ai_generated" / "pending_review").resolve()
    target = (pending / relative_path).resolve()

    try:
        if not is_inside(target, pending):
            return f"Refusing to write outside pending_review: {target}"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")

        return f"Wrote pending tool: {target}"

    except Exception as e:
        return f"Error writing pending tool: {e}"


@mcp.tool()
def list_knowledge_roots() -> str:
    """List currently active searchable roots."""
    return "\n".join(str(r) for r in root_dirs())


@mcp.tool()
def index_stats() -> str:
    """Show index stats."""
    try:
        conn = connect()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM files")
        files = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM chunks")
        chunks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM symbols")
        symbols = cur.fetchone()[0]
        return f"Index: {DB_PATH}\nFiles: {files}\nChunks: {chunks}\nSymbols: {symbols}"
    except Exception as e:
        return str(e)


@mcp.tool()
def agent_workflow() -> str:
    """Read the AI agent workflow rules."""
    path = TOOLS_ROOT / "knowledge" / "AI_AGENT_WORKFLOW.md"

    if not path.exists():
        return "AI_AGENT_WORKFLOW.md not found."

    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    mcp.run()
