from __future__ import annotations

from tech_connector.game_engine.integration.world_production_qualification_service import (
    qualify_world_production,
    validate_world_production_qualification,
)


def test_world_production_qualification_exercises_world_streaming_and_procedural_roundtrips(tmp_path) -> None:
    receipt = qualify_world_production(tmp_path, tmp_path / "qualification", maximum_total_seconds=10.0)

    assert receipt["status"] == "passed"
    assert len(receipt["world_assets"]) == 8
    assert all(row["status"] == "passed" for row in receipt["world_assets"])
    assert all(receipt["streaming_checks"].values())
    assert receipt["procedural"]["status"] == "passed"
    assert set(receipt["procedural"]["adapters"]) == {"unreal", "unity", "blender", "houdini", "godot"}
    assert len(receipt["qualified_asset_types"]) == 9
    assert validate_world_production_qualification(tmp_path, receipt)["valid"] is True


def test_world_production_receipt_is_invalidated_by_engine_source_change(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    feature = source / "world_feature.py"
    feature.write_text("VERSION = 1\n", encoding="utf-8")
    receipt = qualify_world_production(tmp_path, tmp_path / "qualification", maximum_total_seconds=10.0)

    feature.write_text("VERSION = 2\n", encoding="utf-8")
    validation = validate_world_production_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "source_fingerprint" in validation["gates"]
