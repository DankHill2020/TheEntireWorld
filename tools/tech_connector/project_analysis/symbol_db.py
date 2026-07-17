# symbol_db.py
"""SQLite‑backed symbol store for the Project‑Analysis pipeline.

Provides simple CRUD for symbols extracted by the AST parser.
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

DB_PATH = Path(__file__).with_name("project_analysis.db")

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            lineno INTEGER,
            file TEXT NOT NULL,
            UNIQUE(name, file, lineno)
        )
    """)
    return conn

def insert_symbols(symbols: List[Dict[str, Any]]) -> None:
    """Insert a batch of symbol dicts into the DB.
    Each dict must contain keys: name, type, lineno (optional), file.
    """
    conn = _get_conn()
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO symbols (name, type, lineno, file) VALUES (?, ?, ?, ?)",
            [
                (s["name"], s["type"], s.get("lineno"), s["file"]) for s in symbols
            ],
        )
    conn.close()

def query_symbols(name_substr: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.execute(
        "SELECT name, type, lineno, file FROM symbols WHERE name LIKE ?",
        (f"%{name_substr}%",),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1], "lineno": r[2], "file": r[3]} for r in rows]

if __name__ == "__main__":
    # Demo: list all symbols containing "test"
    for sym in query_symbols("test"):
        print(sym)
