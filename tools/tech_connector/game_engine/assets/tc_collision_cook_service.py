from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct
from typing import Any, Iterable


MAGIC = b"TCCOL01\0"
VERSION = 1
KINDS = {"convex_hull": 1, "triangle_mesh": 2, "compound": 3}
PRIMITIVES = {"box": 1, "sphere": 2, "capsule": 3}
_HEADER = struct.Struct("<8sIIIII6f")
_CHILD = struct.Struct("<I12f")


@dataclass(frozen=True)
class CookedCollisionSummary:
    path: Path
    kind: str
    vertex_count: int
    triangle_count: int
    child_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]


def _vector(values: Iterable[Any], count: int, label: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != count or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain {count} finite numbers.")
    return result


def _rotate_quaternion(point: tuple[float, float, float], rotation: tuple[float, ...]) -> tuple[float, float, float]:
    x, y, z, w = rotation
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1.0e-12:
        raise ValueError("Compound child rotation quaternion cannot have zero length.")
    x, y, z, w = x / length, y / length, z / length, w / length
    tx, ty, tz = 2.0 * (y * point[2] - z * point[1]), 2.0 * (z * point[0] - x * point[2]), 2.0 * (x * point[1] - y * point[0])
    return (
        point[0] + w * tx + y * tz - z * ty,
        point[1] + w * ty + z * tx - x * tz,
        point[2] + w * tz + x * ty - y * tx,
    )


def _validate_convex(vertices: list[tuple[float, ...]], triangles: list[tuple[int, ...]]) -> None:
    for triangle in triangles:
        a, b, c = (vertices[index] for index in triangle)
        ab = tuple(b[axis] - a[axis] for axis in range(3))
        ac = tuple(c[axis] - a[axis] for axis in range(3))
        normal = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        signs = {
            1 if sum(normal[axis] * (point[axis] - a[axis]) for axis in range(3)) > 1.0e-6 else
            -1 if sum(normal[axis] * (point[axis] - a[axis]) for axis in range(3)) < -1.0e-6 else 0
            for point in vertices
        }
        if 1 in signs and -1 in signs:
            raise ValueError("convex_hull triangles do not describe a convex surface.")


def cook_collision_asset(
    path: str | Path,
    *,
    kind: str,
    vertices: Iterable[Iterable[float]] = (),
    triangles: Iterable[Iterable[int]] = (),
    children: Iterable[dict[str, Any]] = (),
) -> CookedCollisionSummary:
    """Cook deterministic collision data consumed directly by the native player."""

    kind = str(kind).casefold()
    if kind not in KINDS:
        raise ValueError(f"Unsupported cooked collision kind: {kind}")
    vertex_rows = [_vector(row, 3, "collision vertex") for row in vertices]
    triangle_rows = [tuple(int(value) for value in row) for row in triangles]
    if any(len(row) != 3 for row in triangle_rows):
        raise ValueError("Every collision triangle must contain three indices.")
    if any(index < 0 or index >= len(vertex_rows) for row in triangle_rows for index in row):
        raise ValueError("Collision triangle index is outside the vertex buffer.")
    child_rows = [dict(item) for item in children]
    if kind in {"convex_hull", "triangle_mesh"} and (len(vertex_rows) < 4 or not triangle_rows):
        raise ValueError(f"{kind} requires at least four vertices and one triangle.")
    if kind == "convex_hull":
        _validate_convex(vertex_rows, triangle_rows)
    if kind == "compound" and not child_rows:
        raise ValueError("compound requires at least one primitive child.")
    if len(vertex_rows) > 10_000_000 or len(triangle_rows) > 20_000_000 or len(child_rows) > 65_535:
        raise ValueError("Collision asset exceeds native safety limits.")

    points = list(vertex_rows)
    for child in child_rows:
        center = _vector(child.get("translation") or (0.0, 0.0, 0.0), 3, "child translation")
        extents = _vector(child.get("half_extents") or (0.5, 0.5, 0.5), 3, "child half extents")
        rotation = _vector(child.get("rotation") or (0.0, 0.0, 0.0, 1.0), 4, "child rotation")
        for x in (-extents[0], extents[0]):
            for y in (-extents[1], extents[1]):
                for z in (-extents[2], extents[2]):
                    rotated = _rotate_quaternion((x, y, z), rotation)
                    points.append(tuple(center[axis] + rotated[axis] for axis in range(3)))
    bounds_min = tuple(min(point[axis] for point in points) for axis in range(3))
    bounds_max = tuple(max(point[axis] for point in points) for axis in range(3))

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        stream.write(_HEADER.pack(
            MAGIC, VERSION, KINDS[kind], len(vertex_rows), len(triangle_rows), len(child_rows),
            *bounds_min, *bounds_max,
        ))
        for vertex in vertex_rows:
            stream.write(struct.pack("<3f", *vertex))
        for triangle in triangle_rows:
            stream.write(struct.pack("<3I", *triangle))
        for child in child_rows:
            shape = str(child.get("shape") or "box").casefold()
            if shape not in PRIMITIVES:
                raise ValueError(f"Unsupported compound child shape: {shape}")
            translation = _vector(child.get("translation") or (0.0, 0.0, 0.0), 3, "child translation")
            rotation = _vector(child.get("rotation") or (0.0, 0.0, 0.0, 1.0), 4, "child rotation")
            extents = _vector(child.get("half_extents") or (0.5, 0.5, 0.5), 3, "child half extents")
            stream.write(_CHILD.pack(
                PRIMITIVES[shape], *translation, *rotation, *extents,
                float(child.get("radius", 0.5)), float(child.get("half_height", 0.5)),
            ))
    return CookedCollisionSummary(target, kind, len(vertex_rows), len(triangle_rows), len(child_rows), bounds_min, bounds_max)


def inspect_collision_asset(path: str | Path) -> CookedCollisionSummary:
    source = Path(path)
    with source.open("rb") as stream:
        values = _HEADER.unpack(stream.read(_HEADER.size))
    magic, version, kind_code, vertices, triangles, children, *bounds = values
    if magic != MAGIC or version != VERSION or kind_code not in KINDS.values():
        raise ValueError("Unsupported or corrupt TC collision asset.")
    expected = _HEADER.size + vertices * 12 + triangles * 12 + children * _CHILD.size
    if source.stat().st_size != expected:
        raise ValueError("TC collision asset length does not match its header.")
    kind = next(name for name, code in KINDS.items() if code == kind_code)
    return CookedCollisionSummary(source, kind, vertices, triangles, children, tuple(bounds[:3]), tuple(bounds[3:]))


__all__ = ["CookedCollisionSummary", "cook_collision_asset", "inspect_collision_asset"]
