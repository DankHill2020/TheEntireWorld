import pytest

from tech_connector.services.dcc.tc_simulation_service import (
    CurveFlowField,
    ForceField,
    GeometryEmitter,
    SimulationCache,
    SimulationParticle,
    SimulationWorld,
    TriangleMeshCollider,
    attach_particles,
    create_cloth_grid,
    create_cloth_from_geometry,
    create_breakable_solid_from_geometry,
    create_fluid_from_geometry,
    create_particle_block,
    create_reformable_dough_from_geometry,
    create_soft_body_from_geometry,
    create_sparse_fire_volume,
    signed_mesh_volume,
)
from tech_connector.services.dcc.tc_simulation_transfer_service import build_simulation_transfer_manifest


def test_cloth_grid_stays_constrained_and_collides_with_floor() -> None:
    world = create_cloth_grid(6, 6, spacing=0.1, origin=(-0.25, 0.8, 0.0))
    pinned = [particle.position for particle in world.particles if particle.pinned]
    for _ in range(90):
        world.step(1.0 / 60.0)

    assert [particle.position for particle in world.particles if particle.pinned] == pinned
    assert min(particle.position[1] - particle.radius for particle in world.particles) >= -1.0e-5
    stretch = [constraint for constraint in world.constraints if constraint.constraint_type == "stretch"]
    assert max(
        abs(
            ((sum((world.particles[item.second].position[i] - world.particles[item.first].position[i]) ** 2 for i in range(3)) ** 0.5) / item.rest_length) - 1.0
        )
        for item in stretch
    ) < 0.08


def test_water_goo_and_gravy_presets_create_colliding_fluid_particles() -> None:
    for material in ("water", "goo", "gravy"):
        world = create_particle_block((3, 3, 3), spacing=0.08, origin=(-0.08, 0.2, -0.08), material=material)
        world.step(1.0 / 24.0)
        assert len(world.particles) == 27
        assert all(particle.phase == "fluid" for particle in world.particles)
        assert min(particle.position[1] - particle.radius for particle in world.particles) >= -1.0e-6


def test_sparse_fire_plasma_and_cache_contracts_are_deterministic() -> None:
    fire = create_sparse_fire_volume()
    plasma = create_sparse_fire_volume(plasma=True)
    fire.step(1.0 / 24.0)
    plasma.step(1.0 / 24.0)
    cache = SimulationCache(frame_rate=24.0, metadata={"preset": "fire"})
    cache.store(fire.capture_frame(1))
    payload = cache.to_dict()

    assert len(fire.volumes["fire"].cells) == 25
    assert len(plasma.volumes["plasma"].cells) == 25
    assert payload["schema"] == "tech_connector.sim_cache.v1"
    assert payload["frames"]["1"]["volume_cells"]["fire"]


def test_quad_geometry_emitter_collision_gravity_attachment_and_burning() -> None:
    world = create_particle_block((1, 1, 1), material="water")
    world.particles.clear()
    quad = [(-0.5, 1.0, -0.5), (0.5, 1.0, -0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5)]
    world.emitters.append(GeometryEmitter(quad, [(0, 1, 2, 3)], rate=24.0, material="water", seed=9))
    world.mesh_colliders.append(TriangleMeshCollider(
        [(-2, 0, -2), (2, 0, -2), (2, 0, 2), (-2, 0, 2)],
        [(0, 1, 2, 3)],
    ))
    world.fields = [ForceField("gravity_source", vector=(0.05, 0, 0), center=(0, -3, 0), strength=9.81)]
    world.step(1.0 / 24.0)

    assert len(world.particles) == 1
    assert world.emitters[0].faces == [(0, 1, 2, 3)]
    assert world.mesh_colliders[0].faces == [(0, 1, 2, 3)]
    assert world.particles[0].velocity[1] < 0.0

    cloth = create_cloth_grid(3, 3, spacing=0.1)
    attachments = attach_particles(cloth, [0, 2])
    cloth.fields.append(ForceField("heat", center=cloth.particles[4].position, radius=1.0, strength=1000.0))
    for _ in range(30):
        cloth.step(1.0 / 60.0)
    assert attachments == [0, 1]
    assert cloth.particles[4].burn_damage > 0.0


def test_geometry_emitter_uses_painted_source_density_and_transfers_the_map() -> None:
    vertices = [(0.0, 1.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 1.0)]
    emitter = GeometryEmitter(vertices, [(0, 1, 2)], rate=240.0, seed=17)
    emitter.set_source_weights([1.0, 0.0, 0.0], revision=4)
    world = SimulationWorld(fields=[], emitters=[emitter], substeps=1, constraint_iterations=1)

    world.step(1.0)

    assert len(world.particles) == 80
    assert all(particle.position[1] == pytest.approx(1.0) for particle in world.particles)
    average_distance = sum(particle.position[0] + particle.position[2] for particle in world.particles) / len(world.particles)
    assert average_distance < 0.55
    cache = SimulationCache(frame_rate=24.0)
    cache.store(world.capture_frame(1))
    manifest = build_simulation_transfer_manifest(world, cache, "unreal").to_dict()
    source = manifest["metadata"]["geometry_emitter_sources"][0]
    assert source["source_weights"] == [1.0, 0.0, 0.0]
    assert source["revision"] == 4


def test_zero_painted_geometry_emitter_does_not_emit() -> None:
    emitter = GeometryEmitter(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
        [(0, 1, 2)],
        rate=1000.0,
    )
    emitter.set_source_weights([0.0, 0.0, 0.0])
    world = SimulationWorld(fields=[], emitters=[emitter])

    world.step(1.0)

    assert not world.particles


def test_transfer_manifest_prefers_live_target_features_and_keeps_baked_fallbacks() -> None:
    world = create_cloth_grid(3, 3)
    cache = SimulationCache(frame_rate=24.0)
    cache.store(world.capture_frame(1))
    unreal = build_simulation_transfer_manifest(world, cache, "unreal").to_dict()
    generic = build_simulation_transfer_manifest(world, cache, "generic").to_dict()

    assert any(item["destination_feature"] == "Chaos Cloth" and item["live"] for item in unreal["artifacts"])
    assert any(item["format"] == "alembic" for item in unreal["artifacts"])
    assert not any(item["live"] and item["format"] == "tcfx.intent" for item in generic["artifacts"])
    assert "quad collision/emitter source topology remains preserved" in unreal["validation"]


def test_quad_geometry_converts_to_pinned_tearable_cloth_without_losing_faces() -> None:
    world = create_cloth_from_geometry(
        [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)],
        [(0, 1, 2, 3)],
        material="silk",
        pinned_vertices=[0, 1],
        tear_threshold=1.5,
    )

    assert world.surface_faces == [(0, 1, 2, 3)]
    assert [index for index, particle in enumerate(world.particles) if particle.pinned] == [0, 1]
    assert len([item for item in world.constraints if item.constraint_type == "stretch"]) == 4
    assert len([item for item in world.constraints if item.constraint_type == "shear"]) == 2
    assert all(item.break_threshold == 1.5 for item in world.constraints)
    assert len(world.area_constraints) == 2
    assert all(item.material_axis == "isotropic" for item in world.constraints)


def _closed_quad_cube():
    vertices = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
    ]
    faces = [
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3),
        (1, 2, 6, 5), (0, 1, 5, 4), (3, 7, 6, 2),
    ]
    return vertices, faces


def test_jello_preserves_closed_mesh_volume_and_soup_fills_its_interior() -> None:
    vertices, faces = _closed_quad_cube()
    jello = create_soft_body_from_geometry(vertices, faces)
    rest_volume = abs(jello.volume_constraints[0].rest_volume)
    jello.fields = []
    jello.particles[6].position = (1.35, 1.2, 1.1)
    for _ in range(20):
        jello.step(1.0 / 60.0)
    current_volume = abs(signed_mesh_volume([particle.position for particle in jello.particles], jello.surface_faces))

    soup = create_fluid_from_geometry(vertices, faces, spacing=0.5, max_particles=1000)
    assert abs(current_volume / rest_volume - 1.0) < 0.03
    assert len(soup.particles) == 64
    assert all(particle.material == "soup" and particle.phase == "fluid" for particle in soup.particles)


def test_curve_flow_fractures_glass_and_heat_melts_metal_without_losing_mass_constraint() -> None:
    fluid = create_particle_block((1, 1, 1), material="soup")
    fluid.fields = []
    fluid.particles[0].position = (0.0, 0.3, 0.0)
    fluid.curve_fields.append(CurveFlowField([(-1, 0, 0), (1, 0, 0)], flow_strength=10.0, attraction_strength=20.0))
    fluid.step(0.1)
    assert fluid.particles[0].velocity[0] > 0.0
    assert fluid.particles[0].position[1] < 0.3

    vertices, faces = _closed_quad_cube()
    glass = create_breakable_solid_from_geometry(vertices, faces, material="glass")
    glass.fields = []
    assert glass.surface_faces == [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (12, 13, 14, 15), (16, 17, 18, 19), (20, 21, 22, 23)]
    assert any(constraint.constraint_type == "fracture_bond" for constraint in glass.constraints)
    glass.particles[0].position = (-3.0, -1.0, -1.0)
    glass.step(1.0 / 24.0)
    assert any(
        not constraint.enabled and constraint.constraint_type == "fracture_bond"
        for constraint in glass.constraints
    )
    assert not glass.volume_constraints

    metal = create_breakable_solid_from_geometry(vertices, faces, material="metal")
    metal.fields = [ForceField("heat", strength=2200.0, radius=0.0)]
    metal.step(1.0)
    assert all(particle.state == "molten" and particle.phase == "fluid" for particle in metal.particles)
    assert metal.volume_constraints and metal.volume_constraints[0].compliance > 0.0
    cache = SimulationCache(frame_rate=24.0)
    cache.store(metal.capture_frame(1))
    manifest = build_simulation_transfer_manifest(metal, cache, "unreal").to_dict()
    assert "rigid" in manifest["simulation_types"]
    assert any(artifact["format"] == "alembic" for artifact in manifest["artifacts"])
    assert manifest["metadata"]["material_states"] == ["molten"]


def test_playdoh_is_volumetric_plastic_tearable_and_reformable() -> None:
    vertices, faces = _closed_quad_cube()
    dough = create_reformable_dough_from_geometry(vertices, faces, spacing=0.5, max_particles=1000)
    assert len(dough.particles) == 64
    assert dough.constraints
    assert all(particle.phase == "reformable" and particle.state == "plastic" for particle in dough.particles)
    assert all(constraint.reformable for constraint in dough.constraints)

    world = SimulationWorld(fields=[], substeps=1, constraint_iterations=1, self_collision=False)
    world.particles = [
        SimulationParticle((0.0, 0.0, 0.0), radius=0.05, material="playdoh", phase="reformable", state="plastic"),
        SimulationParticle((1.0, 0.0, 0.0), radius=0.05, material="playdoh", phase="reformable", state="plastic"),
    ]
    world.reformable_settings["playdoh"] = {
        "bond_distance": 1.1, "heal_distance": 0.3, "max_neighbors": 4,
        "max_heal_speed": 2.0, "break_threshold": 1.5,
        "plastic_yield": 0.05, "plastic_creep": 5.0, "compliance": 0.0,
    }
    world._update_reformable_bonds()
    bond = world.constraints[0]
    world.particles[1].position = (1.2, 0.0, 0.0)
    world.step(0.1)
    assert bond.rest_length > 1.0

    world.particles[1].position = (2.0, 0.0, 0.0)
    world.particles[0].velocity = world.particles[1].velocity = (0.0, 0.0, 0.0)
    world.step(0.01)
    assert not bond.enabled
    world.particles[1].position = (0.2, 0.0, 0.0)
    world.particles[0].velocity = world.particles[1].velocity = (0.0, 0.0, 0.0)
    contact_distance = abs(world.particles[1].position[0] - world.particles[0].position[0])
    world.step(0.01)
    assert bond.enabled
    assert bond.rest_length == pytest.approx(contact_distance)
