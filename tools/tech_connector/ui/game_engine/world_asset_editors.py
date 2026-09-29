"""Interactive world-production previews and authoring controls."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import WorldAssetService, WorldBuildService
from tech_connector.game_engine.assets.world_asset_service import (
    apply_foliage_brush, apply_terrain_brush, build_hlod_preview,
    build_lighting_preview, build_navigation_preview, build_partition_preview, build_terrain_preview,
)


class WorldAuthoringCanvas(QWidget):
    strokeRequested = Signal(float, float, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 300)
        self.setMouseTracking(True)
        self.kind = ""
        self.payload: dict[str, Any] = {}
        self.brush_radius = 0.08
        self._painting = False

    def set_preview(self, kind: str, payload: dict[str, Any]) -> None:
        self.kind = str(kind); self.payload = deepcopy(dict(payload)); self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in {Qt.LeftButton, Qt.RightButton}:
            self._painting = True; self._emit_stroke(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._painting and event.buttons() & (Qt.LeftButton | Qt.RightButton):
            self._emit_stroke(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._painting = False

    def _emit_stroke(self, event: QMouseEvent) -> None:
        point = event.position()
        self.strokeRequested.emit(max(0.0, min(1.0, point.x() / max(1, self.width()))),
                                  max(0.0, min(1.0, point.y() / max(1, self.height()))),
                                  event.button() == Qt.RightButton or bool(event.buttons() & Qt.RightButton))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#101820"))
        area = QRectF(10, 10, max(1, self.width() - 20), max(1, self.height() - 20))
        if self.kind == "terrain": self._draw_terrain(painter, area)
        elif self.kind in {"foliage", "biome"}: self._draw_instances(painter, area)
        elif self.kind == "navigation": self._draw_grid(painter, area, "tiles", QColor("#45d6bb"))
        elif self.kind == "partition": self._draw_grid(painter, area, "cells", QColor("#55aaff"))
        elif self.kind == "hlod": self._draw_hlod(painter, area)
        else:
            painter.setPen(QColor("#9cb4c5")); painter.drawText(area, Qt.AlignCenter, "Configure the asset to generate a preview")
        painter.end()

    def _draw_terrain(self, painter: QPainter, area: QRectF) -> None:
        width, depth = int(self.payload.get("width", 0)), int(self.payload.get("depth", 0))
        heights = [float(value) for value in self.payload.get("heights") or ()]
        if not width or len(heights) != width * depth: return
        minimum, maximum = min(heights), max(heights); span = max(1e-9, maximum - minimum)
        step_x, step_y = area.width() / width, area.height() / depth
        for z in range(depth):
            for x in range(width):
                value = (heights[z * width + x] - minimum) / span
                painter.fillRect(QRectF(area.left() + x * step_x, area.top() + z * step_y,
                                        step_x + 0.5, step_y + 0.5),
                                 QColor.fromHsvF(0.30 - value * 0.22, 0.58, 0.28 + value * 0.7))

    def _draw_instances(self, painter: QPainter, area: QRectF) -> None:
        instances = list(self.payload.get("instances") or self.payload.get("manual_instances") or ())
        if not instances: return
        positions = []
        for row in instances:
            if "u" in row: positions.append((float(row["u"]), float(row.get("v", 0.0))))
            else:
                position = list(row.get("position") or [0.0, 0.0, 0.0]); positions.append((float(position[0]), float(position[2])))
        xs, zs = [p[0] for p in positions], [p[1] for p in positions]
        min_x, max_x, min_z, max_z = min(xs), max(xs), min(zs), max(zs)
        painter.setPen(Qt.NoPen); painter.setBrush(QColor("#78d65b"))
        for x, z in positions:
            u = (x - min_x) / max(1e-9, max_x - min_x) if max_x > 1.0 or min_x < 0.0 else x
            v = (z - min_z) / max(1e-9, max_z - min_z) if max_z > 1.0 or min_z < 0.0 else z
            painter.drawEllipse(QPointF(area.left() + u * area.width(), area.top() + v * area.height()), 3.0, 3.0)

    def _draw_grid(self, painter: QPainter, area: QRectF, key: str, color: QColor) -> None:
        columns, rows = int(self.payload.get("columns", 1)), int(self.payload.get("rows", 1))
        cells = list(self.payload.get(key) or ())
        width, height = area.width() / columns, area.height() / rows
        for cell in cells:
            rect = QRectF(area.left() + int(cell.get("x", 0)) * width,
                          area.top() + int(cell.get("z", 0)) * height, width, height)
            active = str(cell.get("state") or "built") in {"loaded", "built"}
            fill = QColor(color); fill.setAlpha(95 if active else 18); painter.fillRect(rect, fill)
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 150), 1)); painter.drawRect(rect)
        for link in self.payload.get("off_mesh_links") or ():
            start, end = list(link.get("start") or [0, 0]), list(link.get("end") or [0, 0])
            painter.setPen(QPen(QColor("#ffcc55"), 2)); painter.drawLine(
                QPointF(area.left() + float(start[0]) * area.width(), area.top() + float(start[-1]) * area.height()),
                QPointF(area.left() + float(end[0]) * area.width(), area.top() + float(end[-1]) * area.height()))

    def _draw_hlod(self, painter: QPainter, area: QRectF) -> None:
        source, proxy = int(self.payload.get("source_triangles", 0)), int(self.payload.get("proxy_triangles", 0))
        split = area.adjusted(20, 30, -20, -40); half = split.width() * 0.45
        painter.fillRect(QRectF(split.left(), split.top(), half, split.height()), QColor("#477ca8"))
        ratio = proxy / max(1, source)
        painter.fillRect(QRectF(split.right() - half, split.bottom() - split.height() * ratio, half, split.height() * ratio), QColor("#69bd7b"))
        painter.setPen(QColor("white")); painter.drawText(area, Qt.AlignTop | Qt.AlignHCenter,
            f"Source {source:,} tris  →  Proxy {proxy:,} tris  ({self.payload.get('triangle_reduction_percent', 0)}% reduction)")


class WorldAssetAuthoringWidget(QWidget):
    changed = Signal()
    visualizationChanged = Signal(dict)

    def __init__(self, service: WorldAssetService, asset_id: str, type_id: str, parent=None) -> None:
        super().__init__(parent)
        self.service = service; self.asset_id = str(asset_id); self.type_id = str(type_id)
        self.values: dict[str, Any] = {}; self.preview: dict[str, Any] = {}
        self._build_timer = QTimer(self); self._build_timer.timeout.connect(self._advance_build)
        self._build_stage = 0
        root = QVBoxLayout(self)
        controls = QHBoxLayout(); root.addLayout(controls)
        self.mode = QComboBox(self); self.radius = QDoubleSpinBox(self); self.strength = QDoubleSpinBox(self)
        self.radius.setRange(0.005, 0.5); self.radius.setSingleStep(0.01); self.radius.setValue(0.08)
        self.strength.setRange(0.01, 5.0); self.strength.setValue(0.35)
        controls.addWidget(QLabel("Tool", self)); controls.addWidget(self.mode)
        controls.addWidget(QLabel("Radius", self)); controls.addWidget(self.radius)
        controls.addWidget(QLabel("Strength / Density", self)); controls.addWidget(self.strength)
        self.rebuild = QPushButton("Rebuild Preview", self); self.rebuild.clicked.connect(self.refresh_preview); controls.addWidget(self.rebuild)
        self.canvas = WorldAuthoringCanvas(self); self.canvas.strokeRequested.connect(self._stroke); root.addWidget(self.canvas, 1)
        self.progress = QProgressBar(self); self.progress.setRange(0, 100); self.progress.hide(); root.addWidget(self.progress)
        self.status = QLabel(self); self.status.setWordWrap(True); root.addWidget(self.status)
        if self.type_id == "tc.terrain": self.mode.addItems(["Raise", "Lower", "Smooth", "Flatten", "Paint Base"])
        elif self.type_id == "tc.foliage_type": self.mode.addItems(["Paint Instances", "Erase Instances"])
        elif self.type_id == "tc.lighting_scenario":
            self.mode.addItems(["Lighting Build"]); self.rebuild.setText("Build Lighting"); self.rebuild.clicked.disconnect(); self.rebuild.clicked.connect(self.start_lighting_build)
        elif self.type_id == "tc.hlod_layer": self.mode.addItems(["Source / Proxy"])
        else: self.mode.addItems(["Inspect"])
        self.radius.valueChanged.connect(lambda value: setattr(self.canvas, "brush_radius", float(value)))

    def load_settings(self, values: dict[str, Any]) -> None:
        self.values = deepcopy(dict(values)); self.refresh_preview()

    def settings(self) -> dict[str, Any]:
        return deepcopy(self.values)

    def refresh_preview(self) -> None:
        try:
            if self.type_id == "tc.terrain":
                self.preview = build_terrain_preview(self.values, maximum_resolution=257); kind = "terrain"
            elif self.type_id == "tc.foliage_type":
                self.preview = {"manual_instances": deepcopy(list(self.values.get("manual_instances") or ())) }; kind = "foliage"
            elif self.type_id == "tc.biome":
                self.preview = self.service.build_preview(self.asset_id, maximum_resolution=129); kind = "biome"
            elif self.type_id == "tc.navigation_mesh":
                self.preview = build_navigation_preview(self.values); kind = "navigation"
            elif self.type_id == "tc.lighting_scenario":
                self.preview = build_lighting_preview(self.values); kind = "lighting"
            elif self.type_id == "tc.world_partition":
                self.preview = build_partition_preview(self.values); kind = "partition"
            elif self.type_id == "tc.hlod_layer":
                self.preview = build_hlod_preview(self.values); kind = "hlod"
            else:
                self.preview = {"asset_ids": deepcopy(list(self.values.get("asset_ids") or ())) }; kind = "data_layer"
            self.canvas.set_preview(kind, self.preview)
            self.visualizationChanged.emit({"kind": kind, "asset_id": self.asset_id, "payload": deepcopy(self.preview)})
            self.status.setText(self._summary(kind))
        except Exception as exc:
            self.status.setText(str(exc)); self.canvas.set_preview("", {})

    def _stroke(self, u: float, v: float, right_button: bool) -> None:
        if self.type_id == "tc.terrain":
            label = self.mode.currentText(); mode = {
                "Raise": "lower" if right_button else "raise", "Lower": "raise" if right_button else "lower",
                "Smooth": "smooth", "Flatten": "flatten", "Paint Base": "paint",
            }.get(label, "raise")
            self.values = apply_terrain_brush(self.values, center=(u, v), radius=self.radius.value(),
                                              strength=(-1.0 if right_button and mode == "paint" else 1.0) * self.strength.value(),
                                              mode=mode, layer="Base")
        elif self.type_id == "tc.foliage_type":
            erase = right_button or self.mode.currentText().startswith("Erase")
            self.values = apply_foliage_brush(self.values, center=(u, v), radius=self.radius.value(),
                                              density=self.strength.value(), erase=erase,
                                              seed=int(self.values.get("paint_revision", 0)))
        else:
            return
        self.changed.emit(); self.refresh_preview()

    def start_lighting_build(self) -> None:
        self.preview = build_lighting_preview(self.values); self._build_stage = 0
        self.progress.setValue(0); self.progress.show(); self.rebuild.setEnabled(False); self._build_timer.start(80)

    def _advance_build(self) -> None:
        stages = list(self.preview.get("stages") or ())
        if self._build_stage >= len(stages):
            self._build_timer.stop(); self.progress.setValue(100); self.rebuild.setEnabled(True)
            self.values["last_build"] = {"status": "complete", "quality": self.values.get("quality", "production"),
                                         "estimated_texels": self.preview.get("estimated_texels", 0)}
            try:
                self.service.update(self.asset_id, self.values, replace=True)
                receipt = WorldBuildService(self.service.project_root, self.service.database).build(self.asset_id)
                self.status.setText(f"Lighting build complete: {receipt.statistics.get('sample_count', 0):,} irradiance samples • {receipt.artifact.path.name}")
            except Exception as exc:
                self.status.setText(f"Lighting build authoring completed, but backend packaging failed: {exc}")
            self.changed.emit(); self.visualizationChanged.emit({"kind": "lighting", "asset_id": self.asset_id, "payload": deepcopy(self.preview)})
            return
        complete = sum(float(row.get("weight", 0.0)) for row in stages[:self._build_stage + 1])
        self.status.setText(f"Building lighting: {stages[self._build_stage]['name']}…")
        self.progress.setValue(min(99, int(complete * 100))); self._build_stage += 1

    def _summary(self, kind: str) -> str:
        if kind == "terrain": return f"{self.preview.get('width', 0)}×{self.preview.get('depth', 0)} editable height samples. Left-drag applies the tool; right-drag reverses raise/paint."
        if kind in {"foliage", "biome"}: return f"{len(self.preview.get('instances') or self.preview.get('manual_instances') or ())} visible instances. Paint with left drag; erase with right drag."
        if kind == "navigation": return f"{len(self.preview.get('tiles') or ())} navigation tiles and {len(self.preview.get('agents') or ())} agent profile(s)."
        if kind == "partition": return f"{self.preview.get('loaded_cells', 0)} of {len(self.preview.get('cells') or ())} cells loaded by current streaming sources."
        if kind == "hlod": return f"Proxy estimate: {self.preview.get('proxy_triangles', 0):,} triangles."
        if kind == "lighting": return "Build uses staged geometry, direct/indirect lighting, reflection, denoise, and packaging passes."
        return "Layer membership and runtime state are available in the property editor."


__all__ = ["WorldAssetAuthoringWidget", "WorldAuthoringCanvas"]
