"""Onboarding, tool guidance, accessibility, and progressive disclosure tests."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QPushButton, QSplitter, QTreeWidget, QVBoxLayout, QWidget

from tech_connector.ui.ux_polish import (
    ContextRecipeCard,
    ToolGuidance,
    WorkflowRecipe,
    apply_3d_viewer_ux_polish,
    apply_main_window_ux_polish,
    apply_widget_discoverability,
    explain_disabled,
    guidance_tooltip,
)
from tech_connector.ui.first_run_dialog import FirstRunDialog


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_guidance_tooltip_has_predictable_novice_structure() -> None:
    tooltip = guidance_tooltip(ToolGuidance(
        "Create a paintable deformer.", "Select a skinned mesh.",
        "A new editable layer is added.", "Ctrl+D", "Canonical skin weights stay unchanged.",
    ))
    assert tooltip.splitlines() == [
        "Create a paintable deformer.", "", "Before you start: Select a skinned mesh.",
        "Result: A new editable layer is added.", "Shortcut: Ctrl+D", "",
        "Canonical skin weights stay unchanged.",
    ]


def test_context_recipe_is_compact_collapsible_and_explains_output() -> None:
    _application()
    card = ContextRecipeCard(WorkflowRecipe(
        "Soft body workflow", ("Select mesh", "Choose preset", "Preview"),
        requires="A closed mesh.", preview="Drag while live.", output="Bake for export.",
    ))
    all_text = " ".join(label.text() for label in card.findChildren(QWidget)
                        if hasattr(label, "text") and callable(label.text))
    assert "Select mesh" in all_text
    assert "Bake for export" in all_text
    card.toggle.setChecked(False)
    assert card.detail.isHidden()


def test_discoverability_fills_accessibility_and_disabled_explanations() -> None:
    _application()
    root = QWidget()
    layout = QVBoxLayout(root)
    send = QPushButton("Send")
    unavailable = QPushButton("Bake")
    unavailable.setEnabled(False)
    combo = QComboBox()
    combo.setAccessibleName("Simulation quality")
    layout.addWidget(send)
    layout.addWidget(unavailable)
    layout.addWidget(combo)

    apply_widget_discoverability(root)
    explain_disabled(unavailable, "Create a simulation first.")

    assert "Shortcut: Enter" in send.toolTip()
    assert send.accessibleDescription() == send.toolTip()
    assert "Create a simulation first" in unavailable.toolTip()
    assert "simulation quality" in combo.toolTip().lower()


class _MainHarness(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = {}
        self.service = SimpleNamespace(save_settings=lambda values: None)
        self.project_loads = 0
        self.index_builds = 0
        root = QVBoxLayout(self)
        self.top_section_widget = QWidget()
        root.addWidget(self.top_section_widget)
        self.menu_bar_controls_widget = QWidget(self.top_section_widget)
        self.menu_bar_controls_widget.setLayout(QHBoxLayout())
        root.addWidget(QWidget())
        from tech_connector.ui.growing_prompt_edit import GrowingPromptEdit
        self.input = GrowingPromptEdit()
        root.addWidget(self.input)

    def load_project(self): self.project_loads += 1
    def build_index(self): self.index_builds += 1


def test_main_window_getting_started_card_guides_actions_and_can_reopen() -> None:
    _application()
    window = _MainHarness()
    apply_main_window_ux_polish(window)
    window.show()
    QApplication.processEvents()

    assert window.getting_started_card.isVisible()
    assert window.getting_started_toggle_btn.text() == "Guide"
    buttons = {button.text(): button for button in window.getting_started_card.findChildren(QPushButton)}
    buttons["Choose project"].click()
    buttons["Quick index"].click()
    buttons["Try an example"].click()
    assert window.project_loads == 1
    assert window.index_builds == 1
    assert "safe first task" in window.input.text()
    close = next(button for button in window.getting_started_card.findChildren(QPushButton) if not button.text())
    close.click()
    assert window.settings["getting_started_dismissed"]
    window.getting_started_toggle_btn.click()
    assert window.getting_started_card.isVisible()


def test_3d_viewer_orientation_banner_and_outliner_guidance_are_installed_once() -> None:
    _application()
    viewer = QWidget()
    root = QVBoxLayout(viewer)
    viewer.scene_splitter = QSplitter()
    viewer.scene_outliner = QTreeWidget()
    viewer.viewport_status_label = QPushButton("Ready")
    root.addWidget(viewer.scene_splitter)
    root.addWidget(viewer.scene_outliner)
    root.addWidget(viewer.viewport_status_label)

    apply_3d_viewer_ux_polish(viewer)
    first = viewer.viewer_getting_started_hint
    apply_3d_viewer_ux_polish(viewer)

    assert viewer.viewer_getting_started_hint is first
    assert "Select an object" in viewer.scene_outliner.toolTip()
    assert root.indexOf(first) < root.indexOf(viewer.scene_splitter)


def test_first_run_dialog_explains_scope_indexing_and_non_destructive_removal() -> None:
    _application()
    dialog = FirstRunDialog({"extra_dirs": [], "auto_index_on_first_run": True})
    labels = " ".join(label.text() for label in dialog.findChildren(QPushButton))
    all_text = " ".join(widget.text() for widget in dialog.findChildren(QWidget)
                        if hasattr(widget, "text") and callable(widget.text))

    assert "Save and continue" in labels
    assert "STEP 1 OF 2" in all_text
    assert "STEP 2 OF 2" in all_text
    assert "does not upload, modify, or execute" in all_text
    remove = next(button for button in dialog.findChildren(QPushButton) if button.text() == "Remove selected")
    assert "not deleted" in remove.toolTip()
