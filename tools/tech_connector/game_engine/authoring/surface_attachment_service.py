"""Portable barycentric mesh attachments for rig controls and constraints."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Any, Sequence


SURFACE_ATTACHMENT_SCHEMA = "tech_connector.surface_attachment.v1"


@dataclass(frozen=True)
class SurfaceAttachment:
    mesh_id: str
    face_index: int
    triangle_vertex_ids: tuple[int, int, int]
    barycentric: tuple[float, float, float]
    position: tuple[float, float, float]
    tangent: tuple[float, float, float]
    normal: tuple[float, float, float]
    binormal: tuple[float, float, float]
    matrix: tuple[float, ...]
    topology_fingerprint: str = ""
    schema: str = SURFACE_ATTACHMENT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["triangle_vertex_ids"] = list(self.triangle_vertex_ids)
        data["barycentric"] = list(self.barycentric)
        data["position"] = list(self.position)
        data["tangent"] = list(self.tangent)
        data["normal"] = list(self.normal)
        data["binormal"] = list(self.binormal)
        data["matrix"] = list(self.matrix)
        return data


def create_surface_attachment(
    mesh_id: str,
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    *,
    face_index: int,
    barycentric: Sequence[float] = (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    triangle_offset: int = 0,
    topology_fingerprint: str = "",
) -> SurfaceAttachment:
    index = int(face_index)
    if index < 0 or index >= len(faces):
        raise IndexError(f"Surface attachment face index {index} is outside the mesh.")
    face = tuple(int(value) for value in faces[index])
    if len(face) < 3:
        raise ValueError("Surface attachment requires a face with at least three vertices.")
    offset = max(0, min(len(face) - 3, int(triangle_offset)))
    triangle = (face[0], face[offset + 1], face[offset + 2])
    if any(vertex_id < 0 or vertex_id >= len(vertices) for vertex_id in triangle):
        raise IndexError("Surface attachment face references a vertex outside the mesh.")
    weights = _normalized_barycentric(barycentric)
    points = [_point3(vertices[vertex_id]) for vertex_id in triangle]
    position = tuple(sum(weights[i] * points[i][axis] for i in range(3)) for axis in range(3))
    tangent = _normalize(_subtract(points[1], points[0]), "Surface attachment triangle has a zero-length edge.")
    normal = _normalize(_cross(_subtract(points[1], points[0]), _subtract(points[2], points[0])), "Surface attachment triangle is degenerate.")
    binormal = _normalize(_cross(tangent, normal), "Surface attachment frame is degenerate.")
    tangent = _normalize(_cross(normal, binormal), "Surface attachment tangent frame is degenerate.")
    matrix = (
        tangent[0], tangent[1], tangent[2], 0.0,
        normal[0], normal[1], normal[2], 0.0,
        binormal[0], binormal[1], binormal[2], 0.0,
        position[0], position[1], position[2], 1.0,
    )
    return SurfaceAttachment(
        mesh_id=str(mesh_id or "mesh"),
        face_index=index,
        triangle_vertex_ids=triangle,
        barycentric=weights,
        position=position,
        tangent=tangent,
        normal=normal,
        binormal=binormal,
        matrix=matrix,
        topology_fingerprint=str(topology_fingerprint or ""),
    )


def update_surface_attachment(
    attachment: SurfaceAttachment | dict[str, Any],
    vertices: Sequence[Sequence[float]],
) -> SurfaceAttachment:
    data = attachment.to_dict() if isinstance(attachment, SurfaceAttachment) else dict(attachment or {})
    triangle = tuple(int(value) for value in data.get("triangle_vertex_ids") or ())
    if len(triangle) != 3 or any(index < 0 or index >= len(vertices) for index in triangle):
        raise ValueError("Surface attachment triangle IDs no longer resolve on this mesh.")
    updated = create_surface_attachment(
        str(data.get("mesh_id") or "mesh"),
        vertices,
        [triangle],
        face_index=0,
        barycentric=data.get("barycentric") or (1.0 / 3.0,) * 3,
        topology_fingerprint=str(data.get("topology_fingerprint") or ""),
    )
    return replace(updated, face_index=int(data.get("face_index", 0) or 0))


def _normalized_barycentric(values: Sequence[float]) -> tuple[float, float, float]:
    weights = tuple(float(value) for value in values)
    if len(weights) != 3 or any(not math.isfinite(value) or value < 0.0 for value in weights):
        raise ValueError("Barycentric coordinates must contain three finite non-negative values.")
    total = sum(weights)
    if total <= 1.0e-12:
        raise ValueError("Barycentric coordinates cannot sum to zero.")
    return tuple(value / total for value in weights)


def _point3(value: Sequence[float]) -> tuple[float, float, float]:
    if len(value) < 3:
        raise ValueError("Surface attachment vertices require three coordinates.")
    point = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError("Surface attachment vertices must be finite.")
    return point


def _subtract(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(value: Sequence[float], message: str) -> tuple[float, float, float]:
    length = math.sqrt(sum(float(item) * float(item) for item in value))
    if length <= 1.0e-12:
        raise ValueError(message)
    return tuple(float(item) / length for item in value)


__all__ = ["SURFACE_ATTACHMENT_SCHEMA", "SurfaceAttachment", "create_surface_attachment", "update_surface_attachment"]
