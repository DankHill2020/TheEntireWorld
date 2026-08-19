from tech_connector.game_engine.runtime.tc_simulation_service import (
    SimulationParticle,
    SimulationWorld,
    SphereCollider,
)


def test_simulation_records_bounded_particle_and_collider_contacts() -> None:
    world = SimulationWorld(
        particles=[
            SimulationParticle((-0.02, 0.0, 0.0), radius=0.05),
            SimulationParticle((0.02, 0.0, 0.0), radius=0.05),
            SimulationParticle((0.0, 0.0, 0.0), radius=0.03),
        ],
        sphere_colliders=[SphereCollider((0.0, 0.0, 0.0), 0.1)],
        fields=[],
        substeps=1,
        constraint_iterations=1,
    )

    world.step(1.0 / 60.0)

    assert world.debug_contacts
    assert {contact["kind"] for contact in world.debug_contacts} & {"particle", "sphere"}
    assert all(contact["penetration"] >= 0.0 for contact in world.debug_contacts)
    assert len(world.debug_contacts) <= 4096
