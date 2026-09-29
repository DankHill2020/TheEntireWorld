"""Headless fixed-step runtime for compiled TC simulation and effect worlds."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields as dataclass_fields, is_dataclass
import hashlib
import json
import math
from typing import Any

from tech_connector.game_engine.runtime.tc_effect_system_service import (
    QUALITY_PROFILES,
    create_effect_world,
    set_effect_parameter,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    CompiledSimulationIR,
    compile_simulation_world,
    execute_compiled_simulation,
)
from tech_connector.game_engine.runtime.tc_simulation_service import SimulationCache, SimulationFrame


_QUALITY_TO_EXECUTION_PROFILE = {
    "low": "mobile",
    "medium": "realtime",
    "high": "realtime",
    "cinematic": "cinematic",
    "realtime": "realtime",
    "mobile": "mobile",
    "toony": "toony",
    "stylized": "stylized",
    "retro": "retro",
}


@dataclass(frozen=True)
class RuntimeCommand:
    tick: int
    path: str
    value: Any
    sequence: int


@dataclass
class RuntimeCheckpoint:
    tick: int
    accumulator: float
    world: Any
    previous_particles: dict[int, tuple[float, float, float]]
    data_channel_cursors: dict[str, int]


@dataclass
class RuntimeFramePacket:
    tick: int
    simulation_time: float
    interpolation_alpha: float
    streams: dict[str, list[dict[str, Any]]]
    events: list[dict[str, Any]]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.runtime_effect_frame.v1",
            "tick": self.tick,
            "simulation_time": self.simulation_time,
            "interpolation_alpha": self.interpolation_alpha,
            "streams": self.streams,
            "events": self.events,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    state: str
    tick: int
    asset_fingerprint: str
    state_hash: str
    compiled_backend: str
    execution_backend: str
    execution_device: str
    fallback_active: bool
    gpu_resident: bool
    readback_free: bool
    synchronization_points: int
    within_budget: bool | None
    average_ms: float
    p95_ms: float
    memory_bytes: int
    pending_commands: int
    checkpoint_count: int
    cached_frames: int
    diagnostics: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "tech_connector.runtime_health.v1", **asdict(self)}


class SimulationRuntimeInstance:
    """Own one compiled world and advance it independently of editor/UI timing."""

    def __init__(
        self,
        world: Any,
        *,
        profile: str = "realtime",
        backend: str = "auto",
        tick_rate: float = 60.0,
        max_catch_up_steps: int = 4,
        checkpoint_interval: int = 30,
        checkpoint_limit: int = 8,
        max_pending_commands: int = 4096,
        command_history_limit: int = 16_384,
    ) -> None:
        if tick_rate <= 0.0:
            raise ValueError("Runtime tick rate must be greater than zero.")
        self.world = world
        self._initial_world = copy.deepcopy(world)
        self.asset_fingerprint = _stable_hash(_canonical_world(world, runtime_state=False))
        self.profile = str(profile).lower()
        self.backend = str(backend).lower()
        self.fixed_dt = 1.0 / float(tick_rate)
        self.max_catch_up_steps = max(1, int(max_catch_up_steps))
        self.checkpoint_interval = max(0, int(checkpoint_interval))
        self.checkpoint_limit = max(1, int(checkpoint_limit))
        self.max_pending_commands = max(1, int(max_pending_commands))
        self.command_history_limit = max(self.max_pending_commands, int(command_history_limit))
        self.compiled = compile_simulation_world(world, profile=self.profile, backend=self.backend)
        self.state = "ready"
        self.tick_index = 0
        self.accumulator = 0.0
        self.dropped_time = 0.0
        self._command_sequence = 0
        self._commands: list[RuntimeCommand] = []
        self._command_history: list[RuntimeCommand] = []
        self._checkpoints: list[RuntimeCheckpoint] = []
        self._previous_particles = self._particle_positions()
        self._events: list[dict[str, Any]] = []
        self._data_channel_cursors: dict[str, int] = {}
        self.cache: SimulationCache | None = None
        self.capture_checkpoint()

    @classmethod
    def from_effect_preset(
        cls,
        preset: str,
        *,
        quality: str = "realtime",
        seed: int = 1,
        tick_rate: float = 60.0,
        backend: str = "auto",
        max_pending_commands: int = 4096,
        command_history_limit: int = 16_384,
    ) -> "SimulationRuntimeInstance":
        quality_key = str(quality).lower()
        world = create_effect_world(preset, quality=quality_key, seed=seed)
        profile = _QUALITY_TO_EXECUTION_PROFILE.get(quality_key, "realtime")
        return cls(
            world, profile=profile, backend=backend, tick_rate=tick_rate,
            max_pending_commands=max_pending_commands, command_history_limit=command_history_limit,
        )

    def queue_parameter(self, path: str, value: Any, *, tick: int | None = None) -> RuntimeCommand:
        if self.world.effect_system is None:
            raise ValueError("Runtime parameter commands require an effect system.")
        target_tick = self.tick_index + 1 if tick is None else int(tick)
        if target_tick <= self.tick_index:
            raise ValueError("Runtime commands must target a future tick.")
        if len(self._commands) >= self.max_pending_commands:
            raise OverflowError(
                f"Runtime command queue reached its bounded capacity ({self.max_pending_commands})."
            )
        command = RuntimeCommand(target_tick, str(path), copy.deepcopy(value), self._command_sequence)
        self._command_sequence += 1
        self._commands.append(command)
        self._command_history.append(command)
        if len(self._command_history) > self.command_history_limit:
            del self._command_history[:-self.command_history_limit]
        self._commands.sort(key=lambda item: (item.tick, item.sequence))
        return command

    def queue_data_channel(self, channel_id: str, values: dict[str, Any], *,
                           tick: int | None = None) -> RuntimeCommand:
        """Publish gameplay/simulation data on a deterministic future tick boundary."""
        system = self.world.effect_system
        if system is None or str(channel_id) not in system.data_channels:
            raise KeyError(f"Unknown runtime FX data channel: {channel_id}")
        return self.queue_parameter(f"data_channel.{channel_id}", dict(values), tick=tick)

    def advance(self, elapsed_seconds: float) -> RuntimeFramePacket:
        if self.state == "paused":
            return self.frame_packet(steps=0)
        if self.state == "error":
            raise RuntimeError("The simulation runtime is in an error state; reset it before advancing.")
        self.state = "running"
        elapsed = max(0.0, float(elapsed_seconds))
        maximum_accumulation = self.fixed_dt * self.max_catch_up_steps
        accepted = min(elapsed, maximum_accumulation)
        self.dropped_time += elapsed - accepted
        self.accumulator += accepted
        steps = 0
        while self.accumulator + 1.0e-12 >= self.fixed_dt and steps < self.max_catch_up_steps:
            try:
                self._step_once()
            except Exception:
                self.state = "error"
                raise
            self.accumulator = max(0.0, self.accumulator - self.fixed_dt)
            steps += 1
        return self.frame_packet(steps=steps)

    def pause(self) -> None:
        if self.state != "error":
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "error":
            raise RuntimeError("Reset an errored runtime before resuming it.")
        self.state = "running"

    def reset(self) -> None:
        """Restore authored initial state while preserving runtime configuration."""
        self.world = copy.deepcopy(self._initial_world)
        self.compiled = compile_simulation_world(self.world, profile=self.profile, backend=self.backend)
        self.state = "ready"
        self.tick_index = 0
        self.accumulator = 0.0
        self.dropped_time = 0.0
        self._commands.clear()
        self._command_history.clear()
        self._checkpoints.clear()
        self._previous_particles = self._particle_positions()
        self._events.clear()
        self._data_channel_cursors.clear()
        if self.cache is not None:
            self.cache.frames.clear()
            self.cache.metadata.clear()
        self.capture_checkpoint()

    def authored_world_snapshot(self) -> Any:
        """Return an isolated copy suitable for qualification, replay, or another runtime instance."""
        return copy.deepcopy(self._initial_world)

    def enable_cache(self, *, frame_rate: float | None = None) -> SimulationCache:
        rate = float(frame_rate) if frame_rate is not None else 1.0 / self.fixed_dt
        if not math.isfinite(rate) or rate <= 0.0:
            raise ValueError("Cache frame rate must be finite and greater than zero.")
        self.cache = SimulationCache(frame_rate=rate)
        self.cache.metadata.update({
            "asset_fingerprint": self.asset_fingerprint,
            "fixed_dt": self.fixed_dt,
            "profile": self.profile,
            "compiled_backend": self.compiled.backend.backend_id,
        })
        self.cache.set_stage_state("simulate", "running", detail="Capturing deterministic runtime frames.")
        self._capture_cache_frame()
        return self.cache

    def disable_cache(self, *, completed: bool = True) -> SimulationCache | None:
        if self.cache is not None:
            self.cache.set_stage_state(
                "simulate", "cached" if completed else "stale",
                detail="Runtime capture completed." if completed else "Runtime capture stopped before completion.",
            )
        return self.cache

    def frame_packet(self, *, steps: int = 0) -> RuntimeFramePacket:
        alpha = min(1.0, max(0.0, self.accumulator / self.fixed_dt))
        streams: dict[str, list[dict[str, Any]]] = {}
        system = self.world.effect_system
        renderers = system.renderer_metadata if system is not None else {}
        for index, particle in enumerate(self.world.particles):
            if not particle.alive:
                continue
            particle_id = self._particle_id(particle, index)
            previous = self._previous_particles.get(particle_id, particle.position)
            position = tuple(
                previous[axis] + (particle.position[axis] - previous[axis]) * alpha
                for axis in range(3)
            )
            renderer = dict(renderers.get(particle.emitter_id, {"type": "particle"}))
            material_mode = str(renderer.get("material_mode") or "").lower()
            stream_id = material_mode if material_mode in {"refractive", "distortion"} else str(renderer.get("type") or "particle")
            streams.setdefault(stream_id, []).append(
                {
                    "particle_id": particle_id,
                    "emitter_id": particle.emitter_id,
                    "position": position,
                    "velocity": particle.velocity,
                    "color": particle.color,
                    "size": particle.size,
                    "rotation": particle.rotation,
                    "renderer": renderer,
                }
            )
        for surface_id, mesh in sorted(
            dict(getattr(self.world, "_native_surface_outputs", {}) or {}).items()
        ):
            streams.setdefault("ocean_surface", []).append({
                "surface_id": str(surface_id),
                "mesh": mesh,
                "renderer": {"type": "mesh", "material_mode": "water"},
            })
        events, self._events = self._events, []
        return RuntimeFramePacket(
            self.tick_index,
            float(self.world.time_seconds),
            alpha,
            streams,
            events,
            {
                "steps": int(steps),
                "fixed_dt": self.fixed_dt,
                "backend": self.compiled.backend.backend_id,
                "execution_backend": self.compiled.metadata.get("execution_backend", "reference_cpu"),
                "gpu_resident": bool(self.compiled.metadata.get("gpu_resident", False)),
                "profile": self.compiled.profile.name,
                "alive_particles": sum(len(items) for items in streams.values()),
                "dropped_time": self.dropped_time,
                "data_channels": {
                    key: value.statistics()
                    for key, value in (getattr(system, "data_channels", {}) or {}).items()
                },
                "last_execution": dict(self.compiled.metadata.get("last_execution") or {}),
                "runtime_state": self.state,
                "asset_fingerprint": self.asset_fingerprint,
                "state_hash": self.state_hash(),
                "checkpoint_count": len(self._checkpoints),
                "cached_frames": len(self.cache.frames) if self.cache is not None else 0,
            },
        )

    def set_quality(self, quality: str) -> None:
        key = str(quality).lower()
        if key not in QUALITY_PROFILES:
            raise KeyError(f"Unknown runtime effect quality: {quality}")
        if self.world.effect_system is not None:
            self.world.effect_system.quality = key
        self.profile = _QUALITY_TO_EXECUTION_PROFILE.get(key, "realtime")
        self.compiled = compile_simulation_world(self.world, profile=self.profile, backend=self.backend)

    def capture_checkpoint(self) -> RuntimeCheckpoint:
        checkpoint = RuntimeCheckpoint(
            self.tick_index,
            0.0,
            _checkpoint_world_copy(self.world),
            dict(self._previous_particles),
            dict(self._data_channel_cursors),
        )
        self._checkpoints.append(checkpoint)
        if len(self._checkpoints) > self.checkpoint_limit:
            del self._checkpoints[:-self.checkpoint_limit]
        return checkpoint

    def rollback(self, tick: int) -> int:
        candidates = [item for item in self._checkpoints if item.tick <= int(tick)]
        if not candidates:
            raise ValueError(f"No runtime checkpoint is available at or before tick {tick}.")
        checkpoint = max(candidates, key=lambda item: item.tick)
        self.world = copy.deepcopy(checkpoint.world)
        self.tick_index = checkpoint.tick
        self.accumulator = checkpoint.accumulator
        self._previous_particles = dict(checkpoint.previous_particles)
        self._data_channel_cursors = dict(checkpoint.data_channel_cursors)
        self._events.clear()
        self._commands = [item for item in self._command_history if item.tick > checkpoint.tick]
        self._checkpoints = [item for item in self._checkpoints if item.tick <= checkpoint.tick]
        return self.tick_index

    def deployment_manifest(self) -> dict[str, Any]:
        system = self.world.effect_system
        return {
            "schema": "tech_connector.runtime_simulation_asset.v1",
            "compiled_ir": self.compiled.to_dict(),
            "fixed_dt": self.fixed_dt,
            "effect_system": system.to_dict() if system is not None else None,
            "requires_editor": False,
            "runtime_backend": self.compiled.backend.backend_id,
            "execution_backend": self.compiled.metadata.get("execution_backend", "reference_cpu"),
            "gpu_resident": bool(self.compiled.metadata.get("gpu_resident", False)),
            "asset_fingerprint": self.asset_fingerprint,
            "deterministic": bool(self.compiled.profile.deterministic and self.compiled.backend.deterministic),
            "compatibility": {
                "simulation_ir_schema": "tech_connector.simulation_ir.v1",
                "runtime_frame_schema": "tech_connector.runtime_effect_frame.v1",
                "fixed_step_required": True,
                "explicit_backend_fallbacks": True,
            },
            "cache": self.cache.to_dict() if self.cache is not None else None,
        }

    def state_hash(self) -> str:
        return _stable_hash({
            "tick": self.tick_index,
            "world": _canonical_world(self.world, runtime_state=True),
            "pending_commands": [asdict(item) for item in self._commands],
        })

    def health_snapshot(self) -> RuntimeHealthSnapshot:
        history = list(self.compiled.metadata.get("execution_history") or [])
        samples = [float(item.get("elapsed_ms", 0.0) or 0.0) for item in history]
        ordered = sorted(samples)
        average = sum(samples) / len(samples) if samples else 0.0
        p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))] if ordered else 0.0
        last = dict(self.compiled.metadata.get("last_execution") or {})
        compiled_backend = self.compiled.backend.backend_id
        execution_backend = str(last.get("execution_backend") or self.compiled.metadata.get("execution_backend") or "")
        return RuntimeHealthSnapshot(
            self.state, self.tick_index, self.asset_fingerprint, self.state_hash(), compiled_backend,
            execution_backend, str(last.get("execution_device") or self.compiled.backend.execution_device),
            bool(execution_backend and execution_backend != compiled_backend),
            bool(last.get("gpu_resident", self.compiled.metadata.get("gpu_resident", False))),
            bool(last.get("readback_free", False)), int(last.get("synchronization_points", 0) or 0),
            bool(last.get("within_budget")) if last else None,
            average, p95, int(last.get("memory_bytes", 0) or 0), len(self._commands),
            len(self._checkpoints), len(self.cache.frames) if self.cache is not None else 0,
            tuple(copy.deepcopy(self.compiled.diagnostics)),
        )

    def _step_once(self) -> None:
        next_tick = self.tick_index + 1
        self._apply_commands(next_tick)
        self._previous_particles = self._particle_positions()
        execute_compiled_simulation(self.compiled, self.world, self.fixed_dt)
        self.tick_index = next_tick
        if self.cache is not None:
            self._capture_cache_frame()
        if self.world.effect_system is not None:
            for event in self.world.effect_system.emitted_events:
                self._events.append({"tick": self.tick_index, **copy.deepcopy(event)})
            for channel_id, channel in self.world.effect_system.data_channels.items():
                cursor = self._data_channel_cursors.get(channel_id, -1)
                for event in channel.read_since(cursor, through_tick=self.tick_index):
                    self._events.append({
                        "tick": self.tick_index, "type": "data_channel", "channel_id": channel_id,
                        **event.to_dict(),
                    })
                    self._data_channel_cursors[channel_id] = event.sequence
        if self.checkpoint_interval and self.tick_index % self.checkpoint_interval == 0:
            self.capture_checkpoint()

    def _capture_cache_frame(self) -> None:
        if self.cache is None:
            return
        volume_cells: dict[str, dict[str, Any]] = {}
        for name, volume in sorted((getattr(self.world, "volumes", {}) or {}).items()):
            volume_cells[str(name)] = {
                str(tuple(key)): _canonicalize(cell)
                for key, cell in sorted(volume.cells.items(), key=lambda item: tuple(item[0]))
            }
        self.cache.store(SimulationFrame(
            self.tick_index,
            float(getattr(self.world, "time_seconds", self.tick_index * self.fixed_dt)),
            [tuple(item.position) for item in self.world.particles],
            [tuple(item.velocity) for item in self.world.particles],
            volume_cells,
        ))

    def _apply_commands(self, tick: int) -> None:
        ready = [item for item in self._commands if item.tick == tick]
        self._commands = [item for item in self._commands if item.tick != tick]
        for command in ready:
            if command.path.startswith("data_channel."):
                channel_id = command.path[len("data_channel."):]
                channel = self.world.effect_system.data_channels.get(channel_id)
                if channel is None:
                    raise KeyError(f"Unknown runtime FX data channel: {channel_id}")
                channel.publish(copy.deepcopy(command.value), tick=tick, source="runtime_command")
            else:
                set_effect_parameter(self.world.effect_system, command.path, copy.deepcopy(command.value))

    def _particle_positions(self) -> dict[int, tuple[float, float, float]]:
        return {
            self._particle_id(particle, index): tuple(particle.position)
            for index, particle in enumerate(self.world.particles)
            if particle.alive
        }

    @staticmethod
    def _particle_id(particle: Any, index: int) -> int:
        particle_id = int(getattr(particle, "particle_id", -1))
        return particle_id if particle_id >= 0 else -(index + 1)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checkpoint_world_copy(world: Any) -> Any:
    """Copy durable simulation state without device sessions or transient buffers."""
    snapshot = copy.copy(world)
    snapshot.__dict__ = copy.deepcopy({
        key: value for key, value in vars(world).items() if not key.startswith("_")
    })
    return snapshot


def _canonical_world(world: Any, *, runtime_state: bool) -> dict[str, Any]:
    ignored = {"debug_contacts", "debug_physics_joints"}
    if not runtime_state:
        ignored.add("time_seconds")
    return {
        key: _canonicalize(value)
        for key, value in sorted(vars(world).items())
        if not key.startswith("_") and key not in ignored
    }


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Runtime state contains a non-finite number.")
        return 0.0 if value == 0.0 else value
    if is_dataclass(value):
        return {
            item.name: _canonicalize(getattr(value, item.name))
            for item in dataclass_fields(value)
            if not item.name.startswith("_") and item.name not in {"debug_contacts", "debug_physics_joints"}
        }
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonicalize(item) for item in value), key=lambda item: repr(item))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _canonicalize(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _canonicalize(item)
            for key, item in sorted(vars(value).items())
            if not key.startswith("_") and key not in {"debug_contacts", "debug_physics_joints"}
        }
    raise TypeError(f"Unsupported runtime state value for canonical hashing: {type(value).__name__}")


__all__ = [
    "RuntimeCheckpoint", "RuntimeCommand", "RuntimeFramePacket", "RuntimeHealthSnapshot",
    "SimulationRuntimeInstance",
]

