"""Destination-aware live and baked handoff plans for TC simulation worlds."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from tech_connector.game_engine.runtime.tc_simulation_service import SimulationCache, SimulationWorld


@dataclass(frozen=True)
class SimulationArtifact:
    role: str
    format: str
    destination_feature: str
    live: bool = False
    required: bool = True


@dataclass
class SimulationTransferManifest:
    target: str
    simulation_types: list[str]
    artifacts: list[SimulationArtifact]
    validation: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.sim_transfer.v1",
            "target": self.target,
            "simulation_types": list(self.simulation_types),
            "artifacts": [asdict(item) for item in self.artifacts],
            "validation": list(self.validation),
            "metadata": dict(self.metadata),
        }


LIVE_TARGETS = {
    "houdini": {"cloth": "Vellum", "softbody": "Vellum Softbody", "fluid": "FLIP/Vellum Fluid", "volume": "Sparse Pyro", "particle": "POP", "rigid": "RBD/Bullet"},
    "unreal": {"cloth": "Chaos Cloth", "fluid": "Niagara Fluids", "volume": "Niagara Fluids/VDB", "particle": "Niagara", "rigid": "Chaos Physics"},
    "unity": {"cloth": "Unity Cloth", "fluid": "VFX Graph/custom fluid package", "volume": "VFX Graph/VDB package", "particle": "VFX Graph", "rigid": "PhysX"},
    "maya": {"cloth": "nCloth", "fluid": "Bifrost Aero/MPM", "volume": "Bifrost Aero", "particle": "Bifrost/nParticles", "rigid": "Bullet"},
    "blender": {"cloth": "Cloth", "fluid": "Mantaflow Liquid", "volume": "Mantaflow Gas/OpenVDB", "particle": "Particle/Geometry Nodes", "rigid": "Rigid Body World"},
}

EMISSION_SOURCE_BINDINGS = {
    "houdini": "point/vertex emit attribute for POP, FLIP, or Pyro sourcing",
    "unreal": "Niagara mesh sampling density attribute or baked mask texture",
    "unity": "VFX Graph mesh sampling attribute or baked mask texture",
    "maya": "Bifrost source-property field or per-vertex color set",
    "blender": "Geometry Nodes named emission-density attribute",
}


def build_simulation_transfer_manifest(
    world: SimulationWorld,
    cache: SimulationCache,
    target: str,
    *,
    prefer_live: bool = True,
) -> SimulationTransferManifest:
    from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world

    target_key = str(target or "generic").strip().lower()
    profile_name = str(getattr(getattr(world, "effect_system", None), "quality", "realtime") or "realtime")
    if profile_name not in {"cinematic", "photoreal", "realtime", "mobile", "toony", "stylized", "retro"}:
        profile_name = "realtime"
    compiled_ir = compile_simulation_world(world, profile=profile_name)
    types = _simulation_types(world)
    artifacts = [
        SimulationArtifact("source", "tcfx.json", "Tech Connector editable simulation", live=True),
        SimulationArtifact("tc_runtime", "tcfx.runtime.json", "TC headless fixed-step game runtime", live=True),
    ]
    live_features = LIVE_TARGETS.get(target_key, {})
    if prefer_live:
        for simulation_type in types:
            feature = live_features.get(simulation_type)
            if feature:
                artifacts.append(SimulationArtifact(f"live_{simulation_type}", "tcfx.intent", feature, live=True, required=False))
    if "volume" in types:
        artifacts.append(SimulationArtifact("volume_cache", "openvdb", live_features.get("volume", "OpenVDB volume playback")))
    if "fluid" in types or "particle" in types:
        artifacts.append(SimulationArtifact("point_cache", "usd", live_features.get("particle", "USD Points/PointInstancer")))
    if "cloth" in types or "softbody" in types or "rigid" in types:
        artifacts.append(SimulationArtifact("geometry_cache", "alembic", "Alembic Geometry Cache"))
        artifacts.append(SimulationArtifact("vertex_animation", "vat", "Vertex Animation Texture", required=False))
    artifacts.append(SimulationArtifact("timeline", "tcfx.cache.json", "Deterministic TC cache receipt"))
    if world.effect_system is not None:
        artifacts.append(SimulationArtifact("effect_graph", "tcfx.effect.json", "Editable modular effect graph", live=True))
        artifacts.append(SimulationArtifact("effect_fallback", "flipbook", "Flipbook or sprite-sheet fallback", required=False))
    if world.deformable_surfaces:
        artifacts.append(SimulationArtifact("surface_deformation", "usd", "Heightfield, contact, and penetration cache"))
    return SimulationTransferManifest(
        target_key,
        types,
        artifacts,
        [
            "frame range and frame rate match the source cache",
            "centimeter scale and source up-axis are declared",
            "particle and vertex counts match every cached frame or carry topology-change receipts",
            "quad collision/emitter source topology remains preserved",
            "destination import readback validates bounds and timing",
            "compiled TC simulation IR validates before target conversion",
        ],
        {
            "frame_rate": cache.frame_rate,
            "frame_count": len(cache.frames),
            "substeps": world.substeps,
            "constraint_iterations": world.constraint_iterations,
            "prefer_live": bool(prefer_live),
            "surface_face_count": len(world.surface_faces),
            "quad_surface_face_count": sum(1 for face in world.surface_faces if len(face) == 4),
            "mesh_collider_quad_count": sum(
                1 for collider in world.mesh_colliders for face in collider.faces if len(face) == 4
            ),
            "area_constraint_count": len(world.area_constraints),
            "volume_constraint_count": len(world.volume_constraints),
            "reformable_bond_count": sum(1 for constraint in world.constraints if constraint.reformable),
            "broken_reformable_bond_count": sum(
                1 for constraint in world.constraints if constraint.reformable and not constraint.enabled
            ),
            "material_states": sorted({particle.state for particle in world.particles}),
            "effect_system": world.effect_system.to_dict() if world.effect_system is not None else None,
            "deformable_surface_count": len(world.deformable_surfaces),
            "surface_mark_count": sum(len(surface.marks) for surface in world.deformable_surfaces),
            "geometry_emitter_sources": [
                {
                    "name": emitter.source_map_name,
                    "revision": emitter.source_map_revision,
                    "vertex_count": len(emitter.vertices),
                    "painted_vertex_count": sum(1 for value in emitter.source_weights if value > 1.0e-8),
                    "source_weights": list(emitter.source_weights),
                    "semantics": "0 = no emission, 1 = full emission density",
                    "destination_binding": EMISSION_SOURCE_BINDINGS.get(
                        target_key, "portable vertex attribute plus baked mask texture"
                    ),
                }
                for emitter in world.emitters
                if emitter.source_weights
            ],
            "compiled_ir": {
                "schema": "tech_connector.simulation_ir.v1",
                "profile": compiled_ir.profile.name,
                "backend": compiled_ir.backend.backend_id,
                "domains": list(compiled_ir.domains),
                "stage_ids": [stage.stage_id for stage in compiled_ir.stages],
                "outputs": list(compiled_ir.outputs),
                "diagnostics": list(compiled_ir.diagnostics),
            },
            "runtime_contract": {
                "schema": "tech_connector.runtime_simulation_asset.v1",
                "requires_editor": False,
                "fixed_step": True,
                "rollback_checkpoints": True,
                "interpolated_render_streams": True,
                "deterministic_parameter_commands": True,
                "event_streams": True,
                "backend": compiled_ir.backend.backend_id,
            },
        },
    )


def _simulation_types(world: SimulationWorld) -> list[str]:
    types = set()
    phases = {particle.phase for particle in world.particles}
    materials = {particle.material for particle in world.particles}
    if "cloth" in phases:
        types.add("cloth")
    if "fluid" in phases:
        types.add("fluid")
    if phases.intersection({"softbody", "reformable"}):
        types.add("softbody")
    if "rigid_cluster" in phases or materials.intersection({"glass", "metal"}):
        types.add("rigid")
    if phases - {"cloth", "fluid", "softbody", "reformable", "rigid_cluster"} or world.emitters:
        types.add("particle")
    if world.volumes:
        types.add("volume")
    if world.effect_system is not None:
        types.add("effect")
    if world.deformable_surfaces:
        types.add("surface")
    return sorted(types)

