"""Persistence layer for DCC local intelligence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .schema import DDL, INDEXES, SCHEMA_VERSION


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _norm_key(value: str) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class ProjectRef:
    id: int
    dcc: str
    name: str
    root_path: str


class IntelligenceStore:
    """Small SQLite wrapper intentionally kept dependency-free."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.apply_schema()

    def close(self) -> None:
        self.conn.close()

    def apply_schema(self) -> None:
        with self.conn:
            for statement in DDL:
                self.conn.execute(statement)
            for statement in INDEXES:
                self.conn.execute(statement)
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
                (SCHEMA_VERSION, "initial dcc local intelligence schema"),
            )

    def upsert_project(self, dcc: str, name: str, root_path: str | Path) -> ProjectRef:
        root = str(Path(root_path).resolve())
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO projects(dcc, name, root_path, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(root_path) DO UPDATE SET
                    dcc=excluded.dcc,
                    name=excluded.name,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (dcc, name, root),
            )
        row = self.conn.execute("SELECT * FROM projects WHERE root_path = ?", (root,)).fetchone()
        return ProjectRef(id=row["id"], dcc=row["dcc"], name=row["name"], root_path=row["root_path"])

    def upsert_asset(self, project_id: int, dcc: str, **data: Any) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO assets(project_id, dcc, asset_path, asset_name, asset_type, package_path,
                                   class_name, modified_at, size_bytes, content_hash, metadata_json, indexed_at)
                VALUES (:project_id, :dcc, :asset_path, :asset_name, :asset_type, :package_path,
                        :class_name, :modified_at, :size_bytes, :content_hash, :metadata_json, CURRENT_TIMESTAMP)
                ON CONFLICT(project_id, asset_path) DO UPDATE SET
                    dcc=excluded.dcc,
                    asset_name=excluded.asset_name,
                    asset_type=excluded.asset_type,
                    package_path=excluded.package_path,
                    class_name=excluded.class_name,
                    modified_at=excluded.modified_at,
                    size_bytes=excluded.size_bytes,
                    content_hash=excluded.content_hash,
                    metadata_json=excluded.metadata_json,
                    indexed_at=CURRENT_TIMESTAMP
                """,
                {
                    "project_id": project_id,
                    "dcc": dcc,
                    "asset_path": data["asset_path"],
                    "asset_name": data.get("asset_name") or Path(data["asset_path"]).name,
                    "asset_type": data.get("asset_type"),
                    "package_path": data.get("package_path"),
                    "class_name": data.get("class_name"),
                    "modified_at": data.get("modified_at"),
                    "size_bytes": data.get("size_bytes"),
                    "content_hash": data.get("content_hash"),
                    "metadata_json": _json(data.get("metadata", {})),
                },
            )

    def upsert_function(self, project_id: int, dcc: str, **data: Any) -> None:
        qn = data.get("qualified_name") or data["function_name"]
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO functions(project_id, dcc, function_name, qualified_name, source_path,
                                                 class_name, signature, docstring, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, dcc, data["function_name"], qn, data.get("source_path"), data.get("class_name"),
                 data.get("signature"), data.get("docstring"), _json(data.get("metadata", {}))),
            )

    def upsert_class(self, project_id: int, dcc: str, **data: Any) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO classes(project_id, dcc, class_name, module_name, source_path,
                                               base_class, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    dcc,
                    data["class_name"],
                    data.get("module_name"),
                    data.get("source_path"),
                    data.get("base_class"),
                    _json(data.get("metadata", {})),
                ),
            )

    def upsert_capability(self, project_id: int, dcc: str, **data: Any) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO capabilities(project_id, dcc, name, description, entrypoint, source_path,
                                         risk_level, input_schema_json, output_schema_json, tags_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, dcc, name) DO UPDATE SET
                    description=excluded.description,
                    entrypoint=excluded.entrypoint,
                    source_path=excluded.source_path,
                    risk_level=excluded.risk_level,
                    input_schema_json=excluded.input_schema_json,
                    output_schema_json=excluded.output_schema_json,
                    tags_json=excluded.tags_json,
                    metadata_json=excluded.metadata_json
                """,
                (project_id, dcc, data["name"], data.get("description", ""), data.get("entrypoint"),
                 data.get("source_path"), data.get("risk_level", "low"), _json(data.get("input_schema", {})),
                 _json(data.get("output_schema", {})), _json(data.get("tags", [])), _json(data.get("metadata", {}))),
            )

    def upsert_symbol(self, project_id: int, dcc: str, **data: Any) -> None:
        symbol_key = str(data["symbol_key"]).strip()
        source_ref = data.get("source_ref") or ""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO symbols(project_id, dcc, symbol_key, symbol_key_norm, symbol_kind,
                                    display_name, qualified_name, source_ref, summary, metadata_json, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(project_id, dcc, symbol_kind, symbol_key_norm, source_ref) DO UPDATE SET
                    symbol_key=excluded.symbol_key,
                    display_name=excluded.display_name,
                    qualified_name=excluded.qualified_name,
                    summary=excluded.summary,
                    metadata_json=excluded.metadata_json,
                    indexed_at=CURRENT_TIMESTAMP
                """,
                (
                    project_id,
                    dcc,
                    symbol_key,
                    _norm_key(symbol_key),
                    data.get("symbol_kind") or "unknown",
                    data.get("display_name"),
                    data.get("qualified_name"),
                    source_ref,
                    data.get("summary"),
                    _json(data.get("metadata", {})),
                ),
            )

    def upsert_python_api(self, project_id: int | None, dcc: str, **data: Any) -> None:
        qualified_name = str(data["qualified_name"]).strip()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO python_api(project_id, dcc, qualified_name, object_type,
                                       signature, docstring, source, tags_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, dcc, qualified_name) DO UPDATE SET
                    object_type=excluded.object_type,
                    signature=excluded.signature,
                    docstring=excluded.docstring,
                    source=excluded.source,
                    tags_json=excluded.tags_json,
                    metadata_json=excluded.metadata_json
                """,
                (
                    project_id,
                    dcc,
                    qualified_name,
                    data.get("object_type") or "unknown",
                    data.get("signature"),
                    data.get("docstring"),
                    data.get("source"),
                    _json(data.get("tags", [])),
                    _json(data.get("metadata", {})),
                ),
            )

    def add_dependency(self, project_id: int, dcc: str, **data: Any) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO dependencies(project_id, dcc, source_kind, source_ref, target_kind,
                                                   target_ref, relation, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, dcc, data["source_kind"], data["source_ref"], data["target_kind"],
                 data["target_ref"], data["relation"], _json(data.get("metadata", {}))),
            )

    def add_snapshot(self, project_id: int, dcc: str, **data: Any) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO editor_state_snapshots(project_id, dcc, snapshot_kind, selected_json, open_document,
                                                   active_level, loaded_assets_json, state_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, dcc, data.get("snapshot_kind", "manual"), _json(data.get("selected", [])),
                 data.get("open_document"), data.get("active_level"), _json(data.get("loaded_assets", [])),
                 _json(data.get("state", {}))),
            )
            return int(cur.lastrowid)

    def add_execution(self, project_id: int, dcc: str, **data: Any) -> int:
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO execution_history(project_id, dcc, request_text, action_name, target_ref, status,
                                              risk_level, summary, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, dcc, data["request_text"], data.get("action_name"), data.get("target_ref"),
                 data.get("status", "planned"), data.get("risk_level", "unknown"), data.get("summary"),
                 _json(data.get("result", {}))),
            )
            return int(cur.lastrowid)

    def latest_snapshot(self, project_id: int, dcc: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM editor_state_snapshots WHERE project_id=? AND dcc=? ORDER BY id DESC LIMIT 1",
            (project_id, dcc),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def search_assets(self, project_id: int, query: str, limit: int = 20) -> list[dict[str, Any]]:
        like = f"%{query}%"
        rows = self.conn.execute(
            """
            SELECT * FROM assets
            WHERE project_id=? AND (asset_name LIKE ? OR asset_path LIKE ? OR asset_type LIKE ? OR class_name LIKE ?)
            ORDER BY indexed_at DESC LIMIT ?
            """,
            (project_id, like, like, like, like, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_functions(self, project_id: int, query: str, limit: int = 20, dcc: str | None = None) -> list[dict[str, Any]]:
        like = f"%{query}%"
        if dcc:
            rows = self.conn.execute(
                """
                SELECT * FROM functions
                WHERE project_id=? AND dcc=? AND (function_name LIKE ? OR qualified_name LIKE ? OR docstring LIKE ?)
                LIMIT ?
                """,
                (project_id, dcc, like, like, like, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM functions
                WHERE project_id=? AND (function_name LIKE ? OR qualified_name LIKE ? OR docstring LIKE ?)
                LIMIT ?
                """,
                (project_id, like, like, like, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_python_api(self, project_id: int, dcc: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = _norm_key(query)
        like = f"%{q}%"
        rows = self.conn.execute(
            """
            SELECT * FROM python_api
            WHERE (project_id=? OR project_id IS NULL) AND dcc=? AND (
                lower(qualified_name) LIKE ? OR
                lower(COALESCE(object_type, '')) LIKE ? OR
                lower(COALESCE(signature, '')) LIKE ? OR
                lower(COALESCE(docstring, '')) LIKE ?
            )
            ORDER BY
                CASE WHEN lower(qualified_name) LIKE ? THEN 0 ELSE 1 END,
                length(qualified_name) ASC
            LIMIT ?
            """,
            (project_id, dcc, like, like, like, like, f"{q}%", limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_symbol(self, project_id: int, dcc: str, key: str, limit: int = 20) -> list[dict[str, Any]]:
        key_norm = _norm_key(key)
        rows = self.conn.execute(
            """
            SELECT * FROM symbols
            WHERE project_id=? AND dcc=? AND symbol_key_norm=?
            ORDER BY indexed_at DESC LIMIT ?
            """,
            (project_id, dcc, key_norm, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def prefix_symbols(self, project_id: int, dcc: str, prefix: str, limit: int = 20) -> list[dict[str, Any]]:
        prefix_norm = _norm_key(prefix)
        rows = self.conn.execute(
            """
            SELECT * FROM symbols
            WHERE project_id=? AND dcc=? AND symbol_key_norm LIKE ?
            ORDER BY symbol_key_norm ASC LIMIT ?
            """,
            (project_id, dcc, f"{prefix_norm}%", limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_symbols(self, project_id: int, dcc: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = _norm_key(query)
        prefix_rows = self.prefix_symbols(project_id, dcc, q, limit=limit)
        if len(prefix_rows) >= limit:
            return prefix_rows[:limit]
        like = f"%{q}%"
        rows = self.conn.execute(
            """
            SELECT * FROM symbols
            WHERE project_id=? AND dcc=? AND (
                symbol_key_norm LIKE ? OR
                lower(COALESCE(display_name, '')) LIKE ? OR
                lower(COALESCE(qualified_name, '')) LIKE ? OR
                lower(COALESCE(summary, '')) LIKE ?
            )
            ORDER BY
                CASE WHEN symbol_key_norm LIKE ? THEN 0 ELSE 1 END,
                indexed_at DESC
            LIMIT ?
            """,
            (project_id, dcc, like, like, like, like, f"{q}%", limit),
        ).fetchall()
        combined = prefix_rows + [self._row_to_dict(r) for r in rows]
        seen = set()
        unique = []
        for item in combined:
            marker = item.get("id") or (item.get("symbol_kind"), item.get("symbol_key_norm"), item.get("source_ref"))
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(item)
        return unique[:limit]

    def search_capabilities(self, project_id: int, query: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = [t for t in query.lower().replace("_", " ").split() if len(t) > 2]
        if not terms:
            terms = [query.lower()]
        rows = self.conn.execute("SELECT * FROM capabilities WHERE project_id=?", (project_id,)).fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            item = self._row_to_dict(row)
            haystack = " ".join(str(item.get(k, "")) for k in ("name", "description", "tags_json", "entrypoint")).lower()
            score = sum(1 for t in terms if t in haystack)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:limit]]

    def related_dependencies(self, project_id: int, refs: Iterable[str], limit: int = 50) -> list[dict[str, Any]]:
        refs = list(refs)
        if not refs:
            return []
        placeholders = ",".join("?" for _ in refs)
        rows = self.conn.execute(
            f"""
            SELECT * FROM dependencies
            WHERE project_id=? AND (source_ref IN ({placeholders}) OR target_ref IN ({placeholders}))
            LIMIT ?
            """,
            [project_id, *refs, *refs, limit],
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key, value in list(data.items()):
            if key.endswith("_json") and isinstance(value, str):
                try:
                    data[key[:-5]] = json.loads(value)
                except json.JSONDecodeError:
                    data[key[:-5]] = value
        return data
