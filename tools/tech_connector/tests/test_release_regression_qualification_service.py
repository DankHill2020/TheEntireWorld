from __future__ import annotations

from datetime import datetime, timezone

from tech_connector.game_engine.integration.playable_project_qualification_service import (
    playable_project_source_fingerprint,
)
from tech_connector.game_engine.integration.release_regression_qualification_service import (
    RELEASE_REGRESSION_QUALIFICATION_SCHEMA,
    validate_release_regression_qualification,
)


def test_release_regression_receipt_is_source_bound_and_fail_closed(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    feature = source / "feature.py"
    feature.write_text("VERSION = 1\n", encoding="utf-8")
    receipt = {
        "schema": RELEASE_REGRESSION_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(tmp_path),
        "passed_tests": 12,
        "skipped_tests": 1,
        "failed_tests": 0,
        "exit_code": 0,
        "timed_out": False,
        "interpreter": {"supported": True},
    }
    assert validate_release_regression_qualification(tmp_path, receipt)["valid"] is True
    feature.write_text("VERSION = 2\n", encoding="utf-8")
    validation = validate_release_regression_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "source_fingerprint" in validation["gates"]


def test_release_regression_receipt_rejects_unsupported_interpreter(tmp_path) -> None:
    receipt = {
        "schema": RELEASE_REGRESSION_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(tmp_path),
        "passed_tests": 1,
        "failed_tests": 0,
        "exit_code": 0,
        "timed_out": False,
        "interpreter": {"supported": False},
    }
    validation = validate_release_regression_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "interpreter" in validation["gates"]
