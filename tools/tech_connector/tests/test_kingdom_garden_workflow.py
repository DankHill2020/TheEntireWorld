"""Focused regressions for the Garden-to-Kingdom level workflow."""

from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from tech_connector.app.main_window_ui import MainWindowUiMixin
from tech_connector.ui.dcc_viewer.mesh_painter.geometry import MayaViewportCamera


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_garden_orbit_drag_follows_horizontal_pointer_direction() -> None:
    camera = MayaViewportCamera()
    before_x = camera.project_world_to_screen((1.0, 0.0, 0.0), 800.0, 600.0)[0]

    camera.tumble(20.0, 0.0)

    after_x = camera.project_world_to_screen((1.0, 0.0, 0.0), 800.0, 600.0)[0]
    assert after_x > before_x


def test_kingdom_workspace_prioritizes_level_workflow_over_commands(monkeypatch) -> None:
    _application()

    class _Preview(QWidget):
        backend_failed = None

        def set_scene(self, *_args, **_kwargs):
            pass

        def set_camera(self, *_args, **_kwargs):
            pass

    monkeypatch.setitem(
        sys.modules,
        "tech_connector.ui.three_d_gpu_viewport",
        types.SimpleNamespace(ThreeDGpuViewport=_Preview),
    )

    class _Host(MainWindowUiMixin, QWidget):
        def __init__(self):
            QWidget.__init__(self)
            self.settings = {}
            self._garden_workspace_tab = None

        def open_garden_workspace_tab(self):
            pass

        def play_tc_scene_path(self, _path):
            return True

        def stop_tc_play_in_editor(self):
            return True

        def build_tc_windows_player(self):
            return True

        def _ensure_visible_workspace_tab(self, _name):
            return True

        def execute_engine_console(self):
            pass

    host = _Host()
    workspace = host._build_the_kingdom_workspace_tab()
    button_text = {button.text() for button in workspace.findChildren(QPushButton)}
    label_text = {label.text() for label in workspace.findChildren(QLabel)}

    assert "Edit Level in Garden" in button_text
    assert "Sync Changes" in button_text
    assert "▶  Play Current Level" in button_text
    assert host.kingdom_world_outliner is not None
    assert host.kingdom_level_label.text().startswith("Level: No Garden level connected")
    assert "Runtime Command:" in label_text
