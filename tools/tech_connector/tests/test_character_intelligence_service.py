from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.character_intelligence_service import (
    CharacterMemory,
    CharacterObjective,
    CharacterParameterSpec,
    CharacterProfile,
    CharacterRule,
    CharacterState,
    CharacterWorldAsset,
    FactCondition,
    NarrativeBeat,
    attach_character_world,
)
from tech_connector.game_engine.runtime.character_brain_service import (
    CharacterAction,
    ModelActionProposal,
    apply_narrative_beat,
    choose_character_action,
    choose_character_lod,
    decay_character_memories,
    execute_character_action,
    record_character_memory,
    select_narrative_beat,
)
from tech_connector.game_engine.runtime.tc_engine_api import TCEngineAPI, engine_access_contract
from tech_connector.game_engine.scene.federated_scene_service import FederatedSceneDocument


def _character_world() -> tuple[CharacterWorldAsset, CharacterState]:
    profile = CharacterProfile(
        "guard",
        "Mara",
        parameter_specs={
            "courage": CharacterParameterSpec("courage", default=0.7),
            "core_identity": CharacterParameterSpec("core_identity", default=1.0, designer_locked=True),
        },
        parameters={"courage": 0.8},
        traits={"empathy": 0.9},
        drives={"duty": 0.8},
        rules=[
            CharacterRule(
                "honor_ceasefire",
                conditions=(FactCondition("world.ceasefire", "equals", True),),
                action_tags=("violence",),
                outcome="deny",
                priority=100,
            )
        ],
    )
    character = CharacterState(profile)
    world = CharacterWorldAsset(characters={"guard": character}, world_facts={"ceasefire": True, "town.safe": False})
    return world, character


def test_character_parameters_are_typed_clamped_locked_and_serializable() -> None:
    world, character = _character_world()
    character.objectives.append(
        CharacterObjective("protect", "Protect the town", {"town.safe": True}, tags=("duty",))
    )

    assert character.profile.set_parameter("courage", 3.0) == 1.0
    with pytest.raises(PermissionError):
        character.profile.set_parameter("core_identity", 0.0)

    restored = CharacterWorldAsset.from_dict(world.to_dict())
    assert restored.characters["guard"].profile.parameters["courage"] == 1.0
    assert restored.characters["guard"].profile.parameter_specs["core_identity"].designer_locked
    assert restored.characters["guard"].objectives[0].tags == ("duty",)

    scene = FederatedSceneDocument()
    payload = attach_character_world(scene, restored)
    assert scene.metadata["character_world"] == payload


def test_authored_rules_objectives_and_affordances_override_model_proposals() -> None:
    world, character = _character_world()
    character.objectives.append(CharacterObjective("protect_town", "Keep the town safe", {"town.safe": True}, priority=1.0))
    actions = (
        CharacterAction("attack", "Attack the visitor", tags=("violence",), base_utility=10.0),
        CharacterAction(
            "help",
            "Secure the gate",
            tags=("duty",),
            effects={"town.safe": True},
            parameter_weights={"empathy": 0.5, "duty": 0.5},
            required_affordance="gate_controls",
        ),
        CharacterAction("wait", "Wait", base_utility=0.1),
    )

    decision = choose_character_action(
        character,
        world,
        actions,
        available_affordances=("gate_controls",),
        model_proposal=ModelActionProposal("attack", "Dramatic conflict", 1.0),
    )

    assert decision.chosen_action == "help"
    assert not decision.model_proposal_accepted
    attack = next(row for row in decision.candidates if row.action_id == "attack")
    assert "rule:honor_ceasefire" in attack.blocked_by
    assert "Model proposal was rejected" in decision.explanation

    receipt = execute_character_action(character, world, actions[1], decision)
    assert world.world_facts["town.safe"] is True
    assert receipt["before"]["town.safe"] is False
    with pytest.raises(PermissionError):
        execute_character_action(character, world, actions[0], decision)


def test_memory_merges_tracks_provenance_and_decays() -> None:
    _world, character = _character_world()
    first = CharacterMemory("m1", "social", "player", "kept_promise", True, salience=0.8, created_at=1.0)
    update = CharacterMemory("m2", "social", "player", "kept_promise", False, confidence=0.7, salience=0.9, created_at=2.0)
    record_character_memory(character, first)
    result = record_character_memory(character, update)

    assert len(character.memories) == 1
    assert result.value is False and result.confidence == 0.7
    assert decay_character_memories(character, now=3.0, elapsed=1.0, decay_rate=0.1) == 0
    assert character.memories[0].salience == pytest.approx(0.8)
    assert decay_character_memories(character, now=20.0, elapsed=20.0, decay_rate=0.1) == 1


def test_narrative_beats_are_conditional_repeat_safe_and_assign_objectives() -> None:
    world, character = _character_world()
    beat = NarrativeBeat(
        "alarm",
        "The town alarm sounds.",
        conditions=(FactCondition("world.ceasefire", "equals", True),),
        effects={"alarm_active": True},
        objectives=(CharacterObjective("investigate", "Investigate the alarm", {"alarm_resolved": True}),),
        eligible_characters=("guard",),
        priority=0.9,
        once=True,
    )
    world.narrative_beats[beat.beat_id] = beat

    decision = select_narrative_beat(world, now=5.0, focus_character="guard")
    applied = apply_narrative_beat(world, beat, decision, now=5.0, focus_character="guard")
    repeated = select_narrative_beat(world, now=6.0, focus_character="guard")

    assert applied["beat_id"] == "alarm"
    assert world.world_facts["alarm_active"] is True
    assert character.objectives[-1].objective_id == "investigate"
    assert not repeated.chosen_beat
    assert "already_played" in repeated.candidates[0]["blocked_by"]


def test_namespaced_world_facts_and_public_engine_api_use_the_same_brain() -> None:
    world, character = _character_world()
    character.profile.rules.append(
        CharacterRule(
            "protect_safe_town",
            conditions=(FactCondition("world.town.safe", "equals", True),),
            action_tags=("damage",),
            outcome="deny",
        )
    )
    world.world_facts["town.safe"] = True
    decision = TCEngineAPI.decide_character(
        world,
        "guard",
        (CharacterAction("damage_gate", "Damage the gate", tags=("damage",)),),
    )

    assert not decision.chosen_action
    assert "rule:protect_safe_town" in decision.candidates[0].blocked_by
    assert "characters.choose_action" in engine_access_contract()["characters"]["commands"]


def test_character_intelligence_lod_preserves_critical_agents() -> None:
    assert choose_character_lod("hero", distance=1000, quest_critical=True).level == "full"
    assert choose_character_lod("merchant", distance=80).level == "scheduled"
    background = choose_character_lod("citizen", distance=800, significance=0.1)
    assert background.level == "statistical"
    assert background.update_interval == 10.0
