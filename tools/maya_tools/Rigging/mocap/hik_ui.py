import os
import json
import maya.cmds as cmds
from maya import OpenMayaUI as omui
from shiboken6 import wrapInstance
from PySide6 import QtWidgets, QtCore, QtGui
from maya_tools.Rigging.mocap import setup_hik
import copy

DEFAULT_JOINT_MAP = {
    "Reference": {"index": 0, "joint": ""},
    "Hips": {"index": 1, "joint": ""},
    "LeftUpLeg": {"index": 2, "joint": ""},
    "LeftLeg": {"index": 3, "joint": ""},
    "LeftFoot": {"index": 4, "joint": ""},
    "LeftToeBase": {"index": 16, "joint": ""},
    "RightUpLeg": {"index": 5, "joint": ""},
    "RightLeg": {"index": 6, "joint": ""},
    "RightFoot": {"index": 7, "joint": ""},
    "RightToeBase": {"index": 17, "joint": ""},
    "Spine": {"index": 8, "joint": ""},
    "Spine1": {"index": 23, "joint": ""},
    "Spine2": {"index": 24, "joint": ""},
    "Spine3": {"index": 25, "joint": ""},
    "Neck": {"index": 20, "joint": ""},
    "Neck1": {"index": 32, "joint": ""},
    "Head": {"index": 15, "joint": ""},
    "LeftShoulder": {"index": 18, "joint": ""},
    "LeftArm": {"index": 9, "joint": ""},
    "LeftForeArm": {"index": 10, "joint": ""},
    "LeftHand": {"index": 11, "joint": ""},
    "LeftInHandIndex": {"index": 147, "joint": ""},
    "LeftInHandMiddle": {"index": 148, "joint": ""},
    "LeftInHandRing": {"index": 149, "joint": ""},
    "LeftInHandPinky": {"index": 150, "joint": ""},
    "LeftHandThumb1": {"index": 50, "joint": ""},
    "LeftHandIndex1": {"index": 54, "joint": ""},
    "LeftHandMiddle1": {"index": 58, "joint": ""},
    "LeftHandRing1": {"index": 62, "joint": ""},
    "LeftHandPinky1": {"index": 66, "joint": ""},
    "LeftHandThumb2": {"index": 51, "joint": ""},
    "LeftHandIndex2": {"index": 55, "joint": ""},
    "LeftHandMiddle2": {"index": 59, "joint": ""},
    "LeftHandRing2": {"index": 63, "joint": ""},
    "LeftHandPinky2": {"index": 67, "joint": ""},
    "LeftHandThumb3": {"index": 52, "joint": ""},
    "LeftHandIndex3": {"index": 56, "joint": ""},
    "LeftHandMiddle3": {"index": 60, "joint": ""},
    "LeftHandRing3": {"index": 64, "joint": ""},
    "LeftHandPinky3": {"index": 68, "joint": ""},
    "LeftHandThumb4": {"index": 53, "joint": ""},
    "LeftHandIndex4": {"index": 57, "joint": ""},
    "LeftHandMiddle4": {"index": 61, "joint": ""},
    "LeftHandRing4": {"index": 65, "joint": ""},
    "LeftHandPinky4": {"index": 69, "joint": ""},
    "RightShoulder": {"index": 19, "joint": ""},
    "RightArm": {"index": 12, "joint": ""},
    "RightForeArm": {"index": 13, "joint": ""},
    "RightHand": {"index": 14, "joint": ""},
    "RightInHandIndex": {"index": 153, "joint": ""},
    "RightInHandMiddle": {"index": 154, "joint": ""},
    "RightInHandRing": {"index": 155, "joint": ""},
    "RightInHandPinky": {"index": 156, "joint": ""},
    "RightHandThumb1": {"index": 74, "joint": ""},
    "RightHandIndex1": {"index": 78, "joint": ""},
    "RightHandMiddle1": {"index": 82, "joint": ""},
    "RightHandRing1": {"index": 86, "joint": ""},
    "RightHandPinky1": {"index": 90, "joint": ""},
    "RightHandThumb2": {"index": 75, "joint": ""},
    "RightHandIndex2": {"index": 79, "joint": ""},
    "RightHandMiddle2": {"index": 83, "joint": ""},
    "RightHandRing2": {"index": 87, "joint": ""},
    "RightHandPinky2": {"index": 91, "joint": ""},
    "RightHandThumb3": {"index": 76, "joint": ""},
    "RightHandIndex3": {"index": 80, "joint": ""},
    "RightHandMiddle3": {"index": 84, "joint": ""},
    "RightHandRing3": {"index": 88, "joint": ""},
    "RightHandPinky3": {"index": 92, "joint": ""},
    "RightHandThumb4": {"index": 77, "joint": ""},
    "RightHandIndex4": {"index": 81, "joint": ""},
    "RightHandMiddle4": {"index": 85, "joint": ""},
    "RightHandRing4": {"index": 89, "joint": ""},
    "RightHandPinky4": {"index": 93, "joint": ""}
}

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


class HIKDefinitionUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        if parent is None:
            parent = wrapInstance(get_main_window_pointer(), QtWidgets.QMainWindow)
        super(HIKDefinitionUI, self).__init__(parent)
        self.setWindowTitle("HIK Character Builder")
        self.setMinimumSize(900, 600)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.char_name = QtWidgets.QLineEdit("Character1")
        self.export_path = QtWidgets.QLineEdit(get_default_export_path())
        namespace = os.path.basename(self.export_path.text()).rsplit('.')[0] + "_retarget"
        self.namespace = QtWidgets.QLineEdit(namespace)

        self.fields = {key: "" for key in DEFAULT_JOINT_MAP.keys()}
        self.buttons = {}
        self.default_map = DEFAULT_JOINT_MAP
        self._build_ui()

    def _build_ui(self):
        top_form = QtWidgets.QFormLayout()
        top_form.addRow("Character Name", self.char_name)
        top_form.addRow("Export Path", self.export_path)
        top_form.addRow("Namespace", self.namespace)

        self.layout().addLayout(top_form)

        layout_widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout()
        layout_widget.setLayout(grid)
        self.layout().addWidget(layout_widget)

        self.single_selector_widget = QtWidgets.QWidget()
        self.single_selector_layout = QtWidgets.QHBoxLayout()
        self.single_selector_widget.setLayout(self.single_selector_layout)
        self.selector_field = QtWidgets.QLineEdit()
        self.selector_button = QtWidgets.QPushButton("Pick Selected")
        self.selector_button.clicked.connect(self.pick_selected_joint)
        self.single_selector_layout.addWidget(self.selector_field)
        self.single_selector_layout.addWidget(self.selector_button)
        self.layout().addWidget(self.single_selector_widget)
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
        }


        right_side_slots = [
            ("RightShoulder", 1, 6),
            ("RightArm", 1, 7),
            ("RightForeArm", 1, 8),
            ("RightHand", 1, 9),

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
        load_btn.clicked.connect(self.load_definition)
        save_btn = QtWidgets.QPushButton("Save Definition")
        save_btn.clicked.connect(self.save_definition)
        detect_btn = QtWidgets.QPushButton("Auto Detect")
        detect_btn.clicked.connect(self.auto_detect)
        create_btn = QtWidgets.QPushButton("Create HIK Character")
        create_btn.clicked.connect(self.create_hik_character)

        btn_layout.addWidget(load_btn)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(detect_btn)
        btn_layout.addWidget(create_btn)

        self.layout().addLayout(btn_layout)

        self.current_slot = None

    def make_selector_callback(self, slot):
        def callback():
            self.current_slot = slot
            self.selector_field.setText(self.fields.get(slot, ""))
            self.single_selector_widget.show()
        return callback

    def update_button_color(self, slot):
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

    def mirror_joint_name(self, name):
        for l, r in [("_L", "_R"), ("_l ", "_r "), ("Left", "Right"), ("left", "right"), ("L_", "R_"), ("l_", "r_")]:
            if l in name:
                return name.replace(l, r)
            elif r in name:
                return name.replace(r, l)
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

    def save_definition(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Joint Map", "", "JSON Files (*.json)")
        if path:
            data = {key: self.default_map[key] for key in self.default_map}
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)

    def auto_detect(self):
        root_joint = "origin"  # You can replace this with a prompt if needed
        joint_map = self.guess_joint_map_from_root(root_joint)
        for slot in self.default_map:
            if slot in joint_map:
                self.fields[slot] = joint_map[slot].get("joint")
            self.update_button_color(slot)

    def guess_joint_map_from_root(self, root_joint):
        if not cmds.objExists(root_joint):
            return {}

        joint_map = copy.deepcopy(self.default_map)

        all_joints = cmds.listRelatives(root_joint, ad=True, type="joint") or []
        all_joints = list(reversed(all_joints))
        all_joints.insert(0, root_joint)

        spines = []
        necks = []

        fingers = {
            "Left": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []},
            "Right": {"Thumb": [], "Index": [], "Middle": [], "Ring": [], "Pinky": []}
        }

        for jnt in all_joints:
            name = jnt.lower()

            def set_slot(slot):
                if slot in joint_map and not joint_map[slot].get("joint"):
                    joint_map[slot]["joint"] = jnt

            if "spine" in name or "spn" in name:
                spines.append(jnt)

            elif "origin" in name:
                set_slot("Reference")

            elif "pelvis" in name:
                set_slot("Hips")

            elif "l_clavicle" in name:
                set_slot("LeftShoulder")
            elif "l_upperarm" in name:
                set_slot("LeftArm")
            elif name == "l_lowerarm":
                set_slot("LeftForeArm")
            elif "l_hand" in name:
                set_slot("LeftHand")

            elif "r_clavicle" in name:
                set_slot("RightShoulder")
            elif "r_upperarm" in name:
                set_slot("RightArm")
            elif name == "r_lowerarm":
                set_slot("RightForeArm")
            elif "r_hand" in name:
                set_slot("RightHand")

            elif "l_thigh" in name:
                set_slot("LeftUpLeg")
            elif "l_knee" in name:
                set_slot("LeftLeg")
            elif "l_ankle" in name:
                set_slot("LeftFoot")
            elif "l_toe" in name and "tip" not in name:
                set_slot("LeftToeBase")

            elif "r_thigh" in name:
                set_slot("RightUpLeg")
            elif "r_knee" in name:
                set_slot("RightLeg")
            elif "r_ankle" in name:
                set_slot("RightFoot")
            elif "r_toe" in name and "tip" not in name:
                set_slot("RightToeBase")

            if "neck" in name:
                necks.append(jnt)
            elif "head" in name:
                set_slot("Head")

            for side_prefix, side in [("l_", "Left"), ("r_", "Right")]:
                if name.startswith(side_prefix):
                    for finger in fingers[side].keys():
                        if finger.lower() in name:
                            fingers[side][finger].append(jnt)

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
                joints = fingers[side][finger]
                if not joints:
                    continue
                joints_sorted = sorted(joints, key=lambda x: x.lower())

                if "Thumb" not in finger:
                    in_hand_key = f"{side}InHand{finger}"
                    if in_hand_key in joint_map and not joint_map[in_hand_key].get("joint"):
                        joint_map[in_hand_key]["joint"] = joints_sorted[0]
                else:
                    thumb4_key = f"{side}Hand{finger}4"
                    joint_map[thumb4_key]["joint"] = joints_sorted[-1]
                for i in range(1, min(5, len(joints_sorted))):
                    num = i
                    if "Thumb" in finger:
                        num = i-1
                    key = f"{side}Hand{finger}{i}"
                    if key in joint_map and not joint_map[key].get("joint"):

                        joint_map[key]["joint"] = joints_sorted[num]

        self.default_map = joint_map
        return joint_map

    def create_hik_character(self):
        char_name = self.char_name.text()
        export_path = self.export_path.text()
        joint_map = {slot: [self.fields.get(slot), self.default_map[slot].get("index")] for slot in self.default_map if self.fields.get(slot)}
        if len(joint_map) < 5:
            cmds.warning("Not enough joints assigned to create a valid character.")
            return

        setup_hik.setup_hik_character(char_name, joint_map, export_path, self.namespace.text())


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
