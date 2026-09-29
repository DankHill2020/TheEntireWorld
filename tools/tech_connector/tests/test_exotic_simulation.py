from __future__ import annotations

import copy
import math
import random

import pytest
import numpy as np

from tech_connector.game_engine.runtime.tc_exotic_simulation_service import (
    create_exotic_simulation,
    exotic_authoring_schema,
    exotic_simulation_preset_names,
    simulation_diagnostics,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    compile_simulation_world,
    execute_compiled_simulation,
)
from tech_connector.game_engine.runtime.tc_simulation_service import (
    ForceField,
    ParticleInteractionSettings,
    SimulationMaterial,
    SimulationParticle,
    SimulationWorld,
)
from tech_connector.game_engine.runtime.tc_plasma_pic_service import ElectrostaticPicGrid
from tech_connector.game_engine.runtime.tc_magnetic_grid_service import MagnetodynamicGrid
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider, COMPUTE_PROVIDERS, ComputeProviderStatus, register_compute_provider,
)
from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import execute_gpu_compute


def test_exotic_presets_are_discoverable_and_have_clean_live_authoring_contract() -> None:
    assert exotic_simulation_preset_names() == [
        "binary_star", "asteroid_ring", "accretion_disk", "roche_breakup", "stellar_merger",
        "magnetosphere", "pic_double_layer", "aurora_curtain", "plasma_jet",
        "molecular_gas", "ferrofluid_lab",
    ]
    schema = exotic_authoring_schema()
    assert schema["schema"] == "tech_connector.exotic_authoring.v1"
    assert {item["accuracy"] for item in schema["presets"]} == {"grounded", "approximation", "cinematic"}
    assert {"activate", "drag_source", "field_lines", "trails", "time_scrub"} <= set(schema["viewport_tools"])
    assert {"linear_momentum", "angular_momentum", "total_charge"} <= set(schema["diagnostics"])


def test_binary_star_starts_at_barycenter_and_preserves_equal_opposite_momentum() -> None:
    world = create_exotic_simulation("binary_star")
    before = simulation_diagnostics(world)
    for _ in range(20):
        world.step(1.0 / 240.0)
    after = simulation_diagnostics(world)

    assert before["center_of_mass"] == pytest.approx((0.0, 0.0, 0.0), abs=1.0e-12)
    assert after["center_of_mass"] == pytest.approx((0.0, 0.0, 0.0), abs=1.0e-12)
    assert after["linear_momentum"] == pytest.approx((0.0, 0.0, 0.0), abs=5.0e-12)
    assert world.particles[0].position != pytest.approx((-3.1515151515, 0.0, 0.0))


def test_electric_and_magnetic_fields_use_particle_charge_to_mass() -> None:
    electric = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), mass=2.0, charge=1.0),
            SimulationParticle((0.0, 1.0, 0.0), mass=2.0, charge=-1.0),
        ],
        fields=[ForceField("electric_field", vector=(4.0, 0.0, 0.0), strength=1.0)],
        self_collision=False, substeps=1, constraint_iterations=1,
    )
    electric.materials["water"] = SimulationMaterial("Undamped", damping=0.0)
    electric.step(0.1)
    assert electric.particles[0].velocity == pytest.approx((0.2, 0.0, 0.0))
    assert electric.particles[1].velocity == pytest.approx((-0.2, 0.0, 0.0))

    magnetic = SimulationWorld(
        particles=[SimulationParticle((0.0, 0.0, 0.0), velocity=(1.0, 0.0, 0.0), mass=1.0, charge=1.0)],
        fields=[ForceField("magnetic", vector=(0.0, 1.0, 0.0))],
        self_collision=False, substeps=1, constraint_iterations=1,
    )
    magnetic.materials["water"] = SimulationMaterial("Undamped", damping=0.0)
    magnetic.step(0.1)
    assert magnetic.particles[0].velocity == pytest.approx((1.0, 0.0, 0.1))


def test_pair_electrostatics_and_molecular_repulsion_are_directionally_correct() -> None:
    electrostatic = SimulationWorld(
        particles=[
            SimulationParticle((-0.5, 0.0, 0.0), mass=1.0, charge=1.0),
            SimulationParticle((0.5, 0.0, 0.0), mass=1.0, charge=1.0),
        ], fields=[], self_collision=False, substeps=1, constraint_iterations=1,
        interactions=ParticleInteractionSettings(coulomb_constant=1.0, softening=1.0e-6),
    )
    electrostatic.materials["water"] = SimulationMaterial("Undamped", damping=0.0)
    electrostatic.step(0.01)
    assert electrostatic.particles[0].velocity[0] < 0.0
    assert electrostatic.particles[1].velocity[0] > 0.0

    molecular = SimulationWorld(
        particles=[SimulationParticle((-0.025, 0.0, 0.0), mass=1.0), SimulationParticle((0.025, 0.0, 0.0), mass=1.0)],
        fields=[], self_collision=False, substeps=1, constraint_iterations=1,
        interactions=ParticleInteractionSettings(lennard_jones_epsilon=0.01, lennard_jones_sigma=0.1, cutoff=0.3, maximum_acceleration=100.0),
    )
    molecular.materials["water"] = SimulationMaterial("Undamped", damping=0.0)
    molecular.step(0.001)
    assert molecular.particles[0].velocity[0] < 0.0
    assert molecular.particles[1].velocity[0] > 0.0


def test_native_space_interactions_match_reference_and_compile_explicit_ir_stage() -> None:
    reference = create_exotic_simulation("binary_star")
    native = copy.deepcopy(reference)
    reference_compiled = compile_simulation_world(reference, backend="reference_cpu")
    native_compiled = compile_simulation_world(native, backend="native_cpu")
    interaction_stage = next(stage for stage in native_compiled.stages if stage.stage_id == "particle_interactions")

    execute_compiled_simulation(reference_compiled, reference, 1.0 / 120.0)
    receipt = execute_compiled_simulation(native_compiled, native, 1.0 / 120.0)

    assert interaction_stage.parameters["gravity"]
    assert native_compiled.metadata["scale"]["accuracy_mode"] == "grounded"
    assert receipt["execution_backend"] == "native_cpu"
    assert [particle.position for particle in native.particles] == pytest.approx(
        [particle.position for particle in reference.particles], abs=1.0e-11
    )
    assert all(math.isfinite(value) for particle in native.particles for value in particle.position)


def test_invalid_scale_is_rejected_before_simulation() -> None:
    world = create_exotic_simulation("binary_star")
    world.scale.distance_unit_meters = 0.0
    with pytest.raises(ValueError, match="distance_unit_meters"):
        world.step(1.0 / 60.0)


def test_asteroid_ring_uses_dominant_source_path_instead_of_all_to_all_material_work() -> None:
    world = create_exotic_simulation("asteroid_ring", particle_count=512)
    compiled = compile_simulation_world(world, backend="native_cpu")
    receipt = execute_compiled_simulation(compiled, world, 1.0 / 60.0)

    assert receipt["execution_backend"] == "native_cpu"
    assert receipt["backend_receipt"]["material_neighbor_pairs"] == 0
    assert receipt["stage_ms"]["integration_ms"] < 50.0
    assert world.interactions.gravity_source_mass_threshold > 1.0


def test_barnes_hut_tracks_exact_gravity_with_bounded_error_and_fewer_interactions() -> None:
    rng = random.Random(19)
    particles = [SimulationParticle(
        (rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0)),
        mass=rng.uniform(0.5, 2.0), material="vacuum",
    ) for _ in range(160)]
    exact = SimulationWorld(
        particles=copy.deepcopy(particles), fields=[], self_collision=False,
        interactions=ParticleInteractionSettings(
            gravity_constant=1.0, softening=0.03, long_range_method="exact",
        ),
    )
    tree = SimulationWorld(
        particles=copy.deepcopy(particles), fields=[], self_collision=False,
        interactions=ParticleInteractionSettings(
            gravity_constant=1.0, softening=0.03, long_range_method="barnes_hut",
            opening_angle=0.5, tree_leaf_capacity=1,
        ),
    )
    exact_acceleration = [(0.0, 0.0, 0.0) for _ in particles]
    tree_acceleration = [(0.0, 0.0, 0.0) for _ in particles]
    exact._accumulate_particle_interactions(exact_acceleration)
    tree._accumulate_particle_interactions(tree_acceleration)
    relative_errors = []
    for actual, expected in zip(tree_acceleration, exact_acceleration):
        error = math.sqrt(sum((actual[axis] - expected[axis]) ** 2 for axis in range(3)))
        magnitude = math.sqrt(sum(value * value for value in expected))
        relative_errors.append(error / max(1.0e-9, magnitude))

    assert sorted(relative_errors)[int(len(relative_errors) * 0.95)] < 0.04
    assert tree._interaction_diagnostics["method"] == "barnes_hut"
    assert tree._interaction_diagnostics["direct_interactions"] < exact._interaction_diagnostics["direct_interactions"]


def test_stellar_merger_conserves_mass_charge_and_linear_momentum() -> None:
    world = create_exotic_simulation("stellar_merger")
    before = simulation_diagnostics(world)
    world.step(0.01)
    after = simulation_diagnostics(world)

    assert sum(particle.alive for particle in world.particles) == 1
    assert after["total_mass"] == pytest.approx(before["total_mass"])
    assert after["total_charge"] == pytest.approx(before["total_charge"])
    assert after["linear_momentum"] == pytest.approx(before["linear_momentum"], abs=1.0e-12)
    assert after["interaction_solver"]["merges"] == 1


def test_roche_body_breaks_constraints_under_tidal_gradient() -> None:
    world = create_exotic_simulation("roche_breakup")
    initial = sum(constraint.enabled for constraint in world.constraints)
    world.step(1.0 / 60.0)
    remaining = sum(constraint.enabled for constraint in world.constraints)

    assert initial == 144
    assert 0 < remaining < initial


def test_accretion_disk_dominant_source_tick_remains_bounded() -> None:
    world = create_exotic_simulation("accretion_disk", particle_count=1500)
    receipt = execute_compiled_simulation(compile_simulation_world(world, backend="native_cpu"), world, 1.0 / 60.0)

    assert receipt["execution_backend"] == "native_cpu"
    assert receipt["particle_count"] == 1501
    assert receipt["stage_ms"]["integration_ms"] < 75.0


def test_molecular_spatial_hash_matches_exact_cutoff_and_rejects_distant_pairs() -> None:
    particles = [SimulationParticle(
        ((index // 36) * 0.2, ((index // 6) % 6) * 0.2, (index % 6) * 0.2),
        mass=1.0, material="molecular",
    ) for index in range(216)]
    settings = dict(
        lennard_jones_epsilon=0.002, lennard_jones_sigma=0.16,
        cutoff=0.31, softening=1.0e-5, maximum_acceleration=50.0,
    )
    exact = SimulationWorld(
        particles=copy.deepcopy(particles), fields=[], self_collision=False,
        interactions=ParticleInteractionSettings(**settings, short_range_method="exact"),
    )
    hashed = SimulationWorld(
        particles=copy.deepcopy(particles), fields=[], self_collision=False,
        interactions=ParticleInteractionSettings(**settings, short_range_method="spatial_hash"),
    )
    exact_acceleration = [(0.0, 0.0, 0.0) for _ in particles]
    hash_acceleration = [(0.0, 0.0, 0.0) for _ in particles]
    exact._accumulate_particle_interactions(exact_acceleration)
    hashed._accumulate_particle_interactions(hash_acceleration)

    for actual, expected in zip(hash_acceleration, exact_acceleration):
        assert actual == pytest.approx(expected, abs=1.0e-12)
    assert hashed._interaction_diagnostics["method"] == "spatial_hash"
    assert hashed._interaction_diagnostics["candidate_pairs"] < len(particles) * (len(particles) - 1) // 4


def test_pic_cic_deposition_conserves_charge_and_self_consistent_field_attracts_opposites() -> None:
    grid = ElectrostaticPicGrid(
        bounds_min=(-3.0, -2.0, -2.0), bounds_max=(3.0, 2.0, 2.0),
        resolution=(21, 13, 13), potential_iterations=80,
    )
    world = SimulationWorld(
        particles=[
            SimulationParticle((-1.0, 0.0, 0.0), mass=1.0, charge=1.0),
            SimulationParticle((1.0, 0.0, 0.0), mass=1.0, charge=-1.0),
        ],
        fields=[], self_collision=False, substeps=1, constraint_iterations=1,
        pic_grids=[grid],
    )
    world.materials["water"] = SimulationMaterial("Undamped", damping=0.0)
    world.step(0.01)

    assert grid.diagnostics["deposited_charge"] == pytest.approx(0.0, abs=1.0e-12)
    assert grid.diagnostics["grid_charge"] == pytest.approx(0.0, abs=1.0e-12)
    assert grid.diagnostics["maximum_field"] > 0.0
    assert world.particles[0].velocity[0] > 0.0
    assert world.particles[1].velocity[0] < 0.0
    assert world.particles[0].velocity[0] == pytest.approx(-world.particles[1].velocity[0], rel=1.0e-10)


def test_pic_stage_compiles_and_truthfully_falls_back_until_gpu_grid_kernels_land() -> None:
    world = create_exotic_simulation("pic_double_layer", particle_count=24)
    compiled = compile_simulation_world(world, backend="native_cpu")
    stage = next(item for item in compiled.stages if item.stage_id == "pic_fields")
    receipt = execute_compiled_simulation(compiled, world, 1.0 / 120.0)

    assert stage.parameters["operations"] == ["cic_deposit", "poisson", "electric_gradient", "cic_sample"]
    assert any(resource.resource_id == "electromagnetic_grid" for resource in compiled.resources)
    assert receipt["execution_backend"] == "reference_cpu"
    assert "PIC grid coupling" in " ".join(receipt["backend_receipt"]["fallback_reasons"])
    assert world.pic_grids[0].diagnostics["active_particles"] == 24


def test_gpu_provider_runs_resident_pic_pipeline_with_reference_parity() -> None:
    provider_id = "test_exotic_gpu_pic"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU PIC", True), np,
    ))
    try:
        reference = create_exotic_simulation("pic_double_layer", particle_count=24)
        gpu = copy.deepcopy(reference)
        reference.step(1.0 / 120.0)
        receipt = execute_gpu_compute(
            compile_simulation_world(gpu, backend="native_cpu"), gpu, 1.0 / 120.0,
            provider_id=provider_id,
        )

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["gpu_pic_cells"] == 14 * 12 * 12
        assert receipt["gpu_pic_memory_bytes"] > 0
        assert receipt["gpu_pic_ms"] > 0.0
        assert receipt["gpu_pic_grids"][0]["execution"] == "gpu"
        assert receipt["gpu_pic_grids"][0]["gauss_residual_l2"] > 0.0
        for actual, expected in zip(gpu.particles, reference.particles):
            assert actual.position == pytest.approx(expected.position, abs=2.0e-5)
            assert actual.velocity == pytest.approx(expected.velocity, abs=2.0e-4)

        resident_world = create_exotic_simulation("pic_double_layer", particle_count=24)
        resident_compiled = compile_simulation_world(resident_world, backend="native_cpu")
        resident_compiled.metadata["gpu_resident_output"] = True
        execute_gpu_compute(resident_compiled, resident_world, 1.0 / 120.0, provider_id=provider_id)
        second = execute_gpu_compute(resident_compiled, resident_world, 1.0 / 120.0, provider_id=provider_id)
        assert second["gpu_pic_resident"]
        assert second["gpu_pic_reused_state"]
        assert second["reused_resident_state"]
        assert second["synchronization_points"] == 0
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)


def test_magnetic_grid_cleans_divergence_and_resistivity_dissipates_energy() -> None:
    grid = MagnetodynamicGrid(
        resolution=(10, 10, 10), uniform_field=(0.0, 0.0, 0.0),
        resistivity=0.2, divergence_clean_iterations=40,
    )
    rng = np.random.default_rng(7)
    grid.magnetic_field = rng.normal(0.0, 0.1, (10, 10, 10, 3))
    cleaned = grid.solve([], 0.0)
    initial_energy = cleaned["magnetic_energy"]
    diffused = grid.solve([], 0.02)

    assert cleaned["divergence_l2_after"] < cleaned["divergence_l2_before"]
    assert diffused["magnetic_energy"] < initial_energy
    assert diffused["current_rms"] > 0.0
    assert diffused["reconnection_energy"] > 0.0


def test_magnetic_induction_stage_compiles_and_upgraded_space_weather_preset_runs() -> None:
    world = create_exotic_simulation("magnetosphere", particle_count=24)
    compiled = compile_simulation_world(world, backend="native_cpu")
    stage = next(item for item in compiled.stages if item.stage_id == "magnetic_induction")
    receipt = execute_compiled_simulation(compiled, world, 1.0 / 120.0)

    assert "divergence_clean" in stage.parameters["operations"]
    assert any(resource.resource_id == "magnetic_grid" for resource in compiled.resources)
    assert receipt["execution_backend"] == "reference_cpu"
    diagnostics = world.magnetic_grids[0].diagnostics
    assert diagnostics["deposited_particles"] == 24
    assert diagnostics["maximum_field"] > 0.0
    assert diagnostics["divergence_l2_after"] <= diagnostics["divergence_l2_before"]


def test_gpu_provider_runs_resident_magnetic_pipeline_with_reference_parity() -> None:
    provider_id = "test_exotic_gpu_magnetic"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU Magnetic", True), np,
    ))
    try:
        reference = create_exotic_simulation("magnetosphere", particle_count=24)
        gpu = copy.deepcopy(reference)
        reference.step(1.0 / 120.0)
        receipt = execute_gpu_compute(
            compile_simulation_world(gpu, backend="native_cpu"), gpu, 1.0 / 120.0,
            provider_id=provider_id,
        )

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["gpu_magnetic_cells"] == 14 * 12 * 12
        assert receipt["gpu_magnetic_memory_bytes"] > 0
        assert receipt["gpu_magnetic_ms"] > 0.0
        assert receipt["gpu_magnetic_grids"][0]["execution"] == "gpu"
        assert receipt["gpu_magnetic_grids"][0]["divergence_l2_after"] <= (
            receipt["gpu_magnetic_grids"][0]["divergence_l2_before"]
        )
        assert "magnetic_lorentz_sample" in receipt["supported_stages"]
        for actual, expected in zip(gpu.particles, reference.particles):
            assert actual.position == pytest.approx(expected.position, abs=2.0e-5)
            assert actual.velocity == pytest.approx(expected.velocity, abs=3.0e-4)

        resident_world = create_exotic_simulation("magnetosphere", particle_count=24)
        resident_compiled = compile_simulation_world(resident_world, backend="native_cpu")
        resident_compiled.metadata["gpu_resident_output"] = True
        execute_gpu_compute(resident_compiled, resident_world, 1.0 / 120.0, provider_id=provider_id)
        second = execute_gpu_compute(resident_compiled, resident_world, 1.0 / 120.0, provider_id=provider_id)
        assert second["gpu_magnetic_resident"]
        assert second["gpu_magnetic_reused_state"]
        assert second["gpu_magnetic_grids"][0]["readback_deferred"]
        assert second["reused_resident_state"]
        assert second["synchronization_points"] == 0
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)
