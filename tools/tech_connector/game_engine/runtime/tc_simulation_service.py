"""Deterministic native simulation primitives for The Entire Scene."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import random
from typing import Any, Iterable, Sequence


Vec3 = tuple[float, float, float]


@dataclass
class SimulationMaterial:
    name: str
    density: float = 1000.0
    damping: float = 0.01
    friction: float = 0.2
    restitution: float = 0.05
    stretch_compliance: float = 0.0
    bend_compliance: float = 2.0e-5
    thickness: float = 0.001
    warp_compliance: float = -1.0
    weft_compliance: float = -1.0
    bias_compliance: float = -1.0
    warp_bend_compliance: float = -1.0
    weft_bend_compliance: float = -1.0
    air_drag: float = 0.02
    lift: float = 0.0
    strain_limit: float = 0.0
    wet_absorption: float = 0.0
    viscosity: float = 0.0
    cohesion: float = 0.0
    surface_tension: float = 0.0
    adhesion: float = 0.0
    yield_strength: float = 0.0
    stringiness: float = 0.0
    temperature: float = 20.0
    emission: float = 0.0
    ignition_temperature: float = 1000000.0
    burn_rate: float = 0.0
    freeze_temperature: float = -1000000.0
    melt_temperature: float = 1000000.0


MATERIAL_PRESETS: dict[str, SimulationMaterial] = {
    "cotton": SimulationMaterial("Cotton", density=450.0, damping=0.025, friction=0.45, bend_compliance=6.0e-5, thickness=0.0006, warp_compliance=8.0e-7, weft_compliance=1.5e-6, bias_compliance=8.0e-6, air_drag=0.035, ignition_temperature=230.0, burn_rate=0.18),
    "silk": SimulationMaterial("Silk", density=130.0, damping=0.012, friction=0.18, bend_compliance=4.0e-4, thickness=0.00018, warp_compliance=2.0e-6, weft_compliance=3.5e-6, bias_compliance=2.0e-5, air_drag=0.05),
    "denim": SimulationMaterial("Denim", density=600.0, damping=0.04, friction=0.55, bend_compliance=8.0e-6, thickness=0.0009, warp_compliance=1.5e-7, weft_compliance=4.0e-7, bias_compliance=3.0e-6, warp_bend_compliance=5.0e-6, weft_bend_compliance=9.0e-6, air_drag=0.02),
    "water": SimulationMaterial("Water", viscosity=0.02, cohesion=0.02, surface_tension=0.07, freeze_temperature=0.0, melt_temperature=2.0),
    "goo": SimulationMaterial("Goo", density=1150.0, damping=0.08, viscosity=0.75, cohesion=0.45, surface_tension=0.3, adhesion=0.35, yield_strength=0.2, stringiness=0.5),
    "granular": SimulationMaterial("Granular", density=1600.0, damping=0.06, friction=0.58, cohesion=0.08),
    "gravy": SimulationMaterial("Gravy", density=1080.0, damping=0.05, viscosity=0.42, cohesion=0.2, surface_tension=0.16),
    "soup": SimulationMaterial("Soup", density=1040.0, damping=0.045, viscosity=0.28, cohesion=0.13, surface_tension=0.1),
    "playdoh": SimulationMaterial("Playdoh", density=1250.0, damping=0.16, friction=0.72, stretch_compliance=8.0e-6, viscosity=0.82, cohesion=0.7, surface_tension=0.38),
    "jello": SimulationMaterial("Jello", density=1050.0, damping=0.08, friction=0.3, stretch_compliance=8.0e-6, bend_compliance=2.0e-5, cohesion=0.5),
    "glass": SimulationMaterial("Glass", density=2500.0, damping=0.015, friction=0.35, restitution=0.08, stretch_compliance=0.0, bend_compliance=0.0),
    "metal": SimulationMaterial("Metal", density=7800.0, damping=0.03, friction=0.4, stretch_compliance=0.0, bend_compliance=0.0, viscosity=0.9, cohesion=0.35, melt_temperature=1450.0),
    "fire": SimulationMaterial("Fire", density=0.4, damping=0.01, temperature=1100.0, emission=1.0),
    "plasma": SimulationMaterial("Plasma", density=0.05, damping=0.005, temperature=8000.0, emission=4.0, cohesion=0.12),
}


@dataclass
class SimulationParticle:
    position: Vec3
    velocity: Vec3 = (0.0, 0.0, 0.0)
    inverse_mass: float = 1.0
    radius: float = 0.03
    material: str = "water"
    phase: str = "particle"
    pinned: bool = False
    temperature: float = 20.0
    fuel: float = 1.0
    burn_damage: float = 0.0
    frozen: bool = False
    state: str = "solid"
    alive: bool = True
    age: float = 0.0
    lifetime: float = 0.0
    color: tuple[float, float, float, float] = (0.85, 0.9, 1.0, 1.0)
    size: float = 1.0
    rotation: float = 0.0
    angular_velocity: float = 0.0
    emitter_id: str = ""
    particle_id: int = -1
    mass: float = 0.0
    charge: float = 0.0
    species: str = "neutral"
    polarizability: float = 0.0
    collision_group: int = 1
    collision_mask: int = -1
    collision_priority: float = 0.0
    effect_attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def inertial_mass(self) -> float:
        """Return explicit mass, or the legacy inverse-mass equivalent."""
        if self.mass > 0.0:
            return float(self.mass)
        return 1.0 / max(1.0e-30, float(self.inverse_mass)) if self.inverse_mass > 0.0 else float("inf")


@dataclass
class DistanceConstraint:
    first: int
    second: int
    rest_length: float
    compliance: float = 0.0
    constraint_type: str = "stretch"
    break_threshold: float = 0.0
    break_distance: float = 0.0
    enabled: bool = True
    lagrange: float = 0.0
    plastic_yield: float = 0.0
    plastic_creep: float = 0.0
    heal_distance: float = 0.0
    reformable: bool = False
    material_axis: str = "isotropic"
    strain_limit: float = 0.0


@dataclass
class PlaneCollider:
    normal: Vec3 = (0.0, 1.0, 0.0)
    offset: float = 0.0
    friction: float = 0.25
    restitution: float = 0.0


@dataclass
class SphereCollider:
    center: Vec3
    radius: float
    friction: float = 0.2
    restitution: float = 0.0


@dataclass
class TriangleMeshCollider:
    vertices: list[Vec3]
    faces: list[tuple[int, ...]]
    friction: float = 0.25
    restitution: float = 0.0
    source_id: str = ""
    live: bool = False
    velocity: Vec3 = (0.0, 0.0, 0.0)
    geometry_revision: int = 0
    _acceleration: Any = field(default=None, init=False, repr=False, compare=False)
    _acceleration_revision: int = field(default=-1, init=False, repr=False, compare=False)
    _acceleration_topology: tuple[tuple[int, ...], ...] = field(default=(), init=False, repr=False, compare=False)
    _query_count: int = field(default=0, init=False, repr=False, compare=False)
    _candidate_sum: int = field(default=0, init=False, repr=False, compare=False)
    _triangle_sum: int = field(default=0, init=False, repr=False, compare=False)
    _visited_node_sum: int = field(default=0, init=False, repr=False, compare=False)

    def mark_geometry_dirty(self, *, topology_changed: bool = False) -> None:
        self.geometry_revision += 1
        if topology_changed:
            self._acceleration = None
            self._acceleration_topology = ()

    def acceleration(self):
        from tech_connector.game_engine.runtime.tc_collision_acceleration_service import TriangleBvh

        topology = tuple(tuple(int(value) for value in face) for face in self.faces)
        if self._acceleration is None or topology != self._acceleration_topology:
            self._acceleration = TriangleBvh.build(self.vertices, self.faces)
            self._acceleration_topology = topology
        elif self._acceleration_revision != self.geometry_revision:
            self._acceleration.refit(self.vertices)
        self._acceleration_revision = self.geometry_revision
        return self._acceleration

    def record_query(self, query: Any) -> None:
        self._query_count += 1
        self._candidate_sum += len(query.triangle_indices)
        self._triangle_sum += int(query.total_triangles)
        self._visited_node_sum += int(query.visited_nodes)

    def collision_diagnostics(self, *, reset: bool = False) -> dict[str, Any]:
        acceleration = self.acceleration()
        result = {
            **acceleration.diagnostics(),
            "source_id": self.source_id,
            "geometry_revision": self.geometry_revision,
            "query_count": self._query_count,
            "average_candidate_triangles": self._candidate_sum / max(1, self._query_count),
            "candidate_ratio": self._candidate_sum / max(1, self._triangle_sum),
            "average_visited_nodes": self._visited_node_sum / max(1, self._query_count),
        }
        if reset:
            self._query_count = self._candidate_sum = self._triangle_sum = self._visited_node_sum = 0
        return result


@dataclass
class AttachmentConstraint:
    particle: int
    target: Vec3
    compliance: float = 0.0
    break_threshold: float = 0.0
    enabled: bool = True
    tag: str = ""


@dataclass
class VolumeConstraint:
    particle_indices: list[int]
    faces: list[tuple[int, int, int]]
    rest_volume: float
    compliance: float = 1.0e-7
    pressure: float = 1.0
    enabled: bool = True
    lagrange: float = 0.0


@dataclass
class AreaConstraint:
    first: int
    second: int
    third: int
    rest_area: float
    compliance: float = 1.0e-7
    break_threshold: float = 0.0
    enabled: bool = True
    lagrange: float = 0.0


@dataclass
class DihedralBendingConstraint:
    edge_first: int
    edge_second: int
    opposite_first: int
    opposite_second: int
    rest_angle: float
    compliance: float = 2.0e-5
    break_threshold: float = 0.0
    enabled: bool = True
    lagrange: float = 0.0


@dataclass
class CurveFlowField:
    points: list[Vec3]
    flow_strength: float = 8.0
    attraction_strength: float = 12.0
    radius: float = 1.0
    falloff_power: float = 1.0
    closed: bool = False


@dataclass
class GeometryEmitter:
    vertices: list[Vec3]
    faces: list[tuple[int, ...]]
    rate: float = 100.0
    material: str = "water"
    radius: float = 0.03
    initial_velocity: Vec3 = (0.0, 0.0, 0.0)
    jitter: float = 0.0
    seed: int = 1
    enabled: bool = True
    remainder: float = 0.0
    emitted_count: int = 0
    source_weights: list[float] = field(default_factory=list)
    source_map_name: str = "emission_source"
    source_map_revision: int = 0

    def set_source_weights(
        self,
        values: Sequence[float],
        *,
        name: str = "emission_source",
        revision: int = 0,
    ) -> None:
        if len(values) != len(self.vertices):
            raise ValueError("Emitter source weights must match the emitter vertex count.")
        self.source_weights = [max(0.0, min(1.0, float(value))) for value in values]
        self.source_map_name = str(name or "emission_source")
        self.source_map_revision = int(revision)


@dataclass
class ForceField:
    field_type: str = "gravity"
    vector: Vec3 = (0.0, -9.81, 0.0)
    center: Vec3 = (0.0, 0.0, 0.0)
    strength: float = 1.0
    radius: float = 0.0
    seed: int = 1
    enabled: bool = True
    inner_radius: float = 0.0
    falloff_power: float = 1.0
    max_acceleration: float = 0.0
    drag: float = 0.0
    gust_strength: float = 0.0
    frequency: float = 1.0
    noise_scale: float = 1.0
    ambient_density: float = 1.225


@dataclass
class SimulationScaleSettings:
    """Numerical/authoring scale contract shared by terrestrial, space, and atomic worlds."""

    distance_unit_meters: float = 1.0
    time_unit_seconds: float = 1.0
    mass_unit_kilograms: float = 1.0
    charge_unit_coulombs: float = 1.0
    accuracy_mode: str = "grounded"
    integrator: str = "symplectic_euler"
    adaptive_substeps: bool = False
    maximum_displacement_fraction: float = 0.35

    def validate(self) -> None:
        for name in ("distance_unit_meters", "time_unit_seconds", "mass_unit_kilograms", "charge_unit_coulombs"):
            if not math.isfinite(float(getattr(self, name))) or float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be finite and greater than zero.")
        if self.accuracy_mode not in {"grounded", "approximation", "cinematic"}:
            raise ValueError(f"Unknown simulation accuracy mode: {self.accuracy_mode}")
        if self.integrator not in {"symplectic_euler"}:
            raise ValueError(f"Unsupported simulation integrator: {self.integrator}")


@dataclass
class ParticleInteractionSettings:
    """Composable long- and short-range particle interactions in authored units."""

    gravity_constant: float = 0.0
    gravity_source_mass_threshold: float = 0.0
    coulomb_constant: float = 0.0
    softening: float = 1.0e-3
    cutoff: float = 0.0
    lennard_jones_epsilon: float = 0.0
    lennard_jones_sigma: float = 0.1
    yukawa_strength: float = 0.0
    yukawa_screening: float = 1.0
    maximum_acceleration: float = 0.0
    long_range_method: str = "auto"
    direct_sum_limit: int = 256
    opening_angle: float = 0.65
    tree_leaf_capacity: int = 8
    maximum_tree_depth: int = 24
    short_range_method: str = "auto"
    collision_mode: str = "none"
    merge_distance_scale: float = 1.0
    merge_speed_limit: float = 0.0
    maximum_merges_per_step: int = 256

    @property
    def enabled(self) -> bool:
        return any(abs(value) > 0.0 for value in (
            self.gravity_constant, self.coulomb_constant,
            self.lennard_jones_epsilon, self.yukawa_strength,
        ))

    def resolved_long_range_method(self, particle_count: int) -> str:
        method = str(self.long_range_method or "auto").lower()
        if method not in {"auto", "exact", "barnes_hut"}:
            raise ValueError(f"Unknown long-range interaction method: {self.long_range_method}")
        if method == "auto":
            return "barnes_hut" if int(particle_count) > max(2, int(self.direct_sum_limit)) else "exact"
        return method

    def resolved_short_range_method(self, particle_count: int) -> str:
        method = str(self.short_range_method or "auto").lower()
        if method not in {"auto", "exact", "spatial_hash"}:
            raise ValueError(f"Unknown short-range interaction method: {self.short_range_method}")
        if method == "auto":
            return "spatial_hash" if self.cutoff > 0.0 and int(particle_count) > max(2, int(self.direct_sum_limit)) else "exact"
        return method


def _force_falloff(force: ForceField, distance: float) -> float:
    radius = max(0.0, float(force.radius))
    if radius <= 0.0:
        return 1.0
    inner = min(radius, max(0.0, float(force.inner_radius)))
    if distance <= inner:
        return 1.0
    amount = max(0.0, 1.0 - (distance - inner) / max(1.0e-12, radius - inner))
    return amount ** max(0.01, float(force.falloff_power))


@dataclass
class SparseVolumeCell:
    density: float = 0.0
    temperature: float = 20.0
    fuel: float = 0.0
    flame: float = 0.0
    velocity: Vec3 = (0.0, 0.0, 0.0)
    emission: float = 0.0


@dataclass
class SparseVolume:
    voxel_size: float = 0.1
    cells: dict[tuple[int, int, int], SparseVolumeCell] = field(default_factory=dict)
    dissipation: float = 0.08
    cooling: float = 0.25
    buoyancy: float = 1.0
    pressure_iterations: int = 0
    projection_strength: float = 1.0

    def step(self, dt: float) -> None:
        retained: dict[tuple[int, int, int], SparseVolumeCell] = {}
        for key, cell in self.cells.items():
            cell.density *= max(0.0, 1.0 - self.dissipation * dt)
            cell.fuel = max(0.0, cell.fuel - cell.flame * dt)
            cell.flame = max(0.0, min(1.0, cell.flame + cell.fuel * dt - self.cooling * dt))
            cell.temperature += (20.0 - cell.temperature) * min(1.0, self.cooling * dt)
            cell.velocity = (cell.velocity[0], cell.velocity[1] + self.buoyancy * max(0.0, cell.temperature - 20.0) * 0.001 * dt, cell.velocity[2])
            if cell.density > 1.0e-4 or cell.flame > 1.0e-4 or cell.emission > 1.0e-4:
                retained[key] = cell
        self.cells = retained
        if self.pressure_iterations > 0 and self.cells:
            self._project_velocity()

    def _project_velocity(self) -> None:
        keys = tuple(sorted(self.cells))
        lookup = {key: index for index, key in enumerate(keys)}
        velocity = [list(self.cells[key].velocity) for key in keys]
        divergence = [0.0] * len(keys)
        spacing = max(1.0e-6, float(self.voxel_size))
        for index, key in enumerate(keys):
            for axis in range(3):
                negative = list(key); negative[axis] -= 1
                positive = list(key); positive[axis] += 1
                negative_velocity = velocity[lookup[tuple(negative)]][axis] if tuple(negative) in lookup else velocity[index][axis]
                positive_velocity = velocity[lookup[tuple(positive)]][axis] if tuple(positive) in lookup else velocity[index][axis]
                divergence[index] += (positive_velocity - negative_velocity) / (2.0 * spacing)
        pressure = [0.0] * len(keys)
        for _ in range(max(1, int(self.pressure_iterations))):
            next_pressure = [0.0] * len(keys)
            for index, key in enumerate(keys):
                neighbors = []
                for axis in range(3):
                    for offset in (-1, 1):
                        neighbor = list(key); neighbor[axis] += offset
                        if tuple(neighbor) in lookup:
                            neighbors.append(lookup[tuple(neighbor)])
                if neighbors:
                    next_pressure[index] = (
                        sum(pressure[item] for item in neighbors) - divergence[index] * spacing * spacing
                    ) / len(neighbors)
            pressure = next_pressure
        strength = max(0.0, min(1.0, float(self.projection_strength)))
        for index, key in enumerate(keys):
            for axis in range(3):
                negative = list(key); negative[axis] -= 1
                positive = list(key); positive[axis] += 1
                negative_pressure = pressure[lookup[tuple(negative)]] if tuple(negative) in lookup else pressure[index]
                positive_pressure = pressure[lookup[tuple(positive)]] if tuple(positive) in lookup else pressure[index]
                velocity[index][axis] -= strength * (positive_pressure - negative_pressure) / (2.0 * spacing)
            self.cells[key].velocity = tuple(velocity[index])


@dataclass
class SimulationFrame:
    frame: int
    time_seconds: float
    positions: list[Vec3]
    velocities: list[Vec3]
    volume_cells: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SimulationCache:
    frame_rate: float = 24.0
    frames: dict[int, SimulationFrame] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def store(self, frame: SimulationFrame) -> None:
        self.frames[int(frame.frame)] = frame

    def set_stage_state(self, stage_id: str, state: str, *, detail: str = "") -> dict[str, Any]:
        if state not in {"ready", "running", "cached", "skipped", "failed", "stale"}:
            raise ValueError(f"Unknown cache stage state: {state}")
        stages = self.metadata.setdefault("workflow_stages", {})
        receipt = {"state": state, "detail": str(detail)}
        if state == "cached":
            receipt["frame_count"] = len(self.frames)
            receipt["last_frame"] = max(self.frames) if self.frames else None
        stages[str(stage_id)] = receipt
        return dict(receipt)

    def checkpoint(self, frame: int, *, stage_id: str = "simulate") -> SimulationFrame:
        frame_number = int(frame)
        if frame_number not in self.frames:
            raise KeyError(f"Frame {frame_number} has not been cached.")
        checkpoints = self.metadata.setdefault("checkpoints", {})
        checkpoints[str(stage_id)] = frame_number
        return self.frames[frame_number]

    def resumable_frame(self, stage_id: str = "simulate") -> SimulationFrame | None:
        frame_number = dict(self.metadata.get("checkpoints", {})).get(str(stage_id))
        return self.frames.get(int(frame_number)) if frame_number is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.sim_cache.v1",
            "frame_rate": self.frame_rate,
            "metadata": dict(self.metadata),
            "frames": {str(key): asdict(value) for key, value in sorted(self.frames.items())},
        }


@dataclass
class SimulationWorld:
    particles: list[SimulationParticle] = field(default_factory=list)
    constraints: list[DistanceConstraint] = field(default_factory=list)
    plane_colliders: list[PlaneCollider] = field(default_factory=list)
    sphere_colliders: list[SphereCollider] = field(default_factory=list)
    mesh_colliders: list[TriangleMeshCollider] = field(default_factory=list)
    attachments: list[AttachmentConstraint] = field(default_factory=list)
    area_constraints: list[AreaConstraint] = field(default_factory=list)
    bending_constraints: list[DihedralBendingConstraint] = field(default_factory=list)
    volume_constraints: list[VolumeConstraint] = field(default_factory=list)
    emitters: list[GeometryEmitter] = field(default_factory=list)
    curve_fields: list[CurveFlowField] = field(default_factory=list)
    fields: list[ForceField] = field(default_factory=lambda: [ForceField()])
    scale: SimulationScaleSettings = field(default_factory=SimulationScaleSettings)
    interactions: ParticleInteractionSettings = field(default_factory=ParticleInteractionSettings)
    pic_grids: list[Any] = field(default_factory=list)
    magnetic_grids: list[Any] = field(default_factory=list)
    volumes: dict[str, SparseVolume] = field(default_factory=dict)
    materials: dict[str, SimulationMaterial] = field(default_factory=lambda: {key: SimulationMaterial(**asdict(value)) for key, value in MATERIAL_PRESETS.items()})
    substeps: int = 5
    constraint_iterations: int = 12
    self_collision: bool = True
    time_seconds: float = 0.0
    surface_faces: list[tuple[int, ...]] = field(default_factory=list)
    reformable_settings: dict[str, dict[str, float]] = field(default_factory=dict)
    cloth_settings: dict[str, Any] = field(default_factory=dict)
    effect_system: Any = None
    deformable_surfaces: list[Any] = field(default_factory=list)
    debug_contacts: list[dict[str, Any]] = field(default_factory=list, repr=False)
    debug_physics_joints: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def step(self, dt: float) -> None:
        self.scale.validate()
        self.debug_contacts.clear()
        if self.effect_system is not None:
            from tech_connector.game_engine.runtime.tc_effect_system_service import prepare_effect_step
            prepare_effect_step(self.effect_system, self, float(dt))
        self._emit_geometry(float(dt))
        self._update_reformable_bonds()
        substeps = self.resolved_substeps(float(dt))
        self._frame_dt = float(dt)
        sub_dt = float(dt) / substeps
        for _substep in range(substeps):
            self._field_time_seconds = self.time_seconds + _substep * sub_dt
            previous = [particle.position for particle in self.particles]
            collision_responses: dict[int, tuple[Vec3, float, float, Vec3]] = {}
            self._integrate(sub_dt)
            for constraint in self.constraints:
                constraint.lagrange = 0.0
            for constraint in self.area_constraints:
                constraint.lagrange = 0.0
            for constraint in self.bending_constraints:
                constraint.lagrange = 0.0
            for constraint in self.volume_constraints:
                constraint.lagrange = 0.0
            bending_iterations = max(0, int(self.cloth_settings.get(
                "dihedral_iterations_per_substep", self.constraint_iterations,
            )))
            for _iteration in range(max(1, int(self.constraint_iterations))):
                self._solve_distance_constraints(sub_dt)
                self._solve_attachments(sub_dt)
                self._solve_area_constraints(sub_dt)
                if _iteration < bending_iterations:
                    self._solve_bending_constraints(sub_dt)
                self._solve_volume_constraints(sub_dt)
                if self.self_collision:
                    self._solve_particle_contacts()
                self._solve_colliders(sub_dt, collision_responses)
                self._solve_material_neighbors(sub_dt)
            for index, particle in enumerate(self.particles):
                if not particle.alive or particle.pinned or particle.frozen or particle.inverse_mass <= 0.0:
                    particle.velocity = (0.0, 0.0, 0.0)
                    continue
                velocity = _scale(_subtract(particle.position, previous[index]), 1.0 / max(1.0e-12, sub_dt))
                material = self.materials.get(particle.material, MATERIAL_PRESETS["water"])
                particle.velocity = _scale(velocity, max(0.0, 1.0 - material.damping * sub_dt))
                response = collision_responses.get(index)
                if response is not None:
                    normal, friction, restitution, surface_velocity = response
                    relative_velocity = _subtract(particle.velocity, surface_velocity)
                    particle.velocity = _add(
                        _friction_velocity(relative_velocity, normal, friction, restitution), surface_velocity
                    )
                    self._apply_material_adhesion(particle, sub_dt)
            self._update_thermal_state(sub_dt)
        self._resolve_interaction_collisions()
        self.__dict__.pop("_field_time_seconds", None)
        self.__dict__.pop("_frame_dt", None)
        for volume in self.volumes.values():
            volume.step(float(dt))
        for surface in self.deformable_surfaces:
            surface.step(float(dt))
        self.time_seconds += float(dt)
        if self.effect_system is not None:
            from tech_connector.game_engine.runtime.tc_effect_system_service import finish_effect_step
            finish_effect_step(self.effect_system, self, float(dt))

    def resolved_substeps(self, dt: float) -> int:
        base = max(1, int(self.substeps))
        if not self.scale.adaptive_substeps or dt <= 0.0:
            return base
        dynamic = [
            particle for particle in self.particles
            if particle.alive and not particle.pinned and not particle.frozen and particle.inverse_mass > 0.0
        ]
        if not dynamic:
            return base
        minimum_radius = min(max(1.0e-9, float(particle.radius)) for particle in dynamic)
        maximum_speed = max(_length(particle.velocity) for particle in dynamic)
        allowed = minimum_radius * max(0.01, float(self.scale.maximum_displacement_fraction))
        required = math.ceil(maximum_speed * float(dt) / max(1.0e-12, allowed))
        return min(256, max(base, required))

    def capture_frame(self, frame: int) -> SimulationFrame:
        volume_cells = {
            name: {f"{key[0]},{key[1]},{key[2]}": asdict(cell) for key, cell in volume.cells.items()}
            for name, volume in self.volumes.items()
        }
        return SimulationFrame(
            int(frame), self.time_seconds,
            [particle.position for particle in self.particles],
            [particle.velocity for particle in self.particles],
            volume_cells,
        )

    def _integrate(self, dt: float) -> None:
        for grid in self.pic_grids:
            solve_tick = float(self.time_seconds)
            if getattr(grid, "_last_solve_tick", None) != solve_tick:
                grid.solve(self.particles)
                grid._last_solve_tick = solve_tick
        for grid in self.magnetic_grids:
            solve_tick = float(self.time_seconds)
            if getattr(grid, "_last_solve_tick", None) != solve_tick:
                grid.solve(self.particles, float(getattr(self, "_frame_dt", dt)))
                grid._last_solve_tick = solve_tick
        accelerations: list[Vec3] = []
        for index, particle in enumerate(self.particles):
            if not particle.alive or particle.pinned or particle.frozen or particle.inverse_mass <= 0.0:
                accelerations.append((0.0, 0.0, 0.0))
                continue
            acceleration = (0.0, 0.0, 0.0)
            for force in self.fields:
                acceleration = _add(acceleration, self._field_acceleration(force, particle, index))
            for curve in self.curve_fields:
                acceleration = _add(acceleration, self._curve_acceleration(curve, particle.position))
            mass = particle.inertial_mass
            if particle.charge and math.isfinite(mass):
                for grid in self.pic_grids:
                    acceleration = _add(
                        acceleration,
                        _scale(grid.sample(particle.position), particle.charge / max(1.0e-30, mass)),
                    )
                for grid in self.magnetic_grids:
                    acceleration = _add(
                        acceleration,
                        _scale(
                            _cross(particle.velocity, grid.sample(particle.position)),
                            particle.charge / max(1.0e-30, mass),
                        ),
                    )
            accelerations.append(acceleration)
        self._accumulate_particle_interactions(accelerations)
        for particle, acceleration in zip(self.particles, accelerations):
            if not particle.alive or particle.pinned or particle.frozen or particle.inverse_mass <= 0.0:
                continue
            particle.velocity = _add(particle.velocity, _scale(acceleration, dt))
            particle.position = _add(particle.position, _scale(particle.velocity, dt))

    def _accumulate_particle_interactions(self, accelerations: list[Vec3]) -> None:
        settings = self.interactions
        if not settings.enabled:
            return
        softening_sq = max(1.0e-30, float(settings.softening) ** 2)
        cutoff = max(0.0, float(settings.cutoff))
        maximum = max(0.0, float(settings.maximum_acceleration))
        source_threshold = max(0.0, float(settings.gravity_source_mass_threshold))
        long_range_only = bool(settings.gravity_constant or settings.coulomb_constant) and not any(
            (settings.lennard_jones_epsilon, settings.yukawa_strength)
        )
        if (
            source_threshold <= 0.0 and long_range_only
            and settings.resolved_long_range_method(len(self.particles)) == "barnes_hut"
        ):
            from tech_connector.game_engine.runtime.tc_nbody_acceleration_service import barnes_hut_accelerations

            tree_acceleration, receipt = barnes_hut_accelerations(
                [particle.position for particle in self.particles],
                [particle.inertial_mass for particle in self.particles],
                [particle.charge for particle in self.particles],
                [particle.alive for particle in self.particles],
                settings,
            )
            for index, value in enumerate(tree_acceleration):
                accelerations[index] = _add(accelerations[index], value)
            self._interaction_diagnostics = receipt
            if maximum > 0.0:
                for index, value in enumerate(accelerations):
                    magnitude = _length(value)
                    if magnitude > maximum:
                        accelerations[index] = _scale(value, maximum / magnitude)
            return
        short_range_only = bool(settings.lennard_jones_epsilon or settings.yukawa_strength) and not any(
            (settings.gravity_constant, settings.coulomb_constant)
        )
        if (
            short_range_only and settings.cutoff > 0.0
            and settings.resolved_short_range_method(len(self.particles)) == "spatial_hash"
        ):
            from tech_connector.game_engine.runtime.tc_short_range_interaction_service import spatial_hash_accelerations

            hashed, receipt = spatial_hash_accelerations(
                [particle.position for particle in self.particles],
                [particle.inertial_mass for particle in self.particles],
                [particle.alive for particle in self.particles], settings,
            )
            for index, value in enumerate(hashed):
                accelerations[index] = _add(accelerations[index], value)
            self._interaction_diagnostics = receipt
            return
        if (
            settings.gravity_constant and source_threshold > 0.0
            and not any((settings.coulomb_constant, settings.lennard_jones_epsilon, settings.yukawa_strength))
        ):
            sources = [
                (index, particle) for index, particle in enumerate(self.particles)
                if particle.alive and particle.inertial_mass >= source_threshold
            ]
            interaction_count = 0
            for target_index, target in enumerate(self.particles):
                if not target.alive:
                    continue
                for source_index, source in sources:
                    if source_index == target_index:
                        continue
                    interaction_count += 1
                    delta = _subtract(source.position, target.position)
                    distance_sq = _dot(delta, delta) + softening_sq
                    distance = math.sqrt(distance_sq)
                    if cutoff > 0.0 and distance > cutoff:
                        continue
                    value = float(settings.gravity_constant) * source.inertial_mass / distance_sq
                    accelerations[target_index] = _add(
                        accelerations[target_index], _scale(delta, value / max(1.0e-30, distance))
                    )
            if maximum > 0.0:
                for index, value in enumerate(accelerations):
                    magnitude = _length(value)
                    if magnitude > maximum:
                        accelerations[index] = _scale(value, maximum / magnitude)
            self._interaction_diagnostics = {
                "method": "dominant_source", "particles": len(self.particles),
                "sources": len(sources), "direct_interactions": interaction_count,
            }
            return
        self._interaction_diagnostics = {
            "method": "exact", "particles": sum(1 for particle in self.particles if particle.alive),
            "direct_interactions": 0,
        }
        for first_index, first in enumerate(self.particles):
            if not first.alive:
                continue
            first_mass = first.inertial_mass
            for second_index in range(first_index + 1, len(self.particles)):
                second = self.particles[second_index]
                if not second.alive:
                    continue
                self._interaction_diagnostics["direct_interactions"] += 1
                delta = _subtract(second.position, first.position)
                distance_sq = _dot(delta, delta) + softening_sq
                distance = math.sqrt(distance_sq)
                if cutoff > 0.0 and distance > cutoff:
                    continue
                direction = _scale(delta, 1.0 / max(1.0e-30, distance))
                second_mass = second.inertial_mass
                first_scalar = second_scalar = 0.0
                if settings.gravity_constant and math.isfinite(first_mass) and math.isfinite(second_mass):
                    if second_mass >= source_threshold:
                        first_scalar += float(settings.gravity_constant) * second_mass / distance_sq
                    if first_mass >= source_threshold:
                        second_scalar -= float(settings.gravity_constant) * first_mass / distance_sq
                if settings.coulomb_constant and math.isfinite(first_mass) and math.isfinite(second_mass):
                    force = -float(settings.coulomb_constant) * first.charge * second.charge / distance_sq
                    first_scalar += force / max(1.0e-30, first_mass)
                    second_scalar -= force / max(1.0e-30, second_mass)
                if settings.lennard_jones_epsilon and distance > 1.0e-15:
                    ratio = min(10.0, float(settings.lennard_jones_sigma) / distance)
                    ratio6 = ratio ** 6
                    force = 24.0 * float(settings.lennard_jones_epsilon) * (2.0 * ratio6 * ratio6 - ratio6) / distance
                    first_scalar -= force / max(1.0e-30, first_mass)
                    second_scalar += force / max(1.0e-30, second_mass)
                if settings.yukawa_strength and distance > 1.0e-15:
                    screening = max(0.0, float(settings.yukawa_screening))
                    force = float(settings.yukawa_strength) * math.exp(-screening * distance) * (
                        1.0 / distance_sq + screening / distance
                    )
                    first_scalar -= force / max(1.0e-30, first_mass)
                    second_scalar += force / max(1.0e-30, second_mass)
                accelerations[first_index] = _add(accelerations[first_index], _scale(direction, first_scalar))
                accelerations[second_index] = _add(accelerations[second_index], _scale(direction, second_scalar))
        if maximum > 0.0:
            for index, value in enumerate(accelerations):
                magnitude = _length(value)
                if magnitude > maximum:
                    accelerations[index] = _scale(value, maximum / magnitude)

    def _resolve_interaction_collisions(self) -> None:
        mode = str(self.interactions.collision_mode or "none").lower()
        if mode == "none":
            return
        if mode != "merge":
            raise ValueError(f"Unknown particle interaction collision mode: {self.interactions.collision_mode}")
        alive = [index for index, particle in enumerate(self.particles) if particle.alive]
        if len(alive) < 2:
            return
        scale = max(0.01, float(self.interactions.merge_distance_scale))
        cell_size = max(1.0e-9, max(self.particles[index].radius for index in alive) * 2.0 * scale)
        grid: dict[tuple[int, int, int], list[int]] = {}
        for index in alive:
            key = tuple(math.floor(value / cell_size) for value in self.particles[index].position)
            grid.setdefault(key, []).append(index)
        maximum_merges = max(1, int(self.interactions.maximum_merges_per_step))
        speed_limit = max(0.0, float(self.interactions.merge_speed_limit))
        merged = 0
        visited: set[tuple[int, int]] = set()
        for key in sorted(grid):
            candidates: list[int] = []
            for x in range(key[0] - 1, key[0] + 2):
                for y in range(key[1] - 1, key[1] + 2):
                    for z in range(key[2] - 1, key[2] + 2):
                        candidates.extend(grid.get((x, y, z), ()))
            for first_index in grid[key]:
                first = self.particles[first_index]
                if not first.alive:
                    continue
                for second_index in candidates:
                    pair = tuple(sorted((first_index, second_index)))
                    if first_index == second_index or pair in visited:
                        continue
                    visited.add(pair)
                    second = self.particles[second_index]
                    if not second.alive:
                        continue
                    distance = _length(_subtract(second.position, first.position))
                    if distance > (first.radius + second.radius) * scale:
                        continue
                    relative_speed = _length(_subtract(second.velocity, first.velocity))
                    if speed_limit > 0.0 and relative_speed > speed_limit:
                        continue
                    first_mass, second_mass = first.inertial_mass, second.inertial_mass
                    if not math.isfinite(first_mass) or not math.isfinite(second_mass):
                        continue
                    total_mass = first_mass + second_mass
                    first.position = tuple(
                        (first.position[axis] * first_mass + second.position[axis] * second_mass) / total_mass
                        for axis in range(3)
                    )
                    first.velocity = tuple(
                        (first.velocity[axis] * first_mass + second.velocity[axis] * second_mass) / total_mass
                        for axis in range(3)
                    )
                    first.mass = total_mass
                    first.inverse_mass = 0.0 if first.pinned else 1.0 / max(1.0e-30, total_mass)
                    first.charge += second.charge
                    first.radius = (first.radius ** 3 + second.radius ** 3) ** (1.0 / 3.0)
                    second.alive = False
                    second.velocity = (0.0, 0.0, 0.0)
                    self.debug_contacts.append({
                        "point": first.position, "normal": (0.0, 1.0, 0.0),
                        "penetration": 0.0, "kind": "merge",
                    })
                    merged += 1
                    if merged >= maximum_merges:
                        self._interaction_diagnostics = {
                            **dict(getattr(self, "_interaction_diagnostics", {}) or {}), "merges": merged,
                        }
                        return
        self._interaction_diagnostics = {
            **dict(getattr(self, "_interaction_diagnostics", {}) or {}), "merges": merged,
        }

    def _field_acceleration(self, force: ForceField, particle: SimulationParticle, particle_index: int) -> Vec3:
        if not force.enabled:
            return (0.0, 0.0, 0.0)
        kind = str(force.field_type or "gravity").lower()
        delta = _subtract(particle.position, force.center)
        distance = _length(delta)
        falloff = _force_falloff(force, distance)
        result = (0.0, 0.0, 0.0)
        if kind in {"gravity", "wind", "uniform"}:
            gust = 1.0 + float(force.gust_strength) * math.sin(
                float(force.frequency) * float(getattr(self, "_field_time_seconds", self.time_seconds))
                * math.tau + float(force.seed)
            )
            result = _scale(force.vector, force.strength * falloff * gust)
            if kind == "wind" and force.drag > 0.0:
                target = _scale(force.vector, force.strength * gust)
                result = _scale(_subtract(target, particle.velocity), float(force.drag) * falloff)
        elif kind in {"gravity_source", "point_gravity"}:
            direction = _scale(_normalize(delta, (0.0, -1.0, 0.0)), -1.0)
            softening = max(1.0e-4, float(force.vector[0]) if force.vector else 0.05)
            acceleration = force.strength / max(softening * softening, distance * distance + softening * softening)
            result = _scale(direction, acceleration * falloff)
        elif kind in {"radial", "repulsor", "attractor"}:
            sign = -1.0 if kind == "attractor" else 1.0
            result = _scale(_normalize(delta, (0.0, 1.0, 0.0)), sign * force.strength * falloff)
        elif kind == "vortex":
            axis = _normalize(force.vector, (0.0, 1.0, 0.0))
            tangent = _normalize(_cross(axis, delta), (1.0, 0.0, 0.0))
            result = _scale(tangent, force.strength * falloff)
        elif kind == "turbulence":
            phase = float(force.seed) * 17.17 + particle_index * 0.754877666
            field_time = float(getattr(self, "_field_time_seconds", self.time_seconds))
            time_phase = field_time * max(0.0, float(force.frequency))
            scale = max(1.0e-6, float(force.noise_scale))
            sample = _add(_scale(particle.position, scale), (phase, phase * 1.37, phase * 2.11))
            noise = (
                math.sin(sample[1] * 1.73 + sample[2] * 0.63 + time_phase * 2.03),
                math.sin(sample[2] * 1.31 + sample[0] * 0.79 + time_phase * 1.71),
                math.sin(sample[0] * 1.57 + sample[1] * 0.91 + time_phase * 2.29),
            )
            result = _scale(noise, force.strength * falloff)
        elif kind in {"drag", "linear_drag"}:
            result = _scale(_subtract(force.vector, particle.velocity), force.strength * falloff)
        elif kind == "quadratic_drag":
            relative = _subtract(particle.velocity, force.vector)
            result = _scale(relative, -force.strength * _length(relative) * falloff)
        elif kind == "buoyancy":
            material = self.materials.get(particle.material)
            density = max(1.0e-6, float(material.density if material is not None else 1000.0))
            density_ratio = max(0.0, float(force.ambient_density)) / density
            result = _scale(_normalize(force.vector, (0.0, 1.0, 0.0)), force.strength * density_ratio * falloff)
        elif kind in {"electric", "electric_field"}:
            mass = particle.inertial_mass
            if math.isfinite(mass):
                result = _scale(force.vector, force.strength * particle.charge / max(1.0e-30, mass) * falloff)
        elif kind in {"magnetic", "magnetic_field"}:
            mass = particle.inertial_mass
            if math.isfinite(mass):
                result = _scale(
                    _cross(particle.velocity, force.vector),
                    force.strength * particle.charge / max(1.0e-30, mass) * falloff,
                )
        elif kind in {"radiation", "radiation_pressure"}:
            mass = particle.inertial_mass
            area = math.pi * max(0.0, particle.radius) ** 2
            if math.isfinite(mass):
                result = _scale(
                    _normalize(force.vector, (0.0, 1.0, 0.0)),
                    force.strength * area / max(1.0e-30, mass) * falloff,
                )
        elif kind in {"coriolis", "rotating_frame"}:
            omega = _scale(force.vector, force.strength)
            relative = _subtract(particle.position, force.center)
            coriolis = _scale(_cross(omega, particle.velocity), -2.0)
            centrifugal = _scale(_cross(omega, _cross(omega, relative)), -1.0)
            result = _scale(_add(coriolis, centrifugal), falloff)
        maximum = max(0.0, float(force.max_acceleration))
        length = _length(result)
        return _scale(result, maximum / length) if maximum > 0.0 and length > maximum else result

    def _curve_acceleration(self, field: CurveFlowField, position: Vec3) -> Vec3:
        points = list(field.points)
        if len(points) < 2:
            return (0.0, 0.0, 0.0)
        segments = list(zip(points, points[1:]))
        if field.closed:
            segments.append((points[-1], points[0]))
        closest = None
        closest_distance = float("inf")
        closest_tangent = (0.0, 0.0, 1.0)
        for first, second in segments:
            segment = _subtract(second, first)
            length_sq = max(1.0e-12, _dot(segment, segment))
            amount = max(0.0, min(1.0, _dot(_subtract(position, first), segment) / length_sq))
            point = _add(first, _scale(segment, amount))
            distance = _length(_subtract(point, position))
            if distance < closest_distance:
                closest, closest_distance = point, distance
                closest_tangent = _normalize(segment, closest_tangent)
        if closest is None or (field.radius > 0.0 and closest_distance > field.radius):
            return (0.0, 0.0, 0.0)
        falloff = 1.0 if field.radius <= 0.0 else max(0.0, 1.0 - closest_distance / field.radius) ** max(0.01, field.falloff_power)
        attraction = _scale(_subtract(closest, position), field.attraction_strength * falloff)
        flow = _scale(closest_tangent, field.flow_strength * falloff)
        return _add(attraction, flow)

    def _solve_distance_constraints(self, dt: float) -> None:
        for constraint in self.constraints:
            if not constraint.enabled:
                continue
            first = self.particles[constraint.first]
            second = self.particles[constraint.second]
            delta = _subtract(second.position, first.position)
            length = _length(delta)
            if length <= 1.0e-12:
                continue
            strain = length / max(1.0e-12, constraint.rest_length)
            if constraint.break_distance > 0.0 and abs(length - constraint.rest_length) > constraint.break_distance:
                constraint.enabled = False
                continue
            if constraint.break_threshold > 0.0 and strain > constraint.break_threshold:
                constraint.enabled = False
                continue
            if (
                constraint.plastic_yield > 0.0
                and abs(strain - 1.0) > constraint.plastic_yield
                and constraint.lagrange == 0.0
            ):
                creep = min(1.0, max(0.0, constraint.plastic_creep) * dt)
                constraint.rest_length += (length - constraint.rest_length) * creep
            first_weight = 0.0 if first.pinned or first.frozen else first.inverse_mass
            second_weight = 0.0 if second.pinned or second.frozen else second.inverse_mass
            weight_sum = first_weight + second_weight
            if weight_sum <= 0.0:
                continue
            normal = _scale(delta, 1.0 / length)
            if constraint.strain_limit > 1.0 and strain > constraint.strain_limit:
                excess = length - constraint.rest_length * constraint.strain_limit
                hard_correction = _scale(normal, excess / weight_sum)
                if first_weight > 0.0:
                    first.position = _add(first.position, _scale(hard_correction, first_weight))
                if second_weight > 0.0:
                    second.position = _subtract(second.position, _scale(hard_correction, second_weight))
                delta = _subtract(second.position, first.position)
                length = _length(delta)
                if length <= 1.0e-12:
                    continue
                normal = _scale(delta, 1.0 / length)
            alpha = max(0.0, constraint.compliance) / max(1.0e-12, dt * dt)
            delta_lambda = (-(length - constraint.rest_length) - alpha * constraint.lagrange) / (weight_sum + alpha)
            constraint.lagrange += delta_lambda
            correction = _scale(normal, delta_lambda)
            if first_weight > 0.0:
                first.position = _subtract(first.position, _scale(correction, first_weight))
            if second_weight > 0.0:
                second.position = _add(second.position, _scale(correction, second_weight))

    def _update_reformable_bonds(self) -> None:
        for material, raw_settings in self.reformable_settings.items():
            settings = dict(raw_settings or {})
            bond_distance = max(1.0e-6, float(settings.get("bond_distance", 0.1)))
            heal_distance = max(1.0e-6, float(settings.get("heal_distance", bond_distance * 0.9)))
            max_neighbors = max(1, int(settings.get("max_neighbors", 14)))
            max_heal_speed = max(0.0, float(settings.get("max_heal_speed", 2.0)))
            particle_indices = [index for index, particle in enumerate(self.particles) if particle.material == material]
            if len(particle_indices) < 2:
                continue
            existing: dict[tuple[int, int], DistanceConstraint] = {}
            neighbor_counts = {index: 0 for index in particle_indices}
            for constraint in self.constraints:
                if not constraint.reformable:
                    continue
                pair = tuple(sorted((constraint.first, constraint.second)))
                existing[pair] = constraint
                if constraint.enabled:
                    neighbor_counts[constraint.first] = neighbor_counts.get(constraint.first, 0) + 1
                    neighbor_counts[constraint.second] = neighbor_counts.get(constraint.second, 0) + 1
            grid: dict[tuple[int, int, int], list[int]] = {}
            for index in particle_indices:
                key = tuple(math.floor(value / bond_distance) for value in self.particles[index].position)
                grid.setdefault(key, []).append(index)
            for first_index in particle_indices:
                first = self.particles[first_index]
                key = tuple(math.floor(value / bond_distance) for value in first.position)
                candidates = []
                for x in range(key[0] - 1, key[0] + 2):
                    for y in range(key[1] - 1, key[1] + 2):
                        for z in range(key[2] - 1, key[2] + 2):
                            candidates.extend(grid.get((x, y, z), ()))
                for second_index in candidates:
                    if second_index <= first_index:
                        continue
                    second = self.particles[second_index]
                    distance = _length(_subtract(second.position, first.position))
                    pair = (first_index, second_index)
                    constraint = existing.get(pair)
                    relative_speed = _length(_subtract(second.velocity, first.velocity))
                    if constraint is not None:
                        if not constraint.enabled and distance <= constraint.heal_distance and relative_speed <= max_heal_speed:
                            constraint.enabled = True
                            constraint.rest_length = max(distance, first.radius + second.radius)
                            constraint.lagrange = 0.0
                            neighbor_counts[first_index] += 1
                            neighbor_counts[second_index] += 1
                        continue
                    if (
                        distance > bond_distance
                        or relative_speed > max_heal_speed
                        or neighbor_counts[first_index] >= max_neighbors
                        or neighbor_counts[second_index] >= max_neighbors
                    ):
                        continue
                    constraint = DistanceConstraint(
                        first_index, second_index, max(distance, first.radius + second.radius),
                        compliance=float(settings.get("compliance", 8.0e-6)),
                        constraint_type="reformable_bond",
                        break_threshold=float(settings.get("break_threshold", 1.65)),
                        plastic_yield=float(settings.get("plastic_yield", 0.08)),
                        plastic_creep=float(settings.get("plastic_creep", 5.0)),
                        heal_distance=heal_distance,
                        reformable=True,
                    )
                    self.constraints.append(constraint)
                    existing[pair] = constraint
                    neighbor_counts[first_index] += 1
                    neighbor_counts[second_index] += 1

    def _solve_attachments(self, dt: float) -> None:
        for attachment in self.attachments:
            if not attachment.enabled or not 0 <= attachment.particle < len(self.particles):
                continue
            particle = self.particles[attachment.particle]
            delta = _subtract(particle.position, attachment.target)
            distance = _length(delta)
            if attachment.break_threshold > 0.0 and distance > attachment.break_threshold:
                attachment.enabled = False
                continue
            if particle.pinned or particle.frozen or particle.inverse_mass <= 0.0:
                particle.position = attachment.target
                continue
            alpha = max(0.0, attachment.compliance) / max(1.0e-12, dt * dt)
            particle.position = _subtract(particle.position, _scale(delta, particle.inverse_mass / (particle.inverse_mass + alpha)))

    def _solve_volume_constraints(self, dt: float) -> None:
        for constraint in self.volume_constraints:
            if not constraint.enabled:
                continue
            gradients = {index: [0.0, 0.0, 0.0] for index in constraint.particle_indices}
            current_volume = 0.0
            for first, second, third in constraint.faces:
                a, b, c = (self.particles[index].position for index in (first, second, third))
                current_volume += _dot(a, _cross(b, c)) / 6.0
                for index, gradient in (
                    (first, _scale(_cross(b, c), 1.0 / 6.0)),
                    (second, _scale(_cross(c, a), 1.0 / 6.0)),
                    (third, _scale(_cross(a, b), 1.0 / 6.0)),
                ):
                    for axis in range(3):
                        gradients[index][axis] += gradient[axis]
            target_volume = constraint.rest_volume * float(constraint.pressure)
            error = current_volume - target_volume
            denominator = 0.0
            for index, gradient in gradients.items():
                particle = self.particles[index]
                weight = 0.0 if particle.pinned or particle.frozen else particle.inverse_mass
                denominator += weight * sum(value * value for value in gradient)
            alpha = max(0.0, constraint.compliance) / max(1.0e-12, dt * dt)
            if denominator + alpha <= 1.0e-12:
                continue
            delta_lambda = (-error - alpha * constraint.lagrange) / (denominator + alpha)
            constraint.lagrange += delta_lambda
            for index, gradient in gradients.items():
                particle = self.particles[index]
                weight = 0.0 if particle.pinned or particle.frozen else particle.inverse_mass
                particle.position = _add(particle.position, _scale(tuple(gradient), weight * delta_lambda))

    def _solve_area_constraints(self, dt: float) -> None:
        for constraint in self.area_constraints:
            if not constraint.enabled:
                continue
            particles = [self.particles[index] for index in (constraint.first, constraint.second, constraint.third)]
            first, second, third = (particle.position for particle in particles)
            cross_value = _cross(_subtract(second, first), _subtract(third, first))
            cross_length = _length(cross_value)
            if cross_length <= 1.0e-12:
                continue
            current_area = 0.5 * cross_length
            if constraint.break_threshold > 0.0 and current_area / max(1.0e-12, constraint.rest_area) > constraint.break_threshold:
                constraint.enabled = False
                continue
            normal = _scale(cross_value, 1.0 / cross_length)
            gradients = (
                _scale(_cross(_subtract(second, third), normal), 0.5),
                _scale(_cross(_subtract(third, first), normal), 0.5),
                _scale(_cross(_subtract(first, second), normal), 0.5),
            )
            weights = [0.0 if particle.pinned or particle.frozen else particle.inverse_mass for particle in particles]
            denominator = sum(weight * _dot(gradient, gradient) for weight, gradient in zip(weights, gradients))
            alpha = max(0.0, constraint.compliance) / max(1.0e-12, dt * dt)
            if denominator + alpha <= 1.0e-12:
                continue
            error = current_area - constraint.rest_area
            delta_lambda = (-error - alpha * constraint.lagrange) / (denominator + alpha)
            constraint.lagrange += delta_lambda
            for particle, weight, gradient in zip(particles, weights, gradients):
                particle.position = _add(particle.position, _scale(gradient, weight * delta_lambda))

    def _solve_bending_constraints(self, dt: float) -> None:
        """Preserve the authored angle between adjacent cloth triangles."""
        for constraint in self.bending_constraints:
            if not constraint.enabled:
                continue
            indices = (
                constraint.edge_first, constraint.edge_second,
                constraint.opposite_first, constraint.opposite_second,
            )
            if min(indices) < 0 or max(indices) >= len(self.particles):
                constraint.enabled = False
                continue
            edge_first, edge_second, opposite_first, opposite_second = (
                self.particles[index] for index in indices
            )
            axis = _subtract(edge_second.position, edge_first.position)
            axis_length = _length(axis)
            if axis_length <= 1.0e-12:
                continue
            direction = _scale(axis, 1.0 / axis_length)
            current = _signed_dihedral_angle(
                edge_first.position, edge_second.position,
                opposite_first.position, opposite_second.position,
            )
            error = _wrapped_angle(current - constraint.rest_angle)
            if constraint.break_threshold > 0.0 and abs(error) > constraint.break_threshold:
                constraint.enabled = False
                continue
            first_weight = 0.0 if opposite_first.pinned or opposite_first.frozen else opposite_first.inverse_mass
            second_weight = 0.0 if opposite_second.pinned or opposite_second.frozen else opposite_second.inverse_mass
            weight_sum = first_weight + second_weight
            if weight_sum <= 0.0 or abs(error) <= 1.0e-10:
                continue
            alpha = max(0.0, constraint.compliance) / max(1.0e-12, dt * dt)
            correction = (error - alpha * constraint.lagrange) / (weight_sum + alpha)
            constraint.lagrange += correction
            if first_weight > 0.0:
                opposite_first.position = _rotate_about_axis(
                    opposite_first.position, edge_first.position, direction,
                    first_weight * correction,
                )
            if second_weight > 0.0:
                opposite_second.position = _rotate_about_axis(
                    opposite_second.position, edge_first.position, direction,
                    -second_weight * correction,
                )

    def _solve_particle_contacts(self) -> None:
        cell_size = max((particle.radius for particle in self.particles), default=0.05) * 2.0
        grid: dict[tuple[int, int, int], list[int]] = {}
        for index, particle in enumerate(self.particles):
            if not particle.alive:
                continue
            key = tuple(math.floor(value / max(1.0e-6, cell_size)) for value in particle.position)
            grid.setdefault(key, []).append(index)
        visited: set[tuple[int, int]] = set()
        excluded_pairs = set()
        if bool(self.cloth_settings.get("exclude_topological_neighbors", False)):
            excluded_pairs = {
                tuple(sorted((item.first, item.second)))
                for item in self.constraints
                if item.enabled and item.constraint_type in {"stretch", "shear", "bend", "seam"}
            }
        for key, indices in grid.items():
            neighbors = []
            for x in range(key[0] - 1, key[0] + 2):
                for y in range(key[1] - 1, key[1] + 2):
                    for z in range(key[2] - 1, key[2] + 2):
                        neighbors.extend(grid.get((x, y, z), ()))
            for first_index in indices:
                for second_index in neighbors:
                    pair = tuple(sorted((first_index, second_index)))
                    if first_index == second_index or pair in visited or pair in excluded_pairs:
                        continue
                    visited.add(pair)
                    self._separate_particles(first_index, second_index)

    def _separate_particles(self, first_index: int, second_index: int) -> None:
        first, second = self.particles[first_index], self.particles[second_index]
        if not (
            int(first.collision_mask) & int(second.collision_group)
            and int(second.collision_mask) & int(first.collision_group)
        ):
            return
        delta = _subtract(second.position, first.position)
        distance = _length(delta)
        minimum = first.radius + second.radius
        if distance >= minimum:
            return
        normal = _normalize(delta, (1.0, 0.0, 0.0))
        first_weight = 0.0 if first.pinned or first.frozen else first.inverse_mass / (1.0 + max(0.0, first.collision_priority))
        second_weight = 0.0 if second.pinned or second.frozen else second.inverse_mass / (1.0 + max(0.0, second.collision_priority))
        total = first_weight + second_weight
        if total <= 0.0:
            return
        correction = _scale(normal, minimum - distance)
        self._record_debug_contact(
            _add(first.position, _scale(normal, first.radius)), normal, minimum - distance, "particle"
        )
        first.position = _subtract(first.position, _scale(correction, first_weight / total))
        second.position = _add(second.position, _scale(correction, second_weight / total))

    def _solve_colliders(
        self, dt: float, responses: dict[int, tuple[Vec3, float, float, Vec3]] | None = None
    ) -> None:
        for particle_index, particle in enumerate(self.particles):
            if not particle.alive or particle.pinned or particle.frozen:
                continue
            for collider in self.plane_colliders:
                normal = _normalize(collider.normal, (0.0, 1.0, 0.0))
                distance = _dot(particle.position, normal) - collider.offset
                if distance < particle.radius:
                    self._record_debug_contact(
                        _subtract(particle.position, _scale(normal, distance)), normal, particle.radius - distance, "plane"
                    )
                    particle.position = _add(particle.position, _scale(normal, particle.radius - distance))
                    if responses is not None:
                        responses[particle_index] = (
                            normal, collider.friction, collider.restitution, (0.0, 0.0, 0.0)
                        )
            for collider in self.sphere_colliders:
                delta = _subtract(particle.position, collider.center)
                minimum = particle.radius + collider.radius
                if _length(delta) < minimum:
                    normal = _normalize(delta, (0.0, 1.0, 0.0))
                    self._record_debug_contact(
                        _add(collider.center, _scale(normal, collider.radius)), normal,
                        minimum - _length(delta), "sphere",
                    )
                    particle.position = _add(collider.center, _scale(normal, minimum))
                    if responses is not None:
                        responses[particle_index] = (
                            normal, collider.friction, collider.restitution, (0.0, 0.0, 0.0)
                        )
            for collider in self.mesh_colliders:
                response = self._solve_mesh_collision(particle, collider, dt)
                if responses is not None and response is not None:
                    responses[particle_index] = response

    def _solve_mesh_collision(
        self, particle: SimulationParticle, collider: TriangleMeshCollider, dt: float
    ) -> tuple[Vec3, float, float, Vec3] | None:
        closest_point = None
        closest_distance = particle.radius
        closest_normal = (0.0, 1.0, 0.0)
        acceleration = collider.acceleration()
        query = acceleration.query_sphere(particle.position, particle.radius)
        collider.record_query(query)
        for triangle_index in query.triangle_indices:
            face = acceleration.triangles[triangle_index]
            if min(face) < 0 or max(face) >= len(collider.vertices):
                continue
            first, second, third = (collider.vertices[index] for index in face)
            point = _closest_point_on_triangle(particle.position, first, second, third)
            distance = _length(_subtract(particle.position, point))
            if distance < closest_distance:
                closest_distance = distance
                closest_point = point
                closest_normal = _normalize(_cross(_subtract(second, first), _subtract(third, first)), closest_normal)
                if _dot(_subtract(particle.position, point), closest_normal) < 0.0:
                    closest_normal = _scale(closest_normal, -1.0)
        if closest_point is not None:
            self._record_debug_contact(
                closest_point, closest_normal, particle.radius - closest_distance, "mesh"
            )
            particle.position = _add(closest_point, _scale(closest_normal, particle.radius))
            normal_speed = _dot(collider.velocity, closest_normal)
            tangent_velocity = _subtract(collider.velocity, _scale(closest_normal, normal_speed))
            particle.position = _add(particle.position, _scale(tangent_velocity, max(0.0, collider.friction) * dt))
            return closest_normal, collider.friction, collider.restitution, collider.velocity
        return None

    def _apply_material_adhesion(self, particle: SimulationParticle, dt: float) -> None:
        material = self.materials.get(particle.material)
        if material is not None and material.adhesion > 0.0:
            particle.velocity = _scale(particle.velocity, math.exp(-material.adhesion * max(0.0, dt)))

    def _record_debug_contact(self, point: Vec3, normal: Vec3, penetration: float, kind: str) -> None:
        if len(self.debug_contacts) >= 4096:
            return
        self.debug_contacts.append({
            "point": tuple(float(value) for value in point),
            "normal": tuple(float(value) for value in normal),
            "penetration": max(0.0, float(penetration)),
            "kind": str(kind),
        })

    def _emit_geometry(self, dt: float) -> None:
        for emitter in self.emitters:
            if not emitter.enabled or not emitter.faces or not emitter.vertices:
                continue
            areas = []
            weighted_area = 0.0
            total_surface_area = 0.0
            valid_faces = []
            face_max_weights = []
            source_weights = (
                list(emitter.source_weights)
                if len(emitter.source_weights) == len(emitter.vertices)
                else [1.0] * len(emitter.vertices)
            )
            for face in _triangulate_polygons(emitter.faces):
                if min(face) < 0 or max(face) >= len(emitter.vertices):
                    continue
                first, second, third = (emitter.vertices[index] for index in face)
                area = 0.5 * _length(_cross(_subtract(second, first), _subtract(third, first)))
                if area > 1.0e-12:
                    vertex_weights = [source_weights[index] for index in face]
                    face_weight = sum(vertex_weights) / 3.0
                    total_surface_area += area
                    if face_weight <= 1.0e-12:
                        continue
                    weighted_area += area * face_weight
                    areas.append(weighted_area)
                    valid_faces.append(face)
                    face_max_weights.append(max(vertex_weights))
            if weighted_area <= 0.0 or total_surface_area <= 0.0:
                continue
            coverage = weighted_area / total_surface_area
            requested = emitter.rate * coverage * dt + emitter.remainder
            count = int(requested)
            emitter.remainder = requested - count
            for _index in range(count):
                rng = random.Random(emitter.seed * 1000003 + emitter.emitted_count)
                sample = rng.random() * weighted_area
                face_index = next(index for index, cumulative in enumerate(areas) if sample <= cumulative)
                face = valid_faces[face_index]
                first, second, third = (emitter.vertices[index] for index in face)
                face_weights = [source_weights[index] for index in face]
                u = v = 0.0
                accepted = False
                for _attempt in range(32):
                    u, v = rng.random(), rng.random()
                    if u + v > 1.0:
                        u, v = 1.0 - u, 1.0 - v
                    barycentric = (1.0 - u - v, u, v)
                    local_weight = sum(weight * coordinate for weight, coordinate in zip(face_weights, barycentric))
                    if rng.random() * face_max_weights[face_index] <= local_weight:
                        accepted = True
                        break
                if not accepted:
                    strongest = max(range(3), key=face_weights.__getitem__)
                    u, v = ((1.0, 0.0) if strongest == 1 else (0.0, 1.0) if strongest == 2 else (0.0, 0.0))
                position = _add(first, _add(_scale(_subtract(second, first), u), _scale(_subtract(third, first), v)))
                jitter = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
                velocity = _add(emitter.initial_velocity, _scale(jitter, emitter.jitter))
                material = self.materials.get(emitter.material, MATERIAL_PRESETS["water"])
                self.particles.append(SimulationParticle(
                    position, velocity=velocity, radius=emitter.radius, material=emitter.material,
                    phase="fluid" if emitter.material in {"water", "goo", "gravy", "soup"} else "particle",
                    state="liquid" if emitter.material in {"water", "goo", "gravy", "soup"} else "solid",
                    temperature=material.temperature,
                ))
                emitter.emitted_count += 1

    def _update_thermal_state(self, dt: float) -> None:
        for particle in self.particles:
            if not particle.alive:
                continue
            for force in self.fields:
                if str(force.field_type or "").lower() not in {"heat", "cold", "temperature"}:
                    continue
                distance = _length(_subtract(particle.position, force.center))
                falloff = 1.0 if force.radius <= 0.0 else max(0.0, 1.0 - distance / force.radius)
                particle.temperature += force.strength * falloff * dt
            material = self.materials.get(particle.material)
            if material is None:
                continue
            if particle.temperature >= material.ignition_temperature and particle.fuel > 0.0:
                burned = min(particle.fuel, material.burn_rate * dt)
                particle.fuel -= burned
                particle.burn_damage = min(1.0, particle.burn_damage + burned)
                particle.temperature += burned * 80.0
            if particle.temperature <= material.freeze_temperature:
                particle.frozen = True
            elif particle.temperature >= material.melt_temperature:
                particle.frozen = False
                if particle.material == "metal":
                    particle.state = "molten"
                    particle.phase = "fluid"
        for constraint in self.constraints:
            damage = max(self.particles[constraint.first].burn_damage, self.particles[constraint.second].burn_damage)
            if damage >= 1.0:
                constraint.enabled = False
            elif damage > 0.0:
                constraint.compliance = max(constraint.compliance, damage * 5.0e-4)
            if any(self.particles[index].state == "molten" for index in (constraint.first, constraint.second)):
                constraint.compliance = max(constraint.compliance, 5.0e-3)
                if all(self.particles[index].temperature >= 1550.0 for index in (constraint.first, constraint.second)):
                    constraint.enabled = False
        for constraint in self.area_constraints:
            particles = [self.particles[index] for index in (constraint.first, constraint.second, constraint.third)]
            if any(particle.state == "molten" for particle in particles):
                constraint.compliance = max(constraint.compliance, 5.0e-3)
            if all(particle.temperature >= 1550.0 for particle in particles):
                constraint.enabled = False
        for constraint in self.volume_constraints:
            if any(self.particles[index].state == "molten" for index in constraint.particle_indices):
                constraint.compliance = max(constraint.compliance, 2.0e-5)

    def _solve_material_neighbors(self, dt: float) -> None:
        for first_index, first in enumerate(self.particles):
            material = self.materials.get(first.material)
            if material is None or (material.viscosity <= 0.0 and material.cohesion <= 0.0):
                continue
            interaction_radius = first.radius * (4.0 + 4.0 * max(0.0, material.stringiness))
            for second_index in range(first_index + 1, len(self.particles)):
                second = self.particles[second_index]
                if second.material != first.material:
                    continue
                delta = _subtract(second.position, first.position)
                distance = _length(delta)
                if distance <= 1.0e-12 or distance >= interaction_radius:
                    continue
                influence = 1.0 - distance / interaction_radius
                if material.viscosity > 0.0:
                    blend = min(0.5, material.viscosity * influence * dt)
                    average = _scale(_add(first.velocity, second.velocity), 0.5)
                    first.velocity = _add(first.velocity, _scale(_subtract(average, first.velocity), blend))
                    second.velocity = _add(second.velocity, _scale(_subtract(average, second.velocity), blend))
                if material.cohesion > 0.0 and distance > first.radius + second.radius:
                    relative_speed = _length(_subtract(first.velocity, second.velocity))
                    yield_factor = 1.0 + max(0.0, material.yield_strength - relative_speed)
                    tension = material.cohesion + material.surface_tension * influence
                    correction = _scale(_normalize(delta), tension * yield_factor * influence * dt * dt)
                    if not first.pinned:
                        first.position = _add(first.position, correction)
                    if not second.pinned:
                        second.position = _subtract(second.position, correction)


def create_cloth_grid(
    columns: int = 16,
    rows: int = 16,
    *,
    spacing: float = 0.08,
    origin: Vec3 = (-0.6, 1.5, 0.0),
    material: str = "cotton",
    pin_top_corners: bool = True,
) -> SimulationWorld:
    if columns < 2 or rows < 2:
        raise ValueError("A cloth grid requires at least two rows and columns.")
    preset = MATERIAL_PRESETS.get(material, MATERIAL_PRESETS["cotton"])
    world = SimulationWorld()
    world.surface_faces = [
        (row * columns + column, row * columns + column + 1, (row + 1) * columns + column + 1, (row + 1) * columns + column)
        for row in range(rows - 1) for column in range(columns - 1)
    ]
    world.plane_colliders.append(PlaneCollider())
    for row in range(rows):
        for column in range(columns):
            pinned = bool(pin_top_corners and row == 0 and column in {0, columns - 1})
            world.particles.append(SimulationParticle(
                (origin[0] + column * spacing, origin[1] - row * spacing, origin[2]),
                inverse_mass=0.0 if pinned else 1.0,
                radius=spacing * 0.18,
                material=material,
                phase="cloth",
                pinned=pinned,
            ))

    def add(first: int, second: int, compliance: float, kind: str, axis: str = "isotropic") -> None:
        world.constraints.append(DistanceConstraint(
            first, second,
            _length(_subtract(world.particles[second].position, world.particles[first].position)),
            _fabric_compliance(preset, axis, compliance, bend=kind == "bend"),
            kind,
            material_axis=axis,
        ))

    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            if column + 1 < columns:
                add(index, index + 1, preset.stretch_compliance, "stretch", "warp")
            if row + 1 < rows:
                add(index, index + columns, preset.stretch_compliance, "stretch", "weft")
            if column + 1 < columns and row + 1 < rows:
                add(index, index + columns + 1, preset.stretch_compliance, "shear", "bias")
                add(index + 1, index + columns, preset.stretch_compliance, "shear", "bias")
            if column + 2 < columns:
                add(index, index + 2, preset.bend_compliance, "bend", "warp")
            if row + 2 < rows:
                add(index, index + columns * 2, preset.bend_compliance, "bend", "weft")
    _add_surface_area_constraints(world, compliance=max(1.0e-8, preset.stretch_compliance))
    from tech_connector.game_engine.runtime.tc_cloth_authoring_service import configure_cloth_quality
    configure_cloth_quality(world, "realtime")
    return world


def create_cloth_from_geometry(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
    *,
    material: str = "cotton",
    pinned_vertices: Iterable[int] = (),
    particle_radius: float = 0.02,
    tear_threshold: float = 0.0,
    uvs: Iterable[tuple[float, float]] | None = None,
) -> SimulationWorld:
    points = [tuple(float(value) for value in point[:3]) for point in vertices]
    polygons = [tuple(int(index) for index in face) for face in faces]
    if not points or not polygons:
        raise ValueError("Cloth conversion requires vertices and polygon faces.")
    if any(len(face) < 3 or min(face) < 0 or max(face) >= len(points) for face in polygons):
        raise ValueError("Cloth conversion contains invalid polygon topology.")
    pinned = set(int(value) for value in pinned_vertices)
    preset = MATERIAL_PRESETS.get(material, MATERIAL_PRESETS["cotton"])
    texture_coordinates = [tuple(float(value) for value in uv[:2]) for uv in (uvs or ())]
    if texture_coordinates and len(texture_coordinates) != len(points):
        raise ValueError("Cloth material coordinates must match the vertex count.")
    world = SimulationWorld(surface_faces=list(polygons))
    world.plane_colliders.append(PlaneCollider())
    for index, point in enumerate(points):
        is_pinned = index in pinned
        world.particles.append(SimulationParticle(
            point,
            inverse_mass=0.0 if is_pinned else 1.0,
            radius=float(particle_radius),
            material=material,
            phase="cloth",
            pinned=is_pinned,
        ))
    edges: set[tuple[int, int]] = set()
    diagonal_edges: set[tuple[int, int]] = set()
    edge_faces: dict[tuple[int, int], list[tuple[int, ...]]] = {}
    for face in polygons:
        for offset, first in enumerate(face):
            second = face[(offset + 1) % len(face)]
            edge = tuple(sorted((first, second)))
            edges.add(edge)
            edge_faces.setdefault(edge, []).append(face)
        if len(face) == 4:
            diagonal_edges.add(tuple(sorted((face[0], face[2]))))
            diagonal_edges.add(tuple(sorted((face[1], face[3]))))

    def add(edge: tuple[int, int], compliance: float, kind: str) -> None:
        first, second = edge
        axis = _fabric_axis(texture_coordinates, first, second, kind)
        world.constraints.append(DistanceConstraint(
            first, second, _length(_subtract(points[second], points[first])),
            _fabric_compliance(preset, axis, compliance, bend=kind == "bend"), kind,
            break_threshold=float(tear_threshold),
            material_axis=axis,
        ))

    for edge in sorted(edges):
        add(edge, preset.stretch_compliance, "stretch")
    for edge in sorted(diagonal_edges - edges):
        add(edge, preset.stretch_compliance, "shear")
    bend_edges = set()
    for shared_edge, adjacent_faces in edge_faces.items():
        if len(adjacent_faces) != 2:
            continue
        opposite = []
        for face in adjacent_faces:
            candidates = [index for index in face if index not in shared_edge]
            if candidates:
                opposite.append(candidates[0])
        if len(opposite) == 2 and opposite[0] != opposite[1]:
            bend_edges.add(tuple(sorted(opposite)))
    for edge in sorted(bend_edges - edges - diagonal_edges):
        add(edge, preset.bend_compliance, "bend")
    _add_surface_area_constraints(
        world,
        compliance=max(1.0e-8, preset.stretch_compliance),
        break_threshold=float(tear_threshold) ** 2 if tear_threshold > 0.0 else 0.0,
    )
    from tech_connector.game_engine.runtime.tc_cloth_authoring_service import configure_cloth_quality
    configure_cloth_quality(world, "realtime")
    return world


def create_soft_body_from_geometry(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
    *,
    material: str = "jello",
    pinned_vertices: Iterable[int] = (),
    volume_compliance: float = 2.0e-7,
) -> SimulationWorld:
    world = create_cloth_from_geometry(
        vertices,
        faces,
        material=material,
        pinned_vertices=pinned_vertices,
        particle_radius=0.025,
    )
    triangles = _triangulate_polygons(world.surface_faces)
    rest_volume = _signed_mesh_volume([particle.position for particle in world.particles], triangles)
    if abs(rest_volume) <= 1.0e-9:
        raise ValueError("Jello conversion requires a closed, consistently oriented volume mesh.")
    for particle in world.particles:
        particle.phase = "softbody"
    # Cloth conversion supplies the shared surface topology, but soft bodies use
    # their own volume quality budget rather than cloth's thin-shell adaptation.
    world.scale.adaptive_substeps = False
    world.cloth_settings = {}
    world.volume_constraints.append(VolumeConstraint(
        list(range(len(world.particles))), triangles, rest_volume,
        compliance=float(volume_compliance), pressure=1.0,
    ))
    world.substeps = max(world.substeps, 8)
    world.constraint_iterations = max(world.constraint_iterations, 18)
    return world


def create_breakable_solid_from_geometry(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
    *,
    material: str = "glass",
) -> SimulationWorld:
    if material == "glass":
        return _create_glass_shards(vertices, faces)
    threshold = 1.025 if material == "glass" else 1.35
    world = create_soft_body_from_geometry(vertices, faces, material=material, volume_compliance=0.0)
    for particle in world.particles:
        particle.phase = "rigid_cluster"
    for constraint in world.constraints:
        constraint.break_threshold = threshold
    for constraint in world.area_constraints:
        constraint.break_threshold = threshold * threshold
    return world


def _create_glass_shards(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
) -> SimulationWorld:
    points = [tuple(float(value) for value in point[:3]) for point in vertices]
    polygons = [tuple(int(index) for index in face) for face in faces]
    if not points or not polygons or any(len(face) < 3 or min(face) < 0 or max(face) >= len(points) for face in polygons):
        raise ValueError("Glass conversion requires valid polygon geometry.")
    diagonal = _length(tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ))
    bond_distance = max(1.0e-4, diagonal * 0.018)
    world = SimulationWorld(substeps=8, constraint_iterations=16, self_collision=False)
    world.plane_colliders.append(PlaneCollider())
    source_duplicates: dict[int, list[int]] = {}
    for face in polygons:
        shard = []
        for source_index in face:
            duplicate = len(world.particles)
            shard.append(duplicate)
            source_duplicates.setdefault(source_index, []).append(duplicate)
            world.particles.append(SimulationParticle(
                points[source_index], radius=max(0.005, diagonal * 0.004),
                material="glass", phase="rigid_cluster", state="solid",
            ))
        world.surface_faces.append(tuple(shard))
        for offset, first in enumerate(shard):
            for second in shard[offset + 1:]:
                world.constraints.append(DistanceConstraint(
                    first, second,
                    _length(_subtract(world.particles[second].position, world.particles[first].position)),
                    compliance=0.0,
                    constraint_type="shard_rigidity",
                ))
    _add_surface_area_constraints(world, compliance=0.0)
    for duplicates in source_duplicates.values():
        anchor = duplicates[0]
        for duplicate in duplicates[1:]:
            world.constraints.append(DistanceConstraint(
                anchor, duplicate, 0.0,
                compliance=0.0,
                constraint_type="fracture_bond",
                break_distance=bond_distance,
            ))
    return world


def create_fluid_from_geometry(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
    *,
    material: str = "soup",
    spacing: float = 0.08,
    max_particles: int = 20000,
) -> SimulationWorld:
    points = [tuple(float(value) for value in point[:3]) for point in vertices]
    polygons = [tuple(int(index) for index in face) for face in faces]
    triangles = _triangulate_polygons(polygons)
    if not points or not triangles:
        raise ValueError("Soup conversion requires a closed polygon mesh.")
    minimum = tuple(min(point[axis] for point in points) for axis in range(3))
    maximum = tuple(max(point[axis] for point in points) for axis in range(3))
    world = SimulationWorld(substeps=8, constraint_iterations=5)
    world.plane_colliders.append(PlaneCollider())
    z = minimum[2] + spacing * 0.5
    while z < maximum[2]:
        y = minimum[1] + spacing * 0.5
        while y < maximum[1]:
            x = minimum[0] + spacing * 0.5
            while x < maximum[0]:
                sample = (x, y, z)
                if _point_inside_closed_mesh(sample, points, triangles):
                    reformable = material == "playdoh"
                    world.particles.append(SimulationParticle(
                        sample,
                        radius=spacing * 0.42,
                        material=material,
                        phase="reformable" if reformable else "fluid",
                        state="plastic" if reformable else "liquid",
                        temperature=MATERIAL_PRESETS.get(material, MATERIAL_PRESETS["soup"]).temperature,
                    ))
                    if len(world.particles) >= max_particles:
                        return world
                x += spacing
            y += spacing
        z += spacing
    if not world.particles:
        raise ValueError("No interior fluid samples were found; verify that the source mesh is closed and consistently scaled.")
    return world


def create_reformable_dough_from_geometry(
    vertices: Iterable[Vec3],
    faces: Iterable[tuple[int, ...]],
    *,
    spacing: float = 0.08,
    max_particles: int = 12000,
    material: str = "playdoh",
) -> SimulationWorld:
    world = create_fluid_from_geometry(
        vertices, faces, material=material,
        spacing=float(spacing), max_particles=int(max_particles),
    )
    world.substeps = max(world.substeps, 7)
    world.constraint_iterations = max(world.constraint_iterations, 10)
    world.reformable_settings[material] = {
        "bond_distance": float(spacing) * 1.48,
        "heal_distance": float(spacing) * 1.16,
        "max_neighbors": 18.0,
        "max_heal_speed": 1.5,
        "compliance": 8.0e-6,
        "break_threshold": 1.58,
        "plastic_yield": 0.075,
        "plastic_creep": 5.0,
    }
    world._update_reformable_bonds()
    if not world.constraints:
        raise ValueError("The source volume is too thin for reformable dough at this particle spacing.")
    return world


def create_particle_block(
    dimensions: tuple[int, int, int] = (8, 8, 8),
    *,
    spacing: float = 0.07,
    origin: Vec3 = (-0.25, 0.2, -0.25),
    material: str = "water",
) -> SimulationWorld:
    world = SimulationWorld(substeps=8, constraint_iterations=5)
    world.plane_colliders.append(PlaneCollider())
    for y in range(max(1, dimensions[1])):
        for z in range(max(1, dimensions[2])):
            for x in range(max(1, dimensions[0])):
                world.particles.append(SimulationParticle(
                    (origin[0] + x * spacing, origin[1] + y * spacing, origin[2] + z * spacing),
                    radius=spacing * 0.42,
                    material=material,
                    phase="reformable" if material == "playdoh" else ("fluid" if material in {"water", "goo", "gravy", "soup"} else "particle"),
                    state="plastic" if material == "playdoh" else ("liquid" if material in {"water", "goo", "gravy", "soup"} else "solid"),
                    temperature=MATERIAL_PRESETS.get(material, MATERIAL_PRESETS["water"]).temperature,
                ))
    return world


def create_sparse_fire_volume(*, plasma: bool = False) -> SimulationWorld:
    world = SimulationWorld(fields=[])
    volume = SparseVolume(voxel_size=0.08, dissipation=0.04 if plasma else 0.12, cooling=0.08 if plasma else 0.3, buoyancy=1.8)
    for x in range(-2, 3):
        for z in range(-2, 3):
            volume.cells[(x, 0, z)] = SparseVolumeCell(
                density=0.3,
                temperature=8000.0 if plasma else 1100.0,
                fuel=1.0,
                flame=0.8,
                emission=4.0 if plasma else 1.0,
            )
    world.volumes["plasma" if plasma else "fire"] = volume
    return world


def attach_particles(
    world: SimulationWorld,
    particle_indices: Iterable[int],
    *,
    compliance: float = 0.0,
    break_threshold: float = 0.0,
) -> list[int]:
    created = []
    for particle_index in sorted(set(int(value) for value in particle_indices)):
        if not 0 <= particle_index < len(world.particles):
            raise IndexError(f"Attachment references missing particle {particle_index}.")
        world.attachments.append(AttachmentConstraint(
            particle_index,
            world.particles[particle_index].position,
            compliance=float(compliance),
            break_threshold=float(break_threshold),
        ))
        created.append(len(world.attachments) - 1)
    return created


def _add(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] + second[index] for index in range(3))


def _subtract(first: Vec3, second: Vec3) -> Vec3:
    return tuple(first[index] - second[index] for index in range(3))


def _scale(value: Vec3, amount: float) -> Vec3:
    return tuple(component * amount for component in value)


def _dot(first: Vec3, second: Vec3) -> float:
    return sum(first[index] * second[index] for index in range(3))


def _cross(first: Vec3, second: Vec3) -> Vec3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _length(value: Vec3) -> float:
    return math.sqrt(_dot(value, value))


def _normalize(value: Vec3, fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    length = _length(value)
    return _scale(value, 1.0 / length) if length > 1.0e-12 else fallback


def _signed_dihedral_angle(edge_first: Vec3, edge_second: Vec3,
                           opposite_first: Vec3, opposite_second: Vec3) -> float:
    direction = _normalize(_subtract(edge_second, edge_first), (1.0, 0.0, 0.0))
    first_normal = _normalize(
        _cross(_subtract(edge_second, edge_first), _subtract(opposite_first, edge_first)),
        (0.0, 1.0, 0.0),
    )
    second_normal = _normalize(
        _cross(_subtract(opposite_second, edge_first), _subtract(edge_second, edge_first)),
        first_normal,
    )
    return math.atan2(_dot(_cross(first_normal, second_normal), direction), _dot(first_normal, second_normal))


def _wrapped_angle(value: float) -> float:
    return (float(value) + math.pi) % (2.0 * math.pi) - math.pi


def _rotate_about_axis(point: Vec3, origin: Vec3, axis: Vec3, angle: float) -> Vec3:
    relative = _subtract(point, origin)
    cosine, sine = math.cos(float(angle)), math.sin(float(angle))
    rotated = _add(
        _add(_scale(relative, cosine), _scale(_cross(axis, relative), sine)),
        _scale(axis, _dot(axis, relative) * (1.0 - cosine)),
    )
    return _add(origin, rotated)


def _friction_velocity(velocity: Vec3, normal: Vec3, friction: float, restitution: float) -> Vec3:
    normal_speed = _dot(velocity, normal)
    normal_velocity = _scale(normal, normal_speed)
    tangent = _subtract(velocity, normal_velocity)
    reflected_normal = _scale(normal_velocity, -max(0.0, restitution) if normal_speed < 0.0 else 1.0)
    return _add(reflected_normal, _scale(tangent, max(0.0, 1.0 - friction)))


def _fabric_axis(
    uvs: list[tuple[float, float]], first: int, second: int, kind: str
) -> str:
    if kind == "bend":
        return "isotropic"
    if not uvs:
        return "isotropic"
    delta_u = abs(uvs[second][0] - uvs[first][0])
    delta_v = abs(uvs[second][1] - uvs[first][1])
    maximum = max(delta_u, delta_v, 1.0e-12)
    if min(delta_u, delta_v) / maximum > 0.35:
        return "bias"
    return "warp" if delta_u >= delta_v else "weft"


def _fabric_compliance(
    material: SimulationMaterial,
    axis: str,
    fallback: float,
    *,
    bend: bool = False,
) -> float:
    if bend:
        value = material.warp_bend_compliance if axis == "warp" else material.weft_bend_compliance
        return float(value if value >= 0.0 else fallback)
    value = {
        "warp": material.warp_compliance,
        "weft": material.weft_compliance,
        "bias": material.bias_compliance,
    }.get(axis, -1.0)
    return float(value if value >= 0.0 else fallback)


def _triangulate_polygons(faces: Iterable[tuple[int, ...]]) -> list[tuple[int, int, int]]:
    triangles = []
    for face in faces:
        if len(face) < 3:
            continue
        triangles.extend((int(face[0]), int(face[index]), int(face[index + 1])) for index in range(1, len(face) - 1))
    return triangles


def _add_surface_area_constraints(
    world: SimulationWorld,
    *,
    compliance: float,
    break_threshold: float = 0.0,
) -> None:
    for first, second, third in _triangulate_polygons(world.surface_faces):
        a, b, c = (world.particles[index].position for index in (first, second, third))
        area = 0.5 * _length(_cross(_subtract(b, a), _subtract(c, a)))
        if area > 1.0e-12:
            world.area_constraints.append(AreaConstraint(
                first, second, third, area,
                compliance=float(compliance),
                break_threshold=float(break_threshold),
            ))


def signed_mesh_volume(vertices: Iterable[Vec3], faces: Iterable[tuple[int, ...]]) -> float:
    """Return oriented closed-mesh volume for validation and solver diagnostics."""
    points = [tuple(float(value) for value in point[:3]) for point in vertices]
    return _signed_mesh_volume(points, _triangulate_polygons(faces))


def _signed_mesh_volume(vertices: list[Vec3], faces: Iterable[tuple[int, int, int]]) -> float:
    volume = 0.0
    for first, second, third in faces:
        if min(first, second, third) < 0 or max(first, second, third) >= len(vertices):
            continue
        volume += _dot(vertices[first], _cross(vertices[second], vertices[third])) / 6.0
    return volume


def _point_inside_closed_mesh(point: Vec3, vertices: list[Vec3], faces: Iterable[tuple[int, int, int]]) -> bool:
    # A skew ray avoids the common vertex/edge degeneracies of an axis-aligned cast.
    direction = _normalize((1.0, 0.371390676, 0.173205081), (1.0, 0.0, 0.0))
    intersections = 0
    for first, second, third in faces:
        if min(first, second, third) < 0 or max(first, second, third) >= len(vertices):
            continue
        distance = _ray_triangle_distance(point, direction, vertices[first], vertices[second], vertices[third])
        if distance is not None and distance > 1.0e-8:
            intersections += 1
    return intersections % 2 == 1


def _ray_triangle_distance(origin: Vec3, direction: Vec3, first: Vec3, second: Vec3, third: Vec3) -> float | None:
    edge_one = _subtract(second, first)
    edge_two = _subtract(third, first)
    cross_value = _cross(direction, edge_two)
    determinant = _dot(edge_one, cross_value)
    if abs(determinant) <= 1.0e-10:
        return None
    inverse = 1.0 / determinant
    offset = _subtract(origin, first)
    u = inverse * _dot(offset, cross_value)
    if u < -1.0e-9 or u > 1.0 + 1.0e-9:
        return None
    q = _cross(offset, edge_one)
    v = inverse * _dot(direction, q)
    if v < -1.0e-9 or u + v > 1.0 + 1.0e-9:
        return None
    return inverse * _dot(edge_two, q)


def _closest_point_on_triangle(point: Vec3, first: Vec3, second: Vec3, third: Vec3) -> Vec3:
    ab, ac, ap = _subtract(second, first), _subtract(third, first), _subtract(point, first)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return first
    bp = _subtract(point, second)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return second
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return _add(first, _scale(ab, d1 / max(1.0e-12, d1 - d3)))
    cp = _subtract(point, third)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return third
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return _add(first, _scale(ac, d2 / max(1.0e-12, d2 - d6)))
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        amount = (d4 - d3) / max(1.0e-12, (d4 - d3) + (d5 - d6))
        return _add(second, _scale(_subtract(third, second), amount))
    denominator = max(1.0e-12, va + vb + vc)
    v, w = vb / denominator, vc / denominator
    return _add(first, _add(_scale(ab, v), _scale(ac, w)))

