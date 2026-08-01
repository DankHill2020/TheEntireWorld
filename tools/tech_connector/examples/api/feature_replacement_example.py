"""Replace one registered feature contract in one API instance."""

from __future__ import annotations

import json

from tech_connector.api import create_api
from tech_connector.services.api_feature_registry_service import (
    APIFeatureDescriptor,
)


def review_asset(asset_path: str = "", ruleset: str = "default") -> dict:
    return {
        "asset_path": asset_path,
        "ruleset": ruleset,
        "passed": bool(asset_path),
        "reviewer": "v1",
    }


def strict_review_asset(asset_path: str = "", ruleset: str = "default") -> dict:
    return {
        "asset_path": asset_path,
        "ruleset": ruleset,
        "passed": bool(asset_path and ruleset != "disabled"),
        "reviewer": "strict-v2",
    }


def descriptor(version: str, source: str) -> APIFeatureDescriptor:
    return APIFeatureDescriptor(
        feature_id="studio.asset_review",
        category="studio",
        version=version,
        description="Review an asset against studio rules.",
        operations=("review",),
        permissions=("project_read",),
        source=source,
    )


def main() -> None:
    api = create_api()
    api.features.register(
        descriptor("1.0", f"{__name__}.review_asset"),
        {"review": review_asset},
    )
    api.features.register(
        descriptor("2.0", f"{__name__}.strict_review_asset"),
        {"review": strict_review_asset},
        replace=True,
    )

    result = api.features.invoke(
        "studio.asset_review",
        "review",
        asset_path="/Game/Characters/SK_Hero",
        ruleset="character",
    )
    if not result.ok:
        raise SystemExit(result.error)
    print(json.dumps(result.result["value"], indent=2))


if __name__ == "__main__":
    main()
