"""Release legal-surface and staged-inventory hardening tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tech_connector.packaging.release_gate import (
    validate_github_root_surface,
    validate_legal_surface,
    validate_production_legal_approval,
    validate_production_source_access,
)
from tech_connector.packaging.smoke_test_package import verify_package_manifest
from tech_connector.packaging.stage_package import write_package_manifest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PACKAGE_ROOT.parent


def test_current_legal_surface_contains_required_source_available_terms() -> None:
    assert validate_legal_surface(TOOLS_ROOT) == []
    assert validate_github_root_surface(TOOLS_ROOT) == []


def test_public_github_surface_requires_activation_and_forbids_launcher_bypass() -> None:
    public_readme = (TOOLS_ROOT / "README.md").read_text(encoding="utf-8")
    connector_readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    launcher = (
        PACKAGE_ROOT / "Start_The_Entire_World_Tech_Connector.bat"
    ).read_text(encoding="utf-8-sig")

    assert "Account activation is required" in public_readme
    assert "does not create an activated license" in public_readme
    assert "Download, account, and activation" in connector_readme
    assert "does not itself activate Tech Connector" in connector_readme
    assert "TECH_CONNECTOR_DEV_LICENSE_BYPASS=1" not in launcher.replace(" ", "")
    assert "requires account sign-in, license acceptance, and activation" in launcher


def test_source_access_model_defines_public_monorepo_and_gated_execution() -> None:
    source_access = (
        PACKAGE_ROOT / "docs" / "SOURCE_ACCESS_MODEL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(source_access.split())

    assert "publicly source-available" in normalized
    assert "complete public monorepo" in normalized
    assert "Official Tools Bundle is one product" in normalized
    assert "official_tools_bundle" in normalized
    assert "own project directories" in normalized
    assert "cannot be remotely erased" in normalized
    assert "GitHub App" in normalized


def test_legal_surface_rejects_an_unrestricted_license_replacement(tmp_path) -> None:
    package = tmp_path / "tech_connector"
    package.mkdir()
    (package / "LICENSE.md").write_text("MIT License\n", encoding="utf-8")
    (package / "README.md").write_text("Open source software\n", encoding="utf-8")

    failures = validate_legal_surface(tmp_path)

    assert any("source-available" in failure for failure in failures)
    assert any("not-open-source" in failure for failure in failures)
    assert any("profit threshold" in failure for failure in failures)
    assert any("PRIVACY.md" in failure for failure in failures)


def test_production_gate_rejects_unapproved_privacy_draft(tmp_path) -> None:
    package = tmp_path / "tech_connector"
    package.mkdir()
    (package / "PRIVACY.md").write_text(
        "Release status: pre-release draft — counsel approval required\n",
        encoding="utf-8",
    )

    assert validate_production_legal_approval(tmp_path) == [
        "production privacy notice has not been marked approved by counsel"
    ]


def test_production_gate_accepts_counsel_approved_privacy_notice(tmp_path) -> None:
    package = tmp_path / "tech_connector"
    package.mkdir()
    (package / "PRIVACY.md").write_text(
        "Release status: approved\n",
        encoding="utf-8",
    )

    assert validate_production_legal_approval(tmp_path) == []


def test_production_gate_accepts_verified_public_monorepo_distribution() -> None:
    assert validate_production_source_access(TOOLS_ROOT) == []


def test_production_gate_accepts_verified_public_monorepo_contract(tmp_path) -> None:
    config = tmp_path / "tech_connector" / "config"
    config.mkdir(parents=True)
    (config / "source_access.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "status": "operational_verified",
                "distribution_model": "public_complete_tools_monorepo",
                "public_repository_contains_complete_source": True,
                "public_repository_contains_core_source": True,
                "official_tools_source_public": True,
                "official_tools_execution_entitlement_required": True,
                "private_services_excluded": True,
                "verified_at": "2026-09-28T20:00:00Z",
                "review_reference": "launch-review-2026-09",
            }
        ),
        encoding="utf-8",
    )

    assert validate_production_source_access(tmp_path) == []


def test_staged_manifest_verifies_before_code_import(tmp_path) -> None:
    package = tmp_path / "stage"
    module = package / "tech_connector" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("VERSION = 1\n", encoding="utf-8")
    write_package_manifest(package, "reasoning-runtime")

    verify_package_manifest(package)


def test_staged_manifest_rejects_modified_and_unexpected_files(tmp_path) -> None:
    package = tmp_path / "stage"
    module = package / "tech_connector" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("VERSION = 1\n", encoding="utf-8")
    write_package_manifest(package, "reasoning-runtime")
    module.write_text("VERSION = 2\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest verification"):
        verify_package_manifest(package)

    module.write_text("VERSION = 1\n", encoding="utf-8")
    (package / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="do not match"):
        verify_package_manifest(package)
