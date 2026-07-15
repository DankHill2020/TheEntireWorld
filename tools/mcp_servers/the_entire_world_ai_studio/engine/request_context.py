"""Cheap request-context snapshot for the Intelligence Engine.

This module deliberately avoids project searches, large file reads, or DCC calls.
It only snapshots already-known UI state so the UI can update context labels
without freezing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class RequestContext:
    text: str
    active_tab: str = "Chat"
    current_file_path: str = ""
    open_file_paths: tuple[str, ...] = ()
    selection_text: str = ""
    project_roots: tuple[str, ...] = ()
    attached_images: tuple[str, ...] = ()
    model: str = ""
    index_state: str = "unknown"
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def has_selection(self) -> bool:
        return bool(self.selection_text.strip())

    @property
    def current_file_name(self) -> str:
        return Path(self.current_file_path).name if self.current_file_path else ""

    def context_label(self) -> str:
        parts = [self.active_tab or "Chat"]
        if self.current_file_name:
            parts.append(self.current_file_name)
        elif self.open_file_paths:
            parts.append(f"Open files {len(self.open_file_paths)}")
        if self.has_selection:
            parts.append(f"Selection {len(self.selection_text.splitlines())} lines")
        if self.project_roots:
            parts.append("Project")
        if self.index_state:
            parts.append(self.index_state)
        if self.model:
            parts.append(self.model.replace("ollama:", ""))
        return "Context: " + " - ".join(parts)


def explicitly_requests_open_file_context(text: str) -> bool:
    """Return True when the user is clearly asking about open/current files."""
    lower = (text or "").lower()
    return bool(
        re.search(r"\b(this|current|active|open|selected)\s+(?:file|script|module|code)\b", lower)
        or re.search(r"\b(in|from|inside)\s+(?:this|the current|the active|the open)\s+(?:file|script|module)\b", lower)
        or re.search(r"\b(open|opened)\s+files?\b", lower)
        or re.search(r"\bcurrent\s+selection\b", lower)
    )


def should_prioritize_open_file_context(window: Any, text: str = "") -> bool:
    """Decide whether already-open editor files should get ranking weight."""
    if explicitly_requests_open_file_context(text):
        return True
    try:
        widget = getattr(window, "prioritize_open_file_context_checkbox", None)
        if widget is not None:
            return bool(widget.isChecked())
    except Exception:
        pass
    try:
        settings = getattr(window, "settings", {}) or {}
        return bool(settings.get("prioritize_open_file_context", False))
    except Exception:
        return False


def open_file_paths_from_window(window: Any) -> tuple[str, ...]:
    """Return already-known open editor paths without touching the filesystem."""
    paths: list[str] = []
    current = str(getattr(window, "current_file_path", "") or "")
    if current:
        paths.append(current)
    try:
        editors = getattr(window, "open_editors", {}) or {}
        for path in editors.keys():
            if path:
                paths.append(str(path))
    except Exception:
        pass
    try:
        for path in (getattr(window, "settings", {}) or {}).get("open_files", []) or []:
            if path:
                paths.append(str(path))
    except Exception:
        pass

    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        key = path.replace("\\", "/").lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(path)
    return tuple(unique[:12])


def snapshot_from_window(window: Any, text: str = "") -> RequestContext:
    """Build a cheap context snapshot from the MainWindow.

    Safe rule: this function must not query SQLite, walk folders, read large files,
    or call live DCC bridges.
    """
    active_tab = "Chat"
    try:
        if hasattr(window, "workspace_tabs"):
            active_tab = window.workspace_tabs.tabText(window.workspace_tabs.currentIndex()) or "Chat"
    except Exception:
        pass

    current_file_path = str(getattr(window, "current_file_path", "") or "")
    open_file_paths = open_file_paths_from_window(window)
    if current_file_path and not should_prioritize_open_file_context(window, text):
        current_file_path = ""

    selection_text = ""
    try:
        editor = getattr(window, "code_editor", None)
        if editor is not None:
            cursor = editor.textCursor()
            selection_text = cursor.selectedText().replace("\u2029", "\n")[:12000]
    except Exception:
        selection_text = ""

    roots: list[str] = []
    try:
        roots = [str(p) for p in window.project_roots()] if hasattr(window, "project_roots") else []
    except Exception:
        roots = []

    images: list[str] = []
    try:
        images = [str(p) for p in getattr(window, "attached_images", [])]
    except Exception:
        images = []

    model = ""
    try:
        model = window.selected_mcphost_model()
    except Exception:
        pass

    index_state = ""
    try:
        sync = getattr(window, "_last_index_sync_status", None) or {}
        if sync.get("stale"):
            index_state = f"Index stale: {sync.get('total_stale', 0)} files"
        elif sync:
            index_state = "Index synced"
        else:
            from models.constants import V2_DB
            index_state = "Index ready" if V2_DB.exists() else "Index missing"
    except Exception:
        index_state = "Index unknown"

    extras: dict[str, Any] = {}
    try:
        route_decision = getattr(window, "_last_prompt_route_decision", None)
        if isinstance(route_decision, dict):
            extras["prompt_route_decision"] = route_decision
    except Exception:
        pass

    try:
        snapshot_str = getattr(window, "unreal_project_snapshot", None)
        if snapshot_str:
            import json
            snapshot_data = json.loads(snapshot_str)
            data = snapshot_data.get("data") or {}
            folders = data.get("selected_folders") or (snapshot_data.get("health") or {}).get("selected_folders")
            if folders:
                extras["selected_folders"] = folders
    except Exception:
        pass

    return RequestContext(
        text=text or "",
        active_tab=active_tab,
        current_file_path=current_file_path,
        open_file_paths=open_file_paths,
        selection_text=selection_text,
        project_roots=tuple(roots),
        attached_images=tuple(images),
        model=model,
        index_state=index_state,
        extras=extras,
    )
