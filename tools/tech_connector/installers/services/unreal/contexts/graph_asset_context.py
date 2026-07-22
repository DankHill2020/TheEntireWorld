from __future__ import annotations

from typing import Any, Dict

from tech_connector.services.unreal.contexts.common import basic_asset_context


class GraphAssetContextBuilder:
    def __init__(
        self, scanner, category: str, label: str, followups: list[str] | None = None
    ):
        self.scanner = scanner
        self.category = category
        self.label = label
        self.followups = followups or []

    def build(self, asset_path: str, focus: str = "selection") -> Dict[str, Any]:
        result = basic_asset_context(asset_path, self.category, focus=focus)
        result["summary"] = f"{self.label}: {asset_path}"
        result["recommended_followups"] = list(self.followups)
        result["warnings"] = []
        return result
