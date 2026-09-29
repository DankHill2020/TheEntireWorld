"""Raycast-wheel vehicle rig with deterministic suspension and control forces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any, Callable, Mapping, Optional, Sequence


Vector3 = tuple[float, float, float]
# Keep this runtime-evaluated type alias compatible with Maya 2023's Python 3.9.
VehicleGroundQuery = Callable[[Vector3, Vector3, float, str], Optional[Mapping[str, Any]]]


@dataclass(frozen=True)
class WheelRigSettings:
    wheel_id: str
    mount_position: Vector3
    radius: float = 0.34
    suspension_rest_length: float = 0.32
    suspension_travel: float = 0.18
    spring_stiffness: float = 32_000.0
    spring_damping: float = 4_200.0
    steerable: bool = False
    driven: bool = True
    brake_torque: float = 1_800.0
    axle: str = "rear"
    collision_mask: str = "world_static"


@dataclass(frozen=True)
class VehicleRigSettings:
    mass: float = 1_350.0
    maximum_steer_angle: float = 32.0
    engine_force: float = 8_500.0
    rolling_resistance: float = 0.015
    aerodynamic_drag: float = 0.34
    anti_roll_stiffness: float = 7_500.0
    center_of_mass_offset: Vector3 = (0.0, -0.35, 0.0)


@dataclass(frozen=True)
class VehicleControlInput:
    throttle: float = 0.0
    steering: float = 0.0
    brake: float = 0.0
    handbrake: float = 0.0


@dataclass(frozen=True)
class WheelDynamicsResult:
    wheel_id: str
    grounded: bool
    contact_point: Vector3
    contact_normal: Vector3
    suspension_length: float
    compression: float
    suspension_force: float
    drive_force: float
    brake_force: float
    steering_angle: float
    angular_velocity: float
    collider: str = ""


@dataclass(frozen=True)
class VehicleDynamicsFrame:
    wheels: tuple[WheelDynamicsResult, ...]
    total_force: Vector3
    total_torque: Vector3
    grounded_wheels: int
    speed: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "wheels": [asdict(wheel) for wheel in self.wheels],
            "total_force": self.total_force,
            "total_torque": self.total_torque,
            "grounded_wheels": self.grounded_wheels,
            "speed": self.speed,
        }


@dataclass
class VehicleDynamicsRuntime:
    settings: VehicleRigSettings = field(default_factory=VehicleRigSettings)
    _previous_lengths: dict[str, float] = field(default_factory=dict)
    _wheel_angular_velocity: dict[str, float] = field(default_factory=dict)

    def step(
        self,
        wheels: Sequence[WheelRigSettings],
        chassis_position: Vector3,
        chassis_velocity: Vector3,
        controls: VehicleControlInput,
        ground_query: VehicleGroundQuery,
        *,
        delta_time: float,
        forward: Vector3 = (0.0, 0.0, 1.0),
        up: Vector3 = (0.0, 1.0, 0.0),
    ) -> VehicleDynamicsFrame:
        dt = max(1.0e-6, float(delta_time))
        chassis_position = _vec(chassis_position)
        velocity = _vec(chassis_velocity)
        forward = _normalize(_vec(forward), (0.0, 0.0, 1.0))
        up = _normalize(_vec(up), (0.0, 1.0, 0.0))
        down = _scale(up, -1.0)
        throttle = _clamp(float(controls.throttle), -1.0, 1.0)
        steering = _clamp(float(controls.steering), -1.0, 1.0)
        brake = _clamp(float(controls.brake), 0.0, 1.0)
        handbrake = _clamp(float(controls.handbrake), 0.0, 1.0)
        driven_count = max(1, sum(1 for wheel in wheels if wheel.driven))
        speed_forward = _dot(velocity, forward)
        results: list[WheelDynamicsResult] = []
        total_force = (0.0, 0.0, 0.0)
        total_torque = (0.0, 0.0, 0.0)
        compressions: dict[str, float] = {}
        for wheel in wheels:
            _validate_wheel(wheel)
            mount = _add(chassis_position, _vec(wheel.mount_position))
            ray_length = wheel.suspension_rest_length + wheel.suspension_travel + wheel.radius
            raw = ground_query(mount, down, ray_length, wheel.collision_mask)
            hit = bool(raw and raw.get("hit", True))
            point = _vec(raw.get("point", _add(mount, _scale(down, ray_length)))) if raw else _add(mount, _scale(down, ray_length))
            normal = _normalize(_vec(raw.get("normal", up)), up) if raw else up
            distance = float(raw.get("distance", _length(_subtract(mount, point)))) if raw else ray_length
            length = _clamp(distance - wheel.radius, 0.0, wheel.suspension_rest_length + wheel.suspension_travel)
            compression = wheel.suspension_rest_length - length if hit else -wheel.suspension_travel
            previous = self._previous_lengths.get(wheel.wheel_id, length)
            damper_velocity = (previous - length) / dt
            self._previous_lengths[wheel.wheel_id] = length
            suspension_force = max(0.0, wheel.spring_stiffness * compression + wheel.spring_damping * damper_velocity) if hit else 0.0
            drive_force = throttle * self.settings.engine_force / driven_count if hit and wheel.driven else 0.0
            wheel_brake = max(brake, handbrake if wheel.axle.casefold() == "rear" else 0.0)
            brake_force = 0.0
            if hit and abs(speed_forward) > 1.0e-5:
                brake_force = -math.copysign(wheel_brake * wheel.brake_torque / max(wheel.radius, 1.0e-5), speed_forward)
            force = _add(_scale(normal, suspension_force), _scale(forward, drive_force + brake_force))
            total_force = _add(total_force, force)
            lever = _subtract(point, _add(chassis_position, self.settings.center_of_mass_offset))
            total_torque = _add(total_torque, _cross(lever, force))
            angular = speed_forward / wheel.radius if hit else self._wheel_angular_velocity.get(wheel.wheel_id, 0.0)
            angular *= max(0.0, 1.0 - wheel_brake * dt * 8.0)
            self._wheel_angular_velocity[wheel.wheel_id] = angular
            compressions[wheel.wheel_id] = compression
            results.append(WheelDynamicsResult(
                wheel.wheel_id, hit, point, normal, length, compression, suspension_force,
                drive_force, brake_force,
                math.radians(self.settings.maximum_steer_angle) * steering if wheel.steerable else 0.0,
                angular, str(raw.get("collider") or "") if raw else "",
            ))
        total_torque = _add(total_torque, self._anti_roll_torque(wheels, compressions))
        speed = _length(velocity)
        drag = self.settings.aerodynamic_drag * speed * speed + self.settings.rolling_resistance * self.settings.mass * 9.81
        if speed > 1.0e-6:
            total_force = _add(total_force, _scale(_normalize(velocity, forward), -drag))
        return VehicleDynamicsFrame(tuple(results), total_force, total_torque, sum(item.grounded for item in results), speed)

    def _anti_roll_torque(self, wheels: Sequence[WheelRigSettings], compressions: Mapping[str, float]) -> Vector3:
        by_axle: dict[str, list[WheelRigSettings]] = {}
        for wheel in wheels:
            by_axle.setdefault(wheel.axle, []).append(wheel)
        roll = 0.0
        for axle_wheels in by_axle.values():
            if len(axle_wheels) != 2:
                continue
            first, second = sorted(axle_wheels, key=lambda item: item.mount_position[0])
            roll += (compressions.get(first.wheel_id, 0.0) - compressions.get(second.wheel_id, 0.0)) * self.settings.anti_roll_stiffness
        return (0.0, 0.0, roll)


def _validate_wheel(wheel: WheelRigSettings) -> None:
    if not wheel.wheel_id:
        raise ValueError("Wheel ID cannot be empty.")
    if wheel.radius <= 0.0 or wheel.suspension_rest_length < 0.0 or wheel.suspension_travel < 0.0:
        raise ValueError(f"{wheel.wheel_id}: wheel and suspension dimensions must be non-negative, with radius greater than zero.")
    if wheel.spring_stiffness < 0.0 or wheel.spring_damping < 0.0 or wheel.brake_torque < 0.0:
        raise ValueError(f"{wheel.wheel_id}: spring, damping, and brake values cannot be negative.")


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


def _dot(a: Vector3, b: Vector3) -> float:
    return sum(a[i] * b[i] for i in range(3))


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


__all__ = [
    "VehicleControlInput", "VehicleDynamicsFrame", "VehicleDynamicsRuntime", "VehicleRigSettings",
    "WheelDynamicsResult", "WheelRigSettings",
]
