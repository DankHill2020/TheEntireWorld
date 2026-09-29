from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.authoring.game_experience_service import (
    GameExperienceProfile,
    build_gameplay_runtime_budget,
    create_game_experience_profile,
    validate_game_experience,
)
from tech_connector.game_engine.runtime.world_intelligence_command_service import (
    execute_gameplay_experience_command,
)


def test_game_experience_planning_has_bounded_catalog_scale() -> None:
    game_types = ("action", "rpg", "strategy", "platformer", "racing", "sandbox")
    started = time.perf_counter()
    results = []
    for index in range(5_000):
        profile = create_game_experience_profile(f"experience_{index}", (game_types[index % len(game_types)],))
        results.append((validate_game_experience(profile), build_gameplay_runtime_budget(profile, target="desktop")))
    elapsed = time.perf_counter() - started

    assert len(results) == 5_000
    assert all(validation["valid"] and budget["tick_rate"] >= 30 for validation, budget in results)
    assert elapsed < 3.0


def test_full_gameplay_and_visual_profile_round_trips_losslessly() -> None:
    profile, _ = execute_gameplay_experience_command(None, "gameplay.configure_experience", {
        "profile_id": "launch_profile",
        "game_types": ["action", "rpg", "sandbox"],
        "axis_overrides": {"accessibility": 1.0},
    })
    profile, _ = execute_gameplay_experience_command(profile, "gameplay.set_visual_style", {
        "style": "stylized_pbr", "world_layout": "3d", "visual_detail": 0.85,
    })
    profile, _ = execute_gameplay_experience_command(profile, "gameplay.update_visual_setting", {
        "setting": "camera_projection", "value": "perspective",
    })
    _, explained = execute_gameplay_experience_command(profile, "gameplay.explain_visual_settings", {})
    _, preview = execute_gameplay_experience_command(profile, "gameplay.preview_visual_plan", {"target": "console"})
    serialized = json.dumps(profile.to_dict(), sort_keys=True)
    restored = GameExperienceProfile.from_dict(json.loads(serialized))

    assert json.dumps(restored.to_dict(), sort_keys=True) == serialized
    assert explained["visual_validation"]["valid"]
    assert preview["visual_plan"]["target"] == "console"
    assert preview["visual_plan"]["simulation_contract"] == "unchanged"


def test_invalid_gameplay_authoring_fails_without_partial_profile() -> None:
    with pytest.raises(KeyError, match="Unknown game type"):
        create_game_experience_profile("bad", ("unknown_genre",))
    with pytest.raises(ValueError, match="schema"):
        GameExperienceProfile.from_dict({"schema": "corrupt"})
    profile = create_game_experience_profile("stable", ("sandbox",))
    before = json.dumps(profile.to_dict(), sort_keys=True)
    with pytest.raises(RuntimeError, match="Set a visual style"):
        execute_gameplay_experience_command(profile, "gameplay.update_visual_setting", {"setting": "visual_detail", "value": "high"})
    assert json.dumps(profile.to_dict(), sort_keys=True) == before
