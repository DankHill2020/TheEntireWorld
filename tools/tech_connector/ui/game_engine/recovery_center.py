"""Recovery-copy discovery and restore UI for engine documents."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import AssetDatabase
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene
from tech_connector.ui.dcc_viewer.scene_document_lifecycle import default_recovery_directory


class EngineRecoveryCenter(QWidget):
    openSceneRequested = Signal(str)
    openAssetRequested = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, project_root: str | Path, parent=None, *, database: AssetDatabase | None = None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Autosave & Recovery", self); title.setStyleSheet("font-size:15px; font-weight:700;")
        heading.addWidget(title); heading.addStretch(1)
        refresh = QPushButton("Refresh", self); refresh.clicked.connect(self.refresh); heading.addWidget(refresh)
        root.addLayout(heading)
        explanation = QLabel(
            "Recovery copies are separate from saved source files. Restore one to inspect it, then use Save As to keep it.", self,
        )
        explanation.setWordWrap(True); root.addWidget(explanation)
        self.tree = QTreeWidget(self)
        self.tree.setAccessibleName("Recoverable engine documents")
        self.tree.setHeaderLabels(["Document", "Kind", "Recovery state", "Modified", "Recovery location"])
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.tree, 1)
        actions = QHBoxLayout()
        self.compare_button = QPushButton("Compare with Saved", self); self.compare_button.clicked.connect(self.compare_selected); actions.addWidget(self.compare_button)
        self.restore_button = QPushButton("Restore Selected", self); self.restore_button.clicked.connect(self.restore_selected); actions.addWidget(self.restore_button)
        self.discard_button = QPushButton("Discard Recovery…", self); self.discard_button.clicked.connect(self.discard_selected); actions.addWidget(self.discard_button)
        actions.addStretch(1); root.addLayout(actions)
        self.comparison = QPlainTextEdit(self); self.comparison.setReadOnly(True); self.comparison.setMaximumHeight(180); self.comparison.setPlaceholderText("Select a recovery copy, then compare it with the last saved version."); self.comparison.setAccessibleName("Recovery comparison details"); root.addWidget(self.comparison)
        self.summary = QLabel(self); root.addWidget(self.summary)
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        paths: set[Path] = set()
        paths.update(self.project_root.rglob(".*.autosave.tcscene"))
        recovery_root = default_recovery_directory()
        if recovery_root.is_dir(): paths.update(recovery_root.glob("Untitled-*.autosave.tcscene"))
        asset_root = self.project_root / ".tech_connector" / "recovery" / "assets"
        if asset_root.is_dir(): paths.update(asset_root.glob("*.json"))
        for path in sorted(paths, key=lambda candidate: candidate.stat().st_mtime, reverse=True):
            kind = "Level" if path.suffix.casefold() == ".tcscene" else "Asset"
            identifier = ""
            label = path.name
            payload: dict[str, Any] = {}
            if kind == "Asset":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8")); identifier = str(payload.get("asset_id") or ""); label = identifier or path.stem
                except (OSError, json.JSONDecodeError): pass
            source = self._saved_source(path, kind, identifier)
            compatible = not (kind == "Asset" and source is not None and payload.get("source_hash") and self.database is not None and (self.database.asset(identifier) is not None and payload.get("source_hash") != self.database.asset(identifier).content_hash))
            newer = source is None or path.stat().st_mtime_ns > source.stat().st_mtime_ns
            state = "Unsaved recovery" if source is None else "Saved asset changed" if not compatible else "Newer than saved" if newer else "Older than saved"
            data = {"path": str(path), "kind": kind, "asset_id": identifier, "source": str(source or ""), "compatible": compatible, "actionable": bool(newer and compatible)}
            item = QTreeWidgetItem([label, kind, state, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)), str(path)])
            item.setData(0, Qt.UserRole, data)
            self.tree.addTopLevelItem(item)
        actionable = sum(bool((self.tree.topLevelItem(index).data(0, Qt.UserRole) or {}).get("actionable")) for index in range(self.tree.topLevelItemCount()))
        self.summary.setText(f"{self.tree.topLevelItemCount()} recovery cop{'y' if self.tree.topLevelItemCount() == 1 else 'ies'} available • {actionable} newer and restorable")
        self.comparison.clear()
        self._selection_changed()

    def _saved_source(self, recovery: Path, kind: str, asset_id: str) -> Path | None:
        if kind == "Asset" and self.database is not None:
            record = self.database.asset(asset_id)
            return record.source_path if record is not None and record.source_path.is_file() else None
        name = recovery.name
        if kind == "Level" and name.startswith(".") and name.endswith(".autosave.tcscene"):
            candidate = recovery.with_name(name[1:-len(".autosave.tcscene")] + ".tcscene")
            return candidate if candidate.is_file() else None
        return None

    def has_actionable_recoveries(self, *, project_only: bool = False) -> bool:
        for index in range(self.tree.topLevelItemCount()):
            data = dict(self.tree.topLevelItem(index).data(0, Qt.UserRole) or {})
            if not data.get("actionable"): continue
            if project_only and data.get("kind") == "Level" and not data.get("source"): continue
            return True
        return False

    def compare_selected(self) -> dict[str, Any]:
        data = self._selected()
        if not data: return {}
        recovery = Path(data["path"]); source = Path(data["source"]) if data.get("source") else None
        result: dict[str, Any] = {"kind": data["kind"], "recovery": str(recovery), "saved": str(source or ""), "compatible": bool(data.get("compatible", True)), "changed_sections": []}
        try:
            if data["kind"] == "Asset":
                recovered = dict(json.loads(recovery.read_text(encoding="utf-8")).get("values") or {})
                authored = json.loads(source.read_text(encoding="utf-8")) if source is not None else {}
                saved = dict(authored.get("properties") or authored) if isinstance(authored, dict) else {}
            else:
                recovered_document, _ = load_federated_scene(recovery); recovered = recovered_document.to_dict()
                if source is not None:
                    saved_document, _ = load_federated_scene(source); saved = saved_document.to_dict()
                else: saved = {}
            result["changed_sections"] = sorted(key for key in set(saved) | set(recovered) if saved.get(key) != recovered.get(key))
        except (OSError, ValueError, json.JSONDecodeError):
            result["changed_sections"] = ["Binary/archive content"] if source is None or source.read_bytes() != recovery.read_bytes() else []
        freshness = "newer" if data.get("actionable") else "not newer"
        compatibility = "compatible" if data.get("compatible", True) else "CONFLICT — the saved asset changed after this recovery was written"
        sections = ", ".join(result["changed_sections"]) or "No authored sections differ"
        self.comparison.setPlainText(f"Recovery: {recovery}\nSaved: {source or 'No saved source'}\nState: {freshness}; {compatibility}\nChanged: {sections}")
        return result

    def restore_selected(self) -> bool:
        data = self._selected()
        if not data or not data.get("compatible", True): return False
        if data["kind"] == "Level": self.openSceneRequested.emit(data["path"])
        elif data.get("asset_id"): self.openAssetRequested.emit(data["asset_id"])
        else: return False
        self.statusMessage.emit(f"Opened recovery copy for {Path(data['path']).name}. Save explicitly to keep it.")
        return True

    def discard_selected(self) -> bool:
        data = self._selected()
        if not data: return False
        answer = QMessageBox.question(self, "Discard Recovery Copy", f"Delete this recovery copy?\n{data['path']}", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes: return False
        try: Path(data["path"]).unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Could not discard recovery", str(exc)); return False
        self.statusMessage.emit("Discarded the selected recovery copy; the saved source was not changed.")
        self.refresh(); return True

    def _selected(self) -> dict:
        item = self.tree.currentItem()
        return dict(item.data(0, Qt.UserRole) or {}) if item is not None else {}

    def _selection_changed(self) -> None:
        data = self._selected()
        self.compare_button.setEnabled(bool(data))
        self.restore_button.setEnabled(bool(data and data.get("compatible", True) and (data.get("kind") == "Level" or data.get("asset_id"))))
        self.discard_button.setEnabled(bool(data))


__all__ = ["EngineRecoveryCenter"]
