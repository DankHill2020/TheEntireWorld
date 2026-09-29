"""Post-build UI layout refinements for Tech Connector.

This module intentionally works after the existing monolithic build_ui() has
created widgets. It lets us clean up the visible UI without rewriting the full
main window constructor yet.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button, icon


ADVANCED_BUTTON_TEXTS = {
    "Project Dirs",
    "Install Components",
    "Build/Rebuild Index",
    "Scan Project",
    "Index Docs",
    "Unreal Cc",
    "Unreal C++",
}

ADVANCED_CHECKBOX_TEXTS = {
    "Show reasoning summary",
    "Use fallback models",
    "Web/GitHub",
    "Use C++",
    "Use PTY",
}

STATUS_CARD_KEYS = (
    "ollama",
    "mcphost",
    "knowledge",
    "vcs",
    "maya",
    "unreal",
    "unreal_daemon",
    "blender",
    "substance_painter",
    "motionbuilder",
    "integrations",
)


def apply_main_window_layout_refinement(window) -> None:
    """Apply final UI polish after build_ui() has run."""
    _install_status_visibility_api(window)
    _install_system_status_toggle(window)
    _move_project_actions_to_left_panel(window)
    _simplify_project_width_controls(window)
    _hide_advanced_top_controls(window)
    _apply_saved_system_status_visibility(window)
    from tech_connector.ui.ux_polish import apply_main_window_ux_polish
    apply_main_window_ux_polish(window)


def _install_status_visibility_api(window) -> None:
    def set_system_status_visible(visible: bool):
        visible = bool(visible)
        try:
            window.settings["show_system_status"] = visible
            window.service.save_settings(window.settings)
        except Exception:
            pass

        details = getattr(window, "bottom_status_details_widget", None)
        if details:
            details.setVisible(visible)
        else:
            for card in getattr(window, "status_cards", {}).values():
                try:
                    card.setVisible(visible)
                except Exception:
                    pass
            for attr in (
                "index_status",
                "index_progress",
                "active_model_label",
                "model_requirement_label",
            ):
                widget = getattr(window, attr, None)
                if widget:
                    widget.setVisible(visible)

        btn = getattr(window, "system_status_toggle_btn", None)
        if btn:
            btn.blockSignals(True)
            btn.setChecked(visible)
            btn.setText("Hide details" if visible else "Show details")
            btn.setIcon(icon("chevron_up" if visible else "chevron_down"))
            btn.blockSignals(False)

        action = getattr(window, "status_action", None)
        if action:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)

    window.set_system_status_visible = set_system_status_visible


def _install_system_status_toggle(window) -> None:
    """Install or wire the status visibility toggle in the bottom status panel.

    Earlier versions inserted a System Status strip above the header. The UI now
    keeps status/reporting in the bottom panel, so this function avoids adding a
    second top strip and simply wires the bottom toggle if build_ui created one.
    """
    bottom_toggle = getattr(window, "bottom_system_status_toggle_btn", None)
    if bottom_toggle:
        window.system_status_toggle_btn = bottom_toggle
        return

    if getattr(window, "system_status_header", None):
        return

    bottom = getattr(window, "bottom_controls_widget", None)
    if not bottom or not bottom.layout():
        return

    header = QFrame()
    header.setObjectName("systemStatusHeader")
    row = QHBoxLayout(header)
    row.setContentsMargins(8, 4, 8, 4)
    row.setSpacing(8)

    title = QLabel("System Status")
    set_ui_role(title, "sectionTitle")
    row.addWidget(title)

    detail = QLabel("routing • model • knowledge • DCC • VCS")
    set_ui_role(detail, "muted")
    row.addWidget(detail, 1)

    btn = QToolButton()
    btn.setCheckable(True)
    btn.setChecked(bool(getattr(window, "settings", {}).get("show_system_status", False)))
    configure_button(
        btn,
        "chevron_up" if btn.isChecked() else "chevron_down",
        text="Hide details" if btn.isChecked() else "Show details",
        role="quiet",
    )
    btn.toggled.connect(window.set_system_status_visible)
    row.addWidget(btn)

    window.system_status_header = header
    window.system_status_toggle_btn = btn
    bottom.layout().insertWidget(0, header)

def _move_project_actions_to_left_panel(window) -> None:
    if getattr(window, "project_panel_extra_actions", None):
        return
    project_root_label = getattr(window, "project_root_label", None)
    if not project_root_label:
        return
    left_widget = project_root_label.parentWidget()
    if not left_widget or not left_widget.layout():
        return
    layout = left_widget.layout()

    actions_frame = QFrame()
    actions_frame.setObjectName("projectPanelActions")
    outer = QVBoxLayout(actions_frame)
    outer.setContentsMargins(8, 6, 8, 6)
    outer.setSpacing(6)

    label = QLabel("Project Tools")
    set_ui_role(label, "sectionTitle")
    outer.addWidget(label)

    row1 = QHBoxLayout()
    dirs_btn = QPushButton("Project Dirs")
    configure_button(dirs_btn, "folder", text="Directories", role="secondary")
    dirs_btn.clicked.connect(window.show_first_run)
    row1.addWidget(dirs_btn)
    index_btn = QPushButton("Quick Index")
    configure_button(index_btn, "database", text="Quick index", role="secondary")
    index_btn.clicked.connect(window.build_index)
    row1.addWidget(index_btn)
    outer.addLayout(row1)

    row2 = QHBoxLayout()
    graph_btn = QPushButton("Graph")
    configure_button(graph_btn, "graph", text="Graph", role="secondary")
    if hasattr(window, "build_dependency_graph_only"):
        graph_btn.clicked.connect(window.build_dependency_graph_only)
    else:
        from tech_connector.ui.ux_polish import explain_disabled
        explain_disabled(graph_btn, "Build the knowledge index before creating a dependency graph.")
    row2.addWidget(graph_btn)
    install_btn = QPushButton("Install")
    configure_button(install_btn, "package", text="Install", role="secondary")
    install_btn.clicked.connect(window.install_components)
    row2.addWidget(install_btn)
    outer.addLayout(row2)

    window.project_panel_extra_actions = actions_frame
    window.project_dirs_panel_btn = dirs_btn
    window.project_quick_index_btn = index_btn
    window.project_graph_btn = graph_btn
    window.project_install_btn = install_btn

    insert_after = layout.indexOf(project_root_label) + 1
    if insert_after <= 0:
        insert_after = 1
    # Put tools after the Load/Update row if possible, otherwise after root label.
    for i in range(layout.count()):
        item = layout.itemAt(i)
        child = item.widget() if item else None
        if child and child.metaObject().className() == "QComboBox":
            insert_after = i
            break
    layout.insertWidget(insert_after, actions_frame)


def _simplify_project_width_controls(window) -> None:
    """Keep only the explicit Hide/Show project panel control."""
    for button in window.findChildren(QPushButton):
        if (button.text() or "").strip() in {"Narrow", "Wide"}:
            button.setVisible(False)


def _hide_advanced_top_controls(window) -> None:
    for button in window.findChildren(QPushButton):
        text = (button.text() or "").strip()
        if text in ADVANCED_BUTTON_TEXTS:
            if button in {
                getattr(window, "project_dirs_panel_btn", None),
                getattr(window, "project_quick_index_btn", None),
                getattr(window, "project_graph_btn", None),
                getattr(window, "project_install_btn", None),
            }:
                continue
            button.setVisible(False)

    for checkbox in window.findChildren(QCheckBox):
        text = (checkbox.text() or "").strip()
        if text in ADVANCED_CHECKBOX_TEXTS:
            checkbox.setVisible(False)


def _apply_saved_system_status_visibility(window) -> None:
    visible = bool(getattr(window, "settings", {}).get("show_system_status", False))
    if hasattr(window, "set_system_status_visible"):
        window.set_system_status_visible(visible)
