from __future__ import annotations

from tech_connector.game_engine.authoring.game_experience_service import GameExperienceProfile, create_game_experience_profile
from tech_connector.game_engine.authoring.presentation_profile_service import (
    available_visual_styles,
    compile_presentation_plan,
    create_presentation_profile,
    presentation_controls,
    presentation_summary,
    update_presentation_control,
    validate_presentation_profile,
)


def test_8bit_presentation_does_not_reduce_realistic_simulation() -> None:
    game = create_game_experience_profile("orbit_arcade", ("realistic_simulation",))
    game.presentation = create_presentation_profile("orbit_visuals", "8-bit", dimensionality="2.5d")
    plan = compile_presentation_plan(game.presentation, target="desktop", viewport_size=(1920, 1080))
    validation = validate_presentation_profile(game.presentation, game)

    assert game.axes.simulation_fidelity == 1.0
    assert game.presentation.visual_style == "pixel_8bit"
    assert plan["simulation_contract"] == "unchanged" and plan["gameplay_contract"] == "unchanged"
    assert plan["internal_resolution"] == [320, 180]
    assert plan["integer_present_scale"] == 6
    assert plan["asset_representations"]["world"] == "layered_cards_and_meshes"
    assert plan["viewport_preview"]["status"] == "interactive"
    assert validation["independence"] == {
        "presentation_fidelity": 0.35, "simulation_fidelity": 1.0, "coupled": False,
    }


def test_friendly_controls_are_plain_described_and_update_the_profile() -> None:
    profile = create_presentation_profile("storybook", "cel shaded", dimensionality="two and a half d")
    controls = presentation_controls(profile)
    labels = {row["label"] for row in controls}
    assert {"Visual Style", "World Layout", "Visual Detail", "Pixel Perfect", "Animation Feel", "Sprite Facing"}.issubset(labels)
    assert all(row["description"] and len(row["description"].split()) >= 5 for row in controls)

    update_presentation_control(profile, "visual_style", "16-bit")
    update_presentation_control(profile, "pixel_canvas", (384, 216))
    update_presentation_control(profile, "animation_feel", "stepped")
    update_presentation_control(profile, "world_layout", "mixed")
    summary = presentation_summary(profile)
    assert profile.visual_style == "pixel_16bit"
    assert profile.resolution.base_width == 384
    assert profile.animation["sampling"] == "stepped"
    assert profile.dimensionality == "mixed"
    assert "Gameplay and simulation remain unchanged" in summary["description"]


def test_hyperreal_and_retro_are_both_first_class_and_profiles_round_trip() -> None:
    hyperreal = create_presentation_profile("film", "hyper realistic", dimensionality="3d")
    retro = create_presentation_profile("retro", "PS1", dimensionality="mixed")
    restored = GameExperienceProfile.from_dict(
        GameExperienceProfile("showcase", ("sandbox",), presentation=hyperreal).to_dict()
    )

    assert validate_presentation_profile(hyperreal)["valid"]
    assert hyperreal.materials["model"] == "spectral_openpbr"
    assert compile_presentation_plan(hyperreal)["viewport_preview"]["status"] == "reference"
    assert "spectral materials" in compile_presentation_plan(hyperreal)["viewport_preview"]["unavailable_features"]
    assert retro.visual_style == "retro_3d"
    assert restored.presentation is not None and restored.presentation.visual_style == "hyperreal"
    assert {"pixel_8bit", "toon", "photoreal", "hyperreal"}.issubset(available_visual_styles())
