import unittest
import sys
from pathlib import Path
import os

# Add project root to python path
sys.path.append(str(Path("C:/depot/tools")))

# Set offscreen platform for headless PySide/Qt rendering in testing environments
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtWidgets, QtCore
from tech_connector.app.application import VideoSplashScreen

class TestApplicationStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def test_video_splash_screen_initialization(self):
        video_path = "C:/depot/tools/tech_connector/assets/tech_connector_logo.mp4"
        splash = VideoSplashScreen(video_path)
        
        # Verify custom window flags are set correctly
        flags = splash.windowFlags()
        self.assertTrue(flags & QtCore.Qt.FramelessWindowHint)
        self.assertTrue(flags & QtCore.Qt.WindowStaysOnTopHint)
        
        # Verify media player source matches
        source = splash.player.source()
        self.assertEqual(source.toLocalFile(), video_path)
        
        # Verify dimensions (640x360)
        self.assertEqual(splash.width(), 640)
        self.assertEqual(splash.height(), 360)
        
        # Clean up
        splash.close()

    def test_settings_skip_splash_video_loaded(self):
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        self.assertIn("skip_splash_video", settings)
        # Default value should be False
        self.assertFalse(settings["skip_splash_video"])

if __name__ == "__main__":
    unittest.main()
