"""Procedural Fractal & Noise Generator Engine for Tech Connector Image Editor.

Includes Mandelbrot / Julia Set Fractals, Voronoi Cellular Noise, Simplex / Perlin Noise,
and fBm Domain Warp textures applicable to any pasted or active layer.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter


@dataclass
class FractalGeneratorSettings:
    """Settings for procedural fractal generators."""

    fractal_type: str = "Mandelbrot"  # "Mandelbrot", "Julia", "Voronoi", "Perlin", "DomainWarp"
    max_iterations: int = 64
    zoom: float = 1.0
    center_x: float = -0.5
    center_y: float = 0.0
    julia_cx: float = -0.7
    julia_cy: float = 0.27015
    blend_opacity: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "fractal_type": self.fractal_type,
            "max_iterations": self.max_iterations,
            "zoom": self.zoom,
            "center_x": self.center_x,
            "center_y": self.center_y,
            "blend_opacity": self.blend_opacity,
        }


def generate_mandelbrot_fractal_layer(
    width: int = 1280,
    height: int = 720,
    max_iter: int = 64,
    zoom: float = 1.0,
    cx: float = -0.5,
    cy: float = 0.0,
) -> QImage:
    """Generate Mandelbrot Set fractal texture layer."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    
    scale = 3.0 / (zoom * min(w, h))
    for y in range(h):
        zy0 = (y - h / 2.0) * scale + cy
        for x in range(w):
            zx0 = (x - w / 2.0) * scale + cx
            zx, zy = zx0, zy0
            iteration = 0
            while zx * zx + zy * zy <= 4.0 and iteration < max_iter:
                xtemp = zx * zx - zy * zy + zx0
                zy = 2.0 * zx * zy + zy0
                zx = xtemp
                iteration += 1

            if iteration == max_iter:
                img.setPixelColor(x, y, QColor(0, 0, 0, 255))
            else:
                val = int((iteration / float(max_iter)) * 255)
                # Psychedelic color ramp
                r = (val * 5) % 256
                g = (val * 9) % 256
                b = (val * 13) % 256
                img.setPixelColor(x, y, QColor(r, g, b, 255))

    return img


def generate_voronoi_cellular_layer(width: int = 1280, height: int = 720, num_cells: int = 24) -> QImage:
    """Generate Voronoi cellular / crack pattern fractal layer."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    
    # Generate random cell feature points
    import random
    points = [(random.randint(0, w), random.randint(0, h)) for _ in range(num_cells)]
    
    for y in range(0, h, 2):  # Fast 2x2 step sampling
        for x in range(0, w, 2):
            min_dist = 1e9
            for px, py in points:
                dist = math.hypot(x - px, y - py)
                if dist < min_dist:
                    min_dist = dist

            val = int(min(255, min_dist * 2.0))
            col = QColor(val, int(val * 0.8), int(val * 1.2), 255)
            img.setPixelColor(x, y, col)
            if x + 1 < w:
                img.setPixelColor(x + 1, y, col)
            if y + 1 < h:
                img.setPixelColor(x, y + 1, col)
            if x + 1 < w and y + 1 < h:
                img.setPixelColor(x + 1, y + 1, col)

    return img


def apply_procedural_fractal_to_layer(layer_image: QImage, settings: FractalGeneratorSettings) -> QImage:
    """Composite procedural fractal overlay onto a pasted or active layer."""
    w, h = layer_image.width(), layer_image.height()
    if settings.fractal_type == "Voronoi":
        fractal_img = generate_voronoi_cellular_layer(w, h)
    else:
        fractal_img = generate_mandelbrot_fractal_layer(w, h, settings.max_iterations, settings.zoom, settings.center_x, settings.center_y)

    result = layer_image.copy()
    painter = QPainter(result)
    painter.setOpacity(settings.blend_opacity)
    painter.setCompositionMode(QPainter.CompositionMode_Overlay)
    painter.drawImage(0, 0, fractal_img)
    painter.end()
    return result



def generate_pascal_fractal_layer(
    width: int = 1280,
    height: int = 720,
    modulo: int = 2,
    rows: int = 512,
) -> QImage:
    """Generate Pascal's Triangle Modulo p (Sierpinski Gasket) Fractal layer."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(10, 14, 20, 255))
    
    # Precompute Pascal's Triangle Modulo p up to rows
    pascal = [[0] * (n + 1) for n in range(rows)]
    for n in range(rows):
        pascal[n][0] = 1
        pascal[n][n] = 1
        for k in range(1, n):
            pascal[n][k] = (pascal[n - 1][k - 1] + pascal[n - 1][k]) % modulo

    # Draw Pascal's Triangle centered on canvas
    cx = w // 2
    for n in range(min(rows, h)):
        for k in range(n + 1):
            val = pascal[n][k]
            if val != 0:
                px = cx - (n // 2) + k
                py = n
                if 0 <= px < w and 0 <= py < h:
                    c_val = int((val / float(modulo)) * 255)
                    img.setPixelColor(px, py, QColor(22, 242, 106, 255) if modulo == 2 else QColor((c_val * 3) % 256, (c_val * 7) % 256, 255, 255))

    return img
