"""Production workflow contracts shared by Tech Connector FX tools.

The workflow layer deliberately describes authoring intent separately from a
particular solver implementation.  A host can therefore present the same
controls, stages, performance target, and fallback explanation whether the
effect is previewed by the reference solver, a native CPU plugin, or a GPU
executor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FxAuthoringControl:
    control_id: str
    label: str
    minimum: float
    maximum: float
    default: float
    unit: str = ""
    help_text: str = ""


@dataclass(frozen=True)
class FxSolverProfile:
    profile_id: str
    name: str
    domain: str
    description: str
    stages: tuple[str, ...]
    controls: tuple[FxAuthoringControl, ...]
    secondary_outputs: tuple[str, ...] = ()
    preferred_backend: str = "gpu_compute"
    supports_stateless: bool = False
    supports_meshing: bool = False


@dataclass
class FxWorkflowStage:
    stage_id: str
    label: str
    state: str = "ready"
    cacheable: bool = False
    optional: bool = False
    detail: str = ""


@dataclass
class FxPerformanceContract:
    target_frame_ms: float = 4.0
    maximum_particles: int = 20_000
    maximum_volume_cells: int = 262_144
    maximum_mesh_vertices: int = 500_000
    adaptive: bool = True
    overflow_policy: str = "reduce_detail"

    def normalized(self) -> "FxPerformanceContract":
        return FxPerformanceContract(
            target_frame_ms=max(0.1, float(self.target_frame_ms)),
            maximum_particles=max(1, int(self.maximum_particles)),
            maximum_volume_cells=max(1, int(self.maximum_volume_cells)),
            maximum_mesh_vertices=max(1, int(self.maximum_mesh_vertices)),
            adaptive=bool(self.adaptive),
            overflow_policy=(
                str(self.overflow_policy)
                if str(self.overflow_policy) in {"reduce_detail", "throttle", "cull", "pause"}
                else "reduce_detail"
            ),
        )


@dataclass
class FxWorkflowPlan:
    solver: FxSolverProfile
    quality: str
    requested_backend: str
    performance: FxPerformanceContract
    stages: list[FxWorkflowStage] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.fx_workflow.v1",
            "solver": asdict(self.solver),
            "quality": self.quality,
            "requested_backend": self.requested_backend,
            "performance": asdict(self.performance.normalized()),
            "stages": [asdict(stage) for stage in self.stages],
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class FxAuditReport:
    status: str
    metrics: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.fx_audit.v1",
            "status": self.status,
            "metrics": dict(self.metrics),
            "diagnostics": list(self.diagnostics),
            "recommendations": list(self.recommendations),
        }


def _control(
    control_id: str,
    label: str,
    minimum: float,
    maximum: float,
    default: float,
    unit: str = "",
    help_text: str = "",
) -> FxAuthoringControl:
    return FxAuthoringControl(control_id, label, minimum, maximum, default, unit, help_text)


FX_SOLVER_PROFILES: dict[str, FxSolverProfile] = {
    "particle_realtime": FxSolverProfile(
        "particle_realtime", "Realtime Particles", "effect",
        "Stage-based particles for sparks, weather, trails, impacts, and stylized FX.",
        ("author", "simulate", "render", "cache"),
        (
            _control("spawn_scale", "Spawn density", 0.0, 4.0, 1.0, "x"),
            _control("drag", "Drag", 0.0, 20.0, 0.1),
            _control("turbulence", "Turbulence", 0.0, 10.0, 0.5),
        ),
        supports_stateless=True,
    ),
    "flip_liquid": FxSolverProfile(
        "flip_liquid", "FLIP Liquid", "fluid",
        "Particle/grid liquid for pouring, splashes, tanks, rivers, and interaction regions.",
        ("source", "simulate", "secondary", "surface", "cache", "export"),
        (
            _control("viscosity", "Viscosity", 0.0, 10.0, 0.02),
            _control("surface_tension", "Surface tension", 0.0, 2.0, 0.07),
            _control("particle_separation", "Particle separation", 0.002, 1.0, 0.05, "scene units"),
        ),
        ("splash", "foam", "bubbles", "mist"), supports_meshing=True,
    ),
    "viscous_goop": FxSolverProfile(
        "viscous_goop", "Viscous / Goop", "fluid",
        "Cohesive and adhesive matter for honey, slime, mud, lava, and stringy fluids.",
        ("source", "simulate", "surface", "cache", "export"),
        (
            _control("viscosity", "Viscosity", 0.0, 100.0, 0.75),
            _control("cohesion", "Cohesion", 0.0, 2.0, 0.45),
            _control("adhesion", "Surface adhesion", 0.0, 2.0, 0.35),
            _control("yield", "Yield strength", 0.0, 10.0, 0.2),
            _control("stringiness", "Stringiness", 0.0, 1.0, 0.5),
        ),
        supports_meshing=True,
    ),
    "granular": FxSolverProfile(
        "granular", "Granular Matter", "particle",
        "Sand, snow, soil, grains, and packed particle materials.",
        ("source", "simulate", "surface", "cache", "export"),
        (
            _control("friction", "Internal friction", 0.0, 2.0, 0.55),
            _control("cohesion", "Cohesion", 0.0, 2.0, 0.08),
            _control("packing", "Packing", 0.1, 1.0, 0.65),
        ),
    ),
    "softbody": FxSolverProfile(
        "softbody", "Soft Body / Jello", "softbody",
        "Constraint-based cloth, rubber, inflatables, jello, and reformable matter.",
        ("constraints", "simulate", "inspect", "cache", "export"),
        (
            _control("stiffness", "Stiffness", 0.0, 1.0, 0.65),
            _control("damping", "Damping", 0.0, 1.0, 0.08),
            _control("pressure", "Internal pressure", 0.0, 10.0, 1.0),
            _control("plasticity", "Plasticity", 0.0, 1.0, 0.0),
            _control("tear_threshold", "Tear threshold", 0.0, 10.0, 0.0),
        ),
    ),
    "destruction": FxSolverProfile(
        "destruction", "Material Destruction", "rigid",
        "Material-aware fracture, constraints, damage propagation, debris, and dust.",
        ("fracture", "constraints", "simulate_proxy", "secondary", "transfer_detail", "cache", "export"),
        (
            _control("fracture_density", "Fracture density", 0.0, 1.0, 0.35),
            _control("bond_strength", "Bond strength", 0.0, 10.0, 1.0),
            _control("damage_spread", "Damage spread", 0.0, 1.0, 0.45),
            _control("deformation", "Pre-break deformation", 0.0, 1.0, 0.1),
        ),
        ("debris", "dust", "sparks"),
    ),
    "sparse_pyro": FxSolverProfile(
        "sparse_pyro", "Sparse Pyro", "volume",
        "Sparse smoke, fire, plasma, and combustion volumes with interactive preview scaling.",
        ("source", "simulate", "shape", "render", "cache", "export"),
        (
            _control("buoyancy", "Buoyancy", -10.0, 10.0, 1.0),
            _control("dissipation", "Dissipation", 0.0, 10.0, 0.15),
            _control("combustion", "Combustion", 0.0, 5.0, 1.0),
            _control("disturbance", "Disturbance", 0.0, 10.0, 0.5),
        ),
    ),
    "ocean_surface": FxSolverProfile(
        "ocean_surface", "Ocean Surface", "surface",
        "Layered spectral ocean with localized interaction, wakes, foam, and spray.",
        ("spectrum", "interaction", "secondary", "surface", "cache", "export"),
        (
            _control("wind_speed", "Wind speed", 0.0, 100.0, 12.0, "m/s"),
            _control("choppiness", "Choppiness", 0.0, 5.0, 1.0),
            _control("fetch", "Fetch", 1.0, 1_000_000.0, 10_000.0, "m"),
            _control("foam_threshold", "Foam threshold", 0.0, 1.0, 0.55),
        ),
        ("foam", "spray", "wake"), supports_meshing=True,
    ),
}


PRESET_SOLVER_PROFILES = {
    "fog": "sparse_pyro", "clouds": "sparse_pyro", "volcano": "sparse_pyro",
    "heat_haze": "sparse_pyro", "mudslide": "viscous_goop",
    "refractive_bubbles": "flip_liquid", "avalanche": "granular",
    "snow": "granular", "earthquake": "destruction",
}


def solver_profile_for_preset(preset: str) -> FxSolverProfile:
    profile_id = PRESET_SOLVER_PROFILES.get(str(preset or "").strip().lower(), "particle_realtime")
    return FX_SOLVER_PROFILES[profile_id]


def build_fx_workflow_plan(
    solver_profile: str,
    *,
    quality: str = "realtime",
    requested_backend: str = "auto",
    performance: FxPerformanceContract | None = None,
) -> FxWorkflowPlan:
    if solver_profile not in FX_SOLVER_PROFILES:
        raise KeyError(f"Unknown FX solver profile: {solver_profile}")
    solver = FX_SOLVER_PROFILES[solver_profile]
    stages = [
        FxWorkflowStage(
            stage_id=stage,
            label=stage.replace("_", " ").title(),
            cacheable=stage in {"simulate", "simulate_proxy", "secondary", "surface", "render"},
            optional=stage in {"secondary", "inspect", "transfer_detail", "export"},
            detail=_stage_detail(stage),
        )
        for stage in solver.stages
    ]
    return FxWorkflowPlan(
        solver=solver,
        quality=str(quality),
        requested_backend=str(requested_backend or "auto"),
        performance=(performance or FxPerformanceContract()).normalized(),
        stages=stages,
    )


def audit_fx_world(world: Any) -> FxAuditReport:
    """Audit solver readiness and budgets without changing the simulation."""
    from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
        effect_system_is_stateless,
        simulation_backend_status,
    )

    system = getattr(world, "effect_system", None)
    if system is None:
        return FxAuditReport(
            "warning", {"particles": len(getattr(world, "particles", ()) or ())},
            [{"severity": "warning", "code": "no_effect_system", "message": "No modular FX system is active."}],
            ["Create or attach an FX system before running the effect audit."],
        )
    contract = FxPerformanceContract(**dict(getattr(system, "performance_contract", {}) or {})).normalized()
    particles = sum(1 for particle in getattr(world, "particles", ()) or () if getattr(particle, "alive", True))
    volume_cells = sum(len(volume.cells) for volume in (getattr(world, "volumes", {}) or {}).values())
    requested = str(getattr(system, "backend_preference", "auto") or "auto")
    backend_id = "gpu_compute" if requested == "auto" else requested
    backend = simulation_backend_status(backend_id)
    diagnostics: list[dict[str, Any]] = []
    recommendations: list[str] = []
    if not backend["available"]:
        diagnostics.append({
            "severity": "warning", "code": "backend_fallback",
            "message": f"{backend_id} is unavailable; deterministic CPU preview will be used.",
        })
        recommendations.append("Install a compatible native/GPU executor to remove the preview fallback.")
    if particles > contract.maximum_particles:
        diagnostics.append({
            "severity": "error", "code": "particle_budget_exceeded",
            "message": f"{particles:,} live particles exceed the {contract.maximum_particles:,} contract.",
        })
        recommendations.append("Reduce spawn density, shorten lifetimes, cull by significance, or raise the contract intentionally.")
    if volume_cells > contract.maximum_volume_cells:
        diagnostics.append({
            "severity": "error", "code": "volume_budget_exceeded",
            "message": f"{volume_cells:,} active cells exceed the {contract.maximum_volume_cells:,} contract.",
        })
        recommendations.append("Use sparse activation, a smaller interaction domain, or lower preview resolution.")
    stateless = effect_system_is_stateless(system)
    if stateless and getattr(system, "solver_profile", "") == "particle_realtime":
        recommendations.append("This system is stateless-compatible; use a stateless executor for the lowest tick and memory cost.")
    status = "error" if any(item["severity"] == "error" for item in diagnostics) else (
        "warning" if diagnostics else "ok"
    )
    return FxAuditReport(status, {
        "particles": particles,
        "particle_budget": contract.maximum_particles,
        "volume_cells": volume_cells,
        "volume_cell_budget": contract.maximum_volume_cells,
        "emitters": len(getattr(system, "emitters", ()) or ()),
        "stateless_compatible": stateless,
        "requested_backend": requested,
        "effective_preview_backend": backend_id if backend["available"] else "reference_cpu",
    }, diagnostics, recommendations)


def _stage_detail(stage: str) -> str:
    return {
        "source": "Emit or initialize simulation matter.",
        "simulate": "Solve motion and material behavior.",
        "simulate_proxy": "Solve an inexpensive proxy representation.",
        "secondary": "Generate foam, spray, debris, dust, bubbles, or mist.",
        "surface": "Convert simulation state into a renderable surface.",
        "transfer_detail": "Transfer proxy motion to production geometry.",
        "cache": "Store resumable, versioned frame data.",
        "export": "Publish host-independent runtime or interchange artifacts.",
        "inspect": "Visualize constraints, contacts, errors, and budget pressure.",
    }.get(stage, "Author and evaluate this workflow stage.")


__all__ = [
    "FX_SOLVER_PROFILES", "PRESET_SOLVER_PROFILES", "FxAuditReport", "FxAuthoringControl",
    "FxPerformanceContract", "FxSolverProfile", "FxWorkflowPlan", "FxWorkflowStage",
    "audit_fx_world", "build_fx_workflow_plan", "solver_profile_for_preset",
]
