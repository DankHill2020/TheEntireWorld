from __future__ import annotations

import pytest

from tech_connector.services.dcc.tc_effect_system_service import effect_preset_names
from tech_connector.services.dcc.tc_simulation_ir_service import (
    SimulationBackendCapabilities,
    compile_simulation_world,
    execute_compiled_simulation,
    register_simulation_backend,
    register_simulation_executor,
)
from tech_connector.services.dcc.tc_simulation_runtime_service import SimulationRuntimeInstance


def _particle_state(runtime: SimulationRuntimeInstance):
    return [
        (particle.particle_id, particle.position, particle.velocity, particle.alive)
        for particle in runtime.world.particles
    ]


def test_runtime_advances_effects_at_a_fixed_tick_independent_of_render_chunks() -> None:
    single = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=11)
    split = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=11)

    single.advance(1.0 / 30.0)
    split.advance(1.0 / 60.0)
    split.advance(1.0 / 60.0)

    assert single.tick_index == split.tick_index == 2
    assert _particle_state(single) == _particle_state(split)


def test_runtime_emits_renderer_packets_without_an_editor_or_qt() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("refractive_bubbles", quality="high")

    packet = runtime.advance(0.25)

    assert packet.diagnostics["steps"] == runtime.max_catch_up_steps
    assert packet.diagnostics["alive_particles"] > 0
    assert "refractive" in packet.streams
    assert runtime.deployment_manifest()["requires_editor"] is False
    assert any(item["role"] == "events" for item in runtime.compiled.outputs)


def test_runtime_commands_apply_on_deterministic_tick_boundaries() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low")
    command = runtime.queue_parameter("emitter.sparks.spawn_rate", 120.0, tick=2)

    runtime.advance(1.0 / 60.0)
    assert runtime.world.effect_system.emitters[0].spawn_rate != 120.0
    runtime.advance(1.0 / 60.0)

    assert command.tick == 2
    assert runtime.world.effect_system.emitters[0].spawn_rate == 120.0


def test_runtime_rolls_back_and_replays_deterministically() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=23)
    runtime.checkpoint_interval = 2
    runtime.advance(2.0 / 60.0)
    runtime.advance(2.0 / 60.0)
    expected = _particle_state(runtime)

    assert runtime.rollback(2) == 2
    runtime.advance(2.0 / 60.0)

    assert _particle_state(runtime) == expected


def test_runtime_quality_recompiles_profile_and_limits_hitches() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("fog", quality="high")
    packet = runtime.advance(1.0)

    assert packet.diagnostics["steps"] == 4
    assert packet.diagnostics["dropped_time"] == pytest.approx(1.0 - 4.0 / 60.0)
    runtime.set_quality("retro")
    assert runtime.compiled.profile.name == "retro"


def test_every_effect_preset_compiles_for_headless_runtime_deployment() -> None:
    for preset in effect_preset_names():
        runtime = SimulationRuntimeInstance.from_effect_preset(preset, quality="low", seed=7)
        packet = runtime.advance(1.0 / 60.0)
        manifest = runtime.deployment_manifest()
        assert packet.tick == 1
        assert manifest["requires_editor"] is False
        assert manifest["effect_system"]["system_id"].startswith("tcfx.")


def test_runtime_backend_executor_is_replaceable_without_changing_the_asset() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low")
    calls = []
    backend = SimulationBackendCapabilities(
        "test_native", True, "cpu", tuple(runtime.compiled.domains), True, True, True, 1000,
    )
    register_simulation_backend(backend)
    register_simulation_executor("test_native", lambda compiled, world, dt: calls.append(dt))
    compiled = compile_simulation_world(runtime.world, profile="realtime", backend="test_native")

    execute_compiled_simulation(compiled, runtime.world, 1.0 / 60.0)

    assert calls == [pytest.approx(1.0 / 60.0)]


def test_runtime_replays_parameter_commands_after_rollback() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low")
    runtime.checkpoint_interval = 1
    runtime.queue_parameter("emitter.sparks.spawn_rate", 77.0, tick=2)
    runtime.advance(2.0 / 60.0)
    assert runtime.world.effect_system.emitters[0].spawn_rate == 77.0

    runtime.rollback(1)
    runtime.advance(1.0 / 60.0)

    assert runtime.world.effect_system.emitters[0].spawn_rate == 77.0
