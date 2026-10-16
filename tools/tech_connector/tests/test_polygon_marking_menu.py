"""Focused regressions for Garden's polygon marking workflow."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu

from tech_connector.game_engine.authoring.tc_mesh_modeling_service import MeshTopology
from tech_connector.ui.dcc_viewer.mesh_painter.geometry import ThreeDMeshCanvas
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_01 import (
    ThreeDMeshPainterViewportMixin01,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Canvas:
    def update(self):
        pass


class _SelectionHost(ThreeDMeshPainterViewportMixin01):
    def __init__(self):
        self.viewport_mode = "Face"
        self.selected_mesh_vertex_indices = set()
        self.selected_mesh_edges = set()
        self.selected_mesh_face_indices = {0}
        self.canvas = _Canvas()
        self._resolved_shaded_status = ""
        self.topology = MeshTopology.from_data(
            [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
            [(0, 1, 4, 3), (1, 2, 5, 4)],
        )

    def _canonical_mesh_topology(self):
        return self.topology, [], []

    def update_viewport_status(self):
        pass


def test_face_selection_can_grow_and_shrink_by_adjacency() -> None:
    host = _SelectionHost()

    assert host.grow_mesh_component_selection() == {0, 1}

    host.selected_mesh_face_indices = {0}
    assert host.shrink_mesh_component_selection() == set()


def test_face_marking_menu_surfaces_direct_polygon_actions() -> None:
    _application()
    calls = []
    owner = SimpleNamespace(
        viewport_mode="Face",
        selected_mesh_face_indices={0},
        selected_mesh_vertex_indices=set(),
        selected_mesh_edges=set(),
        _component_selection_for_mode=lambda _mode: {0},
        set_viewport_interaction_mode=lambda mode: calls.append(("mode", mode)),
        select_all_mesh_components=lambda mode: calls.append(("all", mode)),
        clear_mesh_component_selection=lambda: calls.append(("clear",)),
        grow_mesh_component_selection=lambda: calls.append(("grow",)),
        shrink_mesh_component_selection=lambda: calls.append(("shrink",)),
        prompt_extrude_selected_faces=lambda: calls.append(("extrude",)),
        run_modeling_command_from_ui=lambda command: calls.append((command,)),
    )
    canvas = ThreeDMeshCanvas(viewport_owner=owner)
    menu = QMenu()

    canvas._populate_polygon_marking_menu(menu)

    labels = {action.text() for action in menu.actions()}
    assert {"Component Mode", "Extrude Faces…", "Delete Faces", "Triangulate Faces"} <= labels


def test_edge_marking_menu_includes_loop_bevel_and_bridge() -> None:
    _application()
    owner = SimpleNamespace(
        viewport_mode="Edge",
        selected_mesh_face_indices=set(),
        selected_mesh_vertex_indices=set(),
        selected_mesh_edges={(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)},
        _component_selection_for_mode=lambda _mode: {(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3)},
        set_viewport_interaction_mode=lambda _mode: None,
        select_all_mesh_components=lambda _mode: None,
        clear_mesh_component_selection=lambda: None,
        grow_mesh_component_selection=lambda: None,
        shrink_mesh_component_selection=lambda: None,
        prompt_bevel_selected_edges=lambda: None,
        prompt_split_selected_edge_loop=lambda: None,
        prompt_bridge_selected_edge_loops=lambda: None,
    )
    canvas = ThreeDMeshCanvas(viewport_owner=owner)
    menu = QMenu()

    canvas._populate_polygon_marking_menu(menu)

    actions = {action.text(): action for action in menu.actions()}
    assert actions["Bevel Edges…"].isEnabled()
    assert not actions["Insert Edge Loop…"].isEnabled()
    assert actions["Bridge Two Edge Loops"].isEnabled()
