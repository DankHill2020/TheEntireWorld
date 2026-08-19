"""Transactional topology operations for Tech Connector-native polygon meshes."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable, Sequence


Point3 = tuple[float, float, float]
Polygon = tuple[int, ...]


@dataclass(frozen=True)
class MeshTopology:
    vertices: tuple[Point3, ...]
    faces: tuple[Polygon, ...]

    @classmethod
    def from_data(cls, vertices: Iterable[Sequence[float]], faces: Iterable[Sequence[int]]) -> "MeshTopology":
        topology = cls(
            vertices=tuple(tuple(float(value) for value in point[:3]) for point in vertices),
            faces=tuple(tuple(int(index) for index in face) for face in faces),
        )
        topology.validate()
        return topology

    def validate(self) -> None:
        if not self.vertices:
            raise ValueError("A polygon mesh requires at least one vertex.")
        for face_index, face in enumerate(self.faces):
            if len(face) < 3:
                raise ValueError(f"Face {face_index} has fewer than three vertices.")
            if len(set(face)) < 3:
                raise ValueError(f"Face {face_index} is degenerate.")
            if min(face) < 0 or max(face) >= len(self.vertices):
                raise IndexError(f"Face {face_index} references a missing vertex.")


@dataclass(frozen=True)
class MeshEditResult:
    topology: MeshTopology
    operation: str
    created_vertices: tuple[int, ...] = ()
    created_faces: tuple[int, ...] = ()
    affected_faces: tuple[int, ...] = ()
    face_sources: tuple[int, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def split_edge_loop(
    topology: MeshTopology,
    edge: Sequence[int],
    *,
    divisions: int = 1,
) -> MeshEditResult:
    """Insert evenly spaced cuts through the complete quad ring containing ``edge``."""
    start = _edge(topology, edge)
    cuts = int(divisions)
    if cuts < 1 or cuts > 64:
        raise ValueError("Loop insertion divisions must be between 1 and 64.")

    opposite_graph: dict[tuple[int, int], set[tuple[int, int]]] = {}
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, face in enumerate(topology.faces):
        for offset, first in enumerate(face):
            key = _edge_key(first, face[(offset + 1) % len(face)])
            edge_faces.setdefault(key, []).append(face_index)
        if len(face) != 4:
            continue
        pairs = (
            (_edge_key(face[0], face[1]), _edge_key(face[2], face[3])),
            (_edge_key(face[1], face[2]), _edge_key(face[3], face[0])),
        )
        for first, second in pairs:
            opposite_graph.setdefault(first, set()).add(second)
            opposite_graph.setdefault(second, set()).add(first)
    if start not in edge_faces:
        raise ValueError("The selected vertices do not form a mesh edge.")
    if start not in opposite_graph:
        raise ValueError("Loop insertion requires an edge that belongs to a quadrilateral strip.")

    ring: set[tuple[int, int]] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in ring:
            continue
        ring.add(current)
        pending.extend(opposite_graph.get(current, ()) - ring)

    vertices = list(topology.vertices)
    cut_vertices: dict[tuple[int, int], tuple[int, ...]] = {}
    interpolation: dict[str, dict[str, object]] = {}
    for first, second in sorted(ring):
        created = []
        for cut in range(1, cuts + 1):
            amount = cut / float(cuts + 1)
            created_index = len(vertices)
            vertices.append(_lerp(topology.vertices[first], topology.vertices[second], amount))
            created.append(created_index)
            interpolation[str(created_index)] = {
                "sources": [first, second],
                "weights": [1.0 - amount, amount],
            }
        cut_vertices[(first, second)] = tuple(created)

    faces: list[Polygon] = []
    sources: list[int] = []
    created_faces: list[int] = []
    affected_faces: list[int] = []
    for face_index, face in enumerate(topology.faces):
        split = _split_quad_by_ring(face, ring, cut_vertices)
        if split is None:
            faces.append(face)
            sources.append(face_index)
            continue
        affected_faces.append(face_index)
        for polygon in split:
            created_faces.append(len(faces))
            faces.append(polygon)
            sources.append(face_index)

    result = MeshTopology.from_data(vertices, faces)
    return MeshEditResult(
        result,
        "modeling.split_edge_loop",
        created_vertices=tuple(index for values in cut_vertices.values() for index in values),
        created_faces=tuple(created_faces),
        affected_faces=tuple(affected_faces),
        face_sources=tuple(sources),
        metadata={
            "divisions": cuts,
            "ring_edges": [list(value) for value in sorted(ring)],
            "vertex_interpolation": interpolation,
        },
    )


def bevel_edges(
    topology: MeshTopology,
    edges: Iterable[Sequence[int]],
    *,
    width: float = 0.1,
) -> MeshEditResult:
    """Chamfer vertex-disjoint boundary or manifold edges with filled end caps."""
    selected = {_edge(topology, value) for value in edges}
    if not selected:
        raise ValueError("Bevel requires at least one selected edge.")
    amount = float(width)
    if amount <= 0.0:
        raise ValueError("Bevel width must be greater than zero.")
    selected_vertices = [vertex for edge_key in selected for vertex in edge_key]
    if len(set(selected_vertices)) != len(selected_vertices):
        raise ValueError("This bevel pass requires vertex-disjoint edges; bevel connected edges in separate passes.")

    uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {key: [] for key in selected}
    for face_index, face in enumerate(topology.faces):
        for offset, first in enumerate(face):
            second = face[(offset + 1) % len(face)]
            key = _edge_key(first, second)
            if key in uses:
                uses[key].append((face_index, first, second))
    missing = [key for key, value in uses.items() if not value]
    if missing:
        raise ValueError(f"Selected edge does not exist: {missing[0]}")
    non_manifold = [key for key, value in uses.items() if len(value) > 2]
    if non_manifold:
        raise ValueError(f"Cannot bevel non-manifold edge: {non_manifold[0]}")

    vertices = list(topology.vertices)
    replacements: dict[tuple[int, int, int], tuple[int, int]] = {}
    interpolation: dict[str, dict[str, object]] = {}
    side_vertices: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
    for edge_key, edge_uses in sorted(uses.items()):
        for face_index, first, second in edge_uses:
            face = topology.faces[face_index]
            edge_vector = _subtract(topology.vertices[second], topology.vertices[first])
            edge_length = _length(edge_vector)
            if edge_length <= 1.0e-10:
                raise ValueError("Cannot bevel a zero-length edge.")
            normal = _face_normal(topology, face)
            inward = _normalize(_cross(normal, _normalize(edge_vector)))
            midpoint = _scale(_add(topology.vertices[first], topology.vertices[second]), 0.5)
            toward_center = _subtract(_face_center(topology, face), midpoint)
            if _dot(inward, toward_center) < 0.0:
                inward = _scale(inward, -1.0)
            safe_width = min(amount, edge_length * 0.49)
            first_new = len(vertices)
            vertices.append(_add(topology.vertices[first], _scale(inward, safe_width)))
            second_new = len(vertices)
            vertices.append(_add(topology.vertices[second], _scale(inward, safe_width)))
            replacements[(face_index, first, second)] = (first_new, second_new)
            side_vertices.setdefault(edge_key, []).append((first, second, first_new, second_new))
            interpolation[str(first_new)] = {"sources": [first], "weights": [1.0]}
            interpolation[str(second_new)] = {"sources": [second], "weights": [1.0]}

    faces: list[Polygon] = []
    sources: list[int] = []
    affected_faces: set[int] = set()
    for face_index, face in enumerate(topology.faces):
        updated = list(face)
        for offset, first in enumerate(face):
            second = face[(offset + 1) % len(face)]
            replacement = replacements.get((face_index, first, second))
            if replacement:
                updated[offset] = replacement[0]
                updated[(offset + 1) % len(face)] = replacement[1]
                affected_faces.add(face_index)
        faces.append(tuple(updated))
        sources.append(face_index)

    created_faces: list[int] = []
    for edge_key, sides in sorted(side_vertices.items()):
        if len(sides) == 1:
            first, second, first_new, second_new = sides[0]
            additions = [(first, second, second_new, first_new)]
        else:
            first, second, first_a, second_a = sides[0]
            other_first, other_second, first_b_raw, second_b_raw = sides[1]
            first_b = first_b_raw if other_first == first else second_b_raw
            second_b = second_b_raw if other_second == second else first_b_raw
            additions = [
                (first_a, second_a, second_b, first_b),
                (first, first_b, first_a),
                (second, second_a, second_b),
            ]
        for polygon in additions:
            created_faces.append(len(faces))
            faces.append(polygon)
            sources.append(uses[edge_key][0][0])

    result = MeshTopology.from_data(vertices, faces)
    return MeshEditResult(
        result,
        "modeling.bevel_edges",
        created_vertices=tuple(range(len(topology.vertices), len(vertices))),
        created_faces=tuple(created_faces),
        affected_faces=tuple(sorted(affected_faces)),
        face_sources=tuple(sources),
        metadata={
            "width": amount,
            "segments": 1,
            "selected_edges": [list(value) for value in sorted(selected)],
            "vertex_interpolation": interpolation,
        },
    )


def extrude_faces(topology: MeshTopology, face_indices: Iterable[int], *, distance: float = 0.1) -> MeshEditResult:
    selected = _face_selection(topology, face_indices)
    if not selected:
        raise ValueError("Extrude requires at least one selected face.")

    edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    vertex_normals: dict[int, list[Point3]] = {}
    for face_index in selected:
        face = topology.faces[face_index]
        normal = _face_normal(topology, face)
        for vertex_index in face:
            vertex_normals.setdefault(vertex_index, []).append(normal)
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            edge_uses.setdefault(tuple(sorted((first, second))), []).append((face_index, first, second))

    vertices = list(topology.vertices)
    duplicates: dict[int, int] = {}
    for source_index in sorted(vertex_normals):
        normal = _normalize(_sum_points(vertex_normals[source_index]))
        point = topology.vertices[source_index]
        duplicates[source_index] = len(vertices)
        vertices.append(tuple(point[axis] + normal[axis] * float(distance) for axis in range(3)))

    faces = list(topology.faces)
    face_sources = list(range(len(faces)))
    for face_index in selected:
        faces[face_index] = tuple(duplicates[index] for index in topology.faces[face_index])

    created_faces: list[int] = []
    for uses in edge_uses.values():
        if len(uses) != 1:
            continue
        source_face, first, second = uses[0]
        created_faces.append(len(faces))
        faces.append((first, second, duplicates[second], duplicates[first]))
        face_sources.append(source_face)

    result = MeshTopology.from_data(vertices, faces)
    return MeshEditResult(
        result,
        "modeling.extrude_faces",
        created_vertices=tuple(duplicates.values()),
        created_faces=tuple(created_faces),
        affected_faces=tuple(sorted(selected)),
        face_sources=tuple(face_sources),
        metadata={
            "distance": float(distance),
            "region": True,
            "vertex_sources": {str(created): source for source, created in duplicates.items()},
        },
    )


def delete_faces(topology: MeshTopology, face_indices: Iterable[int]) -> MeshEditResult:
    selected = _face_selection(topology, face_indices)
    faces = [face for index, face in enumerate(topology.faces) if index not in selected]
    sources = [index for index in range(len(topology.faces)) if index not in selected]
    return MeshEditResult(
        MeshTopology.from_data(topology.vertices, faces),
        "modeling.delete_faces",
        affected_faces=tuple(sorted(selected)),
        face_sources=tuple(sources),
    )


def triangulate_faces(topology: MeshTopology, face_indices: Iterable[int] | None = None) -> MeshEditResult:
    selected = set(range(len(topology.faces))) if face_indices is None else _face_selection(topology, face_indices)
    faces: list[Polygon] = []
    sources: list[int] = []
    created: list[int] = []
    for face_index, face in enumerate(topology.faces):
        if face_index not in selected or len(face) == 3:
            faces.append(face)
            sources.append(face_index)
            continue
        for offset in range(1, len(face) - 1):
            created.append(len(faces))
            faces.append((face[0], face[offset], face[offset + 1]))
            sources.append(face_index)
    return MeshEditResult(
        MeshTopology.from_data(topology.vertices, faces),
        "modeling.triangulate_faces",
        created_faces=tuple(created),
        affected_faces=tuple(sorted(selected)),
        face_sources=tuple(sources),
    )


def merge_vertices(topology: MeshTopology, vertex_indices: Iterable[int], *, threshold: float = 1.0e-5) -> MeshEditResult:
    selected = sorted(set(int(value) for value in vertex_indices))
    if len(selected) < 2:
        raise ValueError("Merge requires at least two selected vertices.")
    if selected[0] < 0 or selected[-1] >= len(topology.vertices):
        raise IndexError("Merge selection references a missing vertex.")
    center = tuple(sum(topology.vertices[index][axis] for index in selected) / len(selected) for axis in range(3))
    anchor = selected[0]
    remap = {index: anchor for index in selected}
    vertices = list(topology.vertices)
    vertices[anchor] = center
    faces = []
    sources = []
    for face_index, face in enumerate(topology.faces):
        mapped = tuple(remap.get(index, index) for index in face)
        cleaned = _remove_adjacent_duplicates(mapped)
        if len(set(cleaned)) >= 3:
            faces.append(cleaned)
            sources.append(face_index)
    compact_vertices, compact_faces, compact_sources = _compact_vertices(vertices, faces)
    return MeshEditResult(
        MeshTopology.from_data(compact_vertices, compact_faces),
        "modeling.merge_vertices",
        affected_faces=tuple(index for index in range(len(topology.faces)) if any(v in remap for v in topology.faces[index])),
        face_sources=tuple(sources),
        metadata={
            "merged_count": len(selected),
            "threshold": float(threshold),
            "vertex_sources": {str(new): old for new, old in enumerate(compact_sources)},
        },
    )


def bridge_edge_loops(topology: MeshTopology, first_loop: Sequence[int], second_loop: Sequence[int]) -> MeshEditResult:
    first = tuple(int(value) for value in first_loop)
    second = tuple(int(value) for value in second_loop)
    if len(first) < 2 or len(first) != len(second):
        raise ValueError("Bridge requires two ordered edge loops with the same vertex count.")
    if min(first + second) < 0 or max(first + second) >= len(topology.vertices):
        raise IndexError("Bridge loop references a missing vertex.")
    faces = list(topology.faces)
    created = []
    for index, first_vertex in enumerate(first):
        next_index = (index + 1) % len(first)
        created.append(len(faces))
        faces.append((first_vertex, first[next_index], second[next_index], second[index]))
    sources = list(range(len(topology.faces))) + [-1] * len(created)
    return MeshEditResult(
        MeshTopology.from_data(topology.vertices, faces),
        "modeling.bridge_edge_loops",
        created_faces=tuple(created),
        face_sources=tuple(sources),
    )


def _face_selection(topology: MeshTopology, values: Iterable[int]) -> set[int]:
    selected = set(int(value) for value in values)
    if selected and (min(selected) < 0 or max(selected) >= len(topology.faces)):
        raise IndexError("Face selection references a missing face.")
    return selected


def _edge(topology: MeshTopology, value: Sequence[int]) -> tuple[int, int]:
    values = tuple(int(index) for index in value)
    if len(values) != 2 or values[0] == values[1]:
        raise ValueError("An edge must contain two different vertex indices.")
    if min(values) < 0 or max(values) >= len(topology.vertices):
        raise IndexError("Edge selection references a missing vertex.")
    return _edge_key(values[0], values[1])


def _edge_key(first: int, second: int) -> tuple[int, int]:
    return (first, second) if first < second else (second, first)


def _directed_cut_vertices(
    first: int,
    second: int,
    cut_vertices: dict[tuple[int, int], tuple[int, ...]],
) -> tuple[int, ...]:
    values = cut_vertices[_edge_key(first, second)]
    return values if first < second else tuple(reversed(values))


def _split_quad_by_ring(
    face: Polygon,
    ring: set[tuple[int, int]],
    cut_vertices: dict[tuple[int, int], tuple[int, ...]],
) -> list[Polygon] | None:
    if len(face) != 4:
        return None
    for offset in range(4):
        first, second = face[offset], face[(offset + 1) % 4]
        third, fourth = face[(offset + 2) % 4], face[(offset + 3) % 4]
        if _edge_key(first, second) not in ring or _edge_key(third, fourth) not in ring:
            continue
        first_cuts = _directed_cut_vertices(first, second, cut_vertices)
        opposite_cuts = _directed_cut_vertices(fourth, third, cut_vertices)
        first_chain = (first,) + first_cuts + (second,)
        opposite_chain = (fourth,) + opposite_cuts + (third,)
        return [
            (first_chain[index], first_chain[index + 1], opposite_chain[index + 1], opposite_chain[index])
            for index in range(len(first_chain) - 1)
        ]
    return None


def _face_normal(topology: MeshTopology, face: Polygon) -> Point3:
    origin = topology.vertices[face[0]]
    for index in range(1, len(face) - 1):
        first = _subtract(topology.vertices[face[index]], origin)
        second = _subtract(topology.vertices[face[index + 1]], origin)
        normal = _cross(first, second)
        if _length(normal) > 1.0e-10:
            return _normalize(normal)
    raise ValueError("Cannot extrude a zero-area face.")


def _subtract(first: Point3, second: Point3) -> Point3:
    return tuple(first[index] - second[index] for index in range(3))


def _add(first: Point3, second: Point3) -> Point3:
    return tuple(first[index] + second[index] for index in range(3))


def _scale(value: Point3, amount: float) -> Point3:
    return tuple(component * amount for component in value)


def _dot(first: Point3, second: Point3) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _lerp(first: Point3, second: Point3, amount: float) -> Point3:
    return tuple(first[index] + (second[index] - first[index]) * amount for index in range(3))


def _face_center(topology: MeshTopology, face: Polygon) -> Point3:
    return _scale(_sum_points(topology.vertices[index] for index in face), 1.0 / len(face))


def _cross(first: Point3, second: Point3) -> Point3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _length(value: Point3) -> float:
    return math.sqrt(sum(component * component for component in value))


def _normalize(value: Point3) -> Point3:
    length = _length(value)
    if length <= 1.0e-12:
        raise ValueError("Cannot normalize a zero-length vector.")
    return tuple(component / length for component in value)


def _sum_points(values: Iterable[Point3]) -> Point3:
    result = [0.0, 0.0, 0.0]
    for value in values:
        for index in range(3):
            result[index] += value[index]
    return tuple(result)


def _remove_adjacent_duplicates(face: Polygon) -> Polygon:
    result: list[int] = []
    for value in face:
        if not result or result[-1] != value:
            result.append(value)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return tuple(result)


def _compact_vertices(vertices: list[Point3], faces: list[Polygon]) -> tuple[list[Point3], list[Polygon], list[int]]:
    used = sorted({index for face in faces for index in face})
    remap = {old: new for new, old in enumerate(used)}
    return [vertices[index] for index in used], [tuple(remap[index] for index in face) for face in faces], used
