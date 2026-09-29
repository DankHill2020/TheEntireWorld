"""Explicit ordered coupling graph for TC simulation domains."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


COUPLING_PHASES = ("pre_solve", "contact", "exchange", "post_solve")


@dataclass(frozen=True)
class MultiphysicsCouplingStage:
    stage_id: str
    source_domain: str
    target_domain: str
    phase: str
    operations: tuple[str, ...]
    execution_backend: str
    fallback_backend: str = ""
    fallback_reason: str = ""
    maximum_pairs: int = 0
    deterministic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultiphysicsCouplingPlan:
    domains: tuple[str, ...]
    stages: tuple[MultiphysicsCouplingStage, ...]
    requested_backend: str
    native_stage_count: int
    fallback_stage_count: int
    maximum_contact_pairs: int

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids: set[str] = set()
        phase_order = {name: index for index, name in enumerate(COUPLING_PHASES)}
        previous_phase = -1
        for stage in self.stages:
            if stage.stage_id in ids:
                errors.append(f"Duplicate coupling stage: {stage.stage_id}")
            ids.add(stage.stage_id)
            if stage.source_domain not in self.domains or stage.target_domain not in self.domains:
                errors.append(f"{stage.stage_id}: coupling references an inactive domain")
            phase = phase_order.get(stage.phase, -1)
            if phase < previous_phase:
                errors.append(f"{stage.stage_id}: coupling phases are not ordered")
            previous_phase = max(previous_phase, phase)
            if stage.maximum_pairs < 0:
                errors.append(f"{stage.stage_id}: maximum_pairs cannot be negative")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.multiphysics_coupling.v1",
            "domains": list(self.domains),
            "stages": [item.to_dict() for item in self.stages],
            "requested_backend": self.requested_backend,
            "native_stage_count": self.native_stage_count,
            "fallback_stage_count": self.fallback_stage_count,
            "maximum_contact_pairs": self.maximum_contact_pairs,
        }


_COUPLINGS = (
    ("field_particle", "particle", "particle", "pre_solve", ("force_accumulation", "drag", "buoyancy")),
    ("field_cloth", "cloth", "cloth", "pre_solve", ("force_accumulation", "aerodynamic_drag")),
    ("field_softbody", "softbody", "softbody", "pre_solve", ("force_accumulation", "buoyancy")),
    ("effect_particle", "effect", "particle", "pre_solve", ("spawn", "event_force", "attribute_write")),
    ("cloth_rigid", "cloth", "rigid", "contact", ("continuous_contact", "friction", "two_way_impulse")),
    ("softbody_rigid", "softbody", "rigid", "contact", ("continuous_contact", "friction", "two_way_impulse")),
    ("fluid_rigid", "fluid", "rigid", "contact", ("pressure_force", "buoyancy", "drag", "two_way_impulse")),
    ("particle_rigid", "particle", "rigid", "contact", ("continuous_contact", "impulse", "event_emit")),
    ("particle_fluid", "particle", "fluid", "exchange", ("density_exchange", "viscosity", "surface_tension")),
    ("particle_volume", "particle", "volume", "exchange", ("source_density", "source_temperature", "velocity_advection")),
    ("fluid_volume", "fluid", "volume", "exchange", ("spray_to_mist", "heat_exchange", "velocity_advection")),
    ("surface_particle", "surface", "particle", "post_solve", ("contact_projection", "deformation_mark", "event_emit")),
    ("effect_volume", "effect", "volume", "post_solve", ("render_attribute_export", "event_routing")),
)


_BACKEND_NATIVE_COUPLINGS = {
    "reference_cpu": {item[0] for item in _COUPLINGS},
    "native_cpu": {
        "field_particle", "field_cloth", "field_softbody", "effect_particle",
        "particle_fluid", "particle_volume", "effect_volume",
    },
    "gpu_compute": {
        "field_particle", "effect_particle", "particle_fluid", "particle_volume", "effect_volume",
    },
}


def compile_multiphysics_coupling(
    world: Any,
    domains: list[str] | tuple[str, ...],
    *,
    backend: str,
    maximum_pairs_per_particle: int = 16,
) -> MultiphysicsCouplingPlan:
    active = tuple(sorted(set(str(item) for item in domains)))
    active_set = set(active)
    requested = str(backend or "reference_cpu")
    native = _BACKEND_NATIVE_COUPLINGS.get(requested, set())
    particle_count = len(getattr(world, "particles", ()) or ())
    maximum_pairs = max(1, particle_count) * max(1, int(maximum_pairs_per_particle))
    stages: list[MultiphysicsCouplingStage] = []
    has_fields = bool(getattr(world, "fields", None) or getattr(world, "curve_fields", None))
    for stage_id, source, target, phase, operations in _COUPLINGS:
        is_field_stage = stage_id.startswith("field_")
        if is_field_stage:
            if not has_fields or target not in active_set:
                continue
        elif source not in active_set or target not in active_set:
            continue
        native_execution = stage_id in native
        stages.append(MultiphysicsCouplingStage(
            stage_id, source if not is_field_stage else target, target, phase, operations,
            requested if native_execution else "reference_cpu",
            "" if native_execution else "reference_cpu",
            "" if native_execution else f"{requested} has no qualified {stage_id} coupling kernel.",
            maximum_pairs if phase in {"contact", "exchange"} else 0,
        ))
    stages.sort(key=lambda item: (COUPLING_PHASES.index(item.phase), item.stage_id))
    plan = MultiphysicsCouplingPlan(
        active, tuple(stages), requested,
        sum(item.execution_backend == requested for item in stages),
        sum(bool(item.fallback_backend) for item in stages), maximum_pairs,
    )
    errors = plan.validate()
    if errors:
        raise ValueError("Invalid multiphysics coupling plan: " + "; ".join(errors))
    return plan


__all__ = [
    "COUPLING_PHASES", "MultiphysicsCouplingPlan", "MultiphysicsCouplingStage",
    "compile_multiphysics_coupling",
]
