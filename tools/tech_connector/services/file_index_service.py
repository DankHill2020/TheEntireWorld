"""File-aware access to the existing SQLite project index.

This is intentionally defensive: it does not assume the index schema is exactly
`files(path, content, ...)`. It inspects available tables/columns and uses the
best matching path/content metadata columns it can find.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

    def find_python_symbol_candidates(
        self,
        symbol_names: Iterable[str],
        project_roots: Iterable[str],
        *,
        kinds: tuple[str, ...] = ("function", "class"),
        limit: int = 8,
        max_files: int = 5000,
        max_file_bytes: int = 2_000_000,
    ) -> List[Dict[str, Any]]:
        """
        Find exact Python symbols when the persisted symbol index is stale.
        :param symbol_names: exact callable or class names to locate
        :param project_roots: allowed project roots to inspect
        :param kinds: accepted Python symbol kinds
        :param limit: maximum matches returned
        :param max_files: maximum Python files inspected
        :param max_file_bytes: maximum source file size inspected
        :return: bounded source-backed symbol records
        """
        names = [
            str(name).strip()
            for name in symbol_names
            if re.fullmatch(r"[A-Za-z_]\w*", str(name).strip())
        ]
        if not names:
            return []
        accepted_kinds = {str(kind).strip().lower() for kind in kinds}
        declaration_kinds = []
        if "function" in accepted_kinds:
            declaration_kinds.extend(["def", "async def"])
        if "class" in accepted_kinds:
            declaration_kinds.append("class")
        if not declaration_kinds:
            return []
        declarations = re.compile(
            rf"(?m)^\s*(?P<kind>{'|'.join(re.escape(item) for item in declaration_kinds)})"
            rf"\s+(?P<name>{'|'.join(re.escape(name) for name in names)})\b"
        )
        ignored_directories = {
            ".git", ".hg", ".mypy_cache", ".pytest_cache", ".ruff_cache",
            ".svn", ".tox", ".venv", "__pycache__", "build", "dist",
            "node_modules", "site-packages",
        }
        matches: List[Dict[str, Any]] = []
        inspected = 0
        for raw_root in project_roots:
            try:
                root = Path(str(raw_root)).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if not root.is_dir():
                continue
            for directory, directory_names, file_names in os.walk(root):
                directory_names[:] = [
                    name
                    for name in directory_names
                    if name.casefold() not in ignored_directories
                    and not name.startswith(".")
                ]
                for file_name in file_names:
                    if not file_name.casefold().endswith((".py", ".pyi")):
                        continue
                    inspected += 1
                    if inspected > max(1, int(max_files)):
                        return matches
                    source_path = Path(directory) / file_name
                    try:
                        if source_path.stat().st_size > max(1, int(max_file_bytes)):
                            continue
                        source = source_path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    except OSError:
                        continue
                    for found in declarations.finditer(source):
                        raw_kind = found.group("kind")
                        symbol_kind = "class" if raw_kind == "class" else "function"
                        line = source.count("\n", 0, found.start()) + 1
                        signature = source.splitlines()[line - 1].strip()
                        matches.append(
                            {
                                "name": found.group("name"),
                                "qualname": found.group("name"),
                                "kind": symbol_kind,
                                "path": str(source_path.resolve()),
                                "rel_path": str(source_path.resolve()),
                                "start_line": line,
                                "signature": signature,
                                "source": source[max(0, found.start() - 300):found.start() + 1800],
                                "candidate_source": "project_source_fallback",
                            }
                        )
                        if len(matches) >= max(1, int(limit)):
                            return matches
        return matches

    def find_python_declaration_candidates(
        self,
        query_terms: Iterable[str],
        project_roots: Iterable[str],
        *,
        kinds: tuple[str, ...] = ("function", "class"),
        path_hints: Iterable[str] = (),
        limit: int = 40,
        max_files: int = 5000,
        max_file_bytes: int = 2_000_000,
    ) -> List[Dict[str, Any]]:
        """
        Find related Python declarations when the persisted symbol index is stale.
        :param query_terms: behavior, symbol, or API terms to match
        :param project_roots: allowed first-party project roots to inspect
        :param kinds: accepted Python declaration kinds
        :param path_hints: domain words used to prioritize likely source folders
        :param limit: maximum ranked matches returned
        :param max_files: maximum Python files inspected
        :param max_file_bytes: maximum source file size inspected
        :return: bounded source-backed declaration records
        """
        terms = {
            re.sub(r"[^a-z0-9_]+", "", str(term).casefold())
            for term in query_terms
            if len(re.sub(r"[^a-z0-9_]+", "", str(term).casefold())) >= 2
        }
        if not terms:
            return []
        accepted_kinds = {str(kind).strip().casefold() for kind in kinds}
        declarations = re.compile(
            r"(?m)^(?P<indent>[ \t]*)(?P<kind>async\s+def|def|class)\s+"
            r"(?P<name>[A-Za-z_]\w*)\s*(?P<signature>\([^\n]*\))?"
        )
        ignored_directories = {
            ".git", ".hg", ".mypy_cache", ".pytest_cache", ".ruff_cache",
            ".svn", ".tox", ".venv", "__pycache__", "build", "dist",
            "node_modules", "site-packages",
        }
        normalized_hints = {
            re.sub(r"[^a-z0-9]+", "", str(hint).casefold())
            for hint in path_hints
            if str(hint).strip()
        }
        matches: List[Dict[str, Any]] = []
        inspected = 0
        seen_files: set[str] = set()

        for raw_root in project_roots:
            try:
                root = Path(str(raw_root)).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if not root.is_dir():
                continue
            prioritized_roots: list[Path] = []
            if normalized_hints:
                try:
                    prioritized_roots = [
                        child
                        for child in root.iterdir()
                        if child.is_dir()
                        and any(
                            hint in re.sub(r"[^a-z0-9]+", "", child.name.casefold())
                            for hint in normalized_hints
                        )
                    ]
                except OSError:
                    prioritized_roots = []
            for scan_root in [*prioritized_roots, root]:
                if scan_root == root and prioritized_roots and len(matches) >= max(1, int(limit)):
                    break
                for directory, directory_names, file_names in os.walk(scan_root):
                    directory_names[:] = [
                        name
                        for name in directory_names
                        if name.casefold() not in ignored_directories
                        and not name.startswith(".")
                    ]
                    for file_name in file_names:
                        if not file_name.casefold().endswith((".py", ".pyi")):
                            continue
                        source_path = Path(directory) / file_name
                        file_key = str(source_path).casefold()
                        if file_key in seen_files:
                            continue
                        seen_files.add(file_key)
                        inspected += 1
                        if inspected > max(1, int(max_files)):
                            break
                        try:
                            if source_path.stat().st_size > max(1, int(max_file_bytes)):
                                continue
                            source = source_path.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            continue
                        path_text = str(source_path).replace("\\", "/").casefold()
                        for found in declarations.finditer(source):
                            raw_kind = found.group("kind").replace(" ", "")
                            indent = found.group("indent") or ""
                            symbol_kind = "class" if raw_kind == "class" else ("method" if indent else "function")
                            if symbol_kind not in accepted_kinds and not (
                                symbol_kind == "method" and "function" in accepted_kinds
                            ):
                                continue
                            name = found.group("name")
                            signature = f"{name}{found.group('signature') or ''}"
                            declaration_text = f"{name} {signature}".casefold()
                            name_matches = {term for term in terms if term in declaration_text}
                            if not name_matches:
                                continue
                            line = source.count("\n", 0, found.start()) + 1
                            path_matches = {term for term in terms if term in path_text}
                            score = len(name_matches) * 100 + len(path_matches) * 12
                            score += sum(20 for hint in normalized_hints if hint in path_text)
                            if name.casefold().startswith(("create_", "build_", "make_", "show_", "launch_")):
                                score += 15
                            matches.append(
                                {
                                    "name": name,
                                    "qualname": name,
                                    "kind": symbol_kind,
                                    "path": str(source_path.resolve()),
                                    "rel_path": str(source_path.resolve()),
                                    "start_line": line,
                                    "signature": signature,
                                    "docstring": "",
                                    "source": source[found.start():found.start() + 2200],
                                    "candidate_source": "project_source_fallback",
                                    "source_match_score": score,
                                }
                            )
                    if inspected > max(1, int(max_files)):
                        break
                if inspected > max(1, int(max_files)):
                    break
        matches.sort(
            key=lambda item: (
                -int(item.get("source_match_score") or 0),
                str(item.get("path") or "").casefold(),
                int(item.get("start_line") or 0),
            )
        )
        return matches[:max(1, int(limit))]

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

    def get_bounded_python_snapshot(
        self,
        file_path: str,
        *,
        project_roots: list[str] | tuple[str, ...],
        symbol_limit: int = 100,
        max_bytes: int = 2_000_000,
    ) -> Optional[Dict[str, Any]]:
        """Build a bounded snapshot when the maintained index is stale.

        :param file_path: Explicit Python file selected by target discovery.
        :param project_roots: Allowed project roots for the fallback read.
        :param symbol_limit: Maximum declarations included in the snapshot.
        :param max_bytes: Maximum source file size accepted by the fallback.
        :return: File-and-symbol snapshot, or None when the boundary is unsafe.
        """

        try:
            path = Path(str(file_path or "")).resolve()
            roots = [Path(str(root)).resolve() for root in project_roots if str(root).strip()]
            if (
                path.suffix.lower() != ".py"
                or not path.is_file()
                or path.stat().st_size > max(1, int(max_bytes))
                or not any(path == root or root in path.parents for root in roots)
            ):
                return None
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, ValueError):
            return None

        symbols: list[dict[str, Any]] = []

        def visit(body: list[ast.stmt], parent: str = "", parent_kind: str = "") -> None:
            for node in body:
                if not isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                qualname = f"{parent}.{node.name}" if parent else node.name
                if isinstance(node, ast.ClassDef):
                    kind = "class"
                elif parent:
                    kind = "async_method" if isinstance(node, ast.AsyncFunctionDef) else "method"
                else:
                    kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                symbols.append(
                    {
                        "name": node.name,
                        "qualname": qualname,
                        "parent_qualname": parent,
                        "parent_kind": parent_kind,
                        "kind": kind,
                        "signature": "",
                        "docstring": ast.get_docstring(node) or "",
                        "start_line": int(node.lineno),
                        "end_line": int(node.end_lineno or node.lineno),
                        "source": ast.get_source_segment(source, node) or "",
                    }
                )
                if len(symbols) >= max(1, min(int(symbol_limit), 500)):
                    return
                if isinstance(node, ast.ClassDef):
                    visit(node.body, qualname, "class")

        visit(tree.body)
        imports: list[dict[str, Any]] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        {
                            "import_name": alias.name,
                            "module": alias.name,
                            "name": "",
                            "alias": alias.asname or "",
                            "level": 0,
                            "kind": "import",
                            "lineno": int(node.lineno),
                        }
                    )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append(
                        {
                            "import_name": alias.name,
                            "module": node.module or "",
                            "name": alias.name,
                            "alias": alias.asname or "",
                            "level": int(node.level),
                            "kind": "from",
                            "lineno": int(node.lineno),
                        }
                    )
        data = path.read_bytes()
        return {
            "root": str(next(root for root in roots if path == root or root in path.parents)),
            "path": str(path),
            "rel_path": "",
            "module": "",
            "ext": ".py",
            "size": len(data),
            "mtime": path.stat().st_mtime,
            "sha1": hashlib.sha1(data).hexdigest(),
            "indexed_at": "",
            "source_scope": "bounded_fallback",
            "symbols": symbols,
            "imports": imports[:200],
            "source": "bounded_filesystem_fallback",
        }

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
