from __future__ import annotations

from tech_connector.game_engine.authoring.game_experience_service import (
    GameExperienceProfile,
    LearningObjective,
    attach_game_experience,
    available_game_types,
    build_gameplay_runtime_budget,
    create_game_experience_profile,
    validate_game_experience,
)
from tech_connector.game_engine.scene.federated_scene_service import FederatedSceneDocument


def test_composable_educational_astronomy_sandbox_preserves_distinct_requirements() -> None:
    profile = create_game_experience_profile("orbit_lab", ("realistic_simulation", "educational", "sandbox"))
    profile.learning_objectives.append(
        LearningObjective("orbital_period", "Predict orbital period", ("prediction", "simulation_result"), standards=("NGSS",))
    )
    validation = validate_game_experience(profile)
    budget = build_gameplay_runtime_budget(profile, target="desktop")

    assert profile.axes.simulation_fidelity == 1.0
    assert profile.axes.learning == 1.0 and profile.axes.player_expression == 1.0
    assert profile.simulation.allow_time_scrub
    assert validation["valid"] and not validation["issues"]
    assert {"unit_aware_physics", "adaptive_scaffolding", "runtime_authoring"}.issubset(validation["required_capabilities"])
    assert budget["tick_rate"] >= 60 and budget["requires_deterministic_replay"]


def test_profiles_round_trip_attach_to_scene_and_flag_child_privacy_errors() -> None:
    profile = create_game_experience_profile("kids_puzzle", ("educational", "puzzle"))
    profile.learning_objectives.append(LearningObjective("fractions", "Compare fractions", ("answer",)))
    scene = FederatedSceneDocument()
    payload = attach_game_experience(scene, profile)
    restored = GameExperienceProfile.from_dict(payload)
    profile.safety["minor_privacy"] = False
    validation = validate_game_experience(profile)

    assert scene.metadata["game_experience"]["profile_id"] == "kids_puzzle"
    assert restored.learning_objectives[0].evidence == ("answer",)
    assert not validation["valid"]
    assert any(row["code"] == "minor_privacy_missing" for row in validation["issues"])
    assert {"action", "party", "racing", "rpg", "strategy"}.issubset(available_game_types())


def test_competitive_profiles_request_replay_evidence_without_forcing_one_genre() -> None:
    profile = create_game_experience_profile("arena", ("action",), axis_overrides={"competition": 1.0})
    validation = validate_game_experience(profile)
    assert validation["valid"]
    assert any(row["code"] == "competition_replay_missing" for row in validation["issues"])
