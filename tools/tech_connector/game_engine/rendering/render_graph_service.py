"""Renderer-neutral scheduling for frame resources, hazards, and transient memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import heapq
import math
from typing import Any, Iterable


RENDER_GRAPH_SCHEMA = "tech_connector.render_graph.v1"
_QUEUES = frozenset({"graphics", "compute", "copy"})
_ACCESS = frozenset({"read", "write", "read_write"})


@dataclass(frozen=True)
class RenderResource:
    resource_id: str
    kind: str = "buffer"
    format: str = "raw"
    size_bytes: int = 0
    transient: bool = True
    external: bool = False
    residency: str = "device_local"
    provider_id: str = "renderer"
    usages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("Render resources require an id.")
        if self.kind not in {"buffer", "texture"}:
            raise ValueError(f"Unknown render resource kind: {self.kind}")
        if int(self.size_bytes) < 0:
            raise ValueError("Render resource size cannot be negative.")
        if self.external and self.transient:
            object.__setattr__(self, "transient", False)


@dataclass(frozen=True)
class RenderAccess:
    resource_id: str
    access: str = "read"
    usage: str = "shader_resource"

    def __post_init__(self) -> None:
        if self.access not in _ACCESS:
            raise ValueError(f"Unknown render access: {self.access}")


@dataclass(frozen=True)
class RenderPass:
    pass_id: str
    queue: str
    accesses: tuple[RenderAccess, ...]
    depends_on: tuple[str, ...] = ()
    estimated_gpu_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.pass_id:
            raise ValueError("Render passes require an id.")
        if self.queue not in _QUEUES:
            raise ValueError(f"Unknown render queue: {self.queue}")
        if float(self.estimated_gpu_ms) < 0.0:
            raise ValueError("Estimated GPU time cannot be negative.")


@dataclass(frozen=True)
class RenderBarrier:
    resource_id: str
    before_pass: str
    after_pass: str
    before_access: str
    after_access: str
    before_usage: str
    after_usage: str
    queue_transfer: bool = False


@dataclass(frozen=True)
class QueueSynchronization:
    signal_pass: str
    wait_pass: str
    signal_queue: str
    wait_queue: str
    resources: tuple[str, ...]


@dataclass(frozen=True)
class TransientAllocation:
    resource_id: str
    slot: int
    offset_bytes: int
    size_bytes: int
    first_pass: int
    last_pass: int


@dataclass
class CompiledRenderGraph:
    resources: tuple[RenderResource, ...]
    passes: tuple[RenderPass, ...]
    dependencies: dict[str, tuple[str, ...]]
    barriers: tuple[RenderBarrier, ...]
    queue_synchronization: tuple[QueueSynchronization, ...]
    transient_allocations: tuple[TransientAllocation, ...]
    committed_transient_bytes: int
    aliased_transient_bytes: int
    diagnostics: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def transient_savings_bytes(self) -> int:
        return max(0, self.committed_transient_bytes - self.aliased_transient_bytes)

    def validate(self) -> tuple[str, ...]:
        errors = list(self.diagnostics)
        known = {resource.resource_id for resource in self.resources}
        for item in self.barriers:
            if item.resource_id not in known:
                errors.append(f"Barrier references unknown resource '{item.resource_id}'.")
        return tuple(dict.fromkeys(errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RENDER_GRAPH_SCHEMA,
            "valid": not self.validate(),
            "diagnostics": list(self.validate()),
            "resources": [asdict(item) for item in self.resources],
            "passes": [asdict(item) for item in self.passes],
            "dependencies": {key: list(value) for key, value in self.dependencies.items()},
            "barriers": [asdict(item) for item in self.barriers],
            "queue_synchronization": [asdict(item) for item in self.queue_synchronization],
            "transient_allocations": [asdict(item) for item in self.transient_allocations],
            "memory": {
                "committed_transient_bytes": self.committed_transient_bytes,
                "aliased_transient_bytes": self.aliased_transient_bytes,
                "savings_bytes": self.transient_savings_bytes,
                "savings_ratio": (
                    self.transient_savings_bytes / self.committed_transient_bytes
                    if self.committed_transient_bytes else 0.0
                ),
            },
            "metadata": dict(self.metadata),
        }


def compile_render_graph(
    resources: Iterable[RenderResource],
    passes: Iterable[RenderPass],
    *,
    metadata: dict[str, Any] | None = None,
) -> CompiledRenderGraph:
    """Compile declarations into deterministic execution, barriers, and aliases."""
    resource_list = tuple(resources)
    declared_passes = tuple(passes)
    resource_by_id = _unique_map(resource_list, "resource_id", "resource")
    pass_by_id = _unique_map(declared_passes, "pass_id", "pass")
    declaration_index = {item.pass_id: index for index, item in enumerate(declared_passes)}
    dependencies: dict[str, set[str]] = {item.pass_id: set(item.depends_on) for item in declared_passes}
    diagnostics: list[str] = []

    for item in declared_passes:
        for dependency in item.depends_on:
            if dependency not in pass_by_id:
                diagnostics.append(f"Pass '{item.pass_id}' depends on unknown pass '{dependency}'.")
        for access in item.accesses:
            if access.resource_id not in resource_by_id:
                diagnostics.append(f"Pass '{item.pass_id}' references unknown resource '{access.resource_id}'.")

    # Declaration order is used only to infer hazards. Explicit dependencies may
    # still move independent work onto asynchronous queues.
    previous_accesses: dict[str, list[tuple[str, RenderAccess]]] = {}
    for item in declared_passes:
        for access in item.accesses:
            history = previous_accesses.setdefault(access.resource_id, [])
            for previous_pass, previous in reversed(history):
                if _hazard(previous.access, access.access):
                    dependencies[item.pass_id].add(previous_pass)
                    break
            history.append((item.pass_id, access))

    ordered_ids, cycle = _topological_order(dependencies, declaration_index)
    if cycle:
        diagnostics.append("Render graph contains a dependency cycle: " + ", ".join(cycle))
        ordered_ids = [item.pass_id for item in declared_passes]
    ordered = tuple(pass_by_id[item_id] for item_id in ordered_ids)
    normalized_dependencies = {
        item_id: tuple(sorted(values, key=lambda value: declaration_index.get(value, math.inf)))
        for item_id, values in dependencies.items()
    }
    barriers = _compile_barriers(ordered)
    queue_sync = _compile_queue_sync(ordered, normalized_dependencies, barriers)
    allocations, committed, aliased = _compile_transient_aliases(resource_list, ordered)
    return CompiledRenderGraph(
        resource_list, ordered, normalized_dependencies, barriers, queue_sync,
        allocations, committed, aliased, tuple(diagnostics), dict(metadata or {}),
    )


def build_fx_render_graph(
    stream_receipt: dict[str, Any] | None,
    *,
    width: int = 1920,
    height: int = 1080,
    enable_async_compute: bool = True,
    enable_refraction: bool = True,
    enable_temporal_reconstruction: bool = True,
) -> CompiledRenderGraph:
    """Build the canonical particle/FX frame without claiming unavailable interop."""
    stream = dict(stream_receipt or {})
    count = max(0, int(stream.get("count", 0) or 0))
    pixel_count = max(1, int(width)) * max(1, int(height))
    buffer_bytes = max(16, count * 16)
    direct = bool(stream.get("end_to_end_zero_copy"))
    compatible = bool(stream.get("consumer_compatible", True))
    upload_required = bool(stream.get("consumer_upload_required")) or not direct
    source_residency = str(stream.get("residency") or "host_materialized")
    source_provider = str(stream.get("provider_id") or "unknown")
    resources = [
        RenderResource("simulation_positions", "buffer", "float4", buffer_bytes, False, True,
                       source_residency, source_provider, ("copy_source", "shader_resource")),
        RenderResource("visible_particles", "buffer", "uint", max(16, count * 4), True, False,
                       usages=("unordered_access", "shader_resource")),
        RenderResource("indirect_args", "buffer", "draw_indirect", 32, True, False,
                       usages=("unordered_access", "indirect")),
        RenderResource("depth", "texture", "d32", pixel_count * 4, True, False,
                       usages=("depth_target", "shader_resource")),
        RenderResource("hdr_color", "texture", "rgba16f", pixel_count * 8, True, False,
                       usages=("color_target", "shader_resource")),
        RenderResource("motion_vectors", "texture", "rg16f", pixel_count * 4, True, False,
                       usages=("color_target", "shader_resource")),
        RenderResource("reactive_mask", "texture", "r8", pixel_count, True, False,
                       usages=("color_target", "shader_resource")),
        RenderResource("present", "texture", "swapchain", pixel_count * 4, False, True,
                       "device_local", "swapchain", ("color_target", "present")),
    ]
    position_resource = "simulation_positions"
    passes: list[RenderPass] = []
    if upload_required:
        resources.append(RenderResource(
            "render_positions", "buffer", "float4", buffer_bytes, False, False,
            "device_local", "renderer", ("copy_destination", "shader_resource"),
        ))
        passes.append(RenderPass("upload_simulation_stream", "copy", (
            RenderAccess("simulation_positions", "read", "copy_source"),
            RenderAccess("render_positions", "write", "copy_destination"),
        ), metadata={"reason": stream.get("fallback_reason") or "shared device resource unavailable"}))
        position_resource = "render_positions"
    compute_queue = "compute" if enable_async_compute else "graphics"
    passes.extend([
        RenderPass("cull_and_compact_particles", compute_queue, (
            RenderAccess(position_resource, "read", "shader_resource"),
            RenderAccess("visible_particles", "write", "unordered_access"),
        ), ("upload_simulation_stream",) if upload_required else (), 0.15),
        RenderPass("build_indirect_draw_args", compute_queue, (
            RenderAccess("visible_particles", "read", "shader_resource"),
            RenderAccess("indirect_args", "write", "unordered_access"),
        ), ("cull_and_compact_particles",), 0.04),
        RenderPass("depth_prepass", "graphics", (
            RenderAccess("depth", "write", "depth_target"),
            RenderAccess("motion_vectors", "write", "color_target"),
        ), estimated_gpu_ms=0.35),
        RenderPass("opaque_lighting", "graphics", (
            RenderAccess("depth", "read", "depth_read"),
            RenderAccess("hdr_color", "write", "color_target"),
        ), ("depth_prepass",), 0.8),
        RenderPass("transparent_particles", "graphics", (
            RenderAccess(position_resource, "read", "shader_resource"),
            RenderAccess("visible_particles", "read", "shader_resource"),
            RenderAccess("indirect_args", "read", "indirect"),
            RenderAccess("depth", "read", "depth_read"),
            RenderAccess("hdr_color", "read_write", "color_target"),
            RenderAccess("reactive_mask", "write", "color_target"),
        ), ("opaque_lighting", "build_indirect_draw_args"), 0.45),
    ])
    last_color_pass = "transparent_particles"
    if enable_refraction:
        resources.append(RenderResource("refracted_color", "texture", "rgba16f", pixel_count * 8, True, False,
                                        usages=("color_target", "shader_resource")))
        passes.append(RenderPass("refractive_fx", "graphics", (
            RenderAccess("hdr_color", "read", "shader_resource"),
            RenderAccess("depth", "read", "depth_read"),
            RenderAccess("refracted_color", "write", "color_target"),
        ), (last_color_pass,), 0.3))
        last_color_pass = "refractive_fx"
    source_color = "refracted_color" if enable_refraction else "hdr_color"
    final_pass = "temporal_reconstruction" if enable_temporal_reconstruction else "tone_map"
    passes.append(RenderPass(final_pass, compute_queue if enable_temporal_reconstruction else "graphics", (
        RenderAccess(source_color, "read", "shader_resource"),
        RenderAccess("depth", "read", "shader_resource"),
        RenderAccess("motion_vectors", "read", "shader_resource"),
        RenderAccess("reactive_mask", "read", "shader_resource"),
        RenderAccess("present", "write", "color_target"),
    ), (last_color_pass,), 0.35))
    passes.append(RenderPass("present", "graphics", (
        RenderAccess("present", "read", "present"),
    ), (final_pass,), 0.02))
    fallback_reason = ""
    if upload_required:
        fallback_reason = str(stream.get("fallback_reason") or "No end-to-end shared resource path is available.")
    if not compatible:
        fallback_reason = str(stream.get("fallback_reason") or "Render consumer cannot import the simulation buffer.")
    return compile_render_graph(resources, passes, metadata={
        "workload": "fx_particles",
        "particle_count": count,
        "async_compute_requested": bool(enable_async_compute),
        "source_stream_schema": stream.get("schema", ""),
        "source_provider": source_provider,
        "source_residency": source_residency,
        "shared_resource_path": direct,
        "upload_fallback": upload_required,
        "fallback_reason": fallback_reason,
    })


def qualify_render_graph(
    graph: CompiledRenderGraph,
    *,
    require_async_compute: bool = False,
    require_shared_resource: bool = False,
) -> dict[str, Any]:
    blockers = list(graph.validate())
    queues = {item.queue for item in graph.passes}
    if require_async_compute and "compute" not in queues:
        blockers.append("async_compute")
    if require_shared_resource and not bool(graph.metadata.get("shared_resource_path")):
        blockers.append("shared_resource_interop")
    return {
        "schema": "tech_connector.render_graph_qualification.v1",
        "qualified": not blockers,
        "blockers": blockers,
        "pass_count": len(graph.passes),
        "barrier_count": len(graph.barriers),
        "queue_sync_count": len(graph.queue_synchronization),
        "memory": graph.to_dict()["memory"],
        "shared_resource_path": bool(graph.metadata.get("shared_resource_path")),
        "upload_fallback": bool(graph.metadata.get("upload_fallback")),
    }


def _unique_map(items: tuple[Any, ...], attribute: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key = str(getattr(item, attribute))
        if key in result:
            raise ValueError(f"Duplicate render {label} id: {key}")
        result[key] = item
    return result


def _hazard(before: str, after: str) -> bool:
    return before != "read" or after != "read"


def _topological_order(dependencies: dict[str, set[str]], declaration_index: dict[str, int]) -> tuple[list[str], list[str]]:
    known = set(dependencies)
    indegree = {key: len({item for item in values if item in known}) for key, values in dependencies.items()}
    dependents: dict[str, set[str]] = {key: set() for key in known}
    for item, values in dependencies.items():
        for value in values:
            if value in known:
                dependents[value].add(item)
    ready = [(declaration_index[item], item) for item, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    result: list[str] = []
    while ready:
        _, item = heapq.heappop(ready)
        result.append(item)
        for dependent in dependents[item]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (declaration_index[dependent], dependent))
    cycle = [item for item, degree in indegree.items() if degree > 0]
    cycle.sort(key=declaration_index.get)
    return result, cycle


def _compile_barriers(passes: tuple[RenderPass, ...]) -> tuple[RenderBarrier, ...]:
    last: dict[str, tuple[RenderPass, RenderAccess]] = {}
    barriers: list[RenderBarrier] = []
    for item in passes:
        for access in item.accesses:
            previous = last.get(access.resource_id)
            if previous is not None:
                before_pass, before = previous
                queue_transfer = before_pass.queue != item.queue
                if _hazard(before.access, access.access) or before.usage != access.usage or queue_transfer:
                    barriers.append(RenderBarrier(
                        access.resource_id, before_pass.pass_id, item.pass_id,
                        before.access, access.access, before.usage, access.usage, queue_transfer,
                    ))
            last[access.resource_id] = (item, access)
    return tuple(barriers)


def _compile_queue_sync(
    passes: tuple[RenderPass, ...],
    dependencies: dict[str, tuple[str, ...]],
    barriers: tuple[RenderBarrier, ...],
) -> tuple[QueueSynchronization, ...]:
    by_id = {item.pass_id: item for item in passes}
    resources_by_edge: dict[tuple[str, str], set[str]] = {}
    for barrier in barriers:
        if barrier.queue_transfer:
            resources_by_edge.setdefault((barrier.before_pass, barrier.after_pass), set()).add(barrier.resource_id)
    result: list[QueueSynchronization] = []
    seen: set[tuple[str, str]] = set()
    for wait_pass in passes:
        for signal_id in dependencies.get(wait_pass.pass_id, ()):
            signal_pass = by_id.get(signal_id)
            if signal_pass is None or signal_pass.queue == wait_pass.queue:
                continue
            edge = (signal_id, wait_pass.pass_id)
            if edge in seen:
                continue
            seen.add(edge)
            result.append(QueueSynchronization(
                signal_id, wait_pass.pass_id, signal_pass.queue, wait_pass.queue,
                tuple(sorted(resources_by_edge.get(edge, ()))),
            ))
    return tuple(result)


def _compile_transient_aliases(
    resources: tuple[RenderResource, ...], passes: tuple[RenderPass, ...],
) -> tuple[tuple[TransientAllocation, ...], int, int]:
    pass_index = {item.pass_id: index for index, item in enumerate(passes)}
    lifetimes: dict[str, list[int]] = {}
    for item in passes:
        for access in item.accesses:
            lifetimes.setdefault(access.resource_id, []).append(pass_index[item.pass_id])
    transient = [item for item in resources if item.transient and item.resource_id in lifetimes]
    transient.sort(key=lambda item: (min(lifetimes[item.resource_id]), -item.size_bytes, item.resource_id))
    slots: list[dict[str, Any]] = []
    allocations: list[TransientAllocation] = []
    for resource in transient:
        first, last = min(lifetimes[resource.resource_id]), max(lifetimes[resource.resource_id])
        compatible_slot = None
        for slot_index, slot in enumerate(slots):
            compatible = slot["kind"] == resource.kind and slot["format"] == resource.format
            non_overlapping = all(last < other_first or first > other_last for other_first, other_last in slot["ranges"])
            if compatible and non_overlapping:
                compatible_slot = slot_index
                break
        if compatible_slot is None:
            compatible_slot = len(slots)
            slots.append({"kind": resource.kind, "format": resource.format, "size": 0, "ranges": []})
        slot = slots[compatible_slot]
        slot["size"] = max(slot["size"], resource.size_bytes)
        slot["ranges"].append((first, last))
        allocations.append(TransientAllocation(resource.resource_id, compatible_slot, 0, resource.size_bytes, first, last))
    return tuple(allocations), sum(item.size_bytes for item in transient), sum(slot["size"] for slot in slots)


__all__ = [
    "RENDER_GRAPH_SCHEMA", "CompiledRenderGraph", "QueueSynchronization", "RenderAccess", "RenderBarrier",
    "RenderPass", "RenderResource", "TransientAllocation", "build_fx_render_graph", "compile_render_graph",
    "qualify_render_graph",
]
