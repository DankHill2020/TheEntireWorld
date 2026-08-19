import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

import tech_connector.ui.three_d_mesh_painter_widget as mesh_painter


def _alpha_pixels(image: QImage):
    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    return mesh_painter.np.frombuffer(
        rgba.bits(),
        dtype=mesh_painter.np.uint8,
        count=rgba.bytesPerLine() * rgba.height(),
    ).reshape((rgba.height(), rgba.bytesPerLine()))[:, : rgba.width() * 4].reshape(
        (rgba.height(), rgba.width(), 4)
    )[:, :, 3].copy()


class MeshBrushHotPathTests(unittest.TestCase):
    def setUp(self):
        if mesh_painter.np is None:
            self.skipTest("NumPy acceleration is not installed")
        mesh_painter._BRUSH_ALPHA_ARRAY_CACHE.clear()
        mesh_painter._BRUSH_STAMP_IMAGE_CACHE.clear()
        mesh_painter._BRUSH_ALPHA_PREVIEW_CACHE.clear()

    def test_vectorized_stamp_matches_scalar_alpha(self):
        profile = mesh_painter.MeshBrushProfile(
            hardness=0.55,
            opacity=0.9,
            grain=0.2,
            alpha_mask="noisy_round",
        )
        accelerated = _alpha_pixels(
            mesh_painter.build_brush_stamp_image(profile, 64, QColor(22, 242, 106))
        )

        numpy_module = mesh_painter.np
        try:
            mesh_painter.np = None
            mesh_painter._BRUSH_ALPHA_ARRAY_CACHE.clear()
            mesh_painter._BRUSH_STAMP_IMAGE_CACHE.clear()
            scalar = mesh_painter.build_brush_stamp_image(profile, 64, QColor(22, 242, 106))
        finally:
            mesh_painter.np = numpy_module

        difference = mesh_painter.np.abs(
            accelerated.astype(mesh_painter.np.int16) - _alpha_pixels(scalar).astype(mesh_painter.np.int16)
        )
        self.assertLessEqual(int(difference.max()), 1)

    def test_custom_alpha_softness_preserves_tip_and_widens_edge(self):
        source = QImage(17, 17, QImage.Format_ARGB32)
        source.fill(Qt.transparent)
        for y in range(6, 11):
            for x in range(6, 11):
                source.setPixelColor(x, y, QColor(255, 255, 255, 255))
        alpha_path = "test://square-tip"
        mesh_painter._BRUSH_ALPHA_IMAGE_CACHE[alpha_path] = source
        hard = mesh_painter._brush_alpha_array(
            mesh_painter.MeshBrushProfile(hardness=1.0, alpha_mask="texture", alpha_path=alpha_path),
            68,
        )
        soft = mesh_painter._brush_alpha_array(
            mesh_painter.MeshBrushProfile(hardness=0.15, alpha_mask="texture", alpha_path=alpha_path),
            68,
        )

        self.assertGreater(float(hard[34, 34]), 0.95)
        self.assertGreater(float(soft[34, 34]), 0.1)
        self.assertEqual(float(hard[34, 18]), 0.0)
        self.assertGreater(float(soft[34, 18]), 0.0)
        self.assertEqual(float(soft[2, 2]), 0.0)

    def test_projected_raycaster_matches_scalar_nearest_surface(self):
        vertices = [
            (0, 0, 2, 0, 0, 2, 0, 0),
            (0, 10, 2, 0, 10, 2, 0, 1),
            (10, 0, 2, 10, 0, 2, 1, 0),
            (0, 0, 1, 100, 100, 1, 0.2, 0.2),
            (0, 10, 1, 100, 110, 1, 0.2, 0.8),
            (10, 0, 1, 110, 100, 1, 0.8, 0.2),
        ]
        faces = [(0, 1, 2), (3, 4, 5)]
        points = [(2, 2), (20, 20)]
        accelerated = mesh_painter._ProjectedMeshRaycaster(vertices, faces).hits(points)

        numpy_module = mesh_painter.np
        try:
            mesh_painter.np = None
            scalar = mesh_painter._ProjectedMeshRaycaster(vertices, faces).hits(points)
        finally:
            mesh_painter.np = numpy_module

        self.assertIsNone(accelerated[1])
        self.assertIsNone(scalar[1])
        for accelerated_value, scalar_value in zip(accelerated[0], scalar[0]):
            self.assertAlmostEqual(accelerated_value, scalar_value, places=5)


if __name__ == "__main__":
    unittest.main()
