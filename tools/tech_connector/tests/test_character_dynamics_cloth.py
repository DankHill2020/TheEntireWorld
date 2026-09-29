from __future__ import annotations

import copy
import numpy as np
import pytest

from tech_connector.game_engine.deformation import (
    DeformationWeightMap,
    FleshDeformerSettings,
    FleshRuntimeState,
    JiggleDeformerSettings,
    JiggleRuntimeState,
    evaluate_flesh,
    evaluate_jiggle,
    project_character_point,
)
from tech_connector.game_engine.runtime.tc_cloth_authoring_service import (
    ClothPropertyMaps,
    apply_cloth_property_maps,
    cloth_authoring_schema,
    cloth_diagnostics,
    cloth_export_contract,
    configure_cloth_collision_layers,
    configure_cloth_quality,
    create_cloth_seams,
    enable_dihedral_bending,
)
from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import gpu_backend_support
from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import execute_gpu_compute
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider, COMPUTE_PROVIDERS, ComputeProviderStatus, register_compute_provider,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world
from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import native_backend_support
from tech_connector.game_engine.runtime.tc_simulation_service import (
    DistanceConstraint,
    SimulationParticle,
    SimulationWorld,
    _signed_dihedral_angle,
    _wrapped_angle,
    create_cloth_from_geometry,
    create_cloth_grid,
)


def test_character_collision_supports_swept_spheres_capsules_and_boxes() -> None:
    swept, velocity, contacts = project_character_point(
        (2.0, 0.0, 0.0), (20.0, 0.0, 0.0), previous_position=(-2.0, 0.0, 0.0),
        radius=0.1, friction=0.0, restitution=0.0,
        colliders=[{"type": "sphere", "center": (0.0, 0.0, 0.0), "radius": 0.5}],
    )
    assert swept[0] == pytest.approx(-0.6)
    assert velocity[0] == pytest.approx(0.0)
    assert contacts == 1

    capsule, _velocity, contacts = project_character_point(
        (0.1, 0.0, 0.0), (0.0, 0.0, 0.0), radius=0.05, friction=0.2, restitution=0.0,
        colliders=[{"type": "capsule", "start": (0.0, -1.0, 0.0), "end": (0.0, 1.0, 0.0), "radius": 0.4}],
    )
    assert capsule[0] == pytest.approx(0.45)
    assert contacts == 1

    box, _velocity, contacts = project_character_point(
        (0.1, 0.2, 0.48), (0.0, 0.0, -1.0), radius=0.05, friction=0.0, restitution=0.0,
        colliders=[{"type": "box", "center": (0.0, 0.0, 0.0), "half_extents": (1.0, 1.0, 0.5)}],
    )
    assert box[2] == pytest.approx(0.55)
    assert contacts == 1


def test_jiggle_and_flesh_share_character_capsule_collision() -> None:
    collider = [{"type": "capsule", "start": (0.0, -1.0, 0.0), "end": (0.0, 1.0, 0.0), "radius": 0.5}]
    weights = DeformationWeightMap("body", [1.0])
    jiggle_state = JiggleRuntimeState()
    jiggle_settings = JiggleDeformerSettings(collision_radius=0.05)
    evaluate_jiggle([(0.1, 0.0, 0.0)], weights, jiggle_state, jiggle_settings, 1.0 / 60.0)
    jiggle = evaluate_jiggle(
        [(0.1, 0.0, 0.0)], weights, jiggle_state, jiggle_settings, 1.0 / 60.0, colliders=collider,
    )
    assert jiggle[0][0] >= 0.55 - 1.0e-8
    assert jiggle_state.collision_count > 0

    flesh_state = FleshRuntimeState()
    flesh_settings = FleshDeformerSettings(collision_radius=0.05)
    evaluate_flesh([(0.1, 0.0, 0.0)], weights, flesh_state, flesh_settings, 1.0 / 60.0)
    flesh = evaluate_flesh(
        [(0.1, 0.0, 0.0)], weights, flesh_state, flesh_settings, 1.0 / 60.0, colliders=collider,
    )
    assert flesh[0][0] >= 0.55 - 1.0e-8
    assert flesh_state.collision_count > 0


def test_cloth_profiles_property_maps_seams_diagnostics_and_export_are_coherent() -> None:
    world = create_cloth_grid(3, 3, pin_top_corners=False)
    diagnostics = configure_cloth_quality(world, "hero", strain_warning=1.1)
    assert diagnostics["quality_profile"] == "hero"
    assert world.substeps == 8
    assert world.constraint_iterations == 20
    assert world.bending_constraints
    assert all(item.strain_limit == pytest.approx(1.12) for item in world.constraints if item.constraint_type in {"stretch", "shear"})

    count = len(world.particles)
    mapped = apply_cloth_property_maps(world, ClothPropertyMaps(
        pin=(1.0, 0.5) + (0.0,) * (count - 2),
        mass_scale=(2.0,) * count,
        stretch_stiffness=(1.0,) * count,
        bend_stiffness=(0.5,) * count,
        collision_thickness=(0.75,) * count,
        drag=(0.25,) * count,
    ))
    seam_ids = create_cloth_seams(world, [(6, 8), (8, 6)], compliance=1.0e-7, break_threshold=1.25)
    final = cloth_diagnostics(world)

    assert world.particles[0].pinned
    assert world.particles[0].inverse_mass == 0.0
    assert world.particles[1].inverse_mass == pytest.approx(0.5)
    assert mapped["soft_pins"] == 1
    assert len(seam_ids) == 1
    assert final["constraints_by_type"]["seam"] == 1
    assert final["status"] == "healthy"
    assert {"paint_properties", "sew_edges", "strain_heatmap"} <= set(cloth_authoring_schema()["tools"])
    for destination in ("houdini", "unreal", "maya", "blender", "unity", "usd", "fbx", "gltf"):
        contract = cloth_export_contract(destination)
        assert contract["canonical_skin_preserved"]
        assert contract["runtime_transfer"]


def test_true_dihedral_bending_reduces_fold_error_and_is_backend_qualified() -> None:
    world = create_cloth_from_geometry(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        [(0, 1, 2), (1, 3, 2)],
    )
    enable_dihedral_bending(world, compliance=0.0)
    constraint = world.bending_constraints[0]
    world.particles[constraint.opposite_second].position = (1.0, 1.0, 0.8)

    def error() -> float:
        return abs(_wrapped_angle(_signed_dihedral_angle(
            world.particles[constraint.edge_first].position,
            world.particles[constraint.edge_second].position,
            world.particles[constraint.opposite_first].position,
            world.particles[constraint.opposite_second].position,
        ) - constraint.rest_angle))

    before = error()
    for _ in range(8):
        world._solve_bending_constraints(1.0 / 120.0)
    assert error() < before * 0.05
    assert "dihedral" in " ".join(native_backend_support(world)[1]).lower()
    assert gpu_backend_support(world)[0]


def test_hard_strain_limit_prevents_extreme_cloth_extension() -> None:
    world = SimulationWorld(
        particles=[SimulationParticle((0.0, 0.0, 0.0)), SimulationParticle((3.0, 0.0, 0.0))],
        constraints=[DistanceConstraint(0, 1, 1.0, compliance=1.0, strain_limit=1.1)],
        fields=[], self_collision=False,
    )
    world._solve_distance_constraints(1.0 / 60.0)
    distance = abs(world.particles[1].position[0] - world.particles[0].position[0])
    assert distance <= 1.1 + 1.0e-9
    assert "strain" in " ".join(native_backend_support(world)[1]).lower()
    assert gpu_backend_support(world)[0]


def test_layered_cloth_collision_masks_priorities_and_topology_exclusions() -> None:
    filtered = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), radius=0.5, phase="cloth"),
            SimulationParticle((0.1, 0.0, 0.0), radius=0.5, phase="cloth"),
        ], fields=[], self_collision=True,
    )
    configure_cloth_collision_layers(filtered, [0, 1], mode="same_layer")
    before = [item.position for item in filtered.particles]
    filtered._solve_particle_contacts()
    assert [item.position for item in filtered.particles] == before

    prioritized = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), radius=0.5, phase="cloth"),
            SimulationParticle((0.1, 0.0, 0.0), radius=0.5, phase="cloth"),
        ], fields=[], self_collision=True,
    )
    configure_cloth_collision_layers(prioritized, [0, 1], priorities=[9.0, 0.0], mode="all")
    prioritized._solve_particle_contacts()
    first_motion = abs(prioritized.particles[0].position[0])
    second_motion = abs(prioritized.particles[1].position[0] - 0.1)
    assert first_motion < second_motion

    adjacent = SimulationWorld(
        particles=[
            SimulationParticle((0.0, 0.0, 0.0), radius=0.5, phase="cloth"),
            SimulationParticle((0.1, 0.0, 0.0), radius=0.5, phase="cloth"),
        ], constraints=[DistanceConstraint(0, 1, 0.1)], fields=[], self_collision=True,
        cloth_settings={"exclude_topological_neighbors": True},
    )
    before = [item.position for item in adjacent.particles]
    adjacent._solve_particle_contacts()
    assert [item.position for item in adjacent.particles] == before


def test_provider_gpu_runs_resident_hero_cloth_with_reference_parity() -> None:
    provider_id = "test_gpu_hero_cloth"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Test GPU Hero Cloth", True), np,
    ))
    try:
        reference = create_cloth_grid(4, 4)
        configure_cloth_quality(reference, "hero")
        gpu = copy.deepcopy(reference)
        reference.step(1.0 / 120.0)
        compiled = compile_simulation_world(gpu, backend="native_cpu")
        receipt = execute_gpu_compute(compiled, gpu, 1.0 / 120.0, provider_id=provider_id)

        assert receipt["execution_backend"] == "gpu_compute"
        assert receipt["gpu_dihedral_constraints"] == len(gpu.bending_constraints)
        assert receipt["gpu_strain_constraints"] > 0
        assert {"dihedral_bending", "hard_strain_limit", "layered_cloth_collision"} <= set(receipt["supported_stages"])
        for actual, expected in zip(gpu.particles, reference.particles):
            assert actual.position == pytest.approx(expected.position, abs=2.0e-5)
            assert actual.velocity == pytest.approx(expected.velocity, abs=5.0e-4)

        resident = create_cloth_grid(4, 4)
        configure_cloth_quality(resident, "hero")
        resident_compiled = compile_simulation_world(resident, backend="native_cpu")
        resident_compiled.metadata["gpu_resident_output"] = True
        execute_gpu_compute(resident_compiled, resident, 1.0 / 120.0, provider_id=provider_id)
        second = execute_gpu_compute(resident_compiled, resident, 1.0 / 120.0, provider_id=provider_id)
        assert second["reused_resident_state"]
        assert second["synchronization_points"] == 0
    finally:
        COMPUTE_PROVIDERS.pop(provider_id, None)
