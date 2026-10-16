"""Persistent background-task surface shared by engine tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class EngineTaskCenter(QWidget):
    """Tracks active and recent work without blocking the editor."""

    cancelRequested = Signal(str)
    pauseRequested = Signal(str)
    resumeRequested = Signal(str)
    retryRequested = Signal(str)
    openAssetRequested = Signal(str)
    revealRequested = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, project_root: str | Path, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.state_path = self.project_root / ".tech_connector" / "editor_tasks.json"
        self.tasks: dict[str, dict[str, Any]] = {}
        self._load()
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Background Tasks", self)
        title.setStyleSheet("font-size:15px; font-weight:700;")
        heading.addWidget(title)
        heading.addStretch(1)
        clear = QPushButton("Clear Finished", self)
        clear.clicked.connect(self.clear_finished)
        heading.addWidget(clear)
        root.addLayout(heading)
        self.summary = QLabel("No background work", self)
        self.summary.setAccessibleName("Background task summary")
        root.addWidget(self.summary)
        self.tree = QTreeWidget(self)
        self.tree.setAccessibleName("Engine background tasks")
        self.tree.setHeaderLabels(["Task", "State", "Progress", "Message"])
        self.tree.itemSelectionChanged.connect(self._show_details)
        root.addWidget(self.tree, 1)
        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.cancel_selected)
        actions.addWidget(self.cancel_button)
        self.pause_button = QPushButton("Pause", self)
        self.pause_button.clicked.connect(self.pause_or_resume_selected)
        actions.addWidget(self.pause_button)
        self.retry_button = QPushButton("Retry", self)
        self.retry_button.clicked.connect(self.retry_selected)
        actions.addWidget(self.retry_button)
        self.open_asset_button = QPushButton("Open Asset", self)
        self.open_asset_button.clicked.connect(self.open_selected_asset)
        actions.addWidget(self.open_asset_button)
        self.reveal_button = QPushButton("Reveal Location", self)
        self.reveal_button.clicked.connect(self.reveal_selected_location)
        actions.addWidget(self.reveal_button)
        actions.addStretch(1)
        root.addLayout(actions)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.setPlaceholderText("Select a task for details.")
        root.addWidget(self.details)
        self.refresh()

    def begin(
        self, task_id: str, label: str, *, category: str = "engine",
        can_cancel: bool = False, can_pause: bool = False, can_retry: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        identifier = str(task_id)
        self.tasks[identifier] = {
            "task_id": identifier, "label": str(label), "category": str(category),
            "state": "running", "progress": 0, "message": "Starting…",
            "can_cancel": bool(can_cancel), "can_pause": bool(can_pause), "can_retry": bool(can_retry),
            "metadata": dict(metadata or {}), "started_ns": time.time_ns(), "updated_ns": time.time_ns(),
        }
        self._commit()

    def update(
        self, task_id: str, *, progress: int | None = None, message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        task = self.tasks.get(str(task_id))
        if task is None:
            return
        if progress is not None:
            task["progress"] = max(0, min(100, int(progress)))
        if message:
            task["message"] = str(message)
        if metadata:
            task["metadata"] = {**dict(task.get("metadata") or {}), **dict(metadata)}
        task["updated_ns"] = time.time_ns()
        self._commit()

    def finish(self, task_id: str, *, state: str = "complete", message: str = "") -> None:
        task = self.tasks.get(str(task_id))
        if task is None:
            return
        task["state"] = str(state)
        task["progress"] = 100 if state == "complete" else int(task.get("progress", 0))
        task["message"] = str(message or task.get("message") or state.title())
        task["can_cancel"] = False
        task["can_pause"] = False
        task["can_retry"] = state in {"failed", "canceled", "interrupted"} or bool(task.get("can_retry"))
        task["updated_ns"] = time.time_ns()
        self._commit()

    def apply_event(self, event: object) -> None:
        data = dict(event) if isinstance(event, dict) else {}
        operation = str(data.get("operation") or "update")
        task_id = str(data.get("task_id") or "")
        if not task_id:
            return
        if operation == "begin":
            self.begin(
                task_id, str(data.get("label") or task_id), category=str(data.get("category") or "engine"),
                can_cancel=bool(data.get("can_cancel")), can_pause=bool(data.get("can_pause")), can_retry=bool(data.get("can_retry")),
                metadata=dict(data.get("metadata") or {}),
            )
        elif operation == "finish":
            self.update(task_id, metadata=dict(data.get("metadata") or {}))
            self.finish(task_id, state=str(data.get("state") or "complete"), message=str(data.get("message") or ""))
        else:
            self.update(task_id, progress=data.get("progress"), message=str(data.get("message") or ""), metadata=dict(data.get("metadata") or {}))

    def cancel_selected(self) -> None:
        task = self._selected_task()
        if task and task.get("state") == "running" and task.get("can_cancel"):
            self.cancelRequested.emit(str(task["task_id"]))
            self.update(str(task["task_id"]), message="Cancellation requested — finishing the current safe stage…")

    def retry_selected(self) -> None:
        task = self._selected_task()
        if task and task.get("can_retry") and task.get("state") != "running":
            self.retryRequested.emit(str(task["task_id"]))

    def pause_or_resume_selected(self) -> None:
        task = self._selected_task()
        if not task: return
        task_id = str(task["task_id"])
        if task.get("state") == "running" and task.get("can_pause"):
            self.pauseRequested.emit(task_id)
            self.update(task_id, message="Pause requested — finishing the current safe stage…")
        elif task.get("state") == "paused":
            self.resumeRequested.emit(task_id)

    def open_selected_asset(self) -> None:
        task = self._selected_task(); metadata = dict(task.get("metadata") or {}) if task else {}
        asset_id = str(metadata.get("asset_id") or metadata.get("scene_asset_id") or "")
        if asset_id: self.openAssetRequested.emit(asset_id)

    def reveal_selected_location(self) -> None:
        task = self._selected_task(); metadata = dict(task.get("metadata") or {}) if task else {}
        path = str(metadata.get("output") or metadata.get("path") or metadata.get("scene") or "")
        if path: self.revealRequested.emit(path)

    def clear_finished(self) -> None:
        self.tasks = {key: task for key, task in self.tasks.items() if task.get("state") in {"running", "paused"}}
        self._commit()

    def refresh(self) -> None:
        selected_id = str((self._selected_task() or {}).get("task_id") or "") if hasattr(self, "tree") else ""
        self.tree.clear()
        ordered = sorted(self.tasks.values(), key=lambda task: int(task.get("updated_ns", 0)), reverse=True)
        for task in ordered:
            progress = int(task.get("progress", 0))
            item = QTreeWidgetItem([
                str(task.get("label") or task.get("task_id") or "Task"),
                str(task.get("state") or "unknown").replace("_", " ").title(),
                f"{progress}%", str(task.get("message") or ""),
            ])
            item.setData(0, Qt.UserRole, str(task.get("task_id") or ""))
            item.setToolTip(3, str(task.get("message") or ""))
            self.tree.addTopLevelItem(item)
            if str(task.get("task_id") or "") == selected_id:
                self.tree.setCurrentItem(item)
        running = sum(task.get("state") == "running" for task in ordered)
        paused = sum(task.get("state") == "paused" for task in ordered)
        failed = sum(task.get("state") in {"failed", "interrupted"} for task in ordered)
        self.summary.setText(
            f"{running} running • {paused} paused • {failed} need attention • {len(ordered)} recent"
            if ordered else "No background work"
        )
        self._show_details()

    def _selected_task(self) -> dict[str, Any] | None:
        item = self.tree.currentItem() if hasattr(self, "tree") else None
        return self.tasks.get(str(item.data(0, Qt.UserRole) or "")) if item is not None else None

    def _show_details(self) -> None:
        task = self._selected_task()
        self.cancel_button.setEnabled(bool(task and task.get("state") == "running" and task.get("can_cancel")))
        can_pause = bool(task and task.get("state") == "running" and task.get("can_pause"))
        can_resume = bool(task and task.get("state") == "paused")
        self.pause_button.setEnabled(can_pause or can_resume)
        self.pause_button.setText("Resume" if can_resume else "Pause")
        self.retry_button.setEnabled(bool(task and task.get("state") not in {"running", "paused"} and task.get("can_retry")))
        metadata = dict(task.get("metadata") or {}) if task else {}
        self.open_asset_button.setEnabled(bool(metadata.get("asset_id") or metadata.get("scene_asset_id")))
        self.reveal_button.setEnabled(bool(metadata.get("output") or metadata.get("path") or metadata.get("scene")))
        self.details.setPlainText(json.dumps(task, indent=2, sort_keys=True, default=str) if task else "")

    def _commit(self) -> None:
        self.refresh()
        self._save()

    def _load(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for raw in payload.get("tasks") or ():
            if not isinstance(raw, dict) or not str(raw.get("task_id") or ""):
                continue
            task = dict(raw)
            if task.get("state") == "running":
                task["state"] = "interrupted"
                task["message"] = "The editor closed before this task reported completion. Retry when ready."
                task["can_cancel"] = False
                task["can_pause"] = False
                task["can_retry"] = True
            self.tasks[str(task["task_id"])] = task

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "tech_connector.engine_tasks.v1", "tasks": list(self.tasks.values())[-100:]}
        handle, temporary_name = tempfile.mkstemp(prefix=".editor_tasks.", suffix=".tmp", dir=str(self.state_path.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["EngineTaskCenter"]
