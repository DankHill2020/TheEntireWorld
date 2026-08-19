"""Paintable deformation influence maps and sim-to-render mesh blending."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Sequence


Vec3 = tuple[float, float, float]


@dataclass
class DeformationWeightMap:
    """Per-vertex influence where zero preserves upstream and one follows deformation."""

    name: str
    values: list[float]
    default_value: float = 0.0
    semantics: str = "upstream_to_deformed"
    revision: int = 0

    @classmethod
    def create(cls, name: str, vertex_count: int, *, default_value: float = 0.0) -> "DeformationWeightMap":
        default = _clamp(default_value)
        return cls(str(name), [default] * max(0, int(vertex_count)), default)

    def paint(
        self,
        vertices: Sequence[Sequence[float]],
        center: Sequence[float],
        radius: float,
        *,
        value: float = 1.0,
        strength: float = 1.0,
        hardness: float = 0.5,
        mode: str = "replace",
    ) -> list[int]:
        if len(vertices) != len(self.values):
            raise ValueError("Paint vertices and deformation map must have matching vertex counts.")
        radius_value = max(1.0e-9, float(radius))
        center_value = _vec3(center)
        target = _clamp(value)
        strength_value = _clamp(strength)
        hardness_value = _clamp(hardness)
        changed: list[int] = []
        for index, source in enumerate(vertices):
            point = _vec3(source)
            distance = math.dist(point, center_value)
            if distance > radius_value:
                continue
            normalized = distance / radius_value
            inner = hardness_value
            falloff = 1.0 if normalized <= inner else 1.0 - (normalized - inner) / max(1.0e-9, 1.0 - inner)
            amount = _smoothstep(_clamp(falloff)) * strength_value
            old = self.values[index]
            if mode == "replace":
                new = old + (target - old) * amount
            elif mode == "add":
                new = old + target * amount
            elif mode in {"subtract", "erase"}:
                new = old - target * amount
            elif mode == "scale":
                new = old * (1.0 + (target - 1.0) * amount)
            else:
                raise ValueError(f"Unknown deformation paint mode: {mode}")
            new = _clamp(new)
            if abs(new - old) > 1.0e-12:
                self.values[index] = new
                changed.append(index)
        if changed:
            self.revision += 1
        return changed

    def smooth(self, adjacency: Sequence[Iterable[int]], *, iterations: int = 1, strength: float = 0.5) -> None:
        if len(adjacency) != len(self.values):
            raise ValueError("Map smoothing adjacency must match the vertex count.")
        amount = _clamp(strength)
        for _iteration in range(max(0, int(iterations))):
            source = list(self.values)
            for index, neighbors in enumerate(adjacency):
                valid = [int(value) for value in neighbors if 0 <= int(value) < len(source)]
                if valid:
                    average = sum(source[value] for value in valid) / len(valid)
                    self.values[index] = _clamp(source[index] + (average - source[index]) * amount)
        if iterations and amount:
            self.revision += 1

    def invert(self) -> None:
        self.values = [1.0 - value for value in self.values]
        self.default_value = 1.0 - self.default_value
        self.revision += 1

    def to_dict(self) -> dict[str, Any]:
        sparse = {
            str(index): value
            for index, value in enumerate(self.values)
            if abs(value - self.default_value) > 1.0e-8
        }
        return {
            "schema": "tech_connector.deformation_weight_map.v1",
            "name": self.name,
            "vertex_count": len(self.values),
            "default_value": self.default_value,
            "semantics": self.semantics,
            "revision": self.revision,
            "sparse_values": sparse,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeformationWeightMap":
        if str(data.get("schema") or "") != "tech_connector.deformation_weight_map.v1":
            raise ValueError("Unsupported deformation weight map schema.")
        result = cls.create(
            str(data.get("name") or "influence"),
            int(data.get("vertex_count", 0)),
            default_value=float(data.get("default_value", 0.0)),
        )
        for key, value in dict(data.get("sparse_values") or {}).items():
            index = int(key)
            if 0 <= index < len(result.values):
                result.values[index] = _clamp(value)
        result.semantics = str(data.get("semantics") or "upstream_to_deformed")
        result.revision = int(data.get("revision", 0))
        return result


@dataclass(frozen=True)
class SimulationMeshBindingEntry:
    simulation_vertex_indices: tuple[int, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.simulation_vertex_indices or len(self.simulation_vertex_indices) != len(self.weights):
            raise ValueError("A simulation mesh binding needs matching indices and weights.")
        if abs(sum(float(value) for value in self.weights) - 1.0) > 1.0e-5:
            raise ValueError("Simulation mesh binding weights must sum to one.")


@dataclass(frozen=True)
class SimulationMeshBinding:
    render_mesh_id: str
    simulation_mesh_id: str
    entries: tuple[SimulationMeshBindingEntry, ...]
    method: str = "barycentric"


def sample_simulation_mesh(
    simulation_positions: Sequence[Sequence[float]],
    binding: SimulationMeshBinding,
) -> list[Vec3]:
    source = [_vec3(value) for value in simulation_positions]
    result: list[Vec3] = []
    for entry in binding.entries:
        if min(entry.simulation_vertex_indices) < 0 or max(entry.simulation_vertex_indices) >= len(source):
            raise IndexError("Simulation mesh binding references a missing vertex.")
        result.append(tuple(
            sum(source[index][axis] * weight for index, weight in zip(entry.simulation_vertex_indices, entry.weights))
            for axis in range(3)
        ))
    return result


def blend_deformation(
    upstream_positions: Sequence[Sequence[float]],
    deformed_positions: Sequence[Sequence[float]],
    influence_map: DeformationWeightMap,
) -> list[Vec3]:
    if len(upstream_positions) != len(deformed_positions) or len(upstream_positions) != len(influence_map.values):
        raise ValueError("Upstream, deformed, and influence-map vertex counts must match.")
    return [
        tuple(float(source[axis]) + (float(target[axis]) - float(source[axis])) * weight for axis in range(3))
        for source, target, weight in zip(upstream_positions, deformed_positions, influence_map.values)
    ]


def attach_deformation_map(
    rig_graph: Any,
    source_id: str,
    influence_map: DeformationWeightMap,
) -> str:
    """Attach an output blend map to any skin cluster or ordered deformer."""
    source = str(source_id)
    skins = getattr(rig_graph, "skins", {})
    deformers = getattr(rig_graph, "deformers", {})
    if source in skins:
        skins[source]["output_influence_map"] = influence_map.to_dict()
        skins[source]["map_semantics"] = "0 = upstream bind/input mesh, 1 = skin cluster output"
        return source
    if source in deformers:
        settings = deformers[source].setdefault("settings", {})
        settings["influence_map"] = influence_map.to_dict()
        settings["map_semantics"] = "0 = upstream mesh, 1 = deformer output"
        return source
    raise KeyError(f"Deformation-map source is not a skin cluster or deformer: {source}")


def _vec3(value: Sequence[float]) -> Vec3:
    if len(value) < 3:
        raise ValueError("A deformation position requires three values.")
    return (float(value[0]), float(value[1]), float(value[2]))


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)
