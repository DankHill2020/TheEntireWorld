"""Application entry point."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from tech_connector.app.main_window import MainWindow


class VideoSplashScreen(QWidget):
    """Borderless video splash screen playing Tech Connector logo."""
    
    finished = Signal()

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget(self)
        layout.addWidget(self.video_widget)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.setSource(QUrl.fromLocalFile(video_path))
        self.player.mediaStatusChanged.connect(self._on_status_changed)
        self.resize(640, 360)

        # Center the window on screen
        screen = QApplication.primaryScreen()
        if screen:
            screen_geom = screen.geometry()
            self.move(
                (screen_geom.width() - self.width()) // 2,
                (screen_geom.height() - self.height()) // 2
            )

    def play(self):
        self.player.play()

    def stop(self):
        self.player.stop()

    def _on_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.finished.emit()


def show_main_window(win):
    """Show the main window in a normal, foreground-ready state."""
    try:
        win.showNormal()
    except Exception:
        win.show()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass


def run_application():
    app = QApplication(sys.argv)

    from tech_connector.services.settings_service import load_settings
    settings = load_settings()
    skip_video = settings.get("skip_splash_video", False)

    if skip_video:
        win = MainWindow()
        show_main_window(win)
        QTimer.singleShot(250, lambda: show_main_window(win))
    else:
        # 1. Initialize and show video splash screen
        video_path = str(Path("C:/depot/tools/tech_connector/assets/tech_connector_logo.mp4").resolve())
        splash = VideoSplashScreen(video_path)
        splash.show()
        splash.play()

        # Process events to force rendering of the splash screen immediately
        app.processEvents()

        # 2. Load the main window (done sequentially)
        win = MainWindow()

        # 3. Transition to main window after the video finishes playing (or fallback timeout)
        # Use a flag to ensure the transition runs exactly once
        transitioned = False

        def finish_splash():
            nonlocal transitioned
            if transitioned:
                return
            transitioned = True
            splash.stop()
            splash.close()
            show_main_window(win)
            QTimer.singleShot(250, lambda: show_main_window(win))

        splash.finished.connect(finish_splash)
        QTimer.singleShot(10000, finish_splash)

    sys.exit(app.exec())
