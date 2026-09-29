"""Scale-aware space, plasma, molecular, and cinematic-physics authoring presets."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any

from tech_connector.game_engine.runtime.tc_simulation_service import (
    DistanceConstraint,
    ForceField,
    ParticleInteractionSettings,
    SimulationMaterial,
    SimulationParticle,
    SimulationScaleSettings,
    SimulationWorld,
)
from tech_connector.game_engine.runtime.tc_plasma_pic_service import ElectrostaticPicGrid
from tech_connector.game_engine.runtime.tc_magnetic_grid_service import MagnetodynamicGrid


@dataclass(frozen=True)
class ExoticSimulationPreset:
    preset_id: str
    name: str
    family: str
    accuracy: str
    summary: str
    live_controls: tuple[str, ...]


EXOTIC_SIMULATION_PRESETS: dict[str, ExoticSimulationPreset] = {
    item.preset_id: item for item in (
        ExoticSimulationPreset("binary_star", "Binary Star", "space", "grounded", "Barycentric two-body orbit.", ("separation", "mass_ratio", "eccentricity", "time_scale")),
        ExoticSimulationPreset("asteroid_ring", "Asteroid Ring", "space", "approximation", "Central gravity with a seeded orbiting debris ring.", ("particle_count", "inner_radius", "outer_radius", "velocity_jitter")),
        ExoticSimulationPreset("accretion_disk", "Accretion Disk", "space", "approximation", "Orbiting gas and dust with controllable inward drift.", ("particle_count", "disk_radius", "inward_drift", "temperature")),
        ExoticSimulationPreset("roche_breakup", "Roche Breakup", "space", "approximation", "Breakable satellite body under a steep tidal gradient.", ("orbital_radius", "cohesion", "break_threshold", "time_scale")),
        ExoticSimulationPreset("stellar_merger", "Stellar Merger", "space", "cinematic", "Momentum- and charge-conserving body merger.", ("mass_ratio", "impact_speed", "merge_distance", "time_scale")),
        ExoticSimulationPreset("magnetosphere", "Magnetosphere", "plasma", "approximation", "Charged solar-wind particles crossing a magnetic field.", ("magnetic_strength", "wind_speed", "charge", "particle_count")),
        ExoticSimulationPreset("pic_double_layer", "PIC Double Layer", "plasma", "approximation", "Self-consistent positive and negative charge clouds.", ("grid_resolution", "field_strength", "charge", "iterations")),
        ExoticSimulationPreset("aurora_curtain", "Aurora Curtain", "space_weather", "cinematic", "Charged solar wind guided into a magnetic curtain.", ("solar_wind", "magnetic_strength", "field_strength", "particle_count")),
        ExoticSimulationPreset("plasma_jet", "Plasma Jet", "plasma", "cinematic", "Magnetically collimated charged-particle jet.", ("jet_speed", "collimation", "field_strength", "particle_count")),
        ExoticSimulationPreset("molecular_gas", "Molecular Gas", "molecular", "approximation", "Short-range Lennard-Jones molecular motion.", ("temperature", "epsilon", "sigma", "cutoff")),
        ExoticSimulationPreset("ferrofluid_lab", "Ferrofluid Lab", "exotic_matter", "cinematic", "Magnetically steered cohesive particles.", ("field_strength", "cohesion", "viscosity", "surface_tension")),
    )
}


def exotic_simulation_preset_names() -> list[str]:
    return list(EXOTIC_SIMULATION_PRESETS)


def create_exotic_simulation(preset: str, *, seed: int = 1, particle_count: int | None = None) -> SimulationWorld:
    preset_id = str(preset or "").strip().lower()
    if preset_id == "binary_star":
        return _binary_star()
    if preset_id == "asteroid_ring":
        return _asteroid_ring(seed=seed, particle_count=particle_count or 512)
    if preset_id == "accretion_disk":
        return _accretion_disk(seed=seed, particle_count=particle_count or 1500)
    if preset_id == "roche_breakup":
        return _roche_breakup()
    if preset_id == "stellar_merger":
        return _stellar_merger()
    if preset_id == "magnetosphere":
        return _magnetosphere(seed=seed, particle_count=particle_count or 384)
    if preset_id == "pic_double_layer":
        return _pic_double_layer(seed=seed, particle_count=particle_count or 96)
    if preset_id == "aurora_curtain":
        return _aurora_curtain(seed=seed, particle_count=particle_count or 160)
    if preset_id == "plasma_jet":
        return _plasma_jet(seed=seed, particle_count=particle_count or 192)
    if preset_id == "molecular_gas":
        return _molecular_gas(seed=seed, particle_count=particle_count or 125)
    if preset_id == "ferrofluid_lab":
        return _ferrofluid(seed=seed, particle_count=particle_count or 256)
    raise KeyError(f"Unknown exotic simulation preset: {preset}")


def simulation_diagnostics(world: SimulationWorld) -> dict[str, Any]:
    """Return conserved-quantity overlays shared by viewport and bake validation."""
    momentum = [0.0, 0.0, 0.0]
    angular = [0.0, 0.0, 0.0]
    kinetic = total_mass = total_charge = 0.0
    center = [0.0, 0.0, 0.0]
    alive = [particle for particle in world.particles if particle.alive and math.isfinite(particle.inertial_mass)]
    for particle in alive:
        mass = particle.inertial_mass
        total_mass += mass
        total_charge += particle.charge
        speed_sq = sum(value * value for value in particle.velocity)
        kinetic += 0.5 * mass * speed_sq
        for axis in range(3):
            momentum[axis] += mass * particle.velocity[axis]
            center[axis] += mass * particle.position[axis]
        px, py, pz = (mass * value for value in particle.velocity)
        x, y, z = particle.position
        angular[0] += y * pz - z * py
        angular[1] += z * px - x * pz
        angular[2] += x * py - y * px
    if total_mass > 0.0:
        center = [value / total_mass for value in center]
    return {
        "schema": "tech_connector.simulation_diagnostics.v1",
        "accuracy_mode": world.scale.accuracy_mode,
        "particle_count": len(alive),
        "total_mass": total_mass,
        "total_charge": total_charge,
        "center_of_mass": tuple(center),
        "linear_momentum": tuple(momentum),
        "angular_momentum": tuple(angular),
        "kinetic_energy": kinetic,
        "time_seconds": world.time_seconds * world.scale.time_unit_seconds,
        "interaction_solver": dict(getattr(world, "_interaction_diagnostics", {}) or {}),
        "pic_grids": [dict(grid.diagnostics) for grid in world.pic_grids],
        "magnetic_grids": [dict(grid.diagnostics) for grid in world.magnetic_grids],
    }


def exotic_authoring_schema() -> dict[str, Any]:
    """UI-neutral clean inspector contract for viewport and host-specific panels."""
    return {
        "schema": "tech_connector.exotic_authoring.v1",
        "accuracy_modes": ["grounded", "approximation", "cinematic"],
        "presets": [preset.__dict__ for preset in EXOTIC_SIMULATION_PRESETS.values()],
        "viewport_tools": ["activate", "drag_source", "orbit_preview", "field_lines", "trails", "vector_glyphs", "time_scrub"],
        "diagnostics": ["center_of_mass", "linear_momentum", "angular_momentum", "kinetic_energy", "total_charge", "timestep_stability"],
        "performance": ["adaptive_substeps", "interaction_cutoff", "long_range_method", "opening_angle", "maximum_acceleration", "particle_budget", "backend_status"],
    }


def _binary_star() -> SimulationWorld:
    first_mass, second_mass, separation, gravity = 1.0, 0.65, 8.0, 1.0
    total = first_mass + second_mass
    first_radius = separation * second_mass / total
    second_radius = separation * first_mass / total
    angular_speed = math.sqrt(gravity * total / separation ** 3)
    particles = [
        SimulationParticle((-first_radius, 0.0, 0.0), velocity=(0.0, 0.0, -angular_speed * first_radius), inverse_mass=1.0 / first_mass, mass=first_mass, radius=0.35, species="star"),
        SimulationParticle((second_radius, 0.0, 0.0), velocity=(0.0, 0.0, angular_speed * second_radius), inverse_mass=1.0 / second_mass, mass=second_mass, radius=0.28, species="star"),
    ]
    world = SimulationWorld(
        particles=particles, fields=[], self_collision=False, substeps=4, constraint_iterations=1,
        scale=SimulationScaleSettings(distance_unit_meters=1.496e11, time_unit_seconds=5.0226e6, mass_unit_kilograms=1.98847e30, accuracy_mode="grounded", adaptive_substeps=True),
        interactions=ParticleInteractionSettings(gravity_constant=gravity, softening=0.01, maximum_acceleration=25.0),
    )
    return _assign_material(world, "vacuum")


def _asteroid_ring(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    central_mass, gravity = 5000.0, 1.0
    particles = [SimulationParticle((0.0, 0.0, 0.0), inverse_mass=0.0, mass=central_mass, radius=0.7, species="primary")]
    for _ in range(max(1, particle_count)):
        radius = rng.uniform(4.0, 12.0)
        angle = rng.random() * math.tau
        height = rng.uniform(-0.12, 0.12)
        speed = math.sqrt(gravity * central_mass / radius) * rng.uniform(0.97, 1.03)
        particles.append(SimulationParticle(
            (math.cos(angle) * radius, height, math.sin(angle) * radius),
            velocity=(-math.sin(angle) * speed, 0.0, math.cos(angle) * speed),
            inverse_mass=1.0, mass=1.0, radius=0.025, species="asteroid",
        ))
    world = SimulationWorld(
        particles=particles, fields=[], self_collision=False, substeps=2, constraint_iterations=1,
        scale=SimulationScaleSettings(distance_unit_meters=1.0e7, time_unit_seconds=3600.0, mass_unit_kilograms=1.0e18, accuracy_mode="approximation", adaptive_substeps=False),
        interactions=ParticleInteractionSettings(
            gravity_constant=gravity, gravity_source_mass_threshold=10.0,
            softening=0.08, maximum_acceleration=2000.0,
        ),
    )
    return _assign_material(world, "vacuum")


def _magnetosphere(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    particles = [SimulationParticle(
        (-8.0 + rng.uniform(-1.0, 1.0), rng.uniform(-4.0, 4.0), rng.uniform(-4.0, 4.0)),
        velocity=(5.0 + rng.uniform(-0.2, 0.2), 0.0, 0.0), mass=1.0, charge=-1.0,
        radius=0.025, species="electron",
    ) for _ in range(max(1, particle_count))]
    world = SimulationWorld(
        particles=particles, fields=[],
        magnetic_grids=[MagnetodynamicGrid(
            bounds_min=(-10.0, -6.0, -6.0), bounds_max=(6.0, 6.0, 6.0),
            resolution=(14, 12, 12), uniform_field=(0.0, 0.7, 0.0),
            induction_strength=0.35, resistivity=0.025, divergence_clean_iterations=14,
        )],
        self_collision=False, substeps=4, constraint_iterations=1,
        scale=SimulationScaleSettings(distance_unit_meters=1.0e6, time_unit_seconds=1.0, mass_unit_kilograms=1.6726e-27, charge_unit_coulombs=1.602e-19, accuracy_mode="approximation", adaptive_substeps=True),
    )
    return _assign_material(world, "vacuum")


def _accretion_disk(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    central_mass, gravity = 8000.0, 1.0
    particles = [SimulationParticle(
        (0.0, 0.0, 0.0), inverse_mass=0.0, mass=central_mass, radius=0.8,
        species="compact_primary", temperature=4000.0,
    )]
    for index in range(max(1, particle_count)):
        radius = 1.8 + (rng.random() ** 0.65) * 10.0
        angle = rng.random() * math.tau
        height = rng.gauss(0.0, 0.04 + radius * 0.012)
        radial = (math.cos(angle), 0.0, math.sin(angle))
        tangent = (-math.sin(angle), 0.0, math.cos(angle))
        orbital_speed = math.sqrt(gravity * central_mass / radius)
        inward_speed = orbital_speed * rng.uniform(0.002, 0.018)
        particles.append(SimulationParticle(
            (radial[0] * radius, height, radial[2] * radius),
            velocity=(
                tangent[0] * orbital_speed - radial[0] * inward_speed,
                rng.gauss(0.0, 0.015),
                tangent[2] * orbital_speed - radial[2] * inward_speed,
            ),
            mass=0.02, inverse_mass=50.0, radius=0.018,
            species="ionized_gas" if index % 4 else "dust",
            temperature=1200.0 + 3000.0 / max(1.0, radius),
        ))
    world = SimulationWorld(
        particles=particles, fields=[], self_collision=False, substeps=2, constraint_iterations=1,
        scale=SimulationScaleSettings(
            distance_unit_meters=1.0e8, time_unit_seconds=500.0, mass_unit_kilograms=1.0e24,
            accuracy_mode="approximation", adaptive_substeps=False,
        ),
        interactions=ParticleInteractionSettings(
            gravity_constant=gravity, gravity_source_mass_threshold=100.0,
            softening=0.06, maximum_acceleration=5000.0,
        ),
    )
    return _assign_material(world, "vacuum")


def _pic_double_layer(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    particles = []
    for index in range(max(2, particle_count)):
        charge = 1.0 if index % 2 == 0 else -1.0
        center_x = -1.1 if charge > 0.0 else 1.1
        particles.append(SimulationParticle(
            (rng.gauss(center_x, 0.35), rng.gauss(0.0, 0.65), rng.gauss(0.0, 0.65)),
            velocity=(rng.gauss(0.0, 0.04), rng.gauss(0.0, 0.04), rng.gauss(0.0, 0.04)),
            mass=1.0, charge=charge, radius=0.035,
            species="ion" if charge > 0.0 else "electron",
        ))
    world = SimulationWorld(
        particles=particles, fields=[], self_collision=False, substeps=1, constraint_iterations=1,
        pic_grids=[ElectrostaticPicGrid(
            bounds_min=(-4.0, -3.0, -3.0), bounds_max=(4.0, 3.0, 3.0),
            resolution=(14, 12, 12), potential_iterations=28, field_strength=0.7,
        )],
        scale=SimulationScaleSettings(
            distance_unit_meters=1.0e-3, time_unit_seconds=1.0e-6,
            mass_unit_kilograms=1.6726e-27, charge_unit_coulombs=1.602e-19,
            accuracy_mode="approximation", adaptive_substeps=False,
        ),
    )
    return _assign_material(world, "vacuum")


def _aurora_curtain(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    particles = [SimulationParticle(
        (rng.uniform(-3.0, 3.0), rng.uniform(2.5, 4.5), rng.gauss(0.0, 0.3)),
        velocity=(rng.gauss(0.0, 0.1), rng.uniform(-2.6, -1.8), rng.gauss(0.0, 0.08)),
        mass=1.0, charge=-1.0, radius=0.025, species="solar_electron",
        color=(0.25, 1.0, 0.55, 0.8),
    ) for _ in range(max(2, particle_count))]
    world = SimulationWorld(
        particles=particles,
        fields=[
            ForceField("attractor", center=(0.0, -3.5, 0.0), strength=0.8, radius=9.0),
        ],
        self_collision=False, substeps=2, constraint_iterations=1,
        pic_grids=[ElectrostaticPicGrid(
            bounds_min=(-5.0, -5.0, -3.0), bounds_max=(5.0, 5.0, 3.0),
            resolution=(14, 16, 10), potential_iterations=20, field_strength=0.08,
        )],
        magnetic_grids=[MagnetodynamicGrid(
            bounds_min=(-5.0, -5.0, -3.0), bounds_max=(5.0, 5.0, 3.0),
            resolution=(12, 14, 10), uniform_field=(0.0, 0.55, 0.1),
            induction_strength=0.45, resistivity=0.035, divergence_clean_iterations=12,
        )],
        scale=SimulationScaleSettings(accuracy_mode="cinematic", adaptive_substeps=False),
    )
    return _assign_material(world, "vacuum")


def _plasma_jet(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    particles = [SimulationParticle(
        (rng.gauss(0.0, 0.18), rng.gauss(0.0, 0.18), rng.uniform(-1.0, 1.0)),
        velocity=(rng.gauss(0.0, 0.05), rng.gauss(0.0, 0.05), rng.uniform(3.0, 4.5)),
        mass=1.0, charge=1.0 if index % 2 == 0 else -1.0,
        radius=0.025, species="jet_ion" if index % 2 == 0 else "jet_electron",
        color=(0.25, 0.8, 1.0, 0.85),
    ) for index in range(max(2, particle_count))]
    world = SimulationWorld(
        particles=particles,
        fields=[
            ForceField("attractor", center=(0.0, 0.0, 5.0), strength=0.35, radius=8.0),
        ],
        self_collision=False, substeps=2, constraint_iterations=1,
        pic_grids=[ElectrostaticPicGrid(
            bounds_min=(-3.0, -3.0, -2.0), bounds_max=(3.0, 3.0, 8.0),
            resolution=(12, 12, 18), potential_iterations=20, field_strength=0.15,
        )],
        magnetic_grids=[MagnetodynamicGrid(
            bounds_min=(-3.0, -3.0, -2.0), bounds_max=(3.0, 3.0, 8.0),
            resolution=(10, 10, 16), uniform_field=(0.0, 0.0, 1.4),
            induction_strength=0.65, resistivity=0.02, divergence_clean_iterations=12,
        )],
        scale=SimulationScaleSettings(accuracy_mode="cinematic", adaptive_substeps=False),
    )
    return _assign_material(world, "vacuum")


def _roche_breakup() -> SimulationWorld:
    primary_mass, satellite_mass, gravity = 5000.0, 0.25, 1.0
    orbital_radius, spacing, side = 1.6, 0.18, 4
    orbital_speed = math.sqrt(gravity * primary_mass / orbital_radius)
    particles = [SimulationParticle(
        (0.0, 0.0, 0.0), inverse_mass=0.0, mass=primary_mass, radius=0.65, species="primary",
    )]
    index_by_cell: dict[tuple[int, int, int], int] = {}
    for x in range(side):
        for y in range(side):
            for z in range(side):
                index = len(particles)
                index_by_cell[(x, y, z)] = index
                particles.append(SimulationParticle(
                    (orbital_radius + (x - 1.5) * spacing, (y - 1.5) * spacing, (z - 1.5) * spacing),
                    velocity=(0.0, 0.0, orbital_speed), mass=satellite_mass,
                    inverse_mass=1.0 / satellite_mass, radius=spacing * 0.42, species="tidal_fragment",
                ))
    constraints: list[DistanceConstraint] = []
    for cell, first in index_by_cell.items():
        for axis in range(3):
            neighbor = list(cell)
            neighbor[axis] += 1
            second = index_by_cell.get(tuple(neighbor))
            if second is not None:
                constraints.append(DistanceConstraint(
                    first, second, spacing, compliance=2.0e-6,
                    constraint_type="tidal_cohesion", break_threshold=1.003,
                ))
    world = SimulationWorld(
        particles=particles, constraints=constraints, fields=[], self_collision=False,
        substeps=8, constraint_iterations=8,
        scale=SimulationScaleSettings(
            distance_unit_meters=1.0e6, time_unit_seconds=20.0, mass_unit_kilograms=1.0e19,
            accuracy_mode="approximation", adaptive_substeps=False,
        ),
        interactions=ParticleInteractionSettings(
            gravity_constant=gravity, gravity_source_mass_threshold=100.0,
            softening=0.03, maximum_acceleration=10000.0,
        ),
    )
    return _assign_material(world, "vacuum")


def _stellar_merger() -> SimulationWorld:
    world = SimulationWorld(
        particles=[
            SimulationParticle((-0.45, 0.0, 0.0), velocity=(0.8, 0.0, 0.0), mass=2.0, inverse_mass=0.5, radius=0.6, species="star"),
            SimulationParticle((0.45, 0.0, 0.0), velocity=(-0.8, 0.0, 0.0), mass=1.0, inverse_mass=1.0, radius=0.5, species="star"),
        ],
        fields=[], self_collision=False, substeps=4, constraint_iterations=1,
        scale=SimulationScaleSettings(
            distance_unit_meters=6.957e8, time_unit_seconds=3600.0, mass_unit_kilograms=1.98847e30,
            accuracy_mode="cinematic", adaptive_substeps=True,
        ),
        interactions=ParticleInteractionSettings(
            gravity_constant=0.25, softening=0.02, maximum_acceleration=100.0,
            collision_mode="merge", merge_distance_scale=1.0, merge_speed_limit=5.0,
        ),
    )
    return _assign_material(world, "vacuum")


def _molecular_gas(*, seed: int, particle_count: int) -> SimulationWorld:
    rng = random.Random(seed)
    side = max(1, math.ceil(particle_count ** (1.0 / 3.0)))
    particles: list[SimulationParticle] = []
    for index in range(particle_count):
        x, remainder = divmod(index, side * side)
        y, z = divmod(remainder, side)
        particles.append(SimulationParticle(
            ((x - side / 2) * 0.28, (y - side / 2) * 0.28, (z - side / 2) * 0.28),
            velocity=(rng.gauss(0.0, 0.08), rng.gauss(0.0, 0.08), rng.gauss(0.0, 0.08)),
            mass=1.0, radius=0.04, species="molecule",
        ))
    world = SimulationWorld(
        particles=particles, fields=[], self_collision=False, substeps=4, constraint_iterations=1,
        scale=SimulationScaleSettings(distance_unit_meters=1.0e-9, time_unit_seconds=1.0e-12, mass_unit_kilograms=1.66054e-27, accuracy_mode="approximation", adaptive_substeps=True),
        interactions=ParticleInteractionSettings(lennard_jones_epsilon=0.002, lennard_jones_sigma=0.22, cutoff=0.66, softening=1.0e-5, maximum_acceleration=50.0),
    )
    return _assign_material(world, "molecular")


def _ferrofluid(*, seed: int, particle_count: int) -> SimulationWorld:
    world = _molecular_gas(seed=seed, particle_count=particle_count)
    world.scale.accuracy_mode = "cinematic"
    world.fields = [ForceField("attractor", center=(0.0, 1.0, 0.0), strength=5.0, radius=4.0, falloff_power=2.0)]
    for particle in world.particles:
        particle.species = "magnetic_droplet"
        particle.material = "goo"
    return world


def _assign_material(world: SimulationWorld, name: str) -> SimulationWorld:
    world.materials[name] = SimulationMaterial(name.title(), density=1.0, damping=0.0)
    for particle in world.particles:
        particle.material = name
    return world
