import ast
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TOOLS_ROOT = Path(r"C:\depot\tools")
DB_PATH = TOOLS_ROOT / "knowledge" / "index" / "knowledge_index_v2.sqlite"

DEFAULT_ROOTS = [
    TOOLS_ROOT,

    # Maya 2023
    Path(r"C:\Program Files\Autodesk\Maya2023\devkit"),
    Path(r"C:\Program Files\Autodesk\Maya2023\Python"),
    Path(r"C:\Program Files\Autodesk\Maya2023\scripts"),
    Path(r"C:\Program Files\Autodesk\Maya2023\plug-ins"),
    Path(r"C:\Users\Aaron\Documents\maya\scripts"),

    # Unreal 5.8
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Source"),
    Path(r"C:\Program Files\Epic Games\UE_5.8\Engine\Content\Python"),

    # Project/tooling
    Path(r"C:\Desktop\MayaMCP"),
    Path(r"C:\Desktop\UnrealGenAISupport"),
    Path(r"C:\depot\Time_Fighters 5.8"),
]

TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
    ".ini", ".cfg", ".bat", ".ps1", ".mel", ".cpp", ".h", ".hpp", ".cs"
}

SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".idea", ".vs",
    "Intermediate", "Saved", "DerivedDataCache", "Binaries",
    "Build", ".pytest_cache", "node_modules"
}

MAX_FILE_CHARS = 350_000
CHUNK_SIZE = 4500
CHUNK_OVERLAP = 650


@dataclass
class PythonSymbol:
    name: str
    qualname: str
    kind: str
    signature: str
    docstring: str
    start_line: int
    end_line: int
    source: str
    decorators: list[str]
    calls: list[str]
    imports: list[str]
    maya_cmds: list[str]
    unreal_refs: list[str]
    string_literals: list[str]


def root_dirs() -> list[Path]:
    env = os.environ.get("AI_KNOWLEDGE_ROOTS")
    roots = [Path(p.strip()) for p in env.split(";") if p.strip()] if env else DEFAULT_ROOTS
    return [r for r in roots if r.exists()]


def should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return any(skip.lower() in parts for skip in SKIP_DIRS)


def iter_files():
    for root in root_dirs():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if should_skip(path):
                continue
            if path.suffix.lower() not in TEXT_EXTS:
                continue
            yield root, path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
    except Exception:
        return ""


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[str]:
    if not text:
        return []

    chunks = []
    start = 0
    n = len(text)

    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(0, end - overlap)

    return chunks


def safe_unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def get_source_segment(lines: list[str], start: int, end: int) -> str:
    if start <= 0 or end <= 0:
        return ""
    return "\n".join(lines[start - 1:end])


def extract_imports(tree: ast.AST) -> list[str]:
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}" if mod else alias.name)

    return sorted(set(imports))


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return call_name(node.func)
    return ""


def extract_calls(node: ast.AST) -> list[str]:
    calls = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = call_name(n.func)
            if name:
                calls.append(name)
    return sorted(set(calls))


def extract_string_literals(node: ast.AST) -> list[str]:
    strings = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value.strip()
            if s and len(s) <= 200:
                strings.append(s)
    return sorted(set(strings))[:200]


def extract_signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return getattr(node, "name", "")

    parts = []
    args = node.args

    for arg in getattr(args, "posonlyargs", []):
        parts.append(arg.arg)

    for arg in args.args:
        parts.append(arg.arg)

    if args.vararg:
        parts.append("*" + args.vararg.arg)

    for arg in args.kwonlyargs:
        parts.append(arg.arg)

    if args.kwarg:
        parts.append("**" + args.kwarg.arg)

    return f"{node.name}({', '.join(parts)})"


def extract_python_symbols(text: str) -> list[PythonSymbol]:
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except Exception:
        return []

    file_imports = extract_imports(tree)
    symbols = []

    class StackVisitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_ClassDef(self, node):
            self._add(node, "class")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node):
            self._add(node, "method" if self.stack else "function")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self._add(node, "method" if self.stack else "function")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def _add(self, node, kind):
            name = node.name
            qualname = ".".join(self.stack + [name]) if self.stack else name
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            source = get_source_segment(lines, start, end)

            decorators = [safe_unparse(d) for d in getattr(node, "decorator_list", [])]
            calls = extract_calls(node)
            strings = extract_string_literals(node)

            maya_cmds = sorted({
                c for c in calls
                if c.startswith("cmds.") or c.startswith("maya.cmds.") or c.startswith("pm.")
            })

            unreal_refs = sorted({
                c for c in calls
                if c.startswith("unreal.") or "unreal" in c.lower()
            })

            if kind == "class":
                signature = name
            else:
                signature = extract_signature(node)

            symbols.append(PythonSymbol(
                name=name,
                qualname=qualname,
                kind=kind,
                signature=signature,
                docstring=ast.get_docstring(node) or "",
                start_line=start,
                end_line=end,
                source=source,
                decorators=[d for d in decorators if d],
                calls=calls,
                imports=file_imports,
                maya_cmds=maya_cmds,
                unreal_refs=unreal_refs,
                string_literals=strings,
            ))

    StackVisitor().visit(tree)
    return symbols


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        root TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        rel_path TEXT NOT NULL,
        module TEXT,
        ext TEXT,
        size INTEGER,
        mtime REAL,
        sha1 TEXT,
        indexed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        qualname TEXT NOT NULL,
        kind TEXT NOT NULL,
        signature TEXT,
        docstring TEXT,
        start_line INTEGER,
        end_line INTEGER,
        source TEXT,
        decorators_json TEXT,
        calls_json TEXT,
        imports_json TEXT,
        maya_cmds_json TEXT,
        unreal_refs_json TEXT,
        string_literals_json TEXT,
        searchable_text TEXT,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS symbol_calls (
        id INTEGER PRIMARY KEY,
        symbol_id INTEGER NOT NULL,
        call_name TEXT NOT NULL,
        FOREIGN KEY(symbol_id) REFERENCES symbols(id)
    );

    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        import_name TEXT NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text,
        path UNINDEXED,
        rel_path UNINDEXED,
        content='',
        tokenize='unicode61'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
        name,
        qualname,
        kind,
        signature,
        docstring,
        searchable_text,
        path UNINDEXED,
        rel_path UNINDEXED,
        content='',
        tokenize='unicode61'
    );

    CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
    CREATE INDEX IF NOT EXISTS idx_files_rel_path ON files(rel_path);
    CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
    CREATE INDEX IF NOT EXISTS idx_symbols_qualname ON symbols(qualname);
    CREATE INDEX IF NOT EXISTS idx_symbol_calls_call_name ON symbol_calls(call_name);
    CREATE INDEX IF NOT EXISTS idx_imports_import_name ON imports(import_name);
    """)
    conn.commit()


def clear_file(conn: sqlite3.Connection, path: Path):
    cur = conn.cursor()
    cur.execute("SELECT id FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    if not row:
        return

    file_id = row[0]
    cur.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,))
    chunk_ids = [r[0] for r in cur.fetchall()]
    for cid in chunk_ids:
        cur.execute("DELETE FROM chunks_fts WHERE rowid = ?", (cid,))

    cur.execute("SELECT id FROM symbols WHERE file_id = ?", (file_id,))
    symbol_ids = [r[0] for r in cur.fetchall()]
    for sid in symbol_ids:
        cur.execute("DELETE FROM symbols_fts WHERE rowid = ?", (sid,))

    cur.execute("DELETE FROM symbol_calls WHERE symbol_id IN (SELECT id FROM symbols WHERE file_id = ?)", (file_id,))
    cur.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()


def module_from_rel_path(rel_path: str, ext: str) -> str:
    if ext != ".py":
        return ""
    p = rel_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def index_file(conn: sqlite3.Connection, root: Path, path: Path) -> bool:
    text = read_text(path)
    if not text:
        return False

    try:
        rel = str(path.relative_to(root))
    except Exception:
        rel = str(path)

    stat = path.stat()
    sha = file_hash(path)

    cur = conn.cursor()
    cur.execute("SELECT sha1 FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()

    if row and row[0] == sha:
        return False

    clear_file(conn, path)

    ext = path.suffix.lower()
    module = module_from_rel_path(rel, ext)

    cur.execute("""
        INSERT INTO files(root, path, rel_path, module, ext, size, mtime, sha1, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(root), str(path), rel, module, ext,
        stat.st_size, stat.st_mtime, sha,
        datetime.now().isoformat(timespec="seconds")
    ))

    file_id = cur.lastrowid

    for i, chunk in enumerate(chunk_text(text)):
        cur.execute(
            "INSERT INTO chunks(file_id, chunk_index, text) VALUES (?, ?, ?)",
            (file_id, i, chunk)
        )
        chunk_id = cur.lastrowid
        cur.execute(
            "INSERT INTO chunks_fts(rowid, text, path, rel_path) VALUES (?, ?, ?, ?)",
            (chunk_id, chunk, str(path), rel)
        )

    if ext == ".py":
        symbols = extract_python_symbols(text)

        file_imports = sorted(set([imp for sym in symbols for imp in sym.imports]))
        for imp in file_imports:
            cur.execute(
                "INSERT INTO imports(file_id, import_name) VALUES (?, ?)",
                (file_id, imp)
            )

        for sym in symbols:
            searchable = "\n".join([
                sym.name,
                sym.qualname,
                sym.signature,
                sym.docstring,
                " ".join(sym.calls),
                " ".join(sym.imports),
                " ".join(sym.maya_cmds),
                " ".join(sym.unreal_refs),
                " ".join(sym.string_literals),
            ])

            cur.execute("""
                INSERT INTO symbols(
                    file_id, name, qualname, kind, signature, docstring,
                    start_line, end_line, source,
                    decorators_json, calls_json, imports_json,
                    maya_cmds_json, unreal_refs_json, string_literals_json,
                    searchable_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_id, sym.name, sym.qualname, sym.kind, sym.signature, sym.docstring,
                sym.start_line, sym.end_line, sym.source,
                json.dumps(sym.decorators),
                json.dumps(sym.calls),
                json.dumps(sym.imports),
                json.dumps(sym.maya_cmds),
                json.dumps(sym.unreal_refs),
                json.dumps(sym.string_literals),
                searchable,
            ))

            symbol_id = cur.lastrowid

            cur.execute("""
                INSERT INTO symbols_fts(
                    rowid, name, qualname, kind, signature,
                    docstring, searchable_text, path, rel_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol_id, sym.name, sym.qualname, sym.kind, sym.signature,
                sym.docstring, searchable, str(path), rel
            ))

            for c in sym.calls:
                cur.execute(
                    "INSERT INTO symbol_calls(symbol_id, call_name) VALUES (?, ?)",
                    (symbol_id, c)
                )

    conn.commit()
    return True


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    print(f"Index DB: {DB_PATH}")
    print("Roots:")
    for r in root_dirs():
        print(f"  - {r}")

    total = 0
    updated = 0

    for root, path in iter_files():
        total += 1
        try:
            if index_file(conn, root, path):
                updated += 1
                if updated % 25 == 0:
                    print(f"Indexed/updated {updated} files...")
        except Exception as e:
            print(f"[ERROR] {path}: {e}")

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM files")
    files = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chunks")
    chunks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM symbols")
    symbols = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM symbol_calls")
    calls = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM imports")
    imports = cur.fetchone()[0]

    print("")
    print("Done.")
    print(f"Scanned files: {total}")
    print(f"Updated files: {updated}")
    print(f"Indexed files: {files}")
    print(f"Chunks: {chunks}")
    print(f"Symbols: {symbols}")
    print(f"Calls: {calls}")
    print(f"Imports: {imports}")


if __name__ == "__main__":
    main()