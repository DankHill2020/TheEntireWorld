from __future__ import annotations

"""Headless command executor for world intelligence and game-experience workflows."""

from dataclasses import asdict, dataclass, field
from typing import Any

from tech_connector.game_engine.authoring.character_intelligence_service import CharacterWorldAsset
from tech_connector.game_engine.authoring.game_experience_service import (
    GameExperienceProfile,
    LearningObjective,
    build_gameplay_runtime_budget,
    create_game_experience_profile,
    validate_game_experience,
)
from tech_connector.game_engine.authoring.presentation_profile_service import (
    compile_presentation_plan,
    create_presentation_profile,
    presentation_summary,
    update_presentation_control,
    validate_presentation_profile,
)
from tech_connector.game_engine.authoring.world_intelligence_service import (
    WORLD_INTELLIGENCE_SCHEMA,
    CharacterGroup,
    PerceptionSensor,
    WorldIntelligenceAsset,
)
from tech_connector.game_engine.runtime.world_intelligence_runtime_service import (
    PerceivedStimulus,
    SmartObjectReservationManager,
    apply_perception_receipt,
    authorize_world_mutation,
    choose_dialogue_act,
    evaluate_behavior_graph,
    find_navigation_path,
    sense_stimuli,
    simulate_group_tick,
)


WORLD_AI_AUTHORING_COMMANDS = frozenset({
    "world_ai.add_sensor",
    "world_ai.add_navigation_graph",
    "world_ai.add_smart_object",
    "world_ai.add_behavior_graph",
    "world_ai.add_dialogue_set",
    "world_ai.add_group",
})


@dataclass
class WorldIntelligenceRuntimeState:
    reservations: SmartObjectReservationManager = field(default_factory=SmartObjectReservationManager)
    authority_revision: int = 0


def execute_world_intelligence_command(
    world: CharacterWorldAsset,
    runtime: WorldIntelligenceRuntimeState,
    command: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    intelligence = world.intelligence
    if command == "world_ai.add_sensor":
        character_id = str(payload.get("character_id") or "")
        _require_character(world, character_id)
        sensor = PerceptionSensor(
            sensor_id=str(payload.get("sensor_id") or f"sensor_{len(intelligence.sensors.get(character_id, ())) + 1}"),
            modality=str(payload.get("modality") or "visual"),
            range=float(payload.get("range", 25.0)),
            field_of_view=float(payload.get("field_of_view", 360.0)),
            sensitivity=float(payload.get("sensitivity", 1.0)),
            accepted_tags=tuple(payload.get("accepted_tags") or ()),
            blocked_tags=tuple(payload.get("blocked_tags") or ()),
            memory_duration=float(payload.get("memory_duration", 10.0)),
        )
        intelligence.sensors.setdefault(character_id, []).append(sensor)
        return {"sensor": asdict(sensor), "message": f"Added {sensor.modality} sensor {sensor.sensor_id} to {character_id}."}
    if command == "world_ai.add_navigation_graph":
        partial = _partial_asset("navigation_graphs", payload)
        graph = partial.navigation_graphs.popitem()[1]
        intelligence.navigation_graphs[graph.graph_id] = graph
        return {"navigation_graph": asdict(graph), "message": f"Added navigation graph {graph.graph_id}."}
    if command == "world_ai.add_smart_object":
        partial = _partial_asset("smart_objects", payload)
        item = partial.smart_objects.popitem()[1]
        intelligence.smart_objects[item.object_id] = item
        return {"smart_object": asdict(item), "message": f"Added smart object {item.object_id}."}
    if command == "world_ai.add_behavior_graph":
        partial = _partial_asset("behavior_graphs", payload)
        graph = partial.behavior_graphs.popitem()[1]
        intelligence.behavior_graphs[graph.graph_id] = graph
        return {"behavior_graph": asdict(graph), "message": f"Added behavior graph {graph.graph_id}."}
    if command == "world_ai.add_dialogue_set":
        partial = _partial_asset("dialogue_sets", payload)
        dialogue = partial.dialogue_sets.popitem()[1]
        intelligence.dialogue_sets[dialogue.set_id] = dialogue
        return {"dialogue_set": asdict(dialogue), "message": f"Added dialogue set {dialogue.set_id}."}
    if command == "world_ai.add_group":
        group = CharacterGroup(
            group_id=str(payload.get("group_id") or payload.get("id") or "group"),
            members=list(payload.get("members") or ()),
            leader=str(payload.get("leader") or ""),
            roles=dict(payload.get("roles") or {}),
            shared_facts=dict(payload.get("shared_facts") or {}),
            cohesion=float(payload.get("cohesion", 0.5)),
            morale=float(payload.get("morale", 0.5)),
            resources={str(key): float(value) for key, value in dict(payload.get("resources") or {}).items()},
        )
        unknown = sorted(set(group.members).difference(world.characters))
        if unknown:
            raise KeyError(f"Unknown group member(s): {', '.join(unknown)}")
        intelligence.groups[group.group_id] = group
        return {"group": asdict(group), "message": f"Added character group {group.group_id}."}

    character_id = str(payload.get("character_id") or "")
    if command == "world_ai.sense":
        character = _require_character(world, character_id)
        sensors = intelligence.sensors.get(character_id, [])
        stimuli = tuple(
            PerceivedStimulus(
                stimulus_id=str(row.get("stimulus_id") or row.get("id") or "stimulus"),
                modality=str(row.get("modality") or "visual"),
                source_id=str(row.get("source_id") or "world"),
                position=tuple(row.get("position") or (0.0, 0.0, 0.0)),
                strength=float(row.get("strength", 1.0)),
                tags=tuple(row.get("tags") or ()),
                value=row.get("value", True),
                timestamp=float(row.get("timestamp", payload.get("now", 0.0))),
            )
            for row in payload.get("stimuli") or ()
        )
        receipt = sense_stimuli(character, sensors, stimuli)
        applied = apply_perception_receipt(character, receipt, stimuli, sensors) if payload.get("apply", True) else 0
        return {"perception": asdict(receipt), "memories_applied": applied, "message": f"Detected {applied} stimuli for {character_id}."}
    if command == "world_ai.find_path":
        graph_id = str(payload.get("graph_id") or "")
        graph = intelligence.navigation_graphs.get(graph_id)
        if graph is None:
            raise KeyError(f"Unknown navigation graph: {graph_id}")
        receipt = find_navigation_path(
            graph,
            str(payload.get("start") or ""),
            str(payload.get("goal") or ""),
            traversal_tags=payload.get("traversal_tags") or (),
        )
        return {"navigation": asdict(receipt), "message": f"Planned {max(0, len(receipt.path) - 1)} navigation edges."}
    if command == "world_ai.reserve_smart_object":
        character = _require_character(world, character_id)
        object_id = str(payload.get("object_id") or "")
        definition = intelligence.smart_objects.get(object_id)
        if definition is None:
            raise KeyError(f"Unknown smart object: {object_id}")
        tags = set(character.profile.knowledge_tags) | set(character.profile.faction_tags) | set(payload.get("character_tags") or ())
        reservation = runtime.reservations.reserve(
            definition,
            character_id=character_id,
            action=str(payload.get("action") or ""),
            character_tags=tags,
            now=float(payload.get("now", 0.0)),
            duration=float(payload.get("duration", 5.0)),
            preferred_slot=str(payload.get("preferred_slot") or ""),
        )
        return {"reservation": asdict(reservation), "message": f"Reserved {object_id}:{reservation.slot_id} for {character_id}."}
    if command == "world_ai.evaluate_behavior":
        character = _require_character(world, character_id)
        graph_id = str(payload.get("graph_id") or "")
        graph = intelligence.behavior_graphs.get(graph_id)
        if graph is None:
            raise KeyError(f"Unknown behavior graph: {graph_id}")
        receipt = evaluate_behavior_graph(graph, character, world, now=float(payload.get("now", 0.0)))
        return {"behavior": asdict(receipt), "message": receipt.explanation}
    if command == "world_ai.choose_dialogue":
        character = _require_character(world, character_id)
        set_id = str(payload.get("set_id") or "")
        dialogue = intelligence.dialogue_sets.get(set_id)
        if dialogue is None:
            raise KeyError(f"Unknown dialogue set: {set_id}")
        receipt = choose_dialogue_act(
            dialogue,
            character,
            world,
            now=float(payload.get("now", 0.0)),
            model_realizations=dict(payload.get("model_realizations") or {}),
        )
        return {"dialogue": asdict(receipt), "message": receipt.line}
    if command == "world_ai.tick_group":
        group_id = str(payload.get("group_id") or "")
        group = intelligence.groups.get(group_id)
        if group is None:
            raise KeyError(f"Unknown character group: {group_id}")
        receipt = simulate_group_tick(group, elapsed=float(payload.get("elapsed", 0.0)), events=payload.get("events") or ())
        return {"group_tick": receipt, "message": f"Simulated group {group_id}."}
    if command == "world_ai.authorize_mutation":
        receipt = authorize_world_mutation(
            intelligence.authority,
            writer=str(payload.get("writer") or "client"),
            field_path=str(payload.get("field_path") or ""),
            current_revision=runtime.authority_revision,
            expected_revision=int(payload.get("expected_revision", runtime.authority_revision)),
            predicted=bool(payload.get("predicted", False)),
        )
        if receipt.accepted and not receipt.predicted:
            runtime.authority_revision = receipt.revision_after
        return {"authority": asdict(receipt), "message": receipt.reason}
    raise ValueError(f"No world-intelligence executor is registered for {command}.")


def execute_gameplay_experience_command(
    profile: GameExperienceProfile | None,
    command: str,
    payload: dict[str, Any],
) -> tuple[GameExperienceProfile | None, dict[str, Any]]:
    if command == "gameplay.configure_experience":
        profile = create_game_experience_profile(
            str(payload.get("profile_id") or "game"),
            payload.get("game_types") or ("sandbox",),
            axis_overrides=dict(payload.get("axis_overrides") or {}),
            simulation_overrides=dict(payload.get("simulation_overrides") or {}),
        )
        profile.audience.update(dict(payload.get("audience") or {}))
        profile.accessibility.update(dict(payload.get("accessibility") or {}))
        profile.session.update(dict(payload.get("session") or {}))
        profile.safety.update(dict(payload.get("safety") or {}))
        for row in payload.get("learning_objectives") or ():
            profile.learning_objectives.append(
                LearningObjective(
                    objective_id=str(row.get("objective_id") or row.get("id") or "objective"),
                    description=str(row.get("description") or ""),
                    evidence=tuple(row.get("evidence") or ()),
                    mastery_threshold=float(row.get("mastery_threshold", 0.8)),
                    attempts_before_scaffold=int(row.get("attempts_before_scaffold", 2)),
                    standards=tuple(row.get("standards") or ()),
                )
            )
        return profile, {"game_experience": profile.to_dict(), "message": f"Configured {profile.profile_id} for {', '.join(profile.game_types)}."}
    if command == "gameplay.set_visual_style":
        if profile is None:
            profile = create_game_experience_profile(str(payload.get("profile_id") or "game"), ("sandbox",))
        style = payload.get("visual_style", payload.get("style", "stylized_pbr"))
        world_layout = payload.get("world_layout", payload.get("dimensionality", "3d"))
        profile.presentation = create_presentation_profile(
            f"{profile.profile_id}_visuals",
            str(style),
            dimensionality=str(world_layout),
            overrides=dict(payload.get("advanced_overrides") or {}),
        )
        friendly_settings = {
            "visual_detail": payload.get("visual_detail"),
            "pixel_perfect": payload.get("pixel_perfect"),
            "pixel_canvas": payload.get("pixel_canvas"),
            "animation_feel": payload.get("animation_feel"),
            "camera_projection": payload.get("camera_projection"),
            "sprite_facing": payload.get("sprite_facing"),
        }
        for key, value in friendly_settings.items():
            if value is not None:
                update_presentation_control(profile.presentation, key, value)
        result = presentation_summary(profile.presentation)
        return profile, {"visual_settings": result, "message": result["description"]}
    if profile is None:
        raise RuntimeError("Configure a game experience before evaluating it.")
    if command == "gameplay.update_visual_setting":
        if profile.presentation is None:
            raise RuntimeError("Set a visual style before changing visual settings.")
        update_presentation_control(profile.presentation, str(payload.get("setting") or payload.get("key") or ""), payload.get("value"))
        result = presentation_summary(profile.presentation)
        return profile, {"visual_settings": result, "message": result["description"]}
    if command == "gameplay.explain_visual_settings":
        if profile.presentation is None:
            raise RuntimeError("Set a visual style before explaining visual settings.")
        result = presentation_summary(profile.presentation)
        validation = validate_presentation_profile(profile.presentation, profile)
        return profile, {"visual_settings": result, "visual_validation": validation, "message": result["description"]}
    if command == "gameplay.preview_visual_plan":
        if profile.presentation is None:
            raise RuntimeError("Set a visual style before previewing its render plan.")
        viewport = tuple(payload.get("viewport_size") or (1920, 1080))
        result = compile_presentation_plan(profile.presentation, target=str(payload.get("target") or "desktop"), viewport_size=viewport)
        return profile, {"visual_plan": result, "message": f"Prepared {profile.presentation.visual_style} for {result['target']} without changing gameplay or simulation."}
    if command == "gameplay.validate_experience":
        result = validate_game_experience(profile)
        return profile, {"game_experience_validation": result, "message": f"Found {len(result['issues'])} design issues."}
    if command == "gameplay.runtime_budget":
        result = build_gameplay_runtime_budget(profile, target=str(payload.get("target") or "desktop"))
        return profile, {"gameplay_runtime_budget": result, "message": f"Planned runtime budget for {result['target']}."}
    raise ValueError(f"No game-experience executor is registered for {command}.")


def _partial_asset(collection: str, payload: dict[str, Any]) -> WorldIntelligenceAsset:
    identifier = str(
        payload.get({
            "navigation_graphs": "graph_id",
            "smart_objects": "object_id",
            "behavior_graphs": "graph_id",
            "dialogue_sets": "set_id",
        }[collection])
        or payload.get("id")
        or collection.rstrip("s")
    )
    row = dict(payload)
    row.setdefault({
        "navigation_graphs": "graph_id",
        "smart_objects": "object_id",
        "behavior_graphs": "graph_id",
        "dialogue_sets": "set_id",
    }[collection], identifier)
    return WorldIntelligenceAsset.from_dict({"schema": WORLD_INTELLIGENCE_SCHEMA, collection: {identifier: row}})


def _require_character(world: CharacterWorldAsset, character_id: str) -> Any:
    character = world.characters.get(character_id)
    if character is None:
        raise KeyError(f"Unknown character: {character_id}")
    return character
