import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport


def test_debug_vectors_build_cached_normals_and_paint() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    viewer = ThreeDMeshPainterViewport()
    try:
        viewer.gpu_viewport_enabled = False
        viewer.show_object_vector_handles = True
        viewer.show_vertex_normals = True
        viewer.show_face_normals = True
        viewer.debug_normal_stride = 8
        viewer.canvas.resize(900, 600)

        image = QImage(900, 600, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        viewer.canvas._draw_debug_vectors(painter, image.width(), image.height())
        painter.end()

        assert viewer.canvas._debug_vertex_normals
        assert viewer.canvas._debug_face_normals
        initial_cache_key = viewer.canvas._debug_normal_cache_key

        viewer.canvas._ensure_debug_normal_cache()
        assert viewer.canvas._debug_normal_cache_key == initial_cache_key

        viewer._paint_geometry_revision += 1
        viewer.canvas._ensure_debug_normal_cache()
        assert viewer.canvas._debug_normal_cache_key != initial_cache_key
    finally:
        viewer.close()
        app.processEvents()
