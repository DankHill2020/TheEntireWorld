"""Shared collision projection for skin-adjacent character dynamics."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


Vec3 = tuple[float, float, float]


def project_character_point(
    position: Sequence[float],
    velocity: Sequence[float],
    *,
    radius: float,
    friction: float,
    restitution: float,
    colliders: Sequence[Mapping[str, Any]],
    previous_position: Sequence[float] | None = None,
) -> tuple[Vec3, Vec3, int]:
    """Project a dynamic point against planes, spheres, capsules, and boxes.

    Sphere tests include a swept segment check so fast secondary motion cannot
    silently tunnel through a body collider between substeps.
    """
    point, speed = _vec3(position), _vec3(velocity)
    previous = _vec3(previous_position) if previous_position is not None else None
    contacts = 0
    skin = max(0.0, float(radius))
    for collider in colliders:
        kind = str(collider.get("type") or "sphere").strip().lower()
        collider_friction = max(0.0, float(collider.get("friction", friction)))
        collider_restitution = max(0.0, float(collider.get("restitution", restitution)))
        projected: tuple[Vec3, Vec3] | None = None
        if kind == "plane":
            normal = _normalize(_vec3(collider.get("normal", (0.0, 1.0, 0.0))), (0.0, 1.0, 0.0))
            distance = _dot(point, normal) - float(collider.get("offset", 0.0))
            if distance < skin:
                projected = (_add(point, _scale(normal, skin - distance)), normal)
        elif kind == "sphere":
            center = _vec3(collider.get("center", (0.0, 0.0, 0.0)))
            minimum = max(0.0, float(collider.get("radius", 1.0))) + skin
            delta, distance = _subtract(point, center), _length(_subtract(point, center))
            if distance < minimum:
                normal = _normalize(delta, (0.0, 1.0, 0.0))
                projected = (_add(center, _scale(normal, minimum)), normal)
            elif previous is not None:
                hit = _swept_sphere(previous, point, center, minimum)
                if hit is not None:
                    normal = _normalize(_subtract(hit, center), (0.0, 1.0, 0.0))
                    projected = (_add(center, _scale(normal, minimum)), normal)
        elif kind == "capsule":
            start = _vec3(collider.get("start", collider.get("a", (0.0, -0.5, 0.0))))
            end = _vec3(collider.get("end", collider.get("b", (0.0, 0.5, 0.0))))
            minimum = max(0.0, float(collider.get("radius", 0.5))) + skin
            closest = _closest_segment_point(point, start, end)
            delta, distance = _subtract(point, closest), _length(_subtract(point, closest))
            if distance < minimum:
                normal = _normalize(delta, _capsule_fallback_normal(start, end))
                projected = (_add(closest, _scale(normal, minimum)), normal)
        elif kind in {"box", "aabb"}:
            center = _vec3(collider.get("center", (0.0, 0.0, 0.0)))
            half = _vec3(collider.get("half_extents", collider.get("extents", (0.5, 0.5, 0.5))))
            expanded = tuple(max(0.0, half[axis]) + skin for axis in range(3))
            local = _subtract(point, center)
            if all(abs(local[axis]) < expanded[axis] for axis in range(3)):
                axis = min(range(3), key=lambda value: expanded[value] - abs(local[value]))
                sign = -1.0 if local[axis] < 0.0 else 1.0
                normal = tuple(sign if value == axis else 0.0 for value in range(3))
                corrected = list(point)
                corrected[axis] = center[axis] + sign * expanded[axis]
                projected = (tuple(corrected), normal)
        if projected is not None:
            point, normal = projected
            speed = collision_velocity(speed, normal, collider_friction, collider_restitution)
            previous = point
            contacts += 1
    return point, speed, contacts


def collision_velocity(velocity: Sequence[float], normal: Sequence[float], friction: float, restitution: float) -> Vec3:
    speed, direction = _vec3(velocity), _normalize(_vec3(normal), (0.0, 1.0, 0.0))
    normal_speed = _dot(speed, direction)
    normal_velocity = _scale(direction, normal_speed)
    tangent = _subtract(speed, normal_velocity)
    reflected = _scale(normal_velocity, -max(0.0, restitution) if normal_speed < 0.0 else 1.0)
    return _add(reflected, _scale(tangent, max(0.0, 1.0 - max(0.0, friction))))


def _swept_sphere(start: Vec3, end: Vec3, center: Vec3, radius: float) -> Vec3 | None:
    motion, relative = _subtract(end, start), _subtract(start, center)
    a = _dot(motion, motion)
    if a <= 1.0e-18 or _dot(relative, relative) <= radius * radius:
        return None
    b, c = 2.0 * _dot(relative, motion), _dot(relative, relative) - radius * radius
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    candidates = [value for value in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)) if 0.0 <= value <= 1.0]
    return _add(start, _scale(motion, min(candidates))) if candidates else None


def _closest_segment_point(point: Vec3, start: Vec3, end: Vec3) -> Vec3:
    segment = _subtract(end, start)
    denominator = _dot(segment, segment)
    amount = max(0.0, min(1.0, _dot(_subtract(point, start), segment) / denominator)) if denominator > 1.0e-18 else 0.0
    return _add(start, _scale(segment, amount))


def _capsule_fallback_normal(start: Vec3, end: Vec3) -> Vec3:
    axis = _normalize(_subtract(end, start), (0.0, 1.0, 0.0))
    candidate = _cross(axis, (1.0, 0.0, 0.0))
    return _normalize(candidate, (0.0, 0.0, 1.0))


def _vec3(value: Sequence[float]) -> Vec3:
    values = tuple(float(item) for item in value)
    return (values + (0.0, 0.0, 0.0))[:3]


def _add(a: Vec3, b: Vec3) -> Vec3: return tuple(a[index] + b[index] for index in range(3))
def _subtract(a: Vec3, b: Vec3) -> Vec3: return tuple(a[index] - b[index] for index in range(3))
def _scale(value: Vec3, amount: float) -> Vec3: return tuple(item * amount for item in value)
def _dot(a: Vec3, b: Vec3) -> float: return sum(a[index] * b[index] for index in range(3))
def _cross(a: Vec3, b: Vec3) -> Vec3: return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _length(value: Vec3) -> float: return math.sqrt(_dot(value, value))
def _normalize(value: Vec3, fallback: Vec3) -> Vec3:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-12 else fallback


__all__ = ["collision_velocity", "project_character_point"]
