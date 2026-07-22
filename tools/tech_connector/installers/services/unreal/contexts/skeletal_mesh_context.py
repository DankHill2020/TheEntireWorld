from __future__ import annotations

from tech_connector.services.unreal.contexts.graph_asset_context import GraphAssetContextBuilder


class SkeletalMeshContextBuilder(GraphAssetContextBuilder):
    def __init__(self, scanner):
        super().__init__(
            scanner,
            category="skeletal_mesh",
            label="Skeletal Mesh",
            followups=[
                "Inspect skeleton, physics asset, sockets, and preview animation setup.",
                "Check mesh dependencies before retargeting or animation blueprint changes.",
                "Use targeted follow-up inspection for material, socket, or skeleton questions.",
            ],
        )
