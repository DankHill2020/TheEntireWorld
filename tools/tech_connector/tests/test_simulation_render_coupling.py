"""Resident render-stream and explicit multiphysics coupling regression coverage."""

from __future__ import annotations

import numpy as np

from tech_connector.game_engine.runtime.tc_multiphysics_coupling_service import compile_multiphysics_coupling
from tech_connector.game_engine.runtime.tc_simulation_compute_provider_service import (
    ArrayComputeProvider, ComputeProviderStatus, register_compute_provider,
)
from tech_connector.game_engine.runtime.tc_simulation_gpu_backend_service import execute_gpu_compute
from tech_connector.game_engine.runtime.tc_simulation_ir_service import (
    SimulationBackendCapabilities, compile_simulation_world, execute_compiled_simulation,
    register_simulation_backend, register_simulation_executor,
)
from tech_connector.game_engine.runtime.tc_simulation_native_backend_service import execute_native_cpu
from tech_connector.game_engine.runtime.tc_simulation_render_bridge_service import (
    build_simulation_render_stream, qualify_simulation_render_stream,
)
from tech_connector.game_engine.runtime.tc_simulation_service import ForceField, SimulationParticle, SimulationWorld


def _world(phases: tuple[str, ...] = ("particle",)) -> SimulationWorld:
    return SimulationWorld(
        particles=[
            SimulationParticle((index * 0.1, 1.0, 0.0), velocity=(0.2, 0.0, 0.0), phase=phase)
            for index, phase in enumerate(phases)
        ],
        fields=[ForceField("gravity")], self_collision=False, substeps=1, constraint_iterations=1,
    )


def test_object_stream_truthfully_reports_materialized_fallback() -> None:
    stream = build_simulation_render_stream(_world(), consumer="qt_quick3d")

    assert stream.source_backend == "object_reference"
    assert not stream.zero_copy_source
    assert stream.consumer_compatible
    assert stream.buffers["positions"].shape == (1, 3)
    assert "materialized" in stream.fallback_reason


def test_native_resident_stream_uses_soa_positions_without_object_materialization() -> None:
    world = _world(("particle", "particle"))
    compiled = compile_simulation_world(world, backend="native_cpu")
    compiled.metadata["native_resident_output"] = True
    execute_native_cpu(compiled, world, 1.0 / 60.0)

    stream = build_simulation_render_stream(world, consumer="qt_quick3d")

    assert stream.source_backend == "native_cpu"
    assert stream.residency == "persistent_host_soa"
    assert stream.zero_copy_source
    assert stream.consumer_upload_required
    assert not stream.receipt()["end_to_end_zero_copy"]
    assert not stream.synchronization_required
    assert stream.buffers["positions"].handle.shape == (2, 3)


def test_gpu_stream_requires_explicit_sync_for_qt_but_not_compute_consumers() -> None:
    provider_id = "render_bridge_test_gpu"
    register_compute_provider(ArrayComputeProvider(
        ComputeProviderStatus(provider_id, True, "gpu", "Render Bridge Test GPU", True), np,
    ))
    world = _world(("particle", "particle"))
    compiled = compile_simulation_world(world, backend="native_cpu")
    compiled.metadata["gpu_resident_output"] = True
    initial = world.particles[0].position
    receipt = execute_gpu_compute(compiled, world, 1.0 / 60.0, provider_id=provider_id)

    direct = build_simulation_render_stream(world, consumer=provider_id)
    blocked = build_simulation_render_stream(world, consumer="qt_quick3d", allow_synchronization=False)
    synchronized = build_simulation_render_stream(world, consumer="qt_quick3d", allow_synchronization=True)

    assert receipt["resident_output"]
    assert direct.consumer_compatible and direct.zero_copy_source
    assert not direct.synchronization_required
    assert qualify_simulation_render_stream(direct, require_end_to_end_zero_copy=True)["qualified"]
    assert not blocked.consumer_compatible and blocked.synchronization_required
    assert "consumer_buffer_interop" in qualify_simulation_render_stream(blocked)["blockers"]
    assert synchronized.synchronization_performed
    assert synchronized.fallback_reason.startswith("qt_quick3d required")
    assert world.particles[0].position != initial


def test_multiphysics_plan_orders_couplings_and_bounds_exchange_pairs() -> None:
    world = _world(("fluid", "rigid_cluster", "particle"))
    domains = ["fluid", "rigid", "particle"]
    plan = compile_multiphysics_coupling(world, domains, backend="native_cpu", maximum_pairs_per_particle=8)

    assert not plan.validate()
    assert plan.maximum_contact_pairs == 24
    assert [stage.phase for stage in plan.stages] == sorted(
        [stage.phase for stage in plan.stages], key=("pre_solve", "contact", "exchange", "post_solve").index
    )
    fluid_rigid = next(stage for stage in plan.stages if stage.stage_id == "fluid_rigid")
    assert fluid_rigid.execution_backend == "reference_cpu"
    assert fluid_rigid.fallback_backend == "reference_cpu"


def test_compiled_multiphysics_ir_falls_back_whole_tick_until_hybrid_scheduling_exists() -> None:
    world = _world(("fluid", "rigid_cluster"))
    compiled = compile_simulation_world(world, backend="native_cpu")
    coupling = compiled.metadata["multiphysics_coupling"]
    telemetry = execute_compiled_simulation(compiled, world, 1.0 / 60.0)

    assert coupling["fallback_stage_count"] > 0
    assert "coupling_contacts" in {item.resource_id for item in compiled.resources}
    assert any(stage.stage_id == "couple.fluid_rigid" for stage in compiled.stages)
    assert telemetry["execution_backend"] == "reference_cpu"
    assert "hybrid per-stage device scheduling is not installed" in " ".join(
        telemetry["backend_receipt"]["fallback_reasons"]
    )


def test_gpu_telemetry_distinguishes_resident_allocation_from_readback_free_output() -> None:
    backend_id = "render_receipt_gpu"
    register_simulation_backend(SimulationBackendCapabilities(
        backend_id, True, "gpu", ("particle",), True, False, False, 1000,
    ))
    register_simulation_executor(backend_id, lambda _compiled, _world, _dt: {
        "execution_backend": backend_id, "buffer_residency": "persistent_device",
        "resident_output": True, "synchronization_points": 0,
    })
    world = _world()
    world.fields.clear()
    compiled = compile_simulation_world(world, backend=backend_id)
    telemetry = execute_compiled_simulation(compiled, world, 1.0 / 60.0)

    assert telemetry["gpu_resident"]
    assert telemetry["resident_output"]
    assert telemetry["readback_free"]
    assert telemetry["synchronization_points"] == 0
