"""Menu bar helpers for The Entire World Tech Connector.

The menu bar exposes capability groups instead of implementation details:
project work, AI/runtime controls, direct DCC/application connections,
pipelines, and community-distributed tools.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QMenuBar, QMessageBox

from tech_connector.models.constants import APP_ROOT, LOGO_PATH


def _call_if_present(window, method_name: str) -> Callable:
    def _wrapped(*_args, **_kwargs):
        fn = getattr(window, method_name, None)
        if callable(fn):
            return fn()
        QMessageBox.information(
            window,
            "Action unavailable",
            f"This build does not expose `{method_name}` yet.",
        )
        return None

    return _wrapped


def _add_if_present(menu, label: str, window, method_name: str):
    return menu.addAction(label, _call_if_present(window, method_name))


def _app_icon(app_id: str) -> QIcon:
    icon_dir = APP_ROOT / "assets" / "app_icons"
    for suffix in (".png", ".svg", ".ico"):
        path = icon_dir / f"{app_id}{suffix}"
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def _add_app_menu(parent, label: str, app_id: str):
    menu = parent.addMenu(label)
    icon = _app_icon(app_id)
    if not icon.isNull():
        menu.setIcon(icon)
    return menu


def _install_menu_timing(menu, window, label: str) -> None:
    if getattr(menu, "_tc_timing_installed", False):
        return
    menu._tc_timing_installed = True

    def mark_open():
        menu._tc_open_started = time.perf_counter()

    def mark_close():
        started = getattr(menu, "_tc_open_started", None)
        if not started:
            return
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if elapsed_ms > 250 and hasattr(window, "record_ui_diagnostic_event"):
            window.record_ui_diagnostic_event(
                "menu_visible",
                {"menu": label, "duration_ms": elapsed_ms, "actions": len(menu.actions())},
            )

    menu.aboutToShow.connect(mark_open)
    menu.aboutToHide.connect(mark_close)


def _install_menu_bar_timing(menu_bar: QMenuBar, window) -> None:
    for action in menu_bar.actions():
        menu = action.menu()
        if not menu:
            continue
        label = action.text().replace("&", "")
        _install_menu_timing(menu, window, label)
        for child_action in menu.actions():
            child_menu = child_action.menu()
            if child_menu:
                _install_menu_timing(child_menu, window, f"{label} > {child_action.text().replace('&', '')}")



def _open_prompt_assistant(window):
    """Open the optional Prompt Assistant without changing the default chat UI."""
    try:
        from tech_connector.ui.prompt_assistant_dialog import PromptAssistantDialog
    except Exception as exc:
        QMessageBox.warning(window, "Prompt Assistant unavailable", str(exc))
        return None
    dialog = getattr(window, "_prompt_assistant_dialog", None)
    if dialog is None:
        dialog = PromptAssistantDialog(window)
        window._prompt_assistant_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog



def _open_terminal(window, command: str = ""):
    fn = getattr(window, "open_terminal_dialog", None)
    if callable(fn):
        return fn(command=command)
    try:
        from tech_connector.ui.interactive_terminal_dialog import InteractiveTerminalDialog
    except Exception as exc:
        QMessageBox.warning(window, "Terminal unavailable", str(exc))
        return None
    dialog = getattr(window, "_interactive_terminal_dialog", None)
    if dialog is None:
        cwd = ""
        if hasattr(window, "active_project_root_path"):
            try:
                cwd = window.active_project_root_path()
            except Exception:
                cwd = ""
        dialog = InteractiveTerminalDialog(window, cwd=cwd)
        window._interactive_terminal_dialog = dialog
    if command:
        dialog.stage_command(command)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def _show_about_dialog(window) -> None:
    box = QMessageBox(window)
    box.setWindowTitle("About Tech Connector")
    box.setText("The Entire World Tech Connector v6.7")
    box.setInformativeText(
        "Created and owned by The Entire World.\n\n"
        "Maya - Unreal - Blender - MotionBuilder - AST Knowledge Index - Pipeline Assistant\n\n"
        "Website:\n"
        "https://theentireworld.net\n\n"
        "GitHub:\n"
        "https://github.com/DankHill2020/TheEntireWorld"
    )
    if LOGO_PATH.exists():
        box.setIconPixmap(
            QPixmap(str(LOGO_PATH)).scaled(
                72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
    box.exec()


def _switch_to_tab(window, tab_name: str):
    tabs = getattr(window, "workspace_tabs", None)
    if tabs is None:
        return
    if hasattr(window, "set_workspace_tab_visible"):
        try:
            window.set_workspace_tab_visible(tab_name, True)
        except Exception:
            pass
    for index in range(tabs.count()):
        if tabs.tabText(index).strip().lower() == tab_name.strip().lower():
            tabs.setCurrentIndex(index)
            return


def _toggle_attr(attr):
    def _wrapped(window):
        widget = getattr(window, attr, None)
        if widget is not None:
            widget.setChecked(not widget.isChecked())
    return _wrapped


def _populate_deferred_menu(menu, builder, window, label: str) -> None:
    if getattr(menu, "_tc_deferred_built", False):
        return
    started = time.perf_counter()
    menu.clear()
    menu._tc_deferred_built = True
    builder(menu)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if elapsed_ms > 100 and hasattr(window, "record_ui_diagnostic_event"):
        window.record_ui_diagnostic_event(
            "menu_populate",
            {"menu": label, "duration_ms": elapsed_ms, "actions": len(menu.actions())},
        )


def _install_deferred_menu(menu, builder, window, label: str) -> None:
    if getattr(menu, "_tc_deferred_installed", False):
        return
    menu._tc_deferred_installed = True
    menu.addAction("Loading...").setEnabled(False)
    menu.aboutToShow.connect(lambda: _populate_deferred_menu(menu, builder, window, label))


def _populate_connected_applications_menu(menu, window) -> None:
    dcc_group = menu.addMenu("DCC")
    engine_group = menu.addMenu("Engine")
    ops_group = menu.addMenu("Ops")
    messaging_group = menu.addMenu("Messaging")
    _add_if_present(ops_group, "Add Integration Package...", window, "show_add_integration_package_dialog")
    _add_if_present(ops_group, "GitHub Login...", window, "show_github_login_dialog")
    _add_if_present(ops_group, "Notification Outputs...", window, "show_notification_outputs_dialog")
    _add_if_present(ops_group, "Atlassian Settings...", window, "show_atlassian_settings_dialog")
    _add_if_present(ops_group, "Create Jira Task from Prompt...", window, "show_create_jira_task_from_prompt_dialog")
    _add_if_present(ops_group, "Upload to Confluence...", window, "show_upload_to_confluence_dialog")
    _add_if_present(ops_group, "Backend Operation Log...", window, "show_backend_log_dialog")
    _add_if_present(messaging_group, "Add Messaging Integration...", window, "show_add_integration_package_dialog")
    _add_if_present(messaging_group, "Slack Login...", window, "show_slack_login_dialog")
    _add_if_present(messaging_group, "Discord Login...", window, "show_discord_login_dialog")
    _add_if_present(messaging_group, "Notification Outputs...", window, "show_notification_outputs_dialog")

    unreal_menu = _add_app_menu(engine_group, "Unreal Engine", "unreal")
    _add_if_present(unreal_menu, "Open Unreal Engine", window, "launch_unreal")
    unreal_menu.addSeparator()
    _add_if_present(unreal_menu, "Start / Stop Unreal Indexer", window, "toggle_unreal_daemon")
    _add_if_present(unreal_menu, "Scan Project", window, "trigger_daemon_scan")
    _add_if_present(unreal_menu, "Index Unreal Docs", window, "refresh_unreal_docs_cache")
    _add_if_present(unreal_menu, "Snapshot Project", window, "maybe_auto_snapshot_unreal")
    _add_if_present(unreal_menu, "Capability Validation", window, "show_unreal_capability_validation")

    maya_menu = _add_app_menu(dcc_group, "Maya", "maya")
    _add_if_present(maya_menu, "Open Maya", window, "launch_maya")
    maya_menu.addSeparator()
    _add_if_present(maya_menu, "Selection", window, "direct_maya_selection")
    _add_if_present(maya_menu, "Current File", window, "direct_maya_file")
    _add_if_present(maya_menu, "Scene Objects", window, "direct_maya_scene_objects")

    blender_menu = _add_app_menu(dcc_group, "Blender", "blender")
    _add_if_present(blender_menu, "Open Blender", window, "launch_blender")
    blender_menu.addSeparator()
    _add_if_present(blender_menu, "Install Startup Bridge", window, "install_blender_bridge_from_menu")
    _add_if_present(blender_menu, "Copy Script Editor Setup", window, "copy_blender_script_editor_setup")

    substance_menu = _add_app_menu(dcc_group, "Substance Painter", "substance_painter")
    _add_if_present(substance_menu, "Open Substance Painter", window, "launch_substance_painter")
    substance_menu.addSeparator()
    _add_if_present(substance_menu, "Install Bridge Plugin", window, "install_substance_painter_bridge_from_menu")
    _add_if_present(substance_menu, "Copy Setup Snippet", window, "copy_substance_painter_script_editor_setup")

    unity_menu = _add_app_menu(engine_group, "Unity", "unity")
    _add_if_present(unity_menu, "Open Unity", window, "launch_unity")
    unity_menu.addSeparator()
    _add_if_present(unity_menu, "Selection", window, "direct_unity_selection")
    _add_if_present(unity_menu, "Current Scene", window, "direct_unity_scene")
    _add_if_present(unity_menu, "Scene GameObjects", window, "direct_unity_scene_objects")

    houdini_menu = _add_app_menu(dcc_group, "Houdini", "houdini")
    _add_if_present(houdini_menu, "Open Houdini", window, "launch_houdini")
    houdini_menu.addSeparator()
    _add_if_present(houdini_menu, "Selection", window, "direct_houdini_selection")
    _add_if_present(houdini_menu, "Current File", window, "direct_houdini_file")
    _add_if_present(houdini_menu, "Scene Nodes", window, "direct_houdini_scene_objects")
    _add_if_present(houdini_menu, "Context Summary", window, "direct_houdini_context_summary")
    _add_if_present(houdini_menu, "Call / Execute", window, "direct_houdini_call_from_text")
    _add_if_present(houdini_menu, "Undo Last Command", window, "direct_houdini_undo")

    mobu_menu = _add_app_menu(dcc_group, "MotionBuilder", "motionbuilder")
    _add_if_present(mobu_menu, "Open MotionBuilder", window, "launch_motionbuilder")
    mobu_menu.addSeparator()
    _add_if_present(mobu_menu, "Selection", window, "direct_motionbuilder_selection")
    _add_if_present(mobu_menu, "Current File", window, "direct_motionbuilder_file")
    _add_if_present(mobu_menu, "Scene Objects", window, "direct_motionbuilder_scene_objects")
    _add_if_present(mobu_menu, "Takes", window, "direct_motionbuilder_takes")
    _add_if_present(mobu_menu, "Characters", window, "direct_motionbuilder_characters")


def _rebuild_workspace_visibility_menu(window, menu):
    tabs = getattr(window, "workspace_tabs", None)
    if tabs is None:
        if getattr(menu, "_tc_visibility_signature", None) == ("missing",):
            return
        menu._tc_visibility_signature = ("missing",)
        menu.clear()
        menu.addAction("No workspace tabs available").setEnabled(False)
        return
    titles = []
    if hasattr(tabs, "workspace_tab_titles"):
        titles = tabs.workspace_tab_titles()
    else:
        titles = [tabs.tabText(i) for i in range(tabs.count())]
    if not titles:
        if getattr(menu, "_tc_visibility_signature", None) == ("empty",):
            return
        menu._tc_visibility_signature = ("empty",)
        menu.clear()
        menu.addAction("No workspace tabs available").setEnabled(False)
        return
    visibility = []
    for title in titles:
        visible = True
        if hasattr(window, "is_workspace_tab_visible"):
            visible = window.is_workspace_tab_visible(title)
        visibility.append((title, bool(visible)))
    signature = tuple(visibility)
    if getattr(menu, "_tc_visibility_signature", None) == signature:
        return
    menu._tc_visibility_signature = signature
    menu.clear()
    for title, visible in visibility:
        action = QAction(title, menu)
        action.setCheckable(True)
        action.setChecked(visible)
        action.triggered.connect(lambda checked=False, t=title: window.set_workspace_tab_visible(t, checked))
        menu.addAction(action)


def build_main_menu_bar(window) -> QMenuBar:
    """Return a QMenuBar suitable for a QWidget-based main window."""

    menu_bar = QMenuBar(window)

    file_menu = menu_bar.addMenu("File")
    _add_if_present(file_menu, "New Chat", window, "new_chat")
    _add_if_present(file_menu, "Save Chat", window, "save_history")
    file_menu.addSeparator()
    file_menu.addAction("Prompt Assistant...", lambda: _open_prompt_assistant(window))
    file_menu.addAction("Open Terminal...", lambda: _open_terminal(window))
    file_menu.addSeparator()
    _add_if_present(file_menu, "Settings...", window, "show_settings_dialog")
    file_menu.addSeparator()
    file_menu.addAction("Exit", window.close)

    project_menu = menu_bar.addMenu("Project")
    _add_if_present(project_menu, "Load Project", window, "choose_project")
    _add_if_present(project_menu, "Update Project", window, "update_project")
    _add_if_present(project_menu, "Project Directories...", window, "show_first_run")
    project_menu.addSeparator()
    _add_if_present(project_menu, "Refresh Project Tree", window, "refresh_project_tree_fast")
    _add_if_present(project_menu, "Open Project Folder", window, "open_active_project_folder")

    ai_menu = menu_bar.addMenu("AI")
    _add_if_present(ai_menu, "AI / Model Settings...", window, "show_settings_dialog")
    _add_if_present(ai_menu, "Health Check", window, "health_check")
    activity_action = QAction("Show Activity Details", ai_menu)
    activity_action.setCheckable(True)
    activity_action.setChecked(bool(getattr(window, "settings", {}).get("show_activity_details", True)))
    activity_action.setToolTip(
        "Show observable activity: tools checked, files/functions/classes considered, DCC context inspected, and planned patch targets. "
        "This is not hidden chain-of-thought."
    )
    activity_action.triggered.connect(lambda checked: window.set_show_activity_details(checked) if hasattr(window, "set_show_activity_details") else None)
    ai_menu.addAction(activity_action)
    ai_menu.addSeparator()
    _add_if_present(ai_menu, "Start MCPHost", window, "start_mcphost")
    _add_if_present(ai_menu, "Stop MCPHost", window, "stop_mcphost")
    ai_menu.addAction(
        "Prime Models",
        lambda: window.send_raw(window.prime_editor.toPlainText(), "Prime")
        if hasattr(window, "prime_editor")
        else None,
    )

    safety_menu = ai_menu.addMenu("Model & Safety")
    safety_menu.addAction("Open Settings...", _call_if_present(window, "show_settings_dialog"))
    safety_menu.addSeparator()
    safety_menu.addAction("Toggle Local-Only Model", lambda: _toggle_attr("_chk_local_only")(window))
    safety_menu.addAction("Toggle Project Modifications", lambda: _toggle_attr("_chk_allow_modifications")(window))
    safety_menu.addAction("Toggle Confirmation Before Changes", lambda: _toggle_attr("_chk_require_confirm")(window))
    safety_menu.addAction("Toggle GitHub / Tool Search", lambda: _toggle_attr("_chk_github_search")(window))


    terminal_menu = menu_bar.addMenu("Terminal")
    terminal_menu.addAction("Open Terminal...", lambda: _open_terminal(window))
    terminal_menu.addAction("Stage Prompt in Terminal", _call_if_present(window, "run_prompt_in_terminal"))
    terminal_menu.addAction("Stage Selection in Terminal", _call_if_present(window, "run_selection_in_terminal"))
    terminal_menu.addAction("Stage Current File Command", _call_if_present(window, "run_current_file_in_terminal"))

    knowledge_menu = menu_bar.addMenu("Knowledge")
    _add_if_present(knowledge_menu, "Quick Index", window, "build_index")
    _add_if_present(knowledge_menu, "Rebuild Dependency Graph", window, "build_dependency_graph_only")
    knowledge_menu.addSeparator()
    _add_if_present(knowledge_menu, "Knowledge Summary", window, "show_ai_knowledge_summary")
    _add_if_present(knowledge_menu, "Lock Current Knowledge", window, "lock_ai_knowledge_snapshot")

    pipelines_menu = menu_bar.addMenu("Pipelines")
    pipelines_menu.addAction("Open Pipelines Tab", lambda: _switch_to_tab(window, "Pipelines"))
    _add_if_present(pipelines_menu, "Create New Pipeline", window, "start_new_workflow_builder")
    _add_if_present(pipelines_menu, "Refresh Pipelines", window, "refresh_workflows_list")
    _add_if_present(pipelines_menu, "Upload Documentation to Confluence...", window, "show_upload_to_confluence_dialog")
    pipelines_menu.addSeparator()
    pipelines_menu.addAction("Pipeline Settings...", _call_if_present(window, "show_settings_dialog"))

    tools_menu = menu_bar.addMenu("Tools")


    terminal_tools_menu = tools_menu.addMenu("Terminal Tools")
    terminal_tools_menu.addAction("Open Terminal...", lambda: _open_terminal(window))
    terminal_tools_menu.addAction("Stage Prompt in Terminal", _call_if_present(window, "run_prompt_in_terminal"))
    terminal_tools_menu.addAction("Stage Selection in Terminal", _call_if_present(window, "run_selection_in_terminal"))
    terminal_tools_menu.addAction("Stage Current File Command", _call_if_present(window, "run_current_file_in_terminal"))

    studio_menu = tools_menu.addMenu("Tech Connector Tools")
    _add_if_present(studio_menu, "Install Components", window, "install_components")
    _add_if_present(studio_menu, "Diagnostics / Health Check", window, "health_check")
    _add_if_present(studio_menu, "Add Missing Docstrings", window, "add_docstrings_to_current_file")
    studio_menu.addSeparator()
    _add_if_present(studio_menu, "Start Mobile Second Screen", window, "start_mobile_second_screen")
    _add_if_present(studio_menu, "Open Mobile Download QR", window, "open_mobile_download_qr")
    _add_if_present(studio_menu, "Stop Mobile Second Screen", window, "stop_mobile_second_screen")
    studio_menu.addSeparator()
    _add_if_present(studio_menu, "VCS Accounts / Login", window, "show_vcs_accounts_dialog")
    _add_if_present(studio_menu, "Backend Operation Log...", window, "show_backend_log_dialog")
    if hasattr(window, "set_ui_diagnostic_mode"):
        diagnostic_action = studio_menu.addAction("UI Diagnostic Mode")
        diagnostic_action.setCheckable(True)
        try:
            diagnostic_action.setChecked(bool(window.settings.get("ui_diagnostic_mode", False)))
        except Exception:
            diagnostic_action.setChecked(False)
        diagnostic_action.toggled.connect(window.set_ui_diagnostic_mode)
    _add_if_present(studio_menu, "Show UI Diagnostic Report...", window, "show_ui_diagnostic_report")
    _add_if_present(studio_menu, "Clear UI Diagnostic Report", window, "clear_ui_diagnostic_report")
    _add_if_present(studio_menu, "Create Changelist from Updated Files...", window, "create_vcs_changelist_dialog")
    _add_if_present(studio_menu, "View Current Changelists...", window, "show_vcs_changelists_dialog")

    connected_apps_menu = tools_menu.addMenu("Connected Applications")
    connected_apps_menu.setToolTip(
        "Direct connections to external creative and development applications that Tech Connector can inspect, control, or automate."
    )
    _install_deferred_menu(
        connected_apps_menu,
        lambda menu: _populate_connected_applications_menu(menu, window),
        window,
        "Tools > Connected Applications",
    )

    updates_menu = tools_menu.addMenu("App Updates")
    _add_if_present(updates_menu, "Check App Git Status", window, "check_app_update_status")
    _add_if_present(updates_menu, "Update from Latest", window, "update_app_from_latest")
    _add_if_present(updates_menu, "Update from Git Ref...", window, "update_app_from_git_ref")

    community_menu = menu_bar.addMenu("Community")
    community_tools = community_menu.addMenu("Community Tools")
    community_tools.setToolTip(
        "Discover, install, share, and launch tools created outside the Tech Connector core. "
        "Community Tools can come from GitHub, local folders, or other developers and can be used in your projects and pipelines."
    )
    _add_if_present(community_tools, "Browse / Import from GitHub...", window, "trigger_web_import")
    _add_if_present(community_tools, "Install Local Tool...", window, "trigger_web_import")
    _add_if_present(community_tools, "Add Integration Package...", window, "show_add_integration_package_dialog")
    _add_if_present(community_tools, "Installed Community Tools", window, "trigger_web_import")
    community_tools.addSeparator()
    _add_if_present(community_tools, "Publish Tool...", window, "trigger_web_import")

    window_menu = menu_bar.addMenu("Window")
    window_menu.addAction("Prompt Assistant...", lambda: _open_prompt_assistant(window))
    window_menu.addSeparator()
    _add_if_present(window_menu, "Show / Hide System Status", window, "toggle_system_status_panel")
    window_menu.addSeparator()
    visible_tabs_menu = window_menu.addMenu("Visible Workspace Tabs")
    visible_tabs_menu.setToolTip("Choose which workspace tabs are visible. Hidden tabs keep their state and can be restored here.")
    visible_tabs_menu.addAction("Loading tabs...").setEnabled(False)
    visible_tabs_menu.aboutToShow.connect(
        lambda: QTimer.singleShot(0, lambda: _rebuild_workspace_visibility_menu(window, visible_tabs_menu))
    )
    window_menu.addAction("Anchor Current Tab Right", _call_if_present(window, "anchor_current_workspace_tab_right"))
    window_menu.addAction("Detach Current Tab", _call_if_present(window, "detach_current_workspace_tab"))
    window_menu.addAction("Close Anchored Tab Pane", _call_if_present(window, "close_workspace_anchor"))
    window_menu.addAction("Reattach All Detached Tabs", _call_if_present(window, "reattach_all_workspace_tabs"))
    window_menu.addAction("Show All Tabs", _call_if_present(window, "show_all_workspace_tabs"))
    window_menu.addSeparator()
    window_menu.addAction(
        "Toggle Full Screen",
        lambda: window.toggle_fullscreen_mode(not window.isFullScreen())
        if hasattr(window, "toggle_fullscreen_mode")
        else None,
    )

    # Keep View as a light alias for users who expect display controls there.
    view_menu = menu_bar.addMenu("View")
    view_menu.addAction("Window / Layout Options", lambda: window_menu.exec(window.mapToGlobal(window.rect().topLeft())))
    _add_if_present(view_menu, "Show / Hide System Status", window, "toggle_system_status_panel")

    help_menu = menu_bar.addMenu("Help")
    _add_if_present(help_menu, "Health Check", window, "health_check")
    _add_if_present(help_menu, "Model Provider Setup", window, "show_model_provider_setup")
    help_menu.addSeparator()
    help_menu.addAction(
        "About The Entire World Tech Connector",
        lambda: _show_about_dialog(window),
    )

    _install_menu_bar_timing(menu_bar, window)
    return menu_bar


def install_main_menu(window) -> QMenuBar:
    """Install a menu bar into the current QWidget-based layout."""
    menu_bar = build_main_menu_bar(window)
    layout = window.layout()
    if layout is not None:
        layout.setMenuBar(menu_bar)
    controls = getattr(window, "menu_bar_controls_widget", None)
    if controls is not None:
        menu_bar.setCornerWidget(controls, Qt.TopRightCorner)
        top_section = getattr(window, "top_section_widget", None)
        if top_section is not None:
            top_section.setVisible(False)
    return menu_bar
