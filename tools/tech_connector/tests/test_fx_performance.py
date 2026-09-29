"""Performance regressions for long-running modular FX systems."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.runtime.tc_effect_system_service import (
    create_effect_world,
    effect_emitter_anchor,
    finish_effect_step,
    move_effect_emitter,
    prepare_effect_step,
    set_effect_emitter_interactive,
)
from tech_connector.game_engine.runtime.tc_simulation_service import DistanceConstraint, SimulationParticle
from tech_connector.ui.dcc_viewer.gpu_viewport import DynamicEffectGeometry


def test_sprite_effects_do_not_allocate_unused_trail_history() -> None:
    world = create_effect_world("explosion", quality="high", seed=4)
    world.step(1.0 / 30.0)

    assert world.particles
    assert world.effect_system.trail_history == {}


def test_expired_effect_particles_are_compacted_periodically() -> None:
    world = create_effect_world("sparks", quality="high", seed=2)
    system = world.effect_system
    system.frame = 59
    world.particles = [
        SimulationParticle(
            (0.0, 0.0, 0.0),
            alive=False,
            particle_id=index,
            emitter_id="sparks",
            effect_attributes={"system_id": system.system_id},
        )
        for index in range(300)
    ]
    system.trail_history = {index: [(0.0, 0.0, 0.0)] for index in range(300)}

    finish_effect_step(system, world, 1.0 / 30.0)

    assert world.particles == []
    assert system.trail_history == {}


def test_effect_compaction_preserves_indexed_physics_worlds() -> None:
    world = create_effect_world("sparks", quality="high", seed=2)
    system = world.effect_system
    system.frame = 59
    world.particles = [
        SimulationParticle(
            (0.0, 0.0, 0.0),
            alive=False,
            particle_id=index,
            emitter_id="sparks",
            effect_attributes={"system_id": system.system_id},
        )
        for index in range(300)
    ]
    world.constraints.append(DistanceConstraint(0, 1, 0.0))

    finish_effect_step(system, world, 1.0 / 30.0)

    assert len(world.particles) == 300


def test_completed_one_shot_effect_releases_small_dead_batches() -> None:
    world = create_effect_world("sparks", quality="high", seed=2)
    system = world.effect_system
    system.frame = 59
    system.emitters[0].age = system.emitters[0].duration + 1.0
    world.particles = [
        SimulationParticle(
            (0.0, 0.0, 0.0),
            alive=False,
            particle_id=index,
            emitter_id="sparks",
            effect_attributes={"system_id": system.system_id},
        )
        for index in range(12)
    ]

    finish_effect_step(system, world, 1.0 / 30.0)

    assert world.particles == []


def test_per_emitter_particle_cap_limits_long_running_fx() -> None:
    world = create_effect_world("rain", quality="high", seed=5)
    world.effect_system.emitters[0].max_particles = 25

    for _frame in range(180):
        world.step(1.0 / 60.0)

    assert sum(1 for particle in world.particles if particle.alive) <= 25


def test_per_emitter_update_divisor_throttles_expensive_modules() -> None:
    world = create_effect_world("sparks", quality="high", seed=5)
    system = world.effect_system
    emitter = system.emitters[0]
    emitter.burst_count = 0
    emitter.update_rate_divisor = 4
    particle = SimulationParticle(
        (0.0, 1.0, 0.0),
        emitter_id=emitter.emitter_id,
        particle_id=1,
        effect_attributes={"system_id": system.system_id},
    )
    world.particles = [particle]

    system.frame = 1
    prepare_effect_step(system, world, 1.0 / 60.0)
    assert particle.velocity == (0.0, 0.0, 0.0)

    system.frame = 4
    prepare_effect_step(system, world, 1.0 / 60.0)
    assert particle.velocity[1] < 0.0


def test_gpu_stream_culls_distant_particles_before_upload() -> None:
    _app = QApplication.instance() or QApplication([])
    world = create_effect_world("sparks", quality="high", seed=5)
    system = world.effect_system
    world.particles = [
        SimulationParticle(
            position,
            emitter_id="sparks",
            particle_id=index,
            effect_attributes={"system_id": system.system_id, "initial_size": 1.0},
        )
        for index, position in enumerate(((0.0, 0.0, 2.0), (0.0, 0.0, 200.0)))
    ]
    geometry = DynamicEffectGeometry()

    geometry.upload_world(
        world,
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        maximum_particles=10,
        maximum_distance=10.0,
        render_group="additive",
    )

    assert geometry.source_count == 2
    assert geometry.particle_count == 1
    assert geometry.dropped_count == 1
    assert geometry.last_stream_receipt["schema"] == "tech_connector.simulation_render_stream.v1"
    assert geometry.last_stream_receipt["consumer_upload_required"]


def test_interactive_burst_emitter_keeps_emitting_while_manipulated() -> None:
    world = create_effect_world("explosion", quality="high", seed=8)
    system = world.effect_system
    emitter = system.emitters[0]
    prepare_effect_step(system, world, 1.0 / 60.0)
    initial_count = len(world.particles)
    assert emitter.burst_emitted

    set_effect_emitter_interactive(system, emitter.emitter_id, True, spawn_rate=120.0)
    prepare_effect_step(system, world, 0.1)

    assert emitter.enabled and emitter.interactive_active
    assert len(world.particles) >= initial_count + 12


def test_moving_beam_emitter_preserves_shape_and_translates_spatial_modules() -> None:
    world = create_effect_world("lightning", quality="high", seed=3)
    system = world.effect_system
    emitter = system.emitters[0]
    start_before = tuple(emitter.spawn_shape["start"])
    end_before = tuple(emitter.spawn_shape["end"])
    span_before = tuple(end_before[index] - start_before[index] for index in range(3))

    moved = move_effect_emitter(system, emitter.emitter_id, (3.0, 2.0, -1.0))
    span_after = tuple(
        emitter.spawn_shape["end"][index] - emitter.spawn_shape["start"][index] for index in range(3)
    )

    assert moved == (3.0, 2.0, -1.0)
    assert effect_emitter_anchor(emitter) == moved
    assert span_after == span_before


def test_emitter_drag_can_carry_existing_particles_and_trails() -> None:
    world = create_effect_world("sparks", quality="high", seed=5)
    system = world.effect_system
    emitter = system.emitters[0]
    particle = SimulationParticle(
        (0.0, 1.0, 0.0), emitter_id=emitter.emitter_id, particle_id=17,
        effect_attributes={"system_id": system.system_id, "jiggle_anchor": (0.0, 1.0, 0.0)},
    )
    world.particles = [particle]
    system.trail_history[17] = [(0.0, 0.5, 0.0), (0.0, 1.0, 0.0)]
    original_anchor = effect_emitter_anchor(emitter)

    move_effect_emitter(
        system, emitter.emitter_id, (original_anchor[0] + 2.0, original_anchor[1], original_anchor[2]),
        world=world, move_live_particles=True,
    )

    assert particle.position == (2.0, 1.0, 0.0)
    assert particle.effect_attributes["jiggle_anchor"] == (2.0, 1.0, 0.0)
    assert system.trail_history[17][0] == (2.0, 0.5, 0.0)
