"""Knowledge index process-lock recovery tests."""

from __future__ import annotations

import os
import sqlite3

from tech_connector.knowledge import build_knowledge_index_v2 as builder
from tech_connector.services import project_service


def test_build_lock_recovers_when_owner_process_is_gone(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "knowledge.build.lock"
    lock_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(builder, "LOCK_PATH", lock_path)
    monkeypatch.setattr(builder, "_process_is_alive", lambda _pid: False)

    assert builder.acquire_build_lock()
    assert lock_path.read_text(encoding="utf-8") == str(os.getpid())
    builder.release_build_lock()


def test_build_lock_does_not_replace_a_live_owner(tmp_path, monkeypatch) -> None:
    lock_path = tmp_path / "knowledge.build.lock"
    lock_path.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(builder, "LOCK_PATH", lock_path)
    monkeypatch.setattr(builder, "_process_is_alive", lambda _pid: True)

    assert not builder.acquire_build_lock()
    assert lock_path.read_text(encoding="utf-8") == "12345"


def test_stale_plan_ignores_rows_outside_requested_roots(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE files (
            root TEXT, path TEXT, rel_path TEXT, ext TEXT,
            size INTEGER, mtime REAL, sha1 TEXT, source_scope TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(tmp_path), str(outside), "outside.py", ".py", 0, 0.0, "old", "project"),
    )

    plan, missing, counts = builder.stale_file_plan(connection, [project_root])

    assert plan == []
    assert missing == []
    assert counts == {"indexed": 0, "changed": 0, "new": 0, "missing": 0}


def test_virtual_environments_are_excluded_from_index_scan(tmp_path) -> None:
    assert builder.should_skip(tmp_path / ".venv" / "Lib" / "site-packages" / "library.py")


def test_unchanged_content_refreshes_perforce_modified_time(tmp_path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE files (
            id INTEGER PRIMARY KEY, root TEXT, path TEXT, rel_path TEXT,
            module TEXT, ext TEXT, size INTEGER, mtime REAL, sha1 TEXT,
            indexed_at TEXT, source_scope TEXT
        )
        """
    )
    connection.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1, str(tmp_path), str(source), "module.py", "module", ".py",
            source.stat().st_size, 0.0, builder.file_hash(source), "old", "project",
        ),
    )
    monkeypatch.setattr(builder, "_file_needs_rich_index", lambda *_args: False)

    assert not builder.index_file(connection, tmp_path, source)
    stored_mtime = connection.execute("SELECT mtime FROM files WHERE id = 1").fetchone()[0]
    assert stored_mtime == source.stat().st_mtime


def test_exact_batches_defer_global_search_table_rebuilds(tmp_path, monkeypatch) -> None:
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(project_service, "_project_roots", lambda _path=None: [str(tmp_path)])

    command = project_service._exact_index_command(tmp_path / "build.py", [str(source)])
    finalize = project_service._exact_index_finalize_command(
        tmp_path / "build.py", [str(source)]
    )

    assert "--no-fts" in command
    assert "--no-symbol-lookup" in command
    assert "--graph-only" in finalize
    assert "--no-fts" not in finalize
