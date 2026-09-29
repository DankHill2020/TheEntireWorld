from __future__ import annotations

"""Domain-aware fields, curve conversion, and advanced procedural mesh operators."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

from .procedural_generation_service import ProceduralPayload
from .procedural_mesh_service import join_meshes, mesh_from_data, mesh_to_data
from .tc_mesh_modeling_service import MeshTopology


GEOMETRY_DOMAINS = ("point", "edge", "face", "corner", "spline", "instance")
FIELD_TYPES = ("bool", "int", "float", "vector", "color", "string")


@dataclass(frozen=True)
class GeometryField:
    name: str
    domain: str
    data_type: str
    values: tuple[Any, ...]

    def validate(self, element_count: int) -> None:
        if self.domain not in GEOMETRY_DOMAINS:
            raise ValueError(f"Unsupported geometry domain: {self.domain}")
        if self.data_type not in FIELD_TYPES:
            raise ValueError(f"Unsupported field type: {self.data_type}")
        if len(self.values) not in {1, int(element_count)}:
            raise ValueError(f"Field {self.name} expects one value or {element_count} {self.domain} values.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"values": list(self.values)}


def mesh_edges(mesh: MeshTopology) -> tuple[tuple[int, int], ...]:
    return tuple(sorted({tuple(sorted((face[index], face[(index + 1) % len(face)])))
                         for face in mesh.faces for index in range(len(face))}))


def domain_size(mesh: MeshTopology, domain: str) -> int:
    return {
        "point": len(mesh.vertices), "edge": len(mesh_edges(mesh)), "face": len(mesh.faces),
        "corner": sum(len(face) for face in mesh.faces),
    }.get(str(domain), 0)


def _first_mesh(inputs: list[ProceduralPayload]) -> tuple[str, dict[str, Any], MeshTopology]:
    for payload in inputs:
        if payload.meshes:
            name = sorted(payload.meshes)[0]; data = deepcopy(payload.meshes[name])
            return name, data, mesh_from_data(data)
    raise ValueError("This node requires an upstream mesh.")


def _face_normal(mesh: MeshTopology, face: tuple[int, ...]) -> tuple[float, float, float]:
    a, b, c = (mesh.vertices[index] for index in face[:3])
    ab = tuple(b[i] - a[i] for i in range(3)); ac = tuple(c[i] - a[i] for i in range(3))
    normal = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
    length = math.sqrt(sum(value * value for value in normal)) or 1.0
    return tuple(value / length for value in normal)


def _curve_points(node_id: str, operation: str, parameters: dict[str, Any]) -> ProceduralPayload:
    if operation == "curve_line":
        start = tuple(float(v) for v in parameters.get("start", (0, 0, 0)))
        end = tuple(float(v) for v in parameters.get("end", (0, 1, 0)))
        count = max(2, min(4096, int(parameters.get("points", 2))))
        points = [tuple(start[axis] + (end[axis] - start[axis]) * index / (count - 1) for axis in range(3))
                  for index in range(count)]
        cyclic = False
    else:
        radius = max(1.0e-6, float(parameters.get("radius", 1.0)))
        count = max(3, min(4096, int(parameters.get("points", 32))))
        points = [(math.cos(index / count * math.tau) * radius, 0.0,
                   math.sin(index / count * math.tau) * radius) for index in range(count)]
        cyclic = True
    return ProceduralPayload(metadata={"curves": {node_id: {"points": points, "cyclic": cyclic}}})


def _curve_to_mesh(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    curve = next((curve for payload in inputs for curve in dict(payload.metadata.get("curves") or {}).values()), None)
    if not curve:
        raise ValueError("Curve to Mesh requires an upstream curve.")
    path = [tuple(float(v) for v in point[:3]) for point in curve.get("points") or ()]
    if len(path) < 2:
        raise ValueError("Curve to Mesh requires at least two curve points.")
    sides = max(3, min(128, int(parameters.get("profile_resolution", 8))))
    radius = max(1.0e-6, float(parameters.get("radius", 0.1)))
    vertices: list[tuple[float, float, float]] = []
    # Stable world-up profile; suitable for roads, cables and authored paths without twist surprises.
    for point in path:
        vertices.extend((point[0] + math.cos(side / sides * math.tau) * radius,
                         point[1] + math.sin(side / sides * math.tau) * radius,
                         point[2]) for side in range(sides))
    segments = len(path) if curve.get("cyclic") else len(path) - 1
    faces = []
    for segment in range(segments):
        following = (segment + 1) % len(path)
        for side in range(sides):
            next_side = (side + 1) % sides
            faces.append((segment * sides + side, segment * sides + next_side,
                          following * sides + next_side, following * sides + side))
    mesh = MeshTopology.from_data(vertices, faces)
    return ProceduralPayload(meshes={node_id: mesh_to_data(mesh)}, metadata={"active_mesh": node_id})


def _set_field(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs)
    domain = str(parameters.get("domain") or "point"); field_name = str(parameters.get("name") or "value")
    count = domain_size(mesh, domain)
    values = parameters.get("values")
    if values is None:
        values = [deepcopy(parameters.get("value", 0.0))]
    field = GeometryField(field_name, domain, str(parameters.get("data_type") or "float"), tuple(values))
    field.validate(count)
    data.setdefault("attributes", {}).setdefault(domain, {})[field_name] = field.to_dict()
    return ProceduralPayload(meshes={str(parameters.get("mesh_name") or name or node_id): data},
                             metadata={"active_mesh": name, "field": field.to_dict()})


def _field_math(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs); domain = str(parameters.get("domain") or "point")
    source = str(parameters.get("source") or "value"); target = str(parameters.get("target") or source)
    field = dict(data.get("attributes", {}).get(domain, {}).get(source) or {})
    if not field:
        raise ValueError(f"Missing {domain} field: {source}")
    count = domain_size(mesh, domain); values = list(field.get("values") or ())
    if len(values) == 1: values *= count
    amount = float(parameters.get("value", 1.0)); operation = str(parameters.get("operation") or "multiply")
    functions = {"add": lambda value: value + amount, "subtract": lambda value: value - amount,
                 "multiply": lambda value: value * amount, "divide": lambda value: value / amount if amount else 0.0,
                 "min": lambda value: min(value, amount), "max": lambda value: max(value, amount)}
    if operation not in functions: raise ValueError(f"Unsupported field math operation: {operation}")
    result = [functions[operation](float(value)) for value in values]
    data.setdefault("attributes", {}).setdefault(domain, {})[target] = GeometryField(target, domain, "float", tuple(result)).to_dict()
    return ProceduralPayload(meshes={name or node_id: data}, metadata={"active_mesh": name, "field": target})


def _normals(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs); face_normals = [_face_normal(mesh, face) for face in mesh.faces]
    point_normals = [[0.0, 0.0, 0.0] for _ in mesh.vertices]
    for face, normal in zip(mesh.faces, face_normals):
        for index in face:
            for axis in range(3): point_normals[index][axis] += normal[axis]
    normalized = []
    for normal in point_normals:
        length = math.sqrt(sum(v * v for v in normal)) or 1.0; normalized.append([v / length for v in normal])
    attributes = data.setdefault("attributes", {})
    attributes.setdefault("face", {})["normal"] = GeometryField("normal", "face", "vector", tuple(face_normals)).to_dict()
    attributes.setdefault("point", {})["normal"] = GeometryField("normal", "point", "vector", tuple(normalized)).to_dict()
    return ProceduralPayload(meshes={name or node_id: data}, metadata={"active_mesh": name})


def _generate_uv(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs); axis = str(parameters.get("projection") or "xz")
    pairs = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}; left, right = pairs.get(axis, (0, 2))
    minimum = [min(point[component] for point in mesh.vertices) for component in (left, right)]
    maximum = [max(point[component] for point in mesh.vertices) for component in (left, right)]
    extent = [max(1.0e-8, maximum[i] - minimum[i]) for i in range(2)]
    uv = [[(point[left] - minimum[0]) / extent[0], (point[right] - minimum[1]) / extent[1]] for point in mesh.vertices]
    data.setdefault("attributes", {}).setdefault("point", {})["uv"] = GeometryField("uv", "point", "vector", tuple(uv)).to_dict()
    return ProceduralPayload(meshes={name or node_id: data}, metadata={"active_mesh": name, "uv_projection": axis})


def _map_field_domain(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs); source_domain = str(parameters.get("source_domain") or "point")
    target_domain = str(parameters.get("target_domain") or "face"); source_name = str(parameters.get("source") or "value")
    target_name = str(parameters.get("target") or source_name)
    field = dict(data.get("attributes", {}).get(source_domain, {}).get(source_name) or {})
    values = list(field.get("values") or ())
    if not values: raise ValueError(f"Missing {source_domain} field: {source_name}")
    if len(values) == 1: values *= domain_size(mesh, source_domain)
    if source_domain == "point" and target_domain == "face":
        mapped = [sum(float(values[index]) for index in face) / len(face) for face in mesh.faces]
    elif source_domain == "face" and target_domain == "point":
        accum = [[] for _ in mesh.vertices]
        for face_index, face in enumerate(mesh.faces):
            for vertex in face: accum[vertex].append(float(values[face_index]))
        mapped = [sum(row) / len(row) if row else 0.0 for row in accum]
    elif source_domain == target_domain:
        mapped = values
    else:
        raise ValueError(f"Domain mapping {source_domain} -> {target_domain} is not implemented.")
    result = GeometryField(target_name, target_domain, str(field.get("data_type") or "float"), tuple(mapped)); result.validate(domain_size(mesh, target_domain))
    data.setdefault("attributes", {}).setdefault(target_domain, {})[target_name] = result.to_dict()
    return ProceduralPayload(meshes={name or node_id: data}, metadata={"active_mesh": name, "field": target_name})


def _smooth_or_displace(node_id: str, operation: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    name, data, mesh = _first_mesh(inputs); vertices = [tuple(point) for point in mesh.vertices]
    if operation == "mesh_smooth":
        factor = max(0.0, min(1.0, float(parameters.get("factor", 0.5))))
        adjacency = [set() for _ in vertices]
        for first, second in mesh_edges(mesh): adjacency[first].add(second); adjacency[second].add(first)
        for _ in range(max(1, min(32, int(parameters.get("iterations", 1))))):
            vertices = [tuple(point[axis] * (1.0 - factor) +
                              (sum(vertices[other][axis] for other in adjacency[index]) / len(adjacency[index]) if adjacency[index] else point[axis]) * factor
                              for axis in range(3)) for index, point in enumerate(vertices)]
    else:
        normals_data = dict(data.get("attributes", {}).get("point", {}).get("normal") or {})
        if not normals_data:
            normal_payload = _normals(node_id, {}, inputs); data = next(iter(normal_payload.meshes.values()))
            normals_data = data["attributes"]["point"]["normal"]
        normals = list(normals_data.get("values") or ()); amount = float(parameters.get("distance", 0.1))
        field_name = str(parameters.get("field") or ""); weights = list(data.get("attributes", {}).get("point", {}).get(field_name, {}).get("values") or ()) if field_name else [1.0]
        if len(weights) == 1: weights *= len(vertices)
        if len(weights) != len(vertices): raise ValueError("Displacement field must match the point domain.")
        vertices = [tuple(point[axis] + float(normals[index][axis]) * amount * float(weights[index]) for axis in range(3))
                    for index, point in enumerate(vertices)]
    updated = mesh_to_data(MeshTopology.from_data(vertices, mesh.faces)); updated["attributes"] = deepcopy(data.get("attributes") or {})
    return ProceduralPayload(meshes={name or node_id: updated}, metadata={"active_mesh": name, "operation": operation})


def _voxel_remesh(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    _name, _data, mesh = _first_mesh(inputs); voxel = max(1.0e-6, float(parameters.get("voxel_size", 0.1)))
    vertices: list[tuple[float, float, float]] = []; lookup: dict[tuple[int, int, int], int] = {}; remap: dict[int, int] = {}
    for index, point in enumerate(mesh.vertices):
        cell = tuple(round(value / voxel) for value in point)
        if cell not in lookup:
            lookup[cell] = len(vertices); vertices.append(tuple(value * voxel for value in cell))
        remap[index] = lookup[cell]
    faces = []
    for face in mesh.faces:
        mapped = tuple(dict.fromkeys(remap[index] for index in face))
        if len(mapped) >= 3: faces.append(mapped)
    if not faces: raise ValueError("Voxel size collapsed all mesh faces; choose a smaller voxel size.")
    result = MeshTopology.from_data(vertices, faces)
    return ProceduralPayload(meshes={node_id: mesh_to_data(result)}, metadata={"active_mesh": node_id, "voxel_size": voxel})


def _mesh_to_volume(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    _name, _data, mesh = _first_mesh(inputs); resolution = max(4, min(64, int(parameters.get("resolution", 16))))
    lower = [min(point[axis] for point in mesh.vertices) for axis in range(3)]; upper = [max(point[axis] for point in mesh.vertices) for axis in range(3)]
    values = []
    for z in range(resolution):
        for y in range(resolution):
            for x in range(resolution):
                point = tuple(lower[axis] + (upper[axis] - lower[axis]) * coordinate / (resolution - 1)
                              for axis, coordinate in enumerate((x, y, z)))
                distance = min(math.sqrt(sum((point[axis] - vertex[axis]) ** 2 for axis in range(3))) for vertex in mesh.vertices)
                inside = all(lower[axis] < point[axis] < upper[axis] for axis in range(3))
                values.append(-distance if inside else distance)
    return ProceduralPayload(metadata={"volumes": {node_id: {"schema": "tc.sdf_volume.v1", "resolution": [resolution] * 3,
        "bounds_min": lower, "bounds_max": upper, "values": values}}})


def _volume_to_mesh(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    volume = next((value for payload in inputs for value in dict(payload.metadata.get("volumes") or {}).values()), None)
    if not volume: raise ValueError("Volume to Mesh requires an upstream volume.")
    lower, upper = volume["bounds_min"], volume["bounds_max"]
    from .procedural_mesh_service import create_cube_mesh, transform_mesh
    size = tuple(float(upper[i]) - float(lower[i]) for i in range(3)); center = tuple((float(upper[i]) + float(lower[i])) * .5 for i in range(3))
    mesh = transform_mesh(create_cube_mesh(size), translation=center)
    return ProceduralPayload(meshes={node_id: mesh_to_data(mesh)}, metadata={"active_mesh": node_id,
        "warning_volume_preview": "Bounding surface preview; target-native meshing should use the stored SDF."})


def _boolean(node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload]) -> ProceduralPayload:
    meshes = [mesh_from_data(data) for payload in inputs for data in payload.meshes.values()]
    if len(meshes) < 2: raise ValueError("Mesh Boolean requires at least two upstream meshes.")
    operation = str(parameters.get("operation") or "union")
    if operation == "union":
        result = join_meshes(meshes); warning = ""
    elif operation == "intersection":
        mins = [[min(point[axis] for point in mesh.vertices) for axis in range(3)] for mesh in meshes]
        maxs = [[max(point[axis] for point in mesh.vertices) for axis in range(3)] for mesh in meshes]
        lower = [max(row[axis] for row in mins) for axis in range(3)]; upper = [min(row[axis] for row in maxs) for axis in range(3)]
        if any(lower[axis] >= upper[axis] for axis in range(3)): raise ValueError("Boolean intersection is empty.")
        from .procedural_mesh_service import create_cube_mesh, transform_mesh
        size = tuple(upper[i] - lower[i] for i in range(3)); center = tuple((upper[i] + lower[i]) * .5 for i in range(3))
        result = transform_mesh(create_cube_mesh(size), translation=center); warning = "AABB preview intersection; use a target-native exact boolean when exporting."
    else:
        result = meshes[0]; warning = "Difference is retained as a non-destructive target-native boolean and previewed with the source mesh."
    return ProceduralPayload(meshes={node_id: mesh_to_data(result)}, metadata={"active_mesh": node_id, "boolean_operation": operation,
        **({"warning_boolean_preview": warning} if warning else {})})


def evaluate_advanced_geometry_node(
    operation: str, node_id: str, parameters: dict[str, Any], inputs: list[ProceduralPayload],
) -> ProceduralPayload:
    if operation in {"curve_line", "curve_circle"}: return _curve_points(node_id, operation, parameters)
    if operation == "curve_to_mesh": return _curve_to_mesh(node_id, parameters, inputs)
    if operation == "field_set": return _set_field(node_id, parameters, inputs)
    if operation == "field_math": return _field_math(node_id, parameters, inputs)
    if operation == "field_map_domain": return _map_field_domain(node_id, parameters, inputs)
    if operation == "mesh_compute_normals": return _normals(node_id, parameters, inputs)
    if operation == "mesh_generate_uv": return _generate_uv(node_id, parameters, inputs)
    if operation == "mesh_boolean": return _boolean(node_id, parameters, inputs)
    if operation in {"mesh_smooth", "mesh_displace"}: return _smooth_or_displace(node_id, operation, parameters, inputs)
    if operation == "mesh_voxel_remesh": return _voxel_remesh(node_id, parameters, inputs)
    if operation == "mesh_to_volume": return _mesh_to_volume(node_id, parameters, inputs)
    if operation == "volume_to_mesh": return _volume_to_mesh(node_id, parameters, inputs)
    raise ValueError(f"Unsupported advanced geometry operation: {operation}")


__all__ = ["FIELD_TYPES", "GEOMETRY_DOMAINS", "GeometryField", "domain_size", "evaluate_advanced_geometry_node", "mesh_edges"]
