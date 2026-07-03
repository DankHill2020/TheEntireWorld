import os
import json
import maya.cmds as cmds
from maya import OpenMayaUI as omui
import re

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance

from maya_tools.Rigging.mocap import setup_hik
from maya_tools.Rigging import create_rig
from maya_tools.Rigging import skinning_utils
from unreal_tools import unreal_subprocess as usp
from unreal_tools import unreal_project_data as upd
from maya_tools.Utilities import joints
import importlib

importlib.reload(skinning_utils)
importlib.reload(usp)
importlib.reload(upd)
importlib.reload(create_rig)
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
        
        self.checkbox = QtWidgets.QCheckBox("Use this parent control for all remaining systems with missing parent control")
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


class HIKDefinitionUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        if parent is None:
            parent = wrapInstance(get_main_window_pointer(), QtWidgets.QMainWindow)
        super(HIKDefinitionUI, self).__init__(parent)

        self.setWindowTitle("HIK & Rig Builder")
        self.setMinimumSize(900, 600)
        self.setLayout(QtWidgets.QVBoxLayout())

        # Open a Python command port on port 7002 if not already open
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
        self.namespace.setToolTip("The namespace prefix applied to character joints and animation nodes during retargeting.")

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

        # ---------- Tabs ----------
        self.tabs = QtWidgets.QTabWidget()
        self.layout().addWidget(self.tabs)

        self._build_hik_tab()
        self._build_rigging_tab()

        # Refresh detail widgets when the Rigging tab becomes active
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Auto-populate module states from scene metadata
        self._load_module_metadata_from_scene()

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
        detect_btn.setToolTip("Attempt to automatically discover and map joints in the scene based on naming conventions.")
        detect_btn.clicked.connect(self.auto_detect)

        self.unreal_checkbox = QtWidgets.QCheckBox("Create Unreal Rig")
        self.unreal_checkbox.setToolTip("When checked, automatically generates the Unreal modular control rig for the built skeleton.")

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
        auto_detect_indices_btn.setToolTip("Automatically populate matching indices based on the selected region profile.")
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
        create_surf_btn.setToolTip("Generate a lofted surface and follicle-driven secondary control setup for facial regions.")
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
        self.space_switch_orient_rb.setToolTip("Use an orientConstraint for space switching (changes rotation space only).")
        self.space_switch_parent_rb = QtWidgets.QRadioButton("Parent")
        self.space_switch_parent_rb.setToolTip("Use a parentConstraint for space switching (changes translation and rotation spaces).")
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

        export_skin_btn.clicked.connect(skinning_utils.export_skin_weights)
        import_skin_btn.clicked.connect(skinning_utils.import_skin_weights)

        skin_layout.addWidget(export_skin_btn)
        skin_layout.addWidget(import_skin_btn)

        self.rig_layout.addWidget(skin_group)

        # ------------------------------------------------------------
        # Full Rig Actions Section
        # ------------------------------------------------------------
        self.rig_layout.addSpacing(20)
        actions_group = QtWidgets.QGroupBox("Full Rig Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)
        
        # 1. Create Rig Mapping & Build Full Rig Buttons
        mapping_btn = QtWidgets.QPushButton("Create Rig Mapping")
        mapping_btn.setToolTip("Synchronize and cache the active HumanIK body and face mapping settings.")
        mapping_btn.setStyleSheet("background-color: #3b825c; color: white; font-weight: bold; font-size: 11pt; height: 28px;")
        mapping_btn.clicked.connect(self.create_rig_mapping)
        actions_layout.addWidget(mapping_btn)

        body_btn = QtWidgets.QPushButton("Build Full Rig")
        body_btn.setToolTip("Construct the complete animation control rig for all mapped body and face modules.")
        body_btn.setStyleSheet("background-color: #1a4d1a; color: white; font-weight: bold; font-size: 12pt; height: 30px;")
        body_btn.clicked.connect(self.build_full_rig)
        actions_layout.addWidget(body_btn)

        remove_rig_btn = QtWidgets.QPushButton("Remove Full Rig")
        remove_rig_btn.setToolTip("Teardown the control rig setup, delete constraints/pads, and restore default skeletons.")
        remove_rig_btn.setStyleSheet("background-color: #8a1a1a; color: white; font-weight: bold; font-size: 12pt; height: 30px;")
        remove_rig_btn.clicked.connect(self.remove_full_rig)
        actions_layout.addWidget(remove_rig_btn)
        
        store_load_row = QtWidgets.QHBoxLayout()
        global_store_btn = QtWidgets.QPushButton("Store Connections & Switches")
        global_store_btn.setToolTip("Capture and cache all custom parent constraints and space switch states on the controls.")
        global_store_btn.setStyleSheet("background-color: #3b5b82; color: white; font-weight: bold;")
        global_store_btn.clicked.connect(self.store_all_face_connections)

        load_selection_btn = QtWidgets.QPushButton("Load From Selection")
        load_selection_btn.setToolTip("Quickly select parent and target settings using the active scene selection.")
        load_selection_btn.setStyleSheet("background-color: #5c5c5c; color: white; font-weight: bold;")
        load_selection_btn.clicked.connect(self.load_settings_from_selection)

        refresh_details_btn = QtWidgets.QPushButton("↻ Refresh Module Details")
        refresh_details_btn.setToolTip("Query the scene to update the status and parent connection fields for all modules.")
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
        self.body_parent_field.setToolTip("Optional: Parent control for body modules. If left empty, resolves to optimal scene defaults.")
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
        self.module_parent_field.setToolTip("Optional: Parent control for face modules (e.g. head1_ctrl). If left empty, resolves to optimal scene defaults.")
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
            if "Constraint" in ct or ct in ["blendColors", "multiplyDivide", "plusMinusAverage", "reverse", "condition", "choice", "animCurve"]:
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
                item.setForeground(QtGui.QColor("#d8b4fe")) # Sleek purple
            elif "Connected" in status:
                item.setForeground(QtGui.QColor("#fdba74")) # Warm orange
            else:
                item.setForeground(QtGui.QColor("#86efac")) # Clean light green
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
        dm = self.default_face_map

        side = "l"
        dm["LeftBrow"]["joints"] = brow_joints = [f"{side}_brow{i}" for i in range(1, 6)]
        dm["LeftEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
        dm["LeftEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
        dm["LeftEyelid"]["joints"] = [
            f"{side}_inner_eyelidTip",
            f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
            f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
            f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
            f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
            f"{side}_outer_eyelidTip",
            f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
            f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
            f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
        ]
        side = "r"
        dm["RightBrow"]["joints"] = brow_joints = [f"{side}_brow{i}" for i in range(1, 6)]

        dm["RightEyelid"]["inner"]["joint"] = f"{side}_inner_eyelidTip"
        dm["RightEyelid"]["outer"]["joint"] = f"{side}_outer_eyelidTip"
        dm["RightEyelid"]["joints"] = [
            f"{side}_inner_eyelidTip",
            f"{side}_upper_eyelidTip11", f"{side}_upper_eyelidTip10", f"{side}_upper_eyelidTip9",
            f"{side}_upper_eyelidTip8", f"{side}_upper_eyelidTip7", f"{side}_upper_eyelidTip6",
            f"{side}_upper_eyelidTip5", f"{side}_upper_eyelidTip4", f"{side}_upper_eyelidTip3",
            f"{side}_upper_eyelidTip2", f"{side}_upper_eyelidTip1",
            f"{side}_outer_eyelidTip",
            f"{side}_lower_eyelidTip1", f"{side}_lower_eyelidTip2", f"{side}_lower_eyelidTip3",
            f"{side}_lower_eyelidTip4", f"{side}_lower_eyelidTip5", f"{side}_lower_eyelidTip6",
            f"{side}_lower_eyelidTip7", f"{side}_lower_eyelidTip8", f"{side}_lower_eyelidTip9"
        ]

        # ---------- Lips ----------
        dm["LipChain"]["joints"] = [
            'c_upper_lip', 'r_upper_lip4', 'r_upper_lip3', 'r_upper_lip2', 'r_upper_lip1',
            'r_lip_corner1', 'r_lower_lip1', 'r_lower_lip2', 'r_lower_lip3', 'r_lower_lip4',
            'c_lower_lip', 'l_lower_lip4', 'l_lower_lip3', 'l_lower_lip2', 'l_lower_lip1',
            'l_lip_corner1', 'l_upper_lip1', 'l_upper_lip2', 'l_upper_lip3', 'l_upper_lip4'
        ]
        dm["UpperLipCenter"]["joint"] = "c_upper_lip"
        dm["LowerLipCenter"]["joint"] = "c_lower_lip"
        dm["LeftLipCorner"]["joint"] = "l_lip_corner1"
        dm["RightLipCorner"]["joint"] = "r_lip_corner1"

        # ---------- Jaw ----------
        dm["Jaw"]["joint"] = "jaw"

        # ---------- Tongue ----------
        dm["TongueChain"]["joints"] = ["tongue1", "tongue2", "tongue3", "tongue4"]

        # ---------- Teeth ----------
        dm["UpperTeeth"]["joint"] = "upper_teeth"
        dm["LowerTeeth"]["joint"] = "lower_teeth"

        # ---------- Eyes ----------
        dm["LeftEye"]["joint"] = "l_eye"
        dm["RightEye"]["joint"] = "r_eye"

        # ---------- Nose ----------
        dm["NoseRoot"]["joint"] = "nose_root"

        # ---------- Other Face Joints ----------
        dm["OtherFaceJoints"]["joints"] = [
            'r_undereye_3', 'r_undereye_4', 'r_undereye_5', 'r_undereye_1',
            'r_ear_base1', 'r_ear_base', 'l_upper_cheek', 'r_undereye_2',
            'l_lower_cheek', 'l_inner_cheek', 'r_upper_nose',
            'l_inner_cheek_smile', 'r_inner_cheek_smile', 'r_inner_cheek',
            'r_upper_cheek', 'r_lower_cheek',
            'r_undereye_8', 'r_undereye_7', 'r_undereye_6',
            'l_undereye_8', 'l_undereye_7', 'l_undereye_6',
            'l_undereye_5', 'l_undereye_4', 'l_undereye_3',
            'l_undereye_2', 'l_undereye_1',
            'l_ear_base1', 'l_upper_nose', 'l_ear_base'
        ]
        self.default_face_map = dm

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

        # Reset session overrides
        self._session_parent_override = None
        self._use_override_for_all = False

        still_empty = [slot for slot in self.default_map if not self.fields.get(slot)]
        if still_empty:
            msg = f"The following HumanIK slots are still unmapped:\n{', '.join(still_empty)}\n\nDo you want to proceed and build the rig anyway?"
            res = cmds.confirmDialog(
                title="Unmapped Slots Notice",
                message=msg,
                button=["Proceed", "Cancel"],
                defaultButton="Proceed",
                cancelButton="Cancel"
            )
            if res == "Cancel":
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

        # Force eyelids to build last no matter where they are listed above.
        eyelid_modules = ["Eyelids (Left)", "Eyelids (Right)"]
        all_modules = [m for m in all_modules if m not in eyelid_modules]
        all_modules.extend(eyelid_modules)

        cmds.undoInfo(openChunk=True, chunkName="Build Full Rig")
        built_modules = []
        skipped_modules = []
        try:
            for module in all_modules:
                print(module)
                # Check if joints exist in scene
                if module in ["Brows (Left)", "Brows (Right)", "Eyes Aim", "Eyelids (Left)", "Eyelids (Right)", "Mouth & Lips", "Tongue", "Teeth", "Other Face Joints"]:
                    jnts = self._get_face_module_joints(module)
                else:
                    jnts = self._get_module_joints(module)
                
                # Check if any joints exist for modules that map explicitly to joints
                if module not in ["Mouth & Lips", "Other Face Joints", "Teeth", "Tongue", "Eyes Aim"]:
                    existing_jnts = [j for j in jnts if j and cmds.objExists(j)]
                    if not existing_jnts:
                        skipped_modules.append(module)
                        continue

                # Build module silently
                if module in ["Brows (Left)", "Brows (Right)", "Eyes Aim", "Eyelids (Left)", "Eyelids (Right)", "Mouth & Lips", "Tongue", "Teeth", "Other Face Joints"]:
                    self.create_face_module_setup(module, silent=True)
                else:
                    self.create_body_module_setup(module, silent=True)
                built_modules.append(module)

            # Recreate all spaces and composite spaces once at the end
            for s in ("l", "r"):
                create_rig.create_arm_space_switches(s)
                create_rig.create_leg_space_switches(s)

            # Cleanup orphaned main/temp nodes
            create_rig.delete_unused_scaffold_nodes()

            # Store connections once at the very end
            self.store_all_face_connections(silent=True)

            summary = f"Full Rig Build Completed!\n\nBuilt Modules ({len(built_modules)}):\n" + ", ".join(built_modules)
            if skipped_modules:
                summary += f"\n\nSkipped Modules (joints not in scene) ({len(skipped_modules)}):\n" + ", ".join(skipped_modules)
            cmds.confirmDialog(title="Success", message=summary, button=["OK"])

        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create full rig:\n{e}", button=["OK"])
            cmds.warning(f"Failed to create full rig: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def remove_full_rig(self):
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
            create_rig.remove_full_rig(self.default_map, self.default_face_map)
            cmds.confirmDialog(title="Success", message="Full Rig removed successfully!", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove full rig:\n{e}", button=["OK"])
            cmds.warning(f"Failed to remove full rig: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)
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
        #self._build_face_rig_section(self.rig_layout)
        self._refresh_all_module_details()

    def get_uproject(self, directory):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Unreal Project", directory,
                                                             "Unreal Project (*.uproject)")
        if file_name:
            return file_name.replace('\\', '/')
        return None

    def guess_joint_map_from_root(self, root_joint):
        if not cmds.objExists(root_joint):
            return {}

        # Reset any existing joint mappings to avoid stale cache from previous runs
        for key in self.default_map:
            self.default_map[key]["joint"] = ""

        def is_twist_bone(name):
            return "twist" in name or "roll" in name

        joint_map = self.default_map
        all_joints = cmds.listRelatives(root_joint, ad=True, type="joint") or []
        all_joints = list(reversed(all_joints))
        all_joints.insert(0, root_joint)

        spines = []
        necks = []

        fingers = {
            "Left": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []},
            "Right": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []}
        }

        # Check if upperarm joint exists to distinguish shoulder vs upperarm
        has_l_upperarm = any("l_upper" in j.lower() or "upper_l" in j.lower() or "l_arm" in j.lower() or "arm_l" in j.lower() or "l_upperarm" in j.lower() or "upperarm_l" in j.lower() for j in all_joints)
        has_r_upperarm = any("r_upper" in j.lower() or "upper_r" in j.lower() or "r_arm" in j.lower() or "arm_r" in j.lower() or "r_upperarm" in j.lower() or "upperarm_r" in j.lower() for j in all_joints)

        twist_map = {
            # arms
            "upperarm": ("ArmRoll", 3),
            "lowerarm": ("ForeArmRoll", 3),
            # legs
            "thigh": ("UpLegRoll", 3),
            "knee": ("LegRoll", 2),
        }
        side_prefix = {"l": "Left", "r": "Right"}

        for jnt in all_joints:
            name = jnt.lower()

            def set_slot(slot):
                if slot in joint_map and not joint_map[slot].get("joint"):
                    joint_map[slot]["joint"] = jnt

            # 1. Twist joints mapping
            is_twist = is_twist_bone(name)
            if is_twist:
                for side in ("l", "r"):
                    for limb, (slot_base, count) in twist_map.items():
                        if limb in name:
                            # Match side prefix or suffix
                            is_side = False
                            if side == "l":
                                is_side = name.startswith("l_") or "l_upper" in name or "l_lower" in name or name.endswith("_l") or "_l_" in name or "left" in name
                            else:
                                is_side = name.startswith("r_") or "r_upper" in name or "r_lower" in name or name.endswith("_r") or "_r_" in name or "right" in name
                            
                            if is_side:
                                match = re.search(r'(\d+)', name)
                                num = int(match.group(1)) if match else 1
                                
                                slot_base_fixed = slot_base.replace('ForeArm', "Forearm")
                                if num == 1:
                                    joint_map_key = f"{side_prefix[side]}{slot_base}"
                                    if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                        joint_map[joint_map_key]["joint"] = jnt
                                else:
                                    leaf_idx = num - 1
                                    joint_map_key = f"Leaf{side_prefix[side]}{slot_base_fixed}{leaf_idx}"
                                    if joint_map_key in joint_map and not joint_map[joint_map_key].get("joint"):
                                        joint_map[joint_map_key]["joint"] = jnt
                continue

            # 2. Main skeleton joints mapping
            if "spine" in name or "spn" in name:
                spines.append(jnt)

            elif "origin" in name or "root" in name:
                set_slot("Reference")

            elif "pelvis" in name:
                set_slot("Hips")

            elif "hipswing" in name or "hip_swing" in name:
                set_slot("HipSwing")

            elif "l_clavicle" in name or "clavicle_l" in name or ("l_shoulder" in name and has_l_upperarm):
                set_slot("LeftShoulder")
            elif ("l_upper" in name or "upper_l" in name or "l_upperarm" in name or "upperarm_l" in name or "l_upper_arm" in name or "upper_arm_l" in name or ("l_shoulder" in name and not has_l_upperarm) or "l_arm" in name or "arm_l" in name):
                set_slot("LeftArm")
            elif ("l_lower" in name or "lower_l" in name or "l_lowerarm" in name or "lowerarm_l" in name or "l_lower_arm" in name or "lower_arm_l" in name or "l_forearm" in name or "forearm_l" in name or "l_elbow" in name):
                set_slot("LeftForeArm")

            elif "l_hand" in name or "hand_l" in name and "ik" not in name:
                set_slot("LeftHand")

            elif "r_clavicle" in name or "clavicle_r" in name or ("r_shoulder" in name and has_r_upperarm):
                set_slot("RightShoulder")
            elif ("r_upper" in name or "upper_r" in name or "r_upperarm" in name or "upperarm_r" in name or "r_upper_arm" in name or "upper_arm_r" in name or ("r_shoulder" in name and not has_r_upperarm) or "r_arm" in name or "arm_r" in name):
                set_slot("RightArm")
            elif ("r_lower" in name or "lower_r" in name or "r_lowerarm" in name or "lowerarm_r" in name or "r_lower_arm" in name or "lower_arm_r" in name or "r_forearm" in name or "forearm_r" in name or "r_elbow" in name):
                set_slot("RightForeArm")

            elif "r_hand" in name or "hand_r" in name and "ik" not in name:
                set_slot("RightHand")

            elif ("l_thigh" in name or "thigh_l" in name or "l_upperleg" in name):
                set_slot("LeftUpLeg")

            elif ("l_knee" in name or "knee_l" in name or "calf_l" in name or "l_lowerleg" in name):
                set_slot("LeftLeg")

            elif "l_ankle" in name or "ankle_l" in name or "foot_l" in name and "ik" not in name:
                set_slot("LeftFoot")

            elif "l_toe" in name and "tip" not in name or "ball_l" in name:
                set_slot("LeftToeBase")

            elif ("r_thigh" in name or "thigh_r" in name or "r_upperleg" in name):
                set_slot("RightUpLeg")

            elif ("r_knee" in name or "knee_r" in name or "calf_r" in name or "r_lowerleg" in name):
                set_slot("RightLeg")

            elif "r_ankle" in name or "ankle_r" in name or "foot_r" in name and "ik" not in name:
                set_slot("RightFoot")
            elif "r_toe" in name and "tip" not in name or "ball_r" in name:
                set_slot("RightToeBase")

            if "neck" in name:
                necks.append(jnt)
            elif "head" in name:
                set_slot("Head")

            for side_prefix_str, side in [("l_", "Left"), ("r_", "Right")]:
                if name.startswith(side_prefix_str):
                    for finger in fingers[side].keys():
                        if finger.lower() in name:
                            fingers[side][finger].append(jnt)
                elif name.endswith("_" + side[0].lower()):
                    for finger in fingers[side].keys():
                        if not len(fingers[side][finger]):
                            if cmds.objExists(f"{finger.lower()}_metacarpal_{side[0].lower()}"):
                                fingers[side][finger].append(f"{finger.lower()}_metacarpal_{side[0].lower()}")
                            if cmds.objExists(f"{finger.lower()}_01_{side[0].lower()}"):
                                fingers[side][finger].append(f"{finger.lower()}_01_{side[0].lower()}")
                                fingers[side][finger].append(f"{finger.lower()}_02_{side[0].lower()}")
                                fingers[side][finger].append(f"{finger.lower()}_03_{side[0].lower()}")

        for i, spine in enumerate(spines):
            key = "Spine" if i == 0 else f"Spine{i}"
            if key in joint_map and not joint_map[key].get("joint"):
                joint_map[key]["joint"] = spine

        for i, neck in enumerate(necks):
            key = "Neck" if i == 0 else f"Neck{i}"
            if key in joint_map and not joint_map[key].get("joint"):
                joint_map[key]["joint"] = neck

        for side in ["Left", "Right"]:
            for finger in ["Thumb", "Index", "Middle", "Ring", "Pinky"]:
                joints_list = fingers[side][finger]
                if not joints_list:
                    continue
                if "_metacarpal_" not in joints_list[0]:
                    joints_sorted = sorted(joints_list, key=lambda x: x.lower())
                else:
                    joints_sorted = joints_list
                if "Thumb" not in finger:
                    in_hand_key = f"{side}InHand{finger}"
                    if in_hand_key in joint_map and not joint_map[in_hand_key].get("joint"):
                        joint_map[in_hand_key]["joint"] = joints_sorted[0]
                else:
                    if len(joints_list) > 4:
                        thumb4_key = f"{side}Hand{finger}4"
                    else:
                        thumb4_key = f"{side}Hand{finger}3"
                    joint_map[thumb4_key]["joint"] = joints_sorted[-1]
                for i in range(1, min(5, len(joints_sorted))):
                    num = i
                    if "Thumb" in finger:
                        num = i - 1
                    key = f"{side}Hand{finger}{i}"
                    if key in joint_map and not joint_map[key].get("joint"):
                        joint_map[key]["joint"] = joints_sorted[num]
        # Refresh the face map after assignment
        self.populate_default_face_map_from_scene()
        return joint_map

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
        
        modules_controls = {
            "Left Arm": ["l_upperarm_fk_ctrl", "l_lowerarm_fk_ctrl", "l_hand_fk_ctrl", "l_hand_ik_ctrl", "l_lowerarm_pv_ctrl", "l_hand_switch_ctrl"],
            "Right Arm": ["r_upperarm_fk_ctrl", "r_lowerarm_fk_ctrl", "r_hand_fk_ctrl", "r_hand_ik_ctrl", "r_lowerarm_pv_ctrl", "r_hand_switch_ctrl"],
            "Left Leg": ["l_thigh_fk_ctrl", "l_knee_fk_ctrl", "l_ankle_fk_ctrl", "l_ankle_ik_ctrl", "l_knee_pv_ctrl", "l_ankle_switch_ctrl"],
            "Right Leg": ["r_thigh_fk_ctrl", "r_knee_fk_ctrl", "r_ankle_fk_ctrl", "r_ankle_ik_ctrl", "r_knee_pv_ctrl", "r_ankle_switch_ctrl"],
            "Brows (Left)": ["l_brow_main_ctrl"] + [f"l_brow{i}_ctrl" for i in range(1, 6)],
            "Brows (Right)": ["r_brow_main_ctrl"] + [f"r_brow{i}_ctrl" for i in range(1, 6)],
            "Eyes Aim": ["eye_aim_ctrl", "l_eye_aim_ctrl", "r_eye_aim_ctrl"],
            "Eyelids (Left)": [f"{jnt}_ctrl" for jnt in self.default_face_map.get("LeftEyelid", {}).get("joints", [])],
            "Eyelids (Right)": [f"{jnt}_ctrl" for jnt in self.default_face_map.get("RightEyelid", {}).get("joints", [])],
            "Mouth & Lips": [
                f"{self.default_face_map.get('UpperLipCenter', {}).get('joint') or 'c_upper_lip'}_main_ctrl",
                f"{self.default_face_map.get('LowerLipCenter', {}).get('joint') or 'c_lower_lip'}_main_ctrl",
                f"{self.default_face_map.get('LeftLipCorner', {}).get('joint') or 'l_lip_corner1'}_main_ctrl",
                f"{self.default_face_map.get('RightLipCorner', {}).get('joint') or 'r_lip_corner1'}_main_ctrl"
            ] + [f"{jnt}_ctrl" for jnt in self.default_face_map.get("LipChain", {}).get("joints", [])],
            "Tongue": [f"{jnt}_ctrl" for jnt in self.default_face_map.get("TongueChain", {}).get("joints", [])],
            "Teeth": [
                f"{self.default_face_map.get('UpperTeeth', {}).get('joint') or 'upper_teeth'}_ctrl",
                f"{self.default_face_map.get('LowerTeeth', {}).get('joint') or 'lower_teeth'}_ctrl"
            ],
            "Other Face Joints": [f"{jnt}_ctrl" for jnt in self.default_face_map.get("OtherFaceJoints", {}).get("joints", [])]
        }
        
        stored_modules = []
        for name, ctrls in modules_controls.items():
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
            return [self.fields.get("LeftUpLeg"), self.fields.get("LeftLeg"), self.fields.get("LeftFoot"), self.fields.get("LeftToeBase")]
        elif module == "Right Leg":
            return [self.fields.get("RightUpLeg"), self.fields.get("RightLeg"), self.fields.get("RightFoot"), self.fields.get("RightToeBase")]
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
            if self._use_override_for_all and self._session_parent_override and cmds.objExists(self._session_parent_override):
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
                            cmds.confirmDialog(title="Error", message="Nothing selected. Please select a node in the scene.", button=["OK"])
                    else:
                        return

        self.create_rig_mapping()
        cmds.undoInfo(openChunk=True, chunkName=f"Build Body Module: {module}")
        try:
            if module == "Left Arm":
                create_rig.rig_arm_module("l", self.default_map, parent)
            elif module == "Right Arm":
                create_rig.rig_arm_module("r", self.default_map, parent)
            elif module == "Left Clavicle":
                create_rig.rig_clavicle_module("l", self.default_map, parent)
            elif module == "Right Clavicle":
                create_rig.rig_clavicle_module("r", self.default_map, parent)
            elif module == "Left Leg":
                create_rig.rig_leg_module("l", self.default_map, parent)
            elif module == "Right Leg":
                create_rig.rig_leg_module("r", self.default_map, parent)
            elif module == "Root / Origin":
                create_rig.rig_root_module(self.default_map)
            elif module == "Pelvis & Hips":
                create_rig.rig_pelvis_module(self.default_map, parent)
            elif module == "Spine":
                create_rig.rig_spine_module(self.default_map, parent)
            elif module == "Neck":
                create_rig.rig_neck_module(self.default_map, parent)
            elif module == "Head":
                create_rig.rig_head_module(self.default_map, self.default_face_map, parent)

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
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create body module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def remove_body_module_setup(self, module):
        self.create_rig_mapping()
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

            cmds.confirmDialog(title="Success", message=f"Body Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove body module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def create_face_module_setup(self, module, silent=False):
        edit_info = self._module_detail_widgets.get(module)
        parent = None
        if edit_info and edit_info.get("parent_edit"):
            parent = edit_info["parent_edit"].text().strip() or None
        if not parent:
            parent = self.module_parent_field.text().strip() or None
        if not parent or not cmds.objExists(parent):
            if self._use_override_for_all and self._session_parent_override and cmds.objExists(self._session_parent_override):
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
                            cmds.confirmDialog(title="Error", message="Nothing selected. Please select a node in the scene.", button=["OK"])
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

            # Save metadata for face module so it is kept in rig_module_store node!
            face_joints = self._get_face_module_joints(module)
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
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to create face module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()

    def remove_face_module_setup(self, module):
        self.create_rig_mapping()
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

            cmds.confirmDialog(title="Success", message=f"Face Module '{module}' removed successfully!\nDeleted {deleted_count} rig nodes.", button=["OK"])
        except Exception as e:
            cmds.confirmDialog(title="Error", message=f"Failed to remove face module setup:\n{e}", button=["OK"])
        finally:
            cmds.undoInfo(closeChunk=True)
            self._load_module_metadata_from_scene()
            self._refresh_all_module_details()


    def load_settings_from_selection(self):
        sel = cmds.ls(sl=True)
        if not sel:
            cmds.confirmDialog(title="Info", message="Please select a control or joint in the scene first.", button=["OK"])
            return

        node = sel[0]
        node_lower = node.lower()
        is_body = any(t in node_lower for t in ["upperarm", "lowerarm", "hand", "clavicle", "thigh", "knee", "ankle", "toe", "foot", "leg", "arm"])

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
        "Root / Origin":    ["origin_ctrl"],
        "Pelvis & Hips":    ["pelvis_ctrl", "hipswing_ctrl"],
        "Spine":            ["spine1_ctrl", "spine3_ctrl", "spine5_ctrl"],
        "Left Clavicle":    ["l_clavicle_ctrl"],
        "Right Clavicle":   ["r_clavicle_ctrl"],
        "Neck":             ["neck1_ctrl", "neck2_ctrl"],
        "Head":             ["head1_ctrl"],
        "Left Arm":         ["l_upperarm_fk_ctrl", "l_hand_switch_ctrl"],
        "Right Arm":        ["r_upperarm_fk_ctrl", "r_hand_switch_ctrl"],
        "Left Leg":         ["l_thigh_fk_ctrl", "l_ankle_switch_ctrl"],
        "Right Leg":        ["r_thigh_fk_ctrl", "r_ankle_switch_ctrl"],
        "Brows (Left)":     ["l_brow_main_ctrl", "l_brow1_ctrl"],
        "Brows (Right)":    ["r_brow_main_ctrl", "r_brow1_ctrl"],
        "Eyelids (Left)":   ["l_eyelid_main_ctrl", "l_upper_eyelid1_ctrl"],
        "Eyelids (Right)":  ["r_eyelid_main_ctrl", "r_upper_eyelid1_ctrl"],
        "Mouth & Lips":     ["c_upper_lip_main_ctrl", "l_lip_corner1_main_ctrl"],
        "Eyes Aim":         ["eye_aim_ctrl", "l_eye_aim_ctrl"],
        "Tongue":           ["tongue1_ctrl"],
        "Teeth":            ["upper_teeth_ctrl"],
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
        edit.textChanged.connect(lambda text: self._save_custom_space_switches(module_id, ctrl_name, [t.strip() for t in text.split(",") if t.strip()]))
        
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
            jaw_ctrl_btn.setStyleSheet("color: #777777; font-size: 8pt; border: none; padding: 0 2px; text-align: left;")
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

        body_list_names = ["Root / Origin", "Pelvis & Hips", "Spine", "Left Clavicle", "Right Clavicle", "Neck", "Head", "Left Arm", "Right Arm", "Left Leg", "Right Leg"]
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
                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", [("Reference", "Reference")], module_id))
            elif module_id == "Pelvis & Hips":
                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", [("Hips", "Hips"), ("Hip Swing", "HipSwing")], module_id))
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
                slots_hl.addWidget(self._create_joint_slots_group("Main Joints", [("Clavicle", f"{sp}Shoulder")], module_id))
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
                
                sw_lay.addRow("PV Space Targets:", self._create_space_switch_edit_row(f"{side}_lowerarm_pv_ctrl", ["pelvis_ctrl", "origin_ctrl", f"{side}_clavicle_ctrl", f"{side}_arm_pv_handClav_space"], module_id))
                sw_lay.addRow("FK Space Targets:", self._create_space_switch_edit_row(f"{side}_upperarm_fk_ctrl", [f"{side}_clavicle_ctrl", "pelvis_ctrl", "origin_ctrl"], module_id))
                sw_lay.addRow("IK Space Targets:", self._create_space_switch_edit_row(f"{side}_hand_ik_ctrl", [f"{side}_clavicle_ctrl", "spine5_Tip_ctrl", "pelvis_ctrl", "origin_ctrl"], module_id))
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
                
                sw_lay.addRow("PV Space Targets:", self._create_space_switch_edit_row(f"{side}_knee_pv_ctrl", ["pelvis_ctrl", f"{side}_ankle_ik_ctrl", "origin_ctrl", f"{side}_leg_pv_footHip_space"], module_id))
                sw_lay.addRow("FK Space Targets:", self._create_space_switch_edit_row(f"{side}_thigh_fk_ctrl", ["pelvis_ctrl", "origin_ctrl"], module_id))
                sw_lay.addRow("IK Space Targets:", self._create_space_switch_edit_row(f"{side}_ankle_ik_ctrl", ["pelvis_ctrl", "origin_ctrl"], module_id))
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
                lists_hl.addWidget(self._create_face_list_block("Right Inner Eyelid", ("RightEyelid", "inner", "joint")))
                lists_hl.addWidget(self._create_face_list_block("Right Outer Eyelid", ("RightEyelid", "outer", "joint")))
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
        info = self._module_detail_widgets.get(module_id)
        if not info:
            return

        meta = create_rig.load_module_metadata(module_id)
        built = meta.get("built", False)

        status_lbl = info["status_lbl"]
        parent_btn = info["parent_btn"]
        spaces_container = info["spaces_container"]
        built_view = info["built_view"]
        edit_view = info["edit_view"]

        # Find the first existing control in scene for this module
        main_ctrl = self._get_first_existing_ctrl(module_id, meta)

        # Sync Create / Remove button enabled state with scene presence
        module_exists = main_ctrl is not None
        
        if module_id == "Other Face Joints" and built and not main_ctrl:
            module_exists = True

        # Toggle Built View vs Edit View
        if module_exists:
            built_view.setVisible(True)
            edit_view.setVisible(False)
        else:
            built_view.setVisible(False)
            edit_view.setVisible(True)

            # Populate fields from metadata first so we recover parent and joints
            self._populate_fields_from_metadata(module_id, meta)

            # Initialize / refresh editable fields
            body_list_names = ["Root / Origin", "Pelvis & Hips", "Spine", "Left Clavicle", "Right Clavicle", "Neck", "Head", "Left Arm", "Right Arm", "Left Leg", "Right Leg"]
            if info.get("parent_edit") and not info["parent_edit"].text().strip():
                default_parent = self.body_parent_field.text().strip() if module_id in body_list_names else self.module_parent_field.text().strip()
                info["parent_edit"].setText(default_parent)
            if info.get("jaw_ctrl_edit") and not info["jaw_ctrl_edit"].text().strip():
                info["jaw_ctrl_edit"].setText(self.module_jaw_ctrl_field.text().strip())
            if info.get("jaw_jnt_edit") and not info["jaw_jnt_edit"].text().strip():
                info["jaw_jnt_edit"].setText(self.module_jaw_jnt_field.text().strip())

            # Now update the slot QLineEdit text boxes with the values from self.fields
            for slot_key, widget in self._slot_edit_widgets.items():
                widget.setText(self.fields.get(slot_key, ""))

        create_btn = self.module_create_buttons.get(module_id)
        if create_btn:
            create_btn.setEnabled(not module_exists)
            if module_exists:
                create_btn.setStyleSheet(
                    "background-color: #1e3a20; color: #557755; font-weight: bold; "
                    "border: 1px solid #335533;")
                create_btn.setToolTip(f"Module already exists in scene. Remove it first to rebuild.")
            else:
                create_btn.setStyleSheet("background-color: #2e6930; color: white; font-weight: bold;")
                create_btn.setToolTip(f"Build this module setup.")
        remove_btn = self.module_remove_buttons.get(module_id)
        if remove_btn:
            remove_btn.setEnabled(module_exists)
            if not module_exists:
                remove_btn.setStyleSheet(
                    "background-color: #3a1e1e; color: #775555; font-weight: bold; "
                    "border: 1px solid #553333;")
                remove_btn.setToolTip("Module does not exist in scene — nothing to remove.")
            else:
                remove_btn.setStyleSheet("background-color: #7d2a2a; color: white; font-weight: bold;")
                remove_btn.setToolTip(f"Remove this module setup.")

        # ---- Status indicator ----
        if main_ctrl:
            status_lbl.setText("\u25cf")
            status_lbl.setStyleSheet("color: #55cc66; font-size: 10pt;")  # green = built & in scene
        elif built:
            status_lbl.setText("\u26a0")
            status_lbl.setStyleSheet("color: #cc9933; font-size: 10pt;")  # amber = built but missing
        else:
            status_lbl.setText("\u25cb")
            status_lbl.setStyleSheet("color: #555555; font-size: 10pt;")  # grey = not built

        # ---- Parent button ----
        if main_ctrl:
            parent_node = self._get_ctrl_scene_parent(main_ctrl)
            if parent_node:
                parent_btn.setText(parent_node)
                parent_btn.setEnabled(True)
                color = "#6699cc" if cmds.objExists(parent_node) else "#cc6666"
                parent_btn.setStyleSheet(
                    f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
                    f"text-decoration: underline; text-align: left;"
                )
                try:
                    parent_btn.clicked.disconnect()
                except RuntimeError:
                    pass
                parent_btn.clicked.connect(
                    lambda checked=False, n=parent_node: self._select_node(n)
                )
            else:
                parent_btn.setText("\u2014")
                parent_btn.setEnabled(False)
                parent_btn.setStyleSheet("color: #777777; font-size: 8pt; border: none; padding: 0 2px;")
        else:
            parent_btn.setText("not in scene" if built else "\u2014")
            parent_btn.setEnabled(False)
            parent_btn.setStyleSheet("color: #666666; font-size: 8pt; font-style: italic; border: none; padding: 0 2px;")

        # ---- Jaw Info if applicable ----
        if main_ctrl and module_id in ["Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"]:
            jaw_ctrl_val = meta.get("jaw_ctrl")
            jaw_jnt_val = meta.get("jaw_jnt")
            
            if info["jaw_ctrl_btn"]:
                if jaw_ctrl_val:
                    info["jaw_ctrl_btn"].setText(jaw_ctrl_val)
                    info["jaw_ctrl_btn"].setEnabled(True)
                    color = "#6699cc" if cmds.objExists(jaw_ctrl_val) else "#cc6666"
                    info["jaw_ctrl_btn"].setStyleSheet(f"color: {color}; font-size: 8pt; border: none; text-decoration: underline; text-align: left;")
                    try:
                        info["jaw_ctrl_btn"].clicked.disconnect()
                    except:
                        pass
                    info["jaw_ctrl_btn"].clicked.connect(lambda checked=False, n=jaw_ctrl_val: self._select_node(n))
                else:
                    info["jaw_ctrl_btn"].setText("\u2014")
                    info["jaw_ctrl_btn"].setEnabled(False)
                    info["jaw_ctrl_btn"].setStyleSheet("color: #777777; font-size: 8pt; border: none;")

            if info["jaw_jnt_btn"]:
                if jaw_jnt_val:
                    info["jaw_jnt_btn"].setText(jaw_jnt_val)
                    info["jaw_jnt_btn"].setEnabled(True)
                    color = "#6699cc" if cmds.objExists(jaw_jnt_val) else "#cc6666"
                    info["jaw_jnt_btn"].setStyleSheet(f"color: {color}; font-size: 8pt; border: none; text-decoration: underline; text-align: left;")
                    try:
                        info["jaw_jnt_btn"].clicked.disconnect()
                    except:
                        pass
                    info["jaw_jnt_btn"].clicked.connect(lambda checked=False, n=jaw_jnt_val: self._select_node(n))
                else:
                    info["jaw_jnt_btn"].setText("\u2014")
                    info["jaw_jnt_btn"].setEnabled(False)
                    info["jaw_jnt_btn"].setStyleSheet("color: #777777; font-size: 8pt; border: none;")

        # ---- Mapped Joints / Twist bones read-only display ----
        jnts = meta.get("joints", [])
        twists_u = []
        twists_l = []
        if "Arm" in module_id:
            twists_u = meta.get("twist_upper", [])
            twists_l = meta.get("twist_lower", [])
        elif "Leg" in module_id:
            twists_u = meta.get("twist_thigh", [])
            twists_l = meta.get("twist_knee", [])
        
        mapped_texts = []
        if jnts:
            mapped_texts.append("Joints: " + ", ".join([j.split("|")[-1] for j in jnts if j]))
        if twists_u:
            mapped_texts.append("Upper Twist: " + ", ".join([j.split("|")[-1] for j in twists_u if j]))
        if twists_l:
            mapped_texts.append("Lower Twist: " + ", ".join([j.split("|")[-1] for j in twists_l if j]))
            
        if mapped_texts:
            info["mapped_joints_lbl"].setText("\n".join(mapped_texts))
        else:
            info["mapped_joints_lbl"].setText("\u2014")

        # ---- Spaces / connections section — rebuild ----
        self._clear_widget_layout(spaces_container.layout())

        # Collect all controls associated with this module
        controls_to_check = []
        if "Arm" in module_id:
            side = "l" if "Left" in module_id else "r"
            controls_to_check = [
                (f"{side}_upperarm_fk_ctrl", "FK"),
                (f"{side}_hand_ik_ctrl", "IK"),
                (f"{side}_lowerarm_pv_ctrl", "PV")
            ]
        elif "Leg" in module_id:
            side = "l" if "Left" in module_id else "r"
            controls_to_check = [
                (f"{side}_thigh_fk_ctrl", "FK"),
                (f"{side}_ankle_ik_ctrl", "IK"),
                (f"{side}_knee_pv_ctrl", "PV")
            ]
        else:
            if main_ctrl:
                controls_to_check = [(main_ctrl, "")]

        # Query all spaces first
        has_spaces = False
        first_section = True
        
        for ctrl, label in controls_to_check:
            if not cmds.objExists(ctrl):
                continue
            space_targets = self._get_space_targets(ctrl)
            if space_targets:
                has_spaces = True
                if first_section:
                    sep_lbl = QtWidgets.QLabel("|")
                    sep_lbl.setStyleSheet("color: #444444; font-size: 8pt;")
                    spaces_container.layout().addWidget(sep_lbl)
                    first_section = False
                else:
                    section_sep = QtWidgets.QLabel("  ")
                    spaces_container.layout().addWidget(section_sep)

                hdr_text = f"{label} Spaces →" if label else "Spaces →"
                sw_hdr = QtWidgets.QLabel(hdr_text)
                sw_hdr.setStyleSheet("color: #999999; font-weight: bold; font-size: 8pt;")
                spaces_container.layout().addWidget(sw_hdr)

                for opt, target in space_targets:
                    t_btn = QtWidgets.QPushButton(opt)
                    t_btn.setFlat(True)
                    exists = target and cmds.objExists(target)
                    color = "#aa88cc" if exists else "#cc6666"
                    t_btn.setStyleSheet(
                        f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
                        f"text-decoration: underline;"
                    )
                    t_btn.setCursor(QtCore.Qt.PointingHandCursor)
                    if exists:
                        t_btn.setToolTip(f"Click to select the space switch target '{target}' in the Maya scene.")
                        t_btn.clicked.connect(lambda checked=False, n=target: self._select_node(n))
                    else:
                        t_btn.setToolTip(f"Target node '{target}' does not exist in the scene.")
                        t_btn.setEnabled(False)
                    spaces_container.layout().addWidget(t_btn)

        # Query incoming driven connections on main_ctrl
        if main_ctrl:
            driven_by = self._get_incoming_connections(main_ctrl)
            if driven_by:
                if has_spaces or not first_section:
                    conn_sep = QtWidgets.QLabel("|")
                    conn_sep.setStyleSheet("color: #444444; font-size: 8pt;")
                    spaces_container.layout().addWidget(conn_sep)
                
                conn_hdr = QtWidgets.QLabel("Driven by \u2192")
                conn_hdr.setStyleSheet("color: #999999; font-weight: bold; font-size: 8pt;")
                spaces_container.layout().addWidget(conn_hdr)

                for n in driven_by[:3]:  # cap at 3 to avoid overflow
                    n_btn = QtWidgets.QPushButton(n)
                    n_btn.setFlat(True)
                    exists = cmds.objExists(n)
                    color = "#cc8844" if exists else "#cc6666"
                    n_btn.setStyleSheet(
                        f"color: {color}; font-size: 8pt; border: none; padding: 0 2px; "
                        f"text-decoration: underline;"
                    )
                    n_btn.setCursor(QtCore.Qt.PointingHandCursor)
                    n_btn.setToolTip(f"Click to select the driving node '{n}' in the Maya scene.")
                    n_btn.clicked.connect(lambda checked=False, n_=n: self._select_node(n_))
                    spaces_container.layout().addWidget(n_btn)

    def _refresh_all_module_details(self):
        """Refresh the detail widget for every registered module."""
        for module_id in list(self._module_detail_widgets.keys()):
            try:
                self._refresh_module_detail_widget(module_id)
            except Exception as e:
                cmds.warning(f"[HIK UI] Could not refresh detail for '{module_id}': {e}")

    def _populate_fields_from_metadata(self, module_id, meta):
        if not meta:
            return
        
        # Helper to set if empty
        def set_field_if_empty(slot, value):
            if slot in self.fields and not self.fields[slot]:
                self.fields[slot] = value

        # 1. Parent control
        p = meta.get("parent")
        if p and cmds.objExists(p):
            info = self._module_detail_widgets.get(module_id)
            if info and info.get("parent_edit") and not info["parent_edit"].text().strip():
                info["parent_edit"].setText(p)

        # 2. Jaw controls/joints for face modules
        if module_id in ["Mouth & Lips", "Teeth", "Tongue", "Other Face Joints"]:
            info = self._module_detail_widgets.get(module_id)
            if info:
                jc = meta.get("jaw_ctrl")
                if jc and info.get("jaw_ctrl_edit") and not info["jaw_ctrl_edit"].text().strip():
                    info["jaw_ctrl_edit"].setText(jc)
                jj = meta.get("jaw_jnt")
                if jj and info.get("jaw_jnt_edit") and not info["jaw_jnt_edit"].text().strip():
                    info["jaw_jnt_edit"].setText(jj)

        # 3. Main and twist joint mapping
        jnts = meta.get("joints", [])
        
        if module_id == "Root / Origin" and len(jnts) >= 1:
            set_field_if_empty("Reference", jnts[0])
        elif module_id == "Pelvis & Hips" and len(jnts) >= 1:
            set_field_if_empty("Hips", jnts[0])
            if len(jnts) >= 2:
                set_field_if_empty("HipSwing", jnts[1])
        elif module_id == "Spine":
            for i, j in enumerate(jnts):
                slot = "Spine" if i == 0 else f"Spine{i}"
                set_field_if_empty(slot, j)
        elif "Clavicle" in module_id:
            sp = "Left" if "Left" in module_id else "Right"
            if len(jnts) >= 1:
                set_field_if_empty(f"{sp}Shoulder", jnts[0])
        elif module_id == "Neck":
            for i, j in enumerate(jnts):
                slot = "Neck" if i == 0 else f"Neck{i}"
                set_field_if_empty(slot, j)
        elif module_id == "Head" and len(jnts) >= 1:
            set_field_if_empty("Head", jnts[0])
            
        elif "Arm" in module_id:
            sp = "Left" if "Left" in module_id else "Right"
            # Main chain (Clavicle is now in its own separate module)
            slots = [f"{sp}Arm", f"{sp}ForeArm", f"{sp}Hand"]
            for i, j in enumerate(jnts):
                if i < len(slots):
                    set_field_if_empty(slots[i], j)
            # Twist upper
            tw_u = meta.get("twist_upper", [])
            if tw_u:
                set_field_if_empty(f"{sp}ArmRoll", tw_u[0])
                for i, j in enumerate(tw_u[1:]):
                    set_field_if_empty(f"Leaf{sp}ArmRoll{i+1}", j)
            # Twist lower
            tw_l = meta.get("twist_lower", [])
            if tw_l:
                set_field_if_empty(f"{sp}ForeArmRoll", tw_l[0])
                for i, j in enumerate(tw_l[1:]):
                    set_field_if_empty(f"Leaf{sp}ForearmRoll{i+1}", j)
                    
        elif "Leg" in module_id:
            sp = "Left" if "Left" in module_id else "Right"
            # Main chain
            slots = [f"{sp}UpLeg", f"{sp}Leg", f"{sp}Foot", f"{sp}ToeBase"]
            for i, j in enumerate(jnts):
                if i < len(slots):
                    set_field_if_empty(slots[i], j)
            # Twist thigh (upper)
            tw_u = meta.get("twist_thigh", [])
            if tw_u:
                set_field_if_empty(f"{sp}UpLegRoll", tw_u[0])
                for i, j in enumerate(tw_u[1:]):
                    set_field_if_empty(f"Leaf{sp}UpLegRoll{i+1}", j)
            # Twist knee (lower)
            tw_l = meta.get("twist_knee", [])
            if tw_l:
                set_field_if_empty(f"{sp}LegRoll", tw_l[0])
                for i, j in enumerate(tw_l[1:]):
                    set_field_if_empty(f"Leaf{sp}LegRoll{i+1}", j)

    def _get_first_existing_ctrl(self, module_id, meta=None):
        """Return the first scene-existing control for a module (candidates + metadata fallback)."""
        candidates = list(self._MODULE_CTRL_CANDIDATES.get(module_id, []))
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
            con_nodes.extend(cmds.listRelatives(node, type=["orientConstraint", "parentConstraint", "pointConstraint"]) or [])
            # Also check for duplicate target constraints (e.g. _spaceTarget parent group)
            parents = cmds.listRelatives(node, parent=True) or []
            for p in parents:
                if p.endswith("_spaceTarget"):
                    con_nodes.extend(cmds.listRelatives(p, type=["orientConstraint", "parentConstraint", "pointConstraint"]) or [])

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



    def _load_module_metadata_from_scene(self):
        """Read rig_module_store, check for discrepancies, then refresh all detail widgets."""
        try:
            all_meta = create_rig.get_all_module_metadata()
        except Exception as e:
            cmds.warning(f"[HIK UI] Could not read module metadata: {e}")
            return

        # Key normalisation map — attr key → display name
        key_to_display = {
            "root___origin":    "Root / Origin",
            "pelvis___hips":    "Pelvis & Hips",
            "spine":            "Spine",
            "left_clavicle":    "Left Clavicle",
            "right_clavicle":   "Right Clavicle",
            "neck":             "Neck",
            "head":             "Head",
            "left_arm":         "Left Arm",
            "right_arm":        "Right Arm",
            "left_leg":         "Left Leg",
            "right_leg":        "Right Leg",
            "brows__left_":     "Brows (Left)",
            "brows__right_":    "Brows (Right)",
            "eyelids__left_":   "Eyelids (Left)",
            "eyelids__right_":  "Eyelids (Right)",
            "mouth___lips":     "Mouth & Lips",
            "eyes_aim":         "Eyes Aim",
            "tongue":           "Tongue",
            "teeth":            "Teeth",
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

        if missing_joints:
            lines = [f"  \u2022 [{mod}] {jnt}" for mod, jnt in missing_joints]
            msg = ("The following joints referenced by saved rig modules were "
                   "not found in the current scene:\n\n" + "\n".join(lines) +
                   "\n\nYou may need to re-map or rebuild those modules.")
            cmds.warning("[HIK UI] Module discrepancy detected.")
            cmds.confirmDialog(
                title="Module Discrepancy Warning",
                message=msg,
                button=["OK"],
                icon="warning"
            )

        # Refresh all live detail widgets from the scene
        self._refresh_all_module_details()


def launch_hik_ui():
    global hik_ui_instance
    try:
        hik_ui_instance.close()
        hik_ui_instance.deleteLater()
    except:
        pass
    hik_ui_instance = HIKDefinitionUI()
    hik_ui_instance.show()


if __name__ == "__main__":
    launch_hik_ui()
