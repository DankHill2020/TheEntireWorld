"""Session-aware DCC application-window streaming through Qt Multimedia."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import time

from PySide6.QtCore import QObject, QRectF, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QCapturableWindow, QMediaCaptureSession, QVideoFrame, QVideoSink, QWindowCapture

try:
    import numpy as np
except Exception:  # pragma: no cover - stripped runtime fallback.
    np = None


PROVIDER_WINDOW_TOKENS = {
    "maya": ("maya", "autodesk maya"),
    "blender": ("blender",),
    "houdini": ("houdini", "sidefx"),
    "motionbuilder": ("motionbuilder", "autodesk motionbuilder"),
    "unreal": ("unreal editor", "unreal engine"),
    "unity": ("unity",),
    "3dsmax": ("3ds max", "autodesk 3ds max"),
    "max": ("3ds max", "autodesk 3ds max"),
}


def window_description_states(description: str) -> list[tuple[int, bool]]:
    """Return matching top-level Win32 window PIDs/states in enumeration order."""
    if os.name != "nt" or not str(description or "").strip():
        return []
    target = str(description).strip()
    matches: list[tuple[int, bool]] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def collect(hwnd, _lparam):
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value.strip() == target:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            matches.append((int(pid.value), bool(user32.IsWindowEnabled(hwnd))))
        return True

    try:
        user32.EnumWindows(collect, 0)
    except Exception:
        return []
    return matches


def window_description_is_enabled(description: str) -> bool | None:
    states = window_description_states(description)
    return any(enabled for _pid, enabled in states) if states else None


def window_description_score(description: str, provider: str, scene: str = "") -> int:
    """Rank a capturable app window against one bridge session."""
    text = str(description or "").strip().lower()
    provider_base = str(provider or "").split(":", 1)[0].strip().lower()
    if not text:
        return -1000
    tokens = PROVIDER_WINDOW_TOKENS.get(provider_base, (provider_base,))
    score = max((80 if token and token in text else -1000) for token in tokens)
    if score < 0:
        return score
    scene_name = Path(str(scene or "")).name.lower()
    scene_stem = Path(scene_name).stem
    if scene_name and scene_name in text:
        score += 120
    elif scene_stem and scene_stem in text:
        score += 90
    if "untitled" in text and not scene_name:
        score += 20
    return score


def estimate_viewport_crop(image: QImage, provider: str) -> QRectF | None:
    """Detect the central DCC viewport from strong dock/panel separator edges."""
    if np is None or image.isNull() or image.width() < 400 or image.height() < 300:
        return None
    provider_base = str(provider or "").split(":", 1)[0].lower()
    if provider_base not in {
        "maya",
        "blender",
        "houdini",
        "motionbuilder",
        "unreal",
        "unity",
        "3dsmax",
        "max",
    }:
        return None
    rgba = image.convertToFormat(QImage.Format_RGBA8888)
    pixels = np.frombuffer(
        rgba.bits(),
        dtype=np.uint8,
        count=rgba.width() * rgba.height() * 4,
    ).reshape((rgba.height(), rgba.width(), 4))
    luminance = pixels[:, :, :3].astype(np.float32).mean(axis=2)
    vertical = np.abs(np.diff(luminance, axis=1))[int(rgba.height() * 0.08) : int(rgba.height() * 0.92)].mean(axis=0)
    horizontal = np.abs(np.diff(luminance, axis=0))[:, int(rgba.width() * 0.05) : int(rgba.width() * 0.95)].mean(axis=1)

    def strongest(values, start_ratio: float, end_ratio: float) -> tuple[int, float]:
        start = max(0, min(len(values) - 1, int(len(values) * start_ratio)))
        end = max(start + 1, min(len(values), int(len(values) * end_ratio)))
        offset = int(np.argmax(values[start:end]))
        index = start + offset
        return index, float(values[index])

    if provider_base in {"maya", "motionbuilder", "houdini", "3dsmax", "max"}:
        edge_ranges = (0.12, 0.45, 0.55, 0.90, 0.07, 0.38, 0.58, 0.95)
    else:
        edge_ranges = (0.02, 0.48, 0.52, 0.98, 0.03, 0.40, 0.60, 0.98)
    left, left_strength = strongest(vertical, edge_ranges[0], edge_ranges[1])
    right, right_strength = strongest(vertical, edge_ranges[2], edge_ranges[3])
    top, top_strength = strongest(horizontal, edge_ranges[4], edge_ranges[5])
    bottom, bottom_strength = strongest(horizontal, edge_ranges[6], edge_ranges[7])
    if min(left_strength, right_strength, top_strength, bottom_strength) < 20.0:
        return None
    width = right - left
    height = bottom - top
    if width < rgba.width() * 0.35 or height < rgba.height() * 0.35:
        return None
    return QRectF(
        float(left + 1) / rgba.width(),
        float(top + 1) / rgba.height(),
        float(max(1, width - 1)) / rgba.width(),
        float(max(1, height - 1)) / rgba.height(),
    )


class DccViewportStream(QObject):
    """Capture one DCC window only while a source-stream display mode is active."""

    frame_ready = Signal(QImage, str)
    status_changed = Signal(str)

    def __init__(self, parent: QObject | None = None, *, max_fps: float = 30.0):
        super().__init__(parent)
        self.capture = QWindowCapture(self)
        self.session = QMediaCaptureSession(self)
        self.sink = QVideoSink(self)
        self.session.setWindowCapture(self.capture)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_video_frame)
        self.capture.errorOccurred.connect(self._on_capture_error)
        self.provider_key = ""
        self.scene = ""
        self.crop_rect = QRectF(0.0, 0.0, 1.0, 1.0)
        self.min_frame_interval = 1.0 / max(1.0, float(max_fps))
        self._last_frame_at = 0.0
        self._auto_crop_pending = False
        self._window: QCapturableWindow | None = None
        self._start_generation = 0
        self._last_error = ""
        self._desired_active = False
        self.process_id = 0

    @property
    def active(self) -> bool:
        return bool(self.capture.isActive())

    @staticmethod
    def matching_window(provider: str, scene: str = "", process_id: int = 0) -> QCapturableWindow | None:
        best = None
        best_score = -1000
        description_occurrences: dict[str, int] = {}
        state_cache: dict[str, list[tuple[int, bool]]] = {}
        for window in QWindowCapture.capturableWindows():
            try:
                if not window.isValid():
                    continue
                description = window.description()
                score = window_description_score(description, provider, scene)
                states = state_cache.setdefault(description, window_description_states(description))
                occurrence = description_occurrences.get(description, 0)
                description_occurrences[description] = occurrence + 1
                if occurrence < len(states):
                    candidate_pid, enabled = states[occurrence]
                    if not enabled or (process_id and candidate_pid != int(process_id)):
                        continue
                elif window_description_is_enabled(description) is False:
                    continue
            except Exception:
                continue
            if score > best_score:
                best = window
                best_score = score
        return best if best_score >= 0 else None

    def start(
        self,
        provider: str,
        *,
        scene: str = "",
        crop_rect: QRectF | None = None,
        process_id: int = 0,
    ) -> bool:
        self.stop()
        self._start_generation += 1
        generation = self._start_generation
        self._desired_active = True
        self.provider_key = str(provider or "").strip().lower()
        self.scene = str(scene or "")
        self.process_id = max(0, int(process_id or 0))
        self.crop_rect = QRectF(crop_rect) if crop_rect is not None else QRectF(0.0, 0.0, 1.0, 1.0)
        self._auto_crop_pending = crop_rect is None
        window = self.matching_window(self.provider_key, self.scene, self.process_id)
        if window is None:
            self.status_changed.emit(f"No capturable {self.provider_key or 'DCC'} window matched this session.")
            self._schedule_retry(generation)
            return False
        # PySide's QCapturableWindow wrapper must outlive the asynchronous capture.
        # Retaining it also preserves the exact same-session window selection.
        self._window = window
        self.capture.setWindow(window)
        self._last_frame_at = 0.0
        self._last_error = ""
        self.capture.start()
        if self._last_error:
            self._window = None
            self._schedule_retry(generation)
            return False
        self.status_changed.emit(f"Streaming {window.description()} for {self.provider_key}.")
        QTimer.singleShot(500, lambda: self._verify_capture_started(generation))
        return True

    def stop(self) -> None:
        self._start_generation += 1
        self._desired_active = False
        if self.capture.isActive():
            self.capture.stop()
        self._last_frame_at = 0.0
        self._window = None

    def _verify_capture_started(self, generation: int) -> None:
        if generation != self._start_generation or not self.provider_key:
            return
        if not self.capture.isActive() and self._last_frame_at <= 0.0:
            self.status_changed.emit(
                f"The {self.provider_key} window was found, but its viewport capture did not start."
            )
            self._schedule_retry(generation)

    def _schedule_retry(self, generation: int) -> None:
        QTimer.singleShot(1000, lambda: self._retry_start(generation))

    def _retry_start(self, generation: int) -> None:
        if generation != self._start_generation or not self._desired_active or self.capture.isActive():
            return
        provider = self.provider_key
        scene = self.scene
        process_id = self.process_id
        crop = None if self._auto_crop_pending else QRectF(self.crop_rect)
        self.start(provider, scene=scene, crop_rect=crop, process_id=process_id)

    def _on_capture_error(self, *_args) -> None:
        message = self.capture.errorString() or "DCC window capture failed."
        self._last_error = message
        self.status_changed.emit(message)

    def _on_video_frame(self, frame: QVideoFrame) -> None:
        now = time.monotonic()
        if now - self._last_frame_at < self.min_frame_interval:
            return
        self._last_frame_at = now
        image = frame.toImage()
        if image.isNull():
            return
        if self._auto_crop_pending:
            detected = estimate_viewport_crop(image, self.provider_key)
            if detected is not None:
                self.crop_rect = detected
                self.status_changed.emit(f"Detected the {self.provider_key} viewport within the captured window.")
            self._auto_crop_pending = False
        crop = self.crop_rect
        if crop != QRectF(0.0, 0.0, 1.0, 1.0):
            x = max(0, min(image.width() - 1, int(crop.x() * image.width())))
            y = max(0, min(image.height() - 1, int(crop.y() * image.height())))
            width = max(1, min(image.width() - x, int(crop.width() * image.width())))
            height = max(1, min(image.height() - y, int(crop.height() * image.height())))
            image = image.copy(x, y, width, height)
        self.frame_ready.emit(image, self.provider_key)
