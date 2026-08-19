"""Compatibility imports for the headless world-intelligence command runtime."""

from tech_connector.game_engine.runtime.world_intelligence_command_service import (
    WORLD_AI_AUTHORING_COMMANDS,
    WorldIntelligenceRuntimeState,
    execute_gameplay_experience_command,
    execute_world_intelligence_command,
)

__all__ = [
    "WORLD_AI_AUTHORING_COMMANDS",
    "WorldIntelligenceRuntimeState",
    "execute_gameplay_experience_command",
    "execute_world_intelligence_command",
]
