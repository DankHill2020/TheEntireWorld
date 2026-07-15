from __future__ import annotations

from typing import Any, Dict

from services.unreal.contexts.blueprint_context import BlueprintContextBuilder
from services.unreal.contexts.common import compact_names


class AnimBlueprintContextBuilder(BlueprintContextBuilder):
    def build(self, asset_path: str, focus: str = "anim_blueprint") -> Dict[str, Any]:
        result = super().build(asset_path, focus=focus)
        result["asset_category"] = "anim_blueprint"
        graphs = list(result.get("graphs") or [])
        graph_names = [str(item.get("name") or item) for item in graphs]
        anim_graphs = [name for name in graph_names if "anim" in name.lower()]
        state_graphs = [name for name in graph_names if "state" in name.lower()]
        result["anim_graphs"] = anim_graphs[:12]
        result["state_machine_graphs"] = state_graphs[:12]
        result["summary"] = (
            f"AnimBlueprint {result.get('asset_name') or asset_path}"
            f" | anim graphs: {len(anim_graphs)}"
            f" | state graphs: {len(state_graphs)}"
            f" | functions: {len(result.get('functions') or [])}"
        )
        result["recommended_followups"] = [
            "Inspect live AnimGraph node connectivity before surgical rewrites.",
            "Validate skeleton, preview mesh, and linked animation dependencies.",
            "Use stronger model routing for state-machine or multi-graph animation edits.",
        ]
        result.setdefault("highlights", {})["anim_graphs"] = anim_graphs[:8]
        result.setdefault("highlights", {})["state_machine_graphs"] = state_graphs[:8]
        result.setdefault("highlights", {})["functions"] = compact_names(
            result.get("functions") or [], limit=8
        )
        return result
