import unittest
import sys
from pathlib import Path
import os

# Add project root to python path
sys.path.append(str(Path("C:/depot/tools")))

# Set offscreen platform for headless PySide/Qt rendering in testing environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtWidgets, QtCore
from custom_qt.custom_widgets import LabeledSlider

class TestLabeledSlider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a single QApplication instance for all tests
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def test_labeled_slider_initialization(self):
        slider = LabeledSlider("Test Slider", min_val=10, max_val=200, default_val=50)
        self.assertEqual(slider.label.text(), "Test Slider")
        self.assertEqual(slider.value(), 50)
        self.assertEqual(slider.slider.minimum(), 10)
        self.assertEqual(slider.slider.maximum(), 200)
        self.assertEqual(slider.value_label.text(), "50")

    def test_labeled_slider_set_value(self):
        slider = LabeledSlider("Test Slider", min_val=10, max_val=200, default_val=50)
        slider.setValue(100)
        self.assertEqual(slider.value(), 100)
        self.assertEqual(slider.value_label.text(), "100")

    def test_labeled_slider_signal(self):
        slider = LabeledSlider("Test Slider", min_val=10, max_val=200, default_val=50)
        
        emitted_values = []
        def handler(val):
            emitted_values.append(val)
            
        slider.valueChanged.connect(handler)
        slider.setValue(75)
        
        self.assertEqual(emitted_values, [75])
        self.assertEqual(slider.value_label.text(), "75")

if __name__ == "__main__":
    unittest.main()
