from __future__ import annotations

import copy

from tech_connector.game_engine.integration.fx_qualification_service import (
    qualify_realtime_fx,
    validate_realtime_fx_qualification,
)


def test_realtime_fx_qualification_executes_authoring_cook_runtime_and_cache(tmp_path) -> None:
    receipt = qualify_realtime_fx(
        tmp_path, tmp_path / "qualification", presets=("sparks",), frames=8,
        maximum_particles=128, maximum_preset_seconds=2.0,
    )
    assert receipt["status"] == "passed"
    assert receipt["qualified_asset_types"] == ["tc.effect_system"]
    gpu_qualified = receipt["presets"][0]["backend"]["gpu_qualified"]
    assert receipt["gpu_qualification"]["qualified"] is gpu_qualified
    assert receipt["gpu_qualification"]["qualified_presets"] == (["sparks"] if gpu_qualified else [])
    assert receipt["gpu_qualification"]["unqualified_presets"] == ([] if gpu_qualified else ["sparks"])
    assert receipt["presets"][0]["checks"] == {
        "authoring_validation": True,
        "cost_budget": True,
        "deterministic_cook": True,
        "deterministic_runtime": True,
        "completed_frames": True,
        "runtime_audit": True,
        "particle_budget": True,
        "frame_budget": True,
        "solver_frame_budget": True,
        "surface_render_output": True,
    }
    assert validate_realtime_fx_qualification(tmp_path, receipt)["valid"] is True
    fallback_receipt = copy.deepcopy(receipt)
    fallback_receipt["gpu_qualification"]["qualified"] = False
    gpu_validation = validate_realtime_fx_qualification(tmp_path, fallback_receipt, require_gpu_backend=True)
    assert gpu_validation["valid"] is False
    assert "gpu_backend" in gpu_validation["gates"]
    fallback_receipt["production_backend_qualification"]["qualified"] = False
    production_validation = validate_realtime_fx_qualification(
        tmp_path, fallback_receipt, require_production_backend=True,
    )
    assert production_validation["valid"] is False
    assert "production_backend" in production_validation["gates"]


def test_fx_receipt_is_invalidated_by_engine_source_change(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    feature = source / "fx_feature.py"; feature.write_text("VERSION = 1\n", encoding="utf-8")
    receipt = qualify_realtime_fx(
        tmp_path, tmp_path / "qualification", presets=("sparks",), frames=4,
        maximum_particles=64, maximum_preset_seconds=2.0,
    )
    feature.write_text("VERSION = 2\n", encoding="utf-8")
    validation = validate_realtime_fx_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "source_fingerprint" in validation["gates"]
