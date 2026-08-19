from __future__ import annotations

"""Deterministic, attribute-first procedural content graphs for TC scenes."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import time
from typing import Any, Iterable


PROCEDURAL_GRAPH_SCHEMA = "tc.procedural_graph.v1"
Vec3 = tuple[float, float, float]


def _vec3(value: Any, default: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return default
    return values[:3] if len(values) >= 3 else default


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unit_random(*parts: Any) -> float:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


@dataclass(frozen=True)
class ProceduralPoint:
    point_id: str
    position: Vec3
    rotation: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)
    attributes: dict[str, Any] = field(default_factory=dict)
    bounds_min: Vec3 = (0.0, 0.0, 0.0)
    bounds_max: Vec3 = (0.0, 0.0, 0.0)
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    density: float = 1.0
    steepness: float = 0.5
    seed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def replace_procedural_point(
    point: ProceduralPoint,
    *,
    position: Vec3 | None = None,
    rotation: Vec3 | None = None,
    scale: Vec3 | None = None,
    attributes: dict[str, Any] | None = None,
    density: float | None = None,
    steepness: float | None = None,
) -> ProceduralPoint:
    """Copy a point without dropping native PCG-compatible spatial properties."""
    return ProceduralPoint(
        point_id=point.point_id,
        position=point.position if position is None else position,
        rotation=point.rotation if rotation is None else rotation,
        scale=point.scale if scale is None else scale,
        attributes=deepcopy(point.attributes) if attributes is None else attributes,
        bounds_min=point.bounds_min,
        bounds_max=point.bounds_max,
        color=point.color,
        density=point.density if density is None else max(0.0, min(1.0, float(density))),
        steepness=point.steepness if steepness is None else max(0.0, min(1.0, float(steepness))),
        seed=point.seed,
    )


@dataclass(frozen=True)
class ProceduralInstance:
    instance_id: str
    asset: str
    position: Vec3
    rotation: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProceduralPayload:
    points: list[ProceduralPoint] = field(default_factory=list)
    instances: list[ProceduralInstance] = field(default_factory=list)
    meshes: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [point.to_dict() for point in self.points],
            "instances": [instance.to_dict() for instance in self.instances],
            "meshes": deepcopy(self.meshes),
            "metadata": deepcopy(self.metadata),
        }

    @property
    def fingerprint(self) -> str:
        return _digest(self.to_dict())


@dataclass
class ProceduralNode:
    node_id: str
    operation: str
    inputs: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProceduralGraph:
    name: str = "Procedural Graph"
    graph_id: str = "procedural_graph"
    seed: int = 0
    nodes: dict[str, ProceduralNode] = field(default_factory=dict)
    output_node: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(
        self,
        node_id: str,
        operation: str,
        *,
        inputs: Iterable[str] = (),
        parameters: dict[str, Any] | None = None,
        label: str = "",
    ) -> ProceduralNode:
        key = str(node_id).strip()
        if not key:
            raise ValueError("Procedural nodes require a stable node_id.")
        if key in self.nodes:
            raise ValueError(f"Procedural node already exists: {key}")
        node = ProceduralNode(
            node_id=key,
            operation=str(operation).strip().lower(),
            inputs=[str(item) for item in inputs],
            parameters=deepcopy(parameters or {}),
            label=str(label),
        )
        self.nodes[key] = node
        self.output_node = key
        return node

    def connect(self, source_node: str, destination_node: str) -> None:
        if source_node not in self.nodes or destination_node not in self.nodes:
            raise KeyError("Both procedural graph nodes must exist before connecting them.")
        if source_node not in self.nodes[destination_node].inputs:
            self.nodes[destination_node].inputs.append(source_node)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for node in self.nodes.values():
            if node.operation not in PROCEDURAL_OPERATIONS:
                errors.append(f"{node.node_id}: unsupported operation {node.operation}")
            for source in node.inputs:
                if source not in self.nodes:
                    errors.append(f"{node.node_id}: missing input {source}")
        try:
            _topological_order(self)
        except ValueError as exc:
            errors.append(str(exc))
        if self.output_node and self.output_node not in self.nodes:
            errors.append(f"Missing output node: {self.output_node}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROCEDURAL_GRAPH_SCHEMA,
            "name": self.name,
            "graph_id": self.graph_id,
            "seed": self.seed,
            "nodes": [self.nodes[key].to_dict() for key in sorted(self.nodes)],
            "output_node": self.output_node,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProceduralGraph":
        if str(data.get("schema") or "") != PROCEDURAL_GRAPH_SCHEMA:
            raise ValueError("Unsupported TC procedural graph schema.")
        graph = cls(
            name=str(data.get("name") or "Procedural Graph"),
            graph_id=str(data.get("graph_id") or "procedural_graph"),
            seed=int(data.get("seed") or 0),
            output_node=str(data.get("output_node") or ""),
            metadata=deepcopy(data.get("metadata") or {}),
        )
        for row in data.get("nodes") or []:
            if not isinstance(row, dict):
                continue
            node = ProceduralNode(
                node_id=str(row.get("node_id") or ""),
                operation=str(row.get("operation") or "").lower(),
                inputs=[str(item) for item in row.get("inputs") or []],
                parameters=deepcopy(row.get("parameters") or {}),
                enabled=bool(row.get("enabled", True)),
                label=str(row.get("label") or ""),
            )
            graph.nodes[node.node_id] = node
        return graph


@dataclass(frozen=True)
class ProceduralNodeDiagnostic:
    node_id: str
    operation: str
    elapsed_ms: float
    cache_hit: bool
    point_count: int
    instance_count: int
    fingerprint: str
    warnings: tuple[str, ...] = ()


@dataclass
class ProceduralCookResult:
    graph_id: str
    output_node: str
    payload: ProceduralPayload
    diagnostics: list[ProceduralNodeDiagnostic]
    graph_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "output_node": self.output_node,
            "payload": self.payload.to_dict(),
            "diagnostics": [asdict(row) for row in self.diagnostics],
            "graph_fingerprint": self.graph_fingerprint,
        }


def _topological_order(graph: ProceduralGraph) -> list[str]:
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise ValueError(f"Procedural graph cycle detected at {node_id}")
        visiting.add(node_id)
        for source in graph.nodes[node_id].inputs:
            if source in graph.nodes:
                visit(source)
        visiting.remove(node_id)
        visited.add(node_id)
        ordered.append(node_id)

    for key in sorted(graph.nodes):
        visit(key)
    return ordered


def _source_points(inputs: list[ProceduralPayload]) -> list[ProceduralPoint]:
    return [point for payload in inputs for point in payload.points]


def _source_instances(inputs: list[ProceduralPayload]) -> list[ProceduralInstance]:
    return [instance for payload in inputs for instance in payload.instances]


def _grid_points(node: ProceduralNode, _inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    count_x = max(0, int(node.parameters.get("count_x", 1)))
    count_z = max(0, int(node.parameters.get("count_z", 1)))
    spacing = _vec3(node.parameters.get("spacing"), (1.0, 0.0, 1.0))
    origin = _vec3(node.parameters.get("origin"))
    centered = bool(node.parameters.get("centered", True))
    points: list[ProceduralPoint] = []
    x_offset = (count_x - 1) * 0.5 if centered else 0.0
    z_offset = (count_z - 1) * 0.5 if centered else 0.0
    for x in range(count_x):
        for z in range(count_z):
            point_id = f"{node.node_id}:{x}:{z}"
            points.append(
                ProceduralPoint(
                    point_id=point_id,
                    position=(
                        origin[0] + (x - x_offset) * spacing[0],
                        origin[1],
                        origin[2] + (z - z_offset) * spacing[2],
                    ),
                    attributes={"grid_x": x, "grid_z": z, "seed": seed},
                    seed=seed,
                )
            )
    return ProceduralPayload(points=points)


def _scatter_bounds(node: ProceduralNode, _inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    count = max(0, int(node.parameters.get("count", 100)))
    minimum = _vec3(node.parameters.get("min"), (-1.0, 0.0, -1.0))
    maximum = _vec3(node.parameters.get("max"), (1.0, 0.0, 1.0))
    node_seed = int(node.parameters.get("seed", 0)) ^ seed
    points: list[ProceduralPoint] = []
    for index in range(count):
        position = tuple(
            minimum[axis] + (maximum[axis] - minimum[axis]) * _unit_random(node_seed, node.node_id, index, axis)
            for axis in range(3)
        )
        random_value = _unit_random(node_seed, node.node_id, index, "value")
        points.append(
            ProceduralPoint(
                point_id=f"{node.node_id}:{index}",
                position=position,
                attributes={"random": random_value, "seed": node_seed},
                density=1.0,
                seed=node_seed,
            )
        )
    return ProceduralPayload(points=points)


def _spline_sample(node: ProceduralNode, _inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    controls = [_vec3(row) for row in node.parameters.get("control_points") or []]
    count = max(0, int(node.parameters.get("count", 16)))
    if len(controls) < 2 or not count:
        return ProceduralPayload(metadata={"warning": "Spline sampling requires two controls and a positive count."})
    lengths = [math.dist(controls[index], controls[index + 1]) for index in range(len(controls) - 1)]
    total = sum(lengths)
    points: list[ProceduralPoint] = []
    for index in range(count):
        distance = total * (index / max(1, count - 1))
        segment = 0
        while segment < len(lengths) - 1 and distance > lengths[segment]:
            distance -= lengths[segment]
            segment += 1
        amount = distance / lengths[segment] if lengths[segment] else 0.0
        left, right = controls[segment], controls[segment + 1]
        position = tuple(left[axis] + (right[axis] - left[axis]) * amount for axis in range(3))
        tangent = tuple(right[axis] - left[axis] for axis in range(3))
        points.append(
            ProceduralPoint(
                point_id=f"{node.node_id}:{index}",
                position=position,
                attributes={"spline_u": index / max(1, count - 1), "tangent": tangent},
            )
        )
    return ProceduralPayload(points=points)


def _transform_points(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    translation = _vec3(node.parameters.get("translation"))
    rotation = _vec3(node.parameters.get("rotation"))
    scale = _vec3(node.parameters.get("scale"), (1.0, 1.0, 1.0))
    points = [
        replace_procedural_point(
            point,
            position=tuple(point.position[axis] * scale[axis] + translation[axis] for axis in range(3)),
            rotation=tuple(point.rotation[axis] + rotation[axis] for axis in range(3)),
            scale=tuple(point.scale[axis] * scale[axis] for axis in range(3)),
        )
        for point in _source_points(inputs)
    ]
    return ProceduralPayload(points=points, instances=_source_instances(inputs))


def _repeat_transform(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    iterations = max(0, int(node.parameters.get("iterations", 1)))
    offset = _vec3(node.parameters.get("offset"), (0.0, 1.0, 0.0))
    rotation_step = _vec3(node.parameters.get("rotation_step"))
    scale_step = _vec3(node.parameters.get("scale_step"), (1.0, 1.0, 1.0))
    points: list[ProceduralPoint] = []
    for iteration in range(iterations):
        for point in _source_points(inputs):
            scale = tuple(point.scale[axis] * (scale_step[axis] ** iteration) for axis in range(3))
            points.append(
                ProceduralPoint(
                    **{
                        **replace_procedural_point(
                            point,
                            position=tuple(point.position[axis] + offset[axis] * iteration for axis in range(3)),
                            rotation=tuple(point.rotation[axis] + rotation_step[axis] * iteration for axis in range(3)),
                            scale=scale,
                            attributes={**deepcopy(point.attributes), "iteration": iteration},
                        ).to_dict(),
                        "point_id": f"{point.point_id}:repeat:{iteration}",
                    }
                )
            )
    return ProceduralPayload(points=points)


def _noise_attribute(node: ProceduralNode, inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    name = str(node.parameters.get("attribute") or "noise")
    minimum = float(node.parameters.get("min", 0.0))
    maximum = float(node.parameters.get("max", 1.0))
    node_seed = int(node.parameters.get("seed", 0)) ^ seed
    points: list[ProceduralPoint] = []
    for point in _source_points(inputs):
        value = minimum + (maximum - minimum) * _unit_random(node_seed, point.point_id, point.position)
        points.append(replace_procedural_point(
            point,
            attributes={**deepcopy(point.attributes), name: value},
            density=value if name == "density" else None,
        ))
    return ProceduralPayload(points=points)


def _filter_attribute(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    name = str(node.parameters.get("attribute") or "density")
    comparison = str(node.parameters.get("comparison") or ">=")
    threshold = node.parameters.get("value", 0.5)

    def accepted(point: ProceduralPoint) -> bool:
        value = point.density if name == "density" else point.attributes.get(name, 0.0)
        operations = {
            ">=": lambda: value >= threshold,
            ">": lambda: value > threshold,
            "<=": lambda: value <= threshold,
            "<": lambda: value < threshold,
            "==": lambda: value == threshold,
            "!=": lambda: value != threshold,
        }
        try:
            return bool(operations.get(comparison, operations[">="])())
        except TypeError:
            return False

    return ProceduralPayload(points=[point for point in _source_points(inputs) if accepted(point)])


def _select_asset(node: ProceduralNode, inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    rows = node.parameters.get("assets") or []
    assets: list[tuple[str, float]] = []
    for row in rows:
        if isinstance(row, str):
            assets.append((row, 1.0))
        elif isinstance(row, dict) and row.get("asset"):
            assets.append((str(row["asset"]), max(0.0, float(row.get("weight", 1.0)))))
    total = sum(weight for _asset, weight in assets)
    if not assets or total <= 0.0:
        return ProceduralPayload(points=_source_points(inputs), metadata={"warning": "No weighted assets were supplied."})
    points: list[ProceduralPoint] = []
    for point in _source_points(inputs):
        pick = _unit_random(seed, node.node_id, point.point_id) * total
        selected = assets[-1][0]
        cursor = 0.0
        for asset, weight in assets:
            cursor += weight
            if pick <= cursor:
                selected = asset
                break
        points.append(replace_procedural_point(
            point,
            attributes={**deepcopy(point.attributes), "asset": selected},
        ))
    return ProceduralPayload(points=points)


def _instance_on_points(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    default_asset = str(node.parameters.get("asset") or "")
    instances: list[ProceduralInstance] = []
    for point in _source_points(inputs):
        asset = str(point.attributes.get("asset") or default_asset)
        if not asset:
            continue
        instances.append(
            ProceduralInstance(
                instance_id=f"{node.node_id}:{point.point_id}",
                asset=asset,
                position=point.position,
                rotation=point.rotation,
                scale=point.scale,
                attributes=deepcopy(point.attributes),
            )
        )
    return ProceduralPayload(points=_source_points(inputs), instances=instances)


def _heightfield_parameter(node: ProceduralNode):
    from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField

    value = node.parameters.get("heightfield")
    if isinstance(value, HeightField):
        return value
    if isinstance(value, dict):
        return HeightField.from_dict(value)
    raise ValueError(f"{node.node_id}: a serialized heightfield parameter is required")


def _project_heightfield(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_spatial_service import project_points_to_heightfield

    source = inputs[0] if inputs else ProceduralPayload()
    return project_points_to_heightfield(
        source,
        _heightfield_parameter(node),
        offset=float(node.parameters.get("offset", 0.0)),
    )


def _filter_slope(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_spatial_service import filter_points_by_slope

    source = inputs[0] if inputs else ProceduralPayload()
    return filter_points_by_slope(
        source,
        _heightfield_parameter(node),
        minimum=float(node.parameters.get("min_degrees", 0.0)),
        maximum=float(node.parameters.get("max_degrees", 90.0)),
    )


def _filter_heightfield_mask(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_spatial_service import filter_points_by_heightfield_mask

    source = inputs[0] if inputs else ProceduralPayload()
    return filter_points_by_heightfield_mask(
        source,
        _heightfield_parameter(node),
        str(node.parameters.get("attribute") or "mask"),
        minimum=float(node.parameters.get("min", 0.0)),
        maximum=float(node.parameters.get("max", 1.0)),
    )


def _filter_polygon(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_spatial_service import PolygonMask2D, filter_points_by_polygon

    polygons = tuple(
        tuple((float(point[0]), float(point[1])) for point in polygon)
        for polygon in node.parameters.get("polygons") or ()
    )
    mask = PolygonMask2D(polygons, str(node.parameters.get("operation") or "union"))
    return filter_points_by_polygon(inputs[0] if inputs else ProceduralPayload(), mask)


def _point_neighborhood(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_spatial_service import annotate_point_neighborhoods

    return annotate_point_neighborhoods(
        inputs[0] if inputs else ProceduralPayload(),
        float(node.parameters.get("radius", 1.0)),
    )


def _biome_scatter(node: ProceduralNode, inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_biome_service import BiomeDefinition, scatter_biome
    from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField

    heightfield = node.parameters.get("heightfield")
    if heightfield is None and inputs:
        heightfield = inputs[0].metadata.get("heightfield")
    biome = node.parameters.get("biome")
    if not isinstance(heightfield, dict) or not isinstance(biome, dict):
        raise ValueError(f"{node.node_id}: biome scatter requires serialized heightfield and biome data")
    definition = BiomeDefinition.from_dict({**biome, "seed": int(biome.get("seed", 0)) ^ seed})
    return scatter_biome(HeightField.from_dict(heightfield), definition)


def _hydraulic_erosion(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_biome_service import hydraulic_erode_heightfield
    from tech_connector.game_engine.authoring.procedural_spatial_service import HeightField

    heightfield_data = node.parameters.get("heightfield")
    if heightfield_data is None and inputs:
        heightfield_data = inputs[0].metadata.get("heightfield")
    if not isinstance(heightfield_data, dict):
        raise ValueError(f"{node.node_id}: hydraulic erosion requires a serialized heightfield")
    result = hydraulic_erode_heightfield(
        HeightField.from_dict(heightfield_data),
        iterations=int(node.parameters.get("iterations", 32)),
        rainfall=float(node.parameters.get("rainfall", 0.02)),
        evaporation=float(node.parameters.get("evaporation", 0.08)),
        flow_rate=float(node.parameters.get("flow_rate", 0.55)),
        sediment_capacity=float(node.parameters.get("sediment_capacity", 1.5)),
        erosion_rate=float(node.parameters.get("erosion_rate", 0.12)),
        deposition_rate=float(node.parameters.get("deposition_rate", 0.18)),
        river_threshold=float(node.parameters.get("river_threshold", 0.35)),
    )
    payload = deepcopy(inputs[0]) if inputs else ProceduralPayload()
    payload.metadata["heightfield"] = result.to_dict()
    payload.metadata["field_outputs"] = sorted(result.attributes)
    return payload


def _shape_grammar_spline(node: ProceduralNode, _inputs: list[ProceduralPayload], seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_layout_service import (
        ShapeGrammar,
        SplinePath,
        place_shape_grammar_on_spline,
    )

    path = SplinePath(
        tuple(tuple(float(axis) for axis in point)[:3] for point in node.parameters.get("control_points") or ()),
        bool(node.parameters.get("closed", False)),
    )
    grammar_data = dict(node.parameters.get("grammar") or {})
    grammar_data["seed"] = int(grammar_data.get("seed", 0)) ^ seed
    return place_shape_grammar_on_spline(path, ShapeGrammar.from_dict(grammar_data))


def _procedural_mesh(node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    from tech_connector.game_engine.authoring.procedural_mesh_service import evaluate_mesh_node

    return evaluate_mesh_node(node.operation, node.node_id, node.parameters, inputs)


def _merge(_node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    meshes: dict[str, dict[str, Any]] = {}
    for payload in inputs:
        for name, mesh in payload.meshes.items():
            key = name
            suffix = 2
            while key in meshes:
                key = f"{name}_{suffix}"
                suffix += 1
            meshes[key] = deepcopy(mesh)
    return ProceduralPayload(points=_source_points(inputs), instances=_source_instances(inputs), meshes=meshes)


def _passthrough(_node: ProceduralNode, inputs: list[ProceduralPayload], _seed: int) -> ProceduralPayload:
    return deepcopy(inputs[0]) if inputs else ProceduralPayload()


PROCEDURAL_OPERATIONS = {
    "grid_points": _grid_points,
    "scatter_bounds": _scatter_bounds,
    "spline_sample": _spline_sample,
    "transform_points": _transform_points,
    "repeat_transform": _repeat_transform,
    "noise_attribute": _noise_attribute,
    "filter_attribute": _filter_attribute,
    "select_asset": _select_asset,
    "instance_on_points": _instance_on_points,
    "project_heightfield": _project_heightfield,
    "filter_slope": _filter_slope,
    "filter_heightfield_mask": _filter_heightfield_mask,
    "filter_polygon": _filter_polygon,
    "point_neighborhood": _point_neighborhood,
    "biome_scatter": _biome_scatter,
    "terrain_hydraulic_erosion": _hydraulic_erosion,
    "shape_grammar_spline": _shape_grammar_spline,
    "mesh_cube": _procedural_mesh,
    "mesh_grid": _procedural_mesh,
    "mesh_transform": _procedural_mesh,
    "mesh_extrude_faces": _procedural_mesh,
    "mesh_triangulate": _procedural_mesh,
    "merge": _merge,
    "output": _passthrough,
}


class ProceduralGraphCooker:
    """Incremental graph evaluator with content-addressed per-node caching."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[str, ProceduralPayload]] = {}

    def clear(self, graph_id: str = "") -> None:
        if not graph_id:
            self._cache.clear()
            return
        for key in [key for key in self._cache if key[0] == graph_id]:
            self._cache.pop(key, None)

    def cook(self, graph: ProceduralGraph, *, output_node: str = "") -> ProceduralCookResult:
        errors = graph.validate()
        if errors:
            raise ValueError("; ".join(errors))
        output_key = str(output_node or graph.output_node or (_topological_order(graph)[-1] if graph.nodes else ""))
        if not output_key:
            return ProceduralCookResult(graph.graph_id, "", ProceduralPayload(), [], _digest(graph.to_dict()))
        values: dict[str, ProceduralPayload] = {}
        diagnostics: list[ProceduralNodeDiagnostic] = []
        for node_id in _topological_order(graph):
            node = graph.nodes[node_id]
            inputs = [values[source] for source in node.inputs]
            signature = _digest(
                {
                    "graph_seed": graph.seed,
                    "node": node.to_dict(),
                    "inputs": [payload.fingerprint for payload in inputs],
                }
            )
            started = time.perf_counter()
            cached = self._cache.get((graph.graph_id, node_id))
            cache_hit = bool(cached and cached[0] == signature)
            if cache_hit:
                payload = deepcopy(cached[1])
            elif not node.enabled:
                payload = _passthrough(node, inputs, graph.seed)
            else:
                payload = PROCEDURAL_OPERATIONS[node.operation](node, inputs, graph.seed)
                self._cache[(graph.graph_id, node_id)] = (signature, deepcopy(payload))
            warnings = tuple(
                str(value) for key, value in payload.metadata.items() if "warning" in str(key).lower()
            )
            diagnostics.append(
                ProceduralNodeDiagnostic(
                    node_id=node_id,
                    operation=node.operation,
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                    cache_hit=cache_hit,
                    point_count=len(payload.points),
                    instance_count=len(payload.instances),
                    fingerprint=payload.fingerprint,
                    warnings=warnings,
                )
            )
            values[node_id] = payload
        return ProceduralCookResult(
            graph_id=graph.graph_id,
            output_node=output_key,
            payload=deepcopy(values[output_key]),
            diagnostics=diagnostics,
            graph_fingerprint=_digest(graph.to_dict()),
        )


def create_scatter_graph(
    *,
    assets: Iterable[str | dict[str, Any]],
    count: int = 100,
    bounds_min: Vec3 = (-10.0, 0.0, -10.0),
    bounds_max: Vec3 = (10.0, 0.0, 10.0),
    seed: int = 0,
    density: float = 1.0,
) -> ProceduralGraph:
    """Create a useful editable scatter graph instead of a baked one-off result."""
    graph = ProceduralGraph(name="Scatter", graph_id=f"scatter_{seed}", seed=seed)
    graph.add_node(
        "scatter",
        "scatter_bounds",
        parameters={"count": count, "min": bounds_min, "max": bounds_max},
    )
    graph.add_node(
        "density",
        "noise_attribute",
        inputs=("scatter",),
        parameters={"attribute": "density", "min": 0.0, "max": 1.0},
    )
    graph.add_node(
        "density_filter",
        "filter_attribute",
        inputs=("density",),
        parameters={"attribute": "density", "comparison": "<=", "value": float(density)},
    )
    graph.add_node("assets", "select_asset", inputs=("density_filter",), parameters={"assets": list(assets)})
    graph.add_node("instances", "instance_on_points", inputs=("assets",))
    graph.add_node("output", "output", inputs=("instances",))
    return graph


def attach_procedural_graph(scene: Any, graph: ProceduralGraph, result: ProceduralCookResult | None = None) -> dict[str, Any]:
    """Attach editable graph intent and an optional cooked receipt to a TC scene."""
    metadata = scene.setdefault("metadata", {}) if isinstance(scene, dict) else scene.metadata
    procedural = metadata.setdefault("procedural_graphs", {})
    entry = {"graph": graph.to_dict()}
    if result is not None:
        entry["last_cook"] = {
            "graph_fingerprint": result.graph_fingerprint,
            "output_fingerprint": result.payload.fingerprint,
            "point_count": len(result.payload.points),
            "instance_count": len(result.payload.instances),
        }
    procedural[graph.graph_id] = entry
    return entry
