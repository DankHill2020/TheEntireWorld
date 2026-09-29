"""Public/private source distribution boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tech_connector.packaging.source_distribution import (
    ALLOWED_SUFFIXES,
    PUBLIC_MANIFEST_NAME,
    load_public_repository_manifest,
    stage_public_landing,
    validate_public_landing,
)


def test_public_landing_is_allowlisted_and_contains_no_application_source(tmp_path) -> None:
    output = stage_public_landing(tmp_path / "public")

    assert (output / "README.md").is_file()
    assert (output / "LICENSE").is_file()
    assert (output / "tools/tech_connector/docs/SOURCE_ACCESS_MODEL.md").is_file()
    assert not any(path.suffix == ".py" for path in output.rglob("*"))
    assert all(
        path.suffix.casefold() in ALLOWED_SUFFIXES
        for path in output.rglob("*")
        if path.is_file() and path.name != PUBLIC_MANIFEST_NAME
    )
    manifest = json.loads((output / PUBLIC_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["file_count"] == len(load_public_repository_manifest())
    assert all("tech_connector/app/" not in row["path"] for row in manifest["files"])


def test_public_landing_rejects_any_unallowlisted_file(tmp_path) -> None:
    output = stage_public_landing(tmp_path / "public")
    (output / "unexpected.py").write_text("print('protected')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="differs from its allowlist"):
        validate_public_landing(output)


def test_public_manifest_rejects_path_traversal_and_duplicate_targets(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {"source": "../secret", "target": "README.md"},
                    {"source": "README.md", "target": "README.md"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe repository-relative"):
        load_public_repository_manifest(path)


def test_source_access_grant_schema_keeps_identity_acceptance_and_version_links() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "schemas"
        / "source_access_grant.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    required = set(schema["required"])
    assert {
        "account_id",
        "license_id",
        "product_id",
        "required_capability",
        "agreement_acceptance_id",
        "provider_user_id",
        "repository_class",
        "covered_major_versions",
        "status",
        "policy_version",
    } <= required
    assert schema["properties"]["provider"]["const"] == "github"
    assert schema["properties"]["product_id"]["const"] == "official_tools_bundle"
    assert "major_version" in schema["properties"]["repository_class"]["enum"]
