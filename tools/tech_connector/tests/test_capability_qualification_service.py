from __future__ import annotations

from datetime import datetime, timezone

from tech_connector.game_engine.integration.capability_qualification_service import (
    CAPABILITY_QUALIFICATION_SCHEMA,
    capability_test_files,
    validate_capability_qualification,
)
from tech_connector.game_engine.integration.playable_project_qualification_service import playable_project_source_fingerprint


def test_every_capability_evidence_test_file_exists() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    files = capability_test_files(root)
    assert len(files) >= 40
    assert all(path.is_file() for path in files)


def test_capability_receipt_is_source_bound(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    module = source / "feature.py"
    module.write_text("VERSION = 1\n", encoding="utf-8")
    receipt = {
        "schema": CAPABILITY_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(tmp_path),
        "exit_code": 0,
        "passed_tests": 10,
        "missing_test_files": [],
    }
    assert validate_capability_qualification(tmp_path, receipt)["valid"] is True
    module.write_text("VERSION = 2\n", encoding="utf-8")
    validation = validate_capability_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "source_fingerprint" in validation["gates"]
