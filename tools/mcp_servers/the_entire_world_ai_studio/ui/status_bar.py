"""Status card styling helpers."""

from __future__ import annotations

from html import escape

from models.constants import (
    APP_ROOT,
    LOGO_DARK,
    LOGO_DARK_BLUE,
    STATUS_CARD_COLORS,
    STATUS_CARD_ICONS,
    STATUS_CARD_LABELS,
)

ICON_ALIASES = {
    "atlassian": ("jira",),
    "email": ("gmail",),
    "git": ("git", "github"),
    "p4": ("perforce", "p4"),
    "vcs": ("git", "github", "perforce", "p4"),
}


def _status_icon_html(key: str) -> str:
    """Use real image icons from assets/app_icons when available."""
    icon_dir = APP_ROOT / "assets" / "app_icons"
    candidates = (key, *ICON_ALIASES.get(key, ()))
    for candidate in candidates:
        for suffix in (".png", ".svg", ".ico"):
            icon_path = icon_dir / f"{candidate}{suffix}"
            if icon_path.exists():
                src = icon_path.resolve().as_uri()
                return f'<img src="{escape(src)}" width="14" height="14" />'
    return escape(STATUS_CARD_ICONS.get(key, STATUS_CARD_LABELS.get(key, key)[:2]))


def _compact_detail(detail: str, limit: int = 18) -> str:
    detail = " ".join((detail or "").split())
    if len(detail) <= limit:
        return detail
    return detail[: max(0, limit - 1)].rstrip() + "..."


def format_status_card(key: str, state: str, detail: str = "") -> tuple[str, str]:
    """Return (display_text, stylesheet) for a compact icon-first status card."""
    color = STATUS_CARD_COLORS.get(state, STATUS_CARD_COLORS.get("unknown", "#cfcfcf"))
    icon = _status_icon_html(key)
    
    # Hide "Not checked" or "Unknown" text from the card button UI
    is_unchecked = (
        state == "unknown" 
        or not detail 
        or "not checked" in detail.lower() 
        or "not checked" in state.lower()
    )
    
    if is_unchecked:
        label = STATUS_CARD_LABELS.get(key, key)
        text = f'{icon} {escape(label)}'
    else:
        compact_detail = _compact_detail(detail or state.title())
        text = f'{icon} <span style="color:{color};">●</span> {escape(compact_detail)}'
        
    fill = LOGO_DARK
    if state == "ok":
        fill = LOGO_DARK
    elif state == "busy":
        fill = LOGO_DARK_BLUE
    elif state == "warn":
        fill = "#120804"
    elif state == "bad":
        fill = "#150707"
    stylesheet = (
        f"padding: 2px 6px; border: 1px solid {color}; border-radius: 5px; "
        f"background-color: {fill}; color: {color}; font-weight: bold; font-size: 10px;"
    )
    return text, stylesheet


def format_knowledge_summary(files=0, symbols=0, imports=0, calls=0, graph_ready=False) -> str:
    graph = "ready" if graph_ready else "pending"
    return (
        f"Files: {files:,} | Symbols: {symbols:,} | "
        f"Imports: {imports:,} | Calls: {calls:,} | Graph: {graph}"
    )


def format_index_sync_status(sync: dict | None) -> tuple[str, str]:
    """Return a compact status card for index freshness."""
    if not sync:
        return format_status_card("knowledge", "unknown", "Sync unknown")
    if sync.get("error"):
        return format_status_card("knowledge", "warn", "Sync check failed")
    if sync.get("stale"):
        return format_status_card("knowledge", "warn", f"Stale: {sync.get('total_stale', 0)} files")
    return format_status_card("knowledge", "ok", "Synced")
