"""Coordinate-space conversions for federated DCC scene data.

Tech Connector's composition space is X-right, Y-up, Z-forward, and centimeter based.
Provider-native values stay available for display/editing, but scene assembly,
camera sync, measurements, and cross-app transforms should route through this
module so unit and axis assumptions stay consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Sequence


Vec3 = tuple[float, float, float]
BBox6 = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class AxisBasis:
    """Maps provider-native axes into Tech Connector X-right/Y-up/Z-forward axes."""

    shared_x_from_native: tuple[int, float]
    shared_y_from_native: tuple[int, float]
    shared_z_from_native: tuple[int, float]

    def native_to_shared(self, point: Sequence[float], scale: float) -> Vec3:
        native = _vec3(point)
        axes = (self.shared_x_from_native, self.shared_y_from_native, self.shared_z_from_native)
        return tuple(native[index] * sign * scale for index, sign in axes)  # type: ignore[return-value]

    def shared_to_native(self, point: Sequence[float], scale: float) -> Vec3:
        shared = _vec3(point)
        native = [0.0, 0.0, 0.0]
        for shared_index, (native_index, sign) in enumerate(
            (self.shared_x_from_native, self.shared_y_from_native, self.shared_z_from_native)
        ):
            native[native_index] = shared[shared_index] * sign / scale
        return native[0], native[1], native[2]


PROVIDER_AXIS_BASIS: dict[str, AxisBasis] = {
    # Maya default: X right, Y up, Z forward in scene-space terms.
    "maya": AxisBasis((0, 1.0), (1, 1.0), (2, 1.0)),
    # Blender default: X right, Z up, -Y forward.
    "blender": AxisBasis((0, 1.0), (2, 1.0), (1, -1.0)),
    # Unreal default: Y right, Z up, X forward.
    "unreal": AxisBasis((1, 1.0), (2, 1.0), (0, 1.0)),
    "motionbuilder": AxisBasis((0, 1.0), (1, 1.0), (2, 1.0)),
    "houdini": AxisBasis((0, 1.0), (1, 1.0), (2, 1.0)),
    # Unity world space is X right, Y up, Z forward, in meters by default.
    "unity": AxisBasis((0, 1.0), (1, 1.0), (2, 1.0)),
    "3dsmax": AxisBasis((0, 1.0), (2, 1.0), (1, 1.0)),
    "max": AxisBasis((0, 1.0), (2, 1.0), (1, 1.0)),
}


def _axis_basis_for_provider_scene(provider_id: str, up_axis: str | None = None) -> AxisBasis:
    provider = str(provider_id or "").lower()
    axis = str(up_axis or "").strip().lower()
    if provider in {"maya", "motionbuilder", "houdini", "unity", "3dsmax", "max"}:
        if axis.startswith("z"):
            # X stays right, provider Z becomes shared up, provider Y becomes shared forward.
            return AxisBasis((0, 1.0), (2, 1.0), (1, 1.0))
        if axis.startswith("y"):
            return AxisBasis((0, 1.0), (1, 1.0), (2, 1.0))
    return PROVIDER_AXIS_BASIS.get(provider, PROVIDER_AXIS_BASIS["maya"])


_UNIT_TO_CM = {
    "mm": 0.1,
    "millimeter": 0.1,
    "millimeters": 0.1,
    "cm": 1.0,
    "centimeter": 1.0,
    "centimeters": 1.0,
    "m": 100.0,
    "meter": 100.0,
    "meters": 100.0,
    "km": 100000.0,
    "kilometer": 100000.0,
    "kilometers": 100000.0,
    "in": 2.54,
    "inch": 2.54,
    "inches": 2.54,
    "ft": 30.48,
    "foot": 30.48,
    "feet": 30.48,
    "yd": 91.44,
    "yard": 91.44,
    "yards": 91.44,
    "metric": 100.0,
    "none": 100.0,
    "imperial": 30.48,
    "centimeters": 1.0,
}


def provider_default_unit(provider_id: str) -> str:
    provider = str(provider_id or "").lower()
    if provider in {"blender", "houdini", "unity"}:
        return "meters"
    if provider == "unreal":
        return "centimeters"
    return "centimeters"


def unit_to_centimeters(unit_name: str | None, provider_id: str = "") -> float:
    raw = str(unit_name or provider_default_unit(provider_id)).strip().lower()
    return float(_UNIT_TO_CM.get(raw, _UNIT_TO_CM.get(provider_default_unit(provider_id), 1.0)))


@dataclass(frozen=True)
class CoordinateSpace:
    provider_id: str
    unit_linear: str | None = None
    up_axis: str | None = None

    @property
    def provider(self) -> str:
        return str(self.provider_id or "").lower()

    @property
    def centimeters_per_native_unit(self) -> float:
        return unit_to_centimeters(self.unit_linear, self.provider)

    def native_to_shared_point(self, point: Sequence[float]) -> Vec3:
        return provider_axis_basis(self.provider, self.up_axis).native_to_shared(point, self.centimeters_per_native_unit)

    def shared_to_native_point(self, point: Sequence[float]) -> Vec3:
        return provider_axis_basis(self.provider, self.up_axis).shared_to_native(point, self.centimeters_per_native_unit or 1.0)

    def native_bbox_to_shared(self, bbox: Sequence[float]) -> BBox6:
        b = [float(v) for v in bbox]
        if len(b) != 6:
            raise ValueError("Bounding boxes must have six values.")
        corners = [
            self.native_to_shared_point((b[xi], b[yi], b[zi]))
            for xi in (0, 3)
            for yi in (1, 4)
            for zi in (2, 5)
        ]
        return bounds_from_points(corners)


@dataclass(frozen=True)
class ProviderScaleDiagnostic:
    """Live unit conversion facts for one provider relative to a reference app."""

    provider_id: str
    unit_linear: str
    reference_provider_id: str
    reference_unit_linear: str
    centimeters_per_native_unit: float
    reference_centimeters_per_native_unit: float

    @property
    def native_to_reference_scale(self) -> float:
        return self.centimeters_per_native_unit / max(1.0e-12, self.reference_centimeters_per_native_unit)

    @property
    def reference_to_native_scale(self) -> float:
        return self.reference_centimeters_per_native_unit / max(1.0e-12, self.centimeters_per_native_unit)

    def compact_label(self) -> str:
        return (
            f"{self.provider_id}:{self.unit_linear or provider_default_unit(self.provider_id)} "
            f"->{self.reference_provider_id} x{self.native_to_reference_scale:g}"
        )


@dataclass(frozen=True)
class SceneNormalization:
    center: Vec3
    scale: float

    @classmethod
    def from_bounds(cls, bounds: Iterable[Sequence[float]], target_extent: float = 4.0) -> "SceneNormalization":
        merged = bounds_from_bboxes(bounds)
        min_x, min_y, min_z, max_x, max_y, max_z = merged
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        extent = max(max_x - min_x, max_y - min_y, max_z - min_z, 0.001)
        return cls(center=center, scale=float(target_extent) / extent)

    def shared_to_view_point(self, point: Sequence[float]) -> Vec3:
        x, y, z = _vec3(point)
        return (
            (x - self.center[0]) * self.scale,
            (y - self.center[1]) * self.scale,
            (z - self.center[2]) * self.scale,
        )

    def view_to_shared_point(self, point: Sequence[float]) -> Vec3:
        x, y, z = _vec3(point)
        scale = self.scale or 1.0
        return (
            x / scale + self.center[0],
            y / scale + self.center[1],
            z / scale + self.center[2],
        )


def provider_native_to_shared(
    provider_id: str,
    point: Sequence[float],
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> Vec3:
    return CoordinateSpace(provider_id, unit_linear, up_axis).native_to_shared_point(point)


def shared_to_provider_native(
    provider_id: str,
    point: Sequence[float],
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> Vec3:
    return CoordinateSpace(provider_id, unit_linear, up_axis).shared_to_native_point(point)


def provider_bbox_to_shared(
    provider_id: str,
    bbox: Sequence[float],
    unit_linear: str | None = None,
    up_axis: str | None = None,
) -> BBox6:
    return CoordinateSpace(provider_id, unit_linear, up_axis).native_bbox_to_shared(bbox)


def provider_scale_diagnostic(
    provider_id: str,
    unit_linear: str | None = None,
    *,
    reference_provider_id: str = "maya",
    reference_unit_linear: str | None = "centimeters",
) -> ProviderScaleDiagnostic:
    provider = str(provider_id or "provider").lower()
    reference = str(reference_provider_id or "maya").lower()
    provider_unit = str(unit_linear or provider_default_unit(provider))
    reference_unit = str(reference_unit_linear or provider_default_unit(reference))
    return ProviderScaleDiagnostic(
        provider_id=provider,
        unit_linear=provider_unit,
        reference_provider_id=reference,
        reference_unit_linear=reference_unit,
        centimeters_per_native_unit=unit_to_centimeters(provider_unit, provider),
        reference_centimeters_per_native_unit=unit_to_centimeters(reference_unit, reference),
    )


def snapshot_scale_diagnostics(
    snapshots: dict[str, dict],
    *,
    reference_provider_id: str = "maya",
    reference_unit_linear: str | None = "centimeters",
) -> dict[str, ProviderScaleDiagnostic]:
    diagnostics: dict[str, ProviderScaleDiagnostic] = {}
    for provider, snapshot in (snapshots or {}).items():
        if not isinstance(snapshot, dict):
            continue
        provider_key = str(snapshot.get("provider_id") or provider or "").lower()
        diagnostics[provider_key] = provider_scale_diagnostic(
            provider_key,
            snapshot.get("unit_linear"),
            reference_provider_id=reference_provider_id,
            reference_unit_linear=reference_unit_linear,
        )
    return diagnostics


def convert_point_between_providers(
    source_provider: str,
    target_provider: str,
    point: Sequence[float],
    *,
    source_unit: str | None = None,
    target_unit: str | None = None,
    source_up_axis: str | None = None,
    target_up_axis: str | None = None,
) -> Vec3:
    shared = provider_native_to_shared(source_provider, point, source_unit, source_up_axis)
    return shared_to_provider_native(target_provider, shared, target_unit, target_up_axis)


def convert_vector_between_providers(
    source_provider: str,
    target_provider: str,
    vector: Sequence[float],
    *,
    source_unit: str | None = None,
    target_unit: str | None = None,
    source_up_axis: str | None = None,
    target_up_axis: str | None = None,
) -> Vec3:
    """Convert a direction or delta vector without applying any scene offset."""
    return convert_point_between_providers(
        source_provider,
        target_provider,
        vector,
        source_unit=source_unit,
        target_unit=target_unit,
        source_up_axis=source_up_axis,
        target_up_axis=target_up_axis,
    )


def convert_camera_payload_between_providers(
    source_provider: str,
    target_provider: str,
    payload: dict,
    *,
    source_unit: str | None = None,
    target_unit: str | None = None,
    source_up_axis: str | None = None,
    target_up_axis: str | None = None,
    source_bounds_shared: tuple[Vec3, float] | None = None,
    target_bounds_shared: tuple[Vec3, float] | None = None,
) -> dict:
    """Convert camera eye/target/up payloads between provider-native spaces.

    Eye, target, and up-target first move into Tech Connector shared space. If
    both provider scene bounds are supplied, the camera is then remapped from
    the source scene center/extent to the target scene center/extent. That keeps
    camera framing useful when one provider has only a reference scene or has a
    different source scale, while preserving native axis/unit parity.
    """
    eye_shared = provider_native_to_shared(source_provider, payload["eye"], source_unit, source_up_axis)
    target_shared = provider_native_to_shared(source_provider, payload["target"], source_unit, source_up_axis)
    up_target = payload.get("up_target")
    up_target_shared = (
        provider_native_to_shared(source_provider, up_target, source_unit, source_up_axis)
        if isinstance(up_target, (list, tuple)) and len(up_target) >= 3
        else None
    )
    if source_bounds_shared and target_bounds_shared:
        source_center, source_extent = source_bounds_shared
        target_center, target_extent = target_bounds_shared
        ratio = float(target_extent) / max(1.0e-6, float(source_extent))

        def remap(point: Vec3) -> Vec3:
            return tuple(float(target_center[i]) + (float(point[i]) - float(source_center[i])) * ratio for i in range(3))  # type: ignore[return-value]

        source_target = target_shared
        eye_shared = remap(eye_shared)
        target_shared = remap(target_shared)
        if up_target_shared is not None:
            up_vec = tuple(float(up_target_shared[i]) - float(source_target[i]) for i in range(3))
            up_target_shared = tuple(float(target_shared[i]) + up_vec[i] * ratio for i in range(3))  # type: ignore[assignment]
    converted = {
        "eye": shared_to_provider_native(target_provider, eye_shared, target_unit, target_up_axis),
        "target": shared_to_provider_native(target_provider, target_shared, target_unit, target_up_axis),
        "fov_degrees": float(payload.get("fov_degrees", 45.0)),
        "aspect_ratio": float(payload.get("aspect_ratio", 16.0 / 9.0)),
        "focal_length_mm": float(payload.get("focal_length_mm", 35.0)),
        "near_clip": float(payload.get("near_clip", 0.1)),
        "far_clip": float(payload.get("far_clip", 100000.0)),
    }
    if up_target_shared is not None:
        converted["up_target"] = shared_to_provider_native(target_provider, up_target_shared, target_unit, target_up_axis)
    return converted


def provider_axis_basis(provider_id: str, up_axis: str | None = None) -> AxisBasis:
    return _axis_basis_for_provider_scene(provider_id, up_axis)


def provider_space_label(provider_id: str, unit_linear: str | None = None) -> str:
    provider = str(provider_id or "provider").lower()
    unit = unit_linear or provider_default_unit(provider)
    if provider == "blender":
        axes = "X right, Z up, -Y forward"
    elif provider == "unreal":
        axes = "Y right, Z up, X forward"
    elif provider == "maya":
        axes = "X right, Y up, Z forward"
    else:
        axes = "provider-native basis"
    return f"{provider} native ({axes}, {unit})"


def bounds_from_points(points: Iterable[Sequence[float]]) -> BBox6:
    values = [_vec3(point) for point in points]
    if not values:
        raise ValueError("Cannot compute bounds from no points.")
    return (
        min(p[0] for p in values),
        min(p[1] for p in values),
        min(p[2] for p in values),
        max(p[0] for p in values),
        max(p[1] for p in values),
        max(p[2] for p in values),
    )


def bounds_from_bboxes(bounds: Iterable[Sequence[float]]) -> BBox6:
    boxes = [[float(v) for v in bbox] for bbox in bounds]
    boxes = [bbox for bbox in boxes if len(bbox) == 6 and all(math.isfinite(v) for v in bbox)]
    if not boxes:
        raise ValueError("Cannot compute bounds from no bounding boxes.")
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


def _vec3(point: Sequence[float]) -> Vec3:
    if len(point) < 3:
        raise ValueError("Expected a 3D point.")
    return float(point[0]), float(point[1]), float(point[2])
