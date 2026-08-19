from __future__ import annotations

from pathlib import Path

import pytest

from tech_connector.acceptance import tomorrow_readiness as readiness


def test_readiness_requires_every_required_gate_but_preserves_warnings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(readiness, "DEFAULT_OUTPUT_ROOT", tmp_path / "latest")
    runner = readiness.TomorrowReadinessRunner(tmp_path / "run")
    runner.checks = [
        readiness.AcceptanceCheck("core", "Core", "pass", True, 0.1, "ok"),
        readiness.AcceptanceCheck("dcc", "DCC", "warn", False, 0.1, "live host unavailable"),
    ]
    report = runner._report()
    assert report["ready_for_local_testing"] is True
    assert report["warnings"] == ["dcc"]
    runner._write_report(report)
    assert (tmp_path / "run" / "readiness.json").is_file()
    assert "Hands-On Pass" in (tmp_path / "run" / "TEST_CHECKLIST.md").read_text(encoding="utf-8")


def test_vertical_slice_evidence_is_replaced_when_output_is_reused(tmp_path) -> None:
    from tech_connector.game_engine.runtime.tc_player_build_service import _resolve_player_executable

    try:
        _resolve_player_executable(None)
    except FileNotFoundError:
        pytest.skip("Native player has not been built.")
    runner = readiness.TomorrowReadinessRunner(Path(tmp_path))
    runner._vertical_slice()
    runner._vertical_slice()
    assert [check.status for check in runner.checks] == ["pass", "pass"]
    assert all(check.summary.startswith("90/90 frames") for check in runner.checks)
