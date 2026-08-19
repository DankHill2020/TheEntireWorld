from __future__ import annotations

from tech_connector.services.dcc.tc_effect_system_service import QUALITY_PROFILES, create_effect_world
from tech_connector.services.dcc.tc_simulation_ir_service import (
    EXECUTION_PROFILES,
    compile_simulation_world,
    effect_system_is_stateless,
    execute_compiled_reference,
)
from tech_connector.services.dcc.tc_simulation_service import create_cloth_from_geometry, create_cloth_grid
from tech_connector.services.dcc.tc_simulation_transfer_service import build_simulation_transfer_manifest
from tech_connector.services.dcc.tc_simulation_service import SimulationCache


def test_compiles_cloth_to_valid_staged_native_ir() -> None:
    world = create_cloth_grid(4, 4)

    compiled = compile_simulation_world(world, profile="realtime")

    assert compiled.validate() == []
    assert compiled.backend.backend_id == "native_cpu"
    assert compiled.domains == ["cloth"]
    assert {stage.stage_id for stage in compiled.stages} >= {
        "emit", "integrate", "broadphase", "constraints", "collision", "render_prepare",
    }
    assert any(item["code"] == "production_backend_unavailable" for item in compiled.diagnostics)


def test_requested_unavailable_gpu_backend_falls_back_explicitly() -> None:
    compiled = compile_simulation_world(create_cloth_grid(3, 3), profile="cinematic", backend="gpu_compute")

    assert compiled.backend.backend_id == "reference_cpu"
    assert any(item["code"] == "requested_backend_unavailable" for item in compiled.diagnostics)
    assert compiled.metadata["compiled_substeps"] > compiled.metadata["source_substeps"]


def test_reference_execution_uses_profile_without_mutating_author_settings() -> None:
    world = create_cloth_grid(3, 3)
    original = (world.substeps, world.constraint_iterations)
    compiled = compile_simulation_world(world, profile="retro", backend="reference_cpu")

    execute_compiled_reference(compiled, world, 1.0 / 60.0)

    assert world.time_seconds > 0.0
    assert (world.substeps, world.constraint_iterations) == original


def test_effect_stateless_analysis_and_art_direction_profiles() -> None:
    sparks = create_effect_world("sparks", quality="retro")
    fireworks = create_effect_world("fireworks", quality="realtime")

    assert effect_system_is_stateless(sparks.effect_system)
    assert not effect_system_is_stateless(fireworks.effect_system)
    assert QUALITY_PROFILES["retro"].prefer_stateless
    assert QUALITY_PROFILES["toony"].art_style == "toony"
    assert EXECUTION_PROFILES["cinematic"].solver_precision == "float64"


def test_fabric_uv_axes_compile_to_different_material_response() -> None:
    world = create_cloth_from_geometry(
        [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)],
        [(0, 1, 2, 3)],
        material="cotton",
        uvs=[(0, 1), (1, 1), (1, 0), (0, 0)],
    )

    by_axis = {}
    for constraint in world.constraints:
        by_axis.setdefault(constraint.material_axis, set()).add(constraint.compliance)
    assert {"warp", "weft", "bias"} <= set(by_axis)
    assert next(iter(by_axis["warp"])) != next(iter(by_axis["weft"]))


def test_transfer_manifest_embeds_compiled_ir_receipt() -> None:
    world = create_effect_world("fog", quality="toony")
    cache = SimulationCache()
    cache.store(world.capture_frame(1))

    manifest = build_simulation_transfer_manifest(world, cache, "unreal").to_dict()

    receipt = manifest["metadata"]["compiled_ir"]
    assert receipt["profile"] == "toony"
    assert receipt["backend"] == "native_cpu"
    assert "effect" in receipt["domains"]
    assert "effects" in receipt["stage_ids"]
    assert manifest["metadata"]["runtime_contract"]["requires_editor"] is False
    assert any(item["role"] == "tc_runtime" for item in manifest["artifacts"])
