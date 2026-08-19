import unittest

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from tech_connector.services.dcc.dcc_viewport_stream import estimate_viewport_crop, window_description_score


class DccViewportStreamTests(unittest.TestCase):
    def test_scene_name_selects_the_correct_same_dcc_window(self):
        scene = "C:/shots/dragon/anim_v042.ma"

        correct = window_description_score("anim_v042.ma - Autodesk Maya 2026", "maya:7002", scene)
        other = window_description_score("lighting_v011.ma - Autodesk Maya 2026", "maya:7002", scene)

        self.assertGreater(correct, other)

    def test_provider_mismatch_is_not_capturable(self):
        self.assertLess(window_description_score("Character.blend - Blender", "maya:7001", ""), 0)

    def test_maya_viewport_crop_uses_panel_separators(self):
        image = QImage(1000, 700, QImage.Format_RGB32)
        image.fill(QColor(28, 31, 34))
        painter = QPainter(image)
        painter.fillRect(QRect(200, 100, 600, 500), QColor(96, 96, 96))
        painter.end()

        crop = estimate_viewport_crop(image, "maya:7001")

        self.assertIsNotNone(crop)
        self.assertAlmostEqual(crop.x(), 0.2, delta=0.01)
        self.assertAlmostEqual(crop.y(), 0.14, delta=0.01)
        self.assertAlmostEqual(crop.width(), 0.6, delta=0.02)

    def test_engine_viewport_crop_uses_wider_panel_search_ranges(self):
        image = QImage(1200, 800, QImage.Format_RGB32)
        image.fill(QColor(25, 28, 31))
        painter = QPainter(image)
        painter.fillRect(QRect(60, 48, 1080, 704), QColor(92, 96, 100))
        painter.end()

        for provider in ("blender:7021", "unreal:30010", "unity:7041"):
            with self.subTest(provider=provider):
                crop = estimate_viewport_crop(image, provider)
                self.assertIsNotNone(crop)
                self.assertAlmostEqual(crop.x(), 0.05, delta=0.01)
                self.assertAlmostEqual(crop.y(), 0.06, delta=0.01)
                self.assertAlmostEqual(crop.width(), 0.9, delta=0.02)


if __name__ == "__main__":
    unittest.main()
