"""Backend-neutral triangle BVH used by TC simulation collision stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


Vec3 = tuple[float, float, float]
Bounds = tuple[float, float, float, float, float, float]
Triangle = tuple[int, int, int]


@dataclass
class TriangleBvhNode:
    bounds: Bounds
    left: int = -1
    right: int = -1
    triangles: tuple[int, ...] = ()

    @property
    def leaf(self) -> bool:
        return self.left < 0 and self.right < 0


@dataclass
class TriangleBvhQuery:
    triangle_indices: list[int]
    visited_nodes: int
    rejected_nodes: int
    total_triangles: int

    @property
    def candidate_ratio(self) -> float:
        return len(self.triangle_indices) / max(1, self.total_triangles)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "candidate_triangles": len(self.triangle_indices),
            "total_triangles": self.total_triangles,
            "visited_nodes": self.visited_nodes,
            "rejected_nodes": self.rejected_nodes,
            "candidate_ratio": self.candidate_ratio,
        }


@dataclass
class TriangleBvh:
    vertices: list[Vec3]
    triangles: list[Triangle]
    nodes: list[TriangleBvhNode] = field(default_factory=list)
    leaf_size: int = 8

    @classmethod
    def build(
        cls,
        vertices: Iterable[Sequence[float]],
        faces: Iterable[Sequence[int]],
        *,
        leaf_size: int = 8,
    ) -> "TriangleBvh":
        points = [tuple(float(value) for value in point[:3]) for point in vertices]
        triangles = _triangulate(faces)
        if not points or not triangles:
            raise ValueError("Triangle BVH construction requires vertices and polygon faces.")
        if any(min(face) < 0 or max(face) >= len(points) for face in triangles):
            raise IndexError("Triangle BVH topology references a missing vertex.")
        bvh = cls(points, triangles, leaf_size=max(2, int(leaf_size)))
        bvh._build_node(list(range(len(triangles))))
        return bvh

    def query_sphere(self, center: Sequence[float], radius: float) -> TriangleBvhQuery:
        point = tuple(float(value) for value in center[:3])
        amount = max(0.0, float(radius))
        candidates: list[int] = []
        visited = 0
        rejected = 0
        pending = [0] if self.nodes else []
        while pending:
            node_index = pending.pop()
            node = self.nodes[node_index]
            visited += 1
            if not _sphere_overlaps_bounds(point, amount, node.bounds):
                rejected += 1
                continue
            if node.leaf:
                candidates.extend(node.triangles)
            else:
                if node.left >= 0:
                    pending.append(node.left)
                if node.right >= 0:
                    pending.append(node.right)
        return TriangleBvhQuery(sorted(set(candidates)), visited, rejected, len(self.triangles))

    def refit(self, vertices: Iterable[Sequence[float]]) -> None:
        points = [tuple(float(value) for value in point[:3]) for point in vertices]
        if len(points) != len(self.vertices):
            raise ValueError("BVH refit requires unchanged vertex topology.")
        self.vertices = points
        if self.nodes:
            self._refit_node(0)

    def diagnostics(self) -> dict[str, int | float]:
        leaves = [node for node in self.nodes if node.leaf]
        depths = []
        pending = [(0, 1)] if self.nodes else []
        while pending:
            node_index, depth = pending.pop()
            node = self.nodes[node_index]
            if node.leaf:
                depths.append(depth)
                continue
            if node.left >= 0:
                pending.append((node.left, depth + 1))
            if node.right >= 0:
                pending.append((node.right, depth + 1))
        return {
            "triangle_count": len(self.triangles),
            "node_count": len(self.nodes),
            "leaf_count": len(leaves),
            "maximum_depth": max(depths, default=0),
            "average_leaf_triangles": (
                sum(len(node.triangles) for node in leaves) / max(1, len(leaves))
            ),
        }

    def _build_node(self, triangle_indices: list[int]) -> int:
        node_index = len(self.nodes)
        bounds = _bounds_for_triangles(self.vertices, self.triangles, triangle_indices)
        self.nodes.append(TriangleBvhNode(bounds))
        if len(triangle_indices) <= self.leaf_size:
            self.nodes[node_index].triangles = tuple(sorted(triangle_indices))
            return node_index
        centroid_bounds = _centroid_bounds(self.vertices, self.triangles, triangle_indices)
        extents = [centroid_bounds[index + 3] - centroid_bounds[index] for index in range(3)]
        axis = max(range(3), key=extents.__getitem__)
        ordered = sorted(
            triangle_indices,
            key=lambda triangle_index: _triangle_centroid(
                self.vertices, self.triangles[triangle_index]
            )[axis],
        )
        midpoint = len(ordered) // 2
        if midpoint <= 0 or midpoint >= len(ordered):
            self.nodes[node_index].triangles = tuple(sorted(triangle_indices))
            return node_index
        left = self._build_node(ordered[:midpoint])
        right = self._build_node(ordered[midpoint:])
        self.nodes[node_index].left = left
        self.nodes[node_index].right = right
        return node_index

    def _refit_node(self, node_index: int) -> Bounds:
        node = self.nodes[node_index]
        if node.leaf:
            node.bounds = _bounds_for_triangles(self.vertices, self.triangles, list(node.triangles))
            return node.bounds
        child_bounds = []
        if node.left >= 0:
            child_bounds.append(self._refit_node(node.left))
        if node.right >= 0:
            child_bounds.append(self._refit_node(node.right))
        node.bounds = _merge_bounds(child_bounds)
        return node.bounds


def _triangulate(faces: Iterable[Sequence[int]]) -> list[Triangle]:
    result: list[Triangle] = []
    for raw_face in faces:
        face = tuple(int(value) for value in raw_face)
        if len(face) < 3:
            continue
        result.extend((face[0], face[index], face[index + 1]) for index in range(1, len(face) - 1))
    return result


def _triangle_bounds(vertices: list[Vec3], triangle: Triangle) -> Bounds:
    points = [vertices[index] for index in triangle]
    return (
        min(point[0] for point in points), min(point[1] for point in points), min(point[2] for point in points),
        max(point[0] for point in points), max(point[1] for point in points), max(point[2] for point in points),
    )


def _bounds_for_triangles(
    vertices: list[Vec3], triangles: list[Triangle], triangle_indices: list[int]
) -> Bounds:
    return _merge_bounds([_triangle_bounds(vertices, triangles[index]) for index in triangle_indices])


def _merge_bounds(bounds: list[Bounds]) -> Bounds:
    if not bounds:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return (
        min(value[0] for value in bounds), min(value[1] for value in bounds), min(value[2] for value in bounds),
        max(value[3] for value in bounds), max(value[4] for value in bounds), max(value[5] for value in bounds),
    )


def _triangle_centroid(vertices: list[Vec3], triangle: Triangle) -> Vec3:
    points = [vertices[index] for index in triangle]
    return tuple(sum(point[axis] for point in points) / 3.0 for axis in range(3))


def _centroid_bounds(
    vertices: list[Vec3], triangles: list[Triangle], triangle_indices: list[int]
) -> Bounds:
    points = [_triangle_centroid(vertices, triangles[index]) for index in triangle_indices]
    return (
        min(point[0] for point in points), min(point[1] for point in points), min(point[2] for point in points),
        max(point[0] for point in points), max(point[1] for point in points), max(point[2] for point in points),
    )


def _sphere_overlaps_bounds(center: Vec3, radius: float, bounds: Bounds) -> bool:
    distance_squared = 0.0
    for axis in range(3):
        value = center[axis]
        minimum, maximum = bounds[axis], bounds[axis + 3]
        if value < minimum:
            distance_squared += (minimum - value) ** 2
        elif value > maximum:
            distance_squared += (value - maximum) ** 2
    return distance_squared <= radius * radius
