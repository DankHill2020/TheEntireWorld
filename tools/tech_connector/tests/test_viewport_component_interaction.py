from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TECH_CONNECTOR_GPU_VIEWPORT", "0")
os.environ.setdefault("TECH_CONNECTOR_DCC_VIEWPORT_STREAM", "0")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport, _ProjectedMeshRaycaster
from tech_connector.ui.mesh_component_picker import (
    nearest_edge,
    unique_polygon_edges,
    vertices_in_rectangle,
)


def test_projected_raycaster_reports_nearest_source_face() -> None:
    vertices = [
        (0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 10.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (10.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 10.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (10.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ]
    raycaster = _ProjectedMeshRaycaster(vertices, [(0, 1, 2), (3, 4, 5)])

    assert raycaster.face_indices_at([(2.0, 2.0)]) == [1]
    assert raycaster.face_indices_at([(20.0, 20.0)]) == [None]


def test_pure_component_picker_supports_edges_and_marquee() -> None:
    vertices = [(10.0, 10.0, 1.0), (30.0, 10.0, 1.0), (30.0, 30.0, 1.0)]
    edges = unique_polygon_edges([(0, 1, 2)])

    assert nearest_edge(vertices, edges, 20.0, 11.0, tolerance=3.0) == (0, 1)
    assert vertices_in_rectangle(vertices, 5.0, 5.0, 31.0, 15.0) == {0, 1}


def test_vertex_mode_click_selects_without_starting_paint() -> None:
    app = QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()
    widget.canvas.resize(800, 600)
    vertex = widget.mesh.vertices[0]
    display = widget.shared_local_to_display_local((vertex.x, vertex.y, vertex.z))
    x, y, _depth = widget.viewport_camera.project_world_to_screen(display, 800.0, 600.0)
    widget.viewport_mode = "Vertex"
    widget.is_painting = False

    event = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    widget.canvas.mousePressEvent(event)

    assert len(widget.selected_mesh_vertex_indices) == 1
    assert widget.is_painting is False
    app.processEvents()


def test_shot_guide_handle_click_starts_drag_without_error() -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()
    widget.canvas.resize(800, 600)
    widget.set_shot_guide_mode("2-Point Perspective")
    point = widget.shot_guide_points_for_view(800.0, 600.0)["VP1"]
    event = QMouseEvent(
        QEvent.MouseButtonPress, point, point,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )

    widget.canvas.mousePressEvent(event)

    assert widget._active_shot_guide_handle == "VP1"


def test_edge_click_and_vertex_marquee_update_component_selection() -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()
    widget.canvas.resize(800, 600)
    topology, _raycast, projected, _camera = widget._project_mesh_component_data()
    first_edge = unique_polygon_edges(topology.faces)[0]
    first, second = projected[first_edge[0]], projected[first_edge[1]]
    midpoint = QPointF((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)

    picked = widget.select_mesh_component_at_viewport_position(midpoint, "Edge")
    assert isinstance(picked, tuple)
    assert picked in widget.selected_mesh_edges
    marquee = widget.select_mesh_components_in_viewport_rectangle(
        QPointF(0.0, 0.0), QPointF(800.0, 600.0), "Vertex",
    )

    assert len(marquee) > 1
    assert not widget.selected_mesh_edges


def test_component_keyboard_modes_and_accessibility_metadata() -> None:
    QApplication.instance() or QApplication([])
    widget = ThreeDMeshPainterViewport()

    widget.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_F9, Qt.NoModifier))
    widget.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.ControlModifier))

    assert widget.viewport_mode == "Edge"
    assert widget.selected_mesh_edges
    assert widget.canvas.accessibleName() == "3D scene viewport"
    assert widget.gizmo_mode_combo.accessibleName() == "Viewport interaction mode"
    assert "F9" in widget.gizmo_mode_combo.accessibleDescription()

    widget.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not widget.selected_mesh_edges
