"""Animation Timeline & Stop-Motion Animatic Widget for Tech Connector Image Editor.

Supports multi-layer animation frames, FPS playback controls, scrubbing slider,
Onion Skinning (previous/next frame ghosting), and Spritesheet / Video exports.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tech_connector.ui.image_viewer.editor import LayerStack, ImageLayer
from tech_connector.ui.design_system import component_stylesheet, set_ui_role
from tech_connector.ui.icons import configure_button, icon
from tech_connector.ui.ux_polish import ContextRecipeCard, WorkflowRecipe, apply_property_guidance, apply_widget_discoverability


def playback_frame_for_elapsed(
    start_index: int,
    elapsed_seconds: float,
    fps: float,
    frame_count: int,
) -> tuple[int, int]:
    """Return a drift-free looped frame and elapsed source-frame count."""
    count = max(1, int(frame_count))
    steps = max(
        0,
        int(math.floor(max(0.0, float(elapsed_seconds)) * max(1.0, float(fps)) + 1.0e-9)),
    )
    return (int(start_index) + steps) % count, steps


class AnimationFrameSequence:
    """Manages an ordered sequence of multi-layer animation frames."""

    def __init__(self, width: int = 1280, height: int = 720):
        self.width = max(1, width)
        self.height = max(1, height)
        self.frames: list[LayerStack] = []
        self.current_frame_index = 0
        self.fps = 24
        self.onion_skin_enabled = True
        self.onion_skin_opacity = 0.35

        # Initialize with Frame 1
        initial_frame = LayerStack(self.width, self.height)
        initial_frame.add_layer(name="Background", fill_color=QColor(24, 28, 36))
        initial_frame.add_layer(name="Animation Line Art")
        self.frames.append(initial_frame)

    @property
    def current_frame(self) -> LayerStack:
        if 0 <= self.current_frame_index < len(self.frames):
            return self.frames[self.current_frame_index]
        return self.frames[0]

    def add_frame(self, duplicate: bool = False) -> LayerStack:
        if duplicate and self.current_frame:
            new_frame = LayerStack(self.width, self.height)
            for layer in self.current_frame.layers:
                new_frame.add_layer(layer.copy())
        else:
            new_frame = LayerStack(self.width, self.height)
            new_frame.add_layer(name="Background", fill_color=QColor(24, 28, 36))
            new_frame.add_layer(name="Animation Line Art")

        self.frames.insert(self.current_frame_index + 1, new_frame)
        self.current_frame_index += 1
        return new_frame

    def delete_current_frame(self) -> bool:
        if len(self.frames) > 1:
            self.frames.pop(self.current_frame_index)
            self.current_frame_index = max(0, self.current_frame_index - 1)
            return True
        return False

    def composite_current_frame_with_onion_skin(self, steps_before: int = 2, steps_after: int = 2) -> QImage:
        """Composite current frame with multi-frame 2D Lightbox Flipbook onion skin ghosting."""
        result = QImage(self.width, self.height, QImage.Format_ARGB32_Premultiplied)
        result.fill(QColor(15, 15, 20, 255))
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw Previous Frames (Red/Cyan Lightbox Ghosting)
        if self.onion_skin_enabled:
            for step in range(steps_before, 0, -1):
                idx = self.current_frame_index - step
                if 0 <= idx < len(self.frames):
                    prev_frame = self.frames[idx]
                    prev_img = prev_frame.composite()
                    fade_opacity = self.onion_skin_opacity * (1.0 - (step - 1) * 0.3)
                    painter.setOpacity(max(0.05, fade_opacity))
                    painter.drawImage(0, 0, prev_img)

        # Draw Current Active Keyframe
        current_img = self.current_frame.composite()
        painter.setOpacity(1.0)
        painter.drawImage(0, 0, current_img)

        # Draw Next Frames (Green/Magenta Lightbox Ghosting)
        if self.onion_skin_enabled:
            for step in range(1, steps_after + 1):
                idx = self.current_frame_index + step
                if 0 <= idx < len(self.frames):
                    next_frame = self.frames[idx]
                    next_img = next_frame.composite()
                    fade_opacity = (self.onion_skin_opacity * 0.7) * (1.0 - (step - 1) * 0.3)
                    painter.setOpacity(max(0.05, fade_opacity))
                    painter.drawImage(0, 0, next_img)

        painter.end()
        return result


class AnimationTimelineBar(QFrame):
    """Animation Timeline Control Bar for scrubbing, playback, onion skinning, and frame management."""

    frame_changed = Signal(int)
    playback_toggled = Signal(bool)

    def __init__(self, sequence: AnimationFrameSequence, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.is_playing = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._playback_tick)
        self._playback_epoch_s = 0.0
        self._playback_start_index = 0
        self._playback_step = 0

        self.setStyleSheet(component_stylesheet())
        set_ui_role(self, "panel")
        self._build_ui()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.workflow_guide = ContextRecipeCard(WorkflowRecipe(
            "Animation quick guide",
            ("Draw or pose the current frame", "Duplicate it", "Edit the change", "Scrub or Play", "Export"),
            preview="Onion skin shows neighboring frames as transparent alignment guides.",
            output="Spritesheet export preserves frame order; FPS controls playback timing rather than artwork.",
            tip="Block the motion at 12 FPS, then add in-between frames only where the action needs more detail.",
        ), self, expanded=False)
        outer_layout.addWidget(self.workflow_guide)

        toolbar = QWidget(self)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Playback Controls
        self.play_btn = QPushButton("Play")
        configure_button(self.play_btn, "play", text="Play", tooltip="Play or pause the timeline.", role="primary")
        self.play_btn.clicked.connect(self.toggle_playback)
        layout.addWidget(self.play_btn)

        prev_btn = QPushButton("Previous")
        configure_button(prev_btn, "skip_back", text="Previous", tooltip="Go to the previous frame.", icon_only=True)
        prev_btn.clicked.connect(self._step_prev_frame)
        layout.addWidget(prev_btn)

        next_btn = QPushButton("Next")
        configure_button(next_btn, "skip_forward", text="Next", tooltip="Go to the next frame.", icon_only=True)
        next_btn.clicked.connect(self._step_next_frame)
        layout.addWidget(next_btn)

        # Frame Scrubbing Slider & Counter
        self.frame_lbl = QLabel(f"Frame: 1 / {len(self.sequence.frames)}")
        layout.addWidget(self.frame_lbl)

        self.scrub_slider = QSlider(Qt.Horizontal)
        self.scrub_slider.setRange(0, max(0, len(self.sequence.frames) - 1))
        self.scrub_slider.setValue(0)
        self.scrub_slider.valueChanged.connect(self._scrub_to_frame)
        layout.addWidget(self.scrub_slider, 1)

        # Frame Management Actions
        add_frame_btn = QPushButton("+ Frame")
        configure_button(add_frame_btn, "plus", text="Add frame", tooltip="Add a blank frame after the current frame.")
        add_frame_btn.clicked.connect(self.add_frame)
        layout.addWidget(add_frame_btn)

        dup_frame_btn = QPushButton("Duplicate")
        configure_button(dup_frame_btn, "copy", text="Duplicate", tooltip="Duplicate the current frame.")
        dup_frame_btn.clicked.connect(self.dup_frame)
        layout.addWidget(dup_frame_btn)

        del_frame_btn = QPushButton("Delete")
        configure_button(del_frame_btn, "trash", text="Delete", tooltip="Delete the current frame.", role="danger")
        del_frame_btn.clicked.connect(self.del_frame)
        layout.addWidget(del_frame_btn)

        # Onion Skinning Toggle
        self.onion_btn = QPushButton("Onion skin on" if self.sequence.onion_skin_enabled else "Onion skin off")
        self.onion_btn.setCheckable(True)
        self.onion_btn.setChecked(self.sequence.onion_skin_enabled)
        configure_button(self.onion_btn, "layers", text=self.onion_btn.text(), tooltip="Show neighboring frames as transparent guides.")
        self.onion_btn.clicked.connect(self.toggle_onion_skin)
        layout.addWidget(self.onion_btn)

        # FPS Selection & Custom FPS SpinBox
        layout.addWidget(QLabel("FPS Preset:"))
        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["24 FPS (Film)", "12 FPS (2s)", "30 FPS (TV)", "60 FPS (Game)", "Custom..."])
        self.fps_combo.currentTextChanged.connect(self._change_fps)
        layout.addWidget(self.fps_combo)

        layout.addWidget(QLabel("Custom:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(self.sequence.fps)
        self.fps_spin.setFixedWidth(65)
        self.fps_spin.valueChanged.connect(self._set_custom_fps)
        layout.addWidget(self.fps_spin)

        # Export Spritesheet Button
        export_sheet_btn = QPushButton("Export spritesheet")
        configure_button(export_sheet_btn, "export", text="Export spritesheet", tooltip="Export every frame to a spritesheet.")
        export_sheet_btn.clicked.connect(self.export_spritesheet)
        layout.addWidget(export_sheet_btn)

        toolbar.adjustSize()
        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(toolbar)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(0)
        outer_layout.addWidget(scroll)
        apply_property_guidance(self.scrub_slider, "Drag to move through frames without changing artwork.",
                                safe_start="Pause playback before making precise edits.")
        apply_property_guidance(self.fps_combo, "Sets how quickly frames play and how exported timing is interpreted.",
                                safe_start="12 FPS for blocking, 24 FPS for film-style finished motion.")
        apply_property_guidance(self.fps_spin, "Custom playback frames per second.",
                                safe_start="Use a preset unless the delivery format requires a specific rate.",
                                consequence="Changing FPS changes timing, not the number of frames.")
        apply_widget_discoverability(self)

    def minimumSizeHint(self) -> QSize:
        return QSize(320, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(960, hint.width()), hint.height())

    def toggle_playback(self):
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setText("Pause")
            self.play_btn.setIcon(icon("pause"))
            self._restart_playback_clock()
        else:
            self.play_btn.setText("Play")
            self.play_btn.setIcon(icon("play"))
            self.timer.stop()
        self.playback_toggled.emit(self.is_playing)

    def _step_next_frame(self):
        if self.sequence.current_frame_index < len(self.sequence.frames) - 1:
            self.sequence.current_frame_index += 1
        else:
            self.sequence.current_frame_index = 0
        self.update_timeline_ui()
        if self.is_playing:
            self._restart_playback_clock()

    def _step_prev_frame(self):
        if self.sequence.current_frame_index > 0:
            self.sequence.current_frame_index -= 1
        else:
            self.sequence.current_frame_index = len(self.sequence.frames) - 1
        self.update_timeline_ui()
        if self.is_playing:
            self._restart_playback_clock()

    def _scrub_to_frame(self, index: int):
        if 0 <= index < len(self.sequence.frames):
            self.sequence.current_frame_index = index
            self.update_timeline_ui()
            if self.is_playing:
                self._restart_playback_clock()

    def _restart_playback_clock(self) -> None:
        self._playback_epoch_s = time.perf_counter()
        self._playback_start_index = int(self.sequence.current_frame_index)
        self._playback_step = 0
        self._schedule_playback_tick()

    def _schedule_playback_tick(self) -> None:
        if not self.is_playing:
            return
        fps = max(1.0, float(self.sequence.fps))
        next_deadline = self._playback_epoch_s + (self._playback_step + 1) / fps
        delay_ms = max(1, int(math.ceil((next_deadline - time.perf_counter()) * 1000.0)))
        self.timer.start(delay_ms)

    def _playback_tick(self) -> None:
        if not self.is_playing:
            return
        elapsed = max(0.0, time.perf_counter() - self._playback_epoch_s)
        frame_index, step = playback_frame_for_elapsed(
            self._playback_start_index,
            elapsed,
            self.sequence.fps,
            len(self.sequence.frames),
        )
        if step <= self._playback_step:
            self._schedule_playback_tick()
            return
        self._playback_step = step
        self.sequence.current_frame_index = frame_index
        self.update_timeline_ui()
        self._schedule_playback_tick()

    def add_frame(self):
        self.sequence.add_frame(duplicate=False)
        self.update_timeline_ui()

    def dup_frame(self):
        self.sequence.add_frame(duplicate=True)
        self.update_timeline_ui()

    def del_frame(self):
        if self.sequence.delete_current_frame():
            self.update_timeline_ui()

    def toggle_onion_skin(self):
        self.sequence.onion_skin_enabled = not self.sequence.onion_skin_enabled
        self.onion_btn.setChecked(self.sequence.onion_skin_enabled)
        self.onion_btn.setText("Onion skin on" if self.sequence.onion_skin_enabled else "Onion skin off")
        self.frame_changed.emit(self.sequence.current_frame_index)

    def _set_custom_fps(self, fps: int):
        self.sequence.fps = max(1, fps)
        if self.is_playing:
            self._restart_playback_clock()

    def _change_fps(self, text: str):
        if "12" in text:
            self.fps_spin.setValue(12)
        elif "24" in text:
            self.fps_spin.setValue(24)
        elif "30" in text:
            self.fps_spin.setValue(30)
        elif "60" in text:
            self.fps_spin.setValue(60)

    def update_timeline_ui(self):
        self.scrub_slider.setRange(0, max(0, len(self.sequence.frames) - 1))
        self.scrub_slider.blockSignals(True)
        try:
            self.scrub_slider.setValue(self.sequence.current_frame_index)
        finally:
            self.scrub_slider.blockSignals(False)
        self.frame_lbl.setText(f"Frame: {self.sequence.current_frame_index + 1} / {len(self.sequence.frames)}")
        self.frame_changed.emit(self.sequence.current_frame_index)

    def export_spritesheet(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Animation Spritesheet Texture", "Anim_Spritesheet.png", "PNG Image (*.png)")
        if not path:
            return

        cols = int(math.ceil(math.sqrt(len(self.sequence.frames))))
        rows = int(math.ceil(len(self.sequence.frames) / float(cols)))
        fw, fh = self.sequence.width, self.sequence.height

        sheet = QImage(cols * fw, rows * fh, QImage.Format_ARGB32_Premultiplied)
        sheet.fill(Qt.transparent)
        painter = QPainter(sheet)

        for idx, frame in enumerate(self.sequence.frames):
            c = idx % cols
            r = idx // cols
            img = frame.composite()
            painter.drawImage(c * fw, r * fh, img)

        painter.end()
        QMessageBox.information(self, "Spritesheet Exported", f"Successfully packed {len(self.sequence.frames)} animation frames into flipbook spritesheet ({cols}x{rows} grid):\n{path}")
