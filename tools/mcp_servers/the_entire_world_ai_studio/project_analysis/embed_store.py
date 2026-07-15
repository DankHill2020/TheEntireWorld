# embed_store.py
"""Embedding store for Project‑Analysis.

Uses the Nomic embed model via Ollama's embeddings endpoint.
Embeddings are stored in the same SQLite DB (table `embeddings`).
"""
import json
import sqlite3
import requests
from typing import List

DB_PATH = "c:/depot/tools/mcp_servers/the_entire_world_ai_studio/project_analysis/project_analysis.db"
OLLAMA_URL = "http://localhost:11434/api/embeddings"

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            vector BLOB NOT NULL,
            UNIQUE(text)
        )
    """)
    return conn

def _call_ollama(model: str, input_text: str) -> List[float]:
    payload = {"model": model, "prompt": input_text}
    resp = requests.post(OLLAMA_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    # Ollama returns a list of floats under "embedding"
    return data.get("embedding", [])

def embed_text(text: str, model: str = "nomic-embed-text") -> List[float]:
    """Get (and cache) the embedding for *text* using the given model.
    Returns a list of floats.
    """
    conn = _get_conn()
    cur = conn.execute("SELECT vector FROM embeddings WHERE text = ?", (text,))
    row = cur.fetchone()
    if row:
        conn.close()
        # Stored as JSON string of list
        return json.loads(row[0])
    # Not cached – call Ollama
    vector = _call_ollama(model, text)
    conn.execute(
        "INSERT INTO embeddings (text, vector) VALUES (?, ?)",
        (text, json.dumps(vector)),
    )
    conn.commit()
    conn.close()
    return vector

if __name__ == "__main__":
    sample = "def hello():\n    print(\"hi\")"
    print("Embedding length:", len(embed_text(sample)))
