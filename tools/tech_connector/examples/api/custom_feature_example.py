"""Register an independently invokable studio API feature."""

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
    }


def main() -> None:
    api = create_api()
    api.features.register(
        APIFeatureDescriptor(
            feature_id="studio.asset_review",
            category="studio",
            version="1.0",
            description="Review an asset against studio rules.",
            operations=("review",),
            permissions=("project_read",),
            source=f"{__name__}.review_asset",
            operation_schemas={
                "review": {
                    "input": {
                        "asset_path": "string",
                        "ruleset": "string",
                    },
                    "output": "object",
                }
            },
        ),
        {"review": review_asset},
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

