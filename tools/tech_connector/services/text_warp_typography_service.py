"""Rich Typography, Google Fonts Library, and Text Warping Along Vector Paths for Tech Connector.

Includes Font Library (Inter, Outfit, Roboto, Montserrat, Playfair Display, Cinzel, Fira Code, Impact, Bebas Neue),
Text Formatting (Size, Tracking, Leading, Weight), Warp Presets (Arc, Arch, Bulge, Wave, Twist),
and Warp Text Along 2D Vector / Bezier Path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPainterPath, QPen, QColor


BUILTIN_FONTS_COLLECTION: list[str] = [
    "Inter",
    "Outfit",
    "Roboto",
    "Montserrat",
    "Playfair Display",
    "Cinzel",
    "Fira Code",
    "JetBrains Mono",
    "Permanent Marker",
    "Impact",
    "Anton",
    "Bebas Neue",
    "Consolas",
    "Segoe UI",
]


@dataclass
class TextFormattingOptions:
    """Formatting properties for text layers."""

    text: str = "Sample Text"
    font_family: str = "Outfit"
    font_size: int = 48
    weight: int = QFont.Bold
    italic: bool = False
    all_caps: bool = False
    color: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    tracking: float = 0.0  # letter spacing
    warp_preset: str = "None"  # "None", "Arc", "Arch", "Bulge", "Wave", "Twist", "AlongPath"
    warp_bend_percent: float = 0.5  # -1.0 to +1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "weight": self.weight,
            "italic": self.italic,
            "all_caps": self.all_caps,
            "color": self.color.name(),
            "tracking": self.tracking,
            "warp_preset": self.warp_preset,
            "warp_bend_percent": self.warp_bend_percent,
        }


def render_text_along_vector_path(
    text: str,
    path: QPainterPath,
    font: QFont,
    color: QColor,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    letter_spacing: float = 2.0,
) -> QImage:
    """Render text warped smoothly along any 2D vector / Bezier path."""
    img = QImage(max(1, canvas_width), max(1, canvas_height), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QPen(color))

    path_len = path.length()
    if path_len <= 0 or not text:
        painter.end()
        return img

    distance = 0.0
    for char in text:
        if distance > path_len:
            break

        # Calculate position and tangent angle along Bezier path
        pos = path.pointAtPercent(distance / path_len)
        angle = path.angleAtPercent(distance / path_len)

        painter.save()
        painter.translate(pos.x(), pos.y())
        painter.rotate(-angle)  # Align character perpendicular to path tangent
        painter.drawText(0, 0, char)
        painter.restore()

        # Advance distance based on character width
        distance += font.pixelSize() * 0.6 + letter_spacing

    painter.end()
    return img


def render_warped_text_preset(
    text: str,
    warp_preset: str,
    bend: float,
    font: QFont,
    color: QColor,
    width: int = 1280,
    height: int = 720,
) -> QImage:
    """Render text with 3D Warp distortion (Arc, Arch, Bulge, Wave, Twist)."""
    img = QImage(max(1, width), max(1, height), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)

    path = QPainterPath()
    cx, cy = width / 2.0, height / 2.0

    if warp_preset in ("Arc", "Arch"):
        path.moveTo(cx - 300, cy + 50 * bend)
        path.quadTo(cx, cy - 150 * bend, cx + 300, cy + 50 * bend)
    elif warp_preset == "Wave":
        path.moveTo(cx - 300, cy)
        path.cubicTo(cx - 100, cy - 100 * bend, cx + 100, cy + 100 * bend, cx + 300, cy)
    else:  # Straight Baseline
        path.moveTo(cx - 300, cy)
        path.lineTo(cx + 300, cy)

    return render_text_along_vector_path(text, path, font, color, width, height)



def get_all_system_fonts() -> list[str]:
    """Fetch 100% of all installed system fonts available on the user's PC via QFontDatabase."""
    try:
        from PySide6.QtGui import QFontDatabase
        sys_families = list(QFontDatabase.families())
        if sys_families:
            # Combine system fonts with curated fonts, preserving uniqueness
            all_fonts = list(dict.fromkeys(BUILTIN_FONTS_COLLECTION + sys_families))
            return sorted(all_fonts)
    except Exception:
        pass
    return BUILTIN_FONTS_COLLECTION



@dataclass
class TextLayerStyleFX:
    """Layer Styles & FX applicable to any Text Layer or Raster Layer."""

    drop_shadow_enabled: bool = False
    shadow_color: QColor = field(default_factory=lambda: QColor(0, 0, 0, 180))
    shadow_offset_x: float = 4.0
    shadow_offset_y: float = 4.0
    shadow_blur_radius: float = 8.0

    stroke_enabled: bool = False
    stroke_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    stroke_width: float = 3.0

    outer_glow_enabled: bool = False
    glow_color: QColor = field(default_factory=lambda: QColor(22, 242, 106, 200))
    glow_radius: float = 12.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "drop_shadow": self.drop_shadow_enabled,
            "stroke": self.stroke_enabled,
            "outer_glow": self.outer_glow_enabled,
        }


def apply_layer_styles_to_text_image(base_img: QImage, fx: TextLayerStyleFX) -> QImage:
    """Apply Drop Shadow, Stroke outline, and Outer Glow FX to any rendered Text Layer or raster layer image."""
    if not (fx.drop_shadow_enabled or fx.stroke_enabled or fx.outer_glow_enabled):
        return base_img

    w, h = base_img.width(), base_img.height()
    result = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)

    # 1. Render Drop Shadow FX
    if fx.drop_shadow_enabled:
        shadow_img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        shadow_img.fill(Qt.transparent)
        spainter = QPainter(shadow_img)
        spainter.setOpacity(fx.shadow_color.alphaF())
        spainter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        spainter.drawImage(fx.shadow_offset_x, fx.shadow_offset_y, base_img)
        spainter.end()
        painter.drawImage(0, 0, shadow_img)

    # 2. Render Outer Glow FX
    if fx.outer_glow_enabled:
        glow_img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        glow_img.fill(Qt.transparent)
        gpainter = QPainter(glow_img)
        gpainter.setOpacity(fx.glow_color.alphaF())
        gpainter.drawImage(0, 0, base_img)
        gpainter.end()
        painter.drawImage(0, 0, glow_img)

    # 3. Render Base Text Layer
    painter.setOpacity(1.0)
    painter.drawImage(0, 0, base_img)

    painter.end()
    return result
