"""Image data, layer stack, brush controls, and graphics canvas."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import time
import tempfile
import base64
from typing import Any, Callable

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from psd_tools import PSDImage
    HAS_PSD_TOOLS = True
except ImportError:
    HAS_PSD_TOOLS = False


from tech_connector.game_engine.integration.shaded_frame_provider import (
    parse_shaded_frame_output,
    maya_shaded_frame_code,
    blender_shaded_frame_code,
    unreal_shaded_frame_code,
    motionbuilder_shaded_frame_code,
)


def pil_to_qimage(pil_img) -> QImage:
    """Convert PIL Image to QImage Format_ARGB32_Premultiplied."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format_RGBA8888)
    return qimg.convertToFormat(QImage.Format_ARGB32_Premultiplied)

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
DESIGN_FILE_EXTENSIONS = {".psd", ".psb", ".xcf", ".spp", ".sbs", ".sbsar"}
OPENABLE_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | DESIGN_FILE_EXTENSIONS | {".tcimg"}


def compute_atmospheric_palette(base_color: QColor, haze_color: QColor | None = None) -> list[QColor]:
    """Compute 5-level Atmospheric Perspective Color Palette from base color and sky haze tint.
    
    Level 1: Deep Background Haze (lowest saturation, 40% blend towards haze tint)
    Level 2: Mid-Distance (reduced saturation, 18% blend towards haze tint)
    Level 3: Base / Default (current active brush color)
    Level 4: Foreground (boosted saturation, rich value)
    Level 5: Close Foreground (maximum saturation & contrast vibrancy)
    """
    if haze_color is None:
        haze_color = QColor(180, 205, 235)  # Default cool atmospheric sky haze

    h_base, s_base, v_base, a_base = base_color.getHsvF()
    h_haze, s_haze, v_haze, _ = haze_color.getHsvF()

    if h_base < 0:
        h_base = h_haze if h_haze >= 0 else 0.0

    colors = []

    # Level 1: Deep Background Haze (lowest saturation, 40% blend towards haze tint)
    s1 = max(0.0, min(1.0, s_base * 0.35))
    v1 = max(0.0, min(1.0, v_base * 0.65 + v_haze * 0.35))
    h1 = (h_base * 0.6 + h_haze * 0.4) if h_haze >= 0 else h_base
    colors.append(QColor.fromHsvF(h1 % 1.0, s1, v1, a_base))

    # Level 2: Mid-Distance (reduced saturation, 18% blend towards haze tint)
    s2 = max(0.0, min(1.0, s_base * 0.65))
    v2 = max(0.0, min(1.0, v_base * 0.82 + v_haze * 0.18))
    h2 = (h_base * 0.82 + h_haze * 0.18) if h_haze >= 0 else h_base
    colors.append(QColor.fromHsvF(h2 % 1.0, s2, v2, a_base))

    # Level 3: Base / Default (current active brush color)
    colors.append(QColor(base_color))

    # Level 4: Foreground (boosted saturation, deeper value)
    s4 = max(0.0, min(1.0, s_base * 1.30 if s_base > 0.05 else 0.25))
    v4 = max(0.0, min(1.0, v_base * 1.05))
    colors.append(QColor.fromHsvF(h_base % 1.0, s4, v4, a_base))

    # Level 5: Close Foreground (maximum saturation & contrast vibrancy)
    s5 = max(0.0, min(1.0, s_base * 1.60 if s_base > 0.05 else 0.45))
    v5 = max(0.0, min(1.0, v_base * 1.12))
    colors.append(QColor.fromHsvF(h_base % 1.0, s5, v5, a_base))

    return colors


class ImageLayer:
    """Represents a single raster or annotation layer in the Image Editor layer stack."""

    def __init__(self, name: str, width: int = 1920, height: int = 1080, fill_color: QColor | None = None):
        self.name = name
        self.visible = True
        self.locked = False
        self.opacity = 1.0  # 0.0 to 1.0
        self.blend_mode = "Normal"  # Normal, Multiply, Screen, Overlay, Add, Subtract, Difference, Heatmap
        
        self.image = QImage(max(1, width), max(1, height), QImage.Format_ARGB32_Premultiplied)
        if fill_color is not None:
            self.image.fill(fill_color)
        else:
            self.image.fill(Qt.transparent)

        self.mask: QImage | None = None
        self.mask_enabled = True
        self.editing_mask = False

    def add_mask(self, fill_white: bool = True):
        """Add non-destructive layer mask to layer."""
        w, h = self.image.width(), self.image.height()
        self.mask = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        self.mask.fill(Qt.white if fill_white else Qt.black)
        self.mask_enabled = True
        self.editing_mask = False

    def copy(self, new_name: str = "") -> "ImageLayer":
        layer = ImageLayer(new_name or f"{self.name} Copy", self.image.width(), self.image.height())
        layer.visible = self.visible
        layer.locked = self.locked
        layer.opacity = self.opacity
        layer.blend_mode = self.blend_mode
        layer.image = self.image.copy()
        if self.mask is not None:
            layer.mask = self.mask.copy()
        layer.mask_enabled = self.mask_enabled
        layer.editing_mask = self.editing_mask
        return layer

    def to_project_dict(self) -> dict[str, Any]:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        self.image.save(buffer, "PNG")
        buffer.close()
        return {
            "name": self.name,
            "visible": self.visible,
            "locked": self.locked,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "png_base64": base64.b64encode(bytes(data)).decode("ascii"),
        }

    @classmethod
    def from_project_dict(cls, data: dict[str, Any], width: int, height: int) -> "ImageLayer":
        layer = cls(str(data.get("name") or "Layer"), width, height)
        layer.visible = bool(data.get("visible", True))
        layer.locked = bool(data.get("locked", False))
        try:
            layer.opacity = max(0.0, min(1.0, float(data.get("opacity", 1.0))))
        except Exception:
            layer.opacity = 1.0
        layer.blend_mode = str(data.get("blend_mode") or "Normal")
        raw = base64.b64decode(str(data.get("png_base64") or ""))
        img = QImage()
        if raw and img.loadFromData(raw, "PNG"):
            layer.image = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        return layer


class LayerStack:
    """Manages ordered multi-layer compositing, blend modes, and active selection."""

    def __init__(self, width: int = 1280, height: int = 720):
        self.width = max(1, width)
        self.height = max(1, height)
        self.layers: list[ImageLayer] = []
        self.active_index = 0
        self.history: list[list[ImageLayer]] = []
        self.history_index = -1

    def add_layer(self, layer: ImageLayer | None = None, name: str = "", fill_color: QColor | None = None) -> ImageLayer:
        if layer is None:
            layer = ImageLayer(name or f"Layer {len(self.layers) + 1}", self.width, self.height, fill_color=fill_color)
        self.layers.append(layer)
        self.active_index = len(self.layers) - 1
        self.save_snapshot()
        return layer

    @property
    def active_layer(self) -> ImageLayer | None:
        if 0 <= self.active_index < len(self.layers):
            return self.layers[self.active_index]
        return None

    def composite(self) -> QImage:
        result = QImage(self.width, self.height, QImage.Format_ARGB32_Premultiplied)
        result.fill(QColor(15, 15, 20, 255))
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        for layer in self.layers:
            if not layer.visible or layer.image.isNull():
                continue
            painter.setOpacity(layer.opacity)
            
            # Apply non-destructive layer mask if present and enabled
            layer_img = layer.image
            if layer.mask is not None and layer.mask_enabled and not layer.mask.isNull():
                layer_img = layer.image.copy()
                mp = QPainter(layer_img)
                mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
                mp.drawImage(0, 0, layer.mask)
                mp.end()
            
            if layer.blend_mode == "Multiply":
                painter.setCompositionMode(QPainter.CompositionMode_Multiply)
            elif layer.blend_mode == "Screen":
                painter.setCompositionMode(QPainter.CompositionMode_Screen)
            elif layer.blend_mode == "Overlay":
                painter.setCompositionMode(QPainter.CompositionMode_Overlay)
            elif layer.blend_mode in {"Add", "Additive"}:
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
            elif layer.blend_mode == "Difference":
                painter.setCompositionMode(QPainter.CompositionMode_Difference)
            else:
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            painter.drawImage(0, 0, layer_img)

        painter.end()
        return result

    def save_snapshot(self):
        snapshot = [l.copy() for l in self.layers]
        if self.history_index < len(self.history) - 1:
            self.history = self.history[: self.history_index + 1]
        self.history.append(snapshot)
        if len(self.history) > 20:
            self.history.pop(0)
        self.history_index = len(self.history) - 1

    def undo(self) -> bool:
        if self.history_index > 0:
            self.history_index -= 1
            self.layers = [l.copy() for l in self.history[self.history_index]]
            self.active_index = min(self.active_index, max(0, len(self.layers) - 1))
            return True
        return False

    def redo(self) -> bool:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.layers = [l.copy() for l in self.history[self.history_index]]
            self.active_index = min(self.active_index, max(0, len(self.layers) - 1))
            return True
        return False


class VanishingPointHandleItem(QGraphicsItem):
    """Interactive Vanishing Point handle for N-Point Perspective guidelines in Tech Connector Image Editor."""

    def __init__(self, name: str, label: str, color: QColor, parent=None):
        super().__init__(parent)
        self.name = name
        self.label = label
        self.color = color
        self.hovered = False

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsScenePositionChanges
            | QGraphicsItem.ItemIgnoresTransformations
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(200.0)  # Always render above image & selection items

    def boundingRect(self) -> QRectF:
        return QRectF(-35, -35, 120, 70)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)

        ring_color = QColor(self.color)
        ring_color.setAlpha(255 if self.hovered else 200)

        pen_width = 3.0 if self.hovered else 2.0
        painter.setPen(QPen(ring_color, pen_width))
        painter.setBrush(QBrush(QColor(10, 15, 25, 210)))

        radius = 11.0 if self.hovered else 9.0
        painter.drawEllipse(QPointF(0, 0), radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ring_color))
        painter.drawEllipse(QPointF(0, 0), 3.5, 3.5)

        painter.setPen(QPen(ring_color, 1.5))
        painter.drawLine(-16, 0, -7, 0)
        painter.drawLine(7, 0, 16, 0)
        painter.drawLine(0, -16, 0, -7)
        painter.drawLine(0, 7, 0, 16)

        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        painter.setPen(QPen(QColor(0, 0, 0, 220)))
        painter.drawText(QRectF(-34, -27, 110, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{self.name} ({self.label})")
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(QRectF(-35, -28, 110, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{self.name} ({self.label})")

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene:
                for view in scene.views():
                    view.viewport().update()
        return super().itemChange(change, value)


def create_procedural_brush_mask(preset_name: str, size: int, hardness: float = 0.8, tilt_x: float = 0.0, tilt_y: float = 0.0) -> QImage:
    """Generate 8-bit alpha brush mask QImage adhering to selected brush preset and tilt/lean angle (-1..1)."""
    sz = max(4, size)
    mask = QImage(sz, sz, QImage.Format_ARGB32_Premultiplied)
    mask.fill(Qt.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.Antialiasing, True)

    center = sz / 2.0
    radius = sz / 2.0
    mag = math.hypot(tilt_x, tilt_y)

    if mag > 0.01:
        angle_deg = math.degrees(math.atan2(tilt_y, tilt_x if tilt_x != 0 else 0.001))
        painter.translate(center, center)
        painter.rotate(angle_deg)
        scale_u = 1.0 + 0.45 * mag
        scale_v = max(0.2, 1.0 - 0.65 * mag)
        painter.scale(scale_u, scale_v)
        painter.translate(-center, -center)

    if preset_name in ("Hard Round", "Square Block"):
        painter.setBrush(QBrush(QColor(255, 255, 255, 255)))
        painter.setPen(Qt.NoPen)
        if preset_name == "Square Block":
            painter.drawRect(0, 0, sz, sz)
        else:
            painter.drawEllipse(0, 0, sz, sz)
    else:
        for y in range(sz):
            for x in range(sz):
                dx = x - center
                dy = y - center
                r = math.hypot(dx, dy)
                if r <= radius:
                    norm_r = r / radius
                    chisel_bias = 1.0 + (tilt_x * (dx / radius) + tilt_y * (dy / radius)) * 0.5 if mag > 0.01 else 1.0
                    chisel_bias = max(0.1, min(2.0, chisel_bias))

                    if preset_name == "Soft Airbrush":
                        alpha = int(255 * math.pow(max(0.0, 1.0 - norm_r), 2.0 / max(0.1, hardness)) * chisel_bias)
                    elif preset_name in ("Chalk Grain", "Noise Texture"):
                        import random
                        grain = random.uniform(0.45, 1.0)
                        alpha = int(255 * math.pow(max(0.0, 1.0 - norm_r), 1.2) * grain * chisel_bias)
                    elif preset_name == "Grunge Stencil":
                        stencil_val = (math.sin(x * 0.4) * math.cos(y * 0.4) + 1.0) / 2.0
                        alpha = int(255 * (1.0 - norm_r) * stencil_val * chisel_bias)
                    else:
                        alpha = int(255 * (1.0 - norm_r) * chisel_bias)
                    mask.setPixelColor(x, y, QColor(255, 255, 255, max(0, min(255, alpha))))

    painter.end()
    return mask


class BrushTiltGraphWidget(QFrame):
    """Interactive -1.0 to +1.0 2D Brush Lean / Tilt Angle Graph Control Widget."""

    tilt_changed = Signal(float, float)  # tilt_x (-1..1), tilt_y (-1..1)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 36)
        self.setStyleSheet("QFrame { background: #04080c; border: 1px solid #16f26a; border-radius: 4px; }")
        self.tilt_x = 0.0  # -1.0 (Left) to +1.0 (Right), 0.0 = Upright
        self.tilt_y = 0.0  # -1.0 (Top) to +1.0 (Bottom)
        self.is_dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            self._update_tilt_from_pos(event.position())

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self._update_tilt_from_pos(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False

    def mouseDoubleClickEvent(self, event):
        self.tilt_x = 0.0
        self.tilt_y = 0.0
        self.update()
        self.tilt_changed.emit(self.tilt_x, self.tilt_y)

    def _update_tilt_from_pos(self, pos: QPointF):
        w, h = self.width(), self.height()
        norm_x = (pos.x() / float(w)) * 2.0 - 1.0
        norm_y = (pos.y() / float(h)) * 2.0 - 1.0
        self.tilt_x = max(-1.0, min(1.0, norm_x))
        self.tilt_y = max(-1.0, min(1.0, norm_y))
        self.update()
        self.tilt_changed.emit(self.tilt_x, self.tilt_y)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        axis_pen = QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine)
        painter.setPen(axis_pen)
        painter.drawLine(int(cx), 0, int(cx), h)
        painter.drawLine(0, int(cy), w, int(cy))

        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QPen(QColor(156, 219, 186, 180)))
        painter.drawText(4, 12, "-1")
        painter.drawText(w - 18, 12, "+1")

        cursor_x = cx + self.tilt_x * (cx - 10.0)
        cursor_y = cy + self.tilt_y * (cy - 6.0)

        vector_pen = QPen(QColor(22, 242, 106, 180), 1.5, Qt.SolidLine)
        painter.setPen(vector_pen)
        painter.drawLine(QPointF(cx, cy), QPointF(cursor_x, cursor_y))

        painter.save()
        painter.translate(cursor_x, cursor_y)
        angle_deg = math.degrees(math.atan2(self.tilt_y, self.tilt_x if self.tilt_x != 0 else 0.001))
        painter.rotate(angle_deg)
        
        mag = math.hypot(self.tilt_x, self.tilt_y)
        rx = 6.0 + mag * 6.0
        ry = max(2.5, 6.0 - mag * 3.5)

        painter.setBrush(QBrush(QColor(22, 242, 106, 230)))
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.drawEllipse(QRectF(-rx / 2.0, -ry / 2.0, rx, ry))
        painter.restore()

        tilt_deg = int(self.tilt_x * 90.0)
        readout = f"LEAN: {self.tilt_x:+.2f} ({tilt_deg:>+3d}°)"
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.drawText(int(cx) - 34, h - 4, readout)

        painter.end()


class ImageViewerGraphicsView(QGraphicsView):
    """GPU-Accelerated 60 FPS viewport for zooming, panning, interactive brushes, 2D Grid, and Perspective Overlays."""

    color_hovered = Signal(int, int, QColor)
    draw_stroke_finished = Signal(object, QPointF, QPointF, str)  # path, start, end, tool_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        # Selection overlay item
        self.selection_item = QGraphicsPathItem()
        pen = QPen(QColor(22, 242, 106), 1.5, Qt.DashLine)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(10, 14, 20)))

        self.zoom_level = 1.0
        self.is_panning = False
        self.is_drawing = False
        self.pan_start = QPointF()
        self.draw_start = QPointF()
        self.current_path = QPainterPath()

        # O Key + Drag Opacity State
        self.is_o_held = False
        self.is_adjusting_opacity = False
        self.opacity_drag_start = QPointF()
        self.initial_layer_opacity = 1.0

        # B Key + Drag Brush Size State
        self.is_b_held = False
        self.is_adjusting_brush_size = False
        self.brush_size_drag_start = QPointF()
        self.initial_brush_size = 18

        # T Key + Drag / Hotkey Text Font Size State
        self.is_t_held = False
        self.is_adjusting_text_size = False
        self.text_size_drag_start = QPointF()
        self.initial_font_size = 24

        # 2D Grid State
        self.grid_enabled = False
        self.grid_size = 32
        self.grid_color = QColor(255, 255, 255, 45)
        self.snap_to_grid = False

        # Perspective Guideline State
        self.perspective_mode = "Off"  # "Off", "1-Point Perspective", "2-Point Perspective", "3-Point Perspective"
        self.show_perspective_guides = True
        self.perspective_ray_density = 16
        self.snap_to_perspective = False
        self.guide_opacity = 1.0        # 0.0 (invisible) â†’ 1.0 (full alpha)
        self.isolated_vp = "All"        # "All" | "VP1" | "VP2" | "VP3" | "VP4" | "VP5" | "VP6"
        self.show_golden_ratio_overlay = False
        self.golden_overlay_type = "Rule of Thirds"  # "Rule of Thirds" | "Golden Spiral" | "Phi Grid" | "Golden Triangle" | "Golden Rectangle"
        self.golden_overlay_constrained = True       # True = bounded by canvas + dynamic focal tracking
        self.golden_overlay_pos = QPointF(0.0, 0.0)  # scene coords focal point of overlay
        self.golden_overlay_rot = 0.0                 # degrees
        self.golden_overlay_scale = 1.0               # relative to canvas width
        self._golden_drag_origin: QPointF | None = None
        self._golden_drag_start_pos: QPointF | None = None
        self._golden_drag_start_rot: float = 0.0
        self._golden_drag_mode: str = "none"          # "move" | "rotate"
        self.vp_handles: dict[str, VanishingPointHandleItem] = {}

        # Camera & Cinematography State
        self.camera_aspect_mode = "Off"  # "Off", "2.39:1 Anamorphic", "1.85:1 Academy Flat", "16:9 Widescreen", "4:3 IMAX", "1:1 Square", "9:16 Vertical", "Action/Title Safe"
        self.camera_aspect_opacity = 0.75 # 0.0 -> 1.0 matte darkness
        self.show_action_title_safe = False
        self.camera_fov_mode = "Off"     # "Off", "14mm Ultra-Wide (114°)", "24mm Wide (84°)", "35mm Street (63°)", "50mm Standard (47°)", "85mm Portrait (28°)", "135mm Telephoto (18°)"
        self.value_check_mode = False     # B&W Monochrome contrast evaluation
        self.false_color_mode = False    # ARRI/RED false color exposure evaluation

        # Symmetry Painting Engine State
        self.symmetry_mode = "Off"  # "Off", "Vertical", "Horizontal", "Quad"

        self.hud_toast_text = ""
        self.init_vp_handles()

    def show_hud_toast(self, text: str):
        self.hud_toast_text = text
        self.viewport().update()

    def keyPressEvent(self, event):
        if not event.modifiers() and Qt.Key_1 <= event.key() <= Qt.Key_5:
            level = event.key() - Qt.Key_1 + 1
            curr = self.parent()
            while curr is not None:
                if hasattr(curr, "select_atmospheric_level"):
                    curr.select_atmospheric_level(level)
                    return
                curr = curr.parent()
        super().keyPressEvent(event)

    def drawForeground(self, painter: QPainter, rect: QRectF):
        super().drawForeground(painter, rect)

        pixmap_rect = self.pixmap_item.boundingRect()
        w = pixmap_rect.width() if not pixmap_rect.isEmpty() else 1280.0
        h = pixmap_rect.height() if not pixmap_rect.isEmpty() else 720.0

        # 0. Draw Live Symmetry Axis Guides
        if self.symmetry_mode != "Off":
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            sym_pen = QPen(QColor(0, 220, 255, 200), 1.5, Qt.DashDotLine)
            painter.setPen(sym_pen)

            cx, cy = w / 2.0, h / 2.0
            if self.symmetry_mode in ("Vertical", "Quad"):
                painter.drawLine(QPointF(cx, 0), QPointF(cx, h))
            if self.symmetry_mode in ("Horizontal", "Quad"):
                painter.drawLine(QPointF(0, cy), QPointF(w, cy))
            painter.restore()

        # 1. Draw 2D Grid
        if self.grid_enabled:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, False)
            grid_pen = QPen(self.grid_color, 1, Qt.SolidLine)
            painter.setPen(grid_pen)

            step = max(4, self.grid_size)
            start_x = int(pixmap_rect.left()) - (int(pixmap_rect.left()) % step)
            end_x = int(pixmap_rect.right()) + step
            start_y = int(pixmap_rect.top()) - (int(pixmap_rect.top()) % step)
            end_y = int(pixmap_rect.bottom()) + step

            for x in range(start_x, end_x, step):
                if pixmap_rect.left() <= x <= pixmap_rect.right():
                    painter.drawLine(x, int(pixmap_rect.top()), x, int(pixmap_rect.bottom()))

            for y in range(start_y, end_y, step):
                if pixmap_rect.top() <= y <= pixmap_rect.bottom():
                    painter.drawLine(int(pixmap_rect.left()), y, int(pixmap_rect.right()), y)

            painter.restore()

        # 2. Draw Interactive Perspective Guidelines (1 to 6 Point)
        if self.perspective_mode != "Off" and self.show_perspective_guides:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            density = max(2, self.perspective_ray_density)

            vp1_pos = self.vp_handles["VP1"].scenePos() if "VP1" in self.vp_handles else QPointF(w * 0.5, h * 0.4)
            vp2_pos = self.vp_handles["VP2"].scenePos() if "VP2" in self.vp_handles else QPointF(w * 1.4, h * 0.4)
            vp3_pos = self.vp_handles["VP3"].scenePos() if "VP3" in self.vp_handles else QPointF(w * 0.5, -h * 0.8)
            vp4_pos = self.vp_handles["VP4"].scenePos() if "VP4" in self.vp_handles else QPointF(w * 0.5, h * 1.8)
            vp5_pos = self.vp_handles["VP5"].scenePos() if "VP5" in self.vp_handles else QPointF(w * 0.5, h * 0.4)
            vp6_pos = self.vp_handles["VP6"].scenePos() if "VP6" in self.vp_handles else QPointF(w * 0.5, h * 0.55)

            mode = self.perspective_mode
            _op = max(0.0, min(1.0, self.guide_opacity))
            _iso = self.isolated_vp  # "All" | "VP1" | "VP2" | ...

            # Helper: scale a QColor's alpha by the current guide opacity
            def gc(r, g, b, a=255):
                return QColor(r, g, b, max(0, min(255, int(a * _op))))

            # Helper: should we draw this VP's lines?  True when All or exact match.
            def iso(*vps):
                return _iso == "All" or _iso in vps

            if mode == "1-Point Perspective":
                if iso("VP1"):
                    pen = QPen(gc(30, 155, 255, 140), 1, Qt.DashLine)
                    painter.setPen(pen)
                    num_rays = density * 2
                    for i in range(num_rays):
                        angle = (2.0 * math.pi / num_rays) * i
                        far_x = vp1_pos.x() + 4000.0 * math.cos(angle)
                        far_y = vp1_pos.y() + 4000.0 * math.sin(angle)
                        painter.drawLine(vp1_pos, QPointF(far_x, far_y))

                    ortho_pen = QPen(gc(22, 242, 106, 80), 1, Qt.SolidLine)
                    painter.setPen(ortho_pen)
                    for i in range(density + 1):
                        y_pos = (h / float(density)) * i
                        painter.drawLine(0, int(y_pos), int(w), int(y_pos))
                        x_pos = (w / float(density)) * i
                        painter.drawLine(int(x_pos), 0, int(x_pos), int(h))

            elif mode in ("2-Point Perspective", "3-Point Perspective"):
                # 1. Horizon Line VP1 ↔ VP2 (always shown — structural baseline)
                if iso("VP1", "VP2"):
                    horizon_pen = QPen(gc(22, 242, 106, 220), 2, Qt.SolidLine)
                    painter.setPen(horizon_pen)
                    dx = vp2_pos.x() - vp1_pos.x()
                    dy = vp2_pos.y() - vp1_pos.y()
                    dist = math.hypot(dx, dy)
                    if dist > 0.001:
                        dir_x, dir_y = dx / dist, dy / dist
                        h_start = QPointF(vp1_pos.x() - dir_x * 6000, vp1_pos.y() - dir_y * 6000)
                        h_end   = QPointF(vp2_pos.x() + dir_x * 6000, vp2_pos.y() + dir_y * 6000)
                        painter.drawLine(h_start, h_end)
                        painter.setFont(QFont("Consolas", 9, QFont.Bold))
                        painter.setPen(QPen(gc(22, 242, 106, 200)))
                        painter.drawText(vp1_pos + QPointF(20, -12), "HORIZON LINE (VP1 â†” VP2)")
                else:
                    # Need dx/dy for ray calculations even when horizon is hidden
                    dx = vp2_pos.x() - vp1_pos.x()
                    dy = vp2_pos.y() - vp1_pos.y()
                    dist = math.hypot(dx, dy)

                angle_vp1 = math.atan2(dy, dx)
                fov_spread = math.pi * 0.7

                # 2. Rays from VP1
                if iso("VP1"):
                    pen_vp1 = QPen(gc(30, 155, 255, 140), 1, Qt.DashLine)
                    painter.setPen(pen_vp1)
                    for i in range(density + 1):
                        frac = (i / float(density)) - 0.5
                        ray_angle = angle_vp1 + frac * fov_spread
                        far_pt = QPointF(vp1_pos.x() + 5000.0 * math.cos(ray_angle),
                                         vp1_pos.y() + 5000.0 * math.sin(ray_angle))
                        painter.drawLine(vp1_pos, far_pt)

                # 3. Rays from VP2
                if iso("VP2"):
                    pen_vp2 = QPen(gc(240, 140, 30, 140), 1, Qt.DashLine)
                    painter.setPen(pen_vp2)
                    angle_vp2 = math.atan2(-dy, -dx)
                    for i in range(density + 1):
                        frac = (i / float(density)) - 0.5
                        ray_angle = angle_vp2 + frac * fov_spread
                        far_pt = QPointF(vp2_pos.x() + 5000.0 * math.cos(ray_angle),
                                         vp2_pos.y() + 5000.0 * math.sin(ray_angle))
                        painter.drawLine(vp2_pos, far_pt)

                if mode == "2-Point Perspective":
                    # Vertical parallel guide lines (shown unless isolated to a single VP)
                    if iso("VP1", "VP2"):
                        v_pen = QPen(gc(255, 255, 255, 70), 1, Qt.SolidLine)
                        painter.setPen(v_pen)
                        for i in range(density + 1):
                            x_pos = (w / float(density)) * i
                            painter.drawLine(int(x_pos), -int(h), int(x_pos), int(h * 2))

                elif mode == "3-Point Perspective":
                    # Triangle frame
                    if iso("VP1", "VP2", "VP3"):
                        tri_pen = QPen(gc(200, 60, 255, 200), 1.5, Qt.SolidLine)
                        painter.setPen(tri_pen)
                        painter.drawLine(vp1_pos, vp3_pos)
                        painter.drawLine(vp2_pos, vp3_pos)

                    # Rays from VP3
                    if iso("VP3"):
                        pen_vp3 = QPen(gc(200, 60, 255, 140), 1, Qt.DashLine)
                        painter.setPen(pen_vp3)
                        for i in range(-density, density * 2 + 1):
                            t_frac = i / float(density)
                            horizon_target = QPointF(vp1_pos.x() + dx * t_frac, vp1_pos.y() + dy * t_frac)
                            ray_dx = horizon_target.x() - vp3_pos.x()
                            ray_dy = horizon_target.y() - vp3_pos.y()
                            ray_dist = math.hypot(ray_dx, ray_dy)
                            if ray_dist > 0.001:
                                far_pt = QPointF(vp3_pos.x() + (ray_dx / ray_dist) * 5000.0,
                                                 vp3_pos.y() + (ray_dy / ray_dist) * 5000.0)
                                painter.drawLine(vp3_pos, far_pt)

            elif mode in ("4-Point Perspective (Curvilinear)", "5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
                dx = vp2_pos.x() - vp1_pos.x()
                dy = vp2_pos.y() - vp1_pos.y()

                # â”€â”€ Horizontal Axis: Horizon Line VP1(N/W) â†” VP2(E) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # Always visible — it's the fundamental horizon of this perspective
                # even when one VP is isolated it still provides the structural baseline
                if iso("VP1", "VP2"):
                    dist_h = math.hypot(dx, dy)
                    if dist_h > 0.001:
                        dir_hx, dir_hy = dx / dist_h, dy / dist_h
                        h_far = 7000.0
                        h_start = QPointF(vp1_pos.x() - dir_hx * h_far, vp1_pos.y() - dir_hy * h_far)
                        h_end   = QPointF(vp2_pos.x() + dir_hx * h_far, vp2_pos.y() + dir_hy * h_far)
                        painter.setPen(QPen(gc(22, 242, 106, 160), 1, Qt.SolidLine))
                        painter.drawLine(h_start, h_end)
                    # Bold VP1â†”VP2 segment highlight
                    painter.setPen(QPen(gc(22, 242, 106, 230), 2, Qt.SolidLine))
                    painter.drawLine(vp1_pos, vp2_pos)

                # â”€â”€ Vertical Axis: VP3(H/Top Zenith) â†” VP4(B/Bottom Nadir) â”€â”€â”€â”€â”€
                if iso("VP3", "VP4"):
                    dvx = vp4_pos.x() - vp3_pos.x()
                    dvy = vp4_pos.y() - vp3_pos.y()
                    dist_v = math.hypot(dvx, dvy)
                    if dist_v > 0.001:
                        dir_vx, dir_vy = dvx / dist_v, dvy / dist_v
                        v_far = 7000.0
                        v_start = QPointF(vp3_pos.x() - dir_vx * v_far, vp3_pos.y() - dir_vy * v_far)
                        v_end   = QPointF(vp4_pos.x() + dir_vx * v_far, vp4_pos.y() + dir_vy * v_far)
                        painter.setPen(QPen(gc(200, 60, 255, 160), 1, Qt.SolidLine))
                        painter.drawLine(v_start, v_end)
                    # Bold VP3â†”VP4 segment highlight
                    painter.setPen(QPen(gc(200, 60, 255, 230), 2, Qt.SolidLine))
                    painter.drawLine(vp3_pos, vp4_pos)

                # Outer framing diamond (VP1â†”VP3, VP3â†”VP2, VP2â†”VP4, VP4â†”VP1)
                if iso("VP1", "VP2", "VP3", "VP4"):
                    frame_pen = QPen(gc(255, 255, 255, 70), 1, Qt.DashLine)
                    painter.setPen(frame_pen)
                    painter.drawLine(vp1_pos, vp3_pos)
                    painter.drawLine(vp3_pos, vp2_pos)
                    painter.drawLine(vp2_pos, vp4_pos)
                    painter.drawLine(vp4_pos, vp1_pos)


                half_density = max(1, density // 2)

                # 1. Horizontal Curvilinear Arcs VP1 â†” VP2 (bounded by VP3 & VP4)
                if iso("VP1", "VP2"):
                    mid_12  = QPointF((vp1_pos.x() + vp2_pos.x()) / 2.0, (vp1_pos.y() + vp2_pos.y()) / 2.0)
                    top_vec = QPointF(vp3_pos.x() - mid_12.x(), vp3_pos.y() - mid_12.y())
                    bot_vec = QPointF(vp4_pos.x() - mid_12.x(), vp4_pos.y() - mid_12.y())
                    arc_pen_h = QPen(gc(30, 155, 255, 140), 1, Qt.SolidLine)
                    painter.setPen(arc_pen_h)
                    for i in range(1, half_density + 1):
                        factor = i / float(half_density)
                        for vec in (top_vec, bot_vec):
                            ctrl = mid_12 + vec * (2.0 * factor)
                            path = QPainterPath()
                            path.moveTo(vp1_pos)
                            path.quadTo(ctrl, vp2_pos)
                            painter.drawPath(path)

                # 2. Vertical Curvilinear Arcs VP3 â†” VP4 (bounded by VP1 & VP2)
                if iso("VP3", "VP4"):
                    mid_34   = QPointF((vp3_pos.x() + vp4_pos.x()) / 2.0, (vp3_pos.y() + vp4_pos.y()) / 2.0)
                    left_vec = QPointF(vp1_pos.x() - mid_34.x(), vp1_pos.y() - mid_34.y())
                    right_vec= QPointF(vp2_pos.x() - mid_34.x(), vp2_pos.y() - mid_34.y())
                    arc_pen_v = QPen(gc(30, 220, 120, 140), 1, Qt.SolidLine)
                    painter.setPen(arc_pen_v)
                    for i in range(1, half_density + 1):
                        factor = i / float(half_density)
                        for vec in (left_vec, right_vec):
                            ctrl = mid_34 + vec * (2.0 * factor)
                            path = QPainterPath()
                            path.moveTo(vp3_pos)
                            path.quadTo(ctrl, vp4_pos)
                            painter.drawPath(path)

                # â”€â”€ 5-Point Fisheye: Full-diameter spoke grid centered on VP5 â”€â”€â”€â”€
                # radius = AVERAGE distance to all 4 boundary VPs so the circle
                # consistently passes through (or near) all of them.
                radius5 = 1.0
                if mode in ("5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
                    if iso("VP5"):
                        dists = [math.hypot(bvp.x() - vp5_pos.x(), bvp.y() - vp5_pos.y())
                                 for bvp in (vp1_pos, vp2_pos, vp3_pos, vp4_pos)]
                        radius5 = sum(dists) / len(dists) if any(d > 0.001 for d in dists) else 1.0

                        # Boundary circle
                        f_pen = QPen(gc(255, 40, 120, 180), 1.5, Qt.DashLine)
                        painter.setPen(f_pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawEllipse(vp5_pos, radius5, radius5)

                        # Full-diameter radial spokes through VP5.
                        # Each spoke passes THROUGH VP5 in both directions (like a wheel).
                        # We collect unique half-angles (0 to Ï€) so we only draw each
                        # diameter once, then extend it ±7000 in both directions.
                        ray_pen = QPen(gc(255, 40, 120, 100), 1, Qt.SolidLine)
                        painter.setPen(ray_pen)

                        half_angles: set[float] = set()
                        # Guaranteed spokes through the 4 boundary VPs
                        for bvp in (vp1_pos, vp2_pos, vp3_pos, vp4_pos):
                            adx = bvp.x() - vp5_pos.x()
                            ady = bvp.y() - vp5_pos.y()
                            if math.hypot(adx, ady) > 0.001:
                                ang = math.atan2(ady, adx)
                                # Normalise to [0, Ï€) so opposite directions map to same spoke
                                if ang < 0:
                                    ang += math.pi
                                half_angles.add(ang)
                        # Evenly-spaced additional spokes
                        n_spokes = max(8, density)
                        for i in range(n_spokes):
                            half_angles.add((math.pi / n_spokes) * i)

                        for ang in half_angles:
                            # Extend in both directions through VP5
                            p1 = QPointF(vp5_pos.x() - 7000.0 * math.cos(ang),
                                         vp5_pos.y() - 7000.0 * math.sin(ang))
                            p2 = QPointF(vp5_pos.x() + 7000.0 * math.cos(ang),
                                         vp5_pos.y() + 7000.0 * math.sin(ang))
                            painter.drawLine(p1, p2)

                # â”€â”€ 6-Point: Independent rear-pole fisheye system at VP6 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # VP6 represents the back/rear hemisphere in a 360° wrap.
                # It gets the same full-diameter spoke grid as VP5 (front pole).
                if mode == "6-Point Perspective (360° Spherical)":
                    if iso("VP6"):
                        # VP6 radius = same average formula referenced from VP5's boundary VPs
                        dists6 = [math.hypot(bvp.x() - vp6_pos.x(), bvp.y() - vp6_pos.y())
                                  for bvp in (vp1_pos, vp2_pos, vp3_pos, vp4_pos)]
                        radius6 = sum(dists6) / len(dists6) if any(d > 0.001 for d in dists6) else radius5

                        # Rear boundary circle (gold, dotted)
                        b_pen = QPen(gc(255, 210, 40, 180), 1.5, Qt.DotLine)
                        painter.setPen(b_pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawEllipse(vp6_pos, radius6, radius6)

                        # Full-diameter spokes centered on VP6
                        rear_ray_pen = QPen(gc(255, 210, 40, 80), 1, Qt.SolidLine)
                        painter.setPen(rear_ray_pen)
                        n_spokes6 = max(8, density)
                        half_angles6: set[float] = set()
                        for bvp in (vp1_pos, vp2_pos, vp3_pos, vp4_pos):
                            adx = bvp.x() - vp6_pos.x()
                            ady = bvp.y() - vp6_pos.y()
                            if math.hypot(adx, ady) > 0.001:
                                ang = math.atan2(ady, adx)
                                if ang < 0:
                                    ang += math.pi
                                half_angles6.add(ang)
                        for i in range(n_spokes6):
                            half_angles6.add((math.pi / n_spokes6) * i)
                        for ang in half_angles6:
                            p1 = QPointF(vp6_pos.x() - 7000.0 * math.cos(ang),
                                         vp6_pos.y() - 7000.0 * math.sin(ang))
                            p2 = QPointF(vp6_pos.x() + 7000.0 * math.cos(ang),
                                         vp6_pos.y() + 7000.0 * math.sin(ang))
                            painter.drawLine(p1, p2)

                        # Frontâ†”Rear optical axis
                        painter.setPen(QPen(gc(255, 210, 40, 200), 1.5, Qt.SolidLine))
                        painter.drawLine(vp5_pos, vp6_pos)






            painter.restore()

        # 3. Draw Golden Ratio & Rule of Thirds Composition Overlay
        if self.show_golden_ratio_overlay:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)

            pix_rect = self.pixmap_item.boundingRect()
            img_w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            img_h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

            phi = 1.61803398875
            gold_col   = gc(255, 210, 40, 210)
            guide_pen  = QPen(gold_col, 1.5, Qt.SolidLine)
            accent_pen = QPen(gc(255, 255, 255, 110), 1.0, Qt.DashLine)
            focal_pen  = QPen(gc(255, 40, 120, 230), 2.0, Qt.SolidLine)
            painter.setBrush(Qt.NoBrush)

            otype = self.golden_overlay_type

            if self.golden_overlay_constrained:
                # â”€â”€ Image Canvas Constrained Mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                # Bounded exactly by [0, 0, img_w, img_h]
                # Active focal point (fx, fy) tracks active VP or user focal position
                if self.golden_overlay_pos == QPointF(0.0, 0.0):
                    if "VP5" in self.vp_handles and self.perspective_mode in ("5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
                        self.golden_overlay_pos = QPointF(self.vp_handles["VP5"].scenePos())
                    elif "VP1" in self.vp_handles and self.perspective_mode != "Off":
                        self.golden_overlay_pos = QPointF(self.vp_handles["VP1"].scenePos())
                    else:
                        self.golden_overlay_pos = QPointF(img_w * 0.382, img_h * 0.382)

                fx = max(0.0, min(img_w, self.golden_overlay_pos.x()))
                fy = max(0.0, min(img_h, self.golden_overlay_pos.y()))
                focal_pt = QPointF(fx, fy)

                # Outer Canvas Bounding Box
                painter.setPen(guide_pen)
                painter.drawRect(QRectF(0, 0, img_w, img_h))

                if otype == "Rule of Thirds":
                    # Dynamic Rule of Thirds locked to (fx, fy) inside canvas
                    x1 = fx
                    x2 = img_w - fx if abs(fx - img_w / 2.0) > 5.0 else img_w * (2.0 / 3.0)
                    y1 = fy
                    y2 = img_h - fy if abs(fy - img_h / 2.0) > 5.0 else img_h * (2.0 / 3.0)

                    painter.setPen(guide_pen)
                    painter.drawLine(QPointF(x1, 0), QPointF(x1, img_h))
                    painter.drawLine(QPointF(x2, 0), QPointF(x2, img_h))
                    painter.drawLine(QPointF(0, y1), QPointF(img_w, y1))
                    painter.drawLine(QPointF(0, y2), QPointF(img_w, y2))

                    # 4 Rule-of-Thirds power points
                    painter.setPen(QPen(gold_col, 2.0))
                    for px in (x1, x2):
                        for py in (y1, y2):
                            painter.drawEllipse(QPointF(px, py), 6.0, 6.0)

                elif otype == "Phi Grid":
                    # Dynamic Phi Grid locked to (fx, fy) inside canvas
                    x1 = fx
                    x2 = img_w - (img_w - fx) / phi if fx < img_w / 2.0 else fx / phi
                    y1 = fy
                    y2 = img_h - (img_h - fy) / phi if fy < img_h / 2.0 else fy / phi

                    painter.setPen(guide_pen)
                    painter.drawLine(QPointF(x1, 0), QPointF(x1, img_h))
                    painter.drawLine(QPointF(x2, 0), QPointF(x2, img_h))
                    painter.drawLine(QPointF(0, y1), QPointF(img_w, y1))
                    painter.drawLine(QPointF(0, y2), QPointF(img_w, y2))

                    painter.setPen(QPen(gold_col, 2.5))
                    for px in (x1, x2):
                        for py in (y1, y2):
                            painter.drawEllipse(QPointF(px, py), 5.0, 5.0)

                elif otype == "Golden Spiral":
                    # Recursive golden rectangle cascade converging on (fx, fy)
                    rx, ry, rw, rh = 0.0, 0.0, img_w, img_h
                    qx = 0 if fx < img_w / 2.0 else 1
                    qy = 0 if fy < img_h / 2.0 else 1
                    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)] if (qx, qy) == (0, 0) else \
                           [(-1, 0), (0, 1), (1, 0), (0, -1)] if (qx, qy) == (1, 0) else \
                           [(-1, 0), (0, -1), (1, 0), (0, 1)] if (qx, qy) == (1, 1) else \
                           [(1, 0), (0, -1), (-1, 0), (0, 1)]

                    for lvl in range(7):
                        dd = dirs[lvl % 4]
                        sq = min(rw, rh)
                        if dd == (1, 0):
                            sx, sy, sw, sh = rx, ry, sq, rh
                            nx, ny, nw, nh = rx + sq, ry, rw - sq, rh
                            arc_cx, arc_cy, arc_r = rx + sq, ry + (sh / 2.0 if sh < sw else sq / 2.0), sq / 2.0
                        elif dd == (0, 1):
                            sx, sy, sw, sh = rx, ry + rh - sq, rw, sq
                            nx, ny, nw, nh = rx, ry, rw, rh - sq
                            arc_cx, arc_cy, arc_r = rx + sw / 2.0, ry + rh - sq, sq / 2.0
                        elif dd == (-1, 0):
                            sx, sy, sw, sh = rx + rw - sq, ry, sq, rh
                            nx, ny, nw, nh = rx, ry, rw - sq, rh
                            arc_cx, arc_cy, arc_r = rx + rw - sq, ry + sh / 2.0, sq / 2.0
                        else:
                            sx, sy, sw, sh = rx, ry, rw, sq
                            nx, ny, nw, nh = rx, ry + sq, rw, rh - sq
                            arc_cx, arc_cy, arc_r = rx + sw / 2.0, ry + sq, sq / 2.0

                        painter.setPen(accent_pen)
                        painter.drawRect(QRectF(sx, sy, max(sw, 1.0), max(sh, 1.0)))
                        painter.setPen(guide_pen)
                        arc_path = QPainterPath()
                        start_a = [180, 90, 0, 270][lvl % 4]
                        arc_path.arcTo(QRectF(arc_cx - arc_r, arc_cy - arc_r, arc_r * 2.0, arc_r * 2.0), start_a, -90)
                        painter.drawPath(arc_path)
                        rx, ry, rw, rh = nx, ny, max(nw, 1.0), max(nh, 1.0)
                        if rw < 4 or rh < 4:
                            break

                elif otype == "Golden Triangle":
                    tl, tr = QPointF(0, 0), QPointF(img_w, 0)
                    bl, br = QPointF(0, img_h), QPointF(img_w, img_h)

                    painter.setPen(guide_pen)
                    painter.drawLine(bl, tr)
                    painter.setPen(accent_pen)
                    painter.drawLine(tl, focal_pt)
                    painter.drawLine(br, focal_pt)
                    painter.drawLine(tr, focal_pt)
                    painter.drawLine(bl, focal_pt)

                elif otype == "Golden Rectangle":
                    painter.setPen(guide_pen)
                    painter.drawLine(QPointF(fx, 0), QPointF(fx, img_h))
                    painter.drawLine(QPointF(0, fy), QPointF(img_w, fy))

                    painter.setPen(accent_pen)
                    painter.drawLine(QPointF(0, 0), QPointF(img_w, img_h))
                    painter.drawLine(QPointF(img_w, 0), QPointF(0, img_h))

                # â”€â”€ Dynamic Focal Reticle at (fx, fy) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                painter.setPen(focal_pen)
                painter.drawEllipse(focal_pt, 9.0, 9.0)
                painter.drawEllipse(focal_pt, 4.0, 4.0)
                painter.drawLine(QPointF(fx - 14, fy), QPointF(fx - 5, fy))
                painter.drawLine(QPointF(fx + 5, fy), QPointF(fx + 14, fy))
                painter.drawLine(QPointF(fx, fy - 14), QPointF(fx, fy - 5))
                painter.drawLine(QPointF(fx, fy + 5), QPointF(fx, fy + 14))

                painter.setFont(QFont("Consolas", 8, QFont.Bold))
                painter.setPen(QPen(gc(255, 210, 40, 220)))
                painter.drawText(focal_pt + QPointF(12, -8), f"🎯 Focal Point ({int(fx)}, {int(fy)})")

            else:
                # â”€â”€ Free Transform Mode (Unconstrained, Rotatable, Scalable) â”€â”€â”€
                base = img_w * self.golden_overlay_scale
                cx = self.golden_overlay_pos.x()
                cy = self.golden_overlay_pos.y()

                painter.translate(cx, cy)
                painter.rotate(self.golden_overlay_rot)

                if otype == "Rule of Thirds":
                    w, h = base, base * (img_h / img_w) if img_w > 0 else base * 0.75
                    painter.setPen(guide_pen)
                    painter.drawRect(QRectF(-w / 2, -h / 2, w, h))
                    painter.setPen(accent_pen)
                    for frac in (1 / 3, 2 / 3):
                        xoff = -w / 2 + w * frac
                        painter.drawLine(QPointF(xoff, -h / 2), QPointF(xoff, h / 2))
                        yoff = -h / 2 + h * frac
                        painter.drawLine(QPointF(-w / 2, yoff), QPointF(w / 2, yoff))

                elif otype == "Golden Spiral":
                    w = base
                    h = base / phi
                    painter.setPen(guide_pen)
                    painter.drawRect(QRectF(-w / 2, -h / 2, w, h))
                    rx, ry, rw, rh = -w / 2, -h / 2, w, h
                    directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]
                    for lvl in range(7):
                        dd = directions[lvl % 4]
                        sq = min(rw, rh)
                        if dd == (1, 0):
                            sx, sy, sw, sh = rx, ry, sq, rh
                            nx, ny, nw, nh = rx + sq, ry, rw - sq, rh
                            arc_cx, arc_cy, arc_r = rx + sq, ry + (sh / 2 if sh < sw else sq / 2), sq / 2
                        elif dd == (0, 1):
                            sx, sy, sw, sh = rx, ry + rh - sq, rw, sq
                            nx, ny, nw, nh = rx, ry, rw, rh - sq
                            arc_cx, arc_cy, arc_r = rx + sw / 2, ry + rh - sq, sq / 2
                        elif dd == (-1, 0):
                            sx, sy, sw, sh = rx + rw - sq, ry, sq, rh
                            nx, ny, nw, nh = rx, ry, rw - sq, rh
                            arc_cx, arc_cy, arc_r = rx + rw - sq, ry + sh / 2, sq / 2
                        else:
                            sx, sy, sw, sh = rx, ry, rw, sq
                            nx, ny, nw, nh = rx, ry + sq, rw, rh - sq
                            arc_cx, arc_cy, arc_r = rx + sw / 2, ry + sq, sq / 2

                        painter.setPen(accent_pen)
                        painter.drawRect(QRectF(sx, sy, sw if sw > 0 else 1, sh if sh > 0 else 1))
                        painter.setPen(guide_pen)
                        arc_path = QPainterPath()
                        start_a = [180, 90, 0, 270][lvl % 4]
                        arc_path.arcTo(QRectF(arc_cx - arc_r, arc_cy - arc_r, arc_r * 2, arc_r * 2), start_a, -90)
                        painter.drawPath(arc_path)
                        rx, ry, rw, rh = nx, ny, max(nw, 1.0), max(nh, 1.0)
                        if rw < 2 or rh < 2:
                            break

                elif otype == "Phi Grid":
                    w, h = base, base / phi
                    short = base / (1.0 + phi)
                    long_ = base - short
                    sh = h / (1.0 + phi)
                    lh = h - sh
                    painter.setPen(guide_pen)
                    painter.drawRect(QRectF(-w / 2, -h / 2, w, h))
                    painter.setPen(accent_pen)
                    for xoff in (-w / 2 + short, -w / 2 + long_):
                        painter.drawLine(QPointF(xoff, -h / 2), QPointF(xoff, h / 2))
                    for yoff in (-h / 2 + sh, -h / 2 + lh):
                        painter.drawLine(QPointF(-w / 2, yoff), QPointF(w / 2, yoff))
                    painter.setPen(QPen(gold_col, 4.0, Qt.SolidLine))
                    for xoff in (-w / 2 + short, -w / 2 + long_):
                        for yoff in (-h / 2 + sh, -h / 2 + lh):
                            painter.drawPoint(QPointF(xoff, yoff))

                elif otype == "Golden Triangle":
                    s = base
                    h = s * (phi / 2.0)
                    tl = QPointF(-s / 2, h / 2)
                    tr = QPointF(s / 2, h / 2)
                    top = QPointF(0, -h / 2)
                    painter.setPen(guide_pen)
                    painter.drawLine(tl, tr)
                    painter.drawLine(tr, top)
                    painter.drawLine(top, tl)
                    split_x = tl.x() + (tr.x() - tl.x()) / phi
                    split_y = h / 2
                    foot = QPointF(split_x, split_y)
                    painter.setPen(accent_pen)
                    painter.drawLine(top, foot)
                    split2_x = top.x() + (tr.x() - top.x()) * (1.0 - 1.0 / phi)
                    split2_y = top.y() + (tr.y() - top.y()) * (1.0 - 1.0 / phi)
                    painter.drawLine(tl, QPointF(split2_x, split2_y))

                elif otype == "Golden Rectangle":
                    w, h = base, base / phi
                    painter.setPen(guide_pen)
                    painter.drawRect(QRectF(-w / 2, -h / 2, w, h))
                    painter.setPen(accent_pen)
                    painter.drawLine(QPointF(-w / 2, -h / 2), QPointF(w / 2, h / 2))
                    painter.drawLine(QPointF(w / 2, -h / 2), QPointF(-w / 2, h / 2))
                    gl = -h / 2 + h / phi
                    painter.setPen(QPen(gold_col, 1.2, Qt.DashDotLine))
                    painter.drawLine(QPointF(-w / 2, gl - h / 2), QPointF(w / 2, gl - h / 2))

                # Rotation handle ring
                ring_r = base * 0.07
                painter.setPen(QPen(QColor(255, 210, 40, 150), 1.5, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(0, 0), ring_r, ring_r)
                painter.setPen(QPen(QColor(255, 255, 255, 200), 2.5))
                painter.drawPoint(QPointF(0, 0))

                painter.setPen(QPen(QColor(255, 210, 40, 230), 2.0))
                painter.setBrush(QBrush(QColor(255, 210, 40, 230)))
                painter.drawEllipse(QPointF(0, -ring_r), 4, 4)

            painter.restore()

        # 4. Camera Aspect Ratio & Matte Overlay (Cinematic Framing & Safe Areas)
        if self.camera_aspect_mode != "Off":
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)

            pix_rect = self.pixmap_item.boundingRect()
            img_w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            img_h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

            ratio_map = {
                "2.39:1 Anamorphic": 2.39,
                "1.85:1 Academy Flat": 1.85,
                "16:9 Widescreen": 16.0 / 9.0,
                "4:3 IMAX": 4.0 / 3.0,
                "1:1 Square": 1.0,
                "9:16 Vertical": 9.0 / 16.0,
                "Action/Title Safe": img_w / img_h if img_h > 0 else 1.777,
            }
            target_r = ratio_map.get(self.camera_aspect_mode, 1.777)

            if img_w / img_h >= target_r:
                crop_h = img_h
                crop_w = img_h * target_r
            else:
                crop_w = img_w
                crop_h = img_w / target_r

            cx = (img_w - crop_w) / 2.0
            cy = (img_h - crop_h) / 2.0
            crop_rect = QRectF(cx, cy, crop_w, crop_h)

            # Dark Letterbox Matte Overlay
            matte_alpha = int(255 * max(0.1, min(1.0, self.camera_aspect_opacity)))
            matte_color = QColor(0, 0, 0, matte_alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(matte_color))

            # Top & Bottom mattes
            if cy > 0.5:
                painter.drawRect(QRectF(0, 0, img_w, cy))
                painter.drawRect(QRectF(0, cy + crop_h, img_w, img_h - (cy + crop_h)))
            # Left & Right mattes
            if cx > 0.5:
                painter.drawRect(QRectF(0, cy, cx, crop_h))
                painter.drawRect(QRectF(cx + crop_w, cy, img_w - (cx + crop_w), crop_h))

            # Golden Framing Line around Aspect Box
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(gc(255, 210, 40, 220), 1.5, Qt.SolidLine))
            painter.drawRect(crop_rect)

            # Aspect Ratio Text Badge
            badge_text = f"🎬 {self.camera_aspect_mode.upper()}"
            painter.setFont(QFont("Consolas", 9, QFont.Bold))
            painter.setPen(QPen(gc(255, 210, 40, 240)))
            painter.drawText(crop_rect.adjusted(10, 8, -10, -8), Qt.AlignTop | Qt.AlignLeft, badge_text)

            # Action / Title Safe lines (90% Action, 80% Title)
            if self.camera_aspect_mode == "Action/Title Safe" or self.show_action_title_safe:
                # 90% Action Safe (Dashed Yellow)
                action_w, action_h = crop_w * 0.9, crop_h * 0.9
                action_rect = QRectF(cx + crop_w * 0.05, cy + crop_h * 0.05, action_w, action_h)
                painter.setPen(QPen(gc(255, 220, 60, 200), 1.0, Qt.DashLine))
                painter.drawRect(action_rect)
                painter.setFont(QFont("Consolas", 7))
                painter.drawText(action_rect.adjusted(4, 3, 0, 0), Qt.AlignTop | Qt.AlignLeft, "ACTION SAFE (90%)")

                # 80% Title Safe (Dashed Cyan)
                title_w, title_h = crop_w * 0.8, crop_h * 0.8
                title_rect = QRectF(cx + crop_w * 0.1, cy + crop_h * 0.1, title_w, title_h)
                painter.setPen(QPen(gc(60, 220, 255, 200), 1.0, Qt.DashLine))
                painter.drawRect(title_rect)
                painter.drawText(title_rect.adjusted(4, 3, 0, 0), Qt.AlignTop | Qt.AlignLeft, "TITLE SAFE (80%)")

            painter.restore()

        # 5. Camera Lens FOV Cone Simulator
        if self.camera_fov_mode != "Off":
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)

            pix_rect = self.pixmap_item.boundingRect()
            img_w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            img_h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

            fov_angles = {
                "14mm Ultra-Wide (114°)": 114.0,
                "24mm Wide (84°)": 84.0,
                "35mm Street (63°)": 63.0,
                "50mm Standard (47°)": 47.0,
                "85mm Portrait (28°)": 28.0,
                "135mm Telephoto (18°)": 18.0,
            }
            fov_deg = fov_angles.get(self.camera_fov_mode, 47.0)
            fov_rad = math.radians(fov_deg)

            # Station Point / Camera Position
            if "VP5" in self.vp_handles and self.perspective_mode in ("5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
                st_pt = self.vp_handles["VP5"].scenePos()
            elif "VP1" in self.vp_handles and self.perspective_mode != "Off":
                st_pt = self.vp_handles["VP1"].scenePos()
            else:
                st_pt = QPointF(img_w / 2.0, img_h * 1.15)

            target_pt = QPointF(img_w / 2.0, img_h / 2.0)
            center_angle = math.atan2(target_pt.y() - st_pt.y(), target_pt.x() - st_pt.x())

            half_fov = fov_rad / 2.0
            a1 = center_angle - half_fov
            a2 = center_angle + half_fov

            length = 8000.0
            p1 = QPointF(st_pt.x() + length * math.cos(a1), st_pt.y() + length * math.sin(a1))
            p2 = QPointF(st_pt.x() + length * math.cos(a2), st_pt.y() + length * math.sin(a2))

            # FOV Cone Rays
            painter.setPen(QPen(gc(60, 200, 255, 180), 1.5, Qt.SolidLine))
            painter.drawLine(st_pt, p1)
            painter.drawLine(st_pt, p2)

            # FOV Arc
            arc_r = min(img_w, img_h) * 0.45
            arc_rect = QRectF(st_pt.x() - arc_r, st_pt.y() - arc_r, arc_r * 2.0, arc_r * 2.0)
            start_deg = -math.degrees(a2)
            span_deg = math.degrees(fov_rad)
            painter.setPen(QPen(gc(60, 200, 255, 140), 1.0, Qt.DashLine))
            arc_path = QPainterPath()
            arc_path.arcTo(arc_rect, start_deg, span_deg)
            painter.drawPath(arc_path)

            # Camera Station Badge
            painter.setPen(QPen(gc(60, 200, 255, 230), 2.0))
            painter.setBrush(QBrush(gc(10, 20, 35, 220)))
            painter.drawEllipse(st_pt, 7.0, 7.0)

            painter.setFont(QFont("Consolas", 8, QFont.Bold))
            painter.drawText(st_pt + QPointF(10, -10), f"📷 {self.camera_fov_mode}")

            painter.restore()

        # 6. Draw HUD Toast Overlay


        if self.hud_toast_text:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setFont(QFont("Consolas", 11, QFont.Bold))

            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self.hud_toast_text) + 28
            th = 32.0

            view_top_left = self.mapToScene(16, 16)
            scale_fac = 1.0 / self.zoom_level
            toast_rect = QRectF(view_top_left.x(), view_top_left.y(), tw * scale_fac, th * scale_fac)

            painter.setPen(QPen(QColor(22, 242, 106, 230), 1.5))
            painter.setBrush(QBrush(QColor(8, 14, 22, 230)))
            painter.drawRoundedRect(toast_rect, 6 * scale_fac, 6 * scale_fac)

            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(toast_rect, Qt.AlignCenter, self.hud_toast_text)
            painter.restore()

    def init_vp_handles(self):
        vp_configs = [
            ("VP1", "Left / Main VP", QColor(30, 155, 255)),     # Cyan-Blue
            ("VP2", "Right VP", QColor(240, 140, 30)),          # Amber-Orange
            ("VP3", "Top Zenith VP", QColor(200, 60, 255)),     # Purple
            ("VP4", "Bottom Nadir VP", QColor(30, 220, 120)),   # Emerald Green
            ("VP5", "Center / Front VP", QColor(255, 40, 120)), # Magenta-Pink
            ("VP6", "Back / Rear VP", QColor(255, 210, 40)),    # Gold-Yellow
        ]
        for name, label, color in vp_configs:
            handle = VanishingPointHandleItem(name, label, color)
            handle.setVisible(False)
            self.scene.addItem(handle)
            self.vp_handles[name] = handle
        self.reset_vp_positions()

    def reset_vp_positions(self, width: float = 1280.0, height: float = 720.0):
        pix_rect = self.pixmap_item.boundingRect()
        if not pix_rect.isEmpty():
            w, h = pix_rect.width(), pix_rect.height()
        else:
            w, h = width, height

        mode = self.perspective_mode
        if mode in ("4-Point Perspective (Curvilinear)", "5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
            if "VP1" in self.vp_handles: self.vp_handles["VP1"].setPos(w * 0.05, h * 0.5)
            if "VP2" in self.vp_handles: self.vp_handles["VP2"].setPos(w * 0.95, h * 0.5)
            if "VP3" in self.vp_handles: self.vp_handles["VP3"].setPos(w * 0.5, h * 0.05)
            if "VP4" in self.vp_handles: self.vp_handles["VP4"].setPos(w * 0.5, h * 0.95)
            if "VP5" in self.vp_handles: self.vp_handles["VP5"].setPos(w * 0.5, h * 0.5)
            if "VP6" in self.vp_handles: self.vp_handles["VP6"].setPos(w * 0.5, h * 0.5)
        else:
            if "VP1" in self.vp_handles: self.vp_handles["VP1"].setPos(w * 0.5 if mode == "1-Point Perspective" else -w * 0.3, h * 0.4)
            if "VP2" in self.vp_handles: self.vp_handles["VP2"].setPos(w * 1.3, h * 0.4)
            if "VP3" in self.vp_handles: self.vp_handles["VP3"].setPos(w * 0.5, -h * 0.6)
            if "VP4" in self.vp_handles: self.vp_handles["VP4"].setPos(w * 0.5, h * 1.6)
            if "VP5" in self.vp_handles: self.vp_handles["VP5"].setPos(w * 0.5, h * 0.4)
            if "VP6" in self.vp_handles: self.vp_handles["VP6"].setPos(w * 0.5, h * 0.55)
        self.viewport().update()

    def align_guides_to_golden_ratio(self):
        """Align Vanishing Points, Horizon Line, and Perspective Guides to the Golden Ratio (1 : 1.618034)."""
        pix_rect = self.pixmap_item.boundingRect()
        w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
        h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

        phi = 1.61803398875
        g1_y = h * (1.0 - 1.0 / phi)  # ~0.381966 * h (Golden Horizon Height)
        g2_y = h * (1.0 / phi)        # ~0.618034 * h
        g1_x = w * (1.0 - 1.0 / phi)  # ~0.381966 * w
        g2_x = w * (1.0 / phi)        # ~0.618034 * w

        mode = self.perspective_mode
        if mode == "Off":
            self.set_perspective_mode("2-Point Perspective")
            mode = "2-Point Perspective"

        if mode == "1-Point Perspective":
            if "VP1" in self.vp_handles: self.vp_handles["VP1"].setPos(g2_x, g1_y)
        elif mode in ("2-Point Perspective", "3-Point Perspective"):
            if "VP1" in self.vp_handles: self.vp_handles["VP1"].setPos(-w * (phi - 1.0), g1_y)
            if "VP2" in self.vp_handles: self.vp_handles["VP2"].setPos(w * phi, g1_y)
            if "VP3" in self.vp_handles: self.vp_handles["VP3"].setPos(g1_x, -h * phi)
        elif mode in ("4-Point Perspective (Curvilinear)", "5-Point Perspective (Fisheye Lens)", "6-Point Perspective (360° Spherical)"):
            if "VP1" in self.vp_handles: self.vp_handles["VP1"].setPos(w * 0.08, g1_y)
            if "VP2" in self.vp_handles: self.vp_handles["VP2"].setPos(w * 0.92, g1_y)
            if "VP3" in self.vp_handles: self.vp_handles["VP3"].setPos(g1_x, h * 0.08)
            if "VP4" in self.vp_handles: self.vp_handles["VP4"].setPos(g1_x, h * 0.92)
            if "VP5" in self.vp_handles: self.vp_handles["VP5"].setPos(g2_x, g1_y)
            if "VP6" in self.vp_handles: self.vp_handles["VP6"].setPos(g2_x, g1_y)

        self.show_golden_ratio_overlay = True
        self.viewport().update()
        self.show_hud_toast("âœ¨ Guides Aligned to Golden Ratio (1 : 1.618) Composition!")

    def set_perspective_mode(self, mode: str):
        self.perspective_mode = mode
        is_1p = mode == "1-Point Perspective"
        is_2p = mode == "2-Point Perspective"
        is_3p = mode == "3-Point Perspective"
        is_4p = mode == "4-Point Perspective (Curvilinear)"
        is_5p = mode == "5-Point Perspective (Fisheye Lens)"
        is_6p = mode == "6-Point Perspective (360° Spherical)"

        if "VP1" in self.vp_handles: self.vp_handles["VP1"].setVisible(is_1p or is_2p or is_3p or is_4p or is_5p or is_6p)
        if "VP2" in self.vp_handles: self.vp_handles["VP2"].setVisible(is_2p or is_3p or is_4p or is_5p or is_6p)
        if "VP3" in self.vp_handles: self.vp_handles["VP3"].setVisible(is_3p or is_4p or is_5p or is_6p)
        if "VP4" in self.vp_handles: self.vp_handles["VP4"].setVisible(is_4p or is_5p or is_6p)
        if "VP5" in self.vp_handles: self.vp_handles["VP5"].setVisible(is_5p or is_6p)
        if "VP6" in self.vp_handles: self.vp_handles["VP6"].setVisible(is_6p)

        self.reset_vp_positions()

        self.viewport().update()

    def set_grid_enabled(self, enabled: bool):
        self.grid_enabled = enabled
        self.viewport().update()

    def set_grid_size(self, size: int):
        self.grid_size = max(4, size)
        self.viewport().update()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        new_zoom = self.zoom_level * factor
        if 0.05 <= new_zoom <= 32.0:
            self.zoom_level = new_zoom
            self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            self.is_panning = True
            self.pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        elif event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(scene_pos, self.transform())
            if isinstance(item, VanishingPointHandleItem):
                super().mousePressEvent(event)
                return

            self.is_drawing = True
            self.draw_start = scene_pos
            self.current_path = QPainterPath()
            self.current_path.moveTo(self.draw_start)

        super().mousePressEvent(event)

    def snap_point_to_perspective(self, pos: QPointF, start: QPointF) -> QPointF:
        """Snap pos to the nearest active Vanishing Point ray line passing through start."""
        if self.perspective_mode == "Off" or not self.vp_handles:
            return pos

        mode = self.perspective_mode
        active_names = []
        if mode == "1-Point Perspective":
            active_names = ["VP1"]
        elif mode == "2-Point Perspective":
            active_names = ["VP1", "VP2"]
        elif mode == "3-Point Perspective":
            active_names = ["VP1", "VP2", "VP3"]
        elif mode == "4-Point Perspective (Curvilinear)":
            active_names = ["VP1", "VP2", "VP3", "VP4"]
        elif mode == "5-Point Perspective (Fisheye Lens)":
            active_names = ["VP1", "VP2", "VP3", "VP4", "VP5"]
        elif mode == "6-Point Perspective (360° Spherical)":
            active_names = ["VP1", "VP2", "VP3", "VP4", "VP5", "VP6"]

        active_vps = []
        for name in active_names:
            if name in self.vp_handles and self.vp_handles[name].isVisible():
                active_vps.append(self.vp_handles[name].scenePos())

        if not active_vps:
            return pos

        stroke_dx = pos.x() - start.x()
        stroke_dy = pos.y() - start.y()
        stroke_len = math.hypot(stroke_dx, stroke_dy)
        if stroke_len < 2.0:
            return pos

        u_stroke_x = stroke_dx / stroke_len
        u_stroke_y = stroke_dy / stroke_len

        best_vp = None
        best_dot = -1.0

        for vp_pos in active_vps:
            ray_dx = start.x() - vp_pos.x()
            ray_dy = start.y() - vp_pos.y()
            ray_len = math.hypot(ray_dx, ray_dy)
            if ray_len < 0.001:
                continue

            u_ray_x = ray_dx / ray_len
            u_ray_y = ray_dy / ray_len

            abs_dot = abs(u_stroke_x * u_ray_x + u_stroke_y * u_ray_y)
            if abs_dot > best_dot:
                best_dot = abs_dot
                best_vp = (vp_pos, u_ray_x, u_ray_y)

        if best_vp is not None and best_dot > 0.3:
            vp_pos, u_ray_x, u_ray_y = best_vp
            rel_x = pos.x() - vp_pos.x()
            rel_y = pos.y() - vp_pos.y()
            proj_dist = rel_x * u_ray_x + rel_y * u_ray_y
            snapped_x = vp_pos.x() + proj_dist * u_ray_x
            snapped_y = vp_pos.y() + proj_dist * u_ray_y
            return QPointF(snapped_x, snapped_y)

        return pos

    def _find_editor(self):
        curr = self.parent()
        while curr is not None and not hasattr(curr, "stack"):
            curr = curr.parent()
        return curr

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_O and not event.isAutoRepeat():
            self.is_o_held = True
            self.show_hud_toast("💧 Opacity Adjust Mode: Drag Left-Click Horizontally to Change Layer Opacity")
            return
        elif event.key() == Qt.Key_B and not event.isAutoRepeat():
            self.is_b_held = True
            self.show_hud_toast("🖌 Brush Size Adjust Mode: Drag Left-Click Horizontally to Change Brush Radius")
            return
        elif event.key() == Qt.Key_T and not event.isAutoRepeat():
            self.is_t_held = True
            self.show_hud_toast("🔤 Text Font Size Mode: Drag Left-Click Horizontally to Change Text Font Size")
            return
        elif event.key() == Qt.Key_M and not event.isAutoRepeat():
            self.value_check_mode = not self.value_check_mode
            status = "ON (Monochrome Contrast Preview)" if self.value_check_mode else "OFF"
            self.show_hud_toast(f"🌗 Value Check Mode: {status}")
            curr = self._find_editor()
            if curr:
                curr.update_composited_view()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_O and not event.isAutoRepeat():
            self.is_o_held = False
            return
        elif event.key() == Qt.Key_B and not event.isAutoRepeat():
            self.is_b_held = False
            return
        elif event.key() == Qt.Key_T and not event.isAutoRepeat():
            self.is_t_held = False
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_o_held:
            curr = self._find_editor()
            if curr and curr.stack.active_layer:
                self.is_adjusting_opacity = True
                self.opacity_drag_start = event.position()
                self.initial_layer_opacity = curr.stack.active_layer.opacity
                return

        if event.button() == Qt.LeftButton and self.is_b_held:
            curr = self._find_editor()
            if curr:
                self.is_adjusting_brush_size = True
                self.brush_size_drag_start = event.position()
                self.initial_brush_size = getattr(curr, "brush_size", 18)
                return

        if event.button() == Qt.LeftButton and self.is_t_held:
            curr = self._find_editor()
            if curr:
                self.is_adjusting_text_size = True
                self.text_size_drag_start = event.position()
                self.initial_font_size = getattr(curr, "font_size", 24)
                return

        # â”€â”€ Golden Ratio & Rule of Thirds Overlay interaction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if event.button() == Qt.LeftButton and self.show_golden_ratio_overlay:
            scene_pos = self.mapToScene(event.pos())
            pix_rect = self.pixmap_item.boundingRect()
            img_w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
            img_h = pix_rect.height() if not pix_rect.isEmpty() else 720.0

            if self.golden_overlay_constrained:
                dx = scene_pos.x() - self.golden_overlay_pos.x()
                dy = scene_pos.y() - self.golden_overlay_pos.y()
                dist_from_focal = (dx * dx + dy * dy) ** 0.5
                # Click near focal point or alt-click to drag focal point
                if dist_from_focal < 120.0 or (event.modifiers() & Qt.AltModifier):
                    self._golden_drag_mode = "move"
                    self._golden_drag_origin = scene_pos
                    self._golden_drag_start_pos = QPointF(self.golden_overlay_pos)
                    return
            else:
                dx = scene_pos.x() - self.golden_overlay_pos.x()
                dy = scene_pos.y() - self.golden_overlay_pos.y()
                base = img_w * self.golden_overlay_scale
                ring_r = base * 0.07
                dist_from_centre = (dx * dx + dy * dy) ** 0.5
                if abs(dist_from_centre - ring_r) < ring_r * 0.5:   # near rotation ring
                    self._golden_drag_mode = "rotate"
                    self._golden_drag_origin = scene_pos
                    self._golden_drag_start_rot = self.golden_overlay_rot
                    return
                elif dist_from_centre < ring_r * 3.0:               # near centre â†’ move
                    self._golden_drag_mode = "move"
                    self._golden_drag_origin = scene_pos
                    self._golden_drag_start_pos = QPointF(self.golden_overlay_pos)
                    return


        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier):
            self.is_panning = True
            self.pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        elif event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            item = self.scene.itemAt(scene_pos, self.transform())
            if isinstance(item, VanishingPointHandleItem):
                super().mousePressEvent(event)
                return

            self.is_drawing = True
            self.draw_start = scene_pos
            self.current_path = QPainterPath()
            self.current_path.moveTo(self.draw_start)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_adjusting_opacity:
            delta_x = (event.position().x() - self.opacity_drag_start.x()) / 250.0
            new_opacity = max(0.0, min(1.0, self.initial_layer_opacity + delta_x))
            curr = self._find_editor()
            if curr and curr.stack.active_layer:
                curr.stack.active_layer.opacity = new_opacity
                curr.update_composited_view()
                curr.update_layer_list_ui()
                self.show_hud_toast(f"💧 Active Layer Opacity: {int(new_opacity * 100)}% (Hold O + Drag)")
            return

        if self.is_adjusting_brush_size:
            delta_x = (event.position().x() - self.brush_size_drag_start.x()) / 1.5
            new_size = max(1, min(500, int(self.initial_brush_size + delta_x)))
            curr = self._find_editor()
            if curr:
                curr._change_brush_size(new_size)
                if hasattr(curr, "size_spin"):
                    curr.size_spin.setValue(new_size)
                self.show_hud_toast(f"🖌 Brush Size: {new_size} px (Hold B + Drag)")
            return

        if self.is_adjusting_text_size:
            delta_x = (event.position().x() - self.text_size_drag_start.x()) / 2.0
            new_font_size = max(6, min(280, int(self.initial_font_size + delta_x)))
            curr = self._find_editor()
            if curr:
                curr.font_size = new_font_size
                if hasattr(curr, "font_size_spin"):
                    curr.font_size_spin.setValue(new_font_size)
                self.show_hud_toast(f"🔤 Text Font Size: {new_font_size} pt (Hold T + Drag)")
            return

        # â”€â”€ Golden Ratio & Rule of Thirds Overlay drag / rotate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self._golden_drag_mode == "move" and self._golden_drag_origin is not None:
            scene_pos = self.mapToScene(event.pos())
            delta = scene_pos - self._golden_drag_origin
            new_pos = self._golden_drag_start_pos + delta
            if self.golden_overlay_constrained:
                pix_rect = self.pixmap_item.boundingRect()
                img_w = pix_rect.width() if not pix_rect.isEmpty() else 1280.0
                img_h = pix_rect.height() if not pix_rect.isEmpty() else 720.0
                new_pos.setX(max(0.0, min(img_w, new_pos.x())))
                new_pos.setY(max(0.0, min(img_h, new_pos.y())))
                self.show_hud_toast(f"🎯 Composition Focal Target: ({int(new_pos.x())}, {int(new_pos.y())})")
            self.golden_overlay_pos = new_pos
            self.viewport().update()
            return


        if self._golden_drag_mode == "rotate" and self._golden_drag_origin is not None:
            import math as _math
            scene_pos = self.mapToScene(event.pos())
            cx, cy = self.golden_overlay_pos.x(), self.golden_overlay_pos.y()
            a0 = _math.degrees(_math.atan2(self._golden_drag_origin.y() - cy, self._golden_drag_origin.x() - cx))
            a1 = _math.degrees(_math.atan2(scene_pos.y() - cy, scene_pos.x() - cx))
            self.golden_overlay_rot = (self._golden_drag_start_rot + (a1 - a0)) % 360.0
            self.viewport().update()
            self.show_hud_toast(f"✨ Golden Overlay Rotation: {self.golden_overlay_rot:.1f}°")
            return

        if self.is_panning:
            delta = event.position() - self.pan_start
            self.pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return

        scene_pos = self.mapToScene(event.pos())
        pixmap = self.pixmap_item.pixmap()
        if not pixmap.isNull() and 0 <= scene_pos.x() < pixmap.width() and 0 <= scene_pos.y() < pixmap.height():
            image = pixmap.toImage()
            color = image.pixelColor(int(scene_pos.x()), int(scene_pos.y()))
            self.color_hovered.emit(int(scene_pos.x()), int(scene_pos.y()), color)

        if self.is_drawing:
            if self.snap_to_grid and self.grid_size > 0:
                snapped_x = round(scene_pos.x() / self.grid_size) * self.grid_size
                snapped_y = round(scene_pos.y() / self.grid_size) * self.grid_size
                scene_pos = QPointF(snapped_x, snapped_y)

            if self.snap_to_perspective:
                scene_pos = self.snap_point_to_perspective(scene_pos, self.draw_start)

            self.current_path.lineTo(scene_pos)
            self.selection_item.setPath(self.current_path)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.is_adjusting_opacity:
            self.is_adjusting_opacity = False
            curr = self._find_editor()
            if curr:
                curr.stack.save_snapshot()
                curr.mark_dirty()
            return

        if self.is_adjusting_brush_size:
            self.is_adjusting_brush_size = False
            return

        if self.is_adjusting_text_size:
            self.is_adjusting_text_size = False
            return

        # â”€â”€ Golden Ratio Overlay release â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self._golden_drag_mode != "none":
            self._golden_drag_mode = "none"
            self._golden_drag_origin = None
            return

        if self.is_panning:
            self.is_panning = False
            self.setCursor(Qt.ArrowCursor)
            return
        elif self.is_drawing:
            self.is_drawing = False
            draw_end = self.mapToScene(event.pos())
            if self.snap_to_grid and self.grid_size > 0:
                snapped_x = round(draw_end.x() / self.grid_size) * self.grid_size
                snapped_y = round(draw_end.y() / self.grid_size) * self.grid_size
                draw_end = QPointF(snapped_x, snapped_y)
            if self.snap_to_perspective:
                draw_end = self.snap_point_to_perspective(draw_end, self.draw_start)
            self.draw_stroke_finished.emit(QPainterPath(self.current_path), self.draw_start, draw_end, "brush")
        super().mouseReleaseEvent(event)
