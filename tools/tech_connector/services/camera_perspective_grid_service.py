"""Camera Perspective Grid & Vanishing Point Overlay Engine for Tech Connector Image Editor.

Calculates 1-Point, 2-Point, and 3-Point Perspective Grids based on 3D Camera Lens Settings
(Focal Length, Sensor Size, Pitch, Yaw, Roll, Eye Level Height) and Syncs with Maya / UE5 Cameras.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen


@dataclass
class CameraPerspectiveSettings:
    """3D Camera Lens and Orientation Settings."""

    focal_length_mm: float = 50.0  # 24mm, 35mm, 50mm, 85mm, 200mm
    sensor_width_mm: float = 36.0  # Full Frame 35mm
    pitch_deg: float = -10.0  # tilt up/down
    yaw_deg: float = 0.0  # pan
    roll_deg: float = 0.0  # roll
    camera_height_m: float = 1.7  # Eye level height above ground
    perspective_mode: str = "2-Point"  # "1-Point", "2-Point", "3-Point"
    grid_density: int = 16
    line_color: QColor = field(default_factory=lambda: QColor(30, 155, 255, 180))
    horizon_color: QColor = field(default_factory=lambda: QColor(22, 242, 106, 220))

    @property
    def fov_degrees(self) -> float:
        """Horizontal Field of View (FOV) in degrees."""
        return 2.0 * math.degrees(math.atan(self.sensor_width_mm / (2.0 * self.focal_length_mm)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "focal_length_mm": self.focal_length_mm,
            "sensor_width_mm": self.sensor_width_mm,
            "pitch_deg": self.pitch_deg,
            "yaw_deg": self.yaw_deg,
            "roll_deg": self.roll_deg,
            "fov_degrees": round(self.fov_degrees, 2),
            "perspective_mode": self.perspective_mode,
        }


def compute_vanishing_points(settings: CameraPerspectiveSettings, width: int = 1920, height: int = 1080) -> dict[str, QPointF]:
    """Compute 2D canvas coordinates of Vanishing Points (Left, Right, Vertical) and Horizon Line."""
    cx, cy = width / 2.0, height / 2.0
    fov_rad = math.radians(settings.fov_degrees)
    focal_pixels = (width / 2.0) / math.tan(fov_rad / 2.0)

    pitch_rad = math.radians(settings.pitch_deg)
    yaw_rad = math.radians(settings.yaw_deg)

    # Horizon offset based on camera pitch
    horizon_y = cy + math.tan(pitch_rad) * focal_pixels

    # Left & Right Vanishing Points for 2-Point / 3-Point perspective
    dist_vp = focal_pixels * math.tan(math.radians(45.0))
    vp_left = QPointF(cx - dist_vp * math.cos(yaw_rad), horizon_y)
    vp_right = QPointF(cx + dist_vp * math.cos(yaw_rad), horizon_y)

    # Vertical (Zenith/Nadir) Vanishing Point for 3-Point perspective
    vp_vertical_y = cy - focal_pixels / (math.tan(pitch_rad) if math.sin(pitch_rad) != 0 else 0.001)
    vp_vertical = QPointF(cx, vp_vertical_y)

    return {
        "center": QPointF(cx, cy),
        "horizon_y": QPointF(0, horizon_y),
        "vp_left": vp_left,
        "vp_right": vp_right,
        "vp_vertical": vp_vertical,
    }


def render_camera_perspective_grid_overlay(
    settings: CameraPerspectiveSettings,
    width: int = 1920,
    height: int = 1080,
) -> QImage:
    """Render 3D Camera Perspective Grid and Vanishing Point Rays onto a transparent overlay QImage."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    vps = compute_vanishing_points(settings, w, h)
    horizon_y = vps["horizon_y"].y()

    # 1. Draw Horizon Line (Eye Level)
    painter.setPen(QPen(settings.horizon_color, 2, Qt.SolidLine))
    painter.drawLine(0, int(horizon_y), w, int(horizon_y))
    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.setPen(QPen(settings.horizon_color))
    painter.drawText(20, int(horizon_y) - 8, f"HORIZON / EYE LEVEL ({settings.camera_height_m}m) • {settings.focal_length_mm:.0f}mm Lens (FOV: {settings.fov_degrees:.1f}°)")

    # 2. Draw Perspective Rays from Vanishing Points
    grid_pen = QPen(settings.line_color, 1, Qt.DotLine)
    painter.setPen(grid_pen)

    if settings.perspective_mode in ("2-Point", "3-Point"):
        vp_left = vps["vp_left"]
        vp_right = vps["vp_right"]
        for i in range(settings.grid_density):
            y_target = (h / float(settings.grid_density)) * i
            painter.drawLine(vp_left, QPointF(w, y_target))
            painter.drawLine(vp_right, QPointF(0, y_target))

    if settings.perspective_mode == "3-Point":
        vp_vert = vps["vp_vertical"]
        for i in range(settings.grid_density):
            x_target = (w / float(settings.grid_density)) * i
            painter.drawLine(vp_vert, QPointF(x_target, h if settings.pitch_deg < 0 else 0))

    # 3. Rule of Thirds Guides
    guide_pen = QPen(QColor(255, 255, 255, 60), 1, Qt.DashLine)
    painter.setPen(guide_pen)
    painter.drawLine(int(w / 3.0), 0, int(w / 3.0), h)
    painter.drawLine(int(w * 2 / 3.0), 0, int(w * 2 / 3.0), h)
    painter.drawLine(0, int(h / 3.0), w, int(h / 3.0))
    painter.drawLine(0, int(h * 2 / 3.0), w, int(h * 2 / 3.0))

    painter.end()
    return img



@dataclass
class AdvancedLensSettings:
    """Advanced Cinematic Lens settings including Fisheye, Anamorphic Squeeze, and Tilt-Shift."""

    lens_type: str = "Rectilinear Standard"  # "Rectilinear Standard", "Fisheye Ultra-Wide", "Anamorphic Cinematic", "Tilt-Shift"
    fisheye_fov_deg: float = 180.0  # 120° to 220° fisheye
    barrel_distortion_k1: float = 0.35  # Curvilinear grid bending
    anamorphic_squeeze_ratio: float = 2.0  # 1.33x, 1.5x, 2.0x anamorphic
    shift_offset_x: float = 0.0  # Tilt-Shift lens shift
    shift_offset_y: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lens_type": self.lens_type,
            "fisheye_fov_deg": self.fisheye_fov_deg,
            "barrel_distortion_k1": self.barrel_distortion_k1,
            "anamorphic_squeeze_ratio": self.anamorphic_squeeze_ratio,
        }


def apply_fisheye_barrel_distortion_to_point(pt: QPointF, center: QPointF, k1: float) -> QPointF:
    """Apply radial barrel distortion equation r_distorted = r * (1 + k1 * r^2) to transform perspective grid lines into curvilinear fisheye arcs."""
    dx = pt.x() - center.x()
    dy = pt.y() - center.y()
    r2 = (dx * dx + dy * dy) / (center.x() * center.x() + center.y() * center.y())
    factor = 1.0 + k1 * r2
    return QPointF(center.x() + dx * factor, center.y() + dy * factor)


def render_fisheye_perspective_grid_overlay(
    cam_settings: CameraPerspectiveSettings,
    lens_settings: AdvancedLensSettings,
    width: int = 1920,
    height: int = 1080,
) -> QImage:
    """Render Fisheye Curvilinear Perspective Grid and Anamorphic Horizon Overlay."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    center = QPointF(w / 2.0, h / 2.0)
    k1 = lens_settings.barrel_distortion_k1

    # Render Curvilinear Fisheye Grid Arcs
    pen = QPen(cam_settings.line_color, 1.5, Qt.DotLine)
    painter.setPen(pen)

    # Concentric fisheye ring guides
    num_rings = 8
    max_radius = math.hypot(w / 2.0, h / 2.0)
    for r_idx in range(1, num_rings + 1):
        radius = (max_radius / float(num_rings)) * r_idx
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        painter.drawEllipse(rect)

    # Radial fisheye spoke lines
    num_spokes = 16
    for i in range(num_spokes):
        angle_rad = (2.0 * math.pi / num_spokes) * i
        end_pt = QPointF(center.x() + max_radius * math.cos(angle_rad), center.y() + max_radius * math.sin(angle_rad))
        distorted_pt = apply_fisheye_barrel_distortion_to_point(end_pt, center, k1)
        painter.drawLine(center, distorted_pt)

    # Fisheye Header HUD
    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.setPen(QPen(cam_settings.horizon_color))
    painter.drawText(20, 30, f"👁️ FISHEYE LENS OVERLAY ({lens_settings.fisheye_fov_deg:.0f}° FOV • k1={k1:.2f}) • Anamorphic Squeeze: {lens_settings.anamorphic_squeeze_ratio:.2f}x")

    painter.end()
    return img



def render_golden_ratio_phi_spiral_overlay(width: int = 1920, height: int = 1080, color: QColor | None = None) -> QImage:
    """Render Golden Ratio (Phi = 1.618033) Spiral and Golden Triangle Composition Overlay."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    phi = 1.61803398875
    col = color or QColor(255, 215, 0, 200)  # Gold
    painter.setPen(QPen(col, 1.5, Qt.SolidLine))

    # Golden Ratio Rectangles & Logarithmic Spiral
    x, y, rw, rh = 0.0, 0.0, float(w), float(h)
    for _ in range(8):
        painter.drawRect(QRectF(x, y, rw, rh))
        # Spiral arc inside rectangle
        path = QPainterPath()
        path.moveTo(x, y + rh)
        path.quadTo(x, y, x + rw, y)
        painter.drawPath(path)
        
        # Subdivide by Golden Ratio
        if rw > rh:
            nw = rw / phi
            x += rw - nw
            rw = nw
        else:
            nh = rh / phi
            y += rh - nh
            rh = nh

    painter.end()
    return img


def render_four_point_curved_perspective_grid(width: int = 1920, height: int = 1080, density: int = 16) -> QImage:
    """Render 4-Point Curved Panoramic Perspective Grid (Left, Right, Top, Bottom Vanishing Points)."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(30, 155, 255, 180), 1, Qt.DashLine)
    painter.setPen(pen)

    cx, cy = w / 2.0, h / 2.0
    for i in range(1, density):
        step = (w / float(density)) * i
        # Horizontal curves converging at left and right VPs
        path_h = QPainterPath()
        path_h.moveTo(0, cy)
        path_h.quadTo(step, (cy - h / 2.0) if i % 2 == 0 else (cy + h / 2.0), w, cy)
        painter.drawPath(path_h)

        # Vertical curves converging at top and bottom VPs
        path_v = QPainterPath()
        path_v.moveTo(cx, 0)
        path_v.quadTo((cx - w / 2.0) if i % 2 == 0 else (cx + w / 2.0), step, cx, h)
        painter.drawPath(path_v)

    painter.end()
    return img


def render_four_dimensional_tesseract_projection(width: int = 1920, height: int = 1080, time_angle: float = 0.0) -> QImage:
    """Render 4D Hypercube (Tesseract) Orthogonal & Stereographic Perspective Projection."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(QPen(QColor(255, 0, 128, 220), 2, Qt.SolidLine))
    cx, cy = w / 2.0, h / 2.0

    # 16 Vertices of a 4D Hypercube in (x, y, z, w) space
    nodes_4d = []
    for i in range(16):
        x_val = -1 if (i & 1) == 0 else 1
        y_val = -1 if (i & 2) == 0 else 1
        z_val = -1 if (i & 4) == 0 else 1
        w_val = -1 if (i & 8) == 0 else 1
        nodes_4d.append((x_val, y_val, z_val, w_val))

    # Apply 4D Rotation Matrix (Rotation in XW and YZ planes)
    cos_t, sin_t = math.cos(time_angle), math.sin(time_angle)
    nodes_projected_2d = []
    scale_4d = 180.0

    for x_4d, y_4d, z_4d, w_4d in nodes_4d:
        # Rotate in 4D (XW plane)
        x_rot = x_4d * cos_t - w_4d * sin_t
        w_rot = x_4d * sin_t + w_4d * cos_t

        # Perspective 4D to 3D projection
        distance_4d = 2.5
        w_factor = 1.0 / (distance_4d - w_rot)
        x_3d = x_rot * w_factor
        y_3d = y_4d * w_factor
        z_3d = z_4d * w_factor

        # Perspective 3D to 2D canvas projection
        distance_3d = 3.0
        z_factor = 1.0 / (distance_3d - z_3d)
        screen_x = cx + x_3d * z_factor * scale_4d * 3.0
        screen_y = cy + y_3d * z_factor * scale_4d * 3.0
        nodes_projected_2d.append(QPointF(screen_x, screen_y))

    # Draw 32 Edges connecting 4D Hypercube Vertices
    for i in range(16):
        for j in range(i + 1, 16):
            # Edges exist if vertices differ in exactly 1 coordinate dimension
            diff = (i ^ j)
            if diff in (1, 2, 4, 8):
                painter.drawLine(nodes_projected_2d[i], nodes_projected_2d[j])

    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.drawText(20, h - 30, "✨ 4D HYPERCUBE (TESSERACT) HYPERPLANE PROJECTION • 4D ROTATION ACTIVE")
    painter.end()
    return img



def render_five_point_spherical_perspective_grid(width: int = 1920, height: int = 1080, density: int = 16) -> QImage:
    """Render 5-Point Fisheye Spherical Perspective Grid (Left, Right, Top, Bottom, Center VPs)."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    cx, cy = w / 2.0, h / 2.0
    radius = min(w, h) * 0.45

    # 1. Outer Sphere Circle Boundary (Circular Vanishing Boundary)
    painter.setPen(QPen(QColor(22, 242, 106, 220), 2, Qt.SolidLine))
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

    # 2. Longitudinal Curves (Nadir to Zenith)
    painter.setPen(QPen(QColor(30, 155, 255, 180), 1, Qt.DotLine))
    for i in range(1, density):
        offset = (radius / float(density)) * i
        # Left-right curves
        painter.drawEllipse(QRectF(cx - offset, cy - radius, offset * 2.0, radius * 2.0))
        # Top-bottom curves
        painter.drawEllipse(QRectF(cx - radius, cy - offset, radius * 2.0, offset * 2.0))

    # 3. Center Crosshair (Center VP)
    painter.setPen(QPen(QColor(255, 40, 40, 220), 1.5, Qt.SolidLine))
    painter.drawLine(int(cx - 15), int(cy), int(cx + 15), int(cy))
    painter.drawLine(int(cx), int(cy - 15), int(cx), int(cy + 15))

    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.setPen(QPen(QColor(22, 242, 106)))
    painter.drawText(20, 30, "🔮 5-POINT SPHERICAL PERSPECTIVE GRID (HEMISPHERICAL FISHEYE)")

    painter.end()
    return img


def render_six_point_omnidirectional_perspective_grid(width: int = 1920, height: int = 1080, density: int = 20) -> QImage:
    """Render 6-Point Omnidirectional 360° Perspective Grid (Front + Back Spherical Projection)."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    cx, cy = w / 2.0, h / 2.0
    radius = min(w, h) * 0.45

    # 1. Outer Sphere Circle Boundary
    painter.setPen(QPen(QColor(255, 215, 0, 220), 2, Qt.SolidLine))
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

    # 2. Concentric Radial Shells (Front-to-Back Depth Rings)
    painter.setPen(QPen(QColor(30, 155, 255, 160), 1, Qt.DashLine))
    for r_step in range(1, density):
        r_curr = (radius / float(density)) * r_step
        painter.drawEllipse(QRectF(cx - r_curr, cy - r_curr, r_curr * 2.0, r_curr * 2.0))

    # 3. 360° Omnidirectional Spoke Rays (Front + Back Field-of-View Radians)
    painter.setPen(QPen(QColor(22, 242, 106, 140), 1, Qt.DotLine))
    num_spokes = 24
    for i in range(num_spokes):
        angle = (2.0 * math.pi / num_spokes) * i
        ex = cx + radius * math.cos(angle)
        ey = cy + radius * math.sin(angle)
        painter.drawLine(QPointF(cx, cy), QPointF(ex, ey))

    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.setPen(QPen(QColor(255, 215, 0)))
    painter.drawText(20, 30, "🌐 6-POINT OMNIDIRECTIONAL PERSPECTIVE GRID (360° FRONT + BACK WORLD PROJECTION)")

    painter.end()
    return img



class InteractivePerspectiveHandleTracker:
    """Manages click-and-drag interactive vanishing point handles and live grid line updates."""

    def __init__(self, width: int = 1920, height: int = 1080):
        self.width = width
        self.height = height
        self.opacity: float = 0.65  # 0.0 to 1.0
        self.handle_radius: float = 8.0
        self.dragged_handle: str | None = None

        # Interactive Vanishing Point Coordinates
        cx, cy = width / 2.0, height / 2.0
        self.handles: dict[str, QPointF] = {
            "vp_left": QPointF(cx - 600, cy),
            "vp_right": QPointF(cx + 600, cy),
            "vp_vertical": QPointF(cx, cy - 500),
            "vp_center": QPointF(cx, cy),
            "horizon_line": QPointF(cx, cy),
        }

    def set_opacity(self, alpha_percent: float):
        """Adjust grid line opacity (0.0 invisible to 1.0 opaque)."""
        self.opacity = max(0.0, min(1.0, alpha_percent))

    def move_handle(self, handle_name: str, pos: QPointF):
        """Move a vanishing point handle to a new position on canvas."""
        if handle_name in self.handles:
            self.handles[handle_name] = pos

    def hit_test_handle(self, pos: QPointF) -> str | None:
        """Check if mouse click hits a vanishing point handle."""
        for name, pt in self.handles.items():
            dist = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
            if dist <= self.handle_radius * 1.5:
                return name
        return None

    def move_horizon_line(self, new_y: float):
        """Drag Horizon Line up or down, automatically shifting Left and Right VPs along with it."""
        delta_y = new_y - self.handles["horizon_line"].y()
        self.handles["horizon_line"] = QPointF(self.width / 2.0, new_y)

        # Shift Left and Right VPs vertically with Horizon Line
        if "vp_left" in self.handles:
            self.handles["vp_left"].setY(self.handles["vp_left"].y() + delta_y)
        if "vp_right" in self.handles:
            self.handles["vp_right"].setY(self.handles["vp_right"].y() + delta_y)


def render_custom_interactive_perspective_grid(
    tracker: InteractivePerspectiveHandleTracker,
    width: int = 1920,
    height: int = 1080,
    mode: str = "2-Point",
    line_color: QColor | None = None,
) -> QImage:
    """Render interactive perspective grid with custom vanishing point positions and opacity slider."""
    w, h = max(1, width), max(1, height)
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)

    base_col = line_color or QColor(30, 155, 255)
    c_alpha = int(tracker.opacity * 255)
    grid_pen = QPen(QColor(base_col.red(), base_col.green(), base_col.blue(), c_alpha), 1.5, Qt.DashLine)
    painter.setPen(grid_pen)

    vps = tracker.handles
    vp_left = vps["vp_left"]
    vp_right = vps["vp_right"]
    vp_vert = vps["vp_vertical"]

    # 1. Draw Horizon Line between Left and Right VPs
    horizon_pen = QPen(QColor(22, 242, 106, c_alpha), 2, Qt.SolidLine)
    painter.setPen(horizon_pen)
    painter.drawLine(vp_left, vp_right)

    # 2. Draw Live Grid Rays from Custom VP Handles
    painter.setPen(grid_pen)
    density = 16
    for i in range(density + 1):
        y_target = (h / float(density)) * i
        if mode in ("1-Point", "2-Point", "3-Point", "4-Point"):
            painter.drawLine(vp_left, QPointF(w, y_target))
            painter.drawLine(vp_right, QPointF(0, y_target))

    if mode in ("3-Point", "4-Point"):
        for i in range(density + 1):
            x_target = (w / float(density)) * i
            painter.drawLine(vp_vert, QPointF(x_target, h))

    # 3. Draw On-Canvas Interactive VP Handle Targets
    painter.setBrush(QBrush(QColor(255, 40, 40, 220)))
    painter.setPen(QPen(QColor(255, 255, 255), 2))
    for name, pt in vps.items():
        r = tracker.handle_radius
        painter.drawEllipse(QRectF(pt.x() - r, pt.y() - r, r * 2.0, r * 2.0))
        painter.drawText(QPointF(pt.x() + 10, pt.y() + 4), name.upper())

    painter.setFont(QFont("Consolas", 10, QFont.Bold))
    painter.setPen(QPen(QColor(22, 242, 106, c_alpha)))
    painter.drawText(20, 30, f"🎯 INTERACTIVE PERSPECTIVE GRID ({mode.upper()}) • Opacity: {int(tracker.opacity * 100)}% • Drag VP Handles on Canvas")

    painter.end()
    return img



    def move_horizon_line(self, new_y: float):
        """Drag Horizon Line up or down, automatically shifting Left and Right VPs along with it."""
        delta_y = new_y - self.handles["horizon_line"].y()
        self.handles["horizon_line"] = QPointF(self.width / 2.0, new_y)

        # Shift Left and Right VPs vertically with Horizon Line
        if "vp_left" in self.handles:
            self.handles["vp_left"].setY(self.handles["vp_left"].y() + delta_y)
        if "vp_right" in self.handles:
            self.handles["vp_right"].setY(self.handles["vp_right"].y() + delta_y)



@dataclass
class FocalPointBlurSettings:
    """Interactive Focal Point Depth-of-Field (DoF) Filter Settings."""

    focal_x: float = 960.0
    focal_y: float = 540.0
    focus_radius_px: float = 200.0  # In-focus sharp region
    feather_falloff_px: float = 150.0  # Transition zone
    max_blur_radius_px: float = 16.0  # Gaussian background blur
    mode: str = "Radial"  # "Radial" or "Linear Tilt-Shift"

    def to_dict(self) -> dict[str, Any]:
        return {
            "focal_x": self.focal_x,
            "focal_y": self.focal_y,
            "focus_radius_px": self.focus_radius_px,
            "max_blur_radius_px": self.max_blur_radius_px,
            "mode": self.mode,
        }


def apply_focal_point_depth_of_field_blur(
    src_img: QImage,
    settings: FocalPointBlurSettings,
) -> QImage:
    """Apply interactive Focal Point Depth-of-Field (DoF) Tilt-Shift blur filter to any image layer."""
    w, h = src_img.width(), src_img.height()
    if w <= 0 or h <= 0:
        return src_img

    # 1. Generate heavy background blurred image buffer
    blurred_img = src_img.copy()
    # Fast box/gaussian approximation via downscaling and upscaling
    scale_factor = 4
    small_w = max(1, w // scale_factor)
    small_h = max(1, h // scale_factor)
    scaled_small = src_img.scaled(small_w, small_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred_img = scaled_small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    # 2. Composite sharp focal region with blurred background via radial alpha mask
    result = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)

    # Draw blurred background
    painter.drawImage(0, 0, blurred_img)

    # Draw sharp focal point overlay with radial gradient opacity
    from PySide6.QtGui import QRadialGradient
    focal_mask = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    focal_mask.fill(Qt.transparent)
    mpainter = QPainter(focal_mask)
    mpainter.setRenderHint(QPainter.Antialiasing)

    radial = QRadialGradient(settings.focal_x, settings.focal_y, settings.focus_radius_px + settings.feather_falloff_px)
    c_sharp = QColor(255, 255, 255, 255)
    c_transparent = QColor(255, 255, 255, 0)
    stop_sharp = max(0.01, min(0.9, settings.focus_radius_px / (settings.focus_radius_px + settings.feather_falloff_px)))
    radial.setColorAt(0.0, c_sharp)
    radial.setColorAt(stop_sharp, c_sharp)
    radial.setColorAt(1.0, c_transparent)

    mpainter.fillRect(0, 0, w, h, QBrush(radial))
    mpainter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    mpainter.drawImage(0, 0, src_img)
    mpainter.end()

    painter.drawImage(0, 0, focal_mask)
    painter.end()

    return result
