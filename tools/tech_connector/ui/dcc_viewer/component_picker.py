"""Pure screen-space mesh component picking helpers for the DCC viewport."""

from __future__ import annotations

import math
from typing import Iterable, Sequence


ScreenVertex = tuple[float, float, float]
Edge = tuple[int, int]


def unique_polygon_edges(faces: Iterable[Sequence[int]]) -> list[Edge]:
    edges: set[Edge] = set()
    for face in faces:
        values = [int(value) for value in face]
        for index, first in enumerate(values):
            second = values[(index + 1) % len(values)]
            edges.add((min(first, second), max(first, second)))
    return sorted(edges)


def nearest_vertex_index(
    vertices: Sequence[ScreenVertex], x: float, y: float, *, tolerance: float = 14.0, near_clip: float = 0.0,
) -> int | None:
    candidates = [
        ((vertex[0] - x) ** 2 + (vertex[1] - y) ** 2, index)
        for index, vertex in enumerate(vertices)
        if vertex[2] > near_clip
    ]
    if not candidates:
        return None
    distance_squared, index = min(candidates)
    return index if distance_squared <= float(tolerance) ** 2 else None


def _point_segment_distance_squared(px: float, py: float, first: ScreenVertex, second: ScreenVertex) -> float:
    dx, dy = second[0] - first[0], second[1] - first[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1.0e-12:
        return (px - first[0]) ** 2 + (py - first[1]) ** 2
    amount = max(0.0, min(1.0, ((px - first[0]) * dx + (py - first[1]) * dy) / length_squared))
    x, y = first[0] + amount * dx, first[1] + amount * dy
    return (px - x) ** 2 + (py - y) ** 2


def nearest_edge(
    vertices: Sequence[ScreenVertex], edges: Sequence[Edge], x: float, y: float, *, tolerance: float = 10.0, near_clip: float = 0.0,
) -> Edge | None:
    candidates: list[tuple[float, Edge]] = []
    for first_index, second_index in edges:
        if min(first_index, second_index) < 0 or max(first_index, second_index) >= len(vertices):
            continue
        first, second = vertices[first_index], vertices[second_index]
        if first[2] <= near_clip or second[2] <= near_clip:
            continue
        candidates.append((_point_segment_distance_squared(x, y, first, second), (first_index, second_index)))
    if not candidates:
        return None
    distance_squared, edge = min(candidates)
    return edge if distance_squared <= float(tolerance) ** 2 else None


def vertices_in_rectangle(
    vertices: Sequence[ScreenVertex], left: float, top: float, right: float, bottom: float, *, near_clip: float = 0.0,
) -> set[int]:
    minimum_x, maximum_x = sorted((float(left), float(right)))
    minimum_y, maximum_y = sorted((float(top), float(bottom)))
    return {
        index for index, vertex in enumerate(vertices)
        if vertex[2] > near_clip and minimum_x <= vertex[0] <= maximum_x and minimum_y <= vertex[1] <= maximum_y
    }


def faces_in_rectangle(
    vertices: Sequence[ScreenVertex], faces: Sequence[Sequence[int]], left: float, top: float, right: float, bottom: float,
    *, near_clip: float = 0.0,
) -> set[int]:
    enclosed = vertices_in_rectangle(vertices, left, top, right, bottom, near_clip=near_clip)
    return {
        face_index for face_index, face in enumerate(faces)
        if any(int(vertex_index) in enclosed for vertex_index in face)
    }


def edges_in_rectangle(
    vertices: Sequence[ScreenVertex], edges: Sequence[Edge], left: float, top: float, right: float, bottom: float,
    *, near_clip: float = 0.0,
) -> set[Edge]:
    enclosed = vertices_in_rectangle(vertices, left, top, right, bottom, near_clip=near_clip)
    return {edge for edge in edges if edge[0] in enclosed and edge[1] in enclosed}


def update_selection(selection: set, hits: Iterable, *, shift: bool = False, control: bool = False) -> None:
    hit_set = set(hits)
    if control:
        selection.symmetric_difference_update(hit_set)
    elif shift:
        selection.update(hit_set)
    else:
        selection.clear()
        selection.update(hit_set)
