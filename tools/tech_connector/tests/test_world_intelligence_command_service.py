from __future__ import annotations

from tech_connector.game_engine.authoring.character_intelligence_service import CharacterProfile, CharacterState, CharacterWorldAsset
from tech_connector.game_engine.integration.world_intelligence_command_service import (
    WorldIntelligenceRuntimeState,
    execute_gameplay_experience_command,
    execute_world_intelligence_command,
)
from tech_connector.game_engine.integration.adaptive_scene_command_service import ADAPTIVE_SCENE_COMMANDS
from tech_connector.game_engine.integration.capability_maturity_service import assess_capability
from tech_connector.game_engine.runtime.tc_engine_api import TCEngineAPI, engine_access_contract


def test_commands_author_and_run_a_complete_character_world_slice() -> None:
    world = CharacterWorldAsset(
        characters={"guard": CharacterState(CharacterProfile("guard", "Guard", faction_tags={"town"}, traits={"courage": 0.8}))},
        world_facts={"alarm": True},
    )
    world.characters["guard"].blackboard.update({"position": (0.0, 0.0, 0.0), "forward": (0.0, 0.0, 1.0)})
    runtime = WorldIntelligenceRuntimeState()

    execute_world_intelligence_command(world, runtime, "world_ai.add_sensor", {
        "character_id": "guard", "sensor_id": "eyes", "modality": "visual", "range": 20.0,
    })
    execute_world_intelligence_command(world, runtime, "world_ai.add_navigation_graph", {
        "graph_id": "town", "nodes": {
            "gate": {"position": [0, 0, 0]}, "square": {"position": [5, 0, 0]},
        }, "edges": [{"source": "gate", "target": "square", "cost": 2.0}],
    })
    execute_world_intelligence_command(world, runtime, "world_ai.add_smart_object", {
        "object_id": "gate_controls", "slots": {
            "panel": {"actions": ["operate"], "required_character_tags": ["town"]},
        },
    })
    execute_world_intelligence_command(world, runtime, "world_ai.add_behavior_graph", {
        "graph_id": "guard_duty", "root_node": "respond", "nodes": {
            "respond": {"kind": "action", "action_id": "secure_gate", "conditions": [{"path": "world.alarm", "value": True}]},
        },
    })
    execute_world_intelligence_command(world, runtime, "world_ai.add_dialogue_set", {
        "set_id": "guard_lines", "acts": {
            "warning": {"intent": "warn", "authored_text": "The gate is closed.", "priority": 1.0},
        },
    })
    execute_world_intelligence_command(world, runtime, "world_ai.add_group", {
        "group_id": "town_guard", "members": ["guard"], "resources": {"supplies": 10.0},
    })

    perceived = execute_world_intelligence_command(world, runtime, "world_ai.sense", {
        "character_id": "guard", "stimuli": [{"id": "visitor", "modality": "visual", "source_id": "player", "position": [0, 0, 4]}],
    })
    path = execute_world_intelligence_command(world, runtime, "world_ai.find_path", {"graph_id": "town", "start": "gate", "goal": "square"})
    reservation = TCEngineAPI.execute_world_intelligence(
        world, runtime, "world_ai.reserve_smart_object", character_id="guard", object_id="gate_controls", action="operate"
    )
    behavior = execute_world_intelligence_command(world, runtime, "world_ai.evaluate_behavior", {"character_id": "guard", "graph_id": "guard_duty"})
    dialogue = execute_world_intelligence_command(world, runtime, "world_ai.choose_dialogue", {"character_id": "guard", "set_id": "guard_lines"})

    assert perceived["memories_applied"] == 1
    assert path["navigation"]["path"] == ("gate", "square")
    assert reservation["reservation"]["slot_id"] == "panel"
    assert behavior["behavior"]["selected_action"] == "secure_gate"
    assert dialogue["dialogue"]["line"] == "The gate is closed."
    assert CharacterWorldAsset.from_dict(world.to_dict()).intelligence.behavior_graphs["guard_duty"]
    assert "world_ai.sense" in engine_access_contract()["world_intelligence"]["commands"]
    assert assess_capability(ADAPTIVE_SCENE_COMMANDS["world_ai.sense"]).verified_maturity == "interactive"


def test_gameplay_commands_compose_validate_and_budget_a_game_without_genre_branching() -> None:
    profile, configured = execute_gameplay_experience_command(None, "gameplay.configure_experience", {
        "profile_id": "space_school",
        "game_types": ["realistic_simulation", "educational", "sandbox"],
        "learning_objectives": [{"id": "gravity", "description": "Predict gravity", "evidence": ["prediction"]}],
    })
    _profile, validation = execute_gameplay_experience_command(profile, "gameplay.validate_experience", {})
    _profile, budget = execute_gameplay_experience_command(profile, "gameplay.runtime_budget", {"target": "web"})
    profile, visuals = execute_gameplay_experience_command(profile, "gameplay.set_visual_style", {
        "style": "8-bit", "world_layout": "2.5d", "pixel_canvas": [320, 180],
    })
    _profile, visual_plan = execute_gameplay_experience_command(profile, "gameplay.preview_visual_plan", {"target": "web"})

    assert configured["game_experience"]["axes"]["learning"] == 1.0
    assert validation["game_experience_validation"]["valid"]
    assert budget["gameplay_runtime_budget"]["target"] == "web"
    assert visuals["visual_settings"]["title"] == "8-Bit Pixel Art in 2.5D"
    assert visual_plan["visual_plan"]["simulation_contract"] == "unchanged"
