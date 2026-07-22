from __future__ import annotations

from tech_connector.services.unreal.contexts.graph_asset_context import GraphAssetContextBuilder


class MotionMatchingContextBuilder(GraphAssetContextBuilder):
    def __init__(self, scanner):
        super().__init__(
            scanner,
            category="motion_matching",
            label="Motion Matching asset",
            followups=[
                "Inspect linked Pose Search databases and schemas.",
                "Check source animations, tags, and skeleton compatibility.",
                "Route to stronger reasoning for changes spanning chooser/database/gameplay code.",
            ],
        )
