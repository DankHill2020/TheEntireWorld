"""Focused regressions for the Garden-to-Kingdom level workflow."""

from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget, QTreeWidget, QWidget

from tech_connector.app.main_window_ui import MainWindowUiMixin
from tech_connector.ui.dcc_viewer.gpu_viewport import _mesh_scene_bounds
from tech_connector.ui.dcc_viewer.mesh_painter.geometry import MayaViewportCamera


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_garden_orbit_drag_rotates_camera_horizontally() -> None:
    camera = MayaViewportCamera()
    before_x = camera.project_world_to_screen((1.0, 0.0, 0.0), 800.0, 600.0)[0]

    camera.tumble(20.0, 0.0)

    after_x = camera.project_world_to_screen((1.0, 0.0, 0.0), 800.0, 600.0)[0]
    assert after_x < before_x


def test_garden_orbit_drag_rotates_camera_vertically() -> None:
    camera = MayaViewportCamera()
    before_y = camera.project_world_to_screen((0.0, 1.0, 0.0), 800.0, 600.0)[1]

    camera.tumble(0.0, 20.0)

    after_y = camera.project_world_to_screen((0.0, 1.0, 0.0), 800.0, 600.0)[1]
    assert after_y < before_y


def test_garden_pan_drag_follows_pointer_direction() -> None:
    camera = MayaViewportCamera()
    before_x, before_y, _ = camera.project_world_to_screen((0.0, 0.0, 0.0), 800.0, 600.0)

    camera.track(20.0, 20.0, 800.0, 600.0)

    after_x, after_y, _ = camera.project_world_to_screen((0.0, 0.0, 0.0), 800.0, 600.0)
    assert after_x > before_x
    assert after_y > before_y


def test_gpu_scene_bounds_ignore_invalid_vertices() -> None:
    mesh = types.SimpleNamespace(vertices=[
        types.SimpleNamespace(x=-2.0, y=1.0, z=4.0),
        types.SimpleNamespace(x=6.0, y=-3.0, z=2.0),
        types.SimpleNamespace(x=float("nan"), y=0.0, z=0.0),
    ])

    assert _mesh_scene_bounds(mesh) == ((-2.0, -3.0, 2.0), (6.0, 1.0, 4.0))


def test_kingdom_previews_an_unsaved_garden_level_when_save_is_cancelled() -> None:
    _application()

    class _Preview:
        def __init__(self):
            self.scene = None
            self.lighting_profile = ""

        def set_scene(self, mesh, *_args, **_kwargs):
            self.scene = mesh

        def set_camera(self, *_args, **_kwargs):
            pass

        def set_lighting_profile(self, profile_id):
            self.lighting_profile = profile_id

        def set_viewport_mode(self, mode):
            self.viewport_mode = mode
            return mode

        def set_viewport_exposure(self, exposure):
            self.viewport_exposure = exposure
            return exposure

        def set_grid_visible(self, visible):
            self.grid_visible = visible
            return visible

    mesh = types.SimpleNamespace(scene_proxy_objects=[{"name": "Hero", "type": "character"}])
    viewer = types.SimpleNamespace(
        _federated_scene_path="",
        _scene_lifecycle=types.SimpleNamespace(dirty=True),
        _dcc_deformation_bindings={},
        _last_scene_topology_signature="",
        mesh=mesh,
        viewport_camera=MayaViewportCamera(),
        simulation_world=None,
        save_federated_scene_dialog=lambda: False,
    )

    class _Host(MainWindowUiMixin):
        settings = {}
        _garden_workspace_tab = types.SimpleNamespace(garden_viewer=viewer)
        kingdom_runtime_viewport = _Preview()
        kingdom_level_label = QLabel()
        kingdom_viewport_status = QLabel()
        kingdom_world_outliner = QTreeWidget()

        def _set_kingdom_session_state(self, _state, message):
            self.kingdom_viewport_status.setText(message)

    host = _Host()
    assert host._save_and_sync_garden_level() == ""
    assert host.kingdom_runtime_viewport.scene is mesh
    assert host.kingdom_runtime_viewport.lighting_profile == "daylight"
    assert host.kingdom_level_label.text().startswith("Level: Untitled Garden Level")
    assert host.kingdom_world_outliner.topLevelItem(0).text(0) == "Hero"


def test_kingdom_reuses_unchanged_outliner_and_effect_streams() -> None:
    _application()

    class _Preview:
        def __init__(self):
            self.effect_updates = 0
            self.frame_updates = 0

        def set_scene(self, *_args, **_kwargs):
            pass

        def set_camera(self, *_args, **_kwargs):
            pass

        def update_effects(self, _world):
            self.effect_updates += 1

        def frame_scene(self, *_args, **_kwargs):
            self.frame_updates += 1
            return True

    effect_system = types.SimpleNamespace(emitters=[])
    world = types.SimpleNamespace(effect_system=effect_system, particles=[], time_seconds=0.0)
    viewer = types.SimpleNamespace(
        _federated_scene_path="Level.tcscene",
        _scene_lifecycle=types.SimpleNamespace(dirty=False),
        _dcc_deformation_bindings={},
        _last_scene_topology_signature="topology",
        _paint_geometry_revision=1,
        simulation_frame=1,
        simulation_world=world,
        mesh=types.SimpleNamespace(
            vertices=[types.SimpleNamespace(x=0.0, y=0.0, z=0.0)],
            faces=[(0, 0, 0)],
            scene_proxy_objects=[{"name": "Hero", "type": "character"}],
        ),
        viewport_camera=MayaViewportCamera(),
    )

    class _Host(MainWindowUiMixin):
        _garden_workspace_tab = types.SimpleNamespace(garden_viewer=viewer)
        kingdom_runtime_viewport = _Preview()
        kingdom_level_label = QLabel()
        kingdom_viewport_status = QLabel()
        kingdom_world_outliner = QTreeWidget()

    host = _Host()
    assert host._sync_kingdom_preview_from_garden()
    first_item = host.kingdom_world_outliner.topLevelItem(0)
    assert host._sync_kingdom_preview_from_garden()

    assert host.kingdom_world_outliner.topLevelItem(0) is first_item
    assert host.kingdom_runtime_viewport.effect_updates == 1
    assert host.kingdom_runtime_viewport.frame_updates == 1

    viewer.simulation_frame += 1
    world.time_seconds += 1.0 / 30.0
    assert host._sync_kingdom_preview_from_garden()
    assert host.kingdom_runtime_viewport.effect_updates == 2
    assert host.kingdom_runtime_viewport.frame_updates == 1

    viewer._last_scene_topology_signature = "topology-2"
    assert host._sync_kingdom_preview_from_garden()
    assert host.kingdom_runtime_viewport.frame_updates == 2


def test_kingdom_restores_the_last_saved_garden_level(tmp_path) -> None:
    level = tmp_path / "Main.tcscene"
    level.write_text("{}", encoding="utf-8")
    calls = []

    class _Viewer:
        _federated_scene_path = ""

        def load_federated_scene_file(self, path, *, interactive):
            calls.append((path, interactive))
            self._federated_scene_path = path
            return True, "Loaded"

    class _Host(MainWindowUiMixin):
        settings = {"last_tc_player_scene": str(level)}
        _garden_workspace_tab = types.SimpleNamespace(garden_viewer=_Viewer())

    assert _Host()._restore_last_garden_level()
    assert calls == [(str(level.resolve()), False)]


def test_visible_garden_tab_is_rebound_when_its_cache_attribute_was_lost() -> None:
    _application()
    garden = QWidget()
    garden.garden_viewer = object()

    class _Host(MainWindowUiMixin):
        def __init__(self):
            self.workspace_tabs = QTabWidget()
            self.workspace_tabs.addTab(garden, "The Garden (DCC Integration Suite)")
            self._garden_workspace_tab = None

        def set_workspace_tab_visible(self, *_args):
            pass

        def update_unified_prompt_context_label(self):
            pass

    host = _Host()
    host._show_workspace_tab(
        "The Garden (DCC Integration Suite)",
        "_garden_workspace_tab",
        lambda: (_ for _ in ()).throw(AssertionError("builder should not run")),
    )
    assert host._garden_workspace_tab is garden


def test_kingdom_workspace_prioritizes_level_workflow_over_commands(monkeypatch) -> None:
    _application()

    class _Preview(QWidget):
        backend_failed = None

        def set_scene(self, *_args, **_kwargs):
            pass

        def set_camera(self, *_args, **_kwargs):
            pass

        def set_lighting_profile(self, profile_id):
            self.lighting_profile = profile_id

        def set_viewport_mode(self, mode):
            self.viewport_mode = mode
            return mode

        def set_viewport_exposure(self, exposure):
            self.viewport_exposure = exposure
            return exposure

        def set_grid_visible(self, visible):
            self.grid_visible = visible
            return visible

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
    assert host.kingdom_runtime_viewport.lighting_profile == "daylight"
    assert host.kingdom_lighting_combo.count() >= 25
    neon_index = host.kingdom_lighting_combo.findData("neon_night")
    assert neon_index >= 0
    host.kingdom_lighting_combo.setCurrentIndex(neon_index)
    assert host.kingdom_runtime_viewport.lighting_profile == "neon_night"
    assert host.settings["kingdom_lighting_profile"] == "neon_night"
    lighting_only_index = host.kingdom_view_mode_combo.findData("lighting_only")
    host.kingdom_view_mode_combo.setCurrentIndex(lighting_only_index)
    assert host.kingdom_runtime_viewport.viewport_mode == "lighting_only"
    assert host.settings["kingdom_view_mode"] == "lighting_only"
    host.kingdom_grid_toggle.setChecked(False)
    assert host.kingdom_runtime_viewport.grid_visible is False
