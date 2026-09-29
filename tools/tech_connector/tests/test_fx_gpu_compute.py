"""Conformance coverage for the qualified native GPU particle stage."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world
from tech_connector.game_engine.runtime.tc_gpu_compute_service import (
    NATIVE_LIBRARY_CANDIDATES,
    NativeD3D11ParticleCompute,
    compile_d3d11_mesh_bvh,
    gpu_world_eligibility,
)
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
from tech_connector.game_engine.runtime.tc_simulation_service import (
    DistanceConstraint,
    ForceField,
    PlaneCollider,
    SphereCollider,
    SimulationMaterial,
    SimulationParticle,
    SimulationWorld,
    TriangleMeshCollider,
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


def test_native_gpu_executes_particle_fx_with_cpu_authored_modules() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset(
        "sparks", quality="realtime", seed=17, backend="gpu_compute",
    )

    frame = runtime.advance(1.0 / 60.0)
    health = runtime.health_snapshot()

    assert health.compiled_backend == "gpu_compute"
    assert health.execution_backend == "gpu_compute"
    assert health.execution_device == "gpu"
    assert not health.fallback_active
    assert frame.diagnostics["alive_particles"] > 0
    stages = runtime.compiled.metadata["last_execution"]["backend_receipt"]["dispatch_telemetry"]["supported_stages"]
    assert "effect_modules_cpu" in stages


def test_gpu_fx_checkpoint_excludes_device_handle_and_recreates_it_after_rollback() -> None:
    runtime = SimulationRuntimeInstance(
        create_effect_world("sparks", quality="realtime", seed=23),
        profile="realtime", backend="gpu_compute", tick_rate=60.0, checkpoint_interval=2,
    )

    runtime.advance(2.0 / 60.0)
    checkpoint = runtime._checkpoints[-1]

    assert checkpoint.tick == 2
    assert not hasattr(checkpoint.world, "_compiled_d3d11_service")
    assert runtime.rollback(2) == 2
    runtime.advance(1.0 / 60.0)
    assert runtime.health_snapshot().execution_backend == "gpu_compute"


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


def test_gpu_distance_constraints_are_qualified_but_advanced_damage_fails_closed() -> None:
    world = _simple_world()
    world.constraints.append(DistanceConstraint(0, 1, 1.0))

    eligible, reason = gpu_world_eligibility(world)

    assert eligible, reason
    world.constraints[0].break_threshold = 1.2
    eligible, reason = gpu_world_eligibility(world)
    assert not eligible
    assert "breaking" in reason


def test_graph_colored_gpu_xpbd_distance_constraints_update_position_and_velocity() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), inverse_mass=1.0),
            SimulationParticle((2.0, 0.0, 0.0), inverse_mass=1.0),
            SimulationParticle((4.0, 0.0, 0.0), inverse_mass=1.0),
        ],
        constraints=[DistanceConstraint(0, 1, 1.0), DistanceConstraint(1, 2, 1.0)],
        fields=[], substeps=1, constraint_iterations=12, self_collision=False,
    )
    service = NativeD3D11ParticleCompute()

    telemetry = service.dispatch_runtime(world, 1.0 / 60.0)

    assert service.resident_distance_constraint_count == 2
    assert "distance_constraints" in telemetry.supported_stages
    assert telemetry.upload_bytes > 3 * 32
    assert np.linalg.norm(np.subtract(world.particles[1].position, world.particles[0].position)) == pytest.approx(
        1.0, abs=2.0e-4
    )
    assert np.linalg.norm(np.subtract(world.particles[2].position, world.particles[1].position)) == pytest.approx(
        1.0, abs=2.0e-4
    )
    assert world.particles[0].velocity[0] > 0.0
    assert world.particles[2].velocity[0] < 0.0


def test_authoritative_constraint_tick_reuses_topology_without_upload_or_readback() -> None:
    world = SimulationWorld(
        particles=[SimulationParticle((0.0, 0.0, 0.0)), SimulationParticle((2.0, 0.0, 0.0))],
        constraints=[DistanceConstraint(0, 1, 1.0)], fields=[], self_collision=False,
        substeps=1, constraint_iterations=4,
    )
    service = NativeD3D11ParticleCompute()
    first = service.dispatch_runtime(world, 1.0 / 60.0, resident_output=True)

    resident = service.dispatch_runtime(world, 1.0 / 60.0, resident_output=True)

    assert first.upload_bytes > 0
    assert resident.upload_bytes == 0
    assert resident.readback_bytes == 0
    assert not resident.synchronized_readback


def test_d3d11_composable_spatial_fields_match_reference_motion() -> None:
    def make_world() -> SimulationWorld:
        return SimulationWorld(
            particles=[
                SimulationParticle((1.0, 1.0, 0.2), velocity=(0.4, -0.1, 0.2), material="field_test"),
                SimulationParticle((-0.6, 0.5, 0.8), velocity=(-0.2, 0.3, 0.1), material="field_test"),
            ],
            fields=[
                ForceField("gravity", vector=(0.0, -9.81, 0.0)),
                ForceField("wind", vector=(3.0, 0.2, 0.0), strength=1.2, radius=4.0,
                           inner_radius=0.4, falloff_power=1.5, drag=1.1,
                           gust_strength=0.2, frequency=1.7, seed=7),
                ForceField("attractor", center=(0.0, 0.0, 0.0), strength=2.0, radius=3.0,
                           max_acceleration=1.5),
                ForceField("vortex", vector=(0.0, 1.0, 0.0), strength=0.8, radius=3.0),
                ForceField("turbulence", strength=0.35, radius=4.0, seed=11,
                           frequency=1.3, noise_scale=1.8),
                ForceField("quadratic_drag", strength=0.02),
            ],
            self_collision=False, substeps=2, constraint_iterations=1,
        )

    gpu_world = make_world()
    reference_world = make_world()
    for world in (gpu_world, reference_world):
        world.materials["field_test"] = SimulationMaterial("Field Test", damping=0.0)
    reference_world.step(1.0 / 30.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(gpu_world, 1.0 / 30.0)

    assert "physics_fields" in telemetry.supported_stages
    for actual, expected in zip(gpu_world.particles, reference_world.particles):
        assert actual.position == pytest.approx(expected.position, abs=8.0e-5)
        assert actual.velocity == pytest.approx(expected.velocity, abs=8.0e-5)


def test_generic_array_dispatch_clears_prior_resident_physics_fields() -> None:
    service = NativeD3D11ParticleCompute()
    field_world = SimulationWorld(
        particles=[SimulationParticle((1.0, 0.0, 0.0))],
        fields=[ForceField("attractor", strength=10.0, radius=5.0)], self_collision=False,
    )
    service.dispatch(field_world, 0.1)
    positions = np.asarray([[1.0, 0.0, 0.0, 0.03]], dtype=np.float32)
    velocities = np.zeros_like(positions)

    service.integrate_arrays(positions, velocities, acceleration=(0.0, 0.0, 0.0), dt=0.1)

    assert service.resident_physics_field_count == 0
    assert velocities[0, :3] == pytest.approx((0.0, 0.0, 0.0), abs=1.0e-7)


def test_mesh_bvh_compiles_to_contiguous_d3d11_leaf_records_and_refits() -> None:
    collider = TriangleMeshCollider(
        [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0)],
        [(0, 1, 2, 3)], friction=0.4, restitution=0.2,
    )
    payload = compile_d3d11_mesh_bvh(collider)

    assert payload.node_bounds.dtype == np.float32 and payload.node_bounds.flags.c_contiguous
    assert payload.node_metadata.dtype == np.uint32 and payload.node_metadata.flags.c_contiguous
    assert payload.triangle_vertices.shape == (6, 4)
    assert int(np.sum(payload.node_metadata[:, 3])) == 2
    assert payload.memory_bytes > 0
    previous_bounds = payload.node_bounds.copy()

    collider.vertices = [(x, y + 1.0, z) for x, y, z in collider.vertices]
    collider.mark_geometry_dirty()
    refit = compile_d3d11_mesh_bvh(collider)

    assert refit.source_signature != payload.source_signature
    assert refit.node_bounds[:, 1] == pytest.approx(previous_bounds[:, 1] + 1.0)


def test_d3d11_mesh_bvh_collision_matches_reference_position_and_response() -> None:
    def make_world() -> SimulationWorld:
        world = SimulationWorld(
            particles=[SimulationParticle(
                (0.0, 0.02, 0.0), velocity=(0.2, -0.1, 0.0), radius=0.03,
                material="field_test",
            )],
            fields=[], self_collision=False, substeps=1, constraint_iterations=1,
            mesh_colliders=[TriangleMeshCollider(
                [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)],
                [(0, 1, 2)], friction=0.35, restitution=0.2,
            )],
        )
        world.materials["field_test"] = SimulationMaterial("Field Test", damping=0.0)
        return world

    gpu_world = make_world()
    reference_world = make_world()
    reference_world.step(1.0 / 60.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(gpu_world, 1.0 / 60.0)

    assert "mesh_bvh_collision" in telemetry.supported_stages
    assert gpu_world.particles[0].position == pytest.approx(reference_world.particles[0].position, abs=3.0e-6)
    assert gpu_world.particles[0].velocity == pytest.approx(reference_world.particles[0].velocity, abs=3.0e-5)


def test_d3d11_spatial_hash_self_collision_separates_overlapping_particles() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((-0.01, 0.0, 0.0), radius=0.03, material="field_test"),
            SimulationParticle((0.01, 0.0, 0.0), radius=0.03, material="field_test"),
        ],
        fields=[], self_collision=True, substeps=1, constraint_iterations=3,
    )
    world.materials["field_test"] = SimulationMaterial("Field Test", damping=0.0)

    telemetry = NativeD3D11ParticleCompute().dispatch(world, 1.0 / 60.0)

    distance = np.linalg.norm(np.subtract(world.particles[1].position, world.particles[0].position))
    assert "spatial_hash_self_collision" in telemetry.supported_stages
    assert distance == pytest.approx(0.06, abs=3.0e-5)
    assert world.particles[0].velocity[0] < 0.0
    assert world.particles[1].velocity[0] > 0.0


def test_d3d11_spatial_hash_handles_large_sparse_resident_world_without_transfer() -> None:
    count = 10_000
    world = SimulationWorld(
        particles=[SimulationParticle((index * 0.2, 0.0, 0.0), radius=0.03) for index in range(count)],
        fields=[], self_collision=True, substeps=1, constraint_iterations=1,
    )
    service = NativeD3D11ParticleCompute()
    service.dispatch_runtime(world, 1.0 / 60.0, resident_output=True)

    resident = service.dispatch_runtime(world, 1.0 / 60.0, resident_output=True)

    assert resident.upload_bytes == 0 and resident.readback_bytes == 0
    assert "spatial_hash_self_collision" in resident.supported_stages
