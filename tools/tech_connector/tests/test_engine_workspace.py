from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QTreeWidget, QVBoxLayout, QWidget

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService
from tech_connector.ui.game_engine.engine_workspace import EngineWorkspaceWindow


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


class FakeLevelViewport(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.scene_outliner = QTreeWidget(self); self.scene_outliner.setHeaderLabels(["Actor", "Type", "State"])
        self.instance_details_panel = QFrame(self)
        self.scene_left_panel = QWidget(self); layout = QVBoxLayout(self.scene_left_panel); layout.addWidget(self.scene_outliner); layout.addWidget(self.instance_details_panel)
        self._federated_scene_path = ""; self.simulating = False; self.tool = "select"; self.placed = []; self.sequence_commands = []; self.steps = 0
        self.undo_count = 0; self.redo_count = 0; self.focus_count = 0; self.orientation = "world"; self.snap = {}; self.placement = {}; self.wireframe = False
        self.created = []; self.actor_ops = []

    def load_federated_scene_file(self, path: str, *, interactive: bool = True):
        self._federated_scene_path = str(path); return True, f"Loaded {Path(path).name}"

    def _save_federated_scene_to_path(self, path: str): return bool(path)
    def save_federated_scene_dialog(self): return False
    def set_simulation_playing(self, playing: bool): self.simulating = bool(playing)
    def step_simulation(self): self.steps += 1
    def set_transform_tool(self, tool: str): self.tool = str(tool)
    def place_asset_from_browser(self, payload): self.placed.append(dict(payload)); return True
    def apply_level_sequence_command(self, payload): self.sequence_commands.append(dict(payload))
    def undo_viewer_action(self): self.undo_count += 1
    def redo_viewer_action(self): self.redo_count += 1
    def focus_selected_scene_element(self): self.focus_count += 1; return True
    def change_transform_orientation_mode(self, mode): self.orientation = str(mode).casefold()
    def configure_transform_snapping(self, **settings): self.snap = dict(settings); return self.snap
    def configure_asset_placement(self, **settings): self.placement = dict(settings); return self.placement
    def toggle_wireframe_display(self, enabled): self.wireframe = bool(enabled)
    def create_level_actor(self, actor_type): self.created.append(actor_type); return {"name": actor_type}
    def duplicate_selected_level_actor(self): self.actor_ops.append("duplicate"); return True
    def delete_selected_level_actor(self): self.actor_ops.append("delete"); return True


def test_engine_workspace_exposes_real_editor_surfaces_and_modes(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    workspace = EngineWorkspaceWindow(tmp_path, database=database, viewport_factory=FakeLevelViewport)
    assert workspace.centralWidget() is workspace.viewport
    assert workspace.world_outliner_dock.widget() is workspace.viewport.scene_outliner
    assert workspace.details_dock.widget() is workspace.actor_details
    assert workspace.content_dock.widget() is workspace.asset_browser
    assert workspace.asset_editor_dock.widget() is workspace.asset_editor
    assert workspace.sequence_dock.widget() is workspace.sequence_editor
    assert workspace.world_settings_dock.widget() is workspace.world_settings
    assert workspace.console_dock.widget() is workspace.console_panel
    assert workspace.profiler_dock.widget() is workspace.profiler_panel
    assert workspace.build_dock.widget() is workspace.build_panel
    assert workspace.world_production_dock.widget() is workspace.world_production

    workspace.set_transform_tool("translate"); assert workspace.viewport.tool == "translate"
    workspace.undo(); workspace.redo(); assert (workspace.viewport.undo_count, workspace.viewport.redo_count) == (1, 1)
    assert workspace.focus_selected(); assert workspace.viewport.focus_count == 1
    workspace.coordinate_space.setCurrentIndex(1); assert workspace.viewport.orientation == "object"
    workspace.move_snap.setCurrentIndex(3); workspace.rotate_snap.setCurrentIndex(2); workspace.scale_snap.setCurrentIndex(2)
    assert workspace.viewport.snap == {"translation": 10.0, "rotation": 10.0, "scale": 0.05}
    assert workspace.viewport.placement["grid_snap"] and workspace.viewport.placement["grid_size"] == 10.0
    workspace.view_mode.setCurrentIndex(2); assert workspace.viewport.wireframe
    assert workspace.create_actor("camera") and workspace.viewport.created == ["camera"]
    assert workspace.duplicate_selected_actor() and workspace.delete_selected_actor()
    assert workspace.viewport.actor_ops == ["duplicate", "delete"]
    assert workspace.set_mode("simulate"); assert workspace.viewport.simulating
    workspace.pause(); assert not workspace.viewport.simulating
    workspace.step(); assert workspace.viewport.steps == 1
    assert workspace.set_mode("edit")
    workspace.world_settings.time_of_day.setValue(19.5)
    assert workspace.viewport._engine_world_settings["time_of_day"] == 19.5
    state = workspace.save_layout_state(); assert state; assert workspace.restore_layout_state(state)


def test_engine_workspace_loads_levels_places_assets_and_opens_sequences(tmp_path) -> None:
    database = AssetDatabase(tmp_path / ".tech_connector" / "assets.sqlite3")
    operations = AssetOperationsService(tmp_path, database)
    level = operations.create_asset("tc.level", "Main", folder="Assets/Levels")
    sequence = operations.create_asset("tc.level_sequence", "Intro", folder="Assets/Cinematics")
    terrain = operations.create_asset("tc.terrain", "Landscape", folder="Assets/World", properties={"resolution": [9, 9], "erosion": {"mode": "none"}})
    mesh_path = tmp_path / "Assets" / "Meshes" / "Crate.fbx"; mesh_path.parent.mkdir(parents=True); mesh_path.write_bytes(b"fbx")
    mesh = database.register_asset(mesh_path, "tc.static_mesh")
    workspace = EngineWorkspaceWindow(tmp_path, database=database, viewport_factory=FakeLevelViewport)

    assert workspace.open_asset(level.destination_path, "tc.level", level.asset_id)
    assert workspace.current_level_path.endswith("Main.tcscene")
    assert workspace.place_asset(str(mesh.source_path), mesh.asset_type, mesh.asset_id)
    assert workspace.viewport.placed[0]["asset_id"] == mesh.asset_id
    assert workspace.open_asset(sequence.destination_path, "tc.level_sequence", sequence.asset_id)
    assert workspace.sequence_dock.isVisible() or not workspace.isVisible()
    assert workspace._sequence_asset_id == sequence.asset_id
    assert workspace.save_all()
    assert workspace.open_asset(terrain.destination_path, "tc.terrain", terrain.asset_id)
    assert workspace.viewport._tc_world_visualization["kind"] == "terrain"
    assert workspace.viewport._tc_world_brush_callback(0.5, 0.5, False)
    assert workspace.asset_editor._specialized_dirty
    assert workspace.open_or_create_settings("tc.project_settings", "ProjectSettings")
    assert any(record.asset_type == "tc.project_settings" for record in database.list_assets())
