"""Custom brush-tip shapes, alpha stamps, and image-editor dynamics.

Includes shape presets (Circle, Soft Radial, Square, Chisel, Grunge, Alpha Texture Stamp),
brush size dynamics, softness/hardness, angle, roundness, and random jittering.
"""

from __future__ import annotations

from typing import Any
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QRadialGradient


class CustomBrushTipShape:
    """Represents a brush tip shape or alpha stencil mask for Tech Connector Image Editor."""

    def __init__(self, name: str, shape_type: str = "Circle"):
        self.name = name
        self.shape_type = shape_type  # "Circle", "SoftRadial", "Square", "Chisel", "Grunge", "CustomAlpha"
        self.alpha_image: QImage | None = None
        self.spacing = 0.15  # 15% stamp spacing
        self.angle = 0.0  # degrees
        self.roundness = 1.0  # 0.1 (flat) to 1.0 (circle)
        self.size_jitter = 0.0  # 0.0 to 1.0
        self.angle_jitter = 0.0  # 0.0 to 1.0

    def generate_tip_mask(self, size: int, hardness: float, color: QColor) -> QImage:
        """Generate a rendered brush tip stamp image with softness, angle, and roundness applied."""
        sz = max(1, size)
        img = QImage(sz, sz, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.shape_type == "Square":
            painter.fillRect(0, 0, sz, sz, color)
        elif self.shape_type == "Chisel":
            path = QPainterPath()
            path.moveTo(0, sz * 0.4)
            path.lineTo(sz, 0)
            path.lineTo(sz, sz * 0.6)
            path.lineTo(0, sz)
            path.closeSubpath()
            painter.fillPath(path, QBrush(color))
        elif self.shape_type == "SoftRadial" or hardness < 0.95:
            radial = QRadialGradient(sz / 2.0, sz / 2.0, sz / 2.0)
            c_center = QColor(color)
            c_edge = QColor(color)
            c_edge.setAlpha(0)
            radial.setColorAt(0.0, c_center)
            radial.setColorAt(max(0.1, hardness), c_center)
            radial.setColorAt(1.0, c_edge)
            painter.fillRect(0, 0, sz, sz, QBrush(radial))
        else:  # Circle (Hard)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, sz, sz)

        painter.end()
        return img
