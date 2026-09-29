from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from tech_connector.game_engine.integration.playable_project_qualification_service import (
    PLAYABLE_PROJECT_QUALIFICATION_SCHEMA,
    playable_project_source_fingerprint,
    validate_playable_project_qualification,
)


def test_source_fingerprint_changes_with_engine_source(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    module = source / "feature.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    first = playable_project_source_fingerprint(tmp_path)
    module.write_text("VALUE = 2\n", encoding="utf-8")
    second = playable_project_source_fingerprint(tmp_path)
    assert first != second


def test_qualification_receipt_requires_current_source_and_player(tmp_path) -> None:
    source = tmp_path / "tech_connector" / "game_engine"
    source.mkdir(parents=True)
    (source / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    player = tmp_path / "tc_player.exe"
    player.write_bytes(b"qualified player")
    receipt = {
        "schema": PLAYABLE_PROJECT_QUALIFICATION_SCHEMA,
        "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_fingerprint": playable_project_source_fingerprint(tmp_path),
        "player_executable": str(player),
        "player_sha256": hashlib.sha256(player.read_bytes()).hexdigest(),
        "variants": [{"qualified_id": "playable_sandbox/standard", "status": "passed"}],
    }
    assert validate_playable_project_qualification(tmp_path, receipt)["valid"] is True
    player.write_bytes(b"changed")
    validation = validate_playable_project_qualification(tmp_path, receipt)
    assert validation["valid"] is False
    assert "player_binary" in validation["gates"]
