from __future__ import annotations

from tech_connector.game_engine.integration.content_production_qualification_service import (
    qualify_content_production,
    validate_content_production_qualification,
)


def test_content_production_qualification_exercises_authoring_runtime_and_interchange(tmp_path) -> None:
    receipt = qualify_content_production(tmp_path, tmp_path / "qualification", maximum_total_seconds=10.0)

    assert receipt["status"] == "passed"
    assert len(receipt["assets"]) == 37
    assert len(receipt["qualified_asset_types"]) == 37
    assert all(row["status"] == "passed" for row in receipt["assets"])
    assert all(receipt["interchange_checks"].values())
    assert validate_content_production_qualification(tmp_path, receipt)["valid"] is True


def test_content_production_receipt_is_invalidated_by_engine_source_change(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    feature = source / "content_feature.py"
    feature.write_text("VERSION = 1\n", encoding="utf-8")
    receipt = qualify_content_production(tmp_path, tmp_path / "qualification", maximum_total_seconds=10.0)

    feature.write_text("VERSION = 2\n", encoding="utf-8")
    validation = validate_content_production_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "source_fingerprint" in validation["gates"]
