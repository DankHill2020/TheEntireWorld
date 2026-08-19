"""Semantic, stroke-consistent icons used by the Tech Connector UI."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton

from tech_connector.ui.design_system import TOKENS


# Lucide-style 24px path geometry.  Names describe intent rather than artwork.
_PATHS: dict[str, str] = {
    "settings": '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.86 2.86-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.4v-.1A1.7 1.7 0 0 0 8 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.86-2.86.06-.06A1.7 1.7 0 0 0 3.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2V9.4h.1A1.7 1.7 0 0 0 3.6 8a1.7 1.7 0 0 0-.34-1.88l-.06-.06L6.06 3.2l.06.06A1.7 1.7 0 0 0 8 3.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2h4.2v.1A1.7 1.7 0 0 0 15 3.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.86 2.86-.06.06A1.7 1.7 0 0 0 19.4 8c.14.42.35.76.6 1 .3.27.67.4 1.1.4h.1v4.2h-.1a1.7 1.7 0 0 0-1.7 1.4Z"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "paperclip": '<path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.6-9.6a4 4 0 0 1 5.7 5.7l-9.6 9.6a2 2 0 1 1-2.8-2.8l8.9-8.9"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5M9 12h6M9 16h4"/>',
    "chevron_up": '<path d="m18 15-6-6-6 6"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-2"/>',
    "export": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M12 18v-6M9 15l3 3 3-3"/>',
    "maximize": '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
    "panel_left": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "more_horizontal": '<path d="M5 12h.01M12 12h.01M19 12h.01"/>',
    "cancel": '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "document": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
    "folder": '<path d="M3 5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H5a2 2 0 0 1-2-2Z"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "graph": '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="m7 7 4 9M17 7l-4 9M7 6h10"/>',
    "package": '<path d="m12 2 9 5-9 5-9-5Z"/><path d="m3 7 9 5 9-5M3 12l9 5 9-5M3 17l9 5 9-5"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    "arrow_right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0-5-5L12 3.6 9.6 6 7.3 3.7a4 4 0 0 0 5 5L5 16l3 3 7.3-7.3a4 4 0 0 0 5-5L18 9l-2.4-2.4 2.3-2.3a4 4 0 0 0-3.2 2Z"/>',
    "format": '<path d="M4 6h16M8 10h12M4 14h16M8 18h12"/>',
    "play": '<path d="m7 4 13 8-13 8Z"/>',
    "edit": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 10v7M14 10v7"/>',
    "test": '<path d="M9 3h6M10 3v5l-5 9a3 3 0 0 0 2.6 4.5h8.8A3 3 0 0 0 19 17l-5-9V3M8 15h8"/>',
    "refresh": '<path d="M20 6v5h-5M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6 6.5L4 9M5.5 15A7 7 0 0 0 18 17.5l2-2.5"/>',
    "external_link": '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
    "clear": '<path d="m3 6 3-3h12l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2ZM8 10l8 8M16 10l-8 8"/>',
    "compare": '<rect x="3" y="4" width="7" height="16" rx="1"/><rect x="14" y="4" width="7" height="16" rx="1"/><path d="m12 8-2 2 2 2M12 16l2-2-2-2"/>',
    "sparkles": '<path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2ZM19 14l.7 2.3L22 17l-2.3.7L19 20l-.7-2.3L16 17l2.3-.7ZM5 14l.7 2.3L8 17l-2.3.7L5 20l-.7-2.3L2 17l2.3-.7Z"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h2"/>',
    "camera": '<path d="M14.5 5 13 3h-2L9.5 5H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="4"/>',
    "brush": '<path d="m14 4 6 6-9 9H5v-6ZM4 21c2 0 3-1 3-3"/>',
    "eraser": '<path d="m7 20-4-4L14 5a3 3 0 0 1 4 0l1 1a3 3 0 0 1 0 4L9 20ZM11 8l6 6M7 20h14"/>',
    "rectangle": '<rect x="3" y="5" width="18" height="14" rx="1"/>',
    "circle": '<circle cx="12" cy="12" r="8"/>',
    "lasso": '<path d="M20 9c0 4-4 7-9 7s-8-2-8-5 3-6 8-6 9 2 9 4Z"/><path d="M11 16c1 3 3 5 6 5 2 0 3-1 3-2s-1-2-2-2"/>',
    "bounding_box": '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5M8 8h8v8H8Z"/>',
    "line": '<path d="M4 20 20 4"/>',
    "eyedropper": '<path d="m19 3 2 2-9 9-3-3ZM9 11l-5 5v4h4l5-5"/>',
    "bucket": '<path d="m6 5 10 10M4 13 13 4l7 7-9 9H4Z"/><path d="M21 15s2 2 2 4a2 2 0 0 1-4 0c0-2 2-4 2-4Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "skip_back": '<path d="M6 5v14M19 6l-9 6 9 6Z"/>',
    "skip_forward": '<path d="M18 5v14M5 6l9 6-9 6Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "layers": '<path d="m12 2 9 5-9 5-9-5Z"/><path d="m3 12 9 5 9-5M3 17l9 5 9-5"/>',
    "move": '<path d="M12 2v20M2 12h20"/><path d="m8 6 4-4 4 4M8 18l4 4 4-4M6 8l-4 4 4 4M18 8l4 4-4 4"/>',
}


def icon_names() -> tuple[str, ...]:
    return tuple(sorted(_PATHS))


@lru_cache(maxsize=256)
def icon(name: str, color: str = TOKENS.text_muted) -> QIcon:
    """Return a scalable semantic icon."""
    if name not in _PATHS:
        raise KeyError(f"Unknown Tech Connector icon: {name}")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{_PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for size in (16, 20, 24, 32):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


def configure_button(
    button: QAbstractButton,
    icon_name: str,
    *,
    text: str | None = None,
    tooltip: str | None = None,
    role: str = "secondary",
    icon_only: bool = False,
) -> QAbstractButton:
    """Apply a semantic icon, label, tooltip, and visual role to a button."""
    button.setIcon(icon(icon_name))
    button.setIconSize(QSize(TOKENS.icon, TOKENS.icon))
    if text is not None:
        button.setText(text)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleDescription(tooltip)
    button.setAccessibleName(text or tooltip or icon_name.replace("_", " ").title())
    button.setProperty("uiRole", role)
    button.setProperty("iconOnly", bool(icon_only))
    if icon_only:
        button.setText("")
        button.setFixedSize(TOKENS.control_height, TOKENS.control_height)
    return button


__all__ = ["configure_button", "icon", "icon_names"]
