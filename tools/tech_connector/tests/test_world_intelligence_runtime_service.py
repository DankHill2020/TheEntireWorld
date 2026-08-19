from __future__ import annotations

import pytest

from tech_connector.game_engine.authoring.character_intelligence_service import (
    CharacterProfile,
    CharacterState,
    CharacterWorldAsset,
)
from tech_connector.game_engine.authoring.world_intelligence_service import (
    AuthorityPolicy,
    BehaviorGraph,
    BehaviorNode,
    CharacterGroup,
    DialogueAct,
    DialogueSet,
    NavEdge,
    NavigationGraph,
    NavNode,
    PerceptionSensor,
    SmartObjectDefinition,
    SmartObjectSlot,
)
from tech_connector.game_engine.runtime.world_intelligence_runtime_service import (
    CrowdAgentIntent,
    PerceivedStimulus,
    SmartObjectReservationManager,
    apply_perception_receipt,
    authorize_world_mutation,
    choose_dialogue_act,
    evaluate_behavior_graph,
    find_navigation_path,
    sense_stimuli,
    simulate_group_tick,
    solve_crowd_steering,
)


def _world() -> tuple[CharacterWorldAsset, CharacterState]:
    character = CharacterState(
        CharacterProfile("mara", "Mara", parameters={}, traits={"courage": 0.8}),
        blackboard={"position": (0.0, 0.0, 0.0), "forward": (0.0, 0.0, 1.0)},
    )
    return CharacterWorldAsset(characters={"mara": character}, world_facts={"alarm": True}), character


def test_perception_respects_fov_occlusion_and_creates_expiring_beliefs() -> None:
    _world_asset, character = _world()
    sensor = PerceptionSensor("eyes", "visual", range=10.0, field_of_view=90.0, memory_duration=4.0)
    stimuli = (
        PerceivedStimulus("front", "visual", "visitor", (0.0, 0.0, 5.0), timestamp=2.0),
        PerceivedStimulus("behind", "visual", "threat", (0.0, 0.0, -2.0), timestamp=2.0),
    )
    receipt = sense_stimuli(character, (sensor,), stimuli)
    observations = {row.stimulus_id: row for row in receipt.observations}

    assert observations["front"].detected
    assert "outside_field_of_view" in observations["behind"].blocked_by
    assert apply_perception_receipt(character, receipt, stimuli, (sensor,)) == 1
    assert character.memories[0].subject == "visitor"
    assert character.memories[0].expires_at == 6.0


def test_navigation_is_deterministic_and_honors_traversal_requirements() -> None:
    graph = NavigationGraph(
        "town",
        nodes={key: NavNode(key, position) for key, position in {
            "a": (0.0, 0.0, 0.0), "b": (1.0, 0.0, 0.0), "c": (2.0, 0.0, 0.0), "d": (0.0, 0.0, 2.0)
        }.items()},
        edges=[
            NavEdge("a", "b", 1.0), NavEdge("b", "c", 1.0, required_tags=("door_access",)),
            NavEdge("a", "d", 2.0), NavEdge("d", "c", 2.0),
        ],
    )

    public = find_navigation_path(graph, "a", "c")
    authorized = find_navigation_path(graph, "a", "c", traversal_tags=("door_access",))
    assert public.path == ("a", "d", "c") and public.total_cost == 4.0
    assert authorized.path == ("a", "b", "c") and authorized.total_cost == 2.0


def test_smart_object_reservations_enforce_capacity_tags_expiry_and_ownership() -> None:
    bench = SmartObjectDefinition(
        "bench",
        slots={"left": SmartObjectSlot("left", ("sit",), capacity=1, required_character_tags=("adult",))},
    )
    manager = SmartObjectReservationManager()
    reservation = manager.reserve(bench, character_id="mara", action="sit", character_tags=("adult",), now=1.0, duration=2.0)
    with pytest.raises(PermissionError):
        manager.reserve(bench, character_id="lee", action="sit", character_tags=("adult",), now=2.0)
    with pytest.raises(PermissionError):
        manager.release(reservation.reservation_id, character_id="lee")
    replacement = manager.reserve(bench, character_id="lee", action="sit", character_tags=("adult",), now=3.0)
    assert replacement.character_id == "lee"
    assert SmartObjectReservationManager.from_dict(manager.to_dict()).reservations


def test_behavior_dialogue_group_and_authority_remain_authored_and_explainable() -> None:
    world, character = _world()
    graph = BehaviorGraph(
        "guard",
        "root",
        nodes={
            "root": BehaviorNode("root", "utility_selector", children=("flee", "investigate")),
            "flee": BehaviorNode("flee", "action", conditions=({"path": "character.traits.courage", "operator": "less", "value": 0.3},), action_id="flee", utility=1.0),
            "investigate": BehaviorNode("investigate", "action", conditions=({"path": "world.alarm", "value": True},), action_id="investigate", utility=0.7, parameter_weights={"courage": 0.5}),
        },
    )
    behavior = evaluate_behavior_graph(graph, character, world)
    dialogue = DialogueSet(
        "guard_lines",
        acts={
            "warn": DialogueAct("warn", "warn", "Stay back.", conditions=({"path": "world.alarm", "value": True},), effects={"visitor.warned": True}, allow_model_realization=False)
        },
    )
    line = choose_dialogue_act(dialogue, character, world, model_realizations={"warn": "Improvised unsafe replacement"})
    group = CharacterGroup("guards", members=["mara", "lee"], resources={"food": 10.0}, shared_facts={"consumption.food": 0.5})
    group_receipt = simulate_group_tick(group, elapsed=2.0, events=({"event_id": "win", "morale_delta": 0.2},))

    assert behavior.selected_action == "investigate"
    assert any(row["node_id"] == "flee" and row["status"] == "blocked" for row in behavior.trace)
    assert line.line == "Stay back." and not line.used_model_realization
    assert line.canonical_effects == {"visitor.warned": True}
    assert group_receipt["after"]["resources"]["food"] == 8.0
    denied = authorize_world_mutation(AuthorityPolicy(), writer="client_2", field_path="world_facts", current_revision=4, expected_revision=4)
    predicted = authorize_world_mutation(AuthorityPolicy(), writer="client_2", field_path="movement.intent", current_revision=4, expected_revision=4, predicted=True)
    conflict = authorize_world_mutation(AuthorityPolicy(), writer="server", field_path="world_facts", current_revision=4, expected_revision=3)
    assert not denied.accepted and predicted.accepted and predicted.revision_after == 4
    assert not conflict.accepted and conflict.reason == "revision_conflict"


def test_crowd_steering_and_world_intelligence_round_trip_deterministically() -> None:
    world, _character = _world()
    world.intelligence.sensors["mara"] = [PerceptionSensor("ears", "audio")]
    world.intelligence.groups["guards"] = CharacterGroup("guards", ["mara"])
    restored = CharacterWorldAsset.from_dict(world.to_dict())
    intents = (
        CrowdAgentIntent("a", (0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        CrowdAgentIntent("b", (0.2, 0.0, 0.0), (10.0, 0.0, 0.0)),
    )
    first = solve_crowd_steering(intents)
    second = solve_crowd_steering(reversed(intents))

    assert restored.intelligence.sensors["mara"][0].sensor_id == "ears"
    assert restored.intelligence.groups["guards"].members == ["mara"]
    assert first == second
    assert first[0].avoided == ("b",)
