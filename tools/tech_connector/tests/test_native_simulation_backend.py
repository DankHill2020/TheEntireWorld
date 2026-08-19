"""Executable native SoA simulation backend and truthful fallback coverage."""

from __future__ import annotations

import copy

import pytest

from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    compile_simulation_world,
    execute_compiled_simulation,
    simulation_backend_status,
)
from tech_connector.game_engine.runtime.tc_simulation_service import (
    ForceField,
    PlaneCollider,
    SimulationParticle,
    SimulationWorld,
    create_cloth_grid,
)


def _particle_world(count: int = 4) -> SimulationWorld:
    return SimulationWorld(
        particles=[SimulationParticle((index * 0.1, 1.0 + index * 0.01, 0.0), velocity=(0.2, -0.1, 0.0))
                   for index in range(count)],
        fields=[ForceField("gravity", (0.0, -9.81, 0.0))],
        plane_colliders=[PlaneCollider()], self_collision=False, substeps=2, constraint_iterations=1,
    )


def test_native_cpu_backend_is_installed_and_reports_real_host_residency() -> None:
    status = simulation_backend_status("native_cpu")
    world = _particle_world(16)
    compiled = compile_simulation_world(world, backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert status["available"] and status["executor_installed"]
    assert telemetry["execution_backend"] == "native_cpu"
    assert telemetry["execution_device"] == "cpu"
    assert not telemetry["gpu_resident"]
    assert telemetry["memory_bytes"] > 0
    assert telemetry["backend_receipt"]["buffer_residency"] == "persistent_host_soa"
    assert set(telemetry["stage_ms"]) >= {"buffer_upload", "integrate_collide", "buffer_download"}


def test_native_particle_result_matches_reference_for_supported_world() -> None:
    native_world = _particle_world(32)
    reference_world = copy.deepcopy(native_world)
    native = compile_simulation_world(native_world, backend="native_cpu")
    reference = compile_simulation_world(reference_world, backend="reference_cpu")

    execute_compiled_simulation(native, native_world, 1 / 60)
    execute_compiled_simulation(reference, reference_world, 1 / 60)

    for actual, expected in zip(native_world.particles, reference_world.particles):
        assert actual.position == pytest.approx(expected.position, abs=1.0e-10)
        assert actual.velocity == pytest.approx(expected.velocity, abs=1.0e-10)


def test_native_buffers_persist_without_reallocation_at_stable_capacity() -> None:
    world = _particle_world(300)
    compiled = compile_simulation_world(world, backend="native_cpu")
    first = execute_compiled_simulation(compiled, world, 1 / 60)
    second = execute_compiled_simulation(compiled, world, 1 / 60)

    assert first["backend_receipt"]["buffer_reallocations"] == 1
    assert second["backend_receipt"]["buffer_reallocations"] == 1
    assert second["backend_receipt"]["buffer_capacity"] >= 300


def test_unsupported_native_constraint_world_falls_back_truthfully() -> None:
    world = create_cloth_grid(3, 3)
    compiled = compile_simulation_world(world, backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert compiled.backend.backend_id == "native_cpu"
    assert telemetry["execution_backend"] == "reference_cpu"
    assert not telemetry["gpu_resident"]
    assert "constraint kernels are not installed" in telemetry["backend_receipt"]["fallback_reasons"]
    assert any(item["code"] == "runtime_backend_fallback" for item in compiled.diagnostics)


def test_native_cpu_20k_particle_stress_tick_stays_bounded() -> None:
    world = _particle_world(20_000)
    compiled = compile_simulation_world(world, profile="cinematic", backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert telemetry["execution_backend"] == "native_cpu"
    assert telemetry["elapsed_ms"] < 250.0
    assert telemetry["particle_count"] == 20_000
