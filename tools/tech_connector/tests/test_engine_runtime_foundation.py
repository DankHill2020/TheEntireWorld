"""Lifecycle, cache, identity, health, and qualification coverage for the simulation engine."""

from __future__ import annotations

import pytest

from tech_connector.game_engine.runtime.tc_engine_readiness_service import (
    audit_engine_readiness,
    qualify_runtime_determinism,
)
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance
from tech_connector.game_engine.runtime.tc_simulation_ir_service import compile_simulation_world
from tech_connector.game_engine.runtime.tc_simulation_service import ForceField, SimulationWorld, TriangleMeshCollider
from tech_connector.game_engine.runtime.tc_engine_api import engine


def test_runtime_lifecycle_pause_resume_reset_and_hashes_are_explicit() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=17)
    initial_asset = runtime.asset_fingerprint
    initial_state = runtime.state_hash()

    runtime.pause()
    assert runtime.advance(runtime.fixed_dt).tick == 0
    runtime.resume()
    runtime.advance(runtime.fixed_dt)
    assert runtime.tick_index == 1
    assert runtime.state_hash() != initial_state
    assert runtime.asset_fingerprint == initial_asset

    runtime.reset()
    assert runtime.state == "ready"
    assert runtime.tick_index == 0
    assert runtime.asset_fingerprint == initial_asset
    assert runtime.state_hash() == initial_state


def test_runtime_cache_captures_versioned_frames_and_deployment_identity() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("fog", quality="low", seed=3)
    cache = runtime.enable_cache()
    runtime.advance(3 * runtime.fixed_dt)
    runtime.disable_cache()
    manifest = runtime.deployment_manifest()

    assert sorted(cache.frames) == [0, 1, 2, 3]
    assert cache.metadata["asset_fingerprint"] == runtime.asset_fingerprint
    assert cache.metadata["workflow_stages"]["simulate"]["state"] == "cached"
    assert manifest["asset_fingerprint"] == runtime.asset_fingerprint
    assert manifest["compatibility"]["fixed_step_required"]
    assert manifest["cache"]["schema"] == "tech_connector.sim_cache.v1"


def test_runtime_command_queue_is_bounded_and_reported() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset(
        "sparks", quality="low", max_pending_commands=2, command_history_limit=2
    )
    runtime.queue_parameter("emitter.sparks.spawn_rate", 10.0, tick=2)
    runtime.queue_parameter("emitter.sparks.spawn_rate", 20.0, tick=3)
    with pytest.raises(OverflowError, match="bounded capacity"):
        runtime.queue_parameter("emitter.sparks.spawn_rate", 30.0, tick=4)

    health = runtime.health_snapshot()
    assert health.pending_commands == 2
    assert health.asset_fingerprint == runtime.asset_fingerprint


def test_independent_runtime_replays_qualify_deterministically() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=23, backend="reference_cpu")
    receipt = qualify_runtime_determinism(runtime, ticks=6, repeats=3)

    assert receipt["qualified"]
    assert receipt["mismatch_ticks"] == []
    assert len(set(receipt["final_state_hashes"])) == 1


def test_readiness_report_distinguishes_candidate_from_qualified_evidence() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=9, backend="reference_cpu")
    runtime.enable_cache()
    for _tick in range(4):
        runtime.advance(runtime.fixed_dt)
    determinism = qualify_runtime_determinism(runtime, ticks=4)

    candidate = audit_engine_readiness(runtime, determinism_receipt=determinism, minimum_performance_samples=30)
    qualified = audit_engine_readiness(runtime, determinism_receipt=determinism, minimum_performance_samples=4)

    assert candidate.maturity == "production_candidate"
    assert "performance_evidence" in candidate.blockers
    assert qualified.qualified
    assert qualified.maturity == "qualified"
    assert not qualified.blockers


def test_compiled_ir_makes_fields_and_collision_acceleration_explicit() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", seed=5)
    runtime.world.fields.append(ForceField("wind", vector=(2.0, 0.0, 0.0)))
    compiled = compile_simulation_world(runtime.world, backend="reference_cpu")
    resources = {item.resource_id: item for item in compiled.resources}
    stages = {item.stage_id: item for item in compiled.stages}

    assert resources["fields"].resource_type == "composable_force_fields"
    assert resources["fields"].metadata["types"]
    assert resources["colliders"].metadata["mesh_acceleration"] == "bvh"
    assert "fields" in stages["integrate"].reads
    assert stages["collision"].parameters["continuous_contact"]
    assert resources["cache_frames"].format == "tc.sim_cache.v1"


def test_runtime_hash_ignores_rebuildable_collision_acceleration_caches() -> None:
    collider = TriangleMeshCollider(
        [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (0.0, 0.0, 1.0)], [(0, 1, 2)]
    )
    world = SimulationWorld(mesh_colliders=[collider])
    runtime = SimulationRuntimeInstance(world, backend="reference_cpu")
    before = runtime.state_hash()
    collider.acceleration()

    assert runtime.state_hash() == before


def test_engine_api_exposes_runtime_audit_and_qualification_receipts() -> None:
    runtime = SimulationRuntimeInstance.from_effect_preset("sparks", quality="low", backend="reference_cpu")
    for _tick in range(2):
        runtime.advance(runtime.fixed_dt)

    audit = engine.audit_runtime(runtime, minimum_performance_samples=2)
    qualification = engine.qualify_runtime(runtime, ticks=2, repeats=2, minimum_performance_samples=2)

    assert audit["schema"] == "tech_connector.engine_readiness.v1"
    assert "repeat_determinism" in audit["blockers"]
    assert qualification["determinism"]["qualified"]
    assert qualification["readiness"]["qualified"]
