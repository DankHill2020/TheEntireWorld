from __future__ import annotations

"""Partition, prioritize, and stream deterministic procedural graph outputs."""

from dataclasses import asdict, dataclass, field
import hashlib
import math
from typing import Any, Iterable

from tech_connector.game_engine.authoring.procedural_generation_service import (
    ProceduralCookResult,
    ProceduralInstance,
)


Vec3 = tuple[float, float, float]


def _vec3(value: Any, default: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    try:
        rows = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return default
    return rows[:3] if len(rows) >= 3 else default


def _normalized(value: Vec3) -> Vec3:
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1e-8:
        return (0.0, 0.0, 0.0)
    return tuple(component / length for component in value)


@dataclass(frozen=True)
class ProceduralGenerationSource:
    source_id: str
    position: Vec3
    forward: Vec3 = (0.0, 0.0, 1.0)
    radius_scale: float = 1.0
    importance: float = 1.0


@dataclass(frozen=True)
class ProceduralRuntimeProfile:
    grid_sizes: tuple[float, ...] = (256.0, 64.0, 16.0)
    generation_radii: dict[float, float] = field(
        default_factory=lambda: {256.0: 2048.0, 64.0: 768.0, 16.0: 256.0}
    )
    cleanup_radius_multiplier: float = 1.25
    direction_weight: float = 0.35
    max_parallel_generation: int = 8
    frame_budget_ms: float = 8.0
    pooled_chunk_count: int = 64

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.grid_sizes or any(size <= 0 for size in self.grid_sizes):
            errors.append("Runtime procedural grid sizes must be positive.")
        if self.cleanup_radius_multiplier < 1.0:
            errors.append("Cleanup radius multiplier must be at least one.")
        for size in self.grid_sizes:
            if float(self.generation_radii.get(size, 0.0)) <= 0.0:
                errors.append(f"Missing generation radius for grid size {size}.")
        return errors


@dataclass
class ProceduralRuntimeChunk:
    chunk_id: str
    graph_id: str
    grid_size: float
    cell: tuple[int, int, int]
    instances: list[ProceduralInstance] = field(default_factory=list)

    @property
    def center(self) -> Vec3:
        return tuple((axis + 0.5) * self.grid_size for axis in self.cell)

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for instance in sorted(self.instances, key=lambda row: row.instance_id):
            digest.update(repr(instance.to_dict()).encode("utf-8"))
        return digest.hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "graph_id": self.graph_id,
            "grid_size": self.grid_size,
            "cell": self.cell,
            "center": self.center,
            "fingerprint": self.fingerprint,
            "instances": [instance.to_dict() for instance in self.instances],
        }


@dataclass(frozen=True)
class ProceduralScheduleItem:
    chunk_id: str
    action: str
    priority: float
    distance: float
    grid_size: float
    instance_count: int
    estimated_ms: float


@dataclass
class ProceduralRuntimeSchedule:
    items: list[ProceduralScheduleItem]
    deferred: list[str]
    pooled_chunk_count: int
    estimated_generation_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [asdict(item) for item in self.items],
            "deferred": list(self.deferred),
            "pooled_chunk_count": self.pooled_chunk_count,
            "estimated_generation_ms": self.estimated_generation_ms,
        }


def _instance_grid_size(instance: ProceduralInstance, profile: ProceduralRuntimeProfile) -> float:
    requested = instance.attributes.get("generation_grid", instance.attributes.get("grid_size"))
    if requested is not None:
        requested = float(requested)
        return min(profile.grid_sizes, key=lambda value: abs(value - requested))
    asset_extent = float(instance.attributes.get("asset_extent", 0.0) or 0.0)
    if asset_extent > 0.0:
        for size in sorted(profile.grid_sizes):
            if asset_extent <= size * 0.25:
                return size
        return max(profile.grid_sizes)
    return min(profile.grid_sizes)


def partition_procedural_result(
    result: ProceduralCookResult,
    profile: ProceduralRuntimeProfile | None = None,
) -> list[ProceduralRuntimeChunk]:
    """Place each stable instance into exactly one hierarchical streaming grid."""
    profile = profile or ProceduralRuntimeProfile()
    errors = profile.validate()
    if errors:
        raise ValueError("; ".join(errors))
    groups: dict[tuple[float, tuple[int, int, int]], list[ProceduralInstance]] = {}
    for instance in result.payload.instances:
        grid_size = _instance_grid_size(instance, profile)
        cell = tuple(math.floor(component / grid_size) for component in instance.position)
        groups.setdefault((grid_size, cell), []).append(instance)
    chunks: list[ProceduralRuntimeChunk] = []
    for (grid_size, cell), instances in sorted(groups.items()):
        cell_key = "_".join(str(axis) for axis in cell)
        chunks.append(
            ProceduralRuntimeChunk(
                chunk_id=f"{result.graph_id}:g{grid_size:g}:{cell_key}",
                graph_id=result.graph_id,
                grid_size=grid_size,
                cell=cell,
                instances=sorted(instances, key=lambda row: row.instance_id),
            )
        )
    return chunks


def _chunk_priority(
    chunk: ProceduralRuntimeChunk,
    source: ProceduralGenerationSource,
    direction_weight: float,
) -> tuple[float, float]:
    delta = tuple(chunk.center[axis] - source.position[axis] for axis in range(3))
    distance = math.sqrt(sum(component * component for component in delta))
    facing = sum(
        left * right for left, right in zip(_normalized(delta), _normalized(source.forward))
    )
    direction_penalty = (1.0 - max(-1.0, min(1.0, facing))) * max(0.0, direction_weight)
    priority = distance * (1.0 + direction_penalty) / max(0.01, source.importance)
    return priority, distance


def schedule_procedural_runtime(
    chunks: Iterable[ProceduralRuntimeChunk],
    sources: Iterable[ProceduralGenerationSource],
    *,
    loaded_chunk_ids: Iterable[str] = (),
    profile: ProceduralRuntimeProfile | None = None,
) -> ProceduralRuntimeSchedule:
    """Build one frame's bounded generation, keep, cleanup, and deferred work."""
    profile = profile or ProceduralRuntimeProfile()
    errors = profile.validate()
    if errors:
        raise ValueError("; ".join(errors))
    sources = list(sources)
    loaded = set(loaded_chunk_ids)
    candidates: list[ProceduralScheduleItem] = []
    cleanups: list[ProceduralScheduleItem] = []
    chunk_ids: set[str] = set()
    for chunk in chunks:
        chunk_ids.add(chunk.chunk_id)
        if not sources:
            nearest_priority, nearest_distance = math.inf, math.inf
            nearest_scale = 1.0
        else:
            scored = [(_chunk_priority(chunk, source, profile.direction_weight), source) for source in sources]
            (nearest_priority, nearest_distance), nearest_source = min(scored, key=lambda row: row[0][0])
            nearest_scale = max(0.0, nearest_source.radius_scale)
        radius = float(profile.generation_radii[chunk.grid_size]) * nearest_scale
        estimated_ms = 0.04 + len(chunk.instances) * 0.002
        if nearest_distance <= radius:
            action = "keep" if chunk.chunk_id in loaded else "generate"
            candidates.append(
                ProceduralScheduleItem(
                    chunk.chunk_id,
                    action,
                    nearest_priority,
                    nearest_distance,
                    chunk.grid_size,
                    len(chunk.instances),
                    estimated_ms if action == "generate" else 0.0,
                )
            )
        elif chunk.chunk_id in loaded and nearest_distance > radius * profile.cleanup_radius_multiplier:
            cleanups.append(
                ProceduralScheduleItem(
                    chunk.chunk_id,
                    "cleanup",
                    nearest_priority,
                    nearest_distance,
                    chunk.grid_size,
                    len(chunk.instances),
                    0.0,
                )
            )
    for missing in sorted(loaded - chunk_ids):
        cleanups.append(ProceduralScheduleItem(missing, "cleanup", math.inf, math.inf, 0.0, 0, 0.0))

    candidates.sort(key=lambda item: (item.action != "keep", item.priority, -item.grid_size, item.chunk_id))
    selected: list[ProceduralScheduleItem] = []
    deferred: list[str] = []
    generating = 0
    generation_ms = 0.0
    for item in candidates:
        if item.action == "generate" and (
            generating >= profile.max_parallel_generation
            or generation_ms + item.estimated_ms > profile.frame_budget_ms
        ):
            deferred.append(item.chunk_id)
            continue
        selected.append(item)
        if item.action == "generate":
            generating += 1
            generation_ms += item.estimated_ms
    selected.extend(sorted(cleanups, key=lambda item: (-item.distance, item.chunk_id)))
    return ProceduralRuntimeSchedule(
        items=selected,
        deferred=deferred,
        pooled_chunk_count=profile.pooled_chunk_count,
        estimated_generation_ms=generation_ms,
    )
