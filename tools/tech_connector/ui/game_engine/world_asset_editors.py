"""Interactive world-production previews and authoring controls."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QProgressBar, QPushButton, QSlider, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import WorldAssetService, WorldBuildService
from tech_connector.game_engine.assets.world_asset_service import (
    apply_foliage_brush, apply_terrain_brush, build_hlod_preview,
    build_lighting_preview, build_navigation_preview, build_partition_preview, build_terrain_preview,
    plan_navigation_rebuild, query_navigation_path,
)


class WorldAuthoringCanvas(QWidget):
    strokeRequested = Signal(float, float, bool)
    navigationPointRequested = Signal(float, float)

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
        if self.kind == "navigation" and event.button() == Qt.LeftButton:
            point = event.position()
            self.navigationPointRequested.emit(max(0.0, min(1.0, point.x() / max(1, self.width()))),
                                               max(0.0, min(1.0, point.y() / max(1, self.height()))))
            return
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
            cell_color = QColor(str(cell.get("color") or color.name()))
            fill = QColor(cell_color); fill.setAlpha(95 if active else 48); painter.fillRect(rect, fill)
            painter.setPen(QPen(QColor(cell_color.red(), cell_color.green(), cell_color.blue(), 150), 1)); painter.drawRect(rect)
        for link in self.payload.get("off_mesh_links") or ():
            start, end = list(link.get("start") or [0, 0]), list(link.get("end") or [0, 0])
            painter.setPen(QPen(QColor("#ffcc55"), 2)); painter.drawLine(
                QPointF(area.left() + float(start[0]) * area.width(), area.top() + float(start[-1]) * area.height()),
                QPointF(area.left() + float(end[0]) * area.width(), area.top() + float(end[-1]) * area.height()))
        path = list(self.payload.get("query_path") or ())
        if len(path) > 1:
            painter.setPen(QPen(QColor("#ffffff"), 3))
            for left, right in zip(path, path[1:]):
                painter.drawLine(QPointF(area.left() + float(left[0]) * area.width(), area.top() + float(left[-1]) * area.height()),
                                 QPointF(area.left() + float(right[0]) * area.width(), area.top() + float(right[-1]) * area.height()))
        for point, shade in ((self.payload.get("query_start"), "#55ff88"), (self.payload.get("query_goal"), "#ff6688")):
            if point:
                painter.setPen(Qt.NoPen); painter.setBrush(QColor(shade))
                painter.drawEllipse(QPointF(area.left() + float(point[0]) * area.width(),
                                           area.top() + float(point[-1]) * area.height()), 6.0, 6.0)

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


class NavigationToolsEditorWidget(QWidget):
    """Focused navigation authoring pages with shared, structured settings."""

    changed = Signal()
    visualizationChanged = Signal(dict)

    def __init__(self, service: WorldAssetService, asset_id: str, page: str, parent=None) -> None:
        super().__init__(parent)
        self.service = service; self.asset_id = str(asset_id); self.page = str(page)
        self.values: dict[str, Any] = {}; self._baseline: dict[str, Any] = {}
        self._loading = False; self._query_points: list[tuple[float, float]] = []
        self._build_timer = QTimer(self); self._build_timer.timeout.connect(self._advance_build)
        self._pending_tiles: list[str] = []
        self.root = QVBoxLayout(self)
        title = QLabel({
            "Agents": "Agent Profiles", "Areas & Costs": "Areas and Modifier Volumes",
            "Links": "Off-Mesh Links", "Build": "Navigation Build",
            "Runtime Debug": "Runtime Path Debugger",
        }.get(self.page, self.page), self)
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.root.addWidget(title)
        if self.page == "Agents": self._build_agents()
        elif self.page == "Areas & Costs": self._build_areas()
        elif self.page == "Links": self._build_links()
        elif self.page == "Build": self._build_build()
        else: self._build_debug()

    def _table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self); table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.itemChanged.connect(self._table_changed); self.root.addWidget(table)
        return table

    def _buttons(self, add_callback, remove_callback) -> None:
        row = QHBoxLayout(); add = QPushButton("Add", self); remove = QPushButton("Remove Selected", self)
        add.clicked.connect(add_callback); remove.clicked.connect(remove_callback)
        row.addWidget(add); row.addWidget(remove); row.addStretch(1); self.root.addLayout(row)

    def _build_agents(self) -> None:
        self.agents = self._table(["Name", "Radius", "Height", "Step Height", "Max Slope"])
        self._buttons(lambda: self._add_row(self.agents, ["Agent", "34", "180", "45", "45"]),
                      lambda: self._remove_rows(self.agents))

    def _build_areas(self) -> None:
        self.areas = self._table(["Area", "Traversal Cost", "Color"])
        self._buttons(lambda: self._add_row(self.areas, ["New Area", "1.0", "#7aa2f7"]),
                      lambda: self._remove_rows(self.areas))
        self.modifiers = self._table(["ID", "Area", "Min X", "Min Z", "Max X", "Max Z", "Enabled"])
        self._buttons(lambda: self._add_row(self.modifiers, [f"modifier:{self.modifiers.rowCount()+1}", "Blocked", ".35", ".35", ".65", ".65", "true"]),
                      lambda: self._remove_rows(self.modifiers))

    def _build_links(self) -> None:
        self.links = self._table(["ID", "Start X", "Start Z", "End X", "End Z", "Area", "Cost", "Two Way", "Enabled"])
        self._buttons(lambda: self._add_row(self.links, [f"link:{self.links.rowCount()+1}", ".2", ".5", ".8", ".5", "Walkable", "1", "true", "true"]),
                      lambda: self._remove_rows(self.links))

    def _build_build(self) -> None:
        form = QFormLayout(); self.root.addLayout(form)
        self.voxel = QDoubleSpinBox(self); self.voxel.setRange(.1, 10000); self.voxel.setDecimals(2)
        self.tile = QDoubleSpinBox(self); self.tile.setRange(1, 1000000); self.tile.setDecimals(1)
        self.region = QDoubleSpinBox(self); self.region.setRange(0, 1000000)
        self.runtime = QComboBox(self); self.runtime.addItems(["static", "dynamic_modifiers", "dynamic"])
        self.dynamic = QCheckBox("Update around runtime obstacles", self)
        form.addRow("Voxel Size", self.voxel); form.addRow("Tile Size", self.tile)
        form.addRow("Minimum Region Area", self.region); form.addRow("Runtime Generation", self.runtime)
        form.addRow("", self.dynamic)
        for control in (self.voxel, self.tile, self.region):
            control.valueChanged.connect(self._control_changed)
        self.runtime.currentTextChanged.connect(self._control_changed); self.dynamic.toggled.connect(self._control_changed)
        self.build_button = QPushButton("Build Dirty Tiles", self); self.build_button.clicked.connect(self.start_build)
        self.root.addWidget(self.build_button)
        self.progress = QProgressBar(self); self.progress.setRange(0, 100); self.root.addWidget(self.progress)
        self.status = QLabel("Change settings to calculate an incremental rebuild.", self)
        self.status.setWordWrap(True); self.root.addWidget(self.status); self.root.addStretch(1)

    def _build_debug(self) -> None:
        row = QHBoxLayout(); self.agent = QComboBox(self); self.clear_query = QPushButton("Clear Query", self)
        row.addWidget(QLabel("Agent", self)); row.addWidget(self.agent); row.addStretch(1); row.addWidget(self.clear_query)
        self.root.addLayout(row)
        self.canvas = WorldAuthoringCanvas(self); self.canvas.navigationPointRequested.connect(self._navigation_point)
        self.root.addWidget(self.canvas, 1)
        self.debug_status = QLabel("Click a start point, then a destination.", self)
        self.debug_status.setWordWrap(True); self.root.addWidget(self.debug_status)
        self.clear_query.clicked.connect(self._clear_query); self.agent.currentTextChanged.connect(self._run_query)

    def load_settings(self, values: dict[str, Any]) -> None:
        self.values = deepcopy(dict(values))
        if not self._baseline: self._baseline = deepcopy(self.values)
        self._loading = True
        if self.page == "Agents":
            self._load_rows(self.agents, [[row.get("name", ""), row.get("radius", 34), row.get("height", 180),
                                           row.get("step_height", 45), row.get("maximum_slope", 45)]
                                          for row in self.values.get("agents") or ()])
        elif self.page == "Areas & Costs":
            self._load_rows(self.areas, [[row.get("name", ""), row.get("cost", 1), row.get("color", "#45d6bb")]
                                         for row in self.values.get("areas") or ()])
            self._load_rows(self.modifiers, [[row.get("id", ""), row.get("area", "Blocked"),
                *(list(row.get("minimum") or [0, 0])[:2]), *(list(row.get("maximum") or [1, 1])[:2]),
                str(bool(row.get("enabled", True))).lower()] for row in self.values.get("modifiers") or ()])
        elif self.page == "Links":
            self._load_rows(self.links, [[row.get("id", ""), *(list(row.get("start") or [0, 0])[:2]),
                *(list(row.get("end") or [1, 1])[:2]), row.get("area", "Walkable"), row.get("cost", 1),
                str(bool(row.get("bidirectional", True))).lower(), str(bool(row.get("enabled", True))).lower()]
                for row in self.values.get("off_mesh_links") or ()])
        elif self.page == "Build":
            self.voxel.setValue(float(self.values.get("voxel_size", 10))); self.tile.setValue(float(self.values.get("tile_size", 1024)))
            self.region.setValue(float(self.values.get("region_minimum_area", 2)))
            self.runtime.setCurrentText(str(self.values.get("runtime_generation", "dynamic_modifiers")))
            self.dynamic.setChecked(bool(self.values.get("dynamic_obstacles", True))); self._update_plan()
        else:
            names = [str(row.get("name") or "Agent") for row in self.values.get("agents") or ()]
            current = self.agent.currentText(); self.agent.clear(); self.agent.addItems(names)
            if current in names: self.agent.setCurrentText(current)
            self._refresh_debug()
        self._loading = False

    def settings(self) -> dict[str, Any]:
        if self.page == "Agents":
            return {"agents": [{"name": row[0], "radius": _number(row[1]), "height": _number(row[2]),
                                "step_height": _number(row[3]), "maximum_slope": _number(row[4])}
                               for row in self._rows(self.agents)]}
        if self.page == "Areas & Costs":
            return {"areas": [{"name": row[0], "cost": _number(row[1]), "color": row[2]} for row in self._rows(self.areas)],
                    "modifiers": [{"id": row[0], "area": row[1], "minimum": [_number(row[2]), _number(row[3])],
                                   "maximum": [_number(row[4]), _number(row[5])], "enabled": _truth(row[6])}
                                  for row in self._rows(self.modifiers)]}
        if self.page == "Links":
            return {"off_mesh_links": [{"id": row[0], "start": [_number(row[1]), _number(row[2])],
                                        "end": [_number(row[3]), _number(row[4])], "area": row[5],
                                        "cost": _number(row[6]), "bidirectional": _truth(row[7]), "enabled": _truth(row[8])}
                                       for row in self._rows(self.links)]}
        if self.page == "Build":
            return {"voxel_size": self.voxel.value(), "tile_size": self.tile.value(),
                    "region_minimum_area": self.region.value(), "runtime_generation": self.runtime.currentText(),
                    "dynamic_obstacles": self.dynamic.isChecked()}
        return {}

    def _load_rows(self, table: QTableWidget, rows: list[list[Any]]) -> None:
        table.blockSignals(True); table.setRowCount(0)
        for values in rows: self._add_row(table, values, emit=False)
        table.blockSignals(False)

    def _rows(self, table: QTableWidget) -> list[list[str]]:
        return [[table.item(row, column).text().strip() if table.item(row, column) else ""
                 for column in range(table.columnCount())] for row in range(table.rowCount())]

    def _add_row(self, table: QTableWidget, values: list[Any], *, emit: bool = True) -> None:
        row = table.rowCount(); table.insertRow(row)
        for column, value in enumerate(values): table.setItem(row, column, QTableWidgetItem(str(value)))
        if emit: self._table_changed()

    def _remove_rows(self, table: QTableWidget) -> None:
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        if not rows and table.rowCount(): rows = [table.rowCount() - 1]
        for row in rows: table.removeRow(row)
        self._table_changed()

    def _table_changed(self, *_args) -> None:
        if not self._loading: self.changed.emit()

    def _control_changed(self, *_args) -> None:
        if self._loading: return
        self.values.update(self.settings()); self._update_plan(); self.changed.emit()

    def _update_plan(self) -> None:
        current = deepcopy(self.values); current.update(self.settings())
        plan = plan_navigation_rebuild(self._baseline, current)
        self.status.setText(f"{plan['dirty_tile_count']} of {plan['total_tile_count']} tiles dirty; "
                            f"{plan['reused_tile_count']} reusable. " + (", ".join(plan["reasons"]) or "Up to date."))
        self.build_button.setEnabled(plan["status"] == "dirty")

    def start_build(self) -> None:
        self.values.update(self.settings()); plan = plan_navigation_rebuild(self._baseline, self.values)
        self._pending_tiles = list(plan["dirty_tiles"])
        if not self._pending_tiles and plan["status"] == "clean": return
        self.progress.setValue(0); self.build_button.setEnabled(False); self._build_timer.start(25)

    def _advance_build(self) -> None:
        total = max(1, len(self._pending_tiles)); complete = min(total, max(1, self.progress.value() * total // 100 + max(1, total // 16)))
        self.progress.setValue(min(99, int(complete / total * 100)))
        if self.progress.value() < 99: return
        self._build_timer.stop()
        try:
            self.service.update(self.asset_id, self.values, replace=True)
            receipt = WorldBuildService(self.service.project_root, self.service.database).build(self.asset_id)
            self._baseline = deepcopy(self.values); self.values["last_build"] = {
                "status": "complete", "tile_count": receipt.statistics.get("tile_count", 0),
                "rebuilt_tile_count": len(self._pending_tiles), "reused_tile_count": max(0, receipt.statistics.get("tile_count", 0) - len(self._pending_tiles)),
            }
            self.service.update(self.asset_id, self.values, replace=True); self.progress.setValue(100)
            self.status.setText(f"Build complete: {len(self._pending_tiles)} dirty tiles rebuilt; {self.values['last_build']['reused_tile_count']} reused.")
            self.changed.emit()
        except Exception as exc:
            self.status.setText(f"Navigation build failed: {exc}")
        self.build_button.setEnabled(True)

    def _navigation_point(self, u: float, v: float) -> None:
        if len(self._query_points) >= 2: self._query_points.clear()
        self._query_points.append((u, v)); self._run_query()

    def _run_query(self, *_args) -> None:
        if len(self._query_points) < 2:
            self._refresh_debug(); return
        result = query_navigation_path(self.values, start=self._query_points[0], goal=self._query_points[1],
                                       agent_name=self.agent.currentText())
        preview = build_navigation_preview(self.values); preview["query_start"] = list(self._query_points[0])
        preview["query_goal"] = list(self._query_points[1]); preview["query_path"] = result["points"]
        self.canvas.set_preview("navigation", preview)
        self.debug_status.setText(f"{result['status'].title()}: {len(result['cells'])} tiles, cost {result['cost']}, "
                                  f"{result['visited']} visited" + (f", links: {', '.join(result['used_links'])}" if result["used_links"] else ""))
        self.visualizationChanged.emit({"kind": "navigation", "asset_id": self.asset_id, "payload": preview})

    def _refresh_debug(self) -> None:
        preview = build_navigation_preview(self.values)
        if self._query_points: preview["query_start"] = list(self._query_points[0])
        self.canvas.set_preview("navigation", preview)
        self.debug_status.setText("Click a start point, then a destination.")

    def _clear_query(self) -> None:
        self._query_points.clear(); self._refresh_debug()


def _number(value: str) -> float:
    try: return float(value)
    except (TypeError, ValueError): return 0.0


def _truth(value: str) -> bool:
    return str(value).strip().casefold() not in {"", "0", "false", "no", "off"}


__all__ = ["NavigationToolsEditorWidget", "WorldAssetAuthoringWidget", "WorldAuthoringCanvas"]
