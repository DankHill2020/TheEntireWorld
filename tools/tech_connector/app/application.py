"""Application entry point."""

from __future__ import annotations

from __future__ import annotations

from __future__ import annotations

import sys
import os
from pathlib import Path

from tech_connector.services.environment_service import (
    normalize_current_process_environment,
)

normalize_current_process_environment()

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QVBoxLayout
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from tech_connector.models.constants import TOOLS_ROOT, APP_ROOT

from tech_connector.app.main_window import MainWindow
from tech_connector.services.splash_preloader_service import SplashPreloadWorker


class VideoSplashScreen(QWidget):
    """Borderless video splash screen playing Tech Connector logo."""
    
    finished = Signal()

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
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


def _apply_window_show_mode(win, *, activate: bool = False):
    mode = str(getattr(win, "_restore_window_show_mode", "") or "")
    if mode == "fullscreen":
        win.showFullScreen()
    elif mode == "maximized":
        win.showMaximized()
    else:
        win.showNormal()
    if activate:
        try:
            win.raise_()
            win.activateWindow()
        except Exception:
            pass


def show_main_window(win):
    """Reveal the main window after any splash warmup has already realized it."""
    try:
        if win.testAttribute(Qt.WA_DontShowOnScreen):
            win.hide()
            win.setAttribute(Qt.WA_DontShowOnScreen, False)
    except Exception:
        pass
    try:
        win.setWindowOpacity(1.0)
    except Exception:
        pass
    try:
        if not win.isVisible():
            _apply_window_show_mode(win, activate=False)
        elif win.isMinimized():
            _apply_window_show_mode(win, activate=False)
    except Exception:
        win.show()


def realize_main_window_behind_splash(app: QApplication, win, splash) -> None:
    """Create the expensive native window/first-paint path while splash covers it."""
    try:
        win._last_live_process = "Startup: preparing main window behind splash"
    except Exception:
        pass
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen, True)
        win.setWindowOpacity(0.0)
    except Exception:
        pass
    try:
        _apply_window_show_mode(win, activate=False)
    except Exception:
        try:
            win.show()
        except Exception:
            pass
    try:
        win.ensurePolished()
    except Exception:
        pass
    try:
        layout = win.layout()
        if layout is not None:
            layout.activate()
    except Exception:
        pass
    try:
        if hasattr(splash, "raise_"):
            splash.raise_()
            splash.activateWindow()
    except Exception:
        pass
    try:
        app.processEvents()
    except Exception:
        pass
    try:
        win.hide()
    except Exception:
        pass
    try:
        win._last_live_process = "Startup: main window prepared behind splash"
    except Exception:
        pass


def run_application():
    app = QApplication(sys.argv)
    if os.environ.get("TECH_CONNECTOR_SMOKE_TEST"):
        QTimer.singleShot(0, app.quit)
        sys.exit(app.exec())

    def _on_app_exit():
        try:
            from tech_connector.bridges.session_authorization import clear_bridge_session

            clear_bridge_session()
        except Exception:
            pass
        try:
            from tech_connector.services.ollama_service import unload_all_ollama_models
            unload_all_ollama_models()
        except Exception:
            pass

    app.aboutToQuit.connect(_on_app_exit)

    # Complete all interactive licensing work before constructing MainWindow.
    # Its constructor schedules indexers, host bridges, watchers, and other
    # background services that must not run before entitlement is established.
    from tech_connector.app.licensing_gate import ensure_desktop_preflight
    from tech_connector.services.application_service import ApplicationService

    service = ApplicationService()
    try:
        licensed, licensing_reason, _warnings = ensure_desktop_preflight(service)
    except Exception as exc:
        licensed = False
        licensing_reason = str(exc) or "Tech Connector licensing could not be initialized."
    if not licensed:
        QMessageBox.critical(None, "Activation required", licensing_reason)
        app.quit()
        return

    from tech_connector.services.settings_service import load_settings
    settings = load_settings()
    skip_video = settings.get("skip_splash_video", False) or bool(os.environ.get("AI_STUDIO_SKIP_SPLASH"))

    if skip_video:
        win = MainWindow(
            application_service=service,
            license_preflight_complete=True,
        )
        show_main_window(win)
    else:
        # 1. Initialize and show video splash screen
        candidate_paths = [
            APP_ROOT / "assets" / "tech_connector_logo.mp4",
            TOOLS_ROOT / "tech_connector" / "assets" / "tech_connector_logo.mp4",
            TOOLS_ROOT / "assets" / "tech_connector_logo.mp4",
            APP_ROOT / "mobile_app" / "tech_connector_logo.mp4",
        ]
        video_path = ""
        for p in candidate_paths:
            if p.exists():
                video_path = str(p.resolve())
                break
        if not video_path:
            video_path = str((APP_ROOT / "assets" / "tech_connector_logo.mp4").resolve())
        splash = VideoSplashScreen(video_path)
        splash.show()
        splash.play()

        # Process events to force rendering of the splash screen immediately
        app.processEvents()

        # 2. Build and warm the main window while the splash video is visible.
        win = MainWindow(
            preload_for_splash=True,
            application_service=service,
            license_preflight_complete=True,
        )
        QTimer.singleShot(0, lambda: realize_main_window_behind_splash(app, win, splash))
        preloader = SplashPreloadWorker()
        win._splash_preloader = preloader
        win._splash_preloaded_cache = {}
        win._splash_reveal_complete = False

        preload_done = False
        window_warmup_done = False
        video_done = False

        # 3. Transition to main window after the video finishes playing (or fallback timeout)
        transitioned = False

        def maybe_finish_splash():
            if transitioned or not video_done or not preload_done or not window_warmup_done:
                return
            finish_splash()

        def mark_preload_finished(cache=None):
            nonlocal preload_done
            if preload_done:
                return
            preload_done = True
            if isinstance(cache, dict):
                win._splash_preloaded_cache = dict(cache)
            maybe_finish_splash()

        def mark_video_finished():
            nonlocal video_done
            video_done = True
            maybe_finish_splash()

        def mark_window_warmup_finished():
            nonlocal window_warmup_done
            if window_warmup_done:
                return
            window_warmup_done = True
            maybe_finish_splash()

        def finish_splash():
            nonlocal transitioned
            if transitioned:
                return
            transitioned = True
            try:
                win._last_live_process = "Startup: revealing main window"
            except Exception:
                pass
            splash.stop()
            splash.close()
            show_main_window(win)
            win._splash_reveal_complete = True
            try:
                win._last_live_process = ""
            except Exception:
                pass
            if hasattr(win, "prompt_deferred_startup_model_install"):
                QTimer.singleShot(300, win.prompt_deferred_startup_model_install)
            if hasattr(win, "run_deferred_startup_prompts"):
                QTimer.singleShot(450, win.run_deferred_startup_prompts)

        preloader.preload_finished.connect(mark_preload_finished)
        preloader.finished.connect(lambda: mark_preload_finished())
        preloader.start()

        try:
            win.startup_warmup_finished.connect(mark_window_warmup_finished)
        except Exception:
            pass
        splash.finished.connect(mark_video_finished)
        QTimer.singleShot(10000, mark_video_finished)
        QTimer.singleShot(30000, mark_preload_finished)
        QTimer.singleShot(30000, mark_window_warmup_finished)

    sys.exit(app.exec())
