"""Fast project symbol lookup backed by the maintained SQLite index."""

from __future__ import annotations

from contextlib import contextmanager
from bisect import bisect_left
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any

from reasoning_runtime import SymbolHit, SymbolLookupProvider, SymbolQuery
from tech_connector.models.constants import project_index_db_path


_CACHE_LOCK = threading.Lock()
_SYMBOL_CACHES: dict[str, "_SymbolHotCache"] = {}


def _query_terms(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    terms = [
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+|_", spaced)
        if len(token) >= 2
    ]
    compact = re.sub(r"[^A-Za-z0-9]+", "", text).lower()
    if compact and compact not in terms:
        terms.insert(0, compact)
    lowered = text.lower()
    if lowered and lowered not in terms:
        terms.insert(0, lowered)
    return list(dict.fromkeys(terms))[:8]


def _active_path_bonus(active_path: str, path: str) -> float:
    if not active_path or not path:
        return 0.0
    active_norm = str(active_path).replace("\\", "/").lower().rstrip("/")
    path_norm = str(path).replace("\\", "/").lower().rstrip("/")
    if active_norm == path_norm:
        return 20.0
    active_dir = active_norm.rsplit("/", 1)[0] if "." in active_norm.rsplit("/", 1)[-1] else active_norm
    path_dir = path_norm.rsplit("/", 1)[0] if "/" in path_norm else ""
    if active_dir and path_dir == active_dir:
        return 10.0
    if active_dir and path_norm.startswith(active_dir.rstrip("/") + "/"):
        return 5.0
    return 0.0


class TechConnectorSymbolLookupProvider(SymbolLookupProvider):
    """Fast deterministic symbol lookup for a Tech Connector project index."""

    name = "tech_connector_symbol_lookup"

    def __init__(self, project_root: str | None = None, db_path: str | Path | None = None) -> None:
        self.project_root = str(project_root or "")
        self.db_path = Path(db_path) if db_path else project_index_db_path(project_root)

    @contextmanager
    def _connect(self):
        if not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        uri = self.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, timeout=10, uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.row_factory = sqlite3.Row
            yield conn
        finally:
            conn.close()

    def find_symbols(self, query: SymbolQuery) -> list[SymbolHit]:
        terms = _query_terms(query.query)
        if not terms:
            return []
        cached = _cached_symbol_rows(self.db_path, query, terms)
        if cached is not None:
            return _rank_rows(cached, query)[: max(1, int(query.limit or 50))]
        try:
            with self._connect() as conn:
                if not _table_exists(conn, "symbol_lookup"):
                    return self._fallback_find_symbols(conn, query, terms)
                rows = self._lookup_rows(conn, query, terms)
        except Exception:
            return []
        return _rank_rows(rows, query)[: max(1, int(query.limit or 50))]

    def _lookup_rows(self, conn: sqlite3.Connection, query: SymbolQuery, terms: list[str]) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for term in terms:
            clauses.append("sl.key = ?")
            params.append(term)
            clauses.append("sl.key LIKE ?")
            params.append(f"{term}%")
        where = ["(" + " OR ".join(clauses) + ")"]
        if query.kind:
            where.append("lower(s.kind) = ?")
            params.append(query.kind.lower())
        if query.scope and query.scope not in {"all", "*"}:
            where.append("COALESCE(f.source_scope, 'project') = ?")
            params.append(query.scope)
        limit = max(10, min(int(query.limit or 50) * 8, 600))
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
                s.id AS symbol_id,
                s.name,
                s.qualname,
                s.kind,
                s.start_line,
                s.end_line,
                f.path,
                f.rel_path,
                COALESCE(f.source_scope, 'project') AS source_scope,
                MAX(sl.weight) AS lookup_weight,
                GROUP_CONCAT(DISTINCT sl.match_kind) AS match_kinds
            FROM symbol_lookup sl
            JOIN symbols s ON s.id = sl.symbol_id
            JOIN files f ON f.id = s.file_id
            WHERE {" AND ".join(where)}
            GROUP BY s.id
            ORDER BY lookup_weight DESC, length(s.qualname), s.name
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]

    def _fallback_find_symbols(
        self,
        conn: sqlite3.Connection,
        query: SymbolQuery,
        terms: list[str],
    ) -> list[SymbolHit]:
        params: list[Any] = []
        clauses: list[str] = []
        for term in terms:
            like = f"%{term}%"
            clauses.append("(lower(s.name) LIKE ? OR lower(s.qualname) LIKE ?)")
            params.extend([like, like])
        where = ["(" + " OR ".join(clauses) + ")"]
        if query.kind:
            where.append("lower(s.kind) = ?")
            params.append(query.kind.lower())
        if query.scope and query.scope not in {"all", "*"}:
            where.append("COALESCE(f.source_scope, 'project') = ?")
            params.append(query.scope)
        params.append(max(10, min(int(query.limit or 50) * 8, 600)))
        rows = conn.execute(
            f"""
            SELECT
                s.id AS symbol_id,
                s.name,
                s.qualname,
                s.kind,
                s.start_line,
                s.end_line,
                f.path,
                f.rel_path,
                COALESCE(f.source_scope, 'project') AS source_scope,
                35.0 AS lookup_weight,
                'fallback_like' AS match_kinds
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE {" AND ".join(where)}
            ORDER BY length(s.qualname), s.name
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return _rank_rows([dict(row) for row in rows], query)[: max(1, int(query.limit or 50))]

    def read_symbol(self, symbol_id: int) -> dict[str, Any]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT s.*, f.path, f.rel_path, f.source_scope
                    FROM symbols s
                    JOIN files f ON f.id = s.file_id
                    WHERE s.id = ?
                    LIMIT 1
                    """,
                    (int(symbol_id),),
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}

    def status(self) -> dict[str, Any]:
        exists = self.db_path.exists()
        lookup_rows = 0
        hot_cache = False
        if exists:
            try:
                with self._connect() as conn:
                    if _table_exists(conn, "symbol_lookup"):
                        lookup_rows = int(conn.execute("SELECT COUNT(*) FROM symbol_lookup").fetchone()[0])
            except Exception:
                lookup_rows = 0
        with _CACHE_LOCK:
            hot_cache = str(self.db_path.resolve()) in _SYMBOL_CACHES if exists else False
        return {
            "ok": exists,
            "provider": self.name,
            "db_path": str(self.db_path),
            "symbol_lookup_rows": lookup_rows,
            "hot_cache": hot_cache,
        }


def find_symbols(
    query: str,
    *,
    project_root: str | None = None,
    limit: int = 50,
    kind: str = "",
    scope: str = "project",
    active_path: str = "",
) -> list[SymbolHit]:
    provider = TechConnectorSymbolLookupProvider(project_root=project_root)
    return provider.find_symbols(
        SymbolQuery(query=query, limit=limit, kind=kind, scope=scope, active_path=active_path)
    )


def _rank_rows(rows: list[dict[str, Any]], query: SymbolQuery) -> list[SymbolHit]:
    lowered = str(query.query or "").lower()
    hits: list[SymbolHit] = []
    for row in rows:
        name = str(row.get("name") or "")
        qualname = str(row.get("qualname") or "")
        path = str(row.get("path") or "")
        score = float(row.get("lookup_weight") or 0.0)
        if name.lower() == lowered:
            score += 50.0
        elif name.lower().startswith(lowered):
            score += 25.0
        elif lowered and lowered in name.lower():
            score += 10.0
        if row.get("source_scope") == "project":
            score += 5.0
        score += _active_path_bonus(query.active_path, path)
        hits.append(
            SymbolHit(
                symbol_id=int(row.get("symbol_id") or 0),
                name=name,
                qualname=qualname,
                kind=str(row.get("kind") or ""),
                path=path,
                rel_path=str(row.get("rel_path") or ""),
                start_line=int(row.get("start_line") or 0),
                end_line=int(row.get("end_line") or 0),
                score=score,
                source_scope=str(row.get("source_scope") or "project"),
                metadata={"match_kinds": str(row.get("match_kinds") or "")},
            )
        )
    return sorted(hits, key=lambda item: (-item.score, item.rel_path, item.qualname))


class _SymbolHotCache:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.mtime_ns = db_path.stat().st_mtime_ns
        self.exact: dict[str, list[dict[str, Any]]] = {}
        self.keys: list[str] = []
        self._load()

    def _load(self) -> None:
        uri = self.db_path.resolve().as_uri() + "?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, timeout=30, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    sl.key,
                    sl.match_kind,
                    sl.weight AS lookup_weight,
                    s.id AS symbol_id,
                    s.name,
                    s.qualname,
                    s.kind,
                    s.start_line,
                    s.end_line,
                    f.path,
                    f.rel_path,
                    COALESCE(f.source_scope, 'project') AS source_scope
                FROM symbol_lookup sl
                JOIN symbols s ON s.id = sl.symbol_id
                JOIN files f ON f.id = s.file_id
                """
            ).fetchall()
        finally:
            conn.close()
        exact: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            key = str(item.get("key") or "")
            if not key:
                continue
            item["match_kinds"] = item.get("match_kind") or ""
            exact.setdefault(key, []).append(item)
        self.exact = exact
        self.keys = sorted(exact)

    def find(self, query: SymbolQuery, terms: list[str]) -> list[dict[str, Any]]:
        row_by_symbol: dict[int, dict[str, Any]] = {}
        max_rows = max(40, min(int(query.limit or 50) * 12, 700))
        for term in terms:
            for row in self.exact.get(term, []):
                self._add_row(row_by_symbol, row)
            for key in self._prefix_keys(term):
                for row in self.exact.get(key, []):
                    self._add_row(row_by_symbol, row)
                    if len(row_by_symbol) >= max_rows:
                        break
                if len(row_by_symbol) >= max_rows:
                    break
        rows = list(row_by_symbol.values())
        if query.kind:
            wanted = query.kind.lower()
            rows = [row for row in rows if str(row.get("kind") or "").lower() == wanted]
        if query.scope and query.scope not in {"all", "*"}:
            rows = [row for row in rows if str(row.get("source_scope") or "project") == query.scope]
        return rows

    def _prefix_keys(self, prefix: str) -> list[str]:
        if not prefix:
            return []
        start = bisect_left(self.keys, prefix)
        matches: list[str] = []
        for key in self.keys[start:start + 500]:
            if not key.startswith(prefix):
                break
            if key != prefix:
                matches.append(key)
        return matches

    @staticmethod
    def _add_row(row_by_symbol: dict[int, dict[str, Any]], row: dict[str, Any]) -> None:
        symbol_id = int(row.get("symbol_id") or 0)
        if not symbol_id:
            return
        existing = row_by_symbol.get(symbol_id)
        if existing is None:
            row_by_symbol[symbol_id] = dict(row)
            return
        if float(row.get("lookup_weight") or 0.0) > float(existing.get("lookup_weight") or 0.0):
            existing.update(row)
        kinds = {item for item in str(existing.get("match_kinds") or "").split(",") if item}
        kinds.update(item for item in str(row.get("match_kinds") or row.get("match_kind") or "").split(",") if item)
        existing["match_kinds"] = ",".join(sorted(kinds))


def _cached_symbol_rows(db_path: Path, query: SymbolQuery, terms: list[str]) -> list[dict[str, Any]] | None:
    try:
        resolved = db_path.resolve()
        mtime_ns = resolved.stat().st_mtime_ns
    except Exception:
        return None
    key = str(resolved)
    with _CACHE_LOCK:
        cache = _SYMBOL_CACHES.get(key)
        if cache is None or cache.mtime_ns != mtime_ns:
            try:
                cache = _SymbolHotCache(resolved)
            except Exception:
                return None
            _SYMBOL_CACHES[key] = cache
    return cache.find(query, terms)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)
