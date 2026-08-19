"""Shared visual tokens and component roles for Tech Connector.

The application still contains legacy, surface-owned styles.  New and migrated
controls should use these semantic roles so visual changes remain centralized.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class DesignTokens:
    canvas: str = "#07090d"
    surface: str = "#0c1016"
    surface_raised: str = "#111720"
    surface_hover: str = "#17202b"
    border: str = "#273241"
    border_strong: str = "#3b4a5d"
    text: str = "#edf2f7"
    text_muted: str = "#94a3b8"
    text_subtle: str = "#64748b"
    accent: str = "#38a9ff"
    accent_hover: str = "#65bdff"
    accent_pressed: str = "#1987d4"
    success: str = "#40c878"
    warning: str = "#f5ad42"
    danger: str = "#f06464"
    focus: str = "#7bc8ff"
    radius_small: int = 4
    radius: int = 6
    control_height: int = 30
    icon_small: int = 14
    icon: int = 16


TOKENS = DesignTokens()


def component_stylesheet(tokens: DesignTokens = TOKENS) -> str:
    """Return role-based styles layered after the legacy application theme."""
    return f"""
        QWidget {{
            background: {tokens.canvas};
            color: {tokens.text};
        }}
        QLineEdit, QTextEdit, QTextBrowser, QPlainTextEdit, QListWidget,
        QTreeWidget, QTableWidget, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
            color: {tokens.text};
            selection-background-color: {tokens.accent_pressed};
            selection-color: {tokens.text};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {tokens.focus};
        }}
        QPushButton, QToolButton {{
            background: {tokens.surface_raised};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
            color: {tokens.text};
            font-weight: 500;
            padding: 5px 10px;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {tokens.surface_hover};
            border-color: {tokens.border_strong};
        }}
        QPushButton:focus, QToolButton:focus {{ border-color: {tokens.focus}; }}
        QPushButton:disabled, QToolButton:disabled {{
            background: {tokens.surface};
            border-color: {tokens.border};
            color: {tokens.text_subtle};
        }}
        QMenuBar, QMenu {{
            background: {tokens.surface};
            color: {tokens.text};
        }}
        QMenu {{ border: 1px solid {tokens.border}; }}
        QMenuBar::item:selected, QMenu::item:selected {{
            background: {tokens.surface_hover};
            color: {tokens.text};
        }}
        QGroupBox {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
            color: {tokens.text_muted};
            font-weight: 600;
            margin-top: 10px;
            padding-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 9px;
            padding: 0 4px;
        }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background: {tokens.border_strong};
        }}
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
            background: {tokens.text_subtle};
        }}
        QWidget#appHeader {{
            background: {tokens.canvas};
            border-bottom: 1px solid {tokens.border};
        }}
        QWidget#projectSidebar {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
        }}
        QFrame#projectPanelActions, QFrame#systemStatusHeader {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
        }}
        QLabel[uiRole="title"] {{
            color: {tokens.text};
            font-size: 18px;
            font-weight: 600;
        }}
        QLabel[uiRole="sectionTitle"] {{
            color: {tokens.text};
            font-size: 13px;
            font-weight: 600;
        }}
        QLabel[uiRole="muted"] {{ color: {tokens.text_muted}; }}
        QLabel[uiRole="status"] {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius}px;
            color: {tokens.text_muted};
            padding: 4px 8px;
        }}
        QLabel[uiRole="status"][statusState="ok"] {{
            border-color: {tokens.success};
            color: {tokens.success};
        }}
        QLabel[uiRole="status"][statusState="busy"] {{
            border-color: {tokens.accent};
            color: {tokens.accent};
        }}
        QLabel[uiRole="status"][statusState="warning"] {{
            border-color: {tokens.warning};
            color: {tokens.warning};
        }}
        QLabel[uiRole="status"][statusState="error"] {{
            border-color: {tokens.danger};
            color: {tokens.danger};
        }}
        QLabel[uiRole="context"] {{
            background: {tokens.surface};
            border: 1px solid {tokens.border};
            border-radius: {tokens.radius_small}px;
            color: {tokens.text_muted};
            padding: 3px 7px;
        }}
        QPushButton[uiRole="primary"], QToolButton[uiRole="primary"] {{
            background: {tokens.accent};
            border: 1px solid {tokens.accent};
            color: #06111a;
            font-weight: 600;
        }}
        QPushButton[uiRole="primary"]:hover, QToolButton[uiRole="primary"]:hover {{
            background: {tokens.accent_hover};
            border-color: {tokens.accent_hover};
        }}
        QPushButton[uiRole="primary"]:pressed, QToolButton[uiRole="primary"]:pressed {{
            background: {tokens.accent_pressed};
            border-color: {tokens.accent_pressed};
        }}
        QPushButton[uiRole="secondary"], QToolButton[uiRole="secondary"] {{
            background: {tokens.surface_raised};
            border: 1px solid {tokens.border};
            color: {tokens.text};
            font-weight: 500;
        }}
        QPushButton[uiRole="secondary"]:hover, QToolButton[uiRole="secondary"]:hover {{
            background: {tokens.surface_hover};
            border-color: {tokens.border_strong};
        }}
        QPushButton[uiRole="quiet"], QToolButton[uiRole="quiet"] {{
            background: transparent;
            border: 1px solid transparent;
            color: {tokens.text_muted};
            font-weight: 500;
        }}
        QPushButton[uiRole="quiet"]:hover, QToolButton[uiRole="quiet"]:hover {{
            background: {tokens.surface_hover};
            color: {tokens.text};
        }}
        QPushButton[uiRole="danger"], QToolButton[uiRole="danger"] {{
            background: transparent;
            border: 1px solid #6e363b;
            color: {tokens.danger};
        }}
        QPushButton[iconOnly="true"], QToolButton[iconOnly="true"] {{
            min-width: 28px;
            max-width: 28px;
            padding: 0;
        }}
        QPushButton[toolButton="true"]:checked, QToolButton[toolButton="true"]:checked {{
            background: {tokens.accent_pressed};
            border-color: {tokens.focus};
            color: {tokens.text};
        }}
        QLineEdit[uiRole="composer"], QTextEdit[uiRole="composer"],
        QPlainTextEdit[uiRole="composer"] {{
            background: {tokens.surface};
            border: 1px solid {tokens.border_strong};
            border-radius: 8px;
            padding: 7px 9px;
        }}
        QLineEdit[uiRole="composer"]:focus, QTextEdit[uiRole="composer"]:focus,
        QPlainTextEdit[uiRole="composer"]:focus {{ border-color: {tokens.focus}; }}
        QTabBar::tab {{
            min-width: 72px;
            padding: 7px 12px;
            background: {tokens.surface};
            border-color: {tokens.border};
            color: {tokens.text_muted};
        }}
        QTabBar::tab:selected {{
            background: {tokens.surface_raised};
            border-color: {tokens.border_strong};
            color: {tokens.text};
        }}
    """


def set_ui_role(widget: QWidget, role: str) -> None:
    """Assign a semantic role and refresh the widget's style."""
    widget.setProperty("uiRole", role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def set_status_state(widget: QWidget, state: str, text: str | None = None) -> None:
    """Update a semantic status label without introducing local color styles."""
    if text is not None and hasattr(widget, "setText"):
        widget.setText(text)
    widget.setStyleSheet("")
    widget.setProperty("statusState", state)
    set_ui_role(widget, "status")


__all__ = [
    "DesignTokens",
    "TOKENS",
    "component_stylesheet",
    "set_status_state",
    "set_ui_role",
]
