"""Release legal-surface and staged-inventory hardening tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tech_connector.packaging.release_gate import (
    sensitive_artifacts,
    validate_github_root_surface,
    validate_legal_surface,
    validate_production_legal_approval,
    validate_production_readiness,
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
    normalized_connector_readme = " ".join(connector_readme.split())
    launcher = (
        PACKAGE_ROOT / "Start_The_Entire_World_Tech_Connector.bat"
    ).read_text(encoding="utf-8-sig")

    assert "Account activation is required" in public_readme
    assert "does not create an activated license" in public_readme
    assert "Download, account, and activation" in connector_readme
    assert "does not itself activate Tech Connector" in connector_readme
    assert (
        "complete first-party Official Tools Bundle source are publicly visible"
        in normalized_connector_readme
    )
    assert "delivered separately through an account-gated" not in connector_readme
    assert "TECH_CONNECTOR_DEV_LICENSE_BYPASS=1" not in launcher.replace(" ", "")
    assert "requires account sign-in, license acceptance, and activation" in launcher


def test_publication_inventory_rejects_private_backend_and_generated_state(tmp_path) -> None:
    private_service = tmp_path / ".private_backend" / "server.py"
    generated_database = tmp_path / "knowledge" / "index.sqlite"
    generated_lock = tmp_path / "knowledge" / "index.build.lock"
    bytecode = tmp_path / "__pycache__" / "module.pyc"
    for path in (private_service, generated_database, generated_lock, bytecode):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"local-only")

    failures = sensitive_artifacts(
        [private_service, generated_database, generated_lock, bytecode]
    )

    assert set(failures) == {
        str(private_service), str(generated_database), str(generated_lock), str(bytecode)
    }


def test_publication_inventory_rejects_secret_files_but_allows_env_templates(tmp_path) -> None:
    environment_secret = tmp_path / ".env.production"
    terraform_state = tmp_path / "production.tfstate"
    private_key = tmp_path / "unexpected.txt"
    environment_template = tmp_path / ".env.example"
    environment_secret.write_text("TOKEN=secret\n", encoding="utf-8")
    terraform_state.write_text("{}\n", encoding="utf-8")
    private_key.write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n", encoding="utf-8"
    )
    environment_template.write_text("TOKEN=replace-me\n", encoding="utf-8")

    failures = sensitive_artifacts(
        [environment_secret, terraform_state, private_key, environment_template]
    )

    assert set(failures) == {
        str(environment_secret), str(terraform_state), str(private_key)
    }


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

    failures = validate_production_legal_approval(tmp_path)
    assert "production privacy notice has not been marked approved by counsel" in failures
    assert "production Community project terms document is missing" in failures


def test_production_gate_accepts_counsel_approved_privacy_notice(tmp_path) -> None:
    package = tmp_path / "tech_connector"
    package.mkdir()
    (package / "LICENSE.md").write_text(
        "Release status: approved\n",
        encoding="utf-8",
    )
    (package / "PRIVACY.md").write_text(
        "Release status: approved\n",
        encoding="utf-8",
    )
    (package / "COMMUNITY_PROJECT_TERMS.md").write_text(
        "Release status: approved\n",
        encoding="utf-8",
    )
    (package / "INDIE_LICENSE_TERMS.md").write_text(
        "Release status: approved\n",
        encoding="utf-8",
    )
    (package / "ENTERPRISE_LICENSE_TERMS.md").write_text(
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


def test_current_production_readiness_stays_fail_closed_until_external_controls_are_verified() -> None:
    failures = validate_production_readiness(TOOLS_ROOT)
    assert any("legal_and_privacy" in failure for failure in failures)
    assert any("entitlement_signing_key" in failure for failure in failures)
    assert "production readiness has not been approved for production" in failures


def test_production_readiness_requires_evidence_for_every_control(tmp_path) -> None:
    config = tmp_path / "tech_connector" / "config"
    config.mkdir(parents=True)
    operations = tmp_path / "tech_connector" / "docs" / "operations"
    operations.mkdir(parents=True)
    names = {
        "legal_and_privacy", "production_backend", "entitlement_signing_key",
        "payments_and_tax", "signed_installers",
        "monitoring_and_incident_response", "backups_and_restore",
        "support_operations",
    }
    controls = {}
    for name in names:
        runbook = operations / f"{name}.md"
        runbook.write_text(f"# {name}\n", encoding="utf-8")
        controls[name] = {
            "status": "verified", "owner": "release-owner@example.com",
            "verified_at": "2026-09-29T12:00:00Z",
            "evidence_reference": f"change/{name}/123",
            "runbook": f"tech_connector/docs/operations/{name}.md",
        }
    (config / "production_readiness.json").write_text(json.dumps({
        "schema_version": 1, "status": "approved_for_production",
        "release_approval_reference": "release/2026.1/approval",
        "controls": controls,
    }), encoding="utf-8")
    assert validate_production_readiness(tmp_path) == []

    controls["signed_installers"] = {
        **controls["signed_installers"],
        "status": "pending_external",
        "owner": "",
        "verified_at": "",
        "evidence_reference": "",
    }
    (config / "production_readiness.json").write_text(json.dumps({
        "schema_version": 1,
        "status": "approved_for_signing_candidate",
        "signing_candidate_approval_reference": "release/2026.1/signing-candidate",
        "release_approval_reference": "",
        "controls": controls,
    }), encoding="utf-8")
    assert validate_production_readiness(
        tmp_path,
        pending_controls=frozenset({"signed_installers"}),
        required_status="approved_for_signing_candidate",
        approval_reference_field="signing_candidate_approval_reference",
    ) == []
    final_failures = validate_production_readiness(tmp_path)
    assert any("signed_installers" in failure for failure in final_failures)
    assert "production readiness has not been approved for production" in final_failures


def test_production_readiness_rejects_vague_or_unreviewable_evidence(tmp_path) -> None:
    config = tmp_path / "tech_connector" / "config"
    config.mkdir(parents=True)
    names = {
        "legal_and_privacy", "production_backend", "entitlement_signing_key",
        "payments_and_tax", "signed_installers",
        "monitoring_and_incident_response", "backups_and_restore",
        "support_operations",
    }
    controls = {
        name: {
            "status": "verified", "owner": "owner",
            "verified_at": "last Tuesday",
            "evidence_reference": "looks good",
            "runbook": "../outside.md",
        }
        for name in names
    }
    (config / "production_readiness.json").write_text(json.dumps({
        "schema_version": 1, "status": "approved_for_production",
        "release_approval_reference": "approved in chat",
        "controls": controls,
    }), encoding="utf-8")

    failures = validate_production_readiness(tmp_path)
    assert any("ISO-8601 UTC" in failure for failure in failures)
    assert any("unsafe evidence_reference" in failure for failure in failures)
    assert any("outside operations" in failure for failure in failures)
    assert "production readiness has an unsafe release approval reference" in failures


def test_external_signing_assembly_is_fail_closed_and_verifies_frozen_binaries() -> None:
    script = (
        PACKAGE_ROOT / "packaging" / "windows" / "assemble_signed_installer.ps1"
    ).read_text(encoding="utf-8")
    normalized = " ".join(script.split())
    assert '"--source-root", $repoRoot, "--production"' in normalized
    assert "--signed-installer-candidate" in script
    assert "[switch]$SigningCandidate" in script
    assert "verify_windows_signatures.ps1" in script
    assert "-Recurse -ExpectedPublisher $ExpectedPublisher" in normalized
    assert normalized.index("verify_windows_signatures.ps1") < normalized.index("& $iscc")


def test_protected_signing_workflow_scans_smokes_and_keeps_candidate_private() -> None:
    workflow = (
        PACKAGE_ROOT / "packaging" / "github" / "signed-windows-release.yml"
    ).read_text(encoding="utf-8")
    assert "--production --signed-installer-candidate" in workflow
    assert "-SigningCandidate" in workflow
    assert "MpCmdRun.exe" in workflow
    assert "test_signed_installer.ps1" in workflow
    assert "release-manifest.json" in workflow
    assert "signed_installer_candidate_not_public_release" in workflow
    assert "actions/upload-artifact" in workflow
    assert "gh release" not in workflow.casefold()

    smoke = (
        PACKAGE_ROOT / "packaging" / "windows" / "test_signed_installer.ps1"
    ).read_text(encoding="utf-8")
    normalized = " ".join(smoke.split())
    assert "verify_windows_signatures.ps1" in smoke
    assert "foreach ($pass in 1..2)" in smoke
    assert "Start-Process -FilePath $application" in normalized
    assert "unins000.exe" in smoke
    assert "StartsWith($resolvedTemp" in smoke


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
