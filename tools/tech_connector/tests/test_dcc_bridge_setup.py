"""Tests for portable DCC bridge setup paths."""

from __future__ import annotations

from pathlib import Path

from tech_connector.game_engine.integration import dcc_bridge_setup


def test_roaming_app_data_prefers_environment(monkeypatch) -> None:
    """
    Verifies that the operating-system application-data setting is honored.

    :param monkeypatch: Pytest environment patch helper.
    :return: None.
    """

    expected = Path("C:/portable/profile/Roaming")
    monkeypatch.setenv("APPDATA", str(expected))

    assert dcc_bridge_setup._roaming_app_data_dir() == expected


def test_roaming_app_data_falls_back_to_current_home(monkeypatch) -> None:
    """
    Verifies that setup never falls back to a developer-specific profile.

    :param monkeypatch: Pytest environment patch helper.
    :return: None.
    """

    monkeypatch.delenv("APPDATA", raising=False)
    expected = Path("C:/portable/profile")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: expected))

    assert dcc_bridge_setup._roaming_app_data_dir() == expected / "AppData" / "Roaming"
