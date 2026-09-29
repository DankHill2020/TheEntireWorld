from __future__ import annotations

"""Procedural mesh primitives and non-destructive TC topology operators."""

from copy import deepcopy
import math
from typing import Any

from tech_connector.game_engine.authoring.procedural_generation_service import ProceduralPayload
from tech_connector.game_engine.authoring.tc_mesh_modeling_service import (
    MeshTopology, bevel_edges, delete_faces, extrude_faces, merge_vertices, triangulate_faces,
)


def mesh_to_data(mesh: MeshTopology) -> dict[str, Any]:
    return {
        "schema": "tc.procedural_mesh.v1",
        "vertices": [list(point) for point in mesh.vertices],
        "faces": [list(face) for face in mesh.faces],
    }


def mesh_from_data(data: dict[str, Any]) -> MeshTopology:
    return MeshTopology.from_data(data.get("vertices") or (), data.get("faces") or ())


def create_cube_mesh(size: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> MeshTopology:
    sx, sy, sz = (float(value) * 0.5 for value in size)
    vertices = (
        (-sx, -sy, -sz), (sx, -sy, -sz), (sx, -sy, sz), (-sx, -sy, sz),
        (-sx, sy, -sz), (sx, sy, -sz), (sx, sy, sz), (-sx, sy, sz),
    )
    faces = (
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    )
    return MeshTopology.from_data(vertices, faces)


def create_grid_mesh(width: float = 1.0, depth: float = 1.0, segments_x: int = 1, segments_z: int = 1) -> MeshTopology:
    segments_x, segments_z = int(segments_x), int(segments_z)
    if segments_x < 1 or segments_z < 1:
        raise ValueError("Procedural grids require at least one segment per axis.")
    vertices = [
        ((x / segments_x - 0.5) * float(width), 0.0, (z / segments_z - 0.5) * float(depth))
        for z in range(segments_z + 1)
        for x in range(segments_x + 1)
    ]
    stride = segments_x + 1
    faces = []
    for z in range(segments_z):
        for x in range(segments_x):
            first = z * stride + x
            faces.append((first, first + 1, first + stride + 1, first + stride))
    return MeshTopology.from_data(vertices, faces)


def create_cylinder_mesh(radius: float = 0.5, depth: float = 1.0, segments: int = 32) -> MeshTopology:
    segments = max(3, min(512, int(segments))); radius = max(1.0e-6, float(radius)); half = float(depth) * 0.5
    vertices = [(math.cos(index / segments * math.tau) * radius, y, math.sin(index / segments * math.tau) * radius)
                for y in (-half, half) for index in range(segments)]
    faces = [tuple(reversed(range(segments))), tuple(range(segments, segments * 2))]
    faces.extend((index, (index + 1) % segments, (index + 1) % segments + segments, index + segments)
                 for index in range(segments))
    return MeshTopology.from_data(vertices, faces)


def create_uv_sphere_mesh(radius: float = 0.5, segments: int = 32, rings: int = 16) -> MeshTopology:
    segments, rings = max(3, min(512, int(segments))), max(2, min(256, int(rings)))
    radius = max(1.0e-6, float(radius)); vertices = [(0.0, radius, 0.0)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        vertices.extend((math.sin(phi) * math.cos(index / segments * math.tau) * radius,
                         math.cos(phi) * radius,
                         math.sin(phi) * math.sin(index / segments * math.tau) * radius) for index in range(segments))
    bottom = len(vertices); vertices.append((0.0, -radius, 0.0)); faces = []
    faces.extend((0, 1 + index, 1 + (index + 1) % segments) for index in range(segments))
    for ring in range(rings - 2):
        start = 1 + ring * segments; next_start = start + segments
        faces.extend((start + index, next_start + index, next_start + (index + 1) % segments, start + (index + 1) % segments)
                     for index in range(segments))
    last = 1 + (rings - 2) * segments
    faces.extend((last + index, bottom, last + (index + 1) % segments) for index in range(segments))
    return MeshTopology.from_data(vertices, faces)


def join_meshes(meshes: list[MeshTopology]) -> MeshTopology:
    if not meshes:
        raise ValueError("Join Geometry requires at least one mesh.")
    vertices = []; faces = []
    for mesh in meshes:
        offset = len(vertices); vertices.extend(mesh.vertices)
        faces.extend(tuple(index + offset for index in face) for face in mesh.faces)
    return MeshTopology.from_data(vertices, faces)


def subdivide_mesh(mesh: MeshTopology, levels: int = 1) -> MeshTopology:
    result = mesh
    for _ in range(max(0, min(4, int(levels)))):
        vertices = list(result.vertices); faces = []; edge_points: dict[tuple[int, int], int] = {}
        def midpoint(a: int, b: int) -> int:
            key = tuple(sorted((a, b)))
            if key not in edge_points:
                pa, pb = vertices[a], vertices[b]; edge_points[key] = len(vertices)
                vertices.append(tuple((pa[axis] + pb[axis]) * 0.5 for axis in range(3)))
            return edge_points[key]
        for face in result.faces:
            center = tuple(sum(result.vertices[index][axis] for index in face) / len(face) for axis in range(3))
            center_index = len(vertices); vertices.append(center)
            mids = [midpoint(face[index], face[(index + 1) % len(face)]) for index in range(len(face))]
            for index, vertex in enumerate(face): faces.append((vertex, mids[index], center_index, mids[index - 1]))
        result = MeshTopology.from_data(vertices, faces)
    return result


def transform_mesh(
    mesh: MeshTopology,
    *,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> MeshTopology:
    return MeshTopology.from_data(
        (
            tuple(point[axis] * float(scale[axis]) + float(translation[axis]) for axis in range(3))
            for point in mesh.vertices
        ),
        mesh.faces,
    )


def _input_mesh(inputs: list[ProceduralPayload], requested: str = "") -> tuple[str, MeshTopology]:
    for payload in inputs:
        if requested and requested in payload.meshes:
            return requested, mesh_from_data(payload.meshes[requested])
        if payload.meshes:
            name = sorted(payload.meshes)[0]
            return name, mesh_from_data(payload.meshes[name])
    raise ValueError("Procedural mesh operator requires an upstream mesh.")


def evaluate_mesh_node(operation: str, node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name = str(parameters.get("name") or node_id)
    metadata: dict[str, Any] = {"operation": operation}
    if operation == "mesh_cube":
        mesh = create_cube_mesh(tuple(parameters.get("size") or (1, 1, 1)))
    elif operation == "mesh_grid":
        mesh = create_grid_mesh(
            float(parameters.get("width", 1.0)), float(parameters.get("depth", 1.0)),
            int(parameters.get("segments_x", 1)), int(parameters.get("segments_z", 1)),
        )
    elif operation == "mesh_cylinder":
        mesh = create_cylinder_mesh(float(parameters.get("radius", 0.5)), float(parameters.get("depth", 1.0)), int(parameters.get("segments", 32)))
    elif operation == "mesh_uv_sphere":
        mesh = create_uv_sphere_mesh(float(parameters.get("radius", 0.5)), int(parameters.get("segments", 32)), int(parameters.get("rings", 16)))
    elif operation == "mesh_join":
        mesh = join_meshes([mesh_from_data(data) for payload in inputs for data in payload.meshes.values()])
    else:
        source_name, mesh = _input_mesh(inputs, str(parameters.get("mesh") or ""))
        name = str(parameters.get("name") or source_name)
        if operation == "mesh_transform":
            mesh = transform_mesh(
                mesh,
                translation=tuple(parameters.get("translation") or (0, 0, 0)),
                scale=tuple(parameters.get("scale") or (1, 1, 1)),
            )
        elif operation == "mesh_extrude_faces":
            result = extrude_faces(mesh, parameters.get("faces") or range(len(mesh.faces)), distance=float(parameters.get("distance", 0.1)))
            mesh = result.topology
            metadata["edit_receipt"] = {
                "created_vertices": result.created_vertices,
                "created_faces": result.created_faces,
                "affected_faces": result.affected_faces,
            }
        elif operation == "mesh_triangulate":
            result = triangulate_faces(mesh, parameters.get("faces"))
            mesh = result.topology
            metadata["edit_receipt"] = {"created_faces": result.created_faces}
        elif operation == "mesh_subdivide":
            mesh = subdivide_mesh(mesh, int(parameters.get("levels", 1)))
        elif operation == "mesh_bevel_edges":
            edges = parameters.get("edges")
            if not edges:
                # The modeling kernel bevels a vertex-disjoint edge set per pass. Pick a
                # deterministic maximal set so the default node is immediately usable.
                candidates = sorted({tuple(sorted((face[index], face[(index + 1) % len(face)])))
                                     for face in mesh.faces for index in range(len(face))})
                used: set[int] = set(); edges = []
                for edge in candidates:
                    if edge[0] not in used and edge[1] not in used:
                        edges.append(edge); used.update(edge)
            result = bevel_edges(mesh, edges, width=float(parameters.get("width", 0.05))); mesh = result.topology
            metadata["edit_receipt"] = {"created_vertices": result.created_vertices, "created_faces": result.created_faces}
        elif operation == "mesh_delete_faces":
            result = delete_faces(mesh, parameters.get("faces") or ()); mesh = result.topology
            metadata["edit_receipt"] = {"affected_faces": result.affected_faces}
        elif operation == "mesh_weld":
            result = merge_vertices(mesh, parameters.get("vertices") or range(len(mesh.vertices)), threshold=float(parameters.get("threshold", 1.0e-5)))
            mesh = result.topology; metadata["edit_receipt"] = dict(result.metadata)
        else:
            raise ValueError(f"Unsupported procedural mesh operation: {operation}")
    data = mesh_to_data(mesh)
    data["metadata"] = deepcopy(metadata)
    return ProceduralPayload(meshes={name: data}, metadata={"active_mesh": name})
