"""Undo/redo and crash-recovery state for dedicated asset editors."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any


RECOVERY_SCHEMA = "tech_connector.asset_editor_recovery.v1"


@dataclass(frozen=True)
class AssetEditorSnapshot:
    label: str
    values: dict[str, Any]
    created_ns: int


class AssetEditorSession:
    def __init__(self, project_root: str | Path, *, history_limit: int = 80) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.history_limit = max(2, int(history_limit))
        self.asset_id = ""
        self.source_hash = ""
        self._history: list[AssetEditorSnapshot] = []
        self._cursor = -1
        self.saved_cursor = -1

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._cursor < len(self._history) - 1

    @property
    def dirty(self) -> bool:
        return self._cursor != self.saved_cursor

    @property
    def undo_label(self) -> str:
        return self._history[self._cursor].label if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return self._history[self._cursor + 1].label if self.can_redo else ""

    def begin(self, asset_id: str, source_hash: str, values: dict[str, Any]) -> dict[str, Any] | None:
        self.asset_id = str(asset_id)
        self.source_hash = str(source_hash)
        snapshot = AssetEditorSnapshot("Open Asset", deepcopy(values), time.time_ns())
        self._history = [snapshot]
        self._cursor = 0
        self.saved_cursor = 0
        recovery = self.read_recovery()
        if recovery is None:
            return None
        recovered = dict(recovery.get("values") or {})
        if recovered == values:
            self.clear_recovery()
            return None
        self.record(recovered, "Recover Autosave")
        return deepcopy(recovered)

    def record(self, values: dict[str, Any], label: str) -> bool:
        current = self._history[self._cursor].values if self._cursor >= 0 else None
        if current == values:
            return False
        del self._history[self._cursor + 1:]
        self._history.append(AssetEditorSnapshot(str(label), deepcopy(values), time.time_ns()))
        if len(self._history) > self.history_limit:
            removed = len(self._history) - self.history_limit
            del self._history[:removed]
            self.saved_cursor = max(-1, self.saved_cursor - removed)
        self._cursor = len(self._history) - 1
        return True

    def undo(self) -> dict[str, Any] | None:
        if not self.can_undo:
            return None
        self._cursor -= 1
        return deepcopy(self._history[self._cursor].values)

    def redo(self) -> dict[str, Any] | None:
        if not self.can_redo:
            return None
        self._cursor += 1
        return deepcopy(self._history[self._cursor].values)

    def mark_saved(self, values: dict[str, Any]) -> None:
        self.record(values, "Save Asset")
        self.saved_cursor = self._cursor
        self.clear_recovery()

    def write_recovery(self, values: dict[str, Any]) -> Path | None:
        if not self.asset_id or not self.dirty:
            if self.asset_id:
                self.clear_recovery()
            return None
        path = self.recovery_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": RECOVERY_SCHEMA,
            "asset_id": self.asset_id,
            "source_hash": self.source_hash,
            "created_ns": time.time_ns(),
            "values": deepcopy(values),
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path

    def read_recovery(self) -> dict[str, Any] | None:
        path = self.recovery_path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != RECOVERY_SCHEMA
            or payload.get("asset_id") != self.asset_id
            or payload.get("source_hash") != self.source_hash
        ):
            return None
        return payload

    def clear_recovery(self) -> None:
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def recovery_path(self) -> Path:
        safe_id = self.asset_id.replace(":", "_").replace("/", "_").replace("\\", "_") or "unbound"
        return self.project_root / ".tech_connector" / "recovery" / "assets" / f"{safe_id}.json"
