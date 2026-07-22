"""Collapsible system status panel for Tech Connector."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tech_connector.models.constants import project_index_db_path
from tech_connector.ui.status_bar import format_status_card

STATUS_BAND_STYLE = (
    "QLabel { background-color: #000711; border: 1px solid #1e9bff; "
    "border-radius: 5px; color: #b9dcff; padding: 4px 8px; }"
)

STATUS_BODY_STYLE = (
    "QWidget#systemStatusBody { background-color: #00040a; "
    "border: 1px solid #12324a; border-radius: 5px; }"
)


STATUS_CARD_KEYS = [
    ("ollama", "Ollama"),
    ("mcphost", "MCPHost"),
    ("knowledge", "Knowledge"),
    ("vcs", "VCS"),
    ("maya", "Maya"),
    ("unreal", "Unreal"),
    ("blender", "Blender"),
    ("substance_painter", "Substance"),
    ("motionbuilder", "MotionBuilder"),
    ("integrations", "Integrations"),
]


class ClickableStatusCard(QLabel):
    def __init__(self, key, label, window, parent=None):
        super().__init__(f"{label}: Unknown", parent)
        self.key = key
        self.label = label
        self.window = window
        self.setMinimumWidth(54)
        self.setMaximumWidth(118)
        self.setMaximumHeight(24)
        self.setToolTip(label)
        if key in {"maya", "unreal", "blender", "substance_painter", "motionbuilder", "unity"}:
            self.setToolTip(f"Double-click to launch {label}")

    def mouseDoubleClickEvent(self, event):
        if self.key in {"maya", "unreal", "blender", "substance_painter", "motionbuilder", "unity"}:
            if hasattr(self.window, "launch_dcc"):
                self.window.launch_dcc(self.key)
        super().mouseDoubleClickEvent(event)


def build_system_status_panel(window) -> QWidget:
    """Build the collapsible model/routing/status/progress section.

    The function sets:
        window.system_status_outer
        window.system_status_body
        window.status_cards
        window.index_status
        window.index_progress
        window.status_toggle_btn
    """

    outer = QWidget(window)
    outer_layout = QVBoxLayout(outer)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(4)

    header = QHBoxLayout()
    title = QLabel("System Status")
    title.setStyleSheet("font-weight: bold; color: #b9dcff; background: transparent; border: 0;")
    header.addWidget(title)

    if hasattr(window, "active_model_label"):
        window.active_model_label.setObjectName("activeModelStatusLabel")
        window.active_model_label.setStyleSheet(STATUS_BAND_STYLE)
        header.addWidget(window.active_model_label, 1)
    else:
        window.active_model_label = QLabel("Routing mode: unknown    Active response model: unknown")
        window.active_model_label.setObjectName("activeModelStatusLabel")
        window.active_model_label.setStyleSheet(STATUS_BAND_STYLE)
        header.addWidget(window.active_model_label, 1)

    toggle = QPushButton("Hide Status ▲")
    toggle.setMaximumWidth(130)
    toggle.clicked.connect(window.toggle_system_status_panel)
    window.status_toggle_btn = toggle
    header.addWidget(toggle)
    outer_layout.addLayout(header)

    body = QWidget(outer)
    body.setObjectName("systemStatusBody")
    body.setStyleSheet(STATUS_BODY_STYLE)
    body_layout = QVBoxLayout(body)
    body_layout.setContentsMargins(6, 5, 6, 5)
    body_layout.setSpacing(4)

    cards_row = QHBoxLayout()
    cards_row.setSpacing(6)
    window.status_cards = {}
    for key, label in STATUS_CARD_KEYS:
        card = ClickableStatusCard(key, label, window)
        text, style = format_status_card(key, "unknown", "Not checked")
        card.setText(text)
        card.setStyleSheet(style)
        cards_row.addWidget(card)
        window.status_cards[key] = card
    body_layout.addLayout(cards_row)

    index_row = QHBoxLayout()
    window.index_status = QLabel("Knowledge: " + ("ready" if project_index_db_path().exists() else "missing"))
    window.index_status.setObjectName("statusBandLabel")
    window.index_status.setStyleSheet(STATUS_BAND_STYLE)
    window.index_status.setMinimumWidth(175)
    index_row.addWidget(window.index_status)

    window.index_progress = QProgressBar()
    window.index_progress.setRange(0, 1)
    window.index_progress.setValue(1 if project_index_db_path().exists() else 0)
    index_row.addWidget(window.index_progress, 1)
    body_layout.addLayout(index_row)

    # Dedicated Download progress row (hidden by default, used by Cap Planner & Git Ingestion)
    download_row = QHBoxLayout()
    window.download_status = QLabel("Download: Idle")
    window.download_status.setObjectName("statusBandLabel")
    window.download_status.setStyleSheet(STATUS_BAND_STYLE)
    window.download_status.setMinimumWidth(175)
    window.download_status.setVisible(False)
    download_row.addWidget(window.download_status)

    window.download_progress = QProgressBar()
    window.download_progress.setRange(0, 100)
    window.download_progress.setValue(0)
    window.download_progress.setVisible(False)
    download_row.addWidget(window.download_progress, 1)
    body_layout.addLayout(download_row)

    outer_layout.addWidget(body)
    window.system_status_outer = outer
    window.system_status_body = body

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    outer_layout.addWidget(line)

    return outer


def toggle_system_status_panel(window) -> None:
    body = getattr(window, "system_status_body", None)
    btn = getattr(window, "status_toggle_btn", None)
    if body is None:
        return
    visible = not body.isVisible()
    body.setVisible(visible)
    if btn is not None:
        btn.setText("Hide Status ▲" if visible else "Show Status ▼")
