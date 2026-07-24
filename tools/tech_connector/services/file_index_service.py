"""File-aware access to the existing SQLite project index.

This is intentionally defensive: it does not assume the index schema is exactly
`files(path, content, ...)`. It inspects available tables/columns and uses the
best matching path/content metadata columns it can find.
"""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tech_connector.models.constants import project_index_db_path


PATH_COLUMN_CANDIDATES = ("path", "file_path", "filepath", "absolute_path", "relpath", "relative_path")
CONTENT_COLUMN_CANDIDATES = ("content", "text", "source", "body", "chunk", "snippet")
SIZE_COLUMN_CANDIDATES = ("size", "file_size", "bytes")
MODIFIED_COLUMN_CANDIDATES = ("last_modified", "mtime", "modified", "updated_at", "timestamp")
TYPE_COLUMN_CANDIDATES = ("type", "file_type", "language", "suffix", "extension")


class FileIndexService:
    """Read/search indexed project files from the local SQLite index."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else project_index_db_path()

    @contextmanager
    def _connect(self):
        if not self.db_path.exists():
            raise FileNotFoundError(f"Project index not found: {self.db_path}")
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
        conn = sqlite3.connect(database_uri, timeout=30, uri=True)
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA query_only = ON")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def _tables(self, conn: sqlite3.Connection) -> List[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [str(row[0]) for row in rows]

    def _columns(self, conn: sqlite3.Connection, table: str) -> List[str]:
        rows = conn.execute(f"PRAGMA table_info({self._quote_identifier(table)})").fetchall()
        return [str(row["name"]) for row in rows]

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _pick_column(columns: List[str], candidates: Tuple[str, ...]) -> Optional[str]:
        lowered = {c.lower(): c for c in columns}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        for candidate in candidates:
            for col in columns:
                if candidate.lower() in col.lower():
                    return col
        return None

    def _find_file_table(self, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        best = None
        for table in self._tables(conn):
            columns = self._columns(conn, table)
            path_col = self._pick_column(columns, PATH_COLUMN_CANDIDATES)
            content_col = self._pick_column(columns, CONTENT_COLUMN_CANDIDATES)
            if not path_col:
                continue
            score = 2 if content_col else 1
            if table.lower() in {"files", "file_index", "documents", "chunks"}:
                score += 2
            candidate = {
                "table": table,
                "columns": columns,
                "path_col": path_col,
                "content_col": content_col,
                "size_col": self._pick_column(columns, SIZE_COLUMN_CANDIDATES),
                "modified_col": self._pick_column(columns, MODIFIED_COLUMN_CANDIDATES),
                "type_col": self._pick_column(columns, TYPE_COLUMN_CANDIDATES),
                "score": score,
            }
            if best is None or candidate["score"] > best["score"]:
                best = candidate
        return best

    def describe_schema(self) -> Dict[str, Any]:
        """Return schema information useful for debugging index mismatches."""
        try:
            with self._connect() as conn:
                tables = {table: self._columns(conn, table) for table in self._tables(conn)}
                detected = self._find_file_table(conn)
            return {"db_path": str(self.db_path), "tables": tables, "detected_file_table": detected}
        except Exception as exc:
            return {"db_path": str(self.db_path), "error": str(exc)}

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Return indexed content for a file path.

        The Tech Connector v2 index stores source text in `chunks.text`, not
        `files.content`, so prefer the files→chunks join before falling back to
        any detected content-like column.
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id FROM files
                    WHERE path = ? OR path LIKE ? OR rel_path = ? OR rel_path LIKE ?
                    LIMIT 1
                    """,
                    (
                        file_path,
                        f"%{Path(file_path).as_posix()}",
                        file_path,
                        f"%{Path(file_path).as_posix()}",
                    ),
                ).fetchone()
                if row:
                    chunks = conn.execute(
                        """
                        SELECT text FROM chunks
                        WHERE file_id = ?
                        ORDER BY chunk_index ASC
                        """,
                        (row["id"],),
                    ).fetchall()
                    if chunks:
                        return "".join(str(chunk["text"] or "") for chunk in chunks)

                meta = self._find_file_table(conn)
                if not meta or not meta.get("content_col"):
                    return None
                table = self._quote_identifier(meta["table"])
                path_col = self._quote_identifier(meta["path_col"])
                content_col = self._quote_identifier(meta["content_col"])
                row = conn.execute(
                    f"SELECT {content_col} AS content FROM {table} WHERE {path_col} = ? LIMIT 1",
                    (file_path,),
                ).fetchone()
                if not row:
                    row = conn.execute(
                        f"SELECT {content_col} AS content FROM {table} WHERE {path_col} LIKE ? LIMIT 1",
                        (f"%{Path(file_path).as_posix()}",),
                    ).fetchone()
                return str(row["content"]) if row and row["content"] is not None else None
        except Exception as exc:
            print(f"Error retrieving file content from index: {exc}")
            return None

    def search_files(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search indexed files by path or chunk text."""
        if not query:
            return []
        limit = max(1, min(int(limit), 100))
        try:
            with self._connect() as conn:
                like = f"%{query}%"
                # Prefer the v2 schema: files + chunks.
                try:
                    rows = conn.execute(
                        """
                        SELECT f.path AS path, MIN(c.chunk_index) AS first_chunk, c.text AS content
                        FROM files f
                        LEFT JOIN chunks c ON c.file_id = f.id
                        WHERE f.path LIKE ? OR f.rel_path LIKE ? OR c.text LIKE ?
                        GROUP BY f.id
                        ORDER BY f.path
                        LIMIT ?
                        """,
                        (like, like, like, limit),
                    ).fetchall()
                    return [{"path": row["path"], "content": row["content"] or ""} for row in rows]
                except Exception:
                    pass

                meta = self._find_file_table(conn)
                if not meta:
                    return []
                table = self._quote_identifier(meta["table"])
                path_col = self._quote_identifier(meta["path_col"])
                content_name = meta.get("content_col")
                content_col = self._quote_identifier(content_name) if content_name else None
                if content_col:
                    rows = conn.execute(
                        f"SELECT {path_col} AS path, {content_col} AS content FROM {table} "
                        f"WHERE {path_col} LIKE ? OR {content_col} LIKE ? LIMIT ?",
                        (like, like, limit),
                    ).fetchall()
                    return [{"path": row["path"], "content": row["content"] or ""} for row in rows]
                rows = conn.execute(
                    f"SELECT {path_col} AS path FROM {table} WHERE {path_col} LIKE ? LIMIT ?",
                    (like, limit),
                ).fetchall()
                return [{"path": row["path"], "content": ""} for row in rows]
        except Exception as exc:
            print(f"Error searching files from index: {exc}")
            return []

    def get_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Return available metadata for a file from the detected file table."""
        try:
            with self._connect() as conn:
                meta = self._find_file_table(conn)
                if not meta:
                    return None
                wanted = [meta["path_col"], meta.get("size_col"), meta.get("modified_col"), meta.get("type_col")]
                wanted = [col for col in wanted if col]
                select = ", ".join(f"{self._quote_identifier(col)} AS {self._quote_identifier(col)}" for col in wanted)
                table = self._quote_identifier(meta["table"])
                path_col = self._quote_identifier(meta["path_col"])
                row = conn.execute(
                    f"SELECT {select} FROM {table} WHERE {path_col} = ? LIMIT 1",
                    (file_path,),
                ).fetchone()
                if not row:
                    return None
                data = dict(row)
                return {
                    "path": data.get(meta["path_col"]),
                    "size": data.get(meta.get("size_col")) if meta.get("size_col") else None,
                    "last_modified": data.get(meta.get("modified_col")) if meta.get("modified_col") else None,
                    "type": data.get(meta.get("type_col")) if meta.get("type_col") else None,
                    "source_table": meta["table"],
                }
        except Exception as exc:
            print(f"Error getting file metadata from index: {exc}")
            return None

    def get_file_snapshot(
        self,
        file_path: str,
        *,
        symbol_limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """Return one versioned file-and-symbol snapshot from the index only.

        This deliberately performs no filesystem probes. Prompt handling can
        therefore use the maintained index without turning a request into a
        live project scan.
        """

        requested = str(file_path or "").strip()
        if not requested:
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, root, path, rel_path, module, ext, size, mtime,
                           sha1, indexed_at, source_scope
                    FROM files
                    WHERE path = ? COLLATE NOCASE
                       OR rel_path = ? COLLATE NOCASE
                    LIMIT 1
                    """,
                    (requested, requested),
                ).fetchone()
                if row is None:
                    normalized = Path(requested).as_posix()
                    row = conn.execute(
                        """
                        SELECT id, root, path, rel_path, module, ext, size, mtime,
                               sha1, indexed_at, source_scope
                        FROM files
                        WHERE REPLACE(path, '\\', '/') = ? COLLATE NOCASE
                           OR REPLACE(rel_path, '\\', '/') = ? COLLATE NOCASE
                        LIMIT 1
                        """,
                        (normalized, normalized),
                    ).fetchone()
                if row is None:
                    norm_path = Path(requested).as_posix()
                    parts = norm_path.split("/")
                    if len(parts) >= 2:
                        suffix = "/" + "/".join(parts[-2:])
                        row = conn.execute(
                            """
                            SELECT id, root, path, rel_path, module, ext, size, mtime,
                                   sha1, indexed_at, source_scope
                            FROM files
                            WHERE REPLACE(path, '\\', '/') LIKE ? COLLATE NOCASE
                            LIMIT 1
                            """,
                            (f"%{suffix}",),
                        ).fetchone()
                if row is None:
                    return None
                symbols = conn.execute(
                    """
                    SELECT name, qualname, parent_qualname, parent_kind, kind,
                           signature, docstring, start_line, end_line, source
                    FROM symbols
                    WHERE file_id = ?
                    ORDER BY start_line, id
                    LIMIT ?
                    """,
                    (int(row["id"]), max(1, min(int(symbol_limit), 500))),
                ).fetchall()
                imports = conn.execute(
                    """
                    SELECT import_name, module, name, alias, level, kind, lineno
                    FROM imports
                    WHERE file_id = ?
                    ORDER BY lineno, id
                    LIMIT 200
                    """,
                    (int(row["id"]),),
                ).fetchall()
                snapshot = dict(row)
                snapshot.pop("id", None)
                snapshot["symbols"] = [dict(symbol) for symbol in symbols]
                snapshot["imports"] = [dict(item) for item in imports]
                snapshot["source"] = "project_index"
                return snapshot
        except Exception as exc:
            print(f"Error getting indexed file snapshot: {exc}")
            return None

    def find_indexed_paths_by_name(self, filename: str, *, limit: int = 20) -> List[str]:
        """Return exact basename matches from the maintained project index."""

        name = Path(str(filename or "")).name
        if not name:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT path
                    FROM files
                    WHERE path = ? COLLATE NOCASE
                       OR path LIKE ? COLLATE NOCASE
                       OR path LIKE ? COLLATE NOCASE
                    ORDER BY path
                    LIMIT ?
                    """,
                    (name, f"%\\{name}", f"%/{name}", max(1, min(int(limit), 100))),
                ).fetchall()
            return [str(row["path"]) for row in rows]
        except Exception as exc:
            print(f"Error finding indexed paths by name: {exc}")
            return []

    def list_all_indexed_files(self, limit: int = 100) -> List[str]:
        """List indexed paths."""
        limit = max(1, min(int(limit), 1000))
        try:
            with self._connect() as conn:
                meta = self._find_file_table(conn)
                if not meta:
                    return []
                table = self._quote_identifier(meta["table"])
                path_col = self._quote_identifier(meta["path_col"])
                order = ""
                if meta.get("modified_col"):
                    order = f" ORDER BY {self._quote_identifier(meta['modified_col'])} DESC"
                rows = conn.execute(
                    f"SELECT {path_col} AS path FROM {table}{order} LIMIT ?",
                    (limit,),
                ).fetchall()
                return [str(row["path"]) for row in rows]
        except Exception as exc:
            print(f"Error listing indexed files: {exc}")
            return []


file_index_service = FileIndexService()
