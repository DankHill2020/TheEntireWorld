"""Conformance coverage for the qualified native GPU particle stage."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

from tech_connector.game_engine.runtime.tc_gpu_compute_service import (
    NATIVE_LIBRARY_CANDIDATES,
    NativeD3D11ParticleCompute,
    gpu_world_eligibility,
)
from tech_connector.game_engine.runtime.tc_simulation_service import (
    DistanceConstraint,
    ForceField,
    PlaneCollider,
    SphereCollider,
    SimulationParticle,
    SimulationWorld,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not any(Path(path).exists() for path in NATIVE_LIBRARY_CANDIDATES),
    reason="The native D3D11 compute library is not available in this build.",
)


def _simple_world() -> SimulationWorld:
    return SimulationWorld(
        particles=[
            SimulationParticle((0.0, 1.0, 0.0), velocity=(1.0, 0.0, 0.0), material="water"),
            SimulationParticle((1.0, 2.0, 3.0), velocity=(-1.0, 0.5, 0.25), material="goo"),
        ],
        fields=[ForceField()],
        substeps=3,
        constraint_iterations=1,
        self_collision=False,
    )


def test_native_gpu_integration_matches_reference_solver() -> None:
    gpu_world = _simple_world()
    reference_world = _simple_world()
    reference_world.step(1.0 / 60.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(gpu_world, 1.0 / 60.0)

    assert telemetry.backend == "d3d11"
    assert telemetry.particle_count == 2
    assert telemetry.workgroups == 1
    assert telemetry.readback_bytes == 64
    assert not telemetry.gpu_resident
    for actual, expected in zip(gpu_world.particles, reference_world.particles):
        assert actual.position == pytest.approx(expected.position, abs=2.0e-6)
        assert actual.velocity == pytest.approx(expected.velocity, abs=2.0e-6)


def test_native_gpu_dispatches_large_array_in_workgroups() -> None:
    service = NativeD3D11ParticleCompute()
    positions = np.zeros((1000, 4), dtype=np.float32)
    velocities = np.zeros((1000, 4), dtype=np.float32)
    positions[:, 3] = 1.0

    telemetry = service.integrate_arrays(positions, velocities, substeps=2)

    assert telemetry.workgroups == 4
    assert positions[0, 1] < 0.0
    assert velocities[0, 1] < 0.0
    assert telemetry.dispatch_ms > 0.0


def test_resident_gpu_step_defers_cpu_readback() -> None:
    service = NativeD3D11ParticleCompute()
    positions = np.asarray([[0.0, 1.0, 0.0, 0.03]], dtype=np.float32)
    velocities = np.zeros((1, 4), dtype=np.float32)
    original_positions = positions.copy()

    upload = service.upload_resident_arrays(positions, velocities)
    step = service.step_resident(dt=1.0 / 60.0, substeps=2)

    assert service.resident_particle_count == 1
    assert upload.gpu_resident and upload.upload_bytes == 32
    assert step.gpu_resident and not step.synchronized_readback
    assert step.upload_bytes == 0 and step.readback_bytes == 0
    assert positions == pytest.approx(original_positions)

    readback = service.readback_resident(positions, velocities)
    assert readback.readback_bytes == 32
    assert positions[0, 1] < original_positions[0, 1]


def test_gpu_plane_collision_matches_reference_solver() -> None:
    def world() -> SimulationWorld:
        return SimulationWorld(
            particles=[SimulationParticle((0.0, 0.025, 0.0), velocity=(0.5, -1.0, 0.0), radius=0.03)],
            fields=[ForceField()], plane_colliders=[PlaneCollider(friction=0.4, restitution=0.2)],
            substeps=3, constraint_iterations=2, self_collision=False,
        )

    gpu_world = world()
    reference_world = world()
    reference_world.step(1.0 / 60.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(gpu_world, 1.0 / 60.0)

    assert "plane_collision" in telemetry.supported_stages
    assert gpu_world.particles[0].position == pytest.approx(reference_world.particles[0].position, abs=2.0e-6)
    assert gpu_world.particles[0].velocity == pytest.approx(reference_world.particles[0].velocity, abs=2.0e-6)


def test_gpu_sessions_keep_multiple_worlds_isolated() -> None:
    first = NativeD3D11ParticleCompute()
    second = NativeD3D11ParticleCompute()
    assert first.session_id != second.session_id
    first_positions = np.asarray([[0.0, 1.0, 0.0, 0.03]], dtype=np.float32)
    second_positions = np.asarray([[0.0, 10.0, 0.0, 0.03]], dtype=np.float32)
    first_velocities = np.zeros_like(first_positions)
    second_velocities = np.zeros_like(second_positions)

    first.upload_resident_arrays(first_positions, first_velocities)
    second.upload_resident_arrays(second_positions, second_velocities)
    first.step_resident(acceleration=(0.0, -10.0, 0.0), dt=0.1)
    second.step_resident(acceleration=(0.0, 5.0, 0.0), dt=0.1)
    first.readback_resident(first_positions, first_velocities)
    second.readback_resident(second_positions, second_velocities)

    assert first_positions[0, 1] == pytest.approx(0.9, abs=2.0e-6)
    assert second_positions[0, 1] == pytest.approx(10.05, abs=2.0e-6)
    first.close()
    assert first.resident_particle_count == 0
    assert second.resident_particle_count == 1
    second.close()


def test_gpu_sphere_collision_matches_reference_solver() -> None:
    def world() -> SimulationWorld:
        return SimulationWorld(
            particles=[SimulationParticle(
                (0.95, 0.0, 0.0), velocity=(-1.0, 0.8, 0.0), radius=0.1, material="water"
            )],
            fields=[], sphere_colliders=[SphereCollider((0.0, 0.0, 0.0), 1.0, friction=0.35, restitution=0.4)],
            substeps=2, constraint_iterations=2, self_collision=False,
        )

    gpu_world = world()
    reference_world = world()
    reference_world.step(1.0 / 60.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(gpu_world, 1.0 / 60.0)

    assert "sphere_collision" in telemetry.supported_stages
    assert gpu_world.particles[0].position == pytest.approx(reference_world.particles[0].position, abs=3.0e-6)
    assert gpu_world.particles[0].velocity == pytest.approx(reference_world.particles[0].velocity, abs=2.0e-5)


def test_gpu_eligibility_fails_closed_for_unqualified_constraints() -> None:
    world = _simple_world()
    world.constraints.append(DistanceConstraint(0, 1, 1.0))

    eligible, reason = gpu_world_eligibility(world)

    assert not eligible
    assert "constraints" in reason
