"""Modular deterministic real-time effects systems for The Entire Scene."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
import math
import random
from typing import Any

from tech_connector.game_engine.runtime.tc_simulation_service import PlaneCollider, SimulationParticle, SimulationWorld
from tech_connector.game_engine.runtime.tc_fx_workflow_service import (
    FxPerformanceContract,
    build_fx_workflow_plan,
    solver_profile_for_preset,
)
from tech_connector.game_engine.runtime.tc_fx_data_channel_service import (
    FxDataChannel,
    FxDataChannelBinding,
    FxDataChannelConsumer,
    FxSubgraphDefinition,
    publish_bound_effect_events,
)


Vec3 = tuple[float, float, float]
Color = tuple[float, float, float, float]


@dataclass(frozen=True)
class EffectQualityProfile:
    name: str
    spawn_scale: float = 1.0
    max_particles: int = 20000
    update_stride: int = 1
    render_scale: float = 1.0
    enable_lights: bool = True
    enable_volumes: bool = True
    target_frame_ms: float = 4.0
    solver_substeps: int = 1
    volume_resolution_scale: float = 1.0
    art_style: str = "photoreal"
    prefer_stateless: bool = False


QUALITY_PROFILES = {
    "low": EffectQualityProfile("Low", 0.3, 2500, 2, 0.7, False, False),
    "medium": EffectQualityProfile("Medium", 0.6, 8000, 1, 0.85, False, True),
    "high": EffectQualityProfile("High", 1.0, 20000, 1, 1.0, True, True),
    "cinematic": EffectQualityProfile("Cinematic", 1.75, 75000, 1, 1.25, True, True, 33.3, 2, 1.5, "photoreal"),
    "realtime": EffectQualityProfile("Realtime", 1.0, 20000, 1, 1.0, True, True, 4.0, 1, 1.0, "photoreal"),
    "mobile": EffectQualityProfile("Mobile", 0.35, 3500, 2, 0.65, False, False, 2.0, 1, 0.5, "simplified", True),
    "toony": EffectQualityProfile("Toony", 0.8, 12000, 1, 1.0, True, True, 4.0, 1, 0.75, "toony"),
    "stylized": EffectQualityProfile("Stylized", 0.8, 12000, 1, 1.0, True, True, 4.0, 1, 0.75, "stylized"),
    "retro": EffectQualityProfile("Retro", 0.15, 1200, 4, 0.4, False, False, 1.0, 1, 0.25, "retro", True),
}


@dataclass
class EffectModule:
    module_type: str
    phase: str = "update"
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class EffectEventBinding:
    source_emitter: str
    event_type: str
    target_emitter: str
    spawn_count: int = 1
    inherit_velocity: float = 0.0


@dataclass
class EffectEmitter:
    emitter_id: str
    name: str
    spawn_rate: float = 0.0
    burst_count: int = 0
    max_particles: int = 0
    update_rate_divisor: int = 1
    duration: float = 5.0
    looping: bool = False
    event_only: bool = False
    spawn_shape: dict[str, Any] = field(default_factory=lambda: {"type": "point", "center": (0.0, 0.0, 0.0)})
    modules: list[EffectModule] = field(default_factory=list)
    renderer: dict[str, Any] = field(default_factory=lambda: {"type": "sprite", "blend": "additive"})
    enabled: bool = True
    age: float = 0.0
    spawn_remainder: float = 0.0
    burst_emitted: bool = False
    interactive_active: bool = False
    interactive_spawn_rate: float = 90.0


@dataclass
class EffectSystem:
    system_id: str
    name: str
    emitters: list[EffectEmitter]
    event_bindings: list[EffectEventBinding] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    quality: str = "high"
    deterministic_seed: int = 1
    frame: int = 0
    next_particle_id: int = 0
    emitted_events: list[dict[str, Any]] = field(default_factory=list)
    renderer_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    trail_history: dict[int, list[Vec3]] = field(default_factory=dict)
    solver_profile: str = "particle_realtime"
    backend_preference: str = "auto"
    workflow: dict[str, Any] = field(default_factory=dict)
    performance_contract: dict[str, Any] = field(default_factory=dict)
    performance_metrics: dict[str, Any] = field(default_factory=dict)
    data_channels: dict[str, FxDataChannel] = field(default_factory=dict)
    data_channel_bindings: list[FxDataChannelBinding] = field(default_factory=list)
    subgraphs: dict[str, FxSubgraphDefinition] = field(default_factory=dict)
    data_channel_consumers: list[FxDataChannelConsumer] = field(default_factory=list)
    data_channel_cursors: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.effect_system.v1",
            "system_id": self.system_id,
            "name": self.name,
            "emitters": [asdict(emitter) for emitter in self.emitters],
            "event_bindings": [asdict(binding) for binding in self.event_bindings],
            "parameters": dict(self.parameters),
            "quality": self.quality,
            "deterministic_seed": self.deterministic_seed,
            "renderer_metadata": dict(self.renderer_metadata),
            "solver_profile": self.solver_profile,
            "backend_preference": self.backend_preference,
            "workflow": dict(self.workflow),
            "performance_contract": dict(self.performance_contract),
            "performance_metrics": dict(self.performance_metrics),
            "data_channels": {key: value.to_dict() for key, value in self.data_channels.items()},
            "data_channel_bindings": [asdict(binding) for binding in self.data_channel_bindings],
            "subgraphs": {key: value.to_dict() for key, value in self.subgraphs.items()},
            "data_channel_consumers": [asdict(consumer) for consumer in self.data_channel_consumers],
        }


def module(module_type: str, phase: str = "update", **parameters: Any) -> EffectModule:
    return EffectModule(module_type, phase, True, parameters)


def create_effect_world(preset: str, *, quality: str = "high", seed: int = 1) -> SimulationWorld:
    quality_key = str(quality or "high").strip().lower()
    profile = QUALITY_PROFILES.get(quality_key, QUALITY_PROFILES["high"])
    world = SimulationWorld(fields=[], substeps=max(1, int(profile.solver_substeps)), constraint_iterations=1, self_collision=False)
    world.plane_colliders.append(PlaneCollider())
    world.effect_system = create_effect_preset(preset, quality=quality_key, seed=seed)
    return world


def create_effect_preset(preset: str, *, quality: str = "high", seed: int = 1) -> EffectSystem:
    key = str(preset or "sparks").strip().lower().replace(" ", "_")
    builders = {
        "sparks": _sparks,
        "explosion": _explosion,
        "portal": _portal,
        "magic_ribbons": _magic_ribbons,
        "lightning": _lightning,
        "fireworks": _fireworks,
        "rain": _rain,
        "snow": _snow,
        "dust": _dust,
        "disintegration": _disintegration,
        "shield_impact": _shield_impact,
        "tornado": _tornado,
        "plasma_arc": _plasma_arc,
        "chain_lightning": _chain_lightning,
        "tesla_coil": _tesla_coil,
        "electrical_storm": _electrical_storm,
        "refractive_bubbles": _refractive_bubbles,
        "heat_haze": _heat_haze,
        "fog": _fog,
        "clouds": _clouds,
        "sandstorm": _sandstorm,
        "hurricane": _hurricane,
        "volcano": _volcano,
        "mudslide": _mudslide,
        "avalanche": _avalanche,
        "earthquake": _earthquake,
        "aurora": _aurora,
    }
    if key not in builders:
        raise KeyError(f"Unknown TC effect preset: {preset}")
    system = builders[key]()
    system.quality = quality if quality in QUALITY_PROFILES else "high"
    system.deterministic_seed = int(seed)
    system.renderer_metadata = {emitter.emitter_id: dict(emitter.renderer) for emitter in system.emitters}
    solver = solver_profile_for_preset(key)
    system.solver_profile = solver.profile_id
    system.performance_contract = asdict(FxPerformanceContract(
        target_frame_ms=QUALITY_PROFILES[system.quality].target_frame_ms,
        maximum_particles=QUALITY_PROFILES[system.quality].max_particles,
    ))
    system.workflow = build_fx_workflow_plan(
        system.solver_profile,
        quality=system.quality,
        requested_backend=system.backend_preference,
        performance=FxPerformanceContract(**system.performance_contract),
    ).to_dict()
    return system


def effect_preset_names() -> list[str]:
    return [
        "sparks", "explosion", "portal", "magic_ribbons", "lightning", "chain_lightning",
        "tesla_coil", "electrical_storm", "fireworks",
        "refractive_bubbles", "heat_haze",
        "rain", "snow", "dust", "fog", "clouds", "sandstorm", "hurricane", "volcano",
        "mudslide", "avalanche", "earthquake", "aurora", "disintegration", "shield_impact",
        "tornado", "plasma_arc",
    ]


def set_emitter_renderer(
    system: EffectSystem,
    emitter_id: str,
    renderer_type: str,
    *,
    asset_id: str = "",
    renderer_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    emitter = _emitter(system, emitter_id)
    if emitter is None:
        raise KeyError(f"Effect emitter does not exist: {emitter_id}")
    emitter.renderer = {"type": str(renderer_type), **dict(renderer_parameters or {})}
    if asset_id:
        emitter.renderer["asset_id"] = str(asset_id)
    system.renderer_metadata[emitter_id] = dict(emitter.renderer)
    return dict(emitter.renderer)


def effect_emitter_anchor(emitter: EffectEmitter) -> Vec3:
    """Return a stable manipulation anchor for every supported spawn shape."""
    shape = dict(emitter.spawn_shape or {})
    if "center" in shape or str(shape.get("type") or "point").lower() not in {"line", "beam"}:
        return _vec(shape.get("center", (0.0, 0.0, 0.0)))
    start = _vec(shape.get("start", (0.0, 0.0, 0.0)))
    end = _vec(shape.get("end", start))
    return _scale(_add(start, end), 0.5)


def set_effect_emitter_interactive(
    system: EffectSystem, emitter_id: str, active: bool, *, spawn_rate: float | None = None
) -> EffectEmitter:
    emitter = _emitter(system, emitter_id)
    if emitter is None:
        raise KeyError(f"Effect emitter does not exist: {emitter_id}")
    emitter.interactive_active = bool(active)
    if active:
        emitter.enabled = True
        emitter.age = min(emitter.age, emitter.duration)
    if spawn_rate is not None:
        emitter.interactive_spawn_rate = max(0.0, float(spawn_rate))
    return emitter


def move_effect_emitter(
    system: EffectSystem,
    emitter_id: str,
    position: Vec3,
    *,
    world: SimulationWorld | None = None,
    move_live_particles: bool = False,
) -> Vec3:
    """Translate an emitter and its local spatial modules to a world-space anchor."""
    emitter = _emitter(system, emitter_id)
    if emitter is None:
        raise KeyError(f"Effect emitter does not exist: {emitter_id}")
    target = _vec(position)
    previous = effect_emitter_anchor(emitter)
    delta = _subtract(target, previous)
    shape = emitter.spawn_shape
    kind = str(shape.get("type") or "point").lower()
    if kind in {"line", "beam"}:
        shape["start"] = _add(_vec(shape.get("start", previous)), delta)
        shape["end"] = _add(_vec(shape.get("end", previous)), delta)
    else:
        shape["center"] = target
    for item in emitter.modules:
        if item.module_type in {"point_attractor", "vortex", "orbit", "jiggle"}:
            center_key = "target" if item.module_type == "jiggle" else "center"
            local_center = _vec(item.parameters.get(center_key, previous))
            item.parameters[center_key] = _add(local_center, delta)
    if move_live_particles and world is not None:
        moved_particle_ids: set[int] = set()
        for particle in world.particles:
            if particle.alive and particle.emitter_id == emitter.emitter_id:
                particle.position = _add(particle.position, delta)
                moved_particle_ids.add(particle.particle_id)
                if "jiggle_anchor" in particle.effect_attributes:
                    particle.effect_attributes["jiggle_anchor"] = _add(
                        _vec(particle.effect_attributes["jiggle_anchor"]), delta
                    )
        for particle_id in moved_particle_ids:
            trail = system.trail_history.get(particle_id)
            if trail:
                system.trail_history[particle_id] = [_add(_vec(point), delta) for point in trail]
    system.parameters["interactive_emitter"] = {
        "emitter_id": emitter.emitter_id,
        "position": target,
        "active": emitter.interactive_active,
    }
    return target


def set_effect_parameter(system: EffectSystem, path: str, value: Any) -> Any:
    parts = [part for part in str(path or "").split(".") if part]
    if parts == ["quality"]:
        quality = str(value or "high").strip().lower()
        if quality not in QUALITY_PROFILES:
            raise KeyError(f"Unknown effect quality profile: {value}")
        system.quality = quality
        contract_values = dict(system.performance_contract)
        contract_values.update({
            "target_frame_ms": QUALITY_PROFILES[quality].target_frame_ms,
            "maximum_particles": QUALITY_PROFILES[quality].max_particles,
        })
        contract = FxPerformanceContract(**contract_values).normalized()
        system.performance_contract = asdict(contract)
        system.workflow = build_fx_workflow_plan(
            system.solver_profile,
            quality=quality,
            requested_backend=system.backend_preference,
            performance=contract,
        ).to_dict()
        return quality
    if parts == ["deterministic_seed"]:
        system.deterministic_seed = max(0, int(value))
        return system.deterministic_seed
    if parts == ["solver_profile"]:
        profile_id = str(value or "particle_realtime")
        plan = build_fx_workflow_plan(
            profile_id,
            quality=system.quality,
            requested_backend=system.backend_preference,
            performance=FxPerformanceContract(**system.performance_contract),
        )
        system.solver_profile = profile_id
        system.workflow = plan.to_dict()
        return profile_id
    if parts == ["backend_preference"]:
        backend = str(value or "auto")
        if backend not in {"auto", "reference_cpu", "native_cpu", "gpu_compute"}:
            raise KeyError(f"Unknown simulation backend: {value}")
        system.backend_preference = backend
        system.workflow = build_fx_workflow_plan(
            system.solver_profile,
            quality=system.quality,
            requested_backend=backend,
            performance=FxPerformanceContract(**system.performance_contract),
        ).to_dict()
        return backend
    if len(parts) == 2 and parts[0] == "performance_contract":
        if parts[1] not in FxPerformanceContract.__dataclass_fields__:
            raise KeyError(f"Unknown performance contract property: {parts[1]}")
        values = dict(system.performance_contract)
        values[parts[1]] = value
        normalized = FxPerformanceContract(**values).normalized()
        system.performance_contract = asdict(normalized)
        system.workflow = build_fx_workflow_plan(
            system.solver_profile,
            quality=system.quality,
            requested_backend=system.backend_preference,
            performance=normalized,
        ).to_dict()
        return system.performance_contract[parts[1]]
    if len(parts) >= 2 and parts[0] == "parameters":
        system.parameters[parts[1]] = value
        return value
    if len(parts) < 3 or parts[0] not in {"emitter", "emitters"}:
        raise ValueError("Use parameters.NAME, emitter.ID.PROPERTY, or emitter.ID.module.TYPE.PARAMETER.")
    emitter = _emitter(system, parts[1])
    if emitter is None:
        raise KeyError(f"Effect emitter does not exist: {parts[1]}")
    if parts[2] == "module" and len(parts) >= 5:
        target = next((item for item in emitter.modules if item.module_type == parts[3]), None)
        if target is None:
            raise KeyError(f"Emitter {emitter.emitter_id} has no {parts[3]} module.")
        target.parameters[parts[4]] = value
        return value
    if not hasattr(emitter, parts[2]) or parts[2].startswith("_"):
        raise AttributeError(f"Emitter parameter is not editable: {parts[2]}")
    setattr(emitter, parts[2], value)
    return getattr(emitter, parts[2])


def add_effect_jiggle(
    system: EffectSystem,
    emitter_id: str,
    *,
    stiffness: float = 35.0,
    damping: float = 8.0,
    influence: float = 1.0,
    max_offset: float = 1.0,
    target: Vec3 | None = None,
) -> EffectModule:
    """Tether effect particles to an authored target with spring secondary motion."""
    emitter = _emitter(system, emitter_id)
    if emitter is None:
        raise KeyError(f"Effect emitter does not exist: {emitter_id}")
    parameters = {
        "stiffness": max(0.0, float(stiffness)),
        "damping": max(0.0, float(damping)),
        "influence": max(0.0, min(1.0, float(influence))),
        "max_offset": max(0.0, float(max_offset)),
    }
    if target is not None:
        parameters["target"] = _vec(target)
    result = module("jiggle", **parameters)
    emitter.modules.append(result)
    return result


def bake_effect_system(
    world: SimulationWorld,
    *,
    start_frame: int = 1,
    end_frame: int = 120,
    frame_rate: float = 24.0,
    progress_callback: Any | None = None,
    cancel_event: Any | None = None,
):
    from tech_connector.game_engine.runtime.tc_simulation_service import SimulationCache

    if world.effect_system is None:
        raise ValueError("The world has no effect system to bake.")
    baked_world = copy.deepcopy(world)
    cache = SimulationCache(frame_rate=float(frame_rate), metadata={
        "kind": "effect_bake", "effect_system": baked_world.effect_system.to_dict(),
        "start_frame": int(start_frame), "end_frame": int(end_frame),
    })
    cache.set_stage_state("simulate", "running", detail="Baking deterministic effect frames.")
    first_frame = int(start_frame)
    last_frame = int(end_frame)
    total_frames = max(0, last_frame - first_frame + 1)
    for completed, frame in enumerate(range(first_frame, last_frame + 1), start=1):
        if cancel_event is not None and cancel_event.is_set():
            cache.metadata["canceled"] = True
            break
        if frame > int(start_frame):
            baked_world.step(1.0 / max(1.0, float(frame_rate)))
        cache.store(baked_world.capture_frame(frame))
        if callable(progress_callback):
            progress_callback(completed, total_frames, frame)
    cache.metadata["baked_frame_count"] = len(cache.frames)
    if cache.frames:
        cache.checkpoint(max(cache.frames), stage_id="simulate")
    cache.set_stage_state(
        "simulate", "skipped" if cache.metadata.get("canceled") else "cached",
        detail="Canceled by the user." if cache.metadata.get("canceled") else "Simulation frames are reusable.",
    )
    return cache


def configure_electric_arc(
    system: EffectSystem,
    source: Vec3,
    target: Vec3,
    *,
    branch_count: int = 5,
    conductivity: float = 1.0,
) -> dict[str, Any]:
    beam = next((emitter for emitter in system.emitters if str(emitter.renderer.get("type")) == "beam"), None)
    if beam is None:
        raise ValueError("The effect system has no electrical beam emitter.")
    beam.spawn_shape.update({"type": "beam", "start": tuple(source), "end": tuple(target)})
    beam.spawn_rate = max(24.0, 80.0 * max(0.05, float(conductivity)))
    system.parameters["electric_arc"] = {
        "source": tuple(source), "target": tuple(target),
        "branch_count": max(0, int(branch_count)), "conductivity": float(conductivity),
    }
    return dict(system.parameters["electric_arc"])


def prepare_effect_step(system: EffectSystem, world: SimulationWorld, dt: float) -> None:
    profile = QUALITY_PROFILES.get(system.quality, QUALITY_PROFILES["high"])
    _apply_solver_material_controls(system, world)
    contract = FxPerformanceContract(**dict(system.performance_contract or {})).normalized()
    simulation_particle_budget = min(profile.max_particles, contract.maximum_particles)
    emitters_by_id = {emitter.emitter_id: emitter for emitter in system.emitters}
    system.emitted_events.clear()
    budget_rejected = 0
    alive_by_emitter: dict[str, int] = {}
    for particle in world.particles:
        if particle.alive and particle.effect_attributes.get("system_id") == system.system_id:
            alive_by_emitter[particle.emitter_id] = alive_by_emitter.get(particle.emitter_id, 0) + 1
    alive_count = sum(alive_by_emitter.values())
    for consumer in system.data_channel_consumers:
        channel = system.data_channels.get(consumer.channel_id)
        target = emitters_by_id.get(consumer.target_emitter)
        if channel is None or target is None or not target.enabled:
            continue
        cursor = system.data_channel_cursors.get(consumer.channel_id, -1)
        for channel_event in channel.read_since(cursor, through_tick=system.frame + 1):
            requested_count = max(0, int(channel_event.values.get(consumer.spawn_count_field, consumer.spawn_count))) \
                if consumer.spawn_count_field else max(0, int(consumer.spawn_count))
            available = max(0, simulation_particle_budget - alive_count)
            if int(target.max_particles) > 0:
                available = min(available, max(0, int(target.max_particles) - alive_by_emitter.get(target.emitter_id, 0)))
            spawn_count = min(requested_count, available)
            budget_rejected += requested_count - spawn_count
            position = channel_event.values.get(consumer.position_field)
            velocity = channel_event.values.get(consumer.velocity_field, (0.0, 0.0, 0.0))
            if spawn_count:
                _spawn_particles(
                    system, target, world, spawn_count,
                    override_position=tuple(position) if position is not None else None,
                    inherited_velocity=_scale(_vec(velocity), consumer.velocity_scale),
                )
                alive_count += spawn_count
                alive_by_emitter[target.emitter_id] = alive_by_emitter.get(target.emitter_id, 0) + spawn_count
            system.data_channel_cursors[consumer.channel_id] = channel_event.sequence
    for emitter in system.emitters:
        if not emitter.enabled:
            continue
        emitter.age += dt
        active = emitter.interactive_active or emitter.looping or emitter.age <= emitter.duration
        spawn_count = 0
        if active and not emitter.event_only:
            effective_spawn_rate = max(
                emitter.spawn_rate,
                emitter.interactive_spawn_rate if emitter.interactive_active else 0.0,
            )
            requested = effective_spawn_rate * profile.spawn_scale * dt + emitter.spawn_remainder
            spawn_count = int(requested)
            emitter.spawn_remainder = requested - spawn_count
            if not emitter.burst_emitted:
                spawn_count += max(0, int(round(emitter.burst_count * profile.spawn_scale)))
                emitter.burst_emitted = True
        available = max(0, simulation_particle_budget - alive_count)
        if int(emitter.max_particles) > 0:
            available = min(available, max(0, int(emitter.max_particles) - alive_by_emitter.get(emitter.emitter_id, 0)))
        requested_spawn_count = spawn_count
        spawn_count = min(spawn_count, available)
        budget_rejected += max(0, requested_spawn_count - spawn_count)
        if spawn_count:
            _spawn_particles(system, emitter, world, spawn_count)
            alive_count += spawn_count
            alive_by_emitter[emitter.emitter_id] = alive_by_emitter.get(emitter.emitter_id, 0) + spawn_count
    if system.frame % max(1, profile.update_stride) == 0:
        for particle in world.particles:
            if not particle.alive or particle.effect_attributes.get("system_id") != system.system_id:
                continue
            emitter = emitters_by_id.get(particle.emitter_id)
            update_divisor = max(1, int(getattr(emitter, "update_rate_divisor", 1))) if emitter is not None else 1
            if emitter is not None and system.frame % (max(1, profile.update_stride) * update_divisor) == 0:
                _apply_update_modules(system, emitter, particle, dt * profile.update_stride * update_divisor)
    system.performance_metrics = {
        "alive_particles": alive_count,
        "particle_budget": simulation_particle_budget,
        "budget_rejected_spawns": budget_rejected,
        "budget_pressure": alive_count / max(1, simulation_particle_budget),
        "adaptive": contract.adaptive,
        "overflow_policy": contract.overflow_policy,
        "target_frame_ms": contract.target_frame_ms,
    }
    if budget_rejected:
        system.emitted_events.append({
            "type": "performance_budget",
            "rejected_spawns": budget_rejected,
            "policy": contract.overflow_policy,
        })


def finish_effect_step(system: EffectSystem, world: SimulationWorld, dt: float) -> None:
    pending_events = []
    emitters_by_id = {emitter.emitter_id: emitter for emitter in system.emitters}
    bindings_by_event: dict[tuple[str, str], list[EffectEventBinding]] = {}
    for binding in system.event_bindings:
        bindings_by_event.setdefault((binding.source_emitter, binding.event_type), []).append(binding)
    for particle in world.particles:
        if not particle.alive or particle.effect_attributes.get("system_id") != system.system_id:
            continue
        particle.age += dt
        particle.rotation += particle.angular_velocity * dt
        emitter = emitters_by_id.get(particle.emitter_id)
        if emitter is None:
            continue
        _apply_over_life_modules(emitter, particle)
        renderer_type = str(emitter.renderer.get("type") or "sprite").lower()
        if renderer_type in {"ribbon", "beam", "line"} or "trail_length" in emitter.renderer:
            trail = system.trail_history.setdefault(particle.particle_id, [])
            trail.append(particle.position)
            maximum_trail = max(2, int(emitter.renderer.get("trail_length", 12)))
            if len(trail) > maximum_trail:
                del trail[:-maximum_trail]
        previous_y = float(particle.effect_attributes.get("previous_y", particle.position[1]))
        if previous_y > particle.radius and particle.position[1] <= particle.radius + 1.0e-5:
            pending_events.append((particle, "collision"))
            if world.deformable_surfaces and not particle.effect_attributes.get("surface_impact_applied"):
                interaction = dict(particle.effect_attributes.get("surface_interaction") or {})
                if interaction:
                    surface = world.deformable_surfaces[0]
                    surface.apply_projectile(
                        particle.position, particle.velocity,
                        energy=float(interaction.get("energy", max(0.1, _length(particle.velocity) ** 2))),
                        radius=float(interaction.get("radius", particle.radius)),
                        thickness=float(interaction.get("thickness", 0.1)),
                    )
                    particle.effect_attributes["surface_impact_applied"] = True
        particle.effect_attributes["previous_y"] = particle.position[1]
        if particle.lifetime > 0.0 and particle.age >= particle.lifetime:
            particle.alive = False
            system.trail_history.pop(particle.particle_id, None)
            pending_events.append((particle, "death"))
    for particle, event_type in pending_events:
        event = {"type": event_type, "emitter_id": particle.emitter_id, "position": particle.position, "velocity": particle.velocity}
        system.emitted_events.append(event)
        for binding in bindings_by_event.get((particle.emitter_id, event_type), ()):
            target = emitters_by_id.get(binding.target_emitter)
            if target is not None:
                _spawn_particles(
                    system, target, world, binding.spawn_count,
                    override_position=particle.position,
                    inherited_velocity=_scale(particle.velocity, binding.inherit_velocity),
                )
    publish_bound_effect_events(system, tick=system.frame + 1)
    for channel in system.data_channels.values():
        channel.expire(system.frame + 1)
    system.frame += 1
    if system.frame % 60 == 0:
        _compact_dead_effect_particles(system, world)


def _compact_dead_effect_particles(system: EffectSystem, world: SimulationWorld) -> int:
    """Remove expired effect particles when no index-based physics constraints can reference them."""
    if any((world.constraints, world.volume_constraints, world.area_constraints, world.attachments)):
        return 0
    matching = [
        particle for particle in world.particles
        if particle.effect_attributes.get("system_id") == system.system_id
    ]
    dead_count = sum(1 for particle in matching if not particle.alive)
    system_inactive = all(
        not emitter.enabled or (not emitter.looping and emitter.age > emitter.duration)
        for emitter in system.emitters
    )
    if dead_count < max(256, len(matching) // 4) and not system_inactive:
        return 0
    world.particles = [
        particle for particle in world.particles
        if particle.alive or particle.effect_attributes.get("system_id") != system.system_id
    ]
    live_ids = {
        particle.particle_id for particle in world.particles
        if particle.alive and particle.effect_attributes.get("system_id") == system.system_id
    }
    system.trail_history = {
        particle_id: trail for particle_id, trail in system.trail_history.items()
        if particle_id in live_ids
    }
    return dead_count


def _spawn_particles(
    system: EffectSystem,
    emitter: EffectEmitter,
    world: SimulationWorld,
    count: int,
    *,
    override_position: Vec3 | None = None,
    inherited_velocity: Vec3 = (0.0, 0.0, 0.0),
) -> None:
    for _index in range(max(0, int(count))):
        particle_id = system.next_particle_id
        system.next_particle_id += 1
        rng = random.Random(system.deterministic_seed * 1000003 + particle_id * 9176)
        position, shape_velocity = _sample_shape(emitter.spawn_shape, rng)
        if override_position is not None:
            position = override_position
        phase, material, state = _solver_particle_state(system.solver_profile)
        particle = SimulationParticle(
            position,
            velocity=_add(shape_velocity, inherited_velocity),
            radius=0.025,
            material=material,
            phase=phase,
            state=state,
            emitter_id=emitter.emitter_id,
            particle_id=particle_id,
            effect_attributes={"system_id": system.system_id, "previous_y": position[1]},
        )
        _apply_spawn_modules(emitter, particle, rng)
        if any(item.enabled and item.module_type == "jiggle" for item in emitter.modules):
            particle.effect_attributes["jiggle_anchor"] = particle.position
        world.particles.append(particle)


def _solver_particle_state(solver_profile: str) -> tuple[str, str, str]:
    return {
        "flip_liquid": ("fluid", "water", "liquid"),
        "viscous_goop": ("fluid", "goo", "viscous"),
        "granular": ("granular", "granular", "granular"),
        "destruction": ("rigid_cluster", "glass", "solid"),
        "ocean_surface": ("fluid", "water", "liquid"),
    }.get(str(solver_profile), ("effect", "effect", "energy"))


def _apply_solver_material_controls(system: EffectSystem, world: SimulationWorld) -> None:
    _phase, material_id, _state = _solver_particle_state(system.solver_profile)
    material = world.materials.get(material_id)
    if material is None:
        return
    mappings = {
        "viscosity": "viscosity",
        "cohesion": "cohesion",
        "surface_tension": "surface_tension",
        "adhesion": "adhesion",
        "yield": "yield_strength",
        "stringiness": "stringiness",
        "friction": "friction",
    }
    for control_id, attribute in mappings.items():
        parameter_name = f"solver_{control_id}"
        if parameter_name in system.parameters:
            setattr(material, attribute, max(0.0, float(system.parameters[parameter_name])))


def _sample_shape(shape: dict[str, Any], rng: random.Random) -> tuple[Vec3, Vec3]:
    kind = str(shape.get("type") or "point").lower()
    center = _vec(shape.get("center", (0.0, 0.0, 0.0)))
    if kind == "sphere":
        direction = _random_unit(rng)
        radius = float(shape.get("radius", 1.0))
        distance = radius if shape.get("surface", False) else radius * (rng.random() ** (1.0 / 3.0))
        return _add(center, _scale(direction, distance)), (0.0, 0.0, 0.0)
    if kind == "box":
        extent = _vec(shape.get("extent", (1.0, 1.0, 1.0)))
        return _add(center, tuple(rng.uniform(-extent[i], extent[i]) for i in range(3))), (0.0, 0.0, 0.0)
    if kind in {"ring", "torus"}:
        angle = rng.random() * math.tau
        radius = float(shape.get("radius", 1.0)) + rng.uniform(-1.0, 1.0) * float(shape.get("thickness", 0.05))
        return _add(center, (math.cos(angle) * radius, 0.0, math.sin(angle) * radius)), (0.0, 0.0, 0.0)
    if kind in {"line", "beam"}:
        start, end = _vec(shape.get("start", (-1.0, 0.0, 0.0))), _vec(shape.get("end", (1.0, 0.0, 0.0)))
        amount = rng.random()
        jitter = float(shape.get("jitter", 0.0))
        return _add(_add(start, _scale(_subtract(end, start), amount)), _scale(_random_unit(rng), rng.random() * jitter)), (0.0, 0.0, 0.0)
    if kind == "cone":
        axis = _normalize(_vec(shape.get("axis", (0.0, 1.0, 0.0))))
        spread = math.radians(float(shape.get("angle", 25.0)))
        direction = _normalize(_add(axis, _scale(_random_unit(rng), math.tan(spread) * math.sqrt(rng.random()))))
        return center, _scale(direction, float(shape.get("speed", 1.0)))
    return center, (0.0, 0.0, 0.0)


def _apply_spawn_modules(emitter: EffectEmitter, particle: SimulationParticle, rng: random.Random) -> None:
    for item in emitter.modules:
        if not item.enabled or item.phase != "spawn":
            continue
        values = item.parameters
        kind = item.module_type
        if kind == "initialize":
            particle.lifetime = _range(values.get("lifetime", (1.0, 1.0)), rng)
            particle.size = _range(values.get("size", (1.0, 1.0)), rng)
            particle.radius = max(0.001, float(values.get("radius", 0.025)) * particle.size)
            particle.color = _color(values.get("color", (0.85, 0.9, 1.0, 1.0)))
            particle.effect_attributes["initial_color"] = particle.color
            particle.effect_attributes["initial_size"] = particle.size
        elif kind == "add_velocity":
            velocity = _vec(values.get("velocity", (0.0, 0.0, 0.0)))
            random_speed = _range(values.get("random_speed", (0.0, 0.0)), rng)
            particle.velocity = _add(particle.velocity, _add(velocity, _scale(_random_unit(rng), random_speed)))
        elif kind == "rotation":
            particle.rotation = rng.uniform(0.0, math.tau)
            particle.angular_velocity = _range(values.get("rate", (-1.0, 1.0)), rng)
        elif kind == "surface_interaction":
            particle.effect_attributes["surface_interaction"] = dict(values)


def _apply_update_modules(system: EffectSystem, emitter: EffectEmitter, particle: SimulationParticle, dt: float) -> None:
    for item in emitter.modules:
        if not item.enabled or item.phase != "update":
            continue
        values, kind = item.parameters, item.module_type
        if kind == "gravity":
            particle.velocity = _add(particle.velocity, _scale(_vec(values.get("vector", (0.0, -9.81, 0.0))), dt))
        elif kind == "drag":
            particle.velocity = _scale(particle.velocity, math.exp(-max(0.0, float(values.get("amount", 1.0))) * dt))
        elif kind == "point_attractor":
            delta = _subtract(_vec(values.get("center", (0.0, 0.0, 0.0))), particle.position)
            particle.velocity = _add(particle.velocity, _scale(_normalize(delta), float(values.get("strength", 5.0)) * dt))
        elif kind == "vortex":
            center = _vec(values.get("center", (0.0, 0.0, 0.0)))
            axis = _normalize(_vec(values.get("axis", (0.0, 1.0, 0.0))))
            tangent = _normalize(_cross(axis, _subtract(particle.position, center)))
            particle.velocity = _add(particle.velocity, _scale(tangent, float(values.get("strength", 5.0)) * dt))
        elif kind == "curl_noise":
            frequency = float(values.get("frequency", 2.0))
            strength = float(values.get("strength", 2.0))
            x, y, z = particle.position
            time = system.frame * dt
            noise = (math.sin(y * frequency + time), math.sin(z * frequency + 2.1 + time), math.sin(x * frequency + 4.2 + time))
            particle.velocity = _add(particle.velocity, _scale(noise, strength * dt))
        elif kind == "orbit":
            axis = _normalize(_vec(values.get("axis", (0.0, 1.0, 0.0))))
            center = _vec(values.get("center", (0.0, 0.0, 0.0)))
            particle.velocity = _add(
                particle.velocity,
                _scale(_cross(axis, _subtract(particle.position, center)), float(values.get("speed", 1.0)) * dt),
            )
        elif kind == "jiggle":
            target = _vec(values.get("target", particle.effect_attributes.get("jiggle_anchor", particle.position)))
            influence = max(0.0, min(1.0, float(
                particle.effect_attributes.get("jiggle_weight", values.get("influence", 1.0))
            )))
            delta = _subtract(target, particle.position)
            max_offset = max(0.0, float(values.get("max_offset", 1.0)))
            distance = _length(delta)
            if max_offset and distance > max_offset:
                delta = _scale(delta, max_offset / max(1.0e-12, distance))
            spring = _scale(delta, max(0.0, float(values.get("stiffness", 35.0))))
            damping = _scale(particle.velocity, -max(0.0, float(values.get("damping", 8.0))))
            particle.velocity = _add(particle.velocity, _scale(_add(spring, damping), dt * influence))
        elif kind == "kill_box":
            center, extent = _vec(values.get("center", (0.0, 0.0, 0.0))), _vec(values.get("extent", (10.0, 10.0, 10.0)))
            if any(abs(particle.position[i] - center[i]) > extent[i] for i in range(3)):
                particle.alive = False


def _apply_over_life_modules(emitter: EffectEmitter, particle: SimulationParticle) -> None:
    amount = min(1.0, particle.age / max(1.0e-9, particle.lifetime)) if particle.lifetime > 0.0 else 0.0
    for item in emitter.modules:
        if not item.enabled or item.phase != "update":
            continue
        if item.module_type == "color_over_life":
            particle.color = _gradient(item.parameters.get("colors"), amount, particle.color)
        elif item.module_type == "size_over_life":
            scale = _curve(item.parameters.get("curve", ((0.0, 1.0), (1.0, 0.0))), amount)
            particle.size = float(particle.effect_attributes.get("initial_size", 1.0)) * scale


def _emitter(system: EffectSystem, emitter_id: str) -> EffectEmitter | None:
    return next((emitter for emitter in system.emitters if emitter.emitter_id == emitter_id), None)


def _emitter_template(emitter_id: str, name: str, **kwargs: Any) -> EffectEmitter:
    return EffectEmitter(emitter_id, name, **kwargs)


def _sparks() -> EffectSystem:
    sparks = _emitter_template(
        "sparks", "Impact Sparks", burst_count=72, duration=1.0,
        spawn_shape={"type": "cone", "center": (0, 0.15, 0), "axis": (0, 1, 0), "angle": 70, "speed": 5.5},
        modules=[module("initialize", "spawn", lifetime=(0.45, 1.4), size=(0.45, 1.15), color=(1.0, 0.45, 0.05, 1.0), radius=0.012), module("add_velocity", "spawn", random_speed=(0.5, 3.0)), module("gravity", vector=(0, -9.81, 0)), module("drag", amount=0.25), module("color_over_life", colors=((0, (1, .85, .2, 1)), (1, (1, .05, .01, 0)))), module("size_over_life", curve=((0, 1), (1, 0.1)))],
        renderer={"type": "ribbon", "blend": "additive", "facing": "camera", "light": True},
    )
    return EffectSystem("tcfx.sparks", "Sparks", [sparks])


def _explosion() -> EffectSystem:
    flash = _emitter_template("flash", "Flash", burst_count=8, duration=.2, spawn_shape={"type": "sphere", "radius": .18}, modules=[module("initialize", "spawn", lifetime=(.12, .25), size=(3, 5), color=(1, .75, .2, 1), radius=.08), module("size_over_life", curve=((0, .2), (.25, 1.3), (1, 0))), module("color_over_life", colors=((0, (1, 1, .8, 1)), (1, (1, .1, 0, 0))))], renderer={"type": "sprite", "blend": "additive", "light": True})
    fire = _emitter_template("fire", "Fireball", burst_count=140, duration=.8, spawn_shape={"type": "sphere", "radius": .25}, modules=[module("initialize", "spawn", lifetime=(.6, 1.5), size=(.8, 2.2), color=(1, .25, .02, 1), radius=.035), module("add_velocity", "spawn", random_speed=(1, 5)), module("drag", amount=1.4), module("curl_noise", strength=4, frequency=3), module("color_over_life", colors=((0, (1, .8, .12, 1)), (.4, (1, .12, .01, .9)), (1, (.08, .08, .08, 0)))), module("size_over_life", curve=((0, .4), (.5, 1.3), (1, .2)))], renderer={"type": "sprite", "blend": "additive"})
    smoke = _emitter_template("smoke", "Smoke", burst_count=85, duration=1, spawn_shape={"type": "sphere", "radius": .3}, modules=[module("initialize", "spawn", lifetime=(1.8, 4), size=(1.2, 2.5), color=(.12, .11, .1, .65), radius=.05), module("add_velocity", "spawn", velocity=(0, 1.2, 0), random_speed=(.2, 1)), module("drag", amount=.8), module("curl_noise", strength=2.5, frequency=1.8), module("color_over_life", colors=((0, (.15, .13, .12, .55)), (1, (.04, .04, .04, 0)))), module("size_over_life", curve=((0, .4), (1, 2.2)))], renderer={"type": "volume_sprite", "blend": "alpha"})
    return EffectSystem("tcfx.explosion", "Explosion", [flash, fire, smoke])


def _portal() -> EffectSystem:
    ring = _emitter_template("ring", "Portal Ring", spawn_rate=90, duration=8, looping=True, spawn_shape={"type": "ring", "radius": 1, "thickness": .08}, modules=[module("initialize", "spawn", lifetime=(1.2, 2.2), size=(.5, 1.2), color=(.15, .35, 1, 1), radius=.018), module("vortex", strength=9), module("point_attractor", strength=1.5), module("curl_noise", strength=2, frequency=4), module("color_over_life", colors=((0, (.1, .8, 1, 0)), (.2, (.3, .2, 1, 1)), (1, (.05, 0, .3, 0))))], renderer={"type": "ribbon", "blend": "additive", "light": True})
    return EffectSystem("tcfx.portal", "Portal", [ring])


def _magic_ribbons() -> EffectSystem:
    ribbons = _emitter_template("ribbons", "Magic Ribbons", spawn_rate=48, duration=10, looping=True, spawn_shape={"type": "ring", "radius": .45, "thickness": .1}, modules=[module("initialize", "spawn", lifetime=(2.5, 4), size=(.5, 1.2), color=(.8, .2, 1, 1), radius=.018), module("add_velocity", "spawn", velocity=(0, .7, 0), random_speed=(0, .25)), module("vortex", strength=4), module("curl_noise", strength=3, frequency=2), module("color_over_life", colors=((0, (0, 1, .8, 0)), (.25, (.6, .1, 1, 1)), (1, (1, .2, .5, 0))))], renderer={"type": "ribbon", "blend": "additive"})
    return EffectSystem("tcfx.magic_ribbons", "Magic Ribbons", [ribbons])


def _lightning() -> EffectSystem:
    beam = _emitter_template("beam", "Lightning Beam", spawn_rate=120, duration=2, looping=True, spawn_shape={"type": "beam", "start": (-1, 1, 0), "end": (1, 1, 0), "jitter": .12}, modules=[module("initialize", "spawn", lifetime=(.05, .12), size=(.4, 1), color=(.5, .8, 1, 1), radius=.01), module("curl_noise", strength=7, frequency=12), module("color_over_life", colors=((0, (1, 1, 1, 1)), (1, (.1, .4, 1, 0))))], renderer={"type": "beam", "blend": "additive", "light": True})
    return EffectSystem("tcfx.lightning", "Lightning", [beam])


def _fireworks() -> EffectSystem:
    rocket = _emitter_template("rocket", "Rocket", burst_count=1, duration=1, spawn_shape={"type": "point", "center": (0, .1, 0)}, modules=[module("initialize", "spawn", lifetime=(1.1, 1.1), size=(1, 1), color=(1, .6, .1, 1), radius=.018), module("add_velocity", "spawn", velocity=(0, 5.5, 0)), module("gravity", vector=(0, -2.5, 0))], renderer={"type": "ribbon", "blend": "additive"})
    stars = _emitter_template("stars", "Star Burst", event_only=True, duration=3, spawn_shape={"type": "sphere", "radius": .02}, modules=[module("initialize", "spawn", lifetime=(1.2, 2.2), size=(.5, 1.2), color=(.2, .7, 1, 1), radius=.014), module("add_velocity", "spawn", random_speed=(2.5, 6)), module("gravity", vector=(0, -3.5, 0)), module("drag", amount=.15), module("color_over_life", colors=((0, (1, .9, .3, 1)), (.35, (.2, .6, 1, 1)), (1, (.1, .1, 1, 0))))], renderer={"type": "ribbon", "blend": "additive"})
    return EffectSystem("tcfx.fireworks", "Fireworks", [rocket, stars], [EffectEventBinding("rocket", "death", "stars", 96, .1)])


def _rain() -> EffectSystem:
    rain = _emitter_template("rain", "Rain", spawn_rate=380, duration=20, looping=True, spawn_shape={"type": "box", "center": (0, 4, 0), "extent": (3, .1, 3)}, modules=[module("initialize", "spawn", lifetime=(1.2, 2), size=(.4, .8), color=(.35, .65, 1, .8), radius=.009), module("add_velocity", "spawn", velocity=(.3, -7, 0)), module("gravity", vector=(0, -3, 0))], renderer={"type": "ribbon", "blend": "alpha", "material_mode": "refractive", "transmission": .88, "ior": 1.33, "thickness": .04, "roughness": .03})
    return EffectSystem("tcfx.rain", "Rain", [rain])


def _snow() -> EffectSystem:
    snow = _emitter_template("snow", "Snow", spawn_rate=120, duration=30, looping=True, spawn_shape={"type": "box", "center": (0, 4, 0), "extent": (3, .1, 3)}, modules=[module("initialize", "spawn", lifetime=(4, 7), size=(.6, 1.5), color=(.9, .95, 1, .9), radius=.018), module("add_velocity", "spawn", velocity=(0, -.7, 0), random_speed=(0, .25)), module("curl_noise", strength=.8, frequency=1.4), module("rotation", "spawn", rate=(-2, 2))], renderer={"type": "sprite", "blend": "alpha"})
    return EffectSystem("tcfx.snow", "Snow", [snow])


def _dust() -> EffectSystem:
    dust = _emitter_template("dust", "Dust", spawn_rate=65, duration=20, looping=True, spawn_shape={"type": "box", "center": (0, .5, 0), "extent": (2, .5, 2)}, modules=[module("initialize", "spawn", lifetime=(3, 8), size=(.5, 1.8), color=(.58, .45, .28, .35), radius=.025), module("curl_noise", strength=.45, frequency=.8), module("drag", amount=.6), module("color_over_life", colors=((0, (.6, .5, .3, 0)), (.2, (.6, .5, .3, .4)), (1, (.3, .25, .18, 0))))], renderer={"type": "volume_sprite", "blend": "alpha"})
    return EffectSystem("tcfx.dust", "Dust", [dust])


def _disintegration() -> EffectSystem:
    dissolve = _emitter_template("fragments", "Disintegration", burst_count=420, duration=3, spawn_shape={"type": "box", "center": (0, 1, 0), "extent": (.7, 1, .35)}, modules=[module("initialize", "spawn", lifetime=(1.5, 4), size=(.25, .8), color=(.1, 1, .65, 1), radius=.012), module("add_velocity", "spawn", velocity=(0, .4, 0), random_speed=(.1, .8)), module("curl_noise", strength=2.2, frequency=3), module("point_attractor", center=(0, 2.5, 0), strength=1), module("color_over_life", colors=((0, (.05, 1, .5, 1)), (1, (.2, 0, .5, 0)))), module("size_over_life", curve=((0, 1), (1, 0)))], renderer={"type": "mesh", "mesh": "fragment", "blend": "additive"})
    return EffectSystem("tcfx.disintegration", "Disintegration", [dissolve])


def _shield_impact() -> EffectSystem:
    shield = _emitter_template("shield", "Shield Impact", burst_count=180, duration=1, spawn_shape={"type": "ring", "radius": .2, "thickness": .02}, modules=[module("initialize", "spawn", lifetime=(.4, 1.2), size=(.5, 1.3), color=(.1, .7, 1, .72), radius=.015), module("add_velocity", "spawn", random_speed=(.5, 2)), module("point_attractor", strength=-1.5), module("color_over_life", colors=((0, (1, 1, 1, .8)), (.2, (.1, .8, 1, .65)), (1, (.2, 0, 1, 0))))], renderer={"type": "decal", "blend": "alpha", "material_mode": "refractive", "transmission": .75, "ior": 1.55, "thickness": .12, "roughness": .08, "clearcoat": .8, "light": True})
    return EffectSystem("tcfx.shield", "Shield Impact", [shield])


def _tornado() -> EffectSystem:
    funnel = _emitter_template("funnel", "Tornado", spawn_rate=180, duration=20, looping=True, spawn_shape={"type": "ring", "radius": 1.2, "thickness": .4}, modules=[module("initialize", "spawn", lifetime=(3, 6), size=(.7, 1.8), color=(.3, .28, .25, .45), radius=.025), module("add_velocity", "spawn", velocity=(0, .8, 0)), module("vortex", strength=12), module("point_attractor", center=(0, 1.5, 0), strength=1.5), module("curl_noise", strength=2, frequency=2), module("color_over_life", colors=((0, (.3, .25, .2, 0)), (.2, (.35, .32, .28, .5)), (1, (.2, .2, .2, 0))))], renderer={"type": "volume_sprite", "blend": "alpha"})
    return EffectSystem("tcfx.tornado", "Tornado", [funnel])


def _plasma_arc() -> EffectSystem:
    arc = _lightning()
    arc.system_id, arc.name = "tcfx.plasma_arc", "Plasma Arc"
    arc.emitters[0].modules.append(module("vortex", strength=4, axis=(1, 0, 0)))
    arc.emitters[0].renderer["light"] = True
    return arc


def _chain_lightning() -> EffectSystem:
    main = _lightning().emitters[0]
    main.emitter_id, main.name = "main_arc", "Chain Lightning"
    branches = _emitter_template("branches", "Arc Branches", spawn_rate=180, duration=2, looping=True, spawn_shape={"type": "beam", "start": (-1, 1, 0), "end": (1, 1, 0), "jitter": .45}, modules=[module("initialize", "spawn", lifetime=(.035, .09), size=(.2, .65), color=(.35, .65, 1, .9), radius=.007), module("curl_noise", strength=11, frequency=18), module("color_over_life", colors=((0, (1, 1, 1, 1)), (1, (.1, .2, 1, 0))))], renderer={"type": "beam", "blend": "additive", "light": True})
    system = EffectSystem("tcfx.chain_lightning", "Chain Lightning", [main, branches], parameters={"electric_arc": {"branch_count": 7, "conductivity": 1.0, "chain_radius": 4.0}})
    return system


def _tesla_coil() -> EffectSystem:
    arcs = _chain_lightning()
    arcs.system_id, arcs.name = "tcfx.tesla_coil", "Tesla Coil"
    for emitter in arcs.emitters:
        emitter.spawn_shape.update({"start": (0, 1.2, 0), "end": (1.8, 2.2, 0), "jitter": .65})
        emitter.duration = 20
        emitter.looping = True
    arcs.parameters["electric_arc"].update({"branch_count": 12, "pulse_frequency": 8.0})
    return arcs


def _electrical_storm() -> EffectSystem:
    clouds = _clouds().emitters[0]
    clouds.emitter_id, clouds.name = "storm_clouds", "Charged Storm Clouds"
    bolts = _emitter_template("storm_bolts", "Cloud To Ground Bolts", spawn_rate=35, duration=30, looping=True, spawn_shape={"type": "beam", "start": (-3, 5, 0), "end": (3, 0, 0), "jitter": .8}, modules=[module("initialize", "spawn", lifetime=(.04, .14), size=(.35, 1), color=(.55, .75, 1, 1), radius=.012), module("curl_noise", strength=13, frequency=16), module("surface_interaction", "spawn", energy=25, radius=.06, thickness=.15), module("color_over_life", colors=((0, (1, 1, 1, 1)), (1, (.1, .3, 1, 0))))], renderer={"type": "beam", "blend": "additive", "light": True})
    return EffectSystem("tcfx.electrical_storm", "Electrical Storm", [clouds, bolts], parameters={"weather_type": "electrical_storm", "electric_arc": {"branch_count": 10, "conductivity": .8}, "camera_shake": .18})


def _fog() -> EffectSystem:
    emitter = _emitter_template("fog", "Ground Fog", spawn_rate=55, duration=30, looping=True, spawn_shape={"type": "box", "center": (0, .3, 0), "extent": (4, .25, 4)}, modules=[module("initialize", "spawn", lifetime=(8, 16), size=(2, 5), color=(.62, .68, .72, .22), radius=.08), module("add_velocity", "spawn", velocity=(.12, 0, .04), random_speed=(0, .08)), module("curl_noise", strength=.18, frequency=.35), module("drag", amount=.9), module("color_over_life", colors=((0, (.7, .75, .8, 0)), (.25, (.6, .66, .7, .25)), (1, (.5, .55, .6, 0)))), module("size_over_life", curve=((0, .5), (1, 2.5)))], renderer={"type": "volume_sprite", "blend": "alpha", "soft_particles": True})
    return EffectSystem("tcfx.fog", "Ground Fog", [emitter], parameters={"weather_type": "fog", "visibility": .45})


def _clouds() -> EffectSystem:
    emitter = _emitter_template("clouds", "Cloud Bank", spawn_rate=18, duration=60, looping=True, spawn_shape={"type": "box", "center": (0, 5, 0), "extent": (6, .8, 4)}, modules=[module("initialize", "spawn", lifetime=(20, 45), size=(4, 9), color=(.72, .76, .82, .5), radius=.12), module("add_velocity", "spawn", velocity=(.18, 0, .03)), module("curl_noise", strength=.12, frequency=.22), module("color_over_life", colors=((0, (.75, .78, .82, 0)), (.15, (.72, .74, .8, .55)), (1, (.55, .58, .65, 0))))], renderer={"type": "volume", "blend": "alpha", "shadow": True})
    return EffectSystem("tcfx.clouds", "Cloud Bank", [emitter], parameters={"weather_type": "clouds", "coverage": .7})


def _sandstorm() -> EffectSystem:
    sand = _emitter_template("sand", "Driven Sand", spawn_rate=420, duration=30, looping=True, spawn_shape={"type": "box", "center": (-3, 1.2, 0), "extent": (.2, 1.2, 3)}, modules=[module("initialize", "spawn", lifetime=(2, 5), size=(.3, 1.2), color=(.68, .45, .2, .55), radius=.012), module("add_velocity", "spawn", velocity=(5.5, .15, 0), random_speed=(0, 1)), module("curl_noise", strength=1.8, frequency=1.2), module("drag", amount=.08), module("color_over_life", colors=((0, (.75, .5, .2, 0)), (.2, (.7, .43, .16, .65)), (1, (.45, .25, .1, 0))))], renderer={"type": "volume_sprite", "blend": "alpha"})
    return EffectSystem("tcfx.sandstorm", "Sandstorm", [sand], parameters={"weather_type": "sandstorm", "wind": (5.5, .15, 0), "visibility": .2})


def _hurricane() -> EffectSystem:
    rain = _rain().emitters[0]
    rain.emitter_id, rain.name, rain.spawn_rate = "hurricane_rain", "Hurricane Rain", 650
    for item in rain.modules:
        if item.module_type == "add_velocity":
            item.parameters["velocity"] = (5.5, -6.0, 1.5)
    bands = _emitter_template("bands", "Spiral Cloud Bands", spawn_rate=150, duration=40, looping=True, spawn_shape={"type": "ring", "radius": 2.8, "thickness": 1.2}, modules=[module("initialize", "spawn", lifetime=(5, 10), size=(1.5, 4), color=(.5, .56, .64, .5), radius=.05), module("vortex", strength=18), module("point_attractor", strength=2.5), module("add_velocity", "spawn", velocity=(0, .3, 0)), module("curl_noise", strength=2, frequency=.8)], renderer={"type": "volume_sprite", "blend": "alpha"})
    debris = _emitter_template("debris", "Wind Debris", spawn_rate=38, duration=40, looping=True, spawn_shape={"type": "ring", "radius": 2.2, "thickness": 1}, modules=[module("initialize", "spawn", lifetime=(2, 6), size=(.5, 1.5), color=(.25, .2, .14, 1), radius=.025), module("vortex", strength=22), module("point_attractor", strength=3), module("add_velocity", "spawn", velocity=(0, 1, 0)), module("rotation", "spawn", rate=(-8, 8))], renderer={"type": "mesh", "asset_id": "environment_debris"})
    return EffectSystem("tcfx.hurricane", "Hurricane", [rain, bands, debris], parameters={"weather_type": "hurricane", "wind_speed": 42.0, "camera_shake": .35})


def _volcano() -> EffectSystem:
    ash = _emitter_template("ash", "Volcanic Ash Column", spawn_rate=240, duration=30, looping=True, spawn_shape={"type": "cone", "center": (0, .2, 0), "axis": (0, 1, 0), "angle": 16, "speed": 3.2}, modules=[module("initialize", "spawn", lifetime=(5, 12), size=(1, 4), color=(.1, .08, .07, .7), radius=.04), module("curl_noise", strength=3.5, frequency=1), module("drag", amount=.35), module("size_over_life", curve=((0, .3), (1, 2.8)))], renderer={"type": "volume", "blend": "alpha", "shadow": True})
    lava = _emitter_template("lava", "Lava Bombs", spawn_rate=18, burst_count=45, duration=12, spawn_shape={"type": "cone", "center": (0, .3, 0), "axis": (0, 1, 0), "angle": 48, "speed": 7}, modules=[module("initialize", "spawn", lifetime=(2, 5), size=(.6, 1.8), color=(1, .12, .01, 1), radius=.03), module("gravity", vector=(0, -9.81, 0)), module("rotation", "spawn", rate=(-5, 5)), module("surface_interaction", "spawn", energy=8, radius=.04, thickness=.08), module("color_over_life", colors=((0, (1, .8, .1, 1)), (1, (.2, .01, 0, .3))))], renderer={"type": "mesh", "asset_id": "lava_bomb", "light": True})
    return EffectSystem("tcfx.volcano", "Volcano", [ash, lava], parameters={"disaster_type": "volcano", "camera_shake": .25, "ground_heat": 1200})


def _mudslide() -> EffectSystem:
    mud = _emitter_template("mud", "Mud Flow", spawn_rate=260, duration=20, looping=True, spawn_shape={"type": "box", "center": (-2, 1.2, 0), "extent": (.2, .7, 1.5)}, modules=[module("initialize", "spawn", lifetime=(4, 9), size=(.8, 2), color=(.22, .12, .06, .9), radius=.04), module("add_velocity", "spawn", velocity=(2.8, -1.4, 0), random_speed=(0, .4)), module("gravity", vector=(0, -5, 0)), module("drag", amount=.65), module("surface_interaction", "spawn", energy=3, radius=.08, thickness=.04)], renderer={"type": "metaball", "material": "mud"})
    return EffectSystem("tcfx.mudslide", "Mudslide", [mud], parameters={"disaster_type": "mudslide", "material": "mud", "erosion": True})


def _avalanche() -> EffectSystem:
    snow = _emitter_template("avalanche", "Avalanche Snow", spawn_rate=520, burst_count=700, duration=12, spawn_shape={"type": "box", "center": (-2, 2.5, 0), "extent": (.4, .8, 2)}, modules=[module("initialize", "spawn", lifetime=(4, 9), size=(.5, 2.2), color=(.88, .93, 1, .85), radius=.035), module("add_velocity", "spawn", velocity=(4, -2.2, 0), random_speed=(0, 1.2)), module("gravity", vector=(0, -7, 0)), module("drag", amount=.25), module("curl_noise", strength=1.2, frequency=1.4), module("surface_interaction", "spawn", energy=2, radius=.06, thickness=.03)], renderer={"type": "metaball", "material": "snow"})
    return EffectSystem("tcfx.avalanche", "Avalanche", [snow], parameters={"disaster_type": "avalanche", "camera_shake": .22, "material": "snow"})


def _earthquake() -> EffectSystem:
    dust = _emitter_template("quake_dust", "Ground Dust", burst_count=450, duration=4, spawn_shape={"type": "box", "center": (0, .08, 0), "extent": (3, .05, 3)}, modules=[module("initialize", "spawn", lifetime=(1.5, 5), size=(.8, 2.8), color=(.42, .34, .25, .55), radius=.03), module("add_velocity", "spawn", velocity=(0, .7, 0), random_speed=(0, 1.3)), module("gravity", vector=(0, -2, 0)), module("curl_noise", strength=1, frequency=1)], renderer={"type": "volume_sprite", "blend": "alpha"})
    rubble = _emitter_template("rubble", "Rubble", burst_count=110, duration=3, spawn_shape={"type": "box", "center": (0, .15, 0), "extent": (2.5, .1, 2.5)}, modules=[module("initialize", "spawn", lifetime=(2, 6), size=(.5, 1.8), color=(.3, .27, .22, 1), radius=.025), module("add_velocity", "spawn", velocity=(0, 1.4, 0), random_speed=(.2, 2)), module("gravity", vector=(0, -9.81, 0)), module("rotation", "spawn", rate=(-10, 10)), module("surface_interaction", "spawn", energy=4, radius=.05, thickness=.1)], renderer={"type": "mesh", "asset_id": "rubble"})
    return EffectSystem("tcfx.earthquake", "Earthquake", [dust, rubble], parameters={"disaster_type": "earthquake", "camera_shake": 1.0, "ground_wave": {"amplitude": .12, "frequency": 7.0, "duration": 4.0}})


def _aurora() -> EffectSystem:
    curtain = _emitter_template("aurora", "Aurora Curtain", spawn_rate=70, duration=60, looping=True, spawn_shape={"type": "line", "start": (-4, 4, 0), "end": (4, 4, 0), "jitter": .25}, modules=[module("initialize", "spawn", lifetime=(5, 10), size=(1, 2.5), color=(.1, 1, .55, .7), radius=.02), module("add_velocity", "spawn", velocity=(0, .08, 0)), module("curl_noise", strength=.45, frequency=.55), module("color_over_life", colors=((0, (.1, 1, .4, 0)), (.3, (.15, .8, 1, .75)), (.7, (.6, .2, 1, .7)), (1, (.2, 1, .5, 0))))], renderer={"type": "ribbon", "blend": "additive"})
    return EffectSystem("tcfx.aurora", "Aurora", [curtain], parameters={"weather_type": "aurora"})


def _refractive_bubbles() -> EffectSystem:
    bubbles = _emitter_template("bubbles", "Refractive Bubbles", spawn_rate=42, duration=20, looping=True, spawn_shape={"type": "box", "center": (0, .2, 0), "extent": (1.2, .2, 1.2)}, modules=[module("initialize", "spawn", lifetime=(2.5, 6), size=(1, 3.5), color=(.65, .9, 1, .55), radius=.025), module("add_velocity", "spawn", velocity=(0, .65, 0), random_speed=(0, .12)), module("curl_noise", strength=.25, frequency=1.2), module("size_over_life", curve=((0, .2), (.2, 1), (.85, 1.1), (1, 0)))], renderer={"type": "sprite", "blend": "alpha", "material_mode": "refractive", "transmission": .96, "ior": 1.33, "thickness": .08, "roughness": .02, "clearcoat": 1.0, "attenuation_color": "#a8e9ff", "attenuation_distance": 4.0})
    return EffectSystem("tcfx.refractive_bubbles", "Refractive Bubbles", [bubbles])


def _heat_haze() -> EffectSystem:
    haze = _emitter_template("haze", "Heat Haze", spawn_rate=60, duration=20, looping=True, spawn_shape={"type": "box", "center": (0, .3, 0), "extent": (.8, .25, .8)}, modules=[module("initialize", "spawn", lifetime=(1, 2.5), size=(1.5, 4), color=(1, .85, .65, .14), radius=.04), module("add_velocity", "spawn", velocity=(0, .8, 0)), module("curl_noise", strength=.35, frequency=1.8), module("size_over_life", curve=((0, .2), (.4, 1.2), (1, 0)))], renderer={"type": "sprite", "blend": "alpha", "material_mode": "refractive", "transmission": .98, "ior": 1.05, "thickness": .03, "roughness": .15, "clearcoat": 0.0, "distortion": .35})
    return EffectSystem("tcfx.heat_haze", "Heat Haze", [haze], parameters={"distortion": True})


def _range(value: Any, rng: random.Random) -> float:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return rng.uniform(float(value[0]), float(value[1]))
    return float(value)


def _curve(keys: Any, amount: float) -> float:
    values = list(keys or ((0.0, 1.0), (1.0, 1.0)))
    values.sort(key=lambda item: float(item[0]))
    if amount <= float(values[0][0]):
        return float(values[0][1])
    for first, second in zip(values, values[1:]):
        if amount <= float(second[0]):
            blend = (amount - float(first[0])) / max(1.0e-9, float(second[0]) - float(first[0]))
            return float(first[1]) + (float(second[1]) - float(first[1])) * blend
    return float(values[-1][1])


def _gradient(keys: Any, amount: float, fallback: Color) -> Color:
    values = list(keys or ())
    if not values:
        return fallback
    values.sort(key=lambda item: float(item[0]))
    if amount <= float(values[0][0]):
        return _color(values[0][1])
    for first, second in zip(values, values[1:]):
        if amount <= float(second[0]):
            blend = (amount - float(first[0])) / max(1.0e-9, float(second[0]) - float(first[0]))
            a, b = _color(first[1]), _color(second[1])
            return tuple(a[index] + (b[index] - a[index]) * blend for index in range(4))
    return _color(values[-1][1])


def _color(value: Any) -> Color:
    values = tuple(float(item) for item in value)
    return (values + (1.0, 1.0, 1.0, 1.0))[:4]


def _vec(value: Any) -> Vec3:
    values = tuple(float(item) for item in value)
    return (values + (0.0, 0.0, 0.0))[:3]


def _random_unit(rng: random.Random) -> Vec3:
    z = rng.uniform(-1.0, 1.0)
    angle = rng.random() * math.tau
    radius = math.sqrt(max(0.0, 1.0 - z * z))
    return (math.cos(angle) * radius, z, math.sin(angle) * radius)


def _add(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] + second[index] for index in range(3))


def _subtract(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] - second[index] for index in range(3))


def _scale(value: Vec3, amount: float) -> Vec3:
    return tuple(component * amount for component in value)


def _length(value: Vec3) -> float:
    return math.sqrt(sum(component * component for component in value))


def _normalize(value: Vec3) -> Vec3:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-12 else (0.0, 1.0, 0.0)


def _cross(first: Vec3, second: Vec3) -> Vec3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )

