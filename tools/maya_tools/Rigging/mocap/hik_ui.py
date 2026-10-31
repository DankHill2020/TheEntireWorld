import os
import json
import traceback
import re
import importlib
import sys
import time
import copy
import inspect

try:
    import maya.cmds as cmds
    from maya import OpenMayaUI as omui
    MAYA_HOST = True
except ImportError:
    MAYA_HOST = False

def _maya_major_version():
    match = re.search(r"\d{4}", str(cmds.about(version=True))) if MAYA_HOST else None
    return int(match.group(0)) if match else 0


if MAYA_HOST and _maya_major_version() < 2025:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance
else:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance

if MAYA_HOST:
    from maya_tools.Rigging.mocap import setup_hik
    from maya_tools.Rigging import enum_attrs
    from maya_tools.Rigging import create_rig_core
    from maya_tools.Rigging import create_rig_modules
    from maya_tools.Rigging import create_rig
    from maya_tools.Rigging import joint_placer
    from maya_tools.Rigging import joint_placement_regression
    from maya_tools.Rigging import rig_template
    from maya_tools.Rigging import vehicle_rig
    from maya_tools.Rigging import skinning_utils
    from maya_tools.Rigging import unreal_skeletal_export
    from maya_tools.Utilities import joints, dag
else:
    from tech_connector.services.dcc.tc_hik_ui_host import (
        cmds, create_rig, dag, joints, omui, rig_template, setup_hik, skinning_utils,
    )
    joint_placer = None
    joint_placement_regression = None
    vehicle_rig = None
    unreal_skeletal_export = None
from unreal_tools import unreal_subprocess as usp
from utilities import p4_utils
importlib.reload(p4_utils)
from unreal_tools import unreal_project_data as upd
from maya_tools.Rigging.mocap.hik_ui_specialized_tabs import HIKSpecializedTabsMixin

importlib.reload(usp)
importlib.reload(upd)


_RIG_STACK_SIGNATURE = None


def _rig_stack_source_signature():
    """Return a cheap signature that changes when a rig module changes on disk."""
    if not MAYA_HOST:
        return ()
    rows = []
    for module in (
            enum_attrs,
            skinning_utils,
            unreal_skeletal_export,
            joints,
            dag,
            rig_template,
            vehicle_rig,
            joint_placer,
            joint_placement_regression,
            setup_hik,
            create_rig_core,
            create_rig_modules,
            create_rig,
    ):
        path = os.path.abspath(str(getattr(module, "__file__", "") or ""))
        try:
            stat = os.stat(path)
            rows.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            rows.append((path, 0, 0))
    return tuple(rows)


def reload_rig_function_stack(force=False):
    """Reload changed Maya rig modules; skip the expensive no-change path."""
    global _RIG_STACK_SIGNATURE
    if not MAYA_HOST:
        return "non-maya-host"

    current_signature = _rig_stack_source_signature()
    if not force and _RIG_STACK_SIGNATURE == current_signature:
        return getattr(create_rig_core, "RIG_BUILD_REVISION", "unknown")

    importlib.invalidate_caches()

    # Reload leaf dependencies before the modules that import their functions.
    # create_rig must be last: its import binds the refreshed core helpers into
    # create_rig_modules and republishes the complete legacy function surface.
    for module in (
            enum_attrs,
            skinning_utils,
            joints,
            dag,
            rig_template,
            vehicle_rig,
            joint_placer,
            joint_placement_regression,
            unreal_skeletal_export,
            setup_hik,
            create_rig_core,
    ):
        importlib.reload(module)

    # Older bind_runtime implementations copied create_rig's __name__/__spec__
    # into this bridge module. Repair an already-running Maya session by
    # replacing that poisoned cache entry before reloading the public facade.
    global create_rig_modules
    modules_name = "maya_tools.Rigging.create_rig_modules"
    if (
            sys.modules.get(modules_name) is not create_rig_modules
            or getattr(create_rig_modules, "__name__", None) != modules_name
    ):
        sys.modules.pop(modules_name, None)
        create_rig_modules = importlib.import_module(modules_name)
    else:
        importlib.reload(create_rig_modules)

    importlib.reload(create_rig)
    _RIG_STACK_SIGNATURE = _rig_stack_source_signature()
    return getattr(create_rig_core, "RIG_BUILD_REVISION", "unknown")


if MAYA_HOST:
    reload_rig_function_stack()

script_dir = os.path.dirname(__file__).replace('\\', '/')


def get_default_export_path():
    scene_path = cmds.file(q=True, sn=True)
    if scene_path:
        dir_name = os.path.dirname(scene_path)
        base_name = os.path.basename(scene_path).rsplit('.')[0]
        final_name = os.path.join(dir_name, "mocap_rigs", base_name).replace('\\', '/')
        return final_name + ".fbx"
    else:
        return "C:/temp/mocap_rigs/Character1.fbx"


def get_main_window_pointer():
    """
    Get the Maya main window pointer
    :return:
    """
    main_window_ptr = omui.MQtUtil.mainWindow()
    return int(main_window_ptr)


class ParentSelectionDialog(QtWidgets.QDialog):
    def __init__(self, msg, parent=None):
        super(ParentSelectionDialog, self).__init__(parent)
        self.setWindowTitle("Select Parent Control")
        self.setModal(True)
        self.resize(400, 150)

        layout = QtWidgets.QVBoxLayout(self)

        lbl = QtWidgets.QLabel(msg)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        layout.addSpacing(10)

        self.checkbox = QtWidgets.QCheckBox(
            "Use this parent control for all remaining systems with missing parent control")
        self.checkbox.setChecked(False)
        layout.addWidget(self.checkbox)

        layout.addSpacing(15)

        btn_hl = QtWidgets.QHBoxLayout()
        self.ok_btn = QtWidgets.QPushButton("Assign & Build")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_hl.addWidget(self.ok_btn)
        btn_hl.addWidget(self.cancel_btn)
        layout.addLayout(btn_hl)


class ControlRigPopup(QtWidgets.QDialog):
    def __init__(self, skeletal_meshes, joint_map, uproject, parent=None):
        super(ControlRigPopup, self).__init__(parent)
        self.setWindowTitle("Create Control Rig")
        self.skeletal_meshes = skeletal_meshes
        self.joint_map = joint_map
        self.uproject = uproject
        self.log_path = upd.get_latest_unreal_log(uproject)
        self.cmd_path = upd.get_unreal_cmd_exe(uproject)
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Skeletal Meshes:"))
        self.mesh_filter_input = QtWidgets.QLineEdit()
        self.mesh_filter_input.setPlaceholderText("Filter Skeletal Meshes...")
        self.mesh_filter_input.setToolTip("Type here to filter the list of skeletal meshes shown below.")
        layout.addWidget(self.mesh_filter_input)

        self.mesh_input = QtWidgets.QComboBox()
        self.mesh_input.addItems(self.skeletal_meshes)
        self.mesh_input.setToolTip("Select the Skeletal Mesh to generate the Control Rig from.")
        layout.addWidget(self.mesh_input)

        self.mesh_filter_input.textChanged.connect(self.filter_meshes)

        # Control Rig Name
        layout.addWidget(QtWidgets.QLabel("Control Rig Name:"))
        self.cr_name_input = QtWidgets.QLineEdit()
        self.cr_name_input.setPlaceholderText("Enter Control Rig Name")
        self.cr_name_input.setToolTip("Specify the asset name for the new Control Rig (e.g. CR_MyCharacter).")
        layout.addWidget(self.cr_name_input)

        # Create Button
        self.create_button = QtWidgets.QPushButton("Create Control Rig")
        self.create_button.setToolTip("Initiate the Control Rig generation process in Unreal.")
        self.create_button.clicked.connect(self.create_control_rig)
        layout.addWidget(self.create_button)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

    def filter_meshes(self, text):
        self.mesh_input.clear()
        filtered = [s for s in self.skeletal_meshes if text.lower() in s.lower()]
        self.mesh_input.addItems(filtered)

    def create_control_rig(self):
        selected_mesh = self.mesh_input.currentText()
        rig_name = self.cr_name_input.text().strip()
        try:
            usp.run_create_modular_control_rig(selected_mesh, rig_name, self.joint_map, self.uproject, self.log_path,
                                             self.cmd_path)
        except Exception as exc:
            self.status_label.setText("Control Rig creation failed: {}".format(exc))
            self.status_label.setStyleSheet("color: #ff9a9a; font-weight: bold;")
            self.status_label.show()


class UnrealSkeletalExportDialog(QtWidgets.QDialog):
    """Collect explicit Unreal update/create choices before destructive export."""

    CREATE_NEW_MESH = "Create New Skeletal Mesh"

    def __init__(self, rig_name, output_directory, asset_data, maya_meshes=None, selected_meshes=None, parent=None):
        super(UnrealSkeletalExportDialog, self).__init__(parent)
        self.setWindowTitle("Remove Rig and Send Skeletal Mesh to Unreal")
        self.resize(720, 430)
        self.asset_data = dict(asset_data or {})
        self.mesh_rows = list(self.asset_data.get("skeletal_meshes") or [])
        self.skeleton_rows = list(self.asset_data.get("skeletons") or [])
        self.maya_meshes = list(maya_meshes or [])
        selected_meshes = set(selected_meshes or [])

        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            "This removes the generated control rig, restores the checked skinned meshes to bind pose, "
            "exports FBX, and imports it into the connected Unreal Editor."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #f1d37b; font-weight: bold;")
        layout.addWidget(warning)

        form = QtWidgets.QFormLayout()
        self.rig_name = QtWidgets.QLineEdit(str(rig_name or "Character"))
        form.addRow("Rig Name:", self.rig_name)

        output_row = QtWidgets.QHBoxLayout()
        self.output_directory = QtWidgets.QLineEdit(str(output_directory or ""))
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_directory)
        output_row.addWidget(browse)
        form.addRow("FBX Folder:", output_row)

        self.destination = QtWidgets.QLineEdit("/Game/Characters")
        self.destination.setToolTip("Used only when creating a new Skeletal Mesh.")
        form.addRow("Unreal Folder:", self.destination)

        self.mesh_combo = QtWidgets.QComboBox()
        self.mesh_combo.addItem(self.CREATE_NEW_MESH, "")
        for row in self.mesh_rows:
            path = str(row.get("path") or "")
            self.mesh_combo.addItem("Overwrite Existing: " + (path or str(row.get("name"))), path)
        self.mesh_combo.currentIndexChanged.connect(self._mesh_changed)
        self.mesh_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Skeletal Mesh:", self.mesh_combo)

        skeleton_mode = QtWidgets.QWidget()
        skeleton_mode_layout = QtWidgets.QHBoxLayout(skeleton_mode)
        skeleton_mode_layout.setContentsMargins(0, 0, 0, 0)
        self.new_skeleton = QtWidgets.QRadioButton("Create New Skeleton")
        self.existing_skeleton = QtWidgets.QRadioButton("Use Existing Skeleton")
        self.new_skeleton.setChecked(True)
        skeleton_mode_layout.addWidget(self.new_skeleton)
        skeleton_mode_layout.addWidget(self.existing_skeleton)
        skeleton_mode_layout.addStretch()
        form.addRow("Skeleton Policy:", skeleton_mode)

        self.skeleton_combo = QtWidgets.QComboBox()
        for row in self.skeleton_rows:
            self.skeleton_combo.addItem(str(row.get("path") or row.get("name")), str(row.get("path") or ""))
        self.skeleton_combo.setEnabled(False)
        self.existing_skeleton.toggled.connect(self.skeleton_combo.setEnabled)
        self.existing_skeleton.toggled.connect(self._update_preview)
        self.skeleton_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow("Existing Skeleton:", self.skeleton_combo)

        self.create_physics = QtWidgets.QCheckBox("Create/retain Physics Asset")
        self.create_physics.setChecked(True)
        form.addRow("Physics:", self.create_physics)

        mesh_set = QtWidgets.QWidget()
        mesh_set_layout = QtWidgets.QVBoxLayout(mesh_set)
        mesh_set_layout.setContentsMargins(0, 0, 0, 0)
        self.export_meshes = QtWidgets.QListWidget()
        self.export_meshes.setMinimumHeight(110)
        check_all = not selected_meshes
        for mesh in self.maya_meshes:
            item = QtWidgets.QListWidgetItem(mesh)
            item.setData(QtCore.Qt.UserRole, mesh)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if check_all or mesh in selected_meshes else QtCore.Qt.Unchecked)
            self.export_meshes.addItem(item)
        mesh_buttons = QtWidgets.QHBoxLayout()
        select_all_meshes = QtWidgets.QPushButton("Select All")
        clear_meshes = QtWidgets.QPushButton("Clear")
        select_all_meshes.clicked.connect(lambda: self._set_all_export_meshes(True))
        clear_meshes.clicked.connect(lambda: self._set_all_export_meshes(False))
        mesh_buttons.addWidget(select_all_meshes)
        mesh_buttons.addWidget(clear_meshes)
        mesh_buttons.addStretch()
        mesh_set_layout.addWidget(self.export_meshes)
        mesh_set_layout.addLayout(mesh_buttons)
        form.addRow("Maya Meshes to Export:", mesh_set)
        layout.addLayout(form)

        self.naming_preview = QtWidgets.QLabel()
        self.naming_preview.setWordWrap(True)
        layout.addWidget(self.naming_preview)
        self.rig_name.textChanged.connect(self._update_preview)
        self.destination.textChanged.connect(self._update_preview)
        self._update_preview()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Confirm Export and Import")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_output(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select FBX Export Folder", self.output_directory.text())
        if directory:
            self.output_directory.setText(directory.replace("\\", "/"))

    def _set_all_export_meshes(self, checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for index in range(self.export_meshes.count()):
            self.export_meshes.item(index).setCheckState(state)

    def _checked_export_meshes(self):
        return [
            str(self.export_meshes.item(index).data(QtCore.Qt.UserRole) or "")
            for index in range(self.export_meshes.count())
            if self.export_meshes.item(index).checkState() == QtCore.Qt.Checked
        ]

    def _mesh_changed(self, *_args):
        path = str(self.mesh_combo.currentData() or "")
        updating = bool(path)
        self.destination.setEnabled(not updating)
        self.new_skeleton.setEnabled(not updating)
        if updating:
            self.existing_skeleton.setChecked(True)
            row = next((item for item in self.mesh_rows if str(item.get("path") or "") == path), {})
            skeleton_path = str(row.get("skeleton") or "")
            index = self.skeleton_combo.findData(skeleton_path)
            if index >= 0:
                self.skeleton_combo.setCurrentIndex(index)
            self.skeleton_combo.setEnabled(False)
            self.mesh_combo.setToolTip("The selected Unreal Skeletal Mesh will be overwritten in place.")
        else:
            self.skeleton_combo.setEnabled(self.existing_skeleton.isChecked())
            self.mesh_combo.setToolTip("Create a new Unreal Skeletal Mesh using SKM_<RigName>.")

    def _update_preview(self, *_args):
        try:
            clean = unreal_skeletal_export.sanitize_rig_name(self.rig_name.text())
            destination = self.destination.text().strip().rstrip("/") or "/Game/Characters"
            character_folder = self._character_folder(destination, clean)
            mesh = str(self.mesh_combo.currentData() or "") or f"{character_folder}/SKM_{clean}"
            skeleton = (
                str(self.skeleton_combo.currentData() or "<Select Existing Skeleton>")
                if self.existing_skeleton.isChecked()
                else f"{character_folder}/SK_{clean}"
            )
            action = "OVERWRITE EXISTING" if self.mesh_combo.currentData() else "CREATE NEW"
            text = "{}\nMesh: {}\nSkeleton: {}\nPhysics: {}/PHYS_{}".format(
                action, mesh, skeleton, character_folder, clean
            )
        except ValueError:
            text = "Enter a valid rig name."
        self.naming_preview.setText(text)

    @staticmethod
    def _character_folder(parent, clean_name):
        parent = "/" + str(parent or "/Game/Characters").strip("/")
        return parent if parent.rsplit("/", 1)[-1].lower() == clean_name.lower() else parent + "/" + clean_name

    def _validate_and_accept(self):
        try:
            unreal_skeletal_export.sanitize_rig_name(self.rig_name.text())
            if not self.output_directory.text().strip():
                raise ValueError("Choose an FBX output folder.")
            if self.existing_skeleton.isChecked() and not self.skeleton_combo.currentData():
                raise ValueError("Choose an existing Skeleton or select Create New Skeleton.")
            if not self._checked_export_meshes():
                raise ValueError("Choose at least one Maya mesh to export.")
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Incomplete Unreal Export Settings", str(exc))
            return
        self.accept()

    def values(self):
        return {
            "rig_name": self.rig_name.text().strip(),
            "output_directory": self.output_directory.text().strip(),
            "destination_path": self.destination.text().strip(),
            "existing_skeletal_mesh_path": str(self.mesh_combo.currentData() or ""),
            "skeleton_mode": "use_existing" if self.existing_skeleton.isChecked() else "create_new",
            "existing_skeleton_path": str(self.skeleton_combo.currentData() or ""),
            "create_physics_asset": self.create_physics.isChecked(),
            "meshes": self._checked_export_meshes(),
        }


class HIKDefinitionUI(HIKSpecializedTabsMixin, QtWidgets.QDialog):
    def __init__(self, parent=None, *, host_mode="maya"):
        self.host_mode = str(host_mode or ("maya" if MAYA_HOST else "tech_connector"))
        if parent is None and MAYA_HOST:
            parent = wrapInstance(get_main_window_pointer(), QtWidgets.QMainWindow)
        super(HIKDefinitionUI, self).__init__(parent)

        self.setWindowTitle("HIK & Rig Builder")
        self.setMinimumSize(900, 600)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.char_name = QtWidgets.QLineEdit("Character1")
        self.char_name.setToolTip("The name of the HumanIK character definition in Maya.")
        self.export_path = QtWidgets.QLineEdit(get_default_export_path())
        self.export_path.setToolTip("The directory path where character mappings and definitions will be exported.")
        namespace = os.path.basename(self.export_path.text()).rsplit('.')[0] + "_retarget"
        self.namespace = QtWidgets.QLineEdit(namespace)
        self.namespace.setToolTip(
            "The namespace prefix applied to character joints and animation nodes during retargeting.")

        self.fields = {key: "" for key in setup_hik.DEFAULT_JOINT_MAP.keys()}
        self.fields["HipSwing"] = ""
        self.face_fields = {key: "" for key in setup_hik.DEFAULT_FACE_JOINT_MAP.keys()}
        self.buttons = {}
        self.module_create_buttons = {}
        self.module_remove_buttons = {}
        self.default_map = copy.deepcopy(setup_hik.DEFAULT_JOINT_MAP)
        self.default_map["HipSwing"] = {"index": -1, "joint": ""}
        self.default_face_map = copy.deepcopy(setup_hik.DEFAULT_FACE_JOINT_MAP)
        self.populate_default_face_map_from_scene()
        self.current_slot = None
        self._module_detail_widgets = {}  # {module_id: {"container", "status_lbl", "parent_btn", "spaces_widget"}}
        self._additional_systems_layout = None
        self.face_lists = {}
        self._slot_edit_widgets = {}
        self._session_parent_override = None
        self._use_override_for_all = False

        # During full-rig builds, collect missing saved-joint references and
        # report them once at the end instead of interrupting every module.
        self._defer_module_discrepancy_warnings = False
        self._pending_module_discrepancies = set()

        # ---------- Tabs ----------
        self.tabs = QtWidgets.QTabWidget()
        self.layout().addWidget(self.tabs)

        self._build_hik_tab()
        self._build_rigging_tab()
        self._build_skinning_tab()
        self._build_mesh_tab()
        if self.host_mode == "maya":
            self._build_vehicle_tab()

        # Maya can defer scriptJob updates until a manipulator releases. This
        # heartbeat keeps registered vehicle rigs evaluating while the mouse is
        # down as well as during normal animation playback.
        self._vehicle_live_timer = QtCore.QTimer(self)
        self._vehicle_live_timer.setInterval(16)
        self._vehicle_live_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._vehicle_live_timer.timeout.connect(self._vehicle_live_tick)
        if MAYA_HOST and vehicle_rig is not None and getattr(
            vehicle_rig, "_GROUND_CALLBACK_IDS", None
        ):
            self._vehicle_live_timer.start()

        # One persistent result surface replaces one-button Maya/Qt dialogs.
        # Updating a child label does not create a native window or force Maya
        # to flush the post-operation DAG again when the user dismisses it.
        self.operation_status_label = QtWidgets.QLabel("")
        self.operation_status_label.setWordWrap(True)
        self.operation_status_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self.operation_status_label.hide()
        self.layout().addWidget(self.operation_status_label)

        # Refresh detail widgets when the Rigging tab becomes active
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Auto-populate module states from scene metadata without showing
        # stale saved-joint warnings when the UI first opens.
        self._load_module_metadata_from_scene(
            report_missing=False, refresh_details=False
        )
        # Let Maya paint the window before querying module DAG/connection state.
        QtCore.QTimer.singleShot(100, self._refresh_all_module_details)

    def _notify_operation(self, title, message, severity="info"):
        """Report an operation result without creating a top-level window."""
        severity = str(severity or "info").lower()
        styles = {
            "info": ("#20344a", "#a9d5ff", "#477da8", "ℹ"),
            "success": ("#203b29", "#9ee6ad", "#3b825c", "✓"),
            "warning": ("#493d1d", "#f1d37b", "#9d7d2d", "⚠"),
            "error": ("#4a2424", "#ffaaaa", "#a84c4c", "✕"),
        }
        background, foreground, border, icon = styles.get(
            severity, styles["info"]
        )
        full_message = str(message or "")
        compact = " ".join(full_message.split())
        if len(compact) > 320:
            compact = compact[:317].rstrip() + "..."
        label = self.operation_status_label
        label.setText("{} {}: {}".format(icon, title, compact))
        label.setToolTip(full_message)
        label.setStyleSheet(
            "background-color: {}; color: {}; border: 1px solid {}; "
            "border-radius: 3px; padding: 5px; font-weight: bold;".format(
                background, foreground, border
            )
        )
        label.show()
        print("[HIK UI][{}] {}: {}".format(severity, title, full_message))

    def _vehicle_live_tick(self):
        if vehicle_rig is None:
            return
        try:
            vehicle_rig.update_registered_live_rigs(refresh_viewport=True)
        except Exception:
            # Scene changes can invalidate a DAG path between timer ticks. The
            # callbacks are reinstalled when a rig is built or Live is enabled.
            pass

    def _build_hik_tab(self):
        hik_tab = QtWidgets.QWidget()
        hik_layout = QtWidgets.QVBoxLayout(hik_tab)

        # ----- Top Form -----
        top_form = QtWidgets.QFormLayout()
        top_form.addRow("Character Name", self.char_name)
        top_form.addRow("Export Path", self.export_path)
        top_form.addRow("Namespace", self.namespace)
        hik_layout.addLayout(top_form)

        # ----- Grid -----
        layout_widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(layout_widget)
        hik_layout.addWidget(layout_widget)

        # ----- Single Selector -----
        self.single_selector_widget = QtWidgets.QWidget()
        self.single_selector_layout = QtWidgets.QHBoxLayout(self.single_selector_widget)
        self.selector_field = QtWidgets.QLineEdit()
        self.selector_field.setToolTip("Displays the currently selected joint for the active HIK slot mapping.")
        self.selector_button = QtWidgets.QPushButton("Pick Selected")
        self.selector_button.setToolTip("Map the selected joint in the viewport/outliner to the active HIK slot.")
        self.selector_button.clicked.connect(self.pick_selected_joint)
        self.single_selector_layout.addWidget(self.selector_field)
        self.single_selector_layout.addWidget(self.selector_button)
        hik_layout.addWidget(self.single_selector_widget)
        self.single_selector_widget.hide()

        positions = {
            "Head": (0, 5),
            "Neck1": (1, 5),
            "Neck": (2, 5),
            "Spine3": (3, 5),
            "Spine2": (4, 5),
            "Spine1": (5, 5),
            "Spine": (6, 5),
            "Hips": (7, 5),
            "Reference": (13, 5),

            "LeftShoulder": (1, 4),
            "LeftArm": (1, 3),
            "LeftForeArm": (1, 2),
            "LeftHand": (1, 1),

            "LeftArmRoll": (2, 3),
            "LeafLeftArmRoll1": (3, 3),
            "LeafLeftArmRoll2": (4, 3),
            "LeafLeftArmRoll3": (5, 3),
            "LeftForeArmRoll": (2, 2),
            "LeafLeftForearmRoll1": (3, 2),
            "LeafLeftForearmRoll2": (4, 2),
            "LeafLeftForearmRoll3": (5, 2),

            "LeftInHandIndex": (14, 1),
            "LeftInHandMiddle": (14, 2),
            "LeftInHandRing": (14, 3),
            "LeftInHandPinky": (14, 4),

            "LeftHandThumb1": (15, 0),
            "LeftHandThumb2": (16, 0),
            "LeftHandThumb3": (17, 0),
            "LeftHandThumb4": (18, 0),

            "LeftHandIndex1": (15, 1),
            "LeftHandIndex2": (16, 1),
            "LeftHandIndex3": (17, 1),
            "LeftHandIndex4": (18, 1),

            "LeftHandMiddle1": (15, 2),
            "LeftHandMiddle2": (16, 2),
            "LeftHandMiddle3": (17, 2),
            "LeftHandMiddle4": (18, 2),

            "LeftHandRing1": (15, 3),
            "LeftHandRing2": (16, 3),
            "LeftHandRing3": (17, 3),
            "LeftHandRing4": (18, 3),

            "LeftHandPinky1": (15, 4),
            "LeftHandPinky2": (16, 4),
            "LeftHandPinky3": (17, 4),
            "LeftHandPinky4": (18, 4),

            "LeftUpLeg": (7, 4),
            "LeftLeg": (8, 4),
            "LeftFoot": (9, 4),
            "LeftToeBase": (10, 4),

            "LeftUpLegRoll": (7, 3),
            "LeafLeftUpLegRoll1": (7, 2),
            "LeafLeftUpLegRoll2": (7, 1),
            "LeafLeftUpLegRoll3": (7, 0),
            "LeftLegRoll": (8, 3),
            "LeafLeftLegRoll1": (8, 2),
            "LeafLeftLegRoll2": (8, 1),

        }

        right_side_slots = [
            ("RightShoulder", 1, 6),
            ("RightArm", 1, 7),
            ("RightForeArm", 1, 8),
            ("RightHand", 1, 9),

            ("RightArmRoll", 2, 7),
            ("LeafRightArmRoll1", 3, 7),
            ("LeafRightArmRoll2", 4, 7),
            ("LeafRightArmRoll3", 5, 7),
            ("RightForeArmRoll", 2, 8),
            ("LeafRightForearmRoll1", 3, 8),
            ("LeafRightForearmRoll2", 4, 8),
            ("LeafRightForearmRoll3", 5, 8),

            ("RightInHandIndex", 14, 9),
            ("RightInHandMiddle", 14, 8),
            ("RightInHandRing", 14, 7),
            ("RightInHandPinky", 14, 6),

            ("RightHandThumb1", 15, 10),
            ("RightHandThumb2", 16, 10),
            ("RightHandThumb3", 17, 10),
            ("RightHandThumb4", 18, 10),

            ("RightHandIndex1", 15, 9),
            ("RightHandIndex2", 16, 9),
            ("RightHandIndex3", 17, 9),
            ("RightHandIndex4", 18, 9),

            ("RightHandMiddle1", 15, 8),
            ("RightHandMiddle2", 16, 8),
            ("RightHandMiddle3", 17, 8),
            ("RightHandMiddle4", 18, 8),

            ("RightHandRing1", 15, 7),
            ("RightHandRing2", 16, 7),
            ("RightHandRing3", 17, 7),
            ("RightHandRing4", 18, 7),

            ("RightHandPinky1", 15, 6),
            ("RightHandPinky2", 16, 6),
            ("RightHandPinky3", 17, 6),
            ("RightHandPinky4", 18, 6),

            ("RightUpLeg", 7, 6),
            ("RightLeg", 8, 6),
            ("RightFoot", 9, 6),
            ("RightToeBase", 10, 6),

            ("RightUpLegRoll", 7, 7),
            ("LeafRightUpLegRoll1", 7, 8),
            ("LeafRightUpLegRoll2", 7, 9),
            ("LeafRightUpLegRoll3", 7, 10),
            ("RightLegRoll", 8, 7),
            ("LeafRightLegRoll1", 8, 8),
            ("LeafRightLegRoll2", 8, 9),
        ]

        for slot, row, col in right_side_slots:
            positions[slot] = (row, col)

        for slot, pos in positions.items():
            btn = QtWidgets.QPushButton(slot)
            btn.clicked.connect(self.make_selector_callback(slot))
            grid.addWidget(btn, *pos)
            self.buttons[slot] = btn
            self.update_button_color(slot)

        btn_layout = QtWidgets.QHBoxLayout()

        load_btn = QtWidgets.QPushButton("Load Definition")
        load_btn.setToolTip("Load a previously saved HumanIK character definition JSON file from disk.")
        load_btn.clicked.connect(self.load_definition)

        save_btn = QtWidgets.QPushButton("Save Definition")
        save_btn.setToolTip("Save the current HumanIK character definition mapping to a JSON file on disk.")
        save_btn.clicked.connect(self.save_definition)

        detect_btn = QtWidgets.QPushButton("Auto Detect")
        detect_btn.setToolTip(
            "Attempt to automatically discover and map joints in the scene based on naming conventions.")
        detect_btn.clicked.connect(self.auto_detect)

        self.unreal_checkbox = QtWidgets.QCheckBox("Create Unreal Rig")
        self.unreal_checkbox.setToolTip(
            "When checked, automatically generates the Unreal modular control rig for the built skeleton.")

        create_btn = QtWidgets.QPushButton("Create HIK Character")
        create_btn.setToolTip("Generate the HumanIK character definition in Maya using the current mappings.")
        create_btn.clicked.connect(self.create_hik_character)

        btn_layout.addWidget(load_btn)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(detect_btn)
        btn_layout.addWidget(self.unreal_checkbox)
        btn_layout.addWidget(create_btn)

        hik_layout.addLayout(btn_layout)

        self.current_slot = None
        self.tabs.addTab(hik_tab, "Human IK")

    def _build_rigging_tab(self):
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)

        rig_container = QtWidgets.QWidget()
        self.rig_layout = QtWidgets.QVBoxLayout(rig_container)
        rig_container.setLayout(self.rig_layout)

        scroll_area.setWidget(rig_container)

        # ------------------------------------------------------------
        # Create Control Section
        # ------------------------------------------------------------
        ctrl_group = QtWidgets.QGroupBox("Create Control")
        ctrl_layout = QtWidgets.QVBoxLayout(ctrl_group)

        self.ctrl_module_name_field = QtWidgets.QLineEdit()
        self.ctrl_module_name_field.setPlaceholderText("Auto: Controls - first selected joint")
        self.ctrl_module_name_field.setToolTip(
            "Persistent module name used to remove and rebuild these controls with the full rig."
        )
        ctrl_name_row = QtWidgets.QHBoxLayout()
        ctrl_name_row.addWidget(QtWidgets.QLabel("Module Name:"))
        ctrl_name_row.addWidget(self.ctrl_module_name_field)
        ctrl_layout.addLayout(ctrl_name_row)

        self.ctrl_parent_field = QtWidgets.QLineEdit()
        self.ctrl_parent_field.setToolTip("Optional: Parent node/control for the new control.")
        parent_btn = QtWidgets.QPushButton("Select Parent")
        parent_btn.setToolTip("Set the selected viewport object as the control's parent.")
        parent_btn.clicked.connect(lambda: self._pick_parent(self.ctrl_parent_field))

        parent_row = QtWidgets.QHBoxLayout()
        parent_row.addWidget(QtWidgets.QLabel("Parent:"))
        parent_row.addWidget(self.ctrl_parent_field)
        parent_row.addWidget(parent_btn)

        shape_row = QtWidgets.QHBoxLayout()
        shape_label = QtWidgets.QLabel("Control Shape:")

        self.ctrl_shape_combo = QtWidgets.QComboBox()
        self.ctrl_shape_combo.addItems([
            "Cube",
            "Circle",
            "Diamond",
            "Double Arrow",
            "Sphere",
            "Prism",
        ])
        self.ctrl_shape_combo.setToolTip("Choose the 3D shape configuration for the control curve.")

        shape_row.addWidget(shape_label)
        shape_row.addWidget(self.ctrl_shape_combo)

        create_ctrl_btn = QtWidgets.QPushButton("Create Control")
        create_ctrl_btn.setToolTip("Create a control curve on the selected joint hierarchy.")
        create_ctrl_btn.clicked.connect(self.create_single_control)

        ctrl_layout.addLayout(parent_row)
        ctrl_layout.addLayout(shape_row)
        ctrl_layout.addWidget(create_ctrl_btn)

        self.rig_layout.addWidget(ctrl_group)

        # ------------------------------------------------------------
        # Additional Limb Modules
        # ------------------------------------------------------------
        limb_group = QtWidgets.QGroupBox("Additional Arm / Leg Module")
        limb_layout = QtWidgets.QVBoxLayout(limb_group)

        self.extra_limb_name_field = QtWidgets.QLineEdit()
        self.extra_limb_name_field.setPlaceholderText("Required unique module name")
        limb_name_row = QtWidgets.QHBoxLayout()
        limb_name_row.addWidget(QtWidgets.QLabel("Module Name:"))
        limb_name_row.addWidget(self.extra_limb_name_field)
        limb_layout.addLayout(limb_name_row)

        self.extra_limb_parent_field = QtWidgets.QLineEdit()
        self.extra_limb_parent_field.setPlaceholderText("Parent control")
        extra_limb_parent_btn = QtWidgets.QPushButton("Select Parent")
        extra_limb_parent_btn.clicked.connect(
            lambda: self._pick_parent(self.extra_limb_parent_field)
        )
        limb_parent_row = QtWidgets.QHBoxLayout()
        limb_parent_row.addWidget(QtWidgets.QLabel("Parent:"))
        limb_parent_row.addWidget(self.extra_limb_parent_field)
        limb_parent_row.addWidget(extra_limb_parent_btn)
        limb_layout.addLayout(limb_parent_row)

        limb_help = QtWidgets.QLabel(
            "Select an ordered, contiguous joint chain: 3 joints for an arm; "
            "4–5 joints for a leg."
        )
        limb_help.setWordWrap(True)
        limb_layout.addWidget(limb_help)

        limb_buttons = QtWidgets.QHBoxLayout()
        add_arm_btn = QtWidgets.QPushButton("Add Arm Module")
        add_arm_btn.clicked.connect(lambda: self.create_additional_limb_module("arm"))
        add_leg_btn = QtWidgets.QPushButton("Add Leg Module")
        add_leg_btn.clicked.connect(lambda: self.create_additional_limb_module("leg"))
        limb_buttons.addWidget(add_arm_btn)
        limb_buttons.addWidget(add_leg_btn)
        limb_layout.addLayout(limb_buttons)
        self.rig_layout.addWidget(limb_group)

        # ------------------------------------------------------------
        # Joints Along Curve Section
        # ------------------------------------------------------------
        curve_joint_group = QtWidgets.QGroupBox("Create Joints Along Curve")
        curve_joint_layout = QtWidgets.QVBoxLayout(curve_joint_group)

        curve_joint_row = QtWidgets.QHBoxLayout()
        curve_joint_row.addWidget(QtWidgets.QLabel("Joint Count:"))
        self.curve_joint_count_spin = QtWidgets.QSpinBox()
        self.curve_joint_count_spin.setRange(1, 500)
        self.curve_joint_count_spin.setValue(5)
        self.curve_joint_count_spin.setToolTip("Number of equally spaced joints to create on the selected curve.")
        curve_joint_row.addWidget(self.curve_joint_count_spin)

        self.curve_joint_keep_attached = QtWidgets.QCheckBox("Keep Attached to Curve")
        self.curve_joint_keep_attached.setChecked(True)
        self.curve_joint_keep_attached.setToolTip(
            "Keep live motion-path attachments. Turn this off to bake the joint layout and remove helpers."
        )
        curve_joint_row.addWidget(self.curve_joint_keep_attached)
        curve_joint_row.addStretch()
        curve_joint_layout.addLayout(curve_joint_row)

        create_curve_joints_btn = QtWidgets.QPushButton("Create Joints From Selected Curve")
        create_curve_joints_btn.setToolTip(
            "Select one curve, then create evenly spaced joints along its full arc length."
        )
        create_curve_joints_btn.clicked.connect(self.create_joints_from_selected_curve)
        curve_joint_layout.addWidget(create_curve_joints_btn)
        self.rig_layout.addWidget(curve_joint_group)

        # ------------------------------------------------------------
        # Surface Rig Section
        # ------------------------------------------------------------
        surf_group = QtWidgets.QGroupBox("Create Surface Rig With Drivers")
        surf_layout = QtWidgets.QVBoxLayout(surf_group)

        self.surface_parent_field = QtWidgets.QLineEdit()
        self.surface_parent_field.setToolTip("Specify the parent node for the generated surface rig controls.")
        surf_parent_btn = QtWidgets.QPushButton("Select Parent")
        surf_parent_btn.setToolTip("Pick selected viewport node as the surface rig parent.")
        surf_parent_btn.clicked.connect(lambda: self._pick_parent(self.surface_parent_field))

        parent_row = QtWidgets.QHBoxLayout()
        parent_row.addWidget(QtWidgets.QLabel("Parent:"))
        parent_row.addWidget(self.surface_parent_field)
        parent_row.addWidget(surf_parent_btn)
        surf_layout.addLayout(parent_row)

        self.surf_name_field = QtWidgets.QLineEdit("eyelid")
        self.surf_name_field.setToolTip("Base suffix name for naming the generated surface meshes/nodes.")
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Loft Name:"))
        name_row.addWidget(self.surf_name_field)
        surf_layout.addLayout(name_row)

        self.surf_module_name_field = QtWidgets.QLineEdit()
        self.surf_module_name_field.setPlaceholderText("Auto: Surface Rig - loft name")
        self.surf_module_name_field.setToolTip(
            "Persistent module name used to remove and rebuild this surface rig."
        )
        surf_module_row = QtWidgets.QHBoxLayout()
        surf_module_row.addWidget(QtWidgets.QLabel("Module Name:"))
        surf_module_row.addWidget(self.surf_module_name_field)
        surf_layout.addLayout(surf_module_row)

        self.surf_region_combo = QtWidgets.QComboBox()
        self.surf_region_combo.addItems(["eyelid", "center_eyelid", "mouth", "brow", "other"])
        self.surf_region_combo.setToolTip("Choose the facial anatomical region this surface rig is built for.")

        self.surf_side_combo = QtWidgets.QComboBox()
        self.surf_side_combo.addItems(["r", "l", "c"])
        self.surf_side_combo.setToolTip(
            "Select l/r for a sided surface or c for a centered eyelid surface."
        )

        region_side_row = QtWidgets.QHBoxLayout()
        region_side_row.addWidget(QtWidgets.QLabel("Region:"))
        region_side_row.addWidget(self.surf_region_combo)
        region_side_row.addWidget(QtWidgets.QLabel("Side:"))
        region_side_row.addWidget(self.surf_side_combo)
        surf_layout.addLayout(region_side_row)

        self.surf_offset_spin = QtWidgets.QDoubleSpinBox()
        self.surf_offset_spin.setValue(0.5)
        self.surf_offset_spin.setSingleStep(0.1)
        self.surf_offset_spin.setToolTip("Adjust the scaling factor offset distance for control CV offsets.")

        self.surf_indices_field = QtWidgets.QLineEdit("0, 9, 6, 3, 12, 15, 18, 20")
        self.surf_indices_field.setPlaceholderText("Comma-separated indices e.g. 0, 9, 6")
        self.surf_indices_field.setToolTip("Specific follicle index placement indices along the loft spline path.")

        auto_detect_indices_btn = QtWidgets.QPushButton("Auto Detect")
        auto_detect_indices_btn.setToolTip(
            "Automatically populate matching indices based on the selected region profile.")
        auto_detect_indices_btn.clicked.connect(self.auto_detect_indices)

        offset_indices_row = QtWidgets.QHBoxLayout()
        offset_indices_row.addWidget(QtWidgets.QLabel("Offset:"))
        offset_indices_row.addWidget(self.surf_offset_spin)
        offset_indices_row.addWidget(QtWidgets.QLabel("Driver Indices:"))
        offset_indices_row.addWidget(self.surf_indices_field)
        offset_indices_row.addWidget(auto_detect_indices_btn)
        surf_layout.addLayout(offset_indices_row)

        self.surf_region_combo.currentTextChanged.connect(lambda text: self.auto_detect_indices())

        create_surf_btn = QtWidgets.QPushButton("Create Surface Rig With Drivers")
        create_surf_btn.setToolTip(
            "Generate a lofted surface and follicle-driven secondary control setup for facial regions.")
        create_surf_btn.clicked.connect(self.create_surface_rig_with_drivers)

        surf_layout.addWidget(create_surf_btn)
        self.rig_layout.addWidget(surf_group)

        # ------------------------------------------------------------
        # Space Switch Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)

        space_group = QtWidgets.QGroupBox("Space Switch")
        space_layout = QtWidgets.QVBoxLayout(space_group)

        self.space_switch_orient_rb = QtWidgets.QRadioButton("Orient")
        self.space_switch_orient_rb.setToolTip(
            "Use an orientConstraint for space switching (changes rotation space only).")
        self.space_switch_parent_rb = QtWidgets.QRadioButton("Parent")
        self.space_switch_parent_rb.setToolTip(
            "Use a parentConstraint for space switching (changes translation and rotation spaces).")
        self.space_switch_orient_rb.setChecked(True)

        rb_row = QtWidgets.QHBoxLayout()
        rb_row.addWidget(self.space_switch_orient_rb)
        rb_row.addWidget(self.space_switch_parent_rb)
        rb_row.addStretch()

        create_space_switch_btn = QtWidgets.QPushButton("Create Space Switch")
        create_space_switch_btn.setToolTip("Build a custom space switch connection for a control group target.")
        create_space_switch_btn.clicked.connect(self.create_space_switch)

        space_layout.addLayout(rb_row)
        space_layout.addWidget(create_space_switch_btn)

        self.rig_layout.addWidget(space_group)

        # ------------------------------------------------------------
        # Skinning Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)

        self.skin_group = QtWidgets.QGroupBox("Skinning Tools")
        skin_layout = QtWidgets.QVBoxLayout(self.skin_group)

        export_skin_btn = QtWidgets.QPushButton("Export Skin Weights")
        export_skin_btn.setToolTip("Export the skin weights of all selected skinned meshes to JSON files.")
        import_skin_btn = QtWidgets.QPushButton("Import Skin Weights")
        import_skin_btn.setToolTip(
            "Import skin weights to matching meshes without moving reverse-foot helpers."
        )
        transfer_skin_btn = QtWidgets.QPushButton("Transfer Skin Weights")
        transfer_skin_btn.setToolTip(
            "Transfer skin weights from selected source mesh(es) to the last selected target mesh. The target must not already have a skinCluster.")

        export_skin_btn.clicked.connect(self.export_skin_weights)
        import_skin_btn.clicked.connect(self.import_skin_weights)
        transfer_skin_btn.clicked.connect(self.transfer_skin_weights_from_selection)

        spatial_settings = QtWidgets.QGridLayout()
        self.spatial_smooth_radius = QtWidgets.QDoubleSpinBox()
        self.spatial_smooth_radius.setDecimals(3)
        self.spatial_smooth_radius.setRange(0.001, 1000000.0)
        self.spatial_smooth_radius.setValue(1.0)
        self.spatial_smooth_radius.setToolTip(
            "World-space radius for the optional paint brush. Automatic whole-mesh smoothing chooses its own radius."
        )
        self.spatial_smooth_iterations = QtWidgets.QSpinBox()
        self.spatial_smooth_iterations.setRange(1, 50)
        self.spatial_smooth_iterations.setValue(4)
        self.spatial_smooth_strength = QtWidgets.QDoubleSpinBox()
        self.spatial_smooth_strength.setRange(0.01, 1.0)
        self.spatial_smooth_strength.setSingleStep(0.05)
        self.spatial_smooth_strength.setValue(0.45)
        self.spatial_smooth_max_influences = QtWidgets.QSpinBox()
        self.spatial_smooth_max_influences.setRange(1, 32)
        self.spatial_smooth_max_influences.setValue(8)
        self.spatial_smooth_normal_angle = QtWidgets.QDoubleSpinBox()
        self.spatial_smooth_normal_angle.setRange(0.0, 180.0)
        self.spatial_smooth_normal_angle.setValue(75.0)
        self.spatial_smooth_normal_angle.setSuffix("°")
        self.spatial_smooth_normal_angle.setToolTip(
            "Maximum normal difference for sharing weights; lower values prevent bleeding across folded surfaces."
        )
        self.spatial_smooth_max_neighbors = QtWidgets.QSpinBox()
        self.spatial_smooth_max_neighbors.setRange(2, 256)
        self.spatial_smooth_max_neighbors.setValue(64)
        self.spatial_smooth_max_neighbors.setToolTip(
            "Maximum nearby surface samples per vertex. This keeps very dense meshes responsive."
        )
        self.spatial_smooth_cross_region = QtWidgets.QDoubleSpinBox()
        self.spatial_smooth_cross_region.setRange(0.0, 0.49)
        self.spatial_smooth_cross_region.setSingleStep(0.05)
        self.spatial_smooth_cross_region.setValue(0.10)
        self.spatial_smooth_cross_region.setToolTip(
            "Minimum share reserved for nearby different weight regions. Increase for a stronger visible blend."
        )
        spatial_settings.addWidget(QtWidgets.QLabel("Brush Radius:"), 0, 0)
        spatial_settings.addWidget(self.spatial_smooth_radius, 0, 1)
        spatial_settings.addWidget(QtWidgets.QLabel("Iterations:"), 0, 2)
        spatial_settings.addWidget(self.spatial_smooth_iterations, 0, 3)
        spatial_settings.addWidget(QtWidgets.QLabel("Strength:"), 1, 0)
        spatial_settings.addWidget(self.spatial_smooth_strength, 1, 1)
        spatial_settings.addWidget(QtWidgets.QLabel("Max Influences:"), 1, 2)
        spatial_settings.addWidget(self.spatial_smooth_max_influences, 1, 3)
        spatial_settings.addWidget(QtWidgets.QLabel("Normal Gate:"), 2, 0)
        spatial_settings.addWidget(self.spatial_smooth_normal_angle, 2, 1)
        spatial_settings.addWidget(QtWidgets.QLabel("Neighbor Limit:"), 2, 2)
        spatial_settings.addWidget(self.spatial_smooth_max_neighbors, 2, 3)
        spatial_settings.addWidget(QtWidgets.QLabel("Cross-Region Mix:"), 3, 0)
        spatial_settings.addWidget(self.spatial_smooth_cross_region, 3, 1)

        spatial_smooth_btn = QtWidgets.QPushButton("Auto Hammer Weight Spikes")
        spatial_smooth_btn.setToolTip(
            "Find isolated weight discontinuities and repair only those vertices using connected-neighbor consensus. Preserves coherent gradients to avoid noodle-like deformation."
        )
        spatial_smooth_btn.clicked.connect(self.auto_hammer_weight_spikes)
        spatial_full_smooth_btn = QtWidgets.QPushButton("Auto Smooth Whole Mesh / Selected Verts")
        spatial_full_smooth_btn.setToolTip(
            "Smooth the entire selected mesh, or only the selected vertices when component vertices are selected. Uses connected surface flow with spatial gap bridging."
        )
        spatial_full_smooth_btn.clicked.connect(self.smooth_skin_weights_spatially)
        brush_row = QtWidgets.QHBoxLayout()
        spatial_brush_btn = QtWidgets.QPushButton("Activate Surface Smooth Brush")
        spatial_brush_btn.setToolTip(
            "Paint topology-independent skin smoothing on the visible surface. Hold B and drag to resize."
        )
        spatial_brush_btn.clicked.connect(self.activate_spatial_skin_smooth_brush)
        spatial_brush_exit_btn = QtWidgets.QPushButton("Exit Brush")
        spatial_brush_exit_btn.clicked.connect(self.deactivate_spatial_skin_smooth_brush)
        brush_row.addWidget(spatial_brush_btn)
        brush_row.addWidget(spatial_brush_exit_btn)

        skin_layout.addWidget(export_skin_btn)
        skin_layout.addWidget(import_skin_btn)
        skin_layout.addWidget(transfer_skin_btn)
        skin_layout.addSpacing(8)
        skin_layout.addLayout(spatial_settings)
        skin_layout.addWidget(spatial_smooth_btn)
        skin_layout.addWidget(spatial_full_smooth_btn)
        skin_layout.addLayout(brush_row)

        if self.host_mode != "maya":
            spatial_smooth_btn.setEnabled(False)
            spatial_full_smooth_btn.setEnabled(False)
            spatial_brush_btn.setEnabled(False)
            spatial_brush_exit_btn.setEnabled(False)
            spatial_smooth_btn.setToolTip(
                "Surface-spatial smoothing currently requires live Maya mesh vertex and skinCluster data."
            )
            spatial_full_smooth_btn.setToolTip(
                "Skin-weight smoothing currently requires live Maya mesh vertex and skinCluster data."
            )

        # Constructed here to keep the existing callbacks/settings together;
        # _build_skinning_tab reparents the complete panel into its own tab.
        self.rig_layout.addWidget(self.skin_group)

        # ------------------------------------------------------------
        # Full Rig Actions Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)
        actions_group = QtWidgets.QGroupBox("Full Rig Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)

        template_form = QtWidgets.QFormLayout()
        self.rig_template_path_field = QtWidgets.QLineEdit(rig_template.DEFAULT_BIPED_RIG_TEMPLATE)
        self.rig_template_path_field.setToolTip("Path to the biped rig template scene that includes the RFL joints.")
        template_path_btn = QtWidgets.QPushButton("Select")
        template_path_btn.setToolTip("Choose a Maya .ma/.mb rig template file.")
        template_path_btn.clicked.connect(self.pick_rig_template_path)
        template_path_row = QtWidgets.QHBoxLayout()
        template_path_row.addWidget(self.rig_template_path_field)
        template_path_row.addWidget(template_path_btn)
        template_form.addRow("Biped Template:", template_path_row)

        self.rig_template_namespace_field = QtWidgets.QLineEdit("")
        self.rig_template_namespace_field.setToolTip("Optional namespace for referencing or importing the template.")
        template_form.addRow("Namespace:", self.rig_template_namespace_field)
        actions_layout.addLayout(template_form)

        template_btn_row = QtWidgets.QHBoxLayout()
        import_template_btn = QtWidgets.QPushButton("Import Biped Template")
        import_template_btn.setToolTip("Import the studio biped template into the current Maya scene and report RFL joints.")
        import_template_btn.clicked.connect(lambda: self.load_biped_rig_template(reference=False))
        reference_template_btn = QtWidgets.QPushButton("Reference Biped Template")
        reference_template_btn.setToolTip("Reference the studio biped template into the current Maya scene and report RFL joints.")
        reference_template_btn.clicked.connect(lambda: self.load_biped_rig_template(reference=True))
        template_btn_row.addWidget(import_template_btn)
        template_btn_row.addWidget(reference_template_btn)
        actions_layout.addLayout(template_btn_row)

        placement_btn_row = QtWidgets.QHBoxLayout()
        preview_placement_btn = QtWidgets.QPushButton("Preview Joint Placement")
        preview_placement_btn.setToolTip(
            "Analyze the selected mesh and create color-coded placement guides without creating joints."
        )
        preview_placement_btn.clicked.connect(self.preview_selected_joint_placement)
        fit_template_btn = QtWidgets.QPushButton("Fit Mapped Skeleton / Default Template")
        fit_template_btn.setToolTip(
            "Fit the active Rig Mapping hierarchy when mapped joints exist; otherwise load and fit the 280-joint studio template."
        )
        fit_template_btn.clicked.connect(self.fit_template_to_selected_mesh)
        placement_btn_row.addWidget(preview_placement_btn)
        placement_btn_row.addWidget(fit_template_btn)
        actions_layout.addLayout(placement_btn_row)

        regression_btn_row = QtWidgets.QHBoxLayout()
        capture_baseline_btn = QtWidgets.QPushButton("Capture Approved Baseline")
        capture_baseline_btn.setToolTip(
            "Save normalized golden joint positions from the selected mesh and approved fitted skeleton."
        )
        capture_baseline_btn.clicked.connect(self.capture_joint_placement_baseline)
        validate_baseline_btn = QtWidgets.QPushButton("Validate Selected Placement")
        validate_baseline_btn.setToolTip(
            "Compare the selected mesh's proposed placement with a golden baseline without changing the skeleton."
        )
        validate_baseline_btn.clicked.connect(self.validate_joint_placement_baseline)
        run_regression_btn = QtWidgets.QPushButton("Run Placement Regression Suite")
        run_regression_btn.setToolTip(
            "Run every manifest case in a separate Maya batch process and write a JSON report."
        )
        run_regression_btn.clicked.connect(self.run_joint_placement_regression_suite)
        regression_btn_row.addWidget(capture_baseline_btn)
        regression_btn_row.addWidget(validate_baseline_btn)
        regression_btn_row.addWidget(run_regression_btn)
        actions_layout.addLayout(regression_btn_row)
        if self.host_mode != "maya":
            import_template_btn.setText("Load TC Biped Template")
            import_template_btn.setToolTip("Instantiate the selected TC-native skeleton template in this scene.")
            reference_template_btn.hide()
            template_path_btn.setToolTip("Choose a TC .tcrig.json skeleton template file.")
            self.rig_template_path_field.setToolTip("Versioned TC-native skeleton template asset.")
            self.rig_template_namespace_field.setToolTip("Optional namespace for loading another template instance.")
            preview_placement_btn.setEnabled(False)
            fit_template_btn.setEnabled(False)
            capture_baseline_btn.setEnabled(False)
            validate_baseline_btn.setEnabled(False)
            run_regression_btn.setEnabled(False)
            preview_placement_btn.setToolTip("Mesh-volume placement currently requires Maya geometry queries.")
            fit_template_btn.setToolTip("Studio Maya template fitting currently requires Maya.")

        # 1. Create Rig Mapping & Build Full Rig Buttons
        mapping_btn = QtWidgets.QPushButton("Create Rig Mapping")
        mapping_btn.setToolTip("Synchronize and cache the active HumanIK body and face mapping settings.")
        mapping_btn.setStyleSheet(
            "background-color: #3b825c; color: white; font-weight: bold; font-size: 11pt; height: 28px;")
        mapping_btn.clicked.connect(self.create_rig_mapping)
        actions_layout.addWidget(mapping_btn)

        t_pose_btn = QtWidgets.QPushButton("Set T-Pose")
        t_pose_btn.setToolTip(
            "Align mapped arms, straighten and ground mapped legs, then snap RFL joints."
        )
        t_pose_btn.clicked.connect(self.set_t_pose_from_mapping)
        actions_layout.addWidget(t_pose_btn)
        if self.host_mode != "maya":
            t_pose_btn.setEnabled(False)
            t_pose_btn.setToolTip("Setting the deformation skeleton T-pose requires Maya.")

        body_btn = QtWidgets.QPushButton("Build Full Rig")
        body_btn.setToolTip("Construct the complete animation control rig for all mapped body and face modules.")
        body_btn.setStyleSheet(
            "background-color: #1a4d1a; color: white; font-weight: bold; font-size: 12pt; height: 30px;")
        body_btn.clicked.connect(self.build_full_rig)
        actions_layout.addWidget(body_btn)

        remove_rig_btn = QtWidgets.QPushButton("Remove Full Rig")
        remove_rig_btn.setToolTip(
            "Teardown the control rig setup, delete constraints/pads, and restore default skeletons.")
        remove_rig_btn.setStyleSheet(
            "background-color: #8a1a1a; color: white; font-weight: bold; font-size: 12pt; height: 30px;")
        remove_rig_btn.clicked.connect(self.remove_full_rig)
        actions_layout.addWidget(remove_rig_btn)

        store_load_row = QtWidgets.QHBoxLayout()
        global_store_btn = QtWidgets.QPushButton("Store Connections & Switches")
        global_store_btn.setToolTip(
            "Capture and cache all custom parent constraints and space switch states on the controls.")
        global_store_btn.setStyleSheet("background-color: #3b5b82; color: white; font-weight: bold;")
        global_store_btn.clicked.connect(self.store_all_face_connections)

        load_selection_btn = QtWidgets.QPushButton("Load From Selection")
        load_selection_btn.setToolTip("Quickly select parent and target settings using the active scene selection.")
        load_selection_btn.setStyleSheet("background-color: #5c5c5c; color: white; font-weight: bold;")
        load_selection_btn.clicked.connect(self.load_settings_from_selection)

        refresh_details_btn = QtWidgets.QPushButton("↻ Refresh Module Details")
        refresh_details_btn.setToolTip(
            "Query the scene to update the status and parent connection fields for all modules.")
        refresh_details_btn.setStyleSheet("background-color: #4a4a2a; color: #ddcc66; font-weight: bold;")
        refresh_details_btn.clicked.connect(self._refresh_all_module_details)

        store_load_row.addWidget(global_store_btn)
        store_load_row.addWidget(load_selection_btn)
        store_load_row.addWidget(refresh_details_btn)
        actions_layout.addLayout(store_load_row)

        self.rig_layout.addWidget(actions_group)

        # ------------------------------------------------------------
        # Body Modules Setup Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)
        body_modules_group = QtWidgets.QGroupBox("Body Modules Setup (Granular Controls)")
        body_modules_layout = QtWidgets.QVBoxLayout(body_modules_group)

        body_form = QtWidgets.QFormLayout()
        self.body_parent_field = QtWidgets.QLineEdit()
        self.body_parent_field.setPlaceholderText("e.g. clavicle_ctrl / pelvis_ctrl (Optional)")
        self.body_parent_field.setToolTip(
            "Optional: Parent control for body modules. If left empty, resolves to optimal scene defaults.")
        body_parent_btn = QtWidgets.QPushButton("Select")
        body_parent_btn.setToolTip("Map selected viewport node as the parent control for body modules.")
        body_parent_btn.clicked.connect(lambda: self._pick_parent(self.body_parent_field))
        body_parent_row = QtWidgets.QHBoxLayout()
        body_parent_row.addWidget(self.body_parent_field)
        body_parent_row.addWidget(body_parent_btn)
        body_form.addRow("Parent Control:", body_parent_row)
        body_modules_layout.addLayout(body_form)
        body_modules_layout.addSpacing(5)

        body_grid = QtWidgets.QGridLayout()
        body_grid.setHorizontalSpacing(10)
        body_grid.setVerticalSpacing(5)
        body_grid.addWidget(QtWidgets.QLabel("<b>Module Name</b>"), 0, 0)
        body_grid.addWidget(QtWidgets.QLabel("<b>Create Setup</b>"), 0, 1)
        body_grid.addWidget(QtWidgets.QLabel("<b>Remove Setup</b>"), 0, 2)
        body_grid.setColumnStretch(3, 3)

        body_list = [
            ("Root / Origin", "root"),
            ("Pelvis & Hips", "pelvis"),
            ("Spine", "spine"),
            ("Left Clavicle", "l_clavicle"),
            ("Right Clavicle", "r_clavicle"),
            ("Neck", "neck"),
            ("Head", "head"),
            ("Left Arm", "l_arm"),
            ("Right Arm", "r_arm"),
            ("Left Leg", "l_leg"),
            ("Right Leg", "r_leg")
        ]
        for idx, (label_text, m_id) in enumerate(body_list, start=1):
            lbl_layout = QtWidgets.QHBoxLayout()
            lbl_layout.setContentsMargins(0, 0, 0, 0)

            toggle_btn = QtWidgets.QToolButton()
            toggle_btn.setText("▶")
            toggle_btn.setFixedSize(16, 16)
            toggle_btn.setStyleSheet("border: none; font-weight: bold; color: #aaaaaa;")

            sel_btn = QtWidgets.QPushButton("⌖")
            sel_btn.setFixedSize(20, 20)
            sel_btn.setToolTip(f"Select root control for {label_text}")
            sel_btn.setStyleSheet("border: none; color: #aaaaaa; font-weight: bold;")
            sel_btn.clicked.connect(lambda checked=False, m=label_text: self._select_module_root(m))

            status_lbl = QtWidgets.QLabel("●")
            status_lbl.setFixedWidth(14)
            status_lbl.setStyleSheet("color: #555555; font-size: 10pt;")
            status_lbl.setToolTip("Module build status: green (built), gray (unbuilt/removed).")

            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet("font-weight: bold;")

            lbl_layout.addWidget(toggle_btn)
            lbl_layout.addWidget(sel_btn)
            lbl_layout.addWidget(status_lbl)
            lbl_layout.addWidget(lbl)
            lbl_layout.addStretch()
            lbl_container = QtWidgets.QWidget()
            lbl_container.setLayout(lbl_layout)

            c_btn = QtWidgets.QPushButton("Create")
            c_btn.setToolTip(f"Build the {label_text} module setup.")
            c_btn.setStyleSheet("background-color: #2e6930; color: white; font-weight: bold;")
            c_btn.clicked.connect(lambda checked=False, m=label_text: self.create_body_module_setup(m))
            self.module_create_buttons[label_text] = c_btn
            r_btn = QtWidgets.QPushButton("Remove")
            r_btn.setToolTip(f"Remove the {label_text} module setup.")
            r_btn.setStyleSheet("background-color: #7d2a2a; color: white; font-weight: bold;")
            r_btn.clicked.connect(lambda checked=False, m=label_text: self.remove_body_module_setup(m))
            self.module_remove_buttons[label_text] = r_btn

            detail_widget = self._make_module_detail_widget(label_text, status_lbl)

            toggle_btn.clicked.connect(
                lambda checked=False, tw=detail_widget, tb=toggle_btn:
                (tw.setVisible(not tw.isVisible()), tb.setText("▼" if tw.isVisible() else "▶"))
            )

            row = idx * 2
            body_grid.addWidget(lbl_container, row, 0)
            body_grid.addWidget(c_btn, row, 1)
            body_grid.addWidget(r_btn, row, 2)
            body_grid.addWidget(detail_widget, row + 1, 0, 1, 3)

        body_modules_layout.addLayout(body_grid)

        additional_header = QtWidgets.QLabel("<b>Additional Rig Systems</b>")
        additional_header.setToolTip(
            "Tool-authored added modules and user-authored systems retained across full rig rebuilds."
        )
        body_modules_layout.addSpacing(8)
        body_modules_layout.addWidget(additional_header)
        self._additional_systems_container = QtWidgets.QWidget()
        self._additional_systems_layout = QtWidgets.QVBoxLayout(
            self._additional_systems_container
        )
        self._additional_systems_layout.setContentsMargins(16, 0, 0, 0)
        self._additional_systems_layout.setSpacing(3)
        body_modules_layout.addWidget(self._additional_systems_container)
        self.rig_layout.addWidget(body_modules_group)

        # ------------------------------------------------------------
        # Face Modules Setup Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)
        face_modules_group = QtWidgets.QGroupBox("Face Modules Setup (Granular Controls)")
        face_modules_layout = QtWidgets.QVBoxLayout(face_modules_group)

        face_form = QtWidgets.QFormLayout()
        self.module_parent_field = QtWidgets.QLineEdit("head1_ctrl")
        self.module_parent_field.setToolTip(
            "Optional: Parent control for face modules (e.g. head1_ctrl). If left empty, resolves to optimal scene defaults.")
        face_parent_btn = QtWidgets.QPushButton("Select")
        face_parent_btn.setToolTip("Map selected viewport node as parent control for face modules.")
        face_parent_btn.clicked.connect(lambda: self._pick_parent(self.module_parent_field))
        face_parent_row = QtWidgets.QHBoxLayout()
        face_parent_row.addWidget(self.module_parent_field)
        face_parent_row.addWidget(face_parent_btn)
        face_form.addRow("Parent Control:", face_parent_row)

        self.module_jaw_ctrl_field = QtWidgets.QLineEdit("jaw_ctrl")
        self.module_jaw_ctrl_field.setToolTip("Name of the jaw control node (e.g. jaw_ctrl).")
        face_jaw_btn = QtWidgets.QPushButton("Select")
        face_jaw_btn.setToolTip("Map selected viewport node as jaw control.")
        face_jaw_btn.clicked.connect(lambda: self._pick_parent(self.module_jaw_ctrl_field))
        face_jaw_row = QtWidgets.QHBoxLayout()
        face_jaw_row.addWidget(self.module_jaw_ctrl_field)
        face_jaw_row.addWidget(face_jaw_btn)
        face_form.addRow("Jaw Control:", face_jaw_row)

        self.module_jaw_jnt_field = QtWidgets.QLineEdit("jaw")
        self.module_jaw_jnt_field.setToolTip("Name of the jaw joint node (e.g. jaw).")
        face_jaw_jnt_btn = QtWidgets.QPushButton("Select")
        face_jaw_jnt_btn.setToolTip("Map selected viewport node as jaw joint.")
        face_jaw_jnt_btn.clicked.connect(lambda: self._pick_parent(self.module_jaw_jnt_field))
        face_jaw_jnt_row = QtWidgets.QHBoxLayout()
        face_jaw_jnt_row.addWidget(self.module_jaw_jnt_field)
        face_jaw_jnt_row.addWidget(face_jaw_jnt_btn)
        face_form.addRow("Jaw Joint:", face_jaw_jnt_row)
        face_modules_layout.addLayout(face_form)
        face_modules_layout.addSpacing(5)

        face_grid = QtWidgets.QGridLayout()
        face_grid.setHorizontalSpacing(10)
        face_grid.setVerticalSpacing(5)
        face_grid.addWidget(QtWidgets.QLabel("<b>Module Name</b>"), 0, 0)
        face_grid.addWidget(QtWidgets.QLabel("<b>Create Setup</b>"), 0, 1)
        face_grid.addWidget(QtWidgets.QLabel("<b>Remove Setup</b>"), 0, 2)
        face_grid.setColumnStretch(3, 3)

        modules = [
            "Brows (Left)",
            "Brows (Right)",
            "Eyelids (Left)",
            "Eyelids (Right)",
            "Mouth & Lips",
            "Eyes Aim",
            "Tongue",
            "Teeth",
            "Other Face Joints"
        ]
        for idx, label_text in enumerate(modules, start=1):
            lbl_layout = QtWidgets.QHBoxLayout()
            lbl_layout.setContentsMargins(0, 0, 0, 0)

            toggle_btn = QtWidgets.QToolButton()
            toggle_btn.setText("▶")
            toggle_btn.setFixedSize(16, 16)
            toggle_btn.setStyleSheet("border: none; font-weight: bold; color: #aaaaaa;")

            sel_btn = QtWidgets.QPushButton("⌖")
            sel_btn.setFixedSize(20, 20)
            sel_btn.setToolTip(f"Select root control for {label_text}")
            sel_btn.setStyleSheet("border: none; color: #aaaaaa; font-weight: bold;")
            sel_btn.clicked.connect(lambda checked=False, m=label_text: self._select_module_root(m))

            status_lbl = QtWidgets.QLabel("●")
            status_lbl.setFixedWidth(14)
            status_lbl.setStyleSheet("color: #555555; font-size: 10pt;")
            status_lbl.setToolTip("Module build status: green (built), gray (unbuilt/removed).")

            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet("font-weight: bold;")
            lbl_layout.addWidget(toggle_btn)
            lbl_layout.addWidget(sel_btn)
            lbl_layout.addWidget(status_lbl)
            lbl_layout.addWidget(lbl)
            lbl_layout.addStretch()
            lbl_container = QtWidgets.QWidget()
            lbl_container.setLayout(lbl_layout)
            c_btn = QtWidgets.QPushButton("Create")
            c_btn.setToolTip(f"Build the {label_text} face module setup.")
            c_btn.setStyleSheet("background-color: #2e6930; color: white; font-weight: bold;")
            c_btn.clicked.connect(lambda checked=False, m=label_text: self.create_face_module_setup(m))
            self.module_create_buttons[label_text] = c_btn
            r_btn = QtWidgets.QPushButton("Remove")
            r_btn.setToolTip(f"Remove the {label_text} face module setup.")
            r_btn.setStyleSheet("background-color: #7d2a2a; color: white; font-weight: bold;")
            r_btn.clicked.connect(lambda checked=False, m=label_text: self.remove_face_module_setup(m))
            self.module_remove_buttons[label_text] = r_btn

            detail_widget = self._make_module_detail_widget(label_text, status_lbl)

            toggle_btn.clicked.connect(
                lambda checked=False, tw=detail_widget, tb=toggle_btn:
                (tw.setVisible(not tw.isVisible()), tb.setText("▼" if tw.isVisible() else "▶"))
            )

            row = idx * 2
            face_grid.addWidget(lbl_container, row, 0)
            face_grid.addWidget(c_btn, row, 1)
            face_grid.addWidget(r_btn, row, 2)
            face_grid.addWidget(detail_widget, row + 1, 0, 1, 3)

        face_modules_layout.addLayout(face_grid)
        self.rig_layout.addWidget(face_modules_group)

        self.rig_layout.addStretch()

        # ---------- End of Tab ----------

        self.rig_layout.addSpacing(15)
        self.tabs.addTab(scroll_area, "Rigging")

    def _build_skinning_tab(self):
        """Move all skinning tools into a dedicated, scrollable tab."""
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        skin_container = QtWidgets.QWidget()
        self.skinning_layout = QtWidgets.QVBoxLayout(skin_container)
        self.skinning_layout.setContentsMargins(10, 10, 10, 10)

        self.rig_layout.removeWidget(self.skin_group)
        self.skin_group.setParent(skin_container)
        self.skinning_layout.addWidget(self.skin_group)
        self.skinning_layout.addStretch()

        scroll_area.setWidget(skin_container)
        self.tabs.addTab(scroll_area, "Skinning")

    def _build_mesh_tab(self):
        """Build the persistent Maya-to-Unreal mesh definition surface."""
        self._mesh_export_asset_data = {}
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)

        intro = QtWidgets.QLabel(
            "Define exactly which Maya skinned meshes belong to this export, then choose whether Unreal "
            "creates a new Skeletal Mesh or overwrites an existing one. Export removes the generated rig "
            "and restores the checked meshes to bind pose."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        maya_group = QtWidgets.QGroupBox("Maya Mesh Export Set")
        maya_layout = QtWidgets.QVBoxLayout(maya_group)
        self.mesh_export_mesh_list = QtWidgets.QListWidget()
        self.mesh_export_mesh_list.setMinimumHeight(150)
        maya_layout.addWidget(self.mesh_export_mesh_list)
        maya_buttons = QtWidgets.QHBoxLayout()
        refresh_scene = QtWidgets.QPushButton("Refresh Scene Meshes")
        use_selected = QtWidgets.QPushButton("Use Selected Meshes")
        select_all = QtWidgets.QPushButton("Select All")
        clear_all = QtWidgets.QPushButton("Clear")
        refresh_scene.clicked.connect(self.refresh_mesh_export_scene_meshes)
        use_selected.clicked.connect(self.use_selected_meshes_for_export)
        select_all.clicked.connect(lambda: self._set_all_mesh_export_items(True))
        clear_all.clicked.connect(lambda: self._set_all_mesh_export_items(False))
        for button in (refresh_scene, use_selected, select_all, clear_all):
            maya_buttons.addWidget(button)
        maya_buttons.addStretch()
        maya_layout.addLayout(maya_buttons)
        layout.addWidget(maya_group)

        unreal_group = QtWidgets.QGroupBox("Unreal Skeletal Mesh Definition")
        form = QtWidgets.QFormLayout(unreal_group)
        self.mesh_export_rig_name = QtWidgets.QLineEdit(self.char_name.text().strip() or "Character")
        self.mesh_export_rig_name.setToolTip("Used for SKM_, SK_, and PHYS_ names when creating new assets.")
        form.addRow("Rig / Asset Name:", self.mesh_export_rig_name)

        output_row = QtWidgets.QHBoxLayout()
        default_folder = os.path.dirname(self.export_path.text().strip()) or os.path.dirname(get_default_export_path())
        self.mesh_export_output_directory = QtWidgets.QLineEdit(default_folder.replace("\\", "/"))
        output_browse = QtWidgets.QPushButton("Browse")
        output_browse.clicked.connect(self.browse_mesh_export_directory)
        output_row.addWidget(self.mesh_export_output_directory)
        output_row.addWidget(output_browse)
        form.addRow("FBX Folder:", output_row)

        self.mesh_export_destination = QtWidgets.QLineEdit("/Game/Characters")
        self.mesh_export_destination.setToolTip(
            "Parent folder. A child folder named from Rig / Asset Name is created automatically."
        )
        form.addRow("New Asset Parent Folder:", self.mesh_export_destination)

        target_row = QtWidgets.QHBoxLayout()
        self.mesh_export_target = QtWidgets.QComboBox()
        self.mesh_export_target.addItem("Create New Skeletal Mesh", "")
        refresh_unreal = QtWidgets.QPushButton("Refresh Unreal Assets")
        refresh_unreal.clicked.connect(self.refresh_mesh_export_unreal_assets)
        target_row.addWidget(self.mesh_export_target, 1)
        target_row.addWidget(refresh_unreal)
        form.addRow("Skeletal Mesh:", target_row)

        skeleton_policy = QtWidgets.QWidget()
        skeleton_policy_layout = QtWidgets.QHBoxLayout(skeleton_policy)
        skeleton_policy_layout.setContentsMargins(0, 0, 0, 0)
        self.mesh_export_new_skeleton = QtWidgets.QRadioButton("Create New Skeleton")
        self.mesh_export_existing_skeleton = QtWidgets.QRadioButton("Use Existing Skeleton")
        self.mesh_export_new_skeleton.setChecked(True)
        skeleton_policy_layout.addWidget(self.mesh_export_new_skeleton)
        skeleton_policy_layout.addWidget(self.mesh_export_existing_skeleton)
        skeleton_policy_layout.addStretch()
        form.addRow("Skeleton Policy:", skeleton_policy)

        self.mesh_export_skeleton = QtWidgets.QComboBox()
        self.mesh_export_skeleton.setEnabled(False)
        form.addRow("Existing Skeleton:", self.mesh_export_skeleton)

        self.mesh_export_create_physics = QtWidgets.QCheckBox("Create new or retain existing Physics Asset")
        self.mesh_export_create_physics.setChecked(True)
        form.addRow("Physics:", self.mesh_export_create_physics)
        layout.addWidget(unreal_group)

        self.mesh_export_preview = QtWidgets.QLabel()
        self.mesh_export_preview.setWordWrap(True)
        self.mesh_export_preview.setStyleSheet(
            "background-color: #292929; border: 1px solid #555; padding: 8px;"
        )
        layout.addWidget(self.mesh_export_preview)

        send_unreal = QtWidgets.QPushButton("Remove Rig, Export Defined Meshes && Import to Unreal")
        send_unreal.setStyleSheet(
            "background-color: #46356f; color: white; font-weight: bold; font-size: 11pt; height: 34px;"
        )
        send_unreal.clicked.connect(self.send_skeletal_mesh_to_unreal)
        if self.host_mode != "maya":
            send_unreal.setEnabled(False)
            send_unreal.setToolTip("Skeletal FBX preparation currently requires Maya.")
        layout.addWidget(send_unreal)
        layout.addStretch()

        self.mesh_export_target.currentIndexChanged.connect(self._mesh_export_target_changed)
        self.mesh_export_new_skeleton.toggled.connect(self._update_mesh_export_preview)
        self.mesh_export_existing_skeleton.toggled.connect(self._mesh_export_skeleton_policy_changed)
        self.mesh_export_skeleton.currentIndexChanged.connect(self._update_mesh_export_preview)
        self.mesh_export_rig_name.textChanged.connect(self._update_mesh_export_preview)
        self.mesh_export_destination.textChanged.connect(self._update_mesh_export_preview)
        self.mesh_export_create_physics.toggled.connect(self._update_mesh_export_preview)
        self.mesh_export_mesh_list.itemChanged.connect(self._update_mesh_export_preview)
        self.char_name.textChanged.connect(self._sync_mesh_export_rig_name)

        scroll_area.setWidget(container)
        self.tabs.addTab(scroll_area, "Mesh")
        self._update_mesh_export_preview()

    def _sync_mesh_export_rig_name(self, value):
        if not self.mesh_export_rig_name.hasFocus():
            self.mesh_export_rig_name.setText(str(value or ""))

    def browse_mesh_export_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select FBX Export Folder", self.mesh_export_output_directory.text()
        )
        if directory:
            self.mesh_export_output_directory.setText(directory.replace("\\", "/"))

    def _set_all_mesh_export_items(self, checked):
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for index in range(self.mesh_export_mesh_list.count()):
            self.mesh_export_mesh_list.item(index).setCheckState(state)

    def _checked_mesh_export_items(self):
        return [
            str(self.mesh_export_mesh_list.item(index).data(QtCore.Qt.UserRole) or "")
            for index in range(self.mesh_export_mesh_list.count())
            if self.mesh_export_mesh_list.item(index).checkState() == QtCore.Qt.Checked
        ]

    def refresh_mesh_export_scene_meshes(self, *_args):
        if self.host_mode != "maya" or unreal_skeletal_export is None:
            return
        previous = set(self._checked_mesh_export_items())
        selected = set(cmds.ls(selection=True, long=True) or [])
        meshes = unreal_skeletal_export.list_skinned_meshes()
        selected_meshes = set()
        for mesh in meshes:
            shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True) or []
            if mesh in selected or any(shape in selected for shape in shapes):
                selected_meshes.add(mesh)
        checked = previous or selected_meshes or set(meshes)
        self.mesh_export_mesh_list.clear()
        for mesh in meshes:
            item = QtWidgets.QListWidgetItem(mesh)
            item.setData(QtCore.Qt.UserRole, mesh)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if mesh in checked else QtCore.Qt.Unchecked)
            self.mesh_export_mesh_list.addItem(item)
        self._update_mesh_export_preview()

    def use_selected_meshes_for_export(self):
        selected = set(cmds.ls(selection=True, long=True) or []) if self.host_mode == "maya" else set()
        matched = 0
        for index in range(self.mesh_export_mesh_list.count()):
            item = self.mesh_export_mesh_list.item(index)
            mesh = str(item.data(QtCore.Qt.UserRole) or "")
            shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True) or []
            checked = mesh in selected or any(shape in selected for shape in shapes)
            item.setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
            matched += int(checked)
        if not matched:
            self._notify_operation("No Export Meshes Selected", "Select one or more skinned meshes in Maya.", "warning")

    def refresh_mesh_export_unreal_assets(self):
        try:
            assets = usp.run_list_skeletal_import_targets("/Game")
        except Exception as exc:
            self._notify_operation(
                "Unreal Asset Discovery Failed",
                "Connect the Unreal Tech Connector bridge, then retry.\n\n{}".format(exc),
                "error",
            )
            return
        previous_mesh = str(self.mesh_export_target.currentData() or "")
        previous_skeleton = str(self.mesh_export_skeleton.currentData() or "")
        self._mesh_export_asset_data = dict(assets or {})
        self.mesh_export_target.clear()
        self.mesh_export_target.addItem("Create New Skeletal Mesh", "")
        for row in self._mesh_export_asset_data.get("skeletal_meshes") or []:
            path = str(row.get("path") or "")
            self.mesh_export_target.addItem("Overwrite Existing: " + (path or str(row.get("name") or "")), path)
        self.mesh_export_skeleton.clear()
        for row in self._mesh_export_asset_data.get("skeletons") or []:
            path = str(row.get("path") or "")
            self.mesh_export_skeleton.addItem(path or str(row.get("name") or ""), path)
        mesh_index = self.mesh_export_target.findData(previous_mesh)
        self.mesh_export_target.setCurrentIndex(mesh_index if mesh_index >= 0 else 0)
        skeleton_index = self.mesh_export_skeleton.findData(previous_skeleton)
        if skeleton_index >= 0:
            self.mesh_export_skeleton.setCurrentIndex(skeleton_index)
        self._mesh_export_target_changed()
        self._notify_operation(
            "Unreal Assets Refreshed",
            "Found {} Skeletal Meshes and {} Skeletons.".format(
                len(self._mesh_export_asset_data.get("skeletal_meshes") or []),
                len(self._mesh_export_asset_data.get("skeletons") or []),
            ),
            "success",
        )

    def _mesh_export_target_changed(self, *_args):
        path = str(self.mesh_export_target.currentData() or "")
        overwriting = bool(path)
        self.mesh_export_destination.setEnabled(not overwriting)
        self.mesh_export_new_skeleton.setEnabled(not overwriting)
        if overwriting:
            self.mesh_export_existing_skeleton.setChecked(True)
            rows = getattr(self, "_mesh_export_asset_data", {}).get("skeletal_meshes") or []
            row = next((item for item in rows if str(item.get("path") or "") == path), {})
            skeleton_path = str(row.get("skeleton") or "")
            index = self.mesh_export_skeleton.findData(skeleton_path)
            if index >= 0:
                self.mesh_export_skeleton.setCurrentIndex(index)
            self.mesh_export_skeleton.setEnabled(False)
        else:
            self.mesh_export_skeleton.setEnabled(self.mesh_export_existing_skeleton.isChecked())
        self._update_mesh_export_preview()

    def _mesh_export_skeleton_policy_changed(self, *_args):
        overwriting = bool(self.mesh_export_target.currentData())
        self.mesh_export_skeleton.setEnabled(self.mesh_export_existing_skeleton.isChecked() and not overwriting)
        self._update_mesh_export_preview()

    def _update_mesh_export_preview(self, *_args):
        try:
            clean = unreal_skeletal_export.sanitize_rig_name(self.mesh_export_rig_name.text())
            destination = self.mesh_export_destination.text().strip().rstrip("/") or "/Game/Characters"
            character_folder = self._mesh_export_character_folder(destination, clean)
            existing_mesh = str(self.mesh_export_target.currentData() or "")
            mesh = existing_mesh or "{}/SKM_{}".format(character_folder, clean)
            skeleton = (
                str(self.mesh_export_skeleton.currentData() or "<Select Existing Skeleton>")
                if self.mesh_export_existing_skeleton.isChecked()
                else "{}/SK_{}".format(character_folder, clean)
            )
            action = "OVERWRITE EXISTING" if existing_mesh else "CREATE NEW"
            count = len(self._checked_mesh_export_items())
            physics = (
                "Retain existing assignment"
                if existing_mesh and self.mesh_export_create_physics.isChecked()
                else "{}/PHYS_{}".format(character_folder, clean)
                if self.mesh_export_create_physics.isChecked()
                else "Do not create"
            )
            self.mesh_export_preview.setText(
                "{} | {} Maya mesh(es)\nSkeletal Mesh: {}\nSkeleton: {}\nPhysics: {}".format(
                    action,
                    count,
                    mesh,
                    skeleton,
                    physics,
                )
            )
        except (AttributeError, ValueError):
            self.mesh_export_preview.setText("Enter a valid Rig / Asset Name.")

    @staticmethod
    def _mesh_export_character_folder(parent, clean_name):
        parent = "/" + str(parent or "/Game/Characters").strip("/")
        return parent if parent.rsplit("/", 1)[-1].lower() == clean_name.lower() else parent + "/" + clean_name

    def _mesh_export_settings(self):
        clean = unreal_skeletal_export.sanitize_rig_name(self.mesh_export_rig_name.text())
        meshes = self._checked_mesh_export_items()
        if not meshes:
            raise ValueError("Choose at least one Maya skinned mesh to export.")
        output_directory = self.mesh_export_output_directory.text().strip()
        if not output_directory:
            raise ValueError("Choose an FBX output folder.")
        existing_mesh = str(self.mesh_export_target.currentData() or "")
        existing_skeleton = str(self.mesh_export_skeleton.currentData() or "")
        skeleton_mode = "use_existing" if self.mesh_export_existing_skeleton.isChecked() else "create_new"
        if skeleton_mode == "use_existing" and not existing_skeleton:
            raise ValueError("Refresh Unreal assets and choose an existing Skeleton.")
        return {
            "rig_name": clean,
            "output_directory": output_directory,
            "destination_path": self.mesh_export_destination.text().strip(),
            "existing_skeletal_mesh_path": existing_mesh,
            "skeleton_mode": skeleton_mode,
            "existing_skeleton_path": existing_skeleton,
            "create_physics_asset": self.mesh_export_create_physics.isChecked(),
            "meshes": meshes,
        }

    def _build_vehicle_tab(self):
        vehicle_tab = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(vehicle_tab)

        intro = QtWidgets.QLabel(
            "Build a Maya vehicle control rig from the joint-only vehicle template. "
            "Ground meshes are raycast live in Maya. Wheel roll is accumulated from each wheel's "
            "signed travel using degrees = (distance / radius) × 180/π."
        )
        intro.setWordWrap(True)
        outer_layout.addWidget(intro)

        template_group = QtWidgets.QGroupBox("Vehicle Joint Template")
        template_layout = QtWidgets.QFormLayout(template_group)
        self.vehicle_template_path_field = QtWidgets.QLineEdit(
            rig_template.DEFAULT_VEHICLE_RIG_TEMPLATE
        )
        vehicle_template_browse = QtWidgets.QPushButton("Select")
        vehicle_template_browse.clicked.connect(self.pick_vehicle_template_path)
        template_path_row = QtWidgets.QHBoxLayout()
        template_path_row.addWidget(self.vehicle_template_path_field)
        template_path_row.addWidget(vehicle_template_browse)
        template_layout.addRow("Template:", template_path_row)
        load_template_btn = QtWidgets.QPushButton("Load Vehicle Joint Template")
        load_template_btn.clicked.connect(self.load_vehicle_joint_template)
        template_layout.addRow(load_template_btn)
        outer_layout.addWidget(template_group)

        build_group = QtWidgets.QGroupBox("Vehicle Rig")
        build_layout = QtWidgets.QVBoxLayout(build_group)
        self.vehicle_preview_geometry_checkbox = QtWidgets.QCheckBox("Create preview chassis and wheels")
        self.vehicle_preview_geometry_checkbox.setChecked(True)
        build_layout.addWidget(self.vehicle_preview_geometry_checkbox)
        build_btn = QtWidgets.QPushButton("Build Vehicle Rig")
        build_btn.setStyleSheet(
            "background-color: #1a4d1a; color: white; font-weight: bold; font-size: 12pt; height: 30px;"
        )
        build_btn.clicked.connect(self.build_vehicle_rig_from_template)
        build_layout.addWidget(build_btn)

        ground_row = QtWidgets.QHBoxLayout()
        assign_ground_btn = QtWidgets.QPushButton("Assign Selected Ground Meshes")
        assign_ground_btn.clicked.connect(self.assign_vehicle_ground)
        update_ground_btn = QtWidgets.QPushButton("Update Ground Now")
        update_ground_btn.clicked.connect(self.update_vehicle_ground)
        ground_row.addWidget(assign_ground_btn)
        ground_row.addWidget(update_ground_btn)
        build_layout.addLayout(ground_row)

        evaluation_row = QtWidgets.QHBoxLayout()
        enable_live_btn = QtWidgets.QPushButton("Enable Live Ground")
        enable_live_btn.clicked.connect(self.enable_vehicle_live_ground)
        reset_roll_btn = QtWidgets.QPushButton("Reset Wheel Roll")
        reset_roll_btn.clicked.connect(self.reset_vehicle_wheel_roll)
        bake_ground_btn = QtWidgets.QPushButton("Bake Playback Range")
        bake_ground_btn.clicked.connect(self.bake_vehicle_ground)
        evaluation_row.addWidget(enable_live_btn)
        evaluation_row.addWidget(reset_roll_btn)
        evaluation_row.addWidget(bake_ground_btn)
        build_layout.addLayout(evaluation_row)

        self.vehicle_auto_steering_checkbox = QtWidgets.QCheckBox(
            "Automatic steering from chassis yaw and path curvature"
        )
        self.vehicle_auto_steering_checkbox.setChecked(True)
        self.vehicle_auto_steering_checkbox.setToolTip(
            "Turn the front wheels from direct chassis yaw or mathematically "
            "derived path curvature. The Steering channel remains a manual offset."
        )
        self.vehicle_auto_steering_checkbox.toggled.connect(
            self.set_vehicle_auto_steering
        )
        build_layout.addWidget(self.vehicle_auto_steering_checkbox)

        self.vehicle_steering_drive_checkbox = QtWidgets.QCheckBox(
            "Steering drives forward/reverse vehicle path"
        )
        self.vehicle_steering_drive_checkbox.setChecked(True)
        self.vehicle_steering_drive_checkbox.setToolTip(
            "Use a no-slip bicycle model: moving the global control forward or "
            "backward follows the front-wheel steering angle and wheelbase."
        )
        self.vehicle_steering_drive_checkbox.toggled.connect(
            self.set_vehicle_steering_drive
        )
        build_layout.addWidget(self.vehicle_steering_drive_checkbox)

        save_btn = QtWidgets.QPushButton("Save Vehicle Rig As...")
        save_btn.clicked.connect(self.save_vehicle_rig_file)
        build_layout.addWidget(save_btn)
        outer_layout.addWidget(build_group)
        outer_layout.addStretch()

        if self.host_mode != "maya" or vehicle_rig is None:
            vehicle_tab.setEnabled(False)
            intro.setText("Vehicle rig construction and Maya mesh raycasts require a live Maya session.")
        self.tabs.addTab(vehicle_tab, "Vehicle")

    def pick_vehicle_template_path(self):
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Vehicle Joint Template",
            self.vehicle_template_path_field.text().strip() or rig_template.DEFAULT_VEHICLE_RIG_TEMPLATE,
            "Maya ASCII/Binary (*.ma *.mb);;All Files (*.*)",
        )
        if path:
            self.vehicle_template_path_field.setText(path.replace("\\", "/"))

    def load_vehicle_joint_template(self):
        try:
            result = rig_template.load_vehicle_rig_template(
                self.vehicle_template_path_field.text().strip() or rig_template.DEFAULT_VEHICLE_RIG_TEMPLATE
            )
            self._notify_operation(
                "Vehicle Template Loaded",
                "Loaded {} joints with {} wheel mounts.".format(
                    sum(len(nodes) for nodes in result["roles"].values()),
                    len(result["wheel_mounts"]),
                ),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Vehicle Template Failed", str(exc), "error")

    def build_vehicle_rig_from_template(self):
        try:
            reload_rig_function_stack()
            roots = vehicle_rig.find_template_roots()
            if not roots:
                loaded = rig_template.load_vehicle_rig_template(
                    self.vehicle_template_path_field.text().strip() or rig_template.DEFAULT_VEHICLE_RIG_TEMPLATE
                )
                roots = loaded["root_joints"]
            result = vehicle_rig.build_vehicle_rig(
                roots[-1],
                create_preview_geometry=self.vehicle_preview_geometry_checkbox.isChecked(),
            )
            self._notify_operation(
                "Vehicle Rig Built",
                "Created {} with {} wheel controls.".format(result["rig_root"], len(result["wheels"])),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Vehicle Rig Failed", str(exc), "error")

    def assign_vehicle_ground(self):
        try:
            result = vehicle_rig.attach_selected_ground()
            self._notify_operation(
                "Vehicle Ground Assigned",
                "Assigned {} polygon ground mesh(es).".format(len(result["ground_meshes"])),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Ground Assignment Failed", str(exc), "error")

    def update_vehicle_ground(self):
        try:
            result = vehicle_rig.update_ground()
            self._notify_operation(
                "Vehicle Ground Updated",
                "Updated {} wheels; {} grounded.".format(result["updated"], result["grounded"]),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Ground Update Failed", str(exc), "error")

    def enable_vehicle_live_ground(self):
        try:
            callbacks = vehicle_rig.install_ground_callback()
            self._notify_operation(
                "Live Ground Enabled",
                "Installed {} real-time Maya evaluation callbacks (drag + playback).".format(
                    len(callbacks)
                ),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Live Ground Failed", str(exc), "error")

    def reset_vehicle_wheel_roll(self):
        try:
            result = vehicle_rig.reset_wheel_roll()
            self._notify_operation(
                "Wheel Roll Reset", "Reset {} wheel accumulators.".format(result["reset"]), "success"
            )
        except Exception as exc:
            self._notify_operation("Wheel Roll Reset Failed", str(exc), "error")

    def set_vehicle_auto_steering(self, enabled):
        try:
            rig_root = vehicle_rig._find_rig_root()
            chassis_control = str(cmds.getAttr(rig_root + ".tcChassisControl") or "")
            vehicle_rig._ensure_auto_steer_attributes(rig_root, chassis_control)
            cmds.setAttr(chassis_control + ".autoSteering", bool(enabled))
            vehicle_rig.install_ground_callback(rig_root)
            vehicle_rig.update_ground(rig_root)
            self._notify_operation(
                "Automatic Steering",
                "Automatic chassis/path steering {}.".format(
                    "enabled" if enabled else "disabled"
                ),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Automatic Steering Failed", str(exc), "error")

    def set_vehicle_steering_drive(self, enabled):
        try:
            rig_root = vehicle_rig._find_rig_root()
            chassis_control = str(cmds.getAttr(rig_root + ".tcChassisControl") or "")
            vehicle_rig._ensure_auto_steer_attributes(rig_root, chassis_control)
            cmds.setAttr(chassis_control + ".steeringDrivesMotion", bool(enabled))
            cmds.setAttr(rig_root + ".tcDriveInitialized", False)
            vehicle_rig.install_ground_callback(rig_root)
            vehicle_rig.update_ground(rig_root)
            self._notify_operation(
                "Steering Drive",
                "Steering-driven vehicle motion {}.".format(
                    "enabled" if enabled else "disabled"
                ),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Steering Drive Failed", str(exc), "error")

    def bake_vehicle_ground(self):
        try:
            result = vehicle_rig.bake_ground()
            self._notify_operation(
                "Vehicle Ground Baked",
                "Baked {} samples across frames {} to {}.".format(
                    result["samples"], result["range"][0], result["range"][1]
                ),
                "success",
            )
        except Exception as exc:
            self._notify_operation("Vehicle Bake Failed", str(exc), "error")

    def save_vehicle_rig_file(self):
        path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Vehicle Rig",
            vehicle_rig.DEFAULT_RIG_PATH,
            "Maya ASCII (*.ma);;Maya Binary (*.mb)",
        )
        if not path:
            return
        try:
            saved = vehicle_rig.save_vehicle_rig(path)
            self._notify_operation("Vehicle Rig Saved", saved, "success")
        except Exception as exc:
            self._notify_operation("Vehicle Save Failed", str(exc), "error")

    def get_space_switch_mode(self):
        return "orient" if self.space_switch_orient_rb.isChecked() else "parent"

    def _get_joint_status_display(self, jnt):
        if not jnt:
            return ""
        if not cmds.objExists(jnt):
            return " (Not in scene)"

        # Check constraints
        relatives = cmds.listRelatives(jnt, children=True, type="constraint") or []
        has_constraint = len(relatives) > 0

        # Check connections
        has_connection = False
        connections = cmds.listConnections(jnt, source=True, destination=False) or []
        for n in connections:
            if not cmds.objExists(n):
                continue
            ct = cmds.objectType(n)
            if "Constraint" in ct or ct in ["blendColors", "multiplyDivide", "plusMinusAverage", "reverse", "condition",
                                            "choice", "animCurve"]:
                has_connection = True
                break

        if not has_connection:
            for attr in ["tx", "ty", "tz", "rx", "ry", "rz", "sx", "sy", "sz"]:
                if cmds.connectionInfo(f"{jnt}.{attr}", isDestination=True):
                    has_connection = True
                    break

        if has_constraint:
            return " [Constrained]"
        if has_connection:
            return " [Connected]"
        return " [Clean]"

    def _update_list_widget(self, list_widget, items):
        """Replace all items in a QListWidget with the given items, appending status color cues."""
        list_widget.clear()
        for jnt in items:
            if not jnt:
                continue
            jnt_clean = jnt.split(" ")[0]
            status = self._get_joint_status_display(jnt_clean)
            item = QtWidgets.QListWidgetItem(jnt_clean + status)
            if "Not in scene" in status:
                item.setForeground(QtGui.QColor("#ff6666"))
            elif "Constrained" in status:
                item.setForeground(QtGui.QColor("#d8b4fe"))  # Sleek purple
            elif "Connected" in status:
                item.setForeground(QtGui.QColor("#fdba74"))  # Warm orange
            else:
                item.setForeground(QtGui.QColor("#86efac"))  # Clean light green
            list_widget.addItem(item)

    def create_space_switch(self):
        sel = cmds.ls(sl=True)

        if len(sel) > 1:
            driven = sel[-1]
            targets = sel[:-1]
            create_rig.create_space_switch(
                driven,
                targets,
                attr_name="space",
                dup_suffix="_spaceTarget",
                constraint_type="parent"
            )

    def create_joints_from_selected_curve(self):
        selection = cmds.ls(selection=True, long=True) or []
        if not selection:
            cmds.warning("Select a curve before creating joints.")
            return

        curve = None
        if self.host_mode == "maya":
            for node in selection:
                if cmds.nodeType(node) == "nurbsCurve":
                    curve = node
                    break
                shapes = cmds.listRelatives(
                    node,
                    shapes=True,
                    noIntermediate=True,
                    type="nurbsCurve",
                    fullPath=True,
                ) or []
                if shapes:
                    curve = node
                    break
        else:
            curve = selection[0]

        if not curve:
            cmds.warning("The selection does not contain a curve.")
            return

        try:
            result = create_rig.create_joints_along_curve(
                curve,
                joint_count=self.curve_joint_count_spin.value(),
                keep_attached=self.curve_joint_keep_attached.isChecked(),
            )
            created = result.get("joints", []) if isinstance(result, dict) else []
            self._notify_operation(
                "Joints Along Curve",
                f"Created {len(created)} evenly spaced joints.",
                "success",
            )
        except Exception as exc:
            self._notify_operation(
                "Joints Along Curve Failed",
                f"Failed to create joints along the curve:\n{exc}",
                "error",
            )

    def populate_default_face_map_from_scene(self):
        """Fill default_face_map with scene joints under HIK head reference."""
        self.default_face_map = setup_hik.populate_default_face_map_from_scene(self.default_face_map)

    def assign_face_from_selection(self, list_widget):
        # Get the current selection of joints in Maya
        selection = cmds.ls(sl=True, type="joint") or []

        if not selection:
            cmds.warning("No joints selected. clearing section")

        # Populate the list widget with the selection
        self._update_list_widget(list_widget, selection)

        # Sync the mapping dict immediately so detail panels can reflect changes
        self.create_rig_mapping()
        self._refresh_all_module_details()

    def pick_rig_template_path(self):
        file_filter = "Maya Files (*.ma *.mb);;All Files (*.*)"
        title = "Select Biped Rig Template"
        if self.host_mode != "maya":
            file_filter = "TC Rig Templates (*.tcrig.json);;JSON Files (*.json);;All Files (*.*)"
            title = "Select TC Biped Skeleton Template"
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            title,
            self.rig_template_path_field.text().strip() or rig_template.DEFAULT_BIPED_RIG_TEMPLATE,
            file_filter,
        )
        if path:
            self.rig_template_path_field.setText(path.replace("\\", "/"))

    def load_biped_rig_template(self, reference=False):
        template_path = self.rig_template_path_field.text().strip() or rig_template.DEFAULT_BIPED_RIG_TEMPLATE
        namespace = self.rig_template_namespace_field.text().strip()
        try:
            cmds.undoInfo(openChunk=True, chunkName="Load Biped Rig Template")
            result = rig_template.load_biped_rig_template(
                template_path=template_path,
                namespace=namespace,
                reference=reference,
            )
            if self.host_mode != "maya":
                for slot, row in dict(result.get("joint_map") or {}).items():
                    joint = str((row or {}).get("joint") or "")
                    if slot in self.fields and joint:
                        self.fields[slot] = joint
                        self.update_button_color(slot)
                if isinstance(result.get("face_map"), dict):
                    self.default_face_map = result["face_map"]
                    for key_path, list_widget in self.face_lists.items():
                        data = self.default_face_map
                        for key in key_path:
                            data = data[key]
                        values = data if isinstance(data, list) else [data] if data else []
                        self._update_list_widget(list_widget, values)
            self.create_rig_mapping()
            self._load_module_metadata_from_scene(report_missing=False)
            self._refresh_all_module_details()
            self._notify_operation(
                "TC Biped Template Loaded" if self.host_mode != "maya" else "Biped Template Loaded",
                ("Loaded TC-native biped skeleton template.\n\n" if self.host_mode != "maya" else "Loaded biped rig template.\n\n")
                +
                f"Root joints: {len(result.get('root_joints') or [])}\n"
                f"RFL joints: {result.get('rfl_joint_count', 0)}\n"
                f"New nodes: {result.get('new_node_count', 0)}",
                "success",
            )
            return result
        except Exception as e:
            traceback.print_exc()
            self._notify_operation("Biped Template Load Failed", str(e), "error")
            raise
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

    def preview_selected_joint_placement(self):
        """Create confidence-colored guides without modifying the skeleton."""
        # Development hot reload: placement changes should be testable from an
        # already-open UI without closing the window or restarting Maya.
        reload_rig_function_stack(force=True)
        template_path = self.rig_template_path_field.text().strip() or rig_template.DEFAULT_BIPED_RIG_TEMPLATE
        try:
            self.create_rig_mapping(refresh_details=False)
            studio_namespace = joint_placer.mapped_studio_template_namespace(
                self.default_map
            )
            placement_map = None if studio_namespace is not None else self.default_map
            cmds.undoInfo(openChunk=True, chunkName="Preview Joint Placement")
            preview = joint_placer.preview_selected_mesh_joint_placement(
                solver="production",
                template_path=template_path,
                create_guides=True,
                joint_map=placement_map,
            )
            details = []
            if preview.outside_joints:
                details.append("Outside/unverified: {0}".format(", ".join(preview.outside_joints)))
            if preview.anatomical_issues:
                details.append("Anatomy issues: {0}".format("; ".join(preview.anatomical_issues)))
            message = (
                "Created {0} placement guides.\nPlacement source: {1}\nReview required: {2}".format(
                    len(preview.guides),
                    "Active Rig Mapping" if joint_placer.mapped_hierarchy_requested(placement_map) else preview.template_path,
                    preview.requires_review,
                )
            )
            if details:
                message += "\n\n" + "\n".join(details)
            self._notify_operation(
                "Joint Placement Preview",
                message,
                "warning" if preview.requires_review else "success",
            )
            return preview
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation("Joint Placement Preview Failed", str(exc), "error")
            raise
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

    def fit_template_to_selected_mesh(self):
        """Fit the active mapped hierarchy, or the studio template as fallback."""
        action_started = time.perf_counter()
        # Development hot reload: always execute the current on-disk placer.
        # Remove ``force=True`` when the rig stack returns to release mode.
        reload_rig_function_stack(force=True)
        reload_elapsed = time.perf_counter() - action_started
        selection = cmds.ls(selection=True, long=False) or []
        if not selection:
            self._notify_operation("Fit Template", "Select a mesh transform first.", "warning")
            return None
        template_path = self.rig_template_path_field.text().strip() or rig_template.DEFAULT_BIPED_RIG_TEMPLATE
        namespace = self.rig_template_namespace_field.text().strip()
        fit_started = time.perf_counter()
        try:
            self.create_rig_mapping(refresh_details=False)
            mapped_namespace_fn = getattr(
                joint_placer, "mapped_studio_template_namespace", None
            )
            studio_namespace = (
                mapped_namespace_fn(self.default_map)
                if callable(mapped_namespace_fn) else None
            )
            placement_map = None if studio_namespace is not None else self.default_map
            if studio_namespace is not None:
                namespace = studio_namespace
            mapped_request_fn = getattr(
                joint_placer, "mapped_hierarchy_requested", None
            )
            use_mapping = (
                bool(mapped_request_fn(placement_map))
                if callable(mapped_request_fn) else False
            )
            builder = joint_placer.build_basic_biped_skeleton
            builder_parameters = inspect.signature(builder).parameters
            supports_template_fit = {
                "solver", "template_path", "template_namespace", "joint_map"
            }.issubset(builder_parameters)
            if not supports_template_fit:
                # The GitHub-compatible legacy placer only creates a fresh
                # basic skeleton. It cannot fit an existing studio hierarchy,
                # and its replace guard correctly protects non-generated rigs.
                existing_origins = cmds.ls(
                    "origin", "*:origin", type="joint", long=True
                ) or []
                protected_origins = []
                for root in existing_origins:
                    has_generated_tag = cmds.attributeQuery(
                        joint_placer.GENERATED_ATTR, node=root, exists=True
                    )
                    is_generated = (
                        bool(cmds.getAttr(root + "." + joint_placer.GENERATED_ATTR))
                        if has_generated_tag else False
                    )
                    if not is_generated:
                        protected_origins.append(root)
                if protected_origins:
                    self._notify_operation(
                        "Template Fit Unavailable",
                        "This GitHub-compatible placer can only build a new basic "
                        "skeleton; it cannot fit the existing rig hierarchy. "
                        "The existing origin was preserved and no scene changes "
                        "were made. Use the production template-fit placer to fit "
                        "this rig.",
                        "warning",
                    )
                    return None
            cmds.undoInfo(openChunk=True, chunkName="Fit Mapped Skeleton Or Studio Template")
            if supports_template_fit:
                result = builder(
                    mesh=selection[0],
                    solver="production",
                    template_path=template_path,
                    template_namespace=namespace,
                    create_guides=True,
                    # Match direct production placement: uncertain containment is
                    # reported for review, not promoted to a UI-only hard failure.
                    require_interior=False,
                    joint_map=placement_map,
                    import_skin_weights=False,
                )
            else:
                # The GitHub placer has a smaller API: it generates its
                # mesh-based biped directly and does not accept template or
                # mapped-hierarchy options.
                use_mapping = False
                result = builder(
                    mesh=selection[0],
                    orient=True,
                    replace_existing=True,
                    create_guides=True,
                )
            solve_elapsed = time.perf_counter() - fit_started
            refresh_started = time.perf_counter()
            updates_enabled = self.updatesEnabled()
            if updates_enabled:
                self.setUpdatesEnabled(False)
            try:
                for slot, row in result.body_joint_map.items():
                    joint = str((row or {}).get("joint") or "")
                    if slot in self.fields and joint:
                        self.fields[slot] = joint
                        self.update_button_color(slot)
                self.create_rig_mapping(refresh_details=False)
                self._load_module_metadata_from_scene(report_missing=False)
            finally:
                if updates_enabled:
                    self.setUpdatesEnabled(True)
            refresh_elapsed = time.perf_counter() - refresh_started
            print(
                "[HIK UI][timing] Reload={0:.3f}s, solve={1:.3f}s, "
                "UI refresh={2:.3f}s, dialog ready={3:.3f}s".format(
                    reload_elapsed,
                    solve_elapsed,
                    refresh_elapsed,
                    time.perf_counter() - action_started,
                )
            )
            detail_report = getattr(result, "detail_placement_report", None) or {}
            detail_message = ""
            if detail_report.get("metahuman_style"):
                skipped_count = len(detail_report.get("skipped_driven_or_locked") or [])
                detail_message = (
                    "\nMetaHuman detail placement: {0} twists, {1} corrective roots, "
                    "{2} twist correctives, {3} surface correctives; "
                    "{4}/{5} detected correctives verified; "
                    "{6} facial DNA joints protected; {7} driven/locked joints skipped."
                ).format(
                    detail_report.get("twist_joints_placed", 0),
                    detail_report.get("corrective_roots_placed", 0),
                    detail_report.get("twist_correctives_placed", 0),
                    detail_report.get("surface_correctives_placed", 0),
                    detail_report.get("verified_corrective_joint_count", 0),
                    detail_report.get("detected_corrective_joint_count", 0),
                    detail_report.get("protected_facial_joints", 0),
                    skipped_count,
                )
                unverified = detail_report.get("skipped_unverified") or []
                validation_errors = detail_report.get("corrective_validation_errors") or []
                twist_errors = detail_report.get("twist_validation_errors") or []
                unclassified = detail_report.get("unclassified_corrective_joints") or []
                if unverified or validation_errors or twist_errors or unclassified:
                    detail_message += (
                        "\nDisable or remove RigLogic/RBF drivers in neutral-pose editing mode, "
                        "then run the fit again for any unverified corrective or twist joints."
                    )
            if supports_template_fit:
                outside_joints = getattr(result, "outside_joints", []) or []
                requires_review = bool(getattr(result, "requires_review", False))
                self._notify_operation(
                    "Mapped Skeleton Fitted" if use_mapping else "Studio Template Fitted",
                    "Fitted {0} {1} skeleton joints using {2} verified anchors.\n"
                    "Reverse-foot helpers: {3}\nReview required: {4}{5}".format(
                        result.template_joint_count,
                        "mapped" if use_mapping else "high-resolution template",
                        len(result.points) - len(outside_joints),
                        getattr(result, "reverse_foot_joint_count", 0),
                        requires_review,
                        detail_message,
                    ),
                    "warning" if requires_review else "success",
                )
            else:
                self._notify_operation(
                    "Automatic Skeleton Placed",
                    "The GitHub-compatible placer generated {0} mesh-based joints. "
                    "Template-specific fitting and review checks are not available "
                    "in this placer version.".format(len(getattr(result, "points", {}))),
                    "info",
                )
            return result
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation("Template Fit Failed", str(exc), "error")
            raise
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

    def capture_joint_placement_baseline(self):
        """Save the selected approved mesh/skeleton pair as normalized golden data."""
        default_dir = os.path.join(
            os.path.dirname(joint_placement_regression.__file__),
            "joint_placement_regression_cases",
            "baselines",
        ).replace("\\", "/")
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Capture Approved Joint Placement Baseline",
            default_dir,
            "Joint Placement Baseline (*.json)",
        )
        if not path:
            return None
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            data = joint_placement_regression.capture_selected_baseline(
                path,
                case_id=os.path.splitext(os.path.basename(path))[0],
                namespace=self.rig_template_namespace_field.text().strip(),
            )
            self._notify_operation(
                "Placement Baseline Captured",
                "Captured {0} approved anchors.\n{1}".format(
                    len(data["skeleton"]["anchors"]), path
                ),
                "success",
            )
            return data
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation("Baseline Capture Failed", str(exc), "error")
            raise

    def validate_joint_placement_baseline(self):
        """Run non-destructive placement QA against one approved baseline."""
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Joint Placement Baseline",
            os.path.join(
                os.path.dirname(joint_placement_regression.__file__),
                "joint_placement_regression_cases",
                "baselines",
            ).replace("\\", "/"),
            "Joint Placement Baseline (*.json)",
        )
        if not path:
            return None
        template_path = self.rig_template_path_field.text().strip() or rig_template.DEFAULT_BIPED_RIG_TEMPLATE
        try:
            report = joint_placement_regression.evaluate_selected_mesh(path, template_path)
            metrics = report["metrics"]
            message = (
                "{0}\nMean anchor error: {1:.5f}\nMax anchor error: {2:.5f}\n"
                "Max plane deviation: {3:.8f}".format(
                    "PASS" if report["passed"] else "FAIL",
                    metrics["mean_anchor_error"],
                    metrics["max_anchor_error"],
                    metrics["max_plane_deviation"],
                )
            )
            if report["failures"]:
                message += "\n\n" + "\n".join(report["failures"])
            self._notify_operation(
                "Joint Placement Validation",
                message,
                "success" if report["passed"] else "warning",
            )
            return report
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation("Placement Validation Failed", str(exc), "error")
            raise

    def run_joint_placement_regression_suite(self):
        """Launch the manifest suite in mayapy so the artist scene is untouched."""
        default_manifest = os.path.join(
            os.path.dirname(joint_placement_regression.__file__),
            "joint_placement_regression_cases",
            "manifest.json",
        ).replace("\\", "/")
        manifest, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Joint Placement Regression Manifest",
            default_manifest,
            "Regression Manifest (*.json)",
        )
        if not manifest:
            return None
        report_path = os.path.join(os.path.dirname(manifest), "latest_report.json").replace("\\", "/")
        runner = os.path.join(
            os.path.dirname(joint_placement_regression.__file__),
            "joint_placement_regression_runner.py",
        ).replace("\\", "/")
        executable_dir = os.path.dirname(sys.executable)
        mayapy = os.path.join(executable_dir, "mayapy.exe")
        if not os.path.exists(mayapy):
            mayapy = sys.executable

        process = QtCore.QProcess(self)
        self._joint_regression_process = process
        process.setProgram(mayapy)
        process.setArguments([runner, "--manifest", manifest, "--report", report_path])

        def finished(exit_code, _exit_status):
            stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            message = "Report: {0}".format(report_path)
            if stdout:
                message += "\n\n" + stdout[-1200:]
            if stderr and exit_code:
                message += "\n\n" + stderr[-1200:]
            self._notify_operation(
                "Placement Regression Suite",
                message,
                "success" if exit_code == 0 else "warning",
            )
            process.deleteLater()
            self._joint_regression_process = None

        process.finished.connect(finished)
        process.start()
        self._notify_operation(
            "Placement Regression Suite",
            "Regression suite started in Maya batch mode. Your current scene will not be modified.",
            "info",
        )
        return report_path

    def create_rig_mapping(self, refresh_details=True):
        # Check if there are empty slots in HIK fields
        empty_slots = [slot for slot in self.default_map if not self.fields.get(slot)]

        if empty_slots:
            try:
                top_joints = joints.find_skinned_or_top_joints(namespace='')
                if top_joints:
                    joint_map = self.guess_joint_map_from_root(top_joints[0])
                    for slot in empty_slots:
                        if slot in joint_map:
                            detected_joint = joint_map[slot].get("joint")
                            if detected_joint and cmds.objExists(detected_joint):
                                self.fields[slot] = detected_joint
                                self.update_button_color(slot)
            except Exception as e:
                print(f"[Warning] Auto-population failed: {e}")

        # Synchronize default_map with fields
        for slot in self.default_map:
            self.default_map[slot]["joint"] = self.fields.get(slot, "")

        # Synchronize face mapping
        for key_path, list_widget in self.face_lists.items():
            items = [list_widget.item(i).text().split(" ")[0] for i in range(list_widget.count())]
            data = self.default_face_map
            for key in key_path[:-1]:
                data = data[key]
            last_key = key_path[-1]
            if isinstance(data[last_key], list):
                data[last_key] = items
            else:
                data[last_key] = items[0] if items else ""

        new_map = create_rig.hik_map_to_rig_args(self.default_map, self.default_face_map)

        if refresh_details:
            self._refresh_all_module_details()

        return True

    def set_t_pose_from_mapping(self):
        """Set the mapped deformation skeleton to T-pose as one undoable action."""
        if self.host_mode != "maya":
            self._notify_operation(
                "Set T-Pose", "Setting the deformation skeleton T-pose requires Maya.", "warning"
            )
            return None

        reload_rig_function_stack()
        self.create_rig_mapping()
        mapped_joints = [
            value.get("joint")
            for value in self.default_map.values()
            if isinstance(value, dict) and value.get("joint")
            and cmds.objExists(value.get("joint"))
        ]
        if not mapped_joints:
            self._notify_operation(
                "Set T-Pose",
                "No valid mapped joints were found. Create or auto-detect the rig mapping first.",
                "warning",
            )
            return None

        try:
            setup_hik.validate_t_pose_channels(self.default_map)
        except Exception as exc:
            self._notify_operation(
                "Set T-Pose Blocked",
                str(exc),
                "error",
            )
            return None

        cmds.undoInfo(openChunk=True, chunkName="Set T-Pose")
        try:
            result = setup_hik.set_t_pose(joint_map=self.default_map)
        except Exception as exc:
            traceback.print_exc()
            cmds.undoInfo(closeChunk=True)
            cmds.undo()
            self._notify_operation(
                "Set T-Pose Failed",
                "The skeleton was restored.\n\n{0}".format(exc),
                "error",
            )
            return None
        cmds.undoInfo(closeChunk=True)

        if (result or {}).get("skipped"):
            self._notify_operation(
                "Set T-Pose Complete",
                "The mapped skeleton already matches the stored T-pose. No joint transforms were changed.",
                "success",
            )
            return result

        leg_report = dict((result or {}).get("legs") or {})
        side_count = len(leg_report.get("sides") or {})
        rfl_report = dict((result or {}).get("rfl_snap") or {})
        snapped_sides = sum(
            len(report.get("snapped_sides") or [])
            for report in rfl_report.get("reports") or []
        )
        rotated_count = len(leg_report.get("rotated_joints") or [])
        translates_preserved = bool(leg_report.get("translation_preserved", False))
        message = (
            "T-pose applied to the current mapping.\n"
            "Leg sides aligned: {0}.\n"
            "Leg joints rotated: {1}.\n"
            "Deformation translations preserved: {2}.\n"
            "Reverse-foot sides snapped: {3}."
        ).format(side_count, rotated_count, translates_preserved, snapped_sides)
        if rfl_report.get("error"):
            message += "\n\nRFL warning: {0}".format(rfl_report["error"])
        self._notify_operation("Set T-Pose Complete", message, "success")
        return result

    def build_full_rig(self):
        build_started = time.perf_counter()
        build_revision = reload_rig_function_stack(force=True)
        print("[HIK UI] Full Build reloaded rig stack: {}".format(build_revision))
        self.create_rig_mapping(refresh_details=False)
        repaired_slots = create_rig.repair_preserved_extension_body_mapping(
            self.default_map
        )
        for slot, joint in repaired_slots.items():
            self.fields[slot] = joint
            self.update_button_color(slot)
        if repaired_slots:
            print(
                "[HIK UI] Restored standard mappings excluded from preserved "
                "extensions: {}".format(repaired_slots)
            )

        # Reset session overrides.
        self._session_parent_override = None
        self._use_override_for_all = False

        # Suppress repeated metadata discrepancy dialogs while individual
        # modules build. Missing saved references are collected and reported
        # once in the final summary.
        self._defer_module_discrepancy_warnings = True
        self._pending_module_discrepancies.clear()

        still_empty = [slot for slot in self.default_map if not self.fields.get(slot)]
        if still_empty:
            msg = (
                    "The following HumanIK slots are still unmapped:\n"
                    + ", ".join(still_empty)
                    + "\n\nDo you want to proceed and build the rig anyway?"
            )
            res = cmds.confirmDialog(
                title="Unmapped Slots Notice",
                message=msg,
                button=["Proceed", "Cancel"],
                defaultButton="Proceed",
                cancelButton="Cancel"
            )
            if res == "Cancel":
                self._defer_module_discrepancy_warnings = False
                self._pending_module_discrepancies.clear()
                return

        all_modules = [
            "Root / Origin",
            "Pelvis & Hips",
            "Spine",
            "Left Clavicle",
            "Right Clavicle",
            "Neck",
            "Head",
            "Left Arm",
            "Right Arm",
            "Left Leg",
            "Right Leg",
            "Brows (Left)",
            "Brows (Right)",
            "Eyes Aim",
            "Eyelids (Left)",
            "Eyelids (Right)",
            "Mouth & Lips",
            "Tongue",
            "Teeth",
            "Other Face Joints"
        ]

        # Force eyelids to build last.
        eyelid_modules = ["Eyelids (Left)", "Eyelids (Right)"]
        all_modules = [m for m in all_modules if m not in eyelid_modules]
        all_modules.extend(eyelid_modules)

        face_modules = {
            "Brows (Left)",
            "Brows (Right)",
            "Eyes Aim",
            "Eyelids (Left)",
            "Eyelids (Right)",
            "Mouth & Lips",
            "Tongue",
            "Teeth",
            "Other Face Joints",
        }

        cmds.undoInfo(openChunk=True, chunkName="Build Full Rig")
        built_modules = []
        skipped_modules = []
        build_error = None
        build_traceback = ""
        success_summary = ""

        try:
            # Full-rig construction always normalizes the deformation skeleton
            # first.  setup_hik.set_t_pose is idempotent, so a skeleton that is
            # already in the recorded T-pose is left byte-for-byte unchanged.
            setup_hik.set_t_pose(joint_map=self.default_map)

            for module in all_modules:
                if module in face_modules:
                    mapped_joints = self._get_face_module_joints(module)
                else:
                    mapped_joints = self._get_module_joints(module)

                existing_joints = [
                    joint for joint in mapped_joints
                    if joint and cmds.objExists(joint)
                ]

                # Every module should be skipped when none of its mapped joints
                # exist. This includes optional face modules.
                if not existing_joints:
                    skipped_modules.append(module)
                    continue

                if module in face_modules:
                    def built_ctrl_for_joint(joint_name, fallback):
                        joint_name = str(joint_name or "")
                        if joint_name:
                            base = joint_name.split("|")[-1].split(":")[-1]
                            candidate = base + "_ctrl"
                            if cmds.objExists(candidate):
                                return candidate
                        return fallback if cmds.objExists(fallback) else None

                    head_parent = built_ctrl_for_joint(
                        self.fields.get("Head"), "head1_ctrl"
                    )
                    jaw_joint = (
                        (self.default_face_map.get("Jaw") or {}).get("joint")
                        or self.fields.get("Jaw")
                        or "jaw"
                    )
                    jaw_parent = built_ctrl_for_joint(jaw_joint, "jaw_ctrl")
                    parent_override = head_parent
                    if module == "Tongue":
                        parent_override = jaw_parent or head_parent
                    elif module in {"Eyelids (Left)", "Eyelids (Right)"}:
                        eye_key = "LeftEye" if module.endswith("(Left)") else "RightEye"
                        eye_joint = (self.default_face_map.get(eye_key) or {}).get("joint")
                        parent_override = built_ctrl_for_joint(eye_joint, "") or head_parent

                    self.create_face_module_setup(
                        module,
                        silent=True,
                        parent_override=parent_override,
                        jaw_ctrl_override=jaw_parent,
                        jaw_joint_override=jaw_joint,
                    )
                else:
                    self.create_body_module_setup(module, silent=True)

                built_modules.append(module)

            # Recreate all spaces and composite spaces once at the end.
            for side in ("l", "r"):
                create_rig.create_arm_space_switches(side)
                create_rig.create_leg_space_switches(side)

            create_rig.delete_unused_scaffold_nodes()
            self.store_all_face_connections(silent=True)
            create_rig.restore_all_control_cv_positions()
            dynamic_restore = create_rig.rebuild_dynamic_rig_modules()
            create_rig.record_rig_owned_nodes()
            extension_restore = create_rig.restore_post_build_extensions()
            create_rig.hide_post_build_face_nodes()
            for ikh in cmds.ls(type="ikHandle") or []:
                try:
                    cmds.setAttr(f"{ikh}.visibility", 0)
                except Exception:
                    pass

            if cmds.objExists("Do_Not_Touch"):
                cmds.setAttr("Do_Not_Touch.visibility", 0)

            summary = (
                    f"Full Rig Build Completed!\n\n"
                    f"Built Modules ({len(built_modules)}):\n"
                    + (", ".join(built_modules) if built_modules else "None")
            )

            if skipped_modules:
                summary += (
                        f"\n\nSkipped Modules (no mapped joints in scene) "
                        f"({len(skipped_modules)}):\n"
                        + ", ".join(skipped_modules)
                )

            if dynamic_restore.get("rebuilt"):
                summary += (
                    "\n\nRebuilt Additional Modules:\n"
                    + ", ".join(dynamic_restore["rebuilt"])
                )
            if dynamic_restore.get("failed"):
                summary += (
                    "\n\nAdditional Modules Needing Attention:\n"
                    + ", ".join(
                        item.get("module_id", "Unnamed")
                        for item in dynamic_restore["failed"]
                    )
                )

            restored_extensions = extension_restore.get("roots", [])
            if restored_extensions:
                summary += (
                    "\n\nRestored Post-Build Systems ({0}):\n{1}".format(
                        len(restored_extensions), ", ".join(restored_extensions)
                    )
                )

            if self._pending_module_discrepancies:
                summary += (
                    f"\n\nIgnored Missing Saved Joint References "
                    f"({len(self._pending_module_discrepancies)}):\n"
                )
                summary += "\n".join(
                    f"• [{module_name}] {joint_name}"
                    for module_name, joint_name
                    in sorted(self._pending_module_discrepancies)
                )

            success_summary = summary

        except Exception as e:
            build_error = e
            build_traceback = traceback.format_exc()
            print(build_traceback)

        finally:
            cmds.undoInfo(closeChunk=True)

            if build_error is not None:
                try:
                    # Silent module builds deliberately avoid nested chunks, so
                    # one undo restores the exact pre-build scene.
                    cmds.undo()
                except Exception as undo_error:
                    cmds.warning(f"Failed to roll back the incomplete full rig: {undo_error}")

            # Failed/partial Maya operations can leave evaluation or the global
            # IK solver disabled. Always restore both before returning control
            # to the animator.
            dag.enable_evaluation()
            try:
                cmds.ikSystem(edit=True, solve=True)
            except Exception:
                pass

            # Keep warning deferral enabled for the final metadata refresh so it
            # cannot reopen the same discrepancy dialog after the summary.
            updates_enabled = self.updatesEnabled()
            if updates_enabled:
                self.setUpdatesEnabled(False)
            try:
                # This method already performs one complete detail refresh.
                self._load_module_metadata_from_scene()
            finally:
                if updates_enabled:
                    self.setUpdatesEnabled(True)

            self._defer_module_discrepancy_warnings = False
            self._pending_module_discrepancies.clear()

        print(
            "[HIK UI][timing] Full rig ready in {0:.3f}s".format(
                time.perf_counter() - build_started
            )
        )
        if build_error is not None:
            self._notify_operation(
                "Full Rig Build Failed",
                f"Full Rig build failed and was rolled back:\n{build_error}\n\n"
                + "\n".join(build_traceback.strip().splitlines()[-4:]),
                "error",
            )
            cmds.warning(f"Failed to create full rig: {build_error}")
            return None

        # Never create a completion popup here. Even a non-modal QMessageBox
        # has a native show/close lifecycle that can make Maya flush a large
        # post-build DAG twice. Keep the detailed result as a tooltip and show
        # a compact, persistent status directly beside the build action.
        self._notify_operation("Full Rig Built", success_summary, "success")
        return built_modules

    def remove_full_rig(self):
        reload_rig_function_stack()
        dag.disable_evaluation()

        # Synchronize default_map with fields
        for slot in self.default_map:
            self.default_map[slot]["joint"] = self.fields.get(slot, "")
        # Synchronize face mapping
        for key_path, list_widget in self.face_lists.items():
            items = [list_widget.item(i).text().split(" ")[0] for i in range(list_widget.count())]
            data = self.default_face_map
            for key in key_path[:-1]:
                data = data[key]
            last_key = key_path[-1]
            if isinstance(data[last_key], list):
                data[last_key] = items
            else:
                data[last_key] = items[0] if items else ""

        cmds.undoInfo(openChunk=True, chunkName="Remove Full Rig")
        try:

            create_rig.store_all_control_cv_positions()
            create_rig.remove_full_rig(self.default_map, self.default_face_map)
            self._notify_operation("Full Rig Removed", "Full Rig removed successfully!", "success")
        except Exception as e:
            self._notify_operation("Remove Full Rig Failed", f"Failed to remove full rig:\n{e}", "error")
            cmds.warning(f"Failed to remove full rig: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

    def _sync_export_joint_maps(self):
        for slot in self.default_map:
            self.default_map[slot]["joint"] = self.fields.get(slot, "")
        for key_path, list_widget in self.face_lists.items():
            items = [list_widget.item(i).text().split(" ")[0] for i in range(list_widget.count())]
            data = self.default_face_map
            for key in key_path[:-1]:
                data = data[key]
            final_key = key_path[-1]
            data[final_key] = items if isinstance(data[final_key], list) else (items[0] if items else "")
        return self.default_map, self.default_face_map

    def send_skeletal_mesh_to_unreal(self):
        """Run the Maya-to-Unreal workflow from the persistent Mesh tab definition."""
        if self.host_mode != "maya" or unreal_skeletal_export is None:
            self._notify_operation("Unreal Export Unavailable", "This workflow requires Maya.", "warning")
            return
        try:
            settings = self._mesh_export_settings()
        except ValueError as exc:
            self._notify_operation("Incomplete Mesh Export Definition", str(exc), "warning")
            return
        clean_name = settings["rig_name"]
        existing_mesh_path = settings["existing_skeletal_mesh_path"]
        export_mesh_name = (
            existing_mesh_path.rstrip("/").rsplit("/", 1)[-1]
            if existing_mesh_path else "SKM_" + clean_name
        )

        body_map, face_map = self._sync_export_joint_maps()
        dag.disable_evaluation()
        cmds.undoInfo(openChunk=True, chunkName="Remove Rig and Send to Unreal")
        try:
            export_result = unreal_skeletal_export.remove_rig_restore_bind_pose_and_export(
                body_map,
                face_map,
                clean_name,
                settings["output_directory"],
                meshes=settings["meshes"],
                skeletal_mesh_name=export_mesh_name,
            )
            import_result = usp.run_import_skeletal_mesh_fbx(
                export_result["fbx_path"],
                clean_name,
                settings["destination_path"],
                settings["existing_skeletal_mesh_path"],
                settings["skeleton_mode"],
                settings["existing_skeleton_path"],
                settings["create_physics_asset"],
            )
            warnings = list(import_result.get("warnings") or []) if isinstance(import_result, dict) else []
            message = (
                "FBX: {0}\nSkeletal Mesh: {1}\nSkeleton: {2}\nPhysics Asset: {3}".format(
                    export_result["fbx_path"],
                    import_result.get("skeletal_mesh_path", ""),
                    import_result.get("skeleton_path", ""),
                    import_result.get("physics_asset_path", "") or "Not created",
                )
            )
            if warnings:
                message += "\n\nWarnings:\n" + "\n".join(warnings)
            self._notify_operation("Skeletal Mesh Sent to Unreal", message, "warning" if warnings else "success")
        except Exception as exc:
            self._notify_operation(
                "Skeletal Mesh Export Failed",
                "The Maya scene may already have its control rig removed. Undo in Maya if needed.\n\n{}".format(exc),
                "error",
            )
            cmds.warning("Skeletal Mesh export/import failed: {}".format(exc))
        finally:
            cmds.undoInfo(closeChunk=True)
            dag.enable_evaluation()
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def auto_detect_face_joints(self, key_path, list_widget):
        slot = key_path[0]
        all_joints = cmds.ls(type="joint") or []
        detected = []

        if slot in ["LeftBrow", "RightBrow"]:
            prefix = "l_brow" if "Left" in slot else "r_brow"
            detected = [j for j in all_joints if j.lower().startswith(prefix)]
            detected.sort()
        elif slot in ["LeftEyelid", "RightEyelid"]:
            prefix = "l_eyelid" if "Left" in slot else "r_eyelid"
            if len(key_path) > 2 and key_path[1] in ["inner", "outer"]:
                target_suffix = "inner_eyelidTip" if key_path[1] == "inner" else "outer_eyelidTip"
                detected = [j for j in all_joints if prefix in j.lower() and target_suffix in j]
            else:
                detected = [j for j in all_joints if prefix in j.lower() and "fol" not in j.lower()]
                detected.sort()
        elif slot == "LipChain":
            detected = [j for j in all_joints if "lip" in j.lower() or "corner" in j.lower()]
            detected.sort()
        elif slot == "Jaw":
            detected = [j for j in all_joints if "jaw" in j.lower()]
        elif slot == "TongueChain":
            detected = [j for j in all_joints if "tongue" in j.lower()]
            detected.sort()
        elif slot in ["UpperTeeth", "LowerTeeth"]:
            term = "upper_teeth" if "Upper" in slot else "lower_teeth"
            detected = [j for j in all_joints if term in j.lower()]
        elif slot in ["LeftEye", "RightEye"]:
            term = "l_eye" if "Left" in slot else "r_eye"
            detected = [j for j in all_joints if j.lower() == term or j.lower() == term + "1"]
        elif slot == "NoseRoot":
            detected = [j for j in all_joints if "nose_root" in j.lower()]

        if detected:
            self._update_list_widget(list_widget, detected)

            # Sync the mapping dict immediately so detail panels can reflect changes
            self.create_rig_mapping()
            self._refresh_all_module_details()

    def create_single_control(self):
        sel = cmds.ls(sl=True, type="joint")
        if not sel:
            cmds.warning("Please select at least one joint to create controls for.")
            return

        parent = self.ctrl_parent_field.text().strip() or None
        shape = self.ctrl_shape_combo.currentText().lower()
        if shape == "double arrow":
            shape = "arrow"

        try:
            module_id = self.ctrl_module_name_field.text().strip()
            if not module_id:
                module_id = "Controls - {}".format(sel[0].split("|")[-1])
            spec = create_rig.dynamic_module_spec(
                sel,
                parent=parent,
                control_shape=shape,
                sub_ctrls=False,
                keep_constraint=True,
            )
            create_rig.register_dynamic_rig_module(
                module_id, "controls", spec, build_now=True
            )
            self._notify_operation(
                "Controls Created",
                "Control module '{}' created and registered for rebuild.".format(module_id),
                "success",
            )
        except Exception as e:
            self._notify_operation("Control Creation Failed", f"Failed to create control(s):\n{e}", "error")
            cmds.warning(f"Failed to create control(s): {e}")

    def create_additional_limb_module(self, module_type):
        """Build and register an arbitrary additional arm or leg chain."""
        reload_rig_function_stack()
        joints = cmds.ls(selection=True, type="joint", long=True) or []
        module_id = self.extra_limb_name_field.text().strip()
        parent = self.extra_limb_parent_field.text().strip() or None
        required = 3 if module_type == "arm" else 4
        maximum = 3 if module_type == "arm" else 5
        if not module_id:
            cmds.warning("Enter a unique module name for the additional limb.")
            return
        if len(joints) < required or len(joints) > maximum:
            cmds.warning(
                "Select {} ordered joints for an arm or 4–5 for a leg; received {}.".format(
                    required if module_type == "arm" else "4–5", len(joints)
                )
            )
            return
        for parent_joint, child_joint in zip(joints[:-1], joints[1:]):
            actual = cmds.listRelatives(child_joint, parent=True, type="joint", fullPath=True) or []
            expected = (cmds.ls(parent_joint, long=True) or [parent_joint])[0]
            if not actual or actual[0] != expected:
                cmds.warning("Selected limb joints must be a direct parent-to-child chain.")
                return
        if not parent or not cmds.objExists(parent):
            cmds.warning("Choose an existing parent control for the additional limb.")
            return
        try:
            spec = create_rig.dynamic_module_spec(joints, parent=parent)
            create_rig.register_dynamic_rig_module(
                module_id, module_type, spec, build_now=True
            )
            self._notify_operation(
                "Additional Limb Created",
                "{} module '{}' created and registered for full-rig rebuild.".format(
                    module_type.title(), module_id
                ),
                "success",
            )
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation(
                "Additional Limb Failed",
                "Failed to create '{}':\n{}".format(module_id, exc),
                "error",
            )

    def export_skin_weights(self):
        meshes = cmds.ls(selection=True) or []
        if not meshes:
            self._notify_operation(
                "Export Skin Weights",
                "Select one or more skinned meshes to export.",
                "warning",
            )
            return
        export_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Export Skin Weights", "C:/temp/weights"
        )
        if export_dir:
            return skinning_utils.export_skin_weights(meshes, export_dir)

    def import_skin_weights(self):
        reload_rig_function_stack()
        meshes = cmds.ls(selection=True) or []
        if not meshes:
            self._notify_operation(
                "Import Skin Weights",
                "Select one or more meshes to receive the saved skin weights.",
                "warning",
            )
            return None
        import_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Import Skin Weights", "C:/temp/weights"
        )
        if not import_dir:
            return None
        result = skinning_utils.import_skin_weights(
            meshes,
            import_dir,
            missing_influence_resolver=self._confirm_skin_influence_renames,
        )
        if self.host_mode == "maya" and isinstance(result, dict):
            imported = list(result.get("imported_meshes") or [])
            influence_reports = list(result.get("influence_reports") or [])
            failure_reports = list(result.get("failure_reports") or [])
            preserved_count = sum(
                len(report.get("preserved_influences") or [])
                for report in influence_reports
            )
            added_count = sum(
                len(report.get("added_influences") or [])
                for report in influence_reports
            )
            mapped_count = sum(
                len(report.get("mapped_influences") or [])
                for report in influence_reports
            )
            renamed_count = sum(
                len(report.get("renamed_influences") or [])
                for report in influence_reports
            ) + sum(
                len(report.get("renamed_influences") or [])
                for report in failure_reports
            )
            summary = (
                "Imported skin weights for {0} mesh(es).\n"
                "Existing bind influences preserved: {1}.\n"
                "Missing imported influences added: {2}.\n"
                "Saved influence names remapped: {3}.\n"
                "Confirmed scene joint renames: {4}."
            ).format(
                len(imported), preserved_count, added_count,
                mapped_count, renamed_count,
            )
            if failure_reports:
                details = []
                for report in failure_reports:
                    if report.get("reason") != "missing_influences":
                        details.append(
                            "{}: {}".format(
                                report.get("mesh", "Unknown mesh"),
                                report.get("message", "Import failed."),
                            )
                        )
                        continue
                    details.append(
                        "{} was skipped; these required influences were not "
                        "found:".format(report.get("mesh", "Unknown mesh"))
                    )
                    renamed = report.get("renamed_influences") or []
                    if renamed:
                        details.append(
                            "  Confirmed suggested renames were applied. Resolve "
                            "the remaining influences below, then import again."
                        )
                    suggestions = report.get("similar_influences") or {}
                    for influence in report.get("missing_influences") or []:
                        matches = suggestions.get(influence) or []
                        match_text = (
                            " Possible match{}: {}".format(
                                "es" if len(matches) != 1 else "",
                                ", ".join(matches),
                            )
                            if matches else " No similar scene joint was found."
                        )
                        details.append("  - {}.{}".format(influence, match_text))
                message = "{}\nSkipped meshes: {}.\n{}".format(
                    summary,
                    len(failure_reports),
                    "\n".join(details),
                )
                title = (
                    "Skin Import Partially Complete"
                    if imported else "Skin Import Failed"
                )
                severity = "warning" if imported else "error"
                self._notify_operation(title, message, severity)
            else:
                message = (
                    "{}\nReverse-foot joints were left unchanged; they snap after T-pose."
                ).format(summary)
                self._notify_operation("Skin Import Complete", message, "success")
        return result

    def _confirm_skin_influence_renames(
            self, mesh, proposals, unresolved, ambiguous):
        """Ask before applying safe, formatting-only influence renames."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Rename Suggested Skin Influences?")
        dialog.setModal(True)
        dialog.resize(650, 480)

        layout = QtWidgets.QVBoxLayout(dialog)
        heading = QtWidgets.QLabel(
            "The skin-weight map for '{}' has high-confidence joint-name "
            "matches. Review them before Maya renames any scene joints."
            .format(mesh)
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        lines = ["Current scene joint  →  Required weight-map name"]
        for saved_name, scene_joint in proposals.items():
            lines.append(
                "{}  →  {}".format(
                    skinning_utils._influence_node_name(scene_joint),
                    skinning_utils._influence_leaf_name(saved_name),
                )
            )
        if unresolved:
            lines.append("")
            lines.append("No safe automatic match:")
            lines.extend(
                "  - {}".format(skinning_utils._influence_leaf_name(name))
                for name in unresolved
            )
        if ambiguous:
            lines.append("")
            lines.append("Ambiguous matches (will not be renamed):")
            for saved_name, matches in ambiguous.items():
                lines.append(
                    "  - {}: {}".format(
                        skinning_utils._influence_leaf_name(saved_name),
                        ", ".join(
                            skinning_utils._influence_node_name(match)
                            for match in matches
                        ),
                    )
                )

        mapping_view = QtWidgets.QPlainTextEdit(dialog)
        mapping_view.setReadOnly(True)
        mapping_view.setPlainText("\n".join(lines))
        mapping_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(mapping_view, 1)

        warning = QtWidgets.QLabel(
            "Only the listed high-confidence matches will be renamed. "
            "Left/right sides are never crossed. If unresolved items remain, "
            "the mesh import will stay skipped until they are fixed and the "
            "import is run again."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QtWidgets.QDialogButtonBox(dialog)
        rename_button = buttons.addButton(
            "Rename Suggested Joints",
            QtWidgets.QDialogButtonBox.AcceptRole,
        )
        rename_button.setDefault(True)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        result = dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()
        return result == QtWidgets.QDialog.Accepted

    def auto_hammer_weight_spikes(self):
        """Repair isolated whole-mesh weight outliers without softening valid gradients."""
        reload_rig_function_stack()
        try:
            result = skinning_utils.smooth_skin_weights_spatial_from_selection(
                radius=self.spatial_smooth_radius.value(),
                iterations=self.spatial_smooth_iterations.value(),
                strength=self.spatial_smooth_strength.value(),
                max_influences=self.spatial_smooth_max_influences.value(),
                normal_angle=self.spatial_smooth_normal_angle.value(),
                max_neighbors=self.spatial_smooth_max_neighbors.value(),
                cross_region_share=self.spatial_smooth_cross_region.value(),
                entire_mesh=True,
                automatic_radius=True,
                artifact_only=True,
            )
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation(
                "Surface-Spatial Skin Smoothing",
                "Failed to smooth skin weights:\n{}".format(exc),
                "error",
            )
            return

        if result.get("cancelled") and not result.get("iterations"):
            cmds.warning("Surface-spatial skin smoothing was cancelled before weights were changed.")
            return
        if not result.get("changedVertices") or result.get("maxDelta", 0.0) <= 1.0e-6:
            self._notify_operation(
                "Surface-Spatial Skin Smoothing",
                (
                    "No isolated weight spikes were found among {inspectedVertices} vertices.\n\n"
                    "Coherent gradients and boundary vertices are intentionally preserved."
                ).format(**result),
                "warning",
            )
            return
        self._notify_operation(
            "Surface-Spatial Skin Smoothing",
            (
                "Hammered {changedVertices} detected weight spikes on {mesh}.\n"
                "Detected from weights: {weightArtifactVertices}; posed deformation: {deformationArtifactVertices}.\n"
                "Inspected {inspectedVertices} vertices without changing coherent gradients.\n"
                "Completed {iterations} iteration(s) with radius {radius:g}.\n"
                "Largest weight change: {maxDelta:.4f}."
                "{radius_note}"
            ).format(
                radius_note=(
                    "\nAutomatic surface radius: {radius:g}.".format(**result)
                    if result.get("automaticRadius") else (
                        "\nRadius auto-expanded from {requestedRadius:g} to {radius:g} with a blending margin.".format(**result)
                        if result.get("autoExpandedRadius") else ""
                    )
                ),
                **result
            ),
            "success",
        )

    def smooth_skin_weights_spatially(self):
        """Smooth a selected mesh, or restrict diffusion to selected vertices."""
        reload_rig_function_stack()
        try:
            result = skinning_utils.smooth_skin_weights_spatial_from_selection(
                radius=self.spatial_smooth_radius.value(),
                iterations=self.spatial_smooth_iterations.value(),
                strength=self.spatial_smooth_strength.value(),
                max_influences=self.spatial_smooth_max_influences.value(),
                normal_angle=self.spatial_smooth_normal_angle.value(),
                max_neighbors=self.spatial_smooth_max_neighbors.value(),
                cross_region_share=self.spatial_smooth_cross_region.value(),
                entire_mesh=False,
                automatic_radius=True,
                artifact_only=False,
            )
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation(
                "Smooth Skin Weights",
                "Failed to smooth skin weights:\n{}".format(exc),
                "error",
            )
            return

        if result.get("cancelled") and not result.get("iterations"):
            cmds.warning("Skin-weight smoothing was cancelled before weights were changed.")
            return
        if not result.get("changedVertices") or result.get("maxDelta", 0.0) <= 1.0e-6:
            self._notify_operation(
                "Smooth Skin Weights",
                "No skin weights changed on the requested vertices.",
                "warning",
            )
            return
        self._notify_operation(
            "Smooth Skin Weights",
            (
                "Smoothed {changedVertices} of {vertices} requested vertices on {mesh}.\n"
                "Completed {iterations} iteration(s) with automatic radius {radius:g}.\n"
                "Largest weight change: {maxDelta:.4f}."
            ).format(**result),
            "success",
        )

    def activate_spatial_skin_smooth_brush(self):
        reload_rig_function_stack()
        try:
            result = skinning_utils.activate_surface_spatial_smooth_brush(
                radius=self.spatial_smooth_radius.value(),
                iterations=max(1, min(4, self.spatial_smooth_iterations.value())),
                strength=self.spatial_smooth_strength.value(),
                max_influences=self.spatial_smooth_max_influences.value(),
                normal_angle=self.spatial_smooth_normal_angle.value(),
                max_neighbors=self.spatial_smooth_max_neighbors.value(),
                cross_region_share=self.spatial_smooth_cross_region.value(),
            )
            cmds.warning("Surface Spatial Smooth Brush active on {}. Press Q or Exit Brush when done.".format(
                result.get("mesh")))
        except Exception as exc:
            traceback.print_exc()
            self._notify_operation(
                "Surface Smooth Brush",
                "Could not activate the brush:\n{}".format(exc),
                "error",
            )

    def deactivate_spatial_skin_smooth_brush(self):
        if MAYA_HOST:
            skinning_utils.deactivate_surface_spatial_smooth_brush()

    def transfer_skin_weights_from_selection(self):
        selection = cmds.ls(selection=True) or []
        if len(selection) < 2:
            self._notify_operation(
                "Transfer Skin Weights",
                "Select one or more skinned source meshes, then select the target mesh last.",
                "warning",
            )
            return

        result = skinning_utils.transfer_skin_weights_from_selection()
        if not result:
            self._notify_operation(
                "Transfer Skin Weights",
                "Skin weight transfer failed. Check the Script Editor for details.",
                "warning",
            )
            return

        self._notify_operation(
            "Transfer Skin Weights",
            (
                f"Transferred skin weights to '{selection[-1]}'.\n"
                f"Created skinCluster: {result.get('skinCluster')}"
            ),
            "success",
        )

    def create_surface_rig_with_drivers(self):
        reload_rig_function_stack()
        sel = cmds.ls(sl=True, type="joint")
        if not sel:
            cmds.warning("Please select a joint chain to create a surface rig.")
            return

        parent = self.surface_parent_field.text().strip() or None
        loft_name = self.surf_name_field.text().strip() or "eyelid"
        region = self.surf_region_combo.currentText()
        side = "c" if region == "center_eyelid" else self.surf_side_combo.currentText()
        offset = self.surf_offset_spin.value()

        indices_text = self.surf_indices_field.text().strip()
        driver_indices = None
        if indices_text:
            try:
                driver_indices = [int(x.strip()) for x in indices_text.split(",") if x.strip()]
            except ValueError:
                cmds.warning("Invalid driver indices format. Using None.")

        try:
            module_id = self.surf_module_name_field.text().strip()
            if not module_id:
                module_id = "Surface Rig - {}".format(loft_name)
            spec = create_rig.dynamic_module_spec(
                sel,
                parent=parent,
                loft_name=loft_name,
                offset=offset,
                driver_follicle_indices=driver_indices,
                side=side,
                region=region,
            )
            create_rig.register_dynamic_rig_module(
                module_id, "surface_rig", spec, build_now=True
            )
            self._notify_operation(
                "Surface Rig Created",
                "Surface module '{}' created and registered for rebuild.".format(module_id),
                "success",
            )
        except Exception as e:
            traceback.print_exc()
            self._notify_operation("Surface Rig Failed", f"Failed to create surface rig:\n{e}", "error")
            cmds.warning(f"Failed to create surface rig: {e}")

    def sort_joints_by_bounding_box(self, joints):
        if not joints:
            return []
        if len(joints) <= 1:
            return joints

        positions = []
        for j in joints:
            try:
                positions.append(cmds.xform(j, q=True, ws=True, t=True))
            except:
                positions.append([0.0, 0.0, 0.0])

        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]

        var_x = max(xs) - min(xs)
        var_y = max(ys) - min(ys)
        var_z = max(zs) - min(zs)

        if var_x >= var_y and var_x >= var_z:
            axis_idx = 0
        elif var_y >= var_x and var_y >= var_z:
            axis_idx = 1
        else:
            axis_idx = 2

        sorted_pairs = sorted(zip(joints, positions), key=lambda x: x[1][axis_idx])
        return [p[0] for p in sorted_pairs]

    def auto_detect_indices(self):
        sel = cmds.ls(sl=True, type="joint")
        region = self.surf_region_combo.currentText()
        if not sel:
            if region == "eyelid":
                self.surf_indices_field.setText("0, 9, 6, 3, 12, 15, 18, 20")
            elif region == "center_eyelid":
                self.surf_indices_field.setText("0, 2, 5, 8, 10, 12, 15, 18")
            elif region == "mouth":
                self.surf_indices_field.setText("0, 2, 5, 8, 10, 12, 15, 18")
            elif region == "brow":
                self.surf_indices_field.setText("0, 1, 2, 3, 4")
            else:
                self.surf_indices_field.setText("0, 1, 2")
            return

        sorted_joints = self.sort_joints_by_bounding_box(sel)
        N = len(sorted_joints)

        if N <= 2:
            self.surf_indices_field.setText(", ".join(map(str, range(N))))
            return

        indices = set()
        indices.add(0)
        indices.add(N - 1)

        for idx, jnt in enumerate(sorted_joints):
            name_lower = jnt.lower()
            if any(k in name_lower for k in ["corner", "inner", "outer", "mid", "center", "main"]):
                indices.add(idx)

        if region == "eyelid":
            target_count = 8
            if N == 21:
                self.surf_indices_field.setText("0, 9, 6, 3, 12, 15, 18, 20")
                return
        elif region == "center_eyelid":
            target_count = 8
            if N == 20:
                self.surf_indices_field.setText("0, 2, 5, 8, 10, 12, 15, 18")
                return
        elif region == "mouth":
            target_count = 8
            if N == 20:
                self.surf_indices_field.setText("0, 2, 5, 8, 10, 12, 15, 18")
                return
        elif region == "brow":
            target_count = 5
        else:
            target_count = 3

        if len(indices) < target_count:
            even_indices = [int(round(i * (N - 1) / (target_count - 1))) for i in range(target_count)]
            for val in even_indices:
                indices.add(val)

        final_indices = sorted(list(indices))
        self.surf_indices_field.setText(", ".join(map(str, final_indices)))

    def _pick_parent(self, field):
        sel = cmds.ls(sl=True)
        if sel:
            field.setText(sel[0])

    def make_selector_callback(self, slot):
        def callback():
            self.current_slot = slot
            self.selector_field.setText(self.fields.get(slot, ""))
            self.single_selector_widget.show()
            self.selector_button.setText("Pick " + slot)

        return callback

    def update_button_color(self, slot):
        if slot not in self.buttons:
            return
        joint_data = self.fields.get(slot, "")
        joint = joint_data["joint"] if isinstance(joint_data, dict) else joint_data

        if joint and cmds.objExists(joint):
            self.buttons[slot].setStyleSheet("background-color: green;")
        else:
            self.buttons[slot].setStyleSheet("background-color: lightcoral;")

    def get_opposite_slot(self, slot):
        if slot.startswith("Left"):
            return slot.replace("Left", "Right", 1)
        elif slot.startswith("Right"):
            return slot.replace("Right", "Left", 1)
        return None

    def mirror_joint_name(self, name: str) -> str:
        # 1. Suffix-based swaps (_l / _r / _L / _R at END only)
        if re.search(r'_[lL]$', name):
            suffix = name[-1]
            opp = 'r' if suffix == 'l' else 'R' if suffix == 'L' else suffix
            return name[:-2] + '_' + opp
        if re.search(r'_[rR]$', name):
            suffix = name[-1]
            opp = 'l' if suffix == 'r' else 'L' if suffix == 'R' else suffix
            return name[:-2] + '_' + opp

        # 2. Prefix-based swaps (L_ / R_ / l_ / r_ at START only)
        if re.match(r'^[lL]_', name):
            prefix = name[0]
            opp = 'r' if prefix == 'l' else 'R' if prefix == 'L' else prefix
            return opp + '_' + name[2:]
        if re.match(r'^[rR]_', name):
            prefix = name[0]
            opp = 'l' if prefix == 'r' else 'L' if prefix == 'R' else prefix
            return opp + '_' + name[2:]

        # 3. Whole-word swaps (Left / Right)
        word_swaps = {
            r'\bLeft\b': 'Right',
            r'\bRight\b': 'Left',
            r'\bleft\b': 'right',
            r'\bright\b': 'left',
        }

        for pattern, replacement in word_swaps.items():
            if re.search(pattern, name):
                return re.sub(pattern, replacement, name)

        return name

    def pick_selected_joint(self):
        sel = cmds.ls(selection=True, type="joint")
        if sel and self.current_slot:
            self.selector_field.setText(sel[0])
            self.fields[self.current_slot] = sel[0]
            self.update_button_color(self.current_slot)
            opposite_slot = self.get_opposite_slot(self.current_slot)
            if opposite_slot and opposite_slot in self.fields:
                mirrored = self.mirror_joint_name(sel[0])
                if cmds.objExists(mirrored):
                    self.fields[opposite_slot] = mirrored
                    self.update_button_color(opposite_slot)
            self._refresh_all_module_details()

    def load_definition(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Joint Map", "", "JSON Files (*.json)")
        if path:
            with open(path, 'r') as f:
                data = json.load(f)
                for key in self.default_map:
                    # Load joint name only; keep index intact
                    joint_name = data.get(key).get("joint")
                    self.default_map[key]["joint"] = joint_name
                    self.fields[key] = joint_name
                    self.update_button_color(key)
            self._refresh_all_module_details()

    def save_definition(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Joint Map", "", "JSON Files (*.json)")
        if path:
            data = {key: self.default_map[key] for key in self.default_map}
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)

    def auto_detect(self):
        roots = joints.find_skinned_or_top_joints(namespace='') or []
        if not roots:
            self._notify_operation(
                "Auto Detect Bones",
                "No skinned or top-level joint hierarchy was found in the scene.",
                "warning",
            )
            return
        root_joint = roots[0]
        joint_map = self.guess_joint_map_from_root(root_joint)
        for slot in self.default_map:
            if slot in joint_map:
                joint_name = joint_map[slot].get("joint") or ""
                self.fields[slot] = joint_name
                button = self.buttons.get(slot)
                if button:
                    button.setStyleSheet(
                        "background-color: green;" if joint_name
                        else "background-color: lightcoral;"
                    )
            self.default_map[slot]["joint"] = self.fields.get(slot, "")
        self._notify_operation(
            "Auto Detect Bones",
            "Mapped joints from {}. Module and connection details were left untouched.".format(
                root_joint
            ),
            "success",
        )

    def get_uproject(self, directory):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Unreal Project", directory,
                                                             "Unreal Project (*.uproject)")
        if file_name:
            return file_name.replace('\\', '/')
        return None

    def guess_joint_map_from_root(self, root_joint):
        result = setup_hik.guess_joint_map_from_root(root_joint, self.default_map)
        # Refresh the face map after assignment
        self.populate_default_face_map_from_scene()
        return result

    def create_hik_character(self):
        char_name = self.char_name.text()
        export_path = self.export_path.text()

        def is_valid_hik_slot(slot):
            # Exclude roll / twist / leaf / HipSwing slots entirely
            banned = ["Roll", "HipSwing"]
            return not any(b in slot for b in banned)

        joint_map = {
            slot: [self.fields.get(slot), self.default_map[slot].get("index")]
            for slot in self.default_map
            if self.fields.get(slot) and is_valid_hik_slot(slot)
        }

        if len(joint_map) < 5:
            cmds.warning("Not enough joints assigned to create a valid character.")
            return

        setup_hik.setup_hik_character(
            char_name,
            joint_map,
            export_path,
            self.namespace.text()
        )

        if self.unreal_checkbox.isChecked():
            uproject = self.get_uproject("C:/")
            if uproject:
                http_server_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(script_dir))),
                    "unreal_tools",
                    "http_server.py"
                ).replace('\\', '/')

                upd.add_unreal_startup_script(uproject, http_server_path)
                log_path = upd.get_latest_unreal_log(uproject)
                cmd_path = upd.get_unreal_cmd_exe(uproject)

                try:
                    skel_meshes = usp.run_get_skeletons(
                        uproject, log_path, cmd_path, "SkeletalMesh"
                    )
                except Exception as exc:
                    self._notify_operation("Unreal Asset Discovery Failed", str(exc), "error")
                    return
                if not skel_meshes:
                    self._notify_operation(
                        "No Skeletal Meshes",
                        "No SkeletalMesh assets were found under /Game in Unreal.",
                        "warning",
                    )
                    return

                self.popup = ControlRigPopup(skel_meshes, joint_map, uproject)
                self.popup.exec_()

    def store_all_face_connections(self, silent=False):
        self.create_rig_mapping(refresh_details=not silent)

        stored_modules = []
        for name in self._get_registered_module_ids():
            ctrls = create_rig.get_module_controls(name)
            if not ctrls:
                metadata = create_rig.load_module_metadata(name) or {}
                main_control = self._get_first_existing_ctrl(name, metadata)
                ctrls = [main_control] if main_control else []
            if not ctrls:
                continue

            stored_data = create_rig.store_rig_connections(ctrls, name)
            if any(stored_data.values()):
                stored_modules.append(name)

        if not silent:
            message = "Rig connections and space switches stored successfully!"
            if stored_modules:
                message += "\n\nStored data for:\n" + "\n".join([f"• {m}" for m in stored_modules])
            else:
                message += "\n(No active space switches or custom external connections were found in the scene)."

            self._notify_operation("Global Store", message, "success")

    def _get_module_joints(self, module):
        if module == "Left Arm":
            return [self.fields.get("LeftArm"), self.fields.get("LeftForeArm"), self.fields.get("LeftHand")]
        elif module == "Right Arm":
            return [self.fields.get("RightArm"), self.fields.get("RightForeArm"), self.fields.get("RightHand")]
        elif module == "Left Clavicle":
            return [self.fields.get("LeftShoulder")]
        elif module == "Right Clavicle":
            return [self.fields.get("RightShoulder")]
        elif module == "Left Leg":
            return [self.fields.get("LeftUpLeg"), self.fields.get("LeftLeg"), self.fields.get("LeftFoot"),
                    self.fields.get("LeftToeBase")]
        elif module == "Right Leg":
            return [self.fields.get("RightUpLeg"), self.fields.get("RightLeg"), self.fields.get("RightFoot"),
                    self.fields.get("RightToeBase")]
        elif module == "Root / Origin":
            return [self.fields.get("Reference")]
        elif module == "Pelvis & Hips":
            return [self.fields.get("Hips"), self.fields.get("HipSwing")]
        elif module == "Spine":
            return [self.fields.get(f"Spine{i}" if i > 0 else "Spine") for i in range(4)]
        elif module == "Neck":
            return [self.fields.get(f"Neck{i}" if i > 0 else "Neck") for i in range(2)]
        elif module == "Head":
            return [self.fields.get("Head")]
        return []

    def _get_face_module_joints(self, module):
        dm = self.default_face_map
        if module == "Brows (Left)":
            return dm.get("LeftBrow", {}).get("joints", [])
        elif module == "Brows (Right)":
            return dm.get("RightBrow", {}).get("joints", [])
        elif module == "Eyes Aim":
            return [dm.get("LeftEye", {}).get("joint"), dm.get("RightEye", {}).get("joint")]
        elif module == "Eyelids (Left)":
            return dm.get("LeftEyelid", {}).get("joints", [])
        elif module == "Eyelids (Right)":
            return dm.get("RightEyelid", {}).get("joints", [])
        elif module == "Mouth & Lips":
            return dm.get("LipChain", {}).get("joints", [])
        elif module == "Tongue":
            return dm.get("TongueChain", {}).get("joints", [])
        elif module == "Teeth":
            return [dm.get("UpperTeeth", {}).get("joint"), dm.get("LowerTeeth", {}).get("joint")]
        elif module == "Other Face Joints":
            return dm.get("OtherFaceJoints", {}).get("joints", [])
        return []

    def create_body_module_setup(self, module, silent=False):
        if not silent:
            reload_rig_function_stack()
        edit_info = self._module_detail_widgets.get(module)
        parent = None
        if edit_info and edit_info.get("parent_edit"):
            parent = edit_info["parent_edit"].text().strip() or None
        if not parent:
            parent = self.body_parent_field.text().strip() or None
        if module != "Root / Origin" and (not parent or not cmds.objExists(parent)):
            if self._use_override_for_all and self._session_parent_override and cmds.objExists(
                    self._session_parent_override):
                parent = self._session_parent_override
                if edit_info and edit_info.get("parent_edit"):
                    edit_info["parent_edit"].setText(parent)
            elif silent:
                # Silently fall back to body_parent_field, or None to let the module builder use its optimal defaults
                fallback = self.body_parent_field.text().strip()
                if fallback and cmds.objExists(fallback):
                    parent = fallback
                else:
                    parent = None
                if edit_info and edit_info.get("parent_edit") and parent:
                    edit_info["parent_edit"].setText(parent)
            else:
                msg_parent = f"'{parent}'" if parent else "None"
                msg = f"Parent control {msg_parent} for module '{module}' does not exist in the scene.\n\nPlease select the desired parent control in the viewport and click 'Assign & Build', or click 'Cancel'."
                while True:
                    dialog = ParentSelectionDialog(msg, parent=self)
                    res = dialog.exec_()
                    if res == QtWidgets.QDialog.Accepted:
                        sel = cmds.ls(sl=True)
                        if sel:
                            parent = sel[0]
                            if dialog.checkbox.isChecked():
                                self._session_parent_override = parent
                                self._use_override_for_all = True
                            if edit_info and edit_info.get("parent_edit"):
                                edit_info["parent_edit"].setText(parent)
                            break
                        else:
                            self._notify_operation(
                                "Parent Selection",
                                "Nothing selected. Please select a node in the scene.",
                                "warning",
                            )
                    else:
                        return

        if not silent:
            self.create_rig_mapping()
        else:
            # Batch and TC-host builds skip the full mapping refresh, but the
            # fields are the user's current assignments. Do not pass stale
            # template rows to the module builder.
            for slot, row in self.default_map.items():
                row["joint"] = self.fields.get(slot, "")
        owns_undo_chunk = not silent
        if owns_undo_chunk:
            cmds.undoInfo(openChunk=True, chunkName=f"Build Body Module: {module}")
        try:
            module_func = None
            module_args = []

            if module == "Left Arm":
                module_func = create_rig.rig_arm_module
                module_args = ("l", self.default_map, parent)
            elif module == "Right Arm":
                module_func = create_rig.rig_arm_module
                module_args = ("r", self.default_map, parent)
            elif module == "Left Clavicle":
                module_func = create_rig.rig_clavicle_module
                module_args = ("l", self.default_map, parent)
            elif module == "Right Clavicle":
                module_func = create_rig.rig_clavicle_module
                module_args = ("r", self.default_map, parent)
            elif module == "Left Leg":
                module_func = create_rig.rig_leg_module
                module_args = ("l", self.default_map, parent)
            elif module == "Right Leg":
                module_func = create_rig.rig_leg_module
                module_args = ("r", self.default_map, parent)
            elif module == "Root / Origin":
                module_func = create_rig.rig_root_module
                module_args = (self.default_map,)
            elif module == "Pelvis & Hips":
                module_func = create_rig.rig_pelvis_module
                module_args = (self.default_map, parent)
            elif module == "Spine":
                module_func = create_rig.rig_spine_module
                module_args = (self.default_map, parent)
            elif module == "Neck":
                module_func = create_rig.rig_neck_module
                module_args = (self.default_map, parent)
            elif module == "Head":
                module_func = create_rig.rig_head_module
                module_args = (self.default_map, self.default_face_map, parent)

            if module_func is None:
                raise RuntimeError(f"Unknown body module '{module}'")

            module_func(*module_args)

            # Batch builds recreate all limb spaces once after every module.
            if not silent:
                if module == "Left Arm":
                    create_rig.create_arm_space_switches("l")
                elif module == "Right Arm":
                    create_rig.create_arm_space_switches("r")
                elif module == "Left Leg":
                    create_rig.create_leg_space_switches("l")
                elif module == "Right Leg":
                    create_rig.create_leg_space_switches("r")
                elif module in ("Pelvis & Hips", "Root / Origin", "Spine", "Left Clavicle", "Right Clavicle"):
                    # Update existing limb spaces for an individually rebuilt core module.
                    for s in ("l", "r"):
                        create_rig.create_arm_space_switches(s)
                        create_rig.create_leg_space_switches(s)

            identity_result = create_rig.restore_module_rebuild_identity(module)
            restored = create_rig.restore_rig_connections(module)

            # The full build stores connections once after all modules exist.
            if not silent:
                self.store_all_face_connections(silent=False)

            if not silent:
                msg = f"Body Module '{module}' created successfully!"
                if restored > 0:
                    msg += f"\nRestored {restored} connections/space switches."
                renamed_count = len(identity_result.get("renamed", {}))
                shape_count = identity_result.get("shapes", 0)
                if renamed_count or shape_count:
                    msg += f"\nRestored {renamed_count} control name(s) and {shape_count} control shape(s)."
                self._notify_operation("Body Module Created", msg, "success")
            if not silent:
                create_rig.restore_all_control_cv_positions()
                create_rig.hide_post_build_face_nodes()
                for ikh in cmds.ls(type="ikHandle") or []:
                    try:
                        cmds.setAttr(f"{ikh}.visibility", 0)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[ERROR] create_body_module_setup failed for module={module} parent={parent}: {e}")
            traceback.print_exc()
            if silent:
                raise
            self._notify_operation(
                "Body Module Creation Failed",
                f"Failed to create body module setup:\n{e}",
                "error",
            )
        finally:
            if owns_undo_chunk:
                cmds.undoInfo(closeChunk=True)
            if not silent:
                self._load_module_metadata_from_scene()

    def remove_body_module_setup(self, module):
        reload_rig_function_stack()
        dag.disable_evaluation()
        self.create_rig_mapping()
        create_rig.store_all_control_cv_positions()
        cmds.undoInfo(openChunk=True, chunkName=f"Remove Body Module: {module}")
        try:
            deleted_count = 0
            if module == "Left Arm":
                deleted_count = create_rig.remove_arm_module("l", self.default_map)
            elif module == "Right Arm":
                deleted_count = create_rig.remove_arm_module("r", self.default_map)
            elif module == "Left Clavicle":
                deleted_count = create_rig.remove_clavicle_module("l", self.default_map)
            elif module == "Right Clavicle":
                deleted_count = create_rig.remove_clavicle_module("r", self.default_map)
            elif module == "Left Leg":
                deleted_count = create_rig.remove_leg_module("l", self.default_map)
            elif module == "Right Leg":
                deleted_count = create_rig.remove_leg_module("r", self.default_map)
            elif module == "Root / Origin":
                deleted_count = create_rig.remove_root_module(self.default_map)
            elif module == "Pelvis & Hips":
                deleted_count = create_rig.remove_pelvis_module(self.default_map)
            elif module == "Spine":
                deleted_count = create_rig.remove_spine_module(self.default_map)
            elif module == "Neck":
                deleted_count = create_rig.remove_neck_module(self.default_map)
            elif module == "Head":
                deleted_count = create_rig.remove_head_module(self.default_map)

            # Cleanup orphaned main/temp nodes
            create_rig.delete_unused_scaffold_nodes()

            self._notify_operation(
                "Body Module Removed",
                f"Body Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.",
                "success",
            )
        except Exception as e:
            self._notify_operation(
                "Body Module Removal Failed",
                f"Failed to remove body module setup:\n{e}",
                "error",
            )
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

    def create_face_module_setup(
            self, module, silent=False, parent_override=None,
            jaw_ctrl_override=None, jaw_joint_override=None):
        if not silent:
            reload_rig_function_stack()
        edit_info = self._module_detail_widgets.get(module)
        parent = parent_override
        if not parent and edit_info and edit_info.get("parent_edit"):
            parent = edit_info["parent_edit"].text().strip() or None
        if not parent:
            parent = self.module_parent_field.text().strip() or None
        if not parent or not cmds.objExists(parent):
            if self._use_override_for_all and self._session_parent_override and cmds.objExists(
                    self._session_parent_override):
                parent = self._session_parent_override
                if edit_info and edit_info.get("parent_edit"):
                    edit_info["parent_edit"].setText(parent)
            elif silent:
                # Silently fall back to module_parent_field, or None to let the module builder use its optimal defaults
                fallback = self.module_parent_field.text().strip()
                if fallback and cmds.objExists(fallback):
                    parent = fallback
                else:
                    parent = None
                if edit_info and edit_info.get("parent_edit") and parent:
                    edit_info["parent_edit"].setText(parent)
            else:
                msg_parent = f"'{parent}'" if parent else "None"
                msg = f"Parent control {msg_parent} for module '{module}' does not exist in the scene.\n\nPlease select the desired parent control in the viewport and click 'Assign & Build', or click 'Cancel'."
                while True:
                    dialog = ParentSelectionDialog(msg, parent=self)
                    res = dialog.exec_()
                    if res == QtWidgets.QDialog.Accepted:
                        sel = cmds.ls(sl=True)
                        if sel:
                            parent = sel[0]
                            if dialog.checkbox.isChecked():
                                self._session_parent_override = parent
                                self._use_override_for_all = True
                            if edit_info and edit_info.get("parent_edit"):
                                edit_info["parent_edit"].setText(parent)
                            break
                        else:
                            self._notify_operation(
                                "Parent Selection",
                                "Nothing selected. Please select a node in the scene.",
                                "warning",
                            )
                    else:
                        return

        jaw_ctrl = jaw_ctrl_override
        if not jaw_ctrl and edit_info and edit_info.get("jaw_ctrl_edit"):
            jaw_ctrl = edit_info["jaw_ctrl_edit"].text().strip() or None
        if not jaw_ctrl:
            jaw_ctrl = self.module_jaw_ctrl_field.text().strip() or None

        jaw_jnt = jaw_joint_override
        if not jaw_jnt and edit_info and edit_info.get("jaw_jnt_edit"):
            jaw_jnt = edit_info["jaw_jnt_edit"].text().strip() or None
        if not jaw_jnt:
            jaw_jnt = self.module_jaw_jnt_field.text().strip() or None

        if not silent:
            self.create_rig_mapping()

        # Remove missing scene joints from this module's active mapping before
        # the builder or metadata store sees them.
        face_joints = [
            joint for joint in self._get_face_module_joints(module)
            if joint and cmds.objExists(joint)
        ]

        if not face_joints:
            if not silent:
                self._notify_operation(
                    "Face Module Skipped",
                    (
                        f"Face Module '{module}' was not built because none of "
                        "its mapped joints exist in the current scene."
                    ),
                    "warning",
                )
            return

        build_error = None
        build_traceback = ""
        owns_undo_chunk = not silent
        if owns_undo_chunk:
            cmds.undoInfo(openChunk=True, chunkName=f"Build Face Module: {module}")
        try:
            if module == "Brows (Left)":
                create_rig.rig_brows_module("l", self.default_face_map, parent)
            elif module == "Brows (Right)":
                create_rig.rig_brows_module("r", self.default_face_map, parent)
            elif module == "Eyes Aim":
                create_rig.rig_eyes_module(self.default_face_map, parent)
            elif module == "Eyelids (Left)":
                create_rig.rig_eyelids_module("l", self.default_face_map, parent)
            elif module == "Eyelids (Right)":
                create_rig.rig_eyelids_module("r", self.default_face_map, parent)
            elif module == "Mouth & Lips":
                create_rig.rig_mouth_module(self.default_face_map, parent, jaw_ctrl)
            elif module == "Tongue":
                create_rig.rig_tongue_module(self.default_face_map, parent)
            elif module == "Teeth":
                create_rig.rig_teeth_module(self.default_face_map, parent, jaw_ctrl)
            elif module == "Other Face Joints":
                create_rig.rig_other_face_module(self.default_face_map, parent, jaw_ctrl, jaw_jnt)

            identity_result = create_rig.restore_module_rebuild_identity(module)
            restored = create_rig.restore_rig_connections(module)

            # Save only joints that actually exist in the current scene.
            create_rig.save_module_metadata(module, {
                "parent": parent or "",
                "jaw_ctrl": jaw_ctrl or "",
                "jaw_jnt": jaw_jnt or "",
                "joints": face_joints,
                "built": True
            })

            # The full build stores connections once after all modules exist.
            if not silent:
                self.store_all_face_connections(silent=False)

            if not silent:
                msg = f"Face Module '{module}' created successfully!"
                if restored > 0:
                    msg += f"\nRestored {restored} connections/space switches."
                renamed_count = len(identity_result.get("renamed", {}))
                shape_count = identity_result.get("shapes", 0)
                if renamed_count or shape_count:
                    msg += f"\nRestored {renamed_count} control name(s) and {shape_count} control shape(s)."
                self._notify_operation("Face Module Created", msg, "success")
            if not silent:
                create_rig.restore_all_control_cv_positions()
                create_rig.hide_post_build_face_nodes()
        except Exception as e:
            build_traceback = traceback.format_exc()
            print(build_traceback)
            if silent:
                raise
            build_error = e
        finally:
            if owns_undo_chunk:
                cmds.undoInfo(closeChunk=True)

        if build_error is not None:
            try:
                # The entire module build is one undo chunk. Roll it back so a
                # retry cannot collide with a half-built mouth surface/control
                # hierarchy left behind by the failed attempt.
                chunk_name = f"Build Face Module: {module}"
                undo_name = cmds.undoInfo(query=True, undoName=True)
                if undo_name == chunk_name:
                    cmds.undo()
                else:
                    cmds.warning(
                        "Partial face module rollback was skipped because the current undo item is {!r}.".format(
                            undo_name
                        )
                    )
            except Exception as undo_error:
                cmds.warning(
                    "Failed to roll back partial face module '{}': {}".format(
                        module,
                        undo_error,
                    )
                )
            self._notify_operation(
                "Face Module Creation Failed",
                (
                    f"Failed to create face module setup:\n{build_error}\n\n"
                    f"Rig source: {getattr(create_rig_core, '__file__', 'unknown')}\n"
                    f"Revision: {getattr(create_rig_core, 'RIG_BUILD_REVISION', 'unknown')}\n\n"
                    + "\n".join(build_traceback.strip().splitlines()[-4:])
                ),
                "error",
            )

        if not silent:
            try:
                self._load_module_metadata_from_scene()
            except Exception as refresh_error:
                cmds.warning("Failed to refresh face module details: {}".format(refresh_error))

    def remove_face_module_setup(self, module):
        reload_rig_function_stack()
        dag.disable_evaluation()
        self.create_rig_mapping()
        create_rig.store_all_control_cv_positions()
        cmds.undoInfo(openChunk=True, chunkName=f"Remove Face Module: {module}")
        try:
            deleted_count = 0
            if module == "Brows (Left)":
                deleted_count = create_rig.remove_brows_module("l", self.default_face_map)
            elif module == "Brows (Right)":
                deleted_count = create_rig.remove_brows_module("r", self.default_face_map)
            elif module == "Eyelids (Left)":
                deleted_count = create_rig.remove_eyelids_module("l", self.default_face_map)
            elif module == "Eyelids (Right)":
                deleted_count = create_rig.remove_eyelids_module("r", self.default_face_map)
            elif module == "Mouth & Lips":
                deleted_count = create_rig.remove_mouth_module(self.default_face_map)
            elif module == "Eyes Aim":
                deleted_count = create_rig.remove_eyes_module(self.default_face_map)
            elif module == "Tongue":
                deleted_count = create_rig.remove_tongue_module(self.default_face_map)
            elif module == "Teeth":
                deleted_count = create_rig.remove_teeth_module(self.default_face_map)
            elif module == "Other Face Joints":
                deleted_count = create_rig.remove_other_face_module(self.default_face_map)

            # Clear face module metadata
            create_rig.clear_module_metadata(module)

            # Cleanup orphaned main/temp nodes
            create_rig.delete_unused_scaffold_nodes()

            self._notify_operation(
                "Face Module Removed",
                f"Face Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.",
                "success",
            )
        except Exception as e:
            self._notify_operation(
                "Face Module Removal Failed",
                f"Failed to remove face module setup:\n{e}",
                "error",
            )
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

    def load_settings_from_selection(self):
        sel = cmds.ls(sl=True)
        if not sel:
            self._notify_operation(
                "Load Settings",
                "Please select a control or joint in the scene first.",
                "warning",
            )
            return

        node = sel[0]
        node_lower = node.lower()
        is_body = any(t in node_lower for t in
                      ["upperarm", "lowerarm", "hand", "clavicle", "thigh", "knee", "ankle", "toe", "foot", "leg",
                       "arm"])

        parent_ctrl = ""
        jaw_ctrl = ""
        jaw_jnt = ""

        ctrl = None
        if node.endswith("_ctrl"):
            ctrl = node
        elif cmds.objExists(node + "_ctrl"):
            ctrl = node + "_ctrl"
        elif cmds.objectType(node) == "joint":
            if cmds.objExists(node + "_ctrl"):
                ctrl = node + "_ctrl"
            elif node.startswith("l_") or node.startswith("r_"):
                side = node[0]
                part = node[2:]
                for suffix in ["_fk_ctrl", "_ik_ctrl", "_ctrl"]:
                    if cmds.objExists(f"{side}_{part}{suffix}"):
                        ctrl = f"{side}_{part}{suffix}"
                        break

        if ctrl:
            pad = ctrl + "_pad"
            if not cmds.objExists(pad):
                pad = ctrl + "_main_ctrl_pad"
            if not cmds.objExists(pad):
                parents = cmds.listRelatives(ctrl, p=True)
                if parents:
                    pad = parents[0]

            if cmds.objExists(pad):
                p = cmds.listRelatives(pad, p=True)
                if p:
                    parent_ctrl = p[0]
                    # Strip pad suffixes to get the clean control node itself
                    for suffix in ["_ctrl_sdk_pad", "_sdk_pad", "_ctrl_pad", "_pad"]:
                        if parent_ctrl.endswith(suffix):
                            parent_ctrl = parent_ctrl[:-len(suffix)]
                            if suffix in ["_ctrl_sdk_pad", "_ctrl_pad"]:
                                parent_ctrl += "_ctrl"
                            break

        for j_c in ["jaw_ctrl", "mandible_ctrl"]:
            if cmds.objExists(j_c):
                jaw_ctrl = j_c
                break

        self.create_rig_mapping()
        jaw_jnt = self.fields.get("Jaw", {}).get("joint") or self.default_face_map.get("Jaw", {}).get("joint") or "jaw"
        if not cmds.objExists(jaw_jnt):
            jaw_jnt = "jaw"

        if parent_ctrl:
            if is_body:
                self.body_parent_field.setText(parent_ctrl)
            else:
                self.module_parent_field.setText(parent_ctrl)

        if not is_body:
            if jaw_ctrl:
                self.module_jaw_ctrl_field.setText(jaw_ctrl)
            if jaw_jnt and cmds.objExists(jaw_jnt):
                self.module_jaw_jnt_field.setText(jaw_jnt)

        msg = f"Loaded settings from selection (detected as {'Body' if is_body else 'Face'}):"
        if parent_ctrl: msg += f"\n• Parent: {parent_ctrl}"
        if not is_body:
            if jaw_ctrl: msg += f"\n• Jaw Control: {jaw_ctrl}"
            if jaw_jnt: msg += f"\n• Jaw Joint: {jaw_jnt}"
        self._notify_operation("Settings Loaded", msg, "success")
        self._refresh_all_module_details()

    # ------------------------------------------------------------------
    # Module Detail Widget System — live scene queries per row
    # ------------------------------------------------------------------

    # Primary control candidates per module (tried in order; first existing wins)
    _MODULE_CTRL_CANDIDATES = {
        "Root / Origin": ["origin_ctrl"],
        "Pelvis & Hips": ["pelvis_ctrl", "hipswing_ctrl"],
        "Spine": ["spine1_ctrl", "spine3_ctrl", "spine5_ctrl"],
        "Left Clavicle": ["l_clavicle_ctrl"],
        "Right Clavicle": ["r_clavicle_ctrl"],
        "Neck": ["neck1_ctrl", "neck2_ctrl"],
        "Head": ["head1_ctrl"],
        "Left Arm": ["l_upperarm_fk_ctrl", "l_hand_switch_ctrl"],
        "Right Arm": ["r_upperarm_fk_ctrl", "r_hand_switch_ctrl"],
        "Left Leg": ["l_thigh_fk_ctrl", "l_ankle_switch_ctrl"],
        "Right Leg": ["r_thigh_fk_ctrl", "r_ankle_switch_ctrl"],
        "Brows (Left)": ["l_brow_main_ctrl", "l_brow1_ctrl"],
        "Brows (Right)": ["r_brow_main_ctrl", "r_brow1_ctrl"],
        "Eyelids (Left)": ["l_eyelid_main_ctrl", "l_upper_eyelid1_ctrl"],
        "Eyelids (Right)": ["r_eyelid_main_ctrl", "r_upper_eyelid1_ctrl"],
        "Mouth & Lips": ["c_upper_lip_main_ctrl", "l_lip_corner1_main_ctrl"],
        "Eyes Aim": ["eye_aim_ctrl", "l_eye_aim_ctrl"],
        "Tongue": ["tongue1_ctrl"],
        "Teeth": ["upper_teeth_ctrl"],
        "Other Face Joints": [],
    }

    def _create_joint_slots_group(self, title, slots, module_id):
        group = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QFormLayout(group)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        for label, slot_key in slots:
            row = QtWidgets.QHBoxLayout()
            edit = QtWidgets.QLineEdit()
            edit.setReadOnly(True)
            edit.setText(self.fields.get(slot_key, ""))

            # Register in self._slot_edit_widgets
            self._slot_edit_widgets[slot_key] = edit

            btn = QtWidgets.QPushButton("⌖")
            btn.setFixedSize(20, 20)
            btn.setToolTip(f"Map selected joint to {label}")
            btn.clicked.connect(lambda checked=False, sk=slot_key, e=edit: self._assign_joint_to_slot(sk, e))
            row.addWidget(edit)
            row.addWidget(btn)
            layout.addRow(label + ":", row)
        return group

    def _assign_joint_to_slot(self, slot_key, line_edit):
        sel = cmds.ls(sl=True, type="joint")
        if sel:
            joint_name = sel[0]
            line_edit.setText(joint_name)
            self.fields[slot_key] = joint_name
            self.update_button_color(slot_key)

            opposite_slot = self.get_opposite_slot(slot_key)
            if opposite_slot and opposite_slot in self.fields:
                mirrored = self.mirror_joint_name(joint_name)
                if cmds.objExists(mirrored):
                    self.fields[opposite_slot] = mirrored
                    self._update_edit_view_slot_ui(opposite_slot, mirrored)
                    self.update_button_color(opposite_slot)

            self.create_rig_mapping()
        else:
            cmds.warning("Please select a joint in the scene first.")

    def _update_edit_view_slot_ui(self, slot_key, joint_name):
        widget = self._slot_edit_widgets.get(slot_key)
        if widget:
            widget.setText(joint_name)

    def _create_space_switch_edit_row(self, ctrl_name, default_targets, module_id):
        row = QtWidgets.QHBoxLayout()
        edit = QtWidgets.QLineEdit()

        meta = create_rig.load_module_metadata(module_id)
        custom_sw = meta.get("custom_space_switches", {})
        targets = custom_sw.get(ctrl_name, default_targets)
        edit.setText(", ".join(targets))

        btn = QtWidgets.QPushButton("⌖")
        btn.setFixedSize(20, 20)
        btn.setToolTip("Set targets from selection")

        def assign_targets():
            sel = cmds.ls(sl=True)
            if sel:
                edit.setText(", ".join(sel))
                self._save_custom_space_switches(module_id, ctrl_name, sel)
            else:
                cmds.warning("Nothing selected in viewport.")

        btn.clicked.connect(assign_targets)
        edit.textChanged.connect(lambda text: self._save_custom_space_switches(module_id, ctrl_name,
                                                                               [t.strip() for t in text.split(",") if
                                                                                t.strip()]))

        row.addWidget(edit)
        row.addWidget(btn)
        return row

    def _save_custom_space_switches(self, module_id, ctrl_name, targets):
        meta = create_rig.load_module_metadata(module_id)
        if "custom_space_switches" not in meta:
            meta["custom_space_switches"] = {}
        meta["custom_space_switches"][ctrl_name] = targets
        create_rig.save_module_metadata(module_id, meta)

    def _create_face_list_block(self, label, key_path):
        box = QtWidgets.QGroupBox(label)
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(5, 5, 5, 5)
        v.setSpacing(3)

        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        data = self.default_face_map
        try:
            for key in key_path:
                data = data[key]

            if isinstance(data, dict):
                if "joints" in data:
                    items = data["joints"]
                elif "joint" in data and data["joint"]:
                    items = [data["joint"]]
                else:
                    items = []
            elif isinstance(data, list):
                items = data
            elif isinstance(data, str):
                items = [data] if data else []
            else:
                items = []

            lst.setMinimumHeight(80)
            lst.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self._update_list_widget(lst, items)
        except Exception as e:
            print(f"[ERROR] {label} - Error populating list: {e}")

        assign_btn = QtWidgets.QPushButton("Assign Selected")
        assign_btn.setStyleSheet("height: 18px; font-size: 8pt;")
        auto_btn = QtWidgets.QPushButton("Auto Detect")
        auto_btn.setStyleSheet("height: 18px; font-size: 8pt;")

        assign_btn.clicked.connect(lambda checked=False, l=lst: self.assign_face_from_selection(l))
        auto_btn.clicked.connect(
            lambda checked=False, kp=key_path, l=lst: self.auto_detect_face_joints(kp, l)
        )

        v.addWidget(lst)
        v.addWidget(assign_btn)
        v.addWidget(auto_btn)

        self.face_lists[key_path] = lst
        return box

    def _make_module_detail_widget(self, module_id, status_lbl):
        """Create a collapsible detail widget for a module grid row."""
        container = QtWidgets.QFrame()
        container.setStyleSheet("QFrame { background-color: #2b2b2b; border: 1px solid #1a1a1a; border-radius: 4px; }")
        container.setVisible(False)
        vl = QtWidgets.QVBoxLayout(container)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(5)

        # ------------------ 1. Built View (Read-Only) ------------------
        built_view = QtWidgets.QWidget()
        b_vl = QtWidgets.QVBoxLayout(built_view)
        b_vl.setContentsMargins(0, 0, 0, 0)
        b_vl.setSpacing(5)

        # Parent row
        parent_row = QtWidgets.QHBoxLayout()
        parent_hdr = QtWidgets.QLabel("Parent:")
        parent_hdr.setFixedWidth(50)
        parent_hdr.setStyleSheet("color: #999999; font-size: 8pt; border: none;")
        parent_row.addWidget(parent_hdr)

        parent_btn = QtWidgets.QPushButton("\u2014")
        parent_btn.setFlat(True)
        parent_btn.setEnabled(False)
        parent_btn.setStyleSheet("color: #777777; font-size: 8pt; border: none; padding: 0 2px; text-align: left;")
        parent_btn.setCursor(QtCore.Qt.PointingHandCursor)
        parent_btn.setToolTip("Displays the active parent control for this module. Click to select in Maya.")
        parent_row.addWidget(parent_btn)
        parent_row.addStretch()
        b_vl.addLayout(parent_row)

        # Face Jaw Control section
        jaw_ctrl_btn = None
        jaw_jnt_btn = None
        if module_id in ["Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"]:
            jaw_ctrl_row = QtWidgets.QHBoxLayout()
            jaw_ctrl_hdr = QtWidgets.QLabel("Jaw Ctrl:")
            jaw_ctrl_hdr.setFixedWidth(50)
            jaw_ctrl_hdr.setStyleSheet("color: #999999; font-size: 8pt; border: none;")
            jaw_ctrl_row.addWidget(jaw_ctrl_hdr)
            jaw_ctrl_btn = QtWidgets.QPushButton("\u2014")
            jaw_ctrl_btn.setFlat(True)
            jaw_ctrl_btn.setEnabled(False)
            jaw_ctrl_btn.setStyleSheet(
                "color: #777777; font-size: 8pt; border: none; padding: 0 2px; text-align: left;")
            jaw_ctrl_btn.setCursor(QtCore.Qt.PointingHandCursor)
            jaw_ctrl_row.addWidget(jaw_ctrl_btn)
            jaw_ctrl_row.addStretch()
            b_vl.addLayout(jaw_ctrl_row)

            jaw_jnt_row = QtWidgets.QHBoxLayout()
            jaw_jnt_hdr = QtWidgets.QLabel("Jaw Jnt:")
            jaw_jnt_hdr.setFixedWidth(50)
            jaw_jnt_hdr.setStyleSheet("color: #999999; font-size: 8pt; border: none;")
            jaw_jnt_row.addWidget(jaw_jnt_hdr)
            jaw_jnt_btn = QtWidgets.QPushButton("\u2014")
            jaw_jnt_btn.setFlat(True)
            jaw_jnt_btn.setEnabled(False)
            jaw_jnt_btn.setStyleSheet("color: #777777; font-size: 8pt; border: none; padding: 0 2px; text-align: left;")
            jaw_jnt_btn.setCursor(QtCore.Qt.PointingHandCursor)
            jaw_jnt_row.addWidget(jaw_jnt_btn)
            jaw_jnt_row.addStretch()
            b_vl.addLayout(jaw_jnt_row)

        # Mapped Joints row
        mapped_joints_row = QtWidgets.QHBoxLayout()
        mapped_joints_hdr = QtWidgets.QLabel("Mapped:")
        mapped_joints_hdr.setFixedWidth(50)
        mapped_joints_hdr.setStyleSheet("color: #999999; font-size: 8pt; border: none;")
        mapped_joints_row.addWidget(mapped_joints_hdr)

        mapped_joints_lbl = QtWidgets.QLabel("\u2014")
        mapped_joints_lbl.setStyleSheet("color: #99cc99; font-size: 8pt; border: none;")
        mapped_joints_lbl.setWordWrap(True)
        mapped_joints_row.addWidget(mapped_joints_lbl, 1)
        b_vl.addLayout(mapped_joints_row)

        # Spaces / connections row
        spaces_row = QtWidgets.QHBoxLayout()
        spaces_hdr = QtWidgets.QLabel("Spaces:")
        spaces_hdr.setFixedWidth(50)
        spaces_hdr.setStyleSheet("color: #999999; font-size: 8pt; border: none;")
        spaces_row.addWidget(spaces_hdr)

        spaces_container = QtWidgets.QWidget()
        spaces_layout = QtWidgets.QHBoxLayout(spaces_container)
        spaces_layout.setContentsMargins(0, 0, 0, 0)
        spaces_layout.setSpacing(3)
        spaces_row.addWidget(spaces_container)
        spaces_row.addStretch()
        b_vl.addLayout(spaces_row)

        vl.addWidget(built_view)

        # ------------------ 2. Edit View (Editable when unbuilt) ------------------
        edit_view = QtWidgets.QWidget()
        e_vl = QtWidgets.QVBoxLayout(edit_view)
        e_vl.setContentsMargins(0, 0, 0, 0)
        e_vl.setSpacing(8)

        body_list_names = ["Root / Origin", "Pelvis & Hips", "Spine", "Left Clavicle", "Right Clavicle", "Neck", "Head",
                           "Left Arm", "Right Arm", "Left Leg", "Right Leg"]
        is_body = module_id in body_list_names

        # Common Parameters (Parent Control, and Jaw settings if applicable)
        params_group = QtWidgets.QGroupBox("Parameters")
        params_layout = QtWidgets.QFormLayout(params_group)
        params_layout.setContentsMargins(5, 5, 5, 5)
        params_layout.setSpacing(3)

        parent_edit = QtWidgets.QLineEdit()
        parent_edit.setPlaceholderText("Parent control node name")
        parent_pick_btn = QtWidgets.QPushButton("Select")
        parent_pick_btn.setFixedSize(50, 20)
        parent_pick_btn.clicked.connect(lambda: self._pick_parent(parent_edit))
        parent_row_edit = QtWidgets.QHBoxLayout()
        parent_row_edit.addWidget(parent_edit)
        parent_row_edit.addWidget(parent_pick_btn)
        params_layout.addRow("Parent Control:", parent_row_edit)

        jaw_ctrl_edit = None
        jaw_jnt_edit = None
        if module_id in ["Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"]:
            jaw_ctrl_edit = QtWidgets.QLineEdit()
            jaw_ctrl_edit.setPlaceholderText("jaw_ctrl")
            jaw_ctrl_pick_btn = QtWidgets.QPushButton("Select")
            jaw_ctrl_pick_btn.setFixedSize(50, 20)
            jaw_ctrl_pick_btn.clicked.connect(lambda: self._pick_parent(jaw_ctrl_edit))
            jaw_ctrl_row_edit = QtWidgets.QHBoxLayout()
            jaw_ctrl_row_edit.addWidget(jaw_ctrl_edit)
            jaw_ctrl_row_edit.addWidget(jaw_ctrl_pick_btn)
            params_layout.addRow("Jaw Control:", jaw_ctrl_row_edit)

            if module_id == "Other Face Joints":
                jaw_jnt_edit = QtWidgets.QLineEdit()
                jaw_jnt_edit.setPlaceholderText("jaw")
                jaw_jnt_pick_btn = QtWidgets.QPushButton("Select")
                jaw_jnt_pick_btn.setFixedSize(50, 20)
                jaw_jnt_pick_btn.clicked.connect(lambda: self._pick_parent(jaw_jnt_edit))
                jaw_jnt_row_edit = QtWidgets.QHBoxLayout()
                jaw_jnt_row_edit.addWidget(jaw_jnt_edit)
                jaw_jnt_row_edit.addWidget(jaw_jnt_pick_btn)
                params_layout.addRow("Jaw Joint:", jaw_jnt_row_edit)

        e_vl.addWidget(params_group)

        # Slot Mappings layout (body) or Face list widget blocks (face)
        if is_body:
            # Create joint slot editors
            slots_hl = QtWidgets.QHBoxLayout()
            e_vl.addLayout(slots_hl)

            # Determine slots based on module
            if module_id == "Root / Origin":
                slots_hl.addWidget(
                    self._create_joint_slots_group("Main Joints", [("Reference", "Reference")], module_id))
            elif module_id == "Pelvis & Hips":
                slots_hl.addWidget(
                    self._create_joint_slots_group("Main Joints", [("Hips", "Hips"), ("Hip Swing", "HipSwing")],
                                                   module_id))
            elif module_id == "Spine":
                slots_hl.addWidget(self._create_joint_slots_group("Spine Chain", [
                    ("Spine", "Spine"), ("Spine 1", "Spine1"), ("Spine 2", "Spine2"), ("Spine 3", "Spine3")
                ], module_id))
            elif module_id == "Neck":
                slots_hl.addWidget(self._create_joint_slots_group("Neck Chain", [
                    ("Neck", "Neck"), ("Neck 1", "Neck1")
                ], module_id))
            elif module_id == "Head":
                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", [("Head", "Head")], module_id))
            elif module_id in ["Left Clavicle", "Right Clavicle"]:
                sp = "Left" if "Left" in module_id else "Right"
                slots_hl.addWidget(
                    self._create_joint_slots_group("Main Joints", [("Clavicle", f"{sp}Shoulder")], module_id))
            elif module_id in ["Left Arm", "Right Arm"]:
                side = "l" if "Left" in module_id else "r"
                sp = "Left" if "Left" in module_id else "Right"

                main_slots = [
                    ("Arm (Upper)", f"{sp}Arm"),
                    ("Forearm (Lower)", f"{sp}ForeArm"),
                    ("Hand", f"{sp}Hand")
                ]
                upper_twist = [
                    ("Arm Roll", f"{sp}ArmRoll"),
                    ("Leaf 1", f"Leaf{sp}ArmRoll1"),
                    ("Leaf 2", f"Leaf{sp}ArmRoll2"),
                    ("Leaf 3", f"Leaf{sp}ArmRoll3")
                ]
                lower_twist = [
                    ("Forearm Roll", f"{sp}ForeArmRoll"),
                    ("Leaf 1", f"Leaf{sp}ForearmRoll1"),
                    ("Leaf 2", f"Leaf{sp}ForearmRoll2"),
                    ("Leaf 3", f"Leaf{sp}ForearmRoll3")
                ]

                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", main_slots, module_id))
                slots_hl.addWidget(self._create_joint_slots_group("Twist Upper", upper_twist, module_id))
                slots_hl.addWidget(self._create_joint_slots_group("Twist Lower", lower_twist, module_id))

                # Add space switch targets box
                sw_group = QtWidgets.QGroupBox("Space Switch Options")
                sw_lay = QtWidgets.QFormLayout(sw_group)
                sw_lay.setContentsMargins(5, 5, 5, 5)
                sw_lay.setSpacing(3)

                sw_lay.addRow("PV Space Targets:", self._create_space_switch_edit_row(f"{side}_lowerarm_pv_ctrl",
                                                                                      ["pelvis_ctrl", "origin_ctrl",
                                                                                       f"{side}_clavicle_ctrl",
                                                                                       f"{side}_arm_pv_handClav_space"],
                                                                                      module_id))
                sw_lay.addRow("FK Space Targets:", self._create_space_switch_edit_row(f"{side}_upperarm_fk_ctrl",
                                                                                      [f"{side}_clavicle_ctrl",
                                                                                       "pelvis_ctrl", "origin_ctrl"],
                                                                                      module_id))
                sw_lay.addRow("IK Space Targets:", self._create_space_switch_edit_row(f"{side}_hand_ik_ctrl",
                                                                                      [f"{side}_clavicle_ctrl",
                                                                                       "spine5_Tip_ctrl", "pelvis_ctrl",
                                                                                       "origin_ctrl"], module_id))
                e_vl.addWidget(sw_group)

            elif module_id in ["Left Leg", "Right Leg"]:
                side = "l" if "Left" in module_id else "r"
                sp = "Left" if "Left" in module_id else "Right"

                main_slots = [
                    ("UpLeg", f"{sp}UpLeg"),
                    ("Leg", f"{sp}Leg"),
                    ("Foot", f"{sp}Foot"),
                    ("Toe Base", f"{sp}ToeBase")
                ]
                upper_twist = [
                    ("UpLeg Roll", f"{sp}UpLegRoll"),
                    ("Leaf 1", f"Leaf{sp}UpLegRoll1"),
                    ("Leaf 2", f"Leaf{sp}UpLegRoll2"),
                    ("Leaf 3", f"Leaf{sp}UpLegRoll3")
                ]
                lower_twist = [
                    ("Leg Roll", f"{sp}LegRoll"),
                    ("Leaf 1", f"Leaf{sp}LegRoll1"),
                    ("Leaf 2", f"Leaf{sp}LegRoll2")
                ]

                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", main_slots, module_id))
                slots_hl.addWidget(self._create_joint_slots_group("Twist Upper", upper_twist, module_id))
                slots_hl.addWidget(self._create_joint_slots_group("Twist Lower", lower_twist, module_id))

                # Add space switch targets box
                sw_group = QtWidgets.QGroupBox("Space Switch Options")
                sw_lay = QtWidgets.QFormLayout(sw_group)
                sw_lay.setContentsMargins(5, 5, 5, 5)
                sw_lay.setSpacing(3)

                sw_lay.addRow("PV Space Targets:", self._create_space_switch_edit_row(f"{side}_knee_pv_ctrl",
                                                                                      ["pelvis_ctrl",
                                                                                       f"{side}_ankle_ik_ctrl",
                                                                                       "origin_ctrl",
                                                                                       f"{side}_leg_pv_footHip_space"],
                                                                                      module_id))
                sw_lay.addRow("FK Space Targets:", self._create_space_switch_edit_row(f"{side}_thigh_fk_ctrl",
                                                                                      ["pelvis_ctrl", "origin_ctrl"],
                                                                                      module_id))
                sw_lay.addRow("IK Space Targets:", self._create_space_switch_edit_row(f"{side}_ankle_ik_ctrl",
                                                                                      ["pelvis_ctrl", "origin_ctrl"],
                                                                                      module_id))
                e_vl.addWidget(sw_group)
        else:
            # Face module assignment lists
            lists_hl = QtWidgets.QHBoxLayout()
            e_vl.addLayout(lists_hl)

            if module_id == "Brows (Left)":
                lists_hl.addWidget(self._create_face_list_block("Left Brow Joints", ("LeftBrow", "joints")))
            elif module_id == "Brows (Right)":
                lists_hl.addWidget(self._create_face_list_block("Right Brow Joints", ("RightBrow", "joints")))
            elif module_id == "Eyelids (Left)":
                lists_hl.addWidget(self._create_face_list_block("Left Inner Eyelid", ("LeftEyelid", "inner", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Left Outer Eyelid", ("LeftEyelid", "outer", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Left Eyelids (Ordered)", ("LeftEyelid", "joints")))
            elif module_id == "Eyelids (Right)":
                lists_hl.addWidget(
                    self._create_face_list_block("Right Inner Eyelid", ("RightEyelid", "inner", "joint")))
                lists_hl.addWidget(
                    self._create_face_list_block("Right Outer Eyelid", ("RightEyelid", "outer", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Right Eyelids (Ordered)", ("RightEyelid", "joints")))
            elif module_id == "Mouth & Lips":
                lists_hl.addWidget(self._create_face_list_block("Lip Joints (Ordered)", ("LipChain", "joints")))
            elif module_id == "Eyes Aim":
                lists_hl.addWidget(self._create_face_list_block("Left Eye", ("LeftEye", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Right Eye", ("RightEye", "joint")))
            elif module_id == "Tongue":
                lists_hl.addWidget(self._create_face_list_block("Tongue Joints", ("TongueChain", "joints")))
            elif module_id == "Teeth":
                lists_hl.addWidget(self._create_face_list_block("Upper Teeth", ("UpperTeeth", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Lower Teeth", ("LowerTeeth", "joint")))
            elif module_id == "Other Face Joints":
                lists_hl.addWidget(self._create_face_list_block("Other Face Joints", ("OtherFaceJoints", "joints")))

        vl.addWidget(edit_view)

        self._module_detail_widgets[module_id] = {
            "container": container,
            "built_view": built_view,
            "edit_view": edit_view,
            "status_lbl": status_lbl,
            "parent_btn": parent_btn,
            "jaw_ctrl_btn": jaw_ctrl_btn,
            "jaw_jnt_btn": jaw_jnt_btn,
            "mapped_joints_lbl": mapped_joints_lbl,
            "spaces_container": spaces_container,
            "parent_edit": parent_edit,
            "jaw_ctrl_edit": jaw_ctrl_edit,
            "jaw_jnt_edit": jaw_jnt_edit,
        }
        return container

    def _refresh_module_detail_widget(self, module_id):
        """Query live scene state and update the detail widget for one module."""
        module_widgets = self._module_detail_widgets.get(module_id)
        if not module_widgets:
            return

        metadata = create_rig.load_module_metadata(module_id) or {}
        was_built = metadata.get("built", False)

        main_control = self._get_first_existing_ctrl(module_id, metadata)
        module_exists = self._module_exists(module_id, was_built, main_control)

        self._set_module_view_state(module_widgets, module_exists)

        if not module_exists:
            self._refresh_module_edit_fields(module_id, module_widgets, metadata)

        self._refresh_create_remove_buttons(module_id, module_exists)
        self._refresh_module_status_label(module_widgets["status_lbl"], was_built, main_control)
        self._refresh_parent_button(module_widgets["parent_btn"], was_built, main_control)
        self._refresh_jaw_buttons(module_id, module_widgets, metadata, main_control)
        self._refresh_mapped_joints_label(module_id, module_widgets, metadata)
        self._refresh_spaces_and_connections(module_id, module_widgets, main_control)

    def _module_exists(self, module_id, was_built, main_control):
        if main_control:
            return True

        # Other Face Joints may not have one obvious main control.
        if module_id == "Other Face Joints" and was_built:
            return True

        return False

    def _set_module_view_state(self, module_widgets, module_exists):
        module_widgets["built_view"].setVisible(module_exists)
        module_widgets["edit_view"].setVisible(not module_exists)

    def _refresh_module_edit_fields(self, module_id, module_widgets, metadata):
        self._populate_fields_from_metadata(module_id, metadata)

        body_modules = {
            "Root / Origin",
            "Pelvis & Hips",
            "Spine",
            "Left Clavicle",
            "Right Clavicle",
            "Neck",
            "Head",
            "Left Arm",
            "Right Arm",
            "Left Leg",
            "Right Leg",
        }

        parent_edit = module_widgets.get("parent_edit")
        if parent_edit and not parent_edit.text().strip():
            default_parent = (
                self.body_parent_field.text().strip()
                if module_id in body_modules
                else self.module_parent_field.text().strip()
            )
            parent_edit.setText(default_parent)

        jaw_ctrl_edit = module_widgets.get("jaw_ctrl_edit")
        if jaw_ctrl_edit and not jaw_ctrl_edit.text().strip():
            jaw_ctrl_edit.setText(self.module_jaw_ctrl_field.text().strip())

        jaw_jnt_edit = module_widgets.get("jaw_jnt_edit")
        if jaw_jnt_edit and not jaw_jnt_edit.text().strip():
            jaw_jnt_edit.setText(self.module_jaw_jnt_field.text().strip())

        for slot_key, slot_widget in self._slot_edit_widgets.items():
            slot_widget.setText(self.fields.get(slot_key, ""))

    def _refresh_create_remove_buttons(self, module_id, module_exists):
        create_button = self.module_create_buttons.get(module_id)
        remove_button = self.module_remove_buttons.get(module_id)

        if create_button:
            create_button.setEnabled(not module_exists)

            if module_exists:
                create_button.setStyleSheet(
                    "background-color: #1e3a20; color: #557755; font-weight: bold; "
                    "border: 1px solid #335533;"
                )
                create_button.setToolTip("Module already exists in scene. Remove it first to rebuild.")
            else:
                create_button.setStyleSheet(
                    "background-color: #2e6930; color: white; font-weight: bold;"
                )
                create_button.setToolTip("Build this module setup.")

        if remove_button:
            remove_button.setEnabled(module_exists)

            if module_exists:
                remove_button.setStyleSheet(
                    "background-color: #7d2a2a; color: white; font-weight: bold;"
                )
                remove_button.setToolTip("Remove this module setup.")
            else:
                remove_button.setStyleSheet(
                    "background-color: #3a1e1e; color: #775555; font-weight: bold; "
                    "border: 1px solid #553333;"
                )
                remove_button.setToolTip("Module does not exist in scene — nothing to remove.")

    def _refresh_module_status_label(self, status_label, was_built, main_control):
        if main_control:
            status_label.setText("●")
            status_label.setStyleSheet("color: #55cc66; font-size: 10pt;")
        elif was_built:
            status_label.setText("⚠")
            status_label.setStyleSheet("color: #cc9933; font-size: 10pt;")
        else:
            status_label.setText("○")
            status_label.setStyleSheet("color: #555555; font-size: 10pt;")

    def _refresh_parent_button(self, parent_button, was_built, main_control):
        if not main_control:
            parent_button.setText("not in scene" if was_built else "—")
            parent_button.setEnabled(False)
            parent_button.setStyleSheet(
                "color: #666666; font-size: 8pt; font-style: italic; "
                "border: none; padding: 0 2px;"
            )
            return

        parent_node = self._get_ctrl_scene_parent(main_control)
        if not parent_node:
            parent_button.setText("—")
            parent_button.setEnabled(False)
            parent_button.setStyleSheet(
                "color: #777777; font-size: 8pt; border: none; padding: 0 2px;"
            )
            return

        exists = cmds.objExists(parent_node)
        color = "#6699cc" if exists else "#cc6666"

        parent_button.setText(parent_node)
        parent_button.setEnabled(True)
        parent_button.setStyleSheet(
            f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
            f"text-decoration: underline; text-align: left;"
        )

        self._safe_reconnect_button(parent_button, lambda: self._select_node(parent_node))

    def _refresh_jaw_buttons(self, module_id, module_widgets, metadata, main_control):
        face_modules = {"Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"}

        if not main_control or module_id not in face_modules:
            return

        self._set_scene_node_button(
            module_widgets.get("jaw_ctrl_btn"),
            metadata.get("jaw_ctrl"),
            missing_text="—",
            valid_color="#6699cc",
        )

        self._set_scene_node_button(
            module_widgets.get("jaw_jnt_btn"),
            metadata.get("jaw_jnt"),
            missing_text="—",
            valid_color="#6699cc",
        )

    def _refresh_mapped_joints_label(self, module_id, module_widgets, metadata):
        joint_names = metadata.get("joints", [])
        upper_twist_joints = []
        lower_twist_joints = []

        if "Arm" in module_id:
            upper_twist_joints = metadata.get("twist_upper", [])
            lower_twist_joints = metadata.get("twist_lower", [])
        elif "Leg" in module_id:
            upper_twist_joints = metadata.get("twist_thigh", [])
            lower_twist_joints = metadata.get("twist_knee", [])

        mapped_lines = []

        if joint_names:
            mapped_lines.append(f"Joints: {self._short_node_list(joint_names)}")

        if upper_twist_joints:
            mapped_lines.append(f"Upper Twist: {self._short_node_list(upper_twist_joints)}")

        if lower_twist_joints:
            mapped_lines.append(f"Lower Twist: {self._short_node_list(lower_twist_joints)}")

        module_widgets["mapped_joints_lbl"].setText("\n".join(mapped_lines) if mapped_lines else "—")

    def _refresh_spaces_and_connections(self, module_id, module_widgets, main_control):
        spaces_container = module_widgets["spaces_container"]
        spaces_layout = spaces_container.layout()

        self._clear_widget_layout(spaces_layout)

        controls_to_check = self._get_module_space_controls(module_id, main_control)

        has_added_section = False

        for control_name, control_label in controls_to_check:
            if not cmds.objExists(control_name):
                continue

            space_targets = self._get_space_targets(control_name)
            if not space_targets:
                continue

            self._add_spaces_section(
                spaces_layout,
                control_label,
                space_targets,
                add_separator=has_added_section,
            )
            has_added_section = True

        if main_control:
            driven_by_nodes = self._get_incoming_connections(main_control)
            if driven_by_nodes:
                self._add_driven_by_section(
                    spaces_layout,
                    driven_by_nodes,
                    add_separator=has_added_section,
                )

    def _get_module_space_controls(self, module_id, main_control):
        metadata = create_rig.load_module_metadata(module_id) or {}
        stored_controls = [
            ctrl for ctrl in metadata.get("controls", [])
            if ctrl and cmds.objExists(ctrl) and cmds.attributeQuery("space", node=ctrl, exists=True)
        ]
        if stored_controls:
            return [(ctrl, self._space_control_label(ctrl)) for ctrl in stored_controls]

        if "Arm" in module_id:
            side_prefix = "l" if "Left" in module_id else "r"
            return [
                (f"{side_prefix}_upperarm_fk_ctrl", "FK"),
                (f"{side_prefix}_hand_ik_ctrl", "IK"),
                (f"{side_prefix}_lowerarm_pv_ctrl", "PV"),
            ]

        if "Leg" in module_id:
            side_prefix = "l" if "Left" in module_id else "r"
            return [
                (f"{side_prefix}_thigh_fk_ctrl", "FK"),
                (f"{side_prefix}_ankle_ik_ctrl", "IK"),
                (f"{side_prefix}_knee_pv_ctrl", "PV"),
            ]

        return [(main_control, "")] if main_control else []

    def _space_control_label(self, ctrl_name):
        lower_name = ctrl_name.lower()
        if "_fk_ctrl" in lower_name:
            return "FK"
        if "_ik_ctrl" in lower_name:
            return "IK"
        if "_pv_ctrl" in lower_name:
            return "PV"
        return ctrl_name

    def _add_spaces_section(self, layout, control_label, space_targets, add_separator=False):
        if add_separator:
            separator = QtWidgets.QLabel("  ")
        else:
            separator = QtWidgets.QLabel("|")
            separator.setStyleSheet("color: #444444; font-size: 8pt;")

        layout.addWidget(separator)

        header_text = f"{control_label} Spaces →" if control_label else "Spaces →"
        header_label = QtWidgets.QLabel(header_text)
        header_label.setStyleSheet("color: #999999; font-weight: bold; font-size: 8pt;")
        layout.addWidget(header_label)

        for option_name, target_node in space_targets:
            target_button = QtWidgets.QPushButton(option_name)
            target_button.setFlat(True)

            target_exists = target_node and cmds.objExists(target_node)
            color = "#aa88cc" if target_exists else "#cc6666"

            target_button.setStyleSheet(
                f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
                f"text-decoration: underline;"
            )
            target_button.setCursor(QtCore.Qt.PointingHandCursor)

            if target_exists:
                target_button.setToolTip(
                    f"Click to select the space switch target '{target_node}' in the Maya scene."
                )
                target_button.clicked.connect(
                    lambda checked=False, node=target_node: self._select_node(node)
                )
            else:
                target_button.setToolTip(f"Target node '{target_node}' does not exist in the scene.")
                target_button.setEnabled(False)

            layout.addWidget(target_button)

    def _add_driven_by_section(self, layout, driven_by_nodes, add_separator=False):
        if add_separator:
            separator = QtWidgets.QLabel("|")
            separator.setStyleSheet("color: #444444; font-size: 8pt;")
            layout.addWidget(separator)

        header_label = QtWidgets.QLabel("Driven by →")
        header_label.setStyleSheet("color: #999999; font-weight: bold; font-size: 8pt;")
        layout.addWidget(header_label)

        for node_name in driven_by_nodes[:3]:
            node_button = QtWidgets.QPushButton(node_name)
            node_button.setFlat(True)

            node_exists = cmds.objExists(node_name)
            color = "#cc8844" if node_exists else "#cc6666"

            node_button.setStyleSheet(
                f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
                f"text-decoration: underline;"
            )
            node_button.setCursor(QtCore.Qt.PointingHandCursor)
            node_button.setToolTip(f"Click to select the driving node '{node_name}' in the Maya scene.")

            if node_exists:
                node_button.clicked.connect(
                    lambda checked=False, node=node_name: self._select_node(node)
                )
            else:
                node_button.setEnabled(False)

            layout.addWidget(node_button)

    def _set_scene_node_button(self, button, node_name, missing_text="—", valid_color="#6699cc"):
        if not button:
            return

        if not node_name:
            button.setText(missing_text)
            button.setEnabled(False)
            button.setStyleSheet("color: #777777; font-size: 8pt; border: none;")
            return

        node_exists = cmds.objExists(node_name)
        color = valid_color if node_exists else "#cc6666"

        button.setText(node_name)
        button.setEnabled(node_exists)
        button.setStyleSheet(
            f"color: {color}; font-size: 8pt; border: none; "
            f"text-decoration: underline; text-align: left;"
        )

        if node_exists:
            self._safe_reconnect_button(button, lambda: self._select_node(node_name))

    def _safe_reconnect_button(self, button, callback):
        try:
            button.clicked.disconnect()
        except RuntimeError:
            pass
        except TypeError:
            pass

        button.clicked.connect(lambda checked=False: callback())

    def _short_node_list(self, node_names):
        return ", ".join(node.split("|")[-1] for node in node_names if node)

    def _refresh_all_module_details(self):
        """Refresh the detail widget for every registered module."""
        for module_id in list(self._module_detail_widgets.keys()):
            try:
                self._refresh_module_detail_widget(module_id)
            except Exception as e:
                cmds.warning(f"[HIK UI] Could not refresh detail for '{module_id}': {e}")
        self._refresh_additional_systems()

    def _refresh_additional_systems(self):
        """Render registered and external additions below the body modules."""
        layout = self._additional_systems_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        systems = []
        try:
            for record in create_rig.get_dynamic_rig_modules():
                parent_ref = (record.get("build_spec") or {}).get("parent") or {}
                parent_name = (
                    parent_ref.get("name", "")
                    if isinstance(parent_ref, dict)
                    else str(parent_ref)
                )
                inspection = create_rig.inspect_dynamic_rig_module(record)
                systems.append({
                    "system_id": record.get("module_id"),
                    "label": record.get("module_id") or "Unnamed Module",
                    "kind": (record.get("module_type") or "Module").replace("_", " ").title(),
                    "state": "built" if record.get("built") else "recipe saved",
                    "root": "",
                    "parent": parent_name,
                    "managed": True,
                    "node_count": inspection["node_count"],
                    "constraints": inspection["constraints"],
                    "connections": inspection["connections"],
                })
            systems.extend(create_rig.get_embedded_secondary_arm_systems())
            systems.extend(create_rig.get_external_rig_systems(discover_live=True))
        except Exception as exc:
            cmds.warning("[HIK UI] Could not refresh additional rig systems: {}".format(exc))

        if not systems:
            empty = QtWidgets.QLabel("No additional systems detected")
            empty.setStyleSheet("color: #777777; font-style: italic;")
            layout.addWidget(empty)
            return

        for system in systems:
            system_container = QtWidgets.QWidget()
            system_layout = QtWidgets.QVBoxLayout(system_container)
            system_layout.setContentsMargins(0, 0, 0, 0)
            system_layout.setSpacing(2)
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(7)

            toggle_btn = QtWidgets.QToolButton()
            toggle_btn.setText("▶")
            toggle_btn.setFixedSize(16, 16)
            toggle_btn.setStyleSheet("border: none; color: #aaaaaa;")

            select_btn = QtWidgets.QPushButton("⌖")
            select_btn.setFixedSize(20, 20)
            root = system.get("root", "")
            select_btn.setEnabled(bool(root and cmds.objExists(root)))
            root_label = system.get("root_label") or root or system.get("label", "system")
            select_btn.setToolTip("Select {}".format(root_label))
            if root:
                select_btn.clicked.connect(
                    lambda checked=False, node=root: self._select_node(node)
                )

            state = system.get("state", "")
            status = QtWidgets.QLabel("●")
            status.setFixedWidth(12)
            status.setStyleSheet(
                "color: {}; font-size: 10pt;".format(
                    "#43b35b" if state in {"built", "attached"} else
                    "#d6a83c" if state in {"preserved", "recipe saved"} else
                    "#777777"
                )
            )
            name = QtWidgets.QLabel("<b>{}</b>".format(system.get("label", "System")))
            kind = QtWidgets.QLabel(system.get("kind", ""))
            kind.setMinimumWidth(80)
            kind.setStyleSheet("color: #aaaaaa;")
            parent = system.get("parent") or "World"
            details = QtWidgets.QLabel("{}".format(state))
            details.setStyleSheet("color: #888888;")
            parent_btn = QtWidgets.QPushButton("Parent: {}".format(parent))
            parent_btn.setFlat(True)
            parent_btn.setToolTip(
                "Select parent control {}".format(parent)
                if parent != "World" else "This system is parented to world."
            )
            parent_btn.setStyleSheet("border: none; color: #9ecbff; text-align: left;")
            parent_btn.setEnabled(bool(parent != "World" and cmds.objExists(parent)))
            if parent_btn.isEnabled():
                parent_btn.clicked.connect(
                    lambda checked=False, node=parent: self._select_node(node)
                )

            add_btn = QtWidgets.QPushButton("Add")
            add_btn.setFixedWidth(58)
            add_btn.setStyleSheet("background-color: #2e6930; color: white; font-weight: bold;")
            read_only = bool(system.get("read_only"))
            add_btn.setEnabled(not read_only and state in {"preserved", "recipe saved"})
            add_btn.setVisible(not read_only)
            add_btn.setToolTip(
                "This built-in system is part of the core rig; use its controls directly."
                if read_only else "Attach or build this additional system."
            )
            remove_btn = QtWidgets.QPushButton("Remove")
            remove_btn.setFixedWidth(64)
            remove_btn.setStyleSheet("background-color: #7d2a2a; color: white; font-weight: bold;")
            remove_btn.setEnabled(not read_only and state in {"attached", "built"})
            remove_btn.setVisible(not read_only)
            remove_btn.setToolTip(
                "This built-in system is part of the core rig and cannot be detached here."
                if read_only else "Detach or remove this additional system."
            )
            system_id = system.get("system_id", "")
            managed = bool(system.get("managed"))
            add_btn.clicked.connect(
                lambda checked=False, sid=system_id, is_managed=managed:
                self._set_additional_system_active(sid, is_managed, True)
            )
            remove_btn.clicked.connect(
                lambda checked=False, sid=system_id, is_managed=managed:
                self._set_additional_system_active(sid, is_managed, False)
            )

            row_layout.addWidget(toggle_btn)
            row_layout.addWidget(select_btn)
            row_layout.addWidget(status)
            row_layout.addWidget(name)
            row_layout.addStretch(1)
            row_layout.addWidget(kind)
            row_layout.addWidget(details)
            row_layout.addWidget(parent_btn)
            row_layout.addWidget(add_btn)
            row_layout.addWidget(remove_btn)
            system_layout.addWidget(row)

            detail_view = QtWidgets.QPlainTextEdit()
            detail_view.setReadOnly(True)
            detail_view.setMaximumHeight(150)
            detail_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            constraints = system.get("constraints", [])
            connections = system.get("connections", [])
            lines = [
                "Root: {}".format(root_label or "Generated from saved recipe"),
                "Parent: {}".format(parent),
                "Nodes: {}".format(system.get("node_count", "managed by recipe")),
            ]
            if not system.get("inventory_only"):
                lines.append("Constraints ({}):".format(len(constraints)))
                lines.extend("  " + item for item in constraints)
                lines.append("Connections ({}):".format(len(connections)))
                lines.extend("  " + item for item in connections)
            detail_view.setPlainText("\n".join(lines))
            detail_view.hide()
            toggle_btn.clicked.connect(
                lambda checked=False, view=detail_view, button=toggle_btn:
                (view.setVisible(not view.isVisible()),
                 button.setText("▼" if view.isVisible() else "▶"))
            )
            system_layout.addWidget(detail_view)
            layout.addWidget(system_container)

    def _set_additional_system_active(self, system_id, managed, active):
        """Add/remove an extra system, preserving its recipe or live graph."""
        action = "Add" if active else "Remove"
        try:
            if managed:
                create_rig.set_dynamic_rig_module_active(system_id, active)
            else:
                root = str(system_id or "").split("external:", 1)[-1]
                create_rig.set_external_rig_system_active(root, active)
            self._notify_operation(
                "{} Additional System".format(action),
                "{} completed for {}.".format(action, system_id),
                "success",
            )
        except Exception as exc:
            self._notify_operation(
                "{} Additional System Failed".format(action), str(exc), "error"
            )
            cmds.warning(
                "[HIK UI] {} failed for '{}': {}".format(action, system_id, exc)
            )
        self._refresh_additional_systems()

    def _get_registered_module_ids(self):
        module_ids = []
        module_ids.extend(self._module_detail_widgets.keys())
        module_ids.extend(self.module_create_buttons.keys())
        module_ids.extend(self.module_remove_buttons.keys())
        return list(dict.fromkeys(module_ids))

    def _populate_fields_from_metadata(self, module_id, metadata):
        if not metadata:
            return

        module_widgets = self._module_detail_widgets.get(module_id)

        def set_hik_field_if_empty(field_name, joint_name):
            if field_name in self.fields and not self.fields[field_name]:
                self.fields[field_name] = joint_name

        def set_line_edit_if_empty(widget_key, value):
            if not module_widgets:
                return

            line_edit = module_widgets.get(widget_key)
            if line_edit and value and not line_edit.text().strip():
                line_edit.setText(value)

        def populate_chain_slots(slot_names, joint_names):
            for slot_name, joint_name in zip(slot_names, joint_names):
                set_hik_field_if_empty(slot_name, joint_name)

        def populate_numbered_slots(base_slot_name, joint_names):
            for index, joint_name in enumerate(joint_names):
                slot_name = base_slot_name if index == 0 else f"{base_slot_name}{index}"
                set_hik_field_if_empty(slot_name, joint_name)

        def populate_roll_slots(first_roll_slot, leaf_roll_prefix, roll_joints):
            if not roll_joints:
                return

            set_hik_field_if_empty(first_roll_slot, roll_joints[0])

            for index, joint_name in enumerate(roll_joints[1:], start=1):
                set_hik_field_if_empty(f"{leaf_roll_prefix}{index}", joint_name)

        parent_control = metadata.get("parent")
        if parent_control and cmds.objExists(parent_control):
            set_line_edit_if_empty("parent_edit", parent_control)

        if module_id in {"Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"}:
            set_line_edit_if_empty("jaw_ctrl_edit", metadata.get("jaw_ctrl"))
            set_line_edit_if_empty("jaw_jnt_edit", metadata.get("jaw_jnt"))

        joint_names = metadata.get("joints", [])

        if module_id == "Root / Origin":
            populate_chain_slots(["Reference"], joint_names)

        elif module_id == "Pelvis & Hips":
            populate_chain_slots(["Hips", "HipSwing"], joint_names)

        elif module_id == "Spine":
            populate_numbered_slots("Spine", joint_names)

        elif module_id == "Neck":
            populate_numbered_slots("Neck", joint_names)

        elif module_id == "Head":
            populate_chain_slots(["Head"], joint_names)

        elif "Clavicle" in module_id:
            side_label = "Left" if "Left" in module_id else "Right"
            populate_chain_slots([f"{side_label}Shoulder"], joint_names)

        elif "Arm" in module_id:
            side_label = "Left" if "Left" in module_id else "Right"

            populate_chain_slots(
                [f"{side_label}Arm", f"{side_label}ForeArm", f"{side_label}Hand"],
                joint_names
            )

            populate_roll_slots(
                f"{side_label}ArmRoll",
                f"Leaf{side_label}ArmRoll",
                metadata.get("twist_upper", [])
            )

            populate_roll_slots(
                f"{side_label}ForeArmRoll",
                f"Leaf{side_label}ForearmRoll",
                metadata.get("twist_lower", [])
            )

        elif "Leg" in module_id:
            side_label = "Left" if "Left" in module_id else "Right"

            populate_chain_slots(
                [f"{side_label}UpLeg", f"{side_label}Leg", f"{side_label}Foot", f"{side_label}ToeBase"],
                joint_names
            )

            populate_roll_slots(
                f"{side_label}UpLegRoll",
                f"Leaf{side_label}UpLegRoll",
                metadata.get("twist_thigh", [])
            )

            populate_roll_slots(
                f"{side_label}LegRoll",
                f"Leaf{side_label}LegRoll",
                metadata.get("twist_knee", [])
            )

    def _get_first_existing_ctrl(self, module_id, meta=None):
        """Return the first scene-existing control for a module (candidates + metadata fallback)."""
        candidates = []
        if meta:
            candidates.extend(meta.get("controls", []))
        candidates.extend(self._MODULE_CTRL_CANDIDATES.get(module_id, []))
        if meta:
            for jnt in meta.get("joints", []):
                if jnt:
                    candidates.append(jnt + "_ctrl")
                    candidates.append(jnt + "_fk_ctrl")
        # Fallback to active UI mappings if metadata doesn't have joints (useful for face modules)
        if not meta or not meta.get("joints"):
            face_joints = self._get_face_module_joints(module_id)
            for jnt in face_joints:
                if jnt:
                    candidates.append(jnt + "_ctrl")
                    candidates.append(jnt + "_fk_ctrl")
        for c in candidates:
            if c and cmds.objExists(c):
                return c
        return None

    def _select_module_root(self, module_name):
        """Select the first existing control for a module."""
        ctrl = self._get_first_existing_ctrl(module_name)
        if ctrl and cmds.objExists(ctrl):
            cmds.select(ctrl, replace=True)
        else:
            cmds.warning(f"Root control for module '{module_name}' not found. Is the module built?")

    def _get_ctrl_scene_parent(self, ctrl):
        """Traverse up the DAG hierarchy to find the first ancestor ending with '_ctrl'."""
        if not ctrl or not cmds.objExists(ctrl):
            return None
        curr = ctrl
        while True:
            parents = cmds.listRelatives(curr, parent=True, fullPath=False)
            if not parents:
                break
            curr = parents[0]
            if curr.endswith("_ctrl"):
                return curr
        return None

    def _get_space_targets(self, ctrl):
        """Return the list of (display_name, actual_node_name) space switch option names for *ctrl*, if any."""
        if not cmds.objExists(ctrl):
            return []

        # 1. Collect orientConstraint, parentConstraint, pointConstraint on ctrl, parent, grandparent
        nodes_to_check = [ctrl]
        curr = ctrl
        for _ in range(2):
            if cmds.objExists(curr):
                parents = cmds.listRelatives(curr, parent=True) or []
                if parents:
                    nodes_to_check.append(parents[0])
                    curr = parents[0]
                else:
                    break

        con_nodes = []
        for node in nodes_to_check:
            con_nodes.extend(
                cmds.listRelatives(node, type=["orientConstraint", "parentConstraint", "pointConstraint"]) or [])
            # Also check for duplicate target constraints (e.g. _spaceTarget parent group)
            parents = cmds.listRelatives(node, parent=True) or []
            for p in parents:
                if p.endswith("_spaceTarget"):
                    con_nodes.extend(
                        cmds.listRelatives(p, type=["orientConstraint", "parentConstraint", "pointConstraint"]) or [])

        con_nodes = list(dict.fromkeys(con_nodes))
        actual_targets = []
        for con in con_nodes:
            try:
                ct = cmds.nodeType(con)
                if "orient" in ct:
                    t = cmds.orientConstraint(con, q=True, targetList=True) or []
                elif "parent" in ct:
                    t = cmds.parentConstraint(con, q=True, targetList=True) or []
                else:
                    t = cmds.pointConstraint(con, q=True, targetList=True) or []
                actual_targets.extend(t)
            except Exception:
                pass
        actual_targets = list(dict.fromkeys(actual_targets))

        # Helper to resolve _spaceTarget back to original control
        def resolve_target(target_node):
            if target_node and target_node.endswith("_spaceTarget"):
                parents = cmds.listRelatives(target_node, parent=True) or []
                if parents:
                    return parents[0]
            return target_node

        resolved_targets = [resolve_target(t) for t in actual_targets]

        # 2. Enum 'space' attribute on the ctrl itself
        if cmds.attributeQuery("space", node=ctrl, exists=True):
            try:
                enum_str = cmds.attributeQuery("space", node=ctrl, listEnum=True)
                if enum_str:
                    options = [e.strip() for e in enum_str[0].split(":") if e.strip()]
                    result = []
                    for idx, opt in enumerate(options):
                        target_node = resolved_targets[idx] if idx < len(resolved_targets) else None
                        result.append((opt, target_node))
                    return result
            except Exception:
                pass

        # Only return spaces if there is a 'space' attribute defining them.
        return []

    def _get_incoming_connections(self, ctrl):
        """Return external nodes driving *ctrl* via connections or constraints (excluding its own pad/sdk chain)."""
        if not cmds.objExists(ctrl):
            return []

        # Collect ctrl, parent, and grandparent
        nodes_to_check = [ctrl]
        curr = ctrl
        for _ in range(2):
            if cmds.objExists(curr):
                parents = cmds.listRelatives(curr, parent=True) or []
                if parents:
                    nodes_to_check.append(parents[0])
                    curr = parents[0]
                else:
                    break

        internal_nodes = set(nodes_to_check)
        driven_by = set()

        for node in nodes_to_check:
            if not cmds.objExists(node):
                continue
            cons = cmds.listConnections(node, source=True, destination=False, skipConversionNodes=True) or []
            for c in cons:
                node_type = cmds.nodeType(c)
                if node_type in ("nodeGraphEditorInfo", "hyperLayout", "hyperView", "time"):
                    continue
                # If it's a constraint, get its target list
                if "Constraint" in node_type:
                    try:
                        if "orient" in node_type:
                            targets = cmds.orientConstraint(c, q=True, targetList=True) or []
                        elif "parent" in node_type:
                            targets = cmds.parentConstraint(c, q=True, targetList=True) or []
                        else:
                            targets = cmds.pointConstraint(c, q=True, targetList=True) or []
                        for t in targets:
                            if t not in internal_nodes and t.split("_")[0] != ctrl.split("_")[0]:
                                resolved = t
                                if t.endswith("_spaceTarget"):
                                    pts = cmds.listRelatives(t, parent=True) or []
                                    if pts:
                                        resolved = pts[0]
                                if resolved not in internal_nodes:
                                    driven_by.add(resolved)
                    except Exception:
                        pass
                else:
                    if c not in internal_nodes:
                        driven_by.add(c)

        return sorted(list(driven_by))

    def _clear_widget_layout(self, layout):
        """Remove and delete all widgets from a QLayout."""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _select_node(self, node):
        """Select *node* in the Maya scene if it exists."""
        if node and cmds.objExists(node):
            cmds.select(node, replace=True)

    def _on_tab_changed(self, index):
        """Handle lightweight tab activation without rescanning the scene.

        Module status already refreshes after build/remove operations and via
        the explicit Refresh Module Details button. A tab click must remain a
        pure UI operation; live extension discovery walks the Maya graph and
        is intentionally not run here.
        """
        return None

    def _load_module_metadata_from_scene(
        self, report_missing=True, refresh_details=True
    ):
        """
        Read rig_module_store and refresh all detail widgets.

        When report_missing is False, stale saved-joint references are ignored
        silently. This is used during initial UI startup.
        """
        try:
            all_meta = create_rig.get_all_module_metadata()
        except Exception as e:
            cmds.warning(f"[HIK UI] Could not read module metadata: {e}")
            return

        # Key normalisation map — attr key → display name
        key_to_display = {
            "root___origin": "Root / Origin",
            "pelvis___hips": "Pelvis & Hips",
            "spine": "Spine",
            "left_clavicle": "Left Clavicle",
            "right_clavicle": "Right Clavicle",
            "neck": "Neck",
            "head": "Head",
            "left_arm": "Left Arm",
            "right_arm": "Right Arm",
            "left_leg": "Left Leg",
            "right_leg": "Right Leg",
            "brows__left_": "Brows (Left)",
            "brows__right_": "Brows (Right)",
            "eyelids__left_": "Eyelids (Left)",
            "eyelids__right_": "Eyelids (Right)",
            "mouth___lips": "Mouth & Lips",
            "eyes_aim": "Eyes Aim",
            "tongue": "Tongue",
            "teeth": "Teeth",
            "other_face_joints": "Other Face Joints",
        }

        missing_joints = []
        for attr_key, data in all_meta.items():
            display_name = key_to_display.get(attr_key)
            if display_name is None:
                for k, v in key_to_display.items():
                    if attr_key.startswith(k) or k.startswith(attr_key):
                        display_name = v
                        break
            if display_name is None:
                continue
            if data.get("built"):
                for jnt in data.get("joints", []):
                    if jnt and not cmds.objExists(jnt):
                        missing_joints.append((display_name, jnt))

        if missing_joints and report_missing:
            unique_missing = {
                (module_name, joint_name)
                for module_name, joint_name in missing_joints
                if joint_name
            }

            self._pending_module_discrepancies.update(unique_missing)

            if not self._defer_module_discrepancy_warnings:
                lines = [
                    f"  • [{module_name}] {joint_name}"
                    for module_name, joint_name in sorted(unique_missing)
                ]
                msg = (
                        "The following joints referenced by saved rig modules were "
                        "not found in the current scene:\n\n"
                        + "\n".join(lines)
                        + "\n\nThese missing references will be ignored."
                )
                cmds.warning("[HIK UI] Module discrepancy detected.")
                self._notify_operation(
                    "Module Discrepancy Warning", msg, "warning"
                )

        # Refreshing each module's live DAG/connection state is optional so UI
        # construction can defer that work until after the window first paints.
        if refresh_details:
            self._refresh_all_module_details()


def launch_hik_ui(
    parent=None,
    *,
    graph=None,
    selection_provider=None,
    undo_callback=None,
    refresh_callback=None,
):
    global hik_ui_instance
    host_mode = "maya"
    if graph is not None:
        if MAYA_HOST:
            raise RuntimeError("A TC rig graph cannot be bound inside Maya's HIK host mode.")
        from tech_connector.services.dcc.tc_hik_ui_host import bind_tc_hik_host
        bind_tc_hik_host(
            graph,
            selection_provider=selection_provider,
            undo_callback=undo_callback,
            refresh_callback=refresh_callback,
        )
        host_mode = "tech_connector"
    previous_instance = globals().get("hik_ui_instance")
    if previous_instance is not None:
        try:
            previous_instance.close()
        except (RuntimeError, AttributeError):
            pass

    hik_ui_instance = HIKDefinitionUI(parent, host_mode=host_mode)
    hik_ui_instance.show()
    return hik_ui_instance


if __name__ == "__main__":
    launch_hik_ui()
