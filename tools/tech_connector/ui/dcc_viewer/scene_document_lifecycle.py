"""Document dirty-state and recovery-path policy for the native DCC viewport."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import uuid


def default_recovery_directory() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return root / "TechConnector" / "Recovery"


@dataclass
class SceneDocumentLifecycle:
    recovery_directory: Path = field(default_factory=default_recovery_directory)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 0
    saved_revision: int = 0

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    def mark_dirty(self) -> None:
        self.revision += 1

    def mark_clean(self) -> None:
        self.saved_revision = self.revision

    def recovery_path(self, scene_path: str = "") -> Path:
        if scene_path:
            source = Path(scene_path).resolve()
            return source.with_name(f".{source.stem}.autosave.tcscene")
        return self.recovery_directory / f"Untitled-{self.session_id}.autosave.tcscene"

    def discover_untitled_recoveries(self) -> list[Path]:
        if not self.recovery_directory.is_dir():
            return []
        return sorted(
            self.recovery_directory.glob("Untitled-*.autosave.tcscene"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def remove_recovery(self, scene_path: str = "") -> None:
        path = self.recovery_path(scene_path)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
