"""Persistent Content Browser collections, search, import queue, and lifecycle views."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Iterable, Mapping

from .asset_database_service import AssetDatabase, AssetRecord
from .asset_operations_service import AssetImportCancelled, AssetOperationsService
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry


CONTENT_BROWSER_STATE_SCHEMA = "tech_connector.content_browser_state.v1"
IMPORT_QUEUE_SCHEMA = "tech_connector.asset_import_queue.v1"
SEARCH_FIELDS = ("name", "type", "family", "path", "status", "state", "cook", "vcs", "tag", "collection", "rev", "size")


@dataclass(frozen=True)
class AssetCollection:
    name: str
    kind: str = "static"
    asset_ids: tuple[str, ...] = ()
    query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "asset_ids": list(self.asset_ids), "query": self.query}


@dataclass
class ImportQueueItem:
    queue_id: str
    source_path: str
    folder: str
    type_id: str = ""
    status: str = "queued"
    progress: int = 0
    message: str = "Waiting"
    asset_id: str = ""
    created_ns: int = 0
    importer_settings: dict[str, Any] | None = None
    conflict_policy: str = "rename"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssetImportQueue:
    """Recoverable FIFO import queue with pending-item cancellation and retry."""

    def __init__(self, project_root: str | Path, operations: AssetOperationsService) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.operations = operations
        self.state_path = self.project_root / ".tech_connector" / "import_queue.json"
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._items = self._load()

    def items(self) -> tuple[ImportQueueItem, ...]:
        with self._lock:
            return tuple(ImportQueueItem(**item.to_dict()) for item in self._items)

    def enqueue(
        self, source_paths: Iterable[str | Path], *, folder: str = "Assets", type_id: str = "",
        importer_settings: Mapping[str, Any] | None = None, conflict_policy: str = "rename",
    ) -> tuple[ImportQueueItem, ...]:
        with self._lock:
            created = []
            for source_path in source_paths:
                source = Path(source_path).expanduser().resolve()
                item = ImportQueueItem(
                    queue_id=f"import-{uuid.uuid4().hex}", source_path=str(source),
                    folder=str(folder or "Assets"), type_id=str(type_id or ""), created_ns=time.time_ns(),
                    importer_settings=dict(importer_settings or {}), conflict_policy=str(conflict_policy or "rename"),
                )
                self._items.append(item)
                created.append(item)
            self._save()
            return tuple(ImportQueueItem(**item.to_dict()) for item in created)

    def cancel(self, queue_id: str) -> bool:
        with self._lock:
            item = self._find(queue_id)
            if item is None or item.status not in {"queued", "failed", "processing"}:
                return False
            if item.status == "processing":
                event = self._cancel_events.get(item.queue_id)
                if event is None:
                    return False
                event.set()
                item.message = "Cancelling safely…"
            else:
                item.status = "cancelled"
                item.progress = 0
                item.message = "Cancelled"
            self._save()
            return True

    def retry(self, queue_id: str) -> bool:
        with self._lock:
            item = self._find(queue_id)
            if item is None or item.status not in {"failed", "cancelled"}:
                return False
            item.status = "queued"
            item.progress = 0
            item.message = "Waiting"
            item.asset_id = ""
            self._save()
            return True

    def process_next(self) -> ImportQueueItem | None:
        with self._lock:
            item = next((candidate for candidate in self._items if candidate.status == "queued"), None)
            if item is None:
                return None
            item.status = "processing"
            item.progress = 1
            item.message = "Inspecting source"
            cancellation_event = threading.Event()
            self._cancel_events[item.queue_id] = cancellation_event
            self._save()

        def progress(completed: int, total: int) -> None:
            with self._lock:
                item.progress = min(99, max(1, int(completed * 100 / max(1, total))))
                item.message = f"Copying source data — {item.progress}%"
                self._save()

        try:
            receipt = self.operations.import_asset(
                item.source_path, folder=item.folder, type_id=item.type_id,
                importer_settings=item.importer_settings, conflict_policy=item.conflict_policy,
                cancellation_event=cancellation_event, progress_callback=progress,
            )
            item.asset_id = receipt.asset_id
            item.status = "complete"
            item.progress = 100
            item.message = receipt.message
        except AssetImportCancelled as exc:
            item.status = "cancelled"
            item.progress = 0
            item.message = str(exc)
        except Exception as exc:
            item.status = "failed"
            item.progress = 0
            item.message = str(exc)
        finally:
            with self._lock:
                self._cancel_events.pop(item.queue_id, None)
                self._save()
        return ImportQueueItem(**item.to_dict())

    def process_all(self) -> tuple[ImportQueueItem, ...]:
        processed = []
        while any(item.status == "queued" for item in self._items):
            item = self.process_next()
            if item is not None:
                processed.append(item)
        return tuple(processed)

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if item.status in {"queued", "processing"}]
            self._save()
            return before - len(self._items)

    def _find(self, queue_id: str) -> ImportQueueItem | None:
        return next((item for item in self._items if item.queue_id == str(queue_id)), None)

    def _load(self) -> list[ImportQueueItem]:
        if not self.state_path.is_file():
            return []
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = []
        for value in payload.get("items") or ():
            if not isinstance(value, dict):
                continue
            allowed = {key: value[key] for key in ImportQueueItem.__dataclass_fields__ if key in value}
            try:
                item = ImportQueueItem(**allowed)
            except TypeError:
                continue
            if item.status == "processing":
                item.status = "queued"
                item.progress = 0
                item.message = "Recovered after the previous editor session"
            rows.append(item)
        return rows

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.state_path, {"schema": IMPORT_QUEUE_SCHEMA, "items": [item.to_dict() for item in self._items]})


class ContentBrowserLifecycleService:
    """Project-scoped state shared by the Content Browser UI and Python API."""

    def __init__(
        self, project_root: str | Path, database: AssetDatabase, registry: AssetTypeRegistry | None = None,
        operations: AssetOperationsService | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self.operations = operations or AssetOperationsService(self.project_root, database, self.registry)
        self.state_path = self.project_root / ".tech_connector" / "content_browser.json"
        self.import_queue = AssetImportQueue(self.project_root, self.operations)

    def collections(self) -> tuple[AssetCollection, ...]:
        payload = self._read_state()
        rows = []
        for value in payload.get("collections") or ():
            if not isinstance(value, dict) or not str(value.get("name") or "").strip():
                continue
            rows.append(AssetCollection(
                name=str(value["name"]), kind="dynamic" if value.get("kind") == "dynamic" else "static",
                asset_ids=tuple(dict.fromkeys(str(item) for item in value.get("asset_ids") or () if str(item))),
                query=str(value.get("query") or ""),
            ))
        return tuple(sorted(rows, key=lambda item: item.name.casefold()))

    def save_collection(
        self, name: str, *, asset_ids: Iterable[str] = (), query: str = "", kind: str = "static",
    ) -> AssetCollection:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Collection name cannot be empty.")
        resolved_kind = "dynamic" if str(kind).casefold() == "dynamic" else "static"
        collection = AssetCollection(
            clean_name, resolved_kind,
            tuple(dict.fromkeys(str(value) for value in asset_ids if self.database.asset(str(value)) is not None)),
            str(query or "").strip(),
        )
        if resolved_kind == "dynamic" and not collection.query:
            raise ValueError("A dynamic collection requires a search query.")
        rows = [item for item in self.collections() if item.name.casefold() != clean_name.casefold()]
        rows.append(collection)
        self._write_collections(rows)
        return collection

    def delete_collection(self, name: str) -> bool:
        rows = list(self.collections())
        retained = [item for item in rows if item.name.casefold() != str(name).casefold()]
        if len(retained) == len(rows):
            return False
        self._write_collections(retained)
        return True

    def add_to_collection(self, name: str, asset_ids: Iterable[str]) -> AssetCollection:
        current = self.collection(name)
        if current is None:
            return self.save_collection(name, asset_ids=asset_ids)
        if current.kind != "static":
            raise ValueError("Assets cannot be manually added to a dynamic collection.")
        return self.save_collection(current.name, asset_ids=(*current.asset_ids, *asset_ids))

    def remove_from_collection(self, name: str, asset_ids: Iterable[str]) -> AssetCollection:
        current = self.collection(name)
        if current is None:
            raise KeyError(f"Unknown collection: {name}")
        if current.kind != "static":
            raise ValueError("Assets cannot be manually removed from a dynamic collection.")
        removed = {str(value) for value in asset_ids}
        return self.save_collection(current.name, asset_ids=(value for value in current.asset_ids if value not in removed))

    def collection(self, name: str) -> AssetCollection | None:
        return next((item for item in self.collections() if item.name.casefold() == str(name).casefold()), None)

    def collection_asset_ids(self, name: str, documents: Iterable[Mapping[str, Any]] = ()) -> tuple[str, ...]:
        collection = self.collection(name)
        if collection is None:
            return ()
        if collection.kind == "static":
            return tuple(value for value in collection.asset_ids if self.database.asset(value) is not None)
        return tuple(
            str(document.get("asset_id") or "") for document in documents
            if str(document.get("asset_id") or "") and self.matches(document, collection.query)
        )

    def collection_matches(self, name: str, document: Mapping[str, Any]) -> bool:
        collection = self.collection(name)
        if collection is None:
            return False
        if collection.kind == "dynamic":
            return self.matches(document, collection.query)
        return str(document.get("asset_id") or "") in collection.asset_ids

    def asset_document(
        self, path: str | Path, type_id: str, asset_id: str = "", *,
        source_control: str = "not_queried", collections: Iterable[str] = (),
        cooked: bool | None = None,
    ) -> dict[str, Any]:
        source = Path(path).expanduser().resolve()
        record = self.database.asset(asset_id) if asset_id else None
        descriptor = self.registry.descriptor(type_id)
        imported = bool(record and record.metadata.get("import_source"))
        state = "source" if record is None else ("imported" if imported else "authored")
        is_cooked = bool(record and self.database.derived_artifacts(record.asset_id)) if cooked is None else bool(cooked)
        tags = tuple(str(value) for value in (record.metadata.get("tags") or ()) if str(value)) if record else ()
        try:
            relative = source.relative_to(self.project_root).as_posix()
        except ValueError:
            relative = str(source)
        return {
            "asset_id": record.asset_id if record else "", "name": source.name,
            "path": relative, "absolute_path": str(source), "type": type_id,
            "display_type": descriptor.display_name if descriptor else type_id,
            "family": descriptor.family if descriptor else "Unregistered",
            "status": record.status if record else "source", "state": state,
            "state_label": {"source": "Source File", "imported": "Imported Asset", "authored": "Authored Asset"}[state],
            "cook": "cooked" if is_cooked else ("not_applicable" if record is None else "uncooked"),
            "cook_label": "Cooked" if is_cooked else ("—" if record is None else "Needs Cook"),
            "revision": record.revision if record else 0, "size": source.stat().st_size if source.is_file() else 0,
            "vcs": str(source_control or "not_queried"), "tags": tags,
            "collections": tuple(str(value) for value in collections),
            "instance_note": "Instances are level-local placements and are shown in the World Outliner, not as duplicate assets.",
        }

    def matches(self, document: Mapping[str, Any], query: str) -> bool:
        return self.matches_compiled(document, self.compile_query(query))

    @staticmethod
    def compile_query(query: str) -> tuple[tuple[str, bool], ...]:
        try:
            tokens = shlex.split(str(query or ""))
        except ValueError:
            tokens = str(query or "").split()
        return tuple(
            (raw_token[1:] if raw_token.startswith("-") else raw_token, raw_token.startswith("-"))
            for raw_token in tokens if raw_token
        )

    def matches_compiled(
        self, document: Mapping[str, Any], terms: Iterable[tuple[str, bool]],
    ) -> bool:
        for token, negated in terms:
            result = self._token_matches(document, token)
            if result == negated:
                return False
        return True

    def search_help(self) -> dict[str, Any]:
        return {
            "fields": SEARCH_FIELDS,
            "examples": ("type:tc.texture hero", "family:Animation state:authored", "cook:uncooked rev>=2", "-status:missing path:Assets/Characters"),
            "negation": "Prefix any term with '-' to exclude it.",
        }

    def revision_history(self, asset_id: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
        return self.database.asset_events(asset_id, limit=limit)

    def source_control_snapshot(
        self, paths: Iterable[str | Path], *, runner: Callable[..., Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        resolved = [str(Path(path).expanduser().resolve()) for path in paths]
        result = {path: {"provider": "perforce", "status": "not_in_depot", "head_revision": 0, "have_revision": 0, "change": ""} for path in resolved}
        executable = shutil.which("p4")
        if runner is None and not executable:
            return {path: {**value, "status": "unavailable", "provider": "none"} for path, value in result.items()}
        command = [executable or "p4", "-ztag", "fstat", "-T", "clientFile,depotFile,headRev,haveRev,action,change,otherOpen", *resolved]
        try:
            completed = (runner or subprocess.run)(
                command, capture_output=True, text=True, timeout=8, check=False,
            )
            output = str(getattr(completed, "stdout", "") or "")
        except Exception as exc:
            return {path: {**value, "status": "error", "message": str(exc)} for path, value in result.items()}
        current: dict[str, str] = {}
        rows: list[dict[str, str]] = []
        for line in output.splitlines():
            match = re.match(r"^\.\.\.\s+(\S+)\s*(.*)$", line.strip())
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if key == "clientFile" and current:
                rows.append(current); current = {}
            current[key] = value
        if current:
            rows.append(current)
        by_casefold = {path.casefold(): path for path in resolved}
        for row in rows:
            client_path = str(Path(row.get("clientFile") or "").resolve())
            key = by_casefold.get(client_path.casefold())
            if not key:
                continue
            action = row.get("action") or ""
            head, have = int(row.get("headRev") or 0), int(row.get("haveRev") or 0)
            status = "checked_out" if action else ("opened_elsewhere" if row.get("otherOpen") else ("out_of_date" if head > have else "synced"))
            result[key] = {
                "provider": "perforce", "status": status, "head_revision": head,
                "have_revision": have, "change": row.get("change") or "", "depot_path": row.get("depotFile") or "",
            }
        return result

    def perforce_history(
        self, path: str | Path, *, limit: int = 25, runner: Callable[..., Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return depot revision history for one asset without modifying the workspace."""

        completed = self._run_p4(
            ["-ztag", "filelog", "-m", str(max(1, min(250, int(limit)))), str(Path(path).resolve())],
            runner=runner,
        )
        indexed: dict[int, dict[str, Any]] = {}
        depot_path = ""
        for line in str(getattr(completed, "stdout", "") or "").splitlines():
            match = re.match(r"^\.\.\.\s+(\S+)\s*(.*)$", line.strip())
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if key == "depotFile":
                depot_path = value
                continue
            field = re.match(r"^(rev|change|action|type|time|user|client|desc)(\d+)$", key)
            if field:
                row = indexed.setdefault(int(field.group(2)), {"depot_path": depot_path})
                row[field.group(1)] = int(value) if field.group(1) in {"rev", "change", "time"} and value.isdigit() else value
        return tuple(indexed[index] for index in sorted(indexed))

    def perforce_changelists(
        self, *, status: str = "pending", limit: int = 50,
        runner: Callable[..., Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """List recent pending or submitted changelists visible to the current client."""

        resolved_status = "submitted" if str(status).casefold() == "submitted" else "pending"
        completed = self._run_p4(
            ["-ztag", "changes", "-s", resolved_status, "-m", str(max(1, min(250, int(limit))))],
            runner=runner,
        )
        rows: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in str(getattr(completed, "stdout", "") or "").splitlines():
            match = re.match(r"^\.\.\.\s+(\S+)\s*(.*)$", line.strip())
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if key == "change" and current:
                rows.append(current); current = {}
            current[key] = int(value) if key in {"change", "time"} and value.isdigit() else value
        if current:
            rows.append(current)
        return tuple(rows)

    def perforce_action(
        self, paths: Iterable[str | Path], action: str, *, changelist: str = "",
        confirmed: bool = False, runner: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Run an explicit Perforce workspace action after caller confirmation."""

        operation = str(action).casefold()
        if operation not in {"edit", "add", "revert", "sync"}:
            raise ValueError(f"Unsupported Perforce action: {action}")
        if not confirmed:
            raise PermissionError("Perforce workspace actions require explicit confirmation.")
        resolved_paths = [str(Path(path).expanduser().resolve()) for path in paths]
        arguments = [operation]
        if changelist and operation in {"edit", "add", "reopen"}:
            arguments.extend(["-c", str(changelist)])
        arguments.extend(resolved_paths)
        completed = self._run_p4(arguments, runner=runner)
        return {
            "schema": "tech_connector.perforce_action.v1", "action": operation,
            "paths": tuple(resolved_paths), "changelist": str(changelist or ""),
            "returncode": int(getattr(completed, "returncode", 0) or 0),
            "stdout": str(getattr(completed, "stdout", "") or "").strip(),
            "stderr": str(getattr(completed, "stderr", "") or "").strip(),
        }

    def reference_health(self) -> dict[str, Any]:
        redirectors = self.operations.redirector_report()
        return {
            "redirectors": redirectors,
            "valid_redirectors": sum(1 for row in redirectors if row["valid"]),
            "stale_redirectors": sum(1 for row in redirectors if not row["valid"]),
        }

    @staticmethod
    def _run_p4(arguments: list[str], *, runner: Callable[..., Any] | None = None) -> Any:
        executable = shutil.which("p4")
        if runner is None and not executable:
            raise FileNotFoundError("Perforce CLI 'p4' is unavailable.")
        return (runner or subprocess.run)(
            [executable or "p4", *arguments], capture_output=True, text=True, timeout=12, check=False,
        )

    def _token_matches(self, document: Mapping[str, Any], token: str) -> bool:
        numeric = re.match(r"^(rev|size)(>=|<=|>|<|=)(\d+)$", token, re.IGNORECASE)
        if numeric:
            numeric_key = "revision" if numeric.group(1).casefold() == "rev" else "size"
            actual = int(document.get(numeric_key) or 0)
            expected = int(numeric.group(3)); operator = numeric.group(2)
            return {">": actual > expected, "<": actual < expected, ">=": actual >= expected,
                    "<=": actual <= expected, "=": actual == expected}[operator]
        if ":" in token:
            field, value = token.split(":", 1)
            field, wanted = field.casefold(), value.casefold()
            aliases = {"type": "type", "rev": "revision"}
            key = aliases.get(field, field)
            if field not in SEARCH_FIELDS:
                return False
            actual = document.get(key, "")
            if isinstance(actual, (list, tuple, set)):
                return any(wanted in str(item).casefold() for item in actual)
            if field in {"status", "state", "cook", "vcs"}:
                return wanted == str(actual).casefold()
            return wanted in str(actual).casefold()
        haystack = " ".join(str(document.get(key) or "") for key in ("name", "display_type", "type", "family", "path", "status", "state", "cook", "tags"))
        return token.casefold() in haystack.casefold()

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"schema": CONTENT_BROWSER_STATE_SCHEMA, "collections": []}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema": CONTENT_BROWSER_STATE_SCHEMA, "collections": []}
        return dict(value) if isinstance(value, dict) else {"schema": CONTENT_BROWSER_STATE_SCHEMA, "collections": []}

    def _write_collections(self, collections: Iterable[AssetCollection]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.state_path, {
            "schema": CONTENT_BROWSER_STATE_SCHEMA,
            "collections": [item.to_dict() for item in sorted(collections, key=lambda row: row.name.casefold())],
        })


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


__all__ = [
    "AssetCollection", "AssetImportQueue", "ContentBrowserLifecycleService", "ImportQueueItem",
    "CONTENT_BROWSER_STATE_SCHEMA", "IMPORT_QUEUE_SCHEMA", "SEARCH_FIELDS",
]
