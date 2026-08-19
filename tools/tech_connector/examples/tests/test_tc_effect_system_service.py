import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtWidgets import QApplication

from tech_connector.services.dcc.tc_deformable_surface_service import DeformableSurface, SURFACE_MATERIALS
from tech_connector.services.dcc.tc_effect_system_service import (
    QUALITY_PROFILES,
    add_effect_jiggle,
    bake_effect_system,
    configure_electric_arc,
    create_effect_preset,
    create_effect_world,
    effect_preset_names,
    set_effect_parameter,
    set_emitter_renderer,
)
from tech_connector.services.dcc.tc_simulation_service import SimulationParticle, SimulationWorld, TriangleMeshCollider
from tech_connector.ui.three_d_gpu_viewport import ThreeDGpuViewport


def test_all_effect_presets_spawn_deterministically_and_honor_quality() -> None:
    names = effect_preset_names()
    assert {"hurricane", "volcano", "mudslide", "avalanche", "earthquake", "electrical_storm"} <= set(names)
    for name in names:
        first = create_effect_world(name, quality="low", seed=19)
        second = create_effect_world(name, quality="low", seed=19)
        first.step(1.0 / 24.0)
        second.step(1.0 / 24.0)
        assert [particle.position for particle in first.particles] == [particle.position for particle in second.particles]
        assert first.effect_system.renderer_metadata

    low = create_effect_world("explosion", quality="low")
    high = create_effect_world("explosion", quality="high")
    low.step(1.0 / 24.0)
    high.step(1.0 / 24.0)
    assert len(low.particles) < len(high.particles)
    assert QUALITY_PROFILES["cinematic"].max_particles > QUALITY_PROFILES["high"].max_particles


def test_effect_parameters_events_renderers_electric_arcs_and_bakes_are_editable() -> None:
    system = create_effect_preset("chain_lightning")
    arc = configure_electric_arc(system, (0, 2, 0), (3, 0, 1), branch_count=9, conductivity=0.75)
    assert arc["target"] == (3, 0, 1)
    assert arc["branch_count"] == 9
    assert set_effect_parameter(system, "emitter.main_arc.spawn_rate", 44.0) == 44.0
    renderer = set_emitter_renderer(system, "main_arc", "mesh", asset_id="TC_Current_Mesh")
    assert renderer["asset_id"] == "TC_Current_Mesh"

    fireworks = create_effect_world("fireworks", seed=3)
    for _ in range(15):
        fireworks.step(0.1)
    assert any(event["type"] == "death" for event in fireworks.effect_system.emitted_events) or any(
        particle.emitter_id == "stars" for particle in fireworks.particles
    )
    assert any(particle.emitter_id == "stars" for particle in fireworks.particles)

    live = create_effect_world("sparks", seed=5)
    original_time = live.time_seconds
    cache = bake_effect_system(live, start_frame=1, end_frame=5, frame_rate=24.0)
    assert len(cache.frames) == 5
    assert live.time_seconds == original_time


def test_effect_emitters_support_weighted_jiggle_secondary_motion() -> None:
    world = create_effect_world("sparks", quality="low", seed=8)
    jiggle = add_effect_jiggle(
        world.effect_system,
        "sparks",
        stiffness=45.0,
        damping=6.0,
        influence=0.75,
        max_offset=0.5,
    )

    world.step(1.0 / 24.0)

    assert jiggle.module_type == "jiggle"
    assert world.particles
    assert all("jiggle_anchor" in particle.effect_attributes for particle in world.particles)


def test_reactive_surfaces_support_prints_penetration_recovery_and_conductivity() -> None:
    snow = DeformableSurface("snow", columns=20, rows=20, cell_size=0.1, origin=(-1, 0, -1))
    mark = snow.apply_footprint((0, 0, 0), size=(0.35, 0.14), depth=0.08, tread=(1, .4, 1, .4, 1))
    minimum = min(snow.heights)
    snow.step(1.0)
    assert mark.kind == "footprint"
    assert minimum < 0.0
    assert min(snow.heights) > minimum

    metal = DeformableSurface("metal", columns=10, rows=10, cell_size=0.1, origin=(-.5, 0, -.5))
    stopped = metal.apply_projectile((0, 0, 0), (0, -1, 0), energy=0.1, thickness=0.2)
    passed = metal.apply_projectile((0, 0, 0), (0, -1, 0), energy=30.0, thickness=0.1)
    assert not stopped.penetrated and passed.penetrated
    assert SURFACE_MATERIALS["metal"].conductivity > SURFACE_MATERIALS["wood"].conductivity


def test_moving_mesh_collider_transfers_tangential_motion() -> None:
    world = SimulationWorld(fields=[], substeps=1, constraint_iterations=1, self_collision=False)
    world.particles.append(SimulationParticle((0, 0.02, 0), radius=0.05, material="water"))
    world.mesh_colliders.append(TriangleMeshCollider(
        [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)], [(0, 1, 2, 3)],
        friction=1.0, live=True, velocity=(2.0, 0.0, 0.0),
    ))
    world.step(0.1)
    assert world.particles[0].position[0] > 0.1
    assert world.particles[0].velocity[0] > 1.0


def test_gpu_viewport_streams_live_effect_geometry() -> None:
    app = QApplication.instance() or QApplication([])
    viewport = ThreeDGpuViewport()
    try:
        app.processEvents()
        assert viewport.ready, viewport.last_error
        world = create_effect_world("explosion", quality="low")
        world.step(1.0 / 24.0)
        assert viewport.update_effects(world)
        alive_count = len([particle for particle in world.particles if particle.alive])
        routed_count = viewport.effect_geometry.particle_count + viewport.effect_alpha_geometry.particle_count
        assert viewport.effect_geometry.particle_count > 0
        assert viewport.effect_alpha_geometry.particle_count > 0
        assert routed_count == alive_count

        refractive = create_effect_world("refractive_bubbles", quality="low")
        refractive.step(0.25)
        assert viewport.update_effects(refractive)
        assert viewport.effect_refractive_geometry.particle_count > 0
        assert viewport.rootObject().property("effectTransmission") == 0.96
        assert viewport.rootObject().property("effectIor") == 1.33

        mesh_world = create_effect_world("sparks", quality="low")
        set_emitter_renderer(
            mesh_world.effect_system,
            "sparks",
            "mesh",
            renderer_parameters={
                "source_vertices": ((-0.5, 0, -0.5), (0.5, 0, -0.5), (0, 0, 0.5), (0, 1, 0)),
                "source_faces": ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)),
            },
        )
        mesh_world.step(1.0 / 24.0)
        assert viewport.update_effects(mesh_world)
        assert viewport.effect_mesh_geometry.instance_count > 0
        assert viewport.effect_mesh_instancing.instance_count == viewport.effect_mesh_geometry.instance_count
        assert len(viewport.effect_mesh_instancing.getInstanceBuffer()[0]) == viewport.effect_mesh_instancing.instance_count * 80
        assert viewport.effect_stats["mesh_instances"] > 0
        assert viewport.effect_stats["draw_calls"] == 1
        assert viewport.effect_stats["mesh_instance_bytes"] == viewport.effect_stats["mesh_instances"] * 80

        viewport.set_material(
            color=viewport.rootObject().property("materialColor"),
            opacity=0.7,
            transmission=0.88,
            ior=1.45,
            thickness=0.25,
            clearcoat=0.6,
            attenuation_color="#88ccff",
            attenuation_distance=3.5,
        )
        assert viewport.rootObject().property("materialTransmission") == 0.88
        assert viewport.rootObject().property("materialIor") == 1.45

        budget = viewport.configure_effect_budget(
            target_upload_ms=3.0,
            particle_budget=5,
            mesh_instance_budget=7,
            adaptive=False,
        )
        assert budget == {
            "target_upload_ms": 3.0,
            "particle_budget_per_stream": 100,
            "mesh_instance_budget": 100,
            "adaptive": False,
        }
    finally:
        viewport.close()
        app.processEvents()
