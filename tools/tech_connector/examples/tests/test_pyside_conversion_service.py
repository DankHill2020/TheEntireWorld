import unittest

from tech_connector.services.pyside_conversion_service import convert_pyside_to_pyside6


class TestPySideConversionService(unittest.TestCase):
    def test_converts_imports_moved_qtgui_symbols_and_exec(self) -> None:
        source = (
            "from PySide2.QtWidgets import QApplication, QWidget, QAction, QShortcut\n"
            "from PySide2.QtCore import Qt\n"
            "import shiboken2\n\n"
            "app = QApplication([])\n"
            "screen = QApplication.desktop()\n"
            "alignment = Qt.AlignCenter\n"
            "dialog.exec_()\n"
            "menu.exec_(pos)\n"
        )

        result = convert_pyside_to_pyside6(source)

        self.assertTrue(result.changed)
        self.assertIn("from PySide6.QtWidgets import QApplication, QWidget", result.source)
        self.assertIn("from PySide6.QtGui import QAction, QGuiApplication, QShortcut", result.source)
        self.assertIn("from PySide6.QtCore import Qt", result.source)
        self.assertIn("import shiboken6", result.source)
        self.assertIn("QGuiApplication.primaryScreen()", result.source)
        self.assertIn("dialog.exec()", result.source)
        self.assertIn("menu.exec(pos)", result.source)
        self.assertNotIn("PySide2", result.source)
        self.assertNotIn("exec_(", result.source)
        self.assertTrue(any("Qt enum aliases" in item for item in result.warnings))

    def test_warns_for_qdesktopwidget_and_qregexp(self) -> None:
        result = convert_pyside_to_pyside6(
            "from PyQt5.QtWidgets import QDesktopWidget\n"
            "from PyQt5.QtCore import QRegExp\n"
        )

        self.assertIn("from PySide6.QtWidgets import QDesktopWidget", result.source)
        self.assertTrue(any("QDesktopWidget" in item for item in result.warnings))
        self.assertTrue(any("QRegExp" in item for item in result.warnings))

    def test_compatible_mode_prefers_pyside6_without_dropping_pyside2_fallback(self) -> None:
        source = (
            "try:\n"
            "    from PySide2 import QtWidgets, QtCore, QtGui\n"
            "    PYQT_VERSION = 2\n"
            "except ImportError:\n"
            "    from PySide6 import QtWidgets, QtCore, QtGui\n"
            "    PYQT_VERSION = 6\n\n"
            "if PYQT_VERSION == 6:\n"
            "    action = menu.exec(pos)\n"
            "else:\n"
            "    action = menu.exec_(pos)\n"
        )

        result = convert_pyside_to_pyside6(source, strict=False)

        self.assertTrue(result.changed)
        self.assertLess(result.source.index("from PySide6"), result.source.index("from PySide2"))
        self.assertIn("from PySide2 import QtWidgets, QtCore, QtGui", result.source)
        self.assertIn("PYQT_VERSION = 2", result.source)
        self.assertIn("action = menu.exec_(pos)", result.source)


if __name__ == "__main__":
    unittest.main()
