try:
    from PySide6 import QtWidgets, QtCore, QtGui
    PYQT_VERSION = 6
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    PYQT_VERSION = 2

from functools import partial


class NonScrollingSpinBox(QtWidgets.QSpinBox):

    def wheelEvent(self, event):
        event.ignore()


class BrowseDirectory(QtWidgets.QWidget):
    def __init__(self, directory=None):
        super(BrowseDirectory, self).__init__()
        self.directory = directory
        main_layout = QtWidgets.QVBoxLayout()
        browse_layout = QtWidgets.QHBoxLayout()
        self.setLayout(main_layout)
        current_width = self.width()
        new_height = 10
        self.resize(current_width, new_height)
        main_layout.addLayout(browse_layout)
        self.dir_name = QtWidgets.QLineEdit(directory.replace('\\', '/'))
        browse_layout.addWidget(self.dir_name)
        self.file_btn = QtWidgets.QPushButton("Browse")
        self.file_btn.setStyleSheet("QPushButton { text-align: center; border: 1px solid #e1e1e1; padding:5px; "
                                    "border-radius:1px; } ")
        browse_layout.addWidget(self.file_btn)

        self.file_btn.clicked.connect(partial(lambda: self.get_dir(self.dir_name, self.directory)))
        current_width = self.width()
        new_height = 10
        self.resize(current_width, new_height)
        self.dir_name.textChanged.connect(self.update_directory_from_text)

    def get_dir(self, widget, directory):
        dir_name = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr('Select Batch Directory'),
            directory,
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if dir_name:
            clean_dir = dir_name.replace('\\', '/')
            self.directory = clean_dir
            widget.setText(clean_dir)
        return self.directory

    def update_directory_from_text(self, text):
        self.directory = text.replace('\\', '/')


class ListProgressBar(QtWidgets.QDialog):
    def __init__(self, item_list, parent=None):
        super(ListProgressBar, self).__init__(parent)

        self.item_list = item_list
        self.total_items = len(self.item_list)
        self.current_index = 0

        # Setup window flags correctly
        self.setWindowTitle("Export Progress")
        self.setWindowFlags(
            QtCore.Qt.Window |
            QtCore.Qt.WindowCloseButtonHint |
            QtCore.Qt.WindowStaysOnTopHint
        )

        # Setup UI
        self.label = QtWidgets.QLabel("Starting...", self)
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)

        self.resize(400, 120)
        self.reset()

    def reset(self):
        self.current_index = 0
        self.progress_bar.setValue(0)
        if self.item_list:
            self.label.setText(f"Ready to export {self.item_list[0]}")

    def start(self):
        """Start the progress manually (optional if you want a 'start' call)."""
        if self.item_list:
            self.label.setText(f"Exporting Animation for {self.item_list[0]}")
            self.progress_bar.setValue(0)

    def update_progress(self):
        """Call this AFTER each export is done."""
        if self.current_index >= self.total_items:
            self.label.setText("Completed!")
            self.progress_bar.setValue(100)
            return

        progress_percent = int((self.current_index + 1) / self.total_items * 100)
        self.progress_bar.setValue(progress_percent)
        self.label.setText(f"Exporting Animation for {self.item_list[self.current_index]}")

        self.current_index += 1