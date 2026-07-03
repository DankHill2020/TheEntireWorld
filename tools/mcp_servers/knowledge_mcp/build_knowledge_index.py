import os
import re
import ast
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

TOOLS_ROOT = Path(r"C:\depot\tools")
DB_PATH = TOOLS_ROOT / "knowledge" / "index" / "knowledge_index.sqlite"

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

MAX_FILE_CHARS = 250_000
CHUNK_SIZE = 4000
CHUNK_OVERLAP = 500


def root_dirs():
    env = os.environ.get("AI_KNOWLEDGE_ROOTS")
    roots = [Path(p.strip()) for p in env.split(";") if p.strip()] if env else DEFAULT_ROOTS
    return [r for r in roots if r.exists()]


def should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return any(skip.lower() in parts for skip in SKIP_DIRS)


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
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:MAX_FILE_CHARS]
    except Exception:
        return ""


def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
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


def extract_python_symbols(text: str):
    symbols = []
    try:
        tree = ast.parse(text)
    except Exception:
        return symbols

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node) or ""
            args = []
            if hasattr(node, "args"):
                args = [a.arg for a in getattr(node.args, "args", [])]
            symbols.append({
                "name": node.name,
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "line": getattr(node, "lineno", 0),
                "signature": f"{node.name}({', '.join(args)})" if args else node.name,
                "docstring": doc[:3000],
            })
    return symbols


def init_db(conn):
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        root TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        rel_path TEXT NOT NULL,
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
        kind TEXT NOT NULL,
        line INTEGER,
        signature TEXT,
        docstring TEXT,
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
        kind,
        signature,
        docstring,
        path UNINDEXED,
        rel_path UNINDEXED,
        content='',
        tokenize='unicode61'
    );
    """)
    conn.commit()


def clear_file(conn, path: Path):
    cur = conn.cursor()
    cur.execute("SELECT id FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    if not row:
        return
    file_id = row[0]
    cur.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()


def index_file(conn, root: Path, path: Path):
    text = read_text(path)
    if not text:
        return False

    rel = str(path.relative_to(root)) if root in path.parents else str(path)
    stat = path.stat()
    sha = file_hash(path)

    # Reindex if changed or missing
    cur = conn.cursor()
    cur.execute("SELECT sha1 FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    if row and row[0] == sha:
        return False

    clear_file(conn, path)

    cur.execute("""
        INSERT INTO files(root, path, rel_path, ext, size, mtime, sha1, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(root), str(path), rel, path.suffix.lower(),
        stat.st_size, stat.st_mtime, sha, datetime.now().isoformat(timespec="seconds")
    ))
    file_id = cur.lastrowid

    chunks = chunk_text(text)
    for i, chunk in enumerate(chunks):
        cur.execute("INSERT INTO chunks(file_id, chunk_index, text) VALUES (?, ?, ?)", (file_id, i, chunk))
        cur.execute("INSERT INTO chunks_fts(rowid, text, path, rel_path) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, chunk, str(path), rel))

    if path.suffix.lower() == ".py":
        for sym in extract_python_symbols(text):
            cur.execute("""
                INSERT INTO symbols(file_id, name, kind, line, signature, docstring)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                file_id, sym["name"], sym["kind"], sym["line"],
                sym["signature"], sym["docstring"]
            ))
            cur.execute("""
                INSERT INTO symbols_fts(rowid, name, kind, signature, docstring, path, rel_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                cur.lastrowid, sym["name"], sym["kind"],
                sym["signature"], sym["docstring"], str(path), rel
            ))

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

    print("")
    print("Done.")
    print(f"Scanned files: {total}")
    print(f"Updated files: {updated}")
    print(f"Indexed files: {files}")
    print(f"Chunks: {chunks}")
    print(f"Symbols: {symbols}")


if __name__ == "__main__":
    main()