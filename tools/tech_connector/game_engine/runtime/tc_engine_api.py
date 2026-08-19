"""Ergonomic code API for the same engine workflows exposed by UI and chat."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tech_connector.game_engine.runtime.engine_runtime_experience_service import build_engine_runtime_experience_plan
from tech_connector.game_engine.runtime.tc_effect_system_service import create_effect_world
from tech_connector.game_engine.runtime.tc_live_game_sync_service import (
    build_playtest_iteration_plan,
    publish_tcscene_save,
)
from tech_connector.game_engine.runtime.tc_simulation_runtime_service import SimulationRuntimeInstance


@dataclass
class ConfiguredRuntime:
    runtime: SimulationRuntimeInstance
    plan: dict[str, Any]

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "tech_connector.configured_runtime_receipt.v1",
            "plan": {key: value for key, value in self.plan.items() if key != "compiled_ir"},
            "deployment": self.runtime.deployment_manifest(),
        }


class TCEngineAPI:
    """Stable intent-level API; low-level technical choices remain optional."""

    @staticmethod
    def configure_runtime(
        world: Any,
        *,
        target: str = "desktop",
        goal: str = "balanced",
        quality: str = "auto",
        backend: str = "auto",
        adaptive: bool = True,
        tick_rate: int | None = None,
    ) -> ConfiguredRuntime:
        plan = build_engine_runtime_experience_plan(
            world,
            target=target,
            goal=goal,
            quality=quality,
            backend=backend,
            adaptive=adaptive,
            tick_rate=tick_rate,
        )
        selection = plan["selection"]
        if getattr(world, "effect_system", None) is not None:
            effect_quality = "high" if selection["quality"] == "photoreal" else selection["quality"]
            world.effect_system.quality = effect_quality
        runtime = SimulationRuntimeInstance(
            world,
            profile=selection["quality"],
            backend=selection["backend_requested"],
            tick_rate=selection["tick_rate"],
        )
        return ConfiguredRuntime(runtime, plan)

    @classmethod
    def create_effect(
        cls,
        preset: str,
        *,
        target: str = "desktop",
        goal: str = "balanced",
        quality: str = "auto",
        seed: int = 1,
    ) -> ConfiguredRuntime:
        source_quality = "high" if quality == "auto" else quality
        world = create_effect_world(preset, quality=source_quality, seed=seed)
        return cls.configure_runtime(world, target=target, goal=goal, quality=quality)

    @staticmethod
    def update_running_game(
        scene_document: Any,
        scene_path: str | Path,
        *,
        force_full: bool = False,
    ) -> dict[str, Any]:
        document = scene_document.to_dict() if hasattr(scene_document, "to_dict") else dict(scene_document)
        return publish_tcscene_save(document, scene_path, force_full=force_full)

    @staticmethod
    def plan_playtest(
        *,
        target: str = "desktop",
        session_mode: str = "play_in_editor",
        changed_modes: list[str] | tuple[str, ...] = (),
        session_connected: bool = False,
    ) -> dict[str, Any]:
        return build_playtest_iteration_plan(
            target=target,
            session_mode=session_mode,
            changed_modes=changed_modes,
            session_connected=session_connected,
        )

    @staticmethod
    def create_character(world: Any, profile: Any) -> Any:
        from tech_connector.game_engine.authoring.character_intelligence_service import CharacterState

        character = CharacterState(profile=profile)
        world.characters[character.character_id] = character
        return character

    @staticmethod
    def decide_character(
        world: Any,
        character_id: str,
        actions: Any,
        *,
        available_affordances: Any = (),
        now: float = 0.0,
        model_proposal: Any = None,
    ) -> Any:
        from tech_connector.game_engine.runtime.character_brain_service import choose_character_action

        character = world.characters[str(character_id)]
        return choose_character_action(
            character,
            world,
            actions,
            available_affordances=available_affordances,
            now=now,
            model_proposal=model_proposal,
        )

    @staticmethod
    def execute_world_intelligence(world: Any, runtime_state: Any, command: str, **payload: Any) -> dict[str, Any]:
        from tech_connector.game_engine.runtime.world_intelligence_command_service import execute_world_intelligence_command

        return execute_world_intelligence_command(world, runtime_state, command, payload)

    @staticmethod
    def create_game_experience(profile_id: str, game_types: Any, **options: Any) -> Any:
        from tech_connector.game_engine.authoring.game_experience_service import create_game_experience_profile

        return create_game_experience_profile(profile_id, game_types, **options)

    @staticmethod
    def validate_game_experience(profile: Any) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.game_experience_service import validate_game_experience

        return validate_game_experience(profile)

    @staticmethod
    def create_presentation(profile_id: str, visual_style: str, **options: Any) -> Any:
        from tech_connector.game_engine.authoring.presentation_profile_service import create_presentation_profile

        return create_presentation_profile(profile_id, visual_style, **options)

    @staticmethod
    def preview_presentation(profile: Any, **options: Any) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.presentation_profile_service import compile_presentation_plan

        return compile_presentation_plan(profile, **options)

    @staticmethod
    def graph_to_code(program: Any) -> str:
        from tech_connector.game_engine.authoring.engine_graph_program_service import generate_engine_graph_python

        return generate_engine_graph_python(program)

    @staticmethod
    def code_to_graph(source_code: str, previous: Any = None) -> Any:
        from tech_connector.game_engine.authoring.engine_graph_program_service import parse_engine_graph_python

        return parse_engine_graph_python(source_code, previous=previous)

    @staticmethod
    def compile_graph(program: Any) -> dict[str, Any]:
        from tech_connector.game_engine.authoring.engine_graph_program_service import compile_engine_graph_manifest

        return compile_engine_graph_manifest(program)

    @staticmethod
    def execute_graph(program_or_manifest: Any, context: Any, **options: Any) -> Any:
        from tech_connector.game_engine.authoring.engine_graph_program_service import (
            EngineGraphProgram,
            compile_engine_graph_manifest,
        )
        from tech_connector.game_engine.runtime.graph_execution_service import execute_graph_manifest

        manifest = (
            compile_engine_graph_manifest(program_or_manifest)
            if isinstance(program_or_manifest, EngineGraphProgram)
            else program_or_manifest
        )
        return execute_graph_manifest(manifest, context, **options)

    @staticmethod
    def create_graph_runtime(program_or_manifest: Any, context: Any, **options: Any) -> Any:
        from tech_connector.game_engine.authoring.engine_graph_program_service import (
            EngineGraphProgram,
            compile_engine_graph_manifest,
        )
        from tech_connector.game_engine.runtime.graph_instance_service import GraphRuntimeInstance

        manifest = (
            compile_engine_graph_manifest(program_or_manifest)
            if isinstance(program_or_manifest, EngineGraphProgram)
            else program_or_manifest
        )
        return GraphRuntimeInstance(manifest, context, **options)


engine = TCEngineAPI()


def engine_access_contract() -> dict[str, Any]:
    """Describe equivalent entry points for capability discovery and chat guidance."""
    return {
        "schema": "tech_connector.engine_access_contract.v1",
        "configure_runtime": {
            "manual": "The Entire Scene > Sim > Runtime Setup",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.configure_runtime",
            "chat": [
                "Set this effect up for a stable mobile frame rate.",
                "Configure this cloth for a high-fidelity desktop runtime.",
            ],
            "command": "engine.configure_runtime",
        },
        "live_update": {
            "manual": "The Entire Scene > Sim > Update Running Game Now",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.update_running_game",
            "chat": ["Update the running game with my scene changes."],
            "command": "engine.live_update_scene",
        },
        "playtest": {
            "manual": "Automatic update on scene save",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.plan_playtest",
            "chat": ["Use the fastest route to playtest this on a connected console."],
            "command": "engine.plan_playtest",
        },
        "deformation": {
            "manual": "The Entire Scene > Skin > Paint Selected Deformer Influence / Add Jiggle",
            "api": "tech_connector.game_engine.deformation",
            "chat": [
                "Add jiggle after the selected skin cluster and let me paint its influence.",
                "Paint simulation drive around this region and preserve the rest of the mesh.",
            ],
            "commands": ["deformation.add_jiggle", "deformation.add_secondary_motion_preset", "deformation.paint_influence", "simulation.add_effect_jiggle"],
        },
        "characters": {
            "manual": "The Entire Scene > Characters",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.create_character / decide_character",
            "chat": [
                "Create a cautious guard who values duty but distrusts the player.",
                "Explain why this character chose its current action.",
            ],
            "commands": [
                "characters.create", "characters.set_parameter", "characters.add_rule",
                "characters.add_objective", "characters.set_relationship",
                "characters.record_memory", "characters.choose_action",
                "narrative.set_world_fact", "narrative.add_beat", "narrative.select_beat",
            ],
        },
        "world_intelligence": {
            "manual": "The Entire Scene > Characters",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.execute_world_intelligence",
            "chat": [
                "Give this guard sight and hearing, then make the town gate reservable.",
                "Explain the route and behavior branch this character selected.",
            ],
            "commands": [
                "world_ai.add_sensor", "world_ai.add_navigation_graph", "world_ai.add_smart_object",
                "world_ai.add_behavior_graph", "world_ai.add_dialogue_set", "world_ai.add_group",
                "world_ai.sense", "world_ai.find_path", "world_ai.reserve_smart_object",
                "world_ai.evaluate_behavior", "world_ai.choose_dialogue", "world_ai.tick_group",
                "world_ai.authorize_mutation",
            ],
        },
        "game_experience": {
            "manual": "The Entire Scene > Gameplay",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.create_game_experience",
            "chat": [
                "Configure this as an educational astronomy sandbox for ages 8 to 12.",
                "Plan runtime budgets for a competitive action RPG on console.",
            ],
            "commands": [
                "gameplay.configure_experience", "gameplay.validate_experience", "gameplay.runtime_budget",
                "gameplay.set_visual_style", "gameplay.update_visual_setting",
                "gameplay.explain_visual_settings", "gameplay.preview_visual_plan",
            ],
        },
        "graph_programs": {
            "manual": "The Entire Scene > Graph View / Code View",
            "api": "tech_connector.game_engine.runtime.tc_engine_api.engine.graph_to_code / code_to_graph / compile_graph / execute_graph / create_graph_runtime",
            "status": "authoring_api_ready; interactive Graph View and chat routing are the next integration gate",
        },
    }

