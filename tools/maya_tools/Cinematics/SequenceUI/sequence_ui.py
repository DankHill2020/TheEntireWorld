try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance
    PYQT_VERSION = 6
except:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance
    PYQT_VERSION = 2
import threading
import os
from custom_qt import custom_widgets
from utilities import json_data
from unreal_tools import unreal_subprocess as usp
from unreal_tools import unreal_project_data as upd


def is_maya():
    try:
        import maya.cmds
        return True
    except ImportError:
        return False

def is_motionbuilder():
    try:
        import pyfbsdk

        return True
    except ImportError:
        return False

if is_maya():
    from maya_tools.Animation.anim_export import anim_export_command as anim_ec
    from maya_tools.Animation.anim_export import anim_export_utils as anim_utils
    from maya_tools.Cinematics.SequenceUI import sequence_utils
    print("Running in Maya")

elif is_motionbuilder():
    from motionbuilder_tools.Animation.anim_export import anim_export as anim_ec
    from motionbuilder_tools.Cinematics.SequenceUI import sequence_utils
    print("Running in MotionBuilder")

script_dir = os.path.dirname(__file__).replace('\\', '/')

CINEMATIC_FOLDER = "Cinematics"
GAMEPLAY_FOLDER = "Gameplay"

class ExportHelper(QtCore.QObject):
    progress_update = QtCore.Signal(int)
    progress_update_text = QtCore.Signal(str)
    finished = QtCore.Signal()


class AnimationEntryError(Exception):
    """
    Custom exception for missing animation entry fields.
    :return:
    """
    pass


class AnimationManagerUI(QtWidgets.QDialog):
    file_opened = QtCore.Signal()
    def __init__(self, parent=None):
        if is_maya():
            parent = wrapInstance(sequence_utils.get_main_window_pointer(), QtWidgets.QMainWindow)
        elif is_motionbuilder():
            parent = QtWidgets.QApplication.activeWindow()
        """
        Creates the UI with a table, context menu, and right-side controls.
        :param parent: the actual Maya or motionbuilder window
        """
        super(AnimationManagerUI, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Window |
                            QtCore.Qt.WindowMinimizeButtonHint |
                            QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle("Animation Manager")
        self.setMinimumSize(1100, 450)

        self.icon_path = os.path.join(script_dir, "icons", "theEntireWorld.png").replace('\\', '/')
        self.setWindowIcon(QtGui.QIcon(self.icon_path))
        self.selected_color = QtGui.QColor("#ffffff")

        self.table_widget = QtWidgets.QTableWidget()
        self.headers = ["Animation Name", "Export Directory", "Start Frame", "End Frame", "Namespace", "Skeleton", "Nodes"]
        # Scale image to fit table widget size after showing

        self.animation_name_input = QtWidgets.QLineEdit()
        self.start_frame_input = custom_widgets.NonScrollingSpinBox()
        self.end_frame_input = custom_widgets.NonScrollingSpinBox()
        self.namespace_input = QtWidgets.QLineEdit()
        self.skeleton_filter_input = QtWidgets.QLineEdit()
        self.skeleton_input = QtWidgets.QComboBox()

        self.directory_widget = custom_widgets.BrowseDirectory('C:/')

        self.color_btn = QtWidgets.QPushButton("Choose Color")

        self.add_button = QtWidgets.QPushButton("Add Animation")
        self.duplicate_button = QtWidgets.QPushButton("Duplicate Animations")
        self.delete_button = QtWidgets.QPushButton("Delete Animations")
        self.unreal_checkbox = QtWidgets.QCheckBox("Import into Unreal")
        self.unreal_checkbox.setChecked(True)
        self.export_button = QtWidgets.QPushButton("Export Animations")
        self.export_cinematics_button = QtWidgets.QPushButton("Export For Cinematic")
        self.anim_dict = dict()
        self.skeletons = None
        self.uproject = None
        self.export_dir = ''
        self.log_path = ''
        self.cmd_path = ''
        self.namespace_skeleton_map = {}
        self.export_node = sequence_utils.export_node_exists()
        self.menu_bar = QtWidgets.QMenuBar(self)

        self.init_ui()
        self.file_opened.connect(self._on_file_open_completed)

        sequence_utils.add_file_open_callback(self)

    def init_ui(self):
        """
        Initializes the UI layout and widgets.
        :return:
        """
        main_layout = QtWidgets.QHBoxLayout(self)
        self.setLayout(main_layout)
        main_layout.setMenuBar(self.menu_bar)
        self.table_widget.setColumnCount(7)
        self.table_widget.setHorizontalHeaderLabels(self.headers)
        header = self.table_widget.horizontalHeader()
        header.setVisible(True)
        for i in range(self.table_widget.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

        self.table_widget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.table_widget.setMinimumWidth(700)
        self.table_widget.resizeColumnsToContents()
        self.table_widget.itemChanged.connect(self.on_item_changed)

        main_layout.addWidget(self.table_widget)
        self.table_widget.installEventFilter(self)
        # Right side: Widgets for update
        right_container = QtWidgets.QWidget()
        right_container.setMaximumWidth(400)
        right_layout = QtWidgets.QVBoxLayout(right_container)

        self.animation_name_input = QtWidgets.QLineEdit()
        self.animation_name_input.setPlaceholderText("Animation Name")
        scene_path = sequence_utils.get_scene_path()
        if scene_path:
            self.animation_name_input.setText(os.path.basename(scene_path).split('.')[0])

        self.start_frame_input.setRange(0, 99999)
        self.end_frame_input.setRange(0, 99999)

        start_frame, end_frame = sequence_utils.get_display_range()
        self.start_frame_input.setValue(start_frame)
        self.end_frame_input.setValue(end_frame)

        self.namespace_input = QtWidgets.QLineEdit()
        self.namespace_input.setPlaceholderText("Rig Namespace")
        selected_namespaces = list(sequence_utils.get_rig_namespaces())
        if len(selected_namespaces):
            self.namespace_input.setText(selected_namespaces[0])

        right_layout.addWidget(QtWidgets.QLabel("Animation Name:"))
        right_layout.addWidget(self.animation_name_input)

        right_layout.addWidget(QtWidgets.QLabel("Export Directory:"))
        right_layout.addWidget(self.directory_widget)

        right_layout.addWidget(QtWidgets.QLabel("Start Frame:"))
        right_layout.addWidget(self.start_frame_input)

        right_layout.addWidget(QtWidgets.QLabel("End Frame:"))
        right_layout.addWidget(self.end_frame_input)

        right_layout.addWidget(QtWidgets.QLabel("Namespace:"))
        right_layout.addWidget(self.namespace_input)

        right_layout.addWidget(QtWidgets.QLabel("Skeleton:"))
        self.skeleton_filter_input.setPlaceholderText("Filter skeletons...")
        right_layout.addWidget(self.skeleton_filter_input)
        right_layout.addWidget(self.skeleton_input)
        self.skeleton_filter_input.textChanged.connect(self.filter_skeletons)

        right_layout.addWidget(QtWidgets.QLabel("Select Row Color:"))
        self.color_btn.setStyleSheet("background-color: white; border: 1px solid black;")
        self.selected_color = QtGui.QColor(255, 255, 255)
        self.update_color_button(self.selected_color)

        self.color_btn.clicked.connect(self.open_color_picker)
        right_layout.addWidget(self.color_btn)

        # Add Animation / Duplicate Buttons
        self.add_button.clicked.connect(self.add_animation)
        self.duplicate_button.clicked.connect(self.duplicate_animation)
        self.delete_button.clicked.connect(self.delete_animation)
        self.export_button.clicked.connect(self.export_animation)
        self.export_cinematics_button.clicked.connect(self.export_cinematic)

        right_layout.addWidget(self.add_button)
        right_layout.addWidget(self.duplicate_button)
        right_layout.addWidget(self.delete_button)
        right_layout.addWidget(self.unreal_checkbox)
        right_layout.addWidget(self.export_button)
        right_layout.addWidget(self.export_cinematics_button)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(right_container)
        scroll_area.setMaximumWidth(400)

        main_layout.addWidget(scroll_area)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(main_layout)
        self.setLayout(layout)

        if self.export_node:
            self.anim_dict, self.skeletons, self.uproject, self.export_dir = self.load_data()
        else:
            self.table_widget.clear()
            self.anim_dict, self.skeletons, self.uproject, self.export_dir = self.load_data()

        if not self.skeletons:
            if not self.uproject or os.path.exists(os.path.dirname(self.uproject)):
                self.uproject = self.get_uproject("C:/")
                http_server_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(script_dir))), "unreal_tools", "http_server.py").replace('\\', '/')

                upd.add_unreal_startup_script(self.uproject, http_server_path)
            if self.uproject:
                self.log_path = upd.get_latest_unreal_log(self.uproject)
                self.cmd_path = upd.get_unreal_cmd_exe(self.uproject)
                self.update_skeleton_list()
        else:
            self.skeleton_input.addItems(self.skeletons)

        if os.path.exists(self.export_dir):
            self.directory_widget.dir_name.setText(self.export_dir)
        else:
            self.directory_widget.dir_name.setText("C:/")
            self.export_dir = "C:/"
        self.directory_widget.dir_name.textChanged.connect(self.store_data)
        self.create_file_menu()

    def on_item_changed(self, item):
        self.store_data()

    def closeEvent(self, event):
        """
        Called when the window is closing. Used to clean up callbacks.
        """
        sequence_utils.remove_file_open_callback()
        event.accept()

    def eventFilter(self, obj, event):
        if obj and event:
            if obj == self.table_widget and event.type() == QtCore.QEvent.Resize:
                self.set_table_background_scaled()
        return super().eventFilter(obj, event)

    def set_table_background_scaled(self):
        """
        Loads the Icon as the background after converting to grayscale
        :return:
        """
        size = self.table_widget.size()

        image = QtGui.QImage(self.icon_path)

        image = image.convertToFormat(QtGui.QImage.Format_Grayscale8)

        pixmap = QtGui.QPixmap.fromImage(image).scaled(
            size,
            QtCore.Qt.KeepAspectRatioByExpanding,
            QtCore.Qt.SmoothTransformation
        )

        palette = self.table_widget.viewport().palette()
        palette.setBrush(QtGui.QPalette.Base, QtGui.QBrush(pixmap))
        self.table_widget.viewport().setPalette(palette)
        self.table_widget.viewport().setAutoFillBackground(True)

    def filter_skeletons(self, text):
        """
        Filters list of skeletons in the group box
        :param text: Text to filter by
        :return:
        """
        self.skeleton_input.clear()
        filtered = [s for s in self.skeletons if text.lower() in s.lower()]
        self.skeleton_input.addItems(filtered)

    def _on_file_open_completed(self, *args):
        """Internal method triggered when a new scene is opened."""
        self.table_widget.clear()
        self.load_data()
        self.table_widget.setHorizontalHeaderLabels(self.headers)

    def show_context_menu(self, pos):
        """
        Shows Context Menu for editing Row Data or Widgets from Row Data
        :param pos: Position selected in Table, since the context menu needs to know which row is being edited
        """
        context_menu = QtWidgets.QMenu(self)

        rename_action = context_menu.addAction("Rename Animation Name")
        update_namespace_action = context_menu.addAction("Update Namespace")
        update_skeleton_action = context_menu.addAction("Update Skeleton")
        update_color_action = context_menu.addAction("Update Color")
        copy_action = context_menu.addAction("Copy Selected File Names")
        set_range_action = context_menu.addAction("Set Scene Range to Selected Animation Range")
        copy_to_right_action = context_menu.addAction("Copy to Right Panel")
        add_shot_action = context_menu.addAction("Add Animations for Shots")
        add_selected_action = context_menu.addAction("Add Animations for Selected")
        add_all_rigs_action = context_menu.addAction("Add Animations for All Rigs")
        if is_maya():
            add_facial_sliders_action = context_menu.addAction("Add Facial Sliders As Separate Export")
            add_facial_joints_action = context_menu.addAction("Add Facial Joints As Separate Export")
        else:
            add_facial_sliders_action = ""
            add_facial_joints_action = ""

        select_all_namespace_action = context_menu.addAction("Select All with Namespace")
        refresh_skeletons_action = context_menu.addAction("Refresh Skeletons for uproject")
        update_uproject_path_action = context_menu.addAction("Select new uproject path")
        update_export_directory_action = context_menu.addAction("Update Export Directory")
        if PYQT_VERSION == 6:
            action = context_menu.exec(self.table_widget.mapToGlobal(pos))
        else:
            action = context_menu.exec_(self.table_widget.mapToGlobal(pos))
        if action == rename_action:
            self.update_selected_column(0, self.animation_name_input.text())
        elif action == update_namespace_action:
            self.update_selected_column(4, self.namespace_input.text())
        elif action == update_skeleton_action:
            self.update_selected_column(5, self.skeleton_input.currentText())
        elif action == update_color_action:
            self.apply_row_colors(self.selected_color)
        elif action == copy_action:
            self.copy_selected_filenames()
        elif action == set_range_action:
            self.set_scene_range()
        elif action == copy_to_right_action:
            self.populate_right_side_from_selected_row()
        elif action == add_shot_action:
            self.add_animations_for_shots()
        elif action == add_selected_action:
            self.add_animations_for_selection(True)
        elif action == add_all_rigs_action:
            self.add_animations_for_selection(False)

        elif action == add_facial_sliders_action:
            if is_maya():
                self.add_facial_export_row_for_selected(joints=False)
        elif action == add_facial_joints_action:
            if is_maya():

                self.add_facial_export_row_for_selected(joints=True)
        elif action == select_all_namespace_action:
            self.select_all_with_namespace()
        elif action == refresh_skeletons_action:
            self.update_skeleton_list()
        elif action == update_uproject_path_action:
            self.update_project()
        elif action == update_export_directory_action:
            self.update_export_directory_for_row()

    def update_export_directory_for_row(self):
        """
        Function updates the export directory for any number of selected rows
        :return:
        """
        selected_rows = list(set(index.row() for index in self.table_widget.selectedIndexes()))

        if not selected_rows:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one row to delete.")
            return

        for row in sorted(selected_rows, reverse=True):
            color_to_use = None
            for col in [0, 1, 4, 5, 6]:
                item = self.table_widget.item(row, col)
                if item:
                    color_to_use = item.background().color()
            self.table_widget.setItem(row, 1, QtWidgets.QTableWidgetItem(self.directory_widget.dir_name.text()))
            self.table_widget.selectRow(row)
            self.apply_row_colors(color_to_use)

    def update_skeleton_list(self):
        """
        Function to reload the skeleton list from the uproject without having to reselect project
        :return:
        """
        current_skel = self.skeleton_input.currentText()
        skel_data = usp.run_get_skeletons(self.uproject, self.log_path, self.cmd_path)
        if type(skel_data) == str:
            self.skeletons = eval(skel_data)
        else:
            self.skeletons = skel_data
        self.skeleton_input.clear()
        self.skeleton_input.addItems(self.skeletons)

        if current_skel in self.skeletons:
            index = self.skeleton_input.findText(current_skel)
            if index != -1:
                self.skeleton_input.setCurrentIndex(index)

    def update_project(self):
        """
        Function to reload the skeleton list after selecting the uproject
        :return:
        """
        uproject = self.uproject
        self.uproject = self.get_uproject(os.path.dirname(self.uproject))
        refresh_skeletons = True
        if not self.uproject:
            self.uproject = uproject
            refresh_skeletons = False

        if self.uproject:
            self.log_path = upd.get_latest_unreal_log(self.uproject)
            self.cmd_path = upd.get_unreal_cmd_exe(self.uproject)
            if refresh_skeletons:
                self.update_skeleton_list()

    def update_selected_column(self, column, value):
        """
        Updates selected column with specific value (usually run on selected rows)
        :param column: Column to be updated
        :param value: Value to update in column
        :return:
        """
        for item in self.table_widget.selectedItems():
            if item.column() == column:
                item.setText(value)
                row = item.row()
                if column == 4 or column == 5:
                    namespace_item = self.table_widget.item(row, 4)
                    skeleton_item = self.table_widget.item(row, 5)
                    if namespace_item and skeleton_item:
                        namespace = namespace_item.text().strip()
                        skeleton = skeleton_item.text().strip()
                        if namespace and skeleton:
                            self.namespace_skeleton_map[namespace] = skeleton
        self.store_data()

    def add_animation(self, anim=None, directory=None, start=None, end=None, namespace=None, skeleton=None, color=None,
                      nodes=None):
        """
        Adds a new row using the right-side input fields with validation and an error pop-up.
        :param anim: Animation Name to be added to row
        :param directory: Export Directory for the animation, uses the directory widget input otherwise
        :param start: Start Frame for exported animation
        :param end: End Frame for exported animation
        :param namespace: Namespace to be Exported in the data
        :param skeleton: Skeleton can be input as text, otherwise will use QGroupBox currentText
        :param color: Color to be added, example formatting : QtGui.QColor(255, 255, 255)
        :param nodes: Based of selection, currently only used for cameras

        :return:
        """
        missing_fields = []
        self.table_widget.blockSignals(True)
        tested_widgets = [self.animation_name_input.text().strip(), self.directory_widget.dir_name.text().strip(),
                          self.namespace_input.text().strip(), self.skeleton_input.currentText().strip()]
        tested_labels = ["Animation Name", "Export Directory", "Namespace", "Skeleton"]
        tested_args = [anim, directory, namespace, skeleton]
        for index, widget in enumerate(tested_widgets):
            if not widget:
                if not tested_args[index]:
                    missing_fields.append(tested_labels[index])

        if missing_fields:
            error_message = f"Text must be entered for Animation Entry.\nMissing data: {', '.join(missing_fields)}"
            message = QtWidgets.QMessageBox.critical(None, "Missing Data", error_message)
            return

        row_position = self.table_widget.rowCount()
        self.table_widget.insertRow(row_position)

        if not anim:
            anim = self.animation_name_input.text()
        self.table_widget.setItem(row_position, 0, QtWidgets.QTableWidgetItem(anim))

        if not directory:
            directory = self.directory_widget.directory
        if not os.path.exists(directory):
            os.makedirs(directory)
        self.table_widget.setItem(row_position, 1, QtWidgets.QTableWidgetItem(directory))

        if not start:
            start = self.start_frame_input.value()
        start_spin = custom_widgets.NonScrollingSpinBox()
        start_spin.setRange(0, 99999)
        start_spin.setValue(start)
        start_spin.valueChanged.connect(self.store_data)

        if not end:
            end = self.end_frame_input.value()
        end_spin = custom_widgets.NonScrollingSpinBox()
        end_spin.setRange(0, 99999)
        end_spin.setValue(end)
        end_spin.valueChanged.connect(self.store_data)

        self.table_widget.setCellWidget(row_position, 2, start_spin)
        self.table_widget.setCellWidget(row_position, 3, end_spin)

        if not namespace:
            namespace = self.namespace_input.text()
        self.table_widget.setItem(row_position, 4, QtWidgets.QTableWidgetItem(namespace))

        if not skeleton:
            skeleton = self.skeleton_input.currentText()

        self.table_widget.setItem(row_position, 5, QtWidgets.QTableWidgetItem(skeleton))

        if not nodes:
            nodes = 'None'
        self.table_widget.setItem(row_position, 6, QtWidgets.QTableWidgetItem(nodes))
        self.table_widget.selectRow(row_position)
        if not color:
            color = self.selected_color
        self.apply_row_colors(color)
        self.table_widget.blockSignals(False)
        self.store_data()
        self.table_widget.setHorizontalHeaderLabels(self.headers)

    def add_animations_for_selection(self, selection=False):
        """
        Adds animation entries for selected, including camera and character tracks.
        :return:
        """
        namespaces = sequence_utils.get_rig_namespaces(selection)
        scene_path = sequence_utils.get_scene_path()
        dir_name = self.directory_widget.dir_name.text()
        if scene_path:
            animation_name = os.path.basename(scene_path).split('.')[0]
            dir_name = os.path.join(dir_name, animation_name).replace("\\", "/")
        else:
            reply = QtWidgets.QMessageBox.question(
                self, "Are you Sure? ",
                f"File has not been saved, Animation Names will use the UI Animation Name instead of the File Name",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply != QtWidgets.QMessageBox.No:
                return
            animation_name = self.animation_name_input.text().strip()

        start = self.start_frame_input.value()
        end = self.end_frame_input.value()
        color = self.selected_color
        for namespace in namespaces:
            if namespace in self.namespace_skeleton_map:
                skeleton = self.namespace_skeleton_map[namespace]
            else:
                skeleton = ""
            anim_namespace = namespace.replace(":", "_")
            char_anim_name = f"{animation_name}_{anim_namespace}"
            self.add_animation(anim=char_anim_name, directory=dir_name,
                               start=start, end=end, namespace=namespace, skeleton=skeleton, color=color)

        if selection:
            camera = sequence_utils.get_cameras_from_selection()
            if camera:
                camera_anim_name = f"{animation_name}_{camera}"
                self.add_animation(anim=camera_anim_name, directory=dir_name,
                                   start=start, end=end, namespace="CAM", skeleton="CAM", color=color, nodes=camera)

        self.store_data()

    def add_animations_for_shots(self):
        """
        Adds animation entries for shots, including camera and character tracks.
        :return:
        """
        shot_data = sequence_utils.get_camera_sequencer_data()
        namespaces = sequence_utils.get_rig_namespaces()
        shot_colors = {}

        for shot_number, start, end, camera in shot_data:
            if shot_number not in shot_colors:
                shot_colors[shot_number] = QtGui.QColor.fromHsv(len(shot_colors) * 50 % 360, 255, 200)
            color = shot_colors[shot_number]
            dir_name = self.directory_widget.dir_name.text()
            scene_path = sequence_utils.get_scene_path()
            if scene_path:
                animation_name = os.path.basename(scene_path).split('.')[0]
                dir_name = os.path.join(dir_name, animation_name).replace("\\", "/")
            else:
                reply = QtWidgets.QMessageBox.question(
                    self, "Are you Sure? ",
                    f"File has not been saved, Animation Names will use the UI Animation Name instead of the File Name",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                if reply != QtWidgets.QMessageBox.No:
                    return
                animation_name = self.animation_name_input.text().strip()
                if animation_name:
                    dir_name = os.path.join(dir_name, animation_name).replace("\\", "/")
            camera_anim_name = f"{animation_name}_{shot_number}_{camera}"
            self.add_animation(anim=camera_anim_name, directory=dir_name,
                               start=start, end=end, namespace="CAM", skeleton="CAM", color=color, nodes=camera)

            # Add character animation entries
            for namespace in namespaces:
                if namespace in self.namespace_skeleton_map:
                    skeleton = self.namespace_skeleton_map[namespace]
                else:
                    skeleton = ""
                anim_namespace = namespace.replace(":", "_")
                char_anim_name = f"{animation_name}_{shot_number}_{anim_namespace}"
                self.add_animation(anim=char_anim_name, directory=dir_name,
                                   start=start, end=end, namespace=namespace, skeleton=skeleton, color=color)
        self.store_data()


    def delete_animation(self):
        """
        Deletes the selected rows from the QTableWidget.
        Handles multiple row selections and reorders correctly to prevent index shifting.
        :return:
        """
        selected_rows = list(set(index.row() for index in self.table_widget.selectedIndexes()))

        if not selected_rows:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select at least one row to delete.")
            return

        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_rows)} selected row(s)?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        for row in sorted(selected_rows, reverse=True):
            self.table_widget.removeRow(row)

        self.store_data()
        self.load_data()

    def duplicate_animation(self):
        """
        Duplicates the selected row, inserting the duplicate directly below it.
        Handles shifting indices due to insertions.
        """
        self.table_widget.blockSignals(True)
        selected_rows = sorted([r.row() for r in self.table_widget.selectionModel().selectedRows()])
        offset = 0

        for original_row in selected_rows:
            insert_position = original_row + 1 + offset
            self.table_widget.insertRow(insert_position)
            color_to_use = None

            for col in [0, 1, 4, 5, 6]:
                item = self.table_widget.item(original_row + offset, col)
                if item:
                    color_to_use = item.background().color()
                    self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(item.text()))

            start_widget = self.table_widget.cellWidget(original_row + offset, 2)
            end_widget = self.table_widget.cellWidget(original_row + offset, 3)

            if start_widget and isinstance(start_widget, custom_widgets.NonScrollingSpinBox):
                start_spin = custom_widgets.NonScrollingSpinBox()
                start_spin.setRange(0, 99999)
                start_spin.setValue(start_widget.value())
                self.table_widget.setCellWidget(insert_position, 2, start_spin)

            if end_widget and isinstance(end_widget, custom_widgets.NonScrollingSpinBox):
                end_spin = custom_widgets.NonScrollingSpinBox()
                end_spin.setRange(0, 99999)
                end_spin.setValue(end_widget.value())
                self.table_widget.setCellWidget(insert_position, 3, end_spin)

            self.apply_row_colors(color_to_use)
            self.table_widget.selectRow(insert_position)

            offset += 1
        self.table_widget.blockSignals(False)
        self.store_data()

    def add_facial_export_row_for_selected(self, joints=False):
        """
        Adds Facial Sliders or joints for Namespace of selected row, including nested namespaces in case of sub references
        Defaults to Face Archetype for skeleton otherwise uses the default skeleton if doesn't exist
        :return:
        """
        self.table_widget.blockSignals(True)
        selected_rows = sorted([r.row() for r in self.table_widget.selectionModel().selectedRows()])
        offset = 0

        for original_row in selected_rows:
            current_row = original_row + offset
            namespace_item = self.table_widget.item(current_row, 4)
            if not namespace_item:
                continue

            namespace = namespace_item.text()
            if namespace != "CAM":
                if joints:
                    anim_name_suffix = "_FacialJoints"
                    facial_namespace = anim_utils.get_facial_joints(namespace)[1]
                    nodes = "FacialJoints"
                else:
                    anim_name_suffix = "_FacialSliders"
                    facial_namespace = anim_utils.get_facial_sliders(namespace)[1]
                    nodes = "FacialSliders"
                if nodes:
                    insert_position = current_row + 1
                    self.table_widget.insertRow(insert_position)
                    color_to_use = None

                    for col in [0, 1, 4, 5, 6]:
                        item = self.table_widget.item(current_row, col)
                        if item:
                            color_to_use = item.background().color()
                            if col == 0:
                                self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(item.text() + anim_name_suffix))
                            elif col == 4:
                                self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(facial_namespace))
                            elif col == 5:
                                current_filter = self.skeleton_filter_input.text()
                                current_skel = self.skeleton_input.currentText()
                                self.filter_skeletons("Face_Archetype")
                                if self.skeleton_input.currentText():
                                    self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(self.skeleton_input.currentText()))
                                    self.filter_skeletons(current_filter)
                                    self.skeleton_input.setCurrentText(current_skel)
                                else:
                                    self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(item.text()))
                            elif col == 6:
                                self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(nodes))
                            else:
                                self.table_widget.setItem(insert_position, col, QtWidgets.QTableWidgetItem(item.text()))
                    start_widget = self.table_widget.cellWidget(current_row, 2)
                    end_widget = self.table_widget.cellWidget(current_row, 3)

                    if start_widget and isinstance(start_widget, custom_widgets.NonScrollingSpinBox):
                        start_spin = custom_widgets.NonScrollingSpinBox()
                        start_spin.setRange(0, 99999)
                        start_spin.setValue(start_widget.value())
                        self.table_widget.setCellWidget(insert_position, 2, start_spin)

                    if end_widget and isinstance(end_widget, custom_widgets.NonScrollingSpinBox):
                        end_spin = custom_widgets.NonScrollingSpinBox()
                        end_spin.setRange(0, 99999)
                        end_spin.setValue(end_widget.value())
                        self.table_widget.setCellWidget(insert_position, 3, end_spin)

                    self.table_widget.selectRow(insert_position)
                    self.apply_row_colors(color_to_use)

                    offset += 1
        self.table_widget.blockSignals(False)
        self.store_data()

    def select_all_with_namespace(self):
        """
        Selects all rows in the table that match the namespace of the currently selected row.
        """
        selected_items = self.table_widget.selectedItems()
        if not selected_items:
            return

        first_selected_row = selected_items[0].row()
        namespace_item = self.table_widget.item(first_selected_row, 4)
        if not namespace_item:
            return

        namespace_to_match = namespace_item.text()

        selection_model = self.table_widget.selectionModel()
        selection_model.clearSelection()

        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 4)
            if item and item.text() == namespace_to_match:
                selection_model.select(self.table_widget.model().index(row, 0),
                                       QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

    def open_color_picker(self):
        """
        Opens a QColorDialog and ensures it stays on top of Maya's UI.
        :return:
        """
        color_dialog = QtWidgets.QColorDialog(self)
        color_dialog.setOption(QtWidgets.QColorDialog.ShowAlphaChannel, True)
        color_dialog.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowStaysOnTopHint)

        color_dialog.raise_()
        color_dialog.activateWindow()

        selected_color = color_dialog.getColor(self.selected_color)

        if selected_color.isValid():
            self.selected_color = selected_color
            self.update_color_button(selected_color)
            self.apply_row_colors(selected_color)
        else:
            sequence_utils.display_warning("No valid color selected.")

    def update_color_button(self, color):
        """
        Updates Choose Color button to display the selected color.
        :param color: Color to be updated, example formatting : QtGui.QColor(255, 255, 255)
        :return:
        """
        # Calculate brightness using  luminance
        brightness = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue())

        # Choose white or black text depending on brightness
        text_color = "#000000" if brightness > 186 else "#ffffff"

        self.color_btn.setStyleSheet(
            f"""
            background-color: {color.name()};
            color: {text_color};
            border: 1px solid black;
            """
        )

        self.selected_color = color

    def apply_row_colors(self, color=None):
        """
        Applies the chosen color to all selected rows in the QTableWidget.
        :param color: Color to be updated, example formatting : QtGui.QColor(255, 255, 255)
        :return:
        """

        if color is None:
            color = self.selected_color

        if not isinstance(color, QtGui.QColor):
            try:
                color = QtGui.QColor(color)
            except Exception:
                sequence_utils.display_warning("Invalid color passed to apply_row_colors.")
                return

        if not color.isValid():
            sequence_utils.display_warning("Invalid QColor detected.")
            return

        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            sequence_utils.display_warning("No rows selected to apply color.")
            return

        #Grabbed values for standard coefficients of brightness to detect if color is Bright or dark, to swap text color
        luminance = 0.299 * color.redF() + 0.587 * color.greenF() + 0.114 * color.blueF()
        text_color = QtGui.QColor("black") if luminance > 0.5 else QtGui.QColor("white")

        for index in selected_rows:
            row = index.row()
            for col in range(self.table_widget.columnCount()):
                item = self.table_widget.item(row, col)
                if item:
                    item.setBackground(QtGui.QBrush(color))
                    item.setForeground(QtGui.QBrush(text_color))

        self.store_data()

    def set_scene_range(self):
        """
        Sets the Maya timeline to match the selected animation's frame range.
        :return:
        """
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            sequence_utils.display_warning("No animation selected to set scene range.")
            return

        row = selected_rows[0].row()
        start_widget = self.table_widget.cellWidget(row, 2)
        end_widget = self.table_widget.cellWidget(row, 3)

        if start_widget and end_widget:
            start_frame = start_widget.value()
            end_frame = end_widget.value()
            sequence_utils.set_display_range(start_frame, end_frame)

        else:
            sequence_utils.display_warning("Selected row does not contain valid frame range values.")
        self.store_data()

    def copy_selected_filenames(self):
        """
        Copies selected Export Locations to clipboard.
        :return:
        """
        file_names = [os.path.join(self.table_widget.item(row.row(), 1).text(),
                                   self.table_widget.item(row.row(), 0).text() + '.fbx').replace('\\', '/')
                      for row in self.table_widget.selectionModel().selectedRows()]
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText("\n".join(file_names))

    def populate_right_side_from_selected_row(self):
        """
        Copies values from the selected row and pastes them into the right-side layout widgets.
        :return:
        """
        selected_rows = self.table_widget.selectionModel().selectedRows()
        if not selected_rows:
            sequence_utils.display_warning("No row selected to copy data.")
            return

        row = selected_rows[0].row()

        self.animation_name_input.setText(self.table_widget.item(row, 0).text())
        self.directory_widget.dir_name.setText(self.table_widget.item(row, 1).text())

        start_widget = self.table_widget.cellWidget(row, 2)
        end_widget = self.table_widget.cellWidget(row, 3)
        if isinstance(start_widget, custom_widgets.NonScrollingSpinBox):
            self.start_frame_input.setValue(start_widget.value())
        if isinstance(end_widget, custom_widgets.NonScrollingSpinBox):
            self.end_frame_input.setValue(end_widget.value())

        self.namespace_input.setText(self.table_widget.item(row, 4).text())
        skeleton_text = self.table_widget.item(row, 5).text()
        index = self.skeleton_input.findText(skeleton_text)

        if index != -1:
            self.skeleton_input.setCurrentIndex(index)
        else:
            print(f"'{skeleton_text}' not found in combo box.")

        item_color = self.table_widget.item(row, 0).background().color()
        self.selected_color = item_color
        self.update_color_button(item_color)

    def export_cinematic(self):
        """
        Exports the selected animations and imports the data into Unreal.
        :return:
        """
        self.export_animation(cinematic=True)

    def export_animation(self, cinematic = False):
        """
        Exports the selected animations and imports the data into Unreal.
        :return:
        """
        selected_anim_dict = dict()
        selected_rows = self.table_widget.selectionModel().selectedRows()
        export_paths = []
        for r in selected_rows:
            path = os.path.join(self.table_widget.item(r.row(), 1).text(),
                                       self.table_widget.item(r.row(), 0).text() + '.fbx').replace('\\', '/')
            export_paths.append(path)
        progress_bar = custom_widgets.ListProgressBar(export_paths,
                                                      parent=wrapInstance(sequence_utils.get_main_window_pointer(),
                                                                          QtWidgets.QMainWindow))
        progress_bar.resize(400, 120)
        progress_bar.show()
        progress_bar.start()

        #We export on threads, so this Helper helps make sure the progress bar stays connected to the export being run
        helper = ExportHelper()
        def on_progress_update(percent):
            progress_bar.progress_bar.setValue(percent)

        def on_exports_complete():
            progress_bar.close()

        def on_progress_update_text(string_text):
            progress_bar.label.setText(string_text)

        helper.progress_update.connect(on_progress_update)
        helper.progress_update_text.connect(on_progress_update_text)
        helper.finished.connect(on_exports_complete)

        QtWidgets.QApplication.processEvents()
        export_processes = []
        scene_path = sequence_utils.get_scene_path()
        export_paths = []
        #Actual Export logic is in this for loop
        for row in selected_rows:

            row_index = row.row()
            export_path = os.path.join(self.table_widget.item(row.row(), 1).text(),
                                       self.table_widget.item(row.row(), 0).text() + '.fbx').replace('\\', '/')
            start_widget = self.table_widget.cellWidget(row.row(), 2)
            end_widget = self.table_widget.cellWidget(row.row(), 3)
            namespace = self.table_widget.item(row.row(), 4).text()
            skeleton = self.table_widget.item(row.row(), 5).text()
            nodes = self.table_widget.item(row.row(), 6).text()
            color_str = str(self.table_widget.item(row_index, 0).background().color())
            color_str = color_str.replace("PySide6.", "")
            color = color_str.replace("PySide2.", "")
            export_paths.append(export_path)

            if nodes == 'None':
                nodes = None
            else:
                nodes = [n.strip() for n in nodes.split(",")]
            if is_maya():
                ref_paths = anim_utils.find_references_from_namespace(namespace)

                proc = anim_ec.export_animation_to_fbx(export_path, namespace, start_widget.value(), end_widget.value(),
                                                       nodes=nodes, reference_paths=ref_paths)
            else:
                proc = anim_ec.export_animation(scene_path, export_path, namespace, start_widget.value(), end_widget.value(),
                                                       nodes=nodes)
                progress_bar.update_progress()
            export_processes.append(proc)
            selected_anim_dict[export_path] = [start_widget.value(), end_widget.value(), namespace, skeleton, color,
                                               nodes]
            QtWidgets.QApplication.processEvents()

        def launch_unreal_after_export(export_processes, export_path):
            """
            Waits for all export processes to finish and then launches Unreal
            :param export_processes: list of subprocess.Popen processes
            """
            if is_maya():
                total_exports = len(export_processes)

                while export_processes and any(prc.is_alive() for prc in export_processes):
                    remaining = sum(1 for prc in export_processes if prc.is_alive())
                    progress_percent = int((total_exports - remaining) / total_exports * 100)

                    finished_processes = []
                    for i, prc in enumerate(export_processes):
                        if not prc.is_alive():
                            local_path = export_paths[i]
                            helper.progress_update.emit(progress_percent)
                            helper.progress_update_text.emit(f"Exporting Completed for Animation: {local_path}")
                            finished_processes.append(prc)

                    for prc in finished_processes:
                        export_processes.remove(prc)

                    QtWidgets.QApplication.processEvents()

            helper.finished.emit()
            # Once all exports are done, then launches unreal. Maya File must be a saved path.
            # Since the maya exports are on their own thread, we need to wait for them to finish
            if scene_path:
                export_dir = os.path.dirname(export_path)
                json_dir = os.path.join(export_dir, "JSON")
                os.makedirs(json_dir, exist_ok=True)
                scene_name = os.path.splitext(os.path.basename(scene_path))[0]
                json_path = os.path.join(json_dir, scene_name + '.json').replace('\\', '/')

                if cinematic:
                    sequence_dict = sequence_utils.generate_sequence_dict_from_anim_dict(selected_anim_dict)
                    json_data.save_dict_to_json(sequence_dict, json_path)
                    if self.unreal_checkbox.isChecked():
                        usp.run_create_cinematic_sequence(json_path, "/Game/" + CINEMATIC_FOLDER,
                                                      self.uproject, self.log_path, self.cmd_path)
                else:
                    json_data.save_dict_to_json(selected_anim_dict, json_path)
                    if self.unreal_checkbox.isChecked():
                        usp.run_import_gameplay_animations(json_path, self.uproject, self.log_path, self.cmd_path)

        if len(export_processes) and is_maya():
            thread = threading.Thread(target=launch_unreal_after_export, args=(export_processes, export_path))
            thread.start()
        else:
            launch_unreal_after_export(export_processes, export_path)

    def load_data(self):
        """
        Loads the data from the ExportData node to populate the UI widgets
        :return: list with anim_dict
        """
        self.table_widget.setRowCount(0)
        export_data = sequence_utils.get_export_node_data()
        anim_dict, skeletons, namespace_skeleton_map, uproject, log_path, cmd_path, export_dir = export_data
        if not is_maya():
            if self.uproject and not skeletons:
                skel_data = usp.run_get_skeletons(self.uproject, self.log_path, self.cmd_path)
                if type(skel_data) == str:
                    self.skeletons = eval(skel_data)
                else:
                    self.skeletons = skel_data
            else:
                self.skeletons = skeletons
        else:
            self.skeletons = skeletons

        if anim_dict:
            self.anim_dict, skeletons, self.namespace_skeleton_map, self.uproject, self.log_path, self.cmd_path, \
            self.export_dir = export_data

        else:
            anim_dict = {}
            return [anim_dict, self.skeletons, self.uproject, self.export_dir]

        self.directory_widget.dir_name.setText(self.export_dir)

        for export_path in anim_dict:
            directory = os.path.dirname(export_path)
            anim = os.path.basename(export_path).split('.')[0]
            animation_data = anim_dict.get(export_path, None)
            if animation_data:
                start, end, namespace, skeleton, color, nodes = animation_data
                self.add_animation(anim=anim, directory=directory, start=start, end=end, namespace=namespace,
                                   skeleton=skeleton, color=eval(color), nodes=nodes)

        return [self.anim_dict, self.skeletons, self.uproject, self.export_dir]

    def store_data(self):
        """
        Stores the data for exports to the attributes on the ExportData node
        :return:
        """
        self.anim_dict = dict()
        for row in range(self.table_widget.rowCount()):

            export_path = os.path.join(self.table_widget.item(row, 1).text(),
                                       self.table_widget.item(row, 0).text() + '.fbx').replace('\\', '/')
            start_value = self.table_widget.cellWidget(row, 2).value()
            end_value = self.table_widget.cellWidget(row, 3).value()
            namespace = self.table_widget.item(row, 4).text()
            skeleton = self.table_widget.item(row, 5).text()
            color_str = str(self.table_widget.item(row, 0).background().color())
            color = color_str.replace("PySide6.", "")
            nodes = self.table_widget.item(row, 6).text()

            self.anim_dict[export_path] = [start_value, end_value, namespace, skeleton, color, nodes]

        sequence_utils.create_and_populate_export_node(self.anim_dict, self.skeletons, self.uproject,
                                                                     self.log_path, self.cmd_path,
                                                                     self.directory_widget.directory,
                                                                     self.namespace_skeleton_map)
    def create_file_menu(self):
        """
        Creates File Menu at top of Window
        :return:
        """
        file_menu = self.menu_bar.addMenu("File")

        export_action = file_menu.addAction("Export Data")
        export_action.triggered.connect(self.export_data)

        import_action = file_menu.addAction("Import Data")
        import_action.triggered.connect(self.import_data)

    def export_data(self):
        """
        Exports the UI Animations for loading into another file or package
        :return:
        """

        scene_path=sequence_utils.get_scene_path()
        scene_name = os.path.splitext(os.path.basename(scene_path))[0]
        default_filename = f"{scene_name}.json"

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Animation Data",
            default_filename,
            "JSON Files (*.json)"
        )

        if file_path:
            file_path = file_path.replace("\\", "/")

            json_data.save_dict_to_json(self.anim_dict, file_path)


    def import_data(self):
        """
        Imports Data from exported json (using the Export Data File Menu option, not the Export Animation option)
        :return:
        """
        scene_path=sequence_utils.get_scene_path()
        scene_name = os.path.splitext(os.path.basename(scene_path))[0]
        default_filename = f"{scene_name}.json"

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Export Animation Data",
            default_filename,
            "JSON Files (*.json)"
        )

        if file_path:
            file_path = file_path.replace("\\", "/")
            self.anim_dict = json_data.load_json_as_dict(file_path)
            sequence_utils.create_and_populate_export_node(self.anim_dict, self.skeletons, self.uproject,
                                                                         self.log_path, self.cmd_path,
                                                                         self.directory_widget.directory,
                                                                         self.namespace_skeleton_map)
            self.load_data()

    def get_uproject(self, directory):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Unreal Project", directory,
                                                             "Unreal Project (*.uproject)")
        if file_name:
            return file_name.replace('\\', '/')
        return None


def show_animation_manager():
    """
    Launches the Animation Manager UI in Maya.
    :return:
    """
    global anim_manager
    try:
        anim_manager.close()
    except:
        pass

    anim_manager = AnimationManagerUI()
    anim_manager.show()


if __name__ == "__main__":
    show_animation_manager()
