"""Perspective guide math shared by 2D composition tools and the 3D viewer."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass(frozen=True)
class PerspectiveGuideSolveResult:
    mode: str
    projection_model: str
    camera_settings: dict[str, Any] = field(default_factory=dict)
    projection_settings: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "projection_model": self.projection_model,
            "camera_settings": dict(self.camera_settings),
            "projection_settings": dict(self.projection_settings),
            "confidence": float(self.confidence),
            "notes": list(self.notes),
        }


def solve_perspective_guides(
    mode: str,
    points: dict[str, tuple[float, float]],
    width: float,
    height: float,
    *,
    sensor_width_mm: float = 36.0,
    sensor_height_mm: float = 24.0,
) -> PerspectiveGuideSolveResult:
    """Estimate camera/projection settings from Tech Connector perspective guides.

    The result is intentionally explicit about nonlinear modes. A 4-6 point guide
    can describe a useful shot projection, but it is not always a single standard
    rectilinear camera.
    """

    mode_label = str(mode or "Off")
    w = max(1.0, float(width or 1.0))
    h = max(1.0, float(height or 1.0))
    cx, cy = _point(points, "VP5", (w * 0.5, h * 0.5))
    if "Point" not in mode_label or mode_label == "Off":
        return PerspectiveGuideSolveResult(mode_label, "off", confidence=0.0, notes=["No active perspective guide mode."])

    if mode_label.startswith(("1-Point", "2-Point", "3-Point")):
        return _solve_rectilinear(mode_label, points, w, h, cx, cy, sensor_width_mm, sensor_height_mm)
    return _solve_curvilinear(mode_label, points, w, h, cx, cy, sensor_width_mm, sensor_height_mm)


def _solve_rectilinear(
    mode: str,
    points: dict[str, tuple[float, float]],
    width: float,
    height: float,
    cx: float,
    cy: float,
    sensor_width_mm: float,
    sensor_height_mm: float,
) -> PerspectiveGuideSolveResult:
    notes: list[str] = []
    vp1 = _point(points, "VP1", (width * 0.5, height * 0.45))
    vp2 = _point(points, "VP2", (width * 1.25, height * 0.45))
    vp3 = _point(points, "VP3", (width * 0.5, -height * 0.75))

    focal_px = 0.0
    if mode.startswith(("2-Point", "3-Point")):
        a = (vp1[0] - cx, vp1[1] - cy)
        b = (vp2[0] - cx, vp2[1] - cy)
        f2 = -(a[0] * b[0] + a[1] * b[1])
        if f2 > 1.0:
            focal_px = math.sqrt(f2)
        else:
            notes.append("VP1/VP2 are not orthogonal for a standard camera; using a closest-fit focal estimate.")
    if focal_px <= 0.0:
        active = [vp1]
        if mode.startswith(("2-Point", "3-Point")):
            active.append(vp2)
        if mode.startswith("3-Point"):
            active.append(vp3)
        distances = [math.hypot(p[0] - cx, p[1] - cy) for p in active]
        focal_px = max(height * 0.45, min(max(width, height) * 4.0, sum(distances) / max(1, len(distances))))

    vertical_fov = math.degrees(2.0 * math.atan((height * 0.5) / max(1.0, focal_px)))
    horizontal_fov = math.degrees(2.0 * math.atan((width * 0.5) / max(1.0, focal_px)))
    focal_length_mm = (sensor_height_mm * 0.5) / max(1.0e-6, math.tan(math.radians(vertical_fov) * 0.5))
    roll = 0.0
    if mode.startswith(("2-Point", "3-Point")):
        roll = math.degrees(math.atan2(vp2[1] - vp1[1], vp2[0] - vp1[0]))

    yaw = 0.0
    pitch = 0.0
    if mode.startswith("1-Point"):
        ray = _normalize_3d(((vp1[0] - cx) / focal_px, -(vp1[1] - cy) / focal_px, 1.0))
        yaw = math.degrees(math.atan2(ray[0], ray[2]))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, ray[1]))))
    elif mode.startswith("3-Point"):
        vertical_offset = (vp3[1] - cy) / max(1.0, focal_px)
        pitch = -math.degrees(math.atan(vertical_offset)) * 0.35

    confidence = 0.72
    if mode.startswith("2-Point") and not notes:
        confidence = 0.86
    if mode.startswith("3-Point") and not notes:
        confidence = 0.82

    return PerspectiveGuideSolveResult(
        mode=mode,
        projection_model="rectilinear",
        camera_settings={
            "fov_degrees": vertical_fov,
            "horizontal_fov_degrees": horizontal_fov,
            "focal_length_mm": focal_length_mm,
            "sensor_width_mm": sensor_width_mm,
            "sensor_height_mm": sensor_height_mm,
            "principal_point_px": (cx, cy),
            "film_offset_normalized": ((cx - width * 0.5) / width, (cy - height * 0.5) / height),
            "rotation_degrees": {"pitch": pitch, "yaw": yaw, "roll": roll},
        },
        projection_settings={"projection_blend": 0.0, "curvature": 0.0},
        confidence=confidence,
        notes=notes,
    )


def _solve_curvilinear(
    mode: str,
    points: dict[str, tuple[float, float]],
    width: float,
    height: float,
    cx: float,
    cy: float,
    sensor_width_mm: float,
    sensor_height_mm: float,
) -> PerspectiveGuideSolveResult:
    vp1 = _point(points, "VP1", (width * 0.05, height * 0.5))
    vp2 = _point(points, "VP2", (width * 0.95, height * 0.5))
    vp3 = _point(points, "VP3", (width * 0.5, height * 0.05))
    vp4 = _point(points, "VP4", (width * 0.5, height * 0.95))
    vp6 = _point(points, "VP6", (cx, cy))

    left = abs(cx - vp1[0])
    right = abs(vp2[0] - cx)
    top = abs(cy - vp3[1])
    bottom = abs(vp4[1] - cy)
    horizontal_radius = max(1.0, (left + right) * 0.5)
    vertical_radius = max(1.0, (top + bottom) * 0.5)
    horizontal_fov = max(35.0, min(220.0, 180.0 * (width * 0.5) / horizontal_radius))
    vertical_fov = max(35.0, min(180.0, 180.0 * (height * 0.5) / vertical_radius))
    equivalent_focal = (sensor_height_mm * 0.5) / max(1.0e-6, math.tan(math.radians(min(vertical_fov, 160.0)) * 0.5))
    imbalance = abs(left - right) / max(1.0, left + right) + abs(top - bottom) / max(1.0, top + bottom)
    curvature = max(0.0, min(1.0, 1.0 - imbalance * 0.5))
    projection = "spherical"
    if mode.startswith("4-Point"):
        projection = "four_point_curvilinear"
    elif mode.startswith("5-Point"):
        projection = "fisheye"
    elif mode.startswith("6-Point"):
        projection = "spherical_360"

    return PerspectiveGuideSolveResult(
        mode=mode,
        projection_model=projection,
        camera_settings={
            "fov_degrees": vertical_fov,
            "horizontal_fov_degrees": horizontal_fov,
            "focal_length_mm": equivalent_focal,
            "sensor_width_mm": sensor_width_mm,
            "sensor_height_mm": sensor_height_mm,
            "principal_point_px": (cx, cy),
            "film_offset_normalized": ((cx - width * 0.5) / width, (cy - height * 0.5) / height),
            "rotation_degrees": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        },
        projection_settings={
            "projection_blend": 1.0,
            "curvature": curvature,
            "horizontal_radius_px": horizontal_radius,
            "vertical_radius_px": vertical_radius,
            "upper_pole_px": vp3,
            "lower_pole_px": vp4,
            "front_pole_px": (cx, cy),
            "rear_pole_px": vp6,
        },
        confidence=0.7,
        notes=[
            "Nonlinear guide mode solved as a custom projection profile.",
            "Use the equivalent focal length for framing; exact reproduction needs a fisheye/spherical shader or viewport warp.",
        ],
    )


def _point(points: dict[str, tuple[float, float]], name: str, fallback: tuple[float, float]) -> tuple[float, float]:
    value = points.get(name)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except Exception:
            pass
    return fallback


def _normalize_3d(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])
    if length < 1.0e-9:
        return 0.0, 0.0, 1.0
    return vector[0] / length, vector[1] / length, vector[2] / length
