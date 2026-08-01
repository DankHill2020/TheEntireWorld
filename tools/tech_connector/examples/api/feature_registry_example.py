"""Discover and invoke granular Tech Connector API features."""

from __future__ import annotations

import json

from tech_connector.api import create_api


def main() -> None:
    api = create_api()
    manifest = api.features.manifest()
    print(f"Registered features: {manifest['feature_count']}")

    for feature in api.features.list(category="runtime.context"):
        print(
            feature["feature_id"],
            feature["access"],
            feature["owner_feature_id"],
            feature["operations"],
            feature["source"],
        )

    frame = api.features.invoke(
        "understanding.request_frame",
        "analyze",
        prompt="Create a Maya exporter and an Unreal importer.",
    )
    if not frame.ok:
        raise SystemExit(frame.error)
    print(json.dumps(frame.result["value"], indent=2, ensure_ascii=False))

    result = api.features.invoke(
        "runtime.context.tech_connector_context",
        "active_context",
    )
    if not result.ok:
        raise SystemExit(result.error)
    print(json.dumps(result.result["value"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
