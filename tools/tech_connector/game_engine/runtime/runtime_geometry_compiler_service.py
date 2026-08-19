"""Deterministic surfel and meshlet compilers for TC runtime geometry."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Sequence

import numpy as np


POINT_PROXY_SCHEMA = "tech_connector.point_runtime_proxy.v1"
VIRTUAL_MESH_SCHEMA = "tech_connector.virtualized_hard_surface.v1"


def compile_point_runtime_proxy(
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    output_path: str | os.PathLike[str],
    *,
    face_material_ids: Sequence[int] | None = None,
    materials: Sequence[dict[str, Any]] = (),
    page_size: int = 512,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    points, triangles, source_faces = _validated_triangles(vertices, faces)
    _check_cancel(cancel_event)
    material_ids = _triangle_material_ids(faces, source_faces, face_material_ids)
    positions = points[triangles].mean(axis=1).astype(np.float32)
    edges_a = points[triangles[:, 1]] - points[triangles[:, 0]]
    edges_b = points[triangles[:, 2]] - points[triangles[:, 0]]
    cross = np.cross(edges_a, edges_b)
    lengths = np.linalg.norm(cross, axis=1)
    if np.any(lengths <= 1.0e-12):
        raise ValueError("Point proxy cannot compile degenerate triangles.")
    normals = (cross / lengths[:, None]).astype(np.float32)
    radii = np.sqrt((lengths * 0.5) / math.pi).astype(np.float32)
    pbr = np.asarray([_material_channels(materials, int(material_id)) for material_id in material_ids], dtype=np.float32)
    order = _morton_order(positions)
    positions, normals, radii, material_ids, source_faces, pbr = (
        value[order] for value in (positions, normals, radii, material_ids, source_faces, pbr)
    )
    pages = _pages_for_points(positions, max(32, int(page_size)))
    manifest = {
        "schema": POINT_PROXY_SCHEMA,
        "surfel_count": len(positions),
        "page_count": len(pages),
        "page_size": max(32, int(page_size)),
        "material_count": len(materials),
        "payload": ["position", "normal", "radius", "base_color", "roughness", "metalness", "emission", "opacity", "material_id", "source_primitive_id"],
        "pages": pages,
        "mesh_fallback_required": True,
    }
    _atomic_npz(
        output_path,
        manifest,
        positions=positions,
        normals=normals,
        radii=radii,
        material_ids=material_ids.astype(np.uint32),
        source_face_ids=source_faces.astype(np.uint32),
        pbr=pbr,
    )
    manifest["output_path"] = str(Path(output_path).expanduser().resolve())
    manifest["output_bytes"] = Path(manifest["output_path"]).stat().st_size
    return manifest


def compile_virtualized_hard_surface(
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    output_path: str | os.PathLike[str],
    *,
    max_vertices: int = 64,
    max_triangles: int = 126,
    meshlets_per_page: int = 32,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    points, triangles, source_faces = _validated_triangles(vertices, faces)
    vertex_limit = max(3, min(256, int(max_vertices)))
    triangle_limit = max(1, min(512, int(max_triangles)))
    meshlets: list[dict[str, Any]] = []
    current_triangles: list[tuple[int, int, int]] = []
    current_sources: list[int] = []
    current_vertices: dict[int, int] = {}

    def flush() -> None:
        if not current_triangles:
            return
        global_ids = np.asarray(list(current_vertices), dtype=np.uint32)
        local_triangles = np.asarray([
            tuple(current_vertices[int(vertex)] for vertex in triangle)
            for triangle in current_triangles
        ], dtype=np.uint16)
        meshlet_points = points[global_ids]
        center = meshlet_points.mean(axis=0)
        radius = float(np.linalg.norm(meshlet_points - center, axis=1).max(initial=0.0))
        tri_points = points[np.asarray(current_triangles, dtype=np.int64)]
        normals = np.cross(tri_points[:, 1] - tri_points[:, 0], tri_points[:, 2] - tri_points[:, 0])
        normals /= np.maximum(1.0e-12, np.linalg.norm(normals, axis=1))[:, None]
        cone_axis = normals.mean(axis=0)
        cone_axis /= max(1.0e-12, float(np.linalg.norm(cone_axis)))
        cone_cutoff = float(np.min(normals @ cone_axis))
        meshlets.append({
            "global_vertex_ids": global_ids,
            "triangles": local_triangles,
            "source_face_ids": np.asarray(current_sources, dtype=np.uint32),
            "center": center.astype(np.float32),
            "radius": radius,
            "cone_axis": cone_axis.astype(np.float32),
            "cone_cutoff": cone_cutoff,
        })
        current_triangles.clear()
        current_sources.clear()
        current_vertices.clear()

    for triangle, source_face in zip(triangles, source_faces):
        _check_cancel(cancel_event)
        additions = sum(int(vertex) not in current_vertices for vertex in triangle)
        if current_triangles and (len(current_triangles) >= triangle_limit or len(current_vertices) + additions > vertex_limit):
            flush()
        for vertex in triangle:
            current_vertices.setdefault(int(vertex), len(current_vertices))
        current_triangles.append(tuple(int(value) for value in triangle))
        current_sources.append(int(source_face))
    flush()

    vertex_offsets = [0]
    triangle_offsets = [0]
    global_ids = []
    local_triangles = []
    source_ids = []
    bounds = []
    cones = []
    for meshlet in meshlets:
        global_ids.extend(meshlet["global_vertex_ids"])
        local_triangles.extend(meshlet["triangles"].reshape(-1))
        source_ids.extend(meshlet["source_face_ids"])
        vertex_offsets.append(len(global_ids))
        triangle_offsets.append(len(source_ids))
        bounds.append([*meshlet["center"], meshlet["radius"]])
        cones.append([*meshlet["cone_axis"], meshlet["cone_cutoff"]])
    pages = [
        {"page": page, "meshlet_start": start, "meshlet_count": min(meshlets_per_page, len(meshlets) - start)}
        for page, start in enumerate(range(0, len(meshlets), max(1, int(meshlets_per_page))))
    ]
    hierarchy = _meshlet_hierarchy(np.asarray(bounds, dtype=np.float32))
    manifest = {
        "schema": VIRTUAL_MESH_SCHEMA,
        "source_vertex_count": len(points),
        "source_triangle_count": len(triangles),
        "meshlet_count": len(meshlets),
        "page_count": len(pages),
        "max_vertices": vertex_limit,
        "max_triangles": triangle_limit,
        "pages": pages,
        "hierarchy": hierarchy,
        "source_mapping": "exact_triangle_ids",
        "mesh_fallback_required": True,
    }
    _atomic_npz(
        output_path,
        manifest,
        positions=points.astype(np.float32),
        meshlet_vertex_offsets=np.asarray(vertex_offsets, dtype=np.uint32),
        meshlet_triangle_offsets=np.asarray(triangle_offsets, dtype=np.uint32),
        meshlet_global_vertex_ids=np.asarray(global_ids, dtype=np.uint32),
        meshlet_local_triangles=np.asarray(local_triangles, dtype=np.uint16),
        source_face_ids=np.asarray(source_ids, dtype=np.uint32),
        meshlet_bounds=np.asarray(bounds, dtype=np.float32),
        meshlet_cones=np.asarray(cones, dtype=np.float32),
    )
    manifest["output_path"] = str(Path(output_path).expanduser().resolve())
    manifest["output_bytes"] = Path(manifest["output_path"]).stat().st_size
    return manifest


def _validated_triangles(vertices, faces):
    points = np.asarray(vertices, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.all(np.isfinite(points)):
        raise ValueError("Runtime geometry requires finite Nx3 vertices.")
    triangles = []
    source_faces = []
    for face_index, face in enumerate(faces):
        polygon = tuple(int(value) for value in face)
        if len(polygon) < 3 or any(index < 0 or index >= len(points) for index in polygon):
            raise ValueError(f"Runtime geometry face {face_index} is invalid.")
        for offset in range(1, len(polygon) - 1):
            triangles.append((polygon[0], polygon[offset], polygon[offset + 1]))
            source_faces.append(face_index)
    if not triangles:
        raise ValueError("Runtime geometry requires at least one triangle.")
    return points, np.asarray(triangles, dtype=np.int64), np.asarray(source_faces, dtype=np.int64)


def _triangle_material_ids(faces, source_faces, face_material_ids):
    source = list(face_material_ids or ())
    if source and len(source) != len(faces):
        raise ValueError("face_material_ids must match the polygon face count.")
    return np.asarray([int(source[index]) if source else 0 for index in source_faces], dtype=np.int64)


def _material_channels(materials, material_id):
    material = dict(materials[material_id]) if 0 <= material_id < len(materials) else {}
    color = list(material.get("base_color") or (0.8, 0.8, 0.8, 1.0))
    while len(color) < 4:
        color.append(1.0)
    emission = list(material.get("emission_color") or (0.0, 0.0, 0.0))
    while len(emission) < 3:
        emission.append(0.0)
    return [*color[:3], float(material.get("roughness", 0.5)), float(material.get("metallic", 0.0)), *emission[:3], float(material.get("opacity", color[3]))]


def _morton_order(positions):
    minimum = positions.min(axis=0)
    span = np.maximum(1.0e-9, positions.max(axis=0) - minimum)
    quantized = np.clip(((positions - minimum) / span * 1023.0).astype(np.uint32), 0, 1023)
    codes = np.zeros(len(positions), dtype=np.uint64)
    for bit in range(10):
        codes |= ((quantized[:, 0] >> bit) & 1).astype(np.uint64) << (3 * bit)
        codes |= ((quantized[:, 1] >> bit) & 1).astype(np.uint64) << (3 * bit + 1)
        codes |= ((quantized[:, 2] >> bit) & 1).astype(np.uint64) << (3 * bit + 2)
    return np.argsort(codes, kind="stable")


def _pages_for_points(positions, page_size):
    pages = []
    for page, start in enumerate(range(0, len(positions), page_size)):
        points = positions[start:start + page_size]
        pages.append({"page": page, "start": start, "count": len(points), "bounds_min": points.min(axis=0).tolist(), "bounds_max": points.max(axis=0).tolist()})
    return pages


def _meshlet_hierarchy(bounds):
    if not len(bounds):
        return []
    nodes = [{"level": 0, "start": index, "count": 1, "center": row[:3].tolist(), "radius": float(row[3])} for index, row in enumerate(bounds)]
    current = list(range(len(nodes)))
    level = 1
    while len(current) > 1:
        next_level = []
        for offset in range(0, len(current), 4):
            children = current[offset:offset + 4]
            child_rows = [nodes[index] for index in children]
            centers = np.asarray([row["center"] for row in child_rows], dtype=np.float64)
            center = centers.mean(axis=0)
            radius = max(float(np.linalg.norm(np.asarray(row["center"]) - center)) + float(row["radius"]) for row in child_rows)
            nodes.append({"level": level, "children": children, "center": center.tolist(), "radius": radius})
            next_level.append(len(nodes) - 1)
        current = next_level
        level += 1
    return nodes


def _atomic_npz(path, manifest, **arrays):
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(dir=str(output.parent), prefix=output.name + ".", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            np.savez_compressed(temporary, manifest=np.frombuffer(json.dumps(manifest, separators=(",", ":")).encode("utf-8"), dtype=np.uint8), **arrays)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, output)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()


def _check_cancel(event):
    if event is not None and event.is_set():
        raise RuntimeError("Runtime geometry compilation canceled.")


__all__ = ["POINT_PROXY_SCHEMA", "VIRTUAL_MESH_SCHEMA", "compile_point_runtime_proxy", "compile_virtualized_hard_surface"]
