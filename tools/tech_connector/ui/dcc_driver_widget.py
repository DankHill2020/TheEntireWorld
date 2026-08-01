"""Second-screen DCC driver for connected creative applications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class DccAction:
    label: str
    method: str


@dataclass(frozen=True)
class DccHost:
    key: str
    label: str
    launch_method: str
    raw_method: str
    setup_methods: tuple[DccAction, ...]
    actions: tuple[DccAction, ...]
    placeholder: str


HOSTS: tuple[DccHost, ...] = (
    DccHost(
        key="maya",
        label="Maya",
        launch_method="launch_maya",
        raw_method="direct_maya_call_from_text",
        setup_methods=(),
        actions=(
            DccAction("Selection", "direct_maya_selection"),
            DccAction("Current File", "direct_maya_file"),
            DccAction("Scene Objects", "direct_maya_scene_objects"),
            DccAction("Undo", "direct_maya_undo"),
        ),
        placeholder="import maya.cmds as cmds\nprint(cmds.ls(selection=True))",
    ),
    DccHost(
        key="blender",
        label="Blender",
        launch_method="launch_blender",
        raw_method="direct_blender_call_from_text",
        setup_methods=(
            DccAction("Install Bridge", "install_blender_bridge_from_menu"),
            DccAction("Copy Setup", "copy_blender_script_editor_setup"),
        ),
        actions=(
            DccAction("Selection", "direct_blender_selection"),
            DccAction("Current File", "direct_blender_file"),
            DccAction("Scene Objects", "direct_blender_scene_objects"),
            DccAction("Undo", "direct_blender_undo"),
        ),
        placeholder="import bpy\nprint([obj.name for obj in bpy.context.selected_objects])",
    ),
    DccHost(
        key="substance_painter",
        label="Substance Painter",
        launch_method="launch_substance_painter",
        raw_method="direct_substance_painter_call_from_text",
        setup_methods=(
            DccAction("Install Bridge", "install_substance_painter_bridge_from_menu"),
            DccAction("Copy Setup", "copy_substance_painter_script_editor_setup"),
        ),
        actions=(
            DccAction("Project", "direct_substance_painter_project"),
            DccAction("Status", "direct_substance_painter_status"),
            DccAction("Texture Sets", "direct_substance_painter_texture_sets"),
            DccAction("Undo", "direct_substance_painter_undo"),
        ),
        placeholder=(
            "import substance_painter\n"
            "print(substance_painter.project.file_path() if substance_painter.project.is_open() else 'No project open')"
        ),
    ),
    DccHost(
        key="unreal",
        label="Unreal Engine",
        launch_method="launch_unreal",
        raw_method="direct_unreal_call_from_text",
        setup_methods=(),
        actions=(
            DccAction("Project Snapshot", "direct_unreal_project_snapshot"),
            DccAction("Project Scan", "direct_unreal_project_scan"),
            DccAction("Loaded Level", "direct_unreal_level_scan"),
            DccAction("Skeletons", "direct_unreal_get_skeletons"),
            DccAction("Static Meshes", "direct_unreal_get_static_meshes"),
            DccAction("Undo", "direct_unreal_undo"),
        ),
        placeholder='{"function": "unreal.EditorAssetLibrary.list_assets", "args": ["/Game"], "kwargs": {"recursive": false}}',
    ),
    DccHost(
        key="unity",
        label="Unity",
        launch_method="launch_unity",
        raw_method="direct_unity_call_from_text",
        setup_methods=(),
        actions=(
            DccAction("Selection", "direct_unity_selection"),
            DccAction("Current Scene", "direct_unity_scene"),
            DccAction("Scene Objects", "direct_unity_scene_objects"),
            DccAction("Undo", "direct_unity_undo"),
        ),
        placeholder='Debug.Log("Tech Connector command received");',
    ),
    DccHost(
        key="houdini",
        label="Houdini",
        launch_method="launch_houdini",
        raw_method="direct_houdini_call_from_text",
        setup_methods=(),
        actions=(
            DccAction("Selection", "direct_houdini_selection"),
            DccAction("Current File", "direct_houdini_file"),
            DccAction("Scene Nodes", "direct_houdini_scene_objects"),
            DccAction("Context Summary", "direct_houdini_context_summary"),
            DccAction("Undo", "direct_houdini_undo"),
        ),
        placeholder="import hou\nprint([node.path() for node in hou.selectedNodes()])",
    ),
    DccHost(
        key="motionbuilder",
        label="MotionBuilder",
        launch_method="launch_motionbuilder",
        raw_method="direct_motionbuilder_call_from_text",
        setup_methods=(),
        actions=(
            DccAction("Selection", "direct_motionbuilder_selection"),
            DccAction("Current File", "direct_motionbuilder_file"),
            DccAction("Scene Objects", "direct_motionbuilder_scene_objects"),
            DccAction("Takes", "direct_motionbuilder_takes"),
            DccAction("Characters", "direct_motionbuilder_characters"),
            DccAction("Undo", "direct_motionbuilder_undo"),
        ),
        placeholder="from pyfbsdk import FBSystem\nprint(FBSystem().Scene.Components)",
    ),
)


HOST_BY_KEY = {host.key: host for host in HOSTS}


class DccDriverDialog(QDialog):
    """Bridge-powered control surface for external DCC applications."""

    def __init__(self, window, initial_host: str = "", parent=None):
        parent_widget = parent if isinstance(parent, QWidget) else window if isinstance(window, QWidget) else None
        super().__init__(parent_widget)
        self.window = window
        self.current_host = HOST_BY_KEY.get(initial_host) or HOSTS[0]
        self.action_buttons: list[QPushButton] = []
        self.setup_buttons: list[QPushButton] = []
        self._build_ui()
        self._select_host(self.current_host.key)
        self.refresh_status()

    def _build_ui(self) -> None:
        self.setWindowTitle("DCC Driver / Second Screen")
        self.resize(760, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.host_combo = QComboBox(self)
        for host in HOSTS:
            self.host_combo.addItem(host.label, host.key)
        self.host_combo.currentIndexChanged.connect(self._on_host_changed)
        top.addWidget(QLabel("Host", self))
        top.addWidget(self.host_combo, 1)

        self.status_label = QLabel("Status: unknown", self)
        self.status_label.setMinimumWidth(180)
        top.addWidget(self.status_label)

        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.clicked.connect(self.refresh_status)
        top.addWidget(self.refresh_button)
        root.addLayout(top)

        launch_row = QHBoxLayout()
        self.launch_button = QPushButton("Open Host", self)
        self.launch_button.clicked.connect(self.launch_host)
        launch_row.addWidget(self.launch_button)
        self.open_apps_menu_button = QPushButton("Connected Apps Status", self)
        self.open_apps_menu_button.clicked.connect(lambda: self._call_window_method("show_connected_application_status_dialog"))
        launch_row.addWidget(self.open_apps_menu_button)
        launch_row.addStretch(1)
        root.addLayout(launch_row)

        self.setup_group = QGroupBox("Bridge Setup", self)
        self.setup_layout = QHBoxLayout(self.setup_group)
        self.setup_layout.addStretch(1)
        root.addWidget(self.setup_group)

        self.actions_group = QGroupBox("Quick Actions", self)
        self.actions_layout = QGridLayout(self.actions_group)
        root.addWidget(self.actions_group)

        command_group = QGroupBox("Command Pad", self)
        command_layout = QVBoxLayout(command_group)
        self.command_edit = QPlainTextEdit(self)
        self.command_edit.setPlaceholderText("Enter host command or JSON payload.")
        self.command_edit.setMinimumHeight(130)
        command_layout.addWidget(self.command_edit)
        command_row = QHBoxLayout()
        self.run_button = QPushButton("Run Command", self)
        self.run_button.clicked.connect(self.run_command)
        command_row.addWidget(self.run_button)
        self.clear_button = QPushButton("Clear", self)
        self.clear_button.clicked.connect(self.command_edit.clear)
        command_row.addWidget(self.clear_button)
        command_row.addStretch(1)
        command_layout.addLayout(command_row)
        root.addWidget(command_group)

        log_group = QGroupBox("Driver Log", self)
        log_layout = QVBoxLayout(log_group)
        self.log = QTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.log)
        root.addWidget(log_group, 1)

    def _select_host(self, host_key: str) -> None:
        for index in range(self.host_combo.count()):
            if self.host_combo.itemData(index) == host_key:
                self.host_combo.setCurrentIndex(index)
                return
        self.host_combo.setCurrentIndex(0)

    def _on_host_changed(self, *_args) -> None:
        host_key = self.host_combo.currentData()
        self.current_host = HOST_BY_KEY.get(host_key, HOSTS[0])
        self.launch_button.setText(f"Open {self.current_host.label}")
        self.command_edit.setPlaceholderText(self.current_host.placeholder)
        self._rebuild_setup_buttons()
        self._rebuild_action_buttons()
        self.refresh_status()

    def _rebuild_setup_buttons(self) -> None:
        self._clear_layout(self.setup_layout)
        self.setup_buttons.clear()
        if not self.current_host.setup_methods:
            label = QLabel("No installer action is registered for this host.", self.setup_group)
            self.setup_layout.addWidget(label)
            self.setup_layout.addStretch(1)
            return
        for action in self.current_host.setup_methods:
            button = QPushButton(action.label, self.setup_group)
            button.clicked.connect(lambda _checked=False, method=action.method: self._call_window_method(method))
            self.setup_layout.addWidget(button)
            self.setup_buttons.append(button)
        self.setup_layout.addStretch(1)

    def _rebuild_action_buttons(self) -> None:
        self._clear_layout(self.actions_layout)
        self.action_buttons.clear()
        for index, action in enumerate(self.current_host.actions):
            button = QPushButton(action.label, self.actions_group)
            button.clicked.connect(lambda _checked=False, method=action.method: self._call_window_method(method))
            self.actions_layout.addWidget(button, index // 3, index % 3)
            self.action_buttons.append(button)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def refresh_status(self) -> None:
        port = None
        fn = getattr(self.window, "_dcc_bridge_port_for_host", None)
        if callable(fn):
            try:
                port = fn(self.current_host.key)
            except Exception as exc:
                self._append_log(f"Status check failed: {exc}")
        if port:
            self.status_label.setText(f"Connected :{port}")
            self._append_log(f"{self.current_host.label} bridge connected on port {port}.")
        else:
            self.status_label.setText("Not connected")

    def launch_host(self) -> None:
        self._call_window_method(self.current_host.launch_method)
        QTimer.singleShot(2000, self.refresh_status)
        QTimer.singleShot(5000, self.refresh_status)

    def run_command(self) -> None:
        text = self.command_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "No command", "Enter a command for the selected host first.")
            return
        input_widget = getattr(self.window, "input", None)
        previous_text = ""
        if input_widget is not None and hasattr(input_widget, "text") and hasattr(input_widget, "setText"):
            try:
                previous_text = input_widget.text()
                input_widget.setText(text)
            except Exception:
                previous_text = ""
        try:
            self._call_window_method(self.current_host.raw_method)
            self._append_log(f"Sent command to {self.current_host.label}.")
        finally:
            if input_widget is not None and hasattr(input_widget, "setText"):
                try:
                    if input_widget.text() == "":
                        input_widget.setText(previous_text)
                except Exception:
                    pass
        QTimer.singleShot(250, self.refresh_status)

    def _call_window_method(self, method_name: str):
        fn = getattr(self.window, method_name, None)
        if not callable(fn):
            QMessageBox.information(
                self,
                "Action unavailable",
                f"This build does not expose {method_name}.",
            )
            return None
        self._append_log(f"Running {method_name}...")
        try:
            return fn()
        except Exception as exc:
            self._append_log(f"{method_name} failed: {exc}")
            QMessageBox.warning(self, "DCC action failed", str(exc))
            return None

    def _append_log(self, message: str) -> None:
        self.log.append(message)
        append = getattr(self.window, "append", None)
        if callable(append):
            try:
                append(f"[DCC Driver] {message}\n")
            except Exception:
                pass


def open_dcc_driver_dialog(window, initial_host: str = "") -> DccDriverDialog:
    dialog = getattr(window, "_dcc_driver_dialog", None)
    if dialog is None:
        dialog = DccDriverDialog(window, initial_host=initial_host, parent=window)
        window._dcc_driver_dialog = dialog
    elif initial_host:
        dialog._select_host(initial_host)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
