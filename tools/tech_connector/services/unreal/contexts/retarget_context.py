from __future__ import annotations

from tech_connector.services.unreal.contexts.graph_asset_context import GraphAssetContextBuilder


class RetargetContextBuilder(GraphAssetContextBuilder):
    def __init__(self, scanner):
        super().__init__(
            scanner,
            category="retarget",
            label="Retarget asset",
            followups=[
                "Inspect source and target skeletons / IK rigs.",
                "Check retarget chains, profiles, and missing mappings.",
                "Validate compatibility before proposing cross-skeleton changes.",
            ],
        )
