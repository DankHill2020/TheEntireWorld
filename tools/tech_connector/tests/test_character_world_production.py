from __future__ import annotations

import json
import time

import pytest

from tech_connector.game_engine.authoring.character_intelligence_service import (
    CharacterParameterSpec,
    CharacterProfile,
    CharacterState,
    CharacterWorldAsset,
)
from tech_connector.game_engine.authoring.world_intelligence_service import (
    AuthorityPolicy,
    BehaviorGraph,
    BehaviorNode,
    NavEdge,
    NavigationGraph,
    NavNode,
)
from tech_connector.game_engine.runtime.world_intelligence_runtime_service import (
    CrowdAgentIntent,
    authorize_world_mutation,
    evaluate_behavior_graph,
    find_navigation_path,
    solve_crowd_steering,
)


def _character(identifier: str) -> CharacterState:
    profile = CharacterProfile(
        identifier,
        identifier,
        parameter_specs={"courage": CharacterParameterSpec("courage", default=0.5)},
        parameters={"courage": 0.75},
        traits={"alertness": 0.8},
    )
    return CharacterState(profile, blackboard={"position": (0.0, 0.0, 0.0)})


def test_large_character_world_runtime_and_readback_are_bounded() -> None:
    world = CharacterWorldAsset(
        characters={f"agent_{index}": _character(f"agent_{index}") for index in range(1_000)},
        world_facts={"alarm": True},
    )
    node_count = 5_000
    navigation = NavigationGraph(
        "city",
        nodes={f"n{index}": NavNode(f"n{index}", (float(index), 0.0, 0.0)) for index in range(node_count)},
        edges=[NavEdge(f"n{index}", f"n{index + 1}", 1.0) for index in range(node_count - 1)],
    )
    world.intelligence.navigation_graphs[navigation.graph_id] = navigation
    behavior = BehaviorGraph(
        "alert",
        "root",
        nodes={
            "root": BehaviorNode("root", "utility_selector", children=("investigate",)),
            "investigate": BehaviorNode(
                "investigate", "action", conditions=({"path": "world.alarm", "value": True},),
                action_id="investigate", utility=1.0,
            ),
        },
    )

    started = time.perf_counter()
    decisions = [evaluate_behavior_graph(behavior, character, world) for character in world.characters.values()]
    route = find_navigation_path(navigation, "n0", f"n{node_count - 1}")
    crowd = solve_crowd_steering(
        CrowdAgentIntent(f"crowd_{index}", (index * 0.25, 0.0, 0.0), (100.0, 0.0, 0.0))
        for index in range(250)
    )
    serialized = json.dumps(world.to_dict(), sort_keys=True)
    restored = CharacterWorldAsset.from_dict(json.loads(serialized))
    elapsed = time.perf_counter() - started

    assert all(item.selected_action == "investigate" for item in decisions)
    assert len(route.path) == node_count and route.total_cost == node_count - 1
    assert len(crowd) == 250
    assert json.dumps(restored.to_dict(), sort_keys=True) == serialized
    assert elapsed < 5.0


def test_character_world_failures_are_safe_and_authority_is_explicit() -> None:
    world = CharacterWorldAsset(characters={"hero": _character("hero")})
    hero = world.characters["hero"]
    before = json.dumps(world.to_dict(), sort_keys=True)

    cyclic = BehaviorGraph(
        "cycle", "a",
        nodes={"a": BehaviorNode("a", "sequence", children=("b",)), "b": BehaviorNode("b", "sequence", children=("a",))},
    )
    decision = evaluate_behavior_graph(cyclic, hero, world)
    missing_route = find_navigation_path(NavigationGraph("empty"), "missing", "other")
    denied = authorize_world_mutation(
        AuthorityPolicy(), writer="untrusted_client", field_path="world_facts", current_revision=7, expected_revision=7,
    )
    conflict = authorize_world_mutation(
        AuthorityPolicy(), writer="server", field_path="world_facts", current_revision=7, expected_revision=6,
    )
    with pytest.raises(KeyError, match="Unknown character parameter"):
        hero.profile.set_parameter("missing", 1.0)
    with pytest.raises(ValueError, match="schema"):
        CharacterWorldAsset.from_dict({"schema": "corrupt"})

    assert not decision.selected_action and any(row.get("reason") == "cycle" for row in decision.trace)
    assert missing_route.blocked_reason == "unknown_endpoint"
    assert not denied.accepted and denied.revision_after == 7
    assert not conflict.accepted and conflict.reason == "revision_conflict"
    assert json.dumps(world.to_dict(), sort_keys=True) == before
