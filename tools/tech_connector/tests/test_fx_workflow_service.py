"""Coverage for production-shaped FX workflow and backend contracts."""

from __future__ import annotations

from tech_connector.game_engine.runtime.tc_effect_system_service import (
    bake_effect_system,
    create_effect_world,
    set_effect_parameter,
)
from tech_connector.game_engine.runtime.tc_fx_workflow_service import (
    FX_SOLVER_PROFILES,
    FxPerformanceContract,
    audit_fx_world,
    build_fx_workflow_plan,
    solver_profile_for_preset,
)
from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    compile_simulation_world,
    execute_compiled_simulation,
    simulation_backend_status,
)


def test_all_major_fx_domains_have_authoring_controls_and_stages() -> None:
    assert {
        "particle_realtime", "flip_liquid", "viscous_goop", "granular",
        "softbody", "destruction", "sparse_pyro", "ocean_surface",
    } <= set(FX_SOLVER_PROFILES)
    for profile in FX_SOLVER_PROFILES.values():
        assert profile.controls
        assert len(profile.stages) >= 4
        assert len({control.control_id for control in profile.controls}) == len(profile.controls)


def test_realflow_style_liquid_pipeline_separates_secondary_and_meshing() -> None:
    plan = build_fx_workflow_plan("flip_liquid")
    stage_ids = [stage.stage_id for stage in plan.stages]

    assert stage_ids.index("simulate") < stage_ids.index("secondary") < stage_ids.index("surface")
    assert plan.solver.secondary_outputs == ("splash", "foam", "bubbles", "mist")
    assert plan.solver.supports_meshing


def test_specialist_presets_receive_sensible_solver_profiles() -> None:
    assert solver_profile_for_preset("mudslide").profile_id == "viscous_goop"
    assert solver_profile_for_preset("fog").profile_id == "sparse_pyro"
    assert solver_profile_for_preset("avalanche").profile_id == "granular"
    assert solver_profile_for_preset("earthquake").profile_id == "destruction"


def test_effect_workflow_and_performance_contract_are_live_editable() -> None:
    world = create_effect_world("sparks", quality="realtime")
    system = world.effect_system

    assert set_effect_parameter(system, "solver_profile", "viscous_goop") == "viscous_goop"
    assert set_effect_parameter(system, "backend_preference", "gpu_compute") == "gpu_compute"
    assert set_effect_parameter(system, "performance_contract.maximum_particles", 4321) == 4321
    assert system.workflow["solver"]["profile_id"] == "viscous_goop"
    assert system.workflow["requested_backend"] == "gpu_compute"
    assert system.performance_contract["maximum_particles"] == 4321


def test_viscous_controls_reach_runtime_material_and_spawned_particles() -> None:
    world = create_effect_world("mudslide", quality="realtime")
    system = world.effect_system
    set_effect_parameter(system, "parameters.solver_viscosity", 3.25)
    set_effect_parameter(system, "parameters.solver_adhesion", 0.8)

    world.step(1.0 / 30.0)

    assert world.materials["goo"].viscosity == 3.25
    assert world.materials["goo"].adhesion == 0.8
    assert all(particle.phase == "fluid" and particle.material == "goo" for particle in world.particles)


def test_performance_contract_normalizes_unsafe_values() -> None:
    contract = FxPerformanceContract(
        target_frame_ms=0.0,
        maximum_particles=0,
        maximum_volume_cells=-4,
        maximum_mesh_vertices=0,
        overflow_policy="unknown",
    ).normalized()

    assert contract.target_frame_ms == 0.1
    assert contract.maximum_particles == 1
    assert contract.maximum_volume_cells == 1
    assert contract.maximum_mesh_vertices == 1
    assert contract.overflow_policy == "reduce_detail"


def test_compiled_ir_contains_secondary_surface_cache_and_truthful_fallback() -> None:
    world = create_effect_world("refractive_bubbles", quality="realtime")
    for particle in world.particles:
        particle.phase = "fluid"
    compiled = compile_simulation_world(world, backend="gpu_compute")

    stage_ids = {stage.stage_id for stage in compiled.stages}
    assert {"secondary", "surface", "cache"} <= stage_ids
    assert compiled.metadata["requested_backend"] == "gpu_compute"
    assert compiled.metadata["execution_backend"] == "reference_cpu"
    assert compiled.metadata["gpu_resident"] is False
    assert not simulation_backend_status("gpu_compute")["available"]
    assert any(item["code"] == "requested_backend_unavailable" for item in compiled.diagnostics)

    portable = compile_simulation_world(world, backend="auto")
    execute_compiled_simulation(portable, world, 1.0 / 60.0)
    assert any(item["code"] == "runtime_backend_fallback" for item in portable.diagnostics)


def test_effect_bake_records_resumable_stage_checkpoint() -> None:
    cache = bake_effect_system(create_effect_world("sparks"), start_frame=1, end_frame=3)

    assert cache.metadata["workflow_stages"]["simulate"]["state"] == "cached"
    assert cache.metadata["checkpoints"]["simulate"] == 3
    assert cache.resumable_frame("simulate").frame == 3


def test_simulation_enforces_particle_contract_and_reports_pressure() -> None:
    world = create_effect_world("rain", quality="cinematic")
    system = world.effect_system
    set_effect_parameter(system, "performance_contract.maximum_particles", 12)

    for _frame in range(20):
        world.step(1.0 / 30.0)

    assert sum(1 for particle in world.particles if particle.alive) <= 12
    assert system.performance_metrics["particle_budget"] == 12
    assert system.performance_metrics["budget_pressure"] <= 1.0


def test_audit_explains_backend_fallback_and_stateless_opportunity() -> None:
    report = audit_fx_world(create_effect_world("sparks", quality="realtime"))

    assert report.status == "warning"
    assert report.metrics["effective_preview_backend"] == "reference_cpu"
    assert report.metrics["stateless_compatible"]
    assert any(item["code"] == "backend_fallback" for item in report.diagnostics)
    assert any("stateless" in recommendation for recommendation in report.recommendations)
