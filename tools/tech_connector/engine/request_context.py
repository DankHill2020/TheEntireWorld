"""Tech Connector UI snapshot helpers backed by runtime RequestContext."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reasoning_runtime.engine.request_context import (
    RequestContext,
    explicitly_requests_open_file_context,
    sanitize_prompt_context,
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

    Safe rule: this function must not query SQLite, walk folders, read large
    files, or call live DCC bridges. Tech Connector-specific status helpers are
    sampled only through already-known UI state and non-live checks.
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
    files: list[str] = []
    try:
        files = [str(p) for p in getattr(window, "attached_files", [])]
    except Exception:
        files = []
    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    videos = [
        path
        for path in [*images, *files]
        if Path(str(path)).suffix.lower() in video_exts
    ]

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
            from tech_connector.models.constants import project_index_db_path

            index_state = "Index ready" if project_index_db_path().exists() else "Index missing"
    except Exception:
        index_state = "Index unknown"

    extras: dict[str, Any] = {}
    if files:
        extras["attached_files"] = tuple(files)
    if images:
        extras["attached_images"] = tuple(images)
    if videos:
        extras["attached_videos"] = tuple(videos)
    try:
        workspace = getattr(window, "_active_conversation_workspace", None)
        if isinstance(workspace, dict):
            extras["conversation_workspace"] = dict(workspace)
    except Exception:
        pass
    try:
        memory = getattr(window, "_active_operation_memory", None)
        if isinstance(memory, dict):
            extras["operation_memory"] = dict(memory)
    except Exception:
        pass
    try:
        prior_result = getattr(window, "_last_engine_result_metadata", None)
        if isinstance(prior_result, dict):
            extras["prior_result_metadata"] = dict(prior_result)
    except Exception:
        pass
    try:
        settings = getattr(window, "settings", None)
        if isinstance(settings, dict):
            extras["settings"] = sanitize_prompt_context(settings)
    except Exception:
        pass
    try:
        from tech_connector.services.capability_availability_service import (
            build_capability_availability,
            snapshot_status_cards,
        )

        status_cards = dict(getattr(window, "_status_card_states", {}) or {})
        if not status_cards:
            status_cards = snapshot_status_cards(window)
        extras["status_cards"] = status_cards
        extras["capability_availability"] = build_capability_availability(
            status_cards=status_cards,
            settings=extras.get("settings") or {},
            command_router=getattr(window, "command_router", None),
            include_live_checks=False,
        )
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
        extras=sanitize_prompt_context(extras),
    )


__all__ = [
    "RequestContext",
    "explicitly_requests_open_file_context",
    "open_file_paths_from_window",
    "sanitize_prompt_context",
    "should_prioritize_open_file_context",
    "snapshot_from_window",
]
