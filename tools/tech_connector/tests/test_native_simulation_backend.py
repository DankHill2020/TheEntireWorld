"""Executable native SoA simulation backend and truthful fallback coverage."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider,
    COMPUTE_PROVIDERS,
    ComputeProviderStatus,
    compute_provider,
    compute_provider_statuses,
    register_compute_provider,
)
from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import execute_gpu_compute
from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    compile_simulation_world,
    execute_compiled_simulation,
    simulation_backend_status,
)
from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import (
    native_particle_view,
    synchronize_native_particles,
)
from tech_connector.game_engine.runtime.tc_simulation_native_volume_service import (
    synchronize_native_sparse_volumes,
)
from tech_connector.game_engine.runtime.tc_simulation_service import (
    DistanceConstraint,
    CurveFlowField,
    ForceField,
    PlaneCollider,
    SimulationMaterial,
    SimulationParticle,
    SimulationWorld,
    SparseVolume,
    SparseVolumeCell,
    TriangleMeshCollider,
    VolumeConstraint,
    create_cloth_grid,
    create_sparse_fire_volume,
)


def _particle_world(count: int = 4) -> SimulationWorld:
    world = SimulationWorld(
        particles=[SimulationParticle((index * 0.1, 1.0 + index * 0.01, 0.0), velocity=(0.2, -0.1, 0.0),
                                      material="native_particle")
                   for index in range(count)],
        fields=[ForceField("gravity", (0.0, -9.81, 0.0))],
        plane_colliders=[PlaneCollider()], self_collision=False, substeps=2, constraint_iterations=1,
    )
    world.materials["native_particle"] = SimulationMaterial("Native Particle", damping=0.01)
    return world


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


def test_native_self_collision_cloth_executes_without_fallback() -> None:
    world = create_cloth_grid(3, 3)
    compiled = compile_simulation_world(world, backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert compiled.backend.backend_id == "native_cpu"
    assert telemetry["execution_backend"] == "native_cpu"
    assert not telemetry["gpu_resident"]
    assert "self_collision_pairs" in telemetry["backend_receipt"]


def test_unsupported_native_curve_field_falls_back_truthfully() -> None:
    world = _particle_world(4)
    world.curve_fields.append(CurveFlowField([(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]))
    compiled = compile_simulation_world(world, backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert telemetry["execution_backend"] == "reference_cpu"
    assert "curve-field kernel is not installed" in telemetry["backend_receipt"]["fallback_reasons"]
    assert any(item["code"] == "runtime_backend_fallback" for item in compiled.diagnostics)


def test_native_graph_colored_cloth_constraints_are_deterministic() -> None:
    first = create_cloth_grid(4, 4)
    first.self_collision = False
    second = copy.deepcopy(first)
    first_receipt = execute_compiled_simulation(compile_simulation_world(first, backend="native_cpu"), first, 1 / 60)
    second_receipt = execute_compiled_simulation(compile_simulation_world(second, backend="native_cpu"), second, 1 / 60)

    assert first_receipt["execution_backend"] == "native_cpu"
    assert first_receipt["backend_receipt"]["constraint_colors"] > 0
    assert [item.position for item in first.particles] == [item.position for item in second.particles]


def test_composable_physics_fields_match_native_reference_and_remain_deterministic() -> None:
    fields = [
        ForceField("gravity", vector=(0.0, -9.81, 0.0)),
        ForceField("wind", vector=(4.0, 0.0, 0.0), drag=1.5, gust_strength=0.25, frequency=2.0),
        ForceField("attractor", center=(0.0, 0.0, 0.0), strength=3.0, radius=4.0,
                   inner_radius=0.5, falloff_power=2.0, max_acceleration=2.0),
        ForceField("vortex", vector=(0.0, 1.0, 0.0), strength=1.25, radius=3.0),
        ForceField("turbulence", strength=0.8, radius=5.0, seed=42, frequency=1.7, noise_scale=2.0),
        ForceField("quadratic_drag", vector=(0.0, 0.0, 0.0), strength=0.03),
        ForceField("buoyancy", vector=(0.0, 1.0, 0.0), strength=9.81, ambient_density=1200.0),
    ]
    reference = SimulationWorld(
        particles=[
            SimulationParticle((1.0, 1.5, 0.2), velocity=(0.5, -0.2, 0.1), material="field_test"),
            SimulationParticle((-0.8, 0.4, 1.1), velocity=(-0.1, 0.3, 0.2), material="field_test"),
        ], fields=fields, self_collision=False, substeps=2, constraint_iterations=1,
    )
    reference.materials["field_test"] = SimulationMaterial("Field Test", density=800.0, damping=0.0)
    native = copy.deepcopy(reference)
    repeated = copy.deepcopy(reference)

    execute_compiled_simulation(compile_simulation_world(reference, backend="reference_cpu"), reference, 1 / 30)
    receipt = execute_compiled_simulation(compile_simulation_world(native, backend="native_cpu"), native, 1 / 30)
    execute_compiled_simulation(compile_simulation_world(repeated, backend="native_cpu"), repeated, 1 / 30)

    assert receipt["execution_backend"] == "native_cpu"
    assert [item.position for item in native.particles] == pytest.approx(
        [item.position for item in reference.particles], abs=2.0e-10
    )
    assert [item.velocity for item in native.particles] == pytest.approx(
        [item.velocity for item in reference.particles], abs=2.0e-10
    )
    assert [item.position for item in native.particles] == [item.position for item in repeated.particles]


def test_native_self_and_bvh_mesh_collisions_match_reference() -> None:
    native_world = SimulationWorld(
        particles=[
            SimulationParticle((-0.01, 0.02, 0.0), radius=0.03, material="native_particle"),
            SimulationParticle((0.01, 0.02, 0.0), radius=0.03, material="native_particle"),
        ],
        fields=[], self_collision=True, substeps=1, constraint_iterations=1,
        mesh_colliders=[TriangleMeshCollider(
            [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)], [(0, 1, 2)]
        )],
    )
    native_world.materials["native_particle"] = SimulationMaterial("Native Particle")
    reference_world = copy.deepcopy(native_world)
    native_receipt = execute_compiled_simulation(
        compile_simulation_world(native_world, backend="native_cpu"), native_world, 1 / 60
    )
    execute_compiled_simulation(
        compile_simulation_world(reference_world, backend="reference_cpu"), reference_world, 1 / 60
    )

    assert native_receipt["execution_backend"] == "native_cpu"
    assert native_receipt["backend_receipt"]["self_collision_pairs"] > 0
    for actual, expected in zip(native_world.particles, reference_world.particles):
        assert actual.position == pytest.approx(expected.position, abs=1.0e-10)
        assert actual.velocity == pytest.approx(expected.velocity, abs=1.0e-10)
    assert native_world.mesh_colliders[0].collision_diagnostics()["query_count"] > 0


def test_native_volume_and_material_neighbor_kernels_execute_without_fallback() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), material="goo"),
            SimulationParticle((0.08, 0.0, 0.0), material="goo"),
            SimulationParticle((0.0, 0.1, 0.0), material="goo"),
            SimulationParticle((0.0, 0.0, 0.1), material="goo"),
        ],
        fields=[], self_collision=False, substeps=1, constraint_iterations=2,
    )
    world.volume_constraints.append(VolumeConstraint(
        [0, 1, 2, 3], [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)],
        rest_volume=1.0e-4, compliance=1.0e-6,
    ))
    telemetry = execute_compiled_simulation(compile_simulation_world(world, backend="native_cpu"), world, 1 / 60)

    assert telemetry["execution_backend"] == "native_cpu"
    assert telemetry["backend_receipt"]["material_neighbor_pairs"] > 0
    assert telemetry["stage_ms"]["constraint_ms"] > 0.0
    assert telemetry["stage_ms"]["material_neighbor_ms"] > 0.0


def test_native_material_neighbor_pair_matches_reference_semantics() -> None:
    native_world = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), material="goo"),
            SimulationParticle((0.08, 0.0, 0.0), material="goo"),
        ],
        fields=[], self_collision=False, substeps=1, constraint_iterations=3,
    )
    reference_world = copy.deepcopy(native_world)
    execute_compiled_simulation(compile_simulation_world(native_world, backend="native_cpu"), native_world, 1 / 60)
    execute_compiled_simulation(
        compile_simulation_world(reference_world, backend="reference_cpu"), reference_world, 1 / 60
    )

    assert [item.position for item in native_world.particles] == pytest.approx(
        [item.position for item in reference_world.particles], abs=1.0e-12
    )
    assert [item.velocity for item in native_world.particles] == pytest.approx(
        [item.velocity for item in reference_world.particles], abs=1.0e-12
    )


def test_native_sparse_volume_kernel_matches_reference_state() -> None:
    native_world = create_sparse_fire_volume()
    reference_world = copy.deepcopy(native_world)
    telemetry = execute_compiled_simulation(
        compile_simulation_world(native_world, backend="native_cpu"), native_world, 1 / 30
    )
    execute_compiled_simulation(
        compile_simulation_world(reference_world, backend="reference_cpu"), reference_world, 1 / 30
    )

    assert telemetry["execution_backend"] == "native_cpu"
    assert telemetry["backend_receipt"]["volume_cells"] > 0
    assert telemetry["stage_ms"]["sparse_volume"] > 0.0
    for name, volume in native_world.volumes.items():
        expected = reference_world.volumes[name]
        assert set(volume.cells) == set(expected.cells)
        for key, cell in volume.cells.items():
            assert cell.density == pytest.approx(expected.cells[key].density, abs=1.0e-12)
            assert cell.temperature == pytest.approx(expected.cells[key].temperature, abs=1.0e-12)
            assert cell.flame == pytest.approx(expected.cells[key].flame, abs=1.0e-12)


def test_native_sparse_volume_resident_mode_defers_readback() -> None:
    world = create_sparse_fire_volume()
    name = next(iter(world.volumes))
    key = next(iter(world.volumes[name].cells))
    initial_density = world.volumes[name].cells[key].density
    compiled = compile_simulation_world(world, backend="native_cpu")
    compiled.metadata["native_volume_resident_output"] = True

    execute_compiled_simulation(compiled, world, 1 / 30)
    second = execute_compiled_simulation(compiled, world, 1 / 30)

    assert second["backend_receipt"]["volume_reused_resident_state"]
    assert second["backend_receipt"]["volume_synchronization_points"] == 0
    assert world.volumes[name].cells[key].density == initial_density
    assert synchronize_native_sparse_volumes(world)
    assert world.volumes[name].cells[key].density < initial_density


def test_native_reformable_topology_adds_and_solves_healable_bonds() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((0.00, 0.5, 0.0), radius=0.03, material="playdoh"),
            SimulationParticle((0.06, 0.5, 0.0), radius=0.03, material="playdoh"),
            SimulationParticle((0.12, 0.5, 0.0), radius=0.03, material="playdoh"),
        ],
        fields=[], self_collision=False, substeps=1, constraint_iterations=2,
        reformable_settings={"playdoh": {
            "bond_distance": 0.08, "heal_distance": 0.07, "max_neighbors": 4,
            "max_heal_speed": 2.0, "compliance": 1.0e-5, "break_threshold": 1.6,
        }},
    )
    telemetry = execute_compiled_simulation(
        compile_simulation_world(world, backend="native_cpu"), world, 1 / 60
    )

    assert telemetry["execution_backend"] == "native_cpu"
    assert len(world.constraints) == 2
    assert all(item.reformable and item.enabled for item in world.constraints)
    assert telemetry["backend_receipt"]["constraint_colors"] > 0


def test_native_cpu_20k_particle_stress_tick_stays_bounded() -> None:
    world = _particle_world(20_000)
    compiled = compile_simulation_world(world, profile="cinematic", backend="native_cpu")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert telemetry["execution_backend"] == "native_cpu"
    assert telemetry["elapsed_ms"] < 250.0
    assert telemetry["particle_count"] == 20_000


def test_compute_provider_boundary_has_truthful_gpu_probe_and_persistent_cpu_buffer() -> None:
    statuses = {item["provider_id"]: item for item in compute_provider_statuses()}
    assert statuses["numpy_cpu"]["available"]
    assert statuses["numpy_cpu"]["device_type"] == "cpu"
    assert statuses["cupy_cuda"]["device_type"] == "gpu"
    if not statuses["cupy_cuda"]["available"]:
        assert statuses["cupy_cuda"]["reason"]

    provider = compute_provider("numpy_cpu")
    buffer = provider.allocate((4, 3), "float32")
    values = np.arange(12, dtype=np.float32).reshape(4, 3)
    provider.upload(buffer, values)
    assert buffer.residency == "persistent_host_soa"
    assert buffer.revision == 1
    assert provider.download(buffer).tolist() == values.tolist()


def test_explicit_resident_output_reuses_buffers_until_requested_readback() -> None:
    world = _particle_world(100)
    compiled = compile_simulation_world(world, backend="native_cpu")
    compiled.metadata["native_resident_output"] = True
    initial_position = world.particles[0].position

    first = execute_compiled_simulation(compiled, world, 1 / 60)
    second = execute_compiled_simulation(compiled, world, 1 / 60)
    view = native_particle_view(world)

    assert first["backend_receipt"]["resident_output"]
    assert second["backend_receipt"]["reused_resident_state"]
    assert second["backend_receipt"]["synchronization_points"] == 0
    assert world.particles[0].position == initial_position
    assert view is not None and tuple(view["positions"][0]) != initial_position
    expected = tuple(view["positions"][0])
    assert synchronize_native_particles(world)
    assert world.particles[0].position == pytest.approx(expected)


def test_gpu_executor_runs_real_array_kernels_through_provider_boundary() -> None:
    provider_id = "test_gpu_array_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))
    try:
        world = _particle_world(64)
        compiled = compile_simulation_world(world, backend="native_cpu")
        receipt = execute_gpu_compute(compiled, world, 1 / 60, provider_id=provider_id)

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["compute_provider"] == provider_id
        assert receipt["buffer_residency"] == "persistent_device"
        assert receipt["stage_ms"]["gpu_integrate_collide"] > 0.0
        assert world.particles[0].position != (0.0, 1.0, 0.0)
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_gpu_provider_executes_xpbd_area_distance_and_pairwise_material_kernels() -> None:
    provider_id = "test_gpu_multiphysics_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))
    try:
        world = create_cloth_grid(4, 4)
        world.self_collision = True
        # Exercise the material-neighbor stage without changing the cloth topology contract.
        world.materials["cotton"].viscosity = 0.05
        world.materials["cotton"].stringiness = 1.0
        repeated = copy.deepcopy(world)
        compiled = compile_simulation_world(world, backend="native_cpu")
        receipt = execute_gpu_compute(compiled, world, 1 / 60, provider_id=provider_id)
        execute_gpu_compute(
            compile_simulation_world(repeated, backend="native_cpu"), repeated, 1 / 60,
            provider_id=provider_id,
        )

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["constraint_memory_bytes"] > 0
        assert receipt["constraint_iterations"] > 0
        assert receipt["material_neighbor_pairs"] > 0
        assert np.isfinite(np.asarray([item.position for item in world.particles])).all()
        assert [item.position for item in world.particles] == [item.position for item in repeated.particles]
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_gpu_spatial_hash_broadphase_scales_beyond_legacy_pairwise_limit() -> None:
    provider_id = "test_gpu_spatial_hash_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))
    try:
        count = 5_000
        world = SimulationWorld(
            particles=[
                SimulationParticle((index * 0.2, 0.0, 0.0), radius=0.03, material="field_test")
                for index in range(count)
            ],
            fields=[], self_collision=True, substeps=1, constraint_iterations=1,
        )
        world.materials["field_test"] = SimulationMaterial("Field Test", damping=0.0)

        receipt = execute_gpu_compute(
            compile_simulation_world(world, backend="native_cpu"), world, 1 / 60,
            provider_id=provider_id,
        )

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["buffer_count"] == count
        assert receipt["self_collision_pairs"] == 0
        assert receipt["broadphase_candidates"] < count * 4
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_gpu_provider_executes_persistent_sparse_volume_kernel() -> None:
    provider_id = "test_gpu_sparse_volume_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))
    try:
        world = create_sparse_fire_volume()
        name = next(iter(world.volumes))
        key = next(iter(world.volumes[name].cells))
        initial_density = world.volumes[name].cells[key].density
        compiled = compile_simulation_world(world, backend="native_cpu")
        compiled.metadata["gpu_volume_resident_output"] = True
        execute_gpu_compute(compiled, world, 1 / 30, provider_id=provider_id)
        receipt = execute_gpu_compute(compiled, world, 1 / 30, provider_id=provider_id)

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["gpu_volume_cells"] > 0
        assert receipt["gpu_volume_memory_bytes"] > 0
        assert receipt["stage_ms"]["gpu_sparse_volume"] > 0.0
        assert receipt["gpu_volume_reused_resident_state"]
        assert receipt["gpu_volume_synchronization_points"] == 0
        assert world.volumes[name].cells[key].density == initial_density
        execute_compiled_simulation(compile_simulation_world(world, backend="native_cpu"), world, 1 / 30)
        assert world.volumes[name].cells[key].density < initial_density
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_sparse_pressure_projection_reduces_divergence_on_native_and_gpu() -> None:
    provider_id = "test_gpu_projection_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))

    def make_world() -> SimulationWorld:
        volume = SparseVolume(
            voxel_size=1.0, dissipation=0.0, cooling=0.0, buoyancy=0.0,
            pressure_iterations=60, projection_strength=1.0,
        )
        volume.cells = {
            (x, y, z): SparseVolumeCell(
                density=1.0,
                velocity=(
                    float(np.sin(x * 1.7 + y * 0.3)),
                    float(np.sin(y * 1.3 + z * 0.7 + 1.0)),
                    float(np.sin(z * 1.9 + x * 0.2 + 2.0)),
                ),
            )
            for x in range(4) for y in range(4) for z in range(4)
        }
        return SimulationWorld(particles=[], fields=[], self_collision=False, volumes={"projection": volume})

    def divergence_norm(world: SimulationWorld) -> float:
        cells = world.volumes["projection"].cells
        total = 0.0
        for key, cell in cells.items():
            divergence = 0.0
            for axis in range(3):
                negative = list(key); negative[axis] -= 1
                positive = list(key); positive[axis] += 1
                negative_velocity = cells.get(tuple(negative), cell).velocity[axis]
                positive_velocity = cells.get(tuple(positive), cell).velocity[axis]
                divergence += (positive_velocity - negative_velocity) * 0.5
            total += divergence * divergence
        return float(np.sqrt(total))

    try:
        reference = make_world()
        native = make_world()
        gpu = make_world()
        initial_divergence = divergence_norm(reference)
        execute_compiled_simulation(compile_simulation_world(reference, backend="reference_cpu"), reference, 1 / 30)
        native_receipt = execute_compiled_simulation(
            compile_simulation_world(native, backend="native_cpu"), native, 1 / 30
        )
        gpu_receipt = execute_gpu_compute(
            compile_simulation_world(gpu, backend="native_cpu"), gpu, 1 / 30,
            provider_id=provider_id,
        )

        assert divergence_norm(reference) < initial_divergence
        assert native_receipt["backend_receipt"]["volume_projection_iterations"] == 60
        assert gpu_receipt["gpu_volume_projection_iterations"] == 60
        for key, expected in reference.volumes["projection"].cells.items():
            assert native.volumes["projection"].cells[key].velocity == pytest.approx(expected.velocity, abs=2.0e-10)
            assert gpu.volumes["projection"].cells[key].velocity == pytest.approx(expected.velocity, abs=2.0e-5)
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_gpu_provider_executes_bounded_triangle_mesh_collision_kernel() -> None:
    provider_id = "test_gpu_mesh_provider"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU", True), np,
    ))
    try:
        world = SimulationWorld(
            particles=[SimulationParticle(
                (0.0, 0.02, 0.0), velocity=(0.2, -0.1, 0.0), radius=0.03,
                material="native_particle",
            )],
            fields=[], self_collision=False, substeps=1, constraint_iterations=1,
            mesh_colliders=[TriangleMeshCollider(
                [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)], [(0, 1, 2)]
            )],
        )
        world.materials["native_particle"] = SimulationMaterial("Native Particle")
        reference = copy.deepcopy(world)
        receipt = execute_gpu_compute(
            compile_simulation_world(world, backend="native_cpu"), world, 1 / 60,
            provider_id=provider_id,
        )
        execute_compiled_simulation(
            compile_simulation_world(reference, backend="reference_cpu"), reference, 1 / 60
        )

        assert receipt["execution_backend"] == "gpu_compute"
        assert world.particles[0].position == pytest.approx(reference.particles[0].position, abs=2.0e-5)
        assert world.particles[0].velocity == pytest.approx(reference.particles[0].velocity, abs=2.0e-5)
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_gpu_backend_status_matches_optional_cuda_provider() -> None:
    cuda = {item["provider_id"]: item for item in compute_provider_statuses()}["cupy_cuda"]
    gpu = simulation_backend_status("gpu_compute")
    if cuda["available"]:
        assert gpu["available"]
    if not gpu["available"]:
        assert gpu["reason"]


def test_registered_gpu_backend_dispatches_through_compiled_ir_when_available() -> None:
    if not simulation_backend_status("gpu_compute")["available"]:
        pytest.skip("No qualified hardware GPU provider is available.")
    world = _particle_world(128)
    compiled = compile_simulation_world(world, backend="gpu_compute")
    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    assert compiled.backend.backend_id == "gpu_compute"
    assert telemetry["execution_backend"] == "gpu_compute"
    assert telemetry["execution_device"] == "gpu"
    assert telemetry["backend_receipt"]["compute_provider"]
    assert telemetry["stage_ms"]


def test_compiled_particle_chain_uses_native_gpu_distance_constraint_stage() -> None:
    if not simulation_backend_status("gpu_compute")["available"]:
        pytest.skip("No qualified hardware GPU provider is available.")
    world = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), material="native_particle"),
            SimulationParticle((2.0, 0.0, 0.0), material="native_particle"),
        ],
        constraints=[DistanceConstraint(0, 1, 1.0)], fields=[], self_collision=False,
        substeps=2, constraint_iterations=8,
    )
    world.materials["native_particle"] = SimulationMaterial("Native Particle")
    compiled = compile_simulation_world(world, backend="gpu_compute")

    telemetry = execute_compiled_simulation(compiled, world, 1 / 60)

    dispatch = telemetry["backend_receipt"]["dispatch_telemetry"]
    assert telemetry["execution_backend"] == "gpu_compute"
    assert "distance_constraints" in dispatch["supported_stages"]
    assert np.linalg.norm(np.subtract(world.particles[1].position, world.particles[0].position)) == pytest.approx(
        1.0, abs=2.0e-4
    )


def test_compiled_gpu_resident_state_hands_back_safely_to_native_cpu() -> None:
    if not simulation_backend_status("gpu_compute")["available"]:
        pytest.skip("No qualified hardware GPU provider is available.")
    world = _particle_world(128)
    initial = world.particles[0].position
    gpu_compiled = compile_simulation_world(world, backend="gpu_compute")
    gpu_compiled.metadata["gpu_resident_output"] = True
    execute_compiled_simulation(gpu_compiled, world, 1 / 60)
    resident = execute_compiled_simulation(gpu_compiled, world, 1 / 60)

    assert resident["gpu_resident"]
    assert resident["backend_receipt"]["synchronization_points"] == 0
    assert world.particles[0].position == initial

    native = execute_compiled_simulation(compile_simulation_world(world, backend="native_cpu"), world, 1 / 60)
    assert native["execution_backend"] == "native_cpu"
    assert world.particles[0].position != initial
    assert not getattr(world, "_gpu_buffers_authoritative", False)


def test_resident_constraint_controls_are_detected_without_topology_rebuild() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), material="native_particle"),
            SimulationParticle((1.0, 0.0, 0.0), material="native_particle"),
        ],
        fields=[], self_collision=False, substeps=1, constraint_iterations=1,
    )
    world.materials["native_particle"] = SimulationMaterial("Native Particle")
    world.constraints.append(DistanceConstraint(0, 1, 0.5, compliance=1.0e-5))
    compiled = compile_simulation_world(world, backend="native_cpu")
    compiled.metadata["native_resident_output"] = True
    execute_compiled_simulation(compiled, world, 1 / 60)
    reallocations = world._native_constraint_buffers.reallocations

    world.constraints[0].rest_length = 0.8
    execute_compiled_simulation(compiled, world, 1 / 60)

    assert world._native_constraint_buffers.distance_rest[0] == pytest.approx(0.8)
    assert world._native_constraint_buffers.reallocations == reallocations
