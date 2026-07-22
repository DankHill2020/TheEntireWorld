"""Compact repository map built from the existing knowledge index."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class RepoMap:
    root: str
    file_count: int = 0
    symbol_count: int = 0
    directories: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    important_files: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "symbol_count": self.symbol_count,
            "directories": list(self.directories),
            "important_files": list(self.important_files),
        }


def build_repo_map(
    *,
    project_root: str | None = None,
    scope: str = "project",
    max_dirs: int = 18,
    max_files: int = 24,
) -> dict[str, Any]:
    """Summarize indexed files/symbols without walking disk or invoking a model."""

    try:
        from tech_connector.models.constants import TOOLS_ROOT, project_index_db_path
    except Exception:
        return RepoMap(root=project_root or "", directories=(), important_files=()).to_dict()
    root = _resolve_root(project_root, default_root=TOOLS_ROOT)
    if not project_index_db_path().exists():
        return RepoMap(root=str(root), directories=(), important_files=()).to_dict()
    try:
        with sqlite3.connect(str(project_index_db_path()), timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            scope_sql, scope_params = _scope_filter(scope)
            root_sql = ""
            params: list[Any] = list(scope_params)
            if root:
                root_sql = " AND f.path LIKE ?"
                params.append(str(root) + "%")
            files = conn.execute(
                f"""
                SELECT f.path, COUNT(s.id) AS symbol_count
                FROM files f
                LEFT JOIN symbols s ON s.file_id = f.id
                WHERE 1=1 {scope_sql} {root_sql}
                GROUP BY f.id
                ORDER BY symbol_count DESC, f.path
                LIMIT ?
                """,
                [*params, max(1, int(max_files) * 3)],
            ).fetchall()
            total = conn.execute(
                f"""
                SELECT COUNT(DISTINCT f.id) AS file_count, COUNT(s.id) AS symbol_count
                FROM files f
                LEFT JOIN symbols s ON s.file_id = f.id
                WHERE 1=1 {scope_sql} {root_sql}
                """,
                params,
            ).fetchone()
    except Exception:
        return RepoMap(root=str(root), directories=(), important_files=()).to_dict()

    dir_counts: dict[str, dict[str, Any]] = {}
    important: list[dict[str, Any]] = []
    for row in files:
        path = str(row["path"] or "")
        rel = _relative_path(path, root)
        directory = _top_directory(rel)
        bucket = dir_counts.setdefault(directory, {"path": directory, "files": 0, "symbols": 0})
        bucket["files"] += 1
        bucket["symbols"] += int(row["symbol_count"] or 0)
        if len(important) < max_files:
            important.append(
                {
                    "path": path,
                    "rel_path": rel,
                    "symbols": int(row["symbol_count"] or 0),
                }
            )
    directories = sorted(dir_counts.values(), key=lambda item: (-int(item["symbols"]), item["path"]))[:max_dirs]
    return RepoMap(
        root=str(root),
        file_count=int((total or {})["file_count"] or 0),
        symbol_count=int((total or {})["symbol_count"] or 0),
        directories=tuple(directories),
        important_files=tuple(important),
    ).to_dict()


def render_repo_map(repo_map: dict[str, Any] | None) -> str:
    repo_map = dict(repo_map or {})
    lines = [
        "Repo map:",
        f"Root: {repo_map.get('root') or '(unknown)'}",
        f"Indexed files: {repo_map.get('file_count', 0)}",
        f"Indexed symbols: {repo_map.get('symbol_count', 0)}",
    ]
    directories = list(repo_map.get("directories") or [])
    if directories:
        lines.append("Top indexed areas:")
        for item in directories[:10]:
            lines.append(f"- {item.get('path')}: {item.get('files')} files, {item.get('symbols')} symbols")
    important = list(repo_map.get("important_files") or [])
    if important:
        lines.append("High-signal files:")
        for item in important[:8]:
            lines.append(f"- {item.get('rel_path') or item.get('path')} ({item.get('symbols')} symbols)")
    return "\n".join(lines)


def _resolve_root(project_root: str | None, *, default_root: Path) -> Path:
    try:
        return Path(project_root).expanduser().resolve() if project_root else default_root.resolve()
    except Exception:
        return default_root


def _scope_filter(scope: str) -> tuple[str, tuple[Any, ...]]:
    value = (scope or "project").lower()
    if value in {"all", "everything"}:
        return "", ()
    if value in {"maya", "dcc"}:
        return " AND COALESCE(f.source_scope, 'project') IN (?, ?, ?)", ("project", "external_tools", "maya")
    if value in {"unreal"}:
        return " AND COALESCE(f.source_scope, 'project') IN (?, ?, ?)", ("project", "external_tools", "unreal_engine")
    return " AND COALESCE(f.source_scope, 'project') IN (?, ?)", ("project", "external_tools")


def _relative_path(path: str, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except Exception:
        return path


def _top_directory(rel_path: str) -> str:
    parts = Path(rel_path).parts
    if not parts:
        return "."
    if len(parts) == 1:
        return "."
    return parts[0]
