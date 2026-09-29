from __future__ import annotations

"""Reusable node groups, persistent simulation sessions, and execution planning."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
from typing import Any, Iterable, Mapping

from .procedural_generation_service import (
    ProceduralCookResult, ProceduralGraph, ProceduralNode, ProceduralPayload, replace_procedural_point,
)


GPU_CAPABLE_OPERATIONS = frozenset({
    "grid_points", "scatter_bounds", "transform_points", "repeat_transform", "noise_attribute",
    "filter_attribute", "project_heightfield", "filter_slope", "field_set", "field_math", "field_map_domain",
    "mesh_transform", "mesh_compute_normals", "mesh_generate_uv", "mesh_smooth", "mesh_displace",
    "mesh_to_volume", "volume_to_mesh", "instance_on_points",
})


@dataclass(frozen=True)
class ProceduralNodeGroup:
    group_id: str
    graph: ProceduralGraph
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ("geometry",)
    exposed_parameters: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "tc.procedural_node_group.v1", "group_id": self.group_id,
                "graph": self.graph.to_dict(), "inputs": list(self.inputs), "outputs": list(self.outputs),
                "exposed_parameters": deepcopy(list(self.exposed_parameters))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProceduralNodeGroup":
        if str(data.get("schema") or "") != "tc.procedural_node_group.v1":
            raise ValueError("Unsupported procedural node-group schema.")
        return cls(str(data.get("group_id") or "node_group"), ProceduralGraph.from_dict(dict(data.get("graph") or {})),
                   tuple(str(value) for value in data.get("inputs") or ()),
                   tuple(str(value) for value in data.get("outputs") or ("geometry",)),
                   tuple(deepcopy(dict(value)) for value in data.get("exposed_parameters") or ()))


def instantiate_node_group(
    parent: ProceduralGraph, group: ProceduralNodeGroup, *, prefix: str,
    input_bindings: Mapping[str, str] | None = None, parameter_overrides: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Inline a reusable group while retaining stable names and dependency edges."""
    bindings = {str(key): str(value) for key, value in dict(input_bindings or {}).items()}
    overrides = dict(parameter_overrides or {}); mapping = {node_id: f"{prefix}.{node_id}" for node_id in group.graph.nodes}
    for node_id in [value for value in _ordered_nodes(group.graph)]:
        source = group.graph.nodes[node_id]
        parameters = deepcopy(source.parameters)
        for name, value in overrides.items():
            if name in parameters: parameters[name] = deepcopy(value)
        inputs = [mapping.get(value, bindings.get(value, value)) for value in source.inputs]
        parent.nodes[mapping[node_id]] = ProceduralNode(mapping[node_id], source.operation, inputs, parameters,
                                                        source.enabled, source.label, source.x, source.y)
    if group.graph.output_node:
        parent.output_node = mapping[group.graph.output_node]
    parent.metadata.setdefault("node_group_instances", []).append({"group_id": group.group_id, "prefix": prefix})
    return mapping


def _ordered_nodes(graph: ProceduralGraph) -> list[str]:
    ordered: list[str] = []; visiting: set[str] = set(); visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visited: return
        if node_id in visiting: raise ValueError(f"Procedural node group cycle detected at {node_id}")
        visiting.add(node_id)
        for source in graph.nodes[node_id].inputs:
            if source in graph.nodes: visit(source)
        visiting.remove(node_id); visited.add(node_id); ordered.append(node_id)
    for node_id in sorted(graph.nodes): visit(node_id)
    return ordered


@dataclass(frozen=True)
class ProceduralExecutionStage:
    index: int
    backend: str
    node_ids: tuple[str, ...]
    estimated_cost: float
    synchronization: bool


@dataclass(frozen=True)
class ProceduralExecutionPlan:
    graph_id: str
    requested_backend: str
    stages: tuple[ProceduralExecutionStage, ...]
    gpu_node_count: int
    cpu_node_count: int
    transfer_count: int

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def build_procedural_execution_plan(graph: ProceduralGraph, *, backend: str = "auto") -> ProceduralExecutionPlan:
    requested = str(backend or "auto").lower()
    if requested not in {"auto", "cpu", "gpu"}: raise ValueError("Backend must be auto, cpu, or gpu.")
    stages: list[ProceduralExecutionStage] = []; current_backend = ""; current_nodes: list[str] = []
    gpu_count = 0; cpu_count = 0
    for node_id in _ordered_nodes(graph):
        capable = graph.nodes[node_id].operation in GPU_CAPABLE_OPERATIONS
        selected = "cpu" if requested == "cpu" or not capable else "gpu"
        gpu_count += int(selected == "gpu"); cpu_count += int(selected == "cpu")
        if current_nodes and selected != current_backend:
            stages.append(ProceduralExecutionStage(len(stages), current_backend, tuple(current_nodes),
                                                   sum(_node_cost(graph.nodes[value].operation) for value in current_nodes), True))
            current_nodes = []
        current_backend = selected; current_nodes.append(node_id)
    if current_nodes:
        stages.append(ProceduralExecutionStage(len(stages), current_backend, tuple(current_nodes),
                                               sum(_node_cost(graph.nodes[value].operation) for value in current_nodes), False))
    return ProceduralExecutionPlan(graph.graph_id, requested, tuple(stages), gpu_count, cpu_count,
                                   max(0, len(stages) - 1))


def _node_cost(operation: str) -> float:
    if operation in {"mesh_boolean", "terrain_hydraulic_erosion"}: return 8.0
    if operation.startswith("mesh_") or operation in {"curve_to_mesh", "biome_scatter"}: return 3.0
    return 1.0


@dataclass
class ProceduralSimulationSession:
    """Persistent deterministic preview state for geometry and point simulation zones."""
    session_id: str
    frame: int = 0
    elapsed_seconds: float = 0.0
    point_velocities: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    mesh_velocities: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    last_payload: ProceduralPayload | None = None

    def reset(self) -> None:
        self.frame = 0; self.elapsed_seconds = 0.0; self.point_velocities.clear(); self.mesh_velocities.clear(); self.last_payload = None

    def step(
        self, result: ProceduralCookResult, *, delta_time: float = 1.0 / 60.0,
        gravity: tuple[float, float, float] = (0.0, -9.81, 0.0), damping: float = 0.02,
    ) -> ProceduralPayload:
        dt = max(0.0, min(0.25, float(delta_time))); retain = max(0.0, min(1.0, 1.0 - float(damping)))
        source = deepcopy(self.last_payload or result.payload); points = []
        for point in source.points:
            velocity = self.point_velocities.get(point.point_id, tuple(float(point.attributes.get("velocity", (0, 0, 0))[i]) for i in range(3)))
            velocity = tuple((velocity[i] + float(gravity[i]) * dt) * retain for i in range(3))
            position = tuple(point.position[i] + velocity[i] * dt for i in range(3))
            attributes = deepcopy(point.attributes); attributes["velocity"] = velocity
            points.append(replace_procedural_point(point, position=position, attributes=attributes)); self.point_velocities[point.point_id] = velocity
        source.points = points
        for mesh_name, data in source.meshes.items():
            vertices = [tuple(float(v) for v in point[:3]) for point in data.get("vertices") or ()]
            velocities = self.mesh_velocities.get(mesh_name, [(0.0, 0.0, 0.0)] * len(vertices))
            if len(velocities) != len(vertices): velocities = [(0.0, 0.0, 0.0)] * len(vertices)
            updated_velocity = [tuple((velocity[i] + float(gravity[i]) * dt) * retain for i in range(3)) for velocity in velocities]
            data["vertices"] = [[point[i] + updated_velocity[index][i] * dt for i in range(3)] for index, point in enumerate(vertices)]
            self.mesh_velocities[mesh_name] = updated_velocity
        self.frame += 1; self.elapsed_seconds += dt
        source.metadata["simulation"] = {"session_id": self.session_id, "frame": self.frame,
                                         "elapsed_seconds": self.elapsed_seconds, "delta_time": dt}
        self.last_payload = deepcopy(source); return source


__all__ = ["GPU_CAPABLE_OPERATIONS", "ProceduralExecutionPlan", "ProceduralExecutionStage",
           "ProceduralNodeGroup", "ProceduralSimulationSession", "build_procedural_execution_plan",
           "instantiate_node_group"]
