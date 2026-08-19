import os
import json
import traceback
import re
import importlib

try:
    import maya.cmds as cmds
    from maya import OpenMayaUI as omui
    MAYA_HOST = True
except ImportError:
    MAYA_HOST = False

if MAYA_HOST and int(cmds.about(version=True)) < 2025:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance
else:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance

if MAYA_HOST:
    from maya_tools.Rigging.mocap import setup_hik
    from maya_tools.Rigging import create_rig
    from maya_tools.Rigging import rig_template
    from maya_tools.Rigging import skinning_utils
    from maya_tools.Utilities import joints, dag
else:
    from tech_connector.services.dcc.tc_hik_ui_host import (
        cmds, create_rig, dag, joints, omui, rig_template, setup_hik, skinning_utils,
    )
from unreal_tools import unreal_subprocess as usp
from unreal_tools import unreal_project_data as upd
from maya_tools.Rigging.mocap.hik_ui_specialized_tabs import HIKSpecializedTabsMixin

importlib.reload(usp)
importlib.reload(upd)
if MAYA_HOST:
    importlib.reload(skinning_utils)
    importlib.reload(create_rig)
    importlib.reload(rig_template)
    importlib.reload(setup_hik)

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

    def filter_meshes(self, text):
        self.mesh_input.clear()
        filtered = [s for s in self.skeletal_meshes if text.lower() in s.lower()]
        self.mesh_input.addItems(filtered)

    def create_control_rig(self):
        selected_mesh = self.mesh_input.currentText()
        rig_name = self.cr_name_input.text().strip()
        usp.run_create_modular_control_rig(selected_mesh, rig_name, self.joint_map, self.uproject, self.log_path,
                                           self.cmd_path)


class HIKDefinitionUI(HIKSpecializedTabsMixin, QtWidgets.QDialog):
    def __init__(self, parent=None, *, host_mode="maya"):
        self.host_mode = str(host_mode or ("maya" if MAYA_HOST else "tech_connector"))
        if parent is None and MAYA_HOST:
            parent = wrapInstance(get_main_window_pointer(), QtWidgets.QMainWindow)
        super(HIKDefinitionUI, self).__init__(parent)

        self.setWindowTitle("HIK & Rig Builder")
        self.setMinimumSize(900, 600)
        self.setLayout(QtWidgets.QVBoxLayout())

        # Open a Python command port on port 7002 if not already open
        if MAYA_HOST:
            try:
                if not cmds.commandPort(":7002", q=True):
                    cmds.commandPort(name=":7002", sourceType="python")
            except Exception as e:
                print(f"[HIK UI] Failed to open commandPort 7002: {e}")

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
        self.default_map = dict(setup_hik.DEFAULT_JOINT_MAP)
        self.default_map["HipSwing"] = {"index": -1, "joint": ""}
        self.default_face_map = setup_hik.DEFAULT_FACE_JOINT_MAP
        self.populate_default_face_map_from_scene()
        self.current_slot = None
        self._module_detail_widgets = {}  # {module_id: {"container", "status_lbl", "parent_btn", "spaces_widget"}}
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

        # Refresh detail widgets when the Rigging tab becomes active
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Auto-populate module states from scene metadata without showing
        # stale saved-joint warnings when the UI first opens.
        self._load_module_metadata_from_scene(report_missing=False)

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

        self.surf_region_combo = QtWidgets.QComboBox()
        self.surf_region_combo.addItems(["eyelid", "mouth", "brow", "other"])
        self.surf_region_combo.setToolTip("Choose the facial anatomical region this surface rig is built for.")

        self.surf_side_combo = QtWidgets.QComboBox()
        self.surf_side_combo.addItems(["r", "l"])
        self.surf_side_combo.setToolTip("Select the character side (l for Left, r for Right) the surface resides on.")

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

        skin_group = QtWidgets.QGroupBox("Skinning")
        skin_layout = QtWidgets.QVBoxLayout(skin_group)

        export_skin_btn = QtWidgets.QPushButton("Export Skin Weights")
        export_skin_btn.setToolTip("Export the skin weights of all selected skinned meshes to JSON files.")
        import_skin_btn = QtWidgets.QPushButton("Import Skin Weights")
        import_skin_btn.setToolTip("Import skin weights from JSON files to matching meshes in the scene.")
        transfer_skin_btn = QtWidgets.QPushButton("Transfer Skin Weights")
        transfer_skin_btn.setToolTip(
            "Transfer skin weights from selected source mesh(es) to the last selected target mesh. The target must not already have a skinCluster.")

        export_skin_btn.clicked.connect(self.export_skin_weights)
        import_skin_btn.clicked.connect(self.import_skin_weights)
        transfer_skin_btn.clicked.connect(self.transfer_skin_weights_from_selection)

        skin_layout.addWidget(export_skin_btn)
        skin_layout.addWidget(import_skin_btn)
        skin_layout.addWidget(transfer_skin_btn)

        self.rig_layout.addWidget(skin_group)

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
        if self.host_mode != "maya":
            import_template_btn.setText("Load TC Biped Template")
            import_template_btn.setToolTip("Instantiate the selected TC-native skeleton template in this scene.")
            reference_template_btn.hide()
            template_path_btn.setToolTip("Choose a TC .tcrig.json skeleton template file.")
            self.rig_template_path_field.setToolTip("Versioned TC-native skeleton template asset.")
            self.rig_template_namespace_field.setToolTip("Optional namespace for loading another template instance.")

        # 1. Create Rig Mapping & Build Full Rig Buttons
        mapping_btn = QtWidgets.QPushButton("Create Rig Mapping")
        mapping_btn.setToolTip("Synchronize and cache the active HumanIK body and face mapping settings.")
        mapping_btn.setStyleSheet(
            "background-color: #3b825c; color: white; font-weight: bold; font-size: 11pt; height: 28px;")
        mapping_btn.clicked.connect(self.create_rig_mapping)
        actions_layout.addWidget(mapping_btn)

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
            QtWidgets.QMessageBox.information(
                self,
                "TC Biped Template Loaded" if self.host_mode != "maya" else "Biped Template Loaded",
                ("Loaded TC-native biped skeleton template.\n\n" if self.host_mode != "maya" else "Loaded biped rig template.\n\n")
                +
                f"Root joints: {len(result.get('root_joints') or [])}\n"
                f"RFL joints: {result.get('rfl_joint_count', 0)}\n"
                f"New nodes: {result.get('new_node_count', 0)}",
            )
            return result
        except Exception as e:
            traceback.print_exc()
            QtWidgets.QMessageBox.critical(self, "Biped Template Load Failed", str(e))
            raise
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass

    def create_rig_mapping(self):
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

        self._refresh_all_module_details()

        return True

    def build_full_rig(self):
        self.create_rig_mapping()

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

        try:
            # 1. Run T-pose alignment on mapped arm joints
            if hasattr(self, "default_map") and self.default_map:
                try:
                    setup_hik.set_t_pose(joint_map=self.default_map)
                except Exception as e:
                    print(f"[Warning] Failed to run set_t_pose before building rig: {e}")

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
                    self.create_face_module_setup(module, silent=True)
                else:
                    self.create_body_module_setup(module, silent=True)

                built_modules.append(module)

            # Recreate all spaces and composite spaces once at the end.
            for side in ("l", "r"):
                create_rig.create_arm_space_switches(side)
                create_rig.create_leg_space_switches(side)

            create_rig.delete_unused_scaffold_nodes()
            self.store_all_face_connections(silent=True)

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

            cmds.confirmDialog(
                title="Success",
                message=summary,
                button=["OK"]
            )

        except Exception as e:
            cmds.confirmDialog(
                title="Error",
                message=f"Failed to create full rig:\n{e}",
                button=["OK"]
            )
            cmds.warning(f"Failed to create full rig: {e}")

        finally:
            cmds.undoInfo(closeChunk=True)

            # Keep warning deferral enabled for the final metadata refresh so it
            # cannot reopen the same discrepancy dialog after the summary.
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

            self._defer_module_discrepancy_warnings = False
            self._pending_module_discrepancies.clear()

    def remove_full_rig(self):
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
            cmds.confirmDialog(title="Success", message="Full Rig removed successfully!", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove full rig:\n{e}", button=["OK"])
            cmds.warning(f"Failed to remove full rig: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

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
            create_rig.create_joint_controls(
                joint_list=sel,
                control_shape=shape,
                root_parent=parent,
                sub_ctrls=False,
                keep_constraint=True
            )
            cmds.confirmDialog(title="Success", message="Control(s) created successfully!", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create control(s):\n{e}", button=["OK"])
            cmds.warning(f"Failed to create control(s): {e}")

    def export_skin_weights(self):
        meshes = cmds.ls(selection=True) or []
        if not meshes:
            cmds.confirmDialog(
                title="Export Skin Weights",
                message="Select one or more skinned meshes to export.",
                button=["OK"],
                icon="warning",
            )
            return
        export_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Export Skin Weights", "C:/temp/weights"
        )
        if export_dir:
            return skinning_utils.export_skin_weights(meshes, export_dir)

    def import_skin_weights(self):
        meshes = cmds.ls(selection=True) or []
        import_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Import Skin Weights", "C:/temp/weights"
        )
        if import_dir:
            return skinning_utils.import_skin_weights(meshes, import_dir)

    def transfer_skin_weights_from_selection(self):
        selection = cmds.ls(selection=True) or []
        if len(selection) < 2:
            cmds.confirmDialog(
                title="Transfer Skin Weights",
                message="Select one or more skinned source meshes, then select the target mesh last.",
                button=["OK"],
                icon="warning"
            )
            return

        result = skinning_utils.transfer_skin_weights_from_selection()
        if not result:
            cmds.confirmDialog(
                title="Transfer Skin Weights",
                message="Skin weight transfer failed. Check the Script Editor for details.",
                button=["OK"],
                icon="warning"
            )
            return

        cmds.confirmDialog(
            title="Transfer Skin Weights",
            message=(
                f"Transferred skin weights to '{selection[-1]}'.\n"
                f"Created skinCluster: {result.get('skinCluster')}"
            ),
            button=["OK"]
        )

    def create_surface_rig_with_drivers(self):
        sel = cmds.ls(sl=True, type="joint")
        if not sel:
            cmds.warning("Please select a joint chain to create a surface rig.")
            return

        parent = self.surface_parent_field.text().strip() or None
        loft_name = self.surf_name_field.text().strip() or "eyelid"
        region = self.surf_region_combo.currentText()
        side = self.surf_side_combo.currentText()
        offset = self.surf_offset_spin.value()

        indices_text = self.surf_indices_field.text().strip()
        driver_indices = None
        if indices_text:
            try:
                driver_indices = [int(x.strip()) for x in indices_text.split(",") if x.strip()]
            except ValueError:
                cmds.warning("Invalid driver indices format. Using None.")

        try:
            create_rig.setup_surface_rig_with_drivers(
                joint_list=sel,
                loft_name=loft_name,
                offset=offset,
                driver_follicle_indices=driver_indices,
                side=side,
                region=region,
                root_parent=parent
            )
            cmds.confirmDialog(title="Success", message="Surface Rig created successfully!", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create surface rig:\n{e}", button=["OK"])
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
        root_joint = joints.find_skinned_or_top_joints(namespace='')[0]
        joint_map = self.guess_joint_map_from_root(root_joint)
        for slot in self.default_map:
            if slot in joint_map:
                self.fields[slot] = joint_map[slot].get("joint")
            self.update_button_color(slot)
        # self._build_face_rig_section(self.rig_layout)
        self._refresh_all_module_details()

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

                skel_meshes = usp.run_get_skeletons(
                    uproject, log_path, cmd_path, "SkeletalMesh"
                )

                self.popup = ControlRigPopup(skel_meshes, joint_map, uproject)
                self.popup.exec_()

    def store_all_face_connections(self, silent=False):
        self.create_rig_mapping()

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

            cmds.confirmDialog(title="Global Store", message=message, button=["OK"])

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
                            cmds.confirmDialog(title="Error",
                                               message="Nothing selected. Please select a node in the scene.",
                                               button=["OK"])
                    else:
                        return

        self.create_rig_mapping()
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

            # Recreate only the relevant module's space switches (and composite spaces)
            if module == "Left Arm":
                create_rig.create_arm_space_switches("l")
            elif module == "Right Arm":
                create_rig.create_arm_space_switches("r")
            elif module == "Left Leg":
                create_rig.create_leg_space_switches("l")
            elif module == "Right Leg":
                create_rig.create_leg_space_switches("r")
            elif module in ("Pelvis & Hips", "Root / Origin", "Spine", "Left Clavicle", "Right Clavicle"):
                # Update any existing limb space switches to connect to the new core controls
                for s in ("l", "r"):
                    create_rig.create_arm_space_switches(s)
                    create_rig.create_leg_space_switches(s)

            restored = create_rig.restore_rig_connections(module)

            # Auto-store the module's current connections so they survive rebuilds
            self.store_all_face_connections(silent=silent)

            if not silent:
                msg = f"Body Module '{module}' created successfully!"
                if restored > 0:
                    msg += f"\nRestored {restored} connections/space switches."
                cmds.confirmDialog(title="Success", message=msg, button=["OK"])
            create_rig.restore_all_control_cv_positions()
            for ikh in cmds.ls(type="ikHandle") or []:
                try:
                    cmds.setAttr(f"{ikh}.visibility", 0)
                except Exception:
                    pass
        except Exception as e:
            print(f"[ERROR] create_body_module_setup failed for module={module} parent={parent}: {e}")
            traceback.print_exc()
            cmds.confirmDialog(title="Error", message=f"Failed to create body module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def remove_body_module_setup(self, module):
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

            cmds.confirmDialog(title="Success",
                               message=f"Body Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.",
                               button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove body module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

    def create_face_module_setup(self, module, silent=False):
        edit_info = self._module_detail_widgets.get(module)
        parent = None
        if edit_info and edit_info.get("parent_edit"):
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
                            cmds.confirmDialog(title="Error",
                                               message="Nothing selected. Please select a node in the scene.",
                                               button=["OK"])
                    else:
                        return

        jaw_ctrl = None
        if edit_info and edit_info.get("jaw_ctrl_edit"):
            jaw_ctrl = edit_info["jaw_ctrl_edit"].text().strip() or None
        if not jaw_ctrl:
            jaw_ctrl = self.module_jaw_ctrl_field.text().strip() or None

        jaw_jnt = None
        if edit_info and edit_info.get("jaw_jnt_edit"):
            jaw_jnt = edit_info["jaw_jnt_edit"].text().strip() or None
        if not jaw_jnt:
            jaw_jnt = self.module_jaw_jnt_field.text().strip() or None

        self.create_rig_mapping()

        # Remove missing scene joints from this module's active mapping before
        # the builder or metadata store sees them.
        face_joints = [
            joint for joint in self._get_face_module_joints(module)
            if joint and cmds.objExists(joint)
        ]

        if not face_joints:
            if not silent:
                cmds.confirmDialog(
                    title="Skipped",
                    message=(
                        f"Face Module '{module}' was not built because none of "
                        "its mapped joints exist in the current scene."
                    ),
                    button=["OK"]
                )
            return

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

            restored = create_rig.restore_rig_connections(module)

            # Save only joints that actually exist in the current scene.
            create_rig.save_module_metadata(module, {
                "parent": parent or "",
                "jaw_ctrl": jaw_ctrl or "",
                "jaw_jnt": jaw_jnt or "",
                "joints": face_joints,
                "built": True
            })

            # Auto-store the module's current connections so they survive rebuilds
            self.store_all_face_connections(silent=silent)

            if not silent:
                msg = f"Face Module '{module}' created successfully!"
                if restored > 0:
                    msg += f"\nRestored {restored} connections/space switches."
                cmds.confirmDialog(title="Success", message=msg, button=["OK"])
            create_rig.restore_all_control_cv_positions()
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create face module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def remove_face_module_setup(self, module):
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

            cmds.confirmDialog(title="Success",
                               message=f"Face Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.",
                               button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove face module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()
            dag.enable_evaluation()

    def load_settings_from_selection(self):
        sel = cmds.ls(sl=True)
        if not sel:
            cmds.confirmDialog(title="Info", message="Please select a control or joint in the scene first.",
                               button=["OK"])
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
        cmds.confirmDialog(title="Settings Loaded", message=msg, button=["OK"])
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
        """Refresh module details whenever the Rigging tab becomes active."""
        if self.tabs.tabText(index) == "Rigging":
            self._refresh_all_module_details()

    def _load_module_metadata_from_scene(self, report_missing=True):
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
                cmds.confirmDialog(
                    title="Module Discrepancy Warning",
                    message=msg,
                    button=["OK"],
                    icon="warning"
                )

        # Refresh all live detail widgets from the scene
        self._refresh_all_module_details()


def launch_hik_ui(
    parent=None,
    *,
    graph=None,
    selection_provider=None,
    undo_callback=None,
    refresh_callback=None,
):
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
    hik_ui_instance = HIKDefinitionUI(parent, host_mode=host_mode)
    hik_ui_instance.show()
    return hik_ui_instance


if __name__ == "__main__":
    launch_hik_ui()
