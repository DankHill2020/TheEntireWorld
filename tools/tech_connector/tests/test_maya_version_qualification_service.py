from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tech_connector.game_engine.integration.maya_version_qualification_service import (
    DECLARED_VERSIONS,
    MAYA_VERSION_QUALIFICATION_SCHEMA,
    validate_maya_version_qualification,
)
from tech_connector.game_engine.integration.playable_project_qualification_service import (
    playable_project_source_fingerprint,
)


def test_maya_2023_plus_contract_accepts_current_installed_evidence() -> None:
    source = Path(__file__).resolve().parents[2]
    receipt = {
        "schema": MAYA_VERSION_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(source),
        "declared_versions": list(DECLARED_VERSIONS),
        "source_contract": {"minimum_version": 2023, "shared_bootstrap": True},
        "installed_qualification": [{"version": 2023, "status": "passed"}],
    }

    assert validate_maya_version_qualification(source, receipt)["valid"]


def test_maya_contract_fails_closed_without_real_runtime_evidence() -> None:
    source = Path(__file__).resolve().parents[2]
    receipt = {
        "schema": MAYA_VERSION_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(source),
        "declared_versions": list(DECLARED_VERSIONS),
        "source_contract": {"minimum_version": 2023, "shared_bootstrap": True},
        "installed_qualification": [],
    }

    result = validate_maya_version_qualification(source, receipt)

    assert not result["valid"]
    assert "installed_versions" in result["gates"]
