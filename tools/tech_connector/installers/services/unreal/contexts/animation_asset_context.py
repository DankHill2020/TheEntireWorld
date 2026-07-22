from __future__ import annotations

from tech_connector.services.unreal.contexts.graph_asset_context import GraphAssetContextBuilder


class AnimationAssetContextBuilder(GraphAssetContextBuilder):
    def __init__(
        self, scanner, category: str = "anim_sequence", label: str = "Animation asset"
    ):
        super().__init__(
            scanner,
            category=category,
            label=label,
            followups=[
                "Inspect skeleton compatibility and referenced animation data.",
                "Check notify usage, additive settings, and blend dependencies where relevant.",
                "Use stronger reasoning for multi-asset animation workflow changes.",
            ],
        )
