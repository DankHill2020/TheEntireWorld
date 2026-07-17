"""Application entry point."""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tech_connector.app.main_window import MainWindow


def show_main_window(win):
    """Show the main window in a normal, foreground-ready state."""
    try:
        win.showNormal()
    except Exception:
        win.show()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass


def run_application():
    app = QApplication(sys.argv)
    win = MainWindow()
    show_main_window(win)
    QTimer.singleShot(250, lambda: show_main_window(win))
    sys.exit(app.exec())
