"""Add studio context to the default Tech Connector reasoning runtime."""

from __future__ import annotations

import json

from reasoning_runtime.adapters.context_adapter import (
    ContextAdapter,
    InteractionSurface,
)
from tech_connector.api import create_api


class StudioPublishContext(ContextAdapter):
    """Supply the active studio publish state."""

    name = "studio_publish"

    def get_active_context(self) -> dict:
        return {
            "asset_id": "character.hero",
            "publish_stage": "animation",
            "review_status": "changes_requested",
        }

    def get_interaction_surface(self) -> InteractionSurface:
        return InteractionSurface(
            kind="asset_publish_dashboard",
            supports_clarification=True,
            supports_approval=True,
        )

    def get_permission_context(self) -> dict:
        return {
            "can_read_project": True,
            "can_publish": False,
        }


class StudioRuntimePackage:
    def get_context_adapters(self) -> list[ContextAdapter]:
        return [StudioPublishContext()]


def main() -> None:
    api = create_api(runtime_packages=[StudioRuntimePackage()])
    snapshot = api.reasoning.snapshot("What publish state is active?")
    if not snapshot.ok:
        raise SystemExit(snapshot.error)

    studio_context = snapshot.result["runtime"]["context"]["studio_publish"]
    feature = api.features.get("runtime.context.studio_publish")
    print(json.dumps(studio_context, indent=2))
    print(json.dumps(feature, indent=2))


if __name__ == "__main__":
    main()
