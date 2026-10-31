"""Small project-local editor history such as recent assets and levels."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


class EngineEditorState:
    def __init__(self, project_root: str | Path, *, limit: int = 15) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.path = self.project_root / ".tech_connector" / "editor_state.json"
        self.limit = max(3, int(limit))
        self.data = self._read()

    @property
    def recent_assets(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.data.get("recent_assets") or () if str(value))

    @property
    def recent_levels(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.data.get("recent_levels") or () if str(value))

    def touch_asset(self, asset_id: str) -> None:
        self._touch("recent_assets", str(asset_id))

    def touch_level(self, path: str | Path) -> None:
        self._touch("recent_levels", str(Path(path).expanduser().resolve()))

    def clear_recent(self) -> None:
        self.data["recent_assets"] = []
        self.data["recent_levels"] = []
        self._write()

    def _touch(self, key: str, value: str) -> None:
        if not value: return
        rows = [str(item) for item in self.data.get(key) or () if str(item) != value]
        self.data[key] = [value, *rows][:self.limit]
        self._write()

    def _read(self) -> dict:
        if not self.path.is_file(): return {"schema": "tech_connector.engine_editor_state.v1"}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(payload) if isinstance(payload, dict) else {"schema": "tech_connector.engine_editor_state.v1"}
        except (OSError, json.JSONDecodeError):
            return {"schema": "tech_connector.engine_editor_state.v1"}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["schema"] = "tech_connector.engine_editor_state.v1"
        handle, temporary_name = tempfile.mkstemp(prefix=".editor_state.", suffix=".tmp", dir=str(self.path.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(self.data, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["EngineEditorState"]
