"""Compact toolbar helpers for Tech Connector.

The old toolbar accumulated many advanced buttons. This helper keeps only
high-frequency controls visible; advanced actions belong in the menu bar.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from tech_connector.models.constants import DEFAULT_CONFIGS, DEFAULT_MODEL
from tech_connector.services.model_provider_service import (
    PROVIDER_ORDER,
    PROVIDERS,
    provider_for_model,
)
from tech_connector.services.settings_service import best_config


def build_compact_toolbar(window) -> QWidget:
    """Create the compact always-visible toolbar row.

    Sets expected MainWindow attributes:
        settings_btn
        model_source_mode_box
        model_box
        config_box
        use_pty_checkbox
    """

    bar = QWidget(window)
    controls = QHBoxLayout(bar)
    controls.setContentsMargins(0, 0, 0, 0)
    controls.setSpacing(6)

    settings_btn = QPushButton("Settings")
    settings_btn.clicked.connect(window.show_settings_dialog)
    window.settings_btn = settings_btn
    controls.addWidget(settings_btn)

    controls.addWidget(QLabel("Source:"))
    window.model_source_mode_box = QComboBox()
    window.model_source_mode_box.addItem(
        "Cloud locked / local if unset", "auto_with_local_fallback"
    )
    window.model_source_mode_box.addItem("Always local", "local_only")
    mode = window.settings.get("model_source_mode", "auto_with_local_fallback")
    idx = window.model_source_mode_box.findData(mode)
    if idx >= 0:
        window.model_source_mode_box.setCurrentIndex(idx)
    window.model_source_mode_box.currentIndexChanged.connect(window.on_model_source_mode_changed)
    controls.addWidget(window.model_source_mode_box)

    selected = window.settings.get("model", DEFAULT_MODEL)
    controls.addWidget(QLabel("Provider:"))
    window.model_provider_box = QComboBox()
    for provider_id in PROVIDER_ORDER:
        window.model_provider_box.addItem(
            PROVIDERS[provider_id].display_name,
            provider_id,
        )
    provider_index = window.model_provider_box.findData(provider_for_model(selected))
    if provider_index >= 0:
        window.model_provider_box.setCurrentIndex(provider_index)
    controls.addWidget(window.model_provider_box)

    controls.addWidget(QLabel("Model:"))
    window.model_box = QComboBox()
    window.model_box.setEditable(False)
    window._local_model_options = [("Saved", selected), ("Default", DEFAULT_MODEL)]
    window._installed_ollama_models = []
    window.refresh_model_options_for_provider(
        window.model_provider_box.currentData(),
        selected_model=selected,
    )
    window.model_box.currentIndexChanged.connect(window.on_model_changed)
    window.model_provider_box.currentIndexChanged.connect(
        window.on_model_provider_changed
    )
    controls.addWidget(window.model_box, 2)

    controls.addWidget(QLabel("Config:"))
    window.config_box = QComboBox()
    window.config_box.setEditable(True)
    default_config = window.settings.get("config") or best_config()
    for cfg in [default_config] + DEFAULT_CONFIGS:
        if window.config_box.findText(cfg) < 0:
            window.config_box.addItem(cfg)
    window.config_box.setEditText(default_config)
    controls.addWidget(window.config_box, 2)

    window.use_pty_checkbox = QCheckBox("PTY")
    window.use_pty_checkbox.setChecked(bool(window.settings.get("use_pty", False)))
    window.use_pty_checkbox.setToolTip("Use PTY for MCPHost terminal compatibility.")
    controls.addWidget(window.use_pty_checkbox)

    build_btn = QPushButton("Quick Index")
    build_btn.clicked.connect(window.build_index)
    controls.addWidget(build_btn)

    controls.addStretch(1)
    return bar
