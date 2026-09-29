"""Native multi-track cinematic Sequence Editor for Level Sequence assets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets.sequence_asset_service import (
    RENDER_FORMATS, TRACK_DEFINITIONS, TRACK_TYPES, build_render_jobs, new_binding,
    new_level_blend_section, new_section, new_track, sequence_defaults, track_preset, validate_sequence,
)


TRACK_COLORS = {
    "camera_cut": "#63b3ff", "transform": "#73d3a3", "animation": "#b48cff",
    "audio": "#ff75ae", "event": "#ffd166", "visibility": "#74d7e8",
    "property": "#8eb5d0", "material": "#efb366", "effect": "#54dfd6",
    "spawn": "#80df91", "sub_sequence": "#d98eff", "time_dilation": "#ef8d6d",
}


class SequenceTimelineCanvas(QWidget):
    frameChanged = Signal(int)
    sectionSelected = Signal(str, str)
    sectionEdited = Signal(str, str, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tracks: list[dict[str, Any]] = []
        self.start_frame = 0
        self.end_frame = 300
        self.current_frame = 0
        self.pixels_per_frame = 4.0
        self.snap_interval = 1
        self.selected_section_id = ""
        self._drag: dict[str, Any] | None = None
        self.setMinimumSize(540, 260)
        self.setMouseTracking(True)

    def load(self, tracks: list[dict[str, Any]], start: int, end: int, frame: int) -> None:
        self.tracks = deepcopy(tracks)
        self.start_frame, self.end_frame = int(start), max(int(start) + 1, int(end))
        self.current_frame = min(self.end_frame, max(self.start_frame, int(frame)))
        self.setMinimumWidth(max(540, int((self.end_frame - self.start_frame) * self.pixels_per_frame + 48)))
        self.setMinimumHeight(max(260, 34 + len(self.tracks) * 36))
        self.update()

    def set_zoom(self, value: int) -> None:
        self.pixels_per_frame = max(0.5, float(value) / 10.0)
        self.load(self.tracks, self.start_frame, self.end_frame, self.current_frame)

    def _frame_x(self, frame: float) -> float:
        return 34.0 + (float(frame) - self.start_frame) * self.pixels_per_frame

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#071018"))
        painter.setRenderHint(QPainter.Antialiasing, False)
        major = max(1, round(80.0 / self.pixels_per_frame))
        for frame in range(self.start_frame, self.end_frame + 1, major):
            x = self._frame_x(frame)
            painter.setPen(QPen(QColor("#284051"), 1))
            painter.drawLine(int(x), 20, int(x), self.height())
            painter.setPen(QColor("#93aabc"))
            painter.drawText(int(x + 3), 15, str(frame))
        for index, track in enumerate(self.tracks):
            top = 28 + index * 36
            painter.fillRect(0, top, self.width(), 35, QColor("#0b1720" if index % 2 else "#0d1b25"))
            for section in track.get("sections") or ():
                left = self._frame_x(float(section.get("start_frame") or 0))
                right = self._frame_x(float(section.get("end_frame") or 0))
                rect = QRectF(left, top + 5, max(3.0, right - left), 25)
                color = QColor(TRACK_COLORS.get(str(track.get("type")), "#7da2b8"))
                if track.get("muted"):
                    color.setAlpha(80)
                painter.fillRect(rect, color)
                if str(section.get("id") or "") == self.selected_section_id:
                    painter.setPen(QPen(QColor("#ffffff"), 2))
                    painter.drawRect(rect.adjusted(1, 1, -1, -1))
                painter.setPen(QColor("#051018"))
                painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter, str(section.get("name") or "Section"))
        play_x = self._frame_x(self.current_frame)
        painter.setPen(QPen(QColor("#ff5a6f"), 2))
        painter.drawLine(int(play_x), 0, int(play_x), self.height())
        painter.setBrush(QColor("#ff5a6f"))
        painter.drawPolygon(QPolygon([QPoint(int(play_x - 5), 0), QPoint(int(play_x + 5), 0), QPoint(int(play_x), 8)]))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        frame = round((event.position().x() - 34.0) / self.pixels_per_frame) + self.start_frame
        frame = round(frame / max(1, self.snap_interval)) * max(1, self.snap_interval)
        self.current_frame = min(self.end_frame, max(self.start_frame, int(frame)))
        row = int((event.position().y() - 28) // 36)
        if 0 <= row < len(self.tracks):
            for section in self.tracks[row].get("sections") or ():
                start, end = int(section.get("start_frame") or 0), int(section.get("end_frame") or 0)
                if start <= self.current_frame < end:
                    track_id, section_id = str(self.tracks[row].get("id") or ""), str(section.get("id") or "")
                    self.selected_section_id = section_id
                    edge = 7.0
                    x = event.position().x()
                    mode = "trim_start" if abs(x - self._frame_x(start)) <= edge else "trim_end" if abs(x - self._frame_x(end)) <= edge else "move"
                    self._drag = {"track_id": track_id, "section_id": section_id, "mode": mode,
                                  "anchor_frame": self.current_frame, "start": start, "end": end}
                    self.sectionSelected.emit(track_id, section_id)
                    break
        self.frameChanged.emit(self.current_frame)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        frame = round((event.position().x() - 34.0) / self.pixels_per_frame) + self.start_frame
        frame = round(frame / max(1, self.snap_interval)) * max(1, self.snap_interval)
        delta = int(frame) - int(self._drag["anchor_frame"])
        start, end = int(self._drag["start"]), int(self._drag["end"])
        if self._drag["mode"] == "move":
            duration = end - start; start = max(self.start_frame, start + delta); end = start + duration
        elif self._drag["mode"] == "trim_start": start = min(end - 1, max(self.start_frame, start + delta))
        else: end = max(start + 1, min(self.end_frame, end + delta))
        for track in self.tracks:
            if track.get("id") != self._drag["track_id"]: continue
            for section in track.get("sections") or ():
                if section.get("id") == self._drag["section_id"]:
                    section["start_frame"], section["end_frame"] = start, end
                    break
        self.sectionEdited.emit(str(self._drag["track_id"]), str(self._drag["section_id"]), start, end)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        super().mouseReleaseEvent(event)


class SequenceEditorWidget(QWidget):
    """Serializable editor with bindings, hierarchical tracks, sections, and transport."""

    changed = Signal()

    def __init__(self, database=None, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self._values = sequence_defaults()
        self._loading = False
        self._build_ui()
        self.load_settings(self._values)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        transport = QHBoxLayout()
        self.play = QPushButton("Play", self)
        self.stop = QPushButton("Stop", self)
        self.previous = QPushButton("◀", self)
        self.next = QPushButton("▶", self)
        self.frame = QSpinBox(self); self.frame.setRange(-1_000_000, 1_000_000); self.frame.setPrefix("Frame ")
        self.fps = QSpinBox(self); self.fps.setRange(1, 240); self.fps.setSuffix(" fps")
        self.playback_mode = QComboBox(self); self.playback_mode.addItems(["loop", "once", "ping_pong"])
        self.snap = QSpinBox(self); self.snap.setRange(1, 1000); self.snap.setValue(1); self.snap.setPrefix("Snap ")
        self.zoom = QSlider(Qt.Horizontal, self); self.zoom.setRange(5, 160); self.zoom.setValue(40); self.zoom.setFixedWidth(110)
        for widget in (self.play, self.stop, self.previous, self.next, self.frame): transport.addWidget(widget)
        transport.addStretch(1)
        transport.addWidget(self.fps); transport.addWidget(self.playback_mode); transport.addWidget(self.snap)
        transport.addWidget(QLabel("Zoom")); transport.addWidget(self.zoom)
        root.addLayout(transport)

        authoring = QHBoxLayout()
        self.search = QLineEdit(self); self.search.setPlaceholderText("Filter tracks and bindings…")
        self.add_binding_button = QPushButton("+ Binding", self)
        self.track_type = QComboBox(self)
        for value, definition in TRACK_DEFINITIONS.items(): self.track_type.addItem(f"{definition['category']} • {definition['label']}", value)
        self.add_track_button = QPushButton("+ Track", self)
        self.add_section_button = QPushButton("+ Section", self)
        self.duplicate_button = QPushButton("Duplicate", self)
        self.delete_button = QPushButton("Delete", self)
        for widget in (self.search, self.add_binding_button, self.track_type, self.add_track_button, self.add_section_button, self.duplicate_button, self.delete_button): authoring.addWidget(widget)
        root.addLayout(authoring)

        splitter = QSplitter(Qt.Horizontal, self)
        self.outliner = QTreeWidget(self)
        self.outliner.setHeaderLabels(["Track / Binding", "Type", "M", "S", "L"])
        self.outliner.setSelectionMode(QAbstractItemView.SingleSelection)
        self.outliner.setAlternatingRowColors(True)
        self.outliner.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (2, 3, 4): self.outliner.header().resizeSection(column, 28)
        self.canvas = SequenceTimelineCanvas(self)
        splitter.addWidget(self.outliner); splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 760])
        root.addWidget(splitter, 1)

        section_form = QHBoxLayout()
        self.section_name = QLineEdit(self); self.section_name.setPlaceholderText("Select a section")
        self.section_start = QSpinBox(self); self.section_start.setRange(-1_000_000, 1_000_000); self.section_start.setPrefix("In ")
        self.section_end = QSpinBox(self); self.section_end.setRange(-999_999, 1_000_000); self.section_end.setPrefix("Out ")
        self.section_scale = QDoubleSpinBox(self); self.section_scale.setRange(0.001, 1000.0); self.section_scale.setDecimals(3); self.section_scale.setPrefix("Speed "); self.section_scale.setValue(1.0)
        self.section_asset = QComboBox(self); self.section_asset.setEditable(True); self.section_asset.lineEdit().setPlaceholderText("Referenced asset / camera binding")
        for widget in (QLabel("Selected Section"), self.section_name, self.section_start, self.section_end, self.section_scale, self.section_asset): section_form.addWidget(widget)
        root.addLayout(section_form)
        blend_form = QHBoxLayout()
        self.section_blend = QComboBox(self); self.section_blend.addItems(["absolute", "additive", "crossfade", "replace", "portal", "match_cut"])
        self.section_ease_in = QSpinBox(self); self.section_ease_in.setRange(0, 100_000); self.section_ease_in.setPrefix("Ease In ")
        self.section_ease_out = QSpinBox(self); self.section_ease_out.setRange(0, 100_000); self.section_ease_out.setPrefix("Ease Out ")
        self.section_pre_roll = QSpinBox(self); self.section_pre_roll.setRange(0, 100_000); self.section_pre_roll.setPrefix("Preload ")
        self.blend_lighting = QCheckBox("Lighting", self); self.blend_audio = QCheckBox("Audio", self); self.blend_post = QCheckBox("Post FX", self); self.blend_gameplay = QCheckBox("Gameplay", self); self.preserve_player = QCheckBox("Preserve Player", self)
        blend_form.addWidget(QLabel("Blend"));
        for widget in (self.section_blend, self.section_ease_in, self.section_ease_out, self.section_pre_roll, self.blend_lighting, self.blend_audio, self.blend_post, self.blend_gameplay, self.preserve_player): blend_form.addWidget(widget)
        blend_form.addStretch(1); root.addLayout(blend_form)

        range_row = QHBoxLayout()
        self.start = QSpinBox(self); self.start.setRange(-1_000_000, 1_000_000); self.start.setPrefix("Start ")
        self.end = QSpinBox(self); self.end.setRange(-999_999, 1_000_000); self.end.setPrefix("End ")
        self.duration_label = QLabel(self)
        self.status = QLabel("Ready", self)
        range_row.addWidget(self.start); range_row.addWidget(self.end); range_row.addWidget(self.duration_label)
        range_row.addStretch(1); range_row.addWidget(self.status)
        root.addLayout(range_row)

        self._timer = QTimer(self); self._timer.timeout.connect(self._advance)
        self.play.clicked.connect(self._toggle_play); self.stop.clicked.connect(self._stop)
        self.previous.clicked.connect(lambda: self.frame.setValue(self.frame.value() - self.snap.value()))
        self.next.clicked.connect(lambda: self.frame.setValue(self.frame.value() + self.snap.value()))
        self.frame.valueChanged.connect(self._frame_changed)
        self.fps.valueChanged.connect(self._timing_changed); self.playback_mode.currentTextChanged.connect(self._timing_changed)
        self.start.valueChanged.connect(self._range_changed); self.end.valueChanged.connect(self._range_changed)
        self.snap.valueChanged.connect(lambda value: setattr(self.canvas, "snap_interval", value))
        self.zoom.valueChanged.connect(self.canvas.set_zoom); self.canvas.frameChanged.connect(self.frame.setValue)
        self.canvas.sectionSelected.connect(self._select_section)
        self.canvas.sectionEdited.connect(self._section_edited)
        self.search.textChanged.connect(self._filter)
        self.add_binding_button.clicked.connect(self.add_binding); self.add_track_button.clicked.connect(self.add_track)
        self.add_section_button.clicked.connect(self.add_section); self.duplicate_button.clicked.connect(self.duplicate_selected)
        self.delete_button.clicked.connect(self.delete_selected); self.outliner.itemChanged.connect(self._outliner_changed)
        self.outliner.itemClicked.connect(self._outliner_clicked)
        self.section_name.editingFinished.connect(self._section_details_changed)
        self.section_start.valueChanged.connect(self._section_details_changed); self.section_end.valueChanged.connect(self._section_details_changed)
        self.section_scale.valueChanged.connect(self._section_details_changed); self.section_asset.currentTextChanged.connect(self._section_details_changed)
        self.section_blend.currentTextChanged.connect(self._section_details_changed); self.section_ease_in.valueChanged.connect(self._section_details_changed); self.section_ease_out.valueChanged.connect(self._section_details_changed); self.section_pre_roll.valueChanged.connect(self._section_details_changed)
        for checkbox in (self.blend_lighting, self.blend_audio, self.blend_post, self.blend_gameplay, self.preserve_player): checkbox.toggled.connect(self._section_details_changed)
        self._selected_section: tuple[str, str] = ("", "")

    def load_settings(self, values: dict[str, Any] | None) -> None:
        defaults = sequence_defaults(); defaults.update(deepcopy(dict(values or {}))); self._values = defaults
        self._loading = True
        rate = dict(defaults.get("display_rate") or {})
        playback = dict(defaults.get("playback_range") or {})
        self.fps.setValue(max(1, round(float(rate.get("numerator") or 30) / max(1, int(rate.get("denominator") or 1)))))
        self.start.setValue(int(playback.get("start") or 0)); self.end.setValue(max(self.start.value() + 1, int(playback.get("end") or 300)))
        self.frame.setRange(self.start.value(), self.end.value()); self.frame.setValue(self.start.value())
        index = self.playback_mode.findText(str(defaults.get("playback_mode") or "loop")); self.playback_mode.setCurrentIndex(max(0, index))
        self._rebuild(); self._loading = False

    def settings(self) -> dict[str, Any]:
        values = deepcopy(self._values)
        values["display_rate"] = {"numerator": self.fps.value(), "denominator": 1}
        values["playback_range"] = {"start": self.start.value(), "end": self.end.value()}
        values["view_range"] = dict(values["playback_range"])
        values["playback_mode"] = self.playback_mode.currentText()
        return values

    def validation_issues(self) -> list[str]:
        return [issue.message for issue in validate_sequence(self.settings()) if issue.severity == "error"]

    def add_binding(self, name: str = "Actor Binding", object_id: str = "") -> str:
        binding = new_binding(name, object_id=object_id); self._values.setdefault("bindings", []).append(binding)
        self._rebuild(); self._emit_changed(); return str(binding["id"])

    def add_track(self, track_type: str = "", name: str = "", binding_id: str = "") -> str:
        kind = str(track_type or self.track_type.currentData() or "animation").casefold().replace(" ", "_")
        selected = self.outliner.currentItem()
        if not binding_id and selected is not None and selected.data(0, Qt.UserRole) == "binding": binding_id = str(selected.data(0, Qt.UserRole + 1) or "")
        track = track_preset(kind, name, binding_id=binding_id); self._values.setdefault("tracks", []).append(track)
        self._rebuild(); self._select_track(str(track["id"])); self._emit_changed(); return str(track["id"])

    def add_section(self, name: str = "", start_frame: int | None = None, end_frame: int | None = None, asset_id: str = "") -> str:
        track = self._selected_track()
        if track is None:
            if not self._values.get("tracks"): self.add_track("animation", "Animation")
            track = self._selected_track() or self._values["tracks"][-1]
        start = self.frame.value() if start_frame is None else int(start_frame)
        end = min(self.end.value(), start + max(1, self.fps.value())) if end_frame is None else int(end_frame)
        section = (new_level_blend_section(name or "Level Blend", asset_id, start, max(start + 1, end))
                   if track.get("type") == "level_blend" else
                   new_section(name or f"{track['name']} Section", start, max(start + 1, end), asset_id=asset_id))
        section["channels"] = deepcopy(list(track.get("default_channels") or ()))
        track.setdefault("sections", []).append(section); self._rebuild(); self._select_section(str(track["id"]), str(section["id"])); self._emit_changed(); return str(section["id"])

    def duplicate_selected(self) -> None:
        track = self._selected_track()
        if track is None: return
        clone = deepcopy(track); clone["id"] = new_track(str(track["type"]))["id"]; clone["name"] = f"{track['name']} Copy"
        for section in clone.get("sections") or (): section["id"] = new_section("x", 0, 1)["id"]
        self._values["tracks"].append(clone); self._rebuild(); self._select_track(str(clone["id"])); self._emit_changed()

    def delete_selected(self) -> None:
        item = self.outliner.currentItem()
        if item is None: return
        kind, identifier = item.data(0, Qt.UserRole), str(item.data(0, Qt.UserRole + 1) or "")
        if kind == "track": self._values["tracks"] = [track for track in self._values.get("tracks") or () if track.get("id") != identifier]
        elif kind == "binding":
            self._values["bindings"] = [binding for binding in self._values.get("bindings") or () if binding.get("id") != identifier]
            for track in self._values.get("tracks") or ():
                if track.get("binding_id") == identifier: track["binding_id"] = ""
        self._rebuild(); self._emit_changed()

    def _rebuild(self) -> None:
        self.outliner.blockSignals(True); self.outliner.clear()
        binding_items: dict[str, QTreeWidgetItem] = {}
        for binding in self._values.get("bindings") or ():
            item = QTreeWidgetItem([str(binding.get("name") or "Binding"), str(binding.get("type") or "possessable"), "", "", ""])
            item.setData(0, Qt.UserRole, "binding"); item.setData(0, Qt.UserRole + 1, str(binding.get("id") or "")); item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.outliner.addTopLevelItem(item); binding_items[str(binding.get("id") or "")] = item
        for track in self._values.get("tracks") or ():
            item = QTreeWidgetItem([str(track.get("name") or "Track"), str(track.get("type") or ""), "M" if track.get("muted") else "", "S" if track.get("solo") else "", "L" if track.get("locked") else ""])
            item.setData(0, Qt.UserRole, "track"); item.setData(0, Qt.UserRole + 1, str(track.get("id") or "")); item.setFlags(item.flags() | Qt.ItemIsEditable)
            parent = binding_items.get(str(track.get("binding_id") or "")); (parent.addChild(item) if parent else self.outliner.addTopLevelItem(item))
        self.outliner.expandAll(); self.outliner.blockSignals(False)
        self.canvas.load(list(self._values.get("tracks") or ()), self.start.value(), self.end.value(), self.frame.value())
        self.duration_label.setText(f"{self.end.value() - self.start.value()} frames • {(self.end.value() - self.start.value()) / max(1, self.fps.value()):.2f} sec")

    def _selected_track(self) -> dict[str, Any] | None:
        item = self.outliner.currentItem()
        if item is None or item.data(0, Qt.UserRole) != "track": return None
        identifier = str(item.data(0, Qt.UserRole + 1) or "")
        return next((track for track in self._values.get("tracks") or () if str(track.get("id") or "") == identifier), None)

    def _select_track(self, identifier: str) -> None:
        iterator = self.outliner.invisibleRootItem()
        stack = [iterator.child(index) for index in range(iterator.childCount())]
        while stack:
            item = stack.pop(0)
            if item.data(0, Qt.UserRole) == "track" and item.data(0, Qt.UserRole + 1) == identifier: self.outliner.setCurrentItem(item); return
            stack.extend(item.child(index) for index in range(item.childCount()))

    def _select_section(self, track_id: str, section_id: str) -> None:
        self.canvas.selected_section_id = section_id
        self._selected_section = (track_id, section_id)
        self._select_track(track_id)
        section = self._section(track_id, section_id)
        if section is not None:
            self._loading = True
            self._populate_asset_picker(track_id, str(section.get("asset_id") or ""))
            transition = dict(section.get("level_transition") or {})
            self.section_name.setText(str(section.get("name") or "Section")); self.section_start.setValue(int(section.get("start_frame") or 0)); self.section_end.setValue(int(section.get("end_frame") or 1)); self.section_scale.setValue(float(section.get("time_scale") or 1.0)); self.section_blend.setCurrentText(str(section.get("blend_type") or "absolute")); self.section_ease_in.setValue(int(section.get("ease_in") or 0)); self.section_ease_out.setValue(int(section.get("ease_out") or 0)); self.section_pre_roll.setValue(int(section.get("pre_roll") or 0)); self.blend_lighting.setChecked(bool(transition.get("blend_lighting", True))); self.blend_audio.setChecked(bool(transition.get("blend_audio", True))); self.blend_post.setChecked(bool(transition.get("blend_post_process", True))); self.blend_gameplay.setChecked(bool(transition.get("blend_gameplay", False))); self.preserve_player.setChecked(bool(transition.get("preserve_player_state", True)))
            self._loading = False

    def _section_edited(self, track_id: str, section_id: str, start: int, end: int) -> None:
        for track in self._values.get("tracks") or ():
            if track.get("id") != track_id: continue
            for section in track.get("sections") or ():
                if section.get("id") == section_id:
                    section["start_frame"], section["end_frame"] = int(start), int(end)
                    self.status.setText(f"{section.get('name', 'Section')}: {start}–{end}")
                    self._emit_changed()
                    return

    def _section(self, track_id: str, section_id: str) -> dict[str, Any] | None:
        for track in self._values.get("tracks") or ():
            if track.get("id") == track_id:
                return next((section for section in track.get("sections") or () if section.get("id") == section_id), None)
        return None

    def _section_details_changed(self, *_args) -> None:
        if self._loading: return
        section = self._section(*self._selected_section)
        if section is None: return
        end = max(self.section_start.value() + 1, self.section_end.value())
        if end != self.section_end.value():
            self._loading = True; self.section_end.setValue(end); self._loading = False
        transition = dict(section.get("level_transition") or {})
        transition.update({"blend_lighting": self.blend_lighting.isChecked(), "blend_audio": self.blend_audio.isChecked(), "blend_post_process": self.blend_post.isChecked(), "blend_gameplay": self.blend_gameplay.isChecked(), "preserve_player_state": self.preserve_player.isChecked()})
        section.update({"name": self.section_name.text().strip() or "Section", "start_frame": self.section_start.value(), "end_frame": end, "time_scale": self.section_scale.value(), "asset_id": self._selected_asset_id(), "blend_type": self.section_blend.currentText(), "ease_in": self.section_ease_in.value(), "ease_out": self.section_ease_out.value(), "pre_roll": self.section_pre_roll.value(), "level_transition": transition})
        self._rebuild(); self.canvas.selected_section_id = self._selected_section[1]; self._emit_changed()

    def _populate_asset_picker(self, track_id: str, current_asset_id: str) -> None:
        self.section_asset.blockSignals(True); self.section_asset.clear(); self.section_asset.addItem("None", "")
        track = next((item for item in self._values.get("tracks") or () if item.get("id") == track_id), {})
        allowed = set(TRACK_DEFINITIONS.get(str(track.get("type") or ""), {}).get("asset_types") or ())
        if self.database is not None:
            for record in self.database.list_assets():
                if not allowed or record.asset_type in allowed:
                    self.section_asset.addItem(f"{record.source_path.stem}  [{record.asset_type}]", record.asset_id)
        match = self.section_asset.findData(current_asset_id)
        if match >= 0: self.section_asset.setCurrentIndex(match)
        elif current_asset_id: self.section_asset.setEditText(current_asset_id)
        self.section_asset.blockSignals(False)

    def _selected_asset_id(self) -> str:
        data = self.section_asset.currentData()
        if data:
            return str(data).strip()
        text = self.section_asset.currentText().strip()
        return "" if text == "None" else text

    def _outliner_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading: return
        identifier = str(item.data(0, Qt.UserRole + 1) or "")
        if item.data(0, Qt.UserRole) == "track":
            track = next((value for value in self._values.get("tracks") or () if value.get("id") == identifier), None)
            if track:
                if column == 0: track["name"] = item.text(0)
                elif column == 2: track["muted"] = not bool(track.get("muted"))
                elif column == 3: track["solo"] = not bool(track.get("solo"))
                elif column == 4: track["locked"] = not bool(track.get("locked"))
        self._rebuild(); self._emit_changed()

    def _outliner_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if item.data(0, Qt.UserRole) != "track" or column not in {2, 3, 4}: return
        self._outliner_changed(item, column)

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        root = self.outliner.invisibleRootItem()
        for index in range(root.childCount()):
            item = root.child(index); child_visible = False
            for child_index in range(item.childCount()):
                child = item.child(child_index); match = not query or query in (child.text(0) + " " + child.text(1)).casefold(); child.setHidden(not match); child_visible |= match
            own_match = not query or query in (item.text(0) + " " + item.text(1)).casefold(); item.setHidden(not (own_match or child_visible))

    def _toggle_play(self) -> None:
        if self._timer.isActive(): self._timer.stop(); self.play.setText("Play")
        else: self._timer.start(max(1, round(1000 / max(1, self.fps.value())))); self.play.setText("Pause")

    def _stop(self) -> None: self._timer.stop(); self.play.setText("Play"); self.frame.setValue(self.start.value())

    def _advance(self) -> None:
        value = self.frame.value() + 1
        if value >= self.end.value():
            if self.playback_mode.currentText() == "once": self._stop(); return
            value = self.start.value()
        self.frame.setValue(value)

    def _frame_changed(self, value: int) -> None: self.canvas.current_frame = value; self.canvas.update(); self.status.setText(f"Frame {value}")

    def _range_changed(self) -> None:
        if self.end.value() <= self.start.value(): self.end.setValue(self.start.value() + 1)
        self.frame.setRange(self.start.value(), self.end.value()); self._rebuild(); self._emit_changed()

    def _timing_changed(self) -> None:
        if self._timer.isActive(): self._timer.start(max(1, round(1000 / max(1, self.fps.value()))))
        self._rebuild(); self._emit_changed()

    def _emit_changed(self) -> None:
        if not self._loading: self.changed.emit()


class SequenceCurveEditorWidget(QWidget):
    """Key table for any numeric sequence channel with lossless ID-based patching."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.target = QComboBox(self)
        self.channel_name = QLineEdit("Value", self); self.channel_name.setPlaceholderText("Channel name")
        add = QPushButton("+ Key at Playhead", self); remove = QPushButton("Delete Key", self)
        toolbar.addWidget(QLabel("Target")); toolbar.addWidget(self.target, 1); toolbar.addWidget(self.channel_name)
        toolbar.addWidget(add); toolbar.addWidget(remove); root.addLayout(toolbar)
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(["Track", "Section", "Channel", "Frame", "Value", "Interpolation"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        self._targets: list[dict[str, str]] = []; self._loading = False; self.playhead_frame = 0
        add.clicked.connect(self.add_key); remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(lambda _item: None if self._loading else self.changed.emit())

    def load_settings(self, values: dict[str, Any] | None) -> None:
        self._loading = True; self._targets = []; self.target.clear(); self.table.setRowCount(0)
        for track in dict(values or {}).get("tracks") or ():
            for section in track.get("sections") or ():
                target = {"track_id": str(track.get("id") or ""), "track": str(track.get("name") or "Track"),
                          "section_id": str(section.get("id") or ""), "section": str(section.get("name") or "Section")}
                self._targets.append(target); self.target.addItem(f"{target['track']} / {target['section']}")
                for channel in section.get("channels") or ():
                    channel_id = str(channel.get("id") or channel.get("name") or "Value")
                    for key in channel.get("keys") or ():
                        self._append_key(target, channel_id, str(channel.get("name") or channel_id), key)
        self._loading = False

    def _append_key(self, target: dict[str, str], channel_id: str, channel_name: str, key: dict[str, Any]) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        values = (target["track"], target["section"], channel_name, str(key.get("frame", 0)), str(key.get("value", 0)), str(key.get("interpolation") or "linear"))
        for column, value in enumerate(values): self.table.setItem(row, column, QTableWidgetItem(value))
        first = self.table.item(row, 0); first.setData(Qt.UserRole, target["track_id"]); first.setData(Qt.UserRole + 1, target["section_id"]); first.setData(Qt.UserRole + 2, channel_id)

    def add_key(self, frame: int | None = None, value: float = 0.0, interpolation: str = "linear") -> None:
        index = self.target.currentIndex()
        if index < 0 or index >= len(self._targets): return
        target = self._targets[index]; channel_name = self.channel_name.text().strip() or "Value"
        self._loading = True
        self._append_key(target, channel_name, channel_name, {"frame": self.playhead_frame if frame is None else frame, "value": value, "interpolation": interpolation})
        self._loading = False; self.changed.emit()

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()

    def apply_to(self, values: dict[str, Any]) -> None:
        channels: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in range(self.table.rowCount()):
            first = self.table.item(row, 0); track_id = str(first.data(Qt.UserRole) or ""); section_id = str(first.data(Qt.UserRole + 1) or ""); channel_id = str(first.data(Qt.UserRole + 2) or self.table.item(row, 2).text())
            try: frame = float(self.table.item(row, 3).text()); value = float(self.table.item(row, 4).text())
            except (AttributeError, ValueError): continue
            entry = channels.setdefault((track_id, section_id, channel_id), {"id": channel_id, "name": self.table.item(row, 2).text(), "keys": []})
            entry["keys"].append({"frame": frame, "value": value, "interpolation": self.table.item(row, 5).text() or "linear"})
        touched = {(key[0], key[1]) for key in channels}
        for track in values.get("tracks") or ():
            for section in track.get("sections") or ():
                identity = (str(track.get("id") or ""), str(section.get("id") or ""))
                if identity in touched:
                    section["channels"] = [payload for (track_id, section_id, _channel), payload in channels.items() if (track_id, section_id) == identity]

    def validation_issues(self) -> list[str]:
        seen: set[tuple[str, str, str, float]] = set(); issues = []
        for row in range(self.table.rowCount()):
            first = self.table.item(row, 0)
            try: frame = float(self.table.item(row, 3).text()); float(self.table.item(row, 4).text())
            except (AttributeError, ValueError): issues.append(f"Curve key row {row + 1} has a non-numeric frame or value."); continue
            identity = (str(first.data(Qt.UserRole) or ""), str(first.data(Qt.UserRole + 1) or ""), str(first.data(Qt.UserRole + 2) or ""), frame)
            if identity in seen: issues.append(f"Curve channel has duplicate keys at frame {frame:g}.")
            seen.add(identity)
        return issues


class SequenceBindingsEditorWidget(QWidget):
    """Explicit possessable/spawnable binding editor."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self); controls = QHBoxLayout()
        add = QPushButton("+ Possessable", self); spawn = QPushButton("+ Spawnable", self); component = QPushButton("+ Component", self); bone = QPushButton("+ Bone / Socket", self); remove = QPushButton("Remove", self)
        controls.addWidget(add); controls.addWidget(spawn); controls.addWidget(component); controls.addWidget(bone); controls.addWidget(remove); controls.addStretch(1); root.addLayout(controls)
        self.table = QTableWidget(0, 9, self); self.table.setHorizontalHeaderLabels(["Name", "Binding Type", "Level Object / Asset ID", "Parent Binding", "Component Path", "Skeleton Asset", "Bone", "Socket", "Tags"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch); self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.table, 1); self._loading = False
        add.clicked.connect(lambda: self.add_binding("possessable")); spawn.clicked.connect(lambda: self.add_binding("spawnable")); component.clicked.connect(self.add_component_binding); bone.clicked.connect(self.add_bone_binding); remove.clicked.connect(self.delete_selected)
        self.table.itemChanged.connect(lambda _item: None if self._loading else self.changed.emit())

    def load_settings(self, values: dict[str, Any] | None) -> None:
        self._loading = True; self.table.setRowCount(0)
        for binding in dict(values or {}).get("bindings") or (): self._append(binding)
        self._loading = False

    def _append(self, binding: dict[str, Any]) -> None:
        row = self.table.rowCount(); self.table.insertRow(row)
        for column, value in enumerate((binding.get("name", "Binding"), binding.get("type", "possessable"), binding.get("object_id", ""), binding.get("parent_binding_id", ""), binding.get("component_path", ""), binding.get("skeleton_asset_id", ""), binding.get("bone_name", ""), binding.get("socket_name", ""), ", ".join(binding.get("tags") or ()))): self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.item(row, 0).setData(Qt.UserRole, str(binding.get("id") or new_binding("Binding")["id"]))

    def add_binding(self, binding_type: str = "possessable") -> str:
        binding = new_binding("New Binding", binding_type=binding_type); self._loading = True; self._append(binding); self._loading = False; self.changed.emit(); return str(binding["id"])

    def add_component_binding(self) -> str:
        binding = new_binding("Component", binding_type="component", component_path="SkeletalMeshComponent")
        self._loading = True; self._append(binding); self._loading = False; self.changed.emit(); return str(binding["id"])

    def add_bone_binding(self) -> str:
        binding = new_binding("Bone / Socket", binding_type="bone", bone_name="root")
        self._loading = True; self._append(binding); self._loading = False; self.changed.emit(); return str(binding["id"])

    def delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows: self.table.removeRow(row)
        if rows: self.changed.emit()

    def bindings(self) -> list[dict[str, Any]]:
        result = []
        for row in range(self.table.rowCount()):
            first = self.table.item(row, 0)
            result.append({"id": str(first.data(Qt.UserRole) or ""), "name": first.text(), "type": self.table.item(row, 1).text(), "object_id": self.table.item(row, 2).text(), "parent_binding_id": self.table.item(row, 3).text(), "component_path": self.table.item(row, 4).text(), "skeleton_asset_id": self.table.item(row, 5).text(), "bone_name": self.table.item(row, 6).text(), "socket_name": self.table.item(row, 7).text(), "tags": [value.strip() for value in self.table.item(row, 8).text().split(",") if value.strip()]})
        return result

    def validation_issues(self) -> list[str]:
        values = self.bindings(); identifiers = [value["id"] for value in values]
        return ["Bindings must have stable unique IDs."] if "" in identifiers or len(set(identifiers)) != len(identifiers) else []


class SequenceRenderExportWidget(QWidget):
    """Validated render settings and deterministic camera-cut job preview."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self); form = QFormLayout()
        self.width = QSpinBox(self); self.width.setRange(16, 32768)
        self.height = QSpinBox(self); self.height.setRange(16, 32768)
        size = QHBoxLayout(); size.addWidget(self.width); size.addWidget(QLabel("×")); size.addWidget(self.height)
        self.format = QComboBox(self); self.format.addItems(RENDER_FORMATS)
        self.output = QLineEdit(self); self.handles = QSpinBox(self); self.handles.setRange(0, 10_000)
        self.temporal = QSpinBox(self); self.temporal.setRange(1, 256); self.spatial = QSpinBox(self); self.spatial.setRange(1, 256)
        self.camera_cuts = QCheckBox("Create one job per camera cut", self); self.motion_blur = QCheckBox("Motion blur", self)
        self.audio = QCheckBox("Include audio", self); self.burn_in = QCheckBox("Review burn-in", self); self.overwrite = QCheckBox("Allow overwrite", self)
        form.addRow("Resolution", size); form.addRow("Output format", self.format); form.addRow("Output directory", self.output)
        form.addRow("Frame handles", self.handles); form.addRow("Temporal samples", self.temporal); form.addRow("Spatial samples", self.spatial)
        form.addRow("Shots", self.camera_cuts); form.addRow("", self.motion_blur); form.addRow("", self.audio); form.addRow("", self.burn_in); form.addRow("", self.overwrite)
        root.addLayout(form)
        buttons = QHBoxLayout(); refresh = QPushButton("Refresh Jobs", self); buttons.addWidget(refresh); buttons.addStretch(1); root.addLayout(buttons)
        self.jobs = QTableWidget(0, 5, self); self.jobs.setHorizontalHeaderLabels(["Job", "Start", "End", "Frames", "Camera"]); self.jobs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); root.addWidget(self.jobs, 1)
        self._sequence: dict[str, Any] = sequence_defaults(); self._loading = False
        for widget in (self.width, self.height, self.format, self.output, self.handles, self.temporal, self.spatial, self.camera_cuts, self.motion_blur, self.audio, self.burn_in, self.overwrite):
            signal = widget.currentTextChanged if isinstance(widget, QComboBox) else widget.textChanged if isinstance(widget, QLineEdit) else widget.toggled if isinstance(widget, QCheckBox) else widget.valueChanged
            signal.connect(self._changed)
        refresh.clicked.connect(self.refresh_jobs)

    def load_settings(self, values: dict[str, Any] | None) -> None:
        defaults = sequence_defaults(); defaults.update(deepcopy(dict(values or {}))); self._sequence = defaults
        settings = dict(defaults.get("render_settings") or {}); resolution = list(settings.get("resolution") or [1920, 1080])
        self._loading = True; self.width.setValue(int(resolution[0])); self.height.setValue(int(resolution[1])); self.format.setCurrentText(str(settings.get("format") or "png")); self.output.setText(str(settings.get("output_directory") or "Renders")); self.handles.setValue(int(settings.get("frame_handles") or 0)); self.temporal.setValue(int(settings.get("temporal_samples") or 1)); self.spatial.setValue(int(settings.get("spatial_samples") or 1)); self.camera_cuts.setChecked(bool(settings.get("use_camera_cuts", True))); self.motion_blur.setChecked(bool(settings.get("motion_blur", True))); self.audio.setChecked(bool(settings.get("include_audio", True))); self.burn_in.setChecked(bool(settings.get("burn_in", False))); self.overwrite.setChecked(bool(settings.get("overwrite_existing", False))); self._loading = False
        self.refresh_jobs()

    def render_settings(self) -> dict[str, Any]:
        return {"resolution": [self.width.value(), self.height.value()], "format": self.format.currentText(), "output_directory": self.output.text().strip() or "Renders", "use_camera_cuts": self.camera_cuts.isChecked(), "frame_handles": self.handles.value(), "temporal_samples": self.temporal.value(), "spatial_samples": self.spatial.value(), "motion_blur": self.motion_blur.isChecked(), "include_audio": self.audio.isChecked(), "burn_in": self.burn_in.isChecked(), "overwrite_existing": self.overwrite.isChecked()}

    def refresh_jobs(self) -> None:
        values = deepcopy(self._sequence); values["render_settings"] = self.render_settings(); jobs = build_render_jobs(values)
        self.jobs.setRowCount(0)
        for job in jobs:
            row = self.jobs.rowCount(); self.jobs.insertRow(row); start, end = int(job["start_frame"]), int(job["end_frame"])
            for column, value in enumerate((job["name"], start, end, max(0, end - start), job["camera_binding_id"])): self.jobs.setItem(row, column, QTableWidgetItem(str(value)))

    def _changed(self, *_args) -> None:
        if self._loading: return
        self.refresh_jobs(); self.changed.emit()

    def validation_issues(self) -> list[str]:
        values = deepcopy(self._sequence); values["render_settings"] = self.render_settings()
        return [issue.message for issue in validate_sequence(values) if issue.severity == "error" and issue.path.startswith("render_settings")]
