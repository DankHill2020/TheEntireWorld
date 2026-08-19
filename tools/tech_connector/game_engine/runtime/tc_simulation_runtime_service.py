"""Headless fixed-step runtime for compiled TC simulation and effect worlds."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
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
    ) -> None:
        if tick_rate <= 0.0:
            raise ValueError("Runtime tick rate must be greater than zero.")
        self.world = world
        self.profile = str(profile).lower()
        self.backend = str(backend).lower()
        self.fixed_dt = 1.0 / float(tick_rate)
        self.max_catch_up_steps = max(1, int(max_catch_up_steps))
        self.checkpoint_interval = max(0, int(checkpoint_interval))
        self.checkpoint_limit = max(1, int(checkpoint_limit))
        self.compiled = compile_simulation_world(world, profile=self.profile, backend=self.backend)
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
    ) -> "SimulationRuntimeInstance":
        quality_key = str(quality).lower()
        world = create_effect_world(preset, quality=quality_key, seed=seed)
        profile = _QUALITY_TO_EXECUTION_PROFILE.get(quality_key, "realtime")
        return cls(world, profile=profile, backend=backend, tick_rate=tick_rate)

    def queue_parameter(self, path: str, value: Any, *, tick: int | None = None) -> RuntimeCommand:
        if self.world.effect_system is None:
            raise ValueError("Runtime parameter commands require an effect system.")
        target_tick = self.tick_index + 1 if tick is None else int(tick)
        if target_tick <= self.tick_index:
            raise ValueError("Runtime commands must target a future tick.")
        command = RuntimeCommand(target_tick, str(path), copy.deepcopy(value), self._command_sequence)
        self._command_sequence += 1
        self._commands.append(command)
        self._command_history.append(command)
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
        elapsed = max(0.0, float(elapsed_seconds))
        maximum_accumulation = self.fixed_dt * self.max_catch_up_steps
        accepted = min(elapsed, maximum_accumulation)
        self.dropped_time += elapsed - accepted
        self.accumulator += accepted
        steps = 0
        while self.accumulator + 1.0e-12 >= self.fixed_dt and steps < self.max_catch_up_steps:
            self._step_once()
            self.accumulator = max(0.0, self.accumulator - self.fixed_dt)
            steps += 1
        return self.frame_packet(steps=steps)

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
            copy.deepcopy(self.world),
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
        }

    def _step_once(self) -> None:
        next_tick = self.tick_index + 1
        self._apply_commands(next_tick)
        self._previous_particles = self._particle_positions()
        execute_compiled_simulation(self.compiled, self.world, self.fixed_dt)
        self.tick_index = next_tick
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

