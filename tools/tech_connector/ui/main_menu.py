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
from PySide6.QtWidgets import QMenu, QMenuBar, QMessageBox

from tech_connector.models.constants import APP_ROOT, LOGO_PATH

THE_GARDEN_DCC_VIEWER_NAME = "The Garden"
THE_GARDEN_DCC_VIEWER_WINDOW_TITLE = "The Garden - Adaptive DCC Scene"


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
    fn = getattr(window, method_name, None)
    if not callable(fn):
        return None
    return menu.addAction(label, fn)


def _add_checkable_attr_action(menu, label: str, window, attr: str):
    widget = getattr(window, attr, None)
    if widget is None:
        return None
    action = QAction(label, menu)
    action.setCheckable(True)
    try:
        action.setChecked(bool(widget.isChecked()))
    except Exception:
        action.setChecked(False)
    action.toggled.connect(lambda checked: widget.setChecked(bool(checked)))
    menu.addAction(action)
    return action


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


def _add_top_menu(menu_bar: QMenuBar, title: str) -> QMenu:
    menu = QMenu(title, menu_bar)
    menu_bar.addMenu(menu)
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


def _retain_menu_tree(window, menu_bar: QMenuBar) -> None:
    retained = getattr(window, "_tc_retained_menus", None)
    if retained is None:
        retained = []
        window._tc_retained_menus = retained

    def retain(menu):
        if menu is None or menu in retained:
            return
        retained.append(menu)
        for action in menu.actions():
            retain(action.menu())

    for action in menu_bar.actions():
        retain(action.menu())



def _open_image_editor_window(window, image_path: str = ""):
    try:
        from tech_connector.ui.image_editor_widget import ImageEditorWindow
        return ImageEditorWindow.open_for_image(image_path, window)
    except Exception as exc:
        QMessageBox.warning(window, "Ophanim unavailable", str(exc))
        return None


def _open_mesh_painter_window(window):
    try:
        from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport
    except Exception as exc:
        QMessageBox.warning(window, f"{THE_GARDEN_DCC_VIEWER_NAME} unavailable", str(exc))
        return None
    mesh_window = getattr(window, "_mesh_painter_window", None)
    try:
        if mesh_window is None or not mesh_window.isVisible():
            mesh_window = ThreeDMeshPainterViewport(window)
            mesh_window.setWindowFlags(Qt.Window)
            mesh_window.setWindowTitle(THE_GARDEN_DCC_VIEWER_WINDOW_TITLE)
            mesh_window.resize(1180, 760)
            window._mesh_painter_window = mesh_window
        mesh_window.show()
        mesh_window.raise_()
        mesh_window.activateWindow()
        return mesh_window
    except Exception as exc:
        QMessageBox.warning(window, f"{THE_GARDEN_DCC_VIEWER_NAME} unavailable", str(exc))
        return None


def _open_dcc_driver(window, host: str = ""):
    fn = getattr(window, "show_dcc_driver_dialog", None)
    if callable(fn):
        return fn(host)
    try:
        from tech_connector.ui.dcc_driver_widget import open_dcc_driver_dialog
    except Exception as exc:
        QMessageBox.warning(window, "DCC Driver unavailable", str(exc))
        return None
    return open_dcc_driver_dialog(window, initial_host=host)


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
        "Maya - Unreal - Blender - MotionBuilder - Root System Index - Branching Assistant\n\n"
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
    retained = getattr(window, "_tc_retained_menus", None)
    if retained is None:
        retained = []
        window._tc_retained_menus = retained
    retained.append(menu)
    menu.addAction("Loading...").setEnabled(False)
    menu.aboutToShow.connect(lambda: _populate_deferred_menu(menu, builder, window, label))


def _populate_connected_applications_menu(menu, window) -> None:
    _add_if_present(menu, "Capability Status...", window, "show_connected_application_status_dialog")
    menu.addAction("DCC Driver / Second Screen...", lambda: _open_dcc_driver(window))
    menu.addSeparator()
    dcc_group = menu.addMenu("DCC")
    engine_group = menu.addMenu("Engine")
    services_group = menu.addMenu("Services")
    messaging_group = menu.addMenu("Messaging")
    _add_if_present(services_group, "Add Integration Package...", window, "show_add_integration_package_dialog")
    _add_if_present(services_group, "GitHub Login...", window, "show_github_login_dialog")
    _add_if_present(services_group, "Atlassian Settings...", window, "show_atlassian_settings_dialog")
    _add_if_present(services_group, "Create Jira Task from Prompt...", window, "show_create_jira_task_from_prompt_dialog")
    _add_if_present(services_group, "Upload to Confluence...", window, "show_upload_to_confluence_dialog")
    _add_if_present(messaging_group, "Slack Login...", window, "show_slack_login_dialog")
    _add_if_present(messaging_group, "Discord Login...", window, "show_discord_login_dialog")
    _add_if_present(messaging_group, "Notification Outputs...", window, "show_notification_outputs_dialog")

    unreal_menu = _add_app_menu(engine_group, "Unreal Engine", "unreal")
    _add_if_present(unreal_menu, "Open Unreal Engine", window, "launch_unreal")
    unreal_menu.addSeparator()
    setup_menu = unreal_menu.addMenu("Setup")
    inspect_menu = unreal_menu.addMenu("Inspect")
    actions_menu = unreal_menu.addMenu("Actions")
    _add_if_present(setup_menu, "Start / Stop Indexer", window, "toggle_unreal_daemon")
    _add_if_present(setup_menu, "Index Unreal Docs", window, "refresh_unreal_docs_cache")
    _add_if_present(setup_menu, "Capability Validation", window, "show_unreal_capability_validation")
    _add_if_present(inspect_menu, "Scan Project", window, "trigger_daemon_scan")
    _add_if_present(inspect_menu, "Snapshot Project", window, "direct_unreal_project_snapshot")
    _add_if_present(inspect_menu, "Project Asset Scan", window, "direct_unreal_project_scan")
    _add_if_present(inspect_menu, "Loaded Level Scan", window, "direct_unreal_level_scan")
    _add_if_present(inspect_menu, "Inspect Asset / Blueprint", window, "direct_unreal_inspect_asset_from_text")
    _add_if_present(inspect_menu, "Skeletons", window, "direct_unreal_get_skeletons")
    _add_if_present(inspect_menu, "Meshes", window, "direct_unreal_get_static_meshes")
    _add_if_present(actions_menu, "Run Function", window, "direct_unreal_call_from_text")
    _add_if_present(actions_menu, "Undo Last Command", window, "direct_unreal_undo")
    advanced_unreal = unreal_menu.addMenu("Advanced")
    _add_if_present(advanced_unreal, "Create Python Wrapper from C++", window, "direct_unreal_create_cpp_wrapper_from_text")
    _add_if_present(advanced_unreal, "Safe Operation Catalog", window, "show_unreal_operation_catalog")

    maya_menu = _add_app_menu(dcc_group, "Maya", "maya")
    _add_if_present(maya_menu, "Open Maya", window, "launch_maya")
    maya_menu.addSeparator()
    _add_if_present(maya_menu, "Get Selection", window, "direct_maya_selection")
    _add_if_present(maya_menu, "Get Current File", window, "direct_maya_file")
    _add_if_present(maya_menu, "Get Scene Objects", window, "direct_maya_scene_objects")
    _add_if_present(maya_menu, "Run Command", window, "direct_maya_call_from_text")
    _add_if_present(maya_menu, "Undo Last Command", window, "direct_maya_undo")

    blender_menu = _add_app_menu(dcc_group, "Blender", "blender")
    _add_if_present(blender_menu, "Open Blender", window, "launch_blender")
    blender_menu.addSeparator()
    _add_if_present(blender_menu, "Install Startup Bridge", window, "install_blender_bridge_from_menu")
    _add_if_present(blender_menu, "Copy Script Editor Setup", window, "copy_blender_script_editor_setup")

    max_menu = _add_app_menu(dcc_group, "3ds Max", "3dsmax")
    _add_if_present(max_menu, "Open 3ds Max", window, "launch_3dsmax")
    max_menu.addSeparator()
    _add_if_present(max_menu, "Install Startup Bridge", window, "install_3dsmax_bridge_from_menu")

    substance_menu = _add_app_menu(dcc_group, "Substance Painter", "substance_painter")
    _add_if_present(substance_menu, "Open Substance Painter", window, "launch_substance_painter")
    substance_menu.addAction("Open Driver / Second Screen", lambda: _open_dcc_driver(window, "substance_painter"))
    substance_menu.addSeparator()
    _add_if_present(substance_menu, "Install Bridge Plugin", window, "install_substance_painter_bridge_from_menu")
    _add_if_present(substance_menu, "Copy Setup Snippet", window, "copy_substance_painter_script_editor_setup")

    unity_menu = _add_app_menu(engine_group, "Unity", "unity")
    _add_if_present(unity_menu, "Open Unity", window, "launch_unity")
    unity_menu.addSeparator()
    _add_if_present(unity_menu, "Get Selection", window, "direct_unity_selection")
    _add_if_present(unity_menu, "Get Current Scene", window, "direct_unity_scene")
    _add_if_present(unity_menu, "Get Scene GameObjects", window, "direct_unity_scene_objects")
    _add_if_present(unity_menu, "Run Command", window, "direct_unity_call_from_text")
    _add_if_present(unity_menu, "Undo Last Command", window, "direct_unity_undo")

    houdini_menu = _add_app_menu(dcc_group, "Houdini", "houdini")
    _add_if_present(houdini_menu, "Open Houdini", window, "launch_houdini")
    houdini_menu.addSeparator()
    _add_if_present(houdini_menu, "Get Selection", window, "direct_houdini_selection")
    _add_if_present(houdini_menu, "Get Current File", window, "direct_houdini_file")
    _add_if_present(houdini_menu, "Get Scene Nodes", window, "direct_houdini_scene_objects")
    _add_if_present(houdini_menu, "Context Summary", window, "direct_houdini_context_summary")
    _add_if_present(houdini_menu, "Call / Execute", window, "direct_houdini_call_from_text")
    _add_if_present(houdini_menu, "Undo Last Command", window, "direct_houdini_undo")

    mobu_menu = _add_app_menu(dcc_group, "MotionBuilder", "motionbuilder")
    _add_if_present(mobu_menu, "Open MotionBuilder", window, "launch_motionbuilder")
    mobu_menu.addSeparator()
    _add_if_present(mobu_menu, "Get Selection", window, "direct_motionbuilder_selection")
    _add_if_present(mobu_menu, "Get Current File", window, "direct_motionbuilder_file")
    _add_if_present(mobu_menu, "Get Scene Objects", window, "direct_motionbuilder_scene_objects")
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

    file_menu = _add_top_menu(menu_bar, "File")
    _add_if_present(file_menu, "New Chat", window, "new_chat")
    _add_if_present(file_menu, "Save Chat", window, "save_history")
    file_menu.addSeparator()
    file_menu.addAction("Prompt Assistant...", lambda: _open_prompt_assistant(window))
    file_menu.addSeparator()
    _add_if_present(file_menu, "Settings...", window, "show_settings_dialog")
    _add_if_present(file_menu, "Customization Panel...", window, "show_customization_panel_dialog")
    file_menu.addSeparator()
    file_menu.addAction("Exit", window.close)

    project_menu = _add_top_menu(menu_bar, "Project")
    _add_if_present(project_menu, "Load Project", window, "choose_project")
    _add_if_present(project_menu, "Update Project", window, "update_project")
    _add_if_present(project_menu, "Project Directories...", window, "show_first_run")
    project_menu.addSeparator()
    _add_if_present(project_menu, "Refresh Workspace Roots", window, "refresh_project_tree_fast")
    _add_if_present(project_menu, "Open Project Folder", window, "open_active_project_folder")

    ai_menu = _add_top_menu(menu_bar, "Trunk (Reasoning Engine)")
    _add_if_present(ai_menu, "Local Model Configuration...", window, "show_customization_panel_models")
    _add_if_present(ai_menu, "Cloud AI Setup...", window, "show_customization_panel_cloud")
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

    safety_menu = ai_menu.addMenu("Model & Safety")
    _add_if_present(safety_menu, "Open Settings...", window, "show_settings_dialog")
    safety_menu.addSeparator()
    _add_checkable_attr_action(safety_menu, "Local-Only Model", window, "_chk_local_only")
    _add_checkable_attr_action(safety_menu, "Allow Project Modifications", window, "_chk_allow_modifications")
    _add_checkable_attr_action(safety_menu, "Require Confirmation Before Changes", window, "_chk_require_confirm")
    _add_checkable_attr_action(safety_menu, "Tutorial / Guidance Only", window, "_chk_tutorial_mode")
    _add_checkable_attr_action(safety_menu, "Allow GitHub / Tool Search", window, "_chk_github_search")

    knowledge_menu = _add_top_menu(menu_bar, "Roots")
    _add_if_present(knowledge_menu, "Root Scan", window, "build_index")
    _add_if_present(knowledge_menu, "Rebuild Root System", window, "build_dependency_graph_only")
    knowledge_menu.addSeparator()
    _add_if_present(knowledge_menu, "Root Summary", window, "show_ai_knowledge_summary")
    _add_if_present(knowledge_menu, "Seal Root Record", window, "lock_ai_knowledge_snapshot")

    pipelines_menu = _add_top_menu(menu_bar, "Branches")
    pipelines_menu.addAction("Open Branches (Code Editor) Tab", lambda: _switch_to_tab(window, "Pipelines"))
    _add_if_present(pipelines_menu, "Graft New Branch", window, "start_new_workflow_builder")
    _add_if_present(pipelines_menu, "Refresh Branches", window, "refresh_workflows_list")
    _add_if_present(pipelines_menu, "Upload Documentation to Confluence...", window, "show_upload_to_confluence_dialog")
    pipelines_menu.addSeparator()
    _add_if_present(pipelines_menu, "Branch Settings...", window, "show_settings_dialog")

    apps_menu = _add_top_menu(menu_bar, "Apps")
    apps_menu.setToolTip(
        "Connect to creative and development applications that Tech Connector can inspect, control, or automate."
    )
    _install_deferred_menu(
        apps_menu,
        lambda menu: _populate_connected_applications_menu(menu, window),
        window,
        "Apps",
    )

    tools_menu = _add_top_menu(menu_bar, "Tools")

    tools_menu.addAction("Editor", lambda: _call_if_present(window, "open_editor_workspace_tab"))
    tools_menu.addAction("Search / Symbols", lambda: _call_if_present(window, "open_search_symbols_workspace_tab"))
    tools_menu.addAction("Pipelines", lambda: _call_if_present(window, "open_pipelines_workspace_tab"))
    tools_menu.addSeparator()

    world_action = QAction("The Kingdom (Game Engine Runtime Suite)...", window)
    world_action.setToolTip("Open the Game Engine runtime flow for a scene (.tcscene).")
    world_action.triggered.connect(_call_if_present(window, "open_the_kingdom_workspace_tab"))
    tools_menu.addAction(world_action)

    img_editor_action = QAction("Ophanim (Image & Texture Review Suite)...", window)
    img_editor_action.setShortcut("Ctrl+Shift+I")
    img_editor_action.setToolTip(
        "Open Ophanim for image editing, texture work, PSD inspection, review markups, and PBR inspection."
    )
    img_editor_action.triggered.connect(_call_if_present(window, "open_ophanim_workspace_tab"))
    tools_menu.addAction(img_editor_action)

    mesh_painter_action = QAction(f"{THE_GARDEN_DCC_VIEWER_NAME} (DCC Integration Suite)...", window)
    mesh_painter_action.setToolTip(
        f"Open {THE_GARDEN_DCC_VIEWER_NAME} for adaptive DCC viewport playback, rigging, animation, and engine transfer."
    )
    mesh_painter_action.triggered.connect(_call_if_present(window, "open_garden_workspace_tab"))
    tools_menu.addAction(mesh_painter_action)

    dcc_driver_action = QAction("DCC Driver Suite / Second Screen...", window)
    dcc_driver_action.setToolTip("Open a bridge-powered control surface for Maya, Blender, Substance Painter, Unreal, Unity, Houdini, and MotionBuilder.")
    dcc_driver_action.triggered.connect(lambda: _open_dcc_driver(window))
    tools_menu.addAction(dcc_driver_action)
    tools_menu.addSeparator()

    terminal_tools_menu = tools_menu.addMenu("Terminal Tools")
    terminal_tools_menu.addAction("Open Terminal...", lambda: _open_terminal(window))
    terminal_tools_menu.addAction("Stage Prompt in Terminal", _call_if_present(window, "run_prompt_in_terminal"))
    terminal_tools_menu.addAction("Stage Selection in Terminal", _call_if_present(window, "run_selection_in_terminal"))
    terminal_tools_menu.addAction("Stage Current File Command", _call_if_present(window, "run_current_file_in_terminal"))

    studio_menu = tools_menu.addMenu("Tech Connector Tools")
    _add_if_present(studio_menu, "License & Activation...", window, "show_license_management_dialog")
    studio_menu.addSeparator()
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

    updates_menu = tools_menu.addMenu("App Updates")
    _add_if_present(updates_menu, "Check App Git Status", window, "check_app_update_status")
    _add_if_present(updates_menu, "Update from Latest", window, "update_app_from_latest")
    _add_if_present(updates_menu, "Update from Git Ref...", window, "update_app_from_git_ref")

    community_menu = _add_top_menu(menu_bar, "Community")
    community_tools = community_menu.addMenu("Community Tools")
    community_tools.setToolTip(
        "Discover, install, share, and launch tools created outside the Tech Connector core. "
        "Community Tools can come from GitHub, local folders, or other developers and can be used in your projects and pipelines."
    )
    _add_if_present(community_tools, "Browse / Import from GitHub...", window, "trigger_web_import")
    _add_if_present(community_tools, "Add Integration Package...", window, "show_add_integration_package_dialog")
    community_menu.addSeparator()
    _add_if_present(community_menu, "Custom Integrations & Bridges...", window, "show_customization_panel_ext")

    window_menu = _add_top_menu(menu_bar, "Window")
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

    help_menu = _add_top_menu(menu_bar, "Help")
    _add_if_present(help_menu, "Health Check", window, "health_check")
    _add_if_present(help_menu, "Model Provider Setup", window, "show_model_provider_setup")
    help_menu.addSeparator()
    help_menu.addAction(
        "About The Entire World Tech Connector",
        lambda: _show_about_dialog(window),
    )

    _retain_menu_tree(window, menu_bar)
    _install_menu_bar_timing(menu_bar, window)
    return menu_bar


def install_main_menu(window) -> QMenuBar:
    """Install a menu bar into the current QWidget-based layout."""
    menu_bar = build_main_menu_bar(window)
    window._tc_main_menu_bar = menu_bar
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
