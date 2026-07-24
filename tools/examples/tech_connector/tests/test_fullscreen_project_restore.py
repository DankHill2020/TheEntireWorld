from __future__ import annotations

from unittest import TestCase

from tech_connector.app.main_window_workflows import MainWindowWorkflowsMixin


class _Widget:
    def __init__(self, visible=False):
        self.visible = visible
        self.checked = False
        self.text = ""

    def isVisible(self):
        return self.visible

    def setVisible(self, visible):
        self.visible = bool(visible)

    def show(self):
        self.visible = True

    def raise_(self):
        pass

    def setFocus(self):
        pass

    def setChecked(self, checked):
        self.checked = bool(checked)

    def setText(self, text):
        self.text = text


class _Splitter:
    def __init__(self):
        self.current_sizes = [0, 1000]

    def sizes(self):
        return list(self.current_sizes)

    def setSizes(self, sizes):
        self.current_sizes = list(sizes)


class _Window:
    toggle_main_window_fullscreen = MainWindowWorkflowsMixin.toggle_main_window_fullscreen

    def __init__(self):
        self.workspace_tabs = _Widget(True)
        self.left_panel = _Widget(False)
        self.project_restore_btn = _Widget(True)
        self.main_fullscreen_btn = _Widget(True)
        self.main_splitter = _Splitter()

    def _main_layout_widgets_for_focus_mode(self):
        return []


class FullscreenProjectRestoreTests(TestCase):
    def test_hidden_project_panel_remains_recoverable_in_and_after_focus_mode(self):
        window = _Window()

        window.toggle_main_window_fullscreen()
        self.assertTrue(window.project_restore_btn.isVisible())
        self.assertFalse(window.left_panel.isVisible())

        window.toggle_main_window_fullscreen()
        self.assertTrue(window.project_restore_btn.isVisible())
        self.assertFalse(window.left_panel.isVisible())

    def test_visible_project_panel_is_restored_after_focus_mode(self):
        window = _Window()
        window.left_panel.setVisible(True)
        window.project_restore_btn.setVisible(False)
        window.main_splitter.setSizes([320, 680])

        window.toggle_main_window_fullscreen()
        self.assertFalse(window.project_restore_btn.isVisible())
        self.assertFalse(window.left_panel.isVisible())

        window.toggle_main_window_fullscreen()
        self.assertFalse(window.project_restore_btn.isVisible())
        self.assertTrue(window.left_panel.isVisible())
