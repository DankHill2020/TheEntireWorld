"""Deterministic runtime procedural animation and ground-contact IK."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Callable, Mapping, Optional


Vector3 = tuple[float, float, float]
# Type aliases are evaluated even when ``annotations`` are deferred.  Maya 2023
# embeds Python 3.9, where ``typing.Mapping[...] | None`` is not supported.
GroundQuery = Callable[[Vector3, Vector3, float, str], Optional[Mapping[str, Any]]]


@dataclass(frozen=True)
class GroundIKSettings:
    root_bone: str
    joint_bone: str
    end_bone: str
    pole_vector: Vector3 = (0.0, 0.0, 1.0)
    probe_height: float = 0.5
    probe_depth: float = 1.0
    foot_offset: float = 0.04
    maximum_stretch: float = 1.05
    position_smoothing: float = 18.0
    plant_speed_threshold: float = 0.08
    collision_mask: str = "world_static"


@dataclass(frozen=True)
class GroundContact:
    hit: bool
    point: Vector3
    normal: Vector3 = (0.0, 1.0, 0.0)
    distance: float = 0.0
    collider: str = ""


@dataclass(frozen=True)
class LimbIKResult:
    root_position: Vector3
    joint_position: Vector3
    end_position: Vector3
    foot_normal: Vector3
    grounded: bool
    planted: bool
    stretch_ratio: float
    pelvis_request: float
    collider: str = ""


@dataclass(frozen=True)
class ProceduralAnimationFrame:
    limbs: dict[str, LimbIKResult]
    pelvis_offset: float
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "limbs": {key: asdict(value) for key, value in self.limbs.items()},
            "pelvis_offset": self.pelvis_offset,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class ProceduralAnimationRuntime:
    pelvis_smoothing: float = 14.0
    maximum_pelvis_drop: float = 0.45
    _pelvis_offset: float = 0.0
    _foot_targets: dict[str, Vector3] = field(default_factory=dict)
    _plant_targets: dict[str, Vector3] = field(default_factory=dict)

    def step_ground_ik(
        self,
        limb_settings: Mapping[str, GroundIKSettings],
        bone_positions: Mapping[str, Vector3],
        ground_query: GroundQuery,
        *,
        delta_time: float,
        character_speed: float = 0.0,
        weight: float = 1.0,
    ) -> ProceduralAnimationFrame:
        dt = max(0.0, float(delta_time))
        blend_weight = _clamp(float(weight), 0.0, 1.0)
        results: dict[str, LimbIKResult] = {}
        diagnostics: list[str] = []
        pelvis_requests: list[float] = []
        for limb_id, settings in limb_settings.items():
            missing = [
                bone for bone in (settings.root_bone, settings.joint_bone, settings.end_bone)
                if bone not in bone_positions
            ]
            if missing:
                diagnostics.append(f"{limb_id}: missing bones {', '.join(missing)}")
                continue
            root = _vec(bone_positions[settings.root_bone])
            joint = _vec(bone_positions[settings.joint_bone])
            animated_end = _vec(bone_positions[settings.end_bone])
            origin = _add(animated_end, (0.0, max(0.0, settings.probe_height), 0.0))
            maximum_distance = max(0.0, settings.probe_height + settings.probe_depth)
            raw_contact = ground_query(origin, (0.0, -1.0, 0.0), maximum_distance, settings.collision_mask)
            contact = _contact(raw_contact, origin)
            grounded = contact.hit
            target = animated_end
            if grounded:
                target = _add(contact.point, _scale(contact.normal, settings.foot_offset))
            previous = self._foot_targets.get(limb_id, animated_end)
            alpha = 1.0 - math.exp(-max(0.0, settings.position_smoothing) * dt) if dt else 1.0
            smoothed = _lerp(previous, target, alpha)
            self._foot_targets[limb_id] = smoothed
            planted = grounded and abs(float(character_speed)) <= max(0.0, settings.plant_speed_threshold)
            if planted:
                plant = self._plant_targets.setdefault(limb_id, smoothed)
                smoothed = _lerp(smoothed, plant, blend_weight)
            else:
                self._plant_targets.pop(limb_id, None)
            blended_target = _lerp(animated_end, smoothed, blend_weight)
            solved_joint, solved_end, stretch = solve_two_bone_ik(
                root, joint, animated_end, blended_target, settings.pole_vector,
                maximum_stretch=settings.maximum_stretch,
            )
            pelvis_request = min(0.0, blended_target[1] - animated_end[1]) if grounded else 0.0
            pelvis_requests.append(pelvis_request)
            results[str(limb_id)] = LimbIKResult(
                root, solved_joint, solved_end, contact.normal if grounded else (0.0, 1.0, 0.0),
                grounded, planted, stretch, pelvis_request, contact.collider,
            )
        requested = max(-abs(self.maximum_pelvis_drop), min(pelvis_requests, default=0.0))
        pelvis_alpha = 1.0 - math.exp(-max(0.0, self.pelvis_smoothing) * dt) if dt else 1.0
        self._pelvis_offset += (requested - self._pelvis_offset) * pelvis_alpha
        return ProceduralAnimationFrame(results, self._pelvis_offset, tuple(diagnostics))


def solve_two_bone_ik(
    root: Vector3,
    joint: Vector3,
    end: Vector3,
    target: Vector3,
    pole_vector: Vector3,
    *,
    maximum_stretch: float = 1.0,
) -> tuple[Vector3, Vector3, float]:
    root, joint, end, target = map(_vec, (root, joint, end, target))
    upper = max(1.0e-8, _length(_subtract(joint, root)))
    lower = max(1.0e-8, _length(_subtract(end, joint)))
    to_target = _subtract(target, root)
    distance = _length(to_target)
    maximum = (upper + lower) * max(1.0, float(maximum_stretch))
    solved_distance = _clamp(distance, abs(upper - lower) + 1.0e-7, maximum)
    direction = _normalize(to_target, (0.0, -1.0, 0.0))
    stretch_ratio = max(1.0, solved_distance / (upper + lower))
    effective_upper, effective_lower = upper * stretch_ratio, lower * stretch_ratio
    reach = min(solved_distance, effective_upper + effective_lower - 1.0e-7)
    along = (effective_upper * effective_upper - effective_lower * effective_lower + reach * reach) / (2.0 * reach)
    height = math.sqrt(max(0.0, effective_upper * effective_upper - along * along))
    pole_direction = _subtract(_vec(pole_vector), root)
    plane_normal = _normalize(_cross(direction, pole_direction), (1.0, 0.0, 0.0))
    bend_direction = _normalize(_cross(plane_normal, direction), (0.0, 0.0, 1.0))
    solved_joint = _add(_add(root, _scale(direction, along)), _scale(bend_direction, height))
    solved_end = _add(root, _scale(direction, min(distance, maximum)))
    return solved_joint, solved_end, stretch_ratio


def _contact(value: Mapping[str, Any] | None, origin: Vector3) -> GroundContact:
    if not value or not bool(value.get("hit", True)):
        return GroundContact(False, origin)
    point = _vec(value.get("point", origin))
    return GroundContact(
        True, point, _normalize(_vec(value.get("normal", (0.0, 1.0, 0.0))), (0.0, 1.0, 0.0)),
        float(value.get("distance", _length(_subtract(origin, point)))), str(value.get("collider") or ""),
    )


def _vec(value: Any) -> Vector3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("Expected a three-component vector.")
    result = tuple(float(component) for component in value)
    if not all(math.isfinite(component) for component in result):
        raise ValueError("Vector components must be finite.")
    return result  # type: ignore[return-value]


def _add(a: Vector3, b: Vector3) -> Vector3:
    return tuple(a[i] + b[i] for i in range(3))  # type: ignore[return-value]


def _subtract(a: Vector3, b: Vector3) -> Vector3:
    return tuple(a[i] - b[i] for i in range(3))  # type: ignore[return-value]


def _scale(value: Vector3, factor: float) -> Vector3:
    return tuple(component * factor for component in value)  # type: ignore[return-value]


def _length(value: Vector3) -> float:
    return math.sqrt(sum(component * component for component in value))


def _normalize(value: Vector3, fallback: Vector3) -> Vector3:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-9 else fallback


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _lerp(a: Vector3, b: Vector3, alpha: float) -> Vector3:
    return tuple(a[i] + (b[i] - a[i]) * alpha for i in range(3))  # type: ignore[return-value]


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


__all__ = [
    "GroundContact", "GroundIKSettings", "LimbIKResult", "ProceduralAnimationFrame",
    "ProceduralAnimationRuntime", "solve_two_bone_ik",
]
