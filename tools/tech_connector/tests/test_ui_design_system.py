"""Focused tests for the shared Tech Connector visual foundation."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tech_connector.ui.design_system import TOKENS, component_stylesheet, set_status_state
from tech_connector.ui.icons import configure_button, icon, icon_names
from tech_connector.ui.status_bar import format_status_card


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first = luminance(foreground)
    second = luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_component_stylesheet_exposes_semantic_roles() -> None:
    stylesheet = component_stylesheet()

    assert 'uiRole="primary"' in stylesheet
    assert 'uiRole="composer"' in stylesheet
    assert TOKENS.accent in stylesheet
    assert TOKENS.success in stylesheet


def test_icon_registry_renders_every_declared_icon() -> None:
    _application()

    assert icon_names()
    assert all(not icon(name).isNull() for name in icon_names())


def test_configure_button_sets_accessible_semantic_metadata() -> None:
    _application()
    button = QPushButton()

    configure_button(
        button,
        "send",
        text="Send",
        tooltip="Send request",
        role="primary",
    )

    assert button.text() == "Send"
    assert button.property("uiRole") == "primary"
    assert button.accessibleName() == "Send"
    assert button.accessibleDescription() == "Send request"
    assert not button.icon().isNull()


def test_status_state_uses_semantic_properties() -> None:
    _application()
    status = QLabel()

    set_status_state(status, "ok", "Ready")

    assert status.text() == "Ready"
    assert status.property("uiRole") == "status"
    assert status.property("statusState") == "ok"


def test_core_text_tokens_meet_accessible_contrast() -> None:
    assert _contrast_ratio(TOKENS.text, TOKENS.canvas) >= 7.0
    assert _contrast_ratio(TOKENS.text_muted, TOKENS.canvas) >= 4.5
    assert _contrast_ratio(TOKENS.text, TOKENS.surface) >= 7.0


def test_status_cards_use_quiet_borders_and_semantic_state_dots() -> None:
    text, stylesheet = format_status_card("unreal", "ok", "Connected")

    assert "●" in text
    assert "border: 1px solid #273241" in stylesheet
    assert "font-weight: 500" in stylesheet
