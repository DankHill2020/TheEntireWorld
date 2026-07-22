from __future__ import annotations

from typing import Any, Dict

from tech_connector.services.unreal.contexts.common import basic_asset_context


class LevelContextBuilder:
    def __init__(self, scanner):
        self.scanner = scanner

    def build(self, asset_path: str, focus: str = "level") -> Dict[str, Any]:
        level_name = self.scanner.get_loaded_level()
        selected_actors = self.scanner.get_selected_actors()
        result = basic_asset_context(asset_path or level_name, "level", focus=focus)
        result["loaded_level"] = level_name
        result["selected_actors"] = selected_actors[:20]
        result["selected_actor_count"] = len(selected_actors)
        result["summary"] = (
            f"Level {level_name} | selected actors: {len(selected_actors)}"
        )
        result["recommended_followups"] = [
            "Inspect selected actors and relevant Blueprint classes before mutation.",
            "Use targeted level/selection queries instead of full world scans for simple tasks.",
        ]
        result["warnings"] = []
        return result
