"""Production cloth setup, paint maps, seams, diagnostics, and interchange."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Mapping, Sequence

from tech_connector.game_engine.runtime.tc_simulation_service import (
    AttachmentConstraint, DihedralBendingConstraint, DistanceConstraint,
)


@dataclass(frozen=True)
class ClothQualityProfile:
    profile_id: str
    label: str
    substeps: int
    constraint_iterations: int
    self_collision: bool
    adaptive_substeps: bool
    wrinkle_lod: int
    description: str


CLOTH_QUALITY_PROFILES: dict[str, ClothQualityProfile] = {
    "preview": ClothQualityProfile("preview", "Preview", 3, 6, False, True, 0, "Fast layout and animation blocking."),
    "realtime": ClothQualityProfile("realtime", "Realtime", 5, 12, True, True, 1, "Stable interactive character cloth."),
    "hero": ClothQualityProfile("hero", "Hero", 8, 20, True, True, 2, "Close-up folds, layered garments, and reliable contact."),
    "cinematic": ClothQualityProfile("cinematic", "Cinematic", 12, 32, True, False, 3, "Maximum deterministic offline quality."),
}


@dataclass(frozen=True)
class ClothPropertyMaps:
    # Bone skin weights are intentionally not stored here. They remain on the
    # imported skeletal mesh/skin binding. These maps only control the cloth
    # layer evaluated after skeletal deformation.
    skin_simulation: tuple[float, ...] = ()
    animation_drive: tuple[float, ...] = ()
    max_distance: tuple[float, ...] = ()
    backstop_distance: tuple[float, ...] = ()
    backstop_radius: tuple[float, ...] = ()
    pin: tuple[float, ...] = ()
    mass_scale: tuple[float, ...] = ()
    stretch_stiffness: tuple[float, ...] = ()
    bend_stiffness: tuple[float, ...] = ()
    collision_thickness: tuple[float, ...] = ()
    drag: tuple[float, ...] = ()


def configure_cloth_quality(world: Any, profile_id: str = "realtime", *,
                            collision_thickness_scale: float = 1.0,
                            strain_warning: float = 1.15) -> dict[str, Any]:
    """Apply one coherent quality profile without changing cloth topology."""
    key = str(profile_id).strip().lower()
    if key not in CLOTH_QUALITY_PROFILES:
        raise KeyError(f"Unknown cloth quality profile: {profile_id}")
    if collision_thickness_scale <= 0.0:
        raise ValueError("Cloth collision thickness scale must be greater than zero.")
    if strain_warning <= 1.0:
        raise ValueError("Cloth strain warning must be greater than one.")
    profile = CLOTH_QUALITY_PROFILES[key]
    world.substeps = profile.substeps
    world.constraint_iterations = profile.constraint_iterations
    world.self_collision = profile.self_collision
    world.scale.adaptive_substeps = profile.adaptive_substeps
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    settings.update({
        "schema": "tech_connector.cloth_authoring.v2",
        "quality_profile": key,
        "collision_thickness_scale": float(collision_thickness_scale),
        "strain_warning": float(strain_warning),
        "wrinkle_lod": profile.wrinkle_lod,
        "dihedral_iterations_per_substep": 8 if key == "cinematic" else 4 if key == "hero" else 0,
        "deterministic": True,
        "canonical_surface_preserved": True,
    })
    world.cloth_settings = settings
    if key in {"hero", "cinematic"}:
        settings["exclude_topological_neighbors"] = True
        world.cloth_settings = settings
        enable_dihedral_bending(world)
        strain_limit = 1.12 if key == "hero" else 1.08
        for constraint in world.constraints:
            if constraint.constraint_type in {"stretch", "shear", "seam"}:
                constraint.strain_limit = strain_limit
    else:
        settings["exclude_topological_neighbors"] = False
        world.cloth_settings = settings
        world.bending_constraints.clear()
        for constraint in world.constraints:
            if constraint.constraint_type in {"stretch", "shear", "seam"}:
                constraint.strain_limit = 0.0
    for particle in world.particles:
        if str(getattr(particle, "phase", "")) == "cloth":
            attributes = particle.effect_attributes
            base = float(attributes.setdefault("cloth_base_radius", particle.radius))
            particle.radius = base * float(collision_thickness_scale)
    return cloth_diagnostics(world)


def apply_cloth_property_maps(world: Any, maps: ClothPropertyMaps | Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Apply paintable pin, mass, stiffness, thickness, and drag controls."""
    values = maps if isinstance(maps, ClothPropertyMaps) else ClothPropertyMaps(**{
        key: tuple(float(item) for item in value) for key, value in maps.items()
    })
    count = len(world.particles)
    data = {key: tuple(getattr(values, key)) for key in ClothPropertyMaps.__dataclass_fields__}
    for name, items in data.items():
        if items and len(items) != count:
            raise ValueError(f"Cloth {name} map must match the particle count.")
        normalized_maps = {
            "skin_simulation", "animation_drive", "pin", "stretch_stiffness",
            "bend_stiffness", "collision_thickness", "drag",
        }
        distance_maps = {"max_distance", "backstop_distance", "backstop_radius"}
        if name in normalized_maps and any(not 0.0 <= float(item) <= 1.0 for item in items):
            raise ValueError(f"Cloth {name} values must be between zero and one.")
        if name == "mass_scale" and any(float(item) <= 0.0 for item in items):
            raise ValueError("Cloth mass scale values must be greater than zero.")
        if name in distance_maps and any(float(item) < 0.0 for item in items):
            raise ValueError(f"Cloth {name} values cannot be negative.")

    world.attachments[:] = [item for item in world.attachments if getattr(item, "tag", "") != "cloth_pin_map"]
    simulation = data["skin_simulation"] or (1.0,) * count
    # Simulation influence is the artist-facing inverse of attachment. An
    # explicit pin map remains available for seams and hard authoring masks.
    pin = data["pin"] or tuple(1.0 - float(value) for value in simulation)
    mass_scale = data["mass_scale"] or (1.0,) * count
    collision = data["collision_thickness"] or (1.0,) * count
    drag = data["drag"] or (0.0,) * count
    for index, particle in enumerate(world.particles):
        attributes = particle.effect_attributes
        base_inverse_mass = float(attributes.setdefault("cloth_base_inverse_mass", particle.inverse_mass))
        base_radius = float(attributes.setdefault("cloth_base_radius", particle.radius))
        pin_weight = float(pin[index])
        particle.pinned = pin_weight >= 0.999
        particle.inverse_mass = 0.0 if particle.pinned else base_inverse_mass / float(mass_scale[index])
        particle.radius = base_radius * max(0.05, float(collision[index]))
        attributes["cloth_pin"] = pin_weight
        attributes["cloth_skin_simulation"] = float(simulation[index])
        attributes["cloth_animation_drive"] = float((data["animation_drive"] or (0.0,) * count)[index])
        attributes["cloth_max_distance"] = float((data["max_distance"] or (0.0,) * count)[index])
        attributes["cloth_backstop_distance"] = float((data["backstop_distance"] or (0.0,) * count)[index])
        attributes["cloth_backstop_radius"] = float((data["backstop_radius"] or (0.0,) * count)[index])
        attributes["cloth_mass_scale"] = float(mass_scale[index])
        attributes["cloth_drag"] = float(drag[index])
        attributes["cloth_collision_thickness"] = float(collision[index])
        if 0.0 < pin_weight < 0.999:
            compliance = 2.5e-4 * ((1.0 - pin_weight) / pin_weight) ** 2
            world.attachments.append(AttachmentConstraint(
                index, particle.position, compliance=compliance, tag="cloth_pin_map",
            ))

    _apply_constraint_stiffness(world, data["stretch_stiffness"], {"stretch", "shear", "seam"})
    _apply_constraint_stiffness(world, data["bend_stiffness"], {"bend"})
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    settings["property_maps"] = {name: list(items) for name, items in data.items() if items}
    settings["painted_controls"] = [name for name, items in data.items() if items]
    world.cloth_settings = settings
    return cloth_diagnostics(world)


def create_cloth_seams(world: Any, vertex_pairs: Iterable[Sequence[int]], *,
                       compliance: float = 1.0e-8, break_threshold: float = 0.0) -> list[int]:
    """Create editable sew/weld constraints between garment border vertices."""
    if compliance < 0.0 or break_threshold < 0.0:
        raise ValueError("Cloth seam compliance and break threshold cannot be negative.")
    created: list[int] = []
    seen: set[tuple[int, int]] = set()
    for pair in vertex_pairs:
        if len(pair) != 2:
            raise ValueError("Every cloth seam entry must contain exactly two vertex indices.")
        first, second = int(pair[0]), int(pair[1])
        if first == second or min(first, second) < 0 or max(first, second) >= len(world.particles):
            raise IndexError(f"Invalid cloth seam pair: {(first, second)}")
        edge = tuple(sorted((first, second)))
        if edge in seen:
            continue
        seen.add(edge)
        a, b = world.particles[first].position, world.particles[second].position
        rest = math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))
        world.constraints.append(DistanceConstraint(
            first, second, rest, compliance=float(compliance), constraint_type="seam",
            break_threshold=float(break_threshold), material_axis="seam",
        ))
        created.append(len(world.constraints) - 1)
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    settings["seam_count"] = sum(item.constraint_type == "seam" for item in world.constraints)
    settings["seams_editable"] = True
    world.cloth_settings = settings
    return created


def enable_dihedral_bending(world: Any, *, compliance: float | None = None) -> list[int]:
    """Build true adjacent-triangle angle constraints from the cloth surface."""
    triangles = _triangulate(world.surface_faces)
    edge_faces: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for first, second, third in triangles:
        for edge_first, edge_second, opposite in (
            (first, second, third), (second, third, first), (third, first, second),
        ):
            edge_faces.setdefault(tuple(sorted((edge_first, edge_second))), []).append(
                (edge_first, edge_second, opposite)
            )
    world.bending_constraints.clear()
    for entries in edge_faces.values():
        if len(entries) != 2:
            continue
        edge_first, edge_second, opposite_first = entries[0]
        opposite_second = entries[1][2]
        if opposite_first == opposite_second:
            continue
        rest_angle = _dihedral_angle(
            world.particles[edge_first].position, world.particles[edge_second].position,
            world.particles[opposite_first].position, world.particles[opposite_second].position,
        )
        if compliance is None:
            materials = [world.materials.get(world.particles[index].material) for index in (
                edge_first, edge_second, opposite_first, opposite_second,
            )]
            bend_values = [float(item.bend_compliance) for item in materials if item is not None]
            bend_compliance = sum(bend_values) / max(1, len(bend_values))
        else:
            bend_compliance = float(compliance)
        world.bending_constraints.append(DihedralBendingConstraint(
            edge_first, edge_second, opposite_first, opposite_second,
            rest_angle, compliance=max(0.0, bend_compliance),
        ))
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    settings["dihedral_bending"] = True
    settings["dihedral_constraint_count"] = len(world.bending_constraints)
    world.cloth_settings = settings
    return list(range(len(world.bending_constraints)))


def configure_cloth_collision_layers(
    world: Any,
    layer_indices: Sequence[int],
    *,
    priorities: Sequence[float] = (),
    mode: str = "all",
) -> dict[str, Any]:
    """Assign garment collision layers and resolution priorities per vertex."""
    count = len(world.particles)
    if len(layer_indices) != count or (priorities and len(priorities) != count):
        raise ValueError("Cloth collision layers and priorities must match the particle count.")
    layers = tuple(int(value) for value in layer_indices)
    if any(value < 0 or value > 30 for value in layers):
        raise ValueError("Cloth collision layers must be between zero and 30.")
    priority_values = tuple(float(value) for value in priorities) if priorities else tuple(float(value) for value in layers)
    if any(value < 0.0 for value in priority_values):
        raise ValueError("Cloth collision priorities cannot be negative.")
    collision_mode = str(mode).strip().lower()
    if collision_mode not in {"all", "same_layer", "adjacent_layers"}:
        raise ValueError("Cloth collision layer mode must be all, same_layer, or adjacent_layers.")
    for particle, layer, priority in zip(world.particles, layers, priority_values):
        group = 1 << layer
        if collision_mode == "same_layer":
            mask = group
        elif collision_mode == "adjacent_layers":
            mask = group | (1 << max(0, layer - 1)) | (1 << min(30, layer + 1))
        else:
            mask = -1
        particle.collision_group = group
        particle.collision_mask = mask
        particle.collision_priority = priority
        particle.effect_attributes["cloth_collision_layer"] = layer
        particle.effect_attributes["cloth_collision_priority"] = priority
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    settings.update({
        "collision_layer_mode": collision_mode,
        "collision_layers": sorted(set(layers)),
        "layered_collision": True,
        "exclude_topological_neighbors": True,
    })
    world.cloth_settings = settings
    return cloth_diagnostics(world)


def cloth_diagnostics(world: Any) -> dict[str, Any]:
    cloth_particles = [item for item in world.particles if str(getattr(item, "phase", "")) == "cloth"]
    constraints = [item for item in world.constraints if item.constraint_type in {"stretch", "shear", "bend", "seam"}]
    strains: list[float] = []
    by_type: dict[str, int] = {}
    broken = 0
    for item in constraints:
        by_type[item.constraint_type] = by_type.get(item.constraint_type, 0) + 1
        if not item.enabled:
            broken += 1
            continue
        a, b = world.particles[item.first].position, world.particles[item.second].position
        length = math.sqrt(sum((a[axis] - b[axis]) ** 2 for axis in range(3)))
        strains.append(length / max(1.0e-12, float(item.rest_length)))
    maximum = max(strains, default=1.0)
    rms = math.sqrt(sum((value - 1.0) ** 2 for value in strains) / max(1, len(strains)))
    settings = dict(getattr(world, "cloth_settings", {}) or {})
    warning = float(settings.get("strain_warning", 1.15))
    return {
        "schema": "tech_connector.cloth_diagnostics.v2",
        "particle_count": len(cloth_particles),
        "constraint_count": len(constraints),
        "constraints_by_type": by_type,
        "dihedral_constraints": len(getattr(world, "bending_constraints", ())),
        "dihedral_iterations_per_substep": int(settings.get("dihedral_iterations_per_substep", 0)),
        "pinned_vertices": sum(bool(item.pinned) for item in cloth_particles),
        "soft_pins": sum(getattr(item, "tag", "") == "cloth_pin_map" for item in world.attachments),
        "broken_constraints": broken,
        "maximum_strain": maximum,
        "strain_rms": rms,
        "overstrain_count": sum(value > warning for value in strains),
        "quality_profile": settings.get("quality_profile", "custom"),
        "substeps": int(world.substeps),
        "constraint_iterations": int(world.constraint_iterations),
        "self_collision": bool(world.self_collision),
        "collision_layers": list(settings.get("collision_layers", [])),
        "topological_neighbor_exclusion": bool(settings.get("exclude_topological_neighbors", False)),
        "strain_limit": max((float(item.strain_limit) for item in constraints), default=0.0),
        "status": "warning" if maximum > warning or broken else "healthy",
    }


def cloth_export_contract(destination: str = "portable") -> dict[str, Any]:
    key = str(destination or "portable").strip().lower()
    target = {
        "houdini": "Vellum cloth, attach, weld, and break constraints",
        "unreal": "Chaos Cloth panel/collection properties and skin-weighted attachment",
        "maya": "nCloth properties, component constraints, and cache",
        "blender": "Cloth pin group, sewing springs, collisions, and point cache",
        "unity": "runtime cloth metadata plus skeletal or vertex-cache fallback",
        "usd": "UsdSkel binding plus time-sampled point cache",
        "fbx": "canonical skeletal mesh plus cache sidecar",
        "gltf": "canonical skin plus morph or vertex-cache extension",
        "portable": "TC cloth topology, property maps, seams, and deterministic cache",
    }.get(key, "native cloth reconstruction or deterministic point cache")
    return {
        "schema": "tech_connector.cloth_export.v2", "destination": key,
        "runtime_transfer": target, "canonical_skin_preserved": True,
        "property_maps_preserved": key in {"portable", "houdini", "unreal", "maya", "blender"},
        "fallback_priority": ["native_cloth", "skeletal_proxy", "point_cache", "vertex_animation_texture"],
    }


def cloth_authoring_schema() -> dict[str, Any]:
    return {
        "schema": "tech_connector.cloth_authoring_ui.v2",
        "quality_profiles": {key: asdict(value) for key, value in CLOTH_QUALITY_PROFILES.items()},
        "property_maps": {
            "skin_simulation": "Blend from imported skeletal deformation to cloth simulation",
            "animation_drive": "How strongly simulated vertices chase the animated skin target",
            "max_distance": "Maximum distance from the animated skin target",
            "backstop_distance": "Collision backstop offset from the animated surface",
            "backstop_radius": "Collision backstop radius around the animated surface",
            "pin": "Hard and soft animated attachment",
            "mass_scale": "Per-vertex inertia",
            "stretch_stiffness": "Warp/weft/shear resistance",
            "bend_stiffness": "Fold and wrinkle resistance",
            "collision_thickness": "Per-vertex contact envelope",
            "drag": "Per-vertex aerodynamic response",
        },
        "tools": ["paint_properties", "sew_edges", "tear_seams", "dihedral_bending", "collision_layers", "strain_heatmap", "collision_heatmap", "cache_and_compare"],
        "diagnostics": ["maximum_strain", "strain_rms", "overstrain_count", "broken_constraints", "soft_pins"],
    }


def _apply_constraint_stiffness(world: Any, paint: tuple[float, ...], kinds: set[str]) -> None:
    if not paint:
        return
    for item in world.constraints:
        if item.constraint_type not in kinds:
            continue
        base = float(getattr(item, "_cloth_base_compliance", item.compliance))
        item._cloth_base_compliance = base
        strength = 0.5 * (float(paint[item.first]) + float(paint[item.second]))
        item.compliance = max(base, 1.0e-9) / max(0.0025, strength * strength)


def _triangulate(faces: Iterable[Sequence[int]]) -> list[tuple[int, int, int]]:
    triangles: list[tuple[int, int, int]] = []
    for face in faces:
        values = tuple(int(index) for index in face)
        triangles.extend((values[0], values[index], values[index + 1]) for index in range(1, len(values) - 1))
    return triangles


def _dihedral_angle(edge_first, edge_second, opposite_first, opposite_second) -> float:
    subtract = lambda a, b: tuple(a[axis] - b[axis] for axis in range(3))
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = lambda a, b: sum(a[axis] * b[axis] for axis in range(3))
    normalize = lambda value: tuple(item / max(1.0e-12, math.sqrt(dot(value, value))) for item in value)
    edge = normalize(subtract(edge_second, edge_first))
    first_normal = normalize(cross(subtract(edge_second, edge_first), subtract(opposite_first, edge_first)))
    second_normal = normalize(cross(subtract(opposite_second, edge_first), subtract(edge_second, edge_first)))
    return math.atan2(dot(cross(first_normal, second_normal), edge), dot(first_normal, second_normal))


__all__ = [
    "CLOTH_QUALITY_PROFILES", "ClothPropertyMaps", "ClothQualityProfile",
    "apply_cloth_property_maps", "cloth_authoring_schema", "cloth_diagnostics",
    "cloth_export_contract", "configure_cloth_quality", "create_cloth_seams",
    "configure_cloth_collision_layers", "enable_dihedral_bending",
]
