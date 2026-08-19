from __future__ import annotations

import pytest

from tech_connector.game_engine.rendering.lighting_profile_service import (
    lighting_profile,
    lighting_profiles,
    resolve_lighting_settings,
)


def test_default_profiles_are_stable_and_cover_core_art_directions() -> None:
    assert [item.profile_id for item in lighting_profiles()] == [
        "daylight", "overcast", "golden_hour", "moonlight", "studio_neutral", "toon", "unlit_reference",
    ]
    assert lighting_profile(None).profile_id == "daylight"


def test_profile_values_are_defaults_and_explicit_scene_values_win() -> None:
    rendering, sun = resolve_lighting_settings({"lighting_profile": "golden-hour", "exposure": 1.8})
    assert rendering["lighting_profile"] == "golden_hour"
    assert rendering["exposure"] == 1.8
    assert rendering["atmosphere_enabled"] is True
    assert sun["intensity"] == 5.0


def test_unknown_profile_is_actionable() -> None:
    with pytest.raises(ValueError, match="Available profiles"):
        lighting_profile("mystery")
