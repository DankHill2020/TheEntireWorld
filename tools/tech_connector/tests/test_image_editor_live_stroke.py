from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from tech_connector.ui.image_viewer.canvas import ImageLayer, LayerStack
from tech_connector.ui.image_viewer.editor import ImageEditorWidget


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _mouse_event(event_type, position: QPointF, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        position,
        position,
        button,
        buttons,
        Qt.NoModifier,
    )


def test_brush_draws_on_press_and_keeps_one_undo_snapshot_per_drag() -> None:
    app = _application()
    editor = ImageEditorWidget()
    editor.resize(1100, 760)
    editor.show()
    app.processEvents()

    layer = editor.stack.active_layer
    assert layer is not None
    scene_point = QPointF(64.0, 64.0)
    local_point = QPointF(editor.view.mapFromScene(scene_point))
    before_color = layer.image.pixelColor(64, 64)
    before_history = len(editor.stack.history)

    editor.view.mousePressEvent(_mouse_event(QEvent.MouseButtonPress, local_point, Qt.LeftButton, Qt.LeftButton))

    assert layer.image.pixelColor(64, 64) != before_color
    assert len(editor.stack.history) == before_history

    move_scene_point = QPointF(120.0, 64.0)
    move_local_point = QPointF(editor.view.mapFromScene(move_scene_point))
    editor.view.mouseMoveEvent(_mouse_event(QEvent.MouseMove, move_local_point, Qt.NoButton, Qt.LeftButton))

    assert layer.image.pixelColor(100, 64) != before_color
    assert len(editor.stack.history) == before_history

    editor.view.mouseReleaseEvent(_mouse_event(QEvent.MouseButtonRelease, move_local_point, Qt.LeftButton, Qt.NoButton))

    assert len(editor.stack.history) == before_history + 1
    assert editor.dirty
    editor.close()


def test_dirty_region_composite_matches_full_canvas() -> None:
    stack = LayerStack(128, 96)
    stack.add_layer(ImageLayer("Base", 128, 96, QColor(20, 30, 40)))
    overlay = ImageLayer("Overlay", 128, 96)
    overlay.opacity = 0.65
    overlay.blend_mode = "Screen"
    painter = QPainter(overlay.image)
    painter.fillRect(20, 15, 50, 40, QColor(180, 40, 90, 220))
    painter.end()
    stack.add_layer(overlay)

    dirty = QRectF(14.0, 9.0, 70.0, 58.0)
    region, aligned = stack.composite_region(dirty)
    expected = stack.composite().copy(aligned.toAlignedRect())

    assert region == expected
