"""Truthful resident-buffer handoff between simulation and render consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class RenderBufferView:
    name: str
    handle: Any
    shape: tuple[int, ...]
    dtype: str
    residency: str
    revision: int = 0

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name, "shape": list(self.shape), "dtype": self.dtype,
            "residency": self.residency, "revision": self.revision,
        }


@dataclass
class SimulationRenderStream:
    source_backend: str
    provider_id: str
    residency: str
    count: int
    buffers: dict[str, RenderBufferView]
    consumer: str
    consumer_compatible: bool
    zero_copy_source: bool
    consumer_upload_required: bool
    synchronization_required: bool
    synchronization_performed: bool = False
    fallback_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.simulation_render_stream.v1",
            "source_backend": self.source_backend,
            "provider_id": self.provider_id,
            "residency": self.residency,
            "count": self.count,
            "consumer": self.consumer,
            "consumer_compatible": self.consumer_compatible,
            "zero_copy_source": self.zero_copy_source,
            "consumer_upload_required": self.consumer_upload_required,
            "end_to_end_zero_copy": bool(
                self.zero_copy_source and self.consumer_compatible
                and not self.consumer_upload_required and not self.synchronization_required
            ),
            "synchronization_required": self.synchronization_required,
            "synchronization_performed": self.synchronization_performed,
            "fallback_reason": self.fallback_reason,
            "buffers": {name: view.descriptor() for name, view in self.buffers.items()},
            "metadata": dict(self.metadata),
        }


def build_simulation_render_stream(
    world: Any,
    *,
    consumer: str = "generic_compute",
    allow_synchronization: bool = False,
) -> SimulationRenderStream:
    """Return the best available particle stream without hiding interop copies."""
    consumer_key = str(consumer or "generic_compute").lower()
    from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import (
        gpu_particle_view, synchronize_gpu_particles,
    )

    gpu = gpu_particle_view(world)
    if gpu is not None and bool(gpu.get("authoritative")):
        direct_consumers = {"generic_compute", "cuda", "cupy", str(gpu["provider_id"]).lower()}
        compatible = consumer_key in direct_consumers
        if compatible:
            return _stream_from_mapping(
                gpu, source_backend="gpu_compute", provider_id=str(gpu["provider_id"]),
                residency="persistent_device", consumer=consumer_key, compatible=True,
                zero_copy=True, synchronization_required=False,
            )
        if not allow_synchronization:
            return _stream_from_mapping(
                gpu, source_backend="gpu_compute", provider_id=str(gpu["provider_id"]),
                residency="persistent_device", consumer=consumer_key, compatible=False,
                zero_copy=True, synchronization_required=True,
                fallback_reason=f"{consumer_key} cannot import {gpu['provider_id']} device buffers.",
            )
        synchronize_gpu_particles(world)
        stream = _object_stream(world, consumer_key)
        stream.source_backend = "gpu_compute"
        stream.synchronization_required = True
        stream.synchronization_performed = True
        stream.fallback_reason = f"{consumer_key} required an explicit GPU-to-host synchronization."
        return stream

    from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import native_particle_view

    native = native_particle_view(world)
    if native is not None:
        return _stream_from_mapping(
            native, source_backend="native_cpu", provider_id="numpy_cpu",
            residency="persistent_host_soa", consumer=consumer_key, compatible=True,
            zero_copy=True, synchronization_required=False,
        )
    return _object_stream(world, consumer_key)


def _stream_from_mapping(mapping: dict[str, Any], *, source_backend: str, provider_id: str,
                         residency: str, consumer: str, compatible: bool, zero_copy: bool,
                         synchronization_required: bool, fallback_reason: str = "") -> SimulationRenderStream:
    count = int(mapping.get("count", 0) or 0)
    revisions = dict(mapping.get("revisions") or {})
    buffers: dict[str, RenderBufferView] = {}
    for name in ("positions", "velocities", "radii", "alive"):
        handle = mapping.get(name)
        if handle is None:
            continue
        buffers[name] = RenderBufferView(
            name, handle, tuple(int(value) for value in getattr(handle, "shape", (count,))),
            str(getattr(handle, "dtype", "unknown")), residency, int(revisions.get(name, 0)),
        )
    return SimulationRenderStream(
        source_backend, provider_id, residency, count, buffers, consumer, compatible,
        zero_copy, consumer.startswith("qt_"), synchronization_required, False, fallback_reason,
        {"capacity": int(mapping.get("capacity", count) or count)},
    )


def _object_stream(world: Any, consumer: str) -> SimulationRenderStream:
    particles = list(getattr(world, "particles", ()) or ())
    positions = np.asarray([item.position for item in particles], dtype=np.float32).reshape((-1, 3))
    velocities = np.asarray([item.velocity for item in particles], dtype=np.float32).reshape((-1, 3))
    radii = np.asarray([item.radius for item in particles], dtype=np.float32)
    alive = np.asarray([item.alive for item in particles], dtype=np.bool_)
    mapping = {"positions": positions, "velocities": velocities, "radii": radii, "alive": alive,
               "count": len(particles), "capacity": len(particles)}
    stream = _stream_from_mapping(
        mapping, source_backend="object_reference", provider_id="python_objects",
        residency="host_materialized", consumer=consumer, compatible=True,
        zero_copy=False, synchronization_required=False,
    )
    stream.fallback_reason = "No persistent simulation buffer view was available; materialized host arrays."
    return stream


def qualify_simulation_render_stream(
    stream: SimulationRenderStream,
    *,
    require_end_to_end_zero_copy: bool = False,
) -> dict[str, Any]:
    receipt = stream.receipt()
    blockers: list[str] = []
    if not stream.consumer_compatible:
        blockers.append("consumer_buffer_interop")
    if stream.synchronization_required:
        blockers.append("synchronization_required")
    if require_end_to_end_zero_copy and not receipt["end_to_end_zero_copy"]:
        blockers.append("end_to_end_zero_copy")
    return {
        "schema": "tech_connector.simulation_render_qualification.v1",
        "qualified": not blockers,
        "blockers": blockers,
        "stream": receipt,
    }


__all__ = [
    "RenderBufferView", "SimulationRenderStream", "build_simulation_render_stream",
    "qualify_simulation_render_stream",
]
