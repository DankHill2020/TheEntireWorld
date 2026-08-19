"""Persistent asset database with dependency-aware derived-data invalidation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Iterable, Iterator


SCHEMA_VERSION = 1
_HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    source_path: Path
    asset_type: str
    content_hash: str
    size: int
    modified_ns: int
    revision: int
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class AssetChange:
    sequence: int
    kind: str
    asset_id: str
    affected_assets: tuple[str, ...]
    previous_hash: str = ""
    content_hash: str = ""


@dataclass(frozen=True)
class DerivedArtifact:
    asset_id: str
    key: str
    source_hash: str
    content_hash: str
    path: Path
    metadata: dict[str, Any]


def stable_asset_id(asset_type: str, source_path: str | Path) -> str:
    canonical = _canonical_path(source_path)
    digest = hashlib.sha256(f"{asset_type.casefold()}\0{canonical}".encode("utf-8")).hexdigest()[:24]
    return f"tc.asset.{digest}"


class AssetDatabase:
    """Owns canonical source identities and every artifact derived from them."""

    def __init__(self, database_path: str | Path, cache_root: str | Path | None = None) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.cache_root = (
            Path(cache_root).expanduser().resolve()
            if cache_root is not None
            else self.database_path.parent / "derived_data"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize_schema()

    def register_asset(
        self,
        source_path: str | Path,
        asset_type: str,
        *,
        asset_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        dependencies: Iterable[str | tuple[str, str]] = (),
    ) -> AssetRecord:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        canonical = _canonical_path(source)
        resolved_id = str(asset_id or stable_asset_id(asset_type, source))
        stat = source.stat()
        content_hash = _file_hash(source)
        metadata_json = _json(metadata or {})
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT content_hash, revision FROM assets WHERE asset_id = ?", (resolved_id,)
            ).fetchone()
            revision = int(existing[1]) + int(existing[0] != content_hash) if existing else 1
            connection.execute(
                """
                INSERT INTO assets(asset_id, source_path, asset_type, content_hash, size, modified_ns,
                                   revision, status, metadata_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, 'ready', ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    source_path=excluded.source_path, asset_type=excluded.asset_type,
                    content_hash=excluded.content_hash, size=excluded.size,
                    modified_ns=excluded.modified_ns, revision=excluded.revision,
                    status='ready', metadata_json=excluded.metadata_json
                """,
                (resolved_id, canonical, str(asset_type), content_hash, stat.st_size, stat.st_mtime_ns, revision, metadata_json),
            )
            self._append_event(connection, "registered" if existing is None else "reindexed", resolved_id, {"hash": content_hash})
        if dependencies:
            self.set_dependencies(resolved_id, dependencies)
        record = self.asset(resolved_id)
        if record is None:
            raise RuntimeError(f"Asset registration did not persist: {resolved_id}")
        return record

    def asset(self, asset_id: str) -> AssetRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM assets WHERE asset_id = ?", (str(asset_id),)).fetchone()
        return _asset_record(row) if row else None

    def asset_for_path(self, source_path: str | Path) -> AssetRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE source_path = ?", (_canonical_path(source_path),)
            ).fetchone()
        return _asset_record(row) if row else None

    def list_assets(self, *, status: str | None = None) -> list[AssetRecord]:
        with self._connect() as connection:
            if status is None:
                rows = connection.execute("SELECT * FROM assets ORDER BY asset_id").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM assets WHERE status = ? ORDER BY asset_id", (str(status),)
                ).fetchall()
        return [_asset_record(row) for row in rows]

    def set_dependencies(self, asset_id: str, dependencies: Iterable[str | tuple[str, str]]) -> None:
        owner = str(asset_id)
        normalized = [
            (str(value[0]), str(value[1])) if isinstance(value, tuple) else (str(value), "source")
            for value in dependencies
        ]
        if any(dependency == owner for dependency, _kind in normalized):
            raise ValueError("An asset cannot depend on itself.")
        with self._transaction() as connection:
            known = {
                row[0]
                for row in connection.execute(
                    "SELECT asset_id FROM assets WHERE asset_id IN ({})".format(
                        ",".join("?" for _item in [owner, *normalized])
                    ),
                    (owner, *(item[0] for item in normalized)),
                )
            } if normalized else {row[0] for row in connection.execute("SELECT asset_id FROM assets WHERE asset_id = ?", (owner,))}
            missing = sorted({owner, *(item[0] for item in normalized)} - known)
            if missing:
                raise KeyError("Unknown asset dependency IDs: " + ", ".join(missing))
            connection.execute("DELETE FROM dependencies WHERE asset_id = ?", (owner,))
            connection.executemany(
                "INSERT INTO dependencies(asset_id, dependency_id, kind) VALUES(?, ?, ?)",
                ((owner, dependency, kind) for dependency, kind in normalized),
            )
            if owner in self._dependency_closure(connection, [dependency for dependency, _kind in normalized]):
                raise ValueError(f"Asset dependency cycle detected at {owner}.")
            self._append_event(connection, "dependencies_changed", owner, {"dependencies": normalized})

    def dependencies(self, asset_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT dependency_id FROM dependencies WHERE asset_id = ? ORDER BY dependency_id", (str(asset_id),)
            ).fetchall()
        return tuple(row[0] for row in rows)

    def dependency_closure(self, asset_ids: Iterable[str]) -> tuple[str, ...]:
        with self._connect() as connection:
            return tuple(sorted(self._dependency_closure(connection, [str(value) for value in asset_ids])))

    def affected_assets(self, asset_ids: Iterable[str]) -> tuple[str, ...]:
        pending = list(dict.fromkeys(str(value) for value in asset_ids))
        affected = set(pending)
        with self._connect() as connection:
            while pending:
                current = pending.pop()
                rows = connection.execute(
                    "SELECT asset_id FROM dependencies WHERE dependency_id = ?", (current,)
                ).fetchall()
                for row in rows:
                    if row[0] not in affected:
                        affected.add(row[0])
                        pending.append(row[0])
        return tuple(sorted(affected))

    def scan_changes(self) -> list[AssetChange]:
        changes: list[AssetChange] = []
        for record in self.list_assets():
            source = record.source_path
            if not source.is_file():
                if record.status != "missing":
                    changes.append(self._record_change(record, "missing", ""))
                continue
            stat = source.stat()
            if stat.st_size == record.size and stat.st_mtime_ns == record.modified_ns and record.status == "ready":
                continue
            current_hash = _file_hash(source)
            kind = "restored" if record.status == "missing" else "changed"
            if current_hash == record.content_hash and record.status == "ready":
                with self._transaction() as connection:
                    connection.execute(
                        "UPDATE assets SET size = ?, modified_ns = ? WHERE asset_id = ?",
                        (stat.st_size, stat.st_mtime_ns, record.asset_id),
                    )
                continue
            changes.append(self._record_change(record, kind, current_hash, stat=stat))
        return changes

    def store_derived(
        self,
        asset_id: str,
        key: str,
        payload: bytes,
        *,
        metadata: dict[str, Any] | None = None,
        extension: str = ".bin",
    ) -> DerivedArtifact:
        source = self.asset(asset_id)
        if source is None or source.status != "ready":
            raise KeyError(f"Cannot derive an unavailable asset: {asset_id}")
        artifact_hash = hashlib.sha256(payload).hexdigest()
        suffix = extension if extension.startswith(".") else f".{extension}"
        destination = self.cache_root / artifact_hash[:2] / f"{artifact_hash}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO derived_artifacts(asset_id, artifact_key, source_hash, content_hash, path, metadata_json, valid)
                VALUES(?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(asset_id, artifact_key) DO UPDATE SET
                    source_hash=excluded.source_hash, content_hash=excluded.content_hash,
                    path=excluded.path, metadata_json=excluded.metadata_json, valid=1
                """,
                (source.asset_id, str(key), source.content_hash, artifact_hash, str(destination), _json(metadata or {})),
            )
            self._append_event(connection, "derived_ready", source.asset_id, {"key": key, "hash": artifact_hash})
        result = self.derived(asset_id, key)
        if result is None:
            raise RuntimeError("Derived artifact did not persist.")
        return result

    def derived(self, asset_id: str, key: str) -> DerivedArtifact | None:
        source = self.asset(asset_id)
        if source is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """SELECT asset_id, artifact_key, source_hash, content_hash, path, metadata_json, valid
                   FROM derived_artifacts WHERE asset_id = ? AND artifact_key = ?""",
                (str(asset_id), str(key)),
            ).fetchone()
        if row is None or not row[6] or row[2] != source.content_hash or not Path(row[4]).is_file():
            return None
        return DerivedArtifact(row[0], row[1], row[2], row[3], Path(row[4]), _dict(row[5]))

    def poll_events(self, after_sequence: int = 0, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence, kind, asset_id, created_ns, payload_json FROM events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (max(0, int(after_sequence)), max(1, min(10000, int(limit)))),
            ).fetchall()
        return [
            {"sequence": row[0], "kind": row[1], "asset_id": row[2], "created_ns": row[3], "payload": _dict(row[4])}
            for row in rows
        ]

    def _record_change(
        self,
        record: AssetRecord,
        kind: str,
        content_hash: str,
        *,
        stat: os.stat_result | None = None,
    ) -> AssetChange:
        affected = self.affected_assets([record.asset_id])
        with self._transaction() as connection:
            connection.execute(
                """UPDATE assets SET content_hash = ?, size = ?, modified_ns = ?, revision = revision + 1,
                                     status = ? WHERE asset_id = ?""",
                (
                    content_hash,
                    int(stat.st_size) if stat else 0,
                    int(stat.st_mtime_ns) if stat else 0,
                    "ready" if content_hash else "missing",
                    record.asset_id,
                ),
            )
            connection.executemany(
                "UPDATE derived_artifacts SET valid = 0 WHERE asset_id = ?", ((asset_id,) for asset_id in affected)
            )
            sequence = self._append_event(
                connection,
                kind,
                record.asset_id,
                {"previous_hash": record.content_hash, "content_hash": content_hash, "affected_assets": affected},
            )
        return AssetChange(sequence, kind, record.asset_id, affected, record.content_hash, content_hash)

    @staticmethod
    def _dependency_closure(connection: sqlite3.Connection, roots: Iterable[str]) -> set[str]:
        closure = set(str(value) for value in roots)
        pending = list(closure)
        while pending:
            current = pending.pop()
            rows = connection.execute(
                "SELECT dependency_id FROM dependencies WHERE asset_id = ?", (current,)
            ).fetchall()
            for row in rows:
                if row[0] not in closure:
                    closure.add(row[0])
                    pending.append(row[0])
        return closure

    def _initialize_schema(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_info(version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(
                    asset_id TEXT PRIMARY KEY, source_path TEXT NOT NULL UNIQUE, asset_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
                    revision INTEGER NOT NULL, status TEXT NOT NULL, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dependencies(
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                    dependency_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE RESTRICT,
                    kind TEXT NOT NULL, PRIMARY KEY(asset_id, dependency_id)
                );
                CREATE INDEX IF NOT EXISTS dependencies_reverse ON dependencies(dependency_id);
                CREATE TABLE IF NOT EXISTS derived_artifacts(
                    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                    artifact_key TEXT NOT NULL, source_hash TEXT NOT NULL, content_hash TEXT NOT NULL,
                    path TEXT NOT NULL, metadata_json TEXT NOT NULL, valid INTEGER NOT NULL,
                    PRIMARY KEY(asset_id, artifact_key)
                );
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, asset_id TEXT NOT NULL,
                    created_ns INTEGER NOT NULL, payload_json TEXT NOT NULL
                );
                """
            )
            row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_info(version) VALUES(?)", (SCHEMA_VERSION,))
            elif int(row[0]) != SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported TC asset database schema: {row[0]}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _transaction(self) -> Iterator[sqlite3.Connection]:
        return _DatabaseTransaction(self)

    @staticmethod
    def _append_event(connection: sqlite3.Connection, kind: str, asset_id: str, payload: dict[str, Any]) -> int:
        cursor = connection.execute(
            "INSERT INTO events(kind, asset_id, created_ns, payload_json) VALUES(?, ?, ?, ?)",
            (str(kind), str(asset_id), time.time_ns(), _json(payload)),
        )
        return int(cursor.lastrowid)


class _DatabaseTransaction:
    def __init__(self, owner: AssetDatabase) -> None:
        self.owner = owner
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self.owner._write_lock.acquire()
        self.connection = self.owner._connect()
        self.connection.execute("BEGIN IMMEDIATE")
        return self.connection

    def __exit__(self, exception_type: Any, exception: Any, traceback: Any) -> None:
        assert self.connection is not None
        try:
            self.connection.rollback() if exception_type else self.connection.commit()
        finally:
            self.connection.close()
            self.owner._write_lock.release()


class AssetWatchService:
    """Polls source metadata off the UI thread and emits dependency-closed changes."""

    def __init__(
        self,
        database: AssetDatabase,
        callback: Callable[[list[AssetChange]], None],
        *,
        interval_seconds: float = 0.5,
    ) -> None:
        self.database = database
        self.callback = callback
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tc-asset-watch", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, float(timeout)))
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                changes = self.database.scan_changes()
                if changes:
                    self.callback(changes)
                self.last_error = None
            except Exception as exc:
                self.last_error = exc


def _canonical_path(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _dict(value: str) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return dict(parsed) if isinstance(parsed, dict) else {}


def _asset_record(row: sqlite3.Row) -> AssetRecord:
    return AssetRecord(
        row["asset_id"], Path(row["source_path"]), row["asset_type"], row["content_hash"],
        int(row["size"]), int(row["modified_ns"]), int(row["revision"]), row["status"],
        _dict(row["metadata_json"]),
    )
